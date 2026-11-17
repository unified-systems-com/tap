"""The in-use lock across real processes (`req-tap-plugin-datadir-lifecycle`, the in-use lock).

Each test forks: a child stands in for another TAP process with the plugin loaded. A forked child
inherits this process's open descriptors, and a ``flock`` belongs to the open file description, so
every child first forgets the parent's held locks without closing them and takes its own, exactly
as a separately started process would.

Not covered here, and stated in the spec's note on ``-lifecycle-6``: two containers sharing the
volume. That a lock holds across containers on one kernel is expected and was not found stated in
a primary source; these tests prove it across processes in one container only.
"""

from __future__ import annotations

import os
import signal
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tap import volume_mount
from tap_plugins.datadir import _lock, _placement, _purge, on_plugin_loaded, run_gate
from tap_plugins.manifest import DataDirectoryDeclaration

_DECL = DataDirectoryDeclaration(purpose="Lock fixture.", durability="cache", max_bytes=4096, executes=False)


@pytest.fixture
def volume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Any) -> Iterator[Path]:
    root = tmp_path / "volume"
    root.mkdir()
    monkeypatch.setattr(volume_mount, "root_device", lambda: -1)
    monkeypatch.setattr(_placement, "EPHEMERAL_ROOT", tmp_path / "ephemeral")
    monkeypatch.setattr(_placement, "declared_directories", lambda: {"alpha": (_DECL, "1.0.0")})
    settings.TAP_PLUGIN_DATA_ROOT = str(root)
    settings.TAP_FILES_ROOT = ""
    _placement.reset_verdicts()
    _lock.release_all()
    yield root
    _placement.reset_verdicts()
    _lock.release_all()


def _child(body: Any) -> tuple[int, int]:
    """Fork a child that runs *body(write_fd)* and then waits to be killed; return (pid, read_fd)."""
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:  # pragma: no cover — runs in the child
        try:
            os.close(read_fd)
            _lock._HELD.clear()  # forget the parent's holds without closing them
            body(write_fd)
            while True:
                time.sleep(60)
        finally:
            os._exit(0)
    os.close(write_fd)
    return pid, read_fd


def _wait_for(read_fd: int, token: bytes, timeout: float = 10.0) -> bytes:
    deadline = time.monotonic() + timeout
    got = b""
    os.set_blocking(read_fd, False)
    while token not in got:
        if time.monotonic() > deadline:
            raise AssertionError(f"child never signalled {token!r}; got {got!r}")
        try:
            chunk = os.read(read_fd, 64)
        except BlockingIOError:
            time.sleep(0.02)
            continue
        if not chunk:
            raise AssertionError(f"child exited before signalling {token!r}; got {got!r}")
        got += chunk
    return got


def _reap(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    os.waitpid(pid, 0)


def _holder(volume: Path) -> Any:
    def body(write_fd: int) -> None:
        _lock.hold_shared(volume, "alpha")
        os.write(write_fd, b"held")

    return body


@pytest.mark.spec("req-tap-plugin-datadir-lifecycle-6")
def test_purge_is_refused_while_another_process_has_the_plugin_loaded(volume: Path) -> None:
    run_gate()
    pid, read_fd = _child(_holder(volume))
    try:
        _wait_for(read_fd, b"held")
        with pytest.raises(_purge.PurgeRefused, match=r"alpha is in use"):
            _purge.purge(_purge.plan("alpha"), confirm=True, confirm_state=True)
        assert (volume / "alpha").is_dir()
    finally:
        _reap(pid)
        os.close(read_fd)


@pytest.mark.spec("req-tap-plugin-datadir-lifecycle-8")
def test_a_killed_holder_leaves_no_lock(volume: Path) -> None:
    run_gate()
    pid, read_fd = _child(_holder(volume))
    _wait_for(read_fd, b"held")
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    os.close(read_fd)
    _purge.purge(_purge.plan("alpha"), confirm=True, confirm_state=False)
    assert not (volume / "alpha").exists()


@pytest.mark.spec("req-tap-plugin-datadir-lifecycle-9")
def test_forked_workers_keep_the_lock_after_their_parent_exits(volume: Path) -> None:
    run_gate()

    def parent_then_worker(write_fd: int) -> None:
        _lock.hold_shared(volume, "alpha")
        worker = os.fork()
        if worker == 0:
            os.write(write_fd, f"worker:{os.getpid()};".encode())
            return  # the worker lives on in _child's sleep loop, holding the inherited lock
        os.waitpid(worker, os.WNOHANG)
        os._exit(0)  # the parent exits; only the worker still has the descriptor

    pid, read_fd = _child(parent_then_worker)
    got = _wait_for(read_fd, b";")
    worker = int(got.decode().split("worker:", 1)[1].split(";", 1)[0])
    os.waitpid(pid, 0)  # the parent has exited
    try:
        with pytest.raises(_purge.PurgeRefused, match="in use"):
            _purge.purge(_purge.plan("alpha"), confirm=True, confirm_state=False)
    finally:
        os.kill(worker, signal.SIGKILL)
        os.close(read_fd)
    deadline = time.monotonic() + 10
    while True:  # the worker is not our child, so poll for the lock instead of waiting on it
        try:
            _purge.purge(_purge.plan("alpha"), confirm=True, confirm_state=False)
            break
        except _purge.PurgeRefused:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.05)
    assert not (volume / "alpha").exists()


@pytest.mark.spec("req-tap-plugin-datadir-lifecycle-10")
def test_a_start_during_purge_waits_then_finds_a_fresh_directory(volume: Path) -> None:
    run_gate()
    (volume / "alpha" / "old-data").write_text("from before the purge")
    the_plan = _purge.plan("alpha")
    _lock.take_exclusive(volume, "alpha")  # the purge's hold, taken before the newcomer starts

    def newcomer(write_fd: int) -> None:
        os.write(write_fd, b"starting;")
        on_plugin_loaded("alpha", _DECL, "1.0.0")  # blocks on the shared lock
        listing = sorted(p.name for p in (volume / "alpha").iterdir())
        os.write(write_fd, f"loaded:{time.monotonic()}:{','.join(listing)};".encode())

    pid, read_fd = _child(newcomer)
    try:
        _wait_for(read_fd, b"starting;")
        time.sleep(0.3)
        assert (volume / "alpha" / "old-data").exists(), "the newcomer touched the directory during the purge"
        removed = {"bytes": 0, "entries": 0}
        _purge._remove(volume, "alpha", removed)
        assert removed["entries"] >= 1
        released_at = time.monotonic()
        _lock.back_to_shared(volume, "alpha")
        got = _wait_for(read_fd, b"loaded:").decode()
        while not got.endswith(";"):
            got += _wait_for(read_fd, b";").decode()
        stamp, listing = got.split("loaded:", 1)[1].rstrip(";").split(":", 1)
        assert float(stamp) >= released_at
        assert "old-data" not in listing.split(",")
        assert (volume / "alpha").is_dir() and not (volume / "alpha" / "old-data").exists()
    finally:
        _reap(pid)
        os.close(read_fd)
    assert the_plan.slug == "alpha"
