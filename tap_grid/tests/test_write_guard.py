"""Proof of the write backstop (req-tap-auth-write-batch-routing).

The write analog of test_read_guard: a node/edge mutation that does not route
through the service layer (a direct `.save()`/`.create()`/`.delete()` from a view,
panel, command, etc.) fails closed, so the "everything routes through batches"
rule is a runtime invariant, not just convention.

These tests set `enforce_write_guard` so the autouse `unguarded_write()` test
hatch is OFF — the guard is live, as in production. Every other test in the suite
keeps the hatch (tests are the sanctioned below-service write zone).
"""

from __future__ import annotations

import uuid

import pytest
from django.test import override_settings

from tap_auth.errors import UnguardedOperation
from tap_grid.models import Entity, Search
from tap_grid.services import create_node, delete_node
from tap_grid.write_guard import service_write_scope, unguarded_write

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


def test_delete_and_purge_capabilities_are_write_class():
    """delete + purge (+ import) are write-class, so their @requires_capability
    decorator opens the service-write scope — an instance write inside them (the
    delete verbs' tombstone, purge's hard delete) passes the guard rather than
    tripping it."""
    from tap_grid.write_guard import WRITE_SCOPE_CAPABILITIES

    assert {"grid.write", "grid.delete", "grid.purge", "grid.import_grift"} <= WRITE_SCOPE_CAPABILITIES


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
