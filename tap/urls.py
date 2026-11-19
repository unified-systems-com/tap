"""
TAP URL Configuration

URL structure:
    /admin/         Django admin interface
    /api/...        Versioned API — see tap_api/urls.py
    /auth/...       Authentication (login/logout/OIDC) — see tap_auth/urls.py
    /files/...      Held-file downloads — see tap_files/urls.py
    /viz/...        Visualization views
    /               Web interface (catch-all — must come last)
"""

from django.contrib import admin
from django.contrib.staticfiles.storage import staticfiles_storage
from django.urls import include, path
from django.views.generic.base import RedirectView

urlpatterns = [
    path("favicon.ico", RedirectView.as_view(url=staticfiles_storage.url("tap_web/favicon.ico"), permanent=True)),
    # Health has no network surface: the unauthenticated /healthz endpoint was
    # parked (req-tap-health-exposure-4). The instance introspects itself via the
    # in-process service (`tap_health.run_health`) and `manage.py health`.
    path("admin/", admin.site.urls),
    path("api/", include("tap_api.urls")),
    # Auth routes (login/logout/OIDC) owned by tap_auth, mounted under /auth/
    # rather than allauth's default /accounts/ (req-tap-auth-app-3). Must precede
    # the tap_web catch-all (path("") matches everything).
    path("auth/", include("tap_auth.urls")),
    # File downloads owned by tap_files (req-tap-files-download), behind the login wall.
    path("files/", include("tap_files.urls")),
    # viz must come before the tap_web catch-all (path("") matches everything)
    path("viz/", include("tap_viz.urls")),
    path("", include("tap_web.urls")),
]
