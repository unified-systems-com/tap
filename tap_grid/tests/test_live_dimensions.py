"""Dimension names and knobs resolve from live Dimension rows (req-grid-dimension-reference-9;
unified-systems-com/tap#1188, ruled 2026-11-13 aws-build Q67c).

The seed-file table is gone: a retired node stops resolving, a knob edited on a row is enforced on
the next write, a GRIFT document may use the Dimension nodes it declares, and a grid with no rows
(a write before boot ran) refuses every dimension instead of guessing.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tap_grid import dimension_names, live_dimensions
from tap_grid.dimension_map import DimensionWriteError, supplied
from tap_grid.dimension_names import UnknownDimension
from tap_grid.models import Dimension, Entity

META = "01a1d14c-d80b-725d-8002-eb0b3e272f1d"  # tap.meta, core's dimension bundle


def _document(*nodes: dict[str, Any], batch: str | None = None) -> dict[str, Any]:
    return {
        "metadata": {"grift_version": "0"},
        "_reserved": {},
        "batches": [
            {
                "batch_entity": {
                    "entity_id": batch or str(uuid.uuid7()),
                    "entity_type": "batch",
                    "name": "live dims",
                    "dimensions": {},
                },
                "batch_node": {"source": "tests", "name": "live dims", "description": "d"},
                "nodes": list(nodes),
                "edges": [],
            }
        ],
    }


def _dimension(name: str, ident: str | None = None, **knobs: Any) -> dict[str, Any]:
    return {
        "entity": {
            "entity_id": ident or str(uuid.uuid7()),
            "entity_type": "dimension",
            "name": name,
            "dimensions": {"tap.meta": "dimension"},
        },
        "node": {"name": name, "description": "d", **knobs},
    }


def _carrier(dims: dict[str, Any]) -> dict[str, Any]:
    """A plain fixture node carrying ``dims``."""
    name = f"carrier-{uuid.uuid4().hex[:8]}"
    return {
        "entity": {
            "entity_id": str(uuid.uuid7()),
            "entity_type": "grid_fixtures__node",
            "name": name,
            "dimensions": dims,
        },
        "node": {"name": name},
    }


def _errors(result: Any) -> list[tuple[str, str, str]]:
    return [(i.code, i.path, i.message) for i in result.errors]


@pytest.mark.django_db
@pytest.mark.spec("req-grid-dimension-reference-9")
class TestKnobsAreReadFromTheRow:
    def test_a_knob_edited_on_a_row_is_enforced_on_the_next_write(self) -> None:
        from tap_grid.services import patch_node

        node = Dimension.objects.create(name="tap.test.editable")
        assert supplied({"tap.test.editable": "anything"})[str(node.entity_id)]["v"] == "anything"

        assert patch_node(node.entity_id, {"values": ["a", "b"]}).success
        with pytest.raises(DimensionWriteError, match="bounded"):
            supplied({"tap.test.editable": "anything"})
        assert supplied({"tap.test.editable": "a"})[str(node.entity_id)]["v"] == "a"

        with pytest.raises(DimensionWriteError, match="empty"):
            supplied({"tap.test.editable": ""})
        assert patch_node(node.entity_id, {"values": None, "empty_is_meaningful": True}).success
        assert supplied({"tap.test.editable": ""})[str(node.entity_id)] == {"v": "", "src": "declared"}

    def test_a_change_another_process_made_is_seen_by_the_next_scope(self) -> None:
        """No signal reaches this process for another's write: the currency check catches it."""
        node = Dimension.objects.create(name="tap.test.elsewhere")
        assert supplied({"tap.test.elsewhere": "x"})
        # Another process's edit: a row change plus the version bump every service write makes, and
        # no signal in this process (queryset updates send none).
        Dimension.all_objects.filter(entity_id=node.entity_id).update(values=["only"])  # type: ignore[misc]
        Entity.objects.filter(pk=node.entity_id).update(version=node.entity.version + 1)
        with live_dimensions.scope():
            with pytest.raises(DimensionWriteError, match="bounded"):
                supplied({"tap.test.elsewhere": "x"})

    def test_one_write_of_many_rows_checks_the_vocabulary_once(self) -> None:
        """Not a query per dimension per write: a 40-node import adds one currency check, not 40."""
        from tap_grid.grift import grift_import

        nodes = [_carrier({"tap.graph": "web"}) for _ in range(40)]
        dimension_names.storage_key("tap.meta")  # warm the per-process table
        with CaptureQueriesContext(connection) as queries:
            assert grift_import(_document(*nodes)).success
        checks = [q for q in queries if "tap_entity" in q["sql"] and "SUM(" in q["sql"].upper()]
        assert len(checks) == 1, [q["sql"] for q in checks]


@pytest.mark.django_db
@pytest.mark.spec("req-grid-dimension-reference-9")
class TestDimensionNodesAreJudgedWhenWritten:
    def test_a_second_live_node_under_a_taken_name_is_refused(self) -> None:
        from tap_grid.grift import grift_import

        taken = str(uuid.uuid7())
        assert grift_import(_document(_dimension("tap.test.taken", taken))).success
        result = grift_import(_document(_dimension("tap.test.taken")))
        assert not result.success
        assert any("DuplicateDimensionName" in message and taken in message for _c, _p, message in _errors(result))
        carriers = Dimension.objects.filter(name="tap.test.taken").values_list("entity_id", flat=True)
        assert list(carriers) == [uuid.UUID(taken)]

    @pytest.mark.parametrize(
        ("knob", "bad"), [("values", ["ok", "ok"]), ("empty_is_meaningful", "false"), ("usable_in_keys", 1)]
    )
    def test_a_wrong_typed_knob_is_refused_at_import(self, knob: str, bad: Any) -> None:
        from tap_grid.grift import grift_import

        result = grift_import(_document(_dimension("tap.test.badknob", **{knob: bad})))
        assert not result.success, "a malformed knob must not read as open or true"
        assert not Dimension.objects.filter(name="tap.test.badknob").exists()

    def test_a_wrong_typed_knob_is_refused_by_the_model(self) -> None:
        from django.core.exceptions import ValidationError

        with pytest.raises(ValidationError, match="InvalidDimensionKnob"):
            Dimension.objects.create(name="tap.test.badknob", usable_in_keys="yes")

    def test_a_row_with_a_bad_knob_that_slipped_past_fails_closed(self) -> None:
        """A row written below the model (a raw update) cannot weaken what writes enforce."""
        node = Dimension.objects.create(name="tap.test.tampered")
        Dimension.all_objects.filter(entity_id=node.entity_id).update(values="restricted")  # type: ignore[misc]
        live_dimensions.invalidate()
        with pytest.raises(live_dimensions.InvalidDimensionKnob, match=str(node.entity_id)):
            supplied({"tap.test.tampered": "x"})


@pytest.mark.django_db
@pytest.mark.spec("req-grid-dimension-reference-9")
class TestADocumentUsesWhatItDeclares:
    def test_a_node_declared_and_stamped_in_one_document_imports(self) -> None:
        from tap_grid.grift import grift_import

        ident = str(uuid.uuid7())
        result = grift_import(
            _document(_dimension("tap.test.same-doc", ident, values=["x"]), _carrier({"tap.test.same-doc": "x"}))
        )
        assert result.success, _errors(result)
        assert str(dimension_names.resolve("tap.test.same-doc")) == ident

    def test_the_declared_knobs_govern_that_same_import(self) -> None:
        from tap_grid.grift import grift_import

        result = grift_import(
            _document(
                _dimension("tap.test.same-doc-bounded", values=["x"]), _carrier({"tap.test.same-doc-bounded": "y"})
            )
        )
        assert not result.success
        assert not Dimension.objects.filter(name="tap.test.same-doc-bounded").exists()

    def test_an_already_imported_batch_does_not_revive_a_retired_node(self) -> None:
        from tap_grid.grift import grift_import
        from tap_grid.services import delete_node

        batch = str(uuid.uuid7())
        ident = str(uuid.uuid7())
        assert grift_import(_document(_dimension("tap.test.retired-in-seed", ident), batch=batch)).success
        assert delete_node(ident, reason="operator").success
        again = grift_import(_document(_dimension("tap.test.retired-in-seed", ident), batch=batch))
        assert again.success and again.skipped_batches
        with pytest.raises(UnknownDimension):
            dimension_names.resolve("tap.test.retired-in-seed")


@pytest.mark.django_db
@pytest.mark.spec("req-grid-dimension-reference-9")
class TestRetiredAndAbsentNodes:
    def test_a_row_stamped_before_its_dimension_retired_stays_writable_but_cannot_newly_set_it(self) -> None:
        from tap_grid.grift import grift_import
        from tap_grid.services import delete_node, patch_node

        dimension = Dimension.objects.create(name="tap.test.retiring")
        node = _carrier({"tap.test.retiring": "v"})
        assert grift_import(_document(node)).success
        carrier = node["entity"]["entity_id"]
        assert delete_node(dimension.entity_id, reason="operator").success
        # Shape, not resolution: the stale key does not block an edit to another field.
        result = patch_node(carrier, {"name": "still writable"})
        assert result.success, result
        assert str(dimension.entity_id) in Entity.objects.get(pk=carrier).dimensions
        # The name and the id no longer resolve for a new value.
        with pytest.raises(UnknownDimension):
            supplied({"tap.test.retiring": "v"})
        with pytest.raises(UnknownDimension):
            supplied({str(dimension.entity_id): "v"})
        assert dimension_names.view(Entity.objects.get(pk=carrier).dimensions)[str(dimension.entity_id)] == "v"

    def test_a_write_before_boot_ran_refuses_every_dimension(self) -> None:
        """A grid with no Dimension rows (a fresh test DB, a command before boot): fail closed."""
        Dimension.all_objects.all().delete()
        Entity.objects.filter(entity_type="dimension").delete()
        with pytest.raises(UnknownDimension):
            supplied({"tap.meta": "dimension"})
        with pytest.raises(UnknownDimension):
            dimension_names.storage_key("tap.graph")
        with pytest.raises(DimensionWriteError, match="not a Dimension node id"):
            from tap_grid.dimension_map import refuse_unstored_shape

            refuse_unstored_shape({META: {"v": "dimension", "src": "default"}})

    def test_gryphon_compiles_an_unknown_name_to_itself(self) -> None:
        """An undeclared or retired name matches nothing, as an absent key always has."""
        from tap_grid.gryphon.ast_nodes import KeyStep
        from tap_grid.gryphon.executor import _json_spine_inner_path

        assert _json_spine_inner_path([KeyStep("tap.meta")], context="test") == META
        assert _json_spine_inner_path([KeyStep("tap.test.nobody")], context="test") == "tap.test.nobody"
