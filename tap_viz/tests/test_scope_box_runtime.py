"""Scope boxes do not recurse or draw while hidden.

`layout-scope-boxes.js` threw `RangeError: Maximum call stack size exceeded` from `syncBoxes` when a
labelled box was drawn over members of a compound while the projection was still revealing the scene
(`req-viz-layout-scope-box`).

Two kinds of test, and which is which matters:

* The behaviour tests run the browser modules under Node against the vendored cytoscape, headless, with
  the handful of DOM calls faked (`tap_viz/tests/js/*.mjs`). TAP's runtime image carries no Node and the
  vendored cytoscape arrives at image build, so they SKIP where either is missing, and run on a developer
  machine with both (`TAP_NODE` / `TAP_CYTOSCAPE_JS` name them when they are not on the default path).
* The source tests always run. They only prove the guard is still written, not that it works: a presence
  check, never a substitute for the behaviour tests.
"""

from __future__ import annotations

import pytest

from tap_viz.tests.node_harness import RUNTIME, assert_ok, run_harness


@pytest.fixture(scope="module")
def scope_box_checks() -> dict[str, dict[str, object]]:
    return run_harness("scope_box_runtime.mjs", RUNTIME / "layout-scope-boxes.js")


@pytest.mark.spec("req-viz-layout-scope-box-1")
def test_reentrant_bounds_do_not_recurse(scope_box_checks) -> None:
    assert_ok(scope_box_checks, "reentrant-bounds")


@pytest.mark.spec("req-viz-layout-scope-box-2")
def test_hidden_graph_element_is_not_measured_or_drawn(scope_box_checks) -> None:
    assert_ok(
        scope_box_checks,
        "hidden-not-measured",
        "hidden-not-drawn",
        "hidden-move-still-not-measured",
        "display-none-not-drawn",
    )


@pytest.mark.spec("req-viz-layout-scope-box-3")
def test_shown_graph_element_draws_on_the_next_render(scope_box_checks) -> None:
    assert_ok(scope_box_checks, "shown-draws-on-render")


@pytest.mark.spec("req-viz-layout-scope-box-4")
def test_scope_box_source_carries_both_guards_in_the_one_sync_path() -> None:
    source = (RUNTIME / "layout-scope-boxes.js").read_text(encoding="utf-8")
    sync = source[source.index("function syncBoxes()") : source.index("function drawDeferred()")]
    assert "if (syncing) return;" in sync and "syncing = true;" in sync and "finally" in sync
    assert "containerHidden()" in sync
    assert 'cy.on("render", drawDeferred);' in source and 'cy.off("render", drawDeferred);' in source
