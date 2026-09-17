# RFC Subject Tags — Validation

The checks a rebuild must pass, and the figures from the current build. Each check names the requirement in README.md it serves. The figures section is rewritten by `regen.py`.

## Checks

### Structural (R3, R5, R12)

`engine.Taxonomy('taxonomy.yaml')` loads without error. It asserts:

- every id unique, and every `parent`, `yields_to`, `implies` and `decomposes_to` reference resolves;
- depth at most four levels;
- every root is a topic;
- no catch-all names.

### Coverage (R7, R8)

- No RFC without a tag.
- In the served view, no RFC without a topic.

### Budget (R4, R6)

- Every assignment is emitted as full paths.
- Mean tags per RFC, counting ancestors, is between 1 and 10.
- Report the distribution and the maximum.

### Humor (R16)

Both directions:

- every `humor` document carries nothing else;
- every day-dated document, and every RFC listed in the `humor` tag's `documents` field, carries `humor`.

### Unused and single-document tags (R9, R13)

- No tag is carried by zero documents — such a tag is either mis-ruled or should not exist.
- List tags carried by exactly one document for review against R13.

### Stability replay (R17, R18)

1. Sort the corpus by (year, month, RFC number).
2. Record each tag's first appearance.
3. Report the distribution of new-tags-per-RFC and list every RFC that debuts two or more.
4. Repeat on the topic axis alone and list debuts after 2003.

### Spot checks (R19, R20)

A fixed list of well-known RFCs with expected results:

| RFC | Expected |
|---|---|
| 791 | ipv4 |
| 793 | tcp |
| 822 | message-format |
| 1034 | dns |
| 2616 | http |
| 8446 | tls |
| 9000 | quic, udp — topic `transport` only |
| 9001 | quic + security |
| 9002 | quic + congestion-control |
| 9312 | quic + network-management |
| 3261 | sip |
| 2119 | terminology |
| 1149 | humor |
| 6762 | mdns, dns |
| 5317 | no `jwt` |

### Search grounding (R9)

For each topic, confirm the name is phrasing people search for, not a librarian's abstraction. Record the phrasing considered when a topic is added.

### Rule audits (R9)

- **Embedded words.** For every rule alternative that is a plain word or phrase without `\b`, find corpus matches inside longer words and confirm each is an intended stem.
- **Acronym case.** For every alternative written as an uppercase acronym, list matches whose actual text is not uppercase and confirm each is a lowercase author keyword rather than an English word.

### Working groups (R10, R11)

- **Absorption.** For each working group mapped only to topics or to a parent technology, count its documents and the title mentions of the group's own name. Ten or more documents with no tag of their own is a missing technology.
- **Names.** For every tag whose slug matches a working-group acronym, count RFCs whose title, keywords or abstract use the term other than as a reference to the group. Zero such uses means the tag is named for the group, not the technology, and must be renamed or removed.

### Overlap

List non-ancestor tag pairs with Jaccard similarity above 0.35 over their document sets. Confirm each reflects a real relationship, not a map entry assigning both.

### Root leaks (R12)

For each root, count the RFCs carrying it as a leaf tag beside a technology from another root, and read the titles. Correct co-occurrence looks like RFC 1812 (`ipv4`, `routing`) or RFC 5095 (`ipv6`, `routing`): the title is about the root's subject. A leak looks like RFC 3268 (`tls`, `transport`): the root's rule matched a word inside a protocol name — Transport Layer Security, Real-Time Transport Protocol, Generic Routing Encapsulation, JSON Web Token. In the Overlap view of `rfc-tags.html` leaks show as a root nested inside an unrelated technology. The check has a second half: after tightening a root rule, list documents that carried the root before and no longer do, and read those titles too — RFC 3222 (FIB-based router performance) and RFC 6192 (the router control plane) are routing documents that a tightened `routing` rule once dropped. A document that loses its only tag falls to the abstract fallback and may pick up unrelated tags there. Leaks matter more than search noise: every one fires a notification to every subscriber of the root.

### Topic gaps (R8, R10)

List served-view documents whose only topics are roots but whose titles contain aspect words — manageability, operational, congestion, mobility, compression, discovery, authentication — and inspect for missing rules.

### Keyword noise (R20)

For each topic-implying technology, list assignments with no title evidence and confirm they are working-group-derived rather than incidental keywords.

### Independence (R14, R15)

By inspection of the tree: no tag names an IETF area, a status, a stream or a date.

### Aliases and covers (R21, R22)

- **Structural.** `engine.Taxonomy` fails if any `aliases` or `covers` entry equals a tag id; a term claimed by more than one tag is reported, not failed — `sftp` legitimately belongs to both `ftp` and `ssh`.
- **Grounding.** Every entry is used as that name in RFC text. `curation/alias_pass.py` measures this against the full-text corpus: `raw` documents containing the term, `ctx` of those the tag's own `match` rules also fire on, and the precision `ctx/raw`. Entries below the precision floor are held for review rather than merged.
- **Precision is a noise filter, not a semantic check.** It measures topical co-occurrence, so it catches `disruption` under `dtn` (2%) but not `sftp` under `ftp` (100%) — documents about SFTP genuinely discuss FTP. Whether a term names *this* technology or a neighbouring one stays a reading judgement.
- **Aliases against covers.** Confirm each `aliases` entry denotes the same thing the tag denotes, and each `covers` entry denotes something else the tag stands in for. A `covers` entry whose subject has acquired its own tag must move out.

### Engine round-trip

When the engine or the YAML schema changes, re-run against the previous `rfc-tags.json` and list every RFC whose `tags` differ. Differences must be explainable — at the YAML-to-engine migration nine RFCs differed, all in which tags survive the seven-tag cap or the three-tag abstract fallback, and none in tags matched.

## Records

- `alias-candidates.csv` — alias candidates extracted from an external taxonomy, with RFC usage counts, held for review against the alias criterion in README.md.

## Figures (current build)

### Curated tree

- **Tags:** 542 — 18 roots, 266 at level 2, 233 at level 3, 25 at level 4; 461 technology, 81 topic.
- **Coverage:** 0 untagged.
- **Tags per RFC (with ancestors):** mean 3.63, median 3, max 16.
- **Distribution:** 1:642 · 2:2,611 · 3:2,181 · 4:1,587 · 5:1,352 · 6:699 · 7:389 · 8:207 · 9:93 · 10:36 · 11:22 · 12:8 · 13:4 · 14:3 · 16:1.
- **Over ten tags:** 38 documents (0.4%), all multi-technology cross-area specifications.
- **Unused tags:** 0.
- **Single-document tags:** 22 — amateur-radio, arc, data-center-networking, ebpf, eigrp, ffv1, http-caching, irtp, lpwan, mospf, oblivious-dns, ovsdb, password-hashing, ratp, sdf, sframe, teep, tmux, tvr, whip, xacml, y2k.
- **Humor:** 74 documents, 0 exclusivity violations.
- **Stability replay:** 9,302 RFCs debut no tag, 525 debut one, 7 debut two, 1 debut three. The 8 multi-debut cases are parent-and-child pairs founding a branch, plus RFC 2430 preceding the MPLS architecture into print.

### Served view

- **Axes:** 461 technology tags, 75 topics.
- **Zero-technology documents:** 1,440 — governance, process, humor, ARPANET-era notes, general-subject documents.
- **Zero-topic documents:** 0.
- **Per RFC:** technology mean 1.75, topic mean 2.00, combined mean 3.75.
- **Over ten combined:** 44 documents (0.4%); maximum 16.
- **Documents whose only topics are roots:** 5,350.
- **Topic replay:** 5 documents debut two topics, all in the founding years. Debuts since 2003: emergency-services (2003), nat-traversal (2003), iot (2006), energy-management (2013), autonomic-networking (2014), telemetry (2019), sustainability (2024).
