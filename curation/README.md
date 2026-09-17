# Curation tools

Tools a curator runs by hand. Nothing here is part of the build, and the
published pipeline does not read or execute any of it.

## alias_pass.py

Proposes the `aliases` field for every tag in `taxonomy.yaml`, one model call
per tag, and checks each proposal against the corpus before keeping it.

`aliases` exists because `desc` and `match` cannot do its job. `desc` is the
display text and is searched word by word, so it carries one name and one
expansion; `match` decides which RFCs get a tag and is never searched. Neither
can hold a variant name a reader might type — `SNTP` for `ntp`, `SSL` for
`tls`, `SMIv2` for `mib`. See the Aliases section of `../README.md`.

### Running it

```sh
pip install -r ../requirements.txt -r requirements.txt
python3 alias_pass.py --dry-run --limit 3      # render prompts, no calls
python3 alias_pass.py --limit 20               # calibration run
python3 alias_pass.py                          # full pass, resumable
python3 alias_pass.py --report                 # rebuild outputs, no calls
```

It needs `rfcs.json` for the grounding check. That file is a build product and
is not in the repository — either run `python3 ../make_corpus_from_index.py`
first, or fetch the snapshot the last build published:

```sh
curl -O https://rfc-editor.github.io/rfc-subject-tags/rfcs.json
```

Two backends:

| | `--backend api` | `--backend cli` |
|---|---|---|
| Credential | `ANTHROPIC_API_KEY` | an existing Claude Code login |
| Output shape | guaranteed by schema | requested in the prompt, parsed defensively |
| Full 542-tag pass | ~$10-20 | ~$55 equivalent, drawn from subscription usage |

The `cli` backend exists so the pass can be run without provisioning an API
key. It locates Claude Code's own binary, so it works wherever Claude Code is
installed; set `CLAUDE_CLI` to override the path.

### Outputs

| File | What it is |
|---|---|
| `results.jsonl` | one raw response per tag, with the model's reason for every proposal |
| `aliases.yaml` | proposals that passed grounding, as `aliases` and `covers`, shaped to merge into `taxonomy.yaml` |
| `review.md` | everything needing a human: rejections, ambiguities, collisions, missing-tag candidates |

`results.jsonl` is also the resume file. Re-running skips tags already in it, so
an interrupted pass costs nothing to restart, and changing the prompt means
deleting only the affected rows rather than re-running the vocabulary. Keeping
it tracked is also what makes a grounding change free: the two re-grounds that
set the precision threshold cost nothing, because the responses were on disk.

### Re-running the pass

**A model pass is not deterministic.** A re-run explores a different subset
rather than reproducing the last one — the run that introduced `covers` found
581 entries against the previous 485, but 85 terms the earlier pass had
proposed were simply absent, among them `BGP-4`, `zlib`, `Radix-64`, `CAPPORT`
and `LWAPP`. Nothing judged them; that pass just went a different way.

So compare against the last output on every re-run:

```sh
git show HEAD:curation/aliases.yaml > /tmp/prev.yaml
python3 alias_pass.py --previous /tmp/prev.yaml ...
```

Terms the previous pass proposed and this one did not are listed in `review.md`
under *Proposed by a previous pass, not re-proposed*, to be read as candidates
rather than rejections. This is what makes repeated passes accumulate instead of
churn, and it is why only one `results.jsonl` is kept: the useful artefact is
the difference between passes, not a pile of old ones.

### Grounding: full text and precision

Proposals are checked against the full-text corpus — the `rfcNNNN.txt` files —
via `--fulltext DIR` (default `tmp/rfc`), falling back to `rfcs.json` metadata
when that directory is absent. Metadata alone is not enough: `krb5`, `authz`,
`RadSec`, `tcpdump`, `EBNF`, `ISO8601` and about a hundred others appear only in
RFC bodies, and a metadata-only check rejects every one of them.

But a raw full-text count is not enough either, because a short string matches
for unrelated reasons. `h2` appears in 202 RFCs — almost all of them HTML
headings, hosts H1/H2/H3 in topology diagrams, or IP octets `h1.h2.h3.h4`. So
each term is scored on precision:

| | |
|---|---|
| `raw` | documents containing the term |
| `ctx` | of those, the ones the tag's own `match` rules also fire on |
| `%` | precision, `ctx/raw` |

A proposal is kept with at least one in-context hit and precision at or above
`--min-precision` (default 20). Measured this way `disruption` under `dtn`
scores 2% and `h2` scores 5%, while genuinely short abbreviations hold up —
`TE` 71%, `PW` 72%, `ND` 78%. **Length is not the discriminator; precision is.**
A rule excluding two-character terms would have cost `TE`, `PW`, `ND`, `SR` and
six more, while keeping `LAG` and `DoS`, which are longer and less precise.

The threshold is deliberately low. Between 20% and 50% genuine and spurious
terms are mixed — `X11` at 31% is real, `LAG` at 36% is not — so that band is
kept and surfaced with its numbers rather than filtered blind.

### What the checks catch, and what they don't

Every proposal is counted against RFC titles, keywords and abstracts, and
anything scoring zero is rejected. This is a **confabulation filter, not a
popularity filter**: the threshold is one hit, because real aliases can be rare
(`GnuPG` appears in a single record).

**Precision measures topical co-occurrence, not naming.** It cannot tell "sftp
is another name for ftp" from "sftp is discussed alongside ftp". `sftp` scores
100% against `ftp` and 10% against `ssh`, because documents about SFTP genuinely
mention FTP — yet SFTP *is* the SSH File Transfer Protocol. That judgement is a
reading, not a measurement, and `sftp` is listed on `ssh` as a manual override.
Rule-1 errors generally survive the filter; **the rejection list in `review.md`
is a review queue, not a discard pile.**

Two further limits, both in the search rather than in this tool:

- The tag search never splits a query, so a multi-word alias cannot be found.
  Those are collected under `multiword` and held until that changes.
- The search tokenizer keeps `/` inside a word, so `SONET/SDH` indexes as one
  token and `SDH` is unreachable. 26 tags have such a description. The prompt
  accounts for this; a reader would not.

### Reviewing the output

`aliases.yaml` is a proposal, not a result. Read it. Each line carries the
model's reason and the number of RFCs using the term, which is usually enough
to judge in a few seconds. The failure mode to watch for is a term that names a
*different* technology rather than the same one by another name — that produces
a confidently wrong search hit, where today the reader correctly falls through
to full-text search.

## merge_aliases.py

Merges an `aliases.yaml` proposal into `taxonomy.yaml`.

```sh
python3 merge_aliases.py --dry-run     # report what would change
python3 merge_aliases.py               # write ../taxonomy.yaml
```

`regen.py` rewrites `taxonomy.yaml` by round-tripping it through `yaml.dump`,
so editing the file as text would be undone by the next curator run. This
writes through the same dumper with the same settings: the diff contains only
the added `aliases` blocks, and the next regen run reformats nothing. The field
lands between `desc` and `match`. An alias that would shadow an existing tag id
is refused.

Merging is the last step of the exercise. Once it has been done and the result
reviewed, the taxonomy carries the aliases and nothing here runs again until
someone wants another pass.

## aliases and covers

The pass produces two lists per tag, and the difference is the point.

`aliases` are other names for **the same thing**: someone typing SNTP and
someone typing NTP want the same tag because they mean the same protocol.

`covers` are **different things** the tag stands in for, because nothing more
specific exists — `cellular` covers LTE and 5G; there is no `lte` tag. Both are
searched, but only `covers` is honest to display as the tag's scope, and it is
the standing queue of candidates for the next vocabulary review (R10). When a
covered term earns its own tag, it moves out.

The distinction matters because merging them makes `aliases` mean two things at
once and quietly defers the question of whether a covered technology deserves a
tag. See R21 and R22 in `../README.md`.
