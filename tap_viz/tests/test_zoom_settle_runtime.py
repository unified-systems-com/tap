"""Settle mode for the zoom constant-scale policy, run under Node against the vendored cytoscape.

`zoom-settle.js` writes fonts, borders, edge widths and icon cards once, after the zoom has been still
(`req-viz-label-sizing-settle`). The behaviour checks (`tap_viz/tests/js/zoom_settle_runtime.mjs`) SKIP where Node or
the vendored cytoscape is missing, as the other runtime checks do; the source tests always run and only prove the
guard is still written.
"""

from __future__ import annotations

import pytest

from tap_viz.tests.node_harness import RUNTIME, assert_ok, run_harness


@pytest.fixture(scope="module")
def settle_checks() -> dict[str, dict[str, object]]:
    return run_harness("zoom_settle_runtime.mjs", RUNTIME / "zoom-settle.js")


@pytest.mark.spec("req-viz-label-sizing-settle-1")
def test_off_unless_enabled(settle_checks) -> None:
    assert_ok(settle_checks, "off-unless-enabled", "malformed-is-off", "inert-handle")


@pytest.mark.spec("req-viz-label-sizing-settle-3")
def test_nothing_is_written_while_zooming(settle_checks) -> None:
    assert_ok(settle_checks, "no-writes-during-zoom", "debounce-ms", "settle-writes-final-zoom")


@pytest.mark.spec("req-viz-label-sizing-settle-4")
def test_formula_clamp_and_constant_size(settle_checks) -> None:
    assert_ok(
        settle_checks,
        "defaults",
        "formula-geometric",
        "formula-constant",
        "clamp-band",
        "constant-on-screen",
        "icon-card-resized",
        "plain-node-size-unchanged",
        "edge-width-settled",
    )


@pytest.mark.spec("req-viz-label-sizing-settle-5")
def test_two_batches_in_order(settle_checks) -> None:
    assert_ok(settle_checks, "batch-1-parents-and-visible", "batch-2-is-a-later-task", "stale-batch-dropped")


@pytest.mark.spec("req-viz-label-sizing-settle-6")
def test_bypass_writes_only(settle_checks) -> None:
    assert_ok(settle_checks, "stylesheet-not-reapplied", "foreign-write-rebased")


@pytest.mark.spec("req-viz-label-sizing-settle-7")
def test_layout_measures_at_the_reference(settle_checks) -> None:
    assert_ok(
        settle_checks, "layout-start-restores-base", "layout-stop-settles", "destroy-restores", "destroy-detaches"
    )


class TestSourceGuards:
    """Always run: the written guards, not the behaviour."""

    SOURCE = (RUNTIME / "zoom-settle.js").read_text(encoding="utf-8")

    @pytest.mark.spec("req-viz-label-sizing-settle-6")
    def test_never_uses_the_append_style_form_or_hide_labels_option(self) -> None:
        code = "\n".join(line for line in self.SOURCE.splitlines() if not line.lstrip().startswith(("*", "//", "/*")))
        assert ".update(" not in code
        assert "cy.style()" not in code
        assert "hideLabelsOnViewport" not in code

    @pytest.mark.spec("req-viz-label-sizing-settle-8")
    def test_texture_is_a_constructor_option_defaulting_off(self) -> None:
        panel = (RUNTIME.parent / "panel-graph.js").read_text(encoding="utf-8")
        assert "textureOnViewport: !!(zoomSettleRaw && zoomSettleRaw.texture_on_viewport === true)" in panel
