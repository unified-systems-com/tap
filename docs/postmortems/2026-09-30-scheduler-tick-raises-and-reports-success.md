---
id: pm-2026-09-30-scheduler-tick-raises-and-reports-success
date: 2026-09-30
title: The scheduler raised on every tick and the task framework recorded SUCCESSFUL
status: open
severity: medium
tags:
  - application-bug
  - runtime-issue
  - silent-failure
  - dev-tooling
failure_class: >
  A periodic task catches its own fatal error, logs it, and returns normally — so
  the task framework records a SUCCESS. The subsystem is completely dead and every
  observable signal above the log line says it is healthy. Nothing degrades
  visibly, nothing goes red, and the only trace is a stack trace in a container
  log that is thrown away unless some unrelated thing fails.
surfaces:
  - tap_cares/task_backend.py
  - tap_auth/actors.py
  - tap_auth/sync.py
  - tap_boot/orchestrator.py
  - .github/workflows/core-ci.yml
fix_commits: []
---

# The scheduler raised on every tick and the task framework recorded SUCCESSFUL

## 1. What was observed

While investigating why `product-lines` was red on `main` (a separate matter — two
test-lane failures, written up as the AAR named in §8),
the CI web container's dumped log carried this **once every sixty seconds**:

```
ERROR tap_cares.task_backend … [5985] scheduler_tick: evaluate_tick raised
Traceback (most recent call last):
  File "/app/tap_cares/task_backend.py", line 55, in scheduler_tick
    with acting_as(get_builtin_actor(SCHEDULER)):
  File "/app/tap_auth/actors.py", line 63, in get_builtin_actor
    raise MissingActor(
tap_auth.errors.MissingActor: built-in actor 'tap_cares.scheduler' not found or
  inactive — run auth sync (manage.py sync_auth) before system-initiated work
```

And then, **on the very next line**:

```
INFO django.tasks … Task id=1 path=tap_cares.task_backend.scheduler_tick state=SUCCESSFUL
```

Every tick from 15:01 to 15:09 raised. Every one was recorded as a success. The
scheduler fired nothing for the lifetime of that container and no signal above the
log said so.

## 2. The reporting defect — fully established

`tap_cares/task_backend.py:54-59`:

```python
try:
    with acting_as(get_builtin_actor(SCHEDULER)):
        fires = evaluate_tick()
except Exception:  # noqa: BLE001
    logger.exception("[5985] scheduler_tick: evaluate_tick raised")
    return
```

The bare `except` + `return` is the whole defect. It converts *every* failure —
including "this task cannot run at all" — into a normal return, which the task
framework can only read as success. The `# noqa: BLE001` shows the broad catch was
deliberate; what was not considered is that swallowing it also **lies to the
layer above**.

This half is environment-independent. Whatever the underlying cause, on any
instance where `scheduler_tick` cannot resolve its actor, the scheduler is dead and
the system reports itself healthy.

**Note the asymmetry with the error's own text.** The message is good: it names the
actor, says it is absent-or-inactive, and names the remedy (`manage.py sync_auth`).
A log that helpful being invisible is what makes this a reporting defect rather
than a diagnosis one.

## 3. What is ruled out, with mechanisms

The working hypothesis at the start was reaper work (`tap#471`, the stale-`RUNNING`
`CollectionJob` reconciler). It is not that:

| Hypothesis | Ruled out because |
| --- | --- |
| The reaper deactivated or deleted the actor | `tap_cares/services/reaper.py` only ever writes `CollectionJob` rows. It *reads* built-in actors exactly as the tick does, via `get_builtin_actor(COLLECTOR)`. |
| The reaper is implicated on this path at all | The traceback dies at `task_backend.py:55` resolving `SCHEDULER`, **before** `evaluate_tick` is called. The reaper lives downstream and is never reached. |
| The actor exists but is deactivated (the "zombie built-in" `get_builtin_actor`'s docstring warns about) | `get_builtin_actor` fails on absent **or** not-active, where active is `is_active AND deactivated_at IS NULL`. Nothing in the tree writes `deactivated_at` outside the model definition and two read-side filters. The actor is **absent**, not disabled. |
| A change in the 09-28→09-29 window introduced it | `acting_as(get_builtin_actor(SCHEDULER))` arrived in `e5c24a8e`, 2026-07-03, and is an ancestor of the last green run's head. Nothing in the window touches `tap_cares` or `tap_auth`. |
| It is a defect in the code generally | It does not reproduce on a normal dev stack: zero occurrences in this session's running instance, where `tap_cares.scheduler` is present with `is_active=True` and `deactivated_at=None`. |

## 4. What is NOT established

**Why the actor is absent in the `core_ci` CI lane.** Stated plainly rather than
guessed at, because a postmortem that invents a root cause is worse than one that
names its gap.

What is known: `sync_auth()` → `sync_builtin_actors()` mints `ACTOR_SCHEDULER`
**unconditionally** (`tap_auth/sync.py:286-296`), and boot's `_phase_auth` calls
`sync_auth()` unconditionally (`tap_boot/orchestrator.py:270-274`). The lane's
"Boot the core_ci profile" step reported success. So on the face of it the actor
should exist — and the ticks kept failing for eight straight minutes, which rules
out a simple race where a later tick would have recovered.

Two candidate mechanisms, neither tested:

1. **The readiness probe is satisfied before the auth phase has run.** The lane
   polls `manage.py health --set readiness` rather than the container's own health,
   so "web healthy" may not imply "boot complete".
2. **The worker reads a different database than the one boot synced.** The lane
   builds a `tap_test_template` and worker DBs clone it; if the long-running
   worker resolves settings differently from the boot process, it would look in a
   database where no actor was ever minted.

Why I stopped: the container log is dumped **only on failure** (`core-ci.yml`, step
"Dump web logs on failure"), and that dump is the last 200 lines, so the boot
output had already scrolled off. Green runs retain no container log at all. There
is no retained artifact that can settle it.

**The probe that would settle it, in one dispatch:** run `core-ci` on a branch that
(a) dumps the web log unconditionally rather than on failure, and (b) adds one step
running `manage.py shell -c` to print the built-in actors and `settings.DATABASES`
from inside the web container after boot. That distinguishes candidate 1 from
candidate 2 directly and costs one lane run.

## 5. Impact

- **CI only, as far as is known.** The scheduler fires nothing during a `core_ci`
  lane run. Nothing in the lane depends on a scheduled fire, which is precisely why
  this went unnoticed.
- **Unknown duration.** The line dates to July. This may have been true of every CI
  boot for three months.
- **No production impact established, and none ruled out.** A real instance whose
  boot did not mint the actor would have a silently dead scheduler: no collections
  fire, no schedule runs, and the task framework reports success every minute.
- **One investigative error of mine**, recorded because it is part of how this was
  nearly mis-filed: I first reported the error as *new*, on the grounds that
  `evaluate_tick` appears zero times in the last green run's log. That inference
  was invalid — the green log contains zero container lines at all, because the
  dump is failure-only, so its silence proved nothing. I had even "checked the log
  was retrievable" and found six `scheduler_tick` hits; those were test names. I
  verified the log existed, not that it could ever have contained what I was
  looking for.

## 6. Corrective / Preventive Actions

- [ ] **`scheduler_tick` must not report success when it did nothing.** Re-raise, or
      mark the task failed, or at minimum distinguish "no fires" from "could not
      run". A caught fatal error that returns normally is indistinguishable from a
      healthy idle tick.
- [ ] **Resolve the actor absence** via the dispatch probe in §4. Owner should be
      someone with `tap_cares` context, who can tell a CI boot-ordering artifact
      from a live defect.
- [ ] **Make the signal survivable.** A failure visible only in a container log that
      is discarded unless something else fails is not observable. Either dump the
      web log unconditionally in CI, or surface repeated tick failures somewhere a
      lane can assert on.
- [ ] **Consider a health check that asserts the built-in actors resolve.** `manage.py
      health` is already the lane's readiness probe; a missing program actor is
      exactly the class of thing it could refuse on, which would have turned three
      silent months into a red boot.

## 7. What Paladin would need

**Detection signal (available today, unused):** a task whose terminal state is
`SUCCESSFUL` while an `ERROR`-level log line was emitted from inside the same task
execution, correlated by task id. That pairing — success recorded, exception logged,
same execution — is a generic silent-failure detector and is not specific to the
scheduler. Secondary signal: `scheduler_tick` recorded successful N times in a row
with zero fires produced, where the instance has enabled schedules.

**Safe remediation:** `MissingActor` names its own remedy, and `sync_auth()` is
idempotent and declarative — `sync_builtin_actors()` is a `get_or_create` plus a
repair of drifted managed fields. So running auth sync is a safe automated action
for this signal. Paladin should run it, then confirm the next tick resolves the
actor, and **escalate rather than retry** if the actor is still absent afterwards,
because at that point the cause is configuration or database routing rather than a
missing row.

**What Paladin must not do:** conclude health from the task state. That is the
defect, not the diagnostic.

## 8. Cross-links

- `docs/aar/2026-09-29-absent-is-not-failed.md` — the process AAR from the same
  investigation. **Deliberately named and not linked: that file is on an unmerged
  branch at the time of writing, and a link that resolves only after another branch
  lands is a claim about the future.** Make it a link when both are on `main`. Its root cause 3 is "absent and
  failed were conflated at three independent layers"; this incident is the same
  shape a layer down, in the running system rather than in the tooling, which is
  why it is filed here and not there.
- `tap#471` — the reaper work, examined and exonerated in §3.
