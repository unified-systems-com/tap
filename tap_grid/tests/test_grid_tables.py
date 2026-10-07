"""The grid-table classification single source (req-grid-table-classification.sec).

The ORM read backstop (req-tap-auth-orm-read-backstop) and the DB-level search
role grant (req-grid-search-readonly-role.sec) both consume one classification
of "which tables are grid tables" (``GRID_TABLE_ROLE``, declared on the models,
derived by :mod:`tap_grid.grid_tables`); before the 2026-08-11 collapse each
derived its own set and the copies had diverged. These tests pin the
classification contract — who may declare, what the spine is — and the exact
relationship between the two consumer sets, so a future edit to either cannot
silently reopen the gap between "readable at SQL" and "read-guarded".

Classification tests need no database: everything derives from loaded classes.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from django.core.exceptions import ImproperlyConfigured

from tap_grid.grid_tables import (
    classified_models,
    grid_tables,
    history_tables,
    read_guarded_tables,
    search_role_grant_tables,
    spine_models,
)
from tap_grid.models import BaseModel, Dimension, Edge, Entity, EntityType


class TestClassificationDeclaration:
    """req-grid-table-classification.sec-1: declared on the model, inherited for domain."""

    def test_basemodel_declares_domain_once(self):
        assert BaseModel.__dict__["GRID_TABLE_ROLE"] == "domain"

    def test_concrete_subclasses_inherit_domain_without_declaring(self):
        for model in (Edge, Dimension):
            assert model.GRID_TABLE_ROLE == "domain"
            assert "GRID_TABLE_ROLE" not in model.__dict__

    def test_spine_set_is_exactly_entity_and_entity_type(self):
        # req-grid-table-classification.sec-5: changing the spine set is a
        # deliberate, reviewed spec+test change — this is the pin.
        assert spine_models() == {Entity, EntityType}

    def test_every_classified_model_is_domain_or_spine(self):
        assert set(classified_models().values()) <= {"domain", "spine"}


class TestSubclassCannotDeclare:
    """req-grid-table-classification.sec-3: a BaseModel can never claim (or restate) a role."""

    def test_subclass_declaring_spine_fails_at_class_definition(self):
        with pytest.raises(ImproperlyConfigured, match="GRID_TABLE_ROLE"):

            class _SelfPromoting(BaseModel):
                GRID_TABLE_ROLE: ClassVar[str] = "spine"
                ENTITY_TYPE: ClassVar[str] = "test_self_promoting_xyz"
                FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {}

                class Meta(BaseModel.Meta):
                    managed = False

    def test_subclass_declaring_redundant_domain_also_fails(self):
        # Domain-ness is inherited, not declared: a declarable value in a
        # subclass body is an editable security surface, so even the redundant
        # form is rejected.
        with pytest.raises(ImproperlyConfigured, match="GRID_TABLE_ROLE"):

            class _Redundant(BaseModel):
                GRID_TABLE_ROLE: ClassVar[str] = "domain"
                ENTITY_TYPE: ClassVar[str] = "test_redundant_role_xyz"
                FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {}

                class Meta(BaseModel.Meta):
                    managed = False


class TestForeignDeclarerFailsClosed:
    """req-grid-table-classification.sec-4: explicit classification is core-only."""

    def test_non_basemodel_foreign_declarer_raises_and_flaws(self, caplog, monkeypatch):
        # A plain (non-BaseModel) model claiming spine — the door
        # BaseModel.__init_subclass__ cannot see. Built as a plain class with a
        # _meta stub and injected into the scan, so the real app registry is
        # never polluted by a throwaway Django model.
        class _MetaStub:
            label = "fake_plugin._Impostor"
            db_table = "fake_plugin_impostor"

        class _Impostor:
            GRID_TABLE_ROLE = "spine"
            _meta = _MetaStub()

        import logging

        from django.apps import apps as django_apps

        import tap_grid.grid_tables as gt

        real_get_models = django_apps.get_models
        monkeypatch.setattr(django_apps, "get_models", lambda *a, **k: [*real_get_models(), _Impostor])

        with caplog.at_level(logging.CRITICAL):
            with pytest.raises(ImproperlyConfigured, match="classify itself"):
                gt.classified_models()
        flaws = [
            r
            for r in caplog.records
            if getattr(r, "message_data", {}).get("invariant_id") == "grid_table_classification_foreign_declarer"
        ]
        assert flaws, "a foreign GRID_TABLE_ROLE declarer must emit a security Flaw"
        assert flaws[-1].message_data["flaw_tags"] == ["security"]

    def test_unknown_role_value_fails_closed(self, monkeypatch):
        # An unknown value on a sanctioned declarer chain is still rejected —
        # simulated via a class whose declarer IS sanctioned (subclass of
        # Entity-like stub is impossible without Django, so patch the
        # sanctioned set to include the stub's declarer).
        class _MetaStub:
            label = "tap_grid._Typo"
            db_table = "tap_grid_typo"

        class _Typo:
            GRID_TABLE_ROLE = "spline"  # sic
            _meta = _MetaStub()

        from django.apps import apps as django_apps

        import tap_grid.grid_tables as gt

        real_get_models = django_apps.get_models
        monkeypatch.setattr(django_apps, "get_models", lambda *a, **k: [*real_get_models(), _Typo])
        monkeypatch.setattr(gt, "_sanctioned_declarers", lambda: (BaseModel, Entity, EntityType, _Typo))
        with pytest.raises(ImproperlyConfigured, match="unknown GRID_TABLE_ROLE"):
            gt.classified_models()


class TestConsumerSetRelationship:
    """req-grid-table-classification.sec-5: the one deliberate asymmetry, pinned."""

    def test_grant_set_is_exactly_guarded_set_minus_history(self):
        assert search_role_grant_tables() == read_guarded_tables() - history_tables()
        assert grid_tables() <= read_guarded_tables()

    def test_entity_is_granted_and_read_guarded(self):
        """Issue# 963 - tap: the spine's read-guard exemption is gone."""
        entity_table = Entity._meta.db_table
        assert entity_table in search_role_grant_tables()
        assert entity_table in read_guarded_tables()

    def test_every_classified_domain_table_has_its_history_guarded(self):
        """Each BaseModel's simple_history table is read-guarded, and never granted to search."""
        from django.apps import apps

        expected = {
            model.history.model._meta.db_table
            for model in apps.get_models()
            if issubclass(model, BaseModel) and not model._meta.abstract
        }
        assert expected
        assert expected == history_tables()
        assert expected <= read_guarded_tables()
        assert not expected & search_role_grant_tables()

    def test_entity_type_catalog_is_in_both_sets(self):
        catalog_table = EntityType._meta.db_table
        assert catalog_table in read_guarded_tables()
        assert catalog_table in search_role_grant_tables()

    def test_non_grid_tables_are_never_included(self):
        # The non-grid table the seed vuln reached; must be in no consumer set.
        for tables in (grid_tables(), read_guarded_tables(), search_role_grant_tables()):
            assert "tap_user" not in tables

    def test_every_concrete_basemodel_table_is_classified_domain(self):
        from django.apps import apps

        expected = {
            model._meta.db_table
            for model in apps.get_models()
            if issubclass(model, BaseModel) and not model._meta.abstract
        }
        domain_tables = {m._meta.db_table for m, role in classified_models().items() if role == "domain"}
        assert domain_tables == expected


class TestConsumersUseTheSharedSource:
    """req-grid-table-classification.sec-2: no consumer derives its own set."""

    def test_read_guard_regex_covers_exactly_the_guarded_set(self):
        from tap_grid.read_guard import _guarded_regex

        regex = _guarded_regex()
        for table in read_guarded_tables():
            assert regex.search(f'SELECT * FROM "{table}"'), f"guarded table {table} not matched"
        assert regex.search(f'SELECT * FROM "{Entity._meta.db_table}"')
        assert not regex.search('SELECT * FROM "tap_user"')

    def test_search_role_module_returns_the_shared_grant_set(self):
        from tap_grid import search_role

        assert set(search_role.search_role_grant_tables()) == search_role_grant_tables()


@pytest.mark.django_db(transaction=True)
class TestGrantExistenceReconcile:
    """req-grid-table-classification.sec-6: grant only what exists, loudly skip the rest."""

    def test_declared_but_absent_table_is_skipped_with_loud_warning(self, caplog, settings):
        import logging

        from django.db import connections

        from tap_grid.search_role import provision_search_role

        conn = connections["default"]
        phantom = "tap_zzz_classified_but_never_migrated"
        with caplog.at_level(logging.WARNING):
            granted = provision_search_role(
                conn,
                password=settings.SEARCH_READONLY_PASSWORD,
                database=conn.settings_dict["NAME"],
                gucs=settings.SEARCH_ROLE_GUCS,
                tables=[Entity._meta.db_table, phantom],
            )
        assert granted == [Entity._meta.db_table]
        skip_logs = [r for r in caplog.records if phantom in r.getMessage()]
        assert skip_logs, "the skipped table must be named in a WARNING"
        assert skip_logs[-1].levelno == logging.WARNING
