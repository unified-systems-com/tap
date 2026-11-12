"""TAP Web URL configuration.

URL patterns (evaluated in order):
    /panel/<slug>--<uuid>/edit/                Panel editor
    /panel/<slug>--<uuid>/                     Panel HTMX fragment endpoint
    /object/<entity-type>/<slug>--<uuid>/edit/ Generic object editor
    /object/<entity-type>/<slug>--<uuid>/      Generic object viewer
    /                                          Landing page (or placeholder if none configured)
    /plugins/<slug>/...                        Plugin routes (req-web-page-plugin-urls)
    /<path:page_slug>                          Catch-all dynamic page resolution

The catch-all must come last within this file.
In tap/urls.py, tap_web must be the final include (after admin, api, viz)
because path("") matches any prefix and would shadow other apps' routes.
"""

import importlib
import importlib.util

from django.apps import apps
from django.urls import include, path
from django.urls.resolvers import URLResolver

from tap_plugins.base import TapPluginConfig
from tap_web import views


def plugin_urlpatterns() -> list[URLResolver]:
    """Mount each installed plugin's ``urls`` module at ``plugins/<label>/`` (req-web-page-plugin-urls).

    A plugin without a ``urls`` module contributes nothing. The mount takes the plugin's label as
    both its application and instance namespace, so ``reverse("<label>:<name>")`` resolves.
    """
    mounted: list[URLResolver] = []
    for config in apps.get_app_configs():
        if not isinstance(config, TapPluginConfig):
            continue
        module_name = f"{config.name}.urls"
        if importlib.util.find_spec(module_name) is None:
            continue
        patterns = list(importlib.import_module(module_name).urlpatterns)
        mounted.append(path(f"plugins/{config.label}/", include((patterns, config.label), namespace=config.label)))
    return mounted


urlpatterns = [
    path("panel/<str:panel_url_id>/edit/", views.panel_edit_view, name="panel-edit"),
    path("panel/<str:panel_url_id>/", views.panel_view, name="panel"),
    path("object/<str:entity_type>/<str:object_url_id>/edit/", views.object_edit_view, name="object-edit"),
    path("object/<str:entity_type>/<str:object_url_id>/", views.object_view, name="object-view"),
    path("__nav-index.json", views.nav_index_view, name="nav-index"),
    path("", views.landing_view, name="landing"),
    # samsite per-type viewer pages — entity_type is pinned per route so the
    # shared viewer_panel resolves the right model from <uuid:entity_id>.
    path(
        "samsite/finding/<uuid:entity_id>",
        views.parameterized_page_view,
        {"page_slug": "samsite/finding", "entity_type": "vdr_finding"},
        name="samsite-finding",
    ),
    path(
        "samsite/indicator/<uuid:entity_id>",
        views.parameterized_page_view,
        {"page_slug": "samsite/indicator", "entity_type": "ksi_indicator"},
        name="samsite-indicator",
    ),
    path(
        "samsite/component/<uuid:entity_id>",
        views.parameterized_page_view,
        {"page_slug": "samsite/component", "entity_type": "ksi_component"},
        name="samsite-component",
    ),
    path(
        "samsite/signal/<uuid:entity_id>",
        views.parameterized_page_view,
        {"page_slug": "samsite/signal", "entity_type": "ksi_signal"},
        name="samsite-signal",
    ),
    path(
        "samsite/artifact/<uuid:entity_id>",
        views.parameterized_page_view,
        {"page_slug": "samsite/artifact", "entity_type": "compliance_artifact"},
        name="samsite-artifact",
    ),
    # Plugin mounts sit ahead of the Page catch-all so a Page slug cannot shadow a plugin route.
    *plugin_urlpatterns(),
    path("<path:page_slug>", views.page_view, name="page"),
]
