"""The lane runner: core + every installed plugin's shipped tests, reported by owner.

Why a runner and not one ``pytest`` line (tap#369): pytest's directory collectors prune an
explicitly named path that sits under an ignored or dot directory once the repo root is ALSO
an argument, so ``pytest <plugin tests dirs> /app`` silently collects the core walk alone —
the exact false green this module removes. The core walk and the plugin suites therefore run
as separate invocations, each owning its paths, and the summary says per owner what was
collected, passed, failed, skipped and deselected. Every count is read from pytest's own
summary line; nothing here decides a suite is fine because a file exists.

Rules (req-dev-validation-collection-complete-4, req-dev-validation-bom-lane-1):

* EXPECTED membership comes from the lane's boot record (``--record``); a plugin the record
  installs that discovery did not surface is an unexplained omission → red.
* A plugin whose ``tests/`` holds test modules and that collects 0 → red. A plugin that ships
  no tests says so by shape and is printed, never silent.
* A suite that collected N and executed 0 (everything skipped/deselected) → red; ``--require``
  names suites that must EXECUTE (the Gryphon corpus in the BOM lane).
* pytest failures propagate as the exit code.

Usage inside the container::

    uv run python -m tap.lane_run --root /app --record boot/core_ci.boot.json
    uv run python -m tap.lane_run --root /app --record boot/test_all.boot.json --require gryphon_playground
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from tap.plugin_testing import (
    PluginSuite,
    expected_plugin_slugs,
    installed_plugin_slugs,
    membership_omissions,
    plugin_suites,
)

_SUMMARY_RE = re.compile(r"(\d+) (passed|failed|error|errors|skipped|deselected|xfailed|xpassed|warnings?)")
# Serial pytest prints "collected N items"; xdist prints "N workers [M items]" and, in -q,
# "gwK [M]" — three shapes for one number. A count that no shape matched is DERIVED from the
# summary line (executed + skipped + deselected) rather than left at 0, because a zero here is
# a red ("collects nothing") and must never be an artefact of the reporter's format.
_COLLECTED_RE = re.compile(r"(\d+) tests? collected|(no) tests collected|collected (\d+) items?|\[(\d+) items?\]")


@dataclass
class OwnerResult:
    """One owner's counts, read from pytest's own summary line."""

    owner: str
    paths: list[str]
    collected: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    deselected: int = 0
    xfailed: int = 0
    xpassed: int = 0
    returncode: int = 0
    has_test_files: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def executed(self) -> int:
        return self.passed + self.failed + self.errors + self.xfailed + self.xpassed


def parse_summary(output: str) -> dict[str, int]:
    """Counts from pytest's final ``=== N passed, M skipped ... ===`` line (and ``collected N``)."""
    counts: dict[str, int] = {}
    tail = output.strip().splitlines()
    for line in reversed(tail):
        if line.startswith("=") and (
            "passed" in line
            or "failed" in line
            or "error" in line
            or "no tests ran" in line
            or "skipped" in line
            or "deselected" in line
        ):
            for n, key in _SUMMARY_RE.findall(line):
                key = {"errors": "error", "warning": "warnings"}.get(key, key)
                counts[key] = counts.get(key, 0) + int(n)
            break
    for line in tail:
        m = _COLLECTED_RE.search(line)
        if m:
            if m.group(2) == "no":
                counts["collected"] = 0
            else:
                counts["collected"] = int(m.group(1) or m.group(3) or m.group(4))
            break
    return counts


# A pytest argument this runner is willing to pass on: an option (``-n``, ``--tb=short``,
# ``-k``) or an option's value. Everything else must be an existing path, checked at the sink.
_PYTEST_OPT_RE = re.compile(r"^-{1,2}[A-Za-z0-9][A-Za-z0-9_.=:-]*$|^[A-Za-z0-9_.:\[\]-]+$")


def _checked_argv(paths: list[str], extra: list[str]) -> list[str]:
    """The pytest argv, validated at the sink.

    Paths come from the import system (``plugin_suites``) and the lane's root; extra args come
    from the invoking lane. Neither is user input in the web sense, but this is the one place
    they become a subprocess argv, so this is where they are checked: every path must exist,
    and every extra token must look like an option or an option value. No shell, ever — the
    argv is a list and ``shell=False`` is the default.
    """
    for path in paths:
        if not Path(path).exists():
            raise ValueError(f"lane path does not exist: {path}")
    for token in extra:
        if not _PYTEST_OPT_RE.match(token) and not Path(token).exists():
            raise ValueError(f"refusing to pass an unrecognised pytest argument: {token!r}")
    return ["uv", "run", "pytest", *extra, *paths]


def _run_pytest(paths: list[str], extra: list[str], env: dict[str, str]) -> tuple[int, str]:
    cmd = _checked_argv(paths, extra)
    # NOSONAR (S8705) — the taint reaches this call from argparse, and the sanitiser is one
    # frame up: `_checked_argv` refuses any path that does not exist and any token that is
    # neither a pytest option nor an existing path, and the argv is a list with shell=False.
    # Restructured rather than suppressed first (the call no longer takes a free-form string);
    # the finding that remains is the analyzer not following the sink check across the call.
    proc = subprocess.run(  # NOSONAR (S8705)
        cmd, text=True, capture_output=True, env=env, check=False, shell=False
    )  # noqa: S603 — argv list, validated at the sink by _checked_argv
    out = proc.stdout + proc.stderr
    sys.stdout.write(out)
    return proc.returncode, out


def run_owner(result: OwnerResult, extra: list[str], env: dict[str, str]) -> OwnerResult:
    rc, out = _run_pytest(result.paths, extra, env)
    counts = parse_summary(out)
    result.returncode = rc
    result.passed = counts.get("passed", 0)
    result.failed = counts.get("failed", 0)
    result.errors = counts.get("error", 0)
    result.skipped = counts.get("skipped", 0)
    result.deselected = counts.get("deselected", 0)
    result.xfailed = counts.get("xfailed", 0)
    result.xpassed = counts.get("xpassed", 0)
    # The reported count, or what the summary line proves ran — never 0 by parse failure.
    result.collected = max(counts.get("collected", 0), result.executed + result.skipped + result.deselected)
    if rc == 5:  # pytest: no tests collected
        result.returncode = 0
        result.collected = 0
    return result


def judge(results: list[OwnerResult], omissions: list[str], required: list[str]) -> list[str]:
    """The red reasons, in words. Empty means the lane is honest and green."""
    reasons: list[str] = []
    if omissions:
        reasons.append(f"plugins the record installs but discovery did not surface: {', '.join(omissions)}")
    by_owner = {r.owner: r for r in results}
    for r in results:
        if r.returncode not in (0, 5):
            reasons.append(f"{r.owner}: pytest exit {r.returncode} ({r.failed} failed, {r.errors} errors)")
        if r.has_test_files and r.collected == 0:
            reasons.append(
                f"{r.owner}: holds test files but collected 0 — a shipped suite that collects nothing is a red, not a skip"
            )
        elif r.collected > 0 and r.executed == 0:
            reasons.append(
                f"{r.owner}: collected {r.collected}, executed 0 ({r.skipped} skipped, {r.deselected} deselected) — collection is not execution"
            )
    for slug in required:
        needed = by_owner.get(slug)
        if needed is None:
            reasons.append(f"required suite {slug} is not installed in this profile")
        elif needed.executed == 0:
            reasons.append(f"required suite {slug} executed 0 tests")
    return reasons


def render_summary(results: list[OwnerResult], omissions: list[str], reasons: list[str], record: Path | None) -> str:
    lines = ["## Lane report — by owner", ""]
    if record is not None:
        lines.append(
            f"Expected membership from `{record}`; discovery: {', '.join(installed_plugin_slugs()) or '(none)'}"
        )
        lines.append("")
    lines.append("| owner | collected | passed | failed | errors | skipped | deselected | executed | note |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for r in results:
        note = "; ".join(r.notes)
        lines.append(
            f"| {r.owner} | {r.collected} | {r.passed} | {r.failed} | {r.errors} | {r.skipped} | {r.deselected} | {r.executed} | {note} |"
        )
    if omissions:
        lines.append("")
        lines.append(f"**Unexplained omissions:** {', '.join(omissions)}")
    lines.append("")
    lines.append("**Verdict:** " + ("green" if not reasons else "RED — " + " | ".join(reasons)))
    return "\n".join(lines) + "\n"


def build_plan(root: Path, suites: list[PluginSuite], exclude: set[str]) -> tuple[OwnerResult, list[OwnerResult]]:
    """The core walk (root minus every plugin dir under it) and one owner per plugin suite."""
    core = OwnerResult(owner="core", paths=[str(root)])
    owners: list[OwnerResult] = []
    for st in suites:
        if st.slug in exclude:
            continue
        if st.tests_dir is None:
            owners.append(OwnerResult(owner=st.slug, paths=[], has_test_files=False, notes=["ships no tests/ dir"]))
            continue
        notes = [] if st.has_test_files else ["ships no tests (empty package)"]
        owners.append(
            OwnerResult(owner=st.slug, paths=[str(st.tests_dir)], has_test_files=st.has_test_files, notes=notes)
        )
        # A plugin dir under the root (an editable or fixture install) is owned by its plugin
        # run; ignore it in the core walk so nothing is collected twice.
        try:
            st.tests_dir.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        core.paths.append(f"--ignore={st.tests_dir}")
    return core, owners


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tap.lane_run", description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="the core walk root (default: cwd)")
    parser.add_argument("--record", type=Path, help="boot record whose plugins are EXPECTED to be discovered")
    parser.add_argument(
        "--require", action="append", default=[], help="slug whose suite must execute > 0 tests (repeatable)"
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="slug to leave out of this run (repeatable; e.g. the corpus on a fast lane)",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path(os.environ["GITHUB_STEP_SUMMARY"]) if os.environ.get("GITHUB_STEP_SUMMARY") else None,
    )
    parser.add_argument("--no-core", action="store_true", help="skip the core walk (plugin suites only)")
    parser.add_argument("pytest_args", nargs="*", help="extra pytest args after `--` (e.g. -n auto)")
    args = parser.parse_args(argv)
    extra = [a for a in args.pytest_args if a != "--"]
    env = dict(os.environ)

    suites = plugin_suites()
    omissions = (
        membership_omissions(expected_plugin_slugs(args.record), installed_plugin_slugs()) if args.record else []
    )
    core, owners = build_plan(args.root, suites, set(args.exclude))
    results: list[OwnerResult] = []
    if not args.no_core:
        results.append(run_owner(core, extra, env))
    for owner in owners:
        if owner.paths:
            results.append(run_owner(owner, extra, env))
        else:
            results.append(owner)
    reasons = judge(results, omissions, args.require)
    text = render_summary(results, omissions, reasons, args.record)
    sys.stdout.write("\n" + text)
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(text)
    return 1 if reasons else 0


if __name__ == "__main__":
    raise SystemExit(main())
