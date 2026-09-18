"""The reference model on its own (Issue# 603 - tap): it agrees with the declarations it
restates, it disagrees loudly with a wrong hand answer, and it imports nothing from the code
under test."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tap_grid.batch_corpus import model_oracle
from tap_grid.batch_corpus.loader import CorpusError, load_file

PANEL = {"name": "Panel", "slug": "one", "description": "", "view": "tap_web/panel_error.html"}


def _scenario(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "probe",
        "covers": ["req-grid-import-grift-identity-3"],
        "grid": {"nodes": [], "edges": []},
        "imports": [{"batches": [{"name": "b1", "nodes": [{"ref": "p", "type": "panel", "props": dict(PANEL)}]}]}],
        "expected": {
            "imports": [{"success": True, "batches": {"b1": "committed"}, "errors": []}],
            "live": {"p": 1},
            "tombstoned": {},
            "absent": [],
        },
    }
    base.update(overrides)
    return base


@pytest.mark.spec("req-grid-batch-corpus-oracle-3")
def test_the_model_imports_nothing_from_the_code_under_test() -> None:
    source = Path(model_oracle.__file__).read_text(encoding="utf-8")
    imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
    assert imports, "the scan read nothing"
    assert not [line for line in imports if "tap" in line or "django" in line], imports


@pytest.mark.spec("req-grid-batch-corpus-oracle-3")
def test_the_declaration_table_agrees_with_the_registry() -> None:
    """The table is restated, not imported; this is the check that keeps a restated fact true."""
    from tap_grid.registry import get_model_class, retired_entity_reason

    for entity_type, fields in model_oracle.KEYED.items():
        assert getattr(get_model_class(entity_type), "NATURAL_KEY", None) == fields, entity_type
    for entity_type in model_oracle.UNDECLARED:
        assert (
            getattr(get_model_class(entity_type), "NATURAL_KEY", "absent") is None
        ), f"{entity_type} now declares a key; update the model"
    for entity_type in model_oracle.RETIRED:
        assert retired_entity_reason(entity_type), f"{entity_type} is not retired"


@pytest.mark.spec("req-grid-batch-corpus-oracle-1")
class TestDisagreement:
    def test_a_wrong_hand_answer_fails_at_load_naming_both_sides(self, tmp_path: Path) -> None:
        raw = _scenario()
        raw["expected"]["live"] = {"p": 2}
        path = tmp_path / "probe.batch.json"
        path.write_text(json.dumps({"family": "probe", "description": "x", "scenarios": [raw]}))
        with pytest.raises(CorpusError, match=r"live: author says \{'p': 2\}, model says \{'p': 1\}"):
            load_file(path)

    def test_a_wrong_error_path_fails_at_load(self, tmp_path: Path) -> None:
        raw = _scenario(
            imports=[
                {
                    "batches": [
                        {"name": "b1", "nodes": [{"ref": "x", "type": "grid_fixtures__node", "props": {"name": "x"}}]}
                    ]
                }
            ],
            expected={
                "imports": [
                    {
                        "success": False,
                        "batches": {"b1": "failed"},
                        "errors": [{"code": "identity_undeclared", "path": "$.batches[0].nodes[0].entity.entity_id"}],
                    }
                ],
                "live": {},
                "tombstoned": {},
                "absent": ["x"],
            },
        )
        path = tmp_path / "probe.batch.json"
        path.write_text(json.dumps({"family": "probe", "description": "x", "scenarios": [raw]}))
        with pytest.raises(CorpusError, match="imports\\[0\\].errors: author says"):
            load_file(path)

    def test_a_name_declared_nowhere_is_refused_before_the_model_runs(self, tmp_path: Path) -> None:
        raw = _scenario()
        raw["imports"][0]["batches"][0]["edges"] = [
            {"id": "e", "type": "PG_LINKS__grid_fixtures", "from": "p", "to": "nobody"}
        ]
        path = tmp_path / "probe.batch.json"
        path.write_text(json.dumps({"family": "probe", "description": "x", "scenarios": [raw]}))
        with pytest.raises(CorpusError, match="named as endpoints or targets but declared nowhere"):
            load_file(path)


@pytest.mark.spec("req-grid-batch-corpus-oracle-1")
class TestRules:
    def test_two_refs_on_one_key_fail_the_batch_on_the_second(self) -> None:
        """The Issue# 602 - tap ruling, as the model states it."""
        raw = _scenario()
        raw["imports"][0]["batches"][0]["nodes"].append({"ref": "q", "type": "panel", "props": dict(PANEL)})
        out = model_oracle.run(raw)
        assert out.imports[0].errors == [("duplicate_entity_id", "$.batches[0].nodes[1].entity.ref")]
        assert out.imports[0].batches == {"b1": "failed"} and out.live() == {}

    def test_a_purge_takes_a_rows_events_with_it(self) -> None:
        raw = _scenario(
            settings={"debug": True},
            grid={
                "nodes": [
                    {"name": "A", "type": "grid_fixtures__node", "props": {"name": "A"}},
                    {"name": "C", "type": "grid_fixtures__node", "props": {"name": "C"}},
                ],
                "edges": [{"name": "e", "from": "A", "to": "C", "type": "PG_LINKS__grid_fixtures"}],
            },
            imports=[
                {
                    "batches": [
                        {
                            "name": "b1",
                            "purges": {
                                "on_missing": "error",
                                "edges": [],
                                "nodes": [{"id": "A", "type": "grid_fixtures__node", "reason": "r"}],
                            },
                        }
                    ]
                }
            ],
        )
        out = model_oracle.run(raw)
        assert out.purged == {"A", "e"} and out.live() == {"C": 1}
        assert out.event_delta() == {("A", "create"): -1, ("e", "link"): -1, ("b1", "delete"): 1}

    def test_a_failed_batch_leaves_the_state_of_the_batches_around_it(self) -> None:
        raw = _scenario(
            imports=[
                {
                    "batches": [
                        {"name": "b1", "nodes": [{"id": "X", "type": "grid_fixtures__node", "props": {"name": "X"}}]},
                        {
                            "name": "b2",
                            "nodes": [
                                {
                                    "id": "Y",
                                    "type": "grid_fixtures__node",
                                    "props": {"name": "Y"},
                                    "expected_version": 1,
                                }
                            ],
                        },
                        {"name": "b3", "nodes": [{"id": "Z", "type": "grid_fixtures__node", "props": {"name": "Z"}}]},
                    ]
                }
            ],
        )
        out = model_oracle.run(raw)
        assert out.imports[0].batches == {"b1": "committed", "b2": "failed", "b3": "committed"}
        assert out.live() == {"X": 1, "Z": 1} and not out.imports[0].success

    def test_a_re_sent_ref_that_misses_its_row_must_carry_a_new_name(self) -> None:
        raw = _scenario(
            grid={"nodes": [{"name": "p", "type": "panel", "props": dict(PANEL)}], "edges": [], "tombstoned": ["p"]},
        )
        with pytest.raises(model_oracle.ModelError, match="must carry a new name"):
            model_oracle.run(raw)
