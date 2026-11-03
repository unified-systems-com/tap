"""Which installed plugins a core change can reach: derived imports plus declared pins (tap#1092).

The promote's local lane runs no plugin suite (``req-dev-validation-suite-tiers-6``), so a core change
that breaks a plugin is otherwise found on the plugin side, where it looks like the plugin author's
fault. This module answers "which installed plugin suites should this diff run?" from two sources:

* **Derived — the import graph.** A static AST scan of each installed plugin package (source AND tests)
  for the core modules it imports. Nothing is authored, so it cannot drift. A changed core file reaches
  a plugin that imports its app (``tap_grid/...`` → any plugin importing ``tap_grid``); for the shared
  ``tap`` package it is finer, by module (``tap/lane_run.py`` → a plugin importing ``tap.lane_run``),
  because nearly every plugin imports *something* from ``tap``.
* **Declared — the surfaces a plugin's tests pin without importing.** A plugin's tests can pin behaviour
  that has no import edge: page-layout heights, table-panel options, ``tap_viz`` JavaScript source
  strings, spec rows. The plugin says so with a module-level constant in any of its test modules::

      PINS_CORE_SURFACES = ("tap_viz/static", "tap_web/templates")

  Each entry is a path prefix; a changed file under one selects the plugin. The constant is read by AST
  (never imported), needs no manifest-schema change, and lives next to the tests that rely on it.

Honest boundary: both sources are *conservative guesses about reach*, not proofs. The import graph is
per app, so it over-selects (every ``tap_grid`` change selects every ``tap_grid`` user), and coupling
that is neither imported nor declared is invisible. The server ``gate`` stays the authority
(``req-dev-validation-suite-tiers-4``); this only makes the local lane's coverage of plugins a choice
instead of an accident. Settings-free and import-safe (stdlib + ``tap.source_scan``).

Usage inside the container (changed paths on stdin, one per line)::

    git diff --name-only origin/main | scripts/dc exec -T web uv run python -m tap.impacted_plugins
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from tap.source_scan import iter_parsed_sources

DECLARATION = "PINS_CORE_SURFACES"
# Changed paths that cannot change what a plugin's code or tests see.
_INERT_PARTS = ("/tests/", "/specs/", "/docs/", "/skills/", "/static/vendor/")
_INERT_SUFFIXES = (".md", ".txt", ".rst")


@dataclass(frozen=True)
class PluginReach:
    """What one plugin imports from core and which core surfaces its tests declare they pin."""

    slug: str
    imported_apps: frozenset[str]  # top-level packages other than `tap` and `tap_plugin`, e.g. tap_grid
    imported_tap_modules: frozenset[str]  # dotted `tap.*` modules, e.g. tap.lane_run
    declared_surfaces: tuple[str, ...]  # path prefixes, e.g. tap_viz/static


@dataclass
class Impact:
    """Why a plugin was selected: one human-readable reason per matching changed path."""

    slug: str
    reasons: list[str] = field(default_factory=list)


def is_inert(path: str) -> bool:
    """A path whose change cannot reach plugin behaviour (docs, specs, tests, skills, markdown)."""
    padded = "/" + path
    return path.endswith(_INERT_SUFFIXES) or any(part in padded for part in _INERT_PARTS)


def module_of(path: str) -> str | None:
    """``tap/lane_run.py`` → ``tap.lane_run``; ``tap_grid/x/__init__.py`` → ``tap_grid.x``; else None."""
    if not path.endswith(".py"):
        return None
    parts = path[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else None


def scan_reach(slug: str, package_dir: Path) -> PluginReach:
    """AST-scan one plugin package (source and tests) for core imports and the pins declaration."""
    apps: set[str] = set()
    tap_modules: set[str] = set()
    declared: list[str] = []
    for parsed in iter_parsed_sources([package_dir]):
        for node in ast.walk(parsed.tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
                if node.module == "tap":  # `from tap import lane_run` names the module in the alias
                    names += [f"tap.{alias.name}" for alias in node.names]
            for dotted in names:
                top = dotted.split(".")[0]
                if top == "tap":
                    tap_modules.add(dotted)
                elif top.startswith("tap_") and top != "tap_plugin":
                    apps.add(top)
            declared += _declared_in(node)
    return PluginReach(slug, frozenset(apps), frozenset(tap_modules), tuple(sorted(set(declared))))


def _declared_in(node: ast.AST) -> list[str]:
    """String entries of a module-level ``PINS_CORE_SURFACES = (...)`` assignment, else []."""
    if not isinstance(node, ast.Assign) or not isinstance(node.value, (ast.Tuple, ast.List)):
        return []
    if not any(isinstance(t, ast.Name) and t.id == DECLARATION for t in node.targets):
        return []
    return [e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def impacted(changed_paths: Iterable[str], reaches: Iterable[PluginReach]) -> dict[str, Impact]:
    """Select the plugins a set of changed core paths can reach, with the reason for each."""
    paths = [p for p in (c.strip() for c in changed_paths) if p and not is_inert(p)]
    selected: dict[str, Impact] = {}
    for reach in reaches:
        for path in paths:
            top = path.split("/")[0]
            reason = None
            if top in reach.imported_apps:
                reason = f"{path}: {reach.slug} imports {top}"
            elif top == "tap":
                module = module_of(path)
                if module is not None and any(
                    m == module or m.startswith(module + ".") for m in reach.imported_tap_modules
                ):
                    reason = f"{path}: {reach.slug} imports {module}"
            if reason is None:
                for surface in reach.declared_surfaces:
                    if path == surface or path.startswith(surface.rstrip("/") + "/"):
                        reason = f"{path}: {reach.slug} declares it pins {surface}"
                        break
            if reason is not None:
                selected.setdefault(reach.slug, Impact(reach.slug)).reasons.append(reason)
    return selected


def main(argv: list[str] | None = None) -> int:
    """Read changed paths on stdin; print impacted slugs on stdout and the reasons on stderr."""
    from tap.plugin_testing import plugin_package_dir, plugin_suites

    changed = sys.stdin.read().splitlines()
    reaches = []
    for suite in plugin_suites():
        package_dir = plugin_package_dir(suite.slug)
        if package_dir is not None:
            reaches.append(scan_reach(suite.slug, package_dir))
    result = impacted(changed, reaches)
    for slug in sorted(result):
        sys.stdout.write(slug + "\n")
        for reason in result[slug].reasons[:5]:
            sys.stderr.write(f"impacted plugin {reason}\n")
        extra = len(result[slug].reasons) - 5
        if extra > 0:
            sys.stderr.write(f"impacted plugin {slug}: ... and {extra} more changed paths\n")
    if not result:
        sys.stderr.write(
            "impacted plugins: none (no installed plugin imports or declares a pin on the changed paths)\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
