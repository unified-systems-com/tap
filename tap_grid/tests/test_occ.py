"""Tests for optimistic concurrency control across the service layer.

Covers:
  req-grid-service-batch-occ — pipeline guard + result shape
  req-grid-service-write-occ — patch/replace verb signatures
  req-grid-service-delete-occ — delete/purge verb signatures + tombstone idempotency

OCC contract: callers may pass `entity_expected_version` to mutating verbs.
The pipeline takes a SELECT FOR UPDATE on the target Entity row and verifies
`Entity.version` before any mutation. Conflict surfaces as
`entity_version_conflict` with detail payload {entity_expected_version,
actual_entity_version, entity_id}. Create verbs reject the parameter with
`entity_expected_version_not_allowed_on_create`.
"""

from __future__ import annotations

import uuid

import pytest
from tap_plugin.grid_fixtures.models import ConstrainedSource

from tap_grid.exceptions import ServiceVersionConflictError
from tap_grid.models import Edge, Entity
from tap_grid.service_types import WriteOperation
from tap_grid.services import (
    create_edge,
    create_node,
    delete_edge_by_entity,
    delete_node,
    patch_edge,
    patch_node,
    purge_edge,
    purge_node,
    replace_edge,
    replace_node,
    write_batch,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_character(name: str = "Frodo", description: str = "x") -> ConstrainedSource:
    return ConstrainedSource.objects.create(name=name, description=description)


def _make_edge(from_e: Entity, to_e: Entity, edge_type: str = "SYMMETRIC_LINK__grid_fixtures") -> Edge:
    return create_edge(from_e, to_e, edge_type)


def _version_of(entity_id) -> int:
    return Entity.objects.values_list("version", flat=True).get(pk=entity_id)


# ---------------------------------------------------------------------------
# Patch / replace nodes (req-grid-service-write-occ)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPatchReplaceNodeOCC:
    def test_patch_node_matching_version_succeeds(self):
        char = _make_character()
        v = _version_of(char.entity_id)
        result = patch_node(char.entity_id, {"description": "updated"}, entity_expected_version=v)
        assert result.success
        # Single-bump invariant: exactly one increment.
        assert _version_of(char.entity_id) == v + 1

    def test_patch_node_mismatched_version_returns_conflict(self):
        char = _make_character()
        v = _version_of(char.entity_id)
        result = patch_node(char.entity_id, {"description": "x"}, entity_expected_version=v + 99)
        assert not result.success
        assert result.errors[0].code == "entity_version_conflict"
        assert result.errors[0].detail == {
            "entity_expected_version": v + 99,
            "actual_entity_version": v,
            "entity_id": str(char.entity_id),
        }
        # No mutation: version unchanged.
        assert _version_of(char.entity_id) == v

    def test_patch_node_missing_entity_with_occ_is_conflict_not_not_found(self):
        missing = uuid.uuid4()
        result = patch_node(missing, {"description": "x"}, entity_expected_version=1)
        assert not result.success
        assert result.errors[0].code == "entity_version_conflict"
        assert result.errors[0].detail["actual_entity_version"] is None

    def test_patch_node_missing_entity_without_occ_is_not_found(self):
        missing = uuid.uuid4()
        result = patch_node(missing, {"description": "x"})
        assert not result.success
        assert result.errors[0].code == "not_found"

    def test_replace_node_matching_version_succeeds(self):
        char = _make_character()
        v = _version_of(char.entity_id)
        result = replace_node(char.entity_id, {"name": "Replaced", "description": "new"}, entity_expected_version=v)
        assert result.success
        assert _version_of(char.entity_id) == v + 1

    def test_replace_node_mismatched_version_returns_conflict(self):
        char = _make_character()
        v = _version_of(char.entity_id)
        result = replace_node(char.entity_id, {"name": "Replaced", "description": "new"}, entity_expected_version=v + 5)
        assert not result.success
        assert result.errors[0].code == "entity_version_conflict"
        assert result.errors[0].detail["entity_expected_version"] == v + 5
        assert result.errors[0].detail["actual_entity_version"] == v
        assert _version_of(char.entity_id) == v


@pytest.mark.django_db
class TestPatchReplaceEdgeOCC:
    def test_patch_edge_matching_version_succeeds(self):
        a = _make_character("a")
        b = _make_character("b")
        edge = _make_edge(a.entity, b.entity)
        v = _version_of(edge.entity_id)
        result = patch_edge(edge.entity_id, {"properties": {"x": 1}}, entity_expected_version=v)
        assert result.success
        assert _version_of(edge.entity_id) == v + 1

    def test_replace_edge_mismatched_version_returns_conflict(self):
        a = _make_character("a")
        b = _make_character("b")
        edge = _make_edge(a.entity, b.entity)
        v = _version_of(edge.entity_id)
        result = replace_edge(edge.entity_id, {"properties": {"x": 1}}, entity_expected_version=v + 1)
        assert not result.success
        assert result.errors[0].code == "entity_version_conflict"


# ---------------------------------------------------------------------------
# Delete verbs (req-grid-service-delete-occ)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeleteNodeOCC:
    def test_delete_node_matching_version_succeeds(self):
        char = _make_character()
        v = _version_of(char.entity_id)
        result = delete_node(char.entity_id, entity_expected_version=v)
        assert result.success
        # Tombstoned: version bumped + deleted_at set.
        e = Entity.objects.get(pk=char.entity_id)
        assert e.deleted_at is not None
        assert e.version == v + 1

    def test_delete_node_mismatched_version_returns_conflict(self):
        char = _make_character()
        v = _version_of(char.entity_id)
        result = delete_node(char.entity_id, entity_expected_version=v + 7)
        assert not result.success
        assert result.errors[0].code == "entity_version_conflict"
        # Not tombstoned — verify pre-conflict state preserved.
        e = Entity.objects.get(pk=char.entity_id)
        assert e.deleted_at is None
        assert e.version == v

    def test_delete_tombstoned_with_matching_version_is_noop_success(self):
        """Already-tombstoned + matching expected version = successful no-op.

        The spec's tombstone-idempotency rule (req-grid-service-delete-occ): delete
        is idempotent against tombstoned targets, and OCC does not change that.
        """
        char = _make_character()
        v = _version_of(char.entity_id)
        assert delete_node(char.entity_id, entity_expected_version=v).success
        v_after = _version_of(char.entity_id)
        result = delete_node(char.entity_id, entity_expected_version=v_after)
        assert result.success
        # Still tombstoned; the no-op did not disturb the row.
        e = Entity.objects.get(pk=char.entity_id)
        assert e.deleted_at is not None

    def test_delete_tombstoned_with_stale_version_is_conflict(self):
        """Already-tombstoned + mismatched expected version surfaces the conflict."""
        char = _make_character()
        v = _version_of(char.entity_id)
        assert delete_node(char.entity_id, entity_expected_version=v).success
        stale = v  # the pre-delete version — the tombstoning bumped it
        result = delete_node(char.entity_id, entity_expected_version=stale)
        assert not result.success
        assert result.errors[0].code == "entity_version_conflict"


@pytest.mark.django_db
class TestDeleteEdgeOCC:
    def test_delete_edge_matching_version_succeeds(self):
        a = _make_character("a")
        b = _make_character("b")
        edge = _make_edge(a.entity, b.entity)
        v = _version_of(edge.entity_id)
        result = delete_edge_by_entity(edge.entity_id, entity_expected_version=v)
        assert result.success
        e = Entity.objects.get(pk=edge.entity_id)
        assert e.deleted_at is not None


# ---------------------------------------------------------------------------
# Purge verbs (req-grid-service-delete-occ)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPurgeNodeOCC:
    def test_purge_node_matching_version_succeeds(self, settings):
        settings.DEBUG = True
        char = _make_character()
        v = _version_of(char.entity_id)
        result = purge_node(char.entity_id, entity_expected_version=v, reason="dev")
        assert result.success
        assert not Entity.objects.filter(pk=char.entity_id).exists()

    def test_purge_node_mismatched_version_raises_conflict(self, settings):
        settings.DEBUG = True
        char = _make_character()
        v = _version_of(char.entity_id)
        with pytest.raises(ServiceVersionConflictError) as exc_info:
            purge_node(char.entity_id, entity_expected_version=v + 1, reason="dev")
        assert exc_info.value.entity_expected_version == v + 1
        assert exc_info.value.actual_entity_version == v
        # Not purged.
        assert Entity.objects.filter(pk=char.entity_id).exists()

    def test_purge_node_missing_entity_with_occ_raises_conflict_not_not_found(self, settings):
        settings.DEBUG = True
        missing = uuid.uuid4()
        with pytest.raises(ServiceVersionConflictError) as exc_info:
            purge_node(missing, entity_expected_version=1, reason="dev")
        assert exc_info.value.actual_entity_version is None


@pytest.mark.django_db
class TestPurgeEdgeOCC:
    def test_purge_edge_matching_version_succeeds(self, settings):
        settings.DEBUG = True
        a = _make_character("a")
        b = _make_character("b")
        edge = _make_edge(a.entity, b.entity)
        v = _version_of(edge.entity_id)
        result = purge_edge(edge.entity_id, entity_expected_version=v, reason="dev")
        assert result.success
        assert not Entity.objects.filter(pk=edge.entity_id).exists()

    def test_purge_edge_mismatched_version_raises_conflict(self, settings):
        settings.DEBUG = True
        a = _make_character("a")
        b = _make_character("b")
        edge = _make_edge(a.entity, b.entity)
        v = _version_of(edge.entity_id)
        with pytest.raises(ServiceVersionConflictError):
            purge_edge(edge.entity_id, entity_expected_version=v + 1, reason="dev")
        assert Entity.objects.filter(pk=edge.entity_id).exists()


# ---------------------------------------------------------------------------
# Create verbs reject entity_expected_version (req-grid-service-write-occ-2)
# ---------------------------------------------------------------------------


@pytest.mark.spec("req-grid-service-write-occ-2")
@pytest.mark.django_db
class TestCreateVerbsRejectOCC:
    def test_create_node_via_write_batch_rejects_expected_version(self):
        op = WriteOperation(
            verb="create_node",
            type_slug="grid_fixtures__constrained_source",
            payload={"name": "Sam", "description": "x"},
            entity_expected_version=1,
        )
        result = write_batch([op])
        assert not result.success
        assert result.results[0].errors[0].code == "entity_expected_version_not_allowed_on_create"

    def test_create_node_via_public_verb_does_not_accept_kwarg(self):
        # The public create_node signature does not surface
        # entity_expected_version (per req-grid-service-write-occ).
        with pytest.raises(TypeError):
            create_node(  # type: ignore[call-arg]
                "grid_fixtures__constrained_source",
                {"name": "Pippin", "description": "x"},
                entity_expected_version=1,
            )

    def test_create_edge_via_write_batch_rejects_expected_version(self):
        a = _make_character("from")
        b = _make_character("to")
        op = WriteOperation(
            verb="create_edge",
            from_target=a.entity_id,
            to_target=b.entity_id,
            edge_type="SYMMETRIC_LINK__grid_fixtures",
            payload={"properties": {}},
            entity_expected_version=1,
        )
        result = write_batch([op])
        assert not result.success
        assert result.results[0].errors[0].code == "entity_expected_version_not_allowed_on_create"


# ---------------------------------------------------------------------------
# Batch interaction: a conflict on one op rolls back the whole batch
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOCCBatchRollback:
    def test_conflict_on_one_op_rolls_back_other_ops(self):
        # Two characters; we'll patch both in one batch, with a stale version
        # on the second. The first patch's version bump must be rolled back.
        char_a = _make_character("A")
        char_b = _make_character("B")
        v_a = _version_of(char_a.entity_id)
        v_b = _version_of(char_b.entity_id)

        op_a = WriteOperation(
            verb="patch_node",
            target=char_a.entity_id,
            payload={"description": "updated A"},
            entity_expected_version=v_a,
        )
        op_b_stale = WriteOperation(
            verb="patch_node",
            target=char_b.entity_id,
            payload={"description": "updated B"},
            entity_expected_version=v_b + 99,  # stale
        )
        result = write_batch([op_a, op_b_stale])
        assert not result.success
        # Neither bumped — atomic rollback.
        assert _version_of(char_a.entity_id) == v_a
        assert _version_of(char_b.entity_id) == v_b
        # The first op was rolled back; only the second has the conflict error.
        # (Pipeline bails on first failure; first op's result is success=True
        # but the rollback undid it.)
        char_a.refresh_from_db()
        assert char_a.description == "x"


# ---------------------------------------------------------------------------
# Single-bump invariant (req-grid-service-batch-occ-2)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSingleBumpInvariant:
    def test_patch_with_occ_bumps_exactly_once(self):
        char = _make_character()
        v0 = _version_of(char.entity_id)
        patch_node(char.entity_id, {"description": "first"}, entity_expected_version=v0)
        v1 = _version_of(char.entity_id)
        assert v1 == v0 + 1
        patch_node(char.entity_id, {"description": "second"}, entity_expected_version=v1)
        assert _version_of(char.entity_id) == v1 + 1

    def test_replace_with_occ_bumps_exactly_once(self):
        char = _make_character()
        v0 = _version_of(char.entity_id)
        replace_node(char.entity_id, {"name": "n", "description": "b"}, entity_expected_version=v0)
        assert _version_of(char.entity_id) == v0 + 1

    def test_delete_with_occ_bumps_exactly_once(self):
        char = _make_character()
        v0 = _version_of(char.entity_id)
        delete_node(char.entity_id, entity_expected_version=v0)
        assert _version_of(char.entity_id) == v0 + 1

    def test_omitting_expected_version_preserves_existing_behavior(self):
        char = _make_character()
        v0 = _version_of(char.entity_id)
        # No OCC declared — patch should succeed and bump.
        result = patch_node(char.entity_id, {"description": "no-occ"})
        assert result.success
        assert _version_of(char.entity_id) == v0 + 1
