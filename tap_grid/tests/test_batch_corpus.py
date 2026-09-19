"""The batch playground, run (Issue# 603 - tap).

One pytest case per scenario. A scenario passes when (a) exactly the expected rows exist
afterwards with the expected liveness, version and spine name, (b) nothing else in the grid
changed and no unexpected entity or batch row appeared, and (c) the records and every import
result say what they should. A scenario marked ``pending`` on a named issue is an expected
failure only when those assertions mismatch; a fixture error is a hard failure, and a pending
scenario that holds fails as a stale tag.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from tap_grid.batch_corpus import model_oracle
from tap_grid.batch_corpus.loader import Scenario, load_corpus
from tap_grid.batch_corpus.runner import build, run
from tap_grid.cascade_corpus.timing import live_edges_onto_tombstones

SCENARIOS = load_corpus()
FAMILIES = {"identity", "refs", "removals", "occ", "dangling", "multibatch", "spine", "retired"} | {
    # the second pass (Issue# 613 - tap): families and the five authored datasets
    "reload",
    "collision",
    "rewriting",
    "provenance",
    "atomic",
    "replay",
    "hotlink",
    "observations",
    "encounters",
    "inventory",
    "chain",
    "sightings",
}


def _params() -> list[Any]:
    return [pytest.param(s, id=s.id, marks=[pytest.mark.batch_corpus]) for s in SCENARIOS]


@pytest.mark.spec("req-grid-batch-corpus-format-5")
def test_corpus_is_not_empty() -> None:
    assert len(SCENARIOS) >= 50, f"{len(SCENARIOS)} scenarios; the corpus promises at least 50"


FIRST_PASS = {"identity", "refs", "removals", "occ", "dangling", "multibatch", "spine", "retired"}


@pytest.mark.spec("req-grid-batch-corpus-format-5")
def test_every_family_present_with_at_least_five() -> None:
    per_family = Counter(s.family for s in SCENARIOS)
    assert set(per_family) >= FAMILIES, f"missing families: {sorted(FAMILIES - set(per_family))}"
    thin = {f: n for f, n in per_family.items() if n < (5 if f in FIRST_PASS else 3)}
    assert not thin, f"families thinner than the corpus promises: {thin}"


@pytest.mark.spec("req-grid-batch-corpus-format-6")
def test_the_second_pass_issue_shapes_are_scenarios() -> None:
    """Every issue the second pass classifies has a scenario naming it: the fixed ones expect the
    fix (no tag), the open ones are verified-pending on exactly that issue, and #322 is pinned as
    today's contract with the question named in its note."""
    by_issue = {n: [s for s in SCENARIOS if f"Issue# {n} - tap" in s.name] for n in (606, 607, 608, 351, 609, 322)}
    for n, found in by_issue.items():
        assert found, f"Issue# {n} - tap has no scenario"
    assert all(s.pending is None for s in by_issue[606]), "606 is fixed (PR# 604 - tap): its scenarios expect the fix"
    for n in (607, 608, 351, 609):
        assert all(
            s.pending == f"unified-systems-com/tap#{n}" for s in by_issue[n]
        ), f"{n} scenarios must be pending on it"
    assert all(s.pending is None and "322" in s.expected.get("note", "") for s in by_issue[322])


@pytest.mark.spec("req-grid-batch-corpus-format-3")
def test_every_covers_entry_names_a_requirement_that_exists() -> None:
    """A citation that does not resolve reads as verification: every RID a scenario claims to
    cover must be a row in one of the specs the corpus reads, and the scan must have read them."""
    import tap_grid
    import tap_web

    specs = [
        Path(tap_grid.__file__).resolve().parent / "specs" / name
        for name in (
            "spec-grid-import-grift.md",
            "spec-grift-v0.md",
            "spec-grid-entity.md",
            "spec-grid-service-delete.md",
        )
    ] + [Path(tap_web.__file__).resolve().parent / "specs" / "spec-web-page.md"]
    known: set[str] = set()
    for spec in specs:
        known |= set(re.findall(r"\| (req-[a-z0-9-]+) \|", spec.read_text(encoding="utf-8")))
    assert {
        "req-grid-import-grift-identity-3",
        "req-grid-entity-natural-key-13",
        "req-web-page-landing-14",
    } <= known, "the scan read nothing"
    unknown = sorted({rid for s in SCENARIOS for rid in s.covers if rid not in known})
    assert unknown == [], f"scenarios cite requirements the specs do not have: {unknown}"


@pytest.mark.spec("req-grid-batch-corpus-format-5")
def test_coverage_matrix() -> None:
    """Which requirement rows the corpus exercises, and how many scenarios each."""
    matrix = Counter(rid for s in SCENARIOS for rid in s.covers)
    for rid in (
        "req-grid-import-grift-identity-1",
        "req-grid-import-grift-identity-3",
        "req-grid-import-grift-preflight-2",
        "req-grid-import-grift-batch",
        "req-grid-import-grift-removals-1",
        "req-grid-import-grift-removal-preflight-1",
        "req-grid-import-grift-dangling-1",
        "req-grid-import-grift-occ-2",
        "req-grift-concurrency-version-4",
        "req-grid-entity-natural-key-9",
        "req-grid-entity-natural-key-13",
        "req-web-page-landing-14",
    ):
        assert matrix[rid] >= 2, f"{rid} is covered by {matrix[rid]} scenario(s); the corpus promises at least two"


@pytest.mark.spec("req-grid-batch-corpus-format-4")
def test_the_602_gap_is_a_scenario() -> None:
    """Issue# 602 - tap was found by a question, not a test; the corpus now asks it."""
    pending = [s for s in SCENARIOS if "Issue# 602 - tap" in s.name]
    assert len(pending) >= 2, "the intra-batch duplicate scenarios are missing"
    assert all(
        s.oracle.imports[0].errors == [("duplicate_entity_id", s.oracle.imports[0].errors[0][1])] for s in pending
    )


@pytest.mark.django_db
@pytest.mark.spec("req-grid-batch-corpus-format-1")
@pytest.mark.spec("req-grid-batch-corpus-format-2")
@pytest.mark.spec("req-grid-batch-corpus-format-4")
@pytest.mark.spec("req-grid-batch-corpus-runner-1")
@pytest.mark.spec("req-grid-batch-corpus-runner-2")
@pytest.mark.spec("req-grid-batch-corpus-runner-3")
@pytest.mark.spec("req-grid-batch-corpus-runner-4")
@pytest.mark.spec("req-grid-batch-corpus-oracle-1")
@pytest.mark.spec("req-grid-batch-corpus-oracle-3")
@pytest.mark.spec("req-grid-batch-corpus-nongoals-1")
@pytest.mark.parametrize("scenario", _params())
def test_scenario(scenario: Scenario, monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_grid.registry import get_model_class

    # `grid.cascaded` cascades along the fixture containment edge the cascade corpus declares.
    monkeypatch.setattr(
        get_model_class(model_oracle.NESTS_OWNER), "CONTAINMENT_EDGES", (model_oracle.NESTS,), raising=False
    )
    built = build(scenario)  # a BuildError here is a hard failure whatever `pending` says
    failures = run(scenario, built)
    # The tombstone invariant holds at every committed state (Issue# 609 - tap, ruled 2026-09-18).
    onto = live_edges_onto_tombstones()
    if onto:
        failures.append(f"live edges point at a tombstone: {[built.ref_of(e) for e in onto]}")
    report = f"{scenario.id}\n  " + "\n  ".join(failures)
    if scenario.expected.get("note"):
        report += f"\n  note: {scenario.expected['note']}"
    if scenario.pending is None:
        assert not failures, report
    elif failures:
        pytest.xfail(f"pending {scenario.pending} — verified in-body: {report}")
    else:
        pytest.fail(f"{scenario.id} holds but is still tagged pending {scenario.pending}: remove the tag")
