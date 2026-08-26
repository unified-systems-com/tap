"""Tests for the manifest ``depends_on`` parser (req-tap-plugin-arch-dependencies-2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tap_plugins.manifest import DependencyEntry, PluginManifestError, load_manifest

_BASE = 'manifest_version = "0"\nplugin_version = "0.1.0"\nslug = "acme"\nname = "Acme"\n'


def _manifest(tmp_path: Path, body: str) -> Path:
    (tmp_path / "tap-plugin.toml").write_text(_BASE + body, encoding="utf-8")
    return tmp_path


def test_depends_on_absent_defaults_empty(tmp_path: Path) -> None:
    manifest = load_manifest(_manifest(tmp_path, ""))
    assert manifest.depends_on == []


def test_depends_on_parses_full_entry(tmp_path: Path) -> None:
    body = 'depends_on = [\n  { slug = "sigstore_core", min_version = "0.2.0", optional = true, note = "why" },\n]\n'
    manifest = load_manifest(_manifest(tmp_path, body))
    assert manifest.depends_on == [
        DependencyEntry(slug="sigstore_core", min_version="0.2.0", optional=True, note="why")
    ]


def test_depends_on_minimal_entry_defaults(tmp_path: Path) -> None:
    manifest = load_manifest(_manifest(tmp_path, 'depends_on = [{ slug = "roscale" }]\n'))
    assert manifest.depends_on == [DependencyEntry(slug="roscale", min_version=None, optional=False, note="")]


def test_depends_on_not_a_list_raises(tmp_path: Path) -> None:
    with pytest.raises(PluginManifestError, match="must be an array of tables"):
        load_manifest(_manifest(tmp_path, 'depends_on = "roscale"\n'))


def test_depends_on_missing_slug_raises(tmp_path: Path) -> None:
    with pytest.raises(PluginManifestError, match="non-empty string 'slug'"):
        load_manifest(_manifest(tmp_path, 'depends_on = [{ note = "no slug" }]\n'))


def test_depends_on_self_dependency_raises(tmp_path: Path) -> None:
    with pytest.raises(PluginManifestError, match="cannot depend on itself"):
        load_manifest(_manifest(tmp_path, 'depends_on = [{ slug = "acme" }]\n'))


def test_depends_on_duplicate_slug_raises(tmp_path: Path) -> None:
    body = 'depends_on = [{ slug = "roscale" }, { slug = "roscale" }]\n'
    with pytest.raises(PluginManifestError, match="duplicate depends_on slug"):
        load_manifest(_manifest(tmp_path, body))


def test_depends_on_unknown_key_raises(tmp_path: Path) -> None:
    with pytest.raises(PluginManifestError, match="unknown keys"):
        load_manifest(_manifest(tmp_path, 'depends_on = [{ slug = "roscale", version = "1" }]\n'))


def test_depends_on_bad_optional_type_raises(tmp_path: Path) -> None:
    with pytest.raises(PluginManifestError, match="optional must be a boolean"):
        load_manifest(_manifest(tmp_path, 'depends_on = [{ slug = "roscale", optional = "yes" }]\n'))
