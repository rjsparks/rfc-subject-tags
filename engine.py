#!/usr/bin/env python3
"""RFC subject tag engine: reads taxonomy.yaml, assigns tags to RFC records, derives the two-axis view.

Usage:  python3 engine.py [taxonomy.yaml] [rfcs.json]
Writes  rfc-tags.json: for every RFC its leaf tags, full paths, and technology/topic coordinates.
All per-tag knowledge lives in the YAML; this file is the algorithm only.
"""
import json, re, sys, collections
import yaml

MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December']

class Taxonomy:
    def __init__(self, path='taxonomy.yaml'):
        doc = yaml.safe_load(open(path))
        self.engine = doc['engine']
        self.tags = doc['tags']                      # list, in file order
        self.by_id = {t['id']: t for t in self.tags}
        self.order = [t['id'] for t in self.tags]
        self._validate()
        self.path = {t: self._path(t) for t in self.by_id}
        self.root = {t: p[0] for t, p in self.path.items()}
        self.kind = {t: self.by_id[t]['kind'] for t in self.by_id}
        self.desc = {t: self.by_id[t]['desc'] for t in self.by_id}
        flags = re.I
        self.match = {t: [re.compile(p, flags) for p in e.get('match', [])] for t, e in self.by_id.items()}
        self.match_title = {t: [re.compile(p, flags) for p in e.get('match_title_only', [])] for t, e in self.by_id.items()}
        self.groups = collections.defaultdict(list)
        for t, e in self.by_id.items():
            for g in e.get('groups', []): self.groups[g].append(t)
        self.yields = {t: set(e.get('yields_to', [])) for t, e in self.by_id.items() if e.get('yields_to')}
        self.implies = {t: list(e.get('implies', [])) for t, e in self.by_id.items() if e.get('implies')}
        self.decomp = {t: list(e.get('decomposes_to', [])) for t, e in self.by_id.items() if e.get('decomposes_to')}
        self.max_year = {t: e['max_year'] for t, e in self.by_id.items() if 'max_year' in e}

    def _path(self, t):
        p = [t]
        while 'parent' in self.by_id[p[-1]]: p.append(self.by_id[p[-1]]['parent'])
        return tuple(reversed(p))

    def _validate(self):
        ids = [t['id'] for t in self.tags]
        dup = [i for i, c in collections.Counter(ids).items() if c > 1]
        assert not dup, f'duplicate tag ids: {dup}'
        # aliases are searched, never displayed. One equal to a tag id would
        # shadow that tag, so it is fatal. A term claimed by two tags is
        # legitimate (pkix belongs to both pki and x509) and only warns.
        claims = collections.defaultdict(list)
        for e in self.tags:
            for a in e.get('aliases') or []:
                key = str(a).strip().lower()
                assert key.replace(' ', '-') not in set(ids) - {e['id']}, \
                    f'{e["id"]}: alias {a!r} shadows an existing tag id'
                claims[key].append(e['id'])
        for term, owners in sorted(claims.items()):
            if len(owners) > 1:
                print(f'note: {term!r} is claimed by {", ".join(sorted(owners))}', file=sys.stderr)
        for e in self.tags:
            assert e['kind'] in ('technology', 'topic'), e['id']
            assert not any(b in e['id'] for b in ('misc', 'other', 'general')), f'catch-all name: {e["id"]}'
            if 'parent' in e: assert e['parent'] in self.by_id, f'{e["id"]}: unknown parent {e["parent"]}'
            else: assert e['kind'] == 'topic', f'root {e["id"]} must be a topic'
            for f in ('yields_to', 'implies', 'decomposes_to'):
                for x in e.get(f, []): assert x in self.by_id, f'{e["id"]}.{f}: unknown tag {x}'
        for t in self.by_id:
            assert len(self._path(t)) <= 4, f'too deep: {t}'

    # ---- assignment -------------------------------------------------------
    def assign(self, rfc):
        E = self.engine; hum = E['humor']['tag']
        if rfc.get('day') or rfc['id'] in self.by_id[hum].get('documents', []):
            return [hum]
        tags = []
        year = rfc.get('year') or 0
        def add(ts):
            for t in ts:
                if t not in tags and not (t in self.max_year and year > self.max_year[t]):
                    tags.append(t)
        wg = rfc.get('wg')
        wg_tags = set(self.groups.get(wg, [])) if wg else set()
        add(wg_tags)
        title = rfc.get('title') or ''
        tk = title + ' ; ' + ' ; '.join(rfc.get('keywords') or [])
        for t in self.order:
            if any(rx.search(tk) for rx in self.match[t]): add([t])
        for t in self.order:
            if any(rx.search(title) for rx in self.match_title[t]): add([t])
        if not tags:
            abstract = rfc.get('abstract') or ''
            hits = [t for t in self.order if any(rx.search(abstract) for rx in self.match[t])]
            add(self._prioritise(hits, wg_tags)[:E['abstract_fallback_max_tags']])
        era = E['era_fallback']
        if not tags and rfc.get('year') and rfc['year'] <= era['max_year'] and rfc.get('stream') == era['stream']:
            tags = [era['tag']]
        tags = self._suppress(tags)
        tags = [t for t in tags if not any(o != t and t in self.path[o] for o in tags)]   # ancestor rule
        implied = {x for o in tags for x in self.implies.get(o, [])}
        tags = [t for t in tags if t not in implied]                                      # implied topics are not leaves
        return self._prioritise(tags, wg_tags)[:E['max_leaf_tags']]

    def _suppress(self, tags):
        """Remove generic tags that yield to a present specific. A specific counts only once it is
        settled - it has no yields_to of its own, or none of its own specifics are present - so that a
        keyword-noise tag removed by suppression cannot itself suppress something else."""
        present = list(tags)
        def settled(s): return s not in self.yields or not (self.yields[s] & set(present))
        changed = True
        while changed:
            changed = False
            for t in list(present):
                if t in self.yields and any(s in present and settled(s) for s in self.yields[t]):
                    present.remove(t); changed = True
        for t in list(present):                                  # any cycle left over: plain rule
            if t in self.yields and self.yields[t] & set(present): present.remove(t)
        return present

    def _prioritise(self, tags, wg_tags=()):
        """Order used when limits truncate: working-group tags first, then deeper (more specific) tags, then file order."""
        pos = {t: i for i, t in enumerate(self.order)}
        return sorted(tags, key=lambda t: (t not in wg_tags, -len(self.path[t]), pos[t]))

    def closure(self, tags):
        out = set()
        for t in tags: out.update(self.path[t])
        return out

    # ---- served view ------------------------------------------------------
    def two_axis(self, tags):
        tech, topic = set(), set()
        for t in self.closure(tags):
            if t in self.decomp:
                topic.update(self.decomp[t]); continue
            if self.kind[t] == 'topic':
                topic.add(t); continue
            tech.add(t)
            topic.update(self.implies.get(t, []))
        return sorted(tech), sorted(topic)

def load_rfcs(path='rfcs.json'):
    return json.load(open(path))

if __name__ == '__main__':
    tax = Taxonomy(sys.argv[1] if len(sys.argv) > 1 else 'taxonomy.yaml')
    rfcs = load_rfcs(sys.argv[2] if len(sys.argv) > 2 else 'rfcs.json')
    out = {}
    for r in rfcs:
        leaf = tax.assign(r)
        tech, topic = tax.two_axis(leaf)
        out[r['id']] = {'title': r.get('title'), 'year': r.get('year'), 'tags': leaf,
                        'paths': sorted('/'.join(p) for p in {tax.path[t][:i] for t in leaf for i in range(1, len(tax.path[t]) + 1)}),
                        'technology': tech, 'topic': topic}
    json.dump(out, open('rfc-tags.json', 'w'), indent=1)
    used = collections.Counter(t for v in out.values() for t in v['tags'])
    print(f"{len(tax.by_id)} tags ({dict(collections.Counter(tax.kind.values()))}); untagged {sum(1 for v in out.values() if not v['tags'])}; "
          f"unused {[t for t in tax.by_id if t not in used]}; zero-topic {sum(1 for v in out.values() if not v['topic'])}")
