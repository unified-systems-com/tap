"""Tests for tap_web.utils — req-web-panel-json-embed.sec."""

import json

import pytest

from tap_web.page import build_url_id, parse_panel_url_id
from tap_web.utils import safe_json


class TestSafeJson:
    """req-web-panel-json-embed.sec: Script-Context JSON Embedding Security."""

    def test_plain_value_round_trips(self):
        value = {"name": "Gandalf", "count": 42}
        assert json.loads(safe_json(value)) == value

    def test_list_round_trips(self):
        value = [1, "two", None, True]
        assert json.loads(safe_json(value)) == value

    def test_escapes_script_close_tag(self):
        """ACID req-web-panel-json-embed.sec-4: </script> breakout prevented."""
        payload = "</script><script>alert(1)</script>"
        result = safe_json(payload)
        assert "<" not in result
        assert ">" not in result
        # Still deserializes to the original string.
        assert json.loads(result) == payload

    def test_escapes_lt_gt_amp(self):
        """ACID req-web-panel-json-embed.sec-2: Unicode escape applied."""
        payload = "<b>bold</b> & more"
        result = safe_json(payload)
        assert r"\u003c" in result
        assert r"\u003e" in result
        assert r"\u0026" in result
        assert json.loads(result) == payload

    def test_html_comment_injection(self):
        payload = "<!-- comment -->"
        result = safe_json(payload)
        assert "<!--" not in result
        assert json.loads(result) == payload

    def test_nested_structure_escapes(self):
        value = {"html": "<div>hi</div>", "items": ["a&b", "c>d"]}
        result = safe_json(value)
        assert "<" not in result
        assert ">" not in result
        assert "&" not in result
        assert json.loads(result) == value

    def test_empty_structures(self):
        assert safe_json([]) == "[]"
        assert safe_json({}) == "{}"

    def test_string_type_returned(self):
        assert isinstance(safe_json({"a": 1}), str)


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
