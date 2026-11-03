"""A bare ``pytest`` takes the stack's pytest lock (tap#1092; ``req-dev-validation-suite-tiers-7``).

The lock used to be taken only by ``scripts/test`` and ``pytest-serial``, so a session that typed
``pytest`` next to a running lane shared its test database and produced mass xdist ERRORs. The harness
(``tap.pytest_harness``) now takes it in ``pytest_configure`` on the controller. Each test here runs a
real ``pytest`` subprocess on a throwaway test file, with the lock pointed at a temp path.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tap.pytest_lock import hold_pytest_lock

_PROBE = """
import os
from tap.pytest_lock import holder_text, is_locked

def test_probe():
    print("PROBE locked=%s held=%s text=%s" % (is_locked(), os.environ.get("TAP_PYTEST_LOCK_HELD"), holder_text()))
"""


def _run(tmp_path: Path, *extra: str, held: bool = False, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    probe = tmp_path / "test_probe.py"
    probe.write_text(_PROBE, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "TAP_PYTEST_LOCK_HELD"}
    env["TAP_PYTEST_LOCK"] = str(tmp_path / "lock")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])  # the subprocess runs in tmp_path
    if held:
        env["TAP_PYTEST_LOCK_HELD"] = "1"
    return subprocess.run(  # nosec B603  # nosemgrep  # noqa: S603 — this interpreter + fixed pytest args
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tap.pytest_harness",
            "-p",
            "no:xdist",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:django",
            "-s",
            "-q",
            "-c",
            str(tmp_path / "pytest.ini"),
            str(probe),
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=tmp_path,
        env=env,
        check=False,
    )


def test_a_bare_pytest_holds_the_lock_while_it_runs(tmp_path: Path) -> None:
    result = _run(tmp_path)
    assert "PROBE locked=True held=1 text=pytest pid=" in result.stdout, result.stdout + result.stderr


def test_a_run_under_a_holder_does_not_retake_it(tmp_path: Path) -> None:
    result = _run(tmp_path, held=True)
    assert "PROBE locked=False held=1" in result.stdout, result.stdout + result.stderr


def test_a_bare_pytest_waits_behind_a_holder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Under a lane (or CI) this process inherits TAP_PYTEST_LOCK_HELD=1, which makes hold_pytest_lock a
    # no-op: clear it first so the holder below really takes the lock.
    monkeypatch.delenv("TAP_PYTEST_LOCK_HELD", raising=False)
    with hold_pytest_lock("a lane", path=tmp_path / "lock"):
        os.environ.pop("TAP_PYTEST_LOCK_HELD", None)  # the holder context set it for this process
        with pytest.raises(subprocess.TimeoutExpired):
            _run(tmp_path, timeout=5)


def test_collect_only_and_fixtures_do_not_take_the_lock(tmp_path: Path) -> None:
    for flag in ("--collect-only", "--fixtures"):
        result = _run(tmp_path, flag)
        assert "PROBE" not in result.stdout
        assert not (tmp_path / "lock").exists(), f"{flag} took the lock"
