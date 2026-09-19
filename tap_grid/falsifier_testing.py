"""The four proof cases every falsifier ships (req-grid-reconcile-falsifier-6), and a fake source
to run them against.

A plugin's falsifier probes a real source through the plugin's own client; its tests hand
that client a fake and run :func:`run_four_cases`, which calls ``batch_falsify`` ONCE with the
four candidates (present, dropped, forbidden, reidentified) and asserts each verdict. The
plugin arranges its fake so each candidate meets its situation. :class:`FakeSource` and
:class:`FakeSourceFalsifier` are the reference pair: a source that answers probes from a
table, and the falsifier over it that core's own tests use.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from tap_grid.falsifiers import (
    DROPPED_FROM_OBSERVATION,
    PRESENT_AT_PROBE,
    REIDENTIFIED,
    UNDETERMINED,
    Candidate,
    Expected,
    Falsifier,
    FalsifyContext,
    Probe,
    Verdict,
    verdict_from_probe,
)

CASE_PRESENT = "present"
CASE_DROPPED = "dropped"
CASE_FORBIDDEN = "forbidden"
CASE_REIDENTIFIED = "reidentified"
FOUR_CASES: tuple[str, ...] = (CASE_PRESENT, CASE_DROPPED, CASE_FORBIDDEN, CASE_REIDENTIFIED)


@dataclass
class FakeSource:
    """A source that answers probes from a table keyed by entity id, and remembers what the grid
    holds for each entity in source terms. ``calls`` counts probes, so a test can assert one
    aliased probe per batch rather than one per candidate."""

    expected: dict[uuid.UUID, Expected] = field(default_factory=dict)
    answers: dict[uuid.UUID, Probe] = field(default_factory=dict)
    calls: int = 0

    def holds(self, entity_id: uuid.UUID, source_id: str, *, owner: str | None = None, name: str | None = None) -> None:
        self.expected[entity_id] = Expected(source_id=source_id, owner=owner, name=name)

    def present(self, entity_id: uuid.UUID, *, created_at: datetime | None = None) -> None:
        exp = self.expected[entity_id]
        self.answers[entity_id] = Probe("found", exp.source_id, exp.owner, exp.name, created_at=created_at)

    def dropped(self, entity_id: uuid.UUID) -> None:
        self.answers[entity_id] = Probe("not_found", detail="404")

    def forbidden(self, entity_id: uuid.UUID) -> None:
        self.answers[entity_id] = Probe("forbidden", detail="403")

    def reidentified(self, entity_id: uuid.UUID, new_source_id: str) -> None:
        exp = self.expected[entity_id]
        self.answers[entity_id] = Probe("found", new_source_id, exp.owner, exp.name)

    def renamed(self, entity_id: uuid.UUID, new_name: str) -> None:
        exp = self.expected[entity_id]
        self.answers[entity_id] = Probe("found", exp.source_id, exp.owner, new_name)

    def transferred(self, entity_id: uuid.UUID, new_owner: str) -> None:
        exp = self.expected[entity_id]
        self.answers[entity_id] = Probe("found", exp.source_id, new_owner, exp.name)

    def undetermined(self, entity_id: uuid.UUID, reason: str) -> None:
        self.answers[entity_id] = Probe(reason, detail=reason)  # type: ignore[arg-type]

    def probe_all(self, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Probe]:
        """One aliased probe for the whole batch."""
        self.calls += 1
        return {i: self.answers.get(i, Probe("errored", detail="no answer configured")) for i in ids}


class FakeSourceFalsifier(Falsifier):
    """The reference falsifier: one probe call per batch, classification derived by core."""

    def __init__(self, source: FakeSource) -> None:
        self.source = source

    def batch_falsify(self, candidates: Sequence[Candidate], context: FalsifyContext) -> list[Verdict]:
        probes = self.source.probe_all([c.entity_id for c in candidates])
        out: list[Verdict] = []
        for candidate in candidates:
            expected = self.source.expected.get(candidate.entity_id)
            if expected is None:
                out.append(Verdict(candidate.entity_id, UNDETERMINED, reason="scope_unknown", note="not held"))
                continue
            out.append(verdict_from_probe(candidate, expected, probes[candidate.entity_id]))
        return out


def _check(condition: bool, message: str) -> None:
    """The harness's own assertion: raised explicitly so it survives ``python -O`` and reads as a
    proof step, not a debugging aid."""
    if not condition:
        raise AssertionError(message)


EXPECTED_VERDICTS: dict[str, tuple[str, str | None]] = {
    CASE_PRESENT: (PRESENT_AT_PROBE, None),
    CASE_DROPPED: (DROPPED_FROM_OBSERVATION, None),
    CASE_FORBIDDEN: (UNDETERMINED, "forbidden"),
    CASE_REIDENTIFIED: (REIDENTIFIED, None),
}


def run_four_cases(
    falsifier: Falsifier, candidates: dict[str, Candidate], context: FalsifyContext
) -> dict[str, Verdict]:
    """Call ``batch_falsify`` once with the four case candidates and assert each verdict.

    ``candidates`` maps each of :data:`FOUR_CASES` to the candidate the falsifier's fake source
    has arranged for that situation. Returns the verdicts by case for further assertions.
    """
    missing = [case for case in FOUR_CASES if case not in candidates]
    _check(not missing, f"the four cases need a candidate each; missing {missing}")
    ordered = [candidates[case] for case in FOUR_CASES]
    verdicts = {v.entity_id: v for v in falsifier.batch_falsify(ordered, context)}
    by_case: dict[str, Verdict] = {}
    for case in FOUR_CASES:
        candidate = candidates[case]
        verdict = verdicts.get(candidate.entity_id)
        if verdict is None:
            raise AssertionError(f"{case}: no verdict returned for {candidate.entity_id}")
        want, want_reason = EXPECTED_VERDICTS[case]
        _check(verdict.verdict == want, f"{case}: expected {want}, got {verdict.verdict} ({verdict.note})")
        if want_reason is not None:
            _check(verdict.reason == want_reason, f"{case}: expected reason {want_reason}, got {verdict.reason}")
        by_case[case] = verdict
    return by_case


__all__ = [
    "CASE_DROPPED",
    "CASE_FORBIDDEN",
    "CASE_PRESENT",
    "CASE_REIDENTIFIED",
    "EXPECTED_VERDICTS",
    "FOUR_CASES",
    "FakeSource",
    "FakeSourceFalsifier",
    "run_four_cases",
]
