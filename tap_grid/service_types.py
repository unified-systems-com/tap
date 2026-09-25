"""Write operation data types for the TAP service layer.

These dataclasses form the public contract for write_batch() and the
single-verb convenience functions. They carry no Django or ORM imports
so callers can import them without triggering the Django app registry.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class WriteOperation:
    """A single write intent submitted to write_batch().

    Attributes:
        verb: One of create_node | patch_node | replace_node | delete_node |
              create_edge | patch_edge | replace_edge | delete_edge.
        type_slug: Entity type slug, required for create_node.
        target: Entity UUID (str or uuid.UUID) for patch / replace / delete verbs.
        payload: JSON-safe field values validated against SERVICE_CRUD_SCHEMA.
        from_target: Source entity UUID for create_edge.
        to_target: Destination entity UUID for create_edge.
        edge_type: Edge type string for create_edge.
        entity_id: Pre-specified entity_id for create verbs (e.g. GRIFT upsert).
        dimensions: Caller-supplied dimensions for create verbs. Merged over the
            model class's DEFAULT_DIMENSIONS (caller wins on conflicting keys).
            Applied on both create_node and create_edge paths.
        reason: Closed-vocabulary retirement reason for delete verbs
            (req-grid-service-delete-reason); omitted records ``unspecified``,
            never ``operator``.
        metadata: Structured context for delete verbs, recorded beside the reason
            in the tombstone's BatchEvent. Its shape is keyed by the reason.
        cascade: ``"contained"`` retires everything reachable from the target by
            its model's declared CONTAINMENT_EDGES, in the same transaction
            (req-grid-service-delete-cascade). ``"none"`` (default) retires the
            target and ends its edges only.
        entity_expected_version: Optional optimistic-concurrency declaration
            (req-grid-service-batch-occ). When set, the pipeline takes a
            SELECT FOR UPDATE on the target Entity row before mutation and
            raises `entity_version_conflict` if `Entity.version` does not
            match. Create verbs reject the parameter with
            `entity_expected_version_not_allowed_on_create`. Omitted means
            no version check (current behavior).
    """

    verb: str
    type_slug: str | None = None
    target: str | uuid.UUID | None = None
    payload: dict[str, Any] | None = None
    from_target: str | uuid.UUID | None = None
    to_target: str | uuid.UUID | None = None
    edge_type: str | None = None
    entity_id: str | uuid.UUID | None = None
    dimensions: dict[str, str] | None = None
    entity_expected_version: int | None = None
    reason: str | None = None
    metadata: dict[str, Any] | None = None
    cascade: Literal["none", "contained"] = "none"


# Retirement reasons — a closed vocabulary (req-grid-service-delete-reason-3). A third
# state whose justification is unconstrained becomes a place to put discomfort rather
# than a fact. `operator` asserts a human acted and is therefore never a default: an
# omitted reason records `unspecified`, which claims nothing about who decided.
DELETE_REASONS: frozenset[str] = frozenset(
    {
        "dropped_from_observation",
        "scope_withdrawn",
        "cascaded",
        "resolved",
        "operator",
        "grift_import",
        "unspecified",
    }
)
UNSPECIFIED_REASON = "unspecified"
CASCADED_REASON = "cascaded"
# Cascade modes are a closed set too: a value outside it is a refusal, never a silent
# fall-through to "none" (Codex on #569 — a typo must not tombstone the root and leave
# its contained children live).
CASCADE_MODES: frozenset[str] = frozenset({"none", "contained"})
# A repeat delete of an already-tombstoned target succeeds and writes nothing
# (req-grid-service-delete-tombstone-6). The result says so with a warning that
# starts with this token, so a retrying caller — human or AI — can tell "retired
# just now" from "was already retired" without reading the spine.
NOOP_ALREADY_TOMBSTONED = "noop_already_tombstoned"


@dataclass
class ServiceError:
    """Structured error from the write pipeline.

    Attributes:
        code: Machine-readable error category.
        message: Human-readable description.
        field: Model field name if the error is field-specific.
        detail: Optional structured context for admin or bot inspection.
    """

    code: Literal[
        "validation_error",
        "constraint_violation",
        "authz_failure",
        "not_found",
        "conflict",
        "unsupported_operation",
        "internal_error",
        "write_conflict",
        "hotlink_validation_failed",
        # Optimistic concurrency (req-grid-service-batch-occ).
        "entity_version_conflict",
        "entity_expected_version_not_allowed_on_create",
        # Retirement (req-grid-service-delete-reason / -cascade).
        "invalid_reason",
        "cascade_closure_too_large",
        # A minting write with no name or description (req-grid-service-batch-label-required).
        "batch_label_required",
    ]
    message: str
    field: str | None = None
    detail: dict[str, Any] | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class IdentityResolution:
    """What ``resolve_identity`` decided for one source object (the gate, shape A).

    Attributes:
        entity_id: The id to write under — an existing live row's, or a fresh assignment.
        found: True when a live row already answered the declared search; the write is a
            replace of that row rather than a create.
        keyless: True when the type is ``KEYLESS`` — nothing to search, always assigned.
        key: The identity key the search and its lock were derived from — the type plus the
            constituting values, canonically serialised — or ``None`` when the type is keyless
            or a constituting value was a hole. Two resolutions with one key describe one
            source object, whether or not a row existed yet.
    """

    entity_id: uuid.UUID
    found: bool
    keyless: bool = False
    key: str | None = None


@dataclass
class WriteResult:
    """Result envelope for a single write operation.

    Attributes:
        success: True if the operation was applied (or would be, for dry_run).
        batch_id: The batch UUID string this operation participated in.
        entity_id: The UUID of the created or mutated entity (None on delete).
        object_summary: Populated for standard/verbose modes; None for minimal.
        warnings: Non-fatal advisory messages.
        errors: Populated only when success=False.
    """

    success: bool
    batch_id: str
    operation: str | None = None
    entity_id: uuid.UUID | None = None
    object_summary: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[ServiceError] = field(default_factory=list)


@dataclass
class ReadResult:
    """Result envelope for a single direct-read operation.

    Attributes:
        success: True if the object was found and returned.
        entity_id: UUID of the resolved entity.
        entity_type: Registered type slug of the resolved entity.
        object: The resolved model instance (or None on failure).
        schema_refs: Map of verb name to TAP schema ref string (e.g. "character:create").
        errors: Populated only when success=False.
    """

    success: bool
    entity_id: uuid.UUID | None = None
    entity_type: str | None = None
    object: Any | None = None
    schema_refs: dict[str, str] = field(default_factory=dict)
    errors: list[ServiceError] = field(default_factory=list)


@dataclass
class NodeTypeDescription:
    """Discovery description for a registered node type.

    Attributes:
        type_slug: The entity type slug.
        schemas: Map of verb ("create"/"patch"/"replace") to JSON schema dict.
        hotlinks: Declared hotlink definitions for this type.
        outbound_edge_types: Edge types this node type can create outbound.
        inbound_edge_types: Edge types this node type can receive inbound.
    """

    type_slug: str
    schemas: dict[str, dict[str, Any]]
    hotlinks: list[dict[str, Any]]
    outbound_edge_types: list[str]
    inbound_edge_types: list[str]


@dataclass
class EdgeTypeDescription:
    """Discovery description for a registered edge type.

    Attributes:
        edge_type: The edge type slug.
        allowed_sources: List of source node type slugs, or "wildcard", or "none".
        allowed_targets: List of target node type slugs, or "wildcard", or "none".
        property_schema: JSON schema for edge properties, or None if unregistered.
    """

    edge_type: str
    allowed_sources: list[str] | str
    allowed_targets: list[str] | str
    property_schema: dict[str, Any] | None = None


@dataclass
class ServiceCapabilities:
    """Top-level discovery description for the TAP service layer.

    Attributes:
        node_types: All registered node type slugs.
        edge_types: All registered edge type slugs.
        write_verbs: Supported write operation verb names.
        read_functions: Supported direct-read function names.
    """

    node_types: list[str]
    edge_types: list[str]
    write_verbs: list[str]
    read_functions: list[str]


@dataclass
class BatchWriteResult:
    """Result envelope for write_batch().

    Attributes:
        success: True if all operations succeeded (or passed dry-run validation).
        batch_id: The batch UUID string shared by all operations.
        dry_run: True if no changes were committed to the database.
        results: Per-operation WriteResult list, in submission order.
        errors: Batch-level errors not tied to a specific operation.
    """

    success: bool
    batch_id: str
    dry_run: bool
    results: list[WriteResult] = field(default_factory=list)
    errors: list[ServiceError] = field(default_factory=list)
