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
from tap_cares.tests.test_arm_reconcile import _operator
from tap_cares.tests.test_completeness_flow import _lifecycle_batch
from tap_cares.tests.test_edge_authority_run import _collect, _edge, _edge_record, _hub, _live
from tap_grid.grift import grift_import
from tap_grid.models import BatchEvent, BatchEventType
from tap_grid.services import release_edge_authority_hold
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
        """Refused at tap_grid's own service boundary, even inside the program's grid.reconcile authority."""
        from tap_auth.capabilities import RECONCILE_CAPABILITY
        from tap_auth.enforcement import authorized
        from tap_grid.caller_context import CallerContext

        ids, job = _held(monkeypatch)
        program = get_builtin_actor(COLLECTOR)
        with (
            acting_as(program),
            authorized(CallerContext(user=program), RECONCILE_CAPABILITY, operation="test.release_as_the_program"),
            pytest.raises(CapabilityDenied),
        ):
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


class TestSupersession:
    @SPEC
    def test_a_later_complete_read_of_the_scope_supersedes_the_hold(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A second armed run reads the same scope, empty again, and holds again: the first hold can no
        longer be released, and names the claim that superseded it; the newer hold still can be."""
        from tap_cares.models import Collector
        from tap_cares.services import run_collection
        from tap_cares.tests.test_edge_authority_run import REGISTRY

        ids, first = _held(monkeypatch)
        second = run_collection(Collector.objects.get(collector_registry=REGISTRY))
        second.refresh_from_db()
        (newer,) = _edge_record(second)["held_claims"]
        result = release_edge_authority_hold(str(_lifecycle_batch(first).entity_id))
        assert result["released_claims"] == [] and len(result["superseded_claims"]) == 1
        assert all(_live(ids[f"hub_t{i}"]) for i in range(3)), "nothing removed on the older read"
        (old,) = _edge_record(first)["held_claims"]
        assert old["superseded_by"] == newer["claim_event_id"] and old["released"] is None
        newest = release_edge_authority_hold(str(_lifecycle_batch(second).entity_id))
        assert newest["counts"]["applied"] == 3 and not any(_live(ids[f"hub_t{i}"]) for i in range(3))


class TestSupersessionRace:
    @SPEC
    def test_a_newer_claim_still_being_written_is_waited_for(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A newer complete claim over the scope is mid-transaction, its anchor locked, when the release
        starts. The release waits for it, sees it, and releases nothing under the older read."""
        import contextvars
        import threading

        import tap_grid.grift.importer as importer_module
        from tap_cares.tests.test_edge_authority_run import LINK
        from tap_grid.batch import create_batch
        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.cascade_corpus.timing import JOIN_SECONDS, finish, in_thread, wait_until_blocked_by
        from tap_grid.reconcile import RUN_CONFIG_KEY, run_config

        ids, job = _held(monkeypatch)
        run_id = str(_lifecycle_batch(job).entity_id)
        operator: Any = _operator("cares.arm_reconcile")
        pause: contextvars.ContextVar[bool] = contextvars.ContextVar("pause", default=False)
        paused, go = threading.Event(), threading.Event()
        real = importer_module._apply_authority_claims

        def holding(*args: Any, **kwargs: Any) -> Any:
            # The newer claim is recorded, its anchor and scope locked, its batch not yet committed.
            out = real(*args, **kwargs)
            if pause.get():
                paused.set()
                assert go.wait(JOIN_SECONDS)
            return out

        monkeypatch.setattr(importer_module, "_apply_authority_claims", holding)
        newer_run = create_batch(
            source="t:newer-run",
            name="newer run",
            description="a later read of the same scope",
            metadata={RUN_CONFIG_KEY: run_config(authority=False, budget=None, collector="test")},
        )

        def newer_claim() -> Any:
            pause.set(True)
            ambient = get_caller_context()
            set_caller_context(CallerContext(user=ambient.user if ambient else None, batch_id=str(newer_run.entity_id)))
            container = _batch_container(str(uuid.uuid4()))
            container["edge_cases"] = {
                "authority": [
                    {"edge_type": LINK, "anchor": {"entity_id": ids["hub"]}, "direction": "outbound", "read": "complete"}
                ]
            }
            return grift_import(_minimal_doc([container]))

        def release() -> Any:
            with acting_as(operator):
                return release_edge_authority_hold(run_id)

        n = in_thread(newer_claim)
        assert paused.wait(JOIN_SECONDS)
        r = in_thread(release)
        wait_until_blocked_by(r[1], n[1])
        go.set()
        finish(n, r)
        assert n[1].value.success, n[1].value.errors
        assert r[1].value["released_claims"] == [] and len(r[1].value["superseded_claims"]) == 1
        assert all(_live(ids[f"hub_t{i}"]) for i in range(3)), "nothing removed under the older read"


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
