"""tap_viz admin configuration."""

from django.contrib import admin

from tap_grid.admin import ReadOnlyGraphAdmin
from tap_viz.models import Layout


@admin.register(Layout)
class LayoutAdmin(ReadOnlyGraphAdmin, admin.ModelAdmin):  # type: ignore[type-arg]
    """Admin interface for Layout model."""

    list_display = ["name", "entity_id"]
    search_fields = ["name", "description"]
    readonly_fields = ["entity"]
