"""tap_cares models.

req-tap-cares-collector-model, req-tap-cares-collector-job-model,
req-tap-cares-collector-job-edge, req-tap-cares-collector-job-lifecycle
(spec-tap-cares-collector.md).

req-tap-cares-scheduler-model, req-tap-cares-scheduler-fire-model,
req-tap-cares-scheduler-edges (spec-tap-cares-scheduler.md). The Schedule
model is the on-grid policy node for recurring collector execution. The
ScheduleFire model is the durable decision record for one evaluated cron
slot. Schedule --SCHEDULED_TARGET--> Collector binds a schedule to its
collector. Schedule --HAS_FIRED--> ScheduleFire records the fire history.
ScheduleFire --TRIGGERED_JOB--> CollectionJob bridges scheduled fires to
collector runs.

The Collector model is the on-grid representation of a tap_cares collector
capability. The CollectionJob model is the run record for one attempted
execution of a collector. Collector --HAS_COLLECTION_JOB--> CollectionJob ties the two
together. Status mirrors Django's TaskResultStatus for v0; future TAP-specific
states extend the local TextChoices rather than the upstream Django enum.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from croniter import croniter
from django.core.exceptions import ValidationError
from django.db import models

from tap_cares.exceptions import InvalidCollectorRegistryKeyError
from tap_cares.registry import _validate_collector_token
from tap_grid.models import BaseModel


class Collector(BaseModel):
    """An on-grid tap_cares collector capability.

    The collector_registry field stores a `scope:key` referencing a registered
    CollectorBase subclass. Persisting a Collector with a short key (no `:`),
    a malformed scope/key, or a duplicate collector_registry value all fail
    validation. The Python class itself is never resolved or imported at
    persist time — that happens at execution time via
    `tap_cares.registry.get_collector`.

    Spec: tap_cares/specs/spec-tap-cares-collector.md
    """

    ENTITY_TYPE: ClassVar[str] = "collector"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap_cares": "collector"}
    INTERNAL_ONLY: ClassVar[bool] = True

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "collection_job"}], "edges": [{"type": "HAS_COLLECTION_JOB"}]},
    ]
    INBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "schedule"}], "edges": [{"type": "SCHEDULED_TARGET"}]},
    ]

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, dict[str, Any]]] = {
        "name": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "collector_registry": {"type": "string", "minLength": 1},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name", "collector_registry"]

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict[str, Any]]] = {
        "name": {
            "validation": "jsonschema",
            "schema": {"type": "string", "minLength": 1},
        },
        "description": {
            "validation": "jsonschema",
            "schema": {"type": "string"},
        },
        "collector_registry": {
            "validation": "jsonschema",
            # Loose JSON-schema check; the strict scope:key format check lives in
            # validate() so the error speaks in terms of scope/key rather than regex.
            "schema": {"type": "string", "minLength": 3},
        },
    }

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    collector_registry = models.CharField(max_length=512, unique=True)

    class Meta(BaseModel.Meta):
        db_table = "tap_cares_collector"

    def get_name(self) -> str:
        return self.name or ""

    def __str__(self) -> str:
        return self.name

    def validate(self) -> None:
        """Enforce the scope:key format on collector_registry.

        Short keys (no `:`) are rejected per req-tap-cares-collector-model-4.
        Both halves of the scope:key are validated with
        `_validate_collector_token`, the same helper the registry calls — so
        model-side and registry-side enforcement cannot drift
        (req-tap-cares-collector-registry-10).
        """
        value = self.collector_registry or ""
        if ":" not in value:
            raise ValidationError(
                {
                    "collector_registry": [
                        "Must use scope:key format; short keys are not allowed.",
                    ]
                }
            )
        scope_part, key_part = value.rsplit(":", 1)
        try:
            _validate_collector_token(scope_part)
            _validate_collector_token(key_part)
        except InvalidCollectorRegistryKeyError as exc:
            raise ValidationError({"collector_registry": [str(exc)]}) from exc


def _empty_results_dict() -> dict[str, list]:
    """Default for `CollectionJob.results`.

    Module-level callable so Django migrations can import it by path. Returns a
    fresh dict per call (mutable defaults must never be shared).
    """
    return {"info": [], "warn": [], "error": []}


def _empty_self_test() -> dict[str, Any]:
    """Default for `CollectionJob.self_test`.

    Empty until phase 1 runs. The run-task body writes the structured
    `CollectorSelfTestResult.to_dict()` here at terminal state
    (req-tap-cares-collector-self-test-2). Module-level callable so Django
    migrations can import it by path; fresh dict per call.
    """
    return {}


class CollectionJobStatus(models.TextChoices):
    """v0 CollectionJob lifecycle states — mirror django.tasks.TaskResultStatus.

    req-tap-cares-collector-job-lifecycle. Stored values are uppercase to match
    Django Tasks; display labels are title-case. Future TAP-specific states
    (`CANCEL_REQUESTED`, `CANCELLED`, `BLOCKED`, `PARTIAL`, etc.) extend this
    local enum rather than depending on Django's set evolving
    (req-tap-cares-collector-job-lifecycle-7).
    """

    READY = "READY", "Ready"
    RUNNING = "RUNNING", "Running"
    FAILED = "FAILED", "Failed"
    SUCCESSFUL = "SUCCESSFUL", "Successful"


class CollectionJobRunMode(models.TextChoices):
    """Run-mode discriminator (req-tap-cares-collector-self-test-16).

    `full` runs phase 1 (self-test) then, if runnable, phase 2 (collect).
    `self_test_only` runs phase 1 and stops — a one-off readiness probe (the
    Administrivia Self-test button, an agent probe) is simply a
    `self_test_only` `CollectionJob` on the standard async path. Manual Run
    and the scheduler create `full` jobs.
    """

    FULL = "full", "Full"
    SELF_TEST_ONLY = "self_test_only", "Self-test only"


class CollectionJob(BaseModel):
    """The on-grid run record for one attempted execution of a Collector.

    Created by the tap_cares orchestration service when a collector is
    enqueued; updated as the Django task transitions through its lifecycle.
    Collector module classes do not write to CollectionJob directly
    (req-tap-cares-collector-job-lifecycle-3) — the runtime owns lifecycle
    updates.

    `task_result_id` is the string identifier returned by Django Tasks'
    `TaskResult.id` — not a UUID. The built-in `immediate` / `dummy` backends
    use 32-char random strings; database-backed or third-party backends are
    free to choose another format. Stored as `CharField(max_length=128)` to
    accommodate any of them while staying index-friendly. Empty string means
    the task was not enqueued or enqueue raised
    (req-tap-cares-collector-job-model-6).

    Spec: tap_cares/specs/spec-tap-cares-collector.md
    """

    ENTITY_TYPE: ClassVar[str] = "collection_job"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap_cares": "collection_job"}
    INTERNAL_ONLY: ClassVar[bool] = True

    INBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "collector"}], "edges": [{"type": "HAS_COLLECTION_JOB"}]},
        {"nodes": [{"type": "schedule_fire"}], "edges": [{"type": "TRIGGERED_JOB"}]},
    ]

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, dict[str, Any]]] = {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "status": {"type": "string", "enum": [s.value for s in CollectionJobStatus]},
        # Run-mode discriminator (req-tap-cares-collector-self-test-16). Set
        # at create by run_collection; not patched after.
        "run_mode": {"type": "string", "enum": [m.value for m in CollectionJobRunMode]},
        "task_result_id": {"type": "string"},
        "summary": {"type": "string"},
        # Manual run provenance — req-tap-cares-collector-job-model-21.
        # Scheduler-triggered runs leave both at defaults; the inbound
        # TRIGGERED_JOB edge from ScheduleFire is the scheduler-trigger record.
        "manual_run": {"type": "boolean"},
        "manual_run_source": {"type": "string"},
        # Lifecycle timestamps — set by run_collection (enqueued_at) and the
        # run_collector task body (started_at, finished_at). Datetimes flow in
        # as ISO-8601 strings through the service-layer patch path; Django's
        # DateTimeField parses them on save.
        "enqueued_at": {"type": ["string", "null"], "format": "date-time"},
        "started_at": {"type": ["string", "null"], "format": "date-time"},
        "finished_at": {"type": ["string", "null"], "format": "date-time"},
        # Accumulator — written once at terminal state by the task body from
        # the collector instance's self.results. (Produced batches are a graph
        # relationship: CollectionJob --PRODUCED_BATCH--> Batch, not a field.)
        "results": {"type": "object"},
        # Phase-1 self-test result, written once at terminal state by the
        # task body from the CollectorSelfTestResult (sole-writer invariant,
        # req-tap-cares-collector-self-test-2). Distinct from `results`.
        "self_test": {"type": "object"},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict[str, Any]]] = {
        "status": {
            "validation": "jsonschema",
            "schema": {"type": "string", "enum": [s.value for s in CollectionJobStatus]},
        },
        "run_mode": {
            "validation": "jsonschema",
            "schema": {"type": "string", "enum": [m.value for m in CollectionJobRunMode]},
        },
        "task_result_id": {
            "validation": "jsonschema",
            "schema": {"type": "string", "maxLength": 128},
        },
        "summary": {
            "validation": "jsonschema",
            "schema": {"type": "string", "maxLength": 2048},
        },
        "manual_run_source": {
            "validation": "jsonschema",
            "schema": {"type": "string", "maxLength": 255},
        },
    }

    name = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=CollectionJobStatus.choices,
        default=CollectionJobStatus.READY,
        db_index=True,
    )
    run_mode = models.CharField(
        max_length=16,
        choices=CollectionJobRunMode.choices,
        default=CollectionJobRunMode.FULL,
        db_index=True,
    )
    task_result_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    summary = models.CharField(max_length=2048, blank=True, default="")
    manual_run = models.BooleanField(default=False, db_index=True)
    manual_run_source = models.CharField(max_length=255, blank=True, default="")
    enqueued_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    # Batches this run produced are NOT stored on the row: at terminal state the
    # task body creates one CollectionJob --PRODUCED_BATCH--> Batch edge per
    # produced batch, with a `disposition` ∈ {imported, skipped} property
    # (req-grid-edge-produced-batch / req-tap-cares-collector-grift-import-6).
    # Read them via tap_grid.batch.produced_batches(job.entity_id).
    # Structured per-event log for this run; appended by tap_cares.results
    # record_info / record_warn / record_error helpers. Pinned shape lives at
    # tap_cares/schemas/collection_job_results.schema.json. Per
    # req-tap-cares-collector-job-model-9 through -16.
    results = models.JSONField(default=_empty_results_dict, blank=True)
    # Phase-1 self-test result (CollectorSelfTestResult.to_dict()), written
    # once at terminal state by the run-task body. Empty {} until phase 1
    # runs. Kept distinct from `results` so readiness stays queryable on its
    # own: latest readiness for a collector = the most recent CollectionJob's
    # self_test. Per req-tap-cares-collector-self-test-2; redaction-safe per
    # req-tap-cares-collector-self-test-13.
    self_test = models.JSONField(default=_empty_self_test, blank=True)

    class Meta(BaseModel.Meta):
        db_table = "tap_cares_collection_job"

    def get_name(self) -> str:
        return self.name or f"Collection {self.entity_id}" if self.entity_id else (self.name or "Collection")

    def __str__(self) -> str:
        return self.get_name()

    @property
    def status_display(self) -> str:
        """Title-case human label for `status`.

        Companion to the raw `status` value (req-tap-cares-collector-job-model-8).
        Equivalent to Django's auto-generated `get_status_display()`; exposed as
        a property so serializers and templates can use either spelling.
        """
        return self.get_status_display()


class Schedule(BaseModel):
    """An on-grid recurring policy that says "run this collector when cron matches."

    TAP-IMPLEMENTS: req-tap-cares-scheduler-model@da4d5cabb307/163216b7ad52 (derivation) — the
        on-grid recurring-policy node.

    `Schedule` is user-creatable: writes flow through the tap_cares scheduler
    service for cron validation and `enabled_at` tracking, but the type is not
    `INTERNAL_ONLY` and may be seeded via GRIFT.

    Spec: tap_cares/specs/spec-tap-cares-scheduler.md
    """

    ENTITY_TYPE: ClassVar[str] = "schedule"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap_cares": "schedule"}

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "collector"}], "edges": [{"type": "SCHEDULED_TARGET"}]},
        {"nodes": [{"type": "schedule_fire"}], "edges": [{"type": "HAS_FIRED"}]},
    ]

    # Public CRUD surface — what users can set via create_node / patch_node.
    # `enabled_at` and `last_schedule_fired` are deliberately omitted: they are
    # scheduler-owned bookkeeping fields (the missed-count lower bound and the
    # dedupe cursor respectively). Letting users patch them would let callers
    # skip slot evaluation or fabricate missed-count gaps. The scheduler
    # service writes both via direct ORM; first-save `enabled_at` is stamped
    # automatically by Schedule.save() (req-tap-cares-scheduler-model-8).
    FIELD_CRUD_SCHEMA: ClassVar[dict[str, dict[str, Any]]] = {
        "name": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "enabled": {"type": "boolean"},
        "cron_expression": {"type": "string", "minLength": 1},
        "max_active_runs": {"type": "integer", "minimum": 1},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name", "cron_expression"]

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict[str, Any]]] = {
        "name": {
            "validation": "jsonschema",
            "schema": {"type": "string", "minLength": 1},
        },
        "cron_expression": {
            "validation": "jsonschema",
            # JSON-schema layer is a loose minLength check; strict croniter
            # validation lives in validate() so the error message names
            # cron_expression directly.
            "schema": {"type": "string", "minLength": 1},
        },
        "max_active_runs": {
            "validation": "jsonschema",
            "schema": {"type": "integer", "minimum": 1},
        },
    }

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    enabled = models.BooleanField(default=True, db_index=True)
    enabled_at = models.DateTimeField(null=True, blank=True)
    cron_expression = models.CharField(max_length=255)
    last_schedule_fired = models.DateTimeField(null=True, blank=True, db_index=True)
    max_active_runs = models.PositiveIntegerField(default=1)

    class Meta(BaseModel.Meta):
        db_table = "tap_cares_schedule"

    def get_name(self) -> str:
        return self.name or ""

    def __str__(self) -> str:
        return self.name

    def validate(self) -> None:
        """Whole-record validation hook.

        TAP-IMPLEMENTS: req-tap-cares-scheduler-cron@1db38f24577c/6a90d100b422 (derivation) — the
            five-field cron rule enforced before croniter.

        Validates `cron_expression` with croniter at write time
        (req-tap-cares-scheduler-model-7). Invalid expressions are rejected
        before save so a bad schedule cannot enter the database and produce
        failed fires forever.

        Enforces five-field cron explicitly before delegating to croniter.
        croniter.is_valid accepts six-field (seconds) and seven-field (year)
        variants depending on version, but `req-tap-cares-scheduler-cron-1`
        pins v0 to five-field; widening the contract via library defaults
        would silently change scheduler semantics.
        """
        expr = self.cron_expression or ""
        field_count = len(expr.split())
        if field_count != 5:
            raise ValidationError(
                {
                    "cron_expression": [
                        f"Must be a five-field cron expression "
                        f"(minute hour day-of-month month day-of-week); "
                        f"got {field_count} field(s) in {expr!r}.",
                    ]
                }
            )
        if not croniter.is_valid(expr):
            raise ValidationError(
                {
                    "cron_expression": [
                        f"Invalid cron expression: {expr!r}. "
                        "Use five-field cron (minute hour day-of-month month day-of-week).",
                    ]
                }
            )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Stamp `enabled_at` on save when the schedule is enabled but unset.

        Catches the case where a schedule is written by a path that does not
        manage `enabled_at` explicitly — GRIFT import, direct ORM, or a
        future entry point — and the field would otherwise stay null
        forever. Keeps the field's semantic ("when the schedule became
        enabled") honest across all entry paths
        (req-tap-cares-scheduler-model-8).

        Does not handle the false->true transition case — that lives in
        `scheduler.set_schedule_enabled`, which sets `enabled_at` before
        save so this branch is a no-op for the service path. Two writers
        for one field is intentional: the model is the safety net for
        non-service paths, the service is the explicit transition stamp.
        We deliberately do NOT consult `self.history` to detect transitions
        because the simple-history audit log is not application logic.
        """
        if self.enabled and self.enabled_at is None:
            self.enabled_at = datetime.now(UTC)
        super().save(*args, **kwargs)


class ScheduleFireStatus(models.TextChoices):
    """ScheduleFire lifecycle states (req-tap-cares-scheduler-fire-model).

    `PENDING` is the initial value at Stage 1 (slot claim) and is transient —
    Stage 2 transitions to one of the three terminal values. A fire stuck in
    `PENDING` for more than a tick indicates the scheduler crashed between
    Stage 1 commit and Stage 2 completion.
    """

    PENDING = "PENDING", "Pending"
    TRIGGERED = "TRIGGERED", "Triggered"
    SKIPPED = "SKIPPED", "Skipped"
    FAILED = "FAILED", "Failed"


class ScheduleFire(BaseModel):
    """The on-grid execution-decision record for one evaluated cron slot.

    TAP-IMPLEMENTS: req-tap-cares-scheduler-fire-model@3c7180cf74e0/65903fe45c87 (derivation) —
        the per-slot execution-decision record.

    Created in Stage 1 of the scheduler tick (slot claim, status=PENDING) and
    updated to a terminal status (TRIGGERED/SKIPPED/FAILED) in Stage 2. Only
    the scheduler subsystem may create or modify fires — `INTERNAL_ONLY = True`
    (req-tap-cares-scheduler-fire-model-2).

    The relationship back to `Schedule` is the canonical `HAS_FIRED` edge,
    matching the `Collector --HAS_COLLECTION_JOB--> CollectionJob` pattern. "One fire per
    slot" is enforced by the atomic claim on `Schedule.last_schedule_fired`
    plus `INTERNAL_ONLY` (req-tap-cares-scheduler-dedupe-3); no denormalized
    `schedule` FK is needed for v0.

    Spec: tap_cares/specs/spec-tap-cares-scheduler.md
    """

    ENTITY_TYPE: ClassVar[str] = "schedule_fire"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {"tap_cares": "schedule_fire"}
    INTERNAL_ONLY: ClassVar[bool] = True

    INBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "schedule"}], "edges": [{"type": "HAS_FIRED"}]},
    ]
    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "collection_job"}], "edges": [{"type": "TRIGGERED_JOB"}]},
    ]

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, dict[str, Any]]] = {
        "name": {"type": "string"},
        "description": {"type": "string"},
        "status": {"type": "string", "enum": [s.value for s in ScheduleFireStatus]},
        "scheduled_for": {"type": "string", "format": "date-time"},
        "fired_at": {"type": "string", "format": "date-time"},
        "missed_count": {"type": "integer", "minimum": 0},
        "summary": {"type": "string"},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name", "scheduled_for", "fired_at"]

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict[str, Any]]] = {
        "status": {
            "validation": "jsonschema",
            "schema": {"type": "string", "enum": [s.value for s in ScheduleFireStatus]},
        },
        "missed_count": {
            "validation": "jsonschema",
            "schema": {"type": "integer", "minimum": 0},
        },
        "summary": {
            "validation": "jsonschema",
            "schema": {"type": "string", "maxLength": 2048},
        },
    }

    name = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=ScheduleFireStatus.choices,
        default=ScheduleFireStatus.PENDING,
        db_index=True,
    )
    scheduled_for = models.DateTimeField(db_index=True)
    fired_at = models.DateTimeField()
    missed_count = models.PositiveIntegerField(default=0)
    summary = models.CharField(max_length=2048, blank=True, default="")

    class Meta(BaseModel.Meta):
        db_table = "tap_cares_schedule_fire"

    def get_name(self) -> str:
        if self.name:
            return self.name
        if self.scheduled_for:
            return f"Fire {self.scheduled_for.isoformat()}"
        return "Fire"

    def __str__(self) -> str:
        return self.get_name()

    @property
    def status_display(self) -> str:
        """Title-case human label for `status`."""
        return self.get_status_display()
