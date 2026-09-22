# Edges to Edges: the five arguments, stress-tested on TAP's substrate

**2026-09-22. Third pass on persistent paths, re-opening red-team F6 with new information.**

This document does what the framing asked: it tests five arguments *on their merits, on this
substrate*, and then answers "how should I do it". Prior art appears only where I can name a
mechanism worth stealing or a measured cost. "System X chose differently" appears nowhere as an
argument.

## Method

Every claim is labelled:

- **RAN** — I executed it in this session against the live `tap_demo-dev` stack (31,479 edges,
  ~55k entities) or against the dev Postgres. Plans are `EXPLAIN (ANALYZE)` output.
- **READ** — I read it at the cited file and line.
- **INFERRED** — reasoning over what I read. Not observed.

Five things are new in this pass and none of them appear in either prior document:

1. **I ran the edge-to-edge cascade.** Both prior docs *inferred* what the tombstone machinery would
   do. The dossier called it "worth a one-hour spike". I did the spike. Depth 1 works today,
   unmodified. Depth 2 violates the tombstone invariant. Both **RAN**.
2. **The red team's decisive argument against edge-to-edge is false on this substrate.** It claimed a
   real edge→edge link "cannot say which edge broke" because the cascade would tombstone it. TAP's
   tombstones are *soft*. The link survives, still pointing at the dead edge, with a timestamp.
   **RAN**.
3. **The history story is worse and better than argument 4 assumes.** Worse: every composable
   history query raises `NotImplementedError`, and `Entity` has no history table at all. Better:
   path history does not need them — it falls out of soft tombstones as a valid-time interval query.
   **READ + RAN**.
4. **I measured arguments 1 and 5.** Both are true. Argument 1 is a 2-buffer index scan at 0.010 ms.
   Argument 5 costs ~0.15 ms of sort+JSONB extraction for 939 steps, warm. Neither prior doc
   measured anything.
5. **Three silent-wrong-answer sites neither prior document found**, all of which must move in the
   same change: GRIFT **export** drops an edge-endpointed edge unconditionally; the GRIFT sweep's
   Guardrail B skips referential integrity for edge candidates *by a comment that cites this very
   rule*; and hard purge leaves an **orphaned ghost `Entity`** — a live spine row typed `edge` with no
   `Edge` behind it, which the existing invariant query structurally cannot see (**RAN**).

And one correction to the framing both prior documents share: **"GRIFT round-trips it for free" is
false** for the edge-endpointed form. It round-trips for free for a path whose steps point at *nodes*.
The step that names a specific edge is dropped on export today.

---

# Part 1 — The five arguments

## Argument 1 — "We can do lookups blazingly fast using existing indexes to detect whether an edge has an edge."

### Verdict: **HOLDS, and it is measured, not merely indexed.** Not load-bearing.

**The index that serves it.** `tap_edge` carries six relevant btree indexes (**RAN**, `\d tap_edge`):

```
"idx_edge_from_type"                btree (from_entity_id, edge_type)
"idx_edge_to_type"                  btree (to_entity_id, edge_type)
"tap_edge_from_entity_id_bcbe39d5"  btree (from_entity_id)
"tap_edge_to_entity_id_fa113be2"    btree (to_entity_id)
"tap_edge_entity_id_key"     UNIQUE btree (entity_id)
"tap_edge_edge_type_f32be72d"       btree (edge_type)
```

Declared at `tap_grid/models.py:1084-1085` (**READ**); the bare FK indexes are Django-generated.

**The query shape and its plan.** "Does this edge have an edge?" is a lookup on the *edge's backing
Entity id* in `from_entity_id` / `to_entity_id`.

Undirected, untyped — the general form (**RAN**):

```
Limit (actual time=1.241..1.242 rows=0 loops=1)
  Buffers: shared hit=3 read=1
  -> Bitmap Heap Scan on tap_edge
       -> BitmapOr
            -> Bitmap Index Scan on idx_edge_from_type   Index Cond: (from_entity_id = ...)
            -> Bitmap Index Scan on idx_edge_to_type     Index Cond: (to_entity_id = ...)
Execution Time: 1.266 ms   (cold; 4 buffers touched)
```

Directed and typed — the form a path actually uses (**RAN**):

```
Index Scan using idx_edge_to_type on tap_edge
  Index Cond: ((to_entity_id = '...'::uuid) AND ((edge_type)::text = 'HAS_STEP'::text))
  Buffers: shared hit=2
Execution Time: 0.010 ms
```

**So "blazingly fast" is true, and it is true for a specific reason worth naming:** the composite
`(to_entity_id, edge_type)` index makes the typed form a *pure index scan* — two buffer hits, no
heap access, 10 microseconds. The untyped form costs a BitmapOr over two indexes and a heap recheck.
**Design consequence: always query steps by `edge_type`, never by endpoint alone.** That is free if
`HAS_STEP` is a declared type, which it must be anyway.

**Why it is not load-bearing.** Nothing about the design fails if this were merely "indexed" rather
than "blazing". The per-step lookup is already `O(log E)` and a path is `k` of them, `k` ≤ ~30. This
argument removes an objection; it does not create a requirement. The red team's F1 is right that
persistence is not a performance feature — but F1 over-corrects. This *particular* claim is true and
measured, and F1's own cost arithmetic (`~2 indexed queries, k rows, O(k log N)`) is now **observed**
rather than inferred.

**Cost: zero.** No new index is needed for argument 1. Both indexes already exist and both already
serve it.

**One caveat, honestly.** 31,479 edges is a small table; the indexes are almost entirely in cache.
At 10M edges the plan shape is identical (btree point lookup) but the buffer count rises with tree
depth — **INFERRED**, roughly 4-5 buffers instead of 2. Still sub-millisecond. I did not test at
scale and nobody should quote me as if I had.

---

## Argument 2 — "It gives us a single node to represent a path, and can represent sub-paths."

### Verdict: **PARTLY. The single-node half holds and is free. The sub-path half does NOT need edge-to-edge — and that is the interesting finding, because it removes one of the five arguments from the edge-to-edge column entirely.**

**The single-node half.** Uncontested and already proven by precedent in-tree: `Search`
(`tap_grid/models.py:1168-1292`, **READ**) is exactly this — an authored, `KEYLESS`, first-class grid
object carrying a parse-validated query, bound to consumers by an ordinary edge. A `Path` node gets
identity, name, tags, dimensions (GIN-indexed, `models.py:331`), `version`, `deleted_at`, history and
GRIFT round-tripping for free. Nothing here requires edge-to-edge.

**The sub-path half, tested hard.** The question is whether *path-as-a-step-of-another-path* needs an
edge to point at an edge.

It does not, and the reason is structural: **a path is a node.** `P --HAS_STEP--> Q` where `Q` is a
path node is an ordinary node→node edge. It is legal today, under the existing rule, with no
exception of any kind. **INFERRED from the substrate** (`Edge.from_entity`/`to_entity` are
`ForeignKey(Entity)` with a service check only on `entity_type == "edge"`, `_impl.py:605-609`
**READ**) — `Q.entity_type` is `"path"`, not `"edge"`, so the check never fires.

This is the "member type should be the supertype of {path, step}" pattern the dossier found in
Reactome's `Event` and BioPAX's `pathwayComponent` (dossier §III.3 sixth, **READ**). TAP is already
there for free because everything is an `Entity`.

**So: would a path-node-with-membership give the same thing?** Yes, identically, for sub-paths.
Composition is a property of *paths being nodes*, not of *steps pointing at edges*. The two claims
were bundled in the June notes and they are separable.

**Where the two diverge is a different question — the one argument 3 asks.** Sub-path composition
needs nothing. Naming a *specific edge instance* needs something. Argument 2 does not carry argument
3's weight, and it should stop being cited as if it did.

**Cost of the single-node half: near zero** (the `Search` precedent is the proof).
**Cost of the sub-path half: zero.** It already works.

**One real design consequence, and it is not free.** If a path may contain a path, the ordering and
the breakage query become *recursive*, and TAP has no recursive traversal (E1 / var-length
`-[*n..m]-` is parse-but-reject, per `doc-gryphon-feature-demand.md:304-332`, **READ** via the red
team's citation). "Flatten this path including sub-paths" is a recursive CTE or an application-level
loop. **Recommend: cap sub-path nesting depth explicitly in v0** (I would say depth 2, or forbid it
in v0 and add it when a use case names itself). An uncapped recursive structure with no recursive
query engine is a trap, and it is the *same* trap as uncapped edge-to-edge depth.

---

## Argument 3 — "I absolutely need to do specific edge traversals between two nodes. HARD REQUIREMENT."

> *"We need to know the exact path that something took where there could be multiple edges of the
> same type between nodes. This precision is critical."*

### Verdict: **HOLDS, it is the decisive input, and it makes arguments 1, 2 and 5 moot as *reasons*.** They remain true; they stop being the case.

Both prior documents named this as their falsifier, verbatim:

- Dossier §III.5: *"The edge-to-edge deferral is wrong if a v0 use case needs to name a specific edge
  instance, not an edge class. The one I can construct is multi-edge disambiguation … **If that case
  is real today, the exception should ship in v0**"* (**READ**).
- Red team F6: *"The requirement is real — F1 showed a path that stores only node ids cannot be
  revalidated. **You genuinely need edge identity in the path.**"* (**READ**). F6 then routes it to
  id-as-data; §3.3 below shows why that route fails.

George has ruled the requirement. I am not re-arguing it. But I did verify its *premise* on the
substrate, because if parallel same-type edges were already distinguishable by something other than
id, the requirement would be satisfiable more cheaply.

**RAN** — two parallel `RUNS_ON` edges between the same pair:

```
parallel edges distinguishable by entity id: True | same (from, type, to): True
```

`(from_entity_id, edge_type, to_entity_id)` is **identical**. There is no uniqueness constraint on
that triple (**RAN**, `\d tap_edge` shows no such constraint). The *only* discriminator is
`Entity.id`. The premise is confirmed: **a path that records node ids and edge types does not
determine a route on TAP's grid.**

### 3.1 The mechanisms, enumerated

| # | Mechanism | What it is on this substrate |
| --- | --- | --- |
| (a) | True edge→edge reference | `Edge(from_entity=<path Entity>, to_entity=<edge's backing Entity>)` |
| (b) | `path_step` node with `traversed_edge_id` as a data field | A `BaseModel` with a plain `UUIDField`. Not a FK. |
| (c) | The edge's backing `Entity` id referenced as an ordinary node | — see below — |
| (d) | Composite natural key on the edge | `NATURAL_KEY` over declared discriminators; store the key, not the id |
| (e) | Ordered JSON array of edge ids on the path node | `properties`-style list, no referential structure |
| (f) | Reification — promote the edge to a node, two edges either side | The standard property-graph workaround |

### 3.2 The ballgame: (a) and (c) are the same row

The brief flagged this and it is correct. **(a) and (c) are not two options. They are one option
described twice, and the four-line service check is the only thing that distinguishes them.**

- `Edge.to_entity = ForeignKey(Entity, on_delete=CASCADE)` (**READ**, `models.py:1073-1077`). It is
  *not* typed to a node. There is no node type in TAP.
- Every `Edge` is a `BaseModel` and therefore **has a backing `Entity` row on the spine** with a
  uuid7, dimensions, version, `deleted_at` and history (**READ**, `models.py:1033`, `:675-679`).
- **RAN** — I confirmed the spine row's type directly: `inner edge spine entity_type = edge`.
- The prohibition is a check on `entity_type` *after* the endpoints are loaded
  (`_impl.py:605-609`, **READ**; duplicated at `services/__init__.py:1563-1568`).

So "reference the edge's backing Entity as an ordinary node" **is** "an edge whose endpoint is an
edge". There is no third state. You cannot FK to the row and simultaneously not have an edge
endpoint, because the FK *is* the edge endpoint. **RAN** — I created exactly this and watched both
halves happen:

```
SERVICE refused edge->edge: InvalidEdgeError | Edges cannot have other edges as endpoints (to_entity is an edge).
DB ACCEPTED edge->edge via direct ORM; step entity: 01a0c753-...
```

Two consequences.

1. **The choice is binary**, not six-way. Either the step holds a **foreign key** to the edge's
   Entity — which is edge-to-edge under any name — or it holds the id as **data**, which is not a
   reference at all. Everything else is a variation on one of those two.
2. **The dossier's own reasoning already points at (a).** §III.3 fifth (**READ**): *"TAP's edges
   already have identity … Paying the reification tax to acquire a property you already possess is
   simply waste. **TAP is in the one position where the standard workaround is strictly worse than
   the thing it works around.**"* That argument, taken to its conclusion, rules out (b) and (f) as
   well as reification — and the dossier does not take it that far.

### 3.3 The ranking, with what I observed

Ranked by: integrity guarantees, cascade behaviour, query cost, migration cost.

---

**Rank 1 — (a)/(c), a true edge→edge `HAS_STEP`, fenced to depth 1.**

*Integrity.* A real Postgres foreign key
(`tap_edge_to_entity_id_fa113be2_fk_tap_entity_id`, **RAN**). The referenced row cannot vanish
without the database knowing. `on_delete=CASCADE` means a hard purge takes the step with it rather
than stranding it.

*Tombstone cascade — OBSERVED, not inferred.* I built the structure and deleted the inner edge
through the service layer. **RAN**:

```
delete_edge(eA)                        -> True
  eA: deleted_at=True   version=2  batchevents=['unlink']
  s1: deleted_at=True   version=2  batchevents=[]           <- the HAS_STEP edge, cascaded
  live_onto_tombstones violations among probe rows: 0
```

The existing incident-edge pass (`_impl.py:858-889`, **READ**) gathers
`Edge.objects.filter(Q(from_entity_id=X) | Q(to_entity_id=X))` **without reference to entity type**,
so it already handles an edge endpoint correctly. `Edge.live_onto_tombstones()`
(`models.py:1054-1065`, **READ**) filters on `from_entity__deleted_at` / `to_entity__deleted_at`,
also without reference to type — **the invariant was written against `Entity`, not against
node-ness, and therefore already covers this case.** The dossier inferred this and asked for a spike.
The spike is done and the inference was right.

*And the red team's decisive counter-argument is **false**.* F6 said:

> *"Decisive: referencing the traversed edge as id-as-data **survives that edge being tombstoned**,
> which a real edge-to-edge link cannot … A broken path must still be able to say *which* edge
> broke. Only the data reference can."*

**RAN**, on the tombstoned `HAS_STEP` edge:

```
HAS_STEP readable via all_objects: True
HAS_STEP to_entity_id still points at dead edge: True
```

TAP's deletes are **tombstones, not deletes**. The link is not destroyed; `deleted_at` is set. The
step still names the edge that broke, *and* now carries the timestamp at which it broke — which
id-as-data does not have and cannot get. F6's decisive point inverts: **the cascade is the feature,
not the cost.** This is the single largest correction in this document.

*Query cost.* 0.010 ms typed point lookup (§1, **RAN**). Ordered retrieval 0.315 ms for 939 steps
warm (§5, **RAN**).

*Migration cost.* **No migration.** No column, no polymorphic FK, no union type. The change is the
four-line check plus its duplicate. The cost is entirely above the schema — see Part 3.

*Failure mode.* Depth. See 3.4.

---

**Rank 2 — (b), `path_step` node with `traversed_edge_id` as a plain UUID field.**

This is the red team's recommendation (F6, Q10) and I am rejecting it, on evidence it did not have.

*Integrity.* **None.** A `UUIDField` is not a FK. Nothing in the database, the ORM or the service
layer connects it to the row it names. The one guarantee TAP spends its whole delete design
protecting — no live reference onto a tombstone — does not apply, because it is not a reference.

*Cascade.* **Nothing happens.** The traversed edge is tombstoned; the step node is untouched, live,
and still pointing at a dead uuid. The path presents as intact. This is the exact failure
`spec-grid-reconcile.md:7` forbids elsewhere — *"Absence of evidence must never render as evidence of
absence"* (**READ** via the red team's citation) — recreated as "absence of a cascade renders as
evidence of intactness."

To recover breakage you must **build a detector**: a periodic job joining every `traversed_edge_id`
against `Entity.deleted_at`. That is a new subsystem, it has no natural trigger (TAP has no
change-feed layer — `apoc.trigger` maps to *"TAP reactive (FLIP/signals)"*, which the red team's F8
confirms **does not exist**), and it produces a *derived* timestamp ("we noticed at 03:00") rather
than the *true* one.

*Cost accounting.* (b) is usually sold as cheaper. It is not. It trades ~29 dichotomy call-sites of
one-time work for a permanent detector job, a permanent staleness window, and the loss of a
database-enforced invariant. **That is a bad trade, and it is bad specifically because TAP's delete
machinery is unusually good.** On a substrate with hard deletes, (b) would be right.

*Where (b) IS right.* One place: `observed_batch_id` — the batch that set the edge's value *at
capture time*. That is a snapshot of a value, not a reference to a row, and it belongs as data. Keep
it. See Part 2.

---

**Rank 3 — (d), a composite natural key on the edge.**

`Edge.NATURAL_KEY` is `KEYLESS` today, with the reason recorded in the model
(`models.py:1042-1048`, **READ**): *"Edge identity was ruled separately — assigned uuid7 ids with
OPTIONAL natural keys over declared discriminators — and the migration-collision question is open as
tap#458 item 4."*

So this is *planned* and would give a stable, human-legible, re-observation-surviving edge
identifier. It is genuinely attractive for the case where a re-observed edge should be recognised as
the same edge. **But it does not satisfy argument 3 today** (it does not exist), it does not remove
the need for a reference (you would still store the key *somewhere*, and a key-as-data has exactly
(b)'s integrity properties), and it is blocked on an open ruling. **Complementary, not alternative.**

---

**Rank 4 — (e), an ordered JSON array of edge ids on the path node.**

*The one thing it is best at:* history. One route change = one `UPDATE` = one `HistoricalPath` row
containing the whole before/after list. `as_of` becomes a single-row lookup. The red team's F5
wanted this ("*an ordered step list on the path node, so history can diff it*").

*Why it loses anyway:* no FK, no cascade, no per-step properties, no per-step dimensions, not
indexable, and the `{type: object}` junk-drawer problem TAP already has a standing finding on. And
§4 below shows the history advantage is illusory — the interval query over soft-tombstoned step edges
answers the same question without the JSON blob.

*Keep it as a denormalised cache if a UI needs it. Never as the source of truth.*

---

**Rank 5 — (f), reification.** Rejected on the dossier's own argument (§3.2 above): TAP's edges
already have the identity reification exists to manufacture. +1 node, +1 edge, doubled traversal
depth, a first-class edge type demoted to a node label, to buy a property you already own.

---

### 3.4 The one real cost of (a): depth, and it is enforceable

**RAN.** I built `Q --HAS_STEP--> (P --HAS_STEP--> eA)` — an edge pointing at an edge pointing at an
edge — and deleted `eA`:

```
eA: deleted_at=True   (the traversed edge)
s1: deleted_at=True   (depth 1: cascaded correctly)
s2: deleted_at=False  (depth 2: LEFT LIVE)
DEPTH-2 CHECK — live edges onto tombstones: [(01a0c754-..., 'HAS_STEP')]
```

**The invariant is violated at depth 2.** `Edge.live_onto_tombstones()` returns a row — the set the
spec says is empty at every committed state (`req-grid-service-delete-tombstone-7`, asserted after
every scenario in two corpora plus a dedicated test module). The reason is exactly what the red team
inferred: the incident-edge pass is a **flat bulk update, not a recursive walk**
(`_impl.py:858-889`, **READ** — it gathers edges incident to *the deleted entity* and bulk-updates
them; it does not then gather edges incident to *those*).

So the depth cap is not a stylistic fence. **It is the condition under which TAP's central delete
invariant continues to hold, and I have a failing case to prove it.** That is worth more than every
formal argument about ubergraphs in either prior document, and it is the acceptance criterion the
exception must ship with.

**Enforcement is in the same four lines that currently refuse everything:** permit an edge endpoint
only when the target edge is not itself edge-endpointed, i.e. refuse if
`to_entity.entity_type == "edge"` AND the target edge already has an edge endpoint. See Part 2 for
the exact rule.

---

## Argument 4 — "Factor in how our existing FLIP and history systems interact to trace changes over time … the ability to trace history is going to blow minds (and be essential)."

### Verdict: **PARTLY — and it splits cleanly into a wrong half and a much stronger half than George stated.**

Neither prior document explored this. Here is what is actually there.

### 4.1 The wrong half: FLIP and django-simple-history do not do this, at all

**FLIP is current-state only, by explicit design.** `spec-grid-flip.md` Philosophy (**READ**):

> *"FLIP is intentionally scoped to present state … **If a caller wants to know how that provenance
> changed over time, they must consult history.**"*

`req-grid-flip-separation`, `Implemented`. `flip_map` is a field-path → batch-id dict on the current
row (`models.py:680-684`, **READ**). It is overwritten in place
(`tap_grid/flip.py:86-88`, **READ**: `instance.flip_map[field] = batch_id`). **FLIP contributes
nothing to path history.** It tells you which batch set the *current* value and forgets the previous
one.

**The history query API does not exist.** All four composable methods raise (**READ**,
`tap_grid/history.py:126-176`):

```python
def timeline(self):       raise NotImplementedError("... deferred to the time-travel pass ...")
def between(self, s, e):  raise NotImplementedError(...)
def latest_before(self,t):raise NotImplementedError(...)
def as_of(self, t):       raise NotImplementedError(...)
```

`req-grid-history-query` is `Proposed` (**READ**, `spec-grid-history.md:23`). So "show me how X
changed over the last 90 days" has **no answer today for any object in TAP** — not paths, not nodes,
not edges. Argument 4 cannot be built on it.

**`Entity` has no history table.** `HistoricalRecords` is declared on `BaseModel`
(`models.py:673`, **READ**); `Entity` is a plain `models.Model` (`models.py:259`, **READ**).
Migration `0001_initial.py` creates exactly `HistoricalBatch`, `HistoricalDimension`,
`HistoricalEdge`, `HistoricalKeystone`, `HistoricalSearch` — **no `HistoricalEntity`** (**RAN**,
grep of the migration). **RAN**: `Entity has history attr: False`.

**And a tombstone writes no historical row at all.** `spec-grid-service-delete.md:377`,
`req-grid-service-delete-reason-2`, `Proposed` (**READ**):

> *"**Found 2026-09-17:** a tombstone writes no typed-model historical row at all — the pipeline
> updates `Entity.deleted_at` on the spine and never saves the typed instance — so there is no row to
> carry the reason yet."*

Confirmed by code: the tombstone is `Entity.objects.filter(...).update(deleted_at=..., version=F+1)`
— a **bulk update**, which fires no Django signal and so creates no `HistoricalX` row
(`_impl.py:851-856`, **READ**). And **RAN**: after deleting the edge, `HistoricalEdge` row count was
**1** — the create only. The death is not in history.

**Therefore: the death of an edge is invisible to django-simple-history entirely.** Argument 4's
premise — that FLIP and history already trace change — is false for exactly the event a path cares
about most.

### 4.2 The much stronger half: path history falls out of **soft tombstones**, and it is nearly free

The mechanism George is reaching for exists. It is not FLIP and it is not `HistoricalX`. **It is the
tombstone discipline**, and it gives TAP a valid-time interval model that no other system in either
prior document has.

Every `Entity` carries (**READ**, `models.py:312-320`):

- `created_at` — `auto_now_add`, when the row appeared
- `deleted_at` — `null=True, db_index=True`, when it was retired, **null means live**
- `version` — monotonic, *"Increments on every canonical mutation, including tombstone"*

And a tombstone is **soft**: the row stays, readable through `all_objects`. **RAN**:
`HAS_STEP readable via all_objects: True`, `to_entity_id still points at dead edge: True`.

**So each `HAS_STEP` edge is a half-open interval `[created_at, deleted_at)` naming a specific
traversed edge.** A path's route as-of any time `T` is one indexed query:

```sql
SELECT e.entity_id, e.to_entity_id, e.properties->>'step_index'
  FROM tap_edge e JOIN tap_entity s ON s.id = e.entity_id
 WHERE e.from_entity_id = :path AND e.edge_type = 'HAS_STEP'
   AND s.created_at <= :T AND (s.deleted_at IS NULL OR s.deleted_at > :T)
 ORDER BY (e.properties->>'step_index')::int;
```

Anchored by `idx_edge_from_type` (**RAN**, §1 and §5 both show it chosen). **No time-travel
machinery. No history table. No new subsystem.** "How did this path change over 90 days" is the same
query without the `T` filter, plus `created_at`/`deleted_at` as the change events.

This is the answer to the brief's question, and it is worth stating plainly:

> **TAP does not need `as_of()` to have path history. It needs steps to be entities and deletes to be
> tombstones — and both are already true.**

### 4.3 Does the answer differ between (a) and (b)? **Yes, decisively.**

Both representations get the interval query; steps are entities either way. The difference is **who
writes the end of the interval.**

| | (a) edge→edge `HAS_STEP` | (b) `path_step` node with uuid-as-data |
| --- | --- | --- |
| Step added | `created_at` on the step's Entity | same |
| Route re-declared by a human | you tombstone the old step | same |
| **Traversed edge dies** | **the cascade tombstones the step, same transaction, same timestamp** (**RAN**) | **nothing happens.** Step stays live pointing at a dead uuid |
| "when did this path break?" | `deleted_at` on the step — exact, transactional | a detector job's poll time, or never |
| "which step broke?" | the tombstoned step's `to_entity_id` (**RAN**: preserved) | the field, if you look |
| "broken vs. re-routed?" | join: target's `deleted_at` non-null ⇒ broken; null ⇒ re-routed | must be recorded by the detector |

**(a) makes path *breakage history* free. (b) makes it a build.** That is the strongest argument in
this whole document for the edge-to-edge form, and George is right that it is probably the strongest
of his five — but for a different reason than he gave. It is not FLIP and history that make it work.
It is the cascade plus soft tombstones.

### 4.4 Three gaps this exposes, and one of them is a defect

1. **The cascaded step gets no `BatchEvent`.** **RAN**: `s1: deleted_at=True version=2
   batchevents=[]`, while the directly-deleted edge got `['unlink']`. The code shows why: the
   provenance loop is guarded by `if state is not None and edge_entity_ids:` (`_impl.py:875-886`,
   **READ**), and `state` is non-`None` only for a `delete_node` with `cascade="contained"`
   (`_impl.py:810`, **READ**). **A plain delete's incident edges are retired silently.** You get
   *when* (`deleted_at`) and *that it changed* (`version` 1→2, **RAN**) but not *which batch* and not
   *why*. For a path-breakage audit trail that is a real hole. **This is fileable independent of
   paths** — it is already a gap in edge retirement provenance generally.
2. **Transaction time only.** `created_at` is `auto_now_add` — TAP record time, not source
   observation time. `req-grid-history-time` (`observed_at`) is `Proposed` (**READ**). So the
   interval model answers *"when did TAP learn the route changed"*, not *"when did the route
   change"*. Say so in the spec; it is the honest claim and it is still valuable.
3. **The tap#322 dependency the red team found is real but does NOT bind this design.** F1 Attack 2
   is correct that pinning `observed_batch_id` produces 100% false "broken" while the importer
   rewrites `batch_id` on every unchanged pass. **But the interval model does not use `batch_id`.**
   It uses `deleted_at`, which is written only by an actual retirement. **So §4.2's mechanism is
   *not* blocked on tap#322** — only the optional freshness/`observed_batch_id` layer is. That is a
   material unblocking of the red team's most actionable finding, and it argues for shipping
   intactness first and freshness later.

**Verdict restated:** argument 4's stated mechanism (FLIP + history) is **wrong**. The capability it
predicts is **real, cheaper than claimed, and representation-dependent in a way that favours (a).**

---

## Argument 5 — "Finding a path in order is a quick lookup starting with the path node: gather all edges ordered by step number in the edge."

### Verdict: **HOLDS on speed (measured), FAILS on insertion. The ordering mechanism needs one design decision the argument does not make.**

**Where the step index lives.** `Edge.properties` is a `JSONField` (`models.py:1078`, **READ**) with
a per-edge-type registered JSON Schema validated on **every** save
(`Edge.save()` → `validate_edge_properties`, `models.py:1122-1125`, **READ**; registry at
`constraints.py:270-299`, **READ**). So `{"step_index": 1}` is declarable and schema-enforced today,
with **no model change** — declare `property_schema` on the `HAS_STEP` edge definition
(`tap_grid/schemas/edge-definition.schema.json`, **READ**: `property_schema` is an existing key).

**What index serves the sort: none — and it does not matter.** There is **no index on
`tap_edge.properties`** (**RAN**, `\d tap_edge` — no GIN, no expression index). The selection is
served by `idx_edge_from_type`; the ordering is an in-memory quicksort over the `k` selected rows.

Measured, warm cache, 939 steps from one node (**RAN**):

```
ORDER BY (properties->>'step_index')::int
  Sort (actual time=0.239..0.271 rows=939)  Sort Method: quicksort  Memory: 61kB
  -> Bitmap Heap Scan (0.026..0.167)  Heap Blocks: exact=119
  Execution Time: 0.315 ms

no ORDER BY (same rows)
  Execution Time: 0.162 ms
```

**JSONB extraction + sort of 939 steps costs ~0.15 ms.** At a realistic path length (4-30) it is
unmeasurable. A cold-cache run of the same query took 9.0 ms, and I want to flag that I nearly
reported the cold number as a finding — it is a cache artefact, not a JSONB cost. **Argument 5's
speed claim is true and needs no new index.**

(For contrast I built a narrow table with a real `int` column and a composite
`(from_entity_id, edge_type, step_index)` index, **RAN** in a rolled-back transaction: 0.354 ms —
*no faster*, and the planner still chose Bitmap Heap Scan + Sort, because a bitmap scan discards
index ordering. **A composite index buys nothing here.** That is a useful negative result: do not add
one.)

**Where it fails: insertion into the middle.** With dense integer indices (1, 2, 3…), inserting a
step at position 3 renumbers every step after it. Each renumber is an `UPDATE` on `Edge.properties`,
which means per row: a version bump on the spine, a `HistoricalEdge` row, a `flip_map` rewrite, and a
full JSON-Schema revalidation in `Edge.save()`. **O(k) writes for one logical insert** — and worse,
**it destroys the interval history from §4.2**, because "step 5" no longer means the same thing
before and after the renumber. A history query over renumbered steps is gibberish.

**This is the interaction with (4) the argument asks about, and it is the one that bites.**

**The fix, and it is standard and cheap:** **fractional / gapped indexing.** Make `step_index` a
`number` (not `integer`) in the property schema, mint initial steps at 1000, 2000, 3000…, and insert
between two neighbours at their midpoint. One row written, no renumber, history stays coherent,
sorting is unchanged. (Lexicographic rank strings — the Figma/LSEQ approach — are the rebalance-free
variant if float precision ever becomes a concern; it will not at k ≤ 30.) The cost is that
`step_index` is no longer the human-readable ordinal — so render position from the sorted result, and
never show `step_index` to a user.

**Second, smaller fix:** with a fractional index, **steps become immutable after creation.** A route
change is tombstone-old + create-new, never a patch. That is what makes §4.2's interval model exact,
and it should be a stated rule, not an emergent habit.

**Cost:** one line in a JSON Schema (`"type": "number"`), one helper that computes a midpoint, and a
rule in the spec. No index, no migration, no column.

---

# Part 2 — How TAP should do this

## 2.0 The one-paragraph answer

**Relax `req-grid-edge-nono` to a declared, depth-capped exception, and build the path as a node
whose steps are `HAS_STEP` edges pointing at the traversed edges' backing `Entity` rows.** The
relaxation needs **no migration and no JSON-schema change**, because `Edge.to_entity` is already
`ForeignKey(Entity)`, an edge already has an `Entity`, and `"edge"` is already a declarable target in
`edge-definition.schema.json`. It is *not* four lines: it is four lines plus eight places that
silently assume the old rule (§3.3), three of which give a **wrong answer rather than an error** —
GRIFT export drops the step, the sweep guardrail skips it, and hard purge orphans it. In exchange you get argument 3 satisfied
exactly, the tombstone cascade wiring path breakage for you in the same transaction (**RAN**), and
path history as an indexed interval query with no time-travel machinery (**RAN**). The only genuine
cost is depth, and depth is enforceable in the same four lines — I have a failing depth-2 case to
prove the cap is load-bearing rather than decorative.

## 2.1 The data model

### Tables: **one new, zero altered.**

**`tap_grid_path` — a new `BaseModel` subclass, `ENTITY_TYPE = "path"`.**

| Field | Type | Notes |
| --- | --- | --- |
| `entity` | `OneToOneField(Entity)` | inherited from `BaseModel` |
| `name` | `CharField` | the declared name |
| `kind` | `CharField`, choices `{"authored", "observed"}` | see 2.3 |
| `description` | `TextField` | |
| `integrity` | *derived, not stored* | computed by the read; see 2.4 |
| `verified_at` | `DateTimeField(null=True)` | last time the route was revalidated |
| `captured_by` | `FK(Search, null=True)` | for `observed`: the query that produced it |
| `batch_id`, `flip_map` | inherited | |

`NATURAL_KEY = ("name", "kind")` for `authored`; `KEYLESS` for `observed` with the reason *"an
observed route is an evidence record, not a named thing; it correlates by capture, not by key."*
(The red team's F5 fork is real and the authored/derived split — its F3 conclusion — resolves it.
I am adopting both.)

Guards this must satisfy at class definition (**READ**, `models.py:588-750`): `ENTITY_TYPE`,
`NATURAL_KEY` or `KEYLESS` + `NATURAL_KEY_REASON`, `FIELD_CRUD_SCHEMA`, and `GRID_TABLE_ROLE` must
**not** be declared (it is inherited as `domain`; declaring it fails at import).

**No new step table.** A step is a `HAS_STEP` `Edge`. That is the whole point.

**One correction to a claim both prior documents make, and I made it too in an earlier draft.**
"GRIFT round-trips a node-plus-edges structure for free" is **false for the edge-endpointed form**.
`tap_grid/grift/exporter.py:256` builds `exported_node_ids` by excluding `entity_type=Edge.ENTITY_TYPE`,
and `:372` then drops any edge whose endpoint is not in that set:

```python
372:  if edge.from_entity_id not in exported_node_ids or edge.to_entity_id not in exported_node_ids:
373:      ledger.record(SKIP_EDGE_ENDPOINT_NOT_EXPORTED, edge.entity_id)
374:      continue
```

An edge-backed entity is **by construction** never in `exported_node_ids`, so **every `HAS_STEP`
step would be silently dropped from every GRIFT export**, recorded under
`SKIP_EDGE_ENDPOINT_NOT_EXPORTED`. Not an error — a skip ledger entry. The exporter is therefore on
the required change list, and "free round-trip" must come out of the pitch.

### Edge type: `HAS_STEP`

Declared as an ordinary `.edge.json`, using keys that already exist in
`edge-definition.schema.json` (**READ**) — **no schema change to the edge-definition format**:

```json
{
  "slug": "HAS_STEP",
  "name": "Has step",
  "description": "Orders one traversed edge, or one nested sub-path, within a path.",
  "sources": ["path"],
  "targets": ["edge", "path"],
  "property_schema": {
    "type": "object",
    "additionalProperties": false,
    "required": ["step_index"],
    "properties": {
      "step_index":        {"type": "number", "description": "Fractional rank. Order by this; never display it."},
      "direction":         {"type": "string", "enum": ["forward", "reverse"], "description": "Orientation in which the edge was traversed."},
      "observed_batch_id": {"type": "string", "description": "The traversed edge's batch_id at capture. Freshness only; never identity."},
      "branch":            {"type": "string", "description": "Branch label when the path forks. Absent, not empty, when linear."}
    }
  }
}
```

Three things to notice:

- **`"targets": ["edge", "path"]` is the declaration surface, and it already exists.** `"edge"` is a
  real entity type slug (`Edge.ENTITY_TYPE = "edge"`, **READ**, `models.py:1036`), and
  `register_edge_type_constraints` already parses `targets` into a set of type slugs
  (`constraints.py:198-236`, **READ**). **The exception is declared, not special-cased** — which is
  what makes it narrow and auditable rather than a general relaxation.
- `step_index` is `number`, not `integer` — fractional indexing per §5.
- `observed_batch_id` is data, and it is the *one* place (b)'s id-as-data shape is correct, because
  it snapshots a value rather than referencing a row.

### Indexes: **none new.** Measured, §1 and §5.

## 2.2 The integrity rules

**R1 — Depth cap of one, enforced at write.** An edge may have an edge endpoint only if the target
edge does not itself have one. Replacing `_impl.py:605-609`:

```python
# Step 7: Graph invariant — edges may reference edges only one level deep,
# and only where the edge type declares "edge" as a permitted endpoint.
# The cap is not stylistic: the incident-edge pass is a flat bulk update,
# so a second level would leave a live edge onto a tombstone and break
# req-grid-service-delete-tombstone-7. Proven by the depth-2 case in
# test_edge_endpoint_depth.py.
for role, endpoint in (("from_entity", from_entity), ("to_entity", to_entity)):
    if endpoint.entity_type != "edge":
        continue
    if not _edge_endpoint_declared(op.edge_type, role):
        raise ServiceConstraintError(
            f"Edge type {op.edge_type!r} does not declare an edge endpoint ({role})."
        )
    if _has_edge_endpoint(endpoint.pk):          # the §1 lookup: 0.010 ms, RAN
        raise ServiceConstraintError(
            f"Edge {endpoint.pk} already references an edge; endpoints are capped at depth 1 ({role})."
        )
```

`_has_edge_endpoint` is argument 1's query, and this is where argument 1 becomes load-bearing after
all — **not for reading paths, but for enforcing the cap on every edge write.** That is the honest
place for it, and 0.010 ms per write is affordable. (INFERRED: at collector scale — 10k edges in one
batch — this is 10k extra index probes inside one transaction, ~0.1 s. Measure before claiming it is
free; and note the probe only runs when an endpoint is an edge, which for ordinary collector traffic
is never.)

**R2 — Standing invariant query.** The red team correctly noted there is no invariant query for
edge-to-edge, only a create-time raise. Add one beside `live_onto_tombstones()`:

```python
@classmethod
def edge_endpoints_beyond_depth_one(cls) -> BaseModelQuerySet:
    """Edges whose endpoint is an edge that itself has an edge endpoint — the set R1 says is empty."""
```

Assert it in both corpora after every scenario, exactly as the tombstone invariant is.

**R3 — Steps are immutable after creation.** A route change tombstones the old step and creates a
new one. Never a patch of `step_index` or `direction`. This is what makes §4.2's interval query
exact. Enforce by declaring `HAS_STEP` properties absent from the patch/replace surface.

**R4 — Ordering is fractional.** §5. Mint at multiples of 1000; insert at midpoints.

**R5 — Acyclicity in the incidence relation.** R1 (depth ≤ 1) implies it trivially: you cannot form
a cycle in a relation of depth one. Worth stating so nobody later "just relaxes the cap a little".

**R6 — A path is visible only if every step is visible (deny-on-partial).** Adopted wholesale from
the red team's F9, which I have no new evidence against and which is correct on the
*over-restriction relaxes cheaply* principle. A path with holes is a different and **false**
assertion, and silent omission from an ordered structure leaks the shape of what was omitted.

## 2.3 What the tombstone cascade must do

**Mostly: nothing new.** This is the finding, and it is observed.

| Event | Required behaviour | Status |
| --- | --- | --- |
| Traversed edge is tombstoned | its `HAS_STEP` edges tombstone in the same transaction | **works today, RAN** |
| Tombstone invariant after that | `live_onto_tombstones()` empty | **holds, RAN (0 violations)** |
| Step's spine row after that | `deleted_at` set, `version` bumped | **RAN (1→2)** |
| Broken step remains identifiable | `to_entity_id` preserved on the tombstoned row | **RAN (True)** |
| Depth 2 | must be impossible | **R1 — the cap is required; RAN shows the violation without it** |
| Path node when a step dies | stays **live**, marked `broken` by a derived read | **new, see 2.4** |
| Path node is tombstoned | its `HAS_STEP` edges tombstone (incident pass) | **works today** |
| `HAS_STEP` declared as a `CONTAINMENT_EDGE` | **NEVER.** Containment cascades downward; `path --HAS_STEP--> x` as containment means retiring a path deletes the RDS instance it runs through | red team F3 refutation 2, and it is right |
| Cascaded step retirement provenance | should record a `BatchEvent` naming the consequence | **GAP — RAN: `batchevents=[]`. File it.** |
| **Hard purge** of a traversed edge | must also purge the referring step's spine row | **BROKEN — RAN: orphaned ghost `Entity`. FM2c.** |
| GRIFT sweep retires a traversed edge | referential-integrity guardrail must apply | **BROKEN — Guardrail B skips edge candidates. FM2b.** |

**One change to file, one to specify.** The gap in the last row (§4.4 item 1) is a defect in edge
retirement provenance generally, not a path problem — the cascaded-provenance loop is guarded on
`state is not None`, which is `None` for every delete that is not a contained `delete_node`
(`_impl.py:875`, **READ**). Filing it independently is the right move; paths make it visible, they do
not cause it.

## 2.4 Breakage, not `Flaw`

Adopted from red team F4, which is correct and well-evidenced: `spec-tap-flaw-v0.md:17` —
*"If a 'Flaw' can fire during correct operation, it is miscategorized"* — and infrastructure changing
is correct operation. Path breakage is a **derived state on the read**, shaped like
`grid__cascade_failure` (tap#659/#668):

```
intact           — every step live, count == expected
broken@step_n    — a step is tombstoned AND its target edge's deleted_at is non-null
rerouted@step_n  — a step is tombstoned AND its target edge is still live
unverified_since — verified_at older than policy
```

Note `broken` vs `rerouted` is a *join*, not a field — cheap, and only possible because the
tombstoned step still names the edge (**RAN**). Under (b) neither state is computable at all.

## 2.5 What `req-grid-edge-nono` should say

The current rationale is formally wrong and the dossier is right about why (§III.3 second, **READ**):
edges-about-edges generalises *recursion*, not *arity* — the Levi incidence graph relaxes from
bipartite to DAG. That is an **ubergraph**, not a hypergraph. Edge arity stays binary. Nothing about
traversal complexity follows from the word "hypergraph", and a wrong reason is a defence that
collapses the first time someone informed pushes on it — which is what has now happened twice.

**Retitle: "Edge Endpoints Are Nodes, Except Where Declared".** Status stays `Implemented`; the
rationale and the ACs change.

Proposed rationale:

> Edges model relationships between things. An edge whose endpoint is an edge is formally an
> **ubergraph**, not a hypergraph — arity is unchanged; what relaxes is that the incidence graph
> becomes a DAG rather than bipartite. TAP permits exactly one level of that relaxation, and only for
> edge types that declare it, because one construct requires it: a path step must name the *specific
> edge instance* traversed, and `(from_entity, edge_type, to_entity)` does not identify an edge on a
> multigraph.
>
> The cap at depth one is not stylistic. The delete cascade's incident-edge pass is a flat bulk
> update, not a recursive walk, so a second level leaves a live edge pointing at a tombstoned one and
> violates `req-grid-service-delete-tombstone-7`. A depth-2 case is included in the cascade corpus as
> a negative control.

Acceptance criteria (replacing `-1`/`-2`, keeping `-3`/`-4`):

| ACID | Title | Description |
| --- | --- | --- |
| `-1` | Undeclared Edge Endpoint Refused | `create_edge()` raises if either endpoint's `entity_type` is `"edge"` and the edge type's definition does not list `"edge"` in the corresponding `sources`/`targets`. |
| `-2` | Depth Capped At One | An edge endpoint that itself has an edge endpoint is refused. |
| `-5` | Declaration Is The Only Gate | No hard-coded allow-list of edge type slugs. The permission comes from the `.edge.json` declaration and nowhere else. |
| `-6` | Standing Invariant | `Edge.edge_endpoints_beyond_depth_one()` returns no row at any committed state; asserted after every cascade- and batch-corpus scenario. |
| `-7` | Cascade Ends The Referring Edge | Tombstoning an edge tombstones every edge referencing it, in the same transaction. |
| `-3` | Check Precedes Constraint Validation | unchanged |
| `-4` | Schema Does Not Enforce | unchanged, intentional |

And **delete the duplicate.** The rule exists twice, untagged — `_impl.py:605-609` raising
`ServiceConstraintError` and `services/__init__.py:1563-1568` raising `InvalidEdgeError` (**READ**,
and **RAN**: my probe got `InvalidEdgeError`, so the `__init__.py` copy is the live one for
`create_edge`). That is a standing `req-tap-known-dupes` finding nobody has filed; relaxing the rule
in one copy and not the other is a security-shaped bug waiting to happen.

---

# Part 3 — Failure modes, blast radius, migration

## 3.1 Failure modes of this recommendation

**FM1 — The depth cap leaks through a write path that does not go through `create_edge`.**
`req-grid-edge-nono-4` is explicit that the schema does not enforce this (**READ**), and I proved it:
`unguarded_write()` + direct ORM created both a depth-1 and a depth-2 edge, and the depth-2 one broke
the invariant (**RAN**). The write guard (`tap_grid/write_guard.py:178`) blocks direct ORM saves in
normal operation — it fired on my first probe attempt (**RAN**) — but `unguarded_write()` exists for
tests, admin and migrations. *Mitigation:* R2's standing invariant query in both corpora, so a leak
is caught by the same machinery that catches tombstone leaks. *This is the failure mode I rate most
likely.*

**FM2 — GRIFT: three refusal layers on import, and a silent *drop* on export.** The export bug
above (§2.1) is the serious half and is new in this pass. On import there are three layers, and the
red team reported only the first:

- *Same-batch refs.* `node_refs` is populated solely from the batch's `nodes` array
  (`tap_grid/grift/refs.py:116-121`), so an endpoint naming an edge's ref yields
  `"Edge endpoint … names no node ref of this batch"` (`:135-142`).
- *Literal ids.* The resolution loop runs only when the symbolic key is present —
  `_ENDPOINTS = (("from_entity_id","from_ref"), ("to_entity_id","to_ref"))` (`refs.py:32`) and
  `if ref_key not in payload: continue` (`:128-131`). **A batch supplying the literal
  `to_entity_id` of an already-existing edge never touches the ref machinery.** The importer's
  fallback existence check is `Entity.objects.filter(pk=…, deleted_at__isnull=True).exists()`
  (`importer.py:1875-1899`) — **it does not filter on `entity_type`**, so such a reference passes
  preflight undetected.
- *Service backstop.* GRIFT's create path routes through `write_batch` with `verb="create_edge"`
  (`importer.py:2643, 2719`), landing on the same chokepoint as everything else.

So the real import constraint is a **sequencing** one — a collector cannot create the traversed edge
and the step that names it in the *same* batch — not a format one. The document schema needs **no
change**: `from_entity_id`/`to_entity_id` are plain `format: uuid` strings
(`grift-document.schema.json:107-160`); "must be a node" appears only in `description` prose.

*Mitigation:* v0 authors paths through the service layer only (§3.3); collector-authored steps land
edges in batch N and steps in batch N+1. *What would make me wrong:* if the first real use case is
collector-produced observed paths, the exporter fix and the ref-set fix are not fast-follows — they
are the main work.

**FM2b — The GRIFT sweep's Guardrail B is a load-bearing comment whose premise this falsifies.**
`tap_grid/grift/importer.py:3342-3346`:

```python
# Guardrail B — referential integrity (node candidates only).
# For an edge candidate, Guardrail B is implicit: the edge itself is
# being swept, so edges-referencing-edges doesn't apply (TAP's edge
# model rejects edge-as-endpoint). So we only check for nodes.
if entity_type != "edge":
```

Once a step can reference an edge, a force-reimport sweep can retire an edge candidate while a live
`HAS_STEP` still points at it, because the referential-integrity check is **unconditionally skipped**
for edge candidates. This is the highest-value non-obvious finding in the blast-radius survey: the
comment is correct today and becomes a silent defect the moment the rule changes. It must be fixed in
the same PR as the relaxation, not after.

**FM2c — Hard purge produces an orphaned ghost `Entity`. This is a genuinely new failure class and I
reproduced it. RAN:**

```
before purge: s1 Edge row exists: True | s1 Entity row exists: True
after hard-delete of eA's Entity row:
  eA Entity exists  : False
  s1 Edge row exists: False
  s1 Entity row exists: True
  GHOST: entity_type='edge' deleted_at=None with backing Edge row? False
```

The mechanism (**READ**): `Edge.to_entity` is `ForeignKey(Entity, on_delete=CASCADE)`
(`models.py:1073-1077`), so hard-deleting the traversed edge's `Entity` row DB-cascades into the
**`Edge` row** of the step that points at it. But `BaseModel.entity` is
`OneToOneField(Entity, on_delete=CASCADE)` (`models.py:675-679`) — it cascades parent→child, not
child→parent — so the step's **own `Entity` row survives**. The result is a **live spine row with
`entity_type='edge'`, `deleted_at=None`, and no `Edge` record behind it** — and `live_onto_tombstones()`
cannot see it, because that query reads the `Edge` table, from which the row is gone.

`purge_edge` (`services/__init__.py:944`) does a bare
`Entity.objects.filter(pk=target_uuid).delete()`. The GRIFT sweep's purge has the identical asymmetry
(`importer.py:3472, 3482, 3505`): node candidates get an explicit "cascade-hard-delete attached edges"
pass; edge candidates fall straight through to the bare delete.

*Mitigation:* purge must enumerate and purge referring edges the way it already does for nodes — the
asymmetry is the bug. *Containment:* purge is DEBUG-only by spec
(`spec-grid-service-delete.md:151`), so this is not a production-data risk, but it **is** a dev-reset
footgun that will produce confusing state, and it must be fixed in the same change.

**FM2d — The corpus cannot express the test scenario until the loaders are relaxed.** Both
`tap_grid/cascade_corpus/loader.py` and `tap_grid/batch_corpus/loader.py` reject, **at scenario-load
time**, any fixture whose edge `from`/`to` does not resolve to a declared *node* ref
(`CorpusError: "edge refs must be unique and distinct from node refs"` / `"names no node"`). So R2's
corpus family is **blocked on a loader change**, upstream of and independent from everything else.

**FM2e — The oracle would falsely AGREE with a buggy implementation.**
`tap_grid/batch_corpus/model_oracle.py:310-316` carries the *identical* flat single-hop assumption as
production `_impl.py:861-889`:

```python
for other in state.rows.values():
    if other.kind == "edge" and other.live and other.ends is not None and row.name in other.ends:
        _end_edge(other, event=False)   # flat — never recurses into edges pointing at `other`
```

The oracle's whole purpose is to be an *independent* check (`req-grid-cascade-corpus-oracle-3`: it
imports nothing from the service layer or the ORM). **If both sides share the blind spot, a depth-2
scenario gets false agreement and the defect ships green.** The oracle must be fixed in the same
change as the production cap, and the depth-2 case must be a *negative control* (an expected refusal),
not a cascade scenario — because a cascade scenario is exactly what both would get wrong together.
`tap_grid/cascade_corpus/model_oracle.py` is a bigger lift: its `Graph` dataclass has no concept of an
edge endpoint at all.

**FM3 — "Path" becomes the billion-row table.** The dossier's cardinality argument (§III.5 ruling 3)
is sound: a pipeline that mints paths is a different product from a human naming three. *Mitigation:*
`kind="authored"` only in v0; `observed` requires an explicit act, a retention policy, and a cap.
*Falsifier:* if expected materialised paths per month exceeds ~100, revisit.

**FM4 — Nobody retires an observed path.** Red team F3 is right and I have nothing to add: a derived
path has no external source, so `req-grid-reconcile-falsifier-1` makes it immortal. *Mitigation:*
declare paths outside reconcile explicitly, and make `observed` paths replaced-wholesale caches with
a TTL, never reconciled objects.

**FM5 — Fractional indices drift under heavy editing.** Repeated midpoint insertion at the same
position exhausts float precision after ~50 inserts between two neighbours. *Mitigation:* a rebalance
on a threshold, or lexicographic rank strings. INFERRED; irrelevant at k ≤ 30 but worth a note.

**FM6 — `version` as a staleness signal is noisy until tap#322.** The dossier is right that the whole
freshness layer rests on a version bump meaning something. **But note the scope correction in §4.4
item 3: the *intactness* mechanism uses `deleted_at`, not `batch_id` or `version`, and is not
blocked.** Only the optional freshness layer is.

## 3.1b Three divergent silent behaviours — no crashes anywhere, and that is the problem

The survey traced every read path. **Nothing crashes and nothing raises a dangling-reference error.**
What happens instead is three different silent outcomes depending on which backend fed the query, and
that inconsistency is itself a defect surface worth deciding on deliberately.

- **Gryphon, unlabeled far node** (`MATCH (a)-[:HAS_STEP]->(b)`): `_build_chain_queryset`
  (`executor.py:1989-1992`, **READ**) applies an `entity_type` filter to an endpoint **only if the
  pattern labels it**. Unlabeled, the plain FK join traverses onto the edge-backed entity
  **mechanically, with no code change required** — the traversal already works the moment the write
  check permits the data. The endpoint then lands in the envelope's `"nodes"` array, but
  `batch_resolve_typed_models` (`grift/subgraph.py:318-331`, **READ**) *skips* `entity_type="edge"`
  when resolving typed models, so it serialises with **spine fields only** — no `from_entity`, no
  `to_entity`, no `edge_type`, no `properties`. A blank node where the traversed edge should be.
- **Gryphon, labeled far node** (`(b:some_type)`): the label can never equal `"edge"`, so the hop
  matches **zero rows**. Invisible, not an error.
- **Viz**: `panel-graph.js:457-462` (**READ**) only hands Cytoscape an edge if *both* endpoints are
  already in the node set. So an ORM-DSL- or export-backed panel **silently never renders** the step,
  while an unlabeled-Gryphon-hop-backed panel renders it **connected to a blank, unstyled node**.

**And there is no depth enforcement anywhere on the read side.** The executor has no notion of a
one-level cap; `MATCH (a)-[:HAS_STEP]->(b)-[:HAS_STEP]->(c)` would execute without complaint if such
data existed. **The cap must be airtight at write time, because nothing downstream will catch a
violation after the fact.** That is the strongest argument for R2's standing invariant query.

**The envelope decision this forces:** a traversed edge must be serialised into the envelope's
`edges` array, not smuggled into `nodes` as a spine-only husk. `orm_compiler.py:86` excludes edges
from the node *root* set (**READ**: `Entity.objects.using(db_alias).exclude(entity_type="edge")`) but
the hop-endpoint queries at `:118` and `:183` carry no such exclusion — so an edge-backed entity can
**already** leak into a `nodes` array through a one-hop traversal today, under a different edge type.
That is a pre-existing seam, not one this change creates, but this change makes it routine.

## 3.1c Two adjacent facts the survey settled

**Dimension scoping on reads: REFUTED, not merely uncorroborated.** The red team listed this under
"what I could NOT verify" and flagged F9 as conditionally fatal on it. It is now settled, from the
primary specs. `spec-grid-dimension.md:68-98` (**READ**) carries a section literally headed
*"Future (idea): Dimensions as a database-enforced security gate (Postgres RLS)"* and states
**"Deliberately deferred, not planned."** `spec-tap-auth-v0.md:1219` (**READ**), under `## Backlog`:
*"Dimension-scoped grid authorization. **When built**, dimension/object-scoped read authorization MUST
be pushed into the Gryphon/Search query planning + execution surface."* And in code: `search.py` and
`read_guard.py` contain **zero** dimension references; `executor.py`'s hits are all `dimensions` as a
*queryable spine field* a query author opts into, not scoping applied to a caller. `read_guard.py` is
a binary `grid.read` backstop with no per-row predicate.

So F9's inference channel **does not exist today** — and F9 was explicit that it is void if dimensions
never become an authz boundary. But `spec-tap-auth-v0.md` says "when built", not "if". R6
(deny-on-partial) therefore stands as the cheap forward commitment, on the
*over-restriction-relaxes-cheaply* principle, and it costs nothing to adopt now.

**There is no static guard for this rule.** `tap_grid/guards/` is a 7-line `__init__.py` docstring
stub — **no guard file exists there** (**RAN**, `ls`/`wc -l`). Enforcement is *only* the two runtime
service-layer checks. That is exactly why R2's standing invariant query matters: today the rule has a
create-time raise and nothing else.

**The traceability ratchet is the gate that actually binds the PR.** `tap/guards/unaccounted_ratchet.py`
(**READ**): `ratchet_ceiling` computes `new = sorted(current - baseline)` and **hard-fails** on any
non-empty `new` (`tap/ratchet.py:111-150`). Every new `req-grid-edge-nono-*` AC minted in §2.5 needs,
**in the same PR**, either a `TAP-IMPLEMENTS` claim (`scripts/implements-tag <rid>`) / a
`@pytest.mark.spec`-decorated test, or a `Trace:` disposition beside its `Status:` line. And verbatim
from the guard: *"Never add it to the baseline: the baseline is grandfathered debt, not a place for
new entries."*

## 3.2 What it would take for this to be wrong

- **If argument 3's requirement is actually satisfied by an edge *class* predicate.** The dossier's
  §III.3 third claims the July declared-path ruling dissolves the edge-to-edge need. It would, if
  paths were only ever declarations. George has ruled they are not. *If that ruling reverses, the
  dossier's deferral is correct and this document's recommendation is over-built.*
- **If someone shows the depth cap is unenforceable.** I have shown depth 2 breaks the invariant and
  that the fix is one lookup. If the cap turns out to leak through a path I did not test (the GRIFT
  importer's own edge creation, in particular — it is a 3,863-line module I did not read), the
  recommendation needs a schema-level check constraint, which changes the migration story from zero
  to one.
- **If a measured collector-scale write regression appears from R1's probe.** I have not measured it
  (INFERRED only). If landing 10k edges gets materially slower, the probe must be conditioned or
  moved.
- **If path ordering turns out to be decoration.** The dossier's falsifier is a good one and I am
  adopting it verbatim: once paths exist, randomise step order and see whether any answer changes. If
  nothing does, membership was the product and a dimension was the right design.

## 3.3 Migration path — and the smallest v0 that satisfies argument 3

**Yes, this ships incrementally.** Four steps, each independently landable.

**Step 0 (independent of paths, land first).** File and fix the cascaded-retirement provenance gap
(§4.4 item 1) and delete the duplicated edge-nono check. Both are pre-existing defects that paths
merely expose. Neither needs a ruling.

**Step 1 — the exception. The smallest thing that satisfies argument 3.**

I drafted this as "plausibly one PR" before the blast-radius survey came back. **It is not.** Here is
the honest minimum, and every item is something that *silently misbehaves* if you relax only the two
write checks:

| # | Site | Why it must move in the same change |
| --- | --- | --- |
| 1 | `_impl.py:605-609` **and** `services/__init__.py:1563-1568` | The two enforcement copies. Relaxing one and not the other is the bug. |
| 2 | `grift/refs.py:116-142`, `importer.py:1367, 1580` | Same-batch refs and the `file_node_ids` set must become edge-aware for declared types. |
| 3 | `importer.py:3342-3346` (Guardrail B) | FM2b. Its comment's premise becomes false; a sweep silently orphans steps. |
| 4 | `grift/exporter.py:256, 372` | FM2/§2.1. Otherwise steps are silently dropped from every export and the feature is invisible to GRIFT. |
| 5 | `services/__init__.py:944` (`purge_edge`), `importer.py:3472-3505` (sweep purge) | FM2c. Ghost `Entity` rows. **RAN**. |
| 6 | `_impl.py:861-889` | No change needed *if* the write-time cap is airtight — but that is exactly why R2's standing invariant is not optional. |
| 7 | `batch_corpus/model_oracle.py:310-316` | FM2e. Same blind spot ⇒ false agreement. |
| 8 | `cascade_corpus/loader.py`, `batch_corpus/loader.py` | FM2d. The fixture cannot be authored until these accept an edge endpoint. **Upstream of everything else — do this first.** |
| 9 | `spec-grid-edge.md` §2.5 + new ACs with same-PR traceability dispositions | The ratchet fails closed otherwise. |

Items 3, 4 and 5 are each a *silent* wrong answer rather than a failure, which is the worst shape a
change can have. **Sequence 8 → 1 → 6/7 → 3/4/5.** Realistically two or three PRs, not one. Steps 2-4
below remain as stated.

At the end of Step 1, argument 3 is satisfiable: a plugin declares an edge type with
`"targets": ["edge"]` and can record a specific traversal, round-trip it through GRIFT, and have the
cascade end it correctly. **No new model, no migration, no schema change to either JSON schema.**

**Step 2 — the path node.** Add the `Path` `BaseModel`, the `HAS_STEP` edge definition with its
property schema, and service helpers (`create_path`, `append_step`, `insert_step_after`). Reads go
through Gryphon/the envelope as ordinary nodes+edges — **GRIFT round-trips it with no format change**
because a path is a node and its steps are edges.

**Step 3 — integrity and history.** The derived `integrity` state (§2.4), the as-of interval query
(§4.2), and a panel. This is where the "blow minds" demo lives, and it needs nothing from the
time-travel pass.

**Step 4 — deferred, explicitly.** Observed/materialised paths, collector-authored steps (the GRIFT
change), freshness via `observed_batch_id` (behind tap#322), sub-path nesting beyond depth 1, and
negative path claims ("there is no route from X to Y", which needs E1 *and* a composed
cross-collector completeness statement, neither of which exists).

**And the thing that must ship with Step 2, not after it:** breakage. Red team point 3 is right —
a path with no integrity signal is a confident lie that degrades. But note this recommendation makes
that requirement *much* cheaper than the red team assumed, because the cascade already writes the
breakage event; Step 3 only has to *read* it.

---

# Part 4 — Scorecard

| # | Argument | Verdict | One line |
| --- | --- | --- | --- |
| 1 | Fast lookups via existing indexes | **HOLDS (measured)** | 0.010 ms pure index scan on `idx_edge_to_type`; **RAN**. Not load-bearing for reads — but it *is* what makes the depth cap affordable on writes. |
| 2 | Single node for a path; sub-paths | **PARTLY** | Single-node: holds, free, `Search` is the precedent. Sub-paths: holds but needs **no** edge-to-edge — a path is a node, so `path→path` is legal today. Remove it from the edge-to-edge case. |
| 3 | Specific edge traversals — HARD REQUIREMENT | **HOLDS; decisive** | Premise verified: parallel same-type edges share `(from, type, to)` and differ only by id (**RAN**). (a) and (c) are literally the same row; the choice is FK-or-data, and data loses on integrity and cascade. |
| 4 | FLIP + history trace path change | **PARTLY — wrong mechanism, better capability** | FLIP is current-state-only by spec; all four history query methods `raise NotImplementedError`; `Entity` has no history table; a tombstone writes no historical row. **But** soft tombstones give a free valid-time interval model, and only representation (a) has the cascade write the interval's end. Probably the strongest argument, for a reason George did not give. |
| 5 | Ordered retrieval by step number | **HOLDS on speed, FAILS on insertion** | 0.315 ms for 939 steps warm, no index needed (**RAN**); a composite index is *no faster* (**RAN**). Dense integer indices make mid-insert O(k) writes and corrupt the §4 history. Use fractional indices. |

**Does argument 3 make the others moot?** As *reasons*, yes — 3 alone decides the design, and 1, 2
and 5 would not have. As *facts* they still matter: 1 is what makes the depth cap cheap to enforce, 5
names the one mechanism that needs a decision the arguments did not make, 2 removes itself from the
case, and 4 is the reason this is a product rather than a schema change.

**The weakest of the five is argument 2's sub-path half** — it is true, but it argues for paths being
nodes, which nobody disputes, and not for edges pointing at edges, which is the contested question.

**The one I would have expected to be weakest and is not: argument 4.** Its stated mechanism is
wrong in every particular, and the capability underneath it is real, free, and
representation-dependent in exactly the direction George wants. That is the finding I would put in
front of anyone re-reading the red team's F6.

---

## Appendix — what I ran

All against `tap_demo-dev` (31,479 edges, ~55k entities). Every mutation inside
`transaction.atomic()` ending in a deliberate rollback; **nothing persisted**.

1. `\d tap_edge` — index and FK inventory.
2. `EXPLAIN (ANALYZE, BUFFERS)` × 2 — the edge-has-edge lookup, undirected and typed.
3. `EXPLAIN (ANALYZE, BUFFERS)` × 4 — ordered step retrieval: JSONB cold, JSONB warm, unsorted warm,
   and a rolled-back temp table with a real int column + composite index (with and without
   `enable_bitmapscan`).
4. Probe 1 — service refuses edge→edge; direct ORM accepts; delete the inner edge; observe the
   cascade, the invariant, `all_objects` readability, `BatchEvent`s, `HistoricalEdge` counts, and
   `hasattr(Entity, "history")`.
5. Probe 2 — two parallel same-type edges (identity check); a depth-2 chain; delete the innermost;
   observe depth-1 cascade success and the depth-2 invariant violation.
6. Probe 3 — hard-delete (purge shape) of a referenced edge's `Entity` row; observe the orphaned
   ghost spine row (`entity_type='edge'`, `deleted_at=None`, no backing `Edge`).

Scripts are in this session's scratchpad (`probe.py`, `probe2.py`, `probe3.py`), not in the repository tree.

**Not measured, stated as INFERRED:** behaviour at 10M edges; the write-path cost of R1's probe at
collector scale.

**Read but not executed** (delegated survey, every site cited by file and line): the GRIFT importer,
exporter and ref resolver; the Gryphon executor's chain builder; the viz panel's client filter; both
corpus loaders and both model oracles; `read_guard.py`; the traceability ratchet. Their *runtime*
behaviour under an edge endpoint is INFERRED from the code, not observed — with the single exception
of the purge ghost, which I reproduced.
