---
spec: ../../tap_grid/specs/spec-grid-traversal-language.md
audience: [llm, developer]
covers:
  - doc-dev-gryphon-wishlist.md
  - doc-dev-gryphon-vs-cypher.md
  - ../../tap_grid/specs/spec-grid-traversal-language.md
assumes:
  - Reader knows Gryphon (Cypher-subset → ORM→SQL, read-only) and the demand-shape wishlist buckets
  - This is an EVIDENCE note — it measures external Cypher demand and contrasts it with Gryphon's shipped surface; it does not change any requirement
provides: |
  A numbers-first breakdown of which Cypher features real open-source graph
  applications actually hard-code in their queries, mined across 13 corpora
  (565 app-focused read queries; 1295 with the two library corpora included),
  cross-referenced against what Gryphon supports today, each rated for
  implementation complexity (§2, Low→Very High, anchored to the lowering ladder).
  The point is to let wishlist sequencing be set by measured demand rather than by Cypher's table
  of contents or by intuition. Includes the apoc/GDS skew caveat, the
  non-obvious findings (COLLECT ≫ numeric aggregates; UNWIND's signal has
  arrived; CALL is library-inflated), and one live doc-drift flag. §7 adds an
  APOC heavy-hitter map (48 namespaces → TAP destinations) reading APOC as
  "what professional graph-DB users needed that Cypher didn't ship" — most of
  it is non-language TAP platform surface that TAP has *already shipped or
  deliberately sited* (grift envelope for get-data-out, entity/type endpoints
  for schema, service-layer+FLIP for mutation), so it reads as validation the
  architecture is aimed right. A recurring theme (§3.6, §5.1, §7.4): a
  meaningful slice of "Cypher features Gryphon lacks" are features it doesn't
  need because the typed/declared data model answers them structurally —
  including reachability, planned via named paths not variable-length
  traversal. The genuinely-owed language features shrink to WITH and COLLECT.
---

# Gryphon Feature Demand — What Real Cypher Corpora Actually Use

> "I want to see some numbers first." — George
>
> This is the numbers. It measures the **demand side** (what features real Cypher-writing
> applications reach for) and lays it against the **supply side** (what Gryphon lowers today),
> so the wishlist's `extract-ahead` / `wait-for-signal` calls rest on evidence, not vibes.

## 0. TL;DR — the ranked gap

Sorted by demand among **application** corpora (excludes the two library corpora — see §4 for why),
showing only features Gryphon does **not** fully ship today:

| Rank | Feature | App-corpus demand | Breadth | Gryphon status | Wishlist |
| :--: | --- | :--: | :--: | :--: | :--: |
| 1 | **`WITH`** (pipeline / post-aggregate filter) | **19.5%** | 10/11 repos | ❌ not in grammar | **F1 ★** |
| 2 | **`COLLECT`** | **14.9%** | 10/11 repos | ❌ not in grammar | **C2** |
| 3 | **var-length path** `-[*n..m]-` | **14.5%** | 7/11 repos | ⚠ parses, executor **rejects** | **E1** |
| 4 | **`DISTINCT`** | **12.2%** | 7/11 repos | ❌ not in grammar | **A4** |
| 5 | arithmetic in expressions (`a.x + b.y`) | 10.4% | 10/11 repos | ❌ not built | — (no bucket) |
| 6 | `coalesce()` | 8.7% | 5/11 repos | ❌ not in grammar | H1 |
| ~~7~~ | `labels()` / `type()` / `keys()` | 6.7% | 7/11 repos | ✅ **not a gap** — values exported by the typed envelope (§3.6) | — |
| 8 | string fns (`toLower`, `substring`, …) | 6.0% | 5/11 repos | ❌ not built | H2 |
| 9 | **`shortestPath`** | 5.8% | 5/11 repos | ❌ not in grammar | E3 |
| 10 | list ops / comprehensions | 5.0% | 9/11 repos | ❌ not built | — (deliberate subset) |
| 11 | `size()` | 5.0% | 8/11 repos | ❌ not built | H2 |
| 12 | **`UNWIND`** | 4.8% | 7/11 repos | ❌ not in grammar | F3 |
| 13 | `SKIP` / `OFFSET` | 3.4% | 2/11 repos | ❌ not in grammar | A3 |
| 14 | numeric aggregates (`SUM`/`MIN`/`MAX`/`AVG`) | 2.5% | 4/11 repos | ❌ not in grammar | C1 |
| 15 | positive `EXISTS { }` | 0.5% | 1/11 repos | ❌ not in grammar | D2 |
| 16 | explicit `UNION` | 0.2% | 1/11 repos | ❌ not in grammar | F2 |

**The headline: Gryphon's #1 measured gap is exactly the wishlist's #1 pick (`WITH`, F1 ★).** The
data confirms the existing intuition rather than overturning it — but it **re-sequences the middle
of the list** (see §3): `COLLECT` should precede numeric aggregates, and `UNWIND`'s demand signal
has now arrived.

**What Gryphon already ships covers the demand core.** Every one of the top-6 *most-used* features
across the app corpus — `pred_comparison` (42.8%), `AND/OR/NOT` (30.4%), pattern var-binding
(28.5%), `LIMIT` (23.2%), `$params` (20.9%), inline node props (20.5%) — is **shipped**. So are
`ORDER BY`, multi-`MATCH`, `IN`, `STARTS_WITH`/`CONTAINS`, undirected edges, `COUNT`, `IS NULL`,
`=~`, and (narrow-v0) `OPTIONAL MATCH`. The gap is a **tail of composition/aggregation/function**
features, not a hole in the core.

## 1. Method (so the numbers are auditable)

- **Corpora (14 attempted, 13 with ≥1 read query):** `lyft/cartography`, `SpecterOps/BloodHound`
  (CE), `CompassSecurity/BloodHoundQueries`, `hausec/Bloodhound-Custom-Queries`,
  `ReversecLabs/awspx`, `hetio/hetionet`, `greenelab/connectivity-search-backend`, `MannLabs/CKG`,
  `deepfence/ThreatMapper`, `spring-projects/spring-data-neo4j`, `neo4j-graph-examples/recommendations`,
  plus two **library** corpora held separate in the app view: `neo4j/apoc` and
  `neo4j/graph-data-science`. (`JupiterOne/starbase` was mined but yielded 0 — it uses J1QL, not
  Cypher, and delegates graph I/O to an SDK.)
- **Unit of count = "queries using the feature at least once"** (not raw occurrences), so a query
  that uses `WITH` three times counts once for `WITH`. Percentages are `queries-using ÷
  read-queries-analyzed` within the corpus set.
- **Read-only filter:** write clauses were tallied but excluded from the ranked gap — Gryphon
  rejects writes *by design* (read-only-by-construction; GRY-ARCH-7 / GRY-SEC-1). Writes appeared
  in only 1–2 corpora regardless.
- **Two aggregations** are reported because the two library corpora dominate raw volume and skew
  per-query rates:
  - **App-focused (11 repos, 565 read queries)** — the demand a customer-facing TAP instance
    actually sees. **This is the view the sequencing rests on.**
  - **All-13 (1295 read queries)** — includes apoc + GDS; useful only to show *how badly* they skew
    (see §4).
- **Corroborating external studies** (not counted, used as a sanity check on ranking): the SLE 2019
  empirical study of Cypher in the wild, Neo4j's Text2Cypher 44,387-instance dataset, and Francis
  et al. (SIGMOD 2018) for the semantic-feature taxonomy. All three rank `WITH`, aggregation, and
  variable-length paths in the same high band this corpus does.
- **Honesty about the instrument:** feature classification was done by LLM readers over each repo's
  query text, then aggregated deterministically from the workflow journal (not re-estimated). Treat
  the counts as **±1 rank noise**, not survey-grade precision — the *bands* (headline vs. tail) are
  the load-bearing signal, and they agree with the three external studies. The apoc/GDS split (§4)
  is exact, not estimated.

## 2. The full two-view table

Percentages are share-of-read-queries within each view. `∆` flags where the library corpora move a
feature's apparent rank. **Difficulty** = estimated implementation complexity *for Gryphon
specifically* (legend below) — the "should I brace for this?" signal when a feature surfaces.
**Impl. details** = the concrete lowering approach that drives the rating.

**Complexity legend — anchored to the lowering ladder** (`spec-grid-traversal-execution.md`), not vibes:

- 🟢 **Low** — a direct rung-1 ORM map: one Django annotation / lookup / function / slice, no new
  dispatch path. A day-shaped change. (e.g. `SUM`/`MIN`/`MAX`/`AVG`, `DISTINCT`, `SKIP`, `coalesce`,
  `size`, string/temporal fns, positive `EXISTS`.)
- 🟡 **Medium** — a new dispatch path *or* a new expression/projection class, still rung-1 single-pass
  (no staged materialization). (e.g. `COLLECT`, `UNWIND`, expression arithmetic, `CASE`, map
  projection, explicit `UNION`.)
- 🟠 **High** — staged materialization, cross-stage threading, or a sub-expression-language: a new
  execution *structure*, but still in-plan. (e.g. full `WITH` value-carry, list comprehensions,
  `reduce`, `CALL {}` subqueries.)
- 🔴 **Very High** — a new execution engine, recursion, a different backend, or a new trust boundary:
  recursive CTE, cost-tracking, an IR, or writes. (e.g. variable-length paths, `shortestPath`,
  general `CALL` procedures, write clauses.)

Ratings are for the *full* Cypher feature; several **phase down** — e.g. `WITH`'s node-scoping rung is
Medium even though full `WITH` is High (§5.1 / wishlist F1 note). A blank Difficulty (`—`) = shipped
(no build); `n/a` = not a build (exported by the model, withdrawn, or deliberately out of scope).

**JSON blob axis** — the rightmost column records whether a call reaches *into* JSON blob (`data.*`)
columns, and to what depth. TAP's goal is to operate on JSON-stored values with the same operators
that act on native columns, *to whatever extent is possible* — this column tracks that reach and its
limits per call:

- `scalar` — operates on JSON **scalar** sub-keys (`n.data.x.y` → a string/number/bool/null) via the
  shared field-path resolver (`_typescan_orm_path` / `_resolve_orm_path`), treated identically to a
  spine/column field. Does **not** handle JSON object/array *containers*.
- `container→` — a list/map-shaped call whose JSON-**container** handling is a *named future*
  extension (unbuilt today).
- `—` — not a value operation (structural, clause-level, out-of-scope, or envelope-exported).

No call supports JSON **container** (object/array) sub-values yet — no map/array literals exist to
express container semantics, row values are primitives-only (`req-grid-gryphon-rows-5`), and
jsonb-container equality is unspecified. This column is the ledger for where container support lands
as it is built; the first named candidate is `DISTINCT`'s container case
(`req-grid-gryphon-distinct-6`).

| Feature | App % (n=565) | App breadth | All-13 % (n=1295) | Gryphon status | Difficulty | Impl. details | JSON blob |
| --- | :--: | :--: | :--: | --- | :--- | --- | :--: |
| `pred_comparison` (`=`,`<`,`>`,…) | 42.8 | 11/11 | 21.3 | ✅ shipped | — | — | scalar |
| `AND` / `OR` / `NOT` | 30.4 | 11/11 | 14.2 | ✅ shipped (combinators) | — | — | — |
| pattern var-binding `(a)-[e]->(b)` | 28.5 | 9/11 | 18.7 | ✅ shipped † | — | — | — |
| `LIMIT` | 23.2 | 7/11 | 12.1 | ✅ shipped (A2) | — | — | — |
| `$params` | 20.9 | 7/11 | 16.3 | ✅ shipped | — | — | — |
| inline node props `{k: v}` | 20.5 | 9/11 | 20.4 | ✅ shipped | — | — | scalar |
| **`WITH`** | **19.5** | 10/11 | 13.7 | ❌ not in grammar (F1 ★) | 🟠&nbsp;**High** | node-scope rung is Medium; value-carry-through is the High part | — |
| `ORDER BY` | 19.1 | 11/11 | 13.6 | ✅ shipped (A1) | — | — | scalar |
| multiple `MATCH` | 15.8 | 9/11 | 7.5 | ✅ shipped (implicit union) | — | — | — |
| `IN` list | 15.6 | 9/11 | 6.9 | ✅ shipped (B1) | — | — | scalar |
| **`COLLECT`** | **14.9** | 10/11 | 11.0 | ❌ not in grammar (C2) | 🟡&nbsp;**Medium** | `ArrayAgg` annotation + list-ordering / empty-collect corners | container→ |
| **var-length path** `-[*n..m]-` | **14.5** | 7/11 | 7.5 | ⚠ parses, executor **rejects** (E1) | 🔴&nbsp;**Very&nbsp;High** | recursive CTE (rung 4); or supplanted by named paths | — |
| **`DISTINCT`** | **12.2** | 7/11 | 8.1 | ❌ not in grammar (A4) | 🟢&nbsp;**Low** | `.distinct()` | scalar · container→ |
| arithmetic in expressions | 10.4 | 10/11 | 6.1 | ❌ not built | 🟡&nbsp;**Medium** | `F()`-expression node in projection / WHERE | scalar |
| `STARTS_WITH`/`ENDS_WITH`/`CONTAINS` | 10.3 | 5/11 | 4.6 | ✅ shipped (B2) | — | — | scalar |
| undirected edge | 10.1 | 8/11 | 5.7 | ✅ shipped | — | — | — |
| `COUNT` | 9.9 | 10/11 | 11.7 | ✅ shipped | — | — | — |
| `coalesce()` | 8.7 | 5/11 | 3.9 | ❌ not in grammar (H1) | 🟢&nbsp;**Low** | `Coalesce()` function | scalar |
| `labels()`/`type()`/`keys()` | 6.7 | 7/11 | 5.5 | ✅ exported by envelope (§3.6) — scalar fn form not built (redundant) | ⚪&nbsp;n/a | exported by the typed envelope; scalar fn form redundant | — |
| `OPTIONAL MATCH` | 6.5 | 6/11 | 3.1 | ✅ shipped (D1, narrow v0) | — | shipped; widening beyond COUNT-only is Medium | — |
| string functions | 6.0 | 5/11 | 2.7 | ❌ not built (H2) | 🟢&nbsp;**Low** | one Django `Func` per fn, on demand | scalar |
| **`shortestPath`** | 5.8 | 5/11 | 2.5 | ❌ not in grammar (E3) | 🔴&nbsp;**Very&nbsp;High** | cost-tracking / different execution strategy or backend | — |
| `IS NULL` / `IS NOT NULL` | 5.0 | 6/11 | 2.4 | ✅ shipped | — | — | scalar |
| list ops / comprehensions | 5.0 | 9/11 | 4.7 | ❌ not built (deliberate subset) | 🟠&nbsp;**High** | comprehension is a sub-expression-language (map/filter over lists) | container→ |
| `size()` | 5.0 | 8/11 | 3.2 | ❌ not built (H2) | 🟢&nbsp;**Low** | `Func` (length) | container→ |
| **`UNWIND`** | 4.8 | 7/11 | 6.6 | ❌ not in grammar (F3) | 🟡&nbsp;**Medium** | unroll a list → UNION / `VALUES` join | container→ |
| `id()` | 4.2 | 4/11 | 4.2 | ⚠ partial (`entity_id` projectable; `id()` fn not built) | 🟢&nbsp;**Low** | expose `entity_id` under an alias | — |
| `=~` regex | 3.7 | 6/11 | 1.6 | ✅ shipped | — | — | scalar |
| `SKIP` / `OFFSET` | 3.4 | 2/11 | 1.5 | ❌ not in grammar (A3) | 🟢&nbsp;**Low** | `qs[n:]` slice | — |
| `CALL` procedure | 2.7 | 4/11 | **26.3 ∆** | 🚫 deliberate omission (→ §3, §5) | 🔴&nbsp;**Very&nbsp;High** | out of scope → route algorithmic slice to analytics backend | — |
| numeric aggregates `SUM`/`MIN`/`MAX`/`AVG` | 2.5 | 4/11 | 1.3 | ❌ not in grammar (C1) | 🟢&nbsp;**Low** | parallel to `COUNT` (`Sum`/`Min`/`Max`/`Avg` annotation) | scalar |
| label-union `(:A\|B)` | 1.9 | 4/11 | 1.1 | ❌ withdrawn (B4 superseded) | ⚪&nbsp;n/a | withdrawn (bare-MATCH + `STARTS_WITH` covers it) | — |
| map projection | 1.9 | 2/11 | 1.4 | ❌ not built (deliberate subset) | 🟡&nbsp;**Medium** | new map-shaped output projection | container→ |
| `CASE WHEN` | 1.8 | 3/11 | 1.2 | ❌ not in grammar (H1) | 🟡&nbsp;**Medium** | `Case(When…)` + grammar for the expression tree | scalar |
| temporal functions | 1.6 | 3/11 | 0.7 | ❌ not built | 🟢&nbsp;**Low** | one Django temporal `Func` per fn, on demand | scalar |
| `reduce()` | 1.2 | 3/11 | 0.6 | ❌ not built | 🟠&nbsp;**High** | list-iteration / fold — a sub-expression-language | container→ |
| `NOT EXISTS { }` | 1.2 | 2/11 | 0.5 | ✅ shipped (`~Exists()`) | — | — | — |
| `CALL { }` subquery | 1.1 | 1/11 | 0.5 | ❌ not built | 🟠&nbsp;**High** | correlated-subquery machinery | — |
| pattern predicate in `WHERE` | 0.9 | 3/11 | 0.4 | ⚠ partial | 🟡&nbsp;**Medium** | `Exists()`-shaped pattern in WHERE | — |
| inline edge props `-[{k:v}]-` | 0.5 | 2/11 | 0.8 | ✅ shipped | — | — | scalar |
| `exists(n.prop)` | 0.5 | 2/11 | 0.5 | ✅ partial (via `IS NOT NULL`/`IS KNOWN`) | 🟢&nbsp;**Low** | mostly done via `IS NOT NULL` / `IS KNOWN` | scalar |
| positive `EXISTS { }` | 0.5 | 1/11 | 0.2 | ❌ not in grammar (D2) | 🟢&nbsp;**Low** | sign-flip of the existing `~Exists()` anti-join | — |
| write clauses (`CREATE`/`MERGE`/`SET`/…) | 0.4 | 1/11 | 1.2–1.7 | 🚫 rejected **by design** (read-only) | 🔴&nbsp;**Very&nbsp;High** | out of scope — new language + trust boundary | — |
| explicit `UNION` | 0.2 | 1/11 | 0.2 | ❌ not in grammar (F2) | 🟡&nbsp;**Medium** | `.union()` + dedup-vs-ALL semantics | — |

† *Pattern var-binding* here means naming nodes/edges in the pattern (`(a)-[e]->(b)`), which ships.
The classifier folds in full **path-variable binding** `p = (a)-[*]->(b)` — that shape *parses* (grammar
line 35, `path_var: NAME "="`) but the executor **rejects** it, same fail-closed posture as var-length
paths; it's wishlist E2 and rides with E1. So the 28.5% overstates the *fully-shipped* slice slightly.

## 3. Non-obvious findings

1. **`COLLECT` (14.9%) massively outranks the numeric aggregates `SUM`/`MIN`/`MAX`/`AVG` (2.5%)** —
   a ~6× gap. Intuition (and the wishlist's Bucket C ordering) treats numeric aggregates as the
   natural "next aggregate after COUNT," but the corpus says list-aggregation is what people actually
   write — it's the N+1-defeater that assembles children-per-parent in one query.
   **Sequencing consequence: promote C2 (`COLLECT`) ahead of C1 (numeric aggregates).** The wishlist
   already tags C2 `extract-ahead` and notes it "unlocks UI shapes that don't yet exist" — the data
   backs that and says do it *first*.

2. **`UNWIND`'s demand signal has arrived.** The wishlist parks F3 (`UNWIND`) as `wait-for-signal`
   ("no demand signal yet"). It's in **7 of 11** app repos at 4.8% (and 6.6% across all-13, *above*
   its own IN-list cousin's all-13 rate). That crosses the wishlist's own promotion bar. It's still
   mid-pack, not urgent — but "no signal yet" is now factually stale.

3. **`CALL` is a library-inflation artifact, not app demand.** It's the #1 feature in the all-13 view
   at **26.3%** — but that is almost entirely apoc's test corpus calling apoc procedures. In the app
   view it collapses to **2.7% (4/11)**. This is the strongest argument in the dataset for the
   app/library split, and it **validates Gryphon's deliberate omission of general `CALL`**: real apps
   don't lean on it; the volume is a standard library testing itself. Where genuine app-side `CALL`
   demand exists it is *algorithmic* (GDS-style pagerank/community/path) — which points at the
   **NetworkX/analytics distinct-backend** (see `doc-gryphon-networkx-opportunity.md`), not at a
   general procedure-call surface.

4. **Security asset-graph corpora are the feature-dense, TAP-adjacent ones — and they lean on exactly
   the reachability tail Gryphon rejects.** BloodHound (CE + both community query packs), awspx,
   cartography, and ThreatMapper are the closest analogues to TAP's own domain (asset/attack graphs).
   They are disproportionately heavy on **var-length paths and `shortestPath`** — attack-path /
   blast-radius queries *are* variable-length reachability. So the E1/E3 tail, low-ranked in the
   general corpus, is **high-ranked in TAP's own neighborhood**. When a TAP customer writes the
   queries a BloodHound user writes, E1 stops being `wait-for-signal`. Worth weighting E1 above its
   raw 14.5% for TAP specifically.

5. **The shipped core is genuinely adequate.** No shipped feature is a rare curiosity, and no top-6
   feature is unshipped. Gryphon's demand-shape strategy — grow on signal, not on Cypher's ToC — has
   in fact tracked demand well: the built set *is* the high-frequency set. The gaps are the
   composition layer (`WITH`), the aggregation layer (`COLLECT`), and the graph-flavored tail
   (var-length / shortestPath) — precisely the three the wishlist already flags as its heaviest,
   highest-value items (F1 ★, C2, E1).

6. **`labels()` / `type()` / `keys()` (6.7%) is not a gap — the typed envelope already exports it.**
   This corrects an earlier "❌ not built" classification that measured the wrong thing (the scalar
   *function* form) instead of the capability. Cypher needs these three functions because its nodes
   are untyped, schema-optional property bags — you must *ask* an instance "what are you / what do you
   have?" at query time. TAP is typed-by-construction, so the values are already first-class in every
   grift envelope element:
   - **`type(e)`** → `edge_type`, a top-level spine field on every edge (`subgraph.py:253`).
   - **`labels(n)`** (the *typing* sense) → `entity_type`, a top-level spine field on every node
     (`Entity.SPINE_FIELD_NAMES`).
   - **`labels(n)`** (the *tag / categorization* sense) → **`dimensions`**, also a top-level spine
     field on every node. Cypher *overloads* one `:Label` for both type and tag; TAP cleanly **splits**
     them into `entity_type` + `dimensions` — a Ledger-A credit, not a gap.
   - **`keys(n)`** → the `data` lane is an object *keyed by field name*, so the property-key list is
     the shape of the returned data; the authoritative key set is the declared type schema (the
     `entity_types` endpoint / registry), which is stronger than per-instance introspection.
   All of the above are guarded by a spine drift test (`test_entity_spine.py`). A scalar `labels()`/
   `type()`/`keys()` usable *inside a WHERE/expression* is unbuilt but largely redundant — filtering by
   type is `MATCH (:type)` / dimension scoping, and the values are already in the output.
   **This is the same pattern as §7.4.1 (export) and §7.4.3 (schema): a Cypher function that exists to
   compensate for untyped schema-optional graphs, dissolved by TAP's typed, declared, first-class-in-
   envelope structure.** Three instances is a theme worth stating plainly — *a meaningful slice of
   "Cypher features Gryphon lacks" are features Gryphon doesn't need because the data model already
   answers them structurally.* Watch for this when reading any Gryphon-vs-Cypher gap as debt.

## 4. The apoc/GDS skew (why two views)

The two library corpora carry disproportionate raw volume and distort per-query rates:

| Corpus | Read queries | Share of all-13 | Nature |
| --- | :--: | :--: | --- |
| `neo4j/apoc` | 668 | **52%** | a standard-library test suite calling its own procedures |
| `neo4j/graph-data-science` | 62 | 5% | algorithm-library test fixtures + docs |
| all 11 real apps combined | 565 | 44% | actual application queries |

apoc alone is over half the raw corpus, and it is *not* representative of application demand — it is
a library exercising itself, which is why `CALL` balloons to 26.3% in the all-13 view and collapses
to 2.7% in the app view. **The app-focused view (§0, §2) is the one to sequence against.** The
all-13 column is retained only to make the skew visible and auditable.

## 5. What this means for the wishlist and the commandments

The data doesn't move the top of the list — it **confirms F1 `WITH`** as the keystone, matching the
wishlist and all three external studies. What it changes:

- **Re-order Bucket C:** `COLLECT` (C2) before numeric aggregates (C1). Finding §3.1.
- **Promote `UNWIND` (F3)** out of `wait-for-signal` into a named candidate. Finding §3.2. (Still
  behind F1/C2 — mid-pack, not headline.)
- **Keep `CALL` omitted** as an app-demand call, and route the genuine algorithmic slice to the
  analytics backend, not to a general `CALL`. Finding §3.3 + `doc-gryphon-networkx-opportunity.md`.
- **Reachability demand is affirmed, but the mechanism is named paths, not var-length E1.** TAP's
  asset-graph neighborhood is reachability-heavy (§3.4), but the planned implementation replaces
  reachability-by-traversal with **named-path membership** — see §5.1. So the earlier "weight E1 up"
  call is superseded: var-length `-[*n..m]-` stays parse-but-reject; the demand is met structurally.
- **The commandments (`doc-gryphon-commandments.md`) need no change from this** — the doctrine is
  about *how* features ship (fail-closed, apply-or-reject, source-checked, oracle-pinned), not
  *which*. This doc feeds the wishlist's ordering, not the commandments' rules. Its one relevant
  reinforcement: features that "parse but reject" (var-length, path-var) are the fail-closed credit
  in action (GRY-ARCH-3) — the corpus shows they're *demanded*, which is what makes fail-closed
  (vs. silent-wrong) the right posture until they're built.

### 5.1 Reachability is served by named paths AND variable-length traversal — they are complementary (corrected 2026-09-22, per George)

> **CORRECTED 2026-09-22.** This section previously said the planned implementation *"replaces
> reachability-by-traversal with reachability-by-declared-path membership"*, and that var-length
> `-[*n..m]-` was therefore not on the near-term path because *"the reachability demand it represents
> is met by the named-path primitive instead."* That was George's July 2026 position and he has
> revised it. The substitution claim is withdrawn; the rest of the section — the three
> implementations, the APOC comparison, the design input — stands. The correction is recorded rather
> than silently rewritten, because a study that shows where it changed its mind is worth more than one
> that appears never to have needed to.
>
> George, 2026-09-22: *"paths and traversals are two different, but complimentary things. paths are
> designed to be persistent, traversals are ad-hoc / real-time. they're apples and oranges but both of
> them are fruit."*

The demand this study surfaces for Bucket E (attack-path / blast-radius reachability, §3.4) is real,
and it is served by **two primitives, not one**. **Named paths become first-class declared structure**,
so "is the route we named still intact?" becomes an indexed membership filter rather than a query-time
graph walk. That is a genuine and large win. It is not the same question as "what routes exist?", and
it cannot be made into one.

**Why substitution cannot work, stated once so nobody re-derives it.** Declared membership answers a
question about a route somebody already named. Reachability asks what routes exist, *including the
ones nobody named*. The second cannot be derived from the first: falsification machinery can tell you
whether a recorded fact is still true, and can say nothing whatsoever about a fact that was never
recorded. An instance is exactly the case that matters — `vuln-triage` asks "what route exists from
here to that?", and a declared path cannot enumerate the route nobody thought to declare.

**The genus, and what the two therefore share.** Both are statements about connectivity, which means
they want ONE vocabulary rather than two. GQL's ISO-standard restrictors (`WALK` / `TRAIL` / `SIMPLE`
/ `ACYCLIC`) and selectors (`ANY`, `ALL SHORTEST`, `SHORTEST k`) describe what *kind* of route is
meant, and that question is identical whether the route is being declared or being found. Inventing
separate TAP vocabulary for each side would be the private-notation trap twice over.

**The four axes on which they differ.** These are the reason they are not interchangeable, and each
has a design consequence:

| Axis | Traversal | Declared path |
| --- | --- | --- |
| **Time** | True at the instant of the query; claims nothing beyond it | A standing claim that persists *so that it can be falsified* — you cannot detect drift against something that evaporates |
| **Cost** | Scales with the **branching** factor | Revalidation scales with **length** — Θ(k), measured. Different curves, so neither subsumes the other's cost |
| **Lifecycle** | None | Identity, version, owner, tombstone, history. "Chart how this path changed" has no traversal equivalent |
| **Authorization** | Filtered per query by the viewer's dimensions — the viewer simply sees less | An **object** with its own dimensions, readable by someone who cannot see its members. Persistence is what turns "you saw less" into "you saw that something was hidden" — an inference channel that exists on only one side |

**And the bridge, which the original framing could not express.** A traversal is how you *find* a path
worth declaring. Walk the graph, find the route that matters, **save it as a path**. Discovery feeds
declaration; declaration then makes that route monitorable in a way a repeated query never is. Framing
one as the successor to the other hides this workflow entirely, and without it declared paths are
something a user must author from scratch — which is how a good primitive goes unused.

**Promotion is therefore a requirement, not an implication (ruled 2026-09-22, George).** "Save this
route as a path" is the gesture that connects the two primitives, and it needs to be a named thing the
spec pass carries rather than something a reader infers from the paragraph above. It answers the
question nothing else currently answers — *where do declared paths come from?* — and without it,
declaration is something a user must author from scratch against a blank page, which is the ordinary
way a good primitive ships and goes unused. The traversal that found the route already knows the
edges; promotion is the act of freezing that answer into an object with a name, an owner and a
history.

The product is the **gap between them**: a path TAP discovers is a fact about the graph this morning; a
path somebody declares is a claim about how the organisation believes it works. The distance between
the two has a name in three separate literatures — conformance, drift, reconvergence — it is
measurable, and it is precisely what cannot be computed if only one side was ever stored.
Three implementations, in order (the first two targeted near-term):

1. **Module / model-defined paths** — a module declares its trajectory along a named path at the model
   level; path membership can also be carried *through an edge* (an edge type asserts the path).
2. **User-defined paths** — users mark, in a node/edge *field*, that the element exists along a named
   path (instance-level annotation).
3. **Dynamic grid-level path types** — path types definable dynamically on the grid at runtime.

Path *types* are thus definable both at the model level (static, by modules) and dynamically on the
grid (by users). **This is the same architectural move as §3.6 / §7.4.1 / §7.4.3 — replace a
query-time computation with declared, first-class structure** (the *fourth* instance of the pattern).
Cypher/APOC users hand-roll reachability per query — `apoc.path.expandConfig` with `sequence` /
`relationshipFilter` strings is *literally an inline trajectory definition, re-specified every call*
(§7.3). TAP declares the trajectory once as a named path and filters by membership; the APOC `sequence`
config is the query-time shadow of what TAP makes a first-class type.

**Consequences for this study (revised 2026-09-22):** var-length `-[*n..m]-` remains parse-but-reject
(fail-closed) **today**, which is the correct posture for an unbuilt feature — but it is no longer
*deprioritised on the grounds that named paths cover it*, because they do not. E1's demand stands on
its own and the named-path primitive is additive to it, not a substitute. The original text is
preserved in the correction note above. `shortestPath` (true least-cost / centrality) is a separate concern and still routes to the
analytics backend (`doc-gryphon-networkx-opportunity.md`), not to named paths. Design input still
transfers: APOC's `expandConfig` knobs (edge-type / label / depth / node allow-deny, §7.3) are the
vocabulary a named-path *definition* will want to express.

## 6. Doc-drift caught while verifying supply-side status (fixed 2026-07-06)

`doc-dev-gryphon-vs-cypher.md` (Ledger C, row "Variable-length paths") previously stated *"Bounded
repetition (`*1..3`) ships."* **It does not.** The grammar parses `*n..m` (`hop_range`, grammar line
55) but the executor rejects bounded multi-hop (`executor.py:412` and `:1652` raise
`SearchExecutionError`; rejection is pinned by `test_gryphon.py`; `model_oracle.py` marks it
`OracleUnmodeled`). The correct status is **"parses but the executor rejects — fail-closed, not
shipped"** (this is E1, still `wait-for-signal`). This is the same overclaim the comparative study
caught in its own synthesis and codified as GRY-PROC-2 (source-check executor claims). **The Ledger-C
row has since been corrected** to match the executor.

## 7. APOC heavy-hitters — the "what Cypher didn't ship" map (whole-TAP lens)

APOC is the de-facto standard library every serious Neo4j shop installs — so *what it contains* is
a direct readout of **what professional graph-database users needed that Cypher itself didn't ship.**
That signal is bigger than Gryphon: most of APOC is not query-language surface at all, it's the
operational/ETL/admin machinery a graph *platform* needs. Cypher-the-language couldn't absorb it, so
APOC bolted it on. TAP's job is to place each of those needs in the *right* layer — and most already
have a deliberate home. This section maps the full APOC surface onto TAP's architecture.

**Method & caveat.** Scanned the `neo4j/apoc` core repo's test-string literals + docs (blobless
clone; 3093 `apoc.*`-bearing literals; 392 distinct procedures across 48 namespaces), counting
distinct-literals-using-each once. **Same self-referential caveat as `CALL` in §3.3: this is APOC's
own test suite exercising APOC, so it measures which procedures APOC considers important surface
area, not independent third-party call frequency** (the app corpora barely call APOC — §3.3). Read it
as "the shape of the gap APOC exists to fill," not as app demand. (`neo4j/apoc` core is also slimmer
than the old `neo4j-contrib` full-APOC; the *distribution* is representative, absolute counts are not.)

### 7.1 The headline: APOC is two libraries, and only one is Gryphon's

The top-5 namespaces by volume span **three different TAP layers** — that alone kills any "Gryphon is
missing 80% of APOC" reading:

| Rank | Namespace | Count | What it is | TAP layer |
| :--: | --- | :--: | --- | --- |
| 1 | `apoc.export` | 323 | dump graph/results → csv/json/cypher/graphml/arrow | **mostly met** by Gryphon's grift JSON envelope (§7.4.1) |
| 2 | `apoc.coll` | 273 | list/collection operations | **Gryphon** (expression) |
| 3 | `apoc.text` | 232 | string functions | **Gryphon** (expression) |
| 4 | `apoc.trigger` | 207 | react-to-change database triggers | **TAP reactive** (FLIP/signals) |
| 5 | `apoc.path` | 162 | expand / subgraph / reachability | **Gryphon** (Bucket E) + analytics backend |

So "what Cypher didn't ship" isn't one gap — it's **get-data-out, richer expressions, reachability,
and change-reaction**, and those belong in four different places in TAP. Crucially, two of the top
four are *already answered* by surfaces TAP has shipped: get-data-out by the Gryphon **grift JSON
envelope** (`tap_api/routers/gryphon.py` → `SubgraphLayer`) and schema-description by the **entity /
type endpoints** (`entity_types.py`, `entities.py`, `edges.py`). See §7.4.

### 7.2 Full namespace map → TAP destination

Every namespace with its architectural home. **Gryphon** = query-language expression/read;
**Analytics** = whole-graph algorithms → the NetworkX/distinct-backend idea
(`doc-gryphon-networkx-opportunity.md`); the rest are non-language TAP platform concerns.

| Namespace | Ct | Destination | Notes / does TAP have a home? |
| --- | :--: | --- | --- |
| `apoc.export` | 323 | **mostly met — grift envelope** | JSON get-data-out already ships: Gryphon returns the canonical grift `{nodes,edges}`+lanes envelope (`gryphon.py`→`SubgraphLayer`). Residual = thin format *adapters* (CSV/GraphML) over that envelope; bulk/backup dump is Postgres-native (`pg_dump`) and inflates this count. See §7.4.1. |
| `apoc.coll` | 273 | Gryphon | list ops: `containsAll`,`toSet`,`combinations`,`occurrences` → list-comprehension / list-fn gap |
| `apoc.text` | 232 | Gryphon | string fns (H2). Heavy-tested ones are niche (`toCypher`,`charAt`,`slug`,`snakeCase`) → confirms "one fn at a time on demand" is right |
| `apoc.trigger` | 207 | TAP reactive | react-to-change hooks (`install`,`add`,`pause`) → TAP's FLIP/history + sparing signals; **read-only Gryphon deliberately can't and shouldn't** |
| `apoc.path` | 162 | Gryphon (E) + Analytics | `subgraphNodes`(51),`expandConfig`(41),`subgraphAll`(23),`spanningTree`(14) → reachability, see §7.3 |
| `apoc.refactor` | 147 | TAP service-layer | `rename`,`mergeNodes`(37!),`cloneSubgraph`,`deleteAndReconnect` → entity-merge/dedup is a real op → typed service layer + FLIP |
| `apoc.meta` | 146 | **met — entity/type endpoints + registry** | `relTypeProperties`,`nodeTypeProperties`,`stats`,`graph` → schema introspection → **already shipped**: `entity_types.py` (`GET /entity_types/` → slug/name/description/plugin) + registry-backed discovery (Player-3 legibility). Thin residual = live *stats* (per-type counts / property-coverage), demand-gated. §7.4.3 |
| `apoc.schema` | 122 | TAP migrations | `assert`,`nodes`,`properties` → index/constraint DDL → Django migrations + index mgmt |
| `apoc.load` | 110 | TAP ingestion | `load.json`/`xml`/`arrow` — pull external data into queries → plugin ingestion layer |
| `apoc.import` | 110 | TAP ingestion | `import.csv`/`graphml`/`json` — bulk ingest into the graph → ingestion pipeline (Django Tasks) |
| `apoc.nodes` | 95 | Gryphon + Analytics | `connected`(25),`group`,`collapse`,`cycles`,`isDense` → inspection (Gryphon) + graph-transform (analytics) |
| `apoc.create` | 91 | TAP service + display-lane | `virtual`/`vNode`/`vRelationship` = *ephemeral non-persisted* nodes for return/viz → maps to display-lane / computed rows; `setProperty` = write |
| `apoc.map` | 88 | Gryphon | `fromPairs`,`submap`,`mget`,`removeKeys` → map projection gap |
| `apoc.convert` | 85 | Gryphon | `toTree`,`toJson`,`fromJsonMap` → type conversion / JSON (Gryphon already has JSON reach) |
| `apoc.graph` | 70 | Analytics | `fromDB`,`fromDocument`,`fromCypher` = **named virtual-graph projection** → exactly the "project a subgraph" primitive GDS/NetworkX need |
| `apoc.periodic` | 68 | TAP scheduling | `iterate`(29),`submit`,`repeat` = batched background mutation → Django Tasks |
| `apoc.agg` | 67 | Gryphon (C) | `percentiles`,`median`,`product`,`statistics` → aggregation is *statistical*, beyond SUM (§7.3) |
| `apoc.util` | 65 | TAP util | `compress`/`decompress`,`sleep`,`validatePredicate` → misc ops |
| `apoc.date` | 59 | Gryphon | `parse`,`field`,`format` → temporal-fn gap (+ `apoc.temporal` 26) |
| `apoc.node` | 58 | Gryphon | `relationship`,`degree`,`labels` → element inspection → projection surface |
| `apoc.number` | 58 | Gryphon | `exact`,`format`,`parseInt` → numeric formatting/parsing (+ `apoc.math` 45, `apoc.bitwise` 6) |
| `apoc.cypher` | 56 | TAP execution-safety | `runTimeboxed`(13!),`runManyReadOnly`(5),`runMany` → **query timeout + read-only enforcement**: Gryphon is read-only *by construction* (a credit APOC has to bolt on); timeboxing is a real exec-safety item to consider |
| `apoc.atomic` | 47 | TAP service-layer | `add`,`subtract`,`concat` = concurrency-safe field updates → service-layer concern |
| `apoc.math` | 45 | Gryphon | trig/`sigmoid`/`tanh` — mostly niche |
| `apoc.any` | 44 | Gryphon | `property`(25),`properties` = dynamic property access → projection |
| `apoc.merge` | 37 | TAP service-layer | `merge.node`/`relationship` = upsert → service layer |
| `apoc.algo` | 36 | **Analytics** | `cover`,`dijkstra`,`allSimplePaths`,`aStar` = **graph algorithms** → NetworkX/distinct-backend, NOT Gryphon core |
| `apoc.hashing` | 31 | TAP util | fingerprint/diff a graph or node |
| `apoc.search` | 28 | Gryphon | multi-label/multi-prop node search → predicate power |
| `apoc.temporal` | 26 | Gryphon | temporal formatting (with `apoc.date`) |
| `apoc.spatial` | 21 | out-of-scope (v0) | geo — no TAP demand |
| `apoc.neighbors` | 18 | Gryphon (E) + Analytics | n-hop neighbor gather → reachability |
| `apoc.paths`/`apoc.rel`/`apoc.label`/`apoc.json`/`apoc.diff`/`apoc.do`/`apoc.data`/`apoc.scoring` | ≤14 ea | mixed | tail: path helpers (Gryphon-E), rel/label inspection (Gryphon), conditional write (`do`→service), scoring (analytics) |
| `apoc.lock`/`apoc.warmup`/`apoc.stats`/`apoc.log`/`apoc.xml`/`apoc.initializer`/`apoc.example` | ≤12 ea | TAP infra | locking, cache-warm, logging, startup — pure platform infra |

### 7.3 Detail on the Gryphon-relevant expression/reachability tail

Top procedures within the namespaces a read query-language could actually absorb:

- **`apoc.path` (reachability) — the standout, and it tells us the *shape* E1 should take.** People
  don't want bare `*1..3`; they want `expandConfig`-style reachability: `relationshipFilter`,
  `labelFilter`, `sequence` strings, uniqueness modes, min/max depth, allow/deny node lists
  (`subgraphNodes`, `expandConfig`, `subgraphAll`, `spanningTree`). **Design input for Bucket E:** the
  demanded primitive is "expand from a seed under edge-type + label + depth + node-set constraints,"
  and `subgraph*` is literally the *bounded-subgraph-projection* the NetworkX backend needs.
- **`apoc.coll` / `apoc.text` — the function-library gap, confirmed but diffuse.** No obvious
  must-have-first trio; heavy-tested procedures are edge-casey (`combinations`, `occurrences`,
  `toCypher`, `slug`). Reinforces Gryphon's demand-gated "one function at a time" posture (H2) over
  shipping a library ahead of demand.
- **`apoc.agg` — aggregation demand is statistical.** `percentiles`, `median`, `product`,
  `statistics` — beyond `SUM`/`MIN`/`MAX`/`AVG`. Still thin/specialized; `COLLECT` (§3.1) remains the
  higher-priority aggregate. `apoc.agg` is a "someday, on demand" signal for Bucket C.
- **`apoc.map` / `apoc.convert` / `apoc.date` / `apoc.number`** — map projection, JSON/type
  conversion, temporal, numeric formatting. Each maps to a named wishlist future-seam; none is urgent.

### 7.4 What the operational half tells TAP (beyond Gryphon)

Reading the ETL/admin majority as a platform-feature checklist — *what a mature graph platform needs*
— and checking it against TAP's architecture:

1. **Get-data-out is *mostly already solved* — by the grift envelope. (Corrected.)** An earlier draft
   called this TAP's "#1 unmet gap"; that overclaimed. APOC's `export.*` is fundamentally *data
   serialization*, and Gryphon already emits the canonical structured form: a **grift three-lane JSON
   envelope** (`{nodes,edges}` + `data` + `display`), or a row-projection under `RETURN`, served by
   `tap_api/routers/gryphon.py` (`SubgraphLayer`) — and it's the progressively-more-robust read path
   Gridkin already asserts against. For the dominant "get a scoped subgraph out as structured data"
   case, **TAP has this.** What genuinely remains is narrow: (a) **alternate serialization formats**
   (CSV for analysts, GraphML for tool interchange) — a *thin adapter over the envelope Gryphon
   already produces*, not a missing data-access capability; and (b) **bulk / full-DB dump at scale**
   (backup/migration) — which is **Postgres-native (`pg_dump`)**, not a graph-platform feature, and is
   exactly what inflates `export`(323) (much of `export.cypher`→`import.cypher` is round-trip backup
   testing). So: format adapters are a demand-gated convenience; there is no large export gap.
2. **The mutation/reaction surface is already placed by architecture — APOC validates the aim.**
   `trigger`(207, react-to-change), `refactor`(147, merge/dedup/restructure), `merge`/`atomic`/`do`
   (upsert/concurrency/conditional-write) are exactly what TAP routes through the **typed service
   layer + FLIP/history + sparing signals**. That professionals lean this hard on entity-merge
   (`mergeNodes`) and change-triggers is confirmation TAP's write-path architecture is aimed right —
   and confirmation Gryphon should stay read-only (these must never leak into the language).
3. **Schema description is *already shipped*, not a need. (Sharpened.)** `meta`(146) + `schema`(122) =
   "make the schema queryable / assert structure." TAP already answers the description half with a
   **whole entity/type endpoint surface** — `entity_types.py` (`GET /entity_types/` → slug, name,
   description, icon, plugin), plus `entities.py` / `edges.py` — backed by the **registry-backed
   discovery system**. So this is not a gap; it's a *confirmation* that building queryable,
   machine-legible schema was worth it (the Player-3 / `build-for-ai-helpers` posture): professionals
   demonstrably demand queryable schema, and TAP has it. The only thin residual is live **stats /
   profiling** (`apoc.meta.stats`/`graph` = per-type counts, property-coverage, degree distributions),
   which TAP could compute over the same registry when a demand signal arrives — demand-gated, minor.
   (`apoc.schema`'s index/constraint *DDL* half is Django migrations, not an endpoint concern.)
4. **The graph-algorithm + projection tail points, again, at the analytics backend.** `algo`
   (dijkstra/aStar/allSimplePaths/cover) + `path.subgraph*` + `graph.from*` + `agg.graph` = whole-graph
   computation and named subgraph projection — the exact class `doc-gryphon-networkx-opportunity.md`
   scopes to a distinct backend, not to Gryphon. APOC bundling these is external validation that
   they're a *separate* concern from pattern-query.
5. **Execution-safety primitives worth stealing.** `apoc.cypher.runTimeboxed` / `runManyReadOnly`:
   query **timeout** and **read-only enforcement**. Gryphon already owns read-only by construction (a
   credit); **timeboxing / resource-bounding of a Gryphon query** is a genuine exec-safety item to
   consider (ties to battle-hardening and the security posture).

**Net for Gryphon development:** APOC re-confirms the language gap shape (collections, strings,
reachability, maps, dates, conversion — grow on demand) and, most usefully, shows that **reachability
(`apoc.path.expandConfig`-shaped, Bucket E) is the one place where the demanded feature is genuinely
*query-language*-shaped rather than operational** — everything heavier than that is either the
analytics backend or a non-language TAP platform layer that already has a home. The stronger, more
honest conclusion after the two corrections above (§7.4.1, §7.4.3): **APOC's operational majority is
already placed in surfaces TAP has shipped or deliberately sited** — the grift envelope (get-data-out),
the entity/type endpoints + registry (schema description), the typed service layer + FLIP (mutation /
merge / triggers), Django Tasks (batched background work), and ingestion plugins (load/import). The
genuinely-additive residuals are all *thin and demand-gated*: format adapters (CSV/GraphML) over the
existing envelope, live schema stats/profiling, and query timeboxing. Read the whole exercise as
**external validation that TAP's architecture is aimed right**, not as a backlog of large platform
gaps. Even reachability (Bucket E) — the one place that looked like a genuinely-owed *query-language*
feature — is planned to be answered structurally too, by **named paths** rather than variable-length
traversal (§5.1): the same "declared structure over query-time computation" move, applied a fourth
time. The genuinely-owed language features shrink to composition (`WITH`) and aggregation (`COLLECT`).

## Pointers

- **Supply side (what ships):** `doc-dev-gryphon-vs-cypher.md` (the three ledgers), `doc-dev-gryphon-wishlist.md` (the buckets this re-sequences).
- **The algorithmic-`CALL` destination:** `doc-gryphon-networkx-opportunity.md`.
- **The doctrine this respects:** `doc-gryphon-commandments.md` (fail-closed GRY-ARCH-3, source-check GRY-PROC-2).
- **External corroboration:** SLE 2019 Cypher-in-the-wild study; Neo4j Text2Cypher dataset; Francis et al., SIGMOD 2018 (semantic taxonomy).
- **Raw aggregation (§0–§5):** workflow `wf_684476bc-36b` journal (per-repo `feature_counts`), aggregated deterministically; re-derivable from the journal.
- **APOC scan (§7):** `neo4j/apoc` core repo, blobless clone; `apoc.*` tokens extracted from test-string literals + docs, counted once-per-literal; re-derivable by re-cloning and re-scanning.
- **The analytics/algorithm destination (recurring):** `doc-gryphon-networkx-opportunity.md` — where `apoc.algo`/`apoc.path.subgraph*`/`apoc.graph.from*` land.
- **The reachability answer (§5.1):** `grid-native-paths-notes.md` — the grid-native named-path design; its Future Prior Art Pass now carries a note to revisit the APOC `expandConfig` knobs (§7.3) as path-definition vocabulary.
