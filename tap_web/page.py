"""TAP Web page service layer.

Provides lookup functions used by page, panel, and landing views.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal, cast

from django.conf import settings

from tap_grid.models import Edge, Entity
from tap_web.models import Page, Panel

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


LandingState = Literal["ok", "undeclared", "malformed", "missing", "slug_mismatch"]

_UNSET: Any = object()


@dataclass(frozen=True)
class LandingResolution:
    """The one answer to "what is the landing page?" (req-web-page-landing-12).

    Produced only by `resolve_landing`; consumed by the root route, the boot's
    post-population verification and the `web.landing` health probe. `page` is
    set for `ok` and `slug_mismatch` (the page exists; its live slug differs).
    """

    state: LandingState
    entity_id: str | None = None
    asserted_slug: str | None = None
    source: dict[str, str] | None = None
    page: Page | None = None
    found_entity_type: str | None = None

    @property
    def ok(self) -> bool:
        return self.state == "ok"

    @property
    def live_slug(self) -> str | None:
        return self.page.slug if self.page is not None else None

    @property
    def page_name(self) -> str | None:
        return self.page.name if self.page is not None else None

    def context(self) -> dict[str, Any]:
        """Structured view for the probe / boot record: nulls where unobservable, never omitted."""
        return {
            "state": self.state,
            "entity_id": self.entity_id,
            "asserted_slug": self.asserted_slug,
            "live_slug": self.live_slug,
            "page_name": self.page_name,
            "found_entity_type": self.found_entity_type,
            "source": self.source,
        }

    def describe(self) -> str:
        """One-line human reading of the state, naming every configured and observed value."""
        src = ""
        if self.source:
            src = f" (source: entity_id={self.source.get('entity_id')}, slug={self.source.get('slug')})"
        if self.state == "ok":
            return f"web.landing={self.entity_id} -> page '{self.page_name}' at {self.live_slug}{src}"
        if self.state == "undeclared":
            return "web.landing_entity_id / web.landing_slug not declared in the boot profile"
        if self.state == "malformed":
            return (
                f"web.landing is malformed: entity_id={self.entity_id!r} (must be a UUID), "
                f"slug={self.asserted_slug!r} (must start with a single '/'){src}"
            )
        if self.state == "missing":
            what = (
                f"an entity of type '{self.found_entity_type}', not a page"
                if self.found_entity_type
                else "no live entity"
            )
            return f"web.landing_entity_id={self.entity_id} names {what} (asserted slug {self.asserted_slug}){src}"
        return (
            f"web.landing_slug={self.asserted_slug} but page '{self.page_name}' ({self.entity_id}) "
            f"lives at {self.live_slug}{src}"
        )


def resolve_landing(config: dict[str, Any] | None = _UNSET) -> LandingResolution:
    """Resolve the operator's landing decision to a live Page (req-web-page-landing).

    `config` defaults to `settings.TAP_WEB_LANDING` (the running process's decision);
    the boot passes the pair it resolved from the profile it is booting. Identity is
    the entity id — the slug is only checked, never used to look a page up, so a
    replacement page at the old slug can never inherit `/` (req-web-page-landing-10).

    TAP-IMPLEMENTS: req-web-page-landing@897e92169831/79689db95d77 (derivation) — the single derivation the
        root route, the boot verification and the health probe consume (req-web-page-landing-12).
    """
    cfg = settings.TAP_WEB_LANDING if config is _UNSET else config
    if not cfg:
        return LandingResolution(state="undeclared")
    raw_id = cfg.get("entity_id")
    raw_slug = cfg.get("slug")
    source = cfg.get("source")
    entity_str = None if raw_id is None else str(raw_id)
    slug = raw_slug if isinstance(raw_slug, str) else None

    def _result(state: LandingState, *, page: Page | None = None, found: str | None = None) -> LandingResolution:
        return LandingResolution(
            state=state,
            entity_id=entity_str,
            asserted_slug=slug if slug is not None else (None if raw_slug is None else str(raw_slug)),
            source=source,
            page=page,
            found_entity_type=found,
        )

    try:
        entity_id = uuid.UUID(str(raw_id))
    except ValueError, TypeError, AttributeError:
        return _result("malformed")
    if slug is None or not slug.startswith("/") or slug.startswith("//"):
        # A protocol-relative "//host" is not a slug (validate_page_slug rejects it on
        # every page too); refusing it here keeps the redirect provably on-host.
        return _result("malformed")

    page = cast(Page | None, Page.objects.select_related("entity").filter(entity_id=entity_id).first())
    if page is None:
        found = Entity.objects.filter(pk=entity_id).values_list("entity_type", flat=True).first()
        return _result("missing", found=found)
    if page.slug != slug:
        return _result("slug_mismatch", page=page)
    return _result("ok", page=page)


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
