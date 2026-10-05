"""Django admin is read-only for graph rows, and shows them only to `grid.read` (req-tap-auth-policy-6).

A graph row changes only through the write pipeline, which records its batch, provenance and
history. Admin still shows Entity, Edge, Batch, Layout and EntityType rows, but cannot add, change
or delete them, and has no bulk actions: its "delete selected" action deleted a queryset below the
write guard and left no record (Issue# 957 - tap). The EntityType catalog comes from plugin
declarations at boot, so nothing legitimate edits it in admin either.

Reading those rows needs `grid.read`, superuser or not (req-tap-auth-policy-5). Admin asks TAP's
policy before it reads, so an actor without `grid.read` gets a 403, not the read backstop's
500 (Issue# 961 - tap).

These tests keep the harness's write hatch open, so nothing but the admin's own permissions stands
between a POST and the row: a refusal seen here is the admin refusing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse

from tap_auth import policy
from tap_auth.capabilities import READ_CAPABILITY, WRITE_CAPABILITY
from tap_auth.models import User
from tap_auth.roles import ADMIN_ROLE
from tap_auth.sync import GROUP_VIEWER
from tap_grid.batch import create_batch
from tap_grid.caller_context import CallerContext
from tap_grid.models import Batch, BatchEvent, BatchEventType, Edge, Entity, EntityType
from tap_grid.services import create_edge, create_node
from tap_grid.tests.support import make_spine_entity
from tap_viz.models import Layout

pytestmark = [pytest.mark.django_db, pytest.mark.spec("req-tap-auth-policy-6")]


def _entity() -> Any:
    return make_spine_entity("grid_fixtures__unconstrained", name="admin-entity")


def _edge() -> Any:
    a = make_spine_entity("grid_fixtures__unconstrained", name="admin-edge-from")
    b = make_spine_entity("grid_fixtures__unconstrained", name="admin-edge-to")
    return create_edge(a, b, "ADMIN_READ_ONLY")


def _batch() -> Any:
    return create_batch(name="admin-batch", source="test:admin")


def _layout() -> Any:
    made = create_node("layout", {"name": "admin-layout"})
    assert made.success, made.errors
    return Layout.objects.get(entity_id=made.entity_id)


def _entity_type() -> Any:
    """One catalog row, written the way the plugin loader declares it at boot (`tap_grid/apps.py`):
    the test database does not carry the boot-declared catalog."""
    row, _ = EntityType.objects.update_or_create(slug="admin_entity_type", defaults={"name": "Admin entity type"})
    return row


def _batch_event() -> Any:
    batch = _batch()
    return BatchEvent.objects.create(
        batch=batch,
        event_type=BatchEventType.CREATE,
        entity_id=batch.entity_id,
        entity_type="batch",
        model_name="Batch",
    )


#: (admin URL name stem, the model's unfiltered manager, a factory for one row of it)
CASES = [
    pytest.param("tap_grid_entity", Entity.objects, _entity, id="entity"),
    pytest.param("tap_grid_edge", Edge.all_objects, _edge, id="edge"),
    pytest.param("tap_grid_batch", Batch.all_objects, _batch, id="batch"),
    pytest.param("tap_viz_layout", Layout.all_objects, _layout, id="layout"),
    pytest.param("tap_grid_entitytype", EntityType.objects, _entity_type, id="entity_type"),
]

#: Every admin that reads graph rows. BatchEvent is not a graph row, but its changelist joins Batch.
GATED = [*CASES, pytest.param("tap_grid_batchevent", BatchEvent.objects, _batch_event, id="batch_event")]


def _client_for(user: User, **client_kwargs: Any) -> Client:
    client = Client(**client_kwargs)
    client.force_login(user)
    return client


@pytest.fixture
def admin_client() -> Client:
    """A superuser who also holds the TAP grants: is_superuser grants nothing at the TAP
    boundary (req-tap-auth-policy), and admin's changelists read graph rows through the ORM
    read backstop, which wants `grid.read`. So the strongest operator there is."""
    root = User.objects.create_superuser(username="admin-read-only", password="x")
    root.groups.add(Group.objects.get(name=ADMIN_ROLE))
    return _client_for(root)


@pytest.fixture
def no_grant_client() -> Client:
    """A superuser in no group: Django admin lets it in, and TAP grants it nothing.

    The client hands back the response a server would send instead of re-raising, so a crash
    reads as a 500 rather than as a refusal or an exception.
    """
    root = User.objects.create_superuser(username="admin-no-grants", password="x")
    assert not policy.can(CallerContext(user=root), READ_CAPABILITY)
    return _client_for(root, raise_request_exception=False)


@pytest.fixture
def viewer_client() -> Client:
    """A superuser holding `grid.read` and nothing else, through the read-only viewer role."""
    root = User.objects.create_superuser(username="admin-viewer", password="x")
    root.groups.add(Group.objects.get(name=GROUP_VIEWER))
    ctx = CallerContext(user=root)
    assert policy.can(ctx, READ_CAPABILITY)
    assert not policy.can(ctx, WRITE_CAPABILITY)
    return _client_for(root)


@pytest.mark.parametrize(("stem", "manager", "make"), CASES)
def test_the_changelist_still_shows_the_rows(
    admin_client: Client, stem: str, manager: Any, make: Callable[[], Any]
) -> None:
    """Positive control: viewing still works, so the refusals below are about writing."""
    make()
    assert admin_client.get(reverse(f"admin:{stem}_changelist")).status_code == 200


@pytest.mark.parametrize(("stem", "manager", "make"), CASES)
def test_the_add_view_is_refused(admin_client: Client, stem: str, manager: Any, make: Callable[[], Any]) -> None:
    assert admin_client.get(reverse(f"admin:{stem}_add")).status_code == 403


@pytest.mark.parametrize(("stem", "manager", "make"), CASES)
def test_delete_selected_deletes_nothing(
    admin_client: Client, stem: str, manager: Any, make: Callable[[], Any]
) -> None:
    """The bulk action, confirmed (`post=yes`), as the admin's own form would send it."""
    row = make()
    response = admin_client.post(
        reverse(f"admin:{stem}_changelist"),
        {"action": "delete_selected", "_selected_action": [str(row.pk)], "index": "0", "post": "yes"},
    )
    assert response.status_code < 500
    assert manager.filter(pk=row.pk).exists()


@pytest.mark.parametrize(("stem", "manager", "make"), GATED)
def test_the_changelist_refuses_an_actor_without_grid_read(
    no_grant_client: Client, stem: str, manager: Any, make: Callable[[], Any]
) -> None:
    make()
    assert no_grant_client.get(reverse(f"admin:{stem}_changelist")).status_code == 403


@pytest.mark.parametrize(("stem", "manager", "make"), CASES)
def test_the_change_view_refuses_an_actor_without_grid_read(
    no_grant_client: Client, stem: str, manager: Any, make: Callable[[], Any]
) -> None:
    """Django fetches the object before it asks whether the actor may view it, so this page
    is refused by the read authorization in `get_queryset`, not by the view permission."""
    row = make()
    assert no_grant_client.get(reverse(f"admin:{stem}_change", args=[row.pk])).status_code == 403


def test_batch_history_refuses_an_actor_without_grid_read(no_grant_client: Client) -> None:
    batch = _batch()
    assert no_grant_client.get(reverse("admin:tap_grid_batch_history", args=[batch.pk])).status_code == 403


def _gated_changelist_urls() -> list[str]:
    return [reverse(f"admin:{case.values[0]}_changelist") for case in GATED]


def test_the_index_links_none_of_them_for_an_actor_without_grid_read(no_grant_client: Client) -> None:
    response = no_grant_client.get(reverse("admin:index"))
    assert response.status_code == 200
    body = response.content.decode()
    assert [url for url in _gated_changelist_urls() if url in body] == []


def test_the_index_links_all_of_them_for_an_actor_with_grid_read(viewer_client: Client) -> None:
    """Positive control for the test above: the links are there to be missing."""
    body = viewer_client.get(reverse("admin:index")).content.decode()
    assert [url for url in _gated_changelist_urls() if url not in body] == []


@pytest.mark.parametrize(("stem", "manager", "make"), GATED)
def test_grid_read_alone_opens_the_changelist(
    viewer_client: Client, stem: str, manager: Any, make: Callable[[], Any]
) -> None:
    """The refusal keys on `grid.read`, not on membership of tap_admin."""
    make()
    assert viewer_client.get(reverse(f"admin:{stem}_changelist")).status_code == 200


@pytest.mark.parametrize(("stem", "manager", "make"), CASES)
def test_grid_read_alone_opens_the_change_view(
    viewer_client: Client, stem: str, manager: Any, make: Callable[[], Any]
) -> None:
    """Positive control for the change-view refusal: the row's page exists and opens."""
    row = make()
    assert viewer_client.get(reverse(f"admin:{stem}_change", args=[row.pk])).status_code == 200
