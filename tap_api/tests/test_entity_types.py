"""Tests for EntityType API endpoint."""

import pytest

from tap_grid.models import EntityType, EntityTypeKind


@pytest.mark.django_db
class TestListEntityTypes:
    def test_returns_types(self, logged_in_client):
        EntityType.objects.create(slug="server", name="Server", plugin_name="infra")
        data = logged_in_client.get("/api/v1/entity-types/").json()
        assert len(data) >= 1
        slugs = [t["slug"] for t in data]
        assert "server" in slugs

    def test_empty(self, logged_in_client):
        EntityType.objects.all().delete()
        assert logged_in_client.get("/api/v1/entity-types/").json() == []

    def test_no_cap_denied_403(self, no_cap_client):
        """An authenticated caller without grid.read is denied the type catalog
        (finding cs-tap-api-typecat-003) — the catalog is graph metadata, so it is
        a graph read like any other. Authorization runs before the query."""
        EntityType.objects.create(slug="server", name="Server", plugin_name="infra")
        response = no_cap_client.get("/api/v1/entity-types/")
        assert response.status_code == 403
        assert response.json()["reason"] == "capability_denied"


@pytest.mark.django_db
class TestEntityTypeKind:
    """The node-vs-edge discriminator (req-grid-entity-type-kind).

    Both kinds belong in the catalog — edges ARE entities (req-grid-entity-spine) —
    so the fix for "the API lists edge types among entity types" is a discriminator
    a caller can read and filter on, not removing the edge rows.
    """

    @pytest.mark.spec("req-grid-entity-type-kind")
    def test_kind_is_exposed(self, logged_in_client):
        EntityType.objects.create(slug="server", name="Server", kind=EntityTypeKind.NODE)
        entry = next(t for t in logged_in_client.get("/api/v1/entity-types/").json() if t["slug"] == "server")
        assert entry["kind"] == "node"

    @pytest.mark.spec("req-grid-entity-type-kind")
    def test_filter_by_kind(self, logged_in_client):
        EntityType.objects.all().delete()
        EntityType.objects.create(slug="server", name="Server", kind=EntityTypeKind.NODE)
        EntityType.objects.create(slug="RUNS_ON", name="Runs On", kind=EntityTypeKind.EDGE)

        nodes = logged_in_client.get("/api/v1/entity-types/?kind=node").json()
        edges = logged_in_client.get("/api/v1/entity-types/?kind=edge").json()
        assert [t["slug"] for t in nodes] == ["server"]
        assert [t["slug"] for t in edges] == ["RUNS_ON"]
        # Unfiltered still returns both — the catalog is node types AND edge types.
        assert len(logged_in_client.get("/api/v1/entity-types/").json()) == 2

    @pytest.mark.spec("req-grid-entity-type-kind")
    def test_unknown_kind_returns_empty_not_everything(self, logged_in_client):
        # A typo'd filter must not silently fall back to the unfiltered catalog:
        # over-returning is the dangerous direction.
        EntityType.objects.create(slug="server", name="Server", kind=EntityTypeKind.NODE)
        assert logged_in_client.get("/api/v1/entity-types/?kind=nodes").json() == []

    @pytest.mark.spec("req-grid-entity-type-kind")
    def test_unclassified_rows_are_not_claimed_as_nodes(self, logged_in_client):
        # Rows written before the field existed keep "" until their writer next
        # runs; a consumer must be able to tell that apart from a known node.
        EntityType.objects.create(slug="legacy", name="Legacy")
        entry = next(t for t in logged_in_client.get("/api/v1/entity-types/").json() if t["slug"] == "legacy")
        assert entry["kind"] == ""
        assert logged_in_client.get("/api/v1/entity-types/?kind=node").json() == []
