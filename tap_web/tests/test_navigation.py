"""Tests for the breadcrumb helper + nav-index endpoint.

Covers req-web-nav-auto-parent (URL → breadcrumb decomposition; registered
vs. unregistered prefix handling) and req-web-nav-index-endpoint (the
machine-readable nav index's schema and population).
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client

from tap_web.models import Page
from tap_web.navigation import build_breadcrumb

# Pages require a valid layout to pass model-level validation. These tests
# don't care about layout content; the helpers only read `slug` and `name`.
_MINIMAL_LAYOUT = {"columns": {"col-1": {"width": "1fr", "rows": {"row-1": {"panel-id": "x"}}}}}


def _auth_client() -> Client:
    """Authenticated client holding grid.read (tap_viewer). The default-deny login
    wall (req-tap-auth-service-boundary) requires a session to reach any tap_web
    page, and tap_web read routes now gate on grid.read (req-tap-auth-policy) with
    the ORM read backstop beneath (req-tap-auth-orm-read-backstop) — so a browsing
    user must hold grid.read. (During an HTTP request the middleware binds the
    request user as the caller context, so the autouse tap_test context does not
    apply.) get_or_create so repeated calls within one test don't collide."""
    user, _ = get_user_model().objects.get_or_create(username="nav-user")
    user.groups.add(Group.objects.get(name="tap_viewer"))
    c = Client()
    c.force_login(user)
    return c


def _create_page(
    name: str,
    slug: str,
    description: str = "",
    discoverable: bool = True,
    nav_weight: int = 0,
) -> Page:
    return Page.objects.create(
        name=name,
        slug=slug,
        description=description,
        layout=_MINIMAL_LAYOUT,
        discoverable=discoverable,
        nav_weight=nav_weight,
    )


@pytest.mark.django_db
class TestBreadcrumbReadFree:
    """The chrome shell is read-free when the caller cannot read the grid.

    The breadcrumb context processor runs on every response, before we know the
    caller holds grid.read (anonymous login render, capability-less authenticated
    render). Enriching segments from `Page` is a guarded read; running it for a
    caller without grid.read trips the ORM read backstop and 500s the page
    (req-tap-auth-orm-read-backstop). `build_breadcrumb` therefore only reads
    Pages when `caller_can_read()`, degrading to URL-derived plain text otherwise.
    Regression guard for the 2026-07-01 login outage.
    """

    def test_capless_caller_degrades_to_plain_text_without_reading(self):
        from tap_grid.caller_context import CallerContext, set_caller_context

        # A Page that WOULD enrich /samsite into a clickable "Compliance Home"
        # link — its name differs from the URL-derived title-case so we can tell
        # the enriched path from the degraded path.
        _create_page(name="Compliance Home", slug="/samsite")

        # Anonymous caller (user=None) holds no grid.read.
        set_caller_context(CallerContext(user=None))

        # Must NOT raise (the guarded Page read is skipped, not tripped)...
        segments = build_breadcrumb("/samsite")

        # ...and the segment degrades to the URL-derived plain-text form.
        samsite = segments[1]
        assert samsite.is_registered is False
        assert samsite.label == "Samsite"  # title-cased slug, NOT the Page name


@pytest.mark.django_db
class TestBuildBreadcrumb:
    """Decomposition of URL paths into BreadcrumbSegment chains."""

    def test_home_returns_single_segment(self):
        segments = build_breadcrumb("/")
        assert len(segments) == 1
        assert segments[0].is_home is True
        assert segments[0].is_current is True
        assert segments[0].url == "/"

    def test_single_segment_path_has_home_plus_one(self):
        _create_page("Samsite", "/samsite")
        segments = build_breadcrumb("/samsite")
        assert len(segments) == 2
        assert segments[0].is_home is True
        assert segments[0].is_current is False
        assert segments[1].label == "Samsite"
        assert segments[1].is_current is True
        assert segments[1].is_registered is True

    def test_two_segment_path_marks_last_current(self):
        _create_page("Samsite", "/samsite")
        _create_page("Samsite Compliance", "/samsite/compliance")
        segments = build_breadcrumb("/samsite/compliance")
        labels = [s.label for s in segments]
        assert labels == ["", "Samsite", "Samsite Compliance"]
        assert [s.is_current for s in segments] == [False, False, True]

    def test_unregistered_prefix_renders_unclickable(self):
        """A URL prefix with no registered Page renders as title-cased plain text."""
        # Only register the LEAF, not the intermediate.
        _create_page("Final Page", "/foo/bar/final-page")
        segments = build_breadcrumb("/foo/bar/final-page")
        # Segments: [home, foo, bar, final-page]
        assert len(segments) == 4
        assert segments[1].label == "Foo"  # title-cased slug
        assert segments[1].is_registered is False
        assert segments[2].label == "Bar"
        assert segments[2].is_registered is False
        assert segments[3].label == "Final Page"
        assert segments[3].is_registered is True
        assert segments[3].is_current is True

    def test_trailing_slash_normalized(self):
        _create_page("Samsite", "/samsite")
        with_slash = build_breadcrumb("/samsite/")
        without_slash = build_breadcrumb("/samsite")
        assert [s.url for s in with_slash] == [s.url for s in without_slash]
        assert [s.label for s in with_slash] == [s.label for s in without_slash]

    def test_dash_in_slug_title_cased_when_unregistered(self):
        segments = build_breadcrumb("/my-cool-page")
        # No Page registered → renders the slug title-cased.
        assert segments[1].label == "My Cool Page"
        assert segments[1].is_registered is False

    def test_underscore_in_slug_title_cased_when_unregistered(self):
        segments = build_breadcrumb("/my_cool_page")
        assert segments[1].label == "My Cool Page"

    def test_home_marked_is_home_regardless_of_registration(self):
        """req-web-nav-auto-parent-4: the home segment is always rendered as
        the product mark linking to `/`, whether or not a Page is registered
        there. The helper carries `is_home=True`; the template special-cases
        it. We verify the marker is set; the rendering check is in
        TestBreadcrumbRendering.test_tap_renders_at_home_even_without_root_page.
        """
        segments = build_breadcrumb("/samsite/compliance")
        assert segments[0].is_home is True
        assert segments[0].url == "/"


@pytest.mark.django_db
class TestBreadcrumbRendering:
    """Template-level assertions on the chrome's home-segment special case."""

    def test_chrome_has_palette_affordance(self):
        """req-web-nav-command-palette-2: the chrome carries a visible
        affordance for opening the palette. Click handler + Cmd-K binding
        are JS-side; we only verify the markup is present here.
        """
        body = _auth_client().get("/").content.decode()
        assert "data-tap-palette-affordance" in body
        assert 'aria-label="Open command palette"' in body
        # Keyboard shortcut hint surfaces in the title attribute and the
        # visible kbd chip.
        assert "⌘K" in body

    def test_chrome_loads_palette_assets(self):
        """Palette JS + CSS are linked in the base template head."""
        body = _auth_client().get("/").content.decode()
        assert "tap_web/js/palette.js" in body
        assert "tap_web/css/palette.css" in body

    def test_chrome_loads_breadcrumb_assets(self):
        """Breadcrumb interaction JS + CSS are linked (Phases 6 + 7)."""
        body = _auth_client().get("/").content.decode()
        assert "tap_web/js/breadcrumb.js" in body
        assert "tap_web/css/breadcrumb.css" in body

    def test_chevrons_are_interactive_buttons(self):
        """req-web-nav-segment-interactions-2: separator chevrons are buttons
        with `data-tap-chevron` + `data-tap-sibling-url`, ready for the JS
        click handler to open the sibling popover.
        """
        _create_page("Samsite", "/samsite")
        _create_page("Samsite Compliance", "/samsite/compliance")
        body = _auth_client().get("/samsite/compliance").content.decode()
        assert "data-tap-chevron" in body
        # The chevron preceding "samsite" targets /samsite for sibling lookup.
        assert 'data-tap-sibling-url="/samsite"' in body
        # The chevron preceding "Samsite Compliance" targets /samsite/compliance.
        assert 'data-tap-sibling-url="/samsite/compliance"' in body

    def test_segments_carry_url_for_alt_click_column_view(self):
        """req-web-nav-segment-interactions-3: every segment carries
        `data-tap-segment-url` so the alt-click handler can open column view.
        """
        _create_page("Samsite", "/samsite")
        _create_page("Samsite Compliance", "/samsite/compliance")
        body = _auth_client().get("/samsite/compliance").content.decode()
        assert 'data-tap-segment-url="/"' in body
        assert 'data-tap-segment-url="/samsite"' in body
        assert 'data-tap-segment-url="/samsite/compliance"' in body

    def test_tap_renders_at_home_even_without_root_page(self):
        """req-web-nav-auto-parent-4 in template form: TAP renders + links to /
        on every deep page, even when no Page is registered at slug `/`.
        Regression for the bug where unregistered home fell through to an
        empty-label `<span>`.
        """
        # Create a deep page with NO Page at `/` registered.
        _create_page("Samsite", "/samsite")
        _create_page("Samsite Compliance", "/samsite/compliance")
        body = _auth_client().get("/samsite/compliance").content.decode()
        # The home `<a>` is present, links to /, carries the product mark.
        assert 'href="/"' in body
        assert f">{settings.TAP_PRODUCT_NAME}<" in body  # the configured product mark (RAMPART by default)
        # The home segment is NOT the empty-label unregistered fallback.
        assert '<span class="text-slate-400"></span>' not in body

    def test_lookup_is_batched_in_one_query(self, django_assert_num_queries):
        """All Page lookups happen in a single batched query.

        The count is two: one for the NESTS_UNDER edges (req-web-nav-explicit-parent-edge),
        one for every Page on the path. Neither grows with the depth of the URL.
        """
        _create_page("A", "/a")
        _create_page("B", "/a/b")
        _create_page("C", "/a/b/c")
        with django_assert_num_queries(2):
            build_breadcrumb("/a/b/c")
        with django_assert_num_queries(2):
            build_breadcrumb("/a")


@pytest.mark.django_db
class TestNavIndexEndpoint:
    """The `/__nav-index.json` endpoint exposes the platform's nav surface."""

    def test_returns_200(self):
        response = _auth_client().get("/__nav-index.json")
        assert response.status_code == 200

    def test_response_is_json(self):
        response = _auth_client().get("/__nav-index.json")
        assert response["Content-Type"].startswith("application/json")
        payload = response.json()
        assert "version" in payload
        assert "generated_at" in payload
        assert "pages" in payload
        assert isinstance(payload["pages"], list)

    def test_enumerates_registered_pages(self):
        _create_page("Alpha", "/alpha")
        _create_page("Beta", "/beta")
        response = _auth_client().get("/__nav-index.json")
        urls = {p["url"] for p in response.json()["pages"]}
        assert "/alpha" in urls
        assert "/beta" in urls

    def test_each_page_carries_breadcrumb(self):
        _create_page("Samsite", "/samsite")
        _create_page("Samsite Compliance", "/samsite/compliance")
        response = _auth_client().get("/__nav-index.json")
        entry = next(p for p in response.json()["pages"] if p["url"] == "/samsite/compliance")
        assert "breadcrumb" in entry
        bc = entry["breadcrumb"]
        # Each segment is {label, url}; the home segment has empty label
        # (consumers render the product mark for it).
        assert bc[0] == {"label": "", "url": "/"}
        assert bc[1] == {"label": "Samsite", "url": "/samsite"}
        assert bc[2] == {"label": "Samsite Compliance", "url": "/samsite/compliance"}

    def test_schema_keys_match_spec(self):
        _create_page("A", "/a", description="d")
        response = _auth_client().get("/__nav-index.json")
        payload = response.json()
        # Top-level keys per spec-web-navigation §Machine-Readable Nav Index.
        assert payload["version"] == "0"
        # Each entry has url, name, description, breadcrumb, nav_weight.
        entry = next(p for p in payload["pages"] if p["url"] == "/a")
        assert set(entry.keys()) == {"url", "name", "description", "breadcrumb", "nav_weight"}
        assert entry["description"] == "d"

    def test_excludes_non_discoverable_pages(self):
        """req-web-nav-page-discoverable: Pages with discoverable=False are
        omitted from the nav-index so the palette / chevron popovers /
        column view don't surface parameterized pages.
        """
        _create_page("Visible", "/visible")
        _create_page("Hidden", "/hidden", discoverable=False)
        urls = {p["url"] for p in _auth_client().get("/__nav-index.json").json()["pages"]}
        assert "/visible" in urls
        assert "/hidden" not in urls


@pytest.mark.django_db
class TestNavWeightOrdering:
    """req-web-nav-page-weight: nav_weight controls sort order in the nav-index."""

    def test_default_zero_preserves_alphabetical(self):
        """ACID-1: pages with default weight (0) sort alphabetically by slug."""
        _create_page("Banana", "/b")
        _create_page("Apple", "/a")
        _create_page("Cherry", "/c")
        urls = [p["url"] for p in _auth_client().get("/__nav-index.json").json()["pages"]]
        assert urls == ["/a", "/b", "/c"]

    def test_higher_weight_floats_up(self):
        """ACID-2: nav_weight DESC is the primary sort; positive floats up."""
        _create_page("Apple", "/a")
        _create_page("Banana", "/b", nav_weight=100)
        _create_page("Cherry", "/c", nav_weight=50)
        urls = [p["url"] for p in _auth_client().get("/__nav-index.json").json()["pages"]]
        # /b (100) > /c (50) > /a (0)
        assert urls == ["/b", "/c", "/a"]

    def test_negative_weight_sinks_down(self):
        """ACID-2: negative nav_weight sinks pages below the zero-weight tier."""
        _create_page("Operator", "/operator", nav_weight=-100)
        _create_page("Samsite", "/samsite")
        _create_page("Routine", "/routine")
        urls = [p["url"] for p in _auth_client().get("/__nav-index.json").json()["pages"]]
        # /routine and /samsite (both 0) come first alphabetically; /operator sinks.
        assert urls == ["/routine", "/samsite", "/operator"]

    def test_nav_index_entries_include_weight(self):
        """ACID-4: the endpoint surfaces nav_weight so client-side sort can apply."""
        _create_page("Weighted", "/w", nav_weight=42)
        _create_page("Default", "/d")
        entries = {p["url"]: p for p in _auth_client().get("/__nav-index.json").json()["pages"]}
        assert entries["/w"]["nav_weight"] == 42
        assert entries["/d"]["nav_weight"] == 0

    def test_tiebreaker_is_alphabetical(self):
        """Same-weight pages tie-break alphabetically (by slug at the endpoint)."""
        _create_page("Bravo", "/bravo", nav_weight=10)
        _create_page("Alpha", "/alpha", nav_weight=10)
        _create_page("Charlie", "/charlie", nav_weight=10)
        urls = [p["url"] for p in _auth_client().get("/__nav-index.json").json()["pages"]]
        assert urls == ["/alpha", "/bravo", "/charlie"]


@pytest.mark.django_db
class TestDiscoverableGateInBreadcrumb:
    """Non-discoverable Pages render as plain text in breadcrumbs."""

    def test_non_discoverable_intermediate_renders_unregistered(self):
        """When a URL prefix matches a Page with discoverable=False, the
        breadcrumb segment for that prefix renders as plain text (the
        unregistered-prefix branch) — not as a clickable link to a page
        that would render broken without a URL parameter.
        """
        _create_page("Samsite", "/samsite")
        _create_page("Findings (parameterized)", "/samsite/finding", discoverable=False)
        segments = build_breadcrumb("/samsite/finding/abc-123")
        # Home + samsite (registered) + finding (NOT registered per discoverable=False) + abc-123 (raw)
        assert segments[1].is_registered is True
        assert segments[1].label == "Samsite"
        assert segments[2].is_registered is False  # discoverable=False → treated as unregistered
        assert segments[2].label == "Finding"  # title-cased slug, not the Page's name
        assert segments[3].is_registered is False
        assert segments[3].is_current is True


@pytest.mark.django_db
class TestUserMenu:
    """req-web-nav-user-menu — auth-gated identity + logout in the header chrome."""

    def test_user_menu_present_when_authenticated(self):
        body = _auth_client().get("/").content.decode()
        assert "tap-usermenu" in body  # the menu component
        assert 'action="/auth/logout/"' in body  # logout posts to tap_auth's route
        assert "Sign out" in body

    def test_user_menu_absent_for_anonymous(self):
        # anonymous is caught by the login wall (302) — no authenticated chrome
        resp = Client().get("/")
        assert resp.status_code == 302
        assert "tap-usermenu" not in resp.content.decode()

    def test_user_menu_shows_display_name_not_generated_username(self):
        # the generated ext-<provider>-<hash> login key must never appear in the
        # menu — show the display name + provider avatar (req-tap-auth-external-identity)
        u = get_user_model().objects.create_user(
            username="ext-example-google-zzz",
            email="operator@example.com",
            first_name="George",
            avatar_url="https://lh3.googleusercontent.com/p",
        )
        u.groups.add(Group.objects.get(name="tap_viewer"))  # grid.read to render the page
        c = Client()
        c.force_login(u)
        body = c.get("/").content.decode()
        assert "ext-example-google-zzz" not in body
        assert "George" in body
        assert "lh3.googleusercontent.com/p" in body


def _no_cap_client() -> Client:
    """Authenticated client whose user holds no capability bundle (no grid.read).

    Proves that passing the login wall does not imply permission: the tap_web read
    routes gate on grid.read (req-tap-auth-policy), so a capability-less session is
    denied 403 — distinct from the anonymous 302 to login."""
    user = get_user_model().objects.create_user(username="nav-nocap", password="x")
    c = Client()
    c.force_login(user)
    return c


@pytest.mark.django_db
class TestReadRoutesRequireGridRead:
    """Findings cs-tap-web-page-002 / -panel-001: authenticated no-cap callers are
    denied graph-backed page, nav-index, and panel reads (403), not served 200."""

    def test_page_view_no_cap_denied(self):
        Page.objects.create(name="Secret", slug="/secret", layout=_MINIMAL_LAYOUT)
        resp = _no_cap_client().get("/secret")
        assert resp.status_code == 403

    def test_nav_index_no_cap_denied(self):
        resp = _no_cap_client().get("/__nav-index.json")
        assert resp.status_code == 403

    def test_panel_fragment_no_cap_denied(self):
        # The grid.read gate runs before the panel is resolved, so a no-cap caller
        # is denied even for a well-formed URL — no panel-existence leak.
        resp = _no_cap_client().get(f"/panel/x--{__import__('uuid').uuid4()}/")
        assert resp.status_code == 403
