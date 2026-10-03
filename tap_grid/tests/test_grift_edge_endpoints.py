"""Edge endpoints named by type and natural key, and the skip event for one that names nothing.

Spec: ``req-grid-import-grift-edge-endpoints`` in ``tap_grid/specs/spec-grid-import-grift.md``
(Issue# 914 - tap). Endpoints are panels (``tap_web``), keyed on ``slug``; the edge is the
unconstrained ``PG_LINKS__grid_fixtures``, addressed by explicit id so edge identity stays out
of the way.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

import pytest

from tap_grid.grift import grift_import
from tap_grid.models import BatchEvent, BatchEventType, Edge, Entity
from tap_grid.services import delete_node
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc
from tap_web.models import Panel

SPEC = {n: pytest.mark.spec(f"req-grid-import-grift-edge-endpoints-{n}") for n in range(1, 10)}
LINK = "PG_LINKS__grid_fixtures"
WEB = {"tap.graph": "web"}


def _panel(slug: str, entity_id: str | None = None) -> dict[str, Any]:
    return {
        "entity": {
            "entity_id": entity_id or str(uuid.uuid4()),
            "entity_type": "panel",
            "name": slug,
            "dimensions": WEB,
        },
        "node": {"name": slug, "slug": slug, "description": "", "view": "tap_web/panel_error.html"},
    }


def _key(slug: str, entity_type: str = "panel", **extra: Any) -> dict[str, Any]:
    return {"entity_type": entity_type, "key": {"slug": slug, **extra}}


def _edge(*, edge_id: str | None = None, **endpoints: Any) -> dict[str, Any]:
    return {
        "entity": {"entity_id": edge_id or str(uuid.uuid4()), "entity_type": "edge", "dimensions": {}},
        "edge": {"edge_type": LINK, "properties": {}, **endpoints},
    }


def _doc(*, nodes: list[dict[str, Any]] | None = None, edges: list[dict[str, Any]] | None = None, **extra: Any) -> Any:
    container = _batch_container(_batch_entity_id(), nodes=nodes or [], edges=edges or [])
    container.update(extra)
    return _minimal_doc([container])


def _seed(*slugs: str) -> dict[str, str]:
    """Live panels on the grid, one per slug; returns slug -> entity id."""
    nodes = [_panel(s) for s in slugs]
    result = grift_import(_doc(nodes=nodes))
    assert result.success, result.errors
    return {n["node"]["slug"]: n["entity"]["entity_id"] for n in nodes}


def _codes(result: Any) -> list[str]:
    return [e.code for e in result.errors]


def _edges_between(a: str, b: str) -> list[Any]:
    return list(Edge.objects.filter(from_entity_id=a, to_entity_id=b))


def _skip_events() -> list[BatchEvent]:
    return list(BatchEvent.objects.filter(event_type=BatchEventType.SKIP))


@pytest.mark.django_db
class TestResolution:
    @SPEC[1]
    @SPEC[2]
    def test_a_key_names_a_live_node_on_the_grid(self) -> None:
        ids = _seed("source", "target")
        result = grift_import(_doc(edges=[_edge(from_key=_key("source"), to_key=_key("target"))]))
        assert result.success, result.errors
        assert len(_edges_between(ids["source"], ids["target"])) == 1

    @SPEC[1]
    def test_key_id_endpoints_mix_on_one_edge(self) -> None:
        ids = _seed("source", "target")
        result = grift_import(_doc(edges=[_edge(from_key=_key("source"), to_entity_id=ids["target"])]))
        assert result.success, result.errors
        assert len(_edges_between(ids["source"], ids["target"])) == 1

    @SPEC[2]
    def test_the_batch_is_searched_before_the_grid(self) -> None:
        ids = _seed("target")
        fresh = _panel("only-in-this-batch")
        result = grift_import(
            _doc(nodes=[fresh], edges=[_edge(from_key=_key("only-in-this-batch"), to_entity_id=ids["target"])])
        )
        assert result.success, result.errors
        assert len(_edges_between(fresh["entity"]["entity_id"], ids["target"])) == 1

    @SPEC[2]
    def test_a_tombstoned_node_is_never_found(self) -> None:
        ids = _seed("gone", "target")
        assert delete_node(ids["gone"]).success
        result = grift_import(_doc(edges=[_edge(from_key=_key("gone"), to_entity_id=ids["target"])]))
        assert "dangling_edge" in _codes(result), "strict mode: an unresolved endpoint fails the batch"

    @SPEC[4]
    def test_two_live_matches_fail_the_batch_naming_both(self) -> None:
        first, second = _panel("twin"), _panel("twin")
        assert grift_import(_doc(nodes=[first])).success
        assert grift_import(_doc(nodes=[second])).success
        ids = _seed("target")
        result = grift_import(_doc(edges=[_edge(from_key=_key("twin"), to_entity_id=ids["target"])]))
        assert "identity_ambiguous" in _codes(result)
        message = next(e.message for e in result.errors if e.code == "identity_ambiguous")
        assert first["entity"]["entity_id"] in message and second["entity"]["entity_id"] in message

    @SPEC[1]
    def test_the_callers_document_is_never_rewritten(self) -> None:
        _seed("source", "target")
        doc = _doc(edges=[_edge(from_key=_key("source"), to_key=_key("target"))])
        before = copy.deepcopy(doc)
        assert grift_import(doc).success
        assert doc == before


@pytest.mark.django_db
class TestCompleteKeysOnly:
    @SPEC[3]
    @pytest.mark.parametrize(
        ("endpoint", "code"),
        [
            ({"entity_type": "panel", "key": {}}, "schema_validation_failed"),
            ({"entity_type": "panel", "key": {"slug": None}}, "incomplete_endpoint_key"),
            ({"entity_type": "panel", "key": {"name": "x"}}, "endpoint_key_mismatch"),
            ({"entity_type": "panel", "key": {"slug": "x", "name": "y"}}, "endpoint_key_mismatch"),
            ({"entity_type": "search", "key": {"name": "x"}}, "endpoint_type_unkeyed"),
            ({"entity_type": "grid_fixtures__node", "key": {"name": "x"}}, "endpoint_type_unkeyed"),
            ({"entity_type": "no_such_type", "key": {"name": "x"}}, "unknown_entity_type"),
        ],
    )
    def test_an_unsound_key_is_refused_before_anything_is_written(self, endpoint: dict[str, Any], code: str) -> None:
        ids = _seed("target")
        fresh = _panel("would-be-written")
        result = grift_import(
            _doc(nodes=[fresh], edges=[_edge(from_key=endpoint, to_entity_id=ids["target"])]),
            dangling_edge_mode="permissive",
        )
        assert code in _codes(result), result.errors
        assert not Entity.objects.filter(pk=uuid.UUID(fresh["entity"]["entity_id"])).exists()

    @SPEC[3]
    def test_an_empty_string_is_a_value_not_a_hole(self) -> None:
        """As for nodes (req-grid-entity-natural-key-16): observed-empty is a value; only null is a hole."""
        from tap_grid.grift.importer import _endpoint_key_is_sound

        issues: list[Any] = []
        assert _endpoint_key_is_sound(_key(""), "$.x", issues, batch_entity_id=None, entity_id=None)
        assert issues == []


@pytest.mark.django_db
class TestUnresolved:
    @SPEC[5]
    @SPEC[6]
    def test_strict_mode_fails_the_batch_and_mints_nothing(self) -> None:
        ids = _seed("target")
        fresh = _panel("also-in-the-batch")
        result = grift_import(_doc(nodes=[fresh], edges=[_edge(from_key=_key("nobody"), to_entity_id=ids["target"])]))
        assert "dangling_edge" in _codes(result)
        assert not Panel.objects.filter(slug="nobody").exists(), "a lookup never mints"
        assert not Entity.objects.filter(pk=uuid.UUID(fresh["entity"]["entity_id"])).exists()

    @SPEC[6]
    @SPEC[7]
    def test_strict_mode_names_every_unresolved_endpoint(self) -> None:
        result = grift_import(_doc(edges=[_edge(from_key=_key("nobody"), to_key=_key("no-one"))]))
        dangling = [e for e in result.errors if e.code == "dangling_edge"]
        assert sorted(e.path.rsplit(".", 1)[-1] for e in dangling) == ["from_key", "to_key"]

    @SPEC[6]
    def test_a_skipped_key_edge_of_a_type_with_declared_identity_is_still_skipped(self) -> None:
        """Edge identity runs after endpoint resolution and must pass over a skipped edge."""
        from tap_grid.edge_identity import _edge_identity_registry, register_edge_identity

        before = _edge_identity_registry.all()
        register_edge_identity(LINK, {"discriminators": []})
        try:
            ids = _seed("target")
            result = grift_import(
                _doc(
                    edges=[
                        {
                            **_edge(from_key=_key("nobody"), to_entity_id=ids["target"]),
                            "entity": {"ref": "e", "entity_type": "edge", "dimensions": {}},
                        }
                    ]
                ),
                dangling_edge_mode="permissive",
            )
            assert result.success, result.errors
            assert len(_skip_events()) == 1
        finally:
            _edge_identity_registry._reset_for_testing(before)

    @SPEC[6]
    @SPEC[7]
    @SPEC[8]
    def test_permissive_mode_skips_the_edge_and_records_it_in_the_batch(self) -> None:
        ids = _seed("target")
        fresh = _panel("lands")
        edge_id = str(uuid.uuid4())
        result = grift_import(
            _doc(nodes=[fresh], edges=[_edge(edge_id=edge_id, from_key=_key("nobody"), to_entity_id=ids["target"])]),
            dangling_edge_mode="permissive",
        )
        assert result.success, result.errors
        assert Entity.objects.filter(pk=uuid.UUID(fresh["entity"]["entity_id"])).exists(), "the rest of the batch lands"
        assert not Panel.objects.filter(slug="nobody").exists(), "a lookup never mints"
        (event,) = _skip_events()
        assert str(event.entity_id) == edge_id and event.entity_type == "edge"
        assert str(event.batch.entity_id) == result.imported_batches[0].batch_entity_id
        assert event.metadata["edge_type"] == LINK
        assert event.metadata["unresolved"] == [{"endpoint": "from", "entity_type": "panel", "key": {"slug": "nobody"}}]
        (skip,) = result.imported_batches[0].skips
        assert skip["event_id"] == str(event.id) and skip["edge_entity_id"] == edge_id

    @SPEC[7]
    def test_a_node_this_batch_creates_is_not_listed_as_unresolved(self) -> None:
        """The skip is recorded before the batch's nodes are written; a new node of the batch still resolves."""
        fresh = _panel("created-here")
        result = grift_import(
            _doc(nodes=[fresh], edges=[_edge(from_key=_key("nobody"), to_entity_id=fresh["entity"]["entity_id"])]),
            dangling_edge_mode="permissive",
        )
        assert result.success, result.errors
        (event,) = _skip_events()
        assert event.metadata["unresolved"] == [{"endpoint": "from", "entity_type": "panel", "key": {"slug": "nobody"}}]

    @SPEC[7]
    def test_an_id_endpoint_that_names_nothing_is_recorded_too(self) -> None:
        ids = _seed("target")
        missing = str(uuid.uuid4())
        result = grift_import(
            _doc(edges=[_edge(from_entity_id=missing, to_entity_id=ids["target"])]), dangling_edge_mode="permissive"
        )
        assert result.success, result.errors
        (event,) = _skip_events()
        assert event.metadata["unresolved"] == [{"endpoint": "from", "entity_id": missing}]

    @SPEC[7]
    def test_a_batch_that_fails_after_a_skip_writes_no_skip_event(self) -> None:
        """Ruled 2026-10-02: the skip event commits and rolls back with its batch."""
        ids = _seed("target")
        missing_target = {
            "on_missing": "error",
            "on_tombstoned": "ignore",
            "edges": [],
            "nodes": [{"entity_id": str(uuid.uuid4()), "entity_type": "panel", "reason": "not there"}],
        }
        result = grift_import(
            _doc(edges=[_edge(from_key=_key("nobody"), to_entity_id=ids["target"])], deletes=missing_target),
            dangling_edge_mode="permissive",
        )
        assert not result.success
        assert "removal_target_missing" in _codes(result)
        assert any(w.code == "dangling_edge" for w in result.warnings), "the failed batch still names the endpoint"
        assert _skip_events() == []


@pytest.mark.django_db
class TestForceReimport:
    @pytest.fixture(autouse=True)
    def _debug_on(self, settings: Any) -> None:
        settings.DEBUG = True  # force re-import is DEBUG-only

    @SPEC[6]
    def test_a_skipped_edge_keeps_no_dropped_node_alive(self) -> None:
        """A node the revision drops is swept even when a skipped edge of the revision names it."""
        source, target = _panel("source"), _panel("target")
        batch_id = _batch_entity_id()
        first = _minimal_doc([_batch_container(batch_id, nodes=[source, target])])
        assert grift_import(first).success
        skipped = _edge(from_entity_id=str(uuid.uuid4()), to_entity_id=source["entity"]["entity_id"])
        revised = _minimal_doc([_batch_container(batch_id, nodes=[target], edges=[skipped])])
        result = grift_import(revised, force_batches=[batch_id], dangling_edge_mode="permissive")
        assert result.success, result.errors
        assert Entity.objects.get(pk=uuid.UUID(source["entity"]["entity_id"])).deleted_at is not None
        assert len(_skip_events()) == 1

    @SPEC[6]
    @pytest.mark.xfail(
        strict=True,
        reason="Issue# 938 - tap: the force-reimport sweep never retires edges (candidates are CREATE events; "
        "edges are recorded as link).",
    )
    def test_an_edge_the_revision_skips_is_swept(self) -> None:
        source, target = _panel("source"), _panel("target")
        batch_id, edge_id = _batch_entity_id(), str(uuid.uuid4())

        def version(edge: dict[str, Any]) -> Any:
            return _minimal_doc([_batch_container(batch_id, nodes=[source, target], edges=[edge])])

        source_id, target_id = source["entity"]["entity_id"], target["entity"]["entity_id"]
        assert grift_import(version(_edge(edge_id=edge_id, from_entity_id=source_id, to_entity_id=target_id))).success
        revised = version(_edge(edge_id=edge_id, from_key=_key("nobody"), to_entity_id=target_id))
        result = grift_import(revised, force_batches=[batch_id], dangling_edge_mode="permissive")
        assert result.success, result.errors
        assert Entity.objects.get(pk=uuid.UUID(edge_id)).deleted_at is not None


@pytest.mark.django_db
class TestResolutionIsARead:
    @SPEC[9]
    def test_an_actor_refused_read_is_refused_the_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_auth import policy
        from tap_auth.capabilities import READ_CAPABILITY

        ids = _seed("source", "target")
        real_authorize = policy.authorize
        asked: list[str] = []

        def refuse_read(ctx: Any, capability: str, *args: Any, **kwargs: Any) -> Any:
            if capability == READ_CAPABILITY and kwargs.get("operation") == "grift_import_endpoint_keys":
                asked.append(capability)
                raise PermissionError("grid.read refused for this test")
            return real_authorize(ctx, capability, *args, **kwargs)

        monkeypatch.setattr(policy, "authorize", refuse_read)
        result = grift_import(_doc(edges=[_edge(from_key=_key("source"), to_entity_id=ids["target"])]))
        assert asked == [READ_CAPABILITY]
        assert not result.success
        assert _edges_between(ids["source"], ids["target"]) == []


@pytest.mark.django_db
class TestTheVerb:
    @SPEC[3]
    @pytest.mark.parametrize("properties", [{"slug__icontains": "x"}, {"slug": "x", "name": "y"}, {}])
    def test_find_by_natural_key_takes_exactly_the_declared_properties(self, properties: dict[str, Any]) -> None:
        from tap_grid.exceptions import ServiceValidationError
        from tap_grid.services import find_by_natural_key

        with pytest.raises(ServiceValidationError, match="found by exactly"):
            find_by_natural_key("panel", properties)


@pytest.mark.django_db
class TestTheRunRecord:
    @SPEC[8]
    def test_a_collector_run_names_each_skip_by_event_id(self) -> None:
        from tap_cares.collectors.base import CollectorBase
        from tap_cares.collectors.config import CollectorConfig

        class _Collector(CollectorBase):
            def run(self) -> None:  # pragma: no cover - submit_grift is called directly
                raise NotImplementedError

        collector = _Collector(CollectorConfig(collector_entity_id=uuid.uuid7(), collection_job_entity_id=uuid.uuid7()))
        ids = _seed("target")
        result = collector.submit_grift(
            _doc(edges=[_edge(from_key=_key("nobody"), to_entity_id=ids["target"])]), dangling_edge_mode="permissive"
        )
        (event,) = _skip_events()
        (warn,) = [w for w in collector.results["warn"] if w["message_code"] == "GRIFT_EDGES_SKIPPED"]
        assert warn["message_data"]["count"] == 1
        assert warn["message_data"]["skips"][0]["event_id"] == str(event.id)
        assert result.imported_batches[0].skips[0]["event_id"] == str(event.id)
