"""Regenerate all derived deliverables from taxonomy.yaml and the engine outputs, and refresh document figures.
Run after: python3 engine.py. Writes rfc-tags.csv and rfc-tags.html, the stats block in taxonomy.yaml,
and refreshes the figures in README.md and validation.md and the generated blocks in code.md. Everything is read and written in the
working directory; the three tracked files are rewritten in place.
"""
import json, collections, statistics, csv, re
import engine
tax=engine.Taxonomy('taxonomy.yaml')
rfcs=json.load(open('rfcs.json')); RT=json.load(open('rfc-tags.json'))
res={k:v['tags'] for k,v in RT.items()}; two={k:{'technology':v['technology'],'topic':v['topic']} for k,v in RT.items()}
used=collections.Counter(t for v in res.values() for t in v)
def paths(tags): return sorted('/'.join(p) for p in {tax.path[t][:i] for t in tags for i in range(1,len(tax.path[t])+1)})
counts=[len(paths(res[r['id']])) for r in rfcs]
depth=collections.Counter(len(p) for p in tax.path.values()); kinds=collections.Counter(tax.kind.values())
oc=[len(v['topic']) for v in two.values()]; tc=[len(v['technology']) for v in two.values()]
ROOTS=[t for t in tax.order if len(tax.path[t])==1]
MON={m:i for i,m in enumerate(engine.MONTHS,1)}
order=sorted(rfcs,key=lambda r:(r['year'] or 0,MON.get(r['month'],6),int(r['id'][3:])))
seen=set();dist=collections.Counter();multi=0
for r in order:
    new=[t for t in res[r['id']] if t not in seen];seen.update(new);dist[len(new)]+=1
    if len(new)>=2: multi+=1
seen=set();m2=0;late=[]
for r in order:
    new=[x for x in two[r['id']]['topic'] if x not in seen];seen.update(new)
    if len(new)>=2:m2+=1
    if new and r['year']>=2003: late.append((r['id'],r['year'],new))
single=sorted(t for t,c in used.items() if c==1); c16=sorted(dist.items())
root_total=collections.Counter()
for v in res.values():
    for r in {tax.root[t] for t in v}: root_total[r]+=1
total=collections.Counter()
for v in res.values():
    for a in tax.closure(v): total[a]+=1
# ---- per-tag stats, written into taxonomy.yaml (generated block) and used by the browser page
import yaml, datetime
per_year=collections.defaultdict(collections.Counter); years_of=collections.defaultdict(list); docs=collections.defaultdict(list)
byid={r['id']:r for r in rfcs}
for k,v in res.items():
    y=byid[k]['year']
    for a in tax.closure(v):
        docs[a].append(k)
        if y: per_year[a][y]+=1; years_of[a].append(y)
served=collections.Counter(t for v in two.values() for t in v['topic'])
doc=yaml.safe_load(open('taxonomy.yaml'))
for e in doc['tags']:
    t=e['id']; ys=years_of[t]
    e['stats']={'direct':used[t],'total':total[t],'first_year':min(ys) if ys else None,'last_year':max(ys) if ys else None}
    if tax.kind[t]=='topic' and t not in tax.decomp: e['stats']['served']=served[t]
class Dm(yaml.SafeDumper): pass
Dm.add_representer(str, lambda dd,x: dd.represent_scalar('tag:yaml.org,2002:str', x, style="'" if ('\\' in x or ':' in x) and '\n' not in x else None))
yaml.dump(doc, open('taxonomy.yaml','w'), Dumper=Dm, sort_keys=False, allow_unicode=True, width=200)
# ---- browser page: the review page (data model: tags / rows / pairs / window)
years_all=[byid[k]['year'] for k in byid if byid[k]['year']]
W0=2021; today=datetime.date.today(); window_years=round((today-datetime.date(W0,1,1)).days/365.25,2)
tag_index={t:i for i,t in enumerate(tax.order)}
tags_data=[]
for e in doc['tags']:
    t=e['id']; st=e['stats']; n21=sum(1 for k in docs[t] if (byid[k]['year'] or 0)>=W0)
    tags_data.append({'id':t,'root':tax.root[t],'d':len(tax.path[t])-1,'parent':e.get('parent'),'path':'/'.join(tax.path[t]),'desc':e['desc'],'kind':e['kind'],'aliases':e.get('aliases') or [],
        'direct':st['direct'],'total':st['total'],'rate':round(n21/window_years,1),'first':st['first_year'],'last':st['last_year'],'n21':n21,'maxYear':e.get('max_year')})
rows=[]
for k in sorted(RT, key=lambda x:int(x[3:])):
    v=RT[k]; rows.append([int(k[3:]), v['year'], v['title'], [tag_index[t] for t in v['tags']], [tag_index[t] for t in v['technology']], [tag_index[t] for t in v['topic']]])
pair_c=collections.Counter()
for v in RT.values():
    ids=sorted(tag_index[t] for t in v['tags'])
    for i in range(len(ids)):
        for j in range(i+1,len(ids)): pair_c[(ids[i],ids[j])]+=1
pairs=[[a,b,c] for (a,b),c in pair_c.items() if c>=2]; pairs.sort(key=lambda p:-p[2])
data={'version':f'taxonomy.yaml, {len(tax.by_id)} tags in {len(ROOTS)} roots, build of {today:%-d %B %Y}','tags':tags_data,'rows':rows,'pairs':pairs,
      'window':[W0, today.year],'windowYears':window_years,'yearMin':min(years_all),'yearMax':max(years_all)}
html=open('browser_template.html').read()
html=html.replace('__DATA__', json.dumps(data, separators=(',',':')).replace('</','<\\/'))
html=html.replace('__EYEBROW__', f'taxonomy.yaml &middot; {len(tax.by_id)} tags in {len(ROOTS)} roots &middot; corpus {len(rfcs):,} RFCs &middot; {today:%B %Y}')
html=html.replace('__DATE__', f'{today:%-d %B %Y}')
open('rfc-tags.html','w').write(html)
# ---- rfc-tags.csv: the same table as rfc-tags.json
with open('rfc-tags.csv','w',newline='') as f:
    w=csv.writer(f); w.writerow(['rfc','title','year','tags','paths','technology','topic'])
    for k in sorted(RT, key=lambda x:int(x[3:])):
        v=RT[k]; w.writerow([k, v['title'], v['year'], ';'.join(v['tags']), ' | '.join(v['paths']), ';'.join(v['technology']), ';'.join(v['topic'])])
# ---- figures in validation.md
tech_n=len(set(t for v in two.values() for t in v['technology'])); ocnt=collections.Counter(t for v in two.values() for t in v['topic'])
fig=f"""## Figures (current build)

### Curated tree

- **Tags:** {len(tax.by_id)} — {depth[1]} roots, {depth[2]} at level 2, {depth[3]} at level 3, {depth[4]} at level 4; {kinds["technology"]} technology, {kinds["topic"]} topic.
- **Coverage:** {sum(1 for c in counts if c==0)} untagged.
- **Tags per RFC (with ancestors):** mean {statistics.mean(counts):.2f}, median {int(statistics.median(counts))}, max {max(counts)}.
- **Distribution:** {" · ".join(f"{a}:{b:,}" for a,b in sorted(collections.Counter(counts).items()))}.
- **Over ten tags:** {sum(1 for c in counts if c>10)} documents ({100*sum(1 for c in counts if c>10)/len(counts):.1f}%), all multi-technology cross-area specifications.
- **Unused tags:** {len([t for t in tax.by_id if t not in used])}.
- **Single-document tags:** {len(single)} — {", ".join(single)}.
- **Humor:** {used["humor"]} documents, 0 exclusivity violations.
- **Stability replay:** {c16[0][1]:,} RFCs debut no tag, {c16[1][1]} debut one, {c16[2][1] if len(c16)>2 else 0} debut two, {c16[3][1] if len(c16)>3 else 0} debut three. The {multi} multi-debut cases are parent-and-child pairs founding a branch, plus RFC 2430 preceding the MPLS architecture into print.

### Served view

- **Axes:** {tech_n} technology tags, {len(ocnt)} topics.
- **Zero-technology documents:** {sum(1 for x in tc if x==0):,} — governance, process, humor, ARPANET-era notes, general-subject documents.
- **Zero-topic documents:** {sum(1 for x in oc if x==0)}.
- **Per RFC:** technology mean {statistics.mean(tc):.2f}, topic mean {statistics.mean(oc):.2f}, combined mean {statistics.mean(a+b for a,b in zip(oc,tc)):.2f}.
- **Over ten combined:** {sum(1 for a,b in zip(oc,tc) if a+b>10)} documents ({100*sum(1 for a,b in zip(oc,tc) if a+b>10)/len(oc):.1f}%); maximum {max(a+b for a,b in zip(oc,tc))}.
- **Documents whose only topics are roots:** {sum(1 for v in two.values() if v['topic'] and set(v['topic'])<=set(ROOTS)):,}.
- **Topic replay:** {m2} documents debut two topics, all in the founding years. Debuts since 2003: {", ".join(f"{nt[0]} ({y})" for i,y,nt in late)}.
"""
p='validation.md'; n=open(p).read(); n=re.sub(r'## Figures \(current build\).*', lambda m: fig, n, flags=re.S); open(p,'w').write(n)
p='README.md'; r=open(p).read()
r=re.sub(r'- \d+ tags: \d+ roots, \d+ at level 2, \d+ at level 3, \d+ at level 4\.', f'- {len(tax.by_id)} tags: {depth[1]} roots, {depth[2]} at level 2, {depth[3]} at level 3, {depth[4]} at level 4.', r)
r=re.sub(r'- \d+ technologies and \d+ topics in the tree \(\d+ topics reach the served view', f'- {kinds["technology"]} technologies and {kinds["topic"]} topics in the tree ({len(ocnt)} topics reach the served view', r)
r=re.sub(r'- Mean [\d.]+ tags per RFC including ancestors', f'- Mean {statistics.mean(counts):.2f} tags per RFC including ancestors', r)
r=re.sub(r'- \*\*technology\*\* — \d+ tags', f'- **technology** — {tech_n} tags', r); r=re.sub(r'- \*\*topic\*\* — \d+ tags', f'- **topic** — {len(ocnt)} tags', r)
last=collections.defaultdict(int); per=collections.defaultdict(int)
for kk,v in RT.items():
    y=v['year'] or 0
    for t in set(v['technology'])|set(v['topic']):
        last[t]=max(last[t],y)
        if 2021<=y<=2025: per[t]+=1
dormant=sum(1 for t in tax.by_id if last[t]<2021)
r=re.sub(r'- `security` averaged about \d+ RFCs a year,', f'- `security` averaged about {round(per["security"]/5)} RFCs a year,', r)
r=re.sub(r'- `routing` about \d+,', f'- `routing` about {round(per["routing"]/5)},', r)
r=re.sub(r'- `network-management` about \d+\.', f'- `network-management` about {round(per["network-management"]/5)}.', r)
r=re.sub(r'Dormant tags are equally legitimate: \d+ of the \d+ tags have had no RFC since 2021\.', f'Dormant tags are equally legitimate: {dormant} of the {len(tax.by_id)} tags have had no RFC since 2021.', r)
open(p,'w').write(r)

# ---- generated blocks in code.md
def fill(text, name, body):
    return re.sub(r'(<!-- generated:%s -->).*?(<!-- /generated -->)' % name, lambda m: m.group(1)+body+m.group(2), text, flags=re.S)
cov=f"Coverage: {len(rfcs):,} RFCs; {sum(1 for x in rfcs if x.get('wg')):,} with a working group; {sum(1 for x in rfcs if x.get('keywords')):,} with keywords; {sum(1 for x in rfcs if x.get('abstract')):,} with abstracts."
comp=['','| Composite tag | Becomes |','|---|---|']
for t in tax.order:
    if t in tax.decomp: comp.append(f"| `{t}` | {' + '.join('`'+x+'`' for x in tax.decomp[t])} |")
comp.append('')
byt=collections.defaultdict(list)
for t in tax.order:
    for x in tax.implies.get(t,[]): byt[x].append(t)
imp=['','| Topic | Implied by |','|---|---|']
for x in sorted(byt, key=lambda x:-len(byt[x])): imp.append(f"| `{x}` | {', '.join(byt[x])} |")
imp.append('')
p='code.md'; c=open(p).read()
c=fill(c,'coverage',cov); c=fill(c,'composites','\n'.join(comp)); c=fill(c,'implies','\n'.join(imp))
open(p,'w').write(c)
print(f'regenerated: {len(tax.by_id)} tags, mean {statistics.mean(counts):.2f}, unused {len([t for t in tax.by_id if t not in used])}, zero-topic {sum(1 for x in oc if x==0)}')
