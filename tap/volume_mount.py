"""Is a configured root a mounted, writable volume? — the one test both core volumes share.

The plugin data root (`tap_plugins/specs/spec-tap-plugin-data-directory.md`,
`req-tap-plugin-datadir-mount-gate`) and the file store root (`specs/spec-tap-file-store.md`,
`req-tap-files-mount-gate`) answer the same question the same way, so the answer lives here,
in core's settings-free library, where neither app depends sideways on the other.

The failure it exists to catch: the operator believes data is on a volume, the volume is not
mounted, the path exists anyway in the container's writable layer, and everything written there
is lost when the container is recreated. Docker does nothing to signal that case.

Stdlib only and import-safe.
"""

from __future__ import annotations

import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path

#: Names under a root that core reserves for its write probe. A plugin or store never uses them.
PROBE_PREFIX = ".tap-probe-"


@dataclass(frozen=True)
class VolumeVerdict:
    """Whether a root is usable, and if not, which check failed and why."""

    usable: bool
    #: The check that failed: ``missing``, ``not_a_directory``, ``symlink``, ``not_mounted`` or
    #: ``not_writable`` (a caller may add its own, such as an overlap between two roots); empty
    #: when usable.
    check: str = ""
    reason: str = ""


def root_device() -> int:
    """The device of the container's root filesystem.

    The one seam a test replaces: a temporary directory in a test sits on the same device as
    ``/`` and would otherwise always read as unmounted.
    """
    return os.stat("/").st_dev


def check_volume(root: Path) -> VolumeVerdict:
    """Decide whether *root* is a mounted volume this process can write.

    TAP-IMPLEMENTS: req-tap-plugin-datadir-mount-gate@eecebe74cbaa/a8651f54fa5c (derivation) — the
        one decision function; boot, the health probe, the report and the accessor all call it.

    1. The path exists and is a directory, not a symbolic link.
    2. It is on a different device from ``/`` (``st_dev``). ``os.path.ismount`` is not used: it
       cannot reliably see a bind mount on the same filesystem, and the device comparison answers
       the question that matters, whether the data would land in the container's own disk.
    3. A real write succeeds: create, write, ``fsync``, rename, remove. A permission check alone
       is not accepted as evidence.

    Nothing is created when a check fails: a missing root is reported, never repaired, because
    creating it would hide an unmounted volume.
    """
    try:
        st = os.lstat(root)
    except FileNotFoundError:
        return VolumeVerdict(False, "missing", f"{root} does not exist")
    except OSError as exc:
        return VolumeVerdict(False, "missing", f"{root} cannot be examined: {exc}")
    if stat.S_ISLNK(st.st_mode):
        return VolumeVerdict(False, "symlink", f"{root} is a symbolic link")
    if not stat.S_ISDIR(st.st_mode):
        return VolumeVerdict(False, "not_a_directory", f"{root} is not a directory")
    if st.st_dev == root_device():
        return VolumeVerdict(
            False,
            "not_mounted",
            f"{root} is not a mounted volume: it is on the same device as /, so anything written "
            "there is lost when the container is recreated",
        )
    error = write_probe(root)
    if error:
        return VolumeVerdict(False, "not_writable", f"{root} is not writable: {error}")
    return VolumeVerdict(True)


def write_probe(root: Path) -> str:
    """Create, write, fsync, rename and remove a file under *root*; return the error, or ``""``."""
    token = secrets.token_hex(8)
    first = root / f"{PROBE_PREFIX}{token}"
    second = root / f"{PROBE_PREFIX}{token}.done"
    try:
        fd = os.open(first, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, b"tap volume probe\n")
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(first, second)
        os.unlink(second)
    except OSError as exc:
        for leftover in (first, second):
            try:
                os.unlink(leftover)
            except OSError:
                pass
        return f"{type(exc).__name__}: {exc}"
    return ""


__all__ = ["PROBE_PREFIX", "VolumeVerdict", "check_volume", "root_device", "write_probe"]
