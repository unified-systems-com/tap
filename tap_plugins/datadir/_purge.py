"""Purge: the only deletion path core provides for plugin data (`req-tap-plugin-datadir-lifecycle`).

Nothing in a plugin data directory is ever deleted by core on its own initiative. Purge is the
operator's explicit act, one plugin at a time, and it:

- refuses while any other TAP process has the plugin loaded (the in-use lock, taken exclusive
  without waiting);
- says what it will delete and requires a confirming flag, and a second, differently named flag for
  a ``"state"`` directory or an orphan whose description is missing or says ``"state"``;
- refuses when ``<root>/<slug>`` is a symbolic link, never follows a link while deleting, and stays
  on the root's device, inside the root, by deleting through directory descriptors opened with
  ``O_NOFOLLOW``;
- records who ran it, the slug, and what was removed.

The lock file sits beside the directory and is never deleted.
"""

from __future__ import annotations

import getpass
import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tap_plugins.datadir import _facts, _lock, _placement, _provision
from tap_plugins.datadir._placement import PluginDataDirectoryError

logger = logging.getLogger(__name__)


class PurgeRefused(Exception):
    """Purge deleted nothing; the message says why."""


class PurgeIncomplete(Exception):
    """Purge started deleting and then failed: some entries are gone and the rest remain.

    Raised only once deletion has begun, with what was removed, so the operator is never told
    "nothing deleted" about a directory that is now half gone.
    """

    def __init__(self, reason: str, removed: dict[str, int]) -> None:
        super().__init__(reason)
        self.removed = removed


@dataclass
class PurgePlan:
    """What a purge would delete, shown to the operator before anything is touched."""

    slug: str
    root: Path
    path: Path
    durability: str
    #: ``declared`` for an installed plugin's directory, ``orphan`` otherwise.
    status: str
    needs_state_flag: bool
    measurement: dict[str, Any] = field(default_factory=dict)


def plan(slug: str) -> PurgePlan:
    """Find the directory and decide which flags it needs. Deletes nothing."""
    _provision.check_slug(slug)
    declared = _placement.declared_directories()
    if slug in declared:
        declaration = declared[slug][0]
        placement = _placement.place(slug, declaration.durability)
        if placement.root is None:
            raise PurgeRefused(placement.refusal)
        root, status, durability = placement.root, "declared", declaration.durability
        needs_state = durability == "state"
    else:
        root = _orphan_root(slug)
        status = "orphan"
        description = _provision.read_description(root / slug)
        durability = description["durability"] if description else "unknown"
        needs_state = durability != "cache"
    path = root / slug
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise PurgeRefused(f"there is no data directory for {slug!r} at {path}") from None
    if stat.S_ISLNK(st.st_mode):
        raise PurgeRefused(f"{path} is a symbolic link; purge does not follow it")
    if not stat.S_ISDIR(st.st_mode):
        raise PurgeRefused(f"{path} is not a directory")
    return PurgePlan(slug, root, path, durability, status, needs_state, _facts.measure(path, budget_s=30.0))


def _orphan_root(slug: str) -> Path:
    """The root an orphan directory is under: the volume when enabled, else the ephemeral root."""
    verdict = _placement.volume_verdict(fresh=True)
    root = _placement.volume_root()
    if verdict is not None:
        if not verdict.usable:
            raise PurgeRefused(_placement.volume_refusal(root, verdict))
        assert root is not None  # nosec B101
        return root
    return _placement.EPHEMERAL_ROOT


def purge(the_plan: PurgePlan, *, confirm: bool, confirm_state: bool) -> dict[str, int]:
    """Delete the planned directory, or raise :class:`PurgeRefused` having deleted nothing.

    A failure after deletion has begun (a nested mount, a filesystem error) raises
    :class:`PurgeIncomplete` with what was removed, and is logged like a completed purge.

    TAP-IMPLEMENTS: req-tap-plugin-datadir-lifecycle@c1a3a27d0731/2af6a3391aad (enforcement) — the only
        code that deletes a plugin data directory, behind the confirmation flags and the in-use lock.
    """
    if not confirm:
        raise PurgeRefused("purge needs --yes to delete anything")
    if the_plan.needs_state_flag and not confirm_state:
        raise PurgeRefused(
            f"{the_plan.path} holds durability {the_plan.durability!r}, which may not be rebuildable; "
            "purge needs --delete-state as well as --yes"
        )
    try:
        _lock.take_exclusive(the_plan.root, the_plan.slug)
    except _lock.DirectoryInUse as exc:
        raise PurgeRefused(str(exc)) from exc
    removed = {"bytes": 0, "entries": 0}
    try:
        _remove(the_plan.root, the_plan.slug, removed)
    except (OSError, PluginDataDirectoryError) as exc:
        if not removed["entries"]:
            raise PurgeRefused(f"nothing could be removed from {the_plan.path}: {exc}") from exc
        _log_purge(the_plan, removed, outcome=f"incomplete: {exc}")
        raise PurgeIncomplete(str(exc), removed) from exc
    finally:
        _lock.back_to_shared(the_plan.root, the_plan.slug)
    _log_purge(the_plan, removed, outcome="complete")
    return removed


def _log_purge(the_plan: PurgePlan, removed: dict[str, int], *, outcome: str) -> None:
    actor = _actor()
    logger.warning(
        "[ec35] plugin data: purged %s by %s: durability=%s bytes=%d entries=%d path=%s outcome=%s",
        the_plan.slug,
        actor,
        the_plan.durability,
        removed["bytes"],
        removed["entries"],
        the_plan.path,
        outcome,
        extra={
            "message_data": {
                "actor": actor,
                "slug": the_plan.slug,
                "durability": the_plan.durability,
                "bytes_removed": removed["bytes"],
                "entries_removed": removed["entries"],
                "path": str(the_plan.path),
                "outcome": outcome,
            }
        },
    )


def _actor() -> str:
    try:
        name = getpass.getuser()
    except KeyError, OSError:
        name = "unknown"
    return f"{name} (uid {os.geteuid()})"


def _remove(root: Path, slug: str, counts: dict[str, int]) -> None:
    """Remove ``<root>/<slug>`` through directory descriptors, never following a link.

    *counts* is updated as each entry goes, so a caller still knows what was removed when this
    raises partway.
    """
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    root_fd = os.open(root, flags)
    try:
        device = os.fstat(root_fd).st_dev
        try:
            top_fd = os.open(slug, flags, dir_fd=root_fd)
        except OSError as exc:
            raise PurgeRefused(f"cannot open {root / slug} without following a link: {exc}") from exc
        try:
            if os.fstat(top_fd).st_dev != device:
                raise PurgeRefused(f"{root / slug} is on a different device from {root}")
            _remove_contents(top_fd, device, counts, root / slug)
        finally:
            os.close(top_fd)
        os.rmdir(slug, dir_fd=root_fd)
    finally:
        os.close(root_fd)


def _remove_contents(dir_fd: int, device: int, counts: dict[str, int], where: Path) -> None:
    with os.scandir(dir_fd) as iterator:
        entries = list(iterator)
    for entry in entries:
        st = os.stat(entry.name, dir_fd=dir_fd, follow_symlinks=False)
        if stat.S_ISDIR(st.st_mode):
            if st.st_dev != device:
                raise PluginDataDirectoryError(f"{where / entry.name} is a mount point on another device; not purged")
            child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
            try:
                _remove_contents(child, device, counts, where / entry.name)
            finally:
                os.close(child)
            os.rmdir(entry.name, dir_fd=dir_fd)
        else:
            os.unlink(entry.name, dir_fd=dir_fd)
        counts["bytes"] += st.st_blocks * 512
        counts["entries"] += 1


__all__ = ["PurgeIncomplete", "PurgePlan", "PurgeRefused", "plan", "purge"]
