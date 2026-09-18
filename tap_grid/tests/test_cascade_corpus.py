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
from tap_grid.cascade_corpus.runner import apply_declarations, build, run

SCENARIOS = load_corpus()


def _params() -> list[Any]:
    out = []
    for s in SCENARIOS:
        marks = [pytest.mark.cascade_corpus]
        if s.pending:
            marks.append(pytest.mark.xfail(strict=True, reason=f"pending {s.pending}"))
        out.append(pytest.param(s, id=s.id, marks=marks))
    return out


def test_corpus_is_not_empty() -> None:
    assert len(SCENARIOS) >= 50, f"{len(SCENARIOS)} scenarios; the corpus promises at least 50"


def test_every_family_present() -> None:
    assert {s.family for s in SCENARIOS} >= {"depth", "loops", "blocks", "limits", "records"}


@pytest.mark.django_db
@pytest.mark.parametrize("scenario", _params())
def test_scenario(scenario: Scenario, monkeypatch: pytest.MonkeyPatch) -> None:
    apply_declarations(scenario, monkeypatch)
    built = build(scenario)
    failures = run(scenario, built)
    assert not failures, (
        f"{scenario.id}\n  "
        + "\n  ".join(failures)
        + (f"\n  note: {scenario.expected['note']}" if scenario.expected.get("note") else "")
    )
