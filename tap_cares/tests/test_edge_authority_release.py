"""Releasing a held edge-authority claim: the operator's decision, never the run's (Issue# 920 - tap).

Spec: ``req-grid-reconcile-edge-authority-14`` in ``tap_grid/specs/spec-grid-reconcile.md``. A real
armed run holds a claim that asserted none of a three-edge scope
(``test_edge_authority_run.py``); these release it. The operator is gated on
``cares.arm_reconcile``, which the collector program actor does not hold, though it holds
``grid.reconcile``.
"""

from __future__ import annotations

import uuid
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from tap_auth.actors import COLLECTOR, acting_as, get_builtin_actor
from tap_auth.errors import CapabilityDenied
from tap_cares.services import release_edge_authority_hold
from tap_cares.tests.test_arm_reconcile import _operator
from tap_cares.tests.test_completeness_flow import _lifecycle_batch
from tap_cares.tests.test_edge_authority_run import _collect, _edge, _edge_record, _hub, _live
from tap_grid.grift import grift_import
from tap_grid.models import BatchEvent, BatchEventType
from tap_grid.tests.test_grift import _batch_container, _minimal_doc

SPEC = pytest.mark.spec("req-grid-reconcile-edge-authority-14")

pytestmark = pytest.mark.django_db(transaction=True)


def _held(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[str, str], Any]:
    """A run whose one claim asserted none of hub's three LINK edges: held, nothing removed."""
    ids = _hub(3)
    job = _collect(ids, [], monkeypatch, armed=True)
    assert len(_edge_record(job)["held_claims"]) == 1
    return ids, job


class TestTheRelease:
    @SPEC
    def test_an_operator_releases_a_hold_and_the_record_says_who(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ids, job = _held(monkeypatch)
        run = _lifecycle_batch(job)
        result = release_edge_authority_hold(str(run.entity_id))
        assert len(result["released_claims"]) == 1 and result["counts"]["applied"] == 3
        assert not any(_live(ids[f"hub_t{i}"]) for i in range(3))
        unlink = BatchEvent.objects.get(entity_id=uuid.UUID(ids["hub_t0"]), event_type=BatchEventType.UNLINK)
        assert unlink.metadata["reason"] == "authority"
        assert unlink.metadata["edge_authority"]["released_by"]["operator"] == result["released_by"]["operator"]
        edge = _edge_record(job)
        (claim,) = edge["held_claims"]
        assert claim["released"]["operator"] == result["released_by"]["operator"] and claim["released"]["at"]
        assert (edge["counts"]["held"], edge["counts"]["applied"]) == (0, 3)

    @SPEC
    def test_a_released_hold_releases_nothing_again(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _ids, job = _held(monkeypatch)
        run_id = str(_lifecycle_batch(job).entity_id)
        release_edge_authority_hold(run_id)
        again = release_edge_authority_hold(run_id)
        assert again["released_claims"] == [] and not any(again["counts"].values())

    @SPEC
    def test_the_collector_program_cannot_release_its_own_hold(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ids, job = _held(monkeypatch)
        program = get_builtin_actor(COLLECTOR)
        with acting_as(program), pytest.raises(CapabilityDenied):
            release_edge_authority_hold(str(_lifecycle_batch(job).entity_id))
        assert all(_live(ids[f"hub_t{i}"]) for i in range(3))

    @SPEC
    def test_a_release_is_fenced_again(self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        """An edge sent again after the claim's read is not removed by the release."""
        ids, job = _held(monkeypatch)
        again = grift_import(_minimal_doc([_batch_container(str(uuid.uuid4()), edges=[_edge(ids["hub_t0"], ids["hub"], ids["t0"])])]))
        assert again.success, again.errors
        result = release_edge_authority_hold(str(_lifecycle_batch(job).entity_id))
        assert (result["counts"]["rejected_stale"], result["counts"]["applied"]) == (1, 2)
        assert _live(ids["hub_t0"]) and not _live(ids["hub_t1"]) and not _live(ids["hub_t2"])


class TestTwoOperators:
    @SPEC
    def test_two_concurrent_releases_release_once_and_name_the_first(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The second release waits on the first's lock on the run, re-reads, and finds the claim
        released: the record and every unlink name the operator who released it."""
        import threading

        import tap_grid.reconcile as reconcile_module
        from tap_grid.cascade_corpus.timing import JOIN_SECONDS, finish, in_thread, wait_until_blocked_by

        ids, job = _held(monkeypatch)
        run_id = str(_lifecycle_batch(job).entity_id)
        first, second = _operator("cares.arm_reconcile"), _operator("cares.arm_reconcile", "grid.read")
        first_name = first.username  # type: ignore[attr-defined]
        inside, go = threading.Event(), threading.Event()
        real = reconcile_module._apply_proposal

        def paused(*args: Any, **kwargs: Any) -> Any:
            # Hold the first release inside its transaction, past its read of the record.
            if kwargs["released_by"]["operator"] == first_name and not inside.is_set():
                inside.set()
                assert go.wait(JOIN_SECONDS)
            return real(*args, **kwargs)

        monkeypatch.setattr(reconcile_module, "_apply_proposal", paused)

        def release_as(operator: Any) -> Any:
            with acting_as(operator):
                return release_edge_authority_hold(run_id)

        a = in_thread(lambda: release_as(first))
        assert inside.wait(JOIN_SECONDS)
        b = in_thread(lambda: release_as(second))
        wait_until_blocked_by(b[1], a[1])
        go.set()
        finish(a, b)
        assert len(a[1].value["released_claims"]) == 1 and a[1].value["counts"]["applied"] == 3
        assert b[1].value["released_claims"] == [], "the second release found nothing still held"
        (claim,) = _edge_record(job)["held_claims"]
        assert claim["released"]["operator"] == first_name
        unlinks = BatchEvent.objects.filter(event_type=BatchEventType.UNLINK, entity_id__in=[uuid.UUID(ids[f"hub_t{i}"]) for i in range(3)])
        assert {u.metadata["edge_authority"]["released_by"]["operator"] for u in unlinks} == {first_name}


class TestTheCommand:
    @SPEC
    def test_the_command_releases_as_the_named_operator(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ids, job = _held(monkeypatch)
        run_id = str(_lifecycle_batch(job).entity_id)
        operator = _operator("cares.arm_reconcile")
        out = StringIO()
        call_command("release_edge_authority_hold", run_id, "--as", operator.username, stdout=out)  # type: ignore[attr-defined]
        assert "released 1 claim(s)" in out.getvalue() and "3 removed" in out.getvalue()
        assert not any(_live(ids[f"hub_t{i}"]) for i in range(3))

    @SPEC
    def test_the_command_refuses_a_user_without_the_arming_permission(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ids, job = _held(monkeypatch)
        bystander = _operator("grid.reconcile")
        name = bystander.username  # type: ignore[attr-defined]
        run_id = str(_lifecycle_batch(job).entity_id)
        with pytest.raises(CommandError, match="refused"):
            call_command("release_edge_authority_hold", run_id, "--as", name, stdout=StringIO())
        assert all(_live(ids[f"hub_t{i}"]) for i in range(3))
