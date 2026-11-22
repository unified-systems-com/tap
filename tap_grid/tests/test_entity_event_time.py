"""Event time on the spine: the declaration, the one reader, the derivation and the overlap test.

Covers ``req-grid-entity-event-time`` (spec-grid-entity.md); Issue# 194 - tap. Rows use the neutral
grid_fixtures ``PgNode`` and ``PgHub``, which carry a date-time field (``observed_at``) and two text
fields (``description``, ``kind``); each test states the declaration it needs on the class, since
the fixture plugin declares none. No model in this stack has a date field, so the date-field path
is covered at the reader.
"""

from __future__ import annotations

import importlib
import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tap_plugin.grid_fixtures.models.pg_hub import PgHub
from tap_plugin.grid_fixtures.models.pg_node import PgNode

from tap_grid import event_time
from tap_grid.caller_context import CallerContext
from tap_grid.dimension_map import DimensionWriteError, grid_derived_ids, settle, with_grid_derived
from tap_grid.dimension_names import declared, view
from tap_grid.event_time import (
    EVENT_KINDS,
    EVENT_PRECISIONS,
    FHIR_DATETIME_PATTERN,
    NO_EVENT_TIME,
    Interval,
    Moment,
    Unreadable,
    declaration_from_definition,
    declaration_problems,
    derive,
    overlapping,
    overlaps,
    read_value,
)
from tap_grid.grift import grift_import
from tap_grid.grift.subgraph import build_spine_surface
from tap_grid.models import BatchEvent, BatchEventType, Edge, Entity
from tap_grid.service_types import WRITE_UNCHANGED, WriteOperation
from tap_grid.services import create_edge, create_node, patch_edge, patch_node, write_batch
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc

AC = {n: pytest.mark.spec(f"req-grid-entity-event-time-{n}") for n in range(1, 25)}

_TYPE = "grid_fixtures__node"
_HUB = "grid_fixtures__hub"
LINK = "PG_LINKS__grid_fixtures"
THREE = ("event_start", "event_end", "event_precision")
TIME = "time"
CORE_SEED = Path(__file__).resolve().parents[1] / "data" / "dimensions.grift.json"
SPEC = Path(__file__).resolve().parents[1] / "specs" / "spec-grid-entity.md"


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)  # type: ignore[arg-type, misc]


def _ctx() -> CallerContext:
    return CallerContext(batch_id=str(uuid.uuid7()))


def _create(payload: dict[str, Any], type_slug: str = _TYPE) -> Any:
    result = create_node(type_slug, payload, caller_context=_ctx())
    assert result.success, result.errors
    return result


def _row(entity_id: Any) -> Entity:
    return Entity.objects.get(pk=entity_id)


def _kind(entity_id: Any) -> Any:
    """The row's `time` dimension value, by name, or None when it carries none."""
    return view(_row(entity_id).dimensions).get(TIME)


def _four(entity_id: Any) -> tuple[Any, ...]:
    """Start, end, kind and precision: the three columns and the `time` dimension, in the old order."""
    row = _row(entity_id)
    return (row.event_start, row.event_end, _kind(entity_id), row.event_precision)


@pytest.fixture
def moment_on_observed_at(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(PgNode, "EVENT_TIME", Moment("observed_at", "occurred"), raising=False)


@pytest.fixture
def moment_on_description(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(PgNode, "EVENT_TIME", Moment("description", "published"), raising=False)


@pytest.fixture
def interval_on_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(PgNode, "EVENT_TIME", Interval("description", "created", end="kind"), raising=False)


@pytest.fixture
def edge_moment_on_since(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(event_time._edge_event_time, LINK, Moment("since", "first_seen"))


# ---------------------------------------------------------------------------
# The reader
# ---------------------------------------------------------------------------


class TestTheReader:
    def test_the_pattern_is_the_one_the_requirement_prints(self) -> None:
        printed = re.search(r"```text\n(.+)\n```", SPEC.read_text(encoding="utf-8"))
        assert printed is not None
        assert printed.group(1) == FHIR_DATETIME_PATTERN

    def test_the_closed_lists(self) -> None:
        assert EVENT_KINDS == ("occurred", "created", "first_seen", "published")
        assert EVENT_PRECISIONS == ("year", "month", "day", "second")

    @AC[20]
    def test_the_static_kinds_are_the_seeded_time_dimensions_values(self) -> None:
        """One definition: the tuple a class body is checked against equals the seed's bounded list."""
        seed = json.loads(CORE_SEED.read_text(encoding="utf-8"))
        nodes = {n["node"]["name"]: n["node"] for batch in seed["batches"] for n in batch["nodes"]}
        assert tuple(nodes[TIME]["values"]) == EVENT_KINDS
        assert {name for name in nodes if name.startswith("time.")} == {f"time.{kind}" for kind in EVENT_KINDS}

    @AC[15]
    @pytest.mark.parametrize(
        ("text", "start", "end", "level"),
        [
            ("2026", _utc(2026, 1, 1), _utc(2027, 1, 1), "year"),
            ("2026-12", _utc(2026, 12, 1), _utc(2027, 1, 1), "month"),
            ("2026-02", _utc(2026, 2, 1), _utc(2026, 3, 1), "month"),
            ("2026-12-01", _utc(2026, 12, 1), _utc(2026, 12, 2), "day"),
            ("2026-12-01T18:30:00Z", _utc(2026, 12, 1, 18, 30), _utc(2026, 12, 1, 18, 30), "second"),
            ("2026-12-01T18:30:00+02:00", _utc(2026, 12, 1, 16, 30), _utc(2026, 12, 1, 16, 30), "second"),
        ],
    )
    def test_the_four_forms(self, text: str, start: datetime, end: datetime, level: str) -> None:
        reading = read_value(text)
        assert reading is not None
        assert (reading.start, reading.end_exclusive, reading.level) == (start, end, level)

    def test_a_date_field_value_is_a_day(self) -> None:
        reading = read_value(date(2026, 12, 1))
        assert reading is not None
        assert (reading.start, reading.end_exclusive, reading.level) == (_utc(2026, 12, 1), _utc(2026, 12, 2), "day")

    def test_a_date_time_field_value_is_a_moment_in_utc(self) -> None:
        east = timezone(timedelta(hours=5, minutes=30))
        reading = read_value(datetime(2026, 12, 1, 5, 0, tzinfo=east))
        assert reading is not None
        assert reading.start == reading.end_exclusive == _utc(2026, 11, 30, 23, 30)
        assert reading.start.utcoffset() == timedelta(0)
        assert reading.level == "second"

    def test_a_fraction_finer_than_a_microsecond_is_cut_short(self) -> None:
        reading = read_value("2026-12-01T18:30:00.123456789Z")
        assert reading is not None
        assert reading.start == _utc(2026, 12, 1, 18, 30, 0, 123456)
        assert reading.level == "second"

    @pytest.mark.parametrize("empty", [None, ""])
    def test_an_empty_value_reads_as_nothing(self, empty: Any) -> None:
        assert read_value(empty) is None

    @AC[16]
    @pytest.mark.parametrize(
        "text",
        [
            "2026-12-01T18",  # stops at the hour
            "2026-12-01T18:30",  # stops at the minute
            "2026-12-01T18:30:00",  # a time of day and no zone
            "2026-12-01T24:00:00Z",  # FHIR does not allow 24:00
            "2026-12-01T18:30:60Z",  # a leap second cannot be stored
            "2026-02-30",  # matches the pattern, not a calendar date
            "2026-13",
            "26-12-01",
            "2026-12-01 18:30:00Z",
            "yesterday",
        ],
    )
    def test_what_the_reader_refuses(self, text: str) -> None:
        with pytest.raises(Unreadable):
            read_value(text)

    def test_a_date_time_with_no_zone_is_refused(self) -> None:
        with pytest.raises(Unreadable, match="no time zone"):
            read_value(datetime(2026, 12, 1, 18, 30))  # noqa: DTZ001 — the naive value is the case

    def test_a_value_that_is_neither_a_date_nor_text_is_refused(self) -> None:
        with pytest.raises(Unreadable):
            read_value(20261201)


class TestDerive:
    def test_an_interval_widens_each_bound_on_its_own(self) -> None:
        got = derive(Interval("a", "created", end="b"), {"a": "2026-03", "b": "2026-05-10"}.get)
        assert (got.event_start, got.event_end) == (_utc(2026, 3, 1), _utc(2026, 5, 11))
        # The marker is the coarser of the bounds that are stated.
        assert got.event_precision == "month"
        assert got.kind == "created"
        assert got.as_dimensions() == {TIME: "created"}

    def test_an_unstated_end_is_not_closed_at_the_end_of_the_starts_unit(self) -> None:
        got = derive(Interval("a", "created", end="b"), {"a": "2026", "b": None}.get)
        assert (got.event_start, got.event_end, got.event_precision) == (_utc(2026, 1, 1), None, "year")

    def test_an_interval_with_no_end_field_never_has_an_end(self) -> None:
        got = derive(Interval("a", "created"), {"a": _utc(2020, 5, 5)}.get)
        assert (got.event_start, got.event_end, got.event_precision) == (_utc(2020, 5, 5), None, "second")

    @AC[7]
    def test_an_end_whose_unit_is_over_when_the_start_begins_is_reversed(self) -> None:
        declaration = Interval("s", "created", end="e")
        for values in (
            {"s": "2026-11-02", "e": "2026-11-01"},
            {"s": "2026-11-02T00:00:00Z", "e": "2026-11-01"},
            {"s": "2026-12", "e": "2026-11"},
        ):
            derived = event_time.derive(declaration, values.get)
            assert derived.event_start is None and len(derived.warnings) == 1, values
        same_day = event_time.derive(declaration, {"s": "2026-11-02", "e": "2026-11-02"}.get)
        assert (same_day.event_start, same_day.event_end) == (_utc(2026, 11, 2), _utc(2026, 11, 3))
        instant = event_time.derive(declaration, {"s": "2026-11-02T00:00:00Z", "e": "2026-11-02T00:00:00Z"}.get)
        assert instant.event_start == instant.event_end == _utc(2026, 11, 2)

    def test_an_end_alone_is_not_an_event_time(self) -> None:
        got = derive(Interval("a", "created", end="b"), {"a": None, "b": "2026"}.get)
        assert got.as_columns() == dict.fromkeys(THREE)
        assert got.as_dimensions() == {TIME: None}
        assert got.warnings == ()

    def test_no_declaration_derives_nothing(self) -> None:
        for declaration in (None, NO_EVENT_TIME):
            assert derive(declaration, {}.get).as_columns() == dict.fromkeys(THREE)

    def test_a_future_time_is_stored(self) -> None:
        got = derive(Moment("a", "occurred"), {"a": "2999-01-01"}.get)
        assert got.event_start == _utc(2999, 1, 1)

    def test_an_unknown_kind_is_refused_at_declaration(self) -> None:
        with pytest.raises(event_time.EventTimeDeclarationError):
            Moment("a", "updated")


class TestOverlapsInPython:
    W = (_utc(2026, 12, 1, 12), _utc(2026, 12, 1, 13))

    def test_a_moment_at_the_windows_start_is_inside_and_one_at_its_end_is_not(self) -> None:
        assert overlaps(self.W[0], self.W[0], *self.W)
        assert not overlaps(self.W[1], self.W[1], *self.W)

    def test_a_span_that_ended_at_the_windows_start_does_not_overlap(self) -> None:
        assert not overlaps(_utc(2026, 12, 1, 11), self.W[0], *self.W)

    def test_an_open_ended_row_matches_every_window_after_its_start(self) -> None:
        assert overlaps(_utc(2020, 1, 1), None, *self.W)
        assert not overlaps(_utc(2027, 1, 1), None, *self.W)

    def test_a_row_with_no_event_time_matches_nothing(self) -> None:
        assert not overlaps(None, None, *self.W)

    @AC[8]
    def test_an_empty_or_reversed_window_is_refused(self) -> None:
        from tap_grid.event_time import overlapping

        start, end = self.W
        for window in ((start, start), (end, start)):
            with pytest.raises(ValueError, match="after its start"):
                overlaps(_utc(2020, 1, 1), None, *window)
            with pytest.raises(ValueError, match="after its start"):
                overlapping(*window)


class TestTheLastStorableYear:
    @AC[16]
    @pytest.mark.parametrize("value", ["9999", "9999-12", "9999-12-31"])
    def test_a_unit_that_ends_after_the_last_storable_time_is_refused(self, value: str) -> None:
        with pytest.raises(event_time.Unreadable, match="last time the grid can store"):
            event_time.read_value(value)

    @AC[15]
    def test_the_units_before_it_are_read_whole(self) -> None:
        for value, end in (
            ("9998", _utc(9999, 1, 1)),
            ("9999-11", _utc(9999, 12, 1)),
            ("9999-12-30", _utc(9999, 12, 31)),
        ):
            reading = event_time.read_value(value)
            assert reading is not None and reading.end_exclusive == end


# ---------------------------------------------------------------------------
# The spine columns
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeclaredMoment:
    @AC[1]
    def test_a_declared_moment_is_copied_in_utc(self, moment_on_observed_at: None) -> None:
        result = _create({"name": "login", "observed_at": "2026-12-01T18:30:00+02:00"})
        assert _four(result.entity_id) == (_utc(2026, 12, 1, 16, 30), _utc(2026, 12, 1, 16, 30), "occurred", "second")
        assert result.warnings == []

    @AC[4]
    def test_an_empty_declared_field_is_never_defaulted(self, moment_on_observed_at: None) -> None:
        result = _create({"name": "no-time"})
        assert _four(result.entity_id) == (None, None, None, None)
        patched = patch_node(result.entity_id, {"description": "changed"}, caller_context=_ctx())
        assert patched.success, patched.errors
        assert _four(result.entity_id) == (None, None, None, None)

    @AC[4]
    def test_a_value_taken_away_empties_the_four(self, moment_on_observed_at: None) -> None:
        result = _create({"name": "had-time", "observed_at": "2026-12-01T18:30:00Z"})
        assert _row(result.entity_id).event_start is not None
        assert patch_node(result.entity_id, {"observed_at": None}, caller_context=_ctx()).success
        assert _four(result.entity_id) == (None, None, None, None)

    @AC[10]
    def test_a_patch_to_the_declared_field_moves_the_spine_with_one_version(self, moment_on_observed_at: None) -> None:
        result = _create({"name": "moved", "observed_at": "2026-12-01T18:30:00Z"})
        before = _row(result.entity_id).version
        patched = patch_node(result.entity_id, {"observed_at": "2026-12-02T08:00:00Z"}, caller_context=_ctx())
        assert patched.success, patched.errors
        row = _row(result.entity_id)
        assert (row.event_start, row.event_end) == (_utc(2026, 12, 2, 8), _utc(2026, 12, 2, 8))
        assert row.version == before + 1

    def test_an_unchanged_write_leaves_the_spine_as_it_was(self, moment_on_observed_at: None) -> None:
        result = _create({"name": "same", "observed_at": "2026-12-01T18:30:00Z"})
        before = _four(result.entity_id)
        again = patch_node(result.entity_id, {"name": "same"}, caller_context=_ctx())
        assert again.state == WRITE_UNCHANGED
        assert _four(result.entity_id) == before

    def test_an_undeclared_model_derives_nothing(self) -> None:
        result = _create({"name": "undeclared", "observed_at": "2026-12-01T18:30:00Z"})
        assert _four(result.entity_id) == (None, None, None, None)
        assert result.warnings == []


@pytest.mark.django_db
class TestDeclaredInterval:
    @AC[2]
    def test_a_declared_span_is_copied(self, interval_on_text: None) -> None:
        result = _create({"name": "held", "description": "2026-11-01T00:00:00Z", "kind": "2026-11-03T06:00:00Z"})
        assert _four(result.entity_id) == (_utc(2026, 11, 1), _utc(2026, 11, 3, 6), "created", "second")

    @AC[2]
    def test_an_empty_end_field_leaves_the_end_empty(self, interval_on_text: None) -> None:
        result = _create({"name": "still-holds", "description": "2026-11-01T00:00:00Z"})
        assert _four(result.entity_id) == (_utc(2026, 11, 1), None, "created", "second")

    @AC[2]
    def test_a_partial_save_derives_from_what_the_row_holds(self, interval_on_text: None) -> None:
        result = _create({"name": "held", "description": "2026-11-01T00:00:00Z", "kind": "2026-11-03T06:00:00Z"})
        node = PgNode.objects.get(entity_id=result.entity_id)
        node.description = "2026-11-02T00:00:00Z"
        node.kind = "2030-01-01T00:00:00Z"  # changed in memory and not stored
        node.save(update_fields=["description"])
        assert PgNode.objects.get(entity_id=result.entity_id).kind == "2026-11-03T06:00:00Z"
        assert _four(result.entity_id) == (_utc(2026, 11, 2), _utc(2026, 11, 3, 6), "created", "second")

    @AC[7]
    def test_an_end_before_its_start_is_not_copied(self, interval_on_text: None) -> None:
        result = _create({"name": "backwards", "description": "2026-11-03", "kind": "2026-11-01"})
        assert _four(result.entity_id) == (None, None, None, None)
        node = PgNode.objects.get(entity_id=result.entity_id)
        assert (node.description, node.kind) == ("2026-11-03", "2026-11-01")
        assert len(result.warnings) == 1 and "kind" in result.warnings[0]


@pytest.mark.django_db
class TestPartialPrecision:
    @AC[5]
    @AC[17]
    def test_a_date_with_no_time_covers_its_day(self, moment_on_description: None) -> None:
        result = _create({"name": "day", "description": "2026-12-01"})
        assert _four(result.entity_id) == (_utc(2026, 12, 1), _utc(2026, 12, 2), "published", "day")
        # The original stays in the model it is derived from, as the source gave it (rule 22).
        assert PgNode.objects.get(entity_id=result.entity_id).description == "2026-12-01"

    @AC[15]
    def test_four_forms_on_four_rows_give_four_levels(self, moment_on_description: None) -> None:
        forms = ["2026", "2026-12", "2026-12-01", "2026-12-01T18:30:00Z"]
        rows = [_row(_create({"name": f"n{i}", "description": text}).entity_id) for i, text in enumerate(forms)]
        assert [row.event_precision for row in rows] == ["year", "month", "day", "second"]
        assert [(row.event_start, row.event_end) for row in rows] == [
            (_utc(2026, 1, 1), _utc(2027, 1, 1)),
            (_utc(2026, 12, 1), _utc(2027, 1, 1)),
            (_utc(2026, 12, 1), _utc(2026, 12, 2)),
            (_utc(2026, 12, 1, 18, 30), _utc(2026, 12, 1, 18, 30)),
        ]

    @AC[6]
    @AC[16]
    @pytest.mark.parametrize("text", ["2026-12-01T18", "2026-12-01T18:30", "2026-12-01T18:30:00"])
    def test_a_value_the_grid_cannot_store_is_left_off_and_reported(
        self, moment_on_description: None, text: str
    ) -> None:
        result = _create({"name": "unstorable", "description": text})
        assert result.success
        assert _four(result.entity_id) == (None, None, None, None)
        assert len(result.warnings) == 1
        assert result.warnings[0].startswith("event_time_not_stored: description:")
        # The typed field keeps what the source sent (rule 12).
        assert PgNode.objects.get(entity_id=result.entity_id).description == text

    def test_the_warning_is_reported_on_an_unchanged_write_too(self, moment_on_description: None) -> None:
        result = _create({"name": "again", "description": "2026-12-01T18:30:00"})
        again = patch_node(result.entity_id, {"name": "again"}, caller_context=_ctx())
        assert again.state == WRITE_UNCHANGED
        assert len(again.warnings) == 1


@pytest.mark.django_db
class TestTheOverlapTest:
    @AC[8]
    def test_a_moment_in_the_window_and_an_overlapping_span_match(self, interval_on_text: None) -> None:
        window = (_utc(2026, 12, 1, 12), _utc(2026, 12, 1, 13))
        moment = _create(
            {"name": "moment", "description": "2026-12-01T12:30:00Z", "kind": "2026-12-01T12:30:00Z"}
        ).entity_id
        at_start = _create(
            {"name": "at-start", "description": "2026-12-01T12:00:00Z", "kind": "2026-12-01T12:00:00Z"}
        ).entity_id
        span = _create(
            {"name": "span", "description": "2026-12-01T11:00:00Z", "kind": "2026-12-01T12:10:00Z"}
        ).entity_id
        ended = _create(
            {"name": "ended", "description": "2026-12-01T11:00:00Z", "kind": "2026-12-01T12:00:00Z"}
        ).entity_id
        at_end = _create(
            {"name": "at-end", "description": "2026-12-01T13:00:00Z", "kind": "2026-12-01T13:00:00Z"}
        ).entity_id
        open_ended = _create({"name": "open", "description": "2020-01-01T00:00:00Z"}).entity_id
        untimed = _create({"name": "untimed"}).entity_id

        found = set(Entity.objects.filter(entity_type=_TYPE).filter(overlapping(*window)).values_list("pk", flat=True))
        assert found == {moment, at_start, span, open_ended}
        assert not found & {ended, at_end, untimed}
        # The same rule from a typed row, and in plain Python.
        typed = set(PgNode.objects.filter(overlapping(*window, prefix="entity__")).values_list("entity_id", flat=True))
        assert typed == found
        for entity_id in (moment, at_start, span, ended, at_end, open_ended, untimed):
            row = _row(entity_id)
            assert overlaps(row.event_start, row.event_end, *window) == (entity_id in found)

    @AC[14]
    def test_an_imprecise_value_is_a_possible_match(self, moment_on_description: None) -> None:
        day = _create({"name": "day", "description": "2026-12-01"}).entity_id
        exact = _create({"name": "exact", "description": "2026-12-01T12:30:00Z"}).entity_id
        window = overlapping(_utc(2026, 12, 1, 12), _utc(2026, 12, 1, 13))
        rows = Entity.objects.filter(entity_type=_TYPE).filter(window)
        assert set(rows.values_list("pk", flat=True)) == {day, exact}
        assert set(rows.filter(event_precision="second").values_list("pk", flat=True)) == {exact}


@pytest.mark.django_db
class TestNotImportable:
    @AC[9]
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("event_start", "2026-12-01T00:00:00Z"),
            ("event_end", "2026-12-02T00:00:00Z"),
            ("event_precision", "day"),
        ],
    )
    def test_an_envelope_that_supplies_an_event_field_is_refused(self, field: str, value: str) -> None:
        entity_id = str(uuid.uuid4())
        node: dict[str, Any] = {
            "entity": {
                "entity_id": entity_id,
                "entity_type": "panel",
                "name": "p-ev",
                "dimensions": {"tap.graph": "web"},
            },
            "node": {"name": "p-ev", "slug": "p-ev", "description": "", "view": "tap_web/panel_error.html"},
        }
        node["entity"][field] = value
        result = grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[node])]))
        assert not result.success
        assert any(field in error.message for error in result.errors), [e.message for e in result.errors]
        assert not Entity.objects.filter(pk=entity_id).exists()


@pytest.mark.django_db
class TestEdges:
    def _pair(self) -> tuple[Any, Any]:
        a = PgNode.objects.get(entity_id=_create({"name": "a"}).entity_id)
        b = PgNode.objects.get(entity_id=_create({"name": "b"}).entity_id)
        return a, b

    @AC[18]
    def test_an_edge_type_that_declares_a_moment_has_its_pair_set_from_the_property(
        self, edge_moment_on_since: None
    ) -> None:
        a, b = self._pair()
        edge = create_edge(a.entity, b.entity, LINK, {"since": "2026-12"}, caller_context=_ctx())
        assert _four(edge.entity_id) == (_utc(2026, 12, 1), _utc(2027, 1, 1), "first_seen", "month")
        assert Edge.objects.get(entity_id=edge.entity_id).properties == {"since": "2026-12"}

    @AC[18]
    def test_a_change_to_the_property_moves_the_edges_spine(self, edge_moment_on_since: None) -> None:
        a, b = self._pair()
        edge = create_edge(a.entity, b.entity, LINK, {"since": "2026-12"}, caller_context=_ctx())
        result = patch_edge(edge.entity_id, {"properties": {"since": "2026-12-05T00:00:00Z"}}, caller_context=_ctx())
        assert result.success, result.errors
        assert _four(edge.entity_id) == (_utc(2026, 12, 5), _utc(2026, 12, 5), "first_seen", "second")

    @AC[18]
    def test_an_edge_type_that_declares_nothing_has_no_event_time(self) -> None:
        a, b = self._pair()
        edge = create_edge(a.entity, b.entity, LINK, {"since": "2026-12"}, caller_context=_ctx())
        assert _four(edge.entity_id) == (None, None, None, None)

    @AC[18]
    def test_the_edge_definition_takes_the_declaration_and_does_not_require_it(self) -> None:
        import jsonschema

        schema = json.loads((SPEC.parents[1] / "schemas" / "edge-definition.schema.json").read_text(encoding="utf-8"))
        base = {"slug": "X__y", "name": "X", "description": "x"}
        jsonschema.validate(base, schema)  # none is the default, and validation does not fail
        moment = {"shape": "moment", "field": "since", "kind": "first_seen"}
        interval = {"shape": "interval", "start": "from", "end": "until", "kind": "created"}
        for entry in (moment, interval, {"shape": "interval", "start": "from", "kind": "created"}):
            jsonschema.validate({**base, "event_time": entry}, schema)
            declaration_from_definition(entry)
        for wrong in (
            {"shape": "moment", "kind": "first_seen"},
            {"shape": "moment", "field": "a", "start": "b", "kind": "first_seen"},
            {"shape": "interval", "field": "a", "kind": "created"},
            {"shape": "moment", "field": "a", "kind": "updated"},
            {"shape": "instant", "field": "a", "kind": "occurred"},
        ):
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate({**base, "event_time": wrong}, schema)
            with pytest.raises(event_time.EventTimeDeclarationError):
                declaration_from_definition(wrong)
        assert declaration_from_definition(moment) == Moment("since", "first_seen")
        assert declaration_from_definition(interval) == Interval("from", "created", end="until")

    @AC[19]
    def test_a_value_the_one_reader_refuses_is_refused_for_a_node_and_an_edge(
        self, moment_on_description: None, edge_moment_on_since: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(value: Any) -> Any:
            if value in (None, ""):
                return None
            raise Unreadable("refused by the test")

        monkeypatch.setattr(event_time, "read_value", refuse)
        node = _create({"name": "n", "description": "2026-12-01"})
        assert _four(node.entity_id) == (None, None, None, None)
        assert "refused by the test" in node.warnings[0]
        a, b = self._pair()
        edge = create_edge(a.entity, b.entity, LINK, {"since": "2026-12-01"}, caller_context=_ctx())
        assert _four(edge.entity_id) == (None, None, None, None)


# ---------------------------------------------------------------------------
# The re-derive pass
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRederive:
    @AC[11]
    def test_a_type_whose_declaration_is_removed_loses_its_time_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_grid.event_time_rederive import rederive_event_time

        monkeypatch.setattr(PgNode, "EVENT_TIME", Moment("observed_at", "occurred"), raising=False)
        pk = _create({"name": "was-timed", "observed_at": "2026-12-01T18:30:00Z"}).entity_id
        before = _row(pk)
        assert _kind(pk) == "occurred"
        monkeypatch.setattr(PgNode, "EVENT_TIME", NO_EVENT_TIME, raising=False)
        report = rederive_event_time([_TYPE])
        assert report.changed == 1
        after = _row(pk)
        assert _four(pk) == (None, None, None, None)
        assert (after.version, after.updated_at) == (before.version, before.updated_at)
        other = {key: value for key, value in before.dimensions.items() if key != declared(TIME).id}
        assert after.dimensions == other

    @AC[11]
    def test_a_row_changed_since_it_was_read_is_left_to_the_newer_save(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_grid.event_time_rederive import rederive_event_time

        pk = _create({"name": "raced", "observed_at": "2026-12-01T18:30:00Z"}).entity_id
        monkeypatch.setattr(PgNode, "EVENT_TIME", Moment("observed_at", "occurred"), raising=False)
        real = event_time.derive_for_instance

        def derive_then_lose_the_race(row: Any) -> Any:
            derived = real(row)  # the pass has read the row; now another writer changes it
            result = patch_node(pk, {"observed_at": "2027-01-01T00:00:00Z"}, caller_context=_ctx())
            assert result.success, result.errors
            return derived

        monkeypatch.setattr("tap_grid.event_time_rederive.derive_for_instance", derive_then_lose_the_race)
        report = rederive_event_time([_TYPE])

        assert (report.changed, report.raced) == (0, 1)
        assert _row(pk).event_start == _utc(2027, 1, 1)
        assert report.batch_id is None or not BatchEvent.objects.filter(batch__entity_id=report.batch_id).exists()

    @AC[11]
    def test_it_fills_existing_rows_and_writes_no_history_and_no_version(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_grid.candidates import _OBSERVATION_EVENTS
        from tap_grid.event_time_rederive import rederive_event_time

        timed = [_create({"name": f"t{i}", "observed_at": "2026-12-01T18:30:00Z"}).entity_id for i in range(3)]
        untimed = _create({"name": "untimed"}).entity_id
        before = {pk: _row(pk) for pk in [*timed, untimed]}
        history = {pk: PgNode.history.filter(entity_id=pk).count() for pk in timed}

        # The declaration arrives after the rows were written.
        monkeypatch.setattr(PgNode, "EVENT_TIME", Moment("observed_at", "occurred"), raising=False)
        report = rederive_event_time([_TYPE])

        assert (report.changed, report.by_type) == (3, {_TYPE: 3})
        assert report.batch_id is not None
        for pk in timed:
            row = _row(pk)
            assert (row.event_start, row.event_end, _kind(pk), row.event_precision) == (
                _utc(2026, 12, 1, 18, 30),
                _utc(2026, 12, 1, 18, 30),
                "occurred",
                "second",
            )
            assert row.version == before[pk].version
            assert row.updated_at == before[pk].updated_at
            assert PgNode.history.filter(entity_id=pk).count() == history[pk]
            # No source or analyst named the object: the pointers stay where they were.
            assert row.last_observed_at == before[pk].last_observed_at
            assert row.last_observed_batch_id == before[pk].last_observed_batch_id
            assert row.last_changed_batch_id == before[pk].last_changed_batch_id
        events = BatchEvent.objects.filter(batch__entity_id=report.batch_id)
        assert sorted(events.values_list("entity_id", flat=True)) == sorted(timed)
        assert set(events.values_list("event_type", flat=True)) == {BatchEventType.MAINTENANCE}
        assert not BatchEvent.objects.filter(entity_id=untimed, event_type=BatchEventType.MAINTENANCE).exists()
        # Maintenance is not a sighting: the readers that ask "did a batch see this" leave it out.
        assert BatchEventType.MAINTENANCE not in _OBSERVATION_EVENTS

    @AC[11]
    def test_a_second_pass_changes_nothing_and_opens_no_batch(self, moment_on_observed_at: None) -> None:
        from tap_grid.event_time_rederive import rederive_event_time

        _create({"name": "in-step", "observed_at": "2026-12-01T18:30:00Z"})
        report = rederive_event_time([_TYPE])
        assert (report.changed, report.batch_id) == (0, None)

    @AC[11]
    def test_a_declaration_taken_away_empties_the_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_grid.event_time_rederive import rederive_event_time

        monkeypatch.setattr(PgNode, "EVENT_TIME", Moment("observed_at", "occurred"), raising=False)
        pk = _create({"name": "was-timed", "observed_at": "2026-12-01T18:30:00Z"}).entity_id
        monkeypatch.setattr(PgNode, "EVENT_TIME", NO_EVENT_TIME, raising=False)
        assert rederive_event_time([_TYPE]).changed == 1
        assert _four(pk) == (None, None, None, None)

    def test_a_type_named_wrongly_is_an_error(self) -> None:
        from tap_grid.event_time_rederive import rederive_event_time

        with pytest.raises(ValueError, match="not a registered entity type"):
            rederive_event_time(["no_such_type"])

    @pytest.mark.parametrize(
        "path",
        ["tap_grid/candidates.py", "tap_grid/reconcile.py", "tap_grid/grift/importer.py"],
    )
    def test_no_reader_of_sightings_names_the_maintenance_type(self, path: str) -> None:
        source = (SPEC.parents[2] / path).read_text(encoding="utf-8")
        assert "MAINTENANCE" not in source and '"maintenance"' not in source


# ---------------------------------------------------------------------------
# The surface, the columns and the declaration check
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTheTimeDimension:
    """The kind is the row's `time` dimension, written by the grid alone (rule 3)."""

    def _panel(self, entity_id: str, description: str, *, dimensions: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "entity": {
                "entity_id": entity_id,
                "entity_type": "panel",
                "name": "p-time",
                "dimensions": {"tap.graph": "web"} if dimensions is None else dimensions,
            },
            "node": {
                "name": "p-time",
                "slug": "p-time",
                "description": description,
                "view": "tap_web/panel_error.html",
            },
        }

    def _import(self, node: dict[str, Any]) -> Any:
        return grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[node])]))

    @pytest.fixture
    def timed_panels(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_web.models import Panel

        monkeypatch.setattr(Panel, "EVENT_TIME", Moment("description", "published"), raising=False)

    @AC[20]
    def test_the_kind_is_stored_as_a_derived_dimension_entry(self, moment_on_observed_at: None) -> None:
        pk = _create({"name": "kinded", "observed_at": "2026-12-01T18:30:00Z"}).entity_id
        entry = _row(pk).dimensions[declared(TIME).id]
        assert entry == {"v": "occurred", "src": "derived"}
        assert declared(TIME).id in grid_derived_ids()

    @AC[20]
    def test_a_kind_is_checked_against_the_dimensions_own_values(self) -> None:
        assert event_time.kind_problem("occurred") is None
        problem = event_time.kind_problem("resolved")
        assert problem is not None and "'time' dimension" in problem and "first_seen" in problem

    @AC[20]
    def test_a_row_with_no_event_time_carries_no_time_value(self, moment_on_observed_at: None) -> None:
        pk = _create({"name": "untimed"}).entity_id
        assert TIME not in view(_row(pk).dimensions)
        assert patch_node(pk, {"observed_at": "2026-12-02T08:00:00Z"}, caller_context=_ctx()).success
        assert _kind(pk) == "occurred"
        assert patch_node(pk, {"observed_at": None}, caller_context=_ctx()).success
        assert TIME not in view(_row(pk).dimensions)

    @AC[21]
    def test_a_writer_may_not_supply_it(self, moment_on_observed_at: None) -> None:
        op = WriteOperation(
            verb="create_node", type_slug=_TYPE, payload={"name": "forged"}, dimensions={TIME: "published"}
        )
        refused = write_batch([op], caller_context=_ctx())
        assert not refused.success
        assert "written by the grid only" in str([r.errors for r in refused.results]), refused.results
        assert not PgNode.objects.filter(name="forged").exists()
        with pytest.raises(DimensionWriteError, match="written by the grid only"):
            settle({TIME: "created"}, None)
        with pytest.raises(DimensionWriteError, match="written by the grid only"):
            settle(None, {TIME: {"v": "created", "src": "derived"}})
        with pytest.raises(DimensionWriteError, match="not a dimension the grid derives"):
            with_grid_derived({}, {"tap.graph": "web"})

    @AC[21]
    def test_an_envelope_that_supplies_it_is_refused(self, timed_panels: None) -> None:
        entity_id = str(uuid.uuid4())
        result = self._import(self._panel(entity_id, "2026-12-01", dimensions={"tap.graph": "web", TIME: "published"}))
        assert not result.success
        assert any("written by the grid only" in error.message for error in result.errors), [
            e.message for e in result.errors
        ]
        assert not Entity.objects.filter(pk=entity_id).exists()

    @AC[22]
    def test_an_unchanged_reimport_is_unchanged_and_keeps_it(self, timed_panels: None) -> None:
        """The hazard: an envelope never carries `time`, and the stored map does."""
        from tap_web.models import Panel

        entity_id = str(uuid.uuid4())
        assert self._import(self._panel(entity_id, "2026-12-01")).success
        before = _row(entity_id)
        assert _four(entity_id) == (_utc(2026, 12, 1), _utc(2026, 12, 2), "published", "day")
        history = getattr(Panel, "history").filter(entity_id=entity_id).count()  # noqa: B009

        for _ in range(2):
            assert self._import(self._panel(entity_id, "2026-12-01")).success
        after = _row(entity_id)
        assert (after.version, after.updated_at) == (before.version, before.updated_at)
        assert getattr(Panel, "history").filter(entity_id=entity_id).count() == history  # noqa: B009
        assert after.dimensions == before.dimensions
        assert _kind(entity_id) == "published"
        events = list(
            BatchEvent.objects.filter(entity_id=entity_id).order_by("id").values_list("event_type", flat=True)
        )
        assert events == [BatchEventType.CREATE, BatchEventType.OBSERVE, BatchEventType.OBSERVE]

    @AC[22]
    def test_a_reimport_that_moves_only_the_declared_field_keeps_it(self, timed_panels: None) -> None:
        entity_id = str(uuid.uuid4())
        assert self._import(self._panel(entity_id, "2026-12-01")).success
        version = _row(entity_id).version
        assert self._import(self._panel(entity_id, "2026-12-05")).success
        assert _four(entity_id) == (_utc(2026, 12, 5), _utc(2026, 12, 6), "published", "day")
        assert _row(entity_id).version == version + 1

    @AC[22]
    def test_a_reimport_that_changes_a_callers_dimension_keeps_it(self, timed_panels: None) -> None:
        entity_id = str(uuid.uuid4())
        assert self._import(self._panel(entity_id, "2026-12-01")).success
        assert self._import(
            self._panel(entity_id, "2026-12-01", dimensions={"tap.graph": "web", "zone": "north"})
        ).success
        names = view(_row(entity_id).dimensions)
        assert (names["zone"], names[TIME]) == ("north", "published")

    @AC[23]
    def test_an_export_leaves_it_out_and_round_trips(self, timed_panels: None) -> None:
        from tap_grid.grift.exporter import _entity_envelope

        entity_id = str(uuid.uuid4())
        assert self._import(self._panel(entity_id, "2026-12-01")).success
        envelope = _entity_envelope(_row(entity_id))
        assert declared(TIME).id not in envelope["dimensions"]
        assert envelope["dimensions"]
        node = self._panel(entity_id, "2026-12-01", dimensions=envelope["dimensions"])
        before = _row(entity_id)
        assert self._import(node).success
        after = _row(entity_id)
        assert (after.version, after.dimensions) == (before.version, before.dimensions)


class TestSpineSurface:
    def test_the_three_join_the_canonical_surface(self) -> None:
        names = Entity.SPINE_FIELD_NAMES
        assert names[names.index("last_observed_at") + 1 : names.index("originating_grid_id")] == THREE
        assert "event_kind" not in {field.name for field in Entity._meta.fields}

    def test_only_the_start_is_indexed(self) -> None:
        fields = {field.name: field for field in Entity._meta.fields}
        assert getattr(fields["event_start"], "db_index") is True  # noqa: B009
        for name in ("event_end", "event_precision"):
            assert getattr(fields[name], "db_index") is False  # noqa: B009

    @AC[13]
    def test_the_migration_touches_the_grids_own_tables_only(self) -> None:
        migration = importlib.import_module("tap_grid.migrations.0018_entity_event_time").Migration
        added = [op.name for op in migration.operations if type(op).__name__ == "AddField"]
        assert sorted(added) == sorted([*THREE, "event_kind"])
        assert {op.model_name for op in migration.operations} == {"entity", "batchevent"}
        assert migration.dependencies == [("tap_grid", "0017_entity_batch_pointers")]
        # The kind left the row for the `time` dimension: the next migration drops that one column.
        follow_up = importlib.import_module("tap_grid.migrations.0019_entity_event_kind_to_time_dimension").Migration
        assert [(type(op).__name__, op.model_name, op.name) for op in follow_up.operations] == [
            ("RemoveField", "entity", "event_kind")
        ]

    @pytest.mark.django_db
    def test_the_envelope_surface_carries_them(self, moment_on_description: None) -> None:
        pk = _create({"name": "surfaced", "description": "2026-12-01"}).entity_id
        surface = build_spine_surface(_row(pk))
        assert surface["event_start"] == "2026-12-01T00:00:00+00:00"
        assert surface["event_end"] == "2026-12-02T00:00:00+00:00"
        assert surface["event_precision"] == "day"
        assert "event_kind" not in surface
        assert view(_row(pk).dimensions)[TIME] == "published"


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonReadsThem:
    @AC[12]
    def test_one_window_filters_nodes_of_two_types(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_grid.gryphon import execute_gryphon_raw

        monkeypatch.setattr(PgNode, "EVENT_TIME", Moment("observed_at", "occurred"), raising=False)
        monkeypatch.setattr(PgHub, "EVENT_TIME", Moment("observed_at", "occurred"), raising=False)
        node_in = _create({"name": "node-in", "observed_at": "2026-12-01T12:30:00Z"}).entity_id
        hub_in = _create({"name": "hub-in", "observed_at": "2026-12-01T12:45:00Z"}, _HUB).entity_id
        _create({"name": "node-out", "observed_at": "2026-12-01T14:00:00Z"})
        _create({"name": "hub-out", "observed_at": "2026-11-30T12:30:00Z"}, _HUB)

        found: set[str] = set()
        for label in (_TYPE, _HUB):
            rows = execute_gryphon_raw(
                f"MATCH (n:{label}) WHERE n.event_start >= $from AND n.event_start < $to "
                "RETURN n.entity_id AS id, n.event_precision AS precision",
                {"from": "2026-12-01T12:00:00+00:00", "to": "2026-12-01T13:00:00+00:00"},
            )["rows"]
            assert {row["precision"] for row in rows} == {"second"}
            found |= {str(row["id"]) for row in rows}
        assert found == {str(node_in), str(hub_in)}

    @AC[24]
    def test_one_query_filters_a_window_and_a_kind(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_grid.gryphon import execute_gryphon_raw

        monkeypatch.setattr(PgNode, "EVENT_TIME", Moment("observed_at", "occurred"), raising=False)
        monkeypatch.setattr(PgHub, "EVENT_TIME", Moment("observed_at", "created"), raising=False)
        occurred = _create({"name": "occurred-in", "observed_at": "2026-12-01T12:30:00Z"}).entity_id
        created = _create({"name": "created-in", "observed_at": "2026-12-01T12:40:00Z"}, _HUB).entity_id
        _create({"name": "occurred-out", "observed_at": "2026-12-01T14:00:00Z"})

        def found(label: str, kind: str) -> set[str]:
            rows = execute_gryphon_raw(
                f"MATCH (n:{label}) WHERE n.event_start >= $from AND n.event_start < $to "
                f'AND n.dimensions["time"] = "{kind}" RETURN n.entity_id AS id',
                {"from": "2026-12-01T12:00:00+00:00", "to": "2026-12-01T13:00:00+00:00"},
            )
            # A query that matches nothing returns no `rows` key.
            return {str(row["id"]) for row in rows.get("rows", [])}

        assert found(_TYPE, "occurred") == {str(occurred)}
        assert found(_HUB, "occurred") == set()
        assert found(_HUB, "created") == {str(created)}
        assert found(_TYPE, "created") == set()


class TestTheDeclarationCheck:
    def _run(self, *classes: Any) -> Any:
        from tap_plugins.validate.service import _check_event_time_declarations

        manifest = SimpleNamespace(
            models=[
                SimpleNamespace(slug=cls.ENTITY_TYPE, class_path=f"{cls.__module__}.{cls.__name__}") for cls in classes
            ]
        )
        result: Any = SimpleNamespace(checks=[])
        _check_event_time_declarations(manifest, result)
        return result.checks[-1]

    @AC[18]
    def test_an_edge_declaration_must_name_a_property_its_schema_defines(self) -> None:
        from tap_plugins.validate.service import _check_edge_event_time

        schema = {"type": "object", "properties": {"since": {"type": "string"}}}

        def run(event_time_entry: Any, property_schema: Any) -> Any:
            edge = SimpleNamespace(
                slug="LINKS_THING",
                file_path="edges/links.edge.json",
                event_time=event_time_entry,
                property_schema=property_schema,
            )
            result: Any = SimpleNamespace(checks=[])
            _check_edge_event_time(SimpleNamespace(edges=[edge]), result)
            return result.checks

        good = {"shape": "moment", "field": "since", "kind": "first_seen"}
        assert run(good, schema)[-1].status == "pass"
        typo = run({**good, "field": "sincee"}, schema)[-1]
        assert typo.status == "fail" and "sincee" in str(typo.messages)
        assert run(good, None)[-1].status == "fail"
        assert run(None, schema) == []

    @AC[3]
    def test_an_undeclared_model_is_reported_and_the_check_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(event_time.REQUIRE_DECLARATION_ENV, raising=False)
        check = self._run(PgNode)
        assert check.status == "pass"
        assert check.details == {"undeclared": [_TYPE], "required": False}
        # Carried at info severity: --strict promotes a warning-severity message to a failure.
        assert [m.severity for m in check.messages] == ["info"]
        assert check.messages[0].text.startswith("WARNING") and _TYPE in check.messages[0].text

    def test_the_switch_makes_an_undeclared_model_a_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(event_time.REQUIRE_DECLARATION_ENV, "1")
        check = self._run(PgNode)
        assert check.status == "fail"
        assert check.details == {"undeclared": [_TYPE], "required": True}

    @pytest.mark.parametrize("declared", [Moment("observed_at", "occurred"), NO_EVENT_TIME])
    def test_a_declared_model_passes_either_way(self, monkeypatch: pytest.MonkeyPatch, declared: Any) -> None:
        monkeypatch.setenv(event_time.REQUIRE_DECLARATION_ENV, "1")
        monkeypatch.setattr(PgNode, "EVENT_TIME", declared, raising=False)
        check = self._run(PgNode)
        assert check.status == "pass"
        assert check.details == {"undeclared": [], "required": True}

    @pytest.mark.parametrize("declared", [Moment("no_such_field", "occurred"), Moment("severity_score", "occurred")])
    def test_a_declaration_that_names_the_wrong_thing_fails_now(
        self, monkeypatch: pytest.MonkeyPatch, declared: Any
    ) -> None:
        monkeypatch.delenv(event_time.REQUIRE_DECLARATION_ENV, raising=False)
        monkeypatch.setattr(PgNode, "EVENT_TIME", declared, raising=False)
        assert declaration_problems(PgNode)
        assert self._run(PgNode).status == "fail"

    def test_cores_own_config_types_say_they_have_none(self) -> None:
        from tap_files.models import TapDirectory, TapFile
        from tap_grid.models import Dimension, Keystone, Search
        from tap_viz.models import Arrangement, Elevation, Layout, Projection
        from tap_web.models import Page, Panel

        for cls in (Arrangement, Elevation, Layout, Projection, Page, Panel, Dimension, Keystone, Search, TapFile):
            assert cls.EVENT_TIME is NO_EVENT_TIME, cls
        assert TapDirectory.EVENT_TIME is NO_EVENT_TIME
