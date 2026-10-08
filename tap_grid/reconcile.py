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
   may not bump it. A transfer is fenced on the edge it ends as well: a containment edge
   re-created since the record was derived carries a ``link`` event of its own and no update
   on the child, and it rejects the verdict too.
5. refuses a contradiction (Issue# 656 - tap): a candidate the record marked ``contradicted`` —
   a node under it observed live by this run — is never probed or applied, whatever the
   authority; and a tombstone whose closure holds a node observed since the record was derived,
   by any batch that has not failed, is ``contradicted`` at apply, the closure locked first,
   never cascaded;
6. licenses each delete narrowly: ``grid.reconcile`` stands in for ``grid.delete`` only inside
   ``reconcile_write_scope``, opened around each write for that verdict's target alone, so a
   defect here cannot widen a verdict past the row it judged.

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
    CONTRADICTED,
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
from tap_grid.write_guard import below_pipeline_write, reconcile_write_scope

logger = logging.getLogger(__name__)

#: Every applied entry names one of these outcomes.
APPLIED = "applied"
REJECTED_STALE = "rejected_stale"
REFUSED = "refused"
NOT_APPLICABLE = "not_applicable"
#: ``CONTRADICTED`` is shared with the dispatch (``tap_grid.falsifiers``): at apply it means a node
#: under the tombstone's target was observed by a committed batch since the record was derived.
APPLY_OUTCOMES: frozenset[str] = frozenset({APPLIED, REJECTED_STALE, REFUSED, NOT_APPLICABLE, CONTRADICTED})

RECONCILE_METADATA_KEY = "reconcile"


class ReconcileError(ValueError):
    """A refusal, before any write: ``batch_not_open``, ``no_candidates``, ``invalid_config`` or
    ``invalid_record``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


RUN_CONFIG_KEY = "reconcile_config"


def run_config(*, authority: bool, budget: int | None, collector: str) -> dict[str, Any]:
    """The run's reconcile configuration as the lifecycle batch carries it. Built once by the run
    opener (passed to ``create_batch`` as metadata, so no row is written outside the service);
    refused when the budget is not a non-negative integer — a bad budget never widens a pass."""
    if authority is not True and authority is not False:
        raise ReconcileError("invalid_config", f"authority must be a bool, got {authority!r}")
    if budget is not None and (isinstance(budget, bool) or not isinstance(budget, int) or budget < 0):
        raise ReconcileError("invalid_config", f"budget must be a non-negative integer or None, got {budget!r}")
    return {"authority": authority, "budget": budget, "collector": str(collector)}


def run_config_of(batch: Any) -> dict[str, Any]:
    """The run's configuration as the verb reads it. Fail closed on every axis: absent or
    malformed → authority OFF; authority is on only when it is literally ``true``; a budget that
    is not a non-negative integer probes NOTHING (0), never everything (None)."""
    config = (batch.metadata or {}).get(RUN_CONFIG_KEY)
    if not isinstance(config, Mapping):
        return {"authority": False, "budget": None, "collector": None}
    authority = config.get("authority") is True
    raw = config.get("budget")
    if raw is None:
        budget: int | None = None
    elif isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        budget = raw
    else:
        logger.warning(
            "[7669] reconcile config on batch %s carries budget %r: not a non-negative integer, probing nothing",
            batch.entity_id,
            raw,
        )
        budget = 0
    return {"authority": authority, "budget": budget, "collector": config.get("collector")}


def reconcile_run(batch: Any, *, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The verb's body: judge under the budget, then apply under the fence — one transaction.

    Authority and budget come from the run's configuration, carried into the lifecycle batch when the
    run opener created it (``run_config`` → ``create_batch(metadata=...)``); the batches whose observations are this run's own come from the candidate
    record's ``observed_batches`` — derived once, never supplied by the caller. With authority
    on, judging, every write and the record are one transaction: a failure rolls back every
    tombstone with it, so a run can never half-finish with its audit lost.

    Raises:
        ReconcileError: ``batch_not_open`` or ``no_candidates`` (before any write).
    """
    from tap_grid.models import BatchStatus

    if batch.status != BatchStatus.OPEN:
        raise ReconcileError("batch_not_open", f"cannot reconcile a batch in status {batch.status!r}")
    candidate_record = candidates_of(batch)
    if candidate_record is None:
        raise ReconcileError("no_candidates", f"batch {batch.entity_id} carries no candidate record")
    config = run_config_of(batch)
    produced = {str(b) for b in candidate_record.get("observed_batches", [])}
    produced.add(str(batch.entity_id))
    if not config["authority"]:
        record = record_not_judged(batch, reason="collector reconcile authority is off")
        record[EDGE_AUTHORITY_KEY] = _edge_authority_off(produced)
        _store(batch, record)
        logger.info(
            "[26c5] reconcile on batch %s: authority off, %d candidate(s) recorded not judged, nothing retired",
            batch.entity_id,
            record["candidates"],
        )
        return record
    with transaction.atomic():
        record = falsify_candidates(batch, extra=extra, budget=config["budget"], authority="on")
        summary = _apply(batch, record, produced_batches=produced)
        record["applied"] = summary
        # Edge authority after the node verdicts: an edge a tombstone already ended is then `gone`.
        record[EDGE_AUTHORITY_KEY] = _apply_edge_authority(batch, produced_batches=produced)
        _store(batch, record)
    edge_counts = record[EDGE_AUTHORITY_KEY]["counts"]
    logger.info(
        "[5f2c] reconcile on batch %s: edge authority %d applied, %d rejected stale, %d refused, %d gone, %d held",
        batch.entity_id,
        edge_counts[APPLIED],
        edge_counts[REJECTED_STALE],
        edge_counts[REFUSED],
        edge_counts[GONE],
        edge_counts[HELD],
    )
    logger.info(
        "[b88a] reconcile on batch %s: %d applied, %d rejected stale, %d refused, %d not applicable, %d contradicted",
        batch.entity_id,
        summary["applied"],
        summary["rejected_stale"],
        summary["refused"],
        summary["not_applicable"],
        summary["contradicted"],
    )
    return record


# ---------------------------------------------------------------------------
# Applying verdicts
# ---------------------------------------------------------------------------


def _apply(batch: Any, record: dict[str, Any], *, produced_batches: set[str]) -> dict[str, Any]:
    from dataclasses import replace

    from tap_grid.caller_context import CallerContext, get_caller_context
    from tap_grid.services import write_batch

    since = _derived_at(batch)
    if since is None:
        raise ReconcileError(
            "invalid_record", "the candidate record's recorded_at is missing or unparsable; nothing applied"
        )
    counts = {APPLIED: 0, REJECTED_STALE: 0, REFUSED: 0, NOT_APPLICABLE: 0, CONTRADICTED: 0}
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
        _lock_target(entity_id)  # the fence is check-then-act only if the row can move between the two
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
        if plan == "tombstone":
            # The contradiction fence (Issue# 656 - tap): derivation checked the closure against
            # this run's observations; the closure and the observations can both have moved
            # since. A node under the target observed by any committed batch since the record
            # was derived contradicts the tombstone now — refuse, never cascade over it.
            contradiction = _closure_observed_since(entity_id, since, produced_batches)
            if contradiction is not None:
                entry["applied"] = {"write": plan, "outcome": CONTRADICTED, "error": contradiction}
                counts[CONTRADICTED] += 1
                logger.warning("[2611] reconcile: tombstone on %s contradicted at apply: %s", entity_id, contradiction)
                continue
        licensed = _licensed_rows(entry)  # from the verdict entry, never from the operation
        op = _operation_for(entry, batch, generation)
        if op is None:
            entry["applied"] = {
                "write": plan,
                "outcome": REFUSED,
                "error": "no operation could be formed for this verdict",
            }
            counts[REFUSED] += 1
            continue
        if op.verb == "delete_edge":
            # A transfer ends an EDGE. Re-creating it leaves a `link` event on the edge and no
            # update on the child, so the child's fence cannot see it: fence the edge itself.
            edge_id = uuid.UUID(str(op.target))
            _lock_target(edge_id)
            if _observed_since(edge_id, since, produced_batches):
                entry["applied"] = {
                    "write": plan,
                    "outcome": REJECTED_STALE,
                    "error": "the ownership edge was re-created after the candidate record was derived; the verdict is stale",
                }
                counts[REJECTED_STALE] += 1
                logger.warning(
                    "[7206] reconcile: transfer verdict on %s rejected as stale (edge %s re-created since %s)",
                    entity_id,
                    edge_id,
                    since.isoformat(),
                )
                continue
        # The one scope in which grid.reconcile licenses a delete, bound to the rows the verdict
        # entry names and nothing else: the write pipeline's delete backstop consults it. The
        # licence is derived from the entry, not from the operation, so an operation formed for
        # the wrong row is refused rather than licensed by its own target (Codex on PR# 658).
        # Each verdict's write mints its own batch, and a minted batch must say what it is
        # (req-grid-service-batch-label-required). The label rides on the context, so a
        # caller that bound a batch scope still joins it.
        labelled = replace(
            get_caller_context() or CallerContext(),
            batch_name=f"Reconcile: {plan} {entity_id}",
            batch_description=(
                f"The reconcile verb applied a {plan!r} verdict to {entity_id}, judged on collection "
                f"run batch {batch.entity_id}."
            ),
        )
        with reconcile_write_scope(licensed):
            result = (
                write_batch(  # TAP-AUTHZ-COV: reached only through tap_grid.services.reconcile, gated by grid.reconcile
                    [op], caller_context=labelled, result_mode="minimal"
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


# ---------------------------------------------------------------------------
# Applying edge authority (req-grid-reconcile-edge-authority-9, -11 to -13)
# ---------------------------------------------------------------------------

#: The key, inside the run's reconcile record, that holds the edge authority record.
EDGE_AUTHORITY_KEY = "edge_authority"
#: An edge no longer live when its proposal comes to be applied.
GONE = "gone"
#: A proposal of a held claim: deferred, not dropped (-13).
HELD = "held"
EDGE_AUTHORITY_OUTCOMES: frozenset[str] = frozenset({APPLIED, REJECTED_STALE, REFUSED, GONE, HELD})
#: A claim that asserted none of a scope holding at least this many live edges is held (-13).
WHOLE_SCOPE_HOLD_FLOOR = 3
#: The delete reason an applied proposal records (req-grid-service-delete-reason).
AUTHORITY_REASON = "authority"


def _authority_records(produced_batches: set[str]) -> tuple[dict[tuple[str, str, str, str], Any], list[Any]]:
    """The run's claimed claims, keyed by scope, and its ``proposed`` proposals in edge-id order.

    Both are ``authority_proposed`` events written by the importer's dry-run on the run's own
    batches. A claim's key is its batch and scope; a proposal names its claim by the same fields.
    """
    from tap_grid.models import BatchEvent, BatchEventType

    run_batches = [uuid.UUID(b) for b in produced_batches]
    claims = {
        _claim_key(str(event.batch.entity_id), event.metadata): event
        for event in BatchEvent.objects.filter(
            event_type=BatchEventType.AUTHORITY_PROPOSED,
            batch__entity_id__in=run_batches,
            metadata__record="claim",
            metadata__outcome="claimed",
        ).select_related("batch")
    }
    proposals = list(
        BatchEvent.objects.filter(
            event_type=BatchEventType.AUTHORITY_PROPOSED,
            batch__entity_id__in=run_batches,
            metadata__record="proposal",
            metadata__outcome="proposed",
        )
        .select_related("batch")
        .order_by("entity_id", "id")
    )
    return claims, proposals


def _claim_key(batch_id: str, scope: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (batch_id, str(scope.get("edge_type")), str(scope.get("anchor_entity_id")), str(scope.get("direction")))


def _whole_scope(claim: Any) -> bool:
    """True iff the claim asserted none of a scope holding ``WHOLE_SCOPE_HOLD_FLOOR`` or more live edges."""
    m = claim.metadata
    in_scope = int(m.get("proposed") or 0) + int(m.get("rejected_stale") or 0)
    return int(m.get("asserted") or 0) == 0 and in_scope >= WHOLE_SCOPE_HOLD_FLOOR


def _held_claim(claim: Any) -> dict[str, Any]:
    m = claim.metadata
    return {
        "claim_event_id": str(claim.id),
        "batch": str(claim.batch.entity_id),
        "edge_type": m.get("edge_type"),
        "anchor": m.get("anchor"),
        "anchor_entity_id": m.get("anchor_entity_id"),
        "direction": m.get("direction"),
        "in_scope": int(m.get("proposed") or 0) + int(m.get("rejected_stale") or 0),
        "proposed": int(m.get("proposed") or 0),
        "released": None,
        "superseded_by": None,
    }


def _edge_observed_since(edge_id: uuid.UUID, boundary: datetime, claiming_batch: str) -> list[str]:
    """The batches, other than the claiming one, that created, updated or linked the edge since the
    claim's read boundary: ``-8``'s fence, applied again at apply time (``-11``). This run's other
    batches count, as they do in the dry-run."""
    from tap_grid.models import BatchEvent, BatchEventType

    return sorted(
        {
            str(b)
            for b in BatchEvent.objects.filter(
                entity_id=edge_id,
                event_type__in=[BatchEventType.CREATE, BatchEventType.UPDATE, BatchEventType.LINK],
                timestamp__gt=boundary,
            )
            .exclude(batch__entity_id=uuid.UUID(claiming_batch))
            .values_list("batch__entity_id", flat=True)
        }
    )


def _apply_proposal(
    batch: Any, proposal: Any, claim: Any, removed: set[str], *, released_by: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Apply one proposal: lock, check it is live and claimable, fence it again, remove it."""
    from dataclasses import replace

    from tap_grid.caller_context import CallerContext, get_caller_context
    from tap_grid.constraints import is_internal_edge_type
    from tap_grid.models import Entity
    from tap_grid.services import write_batch

    edge_id = proposal.entity_id
    edge_type = (proposal.metadata.get("identity") or {}).get("edge_type") or ""
    if str(edge_id) in removed:
        return {"outcome": GONE, "error": "already removed by another claim in this run"}
    _lock_target(edge_id)
    if not Entity.objects.filter(pk=edge_id, deleted_at__isnull=True).exists():
        return {"outcome": GONE, "error": None}
    if is_internal_edge_type(edge_type):
        return {"outcome": REFUSED, "error": f"edge type {edge_type!r} is internal-only and cannot be claimed"}
    boundary = _parse_boundary((claim.metadata if claim is not None else {}).get("read_boundary"))
    if boundary is None:
        return {"outcome": REFUSED, "error": "the claim recorded no read boundary; nothing can be fenced"}
    observed = _edge_observed_since(edge_id, boundary, str(proposal.batch.entity_id))
    if observed:
        logger.warning(
            "[e7a1] reconcile: authority proposal on edge %s rejected as stale at apply (observed by %s)",
            edge_id,
            ", ".join(observed),
        )
        return {"outcome": REJECTED_STALE, "error": f"observed since the claim's read by {', '.join(observed)}"}
    audit = {
        EDGE_AUTHORITY_KEY: {
            "run": str(batch.entity_id),
            "claim": proposal.metadata.get("claim"),
            "proposal_event_id": str(proposal.id),
            "released_by": dict(released_by) if released_by else None,
        }
    }
    op = WriteOperation(verb="delete_edge", target=str(edge_id), reason=AUTHORITY_REASON, metadata=audit)
    labelled = replace(
        get_caller_context() or CallerContext(),
        batch_name=f"Reconcile: authority unlink {edge_id}",
        batch_description=(
            f"The reconcile verb removed edge {edge_id} ({edge_type}) on a complete edge-authority claim, "
            f"applied on collection run batch {batch.entity_id}."
        ),
    )
    with reconcile_write_scope({str(edge_id)}):
        result = write_batch(  # TAP-AUTHZ-COV: reached only through tap_grid.services.reconcile and the release, both gated
            [op], caller_context=labelled, result_mode="minimal"
        )
    outcome = result.results[0] if result.results else None
    if outcome is not None and outcome.success:
        removed.add(str(edge_id))
        return {"outcome": APPLIED, "error": None}
    errors = (outcome.errors if outcome is not None else result.errors) or []
    error = "; ".join(f"{e.code}: {e.message}" for e in errors)[:500] or "refused"
    logger.warning("[c4d9] reconcile: authority unlink of edge %s refused: %s", edge_id, error)
    return {"outcome": REFUSED, "error": error}


def _parse_boundary(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _edge_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = dict.fromkeys(sorted(EDGE_AUTHORITY_OUTCOMES), 0)
    for entry in entries:
        counts[entry["outcome"]] += 1
    return counts


def _apply_edge_authority(batch: Any, *, produced_batches: set[str]) -> dict[str, Any]:
    """Apply the run's edge-authority proposals, holding any claim that would empty its scope.

    Runs inside ``reconcile_run``'s transaction, after the node verdicts, with authority on.
    """
    claims, proposals = _authority_records(produced_batches)
    held = {key: _held_claim(claim) for key, claim in claims.items() if _whole_scope(claim)}
    removed: set[str] = set()
    entries: list[dict[str, Any]] = []
    for proposal in proposals:
        key = _claim_key(str(proposal.batch.entity_id), proposal.metadata.get("claim") or {})
        entry: dict[str, Any] = {
            "edge_id": str(proposal.entity_id),
            "edge_type": (proposal.metadata.get("identity") or {}).get("edge_type"),
            "proposal_event_id": str(proposal.id),
            "claim_event_id": str(claims[key].id) if key in claims else None,
        }
        if key in held:
            entry.update({"outcome": HELD, "error": None})
        else:
            entry.update(_apply_proposal(batch, proposal, claims.get(key), removed, released_by=None))
        entries.append(entry)
    for claim in held.values():
        logger.warning(
            "[9b3e] reconcile: edge authority claim %s held: it asserted none of %d live %s edge(s) %s of %s; "
            "nothing applied until a later run supersedes it or an operator releases it",
            claim["claim_event_id"],
            claim["in_scope"],
            claim["edge_type"],
            claim["direction"],
            claim["anchor_entity_id"],
        )
    return {"authority": "on", "counts": _edge_counts(entries), "held_claims": list(held.values()), "entries": entries}


def _superseding_claim(claim: Mapping[str, Any]) -> str | None:
    """The complete claim over the same scope whose read began after the held one's: a later read of
    the scope supersedes the hold (``-14``). Ordered by each claim's recorded read boundary, not by
    when its event was written: a run that read first can submit its claim after a run that read
    later, and only the read order says which saw the scope more recently. Among several later
    reads, the earliest names the hold's successor."""
    from tap_grid.models import BatchEvent, BatchEventType

    held = BatchEvent.objects.filter(id=claim["claim_event_id"]).values_list("metadata", flat=True).first()
    held_boundary = _parse_boundary((held or {}).get("read_boundary"))
    if held_boundary is None:
        return None
    later: list[tuple[datetime, uuid.UUID]] = []
    for event_id, metadata in (
        BatchEvent.objects.filter(
            event_type=BatchEventType.AUTHORITY_PROPOSED,
            metadata__record="claim",
            metadata__outcome="claimed",
            metadata__edge_type=claim["edge_type"],
            metadata__anchor_entity_id=claim["anchor_entity_id"],
            metadata__direction=claim["direction"],
        )
        .exclude(id=claim["claim_event_id"])
        .values_list("id", "metadata")
    ):
        boundary = _parse_boundary((metadata or {}).get("read_boundary"))
        if boundary is not None and boundary > held_boundary:
            later.append((boundary, event_id))
    return str(min(later)[1]) if later else None

def _release_held(batch: Any, *, claim_event_ids: set[str] | None, released_by: Mapping[str, Any]) -> dict[str, Any]:
    """Apply a run's held edge-authority proposals: an operator's release (``-14``).

    Reached only through ``tap_grid.services.release_edge_authority_hold``, which gates the operator
    on ``cares.arm_reconcile`` and runs this as the collector program actor under
    ``grid.reconcile``, the way ``arm_reconcile`` writes; a collector never names it (the
    collectors-never-retire walk). Each held proposal takes the same path as applying, re-locked
    and re-fenced, so an edge observed since the claim's read is ``rejected_stale``. A held claim
    whose scope a later complete claim has read is superseded: it is not released, and records
    which claim superseded it. Each released claim records who released it and when. A claim
    already released or superseded, or a run with nothing held, releases nothing.
    ``claim_event_ids`` narrows the release to those claims; None means every held claim of the run.
    """
    from tap_grid.models import Batch, BatchEvent

    with transaction.atomic():
        # One release of a run at a time: lock its batch row, then read the record under the lock. A
        # second operator waits here, re-reads, and finds the claims already released, so the record
        # and the unlinks never disagree about who released what.
        locked = cast(Batch, Batch.all_objects.select_for_update().get(pk=batch.pk))  # django-stubs: manager typing
        record = verdicts_of(locked)
        edge = (record or {}).get(EDGE_AUTHORITY_KEY) or {}
        candidates = [
            claim
            for claim in edge.get("held_claims", [])
            if claim.get("released") is None
            and claim.get("superseded_by") is None
            and (claim_event_ids is None or claim["claim_event_id"] in claim_event_ids)
        ]
        if record is None or not candidates:
            return {"released_claims": [], "superseded_claims": [], "counts": _edge_counts([])}
        superseded: list[str] = []
        targets: list[dict[str, Any]] = []
        for claim in candidates:
            newer = _superseding_claim(claim)
            if newer is None:
                targets.append(claim)
            else:
                claim["superseded_by"] = newer
                superseded.append(claim["claim_event_id"])
        target_ids = {claim["claim_event_id"] for claim in targets}
        released: list[dict[str, Any]] = []
        removed: set[str] = set()
        for entry in edge["entries"]:
            if entry["outcome"] != HELD or entry["claim_event_id"] not in target_ids:
                continue
            proposal = BatchEvent.objects.select_related("batch").get(id=entry["proposal_event_id"])
            claim_event = BatchEvent.objects.get(id=entry["claim_event_id"])
            entry.update(_apply_proposal(batch, proposal, claim_event, removed, released_by=released_by))
            released.append(entry)
        for claim in targets:
            claim["released"] = dict(released_by)
        edge["counts"] = _edge_counts(edge["entries"])
        record[EDGE_AUTHORITY_KEY] = edge
        _store(locked, record)
    batch.metadata = locked.metadata
    return {"released_claims": sorted(target_ids), "superseded_claims": sorted(superseded), "counts": _edge_counts(released)}


def _edge_authority_off(produced_batches: set[str]) -> dict[str, Any]:
    """With authority off nothing is applied; the record says how many proposals stand unapplied."""
    _claims, proposals = _authority_records(produced_batches)
    return {"authority": "off", "unapplied": len(proposals), "counts": None, "held_claims": [], "entries": []}


def _closure_observed_since(entity_id: uuid.UUID, since: datetime, produced_batches: set[str]) -> str | None:
    """Why the tombstone's closure contradicts it now, or None when it holds no live evidence.

    The closure is read the way the cascade reads it before writing — rows locked, then
    re-discovered under the locks until stable (``contained_closure_locked``) — so a descendant
    attached after the first look is checked too, and the cascade that follows in this
    transaction walks the same closure under the same locks. Two checks on that closure, both
    fail closed: (1) the title invariant re-asserted under the locks — a node THIS run observed
    (any of its committed batches, whenever) must not be in the closure now; derivation checked
    the closure it saw, but a node this run observed can be re-parented under the candidate
    afterwards with only a ``link`` event on the edge (Grok on PR# 663 - tap); (2) a node
    observed since the record was derived by any batch that has not failed — an OPEN batch may
    commit a moment after this check, and only a FAILED batch is known to have rolled back
    (Codex and Grok on PR# 663 - tap). An unknown closure (over the cap) is refused here by
    name rather than left for the cascade to refuse by size."""
    from tap_grid.candidates import observed_by
    from tap_grid.models import BatchEvent, BatchEventType, BatchStatus
    from tap_grid.services import contained_closure_locked

    closure = contained_closure_locked(entity_id)
    if closure is None:
        return "the nodes contained under the target exceed the cascade cap; the closure cannot be checked"
    if not closure:
        return None
    ids = sorted(closure)
    own, _ = observed_by(produced_batches)
    own_hits = sorted(closure & own)
    if own_hits:
        named = ", ".join(str(h) for h in own_hits[:20])
        return (
            f"{len(own_hits)} node(s) this run observed live are contained under the target now "
            f"({named}{'…' if len(own_hits) > 20 else ''}); the tombstone would cascade over the run's own "
            "evidence — refused, investigate (Issue# 656 - tap)"
        )
    hits = list(
        BatchEvent.objects.filter(
            entity_id__in=ids,
            event_type__in=[BatchEventType.CREATE, BatchEventType.UPDATE],
            timestamp__gt=since,
        )
        .exclude(batch__status=BatchStatus.FAILED)
        .values_list("entity_id", flat=True)
        .distinct()
    )
    if not hits:
        return None
    named = ", ".join(str(h) for h in sorted(hits)[:20])
    return (
        f"{len(hits)} node(s) contained under the target were observed after the candidate record was derived, by "
        f"a batch that has not failed ({named}{'…' if len(hits) > 20 else ''}); the tombstone would cascade over "
        "live evidence — refused, investigate (Issue# 656 - tap)"
    )


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


def _licensed_rows(entry: Mapping[str, Any]) -> set[str]:
    """The rows this verdict entry may delete: the candidate itself, and for a transfer the
    parent's containment edge into it. Derived from the entry alone, so the licence and the
    operation are two derivations of the verdict and a defect in either is refused by the other."""
    rows = {str(entry["entity_id"])}
    if entry["verdict"] == RELOCATED and entry.get("kind") == RELOCATED_TRANSFERRED:
        edge_id = _ownership_edge(entry)
        if edge_id is not None:
            rows.add(str(edge_id))
    return rows


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


def _lock_target(entity_id: uuid.UUID) -> None:
    """Hold the target's spine row for the rest of the transaction: a concurrent observer takes
    the same lock in the write pipeline, so the fence's read and the verb's write see one
    committed state, not two."""
    from tap_grid.models import Entity

    Entity.objects.select_for_update().filter(pk=entity_id).exists()


def _derived_at(batch: Any) -> datetime | None:
    record = candidates_of(batch)
    if record is None:
        return None
    try:
        return datetime.fromisoformat(record["recorded_at"])
    except KeyError, ValueError, TypeError:
        return None


def _observed_since(entity_id: uuid.UUID, since: datetime, produced_batches: set[str]) -> bool:
    """Has the entity been re-observed — a create, update or link event from a COMMITTED batch
    that is not one of this run's — since the candidate record was derived? ``Entity.version``
    is not consulted: an unchanged re-observation deliberately may not bump it (-4). ``link`` is
    the event an edge's creation records on the edge's own entity, so the same predicate fences
    a transfer's edge."""
    from tap_grid.models import BatchEvent, BatchEventType, BatchStatus

    return (
        BatchEvent.objects.filter(
            entity_id=entity_id,
            event_type__in=[BatchEventType.CREATE, BatchEventType.UPDATE, BatchEventType.LINK],
            timestamp__gt=since,
            batch__status=BatchStatus.CLOSED,
        )
        .exclude(batch__entity_id__in=[uuid.UUID(b) for b in produced_batches])
        .exists()
    )


def _store(batch: Any, record: dict[str, Any]) -> None:
    """Write the run's reconcile record, validated against the verdicts schema first: the record
    the falsifier validated gains ``applied`` and ``edge_authority`` here, and a shape that drifted
    from the schema is refused rather than stored."""
    from tap.jsonfiles import JsonFileError, validate_json
    from tap_grid.falsifiers import _SCHEMA, METADATA_KEY
    from tap_grid.models import Batch

    try:
        validate_json(record, _SCHEMA, source=f"verdicts on batch {batch.entity_id}")
    except JsonFileError as exc:
        raise ReconcileError("invalid_record", f"{exc} (at {exc.location})") from exc
    with transaction.atomic():
        locked = cast(Batch, Batch.objects.select_for_update().get(pk=batch.pk))  # django-stubs: manager typing
        metadata = dict(locked.metadata or {})
        metadata[METADATA_KEY] = record
        locked.metadata = metadata
        # Run bookkeeping on the lifecycle batch: a named below-pipeline writer.
        with below_pipeline_write("bookkeeping"):
            locked.save(update_fields=["metadata"])
    batch.metadata = metadata


__all__ = [
    "APPLIED",
    "AUTHORITY_REASON",
    "EDGE_AUTHORITY_KEY",
    "EDGE_AUTHORITY_OUTCOMES",
    "GONE",
    "HELD",
    "WHOLE_SCOPE_HOLD_FLOOR",
    "RUN_CONFIG_KEY",
    "APPLY_OUTCOMES",
    "NOT_APPLICABLE",
    "RECONCILE_METADATA_KEY",
    "REFUSED",
    "REJECTED_STALE",
    "ReconcileError",
    "reconcile_run",
    "run_config",
    "run_config_of",
    "verdicts_of",
]
