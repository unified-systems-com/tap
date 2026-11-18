"""Request-scoped grid middleware."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse


class DimensionVocabularyScopeMiddleware:
    """Check the live dimension vocabulary is current once per request (req-grid-dimension-reference-9).

    A page or API response presents every row's dimensions by name; without a scope each row would
    re-check the per-process table with a query. Inside it the check runs once, on first use, and a
    Dimension node written during the request still invalidates the table at once.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        from tap_grid.live_dimensions import scope

        with scope():
            return self.get_response(request)
