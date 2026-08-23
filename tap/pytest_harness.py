"""The TAP test harness as a real pytest plugin (req-tap-test-fixtures).

These fixtures used to live in the repo-root ``conftest.py``. They moved here —
a real pytest plugin, loaded via ``-p tap.pytest_harness`` in the configfile's
``addopts`` — because conftest loading is a function of HOW pytest was invoked,
and these fixtures are load-bearing for every DB test in core and in every plugin:

    2026-08-09: pytest 9.1 stopped loading the rootdir conftest chain for
    ``--pyargs``-resolved packages. Every ``pytest --pyargs tap_plugin.<slug>``
    run — the exact invocation plugin-ci.yml lane 2 uses, and the documented
    completion check for evicted plugins — silently lost `default_caller_context`,
    so every DB test in every plugin suite failed at the service boundary with
    ``MissingActor`` while the same files passed by path. The ``addopts`` carrier
    is provably invocation-independent here: it rides ``[tool.pytest.ini_options]``,
    the same configfile block that delivers ``DJANGO_SETTINGS_MODULE`` to those
    very ``--pyargs`` runs. (A ``pytest11`` entry point would be the textbook
    mechanism, but the root project is a virtual — non-installed — uv project,
    so it has no distribution to register entry points from.) The harness must
    not be one pytest release note away from vanishing.

What the harness provides (unchanged in behavior from the conftest era):

* ``django_db_setup`` (session) — extends pytest-django's fixture to run the
  idempotent auth bootstrap (``sync_auth``) once per session, so the ``tap_test``
  program actor + capabilities + groups exist as committed baseline data.
* ``default_caller_context`` (autouse) — binds a ``CallerContext`` per test:
  DB tests run as ``tap_test`` (a ``tap_admin`` member holding every capability,
  satisfying the on-by-default service-boundary enforcement, req-tap-auth-policy);
  non-DB tests get a ``None``-actor context (they never cross the boundary).
  Transactional tests that flushed the baseline are self-healed by re-running
  ``sync_auth``.
* ``_service_write_hatch`` (autouse) — wraps each test in ``unguarded_write()``
  so direct-ORM test setup is sanctioned below-service writing
  (req-tap-auth-write-batch-routing); ``@pytest.mark.enforce_write_guard``
  opts a test out to exercise the guard itself.

Import discipline: this module is imported at pytest STARTUP, before pytest-django
configures Django settings — so nothing Django-backed may be imported at module
level. ``tap_grid.caller_context`` is safe (pure contextvars); everything else
stays lazy inside the fixtures.

Tests that deliberately verify no-actor / unauthorized behavior set the context
themselves (e.g. ``set_caller_context(None)`` or an unprivileged actor).

Invocation-independence is guarded by ``tap/tests/test_pytest_harness_invocation.py``
(req-tap-test-fixtures-4): a subprocess ``--pyargs`` run must see these fixtures,
and the probe proves it can detect their absence.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractUser

from tap_grid.caller_context import CallerContext, set_caller_context


@contextlib.contextmanager
def batch_ctx(source: str = "test") -> Iterator[str]:
    """Create a Batch entity and bind a batch-carrying CallerContext for the duration.

    The one home of the write-a-batch-then-scope-the-context test idiom (formerly
    copied as ``_batch_ctx`` in five test modules). Yields the batch's entity id;
    restores the prior context on exit. Imports stay lazy per the module discipline
    above (this is called inside test bodies, never at collection time).
    """
    from tap_grid.batch import create_batch
    from tap_grid.caller_context import get_caller_context

    batch = create_batch(source=source)
    batch_id = str(batch.entity.id)
    prev = get_caller_context()
    set_caller_context(CallerContext(user=prev.user if prev is not None else None, batch_id=batch_id))
    try:
        yield batch_id
    finally:
        set_caller_context(prev)


@contextlib.contextmanager
def isolated_registry(*registries: Any) -> Iterator[None]:
    """Snapshot, reset, and restore ``tap.registry``-style registries around a test.

    The one home of the save/`_reset_for_testing()`/restore idiom (formerly copied
    in ~12 per-file fixtures). Accepts any object with the ``all()`` /
    ``_reset_for_testing(data=None)`` pair; app conftests wrap it in a named
    fixture for their own registry.
    """
    saved = [registry.all() for registry in registries]
    for registry in registries:
        registry._reset_for_testing()
    try:
        yield
    finally:
        for registry, snapshot in zip(registries, saved, strict=True):
            registry._reset_for_testing(snapshot)


def make_admin_user(username: str = "test-admin") -> AbstractUser:
    """Create a fresh human user in the ``tap_admin`` group (session auth seed).

    The one home of the make-an-authorized-admin test idiom: create_user + join
    the admin group whose grants satisfy the on-by-default service-boundary
    enforcement (req-tap-auth-service-boundary).
    """
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group

    from tap_auth.roles import ADMIN_ROLE

    user = get_user_model().objects.create_user(username=username, password="x")
    user.groups.add(Group.objects.get(name=ADMIN_ROLE))
    return user


def make_admin_client(username: str = "test-admin") -> Any:
    """A Django test ``Client`` force-logged-in as a fresh tap_admin member.

    Formerly copied as ``_admin_client`` in four tap_web test modules; tap_api's
    ``logged_in_client`` fixture derives its user from :func:`make_admin_user` too.
    """
    from django.test import Client

    client = Client()
    client.force_login(make_admin_user(username))  # type: ignore[arg-type]  # AbstractUser vs concrete User (django-stubs)
    return client


def _tap_test_key() -> str:
    """The built-in test-actor key — tap_auth.sync is its one definition.

    Imported lazily: tap/ must not import a tap_* app at module scope, and this
    harness only needs the key inside a fixture body.
    """
    from tap_auth.sync import ACTOR_TEST

    return ACTOR_TEST


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup: object, django_db_blocker: Any) -> None:  # noqa: PT004
    """Seed the auth bootstrap once per session.

    Runs after pytest-django creates+migrates the test DB. The committed
    capabilities/groups/built-in actors become the baseline every test inherits.
    (If plugin registration order ever lets pytest-django's own fixture win the
    name, `_resolve_test_actor` below still self-heals — the seeding here is the
    fast path, not the only path.)
    """
    with django_db_blocker.unblock():
        from tap_auth.sync import sync_auth

        sync_auth()


def _db_fixture_name(request: pytest.FixtureRequest) -> str | None:
    """Return the db fixture this test uses ('db'/'transactional_db'), or None.

    Returning the specific name lets the autouse context fixture `getfixturevalue`
    it — which both enables DB access and orders this fixture *after* the db
    fixture, avoiding "Database access not allowed".
    """
    if "transactional_db" in request.fixturenames:
        return "transactional_db"
    if "db" in request.fixturenames:
        return "db"
    marker = request.node.get_closest_marker("django_db")
    if marker is not None:
        return "transactional_db" if marker.kwargs.get("transaction") else "db"
    return None


def _resolve_test_actor() -> AbstractUser:
    """Return the tap_test actor, re-running the idempotent sync if a
    transactional test flushed the seeded baseline."""
    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    actor = user_model.objects.filter(tap_builtin_key=_tap_test_key()).first()
    if actor is None:
        from tap_auth.sync import sync_auth

        sync_auth()
        actor = user_model.objects.get(tap_builtin_key=_tap_test_key())
    return actor


@pytest.fixture(autouse=True)
def default_caller_context(request: pytest.FixtureRequest) -> Iterator[CallerContext]:
    """Bind a CallerContext for the duration of each test.

    DB tests run as the `tap_test` actor — a `tap_admin` member that *holds* every
    capability — so the on-by-default service-boundary enforcement is satisfied
    without per-test boilerplate: the stateless backstop re-checks what the actor
    holds (req-tap-auth-policy-8), and tap_test holds it, so there is nothing to
    pre-authorize. Non-DB tests get a `None`-actor context (they do not reach the
    service boundary). A fresh batch_id is generated per test so writes stay
    isolated.
    """
    db_fixture = _db_fixture_name(request)
    if db_fixture is None:
        ctx = CallerContext(user=None, batch_id=str(uuid.uuid7()))
        set_caller_context(ctx)
        yield ctx
        set_caller_context(None)
        return

    # Enable DB access and order this fixture after the db fixture before querying.
    request.getfixturevalue(db_fixture)

    actor = _resolve_test_actor()
    ctx = CallerContext(user=actor, batch_id=str(uuid.uuid7()))
    set_caller_context(ctx)
    try:
        yield ctx
    finally:
        set_caller_context(None)


@pytest.fixture(autouse=True)
def _service_write_hatch(request: pytest.FixtureRequest) -> Iterator[None]:
    """Permit direct-ORM model setup in tests (req-tap-auth-write-batch-routing).

    The write backstop fails a node/edge write that does not route through the
    service layer. Tests are the sanctioned below-service write zone (like
    migrations): a great deal of test setup legitimately does direct
    `.objects.create()` / `.save()` (including intentional model-level tests). So
    each test runs inside `unguarded_write()` by default — prod enforces the guard,
    and the static lint carries authoring-time detection of direct writes in app
    code. A test that needs to exercise the guard itself opts out with
    `@pytest.mark.enforce_write_guard`.
    """
    from tap_grid.write_guard import unguarded_write

    if request.node.get_closest_marker("enforce_write_guard"):
        yield
        return
    with unguarded_write():
        yield
