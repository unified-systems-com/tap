"""Graph panel config for settle mode (`zoom_settle`).

Covers req-viz-label-sizing-settle-1 (opt-in, malformed degrades to off) and -2 (schema describes itself).
"""

from __future__ import annotations

import json
from typing import Any

import jsonschema
import pytest

from tap_viz.panels.graph_panel import GRAPH_CONFIG_SCHEMA, ZOOM_SETTLE_SCHEMA, _error_ctx, _zoom_settle_attr


def _every_schema_node(node: Any):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _every_schema_node(v)
    elif isinstance(node, list):
        for v in node:
            yield from _every_schema_node(v)


class TestZoomSettleAttr:
    @pytest.mark.spec("req-viz-label-sizing-settle-1")
    @pytest.mark.parametrize(
        "config",
        [
            None,
            {},
            {"height": "100%"},
            {"zoom_settle": None},
            {"zoom_settle": {}},
            {"zoom_settle": {"enabled": False}},
            {"zoom_settle": "on"},
        ],
    )
    def test_absent_or_disabled_is_off(self, config):
        assert _zoom_settle_attr(config) == ""

    @pytest.mark.spec("req-viz-label-sizing-settle-1")
    @pytest.mark.parametrize(
        "bad",
        [
            {"debounce_ms": -1},
            {"debounce_ms": 6000},
            {"debounce_ms": 1.5},
            {"exponent": 1.2},
            {"exponent": -0.1},
            {"classes": {"nope": {}}},
            {"classes": {"font": {"min_scale": 0}}},
            {"classes": {"font": {"max_scale": 0.9}}},
            {"classes": {"font": {"gamma": 1}}},
            {"texture_on_viewport": "yes"},
            {"surprise": True},
        ],
    )
    def test_malformed_enabled_config_degrades_to_off(self, bad):
        assert _zoom_settle_attr({"zoom_settle": {"enabled": True, **bad}}) == ""

    @pytest.mark.spec("req-viz-label-sizing-settle-1")
    def test_valid_config_is_passed_through_as_json(self):
        cfg = {
            "enabled": True,
            "debounce_ms": 200,
            "exponent": 0,
            "classes": {"font": {"min_scale": 0.5}},
            "texture_on_viewport": False,
        }
        assert json.loads(_zoom_settle_attr({"zoom_settle": cfg})) == cfg

    @pytest.mark.spec("req-viz-label-sizing-settle-1")
    def test_error_context_carries_the_key_off(self):
        assert _error_ctx("x")["graph_zoom_settle"] == ""


class TestSchema:
    @pytest.mark.spec("req-viz-label-sizing-settle-2")
    def test_every_schema_entry_has_a_description(self):
        """Repo rule: a JSON structure describes itself, at the top and at each entry."""
        assert GRAPH_CONFIG_SCHEMA["description"] and ZOOM_SETTLE_SCHEMA["description"]
        for name, prop in GRAPH_CONFIG_SCHEMA["properties"].items():
            assert prop.get("description"), name
        for container in _every_schema_node(ZOOM_SETTLE_SCHEMA):
            for name, prop in (container.get("properties") or {}).items():
                assert prop.get("description"), name

    @pytest.mark.spec("req-viz-label-sizing-settle-2")
    def test_schema_is_a_valid_draft_schema_and_enabled_is_required(self):
        jsonschema.Draft202012Validator.check_schema(ZOOM_SETTLE_SCHEMA)
        jsonschema.Draft202012Validator.check_schema(GRAPH_CONFIG_SCHEMA)
        assert ZOOM_SETTLE_SCHEMA["required"] == ["enabled"]
        assert ZOOM_SETTLE_SCHEMA["properties"]["texture_on_viewport"]["type"] == "boolean"

    @pytest.mark.spec("req-viz-label-sizing-settle-2")
    def test_graph_schema_accepts_existing_keys_and_unknown_ones(self):
        jsonschema.validate(
            {
                "height": "100%",
                "hide_header": True,
                "nav_rules": [{"entity_type": "x", "url_template": "/a"}],
                "other": 1,
            },
            GRAPH_CONFIG_SCHEMA,
        )
