"""tap_web utilities — shared rendering helpers.

**This module is plugin-facing API.** Plugins in their own repositories import from
here, are released independently, and are installed from git tags at boot — so a
symbol removed here breaks already-released plugins at `django.setup()`, long after
core's own test suite is green. Deprecate; do not delete.
"""

import json
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.utils.html import json_script  # noqa: F401  (re-exported for plugins)

# Element-id grammar for the JSON payloads a graph view embeds. This is the
# contract with tap_viz/static/tap_viz/js/panel-graph.js, which rebuilds the same
# ids by concatenating the panel/context id onto these prefixes.
#
# The ids are built in Python rather than in the template because Django's
# ``json_script`` filter takes the element id as a FILTER ARGUMENT, which cannot be
# a concatenation — and the obvious template workaround (``"tap-graph-nodes-"|add:
# panel.entity_id``) silently yields the empty string, because ``add`` falls back to
# ``value + arg`` and ``str + UUID`` raises. A silently-empty id is a payload the JS
# can never find, so the concatenation lives where a type error is loud.
_GRAPH_PAYLOAD_KINDS = ("nodes", "edges", "projection", "inputs")


def graph_script_ids(context_id: Any) -> dict[str, str]:
    """Return ``{"graph_<kind>_script_id": "tap-graph-<kind>-<context_id>"}``.

    Args:
        context_id: The panel entity id or synthetic graph-context id that
            namespaces this graph's payload elements on the page.

    Returns:
        One ``graph_<kind>_script_id`` entry per embedded payload, ready to splat
        into a template context alongside the payload objects themselves.
    """
    return {f"graph_{kind}_script_id": f"tap-graph-{kind}-{context_id}" for kind in _GRAPH_PAYLOAD_KINDS}


def safe_json(value: Any) -> str:
    """Serialize *value* to a JSON string safe to embed in an HTML ``<script>`` block.

    **Deprecated for new code — use Django's ``json_script`` template filter.** Core's
    own templates were migrated to it (req-web-panel-json-embed.sec); this function
    remains because it is plugin-facing API that three released plugins import
    (administrivia, fedramp_20x_ksi, samsite) and core cannot remove a symbol from
    under an independently versioned plugin. Tracked for removal in
    unified-systems-com/tap#255, after those plugins migrate and re-release.

    ``<``, ``>`` and ``&`` become Unicode escapes, so the payload cannot terminate the
    script element or inject an entity. The escaping is IDENTICAL to Django's
    ``json_script`` — asserted byte-for-byte by a test, rather than claimed in prose as
    the previous docstring did, because a copy of a security control that merely says it
    matches the original is exactly the thing that drifts.

    Args:
        value: Any JSON-serializable object. ``DjangoJSONEncoder`` is used, so
            ``UUID``, ``datetime`` and ``Decimal`` serialize rather than raising.

    Returns:
        The escaped JSON text, for use as ``{{ value|safe }}`` inside a ``<script>``.
    """
    raw = json.dumps(value, cls=DjangoJSONEncoder)
    return raw.replace("<", r"\u003C").replace(">", r"\u003E").replace("&", r"\u0026")
