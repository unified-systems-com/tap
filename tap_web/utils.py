"""tap_web utilities — shared rendering helpers."""

from typing import Any

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
