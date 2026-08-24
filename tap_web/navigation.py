"""URL → breadcrumb decomposition per spec-web-navigation.

The breadcrumb chrome is built once per request from the URL path. The
home segment is always the product mark (resolved by the template); each
subsequent URL slice becomes a breadcrumb level whose label and link are
derived from a registered `Page` at that URL prefix. Unregistered prefixes
render as plain text (raw slug title-cased), unclickable.

Per req-web-nav-auto-parent, the URL hierarchy is the canonical hierarchy.
Parameterized routes (e.g., `/object/<type>/<id>/`) are out of scope for
v0 — those routes generate breadcrumbs through a different code path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BreadcrumbSegment:
    """One segment in a page's breadcrumb path."""

    label: str
    """Display label. Empty for the home segment — the template renders the product mark instead."""

    url: str
    """URL prefix this segment links to. Always starts with `/`."""

    is_registered: bool
    """True iff a `Page` exists at this URL prefix.

    Registered segments render as clickable links using the Page's `name`.
    Unregistered segments render as plain text using a title-cased slug.
    """

    is_current: bool
    """True iff this segment is the leaf (the page being viewed).

    Per req-web-nav-breadcrumb-header-3 the current segment gets active styling
    and is rendered as a non-link `<span>` with `aria-current="page"`.
    """

    is_home: bool
    """True for the root `/` segment — the product mark."""


def build_breadcrumb(url: str) -> list[BreadcrumbSegment]:
    """Decompose a URL into breadcrumb segments.

    TAP-IMPLEMENTS: req-web-nav-auto-parent@7d79eeae6af7/a089aa4320b9 (derivation) — the
        URL hierarchy IS the hierarchy: each parent level is the URL minus its
        trailing slice, derived here with no page-to-parent edge.

    For each URL prefix `/<seg-1>/.../<seg-k>`, looks up a registered `Page`
    by its `slug`. If a Page exists at that prefix, the segment uses the
    Page's `name` and links to its URL. If not, the segment renders the
    raw slug title-cased as plain text.

    The home segment `/` is always present and marked `is_home=True`. The
    last segment is marked `is_current=True`. When the URL is just `/`,
    the home segment IS the current segment.

    All Page lookups happen in a single batched query.
    """
    # Lazy import — this module is loaded by the context processor and we
    # want to avoid circular imports during app initialization.
    from tap_web.models import Page

    path = url.rstrip("/")
    if not path:
        # Just the home page.
        return [
            BreadcrumbSegment(
                label="",
                url="/",
                is_registered=True,
                is_current=True,
                is_home=True,
            )
        ]

    parts = [p for p in path.split("/") if p]
    prefixes = ["/" + "/".join(parts[: i + 1]) for i in range(len(parts))]

    # The breadcrumb chrome renders on EVERY response (context processor), long
    # before we know the caller holds grid.read — including anonymous renders
    # (the login page) and capability-less authenticated renders (the no-access
    # page, error pages). The Page enrichment below is a guarded BaseModel read;
    # running it unconditionally trips the ORM read backstop and 500s those
    # pages (req-tap-auth-orm-read-backstop). So the always-present shell is
    # read-free: we only enrich labels/links when the caller is authorized to
    # read the grid, and otherwise fall through to the URL-derived plain-text
    # segments below. This is the interim shape; the enrichment moves into a
    # gated nav Panel under req-web-nav-panel (nav-as-panel migration).
    from tap_grid.read_guard import caller_can_read

    # One batched query for every prefix, including the home page (slug "/").
    # Filter `discoverable=True` so parameterized pages (e.g. /samsite/finding,
    # which requires an entity_id) render as plain text in the breadcrumb
    # rather than as broken links — same gate used by nav-index, palette,
    # chevron popovers, and column-view per req-web-nav-page-discoverable.
    if caller_can_read():
        page_map = {p.slug: p.name for p in Page.objects.filter(slug__in=["/", *prefixes], discoverable=True)}
    else:
        page_map = {}

    segments: list[BreadcrumbSegment] = [
        BreadcrumbSegment(
            label="",
            url="/",
            is_registered="/" in page_map,
            is_current=False,
            is_home=True,
        )
    ]

    for i, prefix in enumerate(prefixes):
        is_current = i == len(prefixes) - 1
        page_name = page_map.get(prefix)
        if page_name:
            segments.append(
                BreadcrumbSegment(
                    label=page_name,
                    url=prefix,
                    is_registered=True,
                    is_current=is_current,
                    is_home=False,
                )
            )
        else:
            label = parts[i].replace("-", " ").replace("_", " ").title()
            segments.append(
                BreadcrumbSegment(
                    label=label,
                    url=prefix,
                    is_registered=False,
                    is_current=is_current,
                    is_home=False,
                )
            )

    return segments


def breadcrumb(request) -> dict[str, list[BreadcrumbSegment]]:
    """Context processor: expose the request's breadcrumb to every template.

    The chrome in `tap_web/templates/tap_web/base.html` consumes `breadcrumb`
    to render the header. Per req-web-nav-chrome-budget, this is the only
    navigation chrome the platform exposes.

    TAP-IMPLEMENTS: req-web-nav-chrome-read-free@89552760a99b/6c67a5e4aa22 (derivation) —
        chrome renders on every response because this processor derives the
        breadcrumb from the request path alone; no grid read stands between an
        anonymous or capability-less render and its header.
    """
    return {"breadcrumb": build_breadcrumb(request.path)}
