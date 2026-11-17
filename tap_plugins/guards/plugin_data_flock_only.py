"""Plugin data locks use `flock` and only `flock` — `req-tap-plugin-datadir-lifecycle` (`-lifecycle-12`).

The in-use lock is what makes purge refuse while a plugin is loaded. POSIX record locks would quietly
break it: a process loses them when it closes ANY descriptor on the file, a forked worker does not
inherit them, and on Linux they do not exclude `flock` locks, so one stray `lockf` call lets a purge
delete a database a worker has open. This pins the lock module to `fcntl.flock` and keeps every
record-lock spelling out of the data-directory package.
"""

from __future__ import annotations

from tap.guards.base import REPO_ROOT, Guard

_PACKAGE = REPO_ROOT / "tap_plugins" / "datadir"
_LOCK_MODULE = _PACKAGE / "_lock.py"
#: Record-lock spellings, assembled so this module never matches a scan of itself.
_FORBIDDEN = ("lock" + "f(", "F_SET" + "LK", "F_GET" + "LK", "F_OFD_")


class PluginDataFlockOnlyGuard(Guard):
    slug = "plugin-data-flock-only"
    map_row = "Plugin data in-use lock is flock only"
    rid = "req-tap-plugin-datadir-lifecycle"
    description = (
        "Purge refuses while a plugin is loaded only because every holder takes a flock on the same lock "
        "file. A POSIX record lock anywhere in the data-directory package would be dropped on an unrelated "
        "close and not inherited by forked workers, so a purge could delete a database in use. This requires "
        "fcntl.flock in the lock module and forbids lockf and the record-lock commands in the package."
    )

    def check(self) -> None:
        assert "fcntl.flock(" in _LOCK_MODULE.read_text(encoding="utf-8"), (  # nosec B101
            f"{_LOCK_MODULE.relative_to(REPO_ROOT)} no longer calls fcntl.flock"
        )
        violations = [
            f"{path.relative_to(REPO_ROOT).as_posix()}: {needle!r}"
            for path in sorted(_PACKAGE.rglob("*.py"))
            for needle in _FORBIDDEN
            if needle in path.read_text(encoding="utf-8")
        ]
        assert not violations, (  # nosec B101
            "POSIX record locks in the plugin data package (req-tap-plugin-datadir-lifecycle-12):\n  "
            + "\n  ".join(violations)
        )
