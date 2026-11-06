"""The same-origin row-URL rule shared by the Table and Chart panels (tap_web.panels.row_url).

Django-free: the rule is a pattern and a fill function. Spec: req-web-stdpanel-table-rows-5 (the Table's
`row_url_template`) and req-web-stdpanel-table-rows-6 (the one shared implementation).
"""

from __future__ import annotations

import pytest

from tap_web.panels.row_url import fill_row_url, is_same_origin_template, placeholders


@pytest.mark.spec("req-web-stdpanel-table-rows-6")
class TestSameOriginRule:
    @pytest.mark.parametrize("template", ["/x", "/a/b?c={d}", "/a?x={y}&z={w}", "/{a}"])
    def test_a_same_origin_path_passes(self, template):
        assert is_same_origin_template(template)

    @pytest.mark.parametrize(
        "template",
        [
            "",
            "/",
            "//host/x",
            "/\\host",
            "https://evil.example/x",
            "javascript:alert(1)",
            "x/y",
            "/a b",
            "/a\tb",
            "/a\nb",
            "/a\\b",
            None,
            7,
        ],
    )
    def test_anything_else_is_refused(self, template):
        assert not is_same_origin_template(template)

    def test_it_is_the_table_panels_own_pattern(self):
        from tap_web.panels.row_url import ROW_URL_TEMPLATE_PATTERN
        from tap_web.panels.table_panel import TABLE_CONFIG_SCHEMA

        assert TABLE_CONFIG_SCHEMA["properties"]["row_url_template"]["pattern"] == ROW_URL_TEMPLATE_PATTERN


@pytest.mark.spec("req-web-stdpanel-table-rows-6")
class TestFill:
    def test_each_value_is_one_encoded_component(self):
        url = fill_row_url("/c?name={n}&id={i}", {"n": "c++ & more/x", "i": "a=b#c"})
        assert url == "/c?name=c%2B%2B%20%26%20more%2Fx&id=a%3Db%23c"

    def test_a_missing_null_or_empty_value_voids_the_link(self):
        assert fill_row_url("/c?x={a}", {"a": None}) is None
        assert fill_row_url("/c?x={a}", {"a": ""}) is None
        assert fill_row_url("/c?x={a}", {}) is None

    def test_zero_is_a_value(self):
        assert fill_row_url("/c?x={a}", {"a": 0}) == "/c?x=0"

    def test_an_unsafe_template_yields_no_link_even_unvalidated(self):
        assert fill_row_url("//evil/{a}", {"a": "x"}) is None
        assert fill_row_url(None, {"a": "x"}) is None

    def test_placeholders_are_named_once_in_order(self):
        assert placeholders("/a/{b}/{c}?x={b}") == ["b", "c"]
