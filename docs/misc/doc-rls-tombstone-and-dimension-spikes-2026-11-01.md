# Tombstone leaks, row-level security, and the dimensions copy: evidence record (2026-11-01)

Status: evidence record, not a spec. Nothing here authorizes a build. The design decisions it feeds are
tracked in Issue# 1147 - tap; the leak that started it is Issue# 1144 - tap (fixed by PR# 1145 - tap).

Every claim below names its method: **read** (opened the file), **ran** (executed and saw the output), or
**inferred**. Raw scripts and logs sit beside this file in `rls-spikes-2026-11-01/`.

## 1. What started it

`tap_grid/orm_compiler.py` started ORM-DSL searches from an unfiltered `Entity.objects`, so a search returned
tombstoned entities (Issue# 1144 - tap). Managers filter only a query's root, not joins or reverse accessors,
so the same class of leak is possible anywhere a query reaches a tombstoned row by a path other than a
`LiveManager` root.

- Fix (ran, red then green): three `Entity.objects` chains now call `.live()` (`orm_compiler.py` lines 86, 118,
  183); `TestTombstonesNeverReturned` in `tap_grid/tests/test_search_orm.py` (spec `req-grid-search-orm-10`) fails
  without the fix and passes with it; an AST test fails if any compiler chain starts from an unfiltered manager.
- Plugin sweep (ran: shallow clones of the default-branch HEAD of 29 public `unified-systems-com` plugin repos plus
  `rampart-20x-playground-tap` and `stackarmor-vdr-tap`, searched for `Entity.objects` / search runners). Result as
  recorded in the session: the only leak in the wild was the administrivia "All Grid Entities" ORM search, which the
  compiler fix closes. Plugin module runners were clean because they go through `read_scope` by convention, not
  because anything enforces it. The clones (66 MB) are not committed and were taken at branch HEAD, not at pinned
  release tags.

## 2. Why row-level security (RLS)

Gryphon is protected by `tap_grid/gryphon/read_scope.py` and an AST guard covering `tap_grid/gryphon/` only. The
module and ORM search kinds are not covered by an enforced scope. Every search already runs through the
`SEARCH_READONLY` alias and a SELECT-only role (`tap_grid/search_role.py`, `search.py:32,80`), so a database policy
bound to that role covers all three search kinds without touching their code. RLS is also the mechanism planned for
dimensional filtering.

## 3. Spike 2: tombstone policy shapes (PostgreSQL 18.6)

Directory: `rls-spikes-2026-11-01/spike2-tombstone-pg18/`. Ran 2026-11-01 11:19-11:29 PST.

**Environment (ran):** `tap-db:latest`, PostgreSQL 18.6 on aarch64 (Wolfi). Container capped at 3 GB / 2 CPU. Host
load average 5.8-12 on 8 cores while the queries ran (`run.log`). uuids are v4 (production is v7). `md5()` is
unavailable under FIPS, so data is generated without it.

**Data (ran):** 3,000,000 `tap_entity` rows (1M findings, 2M edge entities); 149,720 tombstoned (about 5%); 1M
`spike_finding`; 2M `tap_edge`; 0 live edges touching a dead endpoint. Sizes: `tap_entity` 566 MB, findings 187 MB,
edges 555 MB.

**Variants (policy for the `spike_search` role):**

| Variant | Policy on the typed tables |
| --- | --- |
| V0 | none (baseline) |
| V1 | lookup: `EXISTS (SELECT 1 FROM tap_entity e WHERE e.id = <table>.entity_id AND e.deleted_at IS NULL)` |
| V2 | column: a copied `deleted_at` on the typed table, policy `deleted_at IS NULL`, plus partial indexes `WHERE deleted_at IS NULL` |
| V3c | `entity_id NOT IN (SELECT id FROM spike_dead)`, where `spike_dead` is an owner-run view over tombstoned ids |

**Queries:** a = count of open findings; b = findings joined to `tap_entity`; c = point lookup by `entity_id`;
d = edge `from_entity_id` by type; e = edge to entity join; f = group-by aggregate.

**Results (ran; median of repeated runs, ratio to V0). Every row was flagged UNRELIABLE by the harness because
min-max spread exceeded 1.5x under host load, so read the ratios as orders of magnitude, not as precise factors:**

| Query | V0 (ms) | V1 lookup | V2 column | V3c NOT IN |
| --- | --- | --- | --- | --- |
| a | 52 | 31.7x | 0.96x | 7.1x |
| b | 717 | 5.8x | 1.7x | 2.2x |
| c | 14 | 38.7x | 1.95x | 140.7x |
| d | 155 | 11.8x | 1.3x | 2.3x |
| e | 826 | 3.4x | 1.0x | 1.2x |
| f | 211 | 18.6x | 1.15x | 3.0x |

- The lookup policy (V1) is 3.4-38.7x slower than no policy. **Plan (ran, `run.log` "PG plan for V1 shape a"):**
  Postgres keeps the policy as a correlated SubPlan (`Filter: ... EXISTS(SubPlan 1)`) and loses the parallel scan; it
  does not become a semi-join.
- The column policy (V2) ran 0.96-1.95x of baseline. With this spread that is not distinguishable from noise for most
  shapes; it is the only variant that stayed near baseline on every query.
- The partial index mattered a little for one shape and not for the other (`run.log` "V2 without partial indexes":
  open-findings count 31 ms with the partial index against 108 ms without; edge-by-type 249 ms against 96 ms, i.e. the
  partial index was slower there).
- V3c (`NOT IN` over a view): the dead set is hashed once per query; point lookups were 140x slower. Not recommended.
- **Write cost of the copy (ran, one sample each, loaded host; `write_cost.sql`):** tombstoning 10,000 findings took
  1,729 ms updating `tap_entity` only, and 2,681 ms updating `tap_entity` plus the copied `deleted_at` on the typed row
  (`run.log` "write cost (owner)"). Single samples under load; the extra cost is real in direction but not a measured
  figure.

## 4. Spike 3: dimension scope policies (PostgreSQL 18.6)

Directory: `rls-spikes-2026-11-01/spike3-dimensions-pg18/`. Ran 2026-11-01 11:38-11:43 PST, host load 3-9 on 8 cores.

**Data (ran):** 1,000,000 findings, each with a copy of the entity's flat `{str: str}` dimension map in three
columns: `dims_none` (no index), `dims_gin` (GIN `jsonb_ops`), `dims_gpo` (GIN `jsonb_path_ops`). Index sizes:
entity GIN 14 MB, copy `jsonb_ops` 14 MB, copy `jsonb_path_ops` 10 MB.

**Scopes (`scopes.txt`):** S1 one team (4,990 rows); S2 two keys (5,106); S3 one broad value (249,781); S4 a union of
three scopes (7,605); S5 admin, `[{}]` (all 1,000,000).

**Variants (`mkpol.sh`):** L_arr = lookup on `tap_entity.dimensions` with an array predicate; C_* = policy on the copy:
`gin`/`gpo`/`none` index, `arr` (EXISTS over `jsonb_array_elements` of the scope setting) or `slots` (four OR'd
`dims @> current_setting('tap.scope')::jsonb -> n` terms).

**Correctness (ran):** for all five scopes every variant returned exactly the ground-truth row count
(`run.log` "correctness").

**Results (ran, ratio to V0; `*` spread over 1.5x):** for selective scopes S1, S2, S4 the copy with the slot form and
a GIN index (`C_gin_slots`, `C_gpo_slots`) ran 0.0-0.6x of baseline on scans, aggregates and joins (a, b, f), and
11-44x faster than the lookup form `L_arr`. Point lookups (c) were the exception: slower than baseline
(about 13-36 ms against 3 ms; 3-13x). For the broad scope S3 the slot form ran 0.8-1.7x on a/b/f. For the admin scope S5
no variant beat baseline: the slot form ran 3-4.4x on a/b, 38x on the point lookup; the array form with
a GIN index ran 2-5x on a/b and 1.3x on the point lookup.

**Plan facts (ran, `plans_*.txt`):** the array form cannot use the GIN index (it falls back to a hashed SubPlan over the
whole table); the slot form is index-usable because `current_setting(...)::jsonb -> n` is a stable expression, giving
a BitmapOr of GIN scans. `jsonb_path_ops` is smaller but cannot serve key-existence operators (`?`, `?|`, `?&`), so
key-presence filtering needs `jsonb_ops`.

**Write cost (ran, `write_cost.sql`, 10,000-row update, loaded host):** entity only 848 ms; with an unindexed copy 832 ms;
with `jsonb_ops` copy 519 ms; with `jsonb_path_ops` copy 658 ms. The ordering is inverted against what index
maintenance should cost, so this is noise. The write cost of the copy remains unmeasured.

## 5. Spike 1 (PostgreSQL 16.14, partial)

Directory: `rls-spikes-2026-11-01/spike1-pg16-partial/`. A subagent ran this on `tap-db:0.2.2`, which is PostgreSQL
16.14, not the 18.6 the running stacks use. Its timings are incomplete and are **not** used for any number above. Its
correctness findings (ran by the subagent on 16.14, in its `REPORT.md`; not re-run on 18.6 except the V1 plan shape,
which spike 2 reproduced) are the source of the following semantics:

- Policies apply per role. Table owner, BYPASSRLS roles and superusers bypass them.
- With `FORCE ROW LEVEL SECURITY` and a policy only `TO` the search role, the owner sees zero rows (default deny).
- A subselect inside a policy on an RLS table is itself filtered by that table's policy. A `NOT IN` against a
  filtered table therefore silently shrinks the dead set (the trap that V3c avoids with an owner-run view).
- A typed-only query (no join to `tap_entity`) is filtered by a policy on the typed table; joins from entity or edge
  cannot reach a tombstone once both tables carry a policy.

## 6. What this does not show

- No measurement of the write cost of keeping a copy in sync (section 3 and 4 numbers are noise).
- No `SET LOCAL` per-transaction scope prototype, so no evidence yet about pooled-connection leakage.
- No test of `Meta.base_manager_name = "objects"` on the reverse one-to-one accessor.
- Data is synthetic: flat `{str: str}` dimension maps, uuid v4, no real Gryphon queries, not measured at the
  production row counts, and not on the shape that Issue# 708 - tap proposes (see section 7).

## 7. Decisions on the dimensions epic that gate this (Issue# 716 - tap, Issue# 708 - tap)

Issue# 708 - tap changes `Entity.dimensions` from `{"tap.graph": "x"}` to
`{"<dimension-uuid>": {"v": "x", "src": "declared|default|derived"}}`. Spike 3 measured the flat shape. Key lookups,
containment queries, the policy predicate and the index choice all change with the new shape. Read from the two issues
and their comments on 2026-11-01 (spec lines are Issue# 716's own citations, not re-read):

| # | Decision | Source | Why it is open |
| --- | --- | --- | --- |
| 1 | Storage-shape cutover: migrate wholesale and scope only the behaviour trial to dcom; or a dual-read window with one normalizing reader; or bootstrap `tap.meta` as a genesis node | 708 correction comment; `req-grid-dimension-reference` is the one requirement left `Proposed` | `Entity.dimensions` is one shared column, so a dcom-only shape change makes every reader branch; `Dimension` stamps `tap.meta` on itself, a circular reference |
| 2 | Name uniqueness: a uniqueness constraint on live names, or a name-resolution rule that fails closed on ambiguity | 708 correction comment 1; blocking AC on `req-grid-dimension-tabled` | `Dimension.name` has no uniqueness constraint; assigned ids make same-name nodes possible |
| 3 | Vocabulary fields: `boundaries`, `value_set` (open/closed), `values`, `owner`, `status`, `superseded_by` | 716 against `spec-grid-dimension.md:265,273,293-295` | #709 names the fields; the spec lists only id, name, description |
| 4 | Deprecation carrier for the three-state deprecation | 716; spec lines 540, 545-548 | approved but the carrier is undecided |
| 5 | Validation boundary: missing, wrong-type, deprecated or tombstoned dimension references, same-batch declarations, where an out-of-set value is rejected | 716, 713; spec line 480 | the reference ACs assign no write boundary |
| 6 | Absence and write semantics: omitted dimensions, `{}`, omitted keys, empty strings on create/patch/replace/re-import; whether import keeps `src`; how `derived` reaches the trusted write path | 714, 711/712; defect 608 | write and provenance behaviour is already specified, so absence must be settled first |
| 7 | Reader and schema inventory before sizing the cutover | 716 scope evidence (`models.py:978,1113`, `tap_web/dimensions.py:18`, `importer.py:589`, `grift-document.schema.json:54`, `executor.py:1137`) | four Dimension rows is not the count of map users |
| 8 | Trial design: the four falsifiable questions and the git-serious example, expected results written first | 708, 716 done-test | #713 needs rescoping after decision 1 |

Recommendation (inferred from the spike structure, no dual-read case tested): decide 1 first, and migrate the shape
wholesale in the same wave as the table upgrade. A dual-read window would put two jsonb shapes under the RLS copy and
double the policy surface.

## 8. Batched with

Issue# 323 - tap (batch provenance to the Entity spine; `flip_map` stays on the typed row) and Issue# 886 - tap (time and
observation epic, with Issue# 322 - tap and Issue# 896 - tap) rewrite the same write path
(`tap_grid/models.py` ~795-806). Issue# 140 - tap and Issue# 570 - tap cover tombstoning. The tables upgrade has no
tracking issue as of 2026-11-01.
