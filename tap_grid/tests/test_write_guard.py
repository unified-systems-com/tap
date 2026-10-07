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

import pytest
from django.contrib import admin
from django.test import RequestFactory, override_settings

from tap_auth.capabilities import ALL_CAPABILITY_NAMES, READ_CAPABILITY, WRITE_CAPABILITY
from tap_auth.enforcement import requires_capability
from tap_auth.errors import UnguardedOperation
from tap_grid.models import Entity, Search
from tap_grid.services import create_node, delete_node
from tap_grid.write_guard import (
    BELOW_PIPELINE_WRITERS,
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


@requires_capability(WRITE_CAPABILITY, operation="test_write_guard.gated_named_writer")
def _gated_named_write(writer: str, name: str) -> Entity:
    with below_pipeline_write(writer):
        return Entity.objects.create(entity_type="test", name=name)


@requires_capability(READ_CAPABILITY, operation="test_write_guard.read_gated_batch_writer")
def _read_gated_batch_write(name: str) -> Entity:
    with below_pipeline_write("batch"):
        return Entity.objects.create(entity_type="test", name=name)


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
def test_a_named_writer_under_a_gate_it_accepts_passes():
    made = _gated_named_write("batch", f"named-{uuid.uuid4()}")
    assert made.pk is not None


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_a_named_writer_with_no_gate_fails_closed():
    """The name says why a write skips the pipeline; it never says who may make it."""
    with below_pipeline_write("batch"), pytest.raises(UnguardedOperation, match="open gates: \\[\\]"):
        Entity.objects.create(entity_type="test", name=f"ungated-{uuid.uuid4()}")


@pytest.mark.spec("req-tap-auth-write-batch-routing")
def test_a_named_writer_under_a_gate_it_does_not_accept_fails_closed():
    with pytest.raises(UnguardedOperation, match="unguarded write"):
        _gated_named_write("purge", f"wrong-gate-{uuid.uuid4()}")
    with pytest.raises(UnguardedOperation, match="unguarded write"):
        _read_gated_batch_write(f"read-gate-{uuid.uuid4()}")


def test_an_unknown_writer_name_is_refused():
    with pytest.raises(ValueError, match="not a named below-pipeline writer"):
        with below_pipeline_write("anything_goes"):
            pass


def test_every_named_writer_has_a_reason_and_registered_gates():
    gates = _writer_gates()
    assert set(gates) == set(BELOW_PIPELINE_WRITERS)
    for writer, reason in BELOW_PIPELINE_WRITERS.items():
        assert reason.strip(), writer
        assert gates[writer], writer
        assert gates[writer] <= set(ALL_CAPABILITY_NAMES), (writer, gates[writer] - set(ALL_CAPABILITY_NAMES))
