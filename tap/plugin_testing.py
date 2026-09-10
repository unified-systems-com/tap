"""Test-collection + test-support helpers for package-mode plugin tests.

Plugin tests live *inside* the namespace package (``tap_plugin/<slug>/tests/``) so
they ride in the built wheel and travel with the plugin — both as the all-plugins
CI lane's coverage and as an AI-legible corpus a maintenance agent can read
(see the ``ship-tests-in-wheel`` design note). Two consequences the rest of the
test system is built on:

* **Collection is by explicit path, not the repo-root walk.** pyproject
  ``addopts`` carries ``--ignore=plugins`` so the root discovery never descends
  into plugin source trees (which would double-collect the relocated tests). Plugin
  tests are added back by resolving each *installed* plugin's ``tests/`` dir here
  and passing it to pytest. An uninstalled plugin's tests are therefore never
  referenced at all — structural local scoping, no skip machinery — and the
  all-plugins CI lane owns full-set coverage.

* **Source-layout tests self-skip off a checkout.** A test that inspects the
  plugin *source* tree (``pyproject.toml``, the identity chain) cannot run from an
  installed wheel, where no source root exists. ``find_plugin_source_root`` returns
  ``None`` there so such tests ``skipif`` out, delegated to the plugin repo's own
  build; behavioural tests import ``tap_plugin.<slug>`` and run either way.

``scripts/test`` (the lane) and ``tap.guards`` collection-completeness both source
their plugin paths from here so the two never diverge.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path


def installed_plugin_slugs() -> list[str]:
    """Slugs of the plugins installed+enabled in THIS stack.

    Single-sourced through ``tap.preboot.resolved_plugin_app_configs`` (TAP_PLUGINS
    authoritative: env → persisted set → warned live-discovery fallback), so the test
    harness and ``tap.settings`` INSTALLED_APPS can never disagree on the plugin set —
    the divergence that was previously two hand-copied resolvers.
    """
    from tap.preboot import resolved_plugin_app_configs

    return sorted({app.split(".")[1] for app in resolved_plugin_app_configs() if app.startswith("tap_plugin.")})


def requires_plugins(*slugs: str):
    """Skip a CORE-located test/module unless every named plugin is installed.

    The install-aware complement to collection scoping. A plugin's *own* tests
    ride inside its package, so an uninstalled plugin's tests are simply never
    collected (see the module docstring). But a **core** test — one that lives in
    ``tap_grid/tests/``, ``tap_boot/tests/``, ``tap_plugins/tests/`` … — may import
    or assert on a specific plugin (``import tap_plugin.computing_core``; ``assert
    "samsite" in build_report()``; ``validate_plugin(root, level="loads")`` which
    imports the package; a boot profile that seeds a plugin). Those cannot be
    collection-ignored (they sit among install-independent tests in the same file),
    so a focused stack that lacks the plugin *errors* instead of skipping. Decorate
    such a test (or set a module-level ``pytestmark``) with this so the focused
    local gate skips it while the all-plugins CI lane — where ``test_all`` installs
    every plugin — runs it fully. That split is the whole model: local validates
    what is installed; CI owns all-plugins truth (req-dev-validation-all-plugins-lane).

    Baseline vocabulary plugins (:data:`BASELINE_PLUGIN_SLUGS`) are deliberately NOT
    guarded this way. Their absence is not a legitimate partial stack to skip past —
    it means this stack cannot run the core suite at all, which
    :func:`missing_baseline_plugins` reports as a loud failure instead. Guarding them
    here would convert that into a silent green (req-dev-validation-baseline-vocabulary).
    """
    import pytest

    missing = sorted(set(slugs) - set(installed_plugin_slugs()))
    return pytest.mark.skipif(
        bool(missing),
        reason=f"requires plugin(s) not installed in this stack: {', '.join(missing)}",
    )


#: Plugin slugs whose node/edge vocabulary the CORE suites build fixtures from.
#:
#: These are not optional plugins a stack may or may not carry — core-located tests in
#: ``tap_grid/``, ``tap_api/``, ``tap_web/`` … import ``tap_plugin.<slug>`` models and
#: assert on ``<slug>__*`` entity types directly, so a stack without them cannot
#: exercise the grid spine (service layer, FLIP, OCC, history, GRIFT, purge) at all.
#: The requirement used to live only as prose in this module and in
#: ``boot/core.boot.json``'s description; this tuple is the executable statement of it.
#: A boot profile intended to run the core suite MUST install every slug here — that is
#: the ``core`` vs ``core_dev`` split, and the same split any product line inherits.
BASELINE_PLUGIN_SLUGS: tuple[str, ...] = ("grid_fixtures",)


def missing_baseline_plugins() -> list[str]:
    """Baseline vocabulary slugs (:data:`BASELINE_PLUGIN_SLUGS`) this stack does not have.

    TAP-IMPLEMENTS: req-dev-validation-baseline-vocabulary@b7151874485b/64ff63d8ab7a (derivation) — the one
    place "is the core suite's fixture vocabulary present in this stack" is computed; every caller asks here
    rather than re-reading TAP_PLUGINS or inferring it from a profile classification.

    Derived from :func:`installed_plugin_slugs`, so it reads the same ``TAP_PLUGINS``
    resolution ``tap.settings`` uses to build ``INSTALLED_APPS`` — the fact itself, not a
    proxy for it. A profile classification (``profile_kind``) or a test-runner flag
    (``TAP_TEST_MODE``) would each be a weaker signal that can be true while the
    vocabulary is absent, and ``TAP_TEST_MODE`` is true in every pytest run by
    construction (``tap/test_settings.py``), including the failing ones.
    """
    return sorted(set(BASELINE_PLUGIN_SLUGS) - set(installed_plugin_slugs()))


def plugin_package_dir(slug: str) -> Path | None:
    """Filesystem location of the installed ``tap_plugin.<slug>`` package, or None.

    Resolved through the import system, so it points at the editable checkout
    (``plugins/<slug>/tap_plugin/<slug>``) or the site-packages install with equal
    fidelity — the caller never has to know which.
    """
    spec = importlib.util.find_spec(f"tap_plugin.{slug}")
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations)))


def plugin_test_dirs() -> list[Path]:
    """The ``tests/`` dir of every installed plugin that ships one."""
    dirs: list[Path] = []
    for slug in installed_plugin_slugs():
        pkg = plugin_package_dir(slug)
        if pkg is None:
            continue
        tests = pkg / "tests"
        if tests.is_dir():
            dirs.append(tests)
    return dirs


_INSTALL_DIRS = frozenset({"site-packages", "dist-packages", ".venv"})


def find_plugin_source_root(test_file: str) -> Path | None:
    """Plugin *source* root (the dir holding ``pyproject.toml``) for a test file.

    Returns None when the plugin is installed as a wheel — the caller ``skipif``s,
    delegating source-layout validation to the plugin repo's own build. In a checkout the
    plugin's own source root is the ancestor holding both ``pyproject.toml`` and the
    plugin package this test file lives in.

    The candidate must OWN this plugin's source (``<root>/tap_plugin/<slug>`` contains the
    test file). "Nearest ancestor with a ``pyproject.toml``" alone is a false-negative skip
    guard: under a wheel install the walk climbs out of ``site-packages`` and finds the
    HARNESS's ``pyproject.toml`` (or one a wheel dropped beside the packages), so the guard
    never fires and the test validates a directory that is not the plugin — observed
    2026-09-10 in the first BOM-lane run, where six wheel-installed plugins failed
    ``structure`` validation against ``/app/.venv/.../site-packages`` instead of skipping
    (tap#369).
    """
    resolved = Path(test_file).resolve()
    parents = list(resolved.parents)
    # A package under site-packages (or inside a venv) IS a wheel install — whatever
    # pyproject.toml happens to sit there belongs to something else.
    if any(parent.name in _INSTALL_DIRS for parent in parents):
        return None
    slug: str | None = None
    for i, parent in enumerate(parents):
        if parent.name == "tap_plugin" and i > 0:
            slug = parents[i - 1].name
            break
    for parent in parents:
        if not (parent / "pyproject.toml").is_file():
            continue
        if slug is None:
            return parent
        package = parent / "tap_plugin" / slug
        if package.is_dir() and _contains(package, resolved):
            return parent
        # A pyproject.toml that does not own this plugin's source: a wheel install.
        return None
    return None


def _contains(directory: Path, path: Path) -> bool:
    """True when ``path`` lives inside ``directory`` (both resolved)."""
    try:
        path.resolve().relative_to(directory.resolve())
    except OSError, ValueError:
        return False
    return True


@dataclass(frozen=True)
class PluginSuite:
    """One installed plugin's shipped test suite, as the lane sees it."""

    slug: str
    tests_dir: Path | None  # None: the package is installed but ships no ``tests/`` dir
    has_test_files: bool  # a ``tests/`` dir with at least one non-``__init__`` module


def plugin_suites() -> list[PluginSuite]:
    """Every installed plugin with where (and whether) its shipped tests live.

    The one seam the lanes derive their collection from (req-dev-validation-collection-complete-4).
    A plugin with no ``tests/`` dir or an empty package is reported as such — printed, never
    silently dropped — so the lane runner can tell "ships no tests" from "collected nothing".
    """
    suites: list[PluginSuite] = []
    for slug in installed_plugin_slugs():
        pkg = plugin_package_dir(slug)
        tests = pkg / "tests" if pkg is not None else None
        if tests is None or not tests.is_dir():
            suites.append(PluginSuite(slug, None, False))
            continue
        has_files = any(f.name != "__init__.py" for f in tests.rglob("*.py"))
        suites.append(PluginSuite(slug, tests, has_files))
    return suites


def expected_plugin_slugs(record_path: Path) -> list[str]:
    """Slugs a boot record installs (``install.plugins[]`` with ``enabled`` not false).

    Derived from the record itself, so the lane's EXPECTED membership is the BOM's, never a
    hand list — the guard against a discovery helper that silently omits a plugin.
    """
    record = Path(record_path).resolve()
    # Checked at the sink: the lane names its own record, but this is where a path becomes a
    # filesystem read, so the shape is asserted here rather than assumed from the caller.
    if record.suffix != ".json" or not record.name.endswith(".boot.json") or not record.is_file():
        raise ValueError(f"not a boot record: {record_path}")
    # NOSONAR (S8707) — checked immediately above: resolved, must be a real `*.boot.json` file.
    data = json.loads(record.read_text(encoding="utf-8"))  # NOSONAR (S8707)
    plugins = (data.get("install") or {}).get("plugins") or []
    return sorted(p["slug"] for p in plugins if isinstance(p, dict) and p.get("enabled", True) and p.get("slug"))


def membership_omissions(expected: list[str], installed: list[str]) -> list[str]:
    """Expected slugs the discovery did not surface — each one is an unexplained omission."""
    return sorted(set(expected) - set(installed))


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tap.plugin_testing", description=main.__doc__)
    parser.add_argument("--plan", action="store_true", help="print the lane plan as JSON (suites with dirs and shapes)")
    parser.add_argument(
        "--record",
        type=Path,
        help="boot record to derive EXPECTED membership from; with --check, exit 1 on an omission",
    )
    parser.add_argument(
        "--check", action="store_true", help="fail (exit 1) when a plugin the record installs is not discovered"
    )
    args = parser.parse_args(argv)
    if args.record is not None:
        expected = expected_plugin_slugs(args.record)
        missing = membership_omissions(expected, installed_plugin_slugs())
        if args.check and missing:
            print(f"::error::plugins the record installs but discovery did not surface: {', '.join(missing)}")
            return 1
    if args.plan:
        plan = [
            {
                "slug": st.slug,
                "tests_dir": str(st.tests_dir) if st.tests_dir else None,
                "has_test_files": st.has_test_files,
            }
            for st in plugin_suites()
        ]
        print(json.dumps(plan, indent=2))
        return 0
    main()
    return 0


def main() -> None:
    """Print each installed-plugin ``tests/`` dir on its own line (one per plugin).

    The collection seam for ``scripts/test``: the lane appends these paths to the
    pytest invocation so plugin tests are collected alongside the core walk.
    """
    for path in plugin_test_dirs():
        print(path)


if __name__ == "__main__":
    raise SystemExit(_cli())
