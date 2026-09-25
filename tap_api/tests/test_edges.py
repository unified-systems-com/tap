"""Tests for Edge API endpoints."""

import json
import uuid

import pytest

# Import models to trigger constraint registration via __init_subclass__
import tap_plugin.grid_fixtures.models  # noqa: F401

from tap_grid.models import Edge
from tap_grid.services import create_edge, create_entity

# What each create request says the change is (req-grid-service-batch-label-required-6).
LABEL = {"batch_name": "API test edge", "batch_description": "Created by a tap_api edge test."}


@pytest.fixture
def two_entities():
    """Create character and location entities for testing valid edges."""
    a = create_entity("grid_fixtures__constrained_source", name="Frodo")
    b = create_entity("grid_fixtures__constrained_target", name="Mordor")
    return a, b


@pytest.fixture
def unconstrained_entities():
    """Create entities without constraint definitions for testing."""
    a = create_entity("unconstrained_a", name="A")
    b = create_entity("unconstrained_b", name="B")
    return a, b


@pytest.mark.django_db
class TestListEdges:
    def test_returns_200(self, logged_in_client):
        response = logged_in_client.get("/api/v1/edges/")
        assert response.status_code == 200

    def test_returns_created_edge(self, logged_in_client, unconstrained_entities):
        a, b = unconstrained_entities
        edge = create_edge(a, b, "DEPENDS_ON")
        data = logged_in_client.get("/api/v1/edges/").json()
        found = [e for e in data if e["entity_id"] == str(edge.entity_id)]
        assert len(found) == 1
        assert found[0]["edge_type"] == "DEPENDS_ON"

    def test_filter_by_from(self, logged_in_client, unconstrained_entities):
        a, b = unconstrained_entities
        edge = create_edge(a, b, "DEPENDS_ON")
        data = logged_in_client.get(f"/api/v1/edges/?from_entity_id={a.pk}").json()
        found = [e for e in data if e["entity_id"] == str(edge.entity_id)]
        assert len(found) == 1

    def test_filter_by_type(self, logged_in_client, unconstrained_entities):
        a, b = unconstrained_entities
        edge = create_edge(a, b, "DEPENDS_ON")
        create_edge(b, a, "APPLIES_TO")
        data = logged_in_client.get("/api/v1/edges/?edge_type=DEPENDS_ON").json()
        found = [e for e in data if e["entity_id"] == str(edge.entity_id)]
        assert len(found) == 1

    def test_pagination_bounds_rejected(self, logged_in_client):
        """Same negative-slice 500 class as list_entities (authenticated
        api-fuzz finding, 2026-08-10); out-of-range values are a 422."""
        assert logged_in_client.get("/api/v1/edges/?limit=-5").status_code == 422
        assert logged_in_client.get("/api/v1/edges/?offset=-5").status_code == 422
        assert logged_in_client.get("/api/v1/edges/?limit=1001").status_code == 422
        assert logged_in_client.get(f"/api/v1/edges/?offset={10**33}").status_code == 422


@pytest.mark.django_db
class TestGetEdge:
    def test_found(self, logged_in_client, two_entities):
        a, b = two_entities
        edge = create_edge(a, b, "CONSTRAINED_LINK__grid_fixtures")
        data = logged_in_client.get(f"/api/v1/edges/{edge.entity_id}/").json()
        assert data["edge_type"] == "CONSTRAINED_LINK__grid_fixtures"
        assert data["entity_id"] == str(edge.entity_id)

    def test_not_found(self, logged_in_client):
        response = logged_in_client.get(f"/api/v1/edges/{uuid.uuid4()}/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestCreateEdge:
    def test_create(self, logged_in_client, two_entities):
        a, b = two_entities
        response = logged_in_client.post(
            "/api/v1/edges/",
            data=json.dumps(
                {
                    "from_entity_id": str(a.pk),
                    "to_entity_id": str(b.pk),
                    "edge_type": "CONSTRAINED_LINK__grid_fixtures",
                    "properties": {"weight": 0.9},
                    **LABEL,
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 201
        data = response.json()
        assert data["edge_type"] == "CONSTRAINED_LINK__grid_fixtures"
        assert data["properties"] == {"weight": 0.9}

    def test_invalid_entity_404(self, logged_in_client):
        response = logged_in_client.post(
            "/api/v1/edges/",
            data=json.dumps(
                {
                    "from_entity_id": str(uuid.uuid4()),
                    "to_entity_id": str(uuid.uuid4()),
                    "edge_type": "CONSTRAINED_LINK__grid_fixtures",
                    **LABEL,
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 404

    def test_constraint_violation_returns_400(self, logged_in_client, two_entities):
        """Invalid edge type for character -> location returns 400."""
        a, b = two_entities  # character, location
        response = logged_in_client.post(
            "/api/v1/edges/",
            data=json.dumps(
                {
                    "from_entity_id": str(a.pk),
                    "to_entity_id": str(b.pk),
                    "edge_type": "INVALID_EDGE_TYPE",
                    **LABEL,
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "cannot create 'INVALID_EDGE_TYPE'" in data["detail"]


    @pytest.mark.spec("req-grid-service-batch-label-required-6")
    @pytest.mark.parametrize("missing", ["batch_name", "batch_description"])
    def test_a_request_without_a_batch_label_is_rejected(self, logged_in_client, two_entities, missing):
        a, b = two_entities
        body = {
            "from_entity_id": str(a.pk),
            "to_entity_id": str(b.pk),
            "edge_type": "CONSTRAINED_LINK__grid_fixtures",
            **{k: v for k, v in LABEL.items() if k != missing},
        }
        before = Edge.objects.count()
        response = logged_in_client.post("/api/v1/edges/", data=json.dumps(body), content_type="application/json")

        assert response.status_code == 422
        assert Edge.objects.count() == before

    @pytest.mark.spec("req-grid-service-batch-label-required-6")
    def test_the_request_label_names_the_minted_batch(self, logged_in_client, two_entities):
        from tap_grid.batch import get_entity_batches

        a, b = two_entities
        response = logged_in_client.post(
            "/api/v1/edges/",
            data=json.dumps(
                {
                    "from_entity_id": str(a.pk),
                    "to_entity_id": str(b.pk),
                    "edge_type": "CONSTRAINED_LINK__grid_fixtures",
                    **LABEL,
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 201
        batches = get_entity_batches(response.json()["entity_id"])
        assert [(x.name, x.description) for x in batches] == [(LABEL["batch_name"], LABEL["batch_description"])]


@pytest.mark.django_db
class TestDeleteEdge:
    def test_delete(self, logged_in_client, two_entities):
        a, b = two_entities
        edge = create_edge(a, b, "CONSTRAINED_LINK__grid_fixtures")
        response = logged_in_client.delete(f"/api/v1/edges/{edge.entity_id}/")
        assert response.status_code == 204
        assert not Edge.objects.filter(pk=edge.pk).exists()

    def test_not_found(self, logged_in_client):
        response = logged_in_client.delete(f"/api/v1/edges/{uuid.uuid4()}/")
        assert response.status_code == 404
