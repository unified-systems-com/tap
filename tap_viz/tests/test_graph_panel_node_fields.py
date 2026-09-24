"""Node model fields reach a graph panel's layouts through the envelope's data lane.

Covers:
  req-viz-layout-node-fields-1 — each node envelope a graph panel serves carries its data lane.
  req-viz-layout-node-fields-2 — a model field outside the data lane never reaches the page.
  req-viz-layout-node-fields-3 — panel-graph.js lifts the lane onto the Cytoscape node as `fields`
  (the JS itself is exercised in a browser; this pins the one line that does it).
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from tap_grid.batch import create_batch
from tap_grid.models import Batch, Edge, Entity, Search
from tap_viz.models import Layout
from tap_viz.panels.graph_panel import GraphPanelType
from tap_web.models import Panel

PANEL_GRAPH_JS = Path(__file__).resolve().parents[1] / "static" / "tap_viz" / "js" / "panel-graph.js"


@pytest.fixture
def client(db) -> Client:
    """A grid.read (tap_viewer) session, as in test_views.py."""
    from django.contrib.auth.models import Group

    user = get_user_model().objects.create_user(username="viz-node-fields", password="x")
    user.groups.add(Group.objects.get(name="tap_viewer"))
    c = Client()
    c.force_login(user)
    return c


def _wired_panel() -> str:
    """A graph panel whose layout's search returns every node; returns its url id."""
    search = Search.objects.create(
        name="All Nodes", search_type="orm", root="node", definition={"filters": {}, "order_by": ["name"]}
    )
    layout = Layout.objects.create(entity=Entity.objects.create(entity_type="layout", name="L"), name="L")
    Edge.objects.create(
        entity=Entity.objects.create(entity_type="edge", name="USES_SEARCH"),
        from_entity=layout.entity,
        to_entity=search.entity,
        edge_type="USES_SEARCH",
    )
    panel = Panel.objects.create(slug="node-fields", name="Node Fields", view=GraphPanelType.view)
    Edge.objects.create(
        entity=Entity.objects.create(entity_type="edge", name="USES_LAYOUT"),
        from_entity=panel.entity,
        to_entity=layout.entity,
        edge_type="USES_LAYOUT",
    )
    return f"node-fields--{panel.entity_id}"


def _page_nodes(client: Client, panel_url_id: str) -> list[dict]:
    """The node envelopes as the browser receives them: parsed out of the page's data script."""
    body = client.get(f"/panel/{panel_url_id}/").content.decode()
    m = re.search(r'<script id="tap-graph-nodes-[^"]*"[^>]*>(.*?)</script>', body, re.S)
    assert m, "the graph panel rendered no node data script"
    return json.loads(html.unescape(m.group(1)))


@pytest.mark.django_db
class TestNodeFieldsServed:
    @pytest.mark.spec("req-viz-layout-node-fields-1")
    def test_each_node_carries_its_typed_model_fields(self, client: Client):
        batch = create_batch(source="test.node-fields", name="design edit", description="why it changed")
        url_id = _wired_panel()

        node = next(n for n in _page_nodes(client, url_id) if n["entity_id"] == str(batch.entity_id))

        assert node["data"]["name"] == "design edit"
        assert node["data"]["description"] == "why it changed"
        assert node["data"]["source"] == "test.node-fields"

    @pytest.mark.spec("req-viz-layout-node-fields-2")
    def test_a_field_outside_the_data_lane_never_reaches_the_page(self, client: Client):
        batch = create_batch(source="test.node-fields", name="failing edit")
        Batch.objects.filter(pk=batch.pk).update(status="failed", error_message="PAYLOAD-THAT-MUST-NOT-SHIP")
        url_id = _wired_panel()

        response = client.get(f"/panel/{url_id}/")
        node = next(n for n in _page_nodes(client, url_id) if n["entity_id"] == str(batch.entity_id))

        # error_message and status are patch-only lifecycle fields, not FIELD_CRUD_SCHEMA:
        # the data lane omits them, so neither the envelope nor the page carries them.
        assert "error_message" not in node["data"]
        assert "status" not in node["data"]
        assert b"PAYLOAD-THAT-MUST-NOT-SHIP" not in response.content


class TestNodeFieldsLifted:
    @pytest.mark.spec("req-viz-layout-node-fields-3")
    def test_panel_graph_js_lifts_the_whole_data_lane_as_fields(self):
        source = PANEL_GRAPH_JS.read_text(encoding="utf-8")
        assert re.search(r"\bfields:\s*n\.data\s*\|\|\s*\{\}", source), (
            "panel-graph.js must set `fields` on each envelope-built Cytoscape node to the envelope's "
            "data lane (or {}); layouts read node.data('fields') instead of parsing labels"
        )
