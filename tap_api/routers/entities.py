"""Entity CRUD. All mutations delegate to tap_grid.services."""

import uuid
from typing import Annotated, Any

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Query, Router

from tap_api.schemas import EntityIn, EntityOut, EntityUpdate
from tap_auth import policy
from tap_auth.capabilities import DELETE_CAPABILITY, READ_CAPABILITY, WRITE_CAPABILITY
from tap_grid.caller_context import require_caller_context
from tap_grid.models import Entity
from tap_grid.services import create_entity, delete_entity, update_entity

router = Router()


@router.get("/", response=list[EntityOut])
def list_entities(
    request: HttpRequest,
    entity_type: str | None = None,
    # Bounded (422 outside range, declared in OpenAPI): a negative slice raises in
    # the ORM (500 — found by the authenticated api-fuzz pass) and an unbounded
    # limit is a free memory-exhaustion lever on an unauthenticated-adjacent surface.
    limit: Annotated[int, Query(ge=0, le=1000)] = 100,
    # Ceiling as well as floor: SQL OFFSET is a bigint, so an unbounded offset
    # detonates as NumericValueOutOfRange (the fuzz found 1e33). Deep-offset
    # pagination past 1e6 rows is pathological on this endpoint anyway.
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> list[Entity]:
    # Direct read bypasses Search, so it carries its own grid.read gate (interim,
    # req-tap-auth-policy) until it migrates onto the Search dispatch chokepoint.
    policy.authorize(require_caller_context(), READ_CAPABILITY, operation="list_entities")
    qs = Entity.objects.all()
    if entity_type:
        qs = qs.filter(entity_type=entity_type)
    return list(qs[offset : offset + limit])


@router.get("/{entity_id}/", response=EntityOut)
def get_entity(request: HttpRequest, entity_id: uuid.UUID) -> Entity:
    policy.authorize(require_caller_context(), READ_CAPABILITY, operation="get_entity")
    return get_object_or_404(Entity, pk=entity_id)


@router.post("/", response={201: EntityOut})
def create_entity_endpoint(request: HttpRequest, payload: EntityIn) -> tuple[int, Entity]:
    # DEPRECATED: Bare Entity creation bypasses the typed write pipeline. Prefer
    # create_node(type_slug, payload) for all typed domain objects. This endpoint
    # is kept for backward compatibility and will be removed once all callers migrate.
    entity = create_entity(entity_type=payload.entity_type, name=payload.name, caller_context=require_caller_context())
    return 201, entity


@router.patch("/{entity_id}/", response=EntityOut)
def update_entity_endpoint(request: HttpRequest, entity_id: uuid.UUID, payload: EntityUpdate) -> Entity:
    # Authorize before the lookup (req-tap-auth-policy): a PATCH is a write, so the
    # write capability gates it up front. This closes (a) the empty-body read
    # bypass — an all-optional payload skips update_entity, so without this the
    # endpoint returned EntityOut with no gate (Entity is not covered by the ORM
    # read backstop) — and (b) the 404-before-403 existence oracle.
    policy.authorize(require_caller_context(), WRITE_CAPABILITY, operation="update_entity")
    entity = get_object_or_404(Entity, pk=entity_id)
    updates: dict[str, Any] = payload.dict(exclude_unset=True)
    if updates:
        entity = update_entity(entity, caller_context=require_caller_context(), **updates)
    return entity


@router.delete("/{entity_id}/", response={204: None})
def delete_entity_endpoint(request: HttpRequest, entity_id: uuid.UUID) -> tuple[int, None]:
    # Authorize before the lookup (req-tap-auth-policy): grid.delete gates the
    # endpoint up front, closing the 404-before-403 existence oracle.
    policy.authorize(require_caller_context(), DELETE_CAPABILITY, operation="delete_entity")
    entity = get_object_or_404(Entity, pk=entity_id)
    delete_entity(entity, caller_context=require_caller_context())
    return 204, None
