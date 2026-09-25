"""The `core_ci` boot profile is core plus the fixture plugins, and nothing else.

Spec: specs/spec-dev-validation.md (req-dev-validation-product-line-lanes-8, req-dev-validation-bom-lane-4).

`core_ci` is the core PR gate's profile: core + the three fixture plugins the core suite is built
on (the grid_fixtures vocabulary, the gryphon_playground query corpus, the in-tree
validation_sample target). Product components — github_core and the substrate plugins it depends
on — are owned by the products that ship them and are proven in those products' lanes, not here
(tap#638). The profile owns its own pins; `scripts/release-plugin.sh` bumps every record that
names a released slug, so a fixture's version still moves in one step.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tap.plugin_testing import BASELINE_PLUGIN_SLUGS, plugin_package_dir

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOT_DIR = REPO_ROOT / "boot"

#: Plugins that exist for the core suite's sake: the baseline vocabulary, the query corpus, the
#: validate_plugin target. `core_ci` carries exactly these.
FIXTURE_SLUGS: frozenset[str] = frozenset(BASELINE_PLUGIN_SLUGS) | {"gryphon_playground", "validation_sample"}


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


def _skip_outside_the_core_ci_lane(reason: str) -> None:
    """Skip where core_ci's plugins are not installed; inside a core_ci-booted stack that is a red."""
    assert os.environ.get("TAP_BOOT_PROFILE") != "core_ci", f"booted from core_ci, yet: {reason}"
    pytest.skip(reason)


@pytest.mark.spec("req-dev-validation-product-line-lanes-8")
def test_core_ci_carries_exactly_the_fixture_plugins() -> None:
    """Every fixture plugin, and no product component: products own those (tap#638)."""
    installed = set(_plugins(_record("core_ci")))
    assert installed == FIXTURE_SLUGS, (
        f"core_ci installs {sorted(installed)}; it must install exactly the fixture plugins "
        f"{sorted(FIXTURE_SLUGS)}. A product plugin is proven in its product's lane, not core's."
    )


@pytest.mark.spec("req-dev-validation-product-line-lanes-8")
def test_core_ci_fixtures_depend_only_on_fixtures() -> None:
    """A fixture's declared dependency closure stays inside the fixture set, or core_ci could not install it."""
    checked = 0
    for slug in sorted(FIXTURE_SLUGS):
        closure = _declared_closure(slug)
        if closure is None:
            continue  # not installed in this stack; the core_ci lane installs all three
        checked += 1
        outside = sorted(closure - FIXTURE_SLUGS)
        assert not outside, f"fixture {slug!r} depends on non-fixture plugins {outside}"
    if not checked:
        _skip_outside_the_core_ci_lane(
            "no fixture plugin is installed in this stack; the check runs in the core_ci lane"
        )


@pytest.mark.spec("req-dev-validation-product-line-lanes-8")
def test_core_ci_seeds_a_fixture_it_installs() -> None:
    """Population is non-empty and seeds only installed fixtures, so the cold boot's strict seed is not vacuous."""
    core_ci = _record("core_ci")
    installed = set(_plugins(core_ci))
    seeded = [step["plugin"] for step in core_ci["population"]["steps"] if step.get("type") == "seed-plugin"]
    assert seeded, "core_ci must seed at least one fixture: an empty population makes seed:boot-profile prove nothing"
    for slug in seeded:
        assert slug in installed, f"population seeds {slug!r} which core_ci does not install"


@pytest.mark.spec("req-dev-validation-product-line-lanes-8")
def test_every_seeded_fixture_declares_grift() -> None:
    """A seed step on a plugin with no GRIFT bundles would pass while importing nothing."""
    from tap_plugins.manifest import load_manifest

    checked = 0
    for step in _record("core_ci")["population"]["steps"]:
        root = plugin_package_dir(step["plugin"])
        if root is None:
            continue
        checked += 1
        assert load_manifest(root).grift, f"core_ci seeds {step['plugin']!r}, which declares no GRIFT bundle"
    if not checked:
        _skip_outside_the_core_ci_lane(
            "no seeded core_ci plugin is installed in this stack; the check runs in the core_ci lane"
        )


@pytest.mark.spec("req-dev-validation-product-line-lanes-8")
@pytest.mark.parametrize("record_name", ["core_ci", "test_all"])
def test_a_plugin_is_listed_after_every_sibling_it_depends_on(record_name) -> None:
    """Sibling plugins are not on PyPI, so a dependent installed FIRST cannot resolve them.

    `uv pip install git+…@<commit>` satisfies a sibling dependency only from what an EARLIER
    profile entry already installed. Get the order wrong and pre-boot dies with uv's message
    about a package registry, naming neither plugin (tap#647: github_core v0.10.0 gained
    git_core and compliance_core; test_all listed compliance_core AFTER github_core and only
    survived because v0.4.0 did not need it). tap#675 tracks making pre-boot say this itself.
    """
    order = [p["slug"] for p in _record(record_name)["install"]["plugins"]]
    position = {slug: i for i, slug in enumerate(order)}
    checked = 0
    for slug, index in position.items():
        closure = _declared_closure(slug)
        if closure is None:
            continue  # not installed in this stack; the lane that installs it does the checking
        checked += 1
        for dep in sorted(closure & position.keys()):
            assert position[dep] < index, (
                f"{record_name}: {slug!r} (index {index}) declares {dep!r} (index {position[dep]}) "
                f"as a plugin dependency, but {dep!r} is listed AFTER it. A sibling plugin is not on "
                f"PyPI, so it must already be installed when its dependent resolves (tap#647)."
            )
    if not checked:
        pytest.skip(f"no {record_name} plugin is installed in this stack; the check runs in its lane")
