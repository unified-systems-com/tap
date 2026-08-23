"""
TAP Core Services — canonical mutation API for entities and edges.

Public write API:
  write_batch()        — atomic multi-op batch with dry-run support
  create_node()        — create a typed domain object by slug
  patch_node()         — partial update (PATCH semantics)
  replace_node()       — full replacement (PUT semantics)
  delete_node()        — delete a node and its Entity spine
  create_edge()        — create an Edge between two entities (also the compat wrapper)
  patch_edge()         — partial update of edge properties
  replace_edge()       — full replacement of edge properties
  delete_edge()        — delete an edge (also the compat wrapper)

Backward-compatible low-level helpers (kept for existing callers):
  create_entity(), update_entity(), delete_entity(),
  update_edge_properties()
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from django.db import transaction

from tap_auth.capabilities import (
    DELETE_CAPABILITY,
    DISCOVER_CAPABILITY,
    PURGE_CAPABILITY,
    READ_CAPABILITY,
    WRITE_CAPABILITY,
)
from tap_auth.enforcement import (
    assert_program_actor,
    assert_write_authorized,
    gates_per_operation,
    requires_capability,
)
from tap_grid.caller_context import (
    CallerContext,
    get_caller_context,
    reset_deferred_hotlink_checks,
    set_caller_context,
    start_deferred_hotlink_checks,
)
from tap_grid.constraints import validate_edge as _validate_edge_constraint
from tap_grid.exceptions import (
    EdgePropertyValidationError,
    InvalidEdgeError,
    ServiceConflictError,
    ServiceConstraintError,
    ServiceNotFoundError,
    ServiceValidationError,
    ServiceVersionConflictError,
)
from tap_grid.models import Edge, Entity
from tap_grid.service_types import (
    BatchWriteResult,
    EdgeTypeDescription,
    NodeTypeDescription,
    ServiceCapabilities,
    ServiceError,
    WriteOperation,
    WriteResult,
)
from tap_grid.services._impl import (
    _assert_debug_for_purge,
    _assert_test_or_debug,
    _coerce_uuid,
    _drain_hotlink_checks_into_results,
    _ensure_batch,
    _execute_write_pipeline,
    _load_entity_or_raise,
)
from tap_grid.write_guard import service_write_scope

logger = logging.getLogger(__name__)

# The gateway's public export manifest: the reviewable list of gated operations, and
# nothing else (spec-service-layer-boundary.md req-service-boundary-contract-surface).
# Every name here is a `def` carrying @requires_capability(...) / @gates_per_operation —
# the service-boundary guard fails the build on any entry that is not gated, and on any
# ungated public function defined in this module whether or not it is listed (the union
# invariant: __all__ advertises the surface, it can never shrink what is enforced).
# Non-operation exports (WriteOperation, BatchWriteResult, the Service* types, the
# exception taxonomy) are NOT listed here — callers import those from tap_grid.service_types.
__all__ = [
    # Write API (grid.write / grid.delete / grid.purge)
    "write_batch",
    "create_node",
    "patch_node",
    "replace_node",
    "delete_node",
    "patch_edge",
    "replace_edge",
    "delete_edge_by_entity",
    "purge_node",
    "purge_edge",
    # Read API (grid.read)
    "resolve_entity",
    "get_node",
    "get_edge",
    "get_object",
    # Discovery API (grid.discover)
    "list_node_types",
    "describe_node_type",
    "list_edge_types",
    "describe_edge_type",
    "describe_service_capabilities",
    # Backward-compatible low-level helpers (grid.write / grid.delete)
    "create_entity",
    "update_entity",
    "delete_entity",
    "create_edge",
    "update_edge_properties",
    "delete_edge",
]

# ---------------------------------------------------------------------------
# Internal sentinel for dry-run rollback
# ---------------------------------------------------------------------------


class _DryRunRollback(Exception):
    """Raised inside an atomic() block to force a rollback for dry-run mode."""


class _BailOut(Exception):
    """Raised when a pipeline operation fails, rolling back the entire batch."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Public write API
# ---------------------------------------------------------------------------


@gates_per_operation
@service_write_scope()
def write_batch(
    operations: list[WriteOperation],
    *,
    caller_context: CallerContext | None = None,
    dry_run: bool = False,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
    _internal_only_bypass: bool = False,
) -> BatchWriteResult:
    """Execute multiple write operations atomically.

    All operations share one batch_id. If any operation fails, all are rolled
    back. Dry-run mode runs the full pipeline (including DB writes) then rolls
    back, returning validation results without persisting.

    Args:
        operations: Ordered list of WriteOperation instances.
        caller_context: Optional actor identity and existing batch scope.
        dry_run: If True, validate everything but roll back all writes.
        result_mode: Controls how much detail is included in each WriteResult.
        _internal_only_bypass: Trusted-internal callers only. When True, the
            pipeline does not reject INTERNAL_ONLY model types. Not part of the
            public API; the leading underscore signals the boundary. See
            `_create_node_internal` / `_patch_node_internal`.

    Returns:
        BatchWriteResult with per-operation results and overall success flag.

    Raises:
        ValueError: if `operations` is empty — see below.
    """
    # An empty batch is a caller bug, never a legitimate operation: the single-op
    # verbs pass [op] and the GRIFT importer guards `if ops:`, so nothing in TAP
    # produces write_batch([]). Reject it loudly rather than minting an Entity+Batch
    # row for zero work (doc-auth-per-app-standards "seal empty-batch"). This is a
    # usage error orthogonal to authorization, so it precedes actor resolution and
    # the write backstop.
    if not operations:
        raise ValueError("write_batch requires at least one operation; received an empty batch")

    # Resolve the acting context: inherit the ambient request/task/test actor
    # when the caller passed no context, or passed a batch scope without an actor,
    # so the batch is always attributed to a named actor (no User=None). Mirrors
    # the decorator's _resolve_caller_context.
    if caller_context is None:
        caller_context = get_caller_context()
    elif caller_context.user is None:
        _ambient = get_caller_context()
        if _ambient is not None and _ambient.user is not None:
            caller_context = CallerContext(user=_ambient.user, batch_id=caller_context.batch_id)
    user = caller_context.user if caller_context else None

    # On-by-default write backstop (req-tap-auth-policy, stateless re-check): a
    # mutation must not reach commit with an actor lacking the capability its ops
    # require. Checked per op-class — a delete op requires grid.delete specifically,
    # not merely grid.write. The decorated verbs / grift authorized() scope are the
    # primary gate (typed AuthzError on denial); this is independent defense-in-depth
    # and an unauthorized or actorless path fails closed here (UnguardedOperation).
    _delete_verbs = {"delete_node", "delete_edge"}
    _batch_verbs = {op.verb for op in operations}
    assert_write_authorized(
        caller_context,
        needs_write=bool(_batch_verbs - _delete_verbs),
        needs_delete=bool(_batch_verbs & _delete_verbs),
    )

    # The INTERNAL_ONLY write bypass is a program-actor-only door: the public path
    # rejects INTERNAL_ONLY node types, and the trusted-internal bypass that writes
    # them is bound to program identity by construction (a human reaching it means a
    # forgotten upstream swap). Belt-and-suspenders to the type-level gate; a future
    # refinement narrows it to which entity types each actor may create.
    if _internal_only_bypass:
        assert_program_actor(caller_context, operation="INTERNAL_ONLY write bypass")

    # Resolve or create a batch_id.
    if caller_context and caller_context.batch_id:
        effective_batch_id = caller_context.batch_id
    else:
        effective_batch_id = str(uuid.uuid7())

    # Thread CallerContext so BaseModel.save() stamps batch_id on all writes.
    prior_ctx = get_caller_context()
    set_caller_context(CallerContext(user=user, batch_id=effective_batch_id))

    # Activate deferred-hotlink mode for this batch scope (req-grid-hotlink-
    # deferred). Per-op pipelines that call full_validate() → validate_hotlinks()
    # will enqueue the instance instead of validating inline; the pre-commit
    # consistency phase below drains the queue once every node and edge in the
    # batch has been saved.
    defer_token = start_deferred_hotlink_checks()

    results: list[WriteResult] = []
    batch_errors: list[ServiceError] = []

    try:
        with transaction.atomic():
            # Ensure the Batch entity exists inside the transaction so it
            # participates in rollback (e.g. dry_run, validation savepoints).
            try:
                _ensure_batch(effective_batch_id, user)
            except Exception:
                logger.exception("[fc60] Failed to ensure Batch entity for batch_id=%s", effective_batch_id)

            for op in operations:
                result = _execute_write_pipeline(
                    op,
                    batch_id=effective_batch_id,
                    user=user,
                    result_mode=result_mode,
                    internal_only_bypass=_internal_only_bypass,
                )
                results.append(result)
                if not result.success:
                    raise _BailOut()

            # Pre-commit consistency phase (req-grid-service-batch-precommit-
            # consistency). Drain the deferred hotlink queue; any failure flips
            # the matching per-op result and short-circuits via _BailOut so the
            # surrounding transaction.atomic() rolls back.
            if _drain_hotlink_checks_into_results(results):
                raise _BailOut()

            if dry_run:
                raise _DryRunRollback()

    except _DryRunRollback:
        pass  # Expected; DB changes rolled back; results already collected.
    except _BailOut:
        pass  # First failure captured in results; atomic() rolled back.
    except Exception as exc:
        logger.exception("[0b64] Unexpected error in write_batch")
        batch_errors.append(ServiceError(code="internal_error", message=str(exc)))
    finally:
        reset_deferred_hotlink_checks(defer_token)
        set_caller_context(prior_ctx)

    overall_success = not batch_errors and all(r.success for r in results)
    return BatchWriteResult(
        success=overall_success,
        batch_id=effective_batch_id,
        dry_run=dry_run,
        results=results,
        errors=batch_errors,
    )


@requires_capability(WRITE_CAPABILITY, operation="create_node")
def create_node(
    type_slug: str,
    payload: dict[str, Any],
    *,
    caller_context: CallerContext | None = None,
    dry_run: bool = False,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
) -> WriteResult:
    """Create a new domain object of the given type.

    Args:
        type_slug: Registered entity type slug (e.g. "character").
        payload: Field values validated against SERVICE_CRUD_SCHEMA["create"].
        caller_context: Optional actor identity and batch scope.
        dry_run: If True, validate but do not persist.
        result_mode: Controls WriteResult detail level.

    Returns:
        WriteResult with entity_id populated on success.
    """
    op = WriteOperation(verb="create_node", type_slug=type_slug, payload=payload)
    batch_result = write_batch([op], caller_context=caller_context, dry_run=dry_run, result_mode=result_mode)
    return (
        batch_result.results[0]
        if batch_result.results
        else WriteResult(success=False, batch_id=batch_result.batch_id, errors=batch_result.errors)
    )


@requires_capability(WRITE_CAPABILITY, operation="patch_node")
def patch_node(
    target: str | uuid.UUID,
    payload: dict[str, Any],
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,
    dry_run: bool = False,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
) -> WriteResult:
    """Partially update a domain object (PATCH semantics).

    Omitted fields are unchanged. JSONField values are deep-merged.

    Args:
        target: Entity UUID of the object to patch.
        payload: Field values validated against SERVICE_CRUD_SCHEMA["patch"].
        caller_context: Optional actor identity and batch scope.
        entity_expected_version: Optional OCC declaration (req-grid-service-batch-occ).
            When set, the pipeline takes a SELECT FOR UPDATE on the target
            Entity row and verifies its `version` matches before mutation.
            Mismatch → `entity_version_conflict` with detail payload.
        dry_run: If True, validate but do not persist.
        result_mode: Controls WriteResult detail level.

    Returns:
        WriteResult with entity_id populated on success.
    """
    op = WriteOperation(
        verb="patch_node",
        target=target,
        payload=payload,
        entity_expected_version=entity_expected_version,
    )
    batch_result = write_batch([op], caller_context=caller_context, dry_run=dry_run, result_mode=result_mode)
    return (
        batch_result.results[0]
        if batch_result.results
        else WriteResult(success=False, batch_id=batch_result.batch_id, errors=batch_result.errors)
    )


@requires_capability(WRITE_CAPABILITY, operation="replace_node")
def replace_node(
    target: str | uuid.UUID,
    payload: dict[str, Any],
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,
    dry_run: bool = False,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
) -> WriteResult:
    """Fully replace the user-writable fields of a domain object (PUT semantics).

    All fields declared in SERVICE_CRUD_SCHEMA["replace"]["properties"] are
    replaced. Fields on the Entity spine are not affected.

    Args:
        target: Entity UUID of the object to replace.
        payload: Field values validated against SERVICE_CRUD_SCHEMA["replace"].
        caller_context: Optional actor identity and batch scope.
        entity_expected_version: Optional OCC declaration (req-grid-service-batch-occ).
            When set, the pipeline verifies `Entity.version` before mutation;
            mismatch → `entity_version_conflict`.
        dry_run: If True, validate but do not persist.
        result_mode: Controls WriteResult detail level.

    Returns:
        WriteResult with entity_id populated on success.
    """
    op = WriteOperation(
        verb="replace_node",
        target=target,
        payload=payload,
        entity_expected_version=entity_expected_version,
    )
    batch_result = write_batch([op], caller_context=caller_context, dry_run=dry_run, result_mode=result_mode)
    return (
        batch_result.results[0]
        if batch_result.results
        else WriteResult(success=False, batch_id=batch_result.batch_id, errors=batch_result.errors)
    )


@requires_capability(DELETE_CAPABILITY, operation="delete_node")
def delete_node(
    target: str | uuid.UUID,
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,
    dry_run: bool = False,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
) -> WriteResult:
    """Delete a domain object and its Entity spine.

    Cascades to edges per Django's cascade rules.

    Args:
        target: Entity UUID of the object to delete.
        caller_context: Optional actor identity and batch scope.
        entity_expected_version: Optional OCC declaration (req-grid-service-delete-occ).
            When set, the pipeline verifies `Entity.version` before tombstoning;
            mismatch → `entity_version_conflict`.
        dry_run: If True, validate but do not persist.
        result_mode: Controls WriteResult detail level.

    Returns:
        WriteResult with entity_id=None on success.
    """
    op = WriteOperation(
        verb="delete_node",
        target=target,
        entity_expected_version=entity_expected_version,
    )
    batch_result = write_batch([op], caller_context=caller_context, dry_run=dry_run, result_mode=result_mode)
    return (
        batch_result.results[0]
        if batch_result.results
        else WriteResult(success=False, batch_id=batch_result.batch_id, errors=batch_result.errors)
    )


@requires_capability(WRITE_CAPABILITY, operation="patch_edge")
def patch_edge(
    target: str | uuid.UUID,
    payload: dict[str, Any],
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,
    dry_run: bool = False,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
) -> WriteResult:
    """Partially update an Edge's properties (PATCH semantics).

    edge_type is immutable and cannot be included in the payload.

    Args:
        target: Entity UUID of the Edge to patch.
        payload: Field values validated against Edge.SERVICE_CRUD_SCHEMA["patch"].
        caller_context: Optional actor identity and batch scope.
        entity_expected_version: Optional OCC declaration (req-grid-service-write-occ).
            When set, the pipeline verifies `Entity.version` before mutation;
            mismatch → `entity_version_conflict`.
        dry_run: If True, validate but do not persist.
        result_mode: Controls WriteResult detail level.

    Returns:
        WriteResult with entity_id populated on success.
    """
    op = WriteOperation(
        verb="patch_edge",
        target=target,
        payload=payload,
        entity_expected_version=entity_expected_version,
    )
    batch_result = write_batch([op], caller_context=caller_context, dry_run=dry_run, result_mode=result_mode)
    return (
        batch_result.results[0]
        if batch_result.results
        else WriteResult(success=False, batch_id=batch_result.batch_id, errors=batch_result.errors)
    )


@requires_capability(WRITE_CAPABILITY, operation="replace_edge")
def replace_edge(
    target: str | uuid.UUID,
    payload: dict[str, Any],
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,
    dry_run: bool = False,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
) -> WriteResult:
    """Fully replace an Edge's properties (PUT semantics).

    edge_type is immutable and cannot be included in the payload.

    Args:
        target: Entity UUID of the Edge to replace.
        payload: Field values validated against Edge.SERVICE_CRUD_SCHEMA["replace"].
        caller_context: Optional actor identity and batch scope.
        entity_expected_version: Optional OCC declaration (req-grid-service-write-occ).
            When set, the pipeline verifies `Entity.version` before mutation;
            mismatch → `entity_version_conflict`.
        dry_run: If True, validate but do not persist.
        result_mode: Controls WriteResult detail level.

    Returns:
        WriteResult with entity_id populated on success.
    """
    op = WriteOperation(
        verb="replace_edge",
        target=target,
        payload=payload,
        entity_expected_version=entity_expected_version,
    )
    batch_result = write_batch([op], caller_context=caller_context, dry_run=dry_run, result_mode=result_mode)
    return (
        batch_result.results[0]
        if batch_result.results
        else WriteResult(success=False, batch_id=batch_result.batch_id, errors=batch_result.errors)
    )


@requires_capability(DELETE_CAPABILITY, operation="delete_edge_by_entity")
def delete_edge_by_entity(
    target: str | uuid.UUID,
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,
    dry_run: bool = False,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
) -> WriteResult:
    """Delete an Edge identified by its Entity UUID.

    Args:
        target: Entity UUID of the Edge to delete.
        caller_context: Optional actor identity and batch scope.
        entity_expected_version: Optional OCC declaration (req-grid-service-delete-occ).
            When set, the pipeline verifies `Entity.version` before tombstoning;
            mismatch → `entity_version_conflict`.
        dry_run: If True, validate but do not persist.
        result_mode: Controls WriteResult detail level.

    Returns:
        WriteResult with entity_id=None on success.
    """
    op = WriteOperation(
        verb="delete_edge",
        target=target,
        entity_expected_version=entity_expected_version,
    )
    batch_result = write_batch([op], caller_context=caller_context, dry_run=dry_run, result_mode=result_mode)
    return (
        batch_result.results[0]
        if batch_result.results
        else WriteResult(success=False, batch_id=batch_result.batch_id, errors=batch_result.errors)
    )


# ---------------------------------------------------------------------------
# Service-layer purge — DEBUG-only hard-delete
#
# req-grid-service-purge in spec-grid-service-delete.md. Narrow escape hatch
# for hard-deleting a single entity along with its touching edges and history
# rows. Default delete semantics remain tombstone; this is the explicit
# exception when an operator needs the entity gone rather than hidden.
# ---------------------------------------------------------------------------


@dataclass
class PurgeResult:
    """Outcome of a single purge_node call.

    `purged_edges` lists Entity UUIDs of Edge rows hard-deleted as part of the
    cascade. `purged_entity_id` is the Entity UUID that was the purge target.
    """

    success: bool
    purged_entity_id: str | None
    purged_entity_type: str | None
    purged_edges: list[str] = field(default_factory=list)
    error: str | None = None


@requires_capability(PURGE_CAPABILITY, operation="purge_node")
def purge_node(
    entity_id: str | uuid.UUID,
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,
    reason: str,
) -> PurgeResult:
    """Hard-delete an entity, its touching edges, and history rows.

    DEBUG-only. Removes the typed BaseModel row + Entity-spine row + every
    Edge row touching the entity at either end + the history rows for both
    the typed model and the edges + the BatchEvent rows referencing any of
    them. Neighbor entities at the far end of touching edges are NOT purged
    — cascade is edges-only.

    See req-grid-service-purge for the full contract. This function and
    `_apply_sweep_purge` in the GRIFT importer share the same DEBUG gate and
    the same hard-delete semantics; a future refactor will route the GRIFT
    sweep through this primitive.

    Args:
        entity_id: Entity UUID of the node to purge.
        caller_context: Optional actor identity, captured in the log line.
        entity_expected_version: Optional OCC declaration (req-grid-service-delete-occ).
            When set, the purge takes a SELECT FOR UPDATE on the Entity row
            and verifies `Entity.version` matches before the hard delete.
            Mismatch (or missing entity with OCC engaged) → ServiceVersionConflictError.
            The DEBUG gate still applies independently.
        reason: Required free-form description of why the purge is happening.
            Captured in the application log alongside the entity_id and actor.

    Returns:
        PurgeResult describing what was removed.

    Raises:
        ServiceConflictError: If `settings.DEBUG` is False.
        ServiceValidationError: If entity_id cannot be coerced, or `reason` is empty.
        ServiceNotFoundError: If no Entity with that UUID exists (only when
            entity_expected_version is None; with OCC engaged, missing-entity
            surfaces as ServiceVersionConflictError instead).
        ServiceVersionConflictError: When entity_expected_version is set and
            does not match the local `Entity.version` (or the entity is
            missing).
    """
    _assert_debug_for_purge()

    if not reason or not reason.strip():
        raise ServiceValidationError("purge_node requires a non-empty `reason`.")

    try:
        target_uuid = _coerce_uuid(entity_id)
    except (ValueError, TypeError) as exc:
        raise ServiceValidationError(f"entity_id is not a valid UUID: {entity_id!r}") from exc
    if target_uuid is None:
        raise ServiceValidationError("entity_id must be provided.")

    actor = caller_context.user if caller_context is not None else None

    from django.db.models import Q

    from tap_grid.models import BatchEvent
    from tap_grid.registry import get_model_class

    with transaction.atomic():
        # OCC guard (req-grid-service-delete-occ). When entity_expected_version
        # is declared, take SELECT FOR UPDATE on the Entity row up front and
        # verify the version; this is the only entity-row read for the
        # function and the lock holds for the rest of the transaction so the
        # subsequent cascade reads + hard deletes run on a stable view.
        if entity_expected_version is not None:
            entity = Entity.objects.select_for_update().filter(pk=target_uuid).first()
            if entity is None:
                raise ServiceVersionConflictError(
                    entity_expected_version=entity_expected_version,
                    actual_entity_version=None,
                    entity_id=str(target_uuid),
                )
            if entity.version != entity_expected_version:
                raise ServiceVersionConflictError(
                    entity_expected_version=entity_expected_version,
                    actual_entity_version=entity.version,
                    entity_id=str(target_uuid),
                )
        else:
            entity = Entity.objects.filter(pk=target_uuid).first()
            if entity is None:
                raise ServiceNotFoundError(f"No Entity with entity_id={target_uuid}.")
        entity_type = entity.entity_type

        if entity_type == "edge":
            # Edges have their own delete path (delete_edge_by_entity); purge is
            # scoped to node-style entities so we don't conflate purging a node
            # (which cascades to its edges) with purging an edge directly.
            raise ServiceConflictError(
                f"purge_node targets node entities; entity {target_uuid} is an edge. "
                "Purging an edge directly is not supported in v0."
            )

        # Find touching edges before we delete the spine. Both directions, including
        # tombstoned edges (Edge.all_objects), so the purge actually clears them.
        touching_edge_ids = list(
            Edge.all_objects.filter(Q(from_entity_id=target_uuid) | Q(to_entity_id=target_uuid)).values_list(
                "entity_id", flat=True
            )
        )

        try:
            model_cls = get_model_class(entity_type)
        except KeyError:
            model_cls = None

        # Order matters here: we MUST delete the Entity rows (which cascade to
        # the typed BaseModel rows via OneToOneField(on_delete=CASCADE)) BEFORE
        # sweeping history. django-simple-history's post_delete signal fires on
        # the cascade and would create a fresh "delete" history row that would
        # then survive a pre-cascade history sweep. Deleting history after the
        # cascade catches every row, including the signal-generated ones.

        # 1) Touching edges: delete Entity rows first (cascades the typed Edge).
        if touching_edge_ids:
            Entity.objects.filter(pk__in=touching_edge_ids).delete()

        # 2) The target Entity itself. Cascades the typed BaseModel row.
        Entity.objects.filter(pk=target_uuid).delete()

        # 3) Now sweep history rows for the typed model and the touching edges.
        #    django-simple-history doesn't cascade-delete history with the live
        #    row; explicit deletion is required.
        if model_cls is not None and hasattr(model_cls, "history"):
            model_cls.history.filter(entity_id=target_uuid).delete()
        if touching_edge_ids:
            Edge.history.filter(entity_id__in=touching_edge_ids).delete()

        # 4) BatchEvent rows referencing the purged entity or edges so no
        #    orphan event rows survive.
        BatchEvent.objects.filter(entity_id=target_uuid).delete()
        if touching_edge_ids:
            BatchEvent.objects.filter(entity_id__in=touching_edge_ids).delete()

    logger.info(
        "[3240] purge_node: entity_id=%s entity_type=%s touching_edges=%d actor=%s reason=%r",
        target_uuid,
        entity_type,
        len(touching_edge_ids),
        actor,
        reason,
    )

    return PurgeResult(
        success=True,
        purged_entity_id=str(target_uuid),
        purged_entity_type=entity_type,
        purged_edges=[str(eid) for eid in touching_edge_ids],
    )


@requires_capability(PURGE_CAPABILITY, operation="purge_edge")
def purge_edge(
    entity_id: str | uuid.UUID,
    *,
    caller_context: CallerContext | None = None,
    entity_expected_version: int | None = None,
    reason: str,
) -> PurgeResult:
    """Hard-delete one Edge entity and its history/event rows.

    DEBUG-only. Removes the typed Edge row, its Entity-spine row, its
    HistoricalEdge rows, and BatchEvent rows referencing the edge. Endpoint
    nodes survive; this is the edge sibling of purge_node and does NOT
    cascade to either endpoint.

    See req-grid-service-purge-edge for the full contract.

    Args:
        entity_id: Entity UUID of the Edge to purge.
        caller_context: Optional actor identity, captured in the log line.
        entity_expected_version: Optional OCC declaration (req-grid-service-delete-occ).
            When set, the purge takes a SELECT FOR UPDATE on the Entity row
            and verifies `Entity.version` matches before the hard delete.
            Mismatch (or missing entity with OCC engaged) → ServiceVersionConflictError.
            The DEBUG gate still applies independently.
        reason: Required free-form description of why the purge is happening.
            Captured in the application log alongside the entity_id and actor.

    Returns:
        PurgeResult describing the purged edge. ``purged_edges`` is empty
        (an edge purge has no cascade — the edge itself is the target).

    Raises:
        ServiceConflictError: If ``settings.DEBUG`` is False, or if the
            target Entity is not of type "edge" (purge_edge_wrong_type).
        ServiceValidationError: If entity_id cannot be coerced, or `reason` is empty.
        ServiceNotFoundError: If no Entity with that UUID exists (only when
            entity_expected_version is None; with OCC engaged, missing-entity
            surfaces as ServiceVersionConflictError instead).
        ServiceVersionConflictError: When entity_expected_version is set and
            does not match the local `Entity.version` (or the entity is
            missing).
    """
    _assert_debug_for_purge("purge_edge")

    if not reason or not reason.strip():
        raise ServiceValidationError("purge_edge requires a non-empty `reason`.")

    try:
        target_uuid = _coerce_uuid(entity_id)
    except (ValueError, TypeError) as exc:
        raise ServiceValidationError(f"entity_id is not a valid UUID: {entity_id!r}") from exc
    if target_uuid is None:
        raise ServiceValidationError("entity_id must be provided.")

    actor = caller_context.user if caller_context is not None else None

    from tap_grid.models import BatchEvent

    with transaction.atomic():
        # OCC guard (req-grid-service-delete-occ). When declared, take
        # SELECT FOR UPDATE on the Entity row up front and verify version
        # before any reads or writes; the lock holds for the rest of the
        # transaction.
        if entity_expected_version is not None:
            entity = Entity.objects.select_for_update().filter(pk=target_uuid).first()
            if entity is None:
                raise ServiceVersionConflictError(
                    entity_expected_version=entity_expected_version,
                    actual_entity_version=None,
                    entity_id=str(target_uuid),
                )
            if entity.version != entity_expected_version:
                raise ServiceVersionConflictError(
                    entity_expected_version=entity_expected_version,
                    actual_entity_version=entity.version,
                    entity_id=str(target_uuid),
                )
        else:
            entity = Entity.objects.filter(pk=target_uuid).first()
            if entity is None:
                raise ServiceNotFoundError(f"No Entity with entity_id={target_uuid}.")

        if entity.entity_type != "edge":
            raise ServiceConflictError(
                f"purge_edge targets edge entities; entity {target_uuid} has "
                f"entity_type={entity.entity_type!r} (purge_edge_wrong_type). "
                "Use purge_node for node entities."
            )

        # Capture endpoints before the cascade for the log line. Use all_objects so
        # a tombstoned edge still surfaces its endpoints.
        edge_row = Edge.all_objects.filter(entity_id=target_uuid).first()
        from_id = edge_row.from_entity_id if edge_row else None
        to_id = edge_row.to_entity_id if edge_row else None

        # Delete order mirrors purge_node:
        #   1) Entity row (cascades the typed Edge row via OneToOneField CASCADE)
        #   2) Edge history rows (django-simple-history does not cascade
        #      history with the live row)
        #   3) BatchEvent rows referencing the purged edge
        Entity.objects.filter(pk=target_uuid).delete()
        Edge.history.filter(entity_id=target_uuid).delete()
        BatchEvent.objects.filter(entity_id=target_uuid).delete()

    logger.info(
        "[4a1b] purge_edge: entity_id=%s from=%s to=%s actor=%s reason=%r",
        target_uuid,
        from_id,
        to_id,
        actor,
        reason,
    )

    return PurgeResult(
        success=True,
        purged_entity_id=str(target_uuid),
        purged_entity_type="edge",
        purged_edges=[],
    )


# ---------------------------------------------------------------------------
# Trusted-internal write API
#
# These entry points run the full write pipeline (validation, name sync,
# version, history, provenance, FLIP) minus the INTERNAL_ONLY gate. They are
# the canonical path for subsystem registration helpers (e.g.
# `tap_cares.registry._ensure_collector_node`) and lifecycle managers (e.g.
# `tap_cares.services.run_collection` creating CollectionJob rows) that need
# to write INTERNAL_ONLY model types.
#
# The leading underscore signals the boundary: these functions are not part of
# the public service-layer API and must not be re-exported through
# `tap_grid.__init__`. In-process malicious code can still call them; this is a
# tripwire for accidental misuse, not a wall (see
# `tap_grid/specs/spec-grid-entity.md` `req-grid-entity-internal`).
# ---------------------------------------------------------------------------


@requires_capability(WRITE_CAPABILITY, operation="_create_node_internal")
def _create_node_internal(
    type_slug: str,
    payload: dict[str, Any],
    *,
    caller_context: CallerContext | None = None,
    entity_id: str | uuid.UUID | None = None,
    dimensions: dict[str, str] | None = None,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
) -> WriteResult:
    """Trusted-internal create for INTERNAL_ONLY (or any) node type.

    Runs the full write pipeline minus the INTERNAL_ONLY gate. Accepts an
    optional `entity_id` so callers can produce deterministic identity
    (e.g. UUIDv5 from `scope:key` in the dual-existence pattern).

    Args:
        type_slug: Registered entity type slug.
        payload: Field values validated against SERVICE_CRUD_SCHEMA["create"].
        caller_context: Optional actor identity and batch scope.
        entity_id: Optional pre-specified entity_id (UUID or str).
        dimensions: Optional caller dimensions; merged over DEFAULT_DIMENSIONS.
        result_mode: Controls WriteResult detail level.

    Returns:
        WriteResult with entity_id populated on success.
    """
    op = WriteOperation(
        verb="create_node",
        type_slug=type_slug,
        payload=payload,
        entity_id=entity_id,
        dimensions=dimensions,
    )
    batch_result = write_batch(
        [op],
        caller_context=caller_context,
        result_mode=result_mode,
        _internal_only_bypass=True,
    )
    return (
        batch_result.results[0]
        if batch_result.results
        else WriteResult(success=False, batch_id=batch_result.batch_id, errors=batch_result.errors)
    )


@requires_capability(WRITE_CAPABILITY, operation="_patch_node_internal")
def _patch_node_internal(
    target: str | uuid.UUID,
    payload: dict[str, Any],
    *,
    caller_context: CallerContext | None = None,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
) -> WriteResult:
    """Trusted-internal patch for INTERNAL_ONLY (or any) node type.

    Runs the full write pipeline minus the INTERNAL_ONLY gate. Same semantics
    as `patch_node` for non-INTERNAL_ONLY types.

    Args:
        target: Entity UUID of the object to patch.
        payload: Field values validated against SERVICE_CRUD_SCHEMA["patch"].
        caller_context: Optional actor identity and batch scope.
        result_mode: Controls WriteResult detail level.

    Returns:
        WriteResult with entity_id populated on success.
    """
    op = WriteOperation(verb="patch_node", target=target, payload=payload)
    batch_result = write_batch(
        [op],
        caller_context=caller_context,
        result_mode=result_mode,
        _internal_only_bypass=True,
    )
    return (
        batch_result.results[0]
        if batch_result.results
        else WriteResult(success=False, batch_id=batch_result.batch_id, errors=batch_result.errors)
    )


def _create_node_internal_for_test(
    type_slug: str,
    payload: dict[str, Any],
    *,
    caller_context: CallerContext | None = None,
    entity_id: str | uuid.UUID | None = None,
    dimensions: dict[str, str] | None = None,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
) -> WriteResult:
    """Test-only trusted-internal create.

    Same semantics as `_create_node_internal` but raises `RuntimeError` if not
    running under Django test/DEBUG settings. This keeps production policy
    clean while letting tests construct INTERNAL_ONLY entities directly when
    they need to exercise model-level behavior (validation, dimension defaults,
    display projection, etc.) without going through a subsystem helper.
    """
    _assert_test_or_debug("_create_node_internal_for_test")
    return (
        _create_node_internal(  # TAP-AUTHZ-COV: test-only helper; _assert_test_or_debug makes it production-unreachable
            type_slug,
            payload,
            caller_context=caller_context,
            entity_id=entity_id,
            dimensions=dimensions,
            result_mode=result_mode,
        )
    )


def _patch_node_internal_for_test(
    target: str | uuid.UUID,
    payload: dict[str, Any],
    *,
    caller_context: CallerContext | None = None,
    result_mode: Literal["minimal", "standard", "verbose"] = "standard",
) -> WriteResult:
    """Test-only trusted-internal patch. See `_create_node_internal_for_test`."""
    _assert_test_or_debug("_patch_node_internal_for_test")
    return (
        _patch_node_internal(  # TAP-AUTHZ-COV: test-only helper; _assert_test_or_debug makes it production-unreachable
            target,
            payload,
            caller_context=caller_context,
            result_mode=result_mode,
        )
    )


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------


@requires_capability(READ_CAPABILITY, operation="resolve_entity")
def resolve_entity(target: str | uuid.UUID, *, caller_context: CallerContext | None = None) -> Entity:
    """Return the Entity row for the given entity UUID.

    Args:
        target: Entity UUID (str or uuid.UUID).

    Returns:
        The Entity instance.

    Raises:
        ServiceNotFoundError: If no entity with that UUID exists.
        ServiceValidationError: If target cannot be coerced to a UUID.
    """
    entity_id = _coerce_uuid(target)
    if entity_id is None:
        raise ServiceValidationError("target must be a valid UUID.")
    return _load_entity_or_raise(entity_id)


@requires_capability(READ_CAPABILITY, operation="get_node")
def get_node(target: str | uuid.UUID, *, caller_context: CallerContext | None = None) -> Any:
    """Return the typed domain node instance for the given entity UUID.

    Args:
        target: Entity UUID (str or uuid.UUID).

    Returns:
        The concrete typed model instance (e.g. Character, Location).

    Raises:
        ServiceNotFoundError: If no entity with that UUID exists, or the type is unknown.
        ServiceConstraintError: If the entity is an edge, not a node.
        ServiceValidationError: If target cannot be coerced to a UUID.
    """
    from tap_grid.registry import get_model_class

    entity_id = _coerce_uuid(target)
    if entity_id is None:
        raise ServiceValidationError("target must be a valid UUID.")
    entity = _load_entity_or_raise(entity_id)
    if entity.entity_type == "edge":
        raise ServiceConstraintError(f"Entity {entity_id} is an edge, not a node.")
    try:
        model_cls = get_model_class(entity.entity_type)
    except KeyError as exc:
        raise ServiceNotFoundError(f"Unknown entity type: '{entity.entity_type}'.") from exc
    try:
        return model_cls.objects.select_related("entity").get(entity_id=entity_id)
    except model_cls.DoesNotExist as exc:
        raise ServiceNotFoundError(f"Node {entity_id} not found.") from exc


@requires_capability(READ_CAPABILITY, operation="get_edge")
def get_edge(target: str | uuid.UUID, *, caller_context: CallerContext | None = None) -> Edge:
    """Return the Edge instance for the given entity UUID.

    Args:
        target: Entity UUID (str or uuid.UUID).

    Returns:
        The Edge instance.

    Raises:
        ServiceNotFoundError: If no edge with that UUID exists.
        ServiceValidationError: If target cannot be coerced to a UUID.
    """
    entity_id = _coerce_uuid(target)
    if entity_id is None:
        raise ServiceValidationError("target must be a valid UUID.")
    try:
        return Edge.objects.select_related("entity").get(entity_id=entity_id)
    except Edge.DoesNotExist as exc:
        raise ServiceNotFoundError(f"Edge {entity_id} not found.") from exc


@requires_capability(READ_CAPABILITY, operation="get_object")
def get_object(target: str | uuid.UUID, *, caller_context: CallerContext | None = None) -> Any:
    """Return the typed domain instance for the given entity UUID (node or edge).

    Dispatches to get_edge() for edge entities and get_node() for all others.

    Args:
        target: Entity UUID (str or uuid.UUID).

    Returns:
        The typed model instance.

    Raises:
        ServiceNotFoundError: If no entity with that UUID exists.
        ServiceValidationError: If target cannot be coerced to a UUID.
    """
    entity_id = _coerce_uuid(target)
    if entity_id is None:
        raise ServiceValidationError("target must be a valid UUID.")
    entity = _load_entity_or_raise(entity_id)
    if entity.entity_type == "edge":
        return get_edge(entity_id)
    return get_node(entity_id)


# ---------------------------------------------------------------------------
# Public discovery API
# ---------------------------------------------------------------------------


@requires_capability(DISCOVER_CAPABILITY, operation="list_node_types")
def list_node_types(*, caller_context: CallerContext | None = None) -> list[str]:
    """Return all registered node type slugs, sorted."""
    from tap_grid.registry import list_entity_types

    return list_entity_types()


@requires_capability(DISCOVER_CAPABILITY, operation="describe_node_type")
def describe_node_type(type_slug: str, *, caller_context: CallerContext | None = None) -> NodeTypeDescription:
    """Return a discovery description for a registered node type.

    Args:
        type_slug: Entity type slug (e.g. "character").

    Returns:
        NodeTypeDescription with schemas, hotlinks, and constraint edge types.

    Raises:
        ServiceNotFoundError: If the type slug is not registered.
    """
    from tap_grid.constraints import WILDCARD, get_constraints
    from tap_grid.registry import get_model_class

    try:
        model_cls = get_model_class(type_slug)
    except KeyError as exc:
        raise ServiceNotFoundError(f"Unknown entity type: '{type_slug}'.") from exc

    schemas: dict[str, Any] = dict(getattr(model_cls, "SERVICE_CRUD_SCHEMA", {}))
    hotlinks: list[dict[str, Any]] = list(getattr(model_cls, "HOTLINKS", []))

    constraints = get_constraints(type_slug)
    outbound: list[str] = []
    inbound: list[str] = []
    if constraints:
        if constraints.outbound:
            outbound = sorted(k for k in constraints.outbound if constraints.outbound[k] is not WILDCARD or True)
        if constraints.inbound:
            inbound = sorted(k for k in constraints.inbound if constraints.inbound[k] is not WILDCARD or True)

    return NodeTypeDescription(
        type_slug=type_slug,
        schemas=schemas,
        hotlinks=hotlinks,
        outbound_edge_types=outbound,
        inbound_edge_types=inbound,
    )


@requires_capability(DISCOVER_CAPABILITY, operation="list_edge_types")
def list_edge_types(*, caller_context: CallerContext | None = None) -> list[str]:
    """Return all registered edge type slugs, sorted."""
    from tap_grid.constraints import list_registered_edge_types

    return list_registered_edge_types()


@requires_capability(DISCOVER_CAPABILITY, operation="describe_edge_type")
def describe_edge_type(edge_type: str, *, caller_context: CallerContext | None = None) -> EdgeTypeDescription:
    """Return a discovery description for a registered edge type.

    Args:
        edge_type: Edge type slug (e.g. "LOCATED_IN").

    Returns:
        EdgeTypeDescription with allowed sources/targets and optional property schema.

    Raises:
        ServiceNotFoundError: If the edge type is not registered.
    """
    from tap_grid.constraints import WILDCARD, get_edge_property_schema, get_edge_type_constraints

    constraints = get_edge_type_constraints(edge_type)
    if constraints is None:
        raise ServiceNotFoundError(f"Unknown edge type: '{edge_type}'.")

    def _format_constraint(val: Any) -> list[str] | str:
        if val is WILDCARD:
            return "wildcard"
        if val is None or not val:
            return "none"
        assert isinstance(val, set)
        return sorted(val)

    return EdgeTypeDescription(
        edge_type=edge_type,
        allowed_sources=_format_constraint(constraints.sources),
        allowed_targets=_format_constraint(constraints.targets),
        property_schema=get_edge_property_schema(edge_type),
    )


@requires_capability(DISCOVER_CAPABILITY, operation="describe_service_capabilities")
def describe_service_capabilities(*, caller_context: CallerContext | None = None) -> ServiceCapabilities:
    """Return a top-level discovery description of the TAP service layer."""
    return ServiceCapabilities(
        node_types=list_node_types(),
        edge_types=list_edge_types(),
        write_verbs=[
            "create_node",
            "patch_node",
            "replace_node",
            "delete_node",
            "create_edge",
            "patch_edge",
            "replace_edge",
            "delete_edge",
        ],
        read_functions=[
            "get_object",
            "get_node",
            "get_edge",
            "resolve_entity",
            "list_node_types",
            "describe_node_type",
            "list_edge_types",
            "describe_edge_type",
        ],
    )


# ---------------------------------------------------------------------------
# Legacy backward-compatible helpers (kept for existing callers)
# ---------------------------------------------------------------------------


@requires_capability(WRITE_CAPABILITY, operation="create_entity")
def create_entity(
    entity_type: str,
    name: str = "",
    *,
    caller_context: CallerContext | None = None,
    **kwargs: Any,
) -> Entity:
    """Create a new Entity.

    .. deprecated::
        Bare Entity creation bypasses the typed write pipeline. Prefer
        ``create_node(type_slug, payload)`` for all typed domain objects.
        This function is kept for backward compatibility and will be removed
        once all callers are migrated.
    """
    return Entity.objects.create(
        entity_type=entity_type,
        name=name,
        **kwargs,
    )


@requires_capability(WRITE_CAPABILITY, operation="update_entity")
def update_entity(entity: Entity, *, caller_context: CallerContext | None = None, **kwargs: Any) -> Entity:
    """Update an existing Entity's fields.

    .. deprecated::
        Prefer the typed write pipeline (``patch_node``) for domain objects.
    """
    for field_name, value in kwargs.items():
        setattr(entity, field_name, value)
    entity.save(update_fields=list(kwargs.keys()) + ["updated_at"])
    return entity


@requires_capability(DELETE_CAPABILITY, operation="delete_entity")
def delete_entity(entity: Entity, *, caller_context: CallerContext | None = None) -> None:
    """Delete an Entity. Cascades to edges and domain objects."""
    entity.delete()


@requires_capability(WRITE_CAPABILITY, operation="create_edge")
def create_edge(
    from_entity: Entity,
    to_entity: Entity,
    edge_type: str,
    properties: dict[str, Any] | None = None,
    name: str = "",
    *,
    caller_context: CallerContext | None = None,
) -> Edge:
    """Create an Edge between two entities.

    The backing Entity for the Edge is auto-created by Edge.save().
    An optional name overrides the auto-generated label on that Entity.

    Raises InvalidEdgeError if either endpoint is itself an edge, or if the
    edge violates topology constraints.
    Raises EdgePropertyValidationError (via Edge.save()) if properties fail
    the registered schema for this edge type.

    Routing: this compatibility wrapper routes through ``write_batch`` (the
    ``create_edge`` verb), so the edge lands through the one write chokepoint
    like every other mutation — single transaction, unified validation, FLIP
    propagation, and the ``link`` provenance recorded by the pipeline's
    ``_record_provenance`` (no separate best-effort BatchEvent). The topology and
    edge-constraint pre-checks below run first so the legacy ``InvalidEdgeError``
    contract is preserved for callers (e.g. the edges API) that catch it; the
    nono (edge-as-endpoint) check precedes constraint validation.
    """
    # Edges cannot connect to other edges (req-grid-edge-nono) — pre-checked here
    # to raise InvalidEdgeError (the pipeline would raise ServiceConstraintError).
    if from_entity.entity_type == "edge":
        raise InvalidEdgeError("Edges cannot have other edges as endpoints (from_entity is an edge).")
    if to_entity.entity_type == "edge":
        raise InvalidEdgeError("Edges cannot have other edges as endpoints (to_entity is an edge).")

    _validate_edge_constraint(from_entity.entity_type, to_entity.entity_type, edge_type)

    payload: dict[str, Any] = {}
    if properties:
        payload["properties"] = properties

    op = WriteOperation(
        verb="create_edge",
        from_target=str(from_entity.id),
        to_target=str(to_entity.id),
        edge_type=edge_type,
        payload=payload,
    )
    batch_result = write_batch([op], caller_context=caller_context)
    result = batch_result.results[0] if batch_result.results else None
    if result is None or not result.success or result.entity_id is None:
        errors = result.errors if result is not None else batch_result.errors
        detail = "; ".join(e.message for e in errors) or "edge creation failed"
        raise EdgePropertyValidationError(detail)

    edge = cast(Edge, Edge.objects.select_related("entity").get(entity_id=result.entity_id))

    if name:
        edge.entity.name = name
        edge.entity.save(update_fields=["name", "updated_at"])

    return edge


@requires_capability(WRITE_CAPABILITY, operation="update_edge_properties")
def update_edge_properties(edge: Edge, properties: dict[str, Any]) -> Edge:
    """Update an Edge's properties payload.

    Validates the new properties against the registered schema for the edge
    type (via Edge.save()) before persisting. Raises EdgePropertyValidationError
    if the payload is invalid.

    Args:
        edge: The Edge instance to update.
        properties: The new properties dict to assign.

    Returns:
        The updated Edge instance.
    """
    edge.properties = properties
    edge.save(update_fields=["properties"])
    return edge


@requires_capability(DELETE_CAPABILITY, operation="delete_edge")
def delete_edge(edge: Edge, *, caller_context: CallerContext | None = None) -> None:
    """Delete an Edge and its backing Entity."""
    # Deleting the backing Entity cascades to the Edge via OneToOne,
    # but we go through the Entity to keep the pattern consistent.
    edge.entity.delete()
