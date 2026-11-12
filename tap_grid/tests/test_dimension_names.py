"""Dimension names at the edges (req-grid-dimension-names; unified-systems-com/tap#711).

One resolver maps a dimension name to its stored key (the declared node's uuid) and a stored map to a
name-keyed view, through the static vocabulary, with no query: declared nodes only, never minted, an
ambiguous name refused.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tap_grid import dimension_names
from tap_grid.dimension_names import AmbiguousDimension, UnknownDimension
from tap_grid.models import Dimension, Entity


TAP_META = "01a1d14c-d80b-725d-8002-eb0b3e272f1d"  # core's seed (tap_grid/data/dimensions.grift.json)


@pytest.fixture
def table() -> Iterator[None]:
    """A vocabulary of three declared names, one of them declared twice."""
    from tap_grid import dimension_vocabulary as vocab

    saved = vocab.vocabulary()

    def declared(ident: str, name: str) -> vocab.DeclaredDimension:
        return vocab.DeclaredDimension(id=ident, name=name, values=None, usable_in_keys=False, source="test")

    one = "01a1d150-1111-7000-8000-000000000001"
    twice = ("01a1d150-1111-7000-8000-000000000002", "01a1d150-1111-7000-8000-000000000003")
    vocab.reset(
        vocab.Vocabulary(
            by_id={one: declared(one, "tap.test.resolves"), twice[0]: declared(twice[0], "tap.test.twice"), twice[1]: declared(twice[1], "tap.test.twice")},
            by_name={"tap.test.resolves": (one,), "tap.test.twice": twice},
        )
    )
    yield
    vocab.reset(saved)


@pytest.mark.spec("req-grid-dimension-names-2")
class TestTheStoredShapeIsKeyedByNode:
    def test_the_shape_is_keyed_by_node(self) -> None:
        assert dimension_names.STORAGE_IS_NAME_KEYED is False

    @pytest.mark.django_db
    def test_storage_key_and_containment_resolve_with_no_query(self) -> None:
        with CaptureQueriesContext(connection) as queries:
            assert dimension_names.storage_key("tap.meta") == TAP_META
            assert dimension_names.storage_key(TAP_META) == TAP_META
            assert dimension_names.containment("tap.meta", "dimension") == {TAP_META: {"v": "dimension"}}
        assert len(queries) == 0

    def test_view_presents_names_and_values_as_a_copy(self) -> None:
        stored: dict[str, Any] = {TAP_META: {"v": "dimension", "src": "default"}, "not-a-declared-key": "legacy"}
        shown = dimension_names.view(stored)
        assert shown == {"tap.meta": "dimension", "not-a-declared-key": "legacy"}
        shown["tap.meta"] = "changed"
        assert stored[TAP_META]["v"] == "dimension"
        assert dimension_names.view(None) == {}


@pytest.mark.spec("req-grid-dimension-names-3")
@pytest.mark.usefixtures("table")
class TestNamesResolveToDeclaredNodesOnly:
    def test_a_declared_name_resolves_to_its_node(self) -> None:
        assert str(dimension_names.resolve("tap.test.resolves")) == "01a1d150-1111-7000-8000-000000000001"

    def test_an_undeclared_name_or_id_is_refused(self) -> None:
        with pytest.raises(UnknownDimension, match="tap.test.nobody"):
            dimension_names.resolve("tap.test.nobody")
        with pytest.raises(UnknownDimension):
            dimension_names.resolve("01a1d150-1111-7000-8000-0000000000ff")

    @pytest.mark.django_db
    def test_nothing_is_minted(self) -> None:
        before = Dimension.objects.count()
        with pytest.raises(UnknownDimension):
            dimension_names.storage_key("tap.test.nobody")
        assert Dimension.objects.count() == before

    def test_a_name_on_two_nodes_is_refused_naming_both(self) -> None:
        with pytest.raises(AmbiguousDimension) as raised:
            dimension_names.resolve("tap.test.twice")
        assert "01a1d150-1111-7000-8000-000000000002" in str(raised.value)
        assert "01a1d150-1111-7000-8000-000000000003" in str(raised.value)


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

        monkeypatch.setattr(dimension_names, "storage_key", lambda name: f"stored:{name}")  # resolved at compile
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
