"""Editor Panel — built-in panel for entity editing via EditorDescriptor.

Renders the edit form for a single entity, handling both GET (form display)
and POST (form validation + save) via the panel endpoint.

Subject binding (from request query params):
  request.GET["entity_id"]    — UUID of the target entity.
  request.GET["entity_type"]  — entity type slug.

POST handling:
  The panel_view dispatcher calls handle_post() when request.method == "POST"
  and the panel type defines it. Validates via the EditorDescriptor's form_class,
  delegates save to descriptor.handle_save(), then re-renders the form with a
  success or error message.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse

from tap_web.page import build_url_id

if TYPE_CHECKING:
    from django.http import HttpRequest

    from tap_web.models import Panel

logger = logging.getLogger(__name__)


class EditorPanelType:
    """Built-in editor panel type — form-based entity editing."""

    slug = "editor"
    label = "Editor Panel"
    view = "tap_web/panels/editor_panel.html"
    editor_view = ""
    config_defaults: dict[str, Any] = {}
    form_class = None

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        """Resolve the subject entity and return editor form context."""
        entity_id = request.GET.get("entity_id", "")
        entity_type = request.GET.get("entity_type", "")

        if not entity_id or not entity_type:
            return {"editor_obj": None, "editor_form": None, "editor_error": "No subject configured."}

        return _get_editor_context(entity_id, entity_type)

    @classmethod
    def handle_post(cls, panel: Panel, request: HttpRequest) -> HttpResponse:
        """Handle form submission: validate, save, re-render panel fragment."""
        entity_id = request.GET.get("entity_id", "")
        entity_type = request.GET.get("entity_type", "")

        if not entity_id or not entity_type:
            return render(
                request,
                cls.view,
                {
                    "panel": panel,
                    "editor_obj": None,
                    "editor_form": None,
                    "editor_error": "No subject configured.",
                },
            )

        from tap_grid.registry import get_model_class
        from tap_web.registry import get_editor

        try:
            model_cls = get_model_class(entity_type)
            obj = model_cls.objects.select_related("entity").get(entity__pk=entity_id)
        except KeyError, Exception:
            return render(
                request,
                cls.view,
                {
                    "panel": panel,
                    "editor_obj": None,
                    "editor_form": None,
                    "editor_error": f"Entity '{entity_id}' not found.",
                },
            )

        descriptor = get_editor(entity_type)
        if descriptor is None:
            return render(
                request,
                cls.view,
                {
                    "panel": panel,
                    "editor_obj": obj,
                    "editor_form": None,
                    "editor_error": f"No editor registered for '{entity_type}'.",
                },
            )

        form_class = descriptor.get_form_class(obj)
        if form_class is None:
            return render(
                request,
                cls.view,
                {
                    "panel": panel,
                    "editor_obj": obj,
                    "editor_form": None,
                    "editor_error": f"No form registered for '{entity_type}'.",
                },
            )

        form = form_class(request.POST)
        editor_template = descriptor.get_editor_template(obj)
        success_message = ""

        if form.is_valid():
            descriptor.handle_save(form, obj, request)
            # Re-fetch object after save, rebuild form with fresh initial data.
            obj = model_cls.objects.select_related("entity").get(entity__pk=entity_id)
            initial = descriptor.get_editor_initial(obj)
            form = form_class(initial=initial)
            success_message = "Saved successfully."

        slug = getattr(obj, "slug", "") or obj.entity.name or ""
        object_url_id = build_url_id(slug, entity_id)
        view_url = reverse("object-view", kwargs={"entity_type": entity_type, "object_url_id": object_url_id})

        ctx = {
            "panel": panel,
            "editor_obj": obj,
            "editor_obj_name": str(obj),
            "editor_entity_type": entity_type,
            "editor_form": form,
            "editor_template": editor_template,
            "editor_view_url": view_url,
            "editor_error": None,
            "editor_success": success_message,
            "editor_query_string": request.GET.urlencode(),
        }
        return render(request, cls.view, ctx)


def _get_editor_context(entity_id: str, entity_type: str) -> dict[str, Any]:
    """Build editor form context for a single entity."""
    from tap_grid.registry import get_model_class
    from tap_web.registry import get_editor

    try:
        model_cls = get_model_class(entity_type)
    except KeyError:
        return {"editor_obj": None, "editor_form": None, "editor_error": f"Unknown entity type '{entity_type}'."}

    try:
        obj = model_cls.objects.select_related("entity").get(entity__pk=entity_id)
    except model_cls.DoesNotExist:
        return {"editor_obj": None, "editor_form": None, "editor_error": f"Entity '{entity_id}' not found."}

    descriptor = get_editor(entity_type)
    if descriptor is None:
        return {"editor_obj": obj, "editor_form": None, "editor_error": f"No editor registered for '{entity_type}'."}

    form_class = descriptor.get_form_class(obj)
    if form_class is None:
        extra = descriptor.get_extra_context(obj)
        override = extra.get("edit_url_override")
        if override:
            return {
                "editor_obj": obj,
                "editor_form": None,
                "editor_error": None,
                "editor_redirect_url": override,
            }
        return {"editor_obj": obj, "editor_form": None, "editor_error": f"No form registered for '{entity_type}'."}

    initial = descriptor.get_editor_initial(obj)
    form = form_class(initial=initial)
    editor_template = descriptor.get_editor_template(obj)

    slug = getattr(obj, "slug", "") or obj.entity.name or ""
    object_url_id = build_url_id(slug, entity_id)
    view_url = reverse("object-view", kwargs={"entity_type": entity_type, "object_url_id": object_url_id})

    return {
        "editor_obj": obj,
        "editor_obj_name": str(obj),
        "editor_entity_type": entity_type,
        "editor_form": form,
        "editor_template": editor_template,
        "editor_view_url": view_url,
        "editor_error": None,
        "editor_success": "",
        "editor_query_string": "",
    }
