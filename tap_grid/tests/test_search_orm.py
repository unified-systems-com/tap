"""Tests for ORM search execution mode — req-grid-search-orm."""

import pytest

from tap_grid.exceptions import InvalidSearchDefinitionError
from tap_grid.models import Edge, Search
from tap_grid.orm_compiler import compile_orm_query
from tap_grid.search import execute_search


def _orm_search(**kwargs):
    defaults = {
        "name": "ORM Test",
        "search_type": "orm",
        "root": "node",
        "definition": {"filters": {"entity_type": "grid_fixtures__constrained_source"}},
    }
    defaults.update(kwargs)
    return Search(**defaults)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_entity_id(node):
    """Extract entity_id from a GRIFT envelope (spec-grift-envelope)."""
    return node["entity_id"]


def _node_entity_type(node):
    """Extract entity_type from a GRIFT envelope (spec-grift-envelope)."""
    return node["entity_type"]


def _edge_entity_id(edge):
    """Extract entity_id from a GRIFT envelope (spec-grift-envelope)."""
    return edge["entity_id"]


def _edge_type(edge):
    """Extract edge_type from a GRIFT envelope — lives inside `data` lane."""
    return edge["data"]["edge_type"]


def _make_character(description="Test"):
    from tap_plugin.grid_fixtures.models import ConstrainedSource

    return ConstrainedSource.objects.create(description=description)


def _make_wanderer(description="Test"):
    """Unconstrained has no edge constraints — safe for tests with arbitrary edge types."""
    from tap_plugin.grid_fixtures.models import Unconstrained

    return Unconstrained.objects.create(description=description)


def _make_edge(from_entity, to_entity, edge_type="RELATED_TO", properties=None):
    return Edge.objects.create(
        from_entity=from_entity,
        to_entity=to_entity,
        edge_type=edge_type,
        properties=properties or {},
    )


# ---------------------------------------------------------------------------
# Root selection (req-grid-search-orm-2)
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-search-orm-2")
@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestRootSelection:
    def test_node_root_excludes_edge_entities(self):
        """Node root returns non-edge entities only."""
        character = _make_character()
        s = Search.objects.create(
            name="Node Root",
            search_type="orm",
            root="node",
            definition={"filters": {}},
        )
        result = execute_search(s)
        entity_types = {_node_entity_type(n) for n in result["nodes"]}
        assert "edge" not in entity_types
        assert any(_node_entity_id(n) == str(character.entity_id) for n in result["nodes"])

    def test_edge_root_returns_edge_entities(self):
        """Edge root queries the Edge model."""
        w1 = _make_wanderer("A")
        w2 = _make_wanderer("B")
        _make_edge(w1.entity, w2.entity, edge_type="LINKS_TO")
        s = Search.objects.create(
            name="Edge Root",
            search_type="orm",
            root="edge",
            definition={"filters": {"edge_type": "LINKS_TO"}},
        )
        result = execute_search(s)
        assert result["nodes"] == []
        assert len(result["edges"]) >= 1
        assert all(_edge_type(e) == "LINKS_TO" for e in result["edges"])


# ---------------------------------------------------------------------------
# Filters (req-grid-search-orm-3)
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-search-orm-3")
@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestConjunctiveFilters:
    def test_entity_type_filter(self):
        """Filter by entity_type returns only matching entities."""
        _make_character()
        s = Search.objects.create(
            name="Filter Test",
            search_type="orm",
            root="node",
            definition={"filters": {"entity_type": "grid_fixtures__constrained_source"}},
        )
        result = execute_search(s)
        entity_types = {_node_entity_type(n) for n in result["nodes"]}
        assert entity_types == {"grid_fixtures__constrained_source"}

    def test_no_filters_returns_all_non_edge_entities(self):
        """Empty filters dict returns all non-edge entities."""
        _make_character()
        s = Search.objects.create(
            name="No Filter",
            search_type="orm",
            root="node",
            definition={"filters": {}},
        )
        result = execute_search(s)
        assert len(result["nodes"]) >= 1

    def test_filter_with_no_matching_results_returns_empty(self):
        """Filter that matches nothing returns empty nodes list."""
        s = Search.objects.create(
            name="Empty Filter",
            search_type="orm",
            root="node",
            definition={"filters": {"entity_type": "nonexistent_type_xyz"}},
        )
        result = execute_search(s)
        assert result["nodes"] == []

    def test_multiple_filters_applied_conjunctively(self):
        """Multiple filters are combined as AND."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        ConstrainedSource.objects.create(description="alpha")
        ConstrainedSource.objects.create(description="beta")
        s = Search.objects.create(
            name="Multi Filter",
            search_type="orm",
            root="node",
            definition={"filters": {"entity_type": "grid_fixtures__constrained_source", "name": ""}},
        )
        result = execute_search(s)
        assert all(_node_entity_type(n) == "grid_fixtures__constrained_source" for n in result["nodes"])


# ---------------------------------------------------------------------------
# Hop traversal (req-grid-search-orm-4 through 7)
# Uses wanderer entities — no edge constraints, any edge type is valid.
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-search-orm-4")
@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestHopTraversal:
    def test_out_hop_includes_target_entities_and_edges(self):
        """Outbound hop includes root nodes, endpoint nodes, and connecting edges."""
        w1 = _make_wanderer("Root")
        w2 = _make_wanderer("Target")
        edge = _make_edge(w1.entity, w2.entity, edge_type="CONNECTS_TO")

        s = Search.objects.create(
            name="Out Hop",
            search_type="orm",
            root="node",
            definition={
                "filters": {"entity_type": "grid_fixtures__unconstrained", "id": str(w1.entity_id)},
                "hops": [{"direction": "out", "edge_type": "CONNECTS_TO"}],
            },
        )
        result = execute_search(s)
        node_ids = {_node_entity_id(n) for n in result["nodes"]}
        edge_ids = {_edge_entity_id(e) for e in result["edges"]}
        assert str(w1.entity_id) in node_ids
        assert str(w2.entity_id) in node_ids
        assert str(edge.entity_id) in edge_ids

    def test_in_hop_includes_source_entities_and_edges(self):
        """Inbound hop includes root nodes, source nodes, and connecting edges."""
        w1 = _make_wanderer("Source")
        w2 = _make_wanderer("Root")
        _make_edge(w1.entity, w2.entity, edge_type="POINTS_TO")

        s = Search.objects.create(
            name="In Hop",
            search_type="orm",
            root="node",
            definition={
                "filters": {"entity_type": "grid_fixtures__unconstrained", "id": str(w2.entity_id)},
                "hops": [{"direction": "in", "edge_type": "POINTS_TO"}],
            },
        )
        result = execute_search(s)
        node_ids = {_node_entity_id(n) for n in result["nodes"]}
        assert str(w1.entity_id) in node_ids
        assert str(w2.entity_id) in node_ids
        assert len(result["edges"]) >= 1

    def test_hop_filters_endpoints_with_target_filters(self):
        """target_filters restricts which hop endpoints are included."""
        w1 = _make_wanderer("Root")
        w2 = _make_wanderer("Target")
        _make_edge(w1.entity, w2.entity, edge_type="LINKS_TO")

        s = Search.objects.create(
            name="Hop Target Filter",
            search_type="orm",
            root="node",
            definition={
                "filters": {"id": str(w1.entity_id)},
                "hops": [
                    {
                        "direction": "out",
                        "edge_type": "LINKS_TO",
                        "target_filters": {"entity_type": "nonexistent_xyz"},
                    }
                ],
            },
        )
        result = execute_search(s)
        assert str(w2.entity_id) not in {_node_entity_id(n) for n in result["nodes"]}
        assert result["edges"] == []

    def test_no_hop_returns_empty_edges(self):
        """Search without hops always returns empty edges list for node root."""
        _make_character()
        s = Search.objects.create(
            name="No Hop",
            search_type="orm",
            root="node",
            definition={"filters": {"entity_type": "grid_fixtures__constrained_source"}},
        )
        result = execute_search(s)
        assert result["edges"] == []


# ---------------------------------------------------------------------------
# Ordering (req-grid-search-orm-9)
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-search-orm-9")
@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestOrdering:
    def test_default_ordering_is_deterministic(self):
        """Without order_by, results are ordered by id (deterministic)."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        ConstrainedSource.objects.create(description="first")
        ConstrainedSource.objects.create(description="second")
        s = Search.objects.create(
            name="Default Order",
            search_type="orm",
            root="node",
            definition={"filters": {"entity_type": "grid_fixtures__constrained_source"}},
        )
        result1 = execute_search(s)
        result2 = execute_search(s)
        assert [_node_entity_id(n) for n in result1["nodes"]] == [_node_entity_id(n) for n in result2["nodes"]]

    def test_explicit_order_by_applied(self):
        """order_by field is applied to the queryset."""
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        ConstrainedSource.objects.create(description="z_character")
        ConstrainedSource.objects.create(description="a_character")
        s = Search.objects.create(
            name="Ordered",
            search_type="orm",
            root="node",
            definition={"filters": {"entity_type": "grid_fixtures__constrained_source"}, "order_by": ["id"]},
        )
        result = execute_search(s)
        ids = [_node_entity_id(n) for n in result["nodes"]]
        assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# Non-TAP models excluded (req-grid-search-orm-8)
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-search-orm-8")
@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestNonTapModelsExcluded:
    def test_node_root_only_returns_entities_from_entity_spine(self):
        """Node root queries Entity model — only TAP-managed entities are returned."""
        _make_character()
        s = Search.objects.create(
            name="Entity Spine",
            search_type="orm",
            root="node",
            definition={"filters": {}},
        )
        result = execute_search(s)
        for node in result["nodes"]:
            # spec-grift-envelope: spine fields flat at top.
            assert "entity_type" in node
            assert "entity_id" in node


# ---------------------------------------------------------------------------
# Result envelope and info (req-grid-search-results integration)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestOrmResultEnvelope:
    def test_result_has_canonical_4_keys(self):
        """ORM search result has nodes, edges, info, warnings."""
        s = Search.objects.create(
            name="Envelope",
            search_type="orm",
            root="node",
            definition={"filters": {"entity_type": "grid_fixtures__constrained_source"}},
        )
        result = execute_search(s)
        assert "nodes" in result
        assert "edges" in result
        assert "info" in result
        assert "warnings" in result

    def test_info_contains_total_count(self):
        """info dict contains total_count from compiler."""
        _make_character()
        s = Search.objects.create(
            name="Info Count",
            search_type="orm",
            root="node",
            definition={"filters": {"entity_type": "grid_fixtures__constrained_source"}},
        )
        result = execute_search(s)
        assert "total_count" in result["info"]
        assert result["info"]["total_count"] >= 1

    def test_paginated_result_has_count_limit_offset(self):
        """Paginated ORM search wraps in count/limit/offset/results."""
        _make_character("p1")
        _make_character("p2")
        _make_character("p3")
        s = Search.objects.create(
            name="Paginated",
            search_type="orm",
            root="node",
            definition={"filters": {"entity_type": "grid_fixtures__constrained_source"}},
        )
        result = execute_search(s, limit=2)
        assert "count" in result
        assert result["limit"] == 2
        assert result["offset"] == 0
        assert "results" in result
        assert len(result["results"]["nodes"]) <= 2

    def test_offset_pagination(self):
        """Offset skips results."""
        _make_character("q1")
        _make_character("q2")
        s = Search.objects.create(
            name="Offset",
            search_type="orm",
            root="node",
            definition={"filters": {"entity_type": "grid_fixtures__constrained_source"}, "order_by": ["id"]},
        )
        all_result = execute_search(s)
        all_ids = [_node_entity_id(n) for n in all_result["nodes"]]

        if len(all_ids) >= 2:
            paginated = execute_search(s, limit=1, offset=1)
            page_ids = [_node_entity_id(n) for n in paginated["results"]["nodes"]]
            assert all_ids[1] == page_ids[0]


# ---------------------------------------------------------------------------
# compile_orm_query unit tests (without full DB roundtrip)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestCompileOrmQueryUnit:
    def test_more_than_one_hop_raises(self):
        """compile_orm_query raises InvalidSearchDefinitionError for >1 hop."""
        s = _orm_search(
            definition={
                "filters": {},
                "hops": [
                    {"direction": "out", "edge_type": "A"},
                    {"direction": "out", "edge_type": "B"},
                ],
            }
        )
        with pytest.raises(InvalidSearchDefinitionError, match="one hop"):
            compile_orm_query(s, "search_readonly")
