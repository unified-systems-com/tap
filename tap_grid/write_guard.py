"""Structural write backstop: a graph-row write must go through the write pipeline.

The architectural rule (CLAUDE.md, spec-grid-service): every mutation of a
TAP-managed node or edge goes through the write pipeline, `write_batch`, so it
carries batch scope, FLIP, provenance and the per-operation capability backstop.
A direct `instance.save()` / `Model.objects.create()` / `entity.delete()` /
`queryset.delete()` from a view, panel, collector, command, or a gated helper
bypasses all of that.

This is the write analog of the read backstop (`tap_grid/read_guard.py`). The read
guard asks "does the actor hold grid.read"; this one asks **"is this write the
pipeline's, or one of the named writers that sit below it"**. It passes a graph-row
write only inside one of:

- **the pipeline's scope** (`service_write_scope`), opened by `write_batch` and by
  nothing else;
- **a named below-pipeline writer** (`below_pipeline_write(name)`), one of the
  closed set in `BELOW_PIPELINE_WRITERS`, each a bookkeeping or removal path the
  pipeline itself cannot carry. The name is recorded so a failure says which writer
  was, or was not, open.

A permission gate is not a scope. Until Issue# 959 - tap, `requires_capability` and
`authorized` opened the scope for any write-class capability, so a gated helper could
write the ORM directly and pass: that is how the compatibility helpers removed in
Issue# 957 - tap got through. A gate now opens nothing, and its body runs under the
real rule even inside a test (`gated_body`).

`BaseModel.save`/`delete`, `Entity.save`/`delete` and the graph querysets'
`update`/`delete`/`bulk_create`/`bulk_update` call `enforce_service_write`, which
fails closed (`UnguardedOperation`, a defect-class error → 500, not a user denial)
outside those scopes.

Exemptions:
- `unguarded_write()` — the test harness's hatch. Every test runs inside it, so
  fixtures can set up rows directly, but it stops at a gated service function's
  body: production code reached from a test is held to the real rule.
- Migrations are exempt automatically: migration-state/historical models are
  reconstructed without the `BaseModel`/`Entity` method overrides, so they never
  reach this guard.

See req-tap-auth-write-batch-routing.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import uuid
from collections.abc import Callable, Iterable, Iterator

logger = logging.getLogger(__name__)

# The writers that write graph rows below the pipeline, each for a reason the pipeline
# cannot carry. Closed: `below_pipeline_write` refuses any other name, so a new one is a
# reviewed edit here and in req-tap-auth-write-batch-routing, never a call-site invention.
# A named writer passes the guard only for the writes it exists for (`BELOW_PIPELINE_WRITES`,
# and `BELOW_PIPELINE_ENTITY_TYPES` for the spine rows it may touch), and only while a gate it
# accepts is open (`_writer_gates`): the name says why the write skips the pipeline and what it
# may write, the gate says who may make it.
BELOW_PIPELINE_WRITERS: dict[str, str] = {
    "batch": "a batch's own spine row and its open/close bookkeeping: a batch cannot be written in a batch",
    "purge": "the DEBUG-only hard purge, which removes rows the pipeline only tombstones",
    "sweep_purge": "the GRIFT importer's force-reimport sweep in purge mode",
    "bookkeeping": "the run records on a lifecycle batch: completeness, candidates, verdicts and links",
    "spine_sync": (
        "the GRIFT importer's copy of a replaced node's envelope name and dimensions onto its spine row; "
        "the replace in the same batch carries the version bump and the update event"
    ),
    "scheduler_cursor": "the scheduler's own cursors on a Schedule: the claim of a due slot and the enable stamp",
}

# The writes each named writer may make: (operation, model label) mapped to the fields it may
# write there (Issue# 980 - tap). A save is checked against its ``update_fields``, and creating a
# row is allowed only where ``ROW_INSERT`` is listed; a queryset update is checked against its
# keyword arguments; a delete writes no fields. No writer may change ``entity_type``.
ROW_INSERT = "<insert>"
# The spine fields a BaseModel save keeps in step on its own Entity row (`BaseModel.save`).
_SPINE_SYNC_FIELDS = frozenset({"updated_at", "version", "name"})
BELOW_PIPELINE_WRITES: dict[str, dict[tuple[str, str], frozenset[str]]] = {
    "batch": {
        ("save", "tap_grid.Entity"): frozenset({ROW_INSERT}),
        ("save", "tap_grid.Batch"): frozenset(
            {ROW_INSERT, "status", "closed_at", "error_message", "name", "description"}
        ),
        ("queryset update", "tap_grid.Entity"): _SPINE_SYNC_FIELDS,
    },
    "purge": {("queryset delete", "tap_grid.Entity"): frozenset()},
    "sweep_purge": {("queryset delete", "tap_grid.Entity"): frozenset()},
    "bookkeeping": {
        ("save", "tap_grid.Batch"): frozenset({"metadata"}),
        ("queryset update", "tap_grid.Entity"): _SPINE_SYNC_FIELDS,
    },
    "spine_sync": {("queryset update", "tap_grid.Entity"): frozenset({"name", "dimensions", "updated_at"})},
    "scheduler_cursor": {("queryset update", "tap_cares.Schedule"): frozenset({"last_schedule_fired", "enabled_at"})},
}

# Writers that may touch spine (`tap_grid.Entity`) rows of these entity types only. A writer
# not listed here may touch any type its writes allow (purge, sweep_purge and spine_sync act on
# whatever node or edge they were asked about).
BELOW_PIPELINE_ENTITY_TYPES: dict[str, frozenset[str]] = {
    "batch": frozenset({"batch"}),
    "bookkeeping": frozenset({"batch"}),
}


def _writer_gates() -> dict[str, frozenset[str]]:
    """The gates (capabilities) under which each named writer may write.

    Built on call, not at import: tap_auth.enforcement imports this module at module scope,
    so importing tap_auth.capabilities here at module scope would close the cycle.
    """
    from tap_auth import capabilities as caps

    grid_writes = frozenset(
        {
            caps.WRITE_CAPABILITY,
            caps.DELETE_CAPABILITY,
            caps.RECONCILE_CAPABILITY,
            caps.PURGE_CAPABILITY,
            caps.IMPORT_GRIFT_CAPABILITY,
        }
    )
    return {
        "batch": grid_writes,
        "purge": frozenset({caps.PURGE_CAPABILITY}),
        "sweep_purge": frozenset({caps.IMPORT_GRIFT_CAPABILITY}),
        "bookkeeping": frozenset({caps.WRITE_CAPABILITY, caps.RECONCILE_CAPABILITY}),
        "spine_sync": frozenset({caps.IMPORT_GRIFT_CAPABILITY}),
        # The scheduler's capabilities are spelled where its gates are (tap_cares.services.
        # scheduler); test_write_guard checks each name here is a registered capability.
        "scheduler_cursor": frozenset({"cares.run_scheduler", "cares.toggle_schedules"}),
    }


# True while control is inside the pipeline's scope (nestable — token-based set/reset, so
# an inner scope restores the outer's value on exit). Opened by `write_batch` alone.
_service_write_active: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "service_write_active",
    default=False,
)

# The named below-pipeline writer open around the current code, if any.
_below_pipeline_writer: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "below_pipeline_writer",
    default=None,
)

# The capabilities of the gates open around the current code, outermost first. A gate is
# pushed by `gated_body` after the gate has authorized its capability.
_open_gates: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "open_gates",
    default=(),
)

# True while the test harness's hatch is open (and not suspended by a gated body).
_write_guard_bypass: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "write_guard_bypass",
    default=False,
)


# The targets the reconcile verb's apply pass has licensed (req-grid-reconcile-verb): the one
# place a delete may be licensed by `grid.reconcile` rather than `grid.delete` — and only for
# the rows the verb names. None outside the pass. Opened per write by `tap_grid.reconcile`;
# the delete backstop in tap_auth.enforcement consults it with the delete ops' targets.
_reconcile_licensed_targets: contextvars.ContextVar[frozenset[str] | None] = contextvars.ContextVar(
    "reconcile_licensed_targets",
    default=None,
)


@contextlib.contextmanager
def reconcile_write_scope(targets: Iterable[str | uuid.UUID]) -> Iterator[None]:
    """Mark the wrapped block as the reconcile verb's apply pass for exactly ``targets``.

    Inside it, and only inside it, the write pipeline's delete backstop accepts
    `grid.reconcile` in place of `grid.delete` — for a delete whose every target is one
    of ``targets``, and for nothing else. Reconciliation's tombstones are the verb's own
    writes, licensed by its own capability and bound to the verdict's row: a collector
    actor that holds `grid.reconcile` but not `grid.delete` still cannot delete anywhere
    else, and a defect in the verb cannot widen a verdict past the row it judged. Empty
    ``targets`` license nothing.

    Opened by `tap_grid.reconcile._apply` around each write; nothing else should open it.
    It is a contextvar, not a capability: in-process code could open it, exactly as it
    could `unguarded_write`, so — like that hatch — it is a lint-guarded trust boundary
    (the collectors-never-retire walk forbids naming it), stated as such.
    """
    token = _reconcile_licensed_targets.set(frozenset(str(t) for t in targets))
    try:
        yield
    finally:
        _reconcile_licensed_targets.reset(token)


def reconcile_licenses(targets: Iterable[str | uuid.UUID]) -> bool:
    """True iff the reconcile apply scope is open and licenses every one of ``targets``
    (which must name at least one row)."""
    licensed = _reconcile_licensed_targets.get()
    wanted = {str(t) for t in targets}
    return licensed is not None and bool(wanted) and wanted <= licensed


@contextlib.contextmanager
def service_write_scope() -> Iterator[None]:
    """Mark the wrapped block as the write pipeline.

    Graph-row writes inside it pass the write guard. `write_batch` opens it, and nothing
    else should: code that needs to write calls `write_batch`, or is one of the named
    writers in `BELOW_PIPELINE_WRITERS`.
    """
    token = _service_write_active.set(True)
    try:
        yield
    finally:
        _service_write_active.reset(token)


@contextlib.contextmanager
def below_pipeline_write(writer: str) -> Iterator[None]:
    """Mark the wrapped block as the named below-pipeline writer ``writer``.

    Graph-row writes inside it pass the write guard. ``writer`` must be a key of
    `BELOW_PIPELINE_WRITERS`; any other name raises ValueError before the block runs,
    so the set of writers that skip the pipeline stays the reviewed one.
    """
    if writer not in BELOW_PIPELINE_WRITERS:
        raise ValueError(f"{writer!r} is not a named below-pipeline writer; see BELOW_PIPELINE_WRITERS")
    token = _below_pipeline_writer.set(writer)
    try:
        yield
    finally:
        _below_pipeline_writer.reset(token)


@contextlib.contextmanager
def gated_body(capability: str) -> Iterator[None]:
    """Hold a gated service function's body to the real write rule, inside a test too.

    Opened by `requires_capability` and `authorized` around the body they guard, after the
    gate has authorized ``capability``. It records the gate, so a named below-pipeline
    writer inside the body can pass, and it closes the test harness's hatch for the body,
    so a gated helper that writes the ORM directly fails in the test suite as it would in
    production. It opens no write scope: a gate is a permission check, not the pipeline.
    """
    bypass = _write_guard_bypass.set(False)
    gates = _open_gates.set((*_open_gates.get(), capability))
    try:
        yield
    finally:
        _open_gates.reset(gates)
        _write_guard_bypass.reset(bypass)


@contextlib.contextmanager
def unguarded_write() -> Iterator[None]:
    """Suspend the write guard for the wrapped block: the test harness's hatch.

    For test fixtures that set up rows directly. It does not reach into a gated service
    function's body (`gated_body` closes it there). NOT for application code: views,
    panels, collectors and commands write through `write_batch`.
    """
    token = _write_guard_bypass.set(True)
    try:
        yield
    finally:
        _write_guard_bypass.reset(token)


def _writer_permits(
    writer: str,
    operation: str,
    model_label: str,
    row_types: Callable[[], Iterable[str]] | None,
    fields: Iterable[str] | None,
    inserting: bool,
) -> bool:
    """True iff the named ``writer`` may make this write under the gates open now."""
    if not _writer_gates()[writer].intersection(_open_gates.get()):
        return False
    allowed_fields = BELOW_PIPELINE_WRITES[writer].get((operation, model_label))
    if allowed_fields is None:
        return False
    if not _fields_permitted(operation, allowed_fields, fields, inserting):
        return False
    allowed_types = BELOW_PIPELINE_ENTITY_TYPES.get(writer)
    if allowed_types is None or model_label != "tap_grid.Entity":
        return True
    # A writer held to some entity types must be able to show the rows are of those types.
    return row_types is not None and set(row_types()) <= allowed_types


def _fields_permitted(
    operation: str, allowed_fields: frozenset[str], fields: Iterable[str] | None, inserting: bool
) -> bool:
    """True iff the write touches only fields its writer may write (Issue# 980 - tap)."""
    if operation in {"delete", "queryset delete"}:
        return True
    if inserting:
        return ROW_INSERT in allowed_fields
    if fields is None:
        # A save with no update_fields writes every column: no named writer may do that.
        return False
    written = set(fields)
    return "entity_type" not in written and written <= allowed_fields - {ROW_INSERT}


def enforce_service_write(
    operation: str,
    model_label: str,
    *,
    row_types: Callable[[], Iterable[str]] | None = None,
    fields: Iterable[str] | None = None,
    inserting: bool = False,
) -> None:
    """Fail closed if a graph-row write is happening outside the pipeline.

    Passes iff the pipeline's scope is open; or a named below-pipeline writer is open that
    permits this write (its operation, model and fields, and for a type-held writer the rows'
    entity types) under a gate it accepts; or the test hatch is open (and not closed by a gated body).
    Otherwise raises `UnguardedOperation` — a defect (some code mutated the grid by direct ORM
    instead of the pipeline), not a user-facing denial.

    Args:
        operation: The write: ``save``, ``delete``, or ``queryset update`` / ``queryset delete``
            / ``queryset bulk_create`` / ``queryset bulk_update``.
        model_label: The model written, e.g. ``tap_grid.Entity``.
        row_types: For spine rows, a callable returning the entity types written. Called only
            when a type-held named writer is open.
        fields: The fields written: a save's ``update_fields``, a queryset update's keyword
            arguments. None for a save that writes every column.
        inserting: True when the write creates the row.
    """
    detail = f"{operation} {model_label}"
    if _write_guard_bypass.get() or _service_write_active.get():
        return
    writer = _below_pipeline_writer.get()
    if writer is not None and _writer_permits(writer, operation, model_label, row_types, fields, inserting):
        return

    from tap.flaws import report_service_layer_bypass
    from tap_auth.errors import UnguardedOperation

    # Emit the class-aware security Flaw before failing closed: `code` if the
    # offending write lives in first-party TAP, `app` if in a plugin — so the
    # blame domain is on the record without anyone reading the stack.
    report_service_layer_bypass(
        invariant_id="grid_write_service_layer_bypass",
        message=f"unguarded write: {detail} bypassed the service layer",
        logger=logger,
        detail=detail,
    )
    raise UnguardedOperation(
        f"unguarded write: {detail} bypassed the write pipeline — graph-row mutations go "
        f"through write_batch (or a service verb that calls it), which carries batch scope, "
        f"FLIP, provenance and the per-operation capability backstop. A permission gate is "
        f"not a write scope. A writer that must sit below the pipeline is one of the named "
        f"BELOW_PIPELINE_WRITERS in tap_grid.write_guard, writing only what it is named for, "
        f"under a gate it accepts (writer: {_below_pipeline_writer.get()!r}; "
        f"open gates: {list(_open_gates.get())!r}).",
        callsite=detail,
    )
