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
CORE_KEYS = {"tap.meta", "tap.graph", "tap_cares", "tap.time"}


@pytest.mark.spec("req-grid-dimension-knobs-1")
@pytest.mark.spec("req-grid-dimension-knobs-2")
@pytest.mark.spec("req-grid-dimension-knobs-4")
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

    def test_the_crud_schema_names_every_knob(self) -> None:
        schema = Dimension.FIELD_CRUD_SCHEMA
        assert schema["values"]["type"] == ["array", "null"]
        assert schema["values"]["items"] == {"type": "string", "minLength": 1}
        assert schema["usable_in_keys"] == {"type": "boolean"}
        assert schema["empty_is_meaningful"] == {"type": "boolean"}

    def test_empty_is_not_meaningful_unless_declared(self) -> None:
        assert Dimension(name="example.empty").empty_is_meaningful is False

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
        """Every node is a key core stamps, or the description of one value of a bounded key."""
        nodes = {n["entity"]["name"]: n["node"] for n in self._nodes()}
        described = {
            f"{key}.{value}" for key in CORE_KEYS for value in (nodes[key].get("values") or ()) if key in nodes
        }
        assert set(nodes) == CORE_KEYS | described
        assert described == {"tap.time.occurred", "tap.time.created", "tap.time.first_seen", "tap.time.published"}

    def test_a_seed_batch_is_never_edited_once_shipped(self) -> None:
        """A batch a grid has imported is skipped by id, so new nodes go in a new batch."""
        doc = json.loads(SEED.read_text(encoding="utf-8"))
        first, second = doc["batches"]
        assert first["batch_entity"]["entity_id"] == "01a1d14c-d80b-725d-8002-eb0a03110525"
        assert {n["entity"]["name"] for n in first["nodes"]} == {"tap.meta", "tap.graph", "tap_cares"}
        assert uuid.UUID(second["batch_entity"]["entity_id"]).version == 7
        assert second["batch_entity"]["entity_id"] != first["batch_entity"]["entity_id"]

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
