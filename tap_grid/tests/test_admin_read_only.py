"""Django admin is read-only for graph rows (req-tap-auth-policy-6, Issue# 957 - tap).

A graph row changes only through the write pipeline, which records its batch, provenance and
history. Admin still shows Entity, Edge, Batch and Layout rows, but cannot add, change or delete
them, and has no bulk actions: its "delete selected" action deleted a queryset below the write
guard and left no record.

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

from tap_auth.models import User
from tap_auth.roles import ADMIN_ROLE
from tap_grid.batch import create_batch
from tap_grid.models import Batch, Edge, Entity
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


#: (admin URL name stem, the model's unfiltered manager, a factory for one row of it)
CASES = [
    pytest.param("tap_grid_entity", Entity.objects, _entity, id="entity"),
    pytest.param("tap_grid_edge", Edge.all_objects, _edge, id="edge"),
    pytest.param("tap_grid_batch", Batch.all_objects, _batch, id="batch"),
    pytest.param("tap_viz_layout", Layout.all_objects, _layout, id="layout"),
]


@pytest.fixture
def admin_client() -> Client:
    """A superuser who also holds the TAP grants: is_superuser grants nothing at the TAP
    boundary (req-tap-auth-policy), and admin's changelists read graph rows through the ORM
    read backstop, which wants `grid.read`. So the strongest operator there is."""
    root = User.objects.create_superuser(username="admin-read-only", password="x")
    root.groups.add(Group.objects.get(name=ADMIN_ROLE))
    client = Client()
    client.force_login(root)
    return client


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
