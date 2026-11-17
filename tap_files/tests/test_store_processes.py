"""The file store's write path across real processes (`req-tap-files-write`, `req-tap-files-read`).

Each test forks: the object lock is an ``flock``, which is per open file description, so threads in
one process would not exercise it. Children report through pipes and leave with ``os._exit``.
"""

from __future__ import annotations

import io
import logging
import os
import signal
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from tap.logging_signals import CONCERN_MESSAGE_CODE
from tap_files.store import layout
from tap_files.store.errors import FileIntegrityError, ObjectExists, VersionConflict
from tap_files.store.local import VERSION_STEPS, LocalBackend


@pytest.fixture
def store(tmp_path: Path) -> LocalBackend:
    root = tmp_path / "files"
    root.mkdir()
    backend = LocalBackend(root)
    backend.initialise()
    return backend


def _fork(body: Any) -> tuple[int, int]:
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:  # pragma: no cover — the child
        code = 0
        try:
            os.close(read_fd)
            body(write_fd)
        except BaseException:  # noqa: BLE001 — a child reports, never raises into pytest
            code = 1
        finally:
            os._exit(code)
    os.close(write_fd)
    return pid, read_fd


def _read_until(fd: int, token: bytes, timeout: float = 20.0) -> bytes:
    os.set_blocking(fd, False)
    got, deadline = b"", time.monotonic() + timeout
    while token not in got:
        if time.monotonic() > deadline:
            raise AssertionError(f"no {token!r} from the child; got {got!r}")
        try:
            chunk = os.read(fd, 256)
        except BlockingIOError:
            time.sleep(0.01)
            continue
        if not chunk:
            break
        got += chunk
    return got


@pytest.mark.spec("req-tap-files-write-6")
def test_one_writer_per_object(store: LocalBackend) -> None:
    ident = layout.urn(str(uuid.uuid4()))
    go_r, go_w = os.pipe()

    def creator(out: int) -> None:
        os.read(go_r, 1)
        try:
            store.create(ident, "a", io.BytesIO(b"x" * 100000), "t")
            os.write(out, b"ok;")
        except ObjectExists:
            os.write(out, b"exists;")

    children = [_fork(creator) for _ in range(2)]
    os.write(go_w, b"gg")
    results = sorted(_read_until(fd, b";").decode() for _pid, fd in children)
    for pid, fd in children:
        os.waitpid(pid, 0)
        os.close(fd)
    assert results == ["exists;", "ok;"]

    def versioner(out: int) -> None:
        os.read(go_r, 1)
        try:
            store.add_version(ident, 1, "a", io.BytesIO(os.urandom(100000)), "t")
            os.write(out, b"ok;")
        except VersionConflict:
            os.write(out, b"conflict;")

    children = [_fork(versioner) for _ in range(2)]
    os.write(go_w, b"gg")
    results = sorted(_read_until(fd, b";").decode() for _pid, fd in children)
    for pid, fd in children:
        os.waitpid(pid, 0)
        os.close(fd)
    assert results == ["conflict;", "ok;"]
    assert store.stat(ident).head == 2


@pytest.mark.spec("req-tap-files-write-11")
@pytest.mark.parametrize("step", VERSION_STEPS[:-1])
def test_recovery_spares_a_live_write(store: LocalBackend, step: str) -> None:
    ident = layout.urn(str(uuid.uuid4()))
    store.create(ident, "a", io.BytesIO(b"one"), "t")
    resume_r, resume_w = os.pipe()

    def writer(out: int) -> None:
        def pause(name: str) -> None:
            if name == step:
                os.write(out, b"paused;")
                os.read(resume_r, 1)

        store._step = pause  # type: ignore[method-assign]
        store.add_version(ident, 1, "a", io.BytesIO(b"two"), "t")
        os.write(out, b"done;")

    pid, fd = _fork(writer)
    try:
        _read_until(fd, b"paused;")
        quarantined = sorted(p.name for p in store.quarantine.iterdir())
        staged = sorted(p.name for p in store.staging.iterdir())
        actions = store.recover()
        assert not any(ident in a or layout.encode_identifier(ident) in a for a in actions), actions
        assert sorted(p.name for p in store.quarantine.iterdir()) == quarantined
        assert sorted(p.name for p in store.staging.iterdir()) == staged
        os.write(resume_w, b"g")
        _read_until(fd, b"done;")
    finally:
        os.waitpid(pid, 0)
        os.close(fd)
    opened = store.open(ident)
    try:
        assert (opened.version, opened.stream.read()) == (2, b"two")
    finally:
        opened.close()


@pytest.mark.spec("req-tap-files-read-7")
def test_no_false_alarm_during_a_write(store: LocalBackend, caplog: pytest.LogCaptureFixture) -> None:
    ident = layout.urn(str(uuid.uuid4()))
    store.create(ident, "a", io.BytesIO(b"v1"), "t")

    def writer(out: int) -> None:
        for n in range(1, 40):
            store.add_version(ident, n, "a", io.BytesIO(f"v{n + 1}".encode()), "t")
        os.write(out, b"done;")

    caplog.set_level(logging.WARNING)
    pid, fd = _fork(writer)
    reads = 0
    try:
        os.set_blocking(fd, False)
        while True:
            opened = store.open(ident)
            opened.close()
            reads += 1
            try:
                if b"done;" in os.read(fd, 64):
                    break
            except BlockingIOError:
                continue
    except FileIntegrityError as exc:
        os.kill(pid, signal.SIGKILL)
        raise AssertionError(f"false integrity alarm during a write: {exc}") from exc
    finally:
        os.waitpid(pid, 0)
        os.close(fd)
    assert reads > 0 and store.stat(ident).head == 40
    assert not [r for r in caplog.records if getattr(r, "message_code", None) == CONCERN_MESSAGE_CODE]
