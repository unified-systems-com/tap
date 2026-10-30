"""Tests for the Chart built-in panel type (spec-web-panels-chart).

Pure-function tests cover the config rules and the rows-to-option transforms; the render tests seed real grid
rows, bind a real aggregating Gryphon search and read the fragment the panel endpoint serves. The browser-side
drawing (``chart-panel.js``: theme tokens, colour map, resize) is proven in a real browser, not here: the repo
has no JS test runner.
"""

from __future__ import annotations

import json
import re
import uuid
from html import unescape
from typing import Any

import pytest
from django.core.exceptions import ValidationError

from tap.pytest_harness import make_admin_client
from tap_web.models import Panel
from tap_web.panels.chart import CHART_CONFIG_SCHEMA, COLOR_TOKENS, ChartPanelType, validate_config
from tap_web.panels.chart.transform import (
    build_option,
    build_tree,
    coerce_rows,
    sort_and_limit,
    to_instant,
    to_number,
)

BAR = {"xAxis": {"type": "category"}, "yAxis": {"type": "value"}, "series": [{"type": "bar"}]}
_COUNT_BY_SOURCE = [
    "MATCH (a:grid_fixtures__constrained_source)-[e:CONSTRAINED_LINK__grid_fixtures]->"
    "(b:grid_fixtures__constrained_target)",
    "RETURN a.name AS source, COUNT(b) AS n",
]


def _cfg(**extra: Any) -> dict[str, Any]:
    return {"max_rows": 500, "height": 320, "option": BAR, **extra}


# ---------------------------------------------------------------------------
# req-web-panels-chart-panel-type
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRegistration:
    @pytest.mark.spec("req-web-panels-chart-panel-type-1")
    def test_registered_under_its_slug(self, django_db_setup):  # noqa: ARG002
        from tap_web.registry import panel_type_registry

        found = [s["chart"] for s in panel_type_registry.all().values() if "chart" in s]
        assert found == [ChartPanelType]

    @pytest.mark.spec("req-web-panels-chart-panel-type-2")
    def test_declares_assets_in_load_order_and_they_exist(self):
        from pathlib import Path

        assert ChartPanelType.js == ["tap_web/js/lib/echarts.min.js", "tap_web/js/chart-panel.js"]
        root = Path(__file__).resolve().parents[1] / "static"
        # js/lib/* is vendored from the npm lockfile into the image (/opt/tap-static-vendor), not the tree.
        for path in (*ChartPanelType.css, *(p for p in ChartPanelType.js if "/js/lib/" not in p)):
            assert (root / path).is_file(), path

    @pytest.mark.spec("req-web-panels-chart-config-1")
    def test_defaults_are_valid_once_an_option_is_given(self):
        validate_config({**ChartPanelType.config_defaults, "option": BAR})


# ---------------------------------------------------------------------------
# req-web-panels-chart-config
# ---------------------------------------------------------------------------


def _schema_nodes(node: Any):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _schema_nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _schema_nodes(v)


class TestConfigSchema:
    @pytest.mark.spec("req-web-panels-chart-config-1")
    def test_option_is_required_and_undeclared_keys_rejected(self):
        with pytest.raises(ValidationError):
            validate_config({"height": 300})
        with pytest.raises(ValidationError):
            validate_config({"option": BAR, "theme": "dark"})

    @pytest.mark.spec("req-web-panels-chart-config-2")
    @pytest.mark.parametrize(
        "bad",
        [
            {"height": 50},
            {"height": "tall"},
            {"max_rows": 0},
            {"limit": 0},
            {"types": {"x": "money"}},
            {"sort": {"field": "x", "order": "sideways"}},
            {"color_map": {"map": {"a": "purple"}}},
            {"series_by": {"category": "a", "series": "b"}},
            {"hierarchy": {"path": []}},
            {"hierarchy": {"path": list("abcdefg")}},
        ],
    )
    def test_malformed_config_is_rejected(self, bad):
        with pytest.raises(ValidationError):
            validate_config({"option": BAR, **bad})

    @pytest.mark.spec("req-web-panels-chart-config-2")
    def test_a_full_config_passes(self):
        validate_config(
            {
                "option": {"xAxis": {"type": "category"}, "yAxis": {"type": "value"}, "series": [{"type": "bar"}]},
                "series_by": {"category": "sev", "series": "tool", "value": "c", "order": ["a"], "fill": None},
                "types": {"c": "number", "pub": "time", "sev": "category"},
                "sort": {"field": "c", "order": "desc"},
                "limit": 10,
                "color_map": {"field": "sev", "map": {"critical": "critical"}, "default": "neutral"},
                "height": "slot",
                "empty_text": "none",
                "null_text": "?",
                "blank_text": "-",
                "aria_label": "Findings",
                "max_rows": 100,
                "hide_header": True,
            }
        )

    @pytest.mark.spec("req-web-panels-chart-config-2")
    def test_color_tokens_include_the_stat_card_tones_and_severities(self):
        assert {"good", "warn", "bad", "neutral", "muted", "critical", "high", "medium", "low", "info"} <= set(
            COLOR_TOKENS
        )

    @pytest.mark.spec("req-web-panels-chart-config-3")
    def test_every_schema_entry_has_a_description(self):
        assert CHART_CONFIG_SCHEMA["description"]
        for name, prop in CHART_CONFIG_SCHEMA["properties"].items():
            assert prop.get("description"), name
        for key in ("series_by", "hierarchy", "color_map", "sort"):
            for name, prop in CHART_CONFIG_SCHEMA["properties"][key]["properties"].items():
                assert prop.get("description"), f"{key}.{name}"
        overrides = CHART_CONFIG_SCHEMA["properties"]["series_by"]["properties"]["overrides"]
        assert overrides["additionalProperties"]["description"]

    @pytest.mark.spec("req-web-panels-chart-config-4")
    def test_the_schema_names_no_domain_value(self):
        enums = {v for n in _schema_nodes(CHART_CONFIG_SCHEMA) if "enum" in n for v in n["enum"]}
        assert enums <= {*COLOR_TOKENS, "number", "time", "category", "asc", "desc", "slot"}


# ---------------------------------------------------------------------------
# req-web-panels-chart-safety
# ---------------------------------------------------------------------------


def _check(option: dict[str, Any]) -> str:
    with pytest.raises(ValidationError) as err:
        validate_config({"option": option})
    return " ".join(err.value.messages)


class TestSafety:
    @pytest.mark.spec("req-web-panels-chart-safety-1")
    @pytest.mark.parametrize(
        "text",
        [
            "function(p){return 1}",
            "function (p) { return 1 }",
            "(p) => p.value",
            "p=>p.name",
            "eval(1)",
            "new Function('x')",
            "javascript:alert(1)",
            "<script>x</script>",
            "url(http://x)",
        ],
    )
    def test_function_like_strings_are_rejected_anywhere(self, text):
        assert "looks like code" in _check({**BAR, "title": {"text": text}})
        assert "looks like code" in _check({**BAR, "series": [{"type": "bar", "data": [{"name": [text]}]}]})

    @pytest.mark.spec("req-web-panels-chart-safety-1")
    def test_ordinary_text_with_the_word_function_is_fine(self):
        validate_config({"option": {**BAR, "title": {"text": "Function coverage > 80%"}}})

    @pytest.mark.spec("req-web-panels-chart-safety-2")
    def test_a_formatter_must_be_a_plain_template(self):
        assert "plain template" in _check({**BAR, "tooltip": {"formatter": 5}})
        assert "plain template" in _check({**BAR, "tooltip": {"formatter": "<b>{b}</b>"}})
        assert "plain template" in _check({**BAR, "yAxis": {"axisLabel": {"formatter": {"a": 1}}}})
        validate_config({"option": {**BAR, "tooltip": {"formatter": "{b}: {c} ({d}%)"}}})
        validate_config({"option": {**BAR, "yAxis": {"axisLabel": {"formatter": "{value} open"}}}})

    @pytest.mark.spec("req-web-panels-chart-safety-3")
    @pytest.mark.parametrize(
        "text",
        [
            "https://x.example/a.png",
            "http://x",
            "//x.example/a",
            "image://http://x",
            "data:text/html,x",
            "file:///etc/x",
        ],
    )
    def test_external_references_are_rejected(self, text):
        assert "external" in _check({**BAR, "series": [{"type": "bar", "symbol": text}]})

    @pytest.mark.spec("req-web-panels-chart-safety-3")
    @pytest.mark.parametrize("key", ["link", "sublink", "extraCssText", "className"])
    def test_navigating_and_css_injecting_keys_are_rejected(self, key):
        assert "not allowed" in _check({**BAR, "title": {key: "x"}})

    @pytest.mark.spec("req-web-panels-chart-safety-4")
    def test_the_option_size_is_capped(self):
        assert "bytes" in _check({**BAR, "title": {"text": "x" * 40000}})

    @pytest.mark.spec("req-web-panels-chart-safety-4")
    def test_nesting_depth_is_capped(self):
        deep: dict[str, Any] = {}
        node = deep
        for _ in range(20):
            node["a"] = {}
            node = node["a"]
        assert "deeper" in _check({**BAR, "grid": deep})

    @pytest.mark.spec("req-web-panels-chart-safety-5")
    def test_series_types_are_a_closed_list(self):
        assert "custom" in _check({"series": [{"type": "custom"}]})
        assert "graph" in _check({"series": [{"type": "graph"}]})
        for kind in ("bar", "line", "pie", "scatter", "treemap", "sunburst", "heatmap", "funnel", "gauge", "radar"):
            validate_config({"option": {"series": [{"type": kind}]}})

    @pytest.mark.spec("req-web-panels-chart-safety-6")
    def test_the_panel_owns_the_dataset(self):
        assert "dataset" in _check({**BAR, "dataset": {"source": [[1]]}})


class TestCrossChecks:
    @pytest.mark.spec("req-web-panels-chart-series-by-5")
    def test_series_by_needs_one_bar_or_line_template(self):
        sb = {"category": "a", "series": "b", "value": "c"}
        with pytest.raises(ValidationError):
            validate_config({"option": {"series": [{"type": "bar"}, {"type": "bar"}]}, "series_by": sb})
        with pytest.raises(ValidationError):
            validate_config({"option": {"series": [{"type": "pie"}]}, "series_by": sb})
        validate_config({"option": {"series": [{"type": "line"}]}, "series_by": sb})

    @pytest.mark.spec("req-web-panels-chart-hierarchy-4")
    def test_hierarchy_needs_a_treemap_or_sunburst_and_excludes_series_by(self):
        with pytest.raises(ValidationError):
            validate_config({"option": BAR, "hierarchy": {"path": ["a"]}})
        validate_config({"option": {"series": [{"type": "sunburst"}]}, "hierarchy": {"path": ["a"]}})
        with pytest.raises(ValidationError):
            validate_config(
                {
                    "option": {"series": [{"type": "bar"}]},
                    "hierarchy": {"path": ["a"]},
                    "series_by": {"category": "a", "series": "b", "value": "c"},
                }
            )


# ---------------------------------------------------------------------------
# req-web-panels-chart-data
# ---------------------------------------------------------------------------


class TestData:
    @pytest.mark.spec("req-web-panels-chart-data-1")
    def test_rows_become_the_dataset_with_the_row_keys_as_dimensions(self):
        rows = [{"ex": "yes", "c": 3}, {"ex": "no", "c": 1, "extra": "x"}]
        option = build_option(rows, _cfg()).option
        assert option["dataset"] == {"dimensions": ["ex", "c", "extra"], "source": rows}
        assert option["series"] == [{"type": "bar"}]
        assert "dataset" not in BAR  # the config's option is never mutated

    @pytest.mark.spec("req-web-panels-chart-data-2")
    def test_typed_fields_are_coerced_before_echarts_sees_them(self):
        rows = [{"cvss": "8.2", "pub": "2026-09-29 15:32:23.605000+00:00", "id": 7, "n": "3"}]
        out, notices = coerce_rows(rows, {"cvss": "number", "pub": "time", "id": "category", "n": "number"})
        assert out == [{"cvss": 8.2, "pub": "2026-09-29T15:32:23.605000Z", "id": "7", "n": 3}]
        assert notices == []

    @pytest.mark.spec("req-web-panels-chart-data-3")
    def test_an_unparseable_value_is_a_stated_gap_not_zero(self):
        rows = [{"cvss": "lots", "pub": "last tuesday"}, {"cvss": "5", "pub": "2026-01-01"}]
        out, notices = coerce_rows(rows, {"cvss": "number", "pub": "time"})
        assert out[0] == {"cvss": None, "pub": None}
        assert out[1] == {"cvss": 5, "pub": "2026-01-01T00:00:00Z"}
        assert notices == [
            "1 value in `cvss` could not be read as number and is drawn as a gap.",
            "1 value in `pub` could not be read as time and is drawn as a gap.",
        ]

    @pytest.mark.spec("req-web-panels-chart-data-3")
    def test_null_and_blank_stay_unobserved_and_zero_is_a_value(self):
        out, notices = coerce_rows([{"a": None, "b": "", "c": 0}], {"a": "number", "b": "number", "c": "number"})
        assert out == [{"a": None, "b": "", "c": 0}]
        assert notices == []

    @pytest.mark.spec("req-web-panels-chart-data-2")
    def test_scalars(self):
        assert [to_number(v) for v in ("8.2", 3, "1e2", True, "x", None, "nan")] == [
            8.2,
            3,
            100,
            None,
            None,
            None,
            None,
        ]
        assert to_instant("2026-10-01T12:30:00+02:00") == "2026-10-01T10:30:00Z"
        assert to_instant("2026-10-01 10:30:00") == "2026-10-01T10:30:00Z"
        assert to_instant("nope") is None
        assert to_instant(5) is None

    @pytest.mark.spec("req-web-panels-chart-data-4")
    def test_sort_then_limit_makes_a_top_n(self):
        rows: list[dict[str, Any]] = [{"c": 2}, {"c": 9}, {"c": None}, {"c": 5}]
        cfg = {"sort": {"field": "c"}, "limit": 2, "max_rows": 500}
        out, notices = sort_and_limit(rows, cfg)
        assert out == [{"c": 9}, {"c": 5}]
        assert notices == ["2 more rows not drawn."]
        asc, _ = sort_and_limit(rows, {"sort": {"field": "c", "order": "asc"}, "max_rows": 500})
        assert asc == [{"c": 2}, {"c": 5}, {"c": 9}, {"c": None}]

    @pytest.mark.spec("req-web-panels-chart-data-5")
    def test_max_rows_caps_and_says_so(self):
        out, notices = sort_and_limit([{"c": i} for i in range(5)], {"max_rows": 3})
        assert len(out) == 3
        assert notices == ["2 more rows not drawn."]


class TestLabelsAndTemplates:
    EX: list[dict[str, Any]] = [{"ex": None, "c": 3}, {"ex": "", "c": 2}, {"ex": "poc", "c": None}]
    OPT = {
        "xAxis": {"type": "category"},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "encode": {"x": "ex", "y": "c"}}],
    }

    @pytest.mark.spec("req-web-panels-chart-data-6")
    def test_null_and_blank_labels_are_named_and_numeric_gaps_kept(self):
        src = build_option(self.EX, _cfg(option=self.OPT)).option["dataset"]["source"]
        assert [r["ex"] for r in src] == ["not observed", "(empty)", "poc"]
        assert src[2]["c"] is None
        custom = build_option(self.EX, _cfg(option=self.OPT, null_text="unscanned")).option
        assert custom["dataset"]["source"][0]["ex"] == "unscanned"

    @pytest.mark.spec("req-web-panels-chart-data-6")
    def test_a_pie_item_name_is_a_label_field(self):
        pie = {"series": [{"type": "pie", "encode": {"itemName": "ex", "value": "c"}}]}
        assert build_option(self.EX, _cfg(option=pie)).option["dataset"]["source"][0]["ex"] == "not observed"

    @pytest.mark.spec("req-web-panels-chart-data-7")
    def test_few_categories_show_every_label_unless_configured(self):
        assert build_option(self.EX, _cfg(option=self.OPT)).option["xAxis"]["axisLabel"]["interval"] == 0
        many = [{"ex": f"v{i}", "c": i} for i in range(13)]
        assert "axisLabel" not in build_option(many, _cfg(option=self.OPT)).option["xAxis"]
        own = {**self.OPT, "xAxis": {"type": "category", "axisLabel": {"interval": 2}}}
        assert build_option(self.EX, _cfg(option=own)).option["xAxis"]["axisLabel"]["interval"] == 2

    @pytest.mark.spec("req-web-panels-chart-data-7")
    def test_a_pivoted_chart_shows_every_label_too(self):
        sb = {"category": "sev", "series": "tool", "value": "c"}
        assert build_option(_SEV, _cfg(series_by=sb)).option["xAxis"]["axisLabel"]["interval"] == 0

    @pytest.mark.spec("req-web-panels-chart-safety-7")
    def test_bare_c_is_rejected_for_encoded_series_and_the_field_form_is_named(self):
        bad = {**self.OPT, "tooltip": {"formatter": "{b}: {c}"}}
        with pytest.raises(ValidationError) as err:
            validate_config({"option": bad})
        assert "{@field}" in " ".join(err.value.messages)
        with pytest.raises(ValidationError):
            validate_config(
                {
                    "option": {**BAR, "series": [{"type": "bar", "label": {"formatter": "{c0}"}}]},
                    "series_by": {"category": "a", "series": "b", "value": "c"},
                }
            )
        validate_config({"option": {**self.OPT, "tooltip": {"formatter": "{b}: {@c} ({d}%)"}}})
        validate_config({"option": {"series": [{"type": "treemap", "label": {"formatter": "{b}: {c}"}}]}})
        validate_config({"option": {"series": [{"type": "bar", "data": [1]}], "tooltip": {"formatter": "{c}"}}})


# ---------------------------------------------------------------------------
# series_by / hierarchy
# ---------------------------------------------------------------------------

_SEV: list[dict[str, Any]] = [
    {"sev": "high", "tool": "grype", "c": 4},
    {"sev": "high", "tool": "trivy", "c": 2},
    {"sev": "low", "tool": "grype", "c": 7},
    {"sev": None, "tool": "trivy", "c": 1},
    {"sev": "high", "tool": "grype", "c": 1},
]


class TestSeriesBy:
    SB = {"category": "sev", "series": "tool", "value": "c"}

    @pytest.mark.spec("req-web-panels-chart-series-by-1")
    def test_one_series_per_value_over_a_shared_category_axis(self):
        built = build_option(_SEV, _cfg(series_by=self.SB, option={**BAR, "series": [{"type": "bar", "stack": "t"}]}))
        option = built.option
        assert [s["name"] for s in option["series"]] == ["grype", "trivy"]
        assert all(s["type"] == "bar" and s["stack"] == "t" for s in option["series"])
        assert option["series"][0]["encode"] == {"x": "sev", "y": "series_0"}
        assert option["dataset"]["dimensions"] == ["sev", "series_0", "series_1"]
        by_cat = {r["sev"]: r for r in option["dataset"]["source"]}
        assert by_cat["high"] == {"sev": "high", "series_0": 5, "series_1": 2}  # duplicates are summed

    @pytest.mark.spec("req-web-panels-chart-series-by-2")
    def test_a_missing_combination_is_filled_with_zero_or_left_a_gap(self):
        by_cat = {r["sev"]: r for r in build_option(_SEV, _cfg(series_by=self.SB)).option["dataset"]["source"]}
        assert by_cat["low"]["series_1"] == 0
        gap = {**self.SB, "fill": None}
        by_cat = {r["sev"]: r for r in build_option(_SEV, _cfg(series_by=gap)).option["dataset"]["source"]}
        assert by_cat["low"]["series_1"] is None

    @pytest.mark.spec("req-web-panels-chart-series-by-2")
    def test_a_null_category_is_labelled_not_dropped(self):
        cats = [r["sev"] for r in build_option(_SEV, _cfg(series_by=self.SB)).option["dataset"]["source"]]
        assert cats == ["high", "low", "not observed"]
        custom = build_option(_SEV, _cfg(series_by=self.SB, null_text="unscanned")).option
        assert "unscanned" in [r["sev"] for r in custom["dataset"]["source"]]

    @pytest.mark.spec("req-web-panels-chart-series-by-3")
    def test_a_horizontal_chart_puts_the_category_on_y(self):
        horizontal = {"xAxis": {"type": "value"}, "yAxis": {"type": "category"}, "series": [{"type": "bar"}]}
        s = build_option(_SEV, _cfg(series_by=self.SB, option=horizontal)).option["series"][0]
        assert s["encode"] == {"y": "sev", "x": "series_0"}

    @pytest.mark.spec("req-web-panels-chart-series-by-4")
    def test_a_time_axis_is_sorted_and_keeps_instants(self):
        rows = [
            {"day": "2026-10-03T00:00:00Z", "tool": "a", "c": 1},
            {"day": "2026-10-01T00:00:00Z", "tool": "a", "c": 2},
        ]
        line = {"xAxis": {"type": "time"}, "yAxis": {"type": "value"}, "series": [{"type": "line"}]}
        src = build_option(rows, _cfg(series_by={"category": "day", "series": "tool", "value": "c"}, option=line))
        assert [r["day"] for r in src.option["dataset"]["source"]] == ["2026-10-01T00:00:00Z", "2026-10-03T00:00:00Z"]

    @pytest.mark.spec("req-web-panels-chart-series-by-1")
    def test_order_sets_the_stack_order_and_unlisted_follow(self):
        sb = {**self.SB, "order": ["trivy", "ghost"]}
        assert [s["name"] for s in build_option(_SEV, _cfg(series_by=sb)).option["series"]] == ["trivy", "grype"]

    @pytest.mark.spec("req-web-panels-chart-series-by-2")
    def test_rows_with_no_number_are_counted_not_zeroed(self):
        rows: list[dict[str, Any]] = [{"sev": "a", "tool": "x", "c": None}, {"sev": "a", "tool": "y", "c": 2}]
        built = build_option(rows, _cfg(series_by=self.SB))
        assert built.notices == ["1 row had no numeric `c` and is not drawn."]

    LINE: dict[str, Any] = {
        "xAxis": {"type": "time"},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "lineStyle": {"width": 1.5, "opacity": 0.5}, "endLabel": {"show": True}}],
    }
    ROWS: list[dict[str, Any]] = [
        {"day": "2026-10-01T00:00:00Z", "tool": "a", "c": 1},
        {"day": "2026-10-01T00:00:00Z", "tool": "Overall", "c": 2},
    ]

    @pytest.mark.spec("req-web-panels-chart-series-by-6")
    def test_an_override_is_deep_merged_onto_that_series_only(self):
        sb: dict[str, Any] = {
            "category": "day",
            "series": "tool",
            "value": "c",
            "overrides": {"Overall": {"lineStyle": {"width": 6, "opacity": 1}, "z": 10}},
        }
        cfg = _cfg(series_by=sb, option=self.LINE)
        by_name = {s["name"]: s for s in build_option(self.ROWS, cfg).option["series"]}
        assert by_name["Overall"]["lineStyle"] == {"width": 6, "opacity": 1}
        assert by_name["Overall"]["z"] == 10
        assert by_name["Overall"]["endLabel"] == {"show": True}  # untouched template keys survive
        assert by_name["a"]["lineStyle"] == {"width": 1.5, "opacity": 0.5} and "z" not in by_name["a"]
        assert by_name["Overall"]["encode"] == {"x": "day", "y": "series_1"}
        assert self.LINE["series"][0]["lineStyle"] == {"width": 1.5, "opacity": 0.5}  # template not mutated
        assert sb["overrides"]["Overall"]["z"] == 10

    @pytest.mark.spec("req-web-panels-chart-series-by-6")
    def test_an_override_for_an_absent_series_is_ignored(self):
        sb = {"category": "day", "series": "tool", "value": "c", "overrides": {"Ghost": {"z": 3}}}
        built = build_option(self.ROWS, _cfg(series_by=sb, option=self.LINE))
        assert all("z" not in s for s in built.option["series"])

    @pytest.mark.spec("req-web-panels-chart-series-by-7")
    @pytest.mark.parametrize(
        "bad",
        [
            "thick",
            {"name": "x"},
            {"type": "bar"},
            {"encode": {"y": "z"}},
            {"data": [1]},
            {"dataset": {}},
            {"label": {"formatter": "{c}"}},
            {"label": {"formatter": "<b>{b}</b>"}},
            {"lineStyle": {"color": "url(http://x)"}},
            {"x": "function () {}"},
        ],
    )
    def test_unsafe_overrides_are_rejected(self, bad):
        sb = {"category": "a", "series": "b", "value": "c", "overrides": {"Overall": bad}}
        with pytest.raises(ValidationError):
            validate_config({"option": {"series": [{"type": "line"}]}, "series_by": sb})

    @pytest.mark.spec("req-web-panels-chart-series-by-7")
    def test_a_safe_override_is_accepted(self):
        sb = {
            "category": "a",
            "series": "b",
            "value": "c",
            "overrides": {"Overall": {"lineStyle": {"width": 6}, "z": 10, "endLabel": {"formatter": "{a}"}}},
        }
        validate_config({"option": {"series": [{"type": "line"}]}, "series_by": sb})


class TestHierarchy:
    ROWS: list[dict[str, Any]] = [
        {"eco": "pypi", "comp": "django", "c": 3},
        {"eco": "pypi", "comp": "django", "c": 2},
        {"eco": "pypi", "comp": "flask", "c": 1},
        {"eco": "npm", "comp": "lodash", "c": 4},
        {"eco": None, "comp": "x", "c": None},
    ]
    H = {"path": ["eco", "comp"], "value": "c"}

    @pytest.mark.spec("req-web-panels-chart-hierarchy-1")
    def test_rows_become_a_tree_one_level_per_path_field(self):
        tree, unusable = build_tree(self.ROWS, {"hierarchy": self.H})
        assert tree == [
            {"name": "pypi", "children": [{"name": "django", "value": 5}, {"name": "flask", "value": 1}]},
            {"name": "npm", "children": [{"name": "lodash", "value": 4}]},
        ]
        assert unusable == 1

    @pytest.mark.spec("req-web-panels-chart-hierarchy-2")
    def test_without_a_value_field_each_row_counts_one(self):
        tree, _ = build_tree(self.ROWS[:3], {"hierarchy": {"path": ["eco", "comp"]}})
        assert tree[0]["children"][0] == {"name": "django", "value": 2}

    @pytest.mark.spec("req-web-panels-chart-hierarchy-2")
    def test_a_null_level_is_labelled(self):
        rows = [{"eco": None, "comp": "", "c": 1}]
        tree, _ = build_tree(rows, {"hierarchy": self.H, "null_text": "n/a"})
        assert tree == [{"name": "n/a", "children": [{"name": "(empty)", "value": 1}]}]

    @pytest.mark.spec("req-web-panels-chart-hierarchy-1")
    def test_the_tree_lands_on_treemap_series_and_notes_unusable_rows(self):
        opt = {"series": [{"type": "treemap"}]}
        built = build_option(self.ROWS, _cfg(option=opt, hierarchy=self.H))
        assert built.option["series"][0]["data"][0]["name"] == "pypi"
        assert "dataset" not in built.option
        assert built.notices == ["1 row had no numeric value and is not drawn."]

    @pytest.mark.spec("req-web-panels-chart-hierarchy-3")
    def test_a_single_level_path_gives_flat_leaves(self):
        tree, _ = build_tree(self.ROWS[:4], {"hierarchy": {"path": ["eco"], "value": "c"}})
        assert tree == [{"name": "pypi", "value": 6}, {"name": "npm", "value": 4}]


# ---------------------------------------------------------------------------
# req-web-panels-chart-render  (through the real panel endpoint)
# ---------------------------------------------------------------------------


def _panel(config: dict[str, Any], name: str = "Test Chart") -> Panel:
    panel: Panel = Panel.objects.create(
        slug="chart", name=name, view=ChartPanelType.view, editor_view="", config=config
    )
    return panel


def _bind(panel: Panel, query: list[str]) -> None:
    from tap_grid.models import Edge, Search

    search = Search.objects.create(name="Chart", search_type="gryphon", root="node", definition={"query": query})
    Edge.objects.create(from_entity=panel.entity, to_entity=search.entity, edge_type="USES_SEARCH")


def _seed(links: dict[str, int]) -> None:
    from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
    from tap_grid.models import Edge, Entity

    ctx = get_caller_context()
    assert ctx is not None
    set_caller_context(CallerContext(user=ctx.user, batch_id=str(uuid.uuid4())))
    for name, n in links.items():
        src = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=name)
        for i in range(n):
            tgt = Entity.objects.create(entity_type="grid_fixtures__constrained_target", name=f"{name}/{i}")
            Edge.objects.create(
                entity=Entity.objects.create(entity_type="edge"),
                from_entity=src,
                to_entity=tgt,
                edge_type="CONSTRAINED_LINK__grid_fixtures",
            )


def _get(panel: Panel) -> str:
    response = make_admin_client(username=f"chart-{uuid.uuid4().hex[:8]}").get(
        f"/panel/{panel.slug}--{panel.entity_id}/"
    )
    assert response.status_code == 200
    return str(response.content.decode())


def _option(html: str) -> dict[str, Any]:
    raw = re.search(r'data-tap-chart-option="([^"]*)"', html)
    assert raw, html
    return json.loads(unescape(raw.group(1)))  # type: ignore[no-any-return]


CHART_OPTION = {
    "xAxis": {"type": "category"},
    "yAxis": {"type": "value"},
    "series": [{"type": "bar", "encode": {"x": "source", "y": "n"}}],
}


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestRender:
    @pytest.mark.spec("req-web-panels-chart-render-1")
    def test_search_rows_reach_the_chart_as_its_dataset(self):
        _seed({"alpha": 2, "beta": 1})
        panel = _panel({"option": CHART_OPTION, "types": {"n": "number"}, "sort": {"field": "n"}})
        _bind(panel, _COUNT_BY_SOURCE)
        html = _get(panel)
        assert 'class="tap-panel tap-panel--chart"' in html
        assert f'id="tap-chart-{panel.entity_id}"' in html
        option = _option(html)
        assert option["dataset"]["dimensions"] == ["source", "n"]
        assert option["dataset"]["source"] == [{"source": "alpha", "n": 2}, {"source": "beta", "n": 1}]
        assert option["series"][0]["encode"] == {"x": "source", "y": "n"}

    @pytest.mark.spec("req-web-panels-chart-render-2")
    def test_no_rows_shows_the_configured_empty_text_not_a_blank_frame(self):
        panel = _panel({"option": CHART_OPTION, "empty_text": "Nothing scanned yet."})
        _bind(panel, _COUNT_BY_SOURCE)
        html = _get(panel)
        assert "Nothing scanned yet." in html
        assert "data-tap-chart-option" not in html

    @pytest.mark.spec("req-web-panels-chart-render-3")
    def test_errors_are_stated(self):
        assert "No search linked" in _get(_panel({"option": CHART_OPTION}))
        bad = _panel({"option": {**CHART_OPTION, "title": {"text": "function(){}"}}})
        assert "Invalid chart config" in _get(bad)
        assert 'role="alert"' in _get(bad)
        _seed({"alpha": 1})
        nodes = _panel({"option": CHART_OPTION})
        _bind(nodes, [_COUNT_BY_SOURCE[0], "RETURN a"])
        assert "returned nodes, not rows" in _get(nodes)

    @pytest.mark.spec("req-web-panels-chart-render-4")
    def test_values_are_escaped_and_no_inline_script_is_emitted(self):
        from tap_grid.models import Entity

        _seed({"alpha": 1})
        Entity.objects.filter(name="alpha").update(name="<script>alert(1)</script>")
        panel = _panel({"option": CHART_OPTION})
        _bind(panel, _COUNT_BY_SOURCE)
        html = _get(panel)
        assert not re.search(r"<script", html, re.I)
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html  # the hidden table cell
        assert "<script" not in re.search(r'data-tap-chart-option="([^"]*)"', html).group(1)  # type: ignore[union-attr]

    @pytest.mark.spec("req-web-panels-chart-render-5")
    def test_the_same_data_is_in_a_table_and_the_chart_is_labelled(self):
        _seed({"alpha": 2})
        panel = _panel({"option": CHART_OPTION, "aria_label": "Links per source"})
        _bind(panel, _COUNT_BY_SOURCE)
        html = _get(panel)
        assert 'role="img" aria-label="Links per source: 1 row.' in html
        assert "<caption>Links per source</caption>" in html
        assert '<th scope="col">source</th>' in html and "<td>alpha</td><td>2</td>" in html

    @pytest.mark.spec("req-web-panels-chart-render-6")
    def test_hide_header_and_height(self):
        _seed({"alpha": 1})
        shown = _panel({"option": CHART_OPTION, "height": 410}, name="Shown Heading")
        _bind(shown, _COUNT_BY_SOURCE)
        html = _get(shown)
        assert "<h2" in html and "Shown Heading" in html and "--tap-chart-height: 410px" in html
        hidden = _panel({"option": CHART_OPTION, "hide_header": True, "height": "slot"}, name="Hidden Heading")
        _bind(hidden, _COUNT_BY_SOURCE)
        html = _get(hidden)
        assert "<h2" not in html
        assert "tap-chart--slot" in html and "--tap-chart-height" not in html

    @pytest.mark.spec("req-web-panels-chart-render-7")
    def test_gaps_and_cuts_are_noticed_on_the_page(self):
        _seed({"a": 1, "b": 1, "c": 1})
        panel = _panel({"option": CHART_OPTION, "limit": 2, "types": {"source": "number"}})
        _bind(panel, _COUNT_BY_SOURCE)
        html = _get(panel)
        assert "could not be read as number" in html
        assert "1 more row not drawn." in html

    @pytest.mark.spec("req-web-panels-chart-theme-1")
    def test_the_colour_map_travels_as_data_with_series_by_defaulting_its_field(self):
        _seed({"alpha": 1})
        panel = _panel(
            {
                "option": {**BAR, "series": [{"type": "bar"}]},
                "series_by": {"category": "source", "series": "source", "value": "n"},
                "color_map": {"map": {"alpha": "critical"}},
            }
        )
        _bind(panel, _COUNT_BY_SOURCE)
        html = _get(panel)
        colors = json.loads(unescape(re.search(r'data-tap-chart-colors="([^"]*)"', html).group(1)))  # type: ignore[union-attr]
        assert colors == {"map": {"alpha": "critical"}, "field": "source"}


# ---------------------------------------------------------------------------
# req-web-panels-chart-click
# ---------------------------------------------------------------------------

CLICK = {"row_url_template": "/components/{source}?from=chart"}


class TestClickConfig:
    @pytest.mark.spec("req-web-panels-chart-click-1")
    def test_a_same_origin_template_validates(self):
        validate_config({"option": CHART_OPTION, "click": CLICK})

    @pytest.mark.spec("req-web-panels-chart-click-1")
    @pytest.mark.parametrize(
        "template", ["//evil.example/x", "https://evil.example/x", "javascript:alert(1)", "/a b", "/a\\b", "x", "/", ""]
    )
    def test_anything_but_a_same_origin_path_is_rejected(self, template):
        with pytest.raises(ValidationError):
            validate_config({"option": CHART_OPTION, "click": {"row_url_template": template}})

    @pytest.mark.spec("req-web-panels-chart-click-1")
    def test_the_click_object_is_strict_and_self_describing(self):
        with pytest.raises(ValidationError):
            validate_config({"option": CHART_OPTION, "click": {}})
        with pytest.raises(ValidationError):
            validate_config({"option": CHART_OPTION, "click": {**CLICK, "target": "_blank"}})
        spec = CHART_CONFIG_SCHEMA["properties"]["click"]
        assert spec["description"] and spec["properties"]["row_url_template"]["description"]

    @pytest.mark.spec("req-web-panels-chart-click-3")
    def test_click_needs_a_bar_or_scatter_series_and_excludes_hierarchy(self):
        pie = {"series": [{"type": "pie"}]}
        with pytest.raises(ValidationError, match="bar or scatter"):
            validate_config({"option": pie, "click": CLICK})
        validate_config({"option": {"series": [{"type": "scatter"}]}, "click": CLICK})
        with pytest.raises(ValidationError, match="hierarchy"):
            validate_config(
                {
                    "option": {"series": [{"type": "bar"}, {"type": "treemap"}]},
                    "hierarchy": {"path": ["a"]},
                    "click": CLICK,
                }
            )

    @pytest.mark.spec("req-web-panels-chart-click-3")
    def test_with_series_by_only_the_category_field_may_be_a_placeholder(self):
        sb = {"category": "source", "series": "tool", "value": "n"}
        validate_config({"option": BAR, "series_by": sb, "click": {"row_url_template": "/c/{source}"}})
        with pytest.raises(ValidationError, match="category field"):
            validate_config({"option": BAR, "series_by": sb, "click": {"row_url_template": "/c/{tool}"}})


class TestClickOption:
    ROWS: list[dict[str, Any]] = [{"source": "a b", "n": 2}, {"source": "c&d", "n": 1}, {"source": None, "n": 3}]

    @pytest.mark.spec("req-web-panels-chart-click-2")
    def test_each_dataset_row_carries_its_encoded_url_and_unfillable_rows_none(self):
        option = build_option(self.ROWS, _cfg(option=CHART_OPTION, click=CLICK)).option
        urls = [r.get("_url") for r in option["dataset"]["source"]]
        assert urls == ["/components/a%20b?from=chart", "/components/c%26d?from=chart", None]
        assert option["dataset"]["dimensions"] == ["source", "n"]  # _url is not a drawn dimension

    @pytest.mark.spec("req-web-panels-chart-click-2")
    def test_an_unsafe_template_that_skipped_validation_yields_no_urls(self):
        option = build_option(
            self.ROWS, _cfg(option=CHART_OPTION, click={"row_url_template": "//evil/{source}"})
        ).option
        assert all("_url" not in r for r in option["dataset"]["source"])
        assert "cursor" not in option["series"][0]

    @pytest.mark.spec("req-web-panels-chart-click-3")
    def test_bar_and_scatter_series_get_the_pointer_cursor_and_others_do_not(self):
        series = [
            {"type": "bar", "encode": {"x": "source", "y": "n"}},
            {"type": "scatter", "encode": {"x": "source", "y": "n"}},
            {"type": "line", "encode": {"x": "source", "y": "n"}},
            {"type": "bar", "cursor": "crosshair"},
        ]
        option = build_option(self.ROWS, _cfg(option={**BAR, "series": series}, click=CLICK)).option
        assert [s.get("cursor") for s in option["series"]] == ["pointer", "pointer", None, "crosshair"]

    @pytest.mark.spec("req-web-panels-chart-click-3")
    def test_without_click_nothing_is_added(self):
        option = build_option(self.ROWS, _cfg(option=CHART_OPTION)).option
        assert all("_url" not in r for r in option["dataset"]["source"])
        assert "cursor" not in option["series"][0]

    @pytest.mark.spec("req-web-panels-chart-click-2")
    def test_series_by_gives_each_category_one_url(self):
        rows = [
            {"source": "a", "tool": "x", "n": 1},
            {"source": "a", "tool": "y", "n": 2},
            {"source": "b", "tool": "x", "n": 3},
        ]
        cfg = _cfg(
            option={**BAR, "series": [{"type": "bar"}]},
            series_by={"category": "source", "series": "tool", "value": "n"},
            click={"row_url_template": "/c/{source}"},
        )
        option = build_option(rows, cfg).option
        assert [r["_url"] for r in option["dataset"]["source"]] == ["/c/a", "/c/b"]
        assert all(s["cursor"] == "pointer" for s in option["series"])


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestClickRender:
    @pytest.mark.spec("req-web-panels-chart-click-4")
    def test_the_hidden_data_table_carries_a_real_link_per_clickable_row(self):
        _seed({"alpha": 2, "beta": 1})
        panel = _panel(
            {
                "option": CHART_OPTION,
                "click": {"row_url_template": "/c/{source}"},
                "sort": {"field": "source", "order": "asc"},
            }
        )
        _bind(panel, _COUNT_BY_SOURCE)
        html = _get(panel)
        assert '<th scope="col">Link</th>' in html
        assert re.findall(r'<a href="([^"]*)" data-tap-chart-link>Open (\w+)</a>', html) == [
            ("/c/alpha", "alpha"),
            ("/c/beta", "beta"),
        ]
        option = _option(html)
        assert [r["_url"] for r in option["dataset"]["source"]] == ["/c/alpha", "/c/beta"]
        assert option["series"][0]["cursor"] == "pointer"

    @pytest.mark.spec("req-web-panels-chart-click-4")
    def test_without_click_there_is_no_link_column(self):
        _seed({"alpha": 1})
        panel = _panel({"option": CHART_OPTION})
        _bind(panel, _COUNT_BY_SOURCE)
        html = _get(panel)
        assert "data-tap-chart-link" not in html and ">Link<" not in html


class TestLabelDefaults:
    @pytest.mark.spec("req-web-panels-chart-theme-5")
    def test_the_script_makes_data_labels_solid_by_default_for_every_labelled_series_type(self):
        from pathlib import Path

        script = (Path(__file__).resolve().parents[1] / "static/tap_web/js/chart-panel.js").read_text()
        # the theme: one solid label default shared by the series types that draw data labels
        assert "var solid = { label: { color: text, textBorderWidth: 0," in script
        for key in (
            "bar: solid",
            "line: solid",
            "scatter: solid",
            "heatmap: { label: solid.label }",
            "funnel: { label: solid.label",
        ):
            assert key in script, key
        # and a config's own label object is filled for whatever it leaves unset, never overridden
        assert "if (l.textBorderWidth === undefined) l.textBorderWidth = 0;" in script
        assert 'if (l.color === undefined && key === "label") l.color = text;' in script


@pytest.mark.django_db
class TestPageAssets:
    @pytest.mark.spec("req-web-panels-chart-panel-type-2")
    def test_the_page_pipeline_collects_the_panels_assets(self):
        from tap_web.views import _get_panel_type_for_panel

        assert _get_panel_type_for_panel(_panel({"option": CHART_OPTION})) is ChartPanelType
