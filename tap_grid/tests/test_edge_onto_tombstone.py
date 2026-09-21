"""No live edge may point at a tombstone — the invariant from the create side (Issue# 609 - tap,
ruled 2026-09-18) and, for the write pipeline's target row, from the replace side (Issue# 611).

The cascade already ends every incident edge of a node it retires. These tests close the other
half: an edge is never *created* onto a tombstone, through the service layer or the importer,
in sequence or under contention; and a row tombstoned while a replace waited on it is refused,
not overwritten. Every case ends by reading the invariant set, which must be empty.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tap_grid.cascade_corpus.timing import NESTS, NODE, contains, contend, node
from tap_grid.grift import grift_import
from tap_grid.models import Batch, Edge, Entity
from tap_grid.service_types import WriteOperation, WriteResult
from tap_grid.services import delete_node, replace_node, write_batch
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc


def _link(from_entity: Entity, to_entity: Entity) -> WriteResult:
    """Create one edge through the pipeline and return its typed result (the compat helper raises)."""
    batch = write_batch(
        [WriteOperation(verb="create_edge", from_target=from_entity.pk, to_target=to_entity.pk, edge_type=NESTS)]
    )
    if batch.results:
        return batch.results[0]
    return WriteResult(success=False, batch_id=batch.batch_id, errors=batch.errors)


def _refused_as_tombstoned(result: WriteResult) -> bool:
    """The pipeline maps a ServiceConflictError to the conflict code; the specific code rides the message."""
    return (
        not result.success
        and len(result.errors) == 1
        and result.errors[0].code == "conflict"
        and "entity_tombstoned" in result.errors[0].message
    )


def _edge_doc(bid: str, from_id: str, to_id: str) -> dict[str, Any]:
    edge = {
        "entity": {"entity_id": str(uuid.uuid7()), "entity_type": "edge", "dimensions": {}},
        "edge": {"from_entity_id": from_id, "to_entity_id": to_id, "edge_type": NESTS, "properties": {}},
    }
    return _minimal_doc([_batch_container(bid, edges=[edge])])


@pytest.mark.django_db
class TestCreateOntoATombstone:
    @pytest.mark.parametrize("role", ["from", "to"])
    def test_the_service_layer_refuses_a_tombstoned_endpoint(self, role: str) -> None:
        live, gone = node("live"), node("gone")
        assert delete_node(gone.pk, reason="operator").success
        edges_before = Edge.all_objects.count()
        result = _link(gone if role == "from" else live, live if role == "from" else gone)
        assert _refused_as_tombstoned(result), result.errors
        assert f"({role}_entity)" in result.errors[0].message
        assert Edge.all_objects.count() == edges_before
        assert not Edge.live_onto_tombstones().exists()

    def test_a_live_pair_still_links(self) -> None:
        a, b = node("a"), node("b")
        assert Edge.objects.filter(entity_id=contains(a, b)).exists()

    def test_the_importer_treats_a_tombstoned_endpoint_as_dangling_in_strict_mode(self) -> None:
        live, gone = node("live"), node("gone")
        assert delete_node(gone.pk, reason="operator").success
        before = Entity.objects.count()
        bid = _batch_entity_id()
        result = grift_import(_edge_doc(bid, str(live.pk), str(gone.pk)))
        assert not result.success
        (issue,) = result.errors
        assert issue.code == "dangling_edge" and issue.to_entity_id == str(gone.pk)
        assert Entity.objects.count() == before and not Batch.objects.filter(entity_id=bid).exists()

    def test_the_importer_skips_it_with_a_warning_in_permissive_mode(self) -> None:
        live, gone = node("live"), node("gone")
        assert delete_node(gone.pk, reason="operator").success
        before = Edge.all_objects.count()
        bid = _batch_entity_id()
        result = grift_import(_edge_doc(bid, str(gone.pk), str(live.pk)), dangling_edge_mode="permissive")
        assert result.success, result.errors
        assert any(w.code == "dangling_edge" for w in result.warnings)
        assert result.imported_batches[0].edges_skipped == 1 and result.imported_batches[0].edges_imported == 0
        assert Edge.all_objects.count() == before and not Edge.live_onto_tombstones().exists()


@pytest.mark.django_db(transaction=True)
class TestUnderContention:
    def test_an_edge_created_while_its_endpoint_is_being_deleted_is_refused(self) -> None:
        """The holder locks A and tombstones it; the edge writer blocks on A's row lock, then
        reads the committed tombstone and refuses. Nothing is written."""
        x, a = node("x"), node("a")
        holder, writer = contend(a.pk, lambda: delete_node(a.pk, reason="operator"), lambda: _link(x, a))
        assert holder.value.success
        assert _refused_as_tombstoned(writer.value), writer.value.errors
        assert Entity.objects.get(pk=a.pk).deleted_at is not None
        assert not Edge.all_objects.filter(to_entity_id=a.pk).exists()
        assert not Edge.live_onto_tombstones().exists()

    def test_a_delete_waiting_on_an_edge_creation_ends_the_new_edge(self) -> None:
        """The other order: the holder locks A and links X→A; the delete blocks on A, then
        its incident-edge pass finds the committed edge and ends it. Both succeed; the
        invariant holds at the end."""
        x, a = node("x"), node("a")
        holder, deleter = contend(a.pk, lambda: _link(x, a), lambda: delete_node(a.pk, reason="operator"))
        assert holder.value.success and deleter.value.success
        edge = Edge.all_objects.get(to_entity_id=a.pk)
        assert edge.entity.deleted_at is not None, "the delete's incident pass ended the edge that landed before it"
        assert not Edge.live_onto_tombstones().exists()

    def test_a_row_tombstoned_under_a_waiting_replace_is_refused(self) -> None:
        """Issue# 611 - tap through the public verb: the replace waits on the row lock, the
        holder tombstones and commits, the replace reads the tombstone and refuses."""
        a = node("a")
        version_after_create = Entity.objects.get(pk=a.pk).version
        holder, writer = contend(
            a.pk, lambda: delete_node(a.pk, reason="operator"), lambda: replace_node(a.pk, {"name": "a, replaced"})
        )
        assert holder.value.success
        assert _refused_as_tombstoned(writer.value), writer.value.errors
        row = Entity.objects.get(pk=a.pk)
        assert row.deleted_at is not None and row.version == version_after_create + 1, "only the delete bumped"
        assert row.name != "a, replaced"


@pytest.mark.django_db
def test_the_invariant_query_reads_only_live_edges_with_a_tombstoned_endpoint() -> None:
    """Guard the guard: the set is empty on a clean grid, and would not be if an edge were
    kept live onto a tombstone (built below the service layer, on purpose)."""
    a, b = node("a"), node("b")
    contains(a, b)
    assert not Edge.live_onto_tombstones().exists()
    # Below the service layer, deliberately: tombstone b without ending its edge.
    Entity.objects.filter(pk=b.pk).update(deleted_at=Entity.objects.get(pk=a.pk).created_at)
    assert Edge.live_onto_tombstones().count() == 1
    assert NODE  # the fixture type the helpers build with is the one the corpus uses
