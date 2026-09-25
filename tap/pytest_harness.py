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
* ``pytest_collection_modifyitems`` — the baseline fixture-vocabulary gate
  (req-dev-validation-baseline-vocabulary): fails a core-test run once, loudly, when
  this stack lacks the vocabulary those tests are written against, instead of letting
  it surface as ~30 unexplained collection errors.
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
from pathlib import Path
from types import FrameType
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


HARNESS_LABEL_AUDIT: pytest.StashKey[_HarnessLabelAudit] = pytest.StashKey()
"""Where a test can reach its own audit (the audit's self-test does)."""


def _default_batch_label(request: pytest.FixtureRequest) -> dict[str, str]:
    """The name and description a test's minted batch carries (see default_caller_context)."""
    node_id = request.node.nodeid
    return {
        "batch_name": f"pytest: {node_id}",
        "batch_description": f"Writes made by the test {node_id}.",
    }


def pytest_configure(config: pytest.Config) -> None:
    """Register the harness's own marker, so plugin repos running this harness need not."""
    config.addinivalue_line(
        "markers",
        "no_default_batch_label: run without the harness's default batch label, to exercise "
        "req-grid-service-batch-label-required itself",
    )


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

    The context also carries the test's batch label: a service write that mints
    a batch must say what the change is (req-grid-service-batch-label-required),
    and a test's writes are "this test's writes", named by its node id. So no
    test call needs its own `batch_name`. A test of the rule itself opts out with
    ``@pytest.mark.no_default_batch_label`` and gets an unlabelled context.
    """
    labelled = request.node.get_closest_marker("no_default_batch_label") is None
    label = _default_batch_label(request) if labelled else {}
    db_fixture = _db_fixture_name(request)
    if db_fixture is None:
        ctx = CallerContext(user=None, batch_id=str(uuid.uuid7()), **label)
        set_caller_context(ctx)
        yield ctx
        set_caller_context(None)
        return

    # Enable DB access and order this fixture after the db fixture before querying.
    request.getfixturevalue(db_fixture)

    actor = _resolve_test_actor()
    ctx = CallerContext(user=actor, batch_id=str(uuid.uuid7()), **label)
    set_caller_context(ctx)
    audit = _HarnessLabelAudit(request, ctx) if labelled else None
    if audit is not None:
        request.node.stash[HARNESS_LABEL_AUDIT] = audit
    try:
        if audit is None:
            yield ctx
        else:
            with audit.installed():
                yield ctx
    finally:
        set_caller_context(None)
    if audit is not None and audit.violations:
        pytest.fail(audit.report(), pytrace=False)


class _HarnessLabelAudit:
    """Keep the harness's batch scope from standing in for a production caller's.

    `default_caller_context` binds each test a batch id and a batch label, so a test's
    own service writes need neither (req-grid-service-batch-label-required). The cost is
    that a PRODUCTION caller exercised by a test inherits them too: it would join the
    test's batch, or mint it under the test's label, and pass — while in production,
    where nothing binds either, the same call mints an unlabelled batch and is refused.

    So every write that would rely on the harness scope is traced to its caller: the
    first stack frame outside the service layer. When that frame is production code
    (not a test module, not the harness), the test fails naming the file and line.
    A write is relying on the harness scope when the name OR the description it would
    mint under is the harness's (each judged on its own, so supplying one and inheriting
    the other is still caught), and it either lands in the harness batch or mints a new one — a
    write joining a batch its own code opened is exempt here as it is in production.

    Nothing is listed by name. The service layer's modules are read off the service
    functions themselves; "production" is any module under this pytest rootdir that
    is not a test module and not under an ``--ignore``d path, so each repository
    audits its own code (a plugin's code is audited by the plugin's own test run).
    """

    def __init__(self, request: pytest.FixtureRequest, ctx: CallerContext) -> None:
        self.label = ctx.batch_name
        self.description = ctx.batch_description
        self.batch_id = ctx.batch_id
        self.rootpath = Path(str(request.config.rootpath)).resolve()
        ignored = request.config.getoption("ignore") or []
        self.ignored = [(self.rootpath / str(p)).resolve() for p in ignored]
        self.violations: list[str] = []

    @contextlib.contextmanager
    def installed(self) -> Iterator[None]:
        import tap_grid.services as services
        from tap_auth import enforcement
        from tap_grid import write_guard

        original = getattr(services, "_ensure_batch")  # noqa: B009 — module-private seam, read not imported
        self.service_modules = {
            services.__name__,
            original.__module__,
            enforcement.__name__,
            write_guard.__name__,
            __name__,
            "contextlib",
            "functools",
        }

        def audited(batch_id: str, user: Any, *, name: str, description: str) -> None:
            # Name and description are judged independently: a production write that
            # supplies one and inherits the other from the harness still relies on it.
            if (name and name == self.label) or (description and description == self.description):
                self._check(batch_id)
            original(batch_id, user, name=name, description=description)

        setattr(services, "_ensure_batch", audited)  # noqa: B010 — swap the seam write_batch calls
        try:
            yield
        finally:
            setattr(services, "_ensure_batch", original)  # noqa: B010

    def _check(self, batch_id: str) -> None:
        import sys

        from tap_grid.models import Batch

        if batch_id != self.batch_id and Batch.objects.filter(entity_id=batch_id).exists():
            return  # joins a batch its own code opened: exempt, as in production
        frame: FrameType | None = sys._getframe(2)
        while frame is not None and frame.f_globals.get("__name__", "") in self.service_modules:
            frame = frame.f_back
        if frame is None:
            return
        path = Path(frame.f_code.co_filename).resolve()
        if self.is_production(path):
            self.violations.append(f"{path.relative_to(self.rootpath)}:{frame.f_lineno} ({frame.f_code.co_name})")

    def is_production(self, path: Path) -> bool:
        if not path.is_relative_to(self.rootpath) or "site-packages" in path.parts:
            return False
        if any(path.is_relative_to(p) for p in self.ignored):
            return False
        rel = path.relative_to(self.rootpath)
        name = rel.name
        is_test = "tests" in rel.parts or name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"
        return not is_test

    def report(self) -> str:
        sites = "\n  ".join(sorted(set(self.violations)))
        return (
            "production code wrote through the service layer relying on the test harness's batch scope "
            "(req-grid-service-batch-label-required): in production nothing binds that scope, so this "
            f"write would mint an unlabelled batch and be refused. Label it at the call site:\n  {sites}"
        )


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


# =============================================================================
# Baseline fixture-vocabulary gate (req-dev-validation-baseline-vocabulary)
# =============================================================================

#: Repo root — ``tap/pytest_harness.py`` → ``tap/`` → here. Core is a virtual (non-installed)
#: uv project, so this module always sits in the checkout; an installed plugin's tests never do.
_REPO_ROOT = Path(__file__).resolve().parent.parent

#: Checkouts of OTHER repositories that happen to live under the root: editable plugin
#: workspaces (``spawn --dev-plugins``) and the in-repo plugin dirs. Tests under these are
#: plugin tests, not core tests, even though their paths are inside the worktree.
_NON_CORE_SUBTREES = ("plugins", "_dev-plugins")


def _is_core_test(item: pytest.Item) -> bool:
    """True when *item* is a CORE-located test — one this repo's own suite owns.

    Path-based rather than name-based: a plugin's tests ride inside its package, so they
    resolve either into site-packages (a wheel install) or into one of the in-worktree
    plugin subtrees (an editable install). Everything else under the root is core.
    """
    path = getattr(item, "path", None)
    if path is None:
        return False
    try:
        relative = Path(path).resolve().relative_to(_REPO_ROOT)
    except ValueError:
        return False  # outside the worktree entirely — an installed plugin's tests
    return relative.parts[:1] not in {(sub,) for sub in _NON_CORE_SUBTREES}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Fail once, actionably, when core tests are collected without the baseline vocabulary.

    TAP-IMPLEMENTS: req-dev-validation-baseline-vocabulary@b7151874485b/8c5743afe69d (enforcement) — the
    single point where a missing baseline stops a core run; nothing else may downgrade it to a skip.

    Core-located tests import ``tap_plugin.<slug>`` models and assert on ``<slug>__*``
    entity types (``tap.plugin_testing.BASELINE_PLUGIN_SLUGS``). On a stack whose boot
    profile does not install them — ``core``, or any product profile without its ``_dev``
    counterpart — those files raise ImportError at collection, ~30 of them, none of which
    names the actual cause or the fix.

    Two dispositions were available and only one is honest. ``requires_plugins`` would
    skip them, which is right for an OPTIONAL plugin (local validates what is installed;
    the all-plugins lane owns full-set truth) and wrong here: the grid spine would report
    green having exercised nothing, and that green feeds the promote gate. So this fails.

    Scoped to runs that actually collect core tests, so ``pytest --pyargs tap_plugin.<slug>``
    (plugin-ci lane 2, whose profile has no reason to carry core's fixture vocabulary) is
    unaffected.
    """
    from tap.plugin_testing import installed_plugin_slugs, missing_baseline_plugins

    missing = missing_baseline_plugins()
    if not missing or not any(_is_core_test(item) for item in items):
        return
    raise pytest.UsageError(
        f"core test run is missing its baseline fixture vocabulary: {', '.join(missing)}. "
        f"Core-located tests build fixtures from these plugins' node/edge types, so this "
        f"stack cannot exercise the grid spine. Boot a profile that installs them "
        f"(`core_dev` for core; a product line's `_dev` profile for that line) and re-run. "
        f"Installed here: {', '.join(installed_plugin_slugs()) or '(none)'}."
    )
