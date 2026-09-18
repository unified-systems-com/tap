"""Batch-local refs on the GRIFT envelope — the gate, shape A, slice 1 (Issue# 593 - tap;
parent Issue# 571 - tap; #571 done-tests 4 and 5).

A node the sender has no id for carries ``ref`` instead of ``entity_id``; an edge names such a
node by ``from_ref`` / ``to_ref``. Refs resolve to ids before preflight and the ``ref → id`` map
comes back on the imported batch. Every case here asserts what was written (or that nothing
was), never only the result code. The nodes are web pages and panels — types that declare a
``NATURAL_KEY`` — because since slice 2 (Issue# 594 - tap) a ref on an undeclared type is
refused; what resolution finds is ``test_grift_identity.py``'s subject, not this file's.
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

WEB = {"tap.graph": "web"}


def _panel(ref: str, name: str = "Panel") -> dict[str, Any]:
    """A panel named by ref; its slug is the ref, so each test's refs are its own slugs."""
    return {
        "entity": {"ref": ref, "entity_type": "panel", "name": name, "dimensions": WEB},
        "node": {"name": name, "slug": f"p-{ref}", "description": "", "view": "tap_web/panel_error.html"},
    }


def _page(ref: str, name: str = "Page") -> dict[str, Any]:
    layout = {"columns": {"col-1": {"width": "1fr", "rows": {"row-1": {"panel-id": "hero"}}}}}
    return {
        "entity": {"ref": ref, "entity_type": "page", "name": name, "dimensions": WEB},
        "node": {"name": name, "slug": f"/{ref}", "description": "", "layout": layout},
    }


def _page_by_id(entity_id: str, slug: str, name: str = "Page") -> dict[str, Any]:
    node = _page(slug, name)
    node["entity"] = {"entity_id": entity_id, "entity_type": "page", "name": name, "dimensions": WEB}
    return node


def _edge(entity: dict[str, Any], **endpoints: str) -> dict[str, Any]:
    return {
        "entity": {"entity_type": "edge", "dimensions": WEB, **entity},
        # The page-panels hotlink is exact: the layout row "hero" must be backed by this edge.
        "edge": {
            "edge_type": "USES_PANEL",
            "properties": {"hotlink": {"model": "page", "spec": "page-panels", "value": "hero"}},
            **endpoints,
        },
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
        result = grift_import(_doc(_batch_container(bid, nodes=[_panel("a"), _panel("b", "Bee")])))
        assert result.success, result.errors
        (batch,) = result.imported_batches
        assert set(batch.resolved_refs) == {"a", "b"}
        for entity_id in batch.resolved_refs.values():
            row = Entity.objects.get(pk=uuid.UUID(entity_id))
            assert uuid.UUID(entity_id).version == 7, "an assigned id is a UUIDv7"
            assert row.entity_type == "panel" and row.deleted_at is None
        assert Entity.objects.get(pk=uuid.UUID(batch.resolved_refs["b"])).name == "Bee"
        assert batch.nodes_imported == 2

    def test_no_ref_reaches_a_record(self) -> None:
        """The ref string is absent from every event this import recorded and from the spine."""
        bid = _batch_entity_id()
        ref = "a-ref-string-no-record-may-carry"
        result = grift_import(_doc(_batch_container(bid, nodes=[_panel(ref)])))
        assert result.success, result.errors
        events = list(BatchEvent.objects.filter(batch__entity_id=bid))
        assert events, "the import recorded events to inspect"
        for event in events:
            assert ref not in json.dumps(event.metadata or {})
        minted = result.imported_batches[0].resolved_refs[ref]
        assert ref not in (Entity.objects.get(pk=uuid.UUID(minted)).name or "")

    def test_edges_resolve_their_endpoints_through_the_map(self) -> None:
        """#571 done-test 5: from_ref / to_ref land as the assigned ids; the edge itself may be a ref."""
        bid = _batch_entity_id()
        doc = _doc(
            _batch_container(
                bid,
                nodes=[_page("home"), _panel("hero")],
                edges=[_edge({"ref": "home-hero"}, from_ref="home", to_ref="hero")],
            )
        )
        result = grift_import(doc)
        assert result.success, result.errors
        refs = result.imported_batches[0].resolved_refs
        assert set(refs) == {"home", "hero", "home-hero"}
        edge = Entity.objects.get(pk=uuid.UUID(refs["home-hero"]))
        assert edge.entity_type == "edge"
        link = Edge.objects.get(entity_id=edge.pk)
        assert str(link.from_entity_id) == refs["home"] and str(link.to_entity_id) == refs["hero"]
        assert result.imported_batches[0].edges_imported == 1

    def test_a_mixed_bundle_imports(self) -> None:
        """Ids and refs side by side, with an edge from an id-addressed node to a ref node."""
        bid = _batch_entity_id()
        home = str(uuid.uuid7())
        doc = _doc(
            _batch_container(
                bid,
                nodes=[_page_by_id(home, "home"), _panel("hero")],
                edges=[_edge({"entity_id": str(uuid.uuid7())}, from_entity_id=home, to_ref="hero")],
            )
        )
        result = grift_import(doc)
        assert result.success, result.errors
        refs = result.imported_batches[0].resolved_refs
        assert set(refs) == {"hero"}
        link = Edge.objects.get(from_entity_id=uuid.UUID(home))
        assert str(link.to_entity_id) == refs["hero"]

    def test_the_callers_document_is_not_mutated(self) -> None:
        """Importing the same dict twice presents refs twice; the first import's ids do not leak
        into the caller's document and turn the second into an id-addressed replace."""
        doc = _doc(_batch_container(_batch_entity_id(), nodes=[_panel("a")]))
        before = json.dumps(doc, sort_keys=True)
        assert grift_import(doc).success
        assert json.dumps(doc, sort_keys=True) == before
        assert "ref" in doc["batches"][0]["nodes"][0]["entity"]


class TestRefsRefuse:
    def test_both_entity_id_and_ref_is_a_validation_error_before_any_write(self) -> None:
        """#571 done-test 4, first half."""
        bid = _batch_entity_id()
        before = Entity.objects.count()
        node = _panel("a")
        node["entity"]["entity_id"] = str(uuid.uuid7())
        result = grift_import(_doc(_batch_container(bid, nodes=[node])))
        assert not result.success
        assert "schema_validation_failed" in _codes(result)
        _nothing_written(before, bid)

    def test_neither_entity_id_nor_ref_is_a_validation_error_before_any_write(self) -> None:
        """#571 done-test 4, second half."""
        bid = _batch_entity_id()
        before = Entity.objects.count()
        node = _panel("a")
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
                nodes=[_page("home")],
                edges=[_edge({"ref": "e"}, from_ref="home", to_ref="nobody")],
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
                nodes=[_page("home"), _panel("hero")],
                edges=[_edge({"ref": "e"}, from_ref="home", from_entity_id=str(uuid.uuid7()), to_ref="hero")],
            )
        )
        result = grift_import(doc)
        assert not result.success and "schema_validation_failed" in _codes(result)
        _nothing_written(before, bid)

    def test_a_ref_used_twice_in_one_batch_fails_the_file(self) -> None:
        bid = _batch_entity_id()
        before = Entity.objects.count()
        result = grift_import(_doc(_batch_container(bid, nodes=[_panel("a"), _panel("a", "Other")])))
        assert not result.success and _codes(result) == {"duplicate_ref"}
        _nothing_written(before, bid)

    def test_refs_are_batch_local(self) -> None:
        """An edge in batch two cannot name a ref from batch one."""
        b1, b2 = _batch_entity_id(), _batch_entity_id()
        before = Entity.objects.count()
        doc = _doc(
            _batch_container(b1, nodes=[_panel("hero")]),
            _batch_container(b2, nodes=[_page("home")], edges=[_edge({"ref": "e"}, from_ref="home", to_ref="hero")]),
        )
        result = grift_import(doc)
        assert not result.success and _codes(result) == {"unknown_ref"}
        assert Entity.objects.count() == before
        assert not Batch.objects.filter(entity_id__in=[b1, b2]).exists()

    def test_a_blank_ref_is_invalid(self) -> None:
        bid = _batch_entity_id()
        before = Entity.objects.count()
        result = grift_import(_doc(_batch_container(bid, nodes=[_panel("   ")])))
        assert not result.success and _codes(result) == {"invalid_ref"}
        _nothing_written(before, bid)

    def test_a_batch_is_never_a_ref(self) -> None:
        bid = _batch_entity_id()
        before = Entity.objects.count()
        container = _batch_container(bid, nodes=[_panel("a")])
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
            "nodes": [{"ref": "a", "entity_type": "panel", "reason": "gone"}],
        }
        result = grift_import(_doc(container))
        assert not result.success and "schema_validation_failed" in _codes(result)
        _nothing_written(before, bid)
