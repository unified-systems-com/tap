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

import importlib.util
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


def find_plugin_source_root(test_file: str) -> Path | None:
    """Plugin *source* root (the dir holding ``pyproject.toml``) for a test file.

    Returns None when the plugin is installed as a wheel (no source tree in the
    ancestry) — the caller ``skipif``s, delegating source-layout validation to the
    plugin repo's own build. In a monorepo/checkout the nearest ancestor with a
    ``pyproject.toml`` is the plugin's own source root.
    """
    for parent in Path(test_file).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return None


def main() -> None:
    """Print each installed-plugin ``tests/`` dir on its own line (one per plugin).

    The collection seam for ``scripts/test``: the lane appends these paths to the
    pytest invocation so plugin tests are collected alongside the core walk.
    """
    for path in plugin_test_dirs():
        print(path)


if __name__ == "__main__":
    main()
