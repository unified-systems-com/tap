"""Tests for the manifest ``[fips]`` declaration (req-tap-plugin-manifest-v0-fips / req-fips-crypto-bom).

The author's FACTUAL crypto posture — verified against the crypto-BOM scan by conformance, never a
self-granted exemption. ``uses-nonvalidated`` requires a justification, mirroring the operator waiver.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tap_plugins.manifest import PluginManifestError, load_manifest

_BASE = 'manifest_version = "0"\nplugin_version = "0.1.0"\nslug = "acme"\nname = "Acme"\n'


def _manifest(tmp_path: Path, body: str) -> Path:
    (tmp_path / "tap-plugin.toml").write_text(_BASE + body, encoding="utf-8")
    return tmp_path


def test_fips_absent_is_none(tmp_path: Path) -> None:
    assert load_manifest(_manifest(tmp_path, "")).fips is None


def test_fips_compatible(tmp_path: Path) -> None:
    fips = load_manifest(_manifest(tmp_path, '[fips]\nstatus = "compatible"\n')).fips
    assert fips is not None and fips.status == "compatible" and fips.reason is None and fips.providers == []


def test_fips_uses_nonvalidated_requires_reason(tmp_path: Path) -> None:
    with pytest.raises(PluginManifestError, match="fips.reason is required"):
        load_manifest(_manifest(tmp_path, '[fips]\nstatus = "uses-nonvalidated"\n'))
    with pytest.raises(PluginManifestError, match="fips.reason is required"):
        load_manifest(_manifest(tmp_path, '[fips]\nstatus = "uses-nonvalidated"\nreason = "   "\n'))


def test_fips_uses_nonvalidated_with_reason_and_providers(tmp_path: Path) -> None:
    body = '[fips]\nstatus = "uses-nonvalidated"\nreason = "libsodium for a non-security checksum"\nproviders = ["libsodium"]\n'
    fips = load_manifest(_manifest(tmp_path, body)).fips
    assert fips is not None
    assert fips.status == "uses-nonvalidated"
    assert fips.reason == "libsodium for a non-security checksum"
    assert fips.providers == ["libsodium"]


def test_fips_unknown_status_raises(tmp_path: Path) -> None:
    with pytest.raises(PluginManifestError, match="fips.status must be one of"):
        load_manifest(_manifest(tmp_path, '[fips]\nstatus = "sorta-maybe"\n'))


def test_fips_unknown_key_raises(tmp_path: Path) -> None:
    with pytest.raises(PluginManifestError, match="fips table has unknown keys"):
        load_manifest(_manifest(tmp_path, '[fips]\nstatus = "compatible"\nexempt = true\n'))


def test_fips_providers_must_be_string_list(tmp_path: Path) -> None:
    with pytest.raises(PluginManifestError, match="fips.providers must be a list"):
        load_manifest(_manifest(tmp_path, '[fips]\nstatus = "compatible"\nproviders = [3]\n'))


def test_fips_not_a_table_raises(tmp_path: Path) -> None:
    with pytest.raises(PluginManifestError, match="'fips' must be a table"):
        load_manifest(_manifest(tmp_path, 'fips = "compatible"\n'))
