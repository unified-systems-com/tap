# BloodHound GitHub parity — what the corpus is, where it lives, and how much of it answers today

**Status of this document.** The durable record that the 2026-09-11 parity pass said it owed and
never wrote. That omission cost the pass's working inventories, which lived only in an ephemeral
session scratchpad and are gone — the second time that happened to this thread, after the Aug-27 raw
query files went the same way. Everything below is **re-derived from the artifact that survived**,
not recalled, so it can be checked and re-derived again.

## Where the corpus actually lives

Not in its own plugin. It is a **content data file inside the `git_serious` plugin**:

    tap_plugin/git_serious/data/bloodhound_queries.json      (~146 KB)
    repo: unified-systems-com/git-serious-tap, on main
    measured at: git-serious-tap main 4fd9902, blob 0dcc20f

It landed via `feat/bloodhound-query-pack`, which is merged into that repo's `main`. The file is
**content, not fixture data** — no nodes, no example rows — which is why it belongs to the plugin
that ships the queries rather than to `grid_fixtures`.

Attribution, carried in the file's own `license` field: *"Apache-2.0 — SpecterOps; names,
descriptions and Cypher reproduced with attribution."*

Upstream pins, from the file's `upstream` field:

| upstream | pinned commit |
| --- | --- |
| `SpecterOps/openhound-github` | `056c0f8` |
| `SpecterOps/GitHound` | `bcd3da1` |

`built: 2026-09-11`.

## It is not a GRIFT pack — it is the source a GRIFT pack is generated from

Worth stating because the filename invites the wrong guess. There are three layers, and only the
middle one is GRIFT:

| layer | file | what it is |
| --- | --- | --- |
| source | `tap_plugin/git_serious/data/bloodhound_queries.json` | the content pack, hand-maintained: one record per query id, attribution, upstream pins, the Gryphon translation, `status`/`stage`, caveats. **No nodes, no edges, no batch envelope** — not GRIFT |
| generated | `tap_plugin/git_serious/grift/queries.grift.json` | **this** is the GRIFT batch (`metadata` / `_reserved` / `batches`). Seeds 35 `search`, 35 `object`, 2 `page`, 2 `panel`, 37 `edge`, 1 `batch` |
| generator | `scripts/build_query_pack_grift.py` | compiles source → GRIFT |

The generated file says so itself, on every node it writes: *"GENERATED from
data/bloodhound_queries.json — do not hand-edit"* and *"Seeded from data/bloodhound_queries.json by
scripts/build_query_pack_grift.py; edit the pack, not this node."* So the edit surface is the source
file; the GRIFT batch is build output that happens to be committed.

Two consumers, not one:

- `tap_plugin/git_serious/panels/query_pack.py` reads the **source** file directly at runtime
  (`PACK_PATH`), so the panel renders the whole corpus including the queries that do not yet run;
- the **generated** batch seeds the grid, and it seeds only the runnable ones.

**That second point is a useful cross-check rather than a detail.** The GRIFT batch seeds exactly
**35** `search` nodes, and tallying `status == "runs"` in the source independently gives **35**. The
generator's contract is "seed what runs", and the two numbers agreeing is evidence that both the
tally above and the generator are correct. If they ever diverge, one of the two is stale.

Declared in canon: `specs/spec-git-serious-query-pack.md`, `req-git-serious-query-pack`, status
**Implemented**, naming `data/bloodhound_queries.json` + `/git-serious/queries` as the deliverable.

## Method, so this can be re-derived rather than trusted

Every count below comes from reading that one file and tallying its `queries` array:

```
git -C <git-serious-tap> show origin/main:tap_plugin/git_serious/data/bloodhound_queries.json \
  > /tmp/bhq.json
python3 -c "
import json, collections
q = json.load(open('/tmp/bhq.json'))['queries']
print(collections.Counter(x['status'] for x in q))
print(collections.Counter(x['stage'] for x in q))
print(collections.Counter((x['status'], x['stage']) for x in q))
"
```

No count here is taken from memory or from the lost inventories.

## 79 ids, 87 upstream variants — reconciling the number people remember

The figure cited at the time was **87 queries**. The file holds **79 records**, and both are right:
it keeps *one record per BloodHound query id*, and each record's `sources` array carries every
upstream variant verbatim with its pinned commit. Summing `len(sources)` across all 79 records gives
exactly **87**. So 87 is the variant count and 79 is the id count; earlier notes that said "87
queries" were counting variants.

Anyone comparing this document against an older number should check which of the two it meant before
concluding something regressed.

## How much answers today

`status` is the current verdict; `stage` is when a query starts being answerable. Both are the
file's own fields, and the two agree exactly:

| status | count | meaning |
| ---: | ---: | --- |
| `runs` | **35** | translates and runs on a grid `github_core` has already collected |
| `expressible` | 20 | the Gryphon translation exists; the data does not yet |
| `blocked` | 10 | blocked on a grammar gap or an unbuilt type, not on data |
| `not_observable` | 14 | not observable for a Team-plan organization |
| **total** | **79** | |

Cross-tabulated against `stage`, which is what shows *why* 35 run:

| status \ stage | today | A | A2 | B | C | later | na |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `runs` | 15 | 20 | · | · | · | · | · |
| `expressible` | · | · | 8 | 5 | 7 | · | · |
| `blocked` | · | · | · | 3 | 2 | 5 | · |
| `not_observable` | · | · | · | · | · | · | 14 |

**Read that top row.** 15 ran on the original grid; slice A has since landed, which is what moved
its 20 into `runs` for a total of 35. The remaining slices are the lever: A2 would add 8, B 5, C 7 —
20 more by translation alone, with another 5 of B and C unblocked only after the grammar gaps close.

Stage definitions, verbatim from the file:

| stage | definition |
| --- | --- |
| `today` | runs on a grid `github_core` has collected |
| `A` | after `github-core#110` — organization, repository and environment settings in configuration |
| `A2` | after `github-core#114` — ruleset rules flattened to `configuration.rule_types` |
| `B` | after `github-core#111` — members, teams, membership and repository grants |
| `C` | after `github-core#112` — custom organization roles and fine-grained PAT grants |
| `later` | a type not yet scheduled |
| `na` | not observable for a Team-plan organization (Enterprise, SAML/SCIM, another cloud's identity graph) |

The 14 `na` records are a **plan ceiling, not a defect** — Enterprise-only, SAML/SCIM, or another
cloud's identity graph. They should not be counted against coverage.

## What blocks the 10, and who owns each

`blocked_on`, tallied across the array. This is the gap taxonomy the pass produced, and the half most
worth keeping:

| blocked on | count | owner |
| --- | ---: | --- |
| variable-length path | 4 | `tap#259` |
| variable-length path + edge alternation | 2 | `tap#259` |
| derived eligibility edge not built | 2+1 | no issue — one notes `runner_group` / `MEMBER_OF_RUNNER_GROUP` are friends-tier vocabulary |
| type not built | 2 | collector work, same build as `secret-scanning-alerts` |
| custom org roles not modelled | 2 | `github-core#112` |
| correlated multi-MATCH | 1 | `tap#433` |
| `OPTIONAL MATCH` beyond v0 | 1 | Gryphon grammar, no issue filed |
| a derived branch-creation edge (rulesets + bypass) that nothing computes yet | 1 | no issue |

Two of those have **no issue behind them** — `OPTIONAL MATCH`, and the derived edges. Worth filing
before anyone plans around the stage table, because a gap with no issue is a gap nobody is counting.

## The record schema, so the file can be read without guessing

Each entry carries: `id`, `name`, `category`, `severity`, `kind`, `bloodhound_description`,
`sources` (`repos`, `pins`, `paths`, `cypher`), `about`, `gryphon` (the translation, as a list of
clause lines), `status`, `stage`, `needs` (the TAP types the query reads, e.g.
`github_core__github_account`), `returns`, `blocked_on`, `hatch`, `caveat`.

`hatch` appears on **10** entries and `caveat` on **30** — the caveats are where a translation is
faithful in shape but narrower or broader than the upstream Cypher, and they are the first thing to
read before quoting a verdict.

Distribution by `kind`: `saved_query` 62, `privilege_zone_rule` 12, `doc_query` 5. By `severity`:
medium 27, high 15, low 12, tier-zero 12, critical 5, enterprise 5, unlisted 2, demo 1.

## What is genuinely lost

The pass also produced `bloodhound-inventory.json/.md` (recorded as 41 kinds / 159 edges / 87
queries / 28 samples), `github-core-inventory.json/.md` (26 node types, 48 edges), a
`query-verdicts.json`, and the two scripts that generated the "Twenty-Seven of Eighty-Seven"
briefing — `classify_queries.py` and `build_report.py`. All lived in a session scratchpad under
`/private/tmp`, and none survives.

Recovering them means re-running the classification against the two pinned upstream commits. The
query pack makes that cheaper than starting over, because the per-id verdicts, translations and
`blocked_on` reasons are all in it — what is missing is the upstream-side inventory of BloodHound's
own kinds and edges, and the coverage delta against `github_core`'s types.

**The lesson is the one the 09-11 note already wrote and did not act on:** a scratchpad is not a
deliverable. Derivable numbers belong in a file under `docs/misc/`, next to the artifact they were
derived from, with the command that re-derives them.

## Pointers

- The source pack: `tap_plugin/git_serious/data/bloodhound_queries.json` in `unified-systems-com/git-serious-tap` — the edit surface.
- The generated GRIFT batch: `tap_plugin/git_serious/grift/queries.grift.json` — build output, do not hand-edit.
- The generator: `scripts/build_query_pack_grift.py`.
- The runtime reader: `tap_plugin/git_serious/panels/query_pack.py`.
- Canon: `specs/spec-git-serious-query-pack.md`, `req-git-serious-query-pack` (Implemented).
- Slices: `github-core#109` (epic), `#110` (A, settings), `#111` (B, people), `#112` (C, org roles and PAT grants), `#114` (A2, flattened ruleset rules).
- Grammar gaps: `tap#259` (variable-length path and alternation), `tap#433` (correlated multi-MATCH).
- Unfiled gaps: `OPTIONAL MATCH`; the derived eligibility and branch-creation edges.
