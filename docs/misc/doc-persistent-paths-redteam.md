# Red Team: Persistent Paths as First-Class Grid Nodes

**Adversarial pass, 2026-09-21.** Target: `docs/misc/grid-native-paths-notes.md` §"Candidate
Representation 1: Persistent Path Nodes", and the strategic claim in
`docs/misc/doc-gryphon-feature-demand.md` §5.1 that named paths *replace* reachability traversal.

Produced independently of the constructive dossier. Every claim is labelled **READ** (observed at
the cited file/line), **RAN** (executed), or **INFERRED** (reasoning over what was read). I ran no
TAP code, so every performance statement here is READ-from-a-document or INFERRED from indexes and
query shape — never measured.

**On BloodHound.** The brief originally asked me to use "BloodHound computes paths at query time" as
evidence against persistence. That line was struck mid-task as an appeal to authority, correctly, and
George's objection — that BloodHound has not built a falsification mechanism, so query-time is forced
on them rather than chosen — was handed to me as the better framing. **I verified the premise rather
than adopting it, and it needs a correction of its own; see F2.** BloodHound has more observation
machinery than the objection credits it with, which makes the comparison *more* interesting, not
less. It appears in this document as a verified data point about a differently-constrained system,
never as an argument from authority.

---

## Verdict up front

**Path-as-node is the right shape. I pressed on it and it held.** Four of my eight attack lines
failed against the actual substrate. The schema already permits it, GRIFT round-trips a
node-plus-edges structure for free, cardinality is fenced by the roadmap, and the derive-twice
objection was already ruled on (`tap#499`) with a better answer than I was going to propose.

**What the design must be honest about, in order:**

1. **F1 (CONSTRAINT, and the centre of gravity).** A persisted path in TAP *can* be made falsifiable
   — the coordinator is right that TAP has machinery no comparable system has. But **revalidating a
   stored k-step path costs Θ(k), the same order as the thing it replaces.** Persistence therefore
   buys **identity, naming, protection and a stable authorization target**, plus a real but bounded
   saving of the traversal's *branching* factor. It does not buy a new asymptotic class. If the
   feature is sold as "finding a known path does not require re-running a traversal"
   (`grid-native-paths-notes.md:42`) it will underdeliver. If it is sold as identity, it is obviously
   right and cheap to justify.
2. **F2 (FATAL — to a claim, not to the shape).** §5.1's position that named paths *replace*
   variable-length traversal is wrong for TAP's own flagship security use case. Declared membership
   answers "is the route I named still intact". The product question is "what route exists that
   nobody named". Path-as-node must be **additive to** E1, never a substitute.
3. **F3 (CONSTRAINT, the seam I did not expect).** **Reconcile has no grip on a derived path**:
   `req-grid-reconcile-falsifier-1` — *"No falsifier ⇒ not reconcilable ⇒ never retired"* — and a
   derived path has no external source to probe. A materialised path is, under today's rules,
   immortal.

And one recommendation that changes the build: **do not relax "no edges between edges."** Use a
`path_step` node. It is cheaper on this substrate, it is what W3C chose for the same problem, and it
is the only version that survives the tombstone cascade.

---

## What I could NOT verify

- **Any performance claim, mine included.** No benchmark exists in-tree that I found and I ran none.
  The assertion that path queries are slow enough to need persistence is **NOT OBSERVED**. My own
  cost arithmetic in F1 is INFERRED from index definitions and query shape; it is a prediction, not a
  measurement, and the honest next step for anyone who believes the speed argument is to measure it.
- **Whether dimension scoping is actually applied to Gryphon reads.** Specs assert it
  (`spec-grid-traversal-execution.md:279`, `:314`); a grep of `tap_grid/gryphon/executor.py` found
  only field-path resolution hits, no scoping filter. Possible spec-vs-code divergence, and it is
  load-bearing for F9.
- **BloodHound's retirement behaviour, negatively.** I searched their source for pruning of unseen
  nodes/edges and found none (details in F2), but a code search that finds nothing is weak evidence —
  I could have searched the wrong names. I state it as a negative result with its limits, not as a
  boundary.
- **The samsite path proof-of-concept** (`plan/product-map.md:219`, `tap#141`). Out of repo; I read
  only its intended shape at `docs/misc/code-core-v0.md:317-330`.

---

# Ranked findings

**FATAL** (the shape is wrong) / **CONSTRAINT** (the shape is fine, but this must be designed for on
day one) / **COST** (accept knowingly).

---

## F1 — A falsifiable path is affordable, and its cost proves persistence is about identity, not speed. CONSTRAINT.

**Confidence: high on the mechanism and the design; medium on the arithmetic, which is INFERRED.**

This is the finding the brief's correction asked for, and I think it is the centre of the whole
question.

### 1a. TAP genuinely can falsify a path. Here is exactly what it would have to record.

TAP's per-row provenance is real and specific (all READ):

- Every `BaseModel` — **and `Edge` is a `BaseModel`** — carries `batch_id`, *"UUIDv7 of the batch this
  change was included in"*, and `flip_map`, the field-path → batch-id map (`tap_grid/models.py`,
  BaseModel field block).
- `spec-grid-flip.md:57` (READ): a FLIP value is *"the batch that last **set** the current canonical
  value"*.
- `Entity` carries `version` (monotonic), `updated_at`, `deleted_at` (`models.py:297-318`).
- `BatchEvent` is an append-only log with `idx_batchevent_entity_ts` on `(entity_id, timestamp)`
  (`models.py:1510-1522`) — so "what touched entity E, and when" is one indexed range scan.

So a **falsifiable path** is a small, concrete schema:

| Recorded per step | Why |
| --- | --- |
| `node_entity_id` | the participant |
| `edge_entity_id` | **the traversed edge.** Without it there is nothing to revalidate — you cannot tell whether the route between `n4` and `n5` is still the *same* route. This is the real requirement behind "edges to edges". |
| `step_index`, `direction` | order and orientation |
| `observed_batch_id` | the edge's `batch_id` **at capture**. Revalidation is then a column compare, not a log scan. |

Recorded per path: `captured_at`, `verified_at`, `captured_by` (the Search/pathmaker that produced
it), and — the piece nobody has named — **the completeness statement of the run(s) whose observations
the path rests on** (`tap_grid/completeness.py`: `scope_authorized`, `enumeration_complete`,
`source_consistent`, `admitted`, `applied`, `reconcilable`).

Revalidation then has two halves:

- **Intactness:** `Entity.objects.filter(pk__in=[k edge ids]).values("id", "deleted_at")` — one
  PK-range scan returning k rows.
- **Freshness:** compare each edge's current `batch_id` against the stored `observed_batch_id` —
  carried on rows the intactness query already touched.

**Two indexed reads, k rows each.** That is affordable. The coordinator's core claim is correct: the
inherited constraint does not transfer, and TAP can do something a snapshot store cannot.

### 1b. The arithmetic — and why it is the argument against the speed framing

**Revalidating a stored k-step path:** ~2 indexed queries, k rows. `O(k log N)`.

**Recomputing a fixed-shape k-hop path:** one ORM queryset with k reverse-FK joins on
`idx_edge_from_type` (`executor.py:1892-2010`, `_compute_hop_paths` at `:1568-1625`; READ via agent).
Cost is dominated by the intermediate frontier, ~`b^k` before the anchor predicate narrows
(`graph-lookup-performance-notes.md`: per hop `O(log E + k)`, *"the cost that matters is k and
frontier size"*).

So revalidation is **strictly cheaper**, and the saving is real: it converts a pattern match with
unknown branching into k point lookups. **I concede that plainly.**

But notice precisely *what* it saves. It saves **b**, the branching factor. It does not save **k**.
Revalidation touches every edge the path names, so its cost is Θ(path length) — the same order as the
traversal's *output*. Persistence does not move the problem into a cheaper complexity class; it
removes a constant-ish multiplier that `graph-lookup-performance-notes.md` already argues is small on
a sparse graph with supernodes modelled as dimensions.

And on a sparse infra graph — which is the explicit premise of TAP's own performance argument, pillar
1 — `b` is small by construction. **The feature saves the factor that the architecture already
spent three design decisions making small.**

### 1c. The three attacks on the falsifiable-path design

**Attack 1 — revalidation answers the cheap half of the question, and the expensive half is the one
the product sells.**

Checking that path `P` is intact is a *positive* claim about edges you already named. The claim a
security or compliance buyer pays for is the *negative* one: **"there is no path from the internet to
the cardholder database."** A negative path claim cannot be revalidated by checking the edges you
named — it requires checking the edges you *didn't*, which is the full traversal, every time.

Worse, TAP's own evidence model makes the negative claim harder than it looks: a "no path" answer is
only as strong as `enumeration_complete` **and** `scope_authorized` on **every** collector that could
have contributed a relevant edge — and `tap_grid/completeness.py` records completeness **per listing
surface, per run** (READ). There is no composed, cross-collector completeness statement, and
composing one is a real piece of design nobody has scoped.

**Consequence:** a persisted-path system will be systematically strong at "this route is intact" and
systematically weak at "there is no route". Those are the two halves of vuln-triage, and the second
is the half that ranks a finding as *not* critical — the answer with the highest blast radius when
wrong. *Survives.*

**Attack 2 — the freshness signal TAP would pin against is the one surface with an open ruling
against it. This is a hard sequencing dependency and I do not think it is on anyone's list.**

Three facts, all READ:

1. **TAP has no last-seen stamp, deliberately.** `tap_grid/candidates.py:1-8`: retirement candidates
   are derived *"from the grid's own topology, **not from a per-node observation stamp**"*, and
   `:22-27`: the observed set *"is the run's own record **rather than a stamp on the node**"*.
2. **`Entity.version` cannot be used for freshness.** `tap_grid/reconcile.py:411-428` (READ via
   agent) refuses to consult it, with the reason stated in the spec
   (`spec-grid-reconcile.md:313`): *"an unchanged re-observation deliberately may not bump it, so
   optimistic concurrency alone would let a stale absence verdict survive a newer successful
   observation."*
3. **So freshness must come from `batch_id` / `flip_map` / `BatchEvent` — and today the importer
   rewrites `batch_id` and `flip_map` on every pass, changed or not.**
   `docs/misc/doc-grid-reobservation-prior-art.md:24-26` (READ): *"it rewrites the typed row's
   `batch_id` and `flip_map` on every pass, so an unchanged node gains a history version each time —
   ~1,600 nodes × 144 passes/day at a ten-minute schedule."* And `:38`: *"The specs already say
   re-observation is not history. **The importer disagrees with them.**"* This is `tap#322`, **open**.

**Concrete failure scenario.** A path pins `observed_batch_id` for each of its 8 edges. `github_core`
runs on a ten-minute schedule. Nothing in the graph changes. On the next pass every edge's `batch_id`
is rewritten to the new batch. The revalidation compares 8 stored batch ids against 8 new ones and
reports **8 of 8 steps changed → path broken.** Every ten minutes. Forever. The path integrity signal
is 100% false positives on a completely static graph.

The inverse is equally bad and subtler: if you instead pin `Entity.version`, then *after* `tap#322`
lands an unchanged re-observation will not bump version — but neither will some genuine changes that
the ruling's "diff-before-write" logic classifies as no-ops, and you now have false negatives on the
signal that says "your critical path moved".

**So: path revalidation by provenance is wrong before `tap#322` lands and right after it.** That is a
hard ordering dependency between two workstreams that are currently tracked independently, and it
should be stated as one. *Survives, and this is the most actionable finding in the document.*

**Attack 3 — eager invalidation is worse on this substrate than it looks, and lazy invalidation
concedes the performance argument.**

- **Eager** (invalidate on write) requires an edge → paths-containing-it index, which *is*
  Candidate 2 (`Entity.paths`). So **Candidates 1 and 2 are not alternatives: Candidate 1 without
  Candidate 2 is uninvalidatable.** The notes present them as a choice; they are a dependency.
  It also means taking write locks on path rows from inside the node/edge write pipeline — a pipeline
  with a documented lock-order-inversion history. `_impl.py:264-277` (READ via agent) fixed Issue #590
  by imposing one global lock order: *all nodes ascending by id, then all edges ascending by id*.
  Introducing a third row class, touched from inside a delete cascade, is precisely the shape that
  produced the original bug. And a collector landing 10k edges would pay a path-index probe per edge
  inside one transaction.
- **Lazy** (revalidate on read) is correct and cheap per read — but it means the stored path is never
  authoritative. It is a hint, and every consumer (API, panel, GRIFT envelope, AI surface) must
  handle `unverified` from day one. It also concedes F1's headline: **if you revalidate on every
  read, you have not avoided touching the graph; you have only avoided the branching.**
  Note the read shape makes this concrete: `execute_search` pages the envelope **in Python after full
  execution** (`tap_grid/search.py:97-114`, READ via agent), so there is no cheap "top 10 paths"
  short-circuit above it.
- **Never** — the path is documentation. Honest, and possibly correct for an authored path, but then
  say so in the spec rather than discovering it later.

**Recommendation:** lazy revalidation with `verified_at` + `observed_batch_id`, eager **only** for the
containment-closure case where the declaration already tells you which edges matter. And sequence it
behind `tap#322`.

### 1d. Refutation attempt against my own finding

*"You are comparing against a fixed-shape traversal. The real comparison is against a variable-length
traversal (E1), which is `b^k` with a recursive CTE and genuinely expensive — and against that,
revalidation is an enormous win."* — **This is the strongest counter and it half-lands.** It is true
that revalidating a known path beats discovering one. But it makes F2's point for me: the expensive
query is *discovery*, and a persisted path cannot do discovery. You still need E1 to *find* the path
you then cheaply revalidate. Persistence optimises the follow-up, not the question.

*"Identity, naming, tagging and protection are worth it on their own."* — **Agreed, entirely.** That
is my conclusion, not a counter to it. The finding is not "don't build it"; it is "**build it for the
right reason, and write the right reason in the spec**", because a performance justification will set
expectations the implementation cannot meet.

**Survives, as a CONSTRAINT and a framing correction.**

---

## F2 — Named paths cannot substitute for reachability. FATAL (to the §5.1 claim).

**Confidence: high.**

### The objection, on its own merits

`docs/misc/doc-gryphon-feature-demand.md:304-332` (READ) records the current position:

> "the **planned implementation replaces reachability-by-traversal with reachability-by-declared-path
> membership** … 'what is reachable' collapses into 'select the elements on named path *P*' — an
> indexed membership filter, not a query-time graph walk."
>
> "var-length `-[*n..m]-` stays parse-but-reject (fail-closed) and is *not* on the near-term path;
> the reachability demand it represents is met by the named-path primitive instead."

Declared membership answers *"is the route I already named still intact?"* Reachability answers
*"what routes exist?"* The second cannot be derived from the first, and no amount of falsification
machinery changes that: falsification tells you whether a recorded fact is still true; it cannot tell
you about a fact you never recorded.

### Concrete failure scenario

`plan/product-map.md:218-219` (READ): `vuln-triage` is *"severity ranking against critical paths in a
cloud service. Requires the path primitives in TAP."*

- An operator declares `P-payments`: `alb → ecs_service → task → rds`.
- A collector later lands `lambda_reporting --ASSUMES_ROLE--> role_payments_rw` and
  `role_payments_rw --GRANTS--> rds`. Nobody declares a path through it, because nobody knew it was
  there — that is the premise of infrastructure discovery.
- A CVE lands on `lambda_reporting`. *Does this touch the payment path?*
- **Membership filter: no.** `lambda_reporting` is on no declared path. Fast, indexed, confident,
  wrong. Under `-[*1..4]->` the answer is yes, in one query.

This is the failure class TAP names and forbids elsewhere: `spec-grid-reconcile.md:7` (READ) —
*"Absence of evidence must never render as evidence of absence."* A membership-only reachability
answer is that rule violated at the query layer.

### Refutation attempt

1. *"The NetworkX analytics backend covers it."* — `doc-gryphon-networkx-opportunity.md` §1 (READ via
   agent): *"Gryphon selects the subgraph (its strength), NetworkX computes over it (its strength)."*
   **Selecting the subgraph is the part that needs var-length.** §5.1 itself scopes the backend to
   `shortestPath` / least-cost / centrality as *"a separate concern"*. Does not close it.
2. *"Path types are model-declared, so a plugin author declares the trajectory once and every instance
   is covered."* — §5.1 implementation 1 declares *patterns*, not instances, so the
   `ASSUMES_ROLE·GRANTS` route is covered **if someone declared that sequence**. That relocates the
   problem to "enumerate every dangerous edge-type sequence in advance", which is the thing nobody
   can do. Half-lands at best.
3. *"TAP's customer names their own critical paths."* — True for *ranking against* a path. False for
   *deciding whether a finding reaches* one, which is the prior question.

**Survives.** Not fatal to path-as-node — fatal to the claim that path-as-node lets TAP skip E1.
Those must be decoupled explicitly, because §5.1 currently reads as a commitment to cancel E1.

**Note the internal tension in §5.1's own evidence base.** It cites the corpus study to justify not
building E1. That study's §4 finding (`:228-235`, READ) is that E1 demand is **highest precisely in
TAP's neighbourhood** — *"Security asset-graph corpora … are disproportionately heavy on var-length
paths and `shortestPath`"*. The doc reaches the opposite conclusion from its own strongest data point.

### BloodHound: the premise, verified — and corrected

The brief's struck line assumed BloodHound lacks observation semantics. **I checked, and it has more
than the objection credits.** All READ, from their source and docs:

- `packages/go/graphschema/common/common.go` defines, as standard node/edge properties:
  **`firstseen`, `lastseen`, `lastcollected`, `collected`** — alongside `objectid`, `system_tags`,
  `user_tags`. So BloodHound *does* carry per-fact observation timestamps.
  Their edge documentation confirms it at the user-facing level: every edge's standard properties are
  *"Source Node, Target Node, **Last Seen by BloodHound**"*
  (https://bloodhound.specterops.io/resources/edges/overview).
- `cmd/api/src/daemons/changelog/changelog.go` — a **changelog daemon**, described in its own package
  comment as *"a long-running daemon that manages change deduplication and buffering for graph
  ingestion"*, which skips re-ingestion of unchanged data. **That is `tap#322` — "re-observation is
  not change" — and BloodHound has shipped it while TAP has it open.**

**What I could not find** (negative result, stated with its limits): any mechanism that retires or
tombstones graph objects no longer observed. `cmd/api/src/daemons/datapipe/pipeline.go` (READ) has
`PruneData`, but its own comment scopes it to *ingest files* — *"we get a list of all filenames we
know/expect and delete any other files"* — and `OrphanFileSweeper` is likewise about storage, not the
graph. `DeleteCollectedGraphData` runs behind an explicit user `deleteRequest`. A code search for
`DeleteOrphanedNodes` / `PruneOrphanedNodes` returned **0 results** (RAN, `gh api search/code`). I did
not find retirement; I cannot prove it is absent, and I searched a limited set of names.

**So the corrected reading, and it is more useful than either the original brief or the objection:**

> BloodHound has **staleness**, not **falsification**. `lastseen` tells you the *age of the evidence*;
> without retirement it can never tell you the edge is *false*. A persisted path there could be
> flagged **old**, never **broken**.

That is a real, inherited constraint — but it is one notch further in than "no observation semantics",
and it matters, because `lastseen` alone is arguably *enough* to revalidate a stored path lazily
(`min(lastseen)` over its edges is the path's freshness). **BloodHound has that ingredient and still
does not persist paths.** Which means the question "why not?" is not answered by "they couldn't", and
I cannot answer it from the outside without speculating — so I will not. What I will say is the thing
that *is* grounded: their choice is not evidence against TAP's design, and the argument in F2 stands
on the discovery-vs-membership logic alone, with or without them.

The one external fact I will lean on, because it is a specification rather than a vendor's choice:
Neo4j's Cypher manual (fetched) states that `PATH` is a **structural type** and *"Structural types
cannot be stored as properties."* That is a language-design constraint, not a product decision, and it
is why TAP building its own store genuinely does open a door that is closed elsewhere.

---

## F3 — Reconcile cannot retire a path: a derived path has no falsifier. CONSTRAINT.

**Confidence: high. The seam I did not expect to find.**

### The objection

TAP's retirement machinery is an evidence pipeline, not "delete when gone"
(`tap_grid/specs/spec-grid-reconcile.md`, `candidates.py`, `falsifiers.py`, `reconcile.py`; READ via
agent):

- **Candidates:** `children(P,R) − observed(run) − outside_scope(run)`, where `children` comes from
  declared `CONTAINMENT_EDGES`. *"A relation the model does not declare as containment is a reference
  and yields nothing"* (`candidates.py`, AC `-5`).
- **Falsifier:** `falsifiers.py:34-36` — *"A type with no registered falsifier is **not
  reconcilable**: its candidates are recorded as not re-observed and are never probed or retired."*
  A falsifier **probes the source**, comparing stable source identity and current owner. *"HTTP
  success is not a verdict"* (`:40`).

Both legs assume an **external source of truth**. A materialised path has none — its only source is
the grid, which is the thing being reconciled. The only `batch_falsify` you could write for a path
re-runs the traversal, and per F2 that traversal (var-length) is the one §5.1 says is not being built.

### Concrete failure scenario

- `tap#499` step 2 mints closure path `P` for `account-A ⊃ … ⊃ i-0abc`.
- The AWS collector stops seeing `i-0abc`; its falsifier returns `DROPPED_FROM_OBSERVATION`; reconcile
  calls `delete_node(cascade="contained")`.
- The endpoint cascade (`_impl.py:861-889`, READ via agent) gathers **every** edge incident to
  `i-0abc` — including `P`'s step edge — and bulk-tombstones them.
- **`P` is untouched.** It is not a containment child of anything (`_children_of` at `_impl.py:375-385`
  follows only declared `CONTAINMENT_EDGES`), it has no falsifier, and no collector observes it.
- **A live path node with a hole. Permanently.** A reader asking "what paths pass through account-A"
  gets `P`, which presents as a coherent route that no longer exists.
- **Unrepairable in place.** A re-observed `i-0abc` gets a *new* uuid7 (ids assigned, never derived),
  and `_impl.py:596-604` refuses edge creation onto a tombstone with `entity_tombstoned` anyway.
  Retirement is terminal by rule: `spec-grid-reconcile.md:88-93`, *"a source object that becomes
  observable again is a new observation lifetime with a new entity id."*

### Refutation attempt

1. *"Write a falsifier that re-runs the pathmaker."* — Concedes the point: the falsifier **is** the
   traversal, so you pay it on every reconcile and persistence buys nothing on the write side. It also
   requires E1. Circular.
2. *"Declare `HAS_STEP` as a `CONTAINMENT_EDGE`."* — Catastrophic. Containment cascades *downward*, so
   `path --HAS_STEP--> member` as containment means **retiring a path deletes its members**. Deleting
   the "prod payment flow" object would tombstone your RDS instance. The reverse
   (`member --MEMBER_OF_PATH--> path` as containment) is arguably right and worth ruling on, but makes
   every path a cascade amplifier: one instance dying retires a path that ten live things point at.
3. *"Paths are authored, not observed — like `Search`, `Dimension`, `Keystone`, all `KEYLESS` with
   reason 'authored, not observed'."* — **Correct, and it fully defuses the finding for authored
   paths.** It does not defuse it for `tap#499`'s derived closure paths, nor for pathmaker-materialised
   ones.

**Survives, narrowed.** The rule it yields should be canon:

> **An authored path and a derived path are different types.** An authored path is `KEYLESS`, outside
> reconcile, and its breakage is a data state a query reports. A derived path is a cache: it carries
> the query and the batch that produced it, it is **replaced wholesale** on re-derivation rather than
> reconciled, and reconcile is explicitly declared not to apply — because reconcile's evidence model
> has no grip on it.

---

## F4 — The breakage mechanism the notes rely on is the wrong mechanism. CONSTRAINT.

**Confidence: high.**

`grid-native-paths-notes.md:178-198` (READ) bets path integrity on Flaws:

> "The newly spec'd flaws implementation may be a natural way to report path breakage."

Flaws are built — `tap/flaws.py` (393 lines), `specs/spec-tap-flaw-v0.md` — and they are not this.
READ: `specs/spec-security-posture.md:159`, a Flaw is *"a violated guarantee, **steady-state-empty**,
every fire actionable-and-patchable"*. `spec-tap-flaw-v0.md:17` is blunter: ***"If a 'Flaw' can fire
during correct operation, it is miscategorized."*** `tap/flaws.py:82` — `class Flaw(Exception)`,
subclasses `CodeFlaw`/`AppFlaw`/`InstanceFlaw` dispatched by *who must fix it*.

A broken path fires during correct operation by definition: infrastructure changes, so declared paths
break constantly and legitimately. There is no code to fix and nobody to blame.

**Concrete failure scenario.** An operator retires one EC2 instance during routine scaling. It sits on
three declared critical paths. Under the notes' design one ordinary `delete_node` emits three FLAW
records. Repeat nightly across an autoscaling group and the FLAW channel — one of three reserved
signals meaning "a guarantee was violated" (`specs/spec-tap-logging.md:187-220`) — becomes the loudest
and least meaningful stream in the instance. The cost is not noise; it is that the **real** flaws
(service-layer bypass, read-only write blocked, DB permission denied — `tap/flaws.py:236,273,317`, and
two `REFUSE_BOOT` paths) are now buried.

**Refutation:** *"The notes say 'may be'; it is a sketch."* Fair, and nobody has decided this. But it
is the **only** breakage mechanism named, and F3 shows breakage detection is the load-bearing half.
Naming the wrong mechanism means the integrity story is currently **unowned**. **Survives.**

**What it should be:** breakage is a graph fact, so it belongs on the graph — a derived `integrity`
state (`intact` / `broken@step_n` / `unverified_since`) computed by the same read that serves the path
(see F1's lazy revalidation), with `Flaw` reserved for the case where the path machinery itself
violated a guarantee. There is already the right precedent: `tap#668`'s `grid__cascade_failure` node
type — *"a standard failure capture stored on the graph, a listing + per-failure page drawn through
tap_viz"* (READ, `gh issue view 659/668`).

---

## F5 — Identity: architecture.md forbids the only natural key a path has. CONSTRAINT.

**Confidence: high.** Not a blocker; must be ruled before a line of code, because the guard demands it
at class definition.

`architecture.md`, Core concepts → *Identity* (READ):

> "Entity ids are **always assigned** — a UUIDv7 minted at first sight, **never derived from content,
> because a content-derived id conflates identity with lifetime and dead-ends against tombstones.**"

`tap_grid/natural_key.py:15-27` (READ) records the withdrawn draft: *"It is not a hash. An earlier
draft derived a UUIDv8 over SHA-256 of a canonical key document … withdrawn on 2026-09-17 —
tombstoning forced lookup-by-facts, not hash-of-facts."* And `spec-grid-uuid-selection.md:7`:
*"a content-derived entity id cannot coexist with a terminal tombstone."*

**A path's natural identity *is* its content** — the ordered step sequence. This is the one case where
the forbidden derivation is the semantically correct one.

### Concrete failure scenario — a fork, not a bug

A pathmaker runs nightly. Night 1 mints path `A`, steps `n1..n8`. Night 2 `n5` is replaced by `n5'`.

| Choice | What breaks |
| --- | --- |
| `NATURAL_KEY = ("name",)` | "The prod payment flow" silently means something else. The route change — the fact an operator most wants — is buried in step-edge churn, and per `spec-grid-service-delete.md:377` (Proposed, READ via agent) **a tombstone writes no typed historical row at all**, so the retired steps leave no typed trace of what the path was. |
| `KEYLESS` | Unbounded accumulation, no correlation run-to-run, "show me the payment path" returns N of them — and per F3 nothing retires the old ones. |
| Content-derived id | Forbidden, for a reason that bites here with unusual force: a path *is* a lifetime-bearing object with a terminal tombstone. |

A fourth sub-case the notes never address: **two different routes between the same endpoints.** Under
a name key they are one path that keeps changing; under a content key, two; under `KEYLESS`, however
many were minted. For blast-radius work, "how many distinct routes are there from X to Y" is *the*
question, so this is not a corner case.

**Refutation:** *"`NATURAL_KEY = ("name","scope")`; a route change is an ordinary property change, with
FLIP and history telling you when it moved."* — Good, and right for **authored** paths; it composes
with F3's authored/derived split. **Survives as a CONSTRAINT**, with two riders: it only works if the
steps live in a form history can diff (an ordered step list **on the path node**, not only as step
edges — see the tombstone-writes-no-typed-row problem above), and it does not answer the
distinct-routes question, which needs its own ruling.

---

## F6 — Edges-to-edges is far cheaper than the notes think in the schema, and far more expensive everywhere else. COST → recommendation: don't.

**Confidence: high.**

### The part of my attack that FAILED

The notes call edge-to-edge "the hard part". On this substrate that is wrong, and I want to be explicit
that this attack line collapsed:

- `Edge.from_entity` / `to_entity` are `ForeignKey(Entity)` — **not** to a node type
  (`tap_grid/models.py:1067-1076`, READ). Edges are `BaseModel`s with backing `Entity` rows already.
- The rule is **four lines in one function**, `tap_grid/services/_impl.py:605-609` (READ):
  ```python
  # Step 7: Graph invariant — no edges between edges.
  if from_entity.entity_type == "edge":
      raise ServiceConstraintError(...)
  ```
  (A second copy at `services/__init__.py:1565-1568` raises `InvalidEdgeError` — the same rule derived
  twice, untagged. A live `known-dupes` finding nobody has filed.)
- `tap_grid/DESIGN.md:11` (READ): *"enforced at the service layer, not the schema — **we don't have a
  grounded philosophical argument to prevent it structurally.**"* `spec-grid-edge.md` AC
  `req-grid-edge-nono-4`: *"Schema Does Not Enforce … Intentional."*

**No migration, no polymorphic FK, no union type.** The "hard version" is not hard at storage.

### The part that survives, with numbers

The cost is the **node-vs-edge dichotomy baked in above the schema**.

- **26 sites** in core non-test code branch on `entity_type == "edge"` (RAN: grep across
  `tap_grid/ tap_api/ tap_web/ tap_viz/`, tests excluded). Thirteen are in `grift/importer.py` alone.
- **GRIFT ref resolution hard-refuses it.** `tap_grid/grift/refs.py:116-139` (READ) builds `node_refs`
  from the batch's `nodes` array, then: *"Edge endpoint … names no node ref of this batch"*. A
  collector **cannot author an edge-targeting step in a GRIFT batch** without changing the interchange
  contract. That is the portable-serialisation boundary, not an implementation detail.
- **The GRIFT document schema is `additionalProperties: false`** with `required: ["nodes","edges"]`
  (`grift-document.schema.json`; `spec-grift-subgraph.md:58-99`).
- **Cytoscape cannot draw it** (`tap_viz/panels/graph_panel/__init__.py:257,315` consumes
  `envelope["edges"]` into a node-link graph).
- **It breaks the tombstone invariant's proof.** `Edge.live_onto_tombstones()` (`models.py:1054-1065`)
  is empty *by construction*. The agent confirmed the mechanism: the endpoint cascade is a **flat bulk
  update, not a recursive walk** (`_impl.py:861-889`), so it handles edges-onto-edges **one level
  deep** and would leave a third level live onto a tombstone. The invariant is asserted after *every*
  scenario in two corpora plus a dedicated test module with its own negative control
  (`test_cascade_corpus.py:111`, `test_batch_corpus.py:163`, `test_edge_onto_tombstone.py:64-141`).
  Relaxing the rule means re-proving all of it — and note the agent's other finding: unlike the
  tombstone invariant, **there is no standing invariant query for edge-to-edge at all**, only the
  create-path raise.

### Refutation — and the alternative that wins

*"Do it anyway; a path step traverses an edge, so the step must point at the edge."* The requirement is
real — F1 showed a path that stores only node ids cannot be revalidated. **You genuinely need edge
identity in the path.**

But the notes list a third option (`:62-64`) and do not take it seriously enough: a dedicated
**`path_step` node**.

- It is what the W3C chose for the same problem. RDF 1.2 introduces *triple terms* — statements about
  statements — and does **not** let a triple be a subject directly: it introduces a **reifier** node
  with `rdf:reifies`, and the quoted triple term stays **unasserted**
  (https://www.w3.org/TR/rdf12-concepts/). The standards body that spent a decade on edges-about-edges
  built an identity-bearing intermediary.
- On this substrate it costs nothing new: `path_step` is a `BaseModel` with `step_index`,
  `traversed_edge_id` (a plain UUID field — **data, not an edge**), `observed_batch_id`, `branch`,
  `direction`, plus two ordinary node-to-node edges. Zero changes to GRIFT, to the 26 dichotomy sites,
  to the cascade proof, or to Cytoscape.
- **Decisive:** referencing the traversed edge as id-as-data **survives that edge being tombstoned**,
  which a real edge-to-edge link cannot — `_impl.py:596-604` refuses edge creation onto a tombstone,
  and the cascade would tombstone the link. A broken path must still be able to say *which* edge broke.
  Only the data reference can.

**Recommendation: do not relax `req-grid-edge-nono`.** The notes' framing — *"the fun thing about
building our own graph database layer is that this is actually possible"* — is a capability argument,
not a design argument. *Can* is not *should*, and what the relaxation buys is available for free one
level up.

---

## F7 — Cardinality: mostly a false alarm, except exactly where `tap#499` puts it. COST.

**Confidence: medium-high on the arithmetic; high on the fencing.**

**The part that FAILED.** `tap#141` non-goals (READ): *"general graph-theory sprawl; path features
beyond what vuln-triage demands; the code-paths product."* `product-map.md:218` scopes `vuln-triage`
to ranking against *critical paths* — a handful of operator-declared routes. For **authored** paths
the objection does not survive.

**The part that survives.** `tap#499` step 2 is automatic materialisation of containment closure.
A transitive closure over a containment DAG is `O(N·d)` pairs. INFERRED arithmetic (not measured): an
estate with 100k leaf resources at depth 5 ≈ 400k ancestor-descendant pairs. As path *nodes* with step
edges: ≈400k path entities + ≈1.6M step edges — and **each edge is three rows** (`tap_edge`, its
backing `tap_entity`, and a `HistoricalEdge` row; `BaseModel.history = HistoricalRecords(...)`,
`models.py:673`; `Entity` itself carries no history) — ≈**5.2M rows** for a fact five indexed hops
already answer.

**Refutation:** *"`tap#499` says **embedded** membership (Candidate 2, a field on `Entity`), not path
nodes."* — Correct, and it defuses it. `O(N·d)` JSON entries on rows that already exist is a different
cost entirely. **Survives as a constraint**, yielding a rule that also resolves the notes' unanswered
"which candidate wins":

> **The candidates are not competitors; they are different use cases.** Node identity is for paths a
> human named and wants to protect, share and visualise — few, curated, long-lived. Embedded
> membership is for derived closures — many, mechanical, disposable. **A derived closure must never be
> given node identity.** (And per F1c, Candidate 1 *depends on* Candidate 2 for invalidation, so this
> is a layering, not a fork.)

Rider (cheap COST): the "junk drawer" question (`grid-native-paths-notes.md:107`) is real, and TAP has
a standing finding on exactly this shape — a bare `{type: object}` blocks JSON-lane strictness.
`Entity.paths` needs a schema in the same change that adds it.

---

## F8 — Derive-twice was already ruled; the residual is invalidation, and F1 owns it. CONSTRAINT.

**Confidence: high.**

**Where my attack failed.** `req-tap-known-dupes` governs **code** deriving a fact twice
(`specs/spec-tap-known-dupes.md`: *"when a fact is needed in two places, call one function"*), not data
caching. And `tap#499` (READ) already ruled the harder question, better than I would have:

> "**Build the cascade table first** … **Then embed path information in the models** from the same
> containment declarations … **The two implementations must agree.** … **Trap: Don't derive one
> implementation from the other.** … They have to share the declaration and nothing else."

That is the Gridkin model-oracle pattern applied to data. Attack line 1, as posed, fails.

**The residual.** A differential oracle proves the two derivations **agree on fixtures**. It says
nothing about whether the stored copy is **fresh at read time**. `graph-lookup-performance-notes.md`
already banks this in the right words: *"every materialized path is a **cache that must be
invalidated** when an edge on it mutates."* There is no change-feed layer in TAP — the APOC study maps
`apoc.trigger` (react-to-change, the 4th-largest namespace) to *"TAP reactive (FLIP/signals)"*, a layer
that **does not exist**, and FLIP is current-value provenance, explicitly current-state-only
(`spec-grid-flip.md`, `req-grid-flip-separation`).

**F1 is the full treatment of this**: what to record, what revalidation costs, why eager invalidation
is hazardous on this lock-ordering, and the `tap#322` sequencing dependency. The residual finding here
is just the framing: **the oracle catches derivation bugs; nothing catches staleness, and staleness is
the whole cost of the feature.**

---

## F9 — Authorization: the path object is an inference channel, and nothing derives its dimensions. CONSTRAINT (conditionally FATAL).

**Confidence: medium-high on the mechanism; the conditional is load-bearing and flagged above.**

The notes' answer (`grid-native-paths-notes.md:249-252`, READ) is the leaky one:

> "dimension-gated nodes are simply not returned, while visible participants still can be collected"

Silent omission from an **ordered** structure discloses the shape of what was omitted.

**Concrete failure scenario.** Path `P` = "prod payment flow", 8 steps; steps 3 and 4 are in a
dimension viewer `V` cannot see. `P`'s own `dimensions` are its creator's — `Entity.dimensions` is a
per-entity JSONField (`models.py:297`, GIN-indexed `:331`) and **there is no rule deriving a path's
dimensions from its members'**. `V` reads `P` and learns: it is called "prod payment flow"; it has
exactly 8 steps; six resolve; **steps 3 and 4 do not.** For a payment flow, "there are two things
between the task and the database that you may not see, and here is what they sit between" is most of
the secret. Close the gaps instead (renumber 0..5) and `V` cannot detect the omission and is handed a
**false** path. Both options are bad — the signature of an inference channel with no good answer.

A third leak: `Entity.version` is monotonic and bumped on every canonical mutation (`models.py:308-311`).
`P`'s version ticks when its hidden members change. Poll it: a covert channel with no content and real
signal.

**Refutation:**

1. *"Dimensions are scoping, not security."* — Partly true today, and this is the load-bearing
   uncertainty. `architecture.md` item 8: *"dimensions and security policy **may** scope access"* — a
   "may". And I could not corroborate dimension scoping in the Gryphon executor at all (see
   "could not verify"). **If dimensions never become an authz boundary, this finding is void.**
2. *"Authorization today is capability-based and coarse."* — Confirmed: `grid.read` is checked once
   above the query (`search.py:38`, `executor.py:121`), not per row. So today a viewer sees the whole
   grid or none of it, and nothing leaks **because there is no boundary**. That the discipline is
   understood is visible at `tap_api/routers/searches.py:46`, where `grid.read` is authorized *before*
   the Search is loaded specifically *"so a denied caller cannot probe existence"* — the same class of
   concern, already handled once.

**Survives as a CONSTRAINT with a trigger:** not a problem today; a structural problem the day
dimensions become an authz boundary; and paths are exactly the construct that makes that transition
harder. Because `specs/spec-security-posture.md` is explicit that *"over-restriction relaxes cheaply,
omission retrofits expensively"*, rule it now:

> **A path is visible only if every one of its steps is visible.** Deny-on-partial. Not silent
> omission, not renumbering, not redaction markers — a path is an assertion about a *whole route*, and
> a partial route is a different and false assertion.

The alternative — refuse at write to create a path crossing a dimension boundary — is also coherent
and cheaper to query, and should be weighed alongside it.

---

## F10 — Blast radius, itemised. COST.

**Confidence: high** (enumerated by an agent directly from code and specs).

**Schemas (3):** `tap_grid/schemas/grift-document.schema.json` (new `$defs` + container key + removal
section); the subgraph schema inline at `spec-grift-subgraph.md:58-83` (`additionalProperties: false`,
so a third array is a **breaking** change); `edge-definition.schema.json` if the construct has
registered types.

**Serializers / parsers (3):** `grift/subgraph.py` (`serialize_subgraph:404-462` hardcodes
`{"nodes","edges"}` at three layers; `batch_resolve_typed_models:318-346` branches on
`entity_type != "edge"`); `grift/envelope.py` (`parse_envelope_for_write` routes to exactly four
verbs); `grift/refs.py`.

**Importer (~8 sites in one 3,863-line module):** ref resolution; `file_node_ids` collection
(`:1367,:1580`); the dangling/endpoint loop (`:1851-1902`); removal-target `kind` checks
(`:1124-1145`, `:2166-2181`); op construction (`:2487-2707`); batch-scoped sweep guardrails
(`:3340-3350`, `:3498-3510`).

**Service (3):** `_impl.py` (`is_create`/`is_delete` tuples `:544-545`, a new branch at `:571-610`,
`_verb_to_schema_key`, the verb→`BatchEvent`-type map `:439`, cascade participation);
`service_types.py`; the public surface in `services/__init__.py`.

**Models / spine (2):** the `BaseModel` subclass with its mandatory `NATURAL_KEY`/`KEYLESS`+reason,
`FIELD_CRUD_SCHEMA`, `CONTAINMENT_EDGES` participation and an invariant read; the migration plus
`grid_tables.py` classification — which is **refuse-boot fail-closed** for an unsanctioned declarer
(`:85-105`).

**Specs (≥6-8)** with requirement rows each.

**Corpora (2):** `batch_corpus/` and `cascade_corpus/` — schemas, loader, and `model_oracle.py`, which
**imports nothing from the service layer or the ORM** (`req-grid-cascade-corpus-oracle-3`). So the
construct must be expressible as a set-based reachability fixed point with no ORM, or it cannot be
oracle-checked at all. `req-grid-cascade-corpus-format-5`: ≥50 scenarios, **≥2 per requirement
claimed**.

**And the gate that actually binds** (agent's conclusion, and I agree): not the code — the
**`unaccounted-requirements` ratchet** (`tap/guards/unaccounted_ratchet.py`). *"A requirement ADDED
without any disposition **fails immediately**"*, and the baseline is explicitly closed: *"**Never add
it to the baseline**: the baseline is grandfathered debt, not a place for new entries."* Every new RID
needs a `TAP-IMPLEMENTS:` claim, a spec-marked test, or a `Trace:` disposition, in the same PR.

**This is a COST, not an objection** — but it is the number that belongs next to "what is this
displacing". `plan/road-products.md:339`: the Active step is `step-products-git-serious-self`;
`step-products-rampart-preview`, the one *"standing on the path primitives"*, is `Proposed`.

**The strongest mitigation, and it is the best argument in favour of the whole idea:** if a path is a
node with ordinary node-to-node edges (the F6 recommendation), **most of that list evaporates.** GRIFT
round-trips it as nodes + edges with zero schema change; the service layer needs no new verb; the
corpora need scenarios but no new invariant. **The list above is the cost of the *edge-to-edge*
version, not of path-as-node.**

---

# Questions that must be answered before any code

**Q1 — Motivation.** Which is the driver: (a) a path is a thing people name, tag, protect and share;
(b) paths are fast; (c) a path is an observed historical fact with provenance? The answers are
respectively *extend `Search`*, *stop flattening rows in `_collect_graph_envelope`*, and *build the
construct*. **Highest-value question in this document.** *(F1, and see the note below)*

**Q2 — Substitution.** Does path-as-node *replace* variable-length traversal (E1) or is it *additive*?
`doc-gryphon-feature-demand.md:304-332` currently says replace. **Recommended: additive.** *(F2)*

**Q3 — Revalidation.** Lazy on read, eager on write, or never? **Recommended: lazy, with
`verified_at` + per-step `observed_batch_id`; eager only for the containment closure.** *(F1c)*

**Q4 — Sequencing against `tap#322`.** Path revalidation by provenance produces 100% false "broken"
while the importer rewrites `batch_id` on every unchanged pass. **Is path work blocked on
`tap#322`?** I believe it must be, and I do not think this dependency is currently recorded anywhere.
*(F1, Attack 2)*

**Q5 — Authored vs derived.** One type or two? **Recommended: two**, with reconcile explicitly
declared not to apply to either — authored because it observes no source, derived because it is
replaced wholesale. *(F3, F7)*

**Q6 — Retirement.** What retires a path, given `req-grid-reconcile-falsifier-1`? *(F3)*

**Q7 — Cascade semantics.** A member is tombstoned: does the path (i) stay live with a hole,
(ii) tombstone, or (iii) get marked broken? Today's silent default is (i). Note (ii) via containment
on `HAS_STEP` would make deleting a path delete its members and is never acceptable. *(F3, F4)*

**Q8 — Breakage signal.** Where does "this path is broken" live? **Not `Flaw`** —
`spec-tap-flaw-v0.md:17`: *"If a 'Flaw' can fire during correct operation, it is miscategorized."*
**Recommended: a derived integrity state on the path, on the `grid__cascade_failure` model.** *(F4)*

**Q9 — Identity.** `NATURAL_KEY = ("name", …)` or `KEYLESS`? And are two different routes between the
same endpoints one path or two? The guard forces an answer at class definition, and architecture.md
forbids the content-derived option. *(F5)*

**Q10 — Edge participation.** Relax `req-grid-edge-nono`, or a `path_step` node holding
`traversed_edge_id` as data? **Recommended: `path_step`.** *(F6)*

**Q11 — Partial visibility.** Deny-on-partial, or refuse-at-write across a dimension boundary? Silent
omission is not an option. *(F9)*

**Q12 — Negative claims.** Is "there is no path from X to Y" in scope? If yes, it needs E1 **and** a
composed cross-collector completeness statement, neither of which exists. If no, say so in the
non-goals, because buyers will assume it. *(F1, Attack 1)*

**Q13 — Displacement.** Per `plan/road-products.md:285-287`, what is this displacing? *(F10)*

---

# Verdict

**Path-as-node is the right shape.** I went in expecting to kill it on three lines and all three
failed against the substrate:

- **Derive-twice** is a code guard, not a data rule, and `tap#499` already ruled the data question
  with a differential-oracle design better than what I would have proposed.
- **Edge-to-edge is not a migration problem at all.** `Edge.from_entity` is already
  `ForeignKey(Entity)`; the rule is four lines in one function; `DESIGN.md` says outright there is no
  philosophical argument for it. The notes over-dramatise their own hard part.
- **Cardinality** is fenced by `tap#141`'s non-goals, and the combinatorial case is planned as
  embedded membership, not nodes.

And the positive case is stronger than the notes make it. On **this** substrate a path modelled as a
node with ordinary node-to-node edges costs almost nothing structurally — GRIFT round-trips it,
dimensions/history/FLIP/tombstones apply for free, and `Search` (`models.py:1168-1292`) already
demonstrates the exact pattern: an authored, `KEYLESS`, first-class grid object that carries a
parse-validated query and is bound to panels by a `USES_SEARCH` edge. **Most of the notes' "immediate
benefits" list is a small delta from what exists.**

**What the constructive dossier is likely to be too optimistic about, in order:**

1. **That persistence is about speed.** Revalidating a stored k-step path costs Θ(k) — it saves the
   branching factor, not the length, on a graph whose architecture already spends three design
   decisions keeping branching small. And the flagship demo path is a **fixed-length 4-hop chain**
   (`docs/misc/code-core-v0.md:317-330`) that Gryphon executes **today** as one set-based query —
   `_has_advanced_features` routes any pattern with `len(pattern.edges) > 1` to the chain executor
   (`executor.py:323-325`). What blocks it is not storage; it is **result shape**.
   `_collect_graph_envelope` has the ordered path in hand — `values_list` yields one tuple per matched
   chain in deterministic pattern order, with per-hop edges under `_hop{i}_edge` names — and then
   **flattens it into two unordered sets at `:2457-2467`**, three lines after it existed. Expect the
   dossier to quote `grid-native-paths-notes.md:42`. Ask for the benchmark. There isn't one.
2. **That named paths can stand in for reachability.** §5.1 says so and it is the one claim I would
   call outright wrong for TAP's own security product — reached, moreover, from a study whose §4 says
   the opposite.
3. **That breakage detection is a fast-follow.** It is the load-bearing half. A path with no integrity
   signal is not a neutral feature — it is a confident lie that degrades over time, and F3 shows
   nothing in the current lifecycle machinery will ever retire it. **Breakage must ship in the same
   change as creation, or the feature should not ship.**
4. **That revalidation is free once you have provenance.** It is affordable, but it is wrong until
   `tap#322` lands, and that dependency does not appear to be recorded anywhere.
5. **That Candidates 1 and 2 are alternatives.** They are a dependency: invalidating a path node
   requires an edge → paths index, which *is* Candidate 2.

**The shape I would build:**

- A `path` node — authored, `KEYLESS`, named, tagged, dimensioned, with an **ordered step list on the
  node itself** (so history can diff it, and because a tombstone writes no typed historical row).
- `path_step` as a node where per-step richness is needed, holding `traversed_edge_id` and
  `observed_batch_id` **as data**. No edges between edges; `req-grid-edge-nono` stands.
- Lazy revalidation with `verified_at` and a derived `integrity` state — **in the first change**,
  sequenced behind `tap#322`.
- Derived closures as embedded membership only, never as path nodes.
- **E1 stays on the road.** Named paths are how you *name and protect* a route; variable-length
  traversal is how you *find* one. Ship the first; do not cancel the second.

The idea survives, and the falsifiability machinery George points at is a real and unusual advantage —
it is what makes a persisted path checkable at all. What it does not do is make persistence a
performance feature. **Build it for identity. Say so in the spec.**
