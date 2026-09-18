"""The cascade confirmation corpus, run (Issue# 578 - tap).

One pytest case per scenario. A scenario passes when (a) exactly the expected nodes and
edges are tombstoned, (b) nothing else in the grid changed, and (c) the records say what
they should — or, on an expected refusal, nothing changed at all. A scenario marked
``pending`` on a named issue is a strict xfail: it must fail until that fix lands.
"""

from __future__ import annotations

from typing import Any

import pytest

from tap_grid.cascade_corpus.loader import Scenario, load_corpus
from tap_grid.cascade_corpus.runner import apply_blocks, apply_containment, build, run

SCENARIOS = load_corpus()


def _params() -> list[Any]:
    out = []
    for s in SCENARIOS:
        marks = [pytest.mark.cascade_corpus]
        if s.pending:
            marks.append(pytest.mark.xfail(strict=True, reason=f"pending {s.pending}"))
        out.append(pytest.param(s, id=s.id, marks=marks))
    return out


@pytest.mark.spec("req-grid-cascade-corpus-format-5")
def test_corpus_is_not_empty() -> None:
    assert len(SCENARIOS) >= 50, f"{len(SCENARIOS)} scenarios; the corpus promises at least 50"


@pytest.mark.spec("req-grid-cascade-corpus-format-5")
def test_every_family_present() -> None:
    assert {s.family for s in SCENARIOS} >= {"depth", "loops", "blocks", "limits", "records"}


@pytest.mark.spec("req-grid-cascade-corpus-format-3")
def test_every_covers_entry_names_a_requirement_that_exists() -> None:
    """A citation that does not resolve reads as verification: every RID a scenario claims
    to cover must be a row in the delete spec, and the check must have read that spec."""
    import re
    from pathlib import Path

    import tap_grid

    spec = (Path(tap_grid.__file__).resolve().parent / "specs" / "spec-grid-service-delete.md").read_text(
        encoding="utf-8"
    )
    known = set(re.findall(r"\| (req-grid-service-delete[a-z0-9-]*) \|", spec))
    assert "req-grid-service-delete-cascade-1" in known, "the scan read nothing"
    unknown = sorted({rid for s in SCENARIOS for rid in s.covers if rid not in known})
    assert unknown == [], f"scenarios cite requirements the spec does not have: {unknown}"


@pytest.mark.spec("req-grid-cascade-corpus-format-5")
def test_coverage_matrix() -> None:
    """Which requirement rows the corpus exercises, and how many scenarios each — the derived
    traceability view a reader asks for first."""
    from collections import Counter

    matrix = Counter(rid for s in SCENARIOS for rid in s.covers)
    for rid in (
        "req-grid-service-delete-cascade-1",
        "req-grid-service-delete-cascade-2",
        "req-grid-service-delete-cascade-3",
        "req-grid-service-delete-cascade-4",
        "req-grid-service-delete-cascade-11",
        "req-grid-service-delete-cascade-13",
        "req-grid-service-delete-cascade-14",
        "req-grid-service-delete-reason-1",
        "req-grid-service-delete-reason-3",
        "req-grid-service-delete-reason-4",
    ):
        assert matrix[rid] >= 2, f"{rid} is covered by {matrix[rid]} scenario(s); the corpus promises at least two"


@pytest.mark.django_db
@pytest.mark.spec("req-grid-cascade-corpus-format-1")
@pytest.mark.spec("req-grid-cascade-corpus-format-2")
@pytest.mark.spec("req-grid-cascade-corpus-format-4")
@pytest.mark.spec("req-grid-cascade-corpus-runner-1")
@pytest.mark.spec("req-grid-cascade-corpus-runner-2")
@pytest.mark.spec("req-grid-cascade-corpus-runner-3")
@pytest.mark.spec("req-grid-cascade-corpus-runner-4")
@pytest.mark.spec("req-grid-cascade-corpus-oracle-1")
@pytest.mark.spec("req-grid-cascade-corpus-oracle-2")
@pytest.mark.spec("req-grid-cascade-corpus-oracle-3")
@pytest.mark.spec("req-grid-cascade-corpus-nongoals-1")
@pytest.mark.parametrize("scenario", _params())
def test_scenario(scenario: Scenario, monkeypatch: pytest.MonkeyPatch) -> None:
    apply_containment(scenario, monkeypatch)
    built = build(scenario)
    apply_blocks(scenario, monkeypatch)
    failures = run(scenario, built)
    assert not failures, (
        f"{scenario.id}\n  "
        + "\n  ".join(failures)
        + (f"\n  note: {scenario.expected['note']}" if scenario.expected.get("note") else "")
    )
