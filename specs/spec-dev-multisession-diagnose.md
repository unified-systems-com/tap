# Multi-Session Dev Environment — Spawn-Failure Diagnosis

## Philosophy

A spawn (`scripts/spawn-session.sh`) — and the `scripts/gate-lean` throwaway that drives the same standup — stands an instance up through a fixed ordered sequence: build → pre-boot (install + gates + snapshot) → migrate → `manage.py boot` (auth + population) → health gate. When it fails, the failure is almost always at a **specific step**, and the web container's logs name it. Yet the read of that sequence has been done **by hand, dozens of times**, re-derived from scratch each occurrence.

The spawn script already prints *recovery* commands on failure (`req-dev-multisession-spawn-script-4` — the failure trap: "here is how to nuke the partial state"). What it does **not** do is say **why** it failed. That gap is the diagnosis, and this spec standardizes it as a single, repeatable, self-evolving procedure — implemented by the `/diagnose-failed-session-spawn` skill (`tap_boot/skills/`) — so a red spawn produces a **verdict** (failing step → root cause → the log line that proves it → the fix), not another manual excavation.

It is deliberately a **living** procedure. Each real failure either matches a known signature (fast) or teaches a new one; the procedure's last act is to fold what it learned back into itself, so the catalog of failure→cause signatures compounds instead of freezing at its first draft.

This composes with two neighbours rather than duplicating them: the spawn **failure trap** (`req-dev-multisession-spawn-script-4`, the recovery half) and the **lean-boot independence gate** (`req-dev-validation-lean-boot` in [spec-dev-validation.md](spec-dev-validation.md)), whose "diagnose before nuke" capture (`*-diag.log`) is exactly the evidence this procedure reads when the throwaway is already gone.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Standardize The Read | One ordered procedure over the spawn sequence, not a per-incident re-derivation. |
| 2. | Name The Root Cause | A verdict: failing step, root cause, the proof line, the fix — never "it broke somewhere". |
| 3. | Catalog Signatures | A maintained set of failure→root-cause signatures covering the common classes (import leakage, pre-boot gate abort, migration drift, boot abort, health red, infra). |
| 4. | Diagnose The Vanished | Work from captured diagnostics (`gate-lean`'s `*-diag.log`) when the failed stack has already been torn down. |
| 5. | Self-Evolving | The procedure updates itself when it meets a new failure class or a weak evidence step. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-dev-multisession-diagnose-target | [Target Resolution](#target-resolution) | Implemented | Resolve the failed spawn's compose project / worktree / diag log |
| req-dev-multisession-diagnose-ordered-read | [Ordered Step Read](#ordered-step-read) | Implemented | Map container state to the failing spawn step (build / entrypoint / boot / health) |
| req-dev-multisession-diagnose-signatures | [Failure Signature Catalog](#failure-signature-catalog) | Implemented | Maintained failure→root-cause signatures for the common classes |
| req-dev-multisession-diagnose-verdict | [Verdict](#verdict) | Implemented | Output = failing step + root cause + proof line + fix + nuke-or-not |
| req-dev-multisession-diagnose-self-evolving | [Self-Evolving Procedure](#self-evolving-procedure) | Implemented | The skill amends itself each run on a new class / weak evidence step |
| req-dev-multisession-diagnose-composition | [Composition](#composition) | Implemented | Composes with the spawn failure trap + the lean-boot gate's diagnose-before-nuke |
| req-dev-multisession-fix-spawn | [Proactive Session Repair](#proactive-session-repair) | Backlog | A `/fix-spawn-session` skill that acts on the verdict to bring a broken session back to life |

The procedure is implemented as a skill, not code; its "acceptance" is that a diagnostician (agent or developer) following it top-to-bottom reaches a correct verdict. The skill is the authoritative procedure — this spec states *what it must establish*, the SKILL.md states *how*.

---

### Target Resolution
----
RID: `req-dev-multisession-diagnose-target`

Status: `Implemented`

Given a session name, a compose project (`tap_<name>`), or a `gate-lean` `*-diag.log` path, the procedure resolves the failed spawn's containers and worktree. It accounts for the **append-on-success registry** (`req-dev-multisession-port-registry`): a failed spawn leaves **no** registry row, so a container present but absent from `~/tap-sessions/.registry` is itself a partial-spawn signal. A `gate-lean` throwaway lives under `WORKTREE_BASE` (system tmp), not `~/tap-sessions`.

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-dev-multisession-diagnose-target-1 | Resolve from any handle | Implemented | The procedure locates the stack from a name, a `tap_<name>` project, or a diag-log path. |
| req-dev-multisession-diagnose-target-2 | Partial-spawn awareness | Implemented | A container with no registry row is read as a partial spawn, not an inconsistency to be dismissed. |

### Ordered Step Read
----
RID: `req-dev-multisession-diagnose-ordered-read`

Status: `Implemented`

The procedure reads the **structured evidence first**: the boot record at `<worktree>/logs/boot/latest.boot-record.json` (`req-boot-obs-record` — phases, per-step status/durations, boot-variable provenance, and on abort the failing step + failing self-test checks; a stale `"outcome": "running"` means the boot process was killed) and the captured spawn transcript at `<worktree>/logs/spawn.log` (`req-boot-obs-spawn-presentation`). Then container state (`compose ps`, `logs web`, `logs db`), mapping the last successful line to the failing spawn step. The failure-prone steps, in order: **pull/build & start** (image pull or fallback build; port collision), **entrypoint** (wheel-cache seed → uv sync → pre-boot → migrate → runserver — where most real failures land), **`manage.py boot`** (auth → collector preflight → population), **health gate** (`manage.py health --set readiness --json`).

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-dev-multisession-diagnose-ordered-read-1 | Step localization | Implemented | The failing step is identified from the container logs, not guessed. |
| req-dev-multisession-diagnose-ordered-read-2 | Both containers read | Implemented | `web` and `db` logs are both consulted (a `db`-unhealthy cause hides in `logs db`). |
| req-dev-multisession-diagnose-ordered-read-3 | Record-first evidence | Implemented | When a boot record / spawn transcript exists, the procedure reads it before re-running anything; "re-run boot to reproduce" is the fallback for runs that predate the record. |

### Failure Signature Catalog
----
RID: `req-dev-multisession-diagnose-signatures`

Status: `Implemented`

A maintained catalog of failure→root-cause signatures, ordered most-common-first, covering at least: **backstop timeout on a healthy, still-progressing container** (slow cold-cache first boot, not a fault — do not nuke), **import leakage** (`ModuleNotFoundError` from a core module reaching a plugin-only dependency in a lean profile — the `req-dev-validation-lean-boot` class), **pre-boot gate abort** (identity/reconcile/dependency/coherence mismatch), **migration drift/failure**, **boot population abort** (unknown plugin/collector/bundle, bad GRIFT), **fire-collector external-credential failure** (auth-shaped collector summary with a clean container log; the persisted self-test checks split credential-dead from target-moved, and `~/tap-secrets` being shared host state means the breakage — and the fix — spans every session), **health red** (cache table, secret absent, backend down), and **infra** (port collision, unhealthy `db`, stale volume). Each signature names its proof line and its fix.

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-dev-multisession-diagnose-signatures-1 | Common classes covered | Implemented | The catalog covers the import-leakage, pre-boot-gate, migration, boot, health, and infra classes. |
| req-dev-multisession-diagnose-signatures-2 | Proof + fix per signature | Implemented | Each signature states the load-bearing log line and the corrective action, not just a label. |

### Verdict
----
RID: `req-dev-multisession-diagnose-verdict`

Status: `Implemented`

The procedure's output is a verdict, stated plainly: the **failing step**, the **root cause**, the **one log line** that proves it, the **fix**, and **whether the session should be nuked** (respecting despawn's hard-stop on a session carrying unpushed commits — report that rather than forcing).

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-dev-multisession-diagnose-verdict-1 | Structured verdict | Implemented | Every diagnosis ends with step + cause + proof + fix + nuke-or-not, not a narrative. |
| req-dev-multisession-diagnose-verdict-2 | Respect the teardown hard-stop | Implemented | A session with unpushed commits is reported, not force-nuked (`spec-dev-multisession-teardown.md`). |

### Self-Evolving Procedure
----
RID: `req-dev-multisession-diagnose-self-evolving`

Status: `Implemented`

The procedure's final step is reflection: if the failure was a **new** class, add its signature; if an evidence command came up short, sharpen it; if the target was hard to resolve, improve resolution. The edit is made to the SKILL.md in the same session, so the catalog compounds.

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-dev-multisession-diagnose-self-evolving-1 | Reflect every run | Implemented | The skill's last step evaluates whether it should be amended and, if so, amends itself. |
| req-dev-multisession-diagnose-self-evolving-2 | Change is surfaced | Implemented | Any self-amendment is noted in the run's summary so the evolution is reviewable. |

### Composition
----
RID: `req-dev-multisession-diagnose-composition`

Status: `Implemented`

The procedure is the **why** that complements two existing surfaces: the spawn **failure trap** (`req-dev-multisession-spawn-script-4`) supplies the recovery commands (the *what to do*), and the **lean-boot independence gate** (`req-dev-validation-lean-boot`) captures a `*-diag.log` before nuking its throwaway (the *evidence after the stack is gone*). Diagnosis reads that evidence and produces the verdict; it does not re-implement teardown or the gate.

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-dev-multisession-diagnose-composition-1 | Reads gate-lean diagnostics | Implemented | When invoked on a `gate-lean` RED, the procedure diagnoses from the captured `*-diag.log` (the live stack is already nuked). |
| req-dev-multisession-diagnose-composition-2 | No duplication | Implemented | The procedure does not re-implement teardown (`despawn-session.sh`) or the gate; it consumes their outputs. |

### Proactive Session Repair
----
RID: `req-dev-multisession-fix-spawn`

Status: `Backlog`

Diagnosis (above) produces a **verdict**; repair acts on it. A `/fix-spawn-session` skill takes a diagnosed failure and **proactively attempts to bring the broken session back to life** rather than only reporting + nuking — the remediation counterpart to `/diagnose-failed-session-spawn`, strictly downstream of its verdict (diagnose first, then fix).

The intent is to recover the *common, safe, idempotent* cases without a full despawn/respawn: e.g. re-provision a missing cache table and re-run the health gate; re-run `migrate` after a transient DB hiccup; re-run `manage.py boot` population after a fixed profile/GRIFT; rebuild with `--purge-image` on a poisoned image cache; free a colliding port. It is **bounded** — it only applies recoveries that are safe and idempotent, and **escalates rather than guesses** on ambiguous state (a code-level import leak, a real migration conflict, unpushed work) where the right action is a human fix or a clean respawn, never a blind retry loop. It never destroys uncommitted work (it honours the same teardown hard-stop as despawn).

Sequenced **behind** the fast-fail ABORT signal (`req-boot-abort-signal`, spec-tap-boot-v0.md): repair is far more tractable once a fatal standup failure is a clean, categorized signal rather than a readiness-timeout black box.

#### Acceptance Criteria (Backlog — shape, not yet built)

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-dev-multisession-fix-spawn-1 | Verdict-driven | Backlog | Repair consumes a diagnosis verdict; it never acts without first localizing the failing step + root cause. |
| req-dev-multisession-fix-spawn-2 | Safe + idempotent only | Backlog | Only known-safe, idempotent recoveries are auto-applied; re-running one changes nothing when already healthy. |
| req-dev-multisession-fix-spawn-3 | Escalate on ambiguity | Backlog | Ambiguous / code-level / unpushed-work states are escalated for a human fix or clean respawn, not retried blindly. |
| req-dev-multisession-fix-spawn-4 | Re-verify after repair | Backlog | A repair is only declared successful when the health gate (and, for a gate context, a re-boot) passes afterward. |

---

## Out Of Scope

- **Automated remediation in *this* procedure.** Diagnosis diagnoses and recommends; it does not auto-apply fixes. Proactive repair is a **separate** skill, tracked as `req-dev-multisession-fix-spawn` (Backlog, above), strictly downstream of the verdict.
- **Live-crash fast-fail in the spawn.** That a fatal standup failure currently surfaces via the spawn's readiness timeout (`WAIT_TIMEOUT`) rather than an immediate abort is tracked as `req-boot-abort-signal` (spec-tap-boot-v0.md — the standard `TAP-ABORT:` sentinel the spawn tails and fast-fails on). Not this spec's concern — diagnosis reads whatever the spawn produced.
