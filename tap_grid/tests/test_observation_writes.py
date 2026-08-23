"""Observation-aware write semantics — explicit-null preservation + FLIP-touch scope.

Covers req-grid-service-write-observation (realizing the field-observation convention's
write-path dependency, spec-grid-node.md req-grid-node-observation). These drive the
full service write pipeline, not update_flip_map in isolation.

Uses the neutral grid_fixtures PgNode — whose ``observed_at`` is a nullable field and
``kind`` a non-null one — so this core suite exercises the write pipeline without
depending on any domain plugin (grid_fixtures is present in every profile that runs
the suite; see tap.plugin_testing).
"""

import uuid

import pytest
from tap_plugin.grid_fixtures.models.pg_node import PgNode

from tap_grid.caller_context import CallerContext
from tap_grid.services import create_node, patch_node

_TYPE = "grid_fixtures__node"
# observed_at is a nullable field (exercises explicit-null clearing); kind is non-null
# (exercises null-drop). observed_at takes an ISO date-time string per the node schema.
_OBSERVED = "2026-01-01T00:00:00Z"


def _ctx() -> CallerContext:
    return CallerContext(batch_id=str(uuid.uuid7()))


@pytest.mark.django_db
class TestObservationWrites:
    def _create(self, payload: dict, ctx: CallerContext | None = None) -> tuple[PgNode, str]:
        ctx = ctx or _ctx()
        result = create_node(_TYPE, payload, caller_context=ctx)
        assert result.success, result.errors
        return PgNode.objects.get(entity_id=result.entity_id), ctx.batch_id

    def test_explicit_null_clears_and_stamps_flip(self):
        # observation-1: explicit null on a nullable field clears it...
        node, _ = self._create({"name": "eth0", "observed_at": _OBSERVED})
        ctx_b = _ctx()
        patch_node(node.entity_id, {"observed_at": None}, caller_context=ctx_b)
        node.refresh_from_db()
        assert node.observed_at is None
        # ...and earns a FLIP entry — a known unknown (a batch asserted the absence).
        assert node.flip_map.get("observed_at") == ctx_b.batch_id

    def test_omitted_field_leaves_flip_alone(self):
        # observation-3/5: an omitted field is neither applied nor re-stamped.
        node, batch_a = self._create({"name": "eth0", "observed_at": _OBSERVED})
        ctx_b = _ctx()
        patch_node(node.entity_id, {"name": "eth1"}, caller_context=ctx_b)
        node.refresh_from_db()
        assert node.flip_map.get("name") == ctx_b.batch_id
        assert node.flip_map.get("observed_at") == batch_a  # untouched

    def test_create_stamps_only_provided_fields(self):
        # observation-6: omitted fields get no FLIP entry (unknown unknown), not a default stamp.
        node, batch_a = self._create({"name": "eth0"})
        assert node.flip_map.get("name") == batch_a
        assert "observed_at" not in node.flip_map

    def test_flip_scoped_to_touched_on_patch(self):
        # observation-5: a patch stamps only the touched field, not the full surface.
        node, batch_a = self._create({"name": "eth0", "observed_at": _OBSERVED, "kind": "up"})
        ctx_b = _ctx()
        patch_node(node.entity_id, {"kind": "down"}, caller_context=ctx_b)
        node.refresh_from_db()
        assert node.flip_map.get("kind") == ctx_b.batch_id
        assert node.flip_map.get("name") == batch_a
        assert node.flip_map.get("observed_at") == batch_a

    @pytest.mark.spec("req-grid-service-write-observation-2")
    def test_null_on_non_null_field_dropped(self):
        # observation-2: a null on a non-null field is dropped (treated as absent), not an error.
        node, _ = self._create({"name": "eth0", "kind": "up"})
        result = patch_node(node.entity_id, {"kind": None}, caller_context=_ctx())
        assert result.success, result.errors
        node.refresh_from_db()
        assert node.kind == "up"  # unchanged — null dropped, not applied
