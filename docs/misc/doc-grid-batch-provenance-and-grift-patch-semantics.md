---
title: Batch provenance (tap#322/#323/Q129) and GRIFT patch/replace/upsert semantics
date: 2026-09-29
status: ruled
audience:
  - developer
  - llm
related:
  - tap#322
  - tap#323
  - tap_grid/specs/spec-grid-flip.md
  - tap_grid/specs/spec-grid-history.md
  - tap_grid/specs/spec-grid-import-grift.md
  - tap_grid/specs/spec-grid-entity.md
  - docs/misc/doc-grid-reobservation-prior-art.md
  - docs/misc/doc-grid-provenance-placement-prior-art.md
  - docs/misc/doc-grid-reconcile-design.md
---

> Captured from a support-thread session with George, 2026-09-29, reconstructing and resolving
> Q129 (demo-dev's session, parked since r56/r57) and extending well past its original scope into
> GRIFT's write semantics. Written by the support session, ruled by George in real time as each
> piece landed. demo-dev has not yet seen this — see the "Handoff" section at the end.

# Why this doc exists

demo-dev's tap#322 investigation (spec plan captured in `handoff` memory
`tap322-plan-rulings-stale.md`) was blocked on Q129: which representation should record that a
batch observed a node and found it unchanged. That question, worked through from first principles
in this session, turned out to have a clean answer — and answering it surfaced a real, previously
unfiled defect in FLIP itself, which in turn reopened why GRIFT only ever replaces and never
patches. This doc captures the whole chain, in the order it was actually reasoned through, so
nothing has to be re-derived.

# Part 1 — Q129, ruled

**The question, as demo-dev framed it (draft-r56):** how should "observed, unchanged" be recorded?
Three options — (a) a `BatchEventType.OBSERVE` value, drop the 09-02 ruling's spine stamp and
separate unchanged-set table; (b) build the 09-02 ruling as written (a spine stamp, a separate
per-node-per-pass table, a migration); (c) both.

**Ruling: closer to (c), refined once the actual cost of each piece was checked against what's
landed since 09-02.**

## What's kept from issue #323

Issue #323 (`Move row-level batch provenance to the Entity spine`, ruled by George 2026-09-02) is
**not superseded** — its two spine fields are still the right call:

- `Entity.last_changed_batch_id` — replaces today's typed-row `batch_id` (`tap_grid/models.py:712`,
  on `BaseModel`, not on `Entity`). Moves to the spine so "what did batch X change" is one indexed
  query across every type, instead of a per-type union over typed history tables.
- `Entity.last_observed_batch_id` / `last_observed_at` — the new re-observation stamp tap#322
  needs. Written via `.filter().update()`, never versions, never touches history.
- `BaseModel.batch_id` is **dropped** after backfill, per #323's own plan — "no second copy of a
  fact." One live trap from #323 worth re-stating: plugins read `batch_id` off typed rows today
  (github_core exposes it in its own `data` envelope) — grep every plugin and the envelope
  serializer before dropping, and project the value from the spine into the envelope so no
  consumer sees a behavior change.

## What's added: BatchEvent gets a real third state

`BatchEvent` (built 2026-02-10, commit `19f4aa48`, as FLIP-adjacent audit infrastructure — not
originally built for this purpose at all) already has exactly the shape the 09-02 ruling wanted for
a per-node-per-pass ledger: `entity_id`, a `batch` FK, an `event_type`, indexed both
`(batch, timestamp)` and `(entity_id, timestamp)`. It didn't need building — it needed a new
`BatchEventType.OBSERVE` value, recorded when an update-verb write's diff comes back empty, instead
of the current behavior (every no-op write is mislabeled `update`, a false statement written on
every idle pass).

**This makes the separate `Batch.observations` unchanged-set table from the 09-02 ruling
unnecessary — not because it was a bad idea, but because `BatchEvent` already IS that table.**
George rejected a narrow `(batch_id, entity_id, outcome)` table back in 09-02 specifically on row
count; `BatchEvent` already pays that row cost today (one row per operation, already), already has
better indexing than what was proposed, and the fix costs zero new rows — it only relabels
transactions that are already happening.

## Why both representations, not one or the other

They fail differently and neither substitutes for the other:

- **Spine fields** — free to read (already on the row), but non-versioned pointers. They answer
  "what's the current state" in one query; they cannot answer "show me the whole history."
- **BatchEvent** — the durable, joinable ledger. Answers "every batch that ever touched or
  confirmed this entity," reconstructs the full timeline. Costs a row per observation, forever,
  with **no retention policy specced anywhere today** (checked `spec-grid-history.md` directly —
  its retention discussion is scoped to typed history tables, not `BatchEvent`). At the design
  doc's own cited cadence (~1,612 nodes × 144 ten-minute passes/day), one collector alone is
  ~232,000 rows/day, ~85M/year. Real, unbounded, and explicitly **deferred** rather than solved —
  Postgres genuinely doesn't choke on append-only tables at that scale with the right approach
  (time-based partitioning is the natural shape, given every real query here is time-bounded), but
  nobody has decided a retention window yet.

`Batch` itself needs **no schema change** to answer "which entities did this batch touch" — that's
already answerable today via `BatchEvent.objects.filter(batch=X).values_list('entity_id', flat=True)`,
confirmed against the actual model (`batch.events` reverse relation, `tap_grid/batch.py`'s existing
`get_batch_events`/`get_entity_batches` functions, both already shipped and load-bearing for the
batch-viewer page).

## The mechanism that makes all of this correct: one diff, four consumers

None of the above works without a real diff-before-write, because **nothing in the write pipeline
does one today** — confirmed by direct code read, not inference:

- `_execute_write_pipeline` (`tap_grid/services/_impl.py:521`) applies via `_apply_replace`/
  `_apply_patch` then saves unconditionally.
- `_apply_replace` (`_impl.py:126-147`, read directly this session): for every field not in the
  payload, resets to the model field's declared default (or `""`/`None` if none declared). This is
  itself a real change that any diff must catch — comparing against the payload is wrong; the diff
  has to compare a **pre-image taken before apply** against the **instance after apply**.
- `BaseModel.save` stamps `batch_id` and bumps `Entity.version` unconditionally
  (`models.py:961-962`, `:1010`).
- `update_flip_map` (`flip.py:49-91`, read directly this session) stamps every target field with
  the batch id, no comparison to the persisted value, ever: `for field in target:
  instance.flip_map[field] = batch_id`.
- `_flip_touched_for_verb` (`services/_impl.py:94-102`, read directly): computes `target` purely
  from payload shape — `list(payload.keys())` for patch, `None` (meaning all fields) for replace.
  **Not diffing. Payload-presence, not value-comparison.**

**One comparison, computed once per write, feeds four independent decisions:**

1. Whether `flip_map` gets touched at all for a given field (skip on empty diff).
2. Whether `BatchEvent` records `update` or `observe`.
3. Whether `Entity.last_changed_batch_id` moves.
4. Whether `Entity.version` bumps (this is the ORIGINAL tap#322 symptom).

**FLIP's own storage function does not need to change.** `update_flip_map` has always been
correct in the narrow sense that it does the right thing with whatever field set it's handed — the
defect was entirely upstream, in `_flip_touched_for_verb` computing that set from payload shape
instead of a real comparison. Fix the diff, and FLIP becomes correct automatically, no separate
FLIP-specific change needed.

**Implementation notes for the diff itself** — not algorithmically hard, but three things to get
right on the first pass:
- Compare by field, excluding `batch_id`/`flip_map`/timestamps — an actively maintained exclusion
  list, the same discipline `Entity.SPINE_FIELD_NAMES` already enforces elsewhere
  (`tap_grid/tests/test_entity_spine.py` is the precedent for a drift-guarded list; this needs its
  own, not that one).
- Compare foreign keys by id (`old.entity_id != new.entity_id`), never by object — avoids a
  needless fetch and identity-vs-equality surprises.
- JSON fields need no library — Python's native `==` on already-deserialized dicts/lists is
  recursive and order-independent, which is already correct for this domain. Keep the comparison
  **strict/structural, never semantic** — `{}` and `{"k": null}` are a real, countable change
  (ruled earlier this week, git-serious concurring independently): a consumer reading a nested path
  sees the same absent value either way, but a consumer reading the parent object sees a different
  object, and FLIP keys are field paths. Any "these are basically equivalent" judgment belongs to
  identity/resolution, never to the write-path diff.

A genuinely Postgres-native alternative exists (`UPDATE ... WHERE (cols) IS DISTINCT FROM (vals)`,
or a trigger with `WHEN (OLD.* IS DISTINCT FROM NEW.*)`) — real, and `jsonb` equality in Postgres is
already structural for free, matching the ruling above. Not recommended as the primary mechanism,
since the write path mutates an in-memory Django instance via `_apply_replace`/`_apply_patch` then
calls `.save()`, and moving the check into SQL would mean restructuring every call site to build
conditional `.update()` calls instead. Worth keeping in mind as a **backstop** — a trigger that
protects the invariant even from a write that bypasses the service layer entirely (a management
command, a future direct-DB integration) — not as a replacement for the application-level diff.

# Part 2 — GRIFT's write semantics: why replace, and why that's changing

## Why GRIFT only ever replaces today, verified not assumed

`spec-grid-import-grift.md` preflight step 4 validates every node/edge payload against
`REPLACE_REQUIRED` and explicitly states "patch-only fields excluded" — a GRIFT document **cannot
structurally carry** a partial update today; this was never a runtime choice made per-call, it's a
schema-level constraint. The reasoning (`spec-grid-import-grift.md:209`, plus direct collector code
inspection): GRIFT itself is verb-neutral, but every collector re-emits a full, complete picture of
what it observes each pass (that's the literal cause of tap#322) — so replace was the honest match
for what collectors actually know, and pushing per-collector diffing upstream (patch, requiring
every collector author to compute their own delta) would have multiplied the exact "N independent
implementations must agree" failure already found three separate times this investigation
(`candidates.py`, `reconcile.py` ×2, the cascade oracle) — once per collector instead of once in a
shared pipeline.

## The decision: flip the default, not add a parallel option

**Ruled:** `nodes`/`edges` will come to mean patch by default — accept the breaking-change risk
rather than keep replace as the default and add patch alongside it. The stated reasoning: TAP's
actual dominant write pattern (an AWS collector re-confirming an instance is still there, zizmor
re-confirming a finding persists) is a database receiving repeated confirmations from many
independent, imperfect-visibility sources — closer to the SQL/Mongo upsert convention
(`INSERT ... ON CONFLICT DO UPDATE SET col=val` — patch-shaped by default, you name what changes)
than to the declarative-infra convention (Terraform, `kubectl apply` — full-state-replace by
default) GRIFT was originally modeled on. TAP is the former, not the latter, and the write
semantics should match the workload that's actually running, not the one the earliest collectors
happened to produce.

**The specific risk this creates, and why it was accepted anyway:** any collector that
conditionally omits a field it's capable of knowing would, under patch-by-default, silently stop
clearing that field when the source value genuinely goes away — the omission would read as "no
opinion" instead of "confirmed gone." This is the exact failure shape already found once this
session (a mutable-status field left alone under patch, reported as `resolved` forever after a
regression, in the CHANGES_FINDING_STATE design git-serious was building). Accepting the flip
requires believing the real collectors don't have that pattern — see the audit below.

## The collector audit — five collectors, zero gaps found

Every non-archived plugin repo in the org was checked for a real `collectors/` directory (`gh api
repos/<org>/<repo>/git/trees/main?recursive=true`, filtered on `collectors?/.*\.py$`). Five repos
have real collector code; nineteen have none. Each of the five was independently audited (parallel
subagents, each reading the actual collector source on GitHub) for conditional field omission —
any `if x: payload[k] = v` pattern, any try/except that skips a key on a failed sub-call, anything
short of "every declared field is always a key in the payload, with an explicit default standing in
for an unresolved value."

| Repo | Verdict | Notable finding |
| --- | --- | --- |
| `github-core-tap` | Clean | Builds every payload as a single dict *literal* (not incremental assignment), which makes omission structurally hard by construction. `_ruleset_bypass_fields` (~collector.py:3140) already models "GitHub didn't tell me" as its own explicit `{"state": "unobservable", ...}` value, distinct from an observed-empty answer — real, shipped prior art for exactly the field-level "known unknown" problem (see Part 3). |
| `aws-core-tap` | Clean | Fields come from a comprehension over every manifest-declared field (`projection.py:107-110`); an unresolved path yields `None` explicitly, by documented design ("graceful-missing semantics"), never a dropped key. One deliberate, tested, display-only exception (a name fallback for unnamed resources) — not a data omission. `customfns.py` (1000+ lines) wasn't read line-by-line, though it still funnels through the same unfiltered envelope-build step regardless of extraction method. |
| `samsite-tap` | Clean | Uniform `record.get(key) or default` across every node type; the only conditionality found is normal edge-existence logic (an edge is only added when a relationship resolves), not field omission. Some node fields are built by sigstore_core/identity_core's own helpers, passed through unmodified — not independently audited here. |
| `zizmor-tap` | Clean | Unconditional dict literals for both node types (`run`, `finding`); a re-confirmed finding re-asserts every field from scratch, no partial-update path exists at all. Already hand-rolls its own "first-seen timestamp" preservation, independent of FLIP — a symptom of FLIP's current defect that a correct FLIP would let it stop doing by hand. |
| `fedramp-20x-ksi-tap` | Clean | Smallest and simplest: unconditional field construction with `.get(key, default)`. Bigger finding: this collector doesn't rely on GRIFT's replace/patch question at all — it does its own client-side diff against prior grid state and only ever submits nodes for what actually changed; a no-op pass submits no GRIFT batch whatsoever. Already sidesteps tap#322 entirely, independently. |

**No conditional-omission sites found anywhere, across all five.** Because every real collector
already emits complete payloads today, flipping the default changes **no existing collector's
actual behavior** — a complete payload is indistinguishable from patch or replace's point of view,
since there's nothing left over to either reset or leave alone. The risk the flip accepts is
theoretical against today's fleet, real against a future collector that doesn't hold to the same
discipline.

## The GRIFT shape this implies

Current batch structure, verified against `tap_grid/schemas/grift-document.schema.json`:
- `nodes`, `edges` — bare upsert arrays, no policy knobs, no internal split. (Will come to mean
  patch.)
- `deletes`, `purges` — full **sections**, each with `on_missing` (`error`/`warn`/`ignore`) and
  `deletes` additionally `on_tombstoned` (same enum), each internally split into its own `nodes`/
  `edges` removal-target arrays.
- `batch_entity`, `contents` — metadata, not operations.

**Plan:** add a `put` (or `replace`) section, matching the deletes/purges shape — its own object,
its own `on_missing` policy enum, its own internal `nodes`/`edges` split — for the explicit,
deliberate "I have the complete picture and want to take over this node's state" case, which today
is the default and after this work becomes the opt-in. No collector code changes required to ship
this, since nothing currently uses it — every existing collector already emits complete state, so
their traffic behaves identically whether routed through the new patch-default `nodes`/`edges` or
the new explicit `put` section.

**Open, not yet ruled:** what `on_missing` defaults to for `put`/for patch targeting a nonexistent
entity. Leaning strict (`error`) by default, matching `deletes`/`purges`' own posture and matching
"patch is for re-observing something already known" (`CREATE_REQUIRED` exists to guarantee a new
row can be found again by its natural key — a patch payload has no such guarantee) — but this is a
real call for whoever builds it, not something the precedent forces.

# Part 3 — adjacent, explicitly not in scope for tap#322/#323

Two things surfaced in this session that are real and worth tracking, but are NOT part of
unblocking tap#322/#323 and should not be folded into that scope:

**FLIP field-level tracking is its own defect, unfiled.** Checked every open/closed GitHub issue
mentioning FLIP — the one closed FLIP bug (#815) is about tombstones bypassing the FLIP hook
entirely, a different problem. This one has no issue number yet: `spec-grid-flip.md:57` defines a
FLIP value as "the batch that last **set** the current canonical value" — but for every replace
(and GRIFT, today, only ever replaces), `_flip_touched_for_verb` returns `None`, meaning every
service-writeable field gets stamped with the same batch id on every write regardless of whether
its value changed. For the dominant, collector-driven write pattern, this makes `flip_map` today
carry **zero more information than a single row-level last-batch stamp** — the diff-before-write
work above fixes this as a side effect (a no-op write touches nothing), but genuinely accurate
per-field tracking under patch specifically (not just "skip on no-op") is a separate, bigger
guarantee worth its own issue and its own test coverage, not something to assume falls out for
free.

**A reusable "field-level known-unknown" convention, worth extracting from `_ruleset_bypass_fields`.**
github_core's `{"state": "observed"|"unobservable", "reason": ..., ...}` shape (collector.py
~3140) is bespoke — invented for one specific case (ruleset bypass actors, permission-gated), not
documented as a general convention. It's a genuinely different granularity from shadow nodes
(RULED 2026-09-15, DEFERRED in `doc-grid-reconcile-design.md`) — shadows are node-level ("I don't
have the object at all, just evidence it exists"); this is field-level ("the node is real and
known, but this one field came back as an explicit refusal, not silence and not a real value").
Distinct from patch's omission semantics too — omission means "didn't check this pass," this shape
means "checked, and got a structured 'not allowed to tell you.'" Worth formalizing as a named,
shared convention (probably alongside where the existing null/empty-string convention lives in
`spec-grid-node.md`) the next time either shadow nodes or a permission-gated collector comes up for
real — not urgent, but real, and currently reinvented rather than reused.

# Handoff

demo-dev has been holding Q129 open (draft-r56 through the end of its register) and does not yet
know about anything in Part 2 or Part 3 — this session's investigation started from its own
tap#322 analysis but grew well past what it asked. It should be told: Q129 is ruled (this doc's
Part 1), the scope of the surrounding work is larger than tap#322/#323 alone (Part 2, a real GRIFT
schema change), and two adjacent items are tracked but explicitly deferred (Part 3). The collector
build skill (`build-collector`) should be updated to document the `patches`/`put` choice for future
collector authors — but only once GRIFT's schema change and the diff-before-write mechanism have
actually shipped; documenting it earlier would describe a capability that doesn't exist yet.
