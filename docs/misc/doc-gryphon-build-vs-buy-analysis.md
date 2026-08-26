---
audience: [human, llm, developer]
covers:
  - ../../architecture.md
  - ../../plan/road-products.md
  - ../../tap_grid/specs/spec-grid-search.md
  - ../../tap_grid/specs/spec-grid-traversal.md
  - ../../tap_grid/specs/spec-grid-traversal-language.md
  - ../../tap_grid/specs/spec-grid-traversal-execution.md
  - doc-dev-gryphon-vs-cypher.md
  - doc-dev-gryphon-wishlist.md
  - doc-gryphon-comparative-findings.md
  - doc-gryphon-networkx-opportunity.md
  - doc-gryphon-battle-hardening.md
  - doc-gryphon-hardening-roadmap.md
  - comparanda/dossier-cyp2sql.md
  - ../../plugins/gryphon_playground/specs/spec-gridkin-v0.md
  - doc-gryphon-build-vs-buy-stream.md
status: working-analysis
created: 2026-07-07
provides: |
  A structured build-vs-buy analysis for continuing TAP's SQL-backed graph plus
  Gryphon path versus switching to, or adding, a Cypher graph database such as
  Memgraph, Neo4j, or Apache AGE, with a parallel Gryphon v2 rewrite included
  as a third strategic option.
---

# Gryphon Build-vs-Buy Analysis

## Decision Frame

TAP currently stores graph state in a SQL-backed grid:

- `Entity` is the canonical spine for TAP-managed nodes and edges.
- Concrete node types are Django `BaseModel` subclasses with typed fields and
  one-to-one backing `Entity` rows.
- Edges are first-class TAP objects with their own backing `Entity` rows.
- Dimensions live on `Entity`.
- Writes flow through the service layer and GRIFT.
- Gryphon is the canonical graph read/query interface.

The live question is whether TAP should continue investing in this model and
Gryphon, or switch to / add a Cypher-native graph engine such as Memgraph,
Neo4j, or Apache AGE. A third option is now explicitly on the table: build a
new Gryphon v2 implementation in parallel, from the disciplined semantics and
validation doctrine now emerging, then compare it against the current engine as
a drop-in replacement candidate.

This is not a comparison of "homegrown query language" versus "real graph
database" in the abstract. The relevant question is whether an external graph
engine can replace Gryphon's role while preserving the things TAP's architecture
is explicitly optimized for: typed SQL models, service-layer writes, GRIFT,
dimensions, provenance, read-only stored queries, local/offline deployment,
future authorization, and LLM-legible canonical contracts.

## Near-Term Roadmap Check

The active Rampart step is launch-ready Rampart by 2026-07-18: auth, boot,
installable plugins, and first AI integration over the samsite/Rampart story.

Changing the canonical graph store or adding a second graph database is not on
that critical path. It would introduce:

- data migration or projection logic;
- dual-write or rebuild semantics;
- boot/profile changes;
- deployment and backup complexity;
- authZ/security integration;
- new validation machinery;
- a second query semantics surface.

Recommendation for the current roadmap window: do not switch storage/query
architecture. Continue the current Gryphon hardening and use governed
query-specific relief valves if a launch-critical query outruns the language.

A Gryphon v2 rewrite can be explored only as off-critical-path research with no
mainline dependency. It should not become a new Rampart blocker.

## Local Evidence

The repository history supports a clear story:

- `architecture.md` makes SQL-backed graph state a differentiator: graph
  capabilities while retaining SQL's typed, ACID, operationally hardened base.
- `spec-grid-search.md` now treats Gryphon/Search as the canonical graph-read
  interface; raw ORM and bespoke modules are break-glass.
- `spec-grid-traversal-language.md` says Gryphon is Cypher-familiar but not
  Cypher-compatible, and every deliberate divergence is tracked.
- `spec-grid-traversal-execution.md` says Gryphon compiles through a
  TAP-controlled plan, currently Django ORM QuerySets on the `search_readonly`
  alias, with a lowering ladder for future escalation.
- `doc-dev-gryphon-vs-cypher.md` records where Gryphon goes beyond Cypher:
  observation semantics, declared absence, dimensions, and lane-aware field
  paths.
- `doc-gryphon-comparative-findings.md` validates the core bet: compile into a
  trusted relational substrate where possible; bugs concentrate where execution
  leaves that substrate or duplicates glue paths.
- `doc-gryphon-battle-hardening.md` and `spec-gridkin-v0.md` already define the
  shape a parallel implementation would need to survive: independent lowering,
  model-oracle comparison, deterministic expected envelopes, SQL snapshots,
  fuzz/metamorphic checks, and disagreement capture.
- The cyp2sql dossier is the cautionary prior-art case. A near-cousin project
  rewrote its Cypher-to-SQL translator and fixed the failures the author could
  name, but preserved the untested representation/validation diseases. A
  rewrite is therefore valuable only to the extent the validation net rejects
  the old mistakes.
- The current row-materialization refactor in `spec-grid-traversal-execution.md`
  is exactly the right kind of cleanup: delete duplicate row tails, keep the ORM
  plan as the borrowed IR, and make cross-cutting row features land once.

The bad news is also clear: Gryphon's executor grew organically and contains
implementation debt. The good news is that the debt now has a diagnosis and a
doctrine: shrink Python glue, centralize shared backends, reject unsupported
syntax, and validate through Gridkin/model-oracle/fuzzing rather than intuition.

## Options

### Option A: Continue SQL Entity Spine + Gryphon As Canonical Read Surface

Summary: Keep TAP's current source of truth and invest in Gryphon as a
constrained, read-only compiler over Django ORM/Postgres, not as a general graph
database.

Strengths:

- Preserves typed Django models and SQL constraints.
- Preserves the service layer, GRIFT, OCC, hotlinks, tombstone semantics, and
  future provenance/authZ surfaces.
- Keeps graph reads over the same canonical data, without synchronization.
- Keeps deployment simpler than a multi-database architecture.
- Keeps the SQLite/cold-start door less closed than an external graph service
  would.
- Lets TAP diverge from Cypher where TAP has genuine domain reasons:
  observation semantics, dimensions, spine/data/display lanes, typed-lane
  strictness, read-only-by-construction.
- Lets external validation target translation fidelity: AST/QuerySet/SQL result
  versus model oracle.

Costs:

- TAP owns query semantics and compiler correctness.
- Gryphon can produce silent wrong answers if unsupported constructs are
  accepted but not applied.
- The executor needs continued structural cleanup.
- Advanced reachability/path algorithms are likely poor fits for plain ORM
  lowering.

Use when:

- TAP's main queries are typed operational/compliance/security questions over
  TAP-managed entities.
- Query shapes are relationally expressible: match/filter/project/aggregate over
  bounded joins.
- The service-layer/GRIFT/provenance/dimensions contract is more important than
  generic Cypher compatibility.

This is the recommended path for v0.

### Option A2: Build Gryphon v2 As A Parallel Clean-Room Replacement

Summary: Keep TAP's SQL entity spine and public Gryphon contract, but build a
new executor/compiler in parallel from the written semantics, validation
corpus, and current architectural lessons. Treat it as a drop-in replacement
candidate, not a mainline dependency until it wins against the current engine.

Strengths:

- Preserves TAP's storage architecture while attacking executor debt at its
  source.
- Can be developed off the critical path by multiple coding agents or teams.
- Forces the public Gryphon contract, internal seams, and test oracles to become
  explicit enough for independent implementation.
- Enables bake-offs between independent lowerings: parser/binder/planner,
  QuerySet lowering, row materialization, envelope shaping, and diagnostics.
- Opens a future differential-execution posture: current Gryphon primary,
  Gryphon v2 shadow, disagreement recorded before customer-visible trust is
  moved.
- Makes the current engine more valuable as an oracle target and regression
  reference even if it is eventually replaced.

Costs:

- A rewrite is not a correctness proof. It fixes the bugs the implementers can
  name and preserves the assumptions the validation net cannot see.
- Multiple implementations can share common-mode failures if they share the
  same ambiguous spec, same insufficient fixtures, same ORM assumptions, or same
  model-oracle blind spots.
- Parallel engines create governance burden: which one is authoritative, how
  disagreements are triaged, and when a shadow result is allowed to block or
  influence a product answer.
- A "best component from every contender" mosaic can collapse into accidental
  incompatibility unless the seams are formal: AST, binding context, logical
  plan/queryset contract, materializer contract, result-shaping contract.
- Maintaining two engines permanently would recreate the two-source-of-truth
  problem at the query layer.
- It can steal attention from launch-critical hardening if treated as rescue
  work instead of a bounded research/validation program.

Safe shape if ever adopted:

- Start with a v2 charter/spec, not code: public API compatibility, supported
  grammar, semantic deltas, non-goals, and acceptance gates.
- Build clean-room from specs and tests, not by porting or copying executor
  internals.
- Require zero-shared lowering for any bake-off implementation that claims
  differential value.
- Use Gridkin expected envelopes, the model oracle, SQL snapshots,
  fuzz/metamorphic tests, and disagreement reports as the gate.
- Shadow-run read-only and off-request first. A disagreement should create a
  finding or Flaw, not silently choose whichever engine looked nicer.
- Promote in stages: v1 primary/v2 shadow, then canary, then v2 primary, then
  retire v1 or keep it only as a bounded diagnostic oracle.
- Mix components only across declared seams. Do not splice arbitrary internals
  from one contender into another.

Use when:

- The current executor keeps producing bugs whose root cause is architectural
  path duplication rather than missing local tests.
- Upcoming features such as `WITH`, `COLLECT`, variable-length paths, or richer
  aggregation force a real planner/binder seam anyway.
- The spec/test surface is strong enough that an independent implementation can
  be judged without trusting the old executor.
- There is parallel agent capacity that does not slow launch-critical work.

This is a credible future middle path: more coherent than endlessly renovating
v1, much less disruptive than replacing TAP's storage with a graph database.
It is not the current v0 critical path.

### Option B: Replace TAP Storage With Neo4j Or Memgraph

Summary: Use a graph database as the canonical source of truth.

Strengths:

- Mature graph query engine.
- Native path traversal and graph algorithm ecosystem.
- Familiar Cypher surface for graph engineers.
- Potentially stronger out-of-the-box support for graph-specific workloads.

Costs:

- Replaces the core SQL/Django model instead of merely replacing Gryphon.
- Weakens or removes TAP's typed table guarantees.
- Requires rebuilding service-layer write semantics over a graph database.
- Requires remapping GRIFT, dimensions, field schemas, entity spine metadata,
  tombstones, OCC, edge entities, and provenance.
- Complicates the local/offline/single-container direction.
- Makes Django ORM no longer the central application substrate for graph state.
- Neo4j property values do not store nested maps as properties; maps are
  constructed/returned values, while stored property values are property types
  and only homogeneous lists of simple types are storable.
- Memgraph supports nested `Map`/`List` property values, but its BSL and
  Enterprise feature split need legal/product review for a commercial embedded
  platform.

External facts:

- Neo4j property/constructed type docs:
  <https://neo4j.com/docs/cypher-manual/current/values-and-types/property-structural-constructed/>
- Memgraph data types:
  <https://memgraph.com/docs/fundamentals/data-types>
- Memgraph storage modes:
  <https://memgraph.com/docs/fundamentals/storage-memory-usage>
- Memgraph license:
  <https://github.com/memgraph/memgraph/blob/master/LICENSE>
- Memgraph Enterprise features:
  <https://memgraph.com/docs/database-management/enabling-memgraph-enterprise>

Use when:

- TAP becomes primarily a graph-database product rather than a typed
  systems/compliance platform.
- The SQL/Django/service-layer model is no longer the source of TAP's leverage.
- Cypher compatibility becomes a hard product requirement.

This is not recommended for the current architecture.

### Option C: Add Memgraph/Neo4j As A Secondary Graph Mirror

Summary: Keep SQL as source of truth, project TAP graph state into a graph
database for Cypher queries and/or algorithms.

Strengths:

- Retains SQL canonical store.
- Gives access to native graph algorithms and a broader Cypher surface.
- Can be rebuilt from GRIFT/Entity state if treated as a derived index.

Costs:

- Adds synchronization, rebuild, drift detection, backups, deploy, and
  authorization complexity.
- Creates two query semantics surfaces.
- Risks becoming a silent parallel source of truth.
- Any query result that feeds compliance/security decisions must be validated
  against TAP semantics.
- Requires a formal read-model spec and operational guardrails.

Safe shape if ever adopted:

- Treat the graph database as a derived, read-only projection.
- Rebuild from TAP source of truth, not dual-write as an equal authority.
- Scope it to algorithmic/path workloads that SQL lowering cannot handle
  cheaply.
- Keep GRIFT/TAP entity IDs as the identity bridge.
- Version the projection schema.
- Add drift checks and differential tests.
- Do not expose arbitrary Cypher as a trusted app surface without authZ and
  resource controls.

Use when:

- There are repeated, high-value graph algorithm demands:
  shortest path, blast radius, centrality, communities, flow, deep reachability.
- The cost of implementing those in SQL/ORM exceeds the cost of maintaining a
  bounded derived graph backend.

This is plausible later, but not now.

### Option D: Use Apache AGE Inside Postgres

Summary: Use AGE's Cypher extension for PostgreSQL.

Strengths:

- Keeps Postgres operationally.
- Offers Cypher-like graph querying inside the same database server.
- Avoids running a separate graph database service.

Costs:

- AGE exposes Cypher through a `cypher(...)` SQL function returning records,
  with values in `agtype`, a custom type described by AGE as a superset/custom
  implementation of JSONB.
- Querying moves outside normal Django ORM semantics.
- TAP would still have to map typed BaseModel/entity/edge state into AGE's graph
  model.
- It introduces a second graph abstraction inside Postgres rather than
  strengthening TAP's existing SQL graph.
- The result is not really "Gryphon but maintained by someone else"; it is a
  different storage/query model with its own types and semantics.

External facts:

- Apache AGE overview:
  <https://age.apache.org/>
- AGE Cypher query format:
  <https://age.apache.org/age-manual/master/intro/cypher.html>
- AGE `agtype`:
  <https://age.apache.org/age-manual/master/intro/types.html>

Use when:

- TAP explicitly wants a Postgres-resident external graph engine and accepts
  `agtype`/Cypher as the graph model.

This is not recommended for TAP's canonical graph path. It is worth keeping as a
research reference for future reachability work, not as the near-term answer.

### Option E: Add NetworkX/Rustworkx/Algorithm Backend For Bounded Subgraphs

Summary: Keep Gryphon as the selector. Materialize a bounded subgraph from TAP
and run graph algorithms in an analytical backend.

Strengths:

- Clean division of labor: Gryphon selects; algorithm backend computes.
- Avoids turning Gryphon into a graph-algorithm engine.
- Avoids storing canonical data in another database.
- Fits read-only execution.
- Can start with NetworkX and hide the implementation behind a seam if later
  scale demands rustworkx/igraph/graph-tool/cuGraph/pgRouting/etc.

Costs:

- Still introduces a second execution engine.
- Requires snapshot semantics, caps, result shapes, validation, and deterministic
  behavior for randomized algorithms.
- Not suitable for unbounded whole-grid analysis without serious controls.

Use when:

- The demand is explicitly algorithmic, not pattern-matching:
  shortest path, k-shortest path, centrality, communities, flow, reachability.

This is the best future complement path.

## Comparison Matrix

| Criterion | SQL + Gryphon | Gryphon v2 Rewrite | Neo4j/Memgraph Primary | Graph Mirror | Apache AGE | Algorithm Backend |
| --- | --- | --- | --- | --- | --- | --- |
| Preserves typed Django models | High | High | Low | High | Medium/low | High |
| Preserves service-layer writes | High | High | Low | High if derived | Medium/low | High |
| Avoids state sync | High | High | High | Low | Medium | High |
| Cypher compatibility | Low by design | Low by design | High | High | Medium/high | Low |
| Native graph algorithms | Low today | Low unless added | High | High | Medium | High |
| Deployment simplicity | High | Medium during transition | Medium | Low | Medium | Medium/high |
| Licensing/product risk | Low | Low | Medium/high | Medium/high | Low/medium | Low/medium |
| Local/offline/cold-start fit | High | High after cutover | Low/medium | Low | Medium | Medium/high |
| TAP-specific semantics | High | High if spec-gated | Low | Medium if carefully projected | Medium/low | High |
| Near-term roadmap fit | High | Low now / medium later | Low | Low | Low | Medium later |

## Key Architectural Points

### 1. The SQL Graph Is Not The Problem

The current pain comes from Gryphon executor debt, not from the SQL-backed graph
model itself. The entity spine remains coherent:

- nodes and edges have identity;
- edges can themselves participate as first-class entities;
- dimensions live in one place;
- typed rows keep domain fields structured;
- service-layer writes remain enforceable;
- graph reads can compile to ordinary SQL plans for the common case.

Switching to a graph database does not remove complexity. It relocates it into
projection, synchronization, schema mapping, authZ, and product licensing.

### 2. Gryphon Should Stay A Compiler, Not Become A Database

The sustainable version of Gryphon is narrow:

- read-only;
- demand-gated syntax;
- no broad Cypher compatibility claim;
- ORM/Postgres as the trusted substrate;
- higher lowering rungs only when forced;
- no premature logical-plan IR;
- no caller-specific result shapes;
- reject unsupported constructs loudly.

The failure mode to avoid is accidentally implementing a general graph database
in Python. The commandments and lowering ladder exist to prevent that slide.

### 3. Cypher Familiarity Is Useful, Compatibility Is Expensive

Cypher syntax buys readability. Full compatibility buys a maintenance burden:
version tracking, semantic parity, TCK expectations, function library pressure,
write clauses, path semantics, null behavior, and compatibility bugs.

TAP has already chosen deliberate divergences:

- read-only by construction;
- explicit spine/data/display lanes;
- typed data-lane strictness;
- observation predicates (`IS KNOWN` / `IS UNKNOWN`);
- dimension-aware paths;
- null semantics pinned to TAP's model, not full Cypher 3VL.

Those are not cosmetic. They are why a TAP-owned dialect exists.

### 4. Memgraph Is A Real Candidate For A Future Backend, Not A Drop-In Escape

Memgraph deserves respect in this analysis. It supports maps/lists as
properties, has ACID transactional modes, has built-in traversal algorithms, and
has MAGE. It is the most credible external challenge to "we need our own graph
path."

But adopting it as primary storage would be an architectural rewrite. Adopting
it as a mirror would add a second source of query truth. Using it as a bounded
analytics backend remains plausible, but only after a concrete workload justifies
the operational and licensing cost.

### 5. Query-Specific Relief Valves Are Product Safety, But Need Governance

A direct ORM/module implementation can be the right way to make a high-value
query correct quickly. The rule should be:

- allowed for specific product-critical queries;
- validated independently;
- logged as a Gryphon demand signal;
- not silently multiplied;
- retired or kept deliberately once Gryphon grows.

This aligns with the battle-hardening thesis: particular accuracy for a real
decision beats abstract language purity.

### 6. Gryphon v2 Is A Validation Program Before It Is A Replacement

A parallel rewrite is most attractive when framed as a way to force the system's
semantics into executable public contracts. It should make the old engine and
new engine disagree loudly under controlled conditions, not create two quiet
ways to return answers.

The useful production idea is differential confidence, not consensus theater.
If v1 and v2 disagree, TAP has found a thing to investigate. If v1 and v2 agree,
TAP has more confidence, but not proof: both engines can share the same wrong
assumption. Independent model oracles, hand-authored Gridkin expectations,
metamorphic tests, and SQL/result snapshots remain necessary.

The prior-art lesson from cyp2sql is blunt: a rewrite fixes named problems and
conserves untested problems. The validation net is the asset. The rewrite is
only a way to put more pressure on that net.

## Recommendation

Continue with TAP's SQL entity spine and Gryphon as the canonical graph-read
surface.

Do not switch to Memgraph, Neo4j, or Apache AGE as the canonical store.

Do not add a second graph database for general Cypher querying in the current
roadmap window.

Do not start Gryphon v2 as a launch-blocking rescue project. Keep it as a
deliberate parallel/research option once the current semantics and validation
surfaces are stable enough to judge it.

Proceed with the current Gryphon implementation work, because it is addressing
the right root cause: executor structure and validation, not feature polish.

Adopt this explicit posture:

1. Gryphon is a constrained, read-only TAP query compiler.
2. The Django ORM/Postgres plan is the borrowed IR until a real feature forces a
   lower rung.
3. New language features are demand-gated and oracle-first.
4. Query-specific modules are governed relief valves, not a parallel read
   architecture.
5. Gryphon v2, if started, is a drop-in contender judged by shared oracles, not
   a second permanent query path.
6. External graph engines are future analytical/read-model backends, not primary
   storage, unless a separate architecture decision says otherwise.

## Revisit Triggers

Reopen this decision if one or more of these become true:

- Rampart/customer work repeatedly needs shortest path, blast radius, centrality,
  communities, flow, or variable-length reachability over large subgraphs.
- Gryphon's language maintenance cost starts crowding out product delivery.
- Query-specific ORM/module relief valves become common enough that "canonical
  read path" is no longer honest.
- Current-Gryphon fixes repeatedly require broad shape-by-shape surgery instead
  of landing behind shared compiler/materialization seams.
- Upcoming language features force a binder/planner boundary large enough that
  a clean v2 contender is cheaper to reason about than incremental renovation.
- There is enough parallel agent capacity to build v2 without stealing attention
  from launch-critical Rampart work.
- A customer or plugin ecosystem requires Cypher/GQL compatibility as a product
  feature.
- Postgres query plans for bounded graph traversals become a measured
  performance blocker, not a predicted fear.
- Memgraph/Neo4j licensing and deployment are intentionally accepted for a
  commercial TAP deployment shape.
- TAP's product direction shifts from typed systems/compliance graph to graph
  analytics database.

## Near-Term Action Items

- Finish the row-materialization refactor before DISTINCT.
- Land DISTINCT through the shared row backend, not through per-shape tails.
- Keep `WITH` and `COLLECT` as the next likely language investments, but only
  after the current materialization seam proves out.
- Treat variable-length paths and shortest path as a distinct-backend/algorithm
  trigger, not a reason to hand-roll traversal machinery now.
- Keep adding Gridkin/model-oracle coverage before executor changes.
- Make `gryphon explain` / SQL visibility easy for humans before growing the
  language much further.
- Define the governance rule for query-specific module relief valves before
  they become informal habit.
- If v2 stays attractive after the current refactor, write a one-page Gryphon v2
  charter before any implementation: compatibility surface, required seams,
  acceptance gates, shadow-mode rules, and retirement criteria for v1.

## Bottom Line

The best reason to keep Gryphon is not sunk cost. It is that Gryphon is the
query surface over TAP's actual architecture, and TAP's architecture is not a
plain property graph. It is a typed, service-layered, SQL-backed graph with
dimensions, provenance ambitions, GRIFT interchange, and edge entities on the
same spine as nodes.

The best critique is also valid: owning a query compiler is dangerous. The way
to make the choice sane is to keep Gryphon smaller than Cypher, push execution
into the trusted SQL substrate, invest in validation, and use external graph
tools only at clean, demand-proven boundaries. A Gryphon v2 rewrite may become
the right way to reset the implementation, but only if it is judged by a
stronger oracle net than the one that allowed v1's original executor shape to
grow organically.
