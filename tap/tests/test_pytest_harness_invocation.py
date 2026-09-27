"""Invocation-independence guard for the test harness (req-tap-test-fixtures-4).

The harness fixtures (`default_caller_context` et al.) load as a real pytest
plugin via `-p tap.pytest_harness` in the configfile's addopts, precisely so
they arrive in EVERY invocation mode that reads this repo's config. The mode that
matters — and the one that broke on 2026-08-09 when pytest 9.1 stopped loading
rootdir conftests for package args — is ``pytest --pyargs tap_plugin.<slug>``:
plugin-ci lane 2's exact invocation, and the documented completion check for
evicted plugins. Without the harness, every plugin DB test dies at the service
boundary with ``MissingActor`` while the same files pass by path.

This guard runs that real invocation in a subprocess and asserts the harness is
visible. Two arms, because a probe that reads nothing exits clean (the lesson
this repo keeps re-learning — the worktree-unmounted audit, the ALLOWED_HOSTS
throttle probe): the negative arm blanks ``addopts`` with ``-o addopts=`` —
removing the ``-p tap.pytest_harness`` carrier exactly as a config regression
would — and asserts the SAME probe then reports absence. (A CLI
``-p no:tap.pytest_harness`` cannot serve as the control: addopts are processed
first, so the plugin is already registered by the time the ``no:`` block is
seen.) A probe that cannot detect the broken state proves nothing by passing.

Probed against ``tap_plugin.grid_fixtures`` — the one plugin installed in every
dev/test tier (core_dev upward). Skips, rather than false-greens, where it is
absent.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from tap.plugin_testing import installed_plugin_slugs

_PROBE_PACKAGE = "tap_plugin.grid_fixtures"
_HARNESS_FIXTURE = "default_caller_context"
_SUBPROCESS_TIMEOUT = 120


def _pyargs_fixture_listing(*extra_args: str) -> str:
    """Run `pytest --pyargs <probe> --fixtures` in a subprocess, return stdout.

    ``--fixtures`` collects (so a plugin-loading regression surfaces) but runs no
    tests — no test database is created, keeping the guard cheap. ``-p no:xdist``
    and ``-p no:cacheprovider`` keep the subprocess minimal and side-effect free.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--pyargs",
            _PROBE_PACKAGE,
            "--fixtures",
            "-q",
            "-p",
            "no:xdist",
            "-p",
            "no:cacheprovider",
            *extra_args,
        ],
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT,
    )
    # --fixtures exits 0 on success in both arms; a hard failure (import error,
    # unknown package) is its own finding and must not read as fixture-absence.
    assert result.returncode == 0, (
        f"probe subprocess failed (rc={result.returncode}) — cannot conclude anything "
        f"about harness loading:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
    )
    return result.stdout


@pytest.mark.skipif(
    "grid_fixtures" not in set(installed_plugin_slugs()),
    reason="probe package grid_fixtures not installed in this stack (focused session); "
    "the core_ci lane, which installs it, runs this guard",
)
def test_harness_loads_under_pyargs_and_probe_detects_absence():
    """The harness must be visible to a --pyargs run; the probe must see its removal.

    Positive arm: lane 2's invocation mode sees `default_caller_context`.
    Negative arm: with the plugin explicitly disabled, the identical probe reports
    the fixture gone — proving a future silent-unload regression turns this test
    red rather than invisibly weakening the probe.
    """
    with_harness = _pyargs_fixture_listing()
    assert _HARNESS_FIXTURE in with_harness, (
        "The tap_harness pytest plugin did not load under `--pyargs` — plugin-ci "
        "lane 2 and every `pytest --pyargs tap_plugin.<slug>` run will fail all DB "
        "tests with MissingActor. Check the `-p tap.pytest_harness` entry in addopts "
        "([tool.pytest.ini_options], pyproject.toml)."
    )

    without_harness = _pyargs_fixture_listing("-o", "addopts=")
    assert _HARNESS_FIXTURE not in without_harness, (
        "Probe control failed: the harness fixture is still visible with addopts "
        "blanked, so this guard could no longer detect a real carrier regression."
    )
