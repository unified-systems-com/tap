"""The Dimension node's knobs and core's dimension vocabulary seed (req-grid-dimension-knobs,
req-grid-dimension-core-vocabulary; George, 2026-11-12, aws-build Q47, Q48a, Q52a).

Knobs are named fields, one per knob: ``values`` (a list makes a dimension bounded, null leaves it
open) and ``usable_in_keys`` (whether a type may name it in a NATURAL_KEY). Core's own dimension keys
are declared in ``tap_grid/data/dimensions.grift.json`` with fixed ids, never created on demand.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest

import tap_grid
from tap_grid.models import Dimension

SEED = Path(tap_grid.__file__).resolve().parent / "data" / "dimensions.grift.json"
CORE_KEYS = {"tap.meta", "tap.graph", "tap_cares"}


@pytest.mark.spec("req-grid-dimension-knobs-1")
@pytest.mark.spec("req-grid-dimension-knobs-2")
class TestKnobs:
    def test_a_new_dimension_is_open_and_not_usable_in_keys(self) -> None:
        dimension = Dimension(name="example.open")
        assert dimension.values is None
        assert dimension.usable_in_keys is False
        assert not dimension.is_bounded()
        assert dimension.accepts("anything at all")

    def test_a_values_list_bounds_the_dimension(self) -> None:
        dimension = Dimension(name="example.bounded", values=["a", "b"])
        assert dimension.is_bounded()
        assert dimension.accepts("a")
        assert not dimension.accepts("c")

    def test_the_crud_schema_names_both_knobs(self) -> None:
        schema = Dimension.FIELD_CRUD_SCHEMA
        assert schema["values"]["type"] == ["array", "null"]
        assert schema["values"]["items"] == {"type": "string", "minLength": 1}
        assert schema["usable_in_keys"] == {"type": "boolean"}

    def test_no_knob_is_named_after_the_spine_key_column(self) -> None:
        """That name is the spine column's, and the output-only guard scans core for it."""
        spine_column = "natural" + "_key"
        assert spine_column not in {f.name for f in Dimension._meta.get_fields()}


@pytest.mark.spec("req-grid-dimension-core-vocabulary-1")
class TestCoreVocabularySeed:
    def _nodes(self) -> list[dict[str, Any]]:
        doc = json.loads(SEED.read_text(encoding="utf-8"))
        return [n for batch in doc["batches"] for n in batch["nodes"]]

    def test_the_seed_declares_every_key_core_stamps(self) -> None:
        names = {n["entity"]["name"] for n in self._nodes()}
        assert names == CORE_KEYS

    def test_every_node_is_a_dimension_with_a_fixed_uuid7(self) -> None:
        for node in self._nodes():
            entity = node["entity"]
            assert entity["entity_type"] == "dimension"
            ident = uuid.UUID(entity["entity_id"])
            assert ident.version == 7, f"{entity['name']} id is not a UUIDv7"
            assert entity["name"] == node["node"]["name"]
            assert node["node"]["description"].strip()

    @pytest.mark.parametrize("key", sorted(CORE_KEYS))
    def test_each_core_key_is_stamped_somewhere_in_core(self, key: str) -> None:
        """A declared key that nothing stamps is bit rot; this keeps the seed honest."""
        root = Path(tap_grid.__file__).resolve().parent.parent
        hits = [
            p
            for app in ("tap_grid", "tap_web", "tap_cares")
            for p in (root / app).rglob("*.py")
            if "/tests/" not in str(p) and "/migrations/" not in str(p) and f'"{key}"' in p.read_text(encoding="utf-8")
        ]
        assert hits, f"no core module stamps {key!r}"


@pytest.mark.spec("req-grid-dimension-core-vocabulary-1")
class TestARenamedNodeKeepsItsId:
    """aws-build Q56: a node renamed and moved to another seed keeps its uuid; the latest seed batch
    names it, and the old name still resolves to the same id while both seeds are installed."""

    def _seed(self, tmp_path: Path, file: str, batch: str, name: str) -> tuple[str, Path]:
        doc = {
            "batches": [
                {
                    "batch_entity": {"entity_id": batch},
                    "nodes": [
                        {
                            "entity": {"entity_id": "019dd143-3e8f-73e4-b0fa-e62ac923065d", "entity_type": "dimension", "name": name},
                            "node": {"name": name, "description": "d"},
                        }
                    ],
                }
            ]
        }
        path = tmp_path / file
        path.write_text(json.dumps(doc), encoding="utf-8")
        return (file, path)

    def test_the_latest_batch_names_it_and_both_names_resolve(self, tmp_path: Path) -> None:
        from tap_grid.dimension_vocabulary import build

        old = self._seed(tmp_path, "aws.json", "019dd143-3e8f-73e4-b0fa-e629e288cd8f", "tap.cloud")
        new = self._seed(tmp_path, "computing.json", "01a1d1d0-0000-7000-8000-000000000001", "tap.computing.cloud")
        for files in ([old, new], [new, old]):
            table = build(files)
            assert table.by_id["019dd143-3e8f-73e4-b0fa-e62ac923065d"].name == "tap.computing.cloud"
            assert table.by_name["tap.cloud"] == table.by_name["tap.computing.cloud"] == ("019dd143-3e8f-73e4-b0fa-e62ac923065d",)
