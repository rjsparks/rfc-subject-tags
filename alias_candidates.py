#!/usr/bin/env python3
"""Harvest candidate aliases from RFC titles.

RFC titles spell out an expansion on first use -- "Simple Network Time Protocol
(SNTP)", "Internet Key Exchange (IKEv2)" -- which is exactly where variant names
live. This reads the corpus and the assignments the engine just made, and lists
acronyms that no reader could currently reach by searching the tag they belong
to.

    python3 alias_candidates.py                       # whole corpus
    python3 alias_candidates.py --since 2025          # recent RFCs only
    python3 alias_candidates.py --out alias-candidates.json

Unlike alias_pass.py this calls no model and costs nothing, so it is cheap
enough to run on every build. It generates candidates; it does not judge them.
Roughly half of what it finds is not an alias -- a component (LSP under mpls), a
different technology (BGP-LS under bgp), or a term whose real home is a more
specific tag. Feed the output to a curator, or to alias_pass.py as a prior.

Reads, all of which the build already has on disk at this point:
    taxonomy.yaml   for ids, descriptions, match rules and existing aliases
    rfcs.json       for titles
    rfc-tags.json   for the tags each RFC was assigned
"""
import argparse, json, re, sys
from collections import defaultdict

import yaml

# "Some Expanded Name (ACRO)" -- the expansion is what tells us which tag the
# acronym belongs to. Without it every tag on the RFC looks equally plausible
# and the output is dominated by co-occurrence: EPP -> rdap and RDAP -> epp.
TITLE_ACRONYM = re.compile(r'([A-Za-z][A-Za-z0-9 ,/-]{4,70}?)\s*\(([A-Za-z][A-Za-z0-9./+-]{1,14})\)')

# How the tag search tokenizes: '/', '.', '+' and '#' stay INSIDE a word, so
# "SONET/SDH" is one token and SDH is not reachable through it. Keep in step
# with words() in browser_template.html.
WORD = re.compile(r'[^a-z0-9.+#/]+')
SUBWORD = re.compile(r'[^a-z0-9]+')
words = lambda s: [x for x in WORD.split(str(s or '').lower()) if x]
subwords = lambda s: [x for x in SUBWORD.split(str(s or '').lower()) if x]


def load(taxonomy_path):
    tags = yaml.safe_load(open(taxonomy_path))["tags"]
    by_id = {t["id"]: t for t in tags}
    match = {t: [re.compile(p, re.I) for p in e.get("match", []) + e.get("match_title_only", [])]
             for t, e in by_id.items()}

    def depth(tid):
        d, seen = 0, set()
        while tid and tid not in seen:
            seen.add(tid); d += 1; tid = by_id[tid].get("parent")
        return d

    return by_id, match, {t: depth(t) for t in by_id}


def reachable(entry, term):
    """Would typing `term` into the tag search already land on this tag?

    Mirrors scoreTag() in browser_template.html: exact or prefix match on the id,
    on the id's hyphen-separated parts, or on a whole word of the description --
    plus any alias already recorded, so a decided alias never resurfaces.
    """
    q = term.lower()
    tid = entry["id"].lower()
    if tid == q or tid.startswith(q):
        return True
    if any(k == q or k.startswith(q) for k in subwords(entry["id"])):
        return True
    if any(k == q or k.startswith(q) for k in words(entry.get("desc", ""))):
        return True
    for a in entry.get("aliases", []) or []:
        a = str(a).lower()
        if a == q or a.startswith(q):
            return True
    return False


def harvest(recs, assigned, by_id, match, depth, since=None):
    found = defaultdict(lambda: defaultdict(list))
    for r in recs:
        year = r.get("year")
        if since and (not str(year).isdigit() or int(year) < since):
            continue
        title = r.get("title") or ""
        tags = assigned.get(r["id"], {}).get("tags", [])
        if not tags:
            continue
        for m in TITLE_ACRONYM.finditer(title):
            expansion, acronym = m.group(1), m.group(2)
            if sum(c.isupper() for c in acronym) < 2:
                continue                       # not acronym-shaped; skip
            # Attribute to the most specific tag whose own rules fire on the
            # expansion. "Resource Public Key Infrastructure (RPKI)" fires both
            # pki and rpki; rpki is deeper and wins, and RPKI is then already
            # reachable through that tag's id, so nothing is proposed. Correct.
            hits = [t for t in tags if any(rx.search(expansion) for rx in match[t])]
            if not hits:
                continue
            best = max(hits, key=lambda t: depth[t])
            if reachable(by_id[best], acronym):
                continue
            found[best][acronym].append(r["id"])
    return found


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--taxonomy", default="taxonomy.yaml")
    p.add_argument("--corpus", default="rfcs.json")
    p.add_argument("--assignments", default="rfc-tags.json")
    p.add_argument("--since", type=int, help="only RFCs published in this year or later")
    p.add_argument("--out", default="alias-candidates.json")
    p.add_argument("--min-rfcs", type=int, default=1, help="drop candidates seen in fewer RFCs")
    args = p.parse_args()

    by_id, match, depth = load(args.taxonomy)
    recs = json.load(open(args.corpus))
    assigned = json.load(open(args.assignments))
    found = harvest(recs, assigned, by_id, match, depth, args.since)

    out = {
        "generated_from": {
            "rfcs": len(recs),
            "tags": len(by_id),
            "since": args.since,
        },
        "note": ("Candidates only. Roughly half of these are not aliases but components, "
                 "different technologies, or terms belonging to a more specific tag. "
                 "Each is an acronym that appeared in an RFC title beside its expansion "
                 "and that no reader can currently reach by searching the named tag."),
        "candidates": [],
    }
    for tid in sorted(found):
        for acronym, rfcs in sorted(found[tid].items(), key=lambda kv: -len(kv[1])):
            if len(rfcs) < args.min_rfcs:
                continue
            out["candidates"].append({
                "tag": tid,
                "term": acronym,
                "rfcs": len(rfcs),
                "examples": sorted(rfcs)[:5],
                "desc": by_id[tid].get("desc", ""),
            })
    # Most-seen first: a reviewer reads from the top and stops when the counts
    # thin out, rather than working through 542 tags alphabetically.
    out["candidates"].sort(key=lambda c: (-c["rfcs"], c["tag"], c["term"]))
    out["generated_from"]["candidates"] = len(out["candidates"])

    with open(args.out, "w") as f:
        json.dump(out, f, indent=1, sort_keys=False)
        f.write("\n")

    print(f"{len(out['candidates'])} candidates across {len(found)} tags -> {args.out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
