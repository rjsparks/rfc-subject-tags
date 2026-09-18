# RFC Subject Tags — Code and Outputs

How the tag system is built: the input corpus, the taxonomy file, the engine that assigns tags and derives the served view, and every file the pipeline produces. Aims, requirements and semantics are in README.md; acceptance checks and figures are in validation.md.

## Files at a glance

### Normative (edit this)

| File | Contains |
|---|---|
| `taxonomy.yaml` | Every tag with its parent, kind, description, optional `aliases` (searched, never displayed), match rules, working groups, suppression, decomposition and implied topics; plus engine parameters. Each entry also carries a generated `stats` block (see below) that `regen.py` rewrites and curators do not edit |

### Code

| File | Purpose |
|---|---|
| `engine.py` | Reads `taxonomy.yaml`, validates it, assigns tags to RFC records, derives the two-axis view |
| `make_corpus_from_index.py` | Builds `rfcs.json` from the RFC Editor's `rfc-index.xml`, downloading it if absent |
| `make_corpus_from_local.py` | Builds `rfcs.json` from a directory of per-RFC metadata files instead |
| `regen.py` | Regenerates the generated files, writes the `stats` blocks into `taxonomy.yaml`, and refreshes the figures in validation.md and README.md and the generated blocks in this file |
| `browser_template.html` | The review page (five views: Vocabulary, Co-occurrence, Lifespan, Overlap, All RFCs) with its data removed; `regen.py` embeds the current data to produce `rfc-tags.html`. Fonts are embedded so the page works offline |
| `alias_candidates.py` | Collects acronyms that appear in an RFC title beside their expansion and that no reader can reach by searching the tag they belong to. Runs in CI after `regen.py`; calls no model and needs no network |

### Generated (never edit by hand)

None of these is in the repository — they are gitignored build products. A local run produces
them in the working directory, and CI publishes the current build to GitHub Pages:

| Artifact | Published at |
|---|---|
| `rfc-tags.html` | <https://rfc-editor.github.io/rfc-subject-tags/> |
| `rfc-tags.json` | <https://rfc-editor.github.io/rfc-subject-tags/rfc-tags.json> |
| `rfc-tags.csv` | <https://rfc-editor.github.io/rfc-subject-tags/rfc-tags.csv> |
| `rfcs.json` | <https://rfc-editor.github.io/rfc-subject-tags/rfcs.json> |
| `alias-candidates.json` | <https://rfc-editor.github.io/rfc-subject-tags/alias-candidates.json> |

The build runs daily, so the published page tracks the current corpus. The figures committed in
README.md and validation.md describe the last curation run instead, and drift from it as RFCs
publish; the page carries its own build date so the two can be told apart.

| File | Contents |
|---|---|
| `rfcs.json` | Corpus metadata, one record per RFC — the engine's input, produced by either corpus script. Fetched fresh at build time; the snapshot each build used is published alongside the other artifacts, so a published build can be reproduced exactly |
| `rfc-tags.json` | Per RFC: title, year, leaf `tags`, full `paths` (R4), and `technology` / `topic` coordinates for the served view |
| `rfc-tags.csv` | The same table for spreadsheet use; list fields are `;`-separated, paths `|`-separated |
| `alias-candidates.json` | Alias candidates harvested from RFC titles, most-seen first. A curator reads it; nothing consumes it |
| `rfc-tags.html` | Self-contained review page. **Vocabulary**: the tree with corpus count and notifications-per-year (since 2021) per tag, search, technology/topic filter, multi-select with AND/OR and the matching RFCs. **Co-occurrence**: tag pairs sharing RFCs. **Lifespan**: each tag's first-to-last year, live or dormant. **Overlap**: Jaccard and one-way overlap flags for redundant or nested pairs. **All RFCs**: look-up with tags and served technology/topic coordinates |

### To reproduce

```
pip install -r requirements.txt                          # PyYAML, the only dependency
python3 make_corpus_from_index.py                        # rfcs.json from rfc-index.xml (downloads it)
#   or: python3 make_corpus_from_local.py ~/Data/RFCs rfcs.json
python3 engine.py taxonomy.yaml rfcs.json                # validates, assigns, derives; writes rfc-tags.json
python3 regen.py                                         # rendered files and document figures
```

Every step reads and writes in the working directory. A full run leaves `rfc-index.xml`,
`rfcs.json`, `rfc-tags.json`, `rfc-tags.csv` and `rfc-tags.html` beside the sources; all are
gitignored build products.

Then run the checks in validation.md.

## Corpus

### Record format

One record per published RFC:

| Field | Notes |
|---|---|
| `id` | `RFC9000` |
| `title` | |
| `year`, `month` | |
| `day` | Present only when the source records a day of month — see below |
| `keywords` | Author keywords |
| `abstract` | |
| `wg` | Producing working group, lower-cased; absent for non-WG streams |
| `stream`, `status` | Informational only |

### Sources

- The rfc-editor.org index (`rfc-index.xml`), parsed to `rfcs.json` by `make_corpus_from_index.py`. <!-- generated:coverage -->Coverage: 9,836 RFCs; 7,244 with a working group; 7,429 with keywords; 9,129 with abstracts.<!-- /generated -->
- A local directory of per-RFC `.json` files, via `make_corpus_from_local.py`. It expects one file per RFC, named `rfcNNNN.json`; the script defaults to `~/Data/RFCs` and takes the directory as its first argument. Field names vary between sources, so the script's `FIELD_MAP` is configurable — for example, the producing group may be under `source` rather than `wg`.

### The `day` assumption

In the rfc-editor index only the April 1st series carries a day of month: 71 documents, 63 dated exactly 1 April and the rest adjacent-day entries of the same series. The engine uses the presence of `day` as its humor test. If a metadata source records days for every RFC, replace that test with an explicit month-and-day check.

## The taxonomy file

`taxonomy.yaml` has three top-level keys: `version`, `engine` (parameters, below) and `tags`, a list in tree order. Everything known about a tag is in its one entry.

### Tag entry

```yaml
- id: dkim                       # slug; the tag name used everywhere
  parent: email-authentication   # omitted for roots
  kind: technology               # or topic; roots must be topic
  desc: DKIM (DomainKeys Identified Mail)
  match:                         # regexes, case-insensitive, against title + author keywords
  - '\bDKIM\b|domainkeys'
  groups: [dcrup, dkim]          # working groups whose RFCs take this tag
```

Optional fields:

| Field | Meaning |
|---|---|
| `match_title_only` | Regexes run against the title alone — for words too risky to match in keywords |
| `yields_to` | Tags whose presence removes this one (a generic yielding to a specific) |
| `implies` | Topics this technology entails by purpose (R20), added in the served view |
| `decomposes_to` | For the six composite topics: the topics they split into in the served view |
| `documents` | Explicit RFC list — used by `humor` for whimsical RFCs not dated 1 April |
| `max_year` | Hand-set cutoff: the tag is never assigned to an RFC published after this year (none currently set) |
| `stats` | **Generated.** `direct`, `total`, `first_year`, `last_year`, and for served topics `served`. Rewritten by `regen.py`; the browser's lifetime view reads `first_year`/`last_year` |

Description convention: the correct-case name, the expansion in parentheses for acronyms, then the scope, with no repetition of the name or expansion. See README.md.

### Validation on load

`engine.Taxonomy` refuses a file that has:

- duplicate ids, or a parent, `yields_to`, `implies` or `decomposes_to` reference to a tag that does not exist;
- a root that is not a topic, or a kind other than `technology`/`topic`;
- a path deeper than four levels;
- a catch-all name (`misc`, `other`, `general`).

### Engine parameters

| Key | Value | Effect |
|---|---|---|
| `max_leaf_tags` | 7 | Cap on leaf tags per RFC before closure |
| `abstract_fallback_max_tags` | 3 | Cap when only the abstract matched |
| `era_fallback` | `arpanet`, ≤ 1982, Legacy stream | Tag for otherwise-unmatched early working notes |
| `humor.tag` | `humor` | Sole tag for day-dated or listed documents |

### Editing the file

| To | Do |
|---|---|
| Add a technology | Add an entry with `parent`, `kind: technology`, `desc`, and `match` and/or `groups`. Its subject topic follows from its root automatically. |
| Add a topic | Add an entry with `kind: topic` and its rules; add it to `implies` on technologies whose purpose it is. |
| Move a tag between axes | Change `kind` — one word. (Breaking once subscriptions exist; see README.md.) |
| Split a tag | Add children with `parent` set to it; keep the parent. |
| Rename a tag | Change `id` and every reference to it in `parent`, `yields_to`, `implies` and `decomposes_to`; keep the old slug as a redirect in the serving layer. The loader reports any reference you miss. |

## Assignment

`engine.Taxonomy.assign(record)` returns the leaf tags for one RFC.

### Tiers

1. **Humor.** If `day` is present, or the RFC is in the humor tag's `documents`, the result is `['humor']` and processing stops.
2. **Working group.** Every tag whose `groups` contains the record's `wg`. (At every tier, a tag with `max_year` is skipped for RFCs published after it.)
3. **Match rules.** Every tag with a `match` regex that hits the title or author keywords.
4. **Title-only rules.** Every tag with a `match_title_only` regex that hits the title.
5. **Abstract fallback.** If nothing has matched, `match` regexes run against the abstract; at most `abstract_fallback_max_tags` are kept.
6. **Era fallback.** If still nothing, a Legacy-stream document from 1982 or earlier takes `arpanet`.
7. **Suppression.** A tag is removed when a tag in its `yields_to` is present and *settled* — that is, not itself about to be removed. This makes the result independent of file order while still letting a keyword-noise tag be removed before it can suppress something else.
8. **Ancestor rule.** A tag never sits in the leaf set beside its own descendant, so a root is a leaf only for documents about the subject in general.
   A topic that a present technology implies is likewise dropped from the leaf set; the served view adds it back, so it appears once, by implication.
9. **Cap.** If more than `max_leaf_tags` remain, keep working-group tags first, then deeper (more specific) tags, then earlier tags in file order.

`closure(tags)` expands leaf tags to their root-anchored paths, which appear as `paths` in `rfc-tags.json` (R4).

### Rule-writing discipline

Matching is case-insensitive over title and keywords, which makes several failure modes routine. Each rule below exists because it has bitten.

- **Anchor short words** with `\b` and handle plurals explicitly (`\bMIBs?\b`). Unanchored stems match inside longer words: "tribute" in *Attribute*, "graphic" in *cryptographic*, "port control protocol" inside *Transport Control Protocol*.
- **Never match a bare acronym that is also an English word** — SEND, TURN, STAMP, TRIP, LOST, OPAQUE, SIMPLE. Require the parenthesised form `(TURN)` or the expansion.
- **Disambiguate acronyms that collide across fields** by phrase or by `yields_to`: FEC (forward error correction vs forwarding equivalence class), JWT (the token vs the Joint Working Team), SPF (sender policy framework vs shortest path first).
- **Exclude compound uses**: "TCP/IP" from TCP; "mail routing", "Generic Routing Encapsulation" and "Routing Protocol for Low-Power…" from `routing`; "JSON Web Signature/Token" from `web`; "Constrained Application Protocol" from `applications`; "Transport Layer Security", "Real-Time Transport Protocol" and SSH's "Transport Layer Protocol" from `transport`; "Integrated Services Digital Network" from `intserv`; "Point-to-Point (P2P)" from `p2p`. Where a regex cannot exclude a name cleanly, `yields_to` does the job — `transport` yields to `tls`, `dtls`, `rtp`, `rtcp`, `srtp` and `ssh`. The general root rules are the most exposed to this, because protocol names routinely contain the words routing, web, application and data format; the Overlap view of `rfc-tags.html` shows such leaks as a root nested inside an unrelated technology.
- **Adjectives are not evidence.** Documents about security say "security"; "Secure Transport" in a title does not earn `security`.
- **A working group is not a tag.** When a group's output is a named technology with a following, the technology gets its own entry and the group goes in its `groups` (R10, R11).

The mechanical checks that enforce these are in validation.md.

## Served view

`engine.Taxonomy.two_axis(tags)` turns leaf tags into technology × topic coordinates:

1. Take the closure of the leaf tags.
2. Send each tag to the axis its `kind` names. Roots are topics and closure always includes the root, so every document's subjects are the roots of its paths.
3. Replace composite topics by their `decomposes_to` targets.
4. Add each technology's `implies` topics (R20).

Nothing is decided by hand at this stage; editing `taxonomy.yaml` and re-running re-derives the whole corpus.

### The composites

<!-- generated:composites -->
| Composite tag | Becomes |
|---|---|
| `dns-privacy` | `privacy` |
| `web-security` | `security` |
| `email-authentication` | `security` + `authentication` |
| `routing-security` | `security` |
| `multicast-security` | `multicast` + `security` |
| `operational-security` | `security` + `network-management` |
<!-- /generated -->

### Implication, by topic

<!-- generated:implies -->
| Topic | Implied by |
|---|---|
| `security` | dnssec, dane, cookies, hsts, token-binding, stir, srtp, sframe, rpki, bgpsec, tcpcrypt, send, savi, teep, supply-chain-integrity, oscore, edhoc, firmware-update, mud |
| `authentication` | http-authentication, stir, kerberos, gssapi, sasl, eap, pana, aaa, radius, diameter, tacacs, scim, federated-authentication, otp, pake, ident |
| `iot` | teep, coap, oscore, senml, sdf, 6lowpan, rpl, 6tisch, lpwan, schc, edhoc, firmware-update, mud |
| `multicast` | pim, igmp, mld, msdp, mospf, ssm, amt, bier, flute, norm, mvpn |
| `network-management` | bmp, snmp, mib, agentx, netconf, restconf, yang, syslog, i2rs, ovsdb |
| `ipv6-transition` | dns64, nat64, 6to4, teredo, ds-lite, map, 6rd, 464xlat, happy-eyeballs |
| `tunneling` | masque, pseudowire, vxlan, geneve, gre, ip-in-ip, l2tp |
| `congestion-control` | ecn, aqm, codel, pie, ledbat, pcn, conex |
| `performance-measurement` | rmon, owamp, twamp, stamp, lmap, ipfix, packet-capture |
| `privacy` | doh, dot, oblivious-dns, masque, oblivious-http, privacy-pass |
| `internationalization` | idn, eai, utf-8, unicode, language-tags, precis |
| `qos` | detnet, rsvp, diffserv, intserv, nsis, cops |
| `ip-mobility` | manet, mobile-ipv4, mobile-ipv6, pmipv6, nemo, hip |
| `compression` | rohc, deflate, gzip, brotli, zstd, ipcomp |
| `authorization` | oauth, gnap, xacml, ace |
| `transport-mapping` | doh, dot, http3 |
| `nat-traversal` | ice, stun, turn |
| `time-synchronization` | ntp, ptp, time-zones |
| `storage` | nfs, iscsi, rdma |
| `service-discovery` | dns-sd, slp |
| `reliable-multicast` | flute, norm |
| `traffic-engineering` | rsvp-te, pce |
| `routing-architecture` | lisp, ilnp |
| `multihoming` | shim6, hip |
| `calendaring` | icalendar, caldav |
| `oam` | bfd |
| `header-compression` | rohc |
| `addressing` | slaac |
| `routing` | rpl |
<!-- /generated -->

The `implies` field is consulted over the ancestor closure, so `dkim` inherits `security` through `email-authentication`. Two things the tables do not show because closure supplies them: every tag under the `security` root reaches `security` without an `implies` entry, and a composite's technology context (`dns` for `dns-privacy`) arrives as its ancestor.

## Regeneration

`regen.py` computes each tag's `stats` block and writes it back into `taxonomy.yaml`; renders `rfc-tags.csv`; builds `rfc-tags.html` by embedding into `browser_template.html` the tags (with `stats`, notification rate and lifetime), every RFC's row (leaf tags and served coordinates), and tag co-occurrence pairs; and refreshes the figures in validation.md and README.md. Run it after `engine.py`, after any change to the YAML.

Everything is read and written in the working directory. Three tracked files are rewritten **in place** — `taxonomy.yaml` (its `stats` blocks), `README.md` and `validation.md` (their figures) — so run it on a clean working tree and review the resulting diff as part of the change. The figures move whenever the corpus does: a run against an index one RFC newer than the last shifted two lines of validation.md and 24 lines of `stats`.

## Aliases

An optional list on a tag, searched but never shown as the tag's name — SNTP for
`ntp`, SSL for `tls`, GUID for `uuid`. An alias names the same thing the tag
names; a term naming a distinct technology with RFCs of its own belongs in the
tree as a child tag instead. See R21 in README.md.

Three pieces must agree or the field does nothing: `taxonomy.yaml` carries the
terms, `regen.py` passes them into the page's tag data, and
`browser_template.html` indexes them, an exact alias hit scoring 70 — above a
description word, below the tag's own id. `engine.Taxonomy` rejects an alias
equal to a tag id and reports one claimed by two tags without failing, since
`pkix` legitimately belongs to both `pki` and `x509`.

## Alias candidates

`alias_candidates.py` runs in CI and publishes `alias-candidates.json`. RFC
titles spell out an expansion on first use — "Simple Network Time Protocol
(SNTP)" — which is where variant names live. The script pairs each parenthesised
acronym with the expansion beside it, attributes it to the most specific tag
whose own `match` rules fire on that expansion, and drops anything a reader
could already reach by searching that tag, including its existing `aliases`.

Attribution by expansion is what makes the output usable. Without it every tag
on the RFC looks equally plausible and the list is dominated by co-occurrence —
`EPP` proposed for `rdap` *and* `RDAP` for `epp` — running to roughly 4,000
pairs instead of a few hundred.

**These are candidates, not findings.** Roughly half are not aliases: a
component (`LSP` under `mpls`), a different technology (`BGP-LS` under `bgp`),
or a term whose real home is a more specific tag. Yield is small and steady —
about 200 RFCs a year, roughly 115 carrying a parenthesised acronym, most
already reachable — so expect a short list to review every few months.

Nothing notifies anyone when it changes. CI commits nothing and no bot has
write access, both deliberate, so the list is published and a curator looks.
