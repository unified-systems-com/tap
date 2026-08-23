"""Internal helpers for the tap_grid service layer (below the capability gateway).

Pure logic and below-service-boundary machinery: UUID coercion, schema/payload
shaping, the write pipeline, provenance/batch bookkeeping, entity loading, and
the debug/test guards. NONE of these present a service surface, so none carry a
capability gate — they run *after* an exported gateway callable in
``tap_grid.services`` has already authorized the caller. This module imports
nothing from the gateway (``__init__.py``); the dependency is strictly one-way.
"""

from __future__ import annotations

import logging
import uuid
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
    ServiceConflictError,
    ServiceConstraintError,
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


def _record_provenance(verb: str, entity: Entity, batch_id: str, user: Any) -> None:
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
    )


def _ensure_batch(batch_id: str, user: Any) -> None:
    """Auto-create a Batch entity for batch_id if one does not already exist.

    Called before the main transaction so the Batch row is visible to
    record_batch_event() which looks it up by entity_id=batch_id.
    """
    from tap_grid.models import Batch

    if Batch.objects.filter(entity_id=batch_id).exists():
        return

    # Create the backing Entity with the pre-determined batch_id as its PK.
    entity = Entity.objects.create(
        id=uuid.UUID(batch_id),
        entity_type="batch",
        name=f"Batch {batch_id[:8]}",
    )
    Batch.objects.create(
        entity=entity,
        actor=user,
    )


def _execute_write_pipeline(
    op: WriteOperation,
    *,
    batch_id: str,
    user: Any,
    result_mode: Literal["minimal", "standard", "verbose"],
    internal_only_bypass: bool = False,
) -> WriteResult:
    """Execute the write pipeline for a single WriteOperation.

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
            entity_id_out = target_uuid
            if hasattr(instance, "entity"):
                try:
                    _record_provenance(op.verb, instance.entity, batch_id, user)
                except Exception:
                    logger.exception("[4f93] Provenance recording failed for batch %s", batch_id)
            # Tombstone: set deleted_at on the entity and cascade to its edges.
            now = timezone.now()
            from django.db.models import F, Q

            Entity.objects.filter(pk=instance.entity_id).update(
                deleted_at=now,
                updated_at=now,
                version=F("version") + 1,
            )
            # Cascade tombstone to edges at both endpoints.
            edge_entity_ids = Edge.objects.filter(
                Q(from_entity_id=instance.entity_id) | Q(to_entity_id=instance.entity_id)
            ).values_list("entity_id", flat=True)
            Entity.objects.filter(pk__in=list(edge_entity_ids)).update(
                deleted_at=now,
                updated_at=now,
                version=F("version") + 1,
            )
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
    ) as exc:
        code_map = {
            ServiceValidationError: "validation_error",
            ServiceConstraintError: "constraint_violation",
            ServiceNotFoundError: "not_found",
            ServiceAuthzError: "authz_failure",
            ServiceConflictError: "conflict",
            ServiceUnsupportedOperationError: "unsupported_operation",
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
