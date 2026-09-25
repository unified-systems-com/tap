"""The harness's batch scope must not stand in for a production caller's.

`default_caller_context` binds every test a batch id and label, so a production caller
exercised by a test could pass on the harness's scope and be refused in production
(req-grid-service-batch-label-required). `_HarnessLabelAudit` traces each write that
relies on that scope to its caller and fails the test when the caller is production
code. These tests prove it catches one, and that test code and labelled production
code are not flagged.
"""

from __future__ import annotations

import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tap.pytest_harness import HARNESS_LABEL_AUDIT
from tap_grid.services import create_node


def _write(name: str, **labels: Any) -> Any:
    return create_node("grid_fixtures__constrained_source", {"name": name}, **labels)


def _probe(request: pytest.FixtureRequest, relative_path: str) -> Callable[..., Any]:
    """`_write`, re-homed as if it lived at `relative_path` under the rootdir.

    The audit classifies a caller by its code object's filename, so the same function
    body with a production filename stands in for real production code without adding
    a module to the tree (and without evaluating any source text).
    """
    path = Path(str(request.config.rootpath)) / relative_path
    module = relative_path.removesuffix(".py").replace("/", ".")
    code = _write.__code__.replace(co_filename=str(path))
    return types.FunctionType(code, {"__name__": module, "create_node": create_node}, "write")


@pytest.mark.django_db
@pytest.mark.spec("req-grid-service-batch-label-required-7")
class TestHarnessLabelAudit:
    def test_a_production_caller_relying_on_the_harness_scope_is_caught(self, request):
        audit = request.node.stash[HARNESS_LABEL_AUDIT]
        probe = _probe(request, "tap_grid/_label_audit_probe.py")

        assert probe("Frodo").success  # succeeds only on the harness's scope
        assert [v.split(":")[0] for v in audit.violations] == ["tap_grid/_label_audit_probe.py"]
        audit.violations.clear()  # the catch is the assertion; don't fail this test on it

    @pytest.mark.parametrize(
        "supplied",
        [{"batch_name": "name only"}, {"batch_description": "description only"}],
        ids=["name-only", "description-only"],
    )
    def test_a_production_caller_supplying_half_a_label_is_caught(self, request, supplied):
        """Supplying one field and inheriting the other from the harness still relies on it:
        in production the missing half is absent and the write is refused."""
        import uuid

        from tap_grid.caller_context import CallerContext, get_caller_context

        audit = request.node.stash[HARNESS_LABEL_AUDIT]
        probe = _probe(request, "tap_grid/_label_audit_probe.py")
        bound = get_caller_context()
        assert bound is not None
        fresh = CallerContext(user=bound.user, batch_id=str(uuid.uuid7()))

        assert probe("Pippin", caller_context=fresh, **supplied).success  # the other half is the harness's
        assert [v.split(":")[0] for v in audit.violations] == ["tap_grid/_label_audit_probe.py"]
        audit.violations.clear()

    def test_a_production_caller_that_labels_its_write_is_not_flagged(self, request):
        import uuid

        from tap_grid.caller_context import CallerContext, get_caller_context

        audit = request.node.stash[HARNESS_LABEL_AUDIT]
        probe = _probe(request, "tap_grid/_label_audit_probe.py")
        bound = get_caller_context()
        assert bound is not None
        user = bound.user
        result = probe(
            "Sam",
            caller_context=CallerContext(user=user, batch_id=str(uuid.uuid7())),
            batch_name="probe",
            batch_description="a labelled production write",
        )
        assert result.success
        assert audit.violations == []

    def test_test_code_may_rely_on_the_harness_scope(self, request):
        audit = request.node.stash[HARNESS_LABEL_AUDIT]
        assert create_node("grid_fixtures__constrained_source", {"name": "Merry"}).success
        assert audit.violations == []

    def test_code_outside_the_rootdir_is_not_this_repositorys_to_audit(self, request):
        audit = request.node.stash[HARNESS_LABEL_AUDIT]
        assert not audit.is_production(Path("/usr/lib/python3/site-packages/tap_plugin/x/runner.py"))
        assert not audit.is_production(audit.rootpath / "tap_grid" / "tests" / "test_x.py")
        assert audit.is_production(audit.rootpath / "tap_grid" / "reconcile.py")
