#!/usr/bin/env python3
"""Propose `aliases` for every tag in taxonomy.yaml, one API call per tag.

    pip install anthropic pyyaml
    export ANTHROPIC_API_KEY=...

    (`ant` is a separate Go binary, not part of the `anthropic` pip package.
     You do not need it: the SDK reads ANTHROPIC_API_KEY directly. It is only
     an alternative to a static key -- `ant auth login` stores an OAuth
     profile under ~/.config/anthropic/ that a bare Anthropic() also picks up.)

    python3 alias_pass.py --dry-run --limit 3        # render prompts, no API calls
    python3 alias_pass.py --limit 20                 # calibration run
    python3 alias_pass.py                            # full pass, resumable
    python3 alias_pass.py --report                   # re-emit outputs from results.jsonl

Writes, beside this script:
    results.jsonl   one raw model response per tag; resume reads this and skips done tags
    aliases.yaml    proposals that passed grounding, ready to merge into taxonomy.yaml
    review.md       everything needing a human: rejections, missing-tag candidates, collisions

Interrupt any time. Re-running resumes; nothing is recomputed.
"""
import argparse, json, os, re, sys, threading, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
MODEL = "claude-opus-5"

# ---------------------------------------------------------------- the prompt
#
# Category-instance policy (rule 6 below). "What should `cellular` do with LTE,
# given there is no `lte` tag?" has three defensible answers:
#
#   (a) instances become aliases of the category            <- CHOSEN
#       A reader typing LTE lands somewhere useful today. The cost is a category
#       tag whose alias list is a list of other technologies, which reads oddly
#       and blurs the line rule 1 draws.
#   (b) instances become missing_tag_candidates only
#       Keeps `aliases` strictly synonymous and the criterion clean. A reader
#       typing LTE gets nothing until someone creates the tag, which may never
#       happen.
#   (c) instances belong to full-text search
#       Smallest vocabulary, no new machinery. Full-text search does find LTE in
#       the documents -- it just never reveals that `cellular` is the tag.
#
# (a) was chosen deliberately; it is the only one that helps the reader on the
# day the alias lands. To switch, edit rule 6 and re-run: results.jsonl makes
# that a re-run of the affected tags rather than the whole vocabulary.

INSTRUCTIONS = """\
You are helping build the `aliases` field for tags in the RFC subject tag
taxonomy (rfc-editor/rfc-subject-tags).

An alias exists for one purpose: a reader types a word into the tag lookup and
lands on the right tag. It is searched, never displayed. It does not affect
which RFCs get the tag -- that is the separate `match` field -- so an alias can
never break tagging, and a term already present in `match` still needs to be
listed here if it is a variant name, because `match` is never searched.

## What qualifies

A synonym or variant name for THE EXACT TAG YOU ARE GIVEN -- another string
denoting the same thing, that a reader might type instead of the tag's name:

  - superseded or predecessor names:   SSL -> tls,  SIDR -> rpki
  - version and variant forms:         NFSv4 -> nfs,  HTTP/1.1 -> http,
                                       OSPFv2 -> ospf,  SNTP -> ntp,
                                       ESMTP -> smtp,  IKEv2 -> ike
  - common abbreviations of the name:  i18n -> internationalization
  - informal or vendor names for the
    same technology:                   Bonjour, Zeroconf -> service-discovery
  - the working group name where
    readers use it for the technology: SPRING -> segment-routing

## What does NOT qualify

Route each of these to the right place instead of listing it as an alias.

PRECEDENCE: rules 1-3 are disqualifying and outrank everything else in this
document, including rule 4. If a term is a different technology, a component,
or generic vocabulary, it is NOT an alias no matter what else is true of it --
not if it is frequent in the corpus, not if it is absent from the desc, not if
it seems helpful. Rule 4 only ever REMOVES a candidate that rules 1-3 have
already allowed. It can never promote one.

1. A DIFFERENT TECHNOLOGY, even a closely related one. This is the most common
   and most damaging error: the result is a confidently wrong search hit, where
   today the reader would correctly fall through to full-text search.
     WRONG: SHA-1, ECDSA, Ed25519, Kyber, ML-KEM -> aes   (other algorithms)
     WRONG: Bluetooth, Zigbee, LoRaWAN, NB-IoT   -> 6lowpan (other link layers)
     WRONG: SMB, AFS                             -> nfs   (other file protocols)
   If such a term looks like it deserves a tag of its own, put it under
   `missing_tag_candidates`. That is a useful finding, not a discard.

2. A COMPONENT, SUB-FEATURE OR INSTANCE of the tag's subject.
     WRONG: CA, CRL, PKCS -> pki;  HPACK, QPACK -> http;  SID, SRH ->
     segment-routing;  DSN, MTA -> smtp

3. GENERIC VOCABULARY -- a word describing the area rather than naming it.
     WRONG: community, message, router, forwarding, certificate, registry,
     architecture, framework, performance, use cases, payload format
   These belong to full-text search, which already finds them in the documents.

4. ANYTHING ALREADY REACHABLE BY SEARCHING THE TAG'S `desc`. Note carefully
   what "reachable" means -- being visible in the desc is NOT the test:
     - The desc is indexed as whole words, and a query matches a word only if
       that word STARTS with the query.
     - Words are split on spaces and punctuation, but `/`, `.`, `+` and `#`
       stay INSIDE a word. So in "over SONET/SDH" the indexed word is
       `sonet/sdh`, and typing `SDH` finds nothing. `SDH` is therefore a
       legitimate alias even though it is plainly visible in the desc.
     - Matching is directional: the desc word `ntp` does not make `SNTP`
       findable, because `ntp` does not start with `sntp`.
   The test is: for a term that has ALREADY PASSED rules 1-3, would typing it
   alone land a reader on this tag today? If it would, drop it as redundant;
   if it would not, it survives. This rule never rescues a term that rules 1-3
   rejected.

5. ANY STRING THAT IS ANOTHER TAG'S id (the full list is below). That would
   shadow a real tag. If the right home for a term is a different existing tag,
   say so in `notes` rather than claiming it here.

## A second list: `covers`

6. INSTANCES OF A CATEGORY TAG GO IN `covers`, NOT `aliases`, when the tag names
   a category rather than one technology AND the instance has no tag of its own.
   The tag `cellular` is "IP over 3GPP systems, GPRS/LTE/5G interworking" and
   there is no `lte` tag, so a reader typing LTE has nowhere better to land: put
   LTE, 5G, GSM and UMTS in `covers`.

   The distinction is the whole point of having two lists. `aliases` holds other
   names for THE SAME THING -- someone typing SNTP and someone typing NTP want
   the same tag because they mean the same protocol. `covers` holds DIFFERENT
   things the tag stands in for, because nothing more specific exists yet. Both
   are searched; only `covers` is honest to display as the tag's scope.

   BOTH conditions must hold. Check the vocabulary list below: if the instance
   has its own tag, rule 1 governs and it belongs in neither list -- SHA-1 stays
   out of `aes` because `sha` exists. If the tag names a single technology
   rather than a category, it has no `covers` at all; most tags will not.

   Anything you put in `covers` that looks substantial enough to deserve its own
   tag should ALSO go in `missing_tag_candidates`. That is what makes `covers`
   the standing queue for the next vocabulary review.

## Constraints

- Prefer SINGLE-TOKEN aliases. The tag search matches the whole query against
  individual words and never splits it, so a multi-word alias cannot be found
  today. Put a genuinely important multi-word alias under `multiword` instead,
  so it can wait on a search fix.
- An alias may legitimately belong to more than one tag (e.g. `sftp` for both
  `ftp` and `ssh`). Say so in the reason rather than forcing a single owner.
- Match the capitalisation a reader would type, and the name's correct case.
- AN EMPTY LIST IS THE EXPECTED ANSWER FOR MOST TAGS. Most tags have exactly
  one name. Do not manufacture aliases to fill the field, and do not stretch a
  component or a sibling to qualify. Proposing nothing is a good outcome.
- Only propose terms you are confident appear in real RFC text. Every proposal
  is checked against the corpus and anything with no occurrences is rejected,
  so an invented acronym costs you a rejection and gains nothing.

## The complete tag vocabulary

Every existing tag id, for rule 5 and to tell siblings apart:

{all_ids}
"""

TAG_BLOCK = """\
Propose aliases for this tag, and only this tag.

  id:       {id}
  desc:     {desc}
  kind:     {kind}
  path:     {path}
  parent:   {parent}
  siblings: {siblings}
  children: {children}
  groups:   {groups}
  match:    {match}

Remember: `desc` is already searched word by word, `match` is never searched,
and an empty aliases list is the expected answer for most tags.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "aliases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"term": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["term", "reason"],
                "additionalProperties": False,
            },
        },
        "covers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"term": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["term", "reason"],
                "additionalProperties": False,
            },
        },
        "multiword": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"term": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["term", "reason"],
                "additionalProperties": False,
            },
        },
        "missing_tag_candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"term": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["term", "reason"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["id", "aliases", "covers", "multiword", "missing_tag_candidates", "notes"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------- taxonomy

def load_taxonomy(path):
    tags = yaml.safe_load(open(path))["tags"]
    by_id = {t["id"]: t for t in tags}
    kids = defaultdict(list)
    for t in tags:
        if t.get("parent"):
            kids[t["parent"]].append(t["id"])

    def path_of(tid):
        out, seen = [], set()
        while tid and tid not in seen:
            seen.add(tid)
            out.append(tid)
            tid = by_id[tid].get("parent")
        return "/".join(reversed(out))

    return tags, by_id, kids, path_of


def render_tag(t, by_id, kids, path_of):
    parent = t.get("parent")
    sibs = [s for s in kids.get(parent, []) if s != t["id"]] if parent else []
    return TAG_BLOCK.format(
        id=t["id"],
        desc=t.get("desc", ""),
        kind=t.get("kind", ""),
        path=path_of(t["id"]),
        parent=parent or "(root)",
        siblings=", ".join(sibs) or "(none)",
        children=", ".join(kids.get(t["id"], [])) or "(none)",
        groups=", ".join(t.get("groups", [])) or "(none)",
        match="  |  ".join(t.get("match", []) + t.get("match_title_only", [])) or "(none)",
    )

# ---------------------------------------------------------------- grounding

class Corpus:
    """Grounding: does this term really name this tag, in RFC text?

    Two sources, in order of preference.

    Full text (--fulltext, the rfcNNNN.txt files) is what the check wants.
    Metadata alone -- rfcs.json titles, keywords and abstracts -- misses aliases
    that only ever appear in a body: krb5, authz, RadSec, tcpdump and about a
    hundred others were rejected under the metadata-only rule and are real.

    But a raw full-text count is not enough either, because a short string
    matches for unrelated reasons. `h2` appears in 202 RFCs, almost all of them
    HTML headings, hosts H1/H2/H3 in topology diagrams, or IP octets
    h1.h2.h3.h4. So a term is judged on PRECISION, not volume:

        raw       documents containing the term
        in-ctx    of those, the ones the tag's own `match` rules also fire on
        precision in-ctx / raw

    A term keeps its proposal only with at least one in-context hit and
    precision at or above --min-precision. Measured that way `h2` scores 5% and
    `disruption` under `dtn` scores 2%, while genuinely short abbreviations hold
    up -- `TE` 71%, `PW` 72%, `ND` 78%. Length is not the discriminator;
    precision is. This costs nothing to compute: the match rules already exist.
    """

    def __init__(self, metadata_path, fulltext_dir=None):
        self.texts, self.full = [], False
        if fulltext_dir and os.path.isdir(fulltext_dir):
            import glob
            for f in sorted(glob.glob(os.path.join(fulltext_dir, "rfc[0-9]*.txt"))):
                try:
                    self.texts.append(open(f, encoding="utf-8", errors="ignore").read().lower())
                except OSError:
                    pass
            self.full = bool(self.texts)
        if not self.full:                      # fall back to metadata
            for r in json.load(open(metadata_path)):
                self.texts.append(
                    " ".join(str(r.get(k, "")) for k in ("title", "keywords", "abstract")).lower()
                )
        self._match_cache = {}

    def _rx(self, term):
        return re.compile(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])")

    def score(self, term, entry):
        """-> (raw, in_context, precision%). Without match rules, in_context == raw."""
        low, rx = term.lower(), self._rx(term)
        hits = [t for t in self.texts if low in t and rx.search(t)]
        raw = len(hits)
        pats = entry.get("match", []) + entry.get("match_title_only", [])
        if not pats or not raw:
            return raw, raw, 100 if raw else 0
        key = entry["id"]
        if key not in self._match_cache:
            self._match_cache[key] = [re.compile(p, re.I) for p in pats]
        mrx = self._match_cache[key]
        ctx = sum(1 for t in hits if any(r.search(t) for r in mrx))
        return raw, ctx, (ctx * 100 // raw)


# ---------------------------------------------------------------- the call

def build_client(max_retries):
    import anthropic
    return anthropic.Anthropic(max_retries=max_retries)


# --- CLI backend: reuse Claude Code's own OAuth credentials, no API key ------
#
# Costs ~$0.045-equivalent per call in Claude Code scaffolding alone, drawn from
# the subscription's usage allowance rather than billed. Slower and without
# structured-output guarantees, so JSON is requested in the prompt and parsed
# defensively. Use for a calibration run; prefer --backend api for the full pass.

import glob, subprocess

CLI_FLAGS = [
    "--output-format", "json",
    "--exclude-dynamic-system-prompt-sections",
    "--disallowed-tools", "Bash", "Read", "Write", "Edit", "Glob", "Grep",
    "WebFetch", "WebSearch", "Task", "TodoWrite", "NotebookEdit",
]

JSON_ONLY = (
    "\n\n## Output\n\nEmit ONE JSON object and nothing else -- no prose, no code "
    "fence, no explanation before or after. It must have exactly these keys:\n"
    '  id (string), aliases (array), covers (array), multiword (array),\n'
    '  missing_tag_candidates (array), notes (string)\n'
    "Each array holds objects with exactly the keys `term` and `reason`, both strings. "
    "Empty arrays are expected and correct for most tags."
)


def find_cli():
    if os.environ.get("CLAUDE_CLI"):
        return os.environ["CLAUDE_CLI"]
    pats = [
        os.path.expanduser("~/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude"),
        os.path.expanduser("~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude"),
    ]
    hits = sorted(h for p in pats for h in glob.glob(p))
    if not hits:
        from shutil import which
        if which("claude"):
            return which("claude")
        raise SystemExit("no claude CLI found; set CLAUDE_CLI=/path/to/claude")
    return hits[-1]


def extract_json(text):
    """Tolerate a code fence or stray prose around the object."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t.strip())
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j <= i:
        raise ValueError(f"no JSON object in response: {text[:200]!r}")
    return json.loads(t[i : j + 1])


def ask_cli(cli, system_text, tag_text, timeout):
    proc = subprocess.run(
        [cli, "-p", tag_text, "--system-prompt", system_text + JSON_ONLY] + CLI_FLAGS,
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"cli exit {proc.returncode}: {proc.stderr[:300]}")
    env = json.loads(proc.stdout)
    if env.get("is_error"):
        raise RuntimeError(f"cli error: {str(env.get('result'))[:300]}")
    usage = {
        "in": env["usage"]["input_tokens"],
        "out": env["usage"]["output_tokens"],
        "cache_read": env["usage"].get("cache_read_input_tokens", 0),
        "cost_milli": int(env.get("total_cost_usd", 0) * 1000),
    }
    return extract_json(env["result"]), usage


def ask(client, system_blocks, tag_text, effort):
    resp = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=system_blocks,
        thinking={"type": "adaptive"},
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": tag_text}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"refusal: {getattr(resp.stop_details, 'category', None)}")
    text = next(b.text for b in resp.content if b.type == "text")
    usage = {
        "in": resp.usage.input_tokens,
        "out": resp.usage.output_tokens,
        "cache_read": getattr(resp.usage, "cache_read_input_tokens", 0),
    }
    return json.loads(text), usage

# ---------------------------------------------------------------- outputs

def write_outputs(results, corpus, by_id, out_dir, min_hits, min_precision=20, previous=None):
    ids = set(by_id)
    claimed = defaultdict(list)
    for r in results.values():
        for a in r.get("aliases", []):
            claimed[a["term"].lower()].append(r["id"])

    kept, covers, rejected, missing, collisions = defaultdict(list), defaultdict(list), [], [], []
    for tid in sorted(results):
        for c in results[tid].get("covers", []):
            term, why = c["term"], c["reason"]
            if term.lower().replace(" ", "-") in ids:
                collisions.append((tid, term, "is an existing tag id (covers)")); continue
            if corpus:
                raw, ctx, prec = corpus.score(term, by_id[tid])
            else:
                raw = ctx = min_hits; prec = 100
            # `covers` names a different technology by design, so the tag's own
            # match rules fire on fewer of its documents. Grounding still has to
            # show the term is real, but precision is not the right bar for it.
            if ctx < min_hits and raw < min_hits:
                rejected.append((tid, term, raw, ctx, prec, why, "no corpus use (covers)"))
                continue
            covers[tid].append((term, raw, ctx, prec, why))
        for a in results[tid].get("aliases", []):
            term, why = a["term"], a["reason"]
            if term.lower().replace(" ", "-") in ids:
                collisions.append((tid, term, "is an existing tag id"))
                continue
            if corpus:
                raw, ctx, prec = corpus.score(term, by_id[tid])
            else:
                raw = ctx = min_hits; prec = 100
            if ctx < min_hits:
                rejected.append((tid, term, raw, ctx, prec, why, "no in-context use"))
                continue
            if prec < min_precision:
                rejected.append((tid, term, raw, ctx, prec, why, "imprecise"))
                continue
            kept[tid].append((term, raw, ctx, prec, why))
        for m in results[tid].get("missing_tag_candidates", []):
            missing.append((tid, m["term"], m["reason"]))

    with open(out_dir / "aliases.yaml", "w") as f:
        f.write("# Generated by alias_pass.py -- proposals that passed corpus grounding.\n")
        f.write("# Review before merging into taxonomy.yaml.\n")
        f.write("#   raw  RFCs containing the term\n")
        f.write("#   ctx  of those, the ones this tag's own match rules also fire on\n")
        f.write("#   %    precision: ctx/raw. A short string that matches for unrelated\n")
        f.write("#        reasons scores low here even when raw is large.\n\n")
        for tid in sorted(set(kept) | set(covers)):
            f.write(f"{tid}:\n")
            if kept[tid]:
                f.write("  aliases:\n")
                for term, raw, ctx, prec, why in kept[tid]:
                    f.write(f"  - {json.dumps(term)}   # raw {raw} ctx {ctx} {prec}% -- {why}\n")
            if covers[tid]:
                f.write("  covers:\n")
                for term, raw, ctx, prec, why in covers[tid]:
                    f.write(f"  - {json.dumps(term)}   # raw {raw} ctx {ctx} {prec}% -- {why}\n")
            f.write("\n")

    with open(out_dir / "review.md", "w") as f:
        f.write("# Alias pass -- items needing a human\n\n")
        f.write(f"Tags processed: {len(results)}  |  aliases kept: "
                f"{sum(len(v) for v in kept.values())} across {len(kept)} tags  |  "
                f"covers: {sum(len(v) for v in covers.values())} across {len(covers)} tags\n\n")

        f.write(f"## Rejected -- {len(rejected)}\n\n")
        f.write("Two reasons. *no in-context use*: the term never appears in a document\n")
        f.write("this tag matches, so it is probably invented. *imprecise*: the term does\n")
        f.write(f"appear but under {min_precision}% of its uses are in this tag's documents,\n")
        f.write("so it matches for unrelated reasons -- the usual case for short strings.\n")
        f.write("Read this list; it is a review queue, not a discard pile.\n\n")
        for tid, term, raw, ctx, prec, why, reason in sorted(rejected, key=lambda r: (r[6], r[0])):
            f.write(f"- `{tid}` **{term}** — {reason} (raw {raw}, ctx {ctx}, {prec}%) -- {why}\n")

        amb = {t: v for t, v in claimed.items() if len(v) > 1}
        f.write(f"\n## Claimed by more than one tag -- {len(amb)}\n\n")
        f.write("Not necessarily wrong: an alias may legitimately serve two tags.\n\n")
        for term, tids in sorted(amb.items()):
            f.write(f"- **{term}** -> {', '.join(sorted(tids))}\n")

        f.write(f"\n## Collisions with an existing tag id -- {len(collisions)}\n\n")
        for tid, term, note in collisions:
            f.write(f"- `{tid}` **{term}** -- {note}\n")

        f.write(f"\n## Missing-tag candidates -- {len(missing)}\n\n")
        f.write("Terms the model judged to be a different technology that may deserve\n"
                "its own tag. This is the sibling-technology class, routed here instead\n"
                "of being silently dropped.\n\n")
        for tid, term, why in sorted(missing, key=lambda r: r[0]):
            f.write(f"- `{tid}` **{term}** -- {why}\n")

        # A model pass is not deterministic: re-running finds a different subset,
        # not the same one. Terms an earlier pass proposed and this one did not
        # are listed here rather than lost, which is what makes repeated passes
        # accumulate instead of churn. Feed the prior aliases.yaml with
        # --previous; git has every committed one.
        if previous:
            now = {(t, a) for t, v in list(kept.items()) for a, *_ in v}
            now |= {(t, a) for t, v in list(covers.items()) for a, *_ in v}
            prev = yaml.safe_load(open(previous)) or {}
            gone = {
                (t, a)
                for t, v in prev.items()
                for a in ((v.get("aliases") or []) + (v.get("covers") or []))
                if (t, a) not in now
            }
            # The queue is sticky. Without this it is one-generation memory: a
            # term dropped by pass 2 is listed once, then vanishes at pass 3
            # because it is no longer in the aliases.yaml being differenced
            # against. Carry the previous review.md's own list forward, minus
            # anything since adopted, so an entry survives until someone acts.
            carried = out_dir / "review.md"
            if carried.exists():
                keep_section = False
                for line in carried.read_text().splitlines():
                    if line.startswith("## Proposed by a previous pass"):
                        keep_section = True; continue
                    if keep_section and line.startswith("## "):
                        break
                    m = re.match(r"^- `([^`]+)` \*\*(.+?)\*\*", line)
                    if keep_section and m and (m.group(1), m.group(2)) not in now:
                        gone.add((m.group(1), m.group(2)))
            gone = sorted(gone)
            f.write(f"\n## Proposed by a previous pass, not re-proposed -- {len(gone)}\n\n")
            f.write("A model pass is not deterministic, so a re-run explores a different\n")
            f.write("subset rather than reproducing the last one. These were proposed before\n")
            f.write("and are absent now. They are not rejections -- nothing judged them -- so\n")
            f.write("read them as candidates, deciding for each whether it is an alias, a\n")
            f.write("covers entry, or neither.\n\n")
            for t, a in gone:
                f.write(f"- `{t}` **{a}**\n")

        notes = [(t, results[t]["notes"]) for t in sorted(results) if results[t].get("notes", "").strip()]
        f.write(f"\n## Notes -- {len(notes)}\n\n")
        for tid, note in notes:
            f.write(f"- `{tid}` -- {note}\n")

    return kept, covers, rejected, missing, collisions

# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--taxonomy", default="taxonomy.yaml")
    p.add_argument("--corpus", default="rfcs.json",
                   help="for grounding; omit with --no-ground")
    p.add_argument("--out", default=str(HERE))
    p.add_argument("--backend", default="api", choices=["api", "cli"],
                   help="api = ANTHROPIC_API_KEY; cli = Claude Code's own OAuth, no key")
    p.add_argument("--workers", type=int, help="default 8 for api, 3 for cli")
    p.add_argument("--cli-timeout", type=int, default=300)
    p.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--max-retries", type=int, default=5)
    p.add_argument("--min-hits", type=int, default=1,
                   help="minimum in-context hits: documents using the term that the tag also matches")
    p.add_argument("--min-precision", type=int, default=20,
                   help="minimum %% of a term's uses that fall in this tag's own documents")
    p.add_argument("--fulltext", default="tmp/rfc",
                   help="directory of rfcNNNN.txt files; falls back to metadata when absent")
    p.add_argument("--limit", type=int, help="process only the first N pending tags")
    p.add_argument("--tags", help="comma-separated tag ids to process")
    p.add_argument("--no-ground", action="store_true")
    p.add_argument("--retry-rounds", type=int, default=0,
                   help="after the pass, re-attempt tags that failed, this many more times. "
                        "Use for long runs that may hit a usage limit: resume makes each round "
                        "cost only what is still missing")
    p.add_argument("--retry-wait", type=int, default=900,
                   help="seconds to wait between retry rounds (default 15 min)")
    p.add_argument("--previous", metavar="ALIASES_YAML",
                   help="a prior aliases.yaml; terms it proposed that this pass did not are "
                        "listed in review.md instead of being lost. Use on every re-run: "
                        "`git show HEAD:curation/aliases.yaml > prev.yaml`")
    p.add_argument("--dry-run", action="store_true", help="render prompts, make no API calls")
    p.add_argument("--report", action="store_true", help="rebuild outputs from results.jsonl only")
    args = p.parse_args()
    if args.workers is None:
        args.workers = 3 if args.backend == "cli" else 8

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"

    tags, by_id, kids, path_of = load_taxonomy(args.taxonomy)
    corpus = None if args.no_ground else Corpus(args.corpus, args.fulltext)

    done = {}
    if results_path.exists():
        for line in results_path.open():
            line = line.strip()
            if line:
                r = json.loads(line)
                done[r["id"]] = r

    if args.report:
        kept, cov, rej, miss, coll = write_outputs(done, corpus, by_id, out_dir, args.min_hits, args.min_precision, args.previous)
        print(f"rebuilt from {len(done)} results: {sum(len(v) for v in kept.values())} aliases, "
              f"{sum(len(v) for v in cov.values())} covers, {len(rej)} rejected, "
              f"{len(miss)} missing-tag candidates, {len(coll)} collisions")
        return

    pending = [t for t in tags if t["id"] not in done]
    if args.tags:
        want = {s.strip() for s in args.tags.split(",")}
        pending = [t for t in tags if t["id"] in want]
    if args.limit:
        pending = pending[: args.limit]

    print(f"{len(tags)} tags | {len(done)} already done | {len(pending)} to process")
    if not pending:
        print("nothing to do -- use --report to rebuild outputs")
        return

    system_blocks = [{
        "type": "text",
        "text": INSTRUCTIONS.format(all_ids=", ".join(sorted(by_id))),
        "cache_control": {"type": "ephemeral"},
    }]

    if args.dry_run:
        for t in pending:
            print("=" * 72)
            print(render_tag(t, by_id, kids, path_of))
        print(f"[dry run] system prompt {len(system_blocks[0]['text'])} chars, "
              f"identical and cached across all {len(pending)} calls")
        return

    if args.backend == "cli":
        cli = find_cli()
        print(f"backend: cli ({cli})\n  uses Claude Code's existing credentials -- no API key.\n"
              f"  ~$0.045-equivalent of scaffolding per call, drawn from subscription usage.")
    else:
        client = build_client(args.max_retries)
        print("backend: api (ANTHROPIC_API_KEY)")
    lock = threading.Lock()
    fh = results_path.open("a")
    totals = defaultdict(int)
    failures = []

    def work(t):
        tag_text = render_tag(t, by_id, kids, path_of)
        if args.backend == "cli":
            data, usage = ask_cli(cli, system_blocks[0]["text"], tag_text, args.cli_timeout)
        else:
            data, usage = ask(client, system_blocks, tag_text, args.effort)
        data["id"] = t["id"]          # never trust the model for the key
        return data, usage

    round_no, todo = 0, list(pending)
    while True:
      failures = []
      with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, t): t for t in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            t = futs[fut]
            try:
                data, usage = fut.result()
            except Exception as e:                      # noqa: BLE001 - keep the run alive
                failures.append(t)
                print(f"[{i}/{len(todo)}] {t['id']}: FAILED {e}", file=sys.stderr)
                continue
            with lock:
                fh.write(json.dumps(data) + "\n")
                fh.flush()
                done[t["id"]] = data
                for k, v in usage.items():
                    totals[k] += v
            n = len(data.get("aliases", []))
            print(f"[{i}/{len(todo)}] {t['id']}: {n} alias{'' if n == 1 else 'es'}"
                  + (f", {len(data['missing_tag_candidates'])} missing-tag" if data.get("missing_tag_candidates") else ""))

      # A usage limit shows up as every remaining tag failing in quick succession.
      # Waiting and re-attempting only the failures is what lets a long run cross
      # a limit reset unattended; results.jsonl means nothing already done is redone.
      if not failures or round_no >= args.retry_rounds:
          break
      round_no += 1
      print(f"\n{len(failures)} failed; retry round {round_no}/{args.retry_rounds} "
            f"in {args.retry_wait}s", file=sys.stderr)
      time.sleep(args.retry_wait)
      todo = failures
    fh.close()

    if failures:
        print(f"\n{len(failures)} still failing after {round_no} retry round(s) "
              f"-- re-run to attempt just these:", file=sys.stderr)
        for t in failures:
            print(f"  {t['id']}", file=sys.stderr)

    kept, cov, rej, miss, coll = write_outputs(done, corpus, by_id, out_dir, args.min_hits, args.min_precision, args.previous)
    print(f"\ntokens: {totals['in']} in ({totals['cache_read']} cached), {totals['out']} out"
          + (f" | ~${totals['cost_milli']/1000:.2f} equivalent" if totals.get("cost_milli") else ""))
    print(f"aliases {sum(len(v) for v in kept.values())} across {len(kept)} tags | "
          f"covers {sum(len(v) for v in cov.values())} across {len(cov)} tags | "
          f"rejected {len(rej)} | missing-tag {len(miss)} | collisions {len(coll)}")
    print(f"-> {out_dir/'aliases.yaml'}\n-> {out_dir/'review.md'}")


if __name__ == "__main__":
    main()
