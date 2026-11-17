"""Facts about plugin data directories, read from the manifest and the filesystem, never the grid.

`req-tap-plugin-datadir-report`. Size is measured by walking without following symbolic links and
without leaving the root's device, summing allocated blocks (a sparse file counts what it occupies)
and counting a hard-linked file once. The walk has a time budget: one that runs out reports what it
counted and says the figure is partial, and every figure carries the time it was taken. The report
never blocks a page on an unbounded walk.
"""

from __future__ import annotations

import os
import stat
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tap.plugin_identity import valid_slug
from tap_plugins.datadir._placement import LOCKS_DIRNAME, RESERVED_PREFIX

#: How many top-level entries a listing shows, and how many executable files are named.
LISTING_CAP = 50
EXECUTABLES_CAP = 50
#: The default walk budget, in seconds.
WALK_BUDGET_S = 2.0

_KINDS = ((stat.S_ISREG, "file"), (stat.S_ISDIR, "directory"), (stat.S_ISLNK, "link"))


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _kind(mode: int) -> str:
    for test, name in _KINDS:
        if test(mode):
            return name
    return "other"


def measure(path: Path, *, budget_s: float = WALK_BUDGET_S) -> dict[str, Any]:
    """Walk *path* within *budget_s*: allocated bytes, entry count and executable files.

    TAP-IMPLEMENTS: req-tap-plugin-datadir-report@8c429346e33c/c5861a4b6e85 (derivation) — the one walk that
        measures a plugin data directory; the report and the purge both take their figures from it.

    Links are counted by their own size and never followed; a directory on another device is
    counted but not entered; a hard-linked file is counted once.
    """
    started = time.monotonic()
    measured_at = _now()
    try:
        top = os.lstat(path)
    except OSError as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}", "measured_at": measured_at}
    device = top.st_dev
    seen_inodes: set[tuple[int, int]] = set()
    allocated = 0
    entries = 0
    executables: list[str] = []
    executables_cut = False
    complete = True
    queue: deque[Path] = deque([path])
    while queue:
        current = queue.popleft()
        try:
            iterator = os.scandir(current)
        except OSError:
            continue
        with iterator:
            for entry in iterator:
                if time.monotonic() - started > budget_s:
                    complete = False
                    queue.clear()
                    break
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                entries += 1
                if st.st_nlink > 1 and not stat.S_ISDIR(st.st_mode):
                    key = (st.st_dev, st.st_ino)
                    if key in seen_inodes:
                        continue
                    seen_inodes.add(key)
                allocated += st.st_blocks * 512
                if stat.S_ISDIR(st.st_mode):
                    if st.st_dev == device:
                        queue.append(Path(entry.path))
                elif stat.S_ISREG(st.st_mode) and st.st_mode & 0o111:
                    if len(executables) < EXECUTABLES_CAP:
                        executables.append(Path(entry.path).relative_to(path).as_posix())
                    else:
                        executables_cut = True
    return {
        "available": True,
        "allocated_bytes": allocated,
        "entry_count": entries,
        "complete": complete,
        "measured_at": measured_at,
        "duration_ms": round((time.monotonic() - started) * 1000, 1),
        "executables": sorted(executables),
        "executables_cut": executables_cut,
    }


def listing(path: Path, *, cap: int = LISTING_CAP) -> dict[str, Any]:
    """The directory's top level: name, kind, size and modification time, cut at *cap* entries.

    Bounded: it reads at most *cap* + 1 names, in the order the filesystem returns them, and sorts
    only those, so a directory with a million entries costs what one with *cap* does. The entries
    shown are therefore the first *cap* the filesystem lists, not the first *cap* by name.
    """
    names: list[str] = []
    try:
        with os.scandir(path) as iterator:
            for entry in iterator:
                names.append(entry.name)
                if len(names) > cap:
                    break
    except OSError as exc:
        return {"entries": [], "cut": False, "reason": f"{type(exc).__name__}: {exc}"}
    cut = len(names) > cap
    shown: list[dict[str, Any]] = []
    for name in sorted(names[:cap]):
        try:
            st = os.lstat(path / name)
        except OSError:
            continue
        shown.append(
            {
                "name": name,
                "kind": _kind(st.st_mode),
                "size_bytes": st.st_size,
                "modified_at": datetime.fromtimestamp(st.st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    return {"entries": shown, "cut": cut}


def ownership(path: Path) -> dict[str, Any]:
    """Whether *path* exists and is as provisioned: a real directory, the runtime user's, mode 0700."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return {"exists": False, "as_provisioned": False, "detail": "missing"}
    except OSError as exc:
        return {"exists": False, "as_provisioned": False, "detail": f"{type(exc).__name__}: {exc}"}
    problems = []
    if stat.S_ISLNK(st.st_mode):
        problems.append("is a symbolic link")
    elif not stat.S_ISDIR(st.st_mode):
        problems.append("is not a directory")
    else:
        if st.st_uid != os.geteuid():
            problems.append(f"owned by uid {st.st_uid}, not the runtime user (uid {os.geteuid()})")
        if stat.S_IMODE(st.st_mode) != 0o700:
            problems.append(f"mode {stat.S_IMODE(st.st_mode):04o}, not 0700")
    return {"exists": True, "as_provisioned": not problems, "detail": "; ".join(problems)}


def filesystem(root: Path) -> dict[str, Any]:
    """The filesystem type, free bytes and free inodes of the volume holding *root*."""
    facts: dict[str, Any] = {"type": _filesystem_type(root)}
    try:
        vfs = os.statvfs(root)
    except OSError as exc:
        facts.update({"free_bytes": None, "free_inodes": None, "detail": f"{type(exc).__name__}: {exc}"})
        return facts
    facts.update({"free_bytes": vfs.f_bavail * vfs.f_frsize, "free_inodes": vfs.f_favail})
    return facts


def _filesystem_type(root: Path) -> str | None:
    """The type of the mount holding *root*, from ``/proc/self/mounts``; ``None`` when unknown."""
    try:
        real = os.path.realpath(root)
        lines = Path("/proc/self/mounts").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    best, best_type = "", None
    for line in lines:
        fields = line.split()
        if len(fields) < 3:
            continue
        mount_point = fields[1].replace("\\040", " ")
        inside = real == mount_point or real.startswith(mount_point.rstrip("/") + "/")
        if inside and len(mount_point) >= len(best):
            best, best_type = mount_point, fields[2]
    return best_type


def classify_root(root: Path, declared: set[str]) -> dict[str, list[str]]:
    """Every entry directly under *root*: orphan directories and strays. Declared ones are omitted.

    An orphan is a directory named by a valid slug that no loaded plugin declares. A stray is
    anything else that is not core's: a file, a link, a directory whose name is not a slug.
    """
    orphans: list[str] = []
    strays: list[str] = []
    try:
        with os.scandir(root) as iterator:
            entries = sorted(iterator, key=lambda entry: entry.name)
    except OSError:
        return {"orphans": [], "strays": []}
    for entry in entries:
        name = entry.name
        if name.startswith(RESERVED_PREFIX) or name == LOCKS_DIRNAME:
            continue
        is_dir = entry.is_dir(follow_symlinks=False)
        if is_dir and valid_slug(name):
            if name not in declared:
                orphans.append(name)
        else:
            strays.append(name)
    return {"orphans": orphans, "strays": strays}


__all__ = [
    "EXECUTABLES_CAP",
    "LISTING_CAP",
    "WALK_BUDGET_S",
    "classify_root",
    "filesystem",
    "listing",
    "measure",
    "ownership",
]
