"""Login-wall + /auth/ routing tests (increment 1 — req-tap-auth-app,
req-tap-auth-service-boundary).

The wall (`TapLoginRequiredMiddleware`) is a default-deny gate: every page
requires an authenticated session except the prefixes in
`TAP_LOGIN_EXEMPT_PREFIXES`, each of which carries its own enforcement. These
tests pin the coarse behavior the launch-ready "auth enforced" gate depends on.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse


@pytest.mark.django_db
class TestLoginWall:
    def test_anonymous_protected_page_redirects_to_login(self):
        """A non-exempt page (the landing root) redirects anonymous → login,
        fail-closed, with a ?next back-reference. LOGIN_URL is the native passkey
        login page (req-tap-auth-passkey-rollout-2), not allauth's account_login."""
        response = Client().get("/")
        assert response.status_code == 302
        assert response.url.startswith("/auth/passkey/login/")
        assert "next=/" in response.url

    @pytest.mark.smoke
    def test_login_page_itself_is_exempt(self):
        """The login route must be reachable anonymously (gating it would loop).

        Canary (`smoke`): renders the full base.html chrome for an ANONYMOUS
        caller. The chrome's breadcrumb context processor issues a guarded Page
        read on every response; if that read is not read-free for capability-less
        callers it trips the ORM read backstop and 500s the one page every
        unauthenticated user must reach (req-tap-auth-orm-read-backstop). Blast
        radius is maximal — a broken shared context processor breaks every page —
        so this sits on the trunk. Regression guard for the 2026-07-01 login
        outage (read backstop weaponized the breadcrumb Page read)."""
        response = Client().get("/auth/login/")
        assert response.status_code == 200

    def test_api_prefix_not_html_redirected(self):
        """/api/ is exempt from the HTML wall — anonymous API access is the API's
        own session_auth 401, never a 302 to a login page (which would corrupt a
        JSON client). The route is one that exists, so the 401 is the API's own answer
        and not a 404 standing in for it."""
        response = Client().get("/api/v1/entity-types/")
        assert response.status_code != 302
        assert response.status_code == 401

    def test_admin_prefix_uses_admin_login_not_auth_login(self):
        """/admin/ is exempt — Django admin handles its own staff login, so an
        anonymous hit redirects to the admin login, not /auth/login/."""
        response = Client().get("/admin/")
        assert response.status_code == 302
        assert response.url.startswith("/admin/login/")

    @pytest.mark.smoke
    def test_authenticated_user_passes_wall(self):
        """A logged-in grid.read holder clears the wall AND renders the landing.

        Canary (`smoke`): the authenticated counterpart to the anonymous login
        render — exercises the base.html chrome + landing view for a real
        grid-reading actor, so the enriched (authorized) breadcrumb read path is
        covered too, not only the read-free degraded path. The actor must hold
        `grid.read`: passing the wall proves a session exists, but the landing
        view gates on grid.read at the service boundary (req-tap-auth-policy), so
        a capability-less actor gets a clean 403, not the landing."""
        user = get_user_model().objects.create_user(username="wall-user", password="x")
        user.groups.add(Group.objects.get(name="tap_viewer"))
        client = Client()
        client.force_login(user)
        response = client.get("/")
        assert response.status_code == 200


@pytest.mark.django_db
class TestNoAccessPage:
    def test_no_access_renders_for_authenticated_user(self):
        client = Client()
        client.force_login(get_user_model().objects.create_user(username="capless", password="x"))
        response = client.get(reverse("no_access"))
        assert response.status_code == 200
        assert b"no access yet" in response.content

    def test_no_access_is_wall_exempt_under_auth_prefix(self):
        """/auth/no-access/ lives under the exempt /auth/ prefix, so it is not
        itself gated (it is the destination for an authenticated-but-capless
        actor)."""
        # Even anonymous, the wall does not redirect it (it is under /auth/).
        response = Client().get(reverse("no_access"))
        assert response.status_code == 200


def test_login_success_message_is_suppressed():
    """allauth's "Successfully signed in as …" flash is intentionally suppressed
    (an empty account/messages/logged_in.txt override) so the post-login grid
    reveal isn't covered by a banner. Guards against the override being removed
    (allauth's default would render non-empty). See req-web-render-flash."""
    from django.template.loader import render_to_string

    assert render_to_string("account/messages/logged_in.txt", {}).strip() == ""
