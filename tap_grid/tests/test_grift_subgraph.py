"""Tests for GRIFT subgraph serializers — spec-grift-subgraph + spec-grift-envelope.

Verifies envelope-shape contract: spine fields flat at top, per-model in
`data`, consumer-namespaced computed-for-render in `display.tap_viz`.
Same shape for nodes and edges; polymorphism lives entirely in `data`.
"""

from __future__ import annotations

import uuid

import pytest

from tap_grid.grift.subgraph import (
    batch_resolve_display,
    batch_resolve_typed_models,
    build_data_lane,
    build_display_lane,
    build_spine_surface,
    serialize_edge_extended,
    serialize_edge_full,
    serialize_edge_lite,
    serialize_node_extended,
    serialize_node_full,
    serialize_node_lite,
    serialize_subgraph,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_character(name="Frodo", description="A hobbit"):
    from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
    from tap_grid.models import Entity

    ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
    set_caller_context(ctx)

    from tap_plugin.grid_fixtures.models import ConstrainedSource

    entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=name)
    character = ConstrainedSource.objects.create(entity=entity, name=name, description=description)
    return character


def _make_edge(from_entity, to_entity, edge_type="KNOWS"):
    from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
    from tap_grid.models import Edge, Entity

    ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
    set_caller_context(ctx)

    edge_entity = Entity.objects.create(entity_type="edge", name=edge_type)
    return Edge.objects.create(
        entity=edge_entity,
        from_entity=from_entity,
        to_entity=to_entity,
        edge_type=edge_type,
        properties={},
    )


# ---------------------------------------------------------------------------
# Lane builders (spec-grift-envelope)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBuildSpineSurface:
    def test_all_entity_row_fields_present(self):
        character = _make_character()
        spine = build_spine_surface(character.entity)
        # Canonical order per req-grid-entity-spine-surface.
        for key in (
            "entity_id",
            "entity_type",
            "name",
            "dimensions",
            "created_at",
            "updated_at",
            "deleted_at",
            "version",
            "originating_grid_id",
        ):
            assert key in spine, f"missing spine field: {key}"

    def test_entity_id_is_string(self):
        character = _make_character()
        spine = build_spine_surface(character.entity)
        assert isinstance(spine["entity_id"], str)

    def test_entity_type_matches(self):
        character = _make_character()
        spine = build_spine_surface(character.entity)
        assert spine["entity_type"] == "grid_fixtures__constrained_source"

    def test_no_nested_entity_key(self):
        """Spine is flat at top — no `entity` wrapper key."""
        character = _make_character()
        spine = build_spine_surface(character.entity)
        assert "entity" not in spine


@pytest.mark.django_db
class TestBuildDataLane:
    def test_includes_field_crud_schema_fields(self):
        character = _make_character(name="Frodo", description="A hobbit")
        data = build_data_lane(character)
        assert data["name"] == "Frodo"
        assert data["description"] == "A hobbit"

    def test_includes_universal_basemodel_fields(self):
        character = _make_character()
        data = build_data_lane(character)
        # description and flip_map are universal — always present. The typed batch_id was removed with
        # the base-model release (Issue# 1288 - tap): the batch pointers are spine fields, not data.
        assert "description" in data
        assert "flip_map" in data
        assert "batch_id" not in data
        assert not {"spine_deleted_at", "spine_dimensions"} & set(data), "the copies are on no surface"

    def test_includes_entity_id_mirror(self):
        character = _make_character()
        data = build_data_lane(character)
        assert "entity_id" in data
        assert data["entity_id"] == str(character.entity_id)

    def test_excludes_entity_type(self):
        """entity_type is a spine field; never in data."""
        character = _make_character()
        data = build_data_lane(character)
        assert "entity_type" not in data

    def test_none_typed_model_returns_empty(self):
        assert build_data_lane(None) == {}


class TestBuildDisplayLane:
    def test_namespaced_under_tap_viz(self):
        display = build_display_lane(
            tap_viz_hints={"shape": "ellipse", "colors": {"fill": "#fff"}},
            icon_url="/x.svg",
            url_id="x--id",
        )
        assert "tap_viz" in display
        assert display["tap_viz"]["shape"] == "ellipse"
        assert display["tap_viz"]["icon_url"] == "/x.svg"
        assert display["tap_viz"]["url_id"] == "x--id"

    def test_empty_when_no_hints_or_helpers(self):
        assert build_display_lane() == {}

    def test_edge_labels_when_provided(self):
        display = build_display_lane(from_label="Frodo", to_label="Sam")
        assert display["tap_viz"]["from_label"] == "Frodo"
        assert display["tap_viz"]["to_label"] == "Sam"


# ---------------------------------------------------------------------------
# Node layer serializers
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSerializeNodeLite:
    def test_spine_only(self):
        character = _make_character()
        node = serialize_node_lite(character.entity)
        # Spine fields at top.
        assert node["entity_type"] == "grid_fixtures__constrained_source"
        assert "name" in node
        # No data lane, no display lane.
        assert "data" not in node
        assert "display" not in node


@pytest.mark.django_db
class TestSerializeNodeFull:
    def test_spine_plus_data(self):
        character = _make_character(name="Frodo", description="A hobbit")
        node = serialize_node_full(character.entity, character)
        assert node["entity_id"] == str(character.entity_id)
        assert node["entity_type"] == "grid_fixtures__constrained_source"
        assert "data" in node
        assert node["data"]["name"] == "Frodo"
        assert node["data"]["description"] == "A hobbit"
        # No display lane in full.
        assert "display" not in node

    def test_data_mirror_equals_top_level(self):
        """req-grift-envelope-denorm-3: mirror equality."""
        character = _make_character(name="Frodo")
        node = serialize_node_full(character.entity, character)
        assert node["data"]["entity_id"] == node["entity_id"]
        assert node["data"]["name"] == node["name"]

    def test_none_typed_model_yields_empty_data(self):
        character = _make_character()
        node = serialize_node_full(character.entity, None)
        assert node["data"] == {}


@pytest.mark.django_db
class TestSerializeNodeExtended:
    def test_all_three_lanes(self):
        character = _make_character(name="Frodo")
        node = serialize_node_extended(
            character.entity,
            character,
            icon_url="/static/icon.svg",
            tap_viz_hints={"shape": "ellipse"},
        )
        # Spine top-level.
        assert node["entity_id"] == str(character.entity_id)
        # Data lane.
        assert node["data"]["name"] == "Frodo"
        # Display lane, namespaced.
        assert node["display"]["tap_viz"]["icon_url"] == "/static/icon.svg"
        assert node["display"]["tap_viz"]["shape"] == "ellipse"
        assert "url_id" in node["display"]["tap_viz"]

    def test_url_id_derived_from_name(self):
        character = _make_character(name="Frodo Baggins")
        node = serialize_node_extended(character.entity, character)
        assert node["display"]["tap_viz"]["url_id"].startswith("frodo-baggins--")

    def test_no_flat_promotion_of_icon_url_or_shape(self):
        """req-grift-envelope-display-4: flat-field promotion retired."""
        character = _make_character()
        node = serialize_node_extended(character.entity, character, icon_url="/i.svg", tap_viz_hints={"shape": "x"})
        # Top-level should NOT carry icon_url/shape/url_id — those live in display.tap_viz.
        assert "icon_url" not in node
        assert "shape" not in node
        assert "url_id" not in node


# ---------------------------------------------------------------------------
# Edge layer serializers — same envelope shape as nodes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSerializeEdgeLite:
    def test_spine_only(self):
        c1 = _make_character("Frodo")
        c2 = _make_character("Sam")
        edge = _make_edge(c1.entity, c2.entity, "KNOWS")
        from tap_grid.models import Edge

        edge = Edge.objects.select_related("entity").get(pk=edge.pk)
        lite = serialize_edge_lite(edge)
        # Spine fields at top.
        assert lite["entity_id"] == str(edge.entity_id)
        assert lite["entity_type"] == "edge"
        # No data, no display.
        assert "data" not in lite
        assert "display" not in lite


@pytest.mark.django_db
class TestSerializeEdgeFull:
    def test_spine_plus_data(self):
        c1 = _make_character("Frodo")
        c2 = _make_character("Sam")
        edge = _make_edge(c1.entity, c2.entity, "KNOWS")
        from tap_grid.models import Edge

        edge = Edge.objects.select_related("entity").get(pk=edge.pk)
        full = serialize_edge_full(edge)
        assert full["entity_type"] == "edge"
        assert full["data"]["from_entity_id"] == str(c1.entity_id)
        assert full["data"]["to_entity_id"] == str(c2.entity_id)
        assert full["data"]["edge_type"] == "KNOWS"
        assert "display" not in full

    def test_edge_data_mirror(self):
        c1 = _make_character("Frodo")
        c2 = _make_character("Sam")
        edge = _make_edge(c1.entity, c2.entity, "KNOWS")
        from tap_grid.models import Edge

        edge = Edge.objects.select_related("entity").get(pk=edge.pk)
        full = serialize_edge_full(edge)
        assert full["data"]["entity_id"] == full["entity_id"]
        assert full["data"]["name"] == full["name"]


@pytest.mark.django_db
class TestSerializeEdgeExtended:
    def test_endpoint_labels_in_display(self):
        c1 = _make_character("Frodo")
        c2 = _make_character("Sam")
        edge = _make_edge(c1.entity, c2.entity, "KNOWS")
        from tap_grid.models import Edge

        edge = Edge.objects.select_related("entity").get(pk=edge.pk)
        ext = serialize_edge_extended(edge, from_label="Frodo", to_label="Sam")
        assert ext["display"]["tap_viz"]["from_label"] == "Frodo"
        assert ext["display"]["tap_viz"]["to_label"] == "Sam"
        # No flat from_name / to_name (req-grift-envelope-edge-5).
        assert "from_name" not in ext
        assert "to_name" not in ext


# ---------------------------------------------------------------------------
# Batch resolution
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBatchResolveTypedModels:
    def test_resolves_by_entity_type(self):
        c1 = _make_character("Frodo")
        c2 = _make_character("Sam")
        entities = [c1.entity, c2.entity]
        result = batch_resolve_typed_models(entities, "default")
        assert str(c1.entity_id) in result
        assert str(c2.entity_id) in result
        assert result[str(c1.entity_id)].name == "Frodo"

    def test_skips_edge_entity_type(self):
        from tap_grid.models import Entity

        edge_entity = Entity.objects.create(entity_type="edge", name="test")
        result = batch_resolve_typed_models([edge_entity], "default")
        assert str(edge_entity.pk) not in result


@pytest.mark.django_db
class TestBatchResolveDisplay:
    def test_returns_display_from_default_display(self):
        result = batch_resolve_display({"grid_fixtures__constrained_source"})
        assert "grid_fixtures__constrained_source" in result
        assert result["grid_fixtures__constrained_source"].get("shape") == "round-rectangle"

    def test_unknown_type_defaults_to_empty_dict(self):
        result = batch_resolve_display({"nonexistent_xyz"})
        assert result["nonexistent_xyz"] == {}


# ---------------------------------------------------------------------------
# Subgraph convenience
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSerializeSubgraph:
    def test_lite_spine_only(self):
        c = _make_character()
        result = serialize_subgraph([c.entity], [], layer="lite", db_alias="default")
        assert "nodes" in result
        assert "edges" in result
        n = result["nodes"][0]
        assert n["entity_id"] == str(c.entity_id)
        assert "data" not in n
        assert "display" not in n

    def test_full_includes_data(self):
        c = _make_character()
        result = serialize_subgraph([c.entity], [], layer="full", db_alias="default")
        n = result["nodes"][0]
        assert "data" in n
        assert "display" not in n

    def test_extended_includes_data_and_display(self):
        c = _make_character(name="Frodo")
        result = serialize_subgraph([c.entity], [], layer="extended", db_alias="default")
        n = result["nodes"][0]
        assert "data" in n
        assert "display" in n
        assert "tap_viz" in n["display"]
        assert "url_id" in n["display"]["tap_viz"]
