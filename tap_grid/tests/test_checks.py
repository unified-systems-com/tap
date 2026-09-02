"""tap_grid.E001 refuses the dev-default search-readonly password outside DEBUG.

req-grid-search-readonly-role.sec. `tap_boot.orchestrator` provisions the Postgres
role with `settings.SEARCH_READONLY_PASSWORD` on every boot, so a deployment that
never sets `TAP_SEARCH_READONLY_PASSWORD` would stand up a live database login
whose password is a literal in a public repository.

The check is an `Error`, not a `Warning`, on purpose: every management command
aborts, including `manage.py boot`, whose grid-infra phase is what actually
provisions the role. A warning would scroll past in boot output, which is exactly
how the value would reach production.
"""

from django.conf import settings
from django.test import override_settings

from tap_grid.checks import check_search_readonly_password_is_not_the_dev_default as _check

DEV_DEFAULT = settings.DEV_DEFAULT_SEARCH_READONLY_PASSWORD
REAL_SECRET = "a-generated-deployment-secret"


def _ids() -> list[str | None]:
    return [e.id for e in _check(None)]


@override_settings(DEBUG=False, SEARCH_READONLY_PASSWORD=DEV_DEFAULT)
def test_errors_when_deployed_with_the_dev_default() -> None:
    """The case this exists for: DEBUG off, nobody set the env var."""
    assert _ids() == ["tap_grid.E001"]


@override_settings(DEBUG=False, SEARCH_READONLY_PASSWORD=REAL_SECRET)
def test_silent_when_a_real_secret_is_configured() -> None:
    """Positive control: a correctly configured deployment must boot.

    Without this, a check that errored unconditionally would satisfy the test
    above while making TAP unbootable."""
    assert _ids() == []


@override_settings(DEBUG=False, SEARCH_READONLY_PASSWORD="")
def test_errors_when_the_password_is_explicitly_empty() -> None:
    """Empty is not "not the default".

    `TAP_SEARCH_READONLY_PASSWORD=""` satisfies a bare inequality against the dev
    default while provisioning the role with NO password — strictly worse than the
    published one. The first version of this check tested only inequality and let
    this through; it was caught in review, not by these tests, which is why the case
    is pinned explicitly rather than folded into the default test.
    """
    assert _ids() == ["tap_grid.E002"]


@override_settings(DEBUG=True, SEARCH_READONLY_PASSWORD="")
def test_empty_password_is_still_silent_under_debug() -> None:
    """The DEBUG carve-out applies to both refusals, not just the default one."""
    assert _ids() == []


@override_settings(DEBUG=True, SEARCH_READONLY_PASSWORD=DEV_DEFAULT)
def test_silent_under_debug() -> None:
    """`docker compose up` works out of the box; that convenience is deliberate."""
    assert _ids() == []


@override_settings(DEBUG=False, SEARCH_READONLY_PASSWORD=DEV_DEFAULT)
def test_the_error_is_fail_closed_not_advisory() -> None:
    """Django aborts management commands on Error and continues on Warning, so the
    severity IS the control here — a Warning would let `manage.py boot` reach its
    grid-infra phase and provision the role with the published password, merely
    mentioning it on the way past."""
    from django.core.checks import Error

    errors = _check(None)
    assert len(errors) == 1
    assert isinstance(errors[0], Error)


def test_the_guard_compares_against_the_settings_constant() -> None:
    """The check must read the same constant settings.py defaults to, not a copy.

    A re-typed literal here would drift the day the default changes, and the guard
    would silently stop guarding — the exact failure this whole class of finding
    keeps taking."""
    import inspect

    import tap_grid.checks as mod

    source = inspect.getsource(mod)
    assert "settings.DEV_DEFAULT_SEARCH_READONLY_PASSWORD" in source
    assert DEV_DEFAULT not in source, "the dev default is re-typed here instead of referenced"


def test_the_check_is_registered_with_django() -> None:
    """Registration is what makes it run; the function alone guards nothing."""
    from django.core.checks import registry

    assert any(c is _check for c in registry.registry.get_checks())
