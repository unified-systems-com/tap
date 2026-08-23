"""EntityType endpoint — read-only. Types are managed by plugins, not the API."""

from django.http import HttpRequest
from ninja import Router

from tap_api.schemas import EntityTypeOut
from tap_auth import policy
from tap_auth.capabilities import READ_CAPABILITY
from tap_grid.caller_context import require_caller_context
from tap_grid.models import EntityType

router = Router()


@router.get("/", response=list[EntityTypeOut])
def list_entity_types(request: HttpRequest, kind: str | None = None) -> list[EntityType]:
    """List catalogued types — node types and edge types.

    Both kinds belong here: edges ARE entities (req-grid-entity-spine). The `kind`
    field discriminates them, and `?kind=node` / `?kind=edge` narrows the list — a
    caller asking "what node types exist?" gets an answer instead of having to
    know which slugs happen to be edges (req-grid-entity-type-kind).
    """
    # Grid.read gate (finding cs-tap-api-typecat-003): the type catalog is graph
    # metadata, and every graph read requires grid.read (req-tap-auth-policy). This
    # mirrors the entities router. EntityType is not a BaseModel, so this explicit
    # gate — plus the Layer-2 SQL read backstop — is what covers it.
    policy.authorize(require_caller_context(), READ_CAPABILITY, operation="list_entity_types")
    queryset = EntityType.objects.all()
    if kind is not None:
        # Unknown value ⇒ empty list, not a 500 and not the unfiltered catalog:
        # over-returning is the dangerous direction for a typo'd filter.
        queryset = queryset.filter(kind=kind)
    return list(queryset)
