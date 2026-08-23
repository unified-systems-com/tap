"""TAP Web application configuration."""

from typing import Any

from django.apps import AppConfig

from tap_web.dimensions import WEB_DIMENSIONS


class TapWebConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tap_web"
    verbose_name = "TAP Web"

    # Top-level URL prefixes this app mounts, reserved against Page slugs
    # (req-web-page-slug-sanitize.sec). Collected across all apps by
    # tap_web.reserved.get_reserved_url_prefixes(); see tap_web/reserved.py.
    # tap_web owns /panel and /object (see tap_web/urls.py); /admin and /auth
    # are project-level and declared in tap_web.reserved; /api and /viz are
    # declared by tap_api and tap_viz respectively.
    reserved_url_prefixes: list[str] = ["/panel", "/object"]

    # Same format as TapPluginConfig.edge_types.
    # Processed by register_edge_types_from_list() on startup.
    edge_types: list[dict[str, Any]] = [
        {
            "slug": "USES_PANEL",
            "name": "Uses Panel",
            "description": "Page embeds a panel.",
            "sources": [{"type": "page"}],
            "targets": [{"type": "panel"}],
            "default_dimensions": WEB_DIMENSIONS,
            # Type-authored properties only. The 'hotlink' participation payload
            # is system-owned (req-grid-edge-schema-required-5): its shape is
            # validated centrally by tap_grid.hotlink.EDGE_HOTLINK_PAYLOAD_SCHEMA
            # and per-type schemas may not redeclare it. Presence/correspondence
            # is enforced by hotlink validation itself (exact-mode mirror of the
            # Page.definition panel list), which is stricter than a required-key
            # check ever was.
            "property_schema": {
                "type": "object",
                "properties": {
                    "variable_map": {
                        "type": "object",
                        "properties": {
                            "tap_page_vars": {
                                "type": "object",
                                "additionalProperties": {"type": "string"},
                            },
                            "tap_page_persistent_vars": {
                                "type": "object",
                                "additionalProperties": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
        {
            "slug": "USES_SEARCH",
            "name": "Uses Search",
            "description": "Panel references a Search object as its data source (req-web-stdpanel-table-search).",
            "sources": [{"type": "panel"}],
            "targets": [{"type": "search"}],
            "default_dimensions": WEB_DIMENSIONS,
        },
        {
            "slug": "USES_LANDING_PAGE",
            "name": "Uses Landing Page",
            "description": "Landing page designates a target page for the root URL.",
            "sources": [{"type": "landing_page"}],
            "targets": [{"type": "page"}],
            "default_dimensions": WEB_DIMENSIONS,
        },
    ]

    def ready(self) -> None:
        from tap_plugins.base import register_edge_types_from_list
        from tap_web.editor import EditorDescriptor
        from tap_web.panels.chart import ChartPanelType
        from tap_web.panels.flip_panel import FlipPanelType
        from tap_web.panels.table_panel import TablePanelType
        from tap_web.panels.text_panel import TextPanelType
        from tap_web.registry import panel_type_registry, register_editor

        register_edge_types_from_list(self.edge_types)
        from tap_web.panels.batch_list import BatchListPanelType
        from tap_web.panels.batch_summary import BatchSummaryPanelType
        from tap_web.panels.batch_viewer import BatchViewerPanelType
        from tap_web.panels.editor_panel import EditorPanelType
        from tap_web.panels.sequence_nav import SequenceNavPanelType
        from tap_web.panels.viewer_panel import ViewerPanelType

        panel_type_registry.register("text", TextPanelType)
        panel_type_registry.register("table", TablePanelType)
        panel_type_registry.register("flip", FlipPanelType)
        panel_type_registry.register("viewer", ViewerPanelType)
        panel_type_registry.register("editor", EditorPanelType)
        panel_type_registry.register("chart", ChartPanelType)
        panel_type_registry.register("sequence-nav", SequenceNavPanelType)
        panel_type_registry.register("batch-viewer", BatchViewerPanelType)
        panel_type_registry.register("batch-summary", BatchSummaryPanelType)
        panel_type_registry.register("batch-list", BatchListPanelType)

        class _PanelEditorDescriptor(EditorDescriptor):
            """Redirects /object/panel/.../edit/ to the panel-specific editor."""

            entity_type = "panel"

            def get_editor_initial(self, obj: Any) -> dict[str, Any]:
                return {}

            def handle_save(self, form: Any, obj: Any, request: Any) -> Any:
                raise NotImplementedError

            def get_form_class(self, obj: Any) -> None:
                return None

            def get_extra_context(self, obj: Any) -> dict[str, Any]:
                from django.urls import reverse

                from tap_web.page import build_url_id

                return {
                    "edit_url_override": reverse(
                        "panel-edit", kwargs={"panel_url_id": build_url_id(obj.slug, obj.entity_id)}
                    )
                }

        register_editor(_PanelEditorDescriptor())
