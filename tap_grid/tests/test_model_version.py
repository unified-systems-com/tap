"""Model versions: the declared version, the applied version, the rule that they agree, and the guard.

Covers ``req-grid-entity-model-version`` rules 1 to 8 (spec-grid-entity.md); Issue# 475 - tap.
A "start" here is the call the process makes at start: ``register_type``, or the plugin loader's
own ``_register_types_from_manifest``. A "migration" is ``set_applied_version`` inside a
transaction, which is the one call a plugin's migration makes once its rows are converted. The
adapter that converts rows (rules 29 to 33) is not built, so no test here converts any.

Service writes use the neutral grid_fixtures ``PgNode`` and the ``PG_LINKS__grid_fixtures`` edge.
"""

from __future__ import annotations

import copy
import importlib
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import models, transaction
from django.test.utils import isolate_apps
from tap_plugin.grid_fixtures.models.pg_node import PgNode

from tap_grid import model_definition as definition
from tap_grid import model_version as mv
from tap_grid.caller_context import CallerContext
from tap_grid.grift import grift_import
from tap_grid.grift.exporter import export_grid
from tap_grid.models import BaseModel, Edge, Entity, EntityType, EntityTypeKind
from tap_grid.service_types import WriteOperation, WriteResult
from tap_grid.services import create_node, delete_node, patch_node, write_batch
from tap_grid.tests.test_grift import _batch_container, _minimal_doc

AC = {n: pytest.mark.spec(f"req-grid-entity-model-version-{n}") for n in (1, 2, 3, 4, 5, 18, 21, 22)}

pytestmark = pytest.mark.django_db

_TYPE = "grid_fixtures__node"
LINK = "PG_LINKS__grid_fixtures"


def _write_anywhere(path: Path, record: dict[str, Any]) -> None:
    """A record file in a test's own directory. ``write_record`` itself writes only into an
    installed app's package, so a test that needs a file elsewhere writes it plainly."""
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture(autouse=True)
def _process_state() -> Iterator[None]:
    """What registration keeps per process, put back after each test."""
    pending, edge_versions, owed = dict(mv._pending), dict(mv._edge_versions), mv._start_incomplete
    # Whatever the process found at start belongs to the database it started against, not the test's.
    mv._pending.clear()
    mv._start_incomplete = False
    try:
        yield
    finally:
        mv._start_incomplete = owed
        mv._pending.clear()
        mv._pending.update(pending)
        mv._edge_versions.clear()
        mv._edge_versions.update(edge_versions)


def _declare(monkeypatch: pytest.MonkeyPatch, version: int) -> None:
    monkeypatch.setattr(PgNode, "MODEL_VERSION", version)


def _start(type_slug: str = _TYPE) -> None:
    """What a process start does for the type: the catalog write and the comparison."""
    mv.register_type(
        type_slug,
        kind=mv.NODE,
        declared=mv.declared_version(PgNode),
        defaults={"name": "PgNode", "plugin_name": "tap_plugin.grid_fixtures", "kind": EntityTypeKind.NODE},
    )


def _migrate_to(version: int, type_slug: str = _TYPE) -> None:
    """What a migration does once it has converted the type's rows."""
    with transaction.atomic():
        mv.set_applied_version(type_slug, version)


def _applied(type_slug: str = _TYPE) -> int | None:
    return mv.applied_version(type_slug)


def _node(name: str) -> uuid.UUID:
    made = create_node(_TYPE, {"name": name})
    assert made.success, made.errors
    assert made.entity_id is not None
    return made.entity_id


def _write(op: WriteOperation) -> WriteResult:
    """One operation in a fresh batch, whatever its outcome."""
    outcome = write_batch(
        [op],
        caller_context=CallerContext(batch_id=str(uuid.uuid7())),
        batch_name="model version",
        batch_description="test",
    )
    return outcome.results[0]


def _never_held(type_slug: str = _TYPE) -> None:
    EntityType.objects.filter(slug=type_slug).delete()


# ---------------------------------------------------------------------------
# Rule 1: the declared version
# ---------------------------------------------------------------------------


class TestTheDeclaredVersion:
    def test_a_model_that_states_none_is_at_version_1(self) -> None:
        assert "MODEL_VERSION" not in PgNode.__dict__
        assert mv.declared_version(PgNode) == 1
        assert BaseModel.MODEL_VERSION == 1

    def test_a_model_states_its_version_as_a_class_attribute(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _declare(monkeypatch, 4)
        assert mv.declared_version(PgNode) == 4

    @pytest.mark.parametrize("bad", [0, -1, "2", 2.0, True, None])
    def test_a_version_that_is_not_a_whole_number_from_1_is_refused(self, bad: Any) -> None:
        with pytest.raises(mv.ModelVersionError, match="whole number"):
            mv.checked_version(bad, "Thing.MODEL_VERSION")

    def test_a_class_declaring_a_bad_version_does_not_import(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="MODEL_VERSION"):
            type("BadVersion", (BaseModel,), {"__module__": __name__, "MODEL_VERSION": "2", "Meta": _abstract()})

    def test_an_edge_type_states_its_version_beside_its_property_rules(self) -> None:
        from tap_plugins.base import register_edge_types_from_list

        assert mv.declared_edge_version("UNSTATED_LINK") == 1
        register_edge_types_from_list([{"slug": "VERSIONED_LINK_FOR_TEST", "version": 3}])
        assert mv.declared_edge_version("VERSIONED_LINK_FOR_TEST") == 3

    def test_the_edge_definition_file_accepts_a_version_and_refuses_a_bad_one(self, tmp_path: Path) -> None:
        from tap.jsonfiles import JsonFileError, load_json_file
        from tap_plugins.manifest import _load_edge_schema

        good = tmp_path / "links.edge.json"
        good.write_text('{"slug": "LINKS", "name": "Links", "description": "A link.", "version": 2}')
        assert load_json_file(good, schema=_load_edge_schema())["version"] == 2
        bad = tmp_path / "bad.edge.json"
        bad.write_text('{"slug": "LINKS", "name": "Links", "description": "A link.", "version": 0}')
        with pytest.raises(JsonFileError):
            load_json_file(bad, schema=_load_edge_schema())


def _abstract() -> type:
    return type("Meta", (), {"abstract": True, "app_label": "tap_grid"})


# ---------------------------------------------------------------------------
# Rule 3: the applied version and its two writers
# ---------------------------------------------------------------------------


class TestTheAppliedVersion:
    @AC[1]
    def test_first_registration_records_the_declared_version(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _never_held()
        _declare(monkeypatch, 2)
        _start()
        assert _applied() == 2
        assert mv.disagreement(_TYPE) is None

    @AC[1]
    def test_a_restart_on_newer_code_does_not_advance_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _never_held()
        _declare(monkeypatch, 2)
        _start()
        _declare(monkeypatch, 3)
        _start()
        _start()
        assert _applied() == 2
        behind = mv.disagreement(_TYPE)
        assert behind is not None and (behind.declared, behind.applied) == (3, 2)

    @AC[1]
    def test_a_completed_migration_advances_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _never_held()
        _declare(monkeypatch, 2)
        _start()
        _declare(monkeypatch, 3)
        _start()
        _migrate_to(3)
        assert _applied() == 3
        assert mv.disagreement(_TYPE) is None
        # The next start finds them in agreement and changes nothing.
        _start()
        assert _applied() == 3

    @AC[1]
    def test_the_plugin_loader_compares_and_does_not_stamp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The start-up code itself: the loader every plugin's ``ready()`` runs."""
        config: Any = apps.get_app_config("grid_fixtures")
        config._register_types_from_manifest()
        assert _applied() == 1
        row = EntityType.objects.get(slug=_TYPE)
        assert (row.kind, row.plugin_name) == (EntityTypeKind.NODE, config.name)

        _declare(monkeypatch, 2)
        config._register_types_from_manifest()
        assert _applied() == 1
        assert mv.disagreement(_TYPE) is not None
        # Every other type of the plugin, which states no version, is at 1 and in agreement.
        others = EntityType.objects.filter(plugin_name=config.name).exclude(slug=_TYPE)
        assert others.count() > 5
        assert set(others.values_list("model_version", flat=True)) == {1}
        assert set(mv._pending) == {_TYPE}

    def test_a_type_first_catalogued_while_the_grid_holds_its_rows_is_at_1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rows written before versions were recorded are at version 1, whatever the class now says."""
        _node("written before the catalog row")
        _never_held()
        _declare(monkeypatch, 2)
        _start()
        assert _applied() == 1
        assert mv.disagreement(_TYPE) is not None

    def test_registration_keeps_the_descriptive_columns_current(self) -> None:
        _never_held()
        _start()
        mv.register_type(_TYPE, kind=mv.NODE, declared=1, defaults={"name": "Renamed", "plugin_name": "elsewhere"})
        row = EntityType.objects.get(slug=_TYPE)
        assert (row.name, row.plugin_name, row.model_version) == ("Renamed", "elsewhere", 1)

    def test_a_migration_on_a_database_with_no_catalog_row_records_the_version(self) -> None:
        """A database migrated from nothing: registration found no table at start, so there is no row."""
        _never_held()
        _migrate_to(2)
        assert _applied() == 2

    def test_setting_the_applied_version_needs_a_transaction(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from django.db import connection

        monkeypatch.setattr(connection, "in_atomic_block", False)
        with pytest.raises(mv.ModelVersionError, match="inside the transaction"):
            mv.set_applied_version(_TYPE, 2)

    @AC[18]
    def test_a_failed_migration_leaves_it_and_writes_stay_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _never_held()
        _start()
        _declare(monkeypatch, 2)
        _start()

        class MigrationFailed(Exception):
            pass

        with pytest.raises(MigrationFailed), transaction.atomic():
            mv.set_applied_version(_TYPE, 2)
            assert _applied() == 2
            raise MigrationFailed("a later step of the same migration failed")

        assert _applied() == 1
        refused = create_node(_TYPE, {"name": "after the failed migration"})
        assert not refused.success
        assert [error.code for error in refused.errors] == ["model_version_pending"]


# ---------------------------------------------------------------------------
# Rule 4: applied and declared must agree
# ---------------------------------------------------------------------------


class TestAgreement:
    @pytest.fixture
    def behind(self, monkeypatch: pytest.MonkeyPatch) -> uuid.UUID:
        """The class at version 2, the catalog at 1, and one row written before the change."""
        _never_held()
        _start()
        existing = _node("written at version 1")
        _declare(monkeypatch, 2)
        _start()
        return existing

    @AC[3]
    def test_a_write_is_refused_naming_both_versions(self, behind: uuid.UUID) -> None:
        refused = create_node(_TYPE, {"name": "new"})
        assert not refused.success
        (error,) = refused.errors
        assert error.code == "model_version_pending"
        assert _TYPE in error.message and "version 2" in error.message and "version 1" in error.message
        assert error.detail == {"type": _TYPE, "declared_version": 2, "applied_version": 1}
        assert not Entity.objects.filter(name="new").exists()

        patched = patch_node(behind, {"name": "changed"})
        assert not patched.success and patched.errors[0].code == "model_version_pending"
        assert Entity.objects.get(pk=behind).name == "written at version 1"

    @AC[3]
    def test_migrate_runs_through_the_disagreement(self, behind: uuid.UUID) -> None:
        call_command("migrate", verbosity=0, interactive=False)
        assert _applied() == 1
        assert mv.disagreement(_TYPE) is not None

    @AC[3]
    def test_a_save_below_the_pipeline_is_refused_too(self, behind: uuid.UUID) -> None:
        row = PgNode.all_objects.get(entity_id=behind)
        row.name = "changed below the pipeline"
        with pytest.raises(mv.ModelVersionPending, match="version 2.*version 1"):
            row.save()

    @AC[3]
    def test_code_older_than_the_data_fails_registration_naming_both(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _never_held()
        _declare(monkeypatch, 3)
        _start()
        _declare(monkeypatch, 2)
        with pytest.raises(mv.ModelVersionAhead) as raised:
            _start()
        assert (raised.value.type_slug, raised.value.declared, raised.value.applied) == (_TYPE, 2, 3)
        assert _TYPE in str(raised.value) and "version 2" in str(raised.value) and "version 3" in str(raised.value)
        # It stops the process: Django reports a failure in ready() of this kind as a bad configuration.
        assert isinstance(raised.value, ImproperlyConfigured)

    @AC[3]
    def test_the_plugin_loader_lets_that_failure_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config: Any = apps.get_app_config("grid_fixtures")
        config._register_types_from_manifest()
        _migrate_to(2)
        with pytest.raises(mv.ModelVersionAhead, match=_TYPE):
            config._register_types_from_manifest()

    def test_retiring_by_id_is_the_one_write_let_through(self, behind: uuid.UUID) -> None:
        retired = delete_node(behind, reason="operator")
        assert retired.success, retired.errors
        assert Entity.objects.get(pk=behind).deleted_at is not None

    def test_an_edge_type_is_held_to_the_same_rule(self) -> None:
        source, target = _node("from"), _node("to")
        existing = _write(WriteOperation(verb="create_edge", from_target=source, to_target=target, edge_type=LINK))
        assert existing.success, existing.errors
        assert existing.entity_id is not None
        EntityType.objects.filter(slug=LINK).delete()
        mv.register_type(LINK, kind=mv.EDGE, declared=1, defaults={"name": LINK, "kind": EntityTypeKind.EDGE})
        mv.register_type(LINK, kind=mv.EDGE, declared=2, defaults={"name": LINK, "kind": EntityTypeKind.EDGE})

        refused = _write(WriteOperation(verb="create_edge", from_target=target, to_target=source, edge_type=LINK))
        assert not refused.success and refused.errors[0].code == "model_version_pending"
        assert LINK in refused.errors[0].message
        # A node write is untouched by an edge type's disagreement, and the edge can still be retired by id.
        _node("unaffected")
        retired = _write(WriteOperation(verb="delete_edge", target=existing.entity_id, reason="operator"))
        assert retired.success, retired.errors
        assert Edge.all_objects.get(entity_id=existing.entity_id).entity.deleted_at is not None

    @AC[3]
    def test_an_import_that_carries_the_type_is_refused_whole(self, behind: uuid.UUID) -> None:
        nodes = [
            {
                "entity": {
                    "entity_id": str(uuid.uuid7()),
                    "entity_type": _TYPE,
                    "name": "imported",
                    "dimensions": {},
                    "created_at": "2026-11-01T00:00:00+00:00",
                    "updated_at": "2026-11-01T00:00:00+00:00",
                },
                "node": {"name": "imported"},
            }
        ]
        document = _minimal_doc([_batch_container(str(uuid.uuid7()), nodes=nodes)])
        result = grift_import(document)
        assert not result.success
        codes = [issue.code for issue in result.errors]
        assert "model_version_pending" in codes
        issue = next(issue for issue in result.errors if issue.code == "model_version_pending")
        assert _TYPE in issue.message and "version 2" in issue.message and "version 1" in issue.message
        assert result.imported_batches == []
        assert not Entity.objects.filter(name="imported").exists()

    @AC[3]
    def test_an_export_that_carries_the_type_is_refused(self, behind: uuid.UUID) -> None:
        with pytest.raises(mv.ModelVersionPending, match=f"{_TYPE}.*version 2.*version 1.*export"):
            export_grid()

    def test_a_migration_applied_by_another_process_is_seen_without_a_restart(self, behind: uuid.UUID) -> None:
        """The refusal reads the catalog again before it refuses."""
        with mv._writing_applied_version():
            EntityType.objects.filter(slug=_TYPE).update(model_version=2)
        assert _TYPE in mv._pending
        assert create_node(_TYPE, {"name": "after the migration"}).success
        assert _TYPE not in mv._pending

    def test_types_in_agreement_cost_no_query(self, django_assert_num_queries: Any) -> None:
        assert not mv._pending
        with django_assert_num_queries(0):
            mv.refuse_if_pending(_TYPE, "a write")
            assert mv.disagreements([_TYPE, LINK, "batch"]) == []


class TestAStartThatCouldNotCompare:
    """A process whose start could not read the database owes the comparison, and makes it
    before its first write (rule 4)."""

    def test_each_place_a_start_skips_the_comparison_marks_it_owed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from django.db import OperationalError, ProgrammingError

        from tap_grid import spine_version

        def down(*args: Any, **kwargs: Any) -> None:
            raise OperationalError("could not connect to server")

        def unmigrated(*args: Any, **kwargs: Any) -> None:
            raise ProgrammingError('column "model_version" does not exist')

        core: Any = apps.get_app_config("tap_grid")
        with monkeypatch.context() as patch:
            patch.setattr(mv, "register_core_types", down)
            core.compare_versions_at_start()
        assert mv.start_incomplete()

        mv._start_incomplete = False
        plugin: Any = apps.get_app_config("grid_fixtures")
        with monkeypatch.context() as patch:
            patch.setattr(mv, "register_type", unmigrated)
            plugin._register_types_from_manifest()
        assert mv.start_incomplete()

        mv._start_incomplete = False
        with monkeypatch.context() as patch:
            patch.setattr(spine_version, "recorded_version", down)
            spine_version.refuse_newer_database()
        assert mv.start_incomplete()

    @AC[3]
    def test_a_write_after_a_skipped_start_is_refused_where_the_rows_are_behind(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _never_held()
        _start()
        _declare(monkeypatch, 2)
        # The start that would have found the type behind never compared it.
        mv._start_incomplete = True
        assert not mv._pending
        refused = create_node(_TYPE, {"name": "after a skipped start"})
        assert not refused.success and refused.errors[0].code == "model_version_pending"
        assert not mv.start_incomplete() and set(mv._pending) == {_TYPE}
        assert not Entity.objects.filter(name="after a skipped start").exists()

    @AC[3]
    def test_data_ahead_of_the_code_raises_at_the_first_write_and_at_every_later_one(self) -> None:
        _never_held()
        _start()
        _migrate_to(3)
        mv._start_incomplete = True
        for _attempt in range(2):
            with pytest.raises(mv.ModelVersionAhead) as raised:
                mv.refuse_if_pending(_TYPE, "a write")
            assert (raised.value.declared, raised.value.applied) == (1, 3)
            assert mv.start_incomplete()
        with pytest.raises(mv.ModelVersionAhead):
            PgNode(name="saved directly").save()

    def test_a_newer_spine_raises_at_the_first_write(self) -> None:
        from tap_grid import spine_version
        from tap_grid.models import SpineVersion

        SpineVersion.objects.update(version=spine_version.SPINE_VERSION + 1)
        mv._start_incomplete = True
        with pytest.raises(spine_version.SpineVersionAhead):
            mv.disagreements([_TYPE])
        assert mv.start_incomplete()

    def test_the_comparison_is_made_once_and_then_costs_nothing(self, django_assert_num_queries: Any) -> None:
        mv._start_incomplete = True
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        # The spine record and the whole catalog: two reads, however many types are installed.
        with CaptureQueriesContext(connection) as captured:
            mv.refuse_if_pending(_TYPE, "a write")
        statements = [query["sql"] for query in captured.captured_queries]
        assert sum(1 for sql in statements if 'FROM "tap_spine_version"' in sql) == 1, statements
        assert sum(1 for sql in statements if 'FROM "tap_entity_type"' in sql) == 1, statements
        assert not mv.start_incomplete()
        with django_assert_num_queries(0):
            mv.refuse_if_pending(_TYPE, "a write")
            assert mv.disagreements([_TYPE, LINK, "batch"]) == []

    def test_a_comparison_that_cannot_be_made_stays_owed_and_leaves_the_transaction_usable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from django.db import connection

        from tap_grid import spine_version

        def unmigrated(**kwargs: Any) -> int | None:
            with connection.cursor() as cursor:
                cursor.execute("SELECT version FROM a_table_that_is_not_there")
            return None

        monkeypatch.setattr(spine_version, "recorded_version", unmigrated)
        mv._start_incomplete = True
        with transaction.atomic():
            before = EntityType.objects.count()
            mv.refuse_if_pending(_TYPE, "a write")
            assert mv.disagreements([_TYPE]) == []
            # The failed read was rolled back to its savepoint; this transaction still works.
            assert EntityType.objects.count() == before
        assert mv.start_incomplete()

    def test_applying_migrations_makes_the_owed_comparison(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_grid import spine_version

        _never_held()
        _start()
        _declare(monkeypatch, 2)
        mv._start_incomplete = True
        spine_version.record_after_migrate(sender=apps.get_app_config("tap_grid"))
        assert not mv.start_incomplete() and set(mv._pending) == {_TYPE}

    def test_an_uninstalled_types_row_is_not_compared(self) -> None:
        """A catalog row of a type no installed code declares is not this code's to judge."""
        with mv._writing_applied_version():
            EntityType.objects.create(slug="gone__type", name="Gone", model_version=7)
        mv._start_incomplete = True
        mv.refuse_if_pending(_TYPE, "a write")
        assert not mv.start_incomplete()


class TestWhatADocumentCarries:
    def test_types_named_by_record_and_by_key_are_carried_and_ids_are_not(self) -> None:
        document = {
            "batches": [
                {
                    "nodes": [{"entity": {"entity_type": "page"}, "node": {}}],
                    "edges": [
                        {
                            "entity": {"entity_type": "edge"},
                            "edge": {
                                "edge_type": "USES_PANEL",
                                "from_entity_id": "x",
                                "to_key": {"entity_type": "panel", "key": {"slug": "p"}},
                            },
                        }
                    ],
                    "deletes": {
                        "nodes": [{"entity_id": "y", "entity_type": "layout", "reason": "gone"}],
                        "edges": [
                            {"entity_id": "z", "entity_type": "edge", "reason": "gone"},
                            {
                                "edge_type": "NESTS_UNDER",
                                "from": {"entity_type": "projection", "key": {}},
                                "to": {"entity_id": "w"},
                                "reason": "gone",
                            },
                        ],
                    },
                }
            ]
        }
        assert mv.types_carried(document) == {"batch", "page", "USES_PANEL", "panel", "NESTS_UNDER", "projection"}

    @pytest.mark.parametrize("shape", [None, [], "text", {"batches": "no"}, {"batches": [None, {"nodes": 3}]}])
    def test_a_malformed_document_is_read_without_raising(self, shape: Any) -> None:
        assert mv.types_carried(shape) <= {"batch"}


# ---------------------------------------------------------------------------
# Rule 2: no version on a row
# ---------------------------------------------------------------------------


class TestNoVersionOnARow:
    @AC[2]
    def test_the_migration_touches_the_catalog_and_adds_one_table(self) -> None:
        migration = importlib.import_module("tap_grid.migrations.0022_model_and_spine_versions").Migration
        described = [
            (type(operation).__name__, getattr(operation, "model_name", None) or operation.name.lower())
            for operation in migration.operations
        ]
        assert described == [("AddField", "entitytype"), ("CreateModel", "spineversion")]

    @AC[2]
    def test_no_row_and_no_typed_table_carries_a_version(self) -> None:
        version_columns = {"model_version", "spine_version", "type_version"}
        assert not version_columns & {field.name for field in Entity._meta.get_fields()}
        carriers = [
            model._meta.label
            for model in apps.get_models()
            if issubclass(model, BaseModel) and version_columns & {field.name for field in model._meta.fields}
        ]
        assert carriers == []


# ---------------------------------------------------------------------------
# Rule 6: core's own types
# ---------------------------------------------------------------------------


class TestCoreTypes:
    def test_each_core_node_and_edge_type_gets_a_row_and_a_version(self) -> None:
        EntityType.objects.all().delete()
        mv.register_core_types()
        nodes = set(EntityType.objects.filter(kind=EntityTypeKind.NODE).values_list("slug", flat=True))
        edges = set(EntityType.objects.filter(kind=EntityTypeKind.EDGE).values_list("slug", flat=True))
        assert {"batch", "dimension", "keystone", "search", "page", "panel", "layout", "collector"} <= nodes
        assert {"PRODUCED_BATCH", "USES_PANEL", "NESTS_UNDER"} <= edges
        # The edge model's table is the spine's; it is not a node type.
        assert "edge" not in nodes
        assert nodes == set(mv.core_node_types()) and edges == set(mv.core_edge_types())
        assert set(EntityType.objects.values_list("model_version", flat=True)) == {1}
        # The owning app's dotted name, which icon resolution compares (req-grid-entity-core-type-catalog).
        assert EntityType.objects.get(slug="page").plugin_name == "tap_web"
        # The one row core wrote before this keeps the name and icon it had.
        search = EntityType.objects.get(slug="search")
        assert (search.name, search.icon) == ("Search", "search")
        assert EntityType.objects.get(slug="keystone").name == "Keystone"
        assert not any(slug.startswith("grid_fixtures") for slug in nodes)

    @AC[21]
    def test_every_type_an_export_of_core_types_carries_has_an_applied_version(self) -> None:
        """The catalog half of the criterion. Stating the versions in the document's header is
        ``req-grift-header-versions``, which is not built."""
        from tap_grid.models import Keystone
        from tap_grid.tests.test_grift_export import _empty_the_grid

        _empty_the_grid()
        EntityType.objects.all().delete()
        mv.register_core_types()
        made = create_node("keystone", {"name": "this grid"})
        assert made.success, made.errors
        assert Keystone.objects.count() == 1

        export = export_grid()
        carried = {"batch", *export.node_counts, *export.edge_counts}
        assert "keystone" in carried
        versions = {slug: mv.applied_version(slug) for slug in sorted(carried)}
        assert all(version == 1 for version in versions.values()), versions


# ---------------------------------------------------------------------------
# Rules 5, 7 and 8: the definition, its fingerprint, and the committed record
# ---------------------------------------------------------------------------


def _recorded(state: definition.TypeState) -> dict[str, Any]:
    record: dict[str, Any] = {"format": definition.RECORD_FORMAT}
    assert definition.append_entry(record, state)
    return record


def _problems(state: definition.TypeState, record: dict[str, Any]) -> list[str]:
    return definition.type_problems(state, definition.entries_for(record, state))


class TestTheFingerprintGuard:
    def test_core_is_in_step_with_its_committed_records(self) -> None:
        from tap.guards.model_version import core_problems

        assert core_problems() == []

    def test_every_core_type_and_the_spine_has_an_entry(self) -> None:
        owned = definition.core_states()
        assert {"tap_grid", "tap_web", "tap_viz", "tap_cares", "tap_files"} <= set(owned)
        for owner, states in owned.items():
            record = definition.load_record(definition.app_record_path(owner))
            assert definition.unrecorded(states, record) == [], owner
        assert [state.kind for state in owned["tap_grid"]].count(definition.SPINE) == 1

    @AC[4]
    @isolate_apps("django.contrib.contenttypes")
    def test_adding_a_field_without_raising_the_version_fails_naming_the_model(self) -> None:
        class Before(models.Model):  # noqa: DJ008
            title = models.CharField(max_length=40)

            class Meta:
                app_label = "contenttypes"

        class After(models.Model):  # noqa: DJ008
            title = models.CharField(max_length=40)
            subtitle = models.IntegerField(null=True)

            class Meta:
                app_label = "contenttypes"

        record = _recorded(definition.TypeState(mv.NODE, "sample__thing", 1, definition.node_definition(Before)))
        unchanged = definition.TypeState(mv.NODE, "sample__thing", 1, definition.node_definition(Before))
        assert _problems(unchanged, record) == []

        changed = definition.TypeState(mv.NODE, "sample__thing", 1, definition.node_definition(After))
        (problem,) = _problems(changed, record)
        assert "sample__thing" in problem and "fields.subtitle added" in problem and "still 1" in problem

        # Raising the version and recording it is the way through; the earlier entry stays as it was.
        raised = definition.TypeState(mv.NODE, "sample__thing", 2, definition.node_definition(After))
        assert "version 2 is declared" in _problems(raised, record)[0]
        first = copy.deepcopy(record["nodes"]["sample__thing"][0])
        assert definition.append_entry(record, raised)
        assert _problems(raised, record) == []
        assert record["nodes"]["sample__thing"][0] == first
        assert [entry["version"] for entry in record["nodes"]["sample__thing"]] == [1, 2]

    @AC[4]
    def test_the_guard_names_a_core_model_whose_definition_moved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The guard itself, on the real tree: a core model gains a service field, its version unchanged."""
        from tap.guards.model_version import ModelVersionGuard
        from tap_grid.models import Keystone

        ModelVersionGuard().check()
        monkeypatch.setattr(
            Keystone, "FIELD_CRUD_SCHEMA", {**Keystone.FIELD_CRUD_SCHEMA, "added_field": {"type": "string"}}
        )
        with pytest.raises(AssertionError, match="node type 'keystone'.*still 1"):
            ModelVersionGuard().check()

    @pytest.mark.parametrize(
        "change",
        [
            {"key": ["title"]},
            {"service_schema": {"fields": {"title": {"type": "string"}}}},
            {"edge_rules": {"outbound": [{"type": "x"}]}},
            {"constraints": [{"unique_together": ["title"]}]},
        ],
    )
    def test_each_part_of_a_node_definition_is_covered(self, change: dict[str, Any]) -> None:
        base = definition.node_definition(PgNode)
        record = _recorded(definition.TypeState(mv.NODE, _TYPE, 1, base))
        assert _problems(definition.TypeState(mv.NODE, _TYPE, 1, {**base, **change}), record)

    def test_each_part_of_an_edge_definition_is_covered(self) -> None:
        declared: dict[str, Any] = {
            "sources": ["a"],
            "targets": None,
            "property_schema": {"type": "object"},
            "event_time": None,
            "identity": None,
        }
        base = definition.edge_definition(**declared)
        record = _recorded(definition.TypeState(mv.EDGE, "LINKS", 1, base))
        for key, value in (
            ("sources", ["a", "b"]),
            ("targets", ["c"]),
            ("property_schema", {"type": "object", "required": ["since"]}),
            ("event_time", {"shape": "moment", "kind": "occurred", "field": "since"}),
            ("identity", {"discriminators": []}),
            ("identity", {"discriminators": ["since"]}),
        ):
            moved = definition.edge_definition(**{**declared, key: value})
            assert _problems(definition.TypeState(mv.EDGE, "LINKS", 1, moved), record), key
        # The two ways of writing the same endpoint rule are one definition.
        same = definition.edge_definition(**{**declared, "sources": [{"type": "a"}]})
        assert _problems(definition.TypeState(mv.EDGE, "LINKS", 1, same), record) == []

    def test_an_event_time_declaration_is_covered_and_its_three_statements_differ(self) -> None:
        from tap_grid.event_time import NO_EVENT_TIME, Interval, Moment

        written = [
            definition.event_time_definition(declared)
            for declared in (
                None,
                NO_EVENT_TIME,
                Moment("seen_at", "occurred"),
                Moment("made_at", "occurred"),
                Moment("seen_at", "created"),
                Interval("began", "occurred"),
                Interval("began", "occurred", end="ended"),
            )
        ]
        assert written[0] is None and written[1] == {"shape": "none"}
        assert len({definition._sort_key(item) for item in written}) == len(written)
        assert all("0x" not in str(item) and "NO_EVENT_TIME" not in str(item) for item in written)
        with pytest.raises(TypeError):
            definition.event_time_definition("seen_at")

        base = definition.node_definition(PgNode)
        record = _recorded(definition.TypeState(mv.NODE, _TYPE, 1, base))
        moved = {**base, "event_time": definition.event_time_definition(Moment("name", "occurred"))}
        assert moved != base
        assert _problems(definition.TypeState(mv.NODE, _TYPE, 1, moved), record)

    def test_a_record_is_written_only_into_an_installed_apps_package(self, tmp_path: Path) -> None:
        record: dict[str, Any] = {"format": definition.RECORD_FORMAT}
        outside = tmp_path / definition.record_file_name("tap_grid")
        with pytest.raises(ValueError, match="not the version record of an installed app"):
            definition.write_record(outside, record)
        assert not outside.exists()
        # Inside an installed app's package, under any name but that app's record name.
        misnamed = definition.app_record_path("tap_grid").with_name("tap_web.model_versions.json")
        with pytest.raises(ValueError, match="not the version record of an installed app"):
            definition.write_record(misnamed, record)
        assert not misnamed.exists()
        assert (
            definition._owned_record_path(definition.app_record_path("tap_grid")).name == "tap_grid.model_versions.json"
        )

    def test_what_bears_on_no_stored_row_is_not_covered(self) -> None:
        field = models.CharField(max_length=40, help_text="one", db_index=False, default="a")
        other = models.CharField(max_length=40, help_text="two", db_index=True, default="b")
        assert definition._field_definition(field) == definition._field_definition(other)
        assert definition._field_definition(models.CharField(max_length=41)) != definition._field_definition(field)

    def test_a_definition_is_the_same_on_every_run(self) -> None:
        first = definition.node_definition(PgNode)
        again = definition.node_definition(PgNode)
        assert first == again
        assert definition.canonical({"b": {2, 1}, "a": (1, 2)}) == {"a": [1, 2], "b": [1, 2]}
        assert "0x" not in str(definition.spine_definition())

    @AC[5]
    def test_editing_the_committed_entry_of_an_earlier_version_fails(self) -> None:
        state_1 = definition.TypeState(mv.NODE, _TYPE, 1, definition.node_definition(PgNode))
        record = _recorded(state_1)
        later = {**state_1.definition, "key": ["name", "added"]}
        state_2 = definition.TypeState(mv.NODE, _TYPE, 2, later)
        assert definition.append_entry(record, state_2)
        assert _problems(state_2, record) == []

        edited = copy.deepcopy(record)
        edited["nodes"][_TYPE][0]["definition"]["key"] = ["rewritten"]
        (problem,) = _problems(state_2, edited)
        assert _TYPE in problem and "version 1 was changed after it was recorded" in problem

        # Re-fingerprinting the edited entry alone does not hide it: the next entry chains to the original.
        rehashed = copy.deepcopy(edited)
        rehashed["nodes"][_TYPE][0]["fingerprint"] = definition.fingerprint(
            "", 1, rehashed["nodes"][_TYPE][0]["definition"]
        )
        (problem,) = _problems(state_2, rehashed)
        assert "version 2 was changed after it was recorded" in problem

    @AC[5]
    def test_the_record_only_grows_one_version_at_a_time(self) -> None:
        state = definition.TypeState(mv.NODE, _TYPE, 1, definition.node_definition(PgNode))
        record = _recorded(state)
        assert not definition.append_entry(record, state)
        with pytest.raises(ValueError, match="one entry per version"):
            definition.append_entry(record, definition.TypeState(mv.NODE, _TYPE, 3, state.definition))
        removed = copy.deepcopy(record)
        definition.append_entry(removed, definition.TypeState(mv.NODE, _TYPE, 2, state.definition))
        del removed["nodes"][_TYPE][0]
        assert (
            "changed after it was recorded"
            in _problems(definition.TypeState(mv.NODE, _TYPE, 2, state.definition), removed)[0]
        )
        # A record ahead of the code: a version does not go down.
        assert "does not go down" in _problems(state, _recorded_through(state, 2))[0]

    def test_recording_refuses_to_extend_an_edited_record(self) -> None:
        state = definition.TypeState(mv.NODE, _TYPE, 1, definition.node_definition(PgNode))
        record = _recorded(state)
        record["nodes"][_TYPE][0]["definition"]["key"] = ["rewritten"]
        with pytest.raises(ValueError, match="changed after it was recorded"):
            definition.append_entry(record, definition.TypeState(mv.NODE, _TYPE, 2, state.definition))

    def test_a_meaning_only_change_is_the_authors_manual_raise(self) -> None:
        """Rule 8: the guard cannot see it, and a version raised with an unchanged definition records cleanly."""
        state = definition.TypeState(mv.NODE, _TYPE, 1, definition.node_definition(PgNode))
        record = _recorded(state)
        raised = definition.TypeState(mv.NODE, _TYPE, 2, state.definition)
        assert definition.append_entry(record, raised)
        assert _problems(raised, record) == []
        for skill in ("add-model", "add-edge"):
            guidance = (Path(__file__).resolve().parents[1] / "skills" / skill / "SKILL.md").read_text("utf-8")
            assert "by hand" in guidance and "version" in guidance.lower(), skill

    @AC[22]
    @isolate_apps("django.contrib.contenttypes")
    def test_removing_an_inherited_field_changes_no_types_definition(self) -> None:
        class BaseBefore(models.Model):
            batch_id = models.CharField(max_length=36)
            flip_map = models.JSONField(default=dict)

            class Meta:
                abstract = True
                app_label = "contenttypes"

        class BaseAfter(models.Model):
            flip_map = models.JSONField(default=dict)

            class Meta:
                abstract = True
                app_label = "contenttypes"

        class ThingBefore(BaseBefore):  # noqa: DJ008
            title = models.CharField(max_length=40)

            class Meta:
                app_label = "contenttypes"

        class ThingAfter(BaseAfter):  # noqa: DJ008
            title = models.CharField(max_length=40)

            class Meta:
                app_label = "contenttypes"

        before = definition.node_definition(ThingBefore, base=BaseBefore)
        after = definition.node_definition(ThingAfter, base=BaseAfter)
        assert before == after
        assert set(before["fields"]) == {"id", "title"}
        record = _recorded(definition.TypeState(mv.NODE, "sample__thing", 1, before))
        assert _problems(definition.TypeState(mv.NODE, "sample__thing", 1, after), record) == []

    @AC[22]
    def test_no_recorded_type_holds_an_inherited_field_and_the_spine_holds_them_all(self) -> None:
        inherited = definition.inherited_field_names(BaseModel)
        assert {"entity", "batch_id", "flip_map"} <= inherited
        states = [state for owned in definition.core_states().values() for state in owned]
        plugin: Any = apps.get_app_config("grid_fixtures")
        states += definition.plugin_states(plugin._manifest)
        nodes = [state for state in states if state.kind == mv.NODE]
        assert len(nodes) > 20
        for state in nodes:
            assert not inherited & set(state.definition["fields"]), state.slug
        assert set(definition.spine_definition()["base_model"]) == inherited


def _recorded_through(state: definition.TypeState, version: int) -> dict[str, Any]:
    record = _recorded(state)
    for later in range(state.version + 1, version + 1):
        definition.append_entry(record, definition.TypeState(state.kind, state.slug, later, state.definition))
    return record


# ---------------------------------------------------------------------------
# A plugin's record, checked by plugin validation
# ---------------------------------------------------------------------------


class TestPluginValidation:
    def _run(self, root: Path) -> Any:
        from tap_plugins.validate.service import _check_model_version_records

        loaded: Any = apps.get_app_config("grid_fixtures")
        manifest = SimpleNamespace(
            slug=loaded._manifest.slug, models=loaded._manifest.models, edges=loaded._manifest.edges, plugin_root=root
        )
        result: Any = SimpleNamespace(checks=[])
        _check_model_version_records(manifest, result)
        return result.checks[-1]

    def _record(self, root: Path) -> dict[str, Any]:
        loaded: Any = apps.get_app_config("grid_fixtures")
        record: dict[str, Any] = {"format": definition.RECORD_FORMAT}
        for state in definition.plugin_states(loaded._manifest):
            definition.append_entry(record, state)
        _write_anywhere(root / definition.record_file_name("grid_fixtures"), record)
        return record

    def test_a_plugin_with_no_record_is_told_and_passes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(definition.REQUIRE_RECORD_ENV, raising=False)
        check = self._run(tmp_path)
        assert check.status == "pass"
        (message,) = check.messages
        # INFO severity, so `--strict` does not promote it; worded as the warning it is.
        assert message.severity == "info" and message.text.startswith("WARNING (not yet a failure")
        assert definition.REQUIRE_RECORD_ENV in message.text and "no entry" in message.text
        assert _TYPE in check.details["unrecorded"] and check.details["required"] is False

    def test_the_switch_makes_a_missing_record_a_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(definition.REQUIRE_RECORD_ENV, "1")
        assert self._run(tmp_path).status == "fail"

    def test_a_plugin_in_step_with_its_record_passes(self, tmp_path: Path) -> None:
        self._record(tmp_path)
        check = self._run(tmp_path)
        assert check.status == "pass" and check.details["unrecorded"] == []

    @AC[4]
    def test_a_recorded_plugin_type_that_changed_at_the_same_version_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._record(tmp_path)
        monkeypatch.setattr(PgNode, "FIELD_CRUD_SCHEMA", {**PgNode.FIELD_CRUD_SCHEMA, "added": {"type": "string"}})
        check = self._run(tmp_path)
        assert check.status == "fail"
        assert any(_TYPE in message.text and "still 1" in message.text for message in check.messages)

    @AC[5]
    def test_an_edited_plugin_record_fails(self, tmp_path: Path) -> None:
        record = self._record(tmp_path)
        record["edges"][LINK][0]["definition"]["endpoint_rules"]["sources"] = ["rewritten"]
        _write_anywhere(tmp_path / definition.record_file_name("grid_fixtures"), record)
        check = self._run(tmp_path)
        assert check.status == "fail"
        assert any(
            LINK in message.text and "changed after it was recorded" in message.text for message in check.messages
        )

    def test_core_guards_do_not_judge_an_installed_plugins_types(self) -> None:
        """An installed plugin with no record cannot fail core's guard: it is not core's to check."""
        from tap.guards.model_version import core_problems

        owners = set(definition.core_states())
        assert not any(owner.startswith("tap_plugin") for owner in owners)
        assert core_problems() == []


class TestReviewRoundTwo:
    """What the second review of the slice found."""

    def test_rows_moved_past_the_code_while_it_waited_are_refused(self) -> None:
        """A process that was behind does not resume when the rows pass what it declares."""
        with mv._writing_applied_version():
            EntityType.objects.create(slug="rr2_ahead", name="rr2", model_version=3)
        mv._pending["rr2_ahead"] = (2, 1)
        with pytest.raises(mv.ModelVersionAhead) as raised:
            mv.refuse_if_pending("rr2_ahead", "a write")
        assert (raised.value.declared, raised.value.applied) == (2, 3)
        assert "rr2_ahead" in mv._pending

    def test_equal_versions_clear_the_refusal(self) -> None:
        with mv._writing_applied_version():
            EntityType.objects.create(slug="rr2_equal", name="rr2", model_version=2)
        mv._pending["rr2_equal"] = (2, 1)
        mv.refuse_if_pending("rr2_equal", "a write")
        assert "rr2_equal" not in mv._pending

    def test_a_new_catalog_row_above_version_1_needs_a_writer(self) -> None:
        with pytest.raises(mv.ModelVersionError):
            EntityType.objects.create(slug="rr2_planted", name="rr2", model_version=2)
        with pytest.raises(mv.ModelVersionError):
            EntityType.objects.bulk_create([EntityType(slug="rr2_bulk", name="rr2", model_version=5)])
        EntityType.objects.create(slug="rr2_first", name="rr2")
        assert not EntityType.objects.filter(slug__in=["rr2_planted", "rr2_bulk"]).exists()

    def test_an_unmigrated_schema_refuses_a_type_declared_above_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no version column every stored row is at version 1, so a type declared at 2 is behind."""
        from django.db import ProgrammingError, connection

        from tap_grid import spine_version

        def missing(**kwargs: Any) -> int | None:
            with connection.cursor() as cursor:
                cursor.execute("select no_such_column from tap_entity_type")
            raise ProgrammingError("unreachable")

        monkeypatch.setattr(spine_version, "recorded_version", missing)
        monkeypatch.setattr(mv, "declared_edge_version", lambda slug: 2 if slug == "PRODUCED_BATCH" else 1)
        monkeypatch.setattr(mv, "applied_version", lambda slug, **kwargs: missing())
        mv._start_incomplete = True
        with pytest.raises(mv.ModelVersionPending):
            mv.refuse_if_pending("PRODUCED_BATCH", "a write")
        assert mv._start_incomplete
        # A type declared at 1 cannot be behind version 1, and the surrounding transaction still works.
        mv.refuse_if_pending("batch", "a write")
        assert EntityType.objects.count() >= 0


class TestReviewRoundThree:
    """What the third review of the slice found."""

    def test_a_catalog_row_above_version_1_is_not_deleted_without_a_writer(self) -> None:
        with mv._writing_applied_version():
            row = EntityType.objects.create(slug="rr3_kept", name="rr3", model_version=2)
        with pytest.raises(mv.ModelVersionError):
            EntityType.objects.filter(slug="rr3_kept").delete()
        with pytest.raises(mv.ModelVersionError):
            row.delete()
        assert EntityType.objects.filter(slug="rr3_kept").exists()
        with mv._writing_applied_version():
            row.delete()
        EntityType.objects.create(slug="rr3_plain", name="rr3")
        EntityType.objects.filter(slug="rr3_plain").delete()

    def test_the_owed_comparison_counts_an_uncatalogued_type_with_rows_as_version_1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A type declared at 2 whose rows exist and whose catalog row does not is behind."""
        EntityType.objects.filter(slug="batch").delete()
        monkeypatch.setattr(mv, "declared_version", lambda cls: 2 if cls.__name__ == "Batch" else 1)
        monkeypatch.setattr(mv, "_holds_rows", lambda slug, kind, using: slug == "batch")
        mv._start_incomplete = True
        with pytest.raises(mv.ModelVersionPending) as raised:
            mv.refuse_if_pending("batch", "a write")
        assert (raised.value.declared, raised.value.applied) == (2, 1)

    def test_an_uncatalogued_type_with_no_rows_is_not_behind(self, monkeypatch: pytest.MonkeyPatch) -> None:
        EntityType.objects.filter(slug="batch").delete()
        monkeypatch.setattr(mv, "declared_version", lambda cls: 2 if cls.__name__ == "Batch" else 1)
        monkeypatch.setattr(mv, "_holds_rows", lambda slug, kind, using: False)
        mv._start_incomplete = True
        mv.refuse_if_pending("batch", "a write")
        assert "batch" not in mv._pending
