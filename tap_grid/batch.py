"""Batch service layer — batch lifecycle and event recording.

This module provides the API for:
1. Creating and managing batches
2. Recording batch events
3. Querying batch history

Note: batch_context() has been removed. Batch lifecycle is now managed by the
service layer, which generates a batch_id and threads it via CallerContext.
See req-grid-service-batch-infra and req-grid-service-batch-signals.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django.utils import timezone

from tap_grid.context import get_batch_id
from tap_grid.history import get_history_user
from tap_grid.services import create_entity

if TYPE_CHECKING:
    from collections.abc import Iterable

    # Actor is generic over AUTH_USER_MODEL — not the concrete tap_auth.User
    # (req-tap-auth-user-model-5).
    from django.contrib.auth.models import AbstractUser

    from tap_grid.models import Batch, BatchEvent, Entity


# `source` stamped on a Batch the service layer minted for a write that supplied
# none of its own (see `tap_grid.services._impl._ensure_batch`). It names the
# service layer as the producer, which is the true answer — these batches have no
# plugin, collector or importer behind them. A consumer asking "which batches did
# plugin X produce" can therefore tell "produced by the service layer itself" from
# "producer not recorded" (`source=""`, which after this only pre-existing rows
# carry). See spec-grid-service-batch.md req-grid-service-batch-metadata-7.
AUTO_BATCH_SOURCE = "tap_grid.services.write_batch"

AUTO_BATCH_DESCRIPTION = "Auto-created by the service layer: this write supplied no batch of its own."


def _clamp_batch_name(name: str) -> str:
    """Clamp a batch name to what BOTH ends of the spine can hold.

    A batch name is written twice — onto `Batch.name` and onto the backing
    `Entity.name` — so it must fit the SHORTER of the two columns or one end
    rejects a value the other accepted. The limit is read from the model fields
    rather than hardcoded, so widening a column cannot leave a stale constant
    behind.

    Clamping here, at the one place that sets both ends, is deliberate: a caller
    composing a name from data it does not control (a schedule name, a plugin
    slug, a bundle path) cannot know the budget left after the prefix. Before
    this, an overlong composite raised inside the caller's transaction — for the
    scheduler that rolled back the slot claim too, so a schedule with a
    maximum-length name failed identically on every tick and never fired at all.
    A truncated display name is a far smaller loss than an unfireable schedule.
    """
    from tap_grid.models import Batch, Entity, clamp_to_fields

    return clamp_to_fields(name, (Batch, "name"), (Entity, "name"))


def create_batch(
    source: str = "",
    actor: AbstractUser | None = None,
    name: str = "",
    description: str = "",
    description_json: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    entity_id: uuid.UUID | str | None = None,
) -> Batch:
    """Create a new batch.

    Args:
        source: Source identifier (e.g., 'scanner:aws').
        actor: User initiating the batch (falls back to context user).
        name: Human-readable batch name; also used as the backing Entity name.
        description: Long-form description of the batch purpose.
        description_json: Structured description payload with format and data keys.
        metadata: Additional context for the batch.
        entity_id: Optional pre-specified UUID for the backing Entity (e.g. GRIFT import).
            When omitted, a new UUIDv7 is generated.

    Returns:
        The created Batch instance.
    """
    from tap_grid.models import Batch, Entity

    actor = actor or get_history_user()

    resolved_name = _clamp_batch_name(name or f"Batch {datetime.now().isoformat()}")

    # Create backing Entity for the Batch, optionally with a pre-specified ID.
    if entity_id is not None:
        resolved_id = uuid.UUID(str(entity_id)) if not isinstance(entity_id, uuid.UUID) else entity_id
        entity = Entity.objects.create(
            id=resolved_id,
            entity_type="batch",
            name=resolved_name,
        )
    else:
        entity = create_entity(
            entity_type="batch",
            name=resolved_name,
        )

    return Batch.objects.create(
        entity=entity,
        source=source,
        actor=actor,
        name=resolved_name,
        description=description,
        description_json=description_json,
        metadata=metadata or {},
    )


def close_batch(batch: Batch) -> Batch:
    """Close a batch successfully.

    Args:
        batch: The batch to close.

    Returns:
        The updated batch.

    Raises:
        ValueError: If batch is not open.
    """
    from tap_grid.models import BatchStatus

    if batch.status != BatchStatus.OPEN:
        raise ValueError(f"Cannot close batch in status '{batch.status}'")

    batch.status = BatchStatus.CLOSED
    batch.closed_at = timezone.now()
    batch.save(update_fields=["status", "closed_at"])
    return batch


def fail_batch(batch: Batch, error_message: str = "") -> Batch:
    """Mark a batch as failed.

    Args:
        batch: The batch to fail.
        error_message: Description of the failure.

    Returns:
        The updated batch.

    Raises:
        ValueError: If batch is not open.
    """
    from tap_grid.models import BatchStatus

    if batch.status != BatchStatus.OPEN:
        raise ValueError(f"Cannot fail batch in status '{batch.status}'")

    batch.status = BatchStatus.FAILED
    batch.closed_at = timezone.now()
    batch.error_message = error_message
    batch.save(update_fields=["status", "closed_at", "error_message"])
    return batch


def record_batch_event(
    entity: Entity,
    event_type: str,
    model_name: str = "",
    actor: AbstractUser | None = None,
    metadata: dict[str, Any] | None = None,
    batch_id: str | None = None,
) -> BatchEvent | None:
    """Record a change event in the current batch.

    Args:
        entity: The Entity that was affected.
        event_type: Type of change (create, update, delete, link, unlink).
        model_name: ORM model class name if applicable.
        actor: User making the change (falls back to context user).
        metadata: Additional context.
        batch_id: Explicit batch ID (falls back to context batch_id).

    Returns:
        The created BatchEvent, or None if no batch context.
    """
    from tap_grid.models import Batch, BatchEvent

    # Resolve batch_id: explicit param > context > None
    resolved_batch_id = batch_id or get_batch_id()
    if not resolved_batch_id:
        return None

    try:
        batch = Batch.objects.get(entity_id=resolved_batch_id)
    except Batch.DoesNotExist:
        return None

    actor = actor or get_history_user()

    return BatchEvent.objects.create(
        batch=batch,
        event_type=event_type,
        entity_id=entity.id,
        entity_type=entity.entity_type,
        model_name=model_name,
        actor=actor,
        metadata=metadata or {},
    )


def get_batch(batch_id: str) -> Batch | None:
    """Retrieve a batch by its entity ID.

    Args:
        batch_id: The entity ID of the batch (string UUID).

    Returns:
        The Batch instance, or None if not found.
    """
    from tap_grid.models import Batch

    try:
        return Batch.objects.select_related("entity", "actor").get(entity_id=batch_id)
    except Batch.DoesNotExist:
        return None


def get_batch_events(batch_id: str) -> list[BatchEvent]:
    """Get all events for a batch.

    Args:
        batch_id: The entity ID of the batch (string UUID).

    Returns:
        List of BatchEvent instances, or empty list if batch not found.
    """
    from tap_grid.models import Batch

    try:
        batch = Batch.objects.get(entity_id=batch_id)
        return list(batch.events.all())
    except Batch.DoesNotExist:
        return []


def get_entity_batches(entity_id: uuid.UUID) -> list[Batch]:
    """Get all batches that affected a specific entity.

    Args:
        entity_id: The UUID of the entity.

    Returns:
        List of Batch instances that have events for this entity.
    """
    from tap_grid.models import Batch, BatchEvent

    batch_ids = BatchEvent.objects.filter(entity_id=entity_id).values_list("batch_id", flat=True).distinct()

    return list(Batch.objects.filter(id__in=batch_ids).order_by("-started_at"))


def batch_counts(batch_id: uuid.UUID | str, *, batch: Batch | None = None) -> dict[str, int]:
    """How many nodes/edges a batch added, deleted (tombstoned), and purged.

    ``batch_id`` is stamped on the typed rows (``n.data.batch_id``), not the
    Entity spine, so the node questions go through Gryphon; the edge count is a
    direct ``Edge`` scan; purges survive only in the batch's recorded removal
    manifest (hard-deleted rows are gone). These scans are not free — callers
    rendering many batches in a list should prefer ``batch_summary(...,
    with_counts=False)``.
    """
    from collections import Counter

    from tap_grid.gryphon.executor import execute_gryphon_raw
    from tap_grid.models import Batch, Edge

    bid = str(batch_id)

    def _added(*, deleted: bool) -> list[dict[str, Any]]:
        clause = "IS NOT NULL" if deleted else "IS NULL"
        envelope = execute_gryphon_raw(
            f"MATCH (n) WHERE n.data.batch_id = $bid AND n.deleted_at {clause} RETURN n",
            {"bid": bid},
            layer="extended",
        )
        # The batch node isn't "added by" itself.
        return [n for n in (envelope.get("nodes") or []) if n.get("entity_type") != "batch"]

    added = _added(deleted=False)
    tombstoned = _added(deleted=True)

    if batch is None:
        batch = Batch.objects.filter(entity_id=bid).first()
    removals = (getattr(batch, "metadata", None) or {}).get("removals")
    purges = [r for r in (removals or []) if r.get("action") == "purge"]

    return {
        "nodes": len(added),
        "edges": Edge.objects.filter(batch_id=bid).count(),
        "deletes": len(tombstoned),
        "purges": len(purges),
        "node_types": len(Counter(n.get("entity_type") for n in added)),
    }


def batch_summary(batch_id: uuid.UUID | str, *, with_counts: bool = True) -> dict[str, Any] | None:
    """Display-oriented summary of one batch — the single source of truth for
    "what is this batch" across panels, inline references, the API, and tooling.

    Returns ``None`` when ``batch_id`` does not resolve to a batch. With
    ``with_counts`` (default), also reports node/edge/delete/purge counts via
    :func:`batch_counts` (extra DB work — pass ``with_counts=False`` for list
    rendering where only the metadata + a link is wanted).
    """
    from tap_grid.models import Batch

    batch = Batch.objects.filter(entity_id=str(batch_id)).select_related("actor").first()
    if batch is None:
        return None

    summary: dict[str, Any] = {
        "entity_id": str(batch.entity_id),
        "name": batch.name or "(unnamed batch)",
        "source": batch.source,
        "status": batch.status,
        "started_at": batch.started_at,
        "closed_at": batch.closed_at,
        "description": batch.description,
        "error_message": batch.error_message,
    }
    if with_counts:
        summary["counts"] = batch_counts(str(batch.entity_id), batch=batch)
    return summary


def produced_batches_by_producer(
    producer_entity_ids: Iterable[uuid.UUID | str],
) -> dict[str, dict[str, list[str]]]:
    """Bulk PRODUCED_BATCH targets, grouped by producer then disposition.

    One ``Edge`` scan for all producers, so a page listing many runs avoids an
    N+1. Returns ``{producer_id: {"imported": [...], "skipped": [...]}}`` with
    an entry for every requested producer (empty lists when it produced
    nothing). The ``disposition`` edge property (``req-grid-edge-produced-batch``)
    partitions the targets. Order is newest-edge-first (the ``Edge`` model's
    default ordering), so a "most recent batch produced" reader can take ``[0]``.
    """
    from tap_grid.models import Edge

    ids = [str(p) for p in producer_entity_ids]
    grouped: dict[str, dict[str, list[str]]] = {pid: {"imported": [], "skipped": []} for pid in ids}
    if not ids:
        return grouped
    rows = Edge.objects.filter(
        from_entity_id__in=ids,
        edge_type="PRODUCED_BATCH",
    ).values_list("from_entity_id", "to_entity_id", "properties")
    for from_id, to_id, properties in rows:
        disposition = (properties or {}).get("disposition")
        bucket = grouped.get(str(from_id))
        if bucket is not None and disposition in bucket:
            bucket[disposition].append(str(to_id))
    return grouped


def produced_batches(producer_entity_id: uuid.UUID | str) -> dict[str, list[str]]:
    """PRODUCED_BATCH targets for one producer, grouped by disposition.

    ``{"imported": [...], "skipped": [...]}`` — the canonical, traversable
    replacement for the embedded ``CollectionJob.grift_batches`` field. A
    producer that produced nothing returns empty lists. Newest-edge-first.
    """
    return produced_batches_by_producer([producer_entity_id])[str(producer_entity_id)]
