"""The ``plugin-data`` health probe (`req-tap-plugin-datadir-health`).

Touches the filesystem and not the database, so it tells the truth when the database is
unreachable, and it does not walk directories to measure them.

- No declaring plugin installed: healthy, nothing to check.
- Volume not enabled, only caches declared: healthy, and the context names them as ephemeral.
- A declaring plugin installed: unhealthy when a configured volume fails its test or a ``"state"``
  directory has no volume, and unhealthy when any declared directory is missing, is a link, has the
  wrong owner, or fails a write probe, naming each.
- Orphans and strays never change the verdict; they ride the context. Nor does size, in this release.
"""

from __future__ import annotations

import logging
from typing import Any

from tap_health.results import ProbeResult, exception_detail

logger = logging.getLogger(__name__)


def probe_plugin_data() -> ProbeResult:
    """Every declared plugin data directory is where it should be and usable."""
    from tap.volume_mount import write_probe
    from tap_plugins.datadir import _facts, _placement, _provision

    try:
        declared = _placement.declared_directories()
        verdict = _placement.volume_verdict(fresh=True)
        root = _placement.volume_root()
        context: dict[str, Any] = {"declared": sorted(declared), "volume_enabled": verdict is not None}
        if verdict is not None and verdict.usable and root is not None:
            context.update(_facts.classify_root(root, set(declared)))
        if not declared:
            return ProbeResult.healthy(context={**context, "note": "no installed plugin declares a data directory"})
        if verdict is not None and not verdict.usable:
            return ProbeResult.unhealthy(
                "plugin_data.volume_unusable",
                detail=_placement.volume_refusal(root, verdict),
                reasoning="A plugin declares a data directory and the configured plugin data volume failed its test.",
                context=context,
            )
        bad: dict[str, str] = {}
        ephemeral: list[str] = []
        for slug, (declaration, _version) in declared.items():
            placement = _placement.place(slug, declaration.durability)
            if placement.root is None:
                bad[slug] = placement.refusal
                continue
            if placement.ephemeral:
                ephemeral.append(slug)
            path = placement.path
            assert path is not None  # nosec B101
            problem = _provision.describe(path)
            if problem:
                bad[slug] = f"{path} {problem}"
                continue
            # The mount gate's own write probe, aimed at the plugin's directory. Not the whole
            # mount test: an ephemeral directory is on the root filesystem by design.
            failure = write_probe(path)
            if failure:
                bad[slug] = f"{path} is not writable: {failure}"
        context["ephemeral"] = sorted(ephemeral)
        if bad:
            context["bad"] = bad
            return ProbeResult.unhealthy(
                "plugin_data.directory_bad",
                detail="; ".join(f"{slug}: {why}" for slug, why in sorted(bad.items())),
                reasoning="A declared plugin data directory is missing, misplaced or unusable.",
                context=context,
            )
        return ProbeResult.healthy(context=context)
    except Exception as exc:  # noqa: BLE001 — report, never raise.
        logger.warning("[4665] health: could not check plugin data directories: %s", exc)
        return ProbeResult.unknown("plugin_data.unresolvable", detail=exception_detail(exc))


__all__ = ["probe_plugin_data"]
