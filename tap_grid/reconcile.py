"""The reconcile pass — verdicts applied through the ordinary verbs, behind a fence. Authority on.

``req-grid-reconcile-verb`` (``tap_grid/specs/spec-grid-reconcile.md``): reconciliation is one
service-layer verb, ``tap_grid.services.reconcile``, called once as a run's final phase. This
module is its body. The verb:

1. reads the run's candidate record (``tap_grid.candidates``) and, under the run's **budget**,
   runs the registered falsifiers over it (``tap_grid.falsifiers.falsify_candidates``);
2. with authority **off** — the default — probes nothing, records every candidate
   ``not_judged`` under ``authority: "off"``, and retires nothing (-2);
3. with authority **on**, applies each verdict through the existing verbs, inside the run's
   own transaction scope: ``DROPPED_FROM_OBSERVATION`` → the tombstone (a contained cascade)
   with the candidate's reason; ``RELOCATED(renamed)`` → the name update; ``RELOCATED
   (transferred)`` → the parent's containment edge ended, entity and children live; everything
   else → the run record only (``req-grid-reconcile-falsifier-3``);
4. fences every application (-4): a verdict is applied only if the target has NOT been
   re-observed since the candidate record was derived — no create/update ``BatchEvent`` on the
   entity from a committed batch outside this run's produced set after the record's
   ``recorded_at``. ``Entity.version`` is never consulted, because an unchanged re-observation
   may not bump it.

Withdrawal takes the same path (-7, -8): a ``scope_withdrawn`` candidate is applied through the
same authority, fence, cascade and audit; the candidate record already yields none when the
previous scope was unknown. Collectors never call any of this: the verb is the only caller of
the delete verbs on reconciliation's behalf, and a test walks every collector module to say so
(-1). Nothing here mints or resolves an identity — that is the gate's (``resolve_identity``).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from django.db import transaction

from tap_grid.candidates import candidates_of
from tap_grid.falsifiers import (
    DROPPED_FROM_OBSERVATION,
    JUDGED,
    RELOCATED,
    RELOCATED_RENAMED,
    RELOCATED_TRANSFERRED,
    falsify_candidates,
    record_not_judged,
    verdicts_of,
)
from tap_grid.service_types import WriteOperation

logger = logging.getLogger(__name__)

#: Every applied entry names one of these outcomes.
APPLIED = "applied"
REJECTED_STALE = "rejected_stale"
REFUSED = "refused"
NOT_APPLICABLE = "not_applicable"
APPLY_OUTCOMES: frozenset[str] = frozenset({APPLIED, REJECTED_STALE, REFUSED, NOT_APPLICABLE})

RECONCILE_METADATA_KEY = "reconcile"


class ReconcileError(ValueError):
    """A refusal, before any write: ``batch_not_open``, ``no_candidates`` or ``invalid_record``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def reconcile_run(
    batch: Any,
    *,
    authority: bool,
    budget: int | None,
    produced_batches: set[str] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The verb's body: judge under the budget, then apply under the fence. Returns the verdict
    record as stored, with its ``applied`` summary.

    Raises:
        ReconcileError: ``batch_not_open`` or ``no_candidates`` (before any write).
    """
    from tap_grid.models import BatchStatus

    if batch.status != BatchStatus.OPEN:
        raise ReconcileError("batch_not_open", f"cannot reconcile a batch in status {batch.status!r}")
    if candidates_of(batch) is None:
        raise ReconcileError("no_candidates", f"batch {batch.entity_id} carries no candidate record")
    if not authority:
        record = record_not_judged(batch, reason="collector reconcile authority is off")
        logger.info(
            "[26c5] reconcile on batch %s: authority off, %d candidate(s) recorded not judged, nothing retired",
            batch.entity_id,
            record["candidates"],
        )
        return record
    record = falsify_candidates(batch, extra=extra, budget=budget, authority="on")
    produced = set(produced_batches or ())
    produced.add(str(batch.entity_id))
    summary = _apply(batch, record, produced_batches=produced)
    record["applied"] = summary
    _store(batch, record)
    logger.info(
        "[b88a] reconcile on batch %s: %d applied, %d rejected stale, %d refused, %d not applicable",
        batch.entity_id,
        summary["applied"],
        summary["rejected_stale"],
        summary["refused"],
        summary["not_applicable"],
    )
    return record


# ---------------------------------------------------------------------------
# Applying verdicts
# ---------------------------------------------------------------------------


def _apply(batch: Any, record: dict[str, Any], *, produced_batches: set[str]) -> dict[str, Any]:
    from tap_grid.services import write_batch

    recorded_at = datetime.fromisoformat(record["recorded_at"])
    since = _derived_at(batch) or recorded_at
    counts = {APPLIED: 0, REJECTED_STALE: 0, REFUSED: 0, NOT_APPLICABLE: 0}
    generation = str(batch.entity_id)
    for entry in record["entries"]:
        entry["applied"] = None
        if entry["outcome"] != JUDGED:
            continue
        plan = entry["would"]["write"]
        if plan == "none":
            entry["applied"] = {"write": "none", "outcome": NOT_APPLICABLE, "error": None}
            counts[NOT_APPLICABLE] += 1
            continue
        entity_id = uuid.UUID(entry["entity_id"])
        if _observed_since(entity_id, since, produced_batches):
            entry["applied"] = {
                "write": plan,
                "outcome": REJECTED_STALE,
                "error": "the target was re-observed after the candidate record was derived; the verdict is stale",
            }
            counts[REJECTED_STALE] += 1
            logger.warning(
                "[2dd1] reconcile: verdict on %s rejected as stale (re-observed since %s)", entity_id, since.isoformat()
            )
            continue
        op = _operation_for(entry, batch, generation)
        if op is None:
            entry["applied"] = {
                "write": plan,
                "outcome": REFUSED,
                "error": "no operation could be formed for this verdict",
            }
            counts[REFUSED] += 1
            continue
        with transaction.atomic():
            result = (
                write_batch(  # TAP-AUTHZ-COV: reached only through tap_grid.services.reconcile, gated by grid.reconcile
                    [op], result_mode="minimal"
                )
            )
        outcome = result.results[0] if result.results else None
        if outcome is not None and outcome.success:
            entry["applied"] = {"write": plan, "outcome": APPLIED, "error": None}
            counts[APPLIED] += 1
        else:
            errors = (outcome.errors if outcome is not None else result.errors) or []
            entry["applied"] = {
                "write": plan,
                "outcome": REFUSED,
                "error": "; ".join(f"{e.code}: {e.message}" for e in errors)[:500] or "refused",
            }
            counts[REFUSED] += 1
            logger.warning("[9f78] reconcile: %s on %s refused: %s", plan, entity_id, entry["applied"]["error"])
    return {"authority": "on", **counts}


def _operation_for(entry: Mapping[str, Any], batch: Any, generation: str) -> WriteOperation | None:
    """The write the verdict licenses, as a pipeline operation; None when none can be formed."""
    entity_id = entry["entity_id"]
    audit = {
        RECONCILE_METADATA_KEY: {
            "run": str(batch.entity_id),
            "generation": generation,
            "verdict": entry["verdict"],
            "kind": entry.get("kind"),
            "surface": entry["surface"],
            "candidate_reason": entry["candidate_reason"],
        }
    }
    if entry["verdict"] == DROPPED_FROM_OBSERVATION:
        return WriteOperation(
            verb="delete_node", target=entity_id, reason=entry["candidate_reason"], metadata=audit, cascade="contained"
        )
    if entry["verdict"] == RELOCATED and entry.get("kind") == RELOCATED_RENAMED:
        name = ((entry.get("probe") or {}).get("name")) or None
        if not name:
            return None
        return WriteOperation(verb="patch_node", target=entity_id, payload={"name": name})
    if entry["verdict"] == RELOCATED and entry.get("kind") == RELOCATED_TRANSFERRED:
        edge_id = _ownership_edge(entry)
        if edge_id is None:
            return None
        return WriteOperation(verb="delete_edge", target=str(edge_id), reason=entry["candidate_reason"], metadata=audit)
    return None


def _ownership_edge(entry: Mapping[str, Any]) -> uuid.UUID | None:
    """The live containment edge from the candidate's parent on this surface to the entity."""
    from tap_grid.models import Edge

    parent, edge_type = entry.get("parent"), entry.get("edge_type")
    if not parent or not edge_type:
        return None
    row = (
        Edge.objects.filter(
            from_entity_id=uuid.UUID(parent), to_entity_id=uuid.UUID(entry["entity_id"]), edge_type=edge_type
        )
        .values_list("entity_id", flat=True)
        .first()
    )
    return uuid.UUID(str(row)) if row else None


# ---------------------------------------------------------------------------
# The fence
# ---------------------------------------------------------------------------


def _derived_at(batch: Any) -> datetime | None:
    record = candidates_of(batch)
    if record is None:
        return None
    try:
        return datetime.fromisoformat(record["recorded_at"])
    except KeyError, ValueError, TypeError:
        return None


def _observed_since(entity_id: uuid.UUID, since: datetime, produced_batches: set[str]) -> bool:
    """Has the entity been re-observed — a create or update event from a COMMITTED batch that is
    not one of this run's — since the candidate record was derived? ``Entity.version`` is not
    consulted: an unchanged re-observation deliberately may not bump it (-4)."""
    from tap_grid.models import BatchEvent, BatchEventType, BatchStatus

    return (
        BatchEvent.objects.filter(
            entity_id=entity_id,
            event_type__in=[BatchEventType.CREATE, BatchEventType.UPDATE],
            timestamp__gt=since,
            batch__status=BatchStatus.CLOSED,
        )
        .exclude(batch__entity_id__in=[uuid.UUID(b) for b in produced_batches])
        .exists()
    )


def _store(batch: Any, record: dict[str, Any]) -> None:
    from tap_grid.falsifiers import METADATA_KEY
    from tap_grid.models import Batch

    with transaction.atomic():
        locked = cast(Batch, Batch.objects.select_for_update().get(pk=batch.pk))  # django-stubs: manager typing
        metadata = dict(locked.metadata or {})
        metadata[METADATA_KEY] = record
        locked.metadata = metadata
        locked.save(update_fields=["metadata"])
    batch.metadata = metadata


__all__ = [
    "APPLIED",
    "APPLY_OUTCOMES",
    "NOT_APPLICABLE",
    "RECONCILE_METADATA_KEY",
    "REFUSED",
    "REJECTED_STALE",
    "ReconcileError",
    "reconcile_run",
    "verdicts_of",
]
