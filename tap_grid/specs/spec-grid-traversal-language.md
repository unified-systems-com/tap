# Grid gryphon Language Specification

> **Development doctrine (standing filter).** Before any change to the Gryphon language, executor, or tests, consult [`doc-gryphon-commandments.md`](../../docs/doc-gryphon-commandments.md) — the standing thou-shalt/shalt-not doctrine for all Gryphon work (RFC-2119 commandments with Reason + Enforcement, plus a Forthcoming section). Requirements here SHOULD stay consistent with it; it cites requirements here as its Enforcement anchors.

## Philosophy

gryphon should be pleasant to read in strings while still being structured enough to parse into
a predictable AST. Familiarity with Cypher improves readability for engineers who have used
graph databases, but TAP does not aim for Cypher compatibility — only for a language narrow
enough to compile safely into TAP-controlled execution plans.

**Semantic baseline.** Where Gryphon does follow Cypher, the reference for *what* Cypher's
read-only core means is the peer-reviewed formal semantics — Francis, Green, Guagliardo, Libkin,
Lindaaker, Marsault, Plantikow, Selmer, Taylor et al., *"Formal Semantics of the Language Cypher"*
(SIGMOD 2018; [arXiv:1802.09984](https://arxiv.org/abs/1802.09984)). Gryphon is a **subset with
named divergences**, not a re-derivation: the pattern-matching and projection surface tracks that
denotational core, and every place Gryphon deliberately departs from it is catalogued in
[`doc-dev-gryphon-vs-cypher.md`](../../docs/misc/doc-dev-gryphon-vs-cypher.md). The most
load-bearing divergence is on **NULL logic**: Cypher is fully three-valued; Gryphon does not claim
full 3VL across combinators (`req-grid-traversal-lang-is-null`, `-regex-6`). Concretely, a
comparison against a **null literal** (`x = null`, `x STARTS_WITH null`) short-circuits to a genuine
`FALSE` (the two-valued "unobserved operand" rule), while a **null field value** against a non-null
literal follows the backend's SQL three-valued behavior (the row drops from the positive filter).
Citing the baseline turns that boundary from a quirk into an auditable, defensible design decision.

**Gryphon commandment guidance.** Any change to Gryphon syntax, AST shape, predicate semantics,
or Cypher-subset/divergence behavior must read and apply
[`doc-gryphon-commandments.md`](../../docs/doc-gryphon-commandments.md). The
commandments are not a substitute for this spec; they are the standing development discipline for
keeping new language surface explicit, validated, and tested.

## Goals

|    |              |                                                                          |
| :---: | ---       | ---                                                                      |
| 1. | Compact       | Common graph traversals fit in a short gryphon string                    |
| 2. | Familiar      | Cypher-like notation where it improves readability                       |
| 3. | Reusable      | Storable on Search objects, alias rules, panel config, naming policies   |
| 4. | Parameterized | Runtime inputs via $var without rewriting gryphon text                   |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-traversal-lang-shape | [Traversal Language Shape](#traversal-language-shape) | Implemented | MATCH/WHERE/RETURN clause structure |
| req-grid-traversal-lang-storage | [Traversal Storage Form](#traversal-storage-form) | Implemented | String and list[str] storage forms |
| req-grid-traversal-lang-patterns | [Pattern And Binding Syntax](#pattern-and-binding-syntax) | Implemented | Node/edge/path patterns, direction, bounded traversal |
| req-grid-traversal-lang-filters | [Field And Predicate Semantics](#field-and-predicate-semantics) | Implemented | Inline filters and WHERE predicates over model fields; multi-step JSON paths deferred to `req-grid-traversal-lang-filters-jsonpath` |
| req-grid-traversal-lang-filters-jsonpath | [JSONPath For JSON Field Predicates](#jsonpath-for-json-field-predicates) | Proposed | Adopt RFC 9535 JSONPath for `WHERE` predicates over JSON-backed fields; replace in-house dot/bracket grammar |
| req-grid-traversal-lang-envelope-paths | [Envelope-Aware Field Paths](#envelope-aware-field-paths) | In Development | Recognize `data` and `display` lane prefixes in `WHERE`/`RETURN`; explicit-only, no routing sugar |
| req-grid-traversal-lang-combinators | [Predicate Combinators](#predicate-combinators) | Implemented | AND/OR/NOT in WHERE predicates |
| req-grid-traversal-lang-in | [IN-List Membership](#in-list-membership) | Implemented | `WHERE` membership test against a list of values |
| req-grid-traversal-lang-string-match | [String Match Predicates](#string-match-predicates) | Implemented | `WHERE` substring predicates: `STARTS_WITH` / `ENDS_WITH` / `CONTAINS` |
| req-grid-traversal-lang-regex | [Regex Match Operator](#regex-match-operator) | Implemented | `WHERE field =~ pattern` — PostgreSQL ARE/POSIX-family regex, search semantics (substring match; anchor with `^...$`) |
| req-grid-traversal-lang-is-null | [Null-Existence Predicate](#null-existence-predicate) | Implemented | `WHERE field IS NULL` / `IS NOT NULL` — defensive filter for ORDER BY DESC envelope queries |
| req-grid-traversal-lang-observation | [Observation-Semantic Predicates](#observation-semantic-predicates) | Implemented | `WHERE field IS KNOWN` / `IS UNKNOWN` — the field-observation convention's null axis as intent-revealing vocabulary (`IS EMPTY` deferred) |
| req-grid-traversal-lang-bare-match | [Bare Labelless MATCH](#bare-labelless-match) | Implemented | Labelless `MATCH (n)` scans every registered node type and unions the results |
| req-grid-traversal-lang-params | [Runtime Inputs And Variables](#runtime-inputs-and-variables) | Implemented | $var runtime inputs and named pattern bindings |
| req-grid-traversal-lang-returns | [Return Semantics](#return-semantics) | Implemented | RETURN projection and graph envelope default |
| req-grid-traversal-lang-cypher-divergence | [Cypher Divergences Are Documented](#cypher-divergences-are-documented) | Implemented | Every deliberate divergence from Cypher is recorded in a formal `/docs` ledger; this req mandates the doc and its upkeep, not the divergences themselves |
| req-grid-traversal-lang-cypher-credit | [Net-New Capabilities Are Credited](#net-new-capabilities-are-credited) | Implemented | Every capability Gryphon has that Cypher lacks is credited in the same `/docs` ledger — the running tab of where TAP goes beyond Cypher |
| req-grid-traversal-lang-tck-mining | [TCK Mining Per Language Extension](#tck-mining-per-language-extension) | Implemented | Every Gryphon language extension runs the openCypher TCK mining pass; binds the existing Gridkin TCK-inspiration requirement (gryphon_playground plugin) to the language-extension lifecycle |
| req-grid-traversal-lang-type-strictness | [Data-Lane Type Strictness](#data-lane-type-strictness) | Implemented | A data-lane predicate whose literal type contradicts the field's declared schema is rejected, not coerced or silently dropped; the declared schema is the type oracle |
| req-grid-traversal-lang-relation-guard.sec | [Data-Lane Field-Path Allowlist](#data-lane-field-path-allowlist) | Implemented | Every post-`data` token MUST resolve to a concrete declared field (or a key inside a declared JSONField); anything else is rejected — a relation walk, a Django lookup/transform, an undeclared field, or a `__`/bracket-smuggled step. Enforced in `WHERE` and `RETURN` at all three resolvers. Closes `ROOT-1`: one confirmed cross-table read (`b.data.actor.password` → the user table) plus three further manifestations. The `entity`/`dimensions` spine hop is the only sanctioned cross-table join |


### gryphon Language Shape
----
RID: `req-grid-traversal-lang-shape`
Status: `Implemented`

gryphon uses Cypher-compatible clause style for the core read/traversal surface.

#### Implementation

The v1 gryphon language supports these top-level clauses:

- `MATCH` — pattern-binding clause (one or more allowed)
- `WHERE` — predicate clause over bound variables
- `RETURN` — projection clause

Multiple `MATCH` clauses are allowed and are compositional: bindings from earlier `MATCH` clauses
are in scope for later ones, exactly as in Cypher.

The first version is intentionally read-only. It does not include write clauses such as `CREATE`,
`MERGE`, `SET`, or `DELETE`. These are rejected at parse time rather than at runtime.

```text
MATCH p = (port:port)-[:ON_INTERFACE]->(iface:interface)-[:ON_HOST]->(host:host)
WHERE port.name = $port_name
RETURN p, host.entity_id, host.name
```

```text
MATCH (hub)-[edge]-(neighbor)
WHERE hub.entity_id = $entity_id
RETURN hub, edge, neighbor
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-shape-1 | Supports Match Clause | Implemented | gryphon text supports `MATCH` as the primary pattern-binding clause. | |
| req-grid-traversal-lang-shape-2 | Supports Where Clause | Implemented | gryphon text supports `WHERE` predicates over bound variables and fields. | |
| req-grid-traversal-lang-shape-3 | Supports Return Clause | Implemented | gryphon text supports `RETURN` for named variables and projected fields. | |
| req-grid-traversal-lang-shape-4 | Read-Only Surface Only | Implemented | V1 gryphon text excludes graph mutation clauses; they are rejected at parse time. | |
| req-grid-traversal-lang-shape-5 | Multiple Match Compositional | Implemented | Multiple `MATCH` clauses extend the binding scope; earlier bindings are in scope for later clauses. | |
| req-grid-traversal-lang-shape-6 | Single-Clause Enforcement | Implemented | At most one `WHERE` / `RETURN` / `ORDER BY` / `LIMIT` per query; a duplicate is rejected at parse time with a `GryphonParseError`, never silently dropped. | |

#### Multiple WHERE / RETURN / ORDER BY / LIMIT — Rejected At Parse Time

`WHERE`, `RETURN`, `ORDER BY`, and `LIMIT` are each single-clause. A query
carrying more than one of any of them is rejected at parse time with a clear
`GryphonParseError` (`tap_grid/gryphon/parser.py::_ASTTransformer.start`).

Earlier the parser kept only the **first** `WHERE` (and the first `RETURN`)
and **silently discarded** the rest — a query that lied about what it ran.
That silent-drop footgun is closed: a duplicate clause is now a loud, explicit
error, never a silent drop.

Gryphon's working form is a **single global WHERE**, applied to each MATCH
clause scoped to the variables that clause binds (per
`_filter_predicate_for_bindings`). To filter several MATCH clauses
differently, give them distinct variable names so the one global WHERE scopes
correctly — the samsite landing-page search
(`plugins/samsite/grift/landing.grift.json`) does exactly this.

Per-`MATCH` `WHERE` attachment — Cypher's actual semantics, where a `WHERE`
attaches to its preceding `MATCH` and filters that clause — remains future
work: it needs a `where_clause` field on `MatchClause` plus parser and
executor changes, and arrives naturally with `WITH`-style pipelining.

#### Future
Aggregation and `OPTIONAL MATCH` have since landed as extension clauses — see
`spec-grid-gryphon-multihop-aggregation.md` (`req-grid-gryphon-count`,
`req-grid-gryphon-optional-match`). `WITH` (pipelined composition) remains future work.


### gryphon Storage Form
----
RID: `req-grid-traversal-lang-storage`
Status: `Implemented`

gryphon text should be easy to store in JSON-backed definitions without requiring embedded
newlines when they are inconvenient.

#### Implementation

The canonical storage surface allows either:

- a single `string` for single-line gryphon expressions
- a `list[str]` for multi-line gryphon expressions, preserving clause order line by line

Equivalent examples:

```json
{
  "query": "MATCH (hub)-[e]-(neighbor) WHERE hub.entity_id = $entity_id RETURN hub, e, neighbor"
}
```

```json
{
  "query": [
    "MATCH (hub)-[e]-(neighbor)",
    "WHERE hub.entity_id = $entity_id",
    "RETURN hub, e, neighbor"
  ]
}
```

Execution normalizes both forms into one canonical string before parsing.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-storage-1 | Single-Line String Allowed | Implemented | gryphon definitions may be stored as a single string. | |
| req-grid-traversal-lang-storage-2 | Multi-Line List Allowed | Implemented | gryphon definitions may be stored as an ordered list of strings. | |
| req-grid-traversal-lang-storage-3 | Forms Normalize Equivalently | Implemented | TAP normalizes string and list forms into the same executable gryphon meaning. | |

#### Future
If authoring tools later need per-line metadata such as comments or diagnostics, TAP may add an
enriched editor format while keeping these two storage forms valid.


### Pattern And Binding Syntax
----
RID: `req-grid-traversal-lang-patterns`
Status: `Implemented`

gryphon patterns describe node and edge shape, direction, repetition, and named bindings using
Cypher-like syntax.

#### Implementation

V1 pattern syntax supports:

- node patterns: `(n)` or `(n:host)`
- edge patterns: `-[e]->`, `<-[e]-`, `-[e]-`
- typed edges: `-[e:ON_HOST]->`
- anonymous edges: `-[]->` or `-->`
- inline property maps on nodes and edges: `(n:host {name: "web01"})`
- path bindings: `p = (a)-[:EDGE]->(b)`
- bounded traversal: `-[e:EDGE_TYPE*1..3]->`
- anonymous bounded traversal: `-[*1..3]-`
- wildcard matching by omission of label, type, variable, or direction constraint

```text
MATCH (port:port)-[:ON_INTERFACE]->(iface:interface)-[:ON_HOST]->(host:host)
```

```text
MATCH p = (src)-[rel*1..2]-(dst)
```

```text
MATCH (server:host)<-[edge:ON_HOST]-(iface:interface)
```

#### Single-Hop Execution Semantics

A single-hop pattern (`(a)-[e]->(b)`) executes through the **same chain machinery
as a multi-hop pattern** (`_build_chain_queryset` + `_apply_predicate_to_qs` +
`_collect_graph_envelope`). Three consequences follow, all deliberate:

- **The full `WHERE` is applied — apply-or-reject, never silent-drop.** Every
  predicate (not only an `entity_id` anchor) is compiled into the query, with
  data-lane type strictness (`req-grid-traversal-lang-type-strictness`). A
  predicate the path genuinely cannot support raises `SearchExecutionError`
  rather than being ignored. (Earlier, single-hop *envelope* queries honored
  only an `entity_id` anchor and silently dropped every other predicate — a
  silent-wrong-results defect, now closed by routing single-hop through the
  chain path.)
- **Inner-join semantics, consistent with Cypher.** A single hop that matches no
  edge yields the **empty set** — an anchored hop whose anchor node exists but
  has no qualifying edges does **not** return the lone anchor, and an anchor
  `entity_id` that matches no row yields an empty envelope with **no warning**.
  The pattern binds all of its variables or it contributes nothing.
- **Undirected single hops** (`(a)-[e]-(b)`) are the one shape the directed chain
  builder does not handle natively; they execute as the union of their outbound
  and inbound arms, with the `WHERE` applied to **each** arm — so an undirected
  hop never drops a predicate either.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-patterns-1 | Supports Node Variables And Labels | Implemented | Node patterns may declare a variable and label. | |
| req-grid-traversal-lang-patterns-2 | Supports Edge Variables And Types | Implemented | Edge patterns may declare a variable and edge type. | |
| req-grid-traversal-lang-patterns-3 | Supports Directed And Undirected Edges | Implemented | gryphon patterns support `out`, `in`, and undirected graph shape. | |
| req-grid-traversal-lang-patterns-4 | Supports Path Variables | Implemented | Entire matched paths may be bound to named variables. | |
| req-grid-traversal-lang-patterns-5 | Supports Bounded Repetition | Implemented | gryphon patterns support bounded hop repetition such as `*1..3`. | |
| req-grid-traversal-lang-patterns-6 | Supports Anonymous Repeated Edges | Implemented | Bounded traversal may omit edge variable and edge type. | |
| req-grid-traversal-lang-patterns-7 | Supports Wildcards By Omission | Implemented | Unspecified node labels or edge types behave as wildcards within TAP scope. | A labelless edge in an edge-type scan (`MATCH (a)-[e]-(b)`) scans every edge type; a labelless node is the bare type scan (`req-grid-traversal-lang-bare-match`). |

#### Future

**Bare `MATCH (n)` type-scan — landed.** Labelless `MATCH (n)` scanning every
registered node type is now its own requirement, [Bare Labelless
MATCH](#bare-labelless-match) (`req-grid-traversal-lang-bare-match`). It is the
v0 surface of `req-grid-traversal-lang-patterns-7` ("wildcards by omission")
for the standalone node type-scan case.

Consider subgraph-scoped gryphon composition, where one gryphon result becomes the graph
scope for a later gryphon expression. Defer until a concrete use case appears — this expands planner
and result-scope semantics significantly.

Consider a compile-time maximum hop depth cap for safety and performance. Unbounded depth on a
production graph is potentially expensive. Defer until operational experience defines an
appropriate limit.


### Field And Predicate Semantics
----
RID: `req-grid-traversal-lang-filters`
Status: `Implemented`

gryphon text must support matching and filtering on TAP object-model fields, including
JSON-backed structures.

#### Implementation

Filtering is available in two places:

- inline property maps on node and edge patterns: `(n:host {name: "web01"})`
- explicit `WHERE` predicates over bound variables

Dot notation accesses model fields from a bound variable:

- `host.name`
- `host.entity_id`
- `edge.properties.kind`

JSON-friendly access patterns:

- keyed lookup: `node.dimensions["tap.graph"]`
- positional lookup: `node.properties.aliases[0].name`
- array wildcard: `node.properties.aliases[*].name`

Array wildcard semantics: `[*]` means "any member of this array"; a comparison against a `[*]`
path is true when at least one member satisfies the predicate.

```text
MATCH (n:host)
WHERE n.dimensions["tap.graph"] = "web"
RETURN n
```

```text
MATCH (n:host)
WHERE n.properties.aliases[*].name = $alias
RETURN n.entity_id, n.name
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-filters-1 | Inline Property Maps Supported | Implemented | Node and edge patterns may include inline property filters; values are AND'd into the queryset for the bound pattern. | Edge-side filter implementation at `tap_grid/gryphon/executor.py::_apply_inline_edge_property_filters` (closes Gap 1). Verified by tests in `tap_grid/tests/test_gryphon_inline_edge_filter.py`. |
| req-grid-traversal-lang-filters-2 | Where Predicates Supported | Implemented | gryphon text supports `WHERE` predicates over bound variables. | |
| req-grid-traversal-lang-filters-3 | Dot Field Access Supported | Implemented | Predicates may access object-model fields with dot notation (single step). | Multi-step paths into JSON fields are deferred to `req-grid-traversal-lang-filters-jsonpath`. |
| req-grid-traversal-lang-filters-4 | Keyed Json Access Supported | Backlog | Predicates may access JSON keys using bracket notation. | Subsumed by [JSONPath For JSON Field Predicates](#jsonpath-for-json-field-predicates) (`req-grid-traversal-lang-filters-jsonpath`). The executor currently rejects multi-step paths with a clear `WHERE predicates support single dot-step field paths only.` error. |
| req-grid-traversal-lang-filters-5 | Positional Array Access Supported | Backlog | Predicates may address array members by numeric index. | Subsumed by [JSONPath For JSON Field Predicates](#jsonpath-for-json-field-predicates). |
| req-grid-traversal-lang-filters-6 | Array Wildcard Access Supported | Backlog | Predicates may use `[*]` to mean "any array member". | Subsumed by [JSONPath For JSON Field Predicates](#jsonpath-for-json-field-predicates). |

#### Future
`IN`-list membership has landed — see [IN-List Membership](#in-list-membership)
(`req-grid-traversal-lang-in`). Consider adding `EXISTS` and collection functions once enough
real queries demonstrate the need.


### JSONPath For JSON Field Predicates
----
RID: `req-grid-traversal-lang-filters-jsonpath`
Status: `Proposed`

`WHERE` predicates that need to reach into JSON-backed fields (`Edge.properties`, `BaseModel.dimensions`, model-level JSON columns like `configuration` / `properties`) should adopt **JSONPath ([RFC 9535](https://www.rfc-editor.org/rfc/rfc9535.html))** as the canonical path syntax rather than continue evolving an in-house dot/bracket grammar.

#### Background And Motivation

The currently-shipping executor enforces "single dot-step field paths only" in `WHERE` (`tap_grid/gryphon/executor.py::_apply_comparison`). Multi-step paths into JSON fields — `r.properties.relationship_type`, `n.properties.aliases[*].name`, `n.dimensions["tap.graph"]` — all error out, even though three of them are listed as `Implemented` in the ACID table above. That status discrepancy was discovered during Gap 1 mop-up; this requirement realigns the spec with reality and proposes a path forward that does not require us to invent and maintain a JSONPath equivalent.

JSONPath is preferred over the alternatives because:

- **First-class Postgres support.** Postgres has had `jsonb_path_query`, `jsonb_path_match`, and the `@?` / `@@` operators since version 12. They take a JSONPath string verbatim and evaluate it server-side. We do not need to compile, translate, or interpret the path expression in Python — we thread it through to the database.
- **IETF-standardized.** RFC 9535 (2024) settled what had been a defacto standard for ~15 years. Multiple mature implementations exist in every language we'd plausibly target.
- **Spec gets shorter, not longer.** Instead of documenting our half-working dot/bracket grammar (filters-4/5/6 above), we cite RFC 9535 once and inherit its semantics, including filter expressions like `[?(@.kind == "primary")]` that would otherwise be a year of additional grammar work.

The candidates considered and rejected:

- **JMESPath** (used by AWS CLI, Ansible) — clean grammar but no Postgres native support; we'd be writing the same compiler we're trying to avoid.
- **JSON Pointer** (RFC 6901) — path-only, no filter or wildcard capability; too limited.

#### Implementation

The implementation surface is the `WHERE` compiler in `tap_grid/gryphon/executor.py`. The work is:

1. **Recognize JSON-field paths.** When the first step of a dot/bracket path resolves to a `JSONField` on the bound model (`Edge.properties`, `Entity.dimensions`, `BaseModel.<json_column>`), do not attempt native column traversal. Capture the remainder of the path.
2. **Translate to JSONPath.** Map the captured remainder onto a JSONPath expression rooted at `$`. Examples:
   - `r.properties.relationship_type` → `$.relationship_type`
   - `n.dimensions["tap.graph"]` → `$["tap.graph"]`
   - `n.properties.aliases[0].name` → `$.aliases[0].name`
   - `n.properties.aliases[*].name = $alias` → `$.aliases[*].name == "<value>"` inside `jsonb_path_match`
3. **Emit the SQL.** Use Django's `RawSQL` or a custom queryset annotation that calls `properties @@ '<path expr>'::jsonpath` (or `@?` for existence-only). Bind `$alias` parameters into the JSONPath expression safely, not via string interpolation.
4. **Backend gate.** Behind a backend-detection check so future non-Postgres backends fall through to a Python-side evaluator using a JSONPath library (e.g. `jsonpath-ng`) rather than failing.

The dotted gryphon syntax that authors already write (`r.properties.relationship_type`) stays valid — the compiler maps it to JSONPath under the hood. Authors who prefer JSONPath directly can write `r @@ "$.relationship_type == \"violation\""` once that surface is added.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-filters-jsonpath-1 | JSON Field Detection | Proposed | The compiler identifies JSON-field paths by inspecting the bound model's field types and routes them to JSONPath translation. | |
| req-grid-traversal-lang-filters-jsonpath-2 | Dotted Path Translates To JSONPath | Proposed | Existing `properties.<key>` and `properties.<key>.<key>` dotted forms compile to equivalent JSONPath expressions and are evaluated by Postgres `jsonb_path_match`. | Subsumes filters-4. |
| req-grid-traversal-lang-filters-jsonpath-3 | Bracketed Keys Supported | Proposed | `dimensions["tap.graph"]` and similar bracket-key forms compile to `$["tap.graph"]`. | Subsumes filters-4. |
| req-grid-traversal-lang-filters-jsonpath-4 | Positional Array Access | Proposed | `properties.aliases[0].name` compiles to `$.aliases[0].name`. | Subsumes filters-5. |
| req-grid-traversal-lang-filters-jsonpath-5 | Array Wildcard Access | Proposed | `properties.aliases[*].name = $alias` compiles to a JSONPath expression evaluated server-side; semantics: predicate is true when at least one array member satisfies the comparison. | Subsumes filters-6. |
| req-grid-traversal-lang-filters-jsonpath-6 | Bind Params Are Quoted Safely | Proposed | `$param` references in gryphon `WHERE` are inlined into JSONPath expressions through parameterized placeholders, not string concatenation. | Security-relevant; prevents jsonpath injection. |
| req-grid-traversal-lang-filters-jsonpath-7 | Spec References RFC 9535 | Proposed | The spec text replaces the in-house dot/bracket grammar prose with a citation to RFC 9535 as the authority for path syntax. | |

#### Future

- A second surface that lets authors write JSONPath directly in `WHERE` (e.g. `r @@ "$.relationship_type == \"violation\""`) once the translation path is stable.
- Support for non-Postgres backends via a Python-side JSONPath evaluator. Out of scope until a second backend exists.
- Expanding `[*]` semantics to support `ALL` (all members satisfy) in addition to the default `ANY` (at least one satisfies). Worth a separate ACID once a real query demands it.


### Envelope-Aware Field Paths
----
RID: `req-grid-traversal-lang-envelope-paths`
Status: `In Development`

`WHERE` and `RETURN` field paths interact with the canonical envelope
shape ([`spec-grift-envelope`](spec-grift-envelope.md)) by recognizing
two literal lane prefixes — `data` and `display` — and routing them to
the right underlying storage.

#### Background

The envelope shape has a top-level spine surface (Entity-row fields:
`entity_id`, `entity_type`, `name`, `dimensions`, timestamps, `version`,
`originating_grid_id`), a `data` lane (per-model BaseModel-row fields:
`description`, model-specific scalars, `tags`, JSON-typed blobs,
`batch_id`, `flip_map`), and a `display` lane (consumer-namespaced
computed-for-render values: `display.tap_viz.*`, future
`display.tap_web_table.*`, etc.). Without envelope awareness, Gryphon
can address spine fields directly (today's behavior) but has no way
to filter or project on per-model fields like `n.data.tags.Project` —
which is exactly the query shape the samsite landing-page filter
requires.

#### Implementation

- **Explicit-only prefixes.** A path's first step determines the lane:
  - `n.<spinefield>` — resolves against the Entity row. The compiler
    validates that `<spinefield>` is in the canonical spine set
    (`req-grid-entity-spine-surface` / `Entity._meta`). An unknown
    spine field is a parse-time error, not a silent fallback to data.
  - `n.data.<...>` — resolves against the per-model BaseModel row.
    The compiler joins to the typed model and walks `<...>` against
    its columns (scalars or JSON-typed via JSONPath translation per
    `req-grid-traversal-lang-filters-jsonpath`).
  - `n.display.<consumer>.<...>` — resolves against the per-type
    `DEFAULT_DISPLAY[<consumer>]` lookup. Rare in `WHERE` (the values
    are computed, not stored, so filtering on them is unusual);
    common in `RETURN`.

- **No routing sugar.** The compiler does NOT auto-route an unprefixed
  per-model field to the data lane. `n.tags.Project` is an error
  ("`tags` is not a spine field; if you meant the data-lane field,
  write `n.data.tags.Project`"). The error message names the explicit
  form. Rationale: see [Status Details](#envelope-aware-field-paths-status-details).

- **The `data` and `display` keywords are reserved.** No spine field
  may be named `data` or `display`; the spine field list is small and
  the names don't collide with Entity columns today, so this is a
  natural constraint, not a renaming hazard.

- **Compilation target:** scalar columns on the per-model row compile
  to direct Django ORM lookups (`Character.objects.filter(tags__Project=...)`-
  style). JSON-typed paths inside `data` (e.g.
  `data.configuration.<deep>.<path>`) compile via the JSONPath route
  established in `req-grid-traversal-lang-filters-jsonpath`. JSONPath
  filter predicates (`[?(@.key == "value")]`) come along for the ride
  once that requirement is implemented; this requirement does not
  re-litigate them.

#### Status Details {#envelope-aware-field-paths-status-details}

The earlier design draft considered a sugared form — `n.tags.Project`
auto-routing to `n.data.tags.Project` based on a spine-first /
data-fallback resolution rule. That sugar was rejected for two
overlapping reasons:

1. **No prior-art precedent.** Django ORM (through OneToOne joins),
   SQLAlchemy, Mongo, GraphQL, JSON:API, JSONPath all use explicit
   qualified paths. Cypher elides labels but has no spine/data split
   so the question doesn't arise. SQL's implicit-when-unambiguous is
   the closest precedent, but only because column ambiguity is
   statically detectable. **No mainstream system does the
   implicit-routing pattern we were considering.** Inventing patterns
   with no precedent is usually a warning sign rather than novelty.

2. **LLM-author cost-benefit.** The argument for sugar was keystroke
   savings for interactive query writers. In an LLM-authored
   codebase, the writer (LLM) doesn't care about character count;
   the reader (human in code review, debugging, spec writing) is the
   one who pays the cognitive cost of "what does this path actually
   mean?" Explicit paths self-document; implicit routing creates
   opaque-behavior tax with no offsetting benefit.

The conjunction made the explicit-only design the obvious call. This
status-details section is recorded so future designers can find the
rejected alternative and the reasons it was rejected, not re-litigate
them.

#### Examples

```
# Spine field lookup — works today.
MATCH (n:aws_lambda) WHERE n.entity_id = $id RETURN n

# Per-model scalar — new (data prefix).
MATCH (n:aws_lambda) WHERE n.data.runtime = "nodejs22.x" RETURN n

# JSON-typed per-model field — new (data prefix + JSONPath, via
# req-grid-traversal-lang-filters-jsonpath).
MATCH (n) WHERE n.data.tags.Project = "samsite" RETURN n

# Display lane projection — new (display prefix, mostly RETURN-only).
MATCH (n:aws_lambda) RETURN n.entity_id, n.display.tap_viz.icon_url

# Bad — would have worked under the rejected sugar; now an error.
MATCH (n) WHERE n.tags.Project = "samsite" RETURN n
# Error: `tags` is not a spine field; if you meant the data-lane
# field, write `n.data.tags.Project`.
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-envelope-paths-1 | Spine Prefix Implicit | Proposed | `n.<spinefield>` resolves against the Entity row when `<spinefield>` is in the canonical spine set; unknown spine fields are a parse-time error. | The spine set is sourced from `Entity._meta` per `req-grid-entity-spine-surface`. |
| req-grid-traversal-lang-envelope-paths-2 | Data Prefix Required For Per-Model Fields | Proposed | `n.data.<...>` resolves against the per-model BaseModel row. `n.<per-model-field>` without the `data` prefix is a parse-time error with a message naming the explicit form. | No routing sugar. |
| req-grid-traversal-lang-envelope-paths-3 | Display Prefix For Computed-For-Render | Proposed | `n.display.<consumer>.<...>` resolves against per-type `DEFAULT_DISPLAY[<consumer>]` lookups. | Common in `RETURN`, rare in `WHERE`. |
| req-grid-traversal-lang-envelope-paths-4 | Reserved Keywords | Proposed | `data` and `display` are reserved as lane prefixes; no spine field may shadow them. | Constraint, not enforcement — spine fields don't collide today. |
| req-grid-traversal-lang-envelope-paths-5 | JSON Paths Inside Data Compose | Proposed | A path like `n.data.tags.Project` decomposes into "drop into data lane" + "JSON path inside that JSON-typed column" per `req-grid-traversal-lang-filters-jsonpath`. The two requirements compose; no separate JSON-inside-data syntax. | |
| req-grid-traversal-lang-envelope-paths-6 | No Routing Sugar | Proposed | The compiler does NOT auto-route unprefixed per-model field references to the data lane. Implicit routing was considered and rejected; see Status Details. | See [[feedback-explicit-over-brevity-llm-era]] and [[feedback-borrow-from-oss-prior-art]] for the broader principle. |
| req-grid-traversal-lang-envelope-paths-7 | JSON-Typed Spine Multi-Step | In Development | Spine fields that are JSON-typed (today only `dimensions`) support multi-step access (`n.dimensions.<key>`, `n.dimensions["tap.graph"]`) walking into the JSON via Django nested-key lookup. Scalar spine fields cannot be walked into and raise a clear error pointing at `<var>.data.<field>...` for nested access. | Adds first-class dimension filtering — central to TAP's scoping/partitioning story. |
| req-grid-traversal-lang-envelope-paths-8 | Type-Scan Applies WHERE | In Development | A node-only MATCH (type scan) applies the global WHERE clause filtered to predicates whose variables this MATCH binds, per `_filter_predicate_for_bindings`. Previously type-scan silently ignored WHERE — a real bug surfaced by the samsite landing-page filter work (2026-05-21). | OR/NOT inside type-scan WHEREs remains deferred (consistent with the aggregation executor's current AND-only scope per `_flatten_conjunction`). |

### Predicate Combinators
----
RID: `req-grid-traversal-lang-combinators`
Status: `Implemented`

gryphon `WHERE` predicates may be combined using `AND`, `OR`, and `NOT`. Parentheses may be used to
control grouping explicitly.

#### Implementation

Supported combinators:

- `AND` — both operands must be true
- `OR` — either operand must be true
- `NOT` — negates a single predicate
- Parentheses for explicit grouping: `(a AND b) OR c`

All keywords are case-insensitive.

```text
MATCH (n:host)
WHERE n.entity_id = $entity_id AND n.dimensions["tap.graph"] = "web"
RETURN n
```

```text
MATCH (n:host)
WHERE NOT n.name = "excluded" OR n.entity_id = $entity_id
RETURN n
```

Precedence (highest to lowest): `NOT` > `AND` > `OR`. Parentheses override precedence.

Execution compiles the entire `WHERE` predicate tree — `AND` / `OR` / `NOT` and parenthesized
grouping — into a single Django `Q` expression applied as one filter. The type-scan, multi-hop /
aggregation, and `NOT EXISTS`-inner WHERE paths all share this compiler. (`OPTIONAL MATCH` v0
keeps an AND-only WHERE so its mandatory/optional-variable split stays well-defined — see
`spec-grid-gryphon-multihop-aggregation.md`.)

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-combinators-1 | AND Supported | Implemented | `WHERE` predicates support `AND` to require both operands. | |
| req-grid-traversal-lang-combinators-2 | OR Supported | Implemented | `WHERE` predicates support `OR` to accept either operand. | |
| req-grid-traversal-lang-combinators-3 | NOT Supported | Implemented | `WHERE` predicates support `NOT` to negate a single predicate. | |
| req-grid-traversal-lang-combinators-4 | Grouping With Parens | Implemented | Parentheses may be used to override default precedence. | |

#### Future
Add `XOR` if a concrete use case demonstrates the need.


### IN-List Membership
----
RID: `req-grid-traversal-lang-in`
Status: `Implemented`

A `WHERE` predicate may test a field against a **list of values** with `IN`, instead of spelling out an `OR` chain of equality comparisons.

#### Background

"Type is X or Y or Z" is the single most common shape of dashboard filter. Without `IN` it is written `n.kind = "a" OR n.kind = "b" OR n.kind = "c"` — which scales poorly and, more importantly, cannot be parameterized for a filter that lets a user pick an arbitrary subset of options. `IN` is the readable, list-shaped form.

#### Implementation

- Grammar: the `comparison` rule gains a second alternative — `field_path IN value_list` — where `value_list` is a bracketed, comma-separated list of values:

  ```
  comparison: field_path COMPARE_OP value
            | field_path _IN_KW value_list
  value_list: "[" (value ("," value)*)? "]"
  ```

- A list element is a `value` — a string, number, boolean, `null`, or a `$param` reference. Element-level parameterization (`IN [$a, $b]`) is supported; whole-list parameterization (`IN $list`) is future work.
- Semantics: the predicate is true when the field value equals at least one list member. It compiles to the Django `__in` lookup (SQL `IN (...)`).
- **Empty list** — `IN []` — matches nothing. It is legal, not an error: a parameterized filter that resolves to an empty selection should return no rows, not raise.
- **`null` in the list** — `null` has no defined equality, so a `null` element never matches any row (SQL `IN` semantics: `x IN (NULL, 2)` is true only for `x = 2`, never for a `NULL` `x`). This is a defined choice, pinned by a Gridkin scenario.
- `IN` is a comparison leaf: it composes with `AND` (and, where the executor path supports them, `OR` / `NOT`) exactly as an equality comparison does, and is scoped per bound variable by `_filter_predicate_for_bindings` the same way.
- `IN` works in every WHERE-bearing executor path — type-scan and the multi-hop / aggregation path.

#### Examples

```text
MATCH (n) WHERE n.entity_type IN ["aws_lambda", "aws_ec2_instance"] RETURN n

MATCH (n:finding) WHERE n.data.severity IN ["high", "critical"] RETURN n

MATCH (n:host) WHERE n.entity_id IN [$a, $b, $c] RETURN n
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-in-1 | IN Predicate Accepted | Implemented | The parser accepts `field_path IN [values]` as a `WHERE` comparison leaf. | |
| req-grid-traversal-lang-in-2 | Membership Semantics | Implemented | The predicate is true when the field value equals at least one list member; compiles to SQL `IN`. | |
| req-grid-traversal-lang-in-3 | Empty List Matches Nothing | Implemented | `IN []` is legal and matches no rows. | |
| req-grid-traversal-lang-in-4 | NULL Member Never Matches | Implemented | A `null` list element matches no row; other members in the same list still match. | SQL `IN` semantics |
| req-grid-traversal-lang-in-5 | Elements May Be Params | Implemented | List elements may be `$param` references resolved at execution time. | Whole-list `$param` is future work |
| req-grid-traversal-lang-in-6 | Composes With Combinators | Implemented | An `IN` leaf combines with `AND` like any equality comparison. | |

#### Future

- Whole-list parameterization (`WHERE n.kind IN $kinds`, where `$kinds` resolves to a list) — the fully-dynamic "pick any subset" filter.
- `NOT IN` as a distinct surface (today expressible as `NOT (... IN ...)` where the executor path supports `NOT`).
- Label-union node patterns `(n:type1|type2)` — the pattern-level cousin of `IN` over `entity_type` (Gryphon wishlist B4).


### String Match Predicates
----
RID: `req-grid-traversal-lang-string-match`
Status: `Implemented`

A `WHERE` predicate may test a string field against a substring with `STARTS_WITH`, `ENDS_WITH`, or `CONTAINS`.

#### Background

Prefix / suffix / substring filtering is the predicate behind type-prefix filters (`entity_type STARTS_WITH "aws_"`), name search in finders, and log-grep-style dashboard search boxes. Samsite's pass-1 landing page reached for raw ORM `entity_type__startswith` — that ORM reach is the Gryphon-over-ORM rule firing, the demand signal for this predicate (Gryphon wishlist B2).

#### Implementation

- Three word operators join the `comparison` grammar production alongside `COMPARE_OP` and `IN`: `field_path STARTS_WITH value`, `field_path ENDS_WITH value`, `field_path CONTAINS value`. The operators are case-insensitive keywords; the needle `value` is a string literal or a `$param` reference.
- They are ordinary `Comparison` AST nodes — the operator set on `Comparison` is extended, not a new predicate leaf — so they compose with `AND` / `OR` / `NOT`, scope per bound variable, and flow through the predicate-tree-to-`Q` compiler exactly as `=` does.
- They compile to the Django `__startswith` / `__endswith` / `__contains` lookups (SQL `LIKE`).
- **Case-sensitive.** Matching is case-sensitive, mirroring Cypher's `STARTS WITH`. Case-insensitive variants are future work.
- **`LIKE` metacharacters are literal.** `%` and `_` in the needle match themselves — the lookups parameterize and escape the needle, so `CONTAINS "50%"` matches the literal substring `50%`, never `50` followed by anything.
- An empty needle matches every string value (`STARTS_WITH ""` is `LIKE '%'`).
- The needle is expected to be a string; applying these operators to a non-string field is not guarded — behavior is whatever the backend lookup does, the same laxity as `<` / `>`.

#### Examples

```text
MATCH (n) WHERE n.entity_type STARTS_WITH "aws_" RETURN n

MATCH (n:finding) WHERE n.data.title CONTAINS "timeout" RETURN n

MATCH (n:host) WHERE n.name ENDS_WITH $suffix RETURN n
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-string-match-1 | Operators Accepted | Implemented | The parser accepts `STARTS_WITH` / `ENDS_WITH` / `CONTAINS` as `WHERE` comparison operators. | |
| req-grid-traversal-lang-string-match-2 | Substring Semantics | Implemented | The operators match a prefix / suffix / any substring; an empty needle matches every string value. | |
| req-grid-traversal-lang-string-match-3 | Case-Sensitive | Implemented | Matching is case-sensitive. | Case-insensitive variant is future work |
| req-grid-traversal-lang-string-match-4 | Needle May Be A Param | Implemented | The needle may be a `$param` reference resolved at execution time. | |
| req-grid-traversal-lang-string-match-5 | LIKE Metacharacters Literal | Implemented | `%` / `_` in the needle match literally; needles are escaped, not interpreted as wildcards. | Security-relevant |
| req-grid-traversal-lang-string-match-6 | Composes With Combinators | Implemented | A string-match comparison combines with `AND` / `OR` / `NOT` like any comparison. | |

#### Future

- Case-insensitive variants of the three operators — today expressible as `=~ "(?i)...$"` via `req-grid-traversal-lang-regex`; promote a dedicated `_CI` surface only if a real query needs the shorter spelling.
- Wildcard / regex-like pattern matching — discharged by `req-grid-traversal-lang-regex` (`=~`), which generalizes these three when query authors opt into regex syntax.


### Regex Match Operator
----
RID: `req-grid-traversal-lang-regex`
Status: `Implemented`

A `WHERE` predicate may test a string field against a regex pattern with `=~`. Semantics are search/substring (the pattern matches *anywhere* in the value); explicit anchors `^...$` express full-string match.

#### Background

`STARTS_WITH` / `ENDS_WITH` / `CONTAINS` (`req-grid-traversal-lang-string-match`) cover the three fixed substring shapes; that requirement's Future bullet flagged "promote when a real query needs a shape the three fixed operators cannot express." That promotion moment is here: `github_core`'s link-manifest resolver carries a `near_match_pattern` per link rule that needs case-insensitive partial-match diagnostics on identity-provider URLs (`https://Token.Actions.GitHubUserContent.com`, GHES tenants, mixed case) — a shape no fixed substring operator expresses. The resolver currently reaches for Django's `__iregex` directly, which is the Gryphon-over-ORM rule firing (Gryphon wishlist) and the demand signal for promoting regex into the language.

The symbol is borrowed from Cypher (Neo4j / openCypher / Apache AGE all use `=~`) because it is recognizable to anyone arriving from those systems. **Gryphon deliberately diverges from Cypher on semantics**, though: Cypher's `=~` is full-string anchored (implicit `^...$`); Gryphon's `=~` is search-style (substring match) — the same shape as Postgres `~` / `~*` and the same shape as `grep`. The divergence is deliberate because (a) search semantics is what the demand-shape — diagnostic partial matching on URL fields — actually wants, (b) explicit `^...$` is the obvious, LLM-readable way to say "full string," and (c) hidden anchoring is the kind of magic that surprises authors and inflates the cost of every query review. One spelling (`=~`), one set of semantics (search), explicit anchoring on request.

#### Implementation

- Grammar: a new alternative on the `comparison` rule — `field_path "=~" value`. Carries its own rule label (`regex_comparison`) so the transformer can normalize the operator string without re-tokenizing — the `=~` literal does not pass through `.lower()`-friendly word normalization.

  ```
  comparison: field_path COMPARE_OP value
            | field_path STRING_OP value
            | field_path "=~" value                   -> regex_comparison
            | field_path _IN_KW value_list            -> in_comparison
            | field_path _IS_KW _NULL_KW              -> is_null
            | field_path _IS_KW _NOT_KW _NULL_KW     -> is_not_null
  ```

- AST: the `Comparison.op` `Literal` is extended with `"regex"` — `=~` is an operator extension, not a new predicate leaf. `Comparison` is already handled by every predicate walker, so the only touch-points are the parser's `regex_comparison` transformer (which emits `op="regex"`) and the executor's op→lookup map. No walker audit is required.
- Executor: lowers to rung 1 (ORM `QuerySet` composition). `_comparison_to_q` always compiles a `"regex"` op to Django's `__regex` lookup (Postgres `~`). Inline flags `(?i)`, `(?s)`, `(?m)`, `(?x)` are passed through verbatim — Postgres consumes them. The executor does NOT detect, strip, or rewrite any flag: simpler, less magic, fewer edge cases. The `__iregex` lookup (Postgres `~*`) is deliberately not used as a dispatch target — `(?i)` inside the pattern reaches the same engine.
- **Search semantics.** The pattern matches anywhere in the field value. Full-string matching is the explicit shape `=~ "^...$"`. Prefix-only is `=~ "^needle"`; suffix-only is `=~ "needle$"`. There is no implicit anchoring at either end.
- **Regex flavor.** PostgreSQL ARE/POSIX-family regex (the `~` / `~*` engine, surfaced via Django's `__regex` lookup). The `(?i)` flag is the supported case-insensitive shape (the demand) and is exercised in tests. Other inline flags (`(?s)`, `(?m)`, `(?x)`) reach Postgres unaltered and behave per its engine; v0 does not promise broad Java/Cypher flag parity. PCRE-specific features (variable-width lookbehinds, named groups beyond the POSIX form, etc.) hit a known boundary.
- **Needle is regex text, always.** Unlike `STARTS_WITH` / `CONTAINS` (which escape `%` and `_` literally), `=~` does NOT escape metacharacters in the needle — query authors writing `=~` are opting into regex syntax. The same applies to `$param` substitution: `$param = "."` is "any character," not the literal dot. **This is the explicit deal of `=~` and is loud here so it is visible in spec review.**
- **NULL behavior.** A NULL field value does not match — the row is dropped from the WHERE (Postgres `~` on a NULL operand is NULL; NULL is not truthy). A NULL pattern value does not crash and does not match — the predicate compiles to a tautologically-false `Q` so the row is dropped. Behavior of NULL operands *under* `NOT` / `OR` is not specified beyond "the row is dropped from the positive filter" — Gryphon does not claim full Cypher three-valued logic across combinators, only that NULL inputs neither crash nor silently match.
- **Composes with combinators.** A `Comparison` with `op="regex"` joins `AND` / `OR` / `NOT` like any other comparison and scopes per bound variable through the same `_filter_predicate_for_bindings` walker as every other operator.
- **Needle may be a `$param`.** `WHERE n.url =~ $pattern` resolves `$pattern` at execution time. Pattern values are scalar strings, not pre-compiled regex objects.
- **Works anywhere `Comparison` works.** Spine paths (`n.entity_type =~ "^aws_"`, `n.name =~ "(?i)token"`) and data-lane paths (`n.data.url =~ "(?i)githubusercontent\\.com"`) both flow through the same `_comparison_to_q` compiler — the regex operator is not a special case in any walker or path.

#### Security / DoS surface

- **Catastrophic backtracking.** Postgres' ARE/POSIX engine is less prone to catastrophic backtracking than PCRE on common shapes, but pathological patterns (nested quantifiers like `(a+)+`, deeply alternated unions) can still drive CPU exhaustion. v0 does not analyze patterns for known-bad shapes; operator beware.
- **Statement timeout is the defense — when configured.** Postgres `statement_timeout` caps any single query, including a runaway regex. TAP does not currently set a non-zero default at the database layer, so the defense is effective only where the operator (or the deploying environment) has configured one. Future operational hardening (`tap_grid` settings honoring a default statement_timeout, or a Gryphon-layer regex-pattern budget) is tracked under Future below.
- **Needle escaping is the operator's contract.** A regex operator with non-literal needles is the inverse of the substring operators by design — promoting `=~` into the language *is* surfacing this trade-off into the WHERE surface where it is reviewable, instead of leaving it buried in plugin ORM calls.

#### Examples

```text
# github_core's near-match query — case-insensitive search; no implicit anchoring,
# so .* wrappers are not needed.
MATCH (n:aws_iam_oidc_provider)
WHERE n.data.url =~ "(?i)githubusercontent\\.com"
  AND NOT n.data.url = $exact
RETURN n

# Substring search (case-sensitive):
MATCH (n:finding) WHERE n.data.title =~ "timeout" RETURN n

# Full-string match (explicit anchors):
MATCH (n:host) WHERE n.name =~ "^web-[0-9]+\\.prod$" RETURN n

# Anchored prefix (the search-form long-form of STARTS_WITH):
MATCH (n) WHERE n.entity_type =~ "^aws_" RETURN n

# Parameterized needle:
MATCH (n:host) WHERE n.name =~ $pattern RETURN n
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-regex-1 | Operator Accepted | Implemented | The parser accepts `field_path =~ value` as a `WHERE` `Comparison`, with `Comparison.op == "regex"`. | |
| req-grid-traversal-lang-regex-2 | Search Semantics | Implemented | `=~` matches the pattern anywhere in the field value (substring/search). Full-string match is the explicit shape `=~ "^...$"`. | Deliberate Cypher divergence — see Background |
| req-grid-traversal-lang-regex-3 | Regex Flavor | Implemented | The flavor is PostgreSQL ARE/POSIX-family regex (the `~` engine, via Django `__regex`). PCRE-specific features hit a known boundary. | |
| req-grid-traversal-lang-regex-4 | Case-Insensitive Via `(?i)` | Implemented | A leading or embedded `(?i)` flag is passed through to Postgres unaltered and produces case-insensitive matching. Other inline flags (`(?s)`, `(?m)`, `(?x)`) reach Postgres unaltered; broader Java/Cypher flag parity is not promised. | |
| req-grid-traversal-lang-regex-5 | Compiles To Django `__regex` | Implemented | Always compiles to `__regex` (Postgres `~`). The executor never strips or rewrites flags; Postgres consumes them. | Simpler, less magic |
| req-grid-traversal-lang-regex-6 | NULL Behavior | Implemented | A NULL field value does not match. A NULL pattern value does not crash and does not match (the row is dropped). Behavior under `NOT` / `OR` is not claimed beyond "NULL inputs neither crash nor silently match." | |
| req-grid-traversal-lang-regex-7 | Needle Is Regex Text | Implemented | Metacharacters in the needle carry regex meaning; the needle is NOT escaped (unlike `CONTAINS`). | Security-relevant; the explicit deal of `=~` |
| req-grid-traversal-lang-regex-8 | Needle May Be A Param | Implemented | The needle may be a `$param` reference resolved at execution time. | |
| req-grid-traversal-lang-regex-9 | Composes With Combinators | Implemented | A regex `Comparison` combines with `AND` / `OR` / `NOT` like any comparison. | |
| req-grid-traversal-lang-regex-10 | Spine And Data-Lane Paths | Implemented | The operator works on spine fields (`n.entity_type`, `n.name`) and data-lane fields (`n.data.url`, JSON-key paths like `n.data.tags.url`); no walker treats regex as a special case. | |
| req-grid-traversal-lang-regex-11 | Gridkin Scenario | Implemented | A Gridkin scenario exercises: case-sensitive search, `(?i)` case-insensitive search, explicit `^...$` full-match, escaped dot, parameterized pattern, NULL field, NULL pattern, data-lane path, spine path, and AND + NOT composition. | `plugins/gryphon_playground/scenarios/regex_match.gridkin.json` |
| req-grid-traversal-lang-regex-12 | Documented DoS Surface | Implemented | The spec documents catastrophic-backtracking risk and notes Postgres `statement_timeout` as the defense *when configured* — TAP does not set a non-zero default at the database layer in v0. | |

#### Future

- **Configured statement-timeout default.** TAP currently does not set a non-zero `statement_timeout` at the database layer, so the DoS defense for `=~` (and every other ORM call) depends on the deploying environment. Promote when a real incident motivates a TAP-level default or when multi-tenant deployment requires per-query budgets.
- **Catastrophic-pattern detection.** A pattern validator that rejects known-bad shapes (nested quantifiers like `(a+)+`) before execution. Operational hardening; not built in v0.
- **Pattern compilation caching at the Gryphon layer.** Postgres caches its own regex compilation per backend session; layering additional caching at the Gryphon level is deliberately not built — promote on a measured hot-path miss.
- **`=~i` short-form for case-insensitivity** or `MATCHES` keyword alternative spelling. Not built: `=~` plus inline `(?i)` covers the case-insensitive surface; one spelling.
- **`pg_trgm` integration / index-use guidance.** Postgres can use trigram indexes for some regex patterns (anchored prefix). Future performance tuning, not part of this feature.
- **PCRE features.** Postgres ARE/POSIX is the documented flavor. A future move to PCRE (via `pg_pcre` extension or similar) is a separate spec change — promote when a real query needs PCRE-only features.
- **`github_core` consumer migration.** The `__iregex` ORM call in `plugins/github_core/collectors/github_collector/enrichment.py::resolve_links()` should migrate to a Gryphon Search using `=~` (`(?i)`-prefixed pattern), closing the motivating break-glass path. Tracked as a follow-up commit by the `github_core` session.


### Null-Existence Predicate
----
RID: `req-grid-traversal-lang-is-null`
Status: `Implemented`

A `WHERE` predicate may test whether a field is null with `IS NULL` or `IS NOT NULL`.

#### Background

PostgreSQL's native sort places `NULL` values **first** under `DESC` and **last** under `ASC` — surprising for "latest emission" envelope queries, where a row with a `NULL` sort field would silently win `ORDER BY ... DESC LIMIT 1` and the panel would render the wrong artifact. The defensive shape is a query-side filter:

```text
MATCH (a:compliance_artifact)
WHERE a.data.kind = $kind AND a.data.fetched_at IS NOT NULL
ORDER BY a.data.fetched_at DESC LIMIT 1
```

Without this predicate, panel authors must trust the collector to populate the sort field at emission time — a discipline that lives outside Gryphon and that nothing enforces. With it, panel authors defend in the query itself (the "trust the query" contract). This is the specific hardening `req-grid-gryphon-order-by-envelope` anticipated in its Future bullets, promoted on demand from three samsite panels that ride on the new envelope ORDER BY / LIMIT (Gryphon wishlist B3).

#### Implementation

- Grammar: two new alternatives on the `comparison` rule — `field_path IS NULL` and `field_path IS NOT NULL`. They are separate alternatives (not a single rule with an optional `NOT`) because the `_NOT_KW` terminal is underscore-discarded by lark, so the transformer needs distinct rule labels (`is_null` / `is_not_null`) to recover the negated flag.

  ```
  comparison: field_path COMPARE_OP value
            | field_path STRING_OP value
            | field_path _IN_KW value_list  -> in_comparison
            | field_path _IS_KW _NULL_KW              -> is_null
            | field_path _IS_KW _NOT_KW _NULL_KW      -> is_not_null
  ```

- AST: a new predicate leaf `IsNullComparison(field_path, negated: bool)`. Added to the `Predicate` union; `_collect_params_from_predicate` recognizes it (no `$param` refs to collect).
- Executor: lowers to rung 1 (ORM `QuerySet` composition). `_predicate_to_q` adds a branch returning `Q(**{f"{path}__isnull": not negated})` — SQL `IS NULL` / `IS NOT NULL`. Every predicate walker (`_flatten_conjunction`, `_filter_predicate_for_bindings`, `_predicate_field_paths`, `_is_pure_conjunction`, `_find_entity_id_in_predicate`) is updated to recognize the new leaf — a new `Predicate` variant that any walker silently drops would be the well-known "new leaf misses a walker" footgun.
- The new leaf composes with `AND` / `OR` / `NOT` like any comparison and is scoped per bound variable by `_filter_predicate_for_bindings`. It works in every WHERE-bearing executor path — type-scan, hub-and-spoke, edge-type scan, multi-hop / aggregation, OPTIONAL MATCH, and `NOT EXISTS`.
- Parse rejection: bare `IS` without a `NULL` (e.g. `WHERE a.data.x IS`) does not match the new alternatives and fails parse with `GryphonParseError`.
- Field-path surface: the same field-path machinery as every other predicate — spine fields, the `data` lane (`n.data.fetched_at IS NULL`), and `dimensions.<key>` all work. A missing data-lane field on a model row is `NULL` at the column level, so `IS NULL` matches it. A missing JSON key inside a JSONField is also `NULL` under Django's JSON lookup semantics.

#### Examples

```text
# The demand-shape: defend a latest-emission envelope query against NULL sort fields.
MATCH (a:compliance_artifact)
WHERE a.data.kind = $kind AND a.data.fetched_at IS NOT NULL
ORDER BY a.data.fetched_at DESC LIMIT 1

# Find rows that have never had a value set.
MATCH (n:pg_node) WHERE n.data.observed_at IS NULL

# Compose with NOT for the long-form (equivalent to IS NOT NULL).
MATCH (n:pg_node) WHERE NOT (n.data.observed_at IS NULL)
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-is-null-1 | IS NULL Accepted | Implemented | The parser accepts `field IS NULL` as a `WHERE` comparison leaf, lowering to Django `__isnull=True`. | |
| req-grid-traversal-lang-is-null-2 | IS NOT NULL Accepted | Implemented | The parser accepts `field IS NOT NULL` as a `WHERE` comparison leaf, lowering to Django `__isnull=False`. | |
| req-grid-traversal-lang-is-null-3 | Composes With Combinators | Implemented | An `IS [NOT] NULL` leaf combines with `AND` / `OR` / `NOT` like any comparison. | |
| req-grid-traversal-lang-is-null-4 | Works In Every WHERE-Bearing Path | Implemented | The leaf works in type-scan, hub-and-spoke, edge-type scan, multi-hop / aggregation, OPTIONAL MATCH, and `NOT EXISTS`. | Every predicate walker recognizes it. |
| req-grid-traversal-lang-is-null-5 | Bare IS Rejected | Implemented | `WHERE field IS` (no `NULL`) fails parse with a `GryphonParseError`. | |
| req-grid-traversal-lang-is-null-6 | Defends Envelope ORDER BY DESC | Implemented | `IS NOT NULL` filters out NULL-sort-field rows from a labelled type-scan envelope before `ORDER BY ... DESC LIMIT 1`, so a missing collector field cannot silently win the cap. | The originating demand. |

#### Future

- Per-term `NULLS FIRST` / `NULLS LAST` syntax on `ORDER BY` — the alternative shape for the same defensive concern. Not promoted: the `IS NOT NULL` filter is the cleaner contract because it makes the intent explicit at the WHERE layer (where authors already think about row filters) rather than overloading the ORDER BY semantics.
- A dedicated `NOT IN` surface, mirroring the way `IS NOT NULL` is its own alternative rather than `NOT (... IS NULL)` (today expressible as the latter where the executor path supports `NOT`).


### Observation-Semantic Predicates
----
RID: `req-grid-traversal-lang-observation`
Status: `Implemented`

A `WHERE` predicate may test a field against the field-observation convention's null axis with `IS KNOWN` and `IS UNKNOWN` — intent-revealing vocabulary for "observed" vs "unobserved" (`spec-grid-node.md` `req-grid-node-observation`).

#### Background

The convention reads a stored `null` as *unobserved* and a value as *observed*. `IS NULL` / `IS NOT NULL` already express that mechanically, but a query author writing a graph traversal is asking an *observational* question — "which interfaces have we never captured a MAC for?" — not a storage question. `IS UNKNOWN` / `IS KNOWN` make the intent first-class, read naturally, and stay stable as the representation evolves (e.g. a future Phase-2 known-vs-unknown-unknown refinement lives behind `IS UNKNOWN` without changing query text). They are the Gryphon-side, queryable counterpart to the `x-tap-absence` schema annotation.

#### Semantics

`IS KNOWN` / `IS UNKNOWN` test the **null axis only**, which is universal across every field type:

- `IS UNKNOWN` ≡ the field is `null` (unobserved). Lowers to `__isnull=True`.
- `IS KNOWN` ≡ the field is non-null (observed — **inclusive** of observed-empty). Lowers to `__isnull=False`.

The two **partition the null axis**: every row is exactly one of `KNOWN` / `UNKNOWN`, and `IS KNOWN` is the complement of `IS UNKNOWN`. `IS KNOWN` is deliberately *inclusive* — an observed-empty `""` counts as known ("we observed something"). This is forward-compatible: when `IS EMPTY` lands it *narrows within* `IS KNOWN` (`IS EMPTY ⊂ IS KNOWN`) rather than redefining it.

Because they are pure `__isnull` tests, they require no field-type introspection and work on every field type and every WHERE-bearing path.

#### Why `IS EMPTY` Is Not Here

`IS EMPTY` (observed-empty) is deliberately excluded from this pass. "Empty" is a **container-type concept** — `""` for strings, `[]`/`{}` for collections — and is *undefined for scalar fields* (an integer, boolean, or datetime has no empty form; conflating a scalar's zero-value with "empty" is the null-island anti-pattern the convention rejects). So `IS EMPTY` cannot lower to a single type-agnostic test the way the null axis does: it requires resolving each field's type (or its `x-tap-absence.empty_is_meaningful` declaration) and lowering differently per type — string → `= ""`, collection → empty-container test, scalar → match-nothing. That is field-type-aware compilation threaded through every resolver path, a meaningfully larger change. Its only capability `= ""` cannot already express is *collection*-empty, for which there is no current demand. It is therefore designed-but-deferred: the discriminator (`empty_is_meaningful`) already ships in the schema, so only the executor lowering remains for when collection-empty queries have real demand. Until then, observed-empty strings are expressed with `field = ""`.

#### Implementation

- Grammar: two alternatives on the `comparison` rule, mirroring `is_null` — `field_path IS KNOWN -> is_known` and `field_path IS UNKNOWN -> is_unknown`. `KNOWN` / `UNKNOWN` become reserved keywords (like `NULL`); a field literally named `known`/`unknown` is reached via bracket key-step notation.
- AST: a single leaf `ObservationComparison(field_path, kind: Literal["known", "unknown"])`, added to the `Predicate` union; `_collect_params_from_predicate` recognizes it (field-path-only, no `$param`). A distinct leaf (rather than reusing `IsNullComparison`) preserves the observational intent in the AST for future evolution.
- Executor: `_predicate_to_q` and the OPTIONAL MATCH leaf compiler `_comparison_to_q` lower it to `Q(**{f"{path}__isnull": kind == "unknown"})`. Every predicate walker (`_flatten_conjunction`, `_filter_predicate_for_bindings`, `_predicate_field_paths`, `_is_pure_conjunction`, `_collect_params_from_predicate`) recognizes the new leaf — the "new leaf misses a walker" footgun the IS-NULL work flagged.

#### Examples

```text
# Interfaces whose hardware address has never been observed.
MATCH (n:network_interface) WHERE n.data.mac_address IS UNKNOWN
RETURN n.entity_id AS id ORDER BY id

# Interfaces with an observed MAC.
MATCH (n:network_interface) WHERE n.data.mac_address IS KNOWN

# Composes like any leaf.
MATCH (n:network_interface)
WHERE n.data.mac_address IS UNKNOWN AND n.data.state = "up"
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-observation-1 | IS UNKNOWN Accepted | Implemented | `field IS UNKNOWN` parses to `ObservationComparison(kind="unknown")` and lowers to `__isnull=True`. | Unobserved. |
| req-grid-traversal-lang-observation-2 | IS KNOWN Accepted | Implemented | `field IS KNOWN` parses to `ObservationComparison(kind="known")` and lowers to `__isnull=False`. | Observed; inclusive of observed-empty. |
| req-grid-traversal-lang-observation-3 | Composes With Combinators | Implemented | An observation leaf combines with `AND` / `OR` / `NOT` like any comparison. | |
| req-grid-traversal-lang-observation-4 | Works In Every WHERE-Bearing Path | Implemented | The leaf works in type-scan, hub-and-spoke, edge-type scan, multi-hop / aggregation, OPTIONAL MATCH, and `NOT EXISTS`; bare `IS` still fails parse. | Every predicate walker recognizes it. |
| req-grid-traversal-lang-observation-5 | KNOWN/UNKNOWN Partition The Null Axis | Implemented | `IS KNOWN` is the exact complement of `IS UNKNOWN`; `\|KNOWN\| + \|UNKNOWN\|` equals the full set. | Type-agnostic. |
| req-grid-traversal-lang-observation-6 | IS EMPTY Deferred | Proposed | `IS EMPTY` (observed-empty) is reserved as a container-scoped, `empty_is_meaningful`-driven predicate, not built in this pass; observed-empty strings use `field = ""` in the interim. | Needs field-type-aware lowering; no current collection-empty demand. |

#### Future

- **`IS EMPTY`** — container-scoped observed-empty test driven by `x-tap-absence.empty_is_meaningful`: string → `= ""`, collection → empty-container test, scalar → matches nothing. Build when collection-empty queries have real demand.
- **Phase-2 known-vs-unknown-unknown** — once the convention's extended-FLIP applicability work lands, `IS UNKNOWN` may gain refinements (e.g. distinguishing an asserted absence from an unseen field) without changing the surface keyword.


### Bare Labelless MATCH
----
RID: `req-grid-traversal-lang-bare-match`
Status: `Implemented`

A node pattern with no label — `MATCH (n)` — scans **every registered node entity type** and unions the results. One labelless clause plus a `WHERE` replaces an N-clause per-type list.

#### Background

A query that wants "every node tagged `Project = samsite`, whatever its type" otherwise needs one `MATCH` clause per type — eleven clauses for the samsite landing-page node search. A labelless `MATCH (n)` is the wildcard over node types; it is the standalone-type-scan case of `req-grid-traversal-lang-patterns-7` ("wildcards by omission").

#### Implementation

- `MATCH (n)` — a node-only pattern with no label — routes to a dedicated executor path; a labelled `(n:type)` is unaffected.
- **Spine-only `WHERE`** (or no `WHERE`): one scan of the `Entity` spine table, restricted to the registered node types. A spine-field predicate — `entity_type`, `name`, `dimensions` — is evaluated at the scan layer, so `MATCH (n) WHERE n.entity_type STARTS_WITH "aws_"` is a single cheap query, not a sweep of every per-model table. The spine predicate may use `AND` / `OR` / `NOT`.
- **Data-lane `WHERE`** (`<var>.data.<field>`): each registered node type is scanned and the matched entity ids unioned. **A type that lacks a referenced data field contributes zero rows — silently, never an error.** "Type lacks the field ⇒ that type matches nothing" is the contract: a labelless scan with a data-lane filter crosses entity types that have no such field — and no `data` lane at all — without failing. A data-lane `WHERE` must be `AND`-joined in v0; `OR` / `NOT` across the field-absence boundary would need per-type branch pruning and is deferred.
- Edges are not scanned — they are not registered node models, and are matched by edge patterns.
- v0 returns a **graph envelope** only (`RETURN` omitted, or naming bare variables). Row projection over a bare scan, and `ORDER BY` / `LIMIT` on one, are future work.

#### Examples

```text
MATCH (n) WHERE n.data.tags.Project = "samsite" RETURN n

MATCH (n) WHERE n.entity_type STARTS_WITH "aws_" RETURN n
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-bare-match-1 | Labelless MATCH Accepted | Implemented | `MATCH (n)` with no label is accepted and scans every registered node type. | |
| req-grid-traversal-lang-bare-match-2 | Results Unioned | Implemented | Entities of every matching type are returned together in one graph envelope. | |
| req-grid-traversal-lang-bare-match-3 | Field-Absence Is Non-Matching | Implemented | A type lacking a WHERE-referenced data field contributes zero rows, never an error. | The robustness contract |
| req-grid-traversal-lang-bare-match-4 | Spine Predicate Scans Efficiently | Implemented | A spine-field-only WHERE is one `Entity`-table scan, not a per-type table sweep. | |
| req-grid-traversal-lang-bare-match-5 | Edges Excluded | Implemented | A labelless `MATCH (n)` scans node types only; edges are matched by edge patterns. | |
| req-grid-traversal-lang-bare-match-6 | Graph Envelope Only In v0 | Implemented | A bare scan returns a graph envelope; row projection and `ORDER BY` / `LIMIT` are rejected. | |

#### Future

- Row projection over a bare scan (`MATCH (n) RETURN n.entity_id`), and `ORDER BY` / `LIMIT`.
- `OR` / `NOT` in a data-lane `WHERE` on a bare scan — needs per-type predicate-branch pruning.
- Typeless edge scan — `MATCH (a)-[e]-(b)` with no edge type — the edge-pattern cousin of this requirement.


### Runtime Inputs And Variables
----
RID: `req-grid-traversal-lang-params`
Status: `Implemented`

gryphon text should be parameterizable and bind reusable names for nodes, edges, and paths.

#### Implementation

Runtime inputs use `$var` syntax:

- `$entity_id`
- `$port_name`
- `$alias`

Bound names may be introduced for nodes, edges, and paths within `MATCH` patterns. gryphon
storage and execution treat runtime inputs separately from the gryphon text itself. Input values
are provided by the search service or another TAP-controlled caller and validated against an
input schema when one is declared on the Search object.

```text
MATCH p = (port:port)-[:ON_INTERFACE]->(iface:interface)-[:ON_HOST]->(host:host)
WHERE port.name = $port_name
RETURN p, host
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-params-1 | Supports Dollar Variables | Implemented | Runtime inputs use `$var` syntax within gryphon text. | |
| req-grid-traversal-lang-params-2 | Supports Node Edge And Path Variables | Implemented | Traversal matching may bind names for nodes, edges, and entire paths. | |
| req-grid-traversal-lang-params-3 | Inputs Are Supplied Separately | Implemented | Runtime values are provided separately from stored traversal text. | |

#### Future
If TAP later needs default parameter values or parameter typing inline in gryphon text,
define that separately rather than overloading `$var`.


### Return Semantics
----
RID: `req-grid-traversal-lang-returns`
Status: `Implemented`

gryphon supports projection of matched bindings. The default result packaging is a graph envelope
of matched nodes and edges. Including an explicit `RETURN` clause signals that the caller wants
row projection rather than a graph envelope.

#### Implementation

**Default (RETURN omitted):** TAP returns a graph envelope: `{"nodes": [...], "edges": [...]}`.
All matched node and edge variables are included. This is the standard result for graph panels,
neighborhood lookups, and any consumer that drives Cytoscape or a graph visualization.

**Explicit RETURN:** Signals row projection mode. `RETURN` may reference:

- node variables
- edge variables
- path variables
- field projections: `host.name`, `host.entity_id`
- aliased return expressions: `host.name AS accepted_name`

```text
RETURN host
```

```text
RETURN p, host.entity_id, host.name
```

```text
RETURN host.name AS accepted_name, iface.entity_id AS source_interface
```

Execution packaging (graph envelope vs row projection vs other shapes) remains TAP-controlled.
The `RETURN` clause describes what values are requested from the match; it does not define the
wire format.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-returns-1 | Omitted Return Is Graph Envelope | Implemented | When `RETURN` is omitted, TAP returns a graph envelope of all matched nodes and edges. | |
| req-grid-traversal-lang-returns-2 | Explicit Return Signals Row Projection | Implemented | Including `RETURN` signals that the caller wants projected row results rather than a full graph envelope. | |
| req-grid-traversal-lang-returns-3 | Supports Variable Returns | Implemented | `RETURN` may include node, edge, and path variables. | |
| req-grid-traversal-lang-returns-4 | Supports Field Projection | Implemented | `RETURN` may include specific fields from bound variables. | |
| req-grid-traversal-lang-returns-5 | Supports Named Return Aliases | Implemented | `RETURN` may rename returned values using `AS`. | |
| req-grid-traversal-lang-returns-6 | Packaging Remains Tap-Controlled | Implemented | Traversal text does not redefine TAP's canonical execution packaging contract. | |

#### Future
Aggregation and ordering within `RETURN` should be considered only after base traversal
execution semantics are stable.


### Cypher Divergences Are Documented
----
RID: `req-grid-traversal-lang-cypher-divergence`
Status: `Implemented`

Gryphon is Cypher-*familiar*, not Cypher-*compatible* (see [Philosophy](#philosophy)). Where
Gryphon's behavior deliberately differs from Cypher's, that divergence is a **load-bearing
design decision** an engineer arriving from Neo4j / openCypher / Apache AGE will trip over if it
is not written down. This requirement does not decide *whether* to diverge — each divergence is
argued in its own feature requirement (e.g. `=~` search-vs-anchored semantics in
`req-grid-traversal-lang-regex`). It mandates that every such divergence is **also catalogued in
one formal place** so the set is discoverable as a whole rather than scattered across feature
backgrounds.

#### Implementation

- **The ledger lives at `docs/misc/doc-dev-gryphon-vs-cypher.md`** — a single doc that catalogues
  both divergences (this requirement) and net-new capabilities (`req-grid-traversal-lang-cypher-credit`).
  Co-locating them is intentional: a reader asking "how does Gryphon relate to Cypher?" gets one
  answer surface, not two. The doc follows `spec-docs.md` conventions (`doc-` prefix, frontmatter,
  `covers:` / `update-triggers:`).
- **A divergence is recorded when the difference is observable to a query author** — a query that is
  valid Cypher but means something else (or nothing) in Gryphon, or vice versa. Three kinds qualify:
  (a) *semantic* divergence — same surface, different meaning (`=~` search vs anchored); (b)
  *deliberate subset* — a Cypher capability Gryphon intentionally omits (write clauses, most of the
  function library); (c) *structural* divergence — a shape Cypher does not have a question for
  (the spine/data/display lane split, dimension scoping).
- **Adding or changing a divergence updates the ledger in the same change** that lands the feature.
  This is the docs-drift discipline (`req-docs-drift-conventions`) applied to this specific doc:
  a feature requirement that introduces a divergence cites the ledger, and the ledger cites the
  feature requirement back.
- The ledger is a **catalogue, not the authority**: the owning feature requirement remains the
  source of truth for *why* a divergence exists. The ledger summarizes and links; it does not
  re-argue.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-cypher-divergence-1 | Ledger Exists | Implemented | A formal doc at `docs/misc/doc-dev-gryphon-vs-cypher.md` catalogues every deliberate Cypher divergence. | Seeded from the known divergences at creation. |
| req-grid-traversal-lang-cypher-divergence-2 | Divergence Triggers Update | Implemented | Introducing or changing a Gryphon/Cypher divergence updates the ledger in the same change. | Docs-drift discipline (`req-docs-drift-conventions`) scoped to this doc. |
| req-grid-traversal-lang-cypher-divergence-3 | Three Divergence Kinds Covered | Implemented | The ledger distinguishes semantic, deliberate-subset, and structural divergences. | A subset omission is a divergence worth recording, not a silent gap. |
| req-grid-traversal-lang-cypher-divergence-4 | Catalogue Links To Authority | Implemented | Each ledger entry links to the owning feature requirement, which remains the source of truth for the rationale. | The doc summarizes; it does not re-argue. |


### Net-New Capabilities Are Credited
----
RID: `req-grid-traversal-lang-cypher-credit`
Status: `Implemented`

When Gryphon does something Cypher cannot — a query an engineer could not write against Neo4j —
TAP gives itself credit for it in writing. This is not vanity: the set of net-new capabilities is
the precise answer to "why not just use Cypher / Neo4j?", and that question *will* come up — in
positioning, in early-adopter conversations, and the first time someone proposes adopting an
off-the-shelf graph database instead. Tracked as it accrues, the credit ledger is a ready answer;
reconstructed under pressure, it is a guess.

#### Background

The net-new capabilities to date cluster around one theme: **Cypher models present-state; Gryphon
models observation and provenance as first-class.** `IS KNOWN` / `IS UNKNOWN`
(`req-grid-traversal-lang-observation`), the deferred `IS EMPTY`, the planned extended-FLIP
applicability axis, the `x-tap-absence` declared-absence schema annotation, dimension/perspective
scoping, and future provenance-in-query all sit on that one axis. Naming the theme is itself
credit-worthy — it is the differentiator sentence.

#### Implementation

- **Same doc as the divergence ledger** — `docs/misc/doc-dev-gryphon-vs-cypher.md` carries a
  "where Gryphon goes beyond Cypher" section alongside the divergences. One relationship, one doc.
- **A capability is credited when it has no Cypher equivalent** — not merely a different spelling of
  something Cypher already does, but a question Cypher cannot ask. Each entry names the capability,
  its status (shipped / planned / deferred), links its owning requirement, and states the Cypher gap
  in one line.
- **Shipping a beyond-Cypher capability records it in the same change**, symmetric with the
  divergence discipline. The running tab stays current by construction, never by archaeology.
- **Planned and deferred capabilities are listed too**, marked by status — the tab is a forward
  roadmap of differentiation, not only a record of what already shipped.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-cypher-credit-1 | Credit Ledger Exists | Implemented | `docs/misc/doc-dev-gryphon-vs-cypher.md` carries a section crediting every Gryphon capability Cypher lacks. | Shares the doc with the divergence ledger. |
| req-grid-traversal-lang-cypher-credit-2 | New Capability Triggers Credit | Implemented | Shipping a capability with no Cypher equivalent records it in the ledger in the same change. | Symmetric with `req-grid-traversal-lang-cypher-divergence-2`. |
| req-grid-traversal-lang-cypher-credit-3 | Status-Marked Entries | Implemented | Each entry carries a status (shipped / planned / deferred) and links its owning requirement. | The tab doubles as a differentiation roadmap. |
| req-grid-traversal-lang-cypher-credit-4 | Differentiator Theme Named | Implemented | The ledger names the unifying theme (observation + provenance as first-class) rather than only listing features. | The "why not Cypher?" answer is a sentence, not just a table. |


### TCK Mining Per Language Extension
----
RID: `req-grid-traversal-lang-tck-mining`
Status: `Implemented`

Every extension to the Gryphon language surface runs a pass over the corresponding openCypher TCK
(Technology Compatibility Kit) feature folder to **mine corner-case intent** before the feature is
considered done. The TCK is a decade of accumulated "queries that historically broke real graph
engines"; that hard-won corner-case knowledge is exactly what a new predicate or clause needs to be
tested against — even though Gryphon is not Cypher-compatible and the queries themselves are never
ported.

#### Relationship To The Gridkin TCK-Inspiration Requirement

This requirement does **not** redefine the mining workflow — that already exists as
the TCK-inspiration requirement of `spec-gridkin-v0.md` (gryphon_playground plugin repo), with the
operational steps in the `build-gryphon-capability` skill (Step 8) and the rationale in
[`doc-dev-gryphon-wishlist.md`](../../docs/misc/doc-dev-gryphon-wishlist.md) §7. What this
requirement adds is the **lifecycle binding**: the mining pass is a precondition of *every* language
extension specified in this document, not an optional nicety per feature. It exists here so a future
author extending the language surface meets the obligation from the language spec itself, without
having to already know the gridkin validation spec.

#### Implementation

- **Trigger.** Any new or changed grammar production, AST predicate leaf, operator, or clause in this
  spec runs the TCK mining pass for its closest TCK feature folder (e.g. `expressions/null` for the
  observation/null predicates, `clauses/optional-match` for OPTIONAL MATCH).
- **Output.** Each Gridkin scenario whose intent was mined sets `inspired_by` to the source folder —
  the attribution breadcrumb that lets future authors trace which corner-case taxonomies have already
  been swept. A feature with no applicable TCK folder records that fact (in the feature's request note
  or the scenario file) rather than silently skipping the pass — "we looked and there was nothing" is a
  different state from "we never looked."
- **The hard constraints are inherited verbatim** from that requirement: no TCK query
  text, graph data, or expected results are copied; Cypher-specific quirks that are not Gryphon's
  contract are filtered out. The TCK is a mine, never a source.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-tck-mining-1 | Mining Pass Is A Precondition | Implemented | Every language extension in this spec runs the TCK mining pass before the feature is done. | Binds the Gridkin TCK-inspiration requirement to the language-extension lifecycle. |
| req-grid-traversal-lang-tck-mining-2 | Breadcrumb On Mined Scenarios | Implemented | A Gridkin scenario whose intent was mined sets `inspired_by` to the TCK source folder. | Per the TCK-inspiration breadcrumb criterion (`spec-gridkin-v0.md`). |
| req-grid-traversal-lang-tck-mining-3 | Empty Pass Is Recorded | Implemented | A feature with no applicable TCK folder records "looked, found nothing" rather than silently omitting the breadcrumb. | Enforced: `inspired_by` is schema-required and must be a folder cite or an explicit empty-pass marker (`gridkin-scenario.schema.json`); the pre-existing breadcrumb-less scenarios were backfilled 2026-06-30. Distinguishes "no source" from "never checked". |
| req-grid-traversal-lang-tck-mining-4 | No TCK Content Copied | Implemented | No TCK query text, graph data, or expected results enter any Gryphon or Gridkin file. | Inherited from the TCK-inspiration no-copy criterion (`spec-gridkin-v0.md`). |
| req-grid-traversal-lang-tck-mining-5 | Coverage Is Ledgered | Implemented | Per-folder mining coverage (covered/gaps/excluded) is recorded in the corpus-wide coverage ledger, machine-checked and bidirectionally tied to scenario cites. | Binds the Gridkin TCK-coverage ledger requirement (`spec-gridkin-v0.md`); a language extension that cites a new TCK folder must add its ledger entry in the same change. |


### Data-Lane Type Strictness
----
RID: `req-grid-traversal-lang-type-strictness`
Status: `Implemented`

Gryphon is a query language over a **typed** graph: every data-lane field is backed by a column or a
declared JSON Schema, so the executor knows each field's type. A predicate that compares a field to a
literal of a contradicting type is therefore an **authoring error**, and Gryphon surfaces it rather than
papering over it. This is a deliberate, documented divergence from Cypher in **both** directions:

- Cypher silently **drops** type mismatches (`10 = "10"` → false; `10 STARTS WITH "1"` → null), because a
  schema-optional property graph cannot know the type ahead of time. Gryphon's typed lane can, so the
  rationale does not transfer.
- The relational backend, left to itself, silently **coerces** (`"10"` → `10`; a number → `::text LIKE`),
  which returns *wrong rows* — worse than either Cypher behaviour. Strictness exists to stop exactly this.

**The declared schema is the type oracle.** The check resolves a data-lane field path's declared type by
walking the model's `FIELD_CRUD_SCHEMA` (the per-field JSON Schema) to the addressed leaf, and rejects a
literal whose JSON type is not admitted (with `integer` widening to a `number` field, and a union schema
such as `["string","null"]` admitting either). A text operator (`STARTS_WITH` / `ENDS_WITH` / `CONTAINS`
/ `=~`) applied to a non-text field is likewise rejected. A `null` literal is never a type error — it is
the two-valued "unobserved" operand, owned by the null short-circuit and by `IS KNOWN` / `IS UNKNOWN`.

**Interim asymmetry (named, not hidden).** Strictness reaches only as far as the schema declares a
concrete type. A JSON field whose schema is a bare `{"type": "object"}` (or any path that bottoms out in
an un-typed object) is the schema declaring an **open blob**: the oracle returns "no type" and strictness
is skipped on that sub-path — so today `n.data.tags.zone` stays coercion-tolerant while typed columns are
strict. This is a single code path: the same walker lights up strictness on a JSON sub-path the moment
that field's schema gains real `properties`, with no executor change. The gap that JSON fields may
currently declare themselves as un-schema'd blobs is recorded as a named open edge in
`spec-security-posture.md` (decision home `req-grid-entity-validation`).

#### Implementation

- The leaf compiler (`_comparison_to_q`) enforces strictness before lowering a `Comparison` /
  `InComparison` to a Django `Q`, via `_declared_data_types(model_cls, field_path)` (the schema walk) and
  `_enforce_type_strictness`. The model is resolved per call site: the labelled type scan uses the scanned
  model; the labelless scan checks each candidate model; the chain / NOT-EXISTS / OPTIONAL-MATCH paths
  resolve the bound node's model from its pattern label.
- The check runs on the **resolved** literal (after `$param` substitution), so a parameter cannot smuggle
  a wrong-typed value past the gate — the check is on the value, not the syntax.
- Spine fields, `dimensions`, and undeclared fields are not strictness-checked in v0 (the oracle returns
  "no type"); the surface is the declared data lane.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-type-strictness-1 | Mismatch Is Rejected | Implemented | A data-lane comparison/IN whose literal type is not admitted by the field's declared schema raises `SearchExecutionError`, rather than coercing or silently dropping. | Covered by gridkin `in_lists` / `string_match` rejection scenarios. |
| req-grid-traversal-lang-type-strictness-2 | Text Op Requires Text Field | Implemented | `STARTS_WITH` / `ENDS_WITH` / `CONTAINS` / `=~` on a non-text declared field is rejected. | |
| req-grid-traversal-lang-type-strictness-3 | Null Is Not A Type Error | Implemented | A `null` literal operand is handled by two-valued logic (`IS KNOWN`/`IS UNKNOWN`, null short-circuit), never by the type check. | Composes with the NULL-operand guard. |
| req-grid-traversal-lang-type-strictness-4 | Params Checked On Value | Implemented | The check runs on the resolved literal, so a `$param` of the wrong type is rejected too. | |
| req-grid-traversal-lang-type-strictness-5 | Open Schemas Skip Strictness | Implemented | A path bottoming out in an un-typed object (open blob) is not strictness-checked; the same walk applies strictness once the schema declares the sub-key type. | Interim asymmetry recorded in `spec-security-posture.md`. |


### Data-Lane Field-Path Allowlist
----
RID: `req-grid-traversal-lang-relation-guard.sec`
Status: `Implemented`
Tags: `Security`

> The RID retains its original `-relation-guard` slug (the relation-walk was the seed
> finding); the requirement's scope is broader — a **data-lane leaf allowlist**, of which
> relation-crossing is one rejected case. Broadened per the 2026-07-08 security sweep, which
> confirmed the relation-walk shares a single root cause (`ROOT-1`) with three further
> defects.

A `data`-lane field path (`n.data.<...>`) addresses the per-model BaseModel row. Each of the
three field-path resolvers (`_typescan_orm_path`, `_orm_path_for_envelope_path` node+edge
branches, `_bare_spine_orm_path`) strips the `data.` prefix and `__`-joins the remaining
step tokens into a Django ORM lookup, handing the result straight to `.filter()` / `.values()`
/ `F()` **with no validation against the model's declared fields**. Django then interprets
whatever the tokens spell — a real relation, a registered lookup/transform, or an unknown
field. This requirement closes that gap with a single rule: **every post-`data` token MUST
resolve to a concrete declared field on the model (a scalar column, or a JSON key inside a
declared JSONField); anything else is rejected** — a relation edge, a Django
lookup/transform, or an undeclared field. It is enforced on `WHERE` and `RETURN` alike, at
all three resolvers. The sole sanctioned cross-table joins remain the `entity` and
`dimensions` spine hops (`req-grid-traversal-lang-envelope-paths`), TAP-managed grid tables
by construction.

#### Background And Motivation

This requirement exists because the gap was found and confirmed, not hypothesized. On the
current executor:

- `Batch` is a registered Gryphon type (`ENTITY_TYPE = "batch"`) and declares
  `actor = ForeignKey(AUTH_USER_MODEL)` — a relation from a grid model to the **user
  table**, which is *not* grid data.
- `MATCH (b:batch) WHERE b.data.actor.email = "x"` resolves `b.data.actor.email` →
  `actor__email` and emits `... FROM "tap_batch" INNER JOIN "tap_user" ON
  ("tap_batch"."actor_id" = "tap_user"."id") WHERE "tap_user"."email" = %s` — a working
  **blind enumeration oracle** over user emails.
- `RETURN b.data.actor.password` emits `SELECT "tap_user"."password" AS "actor__password"`
  — **direct exfiltration** of the password hash into the result envelope;
  `b.data.actor.is_superuser` likewise leaks the privilege flag.

The reachable surface is the transitive relational closure from any Gryphon-searchable
model. An actor holding only `grid.read` (not admin) can read user PII, password hashes,
and privilege flags — a privilege-scope escape, since `grid.read` is meant to grant *grid*
data. The type-label path is *not* the hole (labels resolve through the registry allowlist
and reject `MATCH (u:user)`); the hole is the field-path resolver. `_declared_data_types`
is a type-coercion oracle, not a relation guard — it returns permissive `None` for an
undeclared relational field like `actor`, so nothing rejects the walk today. This is the
read analog of the write-path edge named in `spec-security-posture.md`, and is recorded in
the Gryphon findings ledger. It is fixed in bug-fix mode (`GRY-TEST-7` — a wrong/unsafe
Gryphon read is never normalized).

This guard is the innermost of a defense-in-depth set: it is the structural, in-code fix
(the query cannot be *expressed*), backed by the opt-in searchability gate
(`req-grid-traversal-exec-searchable.sec`, which can withhold `batch` from Gryphon
entirely), the compiled-query table-scope guard
(`req-grid-traversal-exec-table-guard.sec`, which blocks the *emitted* query before
execution if it references an out-of-scope table — the shape-agnostic net for any gap in
this guard), and the least-privilege database role (`req-grid-search-readonly-role.sec` +
`req-boot-search-role`, under which the DB itself would deny the `SELECT` on `tap_user`).

#### Implementation

The rule is a **positive allowlist**, stated once and enforced everywhere: resolving a
`data`-lane path, each post-`data` token is validated against the bound model's `_meta`
and MUST resolve to **either a concrete declared field on the model, or — when the prior
step is a declared `JSONField` — a key inside that JSON column**. A token that resolves to
anything else is **rejected** with a clear `SearchExecutionError` naming the offending token
and the rule (`GRY-ARCH-3`). This single check closes four manifestations of one root cause
(`ROOT-1`, the un-allowlisted `__`-join), each of which the sweep confirmed:

- **Relation crossing** — a token resolving to a relation field (`field.is_relation` —
  FK/O2O/M2M, or a reverse accessor) is rejected, so `b.data.actor.email` /
  `b.data.actor.password` can no longer emit a cross-table join into `tap_user`. (The seed
  finding.)
- **Lookup / transform injection** — a token that is a registered Django lookup or transform
  rather than a field (`b.data.version.regex`, `.isnull`, `.year`, `.length`) is rejected. It
  is not a declared field, so the allowlist excludes it; this also forecloses the
  type-strictness bypass where a transform sidesteps the declared-type coercion oracle.
- **Undeclared field** — a token naming no declared field (a typo, a probe, a field that does
  not exist) is rejected **at the resolver as a `422` validation error**, not passed through
  to Django where it surfaces as an uncaught `FieldError` → `500`. This removes the
  error-shape leak (a `500`/`422` oracle distinguishes real from unreal field names, and the
  `FieldError` message enumerates valid fields).
- **Composite-token / bracket-key smuggling** — the `__` separator and bracket-key syntax
  cannot be used to smuggle a multi-step walk through a single token: `b.data.actor__password`
  (embedded `__`) and `b.data["actor__password"]` (bracket key) are **split into their
  constituent steps and each step run through the same allowlist** (equivalently, a raw `__`
  inside a single data-lane token is rejected at parse/resolve time), so neither form can
  reach `.filter()` as an opaque lookup string. This is what makes the guard resolver-shape
  agnostic rather than dot-walk-only.

**JSON key access lowers through a structured primitive, never a raw `__` string.** Once a
step is confirmed to be a key inside a declared `JSONField`, its remaining key path is
lowered through Django's structured JSON-path transform (`KeyTransform` / the `->` operator —
the same primitive `req-grid-traversal-exec-row-materialization-6` already uses for
projection), **not** by concatenating the key into a `__`-joined lookup string. This is what
makes the allowlist's JSON case unambiguous: a JSON key literally named like a Django lookup
or transform (`year`, `isnull`, `regex`, `contains`, `range`) or one containing `__` is
resolved as a *key*, because it is passed as structured path data to `KeyTransform`, never as
a lookup token Django's resolver could re-interpret. Absent this rule, `n.data.blob.year`
would be ambiguous — a JSON key `year` vs. a date transform — precisely the collision the
allowlist exists to remove; the structured-lowering rule closes it at the mechanism level
rather than by blocklisting names. A terminal comparison operator (`=`, `>`, `CONTAINS`) is
applied as an explicit lookup on the resolved transform, not smuggled through the path.

Enforcement points:

- **All three field-path resolvers** carry the check — `_typescan_orm_path`,
  `_orm_path_for_envelope_path` (node and edge branches), and `_bare_spine_orm_path`. The
  seed relation-guard design covered only the first; the sweep showed the single/multi-hop
  and edge dispatch shapes reach the other two, so the allowlist lives at the shared
  resolution boundary they all pass through, not at one call site.
- **`WHERE` and `RETURN` alike** — predicate resolution (`_comparison_to_q` /
  `_predicate_to_q`) and projection resolution (the boundary already governed by
  `req-grid-traversal-exec-row-materialization-16`) apply the identical rule. A path rejected
  in `WHERE` is rejected in `RETURN` and vice-versa — no asymmetry an attacker can exploit.
- The `entity.<spinefield>` and `entity.dimensions.<key>` hops remain allowed: they are the
  named spine surface (`req-grid-traversal-lang-envelope-paths`) and join only TAP-managed
  grid tables. This is an allowlist of exactly two relation hops, not a general permission.
- The rejection is **apply-or-reject, never silent** (`GRY-ARCH-3`). It upholds
  `req-grid-traversal-exec-scope.sec-2` ("Tap Scope Only"), which the finding showed was
  aspirational rather than enforced on the field-path axis.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-traversal-lang-relation-guard.sec-1 | Data-Lane Relation Walk Rejected In WHERE | Implemented | A `WHERE` `data`-lane path whose any step resolves to a relation field (FK/O2O/M2M/reverse) raises `SearchExecutionError`; it does not compile to a cross-table join. | The `b.data.actor.email` case. |
| req-grid-traversal-lang-relation-guard.sec-2 | Data-Lane Relation Walk Rejected In RETURN | Implemented | The same rejection applies to a `RETURN` projection path, so the relation cannot be projected into the envelope. | The `b.data.actor.password` case. |
| req-grid-traversal-lang-relation-guard.sec-3 | Own Columns And JSON Keys Still Allowed | Implemented | The `data` lane still addresses the model's own scalar columns and keys inside its JSON-typed columns; only relation-crossing steps are rejected. | No regression to legitimate data-lane paths. |
| req-grid-traversal-lang-relation-guard.sec-4 | Spine Hop Is The Only Sanctioned Cross-Table Join | Implemented | `entity.<spinefield>` and `entity.dimensions.<key>` remain allowed as the sole cross-table joins; every other relation traversal is rejected. | Two-hop allowlist, not a general grant. |
| req-grid-traversal-lang-relation-guard.sec-5 | Rejection Is Loud, Not Silent | Implemented | A rejected relation walk fails with a clear error naming the step and rule (`GRY-ARCH-3`), never a silently-dropped predicate or an empty result. | |
| req-grid-traversal-lang-relation-guard.sec-6 | Lookup / Transform Token Rejected | Implemented | A data-lane token that is a registered Django lookup or transform rather than a declared field (`n.data.version.regex`, `.isnull`, `.year`) is rejected in both `WHERE` and `RETURN`; it cannot lower to a lookup and cannot sidestep the declared-type coercion oracle. | Closes the type-strictness bypass. |
| req-grid-traversal-lang-relation-guard.sec-7 | Undeclared Field Rejected As Validation Error, Not 500 | Implemented | A data-lane token naming no declared field is rejected at the resolver as a `422` `SearchExecutionError`, never passed to Django as an uncaught `FieldError` producing a `500` and an enumerating error message. | Closes the field-name error-shape oracle / column-list leak. |
| req-grid-traversal-lang-relation-guard.sec-8 | Composite-Token And Bracket-Key Smuggling Rejected | Implemented | An embedded `__` (`n.data.actor__password`) or bracket key (`n.data["actor__password"]`) is decomposed and every constituent step run through the allowlist (equivalently a raw `__` inside one data-lane token is rejected); neither reaches `.filter()` as an opaque lookup string. | The resolver-shape-agnostic case. |
| req-grid-traversal-lang-relation-guard.sec-9 | Guard Enforced At All Three Resolvers | Implemented | The allowlist is applied at `_typescan_orm_path`, `_orm_path_for_envelope_path` (node and edge), and `_bare_spine_orm_path`; a type-scan, single/multi-hop, or edge-projection query cannot reach an un-allowlisted `data`-lane token through any dispatch shape. | The seed guard covered only one resolver. |
| req-grid-traversal-lang-relation-guard.sec-10 | JSON Keys Lower Structurally, Not As Lookups | Proposed | A key inside a declared JSONField lowers through `KeyTransform` / `->` (structured path data), never a `__`-joined lookup string; a JSON key named like a Django lookup/transform (`year`, `isnull`, `regex`) or containing `__` resolves as a key, not a lookup. A scenario pins `n.data.blob.year` (JSON key) distinct from any date transform. | Closes the name-collision at the mechanism level, not by blocklist. |

#### Future

- If a future capability needs a legitimate cross-type projection (e.g. surfacing a related
  grid node's field), it arrives as an explicit, named traversal shape with its own
  requirement — never by relaxing this guard to re-admit arbitrary relation walks.
- Field transforms (`.year` on a date, `.length` on text) are a legitimate future query
  capability, but they arrive as an explicit, typed operator surface with their own grammar,
  AST node, and allowlist of sanctioned transforms per declared type — never by re-admitting
  the raw `__`-transform injection path this guard closes (`sec-6`).


## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed |  |
| Implemented | Requirement is accepted and ready to be implemented |
| In Development |  |
| Implemented |  |
| Verified |  |
| Refactoring |  |
| Deprecating |  |
| Deprecated | Not part of the current architecture and should not be implemented |
