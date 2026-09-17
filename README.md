# RFC Subject Tags

A subject tag system for the RFC series, validated across every published RFC. Current figures are in [validation.md](validation.md).

This document covers what the system is for, the requirements it meets, how search and subscriptions behave, what the generated taxonomy looks like, and the open choices. Two companion documents cover the rest:

- **code.md** — the Python engine, the assignment algorithm, the two-axis derivation, and every file the pipeline produces.
- **validation.md** — the acceptance checks a rebuild must pass and the figures from the current build.

The taxonomy itself is `taxonomy.yaml`; the generated review page — published at <https://rfc-editor.github.io/rfc-subject-tags/>, and produced locally as `rfc-tags.html` — is a self-contained page for browsing it. Both are described in [What the taxonomy looks like](#what-the-taxonomy-looks-like).

## Aims

The tags exist for two things people do with RFCs:

1. **Search** — find RFCs by technology (`quic`, `dkim`) or by topic (`privacy`, `congestion-control`), including intersections such as "BGP and security".
2. **Subscribe** — be told when a new RFC is published that matches a tag or a combination of tags.

Tags complement full-text search rather than duplicating it. Where a document uses a term, the text index already finds it. The tag system earns its place by supplying what text cannot:

- subjects a document never states in words (a privacy document that never says "privacy", a QUIC specification filed under transport);
- topics implied by the technologies a document uses;
- a hierarchy to browse;
- stable targets to subscribe to.

Every proposed addition to the system is judged by that test.

## Design in brief

There are two coordinated representations of the same tags.

**The curated tree** is what people edit. It is a single hierarchy, at most four levels deep, in which every level is an assignable tag:

- The 18 roots are the top-level subjects — routing, transport, security, naming, and so on.
- A document about a subject in general carries the root alone: `/link-layer`.
- A specific document carries the deepest applicable tag together with its ancestors: `/link-layer/ppp/pppoe`.
- Every tag is declared in `taxonomy.yaml` as either a **technology** (a named protocol, system or format) or a **topic** (a subject or cross-cutting aspect). Roots are always topics.

**The served view** is derived from the tree mechanically and is what search and subscriptions run on. It separates the tags into two axes:

- **technology** — 461 tags, keeping the hierarchy;
- **topic** — 75 tags, flat: the root subjects plus cross-cutting aspects such as `privacy`, `multicast` and `ip-mobility`.

A document's topics are the roots of its paths plus any aspect tags it carries, plus the topics its technologies *imply*: TLS implies security, PIM implies multicast, QUIC implies transport. This is what lets "quic AND security" find RFC 9001 without anyone having coined a tag for the intersection.

Curators edit one file, `taxonomy.yaml`, in which each tag's entry carries everything known about it; the served view is derived from it.

## Requirements

Each requirement has an identifier, R1–R20. The validation procedure in validation.md cites these identifiers to say which requirement each check serves.

### Purpose

- **R1** Tags support searching RFCs by technology or by topic.
- **R2** Tags support per-tag subscription to notifications of newly published RFCs.

### Structure

- **R3** The hierarchy is at most four levels deep and every level is an assignable tag. The roots are the top-level subjects; there is no browse-only layer.
- **R4** An RFC is assigned its tags together with all their ancestors — full hierarchical paths.
- **R5** A tag name may appear in more than one place, or on both axes of the served view, only when it means the same technology or topic in each.

### Coverage and budget

- **R6** RFCs carry between one and ten tags on average, counting ancestors.
- **R7** No RFC is untagged.
- **R8** In the served view every RFC carries at least one topic. An RFC with no topic indicates a gap in the topic vocabulary, not a legitimate outcome.

### Vocabulary

- **R9** Every tag is a specific term users would search for.
- **R10** A named technology with its own following gets its own tag rather than being absorbed into a sibling or a working-group mapping. A nearly empty level beneath a tag is the signal that a technology has been wrongly absorbed.
- **R11** A working group's name is not by itself grounds for a tag. The name must be used in RFC text as the name of the technology or topic ("the LISP mapping system", "a DetNet flow"), not merely as a reference to the group. Where RFCs name the technology differently from the group — BGP-SPF rather than LSVR, firmware update rather than SUIT — the tag takes the name the RFCs use.
- **R12** There are no catch-all tags: no "miscellaneous", "other" or "general". A document about a subject in general takes the bare parent tag, up to and including the root itself.
- **R13** A tag used on a single document is acceptable when that document's technology or topic can be described no other way.

### Independence

- **R14** Tags do not follow IETF areas, which change.
- **R15** Tags do not replicate or resemble fixed RFC metadata — status, stream, standards level or publication date. Being old is a status, not a subject: a document takes `internet-history` only if history is what it is about. Genre words (requirements, framework, applicability, use cases) describe document form and are excluded for the same reason.

### Humor

- **R16** Humorous RFCs — the April 1st series and the whimsical documents published on other dates — carry the single tag `humor` and nothing else, and no other document carries it.

### Stability

- **R17** Published tags change rarely; the expected operations are split and rename.
- **R18** New tags are created only for novel technologies or topics, and an RFC should rarely introduce more than one new tag. This is tested by replaying the corpus in publication order, not asserted.

### Topic axis

- **R19** A topic records what a document is *about*, not what properties its subject *has*.
- **R20** A technology implies a topic only when that topic is the technology's purpose, never merely a feature. TLS implies security, ROHC implies compression, PIM implies multicast, QUIC implies transport. QUIC does not imply security although it mandates encryption; HTTP does not imply compression although it supports it.

### Finding a tag

- **R21** A tag may carry `aliases` — other names for the same thing, searched but never displayed. An alias denotes what the tag denotes: a superseded name (SSL for `tls`), a version or variant form (SNTP for `ntp`, IKEv2 for `ike`), a common abbreviation (i18n for `internationalization`), or an informal name (Bonjour for `service-discovery`). A term naming a *different* technology is not an alias however close, because a wrong alias returns a confidently wrong result where full-text search would have served the reader correctly. Every alias must be used as that name in RFC text.
- **R22** A tag may carry `covers` — names of things the tag stands in for because no more specific tag exists. `cellular` covers LTE and 5G. Unlike an alias, a `covers` entry names something else, so it is honest to display as the tag's scope, and it is the standing list of candidates for R10 review. When a covered term earns its own tag, it moves out of `covers`.

## Search and subscription semantics

### What a tag matches

A document matches a tag when the tag is in its **closed set**:

- the tags assigned to it,
- their ancestors,
- the topics implied by its technologies.

Consequences:

- Subscribing to `dns` covers DNSSEC, DoH and every other descendant.
- Subscribing to `security` covers every document whose technologies imply security.
- Combinations work across axes: `quic AND security` delivers RFC 9001 and the QUIC documents that carry a security technology, but not the QUIC base specification (R19, R20). `bgp AND yang` delivers the BGP YANG modules.

A subscription is any boolean expression over tags: a single tag, an OR, or an AND.

### When a subscription fires

- Once, when an RFC is published with a matching closed set.
- Never again for that RFC. Later corrections to its tags change what search and browsing return but do not re-notify.

This puts the weight of correctness on the assignment made at publication. It is why keyword-derived noise is treated as a defect rather than a tolerable imprecision: in search a false positive is a result the reader skips; in a subscription it is an unwanted notification to every subscriber of that tag, and a false negative is an RFC subscribers never learn about.

### Assignment at publication

1. The engine proposes tags from the working group, title and keywords (see code.md).
2. A person confirms them before publication, adding anything the rules missed.
3. If the document introduces a technology or topic the vocabulary lacks, the same person decides whether a new tag is warranted under R10, R11 and R18.
4. New working groups are added to the working-group map when their first RFC is published.

### Changing tags without breaking subscribers

| Operation | Rule |
|---|---|
| Rename | The old slug remains as a redirect; subscriptions follow the tag. |
| Split | The original tag stays as the parent of the new children. Its subscribers continue to receive everything they did and may narrow if they wish. |
| Remove | Only when no document carries the tag, and announced to its subscribers. |
| Move between axes, or under a different root | Changes which combinations the tag satisfies. Treated as a breaking change once subscriptions exist; settle these before launch. |

### Volume

Broad topics are legitimate subscription targets even though they are busy, because subscribers can narrow with AND. Over 2021–2025:

- `security` averaged about 64 RFCs a year,
- `routing` about 56,
- `network-management` about 33.

Dormant tags are equally legitimate: 205 of the 542 tags have had no RFC since 2021. A subscription to one is a standing request to be told if the technology revives.

## What the taxonomy looks like

The taxonomy is `taxonomy.yaml` — one entry per tag with its place in the tree, kind, description, matching rules, working groups and served-view relations — browsable at <https://rfc-editor.github.io/rfc-subject-tags/> (generated as `rfc-tags.html`), a review page with the tree (corpus count and notifications per year per tag), co-occurrence, each tag's lifespan, overlap analysis for merge-or-nest decisions, and RFC look-up showing served technology and topic coordinates. This section describes the taxonomy's shape; the files hold the content.

### Size and shape

- 542 tags: 18 roots, 266 at level 2, 233 at level 3, 25 at level 4.
- 461 technologies and 81 topics in the tree (75 topics reach the served view; six composite topics decompose into their parts).
- Mean 3.63 tags per RFC including ancestors; no RFC untagged; no tag unused.

### The roots

| Root | Holds |
|---|---|
| `naming` | DNS and its extensions, registration protocols, identifiers, service discovery |
| `web` | HTTP and its versions, URIs, web security, WebSocket, WebDAV |
| `messaging` | email and its authentication, instant messaging, Netnews, MIME |
| `real-time-communications` | SIP and its extensions, RTP, codecs, conferencing, emergency services, PSTN interworking |
| `routing` | BGP, OSPF, IS-IS, MPLS, multicast, VPNs, segment routing, traffic engineering |
| `transport` | TCP, UDP, QUIC, SCTP, congestion control, QoS, header compression |
| `internet-layer` | IPv4, IPv6, addressing, transition mechanisms, mobility, NAT, tunnelling |
| `link-layer` | PPP, Ethernet, cellular, DSL, ATM and other media |
| `security` | TLS, IPsec, PKI, cryptography, authentication, authorization, privacy |
| `network-management` | SNMP/MIB, NETCONF/YANG, measurement, OAM, telemetry, time synchronization |
| `applications` | FTP, Telnet, LDAP, storage, calendaring, e-commerce |
| `data-formats` | JSON, CBOR, XML, ASN.1, character sets, compression formats |
| `iot` | CoAP, 6LoWPAN, RPL and other constrained-network technologies |
| `internet-governance` | IETF process, IANA, IPR, the RFC series, terminology, user guides |
| `internet-architecture` | architectural principles (stands alone) |
| `internet-history` | documents about the history of the Internet (stands alone) |
| `arpanet` | the ARPANET's own protocols and working notes |
| `humor` | the April 1st series and other whimsical RFCs (stands alone) |

### Placement rules

- A protocol family with several named members becomes a parent: `email` → `smtp`, `imap`, `pop3`, …
- A single-tag technology sits directly under its root.
- Cross-cutting aspect topics live under the root where they most often occur: `privacy` under `security`, `multicast` under `routing`, `transport-mapping` under `transport`.
- The fourth level is used once: `congestion-control` → `aqm` → `codel`, `pie`.

### Descriptions

Each tag has one description, which is also its display text. The convention:

- It contains the tag's correct-case name — DNS, IPv6, S/MIME, iCalendar, robots.txt — never a form inferred from the slug.
- Where the name is an acronym or abbreviation, the expansion follows in parentheses.
- The rest states the scope, and never repeats the name or the expansion.

Examples: `DKIM (DomainKeys Identified Mail)`; `Stateful NAT64 (Network Address Translation IPv6-to-IPv4) translation`; `Application protocols in general`.

### Topic vocabulary

The served topics are the tree's topic tags minus the six composites that decompose into their parts: the entries in `taxonomy.yaml` with `kind: topic`, a root being one with no `parent`. Reviewing each topic against the phrasing people actually search is part of the R9 check in validation.md, not a separate output.

## Known limits and open choices

### Axis boundaries are decisions

Roots aside, whether a tag is a technology or a topic is a judgement, and a few sit on the line:

- typed as **technologies**: `nat`, `fec`, `checksum`, `pmtud`;
- typed as **topics**: `multicast`, `addressing`, `nat-traversal`;
- `mib` and `yang` are technologies that imply the `network-management` topic.

Flipping a tag between axes after subscriptions exist is a breaking change, so these should be settled before launch.

### Deliberate exceptions near R15

Three topics name document forms but are kept because each is a subject readers search for by exactly that word, and none encodes a status or date:

- `terminology` — glossaries and requirements language;
- `user-guides` — the FYI series and other introductory material;
- `workshop-reports` — IAB and IRTF workshops.

`deployment` and `performance` are *not* topics: both are searched, but both describe document form more than subject. Either can be added as a topic entry in `taxonomy.yaml` if that judgement changes.

### Tag counts

Because roots count as tags, 0.4% of documents exceed ten tags. All are multi-technology cross-area specifications. A hard cap can be added if the average-based budget (R6) is judged insufficient.

### Placements most open to revision

- `terminology` and `user-guides` under `internet-governance`;
- `internationalization` under `data-formats`.

### Aliases

Tags have no alias list. On the full-text-search test above, aliases are worth having only for synonyms and variant names a reader might type into a tag lookup — SNTP for `ntp`, IKEv2 for `ike`, ESMTP for `smtp`, SMIv2 for `mib`. Sub-features and related terms belong to full-text search. An `aliases` field on the tag entry in `taxonomy.yaml`, held to that criterion, is the intended home for them.

### Residual noise

Keyword-derived assignments remain the main source of false positives. The title-only rule tier and the suppression table contain it; the scans in validation.md are how new cases are found.
