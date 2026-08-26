# Dev Boot Collectors

> **Absorbed by `specs/spec-tap-boot-v0.md` (2026-06-12); absorption completed when boot v0 landed 2026-06-24.** The unified TAP bootloader generalizes this spec: collector firing is the `fire-collector` step-type inside the boot profile's `population` phase (`req-boot-population`). The standalone `fire_boot_collectors` management command **and its `tap_cares/schemas/boot-profile.schema.json` are now removed**; the flat collector-only profile shape (`version: 0`, top-level `collectors[]`) is superseded by the ordered-steps profile (`version: 1`, `population.steps` of `seed-plugin`/`fire-collector`) owned by `tap_boot`. The mechanics defined here — firing via `run_collection`, sequential await-to-terminal firing, per-profile `on_failure`, opt-in selection — survive as `tap_cares.services.fire_collector_and_await` (the single-collector fire-and-await) driven by `tap_boot`'s population phase; this spec's RIDs remain the detailed contract for *how a collector is fired*, while the boot spec owns *when, and in what larger sequence*. The historical prose below describes the pre-absorption command and is retained for context only.

## Philosophy

A freshly-spawned TAP stack comes up empty of *collected* state. Migrations run,
GRIFT seeds land the hand-authored graph (pages, layouts, schedules, catalogs),
but the data that collectors pull from the outside world — AWS resources from
the boto3 collector, GitHub repos from the github collector, samsite's signed
compliance artifacts — only appears when a collector actually runs. Today that
happens on the `tap_cares` cron schedule, so a developer who spawns a session at
3pm sees no AWS/GitHub/compliance data until the next scheduled slot.

For the single-developer dog-fooding loop this is the wrong default. We want a
boot to be able to come up *populated*, deterministically, so the attached
session has real collected data from the first request.

This spec defines a **dev/debug bootstrap**: an ordered, file-driven firing of
collectors right after seeding, organized as named **boot profiles**. It is
deliberately **not** persisted in the database and **not** the production
scheduler. Profiles are hardcoded, version-controlled JSON files in a top-level
`boot/` directory, each saying "fire these collectors, in this order, now,"
because:

- **It is a boot action, not durable state.** Expressing "run once at boot" as a
  DB schedule row would distort the schedule model, which is about recurring
  cadence.
- **It is for debugging.** Plain editable files let a developer reorder, disable
  a single collector, keep several named scenarios side by side, and read
  exactly what a boot will do — no migration, no GRIFT, no shell.
- **Order is load-bearing.** Collectors have run-order dependencies. The samsite
  compliance collector's boundary-membership step (specified in the samsite plugin repo)
  reads `aws_account` nodes, so the boto3 collector must run *before* it for the
  boundary edges to mint in a single boot pass. A file makes that order explicit
  and auditable.

Two design choices keep it safe and simple:

- **Opt-in.** Firing happens only when a profile is explicitly selected. With no
  profile selected, the command is a clean no-op — nothing reaches out to AWS or
  GitHub. A plain `docker compose up` on the primary stack therefore fires
  nothing; it must be asked.
- **Many profiles, one shared schema.** Adding a scenario is dropping a new
  validated JSON file in `boot/`, not writing code.

The production "wake up and catch up on missed scheduled runs" mechanism is a
separate, orthogonal concern (a `catchup` policy on the schedule model) and is
**not** in scope here. Boot profiles are the dev path; the scheduler is the
deployed path.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Populated On Boot | When a profile is selected, its collectors fire after seeding so the stack comes up with real collected data. |
| 2. | Files, Not Database | Boot order lives in version-controlled JSON profiles under `boot/`, never DB state. |
| 3. | Named Profiles | Multiple scenarios (full, aws-only, self-test, …) coexist as separate files; one shared schema validates them all. |
| 4. | Opt-In | No profile selected ⇒ nothing fires. Outbound collection at boot is never implicit. |
| 5. | Explicit Order | Within a profile, collectors fire sequentially in declared order; run-order dependencies are expressed by position. |
| 6. | Configurable Failure Policy | Each profile declares what happens when a collector fails; the current default is to **abort** (fail loud) rather than assume success. |
| 7. | Reuse Existing Machinery | Fires collectors through the existing `run_collection` service path; adds no new collector or scheduler framework. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-dev-boot-collectors-profiles | [Boot Profiles Directory](#boot-profiles-directory) | Proposed | Top-level `boot/`; one shared JSON Schema; filename is the profile id |
| req-dev-boot-collectors-command | [Fire Command](#fire-command) | Proposed | `manage.py fire_boot_collectors`; resolves keys, fires via `run_collection`; `--profile` / `--list` |
| req-dev-boot-collectors-profile-selection | [Profile Selection (Opt-In)](#profile-selection-opt-in) | Proposed | `--profile` > `TAP_BOOT_PROFILE` env > none ⇒ no-op |
| req-dev-boot-collectors-ordering | [Sequential Ordered Firing](#sequential-ordered-firing) | Proposed | Declared order is fire order; one at a time |
| req-dev-boot-collectors-failure-policy | [Failure Policy](#failure-policy) | Proposed | `on_failure` per profile; default `abort` |
| req-dev-boot-collectors-spawn-integration | [Spawn Integration](#spawn-integration) | Proposed | New spawn step after seed; profile via `.env.local` `TAP_BOOT_PROFILE` |
| req-dev-boot-collectors-nongoals | [Non-Goals](#non-goals) | Proposed | Not the production scheduler; profile composition deferred |

---

### Boot Profiles Directory
----
RID: `req-dev-boot-collectors-profiles`
Status: `Proposed`

Boot profiles live in a **top-level `boot/`** directory. Each profile is one
JSON file; the **filename is the profile id** (`boot/full.boot.json` → profile
`full`). A single shared JSON Schema validates every profile:

- Profiles (data): `boot/<profile>.boot.json`
- Schema: `tap_cares/schemas/boot-profile.schema.json` — co-located with its
  loader (the `fire_boot_collectors` command lives in `tap_cares`; see
  [Fire Command](#fire-command)), next to the existing
  `tap_cares/schemas/collection_job_results.schema.json`. Authored in the same
  change; the command validates each profile against it and fails loud on a
  violation, per the standing "new structured format ships a JSON Schema,
  validated at load" rule. `boot/` holds profile **data only** — the schema does
  not live in the data directory, and there is no top-level `schemas/` (the repo
  convention is that schemas co-locate with the app/code that owns them).

> **Path note.** The profile *data* directory `boot/` is top-level rather than
> under `dev/` because boot profiles are expected to outgrow pure dev/debug use
> (e.g. a `demo` profile). Until there is a non-dev profile, this remains dev
> tooling; the location is the only thing that anticipates the broader use. The
> schema and command remain in `tap_cares` regardless.

Profile shape (v0):

```json
{
  "version": 0,
  "description": "Full boot — AWS + GitHub + KSI catalog, then samsite compliance.",
  "on_failure": "abort",
  "collectors": [
    { "key": "plugins.aws_core.collectors.boto3_collector.collector:boto3", "enabled": true },
    { "key": "plugins.github_core.collectors.github_collector.collector:github_core", "enabled": true },
    { "key": "plugins.fedramp_20x_ksi.collectors.ksi_catalog:ksi-catalog", "enabled": true },
    { "key": "plugins.samsite.collectors.compliance_collector.collector:samsite-compliance", "enabled": true, "note": "must run after boto3 — reads aws_account for boundary membership" }
  ]
}
```

Fields:

- `version` (int, required) — profile schema version. `0` for v0.
- `description` (string, optional) — human label for `--list` and review.
- `on_failure` (enum, required) — `"abort"` | `"continue"`; see
  [Failure Policy](#failure-policy).
- `collectors` (array, required) — ordered list. Each entry:
  - `key` (string, required) — the collector's **qualified registry key**
    (`scope:key`), exactly as stored in `Collector.collector_registry` / the
    `collector_registry` registry (e.g.
    `plugins.aws_core.collectors.boto3_collector.collector:boto3`). The command
    resolves each key against the registry and **fails loud** on an unknown key.
  - `enabled` (bool, required) — `false` skips the entry without removing it
    (the debug-friendly "comment it out" affordance).
  - `run_mode` (enum, optional) — `"full"` (default) | `"self_test_only"`.
    `self_test_only` runs only the collector's readiness probe (the existing
    `CollectionJobRunMode.SELF_TEST_ONLY` path) — e.g. a `self-test` profile that
    validates every collector's credentials without a full collection.
  - `note` (string, optional) — free-text annotation for the human reader.

Representative profiles a developer might keep: `full`, `aws-only`,
`compliance-only`, `self-test` (all entries `self_test_only`), `minimal`. The
format is intentionally small in v0 but is expected to grow (per-entry overrides,
credential gating, parameterized inputs); the shared schema is the place that
growth is declared.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-boot-collectors-profiles-1 | Shared Schema Authored + Validated | Proposed | `tap_cares/schemas/boot-profile.schema.json` exists and the command validates each selected profile against it at load, failing loud on violation. | |
| req-dev-boot-collectors-profiles-2 | Filename Is Profile Id | Proposed | A profile is selected by the basename of its file (`boot/full.boot.json` ⇒ `full`). | |
| req-dev-boot-collectors-profiles-3 | Disabled Entries Skipped | Proposed | An entry with `enabled: false` is not fired and does not error. | |
| req-dev-boot-collectors-profiles-4 | Unknown Key Fails Loud | Proposed | A `key` absent from the collector registry aborts the run with a clear error before any collector fires. | |

---

### Fire Command
----
RID: `req-dev-boot-collectors-command`
Status: `Proposed`

A Django management command, `fire_boot_collectors` (in
`tap_cares/management/commands/`, alongside the existing collector-lifecycle
commands), is the executable surface:

1. Resolves the profile per [Profile Selection](#profile-selection-opt-in). If
   none is selected, **exits 0 without firing** (clean no-op, logged).
2. Reads `boot/<profile>.boot.json`; validates it against the shared schema; aborts on
   violation or a missing profile file.
3. Pre-resolves every enabled entry's qualified key to its `Collector` entity;
   an unknown key aborts here, before any collector fires.
4. For each enabled entry, in declared order: fires the collector via
   `tap_cares.services.run_collection` (`manual_run=True`,
   `manual_run_source="fire_boot_collectors"`, `run_mode` per entry) and
   **awaits its `CollectionJob` to a terminal state** (`SUCCESSFUL` / `FAILED`)
   before firing the next. The real app runs collectors asynchronously on the
   Steady Queue backend — a worker drains the job out-of-process — so
   `run_collection` only enqueues; the command polls `CollectionJob.status` to
   terminal (per-collector wait bounded by `--timeout`, default 600s; a timeout
   is treated as a failure). Await-to-terminal is also what makes ordering
   real: `samsite` does not fire until `boto3` has actually finished.
5. Applies the [Failure Policy](#failure-policy) on a failed (or timed-out) job.
6. `--list` enumerates the profiles in `boot/` (id + `description`) and exits
   without firing.
7. Exits non-zero if a selected profile is missing/invalid, references an unknown
   key, or (under `abort`) any collector failed — so a spawn step gates on it.

The command does not create schedules, does not write profiles, and adds no new
collector framework — it is a thin profile reader + sequential `run_collection`
driver.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-boot-collectors-command-1 | Fires Via run_collection | Proposed | Each enabled collector is started through `run_collection`, not a bespoke path. | |
| req-dev-boot-collectors-command-2 | List Profiles | Proposed | `--list` prints available profile ids + descriptions and fires nothing. | |
| req-dev-boot-collectors-command-3 | Exit Code Reflects Outcome | Proposed | Non-zero exit on missing/invalid profile, unknown key, or (under `abort`) any collector failure; exit 0 when no profile is selected. | |

---

### Profile Selection (Opt-In)
----
RID: `req-dev-boot-collectors-profile-selection`
Status: `Proposed`

The profile is resolved in this order, first hit wins:

1. `--profile <id>` command flag (explicit; for manual runs and tests).
2. `TAP_BOOT_PROFILE` environment variable (per-session selection; see
   [Spawn Integration](#spawn-integration)).
3. **Nothing.** If neither is set, the command does not fire any collector and
   exits 0.

The no-selection no-op is the safety property: outbound collection at boot is
never implicit. A stack only reaches out to AWS/GitHub/etc. when a human (or a
session's `.env.local`) has named a profile. This also makes the primary stack's
plain `docker compose up` fire nothing, with no special-casing — it simply has no
`TAP_BOOT_PROFILE`.

`TAP_BOOT_PROFILE` slots into the existing per-session env cascade
(`req-dev-multisession-env-cascade`), so each spawned session can choose its own
profile (or none) without a per-session file — the per-session override we had
otherwise deferred falls out of this for free.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-boot-collectors-profile-selection-1 | Resolution Order | Proposed | `--profile` overrides `TAP_BOOT_PROFILE`; either selects a profile. | |
| req-dev-boot-collectors-profile-selection-2 | No Selection Is No-Op | Proposed | With neither set, no collector fires and the command exits 0. | |

---

### Sequential Ordered Firing
----
RID: `req-dev-boot-collectors-ordering`
Status: `Proposed`

Within a profile, collectors fire **one at a time, in declared order** — never
concurrently — and each collector's job is **awaited to a terminal state before
the next fires**. The declared order *is* the dependency order; the profile is
the single place that ordering lives. Sequential await-to-terminal is required
because later collectors may read grid state written by earlier ones in the same
boot pass, and (on the async Steady Queue backend) firing without awaiting would
let a dependent collector run before its predecessor finished.

Concrete v0 dependency the order must honor: the samsite compliance collector
(`samsite-compliance`) reads `aws_account` nodes to synthesize authorization-
boundary membership (per the samsite plugin's boundary-membership requirement, in
the samsite plugin repo), so the boto3
collector (`boto3`) must precede it in any profile that includes both. If the
order were violated the samsite collector would simply mint zero boundary edges
that pass (self-healing on the next daily run), but a single boot pass would not
fully populate — hence order matters for the goal of "populated on boot."

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-boot-collectors-ordering-1 | Declared Order Honored | Proposed | Collectors fire strictly in array order, sequentially, no overlap. | |
| req-dev-boot-collectors-ordering-2 | Samsite After Boto3 | Proposed | Any profile containing both orders `samsite-compliance` after `boto3` so boundary membership mints in one boot pass. | |

---

### Failure Policy
----
RID: `req-dev-boot-collectors-failure-policy`
Status: `Proposed`

Each profile's top-level `on_failure` controls behavior when a collector's job
terminates in a failed state:

- `"abort"` (current default) — stop firing immediately, do not run the
  remaining collectors, and exit non-zero. **This is the chosen default for the
  current situation: we would rather the boot die than silently proceed as if
  everything collected successfully.** A failed collector at boot is a signal to
  investigate, not to paper over.
- `"continue"` — log the failure and proceed to the next collector; exit code
  still reflects that at least one collector failed, but every collector gets a
  chance to run.

Failure policy is profile configuration, not a command flag, so the declared
boot behavior travels with the profile and is reviewable in version control.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-boot-collectors-failure-policy-1 | Abort Stops + Fails | Proposed | Under `abort`, the first failed collector halts the run, skips the rest, and the command exits non-zero. | |
| req-dev-boot-collectors-failure-policy-2 | Continue Runs All | Proposed | Under `continue`, a failure is logged, subsequent collectors still fire, and the exit code still signals the failure. | |
| req-dev-boot-collectors-failure-policy-3 | Default Is Abort | Proposed | The shipped profiles set `on_failure: "abort"`. | |

---

### Spawn Integration
----
RID: `req-dev-boot-collectors-spawn-integration`
Status: `Proposed`

`scripts/spawn-session.sh` runs the fire command as a new step immediately after
Step 6 (`import_plugin_grift --all`) — seed first, then populate from collectors.
The step runs inside the web container (collectors need DB + secrets context),
mirroring how the seed step runs there:

```sh
scripts/dc exec web uv run python manage.py fire_boot_collectors
```

The session's profile is carried by `TAP_BOOT_PROFILE` in its `.env.local`
(`req-dev-multisession-env-cascade`), surfaced into the web container via the
`TAP_BOOT_PROFILE` entry in `docker-compose.yml`'s `web` environment (empty
default, like `TAP_SESSION_LABEL`). The profile is chosen **explicitly per
spawn** as spawn's positional boot-profile argument
(`spawn-session.sh <name> [cli|codex|vscode] [<boot-profile>]`, e.g.
`spawn-session.sh full-stack cli test_all`; the samsite demo boots via its
in-package record, `spawn --from <plugin-ref>#samsite`), or via the equivalent
`--boot <profile>` flag; spawn writes the value into `.env.local`. **There is no
default** — omitting it writes an empty value, so the step is a clean no-op and
the session boots plain (seeded but not collector-populated). The deliberate
choice is that the developer names the profile each spawn rather than silently
inheriting one. The primary stack sets nothing, so a plain `docker compose up`
fires nothing either.

Because the command exits non-zero on a failed collector (under `abort`) or an
invalid/missing selected profile, the spawn aborts and fires its failure trap
rather than leaving a half-populated session — consistent with how the strict
grift import gates the spawn today.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-boot-collectors-spawn-integration-1 | Runs After Seed | Proposed | The fire step runs after `import_plugin_grift --all`, in the web container. | |
| req-dev-boot-collectors-spawn-integration-2 | Gates The Spawn | Proposed | A non-zero exit from the fire command aborts the spawn and triggers its failure handling. | |
| req-dev-boot-collectors-spawn-integration-3 | No Profile, No-Op Spawn Step | Proposed | A session without `TAP_BOOT_PROFILE` runs the step as a no-op and spawns normally. | |

---

### Non-Goals
----
RID: `req-dev-boot-collectors-nongoals`
Status: `Proposed`

- **Production scheduler catch-up.** "On wake, run any scheduled slot we missed"
  is a `catchup` policy on the schedule model — a separate, deployable mechanism.
  Boot profiles are the dev/debug path and do not touch the scheduler.
- **Profile composition.** Profiles are flat and independent in v0. "`compliance`
  extends `full`" / include-another-profile is a future seam, not built — no
  include-resolver until there is demand.
- **Concurrency.** Collectors fire sequentially; parallel firing is explicitly
  out of scope (order is the whole point).
- **Profile authoring tooling.** Profiles are hand-edited JSON; no generator or
  UI in v0.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-boot-collectors-nongoals-1 | Scheduler Untouched | Proposed | The boot-fire mechanism adds no schedule rows and does not alter scheduler behavior. | |
| req-dev-boot-collectors-nongoals-2 | No Composition In v0 | Proposed | Profiles do not include or extend one another in v0. | |

## Status Vocabulary

Standard TAP states: `Proposed`, `Approved for Development`, `In Development`,
`Implemented`, `Verified`, `Refactoring`, `Deprecating`, `Deprecated`,
`Backlog`.
