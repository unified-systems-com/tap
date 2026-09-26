"""Retired rows travel, subsets select exactly, and a batch declares what it carries.

req-grift-export, req-grift-retirement, req-grift-contents and
req-grid-import-grift-retired. The round trip is the done-test: export a grid holding
tombstones, import it into an empty grid, and the second grid holds the same tombstones
with the first grid's retirement data kept beside the import's own record. A re-export
from the second grid carries the first grid's retirement, not the import's.
"""

from __future__ import annotations

import copy
import json
import uuid
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from tap_grid.caller_context import CallerContext, get_caller_context
from tap_grid.grift import grift_import
from tap_grid.grift.exporter import SKIP_EDGE_ENDPOINT_NOT_EXPORTED, SKIP_NOT_SELECTED, ExportSelection, export_grid
from tap_grid.models import Batch, BatchEvent, Edge, Entity
from tap_grid.registry import get_model_class
from tap_grid.service_types import WriteOperation
from tap_grid.services import create_edge, delete_edge_by_entity, delete_node, write_batch

SOURCE = "grid_fixtures__constrained_source"
TARGET = "grid_fixtures__constrained_target"
CONSTRAINED = "CONSTRAINED_LINK__grid_fixtures"
ALT = "ALT_LINK__grid_fixtures"
NESTING = "NESTING_LINK__grid_fixtures"


def _node(entity_type: str, name: str, dimensions: dict[str, str] | None = None, batch_name: str = "") -> uuid.UUID:
    op = WriteOperation(verb="create_node", type_slug=entity_type, payload={"name": name}, dimensions=dimensions or {})
    if not batch_name:
        result = write_batch([op])
    else:
        # A named batch must be one this call mints, so the write carries the ambient
        # actor but no ambient batch scope an earlier write in the test left behind.
        ambient = get_caller_context()
        actor = CallerContext(user=ambient.user if ambient else None)
        result = write_batch([op], caller_context=actor, batch_name=batch_name)
    assert result.success, result.errors
    return uuid.UUID(str(result.results[0].entity_id))


def _edge(source: uuid.UUID, target: uuid.UUID, edge_type: str) -> uuid.UUID:
    edge = create_edge(Entity.objects.get(pk=source), Entity.objects.get(pk=target), edge_type)
    return uuid.UUID(str(edge.entity_id))


def _empty_the_grid() -> None:
    """Hard-reset to an empty grid, the import target (no service verb destroys a spine)."""
    Entity.objects.all().delete()
    assert Entity.objects.count() == 0


def _batch(export: Any) -> dict[str, Any]:
    batch: dict[str, Any] = export.document["batches"][0]
    return batch


def _objects(export: Any) -> dict[str, dict[str, Any]]:
    batch = _batch(export)
    return {obj["entity"]["entity_id"]: obj for obj in batch["nodes"] + batch["edges"]}


def _flip(entity_id: uuid.UUID) -> dict[str, Any]:
    entity_type = Entity.objects.get(pk=entity_id).entity_type
    model = Edge if entity_type == Edge.ENTITY_TYPE else get_model_class(entity_type)
    return dict(model.all_objects.get(entity_id=entity_id).flip_map or {})  # type: ignore[attr-defined]


@pytest.fixture
def grid() -> dict[str, Any]:
    """A grid with three kinds of retirement.

    beta is retired with a reason and metadata; gamma is retired with the default
    reason, which ends its two edges by the endpoint rule (no event of their own); the
    alpha->delta edge is retired on its own with a reason.
    """
    alpha = _node(SOURCE, "alpha", {"dcom": "design"})
    beta = _node(SOURCE, "beta", {"dcom": "design"})
    gamma = _node(TARGET, "gamma", {"dcom": "build"})
    delta = _node(TARGET, "delta")
    ag = _edge(alpha, gamma, CONSTRAINED)
    ad = _edge(alpha, delta, ALT)
    gd = _edge(gamma, delta, NESTING)

    beta_retired = delete_node(beta, reason="operator", metadata={"ticket": "T-1"})
    assert beta_retired.success, beta_retired.errors
    gamma_retired = delete_node(gamma)
    assert gamma_retired.success, gamma_retired.errors
    ad_retired = delete_edge_by_entity(ad, reason="resolved", metadata={"note": "moved"})
    assert ad_retired.success, ad_retired.errors
    return {
        "ids": {"alpha": alpha, "beta": beta, "gamma": gamma, "delta": delta, "ag": ag, "ad": ad, "gd": gd},
        "batches": {
            "beta": str(beta_retired.batch_id),
            "gamma": str(gamma_retired.batch_id),
            "ad": str(ad_retired.batch_id),
        },
    }


@pytest.mark.django_db
class TestEverythingByDefault:
    @pytest.mark.spec("req-grift-export-1")
    def test_retired_nodes_and_edges_are_exported_and_live_ones_carry_no_block(self, grid: dict[str, Any]) -> None:
        export = export_grid()
        assert export.issues == [], [(i.code, i.path, i.message) for i in export.issues]
        objects = _objects(export)
        ids = grid["ids"]
        assert {str(v) for v in ids.values()} <= set(objects)
        retired = {name for name, entity_id in ids.items() if "retirement" in objects[str(entity_id)]}
        assert retired == {"beta", "gamma", "ag", "ad", "gd"}
        assert "tombstoned" not in export.skipped

    @pytest.mark.spec("req-grift-export-2")
    @pytest.mark.spec("req-grift-retirement-3")
    def test_each_block_names_the_source_grids_retirement(self, grid: dict[str, Any]) -> None:
        objects = _objects(export_grid())
        ids, batches = grid["ids"], grid["batches"]

        beta = objects[str(ids["beta"])]["retirement"]
        assert beta["batch_id"] == batches["beta"] == _flip(ids["beta"])["deleted_at"]
        assert beta["reason"] == "operator"
        assert beta["metadata"] == {"ticket": "T-1"}
        retired_at = Entity.objects.get(pk=ids["beta"]).deleted_at
        assert retired_at is not None
        assert beta["retired_at"] == retired_at.isoformat()

        assert objects[str(ids["gamma"])]["retirement"]["reason"] == "unspecified"
        ad = objects[str(ids["ad"])]["retirement"]
        assert (ad["batch_id"], ad["reason"], ad["metadata"]) == (batches["ad"], "resolved", {"note": "moved"})

        # Ended by gamma's plain delete: the retiring batch is known, but the edge has no
        # retirement event of its own, so reason and metadata are null and empty.
        ag = objects[str(ids["ag"])]["retirement"]
        assert (ag["batch_id"], ag["reason"], ag["metadata"]) == (batches["gamma"], None, {})

    @pytest.mark.spec("req-grift-export-3")
    @pytest.mark.spec("req-grift-contents-1")
    def test_the_batch_declares_its_contents(self, grid: dict[str, Any]) -> None:
        export = export_grid()
        assert _batch(export)["contents"] == {
            "tombstones": {"included": True, "nodes": 2, "edges": 3},
            "history": {"included": False},
            "flip": {"included": False},
        }
        assert export.retired_counts == {"nodes": 2, "edges": 3}


@pytest.mark.django_db
class TestRoundTrip:
    @pytest.mark.spec("req-grid-import-grift-retired-1")
    @pytest.mark.spec("req-grid-import-grift-retired-4")
    def test_an_empty_grid_receives_the_same_tombstones(self, grid: dict[str, Any]) -> None:
        export = export_grid()
        _empty_the_grid()
        result = grift_import(export.document, dangling_edge_mode="strict")
        assert result.success, [(i.code, i.path, i.message) for i in result.errors]
        assert (result.counts.nodes_retired, result.counts.edges_retired) == (2, 3)

        ids = grid["ids"]
        for name in ("beta", "gamma", "ag", "ad", "gd"):
            assert Entity.objects.get(pk=ids[name]).deleted_at is not None, name
        for name in ("alpha", "delta"):
            assert Entity.objects.get(pk=ids[name]).deleted_at is None, name

    @pytest.mark.spec("req-grid-import-grift-retired-2")
    @pytest.mark.spec("req-grift-retirement-2")
    def test_the_carried_block_is_data_beside_the_imports_own_provenance(self, grid: dict[str, Any]) -> None:
        export = export_grid()
        original = {k: v["retirement"] for k, v in _objects(export).items() if "retirement" in v}
        _empty_the_grid()
        assert grift_import(export.document).success

        import_batch = export.batch_entity_id
        for entity_id, block in original.items():
            # The import retired the row, so the import's batch is the FLIP entry ...
            assert _flip(uuid.UUID(entity_id))["deleted_at"] == import_batch
            assert block["batch_id"] != import_batch
            # ... and the source grid's block rides on the import's own event, unchanged.
            event = BatchEvent.objects.get(entity_id=entity_id, event_type__in=("delete", "unlink"))
            assert str(event.batch.entity_id) == import_batch
            assert event.metadata["reason"] == "grift_import"
            assert event.metadata["grift_operation"] == "retire"
            assert event.metadata["original_retirement"] == block

    @pytest.mark.spec("req-grift-export-2")
    def test_a_re_export_carries_the_first_grids_retirement(self, grid: dict[str, Any]) -> None:
        first = export_grid()
        original = {k: v["retirement"] for k, v in _objects(first).items() if "retirement" in v}
        _empty_the_grid()
        assert grift_import(first.document).success

        second = export_grid()
        carried = {k: v["retirement"] for k, v in _objects(second).items() if "retirement" in v}
        assert carried == original
        assert _batch(second)["contents"]["tombstones"] == _batch(first)["contents"]["tombstones"]

    @pytest.mark.spec("req-grid-import-grift-retired-3")
    def test_an_existing_tombstone_stands(self, grid: dict[str, Any]) -> None:
        export = export_grid()
        # A second copy under a new batch id, imported into the grid that already holds
        # the tombstones: nothing is replaced and nothing is retired twice.
        document = copy.deepcopy(export.document)
        document["batches"][0]["batch_entity"]["entity_id"] = str(uuid.uuid7())
        beta = grid["ids"]["beta"]
        version = Entity.objects.get(pk=beta).version
        result = grift_import(document)
        assert result.success, [(i.code, i.path, i.message) for i in result.errors]
        assert result.counts.retirements_skipped == 5
        assert (result.counts.nodes_retired, result.counts.edges_retired) == (0, 0)
        assert {w.code for w in result.warnings} >= {"retired_target_already_tombstoned"}
        assert Entity.objects.get(pk=beta).version == version
        assert _flip(beta)["deleted_at"] == grid["batches"]["beta"]


@pytest.mark.django_db
class TestContentsDeclaration:
    def _codes(self, document: dict[str, Any]) -> set[str]:
        _empty_the_grid()
        result = grift_import(document)
        assert not result.success
        assert Entity.objects.count() == 0
        return {issue.code for issue in result.errors}

    @pytest.mark.spec("req-grift-contents-2")
    def test_a_miscounted_declaration_is_refused(self, grid: dict[str, Any]) -> None:
        document = copy.deepcopy(export_grid().document)
        document["batches"][0]["contents"]["tombstones"]["edges"] = 2
        assert "contents_mismatch" in self._codes(document)

    @pytest.mark.spec("req-grift-contents-2")
    def test_declaring_no_tombstones_while_carrying_them_is_refused(self, grid: dict[str, Any]) -> None:
        document = copy.deepcopy(export_grid().document)
        document["batches"][0]["contents"]["tombstones"] = {"included": False, "nodes": 0, "edges": 0}
        assert "contents_mismatch" in self._codes(document)

    @pytest.mark.spec("req-grift-contents-3")
    def test_an_aspect_this_importer_does_not_accept_is_refused(self, grid: dict[str, Any]) -> None:
        document = copy.deepcopy(export_grid().document)
        document["batches"][0]["contents"]["history"] = {"included": True}
        assert "unsupported_contents" in self._codes(document)

    @pytest.mark.spec("req-grift-contents-3")
    def test_an_unknown_aspect_declared_absent_is_accepted(self, grid: dict[str, Any]) -> None:
        document = copy.deepcopy(export_grid().document)
        document["batches"][0]["contents"]["provenance_chain"] = {"included": False}
        _empty_the_grid()
        result = grift_import(document)
        assert result.success, [(i.code, i.path, i.message) for i in result.errors]

    @pytest.mark.spec("req-grift-contents-4")
    def test_a_batch_without_a_declaration_still_imports_its_tombstones(self, grid: dict[str, Any]) -> None:
        document = copy.deepcopy(export_grid().document)
        del document["batches"][0]["contents"]
        _empty_the_grid()
        result = grift_import(document)
        assert result.success, [(i.code, i.path, i.message) for i in result.errors]
        assert result.counts.nodes_retired == 2

    @pytest.mark.spec("req-grift-retirement-1")
    def test_a_malformed_block_is_refused(self, grid: dict[str, Any]) -> None:
        document = copy.deepcopy(export_grid().document)
        retired = next(n for n in document["batches"][0]["nodes"] if "retirement" in n)
        retired["retirement"]["retired_by"] = "someone"
        assert "schema_validation_failed" in self._codes(document)


@pytest.mark.django_db
class TestSubsets:
    @pytest.mark.spec("req-grift-export-4")
    @pytest.mark.spec("req-grift-export-6")
    def test_a_dimension_selects_exactly_its_nodes(self, grid: dict[str, Any]) -> None:
        ids = grid["ids"]
        export = export_grid(selection=ExportSelection(dimensions=(("dcom", "design"),)))
        nodes = {n["entity"]["entity_id"] for n in _batch(export)["nodes"]}
        assert nodes == {str(ids["alpha"]), str(ids["beta"])}
        # No edge joins two selected nodes, so none rides; each is counted.
        assert _batch(export)["edges"] == []
        assert export.skipped[SKIP_EDGE_ENDPOINT_NOT_EXPORTED] == 3
        assert str(ids["gamma"]) in export.skipped_sample[SKIP_NOT_SELECTED]
        capture = _batch(export)["batch_node"]["description_json"]["data"]
        assert capture["selection"]["dimensions"] == [{"key": "dcom", "value": "design"}]
        assert _batch(export)["contents"]["tombstones"] == {"included": True, "nodes": 1, "edges": 0}

    @pytest.mark.spec("req-grift-export-4")
    def test_repeats_of_one_selector_are_or_ed(self, grid: dict[str, Any]) -> None:
        ids = grid["ids"]
        export = export_grid(selection=ExportSelection(dimensions=(("dcom", "design"), ("dcom", "build"))))
        nodes = {n["entity"]["entity_id"] for n in _batch(export)["nodes"]}
        assert nodes == {str(ids["alpha"]), str(ids["beta"]), str(ids["gamma"])}
        edges = {e["entity"]["entity_id"] for e in _batch(export)["edges"]}
        assert edges == {str(ids["ag"])}

    @pytest.mark.spec("req-grift-export-4")
    def test_a_batch_selects_the_nodes_it_touched_by_id_or_name(self, grid: dict[str, Any]) -> None:
        extra = _node(SOURCE, "epsilon", batch_name="seed run one")
        by_name = export_grid(selection=ExportSelection(batches=("seed run one",)))
        assert {n["entity"]["entity_id"] for n in _batch(by_name)["nodes"]} == {str(extra)}

        batch_id = str(Batch.all_objects.get(name="seed run one").entity_id)
        by_id = export_grid(selection=ExportSelection(batches=(batch_id,)))
        assert {n["entity"]["entity_id"] for n in _batch(by_id)["nodes"]} == {str(extra)}

    @pytest.mark.spec("req-grift-export-4")
    def test_a_batch_name_matching_none_or_several_is_refused(self, grid: dict[str, Any]) -> None:
        _node(SOURCE, "zeta", batch_name="twice")
        _node(SOURCE, "eta", batch_name="twice")
        with pytest.raises(ValueError, match="more than one batch"):
            export_grid(selection=ExportSelection(batches=("twice",)))
        with pytest.raises(ValueError, match="no batch"):
            export_grid(selection=ExportSelection(batches=("never ran",)))

    @pytest.mark.spec("req-grift-export-4")
    def test_reachability_follows_edges_both_ways_and_across_retired_ones(self, grid: dict[str, Any]) -> None:
        ids = grid["ids"]
        lone = _node(TARGET, "lone")
        export = export_grid(selection=ExportSelection(reachable_from=(str(ids["delta"]),)))
        nodes = {n["entity"]["entity_id"] for n in _batch(export)["nodes"]}
        # delta <- alpha (retired edge), delta <- gamma; beta and lone join nothing.
        assert nodes == {str(ids["alpha"]), str(ids["gamma"]), str(ids["delta"])}
        assert str(lone) in export.skipped_sample[SKIP_NOT_SELECTED]

        live_only = export_grid(
            selection=ExportSelection(reachable_from=(str(ids["delta"]),), include_tombstones=False)
        )
        assert {n["entity"]["entity_id"] for n in _batch(live_only)["nodes"]} == {str(ids["delta"])}

    @pytest.mark.spec("req-grift-export-4")
    def test_different_selectors_are_and_ed(self, grid: dict[str, Any]) -> None:
        ids = grid["ids"]
        export = export_grid(
            selection=ExportSelection(dimensions=(("dcom", "design"),), reachable_from=(str(ids["delta"]),))
        )
        assert {n["entity"]["entity_id"] for n in _batch(export)["nodes"]} == {str(ids["alpha"])}

    @pytest.mark.spec("req-grift-export-4")
    def test_an_unknown_seed_is_refused(self, grid: dict[str, Any]) -> None:
        with pytest.raises(ValueError, match="names no node"):
            export_grid(selection=ExportSelection(reachable_from=(str(uuid.uuid7()),)))
        with pytest.raises(ValueError, match="names no node"):
            export_grid(selection=ExportSelection(reachable_from=(str(grid["ids"]["ag"]),)))

    @pytest.mark.spec("req-grift-export-4")
    def test_a_subset_imports_into_an_empty_grid_in_strict_mode(self, grid: dict[str, Any]) -> None:
        export = export_grid(selection=ExportSelection(reachable_from=(str(grid["ids"]["delta"]),)))
        _empty_the_grid()
        result = grift_import(export.document, dangling_edge_mode="strict")
        assert result.success, [(i.code, i.path, i.message) for i in result.errors]


@pytest.mark.django_db
class TestCommand:
    @pytest.mark.spec("req-grift-export-4")
    def test_selector_flags_reach_the_export(self, grid: dict[str, Any]) -> None:
        out, err = StringIO(), StringIO()
        call_command(
            "export_grift",
            "--output",
            "-",
            "--dimension",
            "dcom=design",
            "--exclude-tombstones",
            stdout=out,
            stderr=err,
        )
        document = json.loads(out.getvalue())
        nodes = {n["entity"]["entity_id"] for n in document["batches"][0]["nodes"]}
        assert nodes == {str(grid["ids"]["alpha"])}
        assert document["batches"][0]["contents"]["tombstones"] == {"included": False, "nodes": 0, "edges": 0}

    @pytest.mark.spec("req-grift-export-4")
    def test_a_malformed_dimension_or_unknown_batch_is_a_command_error(self, grid: dict[str, Any]) -> None:
        with pytest.raises(CommandError, match="KEY=VALUE"):
            call_command("export_grift", "--output", "-", "--dimension", "dcom", stdout=StringIO(), stderr=StringIO())
        with pytest.raises(CommandError, match="no batch"):
            call_command("export_grift", "--output", "-", "--batch", "nope", stdout=StringIO(), stderr=StringIO())
