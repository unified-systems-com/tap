"""Tests for the tap_cares scheduler service.

Covers req-tap-cares-scheduler-* (spec-tap-cares-scheduler.md). The scheduler
is the trigger system; collector execution is covered separately by
test_task_execution.py.

These tests use Django's ImmediateBackend (configured in tap/settings.py), so
when the scheduler invokes `run_collection(...)` the CollectionJob has its
terminal state by the time `evaluate_tick(...)` returns.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from tap_cares.models import (
    CollectionJob,
    CollectionJobStatus,
    Collector,
    Schedule,
    ScheduleFire,
    ScheduleFireStatus,
)
from tap_cares.registry import reconcile_collector_nodes, register_collector
from tap_cares.services.scheduler import (
    SchedulerError,
    _missed_count,
    create_schedule,
    evaluate_tick,
    set_schedule_enabled,
)
from tap_cares.tests.fakes import BoomCollector, HappyCollector
from tap_grid.models import Edge


@pytest.fixture
def collector(isolate_collector_registry) -> Collector:
    register_collector(
        key="happy",
        cls=HappyCollector,
        scope="tap_cares.tests.fakes",
        name="Test Happy Collector",
        description="Test fixture for scheduler tests.",
    )
    reconcile_collector_nodes()  # materialize the on-grid node (register is read-only)
    return Collector.objects.get(collector_registry="tap_cares.tests.fakes:happy")


@pytest.fixture
def boom_collector(isolate_collector_registry) -> Collector:
    register_collector(
        key="boom",
        cls=BoomCollector,
        scope="tap_cares.tests.fakes",
        name="Test Boom Collector",
        description="Test fixture: always-raising collector.",
    )
    reconcile_collector_nodes()  # materialize the on-grid node (register is read-only)
    return Collector.objects.get(collector_registry="tap_cares.tests.fakes:boom")


def _pin_enabled_at_before(schedule: Schedule, slot: datetime) -> Schedule:
    """Force schedule.enabled_at to one minute before `slot`.

    Tests use future slots to make scheduler behavior deterministic regardless
    of wall-clock time. Since `create_schedule` sets `enabled_at` to the actual
    wall-clock now(), the missed-count walk from there to a far-future slot
    would explode. Pinning enabled_at near the slot keeps the walk bounded and
    the test focused on what it actually exercises.
    """
    Schedule.objects.filter(pk=schedule.pk).update(enabled_at=slot - timedelta(minutes=1))
    schedule.refresh_from_db()
    return schedule


# ---------------------------------------------------------------------------
# Cron / missed-count helpers
# ---------------------------------------------------------------------------


def test_missed_count_null_lower_bound_returns_zero():
    """req-tap-cares-scheduler-missed-count: brand-new schedule has no missed slots."""
    result = _missed_count("* * * * *", None, datetime(2026, 5, 14, 12, 5, tzinfo=UTC))
    assert result == 0


def test_missed_count_every_minute_walk():
    """req-tap-cares-scheduler-missed-count: 12:00 -> 12:05 every-minute = 4 missed."""
    result = _missed_count(
        "* * * * *",
        datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
        datetime(2026, 5, 14, 12, 5, tzinfo=UTC),
    )
    assert result == 4


def test_missed_count_lower_bound_past_current_returns_zero():
    """If lower_bound >= current_slot (re-enabled in the future, etc.), no missed."""
    result = _missed_count(
        "* * * * *",
        datetime(2026, 5, 14, 13, 0, tzinfo=UTC),
        datetime(2026, 5, 14, 12, 5, tzinfo=UTC),
    )
    assert result == 0


def test_missed_count_hourly():
    """Hourly cron, 12:00 -> 16:00 = 3 missed (13, 14, 15)."""
    result = _missed_count(
        "0 * * * *",
        datetime(2026, 5, 14, 12, 0, tzinfo=UTC),
        datetime(2026, 5, 14, 16, 0, tzinfo=UTC),
    )
    assert result == 3


# ---------------------------------------------------------------------------
# Schedule create + cron validation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreateSchedule:
    def test_create_schedule_sets_enabled_at_when_enabled(self, collector):
        """req-tap-cares-scheduler-model-8: enabled=True sets enabled_at."""
        schedule = create_schedule(
            name="daily",
            cron_expression="0 6 * * *",
            collector=collector,
        )
        assert schedule.enabled is True
        assert schedule.enabled_at is not None

    def test_create_schedule_creates_scheduled_target_edge(self, collector):
        """req-tap-cares-scheduler-edges-1: SCHEDULED_TARGET edge wired up."""
        schedule = create_schedule(
            name="daily",
            cron_expression="0 6 * * *",
            collector=collector,
        )
        edges = Edge.objects.filter(
            from_entity_id=schedule.entity_id,
            edge_type="SCHEDULED_TARGET",
            to_entity_id=collector.entity_id,
        )
        assert edges.count() == 1

    def test_create_schedule_disabled_leaves_enabled_at_null(self, collector):
        schedule = create_schedule(
            name="parked",
            cron_expression="0 6 * * *",
            collector=collector,
            enabled=False,
        )
        assert schedule.enabled is False
        assert schedule.enabled_at is None

    def test_create_schedule_rejects_invalid_cron(self, collector):
        """req-tap-cares-scheduler-model-7: invalid cron rejected at write.

        Uses a five-field expression with an out-of-range value so the
        croniter substance check fires (the explicit field-count guard
        would short-circuit before croniter on a non-five-field input).
        """
        with pytest.raises(SchedulerError, match="Invalid cron expression"):
            create_schedule(
                name="bad",
                cron_expression="60 * * * *",  # minute=60 is out of range
                collector=collector,
            )

    def test_create_schedule_rejects_six_field_cron(self, collector):
        """req-tap-cares-scheduler-cron-1: only five-field cron is accepted.

        croniter.is_valid accepts six-field (seconds) and seven-field (year)
        variants depending on version; the explicit length check in
        Schedule.validate keeps v0 pinned to the spec'd field count.
        """
        with pytest.raises(SchedulerError, match="five-field cron"):
            create_schedule(
                name="six-field",
                cron_expression="0 0 0 * * *",  # six fields (with seconds)
                collector=collector,
            )

    def test_create_schedule_rejects_seven_field_cron(self, collector):
        """Same as the six-field guard, for the year-extension variant."""
        with pytest.raises(SchedulerError, match="five-field cron"):
            create_schedule(
                name="seven-field",
                cron_expression="0 0 0 * * * 2026",  # seven fields (with year)
                collector=collector,
            )

    def test_create_schedule_payload_omits_cursor_fields(self, collector):
        """req-tap-cares-scheduler-model: enabled_at and last_schedule_fired
        are scheduler-owned and must not be in FIELD_CRUD_SCHEMA.

        Public create_node with these fields in the payload should be
        rejected by the CRUD schema, not silently accepted.
        """
        from tap_grid.caller_context import CallerContext
        from tap_grid.services import create_node

        result = create_node(
            "schedule",
            {
                "name": "cursor-injected",
                "cron_expression": "0 0 * * *",
                "enabled_at": "2026-05-14T00:00:00Z",
                "last_schedule_fired": "2026-05-14T00:00:00Z",
            },
            caller_context=CallerContext(),
        )
        assert result.success is False
        assert any(
            "enabled_at" in (e.message or "") or "enabled_at" == (e.field or "") for e in result.errors
        ), f"expected enabled_at rejection, got {result.errors}"


@pytest.mark.django_db
class TestScheduleSaveStampsEnabledAt:
    """req-tap-cares-scheduler-model-8 safety net.

    Covers Schedule.save() auto-stamping `enabled_at` when a schedule is
    written via a path that doesn't manage the field explicitly (GRIFT
    import, direct ORM, etc.).
    """

    def test_grift_style_create_stamps_enabled_at(self, collector):
        """GRIFT seeds enabled=True without enabled_at; save fills it in."""
        schedule = create_schedule(
            name="grift-style",
            cron_expression="0 0 * * *",
            collector=collector,
        )
        # Simulate the GRIFT path: force enabled_at back to None and re-save
        # so the model-level safety net is the only thing stamping it.
        Schedule.objects.filter(pk=schedule.pk).update(enabled_at=None)
        schedule.refresh_from_db()
        assert schedule.enabled_at is None
        schedule.save()
        schedule.refresh_from_db()
        assert schedule.enabled_at is not None

    def test_disabled_save_does_not_stamp(self, collector):
        """Disabled schedule with enabled_at=None stays None across saves."""
        schedule = create_schedule(
            name="disabled grift-style",
            cron_expression="0 0 * * *",
            collector=collector,
            enabled=False,
        )
        assert schedule.enabled_at is None
        schedule.save()
        schedule.refresh_from_db()
        assert schedule.enabled_at is None

    def test_existing_enabled_at_preserved(self, collector):
        """If enabled_at is already set, save does not overwrite it."""
        schedule = create_schedule(
            name="preserve",
            cron_expression="0 0 * * *",
            collector=collector,
        )
        original = schedule.enabled_at
        assert original is not None
        schedule.save()
        schedule.refresh_from_db()
        assert schedule.enabled_at == original


@pytest.mark.django_db
class TestSetScheduleEnabled:
    def test_disable_then_enable_updates_enabled_at(self, collector):
        """req-tap-cares-scheduler-model-8: false->true transition refreshes enabled_at."""
        schedule = create_schedule(
            name="toggle",
            cron_expression="0 6 * * *",
            collector=collector,
        )
        first_enabled_at = schedule.enabled_at

        # Disable; enabled_at stays as-is.
        schedule = set_schedule_enabled(schedule, False)
        assert schedule.enabled is False
        assert schedule.enabled_at == first_enabled_at

        # Re-enable; enabled_at updates to the new transition time.
        schedule = set_schedule_enabled(schedule, True)
        assert schedule.enabled is True
        assert schedule.enabled_at > first_enabled_at


# ---------------------------------------------------------------------------
# evaluate_tick — triggered path
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestEvaluateTickTriggered:
    def test_matching_slot_creates_triggered_fire(self, collector):
        """req-tap-cares-scheduler-edges + req-tap-cares-scheduler-fire-model.

        Matching slot: TRIGGERED fire + TRIGGERED_JOB edge + a SUCCESSFUL job.
        """
        slot = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)
        schedule = create_schedule(
            name="every minute",
            cron_expression="* * * * *",
            collector=collector,
        )
        _pin_enabled_at_before(schedule, slot)
        fires = evaluate_tick(now=slot)
        assert len(fires) == 1
        fire = fires[0]
        fire.refresh_from_db()
        assert fire.status == ScheduleFireStatus.TRIGGERED.value
        assert "Triggered run" in fire.summary
        # TRIGGERED_JOB edge created.
        triggered_edges = Edge.objects.filter(
            from_entity_id=fire.entity_id,
            edge_type="TRIGGERED_JOB",
        )
        assert triggered_edges.count() == 1
        # Job ran and is SUCCESSFUL under ImmediateBackend.
        job = CollectionJob.objects.get(entity_id=triggered_edges.first().to_entity_id)
        assert job.status == CollectionJobStatus.SUCCESSFUL

    def test_non_matching_slot_creates_no_fire(self, collector):
        """req-tap-cares-scheduler-fire-model-8: non-matching ticks produce no rows.

        No need to pin enabled_at here: a non-matching slot never gets past
        the cron-match check, so the missed-count walk never runs.
        """
        create_schedule(
            name="6am daily",
            cron_expression="0 6 * * *",
            collector=collector,
        )
        slot = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)  # 12:00, cron wants 06:00
        fires = evaluate_tick(now=slot)
        assert fires == []
        assert ScheduleFire.objects.count() == 0

    def test_dedupe_same_slot_no_second_fire(self, collector):
        """req-tap-cares-scheduler-dedupe: same slot twice = one fire."""
        slot = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)
        schedule = create_schedule(
            name="every minute",
            cron_expression="* * * * *",
            collector=collector,
        )
        _pin_enabled_at_before(schedule, slot)
        first = evaluate_tick(now=slot)
        second = evaluate_tick(now=slot)
        assert len(first) == 1
        assert second == []
        assert ScheduleFire.objects.count() == 1

    def test_disabled_schedule_ignored(self, collector):
        """Disabled schedules are skipped before claim."""
        create_schedule(
            name="disabled",
            cron_expression="* * * * *",
            collector=collector,
            enabled=False,
        )
        slot = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)
        fires = evaluate_tick(now=slot)
        assert fires == []


# ---------------------------------------------------------------------------
# evaluate_tick — skipped path (max_active_runs)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEvaluateTickSkipped:
    def test_max_active_runs_skips_fire(self, collector):
        """req-tap-cares-scheduler-concurrency-3: at-limit creates SKIPPED fire.

        ImmediateBackend completes jobs synchronously, so a normal first tick
        leaves no active run. We force the "at limit" condition by mocking the
        active-run count.
        """
        slot = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)
        schedule = create_schedule(
            name="cap=1",
            cron_expression="* * * * *",
            collector=collector,
            max_active_runs=1,
        )
        _pin_enabled_at_before(schedule, slot)
        with patch("tap_cares.services.scheduler._active_run_count", return_value=1):
            fires = evaluate_tick(now=slot)
        assert len(fires) == 1
        fire = fires[0]
        fire.refresh_from_db()
        assert fire.status == ScheduleFireStatus.SKIPPED.value
        assert "max_active_runs" in fire.summary
        # No TRIGGERED_JOB edge for skipped fires.
        assert Edge.objects.filter(from_entity_id=fire.entity_id, edge_type="TRIGGERED_JOB").count() == 0


# ---------------------------------------------------------------------------
# evaluate_tick — failed path (run_collection raises)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEvaluateTickFailed:
    def test_run_collection_raises_creates_failed_fire(self, collector):
        """req-tap-cares-scheduler-fire-model-9: run_collection raise -> FAILED fire."""
        slot = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)
        schedule = create_schedule(
            name="will fail",
            cron_expression="* * * * *",
            collector=collector,
        )
        _pin_enabled_at_before(schedule, slot)
        with patch(
            "tap_cares.services.run_collection",
            side_effect=RuntimeError("simulated dispatch failure"),
        ):
            fires = evaluate_tick(now=slot)
        assert len(fires) == 1
        fire = fires[0]
        fire.refresh_from_db()
        assert fire.status == ScheduleFireStatus.FAILED.value
        assert "Scheduler error" in fire.summary
        assert "simulated dispatch failure" in fire.summary
        # No TRIGGERED_JOB edge for failed fires.
        assert Edge.objects.filter(from_entity_id=fire.entity_id, edge_type="TRIGGERED_JOB").count() == 0


# ---------------------------------------------------------------------------
# evaluate_tick — missed_count flowing through to the fire row
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEvaluateTickMissedCount:
    def test_first_fire_missed_count_zero(self, collector):
        """Brand-new schedule's first fire has missed_count=0."""
        slot = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)
        schedule = create_schedule(
            name="fresh",
            cron_expression="* * * * *",
            collector=collector,
        )
        _pin_enabled_at_before(schedule, slot)
        fires = evaluate_tick(now=slot)
        assert len(fires) == 1
        fires[0].refresh_from_db()
        assert fires[0].missed_count == 0

    def test_gap_between_ticks_records_missed_count(self, collector):
        """req-tap-cares-scheduler-missed-count: gap shows up as missed_count."""
        schedule = create_schedule(
            name="every minute",
            cron_expression="* * * * *",
            collector=collector,
        )
        # Pin enabled_at just before the first slot so it doesn't gate the lower bound.
        slot_a = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)
        slot_b = datetime(2099, 1, 1, 12, 5, tzinfo=UTC)
        Schedule.objects.filter(pk=schedule.pk).update(enabled_at=slot_a - timedelta(minutes=1))
        evaluate_tick(now=slot_a)
        fires = evaluate_tick(now=slot_b)
        assert len(fires) == 1
        fires[0].refresh_from_db()
        # 4 missed slots: 12:01, 12:02, 12:03, 12:04.
        assert fires[0].missed_count == 4


# ---------------------------------------------------------------------------
# Misconfiguration: SCHEDULED_TARGET edge missing
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSchedulerErrors:
    def test_schedule_with_no_target_edge_fails_dispatch(self, collector):
        """A schedule without a SCHEDULED_TARGET edge produces a FAILED fire.

        Manually remove the edge after create_schedule so we exercise the
        runtime path that catches the misconfiguration.
        """
        slot = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)
        schedule = create_schedule(
            name="orphan",
            cron_expression="* * * * *",
            collector=collector,
        )
        _pin_enabled_at_before(schedule, slot)
        Edge.objects.filter(from_entity_id=schedule.entity_id, edge_type="SCHEDULED_TARGET").delete()
        fires = evaluate_tick(now=slot)
        assert len(fires) == 1
        fires[0].refresh_from_db()
        assert fires[0].status == ScheduleFireStatus.FAILED.value
        assert "SCHEDULED_TARGET" in fires[0].summary
