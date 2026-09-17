"""Scope is decided below the scan root, never above it (tap#501).

`iter_parsed_sources` used to test excluded-directory names against the ABSOLUTE path,
so the location of the checkout decided what got scanned: a repo under `.claude/`, an
installed plugin under `.venv/`, or anything beneath a directory named `tests` had every
file excluded — and each scanner on top reported a clean result having read nothing.

These tests plant real trees under exactly those locations. They are positive controls:
each asserts files were FOUND, because "nothing flagged" is also what a vacuous walk
returns. See spec-tap-tree-scanner.md req-tap-tree-scanner-scope.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tap import plugin_deps
from tap.source_scan import EmptyScanRootError, default_out_of_scope, is_excluded_dir, iter_parsed_sources


def _package(base: Path, name: str, files: dict[str, str]) -> Path:
    root = base / name
    for rel, body in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return root


def _scanned(roots: list[Path], **kwargs: object) -> set[str]:
    return {p.path.name for p in iter_parsed_sources(roots, **kwargs)}  # type: ignore[arg-type]


# --- the checkout's location never decides scope ------------------------------


@pytest.mark.spec("req-tap-tree-scanner-scope-1")
@pytest.mark.parametrize("above", [".claude/worktrees/wt", ".venv/lib/python3.14/site-packages", "tests", "migrations"])
def test_an_excluded_name_above_the_root_does_not_hide_the_tree(tmp_path: Path, above: str) -> None:
    root = _package(tmp_path / above, "tap_app", {"__init__.py": "", "models.py": "X = 1\n"})
    assert _scanned([root]) == {"__init__.py", "models.py"}


@pytest.mark.spec("req-tap-tree-scanner-scope-1")
def test_an_installed_plugin_under_venv_is_scanned_for_imports(tmp_path: Path) -> None:
    # The measured case: github_core installed in site-packages scanned as 0 of 41 files,
    # so its cross-plugin imports were never observed and never checked against depends_on.
    pkg = _package(
        tmp_path / ".venv/lib/python3.14/site-packages/tap_plugin",
        "samsite",
        {"__init__.py": "", "views.py": "from tap_plugin.github_core.models import Repo\n"},
    )
    assert plugin_deps.scan_observed_imports(pkg, own_slug="samsite") == {"github_core"}


@pytest.mark.spec("req-tap-tree-scanner-scope-1")
def test_skip_sees_the_path_from_the_root_down(tmp_path: Path) -> None:
    root = _package(tmp_path / "tests", "tap_app", {"a.py": "", "tests/test_b.py": "", "migrations/0001.py": ""})
    seen: list[Path] = []

    def record(path: Path) -> bool:
        seen.append(path)
        return default_out_of_scope(path)

    assert _scanned([root], skip=record) == {"a.py"}
    assert all(not p.is_absolute() and p.parts[0] == "tap_app" for p in seen)


# --- exclusion still works where it should --------------------------------------


@pytest.mark.spec("req-tap-tree-scanner-scope-2")
@pytest.mark.parametrize("inside", [".venv", ".claude", "node_modules", "__pycache__"])
def test_an_excluded_dir_inside_the_root_is_still_skipped(tmp_path: Path, inside: str) -> None:
    root = _package(tmp_path, "tap_app", {"keep.py": "", f"{inside}/drop.py": ""})
    assert _scanned([root]) == {"keep.py"}


@pytest.mark.spec("req-tap-tree-scanner-scope-2")
def test_tests_and_migrations_inside_the_root_are_still_out_of_scope(tmp_path: Path) -> None:
    root = _package(tmp_path, "tap_app", {"keep.py": "", "tests/test_x.py": "", "migrations/0001_initial.py": ""})
    assert _scanned([root], skip=default_out_of_scope) == {"keep.py"}


# --- an absolute path is refused, not silently mis-scoped ------------------------


@pytest.mark.spec("req-tap-tree-scanner-scope-3")
def test_is_excluded_dir_refuses_an_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="tap#501"):
        is_excluded_dir(tmp_path / "x.py")


@pytest.mark.spec("req-tap-tree-scanner-scope-3")
def test_default_out_of_scope_refuses_an_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="tap#501"):
        default_out_of_scope(tmp_path / "x.py")


# --- a vacuous walk is an error, not a clean result -------------------------------


@pytest.mark.spec("req-tap-tree-scanner-scope-4")
def test_a_root_with_no_python_raises(tmp_path: Path) -> None:
    root = _package(tmp_path, "tap_app", {"README.md": "no code here"})
    with pytest.raises(EmptyScanRootError):
        list(iter_parsed_sources([root]))


@pytest.mark.spec("req-tap-tree-scanner-scope-4")
def test_a_root_whose_every_file_is_excluded_raises(tmp_path: Path) -> None:
    root = _package(tmp_path, "tap_app", {"__pycache__/a.py": ""})
    with pytest.raises(EmptyScanRootError):
        list(iter_parsed_sources([root]))


@pytest.mark.spec("req-tap-tree-scanner-scope-4")
def test_a_root_where_every_file_fails_to_parse_raises(tmp_path: Path) -> None:
    # Codex on #511: counting candidates before parsing let an all-syntax-error root return clean.
    root = _package(tmp_path, "tap_app", {"broken.py": "def broken(\n"})
    with pytest.raises(EmptyScanRootError, match="failed to read or parse"):
        list(iter_parsed_sources([root]))


def test_one_unparseable_file_among_good_ones_is_tolerated(tmp_path: Path) -> None:
    root = _package(tmp_path, "tap_app", {"good.py": "X = 1\n", "broken.py": "def broken(\n"})
    assert _scanned([root]) == {"good.py"}


@pytest.mark.spec("req-tap-tree-scanner-scope-4")
def test_a_missing_root_raises(tmp_path: Path) -> None:
    with pytest.raises(EmptyScanRootError):
        list(iter_parsed_sources([tmp_path / "nope"]))


@pytest.mark.spec("req-tap-tree-scanner-scope-4")
def test_a_root_the_scanner_skips_entirely_is_not_an_error(tmp_path: Path) -> None:
    # Dropping every file via `skip` is the scanner's declared decision, not a vacuum.
    root = _package(tmp_path, "tap_app", {"tests/test_only.py": ""})
    assert _scanned([root], skip=default_out_of_scope) == set()
