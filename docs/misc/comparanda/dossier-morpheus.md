# Dossier — Morpheus / Cypher for Apache Spark (CAPS)

Clone: `5bb7b31b7005b47b5c0fb49ec34464f256ae3041` (github.com/opencypher/morpheus), read 2026-07-04.
License: Apache-2.0 (`LICENSE.txt`). Status: unmaintained/unofficial — README disclaimer added
2026-01-14 (`4f6398ee7`), NOTICE "UNOFFICIAL PROJECT NOTICE" (`5bb7b31b7`); last substantive
engineering activity 2019, cosmetic upkeep (scalafmt `e5f267204`, 2025-12) since.
History: 4,651 commits, 2016-08-02 → 2026-01-14; knowledge held by a small Neo4j core
(Junghanns 1167, Rydberg 846, Stutz 579+500, DarthMax/Kießling 535+131, Plantikow 334 — `git shortlog -sn`).

> Anchors are `file:line` at the clone SHA above (note: tree was scalafmt-reformatted in
> `e5f267204`, so line numbers differ from 2019-era blogs/PRs), commit SHAs, or issue/PR numbers.
> Per the IP posture (protocol §6): ideas mined, no code copied; anything adopted is
> reimplemented in TAP's idiom.

## Snapshot

Morpheus (né CAPS) is openCypher's own answer to "compile Cypher to relational execution": a
Cypher-9-plus-multiple-graphs engine whose front half is Neo4j's real openCypher front-end
(parse → semantic analysis → CNF normalization) and whose back half lowers through **three
in-house IRs** — a block-structured query IR, a logical-operator plan, and a **backend-agnostic
relational-operator plan** — before a thin `Table[T]` trait binds it to Spark DataFrames (and
Catalyst optimizes underneath). It is the purest large-scale existence proof of the layered-IR
architecture Gryphon's execution spec anticipates but has not built
(`spec-grid-traversal-execution.md`, `req-grid-traversal-exec-compiler` Future). Inclusion score
against protocol §2.2: relational-lowering relevance **maximal** (graph pattern → join tree over
element tables, exactly Gryphon's problem); source availability excellent (Apache-2.0, readable
Scala); history rich (4.6k commits, PRs with reasoning, a documented mid-life pipeline collapse);
semantics documentation good (TCK harness + acceptance suites double as a semantics ledger). Its
weakness as a teacher: it executes on Spark, so some scar tissue (partitioning,
`monotonically_increasing_id`, Catalyst bugs) is substrate-specific — though even that carries a
transferable lesson (§Lens H).

## Lens E — Execution  ★ PRIMARY

### Pipeline shape / IR count

Query string → **(1)** Neo4j openCypher front-end: parse, preparatory rewriting, semantic
analysis, AST rewriting, `isolateAggregation`, `Namespacer`, `CNFNormalizer`, late rewriting —
and **literal extraction into parameters** at parse time (`endState.extractedParams`,
`okapi-ir/.../parse/CypherParser.scala:73-100`; consumed at
`okapi-relational/.../RelationalCypherSession.scala:179-185`) → **(2)** query IR: typed blocks
(`MatchBlock`, `ProjectBlock`, `AggregationBlock`, `OrderAndSliceBlock`, …;
`okapi-ir/.../api/block/`, built by `okapi-ir/.../impl/IRBuilder.scala`) with a schema-driven
typer (`okapi-ir/.../impl/typer/`) → **(3)** logical plan (`LogicalPlanner.scala`) →
logical optimizer (3 rewrite rules, `LogicalOptimizer.scala:49-53`) → **(4)** backend-agnostic
relational-operator plan (`RelationalPlanner.scala`) → relational optimizer (cache-insertion
only, `RelationalOptimizer.scala:36-42`) → **(5)** `Table[T]` backend ops
(`morpheus-spark-cypher/.../table/SparkTable.scala`) → Spark Catalyst (its own logical/physical
planning, inherited free). Full stage sequencing: `RelationalCypherSession.scala:161-340`.

**Answer to the bottom-turtle question 1 (logical IR):** yes — emphatically, and *twice over*
(logical + relational layers, both backend-neutral). What it buys them, observable in the code:

- **One lowering match per boundary** (dispatch, next section) instead of shape-special-cased
  executors.
- **Rule-based optimization as pure tree rewrites** over `okapi-trees` (`BottomUp`/`TopDown`
  transformers, `okapi-trees/.../TreeTransformer.scala:47-76`): label-scan elimination for
  nonexistent labels, cartesian→value-join, pattern-scan substitution
  (`LogicalOptimizer.scala:49-53`) — none of which touch execution code.
- **Plan-level testability**: planner stages had dedicated plan-shape test suites (e.g. the
  702-line `FlatPlannerTest` visible in `4c26d9282`'s diffstat) independent of execution.
- **An invariant choke point** at operator granularity (below).

The counter-lesson is just as important: they originally had **four** in-house stages (logical →
*flat* → physical) and deleted one. "Flat planning" (introduced `e31a49d84`, 2017-04-05) was
removed and physical planning generalized to the backend-agnostic relational layer in
`4c26d9282` (2018-07-03, "Remove flat planning and replace physical with relational planning";
final deletion `235c60d9f`, 2018-07-11). The equilibrium was *one well-chosen middle layer per
job*, not maximal layering. For Gryphon (currently zero middle layers): the peer's regret was
never "we had an IR"; it was "we had a redundant one."

### Dispatch shape

**One uniform lowering per stage, exhaustive-match, fail-closed.** The entire logical→relational
lowering is a single `process` pattern-match over logical operators
(`RelationalPlanner.scala:59-325`); anything unmatched throws
`NotImplementedException("Physical planning of operator …")` (`RelationalPlanner.scala:322-323`),
and the logical planner does the same for blocks (`LogicalPlanner.scala:171-175, 234-238`).
Complex constructs (var-length expand, CONSTRUCT graphs) are *subroutines called from the single
match* (`RelationalPlanner.scala:224-279`) that compose the **same primitive operator set**
(`Join`, `Filter`, `Select`, `Distinct`, `TabularUnionAll`, `Add/AddInto`, `Drop` —
`okapi-relational/.../operators/RelationalOperator.scala`), not parallel executors. There is no
"scan path vs hop path vs advanced path" split: a node scan, a 3-hop pattern, an OPTIONAL MATCH
and an EXISTS subquery all end in the same seven-ish table primitives.

**Their history has Gryphon's exact refactor, twice:**

- `4c26d9282` — the stage collapse (above).
- `e2aaae155` (2019-03-07) — *"Remove special case in optional match planner. We need to perform
  the left outer join in all cases. If not, the operator produces an empty result if the right
  hand side is empty. This is wrong in the case of optional match."* A shortcut branch
  (`if (lhs.fields.isEmpty) rhsOp`) silently produced wrong results on an edge shape; the fix
  **deleted the branch** so every OPTIONAL MATCH takes the one LOJ path — and simultaneously
  *removed* a `require` that had blocked the uniform path (empty join exprs), i.e. the special
  case existed partly to route around an over-restrictive invariant. Sister fixes: `b7e8ac410`
  ("Fix optional match with empty input"), PR #858 ("Always use left outer join in OPTIONAL
  MATCH"). This is the envelope-WHERE story with different nouns: special-case path + silent
  wrong answer → collapse to the general machinery.

### Invariant enforcement — one structural choke point (several, actually)

- **Header/data conformance on every operator materialization.** The abstract base class's
  `table` accessor — the only way any operator yields data — verifies on each materialization:
  no duplicate physical columns; every header column exists in the data; no undeclared data
  columns; and per-expression Cypher-type vs column-type conformance
  (`RelationalOperator.scala:70-137`). A plan node whose output drifts from its declared header
  *cannot return a table*. This is "someone forgot to apply X on this path" made loud at the
  first operator boundary after the mistake, for every path, forever.
- **`RecordHeader` — the single expression→column registry.** All column identity flows through
  one immutable map; `header.column(expr)` **throws** on an unregistered expression
  (`okapi-relational/.../table/RecordHeader.scala:91-100`) — a predicate over an unbound
  variable cannot silently resolve to nothing. Conflict-free naming is centralized
  (`newConflictFreeColumnName`, `RecordHeader.scala:317-332`).
- **Join preconditions as constructor `require`s**: overlapping expressions or colliding column
  names refuse to construct (`RelationalOperator.scala:473-480`), backed by
  `withDisjointColumnNames` auto-renaming at the planner (`RelationalPlanner.scala:683-703`) and
  a second `require` at the Spark boundary (`safeJoin`, `SparkTable.scala:404-410`).
  `TabularUnionAll` refuses mismatched column sets (`RelationalOperator.scala:520-532`);
  `unionAll` type-checks per column (`SparkTable.scala:181-196`); `alignColumnNames` `require`s
  header containment (`RelationalPlanner.scala:715-724`); `alignExpressions` ends in an
  assert-equal on the full expression set (`RelationalPlanner.scala:655-670`).
- **Parameterization**: literals are auto-extracted into parameters by the front-end before IR
  building (`CypherParser.scala:73-100`) — queries are parameterized *by construction*, not by
  per-path discipline.
- **Null propagation — one wrapper, declared per expression type.** `nullSafeConversion`
  (`morpheus-spark-cypher/.../SparkSQLExprMapper.scala:73-102`) wraps *every* expression
  lowering: if `expr.nullInNullOut` (default **true** on the `Expr` base,
  `okapi-ir/.../expr/Expr.scala:77`), null children short-circuit the parent to null via a
  generated `CASE WHEN`. Non-strict operators **opt out explicitly** — `Ands`/`Ors`
  (`Expr.scala:294,321`, so SQL's own 3VL AND/OR applies), `Coalesce` (`:952`), `Explode`
  (`:964`), all `Aggregator`s (`:1227`). Null semantics are *metadata on the expression algebra*
  enforced at one choke point, not per-operator vigilance. (Centralized in `2ca516814` "Move
  `nullSafeConversion` to ExprMapper"; documented `3be9f651f`.)

**Where does fail-closed live?** Three structural layers: unmatched plan shapes throw at the
lowering match (`RelationalPlanner.scala:322`); unregistered expressions throw at header lookup
(`RecordHeader.scala:91-100`); header/data drift throws at operator materialization
(`RelationalOperator.scala:70-137`). A path that "accepts input it silently ignores" is close to
inexpressible: input is either an operator in the plan tree (then its header must be honored) or
it never entered the tree (then the exhaustive match already threw). The one silent-wrong-answer
executor bug we found in their history (`e2aaae155`) lived in exactly the kind of place these
guards don't reach — a *planner shortcut around the operator tree* — reinforcing the rule:
shortcuts, not operators, are where silence hides.

### The join/traversal lowering

- **Single hop (`Expand`)**: rel-scan table joined twice — `src ⋈ rel ⋈ tgt` via `StartNode`/
  `EndNode` id columns, `InnerJoin` (`RelationalPlanner.scala:137-186`). Undirected = union of
  both orientations, with a `Not(Equals(startNode, endNode))` filter on the reversed leg to
  avoid double-counting loops (`RelationalPlanner.scala:171-185`). Cyclic/bound-both-ends
  (`ExpandInto`) joins on both endpoints simultaneously (`:188-222`).
- **k-hop**: no special k-hop machinery — the logical planner ties pattern connections together
  by repeated `Expand` over a solved-set fixpoint (`planExpansions`,
  `LogicalPlanner.scala:468-592`); each hop is another rel-scan join. Predicates are planned
  per-component as soon as their variables are in scope (`planMatchPattern`,
  `LogicalPlanner.scala:394-417`).
- **Variable-length (`BoundedVarLengthExpand`)**: unrolled iterative join — hop *i* joins an
  aliased rel-scan (`ListSegment(i, list)`), applies a per-iteration **relationship-isomorphism
  filter** (`Ands(Not(Equals(prevEdge_j, newEdge)))`,
  `VarLengthExpandPlanner.scala:207-208, 96-101, 148-150`), then paths of each admitted length
  are **null-padded to a common target header and unioned by name**
  (`finalize`, `VarLengthExpandPlanner.scala:163-197`), with `lower == 0` emitting a
  copy-source-to-target zero-hop table (`:169-173`) and `upper < lower` short-circuiting to
  `EmptyRecords` at the logical layer (`LogicalPlanner.scala:517-523`, fix `8d457423e`).
  Upper bound must be finite — unbounded `*` is not supported (TCK-blacklisted, "Handling
  unbounded variable length match", `morpheus-tck/src/test/resources/failing_blacklist`).
  This is the reference shape for Gryphon's E1 seam — and its bug cluster is the E1 hotspot
  forecast (§Lens H).
- **OPTIONAL MATCH**: drop rhs copies of shared columns → rename rhs join keys → **left outer
  join** — always, no special case (`planOptional`, `RelationalPlanner.scala:366-406`; the
  `e2aaae155` lesson). Requires Spark cross-join enablement when the LOJ degenerates to
  join-on-`lit(true)` (`SparkTable.scala:214-221`).
- **EXISTS pattern predicate**: rhs → drop non-join columns → **`Distinct` on the join keys
  *before* a left outer join** → project `IsNotNull(rhsKey)` into the predicate field
  (`RelationalPlanner.scala:283-309`). The subquery can never multiply lhs rows because it is
  deduplicated to at most one row per join key *by construction* — their canonical
  anti-row-inflation shape.
- **Aggregation**: `isolateAggregation` front-end rewrite splits aggregates from scalar
  projections *before IR* (`CypherParser.scala:90`), then one `Aggregate` operator with explicit
  grouping vars (`RelationalOperator.scala:372-387`) lowered to `groupBy().agg()`
  (`SparkTable.scala:152-179`); grouping by an element var expands to all its owned columns
  (`SparkTable.scala:159-163`). IR-level fix for DISTINCT-under-aggregation: `abb598979`.

### Predicate placement

`WHERE` becomes `Filter` operators placed by the logical planner as early as each predicate's
variables are solved — per pattern component (`LogicalPlanner.scala:394-417`), with a dedicated
AST-level label-pushdown rewriter (`b1862863d`, cases for NOT/XOR `3d61d8566`, complex-predicate
test `c804d136d`). Filters lower to a single `df.where(expr)` (`SparkTable.scala:87-91`); further
pushdown is delegated to Catalyst. Documented predicate-scoping bug: **`25990d920` "Fix
connection-scope after WITH"** — after a `WITH`, patterns whose connections were entirely
carried by the projected scope were mishandled in `IRBuilder`/`IRBuilderContext` (scope
registries, not executor paths — the same "scoping metadata, not lowering arithmetic" locus as
Gryphon's union-WHERE-scoping oracle bug). And the planner-shortcut drop of `e2aaae155` (above)
is their envelope-WHERE-shaped scar.

### NULL / 3VL

Split across exactly three mechanisms, each at a choke point:

1. **Strict functions/operators**: `nullInNullOut` metadata + the `nullSafeConversion` `CASE
   WHEN` wrapper (anchors above) — null-in-null-out without per-operator code.
2. **Logical connectives**: opt out of (1) and defer to the substrate's 3VL `AND`/`OR`
   (`SparkSQLExprMapper.scala:174-175` folds `&&`/`||`; Catalyst booleans are SQL-3VL).
3. **Statically-null predicates**: a filter whose expression *types* to `CTNull` short-circuits
   the whole operator to an empty table at the planner (`RelationalPlanner.scala:416-426`) —
   the "WHERE null returns no rows" 2VL boundary decided at plan time, structurally analogous
   to Gryphon's null-literal→FALSE rule (`doc-dev-gryphon-vs-cypher.md` Ledger B).

Type-driven null folding also happens in the typer: `childNullPropagatesTo`
(`Expr.scala:78-86`) collapses expressions with `CTNull` children to `CTNull` statically, and
`f8653b97c` optimized lowering to skip recursion for `CTNull`-typed subtrees. Their null bug
tail was long anyway (~95 commits mention null): `91b19cf3f` (functions over null args),
`8d2706904` (Explode rejected *nullable lists* — the strict/non-strict boundary drawn wrong),
`1e2d8e105` (typing of `Add` with nullable input), `1e8e1b9d4` (`Array(null)` → Neo4j write).
Lesson: even with the choke point, the *classification* of each operator (strict vs not) is
itself a bug surface — it wants a table-driven test (Gryphon's TLP rung already probes exactly
this; the `NullTests` suite shape — one `returnsNull()` line per function,
`morpheus-testing/.../acceptance/NullTests.scala:33-90` — is worth mining as a cheap exhaustive
null-matrix scenario generator).

### Type handling

Schema-as-typer, coercion-averse — with one instructive retreat. Property types are inferred
from the graph schema per label combination (`ExpressionConverter` property cases, visible in
`376b28e11`'s diff); a full signature-based type checker rejects inapplicable operand types
(`NoSuitableSignatureForExpr`; built in the `657430380` … `2d064781d` cluster). But **cross-type
*comparisons* were deliberately weakened from rejection to Cypher-conformant null-out** in
`13da53945` ("Allow comparison of unequal types — leads to null instead of an error to be
thrown"), test diff showing `a[NoSuitableSignatureForExpr] shouldBe thrownBy(...)` becoming
`result.records… shouldBe empty`. Same story for `IN` over incompatible types → `NULL_LIT`
(`SparkSQLExprMapper.scala:218-223`; special-case removed `376b28e11`, then its *typing* special
case reinstated `d580765c1` because the generalized propagation "didnt seem any better").
The pressure to coerce/null-out came **only from Cypher-TCK conformance**, which Gryphon
explicitly does not claim (`doc-dev-gryphon-vs-cypher.md` §TCK) — a direct external validation
of the type-strictness divergence (Ledger B, `req-grid-traversal-lang-type-strictness`) as a
*choice with a named cost*, not an accident. Numeric widening etc. is otherwise delegated to
Spark casts (`SparkSQLExprMapper.scala:355-358`).

### Row-inflation defenses

- EXISTS = Distinct-before-LOJ + IsNotNull flag (anchor above) — inflation prevented by
  construction, not by post-hoc dedup.
- Var-length per-iteration edge-isomorphism filter (`VarLengthExpandPlanner.scala:207-208`)
  bounds path multiplicity per Cypher's relationship-uniqueness semantics.
- Undirected expand filters self-loops out of the reversed leg
  (`RelationalPlanner.scala:177-181`).
- `Distinct` over an element var expands to **all** columns owned by that var
  (`RelationalOperator.scala:361-370`) — no accidental id-only dedup.
- OPTIONAL MATCH pre-drops rhs duplicates of shared columns (`RelationalPlanner.scala:384-395`).
- Grouping keys likewise expand to owned-column sets (`SparkTable.scala:159-163`).

What they did *not* defend against: the substrate lying. `SPARK-26572` (join on a distinct
column derived with `monotonically_increasing_id` produces wrong output) forced a groupBy-based
`distinct` **workaround in their own table layer** (`3285975a5`, fixed-up `f8841a3b8`/PR #749,
column-rename interaction `0f596df76`, removed after the Spark fix in `4b37e3c3b`); `4b965e321`
("Upgrade to Spark 2.4.3 fixes #889") is a second substrate-bug fix shipped as a version bump.
See §Lens H for the lesson.

### Determinism / ordering

Thin. `ORDER BY` lowers to `df.orderBy` with asc/desc only — **no explicit NULLS FIRST/LAST
policy anywhere** (no `nulls_first/asc_nulls` hits outside id-generation comments;
`SparkTable.scala:122-133`); null placement is whatever Spark defaults to. No
LIMIT-without-ORDER-BY guard. Element ids for constructed/imported data ride
`monotonically_increasing_id` (`MorpheusFunctions.scala:74-83`,
`SparkSQLExprMapper.scala:282`) — partition-dependent and nondeterministic across runs, which is
precisely the ingredient that made SPARK-26572 bite and later forced `6f1bbd484` ("Fix PGDS id
generation" — rel ids moved *off* property-hash *onto* monotonic ids for uniqueness, PR #929).
Gryphon's sorted-`pk__in` byte-stable SQL discipline
(`req-grid-traversal-exec-sql-capture-3`) has no analog here — a genuine credit.

### ★ Transferable to Gryphon (Lens E)

1. **The invariant-bearing middle layer is real and affordable** — but the peer equilibrium is
   *one* layer whose operators carry their own output contract (header) and verify it at
   materialization. Not four layers (they deleted flat planning), and not zero (every fail-closed
   property above hangs off the operator/header abstraction).
2. **A single expression→column binding registry with throwing lookup** is the load-bearing
   heart of that layer — more valuable than the optimizer it enables.
3. **Null-in-null-out as declarative per-operator metadata + one wrapper** replaces N scattered
   null branches with one auditable table.
4. **Distinct-the-subquery-side-before-joining** as the stated lowering rule for any
   semi-join-shaped construct (EXISTS/NOT EXISTS and future ones).
5. **The var-length reference shape** (per-iteration isomorphism filter; null-pad + union-by-name
   across lengths; explicit zero-hop and empty-interval cases) plus its four-bug cluster =
   a pre-written E1 test plan.
6. **Special cases live in planners, not operators — and that's where their silent bug was.**
   Any Gryphon shortcut that skips the general machinery for an "easy" shape is the highest-risk
   line in the file.

## Lens T — Testing

Deliberately lighter read (protocol guardrail 2); scored against
`doc-gryphon-testing-philosophy.md` §The frontier.

- **Oracle model: the TCK as executable spec — no independent implementation oracle.**
  Conformance = openCypher TCK run live (`morpheus-tck/.../TckSparkCypherTest.scala`), plus
  hand-authored acceptance suites (22 files, `morpheus-testing/.../acceptance/`). Nothing like
  Gryphon's zero-shared-code model oracle exists; correctness claims are
  self-consistent + TCK-anchored. Gryphon's differential rung is *ahead* of this peer.
- **The two-sided blacklist is their best testing idea.** Four blacklists (failing / temporal /
  wont_fix / failure_reporting; 236/919/192/118 lines,
  `morpheus-tck/src/test/resources/`), and — the teeth — **every blacklisted scenario is
  executed and must FAIL**: `Success(_) => throw … "A blacklisted scenario actually worked"`
  (`TckSparkCypherTest.scala:88-101`). A fixed bug cannot silently stay blacklisted; the
  whitelist ratchets forward (`2168e4846` "Whitelist fixed TCK tests", `b448994fa`,
  `6f47ff87a`). A coverage test computes per-feature white/black percentages
  (`TckSparkCypherTest.scala:104-125`).
- **Answer-vs-artifact posture: answers, as bags.** Acceptance assertions are
  `result.records.toMaps` against `Bag(CypherMap(...))` (e.g. `NullTests.scala:38-45`) —
  multiset answer comparison, never SQL/plan text. Plan-shape tests existed per stage
  historically (`FlatPlannerTest`, 702 lines at deletion, `4c26d9282`) — plan-level testability
  is an IR dividend Gryphon would gain, though it is artifact-checking and they knew to keep
  answer tests primary.
- **Differential/metamorphic/fuzzing: none.** No TLP/NoREC/PQS, no query fuzzer, no shrinking.
  Property-based testing (scalatest `GeneratorDrivenPropertyChecks`) is confined to unit-level
  value/type laws (`okapi-api/.../CypherTypesTest.scala`, `MorpheusLiteralTests.scala`,
  `SparkTableTest.scala`). No mutation testing found. Gryphon's fuzz/TLP rungs have no
  counterpart here — nothing to import, and a credit.
- **Test generation**: `AcceptanceTestGenerator` (`okapi-tck/.../AcceptanceTestGenerator.scala:36-101`)
  emits Scala test classes from TCK feature files — codegen-from-corpus, the mechanical cousin
  of Gridkin's mine-not-port discipline (they port; we deliberately don't —
  the Gridkin TCK-inspiration requirement, `spec-gridkin-v0.md` in the
  gryphon_playground plugin repo).
- **Substrate regression capture**: when Spark itself was wrong (SPARK-26572) they pinned the
  workaround with dedicated tests at their own boundary (`3285975a5` test diff:
  `distinct on single column` / `on multiple columns`) — test the substrate's contract where
  you depend on it, not just your own code.

### ★ Transferable to Gryphon (Lens T)

- **Must-fail semantics for every known-broken/xfail list** (the blacklist teeth) — cheap,
  authoring-independent, and it converts "known broken" from a comment into a ratchet.
  Candidate surfaces: the model-oracle skip list (`OracleUnmodeled` skips), fuzz-campaign
  known-issue lists, and the dev-validation known-broken manifest.
- **A generated null-matrix suite** (one scenario per operator × null-position, from the
  operator inventory) mined from the `NullTests` shape — feeds the 2VL/3VL boundary that is
  already a Gryphon hotspot.
- **Substrate-contract pin tests** for the specific ORM/Postgres behaviors the lowering leans
  on (e.g. `IN`-list null semantics, `NULLS FIRST` defaults) — the peer's SPARK-26572 scar says
  "trusted substrate" is a probability, not an axiom; Gryphon's model oracle already covers the
  answer end, a contract pin covers the diagnosis end.

## Lens H — History

Scale: 4,651 commits over ~3.5 active years (2016-08 → 2019-12 substantive; archived-in-place
since), ~15 meaningful contributors, heavily Neo4j-employed (shortlog above). Reasoning lives in
PR descriptions and commit bodies (e.g. `e2aaae155`, `d580765c1` record *why*, not just what);
no ADR/RFC directory — `doc/dev/` holds only scratch (`planner structure.sc`).

### Bug taxonomy (keyword-clustered commit counts; representatives read in full)

| Class | ~Commits touching | Representative fixes (read) | Gryphon mapping |
| --- | ---: | --- | --- |
| Header/column identity & alignment | 314 mention header/column (noisiest bucket; includes refactors) | `0f596df76` distinct-vs-rename, `37c69c99c` align-before-union, `853015872`, `928184c1a` | **Predicted hotspot** for any Gryphon IR: column-identity plumbing is where a header-based layer pays *and* bleeds; the RecordHeader choke point is why the bleeding stayed loud instead of silent |
| Null semantics | 95 | `8d2706904` Explode-nullable, `91b19cf3f`, `1e2d8e105`, `2ca516814` centralization | Maps to gryphon-findings-ledger null-boundary hotspot; their fix trajectory (scattered → metadata + one wrapper) is the playbook |
| Typing / signatures | 45 | `657430380`, `f38022107`, `b66eb7fb0`, `d580765c1` reintroduced-IN-special | Gryphon's schema-as-oracle rejects instead — smaller surface, same locus (type inference feeding lowering) |
| Var-length expand | 36 | `acd7a6750` shorter-path alignment, `5e7228224` segment nullability, `e7c89205d` lower-bound-0, `0b370c6ad` expand-into, `8d457423e` empty interval | **The E1 forecast**: length-0, length-heterogeneous union alignment, per-segment nullability, bound-into-both-ends — write these Gridkin scenarios before writing the executor |
| OPTIONAL MATCH | 34 | `e2aaae155` special-case removal, `b7e8ac410` empty-input, `3c4b982a3`/#368 join-field computation | Gryphon's v0 OPTIONAL MATCH scoreboard + oracle already cover the answer side; the lesson is the *shortcut-branch* shape |
| Scoping across WITH | (few, deep) | `25990d920` connection-scope after WITH | Direct forecast for Gryphon's future `WITH` (wishlist F1): scope-registry hand-off, not lowering, is where it will break |
| Substrate wrong-answers | (few, severe) | `3285975a5`/`4b37e3c3b` SPARK-26572, `4b965e321` #889, `6f1bbd484` PGDS ids | Credit + action: Postgres bet is materially safer than Catalyst-under-churn, and the model oracle would catch it; add contract pins (Lens T) |
| TCK ratchet churn | 114 mention tck/blacklist | `2168e4846`, `376b28e11` | Evidence the two-sided blacklist was actively used as the promote gate |

### Turning-point commits

- **`4c26d9282` + `235c60d9f` (2018-07)** — the pipeline collapse: flat planning deleted,
  physical planner generalized to backend-agnostic relational planning. The "we unified the
  executor" refactor the protocol asks about, in the *reductive* direction.
- **`e2aaae155` (2019-03)** — special-case deletion after a silent wrong answer; their
  single-hop-collapse moment.
- **`2ca516814` / `3be9f651f` (2019)** — null handling centralized into `nullSafeConversion` +
  `nullInNullOut` documented; the null-choke-point birth.
- **`657430380` → `d9e6458ed` → `d580765c1` (2019)** — the type-checker rebuild arc, ending in
  an honest "the generalization didn't beat the special case" reversal.
- **`b1862863d` (2019)** — label-filter pushdown as an AST rewriter: optimization added as a
  pure rewrite rule, zero executor change — the IR dividend in action.

### Lifecycle lesson

Morpheus is a **well-architected dead project**. The archived state (`4f6398ee7`, NOTICE) with
Neo4j explicitly disclaiming it, despite the cleanest layering in the study class, says
architecture doesn't buy survival — a sponsor/demand does (protocol already carries this via
RedisGraph; Morpheus is the same lesson with *good* architecture, sharpening it: the layering
made the codebase *legible enough to abandon safely* — stage boundaries meant TCK conformance
was measurable at the end, per-feature). Second lifecycle note: it never reached 1.0 and its
deepest remaining blacklist clusters (unbounded var-length, mixed var-length chains,
`temporal_blacklist` at 919 lines) show which Cypher corners stay expensive even with three
IRs — corners Gryphon's deliberate-subset ledger (Ledger C) mostly declines.

### ★ Predicted Gryphon hotspots (from this peer's bleeding)

1. **E1 var-length lowering** — their #1 executor-bug cluster; import their four bug shapes as
   pre-landed rejection/result scenarios.
2. **`WITH` scope hand-off** (when F1 lands) — scope registries, not SQL emission.
3. **Column/alias identity under any future IR** — adopt the throwing-registry pattern on day
   one or inherit their 300-commit alignment tail without their guardrails.
4. **Null-strictness classification per operator** — every new Gryphon operator needs an
   explicit strict/non-strict call; their Explode bug is what a wrong default looks like.

## Net read

**Biggest thing to steal:** the invariant-bearing relational-operator layer in its *minimal*
form — a single expression→column registry with throwing lookup, operators that declare an
output header and verify it at materialization, and one exhaustive lowering match that throws
on anything unhandled. That combination is what makes "a path silently ignores its input"
nearly inexpressible, and it is exactly the medicine Gryphon's remaining multi-path dispatch
(type-scan / bare-scan / envelope-collection / `_compute_rows` / OPTIONAL / NOT-EXISTS) wants.
**Biggest thing to avoid:** planner shortcuts around the general machinery (`e2aaae155`) and
over-layering (they deleted a whole planning stage; one middle layer, not three); also their
determinism posture — no null-ordering policy and nondeterministic id generation — which
compounded a substrate bug into silent wrong answers. **Credit:** Gryphon already out-tests this
peer (model oracle, fuzzer, TLP vs their TCK-only self-consistency); its type-strictness
divergence is validated by `13da53945` — the only force that pushed Morpheus into
coercion-to-null was Cypher-conformance Gryphon doesn't claim; its read-only bet forecloses the
entire CONSTRUCT/write-path bug surface; and byte-stable captured SQL has no Morpheus analog.
