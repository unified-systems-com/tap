"""Test-only state setup for the grid's tests. Production code never imports this module.

The write pipeline (``tap_grid.services``) is the only way application code writes the Entity
spine (Issue# 957 - tap). A test sometimes needs a row to simply exist before the thing it is
testing happens: an edge endpoint, a node to hang a batch event or a purge off. Building that
row through the pipeline would drag a typed payload, a batch and provenance into a test that is
about none of them. This module is where such arranging lives, and nowhere else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tap_grid.models import Entity


def make_spine_entity(entity_type: str, name: str = "", **fields: Any) -> Entity:
    """A bare Entity spine row, written straight through the ORM: test-only state setup that
    bypasses the write pipeline on purpose.

    The row gets no batch, no provenance, no history, no domain row and no per-type gate; it
    simply exists. Use it to ARRANGE a test, never as the thing under test: a test whose
    assertion is about writing, deleting, the write guard, batches, provenance or tombstones
    goes through the service layer's verbs (``create_node``, ``delete_node``, ``create_edge`` …).

    It works only inside the test harness's sanctioned write hatch
    (``tap.pytest_harness._service_write_hatch``), so a test marked ``enforce_write_guard``
    cannot use it — by design.
    """
    from tap_grid.models import Entity

    return Entity.objects.create(entity_type=entity_type, name=name, **fields)
