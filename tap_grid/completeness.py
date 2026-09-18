"""The completeness statement — six evidence attributes per listing surface, on the run's Batch.

``req-grid-reconcile-evidence`` (``tap_grid/specs/spec-grid-reconcile.md``): "complete" was
carrying six distinct claims, and finishing pagination establishes only the first two. A
run records them separately for every listing surface it touched — scope, enumeration,
source consistency, interval, admission, application — as a **completeness statement**
about a relation, a filter, a subject and an interval, never a boolean. Phase 4 slice 1
(Issue# 574 - tap): the statement alone, with authority off. Nothing here derives a
candidate, runs a falsifier, or retires anything; a later pass reads this record to
decide whether an absence from a surface licenses anything at all.

The home is the run's lifecycle ``Batch`` (ruled 2026-09-18): ``applied`` is literally the
write batches' own outcome, and ``Batch.metadata`` already exists, so the statement is a
described JSON structure (``tap_grid/schemas/completeness.schema.json``) under
``metadata["completeness"]`` and needs no migration.

Two fields are DERIVED here and refused if authored — ``applied`` from the referenced
batches' committed status, ``reconcilable`` from the rest — and three rules are enforced
in the recorder rather than trusted to the producer: consistency is never inferred (-2), a
count mismatch refuses reconciliation (-3), and a filtered surface without a passing
positive control is not complete (-4).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tap.jsonfiles import JsonFileError, load_schema, validate_json

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "completeness.schema.json"
_SCHEMA: dict[str, Any] = load_schema(SCHEMA_PATH)

METADATA_KEY = "completeness"
UNKNOWN = "unknown"
#: The attributes a producer asserts; each one that is not ``True`` needs a reason (-1).
ASSERTED_ATTRIBUTES: tuple[str, ...] = ("scope_authorized", "enumeration_complete", "source_consistent", "admitted")
#: The attributes only the recorder writes.
DERIVED_ATTRIBUTES: tuple[str, ...] = ("applied", "reconcilable")


class CompletenessError(ValueError):
    """A statement the recorder refuses. ``code`` is the machine-readable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def completeness_of(batch: Any) -> dict[str, Any] | None:
    """The statement recorded on ``batch``, or ``None`` when the run recorded none.

    Three states, never two: ``None`` is "nothing recorded", an empty ``surfaces`` list is
    "the run said it touched no listing surface".
    """
    metadata = getattr(batch, "metadata", None) or {}
    statement = metadata.get(METADATA_KEY)
    return dict(statement) if isinstance(statement, dict) else None


def record_completeness(batch: Any, surfaces: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Validate, derive and record a completeness statement on an OPEN batch.

    Every surface is checked against the schema and the three recorder rules; the
    derived attributes are computed here; the whole statement is refused before any
    write if one surface fails. Returns the statement as stored.

    Raises:
        CompletenessError: the batch is not open, a derived attribute was authored, a
            true ``source_consistent`` carries no promise, an attribute that is not true
            carries no reason, or the statement does not fit the schema.
    """
    from tap_grid.models import BatchStatus

    if batch.status != BatchStatus.OPEN:
        raise CompletenessError("batch_not_open", f"cannot record completeness on a batch in status {batch.status!r}")
    recorded = [_derive(dict(surface), position=i) for i, surface in enumerate(surfaces)]
    statement: dict[str, Any] = {"recorded_at": datetime.now(UTC).isoformat(), "surfaces": recorded}
    try:
        validate_json(statement, _SCHEMA, source=f"completeness on batch {batch.entity_id}")
    except JsonFileError as exc:
        raise CompletenessError("invalid_statement", f"{exc} (at {exc.location})") from exc
    metadata = dict(batch.metadata or {})
    metadata[METADATA_KEY] = statement
    batch.metadata = metadata
    batch.save(update_fields=["metadata"])
    return statement


def _derive(surface: dict[str, Any], *, position: int) -> dict[str, Any]:
    """Apply the recorder's rules to one authored surface and fill in the derived fields."""
    where = f"surfaces[{position}]"
    authored_derived = [k for k in DERIVED_ATTRIBUTES if k in surface]
    if authored_derived:
        raise CompletenessError("derived_not_authored", f"{where}: {authored_derived} are derived by the recorder")
    reasons: dict[str, str] = {str(k): str(v) for k, v in (surface.get("reasons") or {}).items()}

    # -2: consistency is never inferred. `true` needs the source's own promise, named.
    if surface.get("source_consistent") is True and not surface.get("source_promise"):
        raise CompletenessError(
            "consistency_unpromised",
            f"{where}: source_consistent may be true only with source_promise naming the source's snapshot guarantee",
        )

    # -4: a filtered surface is complete only with a passing positive control.
    if surface.get("filter") is not None:
        control = surface.get("filter_control")
        if control is None:
            surface["enumeration_complete"] = False
            reasons["enumeration_complete"] = (
                "filter_uncontrolled: the listing depended on a filter and no bogus-value control was run"
            )
        elif not control.get("value_changed"):
            surface["enumeration_complete"] = False
            reasons["enumeration_complete"] = (
                "filter_ignored: the bogus filter value did not change the result, so an empty answer proves nothing"
            )

    # -3: a count mismatch is a rejection control, never a proof of consistency.
    observed, reported = surface.get("count_observed"), surface.get("count_reported")
    mismatch = observed is not None and reported is not None and observed != reported
    if mismatch:
        reasons["count"] = f"count_mismatch: observed {observed}, reported {reported}"

    # -6 / -7: applied is the write batches' own outcome, not the producer's word.
    applied, why = _applied(list(surface.get("applied_batches") or []))
    if not applied:
        reasons["applied"] = why

    # -1: every attribute that is not true says why.
    for attribute in ASSERTED_ATTRIBUTES:
        if surface.get(attribute) is not True and attribute not in reasons:
            raise CompletenessError(
                "reason_required", f"{where}: {attribute}={surface.get(attribute)!r} without a reason"
            )

    surface["applied"] = applied
    surface["reconcilable"] = bool(
        surface.get("scope_authorized") is True
        and surface.get("enumeration_complete") is True
        and surface.get("admitted") is True
        and applied
        and not mismatch
    )
    surface["reasons"] = reasons
    return surface


def _applied(batch_ids: list[str]) -> tuple[bool, str]:
    """Every referenced batch committed (status closed); a failed, open or unknown one does not count."""
    from tap_grid.models import Batch, BatchStatus

    if not batch_ids:
        return False, "no_batch: no write batch carried this surface's observations"
    status_by_id = {
        str(entity_id): str(status)
        for entity_id, status in Batch.objects.filter(entity_id__in=batch_ids).values_list("entity_id", "status")  # type: ignore[misc]  # django-stubs sees the BaseModel manager
    }
    missing = [b for b in batch_ids if b not in status_by_id]
    if missing:
        return False, f"batch_missing: {missing}"
    uncommitted = {b: s for b, s in status_by_id.items() if s != BatchStatus.CLOSED}
    if uncommitted:
        return False, f"batch_not_committed: {uncommitted}"
    return True, ""
