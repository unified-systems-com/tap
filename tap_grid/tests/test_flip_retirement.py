"""Retirement is a FLIP-tracked state change (req-grid-flip-retirement).

A tombstone is written with a bulk update on the Entity spine, so the save-time FLIP
hook never sees it; the retirement path stamps ``flip_map["deleted_at"]`` itself, on the
retired node and on every edge it ends, in the tombstone's transaction.
"""

from __future__ import annotations

import uuid

import pytest

from tap_grid.models import Edge, Entity
from tap_grid.services import create_edge, create_node, delete_node

SOURCE = "grid_fixtures__constrained_source"
TARGET = "grid_fixtures__constrained_target"
CONTAINS = "CONSTRAINED_LINK__grid_fixtures"


def _node(entity_type: str, name: str) -> uuid.UUID:
    result = create_node(entity_type, {"name": name})
    assert result.success, result.errors
    assert result.entity_id is not None
    return uuid.UUID(str(result.entity_id))


def _edge(source: uuid.UUID, target: uuid.UUID) -> uuid.UUID:
    edge = create_edge(Entity.objects.get(pk=source), Entity.objects.get(pk=target), CONTAINS)
    return uuid.UUID(str(edge.entity_id))


def _flip(model: type, entity_id: uuid.UUID) -> dict[str, str]:
    row = model.all_objects.get(entity_id=entity_id)  # type: ignore[attr-defined]
    return dict(row.flip_map or {})


def _model(entity_type: str) -> type:
    from tap_grid.registry import get_model_class

    return get_model_class(entity_type)


@pytest.fixture
def containment(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_plugin.grid_fixtures.models import ConstrainedSource

    monkeypatch.setattr(ConstrainedSource, "CONTAINMENT_EDGES", (CONTAINS,), raising=False)


@pytest.mark.django_db
class TestFlipRetirement:
    @pytest.mark.spec("req-grid-flip-retirement-1")
    def test_plain_delete_records_the_retiring_batch_on_the_node(self) -> None:
        node = _node(SOURCE, "Numenor")
        result = delete_node(node)
        assert result.success, result.errors
        assert _flip(_model(SOURCE), node)["deleted_at"] == str(result.batch_id)

    @pytest.mark.spec("req-grid-flip-retirement-2")
    def test_plain_delete_records_the_retiring_batch_on_each_ended_edge(self) -> None:
        source = _node(SOURCE, "Gondolin")
        target = _node(TARGET, "Tirion")
        edge = _edge(source, target)
        result = delete_node(source)
        assert result.success, result.errors
        assert Entity.objects.get(pk=edge).deleted_at is not None
        assert _flip(Edge, edge)["deleted_at"] == str(result.batch_id)
        # The far node is a reference, not retired, and gains no entry.
        assert "deleted_at" not in _flip(_model(TARGET), target)

    @pytest.mark.spec("req-grid-flip-retirement-3")
    def test_contained_cascade_records_every_retired_node_and_edge(self, containment: None) -> None:
        source = _node(SOURCE, "Doriath")
        child = _node(TARGET, "Menegroth")
        edge = _edge(source, child)
        result = delete_node(source, cascade="contained")
        assert result.success, result.errors
        batch = str(result.batch_id)
        assert _flip(_model(SOURCE), source)["deleted_at"] == batch
        assert _flip(_model(TARGET), child)["deleted_at"] == batch
        assert _flip(Edge, edge)["deleted_at"] == batch

    @pytest.mark.spec("req-grid-flip-retirement-4")
    def test_a_failed_flip_write_rolls_the_tombstone_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        node = _node(SOURCE, "Ost-in-Edhil")

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("flip write refused")

        monkeypatch.setattr("tap_grid.services._impl._flip_record_retirement", _boom)
        try:
            result = delete_node(node)
        except RuntimeError:
            pass  # a propagated refusal is also a refusal
        else:
            assert not result.success
        assert Entity.objects.get(pk=node).deleted_at is None

    @pytest.mark.spec("req-grid-flip-retirement-5")
    def test_repeat_delete_leaves_the_entry_alone(self) -> None:
        node = _node(SOURCE, "Eregion")
        first = delete_node(node)
        assert first.success, first.errors
        second = delete_node(node)
        assert second.success, second.errors
        assert _flip(_model(SOURCE), node)["deleted_at"] == str(first.batch_id)
