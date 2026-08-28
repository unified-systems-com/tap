# `tap_cares`

## Blurb

Partitions the machinery that *does* the collecting away from the data it collects — the ingestion apparatus, marked so it never reads as part of the estate.

## Purpose

TAP models its own collection machinery on its own grid: a `Collector` is a node, so is each `CollectionJob` it runs, so is the `Schedule` that triggers it and each `ScheduleFire` that schedule produced. That is the right design — a collection run becomes queryable, historied, and connectable to the batch it landed — but it creates the same hazard as the web furniture. A count of nodes on an instance that has collected three repositories should not be dominated by the job records describing the act of collecting them.

`tap_cares` is that partition: the apparatus, distinguished from the observations it produced.

## Goals

- Separate ingestion machinery from ingested data, so neither distorts a count or a view of the other.
- Keep collection auditable as graph data — a job's history, its schedule, its batch — rather than as log lines.
- Make "show me the collection apparatus" a dimension filter rather than a list of four entity types that a fifth would silently fall out of.

## Identity

The key is `tap_cares` — the app that owns it. Note it carries **no dot**: it is a flat namespace where `tap.meta` and `tap.graph` are nested under `tap.`. That inconsistency is real and is recorded here rather than quietly normalised, because a dimension key is effectively immutable: it is written into every entity's `dimensions` JSONB and covered by a GIN index, so renaming it to `tap.cares` would be a migration across the whole grid, not an edit. It is named for the owning app, which makes ownership unambiguous even if the spelling is not uniform.

## Boundaries

- **Not the collected data.** Nodes a collector *lands* carry the source plugin's own dimensions (`github.platform`, and so on), never this one. The apparatus is marked; its output is not.
- **Not the batch.** A GRIFT batch is the grid's own record of a write and belongs to `tap_grid`, not to the collector that produced it.
- **Not scheduling policy.** Whether a schedule *should* fire, and the recurrence rules behind it, are fields and spec behaviour; the dimension only says the node is part of the apparatus.
- **Not a marker of internal-only.** `Collector` also declares `INTERNAL_ONLY`, which is a separate access-shaped decision. Two different questions; do not conflate the partition with the exposure rule.

## Neutrality

**TAP-specific.** Any ingestion system has collectors and jobs, but this dimension exists because TAP puts its own apparatus on its own spine, and its name is literally the owning app's. Not a neutral-substrate candidate.

## Observability

**Always fully observable — declared, never fetched.** Applied from `DEFAULT_DIMENSIONS` at entity creation (`req-grid-dimension-dc`), so it is present the moment a collector, job, schedule or fire exists. It can never be absent because a credential could not see it, which distinguishes it sharply from a collected dimension whose absence is ambiguous.

The gap worth naming is that the values enumerate node *types*, so the vocabulary grows whenever the apparatus does. A fifth `tap_cares` node type that forgot the stamp would silently join the estate partition — a declaration gap, not an observation one, and now caught: the coverage guard fails on a value no article explains.

## Authoritative Source

- **Source:** `tap_cares/specs/spec-tap-cares-collector.md` and the sibling collection-job, schedule and task-backend specs; the declarations in `tap_cares/models.py`
- **Version:** declarations as of commit `b7b35149`
- **Retrieved:** 2026-08-27

## Prior Art

- `tap_grid/specs/spec-grid-dimension.md` (2026-08-27) — default-dimension application, and the dot-notation nesting convention this key predates.
- `tap_cares/specs/spec-tap-cares-collector.md` (2026-08-27) — the collector contract and its registry-key discipline.
- `specs/spec-dev-validation.md` (2026-08-27) — the honest-accounting posture this article follows in recording the flat-key inconsistency rather than hiding it.

## Values

Each value names one node type in the apparatus, and together they are the ingestion lifecycle end to end:

- `collector` — a registered collector definition: what can be collected and by which registered class. The apparatus at rest.
- `collection_job` — one execution of a collector: its status, its run mode, what it landed. The apparatus in motion, and the node an operator actually reads when a collection went wrong.
- `schedule` — a recurrence definition pointing at a collector: the intent to collect repeatedly.
- `schedule_fire` — one firing of a schedule. Separate from `collection_job` on purpose: a schedule can fire and produce no job (suppressed, already running, failed to start), and collapsing the two would make that failure invisible — the firing would simply not exist rather than existing with nothing behind it.
