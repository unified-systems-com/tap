"""Schedule-grift target integrity guard — `req-tap-cares-collector-model-10`.

Every `SCHEDULED_TARGET` grift edge must resolve to a registered collector's
derived entity id. A stale hardcoded id dangles → boot population aborts → fresh
spawn fails. This is the guard the package-mode collector-identity rename motivated.
"""

from __future__ import annotations

import json
import uuid

from tap.guards.base import Guard

SCHEDULED_TARGET = "SCHEDULED_TARGET"


class ScheduleGriftTargetsGuard(Guard):
    slug = "schedule-grift-targets"
    map_row = "Schedule grift target integrity"
    rid = "req-tap-cares-collector-model-10"
    description = (
        "A collector's on-grid id is derived from its scope:key; schedule grift bundles hardcode that id "
        "as a SCHEDULED_TARGET edge. If the two drift (the failure the package-mode rename introduced), the "
        "edge dangles, boot population aborts, and every fresh spawn breaks. This fails that drift at "
        "authoring time instead of at a developer's next spawn."
    )

    def check(self) -> None:
        from tap_cares.registry import NAMESPACE_COLLECTOR, collector_registry
        from tap_plugins.seeding import all_tap_plugins

        registered = {str(uuid.uuid5(NAMESPACE_COLLECTOR, qk)) for qk in collector_registry.keys()}

        edges: list[tuple[str, str, str, str]] = []
        for config in all_tap_plugins():
            manifest = config.manifest
            if manifest is None:
                continue
            for bundle in manifest.grift:
                doc = json.loads((manifest.plugin_root / bundle.path).read_text())
                for batch_idx, batch in enumerate(doc.get("batches", [])):
                    for edge_idx, edge in enumerate(batch.get("edges", [])):
                        body = edge.get("edge", {})
                        if body.get("edge_type") == SCHEDULED_TARGET:
                            edges.append(
                                (
                                    manifest.slug,
                                    bundle.name,
                                    f"$.batches[{batch_idx}].edges[{edge_idx}]",
                                    body["to_entity_id"],
                                )
                            )

        # Install-aware: a focused stack may install no schedule-owning plugin (e.g.
        # {aws_core, grid_fixtures} ships no SCHEDULED_TARGET edge). The invariant this
        # guard enforces — every SHIPPED schedule edge resolves to a registered collector
        # — is then vacuously satisfied, so pass. A hard "≥1 must exist" would bake a
        # specific plugin's presence into a core guard (the pollution
        # spec-tap-plugin-validation-distribution warns against); the all-plugins CI lane,
        # which installs the schedule owners, is where the populated check runs.
        if not edges:
            return

        dangling = [(slug, bundle, path, tid) for slug, bundle, path, tid in edges if tid not in registered]
        assert not dangling, (
            "SCHEDULED_TARGET edge(s) point at a collector entity id that no registered collector "
            "reconciles to — a stale hardcoded id or scope/key drift (req-tap-cares-collector-model-10):\n"
            + "\n".join(f"  {slug}/{bundle} {path} -> {tid}" for slug, bundle, path, tid in dangling)
            + f"\nRegistered collector ids: {sorted(registered)}"
        )
