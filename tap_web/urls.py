"""TAP Web URL configuration.

URL patterns (evaluated in order):
    /panel/<slug>--<uuid>/edit/                Panel editor
    /panel/<slug>--<uuid>/                     Panel HTMX fragment endpoint
    /object/<entity-type>/<slug>--<uuid>/edit/ Generic object editor
    /object/<entity-type>/<slug>--<uuid>/drawer/ Resource drawer fragment
    /object/<entity-type>/<slug>--<uuid>/      Generic object viewer
    /                                          Landing page (or placeholder if none configured)
    /<path:page_slug>                          Catch-all dynamic page resolution

The catch-all must come last within this file.
In tap/urls.py, tap_web must be the final include (after admin, api, viz)
because path("") matches any prefix and would shadow other apps' routes.
"""

from django.urls import path

from tap_web import views

urlpatterns = [
    path("panel/<str:panel_url_id>/edit/", views.panel_edit_view, name="panel-edit"),
    path("panel/<str:panel_url_id>/", views.panel_view, name="panel"),
    path("object/<str:entity_type>/<str:object_url_id>/edit/", views.object_edit_view, name="object-edit"),
    path("object/<str:entity_type>/<str:object_url_id>/drawer/", views.object_drawer_view, name="object-drawer"),
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
    path("<path:page_slug>", views.page_view, name="page"),
]
