"""Fixed panel inputs on USES_PANEL (req-web-page-plink-9/-10/-11, tap#359).

A panel is defined once and mounted on many pages. A page that is about one thing pins the
panel's input on its USES_PANEL edge (``properties.inputs``) instead of carrying a copy of the
panel with the value hardcoded. These tests pin the contract on both rendering roads: the
persisted page prints the overlay into each slot's ``hx-get``; the synthetic page hands it to
the slot's panel as its request.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import patch

import pytest
from django.http import QueryDict
from django.test import RequestFactory

from tap.pytest_harness import make_admin_client
from tap_grid.exceptions import EdgePropertyValidationError
from tap_grid.models import Edge
from tap_web.models import Page, Panel
from tap_web.page import get_page_slots, slot_query_params
from tap_web.views import _process_layout

_LAYOUT: dict[str, Any] = {
    "columns": {
        "col-1": {
            "width": "1fr",
            "rows": {
                "row-1": {"panel-id": "identity", "height": "auto"},
                "row-2": {"panel-id": "wall", "height": "auto"},
            },
        }
    }
}


def _hotlink(panel_id: str) -> dict[str, Any]:
    return {"model": "page", "spec": "page-panels", "value": panel_id}


def _panel(slug: str) -> Panel:
    return cast(
        Panel, Panel.objects.create(slug=slug, name=slug, description="", view="tap_web/panel_error.html", config={})
    )


def _link(page: Page, panel: Panel, panel_id: str, inputs: dict[str, Any] | None = None) -> Edge:
    properties: dict[str, Any] = {"hotlink": _hotlink(panel_id)}
    if inputs is not None:
        properties["inputs"] = inputs
    return cast(
        Edge,
        Edge.objects.create(
            from_entity=page.entity, to_entity=panel.entity, edge_type="USES_PANEL", properties=properties
        ),
    )


# ---------------------------------------------------------------------------
# The overlay itself (req-web-page-plink-11)
# ---------------------------------------------------------------------------


def test_slot_query_params_fixed_wins_and_the_rest_passes_through() -> None:
    base = QueryDict("repo=x/y&state=OPEN")
    pinned = slot_query_params(base, {"repo": "a/b"})
    assert pinned.urlencode() == "repo=a%2Fb&state=OPEN"
    assert base.urlencode() == "repo=x%2Fy&state=OPEN"  # the page's own params are untouched
    assert slot_query_params(base, None).urlencode() == "repo=x%2Fy&state=OPEN"
    assert slot_query_params(None, {"repo": "a/b"}).urlencode() == "repo=a%2Fb"
    assert slot_query_params({"k": "v"}, {}).urlencode() == "k=v"


def test_process_layout_derives_one_query_string_per_slot() -> None:
    rows = _process_layout(
        _LAYOUT,
        {"identity": "identity--1", "wall": "wall--2"},
        QueryDict("repo=x/y&state=OPEN"),
        {"identity": {"repo": "a/b"}},
    )[0]["rows"]
    by_slot = {row["panel_id"]: row["query_string"] for row in rows}
    assert by_slot == {"identity": "repo=a%2Fb&state=OPEN", "wall": "repo=x%2Fy&state=OPEN"}


def test_process_layout_without_params_prints_no_query_string() -> None:
    rows = _process_layout(_LAYOUT, {"identity": "identity--1"})[0]["rows"]
    assert [row["query_string"] for row in rows] == ["", ""]


# ---------------------------------------------------------------------------
# The persisted road (req-web-page-plink-9/-10)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPersistedPage:
    def test_get_page_slots_exposes_fixed_inputs(self) -> None:
        page = Page.objects.create(name="Pinned", slug="/pinned", layout=_LAYOUT)
        identity, wall = _panel("identity"), _panel("wall")
        _link(page, identity, "identity", {"repo": "a/b"})
        _link(page, wall, "wall")
        slots = get_page_slots(page)
        assert [(s.panel_id, s.panel.slug, s.inputs) for s in slots] == [
            ("identity", "identity", {"repo": "a/b"}),
            ("wall", "wall", {}),
        ]

    def test_non_string_fixed_input_is_rejected(self) -> None:
        page = Page.objects.create(name="Pinned", slug="/pinned", layout=_LAYOUT)
        panel = _panel("identity")
        with pytest.raises(EdgePropertyValidationError):
            _link(page, panel, "identity", {"repo": 5})

    def test_pinned_slot_url_carries_fixed_inputs_and_others_pass_through(self) -> None:
        page = Page.objects.create(name="Pinned", slug="/pinned", layout=_LAYOUT)
        identity, wall = _panel("identity"), _panel("wall")
        _link(page, identity, "identity", {"repo": "a/b"})
        _link(page, wall, "wall")

        html = make_admin_client().get("/pinned?repo=x/y&state=OPEN").content.decode()

        assert f'hx-get="/panel/identity--{identity.entity_id}/?repo=a%2Fb&amp;state=OPEN"' in html
        assert f'hx-get="/panel/wall--{wall.entity_id}/?repo=x%2Fy&amp;state=OPEN"' in html


# ---------------------------------------------------------------------------
# The synthetic road (req-web-page-plink-10)
# ---------------------------------------------------------------------------


def _synthetic_subgraph() -> dict[str, Any]:
    def node(entity_id: str, entity_type: str, **fields: Any) -> dict[str, Any]:
        return {"entity": {"entity_id": entity_id, "entity_type": entity_type, "name": entity_id}, "node": fields}

    def edge(from_id: str, to_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        return {
            "entity": {"entity_id": f"e-{from_id}-{to_id}", "entity_type": "edge", "name": ""},
            "edge": {
                "from_entity_id": from_id,
                "to_entity_id": to_id,
                "edge_type": "USES_PANEL",
                "properties": properties,
            },
        }

    panel_fields = {"description": "", "view": "tap_web/panel_error.html", "config": {}}
    return {
        "nodes": [
            node("page-1", "page", name="Pinned", slug="/pinned", layout=_LAYOUT),
            node("panel-identity", "panel", name="identity", slug="identity", **panel_fields),
            node("panel-wall", "panel", name="wall", slug="wall", **panel_fields),
        ],
        "edges": [
            edge("page-1", "panel-identity", {"hotlink": _hotlink("identity"), "inputs": {"repo": "a/b"}}),
            edge("page-1", "panel-wall", {"hotlink": _hotlink("wall")}),
        ],
    }


def test_synthetic_road_lays_the_same_overlay_over_the_panel_request() -> None:
    from tap_web.synthetic import render_synthetic_page

    request = RequestFactory().get("/pinned?repo=x/y&state=OPEN")
    seen: dict[str, str] = {}

    def fake_render(panel: Any, graph: Any, panel_request: Any) -> str:
        seen[panel.slug] = panel_request.GET.urlencode()
        return ""

    with patch("tap_web.synthetic._render_synthetic_panel", side_effect=fake_render):
        response = render_synthetic_page(request, _synthetic_subgraph())

    assert response.status_code == 200
    assert seen == {"identity": "repo=a%2Fb&state=OPEN", "wall": "repo=x%2Fy&state=OPEN"}
    assert request.GET.urlencode() == "repo=x%2Fy&state=OPEN"  # the page's request is never mutated
