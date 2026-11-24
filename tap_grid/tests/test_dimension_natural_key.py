"""A NATURAL_KEY entry may name an identity dimension (form 3; ``req-grid-entity-natural-key-28``..``-32``,
``req-grid-dimension-knobs-3``; unified-systems-com/tap#1355).

``panel`` is the live fixture, re-declared here on ``(dimension:tap.test.issuer, slug)``. The
dimension is declared in the test with ``usable_in_keys`` true; a second one without it proves the
knob gates eligibility.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tap_grid.grift import grift_import
from tap_grid.models import Entity
from tap_grid.natural_key import (
    compose_natural_key,
    constituting_properties,
    declared_columns,
    dimension_entry,
    dimension_name,
    index_expressions,
    is_dimension,
    is_path,
    recipe_fingerprint,
)
from tap_grid.service_types import WriteOperation
from tap_grid.services import find_by_natural_key, write_batch
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc
from tap_web.models import Panel

ISSUER = "tap.test.issuer"
ENTRY = dimension_entry(ISSUER)
DECLARED = (ENTRY, "slug")

pytestmark = pytest.mark.django_db

SPEC_28 = pytest.mark.spec("req-grid-entity-natural-key-28")
SPEC_29 = pytest.mark.spec("req-grid-entity-natural-key-29")
SPEC_30 = pytest.mark.spec("req-grid-entity-natural-key-30")
SPEC_31 = pytest.mark.spec("req-grid-entity-natural-key-31")
SPEC_32 = pytest.mark.spec("req-grid-entity-natural-key-32")
KNOBS_3 = pytest.mark.spec("req-grid-dimension-knobs-3")


def _declare_dimension(name: str, *, usable_in_keys: bool) -> None:
    result = write_batch(
        [
            WriteOperation(
                verb="create_node",
                type_slug="dimension",
                payload={"name": name, "usable_in_keys": usable_in_keys},
                dimensions={"tap.graph": "web"},
            )
        ]
    )
    assert result.success, result.errors


@pytest.fixture
def keyed(monkeypatch: pytest.MonkeyPatch) -> tuple[str, ...]:
    _declare_dimension(ISSUER, usable_in_keys=True)
    monkeypatch.setattr(Panel, "NATURAL_KEY", DECLARED)
    return DECLARED


def _panel_payload(slug: str) -> dict[str, Any]:
    return {"name": slug, "slug": slug, "description": "", "view": "tap_web/panel_error.html", "config": {}}


def _created_id(result: Any) -> str:
    assert result.success, result
    return str(result.results[0].entity_id)


def _create(slug: str, issuer: str | None) -> Any:
    dims: dict[str, Any] = {"tap.graph": "web"}
    if issuer is not None:
        dims[ISSUER] = issuer
    return write_batch(
        [WriteOperation(verb="create_node", type_slug="panel", payload=_panel_payload(slug), dimensions=dims)]
    )


def _bundle(slug: str, issuer: str | None, *, entity_id: str | None = None) -> dict[str, Any]:
    dims: dict[str, Any] = {"tap.graph": "web"}
    if issuer is not None:
        dims[ISSUER] = issuer
    entity: dict[str, Any] = {"entity_type": "panel", "name": slug, "dimensions": dims}
    if entity_id is None:
        entity["ref"] = "it"
    else:
        entity["entity_id"] = entity_id
    return _minimal_doc(
        [_batch_container(_batch_entity_id(), nodes=[{"entity": entity, "node": _panel_payload(slug)}])]
    )


def _resolved(result: Any) -> str:
    assert result.success, result.errors
    return str(result.imported_batches[0].resolved_refs["it"])


@SPEC_28
class TestGrammar:
    def test_a_dimension_entry_is_neither_a_column_nor_a_path(self) -> None:
        assert ENTRY == "dimension:tap.test.issuer"
        assert is_dimension(ENTRY)
        assert not is_path(ENTRY)
        assert dimension_name(ENTRY) == ISSUER
        assert not is_dimension("slug") and not is_dimension("config.tenant")

    def test_a_dimension_name_is_required(self) -> None:
        with pytest.raises(ValueError):
            dimension_entry("")
        with pytest.raises(ValueError):
            dimension_entry(ENTRY)

    def test_the_typed_index_and_columns_leave_the_dimension_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Panel, "NATURAL_KEY", DECLARED)
        assert declared_columns(Panel) == ["slug"]
        assert len(index_expressions(DECLARED)) == 1

    def test_the_value_is_read_from_the_dimension_map_never_the_payload(self) -> None:
        payload = {"slug": "s", ENTRY: "wrong", ISSUER: "wrong"}
        assert constituting_properties(DECLARED, payload, {ISSUER: "a"}) == {ENTRY: "a", "slug": "s"}
        assert constituting_properties(DECLARED, payload, {ISSUER: {"v": "a", "src": "declared"}})[ENTRY] == "a"
        assert constituting_properties(DECLARED, payload)[ENTRY] is None

    def test_the_fingerprint_tells_a_dimension_from_a_column(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Panel, "NATURAL_KEY", ("slug", "name"))
        as_column = recipe_fingerprint(Panel)
        monkeypatch.setattr(Panel, "NATURAL_KEY", DECLARED)
        assert recipe_fingerprint(Panel) != as_column


@SPEC_28
class TestTheSearch:
    def test_finds_the_row_by_dimension_and_column(self, keyed: tuple[str, ...]) -> None:
        entity_id = _created_id(_create("p", "a"))
        found = Panel.find_existing(**{ENTRY: "a", "slug": "p"})
        assert found is not None and str(found.entity_id) == entity_id
        assert Panel.find_existing(**{ENTRY: "b", "slug": "p"}) is None

    def test_two_values_of_one_dimension_are_two_rows(self, keyed: tuple[str, ...]) -> None:
        assert _create("p", "a").success
        assert _create("p", "b").success
        assert Panel.find_existing(**{ENTRY: "a", "slug": "p"}) != Panel.find_existing(**{ENTRY: "b", "slug": "p"})

    def test_a_reference_spells_the_entry_as_declared(self, keyed: tuple[str, ...]) -> None:
        entity_id = _created_id(_create("p", "a"))
        assert find_by_natural_key("panel", {ENTRY: "a", "slug": "p"}) == uuid.UUID(entity_id)


@SPEC_29
@KNOBS_3
class TestEligibility:
    def test_a_dimension_without_usable_in_keys_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _declare_dimension("tap.test.perspective", usable_in_keys=False)
        monkeypatch.setattr(Panel, "NATURAL_KEY", (dimension_entry("tap.test.perspective"), "slug"))
        with pytest.raises(ValueError, match="usable_in_keys"):
            Panel.find_existing(**{dimension_entry("tap.test.perspective"): "a", "slug": "p"})

    def test_an_undeclared_dimension_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(Panel, "NATURAL_KEY", (dimension_entry("tap.test.nowhere"), "slug"))
        with pytest.raises(LookupError, match="tap.test.nowhere"):
            Panel.find_existing(**{dimension_entry("tap.test.nowhere"): "a", "slug": "p"})

    def test_the_importer_reports_an_ineligible_dimension(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _declare_dimension("tap.test.perspective", usable_in_keys=False)
        monkeypatch.setattr(Panel, "NATURAL_KEY", (dimension_entry("tap.test.perspective"), "slug"))
        doc = _bundle("p", None)
        doc["batches"][0]["nodes"][0]["entity"]["dimensions"]["tap.test.perspective"] = "a"
        result = grift_import(doc)
        assert not result.success
        assert "usable_in_keys" in str(result.errors)


@SPEC_30
class TestRequiredOnCreate:
    def test_a_create_without_the_keyed_dimension_is_refused(self, keyed: tuple[str, ...]) -> None:
        result = _create("p", None)
        assert not result.success
        assert "req-grid-entity-natural-key-30" in str(result.results)

    def test_an_import_without_it_is_refused(self, keyed: tuple[str, ...]) -> None:
        result = grift_import(_bundle("p", None))
        assert not result.success


@SPEC_28
class TestResolvedThroughTheImporter:
    def test_reimport_finds_the_same_row_and_another_value_makes_a_new_one(self, keyed: tuple[str, ...]) -> None:
        first = _resolved(grift_import(_bundle("p", "a")))
        again = _resolved(grift_import(_bundle("p", "a")))
        other = _resolved(grift_import(_bundle("p", "b")))
        assert again == first
        assert other != first
        assert Panel.objects.filter(slug="p").count() == 2


@SPEC_31
class TestAKeyedDimensionIsFixed:
    def test_a_replace_that_changes_it_is_refused(self, keyed: tuple[str, ...]) -> None:
        entity_id = _resolved(grift_import(_bundle("p", "a")))
        result = grift_import(_bundle("p", "b", entity_id=entity_id))
        assert not result.success
        assert "req-grid-entity-natural-key-31" in str(result.errors)
        stored = Entity.objects.get(pk=entity_id).dimensions
        assert constituting_properties((ENTRY,), {}, stored)[ENTRY] == "a"

    def test_a_replace_that_drops_it_is_refused(self, keyed: tuple[str, ...]) -> None:
        entity_id = _resolved(grift_import(_bundle("p", "a")))
        result = grift_import(_bundle("p", None, entity_id=entity_id))
        assert not result.success

    def test_a_replace_that_keeps_it_succeeds(self, keyed: tuple[str, ...]) -> None:
        entity_id = _resolved(grift_import(_bundle("p", "a")))
        assert grift_import(_bundle("p", "a", entity_id=entity_id)).success


@SPEC_32
class TestTheSpineKey:
    def test_the_spine_key_composes_the_dimension_in_declared_order(self, keyed: tuple[str, ...]) -> None:
        entity_id = _created_id(_create("p", "a"))
        assert Entity.objects.get(pk=entity_id).natural_key == "a|p"
        assert compose_natural_key(Panel, {ENTRY: "a", "slug": "p"}) == "a|p"

    def test_the_catch_up_sync_agrees_with_the_save(self, keyed: tuple[str, ...]) -> None:
        from tap_grid.spine_natural_key import check

        assert _create("p", "a").success
        report = check(entity_types=["panel"], sample=50)
        assert "panel" not in report.drifted
