"""Per-stack cookie names, and the CSRF token scripts read instead of the cookie (tap#773).

Browsers scope cookies by host, not port, so dev stacks sharing `localhost` must not share
cookie names. Scripts can no longer find the CSRF cookie by a fixed name, so base.html carries
the token in a meta tag.
"""

from __future__ import annotations

import re

import pytest
from django.conf import settings

from tap.pytest_harness import make_admin_client
from tap.settings import per_stack_cookie_names


class TestCookieNames:
    def test_unlabelled_stack_keeps_django_defaults(self) -> None:
        assert per_stack_cookie_names("") == ("sessionid", "csrftoken")

    def test_labelled_stack_suffixes_both(self) -> None:
        assert per_stack_cookie_names("highbar") == ("sessionid_highbar", "csrftoken_highbar")

    def test_label_is_made_cookie_safe(self) -> None:
        session, csrf = per_stack_cookie_names("a b/c;d")
        assert re.fullmatch(r"sessionid_a_b_c_d-[0-9a-f]{8}", session)
        assert re.fullmatch(r"csrftoken_a_b_c_d-[0-9a-f]{8}", csrf)

    def test_cleaning_never_collides_distinct_labels(self) -> None:
        """Labels that clean to the same form still get distinct cookies."""
        names = {per_stack_cookie_names(label)[0] for label in ("foo/bar", "foo bar", "foo;bar", "foo_bar")}
        assert len(names) == 4

    def test_spawn_shaped_labels_are_unchanged(self) -> None:
        """spawn-session.sh mints ^[a-z][a-z0-9_-]*$: those names carry no digest."""
        assert per_stack_cookie_names("gsdt-2") == ("sessionid_gsdt-2", "csrftoken_gsdt-2")

    def test_two_labels_never_share_a_name(self) -> None:
        assert per_stack_cookie_names("gsdt")[0] != per_stack_cookie_names("highbar")[0]

    def test_settings_follow_the_running_label(self) -> None:
        assert (settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME) == per_stack_cookie_names(
            settings.TAP_SESSION_LABEL
        )


@pytest.mark.django_db
def test_base_template_carries_the_csrf_token(settings) -> None:
    """Every page on base.html exposes the token where the tap_viz runtime reads it."""
    settings.TAP_WEB_LANDING = None  # render the placeholder, not a redirect to the stack's landing
    response = make_admin_client(username="cookie-admin").get("/")
    match = re.search(r'<meta name="csrf-token" content="([^"]+)">', response.content.decode())
    assert match, "base.html lost <meta name=\"csrf-token\">"
    assert len(match.group(1)) >= 32
