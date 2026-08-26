# TAP Boot Observability Specification

## Philosophy

Boot is TAP's zero-touch standup (`spec-tap-boot-v0.md`): one command, fixed phases, fails loud. This spec closes the gap between *fails loud* and *fails legible* — the difference between "boot aborted" and knowing, in seconds, **which step died, why, and what to fix**, without re-running anything.

The motivating incident (2026-08-09, the samsite spawn): a fine-grained GitHub PAT had been revoked provider-side (the org-migration credential deletion wave), leaving a dead credential in `TAP_SECRETS_ROOT` that still *parsed* cleanly. Boot installed 11 plugins, seeded six of them, ran a full AWS collection — then aborted ~2.5 minutes in at `fire-collector:github_core:github_core` with a one-line summary (`GitHub API unreachable or PAT auth failed`). The detail that named the actual cause (`/rate_limit` → 401 Bad credentials, distinguishing *revoked token* from *network down* from *wrong scope*) existed in the collector's structured self-test result but was never surfaced. And because `manage.py boot` runs via `exec` from the spawn terminal, its output evaporated with that terminal — the container log looked clean, and diagnosis required re-running boot to reproduce the failure.

Three principles, one per failure mode:

1. **Fail early.** Collector credentials and reachability can be checked in seconds, before minutes of seeding and collection. The check already exists — every collector ships `self_test()` (`spec-tap-cares-collector.md`) — boot just never calls it before committing to population.
2. **Fail with the evidence.** When a collector step kills the boot, the structured check results (which carry the provider's status code and error body) must ride the abort output and the ABORT signal — not just the one-line summary. The evidence is already persisted (`CollectionJob.self_test`); surfacing it is a read, not new machinery.
3. **Leave a record.** Every boot run — success or abort — writes a durable, machine-legible record of what happened: phases, steps, outcomes, durations, resolved boot variables with provenance, failing checks. The record is what a human, the `/diagnose-failed-session-spawn` skill, or a Player-3 AI assistant reads *instead of* re-running boot. This realizes the durable boot report `req-boot-report` deferred.

The corollary for the dev standup: once the record/transcript retains the detail, the spawn script's job is **presentation** — a clean per-step status line for the human watching, with the full firehose captured to a file rather than streamed at them.

This is the AI-integration cheap-edge discipline (`specs/spec-ai-integration.md`) applied to boot: the standup's outcome becomes a declarative, queryable artifact rather than scrollback.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Fail Early | Dead credentials / unreachable upstreams surface in seconds via a readiness preflight, before population mutates anything expensive. |
| 2. | Fail With Evidence | An aborting collector step surfaces its structured self-test checks — status codes and error detail — in the boot output and ABORT signal. |
| 3. | Durable Record | Every boot run leaves a machine-legible record (success or abort) that diagnosis reads instead of re-running boot. |
| 4. | Clean Presentation | The dev spawn shows one informative status line per step; the full transcript is captured, not streamed. |

## Roadmap Alignment

These requirements were written under `step-rampart-launch-ready` (Achieved) and `step-rampart-first-paying-customer` (Superseded), whose boot pillars were "repeatable instance bring-up" and standups that fail legibly with nobody familiar at the terminal. Both demands survive their steps and now sit under the friends preview. A demo-morning standup that burns 2.5 minutes before revealing a stale credential — and then requires a re-run to see why — is exactly the risk these requirements retire. All four are small surfaces over existing machinery (the self-test contract, the persisted `CollectionJob.self_test`, the ABORT signal, the spawn script); none is new framework.

## Relationship To Other Specs

- **Extends `specs/spec-tap-boot-v0.md`.** That spec owns the boot contract (phases, population, abort signal, logging). This spec adds the observability surfaces around it: preflight, abort detail, the durable record (`req-boot-report`'s deferred half), and standup presentation. `req-boot-variable-resolution-3`'s promised "effective value + provenance in the boot/install report" lands in this spec's record.
- **Consumes `tap_cares/specs/spec-tap-cares-collector.md`.** The self-test contract is owned there and not re-implemented here: self-test is phase 1 of a `CollectionJob`, `run_collection(run_mode="self_test_only")` is the only way to produce a fresh readiness result, and `CollectionJob.self_test` is its sole persistence (`req-tap-cares-collector-self-test`). The preflight is a *caller* of that contract, exactly like the CARES administrivia surface.
- **Feeds `specs/spec-dev-multisession-diagnose.md`.** The diagnose procedure's evidence base gains the boot record and the captured spawn transcript; "re-run boot to reproduce" becomes the fallback, not the first move.
- **Follows `specs/spec-tap-json-files.md`** for the record: a documented schema with descriptions on every field, so AI and security readers can consume it without code-reading.
- **Presentation ownership:** `scripts/spawn-session.sh` remains governed by `spec-dev-multisession.md` (`req-dev-multisession-spawn-script` — flow, registry, failure trap). `req-boot-obs-spawn-presentation` here owns only the *output contract* of the standup steps; it deliberately preserves the abort fast-fail semantics of `req-boot-abort-signal-3/-4`.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-boot-obs-preflight | [Collector Readiness Preflight](#collector-readiness-preflight) | Implemented | Self-test every profile-fired collector before population mutates; report all failures at once |
| req-boot-obs-abort-detail | [Abort Carries The Checks](#abort-carries-the-checks) | Implemented | A failing collector step surfaces its persisted self-test checks, not just the summary line |
| req-boot-obs-record | [Durable Boot Record](#durable-boot-record) | Implemented | Per-run machine-legible JSON record (success or abort); realizes `req-boot-report`'s deferred report |
| req-boot-obs-spawn-presentation | [Spawn Presents, The Log Retains](#spawn-presents-the-log-retains) | Implemented | Per-step status lines; full transcript captured to `logs/spawn.log`; verbose escape hatch |

---

### Collector Readiness Preflight
----
RID: `req-boot-obs-preflight`
Status: `Implemented`

> **Built 2026-08-09.** `tap_boot/orchestrator.py:_preflight_collectors`, placed after the collector-node reconcile and before the first seed step; toggle resolved via the now-public `tap.preboot.resolve_var` ladder. Covered by `tap_boot/tests/test_orchestrator.py` (abort-before-seed, batch verdict, continue-mode skip, env/profile disable both loud).

Before the population phase mutates anything, boot runs the self-test of **every** collector named by an enabled `fire-collector` step in the profile, and applies the profile's failure semantics to the combined result. A standup doomed by a dead credential fails in seconds, before seeding, and names *all* broken collectors at once — not serially, one abort per re-run.

#### Implementation

- **Placement.** Within the population phase, after pre-resolution (`req-boot-population-4`, no mutation) and the collector-node reconcile (which the self-test path requires), and **before the first `seed-plugin` step**. Order of preflights follows the declared step order; each is awaited to a terminal state before the next (the self-test timeout is the collector contract's own live-check bound, not the fire step's `timeout_seconds`).
- **Mechanism — a caller, not a second implementation.** The preflight produces readiness via the cares contract's only sanctioned path: `run_collection(run_mode="self_test_only")` awaited to terminal (`req-tap-cares-collector-self-test-16`). Results therefore persist on `CollectionJob.self_test` for free, giving the boot record (`req-boot-obs-record`) and the CARES administrivia surface the same queryable trail. Boot does not call `self_test()` directly and does not persist readiness anywhere else.
- **Failure semantics.** All preflights run to completion before any verdict (the batch answer — a dead AWS key *and* a dead PAT surface in the same run). Then the profile's `on_failure` applies: `abort` → boot aborts with every failing collector's checks (`req-boot-obs-abort-detail`) before a single seed has mutated the grid; a future per-step criticality (`req-boot-collector-criticality`) applies per collector when it lands. A collector whose preflight failed under non-abort semantics has its `fire-collector` step skipped and recorded as such — firing a collector that just proved unready is wasted minutes.
- **Outbound honesty.** Self-tests make live network calls. This adds **no new outbound surface**: the profile already declared these exact collectors would fire this boot; the preflight reaches the same endpoints earlier, with cheaper calls (`/rate_limit`, `sts:GetCallerIdentity` class). This is deliberately *not* part of `req-boot-validate`'s offline validation — dry-run stays offline; preflight runs only when boot will actually fire.
- **Duplication accepted.** The fire step's own phase-1 self-test still runs at fire time (the job contract; it stays authoritative for that run). The preflight is fail-early, not fail-authoritative; the double check costs seconds and keeps the cares contract untouched.
- **Escape hatch.** A boot variable `population.collector_preflight` (default **true**; env `TAP_BOOT_POPULATION__COLLECTOR_PREFLIGHT` per `req-boot-variable-resolution`) disables it — for air-gapped rehearsal against a pre-populated DB, or a deliberately-degraded standup. A skip logs loud (WARNING), the same posture as the disabled snapshot.
- **Declared-secret presence first (`req-boot-required-secrets`, built 2026-08-09).** When the profile declares `required_secrets` (`spec-tap-boot-v0.md`), the preflight opens by checking the effective set (entries referenced by enabled steps) for on-disk presence + kind match — offline, before any live self-test call, joining the same batch verdict. This splits the two failure classes the self-test alone conflates: absent-secret (a provisioning gap — mint it) vs dead-credential (a liveness gap — rotate it).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-obs-preflight-1 | Runs Before First Seed | Implemented | Every enabled `fire-collector` step's collector is self-tested (via `run_mode="self_test_only"`) after reconcile and before any `seed-plugin` step mutates the grid. | |
| req-boot-obs-preflight-2 | Batch Verdict | Implemented | All preflights complete before failure semantics apply; an abort names every failing collector, not only the first. | |
| req-boot-obs-preflight-3 | Persisted Via The Contract | Implemented | Readiness results persist on `CollectionJob.self_test` through `run_collection`; boot adds no parallel readiness store. | |
| req-boot-obs-preflight-4 | Skip Is Loud | Implemented | `population.collector_preflight=false` skips with a WARNING and is recorded in the boot record with provenance. | |
| req-boot-obs-preflight-5 | Unready Fire Skipped | Implemented | Under non-abort semantics, a collector whose preflight failed is not fired; the skip is recorded. | |
| req-boot-obs-preflight-6 | Declared Secrets Checked First | Implemented | `required_secrets` entries referenced by enabled steps are checked (presence + kind, offline) at the head of the preflight batch, before live self-tests; failures join the batch verdict and name `scope:key` + expected kind, never values. | `req-boot-required-secrets-5`. |

#### Future

- Fold the preflight verdicts into `manage.py health` as an opt-in credential-liveness tier (the per-consumer conditional-secret-validation pattern), so a dead credential is detectable any day — not only at boot. Deferred: health today is deliberately network-free; a live tier is a posture change that deserves its own decision.

---

### Abort Carries The Checks
----
RID: `req-boot-obs-abort-detail`
Status: `Implemented`

> **Built 2026-08-09.** `BootError` carries structured `detail`; `tap.logging.abort()` gained the nested `detail` kwarg (contract updated in `spec-tap-logging.md` `req-tap-logging-abort-signal`); failing checks echo beneath the step's FAILED line and ride the boot record's abort block. Covered by `tap_boot/tests/test_orchestrator.py` + `tap/tests/test_logging_abort.py`.

When a collector step (preflight or fire) fails, boot surfaces the **structured self-test checks** — check id, status, message with the provider's status code and truncated error body, readiness status — in its output, in the ERROR log, and in the ABORT signal's structured data. Never only the one-line summary.

#### Implementation

- **The evidence already exists.** The collector self-test writes per-check detail (e.g. `GITHUB_API_REACHABLE: GitHub /rate_limit failed: status=401 body={"message": "Bad credentials"…}`) into the result persisted on `CollectionJob.self_test`. Today the orchestrator prints only `job.summary`. The change is a read: on step failure, echo the failing checks beneath the summary and attach them to the abort path.
- **ABORT signal extension.** The `ABORT` record's `message_data` (`req-boot-abort-signal`) gains the failing step key and the failing checks (structured, not prose), so a watcher or AI consumer gets the cause without log archaeology. The *rendered* `TAP-ABORT:` console line stays one line (it is a grep target — `req-boot-abort-signal-3`); the detail rides the structured record and the boot record (`req-boot-obs-record`).
- **Why it matters, concretely:** `status=401 Bad credentials` (revoked/expired token — fix: re-mint) vs a connect timeout (network/egress — fix: connectivity) vs `404` on one repo (moved/renamed target — fix: the secret's `repos` list) are three different repairs behind the same summary line. The check detail is what picks between them without a manual reproduce.
- **Redaction.** Check messages must remain secret-free (`req-boot-report-2`, `req-boot-secrets`): the self-test contract already truncates provider bodies; nothing in the abort path may echo secret material or full credentials. Truncation bounds stay in the collector contract.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-obs-abort-detail-1 | Checks In Output | Implemented | A failing collector step prints its failing self-test checks (id, status, message) beneath the summary in boot output. | |
| req-boot-obs-abort-detail-2 | Checks In Signal | Implemented | The ABORT `message_data` carries the failing step key + structured failing checks; the rendered `TAP-ABORT:` line stays a one-liner. | |
| req-boot-obs-abort-detail-3 | Secret-Free | Implemented | Surfaced check detail contains no secret material; truncation is inherited from the collector contract. | |

---

### Durable Boot Record
----
RID: `req-boot-obs-record`
Status: `Implemented`

> **Built 2026-08-09.** `tap_boot/record.py` (`BootRecord` / `NullBootRecord` / `maybe_boot_record`), schema at `tap_boot/schemas/boot-record.schema.json`, written to `logs/boot/<run_id>.boot-record.json` + `latest.boot-record.json`. The test runner's boots are record-free via the `TAP_TEST_MODE` carve; a record-write failure disables the record, never the boot. Covered by `tap_boot/tests/test_record.py` (records validate against the schema on both the success and abort paths).

Every `manage.py boot` run writes a machine-legible record of what happened — on success *and* on abort. The record, not terminal scrollback, is the post-hoc evidence: the diagnose skill, the spawn presenter, and Player-3 AI assistants read it instead of re-running boot.

#### Implementation

- **Content.** One JSON document per run: run id (uuid7), grid id, profile id, timestamps/durations; the resolved boot variables with **effective value + provenance** (the home `req-boot-variable-resolution-3` promised); each phase and population step in order with outcome (`ok` / `failed` / `skipped`), duration, and — for collector steps — the `CollectionJob` id, summary, and (on failure) the failing checks (`req-boot-obs-abort-detail`); on abort, the ABORT domain + reason. Secret values never appear (`req-boot-report-2`).
- **Home (v0): a file, not the grid.** Written under the instance's visible runtime-log dir (`logs/boot/`, gitignored; worktree-visible in dev via the repo mount, beside the spawn transcript at `logs/spawn.log` so all standup evidence shares one findable home): a per-run file plus a stable `latest` pointer. Written **incrementally at phase/step boundaries** (atomic replace), so a killed or aborted boot still leaves the record up to its last completed step — the record must exist precisely when things went wrong. The grid-node/queryable representation stays the long-horizon backlog it already is in `spec-tap-boot-v0.md`; a file is the honest v0 and is already AI-legible.
- **Schema.** The record ships a documented JSON Schema per `specs/spec-tap-json-files.md` — descriptions at the top level and on every field, named consumer: the diagnose skill + integrated AI assistants (`specs/spec-ai-integration.md`).
- **Relationship to logging.** Logs remain the narrative (`req-boot-report`); the record is the *outcome summary* — small, stable, parseable. Neither replaces the other.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-obs-record-1 | Written Every Run | Implemented | Success and abort both leave a record; an abort's record ends at the failing step with the ABORT domain + reason. | |
| req-boot-obs-record-2 | Abort-Safe Incremental Write | Implemented | The record is updated at phase/step boundaries via atomic replace; a killed boot leaves the record through its last completed boundary. | |
| req-boot-obs-record-3 | Variables With Provenance | Implemented | Resolved boot variables appear with effective value + source (flag/env/profile/default). | Realizes the report half of `req-boot-variable-resolution-3` |
| req-boot-obs-record-4 | Described Schema | Implemented | The record's JSON Schema exists with per-field descriptions (`spec-tap-json-files.md`); the diagnose skill is a named consumer. | |
| req-boot-obs-record-5 | Secret-Free | Implemented | The record contains secret references and provenance only, never values. | |

#### Future

- Grid-node boot-report (queryable via Gryphon, visible in administrivia) — the existing long-horizon backlog item; the file record's schema should be designed so the grid representation is a projection of it, not a second shape.
- `scripts/despawn-session.sh` could archive the final record alongside the teardown, preserving standup history per session.

---

### Spawn Presents, The Log Retains
----
RID: `req-boot-obs-spawn-presentation`
Status: `Implemented`

`scripts/spawn-session.sh` shows the human a clean, per-step status list — one informative line per step with outcome and duration — while the full output of the noisy steps is captured to a session log file. Nothing is lost; it just stops being the *presentation*.

#### Implementation

- **Captured transcript.** A per-spawn log at `$WORKTREE/logs/spawn.log` (`logs/` is the visible, gitignored runtime-log home — deliberately not a dotfile: evidence should be findable, not hidden), initialized once the worktree exists. The noisy steps append their full output there: the image pull / fallback build + container start (Step 4), the bootloader run (Step 6), and the health-gate JSON (Step 6.5). The container's own log (`scripts/dc logs web`) is unchanged and remains the entrypoint-side evidence.
- **Per-step presentation.** Quiet-by-default: long-running captured steps render as `<label> ... ok (Ns)` with a live elapsed counter while running; failures render `FAILED (Ns)` plus the last lines of the captured log and the log path. The bootloader step streams boot's own **section/step status lines** live (`Boot starting`, `Auth phase:`, `[seed-plugin] … OK`, `[fire-collector] … FAILED`, `Boot complete.`) and captures the rest — the operator watches population progress without the migration/warning firehose.
- **Fast-fail preserved.** The `TAP-ABORT` fast-fail and reason surfacing (`req-boot-abort-signal-3/-4`) are untouched: quiet capture never swallows the abort reason — on failure the reason, the failing step's `FAILED —` line, and the log path are printed.
- **Escape hatch.** `TAP_SPAWN_VERBOSE=1` restores full streaming for every captured step (debugging the capture machinery itself, or CI archaeology).
- **Boundary.** This requirement owns output presentation only; spawn's flow/steps/registry semantics remain `req-dev-multisession-spawn-script` (`spec-dev-multisession.md`). When the boot record (`req-boot-obs-record`) lands, the presenter's failure output should cite the record path alongside `logs/spawn.log`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-obs-spawn-presentation-1 | Quiet Capture | Implemented | Image pull/build + start, boot, and health-gate output append to `$WORKTREE/logs/spawn.log`; the terminal shows per-step status lines with durations. | |
| req-boot-obs-spawn-presentation-2 | Boot Sections Streamed | Implemented | The boot step streams boot's section/step status lines live while capturing the full output. | |
| req-boot-obs-spawn-presentation-3 | Failure Shows Evidence | Implemented | A failing captured step prints the abort reason / failing lines and the `logs/spawn.log` path; the ABORT fast-fail semantics are unchanged. | |
| req-boot-obs-spawn-presentation-4 | Verbose Escape Hatch | Implemented | `TAP_SPAWN_VERBOSE=1` restores full streaming. | |

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed | Requirement has been designed but not yet accepted for implementation. |
| Approved for Development | Requirement is accepted and ready to be implemented. |
| In Development | Actively being worked on. |
| Implemented | Has been written. |
| Verified | Has met the acceptance criteria. |
| Refactoring | In the process of being re-worked. |
| Deprecating | In the process of being deprecated. |
| Deprecated | No longer part of the current architecture. |
