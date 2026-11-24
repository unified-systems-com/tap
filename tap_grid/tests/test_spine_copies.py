"""The spine copies on every typed row, kept by the database (req-grid-entity-spine-copies).

Service writes use the neutral grid_fixtures ``PgNode`` and the unconstrained ``PG_LINKS`` edge; the
import cases use ``tap_web`` panels, as the batch-pointer suite does. The two-writer cases run on the
real tables with two database sessions, ordered by observing one session blocked on the other
(``pg_blocking_pids``), never by a sleep.
"""

from __future__ import annotations

import contextlib
import json
import re
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar, cast

import pytest
from django.apps import apps
from django.conf import settings
from django.db import connection, models, transaction
from tap_plugin.grid_fixtures.models.pg_node import PgNode

from tap_grid import spine_copies
from tap_grid.cascade_corpus.timing import Outcome, finish, in_thread, wait_until_blocked_by
from tap_grid.dimension_map import grid_derived_update
from tap_grid.grift.exporter import ExportSelection, export_grid
from tap_grid.grift.subgraph import build_data_lane, build_spine_surface
from tap_grid.models import BaseModel, Edge, Entity
from tap_grid.registry import _entity_model_registry, get_model_class, list_entity_types
from tap_grid.services import create_edge, create_node, delete_node, patch_node
from tap_grid.tests.test_entity_batch_pointers import _import, _panel
from tap_grid.write_classification import SYSTEM_MANAGED_FIELDS
from tap_grid.write_guard import unguarded_write
from tap_web.models import Panel

AC = {n: pytest.mark.spec(f"req-grid-entity-spine-copies-{n}") for n in range(1, 18)}
COPIES = ("spine_deleted_at", "spine_dimensions")
NODE = "grid_fixtures__node"
LINK = "PG_LINKS__grid_fixtures"


def _node(name: str) -> PgNode:
    made = create_node(NODE, {"name": name})
    assert made.success, made.errors
    return cast(PgNode, PgNode.objects.get(entity_id=made.entity_id))


def _copies(model: type[models.Model], entity_id: Any) -> tuple[Any, Any]:
    return tuple(model._base_manager.filter(entity_id=entity_id).values_list(*COPIES).get())


def _spine(entity_id: Any) -> tuple[Any, Any]:
    return tuple(Entity.objects.filter(pk=entity_id).values_list("deleted_at", "dimensions").get())


def _sql(statement: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(statement, params or [])  # nosemgrep  # nosec B608 - test-owned statements
        return cursor.fetchall() if cursor.description else []


def _concrete_models() -> list[type[BaseModel]]:
    found = []
    for slug in list_entity_types():
        model = get_model_class(slug)
        if isinstance(model, type) and issubclass(model, BaseModel) and not model._meta.abstract:
            found.append(model)
    return found


# ---------------------------------------------------------------------------
# The columns
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestColumns:
    @AC[1]
    def test_every_registered_table_has_both_columns_and_no_model_declares_one(self) -> None:
        declared = {name: cast("models.Field[Any, Any]", BaseModel._meta.get_field(name)).creation_counter for name in COPIES}
        with connection.cursor() as cursor:
            for model in _concrete_models():
                columns = {c.name for c in connection.introspection.get_table_description(cursor, model._meta.db_table)}
                assert set(COPIES) <= columns, model._meta.db_table
                for name in COPIES:
                    # An inherited field keeps the base model's creation counter; a redeclared one does not.
                    field = cast("models.Field[Any, Any]", model._meta.get_field(name))
                    assert field.creation_counter == declared[name], (model, name)
        assert Edge in _concrete_models()

    def test_the_typed_batch_id_is_gone_and_history_still_names_a_batch(self) -> None:
        """Issue# 1288 - tap removed the typed column; Issue# 896 - tap asks that a history row still
        say which batch produced it: the history row's own column does."""
        for model in _concrete_models():
            assert "batch_id" not in {f.name for f in model._meta.concrete_fields}, model
            history = getattr(model, "history", None)
            if history is not None:
                assert "batch_id" in {f.name for f in history.model._meta.concrete_fields}, model


# ---------------------------------------------------------------------------
# Keeping them in step
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestInStep:
    @AC[2]
    def test_a_service_create_holds_the_entity_rows_values(self) -> None:
        node = _node("created")
        assert _copies(PgNode, node.entity_id) == _spine(node.entity_id)
        assert _copies(PgNode, node.entity_id)[1] != {}

    @AC[2]
    def test_wrong_values_supplied_at_insert_are_overruled(self) -> None:
        row = PgNode(name="forged")
        row.spine_dimensions = {"forged": {"v": "x", "src": "declared"}}
        with unguarded_write():
            row.save()
        assert _copies(PgNode, row.entity_id) == _spine(row.entity_id)

    @AC[3]
    def test_retirement_reaches_the_node_and_every_edge_it_ends(self) -> None:
        a, b = _node("a"), _node("b")
        out = create_edge(a.entity, b.entity, LINK, {"weight": 1})
        back = create_edge(b.entity, a.entity, LINK, {"weight": 2})
        assert delete_node(a.entity_id, reason="operator").success
        assert _copies(PgNode, a.entity_id)[0] is not None
        assert _copies(PgNode, a.entity_id) == _spine(a.entity_id)
        for edge in (out, back):
            assert _copies(Edge, edge.entity_id) == _spine(edge.entity_id)
            assert _copies(Edge, edge.entity_id)[0] is not None
        assert _copies(PgNode, b.entity_id) == (None, _spine(b.entity_id)[1])

    @AC[4]
    def test_an_import_that_changes_dimensions_reaches_the_typed_row(self) -> None:
        entity_id = str(uuid.uuid4())
        _import([_panel("copies-dims", entity_id)])
        before = _copies(Panel, entity_id)
        _import([_panel("copies-dims", entity_id, dimensions={})])
        assert _copies(Panel, entity_id) == _spine(entity_id)
        assert _copies(Panel, entity_id) != before

    @AC[4]
    def test_the_grids_key_level_write_of_tap_time_reaches_the_typed_row(self) -> None:
        node = _node("timed")
        update = grid_derived_update({"tap.time": "occurred"})
        assert update is not None, "the tap.time dimension is not seeded in this database"
        with unguarded_write():
            Entity.objects.filter(pk=node.entity_id).update(dimensions=update)
        assert _copies(PgNode, node.entity_id) == _spine(node.entity_id)
        assert len(_copies(PgNode, node.entity_id)[1]) == len(_spine(node.entity_id)[1])

    @AC[5]
    def test_raw_sql_on_the_entity_table_is_covered(self) -> None:
        node = _node("raw")
        _sql("UPDATE tap_entity SET deleted_at = now() WHERE id = %s", [node.entity_id])
        assert _copies(PgNode, node.entity_id) == _spine(node.entity_id)
        _sql("UPDATE tap_entity SET dimensions = '{}'::jsonb, deleted_at = NULL WHERE id = %s", [node.entity_id])
        assert _copies(PgNode, node.entity_id) == (None, {})

    @AC[5]
    def test_raw_sql_on_the_typed_table_cannot_set_a_copy(self) -> None:
        node = _node("raw-typed")
        _sql(
            f"UPDATE {PgNode._meta.db_table} SET spine_deleted_at = now(), spine_dimensions = '{{}}'::jsonb "  # noqa: S608
            "WHERE entity_id = %s",
            [node.entity_id],
        )
        assert _copies(PgNode, node.entity_id) == _spine(node.entity_id)


# ---------------------------------------------------------------------------
# No Python writer (the write guard is in test_write_guard)
# ---------------------------------------------------------------------------


_ASSIGNMENT = re.compile(r"\bspine_(deleted_at|dimensions)\b\s*=(?!=)")
_DECLARATION = re.compile(r"^\s*spine_(deleted_at|dimensions)\s*=\s*models\.")
#: Where a copy may be named on the left of an assignment: its declaration on the base model, the
#: module that sets a history row's values, the version adapter's history row, and migrations.
_ALLOWED = {"tap_grid/spine_copies.py", "tap_grid/version_migration.py"}


@AC[6]
def test_no_source_outside_the_migration_assigns_a_copy() -> None:
    root = Path(settings.BASE_DIR)
    offenders = []
    for app in ("tap", "tap_api", "tap_auth", "tap_boot", "tap_cares", "tap_files", "tap_grid", "tap_health",
                "tap_plugins", "tap_viz", "tap_web"):
        for path in (root / app).rglob("*.py"):
            relative = path.relative_to(root).as_posix()
            if "/tests/" in relative or "/migrations/" in relative or relative in _ALLOWED:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _ASSIGNMENT.search(line) and not _DECLARATION.match(line):
                    offenders.append(f"{relative}:{number}: {line.strip()}")
    assert offenders == []


# ---------------------------------------------------------------------------
# The installer reaches tables no core migration knows (a plugin's)
# ---------------------------------------------------------------------------


@pytest.fixture
def plugin_like_model() -> Iterator[type[BaseModel]]:
    """A node type registered for this test, its table created by the schema editor the way a
    plugin's migration creates it: the two columns and nothing else."""
    saved = _entity_model_registry.all()
    try:

        class CopiesPluginNode(BaseModel):
            ENTITY_TYPE: ClassVar[str] = "tap_grid__copies_plugin_node"
            NATURAL_KEY: ClassVar[tuple[str, ...]] = ("name",)
            FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {"name": {"type": "string", "minLength": 1}}
            CREATE_REQUIRED: ClassVar[list[str]] = ["name"]
            name = models.CharField(max_length=64, blank=True, default="")

            class Meta(BaseModel.Meta):
                app_label = "tap_grid"
                db_table = "tap_grid__copies_plugin_node"

            def get_name(self) -> str:
                return self.name

        with connection.schema_editor() as editor:
            editor.create_model(CopiesPluginNode)
            editor.create_model(CopiesPluginNode.history.model)
        yield CopiesPluginNode
    finally:
        apps.all_models["tap_grid"].pop("copiespluginnode", None)
        apps.all_models["tap_grid"].pop("historicalcopiespluginnode", None)
        apps.clear_cache()
        _entity_model_registry._reset_for_testing(saved)


@pytest.mark.django_db
class TestInstaller:
    @AC[7]
    def test_a_table_with_only_the_columns_gets_both_triggers_and_a_map_entry(self, plugin_like_model: Any) -> None:
        table = plugin_like_model._meta.db_table
        before = spine_copies.check()
        assert table in before.untriggered and plugin_like_model.ENTITY_TYPE in before.unmapped
        report = spine_copies.install()
        assert report.tables[plugin_like_model.ENTITY_TYPE] == table
        triggers = _sql(
            "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid WHERE c.relname = %s "
            "AND NOT t.tgisinternal",
            [table],
        )
        assert (spine_copies.PULL_TRIGGER,) in triggers
        assert _sql(f"SELECT table_name FROM {spine_copies.TYPE_TABLE} WHERE entity_type = %s",  # noqa: S608
                    [plugin_like_model.ENTITY_TYPE]) == [(table,)]
        made = create_node(plugin_like_model.ENTITY_TYPE, {"name": "plugin-row"})
        assert made.success and made.entity_id is not None, made.errors
        assert delete_node(made.entity_id).success
        assert _copies(plugin_like_model, made.entity_id) == _spine(made.entity_id)
        assert spine_copies.check().clean

    def test_a_table_without_the_columns_is_skipped_and_reported(self, plugin_like_model: Any) -> None:
        table = plugin_like_model._meta.db_table
        _sql(f"ALTER TABLE {table} DROP COLUMN spine_dimensions")
        report = spine_copies.install()
        assert plugin_like_model.ENTITY_TYPE in report.skipped
        assert "spine_dimensions" in report.skipped[plugin_like_model.ENTITY_TYPE]
        assert "makemigrations tap_grid" in report.skipped[plugin_like_model.ENTITY_TYPE]
        assert not spine_copies.check().clean

    @AC[8]
    def test_a_reversed_migration_leaves_a_table_that_still_takes_writes(self, plugin_like_model: Any) -> None:
        """A rollback past the migration that added the columns withdraws the table's trigger.

        Left in place, the pull trigger sets columns the table no longer has, and every insert and
        update of the table fails (``record "new" has no field "spine_deleted_at"``).
        """
        table = plugin_like_model._meta.db_table
        spine_copies.install()
        made = create_node(plugin_like_model.ENTITY_TYPE, {"name": "before-rollback"})
        assert made.success, made.errors
        # What reversing the plugin's migration does to its table: both columns go, the trigger stays.
        # (The insert's deferred foreign-key checks are run first: a table with pending ones cannot be altered.)
        _sql("SET CONSTRAINTS ALL IMMEDIATE")
        _sql(f"ALTER TABLE {table} DROP COLUMN spine_deleted_at, DROP COLUMN spine_dimensions")
        spine_copies.install_after_migrate(None, using="default", plan=[(object(), True)])
        triggers = _sql(
            "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid WHERE c.relname = %s "
            "AND NOT t.tgisinternal",
            [table],
        )
        assert (spine_copies.PULL_TRIGGER,) not in triggers
        mapped = _sql(
            f"SELECT table_name FROM {spine_copies.TYPE_TABLE} WHERE entity_type = %s",  # noqa: S608
            [plugin_like_model.ENTITY_TYPE],
        )
        assert mapped == []
        _sql(f"UPDATE {table} SET name = 'after-rollback' WHERE entity_id = %s", [made.entity_id])  # noqa: S608
        # The entity's push has no map entry to follow, so a retirement does not reach the table either.
        _sql("UPDATE tap_entity SET deleted_at = now() WHERE id = %s", [made.entity_id])

    @AC[17]
    def test_a_table_without_the_columns_refuses_the_boot_naming_it_and_the_remedy(
        self, plugin_like_model: Any, tmp_path: Path
    ) -> None:
        from tap_boot.orchestrator import BootError, run_boot
        from tap_boot.record import BootRecord

        table = plugin_like_model._meta.db_table
        spine_copies.assert_columns()  # a database built from the models has them everywhere
        assert spine_copies.missing_columns() == []
        _sql(f"ALTER TABLE {table} DROP COLUMN spine_dimensions")
        [gap] = spine_copies.missing_columns()
        assert (gap.table, gap.app_label, gap.columns) == (table, "tap_grid", ("spine_dimensions",))
        assert gap.entity_types == (plugin_like_model.ENTITY_TYPE,)
        with pytest.raises(spine_copies.SpineColumnsMissing) as raised:
            spine_copies.assert_columns()
        message = str(raised.value)
        for named in (table, "spine_dimensions", "makemigrations tap_grid", "0023_spine_copies", "requires_tap"):
            assert named in message, named

        record = BootRecord("test", base_dir=tmp_path)
        with pytest.raises(BootError, match=re.escape(table)) as aborted:
            run_boot(None, record=record)
        assert aborted.value.detail == {"failed_step": "spine_columns", "tables": [table]}
        data = json.loads(record.path.read_text(encoding="utf-8"))
        # Refused before the first database write: the auth phase never started.
        assert [phase["phase"] for phase in data["phases"]] == ["posture", "plugin_data", "files", "spine_columns"]
        assert data["outcome"] != "ok"

    @AC[17]
    def test_the_command_lists_a_table_without_the_columns_and_the_remedy(self, plugin_like_model: Any) -> None:
        import io

        from django.core.management import call_command
        from django.core.management.base import CommandError

        table = plugin_like_model._meta.db_table
        _sql(f"ALTER TABLE {table} DROP COLUMN spine_deleted_at")
        out = io.StringIO()
        with pytest.raises(CommandError, match="makemigrations tap_grid"):
            call_command("spine_copies", stdout=out)
        assert f"missing columns: {table} (app tap_grid) has no column spine_deleted_at" in out.getvalue()

    @AC[8]
    @AC[9]
    def test_drift_is_counted_per_table_and_repaired_without_changing_a_read(self) -> None:
        nodes = [_node(f"drift-{n}") for n in range(3)]
        assert spine_copies.check().clean
        live_before = PgNode.objects.filter(entity_id__in=[n.entity_id for n in nodes]).count()
        _sql("ALTER TABLE tap_entity DISABLE TRIGGER " + spine_copies.PUSH_TRIGGER)
        _sql("UPDATE tap_entity SET deleted_at = now() WHERE id = ANY(%s)", [[n.entity_id for n in nodes[:2]]])
        _sql("ALTER TABLE tap_entity ENABLE TRIGGER " + spine_copies.PUSH_TRIGGER)
        report = spine_copies.check()
        assert report.drifted == {PgNode._meta.db_table: 2}
        assert not report.clean
        with pytest.raises(spine_copies.SpineCopiesDrift):
            spine_copies.assert_clean()
        # Reported, not trusted: reads keep the join to Entity, so what a reader sees follows the spine.
        assert PgNode.objects.filter(entity_id__in=[n.entity_id for n in nodes]).count() == live_before - 2
        assert spine_copies.repair() == {PgNode._meta.db_table: 2}
        assert spine_copies.check().clean
        assert spine_copies.assert_clean().clean
        assert PgNode.objects.filter(entity_id__in=[n.entity_id for n in nodes]).count() == live_before - 2

    def test_a_table_that_lost_its_trigger_is_reported(self) -> None:
        _sql(f"DROP TRIGGER {spine_copies.PULL_TRIGGER} ON {PgNode._meta.db_table}")
        assert PgNode._meta.db_table in spine_copies.check().untriggered
        spine_copies.repair()
        assert spine_copies.check().clean


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHistory:
    @AC[10]
    def test_a_dimension_only_write_records_the_new_map_and_the_row_before_the_old(self) -> None:
        entity_id = str(uuid.uuid4())
        first = _import([_panel("history-dims", entity_id)])
        old = _spine(entity_id)[1]
        second = _import([_panel("history-dims", entity_id, dimensions={})])
        new = _spine(entity_id)[1]
        assert old != new
        rows = list(Panel.history.filter(entity_id=entity_id).order_by("history_date", "history_id"))
        assert [r.spine_dimensions for r in rows] == [old, new]
        assert [r.batch_id for r in rows] == [str(first), str(second)]

    @AC[15]
    def test_retiring_a_node_with_two_edges_writes_one_row_each(self) -> None:
        a, b = _node("history-a"), _node("history-b")
        out = create_edge(a.entity, b.entity, LINK, {"weight": 1})
        back = create_edge(b.entity, a.entity, LINK, {"weight": 2})
        before_node = PgNode.history.filter(entity_id=a.entity_id).count()
        before_edges = Edge.history.filter(entity_id__in=[out.entity_id, back.entity_id]).count()
        result = delete_node(a.entity_id, reason="scope_withdrawn")
        assert result.success, result.errors
        assert PgNode.history.filter(entity_id=a.entity_id).count() == before_node + 1
        assert Edge.history.filter(entity_id__in=[out.entity_id, back.entity_id]).count() == before_edges + 2
        for model, entity_id in ((PgNode, a.entity_id), (Edge, out.entity_id), (Edge, back.entity_id)):
            rows = list(model.history.filter(entity_id=entity_id).order_by("history_date", "history_id"))
            final = rows[-1]
            assert final.spine_deleted_at == _spine(entity_id)[0] is not None
            assert final.history_change_reason == "scope_withdrawn"
            assert final.batch_id == str(result.batch_id)
            assert all(row.spine_deleted_at is None for row in rows[:-1])
        # The other endpoint was not retired and gained no row.
        assert PgNode.history.filter(entity_id=b.entity_id, spine_deleted_at__isnull=False).count() == 0

    def test_a_service_patch_names_its_batch_on_the_history_row(self) -> None:
        node = _node("history-batch")
        patched = patch_node(node.entity_id, {"name": "history-batch-2"})
        assert patched.success, patched.errors
        latest = PgNode.history.filter(entity_id=node.entity_id).latest("history_date")
        assert latest.batch_id == str(patched.batch_id)
        assert latest.spine_dimensions == _spine(node.entity_id)[1]


# ---------------------------------------------------------------------------
# What the copies are kept out of
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestKeptOut:
    @AC[11]
    def test_not_a_change_and_no_flip_entry(self) -> None:
        assert set(COPIES) <= SYSTEM_MANAGED_FIELDS
        node = _node("not-a-change")
        version = Entity.objects.get(pk=node.entity_id).version
        _sql("UPDATE tap_entity SET dimensions = '{}'::jsonb WHERE id = %s", [node.entity_id])
        unchanged = patch_node(node.entity_id, {"name": "not-a-change"})
        assert unchanged.success and unchanged.state == "unchanged", unchanged
        assert Entity.objects.get(pk=node.entity_id).version == version
        assert not set(COPIES) & set(PgNode.objects.get(pk=node.pk).flip_map)

    @AC[12]
    def test_not_on_the_spine_surface_a_return_layer_or_an_export(self) -> None:
        node = _node("not-on-a-surface")
        assert not set(COPIES) & set(build_spine_surface(node.entity))
        assert not set(COPIES) & set(build_data_lane(node))
        document = export_grid(selection=ExportSelection(reachable_from=(str(node.entity_id),))).document
        assert "spine_deleted_at" not in str(document) and "spine_dimensions" not in str(document)


# ---------------------------------------------------------------------------
# Readiness for row-level security
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestNoPolicyYet:
    @AC[13]
    def test_no_typed_table_has_row_level_security_or_a_policy(self) -> None:
        tables = [model._meta.db_table for model in _concrete_models()]
        secured = _sql("SELECT relname FROM pg_class WHERE relrowsecurity AND relname = ANY(%s)", [tables])
        assert secured == []
        assert _sql("SELECT count(*) FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid WHERE c.relname = ANY(%s)",
                    [tables]) == [(0,)]

    @AC[14]
    def test_a_policy_on_the_copy_agrees_with_the_entity_table(self) -> None:
        live, gone = _node("policy-live"), _node("policy-gone")
        assert delete_node(gone.entity_id).success
        table = PgNode._meta.db_table
        role = f"tap_copies_reader_{uuid.uuid4().hex[:8]}"
        expected = Entity.objects.filter(entity_type=NODE, deleted_at__isnull=True).count()
        with transaction.atomic():
            sid = transaction.savepoint()
            # PostgreSQL will not alter a table with deferred foreign-key checks waiting.
            _sql("SET CONSTRAINTS ALL IMMEDIATE")
            _sql(f"CREATE ROLE {role} NOLOGIN")
            _sql(f"GRANT SELECT ON {table} TO {role}")
            _sql(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            _sql(f"CREATE POLICY copies_live ON {table} FOR SELECT TO {role} USING (spine_deleted_at IS NULL)")
            _sql(f"SET LOCAL ROLE {role}")
            seen = _sql(f"SELECT count(*) FROM {table}")[0][0]  # noqa: S608
            _sql("RESET ROLE")
            transaction.savepoint_rollback(sid)
        assert seen == expected
        assert live.entity_id != gone.entity_id


# ---------------------------------------------------------------------------
# Two writers on the real tables (rule 11)
# ---------------------------------------------------------------------------


def _session(statements: list[tuple[str, list[Any]]], ready: threading.Event, go: threading.Event) -> Any:
    """One database session: run ``statements`` in a transaction, signal, wait, commit."""

    def body() -> None:
        with transaction.atomic(), connection.cursor() as cursor:
            for statement, params in statements:
                cursor.execute(statement, params)
            ready.set()
            assert go.wait(20), "never released"

    return body


def _write(statements: list[tuple[str, list[Any]]]) -> Any:
    def body() -> None:
        with transaction.atomic(), connection.cursor() as cursor:
            for statement, params in statements:
                cursor.execute(statement, params)

    return body


def _blocked_on(waiter: Outcome, holder: Outcome) -> bool:
    """Wait until the waiter's backend is blocked on the holder's (True) or the waiter has finished
    without blocking (False). Returning rather than raising on the second lets a test check the rows
    first, so a missing lock shows as the stale copy it causes and not only as a missing wait."""
    try:
        wait_until_blocked_by(waiter, holder)
    except AssertionError:
        if waiter.done.is_set():
            return False
        raise
    return True


def _hold_then(holder_sql: list[tuple[str, list[Any]]], contender_sql: list[tuple[str, list[Any]]]) -> bool:
    """The holder writes and holds its transaction open; the contender writes; the holder commits once
    the contender is observed blocked on it (or has finished without blocking); the contender finishes.
    Returns whether the contender blocked."""
    ready, go = threading.Event(), threading.Event()
    holder = in_thread(_session(holder_sql, ready, go))
    assert ready.wait(20)
    contender = in_thread(_write(contender_sql))
    try:
        blocked = _blocked_on(contender[1], holder[1])
    finally:
        go.set()
    finish(holder, contender)
    return blocked


def _both_commit_in_turn(first_sql: list[tuple[str, list[Any]]], second_sql: list[tuple[str, list[Any]]]) -> None:
    """The first writes and holds; the second writes without blocking and commits; the first commits."""
    ready, go = threading.Event(), threading.Event()
    first = in_thread(_session(first_sql, ready, go))
    assert ready.wait(20)
    second = in_thread(_write(second_sql))
    second[0].join(20)
    go.set()
    finish(first, second)


@pytest.fixture
def unborn_typed_row() -> Iterator[tuple[uuid.UUID, str]]:
    """An entity whose typed row has been taken away and saved aside, so a session can insert it."""
    node = _node(f"unborn-{uuid.uuid4().hex[:6]}")
    table = PgNode._meta.db_table
    aside = f"copies_aside_{uuid.uuid4().hex[:8]}"
    _sql(f"CREATE TABLE {aside} AS SELECT * FROM {table} WHERE entity_id = %s", [node.entity_id])  # noqa: S608
    _sql(f"DELETE FROM {table} WHERE entity_id = %s", [node.entity_id])  # noqa: S608
    try:
        yield node.entity_id, f"INSERT INTO {table} SELECT * FROM {aside}"  # noqa: S608
    finally:
        _sql(f"DROP TABLE IF EXISTS {aside}")


#: The two entity-row changes a push carries, each as a raw statement on the entity table.
ENTITY_CHANGES = {
    "deleted_at": "UPDATE tap_entity SET deleted_at = now() WHERE id = %s",
    "dimensions": "UPDATE tap_entity SET dimensions = '{}'::jsonb WHERE id = %s",
}
#: An advisory lock key nothing else takes; the pause trigger below waits on it.
PAUSE_KEY = 0x5C0B1E5


@contextlib.contextmanager
def _insert_paused_after_the_pull(table: str) -> Iterator[str]:
    """A test-only BEFORE INSERT trigger on ``table`` that waits on an advisory lock the test holds.

    Row triggers on one event fire in name order, so a trigger named after the pull trigger with a
    suffix fires after it: an insert stopped here has run the pull (read the entity row and set both
    copies on NEW) and has not yet written the row. That is case 1c of the two-writer trial, held
    open by a lock instead of the trial's test-only ``pg_sleep`` inside the trigger.
    """
    suffix = uuid.uuid4().hex[:8]
    trigger, function = f"{spine_copies.PULL_TRIGGER}_zz_pause_{suffix}", f"copies_test_pause_{suffix}"
    _sql(
        f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS "
        f"$$ BEGIN PERFORM pg_advisory_xact_lock_shared({PAUSE_KEY}); RETURN NEW; END $$"
    )
    _sql(f"CREATE TRIGGER {trigger} BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION {function}()")
    try:
        yield trigger
    finally:
        _sql(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        _sql(f"DROP FUNCTION IF EXISTS {function}()")


@pytest.mark.django_db(transaction=True)
class TestTwoWriters:
    """Each interleaving of the two-writer trial on toy tables, repeated on the real tables."""

    @AC[16]
    @pytest.mark.parametrize("change", sorted(ENTITY_CHANGES))
    def test_entity_change_holding_then_typed_insert_waits_and_reads_it(
        self, unborn_typed_row: tuple[uuid.UUID, str], change: str
    ) -> None:
        """Case 1a: the entity change is open when the typed row is inserted."""
        entity_id, insert = unborn_typed_row
        before = _spine(entity_id)
        blocked = _hold_then([(ENTITY_CHANGES[change], [entity_id])], [(insert, [])])
        assert _spine(entity_id) != before
        assert _copies(PgNode, entity_id) == _spine(entity_id)
        assert blocked, "the second writer never waited for the first"

    @AC[16]
    @pytest.mark.parametrize("change", sorted(ENTITY_CHANGES))
    def test_typed_insert_holding_then_entity_change_pushes_after_it(
        self, unborn_typed_row: tuple[uuid.UUID, str], change: str
    ) -> None:
        """Case 1b: the typed insert is open when the entity changes."""
        entity_id, insert = unborn_typed_row
        before = _spine(entity_id)
        # The insert takes FOR SHARE on the entity row, so the change waits for the insert to commit, and
        # its push then finds the typed row.
        blocked = _hold_then([(insert, [])], [(ENTITY_CHANGES[change], [entity_id])])
        assert _spine(entity_id) != before
        assert _copies(PgNode, entity_id) == _spine(entity_id)
        assert blocked, "the second writer never waited for the first"

    @AC[16]
    @pytest.mark.parametrize("change", sorted(ENTITY_CHANGES))
    def test_an_insert_that_has_read_the_entity_holds_it_until_the_row_is_written(
        self, unborn_typed_row: tuple[uuid.UUID, str], change: str
    ) -> None:
        """Case 1c: the insert's trigger has read the entity row and not yet written the typed row when
        the entity changes. Without the lock the change commits in that gap, the push finds no typed row,
        and the insert then writes the value it read: a stale copy. With FOR SHARE the change cannot
        commit until the insert has, so the test observes it blocked on the inserter and not finishing."""
        entity_id, insert = unborn_typed_row
        table = PgNode._meta.db_table
        before = _spine(entity_id)
        me = Outcome(pid=_sql("SELECT pg_backend_pid()")[0][0])
        # The pause firing after the pull is shown, not assumed: the change below can only block on the
        # inserter if the inserter already holds the entity row FOR SHARE, which the pull takes.
        with _insert_paused_after_the_pull(table):
            _sql("SELECT pg_advisory_lock(%s)", [PAUSE_KEY])
            try:
                inserter = in_thread(_write([(insert, [])]))
                wait_until_blocked_by(inserter[1], me)  # stopped in the pause: the pull has run
                changer = in_thread(_write([(ENTITY_CHANGES[change], [entity_id])]))
                blocked = _blocked_on(changer[1], inserter[1])  # the change waits for the insert
            finally:
                _sql("SELECT pg_advisory_unlock(%s)", [PAUSE_KEY])
            finish(inserter, changer)
        assert _spine(entity_id) != before
        assert _copies(PgNode, entity_id) == _spine(entity_id)
        assert blocked, "the entity change committed while the insert was between its read and its write"

    @AC[16]
    def test_dimensions_change_holding_then_typed_update_reads_the_committed_map(self) -> None:
        node = _node("dims-first")
        table = PgNode._meta.db_table
        # The typed update reads the entity row without a lock, so it does not wait; the push in the
        # entity transaction holds the typed row, so the typed update waits for that instead.
        assert _hold_then(
            [("UPDATE tap_entity SET dimensions = '{}'::jsonb WHERE id = %s", [node.entity_id])],
            [(f"UPDATE {table} SET name = 'renamed' WHERE entity_id = %s", [node.entity_id])],  # noqa: S608
        )
        assert _copies(PgNode, node.entity_id) == _spine(node.entity_id) == (None, {})

    @AC[16]
    def test_typed_update_holding_then_dimensions_change_pushes_after_it(self) -> None:
        node = _node("typed-first")
        table = PgNode._meta.db_table
        assert _hold_then(
            [(f"UPDATE {table} SET name = 'renamed' WHERE entity_id = %s", [node.entity_id])],  # noqa: S608
            [("UPDATE tap_entity SET dimensions = '{}'::jsonb WHERE id = %s", [node.entity_id])],
        )
        assert _copies(PgNode, node.entity_id) == _spine(node.entity_id) == (None, {})

    @AC[16]
    def test_the_pipelines_own_order_entity_then_typed_does_not_deadlock_against_a_push(self) -> None:
        """Every core writer locks the entity row and then writes the typed row; a raw retirement racing
        it waits on the entity lock and pushes after."""
        node = _node("pipeline-order")
        table = PgNode._meta.db_table
        assert _hold_then(
            [
                ("SELECT 1 FROM tap_entity WHERE id = %s FOR UPDATE", [node.entity_id]),
                (f"UPDATE {table} SET name = 'renamed' WHERE entity_id = %s", [node.entity_id]),  # noqa: S608
            ],
            [("UPDATE tap_entity SET deleted_at = now() WHERE id = %s", [node.entity_id])],
        )
        assert _copies(PgNode, node.entity_id) == _spine(node.entity_id)
        assert _copies(PgNode, node.entity_id)[0] is not None
