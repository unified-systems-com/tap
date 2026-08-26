"""Search execution endpoint. Delegates to tap_grid.search.execute_search."""

from __future__ import annotations

import uuid
from typing import Any

from django.core.exceptions import ValidationError
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from pydantic import Field

from tap_auth import policy
from tap_auth.capabilities import READ_CAPABILITY
from tap_grid.caller_context import get_caller_context
from tap_grid.exceptions import SearchExecutionError
from tap_grid.grift.subgraph import SubgraphLayer
from tap_grid.models import Search
from tap_grid.search import execute_search

router = Router()


class ExecuteSearchIn(Schema):
    inputs: dict[str, Any] | None = None
    # Bounded both ways (422 otherwise): the same 500 classes the authenticated
    # api-fuzz pass found on the list endpoints — negative values crash the ORM
    # slice, and values past bigint crash SQL OFFSET/LIMIT — closed here before
    # they ride into execute_search.
    limit: int | None = Field(default=None, ge=0, le=1000)
    offset: int | None = Field(default=None, ge=0, le=1_000_000)
    layer: SubgraphLayer | None = None


@router.post("/{search_id}/execute", response={200: dict, 422: dict, 500: dict})
def execute_search_endpoint(
    request: HttpRequest,
    search_id: uuid.UUID,
    payload: ExecuteSearchIn,
) -> tuple[int, dict[str, Any]]:
    """Execute a stored Search and return the canonical graph envelope.

    Body is POST-shaped because `inputs` is a nested JSON object that would be
    awkward and URL-length-limited as query params. Read enforcement: the request
    must hold `grid.read`, authorized BEFORE the Search is loaded so a denied
    caller cannot distinguish a missing search (404) from an existing one
    (existence leak); both return the same 403 (req-tap-auth-service-boundary).
    """
    policy.authorize(get_caller_context(), READ_CAPABILITY, operation="execute_search_endpoint")
    search = get_object_or_404(Search, entity_id=search_id)
    try:
        result = execute_search(
            search,
            inputs=payload.inputs or {},
            limit=payload.limit,
            offset=payload.offset,
            layer=payload.layer or "full",
        )
    except ValidationError as exc:
        return 422, {
            "error": "input_validation_failed",
            "detail": exc.message_dict if hasattr(exc, "message_dict") else exc.messages,
        }
    except SearchExecutionError as exc:
        return 500, {"error": "search_execution_failed", "detail": str(exc)}
    return 200, result
