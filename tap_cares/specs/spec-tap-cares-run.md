# tap-cares Run Convention Specification

## Philosophy

A run is one execution of something that writes to the grid: a scanner pass, an evaluation, a collection, an emission. Every plugin that does this has needed the same few things: a node that says the run happened, a way to find what the run made, a final state that tells the truth even when the worker died, and somebody other than the dead worker to say so. This spec is the one shape for that, so plugins stop inventing their own.

The convention is deliberately thin. It records what happened and closes what was left open. It does not stage writes, hold results back until a run finishes, or decide for a reader which run is "current". A run that wrote half its results and then died has written half its results, and the grid shows them at once; the run node says the run was `abandoned`, and each plugin decides what its readers make of that.

Plugins declare their **own** run node types. There is no single generic run model, because a run's information (what it scanned, how many of which kind it found, which algorithm it ran) is house-specific. What is shared is the shape: a model mixin and a helper that live in `tap_cares`. They do not live under the `tap_plugin` namespace, which is the namespace the boot conformance gate checks as plugin code (`req-tap-plugin-arch-identity` in `tap_plugins/specs/spec-tap-plugin-architecture.md`).

The tap-best-practices skill carries the short form of this rule ("Runs: a run node, plus a `run_id` field on what the run mints"). This spec is the canon behind it.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | One Shape     | Every run node type carries the same lifecycle fields and states, through one mixin and one helper |
| 2. | Findable Results | Every node a run creates names that run by a plain, indexed id, with no super-node of edges |
| 3. | Truthful End  | A run ends `complete`, `failed` or `abandoned`, and that state, once written, does not change |
| 4. | Someone Closes It | A run its own process could not close is closed by the existing reaper, from evidence, without new timers |
| 5. | Plugin Decides Meaning | Core records partial runs and does not filter them; each plugin decides what its readers treat as current |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-cares-run-node | [Plugin-Declared Run Nodes](#plugin-declared-run-nodes) | Proposed | Each plugin declares its own run node types on the core mixin; minimal shared fields; trigger, actor and code identity reached through the owner job |
| req-tap-cares-run-lifecycle | [Lifecycle And States](#lifecycle-and-states) | Proposed | Open (UUIDv7) → any number of GRIFT batches → close; `running`, `complete`, `failed`, `abandoned`; terminal is sticky |
| req-tap-cares-run-id | [The `run_id` Stamp](#the-run_id-stamp) | Proposed | Nodes a run creates carry `run_id` in their `NATURAL_KEY`; plain indexed UUID, not a foreign key, dimension or edge; re-observed persistent nodes never carry it |
| req-tap-cares-run-partial | [Partial Runs Are Visible](#partial-runs-are-visible) | Proposed | No write-ahead log, staging or core completeness gate; reader policy is the plugin's; `latest_complete_runs` offered, not mandated |
| req-tap-cares-run-helper | [The `open_run` Helper](#the-open_run-helper) | Proposed | Context manager that mints, opens, stamps, counts, classifies and conditionally closes, and registers the type for mop-up |
| req-tap-cares-run-graceful-close | [Close In `finally`, Best-Effort](#close-in-finally-best-effort) | Proposed | The run closes itself on the way out when it can; the steady_queue limitation is named; the reaper is the guarantee |
| req-tap-cares-run-mopup | [Mop-Up By The Reaper](#mop-up-by-the-reaper) | Proposed | Extends `req-tap-cares-collector-job-reaper`: a `running` run whose owner job is terminal or dead is closed `abandoned`, at the scheduler tick and at the next open of its type; no new numbers |
| req-tap-cares-run-abort-cleanup | [Abort Clean-Up Hook](#abort-clean-up-hook) | Proposed | Optional `on_abort(run)` on collectors and emitters, enqueued as its own task when the reaper abandons a run; idempotent, outcome recorded, not retried |
| req-tap-cares-run-overlap | [Overlap Per Run Type](#overlap-per-run-type) | Proposed | Allowed by default; a type may refuse overlap with a transaction-scoped advisory lock at open |
| req-tap-cares-run-backlog | [Deferred Run Work](#deferred-run-work) | Backlog | Cooperative stop signal, retention of failed and abandoned runs, `CollectionJob` adopting the convention |

## Plugin-Declared Run Nodes
----
RID: `req-tap-cares-run-node`

Status: `Proposed`

A plugin declares each of its run node types as an ordinary `BaseModel` (via `add-model`) that also inherits `tap_cares.runs.RunMixin`. The mixin contributes the shared fields below; the plugin adds whatever its run needs to say beyond them. A run node is minted per run, so its type is `KEYLESS` with the reason "a run: an act of this grid" (`req-grid-entity-natural-key-5`), and its id is a UUIDv7 minted at open (`req-tap-cares-run-lifecycle`).

| Field | Type | Meaning |
| --- | --- | --- |
| `status` | short text | `running`, `complete`, `failed` or `abandoned` (`req-tap-cares-run-lifecycle`) |
| `started_at` | datetime | Written at open |
| `finished_at` | datetime, nullable | Written by the close, whoever makes it |
| `owner_job_id` | UUID, indexed | The entity id of the tap_cares job executing this run: a `CollectionJob` or an `EmissionJob`. A plain id like core's batch pointers, not a foreign key and not an edge |
| `closed_by` | short text, nullable | `run` when the run's own code closed it, `mop_up` when the reaper did |
| `failure_kind` | short text, nullable | An open list. Core uses `error`, `invalid_output`, `abandoned`, `cancelled` and `deadline_exceeded`; a plugin may add its own values and documents them in its spec |
| `failure` | text, nullable | What went wrong, passed through the secrets redaction (`req-tap-cares-secrets-redaction`) before it is stored. No length cap |
| `results_written` | integer | Nodes this run created and stamped with its `run_id`, counted by the helper |
| `cleanup_status` | short text, nullable | `enqueued`, `succeeded` or `failed` once an abort clean-up is involved (`req-tap-cares-run-abort-cleanup`); empty otherwise |
| `cleanup_failure` | text, nullable | The redacted failure of a clean-up that failed. No length cap |

A plugin declares further counts as its own integer fields and names them in the run type's `RUN_COUNTS` tuple; the helper increments them on request and writes them at close.

**What the run node does not copy.** Who or what started the run (the schedule fire, the manual operator, the actor) and which code ran (plugin slug, release, commit, source hash, the capability's authored version) are already on the owner job: a `CollectionJob` carries `req-tap-cares-collector-version`'s fields, and an `EmissionJob` carries the same set (`req-tap-cares-v0-emitter`). A run node reaches them through `owner_job_id` and never holds a second copy that could disagree.

**Owner job.** Every run is executed by exactly one tap_cares job, and the open refuses an `owner_job_id` that does not resolve to an existing `CollectionJob` or `EmissionJob` that is not terminal. An `EmissionJob` is itself a run under this convention as well as a job (`req-tap-cares-v0-emitter`); its `owner_job_id` is its own entity id.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-run-node-1 | Plugin Types On One Mixin | Proposed | A plugin run node type is a `BaseModel` that inherits `RunMixin`, is `KEYLESS` with a stated reason, and carries every field in the table; the mixin lives in `tap_cares`, not under `tap_plugin`. | No generic core run model exists. |
| req-tap-cares-run-node-2 | Owner Job Required And Live | Proposed | Opening a run with an `owner_job_id` that resolves to no `CollectionJob` or `EmissionJob`, or to a terminal one, is refused before any write. | |
| req-tap-cares-run-node-3 | No Copied Provenance | Proposed | The mixin declares no trigger, actor, plugin release, commit, source hash or capability version field; a test reaches each through `owner_job_id`. | One place for each fact. |
| req-tap-cares-run-node-4 | Failure Text Redacted, Uncapped | Proposed | `failure` and `cleanup_failure` pass through the secrets redaction before storage and are stored whole; a test stores a failure longer than any existing summary bound and reads it back unchanged. | |

## Lifecycle And States
----
RID: `req-tap-cares-run-lifecycle`

Status: `Proposed`

A run has three steps:

1. **Open.** Mint the run node with a UUIDv7 entity id, `status = running`, `started_at = now`, and its `owner_job_id`.
2. **Write.** Perform any number of GRIFT batches. Each node the run creates carries its `run_id` (`req-tap-cares-run-id`).
3. **Close.** Update the run node to a terminal state with `finished_at`, `closed_by`, its counts, and on failure its `failure_kind` and `failure`.

The states are `running`, `complete`, `failed` and `abandoned`. `complete` means the run's own code finished without error. `failed` means the run's own code reported or raised a failure. `abandoned` means the run was closed from outside because its own code could no longer close it, or overran a deadline (`req-tap-cares-run-mopup`).

**Terminal is sticky.** The close is a conditional write from `running` only: it re-reads the row under `select_for_update()` inside one transaction and writes only if the status is still `running`, the same lock pattern as `req-tap-cares-collector-job-reaper-6`. A close that finds the row already terminal changes nothing and is logged. This is a deliberate difference from the `CollectionJob` reaper, where the task body's late write lands after a reap and overwrites it: a run closed `abandoned` stays abandoned even if its thread was still alive and later tries to close it `complete`, because the evidence that ended it (a dead owner, an overrun deadline) is itself a fact a reader needs.

Open and close are written under whatever batch scope is bound when they run; for a collector or emitter that is the job's lifecycle batch. The GRIFT batches of step 2 are their own batches, as `req-tap-cares-collector-run-collection-15` already requires for collected data.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-run-lifecycle-1 | UUIDv7 At Open | Proposed | The run node's entity id is a UUIDv7 minted at open, and the node is written with `status = running` before any result batch. | |
| req-tap-cares-run-lifecycle-2 | Four States | Proposed | `status` takes exactly `running`, `complete`, `failed`, `abandoned`; any other value is refused at write. | |
| req-tap-cares-run-lifecycle-3 | Conditional Close | Proposed | A close re-reads the row under a row lock and writes only from `running`; a test closes a run `abandoned`, then attempts a `complete` close and reads `abandoned` back. | Sticky terminal. |
| req-tap-cares-run-lifecycle-4 | Results In Their Own Batches | Proposed | The open and close ride the bound lifecycle scope; each GRIFT batch of results is a separate batch. | |

## The `run_id` Stamp
----
RID: `req-tap-cares-run-id`

Status: `Proposed`

Every node a run **creates** carries a `run_id` field: the run node's entity id, a plain indexed UUID column, written once, and part of that node type's `NATURAL_KEY`. Results are found by `run_id`, never by walking edges.

- It is **not a foreign key**: there are none between typed node tables (`tap_grid/specs/spec-grid-service-delete.md`, "Cascade First"), and like core's batch pointers it is a plain id (`req-grid-entity-batch-pointers`).
- It is **not a dimension**: dimensions gather diverse types from different plugins into one bucket, and a run's output sits in one or a few house tables.
- There are **no edges from a run to its results**: thousands of edges to one run node make a super-node.

**Persistent nodes never carry `run_id`.** A node that many runs re-observe (an asset, a host, a control) is not minted by any one run. Stamping it would either hide earlier runs in history or write a history row every run. Core's `last_observed_batch_id` already says which batch last saw it (`req-grid-history-reobservation`), and "every run that saw X" comes from the per-run nodes keyed on (X, run).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-run-id-1 | In The Natural Key | Proposed | A node type the run mints declares `run_id` as an indexed UUID field included in its `NATURAL_KEY`; the same observation in two runs yields two nodes. | |
| req-tap-cares-run-id-2 | No Run-To-Result Edges | Proposed | The convention declares no edge type from a run node to the nodes it minted, and the helper writes none. | |
| req-tap-cares-run-id-3 | Persistent Nodes Untouched | Proposed | A node type without a `run_id` field is written by the helper unchanged; a re-observed node gains no `run_id` and its observation is recorded by `last_observed_batch_id`. | |

## Partial Runs Are Visible
----
RID: `req-tap-cares-run-partial`

Status: `Proposed`

**Partial runs are acceptable and visible immediately.** Each GRIFT batch a run writes is committed and readable when it commits, whatever happens to the run later. Core builds:

- no write-ahead log and no staging area for run results;
- no core completeness gate that hides results until the run closes;
- no core rule that rows from an `abandoned` or `failed` run are unread or filtered;
- no core rule that turns a count mismatch into `failed`.

What a reader treats as "current" is each plugin's decision, stated in that plugin's spec. Core offers one reader helper, `latest_complete_runs(RunType, partition_by=())`, which returns, for each distinct value of the named fields, the most recent run of that type with `status = complete`. A plugin may use it, write its own policy, or read every run. It is offered, not mandated.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-run-partial-1 | Visible On Commit | Proposed | A node written by a run's first batch is readable through Search while the run is still `running`, and remains readable after the run is closed `abandoned`. | |
| req-tap-cares-run-partial-2 | No Core Filtering | Proposed | No core read path filters rows by the status of the run named in their `run_id`. | |
| req-tap-cares-run-partial-3 | Reader Helper | Proposed | `latest_complete_runs` returns the most recent `complete` run per partition value and ignores `running`, `failed` and `abandoned` runs. | Optional for plugins. |

## The `open_run` Helper
----
RID: `req-tap-cares-run-helper`

Status: `Proposed`

```python
with open_run(RunType, owner_job_id=job_id, **fields) as run:
    run.submit_grift(document)      # stamps run_id on nodes of run-minted types, counts them
    run.add("findings", n)          # a count declared in RunType.RUN_COUNTS
    run.fail("invalid_output", "…") # optional explicit failure before leaving the block
```

`open_run` is a context manager in `tap_cares.runs`. It:

1. registers `RunType` for mop-up (idempotent; the mop-up also enumerates every installed model carrying `RunMixin`, so a type is swept after a restart even before its next open);
2. runs the mop-up for `RunType`'s own `running` rows (`req-tap-cares-run-mopup`) and, for a type that refuses overlap, takes its lock (`req-tap-cares-run-overlap`);
3. validates `owner_job_id` (`req-tap-cares-run-node-2`), mints the UUIDv7 id and writes the open;
4. yields a handle whose `submit_grift` fills `run_id` on every node of a type that declares it, refuses a node of such a type that names a different `run_id`, and adds the created count to `results_written`;
5. on leaving the block, closes the run with the conditional write: `complete` on a normal exit; `failed` when the block raised an `Exception`, with `failure_kind` taken from the exception's `failure_kind` attribute when it has one and `error` otherwise; `cancelled` when it raised a `BaseException` that is not an `Exception`; or the state `run.fail(...)` set. The exception is re-raised after the close.

The helper never swallows the run's exception and never retries. A run that should be retried is a new run.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-run-helper-1 | Open, Stamp, Count, Close | Proposed | A run that submits two batches through the handle ends `complete` with `results_written` equal to the nodes created, each carrying the run's id. | |
| req-tap-cares-run-helper-2 | Exception Classified And Re-Raised | Proposed | An exception in the block closes the run `failed` with the exception's `failure_kind` (or `error`) and redacted text, and propagates unchanged. | |
| req-tap-cares-run-helper-3 | Foreign run_id Refused | Proposed | A node of a run-minted type submitted with another run's `run_id` is refused and nothing in that batch is written. | |
| req-tap-cares-run-helper-4 | Registered For Mop-Up | Proposed | After a process restart, a `running` row of a type with no new open since is still found by the tick's mop-up. | |

## Close In `finally`, Best-Effort
----
RID: `req-tap-cares-run-graceful-close`

Status: `Proposed`

A run closes itself on the way out whenever its process is still able to run code: the helper's exit path is a `finally`, and it classifies the ending with `failure_kind`. That close is best-effort. The reaper is the guarantee (`req-tap-cares-run-mopup`).

**The steady_queue limitation, named.** On `SIGTERM` the steady_queue supervisor waits its own `shutdown_timeout` and then exits; the worker's pool calls `executor.shutdown(wait=False, cancel_futures=True)`, which cancels queued work but never signals a task thread that is already running. A running run is therefore not told to stop, its `finally` does not run when the process exits under it, and it stays `running` until the mop-up finds its owner job dead: through a `FailedExecution` steady_queue records, or through the claiming process's heartbeat going stale past steady_queue's `process_alive_threshold`. TAP adds no shutdown grace period of its own, because no TAP code could use one: the running thread is never told.

A cooperative stop signal that would let a run close itself on shutdown is Backlog (`req-tap-cares-run-backlog`).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-run-graceful-close-1 | Close On The Way Out | Proposed | A block that raises still writes its terminal state before the exception leaves the helper. | |
| req-tap-cares-run-graceful-close-2 | No TAP Grace Period | Proposed | No TAP setting or code path waits on shutdown for a running run; a run killed with its process is closed only by the mop-up. | |

## Mop-Up By The Reaper
----
RID: `req-tap-cares-run-mopup`

Status: `Proposed`

This requirement extends `req-tap-cares-collector-job-reaper` (in `spec-tap-cares-collector.md`) to runs. The reaper's existing rules carry over unchanged: derive from evidence, never guess; lock the row through the re-check and the write; one bad row is logged and skipped and never cancels the sweep or the tick.

**When it runs.** Twice, with no new interval:

- at the scheduler tick, inside the existing reaper call in `evaluate_tick`, after the job sweep and before any schedule's active-run count is read;
- when the next run of a type opens (`req-tap-cares-run-helper`, step 2), for that type's `running` rows only.

**What closes a run.** For each `running` run, in order:

1. Its owner job resolves and is terminal → `abandoned`, `failure_kind = abandoned`, naming the job and its status. This is the cascade: when the reaper reaps a job, the runs it owned are closed in the same tick.
2. The run records a `deadline_at` that has passed → `abandoned`, `failure_kind = deadline_exceeded`. Only run types that declare a deadline record one; an `EmissionJob` always does (`req-tap-cares-v0-emitter`).
3. Its owner job resolves, is not terminal, and the reaper's derive steps find the job dead (a `FailedExecution`, no steady_queue `Job`, a `Job` already finished, a claiming process past `process_alive_threshold`) → the job is reaped as today and the run is closed by step 1. At open time the same derive steps are applied to the owner job, so a run of a dead job does not wait for the next tick.
4. Its owner job does not resolve at all → the reaper's existing flat-age fallback, measured from the run's `started_at`; past it, `abandoned`.
5. Otherwise the run is left alone.

An `EmissionJob`, being its own owner, goes straight to the reaper's derive steps for its own task (step 3 applied to itself), and its deadline (step 2).

**The write.** The abandon is the conditional close of `req-tap-cares-run-lifecycle` with `closed_by = mop_up`, `finished_at = now`, and a `failure` beginning `Abandoned:` naming which step fired. It is written under the program actor of the capability that owns the job, on a batch of its own labelled `Run mop-up`.

**No new numbers.** The mop-up uses the reaper's existing 30-minute flat-age fallback and steady_queue's own `process_alive_threshold`, read from steady_queue as the reaper already does. It adds no interval, no timeout and no threshold. There is no resume: an abandoned run stays abandoned, and a retry is a new run. Abandoned and failed rows are kept; their retention is a later decision (`req-tap-cares-run-backlog`).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-run-mopup-1 | Cascade From A Terminal Job | Proposed | A `running` run whose owner job is `SUCCESSFUL` or `FAILED` (or a terminal `EmissionJob`) is closed `abandoned` by the next tick, `closed_by = mop_up`, with a failure naming the job. | Includes a job the reaper reaped in the same tick. |
| req-tap-cares-run-mopup-2 | Checked At Open | Proposed | Opening a run of a type sweeps that type's `running` rows first, applying the same steps, so a stale run of a dead job is closed before the new one opens. | |
| req-tap-cares-run-mopup-3 | Live Runs Untouched | Proposed | A run whose owner job is claimed by a process heartbeating within `process_alive_threshold`, and whose deadline (if any) has not passed, is left `running`. | |
| req-tap-cares-run-mopup-4 | Deadline Closes The Run | Proposed | A `running` run past its `deadline_at` is closed `abandoned` with `failure_kind = deadline_exceeded`, whether or not its thread is alive. | Core cannot stop the thread. |
| req-tap-cares-run-mopup-5 | Existing Numbers Only | Proposed | The mop-up reads the reaper's existing flat-age constant and steady_queue's `process_alive_threshold`; it declares no constant, setting or recurring task of its own. | `req-tap-cares-collector-job-reaper-1` still forbids a second recurring task. |
| req-tap-cares-run-mopup-6 | Locked, Fail-Soft | Proposed | Each abandon holds a row lock through re-check and write; an exception on one row is logged with its run id and the sweep continues. | Mirrors `req-tap-cares-collector-job-reaper-6` and `-7`. |
| req-tap-cares-run-mopup-7 | No Resume | Proposed | Nothing reopens an `abandoned` or `failed` run; a retry opens a new run with a new id. | |

## Abort Clean-Up Hook
----
RID: `req-tap-cares-run-abort-cleanup`

Status: `Proposed`

A collector or emitter class may supply `on_abort(self, run)`. The default is a no-op. It exists for side effects a run leaves behind that only the plugin understands: a multipart upload to cancel, a lease to release, a half-written remote draft to delete.

**When the reaper fires it.** Only for a run closed from outside (`closed_by = mop_up`). When the mop-up abandons a run whose capability class overrides `on_abort`, it sets `cleanup_status = enqueued` in the same write and enqueues a clean-up task after commit. The clean-up is never run inline in the reaper. For an emitter, the hook fires once for the `EmissionJob`; the emitter's own run nodes that the same act abandons through the cascade do not fire it again, since the job is the outermost run. For a collector, it fires once for each of its run nodes the mop-up abandons.

**What it receives.** The task's payload is the run type and the run's entity id, nothing else. The task loads the persisted run and its owner job, resolves the capability class from the job's `Collector` or `Emitter` node, constructs it with its configuration exactly as a run does (its envelope resolved and validated), and calls `on_abort(run)`. No in-memory state of the dead run is available, by design.

**What it must be.** Idempotent, and safe when the run was actually alive: a deadline abandon closes a run whose thread may still be running. The outcome is recorded on the run: `cleanup_status = succeeded`, or `failed` with the redacted `cleanup_failure`. A failed clean-up is not retried.

**In-process failures are the plugin's.** Plugin code that fails in its own process handles its own clean-up there, and may call its own `on_abort` to do so. The reaper does not fire the hook for a run its own code closed.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-run-abort-cleanup-1 | Enqueued, Never Inline | Proposed | Abandoning a run whose class overrides `on_abort` enqueues one clean-up task after commit, carrying only the run type and id, and sets `cleanup_status = enqueued`; the reaper itself calls no plugin code. | |
| req-tap-cares-run-abort-cleanup-2 | Outside Endings Only | Proposed | A run closed `failed` or `complete` by its own code never gets a clean-up task from the reaper. | |
| req-tap-cares-run-abort-cleanup-3 | Outcome Recorded, Not Retried | Proposed | A clean-up that raises leaves `cleanup_status = failed` with redacted text and is not enqueued again; one that returns leaves `succeeded`. | |
| req-tap-cares-run-abort-cleanup-4 | Persisted Records Only | Proposed | The hook receives the persisted run; the task reconstructs the class from the owner job's capability node and its configuration. | |
| req-tap-cares-run-abort-cleanup-5 | Default No-Op | Proposed | A class that does not override `on_abort` gets no clean-up task and its run's `cleanup_status` stays empty. | |

## Overlap Per Run Type
----
RID: `req-tap-cares-run-overlap`

Status: `Proposed`

Overlap is declared per run type with `ALLOW_OVERLAP`, default `True`: two runs of the same type may be `running` at once. A type that sets it to `False` refuses overlap at open. The open takes a transaction-scoped PostgreSQL advisory lock keyed on the run type, runs the mop-up for that type, and refuses the open (`RunOverlapRefused`) if a `running` row of the type remains; otherwise it writes the open in the same transaction. The lock is released when that transaction ends and is never held for the run's duration.

The advisory lock is PostgreSQL-specific. A future SQLite shape needs its own serialization here (`tap_grid/specs/spec-grid-sqlite-portability-BACKLOG.md`).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-run-overlap-1 | Allowed By Default | Proposed | Two concurrent opens of a type that does not set `ALLOW_OVERLAP = False` both succeed. | |
| req-tap-cares-run-overlap-2 | Refused Under The Lock | Proposed | For a type with `ALLOW_OVERLAP = False`, of two concurrent opens exactly one succeeds and the other raises `RunOverlapRefused`; a stale `running` row of a dead job is mopped up first and does not block the open. | |

## Deferred Run Work
----
RID: `req-tap-cares-run-backlog`

Status: `Backlog`

- **A cooperative stop signal**, so that a running run can be told to close itself on worker shutdown rather than waiting for the mop-up.
- **Retention** of `failed` and `abandoned` runs and their partial results. Until it is decided, every row is kept.
- **`CollectionJob` adopting the convention**, the way `EmissionJob` does. Collectors are not rewritten now; a collector that wants a run node opens one with `open_run` under its `CollectionJob`.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-run-backlog-1 | Deferred Work Named | Backlog | Each item lands as its own requirement when a consumer needs it. | |

## Prior Art

Surveyed from public documentation; no code copied.

- **Prefect** separates `Failed` (the code raised) from `Crashed` (the infrastructure died under it). That split is `failed` versus `abandoned` here, and why `closed_by` records who wrote the ending.
- **OpenLineage** run events end in exactly one terminal event (`COMPLETE`, `FAIL`, `ABORT`), and a run with no terminal event is incomplete, not successful. That is why a run left `running` is mopped up rather than read as done.
- **Airflow** detects "zombie" task instances from missed heartbeats and fails them from the scheduler side, not from the dead worker (zombie detection; apache/airflow PR #6284). The mop-up rides our scheduler tick the same way, and reuses steady_queue's heartbeat rather than adding one.
- **Hadoop's output committer** calls `abortJob` to clean up after a job that will not commit. That is the `on_abort` hook: a plugin-supplied clean-up called by the framework after the fact.
- **Apache Iceberg** warns that removing orphan files can delete the files of a write still in progress if the age threshold is too short. That is why the clean-up must be safe when the run was actually alive.
- **Temporal** keeps the workflow record authoritative and has a separate party time out an activity whose worker stopped heartbeating; retries are new attempts with their own records. Here a retry is a new run, never a resumed one.
