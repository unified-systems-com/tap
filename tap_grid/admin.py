"""TAP Core Admin — registers Entity, EntityType, Edge, Batch, BatchEvent,
and Registry inspection views.

The canonical User is owned and registered by tap_auth (req-tap-auth-app);
tap_grid no longer owns the user model or its admin.
"""

from typing import Any

from django.contrib import admin
from django.db import models
from django.db.models import QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.template.response import TemplateResponse
from django.urls import path, reverse
from simple_history.admin import SimpleHistoryAdmin

from tap_auth import policy
from tap_auth.capabilities import READ_CAPABILITY
from tap_grid.caller_context import get_caller_context
from tap_grid.models import Batch, BatchEvent, Edge, Entity, EntityType
from tap_grid.registry import Registry, ScopedRegistry, meta_registry


class GridReadAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Admin reads graph rows only for an actor holding `grid.read` (req-tap-auth-policy-6, Issue# 961 - tap).

    `is_superuser` grants no TAP capability (req-tap-auth-policy-5), so without this a superuser
    outside tap_admin passed admin's own checks and read the rows: the ORM read backstop failed
    the page with a 500, or, for the Entity spine it does not guard, the rows were shown. Admin
    now asks TAP's policy first, and refuses with a 403.

    Two hooks, because Django asks in two places. `has_view_permission` hides the model from the
    admin index and refuses the pages that check permission before reading. `get_queryset`
    authorizes every read the admin makes, which covers the change, delete and history views:
    Django fetches their object before it checks permission. A denial there is a
    `CapabilityDenied`, which `CallerContextMiddleware` answers with a 403.
    """

    def has_view_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return policy.can(get_caller_context(), READ_CAPABILITY) and super().has_view_permission(request, obj)

    def get_queryset(self, request: HttpRequest) -> QuerySet[Any]:
        policy.authorize(get_caller_context(), READ_CAPABILITY, operation=f"admin {self.opts.label}")
        return super().get_queryset(request)


class ReadOnlyGraphAdmin(GridReadAdmin):
    """Admin shows graph rows and never writes them (req-tap-auth-policy-6, Issue# 957 - tap).

    A graph row changes only through the service layer's write pipeline, which records its batch,
    provenance and history. The write guard already refuses admin's single-object saves and deletes.
    Its "delete selected" action deleted a queryset below the guard and left no record. So no add,
    no change, no delete and no bulk actions: superuser break-glass covers accounts and auth
    objects, not the grid. The EntityType catalog is declared by plugins at boot, so nothing
    legitimate edits it here either (Issue# 961 - tap).
    """

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def get_actions(self, request: HttpRequest) -> dict[str, Any]:
        return {}


@admin.register(Batch)
class BatchAdmin(ReadOnlyGraphAdmin, SimpleHistoryAdmin):
    """Admin for Batch model with history support."""

    list_display = ["entity", "status", "source", "actor", "started_at", "closed_at"]
    list_filter = ["status", "source"]
    search_fields = ["entity__name", "source", "error_message"]
    readonly_fields = ["entity", "started_at"]
    date_hierarchy = "started_at"
    ordering = ["-started_at"]


@admin.register(BatchEvent)
class BatchEventAdmin(GridReadAdmin):
    """Admin for BatchEvent model (read-only audit log)."""

    list_display = ["id", "batch", "event_type", "entity_type", "model_name", "timestamp", "actor"]
    list_filter = ["event_type", "entity_type", "model_name"]
    search_fields = ["entity_id", "entity_type", "model_name"]
    readonly_fields = [
        "id",
        "batch",
        "event_type",
        "entity_id",
        "entity_type",
        "model_name",
        "timestamp",
        "actor",
        "metadata",
    ]
    date_hierarchy = "timestamp"
    ordering = ["-timestamp"]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: BatchEvent | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: BatchEvent | None = None) -> bool:
        return False


@admin.register(Entity)
class EntityAdmin(ReadOnlyGraphAdmin):
    list_display = ["id", "entity_type", "name", "created_at"]
    list_filter = ["entity_type", "created_at"]
    search_fields = ["name", "entity_type"]
    readonly_fields = ["id", "created_at", "updated_at", "originating_grid_id"]
    ordering = ["-created_at"]


@admin.register(EntityType)
class EntityTypeAdmin(ReadOnlyGraphAdmin):
    list_display = ["slug", "name", "icon", "plugin_name"]
    list_filter = ["plugin_name"]
    search_fields = ["slug", "name"]


@admin.register(Edge)
class EdgeAdmin(ReadOnlyGraphAdmin):
    list_display = ["id", "from_entity", "edge_type", "to_entity"]
    list_filter = ["edge_type"]
    search_fields = ["edge_type"]
    readonly_fields = ["id"]
    raw_id_fields = ["entity", "from_entity", "to_entity"]


# ---------------------------------------------------------------------------
# Registry admin — read-only operational views backed by in-process state.
# RegistryProxy is an unmanaged model (no DB table) used solely to mount
# custom admin views under /admin/tap_grid/registryproxy/.
# ---------------------------------------------------------------------------


class RegistryProxy(models.Model):
    """No-table proxy model used purely to mount registry admin views."""

    class Meta:
        app_label = "tap_grid"
        managed = False
        verbose_name = "Registry"
        verbose_name_plural = "Registries"

    def __str__(self) -> str:
        return "Registry"


def _curate_value(value: Any) -> str:
    """Return a safe human-readable summary of a registry value."""
    if isinstance(value, (Registry, ScopedRegistry)):
        entry_count = len(value.keys())
        return f"{type(value).__name__}(name={value._name!r}, entries={entry_count})"
    if isinstance(value, type):
        return f"{value.__module__}.{value.__qualname__}"
    if callable(value):
        module = getattr(value, "__module__", "")
        qualname = getattr(value, "__qualname__", getattr(value, "__name__", ""))
        return f"{module}.{qualname}" if module else qualname
    return repr(value)[:120]


def _registry_row(reg: Registry[Any] | ScopedRegistry[Any], request: HttpRequest) -> dict[str, Any]:
    """Build a context dict for a single registry index row."""
    is_scoped = isinstance(reg, ScopedRegistry)
    scope_count = len(reg.scopes()) if isinstance(reg, ScopedRegistry) else None
    detail_url = reverse("admin:tap_grid_registryproxy_detail", args=[reg._name])
    return {
        "name": reg._name,
        "title": reg.title,
        "description": reg.description,
        "creator": reg.creator,
        "registry_class": "ScopedRegistry" if is_scoped else "Registry",
        "entry_count": len(reg.keys()),
        "scope_count": scope_count,
        "detail_url": detail_url,
    }


@admin.register(RegistryProxy)
class RegistryProxyAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Read-only admin surface for live registry inspection."""

    def has_view_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return request.user.is_staff

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def get_urls(self) -> list[Any]:
        urls = super().get_urls()
        custom_urls = [
            path(
                "<str:registry_name>/",
                self.admin_site.admin_view(self.registry_detail_view),
                name="tap_grid_registryproxy_detail",
            ),
        ]
        return custom_urls + urls

    def changelist_view(self, request: HttpRequest, extra_context: dict[str, Any] | None = None) -> HttpResponse:
        """Override to render live registry index instead of a model changelist."""
        rows = [_registry_row(meta_registry, request)]
        for reg in meta_registry.all().values():
            rows.append(_registry_row(reg, request))

        total_entries = sum(r["entry_count"] for r in rows)

        context = {
            **self.admin_site.each_context(request),
            "title": "Registries",
            "rows": rows,
            "total_registries": len(rows),
            "total_entries": total_entries,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/tap_grid/registryproxy/change_list.html",
            context,
        )

    def registry_detail_view(self, request: HttpRequest, registry_name: str) -> HttpResponse:
        """Render a read-only detail page for a single registry."""
        if registry_name == "__meta__":
            reg: Registry[Any] | ScopedRegistry[Any] = meta_registry
        else:
            reg = meta_registry.get_optional(registry_name)  # type: ignore[assignment]
            if reg is None:
                raise Http404(f"No registry named {registry_name!r}")

        is_scoped = isinstance(reg, ScopedRegistry)
        entry_rows: list[dict[str, str]] = []

        if is_scoped:
            for scope, scope_data in reg.all().items():
                for key, value in scope_data.items():
                    entry_rows.append(
                        {
                            "scope": scope,
                            "short_key": key,
                            "fq_key": f"{scope}:{key}",
                            "value_summary": _curate_value(value),
                        }
                    )
            entry_rows.sort(key=lambda r: r["fq_key"])
        else:
            for key, value in reg.all().items():
                entry_rows.append({"key": key, "value_summary": _curate_value(value)})
            entry_rows.sort(key=lambda r: r["key"])

        index_url = reverse("admin:tap_grid_registryproxy_changelist")

        scope_count = len(reg.scopes()) if isinstance(reg, ScopedRegistry) else None
        context = {
            **self.admin_site.each_context(request),
            "title": reg.title,
            "reg_name": reg._name,
            "reg_title": reg.title,
            "reg_description": reg.description,
            "reg_creator": reg.creator,
            "registry_class": "ScopedRegistry" if is_scoped else "Registry",
            "entry_count": len(reg.keys()),
            "scope_count": scope_count,
            "is_scoped": is_scoped,
            "entry_rows": entry_rows,
            "index_url": index_url,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/tap_grid/registryproxy/registry_detail.html",
            context,
        )
