"""Edge authority through a real collection run: the run is the claim's read boundary, and the job
result counts what the claims would remove.

Spec: ``req-grid-reconcile-edge-authority`` (``-7``, ``-8``) in ``tap_grid/specs/spec-grid-reconcile.md``
(Issue# 919 - tap). The importer's own behaviour is ``tap_grid/tests/test_grift_edge_authority.py``;
this proves the boundary it reads is the one ``run_collection`` binds, the run's lifecycle batch.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

import pytest

from tap_cares.collectors import CollectorBase
from tap_cares.models import CollectionJobStatus, Collector
from tap_cares.registry import reconcile_collector_nodes, register_collector
from tap_cares.services import run_collection
from tap_grid.grift import grift_import
from tap_grid.models import BatchEvent, BatchEventType
from tap_grid.tests.test_grift import _batch_container, _minimal_doc

LINK = "PG_LINKS__grid_fixtures"


def _node(entity_id: str) -> dict[str, Any]:
    return {
        "entity": {"entity_id": entity_id, "entity_type": "grid_fixtures__node", "name": "n", "dimensions": {}},
        "node": {"name": "n", "description": ""},
    }


def _edge(edge_id: str, source: str, target: str) -> dict[str, Any]:
    return {
        "entity": {"entity_id": edge_id, "entity_type": "edge", "dimensions": {}},
        "edge": {"edge_type": LINK, "from_entity_id": source, "to_entity_id": target, "properties": {}},
    }


class ClaimsTheHub(CollectorBase):
    """Re-sends hub -> b and claims hub's outbound LINK edges are total, so hub -> c is proposed."""

    IDS: ClassVar[dict[str, str]] = {}

    def run(self) -> None:
        ids = self.IDS
        container = _batch_container(str(uuid.uuid4()), edges=[_edge(ids["hub_b"], ids["hub"], ids["b"])])
        container["edge_cases"] = {
            "authority": [
                {"edge_type": LINK, "anchor": {"entity_id": ids["hub"]}, "direction": "outbound", "read": "complete"}
            ]
        }
        self.submit_grift(_minimal_doc([container]))


@pytest.mark.django_db(transaction=True)
class TestAClaimInARun:
    @pytest.mark.spec("req-grid-reconcile-edge-authority-7")
    @pytest.mark.spec("req-grid-reconcile-edge-authority-8")
    def test_the_run_is_the_boundary_and_the_job_counts_the_proposals(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ids = {name: str(uuid.uuid4()) for name in ("hub", "b", "c", "hub_b", "hub_c")}
        seeded = grift_import(
            _minimal_doc(
                [
                    _batch_container(
                        str(uuid.uuid4()),
                        nodes=[_node(ids["hub"]), _node(ids["b"]), _node(ids["c"])],
                        edges=[_edge(ids["hub_b"], ids["hub"], ids["b"]), _edge(ids["hub_c"], ids["hub"], ids["c"])],
                    )
                ]
            )
        )
        assert seeded.success, seeded.errors
        monkeypatch.setattr(ClaimsTheHub, "IDS", ids)
        register_collector(
            key="claims-hub", cls=ClaimsTheHub, scope="tap_cares.tests.authority", name="fixture", description="fixture"
        )
        reconcile_collector_nodes()
        collector = Collector.objects.get(collector_registry="tap_cares.tests.authority:claims-hub")
        assert isinstance(collector, Collector)

        job = run_collection(collector)
        job.refresh_from_db()

        assert job.status == CollectionJobStatus.SUCCESSFUL.value, job.summary
        (record,) = [e for e in job.results["info"] if e["message_code"] == "EDGE_AUTHORITY_PROPOSED"]
        assert record["message_data"]["proposed"] == 1
        (claim,) = record["message_data"]["claim_records"]
        assert (claim["outcome"], claim["reason"]) == ("claimed", None), "the run supplied the read boundary"
        (proposal,) = BatchEvent.objects.filter(event_type=BatchEventType.AUTHORITY_PROPOSED, entity_type="edge")
        assert (str(proposal.entity_id), proposal.metadata["outcome"]) == (ids["hub_c"], "proposed")


class DeclaresAndClaims(CollectorBase):
    """Declares no listing surface, as aws_core does, so the run reaches its reconcile phase; re-sends
    the edges named in ``KEEP`` and claims hub's outbound LINK edges are total."""

    IDS: ClassVar[dict[str, str]] = {}
    KEEP: ClassVar[list[str]] = []

    def run(self) -> None:
        self.declare_no_surfaces()
        ids = self.IDS
        edges = [_edge(ids[f"hub_{t}"], ids["hub"], ids[t]) for t in self.KEEP]
        container = _batch_container(str(uuid.uuid4()), edges=edges)
        container["edge_cases"] = {
            "authority": [
                {"edge_type": LINK, "anchor": {"entity_id": ids["hub"]}, "direction": "outbound", "read": "complete"}
            ]
        }
        self.submit_grift(_minimal_doc([container]))


REGISTRY = "tap_cares.tests.authority:declares-and-claims"


def _hub(targets: int) -> dict[str, str]:
    """``hub`` with LINK edges out to ``t0`` .. ``t{targets-1}``, written before any run opens."""
    names = [f"t{i}" for i in range(targets)]
    ids = {name: str(uuid.uuid4()) for name in ["hub", *names, *(f"hub_{n}" for n in names)]}
    seeded = grift_import(
        _minimal_doc(
            [
                _batch_container(
                    str(uuid.uuid4()),
                    nodes=[_node(ids["hub"]), *(_node(ids[n]) for n in names)],
                    edges=[_edge(ids[f"hub_{n}"], ids["hub"], ids[n]) for n in names],
                )
            ]
        )
    )
    assert seeded.success, seeded.errors
    return ids


def _collect(ids: dict[str, str], keep: list[str], monkeypatch: pytest.MonkeyPatch, *, armed: bool) -> Any:
    """Run the collector once, armed or not, and return its job."""
    from tap_cares.services import arm_reconcile

    monkeypatch.setattr(DeclaresAndClaims, "IDS", ids)
    monkeypatch.setattr(DeclaresAndClaims, "KEEP", keep)
    register_collector(
        key="declares-and-claims",
        cls=DeclaresAndClaims,
        scope="tap_cares.tests.authority",
        name="fixture",
        description="fixture",
    )
    reconcile_collector_nodes()
    if armed:
        arm_reconcile(REGISTRY, authority=True)
    job = run_collection(Collector.objects.get(collector_registry=REGISTRY))
    job.refresh_from_db()
    assert job.status == CollectionJobStatus.SUCCESSFUL.value, job.summary
    return job


def _edge_record(job: Any) -> dict[str, Any]:
    from tap_cares.tests.test_completeness_flow import _lifecycle_batch
    from tap_grid.falsifiers import verdicts_of
    from tap_grid.reconcile import EDGE_AUTHORITY_KEY

    record = verdicts_of(_lifecycle_batch(job))
    assert record is not None, "the run reached its reconcile phase"
    edge: dict[str, Any] = record[EDGE_AUTHORITY_KEY]
    return edge


def _live(edge_id: str) -> bool:
    from tap_grid.models import Entity

    return Entity.objects.filter(pk=uuid.UUID(edge_id), deleted_at__isnull=True).exists()


@pytest.mark.django_db(transaction=True)
class TestArmedRuns:
    @pytest.mark.spec("req-grid-reconcile-edge-authority-9")
    @pytest.mark.spec("req-grid-reconcile-edge-authority-12")
    def test_an_armed_run_removes_what_its_claim_proposed(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ids = _hub(2)
        job = _collect(ids, ["t0"], monkeypatch, armed=True)
        assert _live(ids["hub_t0"]) and not _live(ids["hub_t1"])
        unlink = BatchEvent.objects.get(entity_id=uuid.UUID(ids["hub_t1"]), event_type=BatchEventType.UNLINK)
        assert unlink.metadata["reason"] == "authority"
        edge = _edge_record(job)
        assert (edge["authority"], edge["counts"]["applied"]) == ("on", 1)
        (applied,) = [e for e in job.results["info"] if e["message_code"] == "EDGE_AUTHORITY_APPLIED"]
        assert applied["message_data"]["counts"]["applied"] == 1

    @pytest.mark.spec("req-grid-reconcile-edge-authority-9")
    def test_an_unarmed_run_removes_nothing_and_says_so(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ids = _hub(2)
        job = _collect(ids, ["t0"], monkeypatch, armed=False)
        assert _live(ids["hub_t0"]) and _live(ids["hub_t1"])
        assert not BatchEvent.objects.filter(entity_id=uuid.UUID(ids["hub_t1"]), event_type=BatchEventType.UNLINK).exists()
        edge = _edge_record(job)
        assert (edge["authority"], edge["unapplied"]) == ("off", 1)

    @pytest.mark.spec("req-grid-reconcile-edge-authority-13")
    def test_a_claim_that_would_empty_its_scope_is_held_and_the_job_says_how_to_release_it(
        self, isolate_collector_registry: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ids = _hub(3)
        job = _collect(ids, [], monkeypatch, armed=True)
        assert all(_live(ids[f"hub_t{i}"]) for i in range(3)), "a held claim removes nothing"
        edge = _edge_record(job)
        (held,) = edge["held_claims"]
        assert (held["in_scope"], edge["counts"]["held"], edge["counts"]["applied"]) == (3, 3, 0)
        (warning,) = [e for e in job.results["warn"] if e["message_code"] == "EDGE_AUTHORITY_HELD"]
        assert f"--claim {held['claim_event_id']}" in warning["message"]
        applied = [e for e in job.results.get("info", []) if e["message_code"] == "EDGE_AUTHORITY_APPLIED"]
        assert applied == [], "a run whose only outcome is a hold applied nothing, and does not say it did"
