#!/usr/bin/env python3
"""Merge an aliases.yaml proposal into taxonomy.yaml.

    python3 merge_aliases.py --dry-run     # report what would change
    python3 merge_aliases.py               # write taxonomy.yaml

`regen.py` rewrites taxonomy.yaml by round-tripping it through yaml.dump, so
editing the file as text would be undone on the next curator run. This writes
through the same dumper with the same settings, which keeps the file stable:
the diff contains only the added `aliases` blocks, and the next regen run
reformats nothing.

The field is placed after `desc` and before `match`, which reads in the order a
curator thinks in -- what the tag is called, what else it is called, then how
documents are matched to it.
"""
import argparse, sys

import yaml


class Dm(yaml.SafeDumper):
    """The dumper regen.py uses. Keep the representer in step with it."""


Dm.add_representer(
    str,
    lambda dd, x: dd.represent_scalar(
        "tag:yaml.org,2002:str", x, style="'" if ("\\" in x or ":" in x) and "\n" not in x else None
    ),
)

AFTER = "desc"          # aliases, then covers, are inserted after this key
FIELDS = ("aliases", "covers")


def merge(tax_path, proposal_path, dry_run=False):
    src = open(tax_path).read()
    doc = yaml.safe_load(src)
    proposed = yaml.safe_load(open(proposal_path)) or {}
    by_id = {e["id"]: e for e in doc["tags"]}
    ids = set(by_id)

    changed, skipped, totals = [], [], {f: 0 for f in FIELDS}
    for tid, block in proposed.items():
        if tid not in by_id:
            skipped.append((tid, "-", "no such tag")); continue
        entry = by_id[tid]
        merged = {}
        for field in FIELDS:
            terms = (block or {}).get(field) or []
            keep = []
            for term in terms:
                if str(term).lower().replace(" ", "-") in ids:
                    skipped.append((tid, term, f"shadows an existing tag id ({field})")); continue
                if term not in keep:
                    keep.append(term)
            existing = entry.get(field) or []
            m = existing + [t for t in keep if t not in existing]
            if m and m != existing:
                merged[field] = m
                totals[field] += len(m)
        if not merged:
            continue
        # Rebuild so the new keys land after `desc`, in FIELDS order. PyYAML
        # dumps in insertion order because regen.py passes sort_keys=False.
        rebuilt = {}
        for k, v in entry.items():
            if k in FIELDS:
                continue
            rebuilt[k] = v
            if k == AFTER:
                for f in FIELDS:
                    if f in merged or entry.get(f):
                        rebuilt[f] = merged.get(f, entry.get(f))
        for f in FIELDS:                      # no desc key: fall back to the end
            if (f in merged) and f not in rebuilt:
                rebuilt[f] = merged[f]
        entry.clear()
        entry.update(rebuilt)
        changed.append(tid)

    out = yaml.dump(doc, Dumper=Dm, sort_keys=False, allow_unicode=True, width=200)
    if not dry_run:
        open(tax_path, "w").write(out)

    added_lines = out.count("\n") - src.count("\n")
    verb = "would add" if dry_run else "added"
    print(f"{verb} {totals['aliases']} aliases and {totals['covers']} covers "
          f"across {len(changed)} tags ({added_lines} lines)")
    for tid, term, why in skipped:
        print(f"  skipped {tid} / {term}: {why}", file=sys.stderr)
    return changed, skipped


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--taxonomy", default="../taxonomy.yaml")
    p.add_argument("--proposal", default="aliases.yaml")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    merge(a.taxonomy, a.proposal, a.dry_run)


if __name__ == "__main__":
    main()
