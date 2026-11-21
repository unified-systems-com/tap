"""Which core tests read the specs: recorded on every full lane, so the specs tier can run only those.

A diff that touches nothing but specs (the `specs` tier of scripts/change-tier) cannot red a test
that never reads a spec. So on that tier the `core_ci` line runs only the test files that do, and
skips the rest of the core walk and the plugin suites (req-dev-validation-product-line-lanes-7).

That shortcut is only as good as the list, and a hand-kept list of "tests that read specs" goes
stale the day someone adds one. So the list is MEASURED, not kept: every full `core_ci` line runs
the core walk with this module loaded as a pytest plugin, which records every file a test opens or
lists under a `specs/` directory of the repository, and then checks the committed list holds every
file it saw. A PR that adds a new spec reader fails on that PR, with the fix printed.

What counts as a read, and who it is charged to:

* `open()`, `os.listdir()` and `os.scandir()` of a path under `<rootdir>`, with `specs` as one of
  its directory parts. Paths outside the repository (a test's own temporary `specs/`) are not
  the repository's specs, and a spec edit cannot reach them.
* A read inside a test (setup, call, teardown) is charged to the test's file. A read while pytest
  imports or collects a module (parametrizing over spec rows) is charged to that module. A read
  inside a fixture is charged to every test that requests the fixture, because only the first of
  them triggers a session-scoped fixture's setup on a given worker.
* Reads by a subprocess are invisible to the audit hook. None of the core suite's subprocesses
  read the specs today (measured 2026-11-21 over every subprocess the suite starts); a test that
  starts one that does must be listed by hand, and `--check` cannot catch the omission.

Usage::

    TAP_SPEC_READ_AUDIT=<dir> pytest -p tap.spec_read_audit ...   # record (one JSON per worker)
    python -m tap.spec_read_audit --check <dir>                   # every reader listed?
    python -m tap.spec_read_audit --write <dir>                   # regenerate the list
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

LIST_PATH = Path(__file__).resolve().parent / "spec_reader_tests.txt"
ENV = "TAP_SPEC_READ_AUDIT"
_EVENTS = frozenset({"open", "os.listdir", "os.scandir"})  # "open" covers io.open and os.open
_DIR = "<directory>"

_HEADER = """\
# The core test files that read the specs (tap/spec_read_audit.py). GENERATED, do not hand-edit:
#   python -m tap.spec_read_audit --write <dir of a recorded full core walk>
# On the specs tier the core_ci line runs exactly these (req-dev-validation-product-line-lanes-7).
"""


def is_spec_path(path: str, root: str) -> bool:
    """A path inside the repository with `specs` as one of its directories."""
    if not path.startswith(root.rstrip("/") + "/"):
        return False
    rel = path[len(root.rstrip("/")) + 1 :].split("/")
    return "specs" in rel[:-1] or (rel[-1] == "specs")


class _Recorder:
    def __init__(self, root: str) -> None:
        self.root = root
        # A test file, a module being collected, "fixture:<name>", DIR while pytest walks a
        # directory, or None outside every window (configure, conftest import, session hooks).
        self.current: str | None = None
        self.files: set[str] = set()
        self.unattributed: set[str] = set()  # spec paths read where no test could be charged
        self.fixtures: set[str] = set()
        self.uses: dict[str, set[str]] = {}  # test file -> every fixture its tests request

    def hook(self, event: str, args: tuple[Any, ...]) -> None:
        if event not in _EVENTS or not args or args[0] is None:
            return
        try:
            path = os.path.abspath(os.fsdecode(args[0]))
        except (TypeError, ValueError):
            return  # a file descriptor, not a path
        if not is_spec_path(path, self.root):
            return
        if self.current is None or self.current == _DIR:
            # pytest listing a directory is it walking the tree; anything else here (a conftest or
            # plugin hook reading a spec) feeds tests the audit cannot name, so it is recorded and
            # `--check` refuses the run rather than narrow the specs tier past it.
            if not (self.current == _DIR and event != "open"):
                self.unattributed.add(path[len(self.root.rstrip("/")) + 1 :])
            return
        if self.current.startswith("fixture:"):
            self.fixtures.add(self.current.removeprefix("fixture:"))
        else:
            self.files.add(self.current)


_REC: _Recorder | None = None


def _install() -> None:
    """Install at IMPORT, not at pytest_configure: `-p tap.spec_read_audit` is imported before any
    conftest.py, so a conftest that reads a spec at import is seen, not missed."""
    global _REC
    if not os.environ.get(ENV) or _REC is not None:
        return
    _REC = _Recorder(os.getcwd())
    sys.addaudithook(lambda event, args: _REC.hook(event, args) if _REC is not None else None)


_install()


def _file_of(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def pytest_configure(config: pytest.Config) -> None:
    if _REC is not None:
        _REC.root = str(config.rootpath)


def pytest_collectstart(collector: pytest.Collector) -> None:
    if _REC is not None:
        # Only a module's own collection is charged; a directory collector listing `specs/` is
        # pytest walking the tree, not a test reading a spec.
        module = _file_of(collector.nodeid)
        _REC.current = module if module.endswith(".py") else _DIR


def pytest_collectreport(report: pytest.CollectReport) -> None:
    if _REC is not None:
        _REC.current = None


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(fixturedef: pytest.FixtureDef[Any], request: pytest.FixtureRequest) -> Generator[None, Any, Any]:
    if _REC is None:
        return (yield)
    outer, _REC.current = _REC.current, f"fixture:{fixturedef.argname}"
    try:
        return (yield)
    finally:
        _REC.current = outer


def pytest_runtest_logstart(nodeid: str, location: tuple[str, int | None, str]) -> None:
    if _REC is not None:
        _REC.current = _file_of(nodeid)


def pytest_runtest_logfinish(nodeid: str, location: tuple[str, int | None, str]) -> None:
    if _REC is not None:
        _REC.current = None


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if _REC is not None:
        for item in items:
            _REC.uses.setdefault(_file_of(item.nodeid), set()).update(getattr(item, "fixturenames", ()))


def pytest_sessionfinish(session: pytest.Session) -> None:
    if _REC is None:
        return
    files = set(_REC.files)
    for test_file, names in _REC.uses.items():
        if names & _REC.fixtures:
            files.add(test_file)
    out = Path(os.environ[ENV])
    out.mkdir(parents=True, exist_ok=True)
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    record = {"readers": sorted(files), "unattributed": sorted(_REC.unattributed)}
    (out / f"spec-readers-{worker}.json").write_text(json.dumps(record), encoding="utf-8")


def observed(record_dir: Path) -> tuple[set[str], set[str]]:
    """The union of every worker's recorded reader files, and of its unattributable spec reads."""
    found = sorted(record_dir.glob("spec-readers-*.json"))
    if not found:
        raise SystemExit(f"no spec-readers-*.json under {record_dir}: the audit did not run")
    records = [json.loads(path.read_text(encoding="utf-8")) for path in found]
    return {f for r in records for f in r["readers"]}, {f for r in records for f in r["unattributed"]}


def listed(path: Path = LIST_PATH) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tap.spec_read_audit", description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", type=Path, metavar="DIR", help="fail if a recorded reader is not listed")
    mode.add_argument("--write", type=Path, metavar="DIR", help="regenerate the list from a recorded run")
    parser.add_argument("--list", type=Path, default=LIST_PATH, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.write is not None:
        args.list.write_text(_HEADER + "".join(f"{f}\n" for f in sorted(observed(args.write)[0])), encoding="utf-8")
        return 0
    (seen, unattributed), have = observed(args.check), set(listed(args.list))
    if unattributed:
        sys.stderr.write(
            "These spec files were read outside every test, collection and fixture (a conftest.py, a "
            "pytest plugin or a session hook), so no test file can be charged and the specs tier's "
            "narrowing cannot be trusted:\n" + "".join(f"  {f}\n" for f in sorted(unattributed))
            + "Move the read into a fixture the dependent tests request.\n"
        )
        return 1
    missing, stale = sorted(seen - have), sorted(have - seen)
    if stale:
        # Not a failure: a test skipped on this runner may still read the specs elsewhere.
        sys.stderr.write("listed but not observed reading the specs on this run: " + ", ".join(stale) + "\n")
    if missing:
        sys.stderr.write(
            "These test files read the specs but are not in tap/spec_reader_tests.txt, so a specs-tier PR "
            "would skip them:\n" + "".join(f"  {f}\n" for f in missing)
            + f"Add them (or regenerate: python -m tap.spec_read_audit --write {args.check}).\n"
        )
        return 1
    print(f"spec readers: {len(seen)} observed, all listed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
