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
  - docs/misc/doc-grid-batch-provenance-and-grift-patch-semantics.md
  - docs/misc/doc-grid-reconcile-design.md
  - docs/misc/doc-grid-reobservation-prior-art.md
  - docs/misc/doc-grid-provenance-placement-prior-art.md
  - tap_grid/specs/spec-grid-entity.md
  - tap_grid/specs/spec-grid-node.md
  - tap_grid/specs/spec-grid-flip.md
  - tap_grid/specs/spec-grid-service-write.md
---

> Captured from a support-thread session with George, 2026-09-29, continuing directly from
> `doc-grid-batch-provenance-and-grift-patch-semantics.md` — **read that document first.** It
> covers Q129 (batch provenance: FLIP, the spine, `BatchEvent`) and Q131 (JSON merge-vs-set
> semantics under patch) in full; both are cited here, neither is re-derived. This document covers
> what came after: a general time/observation model for the grid, and the complete execution order
> for everything decided across both documents. Written to be picked up cold, by a session with no
> memory of the conversation that produced it.

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

**The connection worth acting on now, not deferring:** `_apply_patch`'s `_deep_merge`
(`services/_impl.py:75-83`) is, structurally, an unnamed partial implementation of **JSON Merge
Patch (RFC 7396)** — recursive merge, update wins per key. It's missing the RFC's other rule:
**explicit `null` on a key should delete that key**, not set it to `None`. Verified directly:
today, `_deep_merge` sets a nulled key's value to `None` and leaves the key present. Adopting the
missing half of the standard would give a genuine, standards-based per-key delete to whichever
caller(s) end up wanting it under Q131's eventual resolution — additive to that resolution, not an
alternative to it, since it doesn't touch the top-level merge-vs-set question Q131 is actually
about.

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

**Not yet named or spec'd as a general convention** — invented once, for one case, not documented
anywhere for the next collector author to find. Formalizing it (probably in `spec-grid-node.md`,
alongside the existing null/empty-string rule) is its own step below, ahead of the collector-adoption
pass, since nothing can adopt a convention that doesn't have a name yet.

# Part 7 — Execution order

Ordered by actual dependency, not by which conversation surfaced each piece. Steps without a
listed dependency can proceed in parallel with anything else that also has none.

1. **Get George's own direct ruling on Q129** (and Q131, put to him at the same time — see the
   companion document's Handoff section). Not an engineering step — the actual bottleneck. demo-dev
   holds both and has correctly declined to start building from a relay.
   *Depends on: nothing. Blocks: step 2.*

2. **Build the tap#322 core fix**: diff-before-write in `_execute_write_pipeline` (pre-image before
   apply, post-image after — `_apply_replace` resets payload-absent fields to defaults, which is
   itself a real change the diff must catch), `BatchEventType.OBSERVE` for an empty-diff update,
   the four consumer sites widened in the *same* change (`candidates.py:106`, `reconcile.py:436`
   and `:325`, `cascade_corpus/timing.py:187` — not separable, this is the coupling that protects
   against tombstoning live rows), the two spine fields (`last_changed_batch_id`,
   `last_observed_batch_id`/`_at`), drop `BaseModel.batch_id` after the plugin-envelope grep (see
   issue #323's own trap list). Fully independent of everything else in this document — the
   original ask, unblocked once step 1 lands.
   *Depends on: step 1. Blocks: nothing else here.*

3. **Resolve Q131**: caller-intent-keyed JSON apply-semantics (GRIFT import wants wholesale-set,
   the panel editor wants deep-merge — key on caller intent, not field type), plus the RFC 7396
   null-deletes-a-key refinement from Part 5 above. Independent of step 2. Low urgency until step
   7, but the design is done — no reason to defer deciding it.
   *Depends on: step 1 (needs George's ruling, same as Q129). Blocks: step 7.*

4. **Phenomenon time range on the Entity spine** (Part 1/2 above): two columns, a
   `SPINE_FIELD_NAMES` update, the drift-guard test (`test_entity_spine.py`) will catch any
   mismatch by construction. Fully independent additive schema change.
   *Depends on: nothing. Blocks: nothing else here (step 10 benefits from it but doesn't strictly
   need it to start).*

5. **Decide the collector-time input shape (Part 4), then build the `BatchEvent` columns it
   feeds.** The shape decision has to precede the column design.
   *Depends on: nothing. Blocks: step 10's fuller value (a collector can't assert collection time
   until this exists).*

6. **Build the `put`/`replace` GRIFT section** (schema-only; the companion doc's collector audit
   confirmed zero collectors currently need it, so this ships with no collector code changes).
   *Depends on: nothing. Blocks: step 7.*

7. **Flip `nodes`/`edges` to mean patch by default.** Only after step 3 (so the flip doesn't
   reintroduce the JSON-merge danger Q131 exists to prevent) and step 6 (so an escape hatch already
   exists for anyone who turns out to need full-replace). Doing this before either exists means a
   window where the risky change has shipped before either of its safety nets do.
   *Depends on: steps 3, 6. Blocks: step 11.*

8. **Update the `build-collector` skill** to document the patch/put choice for future collector
   authors. Documenting a capability before it exists would mislead the next person who reads it.
   *Depends on: steps 6, 7.*

9. **Formalize the field-level known-unknown convention (Part 6)** — name it, define its canonical
   shape, write it into `spec-grid-node.md` alongside the existing null/empty-string rule.
   Independent of the time and patch work — a naming and spec exercise, not a schema change — but
   has to exist before the next step can use it.
   *Depends on: nothing. Blocks: step 10 (only for the known-unknown half of the adoption).*

10. **Pilot the new capabilities on zizmor-tap, then extend to the rest.** zizmor first, and not
    arbitrarily — it's already hand-rolling the exact thing phenomenon time (step 4) exists to
    replace (its manual `known_since` preservation), so migrating it both validates the new
    capability against a concrete, already-understood need and immediately retires known debt,
    rather than speculatively adding a feature nothing uses yet. Then extend to the other four:
    github-core (largest, and the one already carrying the known-unknown pattern worth
    generalizing per step 9), aws-core, samsite, and fedramp-20x-ksi last, since it already does
    its own client-side diffing and may only need simplifying rather than adopting anything new.
    *Depends on: steps 4, 5, 9 (and 7/8 if patch adoption is part of a given collector's pass).*

# Handoff — picking this up cold

A session starting fresh on this work should, in order:

1. Read `doc-grid-batch-provenance-and-grift-patch-semantics.md` in full — it has the code-level
   evidence for Q129 and Q131 (exact file:line citations for `_apply_replace`, `_apply_patch`,
   `_deep_merge`, `update_flip_map`, `_flip_touched_for_verb`) that this document doesn't repeat.
2. Check whether Q129 and Q131 have actually been ruled by George since this was written — this
   document's step 1 may already be done by the time it's picked up; verify against demo-dev's own
   register or ask directly rather than assume either way.
3. Confirm demo-dev's own current state before starting step 2 — it owns the tap#322 build and may
   have already started once ruled, or moved on to something else entirely (a full session-fleet
   reset was planned around the time this was written; check whether demo-dev is even the same
   session it was).
4. Steps 4, 5, 6, and 9 have no dependency on step 1 or 2 landing — safe to start any of them
   immediately if step 2's build isn't picked up yet, without waiting on anyone.
5. Do not start step 7 (the GRIFT default flip) without steps 3 and 6 both actually shipped, not
   just designed — that ordering is the entire point of sequencing it there.
