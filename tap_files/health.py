"""The ``files`` health probe (`req-tap-files-health`).

Reads the root's markers, the volume's facts and the count of quarantined items; reads no object,
walks nothing and does not touch the database, so it answers truthfully when the database is down.

- Not enabled: healthy, and the context says so, unless an installed plugin requires the store.
- Enabled: unhealthy when the root fails the shared mount test or is not this store's initialised
  root; otherwise healthy, with the filesystem type, free bytes and inodes, and the quarantine count.
- A non-empty quarantine never changes the verdict.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from tap_health.results import ProbeResult, exception_detail

logger = logging.getLogger(__name__)


def filesystem_type(path: Path) -> str:
    """The type of the filesystem *path* is on, from ``/proc/self/mountinfo``; ``""`` when unknown."""
    target = os.path.realpath(path)
    best, kind = "", ""
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as fh:
            for line in fh:
                fields = line.split()
                mount_point = fields[4].replace("\\040", " ")
                fstype = fields[fields.index("-") + 1]
                inside = target == mount_point or target.startswith(mount_point.rstrip("/") + "/")
                if inside and len(mount_point) >= len(best):
                    best, kind = mount_point, fstype
    except OSError, ValueError, IndexError:
        return ""
    return kind


def probe_files() -> ProbeResult:
    """The file store is usable where it is enabled, and required only where it is.

    TAP-IMPLEMENTS: req-tap-files-health@7860defab5c5/4df11962d8ab (derivation) — the probe's verdict: the mount test, the
        root's markers, and the store off only where no plugin requires it; quarantine never counts.
    """
    from tap.volume_mount import check_volume
    from tap_files.boot import requiring_plugins
    from tap_files.config import configured_root
    from tap_files.store.local import LocalBackend

    try:
        root = configured_root()
        if root is None:
            needing = requiring_plugins()
            context: dict[str, Any] = {"enabled": False, "required_by": needing}
            if needing:
                return ProbeResult.unhealthy(
                    "files.required_not_enabled",
                    detail=f"the file store is not enabled and {', '.join(needing)} require it",
                    reasoning="An installed plugin declares [file_store] required = true and TAP_FILES_ROOT is unset.",
                    context=context,
                )
            return ProbeResult.healthy(context={**context, "note": "the file store is not enabled"})
        context = {"enabled": True, "root": str(root)}
        verdict = check_volume(root)
        if not verdict.usable:
            return ProbeResult.unhealthy(
                "files.volume_unusable",
                detail=f"{verdict.check}: {verdict.reason}",
                reasoning="The configured file store root failed the shared mount test.",
                context={**context, "check": verdict.check},
            )
        store = LocalBackend(root)
        problem = store.root_problem()
        if problem:
            return ProbeResult.unhealthy(
                "files.root_invalid",
                detail=problem,
                reasoning="The root is not this store's initialised OCFL storage root.",
                context=context,
            )
        volume = os.statvfs(root)
        context.update(
            filesystem=filesystem_type(root),
            free_bytes=volume.f_bavail * volume.f_frsize,
            free_inodes=volume.f_favail,
            quarantined=store.quarantine_count(),
        )
        return ProbeResult.healthy(context=context)
    except Exception as exc:  # noqa: BLE001 — report, never raise.
        logger.warning("[2be5] health: could not check the file store: %s", exc)
        return ProbeResult.unknown("files.unresolvable", detail=exception_detail(exc))


__all__ = ["filesystem_type", "probe_files"]
