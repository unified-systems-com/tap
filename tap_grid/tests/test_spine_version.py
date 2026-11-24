"""The spine's own version: authored in core, recorded on the grid, guarded like a type's.

Covers ``req-grid-entity-spine-version`` rules 1, 2 and 7 (spec-grid-entity.md). The record is the
one row of ``SpineVersion``; ``record_after_migrate`` is the ``post_migrate`` handler that writes
it and ``refuse_newer_database`` is the check ``tap_grid``'s ``ready()`` makes at start.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models.signals import post_migrate

from tap_grid import model_definition as definition
from tap_grid import model_version as mv
from tap_grid import spine_version
from tap_grid.models import BaseModel, Edge, Entity, SpineVersion

AC = {n: pytest.mark.spec(f"req-grid-entity-spine-version-{n}") for n in (1, 2, 6)}

pytestmark = pytest.mark.django_db


class TestTheRecord:
    @AC[1]
    def test_a_migrated_database_records_the_version_core_declares(self) -> None:
        """The test database was built by ``migrate``; its record is what that left."""
        # Version 2 since the base-model release (Issue# 1288 - tap): the typed batch_id removed and the
        # spine copies added (req-grid-entity-spine-copies).
        assert spine_version.SPINE_VERSION == 2
        assert spine_version.recorded_version() == spine_version.SPINE_VERSION
        assert SpineVersion.objects.count() == 1

    @AC[1]
    def test_applying_migrations_writes_it(self) -> None:
        SpineVersion.objects.all().delete()
        assert spine_version.recorded_version() is None
        call_command("migrate", verbosity=0, interactive=False)
        assert spine_version.recorded_version() == spine_version.SPINE_VERSION

    @AC[1]
    def test_the_handler_is_connected_for_tap_grid(self) -> None:
        config = apps.get_app_config("tap_grid")
        SpineVersion.objects.all().delete()
        post_migrate.send(sender=config, app_config=config, using="default", plan=[], verbosity=0, interactive=False)
        assert spine_version.recorded_version() == spine_version.SPINE_VERSION

    def test_a_flush_puts_the_record_back(self) -> None:
        """``flush`` empties every table and sends post_migrate with no plan."""
        SpineVersion.objects.all().delete()
        spine_version.record_after_migrate(sender=None, using="default", plan=None)
        assert spine_version.recorded_version() == spine_version.SPINE_VERSION

    def test_a_database_missing_a_tap_grid_migration_is_not_recorded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A partial or reversed migrate: the database is not at this code's spine, so nothing is claimed."""
        SpineVersion.objects.all().delete()
        monkeypatch.setattr(spine_version, "_schema_is_current", lambda using: False)
        spine_version.record_after_migrate(sender=None, using="default", plan=[])
        assert spine_version.recorded_version() is None

    def test_the_schema_test_reads_the_recorded_migrations(self) -> None:
        from django.db.migrations.recorder import MigrationRecorder

        assert spine_version._schema_is_current("default")
        latest = MigrationRecorder.Migration.objects.filter(app="tap_grid").order_by("-name").first()
        assert latest is not None and latest.name == "0023_spine_copies"
        with transaction.atomic():
            latest.delete()
            assert not spine_version._schema_is_current("default")
            transaction.set_rollback(True)

    def test_a_record_ahead_of_the_code_is_left_alone(self) -> None:
        SpineVersion.objects.update(version=spine_version.SPINE_VERSION + 1)
        spine_version.record_after_migrate(sender=None, using="default", plan=[])
        assert spine_version.recorded_version() == spine_version.SPINE_VERSION + 1

    def test_the_grid_holds_one_record(self) -> None:
        with pytest.raises(IntegrityError), transaction.atomic():
            SpineVersion.objects.create(id=2, version=1)


class TestANewerDatabase:
    @AC[2]
    def test_code_at_version_1_refuses_a_database_at_version_2(self) -> None:
        # Relative to what core declares now (2 since Issue# 1288 - tap): a record one ahead is refused.
        declared = spine_version.SPINE_VERSION
        SpineVersion.objects.update(version=declared + 1)
        with pytest.raises(spine_version.SpineVersionAhead) as raised:
            spine_version.refuse_newer_database()
        assert (raised.value.declared, raised.value.recorded) == (declared, declared + 1)
        assert f"spine version {declared + 1}" in str(raised.value) and f"spine version {declared}" in str(raised.value)
        # ready() raises it, and Django stops a process whose app cannot be made ready.
        assert isinstance(raised.value, ImproperlyConfigured)

    @AC[2]
    def test_the_start_of_tap_grid_makes_the_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``ready()`` ends in the version checks, and they reach the spine before the catalog."""
        import inspect

        from tap_grid.apps import TapCoreConfig

        assert inspect.getsource(TapCoreConfig.ready).rstrip().endswith("self.compare_versions_at_start()")
        reached: list[str] = []
        monkeypatch.setattr("tap_grid.model_version.register_core_types", lambda: reached.append("catalog"))
        config: Any = apps.get_app_config("tap_grid")
        config.compare_versions_at_start()
        assert reached == ["catalog"]

        SpineVersion.objects.update(version=spine_version.SPINE_VERSION + 1)
        with pytest.raises(spine_version.SpineVersionAhead):
            config.compare_versions_at_start()
        assert reached == ["catalog"]

    def test_an_equal_or_older_record_and_an_absent_one_pass(self) -> None:
        spine_version.refuse_newer_database()
        SpineVersion.objects.all().delete()
        spine_version.refuse_newer_database()

    def test_a_database_with_no_record_table_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from django.db import ProgrammingError

        def missing(**kwargs: Any) -> int | None:
            raise ProgrammingError('relation "tap_spine_version" does not exist')

        monkeypatch.setattr(spine_version, "recorded_version", missing)
        spine_version.refuse_newer_database()


class TestTheSpineDefinition:
    def test_it_covers_the_entity_row_the_inherited_columns_and_the_edge_table(self) -> None:
        spine = definition.spine_definition()
        assert set(spine["entity"]["fields"]) == {field.name for field in Entity._meta.concrete_fields}
        inherited = definition.inherited_field_names(BaseModel)
        assert set(spine["base_model"]) == inherited
        own = {field.name for field in Edge._meta.concrete_fields} - inherited
        assert set(spine["edge"]["fields"]) == own and {"edge_type", "from_entity", "to_entity", "properties"} <= own
        assert any("entity_collected_pair" in str(constraint) for constraint in spine["entity"]["constraints"])

    def test_a_change_to_the_spine_without_its_version_fails_the_guard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap.guards.model_version import ModelVersionGuard

        ModelVersionGuard().check()
        moved = copy.deepcopy(definition.spine_definition())
        moved["entity"]["fields"]["added_column"] = {"type": "CharField", "null": True, "max_length": 8}
        monkeypatch.setattr(definition, "spine_definition", lambda: moved)
        expected = f"the spine.*entity.fields.added_column added.*still {spine_version.SPINE_VERSION}"
        with pytest.raises(AssertionError, match=expected):
            ModelVersionGuard().check()

    @AC[6]
    def test_the_spine_and_the_types_move_independently(self) -> None:
        """Raising the spine's version changes no type's entry, and raising a type's changes not the spine's."""
        owned = definition.core_states()["tap_grid"]
        spine = next(state for state in owned if state.kind == definition.SPINE)
        types = [state for state in owned if state.kind != definition.SPINE]
        record: dict[str, Any] = {"format": definition.RECORD_FORMAT}
        for state in owned:
            definition.append_entry(record, state)
        before = copy.deepcopy(record)

        # The spine moves: a new column and the next version.
        moved = copy.deepcopy(spine.definition)
        moved["entity"]["fields"]["added_column"] = {"type": "CharField", "null": True}
        spine_2 = definition.TypeState(definition.SPINE, definition.SPINE, spine.version + 1, moved)
        assert definition.append_entry(record, spine_2)
        assert record["nodes"] == before["nodes"] and record["edges"] == before["edges"]
        for state in types:
            assert definition.type_problems(state, definition.entries_for(record, state)) == []

        # A type moves: the spine's entries are as they were, and the spine is still in step.
        keystone = next(state for state in types if state.slug == "keystone")
        keystone_2 = definition.TypeState(mv.NODE, "keystone", 2, {**keystone.definition, "key": ["name"]})
        spine_entries = copy.deepcopy(record[definition.SPINE])
        assert definition.append_entry(record, keystone_2)
        assert record[definition.SPINE] == spine_entries
        assert definition.type_problems(spine_2, definition.entries_for(record, spine_2)) == []

    @AC[6]
    def test_no_type_names_the_spine_version_and_the_spine_names_no_type(self) -> None:
        states = [state for owned in definition.core_states().values() for state in owned]
        spine = next(state for state in states if state.kind == definition.SPINE)
        for state in states:
            if state.kind != definition.SPINE:
                assert "spine" not in str(state.definition).lower(), state.slug
        assert set(spine.definition) == {"entity", "base_model", "edge"}
