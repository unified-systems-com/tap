"""Tests for the manifest ``requires_tap`` compatibility floor (req-tap-plugin-extdev-compat-floor)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tap_plugins.manifest import PluginManifestError, load_manifest

_BASE = 'manifest_version = "0"\nplugin_version = "0.1.0"\nslug = "acme"\nname = "Acme"\n'


def _manifest(tmp_path: Path, body: str) -> Path:
    (tmp_path / "tap-plugin.toml").write_text(_BASE + body, encoding="utf-8")
    return tmp_path


def test_requires_tap_absent_is_none(tmp_path: Path) -> None:
    assert load_manifest(_manifest(tmp_path, "")).requires_tap is None


def test_requires_tap_valid_specifier_retained(tmp_path: Path) -> None:
    manifest = load_manifest(_manifest(tmp_path, 'requires_tap = ">=0.1,<0.2"\n'))
    assert manifest.requires_tap == ">=0.1,<0.2"


def test_requires_tap_malformed_specifier_raises(tmp_path: Path) -> None:
    with pytest.raises(PluginManifestError, match="invalid requires_tap"):
        load_manifest(_manifest(tmp_path, 'requires_tap = "not-a-range"\n'))


def test_requires_tap_empty_string_raises(tmp_path: Path) -> None:
    with pytest.raises(PluginManifestError, match="requires_tap.*non-empty string"):
        load_manifest(_manifest(tmp_path, 'requires_tap = ""\n'))


def test_requires_tap_non_string_raises(tmp_path: Path) -> None:
    with pytest.raises(PluginManifestError, match="requires_tap.*non-empty string"):
        load_manifest(_manifest(tmp_path, "requires_tap = 3\n"))
