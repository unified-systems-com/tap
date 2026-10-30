"""The table panel's ``entityType`` column formatter: the server half (req-web-stdpanel-table-config-32).

The server resolves each entity-type slug in the column from the entity-type catalog and hands the result to the
browser formatter as ``formatter_params.types``. The browser half (the markup) is in js/table_columns.test.mjs.
"""

from __future__ import annotations

import copy
from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.test import RequestFactory

from tap_web.models import Panel
from tap_web.panels.table_panel import TablePanelType, _entity_type_catalog, _validate_table_config, _with_entity_types

_RID = "req-web-stdpanel-table-config-32"

ICON_AND_NAME = "grid_fixtures__constrained_source"  # a published ENTITY_ICON whose SVG ships in grid_fixtures
NAME_ONLY = "grid_fixtures__peer_group"
NO_METADATA = "grid_fixtures__unpublished"
UNKNOWN = "nobody__knows_this"


def _column(**params: Any) -> dict[str, Any]:
    return {"field": "entity_type", "title": "Kind", "formatter": "entityType", "formatter_params": params}


@pytest.fixture
def catalog(db):  # noqa: ARG001
    """Three catalog rows: icon+name, name only, and a type that published neither (the loader stores its slug)."""
    from django.apps import apps

    from tap_grid.models import EntityType

    plugin_name = apps.get_app_config("grid_fixtures").name
    for slug, name, icon in (
        (ICON_AND_NAME, "Constrained Source", "constrained-source"),
        (NAME_ONLY, "Peer Group", ""),
        (NO_METADATA, NO_METADATA, ""),
    ):
        EntityType.objects.update_or_create(
            slug=slug, defaults={"name": name, "icon": icon, "plugin_name": plugin_name, "kind": "node"}
        )


class TestConfigValidation:
    @pytest.mark.spec(_RID)
    @pytest.mark.parametrize("show", ["icon", "name", "both"])
    @pytest.mark.parametrize("tone", ["good", "bad", "warn", "muted"])
    def test_the_formatter_and_its_options_are_accepted(self, show, tone):
        _validate_table_config({"columns": [_column(show=show, tone=tone)]})

    @pytest.mark.spec(_RID)
    def test_the_options_are_optional(self):
        _validate_table_config({"columns": [{"field": "entity_type", "title": "Kind", "formatter": "entityType"}]})

    @pytest.mark.spec(_RID)
    @pytest.mark.parametrize("bad", [{"show": "text"}, {"tone": "purple"}, {"show": ["icon"]}])
    def test_other_option_values_are_refused(self, bad):
        with pytest.raises(ValidationError):
            _validate_table_config({"columns": [_column(**bad)]})

    @pytest.mark.spec(_RID)
    def test_an_author_cannot_supply_the_server_owned_types(self):
        with pytest.raises(ValidationError):
            _validate_table_config({"columns": [_column(types={"x": {"icon": "/static/evil.svg"}})]})


class TestCatalogResolution:
    @pytest.mark.spec(_RID)
    def test_a_type_with_icon_and_name_resolves_both(self, catalog):  # noqa: ARG002
        got = _entity_type_catalog({ICON_AND_NAME})[ICON_AND_NAME]
        assert got["name"] == "Constrained Source"
        assert got["icon"].startswith("/static/grid_fixtures/icons/") and got["icon"].endswith("constrained-source.svg")

    @pytest.mark.spec(_RID)
    def test_a_type_with_a_name_only_has_no_icon(self, catalog):  # noqa: ARG002
        assert _entity_type_catalog({NAME_ONLY})[NAME_ONLY] == {"name": "Peer Group", "icon": ""}

    @pytest.mark.spec(_RID)
    def test_a_type_that_published_nothing_has_no_name_and_no_icon(self, catalog):  # noqa: ARG002
        """The loader stores the slug as the name when ENTITY_NAME is absent; that is not a published name."""
        assert _entity_type_catalog({NO_METADATA})[NO_METADATA] == {"name": "", "icon": ""}

    @pytest.mark.spec(_RID)
    def test_an_unknown_type_is_absent_and_an_empty_ask_costs_nothing(self, catalog):  # noqa: ARG002
        assert _entity_type_catalog({UNKNOWN}) == {}
        assert _entity_type_catalog(set()) == {}

    @pytest.mark.spec(_RID)
    def test_a_missing_icon_file_resolves_to_no_icon(self, catalog):  # noqa: ARG002
        from tap_grid.models import EntityType

        EntityType.objects.filter(slug=NAME_ONLY).update(icon="no-such-icon")
        assert _entity_type_catalog({NAME_ONLY})[NAME_ONLY]["icon"] == ""

    @pytest.mark.spec(_RID)
    def test_the_icon_address_comes_from_the_registry_not_from_the_row(self, catalog):  # noqa: ARG002
        """A row whose value is itself an address resolves to nothing: the value is only a lookup key."""
        hostile = "javascript:alert(1)"
        rows = [{"entity_type": hostile}, {"entity_type": "/static/evil.svg"}, {"entity_type": ICON_AND_NAME}]
        out = _with_entity_types([_column()], rows)
        assert out is not None
        types = out[0]["formatter_params"]["types"]
        assert set(types) == {ICON_AND_NAME}
        assert all(t["icon"].startswith("/static/grid_fixtures/") or t["icon"] == "" for t in types.values())


class TestColumnEnrichment:
    @pytest.mark.spec(_RID)
    def test_only_the_slugs_in_the_rows_are_resolved_for_entity_type_columns(self, catalog):  # noqa: ARG002
        rows: list[dict[str, Any]] = [
            {"entity_type": ICON_AND_NAME},
            {"entity_type": UNKNOWN},
            {"entity_type": None},
            {},
        ]
        plain = {"field": "name", "title": "Name"}
        out = _with_entity_types([plain, _column(show="icon")], rows)
        assert out is not None
        assert out[0] == plain
        assert out[1]["formatter_params"]["show"] == "icon", "the author's options are kept"
        assert set(out[1]["formatter_params"]["types"]) == {ICON_AND_NAME}

    @pytest.mark.spec(_RID)
    def test_the_stored_columns_are_never_mutated(self, catalog):  # noqa: ARG002
        columns = [{"title": "G", "columns": [_column(), {"field": "name", "title": "N"}]}]
        before = copy.deepcopy(columns)
        out = _with_entity_types(columns, [{"entity_type": NAME_ONLY}])
        assert columns == before
        assert out is not None
        assert out[0]["columns"][0]["formatter_params"]["types"] == {NAME_ONLY: {"name": "Peer Group", "icon": ""}}

    @pytest.mark.spec(_RID)
    def test_field_path_and_dotted_field_read_the_value(self, catalog):  # noqa: ARG002
        rows = [{"data": {"kind.of": NAME_ONLY}}]
        by_path = {"field_path": ["data", "kind.of"], "title": "K", "formatter": "entityType"}
        by_dotted = {"field": "data.kind", "title": "K", "formatter": "entityType"}
        out = _with_entity_types([by_path, by_dotted], rows)
        assert out is not None
        assert set(out[0]["formatter_params"]["types"]) == {NAME_ONLY}
        assert out[1]["formatter_params"]["types"] == {}

    @pytest.mark.spec(_RID)
    def test_no_entity_type_column_means_no_query_and_the_same_columns(self, db):  # noqa: ARG002
        columns = [{"field": "name", "title": "Name"}]
        assert _with_entity_types(columns, [{"name": "x"}]) is columns
        assert _with_entity_types(None, []) is None

    @pytest.mark.spec(_RID)
    def test_the_panel_context_carries_the_resolved_types(self, catalog):  # noqa: ARG002
        from tap_grid.models import Edge, Search

        panel = Panel.objects.create(
            slug="entity-type-table",
            name="T",
            view=TablePanelType.view,
            editor_view=TablePanelType.editor_view,
            config={"columns": [_column(show="both")]},
        )
        search = Search.objects.create(
            name="S", search_type="orm", root="node", definition={"filters": {}}, default_limit=25, max_limit=100
        )
        Edge.objects.create(from_entity=panel.entity, to_entity=search.entity, edge_type="USES_SEARCH")
        envelope = {
            "nodes": [{"entity_id": "a", "entity_type": ICON_AND_NAME}, {"entity_id": "b", "entity_type": UNKNOWN}],
            "edges": [],
            "info": {},
            "warnings": {},
        }
        with patch("tap_grid.search.execute_search", return_value=envelope):
            ctx = TablePanelType.get_view_context(panel, RequestFactory().get("/"))
        types = ctx["table_columns"][0]["formatter_params"]["types"]
        assert set(types) == {ICON_AND_NAME}
        assert types[ICON_AND_NAME]["name"] == "Constrained Source"
        assert "types" not in panel.config["columns"][0]["formatter_params"]
