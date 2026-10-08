"""Proof of the ORM read backstop (req-tap-auth-orm-read-backstop).

The three findings in the 2026-06-30 codex-security scan were all the same class:
a read entrypoint reached TAP-managed rows via the Django ORM without holding
`grid.read`. These tests pin the structural guard that makes that class fail
closed, so a future forgotten gate cannot silently leak rows.

The predicate is capability-based (matches the write/search backstops): a read is
allowed iff the active actor holds `grid.read`, with two sanctioned exemptions —
the `unguarded_read()` escape hatch and the context-less infrastructure zone
(migrations / shell / commands, where no CallerContext is bound).

Layer 1 is `BaseModelQuerySet._fetch_all` (materialization: .get/.first/list).
Layer 2 is the SQL execute_wrapper (covers .count/.exists and non-BaseModel
catalog tables like EntityType, which Layer 1 cannot see).
"""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

from tap_auth import capabilities as caps
from tap_auth.errors import UnguardedOperation
from tap_auth.models import Capability, User
from tap_grid.caller_context import CallerContext, set_caller_context
from tap_grid.models import Edge, Entity, EntityType, Search
from tap_grid.read_guard import unguarded_read

pytestmark = pytest.mark.django_db


def _admin_ctx() -> CallerContext:
    user = User.objects.create_user(username="rg-admin", password="x")
    user.groups.add(Group.objects.get(name="tap_admin"))
    return CallerContext(user=user)


def _viewer_ctx() -> CallerContext:
    """An actor holding exactly grid.read (the tap_viewer profile)."""
    group = Group.objects.create(name="rg-viewer-grp")
    content_type = ContentType.objects.get_for_model(Capability)
    group.permissions.add(
        Permission.objects.get(content_type=content_type, codename=caps.codename_for(caps.READ_CAPABILITY))
    )
    user = User.objects.create_user(username="rg-viewer", password="x")
    user.groups.add(group)
    return CallerContext(user=user)


def _no_caps_ctx() -> CallerContext:
    return CallerContext(user=User.objects.create_user(username="rg-nocap", password="x"))


# ---------------------------------------------------------------------------
# Layer 1 — BaseModelQuerySet._fetch_all (materialization)
# ---------------------------------------------------------------------------


def test_layer1_nocap_read_fails_closed():
    """A capability-less actor materializing a TAP-managed queryset fails closed.

    This is the finding class: a web/API read entrypoint that reached the ORM
    without authorizing grid.read. Fires even on an empty table — the guard runs
    before the query, so it does not depend on there being rows to leak.
    """
    ctx = _no_caps_ctx()
    set_caller_context(ctx)
    with pytest.raises(UnguardedOperation, match="unguarded read"):
        list(Search.objects.all())
    with pytest.raises(UnguardedOperation, match="unguarded read"):
        Search.objects.first()


def test_layer1_read_capability_holder_passes():
    """An actor holding grid.read reads normally (viewer and admin)."""
    for ctx in (_viewer_ctx(), _admin_ctx()):
        set_caller_context(ctx)
        # Does not raise; empty result is fine.
        assert list(Search.objects.all()) == []
        assert Search.objects.first() is None


def test_layer1_no_context_is_infra_zone():
    """No bound CallerContext (migrations / shell / commands) is exempt."""
    set_caller_context(None)
    assert list(Search.objects.all()) == []


def test_layer1_unguarded_read_hatch_bypasses():
    """`unguarded_read()` suspends the guard for sanctioned direct-ORM readers."""
    set_caller_context(_no_caps_ctx())
    with unguarded_read():
        assert list(Search.objects.all()) == []
    # Guard is restored on exit.
    with pytest.raises(UnguardedOperation):
        list(Search.objects.all())


# ---------------------------------------------------------------------------
# Layer 2 — SQL execute_wrapper (count/exists + non-BaseModel catalog)
# ---------------------------------------------------------------------------


def test_layer2_nocap_count_and_exists_fail_closed():
    """.count()/.exists() bypass _fetch_all but the SQL wrapper still gates them."""
    set_caller_context(_no_caps_ctx())
    with pytest.raises(UnguardedOperation, match="unguarded read"):
        Search.objects.count()
    with pytest.raises(UnguardedOperation, match="unguarded read"):
        Search.objects.exists()


def test_layer2_nocap_entitytype_catalog_fails_closed():
    """EntityType (finding 3) is not a BaseModel, so only Layer 2 covers it."""
    set_caller_context(_no_caps_ctx())
    with pytest.raises(UnguardedOperation, match="unguarded read"):
        list(EntityType.objects.all())


def test_layer2_capability_holder_reads_catalog():
    """A grid.read holder reads the type catalog normally."""
    set_caller_context(_viewer_ctx())
    # The 'search' EntityType is seeded at app ready(); at minimum this executes.
    assert EntityType.objects.filter(slug="search").exists() in (True, False)


# ---------------------------------------------------------------------------
# The spine and the history tables (Issue# 963 - tap)
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-tap-auth-orm-read-backstop")
def test_a_spine_read_without_grid_read_fails_closed():
    """The Entity spine is guarded like the rows it backs: names, types and dimensions.

    Its exemption rested on an Entity API that carried its own gate; that API was
    removed in Issue# 957 - tap.
    """
    set_caller_context(_no_caps_ctx())
    with pytest.raises(UnguardedOperation, match="unguarded read"):
        list(Entity.objects.all())
    with pytest.raises(UnguardedOperation, match="unguarded read"):
        Entity.objects.values_list("name", flat=True).first()
    with pytest.raises(UnguardedOperation, match="unguarded read"):
        Entity.objects.count()
    # An empty pk__in filter sends no SQL, so only Layer 1 (the queryset) can see it.
    with pytest.raises(UnguardedOperation, match="unguarded read"):
        list(Entity.objects.filter(pk__in=[]))


@pytest.mark.spec("req-tap-auth-orm-read-backstop")
def test_a_history_read_without_grid_read_fails_closed():
    """A graph row's history is graph data: Model.history is gated like Model.objects."""
    set_caller_context(_no_caps_ctx())
    with pytest.raises(UnguardedOperation, match="unguarded read"):
        list(Search.history.all())
    with pytest.raises(UnguardedOperation, match="unguarded read"):
        Edge.history.count()


@pytest.mark.spec("req-tap-auth-orm-read-backstop")
def test_a_grid_read_holder_reads_the_spine_and_history():
    set_caller_context(_viewer_ctx())
    assert isinstance(list(Entity.objects.all()[:1]), list)
    assert Search.history.count() >= 0
