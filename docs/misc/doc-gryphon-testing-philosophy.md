---
audience: [llm, developer]
covers:
  - ../../plugins/gryphon_playground/specs/spec-gridkin-v0.md
  - ../../tap_grid/specs/spec-grid-traversal-language.md
assumes:
  - Reader knows what Gryphon is (a Cypher-subset query language that compiles an AST to SQL over TAP's Entity/Edge graph spine)
  - Reader has skimmed spec-gridkin-v0.md (the harness) at least once
provides: |
  The standing philosophy behind how Gryphon is tested — why the methodology is
  shaped the way it is, what each layer catches and (more importantly) what it
  cannot, and the reasoning that took us from committed snapshots to a
  model-based differential oracle. A posterity / orientation essay, not a spec:
  the specs own the contracts; this owns the *why*. Read it once before adding a
  new kind of test to Gryphon, so you extend the ladder deliberately rather than
  re-deriving it.
---

# The Gryphon Testing Philosophy — Layered Defense Against Silent Wrong Answers

> A posterity piece. Written 2026-07-01, the day the model-based reference oracle
> and the single-hop dispatch collapse landed on `main`. It records not just
> *what* we test but *why the methodology has the shape it does* — because the
> shape was earned, one blind spot at a time, and the reasoning is more durable
> than any single test.

## 0. The thing under test is unusual, and that dictates everything

Gryphon is not a database. It is a **compiler**: it parses a Cypher-subset query
into an AST and lowers that AST into SQL (via Django ORM querysets) that runs
against a trusted PostgreSQL substrate — the Entity/Edge graph spine plus typed
per-model domain tables. The database underneath is battle-tested and correct.
Postgres will not return the wrong rows for the SQL we hand it.

So the entire bug surface is **translation fidelity**: does the SQL we generate
*mean the same thing* as the query the user wrote? Every defect Gryphon has ever
had lives in that gap — a `WHERE` that didn't make it into the SQL, a type
coercion that should have been a rejection, a null handled with the wrong logic.
None of them are "the database is wrong." All of them are "we compiled the wrong
question."

This has one enormous consequence that shapes the whole methodology: **we own
both ends of the translation.** We have the source (the query + its AST) *and*
the target (the SQL we emit, and the ground-truth tables it reads). A black-box
database tester can only poke inputs and inspect outputs. We can inspect the
intermediate representation, recompute the intended answer independently, and
diff at every stage. Most of the leverage in what follows comes from refusing to
treat Gryphon as a black box when we don't have to.

The other consequence is the *class* of bug that hurts most. A crash is a good
day — it's loud, it fails a test, someone fixes it. The dangerous defect is the
**silent wrong answer**: a query that returns plausible-but-incorrect data with
no error, no stack trace, no alarm. A subgraph query that quietly returns *all*
the links instead of the filtered subset looks exactly like a correct small
result. The entire methodology is organized around making silent wrong answers
*loud* — structurally, mechanically, and independent of who happened to write
the test.

You cannot test your way to proof of correctness; testing shows the presence of
bugs, not their absence (Dijkstra, and he was right). So the posture is not "one
guarantee." It is **layered defense with loud failures** — a ladder of
independent checks where each rung catches a class the rung below it structurally
cannot. What follows is that ladder, in the order we built it, with the blind
spot that motivated each next rung.

---

## 1. Gridkin: four eyeballable artifacts, real seeding, hard isolation

The foundation is **Gridkin** (`spec-gridkin-v0.md`) — a scenario format where
each test is four committed, human-readable files: a graph fixture (GRIFT JSON),
a Gryphon query, the expected response envelope, and the expected ORM-compiled
SQL. The name nods to Gherkin/Cucumber and openCypher's TCK, but it is
deliberately TAP-shaped, not a port.

Two design choices here are load-bearing and easy to undervalue:

- **Fixtures load through the real GRIFT importer** (the Gridkin runner-contract requirement — this and the RIDs below live in `spec-gridkin-v0.md`, gryphon_playground plugin repo)
  — no test-only seeding shortcut. The data arrives on the same path production
  data does, so the test exercises the real world, not a convenient fiction.
- **Per-scenario isolation** (also runner-contract) — every scenario
  runs against a freshly-seeded database. No inter-scenario state, no order
  dependence, no spooky action. A green scenario means *that query, on that data,
  in isolation* — a claim you can actually reason about.

Everything above this line is about *what* we assert. This line is about making
the assertions trustworthy in the first place.

## 2. Committed snapshots — the regression lock (and what it can't do)

Each scenario commits the expected envelope and the expected SQL as files. The
runner diffs the live output against them (`_check_envelope`, `_check_sql`).
Regeneration is explicit opt-in via `GRIDKIN_UPDATE_SNAPSHOTS=1`
(the snapshot-discipline requirement).

What this catches: **drift.** Once a behavior is pinned, any future change that
alters it lights up as a diff. This is the cheapest, highest-volume safety net we
have, and it is why a refactor as violent as the single-hop collapse (§8) could
be done with confidence — 140-odd committed answers said "you did not change what
anyone can observe."

What this **cannot** catch: **first-write wrongness.** A snapshot only asserts
"the same as last time." If the very first captured answer was wrong, the
snapshot faithfully protects the bug forever. A snapshot is a ratchet, not an
oracle. Which is why the next rung exists.

## 3. Oracle assertion discipline — hand-predict, then read what you got

The Gridkin oracle-assertion requirement is the discipline that the committed envelope must
be **authored and reviewed independently of the executor under test.** You
hand-predict the result *before* looking at what the engine produced, then you
*read the regenerated oracle line by line* and confirm it matches your
prediction. You never trust a captured oracle you didn't read.

This is the rung that has personally caught the most consequential bugs. The
envelope-WHERE defect (§7) was found exactly here: a wrong node leaked into a
regenerated oracle, the human prediction said three neighbors, the file said
four, and that one-row discrepancy unspooled a whole silent-drop bug.

What this **cannot** guarantee: it is **authoring-dependent.** Its power is real
but it only fires if a human happens to author *into* the buggy path and reads
carefully. It is a discipline, not a machine. The last line of defense cannot be
the *only* line of defense — a principle we had to learn the hard way (§7).

## 4. The SQL snapshot — interrogatable evidence, and a false-green trap

Gridkin commits not just the answer but the **SQL the executor emits**
(the explain-snapshot requirement), captured via a dedicated seam
(`explain_gryphon_raw` → `SqlCapture`), stage-labelled and rendered
deterministically. This is unusual — most test suites throw the intermediate
representation away. We keep it because we *own* it, and because a compiler's
intermediate form is where its bugs are visible.

Here lives one of the most instructive lessons in this whole history. When the
envelope-WHERE bug surfaced, the obvious cheap guard presented itself: *for every
scenario whose query carries a `WHERE`, assert the predicate's column appears in
the captured SQL.* It would have caught this bug, it rides entirely on evidence
we already capture, and it is authoring-independent. It sounds perfect.

**It false-greens.** The dropped `WHERE` column still appears in the `SELECT`
list of the generated SQL — so a naive "column is present" scrape passes on the
*buggy* output. We proved this directly. The column was right there in the SQL
the whole time; its presence proved nothing about whether it was *used to
filter*. **Checking the SQL text is not checking the answer.** This is the single
most important negative result in the corpus, and it is why the eventual solution
(§6) recomputes the answer rather than pattern-matching the artifact. Interrogate
the evidence, yes — but interrogate it for the property you actually care about,
not a proxy that correlates with it right up until it doesn't.

## 5. TCK mining + the coverage ledger — indexing the language surface

To find corner cases we don't have the imagination to invent, we mine the real
openCypher TCK (Apache-2.0) for *intent* — clean-room, in TAP's own words, never
porting a single query, graph, or expected result (the TCK-inspiration requirement).
A machine-checked **coverage ledger** (the TCK-coverage requirement,
`gryphon_playground.tck-coverage.json`) tracks, per TCK feature folder, what's
`covered` (derived from scenario breadcrumbs, never hand-stored), what `gaps`
remain (classified `test` / `feature` / `unknown`), and what's deliberately
`excluded` with a reason. A bidirectional drift guard keeps it honest.

This gives us a coverage *number* and a worklist. And it set up the deepest trap
in the whole story, which gets its own section.

## 6. Rejection scenarios and schema-as-oracle — the negative space

Two moves make the corpus assert what should *not* happen:

- **Rejection scenarios** (the rejection-scenario requirement) let a scenario assert
  the query is *refused* (`expected_error: {type, message_contains?}`) rather than
  returning an envelope. Deliberately built *into* Gridkin rather than split off
  into a separate negative-test module — refusal is part of the language's
  behavior, so it lives with the rest of it.
- **Type-strictness** (`req-grid-traversal-lang-type-strictness`): the declared
  schema *is* the type oracle. A cross-type predicate (comparing a field to a
  literal of the wrong type) **rejects** with `SearchExecutionError` rather than
  silently coercing to a plausible-but-wrong result. This converted two
  ex-coercion silent-wrong-answer bugs into loud refusals.

The principle underneath both: **when the engine is asked something ambiguous or
ill-typed, fail loud.** A rejection is a gift; a coerced guess is a latent lie.

---

## 7. The reckoning: intent-coverage is not path-coverage

Then came the insight that reorganized everything, recorded in full in
`docs/aar/2026-06-30-gridkin-intent-coverage-not-path-coverage.md`.

We caught the envelope-WHERE bug — a single-hop relationship *envelope* query
(`MATCH (a)-[:T]->(b)` with no `RETURN`) that silently dropped every non-anchor
`WHERE` predicate, returning too many rows. Good. But we caught it **by luck of
authoring shape.** The same *intent* — "a `WHERE` over two bound nodes" — maps
*many-to-one* onto executor dispatch paths:

| Query shape for the same intent | Executor path | Applied the WHERE? |
| --- | --- | --- |
| envelope, unanchored | `_execute_edge_type_scan` | **No — the bug** |
| envelope, `entity_id`-anchored | `_execute_hub_and_spoke` | anchor only |
| row projection / aggregation | chain executor | **Yes — correct** |

The coverage ledger tracked *which intents were covered*. It said nothing about
*which dispatch paths were exercised*. A "100% of mined intents covered" number
sat directly on top of an entirely untested code branch. Had the author written
the scenario in the aggregation shape (equally valid, equally faithful to the
intent), it would have gone **green** and the bug would still be hiding.

**Mining a spec or TCK for intents proves the language *surface* is covered. It
proves nothing about whether each *implementation* of a feature is exercised.**
Where one feature has several dispatch paths, intent-coverage systematically
under-counts, and a green number over an untested path is a confidence lie — a
metric heard as "behavior verified" when it only asserts "intents enumerated."

That reframe is what set the bar for the fix: not "patch this bug" but "build the
mechanism that would have caught it *regardless of which shape the author
picked*, and would catch the whole silent-wrong-answer class across every path."

## 8. The model-based reference oracle — check the answer, not the artifact

The mechanism is a **second Gryphon engine.**
`plugins/gryphon_playground/gridkin/model_oracle.py` interprets the *same AST*
over *plain Python objects* loaded from the *same fixture*, and it shares **zero
lowering logic** with the production executor — it is authored from the language
spec, never from `executor.py`. Wired as Gridkin's **third assertion**
(`_check_oracle`), it recomputes the expected answer independently and diffs it
against what the executor returned.

This is classic **differential testing**: two independent implementations of the
same specification are unlikely to be wrong in the *same* way on the *same* input.
Where they disagree, at least one is buggy, and you go find out which. The zero
shared code is not an incidental detail — it is the entire source of the
guarantee. The moment the oracle imports a lowering helper from the executor,
their errors correlate and the differential is worthless.

Design choices that make it real rather than a mirror of the bug:

- **Compare the answer by identity** — entity_id sets for nodes and edges, plus
  row values — not by serialization. Format quirks can't hide a wrong result and
  can't manufacture a false one.
- **Fail *loud* on anything unmodeled.** The oracle raises `OracleUnmodeled` for
  shapes it hasn't implemented (bounded multi-hop, display-lane / array field
  paths, aggregates beyond `COUNT`, `LIMIT`-without-`ORDER BY`, …) and the
  assertion *skips* those scenarios rather than silently passing them. Honest
  partial coverage beats fake total coverage. The oracle knows what it doesn't
  know and says so. The Phase-4 deepening (2026-07-01) shrank that skip-list —
  bare-variable `RETURN`, multi-`MATCH` union, `NOT EXISTS`, and the v0 `OPTIONAL
  MATCH` scoreboard are now all modeled, taking oracle coverage of result
  scenarios from 89% to 99% (139/140). The lone remaining skip, `LIMIT` without
  `ORDER BY`, is *deliberate and permanent*: the surviving subset is the
  executor's arbitrary default order, so modeling it would couple the oracle to
  `executor.py` and destroy the zero-shared-lowering guarantee — the one thing
  the differential rests on.
- **Model the backend's real semantics** where they bite — Postgres NULLS-ordering
  under ORDER BY, and the two distinct null logics (see
  `doc-dev-gryphon-vs-cypher.md` and the 2VL/3VL boundary: a null *literal*
  operand short-circuits to genuine FALSE; a null *field* follows SQL three-valued
  logic). An oracle that gets null wrong just diverges on every null case; getting
  it right is what makes divergence *mean* something.

Payoff, observed: the oracle caught the envelope-WHERE defect on day one — the
executor returned four nodes, the oracle computed the correct three, the third
assertion diverged, no human luck required. Then it served as the behavior-
preservation net for the refactor in §9. And, crucially, **the oracle found its
own bugs** during validation (envelope ORDER BY/LIMIT, 2VL `IN`-with-null under
`NOT`, a missing batch node). Expect the reference implementation to need
debugging too — that's not a failure of the method, it *is* the method. Two
implementations grind against each other until they converge on the truth neither
had alone.

## 9. Architecture as a test result: collapse the paths, kill the class

The last move is the one people forget is part of testing. The AAR's other
durable rule was **fail closed at the source**: no dispatch path may accept input
it silently ignores. The envelope path *accepted* a `where_clause` and never
looked at it — a silent-wrong-answer bug with no alarm, by construction.

So the fix wasn't to teach the buggy path to apply the WHERE. It was to **delete
the buggy paths.** The single-hop dispatch collapsed from four executors to one:
`_execute_hub_and_spoke`, `_execute_edge_type_scan`, and the whole `entity_id`-
anchor subsystem are gone; every single-hop pattern now routes through the same
chain machinery (`_build_chain_queryset` + `_apply_predicate_to_qs`) that already
applied the full WHERE correctly. Apply-or-reject — silent-drop is now
**structurally impossible**, not merely tested-against. −389 net lines. (The
semantics were pinned to Cypher's: inner-join, no lone anchor; documented in
`spec-grid-traversal-language.md` → "Single-Hop Execution Semantics".)

This is the highest form of the discipline: the best defense against a class of
bug is an architecture in which that class cannot be expressed. A test proves a
bug is absent *today*; a collapsed, fail-closed dispatch proves it *cannot recur*.
The model oracle is what made the collapse safe to perform — 351 committed answers
and an independent recomputation, all still green, said the behavior was
preserved. Test discipline and architecture are the same craft from two angles.

---

## The principles, distilled

1. **Own the substrate; refuse the black box.** Gryphon is a compiler over
   trusted SQL. We have the source, the intermediate SQL, and the ground truth —
   so we compare at every stage instead of only poking inputs and inspecting
   outputs. Nearly all the leverage is here.
2. **Make silent wrong answers loud.** The crash is the easy case. Organize
   everything around the plausible-but-incorrect result that ships no alarm.
3. **Layered defense, not one guarantee.** Snapshot (regression) → oracle
   discipline (review) → model oracle (mechanical, authoring-independent) →
   fail-closed architecture (structural). Each rung catches a class the one below
   it structurally cannot. Add rungs; don't expect one to do it all.
4. **Check the answer, not the artifact.** The SQL-scrape false-green is the
   monument to this. A proxy that correlates with correctness will betray you at
   the exact moment correctness fails. Recompute the thing you actually care about.
5. **Coverage of intent ≠ coverage of paths.** A green metric names what it
   measures and nothing more. When one feature has many implementations, exercise
   each — and say plainly what the number does *not* assert.
6. **Two independent implementations converge on truth.** Differential testing's
   whole power is the *independence*. Zero shared lowering is the guarantee, not a
   nicety. The reference implementation is allowed — expected — to have its own
   bugs; that's the grind that produces correctness.
7. **Fail loud on the unmodeled.** An oracle that skips what it can't model, and a
   dispatch that rejects what it can't apply, both beat one that quietly guesses.
   Honesty about the boundary is worth more than coverage past it.
8. **Prefer structural impossibility to a test.** When you can collapse the paths
   so a bug class can't be expressed, do that. A passing test says "absent now";
   an architecture says "cannot recur."
9. **The last line of defense must not be the only one.** Human review
   (necessary, real) is authoring-dependent. Always pair "read it carefully" with
   a mechanical check that fires no matter what shape gets written.

## The frontier — toward verifiable completeness

The methodology above is strong but still fundamentally *sampled*: we test the
scenarios we author. The forward research thread (framed in
`doc-gryphon-path-coverage-sprint-plan.md`) asks what *verifiable completeness*
would look like, and the "compiler over a trusted substrate" reframe is what makes
the question tractable. Since this essay was written, the rungs of that thread have
landed — the path/branch coverage gates (the stage-coverage and
executor-branch-coverage requirements), TLP (the metamorphic-TLP requirement), and
now the property fuzzer that closes the sampled-testing ladder:

- **Property-based fuzzing — now built** (the property-fuzz requirement,
  `gridkin/fuzz.py`). The model oracle plus a seedable random-GRIFT-and-query
  generator *is* a property fuzzer: generate a fixture and a query over the oracle's
  modeled surface, run both engines, assert agreement, replay any divergence from
  the seed alone. It paid for itself on the first runs — four real defects the
  authored corpus had never exercised (a `= null` / `!= null` that lowered to
  `IS NULL` / `IS NOT NULL` instead of the two-valued FALSE the spec mandates; a
  single-hop field projection silently ignored by the envelope dispatch; an
  anonymous connecting edge dropped from a bare-variable envelope; and a bug in the
  *reference oracle itself* — union WHERE scoping mis-handling `NOT` over an
  unbound-variable leaf). Each was triaged by evidence and fixed with a
  regression-locking scenario. It also *reproduced* a substantial pre-existing
  executor defect (multi-hop far-node WHERE spawned a duplicate join → row inflation
  and far nodes reached by the wrong edge type) — since **fixed** by folding the
  WHERE into the chain's single `.filter()`, regression-locked by the
  `far_node_where` scenarios, and the generator now emits WHERE on multi-hop chains
  so the fuzzer keeps exercising it. This is the discipline's own lesson turned on
  itself: an authoring-independent generator finds what no hand-authored scenario
  thought to write — including bugs in the checker.
- **Metamorphic / differential oracles from the literature.** SQLancer's **NoREC**
  is our envelope-vs-projection consistency relation — considered, but it does not
  yield a *distinct* check at Gryphon's dispatch layer (single-hop projections
  degrade to envelopes; the target is already covered by the dispatch collapse and
  the oracle), so it is recorded as deferred rather than built. **TLP** (ternary
  logic partitioning) is precisely a probe of our 2VL/3VL null boundary — **now
  built** (the metamorphic-TLP requirement): it partitions each labelled-type-scan
  scenario into TRUE / FALSE / (UNKNOWN) and asserts they reconstruct the
  unfiltered scan, discriminating the null-literal (2VL) from the null-field (3VL)
  case. **PQS** (pivoted query synthesis) guarantees a known row is returned —
  still open.
- **Semantic ground truth.** Francis et al., *"Formal Semantics of the Language
  Cypher"* (SIGMOD 2018, arXiv:1802.09984), is the baseline the model oracle is
  written against; it's the closest thing to a spec we can check *against* rather
  than *derive from ourselves*.
- **Equivalence proofs, aspirationally.** Because we emit the SQL, tools that prove
  SQL-query equivalence (Cosette / HoTTSQL lineage) could one day check our
  compiled output against a reference lowering — proof, not sampling.

We stopped short of all of it on purpose. Naming the frontier is not the same as
building it, and the cheap layers had to come first. But the ladder is built so
the next rungs bolt straight on: the oracle is the differential harness every one
of those techniques needs.

---

## Pointers

- **Harness contract:** `plugins/gryphon_playground/specs/spec-gridkin-v0.md`
- **Language semantics:** `tap_grid/specs/spec-grid-traversal-language.md`
  (esp. "Single-Hop Execution Semantics")
- **The reckoning (AAR):** `docs/aar/2026-06-30-gridkin-intent-coverage-not-path-coverage.md`
- **The bug this all crystallized around:** `docs/misc/doc-gryphon-envelope-where-defect-handoff.md`
- **Forward research frame:** `docs/misc/doc-gryphon-path-coverage-sprint-plan.md`
- **Cypher divergences & null logic:** `docs/misc/doc-dev-gryphon-vs-cypher.md`
- **The oracle itself:** `plugins/gryphon_playground/gridkin/model_oracle.py`
