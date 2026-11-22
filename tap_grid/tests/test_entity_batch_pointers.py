"""The spine's batch pointers: which batch last changed a row, and which last observed it.

Covers ``req-grid-entity-batch-pointers`` (spec-grid-entity.md); Issue# 323 - tap. Service writes
use the neutral grid_fixtures ``PgNode`` and the unconstrained ``PG_LINKS__grid_fixtures`` edge;
GRIFT imports use ``tap_web`` panels, as the other import suites do.
"""

from __future__ import annotations

import copy
import uuid
from datetime import timedelta
from typing import Any

import pytest
from tap_plugin.grid_fixtures.models.pg_node import PgNode

from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
from tap_grid.exceptions import ServiceEvidenceError
from tap_grid.grift import grift_import
from tap_grid.grift.subgraph import build_spine_surface
from tap_grid.models import Batch, Edge, Entity
from tap_grid.service_types import WRITE_CHANGED, WRITE_UNCHANGED, WriteOperation
from tap_grid.services import create_edge, create_node, delete_node, patch_node, replace_node, write_batch
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc
from tap_grid.write_guard import service_write_scope
from tap_web.models import Panel

AC = {n: pytest.mark.spec(f"req-grid-entity-batch-pointers-{n}") for n in range(1, 11)}

_TYPE = "grid_fixtures__node"
LINK = "PG_LINKS__grid_fixtures"
WEB = {"tap.graph": "web"}
POINTERS = ("last_changed_batch_id", "last_observed_batch_id", "last_observed_at")


def _ctx() -> CallerContext:
    return CallerContext(batch_id=str(uuid.uuid7()))


def _bid(ctx: CallerContext) -> uuid.UUID:
    assert ctx.batch_id is not None
    return uuid.UUID(ctx.batch_id)


def _create(payload: dict[str, Any]) -> tuple[PgNode, uuid.UUID]:
    ctx = _ctx()
    result = create_node(_TYPE, payload, caller_context=ctx)
    assert result.success, result.errors
    return PgNode.objects.get(entity_id=result.entity_id), _bid(ctx)


def _row(entity_id: Any) -> Entity:
    return Entity.objects.get(pk=entity_id)


def _panel(
    slug: str, entity_id: str, *, description: str = "", dimensions: dict[str, Any] | None = None, name: str = ""
) -> dict[str, Any]:
    return {
        "entity": {
            "entity_id": entity_id,
            "entity_type": "panel",
            "name": name or slug,
            "dimensions": WEB if dimensions is None else dimensions,
        },
        "node": {"name": slug, "slug": slug, "description": description, "view": "tap_web/panel_error.html"},
    }


def _import(nodes: list[dict[str, Any]]) -> uuid.UUID:
    """Import one fresh batch; returns its batch entity id."""
    batch_id = _batch_entity_id()
    result = grift_import(_minimal_doc([_batch_container(batch_id, nodes=copy.deepcopy(nodes))]))
    assert result.success, result.errors
    return uuid.UUID(batch_id)


@pytest.mark.django_db
class TestCreate:
    @AC[1]
    def test_a_service_create_names_the_creating_batch_twice(self) -> None:
        node, batch = _create({"name": "eth0"})
        row = _row(node.entity_id)
        assert row.last_changed_batch_id == batch
        assert row.last_observed_batch_id == batch
        # A change is also an observation, at the time of the change (rule 5).
        assert row.last_observed_at == row.updated_at

    @AC[1]
    def test_an_import_create_under_a_given_id_names_the_importing_batch(self) -> None:
        entity_id = str(uuid.uuid4())
        batch = _import([_panel("p-create", entity_id)])
        row = _row(entity_id)
        assert (row.last_changed_batch_id, row.last_observed_batch_id) == (batch, batch)
        assert row.last_observed_at == row.updated_at
        assert row.version == 1

    @AC[1]
    def test_an_edge_create_names_the_creating_batch(self) -> None:
        a, _ = _create({"name": "a"})
        b, _ = _create({"name": "b"})
        ctx = _ctx()
        edge = create_edge(a.entity, b.entity, LINK, {"weight": 1}, caller_context=ctx)
        row = _row(edge.entity_id)
        assert (row.last_changed_batch_id, row.last_observed_batch_id) == (_bid(ctx), _bid(ctx))
        assert row.last_observed_at is not None

    def test_a_batch_names_no_batch_on_its_own_row(self) -> None:
        # A batch cannot be written in a batch, so its own spine row carries no pointer.
        _, batch = _create({"name": "eth0"})
        assert Batch.objects.filter(entity_id=batch).exists()
        row = _row(batch)
        assert (row.last_changed_batch_id, row.last_observed_batch_id, row.last_observed_at) == (None, None, None)


@pytest.mark.django_db
class TestObservationAndChange:
    @AC[2]
    def test_an_unchanged_reimport_moves_only_the_observed_pair(self) -> None:
        entity_id = str(uuid.uuid4())
        first = _import([_panel("p-same", entity_id)])
        before = _row(entity_id)
        second = _import([_panel("p-same", entity_id)])
        after = _row(entity_id)
        assert after.last_changed_batch_id == first
        assert after.last_observed_batch_id == second
        assert after.last_observed_at > before.last_observed_at
        assert (after.version, after.updated_at) == (before.version, before.updated_at)
        assert getattr(Panel, "history").filter(entity_id=entity_id).count() == 1  # noqa: B009

    @AC[2]
    def test_an_unchanged_service_write_moves_only_the_observed_pair(self) -> None:
        node, first = _create({"name": "eth0", "kind": "nic"})
        before = _row(node.entity_id)
        ctx = _ctx()
        result = patch_node(node.entity_id, {"kind": "nic"}, caller_context=ctx)
        assert result.success and result.state == WRITE_UNCHANGED
        after = _row(node.entity_id)
        assert (after.last_changed_batch_id, after.last_observed_batch_id) == (first, _bid(ctx))
        assert after.last_observed_at > before.last_observed_at
        assert (after.version, after.updated_at) == (before.version, before.updated_at)

    @AC[3]
    def test_a_changed_write_moves_both(self) -> None:
        node, _ = _create({"name": "eth0", "kind": "nic"})
        patch_node(node.entity_id, {"kind": "nic"}, caller_context=_ctx())
        third = _ctx()
        result = patch_node(node.entity_id, {"kind": "bond"}, caller_context=third)
        assert result.success and result.state == WRITE_CHANGED
        row = _row(node.entity_id)
        assert (row.last_changed_batch_id, row.last_observed_batch_id) == (_bid(third), _bid(third))
        # Written in the statement that increments version, at the time of the change.
        assert row.last_observed_at == row.updated_at
        assert row.version == 2

    @AC[3]
    def test_a_changed_replace_moves_both(self) -> None:
        node, _ = _create({"name": "eth0"})
        ctx = _ctx()
        result = replace_node(node.entity_id, {"name": "eth1"}, caller_context=ctx)
        assert result.success, result.errors
        row = _row(node.entity_id)
        assert (row.last_changed_batch_id, row.last_observed_batch_id) == (_bid(ctx), _bid(ctx))

    @AC[6]
    def test_a_batch_that_names_a_subset_leaves_the_rest_alone(self) -> None:
        named, _ = _create({"name": "named", "kind": "nic"})
        other, _ = _create({"name": "other", "kind": "nic"})
        untouched = {field: getattr(_row(other.entity_id), field) for field in POINTERS}
        ctx = _ctx()
        result = write_batch(
            [
                WriteOperation(verb="patch_node", target=named.entity_id, payload={"kind": "nic"}),
                WriteOperation(verb="create_node", type_slug=_TYPE, payload={"name": "new"}),
            ],
            caller_context=ctx,
            batch_name="subset",
            batch_description="names two of three",
        )
        assert result.success, result.errors
        assert {field: getattr(_row(other.entity_id), field) for field in POINTERS} == untouched
        assert _row(named.entity_id).last_observed_batch_id == _bid(ctx)


@pytest.mark.django_db
class TestRetirement:
    @AC[4]
    def test_a_tombstone_names_the_retiring_batch_on_the_node_and_its_edges(self) -> None:
        a, _ = _create({"name": "a"})
        b, _ = _create({"name": "b"})
        out = create_edge(a.entity, b.entity, LINK, {"weight": 1}, caller_context=_ctx())
        back = create_edge(b.entity, a.entity, LINK, {"weight": 2}, caller_context=_ctx())
        ctx = _ctx()
        result = delete_node(a.entity_id, caller_context=ctx)
        assert result.success, result.errors
        retiring = _bid(ctx)
        for entity_id in (a.entity_id, out.entity_id, back.entity_id):
            row = _row(entity_id)
            assert row.deleted_at is not None
            assert (row.last_changed_batch_id, row.last_observed_batch_id) == (retiring, retiring)
            assert row.last_observed_at == row.updated_at == row.deleted_at
        # It agrees with the per-field record of the same retirement.
        assert PgNode.all_objects.get(entity_id=a.entity_id).flip_map["deleted_at"] == str(retiring)
        for edge in (out, back):
            assert Edge.all_objects.get(entity_id=edge.entity_id).flip_map["deleted_at"] == str(retiring)
        # The other endpoint was not named by the delete and is untouched.
        assert _row(b.entity_id).last_changed_batch_id != retiring

    @AC[4]
    def test_a_repeat_delete_writes_nothing(self) -> None:
        node, _ = _create({"name": "gone"})
        first = _ctx()
        assert delete_node(node.entity_id, caller_context=first).success
        settled = {field: getattr(_row(node.entity_id), field) for field in POINTERS}
        assert delete_node(node.entity_id, caller_context=_ctx()).success
        assert {field: getattr(_row(node.entity_id), field) for field in POINTERS} == settled


@pytest.mark.django_db
class TestOneQueryPerBatch:
    @AC[5]
    def test_one_filter_returns_what_a_batch_last_changed_across_types(self) -> None:
        ctx = _ctx()
        made = write_batch(
            [
                WriteOperation(verb="create_node", type_slug=_TYPE, payload={"name": "kept"}),
                WriteOperation(verb="create_node", type_slug=_TYPE, payload={"name": "changed-later"}),
            ],
            caller_context=ctx,
            batch_name="two nodes",
            batch_description="two nodes and, below, an edge",
        )
        assert made.success, made.errors
        kept, later = (PgNode.objects.get(entity_id=r.entity_id) for r in made.results)
        edge = create_edge(kept.entity, later.entity, LINK, {"weight": 1}, caller_context=ctx)
        footprint = set(Entity.objects.filter(last_changed_batch_id=_bid(ctx)).values_list("pk", flat=True))
        assert footprint == {kept.entity_id, later.entity_id, edge.entity_id}
        assert {"edge", _TYPE} == set(
            Entity.objects.filter(last_changed_batch_id=_bid(ctx)).values_list("entity_type", flat=True)
        )
        # The pointer is the last writer, not a ledger (rule 7).
        assert patch_node(later.entity_id, {"kind": "moved"}, caller_context=_ctx()).success
        footprint = set(Entity.objects.filter(last_changed_batch_id=_bid(ctx)).values_list("pk", flat=True))
        assert footprint == {kept.entity_id, edge.entity_id}


@pytest.mark.django_db
class TestNoBatchNoWrite:
    @AC[7]
    def test_a_change_inside_the_pipeline_with_no_batch_is_refused(self) -> None:
        node, batch = _create({"name": "eth0"})
        before = _row(node.entity_id)
        prior = get_caller_context()
        set_caller_context(CallerContext(user=prior.user if prior else None))
        try:
            node.name = "eth1"
            with service_write_scope(), pytest.raises(ServiceEvidenceError, match="no batch in context"):
                node.save()
        finally:
            set_caller_context(prior)
        after = _row(node.entity_id)
        assert (after.version, after.last_changed_batch_id) == (before.version, batch)
        assert PgNode.objects.get(entity_id=node.entity_id).name == "eth0"

    @AC[7]
    def test_a_create_inside_the_pipeline_with_no_batch_is_refused(self) -> None:
        prior = get_caller_context()
        set_caller_context(CallerContext(user=prior.user if prior else None))
        count = Entity.objects.filter(entity_type=_TYPE).count()
        try:
            with service_write_scope(), pytest.raises(ServiceEvidenceError, match="no batch in context"):
                PgNode(name="orphan").save()
        finally:
            set_caller_context(prior)
        assert Entity.objects.filter(entity_type=_TYPE).count() == count


@pytest.mark.django_db
class TestNotImportable:
    @AC[8]
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("last_changed_batch_id", "01a00000-0000-7000-8000-00000000c0de"),
            ("last_observed_batch_id", "01a00000-0000-7000-8000-00000000c0de"),
            ("last_observed_at", "2026-11-22T00:00:00Z"),
        ],
    )
    def test_an_envelope_that_supplies_a_pointer_is_refused(self, field: str, value: str) -> None:
        entity_id = str(uuid.uuid4())
        node = _panel("p-smuggle", entity_id)
        node["entity"][field] = value
        result = grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[node])]))
        assert not result.success
        assert any(field in error.message for error in result.errors), [e.message for e in result.errors]
        assert not Entity.objects.filter(pk=entity_id).exists()


@pytest.mark.django_db
class TestSpineSyncCounted:
    @AC[9]
    def test_a_reimport_that_changes_only_dimensions_moves_last_changed(self) -> None:
        entity_id = str(uuid.uuid4())
        first = _import([_panel("p-dims", entity_id)])
        assert _row(entity_id).last_changed_batch_id == first
        second = _import([_panel("p-dims", entity_id, dimensions={})])
        row = _row(entity_id)
        assert (row.last_changed_batch_id, row.last_observed_batch_id) == (second, second)

    @AC[9]
    def test_a_reimport_that_renames_the_node_moves_last_changed_with_the_spine_name(self) -> None:
        # A panel's envelope name must equal its payload name, so a rename moves both; the spine
        # name is written by the importer's post-pass, and the pointer by the replace it rides on.
        entity_id = str(uuid.uuid4())
        _import([_panel("p-name", entity_id)])
        renamed = _panel("p-name", entity_id, name="A new name")
        renamed["node"]["name"] = "A new name"
        second = _import([renamed])
        row = _row(entity_id)
        assert row.name == "A new name"
        assert (row.last_changed_batch_id, row.last_observed_batch_id) == (second, second)


class TestSpineSurface:
    def test_the_three_follow_version_on_the_canonical_surface(self) -> None:
        names = Entity.SPINE_FIELD_NAMES
        at = names.index("version")
        assert names[at + 1 : at + 4] == POINTERS

    def test_observed_at_is_declared_after_updated_at(self) -> None:
        # The insert copies updated_at into last_observed_at; Django computes insert values in
        # declaration order, so the order is load-bearing.
        order = [field.name for field in Entity._meta.local_concrete_fields]
        assert order.index("last_observed_at") > order.index("updated_at")

    def test_the_pointers_are_plain_ids_and_the_two_batch_ids_are_indexed(self) -> None:
        fields = {field.name: field for field in Entity._meta.concrete_fields}
        for name in ("last_changed_batch_id", "last_observed_batch_id"):
            field = fields[name]
            assert field.get_internal_type() == "UUIDField" and not field.is_relation
            assert getattr(field, "db_index") is True  # noqa: B009
        assert getattr(fields["last_observed_at"], "db_index") is False  # noqa: B009

    @pytest.mark.django_db
    def test_the_envelope_carries_them(self) -> None:
        node, batch = _create({"name": "eth0"})
        surface = build_spine_surface(_row(node.entity_id))
        assert surface["last_changed_batch_id"] == str(batch)
        assert surface["last_observed_batch_id"] == str(batch)
        assert surface["last_observed_at"] == _row(node.entity_id).last_observed_at.isoformat()


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonReadsThem:
    @AC[10]
    def test_gryphon_filters_on_the_changing_batch_and_compares_the_observed_time(self) -> None:
        from tap_grid.gryphon import execute_gryphon_raw

        kept, batch = _create({"name": "kept"})
        other, _ = _create({"name": "other"})
        rows = execute_gryphon_raw(
            "MATCH (n:grid_fixtures__node) WHERE n.last_changed_batch_id = $batch "
            "RETURN n.entity_id AS id, n.last_observed_batch_id AS seen_by",
            {"batch": str(batch)},
        )["rows"]
        assert [(str(row["id"]), str(row["seen_by"])) for row in rows] == [(str(kept.entity_id), str(batch))]

        # "Not seen since": the other node is re-observed, the first is not.
        cutoff = _row(other.entity_id).last_observed_at + timedelta(microseconds=1)
        assert patch_node(other.entity_id, {"name": "other"}, caller_context=_ctx()).state == WRITE_UNCHANGED
        stale = execute_gryphon_raw(
            "MATCH (n:grid_fixtures__node) WHERE n.last_observed_at < $cutoff RETURN n.entity_id AS id",
            {"cutoff": cutoff.isoformat()},
        )["rows"]
        seen = execute_gryphon_raw(
            "MATCH (n:grid_fixtures__node) WHERE n.last_observed_at >= $cutoff RETURN n.entity_id AS id",
            {"cutoff": cutoff.isoformat()},
        )["rows"]
        assert str(kept.entity_id) in {str(row["id"]) for row in stale}
        assert {str(row["id"]) for row in seen} == {str(other.entity_id)}
