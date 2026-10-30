"""Table panel polish: popovers, cell alignment, plain links, striped rows.

These options live in shipped static CSS and JS, so the tests read the stylesheet and script text (the
schema half is in test_table_panel.py, the pure column logic in js/table_columns.test.mjs). The behaviour
itself was measured in a real browser, light and dark (see the spec's Notes column).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "static" / "tap_web"
_CSS = (_STATIC / "css" / "tabulator-minimal.css").read_text(encoding="utf-8")
_THEME = (_STATIC / "css" / "theme.css").read_text(encoding="utf-8")


def _rule(selector: str) -> str:
    """The declaration block of the rule whose selector list is exactly `selector`."""
    match = re.search(rf"(?m)^{re.escape(selector)} \{{([^}}]*)\}}", _CSS)
    assert match, f"no rule for {selector}"
    return match.group(1)


class TestPopover:
    @pytest.mark.spec("req-web-stdpanel-table-config-24")
    @pytest.mark.spec("req-web-theme-surfaces-5")
    def test_the_header_popover_takes_surface_ink_and_rule_from_tokens(self) -> None:
        body = _rule(".tabulator-popup-container")
        for needle in ("background: rgb(var(--tap-white))", "color: rgb(var(--tap-slate-900))", "border: 1px solid rgb(var(--tap-slate-400))"):
            assert needle in body, needle
        assert not re.search(r"#[0-9a-fA-F]{3,6}\b", body), "no literal colour in the popover rule"

    @pytest.mark.spec("req-web-stdpanel-table-config-24")
    def test_the_sortable_header_hover_is_a_token_not_the_library_grey(self) -> None:
        body = _rule(".tabulator .tabulator-header .tabulator-col.tabulator-sortable.tabulator-col-sorter-element:hover")
        assert "background: rgb(var(--tap-slate-100))" in body


_JS = (_STATIC / "js" / "panel-table.js").read_text(encoding="utf-8")
_STAT = (_STATIC / "css" / "stat-cards.css").read_text(encoding="utf-8")
_GRAPH = (Path(__file__).resolve().parents[2] / "tap_viz" / "static" / "tap_viz" / "css" / "panel-graph.css").read_text(
    encoding="utf-8"
)


class TestCellAlignment:
    @pytest.mark.spec("req-web-stdpanel-table-config-25")
    def test_every_built_column_set_is_centred_by_default(self) -> None:
        assert 'if (!col.vertAlign) col.vertAlign = "middle";' in _JS
        assert 'if (!col.hozAlign) col.hozAlign = "left";' in _JS
        assert "return _centred(col);" in _JS  # custom columns
        assert "COMMON_METADATA_COLUMNS.forEach(_centred);" in _JS
        assert "EDGE_COLUMNS.forEach(_centred);" in _JS

    @pytest.mark.spec("req-web-stdpanel-table-config-25")
    def test_long_plain_text_still_ends_in_an_ellipsis(self) -> None:
        body = _rule(".tabulator .tabulator-cell .tap-cell-text")
        for needle in ("min-width: 0", "overflow: hidden", "text-overflow: ellipsis"):
            assert needle in body, needle

    @pytest.mark.spec("req-web-stdpanel-table-config-25")
    def test_the_other_core_tables_centre_vertically(self) -> None:
        assert "border: 0; vertical-align: middle; }" in _STAT
        assert "vertical-align: top" not in _STAT
        assert "vertical-align: top" not in _GRAPH
        assert _GRAPH.count("vertical-align: middle;") >= 2


class TestWrappingColumn:
    @pytest.mark.spec("req-web-stdpanel-table-config-31")
    def test_a_wrap_column_cell_lets_its_text_flow_and_the_row_grow(self) -> None:
        body = _rule(".tabulator .tabulator-cell.tap-col-wrap .tap-cell-text")
        for needle in ("overflow: visible", "text-overflow: clip", "white-space: normal", "overflow-wrap: anywhere"):
            assert needle in body, needle
        assert "nowrap" not in body
        assert not re.search(r"#[0-9a-fA-F]{3,6}\b", body), "no literal colour"

    @pytest.mark.spec("req-web-stdpanel-table-config-31")
    def test_only_a_wrap_true_column_gets_the_class(self) -> None:
        assert 'if (spec.wrap === true) col.cssClass = "tap-col-wrap";' in _JS


class TestPlainLinks:
    @pytest.mark.spec("req-web-stdpanel-table-config-26")
    def test_the_plain_modifier_drops_colour_underline_and_hover_but_keeps_the_focus_ring(self) -> None:
        match = re.search(r"(?m)^\.tabulator \.tap-cell-link--plain,\n(?:.*\n)*?.*:focus-visible \{([^}]*)\}", _CSS)
        assert match, "no plain-link rule"
        assert "color: inherit" in match.group(1) and "text-decoration: none" in match.group(1)
        assert ".tabulator .tap-cell-link--plain:hover" in _CSS
        assert "outline: none" not in _CSS and "outline:none" not in _CSS  # the focus ring stays
        # the plain rule comes after the default link rules, so equal specificity resolves to it
        assert _CSS.index("tap-cell-link--plain,") > _CSS.index(".tabulator .tap-cell-link:focus-visible")

    @pytest.mark.spec("req-web-stdpanel-table-config-26")
    def test_the_three_link_formatters_use_the_class_helper(self) -> None:
        assert 'params && params.style === "plain" ? "tap-cell-link tap-cell-link--plain" : "tap-cell-link"' in _JS
        assert _JS.count("class=\"' + _linkClass(params)") == 3  # externalLink, link, linkList
        assert "externalLink: function (cell, params)" in _JS

    @pytest.mark.spec("req-web-stdpanel-table-config-26")
    def test_style_is_a_described_enum_in_the_schema(self) -> None:
        from tap_web.panels.table_panel import TABLE_CONFIG_SCHEMA, _validate_table_config

        fp = TABLE_CONFIG_SCHEMA["$defs"]["column"]["properties"]["formatter_params"]
        assert fp["description"] and fp["properties"]["style"]["description"]
        assert fp["properties"]["style"]["enum"] == ["default", "plain"]
        col = {"field": "a", "title": "A", "formatter": "link", "formatter_params": {"style": "plain", "external": False}}
        _validate_table_config({"columns": [col]})
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            _validate_table_config({"columns": [{**col, "formatter_params": {"style": "loud"}}]})


def _triplets(block_start: str) -> dict[str, tuple[int, ...]]:
    start = _THEME.index(block_start)
    block = _THEME[start : _THEME.index("\n}", start)]
    return {k: tuple(int(x) for x in v.split()) for k, v in re.findall(r"(--tap-[a-z0-9-]+):\s*(\d+ \d+ \d+);", block)}


def _lum(rgb: tuple[int, ...]) -> float:
    lin = [c / 255 / 12.92 if c / 255 <= 0.03928 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class TestStripedRows:
    @pytest.mark.spec("req-web-stdpanel-table-config-27")
    def test_stripe_tokens_have_a_light_and_a_dark_value(self) -> None:
        light, dark = _triplets(":root {"), _triplets(':root[data-theme="dark"] {')
        for token in ("--tap-table-stripe", "--tap-table-stripe-hover"):
            assert token in light and token in dark
            assert light[token] != dark[token]
        # system-dark block carries the same values (the theme tests also compare the blocks as a whole)
        media = _THEME[_THEME.index("@media (prefers-color-scheme: dark)") :]
        assert f"--tap-table-stripe: {' '.join(map(str, dark['--tap-table-stripe']))};" in media

    @pytest.mark.spec("req-web-stdpanel-table-config-27")
    @pytest.mark.parametrize("scheme", ["light", "dark"])
    def test_text_and_links_stay_readable_on_the_stripe(self, scheme: str) -> None:
        pal = _triplets(":root {" if scheme == "light" else ':root[data-theme="dark"] {')
        for surface in ("--tap-table-stripe", "--tap-table-stripe-hover"):
            assert _ratio(pal["--tap-slate-900"], pal[surface]) >= 4.5, surface
            assert _ratio(pal["--tap-slate-600"], pal[surface]) >= 4.5, surface  # secondary ink
            link = pal["--tap-blue-700"]
            assert _ratio(link, pal[surface]) >= 4.5, surface
        # subtle: the stripe is close to the plain row, never a different hue family
        assert _ratio(pal["--tap-white"], pal["--tap-table-stripe"]) < 1.25

    @pytest.mark.spec("req-web-stdpanel-table-config-27")
    def test_the_stripe_rule_skips_group_bands_and_keeps_the_clickable_wash(self) -> None:
        assert ".tabulator.tap-table--striped .tabulator-row.tabulator-row-even:not(.tabulator-group) { background: rgb(var(--tap-table-stripe)); }" in _CSS
        assert ".tap-row--clickable:not(.tabulator-group):hover { background: var(--tap-table-row-link-hover); }" in _CSS


class TestTableEmptyText:
    @pytest.mark.spec("req-web-stdpanel-table-config-30")
    def test_the_client_escapes_the_mount_attribute_into_the_placeholder(self) -> None:
        assert 'mountEl.getAttribute("data-tap-table-empty-text")' in _JS
        assert "tableOptions.placeholder = _escapeHtml(emptyText);" in _JS
        assert 'placeholder: "No results."' in _JS  # the default stays
