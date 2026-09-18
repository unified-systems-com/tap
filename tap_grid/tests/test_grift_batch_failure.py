"""A batch-level write failure fails the import batch (Codex, Issue# 605 - tap).

``write_batch`` runs the batch's operations inside its own transaction; an unexpected
exception (or a deadlock) rolls that transaction back and comes back as
``BatchWriteResult.errors`` with every per-op result that preceded it still marked
success. The importer used to read only the per-op results, so it counted those as
imported, synced envelope name and dimensions onto the spine, and closed the batch —
committing spine changes on top of a rollback and reporting success. Now the batch fails,
nothing it touched persists, and the batch-level error is surfaced.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tap_grid.grift import grift_import
from tap_grid.models import Batch, BatchEvent, Entity
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc

pytestmark = pytest.mark.django_db

WEB = {"tap.graph": "web"}


def _panel(entity_id: str, slug: str, name: str, dims: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "entity": {
            "entity_id": entity_id,
            "entity_type": "panel",
            "name": name,
            "dimensions": WEB if dims is None else dims,
        },
        "node": {"name": name, "slug": slug, "description": "", "view": "tap_web/panel_error.html"},
    }


def _boom(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("injected batch-level failure")


@pytest.mark.parametrize(
    "seam",
    ["_drain_hotlink_checks_into_results", "_execute_write_pipeline"],
    ids=["after-every-op-succeeded", "before-any-op-ran"],
)
def test_a_batch_level_write_failure_fails_the_batch_and_persists_nothing(
    monkeypatch: pytest.MonkeyPatch, seam: str
) -> None:
    """Two shapes: the failure arrives after every per-op result succeeded (non-empty results),
    or before any op ran (empty results). Both must leave the existing row untouched — including
    the spine fields the envelope wanted to change — record nothing, and surface the error."""
    existing = str(uuid.uuid7())
    assert grift_import(
        _minimal_doc([_batch_container(_batch_entity_id(), nodes=[_panel(existing, "p", "Before")])])
    ).success
    row = Entity.objects.get(pk=uuid.UUID(existing))
    version, name, dims = row.version, row.name, dict(row.dimensions)
    entities_before, events_before = Entity.objects.count(), BatchEvent.objects.count()

    import tap_grid.services as services

    monkeypatch.setattr(services, seam, _boom)
    bid = _batch_entity_id()
    # A replace that also asks the spine to move: new name and new dimensions.
    result = grift_import(
        _minimal_doc([_batch_container(bid, nodes=[_panel(existing, "p", "After", {"tap.graph": "moved"})])])
    )

    assert not result.success
    assert result.counts.batches_imported == 0
    assert any(
        i.code == "execution_failed" and "internal_error" in i.message and "injected" in i.message
        for i in result.errors
    )
    assert all(i.batch_entity_id == bid for i in result.errors)
    row.refresh_from_db()
    assert (row.version, row.name, dict(row.dimensions)) == (version, name, dims), "nothing about the row moved"
    assert Entity.objects.count() == entities_before and BatchEvent.objects.count() == events_before
    assert not Batch.objects.filter(entity_id=bid).exists(), "the failed batch's row did not survive"
