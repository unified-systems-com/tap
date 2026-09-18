"""Internal helpers for the tap_grid service layer (below the capability gateway).

Pure logic and below-service-boundary machinery: UUID coercion, schema/payload
shaping, the write pipeline, provenance/batch bookkeeping, entity loading, and
the debug/test guards. NONE of these present a service surface, so none carry a
capability gate — they run *after* an exported gateway callable in
``tap_grid.services`` has already authorized the caller. This module imports
nothing from the gateway (``__init__.py``); the dependency is strictly one-way.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import deque
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import jsonschema
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models as django_models
from django.utils import timezone

from tap_grid.caller_context import (
    drain_deferred_hotlink_checks,
)
from tap_grid.constraints import validate_edge as _validate_edge_constraint
from tap_grid.exceptions import (
    InvalidEdgeError,
    ServiceAuthzError,
    ServiceCascadeTooLargeError,
    ServiceConflictError,
    ServiceConstraintError,
    ServiceInvalidReasonError,
    ServiceNotFoundError,
    ServiceUnsupportedOperationError,
    ServiceValidationError,
    ServiceVersionConflictError,
)
from tap_grid.models import Edge, Entity
from tap_grid.null_semantics import prepare_null_payload, schema_permits_null
from tap_grid.service_types import (
    ServiceError,
    WriteOperation,
    WriteResult,
)

logger = logging.getLogger(__name__)


def _coerce_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Coerce a string UUID to uuid.UUID. Returns None if value is None."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _verb_to_schema_key(verb: str) -> str:
    """Map a write verb to its SERVICE_CRUD_SCHEMA key."""
    if verb in ("create_node", "create_edge"):
        return "create"
    if verb in ("patch_node", "patch_edge"):
        return "patch"
    if verb in ("replace_node", "replace_edge"):
        return "replace"
    raise ValueError(f"No schema key for verb '{verb}'")


def _deep_merge(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge update into base. update wins on conflict for scalars."""
    result = dict(base)
    for k, v in update.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


# Null-preparation now lives in tap_grid.null_semantics — shared with the GRIFT
# importer's pre-validation, which must apply the SAME lenient rule
# (req-grid-service-write-observation-2) without importing this gated module.
# Aliased here so the write path and its tests keep their names.
_schema_permits_null = schema_permits_null
_prepare_null_payload = prepare_null_payload


def _flip_touched_for_verb(verb: str, payload: dict[str, Any]) -> list[str] | None:
    """The FLIP-touched field set for a write (req-grid-service-write-observation-5).

    create/patch stamp exactly the payload-present fields; replace asserts the
    complete object, so it stamps the full service-writeable surface (None).
    """
    if verb in ("replace_node", "replace_edge"):
        return None
    return list(payload.keys())


def _apply_patch(instance: Any, payload: dict[str, Any]) -> None:
    """Apply patch payload to an instance. JSONFields deep-merge; scalars replace."""
    for field_name, value in payload.items():
        if value is None:
            # Explicit null clears the field; never deep-merge None into a JSONField
            # (req-grid-service-write-observation-4).
            setattr(instance, field_name, None)
            continue
        try:
            model_field = instance._meta.get_field(field_name)
            is_json = isinstance(model_field, django_models.JSONField)
        except Exception:
            is_json = False

        if is_json:
            existing = getattr(instance, field_name) or {}
            setattr(instance, field_name, _deep_merge(existing, value))
        else:
            setattr(instance, field_name, value)


def _apply_replace(instance: Any, payload: dict[str, Any], model_cls: type) -> None:
    """Apply replace payload to an instance.

    Sets every field listed in SERVICE_CRUD_SCHEMA["replace"]["properties"] to
    the payload value. Missing optional fields are reset to model defaults.
    """
    schema_props = model_cls.SERVICE_CRUD_SCHEMA.get("replace", {}).get("properties", {})
    for field_name in schema_props:
        if field_name in payload:
            setattr(instance, field_name, payload[field_name])
        else:
            # Reset to model field default for optional fields absent from payload.
            try:
                model_field = instance._meta.get_field(field_name)
                default = model_field.default
                if default is not django_models.fields.NOT_PROVIDED:
                    value = default() if callable(default) else default
                else:
                    value = "" if isinstance(model_field, (django_models.CharField, django_models.TextField)) else None
                setattr(instance, field_name, value)
            except Exception:
                pass


def _django_errors_to_service_errors(exc: DjangoValidationError) -> list[ServiceError]:
    """Convert a Django ValidationError into a list of ServiceError instances."""
    errors: list[ServiceError] = []
    try:
        for field_name, messages in exc.message_dict.items():
            for msg in messages:
                errors.append(
                    ServiceError(
                        code="validation_error", message=str(msg), field=field_name if field_name != "__all__" else None
                    )
                )
    except AttributeError:
        for msg in exc.messages:
            errors.append(ServiceError(code="validation_error", message=str(msg)))
    return errors


def _load_entity_or_raise(entity_id: uuid.UUID) -> Entity:
    """Load an Entity by PK or raise ServiceNotFoundError."""
    try:
        return Entity.objects.get(pk=entity_id)
    except Entity.DoesNotExist as exc:
        raise ServiceNotFoundError(f"Entity {entity_id} not found.") from exc


def _build_object_summary(instance: Any) -> dict[str, Any]:
    """Build a minimal object summary for standard/verbose result modes."""
    entity = getattr(instance, "entity", None)
    return {
        "entity_id": str(instance.entity_id) if hasattr(instance, "entity_id") else None,
        "entity_type": entity.entity_type if entity else None,
        "name": entity.name if entity else None,
    }


_CASCADE_KEYS = frozenset({"reason", "consequence_of", "cascade_root", "root_reason"})


@dataclass
class _CascadeState:
    """Bookkeeping shared by every level of one contained cascade (one transaction).

    `discovered` is every node the walk has SEEN — root, queued or retired — and it is
    what the cap bounds: a node is counted the moment it is found, before it is queued,
    so the queue can never hold more than `cap` ids and a dense graph whose children
    share grandchildren cannot enqueue the same id once per parent (Codex on #569: the
    earlier per-fetch LIMIT bounded each query, not the sum of them). `visited` makes a
    cycle terminate and a child with two containing parents retire once; `retired` is
    counted against `cap` again BEFORE each tombstone as a second fence
    (req-grid-service-delete-cascade-11, -13).
    """

    root: uuid.UUID
    root_reason: str
    cap: int
    visited: set[uuid.UUID] = field(default_factory=set)
    discovered: set[uuid.UUID] = field(default_factory=set)
    retired: int = 0

    def headroom(self) -> int:
        """How many more nodes may be discovered before the walk is over the cap, plus one
        so the fetch that crosses the line returns the row that proves it."""
        return self.cap + 1 - len(self.discovered)

    def discover(self, candidates: list[uuid.UUID]) -> list[uuid.UUID]:
        """Admit the not-yet-seen candidates; refuse the walk the moment it exceeds the cap."""
        fresh = [c for c in candidates if c not in self.discovered]
        self.discovered.update(fresh)
        if len(self.discovered) > self.cap:
            raise ServiceCascadeTooLargeError(
                f"contained cascade from {self.root} would retire more than "
                f"TAP_CASCADE_MAX_CLOSURE={self.cap} nodes; nothing written"
            )
        return fresh


def _contained_children(
    entity_id: uuid.UUID, model_cls: type, limit: int, exclude: Collection[uuid.UUID] = ()
) -> list[uuid.UUID]:
    """Live far nodes of this node's declared containment edges not in ``exclude``, at most ``limit``.

    Read BEFORE the node's edges are ended — a tombstoned edge is invisible to the
    live manager, so gathering after the tombstone would find nothing. Undeclared
    edge types are references and are never followed (req-grid-service-delete-cascade-2).
    The fetch is bounded by the walk's discovery headroom, so one node with enormous
    fan-out cannot materialise its whole neighbourhood before the cap is noticed
    (Codex on #568). Nodes the walk has already discovered are excluded IN THE QUERY,
    before the slice: otherwise, in a convergent graph, already-seen children could fill
    the slice and hide an unseen one behind it, and the walk would end "successfully"
    with part of the declared subtree still live (Codex on #569). The exclusion list is
    bounded by the cap; the index-backed half of -15 is still Backlog.
    """
    declared = tuple(getattr(model_cls, "CONTAINMENT_EDGES", ()) or ())
    if not declared or limit <= 0:
        return []
    query = Edge.objects.filter(
        from_entity_id=entity_id,
        edge_type__in=declared,
        to_entity__deleted_at__isnull=True,
    )
    if exclude:
        query = query.exclude(to_entity_id__in=list(exclude))  # type: ignore[misc]  # same stub gap as below
    return list(
        query.values_list(
            "to_entity_id", flat=True
        ).distinct()[  # type: ignore[misc]  # django-stubs sees the BaseModel manager
            :limit
        ]
    )


def _children_of(entity_id: uuid.UUID, limit: int, exclude: Collection[uuid.UUID] = ()) -> list[uuid.UUID]:
    """Contained children of an arbitrary live node, by its spine type — the iterative walk's step."""
    from tap_grid.registry import get_model_class

    try:
        entity_type = Entity.objects.only("entity_type").get(pk=entity_id).entity_type
        model_cls = get_model_class(entity_type)
    except Entity.DoesNotExist, KeyError:
        return []
    return _contained_children(entity_id, model_cls, limit, exclude)


def _validate_retirement(op: WriteOperation) -> dict[str, Any]:
    """The reason and metadata a delete records — checked before any write.

    The vocabulary is closed (req-grid-service-delete-reason-3) and the check lives HERE,
    in the pipeline, so a raw ``write_batch([WriteOperation(...)])`` cannot bypass it
    (Codex and Grok on #568). Metadata must be JSON-serialisable: the audit record is
    written fail-closed below, and a payload that cannot be stored must be refused
    rather than silently dropped.
    """
    from tap_grid.service_types import CASCADE_MODES, DELETE_REASONS, UNSPECIFIED_REASON

    if op.cascade not in CASCADE_MODES:
        raise ServiceValidationError(f"cascade must be one of {sorted(CASCADE_MODES)}; got {op.cascade!r}")
    reason = op.reason or UNSPECIFIED_REASON
    if reason not in DELETE_REASONS:
        raise ServiceInvalidReasonError(
            f"delete reason {reason!r} is not in the closed vocabulary {sorted(DELETE_REASONS)}"
        )
    metadata = dict(op.metadata or {})
    if "reason" in metadata and metadata["reason"] != reason:
        raise ServiceInvalidReasonError("metadata may not carry a 'reason' that differs from the operation's reason")
    try:
        json.dumps(metadata)
    except (TypeError, ValueError) as exc:
        raise ServiceInvalidReasonError(f"delete metadata is not JSON-serialisable: {exc}") from exc
    metadata["reason"] = reason
    return metadata


def _record_provenance(
    verb: str,
    entity: Entity,
    batch_id: str,
    user: Any,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record a BatchEvent for the completed operation (best-effort)."""
    from tap_grid.batch import record_batch_event

    event_map = {
        "create_node": "create",
        "patch_node": "update",
        "replace_node": "update",
        "delete_node": "delete",
        "create_edge": "link",
        "patch_edge": "update",
        "replace_edge": "update",
        "delete_edge": "unlink",
    }
    event_type = event_map.get(verb, "update")
    record_batch_event(
        entity=entity,
        event_type=event_type,
        model_name=type(entity).__name__ if verb not in ("delete_node", "delete_edge") else "",
        actor=user,
        batch_id=batch_id,
        metadata=metadata,
    )


def _auto_batch_name(operations: Sequence[WriteOperation]) -> str:
    """Name an auto-created batch after the work it is scaffolding.

    The name has to be TRUE, not merely present: it is derived from the
    operations themselves, never authored. A single op names its verb and its
    subject (the node type, the edge type, or a short target id); a multi-op
    batch names its size and the distinct verbs in it.
    """

    def subject(op: WriteOperation) -> str:
        if op.type_slug:
            return op.type_slug
        if op.edge_type:
            return op.edge_type
        if op.target:
            return str(op.target)[:8]
        return ""

    # No truncation here: `create_batch()` clamps to what both ends of the spine
    # can hold, and it is the only place that writes them. A second clamp would
    # be a second copy of the limit, free to drift from the first.
    if len(operations) == 1:
        op = operations[0]
        return f"Service write: {op.verb} {subject(op)}".rstrip()
    verbs = ", ".join(sorted({op.verb for op in operations}))
    return f"Service write: {len(operations)} ops ({verbs})"


def _ensure_batch(batch_id: str, user: Any, operations: Sequence[WriteOperation]) -> None:
    """Auto-create a named Batch for batch_id if one does not already exist.

    Runs inside the service layer's transaction so the row participates in
    rollback, and before any operation executes so it is visible to
    `record_batch_event()`, which looks the batch up by `entity_id=batch_id`.
    Idempotent: an existing batch (the caller opened its own) is left alone.

    Routes through `create_batch()` rather than hand-rolling the Entity + Batch
    pair. Hand-rolling is what produced the defect this replaces: the local
    `Entity.objects.create(name=...)` was immediately undone by `Batch.save()`'s
    spine sync projecting `Batch.get_name()` — `""` — back over it, because no
    `name=` reached the Batch. `create_batch()` is the one place that sets both
    ends from one resolved value, so the divergence cannot reappear.
    """
    from tap_grid.batch import AUTO_BATCH_DESCRIPTION, AUTO_BATCH_SOURCE, create_batch
    from tap_grid.models import Batch

    if Batch.objects.filter(entity_id=batch_id).exists():
        return

    create_batch(
        entity_id=uuid.UUID(batch_id),
        name=_auto_batch_name(operations),
        source=AUTO_BATCH_SOURCE,
        description=AUTO_BATCH_DESCRIPTION,
        actor=user,
    )


def _execute_write_pipeline(
    op: WriteOperation,
    *,
    batch_id: str,
    user: Any,
    result_mode: Literal["minimal", "standard", "verbose"],
    internal_only_bypass: bool = False,
    _cascade: _CascadeState | None = None,
) -> WriteResult:
    """Execute the write pipeline for a single WriteOperation.

    `_cascade` is threaded by a contained cascade recursing into its children; it is
    never set by a public caller.

    Returns a WriteResult. Never raises — errors are captured inside the result.

    When `internal_only_bypass=True`, the pipeline does not reject INTERNAL_ONLY
    model types. This flag is for trusted-internal callers (registration
    helpers, lifecycle managers); it is not part of the public write API. See
    `_create_node_internal` / `_patch_node_internal` in this module.
    """
    # Preserve the raw payload with the absent-key vs explicit-null distinction intact.
    # An explicit null is dropped only later, per-field, where the field does not permit
    # null (req-grid-service-write-observation) — never blanket-stripped here, which would
    # collapse "asserted absence" into "omitted" and erase the convention's known-unknown.
    payload: dict[str, Any] = dict(op.payload or {})

    try:
        # Step 2: Security/authz stub (reserved; logs identity at DEBUG).
        logger.debug("[35dc] write_pipeline verb=%s user=%s batch=%s", op.verb, user, batch_id)

        # Step 3: Object load and resolution.
        from tap_grid.registry import get_model_class

        is_create = op.verb in ("create_node", "create_edge")
        is_delete = op.verb in ("delete_node", "delete_edge")

        # OCC pre-check: reject `entity_expected_version` on create verbs.
        # No prior version exists to expect, so this is always a caller mistake.
        # (req-grid-service-batch-occ-4 / req-grid-service-write-occ-2.)
        if is_create and op.entity_expected_version is not None:
            return WriteResult(
                success=False,
                batch_id=batch_id,
                operation=op.verb,
                errors=[
                    ServiceError(
                        code="entity_expected_version_not_allowed_on_create",
                        message=(
                            f"{op.verb} does not accept entity_expected_version; "
                            "no prior version exists on a create."
                        ),
                    )
                ],
            )

        model_cls: type
        instance: Any
        from_entity: Entity | None = None
        to_entity: Entity | None = None
        target_uuid = _coerce_uuid(op.target)

        if op.verb == "create_node":
            if not op.type_slug:
                raise ServiceValidationError("type_slug is required for create_node.")
            try:
                model_cls = get_model_class(op.type_slug)
            except KeyError as exc:
                raise ServiceNotFoundError(f"Unknown entity type: '{op.type_slug}'.") from exc
            if getattr(model_cls, "INTERNAL_ONLY", False) and not internal_only_bypass:
                raise ServiceUnsupportedOperationError(
                    f"'{op.type_slug}' is an internal-only type and cannot be created through the generic service layer."
                )
            instance = model_cls()

        elif op.verb == "create_edge":
            from_uuid = _coerce_uuid(op.from_target)
            to_uuid = _coerce_uuid(op.to_target)
            if from_uuid is None or to_uuid is None:
                raise ServiceValidationError("from_target and to_target are required for create_edge.")
            if not op.edge_type:
                raise ServiceValidationError("edge_type is required for create_edge.")
            from_entity = _load_entity_or_raise(from_uuid)
            to_entity = _load_entity_or_raise(to_uuid)
            # Step 7: Graph invariant — no edges between edges.
            if from_entity.entity_type == "edge":
                raise ServiceConstraintError("Edges cannot have other edges as endpoints (from_entity is an edge).")
            if to_entity.entity_type == "edge":
                raise ServiceConstraintError("Edges cannot have other edges as endpoints (to_entity is an edge).")
            model_cls = Edge
            instance = Edge(from_entity=from_entity, to_entity=to_entity, edge_type=op.edge_type)

        else:
            # patch / replace / delete verbs — load existing instance by target entity_id.
            if target_uuid is None:
                raise ServiceValidationError(f"target is required for {op.verb}.")

            # OCC guard (req-grid-service-batch-occ): when the caller declared
            # entity_expected_version, take a row-level SELECT FOR UPDATE on
            # the Entity row up front. The lock holds until the surrounding
            # transaction commits or rolls back; the subsequent typed-model
            # save + spine sync (or the explicit delete update) is the single
            # version bump per the spec's single-bump invariant. Missing
            # entity is reported as `entity_version_conflict` (not
            # `not_found`) when OCC is engaged, per the spec's not-found-vs-
            # conflict matrix.
            if op.entity_expected_version is not None:
                locked_row = (
                    Entity.objects.select_for_update().filter(pk=target_uuid).only("entity_type", "version").first()
                )
                if locked_row is None:
                    raise ServiceVersionConflictError(
                        entity_expected_version=op.entity_expected_version,
                        actual_entity_version=None,
                        entity_id=str(target_uuid),
                    )
                if locked_row.version != op.entity_expected_version:
                    raise ServiceVersionConflictError(
                        entity_expected_version=op.entity_expected_version,
                        actual_entity_version=locked_row.version,
                        entity_id=str(target_uuid),
                    )
                target_entity = locked_row
            else:
                target_entity = _load_entity_or_raise(target_uuid)

            try:
                model_cls = get_model_class(target_entity.entity_type)
            except KeyError as exc:
                raise ServiceNotFoundError(f"Unknown entity type: '{target_entity.entity_type}'.") from exc
            if getattr(model_cls, "INTERNAL_ONLY", False) and not internal_only_bypass:
                raise ServiceUnsupportedOperationError(
                    f"'{target_entity.entity_type}' is an internal-only type and cannot be modified through the generic service layer."
                )
            instance = model_cls.all_objects.select_related("entity").get(entity_id=target_uuid)

            # Write prohibition — tombstoned entities cannot be mutated.
            if not is_delete and instance.entity.deleted_at is not None:
                raise ServiceConflictError(
                    f"Entity {target_uuid} is tombstoned and cannot be modified.",
                    "entity_tombstoned",
                )

        # Thread caller-supplied dimensions onto the instance so the non-prespecified-id
        # path (BaseModel.save() / Edge.save()) can merge them with type defaults.
        # The prespecified-id branch below applies the same merge explicitly before save().
        if is_create and op.dimensions:
            instance._initial_dimensions = dict(op.dimensions)

        # Step 8 (early): edge_type immutability — checked before schema validation so the
        # error code is "constraint_violation" rather than "validation_error".
        if op.verb in ("patch_edge", "replace_edge") and "edge_type" in payload:
            raise ServiceConstraintError("edge_type is immutable and cannot be changed after creation.")

        # Steps 4 & 5: Schema validation (additionalProperties:False handles strict rejection).
        if not is_delete:
            verb_key = _verb_to_schema_key(op.verb)
            schema = model_cls.SERVICE_CRUD_SCHEMA.get(verb_key, {})
            # Drop an explicit null only where the field does not permit null; preserve it
            # where the schema allows null so it clears the field and earns FLIP
            # (req-grid-service-write-observation-1/2).
            payload = _prepare_null_payload(payload, schema)
            try:
                jsonschema.validate(instance=payload, schema=schema)
            except jsonschema.ValidationError as exc:
                raise ServiceValidationError(exc.message) from exc

        if op.verb == "create_edge":
            try:
                _validate_edge_constraint(from_entity.entity_type, to_entity.entity_type, op.edge_type)  # type: ignore[union-attr]
            except InvalidEdgeError as exc:
                raise ServiceConstraintError(str(exc)) from exc

        # Apply field changes to the instance.
        if op.verb in ("create_node",):
            for field_name, value in payload.items():
                setattr(instance, field_name, value)
        elif op.verb == "create_edge":
            if "properties" in payload:
                instance.properties = payload["properties"]
        elif op.verb in ("patch_node", "patch_edge"):
            _apply_patch(instance, payload)
        elif op.verb in ("replace_node", "replace_edge"):
            _apply_replace(instance, payload, model_cls)

        # Step 6: Model validation (full_validate + Django full_clean).
        if not is_delete:
            try:
                instance.full_validate()
            except DjangoValidationError as exc:
                errors = _django_errors_to_service_errors(exc)
                return WriteResult(success=False, batch_id=batch_id, operation=op.verb, errors=errors)

            try:
                instance.full_clean(exclude=["entity", "batch_id", "flip_map"])
            except DjangoValidationError as exc:
                errors = _django_errors_to_service_errors(exc)
                return WriteResult(success=False, batch_id=batch_id, operation=op.verb, errors=errors)

        # Steps 10 & 11: Persistence and provenance recording.
        # For deletes: record provenance BEFORE tombstoning so the entity row
        # is still valid when record_batch_event() reads it.
        # For creates/updates: record provenance AFTER save so entity_id is set.

        # Pre-create Entity with the caller-specified entity_id for create verbs
        # (e.g. GRIFT upsert where identity must be preserved across grids).
        # This must happen after field-setting so get_name() returns the right value,
        # and before save() so save() takes the explicit-entity path.
        spine_just_created = False
        if is_create and op.entity_id is not None and instance.entity_id is None:
            prespecified_id = _coerce_uuid(op.entity_id)
            if op.verb == "create_edge":
                from tap_grid.constraints import get_edge_default_dimensions

                base_dims = dict(get_edge_default_dimensions(op.edge_type))  # type: ignore[arg-type]
            else:
                base_dims = dict(getattr(model_cls, "DEFAULT_DIMENSIONS", {}))
            caller_dims: dict[str, str] = getattr(instance, "_initial_dimensions", {}) or {}
            merged_dims = {**base_dims, **caller_dims}
            instance.entity = Entity.objects.create(
                id=prespecified_id,
                entity_type=model_cls.ENTITY_TYPE,
                name=instance.get_name(),
                dimensions=merged_dims,
            )
            # Signal BaseModel.save() to skip its spine_updates branch on the
            # subsequent save: this Entity row was created moments ago at
            # version=1 with the correct name/dimensions/updated_at, and the
            # forthcoming save is the SAME logical create operation — not a
            # follow-up mutation. Without this signal, save() would land
            # spine_updates that bump version to 2, producing a single
            # create op that mysteriously lands at version=2 while the
            # auto-create branch (entity_id None) correctly lands at 1.
            # See req-grid-service-batch-occ-2 (single-bump invariant).
            spine_just_created = True

        if is_delete:
            from django.conf import settings as django_settings

            from tap_grid.service_types import CASCADED_REASON

            entity_id_out = target_uuid
            # Reason and metadata (req-grid-service-delete-reason), validated in the
            # pipeline so no caller can bypass the vocabulary or store what cannot be
            # recorded. An omitted reason is `unspecified` — never `operator`.
            provenance = _validate_retirement(op)
            reason = provenance["reason"]
            cap = int(getattr(django_settings, "TAP_CASCADE_MAX_CLOSURE", 5000))

            # Contained cascade (req-grid-service-delete-cascade): an ITERATIVE walk —
            # not recursion, so a chain longer than Python's stack and shorter than the
            # cap cannot blow up (Grok on #568). Children are gathered BEFORE a node's
            # edges are ended, every node is counted against the cap BEFORE it is
            # tombstoned, and the whole walk runs inside write_batch's transaction, so
            # a refusal anywhere rolls the subtree back, target included.
            state = _cascade
            walk = op.verb == "delete_node" and op.cascade == "contained"
            if walk and state is None:
                state = _CascadeState(root=instance.entity_id, root_reason=reason, cap=cap)
                state.discovered.add(instance.entity_id)
            if state is not None:
                state.visited.add(instance.entity_id)
                state.retired += 1
                if state.retired > state.cap:
                    raise ServiceCascadeTooLargeError(
                        f"contained cascade from {state.root} would retire more than "
                        f"TAP_CASCADE_MAX_CLOSURE={state.cap} nodes; nothing written"
                    )
            children: list[uuid.UUID] = []
            if walk and state is not None:
                children = state.discover(
                    _contained_children(instance.entity_id, model_cls, limit=state.headroom(), exclude=state.discovered)
                )

            # Provenance is FAIL-CLOSED for a retirement: a tombstone whose audit record
            # cannot be written is not applied (req-grid-service-delete-reason-1; Codex
            # and Grok on #568). The exception propagates, the transaction rolls back.
            if hasattr(instance, "entity"):
                _record_provenance(op.verb, instance.entity, batch_id, user, metadata=provenance)
            # Tombstone: set deleted_at on the entity and cascade to its edges.
            now = timezone.now()
            from django.db.models import F, Q

            Entity.objects.filter(pk=instance.entity_id).update(
                deleted_at=now,
                updated_at=now,
                version=F("version") + 1,
            )
            # Cascade tombstone to edges at both endpoints.
            edge_entity_ids = list(
                Edge.objects.filter(
                    Q(from_entity_id=instance.entity_id) | Q(to_entity_id=instance.entity_id)
                ).values_list("entity_id", flat=True)
            )
            # In a contained cascade every edge the walk ends records the same provenance
            # a node does — the node it was a consequence of, the root and the root's
            # reason (req-grid-service-delete-cascade-14; Codex on #569: the bulk endpoint
            # update alone left the edges silent). A plain delete keeps its pre-existing
            # shape: the node's event, edges ended by the endpoint rule.
            if state is not None and edge_entity_ids:
                edge_meta = {
                    **{k: v for k, v in provenance.items() if k not in _CASCADE_KEYS},
                    "reason": CASCADED_REASON,
                    "consequence_of": str(instance.entity_id),
                    "cascade_root": str(state.root),
                    "root_reason": state.root_reason,
                }
                for edge_entity in Entity.objects.filter(pk__in=edge_entity_ids, deleted_at__isnull=True):
                    _record_provenance("delete_edge", edge_entity, batch_id, user, metadata=edge_meta)
            Entity.objects.filter(pk__in=edge_entity_ids).update(
                deleted_at=now,
                updated_at=now,
                version=F("version") + 1,
            )

            # The walk: a queue of (child, parent). Each child goes through this same
            # pipeline — the same load, INTERNAL_ONLY and authority checks as any delete —
            # with reason `cascaded` and provenance naming the parent it was a
            # consequence of, the root, and the root's reason
            # (req-grid-service-delete-cascade-14). Its own children are gathered here,
            # before its pipeline call ends its edges.
            if walk and state is not None and _cascade is None:
                queue: deque[tuple[uuid.UUID, uuid.UUID]] = deque((child, instance.entity_id) for child in children)
                inherited = {k: v for k, v in provenance.items() if k not in _CASCADE_KEYS}
                while queue:
                    child_id, parent_id = queue.popleft()
                    if child_id in state.visited:
                        continue
                    grandchildren = state.discover(
                        _children_of(child_id, limit=state.headroom(), exclude=state.discovered)
                    )
                    child_result = _execute_write_pipeline(
                        WriteOperation(
                            verb="delete_node",
                            target=child_id,
                            reason=CASCADED_REASON,
                            metadata={
                                **inherited,
                                "consequence_of": str(parent_id),
                                "cascade_root": str(state.root),
                                "root_reason": state.root_reason,
                            },
                            cascade="none",
                        ),
                        batch_id=batch_id,
                        user=user,
                        result_mode="minimal",
                        internal_only_bypass=internal_only_bypass,
                        _cascade=state,
                    )
                    if not child_result.success:
                        return WriteResult(
                            success=False,
                            batch_id=batch_id,
                            operation=op.verb,
                            errors=[
                                ServiceError(
                                    code=err.code,
                                    message=f"contained cascade from {instance.entity_id} refused at {child_id}: {err.message}",
                                    detail=err.detail,
                                )
                                for err in child_result.errors
                            ],
                        )
                    queue.extend((grandchild, child_id) for grandchild in grandchildren)
        else:
            instance.save(
                skip_validation=True,
                _spine_just_created=spine_just_created,
                flip_changed_fields=_flip_touched_for_verb(op.verb, payload),
            )
            entity_id_out = instance.entity_id
            # Record provenance for non-delete writes too so the BatchEvent log
            # is a complete history of batch-scoped activity. Without this,
            # batch-scoped sweeps (req-grid-import-grift-batch-scoped-sweep)
            # can't identify which entities a batch originally created.
            if hasattr(instance, "entity") and instance.entity is not None:
                try:
                    _record_provenance(op.verb, instance.entity, batch_id, user)
                except Exception:
                    logger.exception("[3c88] Provenance recording failed for batch %s", batch_id)

        # Step 12: Response shaping.
        summary = None
        if result_mode in ("standard", "verbose") and not is_delete:
            summary = _build_object_summary(instance)

        return WriteResult(
            success=True,
            batch_id=batch_id,
            operation=op.verb,
            entity_id=entity_id_out,
            object_summary=summary,
        )

    except ServiceVersionConflictError as exc:
        # OCC conflict — surfaces with the structured detail payload so
        # callers can implement retry-or-surface logic without parsing the
        # message string. See req-grid-service-batch-occ-3.
        return WriteResult(
            success=False,
            batch_id=batch_id,
            operation=op.verb,
            errors=[
                ServiceError(
                    code="entity_version_conflict",
                    message=str(exc),
                    detail=exc.to_detail(),
                )
            ],
        )
    except (
        ServiceValidationError,
        ServiceConstraintError,
        ServiceNotFoundError,
        ServiceAuthzError,
        ServiceConflictError,
        ServiceUnsupportedOperationError,
        ServiceCascadeTooLargeError,
        ServiceInvalidReasonError,
    ) as exc:
        code_map = {
            ServiceValidationError: "validation_error",
            ServiceConstraintError: "constraint_violation",
            ServiceNotFoundError: "not_found",
            ServiceAuthzError: "authz_failure",
            ServiceConflictError: "conflict",
            ServiceUnsupportedOperationError: "unsupported_operation",
            ServiceCascadeTooLargeError: "cascade_closure_too_large",
            ServiceInvalidReasonError: "invalid_reason",
        }
        return WriteResult(
            success=False,
            batch_id=batch_id,
            operation=op.verb,
            errors=[ServiceError(code=code_map[type(exc)], message=str(exc))],  # type: ignore[arg-type]
        )
    except Exception as exc:
        logger.exception("[95fb] Unhandled error in write pipeline for verb=%s", op.verb)
        return WriteResult(
            success=False,
            batch_id=batch_id,
            operation=op.verb,
            errors=[ServiceError(code="internal_error", message=str(exc))],
        )


def _drain_hotlink_checks_into_results(results: list[WriteResult]) -> bool:
    """Pre-commit consistency phase: drain the deferred-hotlink queue.

    Implements req-grid-service-batch-precommit-consistency for the hotlink
    consumer (req-grid-hotlink-deferred). The deferred queue holds the model
    instances whose hotlinks were skipped during per-op validation. The drain
    re-runs validate_hotlinks() on each instance — by now every node and edge
    in this batch has been saved, so the validator sees the batch's intended
    end-state graph.

    The drain collects every failure across the full queue (no first-failure
    bail), attributes each failure to the WriteResult whose entity_id matches
    the failing instance (flipping it to success=False and appending the
    error), and returns True iff any failure was recorded.

    Note: drain_deferred_hotlink_checks() resets the queue to an empty list,
    so re-entrant calls to validate_hotlinks() from within this drain do not
    feed back into the queue we are draining.

    Args:
        results: The per-op WriteResult list, used to attribute failures by
            entity_id.

    Returns:
        True if at least one hotlink failure was collected; False otherwise.
    """
    from tap_grid.hotlink import validate_hotlinks

    queue = drain_deferred_hotlink_checks()
    if not queue:
        return False

    # Build entity_id → WriteResult index for attribution. If multiple ops
    # touched the same entity, the LAST op wins per
    # req-grid-service-batch-precommit-consistency-4.
    result_by_eid: dict[str, WriteResult] = {}
    for r in results:
        if r.entity_id is not None:
            result_by_eid[str(r.entity_id)] = r

    any_failure = False
    for instance in queue:
        try:
            validate_hotlinks(instance)
        except DjangoValidationError as exc:
            any_failure = True
            errors: list[ServiceError] = []
            try:
                for field_name, messages in exc.message_dict.items():
                    for msg in messages:
                        errors.append(
                            ServiceError(
                                code="hotlink_validation_failed",
                                message=str(msg),
                                field=field_name if field_name != "__all__" else None,
                            )
                        )
            except AttributeError:
                for msg in exc.messages:
                    errors.append(ServiceError(code="hotlink_validation_failed", message=str(msg)))

            target = result_by_eid.get(str(instance.entity_id)) if instance.entity_id else None
            if target is not None:
                target.success = False
                target.errors.extend(errors)
            else:
                # No matching result (shouldn't happen — every saved instance
                # came from a per-op pipeline that produced a WriteResult).
                # Attach to the last result as a safety net so the failure is
                # not silently dropped.
                if results:
                    results[-1].success = False
                    results[-1].errors.extend(errors)

    return any_failure


def _assert_debug_for_purge(verb_name: str = "purge_node") -> None:
    """Enforce the DEBUG-only invariant on purge verbs.

    Mirrors req-grid-import-grift-sweep-purge so the "purges are DEBUG-only"
    rule reads consistently across the GRIFT sweep purge and the service-layer
    purge verbs (purge_node, purge_edge). There is no alternate flag, env var,
    or settings key that enables purge in any other configuration.
    """
    from django.conf import settings

    if not settings.DEBUG:
        raise ServiceConflictError(
            f"{verb_name} is permitted only when DEBUG=True (purge_refused_production); " "see req-grid-service-purge."
        )


def _assert_test_or_debug(fn_name: str) -> None:
    """Refuse to run when not in DEBUG / test settings.

    Test detection: pytest sets `PYTEST_CURRENT_TEST` while a test is running.
    DEBUG: Django's settings.DEBUG.
    """
    import os

    from django.conf import settings

    if not settings.DEBUG and "PYTEST_CURRENT_TEST" not in os.environ:
        raise RuntimeError(
            f"{fn_name} is for tests only; it refuses to run outside DEBUG / pytest. "
            "Production code should use the subsystem-owned trusted-internal helper instead."
        )
