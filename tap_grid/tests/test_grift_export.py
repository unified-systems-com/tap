"""The GRIFT export ROUND TRIP — export a populated grid, import it into an empty
one, and prove the second grid equals the first.

The done-test for `Issue# 736 - tap` is deliberately not "it produced a file". A
file proves serialisation ran; only a round trip proves the document is the thing
the importer consumes. Without it the exporter is a hope and the shipped demo
batch becomes a frozen artifact nobody dares regenerate.

The oracle here is INDEPENDENT of the exporter's own field derivation: it reads
every concrete model field off the ORM (minus the surrogate pk and the
framework-managed provenance columns) rather than the write-surface list
`tap_grid.grift.exporter.writeable_field_names` produces. A test that compared
only the fields the exporter chose to emit would pass on an exporter that forgot
a column — a presence test wearing a correctness test's clothes.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any, cast

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from tap_grid.grift import grift_import, validate_grift_document
from tap_grid.grift.exporter import (
    EXPORT_BATCH_SOURCE,
    EXPORT_DESCRIPTION_FORMAT,
    SKIP_EDGE_ENDPOINT_NOT_EXPORTED,
    SKIP_INTERNAL_ONLY_TYPE,
    SKIP_NO_BACKING_ROW,
    SKIP_OUTSIDE_TIME_BOUND,
    SKIP_TOMBSTONED,
    export_grid,
)
from tap_grid.models import BaseModel, Batch, Edge, Entity
from tap_grid.registry import get_model_class
from tap_grid.service_types import WriteOperation
from tap_grid.services import create_edge, delete_node, write_batch

SOURCE = "grid_fixtures__constrained_source"
TARGET = "grid_fixtures__constrained_target"
CONSTRAINED = "CONSTRAINED_LINK__grid_fixtures"
ALT = "ALT_LINK__grid_fixtures"
NESTING = "NESTING_LINK__grid_fixtures"

# Columns every BaseModel carries that CANNOT survive a round trip, and are not
# meant to: `id` is a per-database surrogate, `entity_id` is the identity the
# snapshot keys on, and `batch_id` / `flip_map` are framework-managed provenance
# that the replay re-stamps to the capture batch (stated in the exporter's module
# docstring, asserted by test_replayed_rows_are_attributed_to_the_capture_batch).
_NOT_ROUND_TRIPPED = frozenset({"id", "entity_id", "batch_id", "flip_map"})


# ---------------------------------------------------------------------------
# Independent snapshot oracle
# ---------------------------------------------------------------------------


def _model(entity_type: str) -> type[BaseModel]:
    """The registered model class, typed — `get_model_class` returns a bare `type`."""
    return cast("type[BaseModel]", get_model_class(entity_type))


def _model_columns(model_cls: type[BaseModel]) -> tuple[str, ...]:
    """Every concrete column on the model that a round trip must preserve."""
    return tuple(
        sorted(field.attname for field in model_cls._meta.concrete_fields if field.attname not in _NOT_ROUND_TRIPPED)
    )


def _snapshot() -> dict[str, Any]:
    """Capture the comparable state of the whole grid, keyed by entity id."""
    nodes: dict[str, Any] = {}
    node_counts: dict[str, int] = {}
    for entity in Entity.objects.live().exclude(entity_type=Edge.ENTITY_TYPE).order_by("id"):
        try:
            model_cls = _model(entity.entity_type)
        except KeyError:
            continue
        if getattr(model_cls, "INTERNAL_ONLY", False):
            continue
        row = model_cls.objects.filter(entity_id=entity.id).first()
        if row is None:
            continue
        nodes[str(entity.id)] = {
            "entity_type": entity.entity_type,
            "name": entity.name,
            "dimensions": dict(entity.dimensions or {}),
            "columns": {name: getattr(row, name) for name in _model_columns(model_cls)},
        }
        node_counts[entity.entity_type] = node_counts.get(entity.entity_type, 0) + 1

    edges: dict[str, Any] = {}
    edge_counts: dict[str, int] = {}
    edge_rows = Edge.objects.select_related("entity").filter(entity__deleted_at__isnull=True).order_by("entity_id")
    for edge in cast("list[Edge]", list(edge_rows)):
        edges[str(edge.entity_id)] = {
            "edge_type": edge.edge_type,
            "properties": dict(edge.properties or {}),
            "from_entity_id": str(edge.from_entity_id),
            "to_entity_id": str(edge.to_entity_id),
            "name": edge.entity.name,
            "dimensions": dict(edge.entity.dimensions or {}),
        }
        edge_counts[edge.edge_type] = edge_counts.get(edge.edge_type, 0) + 1

    return {"nodes": nodes, "edges": edges, "node_counts": node_counts, "edge_counts": edge_counts}


def _without_name(edge: dict[str, Any]) -> dict[str, Any]:
    """Drop the one edge field the importer cannot carry (`Issue# 743 - tap`)."""
    return {key: value for key, value in edge.items() if key != "name"}


def _empty_the_grid() -> None:
    """Hard-reset to an empty grid — the import target.

    Direct ORM, deliberately: this is not setup of TAP behaviour but the
    destruction of the whole spine, which no service-layer verb offers and which
    the round trip needs in order to be a round trip at all.
    """
    Entity.objects.all().delete()
    assert Entity.objects.count() == 0
    assert Edge.all_objects.count() == 0


# ---------------------------------------------------------------------------
# Grid builders
# ---------------------------------------------------------------------------


def _node(entity_type: str, payload: dict[str, Any], dimensions: dict[str, str] | None = None) -> Entity:
    result = write_batch(
        [
            WriteOperation(
                verb="create_node",
                type_slug=entity_type,
                payload=payload,
                dimensions=dimensions or {},
            )
        ]
    )
    assert result.success, result.errors
    entity_id = result.results[0].entity_id
    assert entity_id is not None
    return Entity.objects.get(pk=entity_id)


def _populate() -> dict[str, Entity]:
    """Build a small grid exercising every scalar shape the format has to carry."""
    observed = datetime(2026, 9, 14, 11, 22, 33, 456789, tzinfo=UTC)
    alpha = _node(
        SOURCE,
        {
            "name": "alpha",
            "description": "a source with every field set",
            "kind": "workflow",
            "severity_score": 7,
            "is_open": True,
            "observed_at": observed.isoformat(),
            "tags": {"team": "platform", "nested": {"a": [1, 2, 3]}, "flag": False},
        },
        dimensions={"tap.graph": "test", "tap.test": "alpha"},
    )
    beta = _node(
        SOURCE,
        {
            # Deliberately at the edges: empty string (observed-empty), zero,
            # false, and an explicit null on a null-permitting field.
            "name": "beta",
            "description": "",
            "kind": "",
            "severity_score": 0,
            "is_open": False,
            "observed_at": None,
            "tags": {},
        },
    )
    gamma = _node(
        TARGET,
        {"name": "gamma", "description": "a target", "kind": "repo", "severity_score": -3, "is_open": True},
        dimensions={"tap.test": "gamma"},
    )
    delta = _node(TARGET, {"name": "delta"})

    create_edge(alpha, gamma, CONSTRAINED, properties={"weight": 4, "note": "primary"}, name="alpha->gamma")
    create_edge(alpha, delta, ALT, properties={})
    create_edge(gamma, delta, NESTING, properties={"depth": 1})

    return {"alpha": alpha, "beta": beta, "gamma": gamma, "delta": delta}


# ---------------------------------------------------------------------------
# THE round trip
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_round_trip_export_into_an_empty_grid_reproduces_the_grid() -> None:
    """Export a populated grid; import into an empty one; assert they are equal.

    Per-type node and edge counts, then every preserved column of every row,
    field for field.
    """
    _populate()
    before = _snapshot()
    assert before["node_counts"] == {SOURCE: 2, TARGET: 2}
    assert before["edge_counts"] == {CONSTRAINED: 1, ALT: 1, NESTING: 1}

    captured_at = timezone.now()
    export = export_grid(captured_at=captured_at, name="round trip")
    assert export.issues == [], [(i.code, i.path, i.message) for i in export.issues]
    assert export.node_counts == before["node_counts"]
    assert export.edge_counts == before["edge_counts"]

    _empty_the_grid()

    result = grift_import(export.document, dangling_edge_mode="strict")
    assert result.success, [(i.code, i.path, i.message) for i in result.errors]
    assert result.counts.nodes_imported == before["node_counts"][SOURCE] + before["node_counts"][TARGET]
    assert result.counts.edges_imported == 3
    assert result.counts.edges_skipped == 0

    after = _snapshot()
    assert after["node_counts"] == before["node_counts"]
    assert after["edge_counts"] == before["edge_counts"]
    assert set(after["nodes"]) == set(before["nodes"])
    assert set(after["edges"]) == set(before["edges"])

    for entity_id, expected in before["nodes"].items():
        assert after["nodes"][entity_id] == expected, f"node {entity_id} did not round trip"
    for entity_id, expected in before["edges"].items():
        # `name` is excluded for ONE named, filed reason and no other: the importer
        # discards an edge envelope's declared name (`Issue# 743 - tap`, found by
        # this very test). Every other field is compared. See
        # test_edge_names_do_not_survive_the_round_trip, which pins that gap.
        assert _without_name(after["edges"][entity_id]) == _without_name(
            expected
        ), f"edge {entity_id} did not round trip"


@pytest.mark.django_db
def test_round_trip_preserves_entity_ids_rather_than_minting_new_ones() -> None:
    """Identity is carried, not derived — the precondition for re-import to upsert."""
    created = _populate()
    export = export_grid()
    _empty_the_grid()
    assert grift_import(export.document).success

    for entity in created.values():
        assert Entity.objects.filter(pk=entity.id).exists(), f"{entity.name} was re-minted, not restored"


# ---------------------------------------------------------------------------
# Provenance stays honest (hard part 2)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_the_replayed_batch_declares_itself_a_captured_snapshot() -> None:
    _populate()
    export = export_grid(name="a snapshot")

    batch_node = export.document["batches"][0]["batch_node"]
    data = batch_node["description_json"]["data"]
    assert batch_node["source"] == EXPORT_BATCH_SOURCE
    assert "CAPTURED SNAPSHOT" in batch_node["description"]
    assert "not a live collection" in batch_node["description"]
    assert batch_node["description_json"]["format"] == EXPORT_DESCRIPTION_FORMAT
    assert data["capture_kind"] == "captured-snapshot"
    assert data["serialised_at"] == export.serialised_at.isoformat()
    # Nothing was declared, so the capture date IS the derived serialisation time.
    assert data["captured_at"] == export.serialised_at.isoformat()
    assert data["captured_at_is_declared"] is False

    _empty_the_grid()
    assert grift_import(export.document).success

    batch = Batch.objects.get(entity_id=export.batch_entity_id)
    assert batch.source == EXPORT_BATCH_SOURCE
    assert "CAPTURED SNAPSHOT" in batch.description
    # The importer preserves a custom description_json format and nests its own
    # metadata under `_tap_grift_import`, so BOTH the capture claim and the
    # import record survive on the replayed grid.
    assert batch.description_json["format"] == EXPORT_DESCRIPTION_FORMAT
    assert batch.description_json["data"]["serialised_at"] == export.serialised_at.isoformat()
    assert batch.description_json["data"]["_tap_grift_import"]["importer"] == "grift"
    # The SERIALISATION instant reaches the import record as the batch's source time.
    assert batch.description_json["data"]["_tap_grift_import"]["source_created_at"] == export.serialised_at.isoformat()


@pytest.mark.django_db
def test_a_declared_capture_date_is_attributed_and_never_overrides_the_serialisation_time() -> None:
    """`captured_at` is a caller's CLAIM, not a fact the export derived.

    Backdating a restored database is legitimate; relabelling a live snapshot as
    a week old is not, and the two are indistinguishable from inside. So the
    serialisation instant stays derived from the clock, the declared date rides
    beside it attributed to the caller, and a consumer can tell them apart
    (found by the PR's AI review: an unvalidated `captured_at` previously let the
    prose assert a serialisation time that never happened).
    """
    _populate()
    declared = timezone.now() - timedelta(days=7)
    export = export_grid(captured_at=declared, name="a restored database")

    data = export.document["batches"][0]["batch_node"]["description_json"]["data"]
    assert data["captured_at"] == declared.isoformat()
    assert data["captured_at_is_declared"] is True
    # The serialisation time is NOW, not the declared date.
    assert data["serialised_at"] == export.serialised_at.isoformat()
    assert export.serialised_at > declared

    description = export.document["batches"][0]["batch_node"]["description"]
    assert "Serialised from grid" in description
    assert export.serialised_at.isoformat() in description
    assert "caller DECLARED an observation date" in description
    assert "not a fact this export derived" in description

    # The batch entity's own timestamps are the derived instant, so a declared
    # date can never reach the replayed grid's timeline as if it were observed.
    batch_entity = export.document["batches"][0]["batch_entity"]
    assert batch_entity["created_at"] == export.serialised_at.isoformat()


@pytest.mark.django_db
def test_a_future_capture_date_is_refused() -> None:
    """A snapshot cannot declare it observed something that has not happened."""
    _populate()
    with pytest.raises(ValueError, match="in the future"):
        export_grid(captured_at=timezone.now() + timedelta(hours=1))


@pytest.mark.django_db
def test_an_operator_description_cannot_replace_the_capture_claim() -> None:
    _populate()
    export = export_grid(description="Demo data for the Noisebridge talk.")
    description = export.document["batches"][0]["batch_node"]["description"]
    assert description.startswith("CAPTURED SNAPSHOT")
    assert description.endswith("Demo data for the Noisebridge talk.")


@pytest.mark.django_db
def test_replayed_rows_are_attributed_to_the_capture_batch() -> None:
    """The stated limit, asserted rather than assumed.

    `BaseModel.batch_id` is framework-managed and on no model's write surface, so
    a replay cannot restore the original collector run's id. Every replayed row
    points at the capture batch instead — which is true (that IS how the row
    reached this grid) and is why the batch's own provenance has to be honest.
    """
    _populate()
    source_model = _model(SOURCE)
    original_batch_ids = set(source_model.objects.values_list("batch_id", flat=True))
    export = export_grid()
    _empty_the_grid()
    assert grift_import(export.document).success

    replayed_batch_ids = set(source_model.objects.values_list("batch_id", flat=True))
    assert replayed_batch_ids == {export.batch_entity_id}
    assert replayed_batch_ids != original_batch_ids


# ---------------------------------------------------------------------------
# Re-import semantics (hard part 1) — the documented ruling, asserted
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_reimporting_the_same_document_twice_is_a_no_op() -> None:
    """Batch-level idempotency: the second import skips, it does not double-write."""
    _populate()
    export = export_grid()
    _empty_the_grid()

    first = grift_import(export.document)
    assert first.success
    after_first = _snapshot()

    second = grift_import(export.document)
    assert second.success
    assert second.counts.batches_imported == 0
    assert second.counts.nodes_imported == 0
    assert second.counts.edges_imported == 0
    assert [b.reason for b in second.skipped_batches] == ["batch_already_imported"]
    assert _snapshot() == after_first


@pytest.mark.django_db
def test_importing_into_a_populated_grid_upserts_in_place_and_mints_no_duplicates() -> None:
    """Entity-level idempotency: a fresh batch id over ids the grid already holds."""
    created = _populate()
    export = export_grid()

    # Drift the live grid away from the capture, then replay the SAME content
    # under a new batch id (a second cut of one snapshot).
    source_model = _model(SOURCE)
    row = source_model.objects.get(entity_id=created["alpha"].id)
    row.severity_score = 999
    row.save(update_fields=["severity_score"])

    replay = copy.deepcopy(export.document)
    replay["batches"][0]["batch_entity"]["entity_id"] = str(uuid.uuid7())

    before = Entity.objects.exclude(entity_type="batch").count()
    result = grift_import(replay)
    assert result.success, [(i.code, i.message) for i in result.errors]

    # Nothing new on the spine: every id already existed, so every write upserted.
    assert Entity.objects.exclude(entity_type="batch").count() == before
    assert source_model.objects.get(entity_id=created["alpha"].id).severity_score == 7
    assert result.counts.entities_upserted == 7  # 4 nodes + 3 edges


# ---------------------------------------------------------------------------
# What is deliberately left out — counted, never silent
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_batches_are_not_exported_as_nodes_and_the_skip_is_counted() -> None:
    _populate()
    export = export_grid()

    node_types = {node["entity"]["entity_type"] for node in export.document["batches"][0]["nodes"]}
    assert "batch" not in node_types
    assert export.skipped[SKIP_INTERNAL_ONLY_TYPE] >= 1
    assert export.skipped_sample[SKIP_INTERNAL_ONLY_TYPE]


@pytest.mark.django_db
def test_tombstoned_entities_are_left_out_and_counted() -> None:
    created = _populate()
    result = delete_node(created["beta"].id)
    assert result.success, result.errors

    export = export_grid()
    exported_ids = {node["entity"]["entity_id"] for node in export.document["batches"][0]["nodes"]}
    assert str(created["beta"].id) not in exported_ids
    assert export.skipped[SKIP_TOMBSTONED] >= 1
    assert str(created["beta"].id) in export.skipped_sample[SKIP_TOMBSTONED]


@pytest.mark.django_db
def test_a_time_bound_keeps_the_document_self_contained() -> None:
    """A bound that drops a node drops its edges too — and counts both losses.

    The interesting case is an edge that IS inside the window while one of its
    endpoints is not: exporting it would name an id the document never defines,
    which a strict import refuses. It is dropped, and the drop is counted under
    its own reason — never left to be inferred from a shorter edge list.
    """
    created = _populate()
    cutoff = timezone.now()

    # Move alpha and the alpha->gamma edge inside the window; gamma stays out.
    source_model = _model(SOURCE)
    row = source_model.objects.get(entity_id=created["alpha"].id)
    row.kind = "touched"
    row.save(update_fields=["kind"])
    inside = cutoff + timedelta(minutes=1)
    edge = cast("Edge", Edge.objects.get(from_entity_id=created["alpha"].id, edge_type=CONSTRAINED))
    Entity.objects.filter(pk__in=[created["alpha"].id, edge.entity_id]).update(updated_at=inside)

    export = export_grid(since=cutoff)
    exported_ids = {node["entity"]["entity_id"] for node in export.document["batches"][0]["nodes"]}
    assert exported_ids == {str(created["alpha"].id)}
    assert export.document["batches"][0]["edges"] == []
    # The in-window edge lost an endpoint ...
    assert export.skipped[SKIP_EDGE_ENDPOINT_NOT_EXPORTED] == 1
    assert str(edge.entity_id) in export.skipped_sample[SKIP_EDGE_ENDPOINT_NOT_EXPORTED]
    # ... and everything the window itself excluded is counted separately, so a
    # reader can tell "the grid holds nothing else" from "the bound dropped N".
    assert export.skipped[SKIP_OUTSIDE_TIME_BOUND] >= 3
    assert str(created["gamma"].id) in export.skipped_sample[SKIP_OUTSIDE_TIME_BOUND]

    # Self-contained: no edge names an id the document does not define, so a
    # strict import (the mode that refuses dangling edges) succeeds.
    _empty_the_grid()
    assert grift_import(export.document, dangling_edge_mode="strict").success


@pytest.mark.django_db
def test_an_empty_grid_exports_an_importable_empty_document() -> None:
    _empty_the_grid()
    export = export_grid()
    assert export.issues == []
    assert export.node_total == 0
    assert export.edge_total == 0
    assert grift_import(export.document).success
    assert Batch.objects.filter(entity_id=export.batch_entity_id).exists()


@pytest.mark.django_db
def test_edge_names_do_not_survive_the_round_trip() -> None:
    """A tombstone for `Issue# 743 - tap` — invert this when the importer is fixed.

    The exporter emits the edge's declared `Entity.name`; the importer's
    `create_edge` write operation has no field to carry it, so the replayed edge
    is labelled by `Edge.get_name()` instead. Every shipped bundle declares edge
    names (19 of 19 across zizmor's and git_serious_double_tap's bundles, counted
    2026-09-21) and all of them are discarded — a declaration that is present and
    false, which is why this is pinned rather than left to be discovered by a
    stale label on a demo grid.
    """
    created = _populate()
    export = export_grid()

    exported = [
        edge
        for edge in export.document["batches"][0]["edges"]
        if edge["edge"]["from_entity_id"] == str(created["alpha"].id)
        and edge["edge"]["to_entity_id"] == str(created["gamma"].id)
    ]
    assert len(exported) == 1
    # The EXPORT side is correct: the curated name is in the document.
    assert exported[0]["entity"]["name"] == "alpha->gamma"

    _empty_the_grid()
    assert grift_import(export.document).success

    replayed = cast("Edge", Edge.objects.select_related("entity").get(entity_id=exported[0]["entity"]["entity_id"]))
    assert replayed.entity.name != "alpha->gamma"
    assert (
        replayed.entity.name == f"{created['alpha'].id} --[{CONSTRAINED}]--> {created['gamma'].id}"
    ), "Issue# 743 - tap may be fixed; invert this test and drop the exclusion in the round-trip test"


# ---------------------------------------------------------------------------
# The management command — the operator surface, which had no tests until the
# PR's AI review pointed out that both stdout findings would have been caught
# by one (Issue# 736 - tap review, 2026-09-22).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_output_dash_emits_a_document_and_nothing_else_on_stdout() -> None:
    """`export_grift --output - | grift_import` has to be a valid pipe.

    The human report goes to stderr when the document goes to stdout; a report
    line nailed to the front of the JSON is not GRIFT and never will be.
    """
    _populate()
    out, err = StringIO(), StringIO()
    call_command("export_grift", "--output", "-", "--compact", stdout=out, stderr=err)

    document = json.loads(out.getvalue())
    assert document["metadata"]["grift_version"] == "0"
    assert len(document["batches"][0]["nodes"]) == 4
    assert validate_grift_document(document) == []

    # The report is not lost — it went to the other stream.
    assert "Serialised size:" in err.getvalue()
    assert "Serialised size:" not in out.getvalue()


@pytest.mark.django_db
def test_writing_to_a_file_reports_the_size_of_the_bytes_written(tmp_path: Path) -> None:
    """The reported figure is the file's real size, trailing newline included."""
    _populate()
    target = tmp_path / "snapshot.grift.json"
    out = StringIO()
    call_command("export_grift", "--output", str(target), stdout=out)

    written = target.read_bytes()
    match = re.search(r"Serialised size: ([\d,]+) bytes", out.getvalue())
    assert match is not None, out.getvalue()
    assert int(match.group(1).replace(",", "")) == len(written)
    assert json.loads(written.decode()) == json.loads(target.read_text())


@pytest.mark.django_db
def test_a_naive_or_reversed_time_bound_is_refused(tmp_path: Path) -> None:
    """Bad bounds fail before any work, with a message naming the flag."""
    with pytest.raises(CommandError, match="--since"):
        call_command("export_grift", "--output", "-", "--since", "2026-09-14T00:00:00")
    with pytest.raises(CommandError, match="window is empty"):
        call_command(
            "export_grift",
            "--output",
            "-",
            "--since",
            "2026-09-14T00:00:00Z",
            "--until",
            "2026-09-01T00:00:00Z",
        )


@pytest.mark.django_db
def test_the_exported_document_round_trips_through_the_command(tmp_path: Path) -> None:
    """The file on disk — not just the in-memory document — re-imports."""
    _populate()
    before = _snapshot()
    target = tmp_path / "snapshot.grift.json"
    call_command("export_grift", "--output", str(target), stdout=StringIO())

    _empty_the_grid()
    assert grift_import(target.read_text()).success

    after = _snapshot()
    assert after["node_counts"] == before["node_counts"]
    assert after["edge_counts"] == before["edge_counts"]


@pytest.mark.django_db
def test_an_edge_spine_with_no_backing_row_is_counted_not_silently_dropped() -> None:
    """The ledger closes over edge-typed spine rows too.

    The node pass excludes entity_type == "edge" and the edge pass starts from
    the Edge table, so a live edge-typed Entity with no backing Edge row was
    seen by neither and counted by neither — an omission with no named reason,
    which is the one thing this ledger exists to make impossible (found by the
    PR's AI review). Direct ORM here on purpose: this damage cannot be produced
    through the service layer, which is why it has to be manufactured.
    """
    _populate()
    orphan = Entity.objects.create(entity_type=Edge.ENTITY_TYPE, name="an edge with no row", dimensions={})

    export = export_grid()

    exported_edge_ids = {edge["entity"]["entity_id"] for edge in export.document["batches"][0]["edges"]}
    assert str(orphan.id) not in exported_edge_ids
    assert str(orphan.id) in export.skipped_sample[SKIP_NO_BACKING_ROW]
    assert export.skipped[SKIP_NO_BACKING_ROW] == 1
    # The real edges are untouched by the orphan's presence.
    assert export.edge_total == 3
