"""Viewer Panel — built-in read-only panel for entity field display.

Displays the fields of a single entity using its registered EditorDescriptor
to discover field names, labels, and current values.

Subject binding (from request query params):
  request.GET["entity_id"]    — UUID of the target entity.
  request.GET["entity_type"]  — entity type slug.

If neither is present the panel renders an empty/no-subject state.

Rendering:
  Server-side only. No editor in v1.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.urls import reverse

from tap_web.page import build_url_id

if TYPE_CHECKING:
    from django.http import HttpRequest

    from tap_web.models import Panel

logger = logging.getLogger(__name__)


class ViewerPanelType:
    """Built-in viewer panel type — read-only entity field inspector."""

    slug = "viewer"
    label = "Viewer Panel"
    view = "tap_web/panels/viewer_panel.html"
    editor_view = ""
    config_defaults: dict[str, Any] = {}
    form_class = None

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        """Resolve the subject entity and return field display context.

        Subject resolution: reads entity_id and entity_type from request.GET.

        Returns context with viewer_obj, viewer_field_pairs, viewer_entity_type,
        viewer_edit_url, viewer_obj_name, and panel_render_url (for Panel entities).
        """
        entity_id = request.GET.get("entity_id", "")
        entity_type = request.GET.get("entity_type", "")

        if not entity_id or not entity_type:
            return {"viewer_obj": None, "viewer_field_pairs": [], "viewer_error": "No subject configured."}

        return _get_viewer_context(entity_id, entity_type)


def _format_value(value: Any) -> tuple[str, bool]:
    """Format a model field value for display.

    Returns: (display_text, is_block) — is_block is True for multi-line
    values (e.g. pretty-printed JSON) the template should render in a
    code block.
    """
    import json
    from datetime import date, datetime

    if value is None:
        return ("", False)
    if isinstance(value, bool):
        return ("true" if value else "false", False)
    if isinstance(value, (dict, list)):
        if not value:
            return ("", False)
        rendered = json.dumps(value, indent=2, sort_keys=True, default=str)
        return (rendered, "\n" in rendered)
    # datetime is a subclass of date — check it first. A datetime is an absolute
    # instant, so it localizes to the viewer's browser zone through the shared
    # <time> helper (spec-web-time-display, req-web-time-single-helper). A bare
    # date has no time or zone; localizing it could shift the calendar day, so it
    # stays as a plain ISO date.
    if isinstance(value, datetime):
        from tap_web.timefmt import render_local_time

        return (render_local_time(value), False)
    if isinstance(value, date):
        return (value.isoformat(), False)
    text = str(value)
    return (text, "\n" in text)


def _model_field_pairs(obj: Any) -> list[tuple[str, str, bool]]:
    """Walk obj's declared Django fields → display tuples.

    The fallback used when no editor descriptor is registered for the
    entity type. Skips the entity FK chain, primary keys, and the spine's
    own bookkeeping; keeps the model's own declared fields in declaration
    order.
    """
    # batch_id + flip_map are BaseModel spine fields surfaced separately by
    # the FLIP panel below; suppressing them here keeps Details focused on
    # the model's own typed fields (per the entity-page story: identity →
    # context → facts → provenance, with each beat in one place).
    SKIP = {"id", "entity_id", "batch_id", "flip_map"}
    pairs: list[tuple[str, str, bool]] = []
    seen: set[str] = set()
    for field in obj._meta.get_fields():
        if field.is_relation or field.name in SKIP or field.name in seen:
            continue
        seen.add(field.name)
        value = getattr(obj, field.name, None)
        text, is_block = _format_value(value)
        label = str(field.verbose_name or field.name).replace("_", " ").title()
        pairs.append((label, text, is_block))
    return pairs


def _get_viewer_context(entity_id: str, entity_type: str) -> dict[str, Any]:
    """Build viewer context for a single entity."""
    from tap_grid.registry import get_model_class
    from tap_web.registry import get_editor

    try:
        model_cls = get_model_class(entity_type)
    except KeyError:
        return {"viewer_obj": None, "viewer_field_pairs": [], "viewer_error": f"Unknown entity type '{entity_type}'."}

    try:
        obj = model_cls.objects.select_related("entity").get(entity__pk=entity_id)
    except model_cls.DoesNotExist:
        return {"viewer_obj": None, "viewer_field_pairs": [], "viewer_error": f"Entity '{entity_id}' not found."}

    descriptor = get_editor(entity_type)

    field_pairs: list[tuple[str, str, bool]] = []
    if descriptor is not None:
        initial = descriptor.get_editor_initial(obj)
        form_class = descriptor.get_form_class(obj)
        if form_class is not None:
            form = form_class(initial=initial)
            for name, field in form.fields.items():
                label = str(field.label or name.replace("_", " ").title())
                value = initial.get(name, "")
                text, is_block = _format_value(value)
                field_pairs.append((label, text, is_block))

    # Universal fallback: when no editor (or no form) gave us a field list,
    # walk the model's own declared fields. Gives every TAP-managed entity
    # type a baseline drill-down without requiring an editor first.
    if not field_pairs:
        field_pairs = _model_field_pairs(obj)

    extra = descriptor.get_extra_context(obj) if descriptor else {}

    # Build URL ID from object slug + entity_id.
    slug = getattr(obj, "slug", "") or obj.entity.name or ""
    object_url_id = build_url_id(slug, entity_id)
    edit_url = extra.pop(
        "edit_url_override",
        reverse("object-edit", kwargs={"entity_type": entity_type, "object_url_id": object_url_id}),
    )

    # Panel preview URL for panel entities.
    panel_render_url = ""
    if entity_type == "panel":
        panel_slug = getattr(obj, "slug", "") or ""
        panel_render_url = reverse("panel", kwargs={"panel_url_id": build_url_id(panel_slug, entity_id)})

    # Resolve type icon URL once server-side so the template renders a plain
    # <img>. The icon lookup needs the EntityType row (a string slug isn't
    # enough); skip silently if either the lookup or icon-file misses.
    icon_url = ""
    try:
        from tap_grid.icon import resolve_icon_url
        from tap_grid.models import EntityType

        et_row = EntityType.objects.filter(slug=entity_type).first()
        if et_row is not None:
            icon_url = resolve_icon_url(et_row) or ""
    except Exception:  # noqa: BLE001 — icon resolution is best-effort visual chrome
        icon_url = ""

    return {
        "viewer_obj": obj,
        "viewer_obj_name": str(obj),
        "viewer_entity_type": entity_type,
        "viewer_icon_url": icon_url,
        "viewer_field_pairs": field_pairs,
        "viewer_edit_url": edit_url,
        "viewer_panel_render_url": panel_render_url,
        "viewer_error": None,
        **extra,
    }
