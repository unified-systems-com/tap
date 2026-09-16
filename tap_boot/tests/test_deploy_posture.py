"""The deploy posture gate: it runs everywhere, and a correct deployment passes it.

Before 2026-09-16 neither was true (tap#272). The gate sat behind `profile.has_auth`,
so it ran for one of five shipped profiles; and two of the five settings it demanded
were assigned nowhere, so the one profile that reached it could never pass.

The load-bearing test here is `test_a_correctly_configured_deployment_passes`. The old
suite only ever asserted that the gate FAILS — which is how a gate that could never
pass looked healthy for months.

Spec: `specs/spec-tap-serving.md` req-tap-serving-debug-scope, req-tap-serving-proxy.
"""

from __future__ import annotations

import pytest
from django.core.management.utils import get_random_secret_key

from tap_boot.posture import FATAL_DEPLOY_CHECKS, DeployPostureError, check_deploy_posture


def _noop(_message: str) -> None:
    return None


# Generated, never a literal. Django ships the function an operator would actually
# use, so the fixture is the real thing rather than a plausible-looking string — and
# the test then proves the gate accepts ANY adequate key, not one magic value.
#
# The first draft hardcoded a 51-character random-looking string. Codacy's secrets
# engine flagged it, correctly: `*_SECRET* = "<literal>"` is exactly the shape of a
# leaked credential, and a detector that stayed quiet about it would be no use on the
# day the literal were real. An earlier draft was also 40 characters and the gate
# refused it — a "realistic-looking" secret is not automatically an acceptable one.
def _deployable(settings, *, secret_key: str | None = None) -> None:
    """Everything a correct deployment sets. Individual tests spoil one thing."""
    settings.DEPLOY_POSTURE_ENFORCED = True
    settings.DEBUG = False
    settings.SECRET_KEY = get_random_secret_key() if secret_key is None else secret_key
    settings.ALLOWED_HOSTS = ["tap.example.com"]
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_COOKIE_SECURE = True


class TestTheGatePasses:
    def test_a_correctly_configured_deployment_passes(self, settings) -> None:
        """The regression guard #272 asked for, and the one the old suite lacked.

        Without it, a gate that always raised would satisfy every negative assertion
        below while making deploy boots impossible — which is exactly what happened.
        """
        _deployable(settings)
        check_deploy_posture(_noop)

    def test_unenforced_boot_is_not_applicable_rather_than_passing(self, settings) -> None:
        """A dev boot is a third state, and it says so out loud.

        Silence would be indistinguishable from "the posture was checked and was
        fine" — absence of evidence rendered as evidence of absence.
        """
        settings.DEPLOY_POSTURE_ENFORCED = False
        said: list[str] = []
        check_deploy_posture(said.append)
        assert any("not applicable" in line for line in said), said


class TestTheGateFails:
    def test_shipped_dev_secret_is_refused(self, settings) -> None:
        from django.conf import settings as django_settings

        _deployable(settings, secret_key=django_settings.DEV_DEFAULT_SECRET_KEY)
        with pytest.raises(DeployPostureError, match="SECRET_KEY"):
            check_deploy_posture(_noop)

    def test_an_empty_secret_is_django_s_to_refuse_not_ours(self, settings) -> None:
        """Documents where the guarantee lives, so nobody re-adds a dead branch.

        The gate originally also tested `not SECRET_KEY`. That could never fire:
        Django raises on first access, below us. Asserting the real behaviour keeps
        the knowledge without keeping an unreachable guard.
        """
        from django.core.exceptions import ImproperlyConfigured

        _deployable(settings)
        with pytest.raises(ImproperlyConfigured, match="SECRET_KEY"):
            settings.SECRET_KEY = ""
            check_deploy_posture(_noop)

    def test_insecure_session_cookie_is_refused(self, settings) -> None:
        """Sourced from Django's own W010 rather than a hand-rolled assertion."""
        _deployable(settings)
        settings.SESSION_COOKIE_SECURE = False
        with pytest.raises(DeployPostureError, match="W012"):
            check_deploy_posture(_noop)

    def test_insecure_csrf_cookie_is_refused(self, settings) -> None:
        _deployable(settings)
        settings.CSRF_COOKIE_SECURE = False
        with pytest.raises(DeployPostureError, match="W016"):
            check_deploy_posture(_noop)

    def test_empty_allowed_hosts_is_refused(self, settings) -> None:
        _deployable(settings)
        settings.ALLOWED_HOSTS = []
        with pytest.raises(DeployPostureError, match="W020"):
            check_deploy_posture(_noop)


class TestThePromotedSetIsDeliberate:
    def test_unpromoted_deploy_warnings_do_not_abort(self, settings) -> None:
        """A deploy warning outside the promoted set is advisory, not fatal.

        This is what keeps the gate passable: promoting "every Django warning" would
        make it unsatisfiable again the first time the framework adds a check — the
        same defect this module was written to remove, reintroduced by its fix. A
        correct deployment does not set HSTS or SSL-redirect (both meaningful only
        behind a terminating proxy), so those warnings are raised here and must not
        abort.
        """
        _deployable(settings)
        said: list[str] = []
        check_deploy_posture(said.append)  # must not raise
        assert any("advisory" in line for line in said), said

    def test_the_promoted_set_is_named_not_derived_from_severity(self) -> None:
        """The fatal list is an explicit enumeration, so widening it is an edit."""
        assert FATAL_DEPLOY_CHECKS == frozenset(
            {"security.W009", "security.W012", "security.W016", "security.W018", "security.W020"}
        )

    def test_the_dev_secret_check_reads_the_constant_not_a_copy(self) -> None:
        """Re-typing the literal would leave the gate comparing against a string that
        no longer existed — still passing, no longer guarding."""
        import inspect

        from django.conf import settings as django_settings

        import tap_boot.posture as mod

        source = inspect.getsource(mod)
        assert "settings.DEV_DEFAULT_SECRET_KEY" in source
        assert django_settings.DEV_DEFAULT_SECRET_KEY not in source
