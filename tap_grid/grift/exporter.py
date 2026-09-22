"""GRIFT exporter — serialise a live grid to a re-importable GRIFT v0 document.

The write-direction counterpart to :mod:`tap_grid.grift.importer`. The importer
turns a ``.grift.json`` document into grid state; this module turns grid state
back into a document the *same* importer consumes, so a grid populated by a real
collector run can be frozen and replayed on a machine with no credential.

This is deliberately NOT :mod:`tap_grid.grift.subgraph`. The subgraph serializers
build the lite/full/extended envelopes API and viz *responses* carry: a read shape
whose ``data`` lane includes framework-managed fields (``batch_id``, ``flip_map``)
that the service-layer write schema rejects. Feeding a subgraph envelope back to
the importer fails on ``additionalProperties``. What is re-importable is exactly
the model's declared write surface, which is what this module emits.

Scope (ruled 2026-09-21, Issue# 736 - tap): the WHOLE grid, optionally
time-bounded. No selection, no reachability, no redaction.

Three properties this module is built to hold:

Honest provenance
    The batch this export mints declares itself CAPTURED. ``batch_node.source``
    is :data:`EXPORT_BATCH_SOURCE`, its description says which grid the rows came
    off and when, and ``description_json`` carries the capture facts in a machine
    -readable lane. A replayed grid never claims it collected anything live.

Stable identity
    Entity ids are copied verbatim, never re-minted. Re-importing lands the same
    entities, so a replay is an upsert rather than a duplicate. See the module
    docstring section "Re-import semantics" below.

No silent loss
    Every row the export leaves out is counted under a named reason and returned
    in :class:`GriftExportResult.skipped`. Absence of a row in the document is
    never left to be discovered by its absence in the replayed grid.

Re-import semantics (the ruling, stated rather than accidental)
    * The same document imported **twice into the same grid** is a no-op the
      second time. The importer skips a batch whose ``batch_entity_id`` already
      has a ``Batch`` row (``batch_already_imported``); the export mints one
      batch id per run, so replaying the same file cannot double-write.
    * The same document imported into a grid that **already holds some of those
      entity ids** upserts them in place — the importer routes an existing
      ``entity_id`` to ``replace_node`` / ``replace_edge``, last-write-wins per
      entity. It never mints a duplicate, because the ids are carried, not
      derived.
    * What a replay does NOT restore: per-row attribution to the original
      collector batch. ``BaseModel.batch_id`` is framework-managed and is not on
      any model's write surface, so every replayed row is attributed to the
      capture batch. That is the honest answer — the row arrived in this grid via
      the capture — but it means the original run ids do not survive the trip.
      ``Entity.originating_grid_id`` likewise re-stamps to the importing grid,
      and ``created_at`` / ``updated_at`` are the replay's, not the capture's.
      The capture time survives on the batch, which is why it is recorded there.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from tap_grid.grift.importer import (
    GRIFT_VERSION,
    GriftIssue,
    _validate_edge_payload,
    _validate_node_payload,
    validate_grift_document,
)
from tap_grid.grift.subgraph import json_safe

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    # `Edge` is deliberately NOT imported here. Every use of it lives inside a
    # function that imports it at runtime, so a TYPE_CHECKING copy is an unused
    # import (F401) that the function-local ones then redefine (F811).
    from tap_grid.models import BaseModel, Entity

logger = logging.getLogger(__name__)


# `batch_node.source` for every batch this exporter mints. It names the EXPORTER,
# not a collector, and the word "captured" is load-bearing: a consumer reading a
# replayed grid must be able to tell "these rows were observed by an earlier run
# and replayed here" from "these rows were observed by a run against a live
# source". A demo grid whose batches claimed live collection would be a false
# declaration of exactly the kind the presence-is-not-correctness filter exists
# to catch.
EXPORT_BATCH_SOURCE = "tap_grid.grift.exporter:captured-snapshot"

# `batch_node.description_json.format` — the machine-legible half of the same
# claim. The importer preserves a custom format and nests its own import metadata
# under `_tap_grift_import`, so both halves survive the replay.
EXPORT_DESCRIPTION_FORMAT = "tap.grift.export.v0"

# The prose half, written onto `batch_node.description`. Present in the replayed
# grid's batch list, where a human reads it.
PROVENANCE_SENTENCE = (
    "CAPTURED SNAPSHOT — not a live collection. Every node and edge in this batch was "
    "observed by earlier runs against grid {grid_id} and serialised at {captured_at}. "
    "Importing this batch replays those observations; it does not re-observe anything. "
    "The import time is not an observation time."
)

# Reasons a live row is left out of the document. Every one is counted; none is
# silent. Three states, never two: a type is exported, or it is skipped for a
# named reason — never simply missing.
SKIP_TOMBSTONED = "tombstoned"
SKIP_UNREGISTERED_TYPE = "unregistered_entity_type"
SKIP_INTERNAL_ONLY_TYPE = "internal_only_entity_type"
SKIP_NO_BACKING_ROW = "no_backing_row"
SKIP_EDGE_ENDPOINT_NOT_EXPORTED = "edge_endpoint_not_exported"
SKIP_OUTSIDE_TIME_BOUND = "outside_time_bound"

# How many entity ids to keep per skip reason. The COUNTS are exact; this is a
# sample for an operator to start pulling on, and the result says so.
SKIP_SAMPLE_CAP = 50

# Chunk size for `entity_id__in` lookups — Postgres caps bind parameters well
# below the size of a real grid's per-type row count.
_IN_CHUNK = 5_000


@dataclass(frozen=True)
class GriftExportResult:
    """One completed export.

    Attributes:
        document: The GRIFT v0 document — ``metadata`` + ``_reserved`` +
            ``batches``, ready to hand to ``grift_import`` or write to a
            ``.grift.json`` file.
        batch_entity_id: The id of the single batch the document carries.
        captured_at: The capture instant stamped into the batch's provenance.
        node_counts: Exported node count per ``entity_type``.
        edge_counts: Exported edge count per ``edge_type``.
        skipped: Exact count of live rows left out, keyed by reason.
        skipped_sample: Up to :data:`SKIP_SAMPLE_CAP` entity ids per reason.
            A SAMPLE, not the set — read ``skipped`` for the true count.
        issues: Validation issues found by running the importer's own validators
            over the document this export built. Empty means the document is
            structurally valid AND every node payload satisfies its model's
            replace schema. Non-empty means the grid holds rows this document
            cannot express; the caller decides whether to ship it.
    """

    document: dict[str, Any]
    batch_entity_id: str
    captured_at: datetime
    node_counts: dict[str, int] = field(default_factory=dict)
    edge_counts: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    skipped_sample: dict[str, list[str]] = field(default_factory=dict)
    issues: list[GriftIssue] = field(default_factory=list)

    @property
    def node_total(self) -> int:
        return sum(self.node_counts.values())

    @property
    def edge_total(self) -> int:
        return sum(self.edge_counts.values())


class _SkipLedger:
    """Counts and samples every row the export leaves behind."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = defaultdict(int)
        self.sample: dict[str, list[str]] = defaultdict(list)

    def record(self, reason: str, entity_id: Any) -> None:
        self.counts[reason] += 1
        bucket = self.sample[reason]
        if len(bucket) < SKIP_SAMPLE_CAP:
            bucket.append(str(entity_id))


def writeable_field_names(model_cls: type[BaseModel]) -> tuple[str, ...]:
    """Return the field names a GRIFT node payload for ``model_cls`` may carry.

    Read straight off ``SERVICE_CRUD_SCHEMA["replace"]["properties"]`` — the very
    schema ``tap_grid.grift.importer._validate_node_payload`` validates an
    incoming payload against. Deriving the export surface from the import
    surface is the point: the exporter cannot drift into emitting a field the
    importer would reject, or omitting one it requires, because there is one
    declaration and both ends read it.
    """
    replace_schema: dict[str, Any] = model_cls.SERVICE_CRUD_SCHEMA.get("replace", {})
    return tuple(replace_schema.get("properties", {}))


def _node_payload(row: BaseModel, field_names: tuple[str, ...]) -> dict[str, Any]:
    """Project one typed row onto its writeable field surface, JSON-safe."""
    return {name: json_safe(getattr(row, name, None)) for name in field_names}


def _entity_envelope(entity: Entity) -> dict[str, Any]:
    """Build the GRIFT entity envelope for one live entity.

    Deliberately omits ``created_at`` / ``updated_at`` / ``deleted_at``. The
    importer does not thread node or edge timestamps into the create path — it
    validates them and drops them — so emitting them would be a declaration
    nothing honours. The one envelope that DOES carry timestamps is the batch's,
    where the importer records them as ``source_created_at`` provenance.
    """
    envelope: dict[str, Any] = {
        "entity_id": str(entity.id),
        "entity_type": entity.entity_type,
        "dimensions": dict(entity.dimensions or {}),
    }
    # The schema requires a non-empty string when `name` is present at all; an
    # unnamed entity carries no key rather than an empty one.
    if entity.name:
        envelope["name"] = entity.name
    return envelope


def _chunked(values: list[Any], size: int = _IN_CHUNK) -> Iterator[list[Any]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _collect_nodes(
    *,
    since: datetime | None,
    until: datetime | None,
    ledger: _SkipLedger,
) -> tuple[list[dict[str, Any]], dict[str, int], set[uuid.UUID]]:
    """Serialise every exportable live node. Returns (nodes, counts, exported ids)."""
    from tap_grid.models import Edge, Entity
    from tap_grid.registry import get_model_class

    queryset = Entity.objects.live().exclude(entity_type=Edge.ENTITY_TYPE)
    if since is not None:
        queryset = queryset.filter(updated_at__gte=since)
    if until is not None:
        queryset = queryset.filter(updated_at__lte=until)

    by_type: dict[str, list[Entity]] = defaultdict(list)
    for entity in queryset.order_by("created_at", "id").iterator(chunk_size=2_000):
        by_type[entity.entity_type].append(entity)

    nodes: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    exported_ids: set[uuid.UUID] = set()

    for entity_type in sorted(by_type):
        entities = by_type[entity_type]
        try:
            model_cls = cast("type[BaseModel]", get_model_class(entity_type))
        except KeyError:
            # A retired type, or one whose plugin is not installed here. The
            # importer would refuse it (`unknown_entity_type`), so shipping it
            # would build a document that cannot be replayed anywhere.
            logger.warning(
                "[bb05] export skipping %s live %r entities: entity type is not registered on this grid",
                len(entities),
                entity_type,
            )
            for entity in entities:
                ledger.record(SKIP_UNREGISTERED_TYPE, entity.id)
            continue

        if getattr(model_cls, "INTERNAL_ONLY", False):
            # `batch` is the live case: batches are TAP's own bookkeeping, the
            # generic CRUD verbs reject them, and this document mints a batch of
            # its own. Exporting the source grid's batch rows as nodes would ask
            # the importer to create_node a type it refuses.
            logger.info(
                "[5b20] export skipping %s %r entities: internal-only type",
                len(entities),
                entity_type,
            )
            for entity in entities:
                ledger.record(SKIP_INTERNAL_ONLY_TYPE, entity.id)
            continue

        field_names = writeable_field_names(model_cls)
        rows: dict[uuid.UUID, BaseModel] = {}
        ids = [entity.id for entity in entities]
        for chunk in _chunked(ids):
            for row in model_cls.objects.filter(entity_id__in=chunk):
                rows[row.entity_id] = row

        exported_for_type = 0
        for entity in entities:
            typed_row = rows.get(entity.id)
            if typed_row is None:
                # A spine row with no typed row behind it. Real (a partially
                # applied migration, a hand-deleted table row); never silent.
                logger.warning(
                    "[2229] export skipping entity %s (%s): no backing %s row",
                    entity.id,
                    entity_type,
                    model_cls.__name__,
                )
                ledger.record(SKIP_NO_BACKING_ROW, entity.id)
                continue
            nodes.append({"entity": _entity_envelope(entity), "node": _node_payload(typed_row, field_names)})
            exported_ids.add(entity.id)
            exported_for_type += 1

        if exported_for_type:
            counts[entity_type] = exported_for_type

    return nodes, counts, exported_ids


def _collect_edges(
    *,
    since: datetime | None,
    until: datetime | None,
    exported_node_ids: set[uuid.UUID],
    ledger: _SkipLedger,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Serialise every exportable live edge. Returns (edges, counts per edge_type).

    An edge rides only when BOTH endpoints are in the exported node set. That is
    what keeps a time-bounded export self-contained: the document never names an
    id it does not also define, so it imports in ``strict`` dangling-edge mode
    with no special handling. Edges dropped this way are counted under
    :data:`SKIP_EDGE_ENDPOINT_NOT_EXPORTED`.
    """
    from tap_grid.models import Edge

    queryset = Edge.objects.select_related("entity").filter(entity__deleted_at__isnull=True)
    if since is not None:
        queryset = queryset.filter(entity__updated_at__gte=since)
    if until is not None:
        queryset = queryset.filter(entity__updated_at__lte=until)

    edges: list[dict[str, Any]] = []
    counts: dict[str, int] = defaultdict(int)

    for edge in cast("Iterable[Edge]", queryset.order_by("entity__created_at", "entity_id").iterator(chunk_size=2_000)):
        if edge.from_entity_id not in exported_node_ids or edge.to_entity_id not in exported_node_ids:
            ledger.record(SKIP_EDGE_ENDPOINT_NOT_EXPORTED, edge.entity_id)
            continue
        edges.append(
            {
                "entity": _entity_envelope(edge.entity),
                "edge": {
                    "from_entity_id": str(edge.from_entity_id),
                    "to_entity_id": str(edge.to_entity_id),
                    "edge_type": edge.edge_type,
                    "properties": dict(edge.properties or {}),
                },
            }
        )
        counts[edge.edge_type] += 1

    return edges, dict(counts)


def _count_outside_time_bound(*, since: datetime | None, until: datetime | None, ledger: _SkipLedger) -> None:
    """Record every live entity the time bound excluded.

    Without this the window's effect is invisible: a caller reading a bounded
    export could not tell "the grid holds nothing else" from "the bound dropped
    9,000 rows". Absence of evidence must never render as evidence of absence,
    so the complement of the window is counted explicitly rather than inferred.

    Covers nodes and edges alike — an edge IS an entity — which also keeps the
    reasons disjoint: an out-of-window edge is counted here and never reaches
    the endpoint check, so nothing is counted twice.
    """
    from django.db.models import Q

    from tap_grid.models import Entity

    if since is None and until is None:
        return

    outside = Q()
    if since is not None:
        outside |= Q(updated_at__lt=since)
    if until is not None:
        outside |= Q(updated_at__gt=until)

    queryset = Entity.objects.live().filter(outside).order_by("created_at").values_list("id", flat=True)
    for entity_id in queryset.iterator(chunk_size=2_000):
        ledger.record(SKIP_OUTSIDE_TIME_BOUND, entity_id)


def _count_tombstones(ledger: _SkipLedger) -> None:
    """Record every tombstoned entity as a named skip — window or no window.

    A GRIFT upsert batch has no way to say "this once existed and is gone" — the
    `deletes` / `purges` sections name targets an importing grid is expected to
    already hold, which an empty grid does not. So tombstones do not travel.

    Deliberately NOT time-bounded, unlike the live selection: the bound decides
    what is exported, and nothing tombstoned is ever exported. Bounding this too
    would leave a tombstone outside the window counted under no reason at all,
    which is the silence this ledger exists to prevent.
    """
    from tap_grid.models import Entity

    queryset = Entity.objects.tombstoned().order_by("created_at").values_list("id", flat=True)
    for entity_id in queryset.iterator(chunk_size=2_000):
        ledger.record(SKIP_TOMBSTONED, entity_id)


def _validate_document(document: dict[str, Any]) -> list[GriftIssue]:
    """Run the IMPORTER's validators over the document this export built.

    Two passes, both borrowed rather than reimplemented:

    1. ``validate_grift_document`` — the document JSON Schema.
    2. ``_validate_node_payload`` / ``_validate_edge_payload`` — the per-record
       checks preflight runs, which is where a node payload meets its model's
       replace schema. The document schema alone would pass a payload the
       importer rejects, so checking only the former would be a presence test
       wearing a correctness test's clothes.

    What this still does NOT prove is that the rows survive `full_validate` and
    the edge-constraint checks, which need the database of the grid being
    imported INTO. The round-trip test is what proves that end.
    """
    issues = validate_grift_document(document)
    if issues:
        return issues

    for batch_index, batch in enumerate(document["batches"]):
        batch_path = f"$.batches[{batch_index}]"
        batch_entity_id = batch["batch_entity"]["entity_id"]
        for node_index, node in enumerate(batch["nodes"]):
            _validate_node_payload(
                node["node"],
                node["entity"]["entity_type"],
                f"{batch_path}.nodes[{node_index}].node",
                issues,
                batch_entity_id=batch_entity_id,
                entity_id=node["entity"]["entity_id"],
            )
        for edge_index, edge in enumerate(batch["edges"]):
            _validate_edge_payload(
                edge["edge"],
                f"{batch_path}.edges[{edge_index}].edge",
                issues,
                batch_entity_id=batch_entity_id,
                entity_id=edge["entity"]["entity_id"],
            )
    return issues


@contextmanager
def _consistent_snapshot() -> Iterator[None]:
    """Read every phase of the export from ONE database snapshot.

    An export is four separate queries — nodes, edges, the time-bound
    complement, tombstones. Under PostgreSQL's default READ COMMITTED each one
    sees its own snapshot, so a collector writing concurrently can leave the
    document describing a grid state that never existed: an edge whose endpoint
    the node pass did not see, counts that do not add up, provenance that dates
    a mixture. A snapshot tool that cannot take a snapshot is the wrong tool.

    So the whole read runs in one REPEATABLE READ transaction. Postgres refuses
    `SET TRANSACTION ISOLATION LEVEL` after the first statement of a
    transaction, which is exactly the situation when a caller (a test, a
    service-layer block) already has one open — there the ambient transaction's
    own snapshot is what we read under, and this yields without touching it.
    That case is named rather than hidden: inside a caller's READ COMMITTED
    block the cross-phase guarantee is the caller's to make, not ours.
    """
    if connection.in_atomic_block:
        logger.debug(
            "[4664] export reading inside a caller's existing transaction; "
            "its isolation level governs, not REPEATABLE READ",
        )
        yield
        return

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        yield


def export_grid(
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    captured_at: datetime | None = None,
    batch_entity_id: uuid.UUID | str | None = None,
    name: str = "",
    description: str = "",
    metadata: dict[str, Any] | None = None,
) -> GriftExportResult:
    """Serialise this grid into a single re-importable GRIFT v0 batch.

    Args:
        since: Lower bound on ``Entity.updated_at``; ``None`` for no lower bound.
        until: Upper bound on ``Entity.updated_at``; ``None`` for no upper bound.
        captured_at: The capture instant to stamp into provenance. Defaults to
            now. Must not be in the future relative to a later import, which now
            always satisfies.
        batch_entity_id: Id for the batch this export mints. Defaults to a fresh
            UUIDv7. Pass a stable one to re-cut the SAME batch (a plugin that
            ships a regenerated bundle wants its batch id to move, per
            req-tap-plugin-arch-iterative-dev — so pass a NEW one each cut unless
            you mean to make the file inert).
        name: Human-readable batch name. A default naming the capture is used
            when empty.
        description: Extra prose appended AFTER the provenance sentence. It can
            add, never replace: the capture claim is not the caller's to edit.
        metadata: Caller-supplied ``batch_node.metadata``, passed through
            verbatim. The capture facts are NOT copied here — they live in
            ``description_json`` alone.

    Returns:
        A :class:`GriftExportResult`. Read ``issues`` before shipping the
        document — a non-empty list means the grid holds rows this format cannot
        carry. An EMPTY list is necessary, not sufficient: see
        :func:`_validate_document` for what it does not reach.
    """
    captured_at = captured_at or timezone.now()
    resolved_batch_id = str(batch_entity_id or uuid.uuid7())
    grid_id = getattr(settings, "TAP_GRID_ID", "") or "(unset)"
    ledger = _SkipLedger()

    with _consistent_snapshot():
        nodes, node_counts, exported_ids = _collect_nodes(since=since, until=until, ledger=ledger)
        edges, edge_counts = _collect_edges(since=since, until=until, exported_node_ids=exported_ids, ledger=ledger)
        _count_outside_time_bound(since=since, until=until, ledger=ledger)
        _count_tombstones(ledger)

    provenance = PROVENANCE_SENTENCE.format(grid_id=grid_id, captured_at=captured_at.isoformat())
    resolved_name = name or f"Captured grid snapshot {captured_at.date().isoformat()}"

    capture_data: dict[str, Any] = {
        "exporter": "tap_grid.grift.exporter",
        "grift_version": GRIFT_VERSION,
        # Never "live": the one word a consumer keys off to know these rows were
        # replayed rather than observed by this batch.
        "capture_kind": "captured-snapshot",
        "captured_at": captured_at.isoformat(),
        "captured_from_grid_id": str(grid_id),
        "time_bound": {
            "since": since.isoformat() if since is not None else None,
            "until": until.isoformat() if until is not None else None,
        },
        "node_count": len(nodes),
        "edge_count": len(edges),
        "node_counts_by_type": dict(sorted(node_counts.items())),
        "edge_counts_by_type": dict(sorted(edge_counts.items())),
        "skipped_counts_by_reason": dict(sorted(ledger.counts.items())),
    }

    document: dict[str, Any] = {
        "metadata": {"grift_version": GRIFT_VERSION},
        "_reserved": {},
        "batches": [
            {
                "batch_entity": {
                    "entity_id": resolved_batch_id,
                    "entity_type": "batch",
                    "name": resolved_name,
                    "dimensions": {},
                    "created_at": captured_at.isoformat(),
                    "updated_at": captured_at.isoformat(),
                },
                "batch_node": {
                    "name": resolved_name,
                    "source": EXPORT_BATCH_SOURCE,
                    "description": f"{provenance} {description}".strip(),
                    "description_json": {"format": EXPORT_DESCRIPTION_FORMAT, "data": capture_data},
                    # The capture facts live in `description_json` and nowhere
                    # else: a second copy in `metadata` would be a fact derived
                    # twice, and the two would drift the moment either is edited.
                    "metadata": dict(metadata or {}),
                },
                "nodes": nodes,
                "edges": edges,
            }
        ],
    }

    issues = _validate_document(document)
    logger.info(
        "[98c9] exported %s node(s) and %s edge(s) from grid %s as batch %s (%s skipped, %s issue(s))",
        len(nodes),
        len(edges),
        grid_id,
        resolved_batch_id,
        sum(ledger.counts.values()),
        len(issues),
    )

    return GriftExportResult(
        document=document,
        batch_entity_id=resolved_batch_id,
        captured_at=captured_at,
        node_counts=dict(sorted(node_counts.items())),
        edge_counts=dict(sorted(edge_counts.items())),
        skipped=dict(sorted(ledger.counts.items())),
        skipped_sample={reason: list(ids) for reason, ids in sorted(ledger.sample.items())},
        issues=issues,
    )
