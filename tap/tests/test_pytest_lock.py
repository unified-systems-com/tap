"""One heavy pytest per stack, and a stop that kills the whole group (tap#1092).

Spec: specs/spec-dev-validation.md (req-dev-validation-suite-tiers-7).
"""

from __future__ import annotations

import fcntl
import os
import signal
import subprocess  # nosec B404 — fixed argv: this interpreter + a literal -c program, in a temp dir
import sys
import time
from pathlib import Path

import pytest

from tap import pytest_lock
from tap.pytest_lock import LockBusy, hold_pytest_lock, holder_pid, is_locked, stop


@pytest.fixture(autouse=True)
def _not_under_a_holder(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests exercise the lock itself, so they must not inherit a lane's HELD marker."""
    monkeypatch.delenv("TAP_PYTEST_LOCK_HELD", raising=False)


@pytest.mark.spec("req-dev-validation-suite-tiers-7")
def test_a_second_run_cannot_take_a_held_lock(tmp_path: Path) -> None:
    lock = tmp_path / "pytest.lock"
    with hold_pytest_lock("first run", path=lock):
        assert is_locked(lock)
        assert holder_pid(lock) == os.getpid()
        # the marker is set while held, so a child of the holder does not try to re-take it
        assert os.environ.get("TAP_PYTEST_LOCK_HELD") == "1"
    assert not is_locked(lock)
    assert "TAP_PYTEST_LOCK_HELD" not in os.environ


@pytest.mark.spec("req-dev-validation-suite-tiers-7")
def test_a_non_waiting_attempt_names_the_holder(tmp_path: Path) -> None:
    lock = tmp_path / "pytest.lock"
    holder = subprocess.Popen(  # nosec B603  # nosemgrep  # noqa: S603
        [
            sys.executable,
            "-c",
            "import sys, time; from pathlib import Path; "
            "from tap.pytest_lock import hold_pytest_lock; "
            "cm = hold_pytest_lock('lane under test', path=Path(sys.argv[1])); cm.__enter__(); "
            "print('held', flush=True); time.sleep(60)",
            str(lock),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        with pytest.raises(LockBusy, match="lane under test"):
            with hold_pytest_lock("second", wait=False, path=lock):
                pass
        assert is_locked(lock)
    finally:
        holder.kill()
        holder.wait()
    assert not is_locked(lock)  # the kernel released it with the holder


@pytest.mark.spec("req-dev-validation-suite-tiers-7")
def test_stop_with_no_holder_says_so(tmp_path: Path) -> None:
    lock = tmp_path / "pytest.lock"
    lock.write_text("old lane pid=999999 since=00:00:00\n")  # stale text, nobody holds the flock
    assert not is_locked(lock)
    assert "no pytest run holds the lock" in stop(lock)


@pytest.mark.spec("req-dev-validation-suite-tiers-7")
def test_term_kills_the_whole_process_group_not_just_the_leader(tmp_path: Path) -> None:
    """The child spawns a grandchild (an xdist worker, in life); TERM to the runner must leave neither."""
    pidfile = tmp_path / "grandchild.pid"
    child_src = (
        "import subprocess, sys, time; "
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)']); "
        f"open({str(pidfile)!r}, 'w').write(str(g.pid)); time.sleep(120)"
    )
    runner = subprocess.Popen(  # nosec B603  # nosemgrep  # noqa: S603
        [
            sys.executable,
            "-c",
            "import sys; from tap.pytest_lock import run_group; import os; "
            f"run_group([sys.executable, '-c', {child_src!r}], dict(os.environ))",
        ]
    )
    try:
        deadline = time.monotonic() + 20
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        grandchild = int(pidfile.read_text())
        os.kill(grandchild, 0)  # alive
        runner.send_signal(signal.SIGTERM)
        assert runner.wait(timeout=20) == 128 + signal.SIGTERM
        gone = False
        for _ in range(100):
            try:
                os.kill(grandchild, 0)
            except ProcessLookupError:
                gone = True
                break
            time.sleep(0.1)
        assert gone, "the grandchild outlived its group"
    finally:
        runner.kill()


def test_module_has_no_import_time_side_effects() -> None:
    assert pytest_lock._child is None


@pytest.mark.spec("req-dev-validation-suite-tiers-7")
def test_a_killed_holder_cannot_release_the_lock_while_its_pytest_lives(tmp_path: Path) -> None:
    """kill -9 of the holder (an OOM, a crash) must not free the lock under a running pytest: the child
    inherits the lock, and `stop` can still kill the orphaned group from the recorded pgid."""
    lock = tmp_path / "pytest.lock"
    runner = subprocess.Popen(  # nosec B603  # nosemgrep  # noqa: S603
        [
            sys.executable,
            "-c",
            "import os, sys, time; from pathlib import Path; "
            "from tap.pytest_lock import hold_pytest_lock, run_group; "
            "cm = hold_pytest_lock('crashing lane', path=Path(sys.argv[1])); cm.__enter__(); "
            "run_group([sys.executable, '-c', 'import time; time.sleep(120)'], dict(os.environ))",
            str(lock),
        ]
    )
    pgid = None
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and pgid is None:
            pgid = pytest_lock.holder_pgid(lock)
            time.sleep(0.1)
        assert pgid is not None, "the child's process group was never recorded"
        runner.kill()  # SIGKILL: no handler runs, nothing cleans up
        runner.wait(timeout=10)
        assert is_locked(lock), "the lock was released while the orphaned pytest still runs"
        assert "orphaned pytest group" in stop(lock)
        for _ in range(100):
            if not is_locked(lock):
                break
            time.sleep(0.1)
        assert not is_locked(lock)
    finally:
        runner.kill()
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.spec("req-dev-validation-suite-tiers-7")
def test_stop_does_not_signal_an_unrelated_process_that_reused_the_recorded_pid(tmp_path: Path) -> None:
    """A dead holder's pid/pgid can be reused. `stop` must check the process is ours before it signals."""
    lock = tmp_path / "pytest.lock"
    bystander = subprocess.Popen(  # nosec B603 B607  # nosemgrep  # noqa: S603
        [sys.executable, "-c", "import time; time.sleep(120)"]
    )
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)  # the lock is held, as if by an orphaned pytest
        os.write(fd, f"old lane pid={bystander.pid} since=00:00:00 pgid={bystander.pid}\n".encode())
        report = stop(lock)
        assert bystander.poll() is None, "stop signalled an unrelated process"
        assert str(bystander.pid) in report or "gone" in report or "no process group" in report
    finally:
        bystander.kill()
        bystander.wait()
        os.close(fd)
