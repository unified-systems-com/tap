# tap-cares Progressive Collection Specification

## Philosophy

A collector's job does not end at "fetch it and land it." Every source object a collector has
already placed on the grid falls into one of a small number of mutability shapes, and most of
those shapes are known the moment the collector is written: a completed workflow run will never
change again; an uploaded artifact's bytes are fixed the instant it exists; a merged pull request
is nearly frozen; an open one is not. A collector that re-fetches, re-decomposes and re-writes
every one of these on every single pass is not being careful — it is failing to use information
it already has.

This spec names that information a **declared property of the type**, not a runtime guess, and
gives collectors three concrete, composable mechanisms for acting on it: ask the source to filter
by what changed (a watermark), stop walking an ordered listing once known territory is reached
(a cutoff), and skip a per-item enrichment call once the parent record shows nothing moved
(a secondary-call skip). All three converge on the same write-side outcome — an unchanged,
already-known object gets its presence **confirmed**, not its record **rewritten**.

**Why now, not later.** This was investigated 2026-09-29 as a spike against `github_core`
(git-serious-support session), which turned out to already contain the proof of both halves of
this problem in one plugin: `github_actions_run` has real incremental logic — a persisted
watermark, a `created`-filtered re-fetch, and a bounded re-poll of only the non-terminal subset
(`github-core-tap`, `collectors/github_collector/collector.py:6864-6952`) — while every other
entity type in the same collector (artifacts, caches, code-scanning analyses, alerts, releases,
pull requests, workflow file bodies) re-walks its full listing from scratch on every run, with no
watermark, no cutoff, and no conditional check anywhere. *(observed, github-core-tap#209's
sibling investigation, 2026-09-29 — see that issue for the corpus counts this is sized against:
roughly 130 artifacts, 110 analyses and 240 caches per repository on average across 46 repositories
in one dev stack, none of it currently incrementalized.)* The same plugin's own reliability spec
independently named half of this gap and correctly declined to solve it there:
`req-github-core-reliability-conditional` (`spec-github-core-reliability.md`) backlogged ETag/
conditional requests as "an efficiency edge, not a reliability one." That call was right — this is
the spec that edge belongs to, and it belongs at the `tap_cares` layer because every future
collector will meet this same shape, not only GitHub's.

**Why this is not a second write-path.** The presence-touch mechanism this spec relies on —
recording "still there, unchanged" without producing a new history version or rewriting FLIP — is
not invented here. It is the Entity-spine last-observed stamp and GRIFT patch-by-default primitive
that `tap#886` ("Epic: time and observation standardization") is already designing, which itself
grew out of `tap#322` ("re-observation is not change") and `tap#323` (the row-level batch pointer
moving to the Entity spine). This spec defines *when a collector is allowed to reach for that
primitive* and *what it must declare to do so safely*; it explicitly does not define the primitive
itself, and every requirement below that touches the write path is `Blocked` on `tap#886` rather
than re-deriving a competing mechanism. Until `tap#886` lands, a collector that adopts everything
else in this spec (watermark, cutoff, secondary-call skip) still pays a full write on a confirmed-
unchanged object — real progress, with the last mile explicitly deferred rather than faked.

**Why this matters beyond one plugin.** George, 2026-09-29: FedRAMP PAIN-ranking work is going to
need collectors that can run "at-speed" — frequent, low-latency passes over large estates. A
collector built the way `github_core` was built for everything except runs — full re-walk, full
re-write, every pass — does not get faster by adding hardware; its cost is proportional to the
size of the *entire* corpus it has ever seen, not to what actually changed. Building the muscle
memory for progressive collection now, as a declared, reviewed pattern every new collector is
built against (`build-collector` skill, Step 1), is cheaper than retrofitting every collector once
the estate is large enough that "at-speed" stops being optional.

**Prior art, briefly** (a full sweep was not run for this spike; flag if one is wanted before
implementation): HTTP conditional requests (`ETag`/`If-None-Match`, RFC 7232) are exactly the
secondary-call-skip mechanism in its most standardized form, and `githubkit`'s cache layer
(`hishel`, already named in `spec-github-core-reliability.md`'s client comparison) may give a form
of this for free once that migration lands. Kubernetes' list-watch/informer pattern is the ordered-
cutoff mechanism in production form: a `resourceVersion`-ordered stream that a client can resume
from a bookmark instead of re-listing everything. AWS Config's resource-discovery delta and rsync's
mtime/size skip-unchanged heuristic are the same idea again, twice more. Terraform's `refresh` is
the cautionary counter-example: it re-reads every resource on every plan, and large estates
routinely work around this with `-target` and partial refreshes bolted on after the fact rather
than designed in — the outcome this spec is written to avoid inheriting.

**Provenance markers.** Claims marked *observed* were measured against the `git-serious` dev
stack on 2026-09-29 (see `github-core-tap#209` and its sibling spike discussion); everything else
in this spec is *designed*.

## Goals

|    |              |                                                                                          |
| :---: | ---       | ---                                                                                      |
| 1. | Declared      | A type's mutability shape is a visible declaration a collector author writes, not a runtime inference or an unwritten assumption |
| 2. | Composable    | Watermark, cutoff and secondary-call-skip are independent mechanisms a collector adopts per type, not an all-or-nothing switch |
| 3. | Safe By Default | A type with no declaration gets full re-collection, never a silent skip; unsafe cutoff conditions (a mutable sort key) are named and refused, not assumed away |
| 4. | Measured, Not Asserted | A collector claiming a progressive win proves it with a per-run call count, before and after, not a guess |
| 5. | One Write Primitive | Presence confirmation reuses the Entity-spine mechanism `tap#886` is building rather than inventing a second "this didn't change" write path |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-cares-progressive-classification | [Mutability Classification](#mutability-classification) | Proposed | Every emitted node type declares one of five mutability classes |
| req-tap-cares-progressive-watermark | [Server-Side Watermark Filtering](#server-side-watermark-filtering) | Proposed | Generalizes `github_actions_run`'s existing pattern: persist a per-surface watermark, ask the source to filter by it |
| req-tap-cares-progressive-cutoff | [Ordered-Listing Early Cutoff](#ordered-listing-early-cutoff) | Proposed | Stop paginating a monotonically-ordered listing once known, frozen territory is reached — gated on a declared sort-key monotonicity, never assumed |
| req-tap-cares-progressive-secondary-skip | [Secondary-Call Skip](#secondary-call-skip) | Proposed | Skip a per-item enrichment fetch once the parent record and, where declared, a content fingerprint show no change |
| req-tap-cares-progressive-touch | [Presence Touch](#presence-touch) | Blocked | Confirming an unchanged object bumps a last-observed marker instead of a full write; the mechanism is `tap#886`'s, not this spec's |
| req-tap-cares-progressive-instrumentation | [Per-Run Call Instrumentation](#per-run-call-instrumentation) | Proposed | A collector records how many source-system calls each run made, per surface, so a progressive win is a number, not an impression |
| req-tap-cares-progressive-proof | [Two-Pass Proof](#two-pass-proof) | Proposed | An unchanged second pass over the same source data must make measurably fewer calls than the first, checked in the collector's own test suite |
| req-tap-cares-progressive-audit | [Full-Corpus Reconciliation Pass](#full-corpus-reconciliation-pass) | Backlog | A periodic, deliberately non-progressive full walk, so an incremental path's own bugs — a wrong watermark, a broken cutoff assumption — cannot silently drift the grid away from the source forever |

## Explanation

This spec sits between `tap_cares/specs/spec-tap-cares-collector.md` (what a collector *is*) and
each plugin's own collector implementation (what a collector *fetches*). It does not change the
`CollectorBase` contract, the GRIFT submission path, or the failure-mode protocol — a progressive
collector still runs once per invocation, still submits one GRIFT batch, still records `record_info`/
`record_warn`/`record_error` the same way. What changes is what happens *before* a fetch (does this
type's declaration permit skipping it) and *after* a fetch confirms no change (does the write
become a full replace or a presence touch).

None of these mechanisms may be applied to a type with no declaration, and a declaration itself
must be conservative: when in doubt, a type is `MUTABLE`, which is exactly today's behavior. This
spec adds capability; it removes no safety the collector had before adopting it.

### Mutability Classification
----
RID: `req-tap-cares-progressive-classification`

Status: `Proposed`

Every node type a collector emits declares one of five mutability classes, the same way it
declares a `NATURAL_KEY` (`build-collector` skill, Step 4). The declaration is the only thing the
mechanisms below are allowed to read; none of them may infer a class from behavior observed at
runtime.

| Class | Meaning | github_core examples *(observed, 2026-09-29)* |
| --- | --- | --- |
| `FROZEN` | Every field is permanent from the moment the object exists on the source; the object itself is never deleted or revised | `rule_suite`, `code_scanning_analysis`, `commit_observation` |
| `FROZEN_AT_TERMINAL` | Mutable while in flight; once a declared terminal state is reached, every field is permanent | `github_actions_run` (`status="completed"`), `github_actions_job` / `workflow_job` |
| `FROZEN_CONTENT_REVOCABLE` | Content is permanent once created, but the object can be deleted or expire on the source independent of anything a collector did | `actions_artifact`, `actions_cache` |
| `VERSIONED_CONTENT` | Content can change via an explicit edit, but the source hands back a content fingerprint (a hash, an ETag, a blob sha) cheaply, separate from a full fetch of the content | `github_workflow`'s YAML body (GitHub's Contents API returns a blob `sha`) |
| `MUTABLE` | Fields can change at any time with no terminal marker the collector can rely on; a freshness field such as `updated_at`, when the source provides one, still bounds re-checking (`req-tap-cares-progressive-cutoff`) without making the object skippable | `pull_request` (open), `code_scanning_alert`, `github_ruleset`, `github_environment`, `github_runner`, `actions_secret` |

**"Frozen" describes fields, not the row's continued existence — and that boundary is
deliberate, not an oversight.** `FROZEN` and `FROZEN_AT_TERMINAL` promise that an object's *data*
will never change again; neither promises the object can never be *removed* from the source (a
completed workflow run purged after its retention window, a rule suite pruned, a ruleset deleted).
`FROZEN_CONTENT_REVOCABLE` is named for exactly this distinction and carries the one mechanism
this spec defines for it, `EXISTENCE_RECHECK_INTERVAL` — but that mechanism is not extended to
every other class here, and this spec does not attempt to. Detecting a deleted object in general is
`build-collector`'s own already-named, larger gap ("Additive-only is a defect, not a phase" — both
committed cloud collectors upsert and never tombstone today). Adopting any mechanism in this spec
does not change that: a `FROZEN_AT_TERMINAL` run skipped by watermark or cutoff is exactly as
undetectable-if-deleted after adopting these mechanisms as it was before, because nothing in
`github_core` detects that deletion today either way. **What this spec requires is that no
mechanism here be read as having solved that problem for a class that does not declare
`EXISTENCE_RECHECK_INTERVAL`** — a real efficiency win must not be quietly mistaken for a
deletion-detection story it never provided.

#### Status Details
Proposed. Not implemented in any collector today. `github_core`'s own model files carry the
information this classification needs in prose (docstrings noting "an occurrence, not a change,"
"immutable once created," "kept for continuity") but no machine-readable declaration.

#### Implementation
A `MUTABILITY_CLASS: ClassVar[str]` on the model (or, for a manifest-driven collector such as
`aws_core`, a `mutability_class` key per manifest entry — see the manifest-as-engine union in
`build-collector`), one of the five values above, plus, where the class requires it:

- `FROZEN_AT_TERMINAL` — `TERMINAL_STATUS_FIELD` and `TERMINAL_STATUS_VALUES`, naming the field and
  values that mean "will never change again."
- `FROZEN_CONTENT_REVOCABLE` — `EXISTENCE_RECHECK_INTERVAL`, so a collector knows how often to
  reconfirm an item it is not re-fetching the content of, and, if the type is also a
  `req-tap-cares-progressive-cutoff` candidate, both `SORT_KEY_MONOTONIC: bool` (`False` for
  anything ordered by an access-time-like field) and `APPEND_ONLY_VISIBILITY: bool` (`False` unless
  the collector author can positively justify that the source never surfaces a new item behind an
  already-confirmed frontier — ordering alone does not establish this; see
  `req-tap-cares-progressive-cutoff`'s development note).
- `VERSIONED_CONTENT` — `FINGERPRINT_FIELD`, the model field that stores the last-seen content
  fingerprint, and a declared function for cheaply fetching the current fingerprint without the
  full content.

A type with no declaration defaults to `MUTABLE` — today's behavior, unconditionally safe.

#### Development
This is deliberately a five-way, not a boolean, classification. A collector author's first
instinct is "immutable or not," and `actions_cache` is the concrete case that instinct gets wrong:
its *content* is immutable but its *listing order* is not (most-recently-*accessed*, not
most-recently-*created*), so a cutoff mechanism that is safe for `actions_artifact` is unsafe for
`actions_cache` under the same "immutable" label. The classification exists to make that
distinction a declaration a reviewer can check, not a fact a collector author has to remember
correctly every time.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-progressive-classification-1 | Declared, Not Inferred | Proposed | A guard test fails any model whose `MUTABILITY_CLASS` is read anywhere except from the class declaration itself. | Mirrors `tap_grid/tests/test_natural_key.py`'s shape |
| req-tap-cares-progressive-classification-2 | Undeclared Defaults Safe | Proposed | A model with no `MUTABILITY_CLASS` behaves identically to `MUTABLE` — full re-collection, no skip of any kind. | |
| req-tap-cares-progressive-classification-3 | Terminal Fields Required Together | Proposed | A model declaring `FROZEN_AT_TERMINAL` without both `TERMINAL_STATUS_FIELD` and `TERMINAL_STATUS_VALUES` fails the guard at load. | |
| req-tap-cares-progressive-classification-4 | Monotonicity And Visibility Are Explicit For Cutoff Candidates | Proposed | A model declaring itself cutoff-eligible without explicit `SORT_KEY_MONOTONIC` and `APPEND_ONLY_VISIBILITY` booleans, both, fails the guard — silence is never read as `True` for either. | Split into two independent flags after review found them conflated |
| req-tap-cares-progressive-classification-5 | No Class Implies Deletion Detection Except The One That Declares It | Proposed | Documentation and code review for a collector adopting this spec treats `FROZEN`/`FROZEN_AT_TERMINAL`/`VERSIONED_CONTENT`/`MUTABLE` as carrying no claim about the object's continued existence on the source; only `EXISTENCE_RECHECK_INTERVAL`'s presence is that claim, and its absence is never read as "not needed here." | Regression for the existence-revocation scope finding — this spec does not solve `build-collector`'s pre-existing additive-only gap |

#### Future
If a sixth shape turns up in a source this taxonomy does not fit (a append-only-but-redactable
object, say), extend the table rather than force it into the nearest existing class — the whole
point is that the mechanisms below trust the label completely.

### Server-Side Watermark Filtering
----
RID: `req-tap-cares-progressive-watermark`

Status: `Proposed`

When the source API accepts a filter that bounds a listing to "changed since X" — a date
parameter, a cursor, a `since`/`updated`/`created` query argument — a collector for a `FROZEN`,
`FROZEN_AT_TERMINAL` or `MUTABLE`-with-a-freshness-field type persists the highest value it has
already collected and passes it back on the next run, rather than re-walking the full listing.

#### Status Details
Proposed. `github_actions_run` already implements exactly this, unlabeled as a general pattern
(`collector.py:6864-6903` *observed*): `GithubActionsRun.objects.filter(full_name=full_name)
.aggregate(Max("run_started_at"))` on first read, then `params={"created": f">{iso}", ...}` on
every subsequent one. This requirement generalizes that concrete implementation into a declared,
reusable shape every collector reaches for the same way, rather than a bespoke pattern that exists
once and is not recognized as reusable.

#### Implementation
1. The watermark field per surface is declared alongside the mutability class (which field, on
   which model, ordered which direction).
2. The watermark value is read from the grid before the fetch (an aggregate query against already-
   collected rows, as `github_actions_run` does today), not from a side-channel cursor store —
   the grid is already the source of truth for what has been seen.
3. **The boundary is inclusive, with dedup, never a bare strict `>` on the raw field.** A scalar
   timestamp is not a unique cursor: two records can share the same value at the field's
   resolution, and a strict `created > watermark` filter can drop one of them forever if it is
   persisted after the watermark has already advanced past its timestamp. The filter is
   `field >= watermark`, and the natural key's existing dedup (`find_existing`) is what makes
   re-returning an already-stored row safe rather than duplicating it — the filter's job is to
   shrink the fetch, not to be the only thing standing between the collector and a duplicate.
   Where the source offers a true monotonic cursor (an opaque token, a strictly-increasing id) in
   place of a bare timestamp, prefer it; the inclusive-with-dedup rule exists for the common case
   where only a timestamp is available.
4. The filtered fetch's result is the *complement* set: only what changed. It is unioned with, not
   substituted for, whatever `req-tap-cares-progressive-cutoff` or the existing full-listing path
   would otherwise produce for the same surface.
5. Where the type is `FROZEN_AT_TERMINAL`, a second, independent query re-polls only rows still
   short of their terminal state (`github_actions_run`'s non-terminal-refresh, `collector.py:6905-
   6952` *observed*) — the watermark filter alone would never re-check an in-flight object whose
   `created` timestamp has fallen behind the filter's boundary.
6. **A bounded first population is a declared scope decision, not a silent cap.** The watermark's
   whole mechanism only ever asks the source for things at or after the highest value it has
   already collected — nothing pulls it backward. So whatever the *first* population run leaves
   uncollected is uncollected forever, by construction, unless something outside the watermark
   mechanism reaches back for it. A first population that is deliberately narrower than "collect
   everything the source has" (`github_actions_run`'s literal first-population branch, `collector.
   py:6878-6888`, is exactly this: one bounded page of the newest runs, not the repository's whole
   run history) must declare that narrowing explicitly — a stated `COLLECTION_SCOPE_LOWER_BOUND`
   per surface, with a reason — rather than leaving "how much history did we actually agree to
   collect" implicit in whatever a first page happened to return. Absent an explicit bound, first
   population fetches the full available history, however many pages that takes.

#### Development
The two-part shape (watermark filter + separate non-terminal re-poll) looks like two mechanisms
but is one requirement: a watermark filter alone is provably wrong for `FROZEN_AT_TERMINAL` types,
because an object that started before the watermark and is still in flight will never be caught by
a "created after" filter. Any collector adopting this for a `FROZEN_AT_TERMINAL` type must adopt
both halves or neither.

The inclusive-boundary rule (point 3) was tightened after review of this spec's first draft, which
specified a strict `>` filter matching `github_actions_run`'s literal code today. That code is not
wrong for run timestamps at GitHub's actual resolution, but the *general* requirement must not
inherit a narrower assumption than it states — a future adopter with coarser timestamps or
batched writes must not be quietly exposed to the same gap this rule closes.

Point 6 was added after a second review round found that a "bounded first-population fetch"
(named, without qualification, in this draft's first acceptance criterion) creates a permanent,
un-backfillable hole below whatever the bound happened to be — the watermark mechanism has no
way to ever revisit it, by design. Making the bound an explicit, reasoned declaration does not
close that hole; it turns a silent one into a stated, reviewable scope decision, with
`req-tap-cares-progressive-audit` (Backlog) as the only mechanism that could ever backfill it —
named, not assumed away.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-progressive-watermark-1 | Watermark Read From The Grid | Proposed | The watermark value used to filter a fetch is computed from already-collected rows, never a separately persisted cursor. | |
| req-tap-cares-progressive-watermark-2 | Non-Terminal Rows Always Re-Checked | Proposed | For a `FROZEN_AT_TERMINAL` type, every on-grid row not yet in a terminal state is re-fetched every run regardless of the watermark. | Regression for the gap named above |
| req-tap-cares-progressive-watermark-5 | First Population's Bound Is Declared, Not Silent | Proposed | A first-population fetch narrower than the source's full available history requires an explicit `COLLECTION_SCOPE_LOWER_BOUND` declaration with a stated reason; with none declared, first population walks the full history regardless of how many pages that takes. | Regression for the permanent-below-the-bound-gap finding |
| req-tap-cares-progressive-watermark-3 | First Run Has No Watermark | Proposed | With no prior rows, the collector runs a first-population fetch rather than requesting a `>=`/`created` filter with no watermark value to filter by. | Matches `github_actions_run`'s existing first-population branch; whether that fetch is bounded is `req-tap-cares-progressive-watermark-5`'s question, not this one's |
| req-tap-cares-progressive-watermark-4 | Boundary Is Inclusive And Deduplicated | Proposed | Against a fake source where two records share the watermark field's value and only one is stored before the watermark advances, the next fetch uses `>=` and returns both; the second is a no-op write against its existing natural-key row, not a duplicate and not a permanent omission. | Regression for the strict-`>` gap found in review |

### Ordered-Listing Early Cutoff
----
RID: `req-tap-cares-progressive-cutoff`

Status: `Proposed`

When a source's listing has no native filter argument but is returned in an order keyed by an
immutable property (creation time — never access time, never a mutable "last touched" field), a
collector may stop paginating the moment it reaches a run of items already on the grid whose class
confirms they are frozen — **provided the source is also declared to present that surface with
append-only visibility**, a separate claim from ordering that the mechanism does not get for free.

#### Status Details
Proposed. `actions_artifact` and `code_scanning_analysis` are both returned newest-first by
creation *(observed, github_core's own truncation-warning comments at `collector.py:5606` and
`:4766`)* and are candidates once declared `FROZEN` / `FROZEN_CONTENT_REVOCABLE` with
`SORT_KEY_MONOTONIC=True` and `APPEND_ONLY_VISIBILITY=True`. `pull_request`'s existing GraphQL
query already orders by `UPDATED_AT DESC` (`graphql_client.py:233` *observed*) — the single
cleanest case, because `updated_at` encodes "did anything change" directly rather than merely
"when was it made," but the mechanism is not wired to any watermark or cutoff today. `actions_cache`
is the declared counter-example for `SORT_KEY_MONOTONIC`: it is returned ordered by **most recently
accessed** (`collector.py:5369` *observed*), so a cache re-accessed today can resurface above a
genuinely new, never-before-seen cache lower in a stale ordering. This is exactly why
`SORT_KEY_MONOTONIC` is a required, explicit declaration (`req-tap-cares-progressive-
classification`) rather than an assumption a collector author makes once and forgets.

**Ordering and visibility are two different claims, and conflating them was this section's own
gap in an earlier draft.** `SORT_KEY_MONOTONIC` says items within one response sort by an
immutable key. It says nothing about whether the *source itself* can later surface an item whose
key value is *older* than items already confirmed frozen and known — a backfilled record, a
delayed-indexing artifact, anything the source itself did not consider fully settled at the time
of an earlier walk. Neither the completeness precondition nor the overlap window below protects
against this, because both operate on *our* collection history, not on whether the *source* ever
inserts something behind its own frontier. So cutoff requires a second, independently declared
property, `APPEND_ONLY_VISIBILITY: bool` (default `False`, per the same "declared, not inferred,
safe-by-default" rule as every other flag in this spec): the collector author's affirmative claim,
verified against the source's own documentation or behavior — never assumed from monotonic
ordering alone — that a newly visible item never sorts behind an item already confirmed known.
Where this cannot be positively verified, it stays `False` and cutoff is refused for that surface
regardless of `SORT_KEY_MONOTONIC`; the surface instead relies on `req-tap-cares-progressive-audit`
(Backlog) for its risk to be bounded by cadence rather than eliminated by a single insufficient
mechanism.

**Cutoff proves nothing about a surface whose own collection history has a hole in it**, which is
the separate, orthogonal risk the completeness precondition and overlap window below exist for —
distinct from source-side backfill above, and not a substitute for `APPEND_ONLY_VISIBILITY` any
more than the reverse. A prior run that was bounded, capped, partially failed, or filtered can
leave an isolated gap below an item that legitimately is on the grid; naive "stop at the first
known item" treats that known item as proof of everything older, which is false exactly at the
gap. So, on top of the append-only-visibility declaration above, cutoff carries two further
safeguards against *our own* collection history, both required:

1. **A completeness precondition.** Cutoff for a surface is permitted only when that surface's
   most recent walk (for this repository/scope) is recorded as `complete` in the sense
   `spec-github-core-reliability.md`'s `req-github-core-reliability-absence` already defines for
   this exact reason — no degradation, no page cap, nothing skipped. A surface with no recorded
   complete walk, or whose last complete walk predates a gap-introducing event (a failed run, a
   cap reduction), falls back to a full walk until a complete walk re-establishes the precondition.
2. **An overlap window, not a single item.** Even with the precondition satisfied, pagination
   does not stop at the *first* known-frozen item — it continues until it has seen `N` consecutive
   known-frozen items in a row (`N` a per-surface constant, default 3), then stops. A single known
   item proves nothing about a run that itself might have written that one row out of order; a
   run of several does, cheaply, at the cost of a few extra rows fetched per page boundary rather
   than a whole extra page.

#### Implementation
1. Paginate the listing as today.
2. Refuse cutoff outright for any surface not declared both `SORT_KEY_MONOTONIC=True` and
   `APPEND_ONLY_VISIBILITY=True`. This check precedes and is independent of step 3 below.
3. Before applying cutoff at all, check the surface's last recorded walk completeness
   (`req-github-core-reliability-absence`'s `complete` flag, or the equivalent this spec's
   `req-tap-cares-progressive-instrumentation` records for a non-GitHub collector). If it is not
   `complete`, cutoff is refused for this run; the walk proceeds in full and, on completing
   without degradation, records itself as the new complete baseline cutoff can trust next time.
4. With both preconditions satisfied: after decoding each page, count consecutive items already on
   the grid whose declared class confirms they are frozen — terminal state reached for
   `FROZEN_AT_TERMINAL`, unconditionally for `FROZEN`, or content-frozen for
   `FROZEN_CONTENT_REVOCABLE` (a cutoff-skipped `FROZEN_CONTENT_REVOCABLE` item still owes its own
   `EXISTENCE_RECHECK_INTERVAL` check independent of the listing walk, per
   `req-tap-cares-progressive-touch`). Stop requesting further pages only once that streak reaches
   the surface's overlap-window constant; a single known item, or a known/unknown/known sequence
   that breaks the streak, does not stop the walk.
5. This saves page-fetch cost on large, mostly-old corpora; it does not remove the first page's
   cost, which is unavoidable — the source must always be asked at least once per run whether
   anything new exists.

#### Development
The saving here scales with corpus age, not corpus size: a steady-state repository with hundreds
of old artifacts and a handful of new ones per run pays for one or two pages instead of the whole
capped listing. A repository still growing quickly sees little benefit, which is the correct and
expected shape — there is nothing to cut off yet.

The completeness precondition and overlap window were added after review of this spec's first
draft, which stopped at the first known-frozen item with no guard against a prior incomplete
*collection* walk — provably wrong, since a capped or degraded earlier pass could leave an older
item genuinely uncollected below a newer one the collector does recognize. A second review round
then separated that concern from a sharper one this draft had conflated with it: even a perfectly
complete collection history says nothing about whether the *source* can later surface an item
older than its own prior frontier (a backfilled or delayed-indexing record) — ordering
(`SORT_KEY_MONOTONIC`) and append-only source behavior (`APPEND_ONLY_VISIBILITY`) are different
claims, and only the second one bounds that risk, which is why both are now required
independently rather than one implying the other. `req-tap-cares-progressive-audit` (Backlog)
remains the deliberate, periodic *full* re-walk that bounds whatever residual risk survives all
three safeguards — cutoff reduces cost, it does not claim to eliminate the need for an eventual
full check.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-progressive-cutoff-1 | Cutoff Requires Both Declared Properties | Proposed | A collector never applies early cutoff to a surface without explicit `SORT_KEY_MONOTONIC=True` **and** `APPEND_ONLY_VISIBILITY=True`; either alone is insufficient. | Regression for the cache case (monotonicity) and the backfill case (visibility) |
| req-tap-cares-progressive-cutoff-2 | Refused Without A Complete Prior Walk | Proposed | A surface with no recorded complete walk, or a degraded/capped last walk, is walked in full this run regardless of any known-frozen items encountered; a complete walk this run is recorded as the new baseline. | Regression for the silent-gap-in-our-own-history finding |
| req-tap-cares-progressive-cutoff-3 | Overlap Window, Not A Single Item | Proposed | Against a fake listing seeded `known, known, unknown, known, known, known, known` in monotonic order, with a complete prior walk recorded and an overlap window of 3, pagination does not stop at either early `known` run and does reach and collect the `unknown` item; it stops only after the later run of (at least) 3 consecutive known items. | Replaces the single-item stop criterion found unsafe in review |
| req-tap-cares-progressive-cutoff-4 | Access-Ordered Listings Refuse Cutoff | Proposed | A collector configured with `SORT_KEY_MONOTONIC=False` (or undeclared) walks the full listing every run regardless of completeness or overlap state, and a test asserts this explicitly for `actions_cache`'s shape. | |
| req-tap-cares-progressive-cutoff-5 | Backfill Is Never Assumed Away | Proposed | Against a fake source with a recorded-complete prior walk `[100, 90, 80]` (all known-frozen) and `SORT_KEY_MONOTONIC=True`, a run exposing a new record keyed `70` is walked in full — not cut off — unless `APPEND_ONLY_VISIBILITY=True` is also declared for that surface; where it is declared, the collector's test for that surface must independently justify the claim (source documentation or contract, cited in the test), not merely set the flag to make the test pass. | Regression for the backfill finding |
| req-tap-cares-progressive-cutoff-6 | Revocable Content Is Cutoff-Eligible | Proposed | A `FROZEN_CONTENT_REVOCABLE` surface with both properties declared is cutoff-eligible on the same terms as `FROZEN`/`FROZEN_AT_TERMINAL`; a cutoff-skipped item of this class still receives its own existence recheck per `req-tap-cares-progressive-touch-2`, independent of the listing walk. | Regression for the internal-consistency finding — `actions_artifact` is the named example this class exists to cover |

### Secondary-Call Skip
----
RID: `req-tap-cares-progressive-secondary-skip`

Status: `Proposed`

When fetching one item's core listing entry requires a separate per-item call to enrich it (a
run's jobs, a job's steps, a workflow's file body), and the item is already on the grid in a
frozen state, the secondary call is skipped. For a `VERSIONED_CONTENT` type, the skip is
conditional on a cheap fingerprint check rather than unconditional, since the object can be
legitimately edited.

#### Status Details
Proposed. `github_workflow`'s YAML body is refetched via a full Contents-API call on every run for
every workflow, unconditionally (`collector.py:6987`, called from `_workflow_config` at `:1502-
1521` *observed*) — 250 workflows *(observed, github-core-tap#209's sibling investigation,
2026-09-29)* in one dev stack, each refetched in full every single pass regardless of whether the
file changed. GitHub's Contents API returns a blob `sha` alongside the content; a conditional
fetch (compare the currently-stored `FINGERPRINT_FIELD` against a cheap current-sha read, before
pulling the full body) turns the common case — nothing edited — into a near-free check.

#### Implementation
1. For a `FROZEN` / `FROZEN_AT_TERMINAL` secondary call: if the parent item is already on the grid
   in its frozen state, skip the secondary call outright. (`github_actions_job`'s per-run jobs
   fetch does not qualify for this today, because it is also how `_run_completed_at` is derived —
   a collector may only skip a secondary call it does not also depend on for computing another
   field it has not otherwise obtained.)
2. For a `VERSIONED_CONTENT` secondary call: fetch the current fingerprint only; compare against
   the stored `FINGERPRINT_FIELD`; fetch the full content only on a mismatch.
3. Every skip is still a "yes, still there" signal and feeds `req-tap-cares-progressive-touch` —
   a skipped secondary call is not silence, it is a cheap confirmation.

#### Development
This is the most GitHub-specific-looking requirement in the spec but is written generally on
purpose: any collector with an N+1 fetch pattern over already-known parents meets this exact shape,
not only ones with a content hash available. Where no fingerprint exists, `FROZEN_AT_TERMINAL`'s
unconditional skip is the fallback, not a workaround.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-progressive-secondary-skip-1 | Fingerprint Checked Before Content | Proposed | A `VERSIONED_CONTENT` type never fetches full content without first comparing a cheap fingerprint read against the stored value. | |
| req-tap-cares-progressive-secondary-skip-2 | No Skip Where The Call Also Derives A Field | Proposed | A secondary call that is the only source of a field the parent record needs (e.g. a run's completion time, derived from its jobs) is never skipped on frozen-parent grounds alone. | Named exception, github_actions_job |
| req-tap-cares-progressive-secondary-skip-3 | A Skip Still Confirms Presence | Proposed | A skipped secondary call still produces a presence-touch signal for its parent, distinguishable in the run record from an item that was actually re-fetched. | |

### Presence Touch
----
RID: `req-tap-cares-progressive-touch`

Status: `Blocked`

Confirming that an already-on-grid, frozen object is still present on the source must not produce
a full `replace_node`/`patch` write, a new history version, or a rewritten `flip_map` entry. It
bumps a last-confirmed-observed marker and nothing else.

**A touch requires the object to have actually appeared in this run's response.** This is the
one rule in this section that is not blocked on `tap#886` and must hold regardless of when that
epic lands: a presence touch is only ever issued for an object that this run's fetch genuinely
returned — as a full record, as a listing entry a secondary call was then skipped for
(`req-tap-cares-progressive-secondary-skip`), or as the subject of a `FROZEN_CONTENT_REVOCABLE`
type's dedicated existence recheck. **An object that `req-tap-cares-progressive-watermark`'s
filter or `req-tap-cares-progressive-cutoff`'s early stop caused to be excluded from the request
entirely receives no touch and no signal of any kind this run** — it is simply not observed,
exactly as `spec-github-core-reliability.md`'s absence contract already requires for a degraded
surface, and for exactly the same reason: asserting continued existence for something never
asked about is the reassuring-and-wrong shape that contract exists to forbid. This matters most
for `FROZEN_CONTENT_REVOCABLE` types, whose whole point is that the object *can* disappear
independent of anything the collector did — an old artifact excluded from a cutoff-shortened walk
must fall to its own `EXISTENCE_RECHECK_INTERVAL`, never to an inferred touch from the walk that
never looked at it.

#### Status Details
Blocked (the write-primitive half only — see the rule above, which is not blocked) on `tap#886`
("Epic: time and observation standardization"), which owns the actual mechanism — the Entity-spine
last-observed stamp and GRIFT patch-by-default write — and grew out of `tap#322` ("re-observation
is not change") and `tap#323` (the row-level batch pointer moving to the Entity spine). Two design
docs exist on unmerged branches (`docs/tap322-batch-provenance-and-grift-patch`, `docs/grid-time-
observation-standardization`); step one of that epic's own execution order is George's ruling on
Q129/Q131, not engineering. This requirement does not restate that design and must not be
implemented ahead of it — a second, competing "unchanged" write path is exactly the outcome
`req-tap-cares-progressive-classification`'s single-declaration discipline exists to prevent one
layer up.

#### Implementation
Once `tap#886` lands: every mechanism above that confirms an already-known frozen object was
actually seen this run (full fetch, secondary-skip's parent sighting, or an existence recheck)
calls the Entity-spine presence-touch primitive instead of constructing a full node envelope for
that object. An object watermark or cutoff excluded from the request is never a candidate for this
at all, regardless of when `tap#886` lands — that half of the rule is in force from this spec's
adoption, not deferred. Until `tap#886` lands, a collector adopting the read-side mechanisms above
still constructs and submits a full envelope on confirmation — real savings on fetch volume, none
yet on write/version churn, which is the acknowledged interim state `build-collector`'s own
"Re-observation is not change" section already documents.

#### Development
This section originally read as if every mechanism above converged on the same "confirmed, so
touch it" outcome — true for secondary-skip, false for watermark and cutoff, which by design mean
an old, unchanged object is not asked about at all. Blurring those together would have made
presence-touch assert existence for objects the run had no actual evidence for, exactly the defect
class `spec-github-core-reliability.md` was written to close. The observed-this-run rule above was
tightened after review of this spec's first draft for that reason and is deliberately not blocked
on `tap#886` — it constrains what a *future* touch primitive may be called for, and that
constraint is true today regardless of when the primitive itself ships.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-progressive-touch-1 | No Touch Without Observation | Proposed | A collector never issues (or, pre-`tap#886`, never *would* issue) a presence-touch call for an object excluded from a run's request by watermark filtering or early cutoff; only objects the run's response actually returned or explicitly rechecked are eligible. | Regression for the false-presence finding; testable independent of `tap#886` |
| req-tap-cares-progressive-touch-2 | Revocable Content Rechecks On Its Own Cadence | Proposed | A `FROZEN_CONTENT_REVOCABLE` object excluded from the main listing by cutoff still receives an existence check within its declared `EXISTENCE_RECHECK_INTERVAL`, sourced from a dedicated check, never inferred from the listing walk that skipped it. | |

The remaining acceptance criteria for the write primitive itself — what a touch actually writes,
and how it interacts with `flip_map`/history — are `tap#886`'s, not this spec's; they are not
restated here.

#### Future
When `tap#886` lands, this section's status moves to `Proposed` and gains acceptance criteria
naming the specific primitive it calls.

### Per-Run Call Instrumentation
----
RID: `req-tap-cares-progressive-instrumentation`

Status: `Proposed`

A collector records, per run and per surface, how many source-system calls it made, distinguishing
calls that returned an already-known frozen item (candidates for the mechanisms above) from calls
that returned something new or changed.

#### Status Details
Proposed. Checked directly against `github_core` (2026-09-29 *observed*): no request-count or
duration telemetry exists anywhere in the collector, `Batch`, `BatchEvent`, or `CollectionScope` —
there is currently no way to answer "how many API calls did one run make" from stored data at all,
only by counting call sites in the source. This requirement is listed ahead of the mechanisms it
measures deliberately: instrumenting first means every later claim of improvement is a before/after
number, not a guess, on the same collector this spec was spiked against.

#### Implementation
A structured run record (alongside `record_info`/`record_warn`, or as a field on the run's summary
`description_json`) carrying, per surface: calls made, calls that hit a cutoff or watermark skip,
calls that hit a secondary-call skip, and — once `req-tap-cares-progressive-touch` is unblocked —
presence-touches issued versus full writes issued. `spec-github-core-reliability.md`'s
`RUN_BUDGET`/`RETRY` record shape (`req-github-core-reliability-observability`) is the precedent
to extend rather than a second logging convention to invent, for any collector that has already
adopted that spec's Gather/Confirm/Process layering.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-progressive-instrumentation-1 | Calls Counted Per Surface | Proposed | A run's record names, per surface, calls made and calls skipped by each of the mechanisms above. | |
| req-tap-cares-progressive-instrumentation-2 | Present Before Any Skip Ships | Proposed | A collector may not adopt `req-tap-cares-progressive-watermark`, `-cutoff` or `-secondary-skip` for a surface without this instrumentation already covering that surface. | Ordering, not just a nice-to-have |

### Two-Pass Proof
----
RID: `req-tap-cares-progressive-proof`

Status: `Proposed`

A collector claiming a progressive win for a surface proves it the same way `build-collector`'s own
"second pass is part of the done-test" already asks every collector to prove non-duplication: run
it twice against unchanged upstream data, and assert the second run's call count for that surface
is measurably smaller than the first's.

#### Status Details
Proposed. Generalizes `build-collector`'s existing informal guidance ("the second pass's job
summary and API-call count should be a fraction of the first's") into a checked acceptance test,
made possible only once `req-tap-cares-progressive-instrumentation` exists to produce the number.

#### Implementation
In the proof harness (a fake source scripted per `spec-github-core-reliability.md`'s pattern, or
equivalent for a non-GitHub collector): run the collector once against a seeded corpus, then again
with no change to the fake's data. Assert the second run's per-surface call count for every
mechanism-adopting surface is strictly lower than the first's, and that the **resulting grid
state** — the live rows for that surface, their natural keys and their current field values — is
identical after both runs. **This is deliberately not a claim about the second run's *emitted*
envelope count.** A working watermark or cutoff is supposed to emit fewer envelopes on the second
pass than the first — that reduction is the entire point of this spec, and a correctness check
that required identical per-run emission counts would fail every collector that correctly adopted
these mechanisms, which is the opposite of what this requirement is for. What must not change is
where the data ends up, not how many envelopes the second run bothered to construct to get there.

#### Development
The first draft of this requirement asked for identical *emitted* node/edge counts across both
passes, which review correctly identified as self-defeating: an effective watermark or cutoff
necessarily emits a subset on the unchanged second pass, so that criterion would reject every
implementation this spec asks for. The fix compares final grid state instead, which is what
`build-collector`'s own existing duplicate-natural-key check (Step 9's second pass) already
verifies for a non-progressive collector — this requirement extends that same check to also
assert a call-count reduction, rather than inventing a second, conflicting notion of "correct."

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-progressive-proof-1 | Second Pass Costs Less | Proposed | For each surface with an adopted mechanism, the second pass's call count is strictly lower than the first's against unchanged fake data. | |
| req-tap-cares-progressive-proof-2 | Grid State Converges, Emission Count Is Not The Check | Proposed | After both passes, the live rows for each mechanism-adopting surface — natural keys and field values — are identical to running the collector once without any progressive mechanism adopted; the second pass's *emitted* envelope count is explicitly allowed, and expected, to be lower than the first's. | Rewritten after review found the original wording self-defeating; runs alongside the existing duplicate-key check from `build-collector` Step 9's second pass |

### Full-Corpus Reconciliation Pass
----
RID: `req-tap-cares-progressive-audit`

Status: `Backlog`

A watermark can be wrong. A cutoff's monotonicity assumption can quietly stop holding (a source
changes its default sort order without documenting it). A deliberately non-progressive, full
re-walk of a surface — on a slow cadence, or triggered by suspicion rather than the clock — is the
check that an incremental path's own bugs have not silently drifted the grid away from the source.
Needs a place to live (a collector-level "full resync" mode, or a separate scheduled job) that does
not yet exist for any collector. Enter a sprint once the mechanisms above are live for at least one
real surface and there is a concrete cadence question to answer, rather than speculating about one
now.
