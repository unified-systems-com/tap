"""TAP Web models — Page, Panel, LandingPage.

All tap_web node types declare DEFAULT_DIMENSIONS = WEB_DIMENSIONS
(tap_web.dimensions) to keep web artifacts in their own named partition of the graph.
"""

from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models

from tap_grid.models import BaseModel
from tap_web.dimensions import WEB_DIMENSIONS
from tap_web.exceptions import PageLayoutValidationError, PageSlugValidationError
from tap_web.validation import validate_page_layout, validate_page_slug


class Page(BaseModel):
    """A routable web page that hosts one or more panels."""

    ENTITY_TYPE: ClassVar[str] = "page"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = WEB_DIMENSIONS

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, dict]] = {
        "name": {"type": "string", "minLength": 1},
        "slug": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "layout": {"type": "object"},
        "discoverable": {"type": "boolean"},
        "nav_weight": {"type": "integer"},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name", "slug"]

    # Hotlink contract: panel-id values embedded in layout must exactly match
    # the hotlink.value on the page's outbound USES_PANEL edges.
    HOTLINKS: ClassVar[list[dict]] = [
        {
            "name": "page-panels",
            "field": "layout",
            "selector_type": "simple_path",
            "selector": "columns.*.rows.*.panel-id",
            "edge_direction": "outbound",
            "edge_type": "USES_PANEL",
            "mode": "exact",
        }
    ]

    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]] = {
        "layout": {"validation": "function"},
    }

    name = models.CharField(max_length=255)
    slug = models.CharField(
        max_length=255,
        unique=True,
        help_text="Route path starting with /. Example: /my-page",
    )
    description = models.TextField(blank=True, default="")
    layout = models.JSONField(
        default=dict,
        blank=True,
        help_text="Nested grid layout schema (columns → rows → panel-id slots).",
    )
    discoverable = models.BooleanField(
        default=True,
        help_text=(
            "True if this Page appears in nav-discovery surfaces (palette, "
            "chevron popovers, column view, /__nav-index.json). Pages that "
            "require URL parameters (e.g. /samsite/finding/<entity_id>) set "
            "this False so the discovery surfaces don't link to broken-render "
            "URLs. The Page still resolves on direct visit; only browse-style "
            "discovery is gated. See spec-web-navigation `req-web-nav-page-"
            "discoverable`."
        ),
    )
    nav_weight = models.IntegerField(
        default=0,
        help_text=(
            "Sort-order bias for nav-discovery surfaces. Higher floats up; "
            "negative sinks down; 0 means default (alphabetical within tier). "
            "Convention: +100..+999 for primary user destinations, 0 for "
            "routine pages, -100..-999 for operator/internal pages. "
            "Tiebreaker within a tier is alphabetical by name. Applied to the "
            "palette tree + ranked-search tiebreaker, chevron popovers, "
            "column-view explorer, and /__nav-index.json. See spec-web-"
            "navigation `req-web-nav-page-weight`."
        ),
    )

    class Meta(BaseModel.Meta):
        db_table = "web_page"

    def validate_layout(self) -> None:
        try:
            validate_page_layout(self.layout or {})
        except PageLayoutValidationError as exc:
            raise ValidationError({"layout": [str(exc)]}) from exc

    def validate(self) -> None:
        reserved = _get_reserved_slugs()
        try:
            validate_page_slug(self.slug, reserved_prefixes=reserved)
        except PageSlugValidationError as exc:
            raise ValidationError({"slug": [str(exc)]}) from exc

    def get_name(self) -> str:
        return self.name or ""

    def __str__(self) -> str:
        return self.name or self.slug or ""


class Panel(BaseModel):
    """A data-display component embedded in a Page.

    Each Panel declares a template path (`view`), optional static assets
    (`js`, `css`), and a human-readable `slug` used in its HTMX URL.
    The HTMX endpoint is /panel/<slug>--<entity-uuid>/.
    """

    ENTITY_TYPE: ClassVar[str] = "panel"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = WEB_DIMENSIONS

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, dict]] = {
        "slug": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
        "description": {"type": "string"},
        "view": {"type": "string", "minLength": 1},
        "editor_view": {"type": "string"},
        "config": {"type": "object"},
        "input_vars": {"type": "array", "items": {"type": "string"}},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["slug", "name", "view"]

    slug = models.CharField(
        max_length=255,
        help_text="Kebab-case label used in the HTMX URL alongside the entity UUID. Not globally unique.",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    view = models.CharField(
        max_length=500,
        help_text="Template path rendered by the generic panel view. Example: tap_plugin/<slug>/templates/<entity>_list.html",
    )
    editor_view = models.CharField(
        max_length=500,
        blank=True,
        default="",
        help_text="Template path for the panel editor UI. Optional; only set when the panel supports edit mode.",
    )
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Panel-specific configuration object. Default: {}.",
    )
    input_vars = models.JSONField(
        default=list,
        blank=True,
        help_text="Declared panel input variable names expected at runtime. Default: [].",
    )

    class Meta(BaseModel.Meta):
        db_table = "web_panel"

    def get_name(self) -> str:
        return self.name or ""

    def __str__(self) -> str:
        return self.name or self.slug or ""


class LandingPage(BaseModel):
    """Indirection node that designates which Page is served at the root URL.

    The earliest-created LandingPage (by entity__created_at) is used when
    multiple LandingPage nodes exist.
    """

    ENTITY_TYPE: ClassVar[str] = "landing_page"
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = WEB_DIMENSIONS

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, dict]] = {
        "name": {"type": "string"},
        "description": {"type": "string"},
    }

    name = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")

    class Meta(BaseModel.Meta):
        db_table = "web_landing_page"

    def get_name(self) -> str:
        return self.name or ""

    def __str__(self) -> str:
        return self.name or "LandingPage"


def _get_reserved_slugs() -> list[str]:
    """Return the reserved slug prefixes collected across all app configs.

    See tap_web.reserved.get_reserved_url_prefixes() — each app declares the
    top-level prefixes it mounts via `reserved_url_prefixes`, unioned with the
    project-level mounts.
    """
    from tap_web.reserved import get_reserved_url_prefixes

    try:
        return get_reserved_url_prefixes()
    except Exception:  # noqa: BLE001
        return []
