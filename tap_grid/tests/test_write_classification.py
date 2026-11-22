"""Changed, or re-observed unchanged: one comparison decides FLIP, history, the version and the batch's record.

Covers ``req-grid-flip-change`` (spec-grid-flip.md), ``req-grid-history-reobservation``
(spec-grid-history.md) and ``req-grid-service-batch-evidence`` (spec-grid-service-batch.md);
Issue# 322 - tap. Service writes use the neutral grid_fixtures ``PgNode`` and the unconstrained
``PG_LINKS__grid_fixtures`` edge; GRIFT imports use ``tap_web`` panels, as the other import
suites do.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest
from tap_plugin.grid_fixtures.models.pg_node import PgNode

from tap_grid.caller_context import CallerContext
from tap_grid.grift import grift_import
from tap_grid.models import BaseModel, BatchEvent, BatchEventType, Edge, Entity
from tap_grid.service_types import WRITE_CHANGED, WRITE_UNCHANGED, WriteOperation
from tap_grid.services import create_edge, create_node, patch_node, replace_edge, replace_node, write_batch
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc
from tap_grid.write_classification import SYSTEM_MANAGED_FIELDS, spine_delta, values_equal
from tap_grid.write_guard import unguarded_write
from tap_web.models import Panel

FLIP = {n: pytest.mark.spec(f"req-grid-flip-change-{n}") for n in range(1, 7)}
REOBS = {n: pytest.mark.spec(f"req-grid-history-reobservation-{n}") for n in range(1, 9)}
EVIDENCE = {n: pytest.mark.spec(f"req-grid-service-batch-evidence-{n}") for n in range(1, 5)}
OBSERVE_EVENT = pytest.mark.spec("req-grid-service-batch-event-7")

_TYPE = "grid_fixtures__node"
LINK = "PG_LINKS__grid_fixtures"
WEB = {"tap.graph": "web"}


def _ctx() -> CallerContext:
    return CallerContext(batch_id=str(uuid.uuid7()))


def _bid(ctx: CallerContext) -> str:
    assert ctx.batch_id is not None
    return ctx.batch_id


def _create(payload: dict[str, Any]) -> tuple[PgNode, str]:
    ctx = _ctx()
    result = create_node(_TYPE, payload, caller_context=ctx)
    assert result.success, result.errors
    return PgNode.objects.get(entity_id=result.entity_id), _bid(ctx)


def _state(entity_id: Any) -> tuple[int, Any, int]:
    """(version, updated_at, typed history rows) for a node."""
    entity = Entity.objects.get(pk=entity_id)
    return entity.version, entity.updated_at, PgNode.history.filter(entity_id=entity_id).count()


def _keep(target: Any, payload: dict[str, Any], ctx: CallerContext) -> Any:
    """A keep-absent replace, the write the GRIFT importer sends for an existing object."""
    return replace_node(target, payload, caller_context=ctx, absent="keep")


def _panel(
    slug: str, entity_id: str, *, description: str = "", dimensions: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "entity": {
            "entity_id": entity_id,
            "entity_type": "panel",
            "name": slug,
            "dimensions": WEB if dimensions is None else dimensions,
        },
        "node": {"name": slug, "slug": slug, "description": description, "view": "tap_web/panel_error.html"},
    }


def _import(nodes: list[dict[str, Any]], edges: list[dict[str, Any]] | None = None) -> str:
    """Import one fresh batch; returns its batch entity id."""
    batch_id = _batch_entity_id()
    result = grift_import(
        _minimal_doc([_batch_container(batch_id, nodes=copy.deepcopy(nodes), edges=copy.deepcopy(edges or []))])
    )
    assert result.success, result.errors
    return batch_id


def _events(entity_id: Any, batch_id: str) -> list[str]:
    return list(
        BatchEvent.objects.filter(entity_id=entity_id, batch__entity_id=batch_id).values_list("event_type", flat=True)
    )


class TestComparison:
    @FLIP[6]
    def test_values_compare_by_json_value_type_sensitively(self) -> None:
        assert not values_equal(True, 1)
        assert not values_equal([False], [0])
        assert not values_equal({}, {"k": None})
        assert not values_equal({"a": {"b": True}}, {"a": {"b": 1}})
        assert values_equal({"a": 1, "b": [1, {"c": None}]}, {"b": [1, {"c": None}], "a": 1})
        assert values_equal(1, 1.0)
        assert not values_equal([1, 2], [2, 1])

    def test_a_named_field_off_the_published_surface_is_still_compared(self) -> None:
        # A type with no schema for the verb accepts any field; a write that moves one must not
        # be dropped as unchanged because the field is outside compared_fields.
        class Unpublished:
            SERVICE_CRUD_SCHEMA: dict[str, Any] = {}
            INTERNAL_ONLY = True
            flip_map: dict[str, str] = {}

            def __init__(self) -> None:
                self.status = "open"

            def get_name(self) -> str:
                return "u"

            def derive_natural_key(self) -> None:
                return None

        from tap_grid.write_classification import classify, snapshot

        row = Unpublished()
        before = snapshot(row, frozenset({"status"}))
        assert not classify(row, before, frozenset({"status"})).changed
        row.status = "closed"
        result = classify(row, before, frozenset({"status"}))
        assert result.changed
        assert result.changed_fields == {"status"}

    def test_every_system_managed_basemodel_field_is_listed(self) -> None:
        # req-grid-flip-change rule 7: the excluded list is kept in one place, and a field added
        # to BaseModel without it fails here.
        declared = {f.name for f in BaseModel._meta.local_fields}
        assert declared == set(SYSTEM_MANAGED_FIELDS)


@pytest.mark.django_db
class TestFlipMovesOnlyOnChange:
    @FLIP[1]
    @pytest.mark.parametrize("verb", ["patch", "replace", "keep"])
    def test_repeat_leaves_every_entry(self, verb: str) -> None:
        payload = {"name": "eth0", "kind": "up", "tags": {"a": 1}}
        node, batch_a = _create(payload)
        ctx = _ctx()
        if verb == "patch":
            result = patch_node(node.entity_id, payload, caller_context=ctx)
        elif verb == "replace":
            result = replace_node(node.entity_id, payload, caller_context=ctx)
        else:
            result = _keep(node.entity_id, payload, ctx)
        assert result.success, result.errors
        node.refresh_from_db()
        assert node.flip_map == dict.fromkeys(payload, batch_a)

    @FLIP[1]
    def test_repeat_grift_import_leaves_every_entry(self) -> None:
        entity_id = str(uuid.uuid4())
        _import([_panel("p1", entity_id)])
        before = dict(Panel.objects.get(entity_id=entity_id).flip_map)
        assert before
        _import([_panel("p1", entity_id)])
        assert Panel.objects.get(entity_id=entity_id).flip_map == before

    @FLIP[2]
    @pytest.mark.parametrize("verb", ["patch", "replace", "keep"])
    def test_change_moves_one_entry(self, verb: str) -> None:
        node, batch_a = _create({"name": "eth0", "kind": "up", "description": "d"})
        ctx = _ctx()
        payload = {"name": "eth0", "kind": "down", "description": "d"}
        if verb == "patch":
            result = patch_node(node.entity_id, payload, caller_context=ctx)
        elif verb == "replace":
            result = replace_node(node.entity_id, payload, caller_context=ctx)
        else:
            result = _keep(node.entity_id, payload, ctx)
        assert result.success, result.errors
        node.refresh_from_db()
        assert node.flip_map == {"name": batch_a, "kind": ctx.batch_id, "description": batch_a}

    @FLIP[3]
    def test_first_explicit_null_is_stamped(self) -> None:
        node, _ = _create({"name": "eth0"})
        assert "observed_at" not in node.flip_map
        ctx = _ctx()
        assert patch_node(node.entity_id, {"observed_at": None}, caller_context=ctx).success
        node.refresh_from_db()
        assert node.observed_at is None
        assert node.flip_map["observed_at"] == ctx.batch_id

    @FLIP[4]
    def test_repeat_explicit_null_is_not(self) -> None:
        node, _ = _create({"name": "eth0"})
        first = _ctx()
        patch_node(node.entity_id, {"observed_at": None}, caller_context=first)
        for _ in range(2):
            assert patch_node(node.entity_id, {"observed_at": None}, caller_context=_ctx()).success
        node.refresh_from_db()
        assert node.flip_map["observed_at"] == first.batch_id

    @FLIP[5]
    def test_unnamed_field_is_never_stamped(self) -> None:
        node, batch_a = _create({"name": "eth0", "kind": "up"})
        ctx = _ctx()
        # A full replace naming one field: `description` is unnamed and its reset to the default
        # changes nothing, so it gains no entry; `kind` is unnamed and its reset does change the
        # stored value, so it is stamped.
        assert replace_node(node.entity_id, {"name": "eth0"}, caller_context=ctx).success
        node.refresh_from_db()
        assert "description" not in node.flip_map
        assert node.flip_map["name"] == batch_a
        assert node.kind != "up"
        assert node.flip_map["kind"] == ctx.batch_id

    @FLIP[6]
    @pytest.mark.parametrize(("stored", "sent"), [({"flag": True}, {"flag": 1}), ({"l": [False]}, {"l": [0]})])
    def test_type_sensitive_replace_is_a_change(self, stored: dict[str, Any], sent: dict[str, Any]) -> None:
        node, _ = _create({"name": "eth0", "tags": stored})
        version, _, rows = _state(node.entity_id)
        ctx = _ctx()
        result = _keep(node.entity_id, {"name": "eth0", "tags": sent}, ctx)
        assert result.success, result.errors
        assert result.state == WRITE_CHANGED
        node.refresh_from_db()
        assert node.flip_map["tags"] == ctx.batch_id
        assert _state(node.entity_id)[0] == version + 1
        assert _state(node.entity_id)[2] == rows + 1


@pytest.mark.django_db
class TestReobservationIsNotAChange:
    @REOBS[1]
    @OBSERVE_EVENT
    def test_identical_reimport_leaves_no_row(self) -> None:
        entity_id = str(uuid.uuid4())
        _import([_panel("p1", entity_id)])
        entity = Entity.objects.get(pk=entity_id)
        assert entity.version == 1
        second = _import([_panel("p1", entity_id)])
        after = Entity.objects.get(pk=entity_id)
        assert Panel.history.filter(entity_id=entity_id).count() == 1
        assert after.version == 1
        assert after.updated_at == entity.updated_at
        # The second batch still records that it saw the panel.
        assert _events(entity_id, second) == [BatchEventType.OBSERVE]

    @REOBS[2]
    def test_one_change_one_row(self) -> None:
        entity_id = str(uuid.uuid4())
        _import([_panel("p1", entity_id)])
        _import([_panel("p1", entity_id)])
        third = _import([_panel("p1", entity_id, description="now described")])
        assert Entity.objects.get(pk=entity_id).version == 2
        newest, previous = Panel.history.filter(entity_id=entity_id).order_by("-history_date", "-history_id")[:2]
        assert Panel.history.filter(entity_id=entity_id).count() == 2
        differing = {change.field for change in newest.diff_against(previous).changes}
        assert differing == {"description", "batch_id", "flip_map"}
        assert _events(entity_id, third) == [BatchEventType.UPDATE]

    @REOBS[3]
    @pytest.mark.parametrize("verb", ["patch", "replace"])
    def test_same_value_write_leaves_no_row(self, verb: str) -> None:
        payload = {"name": "eth0", "kind": "up"}
        node, _ = _create(payload)
        before = _state(node.entity_id)
        write = patch_node if verb == "patch" else replace_node
        result = write(node.entity_id, payload, caller_context=_ctx())
        assert result.success, result.errors
        assert _state(node.entity_id) == before

    @REOBS[4]
    def test_spine_only_change_is_a_change(self) -> None:
        entity_id = str(uuid.uuid4())
        _import([_panel("p1", entity_id)])
        stored = Entity.objects.get(pk=entity_id)
        flip_before = dict(Panel.objects.get(entity_id=entity_id).flip_map)
        batch = _import([_panel("p1", entity_id, dimensions={})])
        after = Entity.objects.get(pk=entity_id)
        assert after.dimensions != stored.dimensions
        assert after.version == stored.version + 1
        assert Panel.history.filter(entity_id=entity_id).count() == 2
        assert Panel.objects.get(entity_id=entity_id).flip_map == flip_before
        assert _events(entity_id, batch) == [BatchEventType.UPDATE]

    @REOBS[5]
    def test_first_assertion_is_a_change_and_its_repeat_is_not(self) -> None:
        node, _ = _create({"name": "eth0"})
        version, _, rows = _state(node.entity_id)
        first = patch_node(node.entity_id, {"observed_at": None}, caller_context=_ctx())
        assert first.state == WRITE_CHANGED
        assert _state(node.entity_id)[0] == version + 1
        assert _state(node.entity_id)[2] == rows + 1
        settled = _state(node.entity_id)
        repeat = patch_node(node.entity_id, {"observed_at": None}, caller_context=_ctx())
        assert repeat.state == WRITE_UNCHANGED
        assert _state(node.entity_id) == settled

    @REOBS[6]
    def test_stale_writer_is_still_refused(self) -> None:
        payload = {"name": "eth0"}
        node, _ = _create(payload)
        patch_node(node.entity_id, {"name": "eth1"}, caller_context=_ctx())
        before = _state(node.entity_id)
        result = patch_node(node.entity_id, {"name": "eth1"}, caller_context=_ctx(), entity_expected_version=1)
        assert not result.success
        assert result.errors[0].code == "entity_version_conflict"
        assert _state(node.entity_id) == before

    @REOBS[7]
    def test_result_names_the_state(self) -> None:
        ctx = _ctx()
        created = create_node(_TYPE, {"name": "eth0"}, caller_context=ctx)
        assert created.state == WRITE_CHANGED
        assert created.entity_id is not None
        assert patch_node(created.entity_id, {"name": "eth0"}, caller_context=_ctx()).state == WRITE_UNCHANGED
        assert patch_node(created.entity_id, {"name": "eth1"}, caller_context=_ctx()).state == WRITE_CHANGED
        observer = _ctx()
        assert _keep(created.entity_id, {"name": "eth1"}, observer).state == WRITE_UNCHANGED
        assert _events(created.entity_id, _bid(observer)) == [BatchEventType.OBSERVE]

    @REOBS[8]
    def test_edge_replace_follows_the_same_rules(self) -> None:
        a, _ = _create({"name": "a"})
        b, _ = _create({"name": "b"})
        ctx = _ctx()
        edge = create_edge(a.entity, b.entity, LINK, {"weight": 1}, caller_context=ctx)
        entity = Entity.objects.get(pk=edge.entity_id)
        rows = Edge.history.filter(entity_id=edge.entity_id).count()
        same = replace_edge(edge.entity_id, {"properties": {"weight": 1}}, caller_context=_ctx())
        assert same.success, same.errors
        assert same.state == WRITE_UNCHANGED
        after = Entity.objects.get(pk=edge.entity_id)
        assert (after.version, after.updated_at) == (entity.version, entity.updated_at)
        assert Edge.history.filter(entity_id=edge.entity_id).count() == rows
        assert Edge.objects.get(entity_id=edge.entity_id).flip_map == edge.flip_map
        changed = replace_edge(edge.entity_id, {"properties": {"weight": 2}}, caller_context=_ctx())
        assert changed.state == WRITE_CHANGED
        assert Entity.objects.get(pk=edge.entity_id).version == entity.version + 1
        assert Edge.history.filter(entity_id=edge.entity_id).count() == rows + 1

    @REOBS[8]
    def test_edge_reimported_unchanged_leaves_no_row(self) -> None:
        a, b, edge_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        nodes = [_panel("pa", a), _panel("pb", b)]
        edge = {
            "entity": {"entity_id": edge_id, "entity_type": "edge", "dimensions": {}},
            "edge": {"edge_type": LINK, "properties": {}, "from_entity_id": a, "to_entity_id": b},
        }
        _import(nodes, [edge])
        entity = Entity.objects.get(pk=edge_id)
        rows = Edge.history.filter(entity_id=edge_id).count()
        second = _import(nodes, [edge])
        after = Entity.objects.get(pk=edge_id)
        assert (after.version, after.updated_at) == (entity.version, entity.updated_at)
        assert Edge.history.filter(entity_id=edge_id).count() == rows
        assert _events(edge_id, second) == [BatchEventType.OBSERVE]


@pytest.mark.django_db
class TestTheWholeOperationIsClassifiedUnderTheLock:
    """Preparation, validation and the spine comparison all happen in the pipeline, before the save decision."""

    @REOBS[4]
    def test_spine_intent_is_compared_when_the_write_runs_not_when_it_was_built(self) -> None:
        """An envelope that matched the spine when the operation was built, and no longer does when
        it runs, is a change: the comparison is the pipeline's, under the node's row lock."""
        node, _ = _create({"name": "n"})
        entity = Entity.objects.get(pk=node.entity_id)
        intent = {
            "entity_id": str(node.entity_id),
            "entity_type": _TYPE,
            "envelope_name": entity.name,
            "envelope_dims": {},
        }
        assert spine_delta(intent) == {}
        op = WriteOperation(
            verb="replace_node", target=node.entity_id, payload={"name": "n"}, absent="keep", spine_intent=intent
        )
        # Another writer moves the spine after the operation was built.
        with unguarded_write():
            Entity.objects.filter(pk=node.entity_id).update(name="moved by another writer")
        assert spine_delta(intent) == {"name": entity.name}
        version, _, rows = _state(node.entity_id)

        result = write_batch([op], caller_context=_ctx())

        assert result.success, result.errors
        assert result.results[0].state == WRITE_CHANGED
        assert _state(node.entity_id)[0] == version + 1
        assert _state(node.entity_id)[2] == rows + 1

    @REOBS[3]
    def test_the_write_hook_runs_before_classification(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A value the model's write hook derives is stored, although the payload repeats what is stored."""
        node, _ = _create({"name": "n", "description": "d"})
        monkeypatch.setattr(PgNode, "prepare_for_write", lambda self: setattr(self, "description", "derived"))
        version, _, rows = _state(node.entity_id)

        result = _keep(node.entity_id, {"name": "n"}, _ctx())

        assert result.success, result.errors
        assert result.state == WRITE_CHANGED
        assert PgNode.objects.get(entity_id=node.entity_id).description == "derived"
        assert _state(node.entity_id)[0] == version + 1
        assert _state(node.entity_id)[2] == rows + 1

    @REOBS[8]
    def test_an_unchanged_edge_is_still_validated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An edge whose stored properties no longer satisfy its type's schema is refused, not observed."""
        a, _ = _create({"name": "a"})
        b, _ = _create({"name": "b"})
        made = create_edge(a.entity, b.entity, LINK, {"weight": 1}, caller_context=_ctx())
        from tap_grid import constraints
        from tap_grid.exceptions import EdgePropertyValidationError

        def refuse(edge_type: str, properties: Any) -> None:
            raise EdgePropertyValidationError("properties no longer satisfy the schema")

        monkeypatch.setattr(constraints, "validate_edge_properties", refuse)
        ctx = _ctx()

        result = replace_edge(made.entity_id, {"properties": {"weight": 1}}, caller_context=ctx)

        assert not result.success
        assert result.errors[0].code == "validation_error"
        assert not BatchEvent.objects.filter(batch__entity_id=_bid(ctx), entity_id=made.entity_id).exists()


@pytest.mark.django_db
class TestEvidenceIsAtomicWithTheWrite:
    @staticmethod
    def _break_recording(monkeypatch: pytest.MonkeyPatch, only: str | None = None) -> None:
        import tap_grid.batch as batch_module

        real = batch_module.record_batch_event

        def failing(entity: Any, *args: Any, **kwargs: Any) -> Any:
            if only is None or str(entity.pk) == only:
                raise RuntimeError("event store unavailable")
            return real(entity, *args, **kwargs)

        monkeypatch.setattr(batch_module, "record_batch_event", failing)

    @EVIDENCE[1]
    def test_a_failed_record_rolls_back_the_write(self, monkeypatch: pytest.MonkeyPatch) -> None:
        node, _ = _create({"name": "eth0", "kind": "up"})
        before = _state(node.entity_id)
        count = PgNode.objects.count()
        self._break_recording(monkeypatch)

        created = create_node(_TYPE, {"name": "eth9"}, caller_context=_ctx())
        patched = patch_node(node.entity_id, {"kind": "down"}, caller_context=_ctx())
        replaced = replace_node(node.entity_id, {"name": "other"}, caller_context=_ctx())

        for result in (created, patched, replaced):
            assert not result.success
            assert result.errors[0].code == "evidence_not_recorded"
        assert PgNode.objects.count() == count
        node.refresh_from_db()
        assert (node.name, node.kind) == ("eth0", "up")
        assert _state(node.entity_id) == before

    @EVIDENCE[2]
    def test_no_batch_no_write(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import tap_grid.services as services

        # The batch row is never minted, so the operation reaches recording with nothing to record in.
        monkeypatch.setattr(services, "_ensure_batch", lambda *args, **kwargs: None)
        count = PgNode.objects.count()
        result = create_node(_TYPE, {"name": "eth0"}, caller_context=_ctx(), batch_name="n", batch_description="d")
        assert not result.success
        assert result.errors[0].code == "evidence_not_recorded"
        assert PgNode.objects.count() == count

    @EVIDENCE[3]
    def test_import_with_a_failed_record_is_rejected_whole(self, monkeypatch: pytest.MonkeyPatch) -> None:
        good, bad = str(uuid.uuid4()), str(uuid.uuid4())
        self._break_recording(monkeypatch, only=bad)
        batch_id = _batch_entity_id()
        result = grift_import(
            _minimal_doc([_batch_container(batch_id, nodes=[_panel("good", good), _panel("bad", bad)])])
        )
        assert not result.success
        assert not Entity.objects.filter(pk__in=[good, bad]).exists()

    @EVIDENCE[4]
    @OBSERVE_EVENT
    def test_every_committed_write_has_a_record(self) -> None:
        changed, _ = _create({"name": "c", "kind": "up"})
        observed, _ = _create({"name": "o"})
        ctx = _ctx()
        new_id = str(uuid.uuid4())
        result = write_batch(
            [
                WriteOperation(verb="create_node", type_slug=_TYPE, payload={"name": "n"}, entity_id=new_id),
                WriteOperation(verb="patch_node", target=changed.entity_id, payload={"kind": "down"}),
                WriteOperation(verb="replace_node", target=observed.entity_id, payload={"name": "o"}, absent="keep"),
            ],
            caller_context=ctx,
            batch_name="n",
            batch_description="d",
        )
        assert result.success, result.errors
        assert _events(new_id, _bid(ctx)) == [BatchEventType.CREATE]
        assert _events(changed.entity_id, _bid(ctx)) == [BatchEventType.UPDATE]
        assert _events(observed.entity_id, _bid(ctx)) == [BatchEventType.OBSERVE]
