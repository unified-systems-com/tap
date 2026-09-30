---
title: Time and observation standardization — design and execution plan
date: 2026-09-29
status: proposed — design settled in conversation, execution not started; step 1 requires George's
  ruling on Q129 (see the companion document below), which was pending as of this writing
audience:
  - developer
  - llm
related:
  - tap#322
  - tap#323
  - tap#886
  - tap#896
  - docs/misc/doc-grid-batch-provenance-and-grift-patch-semantics.md
  - docs/misc/doc-grid-reconcile-design.md
  - docs/misc/doc-grid-reobservation-prior-art.md
  - docs/misc/doc-grid-provenance-placement-prior-art.md
  - tap_grid/specs/spec-grid-entity.md
  - tap_grid/specs/spec-grid-node.md
  - tap_grid/specs/spec-grid-flip.md
  - tap_grid/specs/spec-grid-service-write.md
  - tap_grid/specs/spec-grid-dimension.md
---

> Captured from a support-thread session with George, 2026-09-29, continuing directly from
> `doc-grid-batch-provenance-and-grift-patch-semantics.md` — **read that document first.** It
> covers Q129 (batch provenance: FLIP, the spine, `BatchEvent`) and Q131 (JSON merge-vs-set
> semantics under patch) in full; both are cited here, neither is re-derived. This document covers
> what came after: a general time/observation model for the grid, and the complete execution order
> for everything decided across both documents. Written to be picked up cold, by a session with no
> memory of the conversation that produced it.

# Update 2026-09-30 — phasing, a gap on non-observed entities, and review corrections

**Everything in this document is Phase 2 or Phase 3 under epic tap#886 — it does not start until
Phase 1 ships.** Phase 1 is the companion document's Part 1 (the tap#322/#323 core fix) alone,
driven by an actual initiating incident: unblocking zizmor's updates and the vulnerability-
management pathway, which needs the multiple-history-bumps-per-write problem fixed and nothing else
this document proposes. George: "this won't be implemented as one big push." See tap#886 and Part 7
below for the phase split and updated execution order.

**A real gap George raised: this document, as first written, assumed every entity is eventually
"observed" at some point in real time — that's false for a whole class of entities TAP already
supports.** A planned network layout in a design dimension — a topology that doesn't exist yet, or
may never be built — was never observed by anything, ever, and may legitimately never acquire a
phenomenon time at all. Separately, a *planned* rollout that has a real target date is not this
case at all — that's a normal, real phenomenon time with a future bound, already covered (Part 1's
SOSA citation on forecasts already supports this; see also tap#896 finding 2). See the new section
under Part 1 below, "Operating outside time," for both.

**An independent review (tap#896) also checked this document against the code and against the
companion document's citations.** Two corrections landed here as a direct result, at the point each
applies: Part 5's proposed adoption of RFC 7396's null-deletes-a-key rule is withdrawn (conflicts
with `spec-grid-node.md`'s own ratified anti-pattern ruling); Part 6's known-unknown convention is
already ratified and partly Implemented elsewhere, so "formalize" becomes "adopt" in the execution
order. See the companion document's own "Update 2026-09-30" section for the full finding list —
several apply to code this document doesn't cite directly (evidence atomicity, a second write path
invisible to any diff) but constrain Phase 1's acceptance criteria, not this document's design.

# Why this document exists

Working through Q129's answer surfaced a bigger question underneath it: TAP has no coherent, named
vocabulary for "when did this happen" or "how do we honestly represent what we only partly know."
Both gaps were already visible in the codebase before this conversation — zizmor hand-rolling its
own `known_since` timestamp, github_core inventing its own `{"state": "unobservable", ...}` shape —
but neither had been named, and nothing prevented the next collector from reinventing either one
differently. This document names both, grounds each in real prior art rather than inventing from
scratch, and lays out the order to build them in.

# Part 1 — Three kinds of time, and why TAP needs to distinguish them

Most systems collapse "when this became true" and "when we found out" into one timestamp. TAP
can't, for a concrete, structural reason: its collectors make multiple API calls over real elapsed
time before committing one batch (github_core reads repos, then workflows, then jobs; aws_core
walks paginated resource lists), so even a perfect collector with zero bugs introduces jitter
between reading a fact and writing it. Three times, not two:

1. **Phenomenon time** — when the fact was true in the real world, according to the system of
   record. What matters for correlation ("what was happening around time T, across every entity
   type") and for anything that needs to reconstruct a real-world timeline, not a collection
   timeline.
2. **Collection time** — when the collector actually read the fact from the source. Distinct from
   phenomenon time (the collector can read something today that became true last week) and from
   grid-write time (the collector can read something now and not commit its batch for minutes).
3. **Grid-write time** — when the batch was actually written. Mostly already tracked today:
   `Batch.started_at`/`closed_at` give the batch-level range, `Entity.updated_at` (already on the
   spine, `auto_now`) gives a per-node approximation.

**Prior art, checked rather than assumed:**

- **W3C SOSA/SSN** (Sensor, Observation, Sample, and Actuator ontology) makes exactly this
  distinction, but only two-way: `sosa:phenomenonTime` (when the observed property held that value)
  and `sosa:resultTime` (when the observation's result was recorded). TAP's split of `resultTime`
  into collection-time and grid-write-time is a genuine, motivated refinement of SOSA — not a
  deviation from it — because SOSA implicitly assumes a sensor that reads and reports in roughly
  the same instant, and TAP's collectors don't.
- **Bitemporal modeling** (financial/regulatory systems, formalized in SQL:2011) makes the same
  distinction from the database side: **valid time** (when a fact was true) vs. **transaction
  time** (when the system learned it), tracked independently. TAP's `last_changed_batch_id` /
  `last_observed_at` split (from #323, see the companion doc) is already, unknowingly, most of the
  way to this pattern — this document is largely about naming what's already implicit and filling
  the one piece that's missing (phenomenon time itself).
- **W3C PROV**'s `used(activity, entity)` without a corresponding `wasGeneratedBy` is the
  activity-level version of "observed, didn't change" — already the shape `BatchEvent`'s new
  `OBSERVE` type gives it (see the companion doc, Part 1).
- **Datomic**'s "the transaction is an entity" is why `Batch` already being a first-class `Entity`
  (not a side table) was the right call from the start — precedent already in the codebase, not
  invented here.

## Where each time lives — spine vs. ledger, and why they're not treated the same way

**Phenomenon time: two columns on the Entity spine** (`phenomenon_time_start`,
`phenomenon_time_end` — see Part 2 for why two, not one). The justification is the same one that
already put `last_changed_batch_id` on the spine (see the provenance-placement prior-art survey):
one indexed query across every type beats a per-type union. Phenomenon time has no other table to
lean on — it's a fact about the entity itself — so it has to live directly on the spine to get that
correlation cheaply.

**Collection time: does NOT need the same treatment, and putting it on the spine would be wrong,
not just unnecessary.** The reasoning that forces phenomenon time onto the spine — "avoid a
per-type union" — doesn't apply to collection time, because `Batch` is already one shared, uniform
table regardless of entity type. `Entity.last_changed_batch_id`/`last_observed_batch_id` already
give a one-hop path from any entity to its batch, so "what did we learn in the last hour, across
every type" is already a single join (`Entity → Batch`), not a multi-table union. Collection time
gets cheap correlation for free through the pointer that already exists. `Entity.updated_at` is the
one accounting concession the spine already makes, and that's enough — the real detail belongs one
hop away, on `BatchEvent`, not duplicated onto the entity.

**Collection time lives on `BatchEvent`: two new columns** (`collection_time_start`,
`collection_time_end`, both nullable — see Part 3), populated only when the collector actually
knows them.

## Operating outside time — entities with no phenomenon time, and entities in the future

This design started from a collector's-eye view — a source observed a real thing at some real
moment — and that view doesn't cover everything the grid already holds. Two distinct cases, only
one of which the design as first written actually handled:

**A future-dated phenomenon time is not a null case — it's an ordinary interval with a future
bound, and nothing here needs to change for it.** A scheduled decommission, a planned cutover, a
rollout with a committed date: the fact will be true at a known or bounded future time. SOSA already
supports this directly (`sosa:phenomenonTime` after `sosa:resultTime`, its own documented forecast
case — see Part 1's citation). The invariant guarded in Part 3 (phenomenon time ≤ collection time ≤
grid-write time) is about *when a value was recorded relative to when it became true*, not about
whether the value itself points at the future — a forecast's phenomenon time is expected to be later
than its collection time, and the guard already treats that as the normal, non-exceptional case for
this kind of fact, not the clock-skew exception.

**A design-dimension entity — a planned network layout that doesn't exist yet, or may never be
built — was never observed at all, and phenomenon time may legitimately stay null forever, not just
"for now."** This is a different thing from an unknown value: it's not that nobody has looked yet
and might later; it's that there is nothing in the world for anyone to have looked at. Mechanically,
the null-means-unasserted convention from Part 3 already covers this with no new schema — null
already means "no time asserted," and "will stay unasserted forever because this was designed, not
observed" is a legitimate, permanent instance of that same null. The thing this document didn't
originally say, and needs to: **don't build any consumer (a freshness check, a staleness dashboard,
a reconciliation sweep) that treats a null phenomenon time as universally "missing, go investigate."**
For an entity that only carries a plan/design-type dimension membership (using the existing
dimensions mechanism, `spec-grid-dimension.md` — which specific dimension marks an entity as planned
rather than observed is a naming decision for whoever builds this, not a call this document makes),
a persistently null phenomenon time is correct and expected. For an entity carrying an
observed/live-collection dimension, the same null is a real signal worth flagging. The scoping rule
is: **key the expectation off dimension membership, not off the presence of the column** — the
column's null state is identical in both cases by design; only the surrounding context says which
meaning applies. This is one more reason (alongside tap#896 finding 2's caution) not to treat
phenomenon time as a blanket expectation for every Entity once the spine columns exist.

# Part 2 — Representing uncertain time: intervals, not error bars

Don't store a point plus an uncertainty magnitude (`timestamp ± N`). Store an **interval** —
earliest-known bound, latest-known bound — collapsing to a single instant when both bounds agree.
This is SOSA/OWL-Time's own answer to the same problem, not a TAP invention, and it's the right one
for a concrete reason a `±` value can't handle: real sources give **asymmetric** uncertainty. "This
vulnerability was introduced somewhere between commit A and commit B" isn't a midpoint ± N minutes
— it's a genuinely lopsided range. "This GitHub Actions run started at exactly this timestamp"
needs zero uncertainty at all. An interval represents both as the same shape; exact is just the
degenerate case where start equals end.

Applies to all three time concepts: `phenomenon_time_start`/`_end` on the spine,
`collection_time_start`/`_end` on `BatchEvent`. Two narrow scalar columns per pair — doesn't trip
the spine's own "header bloat" caution (per-field JSON maps are the thing to keep off the spine;
plain `DateTimeField` pairs are the same shape as what's already there).

# Part 3 — Precision is asserted, never defaulted

**A collector that doesn't know the precise time should leave the fields null — never default to
"now."** A defaulted value and a genuinely precise one are indistinguishable the moment both are
non-null, which destroys the exact distinction this whole design exists to preserve. This directly
extends the grid's existing convention (`natural_key`'s own doc: "null = never written, '' =
observed-empty") to a new pair of fields, rather than inventing a new rule.

**This also answers a question that came up during design and resolves it without new schema:**
does an observation need a separate "was this stamped or derived" state field? **No.** Null on
`collection_time_start`/`_end` already means "not asserted" — non-null already means "the collector
explicitly knew this." A third flag would be redundant with information the existing null
convention already carries.

**Corollary for anything that wants a best-effort time regardless of precision:** compute the
fallback at **read time**, not write time — "use the row's own value if present, else fall back to
the batch's `started_at`/`closed_at`." Baking a fallback into the write path would permanently
destroy the distinction between real and defaulted data; computing it at read time preserves the
distinction for anyone who cares while still giving a usable number to anyone who doesn't.

**A natural invariant worth stating and guarding, with one named exception:** phenomenon time (its
end bound, if a range) should be ≤ collection time ≤ grid-write time. The exception: clock skew on
the source side could make a *reported* phenomenon time look later than collection time — that
should be flagged as a signal, never silently coerced into looking consistent, the same spirit as
the reconciliation design doc's "an unknown selection must never read as a shrunken one."

**On the guard itself:** ship it as a hard stop for now. There will eventually be a real case that
needs to violate it — build the bypass then, against an actual use case, not speculatively now.
Matches the codebase's own existing instinct (shadow nodes: "DEFERRED, not a first-slice
prerequisite" is the same judgment call, made the same way).

# Part 4 — The collector-time input shape

**A new section in the write-batch call (and/or the GRIFT document), keyed by entity id**, letting
a collector optionally assert collection-time bounds per entity, separate from that entity's own
field payload — collection time isn't a *field* of the entity, it's accounting metadata about the
observation, so it shouldn't be mixed into the node's own data. This is not a new structural idea —
it's the same section-based pattern already chosen for GRIFT's `deletes`/`purges`/`patches`
(policy knobs, entity-keyed, its own object) applied to a new kind of metadata rather than invented
fresh. A collector that doesn't have the information simply omits the entry for that entity — same
null-means-unasserted discipline as Part 3.

# Part 5 — JSON path standards, and the connection to Q131

If per-key provenance ever gets built (see Part 6 of the companion document — explicitly deferred,
not in this execution plan), use **JSON Pointer (RFC 6901)** for path notation — slash-delimited
(`/location/city`), not dotted. A real IETF standard, existing tooling, no bespoke escaping rules to
invent (RFC 6901 already defines the escaping for a literal `~` or `/` in a key). **JSON Patch
(RFC 6902)** is the fuller sibling if a structured diff (not just a path) is ever wanted.

**Correction (2026-09-30, tap#896 finding 4): the missing half of RFC 7396 is not adoptable here,
and the earlier framing below was wrong.** `_apply_patch`'s `_deep_merge` (`services/_impl.py:75-83`)
is, structurally, an unnamed partial implementation of **JSON Merge Patch (RFC 7396)** — recursive
merge, update wins per key — and it is missing the RFC's other rule: explicit `null` on a key should
delete that key, not set it to `None`. That part of the observation stands. What doesn't stand is
the conclusion that follows it: **`spec-grid-node.md:396` already, explicitly, ratifies "JSON Merge
Patch's 'null = delete' is the anti-pattern"** as part of the grid's null-means-unobserved
convention (`req-grid-node-observation`) — a field's explicit `null` is a load-bearing assertion
("a source looked and found nothing"), not a deletion signal, and RFC 7396 would silently override
that for every JSON field the moment it's adopted wholesale. If a genuine per-key delete primitive is
ever needed under Q131's eventual resolution, it needs its own explicit, non-null marker — consistent
with the existing convention — not RFC 7396's null-based one. **RFC 6901 (JSON Pointer) is unaffected
by this correction** and still stands as the right path-addressing notation below and in Part 6, if
per-key addressing is ever built; only the null-deletes-a-key rule from RFC 7396 is withdrawn.

# Part 6 — The field-level known-unknown convention

github_core's `_ruleset_bypass_fields` (`collector.py`, ~line 3140) already does this, unnamed:
`{"state": "observed"|"unobservable", "reason": ..., ...}` — a field whose value is itself a
structured record of whether the field was actually readable, not silence and not a placeholder
default. Distinct from two things already in this design:

- **Shadow nodes** (reconciliation design doc, RULED 2026-09-15, DEFERRED) are node-level: "I don't
  have the object at all, just evidence it exists." This is field-level: the node is real and known,
  one specific field came back as an explicit refusal.
- **Patch's omission semantics** (the companion doc, Part 2) mean "didn't check this pass." This
  means "checked, and got a structured 'not allowed to tell you,' with a reason."

**Correction (2026-09-30, tap#896 finding 9): this already exists, ratified and mostly Implemented —
the step below is adoption, not formalization.** `spec-grid-node.md`'s `req-grid-node-observation`
(decided 2026-06-30) is this convention: the `x-tap-absence` field-schema annotation plus the
FLIP-presence hinge, with `req-grid-node-observation-3/4/6/7` already `Implemented`. github_core's
shape predates it and reinvents the same idea with different vocabulary. Nothing needs to be named or
spec'd — it already is; what's needed is migrating github_core (and any future permission-gated
collector) onto `x-tap-absence` instead of its own bespoke shape.

# Part 7 — Execution order, now split into phases (2026-09-30)

**Restructured per George: this is explicitly not a single push.** The original numbered list below
mixed one urgent, independently-motivated fix in with a much larger, still-partly-undecided design.
The phase boundary is deliberate pacing, not just dependency order — Phase 2 does not start merely
because Phase 1's dependencies are satisfied; it starts once Phase 1 has *shipped and been observed*
against real collector traffic (zizmor's actual re-scan cadence, specifically, since that's the
initiating incident). Within each phase, steps without a listed dependency can still proceed in
parallel.

## Phase 1 — the immediate target (entirely in the companion document, nothing here)

George's own ruling on Q129, then the tap#322 core fix (diff-before-write, `BatchEventType.OBSERVE`,
the two spine fields, the four consumer sites, dropping `BaseModel.batch_id`), now with the
evidence-atomicity, first-assertion, spine-sync-bypass, and historical-batch_id acceptance criteria
tap#896 added. Fully specified in the companion document's Part 1 and its new "Evidence durability"
section — see that document, not this one. **This is the only phase gated on the initiating
incident** (unblocking zizmor and the vulnerability-management pathway); everything below waits on
it shipping, not just being designed.

## Phase 2 — the time/observation model and GRIFT patch semantics (this document + companion Part 2)

Gated on Phase 1 shipped and validated, not merely landed. Ordered by dependency within the phase:

1. **Resolve Q131**, corrected per tap#896 finding 4 above: caller-intent-keyed JSON apply-semantics
   (GRIFT import wants wholesale-set, the panel editor wants deep-merge — key on caller intent, not
   field type). The RFC 7396 null-deletes-a-key idea is withdrawn, not part of this step anymore —
   if a per-key delete primitive is wanted, it needs its own non-null marker, a separate design
   question this step does not have to answer to close Q131.
   *Depends on: Phase 1 shipped. Blocks: the patch-default flip, below.*

2. **Phenomenon time range on the Entity spine**, including the "Operating outside time" scoping
   above (null is a legitimate permanent state for design/plan-dimension entities; consumers must key
   the "is this actually missing" question off dimension membership, not off the column's null-ness
   alone). Two columns, a `SPINE_FIELD_NAMES` update, the drift-guard test
   (`test_entity_spine.py`) catches any mismatch by construction.
   *Depends on: Phase 1 shipped (schema-independent, but sequenced here per the phase gate).*

3. **Decide the collector-time input shape (Part 4), then build the `BatchEvent` columns it feeds.**
   The shape decision has to precede the column design.
   *Depends on: Phase 1 shipped.*

4. **Build the `put`/`replace` GRIFT section** (schema-only; the companion doc's collector audit
   confirmed zero collectors currently need it, so this ships with no collector code changes).
   *Depends on: Phase 1 shipped. Blocks: the patch-default flip, below.*

5. **Flip `nodes`/`edges` to mean patch by default.** Only after step 1 (so the flip doesn't
   reintroduce the JSON-merge danger Q131 exists to prevent) and step 4 (so an escape hatch already
   exists for anyone who turns out to need full-replace) — doing this before either exists means a
   window where the risky change has shipped before either of its safety nets do. Also confirm, per
   tap#896 finding 5, that "zero collector changes needed" still holds against the full missing/live/
   tombstoned target matrix, not just the omission audit already done.
   *Depends on: steps 1, 4.*

6. **Update the `build-collector` skill** to document the patch/put choice for future collector
   authors.
   *Depends on: steps 4, 5.*

7. **Adopt the field-level known-unknown convention (Part 6, corrected)** — migrate github_core's
   `_ruleset_bypass_fields` onto the already-ratified `x-tap-absence`/`req-grid-node-observation`
   instead of its own bespoke shape. Not a spec exercise anymore (it's already specced); an adoption
   task, independent of the rest of Phase 2, that could in principle run any time after Phase 1 ships
   if someone wants to pull it forward.
   *Depends on: Phase 1 shipped (phase gate only — no technical dependency on steps 1-6).*

## Phase 3 — pilot and collector rollout

**Pilot the new capabilities on zizmor-tap, then extend to the rest.** zizmor first, and not
arbitrarily — it's already hand-rolling the exact thing phenomenon time exists to replace (its manual
`known_since` preservation; re-verify this against the collector's actual current code before
migrating it, per tap#896 finding 2 — `known_since` preserves first-sighting, which is not the same
claim as introduction time, and phenomenon time must not silently change zizmor's meaning). Then
extend to the other four: github-core (largest, and the one carrying the known-unknown pattern from
Phase 2 step 7), aws-core, samsite, and fedramp-20x-ksi last, since it already does its own
client-side diffing and may only need simplifying rather than adopting anything new.
*Depends on: all of Phase 2 (and Phase 1, transitively).*

# Handoff — picking this up cold

A session starting fresh on this work should, in order:

1. Read `doc-grid-batch-provenance-and-grift-patch-semantics.md` in full — it has the code-level
   evidence for Q129 and Q131 (exact file:line citations for `_apply_replace`, `_apply_patch`,
   `_deep_merge`, `update_flip_map`, `_flip_touched_for_verb`) that this document doesn't repeat, plus
   the Phase 1 acceptance criteria tap#896 added.
2. Check tap#886 for current phase status before assuming Phase 1 is still pending — this document's
   Phase 2 does not start until Phase 1 has actually shipped and been observed against real traffic,
   not merely designed or merged.
3. Check whether Q129 and Q131 have actually been ruled by George since this was written — verify
   against tap#886/tap#322/tap#323 directly rather than assume either way.
4. Confirm who currently owns this work before starting anything — demo-dev held Q129/Q131 before
   tap#886 existed and stood down on this thread; a full session-fleet reset was planned around the
   time this was written, so don't assume any particular session is still the owner.
5. Within Phase 2, steps 2, 3, 4, and 7 have no technical dependency on step 1 — the phase gate
   (Phase 1 shipped) is what actually blocks them, not each other. Do not start step 5 (the GRIFT
   default flip) without steps 1 and 4 both actually shipped, not just designed.
