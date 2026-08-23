"""Plugin cross-plugin dependency derivation + consistency checking (settings-free).

The same declare / derive / cross-check / fail-closed move the pre-boot reconciliation
guard makes, applied to plugin dependencies (spec-tap-plugin-architecture.md
``req-tap-plugin-arch-dependencies``):

- **Declared intent** — each plugin's manifest ``depends_on`` slug edges (Tier 1).
- **Observed reality** — a static AST scan of each installed plugin package for
  ``tap_plugin.<other>`` imports. The cross-plugin *code* dependency graph is not
  authored; it *is* the set of imports, so we observe it rather than trust a
  declaration. (Reuses the filesystem discovery muscle in ``tap.logging``.)
- **Cross-check** — ``tap.preboot._dependency_consistency_guard`` compares the two
  plus the profile install order and fails closed on divergence.

HONEST BOUNDARY (do not conflate): the import graph is the **code** dependency only.
It does NOT capture the **data** dependency (e.g. samsite's compliance collector must
run after the boto3/github collectors because it reads nodes they produce) — that stays
profile-explicit fire-collector ordering for auditability (``req-tap-plugin-arch-dependencies-3``).

This module is settings-free and import-safe (stdlib + ``tap.logging`` only) so it runs
in the pre-Django pre-boot stage and at pytest-collection time.
"""

from __future__ import annotations

import ast
import tomllib
from dataclasses import dataclass
from pathlib import Path

from tap.plugin_identity import NAMESPACE_PACKAGE
from tap.source_scan import first_party_source_roots, iter_parsed_sources

# The PEP 420 namespace every package-mode plugin imports under (req-tap-plugin-arch-identity-3).
# Declared once in tap.plugin_identity (stdlib-only, so pre-Django callers can import it).
NAMESPACE = NAMESPACE_PACKAGE


@dataclass(frozen=True)
class DeclaredDep:
    """A depends_on edge as read from a plugin manifest (lightweight, gate-scoped).

    Mirrors ``tap_plugins.manifest.DependencyEntry`` but is read without the full
    Django-time manifest validation so the gate can run pre-migrate. The manifest
    reader remains the authority on structural validity at ``ready()``.
    """

    slug: str
    min_version: str | None
    optional: bool


def _tap_plugin_segment(dotted: str) -> str | None:
    """Return the ``<slug>`` in a ``tap_plugin.<slug>[.…]`` dotted name, else None."""
    parts = dotted.split(".")
    if len(parts) >= 2 and parts[0] == NAMESPACE:
        return parts[1]
    return None


def scan_observed_imports(package_dir: Path, own_slug: str) -> set[str]:
    """Return the set of OTHER plugin slugs this package imports via ``tap_plugin.<slug>``.

    Static AST scan of every ``*.py`` under *package_dir* for ``import tap_plugin.x`` and
    ``from tap_plugin.x[.…] import …`` (absolute imports only). The plugin's own slug is
    excluded. Unparseable files are skipped (they surface elsewhere), never fatal here.
    """
    observed: set[str] = set()
    for parsed in iter_parsed_sources([package_dir]):
        for node in ast.walk(parsed.tree):
            dotted_names: list[str] = []
            if isinstance(node, ast.Import):
                dotted_names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                # level > 0 is a relative import (never cross-plugin); module may be None.
                if node.level == 0 and node.module:
                    dotted_names = [node.module]
            for dotted in dotted_names:
                seg = _tap_plugin_segment(dotted)
                if seg is not None and seg != own_slug:
                    observed.add(seg)
    return observed


def read_declared_depends_on(package_dir: Path) -> list[DeclaredDep]:
    """Read the ``depends_on`` edges from *package_dir*'s ``tap-plugin.toml``.

    Tolerant, gate-scoped read (structural validation is the manifest reader's job at
    ``ready()``): entries missing a string ``slug`` are skipped rather than raising, so
    a malformed manifest fails at the manifest reader with a precise message instead of
    here. Returns [] when there is no manifest or no ``depends_on``.
    """
    manifest = package_dir / "tap-plugin.toml"
    if not manifest.exists():
        return []
    try:
        with open(manifest, "rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError, OSError:
        return []
    deps: list[DeclaredDep] = []
    for item in raw.get("depends_on", []) or []:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug")
        if not isinstance(slug, str) or not slug:
            continue
        min_version = item.get("min_version")
        if not isinstance(min_version, str) or not min_version:
            min_version = None
        deps.append(DeclaredDep(slug=slug, min_version=min_version, optional=bool(item.get("optional", False))))
    return deps


def read_manifest_slug(package_dir: Path) -> str | None:
    """Return the ``slug`` declared in *package_dir*'s ``tap-plugin.toml``, or None."""
    manifest = package_dir / "tap-plugin.toml"
    if not manifest.exists():
        return None
    try:
        with open(manifest, "rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError, OSError:
        return None
    slug = raw.get("slug")
    return slug if isinstance(slug, str) and slug else None


def discover_plugin_packages(project_root: Path) -> dict[str, Path]:
    """Map plugin slug → its in-repo package directory (the ``tap-plugin.toml``-bearing dir).

    Reuses ``tap.source_scan.first_party_source_roots`` (which already recognizes both the
    legacy flat layout and the package-mode namespace layout), filtered to manifest-bearing
    roots. A fully-extracted site-packages plugin is out of scope by construction — same
    caveat the log/authz scanners carry.
    """
    packages: dict[str, Path] = {}
    for root in first_party_source_roots(project_root):
        slug = read_manifest_slug(root)
        if slug is not None:
            packages[slug] = root
    return packages


def _version_lt(installed: str, minimum: str) -> bool:
    """True if *installed* < *minimum* under PEP 440, tolerant of unparseable versions.

    An unparseable version is treated as NOT-less-than (do not fail the gate on a version
    string we cannot compare — the honest failure is a missing/malformed dist, caught
    elsewhere). ``packaging`` is always present (a uv/pip transitive dependency).
    """
    from packaging.version import InvalidVersion, Version

    try:
        return Version(installed) < Version(minimum)
    except InvalidVersion:
        return False


def compute_violations(
    install_order: list[str],
    declared: dict[str, list[DeclaredDep]],
    observed: dict[str, set[str]],
    versions: dict[str, str | None],
) -> list[str]:
    """Pure consistency check → list of human-readable violation strings (empty = OK).

    Three checks, all fail-closed (spec ``req-tap-plugin-arch-dependencies-4``):

    1. **declared ⊇ observed** — every observed cross-plugin import has a matching
       ``depends_on`` (an undeclared import is exactly the silent coupling that bites on
       extraction to a standalone repo).
    2. **install order respects depends_on** — a (required) dependency must be present in
       the profile install set AND ordered before its dependent. Optional deps that are
       absent are tolerated; if present they must still be ordered correctly.
    3. **min-version satisfied** — a declared ``min_version`` floor holds against the
       installed distribution version.

    Only plugins in *install_order* are checked (the set actually being loaded). Inputs are
    pre-gathered so this function is filesystem-free and trivially unit-testable.
    """
    violations: list[str] = []
    position = {slug: i for i, slug in enumerate(install_order)}
    install_set = set(install_order)

    for slug in install_order:
        decl = declared.get(slug, [])
        declared_slugs = {d.slug for d in decl}
        obs = observed.get(slug, set())

        # (1) declared ⊇ observed
        for missing in sorted(obs - declared_slugs):
            violations.append(
                f"'{slug}' imports 'tap_plugin.{missing}' but does not declare it in depends_on "
                f'(add {{ slug = "{missing}" }} to {slug}\'s tap-plugin.toml depends_on)'
            )

        # (2) install order + presence
        for d in decl:
            if d.slug not in install_set:
                if d.optional:
                    continue
                violations.append(
                    f"'{slug}' depends_on '{d.slug}' which is not in the profile install set "
                    f"(add it to the profile `install` section, or mark the dependency optional)"
                )
                continue
            if position[d.slug] > position[slug]:
                violations.append(
                    f"'{slug}' is installed before its declared dependency '{d.slug}' — reorder the "
                    f"profile `install` section so dependencies precede dependents"
                )

            # (3) min-version (only when the dep is present + declares a floor)
            if d.min_version:
                installed = versions.get(d.slug)
                if installed is not None and _version_lt(installed, d.min_version):
                    violations.append(
                        f"'{slug}' depends_on '{d.slug}>={d.min_version}' but the installed version is "
                        f"'{installed}' (upgrade '{d.slug}')"
                    )

    return violations
