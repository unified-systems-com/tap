"""Dimension names at the edges (req-grid-dimension-names; unified-systems-com/tap#711).

One resolver maps a dimension name to its stored key and a stored map to a name-keyed view. On
today's name-keyed shape it passes names through without a query; ``resolve`` is the strict rule
the storage flip switches on: declared nodes only, never minted, an ambiguous name refused.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tap_grid import dimension_names
from tap_grid.dimension_names import AmbiguousDimension, UnknownDimension
from tap_grid.models import Dimension, Entity


@pytest.mark.spec("req-grid-dimension-names-2")
class TestNameKeyedShapePassesThrough:
    def test_the_shape_is_name_keyed_until_the_flip(self) -> None:
        assert dimension_names.STORAGE_IS_NAME_KEYED is True

    @pytest.mark.django_db
    def test_storage_key_and_containment_are_the_name_with_no_query(self) -> None:
        with CaptureQueriesContext(connection) as queries:
            assert dimension_names.storage_key("tap.cloud") == "tap.cloud"
            assert dimension_names.storage_key("never-declared") == "never-declared"
            assert dimension_names.containment("tap.cloud", "aws") == {"tap.cloud": "aws"}
        assert len(queries) == 0

    def test_view_is_an_equal_copy(self) -> None:
        stored = {"tap.cloud": "aws", "aws_region": "us-gov-west-1"}
        shown = dimension_names.view(stored)
        assert shown == stored
        shown["tap.cloud"] = "changed"
        assert stored["tap.cloud"] == "aws"
        assert dimension_names.view(None) == {}


@pytest.mark.django_db
@pytest.mark.spec("req-grid-dimension-names-3")
class TestNamesResolveToDeclaredNodesOnly:
    def test_a_declared_name_resolves_to_its_node(self) -> None:
        node = Dimension.objects.create(name="tap.test.resolves")
        assert dimension_names.resolve("tap.test.resolves") == node.entity_id

    def test_an_undeclared_name_is_refused_and_nothing_is_minted(self) -> None:
        before = Dimension.objects.count()
        with pytest.raises(UnknownDimension, match="tap.test.nobody"):
            dimension_names.resolve("tap.test.nobody")
        assert Dimension.objects.count() == before

    def test_a_name_on_two_nodes_is_refused_naming_both(self) -> None:
        first = Dimension.objects.create(name="tap.test.twice")
        second = Dimension.objects.create(name="tap.test.twice")
        with pytest.raises(AmbiguousDimension) as raised:
            dimension_names.resolve("tap.test.twice")
        assert str(first.entity_id) in str(raised.value)
        assert str(second.entity_id) in str(raised.value)

    def test_a_retired_node_does_not_resolve(self) -> None:
        from tap_grid.services import delete_node

        node = Dimension.objects.create(name="tap.test.retired")
        assert delete_node(node.entity_id).success
        with pytest.raises(UnknownDimension):
            dimension_names.resolve("tap.test.retired")


@pytest.mark.django_db
@pytest.mark.spec("req-grid-dimension-names-1")
class TestReadersGoThroughTheResolver:
    def test_the_read_envelope_presents_dimensions_through_the_view(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_grid.grift.subgraph import build_spine_surface

        node = Dimension.objects.create(name="tap.test.envelope")
        entity = Entity.objects.get(pk=node.entity_id)
        seen: list[object] = []

        def spy(stored: object) -> dict[str, object]:
            seen.append(stored)
            return {"shown": "by-view"}

        monkeypatch.setattr(dimension_names, "view", spy)
        assert build_spine_surface(entity)["dimensions"] == {"shown": "by-view"}
        assert seen == [entity.dimensions]

    def test_gryphon_compiles_the_bracket_key_through_storage_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_grid.gryphon.ast_nodes import KeyStep
        from tap_grid.gryphon.executor import _json_spine_inner_path

        monkeypatch.setattr(dimension_names, "storage_key", lambda name: f"stored:{name}")
        assert _json_spine_inner_path([KeyStep("tap.cloud")], context="test") == "stored:tap.cloud"

    def test_export_selection_builds_containment_through_the_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_grid.grift.exporter import ExportSelection, _selected_node_ids

        node = Dimension.objects.create(name="tap.test.export")  # carries tap.meta = dimension
        asked: list[tuple[str, str]] = []
        real = dimension_names.containment

        def spy(name: str, value: str) -> dict[str, object]:
            asked.append((name, value))
            return real(name, value)

        monkeypatch.setattr(dimension_names, "containment", spy)
        admitted = _selected_node_ids(ExportSelection(dimensions=(("tap.meta", "dimension"),)))
        assert asked == [("tap.meta", "dimension")]
        assert admitted is not None and node.entity_id in admitted
