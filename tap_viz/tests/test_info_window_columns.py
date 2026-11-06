"""info_window.columns outside the JSON schema: rendering, CSS and width (req-viz-info-window-columns).

The schema is covered by `test_models.py::TestInfoWindowColumnsSchema`. Rendering lives in
browser JavaScript, so it is covered two ways: `js/info_window_columns.test.mjs` runs the real
`renderInfoTable` under `node --test` (skipped, loudly, where node is absent), and the tests here
read the shipped source and stylesheet, which need neither node nor Django.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

TAP_VIZ = Path(__file__).resolve().parents[1]
JS_TEST = TAP_VIZ / "tests" / "js" / "info_window_columns.test.mjs"
CSS = (TAP_VIZ / "static" / "tap_viz" / "css" / "panel-graph.css").read_text(encoding="utf-8")
WINDOW_JS = (TAP_VIZ / "static" / "tap_viz" / "js" / "runtime" / "info-window.js").read_text(encoding="utf-8")


def _rules() -> str:
    """The CSS text from the info-window section start to the stack tooltip section."""
    start = CSS.index("/* Status badge info window")
    end = CSS.index("/* Stack count tooltip")
    return CSS[start:end]


@pytest.mark.spec("req-viz-info-window-columns-3")
@pytest.mark.spec("req-viz-info-window-columns-4")
@pytest.mark.spec("req-viz-info-window-columns-5")
@pytest.mark.spec("req-viz-info-window-columns-6")
@pytest.mark.spec("req-viz-info-window-columns-7")
@pytest.mark.spec("req-viz-info-window-columns-8")
@pytest.mark.spec("req-viz-info-window-columns-15")
@pytest.mark.spec("req-viz-info-window-columns-17")
def test_js_rendering() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed here; the rendering assertions in info_window_columns.test.mjs did not run")
    result = subprocess.run(  # noqa: S603  # nosec B603  # nosemgrep - fixed argv, repo-owned test file
        [node, "--test", str(JS_TEST)], capture_output=True, text=True, check=False, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.spec("req-viz-info-window-columns-4")
def test_header_is_visible_and_sticky_for_columns_tables_only() -> None:
    css = _rules()
    # Legacy header stays hidden; the columns modifier un-hides it and pins it.
    assert re.search(r"\.tap-info-window__table thead\s*\{\s*display:\s*none", css)
    assert re.search(r"\.tap-info-window__table--columns thead\s*\{\s*display:\s*table-header-group", css)
    th = re.search(r"\.tap-info-window__table--columns th\s*\{([^}]*)\}", css)
    assert th is not None
    assert "position: sticky" in th.group(1) and "top: 0" in th.group(1)
    assert "background:" in th.group(1), "a sticky header needs an opaque background"
    body = re.search(r"\.tap-info-window__body\s*\{([^}]*)\}", css)
    assert body is not None and "overflow-y: auto" in body.group(1), "sticky needs the scrolling body ancestor"


@pytest.mark.spec("req-viz-info-window-columns-9")
def test_wide_window_is_content_sized_between_280_and_560_inside_the_panel() -> None:
    wide = re.search(r"\.tap-info-window--wide\s*\{([^}]*)\}", _rules())
    assert wide is not None
    decl = wide.group(1)
    assert "width: max-content" in decl
    assert "min-width: 280px" in decl
    assert "max-width: min(560px, 100%)" in decl
    # Single-column windows keep the fixed width: JS sets it unless the window is wide.
    assert "if (!wide) el.style.width" in WINDOW_JS
    assert "const DEFAULT_WIDTH_PX = 280;" in WINDOW_JS


@pytest.mark.spec("req-viz-info-window-columns-13")
def test_nowrap_class_is_a_stylesheet_rule_and_width_rules_are_unchanged() -> None:
    css = _rules()
    nowrap = re.search(r"\.tap-info-window__cell--nowrap\s*\{([^}]*)\}", css)
    assert nowrap is not None
    assert "white-space: nowrap" in nowrap.group(1)
    assert "style=" not in WINDOW_JS.split("function _renderColumnsTable")[1].split("function _renderTable")[0]
    wide = re.search(r"\.tap-info-window--wide\s*\{([^}]*)\}", css)
    assert wide is not None
    assert "min-width: 280px" in wide.group(1) and "max-width: min(560px, 100%)" in wide.group(1)


@pytest.mark.spec("req-viz-info-window-columns-10")
def test_info_window_colours_are_theme_tokens_with_light_and_dark_values() -> None:
    css = _rules()
    token_names = set(re.findall(r"(--tap-info-[a-z-]+):", css))
    assert token_names, "no --tap-info-* tokens defined"
    # Each token has a light value, a prefers-color-scheme dark value and a data-theme="dark" value.
    light = re.search(r"\n\.tap-info-window\s*\{([^}]*)\}", css)
    scheme = re.search(
        r'prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme="light"\]\) \.tap-info-window\s*\{([^}]*)\}', css
    )
    forced = re.search(r':root\[data-theme="dark"\] \.tap-info-window\s*\{([^}]*)\}', css)
    assert light and scheme and forced
    for block in (light, scheme, forced):
        assert token_names <= set(re.findall(r"(--tap-info-[a-z-]+):", block.group(1)))
    # No colour literal outside those three token blocks.
    remainder = css
    for block in (light, scheme, forced):
        remainder = remainder.replace(block.group(1), "")
    literals = re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", remainder)
    assert not literals, f"colour literals outside the token blocks: {literals}"


@pytest.mark.spec("req-viz-info-window-columns-18")
def test_tone_badge_colours_are_tokens_defined_in_every_scheme() -> None:
    css = _rules()
    names = [f"--tap-info-tone-{tone}-{part}" for tone in ("good", "warn", "bad", "muted") for part in ("bg", "fg")]
    for name in names:
        # Defined in the light block, the prefers-dark block and the forced-dark block.
        assert len(re.findall(re.escape(name) + r":\s*#", css)) == 3, name
    for tone in ("good", "warn", "bad"):
        rule = re.search(r"\.tap-info-window__tone--" + tone + r"\s*\{([^}]*)\}", css)
        assert rule is not None and f"var(--tap-info-tone-{tone}-bg)" in rule.group(1)
        assert f"var(--tap-info-tone-{tone}-fg)" in rule.group(1)
    assert "tap-info-window__tone--${tone}" in WINDOW_JS
