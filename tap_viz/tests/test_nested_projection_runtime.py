"""Per-container layout override and the `ranked` rows axis, run under Node against the vendored cytoscape.

The behaviour checks (`tap_viz/tests/js/nested_projection_runtime.mjs`) SKIP where Node or the vendored cytoscape is
missing, as the other runtime checks do; the source tests always run and prove the contract is still written.
"""

from __future__ import annotations

import pytest

from tap_viz.tests.node_harness import RUNTIME, assert_ok, run_harness

SOURCE = (RUNTIME / "nested-projection.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def nested_checks() -> dict[str, dict[str, object]]:
    return run_harness("nested_projection_runtime.mjs", RUNTIME / "nested-projection.js")


@pytest.mark.spec("req-viz-nested-projection-container-size-from-children-5")
def test_override_source_is_wired() -> None:
    assert 'parentNode.data("_inner_layout")' in SOURCE
    assert "_resolveLayoutFn(parentNode, innerLayout, innerLayouts, override)" in SOURCE
    assert "if (override) spec = override;" in SOURCE
    assert "invalid_inner_layout" in SOURCE


@pytest.mark.spec("req-viz-nested-projection-container-size-from-children-5")
def test_override_behaviour(nested_checks) -> None:
    assert_ok(nested_checks, "override-leaves-sibling-type-alone", "override-beats-per-type", "malformed-override-warns")


@pytest.mark.spec("req-viz-nested-projection-natural-layouts-8")
def test_ranked_rows_source_is_wired() -> None:
    assert 'opts.axis === "rows"' in SOURCE


@pytest.mark.spec("req-viz-nested-projection-natural-layouts-8")
def test_ranked_rows_behaviour(nested_checks) -> None:
    assert_ok(
        nested_checks,
        "rows-leader-above-row",
        "rows-leader-centred",
        "rows-children-share-a-line",
        "rows-children-side-by-side",
        "rows-container-size",
        "rows-no-warnings",
        "rows-reentry-stable",
        "rows-rtl-leader-below",
        "rows-unranked-trails-with-warning",
        "default-columns-unchanged",
    )
