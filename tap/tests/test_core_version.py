"""Unit tests for tap.core_version — the shared compatibility-floor helper.

Covers req-tap-plugin-extdev-compat-floor: core-version resolution (installed metadata
with a pyproject fallback) and the requires_tap satisfy/reject logic.
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

import pytest

from tap import core_version


def test_parse_requires_tap_valid() -> None:
    spec = core_version.parse_requires_tap(">=0.1,<0.2")
    assert str(spec)  # a real SpecifierSet


def test_parse_requires_tap_malformed_raises() -> None:
    with pytest.raises(ValueError, match="invalid requires_tap"):
        core_version.parse_requires_tap("not-a-specifier", source="plugins/x")


@pytest.mark.parametrize(
    ("requires_tap", "core", "expected"),
    [
        (">=0.1,<0.2", "0.1.0", True),
        (">=0.1,<0.2", "0.2.0", False),
        (">=0.5", "0.1.0", False),
        (">=0.1", "0.1.0", True),
        # prereleases=True does real work: a prerelease core strictly inside the range
        # is accepted, where the SpecifierSet default would drop it.
        (">=0.1,<0.3", "0.2.0rc1", True),
        # but PEP 440 exclusive-ordered still excludes a prerelease OF the bound itself.
        (">=0.1,<0.2", "0.2.0rc1", False),
    ],
)
def test_core_satisfies_requires_tap(requires_tap: str, core: str, expected: bool) -> None:
    assert core_version.core_satisfies_requires_tap(requires_tap, core_version=core) is expected


def test_core_satisfies_bad_core_version_raises() -> None:
    with pytest.raises(ValueError, match="not a valid PEP 440 version"):
        core_version.core_satisfies_requires_tap(">=0.1", core_version="garbage")


def test_core_tap_version_prefers_installed_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "9.9.9" if name == "tap" else "0")
    assert core_version.core_tap_version() == "9.9.9"


def test_core_tap_version_falls_back_to_pyproject(monkeypatch: pytest.MonkeyPatch) -> None:
    def _not_found(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", _not_found)
    # The repo pyproject.toml declares [project].version, so the fallback resolves.
    version = core_version.core_tap_version()
    assert version and version[0].isdigit()


def test_core_tap_version_unresolvable_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _not_found(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", _not_found)
    # Point the fallback at a dir with no pyproject.toml.
    monkeypatch.setattr(core_version, "_REPO_ROOT", tmp_path)
    with pytest.raises(core_version.CoreVersionError, match="cannot determine core"):
        core_version.core_tap_version()
