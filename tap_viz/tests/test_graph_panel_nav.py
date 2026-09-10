"""Node navigation declared by a graph panel's `nav_rules`.

Covers:
  req-viz-panel-click-semantics-8 — a rule yields a URL from a template over the node,
  from a data field, or not at all; a template placeholder with no value voids the link, and a
  target that is neither a same-origin path nor an absolute http(s) URL is refused.
"""

from __future__ import annotations

from typing import Any

from tap_viz.panels.graph_panel import _apply_nav_rules, _fill_url_template, _safe_nav_url

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
            [
                {
                    "entity_type": WORKFLOW,
                    "url_template": "/github_core/workflow?repo={data.full_name}&workflow={data.path}",
                }
            ],
            "panel-1",
        )
        assert _nav(node)["nav_url"] == "/github_core/workflow?repo=acme/widgets&workflow=.github/workflows/ci.yml"
        assert "nav_external" not in _nav(node)

    def test_a_node_missing_a_placeholder_value_is_left_un_navigable(self):
        node = _node(full_name="acme/widgets")
        _apply_nav_rules(
            [node],
            [
                {
                    "entity_type": WORKFLOW,
                    "url_template": "/github_core/workflow?repo={data.full_name}&workflow={data.path}",
                }
            ],
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


class TestSafeNavUrl:
    """A nav target is a same-origin path or an absolute http(s) URL — both sources carry
    collected data, so neither is the panel author's to vouch for."""

    def test_a_same_origin_path_is_kept(self):
        assert _safe_nav_url("/github_core/workflow?repo=a/b") == "/github_core/workflow?repo=a/b"

    def test_an_absolute_http_url_is_kept(self):
        assert _safe_nav_url("https://github.com/acme/widgets") == "https://github.com/acme/widgets"

    def test_a_protocol_relative_url_is_refused(self):
        # Reads as a path, navigates off-site.
        assert _safe_nav_url("//evil.example/x") is None

    def test_a_javascript_target_is_refused(self):
        assert _safe_nav_url("javascript:alert(1)") is None

    def test_a_data_target_is_refused(self):
        assert _safe_nav_url("data:text/html,<script>alert(1)</script>") is None

    def test_a_relative_path_with_no_leading_slash_is_refused(self):
        assert _safe_nav_url("workflow?repo=a/b") is None


class TestRefusedTargetsLeaveTheNodeAlone:
    def test_a_hostile_url_field_value_does_not_become_a_nav_target(self):
        node = _node(html_url="javascript:alert(1)")
        _apply_nav_rules([node], [{"entity_type": WORKFLOW, "url_field": "html_url", "external": True}], "panel-1")
        assert _nav(node) == {}

    def test_a_protocol_relative_field_value_does_not_become_a_nav_target(self):
        node = _node(html_url="//evil.example/x")
        _apply_nav_rules([node], [{"entity_type": WORKFLOW, "url_field": "html_url", "external": True}], "panel-1")
        assert _nav(node) == {}

    def test_a_template_filled_into_a_hostile_shape_is_refused(self):
        node = _node(target="//evil.example")
        _apply_nav_rules([node], [{"entity_type": WORKFLOW, "url_template": "{data.target}"}], "panel-1")
        assert _nav(node) == {}

    def test_a_hostile_value_inside_a_path_template_is_harmless(self):
        # The template anchors the origin; the value is encoded into the query.
        node = _node(full_name="javascript:alert(1)", path="ci.yml")
        _apply_nav_rules(
            [node],
            [
                {
                    "entity_type": WORKFLOW,
                    "url_template": "/github_core/workflow?repo={data.full_name}&workflow={data.path}",
                }
            ],
            "panel-1",
        )
        assert _nav(node)["nav_url"] == "/github_core/workflow?repo=javascript%3Aalert%281%29&workflow=ci.yml"
