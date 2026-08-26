"""Core (`tap`) version resolution and plugin compatibility-floor checking.

Low-level, dependency-free helpers shared by the pre-boot compatibility gate
(`tap.preboot`) and the author-time conformance check (`tap_plugins.validate`).
Lives in ``tap/`` — not in either app — so both consume one implementation
rather than depending sideways on each other (see the avoid-app-interdependencies
rule).

The single question this module answers: *does the running core satisfy a plugin's
declared ``requires_tap`` range?* — the VS Code ``engines.vscode`` model applied to
TAP (``spec-tap-plugin-external-development.md`` ``req-tap-plugin-extdev-compat-floor``).

Public API:
    core_tap_version() -> str
    parse_requires_tap(spec, *, source="") -> SpecifierSet
    core_satisfies_requires_tap(requires_tap, *, core_version=None) -> bool
"""

from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

# The distribution / project name of TAP core. Plugins declare compatibility
# against THIS name's version, not their own.
CORE_DIST_NAME = "tap"

# Repo root: tap/core_version.py -> <repo>. The cloned-core harness always has a
# pyproject.toml here even when core is on the path but not pip-installed.
_REPO_ROOT = Path(__file__).resolve().parent.parent


class CoreVersionError(Exception):
    """Raised when the running core version cannot be determined at all."""


def core_tap_version() -> str:
    """Return the running core (`tap`) version string.

    Resolution order, covering both delivery shapes:

    1. Installed distribution metadata (``importlib.metadata.version("tap")``) —
       a packaged/appliance core.
    2. ``[project].version`` in ``<repo>/pyproject.toml`` — the cloned-core harness,
       where core is importable off the path but carries no installed metadata.

    Raises:
        CoreVersionError: if neither source yields a version. Callers that only
            need the version when a plugin actually declares ``requires_tap``
            should resolve lazily so a plugin with no floor is unaffected.
    """
    try:
        return importlib.metadata.version(CORE_DIST_NAME)
    except importlib.metadata.PackageNotFoundError:
        pass

    pyproject = _REPO_ROOT / "pyproject.toml"
    if pyproject.is_file():
        with open(pyproject, "rb") as fh:
            data = tomllib.load(fh)
        version = data.get("project", {}).get("version")
        if isinstance(version, str) and version:
            return version

    raise CoreVersionError(
        f"cannot determine core '{CORE_DIST_NAME}' version: no installed metadata and no "
        f"[project].version in {pyproject}"
    )


def parse_requires_tap(spec: str, *, source: str = "") -> SpecifierSet:
    """Parse a ``requires_tap`` PEP 440 specifier string, raising on malformed input.

    Args:
        spec: e.g. ``">=0.1,<0.2"``.
        source: optional context (plugin slug / manifest path) for the error message.

    Raises:
        ValueError: if *spec* is not a valid PEP 440 version specifier.
    """
    try:
        return SpecifierSet(spec)
    except InvalidSpecifier as exc:
        where = f" ({source})" if source else ""
        raise ValueError(f"invalid requires_tap specifier {spec!r}{where}: {exc}") from exc


def core_satisfies_requires_tap(requires_tap: str, *, core_version: str | None = None) -> bool:
    """Return True iff the running core version is inside *requires_tap*.

    Prereleases are accepted (``prereleases=True``) so a developer running a
    prerelease harness core (e.g. ``0.2.0rc1``) is not spuriously refused.

    Args:
        requires_tap: a PEP 440 specifier string (validated via ``parse_requires_tap``).
        core_version: the running core version; resolved via ``core_tap_version()``
            when omitted.

    Raises:
        ValueError: if *requires_tap* is malformed or *core_version* is not a valid version.
        CoreVersionError: if *core_version* is omitted and cannot be resolved.
    """
    spec = parse_requires_tap(requires_tap)
    resolved = core_version if core_version is not None else core_tap_version()
    try:
        version = Version(resolved)
    except InvalidVersion as exc:
        raise ValueError(f"core version {resolved!r} is not a valid PEP 440 version: {exc}") from exc
    return spec.contains(version, prereleases=True)
