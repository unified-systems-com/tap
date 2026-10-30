"""Keep-absent replace: a replace that leaves payload-absent fields alone (tap#1128).

Covers req-grid-service-write-keepabsent (``WriteOperation.absent == "keep"``) and the GRIFT importer's
use of it for existing entities (req-grid-import-grift-ordering-8..10). The origin is
unified-systems-com/aws-core-tap#60: a collector whose tag read failed had no way to say "no comment"
about ``tags``, so the import reset the field to its default and erased the stored tags.

Uses the neutral grid_fixtures PgNode (``tags`` JSON object, ``kind`` and ``severity_score`` non-null,
``observed_at`` nullable) so this core suite does not depend on a domain plugin.
"""

import uuid
from typing import Any

import pytest
from tap_plugin.grid_fixtures.models.pg_node import PgNode

from tap_grid.caller_context import CallerContext
from tap_grid.grift import grift_import
from tap_grid.models import Edge
from tap_grid.service_types import WriteOperation
from tap_grid.services import create_node, replace_edge, replace_node, write_batch

_TYPE = "grid_fixtures__node"
_OBSERVED = "2026-01-01T00:00:00Z"


def _ctx() -> CallerContext:
    return CallerContext(batch_id=str(uuid.uuid7()))


def _create(payload: dict[str, Any]) -> PgNode:
    result = create_node(_TYPE, payload, caller_context=_ctx())
    assert result.success, result.errors
    node: PgNode = PgNode.objects.get(entity_id=result.entity_id)
    return node


@pytest.mark.django_db
class TestKeepAbsentReplace:
    @pytest.mark.spec("req-grid-service-write-keepabsent-1")
    def test_default_replace_still_resets_absent_fields(self):
        node = _create({"name": "n", "kind": "up", "tags": {"env": "prod"}})
        result = replace_node(node.entity_id, {"name": "n"}, caller_context=_ctx())
        assert result.success, result.errors
        node.refresh_from_db()
        assert node.kind == ""
        assert node.tags == {}

    @pytest.mark.spec("req-grid-service-write-keepabsent-2")
    def test_absent_field_keeps_its_stored_value(self):
        node = _create({"name": "n", "kind": "up", "severity_score": 7, "tags": {"env": "prod"}})
        result = replace_node(node.entity_id, {"name": "n2"}, caller_context=_ctx(), absent="keep")
        assert result.success, result.errors
        node.refresh_from_db()
        assert node.name == "n2"
        assert node.kind == "up"
        assert node.severity_score == 7
        assert node.tags == {"env": "prod"}

    @pytest.mark.spec("req-grid-service-write-keepabsent-3")
    def test_present_object_replaces_whole_without_merging(self):
        node = _create({"name": "n", "tags": {"env": "prod", "team": "x"}})
        result = replace_node(
            node.entity_id, {"name": "n", "tags": {"env": "dev"}}, caller_context=_ctx(), absent="keep"
        )
        assert result.success, result.errors
        node.refresh_from_db()
        # A deep merge would keep "team"; replacing whole drops the tag the sender no longer sends.
        assert node.tags == {"env": "dev"}

    @pytest.mark.spec("req-grid-service-write-keepabsent-3")
    def test_present_empty_object_clears_tags(self):
        # An untagged resource that WAS read is {} and must erase stored tags; only an omission keeps them.
        node = _create({"name": "n", "tags": {"env": "prod"}})
        result = replace_node(node.entity_id, {"name": "n", "tags": {}}, caller_context=_ctx(), absent="keep")
        assert result.success, result.errors
        node.refresh_from_db()
        assert node.tags == {}

    @pytest.mark.spec("req-grid-service-write-keepabsent-4")
    def test_null_on_non_null_field_resets_to_default(self):
        node = _create({"name": "n", "kind": "up", "severity_score": 7})
        result = replace_node(
            node.entity_id, {"name": "n", "kind": None, "severity_score": None}, caller_context=_ctx(), absent="keep"
        )
        assert result.success, result.errors
        node.refresh_from_db()
        assert node.kind == ""
        assert node.severity_score == 0

    @pytest.mark.spec("req-grid-service-write-keepabsent-4")
    def test_null_on_nullable_field_clears_it(self):
        node = _create({"name": "n", "observed_at": _OBSERVED})
        result = replace_node(node.entity_id, {"name": "n", "observed_at": None}, caller_context=_ctx(), absent="keep")
        assert result.success, result.errors
        node.refresh_from_db()
        assert node.observed_at is None

    @pytest.mark.spec("req-grid-service-write-keepabsent-5")
    @pytest.mark.parametrize("verb", ["create_node", "patch_node", "delete_node"])
    def test_keep_is_refused_on_other_verbs(self, verb: str):
        node = _create({"name": "n"})
        op = WriteOperation(
            verb=verb,
            type_slug=_TYPE if verb == "create_node" else None,
            target=None if verb == "create_node" else node.entity_id,
            payload={"name": "m"} if verb != "delete_node" else None,
            absent="keep",
        )
        batch = write_batch([op], caller_context=_ctx())
        assert not batch.success
        assert batch.results[0].errors[0].code == "absent_not_allowed"

    @pytest.mark.spec("req-grid-service-write-keepabsent-6")
    def test_flip_stamps_only_sent_fields(self):
        ctx_a = _ctx()
        created = create_node(_TYPE, {"name": "n", "kind": "up", "tags": {"a": "1"}}, caller_context=ctx_a)
        node = PgNode.objects.get(entity_id=created.entity_id)
        ctx_b = _ctx()
        replace_node(node.entity_id, {"name": "n", "kind": None}, caller_context=ctx_b, absent="keep")
        node.refresh_from_db()
        assert node.flip_map.get("name") == ctx_b.batch_id
        assert node.flip_map.get("kind") == ctx_b.batch_id  # a null reset is an assertion, so it is stamped
        assert node.flip_map.get("tags") == ctx_a.batch_id  # not sent, not re-stamped

    @pytest.mark.spec("req-grid-service-write-keepabsent-5")
    def test_edge_replace_accepts_keep(self):
        a, b = _create({"name": "a"}), _create({"name": "b"})
        edge = Edge.objects.create(
            from_entity=a.entity, to_entity=b.entity, edge_type="SCHEMA_LINK__grid_fixtures", properties={"x": 1}
        )
        result = replace_edge(edge.entity_id, {}, caller_context=_ctx(), absent="keep")
        assert result.success, result.errors
        edge.refresh_from_db()
        assert edge.properties == {"x": 1}


def _doc(batch_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "metadata": {"grift_version": "0"},
        "_reserved": {},
        "batches": [
            {
                "batch_entity": {"entity_id": batch_id, "entity_type": "batch", "name": "b", "dimensions": {}},
                "batch_node": {"name": "b", "description": "", "description_json": None, "source": "t", "metadata": {}},
                "nodes": nodes,
                "edges": edges or [],
            }
        ],
    }


def _node(entity_id: str, node: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity": {"entity_id": entity_id, "entity_type": _TYPE, "name": node["name"], "dimensions": {}},
        "node": node,
    }


@pytest.mark.django_db
class TestGriftUpsertKeepsAbsentFields:
    @pytest.mark.spec("req-grid-import-grift-ordering-8")
    def test_omitted_tags_survive_an_upsert(self):
        # The aws-core-tap#60 shape: run one reads the tags, run two could not and omits them.
        nid = str(uuid.uuid4())
        first = grift_import(
            _doc(str(uuid.uuid4()), [_node(nid, {"name": "q", "kind": "up", "tags": {"env": "prod"}})])
        )
        assert first.success, first.errors
        second = grift_import(_doc(str(uuid.uuid4()), [_node(nid, {"name": "q", "kind": "down"})]))
        assert second.success, second.errors
        node = PgNode.objects.get(entity_id=uuid.UUID(nid))
        assert node.kind == "down"
        assert node.tags == {"env": "prod"}

    @pytest.mark.spec("req-grid-import-grift-ordering-9")
    def test_present_tags_replace_whole_and_empty_clears(self):
        nid = str(uuid.uuid4())
        for tags in ({"env": "prod", "team": "x"}, {"env": "dev"}):
            result = grift_import(_doc(str(uuid.uuid4()), [_node(nid, {"name": "q", "tags": tags})]))
            assert result.success, result.errors
        assert PgNode.objects.get(entity_id=uuid.UUID(nid)).tags == {"env": "dev"}
        result = grift_import(_doc(str(uuid.uuid4()), [_node(nid, {"name": "q", "tags": {}})]))
        assert result.success, result.errors
        assert PgNode.objects.get(entity_id=uuid.UUID(nid)).tags == {}

    @pytest.mark.spec("req-grid-import-grift-ordering-9")
    def test_null_on_non_null_field_resets_through_import(self):
        nid = str(uuid.uuid4())
        grift_import(_doc(str(uuid.uuid4()), [_node(nid, {"name": "q", "severity_score": 9})]))
        result = grift_import(_doc(str(uuid.uuid4()), [_node(nid, {"name": "q", "severity_score": None})]))
        assert result.success, result.errors
        assert PgNode.objects.get(entity_id=uuid.UUID(nid)).severity_score == 0

    @pytest.mark.spec("req-grid-import-grift-ordering-8")
    def test_create_path_is_unchanged(self):
        nid = str(uuid.uuid4())
        result = grift_import(_doc(str(uuid.uuid4()), [_node(nid, {"name": "q"})]))
        assert result.success, result.errors
        node = PgNode.objects.get(entity_id=uuid.UUID(nid))
        assert node.tags == {}
        assert "tags" not in node.flip_map

    @pytest.mark.spec("req-grid-import-grift-ordering-10")
    def test_edge_properties_replace_whole(self):
        a, b, eid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())

        def edge(properties: dict[str, Any]) -> dict[str, Any]:
            body = {
                "from_entity_id": a,
                "to_entity_id": b,
                "edge_type": "SCHEMA_LINK__grid_fixtures",
                "properties": properties,
            }
            return {"entity": {"entity_id": eid, "entity_type": "edge", "dimensions": {}}, "edge": body}

        nodes = [_node(a, {"name": "a"}), _node(b, {"name": "b"})]
        for properties in ({"x": 1, "y": 2}, {"z": 3}):
            result = grift_import(_doc(str(uuid.uuid4()), nodes, [edge(properties)]))
            assert result.success, result.errors
        assert Edge.objects.get(entity_id=uuid.UUID(eid)).properties == {"z": 3}


@pytest.mark.spec("req-grid-import-grift-ordering-10")
def test_edge_replace_surface_is_only_properties():
    # The import spec says keep-absent changes nothing observable for edges today. That holds only while
    # the edge replace schema writes nothing but ``properties``; a new writable edge field must be decided.
    assert set(Edge.SERVICE_CRUD_SCHEMA["replace"]["properties"]) == {"properties"}
