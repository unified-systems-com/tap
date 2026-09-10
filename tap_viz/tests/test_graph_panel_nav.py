"""Node navigation declared by a graph panel's `nav_rules`.

Covers:
  req-viz-panel-click-semantics-8 — a rule yields a URL from a template over the node,
  from a data field, or not at all; a template placeholder with no value voids the link.
"""

from __future__ import annotations

from typing import Any

from tap_viz.panels.graph_panel import _apply_nav_rules, _fill_url_template

WORKFLOW = "github_core__github_workflow"


def _node(**data: Any) -> dict[str, Any]:
    return {"entity_id": "01a0-abc", "entity_type": WORKFLOW, "data": dict(data)}


def _nav(node: dict[str, Any]) -> dict[str, Any]:
    return ((node.get("display") or {}).get("tap_viz")) or {}


class TestFillUrlTemplate:
    def test_reads_dotted_paths_out_of_the_node_envelope(self):
        node = _node(full_name="acme/widgets", path=".github/workflows/ci.yml")
        url = _fill_url_template("/github_core/workflow?repo={data.full_name}&workflow={data.path}", node)
        assert url == "/github_core/workflow?repo=acme/widgets&workflow=.github/workflows/ci.yml"

    def test_entity_id_is_a_dotted_path_like_any_other(self):
        assert _fill_url_template("/object/{entity_id}/", _node()) == "/object/01a0-abc/"

    def test_a_value_is_encoded_but_keeps_its_slashes(self):
        node = _node(full_name="acme/wid gets&co")
        assert _fill_url_template("/p?repo={data.full_name}", node) == "/p?repo=acme/wid%20gets%26co"

    def test_an_empty_placeholder_voids_the_whole_link(self):
        node = _node(full_name="acme/widgets", path="")
        assert _fill_url_template("/p?repo={data.full_name}&workflow={data.path}", node) is None

    def test_a_missing_placeholder_voids_the_whole_link(self):
        assert _fill_url_template("/p?repo={data.nope}", _node(full_name="acme/widgets")) is None

    def test_a_template_with_no_placeholders_is_itself(self):
        assert _fill_url_template("/github_core/workflows", _node()) == "/github_core/workflows"


class TestApplyNavRules:
    def test_a_template_rule_stamps_the_filled_url(self):
        node = _node(full_name="acme/widgets", path=".github/workflows/ci.yml")
        _apply_nav_rules(
            [node],
            [{"entity_type": WORKFLOW, "url_template": "/github_core/workflow?repo={data.full_name}&workflow={data.path}"}],
            "panel-1",
        )
        assert _nav(node)["nav_url"] == "/github_core/workflow?repo=acme/widgets&workflow=.github/workflows/ci.yml"
        assert "nav_external" not in _nav(node)

    def test_a_node_missing_a_placeholder_value_is_left_un_navigable(self):
        node = _node(full_name="acme/widgets")
        _apply_nav_rules(
            [node],
            [{"entity_type": WORKFLOW, "url_template": "/github_core/workflow?repo={data.full_name}&workflow={data.path}"}],
            "panel-1",
        )
        assert "nav_url" not in _nav(node)

    def test_a_voided_template_does_not_fall_through_to_a_later_rule(self):
        # First match wins, even when it yields nothing: a rule that matched has spoken.
        node = _node(full_name="acme/widgets", html_url="https://github.com/acme/widgets")
        _apply_nav_rules(
            [node],
            [
                {"entity_type": WORKFLOW, "url_template": "/p?workflow={data.path}"},
                {"entity_type": WORKFLOW, "url_field": "html_url", "external": True},
            ],
            "panel-1",
        )
        assert "nav_url" not in _nav(node)

    def test_a_field_rule_still_works_and_carries_external(self):
        node = _node(html_url="https://github.com/acme/widgets")
        _apply_nav_rules([node], [{"entity_type": WORKFLOW, "url_field": "html_url", "external": True}], "panel-1")
        assert _nav(node) == {"nav_url": "https://github.com/acme/widgets", "nav_external": True}

    def test_invalid_rules_degrade_to_no_navigation(self):
        node = _node(full_name="acme/widgets")
        _apply_nav_rules([node], [{"entity_type": WORKFLOW}], "panel-1")
        assert _nav(node) == {}
