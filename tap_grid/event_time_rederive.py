"""Re-derive the spine's event time from the typed rows (req-grid-entity-event-time rule 17).

``BaseModel.save`` keeps the three event columns and the row's ``tap.time`` dimension current on every changing write. A change to
a model's declaration reaches the rows already stored through this pass. It writes no history and
no version, because no typed value changed. It runs as a batch of its own and records, for every
row whose spine values it changes, a batch event of the ``maintenance`` type: the change has a
record that says what made it, and nothing reads that record as a sighting. The last-observed
pointers are left where they were, because no source or analyst named the objects.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from django.db import transaction

from tap_auth.capabilities import WRITE_CAPABILITY
from tap_auth.enforcement import requires_capability
from tap_grid.dimension_map import grid_derived_update, with_grid_derived
from tap_grid.event_time import SPINE_EVENT_FIELDS, TIME_DIMENSION, derive_for_instance
from tap_grid.write_guard import below_pipeline_write

if TYPE_CHECKING:
    from tap_grid.caller_context import CallerContext
    from tap_grid.models import Batch

BATCH_SOURCE = "grid:maintenance"
REASON = "event_time_rederive"
CHUNK = 2_000


@dataclass
class RederiveReport:
    """What one pass read and changed."""

    types: int = 0
    rows: int = 0
    changed: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    warnings: int = 0
    raced: int = 0
    batch_id: str | None = None


def _models(entity_types: Iterable[str] | None) -> list[Any]:
    from tap_grid.models import BaseModel
    from tap_grid.registry import get_model_class, list_entity_types

    wanted = sorted(list_entity_types()) if entity_types is None else list(entity_types)
    found = []
    for entity_type in wanted:
        try:
            model = get_model_class(entity_type)
        except KeyError as error:
            # A type asked for by name must exist: a typo that checked nothing would report clean.
            raise ValueError(f"{entity_type!r} is not a registered entity type") from error
        if isinstance(model, type) and issubclass(model, BaseModel) and entity_type != "batch":
            found.append(model)
    return found


@requires_capability(WRITE_CAPABILITY, operation="rederive_event_time")
def rederive_event_time(
    entity_types: Iterable[str] | None = None,
    *,
    caller_context: CallerContext | None = None,
) -> RederiveReport:
    """Re-derive ``Entity.event_*`` for every row of the named types (else every registered type).

    Writes only the rows whose three event columns or ``tap.time`` dimension differ from what their
    declaration now derives; a type that declares none has the columns emptied and the dimension
    removed. Retired rows are included: a retirement does not
    change when the thing happened. One transaction: the spine values, the batch and its events
    commit together or not at all. The batch is opened on the first change, so a pass that finds
    nothing to do leaves no batch behind.
    """
    from tap_grid.batch import close_batch, create_batch, record_batch_event
    from tap_grid.models import BatchEventType, Entity

    actor = caller_context.user if caller_context is not None else None
    report = RederiveReport()
    batch: Batch | None = None
    with transaction.atomic():
        for model in _models(entity_types):
            report.types += 1
            entity_type = model.ENTITY_TYPE
            rows = model.all_objects.select_related("entity").order_by("pk").iterator(chunk_size=CHUNK)
            for row in rows:
                report.rows += 1
                derived = derive_for_instance(row)
                report.warnings += len(derived.warnings)
                columns = derived.as_columns()
                moved = [name for name in SPINE_EVENT_FIELDS if getattr(row.entity, name) != columns[name]]
                stored_dims = row.entity.dimensions or {}
                new_dims = dict(with_grid_derived(stored_dims, derived.as_dimensions()))
                if new_dims != stored_dims:
                    time_update = grid_derived_update(derived.as_dimensions())
                    if time_update is not None:
                        # A key-level expression: it sets or removes the `tap.time` entry and touches
                        # no other dimension, which is all this writer is allowed (write_guard).
                        columns["dimensions"] = time_update
                        moved.append(f"dimensions[{TIME_DIMENSION}]")
                if not moved:
                    continue
                if batch is None:
                    batch = create_batch(
                        source=BATCH_SOURCE,
                        actor=actor,
                        name="Re-derive event time",
                        description=(
                            "Grid maintenance: the spine's event time re-derived from the typed rows "
                            "after a declaration change. No typed value changed, so no history and no "
                            "version were written; this batch observed nothing."
                        ),
                        metadata={"reason": REASON},
                    )
                    report.batch_id = str(batch.entity_id)
                with below_pipeline_write("event_time_rederive"):
                    # The named writer may write the three event columns and `dimensions` (for the
                    # `tap.time` dimension) and nothing else; no typed value changes.
                    # Only while the row is at the version it was read at: a save that changed it
                    # since has bumped `version` and written its own event time in that statement,
                    # which is newer than what this pass derived, and must not be overwritten.
                    written = Entity.objects.filter(  # TAP-WRITE-COV: event-time re-derive
                        pk=row.entity_id, version=row.entity.version
                    ).update(**columns)
                if not written:
                    report.raced += 1
                    continue
                record_batch_event(
                    row.entity,
                    BatchEventType.MAINTENANCE,
                    model_name=model.__name__,
                    actor=actor,
                    metadata={"reason": REASON, "fields": moved},
                    batch_id=report.batch_id,
                )
                report.changed += 1
                report.by_type[entity_type] = report.by_type.get(entity_type, 0) + 1
        if batch is not None:
            close_batch(batch)
    return report
