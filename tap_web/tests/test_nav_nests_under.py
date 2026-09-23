"""Tests for req-web-nav-explicit-parent-edge: the NESTS_UNDER page-to-page nav edge.

A live NESTS_UNDER edge from a child page to a parent page moves the child under
the parent in the header breadcrumb and in /__nav-index.json (which the palette
tree, sibling popover and column view read), without changing any URL. Without
such an edge every surface is exactly what the URL-derived rule produced.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client

from tap_grid.exceptions import EdgePropertyValidationError, InvalidEdgeError
from tap_grid.models import Edge
from tap_grid.services import create_edge, delete_edge_by_entity
from tap_web import navigation
from tap_web.models import Page
from tap_web.navigation import BreadcrumbSegment, build_breadcrumb, choose_explicit_parents, effective_path

_MINIMAL_LAYOUT = {"columns": {"col-1": {"width": "1fr", "rows": {"row-1": {"panel-id": "x"}}}}}


def _auth_client() -> Client:
    """Authenticated client holding grid.read (tap_viewer), as the nav routes require."""
    user, _ = get_user_model().objects.get_or_create(username="nests-under-user")
    user.groups.add(Group.objects.get(name="tap_viewer"))
    client = Client()
    client.force_login(user)
    return client


def _page(name: str, slug: str, *, discoverable: bool = True, nav_weight: int = 0) -> Page:
    page: Page = Page.objects.create(
        name=name, slug=slug, layout=_MINIMAL_LAYOUT, discoverable=discoverable, nav_weight=nav_weight
    )
    return page


def _discoverable_page_names() -> dict[str, str]:
    """``{slug: name}`` for every discoverable page: what the breadcrumb may label."""
    pages = cast("list[Page]", list(Page.objects.filter(discoverable=True)))
    return {page.slug: page.name for page in pages}


def _nest(child: Page, parent: Page) -> Edge:
    """Draw child NESTS_UNDER parent through the service layer."""
    return create_edge(child.entity, parent.entity, "NESTS_UNDER")


def _url_only_breadcrumb(url: str, page_map: dict[str, str]) -> list[BreadcrumbSegment]:
    """The URL-derived breadcrumb as it was computed before NESTS_UNDER existed.

    A frozen reference for req-web-nav-explicit-parent-edge-8: with no edges, the
    new code must produce exactly this.
    """
    path = url.rstrip("/")
    if not path:
        return [BreadcrumbSegment(label="", url="/", is_registered=True, is_current=True, is_home=True)]
    parts = [p for p in path.split("/") if p]
    prefixes = ["/" + "/".join(parts[: i + 1]) for i in range(len(parts))]
    segments = [BreadcrumbSegment(label="", url="/", is_registered="/" in page_map, is_current=False, is_home=True)]
    for i, prefix in enumerate(prefixes):
        name = page_map.get(prefix)
        segments.append(
            BreadcrumbSegment(
                label=name or parts[i].replace("-", " ").replace("_", " ").title(),
                url=prefix,
                is_registered=bool(name),
                is_current=i == len(prefixes) - 1,
                is_home=False,
            )
        )
    return segments


@pytest.fixture
def vendor_pages() -> dict[str, Page]:
    """An instance page, a URL child of it, and three top-level vendor pages."""
    return {
        "highbar": _page("Highbar", "/highbar", nav_weight=100),
        "overview": _page("Overview", "/highbar/overview"),
        "teleport": _page("Teleport", "/teleport", nav_weight=120),
        "okta": _page("Okta", "/okta", nav_weight=300),
        "other": _page("Other", "/other"),
    }


@pytest.mark.spec("req-web-nav-explicit-parent-edge-1")
@pytest.mark.django_db
class TestEdgeType:
    """req-web-nav-explicit-parent-edge-1: the edge type's declared shape is enforced at write."""

    def test_page_to_page_is_accepted_with_web_dimension(self, vendor_pages):
        edge = _nest(vendor_pages["teleport"], vendor_pages["highbar"])
        assert edge.edge_type == "NESTS_UNDER"
        assert edge.entity.dimensions == {"tap.graph": "web"}

    def test_properties_are_refused(self, vendor_pages):
        with pytest.raises(EdgePropertyValidationError):
            create_edge(
                vendor_pages["teleport"].entity,
                vendor_pages["highbar"].entity,
                "NESTS_UNDER",
                properties={"order": 1},
            )

    def test_non_page_source_is_refused(self, vendor_pages):
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        other = ConstrainedSource.objects.create(name="not a page")
        with pytest.raises(InvalidEdgeError):
            create_edge(other.entity, vendor_pages["highbar"].entity, "NESTS_UNDER")

    def test_non_page_target_is_refused(self, vendor_pages):
        from tap_plugin.grid_fixtures.models import ConstrainedSource

        other = ConstrainedSource.objects.create(name="not a page")
        with pytest.raises(InvalidEdgeError):
            create_edge(vendor_pages["teleport"].entity, other.entity, "NESTS_UNDER")


@pytest.mark.spec("req-web-nav-explicit-parent-edge-2")
@pytest.mark.spec("req-web-nav-explicit-parent-edge-3")
@pytest.mark.django_db
class TestBreadcrumb:
    """req-web-nav-explicit-parent-edge-2/-3: the header breadcrumb follows the edge; the URL does not move."""

    def test_vendor_page_nests_under_instance_page(self, vendor_pages):
        _nest(vendor_pages["teleport"], vendor_pages["highbar"])
        segments = build_breadcrumb("/teleport")
        assert [s.url for s in segments] == ["/", "/highbar", "/teleport"]
        assert [s.label for s in segments] == ["", "Highbar", "Teleport"]
        assert [s.is_current for s in segments] == [False, False, True]
        assert segments[1].is_registered is True

    def test_levels_below_the_child_follow_it(self, vendor_pages):
        """An unregistered URL child of the nested page nests with it."""
        _nest(vendor_pages["teleport"], vendor_pages["highbar"])
        segments = build_breadcrumb("/teleport/clusters/")
        assert [s.url for s in segments] == ["/", "/highbar", "/teleport", "/teleport/clusters"]
        assert segments[-1].label == "Clusters"
        assert segments[-1].is_current is True

    def test_levels_above_the_parent_continue_by_the_same_rule(self, vendor_pages):
        org = _page("Org", "/org")
        _nest(vendor_pages["teleport"], vendor_pages["highbar"])
        _nest(vendor_pages["highbar"], org)
        assert [s.url for s in build_breadcrumb("/teleport")] == ["/", "/org", "/highbar", "/teleport"]

    def test_unrelated_pages_keep_their_url_parent(self, vendor_pages):
        _nest(vendor_pages["teleport"], vendor_pages["highbar"])
        assert [s.url for s in build_breadcrumb("/other")] == ["/", "/other"]
        assert [s.url for s in build_breadcrumb("/highbar/overview")] == ["/", "/highbar", "/highbar/overview"]

    def test_page_renders_at_its_own_url_with_its_query_string(self, vendor_pages):
        """-3: no redirect, the current segment is the requested page, the parent is a link."""
        _nest(vendor_pages["teleport"], vendor_pages["highbar"])
        response = _auth_client().get("/teleport?cluster=prod")
        assert response.status_code == 200
        assert response.request["QUERY_STRING"] == "cluster=prod"
        body = response.content.decode()
        assert 'data-tap-sibling-url="/highbar"' in body
        assert '<a href="/highbar" class="text-slate-300 hover:text-white transition-colors" ' in body
        assert 'aria-current="page" data-tap-segment-url="/teleport">Teleport</span>' in body

    def test_edges_and_pages_are_two_queries_at_any_depth(self, vendor_pages, django_assert_num_queries):
        org = _page("Org", "/org")
        _nest(vendor_pages["teleport"], vendor_pages["highbar"])
        _nest(vendor_pages["highbar"], org)
        with django_assert_num_queries(2):
            build_breadcrumb("/teleport/a/b/c")


@pytest.mark.spec("req-web-nav-explicit-parent-edge-5")
@pytest.mark.django_db
class TestSeveralParents:
    """req-web-nav-explicit-parent-edge-5: highest nav_weight parent wins, then the lower slug."""

    def test_higher_weight_parent_wins_regardless_of_write_order(self, vendor_pages):
        low = _page("Low", "/low", nav_weight=5)
        high = _page("High", "/high", nav_weight=50)
        _nest(vendor_pages["teleport"], high)
        _nest(vendor_pages["teleport"], low)
        assert build_breadcrumb("/teleport")[1].url == "/high"

    def test_equal_weight_resolves_by_lower_slug(self, vendor_pages):
        beta = _page("Beta", "/beta", nav_weight=10)
        alpha = _page("Alpha", "/alpha", nav_weight=10)
        _nest(vendor_pages["teleport"], beta)
        _nest(vendor_pages["teleport"], alpha)
        assert build_breadcrumb("/teleport")[1].url == "/alpha"

    def test_chooser_is_order_independent(self):
        rows = [("/c", "/b", 1), ("/c", "/a", 1), ("/c", "/z", 2), ("/d", None, 9), (None, "/a", 9)]
        assert choose_explicit_parents(rows) == {"/c": "/z"}
        assert choose_explicit_parents(list(reversed(rows))) == {"/c": "/z"}


@pytest.mark.spec("req-web-nav-explicit-parent-edge-6")
@pytest.mark.django_db
class TestCycles:
    """req-web-nav-explicit-parent-edge-6: a cycle falls back to the URL path, logged, never hangs."""

    def test_two_page_cycle_falls_back_to_url(self, vendor_pages):
        _nest(vendor_pages["teleport"], vendor_pages["okta"])
        _nest(vendor_pages["okta"], vendor_pages["teleport"])
        with patch.object(navigation.logger, "warning") as warn:
            segments = build_breadcrumb("/teleport")
        assert [s.url for s in segments] == ["/", "/teleport"]
        assert warn.call_count == 1
        assert warn.call_args.args[0].startswith("[f7f4]")

    def test_self_edge_falls_back_to_url(self, vendor_pages):
        _nest(vendor_pages["teleport"], vendor_pages["teleport"])
        with patch.object(navigation.logger, "warning"):
            assert [s.url for s in build_breadcrumb("/teleport/x")] == ["/", "/teleport", "/teleport/x"]

    def test_cycle_through_a_url_parent_falls_back(self):
        """/a/b's URL parent is /a, and /a NESTS_UNDER /a/b: the walk revisits /a/b."""
        with patch.object(navigation.logger, "warning"):
            assert effective_path("/a/b", {"/a": "/a/b"}) == ["/a", "/a/b"]

    def test_nav_index_survives_a_cycle(self, vendor_pages):
        _nest(vendor_pages["teleport"], vendor_pages["okta"])
        _nest(vendor_pages["okta"], vendor_pages["teleport"])
        with patch.object(navigation.logger, "warning"):
            response = _auth_client().get("/__nav-index.json")
        assert response.status_code == 200
        entry = next(p for p in response.json()["pages"] if p["url"] == "/teleport")
        assert [s["url"] for s in entry["breadcrumb"]] == ["/", "/teleport"]


@pytest.mark.spec("req-web-nav-explicit-parent-edge-7")
@pytest.mark.django_db
class TestOnlyLiveDiscoverableParentsCount:
    """req-web-nav-explicit-parent-edge-7."""

    def test_non_discoverable_parent_is_ignored(self, vendor_pages):
        hidden = _page("Hidden", "/hidden", discoverable=False)
        _nest(vendor_pages["teleport"], hidden)
        assert [s.url for s in build_breadcrumb("/teleport")] == ["/", "/teleport"]

    def test_retired_edge_is_ignored(self, vendor_pages):
        edge = _nest(vendor_pages["teleport"], vendor_pages["highbar"])
        delete_edge_by_entity(edge.entity_id)
        assert [s.url for s in build_breadcrumb("/teleport")] == ["/", "/teleport"]


@pytest.mark.spec("req-web-nav-explicit-parent-edge-4")
@pytest.mark.django_db
class TestNavIndex:
    """req-web-nav-explicit-parent-edge-4: the index reports the effective path every surface reads."""

    def test_entry_breadcrumb_is_the_effective_path(self, vendor_pages):
        _nest(vendor_pages["teleport"], vendor_pages["highbar"])
        _nest(vendor_pages["okta"], vendor_pages["highbar"])
        pages = {p["url"]: p for p in _auth_client().get("/__nav-index.json").json()["pages"]}
        assert pages["/teleport"]["url"] == "/teleport"
        assert pages["/teleport"]["breadcrumb"] == [
            {"label": "", "url": "/"},
            {"label": "Highbar", "url": "/highbar"},
            {"label": "Teleport", "url": "/teleport"},
        ]

    def test_palette_tree_and_sibling_popover_inputs(self, vendor_pages):
        """The JS surfaces take a page's parent from breadcrumb[-2] (palette tree) and list
        siblings as the pages sharing breadcrumb[depth-1] (popover, column view)."""
        _nest(vendor_pages["teleport"], vendor_pages["highbar"])
        _nest(vendor_pages["okta"], vendor_pages["highbar"])
        pages = _auth_client().get("/__nav-index.json").json()["pages"]
        parent_of = {p["url"]: p["breadcrumb"][-2]["url"] for p in pages if len(p["breadcrumb"]) >= 2}
        assert parent_of["/teleport"] == "/highbar"
        assert parent_of["/okta"] == "/highbar"
        assert parent_of["/other"] == "/"
        highbar_children = {
            p["breadcrumb"][2]["url"]
            for p in pages
            if len(p["breadcrumb"]) > 2 and p["breadcrumb"][1]["url"] == "/highbar"
        }
        assert highbar_children == {"/highbar/overview", "/teleport", "/okta"}


@pytest.mark.spec("req-web-nav-explicit-parent-edge-8")
@pytest.mark.django_db
class TestNoEdgesNoChange:
    """req-web-nav-explicit-parent-edge-8: without edges the output equals the URL-derived reference."""

    URLS = ["/", "/highbar", "/highbar/overview", "/teleport/", "/teleport//x", "/nope/deeper", "/hidden/child"]

    def test_breadcrumb_matches_url_reference(self, vendor_pages):
        _page("Hidden", "/hidden", discoverable=False)
        page_map = _discoverable_page_names()
        for url in self.URLS:
            assert build_breadcrumb(url) == _url_only_breadcrumb(url, page_map), url

    def test_nav_index_matches_url_reference(self, vendor_pages):
        page_map = _discoverable_page_names()
        for entry in _auth_client().get("/__nav-index.json").json()["pages"]:
            expected = [{"label": s.label, "url": s.url} for s in _url_only_breadcrumb(entry["url"], page_map)]
            assert entry["breadcrumb"] == expected, entry["url"]

    def test_effective_path_without_parents_is_the_url_prefixes(self):
        assert effective_path("/a/b/c", {}) == ["/a", "/a/b", "/a/b/c"]
        assert effective_path("/a/b/c", {"/x": "/y"}) == ["/a", "/a/b", "/a/b/c"]


@pytest.mark.spec("req-web-nav-explicit-parent-edge-9")
@pytest.mark.django_db
class TestReadFree:
    """req-web-nav-explicit-parent-edge-9: no grid.read, no edge read, URL-derived breadcrumb."""

    def test_capless_caller_reads_nothing(self, vendor_pages, django_assert_num_queries):
        from tap_grid.caller_context import CallerContext, set_caller_context

        _nest(vendor_pages["teleport"], vendor_pages["highbar"])
        set_caller_context(CallerContext(user=None))
        with django_assert_num_queries(0):
            segments = build_breadcrumb("/teleport")
        assert [s.url for s in segments] == ["/", "/teleport"]
        assert segments[1].is_registered is False
