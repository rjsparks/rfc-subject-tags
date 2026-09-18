#!/usr/bin/env python3
"""Apply promote_pass.py's decisions to taxonomy.yaml.

    python3 apply_promotions.py --dry-run
    python3 apply_promotions.py

Three things happen at once, and they have to, because each is incoherent
without the others:

  tag    a new child entry is inserted after the parent's existing subtree, with
         the desc and match the pass proposed, and the term leaves `covers`
  alias  the term is appended to the parent's `aliases`
  drop   the term disappears

and `covers` is removed from every entry afterwards. The field existed to hold
terms whose status had not been decided; once every one has an outcome there is
nothing left for it to carry.

Writes through the dumper regen.py uses, so the diff shows only real changes and
the next curator run reformats nothing.
"""
import argparse, json, os, re, sys
from collections import defaultdict

import yaml


class Dm(yaml.SafeDumper):
    """The dumper regen.py uses."""


Dm.add_representer(
    str,
    lambda dd, x: dd.represent_scalar(
        "tag:yaml.org,2002:str", x, style="'" if ("\\" in x or ":" in x) and "\n" not in x else None
    ),
)

# Where a term was proposed under two parents, the tree allows one. Resolved by
# what the thing is, not by which call happened to run first.
DUPLICATE_HOME = {"mikey": "key-management", "arf": "email-authentication"}

# Decided against the pass, which had made it an alias on the grounds that the
# parent's own match already claims \bECDSA\b. That is true and is why the
# parent's rule is narrowed below: six RFC titles name ECDSA as their subject,
# which is the evidence test for a tag of its own.
EXTRA_TAGS = [{
    "parent": "elliptic-curve",
    "id": "ecdsa",
    "term": "ECDSA",
    "desc": "ECDSA (Elliptic Curve Digital Signature Algorithm) and its curves and encodings",
    "match": r"\bECDSA\b",
    "reason": "Six RFC titles name ECDSA as their subject; promoted by decision, not by the pass.",
}]

# A promoted child must not be matched by its parent as well, or the parent
# claims the child's documents. Each entry narrows one parent rule.
NARROW_PARENT = {"elliptic-curve": (r"elliptic curve|\bECDSA\b|\bECDH\b", r"elliptic curve|\bECDH\b")}


def load_decisions(path):
    tags, aliases, drops = [], [], []
    for line in open(path):
        if not line.strip():
            continue
        r = json.loads(line)
        for d in r["decisions"]:
            d = dict(d, parent=r["parent"])
            (tags if d["outcome"] == "tag" else aliases if d["outcome"] == "alias" else drops).append(d)
    return tags, aliases, drops


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--taxonomy", default="../taxonomy.yaml")
    p.add_argument("--decisions", default="promotions.jsonl")
    p.add_argument("--corpus", default="../rfcs.json",
                   help="used to verify each proposed tag actually matches something")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    src = open(a.taxonomy).read()
    doc = yaml.safe_load(src)
    entries = doc["tags"]
    by_id = {e["id"]: e for e in entries}

    corpus = a.corpus if os.path.exists(a.corpus) else None
    promote, alias, drops = load_decisions(a.decisions)
    promote += EXTRA_TAGS

    # One home per id. A duplicate keeps the parent named in DUPLICATE_HOME and
    # becomes an alias of the other, which is what the other parent was saying.
    seen, kept, moved = {}, [], []
    for d in promote:
        i = d["id"]
        if i in seen:
            home = DUPLICATE_HOME.get(i)
            loser = d if d["parent"] != home else seen[i]
            winner = seen[i] if loser is d else d
            seen[i] = winner
            kept = [x for x in kept if x["id"] != i] + [winner]
            alias.append({"parent": loser["parent"], "term": loser["term"],
                          "reason": f"same technology as the new tag `{i}`, which sits under "
                                    f"{winner['parent']}"})
            moved.append((i, loser["parent"], winner["parent"]))
        else:
            seen[i] = d; kept.append(d)
    promote = kept

    # A tag must carry documents: validation.md treats a zero-document tag as
    # either mis-ruled or one that should not exist. Checked here rather than
    # left for a human to notice, because the pass proposes the match rule and
    # has no way to test it.
    if corpus:
        tk = [(r.get("title") or "") + " ; " + " ; ".join(r.get("keywords") or [])
              for r in json.load(open(corpus))]
        still = []
        for d in promote:
            try:
                rx = re.compile(d["match"], re.I)
            except re.error as e:
                print(f"  demoted {d['term']}: bad regex ({e})", file=sys.stderr)
                alias.append({"parent": d["parent"], "term": d["term"],
                              "reason": f"proposed match rule did not compile: {e}"})
                continue
            if not any(rx.search(t) for t in tk):
                print(f"  demoted {d['term']}: its match rule tags no document", file=sys.stderr)
                alias.append({"parent": d["parent"], "term": d["term"],
                              "reason": "proposed as a tag, but the proposed match rule tags no "
                                        "document; a tag carrying nothing is mis-ruled or should "
                                        "not exist"})
                continue
            still.append(d)
        promote = still

    clash = sorted({d["id"] for d in promote} & set(by_id))
    if clash:
        sys.exit(f"proposed ids already exist: {clash}")

    # insert each new tag after its parent's existing subtree, so file order
    # keeps a parent adjacent to its children
    def subtree_end(pid):
        i = next(k for k, e in enumerate(entries) if e["id"] == pid)
        j = i + 1
        while j < len(entries):
            anc, t, s = False, entries[j].get("parent"), set()
            while t and t not in s:
                s.add(t)
                if t == pid:
                    anc = True; break
                t = by_id[t].get("parent") if t in by_id else None
            if not anc:
                break
            j += 1
        return j

    added = 0
    for d in sorted(promote, key=lambda x: x["parent"]):
        e = {"id": d["id"], "parent": d["parent"], "kind": "technology",
             "desc": d["desc"], "match": [d["match"]]}
        entries.insert(subtree_end(d["parent"]), e)
        by_id[d["id"]] = e
        added += 1

    # aliases: append, skipping anything that would shadow a tag id
    ids = set(by_id)
    n_alias, shadowed = 0, []
    for d in alias:
        parent = by_id.get(d["parent"])
        if not parent:
            continue
        term = d["term"]
        if str(term).lower().replace(" ", "-") in ids:
            shadowed.append((d["parent"], term)); continue
        cur = parent.get("aliases") or []
        if str(term).lower() in {str(x).lower() for x in cur}:
            continue          # case-insensitive: the engine compares lowercased
        rebuilt = {}
        for k, v in parent.items():
            if k == "aliases":
                continue
            rebuilt[k] = v
            if k == "desc":
                rebuilt["aliases"] = cur + [term]
        if "aliases" not in rebuilt:
            rebuilt["aliases"] = cur + [term]
        parent.clear(); parent.update(rebuilt); n_alias += 1

    for tid, (old, new) in NARROW_PARENT.items():
        e = by_id[tid]
        e["match"] = [new if m == old else m for m in e.get("match", [])]

    removed = 0
    for e in entries:
        if "covers" in e:
            del e["covers"]; removed += 1

    out = yaml.dump(doc, Dumper=Dm, sort_keys=False, allow_unicode=True, width=200)
    if not a.dry_run:
        open(a.taxonomy, "w").write(out)

    print(f"{'would add' if a.dry_run else 'added'} {added} child tags, {n_alias} aliases; "
          f"dropped {len(drops)}; removed `covers` from {removed} tags")
    for i, loser, winner in moved:
        print(f"  duplicate {i}: kept under {winner}, alias under {loser}")
    for parent, term in shadowed:
        print(f"  skipped alias {term} on {parent}: shadows a tag id", file=sys.stderr)
    print(f"  tags {len(entries)} (was {len(entries) - added})")


if __name__ == "__main__":
    main()
