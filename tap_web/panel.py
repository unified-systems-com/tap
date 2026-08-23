"""TAP Web panel service — helpers for resolving panel graph relationships.

Analogous to page_service.py but scoped to individual panels rather than pages.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tap_grid.models import Search
    from tap_web.models import Panel

logger = logging.getLogger(__name__)

# The vendored Tabulator bundle every table-rendering panel loads. One home so a
# version bump is one edit, not three (2026-08 value-level sweep, finding 15).
TABULATOR_CSS: list[str] = [
    "tap_web/css/lib/tabulator.min.css",
    "tap_web/css/tabulator-minimal.css",
]
TABULATOR_JS: list[str] = [
    "tap_web/js/lib/tabulator.min.js",
    "tap_web/js/panel-table.js",
]


def get_panel_search(panel: Panel) -> Search | None:
    """Return the first Search linked to a Panel via USES_SEARCH, or None.

    Follows the earliest-created USES_SEARCH edge from the panel's entity to
    a Search object. Returns None if no edge exists or the target Search is
    missing. Logs a warning on a dangling edge.

    Args:
        panel: The Panel instance whose linked Search should be resolved.

    Returns:
        The linked Search instance, or None.
    """
    from tap_grid.models import Edge, Search

    edge = (
        Edge.objects.filter(
            from_entity=panel.entity,
            edge_type="USES_SEARCH",
        )
        .select_related("to_entity")
        .order_by("entity__created_at")
        .first()
    )

    if edge is None:
        return None

    try:
        return Search.objects.select_related("entity").get(entity=edge.to_entity)
    except Search.DoesNotExist:
        logger.warning(
            "[6b04] USES_SEARCH edge %s points to missing Search entity %s",
            edge.pk,
            edge.to_entity_id,
        )
        return None
