"""req-web-panel-json-embed.sec: JSON payloads reach the page via ``json_script``.

These tests guard the boundary rather than a helper. TAP used to own the escaping
(``tap_web.utils.safe_json`` + ``{{ value|safe }}``); it now delegates to Django's
``json_script``, and the two failure modes worth catching are a regression back to
``|safe`` and a silently-empty element id — the second of which produces a payload
the panel JS can never find, with no error anywhere on the page.
"""

import json
import re
from pathlib import Path

import pytest
from django.template import Context, Template

# Templates converted from `{{ x_json|safe }}` to `{{ x|json_script:id }}`.
CONVERTED_TEMPLATES = [
    "tap_web/templates/tap_web/panels/table_panel.html",
    "tap_web/templates/tap_web/panels/batch_list.html",
    "tap_web/templates/tap_web/panels/batch_viewer.html",
    "tap_web/templates/tap_web/setup_placeholder.html",
    "tap_viz/templates/tap_viz/panels/graph_panel.html",
    "tap_viz/templates/tap_viz/graph_context.html",
]

_REPO_ROOT = Path(__file__).resolve().parents[2]

# `{{ anything_json|safe }}` — the shape this requirement forbids. Matches the
# variable name, not the value, so it catches a reintroduction under any new name
# ending in `_json`.
_JSON_SAFE = re.compile(r"\{\{\s*[\w.]*_json\s*\|\s*safe\s*\}\}")


class TestNoSafeFilterOnJsonPayloads:
    """ACID req-web-panel-json-embed.sec-3."""

    @pytest.mark.parametrize("relpath", CONVERTED_TEMPLATES)
    def test_converted_template_has_no_json_safe(self, relpath: str) -> None:
        assert not _JSON_SAFE.search((_REPO_ROOT / relpath).read_text())

    def test_no_template_anywhere_pipes_a_json_payload_through_safe(self) -> None:
        """Repo-wide, so a NEW template cannot reintroduce the pattern unnoticed."""
        scanned = list(_REPO_ROOT.glob("tap_*/templates/**/*.html"))
        # A scan that measures nothing is indistinguishable from a scan that found
        # nothing. Assert the scope before asserting the result.
        assert len(scanned) >= len(CONVERTED_TEMPLATES), f"template scan found only {len(scanned)} files"

        offenders = [str(p.relative_to(_REPO_ROOT)) for p in scanned if _JSON_SAFE.search(p.read_text())]
        assert offenders == [], f"JSON payloads piped through |safe: {offenders}"

    def test_the_scan_would_actually_catch_a_reintroduction(self) -> None:
        """Positive control: the regex matches the shape it claims to forbid."""
        assert _JSON_SAFE.search("<script>{{ table_nodes_json|safe }}</script>")
        assert _JSON_SAFE.search("{{ foo.bar_json | safe }}")
        assert not _JSON_SAFE.search("{{ table_nodes|json_script:table_data_script_id }}")


class TestHostilePayloadCannotEscapeTheScriptElement:
    """ACID req-web-panel-json-embed.sec-2 / -4, asserted on rendered output."""

    HOSTILE = "</script><script>alert(1)</script><!-- & -->"

    def _render(self, element_id: str) -> str:
        return Template("{{ payload|json_script:element_id }}").render(
            Context({"payload": {"name": self.HOSTILE}, "element_id": element_id})
        )

    def test_breakout_sequence_is_escaped_and_round_trips(self) -> None:
        rendered = self._render("tap-table-data-x")
        body = rendered.split(">", 1)[1].rsplit("</script>", 1)[0]
        assert "<" not in body and ">" not in body and "&" not in body
        assert json.loads(body) == {"name": self.HOSTILE}

    def test_element_id_is_present_and_non_empty(self) -> None:
        """A blank id renders valid HTML the JS can never resolve — fail loudly."""
        assert 'id="tap-table-data-x"' in self._render("tap-table-data-x")

    def test_uuid_ids_survive_the_python_side_concatenation(self) -> None:
        """The trap: `"prefix-"|add:uuid` in a template silently yields ""."""
        import uuid

        from tap_web.utils import graph_script_ids

        cid = uuid.uuid4()
        eid = graph_script_ids(cid)["graph_nodes_script_id"]
        assert eid.endswith(str(cid))
        assert f'id="{eid}"' in self._render(eid)


class TestSafeJsonRemainsPluginFacingApi:
    """`tap_web.utils.safe_json` is imported by plugins in OTHER repositories.

    Removing it broke `django.setup()` on PR #250's cold-boot gate with
    `ImportError: cannot import name 'safe_json'`, raised from
    tap_plugin.administrivia's panel — a released plugin installed from a git tag.
    Core's own suite was fully green: nothing in this repository imported it any
    more. That is the shape of the mistake, and this class is the guard against
    repeating it.
    """

    def test_it_is_importable(self) -> None:
        from tap_web.utils import safe_json

        assert callable(safe_json)

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param({"a": "</script><script>alert(1)</script>"}, id="breakout"),
            pytest.param(["x&y<z>"], id="entities"),
            pytest.param({"n": 1, "nested": {"s": "<b>"}}, id="nested"),
            pytest.param([], id="empty"),
        ],
    )
    def test_escaping_is_byte_identical_to_django_json_script(self, value) -> None:
        """The docstring claims parity with Django; this proves it.

        The previous implementation ALSO claimed to mirror `json_script` — in prose,
        with nothing checking it. A hand-rolled copy of a security control that merely
        says it matches the original is precisely what drifts.
        """
        from django.utils.html import json_script

        from tap_web.utils import safe_json

        rendered = str(json_script(value, "id"))
        django_payload = rendered.split(">", 1)[1].rsplit("</script>", 1)[0]
        assert safe_json(value) == django_payload

    def test_core_templates_no_longer_use_it(self) -> None:
        """It survives for plugins only — core renders through `json_script`."""
        offenders = [
            str(p.relative_to(_REPO_ROOT))
            for p in _REPO_ROOT.glob("tap_*/templates/**/*.html")
            if "safe_json" in p.read_text()
        ]
        assert offenders == []
