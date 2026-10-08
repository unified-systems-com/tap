"""tap_viz Django app configuration."""

from typing import Any

from django.apps import AppConfig


class TapVizConfig(AppConfig):
    """Configuration for the tap_viz visualization app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "tap_viz"
    verbose_name = "TAP Visualization"

    # Top-level URL prefix this app mounts (tap/urls.py), reserved against Page
    # slugs. Collected by tap_web.reserved.get_reserved_url_prefixes().
    reserved_url_prefixes: list[str] = ["/viz"]

    # The edge types tap_viz's models and panels use, defined here so each is a real
    # edge definition rather than a string only a HOTLINKS entry or a reader knows
    # (Issue# 910 - tap). Same format as TapWebConfig.edge_types; processed by
    # register_edge_types_from_list() on startup. Five are hotlink edges
    # (req-grid-hotlink-model-5: a hotlink's edge_type must be a defined edge type,
    # checked by tap_grid.E004); USES_PROJECTION is written by bundles and read by
    # the graph panel. None declares a property_schema: a hotlink edge carries only
    # the system-owned `hotlink` payload, which per-type schemas may not redeclare
    # (req-grid-edge-schema-required-5). Each declares its identity
    # (req-grid-edge-identity-declaration) as a plain key: a hotlink edge's (source, target) is
    # fully determined by the field it mirrors, so nothing beside the pair tells two apart.
    edge_types: list[dict[str, Any]] = [
        {
            "slug": "USES_ARRANGEMENT",
            "name": "Uses Arrangement",
            "identity": {"discriminators": []},
            "description": (
                "The source layout applies the target arrangement. Mirrors the layout's "
                "definition.arrangements list (hotlink layout-arrangements, exact)."
            ),
            "sources": [{"type": "layout"}],
            "targets": [{"type": "arrangement"}],
        },
        {
            "slug": "USES_LAYOUT",
            "name": "Uses Layout",
            "identity": {"discriminators": []},
            "description": (
                "The source composes the target layout. From an elevation it mirrors the elevation's "
                "definition.layouts list (hotlink elevation-layouts, exact); from a panel it is the legacy "
                "graph-panel binding, read when the panel has no USES_PROJECTION edge."
            ),
            "sources": [{"type": "elevation"}, {"type": "panel"}],
            "targets": [{"type": "layout"}],
        },
        {
            "slug": "USES_ELEVATION",
            "name": "Uses Elevation",
            "identity": {"discriminators": []},
            "description": (
                "The source projection includes the target elevation as one of its zoom stages. Mirrors the "
                "projection's definition.elevations list (hotlink projection-elevations, exact)."
            ),
            "sources": [{"type": "projection"}],
            "targets": [{"type": "elevation"}],
        },
        {
            "slug": "USES_DEFAULT_ELEVATION",
            "name": "Uses Default Elevation",
            "identity": {"discriminators": []},
            "description": (
                "The target elevation is the one the source projection opens at. Mirrors the projection's "
                "definition.default_elevation_id (hotlink projection-default-elevation, exact)."
            ),
            "sources": [{"type": "projection"}],
            "targets": [{"type": "elevation"}],
        },
        {
            "slug": "NAVIGATES_TO",
            "name": "Navigates To",
            "identity": {"discriminators": []},
            "description": (
                "A double-tap on a node in the source elevation navigates to the target elevation. Mirrors the "
                "elevation's definition.double_tap_targets[].target_elevation_id (hotlink "
                "elevation-navigates-to, exact)."
            ),
            "sources": [{"type": "elevation"}],
            "targets": [{"type": "elevation"}],
        },
        {
            "slug": "USES_PROJECTION",
            "name": "Uses Projection",
            "identity": {"discriminators": []},
            "description": (
                "The source graph panel renders through the target projection. The panel reads its "
                "earliest-created USES_PROJECTION edge; with none it falls back to USES_LAYOUT."
            ),
            "sources": [{"type": "panel"}],
            "targets": [{"type": "projection"}],
        },
    ]

    def ready(self) -> None:
        """Register tap_viz's edge types and built-in panel types."""
        from tap_plugins.base import register_edge_types_from_list
        from tap_viz.panels.graph_panel import GraphPanelType
        from tap_web.registry import panel_type_registry

        register_edge_types_from_list(self.edge_types)
        panel_type_registry.register("graph", GraphPanelType)
