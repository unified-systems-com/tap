"""History rows carry the event time (req-grid-history-event-time, spec-grid-history.md).

Issue# 1374 - tap. Rows use the neutral grid_fixtures ``PgNode``, with the declaration each test
needs set on the class as the event-time suite does (the fixture plugin declares none), and the
unconstrained ``PG_LINKS`` edge for the model-version migration.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from django.apps import apps
from django.db import connection, models, transaction
from django.db.migrations.state import ProjectState
from tap_plugin.grid_fixtures.models.pg_node import PgNode

from tap_grid import event_time, version_links, version_migration
from tap_grid import model_version as mv
from tap_grid.caller_context import CallerContext
from tap_grid.event_time import NO_EVENT_TIME, SPINE_EVENT_FIELDS, Moment, overlapping
from tap_grid.models import BASE_HISTORY, BaseModel, Edge, Entity
from tap_grid.registry import get_model_class, list_entity_types
from tap_grid.services import create_edge, create_node, delete_node, patch_node
from tap_grid.spine_copies import fill_history_row, stash_history_copies
from tap_grid.version_links import Step

pytestmark = pytest.mark.django_db

AC = {n: pytest.mark.spec(f"req-grid-history-event-time-{n}") for n in range(1, 10)}
NODE = "grid_fixtures__node"
LINK = "PG_LINKS__grid_fixtures"


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)  # type: ignore[arg-type, misc]


def _ctx() -> CallerContext:
    return CallerContext(batch_id=str(uuid.uuid7()))


def _create(name: str, observed_at: str | None = None) -> Any:
    payload: dict[str, Any] = {"name": name}
    if observed_at is not None:
        payload["observed_at"] = observed_at
    made = create_node(NODE, payload, caller_context=_ctx())
    assert made.success, made.errors
    return made.entity_id


def _spine(entity_id: Any) -> tuple[Any, ...]:
    return tuple(Entity.objects.filter(pk=entity_id).values_list(*SPINE_EVENT_FIELDS).get())


def _rows(model: type[models.Model], entity_id: Any) -> list[tuple[Any, ...]]:
    """Each history row's event time, oldest first."""
    history = cast(Any, model).history
    return [
        tuple(row)
        for row in history.filter(entity_id=entity_id)
        .order_by("history_date", "history_id")
        .values_list(*SPINE_EVENT_FIELDS)
    ]


@pytest.fixture
def moment_on_observed_at(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(PgNode, "EVENT_TIME", Moment("observed_at", "occurred"), raising=False)


def _history_models() -> list[tuple[type[BaseModel], type[models.Model]]]:
    found = []
    for slug in list_entity_types():
        model = get_model_class(slug)
        if not isinstance(model, type) or not issubclass(model, BaseModel) or model._meta.abstract:
            continue
        history = getattr(model, "history", None)
        if history is not None:
            found.append((model, history.model))
    return found


# ---------------------------------------------------------------------------
# Rules 1 to 5: what each write records
# ---------------------------------------------------------------------------


class TestStamping:
    @AC[1]
    def test_a_create_records_the_event_time_it_derived(self, moment_on_observed_at: None) -> None:
        entity_id = _create("created", "2026-12-01T18:30:00Z")
        assert _spine(entity_id) == (_utc(2026, 12, 1, 18, 30), _utc(2026, 12, 1, 18, 30), "second")
        assert _rows(PgNode, entity_id) == [_spine(entity_id)]

    @AC[1]
    def test_a_create_without_a_given_id_records_it_too(self, moment_on_observed_at: None) -> None:
        """``BaseModel.save``'s own create path, where the pipeline did not create the entity row first."""
        row = PgNode(name="direct", observed_at=_utc(2026, 3, 4, 5, 6, 7))
        row.save()
        assert _rows(PgNode, row.entity_id) == [(_utc(2026, 3, 4, 5, 6, 7), _utc(2026, 3, 4, 5, 6, 7), "second")]

    @AC[2]
    def test_a_changed_event_time_is_recorded_on_the_new_row_and_the_old_row_keeps_the_old(
        self, moment_on_observed_at: None
    ) -> None:
        entity_id = _create("moved", "2026-12-01T18:30:00Z")
        old = _spine(entity_id)
        patched = patch_node(entity_id, {"observed_at": "2026-12-02T08:00:00Z"}, caller_context=_ctx())
        assert patched.success, patched.errors
        new = _spine(entity_id)
        assert new == (_utc(2026, 12, 2, 8), _utc(2026, 12, 2, 8), "second") != old
        assert _rows(PgNode, entity_id) == [old, new]

    @AC[2]
    def test_an_event_time_taken_away_is_recorded_empty(self, moment_on_observed_at: None) -> None:
        entity_id = _create("taken-away", "2026-12-01T18:30:00Z")
        old = _spine(entity_id)
        assert patch_node(entity_id, {"observed_at": None}, caller_context=_ctx()).success
        assert _rows(PgNode, entity_id) == [old, (None, None, None)]

    @AC[3]
    def test_an_update_of_another_field_carries_the_stored_event_time(self, moment_on_observed_at: None) -> None:
        entity_id = _create("renamed", "2026-12-01T18:30:00Z")
        stored = _spine(entity_id)
        assert patch_node(entity_id, {"description": "changed"}, caller_context=_ctx()).success
        assert _rows(PgNode, entity_id) == [stored, stored]

    @AC[3]
    def test_a_partial_save_that_stores_no_declared_field_carries_the_stored_event_time(
        self, moment_on_observed_at: None
    ) -> None:
        entity_id = _create("partial", "2026-12-01T18:30:00Z")
        stored = _spine(entity_id)
        row = PgNode.objects.get(entity_id=entity_id)
        # In memory only: the save below does not store it, so the spine keeps the stored time.
        row.observed_at = _utc(1999, 1, 1)
        row.description = "partial"
        row.save(update_fields=["description"])
        assert _spine(entity_id) == stored
        assert _rows(PgNode, entity_id) == [stored, stored]

    @AC[3]
    def test_an_identical_rewrite_adds_no_row(self, moment_on_observed_at: None) -> None:
        entity_id = _create("idle", "2026-12-01T18:30:00Z")
        again = patch_node(entity_id, {"observed_at": "2026-12-01T18:30:00Z"}, caller_context=_ctx())
        assert again.success, again.errors
        assert len(_rows(PgNode, entity_id)) == 1

    @AC[4]
    def test_a_type_with_no_event_time_records_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(PgNode, "EVENT_TIME", NO_EVENT_TIME, raising=False)
        entity_id = _create("timeless", "2026-12-01T18:30:00Z")
        assert patch_node(entity_id, {"description": "still timeless"}, caller_context=_ctx()).success
        assert _rows(PgNode, entity_id) == [(None, None, None), (None, None, None)]

    @AC[5]
    def test_a_retirement_records_the_retiring_rows_event_time(self, moment_on_observed_at: None) -> None:
        entity_id = _create("retired", "2026-12-01T18:30:00Z")
        other = _create("kept")
        edge = create_edge(Entity.objects.get(pk=entity_id), Entity.objects.get(pk=other), LINK, {})
        stored = _spine(entity_id)
        result = delete_node(entity_id, reason="scope_withdrawn")
        assert result.success, result.errors
        rows = _rows(PgNode, entity_id)
        assert len(rows) == 2 and rows[-1] == stored
        # The edge the retirement ends carries its own event time (none: the link declares none).
        assert _rows(Edge, edge.entity_id)[-1] == _spine(edge.entity_id) == (None, None, None)


# ---------------------------------------------------------------------------
# Rules 3 and 4: no stash, and a history model without the columns
# ---------------------------------------------------------------------------


class TestFallback:
    @AC[6]
    def test_a_row_written_without_a_stash_reads_the_entity_row(self, moment_on_observed_at: None) -> None:
        entity_id = _create("fallback", "2026-12-01T18:30:00Z")
        row = PgNode.objects.get(entity_id=entity_id)
        assert getattr(row, "_spine_history", None) is None
        BASE_HISTORY.create_historical_record(row, "~")
        assert _rows(PgNode, entity_id) == [_spine(entity_id), _spine(entity_id)]

    @AC[6]
    def test_a_history_model_without_the_columns_is_filled_without_error(self) -> None:
        instance = SimpleNamespace(entity_id=None)
        history = SimpleNamespace(spine_deleted_at=None, spine_dimensions=None)
        stamped = {"event_start": _utc(2026, 1, 1), "event_end": _utc(2026, 1, 2), "event_precision": "day"}
        with stash_history_copies(instance, None, {"k": 1}, "b", event_time=stamped):
            fill_history_row(None, instance=instance, history_instance=history)
        assert history.spine_dimensions == {"k": 1}
        assert not any(hasattr(history, name) for name in SPINE_EVENT_FIELDS)


# ---------------------------------------------------------------------------
# Rule 6: history-only, declared as on Entity
# ---------------------------------------------------------------------------


class TestColumns:
    @AC[7]
    def test_every_history_model_has_them_as_entity_declares_them_and_no_typed_model_does(self) -> None:
        def shape(field: Any) -> tuple[Any, ...]:
            return (type(field), field.null, field.blank, field.editable, field.max_length, field.choices)

        pairs = _history_models()
        assert any(model is Edge for model, _ in pairs)
        for model, history in pairs:
            typed = {f.name for f in model._meta.concrete_fields}
            assert not typed & set(SPINE_EVENT_FIELDS), model
            for name in SPINE_EVENT_FIELDS:
                assert shape(history._meta.get_field(name)) == shape(Entity._meta.get_field(name)), (history, name)


# ---------------------------------------------------------------------------
# Rule 7: window search over history
# ---------------------------------------------------------------------------


class TestWindowSearch:
    @AC[8]
    def test_the_overlap_test_finds_the_versions_whose_event_time_falls_in_the_window(
        self, moment_on_observed_at: None
    ) -> None:
        inside = _create("in-window", "2026-06-15T00:00:00Z")
        moved = _create("moved-out", "2026-06-20T00:00:00Z")
        assert patch_node(moved, {"observed_at": "2027-01-01T00:00:00Z"}, caller_context=_ctx()).success
        outside = _create("out-of-window", "2025-01-01T00:00:00Z")
        _create("no-time")

        window = overlapping(_utc(2026, 6, 1), _utc(2026, 7, 1))
        found = set(
            PgNode.history.filter(window, entity_id__in=[inside, moved, outside]).values_list(
                "entity_id", "event_start"
            )
        )
        # The moved node's first version had a time in the window; its current one does not.
        assert found == {(inside, _utc(2026, 6, 15)), (moved, _utc(2026, 6, 20))}

    @AC[8]
    def test_event_start_is_indexed_on_every_history_table_and_a_window_query_can_use_it(self) -> None:
        with connection.cursor() as cursor:
            for _model, history in _history_models():
                table = history._meta.db_table
                constraints = connection.introspection.get_constraints(cursor, table)
                assert any(c["index"] and c["columns"] == ["event_start"] for c in constraints.values()), table

        query = PgNode.history.filter(overlapping(_utc(2026, 6, 1), _utc(2026, 7, 1))).values("history_id")
        sql, params = query.query.sql_with_params()
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_seqscan = off")
            cursor.execute(f"EXPLAIN {sql}", params)  # nosemgrep  # nosec B608 - the ORM's own statement
            plan = "\n".join(line for (line,) in cursor.fetchall())
        names = {
            name
            for name, c in connection.introspection.get_constraints(
                connection.cursor(), PgNode.history.model._meta.db_table
            ).items()
            if c["index"] and c["columns"] == ["event_start"]
        }
        assert any(name in plan for name in names), plan


# ---------------------------------------------------------------------------
# Rule 5: a model-version migration's history row
# ---------------------------------------------------------------------------


class TestVersionMigration:
    @AC[9]
    def test_the_history_row_a_version_migration_writes_holds_the_event_time_after_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tap_grid.tests.test_version_migration import _catalogue

        monkeypatch.setitem(event_time._edge_event_time, LINK, Moment("at", "occurred"))
        monkeypatch.setitem(mv._edge_versions, LINK, 2)
        monkeypatch.setattr(version_links, "_declared", dict(version_links._declared))
        _catalogue(LINK)
        _catalogue(NODE)
        version_links.declare(LINK, {2: Step(lambda r: {**r, "at": "2026-12-01T00:00:00Z"})})
        made = create_edge(Entity.objects.get(pk=_create("vm-a")), Entity.objects.get(pk=_create("vm-b")), LINK, {})
        assert _spine(made.entity_id) == (None, None, None)

        report = version_migration.apply_version(ProjectState.from_apps(apps).apps, None, LINK, to_version=2)

        assert report.changed == 1 and report.history_rows == 1
        assert _spine(made.entity_id) == (_utc(2026, 12, 1), _utc(2026, 12, 1), "second")
        assert _rows(Edge, made.entity_id) == [(None, None, None), _spine(made.entity_id)]
