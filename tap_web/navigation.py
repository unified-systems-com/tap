"""URL → breadcrumb decomposition per spec-web-navigation.

The breadcrumb chrome is built once per request from the URL path. The
home segment is always the product mark (resolved by the template); each
subsequent URL slice becomes a breadcrumb level whose label and link are
derived from a registered `Page` at that URL prefix. Unregistered prefixes
render as plain text (raw slug title-cased), unclickable.

Per req-web-nav-auto-parent, the URL hierarchy is the default hierarchy.
Per req-web-nav-explicit-parent-edge, a live `NESTS_UNDER` edge from one Page
to another overrides the URL-derived parent of the source page; every level
without such an edge still takes its parent from the URL. URLs never change:
only the path the chrome projects does.

Parameterized routes (e.g., `/object/<type>/<id>/`) are out of scope for
v0 — those routes generate breadcrumbs through a different code path.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

logger = logging.getLogger(__name__)

NESTS_UNDER = "NESTS_UNDER"
"""The page-to-page edge type that overrides a page's URL-derived nav parent (declared in `tap_web.apps`)."""


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


def choose_explicit_parents(rows: Iterable[tuple[str | None, str | None, int | None]]) -> dict[str, str]:
    """Pick one explicit nav parent per child page from its NESTS_UNDER candidates.

    Each row is ``(child_slug, parent_slug, parent_nav_weight)`` for one live
    NESTS_UNDER edge. A row whose child or parent did not resolve to a live Page
    (or whose parent is not discoverable) arrives with ``None`` there and is
    skipped. When a child has more than one candidate, the parent with the
    highest ``nav_weight`` wins; equal weights resolve by the lower slug, so the
    choice is deterministic and independent of edge creation order.

    Returns:
        ``{child_slug: parent_slug}`` — only children that have a usable candidate.
    """
    best: dict[str, tuple[int, str]] = {}
    for child_slug, parent_slug, parent_weight in rows:
        if not child_slug or not parent_slug:
            continue
        rank = (-(parent_weight or 0), parent_slug)
        current = best.get(child_slug)
        if current is None or rank < current:
            best[child_slug] = rank
    return {child_slug: rank[1] for child_slug, rank in best.items()}


def load_explicit_parents() -> dict[str, str]:
    """Read every live NESTS_UNDER edge between live Pages in one query.

    The child end is the edge's source Page; the parent end is its target Page,
    which must be discoverable (a non-discoverable parent needs a URL parameter,
    so no discovery surface could link to it). Callers must already hold
    `grid.read`; `build_breadcrumb` checks `caller_can_read()` before calling.

    Returns:
        ``{child_slug: parent_slug}`` as chosen by :func:`choose_explicit_parents`.
    """
    from django.db.models import OuterRef, Subquery

    from tap_grid.models import Edge
    from tap_web.models import Page

    # django-stubs types Page.objects as the BaseModel manager, so it cannot see Page's
    # own fields in .values(); the ignores below are that friction, not a type hole.
    child_page = Page.objects.filter(entity=OuterRef("from_entity"))
    parent_page = Page.objects.filter(entity=OuterRef("to_entity"), discoverable=True)
    child_slug = child_page.values("slug")[:1]  # type: ignore[misc]
    parent_slug = parent_page.values("slug")[:1]  # type: ignore[misc]
    parent_weight = parent_page.values("nav_weight")[:1]  # type: ignore[misc]
    rows = (
        Edge.objects.filter(edge_type=NESTS_UNDER)
        .annotate(
            child_slug=Subquery(child_slug),
            parent_slug=Subquery(parent_slug),
            parent_weight=Subquery(parent_weight),
        )
        .values_list("child_slug", "parent_slug", "parent_weight")
    )
    return choose_explicit_parents(rows)


def _url_parent(slug: str) -> str:
    """Return the URL-derived parent of a normalized slug: ``/a/b`` -> ``/a``, ``/a`` -> ``/``."""
    head = slug.rsplit("/", 1)[0]
    return head or "/"


def effective_path(url: str, explicit_parents: Mapping[str, str]) -> list[str]:
    """Return the ordered non-home levels from the root down to ``url``.

    TAP-IMPLEMENTS: req-web-nav-explicit-parent-edge@0355d5dd15ec/b1f149f01fb4 (derivation) — the
        effective parent of every level: explicit NESTS_UNDER parent first, URL
        parent otherwise, cycle falls back to the URL path. Header and nav index
        both call this, so every surface shows the same tree.

    Walks up from ``url``: at each level the parent is the explicit NESTS_UNDER
    parent when the level has one, otherwise the URL minus its trailing slice.
    The walk stops at ``/``. With no explicit parents the result is exactly the
    URL's own prefixes. If the walk revisits a level, the explicit parents form a
    cycle; the cycle is logged and the URL's own prefixes are returned instead,
    so a bad edge can never hang or loop navigation.
    """
    parts = [p for p in url.split("/") if p]
    url_prefixes = ["/" + "/".join(parts[: i + 1]) for i in range(len(parts))]
    if not parts or not explicit_parents:
        return url_prefixes

    current = url_prefixes[-1]
    chain = [current]
    seen = {current}
    while True:
        parent = explicit_parents.get(current) or _url_parent(current)
        if parent == "/":
            break
        if parent in seen:
            logger.warning("[f7f4] NESTS_UNDER cycle reached %s from %s; using the URL-derived breadcrumb", parent, url)
            return url_prefixes
        chain.append(parent)
        seen.add(parent)
        current = parent
    chain.reverse()
    return chain


def build_breadcrumb(url: str, explicit_parents: Mapping[str, str] | None = None) -> list[BreadcrumbSegment]:
    """Decompose a URL into breadcrumb segments.

    TAP-IMPLEMENTS: req-web-nav-auto-parent@230e975dfd7b/7d1e8b146258 (derivation) — the
        URL hierarchy is the default hierarchy: every level without an explicit
        NESTS_UNDER parent takes the URL minus its trailing slice.

    For each level of the page's effective path (see :func:`effective_path`),
    looks up a registered `Page` by its `slug`. If a Page exists at that level,
    the segment uses the Page's `name` and links to its URL. If not, the
    segment renders the level's last slug title-cased as plain text.

    The home segment `/` is always present and marked `is_home=True`. The
    last segment is marked `is_current=True` and is always ``url`` itself.
    When the URL is just `/`, the home segment IS the current segment.

    Args:
        url: The request path (no query string).
        explicit_parents: Pre-loaded ``{child_slug: parent_slug}`` map, so a
            caller building many breadcrumbs (the nav index) reads the
            NESTS_UNDER edges once. ``None`` reads them here.

    All Page lookups happen in a single batched query; the NESTS_UNDER edges
    in one more.
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

    can_read = caller_can_read()
    if can_read and explicit_parents is None:
        explicit_parents = load_explicit_parents()
    # A caller who cannot read the grid gets no edge read either: the URL alone.
    prefixes = effective_path(path, explicit_parents if can_read and explicit_parents else {})

    # One batched query for every prefix, including the home page (slug "/").
    # Filter `discoverable=True` so parameterized pages (e.g. /samsite/finding,
    # which requires an entity_id) render as plain text in the breadcrumb
    # rather than as broken links — same gate used by nav-index, palette,
    # chevron popovers, and column-view per req-web-nav-page-discoverable.
    if can_read:
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
            label = prefix.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").title()
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
