"""Configuration that is unsafe when defaulted has no default.

`req-tap-serving-fail-closed`. Three values used to be wrong-but-present in an artifact
an operator started without configuring anything: `DEBUG` defaulted true, `SECRET_KEY`
fell back to a literal published in this repository, and `DATABASE_URL` fell back to a
working `tap:tap` credential pair. Each passed every check that asks whether the value is
CONFIGURED, which is the presence-is-not-correctness shape this codebase keeps finding.

WHAT THESE TESTS OBSERVE, AND WHAT THEY DO NOT. They re-import `tap/settings.py` under a
spoiled environment and assert it refuses — the refusal itself, executed, not a source
grep. What they cannot observe is the container-level half of the done-test: an image
started with nothing set exiting non-zero and naming the missing configuration. That
needs a container, which this suite does not have, so it is **NOT OBSERVED** here and is
recorded as such in `specs/spec-tap-serving.md` rather than implied by a green test.

The compose assertions at the bottom exist because the development stack is what supplies
these values to every dev session, every CI lane and this suite itself: deleting one of
those lines would break all of them at once, and before this module nothing failed in a
way that named the cause.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http.request import validate_host

_COMPOSE = Path(settings.BASE_DIR) / "docker-compose.yml"


def _reload_settings(env: dict[str, str | None]) -> Any:
    """Re-import `tap/settings.py` with `env` applied; a value of None UNSETS the key.

    `mock.patch.dict` is additive, so the ambient container environment survives — which
    is the point: these tests spoil exactly one variable and leave everything else as a
    real boot would have it.
    """
    import tap.settings as tap_settings

    patched = {k: v for k, v in env.items() if v is not None}
    removed = [k for k, v in env.items() if v is None]
    with mock.patch.dict(os.environ, patched):
        for key in removed:
            os.environ.pop(key, None)
        return importlib.reload(tap_settings)


def _restore_settings() -> None:
    import tap.settings as tap_settings

    importlib.reload(tap_settings)


class TestDebugDefaultsFalse:
    @pytest.mark.spec("req-tap-serving-fail-closed-2")
    def test_debug_is_off_when_nothing_sets_it(self) -> None:
        """Development opts IN; a deployment does not have to remember to opt out."""
        try:
            assert _reload_settings({"DEBUG": None}).DEBUG is False
        finally:
            _restore_settings()

    @pytest.mark.spec("req-tap-serving-fail-closed-2")
    def test_development_can_still_opt_in(self) -> None:
        """Positive control: the default above is a default, not a hardcoded False."""
        try:
            assert _reload_settings({"DEBUG": "true"}).DEBUG is True
        finally:
            _restore_settings()

    @pytest.mark.spec("req-tap-serving-fail-closed-2")
    def test_a_typo_is_refused_rather_than_guessed(self) -> None:
        """One boolean parser, and it refuses what it does not recognise.

        `DEBUG` is parsed by the same `_env_flag` as the cookie-transport flags rather
        than by a second `in ("true", "1", "yes")` — which is the derive-a-fact-once rule
        applied to a set of accepted spellings. `DEBUG=flase` would have silently meant
        False here (the safe direction, by luck), and the identical shape one flag over
        meant `TAP_SESSION_COOKIE_SECURE=flase` served cookies in plaintext.
        """
        try:
            with pytest.raises(ImproperlyConfigured, match="DEBUG"):
                _reload_settings({"DEBUG": "flase"})
        finally:
            _restore_settings()


class TestTheArtifactRefusesToStartUnconfigured:
    @pytest.mark.spec("req-tap-serving-fail-closed-1")
    def test_no_secret_key_is_refused_by_name(self) -> None:
        try:
            with pytest.raises(ImproperlyConfigured, match="SECRET_KEY"):
                _reload_settings({"SECRET_KEY": None})
        finally:
            _restore_settings()

    @pytest.mark.spec("req-tap-serving-fail-closed-1")
    def test_a_blank_secret_key_is_refused_too(self) -> None:
        """Blank is not "not the default" — it is a third way to be unconfigured."""
        try:
            with pytest.raises(ImproperlyConfigured, match="SECRET_KEY"):
                _reload_settings({"SECRET_KEY": "   "})
        finally:
            _restore_settings()

    @pytest.mark.spec("req-tap-serving-fail-closed-1")
    def test_no_database_url_is_refused_by_name(self) -> None:
        """A shipped username and password is a working default for an attacker too."""
        try:
            with pytest.raises(ImproperlyConfigured, match="DATABASE_URL"):
                _reload_settings({"DATABASE_URL": None})
        finally:
            _restore_settings()

    @pytest.mark.spec("req-tap-serving-fail-closed-1")
    def test_the_refusals_are_not_a_settings_module_that_always_raises(self) -> None:
        """Positive control. Without it, a settings module broken in some unrelated way
        would satisfy every refusal above while making the product unstartable."""
        try:
            reloaded = _reload_settings({})
            assert reloaded.SECRET_KEY
            assert reloaded.DATABASES["default"]["NAME"]
        finally:
            _restore_settings()


class TestAllowedHostsOnceEnforced:
    """`ALLOWED_HOSTS` is what Django validates the Host header against — in both modes.

    The widely-believed version, written into this epic's first draft and corrected by
    review, is that `DEBUG=True` disables host validation. It does not. Django validates
    either way; what `DEBUG=True` changes is that an EMPTY list falls back to a permissive
    development default. So flipping the `DEBUG` default does not switch enforcement on —
    it only removes that fallback, and this list is what has been enforcing all along.
    """

    @pytest.mark.spec("req-tap-serving-fail-closed-5")
    def test_labeled_session_urls_are_accepted(self) -> None:
        """The multi-session browser-disambiguation URLs, host by host.

        `req-dev-multisession-browser-disambiguation`: every developer reaches their own
        stack at `<label>.tap.localhost:<port>` so browser tabs are telling apart. A
        deployment-shaped `ALLOWED_HOSTS` that dropped `.localhost` would break every
        session at once, which is the specific regression this asserts against.
        """
        hosts = settings.ALLOWED_HOSTS
        for host in ("localhost", "127.0.0.1", "demo-dev.tap.localhost", "cli.tap.localhost"):
            assert validate_host(host, hosts), f"{host} is not accepted by ALLOWED_HOSTS={hosts}"

    @pytest.mark.spec("req-tap-serving-fail-closed-5")
    def test_a_foreign_host_is_not_accepted(self) -> None:
        """The negative control that makes the test above mean something."""
        assert not validate_host("tap.example.com", settings.ALLOWED_HOSTS)
        assert not validate_host("localhost.evil.example", settings.ALLOWED_HOSTS)

    @pytest.mark.spec("req-tap-serving-fail-closed-5")
    def test_a_deployment_inheriting_this_list_answers_nothing_rather_than_everything(self) -> None:
        """Which is why the dev default is safe to keep as the default.

        A deployment that never sets `ALLOWED_HOSTS` inherits development hostnames and
        rejects its own with a 400 — loud and closed. The dangerous shapes are the empty
        list and the wildcard, and the deploy-posture gate refuses both
        (`tap_boot/posture.py`), so this default is the third state and not a hole.
        """
        assert "*" not in settings.ALLOWED_HOSTS
        assert [h for h in settings.ALLOWED_HOSTS if h.strip()]


class TestTheDevelopmentStackDeclaresItsOwnValues:
    """docker-compose.yml is the development stack, and now the ONLY place these live.

    Before this module nothing asserted the compose file declares them. Deleting a line
    would have been caught by every lane falling over at boot, in a way that named
    neither the file nor the reason — the worst kind of red.
    """

    @staticmethod
    def _compose_env() -> dict[str, str]:
        """The `web`/`db` environment entries, as `KEY: value` text lines.

        Parsed by text rather than by a YAML library so the test has no dependency the
        rest of the suite does not already carry; the assertions below are about which
        keys are declared, which is a question the text answers honestly.
        """
        declared: dict[str, str] = {}
        for line in _COMPOSE.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or ":" not in stripped:
                continue
            key, _, value = stripped.partition(":")
            if key.isupper() or key.startswith("POSTGRES_"):
                declared[key] = value.strip().strip('"')
        return declared

    @pytest.mark.spec("req-tap-serving-fail-closed-1")
    def test_the_dev_stack_supplies_every_value_the_application_now_requires(self) -> None:
        declared = self._compose_env()
        for key in ("SECRET_KEY", "DATABASE_URL", "DEBUG", "POSTGRES_PASSWORD"):
            assert key in declared, f"docker-compose.yml no longer declares {key}"

    @pytest.mark.spec("req-tap-serving-fail-closed-2")
    def test_development_opts_into_debug_rather_than_hardcoding_it(self) -> None:
        """`${DEBUG:-true}`, so a developer can rehearse the deployment posture locally
        with `DEBUG=false scripts/dc up -d` instead of editing a checked-in file."""
        assert self._compose_env()["DEBUG"].startswith("${DEBUG:-")

    @pytest.mark.spec("req-tap-serving-fail-closed-3")
    def test_the_dev_secret_the_stack_declares_is_the_one_the_gate_refuses(self) -> None:
        """The literal is still here — and that is the point of keeping it named.

        Removing the application's fallback closed the inherit-it-by-configuring-nothing
        path. The copy-this-file path stays open by construction (a fresh clone has to
        run), so it is closed by refusal instead: the deploy-posture gate compares the
        configured key against `settings.DEV_STACK_SECRET_KEY`. This asserts the two
        halves still name the same value — a refusal of a string nothing sets would be a
        gate that exists and does nothing.
        """
        assert settings.DEV_STACK_SECRET_KEY in self._compose_env()["SECRET_KEY"]

    @pytest.mark.spec("req-tap-serving-fail-closed-3")
    def test_the_dev_database_password_is_the_one_the_gate_refuses(self) -> None:
        declared = self._compose_env()
        assert declared["POSTGRES_PASSWORD"].startswith(f"${{POSTGRES_PASSWORD:-{settings.DEV_STACK_DB_PASSWORD}}}")
        assert f":${{POSTGRES_PASSWORD:-{settings.DEV_STACK_DB_PASSWORD}}}@" in declared["DATABASE_URL"]
