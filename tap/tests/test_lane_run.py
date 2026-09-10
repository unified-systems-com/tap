"""The lane runner and the seam it derives from (tap#369, Codex's five additions).

Spec: specs/spec-dev-validation.md (req-dev-validation-collection-complete-4,
req-dev-validation-bom-lane-1, req-dev-validation-product-line-lanes-8).

What is proven here, without booting anything: expected membership is derived from the boot
record and an omission is red; a suite with test files that collects nothing is red; a suite
that collects but executes nothing is red; a required suite must execute; the core walk ignores
every plugin dir under the root so wheel and editable installs alike are collected once, by
their owner; pytest's summary line is parsed faithfully.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tap import lane_run
from tap.lane_run import OwnerResult, build_plan, judge, parse_summary, render_summary
from tap.plugin_testing import PluginSuite, expected_plugin_slugs, membership_omissions


def _record(tmp_path: Path, slugs: list[str], disabled: tuple[str, ...] = ()) -> Path:
    rec = {
        "version": 1,
        "install": {
            "plugins": [
                {
                    "slug": s,
                    "enabled": s not in disabled,
                    "source": {"type": "git", "url": f"https://x/{s}", "rev": "v0"},
                }
                for s in slugs
            ]
        },
    }
    p = tmp_path / "lane.boot.json"
    p.write_text(json.dumps(rec))
    return p


def test_expected_membership_is_the_records(tmp_path: Path) -> None:
    rec = _record(tmp_path, ["a_core", "b_core", "c_off"], disabled=("c_off",))
    assert expected_plugin_slugs(rec) == ["a_core", "b_core"]


def test_dropping_one_expected_plugin_from_discovery_is_an_omission(tmp_path: Path) -> None:
    """Codex #2: a discovery helper that silently loses a plugin turns the lane red."""
    rec = _record(tmp_path, ["a_core", "b_core"])
    expected = expected_plugin_slugs(rec)
    assert membership_omissions(expected, ["a_core", "b_core"]) == []
    assert membership_omissions(expected, ["a_core"]) == ["b_core"]
    reasons = judge([], omissions=["b_core"], required=[])
    assert reasons and "b_core" in reasons[0]


def test_parse_summary_reads_the_xdist_shapes_too() -> None:
    """xdist prints "4 workers [N items]", not "collected N items" — a count the reporter's
    format hid read as "collects nothing", the lane's own red (observed run 34436583758)."""
    out = "4 workers [3476 items]\nscheduling tests via LoadScheduling\n=== 3405 passed, 70 skipped in 300s ===\n"
    assert parse_summary(out)["collected"] == 3476


def test_parse_summary_reads_pytests_own_line() -> None:
    out = "collected 12 items\n...\n=== 9 passed, 2 skipped, 1 deselected, 1 xfailed in 3.2s ===\n"
    c = parse_summary(out)
    assert c == {"collected": 12, "passed": 9, "skipped": 2, "deselected": 1, "xfailed": 1}
    assert parse_summary("no tests collected\n=== no tests ran in 0.1s ===\n")["collected"] == 0
    c2 = parse_summary("=== 1 failed, 3 passed, 2 errors in 1s ===\n")
    assert c2["failed"] == 1 and c2["passed"] == 3 and c2["error"] == 2


def test_collected_is_never_zero_when_the_summary_proves_tests_ran(monkeypatch: pytest.MonkeyPatch) -> None:
    """A parse miss must not manufacture the "collects nothing" red: the count falls back to
    what the summary line proves (executed + skipped + deselected)."""
    monkeypatch.setattr(lane_run, "_run_pytest", lambda paths, extra, env: (0, "=== 12 passed, 3 skipped in 1s ===\n"))
    r = lane_run.run_owner(OwnerResult(owner="x_core", paths=["/p"]), [], {})
    assert r.executed == 12 and r.collected == 15
    assert judge([r], [], []) == []


def test_test_files_but_zero_collected_is_red() -> None:
    r = OwnerResult(owner="x_core", paths=["/p"], collected=0, has_test_files=True)
    assert any("collected 0" in s for s in judge([r], [], []))
    empty = OwnerResult(
        owner="y_core", paths=["/p"], collected=0, has_test_files=False, notes=["ships no tests (empty package)"]
    )
    assert judge([empty], [], []) == []


def test_collected_but_nothing_executed_is_red() -> None:
    """Codex #3: 248 collected and 248 skipped is not evidence the corpus ran."""
    r = OwnerResult(owner="gryphon_playground", paths=["/p"], collected=248, skipped=248)
    reasons = judge([r], [], [])
    assert reasons and "executed 0" in reasons[0]
    ran = OwnerResult(owner="gryphon_playground", paths=["/p"], collected=248, passed=240, skipped=8)
    assert judge([ran], [], []) == []


def test_required_suite_must_execute() -> None:
    """Codex #4: the Gryphon corpus is named and must have executed."""
    assert any("not installed" in s for s in judge([], [], ["gryphon_playground"]))
    r = OwnerResult(owner="gryphon_playground", paths=["/p"], collected=5, skipped=5)
    assert any("required suite gryphon_playground" in s for s in judge([r], [], ["gryphon_playground"]))


def test_plan_owns_each_plugin_dir_once(tmp_path: Path) -> None:
    """Codex #5: an editable/fixture dir under the root is ignored by the core walk and run by its owner;
    a wheel dir outside the root is simply its owner's; nothing is collected twice."""
    root = tmp_path / "app"
    editable = root / "_dev-plugins" / "x" / "tap_plugin" / "x_core" / "tests"
    fixture = root / "tap_plugins" / "tests" / "fixtures" / "s" / "tap_plugin" / "s" / "tests"
    wheel = tmp_path / "venv" / "site-packages" / "tap_plugin" / "w_core" / "tests"
    for d in (editable, fixture, wheel):
        d.mkdir(parents=True)
        (d / "test_it.py").write_text("def test_it():\n    assert True\n")
    suites = [
        PluginSuite("x_core", editable, True),
        PluginSuite("s", fixture, True),
        PluginSuite("w_core", wheel, True),
        PluginSuite("n_core", None, False),
    ]
    core, owners = build_plan(root, suites, exclude=set())
    assert core.paths[0] == str(root)
    ignores = set(core.paths[1:])
    assert ignores == {f"--ignore={editable}", f"--ignore={fixture}"}  # under the root → ignored there
    assert [o.owner for o in owners] == ["x_core", "s", "w_core", "n_core"]
    assert owners[2].paths == [str(wheel)] and owners[3].paths == [] and owners[3].has_test_files is False
    core2, owners2 = build_plan(root, suites, exclude={"w_core"})
    assert [o.owner for o in owners2] == ["x_core", "s", "n_core"]


def test_summary_renders_verdict(tmp_path: Path) -> None:
    r = OwnerResult(owner="core", paths=["/app"], collected=10, passed=10)
    text = render_summary([r], [], [], None)
    assert "| core | 10 | 10 |" in text and "**Verdict:** green" in text
    red = render_summary([r], ["b_core"], ["plugins the record installs but discovery did not surface: b_core"], None)
    assert "RED" in red and "b_core" in red


def test_focused_invocation_is_untouched(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A focused pytest run (one plugin, one file) never goes through the runner — the runner only
    orchestrates whole lanes; `--exclude`/`--no-core` narrow it, extra args pass to pytest verbatim."""
    seen: list[list[str]] = []

    def fake_run(paths: list[str], extra: list[str], env: dict[str, str]) -> tuple[int, str]:
        seen.append([*extra, *paths])
        return 0, "collected 1 items\n=== 1 passed in 0.1s ===\n"

    monkeypatch.setattr(lane_run, "_run_pytest", fake_run)
    monkeypatch.setattr(lane_run, "plugin_suites", lambda: [PluginSuite("w_core", tmp_path / "w", True)])
    (tmp_path / "w").mkdir()
    monkeypatch.setattr(lane_run, "installed_plugin_slugs", lambda: ["w_core"])
    rc = lane_run.main(["--root", str(tmp_path / "app"), "--no-core", "--", "-n", "2", "-k", "smoke"])
    assert rc == 0
    assert seen == [["-n", "2", "-k", "smoke", str(tmp_path / "w")]]


# --- The wheel-install skip guard (tap#369, observed run 34436583758) --------------------------


def test_source_root_is_the_tree_that_owns_the_plugin(tmp_path: Path) -> None:
    """A checkout: the ancestor holding pyproject.toml AND tap_plugin/<slug>/ is the source root."""
    from tap.plugin_testing import find_plugin_source_root

    root = tmp_path / "repo"
    tests = root / "tap_plugin" / "roscale" / "tests"
    tests.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='x'\n")
    test_file = tests / "test_roscale_manifest.py"
    test_file.write_text("")
    assert find_plugin_source_root(str(test_file)) == root


def test_source_root_is_none_under_a_wheel_install(tmp_path: Path) -> None:
    """A wheel: site-packages holds the package but no pyproject; the walk reaches the HARNESS's
    pyproject, which does not own tap_plugin/<slug>/ — so the guard returns None and the plugin's
    structure tests skip instead of validating a directory that is not the plugin."""
    from tap.plugin_testing import find_plugin_source_root

    harness = tmp_path / "app"
    site = harness / ".venv" / "lib" / "python3.14" / "site-packages"
    tests = site / "tap_plugin" / "roscale" / "tests"
    tests.mkdir(parents=True)
    (harness / "pyproject.toml").write_text("[project]\nname='tap'\n")  # the harness, not the plugin
    test_file = tests / "test_roscale_manifest.py"
    test_file.write_text("")
    assert find_plugin_source_root(str(test_file)) is None


def test_source_root_is_none_when_a_wheel_dropped_a_pyproject_beside_the_packages(tmp_path: Path) -> None:
    from tap.plugin_testing import find_plugin_source_root

    site = tmp_path / "site-packages"
    tests = site / "tap_plugin" / "roscale" / "tests"
    tests.mkdir(parents=True)
    (site / "pyproject.toml").write_text("[project]\nname='stray'\n")
    test_file = tests / "test_roscale_manifest.py"
    test_file.write_text("")
    assert find_plugin_source_root(str(test_file)) is None


# --- Sink validation (Sonar S8705/S8707: the argv and the record path are checked here) --------


def test_argv_refuses_a_path_that_does_not_exist(tmp_path: Path) -> None:
    from tap.lane_run import _checked_args

    with pytest.raises(ValueError, match="does not exist"):
        _checked_args([str(tmp_path / "nope")], [])


def test_argv_refuses_an_unrecognised_argument(tmp_path: Path) -> None:
    from tap.lane_run import _checked_args

    real = tmp_path / "tests"
    real.mkdir()
    with pytest.raises(ValueError, match="unrecognised pytest argument"):
        _checked_args([str(real)], ["; rm -rf /"])
    # The helper returns the validated TAIL; the command is a literal at the call site.
    assert _checked_args([str(real)], ["-n", "auto", "--tb=short", "-k", "smoke"])[:2] == ["-n", "auto"]


def test_expected_plugin_slugs_refuses_a_non_record(tmp_path: Path) -> None:
    from tap.plugin_testing import expected_plugin_slugs

    stray = tmp_path / "notes.txt"
    stray.write_text("{}")
    with pytest.raises(ValueError, match="not a boot record"):
        expected_plugin_slugs(stray)
    with pytest.raises(ValueError, match="not a boot record"):
        expected_plugin_slugs(tmp_path / "missing.boot.json")


def test_argv_accepts_an_option_carrying_a_real_path(tmp_path: Path) -> None:
    """`--ignore=<dir>` is how the core walk leaves each plugin dir to its owner: the value is a
    path and is checked as one; a value that does not exist is refused (observed run 34444117508,
    where the sink check read the whole token as a path and the lane died before pytest started)."""
    from tap.lane_run import _checked_args

    real = tmp_path / "tests"
    real.mkdir()
    args = _checked_args([str(tmp_path), f"--ignore={real}"], ["-n", "auto"])
    assert args == ["-n", "auto", str(tmp_path), f"--ignore={real}"]
    with pytest.raises(ValueError, match="lane path does not exist"):
        _checked_args([str(tmp_path), f"--ignore={tmp_path / 'gone'}"], [])
