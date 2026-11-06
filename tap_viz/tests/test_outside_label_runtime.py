"""An outside label anchors to a side, and a box can be a transparent line (`req-viz-system-display-hints-9`, `-10`).

`chrome.js` `placeParentLabels` puts a container's label where the model's `label` display hint says,
including outside the box at its left, right or centre; `panel-graph.js` carries the `fill_opacity` and
`border_width` hints to Cytoscape. A compliance boundary uses all three to look like the FedRAMP
authorization boundary: a transparent box, a bold line, its title outside at the top left.

The behaviour tests run `chrome.js` under Node against the vendored cytoscape, headless, and SKIP where
either is missing (the runtime image has no Node; cytoscape arrives at image build): `TAP_NODE` /
`TAP_CYTOSCAPE_JS` name them. The source tests always run and prove only that the wiring is written.
"""

from __future__ import annotations

import pytest

from tap_viz.tests.node_harness import REPO, RUNTIME, assert_ok, run_harness

PANEL_GRAPH = REPO / "tap_viz" / "static" / "tap_viz" / "js" / "panel-graph.js"


@pytest.fixture(scope="module")
def outside_label_checks() -> dict[str, dict[str, object]]:
    return run_harness("outside_label_runtime.mjs", RUNTIME / "chrome.js")


@pytest.mark.spec("req-viz-system-display-hints-10")
def test_outside_label_stands_above_the_box_anchored_to_its_side(outside_label_checks) -> None:
    assert_ok(
        outside_label_checks,
        "outside-left-valign",
        "outside-left-shift",
        "outside-left-above-edge",
        "outside-right-shift",
        "outside-center-no-shift",
    )


@pytest.mark.spec("req-viz-system-display-hints-10")
def test_a_node_without_an_outside_hint_keeps_the_inside_label(outside_label_checks) -> None:
    assert_ok(outside_label_checks, "inside-unchanged")


@pytest.mark.spec("req-viz-system-display-hints-9")
def test_graph_panel_carries_box_chrome_hints_to_cytoscape() -> None:
    source = PANEL_GRAPH.read_text(encoding="utf-8")
    assert 'typeof tapViz.fill_opacity === "number"' in source and "data.fill_opacity" in source
    assert 'typeof tapViz.border_width === "number"' in source and "data.border_width" in source
    for selector in (
        '"node[fill_opacity]"',
        '":parent[fill_opacity]"',
        '"node[border_width]"',
        '":parent[border_width]"',
    ):
        assert selector in source
    # The chrome rules come after the palette rules they override, and before the label-position rule.
    assert source.index('"node[fill_opacity]"') > source.rindex('":parent[fill_color]"')
    assert source.index('"node[border_width]"') < source.index('"node[label_valign][label_halign]"')


@pytest.mark.spec("req-viz-system-display-hints-10")
def test_graph_panel_keeps_the_requested_side_of_an_outside_label() -> None:
    source = PANEL_GRAPH.read_text(encoding="utf-8")
    assert 'data.label_position = "outside";' in source and "data.label_anchor = label.halign;" in source
