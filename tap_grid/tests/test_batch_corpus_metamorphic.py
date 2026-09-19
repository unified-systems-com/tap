"""Metamorphic checks on the batch playground (Issue# 613 - tap): transformations the import
contract says must not change the logical outcome — rename every ref label consistently, add a
disconnected sentinel to the grid, reuse a label from another document — leave the model's
answer invariant modulo ids, and a sample of them is re-run on the real database. The
transformations the contract does NOT promise are named here too and deliberately not applied:
reordering batches (each is its own transaction and the file is executed in order), splitting an
atomic batch, and swapping an explicit id for a ref (a different addressing contract).
"""

from __future__ import annotations

import copy
import re
from typing import Any

import pytest

from tap_grid.batch_corpus import model_oracle
from tap_grid.batch_corpus.loader import Scenario, load_corpus, load_file
from tap_grid.batch_corpus.runner import build, run

SCENARIOS = [s for s in load_corpus() if s.pending is None]
#: the scenarios run on the database under each transformation (the model covers them all)
DB_SAMPLE = (
    "refs::an edge between two ref nodes lands on their assigned ids",
    "rewriting::a diamond of four refs lands every edge on the right pair",
    "collision::a ref that resolves to a row this batch also addresses by id is refused, ref first (Issue# 606 - tap)",
    "encounters::two observations share one subject and one encounter through refs; every edge lands on the shared rows",
    "observations::empty grid: the first observation mints, the second finds it",
)


def _refs(raw: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for imp in raw["imports"]:
        for b in imp["batches"]:
            out |= {o["ref"] for o in list(b.get("nodes", ())) + list(b.get("edges", ())) if "ref" in o}
    return out


def _rename(raw: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """Rename ref labels everywhere a name appears: refs, endpoints, targets, expectations."""
    out = copy.deepcopy(raw)

    def sub(name: Any) -> Any:
        return mapping.get(name, name) if isinstance(name, str) else name

    for imp in out["imports"]:
        for b in imp["batches"]:
            for o in list(b.get("nodes", ())) + list(b.get("edges", ())):
                for key in ("ref", "from", "to", "from_ref", "to_ref"):
                    if key in o:
                        o[key] = sub(o[key])
            for section in ("deletes", "purges"):
                for t in (b.get(section) or {}).get("nodes", []) + (b.get(section) or {}).get("edges", []):
                    t["id"] = sub(t["id"])
    exp = out["expected"]
    for key in ("live", "tombstoned", "dimensions", "fields", "events"):
        if key in exp:
            exp[key] = {sub(k): v for k, v in exp[key].items()}
    exp["absent"] = [sub(n) for n in exp["absent"]]
    if "resolves" in exp:
        exp["resolves"] = {sub(k): sub(v) for k, v in exp["resolves"].items()}
    out["phantoms"] = [sub(n) for n in out.get("phantoms", [])]
    return out


def _outcome_modulo_names(outcome: model_oracle.Outcome, mapping: dict[str, str]) -> Any:
    """The model's answer with every name mapped back through ``mapping``, for comparison."""
    back = {v: k for k, v in mapping.items()}

    def sub(name: str) -> str:
        return back.get(name, name)

    return (
        [
            (
                i.success,
                sorted(i.errors),
                sorted(i.warnings),
                i.batches,
                {sub(k): sub(v) for k, v in i.resolves.items()},
            )
            for i in outcome.imports
        ],
        {sub(k): v for k, v in outcome.live().items()},
        {sub(k): v for k, v in outcome.tombstoned().items()},
        {(sub(n), t): c for (n, t), c in outcome.event_delta().items()},
    )


def _label_map(scenario: Scenario) -> dict[str, str]:
    """A consistent renaming of every ref label; labels are chosen to collide with no other name."""
    taken = set(scenario.universe) | {b["name"] for imp in scenario.imports for b in imp["batches"]}
    mapping: dict[str, str] = {}
    for i, ref in enumerate(sorted(_refs(scenario.raw))):
        new = f"lid{i}"
        while new in taken:
            new += "x"
        mapping[ref] = new
        taken.add(new)
    return mapping


@pytest.mark.batch_corpus
@pytest.mark.spec("req-grid-batch-corpus-oracle-4")
class TestModelInvariance:
    @pytest.mark.parametrize("scenario", [pytest.param(s, id=s.id) for s in SCENARIOS if _refs(s.raw)])
    def test_renaming_every_ref_label_leaves_the_outcome_invariant(self, scenario: Scenario) -> None:
        mapping = _label_map(scenario)
        renamed = model_oracle.run(_rename(scenario.raw, mapping))
        assert _outcome_modulo_names(renamed, mapping) == _outcome_modulo_names(scenario.oracle, {})

    @pytest.mark.parametrize("scenario", [pytest.param(s, id=s.id) for s in SCENARIOS])
    def test_a_disconnected_sentinel_in_the_grid_changes_nothing_and_is_untouched(self, scenario: Scenario) -> None:
        raw = copy.deepcopy(scenario.raw)
        raw["grid"]["nodes"].append(
            {"name": "sentinel_zz", "type": "grid_fixtures__leaf", "props": {"name": "sentinel"}}
        )
        with_sentinel = model_oracle.run(raw)
        assert with_sentinel.live().get("sentinel_zz") == 1
        assert {k: v for k, v in with_sentinel.live().items() if k != "sentinel_zz"} == scenario.oracle.live()
        assert with_sentinel.tombstoned() == scenario.oracle.tombstoned()
        assert [(i.success, sorted(i.errors), i.batches) for i in with_sentinel.imports] == [
            (i.success, sorted(i.errors), i.batches) for i in scenario.oracle.imports
        ]

    def test_reusing_a_label_from_another_document_binds_afresh(self) -> None:
        """Two documents, one label, two objects: the same as two labels (labels never leak)."""
        base = next(
            s
            for s in SCENARIOS
            if s.id
            == "replay::a ref label reused in a later document for another object is a fresh binding: labels never leak between requests"
        )
        raw = copy.deepcopy(base.raw)
        # the corpus keeps names scenario-global, so the reuse is expressed through the model directly
        second = raw["imports"][1]["batches"][0]["nodes"][0]
        second["ref"] = "p"
        raw["expected"]["live"] = {"p": 1}  # the model names the second row by its (reused) label
        with pytest.raises(model_oracle.ModelError, match="must carry a new name"):
            model_oracle.run(raw)
        # The runner's contract is the one that matters: the same label in another document is
        # sent verbatim and the importer binds it to a new row — the shaped scenario proves it
        # with two labels; the DB test below proves it with one.

    def test_the_transformations_the_contract_does_not_promise_are_not_applied(self) -> None:
        """Batch reordering, splitting an atomic batch and id-for-ref swaps change the outcome by
        design; a reader looking for them here finds the reason, not a test."""
        multibatch = next(
            s for s in SCENARIOS if s.id.startswith("multibatch::a later batch replaces a node an earlier batch")
        )
        raw = copy.deepcopy(multibatch.raw)
        raw["imports"][0]["batches"].reverse()
        reordered = model_oracle.run(raw)
        assert reordered.live() != multibatch.oracle.live() or any(
            i.errors for i in reordered.imports
        ), "reordering these batches would have to change something for the non-promise to be real"


@pytest.mark.batch_corpus
@pytest.mark.django_db
@pytest.mark.spec("req-grid-batch-corpus-oracle-4")
class TestDatabaseInvariance:
    @pytest.mark.parametrize("scenario_id", DB_SAMPLE)
    def test_renamed_labels_hold_on_the_database(self, scenario_id: str, tmp_path: Any) -> None:
        scenario = next(s for s in SCENARIOS if s.id == scenario_id)
        renamed = _rename(scenario.raw, _label_map(scenario))
        renamed["name"] = scenario.name + " (renamed labels)"
        path = tmp_path / "renamed.batch.json"
        path.write_text(
            __import__("json").dumps({"family": scenario.family, "description": "metamorphic", "scenarios": [renamed]})
        )
        [transformed] = load_file(path)
        failures = run(transformed, build(transformed))
        assert not failures, "\\n".join(failures)

    def test_the_same_label_in_two_documents_binds_two_rows(self) -> None:
        """The label-reuse transformation on the database: the runner keeps the second document's
        binding apart from the first's, and both rows exist with fresh, distinct ids."""
        base = next(s for s in SCENARIOS if s.id.startswith("replay::a ref label reused"))
        raw = copy.deepcopy(base.raw)
        raw["name"] = base.name + " (one label)"
        raw["imports"][1]["batches"][0]["nodes"][0][
            "ref"
        ] = "q"  # keep the corpus's naming rule; the wire label is set below
        scenario = load_file(_write(raw, base.family))[0]
        built = build(scenario)
        from tap_grid.batch_corpus import runner

        docs = [runner._document(scenario, imp, built) for imp in scenario.imports]
        for doc in docs:
            doc["batches"][0]["nodes"][0]["entity"]["ref"] = "it"  # the SAME label on the wire for both objects
        from tap_grid.grift import grift_import

        first, second = (grift_import(doc) for doc in docs)
        assert first.success and second.success
        a = first.imported_batches[0].resolved_refs["it"]
        b = second.imported_batches[0].resolved_refs["it"]
        assert a != b and re.fullmatch(r"[0-9a-f-]{36}", a) and re.fullmatch(r"[0-9a-f-]{36}", b)


def _write(raw: dict[str, Any], family: str) -> Any:
    import json
    import tempfile
    from pathlib import Path

    path = Path(tempfile.mkdtemp()) / "reuse.batch.json"
    path.write_text(json.dumps({"family": family, "description": "metamorphic", "scenarios": [raw]}))
    return path
