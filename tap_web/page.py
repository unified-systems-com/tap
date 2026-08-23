"""TAP Web page service layer.

Provides lookup functions used by page, panel, and landing views.
"""

import logging
from typing import Any

from tap_grid.models import Edge
from tap_web.models import LandingPage, Page, Panel

logger = logging.getLogger(__name__)


def get_page_by_slug(slug: str) -> Page | None:
    """Return the Page with the given slug, or None if not found.

    Args:
        slug: Route path starting with /. Example: /my-page

    Returns:
        The matching Page instance, or None.
    """
    try:
        return Page.objects.select_related("entity").get(slug=slug)
    except Page.DoesNotExist:
        return None


def get_page_panels(page: Page) -> list[tuple[str, Panel]]:
    """Return ordered (panel_id, Panel) pairs for a page.

    Queries the USES_PANEL edges for the given page, ordered by edge creation
    time. The panel_id is the value stored in the edge's properties dict under
    the 'panel-id' key.

    Args:
        page: The Page instance to query panels for.

    Returns:
        Ordered list of (panel_id, Panel) tuples.
    """
    edges = (
        Edge.objects.filter(
            from_entity=page.entity,
            edge_type="USES_PANEL",
        )
        .select_related("to_entity")
        .order_by("entity__created_at")
    )

    results: list[tuple[str, Panel]] = []
    for edge in edges:
        hotlink_data = (edge.properties or {}).get("hotlink", {})
        panel_id = hotlink_data.get("value", "")
        try:
            panel = Panel.objects.select_related("entity").get(entity=edge.to_entity)
            results.append((panel_id, panel))
        except Panel.DoesNotExist:
            logger.warning("[42e3] USES_PANEL edge %s points to missing Panel entity %s", edge.pk, edge.to_entity_id)

    return results


def get_landing_page() -> Page | None:
    """Resolve the landing page target.

    Selects the earliest-created LandingPage (by entity__created_at), then
    follows its earliest USES_LANDING_PAGE edge to the target Page.

    Returns:
        The target Page, or None if no LandingPage is configured or
        the target Page is missing.
    """
    landing = LandingPage.objects.select_related("entity").order_by("entity__created_at").first()
    if landing is None:
        return None

    edge = (
        Edge.objects.filter(
            from_entity=landing.entity,
            edge_type="USES_LANDING_PAGE",
        )
        .select_related("to_entity")
        .order_by("entity__created_at")
        .first()
    )
    if edge is None:
        return None

    try:
        return Page.objects.select_related("entity").get(entity=edge.to_entity)
    except Page.DoesNotExist:
        logger.warning("[de9b] USES_LANDING_PAGE edge %s points to missing Page entity %s", edge.pk, edge.to_entity_id)
        return None


# The one spelling of the url-id separator (req-web-panel-obj-4): built by
# `build_url_id`, parsed by `parse_panel_url_id`, and mirrored client-side where
# row-click JS navigates on a serialized `url_id` (panel-table.js consumes the
# already-built token, never re-derives it).
_URL_ID_SEPARATOR = "--"


def build_url_id(slug: str, entity_id: Any) -> str:
    """Build the ``<slug>--<uuid>`` URL identifier for a panel or object route.

    The inverse of :func:`parse_panel_url_id` — the slug is decorative, the UUID
    is the canonical identifier. Every place a `/panel/...` or `/object/...` URL
    is constructed derives the token here (paths come from ``reverse()`` on the
    named routes in ``tap_web/urls.py``), so the grammar is stated once.
    """
    return f"{slug}{_URL_ID_SEPARATOR}{entity_id}"


def parse_panel_url_id(panel_url_id: str) -> str | None:
    """Extract the entity UUID from a panel URL identifier.

    Panel URLs use the format <slug>--<uuid>. The UUID is the canonical
    identifier; the slug is decorative.

    Args:
        panel_url_id: The captured URL segment, e.g. 'my-panel--<uuid>'.

    Returns:
        The UUID string, or None if the format is invalid.
    """
    idx = panel_url_id.rfind(_URL_ID_SEPARATOR)
    if idx == -1:
        return None
    return panel_url_id[idx + len(_URL_ID_SEPARATOR) :]
