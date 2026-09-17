"""Dev-only response middleware."""

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

from tap import serving

_NO_STORE = "no-store, no-cache, must-revalidate, max-age=0"


class DevNoStoreMiddleware:
    """In the development serving profile, mark page responses non-cacheable.

    So a reload always re-fetches the HTML and the JSON the panels embed or fetch,
    without hard-refreshes or cache dances. Static assets are WhiteNoise's job — it
    serves them with ``max-age=0`` in the same profile (``req-tap-serving-static-3``),
    which is what retired the ``runserver_nocache`` command this middleware used to
    complement.

    Keyed off ``TAP_SERVE_PROFILE``, not ``DEBUG``: ``DEBUG`` governs error
    presentation only (``req-tap-serving-debug-scope``). Inert in production.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        # Read per request, not cached on the instance: middleware is constructed once
        # per process, and a test that overrides the profile must still be honoured.
        if settings.TAP_SERVE_PROFILE == serving.PROFILE_DEVELOPMENT:
            response["Cache-Control"] = _NO_STORE
        return response
