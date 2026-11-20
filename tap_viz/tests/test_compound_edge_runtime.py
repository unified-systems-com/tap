"""A compound edge is drawn as one arrow (`req-viz-compound-edge`, `tap_viz/specs/spec-viz-compound-edge.md`).

Two kinds of test, as for the scope-box runtime:

* The behaviour tests run `runtime/compound-edge.js` under Node against the vendored cytoscape, headless
  (`tap_viz/tests/js/compound_edge_runtime.mjs`). TAP's runtime image carries no Node and the vendored
  cytoscape arrives at image build, so they SKIP where either is missing; `TAP_NODE` / `TAP_CYTOSCAPE_JS`
  name them when they are not on the default path.
* The source and server tests always run. The source tests only prove the panel still wires the runtime's
  class and data, never that the runtime works.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tap_viz.tests.node_harness import RUNTIME, assert_ok, run_harness

PANEL = Path(RUNTIME).parent / "panel-graph.js"


@pytest.fixture(scope="module")
def compound_checks() -> dict[str, dict[str, object]]:
    return run_harness("compound_edge_runtime.mjs", RUNTIME / "compound-edge.js")


@pytest.mark.spec("req-viz-compound-edge-1")
def test_middle_node_and_role_edges_collapse_into_one_arrow(compound_checks) -> None:
    assert_ok(compound_checks, "collapse-hides-middle-and-roles", "one-synthetic-arrow", "count-and-skipped")


@pytest.mark.spec("req-viz-compound-edge-2")
def test_an_end_that_is_not_drawn_gets_no_arrow(compound_checks) -> None:
    assert_ok(compound_checks, "end-not-drawn-left-alone")


@pytest.mark.spec("req-viz-compound-edge-3")
def test_tap_expands_and_collapses(compound_checks) -> None:
    assert_ok(compound_checks, "expand-on-arrow-tap", "collapse-on-middle-tap")


@pytest.mark.spec("req-viz-compound-edge-4")
def test_rerun_is_idempotent_and_destroy_restores(compound_checks) -> None:
    assert_ok(compound_checks, "idempotent-rerun", "destroy-restores")


@pytest.mark.spec("req-viz-compound-edge-5")
def test_roles_come_from_the_node_and_types_filter(compound_checks) -> None:
    assert_ok(compound_checks, "types-filter", "all-middle-nodes-by-default")


@pytest.mark.spec("req-viz-compound-edge-5")
def test_panel_wires_the_hidden_class_and_the_role_data() -> None:
    source = PANEL.read_text(encoding="utf-8")
    assert ".tap-compound-collapsed" in source, "the panel stylesheet must hide the runtime's collapsed class"
    assert "data.compound_edge = tapViz.compound_edge" in source, "the panel must copy the computed role map"
    assert 'selector: "edge[?_is_compound_edge]"' in source


@pytest.mark.spec("req-viz-system-display-hints-11")
def test_display_lane_carries_the_role_map_only_for_middle_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The role map is computed from COMPOUND_EDGE, added to a copy, and never written back to DEFAULT_DISPLAY."""
    from tap_grid.grift.subgraph import batch_resolve_display
    from tap_grid.registry import get_model_class

    middle_type, plain_type = "grid_fixtures__unconstrained", "grid_fixtures__node"
    model: Any = get_model_class(middle_type)
    declaration = {
        "source": "LINK_SOURCE__grid_fixtures",
        "destination": "LINK_DESTINATION__grid_fixtures",
        "path": "TRAVERSES_COMPONENT__grid_fixtures",
        "retires_with": ["source", "destination"],
    }
    monkeypatch.setattr(model, "COMPOUND_EDGE", declaration, raising=False)
    before = dict(model.DEFAULT_DISPLAY.get("tap_viz", {}))
    resolved = batch_resolve_display({middle_type, plain_type})
    assert resolved[middle_type]["compound_edge"] == {
        "source": "LINK_SOURCE__grid_fixtures",
        "destination": "LINK_DESTINATION__grid_fixtures",
        "path": "TRAVERSES_COMPONENT__grid_fixtures",
    }
    assert "compound_edge" not in resolved[plain_type]
    assert model.DEFAULT_DISPLAY.get("tap_viz", {}) == before, "the model's own hints are not mutated"
