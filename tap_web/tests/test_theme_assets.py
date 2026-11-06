"""The colour theme (spec-web-theme.md): palette tokens, the no-flash script, the switch, the Tailwind bridge.

The theme is CSS, a small script and templates, so these tests read the shipped files (no Django, no database); the
rendered behaviour is proven in a real browser (`req-web-theme-surfaces-3`, `req-web-theme-contrast-1`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TAP_WEB = Path(__file__).resolve().parents[1]
REPO = TAP_WEB.parent
CSS_DIR = TAP_WEB / "static" / "tap_web" / "css"
JS_DIR = TAP_WEB / "static" / "tap_web" / "js"
TEMPLATES = TAP_WEB / "templates"
THEME_CSS = (CSS_DIR / "theme.css").read_text(encoding="utf-8")


def _decls(block: str) -> dict[str, str]:
    return dict(re.findall(r"(--tap-[a-z0-9-]+)\s*:\s*([^;]+);", block))


def _block(opening: str) -> str:
    """The declaration text of the first rule starting at `opening`, including nested blocks."""
    start = THEME_CSS.index(opening)
    brace = THEME_CSS.index("{", start)
    depth, i = 1, brace + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(THEME_CSS[i], 0)
        i += 1
    return THEME_CSS[brace + 1 : i - 1]


LIGHT = _decls(_block(":root {"))
SYSTEM_DARK = _decls(_block("@media (prefers-color-scheme: dark)"))
FORCED_DARK = _decls(_block(':root[data-theme="dark"] {'))


@pytest.mark.spec("req-web-theme-tokens-1")
def test_every_light_token_has_a_dark_value() -> None:
    assert len(LIGHT) > 100
    assert not set(LIGHT) - set(SYSTEM_DARK), sorted(set(LIGHT) - set(SYSTEM_DARK))
    assert not set(LIGHT) - set(FORCED_DARK), sorted(set(LIGHT) - set(FORCED_DARK))


@pytest.mark.spec("req-web-theme-tokens-2")
def test_the_two_dark_blocks_are_identical() -> None:
    assert SYSTEM_DARK == FORCED_DARK


@pytest.mark.spec("req-web-theme-tokens-3")
def test_forced_light_beats_a_dark_system_setting() -> None:
    assert '@media (prefers-color-scheme: dark) {\n  :root:not([data-theme="light"])' in THEME_CSS


@pytest.mark.spec("req-web-theme-tokens-4")
def test_palette_values_are_rgb_triplets() -> None:
    for name, value in {**LIGHT, **FORCED_DARK}.items():
        assert re.fullmatch(r"\d{1,3} \d{1,3} \d{1,3}", value.strip()), (name, value)


# --- the no-flash script -------------------------------------------------------------------------------------------

THEME_INIT = (JS_DIR / "theme-init.js").read_text(encoding="utf-8")
FULL_PAGES = [
    TEMPLATES / "tap_web" / "base.html",
    TEMPLATES / "allauth" / "layouts" / "base.html",
    *sorted((TEMPLATES / "tap_web" / "auth").glob("*.html")),
]


def _is_full_page(path: Path) -> bool:
    return "<html" in path.read_text(encoding="utf-8")


@pytest.mark.spec("req-web-theme-init-1")
def test_head_script_is_blocking_and_before_stylesheets() -> None:
    head = (TEMPLATES / "tap_web" / "partials" / "theme_head.html").read_text(encoding="utf-8")
    init = re.search(r"<script[^>]*theme-init\.js[^>]*>", head)
    assert init and "defer" not in init.group(0) and "async" not in init.group(0)
    base = (TEMPLATES / "tap_web" / "base.html").read_text(encoding="utf-8")
    assert base.index("theme_head.html") < base.index("css/tailwind.css")
    assert base.index("theme_head.html") < base.index("</head>")


@pytest.mark.spec("req-web-theme-init-2")
def test_init_script_guards_storage_and_defaults_to_system() -> None:
    assert re.search(r"try\s*\{[^}]*localStorage", THEME_INIT)
    assert "catch" in THEME_INIT
    assert 'removeAttribute("data-theme")' in THEME_INIT


@pytest.mark.spec("req-web-theme-init-3")
def test_every_full_page_includes_the_theme_head() -> None:
    pages = [p for p in FULL_PAGES if _is_full_page(p)]
    assert len(pages) >= 9
    for page in pages:
        assert "theme_head.html" in page.read_text(encoding="utf-8"), page.name


# --- the switch ------------------------------------------------------------------------------------------------------

SWITCH = (TEMPLATES / "tap_web" / "partials" / "theme_switch.html").read_text(encoding="utf-8")
TOGGLE_JS = (JS_DIR / "theme-toggle.js").read_text(encoding="utf-8")


@pytest.mark.spec("req-web-theme-toggle-1")
def test_the_switch_is_in_every_header() -> None:
    for choice in ("light", "auto", "dark"):
        assert f'data-tap-theme-set="{choice}"' in SWITCH
    for page in FULL_PAGES:
        if _is_full_page(page):
            assert "theme_switch.html" in page.read_text(encoding="utf-8"), page.name


@pytest.mark.spec("req-web-theme-toggle-2")
def test_the_switch_is_accessible() -> None:
    assert 'role="group"' in SWITCH and 'aria-label="Colour theme"' in SWITCH
    assert SWITCH.count("aria-pressed") == 3
    assert SWITCH.count('aria-label="') == 4


@pytest.mark.spec("req-web-theme-toggle-3")
def test_a_change_is_announced_and_nothing_is_written_with_inner_html() -> None:
    assert "tap:themechange" in TOGGLE_JS
    for script in (THEME_INIT, TOGGLE_JS):
        assert "innerHTML" not in script


# --- the Tailwind bridge ---------------------------------------------------------------------------------------------

TAILWIND_CSS = (CSS_DIR / "tailwind.css").read_text(encoding="utf-8")


@pytest.mark.spec("req-web-theme-tailwind-1")
def test_compiled_tailwind_draws_its_palette_from_variables() -> None:
    assert "rgb(var(--tap-slate-" in TAILWIND_CSS and "rgb(var(--tap-canvas)" in TAILWIND_CSS
    for rule in re.findall(r"\.(?:bg|text|border)-(?:slate|gray|red|green|amber|blue|indigo)-\d+\{[^}]*\}", TAILWIND_CSS):
        assert "var(--tap-" in rule, rule


@pytest.mark.spec("req-web-theme-tailwind-2")
def test_white_surface_follows_the_theme() -> None:
    assert re.search(r"\.bg-white\s*\{\s*background-color:\s*rgb\(var\(--tap-white\)\)", THEME_CSS)


@pytest.mark.spec("req-web-theme-tailwind-3")
def test_no_template_pairs_white_text_with_a_palette_fill() -> None:
    palette_fill = re.compile(r"\bbg-(?:slate|gray|red|green|amber|blue|indigo)-\d+\b")
    for path in TEMPLATES.rglob("*.html"):
        for match in re.finditer(r'class="([^"]*)"', path.read_text(encoding="utf-8")):
            classes = match.group(1)
            if re.search(r"(?<![-\w:])text-white\b", classes):
                assert not palette_fill.search(classes), (path.name, classes)


# --- every surface uses tokens ---------------------------------------------------------------------------------------

LITERAL = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|rgba?\(\s*\d")
# Stylesheets that own a token set (the literals ARE the token values) or define the palette itself.
TOKEN_OWNERS = {"theme.css", "panel-chart.css", "stat-cards.css", "tailwind.css", "tailwind-input.css"}
# Fixed by design: shadows, and the dark header bar's own light text and washes.
FIXED = ("shadow", "rgba(0, 0, 0", "rgba(15, 23, 42", "rgba(255, 255, 255", "rgb(226, 232, 240)", "rgb(255, 255, 255)",
         "rgb(203, 213, 225)", "rgb(148, 163, 184)", "rgb(71, 85, 105)", "rgb(100, 116, 139)", "#fcd34d", "color: #fff")


def _declaration_lines(css: str) -> list[str]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [ln.strip() for ln in css.splitlines() if ":" in ln]


@pytest.mark.spec("req-web-theme-surfaces-1")
def test_core_stylesheets_carry_no_theme_blind_colour_literals() -> None:
    offenders: list[str] = []
    for path in sorted(CSS_DIR.glob("*.css")):
        if path.name in TOKEN_OWNERS:
            continue
        for ln in _declaration_lines(path.read_text(encoding="utf-8")):
            if LITERAL.search(ln) and not any(f in ln for f in FIXED):
                offenders.append(f"{path.name}: {ln}")
    assert not offenders, "\n".join(offenders)


@pytest.mark.spec("req-web-theme-surfaces-2")
def test_table_cells_use_palette_tokens() -> None:
    js = (JS_DIR / "panel-table.js").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in js.splitlines() if not ln.strip().startswith(("//", "*", "/*")))
    assert not re.findall(r"""["'(:]\s*#[0-9a-fA-F]{6}\b""", code)
    assert "rgb(var(--tap-" in code
    assert 'fill="' not in re.sub(r"\s+", " ", code).replace('fill="none"', "")


@pytest.mark.spec("req-web-theme-surfaces-4")
def test_form_controls_take_the_theme_at_zero_specificity() -> None:
    assert ":where(input, select, textarea)" in THEME_CSS


# --- the graph canvas is theme-invariant ----------------------------------------------------------------------------

GRAPH_CSS = (REPO / "tap_viz" / "static" / "tap_viz" / "css" / "panel-graph.css").read_text(encoding="utf-8")


@pytest.mark.spec("req-web-theme-graph-1")
def test_graph_canvas_background_is_theme_invariant() -> None:
    assert "--tap-graph-bg" not in SYSTEM_DARK and "--tap-graph-bg" not in FORCED_DARK
    assert re.search(r"--tap-graph-bg:\s*241 240 236;", THEME_CSS)
    match = re.search(r"\.tap-cy-static-grid\s*\{([^}]*)\}", GRAPH_CSS)
    assert match is not None
    rule = match.group(1)
    assert "rgb(var(--tap-graph-bg))" in rule and "rgb(var(--tap-graph-grid))" in rule
    assert not re.search(r"prefers-color-scheme[^{]*\{[^{]*tap-cy-static-grid", GRAPH_CSS)


@pytest.mark.spec("req-web-theme-graph-2")
def test_graph_script_keeps_light_colours_inside_the_canvas() -> None:
    js = (REPO / "tap_viz" / "static" / "tap_viz" / "js" / "panel-graph.js").read_text(encoding="utf-8")
    assert "tap:themechange" not in js and "--tap-" not in js


@pytest.mark.spec("req-web-theme-graph-3")
def test_info_window_outside_the_canvas_follows_the_theme() -> None:
    assert ':root[data-theme="dark"] .tap-info-window' in GRAPH_CSS


# --- the header bar ------------------------------------------------------------------------------------------------


def _hex(triplet: str) -> tuple[float, float, float]:
    return tuple(int(x) / 255 for x in triplet.split())  # type: ignore[return-value]


def _lum(triplet: str) -> float:
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in _hex(triplet)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.spec("req-web-theme-header-1")
@pytest.mark.parametrize("tokens", [LIGHT, FORCED_DARK], ids=["light", "dark"])
def test_header_text_reaches_4_5_to_1_on_the_bar(tokens: dict[str, str]) -> None:
    bar = tokens["--tap-header-bg"]
    for name in ("fg", "link", "dim", "session"):
        assert _ratio(tokens[f"--tap-header-{name}"], bar) >= 4.5, name
    assert _ratio("255 255 255", tokens["--tap-header-avatar"]) >= 4.5


@pytest.mark.spec("req-web-theme-header-2")
def test_header_is_a_light_bar_in_light_and_its_own_dark_bar_in_dark() -> None:
    assert LIGHT["--tap-header-bg"] == LIGHT["--tap-canvas"]
    assert _lum(LIGHT["--tap-header-bg"]) > 0.5 > 0.1 > _lum(FORCED_DARK["--tap-header-bg"])
    assert "border-bottom: 1px solid rgb(var(--tap-header-border))" in THEME_CSS


@pytest.mark.spec("req-web-theme-toggle-5")
def test_the_switch_sits_in_the_user_menu() -> None:
    base = (TEMPLATES / "tap_web" / "base.html").read_text(encoding="utf-8")
    menu = base[base.index('<details class="tap-usermenu"') : base.index("</details>")]
    assert "theme_switch.html" in menu
    # a signed-out page has no menu, so the only other include is the guarded inline one
    assert base.count("theme_switch.html") == 2 and "not request.user.is_authenticated" in base
