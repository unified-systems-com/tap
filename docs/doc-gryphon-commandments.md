---
audience: [llm, developer]
covers:
  - ../tap_grid/specs/spec-grid-traversal-language.md
  - ../tap_grid/specs/spec-grid-traversal-execution.md
  - ../tap_grid/specs/spec-grid-gryphon-multihop-aggregation.md
  - ../plugins/gryphon_playground/specs/spec-gridkin-v0.md
  - ../plugins/gryphon_playground/specs/spec-gryphon-playground-v0.md
update-triggers:
  - A commandment is added, retired, or materially reworded (bump its ID's Reason/Enforcement)
  - A "forthcoming" commandment's trigger capability ships (promote it to an active commandment and record the promotion)
  - A new durable Gryphon rule is earned from a bug, an AAR, or a comparative-study finding
  - An automated guard/test lands that changes a commandment's Enforcement line from "review-time" to a named guard
assumes:
  - Reader is doing (or reviewing, or specifying) work on the Gryphon language, executor, or its tests
  - Reader can consult the specs for exact behavior — this doc is the doctrine layer over them, not a restatement
provides: |
  The standing "thou shalt / shalt not" doctrine for all Gryphon work — the durable
  commandments that keep language, executor, and testing on the happy path, each with
  a Reason and an Enforcement anchor, plus a Forthcoming section of commandments that
  activate once a named capability ships. Written for LLM readers first (high fidelity,
  anchored, RFC-2119 keywords); humans can ask. This is the backbone doc referenced by
  the Gryphon specs; consult it before any new language/executor/test development.
---

# The Gryphon Commandments — Standing Doctrine for Language, Executor, and Testing

> The backbone doc for Gryphon work. The **specs are authoritative for behavior**; this doc is
> the **doctrine filter** over them — the rules that, if followed, keep every future change on the
> path the system has already paid (in bugs, AARs, and a ten-peer comparative study) to find.
> Drafted 2026-07-05 against the **current** state of the system, *before* the research-pass
> hardening recommendations are implemented. Recommendations that are not yet true of the system
> live in [§Forthcoming](#forthcoming-commandments), not among the active commandments.
> Merged 2026-07-06 with the parallel Codex draft (bake-off): absorbed its variable-scope rule
> (→ GRY-SEM-6), canonical-result-shape rule (→ GRY-ARCH-11), the pre-flight Agent Checklist, a
> Baseline-facts grounding block, and the k8s-API-conventions prior-art. `doc-gryphon-commandments-codex.md`
> is retired to a tombstone.

## How to read this

- **Keywords are RFC 2119.** **MUST** / **MUST NOT** are invariants — breaking one is a defect,
  not a style choice. **SHOULD** / **SHOULD NOT** are strong defaults — deviate only with a
  recorded reason. **MAY** is genuine latitude. This precision is deliberate: LLMs are the primary
  readers and authors of Gryphon code, and a fuzzy "prefer" reads differently to a machine than a
  hard "MUST NOT."
- **Every commandment has a stable ID** (`GRY-<AREA>-<n>`). Cite it in specs, commit messages,
  review comments, and test docstrings. IDs are append-only: a retired commandment keeps its ID
  with a `RETIRED` note; new ones take the next number. This makes the doctrine grep-able and
  lets a guard or a spec say exactly which rule it enforces.
- **Each commandment carries a Reason and an Enforcement line.** The Reason is *why the rule
  exists* (usually a scar). The Enforcement is *what actually holds the line* — a named guard/test
  where one exists, or an honest `review-time — no automated guard yet (candidate: …)` where one
  does not. Do not read a `review-time` enforcement as "optional"; read it as "the guard is
  missing and is itself a candidate task." Naming the gap is the security/AI-legibility posture
  applied to this doc (never imply completeness).
- **This doc is doctrine, not behavior.** When a commandment and a spec disagree on *behavior*,
  the spec wins and this doc is stale — fix it. When they disagree on *whether a change is wise*,
  this doc is the tie-breaker the specs defer to.
- **Provenance.** The commandments distil `doc-gryphon-testing-philosophy.md` (the earned test
  ladder), `doc-gryphon-comparative-findings.md` (ten-peer study), `doc-dev-gryphon-vs-cypher.md`
  (the Cypher ledgers), the traversal specs, and agent-memory feedback. Prior-art lineage for the
  *format* is credited in [§Prior art](#prior-art--lineage).

---

## Baseline facts (the current state this doctrine is anchored to)

Not aspirations — the system as it stands (verify before relying on any specific line; GRY-PROC-2):

- Gryphon is the **canonical read/query path** for TAP-managed graph data; raw ORM graph reads and
  bespoke module runners are break-glass, not the normal answer to a missing construct.
- Gryphon is **read-only**; all mutation is the typed service layer's / GRIFT's (GRY-ARCH-7).
- The executor **compiles through the Django ORM first** (lowering ladder rung 1); higher rungs are
  deliberate escalations (GRY-ARCH-2).
- **Gridkin** is the committed validation format (fixture + query + expected envelope + expected SQL
  snapshot + requirement coverage + TCK breadcrumb); the **model oracle** and **fuzz/TLP** catch
  wrong answers the hand-picked scenarios miss.
- **SQL snapshots are evidence about the emitted plan, not the correctness oracle** (GRY-TEST-1/6).
- Variable-length `-[*n..m]->` **parses but the executor rejects it** (fail-closed); the planned
  reachability mechanism is grid-native **named paths**, not recursive traversal (GRY-F-3).

---

## I. Architecture & Execution — `GRY-ARCH`

**GRY-ARCH-1 · Compile over a trusted substrate.**
> Gryphon **MUST** compile to the ORM/relational layer and let PostgreSQL own join ordering,
> three-valued logic, and physical planning. Gryphon is a *compiler*, not a database.

Reason: the substrate is battle-tested; the entire bug surface is **translation fidelity** — does
the emitted SQL mean the same as the query? Owning both ends (AST + captured SQL) over a trusted
target is what makes every other rule here affordable. Four purest peers (DuckPGQ, AgensGraph, AGE,
GraphFrames) borrow the host's plan and are near-silent in their fix streams; the bespoke-executor
peers (RedisGraph) re-earned correctness for years.
Enforcement: `spec-grid-traversal-execution.md` (`req-grid-traversal-exec-lowering`, rung 1); review-time.

**GRY-ARCH-2 · Lowest rung that expresses the query.**
> A query **MUST** lower to the lowest ladder rung that can express it. Reaching for a higher rung
> (raw `Func`/`RawSQL`/CTE/stored fn) is a deliberate, review-visible escalation, never a convenience.

Reason: every rung above the ORM re-earns by hand what the ORM gives for free (bind-params,
read-only alias, dimension scoping, envelope shape). The ladder makes that cost explicit.
Enforcement: `req-grid-traversal-exec-lowering` (invariants list); review-time.

**GRY-ARCH-3 · Apply-or-reject; never silent-drop.**
> A lowering path **MUST NOT** accept an input it silently ignores. If a path cannot apply a
> predicate, a parsed attribute (direction, edge type, optional flag), or a clause, it **MUST**
> reject loudly (`SearchExecutionError`), not proceed with the input dropped.

Reason: the silent wrong answer is the worst outcome — plausible, alarmless, and it looks exactly
like a correct small result. The envelope-WHERE defect was precisely a path that accepted a
`where_clause` and never looked at it. Single-hop was collapsed to make this structurally true for
that shape.
Enforcement: single-hop dispatch (`executor.py::_dispatch_pattern` → chain machinery); the model
oracle (divergence on a dropped predicate); **partial** — not yet a global invariant (see
[GRY-F-1](#forthcoming-commandments)).

**GRY-ARCH-4 · Prefer structural impossibility to a test.**
> When a bug class can be made *inexpressible* by collapsing paths or tightening a type, you
> **SHOULD** do that in preference to adding a test that merely catches it.

Reason: a passing test says "absent today"; a collapsed, fail-closed dispatch says "cannot recur."
The single-hop collapse deleted three buggy executors instead of testing them (−389 lines).
Enforcement: review-time; architectural judgement (this is the top rung of the test ladder, not a
guard).

**GRY-ARCH-5 · Keep semantics ORM-expressible; minimize the glue.**
> Query meaning **SHOULD** live in ORM-expressible constructs (`Exists`, `Subquery`, LEFT JOIN via
> `filter(Q|isnull)`, `Count(filter=Q)`, anti-join). Python-side row assembly ("glue") **SHOULD**
> be minimized — it is the out-of-vocabulary zone the trusted substrate does not cover.

Reason: peers' wrong-results concentrated in exactly the zones that left the relational plan
(CSR/UDF lanes, custom nodes). *Current credit:* Gryphon already lowers `NOT EXISTS` as a
`~Exists()` anti-join (`executor.py:1999`) and `OPTIONAL MATCH` as `Count(filter=Q)` over a LEFT
JOIN (`:2847`) — most of this collapse is already banked. New work **MUST NOT** re-introduce
bespoke Python assembly for something the ORM can express.
Enforcement: review-time; the model oracle covers the combinator paths that exist.

**GRY-ARCH-6 · No premature IR.**
> Gryphon **MUST NOT** grow a bespoke logical-plan IR ahead of demand. The ORM QuerySet + Postgres
> plan *is* the borrowed IR. An own IR is built **only** when variable-length paths or `WITH`
> pipelining force genuine multi-operator plans — and then per [GRY-F-4](#forthcoming-commandments).

Reason: the study is unambiguous — an IR is not the medicine; shrinking the glue is. Cytosm is the
control group: an IR *without* invariant enforcement merely relocated the bugs. Morpheus built four
IR stages and deleted one.
Enforcement: `doc-gryphon-comparative-findings.md` (OPP-14, deferred-with-trigger); review-time.

**GRY-ARCH-7 · Read-only by construction.**
> Execution **MUST** run on the `search_readonly` alias and **MUST NOT** mutate persisted TAP
> state. Any graph mutation goes through the typed service layer, never Gryphon.

Reason: read-only is a *security* property, not just a missing feature — it is what lets a Gryphon
string be stored on a Search object and (future) accepted from untrusted callers. It also makes the
entire write/MVCC/visibility bug family (peers' largest class) inexpressible here.
Enforcement: `req-grid-traversal-exec-scope.sec-1`; the read-only Flaw write-detection guard.

**GRY-ARCH-8 · Parameterize, never interpolate.**
> Caller and `$param` values **MUST** be passed as bind parameters at every rung, never
> string-interpolated into SQL.

Reason: injection- and quoting-regime safety by construction. Three peers that string-interpolate
(openCypherTranspiler, Cytosm, cyp2sql) carry the corresponding class; Gryphon's ORM lowering
forecloses it.
Enforcement: ORM lowering (rung 1 binds by default); `req-grid-traversal-exec-lowering` invariant 2
for higher rungs; review-time for any rung-3+ raw fragment.

**GRY-ARCH-9 · Deterministic captured SQL.**
> The executor **MUST** sort id collections (`pk__in`/`entity_id__in`) so captured SQL is
> byte-stable across processes.

Reason: Python set iteration is hash-randomized; without sorting the `IN (…)` list churns without
changing results, and every SQL snapshot becomes flaky.
Enforcement: `req-grid-traversal-exec-sql-capture-3`; the Gridkin SQL-snapshot check.

**GRY-ARCH-10 · Scope at every rung.**
> Dimension scoping **MUST** be applied identically no matter how low the query is lowered.

Reason: a rung-4 hand-written CTE that forgets dimension scoping leaks across partitions — the
invariant the ORM enforces for free must be re-earned by hand when you leave it.
Enforcement: `req-grid-traversal-exec-lowering` invariant 3; review-time for higher rungs.

**GRY-ARCH-11 · Canonical result shapes only; no caller-specific views in the executor.**
> Every result **MUST** package through TAP's canonical shapes — the grift graph envelope
> (`{nodes, edges}` + spine / `data` / `display` lanes) or the row-projection shape. The executor
> **MUST NOT** grow caller-specific result shapes. A consumer that needs a different view builds it
> *outside* Gryphon, or a general envelope extension is specified first.

Reason: the envelope is TAP's single structured get-data-out surface — it is *why* APOC-style export
is a near-non-gap for TAP (`doc-gryphon-feature-demand.md` §7.4.1). Letting the executor sprout
bespoke shapes fragments that surface, blinds the capture/oracle discipline (which asserts against the
canonical envelope), and re-creates the per-caller drift the envelope exists to prevent.
Enforcement: `spec-grift-envelope.md`; the subgraph serializer (`tap_grid/grift/subgraph.py`); Gridkin
envelope assertions; review-time. *(Merged from Codex GRY-CMD-19.)*

---

## II. Semantics & Correctness — `GRY-SEM`

**GRY-SEM-1 · The declared schema is the type oracle.**
> A data-lane predicate whose literal type contradicts the field's declared schema **MUST** be
> rejected (`SearchExecutionError`), never coerced and never silently dropped.

Reason: the ORM would mis-coerce `"10"`→`10`; a schema-optional graph *can't* reject, but Gryphon's
typed lane can. This converted two ex-coercion silent-wrong-answer bugs into loud refusals, and it
forecloses the universal-value-type boundary that is AgensGraph/AGE's single largest bug class.
Reaches only as far as the schema declares a concrete type (a bare `{"type":"object"}` blob stays
coercion-tolerant — a named open risk).
Enforcement: `req-grid-traversal-lang-type-strictness`; Gridkin rejection scenarios;
`executor.py::_enforce_type_strictness`.

**GRY-SEM-2 · Null logic is pinned, not "fixed toward Cypher".**
> The null boundary — a **null literal** operand short-circuits to a genuine `FALSE` (2VL), a
> **null field** vs a non-null literal follows SQL 3VL — **MUST** hold, and **MUST NOT** be
> "corrected toward" full Cypher 3VL without a spec change. NULL inputs **MUST** neither crash nor
> silently match.

Reason: this is Gryphon's most load-bearing deliberate divergence. Every peer that scattered null
discipline paid a multi-year tail (RedisGraph 4.5 yrs; AgensGraph 3VL retrofits at HEAD after 10
yrs). The boundary is a design decision with a citation (Francis et al.), not a quirk to iron out.
Enforcement: `req-grid-traversal-lang-is-null` / `-regex-6`; `doc-dev-gryphon-vs-cypher.md` Ledger
B; TLP metamorphic probe; the model oracle implements both regimes.

**GRY-SEM-3 · One null; observation is first-class.**
> `null` means *unobserved*; `""`/`[]` mean *observed-empty*. Gryphon **MUST** preserve the
> distinctions the schema declares (`IS KNOWN`/`IS UNKNOWN`, `x-tap-absence`) and **MUST NOT**
> collapse them into an undifferentiated null.

Reason: Cypher models present-state; Gryphon models observation and provenance as first-class —
this is the differentiator, not an accident. Collapsing it throws away the credit ledger's core.
Enforcement: `req-grid-traversal-lang-observation`; `spec-grid-node.md` (`req-grid-node-observation`).

**GRY-SEM-4 · Fail loud on the ambiguous.**
> When asked something ambiguous, ill-typed, or unsupported, Gryphon **MUST** fail loud (reject),
> never guess a plausible answer.

Reason: a rejection is a gift; a coerced guess is a latent lie. This is the general rule of which
GRY-SEM-1 and GRY-ARCH-3 are instances.
Enforcement: Gridkin rejection scenarios (the rejection-scenario requirement of `spec-gridkin-v0.md`, gryphon_playground plugin repo); review-time.

**GRY-SEM-5 · Result semantics are specified, not incidental.**
> Load-bearing result semantics — inner-join with no lone anchor, row identity, edge-repetition —
> **MUST** be written into the spec and pinned by a scenario, **MUST NOT** be left to whatever the
> executor happens to do.

Reason: "whatever the ORM produced" is not a semantics; the LIMIT-without-ORDER-BY skip is the one
place we accept executor-arbitrary order, and it is *documented* as such. Everything else is pinned.
Enforcement: `spec-grid-traversal-language.md` ("Single-Hop Execution Semantics"); Gridkin scenarios.

**GRY-SEM-6 · Variable scope is local, explicit, and read from the AST.**
> A variable is in scope only where the language says it is. Cross-clause visibility (multi-`MATCH`,
> `OPTIONAL MATCH`, `NOT EXISTS`, future `WITH`, future paths) **MUST** be represented explicitly in
> the AST and pinned by tests. The executor **MUST NOT** patch scope by opportunistically resolving a
> name against whatever bindings happen to sit in executor state.

Reason: opportunistic name lookup is how a predicate silently binds to the wrong variable (or to
none) — the far-node-binding failure is the same silent-wrong-answer class as the envelope-WHERE
defect, but in the *binding* dimension. Scope declared in the AST is checkable; scope reconstructed at
lowering time is a guess, and a guess in a load-bearing read path is a latent lie.
Enforcement: per-clause binding resolution in `executor.py`; Gridkin multi-clause scenarios; the model
oracle (divergence when a predicate binds to the wrong variable); review-time. *(Merged from Codex
GRY-CMD-11.)*

---

## III. Language Surface & Scope — `GRY-LANG`

**GRY-LANG-1 · Cypher-familiar, not Cypher-compatible.**
> Gryphon **MUST NOT** pursue Cypher parity as a goal. It grows by **demand-shape** (a real query
> that needs a construct), not by Cypher's table of contents.

Reason: compatibility invites an unbounded maintenance burden (conformance kits, version tracking,
edge-case parity) below the bar until external demand signals it. The subset shrinks on demand, not
ambition.
Enforcement: `doc-dev-gryphon-wishlist.md`; `doc-dev-gryphon-vs-cypher.md` (Ledger C); review-time.

**GRY-LANG-2 · Ledger every divergence and every credit.**
> Every deliberate divergence from Cypher **MUST** be recorded in the divergence ledger; every
> net-new capability Cypher lacks **MUST** be recorded in the credit ledger.

Reason: an undocumented divergence is a gotcha that bites a Neo4j-trained engineer; an undocumented
subset reads as debt instead of a choice. The ledgers are the "why not just use Cypher?" answer,
tracked as it accrues rather than reconstructed under pressure.
Enforcement: `req-grid-traversal-lang-cypher-divergence` / `-cypher-credit`;
`doc-dev-gryphon-vs-cypher.md`; the docs drift guard.

**GRY-LANG-3 · Read-only surface; writes rejected at parse.**
> Write clauses (`CREATE`/`MERGE`/`SET`/`DELETE`/`REMOVE`) **MUST** be rejected at *parse* time,
> not runtime.

Reason: rejecting semantically-at-runtime produces confusing errors for valid-Cypher writers;
rejecting at the grammar is clear and is the parse-time half of GRY-ARCH-7.
Enforcement: grammar (`grammar.lark` admits no write clause); parser.

**GRY-LANG-4 · Single-clause enforcement; no silent drop of duplicates.**
> A query with more than one `WHERE`/`RETURN`/`ORDER BY`/`LIMIT` **MUST** be rejected loudly at
> parse time, never silently reduced to the first.

Reason: the parser used to keep the first and discard the rest — a query that lied about what it
ran. That silent-drop footgun is closed.
Enforcement: `req-grid-traversal-lang-shape-6`; `parser.py::_ASTTransformer.start`.

**GRY-LANG-5 · Raw-ORM reach is a demand signal, not a workaround.**
> When plugin/application code reaches for raw ORM to query the graph, that **SHOULD** be treated
> as the signal that Gryphon must grow the missing construct — not normalized as an acceptable
> bypass.

Reason: Gryphon is the canonical read path; every raw-ORM graph query is un-oracled, un-scoped, and
invisible to the capture seam. The urge to bypass *is* the feature request.
Enforcement: `feedback_gryphon_over_orm` (agent memory); review-time; the service-layer direct-write
lint (adjacent).

---

## IV. Testing & Validation — `GRY-TEST`

**GRY-TEST-1 · Check the answer, not the artifact.**
> A test **MUST** assert on the *result* (node/edge/row identity), **MUST NOT** assert on SQL text
> or plan shape as a *proxy* for correctness.

Reason: the monument to this rule is the SQL-scrape false-green — a dropped `WHERE` column still
appears in the `SELECT` list, so "column is present" passed on the buggy output. A proxy correlates
with correctness right up until correctness fails. (Asserting on SQL for *stability/determinism* —
the snapshot — is fine; asserting on it for *correctness* is not.)
Enforcement: the model oracle (`_check_oracle`) recomputes the answer; `doc-gryphon-testing-philosophy.md` §4.

**GRY-TEST-2 · Correctness is checked by an independent, zero-shared-code oracle.**
> The reference oracle **MUST** be authored from the language spec and **MUST NOT** import any
> lowering logic from `executor.py`. Zero shared lowering is the guarantee, not a nicety.

Reason: two independent implementations of one spec are unlikely to be wrong the same way on the
same input. The moment the oracle imports an executor helper, their errors correlate and the
differential is worthless.
Enforcement: `gridkin/model_oracle.py` in the gryphon_playground plugin (authored from spec);
the oracle-assertion requirement of `spec-gridkin-v0.md`; review-time (the no-import rule).

**GRY-TEST-3 · Intent-coverage is not path-coverage.**
> A green coverage number **MUST** name what it measures. Every *dispatch path* that implements a
> feature **MUST** be exercised — not merely every *intent* of the feature.

Reason: the same intent ("a WHERE over two bound nodes") maps many-to-one onto executor paths; a
"100% of intents covered" number once sat directly on top of an entirely untested branch (the
envelope-WHERE path). Count paths; fail closed.
Enforcement: the stage-coverage and executor-branch-coverage requirements of `spec-gridkin-v0.md` (floor gate; gryphon_playground plugin repo);
`docs/aar/2026-06-30-gridkin-intent-coverage-not-path-coverage.md`.

**GRY-TEST-4 · Fail loud on the unmodeled.**
> The oracle **MUST** raise `OracleUnmodeled` (and the runner **MUST** skip loudly) for shapes it
> cannot model — it **MUST NOT** silently pass them. Honest partial coverage beats fake total
> coverage.

Reason: an oracle that quietly green-lights what it can't compute is worse than no oracle. The
skip-list is the honest manifest of what is not independently checked.
Enforcement: `model_oracle.py::OracleUnmodeled`; the runner's loud skip.

**GRY-TEST-5 · Oracle-first for every new feature.**
> A new language feature **SHOULD** be modeled in the reference oracle (its semantics pinned)
> *before* the executor lowers it, so the executor is written against an independent check rather
> than defining truth by itself.

Reason: DuckPGQ #67 is the exhibit — a var-length semantic *suspected wrong in writing, open across
releases, because no oracle existed to settle it*. Do not ship a feature whose only definition of
correct is the code that implements it.
Enforcement: `build-gryphon-capability` skill (validation contract); review-time.

**GRY-TEST-6 · A snapshot is a ratchet, not an oracle.**
> Committed golden envelopes/SQL **MUST** be understood as drift protection only. A green snapshot
> **MUST NOT** be cited as evidence of *correctness* — it faithfully protects first-write wrongness.

Reason: AGE/AgensGraph/Kùzu/RedisGraph each shipped headline wrong-answer bugs that survived years
under large golden suites; a bug's fix had to *rewrite* the goldens it had been guarding. The
comparative study's blunt lesson: architecture and differential testing are complements, not
substitutes.
Enforcement: the snapshot-discipline requirement of `spec-gridkin-v0.md` (regen is explicit opt-in); GRY-TEST-2 is the
correctness rung above it.

**GRY-TEST-7 · A Gryphon wrong-answer is never normalized.**
> A Gryphon silent-wrong-answer, silent-drop, or crash **MUST NOT** be worked around, reshaped away
> in callers, or filed as an accepted "known limitation." It **MUST** be surfaced to the user,
> logged in the findings ledger, and reproduced + locked with the test system.

Reason: Gryphon is the load-bearing read path; a wrong result there is not acceptable, and routing
around it hides the defect while leaving it live for the next caller.
Enforcement: `doc-dev-gryphon-wishlist.md` §Known Issues; `gryphon-findings-ledger` (agent memory);
review-time.

**GRY-TEST-8 · Layered defense; no single guarantee.**
> Testing **MUST** be a ladder — snapshot (drift) → oracle-authoring discipline (review) → model
> oracle (mechanical, authoring-independent) → property fuzzer / TLP → fail-closed architecture.
> Add rungs; **MUST NOT** expect one rung to catch a class the rung below it structurally cannot.

Reason: you cannot test your way to proof; each rung catches a class the others miss. This is the
shape of the whole `doc-gryphon-testing-philosophy.md`.
Enforcement: the ladder is built (`req-gridkin-*`, `test_gryphon.py`, `gridkin/fuzz.py`, TLP);
review-time (that new work extends the ladder rather than leaning on one rung).

**GRY-TEST-9 · Pair human review with an authoring-independent check.**
> Human review (necessary, real) is authoring-dependent — it only fires if a human authors *into*
> the buggy path. Any new correctness-bearing change **SHOULD** be paired with a mechanical check
> (oracle, fuzz relation, guard) that fires regardless of what shape gets written.

Reason: the last line of defense must not be the only one. The envelope-WHERE bug was caught by
authoring luck once; the model oracle then caught it mechanically, no luck required.
Enforcement: review-time; the fuzzer/oracle are the mechanical pair.

---

## V. Change Discipline & Process — `GRY-PROC`

**GRY-PROC-1 · Prior art before invention.**
> Before designing a convention (syntax, semantics, a testing pattern), you **SHOULD** search how
> established systems solved it. Inventing a pattern with *no* precedent is a warning sign, not a
> sign of novelty.

Reason: the envelope-path "implicit routing" sugar was rejected precisely because no mainstream
system did it; the comparative study exists because peers' scar tissue is a cheaper teacher than
our next bug.
Enforcement: `feedback-borrow-from-oss-prior-art` / `prior-art-search-discipline` (agent memory);
review-time.

**GRY-PROC-2 · Source-check executor claims before they become work.**
> A claim about how the executor *currently behaves* — in a synthesis, a plan, a review, or a
> commandment — **MUST** be verified against the actual code before it is acted on or ranked.

Reason: this doc's own parent study over-claimed twice (bounded `*1..3` as "shipped" when the
executor rejects it; `NOT EXISTS`/`OPTIONAL` as "Python glue" when they are already ORM
combinators). A code-check caught both. *Check the answer, not the artifact* applies to our
descriptions of the system as much as to its outputs.
Enforcement: review-time; the correction trail in `doc-gryphon-comparative-findings.md` /
`-hardening-roadmap.md` is the worked example.

**GRY-PROC-3 · A work-eliding optimization carries its proof, or is deleted.**
> Any fast path that answers from metadata, elides work, or affects cardinality **MUST** ship with
> (a) a written soundness argument at the site, (b) its own regression corpus, and (c) a fail-closed
> sentinel — or it **MUST** be deleted rather than gated.

Reason: the "transparent optimization that silently returns wrong results" class caught **every**
peer in the study (AgensGraph join-drop, AGE `count(*)` fast path, Kùzu semi-masker, RedisGraph
`reduce_count`, GraphFrames CC revert). AgensGraph adopted exactly this discipline after its
rollback.
Enforcement: review-time — no automated guard yet (candidate: a lint for cardinality-affecting
annotations lacking a soundness note).

**GRY-PROC-4 · Design-note at the enforcement site.**
> The semantics and the *why* of a load-bearing invariant (null handling, edge identity, a dispatch
> choice, a fast-path soundness argument) **SHOULD** be committed as a comment *at the source line*
> a future edit would touch, not only in a spec.

Reason: AGE committed a semantics-and-cost postmortem *into* `age_vle.c` "to prevent future
misdiagnoses." A spec is discoverable; a note at the edit site is *unmissable*. This is the
Player-3 machine-legibility posture applied to the executor.
Enforcement: review-time; `spec-ai-integration.md` (machine-legible-in-source).

**GRY-PROC-5 · Explicit over brevity (LLM era).**
> Prefer explicit, qualified, self-documenting forms (`n.data.tags.Project`, named operators, spelled
> semantics) over terse sugar. The *writer* (often an LLM) does not pay for characters; the *reader*
> (a human in review, or a model debugging) pays for ambiguity.

Reason: the rejected implicit-routing sugar is the case study — keystroke savings for the writer,
opaque-behavior tax for every reader. In an LLM-authored codebase the trade favors explicit.
Enforcement: `feedback-explicit-over-brevity-llm-era` (agent memory); review-time.

**GRY-PROC-6 · A capability ships as one full cycle.**
> A new Gryphon capability **MUST** land as a single coherent change spanning: the spec requirement
> + grammar → AST → parser → executor + Gridkin scenarios with oracle expecteds + openCypher-TCK-mined
> corner cases + `test_gryphon.py` tests. Not as a stub with follow-ups.

Reason: a half-landed capability is an un-oracled, un-specced surface that the next reader mistakes
for finished. The fixed order (grammar→AST→parser→executor) keeps the artifacts coherent.
Enforcement: `build-gryphon-capability` skill; review-time.

**GRY-PROC-7 · Mine the TCK; never port it.**
> The openCypher TCK **MUST** be used only as a *corner-case mine* — scenarios are re-authored in
> TAP's own words with `inspired_by` set to the source folder. TCK query text, graph data, and
> expected results **MUST NOT** be copied.

Reason: the TCK's value is its corner-case taxonomy; its queries encode Cypher semantics Gryphon
deliberately diverges from. Porting them would import the divergences as bugs.
Enforcement: the TCK-inspiration requirement of `spec-gridkin-v0.md`; its TCK-coverage ledger requirement (drift guard); in-core, `req-grid-traversal-lang-tck-mining`.

---

## VI. Security & Safety — `GRY-SEC`

**GRY-SEC-1 · Read-only is a security boundary — protect it.**
> The read-only property (GRY-ARCH-7) **MUST** be treated as a security invariant, not a mere
> feature. No change may open a write path through Gryphon, and the property is what permits stored
> and (future) untrusted-caller Gryphon strings.

Reason: it is the single property that makes a Gryphon string safe to persist on a Search object and
to eventually accept from a satellite caller. Spending it is a security decision, not a feature
decision.
Enforcement: `req-grid-traversal-exec-scope.sec`; read-only Flaw guard; `spec-security-posture.md`.

**GRY-SEC-2 · Substring ops escape; `=~` is explicit regex.**
> `STARTS_WITH`/`ENDS_WITH`/`CONTAINS` **MUST** treat `%`/`_` as literal (escaped) needles; `=~`
> **MUST** be the *only* operator that treats its needle as regex, and that opt-in **MUST** stay
> visible in the WHERE surface. The two **MUST NOT** be blurred.

Reason: promoting regex into the language surfaced the escaping trade-off where it is reviewable,
instead of buried in plugin ORM calls. Blurring them silently turns a literal search into a regex
injection surface.
Enforcement: `req-grid-traversal-lang-string-match-5`, `req-grid-traversal-lang-regex`; Gridkin
scenarios.

**GRY-SEC-3 · Name the residual DoS risk; don't imply completeness.**
> Gryphon **MAY** ship a construct with a known unbounded-cost surface (e.g. `=~` catastrophic
> backtracking) **provided** the residual risk is named in the spec and the mitigation stated
> (`statement_timeout` when configured). It **MUST NOT** imply the surface is fully defended.

Reason: over-restriction relaxes cheaply; omission of a *stated* risk retrofits expensively and
misleads. The honest-risk posture: name what is deliberately left open.
Enforcement: `req-grid-traversal-lang-regex` (Security/DoS section); `spec-security-posture.md`
(`req-sec-honest-risk`).

**GRY-SEC-4 · Lay the cheap foundational edge while the surface is open.**
> When work already touches a surface where a foundational defensive edge (a rejection, a scoping
> check, a parameterization) costs near-zero now but is expensive-to-retrofit later, you **SHOULD**
> lay it — even speculatively.

Reason: the asymmetry is the whole security posture — cheap now, impossible later. Type-strictness,
deterministic capture, and single-clause enforcement were all such edges laid while the surface was
open.
Enforcement: `spec-security-posture.md`; review-time.

---

## Forthcoming Commandments

Rules that are **not yet active** because the capability they govern does not yet exist (or the
enforcing mechanism is unbuilt). Each names its **trigger**. When the trigger ships, promote the
rule into the active set above (giving it a `GRY-<AREA>-<n>` ID), and record the promotion in this
doc's change history. Until then, these are the *intended* commandments — design toward them so the
capability lands already-compliant, but do not cite them as binding on current code.

**GRY-F-1 · Global predicate/attribute conservation.**
> *Once the conservation pass (findings OPP-01) lands:* every predicate leaf and every parsed
> attribute **MUST** be consumed by exactly one lowering site or the query rejects — a **global,
> machine-checked** invariant, not the current per-path convention.
Trigger: OPP-01 implemented. Promotes GRY-ARCH-3 from "partial (single-hop)" to "global, guarded."

**GRY-F-2 · Structural edge-uniqueness / row identity.**
> *Once multi-hop edge-repetition semantics are decided (OPP-03, gated on the A3 cyclic-inflation
> probe):* the semantics **MUST** be specified and the relationship-isomorphism (edge-uniqueness)
> constraint **MUST** be emitted at the chain choke point, so duplicate-edge inflation is
> inexpressible.
Trigger: the cyclic-inflation probe confirms a live class **and** OPP-03 lands. (If the probe is
clean, this is preventive and bundles with E1.)

**GRY-F-3 · Reachability is served by named paths; if var-length is ever built, it lowers in-plan, oracle-first.**
> *The planned reachability mechanism is grid-native **named paths** (a declared trajectory + a
> membership filter), not variable-length traversal* — see `grid-native-paths-notes.md` and
> `doc-gryphon-feature-demand.md` §5.1. When named paths land, "reachable" **MUST** lower to a
> membership/selection over declared path structure, and a path *definition* **MUST** be modeled in
> the oracle before the selection lowers. *If* variable-length `*n..m` is ever built as a separate
> feature, it **MUST** lower *inside* the relational plan (rung-4 `WITH RECURSIVE`) — an out-of-plan
> traversal service with its own cache is **forbidden** — and the oracle **MUST** model bounded
> repetition first.
Trigger: named paths implemented (near-term), and/or E1 variable-length implemented (which may never
happen — the named-path route may subsume the demand entirely). Today `*1..3` correctly
*parses-then-rejects*; that fail-closed rejection is a credit to protect, not a gap to rush
(`executor.py:412,1652`, GRY-TEST-5).

**GRY-F-4 · If an IR is built, invariants at construction; one layer.**
> *Once a logical-plan IR is introduced (OPP-14, on the E1/`WITH` trigger):* there **MUST** be
> exactly one middle layer; invariants (schema/column registry with a *throwing* lookup, per-operator
> declared prerequisites) **MUST** be enforced at operator construction; plan-shape tests are added
> *beneath* — never instead of — the answer/oracle rungs.
Trigger: a logical-plan IR is built. Cytosm is the standing warning (an IR without enforcement
relocates bugs).

**GRY-F-5 · Per-clause WHERE attachment.**
> *Once `WITH` pipelining lands:* the single global `WHERE` (scoped per-variable today) **MUST** be
> replaced by per-clause `WHERE` attachment — each `MATCH`/`WITH` stage carries its own `WHERE`
> applied to that stage's output (Cypher's actual model).
Trigger: `WITH` implemented. Retires the "distinct variable names" workaround
(`req-grid-traversal-lang-shape`, Multiple-WHERE section).

**GRY-F-6 · Write invariants modeled before writes are implemented.**
> *Once graph writes are seriously proposed:* the graph invariants (Entity/Edge referential
> integrity, dimension scoping, FLIP/provenance coherence, no-orphan-edges, and isolation under
> concurrency) **MUST** be modeled (Alloy, then TLA+ for concurrency) *before* the write path is
> implemented — because the read-only credit (GRY-ARCH-7) is being spent and a write bug corrupts
> state permanently.
Trigger: writes on the roadmap. See `doc-gryphon-formal-validation-hot-take.md` §4c / rung 3.

**GRY-F-7 · The oracle derives from a written semantics.**
> *Once the denotational semantics artifact (formal rung-0) is written:* the model oracle **MUST**
> be derived from that written spec, not authored ad hoc from reading `executor.py`'s intent — so
> the semantics is stated once and both the oracle and any future equivalence checker share it.
Trigger: the semantics artifact exists. See `doc-gryphon-formal-validation-hot-take.md` §8 rung 0.

**GRY-F-8 · Known-broken lists are must-fail ratchets.**
> *Once the must-fail ratchet (OPP-11) lands:* every `OracleUnmodeled` skip, fuzz known-issue, and
> dev-validation known-broken entry **MUST** be an *executed-and-must-fail* ratchet, so a silently
> fixed bug or a stale skip lights up instead of hiding.
Trigger: OPP-11 implemented.

---

## Agent pre-flight checklist

Before changing Gryphon (language, parser, AST, executor, capture, Gridkin runner, oracle, fuzz
harness, or a Gryphon-facing spec), an agent **SHOULD** be able to answer these. If it cannot, pause
and gather context before editing.

1. **Which commandment IDs** does this work touch? (Cite them in the design note / PR.)
2. **What demand-shape or bug** justifies the change? (GRY-LANG-1 / GRY-LANG-5 — not parity envy.)
3. **Which spec requirement** owns the behavior? (The spec is authoritative; this doc is doctrine.)
4. **What parsed facts are newly accepted**, and where is each one *applied or rejected*? (GRY-ARCH-3
   — no accepted-but-unused input.)
5. **Which lowering rung** is used, and why is the lower rung insufficient? (GRY-ARCH-2.)
6. **What independent check** proves the answer — model oracle, Gridkin scenario, fuzz replay, TLP
   relation, coverage gate, or rejection scenario? (GRY-TEST-1/2 — not an SQL-text proxy.)
7. **What prior art** was consulted, and what was deliberately *not* copied? (GRY-PROC-1 / GRY-PROC-7.)
8. **What ledger/known-issue/forthcoming entry** should move because of this change? (GRY-LANG-2,
   GRY-TEST-7, the Forthcoming triggers.)

*(Merged from the Codex draft's Agent Checklist.)*

---

## Prior art & lineage

This doc deliberately borrows its *form* from established engineering-doctrine genres, per GRY-PROC-1:

- **RFC 2119 / RFC 8174** — the MUST/SHOULD/MAY keyword vocabulary. Adopted wholesale for fidelity:
  it is the standard way to write requirements a machine reads precisely.
- **C++ Core Guidelines** (Stroustrup & Sutter) — the per-rule structure (stable ID + *Rule* +
  *Reason* + *Enforcement*), and especially the discipline of an **Enforcement** line that ties each
  rule to a checker (or admits none exists). Our `Enforcement:` field is that idea.
- **The Zen of Python** (PEP 20) — the value of a small, memorable set of aspirational principles a
  community can internalize; the counterweight that keeps a rule list from becoming bureaucratic.
- **The Twelve-Factor App** — precedent for a numbered "thou shalt" manifesto that became the
  backbone of a whole domain's practice.
- **SQLite's testing ethos** and **SQLancer's differential/metamorphic program** — the specific
  discipline that a query engine is validated by independent oracles and adversarial generation, not
  by golden files (GRY-TEST-1/2/6/8).
- **Rust API Guidelines** — the checklist-with-stable-IDs format that makes a guideline citable in
  review.
- **Kubernetes API conventions** — the discipline that extension authors need durable conventions,
  common object semantics, *explicit schemas*, and deliberate treatment of unknown / absent state.
  Directly informs GRY-SEM-3 (observation and absence as *declared*, not incidental) and GRY-ARCH-11
  (canonical result shapes). *(Prior-art surfaced by the Codex draft.)*
- **TAP's own standing-filter pattern** (`CLAUDE.md`, `spec-security-posture.md`,
  `spec-ai-integration.md`) — the local precedent for a short doctrine that is *consulted before
  work*, which this doc extends to Gryphon specifically.

## Pointers

- **Behavior (authoritative):** `tap_grid/specs/spec-grid-traversal-language.md`,
  `spec-grid-traversal-execution.md`, `spec-grid-gryphon-multihop-aggregation.md`
- **Test ladder (the why behind §IV):** `doc-gryphon-testing-philosophy.md`
- **Cypher relationship (§III):** `doc-dev-gryphon-vs-cypher.md`
- **Comparative study (source of many commandments + all Forthcoming):**
  `doc-gryphon-comparative-findings.md`, `doc-gryphon-hardening-roadmap.md`,
  `doc-gryphon-formal-validation-hot-take.md`, `comparanda/dossier-*.md`
- **Operational how-to:** `tap_grid/skills/build-gryphon-capability/SKILL.md`
- **Harness:** `plugins/gryphon_playground/specs/spec-gridkin-v0.md`
- **Hotspot map:** `gryphon-findings-ledger` (agent memory)
