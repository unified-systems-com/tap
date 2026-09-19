"""Django Tasks runtime for tap_cares collectors.

req-tap-cares-collector-task-execution, req-tap-cares-collector-job-sole-writer,
req-tap-cares-collector-failure-mode, req-tap-cares-collector-self-test
(spec-tap-cares-collector.md).

A single task — `run_collector` — runs a `CollectionJob` as two phases:

  - **Phase 1 — self-test.** Always runs (default-on gate,
    req-tap-cares-collector-self-test-10). Calls the
    `self_test_collector(collector)` service entry point and records the
    structured result onto `CollectionJob.self_test`. A non-runnable result
    fails the job via the standard collector failure mode before any
    external work. A `self_test_only` job stops here SUCCESSFUL.
  - **Phase 2 — collect.** Only for a `full`, runnable job: looks up the
    registered collector class, builds a CollectorConfig, instantiates,
    invokes run(), and writes terminal state.

The task body is the sole writer to CollectionJob after row creation. Writes
per run:
  - run_collection writes the row at READY (kickoff)
  - this task body writes RUNNING + started_at (task start)
  - this task body writes the terminal SUCCESSFUL or FAILED state +
    finished_at + summary + results + self_test (task end), and creates one
    `CollectionJob --PRODUCED_BATCH--> Batch` edge per produced batch
    (req-tap-cares-collector-grift-import-6).

All of those writes — plus `run_collection`'s own kickoff writes — ride ONE
batch per run, opened by `run_collection` and threaded here through the task
payload (`req-tap-cares-collector-run-collection-10`). It is sealed on the way
out of the task, and only when the job actually reached a terminal status.

The collector instance accumulates `self.results`, `self._produced_batches`,
and `self.summary` in memory during run(); the task body reads them at
terminal state, persists results/summary/self_test in the terminal patch, and
links each produced batch to the job with a PRODUCED_BATCH edge.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from django.tasks import task

from tap_auth.actors import COLLECTOR, acting_as, get_builtin_actor
from tap_cares.collectors.config import CollectorConfig
from tap_cares.exceptions import CollectorNotReadyError
from tap_cares.models import (
    CollectionJob,
    CollectionJobRunMode,
    CollectionJobStatus,
    Collector,
)
from tap_cares.registry import get_collector
from tap_grid.services import _patch_node_internal

logger = logging.getLogger(__name__)

_SUMMARY_CAP = 2048

_EMPTY_RESULTS: dict[str, list] = {"info": [], "warn": [], "error": []}


def _patch_job(job_entity_id: str, fields: dict[str, Any]) -> None:
    """Patch the CollectionJob row — the sole-writer's single write primitive.

    The `run_collector` task body is the sole writer to CollectionJob after row
    creation (req-tap-cares-collector-job-sole-writer); every one of its terminal
    and transition writes funnels through here. The task body runs under
    `acting_as(get_builtin_actor(COLLECTOR))`, so this inherits the named
    `tap_cares.collector` program actor from the contextvar — a no-request worker
    has no middleware to bind one (req-tap-auth-actor-model). The write backstop
    independently re-checks the bound actor holds `grid.write`.
    """
    _patch_node_internal(  # TAP-AUTHZ-COV: bound tap_cares.collector via acting_as; grid.write re-checked at the write backstop
        job_entity_id,
        fields,
    )


def _link_produced_batches(job: CollectionJob, produced_batches: list[tuple[str, str]]) -> None:
    """Create one CollectionJob --PRODUCED_BATCH--> Batch edge per produced batch.

    req-tap-cares-collector-grift-import-6. Called at terminal state (success
    AND failure) by the run_collector body — the sole CollectionJob writer —
    from the collector instance's `_produced_batches` accumulator, so partial
    progress on a failed run stays visible.

    PRODUCED_BATCH is run<->batch *correlation*; the batches themselves already
    landed on the grid via `grift_import` before this runs. A correlation write
    that fails is therefore logged loudly per-batch and skipped, never crashing
    an already-committed collection.
    """
    if not produced_batches:
        return
    from tap_grid.models import Entity
    from tap_grid.services import create_edge

    for batch_id, disposition in produced_batches:
        try:
            batch_entity = Entity.objects.get(id=batch_id)
            create_edge(
                from_entity=job.entity,
                to_entity=batch_entity,
                edge_type="PRODUCED_BATCH",
                properties={"disposition": disposition},
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "[f381] PRODUCED_BATCH edge creation failed: job %s -> batch %s (disposition=%s)",
                job.entity_id,
                batch_id,
                disposition,
            )


def _safe_summary(exc: BaseException) -> str:
    msg = f"{type(exc).__name__}: {exc}"
    if len(msg) > _SUMMARY_CAP:
        msg = msg[:_SUMMARY_CAP]
    return msg


def _derive_failure_summary(instance: object, exc: BaseException) -> str:
    """Compose the at-a-glance summary for a FAILED terminal patch.

    Precedence:
        1. collector-set instance.summary, if any
        2. count of recorded error events — "Failed with N error(s)"
        3. exception class + message fallback

    A collector that knows what went wrong should set self.summary directly;
    when it doesn't, the count-derived fallback gives operators "how bad was
    it" at a glance, and the structured detail in results["error"] is where
    they dig in. Per req-tap-cares-collector-failure-mode-3.
    """
    explicit = getattr(instance, "summary", "")
    if explicit:
        return explicit[:_SUMMARY_CAP]
    results = getattr(instance, "results", None)
    if isinstance(results, dict):
        errors = results.get("error") or []
        if errors:
            n = len(errors)
            return f"Failed with {n} error{'s' if n != 1 else ''}"
    return _safe_summary(exc)


@task()
def run_collector(
    collector_entity_id: str,
    collection_job_entity_id: str,
    lifecycle_batch_entity_id: str = "",
) -> None:
    """Execute one collector run as the named tap_cares.collector program actor.

    A no-request Django-Tasks worker has no middleware to bind an actor onto the
    `CallerContext`, so the task binds its own named `tap_cares.collector` program
    actor at entry; every downstream service-layer write — the CollectionJob
    transition/terminal patches and the collector's `submit_grift` GRIFT import —
    inherits it from the contextvar (req-tap-auth-actor-model). This boundary is
    what closes the "green in CI, denied in prod" class: CI runs under an ambient
    test actor, a real worker thread has none, and an unbound write fails closed
    at the backstop. The run itself is `_run_collection_job` below.

    The run's own lifecycle writes — the RUNNING transition, the terminal patch,
    the `PRODUCED_BATCH` correlation edges — share the batch `run_collection`
    opened for them (req-tap-cares-collector-run-collection-10). Its id arrives
    in the task payload rather than through a context manager because these
    writes are on the far side of a task boundary from the ones that opened it.
    Binding it via `acting_as(..., batch_id=...)` scopes every ambient write in
    this body to that batch without threading a `CallerContext` through each
    call; the collector's GRIFT import is unaffected — `grift_import` builds its
    own per-batch context and ignores the ambient scope, so imported data stays
    in its own named batch. The batch is sealed on the way out, and only if the
    job actually reached a terminal status (`_seal_lifecycle_batch`).

    Args:
        collector_entity_id: UUIDv7 of the Collector node (as string).
        collection_job_entity_id: UUIDv7 of the CollectionJob node (as string).
        lifecycle_batch_entity_id: UUIDv7 of the batch carrying this run's own
            lifecycle writes (as string). Empty means no lifecycle batch was
            opened — the pre-#473 payload shape, still accepted so a task
            enqueued before this change can drain.

    Note on `takes_context`: this task does NOT use Django Tasks'
    `takes_context=True` mechanism. Steady Queue 0.2.0 doesn't honor that
    flag — its `ClaimedExecution.perform()` calls `task.func(*args, **kwargs)`
    without injecting a `TaskContext`, so a context-taking task fails with
    a "missing positional argument" error when picked up by a steady_queue
    worker. We capture `task_result.id` on the enqueue side instead
    (see `tap_cares.services.run_collection`). Restore `takes_context=True`
    once upstream gains support.
    """
    # Verify the payload's batch id BEFORE it scopes a single write. The seal
    # checks the same binding on the way out, but a check only at the end would
    # refuse to close a foreign batch after this body had already written the
    # run's status patches and PRODUCED_BATCH edges into it — and a closed batch
    # is not an append barrier, so those events would stay. A payload that does
    # not verify runs UNSCOPED: the run still happens (a bad third argument must
    # not stop collection), its bookkeeping falls back to the service layer's
    # auto-created batches, and the ERROR log names both sides
    # (req-tap-cares-collector-run-collection-16).
    from tap_cares.services import _is_lifecycle_batch_of

    scoped_batch_id = (
        lifecycle_batch_entity_id
        if _is_lifecycle_batch_of(lifecycle_batch_entity_id, collection_job_entity_id, operation="bind")
        else None
    )

    with acting_as(get_builtin_actor(COLLECTOR), batch_id=scoped_batch_id):
        try:
            _run_collection_job(collector_entity_id, collection_job_entity_id, scoped_batch_id=scoped_batch_id)
        finally:
            # Seal in `finally` so a raised failure — the standard collector
            # failure mode re-raises after its terminal patch — closes the batch
            # too. `_seal_lifecycle_batch` re-reads the job and seals only if it
            # is terminal, so a body that died before writing terminal state
            # leaves the batch open on purpose; see its docstring and
            # unified-systems-com/tap#471.
            from tap_cares.services import _seal_lifecycle_batch

            _seal_lifecycle_batch(scoped_batch_id or "", collection_job_entity_id)


def _record_completeness(scoped_batch_id: str | None, instance: Any) -> None:
    """Record the collector's surface statements on the run's lifecycle batch.

    Runs after `run()` on both terminal paths and before the terminal patch, while
    the lifecycle batch is still open (`_seal_lifecycle_batch` closes it afterwards).
    The recorder validates the statement, binds every cited `applied_batches` entry to
    the batches THIS run produced (a foreign batch is refused, never applied), and
    derives `applied` from those batches' committed status
    (req-grid-reconcile-evidence-6); a refused statement is
    logged at ERROR against the run and swallowed — bookkeeping must never turn a
    completed collection into a failed task, and an unscoped run (no lifecycle
    batch) has nowhere to record and says so.
    """
    if not getattr(instance, "_surfaces_declared", False):
        return
    surfaces = list(getattr(instance, "_surfaces", None) or [])
    if not scoped_batch_id:
        logger.error(
            "[79ec] collector recorded %d completeness surface(s) but the run is unscoped; nothing recorded",
            len(surfaces),
        )
        return
    from tap_grid.completeness import record_completeness
    from tap_grid.models import Batch

    try:
        record_completeness(
            Batch.objects.get(entity_id=scoped_batch_id),
            surfaces,
            produced_batches={batch_id for batch_id, _ in getattr(instance, "_produced_batches", [])},
        )
    except Exception as exc:
        logger.exception(
            "[23f6] collector: completeness statement refused for lifecycle batch %s; not recorded: %s",
            scoped_batch_id,
            exc,
        )


def _previous_run(collector_entity_id: str, job_entity_id: str) -> tuple[Any, set[str]]:
    """The previous SUCCESSFUL run of this collector: its lifecycle batch and the batches it produced.

    The previous run's completeness statement is the previous scope statement that
    candidate derivation compares this run's against for withdrawal
    (req-grid-reconcile-candidates-4); its produced batches are the evidence that a
    withdrawn child was ever observed. Walks Collector -HAS_COLLECTION_JOB-> CollectionJob,
    takes the most recently finished successful job other than this one, and reads its
    lifecycle batch through the same verification the worker and the seal use
    (`_is_lifecycle_batch_of`), so a job whose batch pointer does not check out yields
    no previous run rather than a foreign one. ``(None, set())`` when there is none.
    """
    from tap_cares.services import _is_lifecycle_batch_of
    from tap_grid.batch import produced_batches
    from tap_grid.models import Batch, Edge

    job_ids = Edge.objects.filter(from_entity_id=collector_entity_id, edge_type="HAS_COLLECTION_JOB").values_list(
        "to_entity_id", flat=True
    )  # type: ignore[misc]  # django-stubs sees the BaseModel manager
    previous = (
        CollectionJob.objects.filter(entity_id__in=list(job_ids), status=CollectionJobStatus.SUCCESSFUL.value)
        .exclude(entity_id=job_entity_id)
        .order_by("-finished_at", "-entity_id")
        .first()
    )
    if previous is None:
        return None, set()
    lifecycle_batch_id = str(previous.batch_id)
    if not _is_lifecycle_batch_of(lifecycle_batch_id, str(previous.entity_id), operation="candidate derivation"):
        return None, set()
    produced = produced_batches(previous.entity_id)
    # Both dispositions, deliberately: this run's set is `instance._produced_batches`,
    # which `CollectorBase.submit_grift` fills with BOTH imported and skipped batch ids
    # (tap_cares/collectors/base.py), and the derivation keeps only the CLOSED ones
    # either way. The two sides of the comparison read the same kind of set (Grok on
    # PR# 600 - tap).
    return Batch.objects.get(entity_id=lifecycle_batch_id), set(produced["imported"]) | set(produced["skipped"])


def _record_candidates(
    scoped_batch_id: str | None, instance: Any, collector_entity_id: str, job_entity_id: str
) -> None:
    """Derive and record this run's retirement candidates beside its completeness statement.

    Runs right after `_record_completeness`, on the same batch and under the same
    discipline: authority is off, so the record licenses nothing and retires nothing
    (req-grid-reconcile-candidates); a refused derivation is logged at ERROR against the
    run and swallowed. A run that recorded no statement (it declared none, or its
    statement was refused and already logged) has nothing to derive from and records
    nothing — that absence is the statement's, not a second finding.
    """
    if not scoped_batch_id or not getattr(instance, "_surfaces_declared", False):
        return
    from tap_grid.candidates import record_candidates
    from tap_grid.completeness import completeness_of
    from tap_grid.models import Batch

    try:
        batch = Batch.objects.get(entity_id=scoped_batch_id)
        if completeness_of(batch) is None:
            return
        previous_batch, previous_produced = _previous_run(collector_entity_id, job_entity_id)
        record_candidates(
            batch,
            produced_batches={batch_id for batch_id, _ in getattr(instance, "_produced_batches", [])},
            previous_batch=previous_batch,
            previous_produced_batches=previous_produced,
        )
    except Exception as exc:
        logger.exception(
            "[be00] collector: candidate derivation refused for lifecycle batch %s; not recorded: %s",
            scoped_batch_id,
            exc,
        )


def _reconcile(scoped_batch_id: str | None, instance: Any) -> None:
    """The run's final phase (req-grid-reconcile-verb): the one reconcile verb, called once, on
    the SUCCESSFUL path only — a failed run's evidence is not a licence to retire anything.

    Authority and budget are the run's: stamped on the lifecycle batch by `run_collection` from
    the Collector node's `reconcile_authority` (off by default) and `reconcile_budget` before any
    collector code ran; the verb reads them from the stamp and nowhere else, so nothing here — or
    in a collector — can arm a run. The verb runs as the bound `tap_cares.collector` program
    actor, which holds `grid.reconcile`; collector code itself never calls a delete verb, nor the
    verb (-1). A refusal is logged at ERROR against the run and swallowed: reconciliation
    bookkeeping must never turn a completed collection into a failed task, and with authority
    off the verb writes a record that says nothing was judged.
    """
    if not scoped_batch_id or not getattr(instance, "_surfaces_declared", False):
        return
    from tap_grid.candidates import candidates_of
    from tap_grid.models import Batch
    from tap_grid.services import reconcile

    try:
        batch = Batch.objects.get(entity_id=scoped_batch_id)
        if candidates_of(batch) is None:
            return
        reconcile(scoped_batch_id)
    except Exception as exc:
        # Visible on the job, not only in the log: the collection succeeded, the reconcile
        # phase did not, and a reader of the run must be able to tell (Codex on PR# 653 - tap).
        logger.exception(
            "[5bd1] collector: reconcile refused for lifecycle batch %s; not applied: %s", scoped_batch_id, exc
        )
        results = getattr(instance, "results", None)
        if isinstance(results, dict):
            results.setdefault("error", []).append(
                f"reconcile phase failed; nothing applied: {type(exc).__name__}: {exc}"[:500]
            )


def _run_collection_job(
    collector_entity_id: str,
    collection_job_entity_id: str,
    *,
    scoped_batch_id: str | None = None,
) -> None:
    """Run the two collector phases under the caller-bound program actor.

    Split out from `run_collector` so the actor-binding boundary stays a single
    visible line. This body assumes the `tap_cares.collector` context is already
    bound (see `run_collector`); its CollectionJob writes funnel through
    `_patch_job` and its GRIFT import through the collector's `submit_grift`, both
    of which inherit that actor from the contextvar.
    """
    # Task start: RUNNING transition. Patches status + started_at; the
    # task_result_id is set on the enqueue side in run_collection so this
    # task body doesn't depend on backend-specific context plumbing.
    now = datetime.now(UTC)
    _patch_job(
        collection_job_entity_id,
        {
            "status": CollectionJobStatus.RUNNING.value,
            "started_at": now.isoformat(),
        },
    )

    # Resolve the CollectionJob (for run_mode) and Collector node. A missing
    # Collector node (deleted between enqueue and pickup) fails the job via
    # the standard failure mode before phase 1 — self_test never ran, so it
    # is not written.
    job = CollectionJob.objects.get(entity_id=collection_job_entity_id)
    try:
        collector = Collector.objects.get(entity_id=collector_entity_id)
    except Collector.DoesNotExist as exc:
        _patch_job(
            collection_job_entity_id,
            {
                "status": CollectionJobStatus.FAILED.value,
                "finished_at": datetime.now(UTC).isoformat(),
                "summary": _safe_summary(exc),
                "results": dict(_EMPTY_RESULTS),
            },
        )
        raise

    # ------------------------------------------------------------------
    # Phase 1 — self-test. Default-on gate for every CollectionJob
    # (req-tap-cares-collector-self-test-10). The service entry point owns
    # registry resolution (RUNNER_UNAVAILABLE), exception trapping
    # (SELF_TEST_EXCEPTION), stamping, and the redaction-safe site-ID log;
    # it returns the result, never persists. Local import: services.py
    # imports run_collector, so a module-level import here is circular.
    # ------------------------------------------------------------------
    from tap_cares.services import self_test_collector

    readiness = self_test_collector(collector)
    self_test_payload = readiness.to_dict()

    if not readiness.runnable:
        # Non-runnable ⇒ standard collector failure mode
        # (req-tap-cares-collector-failure-mode): one terminal FAILED patch
        # carrying the self-test summary and the full self_test detail; no
        # phase-2 work, no GRIFT, no partial writes.
        _patch_job(
            collection_job_entity_id,
            {
                "status": CollectionJobStatus.FAILED.value,
                "finished_at": datetime.now(UTC).isoformat(),
                "summary": (readiness.summary or "")[:_SUMMARY_CAP],
                "results": dict(_EMPTY_RESULTS),
                "self_test": self_test_payload,
            },
        )
        # Re-raise so Django Tasks' own failure machinery sees the failure
        # (req-tap-cares-collector-failure-mode-5). The exception carries
        # only the operator-facing summary — no secret-bearing detail.
        raise CollectorNotReadyError(readiness.summary)

    if job.run_mode == CollectionJobRunMode.SELF_TEST_ONLY:
        # self_test_only ⇒ phase 1 passed; stop here SUCCESSFUL with no
        # collection performed (req-tap-cares-collector-self-test-16).
        _patch_job(
            collection_job_entity_id,
            {
                "status": CollectionJobStatus.SUCCESSFUL.value,
                "finished_at": datetime.now(UTC).isoformat(),
                "summary": "Self-test passed; no collection performed.",
                "results": dict(_EMPTY_RESULTS),
                "self_test": self_test_payload,
            },
        )
        return

    # ------------------------------------------------------------------
    # Phase 2 — collect (full + runnable only). The instance reference is
    # bound inside the try so that even pre-run() failures (collector
    # resolution, instantiation) flow through the same FAILED terminal-patch
    # path. The phase-1 self_test result rides on every phase-2 terminal
    # patch so readiness stays queryable on a failed run too.
    # ------------------------------------------------------------------
    instance = None
    try:
        # Resolve the collector class and instantiate. The instance owns its
        # own accumulator state (self.results, self._produced_batches, self.summary).
        cls = get_collector(collector.collector_registry)
        config = CollectorConfig(
            collector_entity_id=collector.entity_id,
            collection_job_entity_id=collection_job_entity_id,
        )
        instance = cls(config)
        # Run the collector. It accumulates results/_produced_batches/summary on
        # itself; nothing it does touches the CollectionJob row.
        instance.run()
    except Exception as exc:
        # Terminal write: FAILED. One patch carries the full accumulator. If
        # the collector set self.summary, that wins; otherwise derive a count
        # summary from results["error"], finally falling back to the exception
        # itself. If the instance never got constructed (registry /
        # instantiation failure), use empty defaults for the accumulators.
        if instance is not None:
            _record_completeness(scoped_batch_id, instance)
            _record_candidates(scoped_batch_id, instance, collector_entity_id, collection_job_entity_id)
            summary = _derive_failure_summary(instance, exc)
            results = instance.results
        else:
            summary = _safe_summary(exc)
            results = dict(_EMPTY_RESULTS)
        _patch_job(
            collection_job_entity_id,
            {
                "status": CollectionJobStatus.FAILED.value,
                "finished_at": datetime.now(UTC).isoformat(),
                "summary": summary,
                "results": results,
                "self_test": self_test_payload,
            },
        )
        # Link any batches produced before the failure so partial progress
        # stays visible (req-tap-cares-collector-grift-import-6). Best-effort
        # and must not mask the original collector failure below.
        if instance is not None:
            _link_produced_batches(job, instance._produced_batches)
        # Re-raise so Django Tasks' own failure machinery sees the failure
        # (req-tap-cares-collector-failure-mode-5).
        raise

    # The completeness statement lands on the lifecycle batch first, while it is
    # still open (req-grid-reconcile-evidence; the seal in `run_collector` closes it),
    # and the candidate record derived from it beside it (req-grid-reconcile-candidates).
    _record_completeness(scoped_batch_id, instance)
    _record_candidates(scoped_batch_id, instance, collector_entity_id, collection_job_entity_id)
    # The reconcile phase and the terminal SUCCESSFUL write are one transaction: a tombstone
    # never survives a run that could not record itself as successful (Codex on PR# 653 - tap).
    from django.db import transaction

    with transaction.atomic():
        _reconcile(scoped_batch_id, instance)
        # Terminal write: SUCCESSFUL. One patch carries the full accumulator,
        # including whatever the collector wrote to self.summary, plus the
        # phase-1 self_test result.
        _patch_job(
            collection_job_entity_id,
            {
                "status": CollectionJobStatus.SUCCESSFUL.value,
                "finished_at": datetime.now(UTC).isoformat(),
                "summary": (instance.summary or "")[:_SUMMARY_CAP],
                "results": instance.results,
                "self_test": self_test_payload,
            },
        )
    # Link each produced batch to the job with a PRODUCED_BATCH edge
    # (req-tap-cares-collector-grift-import-6). Done after the durable
    # terminal patch — these are run<->batch correlation, not the sole-writer
    # state — and best-effort per batch (see _link_produced_batches).
    _link_produced_batches(job, instance._produced_batches)
