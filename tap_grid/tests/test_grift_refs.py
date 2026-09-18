"""Batch-local refs on the GRIFT envelope — the gate, shape A, slice 1 (Issue# 593 - tap;
parent Issue# 571 - tap; #571 done-tests 4 and 5).

A node the sender has no id for carries ``ref`` instead of ``entity_id``; an edge names such a
node by ``from_ref`` / ``to_ref``. Refs resolve to ids before preflight, through the mint-only
resolver in this slice, and the ``ref → id`` map comes back on the imported batch. Every case
here asserts what was written (or that nothing was), never only the result code.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from tap_grid.grift import grift_import
from tap_grid.models import Batch, BatchEvent, Edge, Entity
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc

pytestmark = pytest.mark.django_db

NODE_TYPE = "grid_fixtures__constrained_source"
TARGET_TYPE = "grid_fixtures__dual_endpoint"
EDGE_TYPE = "SCHEMA_LINK__grid_fixtures"  # permitted from a constrained source to a dual endpoint


def _ref_node(ref: str, name: str = "Frodo") -> dict[str, Any]:
    return {
        "entity": {"ref": ref, "entity_type": NODE_TYPE, "name": name, "dimensions": {}},
        "node": {"name": name, "description": "a hobbit"},
    }


def _ref_target(ref: str, name: str = "Sting") -> dict[str, Any]:
    return {
        "entity": {"ref": ref, "entity_type": TARGET_TYPE, "name": name, "dimensions": {}},
        "node": {"name": name, "description": "glows", "kind": "Erebor"},
    }


def _id_node(entity_id: str, name: str = "Sam") -> dict[str, Any]:
    return {
        "entity": {"entity_id": entity_id, "entity_type": NODE_TYPE, "name": name, "dimensions": {}},
        "node": {"name": name, "description": "a gardener"},
    }


def _edge(entity: dict[str, Any], **endpoints: str) -> dict[str, Any]:
    return {
        "entity": {"entity_type": "edge", "dimensions": {}, **entity},
        "edge": {"edge_type": EDGE_TYPE, "properties": {}, **endpoints},
    }


def _doc(*batches: dict[str, Any]) -> dict[str, Any]:
    return _minimal_doc(list(batches))


def _nothing_written(before: int, batch_id: str) -> None:
    assert Entity.objects.count() == before
    assert not Batch.objects.filter(entity_id=batch_id).exists()


def _codes(result: Any) -> set[str]:
    return {e.code for e in result.errors}


class TestRefsResolve:
    def test_a_ref_bundle_imports_and_reports_what_each_ref_became(self) -> None:
        bid = _batch_entity_id()
        result = grift_import(_doc(_batch_container(bid, nodes=[_ref_node("frodo"), _ref_node("sam", "Sam")])))
        assert result.success, result.errors
        (batch,) = result.imported_batches
        assert set(batch.resolved_refs) == {"frodo", "sam"}
        for entity_id in batch.resolved_refs.values():
            row = Entity.objects.get(pk=uuid.UUID(entity_id))
            assert uuid.UUID(entity_id).version == 7, "a minted id is a UUIDv7"
            assert row.entity_type == NODE_TYPE and row.deleted_at is None
        assert Entity.objects.get(pk=uuid.UUID(batch.resolved_refs["sam"])).name == "Sam"
        assert batch.nodes_imported == 2

    def test_no_ref_reaches_a_record(self) -> None:
        """The ref string is absent from every event this import recorded and from the spine."""
        bid = _batch_entity_id()
        ref = "a-ref-string-no-record-may-carry"
        result = grift_import(_doc(_batch_container(bid, nodes=[_ref_node(ref)])))
        assert result.success, result.errors
        events = list(BatchEvent.objects.filter(batch__entity_id=bid))
        assert events, "the import recorded events to inspect"
        for event in events:
            assert ref not in json.dumps(event.metadata or {})
        minted = result.imported_batches[0].resolved_refs[ref]
        row = Entity.objects.get(pk=uuid.UUID(minted))
        assert ref not in (row.name or "")

    def test_edges_resolve_their_endpoints_through_the_map(self) -> None:
        """#571 done-test 5: from_ref / to_ref land as the minted ids; the edge itself may be a ref."""
        bid = _batch_entity_id()
        doc = _doc(
            _batch_container(
                bid,
                nodes=[_ref_node("frodo"), _ref_target("sting")],
                edges=[_edge({"ref": "frodo-sting"}, from_ref="frodo", to_ref="sting")],
            )
        )
        result = grift_import(doc)
        assert result.success, result.errors
        refs = result.imported_batches[0].resolved_refs
        assert set(refs) == {"frodo", "sting", "frodo-sting"}
        edge = Entity.objects.get(pk=uuid.UUID(refs["frodo-sting"]))
        assert edge.entity_type == "edge"
        link = Edge.objects.get(entity_id=edge.pk)
        assert str(link.from_entity_id) == refs["frodo"] and str(link.to_entity_id) == refs["sting"]
        assert result.imported_batches[0].edges_imported == 1

    def test_a_mixed_bundle_imports(self) -> None:
        """Ids and refs side by side, with an edge from an id-addressed node to a ref node."""
        bid = _batch_entity_id()
        sam = str(uuid.uuid7())
        doc = _doc(
            _batch_container(
                bid,
                nodes=[_id_node(sam), _ref_target("sting")],
                edges=[_edge({"entity_id": str(uuid.uuid7())}, from_entity_id=sam, to_ref="sting")],
            )
        )
        result = grift_import(doc)
        assert result.success, result.errors
        refs = result.imported_batches[0].resolved_refs
        assert set(refs) == {"sting"}
        link = Edge.objects.get(from_entity_id=uuid.UUID(sam))
        assert str(link.to_entity_id) == refs["sting"]

    def test_the_stub_resolver_has_no_memory(self) -> None:
        """Slice 1 mints on every ref: the same bundle twice makes two rows. Slice 2
        (Issue# 594 - tap) flips this to one row found through find_existing."""
        first = grift_import(_doc(_batch_container(_batch_entity_id(), nodes=[_ref_node("frodo")])))
        second = grift_import(_doc(_batch_container(_batch_entity_id(), nodes=[_ref_node("frodo")])))
        assert first.success and second.success
        a = first.imported_batches[0].resolved_refs["frodo"]
        b = second.imported_batches[0].resolved_refs["frodo"]
        assert a != b
        assert Entity.objects.filter(pk__in=[uuid.UUID(a), uuid.UUID(b)]).count() == 2

    def test_the_callers_document_is_not_mutated(self) -> None:
        """Importing the same dict twice presents refs twice; the first import's ids do not leak
        into the caller's document and turn the second into an id-addressed replace."""
        doc = _doc(_batch_container(_batch_entity_id(), nodes=[_ref_node("frodo")]))
        before = json.dumps(doc, sort_keys=True)
        assert grift_import(doc).success
        assert json.dumps(doc, sort_keys=True) == before
        assert "ref" in doc["batches"][0]["nodes"][0]["entity"]


class TestRefsRefuse:
    def test_both_entity_id_and_ref_is_a_validation_error_before_any_write(self) -> None:
        """#571 done-test 4, first half."""
        bid = _batch_entity_id()
        before = Entity.objects.count()
        node = _ref_node("frodo")
        node["entity"]["entity_id"] = str(uuid.uuid7())
        result = grift_import(_doc(_batch_container(bid, nodes=[node])))
        assert not result.success
        assert "schema_validation_failed" in _codes(result)
        _nothing_written(before, bid)

    def test_neither_entity_id_nor_ref_is_a_validation_error_before_any_write(self) -> None:
        """#571 done-test 4, second half."""
        bid = _batch_entity_id()
        before = Entity.objects.count()
        node = _ref_node("frodo")
        del node["entity"]["ref"]
        result = grift_import(_doc(_batch_container(bid, nodes=[node])))
        assert not result.success
        assert "schema_validation_failed" in _codes(result)
        _nothing_written(before, bid)

    def test_an_edge_naming_an_unknown_ref_fails_the_file(self) -> None:
        """#571 done-test 5, the refusal: nothing is written, not even the nodes that were fine."""
        bid = _batch_entity_id()
        before = Entity.objects.count()
        doc = _doc(
            _batch_container(
                bid,
                nodes=[_ref_node("frodo")],
                edges=[_edge({"ref": "e"}, from_ref="frodo", to_ref="nobody")],
            )
        )
        result = grift_import(doc)
        assert not result.success
        assert _codes(result) == {"unknown_ref"}
        (issue,) = result.errors
        assert issue.path.endswith(".edge.to_ref") and "nobody" in issue.message
        _nothing_written(before, bid)

    def test_an_endpoint_with_both_id_and_ref_is_a_validation_error(self) -> None:
        bid = _batch_entity_id()
        before = Entity.objects.count()
        doc = _doc(
            _batch_container(
                bid,
                nodes=[_ref_node("frodo"), _ref_node("sam", "Sam")],
                edges=[_edge({"ref": "e"}, from_ref="frodo", from_entity_id=str(uuid.uuid7()), to_ref="sam")],
            )
        )
        result = grift_import(doc)
        assert not result.success and "schema_validation_failed" in _codes(result)
        _nothing_written(before, bid)

    def test_a_ref_used_twice_in_one_batch_fails_the_file(self) -> None:
        bid = _batch_entity_id()
        before = Entity.objects.count()
        result = grift_import(_doc(_batch_container(bid, nodes=[_ref_node("frodo"), _ref_node("frodo", "Other")])))
        assert not result.success and _codes(result) == {"duplicate_ref"}
        _nothing_written(before, bid)

    def test_refs_are_batch_local(self) -> None:
        """An edge in batch two cannot name a ref from batch one."""
        b1, b2 = _batch_entity_id(), _batch_entity_id()
        before = Entity.objects.count()
        doc = _doc(
            _batch_container(b1, nodes=[_ref_node("frodo")]),
            _batch_container(
                b2, nodes=[_ref_node("sam", "Sam")], edges=[_edge({"ref": "e"}, from_ref="sam", to_ref="frodo")]
            ),
        )
        result = grift_import(doc)
        assert not result.success and _codes(result) == {"unknown_ref"}
        assert Entity.objects.count() == before
        assert not Batch.objects.filter(entity_id__in=[b1, b2]).exists()

    def test_a_blank_ref_is_invalid(self) -> None:
        bid = _batch_entity_id()
        before = Entity.objects.count()
        result = grift_import(_doc(_batch_container(bid, nodes=[_ref_node("   ")])))
        assert not result.success and _codes(result) == {"invalid_ref"}
        _nothing_written(before, bid)

    def test_a_batch_is_never_a_ref(self) -> None:
        bid = _batch_entity_id()
        before = Entity.objects.count()
        container = _batch_container(bid, nodes=[_ref_node("frodo")])
        del container["batch_entity"]["entity_id"]
        container["batch_entity"]["ref"] = "this-batch"
        result = grift_import(_doc(container))
        assert not result.success and _codes(result) == {"ref_not_allowed"}
        assert Entity.objects.count() == before

    def test_a_removal_target_cannot_be_a_ref(self) -> None:
        """A ref names something not yet written; there is nothing to remove by it."""
        bid = _batch_entity_id()
        before = Entity.objects.count()
        container = _batch_container(bid)
        container["deletes"] = {
            "on_missing": "skip",
            "on_tombstoned": "skip",
            "edges": [],
            "nodes": [{"ref": "frodo", "entity_type": NODE_TYPE, "reason": "gone"}],
        }
        result = grift_import(_doc(container))
        assert not result.success and "schema_validation_failed" in _codes(result)
        _nothing_written(before, bid)
