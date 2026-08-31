"""Read-only routes answer 405, not 200, to a write verb (SonarCloud python:S3752).

A Django view with no method decorator accepts EVERY verb, so a POST to a page
route was silently served as though it were a GET. CsrfViewMiddleware rejects the
cross-site case with a 403 before the view runs, which is why this stayed
invisible — but a same-origin POST from a stray form, a script or an agent got a
rendered page instead of `405 Method Not Allowed`.

These tests assert the DECORATOR'S EFFECT, not its presence: a decorator is exactly
the kind of line a later refactor drops without anyone noticing, and grepping for
`@require_GET` would pass on a view whose decorator had been reordered under one
that swallows it.

THE CLIENT MUST BE AUTHENTICATED. The login wall answers an anonymous request with
a 302 to the login page BEFORE the view is reached, so an anonymous version of
these tests passes whether or not the decorator exists — it measures the wall.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db

READ_ONLY_ROUTES = [
    pytest.param("/", id="landing"),
    pytest.param("/auth/no-access/", id="no-access"),
    pytest.param("/object/search/thing--0198c7d0-0000-7000-8000-000000000000/", id="object-view"),
]

WRITE_VERBS = ["post", "put", "patch", "delete"]


@pytest.fixture
def user_client() -> Client:
    """Past the login wall, so the request actually reaches the view."""
    user_model = get_user_model()
    user = user_model.objects.create_superuser("methodcheck", "m@example.com", "x" * 20)
    client = Client(SERVER_NAME="localhost")
    client.force_login(user)
    return client


@pytest.mark.parametrize("route", READ_ONLY_ROUTES)
@pytest.mark.parametrize("verb", WRITE_VERBS)
def test_read_only_route_rejects_write_verbs(user_client: Client, route: str, verb: str) -> None:
    assert getattr(user_client, verb)(route).status_code == 405


@pytest.mark.parametrize("route", READ_ONLY_ROUTES)
def test_the_same_routes_still_serve_get(user_client: Client, route: str) -> None:
    """Positive control: without it, deleting the routes would satisfy every 405
    assertion above."""
    assert user_client.get(route).status_code != 405


def test_nav_index_allows_head_as_well_as_get(user_client: Client) -> None:
    """GET+HEAD on purpose. This is the machine-readable affordance
    (req-web-nav-index-endpoint), probed by monitors and agents, and Django's
    `require_GET` answers HEAD with 405 — so a tidy-up to `require_GET` for
    consistency with its neighbours would break exactly the callers it exists for."""
    url = reverse("nav-index")
    assert user_client.head(url).status_code != 405
    assert user_client.get(url).status_code != 405
    assert user_client.post(url).status_code == 405


def test_editors_still_accept_post(user_client: Client) -> None:
    """Positive control for the other direction: blanket-decorating every view with
    `require_GET` would satisfy every assertion above while breaking the editors."""
    response = user_client.post("/panel/x--0198c7d0-0000-7000-8000-000000000000/edit/")
    assert response.status_code != 405
