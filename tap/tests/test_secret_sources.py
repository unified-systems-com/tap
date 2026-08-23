"""Tests for the pluggable secret-source seam (spec-tap-plugin-dependency-resolution.md
req-tap-plugin-depres-sources / -trust) and its runtime_secrets dispatch.

These exercise the CORE seam with an in-process fake source — no cloud SDK, no install —
so they run in every lane. The AWS provider itself is tested in the aws_secrets_source
distribution; the end-to-end AWS path is exercised by the CodeBuild samsite lane.
"""

from __future__ import annotations

import importlib.metadata
import json
import types
from pathlib import Path

import pytest

from tap import secret_sources
from tap.runtime_secrets import RuntimeSecretError, resolve_secret_envelope
from tap.secret_naming import SECRET_SUFFIX
from tap.secret_sources import (
    DISK_SOURCE,
    SecretSourceError,
    _normalize_dist,
    register_source,
    resolve_sourced_data,
)


@pytest.fixture(autouse=True)
def _reset_registry():
    """Isolate the module-level source registry between tests."""
    secret_sources._reset_for_testing()
    yield
    secret_sources._reset_for_testing()


class _FakeSource:
    """An in-process source recording its calls and returning fixed data."""

    def __init__(self, name: str = "fake_source", data: dict[str, object] | None = None):
        self.name = name
        self._data = data if data is not None else {"token": "t", "host": "github.com"}
        self.calls: list[tuple[dict[str, object], str, str]] = []

    def fetch(self, ref, *, scope, key):
        self.calls.append((dict(ref), scope, key))
        return self._data


def _write_secret(
    root: Path, *, scope: str, key: str, kind: str, data: dict[str, object], metadata: dict[str, object] | None = None
) -> Path:
    payload = {"scope": scope, "key": key, "kind": kind, "description": "test secret", "data": data}
    if metadata is not None:
        payload["metadata"] = metadata
    path = root / f"{key}{SECRET_SUFFIX}"
    path.write_text(json.dumps(payload))
    return path


# --------------------------------------------------------------------------- #
# registry + dispatch
# --------------------------------------------------------------------------- #


def test_resolve_sourced_data_dispatches_to_registered_source():
    src = _FakeSource(data={"token": "abc"})
    register_source(src)
    out = resolve_sourced_data("fake_source", {"secret_id": "x"}, scope="tap_plugins.source", key="ghp")
    assert out == {"token": "abc"}
    assert src.calls == [({"secret_id": "x"}, "tap_plugins.source", "ghp")]


def test_unregistered_source_fails_loud():
    with pytest.raises(SecretSourceError, match="no such source is registered"):
        resolve_sourced_data("nope", {}, scope="s.x", key="k")


def test_duplicate_registration_raises():
    register_source(_FakeSource("dup"))
    with pytest.raises(SecretSourceError, match="already registered"):
        register_source(_FakeSource("dup"))


def test_reserved_disk_name_rejected():
    with pytest.raises(SecretSourceError, match="reserved"):
        register_source(_FakeSource(DISK_SOURCE))


def test_non_mapping_return_rejected():
    class _BadSource:
        name = "bad"

        def fetch(self, ref, *, scope, key):
            return ["not", "a", "mapping"]

    register_source(_BadSource())
    with pytest.raises(SecretSourceError, match="expected a JSON object"):
        resolve_sourced_data("bad", {}, scope="s.x", key="k")


def test_provider_exception_wrapped():
    class _BoomSource:
        name = "boom"

        def fetch(self, ref, *, scope, key):
            raise RuntimeError("network down")

    register_source(_BoomSource())
    with pytest.raises(SecretSourceError, match="failed to fetch.*network down"):
        resolve_sourced_data("boom", {}, scope="s.x", key="k")


# --------------------------------------------------------------------------- #
# trust allow-list (req-tap-plugin-depres-trust-2)
# --------------------------------------------------------------------------- #


def _fake_ep(name: str, dist_name: str, loader):
    return types.SimpleNamespace(name=name, dist=types.SimpleNamespace(name=dist_name), load=loader)


def test_discover_skips_non_allowlisted_distribution(monkeypatch):
    def _must_not_load():
        raise AssertionError("a non-allow-listed source entry point must never be loaded")

    good = _FakeSource("aws_secrets_manager")
    eps = [
        _fake_ep("evil", "evil-plugin", _must_not_load),
        _fake_ep("aws_secrets_manager", "aws-secrets-source", lambda: (lambda: good)),
    ]
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: eps if group == secret_sources.SECRET_SOURCES_ENTRY_POINT_GROUP else [],
    )

    # An allow-listed source resolves; the non-allow-listed one is absent (never loaded).
    out = resolve_sourced_data("aws_secrets_manager", {"secret_id": "x"}, scope="s.x", key="k")
    assert out is good._data
    with pytest.raises(SecretSourceError, match="no such source is registered"):
        resolve_sourced_data("evil", {}, scope="s.x", key="k")


@pytest.mark.parametrize(
    "raw,expected",
    [("aws_secrets_source", "aws-secrets-source"), ("AWS.Secrets_Source", "aws-secrets-source"), (None, None)],
)
def test_normalize_dist(raw, expected):
    assert _normalize_dist(raw) == expected


# --------------------------------------------------------------------------- #
# runtime_secrets integration — the seam consumers get for free
# --------------------------------------------------------------------------- #


def test_disk_secret_unchanged(tmp_path):
    """No metadata.source ⇒ inline data (disk source), behavior unchanged."""
    _write_secret(tmp_path, scope="tap_plugins.source", key="ghp", kind="github_pat", data={"token": "inline"})
    env = resolve_secret_envelope(tmp_path, "tap_plugins.source", "ghp")
    assert env.data == {"token": "inline"}


def test_sourced_secret_resolves_through_provider(tmp_path):
    register_source(_FakeSource(data={"token": "from-store", "host": "github.com"}))
    _write_secret(
        tmp_path,
        scope="tap_plugins.source",
        key="ghp",
        kind="github_pat",
        data={},  # value lives in the store, not on disk
        metadata={"source": "fake_source", "source_ref": {"secret_id": "tap-ci/ghp"}},
    )
    env = resolve_secret_envelope(tmp_path, "tap_plugins.source", "ghp")
    assert env.data == {"token": "from-store", "host": "github.com"}


def test_explicit_disk_source_is_inline(tmp_path):
    _write_secret(
        tmp_path,
        scope="tap_plugins.source",
        key="ghp",
        kind="github_pat",
        data={"token": "inline"},
        metadata={"source": "disk"},
    )
    env = resolve_secret_envelope(tmp_path, "tap_plugins.source", "ghp")
    assert env.data == {"token": "inline"}


def test_sourced_secret_unregistered_source_raises(tmp_path):
    _write_secret(
        tmp_path,
        scope="tap_plugins.source",
        key="ghp",
        kind="github_pat",
        data={},
        metadata={"source": "not_installed", "source_ref": {"secret_id": "x"}},
    )
    with pytest.raises(RuntimeSecretError, match="no such source is registered"):
        resolve_secret_envelope(tmp_path, "tap_plugins.source", "ghp")


def test_malformed_source_field_rejected_at_parse(tmp_path):
    _write_secret(
        tmp_path,
        scope="tap_plugins.source",
        key="ghp",
        kind="github_pat",
        data={},
        metadata={"source": 123},
    )
    with pytest.raises(RuntimeSecretError, match="metadata.source must be a non-empty string"):
        resolve_secret_envelope(tmp_path, "tap_plugins.source", "ghp")


def test_malformed_source_ref_rejected_at_parse(tmp_path):
    _write_secret(
        tmp_path,
        scope="tap_plugins.source",
        key="ghp",
        kind="github_pat",
        data={},
        metadata={"source": "fake_source", "source_ref": "not-a-dict"},
    )
    with pytest.raises(RuntimeSecretError, match="metadata.source_ref must be a JSON object"):
        resolve_secret_envelope(tmp_path, "tap_plugins.source", "ghp")
