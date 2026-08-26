"""The settings-free secrets-root lookup (req-tap-cares-secrets-root-resolution).

`resolve()` is the one canonical outside-Django read of TAP_SECRETS_ROOT: env or
None, no default — each settings-free caller owns its unset-policy. The
restatement scan lives in the `secrets-root-resolution` guard
(tap/guards/secrets_root_resolution.py, exercised via test_guards.py).
"""

from __future__ import annotations

from pathlib import Path

from tap.secrets_root import ENV_VAR, resolve
import pytest


@pytest.mark.spec("req-tap-cares-secrets-root-resolution-1")
def test_resolve_returns_path_when_set(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "/somewhere/secret-store")
    assert resolve() == Path("/somewhere/secret-store")


def test_resolve_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert resolve() is None


def test_resolve_returns_none_when_empty(monkeypatch):
    # An empty string is "unset" — matching settings.py's falsy handling of the
    # same variable, so the two canonical lookups agree on the degenerate case.
    monkeypatch.setenv(ENV_VAR, "")
    assert resolve() is None


@pytest.mark.spec("req-tap-cares-secrets-root-resolution-2")
def test_settings_projection_agrees_with_leaf(monkeypatch):
    # The two canonical lookups read the same env var: with the var set, the
    # Django projection (settings) and the settings-free leaf resolve
    # identically. Pins the two-lookup contract without coupling their code.
    from django.test import override_settings

    monkeypatch.setenv(ENV_VAR, "/agree/on/this")
    with override_settings(TAP_SECRETS_ROOT="/agree/on/this"):
        from django.conf import settings

        assert Path(settings.TAP_SECRETS_ROOT) == resolve()
