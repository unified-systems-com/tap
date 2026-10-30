"""Which installed plugins a core change can reach (tap#1092).

Spec: specs/spec-dev-validation.md (req-dev-validation-suite-tiers-8).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tap.impacted_plugins import PluginReach, impacted, is_inert, module_of, scan_reach


def _plugin(tmp_path: Path, source: str, tests: str = "") -> Path:
    pkg = tmp_path / "tap_plugin" / "demo_core"
    (pkg / "tests").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "code.py").write_text(source)
    (pkg / "tests" / "test_demo.py").write_text(tests or "def test_x():\n    pass\n")
    return pkg


@pytest.mark.spec("req-dev-validation-suite-tiers-8")
def test_the_scan_reads_imports_from_source_and_tests_and_the_declared_pins(tmp_path: Path) -> None:
    pkg = _plugin(
        tmp_path,
        "from tap_grid.gryphon import executor\nimport tap_web.views\nfrom tap_plugin.other import x\nfrom tap.lane_run import run\nfrom tap import pytest_lock\n",
        'from tap_viz import runtime\nPINS_CORE_SURFACES = ("tap_viz/static", "tap_web/templates")\ndef test_x():\n    pass\n',
    )
    reach = scan_reach("demo_core", pkg)
    assert reach.imported_apps == {"tap_grid", "tap_web", "tap_viz"}  # tap_plugin is not core
    assert {"tap.lane_run", "tap.pytest_lock"} <= reach.imported_tap_modules
    assert reach.declared_surfaces == ("tap_viz/static", "tap_web/templates")


@pytest.mark.spec("req-dev-validation-suite-tiers-8")
def test_a_changed_core_file_reaches_importers_and_declared_pins_only() -> None:
    importer = PluginReach("imp_core", frozenset({"tap_grid"}), frozenset({"tap.lane_run"}), ())
    pinner = PluginReach("pin_core", frozenset(), frozenset(), ("tap_viz/static", "tap_web/templates/page"))
    other = PluginReach("other_core", frozenset({"tap_auth"}), frozenset(), ())
    reaches = [importer, pinner, other]

    grid = impacted(["tap_grid/gryphon/executor.py"], reaches)
    assert set(grid) == {"imp_core"} and "imports tap_grid" in grid["imp_core"].reasons[0]

    # the declared pin has no import edge at all, and selects on a path prefix (not a substring)
    viz = impacted(["tap_viz/static/tap_viz/runtime.js", "tap_web/templates/page/x.html"], reaches)
    assert set(viz) == {"pin_core"} and "pins tap_viz/static" in viz["pin_core"].reasons[0]
    assert impacted(["tap_viz/staticfiles/x.js"], reaches) == {}

    # the shared `tap` package is by MODULE: lane_run reaches its importer, an unrelated module reaches nobody
    assert set(impacted(["tap/lane_run.py"], reaches)) == {"imp_core"}
    assert impacted(["tap/other_module.py"], reaches) == {}


@pytest.mark.spec("req-dev-validation-suite-tiers-8")
def test_inert_paths_select_nothing() -> None:
    reach = PluginReach("imp_core", frozenset({"tap_grid"}), frozenset(), ("tap_viz/static",))
    paths = [
        "tap_grid/tests/test_x.py",
        "tap_grid/specs/spec-x.md",
        "docs/misc/a.md",
        "tap_grid/README.md",
        "tap/skills/run-tests/SKILL.md",
    ]
    assert all(is_inert(p) for p in paths)
    assert impacted(paths, [reach]) == {}


@pytest.mark.spec("req-dev-validation-suite-tiers-8")
def test_module_of_maps_paths_to_dotted_modules() -> None:
    assert module_of("tap/lane_run.py") == "tap.lane_run"
    assert module_of("tap_grid/gryphon/__init__.py") == "tap_grid.gryphon"
    assert module_of("tap_viz/static/a.js") is None
