"""Tests for tap_web.utils — req-web-panel-json-embed.sec."""

import json
from typing import Any

import pytest

from tap_web.page import build_url_id, parse_panel_url_id
from tap_web.utils import graph_script_ids


class TestScriptContextJsonEmbedding:
    """req-web-panel-json-embed.sec: Script-Context JSON Embedding Security.

    The escaping is Django's — ``json_script`` owns it (see the spec section for why
    TAP no longer carries its own copy). These tests assert the SECURITY PROPERTY at
    the boundary TAP actually ships: a hostile value rendered through the filter
    cannot terminate the script element. They would catch a regression that swapped
    the filter back to ``|safe``, which a unit test of a helper never could.
    """

    @staticmethod
    def _render(value: Any, element_id: str = "tap-table-data-x") -> str:
        from django.template import Context, Template

        return Template("{{ payload|json_script:element_id }}").render(
            Context({"payload": value, "element_id": element_id})
        )

    def test_escapes_script_close_tag(self):
        """ACID req-web-panel-json-embed.sec-4: </script> breakout prevented."""
        payload = "</script><script>alert(1)</script>"
        rendered = self._render(payload)
        body = rendered.split(">", 1)[1].rsplit("</script>", 1)[0]
        assert "<" not in body
        assert ">" not in body
        assert json.loads(body) == payload

    def test_escapes_lt_gt_amp(self):
        """ACID req-web-panel-json-embed.sec-2: Unicode escape applied."""
        body = self._render("<b>bold</b> & more").split(">", 1)[1].rsplit("</script>", 1)[0]
        assert r"\u003C" in body
        assert r"\u003E" in body
        assert r"\u0026" in body

    def test_html_comment_injection(self):
        body = self._render("<!-- comment -->").split(">", 1)[1].rsplit("</script>", 1)[0]
        assert "<!--" not in body

    def test_nested_structure_escapes(self):
        value = {"html": "<div>hi</div>", "items": ["a&b", "c>d"]}
        body = self._render(value).split(">", 1)[1].rsplit("</script>", 1)[0]
        assert "<" not in body and ">" not in body and "&" not in body
        assert json.loads(body) == value

    def test_emits_the_element_the_panel_js_looks_up(self):
        """The id is the contract with panel-table.js / panel-graph.js."""
        rendered = self._render([], element_id="tap-table-data-abc")
        assert rendered == '<script id="tap-table-data-abc" type="application/json">[]</script>'


class TestGraphScriptIds:
    """The element-id grammar shared by the graph templates and panel-graph.js."""

    def test_covers_every_payload_the_graph_template_embeds(self):
        ids = graph_script_ids("abc")
        assert ids == {
            "graph_nodes_script_id": "tap-graph-nodes-abc",
            "graph_edges_script_id": "tap-graph-edges-abc",
            "graph_projection_script_id": "tap-graph-projection-abc",
            "graph_inputs_script_id": "tap-graph-inputs-abc",
        }

    def test_stringifies_a_uuid_context_id(self):
        """The trap this helper exists to avoid: str+UUID must not silently vanish."""
        import uuid

        cid = uuid.uuid4()
        assert graph_script_ids(cid)["graph_nodes_script_id"] == f"tap-graph-nodes-{cid}"


class TestUrlIdGrammar:
    """req-web-panel-obj-4: the ``<slug>--<uuid>`` panel/object URL token.

    ``build_url_id`` and ``parse_panel_url_id`` are the grammar's one builder and
    one parser (tap_web/page.py); the round-trip is the fact the ACID names —
    UUID is the lookup key, slug decorative.
    """

    @pytest.mark.spec("req-web-panel-obj-4")
    def test_round_trip_recovers_the_uuid(self):
        url_id = build_url_id("my-panel", "0198c2f0-0000-7000-8000-000000000001")
        assert url_id == "my-panel--0198c2f0-0000-7000-8000-000000000001"
        assert parse_panel_url_id(url_id) == "0198c2f0-0000-7000-8000-000000000001"

    @pytest.mark.spec("req-web-panel-obj-4")
    def test_slug_is_decorative_even_with_separator_collision(self):
        """A slug containing ``--`` still parses: rfind takes the LAST separator,
        so the UUID (which never contains ``--``) always wins the split."""
        url_id = build_url_id("a--tricky--slug", "0198c2f0-0000-7000-8000-000000000002")
        assert parse_panel_url_id(url_id) == "0198c2f0-0000-7000-8000-000000000002"
