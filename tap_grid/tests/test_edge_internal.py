"""Internal-only edge types: bookkeeping the generic verbs and GRIFT refuse.

Spec: ``req-grid-edge-internal`` in ``tap_grid/specs/spec-grid-edge.md`` (Issue# 948 - tap), and
``req-grid-edge-produced-batch-claims-5``, which it holds.

``PRODUCED_BATCH`` is core's internal-only type, so it carries the verb, GRIFT and export tests here.
tap_cares' three lifecycle types are written by the scheduler; their flow is tested in
``tap_cares/tests/test_scheduler.py::TestTheLifecycleEdgesAreInternalOnly``.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ImproperlyConfigured

from tap_auth import sync
from tap_auth.actors import COLLECTOR, get_builtin_actor
from tap_auth.errors import UnguardedOperation
from tap_auth.models import User
from tap_grid.batch import create_batch, imported_by
from tap_grid.caller_context import CallerContext
from tap_grid.constraints import _edge_internal_only_registry, is_internal_edge_type, register_edge_internal_only
from tap_grid.exceptions import InvalidEdgeError
from tap_grid.grift import grift_import
from tap_grid.grift.exporter import SKIP_INTERNAL_ONLY_TYPE, export_grid
from tap_grid.models import Edge, Entity
from tap_grid.service_types import WriteOperation
from tap_grid.services import (
    _create_edge_internal,
    _create_edge_internal_for_test,
    _replace_edge_internal,
    create_edge,
    create_node,
    delete_edge_by_entity,
    delete_node,
    patch_edge,
    replace_edge,
    write_batch,
)
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc
from tap_plugins.base import TapPluginConfig, register_edge_types_from_list
from tap_plugins.manifest import PluginManifestError, _load_edge_file

SPEC = {n: pytest.mark.spec(f"req-grid-edge-internal-{n}") for n in range(1, 8)}
CLAIMS_5 = pytest.mark.spec("req-grid-edge-produced-batch-claims-5")
EDGE_FILE_7 = pytest.mark.spec("req-tap-plugin-manifest-v0-edge-file-7")

BOOKKEEPING = ("PRODUCED_BATCH", "HAS_COLLECTION_JOB", "HAS_FIRED", "TRIGGERED_JOB")


@pytest.fixture
def restored_registry() -> Iterator[None]:
    before = _edge_internal_only_registry.all()
    yield
    _edge_internal_only_registry._reset_for_testing(before)


def _producer(name: str = "producer") -> Entity:
    """A typed node, so it can be deleted through the pipeline."""
    made = create_node("grid_fixtures__node", {"name": name, "description": ""})
    assert made.success, made.errors
    assert made.entity_id is not None
    return Entity.objects.get(pk=made.entity_id)


def _producer_and_batch() -> tuple[Entity, Entity]:
    return _producer(), create_batch(source="t:internal-edge").entity


def _produced(disposition: str = "skipped") -> tuple[Entity, Entity, Edge]:
    producer, batch = _producer_and_batch()
    edge = _create_edge_internal_for_test(producer, batch, "PRODUCED_BATCH", {"disposition": disposition})
    return producer, batch, edge


def _produced_count(batch: Entity) -> int:
    return Edge.objects.filter(edge_type="PRODUCED_BATCH", to_entity_id=batch.id).count()


def _program() -> CallerContext:
    return CallerContext(user=get_builtin_actor(COLLECTOR))


class TestTheDeclaration:
    @SPEC[2]
    def test_the_four_bookkeeping_types_are_internal_only(self) -> None:
        assert [t for t in BOOKKEEPING if not is_internal_edge_type(t)] == []

    @SPEC[1]
    @SPEC[2]
    def test_scheduled_target_and_an_undeclared_type_are_not(self) -> None:
        assert not is_internal_edge_type("SCHEDULED_TARGET")
        assert not is_internal_edge_type("CONSTRAINED_LINK__grid_fixtures")

    @SPEC[1]
    def test_an_edge_types_list_entry_declares_it(self, restored_registry: None) -> None:
        register_edge_types_from_list([{"slug": "T948_INTERNAL", "internal_only": True}, {"slug": "T948_PUBLIC"}])
        assert is_internal_edge_type("T948_INTERNAL")
        assert not is_internal_edge_type("T948_PUBLIC")

    @SPEC[1]
    def test_declaring_a_type_twice_is_a_configuration_error(self, restored_registry: None) -> None:
        register_edge_internal_only("T948_TWICE")
        with pytest.raises(ImproperlyConfigured):
            register_edge_internal_only("T948_TWICE")

    @staticmethod
    def _load(tmp_path: Path, **extra: Any) -> Any:
        data = {"slug": "T948_FILE", "name": "T948", "description": "A test edge type.", **extra}
        edge_file = tmp_path / "edges" / "t948.edge.json"
        edge_file.parent.mkdir(parents=True, exist_ok=True)
        edge_file.write_text(json.dumps(data))
        return _load_edge_file("T948_FILE", "edges/t948.edge.json", edge_file, tmp_path / "tap-plugin.toml")

    @SPEC[1]
    @EDGE_FILE_7
    def test_a_manifest_edge_file_declares_it(self, tmp_path: Path, restored_registry: None) -> None:
        assert self._load(tmp_path).internal_only is False
        entry = self._load(tmp_path, internal_only=True)
        assert entry.internal_only is True

        TapPluginConfig._register_edges_from_manifest(SimpleNamespace(_manifest=SimpleNamespace(edges=[entry])))  # type: ignore[arg-type]
        assert is_internal_edge_type("T948_FILE")

    @EDGE_FILE_7
    def test_a_non_boolean_flag_fails_the_load(self, tmp_path: Path) -> None:
        with pytest.raises(PluginManifestError):
            self._load(tmp_path, internal_only="yes")


@pytest.mark.django_db
class TestTheGenericVerbsRefuse:
    @SPEC[3]
    @CLAIMS_5
    def test_create_edge_refuses_and_writes_nothing(self) -> None:
        producer, batch = _producer_and_batch()
        with pytest.raises(InvalidEdgeError, match="internal-only"):
            create_edge(producer, batch, "PRODUCED_BATCH", {"disposition": "imported"})
        assert _produced_count(batch) == 0

    @SPEC[3]
    @CLAIMS_5
    def test_a_write_batch_create_is_refused(self) -> None:
        """The pipeline refuses on its own, for a caller that skips ``create_edge``."""
        producer, batch = _producer_and_batch()
        op = WriteOperation(
            verb="create_edge",
            from_target=str(producer.id),
            to_target=str(batch.id),
            edge_type="PRODUCED_BATCH",
            payload={"properties": {"disposition": "imported"}},
        )
        result = write_batch([op])
        assert not result.success
        assert [e.code for r in result.results for e in r.errors] == ["unsupported_operation"]
        assert _produced_count(batch) == 0

    @SPEC[3]
    @CLAIMS_5
    @pytest.mark.parametrize("verb", ["patch_edge", "replace_edge", "delete_edge_by_entity"])
    def test_the_pipeline_verbs_refuse_an_existing_edge(self, verb: str) -> None:
        _, batch, edge = _produced("skipped")
        if verb == "patch_edge":
            result = patch_edge(edge.entity_id, {"properties": {"disposition": "imported"}})
        elif verb == "replace_edge":
            result = replace_edge(edge.entity_id, {"properties": {"disposition": "imported"}})
        else:
            result = delete_edge_by_entity(edge.entity_id, reason="operator")

        assert not result.success
        assert [e.code for e in result.errors] == ["unsupported_operation"]
        edge.refresh_from_db()
        edge.entity.refresh_from_db()
        assert edge.properties == {"disposition": "skipped"}
        assert edge.entity.deleted_at is None

    @CLAIMS_5
    def test_no_generic_writer_adds_a_second_imported_holder(self) -> None:
        holder, batch, _ = _produced("imported")
        other = _producer("a second job")
        with pytest.raises(InvalidEdgeError):
            create_edge(other, batch, "PRODUCED_BATCH", {"disposition": "imported"})
        assert imported_by(batch.id) == [str(holder.id)]


@pytest.mark.django_db
class TestGriftRefuses:
    @SPEC[4]
    @CLAIMS_5
    @pytest.mark.parametrize("addressed_by", ["id", "ref"])
    def test_an_import_carrying_one_fails_its_batch_with_nothing_written(self, addressed_by: str) -> None:
        producer, batch = _producer_and_batch()
        envelope: dict[str, Any] = {"entity_type": "edge", "dimensions": {}}
        envelope.update({"ref": "claim"} if addressed_by == "ref" else {"entity_id": str(uuid.uuid4())})
        edge = {
            "entity": envelope,
            "edge": {
                "from_entity_id": str(producer.id),
                "to_entity_id": str(batch.id),
                "edge_type": "PRODUCED_BATCH",
                "properties": {"disposition": "imported"},
            },
        }
        bystander = str(uuid.uuid4())
        node = {
            "entity": {"entity_id": bystander, "entity_type": "grid_fixtures__node", "name": "n", "dimensions": {}},
            "node": {"name": "n", "description": ""},
        }

        result = grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[node], edges=[edge])]))

        assert not result.success
        assert [i.code for i in result.errors] == ["execution_failed"]
        assert "internal-only edge type" in result.errors[0].message
        assert _produced_count(batch) == 0
        assert not Entity.objects.filter(pk=bystander).exists()


@pytest.mark.django_db
class TestTheTrustedInternalPath:
    @SPEC[5]
    def test_it_creates_and_replaces_for_a_program_actor(self) -> None:
        producer, batch = _producer_and_batch()
        edge = _create_edge_internal(
            producer, batch, "PRODUCED_BATCH", {"disposition": "skipped"}, caller_context=_program()
        )
        result = _replace_edge_internal(
            edge.entity_id, {"properties": {"disposition": "imported"}}, caller_context=_program()
        )
        assert result.success, result.errors
        assert Edge.objects.get(pk=edge.pk).properties == {"disposition": "imported"}

    @SPEC[5]
    def test_a_human_actor_cannot_use_it(self) -> None:
        sync.sync_auth()
        admin = User.objects.create_user(username="t948-admin", password="x")
        admin.groups.add(Group.objects.get(name="tap_admin"))
        producer, batch = _producer_and_batch()
        with pytest.raises(UnguardedOperation):
            _create_edge_internal(
                producer, batch, "PRODUCED_BATCH", {"disposition": "imported"}, caller_context=CallerContext(user=admin)
            )
        assert _produced_count(batch) == 0


@pytest.mark.django_db
class TestExportLeavesThemOut:
    @SPEC[6]
    def test_an_internal_only_edge_is_skipped_and_named(self) -> None:
        _, _, edge = _produced("imported")
        export = export_grid()

        exported_types = {e["edge"]["edge_type"] for b in export.document["batches"] for e in b["edges"]}
        assert "PRODUCED_BATCH" not in exported_types
        assert str(edge.entity_id) in export.skipped_sample[SKIP_INTERNAL_ONLY_TYPE]


@pytest.mark.django_db
class TestTheyEndWithTheirEndpoint:
    @SPEC[7]
    def test_deleting_the_producer_ends_its_internal_only_edge(self) -> None:
        producer, _, edge = _produced("imported")
        result = delete_node(producer.id, reason="operator")
        assert result.success, result.errors
        assert Entity.objects.get(pk=edge.entity_id).deleted_at is not None
