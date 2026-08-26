---
audience: [llm, developer]
covers:
  - ../../tap_grid/specs/spec-grid-traversal-language.md
  - ../../tap_grid/specs/spec-grid-traversal-execution.md
  - ../../tap_grid/specs/spec-grid-gryphon-multihop-aggregation.md
  - ../../plugins/gryphon_playground/specs/spec-gridkin-v0.md
  - doc-gryphon-comparative-eval-protocol.md
assumes:
  - Reader knows what Gryphon is (a Cypher-subset language compiling an AST to Django-ORM QuerySets → SQL over TAP's Entity/Edge spine, read-only by construction)
  - Reader has read doc-gryphon-comparative-eval-protocol.md (the study protocol, the three lenses, the §5.2 opportunity shape) and doc-gryphon-testing-philosophy.md (the standing test ladder — do not re-import rungs it already has)
  - Reader has skimmed the per-system dossiers under comparanda/ (dossier-*.md), which carry the load-bearing anchors this synthesis compresses
provides: |
  The cross-system synthesis of the Gryphon comparative study: the finalized roster
  (deep / triage / paper-only), a technique/architecture matrix placing GRYPHON TODAY
  against ten peer Cypher-over-relational implementations, per-lens narrative reads
  centered on the bottom-turtle question (should executor.py grow a logical-plan IR,
  collapse more dispatch paths, and move invariant-enforcement to one choke point),
  a ranked opportunities backlog in the §5.2 record shape, and the credits ledger
  (bug classes peers bled on that Gryphon's architecture already forecloses).
  The dossiers are the evidence; this is the payoff that turns them into buildable work.
---

# Gryphon Comparative Findings — What Ten Cypher-over-Relational Peers Teach Our Executor

> Synthesis output of `doc-gryphon-comparative-eval-protocol.md` (§4.3, §5). Study date:
> 2026-07-04. Every load-bearing claim is anchored to a dossier under `comparanda/`, which
> in turn anchors it to a SHA/file:line/issue/paper. IP posture (§6): ideas mined, no code
> copied; every opportunity's `port_or_mine` is `mine`. Lens E (executor internal
> structure) is primary and carries the ranking weight, per protocol §1.1.

## 1. The finalized roster

Ten systems entered **deep** study, each with a full three-lens dossier. Two roster
candidates stayed **paper-only** and one lineage predecessor folded into a deep dossier
as **triage**. Every exclusion carries a reason (house rule; protocol §2.2).

### Deep (dossier written, all three lenses, anchored)

Ordered by relational-lowering relevance — the purest Cypher→relational cousins first, so
their lessons frame the rest.

| System | Lowers Cypher(-ish) to | License | Why deep |
| --- | --- | --- | --- |
| **openCypherTranspiler** (Microsoft) | **SQL text** (T-SQL), via a 5-operator relational-algebra logical plan | MIT | The purest Cypher→SQL transpiler *with* a real logical-plan IR; read-only by construction like Gryphon. `dossier-opencyphertranspiler.md` |
| **DuckPGQ** | DuckDB relational (AST→AST macro into one SQL subquery) | MIT | SQL/PGQ over a columnar engine; nearest living "compile-to-relational" cousin; borrows the host's IR entirely. `dossier-duckpgq.md` |
| **AgensGraph** | PostgreSQL `Query` trees (kernel fork) | Apache/PG | Deepest lowering: Cypher fused into PG's own planner; 10-year fix stream. `dossier-agensgraph.md` |
| **Apache AGE** | PostgreSQL `Query` trees (extension) | Apache-2.0 | The "bolt Cypher onto PG" bet, as an extension; tests the kludge instinct against 7 years of code. `dossier-apache-age.md` |
| **Morpheus / CAPS** | Spark relational (3 in-house IRs → DataFrames) | Apache-2.0 | openCypher's own layered-IR engine — the existence proof Gryphon's spec anticipates. `dossier-morpheus.md` |
| **Cytosm** | **SQL text** (relational IR, ~14 passes) | Apache-2.0 | Pattern-for-pattern academic cousin; the *control group* for an IR **without** invariant enforcement. `dossier-cytosm.md` |
| **cyp2sql** ("Reagan") | **SQL text** (no IR; dispatch by substring) | Apache-2.0 | The natural experiment: same bet, *no* logical IR — shows the bug classes our ladder foreclosed, uncontained. `dossier-cyp2sql.md` |
| **GraphFrames** | Spark DataFrame joins (motif→join chain) | Apache-2.0 | Purest living relational-lowering bet over two base tables; freshest bug data (2024+ revival). `dossier-graphframes.md` |
| **Kùzu** | native columnar (full multi-IR compiler) | MIT | The **method mine**: best-engineered open-source Cypher compiler pipeline; WCOJ + factorization. `dossier-kuzu.md` |
| **RedisGraph** | GraphBLAS sparse-matrix linear algebra | SSPL (EOL) | The **foil**: the opposite architectural bet, read birth-to-EOL for lifecycle lessons. `dossier-redisgraph.md` |

### Triage (folded, one-line reason)

- **GraphflowDB** — Kùzu's academic predecessor. *Not separately studied:* it is the same
  lineage as Kùzu (dossier notes the `graphflowdb/` PR prefixes); reading Kùzu at HEAD
  captures the matured design. Subsumed into `dossier-kuzu.md`.

### Paper-only (no code read, reason recorded)

- **Memgraph** — native C++ engine, **BSL**-licensed; no relational lowering to mine, and
  the IP posture (§6) says lean on papers/docs first for restrictive licenses. No
  translation-fidelity surface that a source read would add over the doc-level semantics.
  *Excluded from deep; not a relational cousin.*
- **SQLGraph** (IBM Research, SIGMOD'15) — a relational-lowering **design** with no
  expected public code. Cited as a paper reference for the relational property-graph store
  idea; nothing to clone.
- **Oracle PGX/PGQL, AWS Neptune, PuppyGraph** — proprietary; the protocol admits them as
  paper/doc references only, never code. None reached a dossier; recorded here so a future
  reader knows the omission is a licence/availability call, not an oversight.

**No deep-roster system failed to produce a dossier.** The one contrast/foil (RedisGraph)
and the one method-mine (Kùzu) were both completed despite non-relational architectures,
because the protocol admits them for lifecycle and method respectively.

---

## 2. Technique / architecture matrix — who does what, where we sit

Columns: **OCT** openCypherTranspiler · **DPG** DuckPGQ · **AGG** AgensGraph · **AGE**
Apache AGE · **MPH** Morpheus · **CYT** Cytosm · **C2S** cyp2sql · **GF** GraphFrames ·
**KUZ** Kùzu · **RG** RedisGraph · **GRY** Gryphon today. Cells are terse; the dossiers
carry the anchors. (Table scrolls horizontally.)

<div style="overflow-x:auto">

| Technique / decision | OCT | DPG | AGG | AGE | MPH | CYT | C2S | GF | KUZ | RG | **GRY** |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Own logical-plan IR** | Yes (5-op algebra) | No (host's) | No (PG `Query`) | No (PG `Query`) | Yes ×2 (logical+relational) | Yes (SQL-tree, ~14 passes) | No (record only) | No (host Catalyst) | Yes (50 ops, full) | 3 specialized IRs | **No — AST→ORM directly** |
| **Dispatch shape** | Born unified | Unified relational lane | Uniform core + special ring | Uniform top, special interiors + 2nd write lane | Unified, exhaustive-match | Uniform pipeline; variation exiled to macro layer | Many special paths (substring routing) | Uniform fold + bolt-on wrappers | Uniform, normalized at bind | One op-tree; specialization = rewrites | **Multi-path: type-scan / bare-scan / single-hop(collapsed) / advanced / NOT-EXISTS / OPTIONAL** |
| **Predicate placement** | Selection op node | One conjunction sink | Qual in owning MATCH `Query` | Single jointree qual funnel | Filter op placed when vars solved | `MoveRestriction` pass (mutating) | Folded into node prop-bag (destructive) | Not owned (post-`find()` filter) | Index-tracked conservation ledger | One generic placement algorithm | **`_apply_predicate_to_qs`/chain (single-hop); other paths vary** |
| **Predicate CONSERVATION (drop = inexpressible?)** | ~Yes (selection always in DAG) | ~Yes (no per-path WHERE) | No (join-drop opt bled) | **No** (per-path drops, 2023+2026) | ~Yes (throws on unhandled) | **No** (drops if pass skipped) | **No** (silent 6-site drop) | N/A (owns none) | **Yes** (conserve-or-throw) | **Yes** (place-or-error) | **Partial — single-hop apply-or-reject; not global** |
| **Invariant CHOKE POINT** | Plan-build/bind boundary | Host binder | Host pipeline (uniform path) | Split: some central, null per-path | Operator header + throwing registry | **None structural** (mutable pass state) | **None** | Parse `assertValidPatterns` only | Per-op declared prereqs at append | Validation visitor + placement algo | **Chain seam (single-hop); scan/advanced re-assert** |
| **NULL / 3VL lowering** | Shrink at parse, defer to SQL 3VL (1 `CASE` bug) | None (surface = SQL) | Map to SQL NULL; still bled 10 yrs at HEAD | 3-regime accident (dual null) | 1 wrapper + `nullInNullOut` metadata | **Total punt, unexamined** | **Absent; nulls defined out of oracle** | Delegated to Spark | Kleene 3VL, 1 truth-table artifact | Ternary `FT_Result`; 4.5-yr 2VL collapse | **Specified 2VL-literal / 3VL-field split; distributed across `_predicate_to_q`; TLP-probed** |
| **Type handling** | Reject (exhaustive tables) | Coerce (host) | Coerce via jsonb (largest bug class) | Coerce (walking back to typed lanes 2026) | Reject→null-out (TCK pressure) | Incomplete checker (coerce) | Infer-from-data + quote-all (coerce) | Host casts | Reject (allowlist at bind) | Coerce (DISJOINT-tolerant) | **Reject — schema-as-oracle strictness** |
| **Row-inflation / edge-uniqueness** | Auto edge-uniqueness plan rewrite | None (multiset accepted) | `addQualUniqueEdges` structural | `_ag_enforce_edge_uniqueness` qual | Per-iter isomorphism + Distinct-before-join | COUNT-over-UNION (incomplete) | Node-ineq chain ("EXPERIMENTAL") | None by policy (homomorphic) | Factorized multiplicity + reducer | Boolean-semiring dedup + IR normalize | **None structural — inflation recurs in ledger** |
| **Var-length lowering** | Rejected | Escape lane (CSR+UDF; #67 suspect) | Custom `GraphVLE` node (2 rewrites) | Out-of-plan `vle` + global cache (5-bug family) | Unrolled iterative join + isomorphism | String macro-expand → UNION | 2 rival strategies (disagree on direction) | String-expand → union of fixed | `RECURSIVE_EXTEND` + semi-masks | DFS `CondVarLenTraverse` | **`*1..3` PARSES but executor REJECTS (E1 unbuilt, fail-closed); oracle also skips; rung-4 CTE anticipated** |
| **Desugar locus** | Parse-time rejects | Bind-replace macro | Transform-time | Transform-time | Front-end rewrites | **On strings (mistake, self-flagged)** | **On strings (substring)** | **On text (regex) — bug factory** | **Bind-time AST normalize** | AST rewriters | **AST (grammar→frozen AST)** |
| **Parameterization** | **None** (string-interp) | Host binds | PG binds | PG binds | Auto-extract to params | **None** (unescaped concat) | **None** (quote-strip) | N/A (no values) | `parameterMap` at bind | Module args | **ORM bind params (invariant)** |
| **Determinism / ordering** | Weak (subquery ORDER BY) | Inherits SQL | jsonb total order | Plan-order (churny tests) | No NULLS policy; nondet ids | Dropped on wide/UNION | Nondet pagination | Patchwork | Null-flag key byte | One total-order comparator | **Sorted `pk__in` → byte-stable SQL capture** |
| **Worst-case-optimal join** | No | No | No | No | No | No | No | No | **Yes (INTERSECT/WCOJ)** | No (matrix algebra) | **No (not a demand)** |
| **Independent reference oracle** | **Yes (Neo4j diff)** | No | No | No | No (TCK) | No | Count-proxy (false-green) | Algorithm-only (LDBC/GraphX diff) | No | No | **Yes — zero-shared-code model oracle** |
| **Metamorphic / differential** | Neo4j diff | No | No | No | No | No | Row-count proxy | Complement-graph negation oracle | No | **Pattern-direction reversal** | **TLP (2VL/3VL); property fuzzer** |
| **Fuzzing** | No | No | No | No | No | No | No | No | Wished (#2485, unbuilt) | Grammar fuzz (crash-only) | **Differential seeded fuzzer + replay** |

</div>

**How to read the last column.** Gryphon leads the field on four rows that peers paid for
in blood — parameterization, deterministic capture, type-strictness rejection, and the
independent oracle + differential-fuzz ladder — and sits *behind* the best peers on four
structural rows that are exactly the study's target: **no own IR / choke point, multi-path
dispatch, no structural predicate-conservation, no structural row-identity/edge-uniqueness
defense.** The opportunities backlog (§4) is that gap, ranked.

---

## 3. Per-lens narrative

### 3.1 Lens E — the bottom-turtle read (primary)

**Should the executor grow a logical-plan IR?** The ten peers give a sharper answer than a
yes/no. Four of the strongest relational cousins — DuckPGQ, AgensGraph, Apache AGE, and (a
layer up) GraphFrames — have **no own logical IR at all**, and their fixed-length lanes are
nearly silent in the fix stream. They work because they lower *early and completely* into a
mature relational plan (Postgres `Query` / DuckDB binder / Catalyst) that then owns join
ordering, predicate placement, 3VL, and permissions once, for every shape. **That is
exactly Gryphon's bet:** the Django ORM QuerySet + Postgres *is* our borrowed IR
(`dossier-apache-age.md`, `dossier-duckpgq.md`, `dossier-agensgraph.md` all state this
explicitly). The peers validate compile-to-ORM as the spine.

The catch is the same in every one of them, and it *is* the finding: **bugs concentrate
exactly where execution leaves the borrowed layer.** AGE's out-of-plan VLE engine needed
its own shared-memory cache-invalidation scheme and still bleeds consistency bugs seven
years on (`dossier-apache-age.md`, `age_vle.c` + five cache fixes). AgensGraph's custom VLE
node took two rewrites and a decade-long fix tail. DuckPGQ's wrong-results history lives in
its CSR/UDF escape lane (#94, #67, #139), not the relational lane. The one-line rule
(`dossier-duckpgq.md` Net read): *"An IR is not the medicine; shrinking the out-of-vocabulary
zone is."* Gryphon's out-of-vocabulary zone is its **Python-side glue** —
`_merge_envelopes`, `_compute_rows`, the `OPTIONAL MATCH` scoreboard, `_apply_not_exists`
assembly (`executor.py:536, 2394, 2835, 1926`). That, not the absence of an IR, is where
the peers predict our next silent-wrong-answer will live.

So the bottom-turtle recommendation is **shrink the glue before building an IR**: push
everything the ORM can express (`Exists`, `Subquery`, LEFT JOIN via `filter(Q | isnull)`,
`Count(filter=Q)`, anti-join) into queryset combinators over the one chain artifact, and
collapse OPTIONAL / NOT-EXISTS / scan-variant dispatch onto that chain the way single-hop
was already collapsed. The medicine that made single-hop safe — *apply-or-reject, one
lowering* — is the medicine the rest of the executor wants, and four independent peers
reached the identical shape (Morpheus `e2aaae155` "always use the LEFT outer join, delete
the special case"; RedisGraph's one shared `ExecutionPlan_BuildOpsFromPath` under thin
`Optional`/`SemiApply` wrappers; AgensGraph's `transformMatchOptional` as a combinator over
the *one* transform; Kùzu's `planOptionalMatch`/mark-join over `planQueryGraphCollection`).

> **Correction of record (2026-07-05 code-check).** Gryphon has *already done* most of this
> collapse: `_apply_not_exists` is a `~Exists()` anti-join over `_build_chain_queryset`
> (`executor.py:1999`) and `_execute_optional_match` is a `Count(edge, filter=Q)` LEFT-JOIN
> combinator (`:2847`) — exactly the peers' "delete-subsystems-by-delegation" shape. So the
> broad "collapse OPTIONAL/NOT-EXISTS onto the chain" framing (OPP-02) describes a **credit
> mostly banked**, not open work — the remaining task is a *per-path probe* for residual
> Python assembly, and the generalizable win at this seam is the OPP-01 conservation invariant,
> not a sweeping refactor. OPTIONAL's narrow COUNT-only v0 is a demand-gated *scope* question,
> not a correctness collapse.

**When would an actual IR earn its keep?** The peers bound it precisely. Morpheus is the
existence proof — and its lesson is *one* well-chosen middle layer, not many: they built
four in-house stages and **deleted one** (`4c26d9282` removed flat planning). Cytosm is the
control group on the other side: it *has* a real relational IR and still shipped every
silent-wrong-answer class, because its passes coordinate through **mutable shared state and
convention ordering** with no invariant choke point (its own orchestrator comment admits
the pass order is "not understood by its own authors"). The transferable value of an IR is
**not the optimizer** — Gryphon does no cost-based join ordering and needs none — it is the
two things Morpheus and Kùzu hang off the operator layer: a **single expression→column
registry with a throwing lookup** (Morpheus `RecordHeader.column()` throws on an
unregistered expression) and **per-operator declared prerequisites enforced at one
construction choke point** (Kùzu `appendAggregate` runs its flatten prereqs before wiring
the operator; you *structurally cannot* build an aggregate that skipped dedup). Those two
patterns are adoptable incrementally, and the conservation/collapse opportunities below
deliver most of their value without paying for a full IR. A full invariant-bearing operator
layer is therefore ranked structural-high but **deferred with a trigger** (§4, OPP-14):
build it when E1 var-length or `WITH` multi-stage pipelining forces genuine multi-operator
plans, and only if the cheaper conservation/collapse moves have not already closed the gap.

**Where do invariants belong?** Every peer that enforces at one structural choke point is
quiet there; every peer that re-asserts per path bleeds there. The sharpest exhibit is
Apache AGE `4817bfb` (#646): after `WITH ... WHERE` silently dropped its predicate, they
changed the transform's *signature* so the WHERE is a **required parameter every caller
must sign for** — converting tribal per-clause knowledge into a passed obligation. That is
the single-hop collapse in miniature, and it names the general move for Gryphon: make every
lowering path *sign for* the predicate (and every parsed attribute) it must consume, or the
query rejects. cyp2sql is the natural experiment for the cost of *not* doing this — six
distinct accept-then-ignore sites (`hasOptional` set and never read; `direction` computed
and dropped; var-rel `type` discarded at parse), 34% of all its commits spent re-fixing the
two classes (predicates, multi-hop correlation) a conservation invariant would foreclose,
until the only remaining fix was a rewrite.

**Row inflation** — Gryphon's single most recurrent ledger class — is the row where the
peers are furthest ahead and Gryphon has *nothing structural*. Five independent systems
emit relationship-isomorphism (no-edge-bound-twice) as a **plan-level constraint at
lowering time**, so duplicate-edge rows never exist to be counted: openCypherTranspiler's
auto edge-uniqueness rewrite (`LogicalPlan.cs:969-1017`), AgensGraph `addQualUniqueEdges`,
AGE `_ag_enforce_edge_uniqueness`, Morpheus's per-iteration var-length isomorphism filter,
Kùzu's factorized multiplicity + `MULTIPLICITY_REDUCER`. GraphFrames shows the dual failure
(a `_pattern`/`except` TODO sitting in HEAD because no single place defines "what makes two
result rows the same"). Gryphon has the seed — `_node_key`/`_edge_key` (`executor.py:434`) —
but no path is *required* to consume it. Deciding Gryphon's multi-hop edge-repetition
semantics explicitly and emitting the uniqueness constraint inside `_build_chain_queryset`
makes the inflation class inexpressible (OPP-03).

**Null/3VL** is the one place Gryphon's *design* is ahead (a specified 2VL-literal /
3VL-field boundary, `IS KNOWN`/`IS UNKNOWN`, one null not two) but its *implementation* is
distributed — the 3VL logic "currently lives distributed across `_predicate_to_q` sites"
(`dossier-kuzu.md`). Every peer that scattered null discipline paid a multi-year tail:
RedisGraph's 2VL collapse survived **4.5 years** and had two divergent copies of the truth
table (executor + constant-folder) drift inside one engine; AgensGraph landed full Kleene
3VL retrofits *at HEAD, ten years in*, every time a new value context (list element,
comprehension binding, aggregate reducer) was added without re-deriving the null story; AGE
grew a three-regime null accident. The playbook is Morpheus's: null-in-null-out as
**declarative per-operator metadata** enforced by *one* wrapper, with non-strict operators
opting out explicitly. Centralizing Gryphon's null-strictness the same way (OPP-07) means a
new operator can't silently re-open the class — and TLP already probes whether the boundary
holds.

### 3.2 Lens T — what's genuinely missing (and what to not re-import)

Gryphon's ladder **strictly dominates every peer's in-repo testing.** Not one of the ten
has an independent zero-shared-code reference oracle (openCypherTranspiler rents Neo4j —
the closest, but see the reject below; GraphFrames has one for *algorithms* only). None has
a differential property fuzzer with seed-replay (RedisGraph's is crash-only; Kùzu's is an
*unbuilt wish*, #2485). None has TLP. The strongest external validation of our whole ladder
is the peers' silent-wrong-answer tails **under large golden-file suites**: AGE, AgensGraph,
Kùzu, and RedisGraph each shipped headline wrong-answer bugs that survived years because a
committed-golden file is a *ratchet, not an oracle* — it faithfully protects first-write
wrongness (AGE's count(*) fix had to *rewrite* the goldens the bug had been guarding).
Kùzu is the sharpest caution: a 5,000-commit, WCOJ-and-factorization engine with exemplary
architecture still accumulated a **56-issue wrong-result tail** for want of a differential
harness. Architecture and differential testing are complements, not substitutes.

So the guardrail holds — *don't re-import a rung we have* — and the hunt is narrow. Four
genuinely new-to-us techniques survived the filter:

1. **Pattern-direction-reversal metamorphic** (RedisGraph `reversepattern`,
   `test_imdb.py:32-43`): flip every arrow in a MATCH, assert the identical result set.
   This probes a dispatch surface **TLP does not touch** — Gryphon owns real direction code
   (`_single_hop_directed`/`_redirect_single_hop`, `executor.py:510-534`) and Kùzu
   (#5416/#5041) plus GraphFrames both shipped src/dst-swap silent-wrong bugs. Cheap,
   authoring-independent (OPP-08).
2. **Must-fail ratchet for known-broken lists** (Morpheus's two-sided blacklist: every
   xfail scenario is *executed and must FAIL*, `TckSparkCypherTest.scala:88-101`). Converts
   our `OracleUnmodeled` skip-list, fuzz known-issues, and dev-validation known-broken
   manifest from comments into ratchets that light up when a bug is accidentally fixed
   (OPP-11).
3. **Pairwise feature-composition coverage.** GraphFrames' *entire* modern bug stream is
   pairwise interaction (var-length×chain #771, directed×undirected #754, undirected×fixed
   #781); Kùzu's is predicate×recursive (#4966); DuckPGQ's #94 is anchor-predicate×bounded-
   hop. Our fuzzer/coverage ledger doesn't *guarantee* pairwise-composition coverage — make
   the generator emit composed shapes (OPP-10).
4. **Oracle-first for E1.** DuckPGQ's #67 is the exhibit: a variable-length semantic
   ("shortest-in-range" vs "exists-path-in-range") *suspected wrong in writing, open across
   releases, because no independent oracle exists to settle it*. **Correction of record
   (2026-07-04 code-check):** Gryphon does **not** ship bounded `*1..3` — it *parses* it but
   the executor **rejects** it with explicit rejection tests (`test_gryphon.py:328,1440`;
   `executor.py:412,1652`), and the model oracle **also** skips bounded multi-hop
   (`model_oracle.py:477`). The two are consistent *today* — a fail-closed credit, not a
   verification gap. So OPP-05 is oracle-first **prep**: model the semantics and pre-register
   the var-length scenario battery Morpheus, Cytosm, and AgensGraph all bled through, *before*
   rung-4 lowering code exists — so E1 is written against an independent check rather than
   defining truth by itself (OPP-05).

**Rejected/deferred test imports** (recorded so they're not re-litigated): renting a stock
Cypher engine as a third oracle (Gryphon's deliberate divergences, Ledger B, make it a
*noisy* oracle — OPP-16 reject); scenario-count conservation through corpus transforms
(already covered by the coverage-ledger drift guard — OPP-17 reject); NoREC (single-hop
projections degrade to envelopes; already covered by the dispatch collapse + oracle, and
already recorded deferred in the testing philosophy frontier — OPP-18 defer).

### 3.3 Lens H — the archaeology, mapped to our hotspots

The peers' fixed-bug taxonomies cluster with striking agreement, and the clusters *are*
Gryphon's predicted hotspots:

- **Predicate drop / mis-scope at a new dispatch path.** AGE dropped WHERE in WITH (2023),
  CALL-YIELD, pattern-expressions (2026), OPTIONAL MATCH (2026) — *each a new path that
  failed to sign for the predicate.* AgensGraph's join-drop rollback (`c05c235c03`, "their
  envelope-WHERE moment"). Morpheus's `e2aaae155` planner shortcut. DuckPGQ's #94. cyp2sql's
  six accept-then-ignore sites. → Gryphon's WITH-pipelining and per-MATCH-WHERE futures
  (Ledger C) re-open this class unless conservation is structural first (OPP-01).
- **Variable-length as the top executor-semantics bleeder.** Every system with var-length
  bled there, most of all when it left the relational plan (AGE, AgensGraph) or ran a rival
  strategy (cyp2sql, DuckPGQ). → E1 is Gryphon's #1 forecast; lower it in-plan (OPP-04),
  oracle-first (OPP-05).
- **A "transparent" skip-work optimization producing wrong results.** AgensGraph's
  join-removal (`c05c235c03`), AGE's count(*) `output_node` fast path (`ae058ef`, TODO still
  in tree), Kùzu's semi-masker (`1f3c7e81d`), RedisGraph's `reduce_count`, GraphFrames' CC
  revert (`afea945`). *Every* one. → Any future Gryphon fast path that answers from metadata
  or elides work is a standing liability: carry a written soundness argument + own corpus +
  fail-closed sentinel, or delete rather than gate (OPP-13; the discipline AgensGraph adopted
  after its rollback, `inherit.c:87-91`).
- **Null in every newly-added value context**, and **stage-boundary scoping when WITH
  lands** (AGE ~23-fix scoping cluster; RedisGraph #1361/#2220; Morpheus #25990d920). → the
  bugs arrive *with the feature*; centralize null (OPP-07) and expect a scoping surface.
- **Lifecycle.** Two well-architected engines (Morpheus, Kùzu) and one radical foil
  (RedisGraph) all died anyway — architecture is not survival; a sponsor and demand are. The
  strategic read for TAP (per the strategy filter): the peers do not resolve "native vs
  lowering" on commercial grounds, so the decisive argument stays *technical*, and it favors
  Gryphon's inherited-substrate correctness. RedisGraph's EOL note ("graph needed too much
  graph-specific expertise") is the direct validation of not owning a bespoke executor.

---

## 4. Ranked opportunities backlog

Ranked **executor-structural-impact first** (does it make a bug class inexpressible / fix
the bottom-turtle?), then expected-catch-on-known-bug-classes, then inverse-effort — per
protocol §4.3/§5.2. A structural fix that forecloses a class outranks a test that catches
it. De-duplicated across systems (one record, multiple anchors). Every reject/defer carries
a reason.

> **Adversarial-verification pass (2026-07-04).** The top 8 opportunities were re-checked by
> independent skeptic agents against the actual peer clones, and the load-bearing Gryphon
> claims were re-checked against `executor.py` / `model_oracle.py` / `test_gryphon.py`. Results:
> **OPP-01, -02, -04, -06, -07, -09 CONFIRMED** (06 and 09 with "value concentrates at E1" /
> "full one-scan-lowering form is aspirational" caveats — kept at `prototype`). **OPP-05 WEAK →
> corrected**: bounded `*1..3` is executor-*rejected*, not shipped, so OPP-05 is E1-prep, not a
> current-gap close. **OPP-03 WEAK → downgraded**: it forecloses a *distinct, latent* duplicate-
> edge inflation, not "the top recurrent" class (that was the far-node-WHERE duplicate-JOIN,
> already fixed). Corrections are inline in the records below. The pass is itself a datum: the
> differential discipline caught two overclaims the single-pass synthesis had propagated from the
> dossiers — exactly the "check the answer, not the artifact" rule applied to this study's own output.

---

**OPP-01 — Predicate/attribute conservation ledger with fail-closed placement**
- lens: E
- source: Kùzu `plan_join_order.cpp:52-119`, `bind_graph_pattern.cpp:407-423` (conserve-or-throw); RedisGraph `ExecutionPlan_PlaceFilterOps` + `Error_InvalidFilterPlacement` (`execution_plan_construct.c:83-90`); AGE `4817bfb` #646 (predicate-as-required-parameter); cyp2sql `CypherTranslator.java:499-524` (6-site silent drop); DuckPGQ single conjunction sink `match.cpp:1069`
- gryphon_gap: single-hop is apply-or-reject, but scan/advanced/OPTIONAL/NOT-EXISTS paths can still accept a `where_clause` (or a parsed attribute — direction, edge-type, optional flag) and not consume it; conservation is per-path, not global
- maps_to: new-spec-RID under `spec-grid-traversal-execution.md` (lowering-ladder invariant "every predicate leaf and parsed attribute is consumed by exactly one lowering site or the query rejects"); hotspot-ledger predicate-lowering row
- bug_class: predicate drop/mis-scope (envelope-WHERE); accept-then-ignore attribute
- structural: **yes** — generalizes the single-hop collapse's apply-or-reject to a global invariant; makes silent-drop inexpressible on every current and future path
- port_or_mine: mine
- effort: M (a residue-accounting pass over the AST + a fail-closed check at dispatch entry; leans on existing chain seam)
- rank_score: highest — forecloses Gryphon's top ledger hotspot across all paths and future clauses
- recommendation: **adopt-now** — this is the direct generalization of the move the testing philosophy already canonizes (§9); cheap relative to its reach

**OPP-02 — Collapse OPTIONAL MATCH & NOT EXISTS onto the chain via thin combinators; shrink the Python-side semantics glue**
- lens: E
- source: Morpheus `e2aaae155` ("always LEFT outer join; delete the special case"), shared operator set; RedisGraph `ExecutionPlan_BuildOpsFromPath` + `Apply`/`Optional`/`SemiApply` wrappers; AgensGraph `transformMatchOptional` (combinator over the one transform); Kùzu `planOptionalMatch`/mark-join; DuckPGQ "delete subsystems by delegation" (OPTIONAL=outer LEFT JOIN, NOT-EXISTS=anti-join in SQL)
- gryphon_gap: **[corrected 2026-07-05, code-check]** the premise was overstated. `_apply_not_exists` is **already** a `~Exists()` correlated anti-join over `_build_chain_queryset` (`executor.py:1999`), and `_execute_optional_match` is **already** a `Count(edge, filter=Q)` LEFT-JOIN combinator with the filter-placement gotcha handled (`:2847`) — i.e. the peers' "delete subsystems by delegation" collapse is **largely already done**. `_merge_envelopes` (`:536`) is a legitimate multi-MATCH union dedup, not divergence-prone glue. The residual "glue" is narrower than claimed and must be established per-function by probe, not assumed
- maps_to: wishlist executor-structure bucket; `spec-grid-gryphon-multihop-aggregation.md`; dispatch_collapse_candidates
- bug_class: (residual) any remaining genuinely-Python-side assembly; the generalizable defense is OPP-01, not a broad collapse
- structural: partial — where a residual path *is* Python assembly, converting it to a combinator removes a divergence site; but most of this is already combinator-based, so the sweeping "shrink the glue" framing is a credit already banked, not open work
- port_or_mine: mine
- effort: S (probe each path) → M (only where a probe finds real glue)
- rank_score: **[downgraded 2026-07-05]** — the collapse is mostly already implemented; this is a probe-first task, not the 2nd-ranked bottom-turtle fix. The real generalizable win at this seam is OPP-01
- recommendation: **probe-first** — audit each non-chain path; refactor only where genuinely Python-side (OPTIONAL's narrow COUNT-only v0 is a *scope-broadening* question, a separate demand-gated feature, not a correctness collapse). Do NOT refactor NOT-EXISTS/OPTIONAL just because peers model it — they already are combinators here

**OPP-03 — Emit relationship-isomorphism (edge-uniqueness) + one result-row-identity discipline at the chain choke point**
- lens: E
- source: openCypherTranspiler auto edge-uniqueness plan rewrite (`LogicalPlan.cs:969-1017`); AgensGraph `addQualUniqueEdges` (`parse_graph.c:4083-4155`); AGE `_ag_enforce_edge_uniqueness` (`prevent_duplicate_edges`); Morpheus per-iteration isomorphism filter (`VarLengthExpandPlanner.scala:207-208`); Kùzu `MULTIPLICITY_REDUCER`; GraphFrames `_pattern`/`except` row-identity TODO (the dual failure)
- gryphon_gap: no structural row-identity or edge-uniqueness defense; `_node_key`/`_edge_key` exist (`executor.py:434`) but no path is required to consume them; multi-hop aggregate over duplicated joins can overcount
- maps_to: `spec-grid-traversal-language.md` (decide multi-hop edge-repetition semantics explicitly) + emit constraint in `_build_chain_queryset`; hotspot-ledger row-inflation row
- bug_class: multi-hop duplicate-**edge** row inflation (relationship-isomorphism)
- structural: **yes** — with the uniqueness qual emitted at lowering time, duplicate-edge rows never exist to reach an aggregate; inflation-by-duplicate-edge becomes inexpressible
- port_or_mine: mine
- effort: M (needs a spec decision on repetition semantics first, then a qual in the one chain builder)
- rank_score: **[downgraded 2026-07-04, adversarial-verify WEAK]** — forecloses a *distinct, currently-latent* inflation mechanism, NOT "the top recurrent ledger class." The actually-recurrent inflation defect was the far-node-WHERE **duplicate-JOIN** (`doc-gryphon-testing-philosophy.md:350`), a different mechanism that is **already fixed** (folded into the chain's single `.filter()`, `far_node_where` scenarios). Five peers converged on emitting edge-uniqueness structurally, so the gap is real — but its urgency rests on whether Gryphon *actually inflates* on duplicate-edge/cyclic shapes today
- recommendation: **prototype — verify-first**: write a cyclic-fixture edge-reuse scenario and check whether Gryphon inflates on it *now* (a cheap Goal-A probe); if it does, spec the repetition semantics and emit the qual at the chain choke point; if it doesn't, this is preventive architecture to bundle with E1/OPP-06

**OPP-04 — Pin variable-length lowering as in-plan (rung-4 recursive CTE); forbid an out-of-plan traversal service with its own cache**
- lens: E/H
- source: AGE `age_vle.c` + `age_global_graph.c:54-99` + five cache-coherence fixes (#2308/#2341/#2160/#2433/#2382); AgensGraph custom `GraphVLE` node, two rewrites + decade fix tail; RedisGraph derived-representation "signature saga" (~14 commits); the exec spec's own Future note about "a PG graph extension as a backend"
- gryphon_gap: E1 is unbuilt; the ladder anticipates rung-4 but hasn't committed the constraint that var-length must lower *inside* the relational plan
- maps_to: new-spec-RID / acceptance criterion under `req-grid-traversal-exec-lowering`; wishlist E1
- bug_class: cache-coherence/consistency family (transactional visibility, replica failure, stale snapshot) that appears the moment traversal leaves the plan
- structural: **yes** — pre-committing "in-plan only" forecloses the entire out-of-plan-cache bug family before any E1 code exists
- port_or_mine: mine
- effort: S (a spec constraint, not code)
- rank_score: high — cheapest structural foreclosure of the #1 predicted hotspot's worst failure mode
- recommendation: **adopt-now** — record the constraint in the lowering-ladder spec now, while E1 is still on paper

**OPP-05 — Oracle-first for E1: extend the model oracle over bounded repetition and pre-register the var-length scenario battery before rung-4 code**
- lens: T
- source: DuckPGQ #67 (shortest-in-range vs exists-in-range, *suspected wrong in writing for years* — the state a missing oracle produces); Morpheus var-length four-bug cluster (`acd7a6750`, `5e7228224`, `e7c89205d`, `8d457423e` — length-0, per-segment nullability, union-alignment, empty interval); Cytosm three systemic var-length Known Issues (COUNT/ORDER-BY/edge-reuse over unioned disjuncts); AgensGraph/AGE VLE fix tails; Kùzu #4966
- gryphon_gap: **[corrected 2026-07-04]** Gryphon *parses* `*1..3` but the executor **rejects** it (E1 unbuilt; `executor.py:412,1652`; rejection tests `test_gryphon.py:328,1440`), and the model oracle also skips it (`model_oracle.py:477`) — consistent today (a fail-closed credit, not a live gap). OPP-05 is oracle-first **prep**: pin the semantics *before* rung-4 lowering exists (the DuckPGQ #67 lesson) so E1 code is written against an independent check
- maps_to: testing-ladder rung (model oracle deepening) + pre-landed Gridkin scenarios; wishlist E1
- bug_class: var-length semantics (shortest-vs-exists, path-uniqueness, length-0/empty-interval, per-segment nullability), COUNT-over-var-length inflation
- structural: partial — pins the semantics before lowering exists, so the code is written *against* an independent check rather than defining truth by itself
- port_or_mine: mine
- effort: M (oracle modeling of bounded repetition + scenario authoring)
- rank_score: high **as E1 prep** — gates the #1 predicted hotspot's semantics before any rung-4 code; NOT a current-gap close (the feature is executor-rejected today)
- recommendation: **adopt-now (as E1-readiness, sequenced with OPP-04/OPP-06)** — extend the oracle and register COUNT/ORDER-BY+LIMIT/cyclic-edge-reuse/length-0/empty-interval scenarios ahead of the executor work; do it when E1 is picked up, not as a standing verify-now item

**OPP-06 — Desugar at one AST→AST normalization choke point (inline maps, self-loops, anchor shapes, bounded-rep expansion); never on text, never inside a wrapper**
- lens: E
- source: Kùzu `Binder::rewriteMatchPattern` (`bind_match.cpp:83-120` — inline maps→WHERE conjunct, self-loop→predicate normal form); GraphFrames `024f939` (pre-fold normalization made the scoping bug unreachable) vs its text-rewrite bug cluster (#754/#771/#781); Cytosm string-re-entry anti-pattern (self-flagged "plain wrong"); cyp2sql substring routing
- gryphon_gap: Gryphon parses to a frozen AST (good) but has no single normalization pass that rewrites sugar/degenerate shapes (`(a)-[e]->(a)`, inline `{k:v}`, anchor forms, `*1..k` expansion) into one canonical pattern+WHERE form before dispatch
- maps_to: new normalization stage in the pipeline (`req-grid-traversal-exec-pipeline` compile step); reduces the dispatch surface OPP-02/OPP-09 must cover
- bug_class: missing-dispatch-arm for degenerate shapes (self-loop, repeated variable); composition breaks; predicate drop from un-normalized sugar
- structural: **yes** — normalizing to one form *before* lowering collapses whole shape families into the uniform path, making per-shape arms unnecessary
- port_or_mine: mine
- effort: M
- rank_score: high — forecloses the composition/degenerate-shape class; especially load-bearing before E1's bounded-rep expansion
- recommendation: **prototype** — bundle the normalization pass with the E1 expansion so `*1..k` is desugared at the choke point, not in a wrapper

**OPP-07 — Centralize null-strictness as declared per-operator metadata + a single lowering wrapper**
- lens: E
- source: Morpheus `nullInNullOut` metadata + one `nullSafeConversion` wrapper (`SparkSQLExprMapper.scala:73-102`), non-strict operators opt out explicitly; RedisGraph 4.5-year 2VL collapse with two divergent truth-table copies (`01d60592` #2699); AgensGraph 3VL retrofits at HEAD after 10 years; AGE dual-null three-regime accident; Kùzu one truth-table artifact (`boolean_functions.h:8-90`)
- gryphon_gap: the specified 2VL-literal/3VL-field boundary is correct by design but its implementation "lives distributed across `_predicate_to_q` sites" — each new operator/aggregate re-derives the null story
- maps_to: `spec-grid-traversal-language.md` (null semantics) + executor refactor to one null wrapper; hotspot-ledger null-boundary row
- bug_class: null 2VL/3VL boundary, especially "a new value context re-opens the class"
- structural: **yes** — a new operator declares strict/non-strict and inherits the boundary from one enforced site; it cannot silently get null wrong
- port_or_mine: mine
- effort: M
- rank_score: high — TLP already *probes* the boundary; this makes it *hold* structurally as the operator set grows
- recommendation: **prototype** — declare per-operator strictness, route all null handling through one wrapper; pair with OPP-12

**OPP-08 — Pattern-direction-reversal metamorphic check**
- lens: T
- source: RedisGraph `tests/flow/reversepattern/__init__.py` + `test_imdb.py:32-43` (flip every arrow, assert identical result set); corroborated by Kùzu src/dst swap bugs (#5416/#5041) and GraphFrames undirected/directed mixing bugs
- gryphon_gap: TLP probes the predicate partition but nothing probes *pattern orientation*, and Gryphon owns real direction code (`_single_hop_directed`/`_redirect_single_hop`, `executor.py:510-534`)
- maps_to: testing-ladder rung (new metamorphic relation alongside TLP)
- bug_class: direction/undirected src-dst identity swaps (silent wrong answer)
- structural: no — a catch, not a foreclosure
- port_or_mine: mine
- effort: S (a metamorphic relation over existing fixtures/generator)
- rank_score: top of the test tier — cheap, authoring-independent, exercises a dispatch surface no current rung touches
- recommendation: **adopt-now**

**OPP-09 — Collapse scan-variant duplication into narrowing rewrites of one scan lowering**
- lens: E
- source: RedisGraph scan choice as optimizer *rewrites* of the general plan (`reduceScans`/`optimizeLabelScan`, `optimizer.c:27-37`), so fast paths inherit filters/scoping; Kùzu label-vs-no-label as *data* (`NodeLabelFilter` operator), not dispatch
- gryphon_gap: `_execute_type_scan` vs `_execute_bare_type_scan`, and `_apply_order_limit_typescan` vs `_apply_order_limit_typescan_envelope`, are sibling paths that separately re-apply predicate/order/limit — the duplicated-per-path shape peers avoid
- maps_to: wishlist executor-structure bucket; dispatch_collapse_candidates
- bug_class: per-path predicate/order/limit divergence (a scan variant applies a filter another forgets)
- structural: **yes** (narrower reach than OPP-01/02) — one scan lowering narrowed by label/order/limit as data means no sibling path to forget an application
- port_or_mine: mine
- effort: M
- rank_score: mid structural tier — real foreclosure, smaller blast radius than OPP-01/02
- recommendation: **prototype** — fold the two type-scan variants (and their two order/limit appliers) into one

**OPP-10 — Pairwise feature-composition fuzz coverage**
- lens: T
- source: GraphFrames' entire modern bug stream is pairwise (var-length×chain #771, directed×undirected #754, undirected×fixed #781); Kùzu predicate×recursive (#4966); DuckPGQ anchor-predicate×bounded-hop (#94)
- gryphon_gap: the fuzzer/coverage ledger doesn't *guarantee* pairwise-composition coverage (OPTIONAL×WHERE-scoping, NOT-EXISTS×multi-hop, bounded-rep×far-node-WHERE, multi-MATCH-union×ORDER/LIMIT)
- maps_to: testing-ladder rung (generator composition rules); coverage-ledger
- bug_class: feature-interaction seams (the dominant peer class)
- structural: no — a catch
- port_or_mine: mine
- effort: S–M (extend the generator to emit composed shapes)
- rank_score: high test tier — targets the empirically dominant peer bug locus
- recommendation: **adopt-now** — teach the generator to compose two features per query

**OPP-11 — Must-fail ratchet for every known-broken / xfail list**
- lens: T
- source: Morpheus two-sided blacklist — every blacklisted scenario is executed and *must FAIL* (`TckSparkCypherTest.scala:88-101`), so a silently-fixed bug can't stay hidden behind a stale tag
- gryphon_gap: the model-oracle `OracleUnmodeled` skip-list, fuzz-campaign known-issue lists, and the dev-validation known-broken manifest are comments/skips with no ratchet forcing them to shrink
- maps_to: testing-ladder + dev-validation known-broken manifest gate
- bug_class: process (stale known-broken entries hiding accidental fixes/regressions)
- structural: no — a ratchet
- port_or_mine: mine
- effort: S
- rank_score: high test tier — cheap, converts three existing comment-lists into ratchets
- recommendation: **adopt-now**

**OPP-12 — Generated null-matrix scenario suite (operator × null-position)**
- lens: T
- source: Morpheus `NullTests.scala:33-90` (one `returnsNull()` line per function) as a cheap exhaustive null-matrix generator; Kùzu null-inside-aggregate cluster (#4909/#4949); AgensGraph "nulls in every new value context" as a standing generator rule
- gryphon_gap: null coverage is authored per-scenario, not generated across the operator × null-position cross-product
- maps_to: testing-ladder rung (mines the NullTests shape); pairs with OPP-07
- bug_class: null 2VL/3VL boundary, null-in-aggregate
- structural: no — a catch
- port_or_mine: mine
- effort: S
- rank_score: mid test tier — cheap generator that feeds the existing null hotspot
- recommendation: **adopt-now** — as a generator rule, not a one-off scenario

**OPP-13 — Skip-work-optimization discipline: soundness argument + own corpus + fail-closed sentinel, or delete not gate**
- lens: H/E
- source: AgensGraph join-drop rollback (`c05c235c03`) → the discipline it forced (`inherit.c:87-91` written soundness argument + `cypher_graphmeta_prune.sql` corpus + `-1` sentinels); AGE count(*) `output_node` fast path (`ae058ef`, TODO still in tree, "delete rather than gate"); RedisGraph `reduce_count`, Kùzu semi-masker `1f3c7e81d`, GraphFrames CC revert `afea945`
- gryphon_gap: no standing rule governing future cardinality-affecting or work-eliding fast paths (Gryphon has few today, but they will come with aggregation/EXISTS shortcuts)
- maps_to: new-spec-RID / doctrine note in `spec-grid-traversal-execution.md`; security/AI-legibility posture (design-note-at-the-site)
- bug_class: "transparent" optimization producing silent wrong results (every peer hit this)
- structural: partial — a policy that makes the class reviewable and gated, not inexpressible
- port_or_mine: mine
- effort: S (a doctrine note now; enforced per future optimization)
- rank_score: mid — cheap insurance against a class *every* peer paid for
- recommendation: **adopt-now** — record the doctrine before the first fast path lands

**OPP-14 — Thin invariant-bearing operator/header layer (schema-carrying ops + throwing expression→column registry + per-operator declared prerequisites at one construction choke point), NO cost optimizer**
- lens: E
- source: Morpheus `RecordHeader.column()` throws on unregistered expression (`RecordHeader.scala:91-100`) + operator materialization conformance check (`RelationalOperator.scala:70-137`); Kùzu `computeFactorizedSchema` + `append*` prereq enforcement (`append_aggregate.cpp:9-18`); openCypherTranspiler's binding-boundary invariant passes; Cytosm as the counter-example (IR *without* invariant enforcement merely relocates bugs); Morpheus deleted a redundant stage (`4c26d9282`) — one middle layer, not many
- gryphon_gap: no logical-plan layer; the executor lowers AST→ORM directly (the exact seam the exec spec's `req-grid-traversal-exec-compiler` Future anticipates)
- maps_to: `req-grid-traversal-exec-compiler` Future (the IR seam) + `req-grid-traversal-exec-lowering` (per-node rung selection); plan/pass-shape test rung *underneath* the answer-level rungs
- bug_class: whole-executor invariant enforcement (predicate/scope/type/multiplicity) at one place
- structural: **yes, the largest** — but its value is the choke point + throwing registry + declared prereqs, *not* an optimizer, and OPP-01/02/03/07 deliver most of that value incrementally
- port_or_mine: mine
- effort: L
- rank_score: structural-high but effort-discounted and partially subsumed by the conservation/collapse opportunities
- recommendation: **defer-with-trigger** — build when E1 var-length or `WITH` multi-stage pipelining forces genuine multi-operator plans, and only if OPP-01/02/03/07 have not already closed the choke-point gap; if built, follow the peers: exactly one middle layer, invariants enforced at construction, plan-shape tests added *beneath* (never instead of) the answer/oracle rungs (Cytosm's inversion is the warning)

**OPP-15 — Design-note-at-the-enforcement-site practice**
- lens: H
- source: AGE `9f9d0f3` (semantics + cost postmortem committed *into* `age_vle.c` "to prevent future misdiagnoses"); AgensGraph graphmeta soundness argument in-source (`inherit.c:87-91`)
- gryphon_gap: Gryphon's semantics reasoning lives in specs/docs (good) but not always *at the source line* where a future edit would re-introduce the bug
- maps_to: AI-legibility posture (Player-3 machine-legible in-source semantics); executor comment discipline
- bug_class: process (re-introduced bugs at subtle enforcement sites)
- structural: no — a practice
- port_or_mine: mine
- effort: S
- rank_score: low but nearly free; aligns with the AI-integration posture
- recommendation: **adopt-now** — commit the semantics + why at the enforcement line for null, edge-uniqueness, and E1

**OPP-16 — Rent a stock Cypher engine (Neo4j/Memgraph) as a third differential oracle** — *reject*
- lens: T
- source: openCypherTranspiler's Neo4j-vs-SQL-Server differential harness (`SQLRendererTest.cs:266-360`)
- gryphon_gap: none that this closes
- bug_class: n/a
- structural: no
- recommendation: **reject-with-reason** — Gryphon's deliberate divergences from Cypher (Ledger B: `RETURN`-optional envelope, `=~` substring, 2VL-null-literal, type-strictness rejection, `IS KNOWN`/`IS UNKNOWN`) make a stock-Cypher engine a *noisy* oracle that would diverge on correct behavior; the zero-shared-code model oracle already fills the independence role. (openCypherTranspiler's own harness also shows the trap: its ordering assertion is `NotImplementedException` and it blurs null vs "" — proxies that false-green where the lowering is weakest.)

**OPP-17 — Scenario-count conservation through corpus transforms** — *reject*
- lens: T
- source: cyp2sql corpus-shrink bug (queries silently overwritten in a `TreeMap` keyed by `nextInt(1000)`, `Reagan_Main_V4.java:184-205`)
- gryphon_gap: none — the coverage-ledger bidirectional drift guard (the Gridkin TCK-coverage requirement, gryphon_playground plugin repo) already asserts corpus↔ledger conservation
- recommendation: **reject-with-reason** — duplicate of an existing rung

**OPP-18 — NoREC envelope/projection differential** — *defer*
- lens: T
- source: SQLancer NoREC; considered in the testing-philosophy frontier
- gryphon_gap: single-hop projections degrade to envelopes at Gryphon's dispatch layer, so NoREC yields no *distinct* check
- recommendation: **defer-with-reason** — already recorded deferred (testing philosophy §frontier); the target is covered by the dispatch collapse + model oracle. Revisit only if a dispatch path emerges where projection and envelope genuinely diverge

---

## 5. Credits — bug classes Gryphon's architecture already forecloses

Evidence the current bets pay off. Each is a class one or more peers bled on for *years*
that is structurally inexpressible (or already-loud) in Gryphon — recorded per protocol
§7.3 so the read-only, typed-lane, single-hop-collapse, and owned-substrate bets are
visibly earning their keep.

| Gryphon bet | Peer class it forecloses | Peer evidence |
| --- | --- | --- |
| **Read-only by construction** (parse-time write rejection, `search_readonly` alias) | The entire write-path / MVCC / eager-eval / visibility family | AGE ~52 write-path + MERGE-visibility fixes (still active 2026); AgensGraph ~15 write-visibility fixes over 8 years (two in the final week); Kùzu ~48 storage/txn/WAL fixes; RedisGraph deleted-entity/ID-reuse crash class; GraphFrames' entire iterative-algorithm state family (>half its wrong-result history) |
| **Typed-lane rejection** (schema-as-oracle, `req-grid-traversal-lang-type-strictness`) | Universal-value-type coercion at the cast/null boundary | AgensGraph jsonb class #1 (~19 fixes, silent never-match `0f0cbf521d`); AGE `agtype` cast-crash cluster + the 2026 walk-back toward typed composite lanes (`5ef7d6d`) — *the opposite-pole peer migrating toward Gryphon's bet*; RedisGraph DISJOINT-tolerance; Kùzu ~38 cast fixes; cyp2sql infer-INT-from-data + quote-everything |
| **One null + specified 2VL/3VL boundary** (`IS KNOWN`/`IS UNKNOWN`) | The dual-null / undesigned-null-boundary accident | AGE three-regime `AGTV_NULL` vs SQL NULL; AgensGraph 3VL retrofits at HEAD after 10 years; RedisGraph 4.5-year 2VL collapse with two divergent truth-table copies |
| **Single-hop dispatch collapse** (apply-or-reject, already shipped) | The many-armed dispatch where one arm silently does the wrong join | Morpheus `e2aaae155` (planner shortcut → silent wrong answer); GraphFrames `024f939` (`left_outer` should be inner + missing self-loop arm); the whole envelope-WHERE family every peer independently reproduced |
| **Compile-to-ORM over a trusted substrate** (Postgres owns join/3VL/plan) | The correctness scaffolding a bespoke executor must re-earn by hand | RedisGraph (EOL'd citing graph-expertise cost; re-earned 3VL, join semantics, memory safety over 7 years); Kùzu (56-issue wrong-result tail despite exemplary architecture); the derived-representation "signature saga" (~14 transpose-maintenance fixes) — the fence the lowering ladder's rung-4/5 gating maintains |
| **Bind-parameterized ORM values** | SQL injection / quoting-regime bugs by construction | openCypherTranspiler string-interpolates literals (no binds); Cytosm concatenates unescaped (`RenderingHelper.java:39-42`); cyp2sql quote-strips (`v.replace("'","")`, two regimes at two layers) |
| **Deterministic captured SQL** (sorted `pk__in`, identity-set envelope compare) | Golden-file order/locale/endianness/float churn; comparator normalization laundering bugs | AGE four separate test-stabilization fixes (`c3f8caf`, `3b8aaa6`, `14732bf`, `a29e281`) + "add ORDER BY to the tested query" (distorts the query under test); cyp2sql bent its comparator (lowercasing, null-skipping) to match its own defects |
| **Independent model oracle + differential fuzzer** (already built) | Silent-wrong-answers surviving years under golden-file-only suites | AGE / AgensGraph / Kùzu / RedisGraph each shipped headline silent-wrong bugs that a ratchet-not-oracle suite protected; DuckPGQ #67 open across releases for want of an oracle to settle it; GraphFrames' hardest wrong-result bug hand-shrunk by a user |
| **Stateless per-query execution, owned grammar** | Registry/state drift and host-parser-shape crashes | DuckPGQ ~12 host-integration segfaults (MATCH in CTE/subquery/EXPLAIN/COPY) + ~12 registry-scoping fixes — both inexpressible in Gryphon (owns its grammar; schema from the live registry) |

---

## 6. Pointers

- **Dossiers (the evidence):** `comparanda/dossier-{opencyphertranspiler,duckpgq,agensgraph,apache-age,morpheus,cytosm,cyp2sql,graphframes,kuzu,redisgraph}.md`
- **Study protocol (the rubric):** `doc-gryphon-comparative-eval-protocol.md`
- **Test ladder & frontier:** `doc-gryphon-testing-philosophy.md`
- **Cypher relationship (divergences/credits/subset):** `doc-dev-gryphon-vs-cypher.md`
- **Demand-shape roadmap:** `doc-dev-gryphon-wishlist.md`
- **Execution seams the opportunities target:** `tap_grid/specs/spec-grid-traversal-execution.md` (lowering ladder, IR Future note), `spec-grid-gryphon-multihop-aggregation.md`
- **Hotspot map:** `gryphon-findings-ledger` (agent memory) + `doc-gryphon-envelope-where-defect-handoff.md`
