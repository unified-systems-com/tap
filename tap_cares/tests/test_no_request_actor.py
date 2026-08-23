"""Production-realism auth tests for the tap_cares no-request boundaries.

The bug class these guard against is "green in CI, denied in prod": a Django-Tasks
worker (`run_collector`) or a scheduler tick (`scheduler_tick`) runs on a bare
thread with **no ambient `CallerContext`** — CI binds an ambient `tap_test` actor
(conftest autouse), a real worker thread binds none. Unless each background task
binds a named program actor, every graph write fails closed at the stateless
backstop. `run_collector` self-binds `tap_cares.collector` in its own body; the
scheduler tick declares `tap_cares.scheduler` and calls the *gated* `evaluate_tick`
(which, under the boundary convention, no longer invents its own trigger identity).
These tests clear the ambient actor and assert each path either binds correctly and
commits, or — for the gated tick — is denied up front when nothing is bound.

The complementary surface is the `run_collection` trigger gate
(`@requires_capability("cares.run_collectors")`): the *triggering* actor — the
request user passed through from tap_web, the scheduler, the bootloader — is
authorized to run collectors **before** the collection swaps to the
least-privilege `tap_cares.collector` execution identity. Two decisions, never
collapsed (req-tap-auth-actor-model).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from tap_auth import capabilities as caps
from tap_auth.actors import SCHEDULER, acting_as, get_builtin_actor
from tap_auth.errors import CapabilityDenied, MissingActor
from tap_auth.models import Capability
from tap_cares.models import (
    CollectionJob,
    CollectionJobRunMode,
    CollectionJobStatus,
    Collector,
    Schedule,
    ScheduleFireStatus,
)
from tap_cares.registry import reconcile_collector_nodes, register_collector
from tap_cares.services import create_schedule, evaluate_tick, run_collection
from tap_cares.tasks import run_collector
from tap_cares.tests.fakes import HappyCollector
from tap_grid.caller_context import CallerContext, set_caller_context
from tap_grid.services import _create_node_internal

User = get_user_model()


@pytest.fixture(autouse=True)
def reset_happy_runs():
    HappyCollector.runs.clear()
    yield
    HappyCollector.runs.clear()


def _collector(*, scope: str = "tap_cares.tests.fakes", key: str = "happy") -> Collector:
    register_collector(
        key=key,
        cls=HappyCollector,
        scope=scope,
        name="No-request test collector",
        description="Fixture collector for tap_cares.tests.test_no_request_actor.",
    )
    reconcile_collector_nodes()  # materialize the on-grid node (register is read-only)
    return Collector.objects.get(collector_registry=f"{scope}:{key}")


def _make_ready_job(collector: Collector) -> str:
    """Create a READY CollectionJob row the way `run_collection` does, but WITHOUT
    enqueuing the task — so the task body can then be invoked in isolation under a
    deliberately cleared context. Runs under the ambient `tap_test` actor."""
    now = datetime.now(UTC)
    result = _create_node_internal(
        "collection_job",
        {
            "name": f"no-ambient {now.isoformat()}",
            "description": "prod-realism: bare worker thread, no ambient actor",
            "status": CollectionJobStatus.READY.value,
            "run_mode": CollectionJobRunMode.FULL.value,
            "enqueued_at": now.isoformat(),
            "manual_run": False,
            "manual_run_source": "",
        },
    )
    assert result.success, result.errors
    return str(result.entity_id)


def _ctx_with_caps(*capabilities: str, username: str) -> CallerContext:
    """A context whose actor holds exactly `capabilities` via one ad-hoc group —
    independent of the built-in bundles. Mirrors tap_auth.tests.test_enforcement."""
    group = Group.objects.create(name=f"grp-{username}")
    content_type = ContentType.objects.get_for_model(Capability)
    for capability in capabilities:
        group.permissions.add(Permission.objects.get(content_type=content_type, codename=caps.codename_for(capability)))
    user = User.objects.create_user(username=username, password="x")
    user.groups.add(group)
    return CallerContext(user=user)


def _pin_enabled_at_before(schedule: Schedule, slot: datetime) -> None:
    """Pin `enabled_at` just before `slot` so a fixed-slot tick is deterministic
    (create_schedule stamps enabled_at to real wall-clock)."""
    Schedule.objects.filter(pk=schedule.pk).update(enabled_at=slot - timedelta(minutes=1))


@pytest.mark.django_db(transaction=True)
class TestNoAmbientActorSelfBinds:
    """Background boundaries bind a named program actor so their writes commit.

    The regression guard for the prod break (an unbound graph write fails closed at the
    backstop). Two shapes, both with the *task* owning the binding:
      - `run_collector` (the collection task) self-binds `tap_cares.collector` in its body.
      - the scheduler tick (`scheduler_tick` in task_backend) declares `tap_cares.scheduler`
        via `acting_as` and calls the *gated* `evaluate_tick`. Under the boundary convention
        `evaluate_tick` no longer self-binds its trigger — the caller must present an
        authorized actor (cares.run_scheduler), which the tick task does. The case below
        exercises that gated path with the scheduler bound, as the tick task binds it.
    """

    def test_run_collector_self_binds_collector(self, isolate_collector_registry):
        col = _collector()
        job_id = _make_ready_job(col)

        # Simulate the bare Steady Queue worker thread: no ambient actor at all.
        set_caller_context(None)
        run_collector.enqueue(str(col.entity_id), job_id)

        job = CollectionJob.objects.get(entity_id=job_id)
        # SUCCESSFUL is reachable only if every CollectionJob write (RUNNING →
        # terminal) committed — i.e. the task's `acting_as(COLLECTOR)` bound the
        # actor. Without that binding this path raised UnguardedOperation at the
        # first write and the job stayed READY.
        assert job.status == CollectionJobStatus.SUCCESSFUL
        assert HappyCollector.runs == [job_id]

    def test_scheduler_tick_runs_as_bound_scheduler(self, isolate_collector_registry):
        col = _collector()
        slot = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
        schedule = create_schedule(name="due-every-minute", cron_expression="* * * * *", collector=col)
        _pin_enabled_at_before(schedule, slot)

        # Option X (spec-service-layer-boundary): the tick task declares its identity
        # rather than the boundary inventing one. Bind tap_cares.scheduler exactly as
        # scheduler_tick does, then evaluate — its cares.run_scheduler gate authorizes that
        # actor and the writes commit as the scheduler.
        with acting_as(get_builtin_actor(SCHEDULER)):
            fires = evaluate_tick(now=slot)

        # A claimed fire (Schedule/ScheduleFire writes) AND a triggered collection are
        # produced only if the scheduler actor was bound, its cares.run_scheduler gate
        # passed, and the writes committed as that actor.
        assert len(fires) == 1
        fires[0].refresh_from_db()
        assert fires[0].status == ScheduleFireStatus.TRIGGERED
        assert CollectionJob.objects.count() == 1

    def test_scheduler_tick_denied_without_bound_actor(self, isolate_collector_registry):
        """The fail-closed dual: with no authorized actor, the gated tick is denied.

        This is the behavior the tick task's acting_as(SCHEDULER) exists to satisfy — the
        boundary no longer self-binds a trigger, so an unbound call is rejected up front
        (spec-service-layer-boundary req-service-boundary-contract-surface).
        """
        col = _collector()
        slot = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
        schedule = create_schedule(name="due-every-minute", cron_expression="* * * * *", collector=col)
        _pin_enabled_at_before(schedule, slot)

        set_caller_context(None)  # bare background thread: no ambient actor
        with pytest.raises(MissingActor):
            evaluate_tick(now=slot)


@pytest.mark.django_db(transaction=True)
class TestRunCollectionTriggerGate:
    """`run_collection` authorizes the triggering actor for cares.run_collectors
    before swapping to the tap_cares.collector execution identity."""

    def test_denies_trigger_without_cares_capability(self, isolate_collector_registry):
        col = _collector()
        before = CollectionJob.objects.count()

        # A triggering actor that holds no capabilities at all.
        set_caller_context(None)
        nobody = CallerContext(user=User.objects.create_user(username="nobody", password="x"))
        with pytest.raises(CapabilityDenied):
            run_collection(col, caller_context=nobody)

        # The gate fires before any CollectionJob is created (two decisions, never
        # collapsed): a denied trigger writes nothing.
        assert CollectionJob.objects.count() == before

    def test_allows_trigger_holding_only_cares_capability(self, isolate_collector_registry):
        col = _collector()

        # cares.run_collectors ALONE authorizes the trigger; the triggering actor
        # holds no grid capabilities of its own. The collection then runs as
        # tap_cares.collector (the swap), which supplies grid.write / import — so
        # the run still succeeds end-to-end. This is the bundle contract that lets
        # the scheduler and bootloader trigger collectors.
        set_caller_context(None)
        trigger = _ctx_with_caps("cares.run_collectors", username="runner")
        job = run_collection(col, caller_context=trigger)

        assert job.status == CollectionJobStatus.SUCCESSFUL
