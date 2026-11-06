"""Table panel link affordance (req-web-stdpanel-table-config-16, -17, -18).

The formatters and the row formatter live in shipped static JS and the colours in a stylesheet, so
these tests read both files: the anchors carry the styled class, a navigating row carries the
clickable class instead of an inline style, and the stylesheet's token pairs reach 4.5:1.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "static" / "tap_web"
_CSS = (_STATIC / "css" / "tabulator-minimal.css").read_text()
_JS = (_STATIC / "js" / "panel-table.js").read_text()


def _luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


_THEME = (Path(__file__).resolve().parents[1] / "static" / "tap_web" / "css" / "theme.css").read_text(encoding="utf-8")


def _palette(dark: bool) -> dict[str, str]:
    """Palette name to hex, from the light block of theme.css or its forced-dark block."""
    start = _THEME.index(':root[data-theme="dark"] {' if dark else ":root {")
    block = _THEME[start : _THEME.index("}", start)]
    return {
        k: "#" + "".join(f"{int(x):02x}" for x in v.split())
        for k, v in re.findall(r"(--tap-[a-z0-9-]+):\s*(\d+ \d+ \d+);", block)
    }


def _token(name: str, dark: bool = False) -> str:
    """A table token as hex: a literal, or a `rgb(var(--tap-...))` palette reference resolved for the theme."""
    match = re.search(rf"{re.escape(name)}:\s*(#[0-9a-fA-F]{{6}}|rgb\(var\((--tap-[a-z0-9-]+)\)\))\s*;", _CSS)
    assert match, f"token {name} is not defined in tabulator-minimal.css"
    return _palette(dark)[match.group(2)] if match.group(2) else match.group(1)


class TestLinkAffordance:
    @pytest.mark.spec("req-web-stdpanel-table-config-16")
    def test_stylesheet_colours_and_underlines_cell_links_with_a_focus_ring(self) -> None:
        link_rule = re.search(r"\.tabulator \.tap-cell-link \{([^}]*)\}", _CSS)
        assert link_rule, "no base rule for .tap-cell-link"
        assert "color: var(--tap-table-link)" in link_rule.group(1)
        assert "text-decoration: underline" in link_rule.group(1)
        # the default link is never undecorated; only the opt-in plain modifier (config-26) is
        assert "text-decoration: none" not in _CSS.split("/* Plain links")[0]
        assert ".tabulator .tap-cell-link:hover" in _CSS
        focus = re.search(r"\.tap-cell-link:focus-visible \{([^}]*)\}", _CSS)
        assert focus and "outline: 2px solid" in focus.group(1)

    @pytest.mark.spec("req-web-stdpanel-table-config-16")
    def test_every_anchor_the_script_builds_carries_the_link_class(self) -> None:
        anchors = [_JS[m.start() : m.start() + 260] for m in re.finditer(r"<a href=", _JS)]
        assert len(anchors) >= 4  # externalLink, link, the icon link, linkList items
        assert all('class="tap-cell-link"' in a or "class=\"' + _linkClass(params) + '\"" in a for a in anchors)

    @pytest.mark.spec("req-web-stdpanel-table-config-17")
    def test_row_url_rows_get_a_class_not_an_inline_style(self) -> None:
        assert 'classList.add("tap-row--clickable")' in _JS
        raw = _JS[_JS.index('} else if (mode === "raw") {') :]
        assert "style.cursor" not in raw.split("/* global Tabulator */")[0]
        rule = re.search(r"\.tap-row--clickable \{([^}]*)\}", _CSS)
        assert rule and "cursor: pointer" in rule.group(1)
        assert ".tabulator-row.tap-row--clickable:hover" in _CSS

    @pytest.mark.spec("req-web-stdpanel-table-config-17")
    def test_tables_without_row_urls_are_not_restyled(self) -> None:
        # Only the class on a row changes its cursor or hover; the base row rules are untouched.
        assert ".tabulator .tabulator-row:hover { background: rgb(var(--tap-slate-50)); }" in _CSS
        assert ".tabulator .tabulator-row { cursor" not in _CSS

    @pytest.mark.spec("req-web-stdpanel-table-config-18")
    def test_link_colours_reach_4_5_to_1_on_their_surface(self) -> None:
        row = "#ffffff"
        wash = _token("--tap-table-row-link-hover")
        assert _contrast(_token("--tap-table-link"), row) >= 4.5
        assert _contrast(_token("--tap-table-link-hover"), row) >= 4.5
        assert _contrast(_token("--tap-table-link"), wash) >= 4.5
        assert _contrast(_token("--tap-table-link-hover"), wash) >= 4.5
        assert _contrast(_token("--tap-table-link-focus"), row) >= 3.0

    @pytest.mark.spec("req-web-theme-contrast-1")
    def test_link_colours_reach_4_5_to_1_in_the_dark_theme_too(self) -> None:
        dark = _palette(True)
        row = dark["--tap-white"]
        wash = _token("--tap-table-row-link-hover", dark=True)
        for name in ("--tap-table-link", "--tap-table-link-hover"):
            assert _contrast(_token(name, dark=True), row) >= 4.5
            assert _contrast(_token(name, dark=True), wash) >= 4.5
