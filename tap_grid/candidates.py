"""Retirement candidates — fan-out from the parent, minus observed, minus out of scope.

``req-grid-reconcile-candidates`` (``tap_grid/specs/spec-grid-reconcile.md``): a candidate
for retirement is derived from the grid's own topology, not from a per-node observation
stamp. For a parent P and a containment relation R:

    children(P, R) in the grid  −  observed(this run, P, R)  −  outside_scope(this run)

Phase 4 slice 2 (Issue# 596 - tap): derive and record, authority off. Nothing here runs a
falsifier or retires anything; the recorded structure (``tap_grid/schemas/candidates.schema.json``)
is what a later pass would hand to a falsifier (``req-grid-reconcile-falsifier``).

The inputs are all already on the record:

- **children(P, R)** is the live far end of P's edges of type R, where R is one of the
  edge types P's model declares in ``CONTAINMENT_EDGES`` (``req-grid-service-delete-cascade``)
  — the one containment declaration, read here through ``tap.edge_declarations``. A
  relation the model does not declare as containment is a reference and yields nothing
  (-5). The completeness surface names R in its ``edge_type`` field; the spec's
  "collector's descent table" has no other home yet.
- **observed(this run)** is every entity with a create/update ``BatchEvent`` on one of the
  run's produced write batches that COMMITTED. The service write pipeline records that
  event for every node it writes, unchanged re-observations included, so the set is the
  run's own record rather than a stamp on the node (-1). A failed or open batch is not
  evidence of anything.
- **the prerequisite is per parent** (-2): P is live, P was itself observed this run, and
  the surface listing P's R-children is ``reconcilable`` by the completeness statement's
  own derivation (``tap_grid.completeness``). What happened to the listing of P's siblings
  is not consulted. A retired P is skipped outright: its children are cascade's business (-3).
- **withdrawal is not absence** (-4): a surface the previous run's statement held in scope
  (``scope_authorized: true``) that this run's statement does not is a narrowed scope. Its
  candidates are the children the PREVIOUS run observed, with reason ``scope_withdrawn``;
  a child that no run observed under that scope is nothing. Without a previous run to
  compare, withdrawal is NOT OBSERVABLE and the record says so (``previous: null``) —
  three states, never two.

Perspectives are Future: nothing here scopes by dimension.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tap.edge_declarations import edge_types_in
from tap.jsonfiles import JsonFileError, load_schema, validate_json
from tap_grid.completeness import completeness_of

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "candidates.schema.json"
_SCHEMA: dict[str, Any] = load_schema(SCHEMA_PATH)

METADATA_KEY = "candidates"
#: The completeness-surface field naming the grid edge type its relation maps to.
SURFACE_EDGE_TYPE = "edge_type"
#: The reasons a candidate would carry — a subset of ``DELETE_REASONS`` (asserted in tests).
ABSENT = "dropped_from_observation"
WITHDRAWN = "scope_withdrawn"
#: A fan-out larger than this is recorded as ``fan_out_exceeds_cap`` rather than
#: materialised into the batch's metadata; a later pass with a store of its own can raise it.
MAX_CANDIDATES_PER_SURFACE = 5000
#: The BatchEvent types that mean "this run wrote this node" — deletes are not observations.
_OBSERVATION_EVENTS: tuple[str, ...] = ("create", "update")


class CandidatesError(ValueError):
    """A derivation the recorder refuses. ``code`` is the machine-readable reason."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def candidates_of(batch: Any) -> dict[str, Any] | None:
    """The candidate record on ``batch``, or ``None`` when none was recorded."""
    metadata = getattr(batch, "metadata", None) or {}
    record = metadata.get(METADATA_KEY)
    return dict(record) if isinstance(record, dict) else None


def observed_by(produced_batches: Collection[str]) -> tuple[set[uuid.UUID], list[str]]:
    """The entities a run's committed write batches touched, and which batches counted.

    Only a CLOSED batch is evidence: a failed batch rolled back, an open one may still,
    and a missing one never existed. Returns ``(entity_ids, closed_batch_ids)``.
    """
    from tap_grid.models import Batch, BatchEvent, BatchStatus

    wanted = sorted({str(b) for b in produced_batches})
    if not wanted:
        return set(), []
    closed = sorted(
        str(entity_id)
        for entity_id in Batch.objects.filter(entity_id__in=wanted, status=BatchStatus.CLOSED).values_list(
            "entity_id", flat=True
        )
    )
    if not closed:
        return set(), []
    touched = set(
        BatchEvent.objects.filter(batch__entity_id__in=closed, event_type__in=_OBSERVATION_EVENTS).values_list(
            "entity_id", flat=True
        )
    )
    return touched, closed


def derive_candidates(
    batch: Any,
    *,
    produced_batches: Collection[str],
    previous_batch: Any = None,
    previous_produced_batches: Collection[str] = (),
) -> dict[str, Any]:
    """Derive the candidate record for a run from its completeness statement — no write.

    TAP-IMPLEMENTS: req-grid-reconcile-candidates@f1fe8cd87198/d29defa95de3 (derivation) — the one
    place the candidate set is computed: fan-out through the declared containment edge type,
    minus the run's committed observations, per-parent prerequisite, withdrawal from the
    previous statement.

    ``produced_batches`` are the write batches this run produced (the run task passes the
    collector's own). ``previous_batch`` is the previous run's lifecycle batch, whose
    statement is the previous scope; ``previous_produced_batches`` are that run's write
    batches, the evidence that a withdrawn child was observed. Omit both and withdrawal is
    recorded as not observable.

    Raises:
        CandidatesError: ``batch`` carries no completeness statement (``no_statement``).
    """
    statement = completeness_of(batch)
    if statement is None:
        raise CandidatesError("no_statement", f"batch {batch.entity_id} recorded no completeness statement")
    observed, observed_batches = observed_by(produced_batches)
    surfaces: list[dict[str, Any]] = [_derive_surface(s, observed) for s in statement.get("surfaces", [])]

    previous: dict[str, Any] | None = None
    if previous_batch is not None:
        previous_statement = completeness_of(previous_batch)
        previous = {
            "batch": str(previous_batch.entity_id),
            "compared": previous_statement is not None,
            "reason": None if previous_statement is not None else "no_statement: the previous batch recorded none",
            "observed_batches": [],
        }
        if previous_statement is not None:
            previously_observed, previous["observed_batches"] = observed_by(previous_produced_batches)
            in_scope_now = _scope_of(statement)
            for prior in previous_statement.get("surfaces", []):
                if prior.get("scope_authorized") is True and _key(prior) not in in_scope_now:
                    surfaces.append(_withdraw_surface(prior, previously_observed))

    return {
        "recorded_at": datetime.now(UTC).isoformat(),
        "authority": "off",
        "observed_batches": observed_batches,
        "previous": previous,
        "surfaces": surfaces,
    }


def record_candidates(
    batch: Any,
    *,
    produced_batches: Collection[str],
    previous_batch: Any = None,
    previous_produced_batches: Collection[str] = (),
) -> dict[str, Any]:
    """Derive and record the candidate record on an OPEN batch, beside its completeness statement.

    Refused before any write when the batch is not open, carries no statement, or the
    derived record does not fit its schema. Retires nothing. Returns the record as stored.

    Raises:
        CandidatesError: ``batch_not_open``, ``no_statement`` or ``invalid_record``.
    """
    from tap_grid.models import BatchStatus

    if batch.status != BatchStatus.OPEN:
        raise CandidatesError("batch_not_open", f"cannot record candidates on a batch in status {batch.status!r}")
    record = derive_candidates(
        batch,
        produced_batches=produced_batches,
        previous_batch=previous_batch,
        previous_produced_batches=previous_produced_batches,
    )
    try:
        validate_json(record, _SCHEMA, source=f"candidates on batch {batch.entity_id}")
    except JsonFileError as exc:
        raise CandidatesError("invalid_record", f"{exc} (at {exc.location})") from exc
    metadata = dict(batch.metadata or {})
    metadata[METADATA_KEY] = record
    batch.metadata = metadata
    batch.save(update_fields=["metadata"])
    derived = sum(len(s["candidates"]) for s in record["surfaces"])
    logger.info(
        "[0bd2] candidates recorded on batch %s: %d surface(s), %d candidate(s), authority off",
        batch.entity_id,
        len(record["surfaces"]),
        derived,
    )
    return record


# ---------------------------------------------------------------------------
# Per-surface derivation
# ---------------------------------------------------------------------------


def _key(surface: Mapping[str, Any]) -> tuple[str, str]:
    return str(surface.get("subject")), str(surface.get("relation"))


def _scope_of(statement: Mapping[str, Any]) -> set[tuple[str, str]]:
    """The (subject, relation) pairs a statement holds in scope."""
    return {_key(s) for s in statement.get("surfaces", []) if s.get("scope_authorized") is True}


def _entry(surface: Mapping[str, Any], **fields: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "relation": surface.get("relation"),
        "subject": surface.get("subject"),
        "edge_type": surface.get(SURFACE_EDGE_TYPE),
        "parent": None,
        "outcome": "skipped",
        "reason": None,
        "children": None,
        "observed": None,
        "candidates": [],
    }
    entry.update(fields)
    return entry


def _skip(surface: Mapping[str, Any], reason: str, **fields: Any) -> dict[str, Any]:
    return _entry(surface, outcome="skipped", reason=reason, **fields)


def _resolve_parent(surface: Mapping[str, Any]) -> tuple[uuid.UUID, str] | dict[str, Any]:
    """The live parent (id, edge type) a surface fans out from, or the skip entry explaining why not.

    The checks that do not depend on this run's observations: the subject is a grid id, the
    entity exists and is live, its type is registered, and the surface's edge type is one the
    type declares as containment. Order matters for the reason recorded: a retired parent is
    reported as retired before anything about its relation is asked.
    """
    from tap_grid.models import Entity
    from tap_grid.registry import get_model_class

    try:
        parent_id = uuid.UUID(str(surface.get("subject")))
    # PEP 758 (Python 3.14): an except clause may list exception types without
    # parentheses; black removes them if written. Flagged as a SyntaxError by three
    # reviewers now (Grok on PR# 600 - tap) — it parses and runs on the repo's floor.
    except ValueError, TypeError:
        return _skip(surface, "subject_unresolved: the subject is not a grid entity id")
    row = Entity.objects.filter(pk=parent_id).values("entity_type", "deleted_at").first()
    if row is None:
        return _skip(surface, "parent_unknown: no entity has the subject's id", parent=str(parent_id))
    if row["deleted_at"] is not None:
        return _skip(
            surface,
            "parent_retired: the parent is tombstoned; its children are cascade's business",
            parent=str(parent_id),
        )
    try:
        model_cls = get_model_class(row["entity_type"])
    except KeyError:
        return _skip(surface, f"parent_type_unknown: {row['entity_type']!r} is not registered", parent=str(parent_id))
    edge_type = surface.get(SURFACE_EDGE_TYPE)
    if not edge_type:
        return _skip(surface, "relation_unmapped: the surface names no grid edge type", parent=str(parent_id))
    containment = edge_types_in("CONTAINMENT_EDGES", getattr(model_cls, "CONTAINMENT_EDGES", ()))
    if edge_type not in containment:
        return _skip(
            surface,
            f"relation_not_containment: {edge_type!r} is not in {row['entity_type']}.CONTAINMENT_EDGES; "
            "a reference relation never yields a candidate",
            parent=str(parent_id),
        )
    return parent_id, str(edge_type)


def _children(parent_id: uuid.UUID, edge_type: str) -> dict[uuid.UUID, str] | None:
    """Live children of the parent through one containment edge type, ``{id: entity_type}``.

    Read from the topology only — the edge table and the spine — never a typed row or a
    per-node stamp. ``None`` when the fan-out exceeds the cap.
    """
    from tap_grid.models import Edge

    query = Edge.objects.filter(from_entity_id=parent_id, edge_type=edge_type, to_entity__deleted_at__isnull=True)
    if query.count() > MAX_CANDIDATES_PER_SURFACE:
        return None
    return {
        child_id: str(child_type)
        for child_id, child_type in query.values_list("to_entity_id", "to_entity__entity_type").distinct()  # type: ignore[misc]  # django-stubs sees the BaseModel manager
    }


def _derive_surface(surface: Mapping[str, Any], observed: set[uuid.UUID]) -> dict[str, Any]:
    """One surface of THIS run's statement: the per-parent prerequisite, then fan-out minus observed."""
    resolved = _resolve_parent(surface)
    if isinstance(resolved, dict):
        return resolved
    parent_id, edge_type = resolved
    parent = str(parent_id)
    if parent_id not in observed:
        return _skip(surface, "parent_not_observed: no committed batch of this run touched the parent", parent=parent)
    if surface.get("reconcilable") is not True:
        reasons = "; ".join(f"{k}: {v}" for k, v in sorted((surface.get("reasons") or {}).items()))
        return _skip(surface, f"surface_not_reconcilable: {reasons or 'the statement says so'}", parent=parent)
    children = _children(parent_id, edge_type)
    if children is None:
        return _skip(surface, f"fan_out_exceeds_cap: more than {MAX_CANDIDATES_PER_SURFACE} children", parent=parent)
    seen = {c for c in children if c in observed}
    return _entry(
        surface,
        parent=parent,
        outcome="derived",
        reason=None,
        children=len(children),
        observed=len(seen),
        candidates=[
            {"entity_id": str(c), "entity_type": t, "reason": ABSENT}
            for c, t in sorted(children.items(), key=lambda item: item[0])
            if c not in seen
        ],
    )


def _withdraw_surface(prior: Mapping[str, Any], previously_observed: set[uuid.UUID]) -> dict[str, Any]:
    """One surface of the PREVIOUS statement that this run's scope no longer holds.

    The evidence is the two scope statements compared, so neither this run's observations
    nor the surface's enumeration are consulted; what IS required is that the previous run
    actually observed the child — a child nobody observed under the withdrawn scope is
    nothing to end.
    """
    resolved = _resolve_parent(prior)
    if isinstance(resolved, dict):
        return resolved
    parent_id, edge_type = resolved
    parent = str(parent_id)
    children = _children(parent_id, edge_type)
    if children is None:
        return _skip(prior, f"fan_out_exceeds_cap: more than {MAX_CANDIDATES_PER_SURFACE} children", parent=parent)
    withdrawn = {c: t for c, t in children.items() if c in previously_observed}
    return _entry(
        prior,
        parent=parent,
        outcome="withdrawn",
        reason="scope_withdrawn: the previous run held this surface in scope and this run does not",
        children=len(children),
        observed=len(withdrawn),
        candidates=[
            {"entity_id": str(c), "entity_type": t, "reason": WITHDRAWN}
            for c, t in sorted(withdrawn.items(), key=lambda item: item[0])
        ],
    )
