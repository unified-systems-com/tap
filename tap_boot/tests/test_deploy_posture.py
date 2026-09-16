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

    def test_wildcard_allowed_hosts_is_refused(self, settings) -> None:
        """The defence Django does not provide, and that review caught me dropping.

        The hand-rolled gate refused `"*" in hosts`. Django's `security.W020` fires only
        on an EMPTY list — verified on the pinned Django: with `ALLOWED_HOSTS = ["*"]`
        the checks that fire are W004, W008 and tap_grid.E001, and W020 is not among
        them. So sourcing findings from Django alone silently removed a Host-header
        defence while looking equivalent. `ALLOWED_HOSTS=*` is one character away on the
        documented env path, which splits on commas.
        """
        _deployable(settings)
        settings.ALLOWED_HOSTS = ["*"]
        with pytest.raises(DeployPostureError, match=r"\*"):
            check_deploy_posture(_noop)

    def test_wildcard_among_real_hosts_is_still_refused(self, settings) -> None:
        """A wildcard beside legitimate entries still admits any Host."""
        _deployable(settings)
        settings.ALLOWED_HOSTS = ["tap.example.com", "*"]
        with pytest.raises(DeployPostureError, match=r"\*"):
            check_deploy_posture(_noop)

    def test_blank_only_allowed_hosts_is_refused(self, settings) -> None:
        """`ALLOWED_HOSTS=` yields `[""]`, which Django's W020 accepts.

        `bool([""])` is true, so the emptiness check does not fire. The deleted gate
        filtered blanks before testing, and the replacement did not — a third case where
        derive-from-Django dropped something the hand-rolled version encoded. Not a
        bypass (Django rejects real Host values against `[""]` at request time), but a
        false declaration: the gate would report OK for an instance that serves no host.
        """
        _deployable(settings)
        settings.ALLOWED_HOSTS = [""]
        with pytest.raises(DeployPostureError, match="no host"):
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


class TestEnforcementCannotBeSwitchedOff:
    """The gate must not carry its own escape hatch — a hatch in the hull.

    An earlier draft read `_env_flag("TAP_DEPLOY_POSTURE_ENFORCED", not DEBUG)`, which
    made `DEBUG=false` + `TAP_DEPLOY_POSTURE_ENFORCED=false` a production-shaped boot
    with every posture check skipped. That bypass did not exist before the change, since
    the old gate keyed on `DEBUG` alone.
    """

    @staticmethod
    def _reload(env: dict[str, str]):
        import importlib
        import os
        from unittest import mock

        import tap.settings as tap_settings

        with mock.patch.dict(os.environ, env):
            return importlib.reload(tap_settings)

    def test_a_production_shaped_boot_cannot_opt_out(self) -> None:
        import importlib

        import tap.settings as tap_settings

        try:
            reloaded = self._reload({"DEBUG": "false", "TAP_DEPLOY_POSTURE_ENFORCED": "false"})
            assert reloaded.DEPLOY_POSTURE_ENFORCED is True, "enforcement must not be disableable"
        finally:
            importlib.reload(tap_settings)

    def test_a_dev_box_can_opt_in(self) -> None:
        """The useful direction still works: force enforcement on to prove the gate passes."""
        import importlib

        import tap.settings as tap_settings

        try:
            reloaded = self._reload({"DEBUG": "true", "TAP_DEPLOY_POSTURE_ENFORCED": "true"})
            assert reloaded.DEPLOY_POSTURE_ENFORCED is True
        finally:
            importlib.reload(tap_settings)

    def test_a_typo_raises_rather_than_failing_open(self) -> None:
        """`flase` must not read as "off". A security flag that fails open on a typo is
        worse than an absent one: the configuration reads as set."""
        import importlib

        from django.core.exceptions import ImproperlyConfigured

        import tap.settings as tap_settings

        try:
            with pytest.raises(ImproperlyConfigured, match="TAP_DEPLOY_POSTURE_ENFORCED"):
                self._reload({"DEBUG": "true", "TAP_DEPLOY_POSTURE_ENFORCED": "flase"})
        finally:
            importlib.reload(tap_settings)

    def test_a_typo_in_a_cookie_flag_also_raises(self) -> None:
        import importlib

        from django.core.exceptions import ImproperlyConfigured

        import tap.settings as tap_settings

        try:
            with pytest.raises(ImproperlyConfigured, match="TAP_SESSION_COOKIE_SECURE"):
                self._reload({"TAP_SESSION_COOKIE_SECURE": "flase"})
        finally:
            importlib.reload(tap_settings)


class TestTheTrustedProxyDeclarationFailsClosed:
    """A malformed trust declaration must refuse to load, not load permissively.

    `SECURE_PROXY_SSL_HEADER` decides whose claim of "this request arrived over HTTPS"
    is believed. The first draft tested the value before stripping and never tested the
    header name, so `'HTTP_X_FORWARDED_PROTO, '` parsed to `(..., "")` — and a request
    arriving with an empty forwarded header would then compare equal to the configured
    secure value, letting any client assert HTTPS.
    """

    @staticmethod
    def _reload_with(value: str):
        import importlib
        import os
        from unittest import mock

        import tap.settings as tap_settings

        with mock.patch.dict(os.environ, {"TAP_SECURE_PROXY_SSL_HEADER": value}):
            return importlib.reload(tap_settings)

    @pytest.mark.parametrize(
        "value",
        [
            "HTTP_X_FORWARDED_PROTO, ",  # empty value after trimming
            ",https",                     # empty header name
            " , ",                        # both blank
            "HTTP_X_FORWARDED_PROTO",     # no separator at all
        ],
    )
    def test_malformed_declarations_are_refused(self, value: str) -> None:
        import importlib

        from django.core.exceptions import ImproperlyConfigured

        import tap.settings as tap_settings

        try:
            with pytest.raises(ImproperlyConfigured, match="TAP_SECURE_PROXY_SSL_HEADER"):
                self._reload_with(value)
        finally:
            importlib.reload(tap_settings)

    def test_a_well_formed_declaration_loads(self) -> None:
        """Positive control: the refusals above must not be a parser that always raises."""
        import importlib

        import tap.settings as tap_settings

        try:
            reloaded = self._reload_with("HTTP_X_FORWARDED_PROTO,https")
            assert reloaded.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
        finally:
            importlib.reload(tap_settings)

    def test_unset_means_trust_nobody(self) -> None:
        import importlib

        import tap.settings as tap_settings

        try:
            reloaded = self._reload_with("")
            assert reloaded.SECURE_PROXY_SSL_HEADER is None
        finally:
            importlib.reload(tap_settings)
