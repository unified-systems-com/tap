---
title: Batch provenance (tap#322/#323/Q129) and GRIFT patch/replace/upsert semantics
date: 2026-09-29
status: pending — Q129 relayed to demo-dev, NOT treated by it as ruled pending George's own word
  (correctly, per demo-dev: a relay is not sufficient authorization for a code path that can
  tombstone live rows); the GRIFT patch-by-default flip additionally has an amended safety case
  below (2026-09-29, later the same day) after demo-dev found a real gap in the original audit
audience:
  - developer
  - llm
related:
  - tap#322
  - tap#323
  - tap#886
  - tap#896
  - tap_grid/specs/spec-grid-flip.md
  - tap_grid/specs/spec-grid-history.md
  - tap_grid/specs/spec-grid-import-grift.md
  - tap_grid/specs/spec-grid-entity.md
  - tap_grid/specs/spec-grid-node.md
  - docs/misc/doc-grid-reobservation-prior-art.md
  - docs/misc/doc-grid-provenance-placement-prior-art.md
  - docs/misc/doc-grid-reconcile-design.md
---

> Captured from a support-thread session with George, 2026-09-29, reconstructing and resolving
> Q129 (demo-dev's session, parked since r56/r57) and extending well past its original scope into
> GRIFT's write semantics. Written by the support session, ruled by George in real time as each
> piece landed. demo-dev has not yet seen this — see the "Handoff" section at the end.

# Update 2026-09-30 — phasing, and corrections from an independent review

**This work is now explicitly phased under epic tap#886, and Part 1 is Phase 1 — the immediate
target.** The initiating incident is unblocking zizmor's updates and the vulnerability-management
pathway, which is blocked specifically on tap#322's core symptom (multiple history bumps per
write), not on anything in Part 2 or the companion time/observation document. George: "this won't
be implemented as one big push" — Part 1 (this section) ships and is validated against real
collector traffic (zizmor's actual re-scan cadence in particular) before Part 2 (GRIFT patch
semantics, Q131) or the companion document's time model start. See tap#886 for the phase tracker.

**An independent review (Codex, filed as tap#896) checked this document and its companion against
the actual code and found several real gaps, all verified directly against the cited files rather
than taken on the review's word.** Confirmed and folded in below, at the point each applies:

- The diff-before-write mechanism must not collapse a genuine knowledge change (create with an
  omitted nullable field, then an explicit `null` write) into "no change" — see the added note under
  "Implementation notes for the diff itself" in Part 1.
- Provenance/evidence recording is currently best-effort, not atomic with the write it documents —
  see the new "Evidence durability, and two write paths a diff doesn't see" section after Part 1.
- A separate write path (`_sync_spine_for_replaced_nodes`) mutates spine fields outside the model
  save path entirely, invisible to any diff built on `.save()` — same new section.
- `BatchEvent` is correlation, not reconstruction, by its own docstring — dropping the typed-row
  `batch_id` needs an explicit answer for per-version batch attribution, not just a last-writer
  pointer — same new section.
- The known-unknown "convention" in Part 3 below is not something to formalize — it already exists,
  ratified and partly Implemented, as `req-grid-node-observation`/`x-tap-absence` in
  `spec-grid-node.md`. Corrected in place, below.
- The Q131 direction in Part 2 needs one addition: whatever it resolves to must not adopt RFC
  7396's null-deletes-a-key rule, because `spec-grid-node.md` already, explicitly, ratifies null-as-
  delete as the anti-pattern TAP rejects. Corrected in place, below, and in the companion document's
  Part 5.

No finding here says Phase 1 is wrong or should wait further — Q129's answer, the shared diff
mechanism, and the collector audit all stand. The findings sharpen Phase 1's acceptance criteria and
correct two places (Part 2, Part 3) where the plan was about to build something that either
duplicates ratified canon or conflicts with it.

# Update 2026-09-30, round 2 — github_core replaces zizmor as the proving ground; Phase 1 in three slices; a deeper canon gap

**Correction: zizmor is not Phase 1's proving case, and the round-1 update above overstated that it
was.** A second review pass (Codex) fetched zizmor-tap's actual collector source and found that
`observed_at` (`collector.py:449,625`) is set from `state.started_at` — this collection run's own
start time — and written into every finding's payload on every pass, whether or not anything else
about the finding changed. **George's ruling, direct: this is not a defect to suppress.** A field
that genuinely differs every pass should cause exactly one history bump per pass, FLIP updated for
that field — "working as expected," not a special case the diff needs to route around. What that
means concretely is that zizmor's own re-scan churn will **not** visibly quiet down under Phase 1
alone, because that field really does change every time, by zizmor's own design — Phase 1 fixes the
class of bug tap#322 actually describes (identical repeated observations wrongly recorded as
changes), it does not and should not make a genuinely-changing field look unchanged.

**George: focus-fire Phase 1's proving ground on github_core instead — "we know there's plenty of
non-moving entities in there."** github_core's config-layer nodes (workflows, rulesets, etc. — the
same set tap#322's own 1,612-node/144-pass measurement came from) have no equivalent per-pass
timestamp baked into their domain payload, which makes them the clean test of the actual mechanism:
two idle passes should produce zero new typed-row versions, not "fewer than before." Every reference
to zizmor as the Phase-1 validation target above and in the companion document is superseded by this.

**Also separately filed:** `unified-systems-com/zizmor-tap#57` — a backlogged idea (walk a flagged
file's git history to find the commit that actually introduced the condition, giving zizmor a real
event-time it doesn't have today). Not part of Phase 1, not scheduled.

**Phase 1, broken into delivery slices with their own done-tests (Codex, tap#896, adjusted for the
github_core proving ground):**

- **Slice A — correct write classification.** The diff-before-write mechanism itself, the
  three-row first-assertion table above, `BatchEventType.OBSERVE`, atomic evidence recording (see
  "Evidence durability" below), and all four consumer sites, landed together — they're one coupled
  change, not separable, per the original tombstoning-risk reasoning.
- **Slice B — provenance placement.** The two spine pointers (`last_changed_batch_id`,
  `last_observed_batch_id`/`_at`), the historical-batch-association check against
  django-simple-history before dropping `BaseModel.batch_id` (see "Evidence durability" below),
  serializer/envelope compatibility, and the typed-column drop **only once that check is verified** —
  the drop must not become an accidental prerequisite for landing the no-op fix itself. A and B may
  share one PR if the implementation is tightly coupled; the sequencing above is what matters, not
  the PR boundary.
- **Slice C — observation proof on github_core.** Two idle collection passes over github_core's
  config-layer nodes produce zero new typed-row versions, one `BatchEventType.OBSERVE` per entity per
  pass, `last_changed_batch_id` unchanged and `last_observed_batch_id` moved. This is the actual
  done-test for the initiating incident — the running-instance validation should be its own issue,
  closed separately from the build issues per the repo's own "issues close when tested code merges"
  rule, not folded into Slice A/B's build issues.

**A deeper, related gap, caught doing the self-audit George asked for after this round:** this whole
temporal/observation design — spanning this document and its companion — never checked
`tap_grid/specs/spec-grid-history.md`'s `req-grid-history-time` (`Proposed`) or
`tap_grid/specs/spec-grid-perspective-BACKLOG.md`'s `req-grid-perspective-record` (`Proposed`)
before proposing new mechanisms. Both already speak directly to this problem space, and zizmor's own
`observed_at` field name is not a coincidence — see the companion document's own "Update 2026-09-30,
round 2" section for the full reconciliation; it belongs there since it's about the time model, not
this document's batch-provenance half.

# Why this doc exists

demo-dev's tap#322 investigation (spec plan captured in `handoff` memory
`tap322-plan-rulings-stale.md`) was blocked on Q129: which representation should record that a
batch observed a node and found it unchanged. That question, worked through from first principles
in this session, turned out to have a clean answer — and answering it surfaced a real, previously
unfiled defect in FLIP itself, which in turn reopened why GRIFT only ever replaces and never
patches. This doc captures the whole chain, in the order it was actually reasoned through, so
nothing has to be re-derived.

# Part 1 — Q129, relayed (see Handoff at the end — not treated as ruled)

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
- JSON fields need no library: Python's native `==` on already-deserialized dicts/lists is
  recursive, order-independent, and structural rather than semantic — `{}` and `{"k": null}` are a
  real, countable change (ruled earlier this week, git-serious concurring independently), which is
  the behavior this domain wants. **But native `==` alone is not JSON-type-sensitive and the diff
  must not stop there** (tap#896, verified directly: `{"flag": True} == {"flag": 1}` and
  `[False] == [0]` both return `True` in Python, since `bool` is an `int` subclass). A collector or
  editor writing `1` where the stored value is `true` is a real, distinct value in JSON even though
  Python's native equality says otherwise. **The one instruction this collapses to:** use `==` for
  structural comparison, paired with an explicit `type(old) is type(new)` check (or equivalent) for
  any field where a bool/int/float mixup is possible — not a wholesale replacement of `==`, which
  stays correct for everything else, and not two separate, competing claims about whether `==` is
  trustworthy.
- **A value-unchanged diff is not the same claim as knowledge-unchanged — three cases, not two**
  (tap#896, finding 1, and George's ruling 2026-09-30 on the case Codex's table left open):

  | Write | Prior state | Classification |
  | --- | --- | --- |
  | Create with a nullable field omitted | No FLIP entry for that field | No assertion — unknown unknown, no history impact. |
  | First explicit `null` on that field | No FLIP entry yet | **New knowledge. Version bump.** Something material changed in what the grid knows, and that must be identified the same as any other change — not treated as a no-op just because the stored value stayed `null`. |
  | A later explicit `null` on the same field | FLIP entry already present for it | Repeat observation. Zero new version — `BatchEventType.OBSERVE`, same as any other unchanged re-confirmation. |

  The middle row is **already handled correctly today at the FLIP level** by the existing write-intent
  boundary (`req-grid-node-observation-4`/`-7`, Implemented) — an explicit null is always a touched
  field and always gets FLIP-stamped, whether or not the stored value moved. What the *new*
  diff-before-write classifier must do, to avoid regressing that and to satisfy George's ruling, is
  key its `OBSERVE`-vs-`UPDATE`/version-bump decision off **whether a FLIP entry existed for that
  field path before this write**, not off payload-presence alone and not off the stored value alone —
  payload-presence tells you a field was touched; prior FLIP-presence tells you whether touching it is
  the first time or a repeat, which is the actual distinction that determines version/history impact.
  This needs three explicit test cases in whatever test suite lands with the diff function (create-
  omitted; first explicit-null; second explicit-null), not further design — the classification rule
  above is settled.

A genuinely Postgres-native alternative exists (`UPDATE ... WHERE (cols) IS DISTINCT FROM (vals)`,
or a trigger with `WHEN (OLD.* IS DISTINCT FROM NEW.*)`) — real, and `jsonb` equality in Postgres is
already structural for free, matching the ruling above. Not recommended as the primary mechanism,
since the write path mutates an in-memory Django instance via `_apply_replace`/`_apply_patch` then
calls `.save()`, and moving the check into SQL would mean restructuring every call site to build
conditional `.update()` calls instead. Worth keeping in mind as a **backstop** — a trigger that
protects the invariant even from a write that bypasses the service layer entirely (a management
command, a future direct-DB integration) — not as a replacement for the application-level diff.

## Evidence durability, and two write paths a diff doesn't see (tap#896, findings 3 and 5)

**Provenance recording is best-effort today, and Phase 1 needs to make it atomic with the write it
documents.** `_execute_write_pipeline` (`_impl.py:963-967`, read directly) wraps `_record_provenance`
in `try/except Exception: logger.exception(...)` and continues — the write can succeed while its
provenance record silently doesn't exist. `record_batch_event` (`batch.py:186-217`, read directly)
returns `None` with no error if there's no batch context or the batch row can't be found. This is
fine for logging; it's not fine once `BatchEvent` is the ledger reconciliation trusts as evidence a
batch actually touched or confirmed an entity (`candidates.py:106`, `reconcile.py:325,436` already
consume it this way). Phase 1's acceptance criteria needs a case for this directly: inject a failure
in evidence recording and confirm the whole write rolls back, not just the typed-row half of it.

**A separate write path already bypasses the model-level save entirely, and it needs an explicit
answer once spine pointers exist.** `_sync_spine_for_replaced_nodes` (`grift/importer.py:3517-3548`,
read directly) propagates envelope `name`/`dimensions` onto `Entity` rows via a queryset `.update()`
— deliberately, so a pure spine sync doesn't bump `version` — because `replace_node` leaves spine
fields untouched by design. This pass predates everything in this document and isn't itself a defect,
but it's a second, currently invisible mutation path: it doesn't call `_record_provenance`, doesn't
touch `flip_map`, and won't touch `last_changed_batch_id`/`last_observed_batch_id` either, once those
exist, unless this pass is explicitly updated to set them. Decide, when Phase 1 lands the two spine
fields: does a spine-only rename count as "changed" for `last_changed_batch_id`'s purposes? Silence
here means a renamed entity's spine pointer goes stale relative to its actual last-touched batch.

**`BatchEvent` is correlation, not reconstruction, by its own docstring — dropping the typed-row
`batch_id` needs to account for that before it happens, not after.** `models.py:1495-1503`: *"
BatchEvent's job is correlation (what batch), not reconstruction (what changed)."* `last_changed_
batch_id` on the spine answers "who changed the *current* state" — it is a last-writer pointer, not a
per-version history. If anything downstream ever needs "which batch produced version N of this
field" (not just "which batch is responsible for the value right now"), that has to come from
django-simple-history's own per-version rows, which already carry a timestamp but were not audited
in this document for whether they retain batch attribution after `BaseModel.batch_id` is dropped.
Check that before the drop, not as a follow-up — the entire point of #323's "no second copy of a
fact" reasoning was that nothing else was thought to depend on the typed-row column; this is a real
candidate for "something else depends on it."

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

**Direction taken, safety case amended below — see "The JSON-merge gap" before treating this as settled:** `nodes`/`edges` will come to mean patch by default — accept the breaking-change risk
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

## The JSON-merge gap (found by demo-dev, 2026-09-29, after this doc's first version shipped)

**The audit above answered the wrong-but-adjacent question for JSON fields, and the safety case is
incomplete without this.** "No collector conditionally omits a top-level field" does not imply "no
collector's JSON documents lose inner keys" — those are different claims, and only the first was
checked.

The mechanism, verified directly (`services/_impl.py:75-83`): `_apply_patch` special-cases
`JSONField` and calls `_deep_merge(existing, value)` — `result = dict(base)` (every key from the
**persisted** document), then only overwrites keys present in `value`. Any key the persisted
document already has, that the new payload doesn't mention, survives untouched, forever.
`_apply_replace` sets the field wholesale — no merge, no survival. So the flip changes JSON-field
semantics for **every** collector, including every collector the audit above called clean, because
the failure isn't about which top-level fields are present — it's about what happens to keys
*inside* an always-present one.

Concretely: a collector emits a complete, correct `location` document every pass. Under today's
replace, the source removing a key makes it disappear from the grid, correctly. Under patch, the
new document merges *over* the stored one and the removed key survives forever — the grid reports a
field the source no longer has, indistinguishable to every consumer from a field that's still
genuinely observed. The exact false-presence class this whole investigation has been chasing,
reintroduced by the fix meant to prevent it.

**Measured, not assumed:** demo-dev loaded the model registry and intersected each entity type's
`patch` schema properties against its JSONFields — 58 registered entity types have at least one
JSONField in their patch schema. `github_core__code_scanning_alert` alone has five
(`rule_tags`, `location`, `classifications`, `configuration`, `tags`), and github-core is the
largest real collector in the org — the one the audit above called structurally clean by
construction on omission. Clean on omission does not protect it here.

**This compounds with the diff-before-write work in the worst possible direction.** After a merge
that silently preserves a stale key, the persisted value equals the resulting document, so
diff-before-write correctly sees no change and skips the write entirely — no version, no history
row, no `BatchEvent`. The wrong answer becomes both permanent and untraceable; two individually
correct pieces of work compose into a silent, unfalsifiable failure.

**The escape hatch that exists today doesn't fix this.** `req-grid-service-write-observation-4`
lets an explicit `null` clear a whole JSONField, but that clears the entire document, not one key —
so a collector's only way to drop a single key under patch would be clear-then-rewrite: two writes,
the first of which is a real, versioned change, with the field reading as unobserved in between.
Not a workable per-key delete.

**The fix is genuinely open, not a small detail — an earlier draft of this section proposed
"JSONFields never merge under patch, always set wholesale" as the likely direction, and that
proposal was wrong as stated, caught before it was acted on.** Two things make it wrong:

1. Deep-merge-on-patch for JSONFields isn't an implementation detail sitting quietly inside
   `_apply_patch` — it's a **ratified, Implemented, tested requirement**
   (`req-grid-service-write-patch-1`, "JSONField Deep Merge, Scalars Replace" —
   `spec-grid-service-write.md:346,360`; asserted by name in
   `test_services.py::test_json_field_deep_merge`). Removing it retires a specified contract, not a
   bugfix.
2. **There is a live, real dependant on the current behavior: the panel editor.**
   `tap_web/views.py::_form_to_patch_payload` (~line 605) builds its patch payload only from the
   edit form's own fields — `{k: v for k, v in cleaned.items() if k not in _STANDARD_PANEL_FIELDS}`
   — and relies on deep-merge to preserve every config key the form doesn't render. Setting
   JSONFields wholesale under patch, globally, would silently wipe every config key an edit form
   doesn't expose on the next ordinary save through the UI. That's real data loss, in a shipped
   feature, worse than the problem being solved.

**The actual shape of the fix:** a collector's GRIFT document is a *complete observation* — wholesale-set
is correct for it, a key the source stopped sending should disappear. An interactive editor's
payload is a *partial edit* — deep-merge is correct for it, keys the form never showed must
survive. Both callers are right, for different and legitimate reasons, which means the semantics
can't be keyed on field type alone inside `_apply_patch` — they have to be keyed on **caller
intent**: either a distinct internal verb for the GRIFT import path, or an explicit flag on the
write operation that `_apply_patch` reads. Which of those two is cleaner is not yet decided.

This is now filed as **Q131**, a spec question about revoking part of a ratified requirement for
one caller only — George's call, not either session's to resolve unilaterally. Neither this
document nor either session treats a fix as chosen.

**Correction (2026-09-30, tap#896 finding 4): whatever Q131 resolves to, it must not adopt RFC
7396's null-deletes-a-key rule as a per-key delete primitive.** The companion time/observation
document's Part 5 proposed exactly that — "adopting the missing half of the standard" — without
checking it against `spec-grid-node.md:396`, which already, explicitly, ratifies *"JSON Merge
Patch's 'null = delete' is the anti-pattern"* as part of the null-means-unobserved convention this
whole investigation depends on. TAP's null already carries a load-bearing meaning (explicit unobserved
assertion, FLIP-stamped) that RFC 7396's delete-on-null rule would silently override for any JSON
field. If a per-key JSON delete primitive is ever actually needed, it needs its own explicit,
non-null marker (a reserved sentinel key, a structured tombstone token — the mechanism is an open
design question, not this correction's job to pick), consistent with the existing convention rather
than borrowing the one part of RFC 7396 that convention already rejects. RFC 6901 (JSON Pointer) for
*addressing* a key is unaffected by this and still stands as the right notation if per-key
addressing is ever built.

None of this says the patch-by-default direction is wrong — the SQL/Mongo upsert reasoning above
still holds, and per-collector diffing would still multiply the same defect N ways. It says the
safety case needed this second, orthogonal check before the flip is actually committed, this doc's
first version didn't have it, and the first proposed fix didn't survive contact with a real
consumer either.

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

**Open, not yet ruled — Q131 (demo-dev, 2026-09-29):** how to key JSONField apply-semantics on
caller intent (GRIFT import vs. an interactive service-layer patch) without breaking
`req-grid-service-write-patch-1` for the panel editor. See "The JSON-merge gap" above. A distinct
internal verb for the GRIFT import path and an explicit flag on the write operation are both live
options; neither is chosen.

# Part 3 — adjacent, explicitly not in scope for tap#322/#323

Two things surfaced in this session that are real and worth tracking, but are NOT part of
unblocking tap#322/#323 and should not be folded into that scope:

**FLIP field-level tracking is its own defect, unfiled.** Checked every open/closed GitHub issue
mentioning FLIP — the one closed FLIP bug (#815) is about tombstones bypassing the FLIP hook
entirely, a different problem. This one has no issue number yet: `spec-grid-flip.md:57` defines a
FLIP value as "the batch that last **set** the current canonical value" — but for every replace
(and GRIFT, today, only ever replaces), `_flip_touched_for_verb` returns `None`, meaning every
service-writeable field gets stamped with the same batch id on every write regardless of whether
its value changed. Confirmed two independent ways: reading `update_flip_map`/`_flip_touched_for_verb`
directly (this session), and separately, at runtime — demo-dev's own premise probe on two identical
no-op `replace_node` calls showed `flip_map` growing from one entry to seven, observed rather than
inferred. For the dominant, collector-driven write pattern, this makes `flip_map` today
carry **zero more information than a single row-level last-batch stamp** — the diff-before-write
work above fixes this as a side effect (a no-op write touches nothing), but genuinely accurate
per-field tracking under patch specifically (not just "skip on no-op") is a separate, bigger
guarantee worth its own issue and its own test coverage, not something to assume falls out for
free.

**Correction (2026-09-30, tap#896 finding 9): this is not a convention to formalize — it already
exists, ratified and mostly Implemented, and github_core should be pointed at it rather than have it
re-derived.** `spec-grid-node.md`'s `req-grid-node-observation` (decided 2026-06-30, dynamic half
closed 2026-06-30) is exactly this: the `x-tap-absence` field-schema annotation plus the FLIP-presence
hinge (`null` + FLIP-present = known unknown, a source explicitly asserted absence; `null` +
FLIP-absent = unknown unknown, nobody has looked) — `req-grid-node-observation-3/4/6/7` are all
already `Implemented`. It's field-level, exactly as this section originally argued for, and it's
already distinct from shadow nodes (node-level) for the same reason given above. The only real gap
is **adoption**, not design: github_core's `_ruleset_bypass_fields`
(`{"state": "observed"|"unobservable", "reason": ..., ...}`, collector.py ~3140) is a bespoke,
undocumented shape that predates the ratified convention and does the same job with a different
vocabulary. The work here is migrating github_core (and any future permission-gated collector) onto
`x-tap-absence` instead of its own invented shape — a rollout/adoption task for Phase 2's collector
pass, not a new spec to write. This document's earlier framing of this as an unnamed convention
worth naming was wrong; the earlier research pass should have found `req-grid-node-observation`
before proposing to reinvent it.

# Handoff — updated after demo-dev's review, 2026-09-29 (same day)

demo-dev has read this document against the code directly and confirms Part 1 (the batch-provenance
half) matches its own independent read. Two things came out of that review that change this
document's status from what its first version claimed:

**Q129 is relayed, not ruled — correctly, per demo-dev, and this document should not be read
otherwise.** A relay through a support session is not sufficient authorization to start a four-PR
build that reaches a code path capable of tombstoning live rows. demo-dev has put Q129 to George
directly, alongside Q131 below, and will not begin building until it has George's own word. Anyone
reading this document as license to start P1–P4 is reading it wrong.

**Q131 is new, and it's the more consequential of the two open items.** demo-dev found that the
JSON-merge gap's first proposed fix ("JSONFields never merge under patch") would have retired a
ratified, tested requirement (`req-grid-service-write-patch-1`) and broken a live consumer (the
panel editor, `tap_web/views.py::_form_to_patch_payload`) on every ordinary save. That fix is
withdrawn; the problem it was trying to solve stands, and the actual fix needs to key JSONField
apply-semantics on caller intent, not field type alone. See "The JSON-merge gap" and Q131 above.

**Work already done that does not depend on either ruling:** the batch-provenance design (Part 1),
the shared diff-before-write mechanism and its four consumers, the collector audit (five collectors,
confirmed clean on the omission question specifically), and the two Part 3 items remain as
described and are not in question.

**Still true regardless of how Q129/Q131 land:** the collector build skill (`build-collector`)
should be updated once GRIFT's schema change and the diff-before-write mechanism actually ship —
documenting it earlier would describe a capability that doesn't exist yet, and now additionally
depends on however Q131 resolves for the patch/JSON-merge story specifically.

**Update 2026-09-30:** this work now lives under epic tap#886, explicitly phased — see the "Update
2026-09-30" section at the top of this document. Phase 1 is Part 1 plus the new "Evidence
durability" section above; it is the immediate target, driven by unblocking zizmor's vulnerability-
management pathway, and ships and is validated on its own before Phase 2 (Part 2 / Q131, and the
companion time/observation document) starts. An independent review filed as tap#896 checked both
documents against the code directly; its confirmed findings are folded in above at the point each
applies, and tap#896 itself stays open as the traceability record.
