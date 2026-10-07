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
