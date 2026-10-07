"""Proof of the write backstop (req-tap-auth-write-batch-routing).

The write analog of test_read_guard: a graph-row mutation that does not go through the
write pipeline fails closed, so "everything routes through batches" is a runtime
invariant, not a convention. That covers a direct `.save()` / `.create()` / `.delete()`,
a queryset `update` / `delete` / `bulk_create`, and a gated helper that writes the ORM
itself: a permission gate is not a write scope (Issue# 959 - tap).

These tests set `enforce_write_guard` so the autouse `unguarded_write()` test hatch is OFF,
as in production. Every other test keeps the hatch, which stops at a gated body.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import cast

import pytest
from django.contrib import admin
from django.test import RequestFactory, override_settings

from tap_auth.capabilities import ALL_CAPABILITY_NAMES, READ_CAPABILITY, WRITE_CAPABILITY
from tap_auth.enforcement import requires_capability
from tap_auth.errors import UnguardedOperation
from tap_cares.models import Schedule
from tap_grid.batch import create_batch
from tap_grid.models import Batch, Entity, Search
from tap_grid.services import create_node, delete_node
from tap_grid.write_guard import (
    BELOW_PIPELINE_ENTITY_TYPES,
    BELOW_PIPELINE_WRITERS,
    BELOW_PIPELINE_WRITES,
    ROW_INSERT,
    _writer_gates,
    below_pipeline_write,
    service_write_scope,
    unguarded_write,
)

pytestmark = [pytest.mark.django_db, pytest.mark.enforce_write_guard]


def _node(name: str) -> Entity:
    """A node written through the write pipeline: with the guard live, the only way in."""
    made = create_node("grid_fixtures__node", {"name": name})
    assert made.success, made.errors
    assert made.entity_id is not None
    return Entity.objects.get(pk=made.entity_id)


# --- direct ORM writes outside the service layer fail closed ---------------


def test_direct_node_save_fails_closed():
    """A direct BaseModel.save() (create/update) outside a write scope raises."""
    with pytest.raises(UnguardedOperation, match="unguarded write"):
        Search().save()


def test_unguarded_write_emits_class_aware_security_flaw(caplog):
    """The write gate emits a `security` Flaw before failing closed, classed by the
    offending callsite — `code` here (this test frame is first-party TAP)."""
    import logging

    with caplog.at_level(logging.ERROR):
        with pytest.raises(UnguardedOperation):
            Search().save()

    flaws = [r for r in caplog.records if getattr(r, "message_code", None) == "FLAW"]
    assert flaws, "expected a FLAW record from the write gate"
    md = flaws[-1].message_data
    assert md["flaw_class"] == "code"
    assert md["flaw_tags"] == ["security"]
    assert md["invariant_id"] == "grid_write_service_layer_bypass"


def test_direct_entity_create_fails_closed():
    with pytest.raises(UnguardedOperation, match="unguarded write"):
        Entity.objects.create(entity_type="test", name="x")


def test_direct_entity_delete_fails_closed():
    entity = _node("x")  # via the pipeline (scoped)
    with pytest.raises(UnguardedOperation, match="unguarded write"):
        entity.delete()  # direct, outside a scope


# --- the sanctioned paths pass (create / update / delete / purge) ----------


def test_service_layer_create_and_delete_pass():
    entity = _node("x")  # create_node: grid.write scope
    assert entity.pk is not None
    result = delete_node(entity.pk, reason="operator")  # grid.delete scope — no raise
    assert result.success, result.errors
    # The delete verb tombstones: the row stays, marked deleted.
    entity.refresh_from_db()
    assert entity.deleted_at is not None


@override_settings(DEBUG=True)
def test_service_layer_purge_passes():
    """purge_node (grid.purge) runs to completion with the write guard live — the
    purge path is not spuriously blocked. DEBUG=True satisfies purge's own
    production gate."""
    from tap_grid.services import purge_node

    entity = _node("to-purge")  # create_node: grid.write scope
    result = purge_node(entity.pk, reason="write-guard proof")  # grid.purge scope
    assert result is not None
    assert not Entity.objects.filter(pk=entity.pk).exists()


def test_service_write_scope_permits_direct_save():
    with service_write_scope():
        e = Entity.objects.create(entity_type="test", name="scoped")
    assert e.pk is not None


def test_unguarded_write_hatch_permits_direct_save():
    with unguarded_write():
        e = Entity.objects.create(entity_type="test", name=f"hatched-{uuid.uuid4()}")
    assert e.pk is not None


# --- a permission gate is not a write scope (Issue# 959 - tap) --------------


@requires_capability(WRITE_CAPABILITY, operation="test_write_guard.gated_direct_create")
def _gated_direct_create(name: str) -> Entity:
    """A gated helper that writes the ORM itself: the shape the removed helpers had."""
    return Entity.objects.create(entity_type="test", name=name)


@requires_capability(WRITE_CAPABILITY, operation="test_write_guard.under_grid_write")
def _under_grid_write(writer: str, write: Callable[[], object]) -> object:
    with below_pipeline_write(writer):
        return write()


@requires_capability(READ_CAPABILITY, operation="test_write_guard.under_grid_read")
def _under_grid_read(writer: str, write: Callable[[], object]) -> object:
    with below_pipeline_write(writer):
        return write()


@requires_capability("cares.run_scheduler", operation="test_write_guard.under_run_scheduler")
def _under_run_scheduler(writer: str, write: Callable[[], object]) -> object:
    with below_pipeline_write(writer):
        return write()


@requires_capability("grid.import_grift", operation="test_write_guard.under_import_grift")
def _under_import_grift(writer: str, write: Callable[[], object]) -> object:
    with below_pipeline_write(writer):
        return write()


@requires_capability(WRITE_CAPABILITY, operation="test_write_guard.make_batch")
def _make_batch(name: str) -> Batch:
    return create_batch(name=name)


def _batch_spine(name: str) -> Entity:
    """A batch's spine row, written the way the batch writer writes it."""
    return cast(Entity, _under_grid_write("batch", lambda: Entity.objects.create(entity_type="batch", name=name)))


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_a_gated_helper_writing_the_orm_directly_fails_closed():
    with pytest.raises(UnguardedOperation, match="unguarded write"):
        _gated_direct_create(f"gated-{uuid.uuid4()}")


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_the_test_hatch_stops_at_a_gated_body():
    """The fixture hatch cannot hide a production bypass: inside the gate, the real rule holds."""
    with unguarded_write(), pytest.raises(UnguardedOperation, match="unguarded write"):
        _gated_direct_create(f"hatched-gated-{uuid.uuid4()}")


# --- queryset writes are guarded too ------------------------------------------


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_a_queryset_delete_outside_the_pipeline_fails_closed():
    entity = _node("queryset-delete")
    with pytest.raises(UnguardedOperation, match="queryset delete"):
        Entity.objects.filter(pk=entity.pk).delete()
    assert Entity.objects.filter(pk=entity.pk).exists()


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_a_queryset_update_outside_the_pipeline_fails_closed():
    entity = _node("queryset-update")
    with pytest.raises(UnguardedOperation, match="queryset update"):
        Entity.objects.filter(pk=entity.pk).update(name="renamed outside the pipeline")
    entity.refresh_from_db()
    assert entity.name == "queryset-update"


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_a_bulk_create_outside_the_pipeline_fails_closed():
    with pytest.raises(UnguardedOperation, match="queryset bulk_create"):
        Entity.objects.bulk_create([Entity(entity_type="test", name=f"bulk-{uuid.uuid4()}")])


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_admin_bulk_delete_fails_closed_at_runtime():
    """Admin's "delete selected" calls delete_queryset, which the runtime guard now refuses
    whatever the admin's permission configuration says."""
    entity = _node("admin-bulk-delete")
    model_admin = admin.site._registry[Entity]
    with pytest.raises(UnguardedOperation, match="queryset delete"):
        model_admin.delete_queryset(RequestFactory().post("/admin/"), Entity.objects.filter(pk=entity.pk))
    assert Entity.objects.filter(pk=entity.pk).exists()


# --- named below-pipeline writers ----------------------------------------------


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_a_named_writer_making_its_own_write_under_a_gate_it_accepts_passes():
    spine = _batch_spine(f"named-{uuid.uuid4()}")
    assert spine.pk is not None


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_a_named_writer_with_no_gate_fails_closed():
    """The name says why a write skips the pipeline; it never says who may make it."""
    with below_pipeline_write("batch"), pytest.raises(UnguardedOperation, match="open gates: \\[\\]"):
        Entity.objects.create(entity_type="batch", name=f"ungated-{uuid.uuid4()}")


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_a_named_writer_under_a_gate_it_does_not_accept_fails_closed():
    entity = _node("wrong-gate")
    with pytest.raises(UnguardedOperation, match="unguarded write"):
        _under_grid_write("purge", lambda: Entity.objects.filter(pk=entity.pk).delete())
    assert Entity.objects.filter(pk=entity.pk).exists()
    with pytest.raises(UnguardedOperation, match="unguarded write"):
        _under_grid_read("batch", lambda: Entity.objects.create(entity_type="batch", name=f"read-{uuid.uuid4()}"))


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_a_named_writer_cannot_make_a_write_it_is_not_named_for():
    """A writer's name binds what it may write, not only who may open it: "batch" cannot
    create an arbitrary node, and the scheduler's cursor cannot delete a spine row."""
    with pytest.raises(UnguardedOperation, match="save tap_grid.Entity"):
        _under_grid_write(
            "batch", lambda: Entity.objects.create(entity_type="test", name=f"not-a-batch-{uuid.uuid4()}")
        )
    entity = _node("not-a-cursor")
    with pytest.raises(UnguardedOperation, match="queryset delete tap_grid.Entity"):
        _under_run_scheduler("scheduler_cursor", lambda: Entity.objects.filter(pk=entity.pk).delete())
    assert Entity.objects.filter(pk=entity.pk).exists()


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_a_type_held_writer_touches_only_its_own_spine_rows():
    node = _node("not-bookkeeping")
    with pytest.raises(UnguardedOperation, match="queryset update tap_grid.Entity"):
        _under_grid_write("bookkeeping", lambda: Entity.objects.filter(pk=node.pk).update(name="renamed"))
    node.refresh_from_db()
    assert node.name == "not-bookkeeping"
    spine = _batch_spine(f"bookkept-{uuid.uuid4()}")
    _under_grid_write("bookkeeping", lambda: Entity.objects.filter(pk=spine.pk).update(name="bookkept"))
    spine.refresh_from_db()
    assert spine.name == "bookkept"


def test_an_unknown_writer_name_is_refused():
    with pytest.raises(ValueError, match="not a named below-pipeline writer"):
        with below_pipeline_write("anything_goes"):
            pass


def test_every_named_writer_has_a_reason_writes_and_registered_gates():
    gates = _writer_gates()
    assert set(gates) == set(BELOW_PIPELINE_WRITERS) == set(BELOW_PIPELINE_WRITES)
    assert set(BELOW_PIPELINE_ENTITY_TYPES) <= set(BELOW_PIPELINE_WRITERS)
    for writer, reason in BELOW_PIPELINE_WRITERS.items():
        assert reason.strip(), writer
        assert BELOW_PIPELINE_WRITES[writer], writer
        assert gates[writer], writer
        assert gates[writer] <= set(ALL_CAPABILITY_NAMES), (writer, gates[writer] - set(ALL_CAPABILITY_NAMES))


# --- a named writer writes only the fields it is named for (Issue# 980 - tap) ----


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_a_named_writer_updates_only_the_fields_it_is_named_for():
    with pytest.raises(UnguardedOperation, match="queryset update tap_cares.Schedule"):
        _under_run_scheduler(
            "scheduler_cursor", lambda: Schedule.objects.filter(pk=uuid.uuid4()).update(**{"name": "x"})
        )
    _under_run_scheduler(
        "scheduler_cursor", lambda: Schedule.objects.filter(pk=uuid.uuid4()).update(**{"enabled_at": None})
    )
    with pytest.raises(UnguardedOperation, match="queryset update tap_grid.Entity"):
        _under_import_grift("spine_sync", lambda: Entity.objects.filter(pk=uuid.uuid4()).update(version=7))


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_no_named_writer_changes_a_rows_entity_type():
    spine = _batch_spine(f"typed-{uuid.uuid4()}")
    with pytest.raises(UnguardedOperation, match="queryset update tap_grid.Entity"):
        _under_grid_write("bookkeeping", lambda: Entity.objects.filter(pk=spine.pk).update(entity_type="test"))
    spine.refresh_from_db()
    assert spine.entity_type == "batch"
    for writer, writes in BELOW_PIPELINE_WRITES.items():
        for target, fields in writes.items():
            assert "entity_type" not in fields, (writer, target)


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_a_named_writer_saves_only_the_fields_it_is_named_for():
    batch = _make_batch(f"fields-{uuid.uuid4()}")
    with pytest.raises(UnguardedOperation, match="save tap_grid.Batch"):
        _under_grid_write("batch", lambda: batch.save(update_fields=["metadata"]))
    with pytest.raises(UnguardedOperation, match="save tap_grid.Batch"):
        _under_grid_write("bookkeeping", lambda: batch.save(update_fields=["status"]))
    with pytest.raises(UnguardedOperation, match="save tap_grid.Batch"):
        _under_grid_write("bookkeeping", lambda: batch.save())
    batch.metadata = {"note": "bookkept"}
    _under_grid_write("bookkeeping", lambda: batch.save(update_fields=["metadata"]))
    batch.refresh_from_db()
    assert batch.metadata == {"note": "bookkept"}


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_only_a_writer_named_for_inserts_creates_a_row():
    spine = _batch_spine(f"insert-{uuid.uuid4()}")
    with pytest.raises(UnguardedOperation, match="save tap_grid.Batch"):
        _under_grid_write("bookkeeping", lambda: Batch(entity=spine, name="not bookkeeping's", source="test").save())


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_a_writer_named_for_inserts_cannot_overwrite_a_row_by_reusing_its_id():
    """A fresh instance carrying an existing id is still "adding"; saving it can update that row.
    Only a forced insert counts as creating a row."""
    node = _node("existing")
    with pytest.raises(UnguardedOperation, match="save tap_grid.Entity"):
        _under_grid_write(
            "batch", lambda: Entity(id=node.pk, entity_type="batch", name="overwritten").save(force_update=True)
        )
    with pytest.raises(UnguardedOperation, match="save tap_grid.Entity"):
        _under_grid_write("batch", lambda: Entity(id=node.pk, entity_type="batch", name="overwritten").save())
    node.refresh_from_db()
    assert (node.entity_type, node.name) == ("grid_fixtures__node", "existing")


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_a_writer_named_for_inserts_cannot_overwrite_a_batch_by_reusing_its_id():
    """The same rule on ``BaseModel.save``, which Batch inherits: the batch writer may create a
    Batch, not overwrite one."""
    existing = _make_batch(f"existing-{uuid.uuid4()}")
    with pytest.raises(UnguardedOperation, match="save tap_grid.Batch"):
        _under_grid_write(
            "batch",
            lambda: Batch(pk=existing.pk, entity=existing.entity, name="overwritten", source="test").save(
                force_update=True
            ),
        )
    with pytest.raises(UnguardedOperation, match="save tap_grid.Batch"):
        _under_grid_write(
            "batch", lambda: Batch(pk=existing.pk, entity=existing.entity, name="overwritten", source="test").save()
        )
    existing.refresh_from_db()
    assert existing.name != "overwritten"


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_a_save_naming_fields_on_a_new_instance_is_checked_as_the_insert_it_can_be(
    monkeypatch: pytest.MonkeyPatch,
):
    """Django inserts a new instance whose key has a default even when ``update_fields`` names
    fields (``Model._save_table``), so a writer named only for updates cannot create a row that
    way. No shipped writer may update an Entity by save; this one is granted ``name`` only."""
    import tap_grid.write_guard as write_guard

    grants = {**write_guard.BELOW_PIPELINE_WRITES["bookkeeping"], ("save", "tap_grid.Entity"): frozenset({"name"})}
    monkeypatch.setitem(write_guard.BELOW_PIPELINE_WRITES, "bookkeeping", grants)
    name = f"inserted-{uuid.uuid4()}"
    with pytest.raises(UnguardedOperation, match="save tap_grid.Entity"):
        _under_grid_write("bookkeeping", lambda: Entity(entity_type="batch", name=name).save(update_fields=["name"]))
    assert not Entity.objects.filter(name=name).exists()
    # A loaded row saved with the fields it is granted is an update, and still allowed.
    spine = _batch_spine(f"renamed-{uuid.uuid4()}")
    spine.name = name
    _under_grid_write("bookkeeping", lambda: spine.save(update_fields=["name"]))
    spine.refresh_from_db()
    assert spine.name == name


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_an_upsert_is_checked_as_the_insert_and_the_update_it_can_be(monkeypatch: pytest.MonkeyPatch):
    """bulk_create(update_conflicts=True) inserts the rows that do not conflict and updates those
    that do, so it needs both the right to insert and the fields. No shipped writer may
    bulk-create; this one is granted inserts only, then fields only."""
    import tap_grid.write_guard as write_guard

    grants = {
        **write_guard.BELOW_PIPELINE_WRITES["batch"],
        ("queryset bulk_create", "tap_grid.Entity"): frozenset({ROW_INSERT}),
    }
    monkeypatch.setitem(write_guard.BELOW_PIPELINE_WRITES, "batch", grants)
    spine = _batch_spine(f"upsert-{uuid.uuid4()}")
    with pytest.raises(UnguardedOperation, match="queryset bulk_create tap_grid.Entity"):
        _under_grid_write(
            "batch",
            lambda: Entity.objects.bulk_create(
                [Entity(id=spine.pk, entity_type="batch", name="upserted")],
                update_conflicts=True,
                update_fields=["name"],
                unique_fields=["id"],
            ),
        )
    # The same upsert with its options passed by position, which Django accepts.
    with pytest.raises(UnguardedOperation, match="queryset bulk_create tap_grid.Entity"):
        _under_grid_write(
            "batch",
            lambda: Entity.objects.bulk_create(
                [Entity(id=spine.pk, entity_type="batch", name="upserted")], None, False, True, ["name"], ["id"]
            ),
        )
    # An upsert naming no fields is refused by the guard, as an update without fields is.
    with pytest.raises(UnguardedOperation, match="queryset bulk_create tap_grid.Entity"):
        _under_grid_write(
            "batch",
            lambda: Entity.objects.bulk_create(
                [Entity(id=spine.pk, entity_type="batch", name="upserted")], update_conflicts=True, unique_fields=["id"]
            ),
        )
    spine.refresh_from_db()
    assert spine.name != "upserted"
    made = _under_grid_write(
        "batch", lambda: Entity.objects.bulk_create([Entity(entity_type="batch", name=f"bulk-{uuid.uuid4()}")])
    )
    assert made
    # It may insert too: a writer granted the fields but not inserts is refused one.
    monkeypatch.setitem(
        write_guard.BELOW_PIPELINE_WRITES,
        "batch",
        {**grants, ("queryset bulk_create", "tap_grid.Entity"): frozenset({"name"})},
    )
    name = f"upsert-insert-{uuid.uuid4()}"
    with pytest.raises(UnguardedOperation, match="queryset bulk_create tap_grid.Entity"):
        _under_grid_write(
            "batch",
            lambda: Entity.objects.bulk_create(
                [Entity(entity_type="batch", name=name)],
                update_conflicts=True,
                update_fields=["name"],
                unique_fields=["id"],
            ),
        )
    assert not Entity.objects.filter(name=name).exists()
