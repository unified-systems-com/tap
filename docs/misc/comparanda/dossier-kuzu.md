# Dossier — Kùzu (clone `89f0263cc7a1fd9c396d2c4953747a013556a7f9`, cloned 2026-07-04, license MIT)

> Study artifact of `doc-gryphon-comparative-eval-protocol.md` (§4.4 template). All file:line
> anchors are against the clone SHA above in `undefined/kuzu/`. IP posture: ideas mined, zero
> code copied (protocol §6). First commit 2020-09-26; HEAD commit 2025-10-10; the repo is
> **archived** — the README's closing note says the team is "archiving the KuzuDB project here"
> and "working on something new" (`README.md:1-17`).

## Snapshot

Kùzu is an **embedded, native columnar graph DBMS** speaking Cypher — the successor to the
academic GraphflowDB (first commits under `graphflowdb/` PR prefixes, e.g. merge `28e874155`;
project began 2020-09-26). It is in this study **not** as a relational-lowering cousin (its
storage and executor are its own) but as the **method mine** the protocol names (§2.1): the
best-engineered open-source Cypher *compiler pipeline* available to read. Its bet: a full
multi-IR compiler — ANTLR parse → **Binder** (typed bound statements) → **Planner** (a
logical-operator algebra with DP join-order enumeration and worst-case-optimal joins) →
**Optimizer** (rewrite passes over the logical plan) → **PlanMapper** (one logical→physical
switch) → a vectorized, *factorized* physical executor
(`src/main/client_context.cpp:400,461-472,512-518`). Factorized processing — multiplicity kept
compressed as flat/unflat vector groups rather than materialized as inflated rows — is the
signature idea (README.md: "Vectorized and factorized query processor"; design lineage:
Salihoğlu et al., *Kùzu Graph Database Management System*, CIDR 2023,
https://www.cidrdb.org/cidr2023/; factorization theory: Olteanu & Závodný, *Size Bounds for
Factorised Representations of Query Results*, ACM TODS 2015; WCOJ: Ngo, Porat, Ré, Rudra,
*Worst-Case Optimal Join Algorithms*, JACM 2018).

Inclusion score (§2.2): **deep — method mine**. Relational-lowering relevance: low (native
engine, no SQL emission). Source readability: excellent (each pipeline stage its own
directory; one file per logical operator / per mapper). History richness: excellent — 5,231
commits, 79 contributors, a real fixed-bug stream, and unify/rewrite refactor arcs. Semantics
documentation: good in-code (3VL truth tables written as comments at the implementation
site). Lifecycle: company wound down and archived the repo in 2025 — a RedisGraph-adjacent
commercial data point with the opposite engineering posture.

## Lens E — Execution ★ PRIMARY

### Bottom-turtle question 1 — logical-plan IR: yes, and it is the invariant carrier

Kùzu has a full logical-plan IR between the bound AST and physical execution: 50
`LogicalOperatorType`s (`src/include/planner/operator/logical_operator.h:13-64`), of which
~30 serve read queries (SCAN_NODE_TABLE, EXTEND, RECURSIVE_EXTEND, HASH_JOIN, INTERSECT,
FILTER, FLATTEN, AGGREGATE, ACCUMULATE, SEMI_MASKER, MULTIPLICITY_REDUCER, …). The pipeline
is: `Parser::parseQuery` → `Binder.bind` → `Planner.planStatement` → `Optimizer::optimize` →
(at execute time) `PlanMapper.getPhysicalPlan` (`src/main/client_context.cpp:400,461-472,512-518`).

What the IR buys them, in order of relevance to Gryphon:

1. **A schema-carrying plan.** Every logical operator computes its own output schema —
   `computeFactorizedSchema()` — where the schema is a set of `FactorizationGroup`s, each
   flat or unflat with a cardinality multiplier
   (`src/include/planner/operator/schema.h:14-57`). Scope and multiplicity are *properties of
   the plan*, checkable at construction, not emergent facts discovered at execution.
2. **A single construction choke point per operator.** Planner `append*` functions are the
   only way an operator enters a plan, and each enforces its operator's prerequisites
   before wiring it — e.g. `appendAggregate` runs `appendFlattens(aggregate->
   getGroupsPosToFlatten(), plan)` *before* attaching the aggregate
   (`src/planner/plan/append_aggregate.cpp:9-18`). You structurally cannot build an
   aggregate whose flatten (dedup) prerequisites were skipped.
3. **Optimization as plan rewrites** (filter/projection pushdown, subquery unnesting,
   semi-mask insertion — `src/optimizer/`), each a visitor over the same IR.
4. **Plan-level testability**: optimizer tests assert compact encoded-plan strings like
   `"HJ(b._ID){E(b)S(a)}{E(c)S(b)}"` (`test/optimizer/optimizer_test.cpp:31-100`).

Is the IR the *reason* they avoid Gryphon's bug classes? Partially. The honest read: Kùzu
needs a full IR because it does cost-based join ordering (`planQueryGraph` runs DP over
subgraphs, picking the cheapest plan — `src/planner/plan/plan_join_order.cpp:123-152`), which
Gryphon does not. The transferable part is **not** the optimizer; it is items 1–2 — the
schema-carrying operator DAG whose constructors enforce invariants. That pattern does not
require an optimizer to pay for itself.

### Bottom-turtle question 2 — dispatch: one uniform lowering, normalized at bind time

There are **no per-query-shape executors anywhere**. Every read query — bare scan, labelled
scan, single-hop, k-hop, cyclic pattern, OPTIONAL MATCH, EXISTS, aggregation — normalizes to
a `QueryGraph` (nodes + rels) plus a predicate list, then lowers through the same operator
vocabulary. The normalization happens in the binder, before planning ever sees the query:

- **Inline property maps become WHERE conjuncts**: `MATCH (n {name: 'bar'})` is rewritten to
  an equality predicate ANDed into the clause's WHERE
  (`Binder::rewriteMatchPattern`, `src/binder/bind/read/bind_match.cpp:83-120`).
- **Self-loop edges are rewritten away**: `(a)-[e]->(a)` becomes `(a)-[e]->(b) WHERE id(a) =
  id(b)` (same function, `bind_match.cpp:84-103`) — a shape that would otherwise need its own
  join-handling path is converted into the normal form plus a predicate.
- **OPTIONAL MATCH is not a separate executor**: `planOptionalMatch` plans the optional
  pattern with the *same* `planQueryGraphCollection` machinery and attaches it with a LEFT
  hash join (correlated case) or an optional cross product (uncorrelated case)
  (`src/planner/plan/plan_subquery.cpp:114-171`).
- **EXISTS is not a separate executor**: correlated EXISTS lowers to a mark join over the
  same planner (`plan_subquery.cpp:277-278`); uncorrelated EXISTS to COUNT(*)-aggregate +
  cross product (`plan_subquery.cpp:237-249`). NOT EXISTS is just NOT over the mark column.
- **Label vs no-label is data, not dispatch**: a scan is always `ScanNodeTable` carrying a
  table-ID set; label pruning is a `NodeLabelFilter` operator appended when the set shrinks
  (`src/planner/plan/append_extend.cpp:71-99`), not a different code path.

History confirms the collapse discipline is lived, both ways:

- **Unify commits**: `d40b43f04` "Unify semi mask used in GDS, HNSW index & Recursive join"
  (2025-05-15); `c6f88285c` "Unify vector index, gds & table function planning";
  `ca5d82ad8` "unify CopyNode and CopyRel operator"; `f9e9e29f1` "unify many_one and
  many_many storage".
- **A full executor-path rewrite**: the original dedicated recursive-join operator was
  replaced by a GDS(graph-algorithm)-based recursive extend, then the old one deleted —
  `96ecc65fd` "Remove old recursive extend (#4976)" (2025-02-28).
- **And a principled re-split**: a week later they split recursive join from GDS *at every
  level* — binding (`15156bf19`), logical (`3de91bb84`), physical (`7c25727df`) — because
  the two semantics genuinely diverged. The lesson is two-sided: collapse aggressively, but
  when a collapse forces two meanings through one path, split *along the IR layers*, keeping
  each layer's vocabulary uniform. Neither move re-introduced a per-query-shape executor.

### Bottom-turtle question 3 — invariants at structural choke points

- **Read-only**: decided once at prepare time by a visitor over the parsed statement
  (`StatementReadWriteAnalyzer`, `client_context.cpp:451-458`) and enforced centrally —
  `"Cannot execute write operations in a read-only database!"`
  (`client_context.cpp:432`). Not re-checked per operator.
- **Parameterization**: `$param` values live in a bind-time `parameterMap` on the prepared
  statement (`client_context.cpp:461-470`, `src/main/prepared_statement.cpp:60-77`); no
  string interpolation surface exists.
- **Type discipline**: exactly one implicit-cast gate. `ExpressionBinder::
  implicitCastIfNecessary` → `implicitCast` consults a central allowlist
  (`CastFunction::hasImplicitCast`) and otherwise throws `BinderException`: "Expression {}
  has data type {} but expected {}. Implicit cast is not supported."
  (`src/binder/expression_binder.cpp:103-135`). Coercion is rule-governed, centralized, and
  bind-time — never an executor improvisation.
- **Multiplicity/flatten correctness**: each logical operator *declares* its flatten
  requirements (`getGroupsPosToFlatten`) and the append functions apply them — the invariant
  is attached to the operator definition, not re-remembered at call sites
  (`src/planner/operator/logical_aggregate.cpp:32-59`,
  `src/planner/plan/append_projection.cpp:11-35`).

### Bottom-turtle question 4 — fail-closed: conservation + unreachable defaults

The envelope-WHERE bug shape — a path accepting input it silently ignores — is structurally
prevented in three distinct places:

1. **Predicate conservation in the planner.** Predicates are tracked *by index* in a set;
   each is either claimed by the query graph that can evaluate it, or falls through to a
   `remainingPredicates` loop that appends it as a Filter at the top of the plan
   (`src/planner/plan/plan_join_order.cpp:52-119`). A predicate cannot exit the planner
   unapplied; the worst case is a suboptimally-placed filter, never a dropped one.
2. **Pushdown that can only relocate, never drop.** `FilterPushDownOptimizer`'s default case
   for an operator it doesn't understand is a barrier: it stops the push and
   `finishPushDown` re-appends every unconsumed predicate as a Filter right there
   (`src/optimizer/filter_push_down_optimizer.cpp:43-47,233-242`). An optimization pass that
   forgets a case degrades performance, not correctness.
3. **Unrouteable input is a loud error.** The recursive-pattern WHERE binder splits the
   predicate on AND and routes each conjunct by variable dependency (node-dependent →
   node predicate, rel-dependent → rel predicate); a conjunct depending on *both*, or on
   *neither*, throws `BinderException` rather than being guessed at or ignored
   (`src/binder/bind/bind_graph_pattern.cpp:380-423`; sharpened by fix `d187ff2c0` "Fix
   label predicate in recursive pattern (#4966)"). And the logical→physical mapper's
   `default:` is `KU_UNREACHABLE` (`src/processor/map/plan_mapper.cpp:197-198`) — an
   unmapped operator aborts, it does not skip.

### The specific lowerings

- **Single-hop / k-hop**: each hop is an `EXTEND` operator (index-based adjacency
  traversal) appended onto the growing plan; join-order DP decides between extend chains and
  hash joins per level (`plan_join_order.cpp:154-176`); cyclic patterns at level ≥ 2 also
  get a worst-case-optimal `INTERSECT` (multiway) plan candidate
  (`Planner::planWCOJoin`, `plan_join_order.cpp:354`).
- **Variable-length / recursive**: `RECURSIVE_EXTEND` runs a GDS-style frontier computation
  over node/rel IDs only; per-path node predicates are compiled into **semi-masks** fed as a
  side input (`src/planner/plan/append_extend.cpp:100-125`), and path node/rel *properties*
  are hash-joined back after traversal by `PATH_PROPERTY_PROBE` — traversal state stays
  narrow, property fetch is a separate, uniform join.
- **OPTIONAL MATCH / EXISTS / aggregation**: see question 2; all compositions of the same
  operators (LEFT hash join with mark, mark join, AGGREGATE with declared flatten groups).
- **NULL/3VL**: full Kleene 3VL, implemented once as literal truth tables — `NULL_BOOL = 2`
  with the AND/OR/XOR tables written out in comments at the implementation site
  (`src/include/function/boolean/boolean_functions.h:8-90`; NOT needs no table since
  NOT NULL = NULL, noted at `boolean_function_executor.h:11-12`). The spec *is* at the code
  site; every combinator reads from one artifact. (Contrast Gryphon's deliberate 2VL-literal
  / 3VL-field split — Ledger B of `doc-dev-gryphon-vs-cypher.md` — which is a different
  semantics but currently lives distributed across `_predicate_to_q` sites.)
- **Type handling**: coerce-by-allowlist at bind time, reject everything else loudly
  (`expression_binder.cpp:103-135`). Untyped NULL literals get a default type assigned at
  bind (`NULL IS NULL` crashed until fix `1255c52ce` assigned BOOL to the ANY-typed child —
  `src/binder/bind_expression/bind_null_operator_expression.cpp`; regression test landed in
  the same commit). The null *literal* is their bug magnet too — same hotspot as ours.
- **Row-inflation defenses**: the deepest structural answer in the study. Multiplicity is
  *represented, not materialized*: an extend marks the neighbor group unflat with a
  cardinality multiplier instead of duplicating bound-side rows
  (`append_extend.cpp:86-93`, `schema.h:14-57`). Operators that would be wrong over
  compressed multiplicity declare forced flattens — distinct aggregates flatten every
  dependent group other than the unflat key group (`logical_aggregate.cpp:32-59`);
  projections flatten all-but-one (`append_projection.cpp:25-30`); and a
  `MULTIPLICITY_REDUCER` operator re-normalizes tuple multiplicity before projection
  boundaries (`src/processor/operator/multiplicity_reducer.cpp:6-20`). Overcounting is
  prevented by construction, not by remembering DISTINCT.
- **Determinism/ordering**: results are unordered unless ORDER BY — the e2e test runner
  sorts both expected and actual output unless `-CHECK_ORDER` is set
  (`test/test_runner/test_runner.cpp:186-188,327-331`). NULL position under ORDER BY is
  structural: the radix-sort key prepends a null-flag byte (UINT8_MAX in ASC), so null
  placement is a property of key encoding, decided once
  (`src/include/processor/operator/order_by/order_by_key_encoder.h:38-39,70-71`).

**★ transferable to Gryphon:** (1) bind-time normalization to one form — inline sugar,
self-loops, anchor shapes all rewritten into pattern + WHERE-conjunct normal form *before*
dispatch sees them; (2) the predicate-conservation ledger — every WHERE conjunct is
registered and must be consumed exactly once or fail loud; (3) per-operator declared
prerequisites enforced at the single construction choke point (the shape a thin Gryphon IR
should take, well short of a cost-based optimizer); (4) dependency-routing rejection for
predicates entering the variable-length seam (our E1); (5) aggregate-over-keys as a declared
structural rule rather than per-site DISTINCT hygiene.

## Lens T — Testing

- **Oracle model**: no independent reference implementation. The backbone is a very large
  answer-asserting e2e corpus — 465 `.test` files under `test/test_files/` — where each
  scenario states a query and its expected tuples, authored by humans (self-consistent
  assertions; the trap our model oracle exists to escape). External semantics pressure comes
  from a **ported-and-adapted openCypher TCK**: 88 `.test` files under
  `test/test_files/tck/` restating TCK scenarios in Kùzu DDL/syntax
  (`test/test_files/tck/match/match1.test:1-40`). Port-not-mine is viable for them because
  they *claim* Cypher compatibility; Gryphon's mine-not-port stance
  (the Gridkin TCK-inspiration requirement, `spec-gridkin-v0.md` in the
  gryphon_playground plugin repo) remains correct for a deliberate divergent subset.
- **Differential/metamorphic**: none in-repo. No TLP, NoREC, PQS, or plan-differential
  harness exists in the tree.
- **Fuzzing**: aspirational only — issue #2485 "Setup Fuzzing Infrastructure" (open, never
  landed; repo now archived). No grammar-based generator, no shrinking. Wrong-result reports
  arrived from users: 56 issues match "wrong result" (gh search 2026-07-04), e.g. #4715
  "Logic bug causing non-existing relations returned" (v0.7.1), #3024 "WHERE clause
  sometimes fails in filtering results but adding non-existing lines", #6010 "incorrect
  result using `IN`" (still open at archive time).
- **Corpus/coverage/regression capture**: strong regression discipline — a dedicated
  issue-keyed corpus (`test/test_files/issue/*.test`, 54 CASEs, files literally named
  `issue*.test`), and fixes land with their pinning test in the same commit (e.g.
  `1255c52ce` adds `test/test_files/tinysnb/function/null.test` alongside the binder fix).
  No mutation testing, no branch-coverage gate found in CI workflows
  (`.github/workflows/ci-workflow.yml`).
- **Answer-vs-artifact posture**: answers first — tuples compared sorted-unless-ordered
  (`test_runner.cpp:186-206`), with an md5-hash mode for very large results (hash of the
  *sorted answer text*, still an answer check — `test_runner.cpp:170-179,335-345`).
  Plan-artifact assertions exist but are confined to optimizer unit tests and use a compact
  encoded-plan string (`"HJ(b._ID){E(b)S(a)}{E(c)S(b)}"`), at least once paired with a
  result-count assertion in the same test (`test/optimizer/optimizer_test.cpp:90-93`) — a
  disciplined version of artifact-checking: assert the *shape* the rewrite is supposed to
  produce, and separately assert the answer.

**★ transferable to Gryphon:** little on the harness side — Gryphon's ladder (model oracle,
property fuzzer, TLP, snapshot discipline, coverage gates) strictly exceeds Kùzu's in-repo
validation; that is a **credit**, and a caution (a 5,000-commit engine with excellent
architecture still shipped 56 user-reported wrong-result bugs without a differential
harness). The two importable ideas: the issue-keyed regression corpus convention (we have
the findings-ledger; naming scenario files by finding/issue ID would make the
regression↔ledger link mechanical), and compact encoded-plan-shape assertions *if/when*
Gryphon grows plan rewrites or an IR (assert shape and answer, never shape alone).

## Lens H — History

- **Scale**: 5,231 commits, 2020-09-26 → 2025-10-10, 79 contributors; knowledge concentrated
  in ~7 people (ziyi chen 960, Guodong Jin 875, andyfeng 764, 囧囧 402, Benjamin Winger 335,
  xiyang 316+142 — `git shortlog -sn`). 1,582 commits match the correctness-fix grep
  (`fix|bug|wrong|incorrect|inflat|null|predicate|dedup|regress`).

- **Bug taxonomy** (grep-clustered on commit subjects; classes overlap; representative SHAs
  read):

| Class | ~Count | Representative | Note |
| --- | ---: | --- | --- |
| Storage / txn / WAL / checkpoint / buffer | 48 | `dcdd534d6` copy-rollback wrong result; `77386aeac` MVCC | **Inapplicable to Gryphon** — read-only over trusted Postgres forecloses the entire class (credit) |
| NULL semantics in functions/aggregates | 50 | `3ab41615b` null list entries in AggregateHashTable; `1fdfab7e6` null keys in distinct HT; `34b1eb7aa` null in COUNT agg state; `1255c52ce` `NULL IS NULL` | The **null-literal-with-no-type** and **null-inside-aggregate** boundaries recur for years |
| Cast / type coercion | 38 | `aaf60867a` rework null handling in string casting; `100f975ae` JSON cast bugs | Mostly in casting machinery Gryphon rejects instead of building (credit to type-strictness) |
| Aggregation / DISTINCT | 33 | `b7d37bf3e` mixed distinct/non-distinct aggregates; `885a7fde5` distinct agg on recursive rel; `c308a5aff` distinct+ORDER BY ordering | Dedup-under-aggregation is *their* recurring shape too — even with factorization, at the boundaries |
| Recursive / variable-length paths | ~10 real | `d187ff2c0` label predicate in recursive pattern; `ace38f7e7` multi-label recursive join; `a9f31f471` all-shortest-path lower bound; `1f3c7e81d` PathSingleTableSemiMasker wrong results | Predicate × var-length interaction is the top *executor-semantics* bleeder |
| OPTIONAL MATCH / mark join | ~5 real | `7cb6fabba` optional-match + merge; `0c59cc5c1` OPTIONAL MATCH null handling; `44a70abbd` merge operator mark | Mark-column and null-propagation edges |
| Ordering | 16 | `c308a5aff` | Mostly distinct/order interactions |
| Direction / undirected edges | 3 | `63424031c` undirected src&dst wrong order; `617f170d6` undirected path src/dst | Small but silent-wrong-answer shaped |
| Predicate placement / pushdown | 6 | `58b822284` multi-query filter result error; `5634ea21b` projection pushdown on sql_query fn | Low count — consistent with the conservation architecture (§Lens E q4) |

- **Turning-point commits**: the recursive-extend arc — `96ecc65fd` "Remove old recursive
  extend" (2025-02-28) deleting the legacy operator after the GDS-based one became
  canonical, then the three-layer re-split `15156bf19` / `3de91bb84` / `7c25727df`
  (2025-03) when one unified path proved to be carrying two semantics; the semi-mask
  unification `d40b43f04` (2025-05); `aa01fdbe5`/`21dbaeac4` semi-mask refactors preceding
  it; `c528c77b6` removing the ENCODED_JOIN special case (2024-10). The optimizer-induced
  wrong-result fix `1f3c7e81d` (semi-masker, 2024-10) is the cautionary one: **a
  performance-only optimization (sideways information passing) produced wrong results when
  its masking was wrong** — every "transparent" optimization is a correctness surface.
- **Design-doc / RFC trail**: thin in-repo (no docs/ directory; documentation moved to
  kuzudb.github.io). The reasoning that is preserved lives in the CIDR 2023 paper and in
  unusually good in-code comment blocks (the 3VL truth tables, the planner's subquery
  comments at `plan_join_order.cpp:189-198`).
- **Lifecycle lesson**: a technically excellent, actively-maintained engine (222 commits
  after 2025-07-01) was still archived when the company pivoted (`README.md:1-17`).
  Same terminal state as RedisGraph via the opposite route — RedisGraph died of an
  architecture too alien to staff, Kùzu's architecture was exemplary and it died anyway.
  Peer-system quality is not survival; for the study's strategy-validation axis it means
  *neither* foil resolves "native vs lowering" on commercial grounds — the decisive
  arguments stay technical (inherited substrate correctness vs owned-executor performance).

**★ predicted Gryphon hotspot(s):** (1) null-inside-aggregate boundaries — COUNT/aggregates
over null-bearing fields and null keys in any future GROUP BY (their #4909/#4949 shape) —
our fuzzer should generate aggregates over deliberately-null-seeded fields; (2) predicate ×
variable-length interaction the moment E1 (bounded repetition beyond the current subset /
`WITH RECURSIVE`) grows — their #4966 is precisely a predicate mis-routed into a recursive
pattern; (3) direction/undirected src-dst identity swaps in envelope serialization (their
#5416/#5041) — a silent-wrong-answer class our edge-identity comparisons would catch but
only if scenarios exercise BOTH-direction patterns; (4) DISTINCT × ORDER BY interaction
(#4345) when Gryphon grows DISTINCT.

## Net read

The biggest thing to steal is not the IR wholesale — it is the **three-part fail-closed
lowering discipline** the IR hosts: bind-time normalization of all sugar into one
pattern+predicate normal form (`bind_match.cpp:83-120`), index-tracked predicate
conservation where every conjunct is consumed-or-reapplied and unrouteable ones throw
(`plan_join_order.cpp:52-119`, `bind_graph_pattern.cpp:407-423`), and per-operator declared
prerequisites enforced at a single append-time choke point (`append_aggregate.cpp:9-18`).
Each is adoptable in Gryphon *today*, without a cost-based optimizer, and each makes one of
our known bug classes (predicate drop, predicate mis-scope, aggregate inflation)
structurally inexpressible rather than tested-against. The thing to avoid is their
validation posture: a superb architecture with only self-consistent answer files and an
unbuilt fuzzing wish (#2485) still accumulated a 56-issue wrong-result tail — architecture
and differential testing are complements, not substitutes, which is the strongest external
confirmation of Gryphon's dual bet. Credits: roughly half of Kùzu's entire fix stream
(storage/transaction/cast machinery, ~86+ commits) lands in code Gryphon structurally does
not have — the read-only, trusted-substrate, schema-as-oracle bets each foreclose a class a
5,000-commit peer paid for in full.
