"""Node model fields reach a graph panel's layouts through the envelope's data lane.

Covers:
  req-viz-layout-node-fields-1 — each node envelope a graph panel serves carries its data lane.
  req-viz-layout-node-fields-2 — a model field outside the data lane never reaches the panel.
  req-viz-layout-node-fields-3 — panel-graph.js lifts the lane onto the Cytoscape node as `fields`
  (the JS itself is exercised in a browser; this pins the one line that does it).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from django.test import RequestFactory

from tap_grid.batch import create_batch
from tap_grid.models import Edge, Entity, Search
from tap_viz.models import Layout
from tap_viz.panels.graph_panel import GraphPanelType
from tap_web.models import Panel

PANEL_GRAPH_JS = Path(__file__).resolve().parents[1] / "static" / "tap_viz" / "js" / "panel-graph.js"


def _wired_panel() -> Panel:
    """A graph panel whose layout's search returns every batch node."""
    search = Search.objects.create(
        name="All Batches",
        search_type="orm",
        root="node",
        definition={"filters": {"entity_type": "batch"}, "order_by": ["name"]},
    )
    layout = Layout.objects.create(entity=Entity.objects.create(entity_type="layout", name="L"), name="L")
    Edge.objects.create(
        entity=Entity.objects.create(entity_type="edge", name="USES_SEARCH"),
        from_entity=layout.entity,
        to_entity=search.entity,
        edge_type="USES_SEARCH",
    )
    panel: Panel = Panel.objects.create(slug="node-fields", name="Node Fields", view=GraphPanelType.view)
    Edge.objects.create(
        entity=Entity.objects.create(entity_type="edge", name="USES_LAYOUT"),
        from_entity=panel.entity,
        to_entity=layout.entity,
        edge_type="USES_LAYOUT",
    )
    return panel


def _served_nodes(panel: Panel) -> list[dict[str, Any]]:
    """The node envelopes the panel hands its template (and so the page's node script)."""
    context = GraphPanelType.get_view_context(panel, RequestFactory().get("/"))
    assert context["graph_error"] is None, context["graph_error"]
    nodes: list[dict[str, Any]] = context["graph_nodes"]
    return nodes


# Transactional: the panel's search reads through the separate `search_readonly`
# connection, which cannot see rows written inside an open test transaction.
@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestNodeFieldsServed:
    @pytest.mark.spec("req-viz-layout-node-fields-1")
    def test_each_node_carries_its_typed_model_fields(self) -> None:
        batch = create_batch(source="test.node-fields", name="design edit", description="why it changed")

        node = next(n for n in _served_nodes(_wired_panel()) if n["entity_id"] == str(batch.entity_id))

        assert node["data"]["name"] == "design edit"
        assert node["data"]["description"] == "why it changed"
        assert node["data"]["source"] == "test.node-fields"

    @pytest.mark.spec("req-viz-layout-node-fields-2")
    def test_a_field_outside_the_data_lane_never_reaches_the_panel(self) -> None:
        batch = create_batch(source="test.node-fields", name="failing edit")
        batch.status = "failed"
        batch.error_message = "PAYLOAD-THAT-MUST-NOT-SHIP"
        batch.save(update_fields=["status", "error_message"])
        batch.refresh_from_db()
        assert batch.error_message == "PAYLOAD-THAT-MUST-NOT-SHIP"  # the field is really set

        nodes = _served_nodes(_wired_panel())
        node = next(n for n in nodes if n["entity_id"] == str(batch.entity_id))

        # status and error_message are patch-only lifecycle fields, not FIELD_CRUD_SCHEMA:
        # the data lane omits them, so nothing the panel serves carries them.
        assert "error_message" not in node["data"]
        assert "status" not in node["data"]
        assert "PAYLOAD-THAT-MUST-NOT-SHIP" not in json.dumps(nodes, default=str)


class TestNodeFieldsLifted:
    @pytest.mark.spec("req-viz-layout-node-fields-3")
    def test_panel_graph_js_lifts_the_whole_data_lane_as_fields(self) -> None:
        source = PANEL_GRAPH_JS.read_text(encoding="utf-8")
        assert re.search(r"\bfields:\s*n\.data\s*\|\|\s*\{\}", source), (
            "panel-graph.js must set `fields` on each envelope-built Cytoscape node to the envelope's "
            "data lane (or {}); layouts read node.data('fields') instead of parsing labels"
        )
