"""The operator arming switch (Issue# 655 - tap; req-tap-cares-collector-model-11)."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO
from typing import cast

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError

from tap_auth import capabilities as caps
from tap_auth.errors import CapabilityDenied
from tap_auth.models import Capability
from tap_cares.exceptions import CollectorNotFoundError
from tap_cares.models import Collector
from tap_cares.services import ARM_RECONCILE_AUDIT_KEY, ARM_RECONCILE_BATCH_SOURCE, arm_reconcile
from tap_grid.models import Batch, BatchStatus
from tap_grid.reconcile import ReconcileError, run_config_of
from tap_grid.tests.test_read_guard import _viewer_ctx

pytestmark = pytest.mark.django_db

REGISTRY = "tap_cares.tests.arm:switch"


@pytest.fixture
def collector() -> Collector:
    from django.core.exceptions import ImproperlyConfigured

    from tap_cares.registry import reconcile_collector_nodes, register_collector
    from tap_cares.tests.test_completeness_flow import SurfaceCollector

    try:  # the registry is process-global; the node is per test (the DB rolls back)
        register_collector(
            key="switch", cls=SurfaceCollector, scope="tap_cares.tests.arm", name="switch", description="x"
        )
    except ImproperlyConfigured:
        pass
    reconcile_collector_nodes()
    return cast(Collector, Collector.objects.get(collector_registry=REGISTRY))


def _operator(*capability_names: str) -> object:
    """A human holding exactly the named capabilities."""
    user = get_user_model().objects.create_user(username="ops-" + "-".join(c.split(".")[-1] for c in capability_names))
    group = Group.objects.create(name=f"grp-{user.username}")
    content_type = ContentType.objects.get_for_model(Capability)
    for name in capability_names:
        group.permissions.add(Permission.objects.get(content_type=content_type, codename=caps.codename_for(name)))
    user.groups.add(group)
    return user


class TestTheVerb:
    def test_arming_sets_the_fields_and_writes_an_audit_batch_the_next_run_reads(self, collector: Collector) -> None:
        from tap_auth.actors import COLLECTOR, get_builtin_actor
        from tap_cares.services import _open_lifecycle_batch, _reconcile_config
        from tap_grid.caller_context import CallerContext

        assert collector.reconcile_authority is False and collector.reconcile_budget is None
        record = arm_reconcile(REGISTRY, authority=True, budget=5)

        collector.refresh_from_db()
        assert collector.reconcile_authority is True and collector.reconcile_budget == 5
        assert record["before"] == {"authority": False, "budget": None}
        assert record["after"] == {"authority": True, "budget": 5}
        audit = Batch.objects.get(entity_id=record["batch"])
        assert audit.source == ARM_RECONCILE_BATCH_SOURCE and audit.status == BatchStatus.CLOSED
        assert audit.metadata[ARM_RECONCILE_AUDIT_KEY]["collector"] == REGISTRY
        assert audit.metadata[ARM_RECONCILE_AUDIT_KEY]["operator"] == record["operator"]
        assert audit.metadata[ARM_RECONCILE_AUDIT_KEY]["after"] == {"authority": True, "budget": 5}
        # the next run's lifecycle batch carries it, and the verb reads it from there
        config = _reconcile_config(collector)
        ctx = CallerContext(user=get_builtin_actor(COLLECTOR))
        run = _open_lifecycle_batch("switch", datetime.now(UTC), ctx, reconcile=config)
        assert run_config_of(run) == {"authority": True, "budget": 5, "collector": str(collector.entity_id)}

    def test_disarming_turns_it_off_and_clears_the_budget(self, collector: Collector) -> None:
        arm_reconcile(REGISTRY, authority=True, budget=5)
        record = arm_reconcile(REGISTRY, authority=False)
        collector.refresh_from_db()
        assert collector.reconcile_authority is False and collector.reconcile_budget is None
        assert record["before"] == {"authority": True, "budget": 5}
        assert Batch.objects.filter(source=ARM_RECONCILE_BATCH_SOURCE).count() == 2

    def test_an_actor_without_the_capability_is_refused_and_nothing_changes(self, collector: Collector) -> None:
        with pytest.raises(CapabilityDenied):
            arm_reconcile(REGISTRY, authority=True, budget=5, caller_context=_viewer_ctx())
        collector.refresh_from_db()
        assert collector.reconcile_authority is False
        assert not Batch.objects.filter(source=ARM_RECONCILE_BATCH_SOURCE).exists()

    def test_a_bad_budget_is_refused_before_any_write(self, collector: Collector) -> None:
        with pytest.raises(ReconcileError) as excinfo:
            arm_reconcile(REGISTRY, authority=True, budget=-1)
        assert excinfo.value.code == "invalid_config"
        collector.refresh_from_db()
        assert collector.reconcile_authority is False
        assert not Batch.objects.filter(source=ARM_RECONCILE_BATCH_SOURCE).exists()

    def test_an_unknown_collector_is_refused(self) -> None:
        with pytest.raises(CollectorNotFoundError):
            arm_reconcile("nowhere:nothing", authority=True)


class TestTheCommand:
    def test_the_command_arms_and_disarms_as_the_named_operator(self, collector: Collector) -> None:
        operator = _operator("cares.arm_reconcile")
        out = StringIO()
        call_command("arm_reconcile", REGISTRY, "--on", "--budget", "7", "--as", operator.username, stdout=out)  # type: ignore[attr-defined]
        collector.refresh_from_db()
        assert collector.reconcile_authority is True and collector.reconcile_budget == 7
        assert "ON" in out.getvalue() and operator.username in out.getvalue()  # type: ignore[attr-defined]
        audit = Batch.objects.get(source=ARM_RECONCILE_BATCH_SOURCE)
        assert audit.metadata[ARM_RECONCILE_AUDIT_KEY]["operator"] == operator.username  # type: ignore[attr-defined]

        call_command("arm_reconcile", REGISTRY, "--off", "--as", operator.username, stdout=StringIO())  # type: ignore[attr-defined]
        collector.refresh_from_db()
        assert collector.reconcile_authority is False and collector.reconcile_budget is None

    def test_the_command_refuses_a_user_without_the_capability(self, collector: Collector) -> None:
        bystander = _operator("grid.read")
        with pytest.raises(CommandError, match="refused"):
            call_command("arm_reconcile", REGISTRY, "--on", "--as", bystander.username, stdout=StringIO())  # type: ignore[attr-defined]
        collector.refresh_from_db()
        assert collector.reconcile_authority is False

    def test_the_command_names_an_unknown_user(self) -> None:
        with pytest.raises(CommandError, match="no user"):
            call_command("arm_reconcile", REGISTRY, "--on", "--as", "nobody", stdout=StringIO())
