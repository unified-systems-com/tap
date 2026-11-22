"""Collection time on the spine and on the batch event: when a collector read an object.

Covers ``req-grid-entity-collection-time`` (spec-grid-entity.md); Issue# 194 - tap. A window is
stated beside a write operation (``WriteOperation.collected``), apart from the object's fields.
Service writes use the neutral grid_fixtures ``PgNode`` and the ``PG_LINKS__grid_fixtures`` edge;
the import-refusal test uses a ``tap_web`` panel, as the other import suites do.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from tap_plugin.grid_fixtures.models.pg_node import PgNode

from tap_grid.caller_context import CallerContext
from tap_grid.collection_time import NOT_RECORDED, OLDER_READ, OUT_OF_ORDER, settle_window
from tap_grid.event_time import Moment
from tap_grid.grift import grift_import
from tap_grid.grift.subgraph import build_spine_surface
from tap_grid.models import BatchEvent, Edge, Entity
from tap_grid.service_types import WRITE_CHANGED, WRITE_UNCHANGED, CollectionWindow, WriteOperation, WriteResult
from tap_grid.services import write_batch
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc
from tap_grid.write_classification import spine_delta

AC = {n: pytest.mark.spec(f"req-grid-entity-collection-time-{n}") for n in range(1, 9)}

_TYPE = "grid_fixtures__node"
LINK = "PG_LINKS__grid_fixtures"
PAIR = ("collected_start", "collected_end")


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)  # type: ignore[arg-type, misc]


W1 = CollectionWindow(_utc(2026, 11, 20, 10, 0), _utc(2026, 11, 20, 10, 5))
W2 = CollectionWindow(_utc(2026, 11, 20, 11, 0), _utc(2026, 11, 20, 11, 5))
EARLIER = CollectionWindow(_utc(2026, 11, 20, 9, 0), _utc(2026, 11, 20, 9, 5))


def _run(op: WriteOperation) -> tuple[WriteResult, uuid.UUID]:
    """One operation in a fresh batch: its result and the batch's entity id."""
    batch_id = str(uuid.uuid7())
    outcome = write_batch(
        [op], caller_context=CallerContext(batch_id=batch_id), batch_name="collection time", batch_description="test"
    )
    assert outcome.success, [e.message for r in outcome.results for e in r.errors] + [e.message for e in outcome.errors]
    return outcome.results[0], uuid.UUID(batch_id)


def _create(name: str, collected: CollectionWindow | None = None, **fields: Any) -> uuid.UUID:
    result, _ = _run(
        WriteOperation(verb="create_node", type_slug=_TYPE, payload={"name": name, **fields}, collected=collected)
    )
    assert result.entity_id is not None
    return result.entity_id


def _reobserve(entity_id: uuid.UUID, name: str, collected: CollectionWindow | None) -> tuple[WriteResult, uuid.UUID]:
    """The write a re-import makes for an object it already holds: a keep-absent replace."""
    return _run(
        WriteOperation(
            verb="replace_node", target=entity_id, payload={"name": name}, absent="keep", collected=collected
        )
    )


def _eid(result: WriteResult) -> uuid.UUID:
    assert result.entity_id is not None
    return result.entity_id


def _pair(entity_id: Any) -> tuple[Any, Any]:
    row = Entity.objects.get(pk=entity_id)
    return row.collected_start, row.collected_end


def _event(entity_id: Any, batch: uuid.UUID) -> BatchEvent:
    return BatchEvent.objects.get(entity_id=entity_id, batch__entity_id=batch)


def _warned(result: WriteResult, token: str) -> list[str]:
    return [warning for warning in result.warnings if warning.startswith(token)]


# ---------------------------------------------------------------------------
# The window a writer states
# ---------------------------------------------------------------------------


class TestSettleWindow:
    @AC[2]
    def test_nothing_stated_is_an_empty_pair_and_no_warning(self) -> None:
        settled = settle_window(None)
        assert (settled.start, settled.end, settled.warnings) == (None, None, ())

    @AC[1]
    def test_a_stated_window_is_stored_in_utc(self) -> None:
        plus_two = timezone(timedelta(hours=2))
        settled = settle_window(
            CollectionWindow(datetime(2026, 11, 20, 12, 0, tzinfo=plus_two), "2026-11-20T12:05:00+02:00")
        )
        assert (settled.start, settled.end) == (_utc(2026, 11, 20, 10, 0), _utc(2026, 11, 20, 10, 5))
        assert settled.start is not None and settled.start.utcoffset() == timedelta(0)

    @AC[1]
    def test_a_read_in_one_call_has_equal_bounds(self) -> None:
        moment = _utc(2026, 11, 20, 10, 0)
        settled = settle_window(CollectionWindow(moment, moment))
        assert settled.start == settled.end == moment

    @AC[5]
    @pytest.mark.parametrize(
        ("window", "why"),
        [
            (CollectionWindow(_utc(2026, 11, 20, 10, 5), _utc(2026, 11, 20, 10, 0)), "is before the start"),
            (CollectionWindow(datetime(2026, 11, 20, 10, 0), _utc(2026, 11, 20, 10, 5)), "the start has no time zone"),
            (CollectionWindow(_utc(2026, 11, 20, 10, 0), "2026-11-20T10:05:00"), "the end has no time zone"),
            (CollectionWindow(_utc(2026, 11, 20, 10, 0), "yesterday"), "is not a date and time"),
        ],
    )
    def test_a_window_that_cannot_be_stored_truthfully_is_left_out(self, window: CollectionWindow, why: str) -> None:
        settled = settle_window(window)
        assert (settled.start, settled.end) == (None, None)
        assert len(settled.warnings) == 1
        assert settled.warnings[0].startswith(NOT_RECORDED) and why in settled.warnings[0]


# ---------------------------------------------------------------------------
# Recorded on the batch event and on the spine
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStatedPairIsRecorded:
    @AC[1]
    @AC[8]
    def test_a_create_that_states_a_window_sets_the_event_and_the_spine(self) -> None:
        result, batch = _run(
            WriteOperation(verb="create_node", type_slug=_TYPE, payload={"name": "stated"}, collected=W1)
        )
        assert result.state == WRITE_CHANGED and result.warnings == []
        assert _pair(result.entity_id) == (W1.start, W1.end)
        event = _event(result.entity_id, batch)
        assert (event.event_type, event.collected_start, event.collected_end) == ("create", W1.start, W1.end)
        # Apart from the object's own fields: nothing of it is on the typed row.
        assert PgNode.objects.get(entity_id=result.entity_id).observed_at is None

    @AC[1]
    def test_a_create_under_a_given_id_sets_them_too(self) -> None:
        given = uuid.uuid7()
        result, batch = _run(
            WriteOperation(
                verb="create_node", type_slug=_TYPE, payload={"name": "given"}, entity_id=given, collected=W1
            )
        )
        assert result.entity_id == given
        assert _pair(given) == (W1.start, W1.end)
        assert _event(given, batch).collected_end == W1.end
        assert Entity.objects.get(pk=given).version == 1

    @AC[1]
    def test_a_changing_write_sets_them_in_the_statement_that_names_its_batch(self) -> None:
        entity_id = _create("before", W1)
        result, batch = _run(
            WriteOperation(verb="patch_node", target=entity_id, payload={"name": "after"}, collected=W2)
        )
        assert result.state == WRITE_CHANGED
        row = Entity.objects.get(pk=entity_id)
        assert (row.collected_start, row.collected_end) == (W2.start, W2.end)
        assert row.last_observed_batch_id == batch and row.last_changed_batch_id == batch
        event = _event(entity_id, batch)
        assert (event.event_type, event.collected_start, event.collected_end) == ("update", W2.start, W2.end)

    @AC[1]
    def test_an_edge_carries_its_own_window(self) -> None:
        source, target = _create("from"), _create("to")
        result, batch = _run(
            WriteOperation(verb="create_edge", from_target=source, to_target=target, edge_type=LINK, collected=W1)
        )
        assert _pair(result.entity_id) == (W1.start, W1.end)
        assert _event(result.entity_id, batch).collected_start == W1.start
        assert Edge.objects.filter(entity_id=result.entity_id).exists()
        # The endpoints were not named by that operation: their pairs are as they were.
        assert _pair(source) == (None, None) and _pair(target) == (None, None)

    @AC[1]
    def test_a_retirement_carries_the_window_stated_for_the_node_and_none_for_the_edges_it_ends(self) -> None:
        source, target = _create("from", W1), _create("to", W1)
        edge, _ = _run(
            WriteOperation(verb="create_edge", from_target=source, to_target=target, edge_type=LINK, collected=W1)
        )
        result, batch = _run(WriteOperation(verb="delete_node", target=source, collected=W2))
        assert result.success
        assert _pair(source) == (W2.start, W2.end)
        assert _event(source, batch).collected_end == W2.end
        # The edge ended with the node. The retiring batch is the last to name it and stated no
        # window for it, so no pair is left standing on it.
        edge_row = Entity.objects.get(pk=_eid(edge))
        assert edge_row.deleted_at is not None and edge_row.last_observed_batch_id == batch
        assert (edge_row.collected_start, edge_row.collected_end) == (None, None)


@pytest.mark.django_db
class TestUnstatedPairStaysEmpty:
    @AC[2]
    def test_a_write_that_states_none_leaves_both_pairs_empty(self) -> None:
        result, batch = _run(WriteOperation(verb="create_node", type_slug=_TYPE, payload={"name": "unstated"}))
        row = Entity.objects.get(pk=_eid(result))
        assert (row.collected_start, row.collected_end) == (None, None)
        # Never the write time, which the row does carry.
        assert row.last_observed_at is not None and row.updated_at is not None
        event = _event(result.entity_id, batch)
        assert (event.collected_start, event.collected_end) == (None, None)
        assert event.timestamp is not None


@pytest.mark.django_db
class TestUnchangedObservation:
    @AC[3]
    def test_an_unchanged_reobservation_with_a_new_window_moves_the_pair_and_nothing_else(self) -> None:
        entity_id = _create("steady", W1)
        before = Entity.objects.get(pk=entity_id)
        history = PgNode.history.filter(entity_id=entity_id).count()

        result, batch = _reobserve(entity_id, "steady", W2)

        assert result.state == WRITE_UNCHANGED
        after = Entity.objects.get(pk=entity_id)
        assert (after.collected_start, after.collected_end) == (W2.start, W2.end)
        assert after.version == before.version
        assert after.updated_at == before.updated_at
        assert PgNode.history.filter(entity_id=entity_id).count() == history
        assert after.last_changed_batch_id == before.last_changed_batch_id
        assert after.last_observed_batch_id == batch
        event = _event(entity_id, batch)
        assert (event.event_type, event.collected_start, event.collected_end) == ("observe", W2.start, W2.end)

    @AC[3]
    def test_a_window_is_not_a_spine_value_the_classifier_compares(self) -> None:
        entity_id = _create("steady", W1)
        # What the importer hands the classifier for a re-import is the envelope's name and
        # dimensions, read against the stored row. The row's window takes no part in it.
        row = Entity.objects.get(pk=entity_id)
        intent = {
            "entity_id": str(entity_id),
            "entity_type": _TYPE,
            "envelope_name": row.name,
            "envelope_dims": {},
        }
        assert spine_delta(intent) == {}
        patched, _ = _run(WriteOperation(verb="patch_node", target=entity_id, payload={"name": "steady"}, collected=W2))
        assert patched.state == WRITE_UNCHANGED
        assert spine_delta(intent) == {}

    @AC[4]
    def test_a_later_pass_that_states_none_empties_the_pair(self) -> None:
        entity_id = _create("steady", W1)
        seen = Entity.objects.get(pk=entity_id).last_observed_at

        result, batch = _reobserve(entity_id, "steady", None)

        assert result.state == WRITE_UNCHANGED and result.warnings == []
        row = Entity.objects.get(pk=entity_id)
        assert (row.collected_start, row.collected_end) == (None, None)
        assert row.last_observed_at > seen and row.last_observed_batch_id == batch
        event = _event(entity_id, batch)
        assert (event.event_type, event.collected_start, event.collected_end) == ("observe", None, None)

    @AC[4]
    def test_a_changing_pass_that_states_none_empties_it_too(self) -> None:
        entity_id = _create("before", W1)
        result, _ = _run(WriteOperation(verb="patch_node", target=entity_id, payload={"name": "after"}))
        assert result.state == WRITE_CHANGED
        assert _pair(entity_id) == (None, None)


@pytest.mark.django_db
class TestBadPairNotRecorded:
    @AC[5]
    @pytest.mark.parametrize(
        "window",
        [
            CollectionWindow(_utc(2026, 11, 20, 10, 5), _utc(2026, 11, 20, 10, 0)),
            CollectionWindow(datetime(2026, 11, 20, 10, 0), datetime(2026, 11, 20, 10, 5)),
        ],
    )
    def test_the_write_succeeds_records_nothing_and_warns(self, window: CollectionWindow) -> None:
        result, batch = _run(
            WriteOperation(verb="create_node", type_slug=_TYPE, payload={"name": "bad window"}, collected=window)
        )
        assert result.success and result.state == WRITE_CHANGED
        assert len(_warned(result, NOT_RECORDED)) == 1
        assert _pair(result.entity_id) == (None, None)
        event = _event(result.entity_id, batch)
        assert (event.collected_start, event.collected_end) == (None, None)

    @AC[5]
    def test_a_bad_window_on_a_reobservation_empties_the_pair_it_would_have_replaced(self) -> None:
        entity_id = _create("steady", W1)
        result, _ = _reobserve(entity_id, "steady", CollectionWindow(datetime(2026, 11, 20, 11, 0), W2.end))
        assert len(_warned(result, NOT_RECORDED)) == 1
        assert _pair(entity_id) == (None, None)


@pytest.mark.django_db
class TestOrderNotEnforced:
    @AC[6]
    def test_an_event_time_later_than_the_collection_time_is_recorded_and_reported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(PgNode, "EVENT_TIME", Moment("observed_at", "occurred"), raising=False)
        result, _ = _run(
            WriteOperation(
                verb="create_node",
                type_slug=_TYPE,
                payload={"name": "clock", "observed_at": "2026-11-20T12:00:00Z"},
                collected=W1,
            )
        )
        assert result.success
        row = Entity.objects.get(pk=_eid(result))
        assert row.event_start == _utc(2026, 11, 20, 12, 0)
        assert (row.collected_start, row.collected_end) == (W1.start, W1.end)
        reported = _warned(result, OUT_OF_ORDER)
        assert len(reported) == 1 and str(result.entity_id) in reported[0] and "event time" in reported[0]

    @AC[6]
    def test_a_collection_time_later_than_the_write_is_recorded_and_reported(self) -> None:
        ahead = datetime.now(UTC) + timedelta(days=1)
        result, _ = _run(
            WriteOperation(
                verb="create_node", type_slug=_TYPE, payload={"name": "ahead"}, collected=CollectionWindow(ahead, ahead)
            )
        )
        assert _pair(result.entity_id) == (ahead, ahead)
        reported = _warned(result, OUT_OF_ORDER)
        assert len(reported) == 1 and "time of this write" in reported[0]

    @AC[6]
    def test_an_ordinary_window_reports_nothing(self) -> None:
        result, _ = _run(WriteOperation(verb="create_node", type_slug=_TYPE, payload={"name": "fine"}, collected=W1))
        assert result.warnings == []


@pytest.mark.django_db
class TestLateOlderRead:
    @AC[7]
    def test_an_earlier_window_arriving_second_moves_the_pair_and_warns(self) -> None:
        entity_id = _create("steady", W2)
        seen = Entity.objects.get(pk=entity_id).last_observed_at

        result, batch = _reobserve(entity_id, "steady", EARLIER)

        row = Entity.objects.get(pk=entity_id)
        assert (row.collected_start, row.collected_end) == (EARLIER.start, EARLIER.end)
        assert row.last_observed_at > seen and row.last_observed_batch_id == batch
        event = _event(entity_id, batch)
        assert (event.collected_start, event.collected_end) == (EARLIER.start, EARLIER.end)
        reported = _warned(result, OLDER_READ)
        assert len(reported) == 1
        for named in (
            str(entity_id),
            "2026-11-20T09:00:00",
            "2026-11-20T09:05:00",
            "2026-11-20T11:00:00",
            "2026-11-20T11:05:00",
        ):
            assert named in reported[0], (named, reported[0])

    @AC[7]
    def test_an_older_read_that_changes_the_object_moves_the_pair_with_the_values(self) -> None:
        entity_id = _create("newer value", W2)
        result, _ = _run(
            WriteOperation(verb="patch_node", target=entity_id, payload={"name": "older value"}, collected=EARLIER)
        )
        assert result.state == WRITE_CHANGED
        assert _pair(entity_id) == (EARLIER.start, EARLIER.end)
        assert len(_warned(result, OLDER_READ)) == 1
        # What the row held before is read from history, and its window from the earlier event.
        assert list(
            PgNode.history.filter(entity_id=entity_id).order_by("history_date").values_list("name", flat=True)
        ) == [
            "newer value",
            "older value",
        ]

    @AC[7]
    def test_a_later_window_does_not_warn(self) -> None:
        entity_id = _create("steady", W1)
        result, _ = _reobserve(entity_id, "steady", W2)
        assert _warned(result, OLDER_READ) == []


# ---------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSurfaces:
    def test_the_spine_pair_is_on_the_canonical_surface_after_event_time(self) -> None:
        names = Entity.SPINE_FIELD_NAMES
        assert names[names.index("event_precision") + 1 : names.index("event_precision") + 3] == PAIR
        surface = build_spine_surface(Entity.objects.get(pk=_create("surfaced", W1)))
        assert isinstance(surface["collected_start"], str) and isinstance(surface["collected_end"], str)
        assert (
            datetime.fromisoformat(surface["collected_start"]),
            datetime.fromisoformat(surface["collected_end"]),
        ) == (
            W1.start,
            W1.end,
        )

    def test_the_spine_pair_is_not_indexed(self) -> None:
        fields = {field.name: field for field in Entity._meta.fields}
        for name in PAIR:
            assert getattr(fields[name], "db_index") is False  # noqa: B009
        indexed = {field for index in Entity._meta.indexes for field in index.fields}
        assert not indexed & set(PAIR)

    @pytest.mark.parametrize("field", PAIR)
    def test_an_envelope_that_supplies_either_is_refused(self, field: str) -> None:
        entity_id = str(uuid.uuid4())
        node = {
            "entity": {
                "entity_id": entity_id,
                "entity_type": "panel",
                "name": "p-smuggle",
                "dimensions": {"tap.graph": "web"},
                field: "2026-11-20T10:00:00Z",
            },
            "node": {"name": "p-smuggle", "slug": "p-smuggle", "description": "", "view": "tap_web/panel_error.html"},
        }
        result = grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[node])]))
        assert not result.success
        assert any(field in error.message for error in result.errors), [e.message for e in result.errors]
        assert not Entity.objects.filter(pk=entity_id).exists()

    def test_an_import_states_no_window_yet_and_leaves_the_pair_empty(self) -> None:
        # The GRIFT document form is not built (rule 2): an import states none, so a row it names
        # has an empty pair, whatever it carried before.
        entity_id = str(uuid.uuid4())
        node = {
            "entity": {
                "entity_id": entity_id,
                "entity_type": "panel",
                "name": "p-in",
                "dimensions": {"tap.graph": "web"},
            },
            "node": {"name": "p-in", "slug": "p-in", "description": "", "view": "tap_web/panel_error.html"},
        }
        assert grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[node])])).success
        assert _pair(entity_id) == (None, None)


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonReadsTheSpinePair:
    def test_gryphon_filters_on_the_spine_pair(self) -> None:
        from tap_grid.gryphon import execute_gryphon_raw

        early, late, unstated = _create("early", W1), _create("late", W2), _create("unstated")
        rows = execute_gryphon_raw(
            "MATCH (n:grid_fixtures__node) WHERE n.collected_end < $cutoff "
            "RETURN n.entity_id AS id, n.collected_start AS began",
            {"cutoff": _utc(2026, 11, 20, 10, 30).isoformat()},
        )["rows"]
        assert {str(row["id"]) for row in rows} == {str(early)}
        assert {str(late), str(unstated)}.isdisjoint({str(row["id"]) for row in rows})
