# Gryphon Multi-Hop and Aggregation Extension Specification

> **Development doctrine (standing filter).** Before any change to the Gryphon language, executor, or tests, consult [`doc-gryphon-commandments.md`](../../docs/doc-gryphon-commandments.md) — the standing thou-shalt/shalt-not doctrine for all Gryphon work (RFC-2119 commandments with Reason + Enforcement, plus a Forthcoming section). Requirements here SHOULD stay consistent with it; it cites requirements here as its Enforcement anchors.

## Philosophy

Gryphon v1 is deliberately small: single-hop `MATCH` patterns, predicate `WHERE` clauses, projection-only `RETURN`. That floor fit the first wave of TAP searches — type scans, hub-and-spoke traversals, simple predicate filters — and left obvious escape valves (module-based Python runners) for anything more ambitious.

This spec extends gryphon along three axes to unlock a class of queries that are becoming idiomatic, not exotic: **multi-hop patterns**, **anti-join subqueries** (`NOT EXISTS`), and **count aggregation with implicit grouping**. The motivating query is the compliance alert-count traversal — "per entity, count open findings that have no active exception covering them" — but the same three extensions unblock many other shapes: cross-layer traversals, coverage audits, gap analysis, and most summary tiles that reduce graph structure to a tabular result.

The choice to extend the language, rather than push the query into a custom Python runner, is deliberate. Each custom runner is a chunk of code that bypasses the gryphon compilation pipeline and its validation, read-only guarantees, and backend-agnosticism. Runners are the right tool when semantics exceed what a declarative query can express; they are the wrong tool when the semantics *can* be declared and we're just missing language surface. This extension keeps semantics declarative wherever the query shape allows it.

The extension is scoped tight on purpose. `COUNT` is the only aggregate; `SUM`/`AVG`/`MIN`/`MAX` are not in scope. `NOT EXISTS` covers anti-joins but `EXISTS`, `OPTIONAL MATCH`, and `UNION` do not. Variable-length traversal (`-[*1..3]->`) remains rejected by the executor even though the grammar parses it. Each deferred item has a clear upgrade path when a real use case arrives.

**Gryphon commandment guidance.** Multi-hop, anti-join, aggregation, optional-match, and future
recursive-path work must read and apply
[`doc-gryphon-commandments.md`](../../docs/doc-gryphon-commandments.md). This spec
owns the concrete feature requirements; the commandments supply the durable development discipline
for avoiding silent drops, join drift, unsupported-shape approximation, and oracle/test gaps.

## Goals

|    |              |                                                                          |
| :---: | ---       | ---                                                                      |
| 1. | Declarative     | Queries the language *can* express stay in the language, not in custom Python runners |
| 2. | Minimal-Surface | Only the constructs needed by the motivating class of queries; no speculative grammar |
| 3. | Safe            | Read-only, validation, and service-layer posture from v1 carry through unchanged |
| 4. | Compatible      | Every existing gryphon query continues to parse, execute, and return identical results |
| 5. | Extensible      | Grammar, AST, and executor changes leave clean seams for deferred work (other aggregates, EXISTS, variable-length, UNION) |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-gryphon-multihop | [Multi-Hop Pattern Execution](#multi-hop-pattern-execution) | Implemented | N-hop outer patterns executable; NOT EXISTS inner may also be multi-hop |
| req-grid-gryphon-not-exists | [NOT EXISTS Subqueries](#not-exists-subqueries) | Implemented | New grammar production for correlated anti-join subqueries |
| req-grid-gryphon-count | [COUNT Aggregation and Implicit GROUP BY](#count-aggregation-and-implicit-group-by) | Implemented | `COUNT(var)` in RETURN, implicit GROUP BY on non-aggregated columns |
| req-grid-gryphon-rows | [Rows Result Envelope](#rows-result-envelope) | Implemented | Canonical envelope gains a `rows` key populated by aggregating queries |
| req-grid-gryphon-multihop-envelope | [Multi-Hop Graph Envelope](#multi-hop-graph-envelope) | Implemented | Multi-hop queries return graph envelope (nodes + edges) when RETURN is omitted or uses bare variables |
| req-grid-gryphon-order-by | [ORDER BY Row Ordering](#order-by-row-ordering) | Implemented | `ORDER BY` over row-projection outputs; ascending default, `DESC` explicit, multi-key, deterministic tiebreak |
| req-grid-gryphon-limit | [LIMIT Row Capping](#limit-row-capping) | Implemented | `LIMIT n` caps row-projection output; compiles to SQL `LIMIT` |
| req-grid-gryphon-optional-match | [OPTIONAL MATCH Left-Outer Join](#optional-match-left-outer-join) | Implemented | `OPTIONAL MATCH` keeps mandatory rows that have no optional match; `COUNT` of the optional variable is 0, not absent |
| req-grid-gryphon-order-by-envelope | [ORDER BY / LIMIT On A Type-Scan Graph Envelope](#order-by--limit-on-a-type-scan-graph-envelope) | Implemented | A labelled type-scan with envelope `RETURN` accepts `ORDER BY <var>.<field-path>` and `LIMIT`; compiles to SQL `ORDER BY` / `LIMIT` |
| req-grid-gryphon-distinct | [RETURN DISTINCT Row Deduplication](#return-distinct-row-deduplication) | Proposed | `RETURN DISTINCT <field projections>` dedups projected rows via SQL `SELECT DISTINCT` (incl. JSON scalar sub-keys); composes with `ORDER BY` / `LIMIT`; single-var envelope honored as no-op; `count(DISTINCT)`, multi-var envelope, JSON-container, and aggregate-return DISTINCT rejected |
| req-grid-gryphon-compat | [Backward Compatibility](#backward-compatibility) | Implemented | Existing queries parse, execute, and return identical results |

---

### Multi-Hop Pattern Execution
----
RID: `req-grid-gryphon-multihop`

Status: `Implemented`

The executor accepts `MATCH` patterns with more than one edge hop, producing results that join each declared hop by shared variable.

#### Implementation

- No grammar change required. The grammar already parses `pattern: node_pattern (edge_pattern node_pattern)*` as multi-hop.
- Executor composes a single `Edge` queryset with reverse-FK joins: each additional hop is reached via the previous hop's shared-node path plus `edges_out` (for `->`) or `edges_in` (for `<-`). All hop filters (edge_type, endpoint labels) are collapsed into one `.filter(**kwargs)` call so Django reuses a single JOIN per unique path.
- The WHERE predicate is folded into that SAME `.filter()` call (`_build_chain_queryset(..., predicate=..., bindings=...)`), not applied as a separate `.filter()`. This is load-bearing for a predicate on a node BEYOND the root edge: such a predicate resolves through a reverse-FK path (`to_entity__edges_out__…`) identical to a structural hop path, and a separate `.filter()` on a multi-valued path makes Django spawn a SECOND join carrying none of the structural edge_type/label filters. The projection then bound to that duplicate join, silently returning far nodes reached by the WRONG edge type and inflating COUNT. Folding predicate and structure into one call reuses the single structural join, so the far-node WHERE constrains exactly the chain's far node. (The `NOT EXISTS` inner queryset, whose correlation is layered on afterward, still applies its WHERE via `_apply_predicate_to_qs`.)
- Semantics: `MATCH (a)-[:E1]->(b)-[:E2]->(c)` produces the set of `(a, b, c)` triples where `a -E1-> b` and `b -E2-> c` both hold.
- Directionality: each edge pattern's arrow is honored independently. `-[:E]->` and `<-[:E]-` each behave as in single-hop. Undirected `-[:E]-` remains rejected by the aggregation executor with a targeted error.
- Node labels on intermediate nodes may be omitted (wildcard) or present (type filter).
- RETURN projection columns and COUNT sources are pre-annotated via `F()` aliases so Django reuses JOIN aliases across filters, aggregates, and OuterRef correlations. Without this, COUNT on a multi-hop outer produces inflated counts because Django adds a duplicate LEFT OUTER JOIN for each reference to the reverse-FK path.
- NOT EXISTS correlation with a multi-hop outer uses the same F-alias strategy: the outer's shared-variable entity_id is pre-annotated and `OuterRef` references the alias rather than the raw reverse-FK path.
- Path variable binding (`path = MATCH (a)-[]->(b)`) remains parseable but executor-unsupported.
- Variable-length edges (`-[:E*1..3]->`) remain executor-rejected with an unsupported-feature error.
- Multi-hop queries with no outer WHERE clause emit a `multi_hop_no_anchor` warning in the envelope's `warnings` dict; callers should add an anchor or LIMIT.

#### Development

Multi-hop is the largest of the three language changes in this spec because it shifts the compiler from "one edge queryset" to "composed joins." The discipline here is to implement the simplest correct join path — one ORM join per hop, anchored by a WHERE predicate where one exists — and not reach for query-planner heuristics. The JOIN-reuse trick via `F()` annotation aliases was necessary to prevent count inflation when COUNT arguments or OuterRef paths reference the same reverse-FK chain that filters already touched.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-gryphon-multihop-1 | N-Hop Chains | Implemented | The executor accepts and correctly joins MATCH patterns with two or more edge hops. | `_build_chain_queryset` + F-alias annotation pattern |
| req-grid-gryphon-multihop-2 | Directionality Per Hop | Implemented | Each hop's direction (`->`, `<-`) is respected independently. | Undirected `-[:E]-` still rejected |
| req-grid-gryphon-multihop-3 | Optional Intermediate Labels | Implemented | Intermediate node patterns with no label are treated as any-type and still bind their variable. | |
| req-grid-gryphon-multihop-4 | Variable-Length Still Rejected | Implemented | `-[:E*m..n]->` patterns continue to be rejected at the executor with an unsupported-feature error. | Grammar parses them; deferred to a future iteration |
| req-grid-gryphon-multihop-5 | Single-Hop Results Unchanged | Implemented | Queries with exactly one hop produce identical results to the pre-extension executor. | See `req-grid-gryphon-compat` |

#### Future

- Variable-length traversal with explicit bounds and cycle semantics.
- Path variable binding and path-level projections.
- Query planner heuristics for anchor selection when multiple WHERE clauses are equally viable.
- Row-level negation of a far-node (past-the-root-edge) predicate — `!=` or `NOT (...)` on a node reached through a reverse-FK hop. Today it is *rejected* (`_guard_negated_far_predicate`): Django lowers a negated comparison over a multi-valued relation to an existential anti-join subquery, which crashes (`bigint = uuid`) and carries per-pattern, not per-binding, semantics. Full support needs per-field `F()` annotation so the negation lands on the joined column rather than the relation path (the same JOIN-reuse-via-`F()` trick already used for COUNT/OuterRef). Positive / `OR` / `IN` / `IS NULL` far-node forms already work.

---

### NOT EXISTS Subqueries
----
RID: `req-grid-gryphon-not-exists`

Status: `Implemented`

Gryphon gains a `NOT EXISTS { ... }` block that expresses correlated anti-join subqueries: "match the outer pattern where there *does not exist* a corresponding inner pattern."

#### Implementation

- Grammar addition: a new clause type `not_exists_clause` produced by:

  ```
  not_exists_clause: _NOT_KW _EXISTS_KW "{" match_clause where_clause? "}"
  _EXISTS_KW: /EXISTS/i
  ```

  and threaded into the top-level `clause` alternation.
- Placement: `NOT EXISTS` is a top-level clause sibling to `MATCH`, `WHERE`, and `RETURN`. A query may contain zero or more `NOT EXISTS` blocks; each is applied as an additional filter against the outer match set.
- Variable scope:
  - Variables declared in the outer query (in the outer `MATCH`) are in scope inside the `NOT EXISTS` block and may be used in its MATCH and WHERE.
  - Variables declared inside a `NOT EXISTS` block are scoped to that block and are not visible outside it or in sibling blocks.
  - This matches Cypher's `CALL { ... }` / `WHERE NOT EXISTS { ... }` subquery scope semantics.
- Semantic: the outer pattern row is included in the result iff the subquery pattern has zero matches under that row's variable bindings.
- `EXISTS { ... }` (without `NOT`) is not in scope. The executor rejects bare `EXISTS` with an unsupported-feature error. Most positive-existence cases can be expressed by adding another `MATCH` hop.
- Nesting: `NOT EXISTS` blocks themselves do not contain further `NOT EXISTS` blocks in v1. A clear parse-time error is surfaced if encountered.
- Compilation: the ORM compiler translates `NOT EXISTS { MATCH (x)-[:E]->(shared) WHERE ... }` into a Django `~Exists(Subquery(...))` clause composed against the outer queryset, with the correlation carried through the shared variable.

#### Development

The motivating query for this requirement — "findings not covered by an active exception" — is the cleanest test case. Implementation tests should exercise at least three cases: (1) the motivating correlated anti-join, (2) a `NOT EXISTS` where the correlated variable is mapped through a multi-hop outer pattern, (3) a `NOT EXISTS` where the inner pattern itself is multi-hop. Uncorrelated inner patterns (no shared variable with the outer) are valid but less useful; keep them on the happy path but do not optimize for them.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-gryphon-not-exists-1 | Grammar Support | Implemented | The parser accepts `NOT EXISTS { MATCH ... WHERE ... }` as a top-level clause. | |
| req-grid-gryphon-not-exists-2 | Variable Correlation | Implemented | Variables declared in the outer MATCH are in scope inside a `NOT EXISTS` block. | |
| req-grid-gryphon-not-exists-3 | Anti-Join Semantics | Implemented | Outer rows are excluded if the inner pattern has any match under their bindings. | |
| req-grid-gryphon-not-exists-4 | Bare EXISTS Rejected | Implemented | `EXISTS { ... }` without `NOT` is rejected at the executor with an unsupported-feature error. | Deferred to a future iteration |
| req-grid-gryphon-not-exists-5 | No Nested Anti-Joins | Implemented | `NOT EXISTS` blocks that themselves contain `NOT EXISTS` are rejected at parse with a clear error. | |
| req-grid-gryphon-not-exists-6 | Multiple Sibling Blocks | Implemented | A query may contain multiple sibling `NOT EXISTS` blocks; each is applied as an additional anti-join filter. | |

#### Future

- Positive `EXISTS { ... }` when a concrete use case justifies it over adding a hop to the outer MATCH.
- Nested `NOT EXISTS` for higher-order exclusions.
- `OPTIONAL MATCH` as a related but distinct construct (left-outer-join semantics).

---

### COUNT Aggregation and Implicit GROUP BY
----
RID: `req-grid-gryphon-count`

Status: `Implemented`

Gryphon gains a single aggregate function, `COUNT`, usable in `RETURN` projections. Non-aggregated RETURN items implicitly form the GROUP BY key set.

#### Implementation

- Grammar addition: `RETURN` items may be aggregate function calls in addition to field paths.

  ```
  return_item: aggregate_call _AS_KW NAME
             | field_path (_AS_KW NAME)?
  aggregate_call: _COUNT_KW "(" (NAME | field_path) ")"
  _COUNT_KW: /COUNT/i
  ```

  - `COUNT(var)` counts non-null occurrences of the variable across the match set.
  - `COUNT(field_path)` counts non-null occurrences of the projected field.
  - `COUNT(*)` is **not** in scope; every count expression names its counted variable or field. The executor rejects `COUNT(*)` with a clear error.
- `AS alias` is **required** on every aggregate RETURN item. The alias becomes the column key in the `rows` envelope field (see `req-grid-gryphon-rows`). Aliases on non-aggregate RETURN items remain optional; when omitted, the field path expression itself is the column key.
- `COUNT(DISTINCT var)` is not in scope. Callers who need distinct-count semantics should structure the outer pattern such that duplicates cannot occur. Defer to a future iteration when a concrete use case appears.
- Implicit GROUP BY: when at least one aggregate is present in RETURN, every non-aggregate RETURN item becomes a GROUP BY key. When all RETURN items are aggregates, the query produces a single-row result.
- Semantic example — motivating query:

  ```
  MATCH (e)-[:HAS_FINDING]->(f)
  WHERE f.status = "open"
  NOT EXISTS {
    MATCH (x)-[:COVERS_FINDING]->(f)
    WHERE x.status = "active"
  }
  RETURN e.entity_id AS entity_id, COUNT(f) AS count
  ```

  produces rows of the shape `{entity_id: "...", count: <int>}`, grouped by `e.entity_id`.
- Compilation: the ORM compiler emits `.values(*group_keys).annotate(**aggregates)` against the joined queryset. Each aggregate becomes a `Count(...)` annotation keyed by the RETURN alias.
- Counts are always integers. `NULL` / missing values are excluded from counts per SQL standard semantics.

#### Development

The scope of this requirement is deliberately narrow. Numeric aggregates (`SUM`, `AVG`, `MIN`, `MAX`) and `DISTINCT` are all straightforward grammar and compiler additions on top of this foundation — but adding them now introduces surface area we don't have real queries for. Wait for the first concrete use case, then pull the lever. The ACID set below includes "only COUNT is supported" as an explicit acceptance criterion so drift is caught at review time.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-gryphon-count-1 | COUNT In RETURN | Implemented | `COUNT(var)` and `COUNT(field_path)` are accepted in RETURN projections. | |
| req-grid-gryphon-count-2 | AS Alias Required For Aggregates | Implemented | Every aggregate RETURN item must carry an `AS alias`; parse fails otherwise. | |
| req-grid-gryphon-count-3 | Implicit GROUP BY | Implemented | Non-aggregate RETURN items become GROUP BY keys when any aggregate is present. | |
| req-grid-gryphon-count-4 | All-Aggregate Returns Single Row | Implemented | Queries whose RETURN contains only aggregates produce exactly one result row. | |
| req-grid-gryphon-count-5 | COUNT Is The Only Aggregate | Implemented | `SUM`, `AVG`, `MIN`, `MAX`, `COUNT(*)`, and `COUNT(DISTINCT ...)` are rejected with an unsupported-feature error. | Each has a future-iteration upgrade path |
| req-grid-gryphon-count-6 | Integer Result | Implemented | Count results are integers in the rows envelope. | |

#### Future

- Numeric aggregates: `SUM`, `AVG`, `MIN`, `MAX`.
- `COUNT(DISTINCT var)` and `COUNT(*)`.
- Post-aggregation `HAVING` clauses for filtering grouped results.
- `ORDER BY` over aggregated columns.

---

### Rows Result Envelope
----
RID: `req-grid-gryphon-rows`

Status: `Implemented`

The canonical search result envelope gains a `rows` field. Aggregating queries populate `rows` as their primary output.

#### Implementation

- Envelope shape becomes:

  ```json
  {
    "nodes": [...],
    "edges": [...],
    "rows": [
      {"entity_id": "019...", "count": 5},
      ...
    ],
    "info": [...],
    "warnings": [...]
  }
  ```

- `rows` is a JSON array. Each element is an object keyed by RETURN alias (or field-path expression where no alias is given for non-aggregate items). Values are primitives (strings, integers, numbers, booleans, nulls). Nested objects are not emitted in v1; queries that project a whole entity (`RETURN e`) continue to populate `nodes` for that variable rather than embedding the full entity into a row.
- Population rule:
  - **Aggregating queries** (any `COUNT(...)` in RETURN) populate `rows`. One row per GROUP BY key combination. `nodes` and `edges` remain populated only with distinct entities referenced by non-aggregate whole-entity RETURN items (e.g. `RETURN e, COUNT(f)` populates `nodes` with the distinct `e` entities and `rows` with `{e: <entity_id>, count: <n>}` per group).
  - **Non-aggregating queries** may also populate `rows`, but are not required to in v1 to preserve strict backward compatibility. If a future iteration decides non-aggregating queries should always populate `rows`, that change lands as a separate requirement after consumers have confirmed they can tolerate the additional field.
- The `rows` field is always present in the envelope even when empty (`[]`), so consumers can rely on its shape without null-checking.
- When `nodes` and `rows` both reference the same entity (e.g., `RETURN e, COUNT(f)`), the canonical form is: the row contains the entity's `entity_id` (not a nested entity object), and the full entity record lives in `nodes`. Consumers join by `entity_id`.

#### Development

The decision to *not* populate `rows` for non-aggregating queries in v1 is intentional backward-compatibility insurance. Existing consumers have been written against `{nodes, edges}` and have never seen `rows`. Adding a new optional field is safe; making a field appear on outputs it didn't appear on before invites surprises. Once the aggregating path is in use and stable, revisit the universal-population rule as a separate, opt-in change.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-gryphon-rows-1 | Envelope Key Added | Implemented | The result envelope contains a `rows` field alongside `nodes`, `edges`, `info`, `warnings`. | |
| req-grid-gryphon-rows-2 | Always Present | Implemented | `rows` is always present in the envelope, even when the value is `[]`. | |
| req-grid-gryphon-rows-3 | Aggregating Queries Populate `rows` | Implemented | Queries with any aggregate in RETURN populate `rows` with one object per GROUP BY key. | |
| req-grid-gryphon-rows-4 | Entity Reference By ID | Implemented | Whole-entity RETURN items referenced in aggregate queries appear in `rows` as `entity_id` values, with full entity records in `nodes`. | |
| req-grid-gryphon-rows-5 | Primitive Row Values | Implemented | Row object values are primitives only — no nested objects, no arrays — in v1. | |
| req-grid-gryphon-rows-6 | Non-Aggregating Queries Unchanged | Implemented | Non-aggregating queries preserve existing envelope behavior (empty `rows`, populated `nodes`/`edges`). | See `req-grid-gryphon-compat` |

#### Future

- Universal `rows` population for non-aggregating queries (behind an opt-in flag, eventually default).
- Nested object row values (e.g. full entity embedded) once a consumer needs it and we've decided how to reconcile with `nodes`.
- Pagination hints on aggregating queries that produce large result sets.

---

### Multi-Hop Graph Envelope
----
RID: `req-grid-gryphon-multihop-envelope`

Status: `Implemented`

Multi-hop queries support graph envelope returns in addition to row projection, enabling multi-hop queries to feed graph visualizations directly.

#### Implementation

- The executor detects graph envelope mode based on the RETURN clause shape:
  - **No RETURN clause** (omitted): all bound node and edge variables are collected and returned as a graph envelope.
  - **Bare-variable RETURN** (all items are variable names with no field steps or aggregates, e.g. `RETURN c, l`): only the named variables are collected as graph objects. Edges connecting the chain are included automatically.
  - **Field projections or aggregates in RETURN**: existing row projection path (unchanged).
- Collection uses `.values_list()` on the chained Edge queryset to extract entity_id columns for each requested variable, then bulk-fetches `Entity` and `Edge` objects and serializes them through the existing GRIFT layer serializers.
- The `layer` parameter (lite, full, extended) is respected, matching the behavior of the standard executor's graph envelope mode.
- Deduplication is inherent: entity_id sets are collected before bulk-fetch.
- The `rows` field is always present in the envelope (empty `[]` for graph envelope returns).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-gryphon-multihop-envelope-1 | No RETURN Graph Envelope | Implemented | Omitting RETURN on a multi-hop query returns all matched nodes and edges. | |
| req-grid-gryphon-multihop-envelope-2 | Bare Variable RETURN | Implemented | `RETURN c, l` returns only the named node variables plus connecting edges. | |
| req-grid-gryphon-multihop-envelope-3 | WHERE Anchor Scoping | Implemented | WHERE predicates scope the graph envelope to matching subgraph, including a predicate on a node BEYOND the root edge (which must constrain the structural far node, not any out-neighbor). | Far-node WHERE folds into the chain's single `.filter()` — see Implementation; regression `gridkin:far_node_where-far-node-where-constrains-the-structural-chain-node-not-any-out-neighbor`. |
| req-grid-gryphon-multihop-envelope-4 | Deduplication | Implemented | Entities appearing at multiple chain positions are returned exactly once. | |

---

### ORDER BY Row Ordering
----
RID: `req-grid-gryphon-order-by`

Status: `Implemented`

Gryphon gains an `ORDER BY` clause that imposes a defined order on row-projection results, including ordering by an aggregated column.

#### Implementation

- Grammar addition: a top-level `order_by_clause`, sibling to `MATCH`, `WHERE`, `RETURN`:

  ```
  order_by_clause: _ORDER_KW _BY_KW order_item ("," order_item)*
  order_item: NAME order_dir?
  order_dir: _ASC_KW -> asc | _DESC_KW -> desc
  ```

- An `order_item` names a **RETURN output by key** — its explicit `AS` alias, or, for an unaliased field projection, its last dot-step name. `ORDER BY` does not introduce new column expressions; it can only reorder what `RETURN` already projects. An `ORDER BY` term that names no RETURN output is a clear execution error. This mirrors Cypher's post-`RETURN` ordering scope and keeps the compiler from having to resolve a second, parallel field-path surface.
- Direction is `ASC` (ascending) by default; `DESC` is explicit per term. Keywords are case-insensitive.
- Multiple `order_item`s order left-to-right: the first is primary, each subsequent one breaks ties of the prior.
- **Deterministic tiebreak.** After the user's terms, the executor appends the query's group-by / identity columns (the GROUP BY keys for aggregating queries; the per-model `entity_id` for type-scan projections) as ascending tiebreakers. Output row order — and therefore the captured SQL and any `LIMIT` result — is fully determined even when the named keys have ties. "Stable ordering with ties" is a guarantee, not an accident.
- ORDER BY compiles to SQL `ORDER BY` via Django `.order_by(...)`: for the aggregation path, by annotation alias; for the type-scan projection path, by the ORM lookup of the projecting RETURN item. NULL ordering is therefore PostgreSQL's (`NULLS LAST` for ascending).
- `ORDER BY` applies to **row-projection** queries; the one envelope-mode carve-out is a labelled type-scan whose envelope `RETURN` accepts `ORDER BY <var>.<field-path>` (see `req-grid-gryphon-order-by-envelope`). All other envelope shapes (hub-and-spoke, edge-type scan, multi-hop envelope, bare `MATCH (n)`, multi-clause unions, queries carrying `NOT EXISTS` or `OPTIONAL MATCH`) continue to reject `ORDER BY` — those have no canonical row order.

#### Development

`ORDER BY` is deliberately scoped to reorder existing RETURN outputs rather than accept arbitrary field paths. The narrower surface means the compiler reuses the alias→column map it already builds for projection, the determinism tiebreak falls out of columns the query already groups on, and there is no second path-resolution code path to keep correct. Ordering by a richer expression than a RETURN output waits for a real query that needs it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-gryphon-order-by-1 | ORDER BY Clause Accepted | Implemented | The parser accepts `ORDER BY` as a top-level clause with one or more terms. | |
| req-grid-gryphon-order-by-2 | Terms Name RETURN Outputs | Implemented | An `ORDER BY` term names a RETURN output by alias or default key; an unknown name is a clear execution error. | |
| req-grid-gryphon-order-by-3 | Ascending Default Descending Explicit | Implemented | Terms sort ascending unless `DESC` is given; `ASC`/`DESC` are case-insensitive. | |
| req-grid-gryphon-order-by-4 | Multi-Key Ordering | Implemented | Multiple terms order left-to-right, each breaking ties of the prior. | |
| req-grid-gryphon-order-by-5 | Deterministic Tiebreak | Implemented | The executor appends group-by / identity columns as tiebreakers so row order is fully deterministic across runs. | |
| req-grid-gryphon-order-by-6 | Orders Aggregated Columns | Implemented | An `ORDER BY` term may name an aggregate RETURN alias (e.g. a `COUNT` result). | The "top-N" dashboard verb |
| req-grid-gryphon-order-by-7 | Row-Projection Or Type-Scan Envelope | Implemented | `ORDER BY` paired with a graph-envelope RETURN is rejected unless the query is a single labelled type-scan, per `req-grid-gryphon-order-by-envelope`. Hub-and-spoke, edge-type-scan, multi-hop, bare `MATCH (n)`, multi-clause union envelopes, and queries carrying `NOT EXISTS` or `OPTIONAL MATCH` are still rejected. | |

#### Future

- `ORDER BY` over an expression that is not a RETURN output (projection mode).
- Graph-envelope ordering for non-type-scan dispatches — hub-and-spoke, edge-type scan, multi-hop, bare `MATCH (n)`, multi-clause unions. Each needs its own "what does row order mean here" answer before it can be supported.
- `NULLS FIRST` / `NULLS LAST` control per term.

---

### LIMIT Row Capping
----
RID: `req-grid-gryphon-limit`

Status: `Implemented`

Gryphon gains a `LIMIT n` clause that caps the number of rows a row-projection query returns.

#### Implementation

- Grammar addition: a top-level `limit_clause`:

  ```
  limit_clause: _LIMIT_KW INT
  ```

  `INT` is `/[0-9]+/`, so `n` is a non-negative integer literal; `LIMIT 0` is legal and `LIMIT` cannot be negative.
- `LIMIT` compiles to SQL `LIMIT` via Django queryset slicing (`qs[:n]`) — the database short-circuits rather than the executor materializing every row and slicing in Python.
- `LIMIT` composes with `ORDER BY`: ordering is applied first, then the cap. The combination is the "top-N" query shape.
- `LIMIT` **without** `ORDER BY` is legal. Because the executor always appends deterministic tiebreak columns (per `req-grid-gryphon-order-by-5`), the rows that survive the cap are still deterministic — they are the first `n` in the executor's default order (group-by / entity-name order), not an arbitrary subset.
- `LIMIT n` with `n` larger than the result set returns the whole result set, unchanged.
- Like `ORDER BY`, `LIMIT` applies to row-projection queries; the one envelope-mode carve-out is a labelled type-scan (see `req-grid-gryphon-order-by-envelope`). All other envelope shapes continue to reject `LIMIT`.
- At most one `ORDER BY` and one `LIMIT` clause per query; a duplicate is a parse error (not a silent drop).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-gryphon-limit-1 | LIMIT Clause Accepted | Implemented | The parser accepts `LIMIT n` as a top-level clause with a non-negative integer. | |
| req-grid-gryphon-limit-2 | Caps Row Count | Implemented | A query returns at most `n` rows; `LIMIT` compiles to SQL `LIMIT`. | |
| req-grid-gryphon-limit-3 | LIMIT Zero Is Empty | Implemented | `LIMIT 0` returns no rows. | |
| req-grid-gryphon-limit-4 | Oversize LIMIT Returns All | Implemented | `LIMIT n` with `n` past the result-set size returns every row. | |
| req-grid-gryphon-limit-5 | LIMIT Without ORDER BY Deterministic | Implemented | `LIMIT` with no `ORDER BY` caps in the executor's deterministic default order, not an arbitrary subset. | |
| req-grid-gryphon-limit-6 | Row-Projection Or Type-Scan Envelope | Implemented | `LIMIT` paired with a graph-envelope RETURN is rejected unless the query is a single labelled type-scan, per `req-grid-gryphon-order-by-envelope`. Hub-and-spoke, edge-type-scan, multi-hop, bare `MATCH (n)`, multi-clause union envelopes, and queries carrying `NOT EXISTS` or `OPTIONAL MATCH` are still rejected. | |

#### Future

- `SKIP` / `OFFSET` for query-level pagination (Gryphon wishlist A3).
- Graph-envelope `LIMIT` for non-type-scan dispatches (covered alongside the corresponding envelope-ordering Future bullet in `req-grid-gryphon-order-by`).

---

### OPTIONAL MATCH Left-Outer Join
----
RID: `req-grid-gryphon-optional-match`

Status: `Implemented`

Gryphon gains an `OPTIONAL MATCH` clause: a second pattern that, where it does not match, leaves its variables unbound rather than dropping the mandatory row. It is the left-outer-join primitive — the missing piece for every per-entity scoreboard.

#### Background And Motivation

The load-bearing query for a compliance dashboard is "show me every X and how many related Y it has." Written with a plain `MATCH`:

```text
MATCH (l:aws_lambda)-[:HAS_FINDING]->(f:finding)
RETURN l.entity_id AS lambda, COUNT(f) AS findings
```

this **silently drops every Lambda with zero findings** — an inner join. The clean Lambdas vanish from the scoreboard, which is the exact opposite of what a scoreboard should show. `OPTIONAL MATCH` fixes this: every Lambda appears, and `COUNT(f)` is `0` where there is no finding (`COUNT` ignores unbound/NULL — the one place SQL's null handling is exactly what we want).

#### Implementation

- Grammar: a top-level `optional_match_clause` — `OPTIONAL MATCH` followed by a pattern — sibling to `MATCH`.
- AST: `OptionalMatchClause`; `GryphonAST` gains `optional_match_clauses`.
- The executor routes any query carrying an `OPTIONAL MATCH` to a dedicated path (`_execute_optional_match`).

**v0 shape.** The implemented surface is the per-entity-scoreboard shape, scoped tight:

- Exactly one mandatory `MATCH` — a single node-only **type scan** with a label, binding the mandatory variable `v` (e.g. `MATCH (t:pg_node)`).
- Exactly one `OPTIONAL MATCH` — a **single-hop, directed** pattern that starts from `v` (`OPTIONAL MATCH (v)-[e:E]->(w)` or `(v)<-[e:E]-(w)`).
- A **row-projection** `RETURN` that projects `v`'s fields and `COUNT`s the optional variable (`w` or the optional edge `e`).

**Compilation.** The mandatory `MATCH` is the type-scan queryset. The optional hop compiles to a Django `Count(<edge>, filter=Q(...))` over a `LEFT OUTER JOIN` to the edge table. Because the join is a left join and the optional pattern's constraints live in the `COUNT(...) FILTER (WHERE ...)` clause, a mandatory row with no qualifying optional edge still appears, with a count of `0`. Counting the optional node `w` and counting the optional edge `e` are equivalent over a single hop (one edge is one binding).

**WHERE placement — the filter-placement gotcha.** A single global `WHERE` is split by variable:

- A predicate on the mandatory variable `v` filters the **outer scan** (it is a real row filter — `MATCH (t) ... WHERE t.kind = "target"` returns only `target` rows).
- A predicate on an optional variable (`w` or `e`) is folded into the **optional join's `filter=Q`**. It constrains which optional edges match — it does **not** drop mandatory rows. `OPTIONAL MATCH (t)<-[:E]-(g) WHERE g.severity > 100` still returns every `t`; the ones whose `g` fails the predicate simply count `0`. This is the well-known Cypher gotcha (a `WHERE` "inside" an `OPTIONAL MATCH` behaves differently from one after it); pinning it correctly is a v0 requirement.

`OR` / `NOT` in the `WHERE`, and predicates referencing a variable bound by neither clause, are rejected — consistent with the AND-only scope of the rest of the executor.

**Out of v0 scope** (each rejected with a clear error, each a named future item): a multi-hop optional pattern; more than one `OPTIONAL MATCH`; an optional pattern not anchored on `v`; a graph-envelope (non-row) `RETURN`; projecting an optional variable's fields (it can only be `COUNT`ed); combining `OPTIONAL MATCH` with `NOT EXISTS`.

#### Development

The v0 scope is the per-entity-scoreboard shape and nothing wider, because that shape alone unblocks the KSI scoreboard and every Rampart-step compliance dashboard. The two genuinely hard generalizations — a multi-hop optional pattern, and projecting (not just counting) the optional variable's rows — both need row-per-edge materialization of the left join, which the `Count(filter=Q)` compilation deliberately sidesteps. They wait for a query that needs them. The filter-placement gotcha, by contrast, is *not* deferred: getting it wrong is a silent-wrong-answer bug, so it is pinned by a Gridkin scenario in v0.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-gryphon-optional-match-1 | OPTIONAL MATCH Accepted | Implemented | The parser accepts `OPTIONAL MATCH` as a top-level clause; the executor routes it to the left-outer-join path. | |
| req-grid-gryphon-optional-match-2 | Zero-Match Keeps The Row | Implemented | A mandatory row with no qualifying optional match is still returned, rather than dropped as a plain `MATCH` would. | The headline behavior |
| req-grid-gryphon-optional-match-3 | COUNT Of Optional Is Zero | Implemented | `COUNT` of the optional variable (node or edge) is `0` for a mandatory row with no match, not NULL or absent. | |
| req-grid-gryphon-optional-match-4 | WHERE On Optional Var Constrains The Join | Implemented | A `WHERE` predicate on an optional variable is folded into the optional join filter; it never drops a mandatory row. | The Cypher filter-placement gotcha |
| req-grid-gryphon-optional-match-5 | WHERE On Mandatory Var Filters Outer Scan | Implemented | A `WHERE` predicate on the mandatory variable filters the outer type scan as a real row filter. | |
| req-grid-gryphon-optional-match-6 | Directed Optional Edge | Implemented | The optional hop may be outbound (`->`) or inbound (`<-`); both compile correctly. | Undirected is rejected |
| req-grid-gryphon-optional-match-7 | Composes With ORDER BY / LIMIT | Implemented | An `OPTIONAL MATCH` scoreboard accepts `ORDER BY` (including by the `COUNT` alias) and `LIMIT`. | The "top-N scoreboard" verb |
| req-grid-gryphon-optional-match-8 | v0 Scope Bounds Enforced | Implemented | Multi-hop optional patterns, multiple `OPTIONAL MATCH` clauses, an unanchored optional pattern, graph-envelope returns, and optional-variable field projection are each rejected with a clear error. | Each is a named future item |

#### Future

- Multi-hop optional patterns (`OPTIONAL MATCH (v)-[:E1]->(x)-[:E2]->(w)`).
- Projecting the optional variable's rows, not only `COUNT`ing them (`RETURN v, w` with `w` NULL where unmatched) — needs row-per-edge left-join materialization.
- More than one `OPTIONAL MATCH` clause; chained optionals where a later one depends on an earlier.
- Graph-envelope `OPTIONAL MATCH` (`{nodes, edges}` of the mandatory scan plus the matched optional subgraph).
- Positive `EXISTS { ... }` — the presence-test cousin (Gryphon wishlist D2).

---

### ORDER BY / LIMIT On A Type-Scan Graph Envelope
----
RID: `req-grid-gryphon-order-by-envelope`

Status: `Implemented`

A labelled type-scan (`MATCH (n:type)`) returning a graph envelope (`RETURN` omitted, or `RETURN n`) accepts `ORDER BY <var>.<field-path>` and `LIMIT n`. The one-node "latest emission of kind X" lookup the panel layer hits today becomes a single Gryphon query — `ORDER BY n.data.fetched_at DESC LIMIT 1` returns a one-node envelope — rather than a Python helper that fetches every matching node and sorts in memory.

#### Implementation

- **Grammar.** `order_item` is extended from `NAME order_dir?` to `field_path order_dir?`. A bare name still parses (a `field_path` with no steps is the original surface) so existing row-projection ORDER BY queries continue to work unchanged.
- **AST.** `OrderByItem.key: str` is replaced by `OrderByItem.path: FieldPath`. A `.key` derived property reproduces the previous surface for projection-mode callers — `path.variable` when steps are empty, the last dot-step name otherwise — so existing executor branches that look up RETURN aliases continue to work.
- **Executor.** Lowers to rung 1 (ORM `QuerySet` composition) — the same machinery already used by row-projection `ORDER BY`/`LIMIT`. The envelope branch in `_execute_type_scan` calls a new envelope-mode helper that resolves each `OrderByItem.path` through the existing `_typescan_orm_path` (so spine fields, the `data` lane, and `dimensions.<key>` all reach the right ORM column) and appends `entity_id` as the deterministic tiebreaker before applying any `LIMIT`. `LIMIT` compiles via Django queryset slicing (`qs[:n]`), so the DB short-circuits.
- **Dispatch guard.** `execute_gryphon_raw`'s top-level rejection of `ORDER BY` / `LIMIT` on graph-envelope returns is narrowed: a single-clause, single-pattern, labelled type-scan with envelope `RETURN`, no `NOT EXISTS`, and no `OPTIONAL MATCH` is now allowed. Every other envelope shape (hub-and-spoke, edge-type scan, multi-hop chain, bare `MATCH (n)`, multi-clause unions, queries carrying `NOT EXISTS` or `OPTIONAL MATCH`) keeps the existing rejection — each has a different "what does row order mean here" answer.
- **Ordering semantics.** Same as the row-projection path: ascending by default, `DESC` explicit; PostgreSQL's `NULLS LAST` for ascending, `NULLS FIRST` for descending. A data-lane field that is `NULL` on some rows is ordered per that default (no `NULLS FIRST`/`NULLS LAST` control yet — tracked under `req-grid-gryphon-order-by` Future). The `entity_id` tiebreaker is always appended in ascending order so the surviving rows under `LIMIT` and the captured SQL are deterministic across runs.
- **Form constraint.** Envelope-mode `ORDER BY` must name a field path (e.g. `ORDER BY n.data.fetched_at DESC`). A bare name (`ORDER BY observed_at`) is ambiguous in envelope mode — there are no RETURN aliases — and is rejected with a clear executor error directing the author to the field-path form. In projection mode, the bare-name surface continues to mean "the RETURN alias" exactly as before.

#### Development

The v0 scope is deliberately one dispatch path (the type-scan) because that path has an unambiguous answer to "what column is the row ordering on" — the typed model's row. The other envelope dispatches each carry an open design question (hub-and-spoke: do you order the hub, the neighbors, or the edges? edge-type scan: which endpoint's column? multi-hop: which hop?), and the demand signal calls for the type-scan shape only — three samsite panels (`vdr_ingestion_health`, `ksi_scoreboard`'s two OSCAL artifact lookups, `oscal_workbench` + `oscal_poam_workbench`) all need "latest artifact of kind X" or "artifact by pinned entity_id else latest of kind X." Today they ride on a Python helper in `plugins/roscale/panels/_common.py` (`_lookup_latest_by_kind`) that fetches every matching node and sorts in Python — exactly the demand-extension pattern that `req-grid-gryphon-order-by` and `req-grid-gryphon-limit` were landed under (sibling A1 / A2 in the wishlist), now needed for graph-envelope returns instead of row projections. The other-envelope dispatches stay rejected with a clear error so the v0 boundary is legible — each is a named Future bullet.

The grammar change to accept a `field_path` in an `order_item` is the smallest possible parser surface change: a bare `NAME` (the original surface) is already a degenerate `field_path` with zero steps, so the existing row-projection ORDER BY tests are unchanged. The executor splits on `len(path.steps)`: zero steps stays the projection-mode "name a RETURN alias" lookup; one-or-more steps takes the envelope-mode resolution through `_typescan_orm_path`. Projection-mode queries that try the new field-path form get a clear error pointing at envelope mode — that broader surface waits for a real query.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-gryphon-order-by-envelope-1 | Envelope ORDER BY Field Path Accepted | Implemented | `MATCH (n:type) RETURN n ORDER BY n.data.<field>` parses and executes, ordering the returned node envelope by the data-lane field. | RETURN omitted is equivalent to bare-variable RETURN here. |
| req-grid-gryphon-order-by-envelope-2 | Envelope LIMIT Caps Node Count | Implemented | `LIMIT n` on a type-scan envelope returns at most `n` nodes; `LIMIT 0` is empty, oversize `LIMIT` returns every node. | Compiles to SQL `LIMIT`. |
| req-grid-gryphon-order-by-envelope-3 | Spine And Data-Lane Field Paths | Implemented | An envelope `ORDER BY` may name a spine field (`n.name`, `n.created_at`) or a data-lane field (`n.data.<x>`). | Reuses `_typescan_orm_path`. |
| req-grid-gryphon-order-by-envelope-4 | Deterministic Tiebreak | Implemented | `entity_id` is appended ascending as the tiebreaker so rows under `LIMIT` and the captured SQL are deterministic. | Same discipline as the projection path. |
| req-grid-gryphon-order-by-envelope-5 | NULL Rows Ordered Per Postgres Default | Implemented | A row whose data-lane field is `NULL` sorts after non-null rows under ascending order, before them under descending. | Postgres native `NULLS LAST` (ASC) / `NULLS FIRST` (DESC); per-term control is future work. |
| req-grid-gryphon-order-by-envelope-6 | WHERE Composes Before ORDER BY | Implemented | A type-scan WHERE filters first; ORDER BY and LIMIT apply to the filtered envelope. | Reuses `_apply_typescan_predicate`. |
| req-grid-gryphon-order-by-envelope-7 | RETURN Omitted Equivalent To RETURN var | Implemented | Both `MATCH (n:type) ORDER BY n.name LIMIT 1` and `MATCH (n:type) RETURN n ORDER BY n.name LIMIT 1` produce the same one-node envelope. | Both are graph-envelope per `_is_graph_envelope_return`. |
| req-grid-gryphon-order-by-envelope-8 | Bare-Name ORDER BY Rejected In Envelope Mode | Implemented | `MATCH (n:type) ORDER BY name` is rejected with a clear executor error pointing at the field-path form. | Bare names are ambiguous in envelope mode. |
| req-grid-gryphon-order-by-envelope-9 | Other Envelope Dispatches Still Rejected | Implemented | Hub-and-spoke, edge-type scan, multi-hop envelope, bare `MATCH (n)`, multi-clause union envelopes, and queries carrying `NOT EXISTS` or `OPTIONAL MATCH` keep their `ORDER BY` / `LIMIT` rejection. | Each is a named Future bullet. |

#### Future

- Envelope `ORDER BY` / `LIMIT` for the other dispatches (hub-and-spoke, edge-type scan, multi-hop, bare `MATCH (n)`, multi-clause unions). Each needs its own "what does row order mean here" answer.
- Field-path ORDER BY in projection mode (`RETURN n.entity_id AS id ORDER BY n.data.kind`). Today projection mode requires a RETURN-output alias; the field-path form is envelope-only in v0.
- `NULLS FIRST` / `NULLS LAST` per-term control (shared Future bullet with `req-grid-gryphon-order-by`).

---

### RETURN DISTINCT Row Deduplication
----
RID: `req-grid-gryphon-distinct`

Status: `Proposed`

Gryphon gains a `DISTINCT` modifier on a **row-projection** `RETURN`: `RETURN DISTINCT <field projections>` collapses duplicate projected rows so each distinct combination of projected values appears exactly once. It is the "distinct list of values" verb — the shape a dashboard needs to populate a filter dropdown (distinct `entity_type`s, distinct tag values, distinct owners) without post-processing the envelope in Python.

#### Implementation

- Grammar addition: an optional `DISTINCT` keyword between `RETURN` and the first return item:

  ```
  return_clause: _RETURN_KW _DISTINCT_KW? return_item ("," return_item)*
  _DISTINCT_KW: /DISTINCT/i
  ```

  `_DISTINCT_KW` is underscore-prefixed so lark discards it from the tree; the parser records its presence as a boolean `distinct` flag on the `ReturnClause` AST node (default `False`, so every existing construction site is unaffected). Because the keyword is a single optional token, a duplicate (`RETURN DISTINCT DISTINCT ...`) is a parse error, not a silent drop (`GRY-LANG-4`).
- Distinctness is over the **full projected tuple** — the ordered set of all `RETURN` output columns — not per-column. `RETURN DISTINCT n.a, n.b` collapses two rows only when both `a` and `b` match.
- **One uniform lowering: rung 1 SQL `SELECT DISTINCT`, applied once in the shared row backend** (`GRY-ARCH-2`). Since the row-materialization refactor (`req-grid-traversal-exec-row-materialization`), every row-projection shape — type-scan, edge-chain (single- and multi-hop), and OPTIONAL MATCH — resolves its projection through the shared `_typescan_orm_path`/`_resolve_orm_path` resolver into `.values(<projected columns>)` and feeds **one** `materialize_rows(MaterializationPlan)` backend. DISTINCT is therefore **one** change, not a per-path one: each Layer-A shape builder sets `plan.distinct = True` when the `RETURN` carries the keyword, and `materialize_rows` applies it exactly once as `.values(...).distinct()` — a genuine `SELECT DISTINCT` over the projected columns. There is **no** per-path mechanism split, **no** Python-side dedup, and no per-tail `distinct` branch; the former Python `_project_node` walk and the separate per-shape row tails no longer exist (`GRY-ARCH-4` — this feature was the motivating case for that single-backend property).
  - Because `materialize_rows` **always** `.values()`-projects before applying DISTINCT, the bare-`.distinct()`-dedups-by-primary-key no-op (the silent-wrong-answer class the doctrine forbids, `GRY-ARCH-3`) is structurally unreachable — the `.values()` is what makes `SELECT DISTINCT` operate on the *projected* columns.
- **The aggregate-bearing plans reject DISTINCT, never ignore it — and that rejection already lives in the backend.** `materialize_rows` raises `SearchExecutionError` when `plan.distinct` is set and the plan carries any aggregate descriptor (`req-grid-traversal-exec-row-materialization-14`, already implemented as a dormant guard). OPTIONAL MATCH is no longer a separate row tail: its Layer-A builder produces a plan carrying the zero-preserving `Count(edge_path, filter=opt_q)`, so a `RETURN DISTINCT` over an OPTIONAL MATCH is *by construction* a distinct-over-aggregate plan and rejects at that single backend site — as does the aggregate branch of the edge-chain builder. DISTINCT is consumed by exactly one lowering site — the backend's non-aggregate `.values().distinct()` — or the query rejects; no path accepts-and-ignores it (`GRY-ARCH-3`).
- **DISTINCT is applied before `LIMIT`** — the natural SQL order (`SELECT DISTINCT ... LIMIT n`), so `RETURN DISTINCT ... LIMIT n` returns `n` *distinct* rows, never fewer-than-`n` because duplicates were counted against the cap.
- **Under DISTINCT the inherited default ordering MUST be cleared before `.values().distinct()`.** The type-scan queryset is created with a default `.order_by("entity__name")`, and the normal projection paths append `entity_id` as a tiebreaker (`req-grid-gryphon-order-by-5`). Django folds *every* `ORDER BY` column into the `SELECT DISTINCT` column list — so a leaked `entity__name` / `entity_id` would make two rows with the *same projected value but different entity* appear distinct, silently defeating the dedup (the [Django `distinct()` ordering caveat](https://docs.djangoproject.com/en/stable/ref/models/querysets/#distinct)). The DISTINCT branch of `materialize_rows` therefore **MUST** reset ordering (`.order_by()` with the inherited default cleared) and order **only** by projected columns — one place, since ordering is applied in the single backend from `plan.order_cols`.
- **Determinism under DISTINCT tiebreaks on the projected columns, not `entity_id`** (`GRY-ARCH-9`). Because the hidden `entity_id` tiebreaker is both wrong here and illegal under `SELECT DISTINCT` (PostgreSQL requires every `ORDER BY` term to appear in the `SELECT DISTINCT` list, and `entity_id` is not a projected column), determinism comes from ordering by the **full projected tuple**: any `ORDER BY` terms first, then the remaining projected columns in projection order. A DISTINCT result's rows are already unique tuples, so this is fully deterministic and Postgres-legal.
- **NULL rows dedup as equal.** Two projected rows that are both `NULL` in a column collapse to one, matching SQL `SELECT DISTINCT` (which treats `NULL` as not-distinct-from-`NULL`). This is standard set-membership NULL grouping and is distinct from the WHERE-predicate null boundary of `GRY-SEM-2` (which governs comparison truth values, not row identity) — no change to that boundary.
- **JSON blob values: scalar sub-keys are in scope; containers are loudly rejected (v0).** Because DISTINCT reuses the shared field-path resolver, a JSON *scalar* sub-key projection (`RETURN DISTINCT n.data.tags.Project`, where the value is a string / number / bool / null) lowers to `SELECT DISTINCT (data->'tags'->>'Project')` — treated **identically to a column**, which is the intended parity. A JSON *container* sub-value (an object or array) is **out of v0 scope**: row values are primitives-only by `req-grid-gryphon-rows-5`, there is no map/array literal to express container semantics, and jsonb-container equality (normalized, key-order-independent) is not a specified Gryphon semantics. To keep `.values().distinct()` from *silently* widening the row contract by jsonb-deduping containers, a DISTINCT projection whose field the **declared schema types as `object`/`array`** is rejected with `SearchExecutionError` — in **both** non-aggregate row paths — reusing the type-strictness schema machinery (`GRY-SEM-1`), not accepted-and-deduped. The residual case is an **opaque JSON blob** (a field declared bare `{"type": "object"}` with no sub-key schema): its container-ness cannot be known statically, so DISTINCT over such a sub-key is a **named open risk** (the same coercion-tolerant boundary `GRY-SEM-1` already names), not a claimed-complete defense. The can/cannot boundary for JSON-blob containers is tracked as a first-class column in `doc-gryphon-feature-demand.md` §2 (the "JSON blob" axis), so it is legible across every call, not just this one.
- **Envelope-mode DISTINCT: exactly one bare-variable return item is honored as a no-op; anything else bare is rejected.** A graph-envelope `RETURN` already deduplicates nodes/edges by `entity_id` (`req-grid-gryphon-multihop-envelope-4`), so `RETURN DISTINCT n` — **exactly one** bare-variable return item — is *satisfied by construction*: DISTINCT is **honored, not silently ignored** (the envelope IS distinct by entity identity), so it is accepted and returns the same envelope as `RETURN n`. **More than one bare item** — whether distinct variables (`RETURN DISTINCT a, b`) or a repeated one (`RETURN DISTINCT n, n`) — has **no faithful envelope semantics** (the envelope has no notion of a distinct row-*tuple* — it returns deduped `a`-nodes ∪ `b`-nodes ∪ edges), so it is **rejected** with an error pointing at field-projection form (`RETURN DISTINCT a.id, b.id`). The no-op is defined on the *item count* (exactly one bare item), not merely "one variable," so the envelope is never allowed to pretend it has row-tuple identity. This keeps DISTINCT meaningful on both output types — real dedup on row projections, identity-dedup on the single-var envelope — and rejects only the genuinely-undefined cases (`GRY-ARCH-3`, `GRY-SEM-4`).
- **`count(DISTINCT x)` is a separate, unrelated feature.** This requirement's grammar addition sits between `RETURN` and the return items; it does not touch `aggregate_call`. `COUNT(DISTINCT ...)` remains rejected under `req-grid-gryphon-count-5` and would land as `Count(distinct=True)` — a different lowering — under its own future requirement (the likely next Gryphon feature).
- **DISTINCT over aggregate returns is deferred — and the rejection fires on every aggregate-bearing path.** A `RETURN DISTINCT` whose projection contains an aggregate item (e.g. `RETURN DISTINCT h.id AS id, COUNT(n) AS c`) is rejected in v0: `DISTINCT` over an implicit-GROUP-BY result set has its own semantics (the group-by columns are already distinct) and no demand signal yet. The rejection **MUST** be enforced in both aggregate-producing sites — the aggregate branch of `_compute_rows` **and** `_execute_optional_match` (where every valid v0 RETURN carries a COUNT, so `RETURN DISTINCT` there is *always* this case) — so no aggregate path silently swallows the flag.

#### Build Sequencing

The row-materialization refactor (`req-grid-traversal-exec-row-materialization`) pre-built DISTINCT's home, so this feature is a small, well-ordered add against an existing backend rather than a new tail:

- **Already in place (the landing pad).** `MaterializationPlan` carries a `distinct: bool` field; `materialize_rows` already applies ordering from `plan.order_cols` and already rejects DISTINCT over an aggregate plan (`req-grid-traversal-exec-row-materialization-14`). Today the flag is **fail-closed** — a non-aggregate `plan.distinct=True` raises "not implemented yet" rather than silently no-op (`GRY-ARCH-3`) — so the surface is prepared without a silent-drop hole.
- **Build the backend *apply* before the grammar.** First replace the fail-closed reject in `materialize_rows` with the real `.values(...).distinct()` application (plus the ordering-clear this requirement mandates above), covered by below-service-layer backend tests (mirroring `TestMaterializeRowsDistinctFailClosed`). *Then* wire the surface: the `_DISTINCT_KW?` grammar token, the `ReturnClause.distinct` AST field, the parser flag, and each Layer-A builder setting `plan.distinct` from it. This ordering guarantees there is never a commit where a parseable `RETURN DISTINCT` reaches an unwired backend — the flag applies-or-rejects at every point (`GRY-ARCH-3`).
- **TCK corners.** Mine `clauses/return` for DISTINCT intents; the folder is already in the coverage ledger (`gryphon_playground.tck-coverage.json`) from the row-materialization RETURN-projection parity scenarios, so extend that entry rather than opening a new folder.

#### Development

The v0 boundary is `RETURN DISTINCT` over field projections (plus the single-var-envelope no-op) and nothing wider, because that is the demand shape: `doc-gryphon-feature-demand.md` §2 ranks `DISTINCT` at **A4** (🟢 Low, 12.2% of surveyed real-world queries, 7/11 repos) with the one-word implementation note `.distinct()`. The rejected shapes are each a genuinely different construct rather than a smaller version of this one — `count(DISTINCT)` is an aggregate-argument modifier with a `Count(distinct=True)` lowering; multi-variable envelope DISTINCT has no faithful `(a, b)`-pair semantics over `{nodes, edges}`; aggregate-return DISTINCT dedups an already-grouped set; JSON-container DISTINCT needs an unspecified jsonb-equality semantics. The single-bare-variable envelope case is *accepted*, not rejected — the envelope's existing `entity_id` dedup genuinely satisfies DISTINCT, so honoring it (rather than rejecting valid Cypher-shaped input) is the apply-not-drop-and-don't-over-reject reading of `GRY-ARCH-3`. Naming each rejection with a clear error (and a `Future` bullet) keeps the boundary legible: a silently-ignored `DISTINCT` would be a silent-wrong-answer bug, a loudly-rejected one is a contract (`GRY-SEM-4`).

DISTINCT is lowered uniformly to SQL `SELECT DISTINCT` in both dispatch paths by reusing the same field-path resolver the `WHERE` clause already uses — deliberately *not* as a Python-side dedup layered over the type-scan's Python projection. The Python dedup would have been a same-answer alternative, but it splits the mechanism (SQL in one path, Python in the other), needs hashable-key handling for edge cases, and diverges from the "operate on JSON blob values with the same machinery as columns" goal; routing the type-scan DISTINCT through `.values(...).distinct()` keeps one mechanism and inherits JSON scalar sub-key support for free. The primary-key no-op trap (a bare `.distinct()` on the un-`.values()`'d model queryset) is recorded at the executor site so a future edit does not reintroduce it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-gryphon-distinct-1 | DISTINCT Keyword Accepted | Proposed | The parser accepts `RETURN DISTINCT <items>` and records a `distinct=True` flag on the return clause; a bare `RETURN <items>` is `distinct=False`. | |
| req-grid-gryphon-distinct-2 | Dedups Projected Rows | Proposed | The result contains each distinct combination of projected values exactly once. | The headline behavior |
| req-grid-gryphon-distinct-3 | Distinctness Over The Full Tuple | Proposed | Two rows collapse only when *every* projected column matches; `RETURN DISTINCT n.a, n.b` is distinct over `(a, b)`, not per-column. | |
| req-grid-gryphon-distinct-4 | Uniform SQL DISTINCT In Both Dispatch Paths | Proposed | DISTINCT lowers to `.values(...).distinct()` (SQL `SELECT DISTINCT`) in both the type-scan and advanced (`_compute_rows`) paths; a single-labelled-node scan and an edge-bearing / multi-hop projection each dedup via the same mechanism. | Apply-in-every-path, one mechanism |
| req-grid-gryphon-distinct-5 | JSON Scalar Sub-Key Distinct | Proposed | `RETURN DISTINCT n.data.<...>` over a JSON *scalar* sub-key dedups on the extracted scalar, treated identically to a spine/column field via the shared field-path resolver. | The JSON-parity behavior |
| req-grid-gryphon-distinct-6 | JSON Container Distinct Rejected | Proposed | DISTINCT over a projection whose declared schema types the field as `object`/`array` raises `SearchExecutionError` in both non-aggregate row paths (not accepted-and-jsonb-deduped); an *opaque* `{"type":"object"}` blob is a named residual risk per `GRY-SEM-1`. Tracked in the feature-demand "JSON blob" column and Future. | Boundary enforced, not silently coerced |
| req-grid-gryphon-distinct-7 | Composes With ORDER BY | Proposed | `RETURN DISTINCT ... ORDER BY <output>` orders the deduplicated rows; ordering tiebreaks on the remaining projected columns, not `entity_id`, so the order is deterministic and Postgres-legal. | |
| req-grid-gryphon-distinct-8 | Inherited Ordering Cleared Under DISTINCT | Proposed | The DISTINCT branch clears the type-scan's default `order_by("entity__name")` and the `entity_id` tiebreaker so no non-projected column leaks into `SELECT DISTINCT`; two entities with the same projected value but different names/ids dedup to one row. | The Django ordering-poisons-DISTINCT trap |
| req-grid-gryphon-distinct-9 | DISTINCT Before LIMIT | Proposed | `RETURN DISTINCT ... LIMIT n` returns `n` distinct rows; dedup is applied before the cap, never after. | |
| req-grid-gryphon-distinct-10 | NULL Rows Dedup As Equal | Proposed | Projected rows that are `NULL` in a column collapse as equal, matching SQL `SELECT DISTINCT`; unrelated to the `GRY-SEM-2` predicate null boundary. | |
| req-grid-gryphon-distinct-11 | Single-Item Bare Envelope DISTINCT Honored As No-Op | Proposed | `RETURN DISTINCT n` with **exactly one** bare-variable return item is accepted; the graph envelope is already distinct by `entity_id`, so DISTINCT is honored (not ignored) and the result equals `RETURN n`. | Cypher-faithful; applied-not-dropped |
| req-grid-gryphon-distinct-12 | Multi-Item Bare Envelope DISTINCT Rejected | Proposed | A bare-variable envelope RETURN with more than one item — `RETURN DISTINCT a, b` or `RETURN DISTINCT n, n` — raises `SearchExecutionError` (no faithful envelope row-tuple semantics), naming the field-projection alternative. | |
| req-grid-gryphon-distinct-13 | count(DISTINCT) Still Rejected | Proposed | `COUNT(DISTINCT x)` remains rejected (`req-grid-gryphon-count-5`); the RETURN-level DISTINCT modifier does not enable it. | Separate future feature |
| req-grid-gryphon-distinct-14 | Aggregate-Return DISTINCT Rejected On Every Path | Proposed | A `RETURN DISTINCT` projection containing an aggregate item raises `SearchExecutionError` in both the `_compute_rows` aggregate branch and the `_execute_optional_match` path (where every valid RETURN carries a COUNT); no aggregate path silently drops the flag. | Deferred; named in Future |

#### Future

- `count(DISTINCT x)` as an aggregate-argument modifier — its own requirement, lowering to `Count(distinct=True)` (upgrade path noted in `req-grid-gryphon-count-5`). The likely next Gryphon feature.
- `DISTINCT` over aggregate/grouped returns, if a demand signal appears.
- `DISTINCT` over JSON *container* sub-values (objects/arrays) — requires a specified jsonb-container equality semantics and relaxing the primitives-only row contract (`req-grid-gryphon-rows-5`); tracked as the "JSON blob" container axis in `doc-gryphon-feature-demand.md` §2.
- Multi-variable envelope distinctness (distinct `(a, b)` pairs), if a real query needs it beyond the field-projection form.
- Envelope-mode dedup controls beyond the existing `entity_id` identity, if a real query needs them.

---

### Backward Compatibility
----
RID: `req-grid-gryphon-compat`

Status: `Implemented`

Every query that parses and executes before this extension lands continues to parse, execute, and return results with the same shape and content after.

#### Implementation

- Single-hop queries produce identical `nodes`/`edges` collections. The new `rows` field is present but empty for these queries (`req-grid-gryphon-rows-6`).
- `WHERE` predicate semantics, `RETURN` projection behavior for non-aggregate field paths, runtime input binding (`$var`), and error shapes are unchanged.
- The existing test suite for single-hop, hub-and-spoke, and edge-scan patterns must continue to pass without modification.
- Error messages previously emitted for unsupported features (multi-hop, aggregates) change content as those features land. Downstream callers that string-match against specific error messages are out of scope for backward compatibility; error codes (where present) remain stable.
- Variable-length edge syntax (`-[:E*m..n]->`), already rejected pre-extension, continues to be rejected with a targeted unsupported-feature error.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-gryphon-compat-1 | Single-Hop Parity | Implemented | Single-hop queries produce identical `nodes` and `edges` collections before and after the extension. | |
| req-grid-gryphon-compat-2 | Existing Test Suite Passes | Implemented | The pre-extension gryphon test suite passes unchanged. | |
| req-grid-gryphon-compat-3 | Envelope Additive | Implemented | New `rows` field is additive; existing envelope keys retain their shape and semantics. | |
| req-grid-gryphon-compat-4 | Error Codes Stable | Implemented | Structured error codes for existing rejection cases are unchanged. | Error message *strings* may be updated |

---

## Future Work

- **Positive `EXISTS { ... }`** subqueries.
- **Numeric aggregates** (`SUM`, `AVG`, `MIN`, `MAX`).
- **`COUNT(DISTINCT ...)`** and **`COUNT(*)`**.
- **`HAVING`** clause for post-aggregation filtering.
- **`SKIP` / `OFFSET`** for query-level pagination, composing with `ORDER BY` / `LIMIT`.
- **Multi-hop / projecting `OPTIONAL MATCH`** — `req-grid-gryphon-optional-match` landed the single-hop, COUNT-only scoreboard shape; multi-hop optional patterns and projecting (not counting) the optional variable remain future work.
- **`UNION`** and **`UNION ALL`** across sibling queries.
- **Variable-length edge traversal** with cycle handling (`-[:E*1..3]->`).
- **Path variable binding** and path-level projections.
- **Nested `NOT EXISTS`** for higher-order anti-joins.
- **Query planner heuristics** once multiple anchor candidates are common.
- **Result pagination** for aggregating queries returning large result sets.

## Downstream Consumers

- **Compliance alert-count population** (`plugins/fedramp_20x_ksi`, cross-reference with `spec-fedramp-20x-ksi-finding.md`) — the motivating consumer. Uses all three new features in a single query.
- **`spec-viz-badges.md` search-backed population** — the `population.type: "search"` variant of status-badge configuration will consume aggregating-query envelopes with a `rows` field keyed `{entity_id, count}`.
- Any future summary/tile panels that reduce graph structure to tabular data.

## Status Vocabulary

| Status States |  |
| --- | --- |
| Implemented |  |
| Approved for Development | Requirement is accepted and ready to be implemented |
| In Development |  |
| Implemented |  |
| Verified |  |
| Refactoring |  |
| Deprecating |  |
| Deprecated | Not part of the current architecture and should not be implemented |

## RID Format

`req-<application>-<specification>-<feature>-<sub-feature>`

## Requirements Format

`RID: `...``
`Status: `...``

| Sub-Sections | (as needed) |
| --- | --- |
| Status Details |  |
| Implementation |  |
| Development |  |
| Acceptance Criteria |  |
| Future |  |
