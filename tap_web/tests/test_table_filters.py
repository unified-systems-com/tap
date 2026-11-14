"""Tests for req-web-stdpanel-table-filters: the table filter bar, views and group-by choices.

The URL is the state (``f.<field>``, ``group``); projection rows are filtered in Python
with faceted counts; a declared search input receives a single selected value.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.http import QueryDict

from tap.pytest_harness import make_admin_client
from tap_grid.search import inputs_from_query
from tap_web.models import Panel
from tap_web.panels.table_panel import TablePanelType, _validate_table_config as validate_table_config
from tap_web.panels.table_panel.filters import apply_selection, build_bar, read_selection, resolve_group

ROWS: list[dict[str, Any]] = [
    {"id": "1", "status": "open", "product": "GuardDuty", "score": 9},
    {"id": "2", "status": "open", "product": "Inspector", "score": 4},
    {"id": "3", "status": "closed", "product": "GuardDuty", "score": 7},
    {"id": "4", "status": "open", "product": "GuardDuty", "score": None},
    {"id": "5", "status": "", "product": "Config", "score": 2},
]
SPECS = [{"field": "status"}, {"field": "product", "label": "Product"}, {"field": "score", "kind": "range"}]


def _q(query: str) -> QueryDict:
    return QueryDict(query)


class TestSchema:
    @pytest.mark.spec("req-web-stdpanel-table-filters-1")
    def test_filters_views_and_value_grouping_validate(self):
        validate_table_config(
            {
                "filters": [{"field": "status", "kind": "enum", "max_chips": 5}, {"field": "name", "kind": "text"}],
                "views": [{"label": "Open", "filters": {"status": ["open"]}, "group_by": "product"}],
                "group_by": {"field": "product", "mode": "value", "choices": ["product", "status"]},
                "drawer": {"id_field": "id", "entity_type": "aws_core__ec2_instance"},
            }
        )

    @pytest.mark.spec("req-web-stdpanel-table-filters-1")
    @pytest.mark.parametrize(
        "config",
        [
            {"filters": [{"field": "status", "kind": "slider"}]},
            {"filters": [{"field": "status", "extra": 1}]},
            {"views": [{"label": "Open"}]},
            {"group_by": {"field": "status"}},  # prefix mode still needs rules
            {"drawer": {"id": "x"}},
        ],
    )
    def test_unknown_kinds_and_keys_are_rejected(self, config):
        with pytest.raises(ValidationError):
            validate_table_config(config)


class TestSelection:
    @pytest.mark.spec("req-web-stdpanel-table-filters-2")
    def test_enum_values_or_and_fields_and(self):
        sel = read_selection(SPECS, _q("f.status=open&f.product=GuardDuty&f.product=Config"))
        assert [r["id"] for r in apply_selection(ROWS, sel)] == ["1", "4"]

    @pytest.mark.spec("req-web-stdpanel-table-filters-2")
    def test_empty_value_is_a_none_chip(self):
        sel = read_selection(SPECS, _q("f.status=(none)"))
        assert [r["id"] for r in apply_selection(ROWS, sel)] == ["5"]

    @pytest.mark.spec("req-web-stdpanel-table-filters-2")
    def test_range_is_inclusive_and_skips_non_numbers(self):
        sel = read_selection(SPECS, _q("f.score.min=4&f.score.max=9"))
        assert [r["id"] for r in apply_selection(ROWS, sel)] == ["1", "2", "3"]

    @pytest.mark.spec("req-web-stdpanel-table-filters-3")
    def test_blank_values_are_absent(self):
        sel = read_selection(SPECS, _q("f.status=&f.score.min=&f.product=%20"))
        assert sel.is_empty()

    @pytest.mark.spec("req-web-stdpanel-table-filters-2")
    def test_counts_are_faceted_over_the_other_filters(self):
        bar = build_bar(ROWS, SPECS, [], [], None, _q("f.product=GuardDuty"), {})
        status = {c.label: c.count for c in bar["filters"][0].chips}
        assert status == {"open": 2, "closed": 1}
        product = {c.label: (c.count, c.active) for c in bar["filters"][1].chips}
        assert product["GuardDuty"] == (3, True)
        assert product["Inspector"] == (1, False)

    @pytest.mark.spec("req-web-stdpanel-table-filters-3")
    def test_chip_links_toggle_their_value_and_keep_other_params(self):
        bar = build_bar(ROWS, SPECS, [], [], None, _q("f.product=GuardDuty&offset=50&account=123"), {})
        chips = {c.label: c.href for c in bar["filters"][1].chips}
        assert chips["GuardDuty"] == "?account=123"
        on = QueryDict(chips["Inspector"][1:])
        assert sorted(on.getlist("f.product")) == ["GuardDuty", "Inspector"]
        assert "offset" not in on and on["account"] == "123"


class TestViewsAndGroup:
    VIEWS = [{"label": "Open", "filters": {"status": ["open"]}}, {"label": "Inspector", "filters": {"product": ["Inspector"]}, "group_by": "status"}]

    @pytest.mark.spec("req-web-stdpanel-table-filters-5")
    def test_view_tabs_link_their_filters_and_mark_the_active_one(self):
        bar = build_bar(ROWS, SPECS, self.VIEWS, [], None, _q("f.status=open"), {})
        tabs = {t.label: t for t in bar["views"]}
        assert list(tabs) == ["All", "Open", "Inspector"]
        assert tabs["Open"].active and not tabs["All"].active
        inspector = QueryDict(tabs["Inspector"].href[1:])
        assert inspector.getlist("f.product") == ["Inspector"] and "f.status" not in inspector
        assert inspector["group"] == "status"

    @pytest.mark.spec("req-web-stdpanel-table-filters-6")
    def test_group_choice_switches_to_value_mode_and_none_turns_it_off(self):
        config = {"field": "product", "rules": [{"prefix": "G", "label": "G"}], "choices": ["product", "status"]}
        assert resolve_group(config, _q("")) is config
        assert resolve_group(config, _q("group=status")) == {"field": "status", "mode": "value"}
        assert resolve_group(config, _q("group=none")) is None
        assert resolve_group(config, _q("group=unlisted")) is config


class TestQuietDefaults:
    @pytest.mark.spec("req-web-stdpanel-table-filters-7")
    def test_a_filter_that_cannot_narrow_is_left_out_unless_selected(self):
        rows = [r for r in ROWS if r["product"] == "GuardDuty"]
        fields = [f.field for f in build_bar(rows, SPECS, [], [], None, _q(""), {})["filters"]]
        assert fields == ["status", "score"]
        kept = build_bar(rows, SPECS, [], [], None, _q("f.product=GuardDuty"), {})["filters"]
        assert [f.field for f in kept] == ["status", "product", "score"]

    @pytest.mark.spec("req-web-stdpanel-table-filters-7")
    def test_declared_order_wins_over_counts(self):
        specs = [{"field": "product", "order": ["Config", "Inspector"]}]
        chips = [c.label for c in build_bar(ROWS, specs, [], [], None, _q(""), {})["filters"][0].chips]
        assert chips == ["Config", "Inspector", "GuardDuty"]

    @pytest.mark.spec("req-web-stdpanel-table-filters-7")
    def test_initial_none_starts_ungrouped_until_an_axis_is_picked(self):
        config = {"field": "status", "mode": "value", "initial": "none", "choices": ["status", "product"]}
        assert resolve_group(config, _q("")) is None
        assert resolve_group(config, _q("group=product")) == {"field": "product", "mode": "value"}
        validate_table_config({"group_by": config})


class TestSearchInputs:
    @staticmethod
    def _search(schema: dict[str, Any]) -> Any:
        class _S:
            input_schema = schema

        return _S()

    @pytest.mark.spec("req-web-stdpanel-table-filters-4")
    def test_a_single_filter_value_feeds_a_declared_input(self):
        search = self._search({"properties": {"status": {"type": ["string", "null"], "default": None}}})
        assert inputs_from_query(search, _q("f.status=open")) == {"status": "open"}
        assert inputs_from_query(search, _q("f.status=open&f.status=closed")) == {}
        assert inputs_from_query(search, _q("f.status=")) == {}

    @pytest.mark.spec("req-web-stdpanel-table-filters-4")
    def test_a_blank_nullable_input_is_absent_but_a_blank_string_input_is_kept(self):
        nullable = self._search({"properties": {"q": {"type": ["string", "null"], "default": None}}})
        plain = self._search({"properties": {"q": {"type": "string"}}})
        assert inputs_from_query(nullable, _q("q=")) == {}
        assert inputs_from_query(plain, _q("q=")) == {"q": ""}


@pytest.mark.django_db
class TestRendered:
    @staticmethod
    def _panel(config: dict[str, Any]) -> Panel:
        from tap_grid.models import Edge, Search

        panel: Panel = Panel.objects.create(
            slug="filtered", name="Findings", view=TablePanelType.view, editor_view=TablePanelType.editor_view, config=config
        )
        search = Search.objects.create(name="Rows", search_type="orm", root="node", definition={"filters": {}})
        Edge.objects.create(from_entity=panel.entity, to_entity=search.entity, edge_type="USES_SEARCH")
        return panel

    @staticmethod
    def _get(panel: Panel, query: str = "") -> str:
        envelope = {"nodes": [], "edges": [], "rows": [dict(r) for r in ROWS], "info": {}, "warnings": {}}
        with patch("tap_grid.search.execute_search", return_value=envelope):
            url = f"/panel/{panel.slug}--{panel.entity_id}/" + (f"?{query}" if query else "")
            body: str = make_admin_client(username="filters-admin").get(url).content.decode()
            return body

    @staticmethod
    def _rows(content: str, panel: Panel) -> list[dict[str, Any]]:
        match = re.search(rf'<script id="tap-table-data-{panel.entity_id}" type="application/json">(.*?)</script>', content, re.S)
        assert match
        rows: list[dict[str, Any]] = json.loads(html.unescape(match.group(1)))
        return rows

    @pytest.mark.spec("req-web-stdpanel-table-filters-2")
    def test_bar_renders_chips_with_counts_and_rows_are_filtered(self):
        panel = self._panel({"filters": [{"field": "product"}], "drawer": {"id_field": "id", "entity_type": "x"}})
        content = self._get(panel, "f.product=GuardDuty")
        assert "data-tap-filterbar" in content
        assert re.search(r'tap-chip is-active".*?GuardDuty</span><span class="tap-chip-count">3<', content, re.S)
        assert [r["id"] for r in self._rows(content, panel)] == ["1", "3", "4"]
        assert "Showing 3 of 3" in content
        assert 'data-tap-table-drawer' in content and 'data-tap-drawer-id-field="id"' in content

    @pytest.mark.spec("req-web-stdpanel-table-filters-1")
    def test_no_bar_without_filters_views_or_choices(self):
        content = self._get(self._panel({}))
        assert "data-tap-filterbar" not in content
        assert "data-tap-table-drawer" not in content
