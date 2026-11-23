"""The adapter that carries a type's stored rows to its next version (tap_grid.version_migration).

``req-grid-entity-model-version`` rules 18 and 27 to 33. The migrations here are real
``django.db.migrations.Migration`` objects applied through Django's own machinery
(``Migration.apply`` with a schema editor) inside the test's transaction: the table starts in
its version-1 shape, the operations add, convert and remove columns, and the adapter runs as a
``RunPython`` between them on the historical models of that point, as it does in a plugin.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Any, ClassVar

import pytest
from django.apps import apps
from django.db import connection, migrations, models
from django.db.migrations.state import ProjectState

from tap_auth import sync
from tap_grid import model_definition as definition
from tap_grid import model_version as mv
from tap_grid import version_links, version_migration
from tap_grid.caller_context import CallerContext
from tap_grid.models import BaseModel, BatchEvent, BatchEventType, Edge, Entity, EntityType
from tap_grid.registry import _entity_model_registry
from tap_grid.service_types import WriteOperation, WriteResult
from tap_grid.services import create_edge, create_node, write_batch
from tap_grid.version_links import RecordRefused, Step

pytestmark = pytest.mark.django_db

RID = "req-grid-entity-model-version"
AC = {n: pytest.mark.spec(f"{RID}-{n}") for n in (14, 17, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32)}

WIDGET = "vm_widget"
PLAIN = "vm_plain"
APP = "tap_grid"


def _forget(*names: str) -> None:
    for name in names:
        apps.all_models[APP].pop(name.lower(), None)
    apps.clear_cache()


@pytest.fixture(autouse=True)
def _process_state() -> Iterator[None]:
    """What registration and link discovery keep per process, put back after each test."""
    pending, edge_versions, owed = dict(mv._pending), dict(mv._edge_versions), mv._start_incomplete
    declared = dict(version_links._declared)
    mv._pending.clear()
    mv._start_incomplete = False
    sync.sync_auth()
    try:
        yield
    finally:
        mv._start_incomplete = owed
        mv._pending.clear()
        mv._pending.update(pending)
        mv._edge_versions.clear()
        mv._edge_versions.update(edge_versions)
        version_links._declared.clear()
        version_links._declared.update(declared)


@pytest.fixture
def widget() -> Iterator[Any]:
    """A node type whose installed class is at version 2: ``label`` became ``title`` and ``size``
    became a whole number. Registered for this test only."""
    saved = _entity_model_registry.all()
    try:

        class VmWidget(BaseModel):
            ENTITY_TYPE: ClassVar[str] = WIDGET
            ENTITY_NAME: ClassVar[str] = "Version Migration Widget"
            NATURAL_KEY: ClassVar[tuple[str, ...]] = ("name",)
            MODEL_VERSION: ClassVar[int] = 2
            FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
                "name": {"type": "string", "minLength": 1},
                "title": {"type": ["string", "null"]},
                "size": {"type": ["integer", "null"]},
            }
            CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

            name = models.CharField(max_length=255, blank=True, default="")
            title = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001
            size = models.IntegerField(null=True, blank=True, default=None)

            class Meta(BaseModel.Meta):
                app_label = APP
                db_table = "tap_grid_vm_widget"

            def get_name(self) -> str:
                return self.title or self.name

        yield VmWidget
    finally:
        _forget("VmWidget", "HistoricalVmWidget")
        _entity_model_registry._reset_for_testing(saved)


@pytest.fixture
def plain() -> Iterator[Any]:
    """A node type that keeps no history, at version 2: ``note`` is upper-cased."""
    saved = _entity_model_registry.all()
    try:

        class VmPlain(BaseModel):
            ENTITY_TYPE: ClassVar[str] = PLAIN
            NATURAL_KEY: ClassVar[tuple[str, ...]] = ("name",)
            MODEL_VERSION: ClassVar[int] = 2
            TRACK_HISTORY: ClassVar[bool] = False
            FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
                "name": {"type": "string", "minLength": 1},
                "note": {"type": ["string", "null"]},
            }
            CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

            name = models.CharField(max_length=255, blank=True, default="")
            note = models.CharField(max_length=64, null=True, blank=True, default=None)  # noqa: DJ001

            class Meta(BaseModel.Meta):
                app_label = APP
                db_table = "tap_grid_vm_plain"

            def get_name(self) -> str:
                return self.name

        yield VmPlain
    finally:
        _forget("VmPlain")
        _entity_model_registry._reset_for_testing(saved)


def _state_at_version_1(widget_model: Any) -> ProjectState:
    """The project state with the widget in its version-1 shape: ``label`` and a text ``size``."""
    state = ProjectState.from_apps(apps)
    backwards = [
        migrations.RemoveField("vmwidget", "title"),
        migrations.RemoveField("historicalvmwidget", "title"),
        migrations.AddField("vmwidget", "label", models.CharField(max_length=64, null=True)),
        migrations.AddField("historicalvmwidget", "label", models.CharField(max_length=64, null=True)),
        migrations.AlterField("vmwidget", "size", models.CharField(max_length=20, null=True)),
        migrations.AlterField("historicalvmwidget", "size", models.CharField(max_length=20, null=True)),
    ]
    for operation in backwards:
        operation.state_forwards(APP, state)
    return state


def _create_tables(state: ProjectState, *model_names: str) -> None:
    with connection.schema_editor() as editor:
        for name in model_names:
            editor.create_model(state.apps.get_model(APP, name))


def _apply(state: ProjectState, operations: list[Any]) -> ProjectState:
    """Apply ``operations`` as one migration, the way ``migrate`` does."""
    migration = type("Migration", (migrations.Migration,), {"operations": operations, "atomic": True})("vm", APP)
    # The rows a test wrote sit in this same transaction with their foreign-key checks deferred;
    # a real migration starts with none waiting.
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
    with connection.schema_editor(atomic=True) as editor:
        applied: ProjectState = migration.apply(state.clone(), editor)
        return applied


def _adapter(type_slug: str, to_version: int, seen: list[Any] | None = None) -> Any:
    def forwards(historical: Any, editor: Any) -> None:
        report = version_migration.apply_version(historical, editor, type_slug, to_version=to_version)
        if seen is not None:
            seen.append(report)

    return migrations.RunPython(forwards, migrations.RunPython.noop)


def _to_whole(value: Any) -> Any:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise RecordRefused(f"size {value!r} is not a whole number") from error


def _widget_step(record: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in record.items() if k not in {"label", "size"}}
    if "label" in record:
        out["title"] = record["label"]
    if "size" in record:
        out["size"] = _to_whole(record["size"])
    return out


WIDGET_STEP = Step(_widget_step, renames={"title": "label"}, may_refuse="a size that is not a whole number")


def _widget_operations(seen: list[Any] | None = None) -> list[Any]:
    """The migration a plugin ships with version 2 of the widget."""
    return [
        migrations.AddField("vmwidget", "title", models.CharField(max_length=64, null=True)),
        migrations.AddField("historicalvmwidget", "title", models.CharField(max_length=64, null=True)),
        _adapter(WIDGET, 2, seen),
        migrations.RemoveField("vmwidget", "label"),
        migrations.RemoveField("historicalvmwidget", "label"),
        migrations.AlterField("vmwidget", "size", models.IntegerField(null=True)),
        migrations.AlterField("historicalvmwidget", "size", models.IntegerField(null=True)),
    ]


def _catalogue(type_slug: str, version: int = 1) -> None:
    with mv._writing_applied_version():
        EntityType.objects.update_or_create(slug=type_slug, defaults={"name": type_slug, "model_version": version})


def _row(state: ProjectState, model_name: str, type_slug: str, **values: Any) -> uuid.UUID:
    """One stored row in the table's current shape, with its spine row, written before versions moved."""
    flip = values.pop("flip_map", {})
    entity = Entity.objects.create(entity_type=type_slug, name=str(values.get("label") or values.get("name")))
    state.apps.get_model(APP, model_name).objects.create(entity_id=entity.pk, batch_id="", flip_map=flip, **values)
    return uuid.UUID(str(entity.pk))


@pytest.fixture
def widget_v1(widget: Any) -> ProjectState:
    """The widget's tables in their version-1 shape, catalogued at version 1, with its step declared."""
    state = _state_at_version_1(widget)
    _create_tables(state, "VmWidget", "HistoricalVmWidget")
    _catalogue(WIDGET)
    version_links.declare(WIDGET, {2: WIDGET_STEP})
    return state


# ---------------------------------------------------------------------------
# Rules 29, 30 and 33: the adapter, its batch and the applied version
# ---------------------------------------------------------------------------


class TestMigrationGoesThroughTheAdapter:
    @AC[23]
    def test_ten_rows_each_get_a_revision_a_history_row_and_a_maintenance_event(self, widget_v1: ProjectState) -> None:
        ids = [_row(widget_v1, "VmWidget", WIDGET, name=f"w{n}", label=f"L{n}", size=str(n)) for n in range(10)]
        before = {e.pk: e for e in Entity.objects.filter(pk__in=ids)}
        seen: list[Any] = []

        _apply(widget_v1, _widget_operations(seen))

        report = seen[0]
        assert (report.rows, report.changed, report.history_rows, report.applied) == (10, 10, 10, True)
        assert mv.applied_version(WIDGET) == 2
        history = widget_v1.apps.get_model(APP, "HistoricalVmWidget")
        for entity in Entity.objects.filter(pk__in=ids):
            was = before[entity.pk]
            assert entity.version == was.version + 1
            assert str(entity.last_changed_batch_id) == report.batch_id
            # No source or analyst named the object: the observation side is where it was.
            assert entity.last_observed_at == was.last_observed_at
            assert entity.last_observed_batch_id == was.last_observed_batch_id
            assert (entity.collected_start, entity.collected_end) == (was.collected_start, was.collected_end)
            events = BatchEvent.objects.filter(entity_id=entity.pk)
            assert [e.event_type for e in events] == [BatchEventType.MAINTENANCE]
            assert str(events[0].batch.entity_id) == report.batch_id
            assert events[0].metadata["fields"] == ["size", "title"]
        assert history._default_manager.count() == 10

    @AC[23]
    def test_an_unchanged_row_is_not_written(self, widget_v1: ProjectState) -> None:
        version_links.declare(WIDGET, {2: Step(lambda record: dict(record))})
        entity_id = _row(widget_v1, "VmWidget", WIDGET, name="same", label=None, size=None)
        before = Entity.objects.get(pk=entity_id)
        seen: list[Any] = []

        _apply(widget_v1, [_adapter(WIDGET, 2, seen)])

        after = Entity.objects.get(pk=entity_id)
        assert (seen[0].rows, seen[0].changed, seen[0].batch_id) == (1, 0, None)
        assert (after.version, after.updated_at) == (before.version, before.updated_at)
        assert not BatchEvent.objects.filter(entity_id=entity_id).exists()
        assert mv.applied_version(WIDGET) == 2

    @AC[14]
    def test_the_stored_rows_equal_the_records_the_step_returns(self, widget: Any, widget_v1: ProjectState) -> None:
        """What an export of version 1 gives the step, and what the migrated table then holds."""
        version_1: list[dict[str, Any]] = [
            {"name": "a", "label": "Alpha", "size": "7"},
            {"name": "b", "label": None, "size": None},
            {"name": "c", "label": "Gamma", "size": "12"},
        ]
        for record in version_1:
            _row(widget_v1, "VmWidget", WIDGET, **record)

        _apply(widget_v1, _widget_operations())

        upgraded = sorted((_widget_step(dict(r)) for r in version_1), key=lambda r: r["name"])
        stored = sorted(widget.all_objects.values("name", "title", "size"), key=lambda r: r["name"])
        assert stored == upgraded

    @AC[23]
    def test_the_spine_values_the_class_derives_follow_the_new_fields(self, widget_v1: ProjectState) -> None:
        entity_id = _row(widget_v1, "VmWidget", WIDGET, name="n", label="Shown", size="1")
        Entity.objects.filter(pk=entity_id).update(name="stale")

        _apply(widget_v1, _widget_operations())

        entity = Entity.objects.get(pk=entity_id)
        assert entity.name == "Shown"
        # The stored key is brought in step for the type by its own catch-up.
        assert getattr(entity, "natural" + "_key") is not None

    def test_a_refused_record_changes_nothing(self, widget_v1: ProjectState) -> None:
        good = _row(widget_v1, "VmWidget", WIDGET, name="good", label="G", size="3")
        bad = _row(widget_v1, "VmWidget", WIDGET, name="bad", label="B", size="three")
        before = {e.pk: e.version for e in Entity.objects.filter(pk__in=[good, bad])}

        from django.db import transaction

        with pytest.raises(version_migration.VersionMigrationRefused) as refused, transaction.atomic():
            _apply(widget_v1, _widget_operations()[:3])

        assert str(bad) in str(refused.value) and "not a whole number" in str(refused.value)
        assert {e.pk: e.version for e in Entity.objects.filter(pk__in=[good, bad])} == before
        assert mv.applied_version(WIDGET) == 1
        assert not BatchEvent.objects.filter(entity_id__in=[good, bad]).exists()

    def test_a_failure_later_in_the_migration_takes_the_adapter_s_work_with_it(self, widget_v1: ProjectState) -> None:
        """The forced mid-way failure: the adapter completes, a later operation fails, all of it rolls back."""
        from django.db import transaction

        entity_id = _row(widget_v1, "VmWidget", WIDGET, name="n", label="L", size="4")
        before = Entity.objects.get(pk=entity_id)

        def fail(historical: Any, editor: Any) -> None:
            raise RuntimeError("the operation after the adapter failed")

        with pytest.raises(RuntimeError), transaction.atomic():
            _apply(widget_v1, [*_widget_operations()[:3], migrations.RunPython(fail)])

        after = Entity.objects.get(pk=entity_id)
        assert after.version == before.version
        assert mv.applied_version(WIDGET) == 1
        assert not BatchEvent.objects.filter(entity_id=entity_id).exists()
        rows = widget_v1.apps.get_model(APP, "VmWidget").objects.filter(pk__isnull=False)
        assert [r.label for r in rows] == ["L"]

    def test_the_adapter_is_refused_out_of_order_and_does_nothing_when_run_again(self, widget_v1: ProjectState) -> None:
        _row(widget_v1, "VmWidget", WIDGET, name="n", label="L", size="4")
        with pytest.raises(version_migration.VersionMigrationRefused, match="declared at version 2"):
            version_migration.apply_version(widget_v1.apps, None, WIDGET, to_version=3)
        seen: list[Any] = []
        state = _apply(widget_v1, _widget_operations(seen))
        again = version_migration.apply_version(state.apps, None, WIDGET, to_version=2)
        assert (again.applied, again.changed) == (False, 0) and "already at version 2" in again.note

    def test_a_declared_break_has_no_step_to_carry_rows(self, widget_v1: ProjectState) -> None:
        version_links.declare(WIDGET, {2: version_links.Break("the size cannot be carried")})
        _row(widget_v1, "VmWidget", WIDGET, name="n", label="L", size="4")
        with pytest.raises(version_migration.VersionMigrationRefused, match="declared break"):
            version_migration.apply_version(widget_v1.apps, None, WIDGET, to_version=2)
        assert mv.applied_version(WIDGET) == 1

    def test_a_type_the_grid_has_never_held_is_left_for_its_first_registration(self, widget_v1: ProjectState) -> None:
        EntityType.objects.filter(slug=WIDGET).delete()
        report = version_migration.apply_version(widget_v1.apps, None, WIDGET, to_version=2)
        assert not report.applied and mv.applied_version(WIDGET) is None


# ---------------------------------------------------------------------------
# Rule 30: retired rows, and a type with no history
# ---------------------------------------------------------------------------


class TestEveryRowOfTheType:
    @AC[29]
    def test_live_and_retired_rows_both_move_and_a_retired_row_stays_retired(
        self, widget: Any, widget_v1: ProjectState
    ) -> None:
        from django.utils import timezone

        live = _row(widget_v1, "VmWidget", WIDGET, name="live", label="L", size="1")
        retired = _row(widget_v1, "VmWidget", WIDGET, name="gone", label="G", size="2")
        when = timezone.now()
        Entity.objects.filter(pk=retired).update(deleted_at=when)

        _apply(widget_v1, _widget_operations())

        assert mv.applied_version(WIDGET) == 2
        assert Entity.objects.get(pk=retired).deleted_at == when
        assert Entity.objects.get(pk=live).deleted_at is None
        rows = {row.name: row for row in widget.all_objects.all()}
        assert (rows["gone"].title, rows["gone"].size) == ("G", 2)
        # A restore finds a row the installed class validates.
        rows["gone"].full_clean(exclude=["entity"])

    @AC[31]
    def test_a_type_without_history_moves_its_revision_and_records_its_event(self, plain: Any) -> None:
        state = ProjectState.from_apps(apps)
        _create_tables(state, "VmPlain")
        _catalogue(PLAIN)
        version_links.declare(
            PLAIN, {2: Step(lambda r: {**r, "note": r["note"].upper() if r.get("note") else r.get("note")})}
        )
        entity_id = _row(state, "VmPlain", PLAIN, name="p", note="quiet")
        before = Entity.objects.get(pk=entity_id)
        seen: list[Any] = []

        _apply(state, [_adapter(PLAIN, 2, seen)])

        assert not hasattr(plain, "history")
        assert (seen[0].changed, seen[0].history_rows) == (1, 0)
        assert Entity.objects.get(pk=entity_id).version == before.version + 1
        assert [e.event_type for e in BatchEvent.objects.filter(entity_id=entity_id)] == [BatchEventType.MAINTENANCE]
        assert plain.all_objects.get(pk=state.apps.get_model(APP, "VmPlain").objects.get().pk).note == "QUIET"
        with pytest.raises(LookupError):
            state.apps.get_model(APP, "HistoricalVmPlain")


# ---------------------------------------------------------------------------
# Rule 31: FLIP stays with the source
# ---------------------------------------------------------------------------


class TestFlipStaysWithTheSource:
    @AC[24]
    @AC[32]
    def test_a_renamed_field_s_entry_moves_and_no_entry_names_the_migration(self, widget_v1: ProjectState) -> None:
        source = str(uuid.uuid7())
        entity_id = _row(
            widget_v1, "VmWidget", WIDGET, name="n", label="L", size="5", flip_map={"label": source, "size": source}
        )
        seen: list[Any] = []

        state = _apply(widget_v1, _widget_operations(seen))

        row = state.apps.get_model(APP, "VmWidget").objects.get(entity_id=entity_id)
        # `title` is `label` renamed; `size` kept its name though the step rewrote its value.
        assert row.flip_map == {"title": source, "size": source}
        assert seen[0].batch_id not in row.flip_map.values()

    @AC[32]
    def test_a_declared_rename_passes_the_guard_with_nothing_dropped(self, widget: Any) -> None:
        before = {
            "fields": {"name": {"type": "CharField", "null": False}, "label": {"type": "CharField", "null": True}}
        }
        after = {"fields": {"name": {"type": "CharField", "null": False}, "title": {"type": "CharField", "null": True}}}
        step = Step(lambda r: r, renames={"title": "label"})
        assert definition._node_step_problems("widget", "version 1 to 2", before, after, step) == []
        assert step.drops == ()

    def test_the_declaration_decides_and_the_values_do_not(self) -> None:
        step = Step(lambda r: r, renames={"title": "label"}, derived={"short": "body", "long": "body"}, drops=("old",))
        flip = {"label": "b1", "body": "b2", "old": "b3", "kept": "b4"}
        assert version_migration._carry_flip(flip, step) == {
            "title": "b1",
            "body": "b2",
            "short": "b2",
            "long": "b2",
            "kept": "b4",
        }


# ---------------------------------------------------------------------------
# Rule 27: history
# ---------------------------------------------------------------------------


def _history_row(state: ProjectState, entity_id: uuid.UUID, **values: Any) -> None:
    from django.utils import timezone

    row_id = state.apps.get_model(APP, "VmWidget").objects.get(entity_id=entity_id).pk
    state.apps.get_model(APP, "HistoricalVmWidget").objects.create(
        id=row_id,
        entity_id=entity_id,
        batch_id="",
        flip_map={},
        history_date=timezone.now(),
        history_type="~",
        **values,
    )


def _history_values(state: ProjectState, column: str) -> list[Any]:
    history = state.apps.get_model(APP, "HistoricalVmWidget")
    return list(history._default_manager.order_by("history_id").values_list(column, flat=True))


class TestHistory:
    @AC[17]
    def test_history_written_before_the_change_is_left_as_written(self, widget_v1: ProjectState) -> None:
        entity_id = _row(widget_v1, "VmWidget", WIDGET, name="n", label="L", size="5")
        _history_row(widget_v1, entity_id, name="older", label="L0", size="4")
        _history_row(widget_v1, entity_id, name="old", label="L1", size="5")

        state = _apply(widget_v1, [*_widget_operations()[:3]])

        # Two rows written before, one by the adapter; the kept field's old values are untouched.
        assert _history_values(state, "name") == ["older", "old", "n"]

    @AC[27]
    def test_a_retyped_field_s_history_is_converted_with_the_column(self, widget_v1: ProjectState) -> None:
        entity_id = _row(widget_v1, "VmWidget", WIDGET, name="n", label="L", size="5")
        _history_row(widget_v1, entity_id, name="n", label="L", size="4")

        state = _apply(widget_v1, _widget_operations())

        assert _history_values(state, "size") == [4, 5]

    @AC[27]
    def test_one_history_value_that_cannot_be_converted_refuses_the_migration(self, widget_v1: ProjectState) -> None:
        entity_id = _row(widget_v1, "VmWidget", WIDGET, name="n", label="L", size="5")
        _history_row(widget_v1, entity_id, name="n", label="L", size="several")
        before = Entity.objects.get(pk=entity_id).version

        with pytest.raises(version_migration.VersionMigrationRefused) as refused:
            version_migration.apply_version(widget_v1.apps, None, WIDGET, to_version=2)

        text = str(refused.value)
        assert "1 history value(s)" in text and f"{WIDGET}.size" in text and "integer" in text
        assert Entity.objects.get(pk=entity_id).version == before
        assert mv.applied_version(WIDGET) == 1
        assert _history_values(widget_v1, "size") == ["several"]

    @AC[27]
    def test_declared_discarded_it_completes_and_leaves_that_value_empty(self, widget_v1: ProjectState) -> None:
        version_links.declare(
            WIDGET,
            {2: Step(_widget_step, renames={"title": "label"}, may_refuse="x", discards_history=("size",))},
        )
        entity_id = _row(widget_v1, "VmWidget", WIDGET, name="n", label="L", size="5")
        _history_row(widget_v1, entity_id, name="n", label="L", size="several")
        _history_row(widget_v1, entity_id, name="n", label="L", size="4")
        seen: list[Any] = []

        state = _apply(widget_v1, _widget_operations(seen))

        assert seen[0].history_discarded == {"size": 1}
        # The rows stay; the one value that could not be converted is empty.
        assert _history_values(state, "size") == [None, 4, 5]

    @AC[27]
    def test_the_guard_refuses_the_declaration_where_the_new_field_cannot_be_empty(self) -> None:
        before = {"fields": {"size": {"type": "CharField", "null": True}}}
        can_be_empty = {"fields": {"size": {"type": "IntegerField", "null": True}}}
        cannot = {"fields": {"size": {"type": "IntegerField", "null": False}}}
        step = Step(lambda r: r, may_refuse="x", discards_history=("size",))
        assert definition._node_step_problems("widget", "version 1 to 2", before, can_be_empty, step) == []
        problems = definition._node_step_problems("widget", "version 1 to 2", before, cannot, step)
        assert len(problems) == 1 and "cannot be empty" in problems[0] and "'size'" in problems[0]


# ---------------------------------------------------------------------------
# Rule 32: a tightened edge rule
# ---------------------------------------------------------------------------

_ALLOWS = [{"edges": [{"type": "VM_LINKS"}], "nodes": [{"type": "a"}, {"type": "b"}]}]


class TestTightenedEdgeRuleIsDeclared:
    @AC[25]
    def test_without_a_version_change_the_fingerprint_guard_fails(self) -> None:
        wider = {"fields": {}, "edge_rules": {"outbound": definition._unordered(_ALLOWS), "inbound": None}}
        narrower: dict[str, Any] = {"fields": {}, "edge_rules": {"outbound": [], "inbound": None}}
        first = definition.fingerprint("", 1, wider)
        state = definition.TypeState(mv.NODE, "vm_t", 1, narrower)
        entry = {"version": 1, "definition": wider, "fingerprint": first}
        problems = definition.type_problems(state, [entry])
        assert problems and "vm_t" in problems[0]

    @AC[25]
    def test_with_a_version_change_it_must_be_declared_on_the_link(self) -> None:
        wider = {"fields": {}, "edge_rules": {"outbound": definition._unordered(_ALLOWS), "inbound": None}}
        for narrower in (
            [],
            [{"edges": [{"type": "VM_LINKS"}], "nodes": [{"type": "a"}]}],
            [{"edges": [{"type": "VM_OTHER"}]}],
        ):
            after = {"fields": {}, "edge_rules": {"outbound": definition._unordered(narrower), "inbound": None}}
            undeclared = definition._node_step_problems("t", "version 1 to 2", wider, after, Step(lambda r: r))
            assert undeclared and "tightens_edges" in undeclared[0], narrower
            declared = Step(lambda r: r, tightens_edges="the type no longer links to b")
            assert definition._node_step_problems("t", "version 1 to 2", wider, after, declared) == []

    def test_a_rule_that_only_widens_needs_no_declaration(self) -> None:
        narrow = {"fields": {}, "edge_rules": {"outbound": definition._unordered(_ALLOWS), "inbound": None}}
        for wider in ([{"edges": [{"type": "VM_LINKS"}]}], [*_ALLOWS, {"edges": [{"type": "VM_MORE"}]}], None):
            after = {"fields": {}, "edge_rules": {"outbound": definition._unordered(wider), "inbound": None}}
            assert definition._node_step_problems("t", "version 1 to 2", narrow, after, Step(lambda r: r)) == []

    def test_an_edge_type_s_narrowed_endpoints_and_changed_identity_are_declared(self) -> None:
        before = definition.edge_definition(
            sources=None, targets=["a", "b"], property_schema={}, event_time=None, identity=None
        )
        after = definition.edge_definition(
            sources=["a"], targets=["a"], property_schema={}, event_time=None, identity={"by": "endpoints"}
        )
        problems = definition._edge_step_problems("E", "version 1 to 2", before, after, Step(lambda r: r))
        assert len(problems) == 3
        assert sum("endpoint rules are narrowed" in p for p in problems) == 2
        assert sum("identity declaration changes" in p for p in problems) == 1
        declared = Step(lambda r: r, tightens_edges="only a links to a", key_refused="identity was not declared")
        assert definition._edge_step_problems("E", "version 1 to 2", before, after, declared) == []


LINK = "PG_LINKS__grid_fixtures"
NODE_TYPE = "grid_fixtures__node"


def _write(op: WriteOperation) -> WriteResult:
    outcome = write_batch(
        [op],
        caller_context=CallerContext(batch_id=str(uuid.uuid7())),
        batch_name="version migration",
        batch_description="test",
    )
    return outcome.results[0]


def _node(name: str) -> uuid.UUID:
    made = create_node(NODE_TYPE, {"name": name})
    assert made.success and made.entity_id is not None, made.errors
    return uuid.UUID(str(made.entity_id))


@pytest.fixture
def link_at_version_2(monkeypatch: pytest.MonkeyPatch) -> Callable[[], None]:
    """The fixture plugin's link type raised to version 2 over rows at version 1, its step
    declaring a tightened rule. Returns the call that makes the new rules refuse every edge of it."""
    from tap_grid import constraints

    _catalogue(LINK)
    _catalogue(NODE_TYPE)
    mv.register_edge_version(LINK, 2)
    version_links.declare(LINK, {2: Step(lambda r: dict(r), tightens_edges="the type links nothing now")})

    def tighten() -> None:
        monkeypatch.setattr(constraints, "validate_edge", _refuse_link)
        mv._pending[LINK] = (2, 1)

    return tighten


def _refuse_link(from_type: str, to_type: str, edge_type: str) -> None:
    from tap_grid.exceptions import InvalidEdgeError

    if edge_type == LINK:
        raise InvalidEdgeError(f"{from_type} cannot create '{edge_type}' edge to {to_type}")


class TestViolatingEdgesRefuseTheMigration:
    @AC[26]
    @AC[28]
    def test_refused_while_a_live_edge_breaks_the_new_rules_and_completes_once_it_is_retired(
        self, link_at_version_2: Callable[[], None]
    ) -> None:
        source, target = _node("vm-a"), _node("vm-b")
        made = create_edge(Entity.objects.get(pk=source), Entity.objects.get(pk=target), LINK, {})
        edge_id = uuid.UUID(str(made.entity_id))
        before = Entity.objects.get(pk=edge_id).version
        link_at_version_2()
        state = ProjectState.from_apps(apps)

        with pytest.raises(version_migration.VersionMigrationRefused) as refused:
            version_migration.apply_version(state.apps, None, LINK, to_version=2)

        text = str(refused.value)
        assert f"1 live {LINK} edge(s) from {NODE_TYPE} to {NODE_TYPE}" in text and str(edge_id) in text
        assert mv.applied_version(LINK) == 1
        assert Entity.objects.get(pk=edge_id).version == before

        # While the versions disagree an update to that edge is refused, and retiring it by id is not.
        updated = _write(WriteOperation(verb="patch_edge", target=edge_id, payload={"properties": {}}))
        assert not updated.success and updated.errors[0].code == "model_version_pending"
        retired = _write(WriteOperation(verb="delete_edge", target=edge_id, reason="operator"))
        assert retired.success, retired.errors

        report = version_migration.apply_version(state.apps, None, LINK, to_version=2)
        assert report.applied and mv.applied_version(LINK) == 2

    @AC[26]
    def test_retired_edges_are_not_checked(self, link_at_version_2: Callable[[], None]) -> None:
        source, target = _node("vm-c"), _node("vm-d")
        made = create_edge(Entity.objects.get(pk=source), Entity.objects.get(pk=target), LINK, {})
        retired = _write(WriteOperation(verb="delete_edge", target=made.entity_id, reason="operator"))
        assert retired.success, retired.errors
        link_at_version_2()
        report = version_migration.apply_version(ProjectState.from_apps(apps).apps, None, LINK, to_version=2)
        assert report.applied

    def test_an_edge_type_s_properties_go_through_its_step(self) -> None:
        _catalogue(LINK)
        _catalogue(NODE_TYPE)
        mv.register_edge_version(LINK, 2)
        version_links.declare(LINK, {2: Step(lambda r: {**r, "weight": 1})})
        source, target = _node("vm-e"), _node("vm-f")
        made = create_edge(Entity.objects.get(pk=source), Entity.objects.get(pk=target), LINK, {})
        before = Entity.objects.get(pk=made.entity_id).version

        report = version_migration.apply_version(ProjectState.from_apps(apps).apps, None, LINK, to_version=2)

        edge = Edge.all_objects.get(entity_id=made.entity_id)
        assert report.changed == 1 and edge.properties == {"weight": 1}
        assert Entity.objects.get(pk=made.entity_id).version == before + 1
        assert Edge.history.filter(entity_id=made.entity_id).order_by("-history_date").first().properties == {
            "weight": 1
        }


# ---------------------------------------------------------------------------
# Rule 10 and rule 18: a chain through a field the class no longer has
# ---------------------------------------------------------------------------


class TestChainThroughFieldsTheClassNoLongerHas:
    @AC[30]
    def test_version_1_to_3_through_a_field_version_2_added_and_version_3_removed(
        self, plain: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Version 2 adds ``draft``; version 3 folds it into ``note`` and removes it. The installed
        class is at version 3 and has never had ``draft``; neither step imports it."""
        monkeypatch.setattr(plain, "MODEL_VERSION", 3)
        state = ProjectState.from_apps(apps)
        _create_tables(state, "VmPlain")
        _catalogue(PLAIN)

        def one_to_two(record: dict[str, Any]) -> dict[str, Any]:
            return {**record, "draft": f"draft of {record['name']}"}

        def two_to_three(record: dict[str, Any]) -> dict[str, Any]:
            out = {k: v for k, v in record.items() if k != "draft"}
            out["note"] = f"{record.get('note') or ''}|{record['draft']}"
            return out

        version_links.declare(PLAIN, {2: Step(one_to_two), 3: Step(two_to_three, drops=("draft",))})
        version_1: list[dict[str, Any]] = [{"name": "x", "note": "kept"}, {"name": "y", "note": None}]
        for record in version_1:
            _row(state, "VmPlain", PLAIN, **record)

        state = _apply(
            state,
            [migrations.AddField("vmplain", "draft", models.CharField(max_length=64, null=True)), _adapter(PLAIN, 2)],
        )
        assert mv.applied_version(PLAIN) == 2
        assert sorted(state.apps.get_model(APP, "VmPlain").objects.values_list("draft", flat=True)) == [
            "draft of x",
            "draft of y",
        ]
        _apply(state, [_adapter(PLAIN, 3), migrations.RemoveField("vmplain", "draft")])

        assert mv.applied_version(PLAIN) == 3
        through_the_steps = sorted((two_to_three(one_to_two(dict(r))) for r in version_1), key=lambda r: r["name"])
        stored = sorted(plain.all_objects.values("name", "note"), key=lambda r: r["name"])
        assert stored == through_the_steps


# ---------------------------------------------------------------------------
# What the review of the adapter found
# ---------------------------------------------------------------------------


class TestStoredKeysFollowAVersionThatChangesNoRow:
    @AC[30]
    def test_an_identity_valued_step_still_brings_the_stored_keys_in_step(self, plain: Any) -> None:
        """A version can change which fields make the key and leave every value as it was. No row
        is written and no batch is opened, and the stored keys are rebuilt all the same."""
        from tap_grid import spine_natural_key

        state = ProjectState.from_apps(apps)
        _create_tables(state, "VmPlain")
        _catalogue(PLAIN)
        version_links.declare(PLAIN, {2: Step(lambda record: dict(record), key=lambda key: dict(key))})
        entity_id = _row(state, "VmPlain", PLAIN, name="p", note="quiet")
        before = Entity.objects.get(pk=entity_id)
        # The row was written below the pipeline, so its spine key was never derived.
        assert PLAIN in spine_natural_key.check([PLAIN]).drifted
        seen: list[Any] = []

        _apply(state, [_adapter(PLAIN, 2, seen)])

        assert (seen[0].applied, seen[0].changed, seen[0].batch_id) == (True, 0, None)
        assert Entity.objects.get(pk=entity_id).version == before.version
        after = spine_natural_key.check([PLAIN])
        assert PLAIN not in after.drifted and PLAIN not in after.stale_recipes
        assert mv.applied_version(PLAIN) == 2


class TestATrackedTypeIsNeverCarriedWithoutItsHistory:
    @AC[30]
    def test_a_missing_history_model_refuses_the_migration(self, widget_v1: ProjectState) -> None:
        entity_id = _row(widget_v1, "VmWidget", WIDGET, name="n", label="L", size="4")
        before = Entity.objects.get(pk=entity_id)
        without = widget_v1.clone()
        without.remove_model(APP, "historicalvmwidget")

        with pytest.raises(version_migration.VersionMigrationRefused) as refused:
            version_migration.apply_version(without.apps, None, WIDGET, to_version=2)

        message = str(refused.value)
        assert WIDGET in message and "HistoricalVmWidget" in message and "must depend on" in message
        assert mv.applied_version(WIDGET) == 1
        assert Entity.objects.get(pk=entity_id).version == before.version
        assert not BatchEvent.objects.filter(entity_id=entity_id).exists()

    @AC[31]
    def test_a_type_that_keeps_no_history_is_not_asked_for_one(self, plain: Any) -> None:
        state = ProjectState.from_apps(apps)
        _create_tables(state, "VmPlain")
        _catalogue(PLAIN)
        version_links.declare(PLAIN, {2: Step(lambda record: dict(record))})
        _row(state, "VmPlain", PLAIN, name="p", note="quiet")
        report = version_migration.apply_version(state.apps, None, PLAIN, to_version=2)
        assert report.applied and report.history_rows == 0


class TestOneMigrationOfATypeAtATime:
    @AC[29]
    def test_the_applied_version_is_read_under_a_lock_on_the_catalog_row(self, widget_v1: ProjectState) -> None:
        from django.test.utils import CaptureQueriesContext

        _row(widget_v1, "VmWidget", WIDGET, name="n", label="L", size="4")
        with CaptureQueriesContext(connection) as queries:
            _apply(widget_v1, _widget_operations())
        catalog = [q["sql"] for q in queries if '"tap_entity_type"' in q["sql"] and q["sql"].startswith("SELECT")]
        locked = [sql for sql in catalog if "FOR UPDATE" in sql]
        assert locked, catalog
        # The lock is the read the adapter decides on: no unlocked read of the version comes first.
        versions = [sql for sql in catalog if "model_version" in sql]
        assert versions[0] in locked

    @AC[29]
    def test_a_second_run_after_the_first_finds_the_version_applied_and_runs_no_step(
        self, widget_v1: ProjectState
    ) -> None:
        calls: list[int] = []

        def counted(record: dict[str, Any]) -> dict[str, Any]:
            calls.append(1)
            return _widget_step(record)

        version_links.declare(WIDGET, {2: Step(counted, renames={"title": "label"})})
        _row(widget_v1, "VmWidget", WIDGET, name="n", label="L", size="4")
        state = _apply(widget_v1, _widget_operations())
        assert calls == [1]
        again = version_migration.apply_version(state.apps, None, WIDGET, to_version=2)
        assert calls == [1] and not again.applied

    @AC[29]
    def test_rows_the_catalog_never_recorded_are_catalogued_at_version_1_and_locked(
        self, widget_v1: ProjectState
    ) -> None:
        EntityType.objects.filter(slug=WIDGET).delete()
        _row(widget_v1, "VmWidget", WIDGET, name="n", label="L", size="4")
        seen: list[Any] = []
        _apply(widget_v1, _widget_operations(seen))
        assert (seen[0].from_version, seen[0].applied) == (1, True)
        assert mv.applied_version(WIDGET) == 2


class TestANonAtomicMigration:
    def test_the_adapter_refuses_a_migration_that_is_not_atomic(self, widget_v1: ProjectState) -> None:
        """Outside one transaction a later operation could fail after the applied version was set."""
        from types import SimpleNamespace

        editor = SimpleNamespace(connection=connection, atomic_migration=False)
        with pytest.raises(version_migration.VersionMigrationRefused, match="atomic = False"):
            version_migration.apply_version(widget_v1.apps, editor, WIDGET, to_version=2)
        assert mv.applied_version(WIDGET) in (None, 1)
