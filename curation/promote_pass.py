#!/usr/bin/env python3
"""Decide which candidate terms deserve a tag of their own.

    python3 promote_pass.py --dry-run --limit 2
    python3 promote_pass.py                       # resumable, one call per parent tag

The alias pass produced two kinds of leftover: `covers` entries -- technologies a
category tag stands in for -- and terms an earlier pass proposed that a later one
did not. Both are the same question deferred: is this a technology of its own, or
another name for the tag it sits under?

R10 says a technology with documents of its own deserves a tag, R13 permits
single-document tags, and R11's evidence test is "does an RFC use the name as the
name of the thing". A title hit is that evidence. But counting cannot make the
decision: it promotes IAB (69 title hits), IESG and IRTF, which are organisations
R14/R15 exclude; and it cannot separate a family member from a technology --
SHA-256 and ECDSA score alike, yet one is a variant of `sha` and the other is a
technology in its own right. So the count is a prefilter and this pass is the
decision.

Batched by parent, not by term: whether SHA-256 is a child of `sha` or a name for
it depends on what `sha` already covers and what children it already has, so the
model sees the parent's whole situation at once.

Writes, beside this script:
    promotions.jsonl  one raw response per parent tag; also the resume file
    promotions.yaml   per candidate: tag / alias / drop, with desc and match for tags
"""
import argparse, json, os, re, sys, threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
MAX_DEPTH = 4                      # the taxonomy's own limit; a level-4 tag takes no children

INSTRUCTIONS = """\
You are deciding, for one tag in the RFC subject tag taxonomy, whether each of
its candidate terms should become a child tag, stay as an alias, or be dropped.

## The three outcomes

**tag** -- the term names a distinct technology with RFCs of its own. R10 says
such a technology deserves a tag; R13 allows a tag carried by a single document.
The evidence is R11's: an RFC title uses the name as the name of the thing. Each
candidate's title-hit count is given below.

**alias** -- the term is another name for the tag it sits under, not a separate
thing. This covers:
  - version and family members: SHA-256 and SHA-1 are members of the family
    `sha` already names; BGP-4 is a version of `bgp`; GSS-API is a spelling of
    `gssapi`; peer-to-peer is the expansion of `p2p`.
  - a technology RFCs mention but never take as their subject, which therefore
    could not carry a tag: no document would be filed under it.
  - abbreviations and expansions of the tag's own name.

**drop** -- neither. An organisation or body rather than a technology (IAB,
IESG, IRTF, ISOC: R14 and R15 exclude these), generic vocabulary, or a component
of the tag's subject rather than a thing in itself.

## What a high title count does and does not mean

It is evidence that RFCs are *about* the thing, which is what distinguishes a
tag from an alias. It is not a decision. IAB has 69 title hits and is an
organisation. SHA-256 has 9 and is a family member. Judge what the term denotes,
then use the count to confirm documents exist to carry it.

## Constraints

- The parent is at depth {depth}. The taxonomy allows four levels, so a child
  lands at depth {child_depth}.{depth_note}
- A tag needs a `desc` and a `match`. Follow the house conventions: the desc
  carries the correct-case name, the expansion in parentheses for an acronym,
  then the scope, and never repeats the name; the match is a Python regular
  expression tried case-insensitively against title and author keywords. Write
  `match` tightly enough that it does not fire on the parent's other documents.
- Prefer **alias** when genuinely unsure. A wrong alias costs a search hit; a
  wrong tag enters a published vocabulary that R17 says changes rarely, and
  which readers subscribe to.
- Every outcome needs a reason naming which of the three cases applies.
"""

TAG_BLOCK = """\
Parent tag
  id:       {id}
  desc:     {desc}
  kind:     {kind}
  path:     {path}
  children: {children}
  match:    {match}

Candidates (term, and the number of RFC titles using it)
{candidates}
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "parent": {"type": "string"},
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "outcome": {"type": "string", "enum": ["tag", "alias", "drop"]},
                    "reason": {"type": "string"},
                    "id": {"type": "string"},
                    "desc": {"type": "string"},
                    "match": {"type": "string"},
                },
                "required": ["term", "outcome", "reason", "id", "desc", "match"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["parent", "decisions"],
    "additionalProperties": False,
}

JSON_ONLY = (
    "\n\n## Output\n\nEmit ONE JSON object and nothing else -- no prose, no code fence. Keys: "
    "parent (string), decisions (array). Each decision has term, outcome "
    "(\"tag\", \"alias\" or \"drop\"), reason, id, desc, match -- all strings. For an "
    "outcome that is not \"tag\", set id, desc and match to the empty string."
)


def load(tax_path, corpus_path):
    tags = yaml.safe_load(open(tax_path))["tags"]
    by_id = {t["id"]: t for t in tags}
    kids = defaultdict(list)
    for t in tags:
        if t.get("parent"):
            kids[t["parent"]].append(t["id"])

    def depth(tid):
        d, seen = 0, set()
        while tid and tid not in seen:
            seen.add(tid); d += 1; tid = by_id[tid].get("parent")
        return d

    def path(tid):
        out, seen = [], set()
        while tid and tid not in seen:
            seen.add(tid); out.append(tid); tid = by_id[tid].get("parent")
        return "/".join(reversed(out))

    titles = [(r.get("title") or "") for r in json.load(open(corpus_path))]
    return tags, by_id, kids, depth, path, titles


def title_hits(titles, term):
    rx = re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.I)
    return sum(1 for t in titles if rx.search(t))


def gather(tags, review_md):
    """Candidates: every `covers` entry, plus the carry-forward queue."""
    cand = defaultdict(list)
    for e in tags:
        for c in e.get("covers") or []:
            cand[e["id"]].append(str(c))
    if review_md and os.path.exists(review_md):
        section = False
        for line in open(review_md):
            if line.startswith("## Proposed by a previous pass"):
                section = True; continue
            if section and line.startswith("## "):
                break
            m = re.match(r"^- `([^`]+)` \*\*(.+?)\*\*", line)
            if section and m and m.group(2) not in cand[m.group(1)]:
                cand[m.group(1)].append(m.group(2))
    return cand


def render(tid, terms, by_id, kids, depth, path, titles):
    e = by_id[tid]
    d = depth(tid)
    note = ("" if d < MAX_DEPTH else
            "  This parent is already at the limit, so NO candidate here can become a tag; "
            "choose alias or drop for every one.")
    lines = "\n".join(f"  {t}  ({title_hits(titles, t)} RFC titles)" for t in terms)
    return (INSTRUCTIONS.format(depth=d, child_depth=d + 1, depth_note=note)
            + "\n\n"
            + TAG_BLOCK.format(
                id=tid, desc=e.get("desc", ""), kind=e.get("kind", ""), path=path(tid),
                children=", ".join(kids.get(tid, [])) or "(none)",
                match="  |  ".join(e.get("match", []) + e.get("match_title_only", [])) or "(none)",
                candidates=lines))


# ------------------------------------------------------------------ backends

import glob, subprocess

CLI_FLAGS = ["--output-format", "json", "--exclude-dynamic-system-prompt-sections",
             "--disallowed-tools", "Bash", "Read", "Write", "Edit", "Glob", "Grep",
             "WebFetch", "WebSearch", "Task", "TodoWrite", "NotebookEdit"]


def find_cli():
    if os.environ.get("CLAUDE_CLI"):
        return os.environ["CLAUDE_CLI"]
    hits = sorted(h for p in (
        os.path.expanduser("~/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude"),
        os.path.expanduser("~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude"),
    ) for h in glob.glob(p))
    if hits:
        return hits[-1]
    from shutil import which
    if which("claude"):
        return which("claude")
    raise SystemExit("no claude CLI found; set CLAUDE_CLI=/path/to/claude")


def extract_json(text):
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t.strip())
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if i == -1 or j <= i:
            raise ValueError(f"no JSON object in response: {text[:200]!r}")
        return json.loads(t[i:j + 1])


def ask_cli(cli, prompt, timeout):
    proc = subprocess.run([cli, "-p", prompt + JSON_ONLY] + CLI_FLAGS,
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"cli exit {proc.returncode}: {proc.stderr[:300]}")
    env = json.loads(proc.stdout)
    if env.get("is_error"):
        raise RuntimeError(f"cli error: {str(env.get('result'))[:300]}")
    return extract_json(env["result"]), env["usage"], env.get("total_cost_usd", 0)


def ask_api(client, prompt, effort):
    r = client.messages.create(
        model="claude-opus-5", max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    if r.stop_reason == "refusal":
        raise RuntimeError("refusal")
    text = next(b.text for b in r.content if b.type == "text")
    return json.loads(text), {"input_tokens": r.usage.input_tokens,
                              "output_tokens": r.usage.output_tokens}, 0


# ------------------------------------------------------------------ outputs

def write_outputs(results, by_id, out_dir, titles=None, min_hits=0):
    tags, aliases, drops = defaultdict(list), defaultdict(list), []
    for parent in sorted(results):
        for d in results[parent].get("decisions", []):
            # Enforce the prefilter rather than merely showing it to the model.
            # A term with too little title evidence cannot become a tag however
            # well the model argued it, because R10's case for a tag rests on
            # that evidence. It stays an alias instead.
            if d["outcome"] == "tag" and titles is not None:
                if title_hits(titles, d["term"]) < min_hits:
                    d = dict(d, outcome="alias",
                             reason=f"below the evidence threshold ({min_hits} title hits); "
                                    f"kept as an alias. " + d["reason"])
            if d["outcome"] == "tag":
                tags[parent].append(d)
            elif d["outcome"] == "alias":
                aliases[parent].append(d)
            else:
                drops.append((parent, d["term"], d["reason"]))

    with open(out_dir / "promotions.yaml", "w") as f:
        f.write("# Generated by promote_pass.py. Review before applying.\n")
        f.write("# tag    -> becomes a child tag, with the desc and match given\n")
        f.write("# alias  -> stays an alias of the parent\n")
        f.write("# drop   -> neither; see promotions.yaml comments and the reasons below\n\n")
        f.write("promote:\n")
        for parent in sorted(tags):
            for d in tags[parent]:
                f.write(f"  - parent: {parent}\n")
                f.write(f"    id: {d['id']}\n")
                f.write(f"    term: {json.dumps(d['term'])}\n")
                f.write(f"    desc: {json.dumps(d['desc'])}\n")
                f.write(f"    match: {json.dumps(d['match'])}\n")
                f.write(f"    reason: {json.dumps(d['reason'])}\n")
        f.write("\nalias:\n")
        for parent in sorted(aliases):
            for d in aliases[parent]:
                f.write(f"  - parent: {parent}\n")
                f.write(f"    term: {json.dumps(d['term'])}\n")
                f.write(f"    reason: {json.dumps(d['reason'])}\n")
        f.write("\ndrop:\n")
        for parent, term, why in drops:
            f.write(f"  - parent: {parent}\n")
            f.write(f"    term: {json.dumps(term)}\n")
            f.write(f"    reason: {json.dumps(why)}\n")

    n_tag = sum(len(v) for v in tags.values())
    n_alias = sum(len(v) for v in aliases.values())
    return n_tag, n_alias, len(drops)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--taxonomy", default="../taxonomy.yaml")
    p.add_argument("--corpus", default="rfcs.json")
    p.add_argument("--review", default="review.md", help="for the carry-forward queue")
    p.add_argument("--out", default=str(HERE))
    p.add_argument("--backend", default="cli", choices=["api", "cli"])
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--effort", default="high")
    p.add_argument("--cli-timeout", type=int, default=420)
    p.add_argument("--min-hits", type=int, default=1,
                   help="prefilter: candidates with fewer title hits are not even considered "
                        "for a tag (they are still listed as aliases)")
    p.add_argument("--limit", type=int)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--report", action="store_true")
    args = p.parse_args()

    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    res_path = out_dir / "promotions.jsonl"
    tags, by_id, kids, depth, path, titles = load(args.taxonomy, args.corpus)
    cand = gather(tags, args.review)
    cand = {t: v for t, v in cand.items() if t in by_id and v}

    done = {}
    if res_path.exists():
        for line in res_path.open():
            if line.strip():
                r = json.loads(line); done[r["parent"]] = r

    if args.report:
        a, b, c = write_outputs(done, by_id, out_dir, titles, args.min_hits)
        print(f"from {len(done)} parents: {a} tags, {b} aliases, {c} drops -> {out_dir/'promotions.yaml'}")
        return

    pending = [t for t in sorted(cand) if t not in done]
    if args.limit:
        pending = pending[: args.limit]
    total = sum(len(v) for v in cand.values())
    print(f"{total} candidates across {len(cand)} parent tags | {len(done)} done | {len(pending)} to process")
    if not pending:
        print("nothing to do -- use --report"); return

    if args.dry_run:
        for t in pending:
            print("=" * 72); print(render(t, cand[t], by_id, kids, depth, path, titles))
        return

    if args.backend == "cli":
        cli = find_cli(); print(f"backend: cli ({cli})")
    else:
        import anthropic
        client = anthropic.Anthropic(max_retries=5); print("backend: api")

    lock = threading.Lock()
    fh = res_path.open("a")
    spend = 0.0

    def work(t):
        prompt = render(t, cand[t], by_id, kids, depth, path, titles)
        if args.backend == "cli":
            return ask_cli(cli, prompt, args.cli_timeout)
        return ask_api(client, prompt, args.effort)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, t): t for t in pending}
        for i, fut in enumerate(as_completed(futs), 1):
            t = futs[fut]
            try:
                data, _usage, cost = fut.result()
            except Exception as e:                      # noqa: BLE001
                print(f"[{i}/{len(pending)}] {t}: FAILED {e}", file=sys.stderr); continue
            data["parent"] = t
            with lock:
                fh.write(json.dumps(data) + "\n"); fh.flush()
                done[t] = data; spend += cost
            n = sum(1 for d in data.get("decisions", []) if d["outcome"] == "tag")
            print(f"[{i}/{len(pending)}] {t}: {n} tag(s) of {len(data.get('decisions', []))}")
    fh.close()

    a, b, c = write_outputs(done, by_id, out_dir, titles, args.min_hits)
    print(f"\n{a} tags, {b} aliases, {c} drops" + (f" | ~${spend:.2f} equivalent" if spend else ""))
    print(f"-> {out_dir/'promotions.yaml'}")


if __name__ == "__main__":
    main()
