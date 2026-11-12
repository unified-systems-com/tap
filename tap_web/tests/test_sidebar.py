"""Tests for req-web-nav-sidebar: the structural sidebar beside the content.

The tree is the nav index's page set arranged by its parent resolution: discoverable
pages only, NESTS_UNDER parents over URL parents, siblings in nav_weight order, the
current page marked, nothing hand-added, nothing for a caller without grid.read.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client

from tap_grid.services import create_edge
from tap_web.models import Page
from tap_web.navigation import assemble_nav_tree

_MINIMAL_LAYOUT = {"columns": {"col-1": {"width": "1fr", "rows": {"row-1": {"panel-id": "x"}}}}}


def _auth_client() -> Client:
    user, _ = get_user_model().objects.get_or_create(username="sidebar-user")
    user.groups.add(Group.objects.get(name="tap_viewer"))
    client = Client()
    client.force_login(user)
    return client


def _page(name: str, slug: str, *, discoverable: bool = True, nav_weight: int = 0) -> Page:
    page: Page = Page.objects.create(
        name=name, slug=slug, layout=_MINIMAL_LAYOUT, discoverable=discoverable, nav_weight=nav_weight
    )
    return page


def _aside(body: str) -> str:
    match = re.search(r'<aside class="tap-sb".*?</aside>', body, re.S)
    return match.group(0) if match else ""


class TestAssemble:
    @pytest.mark.spec("req-web-nav-sidebar-1")
    def test_nests_by_url_and_orders_by_weight_then_name(self):
        pages = [("/", "Home", 0), ("/ops", "Ops", 5), ("/ops/b", "Bravo", 0), ("/ops/a", "Alpha", 0), ("/zed", "Zed", 9)]
        tree = assemble_nav_tree(pages, {}, "/")
        assert [n.url for n in tree] == ["/zed", "/ops"]
        assert [c.name for c in tree[1].children] == ["Alpha", "Bravo"]

    @pytest.mark.spec("req-web-nav-sidebar-1")
    def test_explicit_parent_moves_a_page(self):
        tree = assemble_nav_tree([("/ops", "Ops", 0), ("/costs", "Costs", 0)], {"/costs": "/ops"}, "/")
        assert [n.url for n in tree] == ["/ops"]
        assert [c.url for c in tree[0].children] == ["/costs"]

    @pytest.mark.spec("req-web-nav-sidebar-1")
    def test_unlisted_intermediate_level_lifts_the_child(self):
        tree = assemble_nav_tree([("/ops", "Ops", 0), ("/ops/x/deep", "Deep", 0)], {}, "/")
        assert [c.url for c in tree[0].children] == ["/ops/x/deep"]

    @pytest.mark.spec("req-web-nav-sidebar-2")
    def test_current_and_ancestors_are_marked(self):
        tree = assemble_nav_tree([("/ops", "Ops", 0), ("/ops/a", "A", 0)], {}, "/ops/a/")
        assert tree[0].is_open and not tree[0].is_current
        assert tree[0].children[0].is_current

    @pytest.mark.spec("req-web-nav-sidebar-2")
    def test_unlisted_current_marks_nearest_listed_ancestor(self):
        tree = assemble_nav_tree([("/ops", "Ops", 0)], {}, "/ops/finding")
        assert tree[0].is_current


@pytest.mark.django_db
class TestRendered:
    @pytest.mark.spec("req-web-nav-sidebar-1")
    def test_lists_exactly_the_discoverable_pages(self):
        _page("Ops", "/ops", nav_weight=2)
        _page("Alpha", "/ops/alpha")
        _page("Hidden", "/ops/hidden", discoverable=False)
        aside = _aside(_auth_client().get("/ops").content.decode())
        assert 'aria-label="Rooms"' in aside
        hrefs = re.findall(r'class="tap-sb-link"[^>]*href="([^"]+)"|href="([^"]+)" class="tap-sb-link"', aside)
        assert sorted(a or b for a, b in hrefs) == ["/ops", "/ops/alpha"]

    @pytest.mark.spec("req-web-nav-sidebar-1")
    def test_nests_under_edge_reaches_the_rail(self):
        ops = _page("Ops", "/ops")
        costs = _page("Costs", "/costs")
        create_edge(costs.entity, ops.entity, "NESTS_UNDER")
        aside = _aside(_auth_client().get("/ops").content.decode())
        nested = re.search(r'<ul class="tap-sb-list tap-sb-list--nested".*?</ul>', aside, re.S)
        assert nested and 'href="/costs"' in nested.group(0)

    @pytest.mark.spec("req-web-nav-sidebar-2")
    def test_current_page_carries_aria_current(self):
        _page("Ops", "/ops")
        _page("Alpha", "/ops/alpha")
        aside = _aside(_auth_client().get("/ops/alpha").content.decode())
        assert re.search(r'href="/ops/alpha"[^>]*aria-current="page"', aside)
        assert not re.search(r'href="/ops"[^>]*aria-current', aside)

    @pytest.mark.spec("req-web-nav-sidebar-3")
    def test_collapse_is_a_labelled_button_and_no_hamburger_exists(self):
        _page("Ops", "/ops")
        body = _auth_client().get("/ops").content.decode()
        aside = _aside(body)
        assert re.search(r'<button[^>]*data-tap-sb-collapse[^>]*aria-label="Collapse sidebar"', aside)
        assert "hamburger" not in body.lower()
        assert "sidebar-init.js" in body

    @pytest.mark.spec("req-web-nav-sidebar-4")
    def test_no_sidebar_without_read(self):
        _page("Ops", "/ops")
        user, _ = get_user_model().objects.get_or_create(username="sidebar-noread")
        client = Client()
        client.force_login(user)
        body = client.get("/ops").content.decode()
        assert 'class="tap-sb"' not in body
        assert 'id="tap-drawer"' not in body
