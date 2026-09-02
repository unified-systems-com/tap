"""tap_auth HTTP views.

Auth-owned routes mounted under ``/auth/`` (req-tap-auth-app-3). allauth provides
the login/logout/social-login machinery; this module adds TAP-specific auth
surfaces that sit alongside it — currently the generic no-access landing.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET


@require_GET
def no_access(request: HttpRequest) -> HttpResponse:
    """Generic no-access landing for an authenticated actor holding no TAP
    capabilities.

    Per req-tap-auth-google-oidc, authentication is not permission: an
    auto-provisioned (or deactivated-group) user may log in successfully yet
    hold no capabilities. Rather than a bare 403, they land here with a clear
    explanation and a logout affordance. Rendered under ``/auth/`` (wall-exempt)
    and from a self-contained template (owned by tap_web — tap_auth renders no
    HTML of its own) that depends on no grid-readable context, so it always
    renders even when every capability check would deny.
    """
    return render(request, "tap_web/auth/no_access.html")
