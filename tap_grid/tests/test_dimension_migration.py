"""Migration 0012 re-keys stored dimensions by node id (req-grid-dimension-reference-0), and the
importer's replace and trust rules (req-grid-dimension-reference-6, -7)."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any

import pytest
from django.apps import apps
from django.db import connection

from tap_grid.models import Dimension, Entity

META = "01a1d14c-d80b-725d-8002-eb0b3e272f1d"  # tap.meta, core's seed
GRAPH = "01a1d14c-d80b-725d-8002-eb0c8e7f34c6"  # tap.graph, core's seed

migration = importlib.import_module("tap_grid.migrations.0012_dimensions_keyed_by_node")


def _editor() -> Any:
    return SimpleNamespace(connection=connection)


def _set_raw(entity_id: Any, dims: dict[str, Any]) -> None:
    from tap_grid.write_guard import unguarded_write

    with unguarded_write():
        Entity.objects.filter(pk=entity_id).update(dimensions=dims)


@pytest.mark.django_db
@pytest.mark.spec("req-grid-dimension-reference-0")
class TestTheMigration:
    def test_a_name_keyed_row_is_re_keyed_with_provenance(self) -> None:
        node = Dimension.objects.create(name="tap.test.migrated")
        _set_raw(node.entity_id, {"tap.meta": "dimension", "tap.graph": "web"})
        migration.forwards(apps, _editor())
        stored = Entity.objects.get(pk=node.entity_id).dimensions
        # tap.meta = dimension is Dimension's own default; tap.graph = web is not, so it is declared.
        assert stored == {META: {"v": "dimension", "src": "default"}, GRAPH: {"v": "web", "src": "declared"}}

    def test_it_is_idempotent(self) -> None:
        node = Dimension.objects.create(name="tap.test.twice-migrated")
        migration.forwards(apps, _editor())
        before = Entity.objects.get(pk=node.entity_id).dimensions
        migration.forwards(apps, _editor())
        assert Entity.objects.get(pk=node.entity_id).dimensions == before

    def test_an_undeclared_key_stops_it_before_anything_is_written(self) -> None:
        node = Dimension.objects.create(name="tap.test.undeclared")
        _set_raw(node.entity_id, {"tap.meta": "dimension", "tap.test.never-seeded": "x"})
        with pytest.raises(RuntimeError, match="tap.test.never-seeded.*dimension"):
            migration.forwards(apps, _editor())
        assert Entity.objects.get(pk=node.entity_id).dimensions == {"tap.meta": "dimension", "tap.test.never-seeded": "x"}

    def test_backwards_restores_names_and_plain_values(self) -> None:
        node = Dimension.objects.create(name="tap.test.reversed")
        migration.backwards(apps, _editor())
        assert Entity.objects.get(pk=node.entity_id).dimensions == {"tap.meta": "dimension"}


def _doc(entity_id: str, dims: dict[str, Any], name: str = "replace-me") -> dict[str, Any]:
    import uuid

    from tap_grid.tests.test_grift import _batch_container, _minimal_doc

    doc = _minimal_doc([_batch_container(str(uuid.uuid7()))])
    batch = doc["batches"][0]
    batch["nodes"] = [
        {
            "entity": {"entity_id": entity_id, "entity_type": "dimension", "name": name, "dimensions": dims},
            "node": {"name": name, "description": "d"},
        }
    ]
    batch["edges"] = []
    return doc


@pytest.mark.django_db
@pytest.mark.spec("req-grid-dimension-reference-7")
class TestReplaceIsAuthoritative:
    def test_an_empty_map_on_a_replace_clears_the_callers_values_and_the_defaults_return(self) -> None:
        """Issue# 608 - tap: {} on a replace used to be skipped. Q59 D6: the type's defaults return."""
        import uuid

        from tap_grid.grift import grift_import

        ident = str(uuid.uuid7())
        assert grift_import(_doc(ident, {"tap.graph": "web"})).success
        assert Entity.objects.get(pk=ident).dimensions[GRAPH]["v"] == "web"
        second = _doc(ident, {})
        second["batches"][0]["batch_entity"]["entity_id"] = str(uuid.uuid7())
        assert grift_import(second).success
        assert Entity.objects.get(pk=ident).dimensions == {META: {"v": "dimension", "src": "default"}}

    def test_a_collector_run_carrying_only_its_stamped_keys_keeps_the_type_defaults(self) -> None:
        """Q59 D6: a collector's envelope carries only the keys it stamps; the replace must not wipe
        the type's defaults on every run."""
        import uuid

        from tap_grid.grift import grift_import

        ident = str(uuid.uuid7())
        stamped = {"tap.graph": {"v": "web", "src": "derived"}}
        assert grift_import(_doc(ident, stamped), trusted_derivation=True).success
        for _run in range(2):
            again = _doc(ident, stamped)
            again["batches"][0]["batch_entity"]["entity_id"] = str(uuid.uuid7())
            assert grift_import(again, trusted_derivation=True).success
            assert Entity.objects.get(pk=ident).dimensions == {
                META: {"v": "dimension", "src": "default"},
                GRAPH: {"v": "web", "src": "derived"},
            }


@pytest.mark.django_db
@pytest.mark.spec("req-grid-dimension-reference-6")
class TestTrustedDerivation:
    def _import(self, trusted: bool) -> dict[str, Any]:
        import uuid

        from tap_grid.grift import grift_import

        ident = str(uuid.uuid7())
        result = grift_import(_doc(ident, {"tap.graph": {"v": "web", "src": "derived"}}), trusted_derivation=trusted)
        assert result.success, result.errors
        stored: dict[str, Any] = Entity.objects.get(pk=ident).dimensions[GRAPH]
        return stored

    def test_a_portable_import_resets_derived_to_declared(self) -> None:
        assert self._import(trusted=False) == {"v": "web", "src": "declared"}

    def test_the_collector_runner_keeps_derived(self) -> None:
        assert self._import(trusted=True) == {"v": "web", "src": "derived"}

    def test_a_documents_src_default_entries_are_dropped_and_re_stamped(self) -> None:
        """Q59 D4: the grid stamps its own defaults, so a document's default entries are dropped."""
        import uuid

        from tap_grid.grift import grift_import

        ident = str(uuid.uuid7())
        exported_shape = {
            META: {"v": "dimension", "src": "default"},
            "tap.graph": {"v": "web", "src": "default"},  # not a Dimension default: dropped, not re-stamped
        }
        result = grift_import(_doc(ident, exported_shape))
        assert result.success, result.errors
        assert Entity.objects.get(pk=ident).dimensions == {META: {"v": "dimension", "src": "default"}}

    def test_an_export_of_a_defaulted_type_re_imports_into_an_empty_grid(self) -> None:
        """Q59 D4 round trip: a Dimension node carries its type default (tap.meta, src default)."""
        from tap_grid.grift.exporter import export_grid
        from tap_grid.grift import grift_import
        from tap_grid.tests.test_grift_export import _empty_the_grid

        node = Dimension.objects.create(name="tap.test.round-trip")
        before = Entity.objects.get(pk=node.entity_id).dimensions
        assert before == {META: {"v": "dimension", "src": "default"}}
        from django.utils import timezone

        export = export_grid(captured_at=timezone.now(), name="defaulted round trip")
        assert export.issues == [], export.issues
        _empty_the_grid()
        result = grift_import(export.document, dangling_edge_mode="strict")
        assert result.success, [(i.code, i.path, i.message) for i in result.errors]
        assert Entity.objects.get(pk=node.entity_id).dimensions == before

    def test_an_undeclared_dimension_fails_preflight(self) -> None:
        import uuid

        from tap_grid.grift import grift_import

        result = grift_import(_doc(str(uuid.uuid7()), {"tap.test.never-seeded": "x"}))
        assert not result.success
        assert any("tap.test.never-seeded" in str(e) for e in result.errors)
