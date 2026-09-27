---
audience: [developer, llm]
status: RESEARCH DOSSIER — not a spec, not an ADR, nothing here is built
captured: 2026-09-21
covers:
  - docs/misc/grid-native-paths-notes.md
  - docs/misc/grid-native-paths-soc.txt
  - docs/misc/graph-lookup-performance-notes.md
  - docs/misc/trace-overlay-on-system-model-seam.md
  - docs/misc/doc-gryphon-feature-demand.md (§5.1, §7.3)
  - tap_grid/specs/spec-grid-edge.md (req-grid-edge-nono)
  - tap_grid/specs/spec-grid-traversal-language.md
  - Issue# 141 - tap, Issue# 259 - tap, Issue# 499 - tap
provides: |
  A long-form research dossier on persistent paths: what TAP has already said,
  what the rest of the world has learned about representing "the way through"
  a graph, and a rigorous evaluation of the path-as-node design including the
  edge-to-edge question. Ends with a stated recommendation and the conditions
  that would falsify it.
---

# On the Way Through: A Dossier on Persistent Paths

> *"The Tao that can be told is not the eternal Tao."* — which is a fine
> sentiment for a philosopher and an absolute menace for someone trying to
> write a database schema.

## Preface: how to read this, and how to trust it

This is a long document. It is long on purpose, because the question it
addresses — *should a path be a thing the grid stores, and if so what kind of
thing* — is one of those questions that looks small from the outside and turns
out, on inspection, to be load-bearing for about six other capabilities. Get it
right and cascades, blast radius, build provenance, vuln triage, and the
visualisation layer all get cheaper. Get it wrong and TAP acquires a slowly
rotting cache of assertions about a graph that has since moved on, which is
the database equivalent of a map with "HERE BE DRAGONS" written over a suburb
that was developed in 1987.

**Method labels.** Every claim in this document carries one of three labels,
because the alternative is a confident-sounding document that quietly
interpolates. This follows the house convention already used in
`docs/misc/doc-grid-dimension-prior-art.md`.

| Label | Meaning |
| --- | --- |
| **READ** | I fetched and read the primary source — this repo's tree at the cited path, or the cited project's own published documentation |
| **RAN** | I executed something and this is the output |
| **INFERRED** | A conclusion I drew from READ facts. It is mine, not the source's |
| **UNVERIFIED** | Believed, plausible, useful, and *not* checked against a primary source. A lead, not a fact |

Where a whole section is one label, it says so at the top. Where a single
sentence differs from its section, it is labelled inline.

**Three negative results, stated up front**, because their absence shaped the
argument and a reader deserves to know what I looked for and did not find:

1. **No shipping graph database stores a path as a first-class persistent
   entity.** Not Neo4j, not any of the twenty engines checked, not any of the ten
   already dossiered in `docs/misc/comparanda/`. The single design that does — 
   **G-CORE**, from the LDBC task force that fed into ISO GQL — was never
   implemented in a production engine, and I could find no prototype (which is a
   failure to find, not a proof of absence). Paths are *values* produced by
   queries and discarded. This is either a gap TAP can exploit or a warning
   everyone else heeded, and Movement III is largely about telling those two
   apart.
2. **No published post-mortem exists of a persistent-attack-path product
   admitting what staleness cost it.** Vendors market attack paths; none
   publishes the invalidation bill. The staleness argument below is therefore
   argued from mechanism, from source code, and from adjacent traditions (MPLS
   reconvergence, Reactome identifier policy) — not from a war story. The closest
   thing to one is Microsoft silently narrowing its attack-path generator and
   retiring the published type catalogue to a redirect, which customers could not
   detect *because* nothing was persisted.
3. **The one community that has genuinely solved persistent named paths at
   scale did it with human curators and a release train**, not with automatic
   invalidation. That is Movement II's most uncomfortable finding, it is discussed
   at length in §II.6, and the two mechanisms worth borrowing from it are
   precisely the two that are automatic rather than curatorial.
4. **No benchmark anywhere compares edge-to-edge against reified-node.** If TAP
   wants that number, TAP will have to produce it.

---
# Movement I — What We Have Already Said

*Section method: **READ** throughout, from the worktree at
`/Users/george/tap-sessions/demo-dev` on branch `feat/736-export-grift`, and
from the `unified-systems-com/tap` issue tracker via `gh` (**RAN**). Every
quotation is verbatim. Where I characterise an idea as load-bearing or
passing, that judgement is **INFERRED** and labelled.*

There is a particular pleasure in reading your own old notes. It is the
pleasure of discovering that a past self, who did not know what you know now,
nonetheless left the door propped open with a brick. There are several bricks
here. There are also two places where the past self cheerfully wrote down a
thing that later work has quietly overtaken, and one place where a ruling made
in July contradicts — or at least sharply narrows — a ruling sketched in June.
All three are flagged.

## I.1 The thesis, and where it actually comes from

The canonical statement lives in `docs/misc/grid-native-paths-notes.md`,
captured 2026-06-14 from a stream-of-consciousness note preserved alongside it
as `grid-native-paths-soc.txt`. The notes are explicit about their own status:

> "This is a thinking document, not a spec, not scheduled implementation, and
> not an architecture decision record. Its purpose is to preserve the shape of
> the idea so a later spec pass can pick it up cleanly."

The thesis itself:

> "Paths are a first-class data construct on the grid. TAP already has graph
> objects and graph traversal, but it does not yet have durable, named,
> queryable representations of 'the way through' a system."

And the argument for why that matters, which is the sentence the whole
capability hangs from:

> "A graph can show territory: entities and their relationships. A path can
> show a route, process, dependency chain, blast radius, ownership chain,
> workflow, or flow of meaning through that territory."

The raw note is blunter and, I think, better:

> "Without it we have a map of the territory and it's on the reader to decide
> what to do with it. With paths we have a way to add a critical layer of
> depth beyond Vanavar Bush's 'it's the connections between things that are
> important' from as we may think. He's right of course, but the paths through
> those connections matter...a lot."

That Bush reference is doing more work than it looks like. *As We May Think*
(1945) proposed the memex, and the specific memex feature that mattered was
not the microfilm — it was the **trail**: a named, persistent, shareable
sequence of documents that a researcher builds by walking, and which another
researcher can then walk. Bush called the person who made them a *trail
blazer*, and he explicitly imagined trails being bought, sold and inherited.
So the intuition here is not merely adjacent to Bush; it is arguably Bush's
actual proposal, which hypertext then dropped on the floor for eighty years
because a trail is much harder to store than a link. **INFERRED**, but I would
defend it: the notes cite Bush for *connections*, when the stronger citation
available is Bush for *trails*, and the stronger citation is also a warning —
trails are the memex feature nobody successfully shipped.

The compact framing is the one to keep:

> "TAP maps the Tao. Paths are the feature that makes a map of 'the way'
> possible as a standardized, robust, flexible, first-order capability rather
> than as a reader's private interpretation layered over raw nodes and edges."

## I.2 The three candidate representations, faithfully

The notes name three. They are not presented as competitors — the document is
careful to say so — and that carefulness turns out to be the most useful thing
in it.

### Candidate 1 — Persistent Path Nodes

> "In this model, a path is represented by a TAP-managed node entity. That path
> node has ordered step edges to each entity participating in the path. Step
> ordering and path-local metadata live on those step edges."

Benefits claimed, verbatim: identity on the grid; nameable, taggable,
describable, versionable, visualisable, protectable; "finding a known path does
not require re-running a traversal query"; Gryphon can search paths as ordinary
graph objects; metadata lives in normal graph structures "rather than in an
opaque side table."

Then the crux, and it is worth quoting in full because it is the sentence this
entire dossier's third movement exists to interrogate:

> "The hard part is representing a true node-edge-node walk. If a path step
> needs to include both the node and the edge traversed from that node, the
> path must be able to point at edges as path participants.
>
> That implies relaxing the current convention that TAP edges connect only node
> entities. Since edges are already first-class graph objects with their own
> backing Entity rows, this is not structurally impossible. It is a convention
> TAP set early, and paths may be the first use case that justifies a narrow,
> well-specified exception."

The stream-of-consciousness version is more cheerful about it:

> "the fun thing about building our own graph database layer is that this is
> actually possible - the only thing keeping us from making edges to edges is a
> convention we set early on, which we can relax for this specific use case."

**This is factually correct about the substrate, and I verified it.** See §I.6.

### Candidate 2 — Embedded Path Membership

> "In this model, a named path may still be represented by a node, but each
> Entity also carries a first-order path membership object. Conceptually, this
> might be an `Entity.paths` field that records which paths the entity
> participates in and where it appears within them."

The justification is an argument from company: paths belong on Entity because

> "paths feel like dimensions, history, and FLIP: cross-cutting grid
> infrastructure rather than plugin-domain payload."

Benefits: fast path-aware traversal without loading typed BaseModel rows;
cheap "what paths is this entity part of?"; and — the one that matters most —
"a natural foundation for service-layer behavior such as cascades, protection,
validation, and path-aware deletes."

The notes then name the motivating example that has since become the live one:

> "a model/edge declaration could say that `application - RUNS_ON ->
> ec2_instance` establishes an ownership or reliance path. Deleting the EC2
> instance could then delete, tombstone, block, or warn on associated
> applications according to declared path semantics."

### Candidate 3 — Traversed or Generated Paths

> "This is closest to the way graph databases commonly expose paths today: a
> path is the result of a traversal query."

And critically:

> "This does not need to compete with persistent path nodes or embedded path
> membership. It may be the primary mechanism by which those structures are
> created and maintained."

with the loop closed as: user or plugin defines a pathfinder/pathmaker query →
Gryphon executes it → result "can be inspected directly, materialized into a
path node, embedded as Entity path membership, or refreshed on a schedule."

**INFERRED, and I think this is the single most important structural insight
in the June notes**: Candidate 3 is not a third option. It is the *production
mechanism* for Candidates 1 and 2, and the June notes already knew it. Any
design that treats the three as a menu has misread the source.

## I.3 The rest of the June notes, in order of how much they will bite

### Load-bearing

**Branch and loop addressing.** The sketch is dotted notation —
`path.branch:step.branch:step` — with `loop:step` for cycles. The notes are
admirably suspicious of their own sketch:

> "This needs prior art before it becomes a TAP-specific design."

and:

> "TAP should avoid choosing a notation that only handles the simple case while
> pretending it solved paths."

That warning is the correct one and Movement II supplies rather a lot of prior
art for it, most of it saying "don't invent a notation; the shape you want is
an ordered membership relation plus a successor relation, and every tradition
that tried to encode structure in a string regretted it."

**Broken paths and path protection.** Two modes are named and both are wanted:

> "Non-breaking/protected paths, where certain mutations are refused or require
> explicit override.
>
> Break-detecting paths, where mutations proceed but the system records that a
> critical path was damaged."

The proposed reporting channel is the Flaw surface. **This is a mis-fit and it
should be caught now rather than in the spec pass.** `specs/spec-tap-flaw-v0.md`
is explicit (**READ**): "A Flaw is a detected *should-never-happen* condition:
an invariant that TAP's own design guarantees, violated at runtime… If a 'Flaw'
can fire during correct operation, it is miscategorized." A user deleting an
EC2 instance that a named path runs through is *correct operation*. Routing it
to Flaws would violate the Flaw spec's Goal 5 ("A Flaw that fires in normal
operation is a bug in the Flaw, not a Flaw in the system") on day one. Path
breakage needs its own signal — and there is already a shaped precedent for one
in Issue# 668 - tap / Issue# 659 - tap, the `grid__cascade_failure` node type
and its "what went wrong" view. **INFERRED**: path breakage should be a grid
record like a cascade failure, not a Flaw.

**Cross-dimensional paths.** The notes spot the real hazard, which is not
access control but inference:

> "A partial path can accidentally reveal that hidden structure exists, even
> when it does not return the hidden object."

This is the classic inference channel and it is genuinely hard; Movement II
finds only one tradition that has faced it squarely.

**Actions on paths / cascades.** Named as "probably where embedded path
membership has its strongest first use case." It was right, and that is now the
live thread (§I.5).

### Genuinely useful but second-order

**"Paths on paths."** Walk forward, walk backward, follow one branch, compare
two paths, treat a branch as a first-class object. The notes are honest that
"the exact use cases are not yet clear, but the capability feels powerful
enough that the initial design should avoid closing the door." I read this as
a *don't-preclude* constraint rather than a requirement, and Movement III
treats it as such — which turns out to matter, because one of the candidate
designs precludes it and one does not.

**Gryphon implications.** A list of seven affordances (fetch a named path;
traverse from a node along a path; filter within a path result; return
traversal order; return path membership in a subgraph; execute and store
pathmaker queries; materialise a traversal into persistent structure). Plus a
discipline note worth keeping:

> "This should stay canonical in Gryphon, not become a one-off ORM search helper
> or plugin-specific graph traversal module."

**Visualisation.** Glow/highlight, overlay lines, fade the background, recolour,
stack overlays, walk as an animation. The document's own verdict: glow handles
one path well, overlay lines stack. Fun, real, and entirely downstream of the
data model — which the notes say themselves ("it should still follow the data
model rather than inventing separate visual-only path semantics").

### Passing thoughts

The `Entity.paths` JSON shape; the specific dotted notation; the list of
visualisation treatments; the "better name needed" on path-nodes. These are
placeholders, explicitly marked as such by their own document, and nothing
should be inherited from them but the questions.

## I.4 The July amendment: structural containment as the first target

On 2026-07-08 a section was appended naming a concrete first proving ground:
AWS structural containment. The reasoning is the best paragraph in the file
(**READ**, verbatim):

> "'What thing is inside what other thing' is the canonical reified-path
> concept: it is inherently *transitive and derived* (a task is inside a service
> is inside a cluster is inside an account), so it belongs at the path level,
> not as a single asserted edge. During the aws_core cleanup we deliberately
> declined to model a generic `CONTAINS` edge — a single-hop assertion of a
> multi-hop concept that also duplicated the specific edges already present —
> and instead broke it into specific parent→child relationships."

Three rulings fall out of that section and all three survive into Movement III:

1. **Normalised direction.** Parent→child, uniformly, so "what contains X" is
   the same walk reversed. One canonical edge, traversed both ways, rather than
   reverse-twin edge types.
2. **Containment is a DAG, not a tree.** "a subnet is inside both a VPC (address
   space) and an AZ (physical location), so a node can have multiple containment
   parents — the path layer must expect that." This single sentence kills a
   large family of tempting simplifications.
3. **A deferred edge-classification hook.** The notes want paths to select edges
   *by class*, not by a hardcoded slug list:

   > "The clean way for the path layer to gather this family is a shared
   > classification on the edges themselves — an edge `kind`/tag such as
   > `structural: containment` — so paths select containment edges by class
   > instead of a hardcoded slug list. We are **not** changing the edge model now
   > to add that tag."

   That paragraph is explicitly "the placeholder for that decision." It is
   still a placeholder. It is also, **INFERRED**, the highest-leverage single
   decision in the whole capability, because it determines whether a path
   definition is a *predicate over edge classes* (composable, survives edge
   renames, reusable across plugins) or *a list of slugs* (brittle, per-plugin,
   and exactly the hand-rolled-per-query shape §7.3 of the feature-demand study
   criticises APOC for).

## I.5 What has happened since — and the ruling the June notes do not contain

This is the part where the archaeology stops being polite. Two later documents
materially change the picture, and a reader who only read the June notes would
walk into the implementation with a wrong model.

### The July ruling: reachability by declared membership, not by traversal

`docs/misc/doc-gryphon-feature-demand.md` §5.1, dated 2026-07-06, is headed
**"Reachability will be served by named paths, not variable-length traversal
(planned, per George)"** (**READ**). It is worth quoting at length because it is
a *plan*, not a musing:

> "the **planned implementation replaces reachability-by-traversal with
> reachability-by-declared-path membership** — a deliberately cheaper route that
> sidesteps E1's recursive-CTE, the heaviest wishlist item. **Named paths become
> first-class declared structure**, and 'what is reachable' collapses into
> 'select the elements on named path *P*' — an indexed membership filter, not a
> query-time graph walk."

And it names three implementations *in order*:

> "1. **Module / model-defined paths** — a module declares its trajectory along a
> named path at the model level; path membership can also be carried *through an
> edge* (an edge type asserts the path).
> 2. **User-defined paths** — users mark, in a node/edge *field*, that the element
> exists along a named path (instance-level annotation).
> 3. **Dynamic grid-level path types** — path types definable dynamically on the
> grid at runtime."

With consequences stated:

> "var-length `-[*n..m]-` stays parse-but-reject (fail-closed) and is *not* on
> the near-term path; the reachability demand it represents is met by the
> named-path primitive instead. `shortestPath` (true least-cost / centrality) is
> a separate concern and still routes to the analytics backend."

**This is a significant narrowing of the June notes and it must be carried into
the spec pass.** In June, Candidate 3 (traversal) was named as the likely
*production mechanism* for Candidates 1 and 2. In July, traversal is explicitly
taken off the near-term road and declaration replaces it. The July position is:
paths are **declared**, not **discovered**. The June position was: paths are
**discovered and then materialised**.

Those are different systems. They have different failure modes (a declared path
is wrong when reality diverges from the declaration; a discovered path is wrong
when the discovery is stale). They have different staleness answers. They need
different validation. **INFERRED, and stated as my own reading**: the July
ruling is the stronger one for the near term and Movement III backs it — but it
inherits a problem the June notes did not have, which is that a declared path
has no automatic way of noticing it has become a lie. Movement II calls this the
prospective/retrospective split and it is the single most transferable idea in
this document.

Also worth keeping from §7.3: the observation that APOC's `expandConfig` knobs —
`relationshipFilter`, `labelFilter`, `sequence`, uniqueness modes, min/max
depth, node allow/deny lists — are "*literally an inline trajectory definition,
re-specified every call*", and are therefore the field-tested vocabulary that a
*declarative* named-path definition should express once.

### The September ruling: cascade table first, embedded paths second, and they must agree

Issue# 499 - tap (**RAN**: `gh issue view 499`) records a ruling from
2026-09-17 that is the most concrete plan anyone has written for paths:

> "The declared-containment table behind `req-grid-service-delete-cascade` is a
> half-built version of **embedded path membership** — Candidate 2 in
> `docs/misc/grid-native-paths-notes.md`. The plan:
>
> 1. **Build the cascade table first**, as specified.
> 2. **Then embed path information in the models** from the same containment
> declarations. This is the first real use of embedded paths, and it produces
> the closure paths that cascade deletion walks.
> 3. **The two implementations must agree.**"

with the discipline that makes it worth something:

> "**Don't derive one implementation from the other.** A path closure computed
> by calling the cascade evaluator (or the other way round) will always match,
> so the comparison would test nothing. They have to share the declaration and
> nothing else."

This is the Gridkin model-oracle pattern applied to paths, and it is the right
shape. It also leaves three questions open, quoted from the issue:

- **"Where the declaration lives."** On the model (`req-grid-entity-cascade`),
  or as an edge classification (the July notes' deferred `structural:
  containment` kind)? "Both implementations have to read one declaration."
- **"Representation."** "path membership stored on `Entity`, or only the closure
  computed on demand."
- **"Multi-parent semantics."** "When a child has two containing parents and
  only one is retired, does it stay live?"

That third one is the DAG caveat from July arriving with a bill.

### The May precedent nobody has connected to paths yet

`docs/misc/trace-overlay-on-system-model-seam.md` (2026-05-29, **READ**) is
about observability, not paths, and it contains a ruling that bears directly on
path persistence. The ladder it walks reaches step 3:

> "**The temptation we resisted (again):** logging/telemetry **to the grid**.
> Spans/datapoints as Entity rows is a category error. Keep resisting."

and settles on a division of labour:

> "**Grid holds the map** — an authored/derived model of TAP's own architecture…
> Stable, low-cardinality. TAP's home turf.
> **Jaeger holds the journeys** — OTel spans, local-only… High-cardinality,
> ephemeral. Jaeger's home turf.
> **The visualization is the join** — … Computed at view time, **never persisted
> to the grid.**"

**INFERRED, and I think it is the most important unremarked precedent in the
repo**: TAP has already ruled, in a neighbouring domain, that *the stable
low-cardinality structure goes on the grid and the high-cardinality instance
journeys do not*. A path **type** ("the deploy path for service X") is a map. A
path **instance** ("the 14,332nd execution of the deploy path, at 09:14 on
Tuesday") is a journey. If the same rule holds — and I will argue in Movement
III that it should — then path instances are the thing most likely to blow up
the grid and the thing the design should most carefully decline to store.

That document also names the failure mode to design around, and the phrasing
transfers exactly:

> "a cold node must distinguish **'this code genuinely never ran'** from **'this
> code isn't instrumented yet.'** … otherwise empty silently reads as dead, and
> the pretty picture lies in exactly the seductive way."

Substitute "this path is broken" for "this code never ran" and "we haven't
re-evaluated this path since Tuesday" for "isn't instrumented yet" and you have
the staleness UX problem in one sentence.

## I.6 Ground truth: what the substrate actually permits

*Section method: **READ** from source at the paths cited; **RAN** for greps.*

The June notes say edge-to-edge is "not structurally impossible." That is
correct, and here is exactly how correct.

**Edge is a BaseModel, so every edge has an Entity row.** `tap_grid/models.py:1033`:

```python
class Edge(BaseModel):
    """Directed, typed relationship between two entities.

    Edges ARE entities (inherit BaseModel → OneToOne to Entity).
    "No edges between edges" is a service-layer rule, not a schema constraint.
    """
```

**The endpoints are plain FKs to Entity, with no type restriction**
(`tap_grid/models.py:1070-1079`):

```python
    from_entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name="edges_out")
    to_entity   = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name="edges_in")
    edge_type   = models.CharField(max_length=255, db_index=True)
    properties  = models.JSONField(default=dict, blank=True)
```

**The prohibition is four lines of Python in the service layer.**
`tap_grid/services/_impl.py:605-609`:

```python
            # Step 7: Graph invariant — no edges between edges.
            if from_entity.entity_type == "edge":
                raise ServiceConstraintError("Edges cannot have other edges as endpoints (from_entity is an edge).")
            if to_entity.entity_type == "edge":
                raise ServiceConstraintError("Edges cannot have other edges as endpoints (to_entity is an edge).")
```

duplicated as a legacy-contract pre-check in `tap_grid/services/__init__.py:1564-1568`.

**And the spec says so out loud.** `tap_grid/specs/spec-grid-edge.md`,
`req-grid-edge-nono`, status `Implemented`:

> "Edges model relationships between things, not between relationships. Allowing
> edges whose endpoints are themselves edges collapses the model into a
> hypergraph with significantly higher traversal complexity. This rule keeps the
> graph semantically flat."
>
> "This is a service-layer rule only. The database schema does not enforce it —
> `from_entity` and `to_entity` are plain ForeignKeys to `Entity` with no check
> constraint on `entity_type`. A connection created by bypassing the service
> layer will be accepted by the DB."

So: the June note's claim is exactly right. The cost of edge-to-edge *at the
storage layer* is zero. The rule is a deliberate semantic fence with a stated
rationale ("collapses the model into a hypergraph"), three acceptance criteria,
and a named test class. Movement III's job is to decide whether that rationale
survives contact with the prior art. (Spoiler, stated here so the reader can
argue with me for the next forty pages: **the rationale survives, but not for
the reason the spec gives.**)

**Gryphon cannot do variable-length traversal today, and this is decisive for
sequencing.** `tap_grid/specs/spec-grid-traversal-language.md` (**READ**) lists,
under "Grammar-accepted but executor-REFUSED with a named error":

> "- path bindings: `p = (a)-[:EDGE]->(b)` — rejected at the dispatch fork in
> `_execute_gryphon_raw_impl` (a bound path has no consumer: no `RETURN p`, no
> path functions)…
> - bounded traversal `-[e:EDGE_TYPE*1..3]->` and its anonymous form `-[*1..3]-`
> — rejected in the chain executor ('grammar-accepted but not supported'). Ships
> with #259, together with path binding, because the corpus demand consumes them
> as one shape (`MATCH p = shortestPath(...) RETURN p`)."

There is also no multi-`MATCH` join (`req-grid-traversal-lang-shape-7`,
`Proposed`, ruled 2026-09-11 as *not on the road*), which means Gryphon today
unions rather than joins across MATCH clauses.

**INFERRED, and this is a sequencing fact the design must respect**: TAP is
proposing to build *persistent* paths on a substrate that cannot yet compute an
*ephemeral* one. In every other system surveyed in Movement II, the ephemeral
capability came first by years or decades and the persistent one — where it
exists at all — was built on top of it. TAP would be doing it backwards. That
is not automatically wrong (the July ruling argues it is deliberately cheaper),
but it means the usual safety net — "if the stored path looks wrong, recompute
it and compare" — **does not exist and would have to be built**. Issue# 499's
differential-oracle discipline is precisely an attempt to manufacture that
safety net out of a second declaration instead. Hold that thought; it comes
back in Movement III as the recommendation's main risk.

**Two existing patterns the design should reuse rather than reinvent:**

- **`Search` is already a first-class grid entity** (`tap_grid/models.py`,
  `ENTITY_TYPE = "search"`), storing `search_type` ∈ {module, orm, gryphon}, a
  `definition`, an `input_schema`, `returns`, and limits — and gryphon
  definitions are *parsed at validation time* to catch syntax errors early. A
  "pathmaker query stored as a grid object" is therefore **already built**; it
  is a `Search` with `search_type="gryphon"`. The June notes asked "Are
  pathmaker queries stored as grid objects, plugin declarations, or both?" The
  answer available today is "grid objects, and the machinery exists."
- **The dual-existence pattern** (`tap_grid/specs/spec-grid-dual-existence.md`,
  `Proposed`) codifies "sub-grid registry entry + on-grid node for the same
  capability, joined by a registry key, created through one idempotent
  registration entry point." A *plugin-declared* path type is exactly this
  shape, and the spec's open items (`req-grid-dual-existence-teardown`,
  Backlog: "What happens to the grid node when a plugin uninstalls") are
  exactly the path-type lifecycle questions.

## I.7 The open questions our past selves left behind

Collected from all four sources, deduplicated, and ordered by how much damage
each will do if it is still open when code starts. This list is the real output
of Movement I.

| # | Question | Source | Why it bites |
| --- | --- | --- | --- |
| 1 | **Declared or discovered?** June says traversal produces paths; July says declaration replaces traversal. Which is v0? | notes §Cand.3 vs feature-demand §5.1 | Different staleness model, different validation, different everything. Must be settled first |
| 2 | **Where does the declaration live** — on the model, or as an edge classification (`structural: containment`)? | July amendment; Issue# 499 | Determines whether path definitions are composable predicates or slug lists. Issue# 499 requires *one* declaration read by two implementations |
| 3 | **Do path steps point at edges, or only at nodes?** | notes §Cand.1 | The `req-grid-edge-nono` question. Movement III's centre |
| 4 | **Is there a dedicated path-step node between path and participant, or does the path edge point straight at the participant?** | notes §Cand.1 | Decides whether step metadata has a home and whether "paths on paths" stays possible |
| 5 | **Is `Entity.paths` authoritative, a cache, or both-depending-on-type?** | notes §Cand.2 | An unanswered cache-coherence question is a bug generator |
| 6 | **Multi-parent containment semantics**: child with two containing parents, one retired — live or not? | Issue# 499 | Blocks both the cascade table and the path closure; they must agree |
| 7 | **How do paths interact with history, FLIP, tombstones and GRIFT removals?** | notes §Cand.1 | Unanswered. A path node is an Entity, so it gets all four whether or not anyone designed for it |
| 8 | **What does a path look like in GRIFT?** Is it portable? | notes §Future Spec Hooks | Paths that cannot cross a GRIFT boundary are not first-class |
| 9 | **Partial visibility across dimensions**: omit silently, show redacted gaps, or deny? | notes §Cross-Dimensional | Security-relevant; an inference channel either way |
| 10 | **Where does path breakage get reported?** June says Flaws; the Flaw spec says no | notes vs spec-tap-flaw-v0 | Caught here; needs a home |
| 11 | **Branch/loop addressing notation** | notes §Branches | The notes ask for prior art before choosing. Movement II supplies it, and the answer is "don't" |
| 12 | **Are path names and tags dimension-scoped?** | notes §Cross-Dimensional | Unanswered |
| 13 | **Optimistic concurrency when path membership changes as a side effect of an ordinary write** | notes §Cand.2 | Every write becomes a potential path write. Version-bump storms |

Question 1 is the one that decides the others. Which is why Movement II spends
a great deal of its time on traditions that have faced exactly that fork.

---
# Movement II — Prior Art: Who Else Has Thought This Through

There is a particular kind of comfort in discovering that a problem which has
kept you up at night has also kept up entire research communities, standards
committees, network operators, and — this is the one that genuinely surprised
me — thirty years of biochemists. It is not the comfort of "someone has solved
it." It is the better comfort of "several people have failed at it in
interestingly different ways, and the shapes of their failures are informative."

What follows is organised by tradition rather than by conclusion, because the
conclusions only land once you see how differently each community arrived at
them. Readers in a hurry may skip to §II.9, which is the cross-tradition
synthesis, but they will be skipping the part where the argument is actually
made.

### The organising question — and a rule about evidence

Before any of it, a methodological commitment, because without it this movement
degenerates into a list of what other people did, and a list of what other
people did is worth almost nothing.

> **"System X does (or does not) persist paths" is an observation, not an
> argument.** It acquires force only when you can say *what constraint in X's
> substrate produced the choice*, and then say *whether TAP shares that
> constraint*.

This matters because the most common way to lose an architectural argument is
to win it by appeal to authority over a system that had no choice. If a graph
store has no way of knowing whether a fact it holds is still true, then it
*cannot* persist a path, because a persisted path is a claim about a set of
facts and it would have no way of ever re-checking the claim. Such a system's
"decision" to compute paths at query time is not a decision. It is the only
thing it could do. Citing it is like citing a man with no legs on the merits of
sitting down.

So the question this movement is actually organised around is not "who persists
paths." It is:

> **What does each system's substrate let it know about whether a stored path is
> still true — and what does it do with that knowledge?**

That reframing changes the verdict on several traditions, and in one case it
reverses it entirely. BloodHound turns out to be the reversal (§II.4), and the
reversal is the single most useful finding in this dossier: BloodHound
Enterprise **does** have observation semantics — a per-data-point last-seen
stamp, an explicit rule that absence from one collection is not evidence of
deletion, retention windows, TTLs on behavioural facts — and it still declines
to persist the path, while persisting something else instead. That is a real
argument, arrived at by people who had the means to choose differently. It
deserves weight in a way that a snapshot store's identical behaviour would not.

For every tradition below, therefore, the section ends with the same two
questions answered explicitly: **what forced the choice**, and **does TAP
inherit the constraint?**

And it is worth stating TAP's own position up front, because it is unusual and
it is what makes the constraint test bite. TAP has, built and shipped
(**READ**, per §I.6 and the specs cited there):

- **Batch provenance on every canonical write** — FLIP's field-path-to-batch
  map, and `BatchEvent` records naming the run, scope, reason and consequence
  chain.
- **An explicit unobserved-versus-observed-empty convention** —
  `null` = never written, `""` = observed-empty (`req-grid-node-observation`,
  quoted verbatim in `tap_grid/models.py`'s `natural_key` help text).
- **Tombstones rather than deletion**, with `deleted_at` on the spine, a
  tombstone-aware manager, and a shipped invariant that no live edge points at a
  tombstone (`req-grid-service-delete-tombstone-7`).
- **Re-observation is not change** (tap#322) — a re-collected identical fact does
  not manufacture a history version.
- **A monotonic `Entity.version`** that increments on every canonical mutation,
  tombstone included.

Very few systems in this movement have all five. That is the fact that decides
which of their constraints transfer and which do not.

## II.1 Query-language paths: the formal state of the art

*Section method: primary sources fetched and read except where marked. The ISO
GQL text itself is paywalled (iso.org returns 403 to an unauthenticated fetch),
so every GQL claim below comes from the standard's own authors writing formally
about it — the ICDT 2023 "Researcher's Digest of GQL" and the PathFinder paper
— which is the best available substitute but is **not** the normative text.
This is flagged again wherever it matters.*

### The headline, stated flatly

**No mainstream graph database lets you store a path as a first-class value or
entity.** Not one. Paths are values that queries produce and clients consume
and nobody writes down. The single serious design that makes paths storable is
**G-CORE**, an LDBC task-force language from SIGMOD 2018 that was never shipped
in a production engine — and it is the most important thing in this whole
movement, so it gets its own subsection.

That universal negative is not an oversight. It is a chain of three constraints
that every language in this space runs into, in order:

1. The set of paths between two nodes in a cyclic graph is **infinite** if you
   allow repeats, and **exponential** if you don't.
2. Deciding whether even *one* path matching a regular expression is simple or
   a trail is **NP-complete** — and it stays NP-complete for fixed, tiny
   expressions like `(aa)*`.
3. So a language that returns paths must impose *finiteness restrictors* or
   *cardinality selectors*, and a language that wants to stay tractable simply
   declines to return paths at all.

Each of those three deserves unpacking, because each one has a direct
consequence for TAP.

### Cypher: paths are structural, and structural means unstorable

Neo4j's type system splits values into **property types** and **structural
types**. The manual is blunt about the consequence (**READ**,
[Neo4j Cypher Manual — property, structural and constructed values](https://neo4j.com/docs/cypher-manual/current/values-and-types/property-structural-constructed/)):

> "Property types can be stored as properties." … "Structural types cannot be
> stored as properties."
>
> "The `PATH` data type is an alternating sequence of nodes and relationships."

`PATH` sits alongside `NODE` and `RELATIONSHIP` in the structural tier. It is
a genuine first-class *runtime* value — bind it, return it, pass it to
functions — and it is explicitly not storable. There is no `SET n.route = p`.
You may decompose it with `nodes(path)` and `relationships(path)` (both
documented as order-preserving, **READ**,
[list functions](https://neo4j.com/docs/cypher-manual/current/functions/list/)),
and APOC will even *construct* one in memory
([`apoc.path.create`](https://neo4j.com/docs/apoc/current/overview/apoc.path/apoc.path.create/),
**READ**), but nothing in the documented surface persists one.

What people actually do instead is reify: make a node, hang ordered edges off
it. This is widely described in community material and I could find **no
authoritative Neo4j document prescribing it** (**UNVERIFIED** as official
guidance; **INFERRED** as the only mechanism the data model permits). Which is
to say: the workaround TAP is considering making first-class is the workaround
Neo4j users already hand-roll, without a blessing.

A detail worth stealing: Cypher's **group variables**. Variables bound inside a
quantified pattern become *lists* of what they matched, not singletons
(**READ**, [variable-length patterns](https://neo4j.com/docs/cypher-manual/current/patterns/variable-length-patterns/)).
That is Cypher's answer to "what does a repeated binding mean," and it is not a
path — it is a list. The path variable on the whole pattern is what gives you
the path. TAP will face the same fork.

And a detail worth avoiding: the older `[*1..5]` spelling is, in Neo4j's own
words, "still available but it is not GQL conformant." The conformant form is
the quantified path pattern `(pattern){min,max}`. If Gryphon is going to grow
bounded repetition under Issue# 259 - tap, it should grow the conformant
spelling, not the deprecated one. That is a free win available today.

### GQL (ISO/IEC 39075:2024): the vocabulary to adopt wholesale

Published 12 April 2024 by ISO/IEC JTC 1/SC 32/WG 3 — the first genuinely new
ISO database query language since SQL (**UNVERIFIED** as to the exact date;
iso.org 403s, corroborated at [gqlstandards.org](https://www.gqlstandards.org/)
and [Wikipedia](https://en.wikipedia.org/wiki/Graph_Query_Language)).

GQL factors the path problem into two orthogonal knobs, and this factorisation
is the single most useful piece of vocabulary in the entire dossier:

- A **restrictor** says *which paths are legal*: `WALK`, `TRAIL`, `SIMPLE`,
  `ACYCLIC`.
- A **selector** says *how many to return*: `ANY`, `ANY SHORTEST`,
  `ALL SHORTEST`, `ANY k`, `SHORTEST k`, `SHORTEST k GROUPS`.

The formal semantics, from the ICDT 2023 digest written by the standard's own
authors (**READ**,
[A Researcher's Digest of GQL](https://drops.dagstuhl.de/opus/volltexte/2023/17743/pdf/LIPIcs-ICDT-2023-1.pdf)):

```
⟦TRAIL π⟧_G    = { (p, µ) ∈ ⟦π⟧_G | no edge occurs more than once in p }
⟦ACYCLIC π⟧_G  = { (p, µ) ∈ ⟦π⟧_G | no node occurs more than once in p }
```

and the distinction people always get wrong, in the digest's own words:

> "Another mode present in GQL is SIMPLE: it is similar to ACYCLIC but allows
> the first and the last node on a path to be the same, i.e., a simple cycle.
> There is also the keyword WALK to explicitly indicate the absence of a path
> mode."

So: **ACYCLIC ⊂ SIMPLE ⊂ TRAIL ⊂ WALK**. SIMPLE admits the closed cycle;
ACYCLIC does not. The
[PathFinder paper](https://arxiv.org/pdf/2306.02194) (**READ**) gives the same
definitions in standards-faithful form, and then the number to quote:

> "This gives us **28 path modes**: 6 selectors times 4 restrictors, plus the 4
> restrictors without selector. However, **WALK needs to be preceded by a
> selector to avoid the need to return infinitely many paths** in some cases,
> which gives **27 relevant modes**."

Three semantic subtleties that will bite anyone designing path features:

1. **Shortest is grouped by endpoints, not globally.** "the selected paths do
   not [compete globally]" — `ALL SHORTEST` gives you the shortest path *per
   distinct (source, target) pair*.
2. **Shortest is computed among paths that match the pattern**, not among all
   paths. The digest's example returns a three-hop path as "shortest" even
   though a shorter path exists, because the shorter one does not match the
   regular expression.
3. **Non-determinism is in the standard.** "the semantics of ANY, ANY SHORTEST,
   ANY k, and SHORTEST k is non-deterministic." A conformant engine may return a
   different path on each run. If TAP ever persists the output of an `ANY`
   selector, it has persisted a coin flip.

**GQL does have a `Path` type.** The digest's type system is
`τ ::= Node | Edge | Path | Maybe(τ) | Group(τ)` and a variable "is **a path
variable** if its type is Path." The binding rule is explicit:

```
⟦x = π⟧_G = { (p, µ ∪ {x ↦ p}) | (p, µ) ∈ ⟦π⟧_G }
```

### Path values versus path bindings — and the fact that kills node-array storage

This is the sharpest idea in the digest and it changes a schema decision.

**The semantics of every GQL pattern is a set of *pairs* `(p, µ)`** — a path
**value** `p` and a **binding** `µ` from variables to graph elements. These are
different objects. One path value can carry many distinct bindings: the digest's
money-laundering example shows the same trail appearing four times, once per
choice of start node, with the group variables ordered differently each time.

And then, in a single sentence, the reason a stored path cannot be a list of
node ids (**READ**):

> "property graphs can have multiple edges with the same end-nodes, so **the
> list of nodes in a path is not sufficient to determine the path**."

**If TAP stores a path, it must name edges.** Not node ids, not node ids plus
edge types — edge identities. TAP has multi-edges (nothing prevents two
`RUNS_ON` edges between the same pair with different `properties`), so this
applies directly. G-CORE, independently, reaches the same conclusion and encodes
it in the type of its path function (below).

One more, and it is the fence every path design needs: the digest's Remark 10
observes that for `(a){0,}` on an isolated node there are *infinitely many
bindings all associated with the same path*, so `ALL SHORTEST (a){0,}` would
have infinite output. GQL forbids this **syntactically** — well-formedness
condition 4 requires that a pattern under `ALL` contain no unbounded repetition.
It is a static check, not a runtime guard. TAP should copy that posture: fence
the forbidden combination in the grammar, not in the executor.

### A trap: GQL's TRAIL is not Cypher's default

Worth its own paragraph because it will cause an argument one day (**READ**,
digest §"Complex path modes"):

> "GQL's TRAIL differs from Cypher's trail semantics. The latter corresponds to
> GQL's match mode **DIFFERENT EDGES** … Cypher's requirement that all matched
> edges must be different operates at the level of **graph patterns**, whereas
> GQL's TRAIL operates at the level of **path patterns**."

Cypher's default no-edge-reuse is a *pattern-wide* rule; GQL's TRAIL is a
*per-path* rule. `MATCH TRAIL ()-[e1]->(), TRAIL ()-[e2]->()` will happily bind
`e1 = e2` in GQL and will not in Cypher.

### SQL/PGQ: same pattern language, different ambitions

ISO/IEC 9075-16:2023. PGQ and GQL share an identical pattern-matching
sublanguage — the authors call it **GPML** (**READ**,
[Graph Pattern Matching in GQL and SQL/PGQ](https://arxiv.org/abs/2112.06217),
authored by ISO WG3 and LDBC people including Deutsch, Francis, Libkin, Green
and Hare). PathFinder confirms the same 27 modes apply to both.

What PGQ omits relative to GQL: graph updates, querying multiple graphs, and
returning a graph rather than a binding table. Property graphs in PGQ are
"view-like objects on top of existing tables" — a read-only projection over
relational storage (**UNVERIFIED**; consistent across
[Wikipedia](https://en.wikipedia.org/wiki/Graph_Query_Language) and
[Oracle's 23ai writeup](https://blogs.oracle.com/database/property-graphs-in-oracle-database-23ai-the-sql-pgq-standard)
but not read in the normative text).

**Open question I could not close, and it matters:** whether PGQ's
`GRAPH_TABLE … COLUMNS` clause can yield a path-typed column at all. My reading
is no — SQL has no PATH type, so PGQ can *select over* paths but not surface one
whole — whereas GQL, having its own type system with `Path`, can. That is
**INFERRED** and I flag it as the one unresolved comparison in this section.

Practically, DuckPGQ — the reference PGQ implementation, and one TAP already has
a dossier on at `docs/misc/comparanda/dossier-duckpgq.md` — supports only partial
RPQ and **no** TRAIL / SIMPLE / ACYCLIC / GROUPS (**READ**, PathFinder Table 1).

### SPARQL: the tradition that looked at paths and said no

SPARQL 1.1 property paths are the most instructive *refusal* in this movement,
because the refusal is documented, argued, and traceable to a specific paper.

The syntax is the familiar regex-over-predicates set: `iri`, `^elt`,
`elt1/elt2`, `elt1|elt2`, `elt*`, `elt+`, `elt?`, `!iri` (**READ**,
[SPARQL 1.1 §9.4](https://www.w3.org/TR/sparql11-query/#propertypaths)). A
property path is "a possible route through a graph between two graph nodes," and
crucially "**variables can not be used as part of the path itself, only the
ends.**"

The normative sentence:

> "Such connectivity matching **does not introduce duplicates** (it does not
> incorporate any count of the number of ways the connection can be made) even
> if the repeated path itself would otherwise result in duplicates."

And the algebra removes all doubt. The `ALP` (Arbitrary Length Path) definition
in §18.4 (**READ**):

```
ALP(x:term, path, V:set of RDF terms) =
  if ( x in V ) return
  add x to V
  X = eval(x,path)
  For n:term in X
    ALP(n, path, V)
  End
```

**`ALP`'s return type is a multiset of RDF terms — nodes.** The route is
structurally absent from the algebra. It exists only as the recursion stack and
is thrown away with it. Jena's implementation note confirms the consequence:
"Only one match is recorded — no duplicates for any given path expression"
(**READ**, [Jena property paths](https://jena.apache.org/documentation/query/property_paths.html)).

**Why they did it.** The working group's own response document (**READ**,
[CommentResponse: PropertyPathComments](https://www.w3.org/2009/sparql/wiki/CommentResponse_PropertyPathComments.html)):

> "The semantics of `*`, `+`, and `?` are changed to be **non-counting** (they no
> longer preserve duplicates)"
> "The `/`, `|`, and `!` remain unchanged … (they preserve duplicates)"
> "The curly brace forms — `{n}`, `{n,m}`, `{n,}`, `{,m}` — have **all been
> removed**"

with the rationale given as evaluation-performance concerns, and the `{n,m}`
removal attributed to "**lack of experience with appropriate
counting/non-counting semantics for these forms**." Note the asymmetry and its
logic: the fixed-length operators stay counting because they are shorthand for
patterns you could write longhand; the arbitrary-length ones become non-counting
because that is exactly where counting explodes.

The forcing paper is Arenas, Conca and Pérez, *"Counting beyond a Yottabyte, or
how SPARQL 1.1 property paths will prevent adoption of the standard"* (WWW 2012,
pp. 629–638,
[repository record](https://repositorio.uchile.cl/handle/2250/125815)) —
double-exponential naive evaluation, path counts on DBpedia-scale data whose
*number of digits* exceeded a yottabyte, and several implementations falling over
on simple queries. **UNVERIFIED** as to the exact figures (I read summaries, not
the body); the causal link to the WG decision is **INFERRED** from chronology plus
the WG's own "evaluation performance concerns" wording.

And the detail that should make TAP sit up: **the WG did consider making the path
a datatype.** Their feature page records Issue 2 — whether "the path itself
[should] become a datatype," which "would allow a filter to restrict paths in
more complex ways." **No resolution is documented** (**READ**,
[Feature:PropertyPaths](https://www.w3.org/2009/sparql/wiki/Feature_PropertyPaths.html)).
They did not reject path-as-a-thing. They ran out of time and shipped the
tractable subset. That is a rather different signal from "the idea is bad."

### Gremlin: paths are provenance, and they destroy bulking

TinkerPop's `Path` is "a particular walk through a `Graph` as defined by a
`Traversal`," implemented as "a list of sets of labels and a list of objects"
(**READ**,
[Path javadoc](https://tinkerpop.apache.org/javadocs/current/core/org/apache/tinkerpop/gremlin/process/traversal/Path.html)).

Two things make it different from Cypher's and GQL's, and both are **INFERRED**
from the documented behaviour: it is *not* an alternating node/edge sequence —
`g.V(marko).out('knows').values('name').path()` yields `[v[1],v[2],vadas]`, two
vertices and a *String* — so a Gremlin Path is traversal provenance rather than a
graph-theoretic path; and it carries step labels, making it also a named-slot
record.

The cost, which is the part that generalises well beyond Gremlin (**READ**,
[path step](https://tinkerpop.apache.org/docs/current/reference/#path-step) and
[the-graphcomputer.asciidoc](https://github.com/apache/tinkerpop/blob/master/docs/src/reference/the-graphcomputer.asciidoc)):

> "**Path calculation is costly in terms of space** as an array of previously
> seen objects is stored in each path of the respective traverser. Thus, a
> traversal strategy analyzes the traversal to determine if path metadata is
> required. If not, then path calculations are turned off."

> "If a traverser's path is being recorded, then **bulking is not possible**
> since the path differentiates each traverser from one another."

> "every traverser is unique and thus, must be **enumerated as opposed to being
> counted/merged**. The difference being **a collection of paths vs. a single
> 64-bit long** at a single vertex."

That last sentence is the crispest statement of the cost anywhere in the
literature. Without path identity, a vertex holds a counter — eight bytes. With
path identity, it holds a set of path objects whose size is the number of
distinct routes. **This is not merely a memory fact; it is a general statement
about what path identity destroys: the ability to merge equivalent intermediate
states.** Any system that persists paths pays a version of this bill in its
indexes and its aggregates, not just in its working set.

Gremlin's `simplePath()` and `cyclicPath()` look like GQL's ACYCLIC but are
operationally its opposite: GQL's restrictor prunes the *search*; Gremlin's
filter discards traversers *after the fact* (**INFERRED**).

### The complexity results, stated precisely because they are load-bearing

The foundational citation, verified through Crossref (**RAN**):

> Alberto O. Mendelzon and Peter T. Wood, **"Finding regular simple paths in
> graph databases,"** *SIAM Journal on Computing* 24(6):1235–1258, 1995.
> DOI [10.1137/S009753979122370X](https://doi.org/10.1137/S009753979122370X)

The sharp modern statement, from PathFinder §4 (**READ**):

> "It is well known that **even checking whether there is a single path between
> two nodes that conforms to a regular expression and is a simple path, trail, or
> acyclic path is NP-complete**, even for undirected graphs … **These hardness
> results already hold for fixed regular expressions, such as `(aa)*` or
> `a*ba*`**."

Two things to underline:

- **The hardness is in the decision problem, not the output size.** You cannot
  rescue TRAIL/SIMPLE/ACYCLIC by capping the number of results. Deciding
  *existence* is already NP-complete.
- **It holds for fixed, tiny expressions.** You cannot escape by restricting
  query complexity.

Consolation, also from PathFinder: "regular expressions for which these problems
are NP-hard are **rare**" in practice — which is why real engines perform fine
despite the worst case.

The trichotomy that sorts the tractable from the intractable: Bagan, Bonifati and
Groz, *"A trichotomy for regular simple path queries on graphs,"* PODS 2013,
[10.1145/2463664.2467795](https://dl.acm.org/doi/10.1145/2463664.2467795)
(**UNVERIFIED** — read summaries and the dblp record, not the paper) —
finite languages, a tractable class, and everything else, which is NP-complete.
A companion result for trails (Martens, Niewerth, Trautner, STACS 2020,
[arXiv:1903.00226](https://arxiv.org/pdf/1903.00226), **UNVERIFIED**) notes that
the tractable class for simple paths is *smaller* than for trails.

And for GQL specifically (**READ**,
[Complexity of Evaluating GQL Queries](https://arxiv.org/pdf/2407.06766)):
**P^NP[log]-complete with restrictors; NL-complete without them.** Restrictor-free
GQL is captured by FO[TC]. The hardness reduction is Mendelzon–Wood lifted.

**The restrictors are exactly where the hardness lives.** That sentence is the
single most actionable fact in §II.1, and it has a direct TAP consequence stated
in Movement III.

### G-CORE: the one design that makes paths first-class, and why

Angles, Arenas, Barceló, Boncz, Fletcher, Gutierrez, Lindaaker, Paradies,
Plantikow, Sequeda, van Rest and Voigt, **"G-CORE: A Core for Future Graph Query
Languages,"** SIGMOD 2018 ([arXiv:1712.01550](https://arxiv.org/pdf/1712.01550),
[ACM](https://dl.acm.org/doi/10.1145/3183713.3190654)) — **READ**.

This is the paper George should read in full before writing the spec. Its
argument for persistent paths is better than the one in TAP's own June notes,
and it arrives at it from a completely different direction.

The motivation:

> "The notion of Path is fundamental for graph databases, because it introduces
> an intermediate abstraction level that allows to represent how elements in a
> graph are related. The facilities provided by a graph query language to
> manipulate paths (i.e. **describe, search, filter, count, annotate, return**,
> etc.) increase the expressivity of the language."

And then the closure argument, which is the load-bearing one:

> "G-CORE treats paths as first-class citizens. This means that paths are outputs
> of certain queries. **The fact that the language must be closed implies that
> paths must be part of the graph data model.** This leads to a principled change
> of the data model: it extends property graphs with paths. … given that nodes,
> edges and paths are all first-class citizens, **paths have identity and can
> also have labels and ⟨property,value⟩ pairs** associated with them."

*Closure forces persistence.* If your query language returns graphs rather than
tables, and a query can return paths, then paths must be storable or the language
is not closed. That is the cleanest justification for persistent paths anywhere in
the literature — and note what it implies in reverse: **if your language returns
tables, this pressure does not exist and persistence is a product decision, not a
semantic necessity.** Gryphon returns a GRIFT subgraph envelope
(`{nodes: [], edges: []}`, per `tap_grid/specs/spec-grift-subgraph.md`, **READ**),
which is *graph-shaped* — so TAP is closer to G-CORE's position than to SQL's,
and this argument partially applies. Partially, because that envelope has no
`paths` member today.

The formal model, Definition 2.1 (**READ**), a **Path Property Graph**
`G = (N, E, P, ρ, δ, λ, σ)`:

- `N`, `E`, **`P`** — node, edge, and **path** identifier sets, pairwise disjoint.
- `ρ : E → (N × N)`
- **`δ : P → FLIST(N ∪ E)`** — a path maps to a *finite list over nodes and
  edges*, `[a₁, e₁, a₂, …, aₙ, eₙ, aₙ₊₁]`, where each `eⱼ` connects `aⱼ` and
  `aⱼ₊₁` **in either direction**.
- **`λ : (N ∪ E ∪ P) → FSET(L)`** — labels on paths.
- **`σ : (N ∪ E ∪ P) × K → FSET(V)`** — properties on paths.

Three details in that definition are worth a long pause:

1. **`δ` maps into `N ∪ E`.** Edges are named in the stored path. Same reason
   the GQL digest gave: multi-edges.
2. **A stored path may traverse an edge against its direction** (the definition
   permits `ρ(eⱼ) = (aⱼ₊₁, aⱼ)`). This matters enormously for TAP's July
   containment ruling, where "what contains X" is deliberately the canonical
   parent→child edge walked backwards.
3. **Paths get labels and properties by the same functions as nodes and edges.**
   `λ` and `σ` are defined on `N ∪ E ∪ P` as one domain. Path-as-first-class is
   not bolted on; it is a widening of the existing maps.

The syntax gives paths their own tier — `-/ … /-` rather than `-[ … ]-` — and an
`@` prefix marks a *stored* path:

```
CONSTRUCT (n)-/@p:localPeople {distance := c}/->(m)
  MATCH    (n)-/3 SHORTEST p <:knows*> COST c/->(m)
  WHERE    (n:Person) AND (m:Person) AND …
```

> "In CONSTRUCT `(n)-/@p:localPeople{distance:c}`, we see the bound path variable
> `@p`. **The `@` prefix indicates a stored path**, that is, this query is
> delivering a graph with paths."

**And now the fence, which is the most important sentence in the paper for our
purposes** (**READ**):

> "Using ALL instead of SHORTEST: **asking for all paths, is not allowed if a
> path variable is bound to it and used somewhere, as this would be intractable
> or impossible due to an infinite amount of results.** However, G-CORE can
> support it in the case where the path variable is only used to return a
> **graph projection** of all paths."

So `MATCH (n)-/ALL p <:knows*>/->(m)` is legal only when `p` is used solely as
`CONSTRUCT (n)-/p/->(m)` — a *projection* of the union of all paths into a
subgraph. That is polynomial, because "the materialization of all paths can be
avoided by **summarizing these paths in a graph projection**." With that fence,
G-CORE claims its whole evaluation is polynomial-time.

**G-CORE bought first-class persistent paths by permitting only `k SHORTEST` to
bind a path variable, and degrading `ALL` to a summarised subgraph.** That is the
price, stated by the people who designed it. Any TAP design that wants persistent
paths without that fence should be able to say what it is paying instead.

I could find **no production or prototype engine implementing G-CORE's stored
paths** (**UNVERIFIED** — I can show absence of search results, not absence of a
prototype). G-CORE fed into GQL; the stored-path part did not survive the trip.

### The compression route: don't store paths, store the machine that makes them

If you need many paths and cannot afford to materialise them, the state of the
art is a **succinct representation**.

Martens, Niewerth, Popp, Vansummeren and Vrgoč, *"Representing paths in graph
database pattern matching"* ([arXiv:2207.13541](https://arxiv.org/abs/2207.13541),
also VLDB) introduce **path multiset representations (PMRs)**, which "can
represent multisets of paths in an **exponentially succinct** manner" and work
"especially well for regular path queries plus operations involving **counting,
random sampling, unions, and joins**" (**READ**, abstract level).

PathFinder implements this: "At the core of our approach is the **product graph
construction**," achieving **output-linear delay** — "to return a path to the
user, we have to at least write down each element of the path" (**READ**).

The compromise the theory community landed on is therefore: *store the product
graph, not the paths; enumerate on demand with optimal delay; count and sample
cheaply.* Hold that thought — it is one of the alternatives Movement III has to
give a fair hearing.

### Engine reality check

PathFinder's Table 1 is the best available census of what shipping engines can
actually *return* (**READ**), and it is bleak:

| Engine | RPQ | WALK | TRAIL | SIMPLE | ACYCLIC | SHORTEST | GROUPS |
|---|---|---|---|---|---|---|---|
| BlazeGraph / Jena / Virtuoso | ✓ | – | – | – | – | – | – |
| Neo4j | partial | ✓ | ✓ | – | – | ✓ | – |
| NebulaGraph | partial | partial | ✓ | – | ✓ | ✓ | – |
| Memgraph | partial | ✓ | ✓ | – | – | ✓ | – |
| Kùzu | partial | ✓ | – | – | – | ✓ | – |
| DuckPGQ | partial | ✓ | – | – | – | ✓ | – |

> "**no property graph engine to date supports all regular path queries** like
> SPARQL engines do."

**INFERRED, and worth saying plainly**: TAP is not behind here. It is level with
an industry that has collectively implemented about a third of its own standard.

### What TAP inherits, and what it avoids

**Inherit:**

- **The restrictor × selector vocabulary, verbatim.** WALK/TRAIL/SIMPLE/ACYCLIC
  and ANY/ANY SHORTEST/ALL SHORTEST/ANY k/SHORTEST k/SHORTEST k GROUPS. It is
  ISO-standard, it is precise, and inventing TAP words for it would be the
  "confusing private notation" the June notes warned against.
- **Edge identity in the stored representation.** Never a node-id array.
- **The static fence on `ALL` + unbounded + bound variable.** Grammar-level, per
  GQL's well-formedness condition and G-CORE's restriction.
- **G-CORE's widening move**: labels and properties defined on `N ∪ E ∪ P` as one
  domain, rather than a bolted-on path table. TAP's `Entity` spine is already
  exactly this shape — one domain, three kinds of citizen. That is a genuine
  architectural advantage and §III makes much of it.
- **The GQL-conformant quantified-pattern spelling** if Issue# 259 - tap ever
  ships bounded repetition.

**Avoid:**

- **Inventing a dotted string notation for branches and loops.** No tradition in
  this section encodes structure in a string. GQL uses group variables (lists);
  G-CORE uses `δ` (a list over `N ∪ E`); Gremlin uses labelled slots. The June
  notes' `path.branch:step.branch:step` sketch has no prior art behind it and a
  great deal of prior art implicitly against it.
- **Persisting the output of a non-deterministic selector** (`ANY`, `SHORTEST k`)
  without recording that it was one of several legitimate answers. TAP already
  has exactly the right instinct here — `tap_grid/cascade_corpus/model_oracle.py`
  "states every order-dependent answer as the SET of legitimate answers rather
  than one run's" (**READ**). The same discipline must apply to paths.
- **Assuming path counting is cheap.** SPARQL's yottabyte is the cautionary
  number.



### The constraint test applied to the query languages

**What forced the choice?** Three different constraints operate here and it
matters not to confuse them, because only one of them transfers.

1. **Cypher's refusal is a storage-model constraint, and it is arbitrary.** The
   property-graph model says a property is a scalar or a list of scalars; a path
   is a structural value; therefore a path cannot be a property. That is a
   definitional fence, not a discovered limit. Neo4j could have added a fourth
   element kind. It did not, and the documentation offers no rationale beyond the
   taxonomy itself — I looked for one and did not find it, which is a **negative
   result**, not proof of absence. **Does TAP inherit it? No.** TAP's substrate
   has exactly one storage kind — `Entity` on the spine — and a path node would
   be an `Entity` like any other. TAP does not have a property/structural split
   to be on the wrong side of. This is the clearest case in the dossier of a
   constraint that does not transfer, and it means "Neo4j doesn't do it" is
   worth nothing as evidence here.

2. **SPARQL's refusal is a semantics-plus-performance constraint, and it is
   real — but narrower than it looks.** The working group did not decide paths
   were a bad idea. They decided that *counting the number of ways an
   arbitrary-length connection can be made* is computationally catastrophic (the
   Arenas/Conca/Pérez result), and that the tractable move was to make `*` and
   `+` non-counting — which, as a side effect, means the algebra never
   materialises a route. The record shows they explicitly considered making the
   path a datatype and **left the issue unresolved** rather than rejecting it
   (**READ**, W3C Feature:PropertyPaths Issue 2), and their own stated reasons
   for the cuts include "schedule." **Does TAP inherit it? Partly, and
   precisely.** TAP inherits the *counting* constraint: any TAP feature that
   enumerates or counts all paths matching a pattern over a cyclic graph hits
   the same wall, and no engineering avoids it, because the hardness is in the
   decision problem (Mendelzon–Wood). TAP does **not** inherit the conclusion
   that paths must be unnameable — that conclusion followed from wanting *one
   query operator* to be tractable over *arbitrary* regular expressions. A
   named, declared, bounded path is not an arbitrary RPQ, and the intractable
   part of the problem is the part TAP's July ruling already declines to build.

3. **Gremlin's cost is an execution-model constraint, and it is the most
   transferable of the three.** Path identity destroys bulking: "a collection of
   paths vs. a single 64-bit long." **Does TAP inherit it? Yes — and TAP should
   say so out loud.** The moment a traversal needs to know *which route* it took
   rather than merely *whether it arrived*, it loses the ability to merge
   equivalent frontier states. In `WITH RECURSIVE` terms that is precisely the
   difference between `UNION` (which dedupes) and `UNION ALL` (which does not),
   and therefore the difference between a frontier bounded by the node count and
   a frontier bounded by the *route* count.
   `docs/misc/graph-lookup-performance-notes.md` already names frontier size as
   the term that matters ("the cost that matters is k and frontier size").
   **Path tracking is exactly the thing that stops the frontier being bounded by
   the graph.** That is the honest cost of any query-time path feature, and it
   is unaffected by whether the answer is subsequently persisted. Postgres hands
   you the mechanism and the bill together: the `CYCLE id SET is_cycle USING
   path` clause (**READ**,
   [PostgreSQL WITH queries](https://www.postgresql.org/docs/current/queries-with.html))
   maintains a per-row array of visited ids — a materialised path column, free
   with the syntax — and that array is the memory the bulking argument says you
   are now paying for.

**And one that reverses the polarity entirely.** G-CORE's position is not a
constraint at all — it is an *entailment*. Closure forces persistence: if a
language returns graphs and can return paths, paths must be part of the model.
Gryphon returns a GRIFT subgraph, which is graph-shaped, so the entailment
applies to TAP *more* strongly than it applies to Cypher, which returns tables
of values. **TAP is architecturally closer to the one design in the literature
that made paths first-class than it is to the designs that refused.**


## II.2 A short detour: the road not taken, 1945–1989

*Section method: bibliographic records verified through the Crossref API
(**RAN**); Bush's text quoted via a secondary source that quotes the primary
(**READ**, with the secondary-source caveat stated). The substantive claims about
what these systems did are **UNVERIFIED** where the papers are paywalled, and
labelled.*

The June notes cite Vannevar Bush for *connections*. The stronger citation is
Bush for *trails*, and the reason it is stronger is that it comes with forty
years of subsequent failure attached.

*As We May Think* (Atlantic Monthly, July 1945, vol. 176 no. 1, pp. 101–108)
proposes the memex, and the memex's signature feature is not microfilm. It is the
**trail**: a mechanism for creating, as Bush put it, "a new *linear* sequence of
microfilm frames across any arbitrary sequence of microfilm frames by creating a
chained sequence of links." Trails are authored, annotated, and — this is the
part everybody forgets — **transferable**: "A user could insert a comment of his
own, either linking it into the main trail or joining it by a side trail to a
particular item," and could "pass it to his friend for insertion in his own
memex, there to be linked into the more general trail." Bush foresaw a
profession: "a new profession of trailblazers, those who find delight in the task
of establishing useful trails through the enormous mass of the common record."
(**READ**, via
[Wikipedia's Memex article](https://en.wikipedia.org/wiki/Memex), which quotes
the primary text; I did not read the Atlantic original.)

So Bush proposed, in 1945, a named persistent path with an owner, side branches,
annotations, and a transfer format. That is very nearly TAP's feature list, filed
eighty-one years early.

Hypertext then spent decades failing to ship it. Two of the attempts are worth
knowing about:

- **Randall H. Trigg, "Guided tours and tabletops: tools for communicating in a
  hypertext environment,"** *ACM TOIS* 6(4):398–414, October 1988, DOI
  [10.1145/58566.59299](https://doi.org/10.1145/58566.59299) (also CSCW '88, pp.
  216–226, DOI
  [10.1145/62266.62283](https://doi.org/10.1145/62266.62283)). Built on NoteCards
  at Xerox PARC (Trigg, Halasz and Moran, 1984 —
  [NoteCards](https://en.wikipedia.org/wiki/NoteCards), **READ**). Bibliographic
  record **RAN** via Crossref; the paper body is **UNVERIFIED** (ACM 403s).
- **Polle T. Zellweger, "Scripted documents: a hypermedia path mechanism,"**
  Hypertext '89, pp. 1–14, DOI
  [10.1145/74224.74225](https://doi.org/10.1145/74224.74225). Bibliographic
  record **RAN**; body **UNVERIFIED**. Note the subtitle: *a hypermedia path
  mechanism.* Somebody was calling this exact thing a "path mechanism" in 1989.
- Later: Guinan and Smeaton, "Information retrieval from hypertext using
  dynamically planned guided tours," Hypertext '93, DOI
  [10.1145/168466.168506](https://doi.org/10.1145/168466.168506) — note
  *dynamically planned*, i.e. by 1993 the field had already swung from authored
  tours to computed ones (**RAN**, bibliographic only).

And the document that names the problem in general terms is Frank G. Halasz,
**"Reflections on NoteCards: Seven Issues for the Next Generation of Hypermedia
Systems,"** *CACM* 31(7):836–852, 1988, DOI
[10.1145/48511.48514](https://doi.org/10.1145/48511.48514) (**RAN** for the
citation). Wikipedia's summary of the seven issues confirms four of them by name
— "search and query in large hypertexts, composite structures, versioning, and
collaborative work" (**READ**,
[Hypertext](https://en.wikipedia.org/wiki/Hypertext)). My recollection is that
one of the remaining three is **virtual structures** — structures *computed on
demand* rather than stored, which is precisely the persistent-versus-computed
path question posed in 1988 — but I could not verify that against the paper body
(ACM 403s) and so it is **UNVERIFIED**. If George reads one old paper before the
spec pass, this is the one; the version of the question it poses is thirty-eight
years older than ours and the vocabulary ("virtual structures," "composites,"
"versioning") is uncannily close.

**What TAP should take from this detour.** Three things, and the third is
uncomfortable.

1. **The feature has been independently reinvented roughly once a decade since
   1945.** That is a strong signal that it answers a real need. It is an equally
   strong signal that it is hard, because the reinventions keep happening.
2. **Authored trails lost to computed navigation.** The web shipped the link and
   dropped the trail. Search replaced the trailblazer. The 1993 "dynamically
   planned" paper is the swing already happening inside the research community.
   **INFERRED**: the reason is maintenance — an authored trail through a corpus
   that changes is wrong within weeks, and nobody wants the job of the
   trailblazer's janitor.
3. **The one place trails did ship and survive is where the corpus is curated at
   the same cadence as the trail.** Which is Reactome, and Wikipedia's "vital
   articles," and a course syllabus. §II.6 is entirely about what that costs.

---
## II.3 Edges about edges: twenty years of saying yes, sort of

*Section method: W3C specifications, vendor documentation, raw READMEs, C++
headers and GitHub APIs fetched and read (**READ**); roughly ten papers
converted from PDF locally (**READ**); ISO 39075 and 9075-16 are paywalled and
403 to an unauthenticated fetch, so every standards claim rests on the
committee members' own published formal models plus Oracle's conformant manual
(**flagged**). Several leads could not be closed and are listed at the end of
the section rather than quietly dropped.*

This is the section the June notes pointed at when they said "paths may be the
first use case that justifies a narrow, well-specified exception." It turns out
to be a much larger subject than that sentence suggests, with a clean formal
answer, an unambiguous industry consensus, two serious dissenters, and one
consequence that nobody anticipated and everybody who tried it ran into.

### The formal answer first, because it clarifies everything else

**Edge-to-edge is not what a hypergraph gives you.** This confusion is
everywhere and it wastes a lot of argument, so here is the distinction, stated
precisely.

A hypergraph generalises **arity**: an edge may contain any number of vertices
rather than exactly two. Edge-to-edge requires **recursion**: edges must be
first-class elements of the same universe that incidence sets draw from.

The formal statement, and it is beautifully compact — from Joslyn and Nowak,
*Ubergraphs: A Definition of a Recursive Hypergraph Structure*, PNNL-26402,
[arXiv:1704.05547](https://arxiv.org/pdf/1704.05547) (**READ**):

> "**As hypergraphs generalize graphs by allowing edges to have more than two
> vertices, ubergraphs generalize hypergraphs by allowing edges to contain other
> edges as vertices.** Thus, all graphs are hypergraphs and all hypergraphs are
> ubergraphs.
>
> **The ability to do indirection in graph data structures by 'quoting' or
> 'pointing to' edges is absolutely central in graph-based data science, and is
> accomplished in such systems by a variety of ad hoc mechanisms such as
> reification. Hypergraphs are frequently used as part of that armamentarium,
> but ubergraphs are a more robust representation framework.**"

And the mechanism, in one line. Every hypergraph has a **Levi graph** — the
bipartite incidence graph `(V ⊎ E, E′)` where `(v, e) ∈ E′` iff `v ∈ e`. Joslyn
and Nowak's Note 3: "**The uber-Levi graph is a directed acyclic graph (DAG)** …
Moreover, every DAG yields an ubergraph."

So, **INFERRED** but I would defend it as the clearest framing available:

| Structure | Levi graph | What it generalises |
| --- | --- | --- |
| ordinary graph | bipartite, edges have 2 elements | — |
| **hypergraph** | **bipartite** | arity |
| **ubergraph / recursive hypergraph** | **DAG** | recursion |

**Edge-to-edge is exactly the relaxation of the Levi graph from bipartite to
DAG.** That is the whole design axis, and — this matters — it is *not* a
relaxation to an arbitrary graph. The DAG constraint is load-bearing:

> "**Allowing (ultimately) expressions like e = {e}, and thus arbitrary cycles in
> the uber-Levi graph, violates the axiom of foundation. The vertex set is no
> longer well defined, and non-well-founded sets would need to be invoked.**"

That same boundary is confirmed independently by three unconnected literatures
(**READ**, all three): HyperGraphDB's author cites Aczel's non-well-founded set
theory for the same reason; AtomSpace's Linas Vepštas states that metagraph
links "are arranged to be **acyclic**"; and the Statement Graphs paper unifying
RDF and property graphs does it *as DAGs*
([arXiv:2304.13097](https://arxiv.org/abs/2304.13097)).

**Well-foundedness is where the mathematics stops, not where an implementation
got lazy.** A requirement for mutually-referencing edges is a requirement to
leave ZF set theory, and the honest engineering answer is to re-express it via
a shared named node.

**A terminology warning worth heeding.** "Metagraph" names two different
structures, and the AGI literature miscites the other one. Basu and Blanning's
*Metagraphs and Their Applications* (Springer 2007, **READ** — front matter and
the full sample Chapter 1) defines a metagraph as "a set of elements, which are
**assumed to be atomic**, along with a set of edges. Each edge is an ordered
pair of sets of elements." Their own placement: "the one closest to metagraphs
is **directed hypergraphs** … The principal difference … is in the type of
research done in these areas." **There is no edge-to-edge anywhere in Basu and
Blanning.** Goertzel's *Folding and Unfolding on Metagraphs*
([arXiv:2012.01759](https://arxiv.org/abs/2012.01759), **READ**) cites them
twice as the source of "links pointing to links," and **INFERRED**, the
attribution does not hold — the name was inherited, the concept was not.

**Recommendation for the spec pass: do not use the bare word "metagraph."** Say
**recursive hypergraph** or **ubergraph** when you mean edges-in-edges, and cite
Basu–Blanning only for set-to-set mappings. TAP has been bitten by inherited
vocabulary before.

### The property-graph world: a uniform, normative, unanimous no

Twenty systems and four standards documents were checked. The answer is the
same everywhere, and it is written into the *formal model*, not merely into an
implementation.

The crispest statement is openCypher's own (**READ**,
[property-graph-model.adoc](https://raw.githubusercontent.com/opencypher/openCypher/master/docs/property-graph-model.adoc)):

> "A _relationship_ is an entity that encodes a directed connection between
> **exactly two nodes**"
>
> "A _node_ is the basic entity of the graph, with the unique attribute of
> **being able to exist in and of itself**."

That second sentence is the model's stated *justification*: edges are
definitionally **dependent** entities. It is a philosophical position, not an
engineering compromise.

The GQL committee's own paper — authors include Deutsch, Francis, Green, Libkin,
Plantikow and Vrgoč, i.e. the standards committee plus the formal-semantics
working group ([arXiv:2112.06217](https://arxiv.org/abs/2112.06217), Def. 2.1,
**READ**):

> "𝑁 is a finite set of node identifiers; 𝐸 is a finite set of edge identifiers;
> **such that 𝑁 ∩ 𝐸 = ∅**; ρ : 𝐸 → (𝑁 × 𝑁) ∪ {{𝑢, 𝑣} | 𝑢, 𝑣 ∈ 𝑁} is a total
> function **mapping edges to ordered or unordered pairs of nodes**"

The node and edge identifier spaces are **provably disjoint** by definition. And
grepping the full extracted text of that paper, of the GPC calculus paper
([arXiv:2210.16580](https://arxiv.org/pdf/2210.16580)), and of PG-Schema
([arXiv:2211.10962](https://arxiv.org/pdf/2211.10962)) for "hyperedge",
"hyper-edge", "n-ary" and "reif" returns **zero hits in all three** (**READ,
measured**). The body chartered specifically to design a schema language for
property graphs did not contemplate the extension at all.

Neo4j's documentation is equally plain (**READ**,
[GraphAcademy](https://neo4j.com/graphacademy/training-gdm-40/04-common-graph-structures/)):
"**In Neo4j, there is no way to create a relationship that connects a
relationship to a node. Neo4j relationships can only connect nodes.**" A
hyperedge is "**not supported in Neo4j but can be solved by using an
intermediary node.**"

Verified the same way and giving the same answer: TinkerPop/Gremlin, JanusGraph,
Amazon Neptune (both DB and Analytics), TigerGraph, Kùzu, Memgraph, Dgraph,
FalkorDB/RedisGraph, NebulaGraph, Cayley, TerminusDB, and SQL/PGQ via Oracle's
conformant manual. Twenty for twenty.

**And the feature request history is instructive rather than damning.**
[neo4j/neo4j#13293, "Why Not Direct Support for Hyperedges?"](https://github.com/neo4j/neo4j/issues/13293)
was opened 2023-09-09 and **closed 2026-03-04** after two and a half years with
one reply from a Neo4j contributor: "**Hyperedge have come up every now and
then, but have not been prioritized so far. Feel free to re-request the
feature.**" (**READ** via `gh`.) Not rejected on principle. Never prioritised.

**Where the prohibition actually lives matters enormously, and it is not the
same everywhere.** This is the check to run before assuming any given system's
"no" is meaningful:

- **API-layer only.** Amazon Neptune stores property graphs as **quads**, and
  its own documentation says "[the G position] is used to **store the edge ID
  value in the case of an edge**" (**READ**,
  [Neptune data model](https://docs.aws.amazon.com/neptune/latest/userguide/feature-overview-data-model.html)).
  **INFERRED**: internally Neptune's edge properties *are* statements whose
  subject is an edge id — edges are already addressable. The prohibition is at
  the API surface. Neptune also "does allow a vertex and an edge to have the
  same ID," so its id namespaces are *not* disjoint, unlike GQL's. ArangoDB is
  franker still: "**Edges can technically also be used as vertices but the
  usefulness is limited**" (**READ**) — though whether AQL actually *traverses
  through* an edge-as-vertex is **UNVERIFIED**, and a doc sentence ending in
  "but the usefulness is limited" is not a supported feature.
- **Physical.** FalkorDB stores edges as nonzeros in a sparse adjacency matrix
  at coordinate `(src_id, dst_id)` — there is no coordinate space for an edge
  indexing an edge. NebulaGraph's edge key *is* `<src, type, rank, dst>`. No API
  change could relax either.

**Which is exactly the question TAP must ask of itself, and §I.6 already
answered it: TAP's prohibition is four lines of Python in the service layer, over
FKs that point at `Entity` and have no type restriction. TAP is in the
API-layer-only category, and further along it than Neptune, because TAP's edge
already has an identity independent of `(src, type, dst)` — its own `Entity` row
on the spine.**

### RDF's four attempts, and what each one broke

The semantic-web tradition has been trying to say things about statements since
1999 and has produced four designs, each failing differently. Reading them in
order is the cheapest education available on this problem.

**1. Classic reification (`rdf:Statement`).** Four triples per statement — type,
subject, predicate, object — plus metadata, plus the original triple if you also
want it asserted: **six triples to say one annotated fact**. Two documented
defects, both quoted verbatim from
[RDF 1.1 Semantics Appendix D.1](https://www.w3.org/TR/rdf11-mt/) (**READ**, and
note the appendix is headed *Informative*):

> "**A reification of a triple does not entail the triple, and is not entailed
> by it.** The reification only says that the triple token exists and what it is
> about, not that it is true."

and the referential-transparency defect: "**The value of the `rdf:subject`
property is not the subject IRI itself but the thing it denotes**." Tim
Berners-Lee's verdict, 2004 (**READ**,
[Reifying RDF (properly)](https://www.w3.org/DesignIssues/Reify.html)): "**The
form of reification which is provided by the original RDF specification is not
suitable, because it loses that information.**"

But the killer is worse than either, and it is the one that transfers directly
to TAP. From [RDF Primer 2004 §4.3](https://www.w3.org/TR/2004/REC-rdf-primer-20040210/#reification)
(**READ**):

> "there needs to be some means of associating the subject of the reification
> triples with an individual triple in some document. **However, RDF provides no
> way to do this.**"

**Referential integrity is nil. There is no foreign key.** Delete the underlying
triple and the four reification triples remain, semantically unchanged and
undetectably stale — because they never referred to the triple in the first
place. They described its *shape*.

Evidence of abandonment, measured (**READ**, grep of raw W3C HTML): occurrences
of the stem "reif" — RDF 1.1 Primer: **0**. RDF 1.1 Concepts: **0**. RDF Primer
2004: **42**. The 2014 Primer replaced that whole role with §3.5, "Multiple
graphs."

**2. Singleton property.** Mint a unique predicate per statement. Nguyen,
Bodenreider and Sheth, WWW'14 (**READ**, full text via
[PMC4350149](https://pmc.ncbi.nlm.nih.gov/articles/PMC4350149/)). It is elegant
on paper and catastrophic in practice, for a reason that is pure systems
engineering: the data pattern is `s ?pi o` — **a variable in the predicate
position** — which defeats every predicate-first index and every
predicate-selectivity estimator in every engine. Measured consequences below.
It also breaks OWL reasoning outright: `owl:equivalentClass` and friends are
*axiom syntax*, not properties, so singleton-ising them produces "an owl
annotation assertion, which has no logical semantics," tested with HermiT
(**READ**, [Mungall](https://douroucouli.wordpress.com/2021/07/21/edge-properties-part-2-singleton-property-pattern-and-why-it-doesnt-work/)).
His conclusion: "**avoid the SPP regardless of your use case.**"

**3. Named graphs / quads.** The pragmatic substitute: annotate a *set* rather
than a statement. Its failure is documented in the single most citable artefact
in this section — [*RDF 1.1: On Semantics of RDF Datasets*, W3C Working Group
Note, 2014](https://www.w3.org/TR/rdf11-datasets/) (**READ**):

> "**The RDF Working Group did not standardize the semantics of RDF datasets.**"
>
> "**However, discussions within the Working Group revealed that very different
> assumptions currently exist among practitioners**"

It then enumerates **nine** candidate denotations for a graph name, **five**
candidate meanings for the triples inside one, and formalises **seven** distinct
semantics — each a legal reading of the same bytes. A group chartered to define
this failed to. And [RDF 1.1 Concepts §4](https://www.w3.org/TR/rdf11-concepts/#section-dataset)
(**READ**) makes the shortfall normative: "**Despite the use of the word 'name'
in 'named graph', the graph name is not required to denote the graph. It is
merely syntactically paired with the graph.**"

Note also the granularity trap, which is the same trap one column over: pushing
statement-level identity into the graph slot means one named graph per
statement, which on Wikidata is **57 million named graphs**, at which point
4store "**slowed to loading 24 triples/second**" and the load was killed
(**READ**, Hernández et al., below). And it burns the one context slot you had
for access control, versioning, and source tracking.

**4. RDF-star → RDF 1.2.** The current, live attempt — and the most instructive,
because its designers changed their minds in public.

The Community Group report of 2021 (**READ**,
[RDF-star and SPARQL-star](https://www.w3.org/2021/12/rdf-star.html)) chose
**type over token**: "**Unlike reified statements, RDF-star quoted triples are
unique**: wherever `<< :employee38 :jobTitle "Assistant Designer" >>` appears,
it always denotes one and the same thing." The report names the philosophical
problem outright — "**this is known, in philosophy and linguistics, as the
type-token distinction**" — and then, in Appendix B.2, publicly retracts its own
motivating example:

> "**it appears to have set wrong expectations about what quoted triples
> represent** … **The problem with this interpretation is that it will break as
> soon as other creators and sources are added for the triple: one could not tell
> which source corresponds to which creator.** … **the seminal example does not
> work as stated**."

And RDF 1.2 (**READ**,
[RDF 1.2 Concepts](https://www.w3.org/TR/rdf12-concepts/), **W3C Candidate
Recommendation Snapshot, 7 April 2026**) bought occurrence identity back **by
adding a node**: a *triple term* is permitted **in object position only**, and
you point at it via a **reifier** — a minted node related by `rdf:reifies`.

**INFERRED, and worth stating plainly: the CG design collapsed occurrences into
types, and RDF 1.2 bought occurrence identity back by adding a node. That is
reification again — better spelled, with a standard predicate and real syntax
sugar, but structurally the same move.** Twenty-two years, four designs, and the
answer converged on "mint a node for the occurrence."

Two further findings from this thread that bear directly on TAP:

- **Opacity versus transparency is per-predicate, not per-system.** `:measuredOn`
  is about the *fact* and wants transparency; `:source` is about the *record* and
  wants opacity. The CG's fix was a per-property flag,
  `rdf-star:TransparencyEnablingProperty` (**READ**, §6.4.4–6.4.5). **A system
  that treats all edge-annotations alike will be wrong about half of them.**
- **Delete semantics, and this is the most directly relevant precedent in the
  entire corpus** (**READ**, CG report §5.1.1–5.1.3):

  > "**Notice that deleting triples by using the DELETE DATA operation does not
  > affect any other triples** … the following operation **would delete this
  > asserted triple but it would not delete any nested triple that contains the
  > given triple as a quoted triple.**"

  The most carefully argued design in this space deliberately chose: **asserting
  an edge-about-an-edge neither asserts nor requires the inner edge, and deleting
  the inner edge leaves the outer standing.**

Engine support is thin and one major implementation has given up in place.
Stardog's own documentation (**READ**,
[edge properties](https://docs.stardog.com/query-stardog/edge-properties)):

> "This feature is based on early RDF/SPARQL research proposals and **does not
> implement the later RDF 1.2 and SPARQL 1.2 working drafts. It also has several
> known performance problems and is not recommended for new Knowledge Graph
> projects.**"

Stardog's limitation list is also the most honest inventory anywhere of what
edge-annotation costs an engine: only triple *subjects* may carry properties;
**nested edge properties are forbidden**; edge properties must live in the same
graph as their edge; the database must be created with `edge.properties` on and
it is **immutable thereafter**; the system silently switches to abort-on-conflict
transactions, "which creates complications in clustered deployments with
concurrent writes"; and — note this one — **edge properties cascade-delete when
their parent edge is removed**.

### What it costs, measured

Three independent teams measured the RDF encodings. Their results are more
surprising than the arithmetic suggests.

**Hernández, Hogan and Krötzsch**, *Reifying RDF: What Works Well With
Wikidata?*, SSWS 2015
([PDF](http://ceur-ws.org/Vol-1457/SSWS2015_paper3.pdf), **READ**). n =
57,088,184 Wikidata statements, p = 1,311 predicates, five engines:

| Schema | Formula | Tuples |
| --- | --- | --- |
| standard reification | 3n | 171,264,552 |
| n-ary relations | 2(n+p) | 114,178,990 |
| singleton properties | 2n | 114,176,368 |
| named graphs | n | 57,088,184 |

And then, verbatim:

> "**even though different models lead to different triple counts, index sizes
> were often nearly identical**: we believe that since the entropy of the data is
> quite similar, compression manages to factor out the redundant repetitions"

> "**4store and GraphDB both ran into problems when loading singleton
> properties, where it seems the indexing schemes used assume a low number of
> unique predicates**"

> "**Jena failed to return answers for singleton properties, timing-out on all
> queries**"

Firsts across 70 engine × query cells: named graphs 17, reification 16, n-ary 4,
singleton properties 3 firsts and **34 "could not run."** Overall verdict: "**no
clear winner between standard reification, n-ary predicates and named graphs**."

**Orlandi, Graux and O'Sullivan**, ICSC 2021
([PDF](https://fabriziorlandi.net/pdf/2021/ICSC2021_REF-Benchmark.pdf),
**READ**), on Stardog 7.3, found the *opposite* sign on storage: "with Stardog,
approaches such as **singleton and RDF\* cause the database size to increase at a
much faster rate than reification**" — despite RDF-star using 61.0 M triples
against reification's 175.6 M. Their distinct-predicate counts tell the story:
reification 6, RDF-star 674, **singleton 33,630,338**.

**Three lessons, and they are not the ones you would guess:**

1. **Element count is a poor proxy for storage cost.** Two teams measured this
   and disagreed with the naive arithmetic in *opposite directions*. Do not
   estimate the cost of a path representation by counting rows.
2. **Encoding identity into a structural position has hard engine costs.**
   Predicate position → 33.6 M distinct predicates → four of five engines fail.
   Graph position → 57 M graphs → 24 triples/second. Subject position → 3–6×
   inflation and up to 21 triple patterns per query. **The measured evidence
   favours a dedicated identifier over overloading an existing position** —
   which, note, is exactly what TAP already has, because an edge is an `Entity`
   with a uuid7.
3. **The largest live deployment of edges-about-edges pays for it by emitting
   the data twice.** Wikidata ships both `wdt:` truthy direct claims
   ("convenient to search, index and match") *and* the full `p:/wds:/ps:/pq:`
   reified statement nodes (**READ**,
   [Wikibase RDF Dump Format](https://www.mediawiki.org/wiki/Wikibase/Indexing/RDF_Dump_Format)).

### The two systems that say yes, and what it costs them

**TypeDB** is the strongest *typed* production yes, and its documentation is
unusually candid about the bill.

The model is PERA — entities, relations, attributes, with **roles as
interfaces**. The normative sentence (**READ**,
[TypeQL data model](https://typedb.com/docs/typeql-reference/data-model/)):

> "**Relation types can also have capabilities, i.e. play roles or own attribute
> types. This, for example, allows the creation of nested relations (i.e.,
> relations playing roles in other relations).**"

The boundary is sharp and well chosen: entity and relation types are "object
types" and may have capabilities; **attributes may not**. So node→edge and
edge→edge, never attribute-as-participant. The nesting is **type-constrained** —
"only a relation of type `acquisition` can fill the `reviewed-acquisition` role"
— which is the key differentiator from RDF-star and from HyperGraphDB, and the
theoretical footing is dependent types, under which "**entities are understood
as nullary relation types**" (**READ**,
[Academy 11.1](https://typedb.com/docs/academy/11-advanced-modeling/11.1-using-dependent-types/)).

Now the bill, from TypeDB's own Academy rather than its marketing (**READ**,
[Academy 9.7](https://typedb.com/docs/academy/9-modeling-schemas/9.7-avoiding-interface-redundancies)):

> "**Nested relation types are an advanced feature of the PERA model. They can be
> difficult to deal with, and so should be used with caution.**"

and on the same page, the specific thing it breaks: **standard deletion
strategies cannot be universally applied** once nested relations exist.

*The vendor that ships edge-to-edge says the thing it breaks is deletion.* And
the state of play is worse than that warning implies (**READ**,
[Academy 4.3](https://typedb.com/docs/academy/4-writing-data/4.3-deleting-data/)
and [@cascade](https://typedb.com/docs/typeql-reference/annotations/cascade/)):

> "**When deleting a roleplayer, related relations are not deleted automatically
> unless your schema uses role `@cascade`, once available.** Otherwise, delete
> related relations first, then the roleplayer."

> "**The `@cascade` annotation is a planned feature and not yet available in
> TypeDB. Coming soon!**"

So today, deleting a role player **leaves the relation standing with a hole in
it**, unless the deletion empties it entirely, in which case a separate rule
reaps nullary relations at commit. Compose that with unbounded recursive nesting
and the application must delete an arbitrarily deep tower top-down, by hand.
There is also **no benchmark anywhere that isolates nested relations** — the
feature is well specified and unmeasured (**UNVERIFIED**, a gap I could not
close).

**OpenCog AtomSpace** is the maximalist yes, and it makes a trade that is
directly fatal to one of TAP's requirements.

The model has no node/edge distinction at all: an Atom is a Node (arity 0) or a
Link (arity > 0), and "**Furthermore, Links can also hold other Links**"
(**READ**, [wiki/Link](https://wiki.opencog.org/w/Link)). The outgoing set is an
*ordered* vector (`HandleSeq _outgoing;`, **READ**, `Link.h`), so AtomSpace
edges are ordered tuples — a stronger structure than a hypergraph edge.

The price is stated in the same document:

> "**The AtomSpace ensures that Links are unique. Links are identified only by
> their type and outgoing set (and by nothing else).** … Inserting a second Link
> of the same type and outgoing set just returns the first Link."

Vepštas spells out the consequence (**READ**,
[*Graphs, Metagraphs, RAM, CPU*](https://github.com/opencog/atomspace/blob/master/opencog/sheaf/docs/ram-cpu.pdf) §7):

> "Suppose one wishes to change 'just one' of the 'n3's into an 'n5'. But which
> one? **They are, after all, all the same 'n3', so if edited, they all change
> together, atomically.**"

**INFERRED, and this is the finding that should stop a TAP design in its
tracks:** you cannot have two distinct edges with the same type and endpoints.
The same relation observed by two collectors on two days is *one* Link.
Per-instance metadata cannot live on the edge. The escape is to add a
distinguishing node to the outgoing set — **which is reification again, re-imposed
by a system that was supposed to have escaped it.**

**AtomSpace gives you edge-to-edge for free but takes away edge-instance
identity to do it. Those two properties trade against each other; they are not
bundled.** If TAP's real requirement is "two observations of the same relation
must stay distinguishable" — and given FLIP, batch provenance and
re-observation-is-not-change, it demonstrably is — **that is a multigraph
requirement, not a metagraph one, and adopting a metagraph model would actively
make it harder.**

AtomSpace's deletion story is the other horn (**READ**, `AtomSpace.h`
doc-comment):

> "**if the recursive flag is set to false, and the atom appears in the incoming
> set of some other atom, then extraction will fail.**"
>
> "@param recursive … **this atom, and *everything* that points to it will be
> removed from the atomspace. This can cause a large cascade of removals!**"

Non-recursive **silently fails** (returns `false`; an unchecked caller believes
it deleted something); recursive can take out an arbitrary fraction of the
graph. No `ON DELETE RESTRICT`, no scoping, no dry-run.

**HyperGraphDB** deserves a paragraph for two reasons. First, its author's
statement of the model is the sharpest in the literature (**READ**, Iordanov,
*HyperGraphDB: A Generalized Graph Database*, WAIM 2010,
[PDF](https://hypergraphdb.org/docs/hypergraphdb.pdf)): "**Atoms of arity 0 are
called nodes and atoms of arity > 0 are called links**," and the whole design
"**automatically reifies every entity expressed in the database**." Second, its
critique of RDF reification is the best edge-to-edge argument in the corpus:

> "**In this transformation a single triplet yields 4 triplets, which is
> unnatural, breaks algorithms relying on the original representation, and
> suffers from both time and space inefficiencies.**"

Note the shape of that: the cost of *not* having edge-to-edge is a 4× blowup
**plus the silent breakage of every algorithm written against the unreified
shape.** That is a real cost and it should be weighed.

What it costs: a **mandatory reverse index on every element**. "**The implicit
indexing of atoms described in section 3 is not optional** as it is essential
for an efficient support of the model layer semantics." Because any atom may be
pointed at by any link, there is no structural shortcut — every atom carries an
incidence index, and traversal performance *is* the performance of that index.
AtomSpace's numbers make the same point concretely: 48 bytes per atom for one
naive container, "**incoming sets containing 10K atoms are not unusual, and can
be the source of bottlenecks**," at a target scale of 10⁸ atoms (**READ**,
`Atom.h`).

**And both projects are effectively dead.** HyperGraphDB: 251 stars, 81 open
issues, last substantive commit on master 2024-02-27, last commit of any kind
2025-01-27, **zero published releases, one tag, not on Maven Central**
(**READ**, GitHub REST API queried 2026-09-21). AtomSpace core is alive but
OpenCog proper says "***This repo is no longer maintained!*** … **Some unit tests
fail. Some unit tests won't run. Some code won't compile**," its only fully
supported durable store is a single-writer embedded key-value store, and the
Postgres backend is deprecated with the note that "years of experience have
revealed that the design is not all that great" (**READ**). Kùzu shipped RDF
graphs in v0.0.9, headlined them in v0.2.0, **removed them in v0.7.0 nine months
later**, and the whole organisation is now archived (**READ**, GitHub releases
API).

**INFERRED, and I state it as a pattern rather than a proof: every project in
this survey that made edges-about-edges a first-class primitive is dead,
archived, or shipping the feature with a "use with caution" warning and no
cascade support.** That is not decisive — plenty of good ideas live in dead
projects, and TAP's own comparanda directory is full of them — but it is a
pattern, and the *reason* is consistent across all of them, which makes it worth
more than the correlation alone.

### Deletion is the design problem, not storage

This is the single most actionable finding in Movement II, so it gets its own
table. Every position in the design space is occupied and **nobody agrees**
(all rows **READ** except where noted):

| System | Policy when the pointed-at edge is deleted |
| --- | --- |
| Classic RDF reification | **No link exists.** The reification never pointed at the triple; four stale triples remain, undetectably |
| RDF-star / RDF 1.2 | **Explicit no-cascade, by design.** Deleting the inner triple leaves the outer standing |
| Named graphs | Integrity *inside* the pair; metadata *about* the name dangles. An emptied graph may or may not survive its last triple, implementation-dependently — so **you cannot reliably detect the dangle** (**INFERRED**) |
| Singleton property | Orphan singleton predicate is a **perfectly consistent** graph. Undetectable as an error (**INFERRED**) |
| Stardog edge properties | **Cascade-delete** with the parent edge |
| TypeDB 3.x | **No cascade. `@cascade` is "planned… not yet available."** Role-player deletion leaves a hole; only an emptied relation is reaped |
| HyperGraphDB | **Cascade by default**, `keepIncidentLinks` flag to unlink-but-keep. Per-call, not per-schema |
| AtomSpace | Two horns: non-recursive **silently fails**; recursive **"can cause a large cascade of removals!"** No RESTRICT, no dry-run |
| PROV-O bundles | "adding or removing a triple creates a **new distinct Bundle**" — any edit invalidates the identity the provenance was attached to |

**Edge-to-edge does not break storage. It breaks deletion** — and the two most
mature implementations, HyperGraphDB in 2010 and TypeDB in 2026, landed on
*opposite defaults*, with the newer one still lacking the mechanism the older
one shipped fifteen years ago.

### The constraint test applied

**What forced the property-graph world's "no"?** Three different things, and only
one of them is a real constraint.

1. **A definitional choice about dependence** (openCypher: a node can "exist in
   and of itself," an edge cannot). This is a modelling philosophy. **TAP does
   not inherit it** — TAP already broke it, deliberately, by making `Edge` a
   `BaseModel` with its own `Entity` row. In TAP an edge *does* exist in and of
   itself; it has a uuid7, dimensions, history, a version counter and a
   tombstone. **TAP left the property-graph model's premise behind years ago and
   has apparently not noticed.**
2. **A physical storage constraint** (FalkorDB's matrices, Nebula's derived
   keys). **TAP does not inherit it** — FKs to `Entity` with no type restriction.
3. **The deletion and referential-integrity problem.** **TAP inherits this
   completely**, and it is worse for TAP than for most, because TAP has a
   *shipped, specified, corpus-verified* cascade with an invariant that no live
   edge may point at a tombstone (`req-grid-service-delete-tombstone-7`), and a
   `CONTAINMENT_EDGES` declaration that governs what a delete follows. An edge
   whose endpoint is an edge would immediately raise questions the cascade corpus
   cannot currently express: does tombstoning an edge tombstone the path-step
   edges that point at it? Is a path-step edge a containment edge or a reference
   edge? The corpus families are `depth`, `loops`, `blocks`, `limits`, `records`,
   `undeclared`, `ownership` — none of them has a node-versus-edge endpoint
   dimension.

**And the one argument against building it at all, which deserves a direct
answer rather than a walk-around.** TinkerPop gives *vertex* properties a second
level — `VertexProperty` implements `Element`, so it carries its own properties
— and explicitly denies the same to edge properties, on the stated grounds that
"a vertex can have an edge to a 'literal vertex' … The properties on the edge
represent the literal vertex's properties" (**READ**). **One level of
meta-structure suffices, because the second level is always reachable by
promoting to a vertex.** The market agrees emphatically: edge properties
everywhere, qualifiers-on-qualifiers nowhere, and the one system offering a
second level has it turned off by default in its largest managed implementation
(Neptune's `MetaProperties: false`).

### And the depth question, which reframes the whole argument

The machine-learning community reached the same place from a completely
different direction, and their framing is the most useful one for TAP.

Galkin et al., *Message Passing for Hyper-Relational Knowledge Graphs* (StarE),
EMNLP 2020 ([arXiv:2009.10847](https://arxiv.org/abs/2009.10847), **READ**),
model a statement as `(s, r, o, Q)` — a main triple plus a set of qualifier
pairs — and explain why they did not flatten it into a hyperedge:

> "**We deem hyper-relational graphs and hypergraphs are conceptually different.
> As hyperedges contain multiple nodes, such hyperedges are closer to n-ary
> relations r(e₁,…,e_n) with one abstract relation. The attribution of entities
> to the main triple or qualifiers is lost, and qualifying relations are not
> defined.** Combining a certain set of main and qualifying relations into one
> abstract r_k() would lead to **a combinatorial explosion of typed hyperedges**"

Empirically motivated, independently derived, and it confirms the central thesis
from the ML side: flattening a statement-about-a-statement into a wider hyperedge
destroys role attribution *and* explodes the type space. The payoff for keeping
qualifiers was "gains up to **25 MRR points**."

But note what StarE deliberately does **not** do: a qualifier value is an
entity, not another statement. **Depth 1, not depth k.**

**So the real design axis is depth**, and this is the framing I would urge on the
spec pass:

| Depth | What it is | Who is there |
| --- | --- | --- |
| **0** | arity only | hypergraphs |
| **1** | annotate an edge; the annotation's targets are nodes | RDF 1.2 reifiers, Wikidata qualifiers, StarE, **every property-graph engine's edge properties** |
| **k** | edges about edges about edges | AtomSpace, ubergraphs, TypeDB nested relations, HyperGraphDB |

**"Which depth do we actually need?" is a far more productive question than
"should we allow edges to edges."** And the overwhelming majority of real demand
— including, I will argue in Movement III, TAP's — is depth 1.

One more frame worth adopting wholesale, from the OneGraph paper (Lassila,
Schmidt, Hartig, Bebee, Sequeda et al., *Graph? Yes! Which one? Help!*,
[arXiv:2110.13348](https://arxiv.org/pdf/2110.13348), **READ**):

> "In RDF-star as currently formulated, a triple `<s,p,o>` is understood to be
> unique, in the sense that **there cannot exist an identical instance of that
> triple with its own identity** … In LPGs, each edge is considered a unique
> object with its own identity, and **it is perfectly possible to have two edges
> with identical endpoints and label**."

Two separable questions: **(a) does the edge have identity?** and **(b) is that
identity in the same namespace as node identity?** Property graphs answer
yes/no. RDF-star answered no/yes. OneGraph proposes yes/yes. **TAP already
answers yes/yes** — `Edge` is a `BaseModel`, its identity is an `Entity` id from
the same uuid7 space as every node. TAP is, without having meant to be, already
standing where the unification paper says everyone should end up.

### Gaps I could not close

Stated rather than glossed, because a research document that hides its holes is
worse than a short one.

- **ISO/IEC 39075:2024 and 9075-16:2023 are paywalled** and 403 to an
  unauthenticated fetch. Every standards claim rests on committee members'
  published formal models and Oracle's conformant manual.
- **ArangoDB edge-as-endpoint is documented as possible and never observed.**
  Somebody must actually insert an edge whose `_from` is an edge handle and then
  attempt a traversal through it. This is the one cheap experiment that would
  settle whether *any* production system really does this.
- **Amazon Neptune's "no RDF-star support"** comes from a dated AWS re:Post
  answer; the FAQ is silent, which is not a denial.
- **Dgraph's widely-quoted "facets are not first-class citizens"** could not be
  found in a live primary source; old URLs 404 and archive.org was unreachable.
  Strongly indicated, not confirmed.
- **No benchmark anywhere compares edge-to-edge against reified-node.** That is
  itself a finding: if TAP wants the number, TAP will have to produce it.
- **Mailing-list archaeology** on why reification was abandoned (the
  Hayes/Beckett/DuCharme threads) was not done; the search budget ran out.

## II.4 Attack paths: the tradition that had the choice and still said no

*Section method: SpecterOps documentation and blog posts fetched and read
(**READ**); BloodHound and Cartography **source code read via the GitHub API**
(**READ (source)**); vendor documentation fetched where the vendor permitted it
(Wiz's docs returned HTTP 429 on every attempt, so Wiz claims rest on Google
Cloud's partner page and a third-party production API template — flagged);
several academic primaries are paywalled and are flagged **UNVERIFIED**.*

This is the section where the constraint test earns its keep, because the naive
version of this argument — "BloodHound computes paths at query time, therefore
so should TAP" — is worthless, and the version that survives scrutiny is both
different and much more useful.

### The finding that reverses the naive argument

BloodHound Enterprise **has** falsification machinery. I checked this myself
rather than taking it on trust, and the documentation is unusually good on the
point (**READ**,
[Data Reconciliation and Retention](https://bloodhound.specterops.io/collect-data/enterprise-collection/data-retention)):

> "BHE stores a timestamp on every data point, updated whenever a new collection
> includes the same data point."
>
> "Retention means BHE does not assume that lack of visibility during a single
> collection means that an object or edge no longer exists."

Read that second sentence again, because it is TAP's own `unknown ≠ false` rule,
written by somebody else, for the same reason. BloodHound Enterprise carries:

- a per-data-point **Last Seen** stamp, refreshed on every re-sighting, surfaced
  in the entity panel;
- **retention windows** rather than immediate deletion — 7 days for general data,
  3 days for sessions, both configurable;
- a **separate reconciliation rule for behavioural facts**: `HasSession` edges
  are reconciled by TTL expiry *only*, never by absence from a follow-on
  collection, because they "are generated to indicate patterns of behavior
  rather than session active at any exact moment";
- **transitive visibility** — if a deleted object's SID still appears in an ACE
  elsewhere, its timestamp updates and it survives;
- an awareness of the upstream system's own tombstones: for AD objects the
  retention clock starts only after permanent AD deletion, so the effective
  window is ~187 days (180-day recycle bin + 7);
- and **collection-completeness telemetry** so an operator can see that the graph
  is incomplete rather than assume it is whole (**READ**,
  [Data Quality](https://bloodhound.specterops.io/collect-data/data-quality)):
  "Completeness below 100% is common. Workstations and servers can be offline,
  unavailable, or inaccessible during a collection run."

**So the "it's only a snapshot, it could never trust a stored path" constraint
does not apply to BloodHound Enterprise.** They had the means to persist a path
and know whether it was still true. They chose not to. That makes their choice
evidence rather than a symptom — and it obliges us to find out what they chose
*instead*, because that is where the real design content is.

### But read the source, because the docs undersell it and the split matters

Documentation is a vendor's account of itself. The BloodHound source was read
directly (**READ (source)**, `SpecterOps/BloodHound` via the GitHub API), and it
changes the picture in two directions at once.

**It is better than the docs suggest at the edge level.** `packages/go/graphschema/common/common.go`
declares, as *common* properties:

```go
Collected     Property = "collected"
LastSeen      Property = "lastseen"
FirstSeen     Property = "firstseen"
LastCollected Property = "lastcollected"
WhenCreated   Property = "whencreated"
CompositionID Property = "compositionid"
```

and `cmd/api/src/services/graphify/ingestrelationships.go` writes
`nextRel.RelProps[common.LastSeen.String()] = batch.IngestTime` — **`lastseen`
lands on relationship properties, not merely on nodes.**

More striking, there is a **content-addressed changelog daemon**
(`cmd/api/src/daemons/changelog/model.go`) implementing, in Go, almost exactly
what TAP calls re-observation-is-not-change:

```go
func (s EdgeChange) IdentityKey() uint64 {
	identity := s.SourceNodeID + "|" + s.TargetNodeID + "|" + s.Kind.String()
	return xxhash.Sum64String(identity)
}

// ignoredPropertiesKeys defines a set of node/edge properties that are
// excluded from content hashing. These fields are typically volatile
// (timestamps, collection metadata, environment-specific IDs) and are
// not meaningful indicators of a substantive graph change.
ignoredPropertiesKeys = map[string]struct{}{
	propLastSeen: {}, propObjectID: {}, "lastcollected": {},
	"isinherited": {}, "domainsid": {}, "isacl": {}, "tenantid": {},
}
```

An unchanged edge routes through `EdgeChange.Apply()`, which writes **only**
`lastseen` — a pure touch. A changed edge takes the full update path. **That is
a stable per-edge identity key, plus a content hash with an explicit volatility
denylist, plus a re-observation-versus-change distinction — and it is the single
most directly reusable artefact this research turned up**, because it is
tap#322's ruling implemented by someone else, in a different language, against
the same problem.

**And it is worse than the docs suggest in two specific, decisive ways.**

*First, there is no tombstone and no run provenance.* A code search for
"tombstone" across the repository returns **zero results** (**RAN** via
`gh api search/code`); every deletion path is `DETACH DELETE` or
`batch.DeleteRelationship(id)`. And `normalizeEinNodeProperties`
(`cmd/api/src/services/graphify/ingestnodes.go:139`) stamps exactly two things —
`lastseen` and `objectid`. No job id, no collection-run id, no collector
identity, no source-file provenance on any fact. The inbound `reconcile` hint is
explicitly `delete()`d before the write. **You can ask when a fact was last
seen. You cannot ask by which run, from which collector, or whether that run was
scoped or complete** — so you cannot distinguish "not seen for six days because
it is gone" from "not seen for six days because the only collector covering it
has been failing."

*Second, and this is the mechanism nobody writes down: the ingest path cannot
express edge absence at all.* SharpHound's wire format does carry an
observed-versus-unobserved flag —
`type APIResult struct { Collected bool; FailureReason string }`
(`packages/go/ein/incoming_models.go:286`) — and it is consumed as a guard:

```go
if item.SmbInfo.Collected {
	itemProps[ad.SMBSigning.String()] = item.SmbInfo.Result.SigningEnabled
}
```

Not collected ⇒ the property is not written ⇒ the previous value survives.
Unobserved leaves the old claim standing. There is even one hand-written
observed-absent *retraction* (`packages/go/ein/ad.go:122`), comment and all:

```go
if item.NTLMRegistryData.Collected {
	// If a registry value doesn't exist, assign its item prop to nil to clear it from the node
	itemProps[ad.RestrictOutboundNTLM.String()] = nil
```

Nine properties get that treatment. Hundreds do not. **And for edges there is no
absence channel whatsoever**: `if computer.Sessions.Collected { for … emit
HasSession }` — collected-and-empty emits nothing, not-collected emits nothing,
**identical at the graph**. No edge is ever retracted at ingest, under any
circumstance.

**That is the mechanical explanation for the TTLs I quoted approvingly above.**
BHE's 3-day session and 7-day general retention windows are not a considered
preference for time-based reconciliation. **The ingest path structurally cannot
express edge absence, so elapsed time is the only retraction mechanism
available.** The docs' graceful sentence about behavioural patterns is true, and
it is also making a virtue of a missing channel.

**So the CE/BHE split has to be drawn wherever BloodHound is cited as evidence,
and only one half of it counts.** Community Edition has per-edge `lastseen`,
stable edge identity and change detection — but no reaper, no tombstone, no run
provenance and no edge-absence channel. `PruneData` is documented *in source* as
removing "outdated/invalid **ingest files**," not graph data, and the separate
garbage-collection daemon sweeps web sessions, asset-group collections and SAML
identifiers — nothing touches a relationship. **Stale CE edges survive
indefinitely. For CE, query-time computation is forced, not chosen, and citing
it proves nothing.** Enterprise adds continuous collection and TTL
reconciliation, and Enterprise's choice is the one that carries weight.

### What they persist instead, part one: derived edges with reconstructible proofs

This is verified in source, not inferred from marketing.

`packages/go/graphschema/ad/ad.go` declares `PostProcessedRelationships()` — 31
edge kinds including `DCSync`, `CanRDP`, `AdminTo`, `GoldenCert`, the whole
`ADCSESC*` family, `CoerceAndRelayNTLMTo*`, and `GPOAppliesTo`. Against that,
`PathfindingRelationships()` lists 63 traversable kinds. **Roughly half of the
edge vocabulary you path over in BloodHound is computed, not collected**
(**READ (source)**; the ratio is **INFERRED** from the two lists).

And the computation is a full teardown. `packages/go/analysis/post/post.go`:

```go
func DeleteTransitEdges(ctx context.Context, db graph.Database, baseKinds graph.Kinds,
                        targetRelationships graph.Kinds) (*AtomicPostProcessingStats, error)
```

called at the top of AD post-processing, which fetches every relationship id of
every post-processed kind, batch-deletes them, and then rebuilds them from
scratch. **There is no incremental path.** Every analysis run destroys and
recreates the derived layer.

The semantics are documented and they are the best idea in this section
(**READ**, [ADCS attack paths in BloodHound](https://securityboulevard.com/2024/01/adcs-attack-paths-in-bloodhound-part-1/)):
`GetChanges` and `GetChangesAll` are **non-traversable** edges — "you cannot
abuse a given relationship between two nodes to take control of the end node" —
and "BloodHound uses them to produce the traversable DCSync edge in what we call
the post-processing logic." Then the **Composition** feature expands a derived
edge back into "all the nodes and edges involved in meeting the requirements."

**A derived edge is a persisted *claim* carrying a lazily reconstructible
*proof*.** You get the queryability of a materialised conclusion and the
auditability of a path, and you store neither a path nor a proof. That is the
single most transferable idea in Movement II for a security product, and TAP's
July "structural containment" note is reaching for the same shape from the other
direction — except that TAP's note proposes to *compute* the containment
relation as a path, where BloodHound *materialises* it as an edge and keeps the
path derivable.

### What they persist instead, part two: reachability as bitmaps

SpecterOps built their own graph layer, `dawgs` — "Database Abstraction Wrapper
for Graph Schemas," running property graphs "on vanilla PostgreSQL without extra
database plugins," with an openCypher-to-SQL translator
([SpecterOps/DAWGS](https://github.com/SpecterOps/DAWGS), **READ (source)**).
That alone should interest TAP, which made the same bet. But the relevant part
is that `dawgs` contains exactly two algorithms — Tarjan SCC condensation, and
reachability — and the reachability API is:

```go
// CanReach determines whether a directed path exists from startID to endID ...
func (s *ReachabilityCache) CanReach(startID, endID uint64, direction graph.Direction) bool
```

**It returns a boolean.** No path is constructed or retained. The
implementation condenses the graph into strongly-connected components, stores
per-component reachability as bitmaps, and holds them in a bounded SIEVE LRU
cache sized at **15% of node count**. It is built **filtered by edge kind**,
once per analysis run, and handed to every post-processing function — bound, in
the AD code, to a variable literally named `groupExpansions`.

**INFERRED, high confidence:** BloodHound's answer to "MemberOf is transitive
and walking it repeatedly is ruinous" is to compute the **transitive closure of
group membership once per run, as bitmaps**, and pass it down. That is a
materialised *closure*, bounded and cached — not a materialised path set. It is
also, note, precisely the thing TAP's cascade closure computes on every delete
and throws away.

### What they persist instead, part three: findings, which have identity

Here is the definition, and it is the crux of the whole section (**READ**,
[Attack Paths](https://bloodhound.specterops.io/analyze-data/findings/attack-paths)):

> "A **finding** is a specific instance of an Attack Path that BloodHound
> Enterprise has identified as a high-value remediation point… **An attack path
> is the route. A finding is the identified risk instance tied to that route.**"

A finding is a persisted record with a five-state lifecycle and stored status
values (**READ**):

| Status | Stored | Meaning | Archived |
| --- | --- | --- | --- |
| Open | `active` | currently detected | No |
| Accepted | `accepted` | known risk, not expired; still counted in posture | No |
| Remediated | `remediated` | "A later analysis run no longer detects the Attack Path" | Yes |
| Orphaned | `orphaned` | environment archived or no longer collected | Yes |
| Deprecated | `deprecated` | "The finding type is no longer defined in the current schema" | Yes |

User transitions are Open↔Accepted only; acceptance is **time-boxed in days and
auto-expires back to Open**; the other three are terminal and system-set during
analysis. I verified the acceptance semantics independently (**READ**,
[Risk Acceptance](https://bloodhound.specterops.io/analyze-data/findings/risk-acceptance)):
an accepted principal is "hidden from the default principal table view for that
finding" but "is still included in posture calculations." **Acceptance is not
remediation, and the metric refuses to let you pretend otherwise.**

And the record's shape, from BHE's own CSV export (**READ**), is the thing to
copy:

```
Severity, Finding, Title, FindingType, Platform, EnvironmentID, ZoneName,
SourcePrincipalID, SourcePrincipalKind, SourcePrincipalName,
TargetPrincipalID, TargetPrincipalKind, TargetPrincipalName,
Status, FirstSeen, LastSeen, ArchivedAt
```

**The identity key is `(finding_type, source_principal, target_principal,
environment, zone)`.** Bounded. Stable. Diffable across runs. *That* is why
`FirstSeen` / `LastSeen` / `remediated` are possible at all.

### So what actually forced the choice? Identity, not truth

Put the three pieces together and the constraint falls out cleanly, and it is
not the one anybody would guess.

**A discovered path has no stable identity across recomputes.** Run the
analysis, get a route. Run it again after the graph moves, get a route that is
*mostly* the same but detours around a patched host. Is that the same path,
repaired? A different path? The old one closed and a new one opened? There is no
principled answer, because the path's identity was never anything more than the
sequence of edges the algorithm happened to return — and that sequence is, as
§II.1 established, frequently one of several legitimate answers to a
non-deterministic selector.

Everything BloodHound persists is keyed on something that *does* survive
recomputation: an edge is keyed on `(source, type, target)`; a finding is keyed
on `(type, source, target, environment, zone)`; reachability is keyed on a pair.
The path, alone among these, is keyed on nothing.

**That constraint is real, it is not an artefact of BloodHound's substrate, and
it is the thing a naive path-as-node design walks straight into.** The industry
evidence is unanimous and it took the agent a great deal of reading to establish
that the unanimity is not laziness:

- **Only two vendors give an attack path a durable identifier at all** —
  Microsoft (an Azure Resource Graph resource type,
  `microsoft.security/attackpaths`, with an `AttackPathID`) and Rapid7 (an
  "Attack Path ID" usable with the API) — **and neither gives it a status
  field** (**READ**,
  [Microsoft's attack path API](https://learn.microsoft.com/en-us/azure/defender-for-cloud/attack-path-api)).
  Microsoft's path is *addressable but not stateful*, and its resolution model is
  an absence: "Once an attack path is resolved, it can take **up to 24 hours**
  for an attack path to be removed from the list." A resolved path is not
  closed. It stops being returned.
- **Wiz's Control is a saved graph query; the persisted object is an Issue**, one
  per matching result, carrying `id / status / createdAt / resolvedAt / dueAt /
  notes / serviceTickets` and — the nice touch — an `entitySnapshot` of the
  subject's state at finding time, so the Issue survives the asset mutating or
  vanishing (**READ**, via
  [Google Cloud's Wiz partner architecture page](https://docs.cloud.google.com/architecture/partners/id-prioritize-security-risks-with-wiz)
  and a third-party production API template; **docs.wiz.io returned 429 on every
  attempt**, so no Wiz product doc was read).
- **Prisma Cloud has the best-documented reopen semantics in the industry**, and
  the asymmetry is a genuine design ruling (**READ**,
  [Prisma Cloud alerts](https://docs.prismacloud.io/content-collections/alerts/view-respond-to-prisma-cloud-alerts)):
  "A resolved alert can also **transition back to the open state if the issue
  resurfaces**," whereas "Alerts that are manually dismissed **remain in the
  Dismissed state even when the same policy violation happens again**."
  *Auto-resolve reopens; human-dismiss does not.* A human decision to suppress
  outranks the recompute; a machine decision to resolve does not.
- **Sysdig offers the cheap middle path** and it deserves more attention than it
  gets (**READ**, [Sysdig Risks](https://docs.sysdig.com/en/sysdig-secure/risks/)):
  a Risk is tagged **New** "if previously we had no affected resources match this
  risk, and now at least one does," and stays New for 7 days; **Live** means a
  high-confidence event within the last 3 hours. **That is transition detection
  without any path history at all** — you only need "did the matched set go from
  empty to non-empty," plus a decay window.

### Does TAP inherit the constraint? Yes — and the July ruling is the escape

This is the point the whole section exists to make, so it gets stated plainly.

**The identity constraint transfers completely to any TAP design where paths are
produced by traversal and then materialised.** TAP's batch pointers, tombstones,
version counters and unobserved-versus-observed-empty rule are all machinery for
knowing whether a *fact* is still true. None of them tells you whether two
computed routes are *the same path*. A materialised-traversal path in TAP would
have exactly BloodHound's problem, plus TAP's own aggravating factor: Gryphon
cannot compute a path at all today (§I.6), so there would be no second opinion
to diff against.

**But the constraint does not transfer to a declared path, and this is the whole
argument.** A path that is *declared* — "the containment closure rooted at
account X," "the deploy path for service Y," "the reliance chain that
`RUNS_ON` establishes" — has identity by construction, because its identity is
the declaration, not the route. The route becomes what the declaration currently
resolves to. And that is exactly the two-level structure §II.7 found in RFC 9256
(`<headend, colour, endpoint>` is the identity; the active candidate path is the
current answer) and §II.8 found in BPMN (the definition is the identity; the
instance is the walk).

**TAP's July 2026 ruling — reachability by declared path membership rather than
by variable-length traversal — is therefore not merely a cheaper implementation.
It is the move that supplies the identity the whole industry could not find.**
I do not think the ruling was made for that reason (the feature-demand study
argues it on cost grounds: it "sidesteps E1's recursive-CTE, the heaviest
wishlist item"), which makes it the happiest accident in this dossier.

### The four-constraint transfer table

This is the load-bearing analysis of the whole movement, so it is set out
explicitly. Four distinct constraints push every system in this section toward
ephemeral paths. TAP's substrate — batch provenance, tombstones, an explicit
unobserved-versus-observed-absent convention, re-observation-is-not-change,
`Entity.version` — dissolves **exactly one of the four**.

| Constraint | Does it transfer to TAP? |
| --- | --- |
| **Falsifiability** — you cannot know whether a stored path is still true | **No. Dissolved.** Per-fact batch provenance plus tombstones plus an observed-absent signal lets TAP invalidate a stored path *on evidence* rather than *on a timer*. Nobody surveyed can do this. It is TAP's genuine, distinguishing advantage and it is real |
| **Identity** — a path has no stable key | **Yes, fully. Untouched.** Provenance and tombstones do nothing here. An edge has a natural key (BloodHound literally hashes `source\|target\|kind`); a finding has one; **a path, being a sequence of unbounded length through a mutating graph, has none** |
| **Retraction cost** — full rebuild every run | **Partially.** Provenance makes incremental maintenance *expressible*, but the monotonicity asymmetry survives: additions are cheap, retractions are structurally hard. An explicit observed-absent signal helps here more than tombstones do, because it converts "unknown, assume still true" into a genuine retraction event |
| **Combinatorial volume** — *"millions, if not billions of Attack Paths"* at 1,000 endpoints | **No relief whatsoever.** Substrate features are orthogonal to cardinality. A billion paths are exactly as unstorable with perfect provenance as without it. **This alone forecloses storing paths exhaustively, regardless of how good TAP's substrate is** — and it is the constraint most easily forgotten, because it is the one that sounds like an implementation detail and is not |

**One of four.** That is the honest accounting, and it is both more and less
encouraging than it sounds: the dissolved constraint is the one no competitor has
dissolved, and the surviving three are the ones that decide the design.

**And BloodHound's documentation contains the proof that identity is what drove
their design** (**READ**): "A single finding may include multiple Attack Paths
when different intermediate nodes all enable the same type of access from source
to target." **They collapsed the path set to its endpoints precisely in order to
obtain a stable key.** That is not a presentation choice. It is the identity
problem being solved by projection, and the projection is lossy on purpose.

So the decision TAP must actually make, stated as a fork with three tines and no
fourth:

1. **Key on endpoints** — you have reinvented BHE Findings, and the
   multiple-paths-per-finding collapse comes with it.
2. **Key on the full node/edge sequence** — a new object every time any
   intermediate hop changes; churn proportional to graph volatility.
3. **Key on the declaration** — the path's identity is the thing that *asked*
   for a path, and the route is what the declaration currently resolves to.

The third is the one no vendor in this section took, because none of them has a
declaration layer. It is also, exactly, RFC 9256's `<headend, colour, endpoint>`
(§II.7), BPMN's process definition (§II.8), WINGS' workflow template (§II.5),
and Reactome's stable identifier (§II.6). **Four traditions, independently, put
the identity on the intent.** Movement III's recommendation is built on that
convergence.

### The rest of the field, briefly, with its constraints named

**Cartography** (Lyft, now CNCF) persists derived *edges and properties* via
Analysis Jobs, and its constraint is self-inflicted and instructive. Cleanup is
`WHERE n.lastupdated <> $UPDATE_TAG … DETACH DELETE` (**READ (source)**,
`cartography/graph/cleanupbuilder.py`) — note `<>`, not `<`: anything not
touched by *this exact run* dies. **Because cleanup is a destructive delete,
Cartography's graph is a point-in-time snapshot with no history**; a node
deleted and later re-observed gets a *new* `firstseen`, and "did this path exist
for forty days?" is unanswerable inside the graph. That is precisely why
`drift-detect` had to be built *outside* it, as timestamped JSON files on disk
compared by an external differ (**READ**,
[drift-detect docs](https://docs.cartography.dev/usage/drift-detect.html)).
**Does TAP inherit it? No — and this is the sharpest contrast in the dossier.**
TAP tombstones; it does not delete. The whole reason Cartography's change-history
lives in a filesystem diff is the reason TAP's would not have to.

Cartography does contribute one rule TAP must copy if it ever materialises
anything: **merge-then-sweep, not sweep-then-merge.** Its docs are explicit that
relationship effects "run their `MERGE` statements first and delete
relationships with an old `lastupdated` value afterward. **This avoids a window
where concurrent readers see all managed relationships disappear.**" BloodHound,
which deletes then rebuilds, has exactly that window and evidently tolerates it
because analysis is a visible discrete phase.

And Cartography supplies the honesty paragraph every path product should
plagiarise (**READ**,
[AWS privilege escalation queries](https://docs.cartography.dev/usage/aws-privilege-escalation-queries.html)):

> "These queries are **triage aids, not effective-permission evaluations**. They
> match action strings on `Allow` policy statements and do not account for
> resource scope, conditions, explicit denies, wildcard actions, permissions
> boundaries, service control policies, **or whether a principal can reach a
> suitable target**."

Anyone shipping a *persisted* path owns that entire list, and owns it over time
rather than only at query time.

**Wiz and Prisma Cloud are, on reflection, stronger evidence than BloodHound**,
and I want to be explicit about why, because it is the reverse of the obvious
reading. Wiz already persists a rich, lifecycle-bearing object with a
tombstone-substitute built in — `entitySnapshot` freezes the subject's state at
finding time so the Issue survives the asset mutating or vanishing. Prisma
already has a five-state lifecycle with reopen-on-resurface and a documented
human-dismiss asymmetry. **These are vendors who solved persistence, shipped it,
and then declined to apply it to paths.** Their constraint cannot be
falsifiability, because they demonstrably have the machinery. It is identity and
cardinality. **Two independent considered rejections beat one forced one.**

**Steampipe / Powerpipe** is the control case, and on reflection it should carry
much less weight than I first gave it: it persists nothing at all.
Steampipe's own FAQ says so — "results flow into Postgres as ephemeral tables
that are only cached for 5 minutes (by default)… **stores nothing by default**"
(**READ**). Powerpipe has `graph` blocks, but a measured read of
`turbot/steampipe-mod-aws-insights` found **140 hand-written `node` definitions,
289 hand-written `edge` definitions, and zero recursive CTEs** (**READ
(measured)**). It is fixed-depth, hand-authored, one-hop-out neighbourhood
expansion. **The 289 is the number to cite against per-type hand-authoring** —
it is the maintenance cost of a slug list made visible, which is the fate TAP's
July note was explicitly trying to avoid when it asked for an edge
*classification* instead of an enumerated set. But note what Steampipe is *not*
evidence for: path persistence was never declined there on the merits, it is
simply unreachable from a live-query foreign-data-wrapper with a five-minute
cache. **Cite Steampipe for the maintenance number and for the file-diff
convergence, and for nothing else.**

Note the convergence, which is not a coincidence: **when a non-persisting system
is asked for change-over-time, it reaches for a file diff.** Cartography's
drift-detect states and Powerpipe's snapshot JSON are structurally the same
answer, arrived at independently.

### The academic lineage, and the one asymmetry nobody has named

The attack-graph literature is a forty-year argument about whether you can build
the graph at all, and it was settled in 2002 by a single idea.

- **Schneier's attack trees** (*Dr. Dobb's*, December 1999,
  [schneier.com](https://www.schneier.com/academic/archives/1999/12/attack_trees.html),
  **READ**) are goal-rooted, hand-authored, with AND/OR nodes and value
  propagation. Everything since is an attempt to *generate* this from observed
  configuration.
- **Sheyner and Wing** (IEEE S&P 2002,
  [PDF](https://conferences.computer.org/sp/pdfs/sp/2002/02_08_01.pdf), **READ**)
  automated it with symbolic model checking. The numbers are the point: **5
  hosts and 8 atomic attacks** produced a graph of **5,948 nodes and 68,364
  edges** in **2 hours**, and minimising it is NP-complete by reduction from
  minimum cover.
- **Ammann, Wijesekera and Kaushik** (CCS 2002) introduced **monotonicity** —
  "once a postcondition is satisfied, it can never become 'unsatisfied'" and
  "the negation operator cannot be used in expressing action preconditions"
  (**READ** via Sheyner's thesis; the primary is ACM-403 and is **UNVERIFIED**).
  Without it you enumerate orderings and the state space is exponential. With it
  you need only each attribute's first satisfaction, and the structure becomes a
  fixed point over a monotone operator — polynomial.
- **Ou, Boyer and McQueen** (CCS 2006,
  [PDF](https://cse.usf.edu/~xou/publications/ccs06.pdf), **READ**) made it a
  logical attack graph over Datalog, proved size **O(N²)** and construction
  **O(δN²)**, and supplied the comparison that ended the argument: on Sheyner's
  tool, "a network of only **10 hosts with 5 vulnerabilities per host** takes
  about 15 minutes to generate and results in a graph of **10 million edges**."
- **Jajodia and Noel's TVA/Cauldron** stated the principle outright (**READ**,
  [TVA chapter](https://csis.gmu.edu/noel/pubs/TVA_chapter.pdf)): "For
  scalability, what is needed is a representation that allows the (implicit)
  analysis of all possible attack paths **without explicitly enumerating them**."
- **NetSPA** (MIT Lincoln Lab, ACSAC 2006,
  [PDF](https://www.acsac.org/2006/papers/70.pdf), **READ**) took it
  operational — 252 hosts, a graph of 8,901 nodes and 23,315 edges in **0.5
  seconds** — and then simplified it by **99%**, to 80 nodes and 190 edges,
  because nobody could read the real one. Their framing is the lesson: the graph
  is "an **intermediate structure, not a final product**."

**The shape of the whole field, INFERRED:** monotonicity converted *generation*
from exponential to quadratic, and in doing so converted the problem from
**compute** into **comprehension**. Nobody after 2002 complains they cannot
build the graph. Everybody after 2002 complains nobody can read it. Noel and
Jajodia demonstrated in 2004 that **14 machines** produce an unreadable picture
([VizSEC 2004](https://csis.gmu.edu/noel/pubs/2004_VizSec.pdf), **READ**), and
their fix — recursive aggregation along a *protection domain* hierarchy derived
"through knowledge of the network configuration" rather than by running clique
detection — is structurally the same move as BloodHound's SCC condensation and
as SpecterOps' 2025 per-platform subgraphs. Three independent arrivals at
"condense the dense regions first, using what you already know rather than an
algorithm."

**And here is the asymmetry that nobody in the literature appears to have
named, which I flag as the most important open research question this dossier
touched.** A monotone Datalog fixed point is exactly the setting where
incremental view maintenance applies — semi-naive evaluation, the DRed algorithm
(Gupta, Mumick and Subrahmanian, "Maintaining views incrementally," SIGMOD 1993,
DOI [10.1145/170036.170066](https://doi.org/10.1145/170036.170066); Dong and
Topor, "Incremental evaluation of Datalog queries," ICDT 1992, DOI
[10.1007/3-540-56039-4_48](https://doi.org/10.1007/3-540-56039-4_48); both
citations **RAN** via Crossref, bodies **UNVERIFIED**). **Monotone additions are
cheap. Retractions are not** — a host decommissioned, a vulnerability patched, a
firewall rule tightened — because monotonicity gives you no mechanism to
withdraw a derived fact without re-deriving it. *That asymmetry is the
theoretical core of attack-graph staleness, and it is why every system in this
section recomputes wholesale rather than incrementally.* The one paper that
addresses it directly — Saha, "Extending Logical Attack Graphs for Efficient
Vulnerability Analysis," CCS 2008, DOI
[10.1145/1455770.1455780](https://dl.acm.org/doi/10.1145/1455770.1455780),
described in a 2023 survey as presenting a "method to incrementally re-generate
logical attack graphs" — **is paywalled and I could not read it**
(**UNVERIFIED**). It is the single most on-point academic citation for a
persistent-path design and George should read the primary before relying on
anything I have said about it.

**Does TAP inherit the retraction asymmetry? Yes, completely, and this is the
sharpest cost of persistence.** Adding an edge to TAP's grid can only *extend*
the set of true paths. Tombstoning one can *invalidate* paths, and there is no
cheap way to find which. Postgres will not help: `REFRESH MATERIALIZED VIEW`
"**completely replaces the contents of a materialized view**… The old contents
are discarded" — there is no incremental refresh, and `CONCURRENTLY` only avoids
blocking readers, it does not make the refresh partial (**READ**,
[PostgreSQL REFRESH MATERIALIZED VIEW](https://www.postgresql.org/docs/current/sql-refreshmaterializedview.html)).
Any TAP design that materialises path *contents* is signing up for full
recomputation on every retraction, exactly like everybody else.

Which is the argument for the RFC 9256 trick from §II.7: **do not maintain the
path; maintain a cheap staleness signal and re-resolve on read.** TAP's
`Entity.version` and `deleted_at` are exactly that signal, already written on
every canonical mutation, already indexed.

### The ideas from this tradition most worth stealing

1. **A derived edge plus a reconstructible proof** (BloodHound's post-processed
   edges + Composition). The persisted thing is the claim; the path is
   regenerated on demand for audit.
2. **Materialise reachability, not paths** — `CanReach() bool` over SCC-condensed
   bitmaps, LRU-bounded at 15% of node count, built filtered by edge kind once
   per run. Reachability is polynomial and cacheable; paths are not.
3. **Key the persisted object on something that survives recomputation.**
   `(type, source, target, environment, zone)`. If you cannot write down such a
   key for your path, you cannot have `first_seen` / `last_seen` / `remediated`,
   and you should not pretend otherwise.
4. **A five-state lifecycle including `deprecated`** — "the finding type is no
   longer defined in the current schema." That is the schema-evolution state
   almost everyone skips, and TAP will need it the first time a plugin is
   uninstalled with paths declared against its edge types
   (`req-grid-dual-existence-teardown`, currently Backlog).
5. **Time-boxed acceptance that auto-expires back to Open**, with accepted items
   still counted in the metric. Acceptance is not remediation.
6. **The reopen asymmetry**: auto-resolve reopens on resurface; human-dismiss
   does not.
7. **Sysdig's `New` (7 days) and `Live` (3 hours)** as the cheap middle: the
   transition signal without the history.
8. **Microsoft's two-tier remediation split** — "Recommendations: steps that fix
   the attack path" versus "Additional recommendations: steps that lower risk but
   don't fully fix the attack path." **Path-breaking versus risk-reducing.** That
   distinction is what makes a path object actionable even with no status field
   at all, and TAP's "broken paths" concept is the same idea inverted.
9. **Separate configured access from observed access.** Cartography models
   `STS_ASSUMEROLE_ALLOW` (configured permission) distinctly from
   `ASSUMED_ROLE {times_used, first_seen, last_seen}` (derived from CloudTrail
   over a lookback window). Two truth-values, two staleness profiles, two edges.
10. **Merge-then-sweep, batched**, with an explicit statement of the window it
    closes.

And one warning, observed in the wild (**READ**): Microsoft narrowed its
attack-path generator and customers' path inventories silently shrank, with only
a docs note ("You might see an empty Attack Path page") while the published type
catalogue was quietly retired to a 302 redirect. **With no persisted path
objects and no history, there is no record that the population changed**, and a
customer cannot distinguish "we got better" from "the vendor changed the rules."
That is a direct argument *for* persistence — the strongest one in this section
— and it is the mirror image of TAP's own `trace-overlay` warning that an
uninstrumented node must not read as a dead one.

## II.5 Provenance, build chains and tracing: the path that is a legal claim

*Section method: W3C specifications, the OPM FGCS paper, in-toto and SLSA
specifications, SPDX and CycloneDX schemas (diffed directly), OpenTelemetry
specs and protobuf, and git documentation fetched and read (**READ**). Two
paywalled primaries are flagged **UNVERIFIED** and one of them is load-bearing,
so it is called out twice.*

This is the tradition where a path is a *claim* — about how software was built,
where data came from, who touched it — and where getting it wrong has legal and
security consequences. That makes their omissions unusually well argued.

**And the headline finding is a flat negative across nine traditions and roughly
thirty specifications: not one makes a path a first-class object with its own
identity.** Every tradition names the nodes. Several name the hops. Two name a
*set* of facts (PROV bundles, OPM accounts). One names the *shape* of a pipeline
(CycloneDX workflow). One names a *verdict about* a traversal (SLSA's VSA). **The
chain itself is always computed, always at read time, always discarded
afterwards.**

The two standards bodies that came closest each declined for a stated reason,
and those two reasons are the design brief for anything that wants to occupy the
space: **you cannot validate a path, and you cannot identify one.**

### The distinction TAP most needs a name for: prospective versus retrospective

The canonical citation is verified verbatim (**READ**, Freire, Koop, Santos and
Silva, *Provenance for Computational Tasks: A Survey*, *Computing in Science &
Engineering* 10(3):11–21, 2008,
[open PDF](https://www.sci.utah.edu/~csilva/papers/cise2008a.pdf)):

> "When it comes to computational tasks, there are two forms of provenance:
> prospective and retrospective. **Prospective provenance captures a computational
> task's specification** (whether it's a script or a workflow) and corresponds to
> the steps (or recipe) that must be followed to generate a data product…
> **Retrospective provenance captures the steps executed as well as information
> about the environment used to derive a specific data product** — in other
> words, it's a detailed log of a computational task's execution."

And an asymmetry that bears directly on TAP's Movement I question 1:

> "**Retrospective provenance doesn't depend on the presence of prospective
> provenance** — for example, we can capture information such as which process
> ran, who ran it, and how long it took without having prior knowledge of the
> sequence of computational steps involved."

(A caution for the bibliography: **Davidson and Freire, SIGMOD 2008**, is the
citation everyone reaches for and its *content could not be verified* — ACM 403s,
the abstract is publisher-elided, two mirrors failed. The bibliographic record is
confirmed; **do not attribute the prospective/retrospective definitions to it**.
Freire et al. CISE 2008 carries that load and is verified verbatim.)

The single most transferable warning in the tradition is also in that survey,
about Pegasus (**READ**):

> "Although Pegasus models prospective provenance using OWL, it captures
> retrospective provenance by using the Virtual Data System … and then stores it
> in a relational database. **Queries that span prospective and retrospective
> provenance must combine two different query languages: SPARQL and SQL.**"

**Keep the declared path and the observed path in one graph with one query
language, or you will build that seam and then spend years removing it.**
ProvONE, wfdesc/wfprov and Workflow RO-Crate all exist to undo exactly this.

And the reason to keep both, from a 2015 paper that measured it (**READ**, Dey
et al., TaPP 2015, [PDF](https://www.usenix.org/system/files/tapp15-dey.pdf)):

> "**prospective provenance can improve the precision of retrospective provenance
> by reducing the number of 'false' dependencies** and conversely, **fine-grained
> execution provenance can be used to improve the precision of input-output
> dependencies** of workflow actors."

**The declared path de-noises the observed path; the observed path corrects the
declared one.** Bidirectional. That is a better argument for building both than
either half makes alone.

**ProvONE** is the vocabulary that unifies them, and it is worth naming because
it does what TAP would need to do (**READ**, from the OWL file directly — the
human-readable spec is offline behind a Jenkins 503, so cite the OWL, not the
PURL). `provone:Program` is a subclass of **both** `prov:Entity` and
**`prov:Plan`**; `provone:Execution` is a `prov:Activity`; and there are *two*
links between the layers:

- **Whole-program:** `Execution --qualifiedAssociation--> Association
  --hadPlan--> Program`.
- **Event-level, and this is the clever one:** `provone:hadInPort` has domain
  `prov:Usage` and `provone:hadOutPort` has domain `prov:Generation` — **each
  individual observed data movement is annotated with the declared port it flowed
  through.**

**That makes "show me every run where data entered *this* slot of *this* path"
answerable without joining through the whole trace**, and it is the single most
elegant declared/observed join in this section.

**WINGS** supplies the three-rung ladder, and the finding attached to it is
startling (**READ**, Kim et al., *CCPE* 2007,
[PDF](https://pegasus.isi.edu/wordpress/wp-content/papercite-data/pdf/kim2007provenance.pdf)):

> "The first layer of workflow creation defines **workflow templates** that are
> data- and execution-independent specifications… **A workflow template can be
> shared and reused among users performing the same type of analysis.**"

Template (typed, data-free, reusable, library-resident) → instance (data-bound)
→ executable (resource-bound). And then:

> "**most of the queries of the First Provenance Challenge can be answered using
> information that is available in Wings/Pegasus before the execution of the
> workflow begins.**"

**A substantial fraction of the interesting questions were answerable off the
template alone, with no run in hand.** That is the strongest available argument
for TAP's July declared-path ruling, and it comes from people who had both
layers and measured which one carried the load.

### The one named-indirect-dependency construct in the prior art, and why it died

This is the part of Movement II most directly aimed at TAP's design, and it is a
ghost story.

The **Open Provenance Model** (Moreau et al., *FGCS* 27(6):743–756, 2011,
**READ** from a lab mirror — openprovenance.org's DNS is dead) had **multi-step
edges**. §6.2, verbatim:

> "When users want to find out the causes of an artifact or a process, they may
> not just be interested in direct causes, but in indirect causes … Hence, **for
> the purpose of expressing queries or expressing inferences about provenance
> graphs**, we introduce four new relationships, which are multi-step versions of
> existing relationships."

Definition 11: "An artifact a₁ was derived from a₂ (possibly using multiple
steps), written as a₁ →* a₂ … **In other words, it is the transitive closure of
the edge 'was derived from'.**" The mechanism: "multi-step edges can be inferred
from single-step edges, by **'eliminating' artifacts that occur in chains of
dependencies**." Figure 12 draws them **dashed**.

**And they did not survive standardisation.** PROV has no transitive-derivation
inference and no counterpart to `→*`. I verified this exhaustively: the complete
list of transitivity inferences in PROV-CONSTRAINTS is **Inference 17
(`alternate-transitive`) and Inference 19 (`specialization-transitive`)**; there
is no `derivation-transitive`; `wasDerivedFrom` is **not** declared
`owl:TransitiveProperty` in the OWL file; and PROV-CONSTRAINTS separately
*denies* transitivity for `wasInformedBy` with a worked counterexample
(**READ**).

**The two reasons it died are exactly TAP's two problems**, and both are legible
in the specifications:

1. **It could not be validated.** OPM's legality rules — no `wasDerivedFrom`
   cycles, at most one `wasGeneratedBy` per artifact, per account view — are
   defined over *single-step* edges. There was no account of what makes a
   *multi-step* edge well-formed.
2. **It could not be identified.** Definition 11 computes the closure "by
   **eliminating** artifacts that occur in chains" — **the witness is destroyed
   by the inference that produces it.** Two different routes from a₁ to a₂ yield
   one indistinguishable multi-step edge.

PROV itself says the same thing about its own imprecise derivations (**READ**,
PROV-CONSTRAINTS):

> "In a derivation of the form `wasDerivedFrom(id; e1,e2,attr)`, the absence of
> the optional activity, generation and use identifiers means that **the
> derivation relationship may encompass multiple activities, generations, and
> uses.** … **if `a` is not provided, then one cannot tell whether one or more
> activities are involved in the derivation** … **The inferences defined in this
> specification do not allow the latter modeling to be inferred from the
> former.**"

**A bare `wasDerivedFrom(e2,e1)` is an unnamed, unidentified, multi-hop summary.
PROV knows it may span many activities and deliberately refuses to let you infer
either the expansion or the collapse.** You may assert the summary edge and the
detail separately, and PROV will treat them as two unrelated statements about the
world.

> **A path object that carries its witness sequence *and* its own identity is
> exactly the thing neither standards body was willing to build.** That is the
> gap TAP is proposing to fill. It is also the warning: both bodies declined for
> *validation* and *identity* reasons, so a design claiming the space has to
> answer both — and then answer a third question neither of them ever faced,
> because neither stored anything: **invalidation.**

### PROV's qualification pattern: reification by design, and its bill

PROV's answer to "how do I say something about a relation" is the **Qualification
Pattern** (**READ**, [PROV-O §3.3](https://www.w3.org/TR/prov-o/#qualified-terms)):

> "The Qualification Pattern **restates an unqualified influence relation by
> using an intermediate class** that represents the influence between two
> resources. This new instance, in turn, can be annotated with additional
> descriptions of the influence that one resource had upon another."

Fourteen relations, each with a qualifier property and an Influence subclass —
**28 extra terms**, plus four influencer properties and three abstract classes.
And critically, the attributes you actually want are *only reachable through the
heavy form*: `prov:hadRole` has domain `prov:Influence`, `prov:hadPlan` has domain
`prov:Association`, `prov:atTime` has domain `prov:InstantaneousEvent` (**READ**,
from the Turtle, not the prose).

**The "optional, use it if you need extras" framing is misleading: needing a role
*forces* the heavy form.**

The cost is a dual representation, and the spec both mandates and laments it
(**READ**, verbatim):

> "As can be seen in this example, qualifying an influence relation provides **a
> second form** … to express an equivalent influence relation … Because the
> qualification form is **more verbose**, the unqualified form should be favored
> in cases where additional properties are not provided. **When the qualified form
> is expressed, including the equivalent unqualified form can facilitate PROV-O
> consumption, and is thus encouraged.**"

The maddening part is that the entailment *exists*: the OWL file contains **13
`owl:propertyChainAxiom` declarations**, OWL 2 RL-computable, so a reasoner
derives the unqualified form for free (**READ**, counted in the Turtle). And
PROV-O Appendix B explains why they told people to write it twice anyway:

> "**We cannot assume that everybody is using OWL reasoning. We do not want
> people to write more code and query than necessary.**"

**PROV chose redundant materialisation at write time over inference at read time,
because it could not control its consumers.** That is a real engineering
decision made by serious people, and it is exactly the decision TAP would face if
it materialised a derived path alongside the asserted edges.

**And the adoption data says it did not pay.** Counting per-term implementation
support directly from Table 2 of the PROV Implementation Report (**READ** +
parsed HTML; these are counts I derived, not figures the report states in prose):

| Term | implementations, of 41 |
| --- | --- |
| Entity / Activity / Agent | 39 / 39 / 38 |
| Generation / Usage | 36 / 37 |
| Association | 30 |
| Derivation | 28 |
| **Bundle** | **16** |
| **Role** | **10** |
| **Influence** | **9** |

**`prov:Role` — the single attribute the entire qualified pattern exists to carry
— is used by 10 of 41 implementations, roughly a quarter of `used`'s uptake.**

Published critique, from the PAV ontology paper (**READ**, Ciccarese et al.,
*J. Biomedical Semantics* 2013, [arXiv:1304.7224](https://arxiv.org/pdf/1304.7224)):
the detailed-chain approach comes "at the cost of **increased verbosity, which we
argue reduces the ability to query the provenance in a consistent way**."

**The contrast with OPM is the cleanest in the dossier.** OPM put role **directly
on the edge** and made it **mandatory** (graph rule 7). PROV made role reachable
only through a minted Influence instance and made it **optional**. **OPM bought
brevity and had nowhere to put anything unanticipated; PROV bought uniformity
and paid the reification tax, and the tax was not paid by its implementers.**

### Bundles and accounts: naming a set, never a path

PROV's **bundle** is "a **named set of provenance descriptions**, and is itself
an entity, so allowing provenance of provenance" (**READ**, PROV-DM §2.2.2). To
give one provenance you re-declare its identifier as an entity. And two
constraints define its shape (**READ**): "**Bundles cannot be nested**" and
"**each bundle is handled independently; there is no interaction between
bundles**."

**A bundle is the closest thing PROV has to a first-class named persistent set of
graph facts, and it is deliberately flat, non-composable and reasoning-isolated.
It names a set, never a path** — nothing constrains its contents to be connected.

The boundary hurt enough to need a patch that never shipped: PROV-LINKS adds
`prov:mentionOf` so a consumer can reference a bundle-contextualised entity
instead of duplicating it, and its own status note says "**The concept Mention is
experimental, and for this reason was not defined in PROV recommendation-track
documents**" (**READ**).

OPM's **accounts** were more expressive and more dangerous: elements are tagged,
views are computed by filter, a node may be in several accounts at once, and
refinement between accounts is assertable and *measurably defined* (in terms of
the multi-step dependencies inferable in each). But unioning two legal account
views "**is not necessarily a legal view since it may contain cycles**"
(**READ**). PROV traded that expressivity for tractable per-bundle validation.

**If TAP's named paths live in scopes, decide up front whether a path may
reference across scopes, or you will ship `prov:mentionOf` too.**

### Supply chain: in-toto's layout/link split is the cleanest structural statement

in-toto enforces the declared/observed distinction with **distinct types,
distinct signers, and distinct verification roles** (**READ**, in-toto v1.0
specification). A **layout** is prospective — expected materials, expected
products, expected command, written *before* the run by the *project owner*,
signed by them, and it **expires**. A **link** is retrospective — actual
materials, products, command, written by the executor, signed per-step per
functionary, never expiring.

Two mechanisms in there are directly stealable.

**Rename-tolerance at the hop boundary.** The `MATCH` rule joins on
`(name after prefix rewriting, hash)` — `MATCH foo IN lib WITH PRODUCT IN
build/lib FROM compilation` makes `lib/foo` match `build/lib/foo` across a step
that relocates files. CycloneDX independently needed the same thing: its
workspace `aliases` field is "a name mapping so other tasks can use their own
local name in their steps" (**READ**, both). **Two independent designs needed a
rename-tolerance mechanism at the hop boundary — take it as settled that a stored
path must survive its participants being renamed between hops.**

**And the fail-open trap, which TAP should invert.** Artifact rules are processed
"**in a similar fashion as firewall rules do**" — first match consumes — and:

> "**There is an implicit `ALLOW *` at the end of each rule list** … it is
> generally recommended that all rule lists include a `DISALLOW *` at the end."

**Closure is opt-in. Unexplained artifacts pass silently.** TAP fails closed
everywhere else; it should fail closed here.

One more finding worth flagging because it is the same lesson twice: when
in-toto generalised away from filesystem paths to arbitrary attestations
(ITE-6), it **lost the ability to verify paths** and has been trying to get it
back ever since. ITE-10, still a *Draft*, states the problem verbatim (**READ**):

> "**in-toto v1.0 layouts and artifact rules cannot be used to verify artifacts
> recorded in ITE-6 attestations.**"

Its proposed fix is a two-class taxonomy — **transformational predicates**
("steps that transform artifacts … They consume some artifacts as materials and
produce others as products") versus **informational predicates** (contextual
attributes that move nothing). **The framework that generalised away from paths
had to reintroduce a distinction between edges-that-move-things and
annotations-that-do-not in order to get path verification back — and it is still
a Draft.** That distinction is precisely TAP's containment-versus-reference
edge classification, discovered independently by a supply-chain security project.

### SLSA: a chain that is explicitly acknowledged never to terminate

SLSA (currently **v1.2**, not v1.0 — the v1.0 URLs are superseded and
`/v1.2/levels` 404s because the spec restructured around tracks; **READ**) models
a **single step**: "Provenance is an attestation that a particular build platform
produced a set of software artifacts through execution of **the**
`buildDefinition`."

The chain is the verifier's job, and the spec is candid about how badly it goes
(**READ**, [verifying artifacts](https://slsa.dev/spec/v1.2/verifying-artifacts)):

> "**Finally, recursively check the `resolvedDependencies` as available and to the
> extent desired.** … If `resolvedDependencies` is incomplete, these checks can be
> done on a best-effort basis."

> "**A trimming heuristic or exception mechanism is almost always necessary when
> verifying dependencies** because there will be transitive dependencies that are
> SLSA Build L0. (For example, consider the compiler's compiler's compiler's …
> compiler.)"

**There is no chain object, no chain identity, no chain persistence — and the
spec's own escape hatch is a "trimming heuristic."** This is the strongest
available argument that the industry has repeatedly declined to make the path
first-class and has paid for it with a documented non-terminating recursion. And
the sharpest consequence: **if the path is not an object, no one can name where
the trim happened.**

**The one place a traversal result does persist is the Verification Summary
Attestation**, and what it persists is instructive: `verifier.id`,
`timeVerified`, `resourceUri`, `policy`, `inputAttestations`, `verificationResult`
(PASSED/FAILED), `verifiedLevels`, `dependencyLevels`. Its stated purpose
(**READ**):

> it enables "software consumers to make a decision about the validity of an
> artifact **without needing to have access to all of the attestations about the
> artifact or all of its transitive dependencies**."

**INFERRED: a VSA is a memoised, timestamped, signed reachability answer with no
re-derivable structure.** `dependencyLevels` is a histogram. You can ask it "did
it pass, as of when, per whom, under which policy" — never "which path."

**That is the shape to beat, and beating it is a one-line product thesis: keep
the verdict caching; retain the traversal so the answer is explicable.**

### SPDX 3.0 quietly did the thing everyone else refused to

This is the most useful and least-known finding in this section.

In SPDX 2.3, a Relationship was a field of a document addressed only by
`(from, type, to)` — 64 relationship types, no identity. **In SPDX 3.0, the
Relationship class is declared `SubclassOf: Element`** (**READ**,
[Relationship](https://spdx.github.io/spdx-spec/v3.0.1/model/Core/Classes/Relationship/)),
with properties `from` (1..1), **`to` (1..*)**, `relationshipType` (1..1),
**`completeness`** (0..1), **`startTime`** (0..1), **`endTime`** (0..1).

Because Relationship *is* an Element, it inherits `spdxId`. **INFERRED, and
load-bearing: in SPDX 3.0 an edge is persistent, named, addressable, and can
itself be the `from` or `to` of another relationship.** That is edge reification
— and unlike PROV's, it creates *no parallel unqualified form to keep in sync*.

Note also that `to` is 1..*, so **an SPDX relationship is a hyperedge, not a
binary edge**; and that it carries the two things a persisted edge most needs and
almost nobody provides: **`completeness`** (the "is this the whole story" flag
in-toto lacks and SLSA answers with a footnote) and **`startTime`/`endTime`** (a
per-edge validity interval, against in-toto's single wall-clock `expires` on an
entire layout).

**A path is still not first-class in SPDX. But SPDX 3.0 has already paid the
modelling cost that makes one expressible**, and its Build profile — `buildId`,
`buildType`, `buildStartTime`/`EndTime`, `configSourceUri`/`Digest`/`Entrypoint`,
`environment`, `parameter`, with required `hasInput`/`hasOutput`/`invokedBy`
relations — is SLSA's `buildDefinition` restated as graph vertices and addressable
edges rather than nested JSON.

**The difference between SPDX 3.0 and SLSA is purely representational, and it is
exactly the difference this dossier is about: SLSA nests the step inside a
document keyed by its outputs; SPDX makes the step a vertex and the input/output
relations addressable edges.**

CycloneDX (currently **1.7**, October 2025, ECMA-424 2nd Edition — **READ**, and
the version history established by diffing the raw JSON schemas) contributes two
things. First, its `formulation`/`workflow`/`task`/`step` hierarchy is the
pipeline *shape* as an addressable object — except that **`step` is the only
level with no `bom-ref`**, so the finest-grained unit of a pipeline cannot be
referenced, annotated or diffed. Second, and better, its dependency-graph rule is
TAP's own `null`-versus-`""` convention arrived at independently (**READ**,
verbatim):

> "**Components or services that do not have their own dependencies MUST be
> declared as empty elements within the graph. Components or services that are
> not represented in the dependency graph may have unknown dependencies. It is
> recommended that implementations assume this to be opaque and not an indicator
> of an object being dependency-free.**"

**Absent ≠ empty, stated in a schema.** That is external confirmation of a
decision TAP already made.

And a cautionary contrast: CycloneDX 1.7's prose says processes "are modeled
using **declared and observed formulas**" — but grepping the entire 1.7 schema
for "declared" and "observed" finds them only in descriptions (**READ**,
measured). **There is no enum, flag or field on `formula` saying which kind it
is.** in-toto gives the two kinds different file types, different signers and
different verification roles; CycloneDX names the distinction in prose and
**omits it from the schema**. Guess which one a consumer can rely on.

### Tracing: the most emphatically ephemeral tradition, and it scaled

OpenTelemetry's overview says it outright (**READ**): "**Traces in OpenTelemetry
are defined implicitly by their Spans**," and a trace "can be thought of as a
**directed acyclic graph (DAG) of Spans**." The wire format settles it: **there
is no `Trace` message in `trace.proto`** — the hierarchy is
`TracesData → ResourceSpans → ScopeSpans → Span`, and the outer two are transport
grouping, not trace objects.

A **Span Link** is close to an edge-about-an-edge and worth noting for §II.3: its
protobuf comment reads "**A pointer from the current span to another span in the
same trace or in a different trace**," it carries attributes, and order is
preserved. But it has **no id of its own**, it is not independently queryable,
and it is stored *inside one endpoint*, so you find it only by already holding
the source span.

The staleness statement is the best quote in this section, from Grafana Tempo's
architecture documentation (**READ**):

> "**There's no concept of the 'end' of a trace.** A trace can start with any span
> which holds a unique trace ID that hasn't been seen by Tempo previously.
> However, **spans can be continually added at any point in the future.**"

**INFERRED, and it is the tracing tradition's whole lesson: a trace is a
late-bound, possibly-never-complete, retention-limited join over immutable
fragments. Nobody can tell you a trace is finished; nobody can tell you it is
correct; nobody can name it other than by its join key. Tracing scaled to
enormous volume precisely by refusing to materialise the path — and the price is
that you can never assert anything about a trace as a whole.**

TAP has already ruled on this once, in `docs/misc/trace-overlay-on-system-model-seam.md`
— "Grid holds the map, Jaeger holds the journeys" — and the ruling holds up
against the evidence. Spans belong where they are, and the join is a view.

### Git: the two-layer identity model, and the only path that cannot go stale

A commit chain is a persistent path, and **the path is baked into the identity**.
A commit object's content includes its parent lines, so its SHA is a function of
its entire ancestry; change any ancestor and every descendant's name changes
(**READ**, [Git Internals — Git Objects](https://git-scm.com/book/en/v2/Git-Internals-Git-Objects)).

Above that sits a **mutable, human-named pointer layer that is deliberately not
part of the hash**: refs are "simple names that store SHA-1 values," a branch is
"a simple pointer or reference to the head of a line of work," a lightweight tag
is "simply a reference that never moves," and an **annotated tag** is the
interesting case — "Git creates a tag object and then writes a reference to point
to it rather than directly to the commit," with its own SHA, tagger, date and
message (**READ**).

**This is the cleanest two-layer identity model in the entire dossier: an
immutable, content-addressed, history-carrying object layer, plus a mutable,
human-named pointer layer outside the hash.** A branch going stale is not
corruption; it is the pointer layer doing its job. And an annotated tag is the
proof that **a name can be promoted into a first-class object with its own
identity and metadata when it needs to carry more than a pointer** — which is
precisely what a TAP path node would be.

Path *queries* remain computed: `git log --ancestry-path` is a filter over the
DAG evaluated per invocation, and nothing is persisted (**READ**).

And the general Merkle-DAG statement (**READ**,
[IPFS Merkle DAG](https://docs.ipfs.tech/concepts/merkle-dag/)): node identity is
"the result of hashing the node's contents — any opaque payload carried by the
node **and the list of identifiers of its children**"; nodes are immutable; "Any
change in a node would alter its identifier and thus **affect all the ascendants
in the DAG, essentially creating a different DAG**."

**INFERRED: content addressing is the one mechanism in the prior art where a path
*cannot* go stale, because the path is not stored alongside the node — it *is*
the node's name.** The cost is equally sharp: you cannot edit history, only
rewrite it into a new history, and every consumer holding the old name now holds
a different object. TAP cannot pay that price — the grid is edited constantly —
but the *shape* is worth keeping in view, because it is the limiting case that
shows what perfect freshness costs.

Git also has both layers of the declared/observed split, arrived at for
operational rather than security reasons: the commit DAG is the durable
structure, and the **reflog** is a retrospective, local-only, *expiring* log of
how the named pointers actually moved — 90 days reachable, 30 days unreachable
(**READ**). Same shape as in-toto's layout-versus-link. Nobody coordinated.

### The constraint test applied to provenance

**What forced the negative?** Two constraints, and TAP's position on each is
different.

1. **You cannot validate a path.** OPM's legality rules were defined over
   single-step edges and there was no account of multi-step well-formedness.
   **Does TAP inherit it? Partly — and TAP has a better answer available than OPM
   had.** BioPAX's adjacency rule (consecutive steps must share a participant)
   and workflow-net soundness (no unreachable step) are both cheap, static,
   fail-closed validations that OPM simply never wrote down. TAP already runs
   exactly this class of check — `req-grid-service-delete-cascade-17` validates
   that every declared edge type resolves, at boot and in plugin CI. **Path
   validation is a solved problem that OPM did not solve.**
2. **You cannot identify a path.** The witness is destroyed by the inference that
   produces it. **Does TAP inherit it? Yes, for a computed path, exactly as §II.4
   found.** And the escape is the same escape: WINGS' template, in-toto's layout,
   git's annotated tag, ProvONE's `prov:Plan`. **Identity comes from the
   declaration, not from the computation.** Four traditions in this section alone.

And a third that this section adds, which neither of the others faced: **nobody
here stored anything, so nobody here had to solve invalidation.** SLSA's
`timeVerified` is the closest gesture, and it works by throwing the path away.
**That problem is genuinely TAP's own, and §II.7's answer — watch a version
counter, do not re-walk the path — is the only cheap one this dossier found.**

## II.6 Biological pathways: thirty years of doing this on purpose

*Section method: KEGG, Reactome, BioPAX, SBML, SBGN, MSigDB, Pathway Commons,
Gene Ontology and WikiPathways documentation and specifications fetched and read
(**READ**), including several specification PDFs converted locally and one live
SPARQL query against the WikiPathways endpoint (**RAN**). Negative findings were
established by grep over complete fetched spec texts and are labelled as such.
Items behind paywalls or dead sites are flagged **UNVERIFIED** inline.*

I came into this section expecting a pleasant analogy and came out of it
thinking it is the most directly applicable body of prior art in the entire
dossier. This community has been running TAP's proposed experiment — *persistent,
named, curated, versioned, identified paths over a graph that keeps moving* — in
public, at scale, since 1995. They have made every mistake available. Several of
them have published post-mortems. And two of their solutions are close enough to
finished that TAP could implement them next week.

There is also a genuinely unsettling finding in here, and it is not the one
about curation cost. It is about whether the ordering is worth anything at all.

### Finding 1: the template/instance split, invented three times independently

This is the headline, and the convergence is what makes it persuasive.

**KEGG** keeps one five-digit number and changes the namespace prefix
(**READ**, [KEGG PATHWAY](https://www.genome.jp/kegg/pathway.html),
[KEGG overview](https://www.genome.jp/kegg/kegg1b.html)):

| Identifier | What it is |
| --- | --- |
| `map00010` | the **reference map** — manually drawn, no organism, uncoloured |
| `ko00010` / `ec00010` / `rn00010` | reference, highlighting orthologs / EC numbers / reactions |
| `hsa00010` | the **human instance**, rendered green |

And the instantiation is a *function*, not a curation act:

> organism-specific pathways are generated "by the **set operation** between
> manually created pathway maps (called reference pathway maps) and an annotated
> set of genes in the genome, annotated with KO (KEGG Orthology) identifiers"

For roughly 6,000 organisms. Mechanically, in KGML, the reference carries
`entry type="ortholog"` with `name="ko:K00844"` and the organism instance carries
`entry type="gene"` with `name="hsa:3098"`. **The template is the topology; the
instance is the binding.**

**Reactome** does the same thing with a species code in the same position:
`R-HSA-70171` is human Glycolysis, `R-BTA-70171` is bovine Glycolysis, and I
verified on live pages that the *number is identical* (**READ**). Reactome's own
FAQ states the rule: for computationally inferred events "the species code is
that of the model organism species and **the DB identifier is the one assigned to
the human event that is the basis of the inference**." The inference runs off
PANTHER phylogenetic trees, requires every input, output and catalyst to have a
mapped orthologue, and for complexes requires **≥75% of accessioned protein
components** to map.

**WikiPathways** does it a third way, with a suffix and a separate repository:
866 of 1,913 human pathways generate **22,790 species variants** stored as
`pathways/Mm/WP107/WP107_Mm.gpml` (**READ**,
[wikipathways-homology](https://github.com/wikipathways/wikipathways-homology)).
Provenance is *in the identifier*; you recover the parent by string surgery; and
machine-generated content can never be confused with curated content because
they live in different repositories.

**Three independent 25-year projects, different data models, different funding,
all arrived at: keep the number, change the namespace, mark the instance as
derived, point back at the template, and carry zero curation burden on
instances.** That is not a coincidence, it is a discovered constraint, and it is
the single most transferable idea in this movement.

**And it has a documented failure mode worth stealing the scar from.** When
Bioconductor's `reactome.db` adopted the shared-number scheme, "Bos taurus:
Interleukin-6 signaling" and "Homo sapiens: Interleukin-6 signaling" both mapped
to `1059683`, breaking the identifier-to-name bijection and taking downstream
packages with it. The fix was to adopt the full `R-{species}-{number}` form, and
the maintainer **declined to publish an old-to-new mapping table**, calling it
"stale data" (**READ**,
[Bioconductor support #95022](https://support.bioconductor.org/p/95022/)).

**The rule that falls out: the namespace must be an inseparable part of the
identifier, and a renumbering without a published migration table is a defect.**

### Finding 2: membership and ordering are two different properties, and ordering is the optional one

Every mature system in this space separates them, and the one that states the
rule most clearly is BioPAX. From the Level 3 specification (**READ**, PDF
fetched and text-extracted), on `pathwayOrder`:

> "**If this property is used, it is still necessary to specify pathway
> components in the pathwayComponent property (even though all pathway components
> would also be listed in the set of pathwayOrder properties).** A PathwayStep
> should not be listed in the nextStep property of another PathwayStep **if the
> intersection of the entities in the participant properties of their
> interactions is empty.** […] **Holes in the pathway are allowed**, for instance
> if intermediate steps are not known. **The nextStep property is meant only to
> represent pathway topology, not order of events.**"

Five rulings in one paragraph, and all five transfer:

1. **Order does not replace membership; both are required.** Deliberately
   redundant, because they answer different questions and a consumer must not be
   forced to compute one from the other.
2. **Ordering exists to handle branches, cycles, and context-dependent
   direction** — precisely the cases where a plain edge set is ambiguous. If your
   graph has none of those, you do not need an ordering layer at all.
3. **Adjacency has a validation rule**: consecutive steps must share a
   participant. That is a cheap, fail-closed lint for "this path has drifted
   apart," and TAP's analogue — consecutive hops must share an endpoint — costs
   almost nothing.
4. **Holes are legal.** A path may be declared before it is fully known. TAP will
   want this the first time somebody names a deploy path with a gap in the middle.
5. **The ordering is topology, not chronology** — stated defensively, in the
   spec, to head off a decade of misuse.

Reactome separates them too, but differently, and the difference is a genuine
fork TAP must choose between (§II.6, Finding 7 below). Its properties (**READ**,
[Pathway](https://reactome.org/content/schema/Pathway),
[Event](https://reactome.org/content/schema/Event)):

| Concern | Property | Lives on | Cardinality |
| --- | --- | --- | --- |
| Membership, downward | `hasEvent` → Event | **Pathway** | `+` |
| Membership, upward | `eventOf` → Pathway | **Event** | `+` |
| Ordering | `precedingEvent` / `followingEvent` | **Event** | `+` |
| Negative ordering | `negativePrecedingEvent` | **Event** | `+` |

`eventOf` being `+` means **membership is many-to-many**: the data model text
says outright that "an event may be a member of more than one Pathway." **A path
is an overlay, not a partition.** That is exactly the shape TAP needs and it is
worth noting that Reactome has no step object at all — it gets by with a
membership relation plus a global precedence relation.

### Finding 3: the dedicated path-step node exists, and it is mostly unused

This is the design George is weighing — "is there a dedicated path-step node
between the path and the participant?" — and biology has run it.

BioPAX's `PathwayStep` carries `stepProcess` (0..n → Pathway or Interaction),
`nextStep` (0..n → PathwayStep), `evidence`, and `comment`. Its subclass
`BiochemicalPathwayStep` adds `stepConversion` and — the whole reason it exists —
`stepDirection` ∈ {REVERSIBLE, RIGHT-TO-LEFT, LEFT-TO-RIGHT}, documented as
"Direction of the conversion **in this particular pathway context**" (**READ**).

**That is the argument for a step node, and it is a good one.** The same reaction
runs left-to-right in gluconeogenesis and right-to-left in glycolysis. A step
node is the place to put *what this edge means when traversed as part of P*.

Now the three warnings, and they are severe.

**Warning one: it was demoted, and the spec says why.** From "Major changes from
BioPAX Level 2" (**READ**, verbatim):

> "**The PathwayStep class has been moved to a new property in pathway to make
> pathways easier to create (you only need to create pathway step instances if
> you want to order parts of the pathway.)**"

In Level 2, ordering was structurally mandatory. In Level 3 it became optional.
**The authoring cost of a mandatory step layer was judged, by the people who
designed it, to exceed its value for most content.**

**Warning two: optional meant unpopulated, and unpopulated meant useless.** From
the 2024 review (**READ**,
[PMC11585474](https://pmc.ncbi.nlm.nih.gov/articles/PMC11585474/)): Reactome uses
`PathwayStep` systematically, but "**other pathway databases make little or no
use of the PathwayStep class, but represent a pathway as an independent unit of
information**," and this inconsistency "complicates standard pathway traversal
algorithms."

**INFERRED, tightly, and it is a rule I would put in the spec: an ordering layer
that is optional will be unpopulated, and an unpopulated ordering layer is worse
than none, because every consumer must write both code paths and can rely on
neither.**

**Warning three, and this is the sharpest single warning in the dossier for
TAP's specific decision.** `PathwayStep` is a `UtilityClass`, not an `Entity`,
and the spec explains the consequence (**READ**, verbatim):

> "Utility classes store structured bits of information **in the context of the
> main ontology classes**. As such, they are **not guaranteed to make sense out of
> the context of the classes they are used in.** […] consider a
> BiochemicalPathwayStep instance that was used by multiple pathways. **If new
> information became available for one of those pathways, addition of this
> additional information to the BiochemicalPathwayStep instance could invalidate
> it for all of the other pathways that refer to it.** Due to these potential
> problems, **it should not be assumed that utility class instances will be
> re-used** in a BioPAX file."

**A path-step node is contextual by nature. If you make it a shareable,
addressable, identity-bearing node, you create an aliasing hazard: two paths
pointing at one step, and one path's curation silently corrupting the other.**
BioPAX's answer was to make steps deliberately non-identity-bearing and
non-reusable — owned and duplicated, rather than shared and compact — and to say
so in the specification.

That is a direct answer to open question #4 from Movement I, and the answer is:
**if TAP builds step nodes, each step belongs to exactly one path.** Duplication
is the price of not having an aliasing bug.

**One more thing to steal from both systems**, because it makes nesting free:
BioPAX's `pathwayComponent` ranges over `Interaction` **or** `Pathway`, and
Reactome's `hasEvent` ranges over `Event`, which is the supertype of `Pathway`
and `ReactionLikeEvent`. **Make the path's member type the supertype of
{path, step}, and hierarchy costs you nothing.** TAP is already there: a path
node would be an `Entity`, and so is everything else.

### Finding 4: the identity-and-drift problem has a finished answer, and it is Reactome's

Movement I's question 7 — how do paths interact with history, tombstones and
removals — has a worked answer sitting in a public schema.

Reactome has a class called **`Deleted`**, and there are **7,832 instances of it
in the live database** (**READ**,
[Deleted](https://reactome.org/content/schema/Deleted)). Its attributes:
`deletedInstanceDbId`, `deletedInstance`, **`replacementInstances` (cardinality
`+`)**, **`reason` (a controlled vocabulary)**, `curatorComment`, `created`,
`modified`.

The seven reasons, verbatim (**READ**,
[DeletedControlledVocabulary](https://reactome.org/content/schema/objects/DeletedControlledVocabulary)):

1. `Duplicate`
2. `Merged`
3. `Split`
4. `Obsoleted`
5. `Killed not replaced`
6. `Literature_retracted`
7. `never_released_not_needed`

**Read that list against the question "what happens when a path is split,
merged, renamed or deleted?"** The answer is: it is recorded as a typed event
with a controlled reason, a curator's prose explanation, and zero or more
replacement instances, and the record is permanent and queryable.

Note the distinctions a naive design would collapse:

- **`Merged` versus `Duplicate`** — were these two names for one thing, or two
  things that became one thing? Different questions, different consequences.
- **`Split`** — one deleted instance, *multiple* `replacementInstances`. The
  cardinality is already `+`, so fan-out is native.
- **`Killed not replaced`** — an affirmative "there is no successor,"
  distinguishable from "we have not said." That is TAP's `null` versus `""`
  convention applied to succession.
- **`Literature_retracted`** — the *reason the world changed*, not merely that it
  changed. Provenance failure is its own category.
- **`never_released_not_needed`** — a draft that never became public, so nothing
  downstream can break. WikiPathways reached the same insight independently by
  returning unpublished identifiers to the pool: **an identifier that was never
  dereferenceable has no obligations.**

Reactome also keeps a *separate* release-scoped audit class, `UpdateTracker`
(`action`, `release`, `updatedInstance`), with **62,304 instances** (**READ**).
So there are two mechanisms doing two jobs: **the version counter says
*that* something changed; UpdateTracker says *what*.**

And the version counter itself is worth understanding precisely, because it is
computed rather than asserted (**READ**,
[release-update-stable-ids](https://github.com/reactome/release-update-stable-ids)):

> "This program evaluates if an instance has changed by looking at the number of
> `modifications` the instance has in the current and previous release. If the
> current instance has more modifications, the `identifierVersion` of the
> stableIdentifier will be incremented."

**The version bump is derived by diffing two release databases.** No curator
decides it.

**And the two-tier identifier is the detail TAP most needs.** The stable
identifier's full form is `R-HSA-70171.3`, but the public page renders
`R-HSA-70171` with no suffix (**READ**, verified on the live page).
**INFERRED**: the version suffix is a data-layer artefact for change detection,
and the resolvable, citable, cross-referenced identity is the bare stem. *Version
for diffing, stem for linking.* Both are issued. Neither has to do the other's
job.

**Gene Ontology supplies the complementary half**, and its two-value enum is the
cheapest high-value primitive in the whole dossier (**READ**,
[obsoleting a term](https://go-ontology.readthedocs.io/en/latest/ObsoleteTerm.html),
[OBO format](https://owlcollab.github.io/oboformat/doc/GO.format.obo-1_4.html)):

- **`replaced_by`** — "The value of this tag can safely be used to
  **automatically reassign** instances whose `instance_of` property points to an
  obsolete term."
- **`consider`** — "Gives a term which may be an appropriate substitute for an
  obsolete term, but **needs to be looked at carefully by a human expert** before
  the replacement is done."

**The confidence of the successor link is typed, in the schema, with an
operational meaning: one tag a machine may follow, one it may not.** That is two
enum values doing an enormous amount of work, and it is exactly what TAP will
need the first time a path's underlying edge type is renamed.

GO's obsoletion ritual is worth copying wholesale: set `owl:deprecated`, prepend
"obsolete" to the label, prepend "OBSOLETE." to the definition, add a comment
giving the rationale, sever all relations — **and keep the term, resolvable,
forever.** On a merge, the loser's identifier becomes an `alt_id` on the winner
and the loser's label survives as a synonym, so a twelve-year-old citation still
resolves to the right concept. And before obsoleting anything with dependents,
GO mandates a **7-day comment period**.

**None of that is expensive. All of it is missing from most systems.**

### Finding 5: the uncomfortable one — the ordering may not be worth anything

George's brief asked whether the value of a persistent named pathway is "as a
NAMED SET with provenance, not as an ordered walk," and asked for sources
supporting *or contradicting* it. The answer is: **substantially confirmed, with
one correction, and the confirmation is measured rather than asserted.**

The correction first: biological pathways are **not** natively sets. KGML,
Reactome and BioPAX all carry directed, signed edges. The claim that survives is
narrower and more interesting: **the dominant consumption format deliberately
throws the graph away, and when the graph is retained and used, it has been
repeatedly measured to add little.**

**The dominant consumption format throws the graph away.** GSEA's foundational
paper defines a gene set as "*An a priori defined set of genes S (e.g., genes
encoding products in a **metabolic pathway**, located in the same **cytogenetic
band**, or sharing the same **GO category**)*" (**READ**,
[PMC1239896](https://pmc.ncbi.nlm.nih.gov/articles/PMC1239896/)). **Note the
equivalence class: a pathway, a chromosome band and an ontology term are
interchangeable inputs to the same type.** The only operation applied to S is
membership testing.

And the single best artefact in this section (**READ**,
[MSigDB KEGG_DNA_REPLICATION](https://www.gsea-msigdb.org/gsea/msigdb/human/geneset/KEGG_DNA_REPLICATION.html)):
KEGG's `hsa03030`, a genuine directed reaction graph upstream, is published as a
systematic accession `M16853`, an "Exact source: hsa03030" provenance line, and
**an unordered table of 36 genes**. No edges. No order. And this is the form that
gets used millions of times a year.

**And when the graph is used, measurement went against it.** Topology-based
methods genuinely consume the edges — SPIA propagates a perturbation factor over
KEGG's signed directed edges (**READ**,
[Bioinformatics 2009](https://academic.oup.com/bioinformatics/article/25/1/75/302846)).
But a seven-method comparison found (**READ**,
[PLOS ONE 2018](https://pmc.ncbi.nlm.nih.gov/articles/PMC5784953/)):

> "*In TopologyGSA and Clipper, **no difference between the topological and
> non-topological variant of the method was found**… these methods do not appear
> to fit the definition of topology-based methods.*"
>
> "*the number of differentially expressed genes usually **surpassed their
> topological influence**. None of the methods showed a preference for a
> particular differentially expressed topological motif.*"
>
> "*Large pathways achieved lower median p-values in comparison to small
> pathways, independently on the dataset sample size.*"

Corroborated by a ~70-method review (**READ**,
[Briefings in Bioinformatics 2022](https://academic.oup.com/bib/article/23/3/bbac143/6572658)):
"*the removal of topological information yields no differences in results, for
other methods, it can improve results*," and "*pathway size can have a stronger
effect than the statistical corrections used.*"

**Two of the seven methods stored the graph and produced identical answers with
it removed.** That is as clean a negative result as this literature offers.

**And it hands TAP a test it can run on itself, which I would urge as an
acceptance criterion rather than a curiosity:**

> **Randomise the ordering of every persistent path and see whether any answer
> changes. If nothing changes, the ordering is decoration.**

It also hands over a warning about size: **a big path always looks important**,
for the same reason a big gene set always wins on p-value. If TAP ever ranks
paths by anything, the size term will dominate unless it is explicitly
controlled for.

### Finding 6: SBML models a network and has no path object at all

Worth stating because it is a clean negative and because the *reason* is
instructive. SBML's `Model` holds ten containers and the specification says of
them: the `ListOf` classes "**are merely containers used for organizing** the
main components of an SBML document," with three stated motivations — annotation
attachment, package modularity, human readability. **None is sequence** (**READ**,
L3V2 Core).

The nearest construct is the `groups` package, and three findings settle it
(**READ**, the Groups V1R1 specification in full):

1. **No ordering anywhere** — a grep of the complete spec text for "order"
   returned only English idiom and validation boilerplate (**READ**, negative
   evidence over full text).
2. **Duplicates collapse**, verbatim: "If the same element is referenced by
   multiple `Member` objects, **this is equivalent to including it just once.**"
   **A Group is a mathematical set. A walk that revisits a node — a loop, a
   backtrack, an A→B→A — is unrepresentable, and the document remains valid while
   meaning something else.** Silent semantic loss.
3. **No semantics**: "There are **no predefined behavioral semantics** associated
   with groups"; "the use of Groups constructs **has no impact on the mathematics
   of a model**."

And the word "pathway" does not appear anywhere in the Groups specification
(**READ**, grep, zero hits).

**What SBML does instead is the finding.** It outsources pathway identity to
someone else's database, via MIRIAM RDF annotation. Its own worked example
annotates a model with `bqmodel:is → biomodels.db/BIOMD0000000003` and
**`bqbiol:isVersionOf` → `wikipathways/WP179` and `reactome/REACT_152`**
(**READ**, Core §6). *SBML's answer to "which pathway is this?" is an external
URI under the relation `isVersionOf`.*

The qualifier vocabulary itself is worth stealing, because it contains exactly
the relations TAP needs names for: **`isVersionOf` / `hasVersion`** and
**`isInstanceOf` / `hasInstance`** — the template/instance and drift relations,
already named by a standards body.

SBGN, the visualisation standard, likewise has no path object; its only
named-subgraph primitive is `submap`, "used to **encapsulate a map**… The submap
**hides the content** of this map… and displays only submap terminals"
(**READ**). And it contains a bitter coincidence of vocabulary that TAP should
learn from now rather than later: **the only "path" in SBGN-ML is a Bezier
polyline** (`arc/next` is "the next point in the **arc's path**"). *Pick the
nouns before the collision, not after.*

### Finding 7: the open question this section puts on TAP's desk

Reactome and BioPAX disagree about one thing, they disagree cleanly, and TAP
must pick.

- **Reactome: ordering is a property of the world.** `precedingEvent` lives on
  the Event, is global, and is the same regardless of which pathway you are
  viewing.
- **BioPAX: ordering is a property of the named path.** `pathwayOrder` lives on
  the Pathway, `nextStep` connects steps within it, and `stepDirection` exists
  precisely to say "this edge runs the other way when you traverse it as part of
  *this* path."

Reactome's is cheaper and has no aliasing hazard. BioPAX's is more expressive
and comes with a warning from its own authors about shared step instances.

**The test is simple: will two of TAP's paths ever disagree with each other about
the direction or meaning of a shared edge?** If yes, TAP needs BioPAX's model and
must own the step-ownership question up front. If no, Reactome's two-relation
model — `hasEvent`/`eventOf` for membership, `precedingEvent`/`followingEvent`
for order — is a complete, proven design that could be implemented this week.

**My reading is that TAP's answer is yes, eventually, and no, not in v0.** The
July containment note already contains the seed of the disagreement: containment
is normalised parent→child and "what contains X" is the same walk *reversed*.
That is a direction that differs by path. But it differs *by convention*, not by
assertion, and a convention needs no step node.

### Finding 8: integration, and the gap that is precisely TAP's problem

Pathway Commons integrates **22 databases** into **4,794 human pathways** and
~2.3 million interactions (**READ**,
[NAR 2019](https://academic.oup.com/nar/article/48/D1/D489/5606621)). Its
identity mechanism is the best in this section and TAP should copy it outright.

Identity is **computed, not asserted**. A Normalizer rewrites URIs into
Identifiers.org form — "if a ProteinReference has a UnificationXref, db='UniProt',
id='P62158', then the new absolute URI… will be `urn:miriam:uniprot:P62158`" —
with a declared fallback for un-normalizable objects,
`urn:biopax:{xrefClassName}#{db}_{id}_{idVersion}` (**READ**,
[cPath2 pre-merge](https://github.com/PathwayCommons/cpath2/wiki/cPath2PreMerge)).

**Two records from two sources are the same entity iff they normalise to the same
URI, where normalisation is a published deterministic function keyed on an
external registry. Merging becomes a *consequence* of normalisation, not a
separate fuzzy-matching stage. And failure produces a stable local URI rather
than a guess or a drop.**

Also worth stealing: Pathway Commons ships **a named ladder of lossy projections
from one canonical store** — full BioPAX (mechanism, n-ary, stateful) → extended
SIF (14 typed binary edge kinds, named so "reading the text output of the
interaction makes sense like a sentence," e.g. `MDM2 controls-state-change-of
TP53`) → GMT (pure membership). **Do not choose between a rich model and simple
edges. Publish a named ladder, define each rung as a rule, and state the loss.**

And OmniPath, integrating 100+ resources, makes provenance *queryable*: every
record carries **`curation_effort`** (count of unique resource–reference pairs)
and a **`consensus_score`** (how many independent sources made the same
assertion), and users can filter by licence via a web-service parameter
(**READ**, [omnipathdb.org](https://omnipathdb.org/)). **That is the model for
path membership provenance: how many independent collectors asserted this hop,
and how much curation went into it.**

**Now the gap, and it is TAP's gap exactly.** Pathway Commons solved *entity*
identity by outsourcing it to external registries. **Pathways have no external
canonical registry to outsource to.** Their identity is provider-scoped, and no
cross-release identity guarantee for them was found (**UNVERIFIED** — not stated
anywhere reachable, which is itself the finding).

> **Pathway Commons solved entity identity and left path identity undefined. A
> path has no registry to borrow from. You must define its identity function
> yourself, and decide up front what change makes it a different path.**

That sentence is the same conclusion §II.4 reached from the attack-path
direction, arrived at independently, in a completely different field. **Two
traditions, two decades apart, both reduce to: the hard part is not storing the
path, it is saying what makes it the same path tomorrow.**

### Finding 9: what curation actually cost, and the two sustainability failures

The brief asked what makes the curation trade right for biology and whether TAP's
data is more or less volatile. Two cautionary tales answer it, and they fail in
opposite directions.

**KEGG froze a canonical corpus for twelve years with a licensing decision.**
KEGG is "an original database product, copyright **Kanehisa Laboratories**";
non-academic use requires a commercial licence; in July 2011 the academic FTP
site became subscriber-only. The plea page states: "**Public funding accounts for
only about one tenth of our total operational cost**" (**READ**,
[legal](https://www.kegg.jp/kegg/legal.html),
[plea](https://www.genome.jp/kegg/docs/plea.html)).

The downstream consequence is measurable in a third party's product. MSigDB's
gene sets carry, verbatim: "**The content of the gene sets in the KEGG_LEGACY
collection has not been updated since KEGG restricted their usage terms in
2011**" (**READ**). The replacement collection arrived in **2023**.

**The lesson is not "don't charge."** KEGG is still alive and still curating,
which some free competitors are not. **The lesson is that the browse/download
split kills federation.** KEGG gives away the page and charges for the bulk data
— and bulk data is exactly what makes identifiers durable, because durability
comes from hundreds of downstream tools hard-coding them.

**WikiPathways lost revision addressability in a migration, having promised it in
print.** The 2016 paper states: "**For every edit, a version of the pathway is
stored indefinitely as a uniquely citable reference.**" The 2024 paper states:
"**A major difference from the previous mediawiki-based page is that it is no
longer possible to directly link to a specific version of the pathway using the
revision number.**" (**READ**, both.)

What replaced it: to cite a specific version you are instructed to download the
pathway as a PNG, log into Zenodo, upload it, and publish for a DOI (**READ**,
[cite.html](https://www.wikipathways.org/cite.html)).

> **The canonical mechanism for citing a version of a curated knowledge object is
> now "the reader screenshots it and self-archives the picture."**

And the revision handle *still exists in the data* — GPML carries
`Version="WP554_r139872"`, `info.json` carries `revision: r139872` — but no
resolver does. They migrated onto the best version-control system in the world
and did not wire its history to their identity scheme.

**I also ran a live query against the WikiPathways SPARQL endpoint (**RAN**,
https://sparql.wikipathways.org/sparql) and the result is the sharpest technical
warning in this section:**

```
Pathway IRI:   https://identifiers.org/wikipathways/WP1062_r120933
DataNode IRI:  http://rdf.wikipathways.org/Pathway/WP1264_r141993/Complex/a61f9
Membership:    ?datanode dcterms:isPartOf ?pathway
```

**Every URI is revision-scoped, at every level.** Every edit invalidates every
URI in the pathway. A saved query, a stored triple, or an external annotation
pointing at `…/WP1264_r141993/DataNode/a61f9` breaks the instant somebody fixes a
typo. It is *technically correct* — each revision genuinely is a different graph
— and *practically unusable as a link target*. Compare, in the same dataset,
`https://identifiers.org/kegg.pathway/map04210`: **no revision component.**

**The rule: issue both a version-pinned identifier and a floating one.** Reactome
does exactly this. WikiPathways issues only the pinned form in RDF and only the
floating form on the web, and the two never meet.

**And on whether the crowd curates.** The contribution statistics across five
papers (**READ**) are worth reading for their *shape* rather than their totals:
208 individual contributors in 12 months (2016) → 201 across three years (2024);
~10,079 edits per three years → ~10,873. **After sixteen years, annual active
editors ≈ 200 and flat.** Lifetime: 906 individuals, 46,923 edits — and one
pathway alone has 445 revisions from 14 curators, so the distribution is
certainly a power law. Governance was added in every single release and removed
in none. And the stated purpose of the entire 2024 platform migration was to free
the team "to focus more on human-centered activities such as biocuration."

**INFERRED, and stated as my reading rather than theirs: the crowd never became
self-sustaining, a small professional core does most of the work, and the
winning structural move was not open editing but *communities* — domain-scoped
groups with their own portals, adopted from 2021 onward.**

### The constraint test applied to biology

**What forced these systems to persist paths at all?** A constraint TAP does not
share and should be honest about: **in biology the path is the object of study.**
A metabolic pathway is not a route *through* the data; it is the thing the
science is about, it has a name in the literature, it predates the database by
decades, and it is cited in papers. Persistence was never optional.

**Does TAP inherit it?** **Partly, and the part it inherits is the part that
matters.** TAP's paths are not scientific objects, but the motivating cases from
the June notes — an ownership chain, a deploy flow, a compliance argument, a
containment closure — are all things that *exist in the organisation
independently of the grid*, have names people already use, and are cited in
documents. They are closer to KEGG's `map00010` than to a shortest-path query
result. **And that is the strongest single argument for persistence in the whole
dossier: the reason biology stores pathways is that the pathway is a thing in the
world, not an artefact of a query — and several of TAP's named paths are the
same.**

**What is TAP's volatility relative to biology's?** Higher, and this is the
uncomfortable half. A metabolic network changes on the timescale of scientific
consensus — years. An AWS account's containment graph changes on the timescale of
a Terraform apply — minutes. Reactome can afford quarterly releases, human
review, and a six-month confidence decay because the underlying reality holds
still. **TAP cannot, and every mechanism borrowed from this section has to be
re-costed against a graph that moves thousands of times faster.**

**Which is exactly why the two mechanisms worth borrowing are the two that are
automatic rather than curatorial**: Reactome's *computed* version bump (derived
by diffing releases, no human involved) and its *automatic* confidence decay
(unreviewed content drops from five stars to three after six months, visibly,
with nobody doing anything). **Confidence that erodes by default rather than
requiring an affirmative "this went stale" act** is the single best staleness
primitive in this dossier, and it scales to any cadence you like.

## II.7 Networking: forty years of paying for persistent paths

*Section method: RFCs fetched and read directly (**READ**); the GLOBECOM Segment
Routing paper read as PDF (**READ**); two claims flagged **UNVERIFIED** inline.*

Networking is the only tradition in this dossier where a persistent path is a
*product*, an *operational object*, and a *billable service*, and where the
industry has gone all the way round the loop: built it, scaled it, discovered
what it cost, and then deliberately un-built it. If TAP reads one section of
Movement II for engineering lessons rather than vocabulary, it should be this
one.

### MPLS: a path that exists only as the sum of its hops

RFC 3031 §3.15 defines a Label Switched Path as *a sequence of routers*
`<R1, …, Rn>` (**READ**, [RFC 3031](https://www.rfc-editor.org/rfc/rfc3031.txt)).
But that sequence is a *description*, not a stored object. What exists in the
network is per-hop label state: the ILM maps an incoming label to an NHLFE, and
the RFC is emphatic, in capitals, that "the next hop is always taken from the
NHLFE."

Three consequences (**INFERRED** from §3.13/§3.15):

1. **The path has no custodian.** It is a distributed invariant: *n* routers each
   holding one swap entry. Nobody holds the list. End-to-end connectivity is an
   emergent property of *n* independent pieces of state.
2. **Bindings are assigned downstream** (§3.4) — the path assembles from the
   destination backwards.
3. **Staleness handling is a configuration knob.** §3.8's *Liberal* label
   retention keeps bindings from non-next-hop neighbours to enable "quicker
   adaptation to routing changes"; *Conservative* discards them and re-acquires.
   Memory versus staleness, made an operator's choice rather than an
   architect's.

**LDP LSPs are not really persistent paths at all.** RFC 5036 defines LDP as
"mapping network-layer routing information directly to data-link layer switched
paths" (**READ**, [RFC 5036](https://www.rfc-editor.org/rfc/rfc5036.txt)); on a
routing change the LSR simply retrieves the label advertised by the new next hop.
**An LDP LSP cannot go stale because it has no independent existence.** It is a
shadow of the routing table. That is one entirely legitimate answer to the
staleness problem: *don't have the object.*

### RSVP-TE and the ERO: the one place the ordered list is literally stored

RFC 3209 (**READ**, [RFC 3209](https://www.rfc-editor.org/rfc/rfc3209.txt)) is
the closest thing in networking to TAP's proposed path node, and nearly every
design decision in it is worth stealing.

- The **EXPLICIT_ROUTE object (ERO)**, §4.3, is an ordered list of subobjects
  representing hops — *abstract nodes*, not necessarily physical routers.
- Each subobject carries an **L bit**: set means "loose," clear means "strict"
  (§4.3.3.1). **The canonical persistent path object in networking is explicitly
  designed to under-specify.** The parts nobody cares about are re-resolved on
  the fly. This exists because strict end-to-end lists proved too brittle to
  survive a moving topology.
- **Who holds it:** the ingress constructs it; per §2.2 each node along the path
  records it in its path state block. So there are *n+1* copies — one authored at
  the head-end, one cached per hop.
- **Identity is two-level**, and this is the transferable idea: the SESSION
  object carries a Tunnel ID "constant throughout the tunnel's lifetime," and the
  SENDER_TEMPLATE carries an **LSP ID** (§4.6.1.1, §2.5). **The tunnel is the
  stable identity; the LSP is the current instantiation of it.**

**Make-before-break** (§2.5) exists *because* of that split: "the tunnel ingress
needs to appear as two different senders to the RSVP session. This is achieved by
the inclusion of the 'LSP ID'." The old and new paths coexist under one identity,
distinguished by a version-like sub-identifier, and "resources used by the old
LSP tunnel should not be released before traffic is transitioned."

**Re-optimisation** (§2.2): "If, after a session has been successfully
established, the sender node discovers a better route, the sender can dynamically
reroute the session by simply changing the EXPLICIT_ROUTE object." Note the
trigger — *discovery of a better route*, not detection of breakage. The path
object is continuously re-evaluated against a moving world even when nothing
failed.

**Fast Reroute** (RFC 4090, **READ**,
[RFC 4090](https://www.rfc-editor.org/rfc/rfc4090.txt)) offers one-to-one backup
(a detour per protected LSP) and facility backup (one bypass tunnel protecting
many, via label stacking), targeting "redirection within 10s of milliseconds"
(§6.3.3). And §6.5.2 recommends *global revertive mode*: the head-end
re-optimises afterwards.

**That is the operational lesson in one sentence: local repair is a deliberately
temporary, deliberately non-optimal patch, and the architecture assumes a
slower, globally-informed authority will replace it.** Two timescales, two
owners. A graph product that offers "auto-repair the broken path" should know
which of those two it is building.

### Segment Routing: the argument against persistent per-path state, and it won

RFC 8402 (**READ**, [RFC 8402](https://www.rfc-editor.org/rfc/rfc8402.txt)):

> "Segment Routing (SR) leverages the source routing paradigm. A node steers a
> packet through an ordered list of instructions, called 'segments'."
>
> "SR supports per-flow explicit routing **while maintaining per-flow state only
> at the ingress nodes** to the SR domain."

RFC 8754 (**READ**, [RFC 8754](https://www.rfc-editor.org/rfc/rfc8754.txt))
gives the SRv6 header: a Segment List array, "encoded starting from the last
segment of the SR Policy," plus a mutable **Segments Left** cursor. Processing is
literally "Decrement Segments Left by 1. Copy Segment List[Segments Left] … to
the destination address."

**The SRH is a persistent path that travels with the traveller, carrying its own
program counter** (**INFERRED**). That is the whole architectural move, and it is
the most elegant thing in this dossier.

The rationale, from the architects — Filsfils, Nainar, Pignataro, Cardona and
Francois, *The Segment Routing Architecture*, IEEE GLOBECOM 2015
([PDF](https://www.cs.utsa.edu/~korkmaz/teaching/ds-resources/sharvari-papers/seg-2015-Filsfils-segment-routing.pdf),
**READ** from the PDF pages):

> "Because the information of the path that the packet has to traverse is
> included in the packet, intermediate routers do not have to maintain state for
> all steered paths that the network offers."

and the explicit indictment of RSVP-TE:

> "This additional state … **has proven to be difficult to cope with for ISP
> networks that may require the definition of multiple thousands of service
> chains** in their network."

The paper names three RSVP-TE failures: poor balancing (it does not fit ECMP, so
"a notorious number of MPLS RSVP-TE tunnels need to be replicated"),
"control-plane and data-plane scalability issues … caused by the state required
at each hop along any explicit path," and "unpredictable placement of the
traffic, non-optimal use of the resources, and **slow re-optimization**."

**That third one is the sleeper, and it is the sentence TAP should write on a
wall.** Distributed per-path state made re-optimisation slow, which made paths
stale, which made placement bad. *The state cost and the staleness cost were the
same cost.* You do not get to pay one and skip the other.

(A frequently quoted figure — "an order of magnitude reduction in router state
across ten topologies" — appeared only in a search summary and **not** in the
pages of the paper I read. **UNVERIFIED**. Do not quote it.)

### SR-TE Policies (RFC 9256): the best-designed persistent path object I found

If TAP copies one external data model, copy this one (**READ**,
[RFC 9256](https://www.rfc-editor.org/rfc/rfc9256.txt)):

- **Identity is a triple.** §2.1: "An SR Policy MUST be identified through the
  tuple `<Headend, Color, Endpoint>`." Colour is an opaque 32-bit *intent* tag —
  "low latency," "avoid-this-country."
- **One policy, many candidate paths.** §2.2. Candidate paths are *explicit*
  (operator-provisioned), *dynamic* (computed by headend or PCE), or *composite*.
- **Selection by preference.** §2.7: a 32-bit preference, default 100, highest
  wins. The winner is the *active* candidate path.
- **Validity is defined and checked cheaply.** §5.1: a segment list is invalid if
  empty, zero-weighted, mixing SR-MPLS and SRv6, **or if the headend cannot
  resolve the first SID**. §2.11: "Generally, only valid SR policies are
  instantiated in the forwarding plane." Validation is O(1) at the edge, not
  O(path length) across the network (**INFERRED**).
- **And the warning.** §6.2: the Binding SID "of an SR Policy is the BSID of its
  active candidate path" — and it may change when the active path changes,
  **making it unsuitable as a permanent policy identifier**.

That last bullet is a hard-won design lesson stated normatively in an RFC: *do
not use the handle of the current best path as the identity of the thing that
wants a path.* The identity is the intent. The handle is a pointer that moves.

### PCE: the centralised path authority, with an expiry date for orphans

RFC 4655 (**READ**) motivates centralisation: constrained path computation may be
too CPU-intensive for routers, the computing node has limited visibility in
inter-domain cases, and the TED "may require a lot of memory and … non-negligible
CPU activity." It also warns, in §6.8, that a *stateful* PCE "require[s] reliable
state synchronization mechanisms, with potentially significant control plane
overhead and the maintenance of a large amount of data/states."

RFC 8231 (**READ**) makes it concrete: State Synchronization provides "a
**checkpoint-in-time state replica** of a PCC's LSP state in a PCE"; **delegation**
is temporary and revocable; the **PLSP-ID** is "constant for the lifetime of a
PCEP session"; and there is a **State Timeout Interval** — "the period of time a
PCC waits for, when a PCEP session is terminated, before flushing LSP state."

RFC 8281 (**READ**) is the fully centralised named path object, and its best
feature is what happens when the authority dies:

> "PCE-initiated LSPs are not removed immediately upon PCE failure. Instead, they
> are cleaned up on the expiration of this timer."

Naming: "The LSP object MUST include the SYMBOLIC-PATH-NAME TLV, which is used to
correlate between the PCC-assigned PLSP-ID and the LSP" (§5.3). **The authority
names the path; the local node assigns the handle; the name is the join key.**

### BGP AS_PATH: path as value, not path as object

RFC 4271 (**READ**): AS_PATH is a well-known mandatory attribute identifying "the
autonomous systems through which routing information … has passed," composed of
AS_SEQUENCE (ordered) and AS_SET (unordered) segments. Loop detection is by
*inspection of the carried value* — reject a route whose AS_PATH contains your own
AS number.

Three things (**INFERRED**):

1. **The path is an attribute of the route, not an entity.** It has no ID.
   Nothing points at it. There is no "path object" to go stale; a stale AS_PATH
   is simply a superseded route.
2. **Carrying the path with the value makes a global property (loop-freedom)
   checkable locally, in O(path length), with no shared state and no
   coordination.** That is an extraordinarily cheap way to buy a safety property,
   and it is the mechanism TAP's cascade walk already reaches for — the visited
   set in `_discover_closure` is an AS_PATH by another name.
3. **AS_SET is the warning label.** It is the "I aggregated several paths and can
   no longer tell you the order" escape hatch. Lossy path aggregation degrades the
   very inspection that makes the scheme work. (That AS_SET is widely regarded as
   problematic in practice is **UNVERIFIED** — RFC 4271 merely defines it.)

### Soft state: the canonical staleness answer, and why it died

RFC 2205 (**READ**, [RFC 2205](https://www.rfc-editor.org/rfc/rfc2205.txt)):

> "RSVP soft state is created and periodically refreshed by Path and Resv
> messages. **The state is deleted if no matching refresh messages arrive before
> the expiration of a 'cleanup timeout' interval.**"
>
> "If the effective cleanup timeout is set to K times the refresh timeout period,
> then RSVP can tolerate K-1 successive RSVP packet losses without falsely
> deleting state."

**Soft state makes correctness the default failure mode.** Absence of evidence
becomes deletion. Nobody has to send a teardown; nobody has to be reachable to be
forgotten. It is the most elegant staleness answer available and TAP should
consider it seriously.

The cost is refresh traffic proportional to the number of live paths — and *that*
is what killed per-flow RSVP. RFC 2208 (**READ**,
[RFC 2208](https://www.rfc-editor.org/rfc/rfc2208.txt)) says the quiet part out
loud, in 1997:

> "The resource requirements (processing and storage) for running RSVP on a
> router **increase proportionally with the number of separate sessions**."
>
> "These scaling issues imply that it will generally **not be appropriate to
> deploy RSVP on high-bandwidth backbones** at the present time."

with the prescribed alternative: "at the 'edge' of the backbone, aggregate
together the streams that require special treatment," then use "various less
costly approaches" inside. **Detail at the edge, aggregates in the middle** —
which is, note, structurally the same move as process mining's trace variants
(§II.8) and as TAP's own dimensions-instead-of-a-million-CONTAINS-edges argument
in `docs/misc/graph-lookup-performance-notes.md`.

(The end-to-end argument — Saltzer, Reed and Clark, *ACM TOCS* 2(4), 1984,
[MIT PDF](https://web.mit.edu/saltzer/www/publications/endtoend/endtoend.pdf) —
is the theoretical ancestor of all of this. Citation located, body **UNVERIFIED**
in this pass.)

### What TAP inherits from networking

**Inherit:**

- **Three levels of identity, not two.** Intent (`Tunnel ID`, `<headend, colour,
  endpoint>`, `SYMBOLIC-PATH-NAME`) → current chosen path (`LSP ID`, active
  candidate, `PLSP-ID`) → evidence of traffic. RFC 9256 §6.2 is an RFC telling
  you in normative prose not to collapse the first two.
- **Make paths under-specifiable.** Loose EROs exist because strict lists were too
  brittle. A persistent TAP path should be able to say "through this node, then
  somehow to that node" and re-resolve the gaps — which, delightfully, is exactly
  what a *declared* path with edge-class predicates is.
- **Soft state or an explicit reaper.** A persistent path whose author has
  disappeared must expire, not accumulate. Two proven shapes: refresh-or-die
  (RSVP) and grace-period-then-flush (PCE State Timeout). Pick one. Do not pick
  neither. TAP's `req-grid-dual-existence-teardown` is Backlog and is exactly
  this question wearing a different hat.
- **Validate cheaply and locally.** RFC 9256 checks that the *first* SID resolves,
  not the whole path. "Is this path still valid?" need not mean "re-walk it."

**Avoid:**

- **Per-path state everywhere the path goes.** The networking industry paid for
  this lesson twice, in 1997 and 2015, and the bill came due in re-optimisation
  latency more than in memory. If a path must be stored, store it once — at the
  authority, or at the edge.
- **Using the current best path's handle as the path's identity.** By name, RFC
  9256 §6.2.


### The constraint test — and why MPLS is the closest engineering analogue TAP has

This is the tradition where the constraint question pays out best, because
networking is the only tradition here that built a persistent path object
*with explicit machinery for detecting its own invalidity* and then measured
what that machinery cost.

**What forced each choice.**

- **LDP's non-persistence is forced by having no independent object.** An LDP
  LSP is a projection of the routing table. There is nothing to invalidate and
  nothing to detect. **Does TAP inherit it? No** — a TAP path is not a
  projection of anything that re-derives itself for free.
- **RSVP-TE's persistence was *affordable* precisely because it had
  falsification machinery**: soft state with refresh-or-die, an explicit cleanup
  timeout tolerant of K−1 losses, a hello/liveness layer, FRR to survive the gap
  between breakage and repair, and head-end re-optimisation to replace the patch.
  **This is the point.** RSVP-TE did not persist a path and hope. It persisted a
  path *and continuously re-asserted it*, and the moment re-assertion stopped,
  the path stopped.
- **What killed RSVP-TE was not the storage. It was the re-assertion.** RFC 2208
  §2.1 is explicit that the cost "increase[s] proportionally with the number of
  separate sessions," and Filsfils's 2015 indictment names *slow
  re-optimisation* as a first-class failure, alongside the state itself. The bill
  came due for keeping the path *fresh*, not for writing it down.

**Does TAP inherit the RSVP-TE constraint?** This needs care, because the naive
answer is wrong in both directions.

*Not inherited:* TAP has no per-hop replication. A TAP path is written once, in
one Postgres row-set, at one place. RSVP-TE's `n+1` copies — one per router — are
the thing that made refresh traffic scale with path count × path length. TAP's
equivalent is a single row and its membership edges. The scaling term that killed
per-flow RSVP in the backbone simply does not exist in a single-writer relational
store.

*Inherited, and this is the part that matters:* **the re-assertion cost is real
and TAP pays it in a different currency.** RSVP-TE paid in refresh packets; TAP
would pay in re-evaluation queries. If a TAP path is a claim about which edges
are currently true, then keeping it honest means periodically re-asserting that
claim, and *that* cost scales with (number of paths × path length × how fresh you
want them) exactly as RSVP's did. The difference is that TAP can choose the
freshness dial and RSVP could not, because in a network a stale path drops
packets and in a grid a stale path merely misinforms a human. **That is a real
difference and it is the whole reason a persistent path is more defensible in
TAP than it was in a backbone router.**

And here is the mechanism RFC 9256 supplies for cutting the bill by an order of
magnitude, which TAP should copy outright: **do not re-validate the whole path.
Validate the cheapest thing that would have changed.** A segment list is invalid
if "the headend cannot resolve reachability for the first SID" — one lookup, not
*n*. The TAP analogue is exact and cheap: a stored path is *suspect* the moment
any `Entity` it names bumps its `version` or gains a `deleted_at`, and TAP
already has both of those as indexed spine columns written on every canonical
mutation. **A path does not need to be re-walked to be known stale; it needs to
be watching a version counter.** That turns "is this path still true?" from a
traversal into an indexed comparison, which is the single most valuable
engineering idea in Movement II.

**The three-level identity is the other inheritance**, and the reason to take it
seriously is that RFC 9256 §6.2 is a standards body writing down, normatively,
the mistake it watched people make: using the handle of the current best path as
the identity of the thing that wants a path. TAP's version of that mistake is
available and tempting — naming a path node after the route it currently
describes, so that when the route changes the node is either wrong or replaced.
The fix is the same fix: the durable identity is the *intent* ("the deploy path
for service X", "the containment closure of account Y"), and the route is a
mutable, replaceable, versioned thing hanging beneath it.

## II.8 Process mining, Petri nets and BPM: paths as discovered objects

*Section method: van der Aalst's own papers and the OMG BPMN 2.0.2 PDF fetched
and read (**READ**); Camunda and Temporal documentation fetched and read
(**READ**); several secondary claims flagged **UNVERIFIED** inline where a
paywall or a refused fetch blocked the primary.*

This is the tradition that discovers paths rather than declaring them, and it has
the most honest empirical data about what path spaces in real systems actually
look like. Two numbers from it should change how TAP thinks about scale.

### The two numbers

From van der Aalst, *Object-Centric Process Mining: Dealing With Divergence and
Convergence in Event Data*
([p1056.pdf](https://vdaalst.com/publications/p1056.pdf), **READ**):

> "Often, 80% of the observed process executions (cases) can be described by less
> than 20% of the observed process variants. This implies that the remaining 20%
> of the observed process executions account for 80% of the observed process
> variants."
>
> "In some organizations, one can observe **close to one million different ways to
> perform the O2C process in a single year**."
>
> "Often the 20% least frequent behavior may cause most of the compliance and
> performance problems."

**Path spaces in real systems have a heavy tail of near-unique paths, and the
tail is where the interesting findings live.** For a security product this is not
a curiosity, it is the whole business: the weird path *is* the finding. Any design
that summarises paths by frequency will systematically discard exactly the paths
TAP exists to surface.

### Directly-Follows Graphs: the beautiful lie

van der Aalst, "A practitioner's guide to process mining: Limitations of the
directly-follows graph," *Procedia CS* 164 (2019) 321–328, DOI
[10.1016/j.procs.2019.12.189](https://doi.org/10.1016/j.procs.2019.12.189).
Citation and abstract **READ** (via the Semantic Scholar API: "the risks
associated with frequency-based simplification"); the enumerated limitations are
**UNVERIFIED-from-full-text** — ScienceDirect, ResearchGate and the RWTH
repository all refused fetches. From the search index, the named pitfalls are:

1. DFGs **cannot represent concurrency**; concurrent activities appear as loops
   that never occurred.
2. **Frequency-based simplification** — dropping nodes and edges below a
   threshold — is applied seamlessly, and the resulting graph implies behaviour
   the log never contained.
3. Users therefore "need to know how these process models are generated before
   interpreting them."

**This is the precise hazard for a graph product that renders "paths" as a
summarised edge-frequency graph.** A DFG loses the distinction between "A and B
happened in either order, independently" and "A then B then A then B," and then
admits routes no instance ever walked. If TAP builds a path view by aggregating
observed hops into a weighted graph, it has built a DFG and inherited the defect.
The literature's fix is not a better DFG — it is to keep *variants* as
first-class objects and to use a formalism that can express concurrency.

**Trace variants** are the data-reduction move: an event log is formally a
*multiset of trace variants*, `L = [⟨a,b,c⟩³, ⟨a,b,a⟩¹¹, ⟨a,c,b,a⟩²⁰]`. You do
not store *N* paths; you store *V* distinct path-shapes with counts. It is
run-length encoding over the path space, lossless as to shape and lossy as to
per-instance identity — which is why the million-variant tail still costs you.

### Alignments: "is this path still true?", answered properly

This is the single best answer to the question that Movement III has to solve,
and it comes from conformance checking.

From van Dongen, Carmona and Chatain, "Alignment-based Metrics in Conformance
Checking," EMISA 2016
([CEUR Vol-1701 paper22](https://ceur-ws.org/Vol-1701/paper22.pdf), **READ**):

> "An alignment is a sequence of pairs that refer to an event from a trace and a
> transition in the model, or ≫ elements indicating deviations. … If both parts
> of the pair are equally labelled, we call such a pair a **synchronous move**. A
> **model move** is a pair ⟨≫, t⟩, i.e. a transition is fired, but no
> corresponding event appeared in the log, and a **log move** is a pair ⟨a, ≫⟩,
> i.e. an event appears in the log, but there is no corresponding transition to
> be fired in the model."
>
> "Typically, a cost function is used to compute so-called **optimal
> alignments**, such that the number of model moves … and log moves … is
> minimized."

Their worked example yields fitness `1 − 5/11 = 0.55` for a trace with five
deviations.

**An alignment does not answer "does this path still hold?" with a boolean. It
returns the cheapest explanation of the discrepancy, itemised** — here is where
reality did something the declared path forbids; here is where the declared path
expected something reality skipped — **plus a scalar in [0,1]**. That is an
enormously better product than a red badge, and it degrades gracefully: a path
that is 90% still true reports 0.9 with two named deviations rather than
"broken."

The move vocabulary — synchronous / log-move / model-move — is a ready-made diff
format for "reality versus declared path," and TAP should consider adopting it
verbatim rather than inventing one.

**The cost is real and must be budgeted.** From Reißner et al., "Scalable
Alignment of Process Models and Event Logs," *Information Systems* 2020
([arXiv:1910.09767](https://arxiv.org/pdf/1910.09767), **READ**):

> "it applies an **A\* algorithm to find the shortest path through the
> synchronous net** which represents an optimal alignment."
>
> "the number of possible interleavings of the parallel activities increases
> rapidly, for example **four tasks in parallel can be executed in 24 different
> ways while eight tasks can already be executed in 40 320 different ways**."
>
> "in a collection of 40 real-life event logs … the execution times of these
> techniques are **over 10 seconds in about a quarter of cases and over 5 seconds
> in about half of cases**."
>
> "existing techniques compare each execution trace in the log against the
> process model separately, **without reusing computations made for one trace
> when processing subsequent traces**. Yet, the execution traces of a business
> process typically share common fragments."

Their remedies: represent the whole log as one minimal DAFSA so shared prefixes
and suffixes are aligned once, and decompose the model into concurrency-free
S-components. Even so, the technique "still fails to perform satisfactorily on a
handful of the event logs," particularly with nested loops.

(A commonly cited claim that alignment is PSPACE-complete on safe workflow nets
appeared in search summaries and **not** in the pages I read. **UNVERIFIED**.
What is certain from primary text: it is A\* over a synchronised product whose
state space explodes with concurrency, and it costs seconds to minutes per log at
real-world scale.)

**If TAP offers "check all my paths," it is offering an NP-flavoured search and
needs the shared-prefix trick from the outset, not as an optimisation later.**

### Petri nets: the net is not the run, and cut-off events are the stopping rule

A path through a Petri net is a **firing sequence** — a linear order. For a
concurrent net, many firing sequences represent the same underlying run; the
partial-order representation of a run is an **occurrence net**, and the set of all
runs is the **unfolding**, a branching acyclic net. The unfolding of a looping net
is infinite; McMillan's contribution was the **finite complete prefix**, built by
identifying **cut-off events** — "those events where the unfolding process can be
stopped without any loss of information." Esparza, Römer and Vogler improved it
with a total order on configurations (the ERV algorithm), producing a smaller
prefix. Sources: [Springer](https://link.springer.com/chapter/10.1007/BFb0055644),
[McMillan for contextual nets](https://link.springer.com/chapter/10.1007/978-3-540-89287-8_12),
[arXiv:2311.11443](https://arxiv.org/pdf/2311.11443). All **UNVERIFIED-from-primary**
— these are search-index summaries of pages not fetched.

**Cut-off events are the transferable idea, and they answer a question the June
notes did not ask.** If TAP ever materialises a path *space* rather than a path,
the principled answer to "when do I stop expanding?" is not a depth cap. It is an
equivalence-based stopping criterion with a completeness argument attached. A
depth cap is an admission that you do not know what you are throwing away.
(TAP's `TAP_CASCADE_MAX_CLOSURE` is a depth cap, and it is the right *safety*
device — it refuses rather than truncates — but it is not a completeness
argument.)

**Workflow-net soundness** gives a free validation for any declared path space
(**READ-from-search-index**, corroborated across the Inductive Miner literature;
primary sources
[Springer](https://link.springer.com/content/pdf/10.1007/s00165-010-0161-4.pdf)
and [van der Aalst p464](https://www.vdaalst.rwth-aachen.de/publications/p464.pdf)):

1. **Option to complete** — the end state is always still reachable.
2. **Proper completion** — when the end place is marked, all others are empty.
3. **No dead transitions** — every activity is reachable by some route.

**Condition 3 is directly implementable for TAP**: a declared path space
containing a step that no path can reach is, by definition, unsound. That is
dead-code detection over a path definition, and it is exactly the kind of check
`validate_plugin` already performs for edge declarations
(`req-grid-service-delete-cascade-17`, **READ**).

And the warning attached: soundness becomes **undecidable** once you add reset
arcs. *Expressiveness in the path-space language costs you decidability of the
invariant.* Every feature added to a path-definition DSL should be weighed
against that.

### BPMN: the model/instance split, verified against the spec

From the [OMG BPMN 2.0.2 PDF](https://www.omg.org/spec/BPMN/2.0.2/PDF/),
converted locally (**READ**, verbatim):

> "we employ the concept of a token that will traverse the Sequence Flows … **A
> token is a theoretical concept that is used as an aid to define the behavior of
> a Process that is being performed.** … modeling and execution tools that
> implement BPMN are **NOT REQUIRED** to implement any form of token."

> "A Process is instantiated when one of its Start Events occurs. **Each
> occurrence of a Start Event creates a new Process Instance** unless the Start
> Event participates in a Conversation…"

> "**All the tokens that were generated within the Process MUST be consumed by an
> End Event before the Process has been completed.**"

That last line is workflow-net *proper completion* restated in BPMN's vocabulary
(**INFERRED**).

And a trap worth naming, from §10 on uncontrolled flow:

> "If the Activity has multiple incoming Sequence Flows, then this is considered
> **uncontrolled flow**. … when a token arrives from one of the Paths, the
> Activity will be instantiated. It will not wait … If another token arrives … a
> separate instance of the Activity will be created."

**Implicit merges in a path model silently multiply instances.** If TAP's path
model lets two branches reconverge without saying what reconvergence *means*, it
has an uncontrolled flow.

### Camunda and Temporal: how the industry actually stores path instances

**Camunda 7** (**READ**,
[history docs](https://docs.camunda.org/manual/latest/user-guide/process-engine/history/)):
the engine maintains runtime state **while simultaneously producing a separate
history event stream**; "the process engine is still able to work … if the user
chooses to log events to a different database." Depth is a dial —
`historyLevel` ∈ {NONE, ACTIVITY, AUDIT, FULL} — and retention is a configurable
TTL. **Runtime state and path evidence are separate stores with separate
lifecycles, and the depth of path recording is a per-deployment choice, not a
fixed schema.**

**Camunda 8 / Zeebe** goes further (**READ-from-search-index**,
[exporters](https://docs.camunda.io/docs/self-managed/concepts/exporters/)): the
broker keeps an event log **compacted based on positions acknowledged by
exporters**, and the queryable history is a *derived projection* held elsewhere.
The authoritative stream is cheap and short-lived; the path view is rebuilt.

**Camunda 8's migration API is the best prior art anywhere for "the graph moved
under my persistent path"** (**READ**,
[process instance migration](https://docs.camunda.io/docs/components/concepts/process-instance-migration/)):

- Why: "the process definition of a running process instance needs changes due to
  bugs or updated requirements."
- How: "You must provide a **migration plan with mapping instructions** to the
  target process definition to clarify your intentions."
- Constraints: "You cannot map an element to an element of a different type"; all
  active elements require mappings; "the number of active elements cannot be
  changed."
- Atomicity: "it is migrating all active elements or nothing."

**Camunda refuses to guess.** A typed, total, atomic, explicitly-authored
mapping. Contrast RSVP-TE's loose EROs, which *do* guess for the under-specified
segments. The two systems differ because BPMN instances carry business-critical
side effects and LSPs do not (**INFERRED**) — and TAP should decide which of
those its paths resemble before choosing.

**Temporal** is the cleanest instance of the pattern and it inverts the usual
arrangement (**READ**,
[Events and Event History](https://docs.temporal.io/workflow-execution/event),
[limits](https://docs.temporal.io/workflow-execution/limits)):

- Event History is "**an append-only log of Events**," "durably persisted by the
  Temporal Service."
- **Replay**: "a Replay is the method by which a Workflow Execution resumes making
  progress, and during a Replay the Commands that are generated are checked
  against an existing Event History." A mismatch due to non-determinism is a hard
  failure.
- **Limits**: hard cap of **51,200 Events or 50 MB** per execution, warnings at
  **10,240 Events or 10 MB**; the remedy is **Continue-As-New**, which segments
  one logical process into a chain of bounded executions.

**The code is the path space. The event history is the path instance. The
instance is authoritative — state is reconstructed by replaying it.** Which is
why non-determinism is an error rather than a warning, and why "is this path still
true?" becomes "does replay still succeed?", failing loudly at a specific command
index rather than drifting silently.

Two things to steal: **bound the path instance loudly, with a documented
segmentation escape hatch** (warn at 20% of cap; provide Continue-As-New), and
note that the precise-failure property comes *from* the determinism constraint —
you only get a crisp "this path broke here" if you were strict about what a path
was allowed to be.

### The claim, tested: does "space persistent, instance evidence" hold?

The brief asked for this claim to be tested rather than assumed. **It holds for
execution systems and inverts for analysis systems.**

**Holds:** BPMN/Camunda/Zeebe/Temporal (definition is durable and versioned;
instance is bounded, aged, retention-dialled evidence). Petri nets (soundness is a
property of the net, provable with no run in hand).

**Inverts:** *Process discovery runs the arrow backwards.* The instances are the
primary given data and the path space is derived, provisional and disposable — a
different miner on the same log yields a different model. In process mining the
**log is the durable asset and the model is the transient artefact.** Temporal
inverts it hardest: the instance constrains the space, not the reverse.

**Declines to choose:** conformance checking. van der Aalst's framing is that it
checks "if reality, as recorded in the log, conforms to the model **and vice
versa**," and the model "may be descriptive or normative" (**READ**). The field
explicitly refuses to privilege either side.

**The refined claim I would carry forward — and it agrees exactly with what §II.7
found independently in networking:**

> Every mature system separates **a durable identity that outlives any particular
> route**, from **the route currently in force**, from **the evidence of routes
> actually walked**. Three levels, not two. RSVP-TE: Tunnel ID / LSP ID /
> forwarding state. SR: `<headend, colour, endpoint>` / active candidate path /
> packets. BPMN: process definition / process instance / history rows. Temporal:
> workflow type + ID / current run / event history. **The failure mode in all of
> them is conflating level 1 with level 2** — and RFC 9256 §6.2 warns about that
> conflation by name.

### The multi-entity warning, which is aimed straight at graph products

The known limitation of XES (IEEE 1849, currently the 2023 revision — **READ**,
[xes-standard.org](https://xes-standard.org/)) is the case-ID assumption, and van
der Aalst's statement of it is the most relevant single sentence in §II.8 for TAP
(**READ**, p1056 abstract):

> "In many applications, there are multiple candidate identifiers leading to
> different views on the same process. Moreover, one event may be related to
> different cases (**convergence**) and, for a given case, there may be multiple
> instances of the same activity within a case (**divergence**). To create a
> traditional process model, the event data need to be 'flattened'. … Therefore,
> one quickly loses the overview and event data need to be exacted multiple times
> (for the different views)."

**In a graph, an event genuinely does relate to several entities at once, and
choosing one as "the case" is exactly the flattening van der Aalst says loses the
overview.** The response is **OCEL 2.0** (**READ**,
[ocel-standard.org](https://www.ocel-standard.org/),
[arXiv:2403.01975](https://arxiv.org/pdf/2403.01975)) whose metamodel has events,
typed objects with *time-varying attributes*, **two kinds of relationship**
(event-to-object *and* object-to-object independent of any event), activities, and
**qualifiers** categorising relationships — "distinguishing roles objects play in
events, such as designating an actor."

Note what happened: **the process-mining field arrived at a property graph from
the log direction** (**INFERRED**). And note what they needed when they got there:
*qualified* relationships — role labels on the event-to-object edge. That is
exactly the "roles" idea §II.3 finds in TypeDB, reached independently.

TAP is already on the correct side of this, and should know that it is: the grid
does not flatten to a case ID, because it never had one.

### Concept drift: the honest answer to "when does my declared path go stale?"

Process mining has a named research area for model decay
([survey, arXiv:2112.02000](https://arxiv.org/html/2112.02000v1),
[VLDB evaluation](https://dl.acm.org/doi/10.14778/3594512.3594517) —
**READ-from-search-index**). Drifts are classified **sudden, gradual, incremental,
recurring**, and "detecting gradual drifts is more challenging than sudden drifts
because there is no specific point when cases start emanating from a different
version of the process."

The operational point is sharp: **a discovered path model is a statistical claim
about a window of time, and it decays. The literature's answer is not "refresh on
a schedule" but "detect the change point and localise it."** A product that
re-derives paths nightly and shows the latest answer is strictly worse than one
that says "this path's behaviour changed on the 14th, in this region." That is
also, note, exactly TAP's own re-observation ruling (re-observation ≠ change,
tap#322) pointed at paths.

## II.9 Cross-tradition synthesis: what eight traditions agree on

Eight traditions, several hundred sources, and a surprising amount of agreement
once you stop asking "who persists paths" and start asking "what does each
system's substrate let it know, and what does it do with that knowledge."

### The seven convergences

**1. Three levels of identity, not two.** Every mature system separates *a
durable name for the intent*, from *the route currently in force*, from *the
evidence of routes actually walked*.

| Tradition | Level 1: intent | Level 2: current route | Level 3: evidence |
| --- | --- | --- | --- |
| RSVP-TE | Tunnel ID | LSP ID | forwarding state |
| Segment Routing | `<headend, colour, endpoint>` | active candidate path | packets |
| BPMN / Camunda | process definition | process instance | history rows |
| Temporal | workflow type + ID | current run | event history |
| WINGS | workflow template | instance | executable run |
| in-toto | layout | — | link metadata |
| KEGG | `map00010` | `hsa00010` | — |
| Reactome | `R-HSA-70171` | `.N` version | InstanceEdits |
| git | ref / annotated tag | commit it points at | reflog |

**The failure mode in all of them is conflating level 1 with level 2, and RFC
9256 §6.2 warns about that conflation by name**: do not use the handle of the
current best path as the identity of the thing that wants a path.

**2. Identity is the binding constraint, not truth.** Established independently
three times — from attack paths (§II.4: BloodHound Enterprise *has* falsification
machinery and still does not persist paths, because a path has no natural key
while an edge and a finding do), from provenance (§II.5: OPM's multi-step edges
died because "the witness is destroyed by the inference that produces it"), and
from biology (§II.6: "Pathway Commons solved entity identity and left path
identity undefined"). **A path has no external registry to borrow identity from.
You must define its identity function yourself.**

**3. And the escape is always the same: identity comes from the declaration.**
RFC 9256's colour, BPMN's process definition, WINGS' template, in-toto's layout,
ProvONE's `prov:Plan`, KEGG's reference map, git's annotated tag. **Seven
traditions, no coordination, one answer.** The route is what the declaration
currently resolves to.

**4. Membership and ordering are two properties, and ordering is the optional
one.** BioPAX states the rule and requires membership even when order is present.
Reactome implements it with `hasEvent` and `precedingEvent`. And the measured
finding in §II.6 is that **two of seven topology-based methods stored the graph
and produced identical answers with it removed.** Build the ordering if you have
it; do not make it the only route to value.

**5. Absent is not empty, and every serious system says so in its schema.**
CycloneDX: components with no dependencies "MUST be declared as empty elements";
those absent "may have unknown dependencies … assume this to be opaque."
BloodHound Enterprise: "does not assume that lack of visibility during a single
collection means that an object or edge no longer exists." TAP's own
`null` = unobserved, `""` = observed-empty. **Three independent arrivals.**

**6. When a non-persisting system is asked for change-over-time, it reaches for a
file diff.** Cartography's `drift-detect` JSON states on disk; Powerpipe's
snapshot JSON; WikiPathways' Zenodo deposits; SLSA's VSA. **Four systems, same
workaround, and in every case the reason is that the store destroys evidence on
delete.** TAP tombstones. This is the clearest place where TAP's substrate makes a
competitor's design unnecessary rather than merely cheaper.

**7. Nobody stores paths; everybody stores something adjacent.** A derived edge
with a reconstructible proof (BloodHound). A reachability bitmap (dawgs). A
finding keyed on endpoints (BHE, Wiz, Prisma, Sysdig, Tenable). A named set with
an accession (MSigDB). A verdict with a timestamp (SLSA's VSA). A template
(KEGG, WINGS). **The path is the transient thing in the middle, and the durable
things sit one layer above it or one layer below.**

### The three costs, honestly

**Path tracking destroys merging.** TinkerPop states it best — "a collection of
paths vs. a single 64-bit long" — and it generalises well beyond Gremlin, because
it is really a statement about `UNION` versus `UNION ALL`. Whatever else a path
feature costs, it costs you the ability to bound a frontier by the graph.

**Retraction is structurally harder than addition.** Monotone derivation makes
additions cheap and gives you no mechanism to un-derive. Postgres offers no
incremental materialised-view refresh — `REFRESH MATERIALIZED VIEW` "completely
replaces the contents… The old contents are discarded." Every system surveyed
recomputes wholesale, and the one paper addressing incremental attack-graph
maintenance (Saha, CCS 2008) is paywalled, uncited in practice, and eighteen
years old.

**Cardinality is untouched by any substrate feature.** *"Millions, if not
billions of Attack Paths"* at a thousand endpoints. A million distinct O2C
process variants in one organisation in one year. Ten million edges from ten
hosts with five vulnerabilities each. **No amount of provenance makes a billion
paths storable**, and this is the constraint most easily forgotten because it
sounds like an implementation detail and is not.

### The six mechanisms worth stealing outright

1. **Validate cheaply and locally.** RFC 9256 checks that the *first* SID
   resolves, not the whole path. TAP's analogue is exact and free: **a stored path
   is suspect the moment any `Entity` it names bumps `version` or gains
   `deleted_at`** — both indexed spine columns written on every canonical
   mutation. *"Is this path still true?" becomes an indexed comparison rather than
   a traversal.*
2. **Confidence that decays by default.** Reactome's unreviewed content drops
   from five stars to three after six months, visibly, with nobody acting. Erosion
   by default beats requiring an affirmative "this went stale."
3. **Alignments, not booleans.** Conformance checking returns the cheapest
   itemised explanation of the divergence — synchronous move, log move, model
   move — plus a fitness scalar. A path that is 90% still true reports 0.9 with
   two named deviations, not "broken."
4. **A typed lifecycle with a controlled reason vocabulary.** Reactome's seven
   deletion reasons, with `replacementInstances` at cardinality `+` so split fans
   out and merge fans in through one field. Plus GO's two-value successor
   confidence: `replaced_by` a machine may follow, `consider` a human must judge.
5. **A named ladder of lossy projections from one canonical store.** Pathway
   Commons ships BioPAX → extended SIF → GMT and names each rung. Do not choose
   between a rich model and simple edges; publish both and state the loss.
6. **Issue both a pinned and a floating identifier.** Reactome's `.N` for
   diffing, bare stem for linking. WikiPathways issues only pinned in RDF and only
   floating on the web, and the two never meet, and the result is that citing a
   version means screenshotting the page.

### And the four things every tradition warns against

- **An optional ordering layer.** BioPAX made `PathwayStep` optional to reduce
  authoring cost, essentially nobody populated it, and traversal algorithms can
  now rely on neither. *Unpopulated ordering is worse than none.*
- **A set masquerading as a path.** SBML Groups deduplicates members, so a loop or
  a revisit is unrepresentable — and the document stays valid while meaning
  something else.
- **Rendering paths as a frequency-filtered directly-follows graph.** It cannot
  express concurrency, shows concurrency as loops that never happened, and admits
  routes no instance ever walked.
- **Shipping create and update without merge, delete and redirect.** WP3963 is the
  proof, and `req-grid-dual-existence-teardown` is TAP's version of the same
  Backlog item.

---
# Movement III — Evaluating the Path-as-Node

*Section method: this movement is argument, not research. Where it rests on a
fact, the fact is cited back to Movement I (TAP's own tree and specs, **READ**)
or Movement II (external sources, cited there). Where it is my judgement, it says
so. The recommendation at the end is a stated opinion and is meant to be argued
with.*

Two movements of evidence, and now the part where somebody has to decide
something.

A brief orientation, because the shape of this movement matters. It does not
proceed by listing pros and cons and then splitting the difference. It proceeds
by establishing that **the June notes bundled together four separable decisions
that look like one decision**, pulling them apart, and answering each on its own
evidence. The four are:

1. **Does a path get an identity on the grid?** (path-as-node)
2. **Where does that identity come from** — a declaration, or a computation?
3. **Does TAP store path *instances*** — recorded walks — as well as path *types*?
4. **Do path edges point at edges?**

The June notes treat (1) and (4) as one question — "persistent path nodes require
edge-to-edge" — and that bundling is, I will argue, the single most consequential
error in the prior sketch. **Question 4's answer depends entirely on question 3's,
and question 3 has an answer the prior art is unanimous about.**

## III.1 What a path-as-node buys

Let me steelman it properly first, because the case is strong and some of it is
stronger than the June notes claimed.

**Identity, and it is the whole game.** Movement II's single most repeated
finding is that identity is the binding constraint. A path node supplies one by
construction: a uuid7 on the spine, assigned, never derived, never reused. That
is not a small thing — it is the thing BloodHound could not have, the thing OPM's
multi-step edges lacked, the thing Pathway Commons left undefined. **TAP would be
solving, with an existing primitive, the problem three separate traditions named
as the reason they gave up.**

**Everything the spine already does, for free.** This is the argument the June
notes made and undersold. A path node is an `Entity`, so it inherits, with no new
code: `dimensions` with a GIN index (so path membership is queryable and
scopeable); `version`, monotonic, bumped on every canonical mutation;
`deleted_at`, so a path tombstones rather than vanishes; `created_at`/`updated_at`;
`originating_grid_id`; history via `HistoricalRecords`; FLIP field-level batch
provenance; the write chokepoint and its guard; and the `SPINE_FIELD_NAMES`
serialisation surface. **Movement II is full of systems that had to build each of
these by hand and mostly didn't.** Reactome built `UpdateTracker` and a computed
version counter; Cartography built a filesystem differ; WikiPathways built a
Zenodo workflow; SLSA built `timeVerified`. TAP gets all of it by declaring one
model class.

**GRIFT portability for free, and this is a verifiable fact rather than a hope.**
The canonical subgraph schema is `{nodes: [], edges: []}` with
`"additionalProperties": false` and "Unknown keys are invalid at the canonical
subgraph level" (**READ**, `spec-grift-subgraph.md`). **A path-as-node
serialises through GRIFT with zero format change** — it is a node in `nodes`, its
membership edges are edges in `edges`, and every existing consumer (search, web,
viz, the API) handles it without modification. **A path as a *new kind of thing*
— a `paths` array — is a breaking schema change to the one portable contract TAP
has.** That asymmetry alone is close to decisive on the representation question.

**Being pointed at.** A path node can be the target of edges from findings, from
requirements, from evidence, from a `Search`, from an AI agent's proposal. The
June notes' "paths on paths" is the same property in a more ambitious costume.
Nothing else in the design space has this: a materialised view cannot be an edge
endpoint, and a JSON blob on `Entity` cannot be pointed at from outside the row
that carries it.

**Permissions, protection and dimensional scoping, without new machinery.** TAP's
authz is dimension-shaped and dimensions live on `Entity`. A path node is
dimension-scoped the day it exists. The June notes' "path protection" and
"path importance tagging" are, in this model, ordinary dimension and property
work rather than a new subsystem.

**And a precedent that is already spec'd.** `Dimension` is a `BaseModel` with
`ENTITY_TYPE = "dimension"`, an assigned uuid7, `INBOUND_EDGES = []`, and entities
referencing it by id (`spec-grid-dimension.md`, **READ**). **TAP has already
ruled that grid vocabulary becomes nodes.** A path node is the same ruling
applied to a different vocabulary — with the interesting inversion that a
dimension is *a node nothing points at*, and a path is *a node that points at
everything*. Both are coherent; the pair of them makes a pattern rather than a
one-off.

**Finally, the argument nobody in Movement II can make and TAP can.** Every
persistent-path design surveyed had to answer "how do you know this is still
true?" with either a timer (BloodHound's TTLs, RSVP's soft state, Reactome's
six-month decay) or a full recompute (everyone else). **TAP can answer it with an
indexed comparison**, because `Entity.version` and `Entity.deleted_at` are
written on every canonical mutation and both are indexed. A stored path is
*suspect* the moment any entity it names moves. That is RFC 9256's
validate-the-first-SID trick, available to TAP in a stronger form than it is
available to a router. **This is TAP's genuine, distinguishing advantage and it
should be the centrepiece of the design rather than a footnote.**

## III.2 What it costs

Now the bill, itemised, with the prior art's evidence attached to each line.

**Staleness, and the shape of it is worse than "the data goes out of date."** A
persisted path makes a claim about a *conjunction* of facts. Its truth-value is
bounded by its weakest member's freshness, and — as BloodHound's 3-day-versus-
7-day TTL split shows — those freshnesses are not comparable. A path over
`RUNS_ON` edges collected hourly and `OWNED_BY` edges authored once a year is
stale on a schedule nobody can state. **No product surveyed exposes per-path
freshness**, and TAP would have to invent the display as well as the mechanism.

**The retraction asymmetry, which is the deep one.** Adding an edge to the grid
can only *extend* the set of true paths; tombstoning one can *invalidate* paths,
and there is no cheap way to find which. This is not a TAP problem, it is a
property of monotone derivation, named in §II.4 and §II.9, and Postgres offers no
relief: `REFRESH MATERIALIZED VIEW` "completely replaces the contents… The old
contents are discarded" (**READ**). **Any design that materialises path
*contents* signs up for full recomputation on every retraction, exactly like
everybody else in Movement II.**

**Combinatorial volume, which no substrate feature touches.** *"Millions, if not
billions of Attack Paths"* at a thousand endpoints. A million distinct process
variants in one organisation in one year. Ten million edges from ten hosts. **A
billion paths are exactly as unstorable with perfect provenance as without it.**
This is the constraint that most easily gets forgotten, and it forecloses one
whole family of designs on its own.

**Frontier explosion at query time.** TinkerPop's bulking argument generalises:
path identity is precisely what stops a traversal frontier being bounded by the
graph. In TAP's terms this is the difference between `UNION` and `UNION ALL` in a
recursive CTE, and `docs/misc/graph-lookup-performance-notes.md` already names
frontier size as the term that matters. **Any query-time path feature pays this
whether or not the answer is persisted.**

**The "is this path still true?" question has no boolean answer, and pretending
otherwise is the product failure.** §II.8's alignment work is the rigorous
treatment: the right answer is an itemised cheapest-explanation plus a fitness
scalar, not a red badge. And the cost of computing one properly is A\* over a
synchronised product, seconds to minutes per log at real-world scale. **A TAP
feature that offers "check all my paths" is offering an NP-flavoured search.**

**Aliasing, if step nodes are shared.** BioPAX's warning, verbatim and aimed
squarely at this design: "**If new information became available for one of those
pathways, addition of this additional information to the BiochemicalPathwayStep
instance could invalidate it for all of the other pathways that refer to it.**"

**Write amplification and version-bump storms.** Movement I's open question 13.
If path membership changes as a side-effect of ordinary writes, every collector
pass potentially bumps `Entity.version` on every path node whose membership
moved. TAP has been bitten by precisely this shape before — tap#322, where an
unchanged node gained a history version on every one of 144 daily collector
passes. **A naive path-membership implementation would recreate tap#322 at the
path layer**, and it would be worse, because a path spans many nodes and so is
touched by many collectors.

**And the one that is not usually counted: a stored path is a claim you now own.**
Cartography's honesty paragraph is the model here — their privilege-escalation
queries "are **triage aids, not effective-permission evaluations**" and "do not
account for resource scope, conditions, explicit denies, wildcard actions,
permissions boundaries, service control policies, **or whether a principal can
reach a suitable target**." **Anyone shipping a persisted path owns that entire
list, and owns it over time rather than only at the moment of the query.**

## III.3 Edges to edges, seriously examined

This is the crux, so it gets the space.

### First, the facts about TAP's substrate, restated

- `Edge` is a `BaseModel` and therefore has its own `Entity` row on the spine,
  with a uuid7, dimensions, version, history and a tombstone (**READ**,
  `tap_grid/models.py:1033`).
- `from_entity` and `to_entity` are plain FKs to `Entity` with `on_delete=CASCADE`
  and **no type restriction whatsoever** (**READ**, `models.py:1070-1079`).
- The prohibition is four lines of Python in the service layer, duplicated once
  for a legacy error contract (**READ**, `services/_impl.py:605-609`,
  `services/__init__.py:1564-1568`).
- The spec says so itself: "**This is a service-layer rule only. The database
  schema does not enforce it** … A connection created by bypassing the service
  layer will be accepted by the DB" (**READ**, `req-grid-edge-nono`).

So the June note's claim — "the only thing keeping us from making edges to edges
is a convention we set early on" — is **exactly correct**, and Movement II
confirms that TAP is unusual in this. Twenty property-graph systems were checked
and twenty say no; but the *reason* differs, and for TAP the reason is neither of
the two real ones. FalkorDB's sparse matrices and Nebula's endpoint-derived keys
make it physically impossible; openCypher's "a node can exist in and of itself,
an edge cannot" makes it definitionally forbidden. **TAP broke the second premise
years ago, deliberately, and has apparently not noticed. In TAP, an edge *does*
exist in and of itself.**

### Second, what the spec's stated rationale actually claims, and whether it holds

`req-grid-edge-nono` says: "Allowing edges whose endpoints are themselves edges
**collapses the model into a hypergraph with significantly higher traversal
complexity**."

**That rationale is wrong on the formalism and right on the instinct, and it is
worth separating the two.**

Wrong on the formalism: edges-about-edges does **not** make a hypergraph. A
hypergraph generalises *arity*; this generalises *recursion*. The formal object
is an **ubergraph** — Joslyn and Nowak's term — and the precise statement is that
the Levi (incidence) graph relaxes from **bipartite** to **DAG** (§II.3,
**READ**). TAP's edges stay binary. Nothing about arity changes. If the spec is
revised, that sentence should be too, because it currently defends the right
conclusion with a wrong reason, and a wrong reason is a defence that collapses
the first time someone informed pushes on it.

Right on the instinct: the DAG relaxation *does* have costs, they are just not
the ones named. **They are three, and only one of them is traversal complexity.**

1. **Deletion.** §II.3's most actionable finding: edge-to-edge does not break
   storage, it breaks deletion, and the two most mature implementations landed on
   *opposite defaults* — HyperGraphDB cascades by default with an unlink flag,
   TypeDB does not cascade and its `@cascade` annotation is still "planned… not
   yet available" after years. AtomSpace offers only "silently fail" or "cascade
   possibly catastrophically."
2. **Well-foundedness.** The DAG constraint is load-bearing; cycles in the
   incidence structure violate the axiom of foundation. Confirmed independently
   by four literatures. **An edge-to-edge design must be acyclic *in the
   incidence relation*, and must say so and enforce it** — which TAP currently
   does not, anywhere.
3. **Every existing traversal assumes endpoints are nodes.** This is the mundane
   one and probably the expensive one. `tap_grid/orm_compiler.py:86` literally
   starts with `Entity.objects.exclude(entity_type="edge")` (**READ**). The GRIFT
   subgraph builder "Skips `entity_type='edge'` (edges are resolved separately)."
   Gryphon's chain machinery, the envelope builder, the viz layer and the cascade
   corpus all rest on the same assumption. **Relaxing the rule is four lines in
   the service layer and an unknown number of lines everywhere else**, and the
   unknown number is the real estimate.

### Third, and decisively: does TAP actually need it?

Here is where the four-questions decomposition pays off.

The June notes' argument for edge-to-edge is a single sentence: "If a path step
needs to include both the node and the edge traversed from that node, the path
must be able to point at edges as path participants."

**That requirement is generated entirely by the discovered-path model.** A
recorded walk must name the edges it traversed — §II.1 proved this rigorously
(multi-edges mean a node list does not determine a path; G-CORE's `δ` maps into
`N ∪ E` for exactly this reason). If TAP stores walks, it must point at edges.
No way around it.

**But a *declared* path does not record a traversal.** Under the July 2026
ruling, a named path is a declaration — "the containment closure rooted at
account X," "everything on the `structural: containment` edge class reachable
from here" — and membership is a *predicate over edge classes*, not a list of
edge instances. **A declaration selects edges by class; it does not need to point
at them individually.**

So:

> **The edge-to-edge requirement is an artefact of the discovered-path model, and
> the July ruling dissolves it.** The two decisions the June notes bundled
> together turn out to be the same decision seen twice: choose declared paths and
> the edge-to-edge question does not arise in v0.

I want to be careful not to overclaim. Two genuine residual needs survive:

- **Path breakage must name the edge that broke.** But "which edge broke" is a
  *query result*, not a stored relationship. The stored thing is the declaration;
  the broken edge is found by evaluating it.
- **Provenance on membership.** §II.6 and §II.5 both argue hard for per-membership
  provenance — GO's evidence codes, OmniPath's `consensus_score`. But that is a
  property *of the membership relation*, not a requirement to point at an edge:
  it lives on the membership edge itself, which already has `properties` and
  a backing `Entity` with FLIP.

### Fourth: if it is ever needed, what is the honest design?

Because "not in v0" is not the same as "never," and the June notes are right that
the door should not be closed.

**The depth question is the right frame** (§II.3). Depth 0 is arity. Depth 1 is
"annotate an edge; the annotation's targets are nodes" — RDF 1.2 reifiers,
Wikidata qualifiers, StarE, every property-graph engine's edge properties.
Depth *k* is edges about edges about edges — AtomSpace, ubergraphs, TypeDB
nested relations, HyperGraphDB, **and every project in that list is dead,
archived, or shipping the feature with a "use with caution" warning and no
cascade support.**

**TAP needs depth 1. A `HAS_STEP` edge from a path node to an edge entity is
depth 1**: the edge-with-an-edge-endpoint's *other* endpoint is a node (the path),
and nothing points at `HAS_STEP` in turn. So the honest fence is:

- **Only declared path-step edge types may have an edge endpoint.** Not a general
  relaxation. `req-grid-edge-nono` becomes `req-grid-edge-nono` *plus a named,
  enumerated exception*, exactly as the June notes proposed — "a narrow,
  well-specified exception."
- **Depth 1 only, enforced.** An edge whose endpoint is an edge may not itself be
  the endpoint of another edge. That is the ubergraph DAG constraint reduced to
  its cheapest enforceable form: a depth cap of one, checked in the same four
  lines that currently refuse everything.
- **Cascade semantics decided before the first row.** HyperGraphDB and TypeDB
  disagree, and TypeDB shipped without an answer and is still paying. TAP's
  answer is nearly forced by its own invariant: `req-grid-service-delete-tombstone-7`
  says at no committed state may a live edge have a tombstoned endpoint, and
  `Edge.live_onto_tombstones()` checks `from_entity__deleted_at` /
  `to_entity__deleted_at` **without reference to entity type** (**READ**). **The
  existing invariant already covers edge endpoints correctly, because it was
  written against `Entity` rather than against node-ness.** So the cascade must
  tombstone a `HAS_STEP` edge when its target edge is tombstoned — which is what
  the incident-edge pass already does, for the same reason. **INFERRED, and worth
  a one-hour spike to confirm: the deletion machinery probably already works,
  and the cost is a new cascade-corpus family rather than a new subsystem.**

That is a genuinely cheap exception, and it is cheap *because* of decisions TAP
already made. But it should still not be taken in v0, for the reason above: the
requirement that motivates it does not exist yet.

### Fifth: is reification the honest alternative, and what is lost?

The standard workaround — promote the edge to a node, hang two edges off it — is
one move under many names: Neo4j's intermediate node, TinkerPop's literal vertex,
RDF's reification quad, Wikidata's statement node.

Its cost is uniform and quantifiable (**INFERRED**, §II.3): +1 node and +1 edge
per reified relationship; **traversal depth doubles**, so a *k*-hop query becomes
2*k*; and the edge *type* is demoted from a first-class, indexable relationship
type matchable by `-[:TYPE]->` to a node label plus two generic edge types.

Its benefit is that identity is *gained*.

**For TAP specifically, reification is a bad trade and I would reject it**, for a
reason that is TAP-specific and decisive: **TAP's edges already have identity.**
The entire point of the reification manoeuvre is to give a relationship a node so
it can be pointed at. TAP's relationships *already have an `Entity` row*. Paying
the reification tax — a second node, doubled depth, a demoted type — to acquire a
property you already possess is simply waste. **TAP is in the one position where
the standard workaround is strictly worse than the thing it works around.**

That is worth stating plainly because it inverts the usual advice, and the usual
advice is right for everyone whose edges are not entities.

### Sixth: the hybrid, and why it is the shape to build

The brief asks whether "a path node with ordered membership edges carrying an
index" gets most of the benefit with none of the substrate surgery. **Yes, and
more cleanly than the question implies**, because the prior art has already
worked out what such a thing should look like.

- **Membership and ordering are two properties** (BioPAX's rule; Reactome's
  implementation). Membership is the one that must exist; ordering is optional and
  should be *absent* rather than *empty* when not known.
- **The index is a property on the membership edge**, which TAP already supports
  — `Edge.properties` is a JSONField with a registered per-type schema and
  validation on every save (**READ**).
- **Duplicates must not collapse**, which rules out modelling membership as a set
  or a dimension. SBML Groups' failure mode — "this is equivalent to including it
  just once," silently making loops unrepresentable — is the exact trap, and TAP's
  multigraph edges avoid it natively.
- **Steps are owned, not shared** (BioPAX's `UtilityClass` warning). One path's
  step is not another path's step, even if they describe the same hop.
- **The member type should be the supertype of {path, step}** so nesting is free
  (Reactome's `Event`, BioPAX's `pathwayComponent`). TAP is already there:
  everything is an `Entity`.

And the thing that makes it a hybrid rather than a compromise: **membership edges
can point at nodes today and at edges tomorrow, with no change to the path model
at all** — because the endpoint type is the only thing that differs, and the
substrate does not care. **The hybrid does not close the edge-to-edge door; it
makes the door a four-line change in one file.**

## III.4 The alternatives, fairly stated

Five candidates. Each gets a fair hearing before the ranking, because the
ranking is only worth something if the losers were genuinely considered.

### A. Pure query-time paths — no persistence at all

*What it is:* Gryphon grows variable-length traversal and path binding (tap#259),
returns paths as values, and TAP stores nothing. The SPARQL / OpenTelemetry /
Cartography answer.

*For it.* It is what everybody does, and Movement II establishes that in at least
two cases (SPARQL, Gremlin) the reasons are sound rather than lazy. It has no
staleness problem because there is nothing to go stale. It has no identity
problem because nothing needs a name. It has no invalidation problem, no
cache-coherence problem, no write amplification. It is the only option with a
zero-line data model. And the theory says the expensive part — deciding whether
even one simple path or trail matching a pattern exists — is NP-complete
regardless, so persisting the answer does not make the question cheaper the *next*
time the graph moves.

*Against it.* Three things, and the third is the killer for TAP specifically.
It does not exist: Gryphon has neither variable-length traversal nor path binding
today, both are refused at the dispatch fork, and tap#259 is open and unscheduled.
It is the *heaviest* item on the Gryphon wishlist — a recursive-CTE composition
against a JOIN-based executor, described in TAP's own documents as "the heaviest
engineering item in the wishlist by a meaningful margin." And **the July 2026
ruling explicitly took it off the road**, on the grounds that declared membership
serves the demand more cheaply.

*Verdict.* A legitimate design that TAP has already ruled against for good
reasons, and which would take longest to build. But note the asymmetry it
creates: **without it there is no second opinion.** Everything else in this list
loses the ability to check a stored answer against a freshly computed one, and
Issue# 499's differential-oracle discipline exists precisely to manufacture a
substitute.

### B. Materialised-view paths

*What it is:* precompute hot traversals into a table or a Postgres materialised
view; refresh on a schedule or on write.

*For it.* Read performance. `docs/misc/graph-lookup-performance-notes.md` already
names materialised paths as the third pillar of the scaling argument, and the
formal names — transitive-closure table, path reification — are well established.
Postgres gives you `CYCLE … SET is_cycle USING path` for free, which accumulates
the visited-node array as you go.

*Against it.* Four things. **Postgres has no incremental refresh** — "REFRESH
MATERIALIZED VIEW completely replaces the contents… The old contents are
discarded" — so every retraction costs a full rebuild, which is precisely what
BloodHound does with `DeleteTransitEdges` and precisely why it is a batch job
rather than a live feature. **A view cannot be pointed at**: nothing can draw an
edge to a row in a materialised view, so tagging, protection, permissions,
provenance and "paths on paths" are all unavailable. **It is invisible to GRIFT**,
so a materialised path cannot cross a grid boundary. And TAP's own performance
note already banks the deferred cost: "every materialized path is a **cache that
must be invalidated** when an edge on it mutates."

*Verdict.* A performance technique, not a data model. It has a real place —
underneath something else, as an optimisation, once there is something to
optimise. It is not a candidate for what a path *is*.

### C. Embedded path membership on `Entity` (June's Candidate 2)

*What it is:* an `Entity.paths` JSON field recording which paths an entity
participates in and where.

*For it.* This is the option with the most momentum behind it: it is Issue# 499's
ruled plan, it is §5.1 of the feature-demand study's tier 2, and its performance
argument is genuinely strong — membership becomes a GIN-indexable JSONB query on
the spine, with no join to typed tables, exactly as dimensions are today. For the
cascade use case it is close to ideal: the service layer can consult membership
during an ordinary mutation without traversing anything.

*Against it.* Three real problems and one that is almost fatal. **It is a cache
with no stated coherence rule** — Movement I's open question 5, still open, and an
unanswered cache-coherence question is a bug generator. **It recreates tap#322 at
the path layer**: membership changing as a side-effect of ordinary writes means
`Entity.version` bumps and history rows on every collector pass that moves a
membership, across many entities per path. **It cannot carry ordering without
becoming a junk drawer** — the June notes worried about this themselves ("How does
this avoid becoming a junk drawer for rich path semantics that should instead be
nodes?"). And the near-fatal one: **the spine is the hottest table in the system**,
every query pays for its width, and Movement II has a direct precedent —
Kubernetes put per-field provenance on the shared header and got "over half of a
640-line object," a hide-by-default fix in kubectl, and an open item to compress
field names (**READ**, cited in TAP's own `doc-grid-provenance-placement-prior-art.md`).

*Verdict.* A strong optimisation for one use case (cascade), a poor general model.
Note that it is not exclusive with a path node — Issue# 499 explicitly pairs
them — and that its own justification is a *performance* argument, which is the
right way to think about it.

### D. Path templates that are persistent while instances are not

*What it is:* the grid stores path *types* — declarations, with names, owners,
dimensions, tags and an edge-class predicate — and never stores the instances.
"What is on path P right now" is evaluated on read. KEGG's `map00010` without the
`hsa00010`; WINGS' template without the run; BPMN's definition without the
instance.

*For it.* **This is the option Movement II endorses most strongly and from the
most directions.** It supplies identity from the declaration, which is the
constraint every tradition named (§II.9 convergence 2 and 3, seven traditions).
It has no cardinality problem, because the number of declarations is human-scale
while the number of instances is not. It has no retraction problem, because
nothing derived is stored. It matches TAP's own `trace-overlay` ruling — the grid
holds the map, not the journeys — and its own dual-existence pattern. And WINGS
measured that "**most of the queries of the First Provenance Challenge can be
answered using information that is available… before the execution of the
workflow begins**."

*Against it.* Two honest costs. **It does not answer "what was true last
Tuesday"** — a declaration plus today's graph gives you today's answer, and
history reconstruction is a separate (and already-backlogged) problem. And **it
requires evaluation on read**, which means the read path needs *something* to
evaluate with. If that something is variable-length traversal, we are back to
option A's dependency; if it is an edge-class membership filter, we are not.
**Which is exactly why the July ruling's edge-classification question (Movement I,
open question 2) is the highest-leverage decision in the whole capability.**

*Verdict.* The strongest single option, and the one the prior art votes for.

### E. The hybrid: a path node with ordered membership edges

*What it is:* a path node with an identity, plus `HAS_STEP` edges to its
participants carrying an index and per-membership provenance in `properties`.
June's Candidate 1, minus the edge-to-edge requirement.

*For it.* Everything in §III.1. Plus: it is the *materialisation form* that
option D needs when it materialises anything at all, so the two compose rather
than compete.

*Against it.* Everything in §III.2, and in particular the cardinality objection
if it is used for instances rather than types. **The hybrid is a good
representation and a bad policy**: it says nothing about *what* gets
materialised, and applied without a policy it is the design that stores a billion
paths.

## III.5 RECOMMENDATION

Here is my opinion, stated as plainly as I can make it.

> **Build the path as a node. Give it identity from its declaration, not from a
> computation. Store path *types*, not path *instances*. Use ordered membership
> edges when — and only when — a concrete answer needs materialising, with the
> index and the provenance as edge properties. Do not relax `req-grid-edge-nono`
> in v0, because the requirement that motivates it does not yet exist. And make
> `Entity.version` the staleness signal, because it is the one advantage nobody
> else in the field has.**

In slightly more operational terms, four rulings:

**1. A `Path` is a `BaseModel` with `ENTITY_TYPE = "path"`.** Assigned uuid7,
`KEYLESS` with a stated reason, dimensions, history, tombstone, FLIP — everything
the spine already gives. It serialises through GRIFT with no format change, which
is a verified fact and not a hope. Two identifiers are issued, per Reactome:
**the bare id floats** (it is what everything links to) and **`version` pins**
(it is what diffs). Never one without the other.

**2. Identity comes from the declaration.** A `Path` names an *intent* — "the
containment closure rooted at this account," "the deploy path for this service"
— and its membership is a **predicate over edge classes**, not a list of edge
instances. The route is what the declaration currently resolves to. This is RFC
9256's `<headend, colour, endpoint>`, BPMN's process definition, WINGS' template,
KEGG's reference map and git's annotated tag, arrived at by seven traditions
independently, and it is the only answer to the identity constraint that anybody
found.

Practically, this makes Movement I's open question 2 — *where does the
declaration live?* — the first thing the spec pass must settle, and I would settle
it the way the July note wanted: **an edge classification, not a slug list.**
Steampipe's 289 hand-written edge definitions are the visible cost of the
alternative. And there is a cheap implementation available that nobody has
noticed: **edge types already declare `default_dimensions`, which land on the
edge's backing `Entity`, which carries a GIN index.** A `structural: containment`
classification could be a *dimension on the edge*, selectable by an indexed
containment query, requiring no model change at all (**READ**, verified in
`Edge.save()` and `spec-grid-dimension.md`; **INFERRED** that this is sufficient,
and it deserves a spike rather than my confidence).

**3. Store types; do not store instances.** This is the ruling that does the most
work and the one most likely to be argued with, so here is the case in one place.
TAP has already made it once, in a neighbouring domain: *the grid holds the map,
Jaeger holds the journeys, and the join is computed at view time, never persisted*
(`trace-overlay-on-system-model-seam.md`, **READ**). Movement II says the same
thing from six directions: cardinality is untouched by any substrate feature;
every execution system bounds and ages its instance evidence while versioning its
definitions; Temporal caps a path instance at 51,200 events and warns at 10,240;
Camunda makes instance-history depth a per-deployment dial with a TTL. **A path
type is stable, low-cardinality, named, owned, and belongs on the grid. A path
instance is high-cardinality, ephemeral evidence, and does not.**

Where a concrete route genuinely must be preserved — an incident chain, a
compliance argument, a specific build's lineage — **materialise it deliberately,
as an ordinary path node with `HAS_STEP` edges, as an act rather than a policy.**
A handful of these is fine. A pipeline that generates them is the billion-path
design.

**4. Staleness is an indexed comparison, not a timer and not a re-walk.** Every
system in Movement II answers "is this still true?" with a timer (BloodHound's
TTLs, RSVP's soft state, Reactome's six-month decay) or a full recompute. **TAP
can answer it with a comparison**, because every entity carries a monotonic
`version` and a `deleted_at`, both indexed, both written on every canonical
mutation. A materialised path records the versions it was built from; it is
*suspect* the moment any of them moves; it is *broken* when any of them
tombstones. That is RFC 9256's validate-the-first-SID trick in a stronger form
than a router can manage, and **it is the single thing TAP can do that nobody
else in this dossier can.**

Two corollaries. **Report the answer as an alignment, not a boolean** — which
members moved, which vanished, and a fitness scalar — because §II.8 shows the
boolean is the wrong product and the itemised diff is the right one. And **let
confidence decay by default**, per Reactome's three-star rule, so a path nobody
has re-evaluated visibly loses standing without anyone having to act.

### Four things to do that are not the main ruling

- **Move path breakage off the Flaw surface.** A user deleting an EC2 instance
  that a named path runs through is *correct operation*, and `spec-tap-flaw-v0.md`
  says a Flaw that can fire during correct operation is miscategorised. Path
  breakage should be a grid record shaped like `grid__cascade_failure`
  (Issue# 668, Issue# 659), not a Flaw.
- **Do not invent a dotted branch/loop notation.** No tradition in Movement II
  encodes structure in a string; GQL uses group variables, G-CORE uses a list over
  `N ∪ E`, Gremlin uses labelled slots, BioPAX uses `nextStep`. Ordered membership
  edges carry branch and loop structure natively.
- **Adopt GQL's vocabulary verbatim** — WALK / TRAIL / SIMPLE / ACYCLIC as
  restrictors, ANY / ALL SHORTEST / SHORTEST k as selectors. It is ISO-standard
  and inventing TAP words for it is exactly the "confusing private notation" the
  June notes warned against.
- **Write the lifecycle before the first row.** Reactome's seven deletion reasons
  with `replacementInstances` at cardinality `+`, and GO's `replaced_by` versus
  `consider` successor-confidence distinction. Both are cheap. Both are missing
  from almost every system surveyed. And `req-grid-dual-existence-teardown` is
  already Backlog asking the same question for plugin-declared capabilities.

### What would have to be true for this to be wrong

A recommendation without falsifiers is an opinion wearing a hat. Here are the
specific things that would overturn each part of it.

**The declared-path ruling is wrong if TAP's real demand is for discovered
paths.** The test is concrete: go to the vuln-triage methodology and the
`git-serious` build/deploy views — the two things Issue# 141 says path primitives
gate — and ask whether the paths people actually want are ones a human would
*declare* or ones the system must *find*. If practitioners describe their work as
"show me every route from the internet to this bucket," that is discovery, the
identity problem returns in full, and options A and E move up. If they describe it
as "these are our three critical paths, tell me when one breaks," the declaration
is the identity and this recommendation holds. **I have not run that test and
nobody should take my ruling over its result.**

**The "types not instances" ruling is wrong if the instances are few and
precious.** The whole cardinality argument assumes many cheap instances. If TAP's
real case is a dozen incident chains a year, each of which somebody will want to
cite in a report five years later, then instances are the product and the argument
collapses. The number that decides it is *expected materialised paths per month*,
and if it is under about a hundred, ignore me.

**The edge-to-edge deferral is wrong if a v0 use case needs to name a specific
edge instance, not an edge class.** The one I can construct is multi-edge
disambiguation: if two `RUNS_ON` edges exist between the same pair with different
`properties` and a path must distinguish them, a class predicate cannot, and
pointing at the edge becomes necessary. **If that case is real today, the
exception should ship in v0** — and the good news is that §III.3 argues it is
cheap, bounded and probably already handled by the existing tombstone invariant.

**The staleness mechanism is wrong if `Entity.version` is too noisy.** The whole
scheme rests on a version bump meaning something. If re-observation bumps versions
in practice — the tap#322 shape — then every path is permanently "suspect" and the
signal is worthless. **tap#322's resolution is therefore a hard prerequisite, not
an adjacent concern**, and I would treat "re-observation does not bump version" as
a gate on the path work rather than a nice-to-have.

**And the whole thing is wrong if paths turn out to be decoration.** §II.6's
measured finding is that two of seven topology-based methods stored the graph and
produced identical answers with it removed. The test transfers directly: **once
TAP has paths, randomise their ordering and see whether any answer changes.** If
nothing does, the ordering is decoration, membership was the whole product, and
the right design was a dimension all along.

### A closing note on the shape of the thing

The June notes ask whether paths make TAP's compact self-description true — that
it maps the Tao. I think they do, but not quite in the way the notes imagined,
and the difference is worth a sentence.

Vannevar Bush's trail was an *authored* object. A trailblazer made it, annotated
it, and passed it to a colleague, who linked it into their own. It was never a
search result. Eighty-one years of hypertext, three attempts at guided tours, four
RDF reification designs, two ISO standards and thirty years of curated biology
all converge on the same unglamorous finding: **the durable thing is the one
somebody meant, and the computed thing is the one that tells you whether they
still get to mean it.**

A path that TAP discovers is a fact about the graph this morning. A path that
somebody *declares* is a claim about how the organisation believes it works — and
the useful, sellable, alarming thing is the gap between the two. That gap has a
name in three different literatures (conformance, drift, reconvergence), it is
measurable, it is what a persistent path is *for*, and it is precisely what you
cannot compute if you only ever stored one side of it.

Which is, on reflection, a rather Taoist result: the map is not the way, the
walking is not the way, and what TAP would actually be selling is the distance
between them.


---

# Appendix: what could not be verified

A research document that hides its holes is worse than a short one. Everything
below is a lead, not a fact, and nothing in the recommendation rests on any of
it. Items are grouped by how much it would matter if they turned out otherwise.

### Would change an argument

- **Saha, "Extending Logical Attack Graphs for Efficient Vulnerability
  Analysis," ACM CCS 2008**, DOI [10.1145/1455770.1455780](https://dl.acm.org/doi/10.1145/1455770.1455780).
  Described in a 2023 survey as presenting a method to *incrementally* re-generate
  logical attack graphs. **Paywalled; not read.** This is the single most on-point
  academic citation for a persistent-path design, and §II.4's claim that
  incremental maintenance is essentially unused rests on not having read it. Read
  the primary before relying on anything I said about it.
- **Whether SQL/PGQ's `GRAPH_TABLE … COLUMNS` clause can yield a path-typed
  column.** ISO 9075-16 is paywalled. My reading (no, because SQL has no PATH
  type) is **INFERRED** and is the one unresolved comparison in §II.1.
- **ArangoDB edge-as-endpoint.** Documented as possible ("Edges can technically
  also be used as vertices but the usefulness is limited") and **never observed**.
  One cheap experiment — insert an edge whose `_from` is an edge handle, then
  traverse through it — would settle whether *any* production system really does
  this. Worth an hour.
- **Whether TAP's existing delete cascade already handles an edge endpoint
  correctly.** §III.3 argues it probably does, because `live_onto_tombstones()`
  and the incident-edge pass are written against `Entity` rather than against
  node-ness. **INFERRED from reading, not run.** A one-hour spike settles it and
  it materially changes the cost estimate for the edge-to-edge exception.

### Would change a citation but not a conclusion

- **ISO/IEC 39075:2024 (GQL) and 9075-16:2023 (SQL/PGQ)** are paywalled and 403
  to an unauthenticated fetch. Every standards claim rests on the committee
  members' own published formal models plus Oracle's conformant manual.
- **Davidson & Freire, SIGMOD 2008** — bibliographic record confirmed, content
  not. Do not attribute the prospective/retrospective definitions to it; Freire
  et al., CISE 2008 carries that load and is verified verbatim.
- **Ammann, Wijesekera & Kaushik, CCS 2002** (monotonicity) — read only through
  three secondary accounts, all consistent.
- **Arenas, Conca & Pérez's exact figures** ("yottabyte," double-exponential) —
  abstracts and summaries, not the paper body. The causal link to the SPARQL WG's
  decision is **INFERRED** from chronology plus the WG's own wording.
- **Halasz's seven issues** — four confirmed by name via a secondary source; my
  recollection that "virtual structures" is among them is **UNVERIFIED** (ACM
  403s). Trigg 1988 and Zellweger 1989 are confirmed bibliographically via
  Crossref; their bodies are unread.
- **Bagan/Bonifati/Groz trichotomy** and **Martens/Niewerth/Trautner trail
  trichotomy** — read as summaries and dblp records.
- **Petri-net unfoldings, McMillan cut-off events, ERV** — search-index summaries
  of pages not fetched. The idea is well attested; the wording is not mine to
  quote.
- **Alignment complexity as PSPACE-complete on safe workflow nets** — appeared in
  summaries, not in the pages read. What *is* certain from primary text: it is A\*
  over a synchronised product, and it costs seconds to minutes per log.
- **van der Aalst's enumerated DFG limitations** — the citation, venue and
  abstract are confirmed; the enumerated pitfalls are from the search index
  because three hosts refused the full text.
- **Amazon Neptune's lack of RDF-star support** — from a dated AWS re:Post
  answer; the FAQ is silent, which is not a denial.
- **Dgraph's "facets are not first-class citizens"** — quoted everywhere, not
  findable in a live primary source.
- **KEGG subscription prices, KegSketch, Reactome orthology success rates,
  PANTHER-versus-Compara** — search snippets. Reactome's own documentation says
  PANTHER; treat Compara as historical or wrong.
- **Wadi et al., "Impact of outdated gene annotations on pathway enrichment
  analysis," Nat Methods 2016** — paywalled behind an IdP. The *Briefings in
  Bioinformatics* 2022 review is the safe substitute and is verified.
- **WikiPathways' classic curation-tier definitions** — the portal 404s and
  archive.org was unreachable. That the tiers evaporated is **INFERRED** from
  their absence in the 2024 paper and the new browse surface.
- **The end-to-end argument** (Saltzer, Reed & Clark 1984) — citation located,
  body not read this pass.
- **The "order of magnitude reduction in router state"** figure often attached to
  Segment Routing — appeared only in a search summary and **not** in the pages of
  the GLOBECOM paper that were read. **Do not quote it.**

### Searched for and not found (negative results, stated as such)

- **Any rationale in Neo4j's documentation for why a path is not storable**,
  beyond the type taxonomy itself.
- **Any implementation of G-CORE's stored paths**, production or prototype.
- **Any vendor's published bill for persistent-path staleness.**
- **Any benchmark isolating nested relations in TypeDB**, or comparing
  edge-to-edge against reified-node anywhere.
- **Any per-path freshness display** in any attack-path product surveyed.
- **Any cross-release identity guarantee for pathways** in Pathway Commons —
  entities have one, paths do not, and the absence is the finding.
- **Mailing-list archaeology** on why RDF reification was abandoned (the
  Hayes/Beckett/DuCharme threads) — not done; the session's web-search budget was
  exhausted. One unfetched lead:
  [Lassila, public-rdf-star-wg, 2024-04-08](https://lists.w3.org/Archives/Public/public-rdf-star-wg/2024Apr/0019.html).

### Method note

This dossier was assembled from the worktree at
`/Users/george/tap-sessions/demo-dev` on branch `feat/736-export-grift`, plus six
parallel research streams against primary sources on the open web. The session's
web-search budget (200 calls) was exhausted partway through; the later work was
done by direct fetch against known URLs, by the GitHub and Crossref APIs, and by
converting fetched PDFs locally. Several sources were read as source code rather
than documentation, and are labelled **READ (source)** where that matters — in
particular the BloodHound findings in §II.4, which contradict the vendor's own
documentation in two places and were the most valuable half-hour of the exercise.

**Nothing described here is built. There is no code, no migration, no spec change
and no scheduled work. This is a thinking document, and the specs remain canon.**
