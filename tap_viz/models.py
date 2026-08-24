"""tap_viz models — Viz layout, projection, elevation, and arrangement entities."""

from typing import Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models

from tap_grid.models import BaseModel

# ---------------------------------------------------------------------------
# Arrangement definition schema
# ---------------------------------------------------------------------------

_ARRANGEMENT_DEFINITION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["anchor", "members", "positioning", "distribution"],
    "additionalProperties": False,
    "properties": {
        "anchor": {
            "type": "object",
            "required": ["gryphon"],
            "additionalProperties": False,
            "properties": {
                "gryphon": {"type": "string", "minLength": 1},
            },
        },
        "members": {
            "type": "object",
            "required": ["gryphon"],
            "additionalProperties": False,
            "properties": {
                "gryphon": {"type": "string", "minLength": 1},
            },
        },
        "positioning": {"type": "string", "enum": ["horizontal", "vertical"]},
        "distribution": {"type": "string", "enum": ["even"]},
        # Optional anchor-relative placement (req-viz-arrangement-span).
        # When `span_px` is present, even-distribution lays members out across
        # exactly that many pixels along the positioning axis, starting at
        # anchor + `anchor_offset_px` (default 0). Both are optional; when
        # absent the legacy behavior uses members' current min..max span.
        "span_px": {"type": "number", "minimum": 0},
        "anchor_offset_px": {"type": "number"},
    },
}


class Arrangement(BaseModel):
    """A declarative post-layout positioning rule.

    Arrangements reposition nodes already on the Cytoscape graph into structured
    formations relative to an anchor node. They are pure data — no executable
    code — and are connected to layouts via USES_ARRANGEMENT edges (hotlinks).
    See spec-viz-arrangement.md.

    TAP-IMPLEMENTS: req-viz-arrangement-model@058264396ff1/b7c9123a5cfe (derivation) — the
        TAP-managed entity that stores the declarative arrangement rule.
    TAP-IMPLEMENTS: req-viz-arrangement-definition@9a086380314a/b7c9123a5cfe (derivation) —
        the definition JSON shape (anchor, members, positioning, distribution) is
        schema-validated here via FIELD_VALIDATION_SCHEMA; the runtime executes what
        this model admits.
    """

    ENTITY_TYPE: ClassVar[str] = "arrangement"

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, dict]] = {
        "name": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "definition": {"type": "object"},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]] = {
        "definition": {
            "validation": "jsonschema",
            "schema": _ARRANGEMENT_DEFINITION_SCHEMA,
        },
    }

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    definition = models.JSONField(
        default=dict,
        blank=True,
        help_text="Declarative arrangement rule: anchor, members, positioning, distribution.",
    )

    class Meta(BaseModel.Meta):
        db_table = "tap_arrangement"
        ordering = ["-entity__created_at"]

    def get_name(self) -> str:
        return self.name or ""

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Layout (v1) — dual-mode definition: optional js_file (layout_module) and/or
# optional ordered arrangements list. See spec-viz-layouts.md.
# ---------------------------------------------------------------------------

_LAYOUT_DEFINITION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
    "properties": {
        "js_file": {"type": "string", "minLength": 1},
        "arrangements": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "arrangement_control": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "mode": {"type": "string", "enum": ["all", "none"]},
            },
        },
    },
}


class Layout(BaseModel):
    """A reusable TAP viz layout entity.

    A Layout entity may carry a `js_file` reference (the layout_module — the
    JavaScript file whose `execute(context)` the runtime invokes for broad-strokes
    positioning) and/or an ordered list of arrangement entity IDs (declarative
    polish applied after the module runs). Both are optional; layouts may use
    either, both, or neither. See spec-viz-layouts.md.

    TAP-IMPLEMENTS: req-viz-layout-artifact@dbd78fbb7bd6/0d4e45f10a55 (derivation) — the
        TAP-managed layout artifact whose definition carries the file-backed module
        reference.
    TAP-IMPLEMENTS: req-viz-layout-dual-mode@c2ac6c52a142/0d4e45f10a55 (derivation) — the
        dual-mode definition contract: optional js_file, optional ordered arrangements,
        both or neither, admitted by the definition schema.
    TAP-IMPLEMENTS: req-viz-arrangement-layout-hotlink@958618d0f494/0d4e45f10a55 (derivation) —
        the layout-arrangements HOTLINK declaration: definition arrangements.* entries
        become validated USES_ARRANGEMENT edges.
    """

    ENTITY_TYPE: ClassVar[str] = "layout"

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, dict]] = {
        "name": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "definition": {"type": "object"},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]] = {
        "definition": {
            "validation": "jsonschema",
            "schema": _LAYOUT_DEFINITION_SCHEMA,
        },
    }

    HOTLINKS: ClassVar[list[dict]] = [
        {
            "name": "layout-arrangements",
            "field": "definition",
            "selector_type": "simple_path",
            "selector": "arrangements.*",
            "edge_direction": "outbound",
            "edge_type": "USES_ARRANGEMENT",
            "mode": "exact",
        },
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    definition = models.JSONField(
        default=dict,
        blank=True,
        help_text="Layout definition: optional js_file (layout_module) and/or arrangements (ordered IDs).",
    )

    class Meta(BaseModel.Meta):
        db_table = "tap_layout"
        ordering = ["-entity__created_at"]

    def get_name(self) -> str:
        return self.name or ""

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# Elevation — zoom-driven stage; composes Layout entities via USES_LAYOUT and
# declares double-tap navigation via NAVIGATES_TO. See spec-viz-elevation.md.
# ---------------------------------------------------------------------------

_ELEVATION_DEFINITION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["zoom"],
    "additionalProperties": True,
    "properties": {
        "zoom": {"type": "number"},
        "description": {"type": "string"},
        "layouts": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "double_tap_targets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["entity_type", "target_elevation_id"],
                "additionalProperties": False,
                "properties": {
                    "entity_type": {"type": "string", "minLength": 1},
                    "target_elevation_id": {"type": "string", "minLength": 1},
                },
            },
        },
    },
}


class Elevation(BaseModel):
    """A zoom-driven stage within a projection.

    Elevations compose Layout entities (via USES_LAYOUT) and declare double-tap
    navigation targets to other elevations (via NAVIGATES_TO). The runtime
    behavior — zoom-threshold watching, double-tap pan-zoom, hysteresis — is
    orchestrated by the projection runtime; this model is the structural
    entity. See spec-viz-elevation.md.
    """

    ENTITY_TYPE: ClassVar[str] = "elevation"

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, dict]] = {
        "name": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "definition": {"type": "object"},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name", "definition"]

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]] = {
        "definition": {
            "validation": "jsonschema",
            "schema": _ELEVATION_DEFINITION_SCHEMA,
        },
    }

    HOTLINKS: ClassVar[list[dict]] = [
        {
            "name": "elevation-layouts",
            "field": "definition",
            "selector_type": "simple_path",
            "selector": "layouts.*",
            "edge_direction": "outbound",
            "edge_type": "USES_LAYOUT",
            "mode": "exact",
        },
        {
            "name": "elevation-navigates-to",
            "field": "definition",
            "selector_type": "simple_path",
            "selector": "double_tap_targets.*.target_elevation_id",
            "edge_direction": "outbound",
            "edge_type": "NAVIGATES_TO",
            "mode": "exact",
        },
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    definition = models.JSONField(
        default=dict,
        blank=True,
        help_text="Elevation definition: zoom, layouts (ordered IDs), double_tap_targets.",
    )

    class Meta(BaseModel.Meta):
        db_table = "tap_elevation"
        ordering = ["-entity__created_at"]

    def get_name(self) -> str:
        return self.name or ""

    def __str__(self) -> str:
        return self.name


_PROJECTION_DEFINITION_SCHEMA: dict = {
    "type": "object",
    "required": ["default_elevation_id", "elevations"],
    "additionalProperties": True,
    "properties": {
        "node_style": {
            "oneOf": [
                {"type": "string", "enum": ["default", "icon-badge"]},
                {
                    "type": "object",
                    "required": ["mode"],
                    "additionalProperties": False,
                    "properties": {
                        "mode": {"type": "string", "enum": ["default", "icon-badge"]},
                        "exclude_types": {"type": "array", "items": {"type": "string"}},
                    },
                },
            ],
        },
        "status_badges": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "refresh_seconds": {"type": "number", "minimum": 0},
                "badge_sets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["name", "color", "population"],
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string", "minLength": 1},
                            "label": {
                                "type": "string",
                                "minLength": 1,
                                "description": "Human-readable badge-set label used as the info-window section header. Falls back to `name` when absent.",
                            },
                            "color": {"type": "string", "minLength": 1},
                            "text_color": {"type": "string", "minLength": 1},
                            "info_window": {
                                "type": "object",
                                "required": ["search_id"],
                                "additionalProperties": False,
                                "properties": {
                                    "search_id": {
                                        "type": "string",
                                        "minLength": 1,
                                        "description": "UUID of a stored Search that returns rows of {entity_id, name} for the detail panel opened on badge/host click.",
                                    },
                                    "inputs": {
                                        "type": "object",
                                        "description": "Static inputs forwarded to the Search's $var bindings.",
                                    },
                                },
                            },
                            "population": {
                                "type": "object",
                                "required": ["type"],
                                "additionalProperties": True,
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": ["static_by_node_type", "search"],
                                    },
                                    "rules": {
                                        "type": "array",
                                        "items": {
                                            "type": "object",
                                            "required": ["entity_type", "count"],
                                            "additionalProperties": False,
                                            "properties": {
                                                "entity_type": {"type": "string", "minLength": 1},
                                                "count": {"type": "integer", "minimum": 0},
                                            },
                                        },
                                    },
                                    "search_id": {
                                        "type": "string",
                                        "minLength": 1,
                                        "description": "UUID of a stored Search whose rows return {entity_id, count} pairs. Used when type=search.",
                                    },
                                    "inputs": {
                                        "type": "object",
                                        "description": "Runtime inputs forwarded to the Search's $var bindings. Used when type=search.",
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
        "min_zoom": {
            "oneOf": [
                {"type": "string", "enum": ["fit"]},
                {"type": "number", "exclusiveMinimum": 0},
            ],
        },
        "lock_nodes": {"type": "boolean"},
        # v1: elevations is an ordered array of Elevation entity UUIDs.
        # default_elevation_id is the single Elevation that is the landing point.
        # Both are validated by hotlinks; their cross-set membership is enforced in validate().
        "default_elevation_id": {"type": "string", "minLength": 1},
        "elevations": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
    },
}


class Projection(BaseModel):
    """A reusable TAP Viz projection — a coherent multi-elevation visual perspective.

    A projection composes Elevation entities into a zoom-driven visual journey
    and designates a single Elevation as the landing point. Graph panels reference
    a projection via `USES_PROJECTION`. See `spec-viz-projection.md`.

    Composition is via two hotlinks:
      - USES_ELEVATION (ordered, exact) — every elevation in the journey
      - USES_DEFAULT_ELEVATION (single, exact) — the landing point on initial load

    TAP-IMPLEMENTS: req-viz-projection-artifact@97e6eb81eca2/9af7d486ddbb (derivation) — the
        first-class TAP Viz projection artifact.
    TAP-IMPLEMENTS: req-viz-projection-entity-structure@a46a83f09d44/9af7d486ddbb (derivation) —
        elevations-plus-default composition via the two typed hotlinks, with the
        cross-hotlink invariant (default must appear in elevations) enforced in
        validate().
    """

    ENTITY_TYPE: ClassVar[str] = "projection"

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, dict]] = {
        "name": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "definition": {"type": "object"},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name", "definition"]

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]] = {
        "name": {
            "validation": "jsonschema",
            "schema": {"type": "string", "minLength": 1},
        },
        "definition": {
            "validation": "jsonschema",
            "schema": _PROJECTION_DEFINITION_SCHEMA,
        },
    }

    HOTLINKS: ClassVar[list[dict]] = [
        {
            "name": "projection-elevations",
            "field": "definition",
            "selector_type": "simple_path",
            "selector": "elevations.*",
            "edge_direction": "outbound",
            "edge_type": "USES_ELEVATION",
            "mode": "exact",
        },
        {
            "name": "projection-default-elevation",
            "field": "definition",
            "selector_type": "simple_path",
            "selector": "default_elevation_id",
            "edge_direction": "outbound",
            "edge_type": "USES_DEFAULT_ELEVATION",
            "mode": "exact",
        },
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    definition = models.JSONField(
        default=dict,
        blank=True,
        help_text="Projection definition: elevations (ordered IDs), default_elevation_id, chrome.",
    )

    class Meta(BaseModel.Meta):
        db_table = "tap_projection"
        ordering = ["-entity__created_at"]

    def get_name(self) -> str:
        return self.name or ""

    def __str__(self) -> str:
        return self.name

    def validate(self) -> None:
        """Cross-hotlink invariant: default_elevation_id must appear in elevations."""
        if not isinstance(self.definition, dict):
            return

        elevations = self.definition.get("elevations")
        default_id = self.definition.get("default_elevation_id")

        if not isinstance(elevations, list) or not isinstance(default_id, str):
            return

        if default_id not in elevations:
            raise ValidationError(
                {"definition": [f"default_elevation_id '{default_id}' must also appear in 'elevations'."]}
            )
