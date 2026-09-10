"""The `core_ci` boot profile is bounded, and its pins are `test_all`'s.

Spec: specs/spec-dev-validation.md (req-dev-validation-bom-lane-4, req-dev-validation-product-line-lanes-8).

`core_ci` is the core PR gate's profile: core + the fixture plugins the core suite needs + ONE
flagship canary with its declared dependency closure. It must never quietly grow into a second
full set (that is `test_all`, the BOM), and it must never carry a pin of its own — a plugin
version lives in one place and `scripts/release-plugin.sh` bumps every consuming record.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tap.plugin_testing import BASELINE_PLUGIN_SLUGS, installed_plugin_slugs, plugin_package_dir

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOT_DIR = REPO_ROOT / "boot"

CANARY = "github_core"
#: Plugins that exist for the core suite's sake: the baseline vocabulary, the query corpus, the
#: validate_plugin target. Anything else in `core_ci` must be the canary or in its closure.
FIXTURE_SLUGS: frozenset[str] = frozenset(BASELINE_PLUGIN_SLUGS) | {"gryphon_playground", "validation_sample"}
CANARY_DEP_NOTE_PREFIX = "Canary dependency:"


def _record(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((BOOT_DIR / f"{name}.boot.json").read_text(encoding="utf-8"))
    return data


def _plugins(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["slug"]: p for p in record["install"]["plugins"]}


def _declared_closure(slug: str) -> set[str] | None:
    """Transitive `depends_on` closure of an INSTALLED plugin's manifest, or None if not installed."""
    from tap_plugins.manifest import load_manifest

    root = plugin_package_dir(slug)
    if root is None:
        return None
    closure: set[str] = set()
    frontier = [slug]
    while frontier:
        current = frontier.pop()
        pkg = plugin_package_dir(current)
        if pkg is None:
            continue
        for dep in load_manifest(pkg).depends_on:
            if dep.slug not in closure:
                closure.add(dep.slug)
                frontier.append(dep.slug)
    return closure


def _installed_version(slug: str) -> str | None:
    """The installed distribution version of a plugin, or None when it is not installed."""
    from importlib.metadata import PackageNotFoundError, version

    from tap.plugin_identity import dist_name_for_slug

    try:
        return version(dist_name_for_slug(slug))
    except PackageNotFoundError:
        return None


def _booted_from_core_ci() -> bool:
    """True inside a stack booted from the `core_ci` profile — where the bound must hold, not skip."""
    return os.environ.get("TAP_BOOT_PROFILE") == "core_ci"


def _installed_matches_pin(slug: str, entry: dict[str, Any]) -> bool:
    """True when the installed distribution is the record's pinned rev (`vX.Y.Z` → `X.Y.Z`)."""
    rev = str(entry["source"].get("rev", ""))
    installed = _installed_version(slug)
    return installed is not None and installed == rev.lstrip("v")


def pinned_reason(slug: str, entry: dict[str, Any]) -> str:
    return (
        f"installed {slug} is {_installed_version(slug)!r}, the record pins {entry['source'].get('rev')!r}; "
        "the closure check compares against the PINNED manifest and runs where the pin is what is installed (the core_ci lane)"
    )


@pytest.mark.spec("req-dev-validation-product-line-lanes-8")
def test_core_ci_carries_only_fixtures_and_the_canary_closure() -> None:
    """Every `core_ci` plugin is a fixture, the canary, or a declared canary dependency."""
    core_ci = _plugins(_record("core_ci"))
    assert CANARY in core_ci, "core_ci must carry the canary"
    extras = set(core_ci) - FIXTURE_SLUGS - {CANARY}
    for slug in sorted(extras):
        note = core_ci[slug].get("note", "")
        assert note.startswith(CANARY_DEP_NOTE_PREFIX), (
            f"{slug!r} is neither a fixture ({sorted(FIXTURE_SLUGS)}) nor the canary ({CANARY!r}); "
            f"a canary dependency's note must start with {CANARY_DEP_NOTE_PREFIX!r}, and nothing else belongs in core_ci"
        )
    closure = _declared_closure(CANARY)
    if closure is None:
        pytest.skip(f"{CANARY} is not installed in this stack; the closure check runs in the core_ci lane")
    pinned = _installed_matches_pin(CANARY, core_ci[CANARY])
    if not pinned:
        # In the core_ci lane the installed canary IS the pinned one; anything else there is a
        # broken install or a broken lookup and must be red, not a skip (fail closed).
        assert not _booted_from_core_ci(), pinned_reason(CANARY, core_ci[CANARY])
        pytest.skip(pinned_reason(CANARY, core_ci[CANARY]))
    assert (
        extras == closure
    ), f"core_ci's non-fixture set {sorted(extras)} must equal {CANARY}'s declared dependency closure {sorted(closure)}"


@pytest.mark.spec("req-dev-validation-product-line-lanes-8")
def test_core_ci_pins_are_test_all_pins() -> None:
    """A plugin version lives once: every `core_ci` source equals `test_all`'s for the same slug."""
    core_ci = _plugins(_record("core_ci"))
    test_all = _plugins(_record("test_all"))
    for slug, entry in core_ci.items():
        assert slug in test_all, f"{slug!r} is in core_ci but not in test_all — the BOM must be the superset"
        assert (
            entry["source"] == test_all[slug]["source"]
        ), f"{slug!r} pin differs: core_ci {entry['source']} vs test_all {test_all[slug]['source']}"


@pytest.mark.spec("req-dev-validation-product-line-lanes-8")
def test_core_ci_seeds_only_what_it_installs_and_test_all_seeds() -> None:
    """Population is a subset of the install set and of `test_all`'s population."""
    core_ci = _record("core_ci")
    test_all_steps = {s["plugin"] for s in _record("test_all")["population"]["steps"]}
    installed = set(_plugins(core_ci))
    for step in core_ci["population"]["steps"]:
        assert step["plugin"] in installed, f"population seeds {step['plugin']!r} which core_ci does not install"
        assert step["plugin"] in test_all_steps, f"{step['plugin']!r} is seeded by core_ci but not by test_all"


@pytest.mark.skipif(
    CANARY not in installed_plugin_slugs(), reason="the canary is installed only in the core_ci / test_all lanes"
)
def test_canary_is_installed_where_the_profile_says() -> None:
    """On a stack booted from `core_ci` the canary's package resolves (the lane is not a no-op)."""
    assert plugin_package_dir(CANARY) is not None
