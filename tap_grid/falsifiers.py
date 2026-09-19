"""Per-type falsifiers and their verdicts — declared, registered, run, and RECORDED. Authority off.

``req-grid-reconcile-falsifier`` (``tap_grid/specs/spec-grid-reconcile.md``): a candidate for
retirement (``tap_grid.candidates``) is not retired on the strength of a listing. A
**falsifier** — one per entity type, declared by the plugin that owns the type — probes the
source for each candidate and returns a **verdict**. Five verdicts, none of them a field on
the observed node:

- ``DROPPED_FROM_OBSERVATION`` — listing and probe agree it is gone from view.
- ``PRESENT_AT_PROBE`` — absent from the listing, yet the probe found the same source
  identity under the same owner. The subject of this verdict is *this* system, and it claims
  no collector defect: the object was created after the listing started, **or** access was
  restored between the listing and the probe. The record states the disjunction and names a
  cause only when the source's creation time settles it (-4).
- ``RELOCATED`` — the same source identity under a new name (a rename: a locator update,
  -8) or under a different owner (a transfer: ends *this* owner's relationship, retires
  nothing, cascades nothing, -7/-9).
- ``UNDETERMINED(reason)`` — the probe could not answer: ``forbidden``, ``errored``,
  ``rate_limited``, ``budget`` or ``scope_unknown``.
- ``REIDENTIFIED`` — a different source identity now occupies the address.

Phase 4 slice 3 (Issue# 644 - tap): **authority off**. ``falsify_candidates`` runs the
registered falsifiers over a run's recorded candidates and writes the verdicts on the run's
lifecycle ``Batch`` beside its candidate record (``tap_grid/schemas/verdicts.schema.json``).
Nothing here tombstones, renames or ends an edge; every entry names the write the reconcile
verb (``req-grid-reconcile-verb``, slice 4) WOULD make and where it would land (-3), so the
record is a plan that can be read, not a change that has to be trusted.

A type with no registered falsifier is **not reconcilable**: its candidates are recorded as
not re-observed and are never probed or retired (-1). Coverage is a validate-time warning,
not a load-time gate (-2, ``tap_plugins.validate``).

The **classification** is derived once, here, from what the probe returned against what the
grid holds, in source terms (``classify``). A falsifier's job is the probe; it hands the
answer to ``verdict_from_probe`` rather than re-deriving the table. HTTP success is not a
verdict.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from tap.credential_patterns import CREDENTIAL_PATTERNS
from tap.jsonfiles import JsonFileError, load_schema, validate_json
from tap_grid.candidates import candidates_of
from tap_grid.completeness import completeness_of

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "verdicts.schema.json"
_SCHEMA: dict[str, Any] = load_schema(SCHEMA_PATH)

METADATA_KEY = "verdicts"

# ---------------------------------------------------------------------------
# The vocabulary — closed sets, every one
# ---------------------------------------------------------------------------

DROPPED_FROM_OBSERVATION = "DROPPED_FROM_OBSERVATION"
PRESENT_AT_PROBE = "PRESENT_AT_PROBE"
RELOCATED = "RELOCATED"
UNDETERMINED = "UNDETERMINED"
REIDENTIFIED = "REIDENTIFIED"
VERDICTS: frozenset[str] = frozenset(
    {DROPPED_FROM_OBSERVATION, PRESENT_AT_PROBE, RELOCATED, UNDETERMINED, REIDENTIFIED}
)

#: Why a probe could not answer (``UNDETERMINED``). Closed: a reason outside it is a refusal.
UNDETERMINED_REASONS: frozenset[str] = frozenset({"forbidden", "errored", "rate_limited", "budget", "scope_unknown"})

#: What ``RELOCATED`` found: the same identity under a new name, or under a different owner.
RELOCATED_RENAMED = "renamed"
RELOCATED_TRANSFERRED = "transferred"
RELOCATED_KINDS: frozenset[str] = frozenset({RELOCATED_RENAMED, RELOCATED_TRANSFERRED})

#: The cause a ``PRESENT_AT_PROBE`` record names. ``created_after_listing_started`` only when
#: the source's creation time is at or after the surface's observation interval start; anything
#: else is ``indeterminate``, because restored access explains it equally well.
CAUSE_CREATED_AFTER = "created_after_listing_started"
CAUSE_INDETERMINATE = "indeterminate"
PRESENT_CAUSES: frozenset[str] = frozenset({CAUSE_CREATED_AFTER, CAUSE_INDETERMINATE})

#: The disjunction every ``PRESENT_AT_PROBE`` record states, verbatim, so no reader can take it
#: for a collector-defect claim (-4).
PRESENT_STATEMENT = (
    "absent from the listing and present at the probe under the same source identity and owner: "
    "either the object was created after the listing started, or access to it was restored "
    "between the listing and the probe"
)

#: Per-entry outcomes of the dispatch: a falsifier judged it, or no falsifier exists for the type.
JUDGED = "judged"
NOT_RECONCILABLE = "not_reconcilable"

ProbeStatus = Literal["found", "not_found", "forbidden", "errored", "rate_limited", "budget", "scope_unknown"]
PROBE_STATUSES: frozenset[str] = frozenset({"found", "not_found"} | UNDETERMINED_REASONS)

#: Free text from a probe or a failing falsifier is recorded on the run's Batch and shown in the
#: viewer, so it is scrubbed first: every credential shape the repository scanner knows, plus the
#: generic ``key: value`` / ``key=value`` shapes an HTTP client's error text carries, and a length
#: cap. The dispatch never reads this text; a human does.
_SECRET_FIELD = re.compile(
    r"(?i)\b(authorization|bearer|token|secret|password|passwd|api[_-]?key|x-api-key|cookie|set-cookie)\b"
    r"(\s*[:=]\s*(?:(?:basic|bearer|token)\s+)?)(\S+)"
)
_DETAIL_CAP = 500
REDACTED = "<redacted>"


def scrub(text: str | None) -> str:
    """Free text fit to record: credential shapes and secret-looking fields redacted, length capped."""
    if not text:
        return ""
    out = str(text)
    for pattern in CREDENTIAL_PATTERNS:
        out = pattern.regex.sub(REDACTED, out)
    out = _SECRET_FIELD.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", out)
    return out if len(out) <= _DETAIL_CAP else out[:_DETAIL_CAP] + "…"


class FalsifierError(ValueError):
    """A refusal, before any write: ``batch_not_open``, ``no_candidates``, ``invalid_record``,
    ``bad_verdict`` or ``duplicate_registration``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# The data a falsifier is handed, and what it hands back
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """One retirement candidate as the candidate record holds it, plus the surface it came from.

    ``interval_first`` is the start of the surface's observation interval when the surface
    belongs to this run's statement; ``None`` for a withdrawn surface (the previous run read
    it), which makes any present-at-probe cause ``indeterminate``.
    """

    entity_id: uuid.UUID
    entity_type: str
    reason: str
    surface: int
    relation: str | None
    subject: str | None
    edge_type: str | None
    parent: uuid.UUID | None
    interval_first: datetime | None


@dataclass(frozen=True)
class Expected:
    """What the grid holds for a candidate, in the source's own terms: the stable source identity
    the natural key rests on, and the owner or containing scope it was observed under."""

    source_id: str
    owner: str | None = None
    name: str | None = None

    def summary(self) -> dict[str, Any]:
        return {"source_id": self.source_id, "owner": self.owner, "name": self.name}


@dataclass(frozen=True)
class Probe:
    """What a probe of the source returned. ``status`` is the closed set; the identity fields are
    only meaningful when it is ``found``. ``created_at`` is the source's own creation time for the
    object, when the source reports one."""

    status: ProbeStatus
    source_id: str | None = None
    owner: str | None = None
    name: str | None = None
    created_at: datetime | None = None
    detail: str = ""

    def summary(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source_id": self.source_id,
            "owner": self.owner,
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "detail": scrub(self.detail),
        }


@dataclass(frozen=True)
class Verdict:
    """A falsifier's answer for one candidate: the verdict, its qualifier, the probe it rests on and
    the grid-side terms it was compared against. Both sides travel with the verdict so the
    dispatch can re-derive the classification and refuse a verdict the evidence does not yield."""

    entity_id: uuid.UUID
    verdict: str
    reason: str | None = None  #: UNDETERMINED: why the probe could not answer
    kind: str | None = None  #: RELOCATED: renamed | transferred
    cause: str | None = None  #: PRESENT_AT_PROBE: created_after_listing_started | indeterminate
    probe: dict[str, Any] | None = None
    expected: dict[str, Any] | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise FalsifierError("bad_verdict", f"{self.verdict!r} is not a verdict; the set is {sorted(VERDICTS)}")
        if self.verdict == UNDETERMINED and self.reason not in UNDETERMINED_REASONS:
            raise FalsifierError(
                "bad_verdict", f"UNDETERMINED needs a reason in {sorted(UNDETERMINED_REASONS)}, got {self.reason!r}"
            )
        if self.verdict == RELOCATED and self.kind not in RELOCATED_KINDS:
            raise FalsifierError(
                "bad_verdict", f"RELOCATED needs a kind in {sorted(RELOCATED_KINDS)}, got {self.kind!r}"
            )
        if self.verdict == PRESENT_AT_PROBE and self.cause not in PRESENT_CAUSES:
            raise FalsifierError(
                "bad_verdict", f"PRESENT_AT_PROBE needs a cause in {sorted(PRESENT_CAUSES)}, got {self.cause!r}"
            )


@dataclass(frozen=True)
class FalsifyContext:
    """What every falsifier call is told about the run: the lifecycle batch id and the run's
    completeness statement (surfaces in statement order), read-only."""

    batch_id: str
    statement: Mapping[str, Any] | None
    extra: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Classification — derived once, from the probe table in the spec
# ---------------------------------------------------------------------------


def classify(expected: Expected, probe: Probe, *, interval_first: datetime | None) -> dict[str, Any]:
    """The four-outcome table, plus the two ways a probe fails to answer.

    TAP-IMPLEMENTS: req-grid-reconcile-falsifier@d63eb8b978f6/90376f4c461e (derivation) — the
        verdict a probe result yields is derived here and nowhere else: identity and owner
        decide, never HTTP status.

    Returns the ``verdict`` / ``reason`` / ``kind`` / ``cause`` fields for a :class:`Verdict`.
    """
    if probe.status in UNDETERMINED_REASONS:
        return {"verdict": UNDETERMINED, "reason": probe.status}
    if probe.status == "not_found":
        return {"verdict": DROPPED_FROM_OBSERVATION}
    if probe.status != "found":
        raise FalsifierError("bad_verdict", f"probe status {probe.status!r} is not in {sorted(PROBE_STATUSES)}")
    if probe.source_id != expected.source_id:
        return {"verdict": REIDENTIFIED}
    if probe.owner != expected.owner:
        return {"verdict": RELOCATED, "kind": RELOCATED_TRANSFERRED}
    if probe.name is not None and expected.name is not None and probe.name != expected.name:
        return {"verdict": RELOCATED, "kind": RELOCATED_RENAMED}
    return {"verdict": PRESENT_AT_PROBE, "cause": _present_cause(probe.created_at, interval_first)}


def _present_cause(created_at: datetime | None, interval_first: datetime | None) -> str:
    """Timing rules a cause IN; it never rules restored access OUT (-4)."""
    if created_at is None or interval_first is None:
        return CAUSE_INDETERMINATE
    created = created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)
    first = interval_first if interval_first.tzinfo else interval_first.replace(tzinfo=UTC)
    return CAUSE_CREATED_AFTER if created >= first else CAUSE_INDETERMINATE


def verdict_from_probe(candidate: Candidate, expected: Expected, probe: Probe, *, note: str = "") -> Verdict:
    """The verdict for a candidate, given what the grid holds and what the probe returned."""
    fields = classify(expected, probe, interval_first=candidate.interval_first)
    return Verdict(
        entity_id=candidate.entity_id, probe=probe.summary(), expected=expected.summary(), note=note, **fields
    )


def would(verdict: Verdict) -> dict[str, str]:
    """The write the reconcile verb WOULD make on this verdict, and its one home (-3)."""
    if verdict.verdict == DROPPED_FROM_OBSERVATION:
        return {"write": "tombstone", "home": "entity"}
    if verdict.verdict == RELOCATED and verdict.kind == RELOCATED_RENAMED:
        return {"write": "rename", "home": "entity_name"}
    if verdict.verdict == RELOCATED:
        return {"write": "end_ownership_edge", "home": "ownership_edge"}
    return {"write": "none", "home": "run_record"}


# ---------------------------------------------------------------------------
# The falsifier contract and the per-type registry
# ---------------------------------------------------------------------------


class Falsifier:
    """One entity type's falsifier. Implement ``batch_falsify`` (preferred: one aliased query for
    fifty candidates) or ``falsify_one``; the base class supplies the batch-over-singular default.
    ``entity_type`` is set by registration."""

    entity_type: str = ""

    def batch_falsify(self, candidates: Sequence[Candidate], context: FalsifyContext) -> list[Verdict]:
        return [self.falsify_one(candidate, context) for candidate in candidates]

    def falsify_one(self, candidate: Candidate, context: FalsifyContext) -> Verdict:
        raise NotImplementedError(f"{type(self).__name__} implements neither batch_falsify nor falsify_one")


_FALSIFIERS: dict[str, Falsifier] = {}


def register_falsifier(entity_type: str, falsifier: Falsifier) -> None:
    """Register the falsifier for an entity type. A second registration for the same type is a
    configuration error, never a silent replacement."""
    if not isinstance(falsifier, Falsifier):
        raise ImproperlyConfigured(f"falsifier for {entity_type!r} must be a tap_grid.falsifiers.Falsifier instance")
    if entity_type in _FALSIFIERS:
        raise ImproperlyConfigured(f"a falsifier is already registered for {entity_type!r}")
    falsifier.entity_type = entity_type
    _FALSIFIERS[entity_type] = falsifier


def unregister_falsifier(entity_type: str) -> None:
    _FALSIFIERS.pop(entity_type, None)


def get_falsifier(entity_type: str) -> Falsifier | None:
    return _FALSIFIERS.get(entity_type)


def registered_falsifiers() -> dict[str, Falsifier]:
    return dict(_FALSIFIERS)


# ---------------------------------------------------------------------------
# Dispatch — run the falsifiers over a run's candidates and record; retire nothing
# ---------------------------------------------------------------------------


def verdicts_of(batch: Any) -> dict[str, Any] | None:
    """The verdict record on a batch, or None when no dispatch was recorded."""
    metadata = batch.metadata or {}
    record = metadata.get(METADATA_KEY)
    return dict(record) if isinstance(record, dict) else None


def candidates_from(batch: Any) -> list[Candidate]:
    """Every candidate the run's record holds, with the surface it came from and that surface's
    observation interval start (this run's statement only; withdrawn surfaces carry None)."""
    record = candidates_of(batch)
    if record is None:
        raise FalsifierError("no_candidates", f"batch {batch.entity_id} carries no candidate record")
    statement = completeness_of(batch) or {}
    intervals = [_first_of(s) for s in statement.get("surfaces", [])]
    out: list[Candidate] = []
    for index, surface in enumerate(record.get("surfaces", [])):
        interval_first = intervals[index] if index < len(intervals) and surface.get("outcome") != "withdrawn" else None
        parent = surface.get("parent")
        for entry in surface.get("candidates", []):
            out.append(
                Candidate(
                    entity_id=uuid.UUID(entry["entity_id"]),
                    entity_type=entry["entity_type"],
                    reason=entry["reason"],
                    surface=index,
                    relation=surface.get("relation"),
                    subject=surface.get("subject"),
                    edge_type=surface.get("edge_type"),
                    parent=uuid.UUID(parent) if parent else None,
                    interval_first=interval_first,
                )
            )
    return out


def _first_of(surface: Mapping[str, Any]) -> datetime | None:
    first = (surface.get("interval") or {}).get("first")
    try:
        return datetime.fromisoformat(first) if first else None
    except ValueError:
        return None


def falsify_candidates(batch: Any, *, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Run each type's registered falsifier once over that type's candidates and record the
    verdicts on the OPEN lifecycle batch beside its candidate record. Authority off: nothing is
    retired, renamed or unlinked; each entry names the write slice 4 would make (-3).

    TAP-IMPLEMENTS: req-grid-reconcile-falsifier@d63eb8b978f6/5fb88d0846bb (enforcement) — a
        type without a falsifier is not reconcilable and its candidates are recorded, never
        probed or retired (-1); batch is the interface (one call per type).

    Raises:
        FalsifierError: ``batch_not_open``, ``no_candidates`` or ``invalid_record``.
    """
    from tap_grid.models import Batch, BatchStatus

    if batch.status != BatchStatus.OPEN:
        raise FalsifierError("batch_not_open", f"cannot record verdicts on a batch in status {batch.status!r}")
    candidates = candidates_from(batch)
    context = FalsifyContext(batch_id=str(batch.entity_id), statement=completeness_of(batch), extra=dict(extra or {}))
    record = _dispatch(candidates, context)
    try:
        validate_json(record, _SCHEMA, source=f"verdicts on batch {batch.entity_id}")
    except JsonFileError as exc:
        raise FalsifierError("invalid_record", f"{exc} (at {exc.location})") from exc
    # The probes took time; the batch may have been closed or failed meanwhile. The write
    # re-reads the row under a lock and decides on the committed status, not the one read
    # before the probes ran.
    with transaction.atomic():
        locked = cast(Batch, Batch.objects.select_for_update().get(pk=batch.pk))  # django-stubs: manager typing
        if locked.status != BatchStatus.OPEN:
            raise FalsifierError(
                "batch_not_open", f"batch {batch.entity_id} left status open during the probes (now {locked.status!r})"
            )
        metadata = dict(locked.metadata or {})
        metadata[METADATA_KEY] = record
        locked.metadata = metadata
        locked.save(update_fields=["metadata"])
    batch.metadata = metadata
    logger.info(
        "[2eb2] verdicts recorded on batch %s: %d candidate(s), %d judged, %d not reconcilable, authority off",
        batch.entity_id,
        len(candidates),
        sum(1 for e in record["entries"] if e["outcome"] == JUDGED),
        sum(1 for e in record["entries"] if e["outcome"] == NOT_RECONCILABLE),
    )
    return record


def _dispatch(candidates: Iterable[Candidate], context: FalsifyContext) -> dict[str, Any]:
    by_type: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        by_type.setdefault(candidate.entity_type, []).append(candidate)
    entries: list[dict[str, Any]] = []
    calls: dict[str, int] = {}
    stray: dict[str, int] = {}
    not_reconcilable: list[str] = []
    for entity_type, group in by_type.items():
        falsifier = get_falsifier(entity_type)
        if falsifier is None:
            not_reconcilable.append(entity_type)
            logger.info(
                "[c93b] no falsifier for %s: %d candidate(s) recorded not reconcilable", entity_type, len(group)
            )
            entries.extend(_entry(c, outcome=NOT_RECONCILABLE) for c in group)
            continue
        calls[entity_type] = 1
        verdicts, strays = _judge(falsifier, group, context)
        if strays:
            stray[entity_type] = strays
        entries.extend(_entry(c, outcome=JUDGED, verdict=verdicts[c.entity_id]) for c in group)
    entries.sort(key=lambda e: (e["surface"], e["entity_type"], e["entity_id"]))
    return {
        "recorded_at": datetime.now(UTC).isoformat(),
        "authority": "off",
        "candidates": len(entries),
        "calls": calls,
        "stray_answers": stray,
        "not_reconcilable": sorted(not_reconcilable),
        "entries": entries,
    }


def _judge(
    falsifier: Falsifier, group: list[Candidate], context: FalsifyContext
) -> tuple[dict[uuid.UUID, Verdict], int]:
    """One call per type. A falsifier that raises, answers for the wrong set, answers twice for one
    candidate, or returns a verdict its own evidence does not yield gets ``UNDETERMINED(errored)``
    for the candidate concerned: fail closed, retire nothing. Returns the verdicts and the number
    of stray answers (for ids that were not asked)."""
    name = type(falsifier).__name__
    try:
        answers = list(falsifier.batch_falsify(list(group), context))
    except Exception as exc:  # noqa: BLE001 — a plugin's probe failing must not fail the run record
        detail = scrub(f"{type(exc).__name__}: {exc}")
        logger.warning("[7f78] falsifier %s raised: %s", name, detail)
        return {c.entity_id: _errored(c, detail) for c in group}, 0
    asked = {c.entity_id for c in group}
    by_id: dict[uuid.UUID, list[Verdict]] = {}
    stray = 0
    for answer in answers:
        if not isinstance(answer, Verdict) or answer.entity_id not in asked:
            stray += 1
            continue
        by_id.setdefault(answer.entity_id, []).append(answer)
    if stray:
        logger.warning("[8a89] falsifier %s returned %d answer(s) for candidates it was not asked about", name, stray)
    out: dict[uuid.UUID, Verdict] = {}
    for candidate in group:
        got = by_id.get(candidate.entity_id, [])
        if not got:
            logger.warning("[991a] falsifier %s returned no verdict for %s", name, candidate.entity_id)
            verdict = _errored(candidate, "the falsifier returned no verdict for this candidate")
        elif len(got) > 1:
            logger.warning("[fb9e] falsifier %s returned %d verdicts for %s", name, len(got), candidate.entity_id)
            verdict = _errored(
                candidate,
                f"the falsifier returned {len(got)} verdicts for this candidate: " + ", ".join(v.verdict for v in got),
            )
        elif (why := unsupported(got[0], interval_first=candidate.interval_first)) is not None:
            logger.warning("[31b6] falsifier %s: verdict for %s rejected: %s", name, candidate.entity_id, why)
            verdict = _errored(
                candidate, f"verdict {got[0].verdict} rejected: {why}", probe=got[0].probe, expected=got[0].expected
            )
        else:
            verdict = got[0]
        out[candidate.entity_id] = verdict
    return out, stray


def unsupported(verdict: Verdict, *, interval_first: datetime | None = None) -> str | None:
    """Why a returned verdict is not what its own evidence yields, or None when it is.

    Core cannot re-run a plugin's probe, but it holds both sides the plugin compared — the
    probe summary and the grid-side terms — and re-derives the classification from them. A
    verdict is refused when: it carries no probe (only ``UNDETERMINED`` may say "I could not
    look"); the probe failed and the verdict is not ``UNDETERMINED`` with that reason; the probe
    found nothing and the verdict is not ``DROPPED_FROM_OBSERVATION``; the probe found the object
    but no grid-side terms are recorded (nothing to compare against); or the probe found the
    object and ``classify`` on the recorded sides yields a different verdict, kind or cause. A
    refused verdict is recorded ``UNDETERMINED(errored)`` with the reason: fail closed.
    """
    probe = verdict.probe
    if probe is None:
        return None if verdict.verdict == UNDETERMINED else "no probe evidence recorded"
    status = probe.get("status")
    if status in UNDETERMINED_REASONS:
        if verdict.verdict == UNDETERMINED and verdict.reason == status:
            return None
        return f"probe could not answer ({status}), verdict says {verdict.verdict}({verdict.reason})"
    if status == "not_found":
        if verdict.verdict == DROPPED_FROM_OBSERVATION:
            return None
        return f"probe found nothing, verdict says {verdict.verdict}"
    if status != "found":
        return f"probe status {status!r} is not in {sorted(PROBE_STATUSES)}"
    if verdict.expected is None or not verdict.expected.get("source_id"):
        return "probe found the object but no grid-side terms are recorded to compare it against"
    derived = classify(_expected_of(verdict.expected), _probe_of(probe), interval_first=interval_first)
    claimed = {"verdict": verdict.verdict}
    if verdict.kind is not None:
        claimed["kind"] = verdict.kind
    if verdict.cause is not None:
        claimed["cause"] = verdict.cause
    if derived != claimed:
        return f"the recorded sides yield {_describe(derived)}, verdict says {_describe(claimed)}"
    return None


def _describe(fields: Mapping[str, Any]) -> str:
    qualifier = fields.get("kind") or fields.get("cause") or fields.get("reason")
    return f"{fields['verdict']}({qualifier})" if qualifier else str(fields["verdict"])


def _expected_of(summary: Mapping[str, Any]) -> Expected:
    return Expected(source_id=str(summary["source_id"]), owner=summary.get("owner"), name=summary.get("name"))


def _probe_of(summary: Mapping[str, Any]) -> Probe:
    created = summary.get("created_at")
    try:
        created_at = datetime.fromisoformat(created) if created else None
    except ValueError:
        created_at = None
    return Probe(
        status=summary.get("status"),  # type: ignore[arg-type]
        source_id=summary.get("source_id"),
        owner=summary.get("owner"),
        name=summary.get("name"),
        created_at=created_at,
        detail=str(summary.get("detail") or ""),
    )


def _errored(
    candidate: Candidate,
    detail: str,
    *,
    probe: dict[str, Any] | None = None,
    expected: dict[str, Any] | None = None,
) -> Verdict:
    return Verdict(
        entity_id=candidate.entity_id,
        verdict=UNDETERMINED,
        reason="errored",
        probe=probe,
        expected=expected,
        note=scrub(detail),
    )


def _entry(candidate: Candidate, *, outcome: str, verdict: Verdict | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "entity_id": str(candidate.entity_id),
        "entity_type": candidate.entity_type,
        "candidate_reason": candidate.reason,
        "surface": candidate.surface,
        "outcome": outcome,
        "verdict": None,
        "reason": None,
        "kind": None,
        "cause": None,
        "statement": None,
        "probe": None,
        "expected": None,
        "note": "",
        "would": {"write": "none", "home": "run_record"},
    }
    if verdict is None:
        entry["note"] = f"no falsifier is registered for {candidate.entity_type}: not re-observed, never retired"
        return entry
    entry.update(
        verdict=verdict.verdict,
        reason=verdict.reason,
        kind=verdict.kind,
        cause=verdict.cause,
        statement=PRESENT_STATEMENT if verdict.verdict == PRESENT_AT_PROBE else None,
        probe=verdict.probe,
        expected=verdict.expected,
        note=scrub(verdict.note),
        would=would(verdict),
    )
    return entry


__all__ = [
    "CAUSE_CREATED_AFTER",
    "CAUSE_INDETERMINATE",
    "DROPPED_FROM_OBSERVATION",
    "JUDGED",
    "METADATA_KEY",
    "NOT_RECONCILABLE",
    "PRESENT_AT_PROBE",
    "PRESENT_CAUSES",
    "PRESENT_STATEMENT",
    "REIDENTIFIED",
    "RELOCATED",
    "RELOCATED_KINDS",
    "RELOCATED_RENAMED",
    "RELOCATED_TRANSFERRED",
    "UNDETERMINED",
    "UNDETERMINED_REASONS",
    "VERDICTS",
    "Candidate",
    "Expected",
    "Falsifier",
    "FalsifierError",
    "FalsifyContext",
    "Probe",
    "Verdict",
    "candidates_from",
    "classify",
    "falsify_candidates",
    "get_falsifier",
    "register_falsifier",
    "registered_falsifiers",
    "scrub",
    "unregister_falsifier",
    "unsupported",
    "verdict_from_probe",
    "verdicts_of",
    "would",
]
