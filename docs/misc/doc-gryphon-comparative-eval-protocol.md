---
audience: [llm, developer]
covers:
  - ../../tap_grid/specs/spec-grid-traversal-language.md
  - ../../tap_grid/specs/spec-grid-traversal-execution.md
  - ../../tap_grid/specs/spec-grid-gryphon-multihop-aggregation.md
  - ../../plugins/gryphon_playground/specs/spec-gridkin-v0.md
assumes:
  - Reader knows what Gryphon is (a Cypher-subset language that compiles an AST to Django-ORM QuerySets → SQL over TAP's Entity/Edge spine)
  - Reader has read doc-gryphon-testing-philosophy.md (the standing test ladder) and doc-dev-gryphon-vs-cypher.md (the Cypher-relationship ledgers)
  - Reader understands the animating pain: soak/fuzz work still surfaces defects in the data-search layer, and comparison to peer implementations is a distinct evaluation axis from more soak testing
provides: |
  The methodology for a deep comparative study of open-source Cypher-over-relational
  ("compile-to-SQL") implementations, mining their execution strategy, testing
  strategy, and git-history lessons to produce a traceable backlog of concrete,
  ranked improvement opportunities for Gryphon. This doc is the protocol (the how
  and the rubric); the study's outputs (per-system dossiers, the cross-system
  synthesis matrix, the opportunities backlog) are separate artifacts this protocol
  defines the shape of. Re-runnable as new candidate systems emerge.
---

# Gryphon Comparative Evaluation Protocol — Learning From Cypher-over-Relational Peers

> A methodology doc, not a spec. The specs own Gryphon's contracts; this owns the
> *procedure* for mining peer implementations and the *shape* of what that mining
> must produce. Drafted 2026-07-04, before the first study run, so the run executes
> against a fixed rubric rather than an improvised one.

## 1. Why this exists — the comparative axis

Gryphon has an unusually strong *internal* validation ladder already
(`doc-gryphon-testing-philosophy.md`): committed snapshots → oracle-authoring
discipline → a zero-shared-code **model reference oracle** → a **property fuzzer**
→ **TLP** metamorphic checks → coverage/branch gates → a **fail-closed dispatch
collapse**. That ladder is *sampled from within our own understanding of the
problem*. Soak and fuzz campaigns extend the sample, and they keep finding bugs —
which is exactly why a second, *external* axis is worth opening.

Every one of those internal rungs was earned by falling into a hole and climbing
out (the SQL-scrape false-green; intent-coverage ≠ path-coverage; the envelope-WHERE
silent drop). **Peer implementations of the same translation problem have their own
holes-and-climbs, recorded in their commit history, issue trackers, and postmortems.**
The premise of this study: their scar tissue is a cheaper teacher than our own next
bug. The comparative axis buys three things soak testing structurally cannot:

1. **Technique transfer** — validation methods, semantic-handling patterns, and
   architectural moves that peers use and we don't yet, ranked by whether they'd
   catch *our* known bug classes.
2. **Strategy validation / challenge** — an independent read on whether
   compile-to-ORM-then-SQL is the right spine, seen against systems that made the
   same bet (and against one famous system that made the opposite bet).
3. **Predictive hotspot mapping** — where peers historically bled (their fixed-bug
   taxonomy) predicts where *we* will bleed, sharpening the fuzzer and the
   `gryphon-findings-ledger` hotspot map before the bug lands.

**Scope discipline.** This is not a "adopt Cypher-compatibility" project and not a
rewrite. Every output is a *ranked opportunity*, weighed against Gryphon's actual
demand surface (`doc-dev-gryphon-wishlist.md`) and its deliberate-subset choices
(`doc-dev-gryphon-vs-cypher.md`, Ledger C). A peer having a feature is not a reason
to want it; a peer's *bug-and-fix* is worth more to us than a peer's *feature*.

### 1.1 Primary concern — the executor's internal structure (the bottom turtle)

The three lenses are read together, but they are **not weighted equally**. The
load-bearing question this study exists to answer is about **Gryphon's executor
internal architecture — the mechanics of how we translate an AST into relational
work.** Testing is already the strong suit (the whole ladder in
`doc-gryphon-testing-philosophy.md` is built and cooking); more testing is not the
gap. The gap is *structural*: is `executor.py`'s internal shape — AST straight to
ORM QuerySets, no logical-plan IR, dispatch split across type-scan / single-hop /
advanced paths — the right **bottom turtle** to build a stable, reliable base on?

This is the Dijkstra corner directly: *you cannot test your way out of a shaky
architecture.* The internal ladder's own highest rung already says as much — "prefer
structural impossibility to a test" (`§9`, the single-hop dispatch collapse that
deleted three buggy executors instead of testing them). That move worked for
single-hop. **The study's central job is to learn, from peers who solved the same
translation problem, whether the *rest* of the executor wants the same medicine —
a logical-plan IR, further dispatch collapse, invariant-enforcing lowering — so that
whole classes of translation-fidelity bug become inexpressible rather than merely
caught.** Lens E carries that; Lens T and Lens H are in service of it (T: what test
technique *validates an architecture change* and confirms no rung is missing; H:
which architectures peers *regretted* and rewrote, and why). Every opportunity is
ranked with executor-structural impact weighted first.

## 2. The target class — compile-to-SQL / compile-to-relational

The steer that scopes the whole study: **prioritize systems that compile a
Cypher-family query into relational execution** (SQL, relational algebra, or an
ORM/queryset layer), because that is *architecturally what Gryphon is*. A pure-play
native graph engine (its own storage, its own iterator-tree executor) is a weaker
teacher for our translation-fidelity bug surface than a system solving our exact
"does the emitted relational query mean the same thing as the graph query" problem.

Native engines are still worth a **contrast read** — chiefly one that made the
*opposite* architectural bet (RedisGraph's linear-algebra model) as a foil, and one
with an exceptional testing culture (Kùzu) mined for method regardless of storage.
But the center of gravity is the relational-lowering school.

### 2.1 Candidate roster

Confirmed reachable at draft time (`git ls-remote` OK) unless noted. The
discovery pass (§4.1) refreshes and extends this — treat it as a seed, not a
closed set.

| System | License | Lowers Cypher(-ish) to | Relational cousin? | Role in study | Repo |
| --- | --- | --- | :---: | --- | --- |
| **Apache AGE** | Apache-2.0 | Postgres (own executor over `agtype`, in-PG) | Partial (in-PG, not pure SQL transpile) | **Core.** PG-family; the "bolt Cypher onto PG" bet you already distrust — test that instinct against the code. | github.com/apache/age |
| **AgensGraph** | Apache-2.0 (PG fork) | Postgres query plans (Cypher fused into SQL) | **Yes** | **Core.** Closest "Cypher compiled into the relational planner" data point. | github.com/bitnine-oss/agensgraph |
| **DuckPGQ** | MIT | DuckDB relational (SQL/PGQ → joins) | **Yes** | **Core.** Modern SQL:2023 PGQ over a columnar relational engine; nearest living cousin to compile-to-relational. | github.com/cwida/duckpgq-extension |
| **openCypherTranspiler** (Microsoft) | MIT | **SQL text** (openCypher → T-SQL/Spark-SQL) | **Yes — purest** | **Core (confirm in discovery).** A literal Cypher→SQL transpiler; the most direct mirror of Gryphon's compile step. | github.com/microsoft/openCypherTranspiler |
| **Morpheus / Cypher-for-Apache-Spark (CAPS)** | Apache-2.0 (archived) | Spark relational (DataFrames / Spark SQL) | **Yes** | **Core.** Cypher → relational algebra, done by openCypher's own people; rich semantics notes. | github.com/opencypher/morpheus |
| **Kùzu** | MIT | native columnar (own storage) | No | **Method mine.** Included for its testing culture, not its architecture. | github.com/kuzudb/kuzu |
| **RedisGraph** | SSPL (EOL) | GraphBLAS sparse-matrix linear algebra | No (opposite bet) | **Contrast + lifecycle.** The foil; plus a full birth-to-EOL history to read for lessons. | github.com/RedisGraph/RedisGraph |
| **Memgraph** | BSL | native C++ engine | No | **Light semantics read** (docs/paper-first per IP posture; BSL). | github.com/memgraph/memgraph |
| **Cytosm** | (find in discovery) | SQL middleware (Cypher→SQL, academic) | **Yes** | **Discovery target.** GRADES'15 "queries without data migration"; confirm live repo. | — |
| **SQLGraph** (IBM Research) | paper-only (likely) | SQL (relational property-graph store) | **Yes** | **Paper reference.** SIGMOD'15 relational-lowering design; no code expected. | — |

Discovery (§4.1) should actively hunt for more of the *purest* class — Cypher/GQL→SQL
transpilers — e.g. GraphflowDB (Kùzu predecessor), PGQL tooling, GQL/SQL-PGQ
reference implementations, GraphFrames motif-to-SQL lowering, and anything newer.
Proprietary-but-documented systems (Oracle PGX/PGQL, AWS Neptune, PuppyGraph) are
**paper/doc references only**, never code.

### 2.2 Inclusion / exclusion criteria (record the call per system)

Admit a system to **deep** study when it scores on enough of:

- **Relational-lowering relevance** (weightiest): does it translate graph queries
  into SQL / relational algebra / a queryset layer? The purer the transpile, the higher.
- **Source availability + readability** under the IP posture (§6).
- **History richness**: a real commit history, issue tracker, and ideally
  postmortems/design docs — the "holes fallen into" surface.
- **Semantics documentation**: does it write down its NULL/3VL, type-coercion, and
  ordering decisions (the choices that map onto our hotspots)?

Demote to **shallow triage** (a one-paragraph "why not deep") when a system is
native-storage with no relational lowering *and* no standout method to mine, is
paper-only, or is licence-encumbered past what the posture allows. **Every excluded
candidate gets a recorded one-line reason** — an exclusion with no reason reads as
an oversight, per the house rule.

## 3. The three lenses and their rubric (executor-structure primary)

Per §1.1 the lenses are **not equal weight: Lens E (executor internal structure) is
primary and deepest; Lens T and Lens H serve it.** All three read through Gryphon's
one obsession: *translation fidelity — does the emitted relational query mean the
same thing as the graph query?* (`doc-gryphon-testing-philosophy.md §0`). For each
system, answer each lens's questions with **evidence anchors** (a file path + line, a
commit SHA, an issue #, a doc URL). A claim with no anchor is a rumor and does not
enter a dossier. Lens E gets the most reading time, the most anchors, and the most
weight in the opportunity ranking.

### Lens E — Execution / compilation strategy  ★ PRIMARY

Read this lens as *"what is this system's executor made of, and what would ours look
like if it had learned the same lessons."* Beyond the questions below, answer the
**bottom-turtle architecture questions** explicitly for each deep system, because
they are the ones the study exists to resolve:

- **Is there a logical-plan IR between AST and physical execution?** Gryphon lowers
  AST→ORM directly (no IR; the lowering-ladder spec *anticipates* one but hasn't
  built it). Does this system have a logical plan / algebra layer? What does it buy
  them — optimization, a clean place to enforce invariants, testability of the plan
  independent of execution? Is its *absence* a source of their bugs, or is a thin
  transpiler (openCypherTranspiler) fine without one?
- **How is dispatch structured, and did they collapse it?** Gryphon routes by AST
  shape across separate executor paths (type-scan / bare-scan / single-hop / advanced
  `_compute_rows` / `NOT EXISTS` / `OPTIONAL MATCH`) — the exact shape whose
  single-hop corner harbored a silent-drop until it was collapsed to one path. Does
  this system have one uniform lowering or many special-case paths? Has its history a
  "we unified the executor" refactor (Lens H overlap)? **Name Gryphon's next
  dispatch-collapse candidates by analogy.**
- **Where are the invariants enforced?** Read-only, parameterization, dimension
  scoping, canonical-envelope normalization (our lowering-ladder invariants). Does the
  peer enforce its equivalents *at one structural choke point* or re-assert them per
  path? A single choke point is the architecture that makes "someone forgot to apply
  X on this path" inexpressible.
- **Where does fail-closed live?** Can a path in their executor *accept input it
  silently ignores* (the envelope-WHERE bug shape)? What structurally prevents it?

- **Pipeline shape.** Parse → AST/IR → logical plan → physical plan → lowering.
  How many IRs? Is there a logical-plan layer Gryphon lacks (we go AST→ORM directly;
  the lowering-ladder spec anticipates but hasn't built an IR)?
- **The join/traversal lowering.** How is a `k`-hop pattern turned into relational
  work — join chain, recursive CTE, semi-join, worst-case-optimal join (Kùzu/DuckPGQ
  territory), matrix multiply (RedisGraph)? What does *variable-length* lower to
  (our E1 seam)? What does *OPTIONAL MATCH* lower to, and how do they avoid the
  COUNT-inflation trap we footgunned?
- **Predicate placement.** Where does `WHERE` get applied relative to the join —
  and do they have a documented bug where a predicate got dropped or mis-scoped
  (our envelope-WHERE and multi-hop far-node-WHERE scars)?
- **NULL / 3VL handling in the lowering.** How is Cypher's three-valued logic
  emitted into SQL? Where do they short-circuit vs. defer to SQL 3VL (our exact
  2VL-literal / 3VL-field boundary)?
- **Type handling.** Coerce, reject, or defer to SQL? (We reject — schema-as-oracle.)
- **Row-inflation defenses.** How do they keep an aggregate over a multi-join from
  overcounting — the single most recurrent shape in our findings ledger?
- **Determinism / ordering.** How do they make results (and, for us, captured SQL)
  stable? NULLS FIRST/LAST, tiebreaks, `LIMIT`-without-`ORDER-BY`.

### Lens T — Testing / validation strategy

- **Oracle model.** Do they have an independent reference implementation, or only
  self-consistent assertions (the trap our whole ladder is built against)?
- **Differential / metamorphic techniques.** TLP, NoREC, PQS, cardinality
  estimation restriction (CERT), query-plan differential — which, and *what did each
  find*? (SQLancer lineage especially.) Map each against our built rungs.
- **Fuzzing / generation.** Grammar-based query generation, random graph generation,
  shrinking/replay-from-seed. How is the generator kept honest about its own coverage?
- **Corpus & coverage.** TCK usage (port vs. mine), golden/snapshot discipline,
  branch/path coverage gates, mutation testing (did they run it, what survived?).
- **The "check the answer not the artifact" question.** Do they assert on results,
  on plans, on SQL text, or on cardinalities — and where has a proxy false-greened them?
- **Regression capture.** Is every fixed bug pinned by a test? Sample the ratio.

### Lens H — Git history / lessons (the archaeology)

- **Bug taxonomy.** Cluster their fixed correctness bugs by class (predicate drop,
  null logic, join inflation, ordering, type coercion, planner mis-estimate).
  Produce a ranked *"where this system historically bled"* table.
- **Turning-point commits/PRs.** The refactors born of pain — an executor rewrite, a
  planner introduction, a semantics correction. Read the message and the diff shape.
- **Design-doc / RFC trail.** Do they reason in the open? Harvest the reasoning, not
  just the outcome.
- **Lifecycle lessons** (RedisGraph especially): what did the *retrospective on a dead
  project* teach — architectural regrets, maintenance cost, the linear-algebra bet's
  payoff and its limits.
- **Map onto our hotspots.** For each recurring peer bug class, ask: *does Gryphon's
  architecture make this class expressible?* If yes → candidate opportunity. If
  structurally impossible for us (e.g. we can't mutate — half of any peer's write-path
  bugs don't apply) → record as a *credit* for the read-only bet.

## 4. Procedure

### 4.0 Setup

- Clone into scratch, never into the repo tree:
  `CANDIR=<scratchpad>/gryphon-comparanda`. Shallow-clone for source reading,
  but **full history** (`git clone` without `--depth`, or `--filter=blob:none`
  blobless) for any system entering Lens-H archaeology — the history *is* the data.
- One working directory + one dossier file per system:
  `docs/misc/comparanda/dossier-<system>.md` (create the folder). The dossier is
  the durable output; the clone is disposable.
- Record clone SHA + date at the top of each dossier so every anchor is reproducible.

### 4.1 Discovery pass (do first, time-boxed)

Refresh and extend the roster (§2.1). Web-search for Cypher/GQL/SQL-PGQ→SQL
transpilers and relational graph-query compilers; `git ls-remote` each hit to
confirm live; classify each as deep / triage / paper-only with a one-line reason.
Output: the finalized roster table, committed into the synthesis doc (§5).

### 4.2 Per-system dossier (the unit of work)

For each **deep** system, fill the dossier template (§4.4) across all three lenses,
every claim evidence-anchored. Order the deep set by relational-lowering relevance
so the purest cousins (openCypherTranspiler, DuckPGQ, AgensGraph, Morpheus) land
first — their lessons transfer most directly and set the frame for reading the rest.

Archaeology mechanics (Lens H), run in the clone:

```
git log --oneline --all | wc -l                       # scale of history
git log --grep -iE 'fix|bug|wrong|incorrect|inflat|null|predicate|dedup|regress'
    --oneline                                          # correctness-fix stream
git log -S '<lowering symbol>' --oneline               # evolution of a hot function
git shortlog -sn                                       # who held the knowledge
# issue tracker via gh/API: closed bugs labelled correctness/query/semantics
```

Cluster the correctness-fix stream into the bug taxonomy; for the top classes read
the actual fix diff and the surrounding discussion.

### 4.3 Synthesis & opportunity extraction (the payoff)

Collapse the dossiers into **one cross-system synthesis** plus a **ranked
opportunities backlog** (§5). This is where peer findings become Gryphon actions.
Each opportunity is a structured record (§5.2), traced back to its evidence anchor
and forward to the Gryphon surface it touches (a wishlist bucket, a testing-ladder
rung, a hotspot-ledger row, or a new spec RID). **Rank executor-structural
opportunities first (does it make a bug class inexpressible / does it fix the
bottom-turtle architecture?), then by expected defect-catch on our known bug
classes, then by cost.** A structural fix that foreclosures a class outranks a test
that catches it.

### 4.4 Dossier template

```
# Dossier — <System>   (clone <sha>, <date>, license <x>)

## Snapshot
one-paragraph what-it-is, its Cypher-relational bet, why it's in the study,
inclusion score against §2.2.

## Lens E — Execution
- pipeline shape / IR count
- join & traversal lowering (k-hop, var-length, OPTIONAL, aggregation)
- predicate placement + any documented drop/mis-scope bug   [anchor]
- NULL/3VL lowering                                          [anchor]
- type handling                                             [anchor]
- row-inflation defenses                                    [anchor]
- determinism/ordering                                      [anchor]
- ★ transferable to Gryphon: ...

## Lens T — Testing
- oracle model (independent reference? or self-consistent?)  [anchor]
- differential/metamorphic techniques + what each found      [anchor]
- fuzzing/generation + shrinking                             [anchor]
- corpus/coverage/TCK/mutation                               [anchor]
- answer-vs-artifact posture; any proxy false-green          [anchor]
- ★ transferable to Gryphon: ...

## Lens H — History
- scale (commits/age/contributors)
- bug taxonomy table (class → count → representative SHA)
- turning-point commits/PRs                                  [anchor]
- design-doc/RFC trail                                       [anchor]
- lifecycle/retrospective lessons                            [anchor]
- ★ predicted Gryphon hotspot(s): ...

## Net read
3–5 sentences: biggest thing to steal, biggest thing to avoid, one credit
(something Gryphon already does better / a class our architecture forecloses).
```

## 5. Outputs

### 5.1 Artifacts

1. **Per-system dossiers** — `docs/misc/comparanda/dossier-<system>.md`, one each.
2. **Cross-system synthesis** — `docs/misc/doc-gryphon-comparative-findings.md`:
   the finalized roster, a **capability/technique matrix** (rows = technique or
   semantic decision; columns = systems + a "Gryphon today" column), and the
   narrative reads per lens. The matrix is the at-a-glance "who does what, where do
   we sit."
3. **Opportunities backlog** — the ranked list of §5.2 records, embedded in the
   synthesis doc (or its own file if long). This is the deliverable that justifies
   the study.

### 5.2 Opportunity record shape

Each opportunity is machine-legible and traceable (Player-3 discipline — an AI or a
human should be able to read the record and act):

```
OPP-<nn>
title:        short imperative ("Add NoREC-style envelope/projection differential")
lens:         E | T | H
source:       <system> @ <sha/issue/doc anchor>          # where we learned it
gryphon_gap:  what we lack / do differently, in one line
maps_to:      wishlist-bucket | testing-ladder-rung | hotspot-ledger-row | new-spec-RID
bug_class:    which of our known classes it defends (or "new capability")
structural:   does it make a bug class inexpressible / fix executor architecture? (yes/no + one line)
port_or_mine: mine (reimplement from understanding) — always, per IP posture
effort:       S | M | L   (+ one-line why)
rank_score:   structural-impact (primary) → expected-catch-on-known-bugs → inverse-effort
recommendation: adopt-now | prototype | defer-with-trigger | reject-with-reason
```

`reject-with-reason` is a first-class outcome. A peer technique that doesn't fit our
demand surface or duplicates a rung we already have is a *recorded decision*, so a
future reader doesn't re-litigate it (the same courtesy `doc-dev-gryphon-vs-cypher.md`
Ledger C pays for deliberate-subset omissions).

## 6. IP / clean-room posture

**Mine ideas, never copy code. Cite everything.** This mirrors the existing
"TCK: mine, never port" discipline (the Gridkin TCK-inspiration requirement, `spec-gridkin-v0.md` in the gryphon_playground plugin repo). Concretely:

- Read source freely across licenses (Apache/MIT/BSD/SSPL/BSL) **for understanding**.
- Every technique that lands in Gryphon is **reimplemented from the described
  concept**, in TAP's own idiom — never a code lift, never a line-for-line
  translation. An opportunity's `port_or_mine` field is always `mine`.
- Restrictive-license systems (RedisGraph SSPL, Memgraph BSL) lean on
  papers/docs/blogs first; source reads are for comprehension of *approach*, and
  nothing derived from them ships as copied structure.
- Dossiers cite the anchor (SHA/file/issue/paper) so provenance of every idea is
  auditable. If a technique has an academic name (TLP, NoREC, PQS, WCOJ), cite the
  paper, not just the repo.

## 7. Guardrails — the traps this study must not fall into

Earned from Gryphon's own history; do not re-pay for these:

1. **Feature-envy ≠ demand.** A peer clause we lack is not automatically an
   opportunity. Weigh every candidate against the demand-shape rule
   (`feedback_gryphon_over_orm`) and the deliberate-subset ledger. The valuable
   import is usually a *bug-and-fix* or a *test technique*, not a feature.
2. **Don't re-import a rung we already have.** We have a differential model oracle,
   a property fuzzer, TLP, snapshot discipline, coverage gates. Credit them; look
   past them for what's *missing* (NoREC was considered and deferred with a reason —
   PQS and CERT are still open; mutation testing and equivalence proofs are named
   frontier). Read `doc-gryphon-testing-philosophy.md §The frontier` first so we
   hunt the gaps, not the filled rungs.
3. **Their bug may be structurally impossible for us** (anything on a write/mutation
   path; anything from schema-optional coercion we reject). Record those as
   *credits*, not opportunities — evidence the read-only + typed-lane bets pay off.
4. **Intent ≠ path, again.** When importing a test technique, ask what *dispatch
   path* it exercises in our executor, not just what *intent* it covers. The
   category error that hid the envelope-WHERE bug is the one to not repeat.
5. **Anchor or it didn't happen.** No dossier claim without a SHA/file/issue/paper.
   An unanchored "system X does Y" is exactly the kind of plausible-but-unverified
   assertion the whole methodology exists to reject.
6. **Check the answer, not the artifact** — applies to *reading* peers too. "Their
   README says they test X" is an artifact; find the test and read what it asserts.

## 8. Execution notes (how to run it)

- **Parallelism.** The per-system dossiers are independent — a natural fan-out. The
  study can run one agent per deep system (each doing discovery-anchored clone +
  archaeology into its dossier), with synthesis (§4.3) reserved for a single pass
  that reads all dossiers together. This is a good place to take **Fable 5** for a
  ride: one Fable-5 agent per candidate, Opus synthesizing. The dossier template
  (§4.4) *is* each agent's brief.
- **Verification.** Synthesis claims and the top-ranked opportunities get an
  adversarial verify pass — a skeptic agent re-checks each load-bearing anchor
  actually says what the dossier claims, before it enters the backlog. Same posture
  the internal ladder takes toward its own findings.
- **Order.** Discovery (§4.1) → purest-cousin dossiers first (openCypherTranspiler,
  DuckPGQ, AgensGraph, Morpheus) → contrast/method reads (RedisGraph, Kùzu) → light
  reads (AGE deep-dive to test the "kludge" instinct; Memgraph doc-first) →
  synthesis → opportunities → verify.

## 9. Done-test

The study is complete when:

- Every roster candidate is classified deep / triage / paper-only **with a reason**.
- Every deep system has a dossier with all three lenses filled and every claim anchored.
- The synthesis carries the technique matrix and a per-lens narrative.
- The opportunities backlog exists, every record has the §5.2 fields, is ranked by
  expected-catch-on-known-bugs × inverse-effort, and every `reject`/`defer` carries a reason.
- At least the top-ranked opportunities are verified (§8) and mapped to a concrete
  Gryphon surface (wishlist bucket / testing rung / hotspot row / new spec RID),
  so the study ends pointing at buildable work, not at a reading list.

## Pointers

- **Test ladder & frontier:** `doc-gryphon-testing-philosophy.md`
- **Cypher relationship (divergences/credits/subset):** `doc-dev-gryphon-vs-cypher.md`
- **Demand-shape roadmap:** `doc-dev-gryphon-wishlist.md`
- **Hotspot map:** `gryphon-findings-ledger` (agent memory) + `docs/misc/doc-gryphon-envelope-where-defect-handoff.md`
- **Language / execution specs:** `tap_grid/specs/spec-grid-traversal-language.md`, `spec-grid-traversal-execution.md`, `spec-grid-gryphon-multihop-aggregation.md`
- **Harness:** `plugins/gryphon_playground/specs/spec-gridkin-v0.md`
</content>
</invoke>
