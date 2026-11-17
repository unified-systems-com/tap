"""The in-use lock: shared by every process that has a plugin loaded, exclusive for purge.

`req-tap-plugin-datadir-lifecycle`, "The in-use lock". One empty lock file per plugin directory at
``<root>/.tap-locks/<slug>.lock``, beside the directory and never inside it, so purge does not
delete what it is holding. Core creates it on first need and never deletes it: an unlinked lock
file can be locked twice, by one process on the old inode and another on the new.

``fcntl.flock`` and only ``flock``. POSIX record locks are lost when a process closes ANY descriptor
on the file, are not inherited across ``fork``, and on Linux do not exclude ``flock`` locks. A
``flock`` lock belongs to the open file description, so workers forked from a holder share it and
it stays held until the last of them exits; the kernel drops it when a process ends, however it
ends, so no lock is ever left behind and nothing records a process id.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path

from tap_plugins.datadir._placement import LOCKS_DIRNAME

#: Descriptors this process holds, by lock path. Kept open for the life of the process.
_HELD: dict[str, int] = {}


class DirectoryInUse(Exception):
    """Another process holds the plugin's lock, so its directory may not be purged now."""


def lock_path(root: Path, slug: str) -> Path:
    return root / LOCKS_DIRNAME / f"{slug}.lock"


def _open_lock(root: Path, slug: str) -> int:
    locks = root / LOCKS_DIRNAME
    try:
        os.mkdir(locks, 0o700)
    except FileExistsError:
        pass
    # O_CLOEXEC: the descriptor is not passed to programs a plugin runs.
    return os.open(lock_path(root, slug), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)


def hold_shared(root: Path, slug: str) -> None:
    """Take the plugin's lock shared and keep it for the life of the process.

    TAP-IMPLEMENTS: req-tap-plugin-datadir-lifecycle@cf3b9a921595/cf103f17d916 (derivation) — what "in use"
        means: every process that loads a declaring plugin holds this before it provisions or touches
        the directory, and purge refuses while anyone else does.

    Blocks while a purge holds it exclusive, so a process that starts during a purge waits and then
    finds whatever the purge left, never a half-deleted directory. Idempotent within a process.
    """
    key = str(lock_path(root, slug))
    if key in _HELD:
        return
    fd = _open_lock(root, slug)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
    except OSError:
        os.close(fd)
        raise
    _HELD[key] = fd


def take_exclusive(root: Path, slug: str) -> None:
    """Convert this process's hold to exclusive without waiting, or raise :class:`DirectoryInUse`.

    The purge command's own process loaded the plugin like any other, so it converts the descriptor
    it already holds; opening the file a second time would make it refuse itself.
    """
    key = str(lock_path(root, slug))
    fd = _HELD.get(key)
    if fd is None:
        fd = _open_lock(root, slug)
        _HELD[key] = fd
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        # A failed conversion can drop the shared hold on some kernels; take it back so this
        # process still counts as a user.
        fcntl.flock(fd, fcntl.LOCK_SH)
        raise DirectoryInUse(f"{root / slug} is in use: another TAP process has plugin {slug!r} loaded") from exc


def back_to_shared(root: Path, slug: str) -> None:
    """Downgrade an exclusive hold taken by :func:`take_exclusive` back to shared."""
    fd = _HELD.get(str(lock_path(root, slug)))
    if fd is not None:
        fcntl.flock(fd, fcntl.LOCK_SH)


def release_all() -> None:
    """Close every held descriptor (tests only; a running process keeps them until it exits)."""
    for fd in _HELD.values():
        try:
            os.close(fd)
        except OSError:
            pass
    _HELD.clear()


__all__ = ["DirectoryInUse", "back_to_shared", "hold_shared", "lock_path", "release_all", "take_exclusive"]
