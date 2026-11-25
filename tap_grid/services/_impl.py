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
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any, Literal

import jsonschema
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models as django_models
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from tap.jsonfiles import jsonschema_validate
from tap_grid.caller_context import (
    drain_deferred_hotlink_checks,
)
from tap_grid.collection_time import Settled, order_warnings, settle_window
from tap_grid.compound_edges import EMPTY_INDEX, DependentsIndex
from tap_grid.constraints import validate_edge as _validate_edge_constraint
from tap_grid.event_time import derive_for_instance
from tap_grid.exceptions import (
    EdgePropertyValidationError,
    InvalidEdgeError,
    ServiceAuthzError,
    ServiceCascadeTooLargeError,
    ServiceConflictError,
    ServiceConstraintError,
    ServiceEvidenceError,
    ServiceInvalidReasonError,
    ServiceNotFoundError,
    ServiceUnsupportedOperationError,
    ServiceValidationError,
    ServiceVersionConflictError,
)
from tap_grid.models import Edge, Entity
from tap_grid.null_semantics import prepare_null_payload, schema_permits_null
from tap_grid.service_types import (
    NOOP_ALREADY_TOMBSTONED,
    WRITE_CHANGED,
    WRITE_UNCHANGED,
    ServiceError,
    WriteOperation,
    WriteResult,
)
from tap_grid.spine_copies import write_retirement_history
from tap_grid.write_classification import (
    SYSTEM_MANAGED_FIELDS,
    WriteClassification,
    classify,
    snapshot,
    spine_delta,
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


def _flip_stamped(payload: dict[str, Any], classification: WriteClassification | None) -> list[str]:
    """The fields whose FLIP entry a write moves (req-grid-flip-change).

    A create establishes the fields its payload sent. An update-shaped write stamps what its
    classification found: the fields whose value changed, and the named fields asserted for the
    first time. A field the payload repeats, and a field it does not name, keep their entries.
    """
    if classification is None:
        return list(payload.keys())
    return classification.stamped


def _apply_patch(instance: Any, payload: dict[str, Any]) -> None:
    """Apply patch payload to an instance. JSON objects deep-merge; every other value replaces.

    A JSONField holding an object takes an object patch by deep merge. A list, string, number or boolean
    has nothing to merge into, so it replaces what was there (req-grid-service-write-patch-5), as does an
    object patched over a value that is not an object."""
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
            existing = getattr(instance, field_name)
            if isinstance(value, dict) and (existing is None or isinstance(existing, dict)):
                setattr(instance, field_name, _deep_merge(existing or {}, value))
            else:
                setattr(instance, field_name, value)
        else:
            setattr(instance, field_name, value)


def _model_default(instance: Any, field_name: str) -> Any:
    """The value a field takes when nothing sets it: its declared default, else ``""`` for text, else ``None``."""
    model_field = instance._meta.get_field(field_name)
    default = model_field.default
    if default is not django_models.fields.NOT_PROVIDED:
        return default() if callable(default) else default
    return "" if isinstance(model_field, (django_models.CharField, django_models.TextField)) else None


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
                setattr(instance, field_name, _model_default(instance, field_name))
            except Exception:
                pass


def _apply_replace_keep(instance: Any, payload: dict[str, Any], reset_to_default: frozenset[str]) -> None:
    """Apply a keep-absent replace (``WriteOperation.absent == "keep"``).

    A field the payload omits is left alone. A present field replaces its stored value whole, so a JSON object
    is never merged. A field in ``reset_to_default`` was sent as an explicit null on a field that does not permit
    null, and takes its model default (req-grid-service-write-keepabsent-3 and -4).
    """
    for field_name, value in payload.items():
        setattr(instance, field_name, value)
    for field_name in reset_to_default:
        setattr(instance, field_name, _model_default(instance, field_name))


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


_CASCADE_KEYS = frozenset({"reason", "consequence_of", "cascade_root", "root_reason", "compound_end"})


@dataclass
class _CascadeState:
    """Bookkeeping shared by every level of one delete walk (one transaction).

    A walk is a contained cascade (``contained``: follow ``CONTAINMENT_EDGES``), or a plain
    delete whose root is a declared end of a compound edge, or both. Either way it also follows
    the compound-edge retire rule: a middle node whose declared ``retires_with`` end retires is
    retired with it (``req-grid-edge-compound-5``), through ``index``. ``compound_end`` records,
    for each node admitted that way, which end retired it — the walk's provenance carries it.

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
    contained: bool = True
    index: DependentsIndex = EMPTY_INDEX
    compound_end: dict[uuid.UUID, str] = field(default_factory=dict)

    def fresh(self) -> _CascadeState:
        """An empty state for the same walk — same root, reason, cap, mode and index."""
        return _CascadeState(
            root=self.root, root_reason=self.root_reason, cap=self.cap, contained=self.contained, index=self.index
        )

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


def _compound_dependents(
    entity_id: uuid.UUID, index: DependentsIndex, limit: int, exclude: Collection[uuid.UUID] = ()
) -> list[tuple[uuid.UUID, str, str]]:
    """Live middle nodes that retire because ``entity_id`` does: ``(id, entity_type, end)``, at most ``limit``.

    The compound-edge retire rule (``req-grid-edge-compound-5``), read the way containment is:
    before the node's edges are ended, bounded by the walk's headroom, already-discovered nodes
    excluded in the query. A middle node retires with ``entity_id`` when ``entity_id`` is at the
    FROM end of one of its source edges or the TO end of one of its destination edges and its
    type's ``retires_with`` names that end. The far node's type is matched too, so an open-ended
    role edge pointing at some other type never retires it. A path or carrier edge is never read.
    """
    if not index or limit <= 0:
        return []
    out: list[tuple[uuid.UUID, str, str]] = []
    excluded = list(exclude)
    for end, by_edge, near, far in (
        ("source", index.by_source, "from_entity_id", "to_entity"),
        ("destination", index.by_destination, "to_entity_id", "from_entity"),
    ):
        if not by_edge or len(out) >= limit:
            continue
        match = Q()
        for edge_type, middle_types in sorted(by_edge.items()):
            match |= Q(edge_type=edge_type, **{f"{far}__entity_type__in": sorted(middle_types)})
        query = Edge.objects.filter(match, **{near: entity_id, f"{far}__deleted_at__isnull": True})
        # Exclude what the source pass already found IN the query, so a middle node that has the
        # retiring entity at both ends cannot spend the slice and hide another dependent past
        # the headroom (Codex on PR 1268).
        found = excluded + [row[0] for row in out]
        if found:
            query = query.exclude(**{f"{far}_id__in": found})
        rows = query.values_list(f"{far}_id", f"{far}__entity_type").distinct()[: limit - len(out)]
        out.extend((row[0], row[1], end) for row in rows)
    return out


def _refuse_internal_edge_type(edge_type: str, verb: str, internal_only_bypass: bool) -> None:
    """Refuse a generic write of an internal-only edge type (req-grid-edge-internal).

    The edge counterpart of the INTERNAL_ONLY node gate: the trusted-internal path passes the
    bypass, which ``write_batch`` grants a program actor only. Ending a node's edges when the node
    is deleted does not come through here, so an internal-only edge still ends with its endpoint.

    TAP-IMPLEMENTS: req-grid-edge-internal@3947d5d8c25a/f4c607b823a2 (enforcement) — the pipeline's
        refusal, which every write_batch caller and GRIFT import pass through.
    """
    from tap_grid.constraints import is_internal_edge_type

    if is_internal_edge_type(edge_type) and not internal_only_bypass:
        raise ServiceUnsupportedOperationError(
            f"'{edge_type}' is an internal-only edge type and cannot be written through the generic service "
            f"layer ({verb})."
        )


def _lock_rows(entity_ids: Collection[uuid.UUID]) -> list[uuid.UUID]:
    """Take FOR NO KEY UPDATE on the given Entity rows in ascending id order, and return the ids found.

    NO KEY: core never changes an entity's id, and the stronger FOR UPDATE also blocks the foreign-key
    check (FOR KEY SHARE) another writer's typed row makes at commit. Since the spine copies
    (req-grid-entity-spine-copies) a retirement updates each typed row twice in one transaction (the
    trigger's copy, then the FLIP stamp), and PostgreSQL re-checks a row's foreign keys on a second
    update; with FOR UPDATE, a retirement ending an edge whose other endpoint a concurrent delete held
    deadlocked at commit (req-grid-flip-retirement-2). Every writer still excludes every other: NO KEY
    UPDATE conflicts with itself, with FOR UPDATE and with the FOR SHARE a typed insert takes.

    Every delete — plain or cascade — acquires its row locks in one global order: every
    node it will retire, ascending by id, then every edge it will end, ascending by id.
    Two writers that both follow one order cannot wait on each other in a cycle
    (Issue# 590 - tap: the per-target lock alone let a cascade hold edge rows while waiting
    on a node another writer held while waiting on those edges). Rows this transaction
    already holds are re-locked without waiting.
    """
    ids = sorted(set(entity_ids))
    if not ids:
        return []
    locking = Entity.objects.select_for_update(no_key=True).filter(pk__in=ids).order_by("pk")
    return list(locking.values_list("pk", flat=True))


def _closure_cap() -> int:
    """The one reading of ``TAP_CASCADE_MAX_CLOSURE``: the most nodes a contained cascade may
    discover, and so the most a read of the closure will walk before answering "unknown"."""
    from django.conf import settings as django_settings

    return int(getattr(django_settings, "TAP_CASCADE_MAX_CLOSURE", 5000))


def _discover_closure(root_id: uuid.UUID, model_cls: type, state: _CascadeState) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Breadth-first discovery of the whole closure, bounded by the cap, before anything is
    locked or written (req-grid-service-delete-cascade-6). Returns each node's children in
    discovery order — its contained children (in a contained walk), then the middle nodes it
    retires as a compound edge's end (always, req-grid-edge-compound-5); `state.discovered`
    holds the closure and `state.compound_end` says which members came in by the retire rule.

    One walk, one cap, one visited set: a middle node counts against `TAP_CASCADE_MAX_CLOSURE`
    like any child, is found once however many of its ends are in the closure, and its own
    containment (in a contained walk) and its own role as an end are followed in turn.

    TAP-IMPLEMENTS: req-grid-edge-compound@3d34b80a3526/5a8f028b09dc (derivation) — the delete
        walk's discovery: containment and the compound retire rule in one bounded pass.
    """
    from tap_grid.registry import get_model_class

    children_of: dict[uuid.UUID, list[uuid.UUID]] = {}
    frontier: deque[tuple[uuid.UUID, type | None]] = deque([(root_id, model_cls)])
    while frontier:
        node_id, node_cls = frontier.popleft()
        if node_cls is None:
            node_cls = _model_of(node_id)
        kids: list[uuid.UUID] = []
        if state.contained and node_cls is not None:
            kids = state.discover(
                _contained_children(node_id, node_cls, limit=state.headroom(), exclude=state.discovered)
            )
        frontier.extend((k, None) for k in kids)
        dependents = _compound_dependents(node_id, state.index, limit=state.headroom(), exclude=state.discovered)
        admitted = state.discover([dep_id for dep_id, _, _ in dependents])
        fresh = set(admitted)
        for dep_id, dep_type, end in dependents:
            if dep_id not in fresh:
                continue
            state.compound_end[dep_id] = end
            try:
                frontier.append((dep_id, get_model_class(dep_type)))
            except KeyError:
                frontier.append((dep_id, None))
        children_of.setdefault(node_id, []).extend(kids + admitted)
    return children_of


def _closure_under_locks(root_id: uuid.UUID, model_cls: type, state: _CascadeState) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Lock the closure, then recompute it from scratch under those locks, until stable.

    The first discovery ran on an unlocked read. Between it and the locks another writer
    may have attached a child to a closure node (it must be retired) or removed a child's
    containing edge (it must NOT be retired — req-grid-service-delete-cascade-7). So the
    closure is discovered again with the rows held; any node that appears is locked and
    the discovery repeated, until nothing new appears. A FOR UPDATE row cannot gain an edge
    (the insert's KEY SHARE conflicts with it), so the loop converges and is bounded by the
    cap. `state.discovered` ends as the closure the walk will retire.
    """
    _lock_rows(state.discovered)
    while True:
        fresh = state.fresh()
        fresh.discovered.add(root_id)
        children_of = _discover_closure(root_id, model_cls, fresh)
        late = fresh.discovered - state.discovered
        state.discovered = fresh.discovered
        state.compound_end = fresh.compound_end
        if not late:
            return children_of
        _lock_rows(late)


def _warn_shared_parents(root_id: uuid.UUID, closure: Collection[uuid.UUID]) -> None:
    """The directed-graph reading's corner case, named when it happens (Issue# 650 - tap; the
    concept is Issue# 649 - tap): a node in the closure that ANOTHER live parent outside the
    closure still contains is retired with this cascade all the same (ruled; the cascade
    corpus pins it). Nothing changes here — this warning is the visibility the ruling asked
    for, so the case can be found in the logs when a real one arrives.

    The root is not a shared child: its own parents contain it by design, and an ordinary
    "delete a node that has a parent" must not warn. Runs under the cascade's locks, so it is
    three bounded queries, never one per edge: the inbound edges, the outside parents' types,
    and nothing else — the containment declaration is resolved once per type.
    """
    from tap_grid.registry import get_model_class

    inside = set(closure)
    children = inside - {root_id}
    if not children:
        return
    inbound = Edge.objects.filter(Q(to_entity_id__in=children) & ~Q(from_entity_id__in=inside))
    rows = list(inbound.values_list("from_entity_id", "to_entity_id", "edge_type"))  # type: ignore[misc]  # django-stubs
    if not rows:
        return
    parent_types = dict(
        Entity.objects.filter(pk__in={parent_id for parent_id, _, _ in rows}).values_list("id", "entity_type")
    )
    declared_by_type: dict[str, tuple[str, ...]] = {}
    for parent_id, child_id, edge_type in rows:
        parent_type = parent_types.get(parent_id)
        if parent_type is None:
            continue
        if parent_type not in declared_by_type:
            try:
                declared_by_type[parent_type] = tuple(
                    getattr(get_model_class(parent_type), "CONTAINMENT_EDGES", ()) or ()
                )
            except KeyError:
                declared_by_type[parent_type] = ()
        if edge_type in declared_by_type[parent_type]:
            logger.warning(
                "[341b] cascade from %s retires %s although %s still contains it through %s: the directed "
                "containment graph reads shared ownership as ownership by the first parent to cascade "
                "(Issue# 649 - tap)",
                root_id,
                child_id,
                parent_id,
                edge_type,
            )


def _model_of(entity_id: uuid.UUID) -> type | None:
    """The model class of an arbitrary node, by its spine type — the iterative walk's step."""
    from tap_grid.registry import get_model_class

    try:
        entity_type = Entity.objects.only("entity_type").get(pk=entity_id).entity_type
        return get_model_class(entity_type)
    except Entity.DoesNotExist, KeyError:
        return None


def _validate_retirement(op: WriteOperation) -> dict[str, Any]:
    """The reason and metadata a delete records — checked before any write.

    The vocabulary is closed (req-grid-service-delete-reason-3) and the check lives HERE,
    in the pipeline, so a raw ``write_batch([WriteOperation(...)])`` cannot bypass it
    (Codex and Grok on #568). Metadata must be JSON-serialisable: the audit record is
    written fail-closed below, and a payload that cannot be stored must be refused
    rather than silently dropped.

    Only OMISSION defaults: ``reason=None`` records ``unspecified``. An explicit empty
    or whitespace-only string is a stated reason outside the vocabulary and is refused
    like any other (Issue# 576 - tap: ``op.reason or UNSPECIFIED_REASON`` let ``""``
    through as omission).
    """
    from tap_grid.service_types import CASCADE_MODES, DELETE_REASONS, UNSPECIFIED_REASON

    if op.cascade not in CASCADE_MODES:
        raise ServiceValidationError(f"cascade must be one of {sorted(CASCADE_MODES)}; got {op.cascade!r}")
    reason = UNSPECIFIED_REASON if op.reason is None else op.reason
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


def _flip_record_retirement(model_cls: type, entity_ids: list[Any], batch_id: str) -> None:
    """Record the retiring batch in FLIP for objects this retirement tombstones.

    A tombstone is written with a bulk update on the Entity spine, which bypasses
    BaseModel.save() and so the save-time FLIP hook; the retirement path stamps
    `flip_map["deleted_at"]` itself, in the tombstone's transaction
    (req-grid-flip-retirement). Exceptions propagate so the retirement rolls back.

    Every retirement runs inside `write_batch`, which resolves a batch id before any
    operation executes, so a missing one is a broken caller. It raises rather than
    returning: a tombstone without its FLIP entry must not commit.
    """
    from tap_grid.flip import is_flip_enabled

    if not batch_id:
        raise ValueError("a retirement must name its retiring batch; refusing to tombstone without a FLIP entry")
    if not entity_ids or not is_flip_enabled(model_cls):
        return
    from django.db.models import F, Func, JSONField, Value
    from django.db.models.functions import Coalesce, JSONObject

    # One UPDATE for the whole set: merge the entry into each row's map in place, so a
    # cascade's query count does not grow with the number of rows it retires. Built
    # from ORM expressions, so the batch id is always a bound parameter.
    merged = Func(
        Coalesce(F("flip_map"), Value({}, output_field=JSONField())),
        JSONObject(deleted_at=Value(str(batch_id))),
        template="(%(expressions)s)",
        arg_joiner=" || ",
        output_field=JSONField(),
    )
    model_cls.all_objects.filter(entity_id__in=entity_ids).update(flip_map=merged)  # type: ignore[attr-defined]


def _record_provenance(
    verb: str,
    entity: Entity,
    batch_id: str,
    user: Any,
    metadata: dict[str, Any] | None = None,
    *,
    observed_unchanged: bool = False,
    collected: Settled | None = None,
) -> None:
    """Record a BatchEvent for the operation, or raise: a write is not applied without its record.

    ``collected`` is the collection window the writer stated for the object; the event carries
    it as the per-pass record (req-grid-entity-collection-time), empty when none was stated.

    An update-shaped operation that re-observed its object unchanged is recorded as ``observe``
    (req-grid-history-reobservation). The record is evidence reconciliation reads, so a batch
    that cannot be found is a failure, never a skipped record (req-grid-service-batch-evidence).

    TAP-IMPLEMENTS: req-grid-service-batch-evidence@02ccdac55a7a/318a9e86fed5 (enforcement) — the one
        recorder the write pipeline calls: a missing batch or a failed insert fails the operation.
    """
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
    event_type = "observe" if observed_unchanged else event_map.get(verb, "update")
    try:
        recorded = record_batch_event(
            entity=entity,
            event_type=event_type,
            model_name=type(entity).__name__ if verb not in ("delete_node", "delete_edge") else "",
            actor=user,
            batch_id=batch_id,
            metadata=metadata,
            collected_start=collected.start if collected is not None else None,
            collected_end=collected.end if collected is not None else None,
        )
    except Exception as exc:
        raise ServiceEvidenceError(
            f"the batch's record of {verb} on {entity.pk} could not be written; nothing applied"
        ) from exc
    if recorded is None:
        raise ServiceEvidenceError(f"no batch {batch_id} to record {verb} on {entity.pk} in; nothing applied")


def _pointer_uuid(batch_id: str | uuid.UUID) -> uuid.UUID:
    """The pipeline's batch id as the UUID the spine's batch pointers store.

    A pipeline operation always runs in a batch; one that somehow has none is refused here, so a
    change never leaves a null pointer (req-grid-entity-batch-pointers rule 6).
    """
    if not batch_id:
        raise ServiceEvidenceError("the operation has no batch in context; a change names the batch that made it")
    return batch_id if isinstance(batch_id, uuid.UUID) else uuid.UUID(str(batch_id))


def _stamp_observed(entity: Entity, batch_id: str, collected: Settled) -> None:
    """Record on the spine that this batch named an object it did not change.

    A direct row update: it does not increment ``version``, does not move ``updated_at`` (a
    queryset update does not fire ``auto_now``) and writes no history, since ``Entity`` has none.
    ``last_changed_batch_id`` is left naming the batch that last changed the row.

    req-grid-entity-batch-pointers rule 3: the observed pair is set for an object an operation
    names and leaves unchanged, with no version, no ``updated_at`` move and no history.

    The collection window rides the same statement (req-grid-entity-collection-time rule 4): the
    pair this batch stated for the object, or empty when it stated none, so the pair on the row
    is always the one of the batch ``last_observed_batch_id`` names (rule 5).
    """
    observed_by = _pointer_uuid(batch_id)
    now = timezone.now()
    Entity.objects.filter(pk=entity.pk).update(
        last_observed_batch_id=observed_by,
        last_observed_at=now,
        collected_start=collected.start,
        collected_end=collected.end,
    )
    entity.last_observed_batch_id = observed_by
    entity.last_observed_at = now
    entity.collected_start = collected.start
    entity.collected_end = collected.end


def _ensure_batch(batch_id: str, user: Any, *, name: str, description: str) -> None:
    """Create the named Batch for batch_id if one does not already exist.

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

    ``name`` / ``description`` say what the change is. `write_batch` refuses a
    minting write that has none before it gets here
    (req-grid-service-batch-label-required), so both are always present. ``source``
    stays the service layer: it is the producer, whoever named the change.
    """
    from tap_grid.batch import AUTO_BATCH_SOURCE, create_batch
    from tap_grid.models import Batch

    if Batch.objects.filter(entity_id=batch_id).exists():
        return

    create_batch(
        entity_id=uuid.UUID(batch_id),
        name=name,
        source=AUTO_BATCH_SOURCE,
        description=description,
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
    # The collection window the writer stated for this operation's object, settled once: the pair
    # every write below records, or empty with the reason (req-grid-entity-collection-time rules
    # 3 and 6). It is not a field of the object and takes no part in classifying the write.
    collected = settle_window(op.collected)
    # The pair the row carried before this write, to tell an older read arriving late (rule 5).
    stored_window: tuple[Any, Any] = (None, None)

    try:
        # Step 2: Security/authz stub (reserved; logs identity at DEBUG).
        logger.debug("[35dc] write_pipeline verb=%s user=%s batch=%s", op.verb, user, batch_id)

        # Step 3: Object load and resolution.
        from tap_grid.registry import get_model_class

        is_create = op.verb in ("create_node", "create_edge")
        is_delete = op.verb in ("delete_node", "delete_edge")

        # req-grid-service-write-keepabsent-5: keep-absent is a replace-only mode; refuse it elsewhere
        # rather than ignore it.
        if op.absent == "keep" and op.verb not in ("replace_node", "replace_edge"):
            return WriteResult(
                success=False,
                batch_id=batch_id,
                operation=op.verb,
                errors=[
                    ServiceError(
                        code="absent_not_allowed",
                        message=f"{op.verb} does not accept absent='keep'; only replace_node and replace_edge do.",
                    )
                ],
            )

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
        reset_to_default: frozenset[str] = frozenset()
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
            # No live edge may point at a tombstone (Issue# 609 - tap, ruled 2026-09-18): the
            # endpoints are row-locked first, in the delete's global order, so a delete of
            # either endpoint waits for this edge to commit (and then ends it in its own
            # incident-edge pass) or has already committed and is seen here as a tombstone.
            _lock_rows([from_uuid, to_uuid])
            from_entity = _load_entity_or_raise(from_uuid)
            to_entity = _load_entity_or_raise(to_uuid)
            for role, endpoint in (("from_entity", from_entity), ("to_entity", to_entity)):
                if endpoint.deleted_at is not None:
                    raise ServiceConflictError(
                        f"Entity {endpoint.pk} is tombstoned; an edge cannot be created onto a tombstone ({role}).",
                        "entity_tombstoned",
                    )
            # Step 7: Graph invariant — no edges between edges.
            if from_entity.entity_type == "edge":
                raise ServiceConstraintError("Edges cannot have other edges as endpoints (from_entity is an edge).")
            if to_entity.entity_type == "edge":
                raise ServiceConstraintError("Edges cannot have other edges as endpoints (to_entity is an edge).")
            model_cls = Edge
            _refuse_internal_edge_type(op.edge_type, op.verb, internal_only_bypass)
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
                    Entity.objects.select_for_update(no_key=True)
                    .filter(pk=target_uuid)
                    .only("entity_type", "version")
                    .first()
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
                # EVERY mutating verb locks its target row first, OCC or not. For a delete
                # (req-grid-service-delete-tombstone-6) the repeat-delete no-op below decides
                # on `deleted_at`; for a patch or replace the write prohibition below decides
                # on it too — and a decision made on an unlocked read is a race: a row
                # tombstoned while the replace waited on the holder's lock was still written,
                # onto the tombstone, at version 3 (Issue# 611 - tap; the delete side was
                # Issue# 590). The lock serialises them: the second waits, then reads the
                # committed tombstone and refuses (or no-ops, for a delete). Held to the end
                # of write_batch's transaction, like OCC's.
                locked_row = (
                    Entity.objects.select_for_update(no_key=True).filter(pk=target_uuid).only("entity_type").first()
                )
                if locked_row is None:
                    raise ServiceNotFoundError(f"Entity {target_uuid} not found.")
                target_entity = locked_row

            try:
                model_cls = get_model_class(target_entity.entity_type)
            except KeyError as exc:
                raise ServiceNotFoundError(f"Unknown entity type: '{target_entity.entity_type}'.") from exc
            if getattr(model_cls, "INTERNAL_ONLY", False) and not internal_only_bypass:
                raise ServiceUnsupportedOperationError(
                    f"'{target_entity.entity_type}' is an internal-only type and cannot be modified through the generic service layer."
                )
            instance = model_cls.all_objects.select_related("entity").get(entity_id=target_uuid)
            if isinstance(instance, Edge):
                _refuse_internal_edge_type(instance.edge_type, op.verb, internal_only_bypass)
            stored_window = (instance.entity.collected_start, instance.entity.collected_end)

            # Write prohibition — tombstoned entities cannot be mutated.
            if not is_delete and instance.entity.deleted_at is not None:
                raise ServiceConflictError(
                    f"Entity {target_uuid} is tombstoned and cannot be modified.",
                    "entity_tombstoned",
                )

        # A type whose rows are behind its code takes no write until migrations are applied
        # (req-grid-entity-model-version rule 4). One write is let through: a retirement, which
        # this pipeline only ever takes by id. It reads and writes no field of the type, and it
        # is the cleanup a refused migration asks for.
        if not is_delete:
            from tap_grid.model_version import disagreement, row_type_slug

            behind = disagreement(row_type_slug(instance) or "")
            if behind is not None:
                return WriteResult(
                    success=False,
                    batch_id=batch_id,
                    operation=op.verb,
                    errors=[
                        ServiceError(
                            code="model_version_pending",
                            message=str(behind.refusal(f"{op.verb} on it")),
                            detail={
                                "type": behind.type_slug,
                                "declared_version": behind.declared,
                                "applied_version": behind.applied,
                            },
                        )
                    ],
                )

        # Thread caller-supplied dimensions onto the instance so the non-prespecified-id
        # path (BaseModel.save() / Edge.save()) can merge them with type defaults.
        # The prespecified-id branch below applies the same merge explicitly before save().
        # The caller's map in stored shape (req-grid-dimension-reference-3). A map the importer
        # already settled under a trusted collector run passes through; any other is untrusted, so
        # a `src: derived` in it is reset to declared and `src: default` is refused.
        # Dimensions are set at create. A replace or patch verb never writes them (the importer's
        # replace re-stamps a node's map itself), so any map handed to one, `{}` included, is refused,
        # not dropped.
        if not is_create and op.dimensions is not None:
            raise ServiceValidationError(
                f"{op.verb} does not write dimensions; they are set when the entity is created"
            )
        if is_create and op.dimensions:
            from tap_grid.dimension_map import DimensionWriteError, supplied

            try:
                instance._initial_dimensions = supplied(
                    op.dimensions, where=f"{op.type_slug or op.edge_type} dimensions"
                )
            except (DimensionWriteError, LookupError) as error:
                raise ServiceValidationError(str(error)) from error

        # A type keyed on a dimension cannot be created without its value: a hole would mint a new
        # row on every run instead of finding the last one (req-grid-entity-natural-key-30).
        if op.verb == "create_node":
            try:
                missing = instance.missing_key_dimensions()
            except (LookupError, ValueError) as error:  # an undeclared or ineligible key dimension (-29)
                raise ServiceValidationError(str(error)) from error
            if missing:
                raise ServiceValidationError(
                    f"{op.type_slug} is keyed on {missing}; a create must supply a value for each "
                    "(req-grid-entity-natural-key-30)."
                )

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
            prepared_payload = _prepare_null_payload(payload, schema)
            if op.absent == "keep":
                # A null the prep dropped (null on a non-null field) resets to the default in this mode.
                reset_to_default = frozenset(key for key in payload if key not in prepared_payload)
            payload = prepared_payload
            try:
                jsonschema_validate(payload, schema)
            except jsonschema.ValidationError as exc:
                raise ServiceValidationError(exc.message) from exc

        if op.verb == "create_edge":
            try:
                _validate_edge_constraint(from_entity.entity_type, to_entity.entity_type, op.edge_type)  # type: ignore[union-attr]
            except InvalidEdgeError as exc:
                raise ServiceConstraintError(str(exc)) from exc

        # The stored state an update-shaped write is compared against, taken before the payload
        # is applied (req-grid-flip-change rule 1).
        before = None if is_create or is_delete else snapshot(instance, frozenset(payload) | reset_to_default)

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
            if op.absent == "keep":
                _apply_replace_keep(instance, payload, reset_to_default)
            else:
                _apply_replace(instance, payload, model_cls)

        # Step 6: Model validation (full_validate + Django full_clean), on the values in the form
        # they are stored in. The model's write hook and every check a save would run happen here,
        # before the write is classified, so a write found unchanged has skipped none of them
        # (req-grid-history-reobservation rule 10).
        if not is_delete:
            instance._prepare_for_write_checked()
            if is_create and op.entity_id is not None and instance.entity_id is None:
                # The id this create will land under, so a whole-record check can tell the row
                # from another one (Dimension.validate's duplicate-name rule; the spine row is
                # created after validation, below).
                instance._pending_entity_id = str(_coerce_uuid(op.entity_id))
            try:
                instance.full_validate()
            except DjangoValidationError as exc:
                errors = _django_errors_to_service_errors(exc)
                return WriteResult(success=False, batch_id=batch_id, operation=op.verb, errors=errors)

            try:
                instance.full_clean(exclude=sorted(SYSTEM_MANAGED_FIELDS))
            except DjangoValidationError as exc:
                errors = _django_errors_to_service_errors(exc)
                return WriteResult(success=False, batch_id=batch_id, operation=op.verb, errors=errors)

        # Changed, or re-observed unchanged: classified once, after validation has cleaned the
        # values to their stored types. FLIP, the save, the version and the batch's record all
        # read this one result (req-grid-history-reobservation rule 5).
        classification: WriteClassification | None = None
        if before is not None:
            if isinstance(instance, Edge):
                # Edge.save validates the properties against the edge type's schema; an unchanged
                # edge skips the save, so the check runs here for every update-shaped write.
                from tap_grid.constraints import validate_edge_properties

                validate_edge_properties(instance.edge_type, instance.properties)
            classification = classify(
                instance,
                before,
                frozenset(payload) | reset_to_default,
                # Read here, not where the operation was built: the target's row has been locked
                # since it was loaded, so no other writer can move the spine between this
                # comparison and the caller's write of it.
                caller_spine_change=bool(spine_delta(op.spine_intent)),
            )

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
            from tap_grid.dimension_map import DimensionWriteError, settle

            caller_dims: Any = getattr(instance, "_initial_dimensions", {}) or {}
            # Derived once and written twice below: the three event columns, and the kind as the
            # row's `tap.time` dimension (req-grid-entity-event-time rule 3).
            created_event_time = derive_for_instance(instance)
            try:
                merged_dims = settle(
                    base_dims,
                    caller_dims,
                    grid=created_event_time.as_dimensions(),
                    where=f"{op.type_slug or op.edge_type} dimensions",
                )
            except (DimensionWriteError, LookupError) as error:
                raise ServiceValidationError(str(error)) from error
            instance.entity = Entity.objects.create(
                id=prespecified_id,
                entity_type=model_cls.ENTITY_TYPE,
                name=instance.get_name(),
                # The row's natural key, which BaseModel.save derives again and stores on the row
                # (req-grid-entity-natural-key-19); the save below skips its spine sync for this
                # logical create, so the spine copy is written here.
                natural_key=instance.derive_natural_key(),
                dimensions=merged_dims,
                # The creating batch, as last to change and last to observe the row; the save
                # below skips its spine update for this same create, so they are written here
                # (req-grid-entity-batch-pointers rules 2 and 5).
                last_changed_batch_id=_pointer_uuid(batch_id),
                last_observed_batch_id=_pointer_uuid(batch_id),
                # Event time, derived from the fields the model declares; written here for the
                # same reason as the natural key (req-grid-entity-event-time rule 3).
                **created_event_time.as_columns(),
                # The collection window the creating batch stated, for the same reason as the
                # pointers (req-grid-entity-collection-time rule 4).
                **collected.as_columns(),
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

            from tap_grid.service_types import CASCADED_REASON

            entity_id_out = target_uuid
            # Reason and metadata (req-grid-service-delete-reason), validated in the
            # pipeline so no caller can bypass the vocabulary or store what cannot be
            # recorded. An omitted reason is `unspecified` — never `operator`.
            provenance = _validate_retirement(op)
            reason = provenance["reason"]

            # Repeat delete is a SILENT no-op (req-grid-service-delete-tombstone-6;
            # Issue# 575 - tap). A retry after a timeout must not create history: the
            # tombstone's `deleted_at`, `updated_at` and `version` stand, no second
            # retirement event is recorded, the edges are left as the first delete left
            # them, and a contained cascade from a retired root walks nothing — the same
            # rule the walk already applies to an already-retired child
            # (req-grid-service-delete-cascade-3), applied at the root. The OCC check
            # above still ran, so a stale expected version conflicts before this point.
            # The input was validated first: a malformed retry is refused, not ignored.
            if instance.entity.deleted_at is not None:
                return WriteResult(
                    success=True,
                    batch_id=batch_id,
                    operation=op.verb,
                    entity_id=target_uuid,
                    # The token and the id only — not the retirement time. A delete
                    # capability is not a licence to read tombstone history, and current-
                    # state reads hide tombstones; the warning must not become the oracle
                    # they refuse to be (Codex on #579).
                    warnings=[f"{NOOP_ALREADY_TOMBSTONED}: {target_uuid} is already retired; nothing written"],
                )
            cap = _closure_cap()

            # Contained cascade (req-grid-service-delete-cascade): an ITERATIVE walk —
            # not recursion, so a chain longer than Python's stack and shorter than the
            # cap cannot blow up (Grok on #568). Children are gathered BEFORE a node's
            # edges are ended, every node is counted against the cap BEFORE it is
            # tombstoned, and the whole walk runs inside write_batch's transaction, so
            # a refusal anywhere rolls the subtree back, target included.
            state = _cascade
            contained = op.verb == "delete_node" and op.cascade == "contained"
            # A plain delete walks too when some registered type is a compound edge's middle
            # node: an end that retires retires the middle nodes that declare it in
            # `retires_with`, by plain delete or by cascade (req-grid-edge-compound-5). The
            # index is empty — and the plain delete untouched — when no type declares one.
            from tap_grid.compound_edges import dependents_index

            index = dependents_index() if op.verb == "delete_node" and _cascade is None else EMPTY_INDEX
            walk = _cascade is None and (contained or bool(index))
            if walk:
                state = _CascadeState(
                    root=instance.entity_id, root_reason=reason, cap=cap, contained=contained, index=index
                )
                state.discovered.add(instance.entity_id)
            children: list[uuid.UUID] = []
            children_of: dict[uuid.UUID, list[uuid.UUID]] = {}
            if walk and state is not None:
                # Gather the whole closure, then lock every node of it in id order, then
                # every edge it will end — before writing anything. Two writers that both
                # take their locks in this one order cannot deadlock, and rows held FOR
                # UPDATE cannot be re-tombstoned or gain edges under us (Issue# 590 - tap;
                # req-grid-service-delete-cascade-6). The compound retire rule rides the same
                # discovery, cap, lock order and provenance (req-grid-edge-compound-5).
                _discover_closure(instance.entity_id, model_cls, state)
                children_of = _closure_under_locks(instance.entity_id, model_cls, state)
                if not contained and state.discovered == {instance.entity_id}:
                    # A plain delete that retires no middle node keeps its pre-existing shape:
                    # the node's event, its edges ended by the endpoint rule, no walk records.
                    walk, state, children_of = False, None, {}
            if state is not None:
                state.visited.add(instance.entity_id)
                state.retired += 1
                if state.retired > state.cap:
                    raise ServiceCascadeTooLargeError(
                        f"contained cascade from {state.root} would retire more than "
                        f"TAP_CASCADE_MAX_CLOSURE={state.cap} nodes; nothing written"
                    )
            if walk and state is not None:
                try:
                    _warn_shared_parents(instance.entity_id, state.discovered)
                except Exception as exc:  # noqa: BLE001 — advisory only: never fail a cascade that holds its locks
                    logger.warning("[34a9] shared-parent check skipped: %s: %s", type(exc).__name__, exc)
                closure_edge_ids = list(
                    Edge.objects.filter(
                        Q(from_entity_id__in=state.discovered) | Q(to_entity_id__in=state.discovered)
                    ).values_list("entity_id", flat=True)
                )
                _lock_rows(closure_edge_ids)
                children = children_of.get(instance.entity_id, [])

            # Provenance is FAIL-CLOSED for a retirement: a tombstone whose audit record
            # cannot be written is not applied (req-grid-service-delete-reason-1; Codex
            # and Grok on #568). The exception propagates, the transaction rolls back.
            if hasattr(instance, "entity"):
                _record_provenance(op.verb, instance.entity, batch_id, user, metadata=provenance, collected=collected)
            # Tombstone: set deleted_at on the entity and cascade to its edges.
            now = timezone.now()

            # A retirement is a change: the retiring batch is named in the statement that
            # increments `version`, on the node here and on every edge it ends below
            # (req-grid-entity-batch-pointers rules 2 and 5).
            retiring_batch = _pointer_uuid(batch_id)
            Entity.objects.filter(pk=instance.entity_id, deleted_at__isnull=True).update(
                deleted_at=now,
                updated_at=now,
                version=F("version") + 1,
                last_changed_batch_id=retiring_batch,
                last_observed_batch_id=retiring_batch,
                last_observed_at=now,
                # The window the retiring batch stated for this object, or empty
                # (req-grid-entity-collection-time rules 4 and 5).
                **collected.as_columns(),
            )
            if getattr(model_cls, "ENTITY_TYPE", None) == "dimension":
                # A queryset update sends no signal: tell the live vocabulary a node retired, so it
                # stops resolving within this same write (req-grid-dimension-reference-9).
                from tap_grid.live_dimensions import invalidate

                invalidate()
            _flip_record_retirement(model_cls, [instance.entity_id], batch_id)
            # The retirement's final history row (req-grid-entity-spine-copies rule 13): it holds the
            # retirement copy and the reason. Written after the entity row, which the trigger has
            # copied to the typed row by now.
            write_retirement_history(model_cls, [instance.entity_id], reason=reason, batch_id=batch_id)
            # Edges to end, gathered under this node's lock. A plain delete locks them now,
            # in id order (a cascade already holds every edge of its closure); the ending
            # is conditional on the row still being live, so an edge another writer ended
            # first is neither bumped nor recorded again (Issue# 590 - tap, second shape).
            incident = list(
                Edge.objects.filter(
                    Q(from_entity_id=instance.entity_id) | Q(to_entity_id=instance.entity_id)
                ).values_list("entity_id", flat=True)
            )
            _lock_rows(incident)
            edge_entity_ids = list(
                Entity.objects.filter(pk__in=incident, deleted_at__isnull=True).values_list("pk", flat=True)
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
                for edge_entity in Entity.objects.filter(pk__in=edge_entity_ids):
                    _record_provenance("delete_edge", edge_entity, batch_id, user, metadata=edge_meta)
            Entity.objects.filter(pk__in=edge_entity_ids, deleted_at__isnull=True).update(
                deleted_at=now,
                updated_at=now,
                version=F("version") + 1,
                last_changed_batch_id=retiring_batch,
                last_observed_batch_id=retiring_batch,
                last_observed_at=now,
                # The batch stated a window for the node it named, not for the edges that end
                # with it; a pair is never left standing for a batch that stated none
                # (req-grid-entity-collection-time rule 5).
                collected_start=None,
                collected_end=None,
            )
            _flip_record_retirement(Edge, edge_entity_ids, batch_id)
            # And one for every edge this retirement ended, with the reason its own record carries:
            # `cascaded` in a cascade, the node's reason where the endpoint rule ended it (rule 13).
            write_retirement_history(
                Edge, edge_entity_ids, reason=CASCADED_REASON if state is not None else reason, batch_id=batch_id
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
                    grandchildren = children_of.get(child_id, [])
                    child_meta: dict[str, Any] = {
                        **inherited,
                        "consequence_of": str(parent_id),
                        "cascade_root": str(state.root),
                        "root_reason": state.root_reason,
                    }
                    if child_id in state.compound_end:
                        # Retired as a compound edge's middle node: which declared end took it
                        # (req-grid-edge-compound-5), so the record says why, not only that.
                        child_meta["compound_end"] = state.compound_end[child_id]
                    child_result = _execute_write_pipeline(
                        WriteOperation(
                            verb="delete_node",
                            target=child_id,
                            reason=CASCADED_REASON,
                            metadata=child_meta,
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
            unchanged = classification is not None and not classification.changed
            # The write and the batch's record of it commit together or not at all
            # (req-grid-service-batch-evidence): one savepoint holds both.
            with transaction.atomic():
                if not unchanged:
                    instance.save(
                        skip_validation=True,
                        _spine_just_created=spine_just_created,
                        flip_changed_fields=_flip_stamped(payload, classification),
                        _collected=collected.as_columns(),
                        _spine_intent=op.spine_intent,
                    )
                # A re-observed-unchanged operation does not save the typed row, so it writes
                # no history row, no version and no FLIP entry, and leaves updated_at alone
                # (req-grid-history-reobservation rule 3). The batch still records that it saw
                # the object, as an `observe` event, which batch-scoped sweeps and
                # reconciliation read beside create and update.
                _record_provenance(
                    op.verb, instance.entity, batch_id, user, observed_unchanged=unchanged, collected=collected
                )
                if unchanged:
                    _stamp_observed(instance.entity, batch_id, collected)
            entity_id_out = instance.entity_id

        # Step 12: Response shaping.
        summary = None
        if result_mode in ("standard", "verbose") and not is_delete:
            summary = _build_object_summary(instance)

        outcome: Literal["changed", "unchanged"] | None = None
        if not is_delete:
            outcome = WRITE_UNCHANGED if classification is not None and not classification.changed else WRITE_CHANGED
        return WriteResult(
            success=True,
            batch_id=batch_id,
            operation=op.verb,
            entity_id=entity_id_out,
            object_summary=summary,
            state=outcome,
            # A declared event time the grid could not store truthfully is left off the spine
            # and reported here, naming the field (req-grid-entity-event-time rule 12). It is
            # reported on an unchanged write too: the typed value is still what it was.
            # Then what there is to say about the collection window: one left out, an older read
            # arriving late, a clock out of order (req-grid-entity-collection-time rules 5 to 7).
            warnings=[
                *([] if is_delete else derive_for_instance(instance).warnings),
                *collected.warnings,
                *order_warnings(
                    collected,
                    entity_id=entity_id_out,
                    stored_start=stored_window[0],
                    stored_end=stored_window[1],
                    event_start=getattr(getattr(instance, "entity", None), "event_start", None),
                    now=timezone.now(),
                ),
            ],
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
        ServiceEvidenceError,
        EdgePropertyValidationError,
    ) as exc:
        code_map = {
            ServiceValidationError: "validation_error",
            # An edge's properties failed its type's schema (req-grid-edge-properties-8): a
            # caller's input error, reported as one, never an unhandled pipeline failure.
            EdgePropertyValidationError: "validation_error",
            ServiceConstraintError: "constraint_violation",
            ServiceNotFoundError: "not_found",
            ServiceAuthzError: "authz_failure",
            ServiceConflictError: "conflict",
            ServiceUnsupportedOperationError: "unsupported_operation",
            ServiceCascadeTooLargeError: "cascade_closure_too_large",
            ServiceInvalidReasonError: "invalid_reason",
            ServiceEvidenceError: "evidence_not_recorded",
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
