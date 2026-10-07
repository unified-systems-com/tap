"""Identity locks are taken in one order per batch, so two batches never deadlock on them; and a
permissive batch that skips an edge still reports the removals it committed.

Issue# 943 - tap: the importer took each identity lock as it looked an object up, in document
order. Two batches naming the same identities in opposite orders could each hold one lock while
waiting for the other's, and Postgres failed one of them. Every lock is now taken up front, sorted:
node keys, then edge keys (ref edges, keyless duplicate checks and deletes by identity together).
Spec: ``req-grid-edge-identity-4`` (``tap_grid/specs/spec-grid-edge.md``) and
``req-grid-entity-natural-key-13``'s lock (``spec-grid-entity.md``).

Issue# 962 - tap: in permissive mode a skipped dangling edge is a warning, and the batch commits,
but the per-batch removal counters were reset as if it had rolled back.

Each concurrency test holds each batch after its first lookup until the other has made one too.
Taken in document order that interleaving is the deadlock; taken in sorted order the second batch
queues on the first lock, the barrier times out, and both batches succeed.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from tap_grid.cascade_corpus.timing import finish, in_thread
from tap_grid.edge_identity import _edge_identity_registry, register_edge_identity
from tap_grid.grift import grift_import
from tap_grid.models import Edge, Entity
from tap_grid.services import resolve_edge_identity, resolve_identity
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc

PLAIN = "PG_LINKS__grid_fixtures"
WEB = {"tap.graph": "web"}


@pytest.fixture(autouse=True)
def declared() -> Iterator[None]:
    before = _edge_identity_registry.all()
    register_edge_identity(PLAIN, {"discriminators": []})
    yield
    _edge_identity_registry._reset_for_testing(before)


def _node(name: str) -> dict[str, Any]:
    return {
        "entity": {
            "entity_id": str(uuid.uuid4()),
            "entity_type": "grid_fixtures__node",
            "name": name,
            "dimensions": {},
        },
        "node": {"name": name, "description": ""},
    }


def _ref_panel(ref: str) -> dict[str, Any]:
    """A panel addressed by ref, found by its natural key, ``slug``."""
    return {
        "entity": {"ref": ref, "entity_type": "panel", "name": ref, "dimensions": WEB},
        "node": {"name": ref, "slug": f"lock-order-{ref}", "description": "", "view": "tap_web/panel_error.html"},
    }


def _edge(from_id: str, to_id: str, *, ref: str | None = None, entity_id: str | None = None) -> dict[str, Any]:
    envelope: dict[str, Any] = {"entity_type": "edge", "dimensions": {}}
    envelope.update({"ref": ref} if ref is not None else {"entity_id": entity_id or str(uuid.uuid4())})
    return {
        "entity": envelope,
        "edge": {"from_entity_id": from_id, "to_entity_id": to_id, "edge_type": PLAIN, "properties": {}},
    }


def _import(*, nodes: tuple[Any, ...] = (), edges: tuple[Any, ...] = (), **options: Any) -> Any:
    container = _batch_container(_batch_entity_id(), nodes=list(nodes), edges=list(edges))
    container.update(options.pop("sections", {}))
    return grift_import(_minimal_doc([container]), **options)


def _seed(*names: str) -> list[str]:
    nodes = [_node(n) for n in names]
    result = _import(nodes=tuple(nodes))
    assert result.success, result.errors
    return [n["entity"]["entity_id"] for n in nodes]


def _wait_after_first(real: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a lookup verb: each batch's first call waits until the other batch has made one too."""
    both_looked = threading.Barrier(2, timeout=3)
    waited = threading.local()

    def look_up_then_wait(*args: Any, **kwargs: Any) -> Any:
        found = real(*args, **kwargs)
        if not getattr(waited, "once", False):
            waited.once = True
            try:
                both_looked.wait()
            except threading.BrokenBarrierError:
                pass  # the other batch is queued on this one's lock, which is the point
        return found

    return look_up_then_wait


@pytest.mark.django_db(transaction=True)
class TestOppositeOrders:
    @pytest.mark.spec("req-grid-edge-identity-4")
    def test_two_batches_upserting_the_same_ref_edges_in_opposite_orders_both_succeed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tap_grid.grift import importer

        a, b, c = _seed("a", "b", "c")
        monkeypatch.setattr(importer, "resolve_edge_identity", _wait_after_first(resolve_edge_identity))
        forward = (_edge(a, b, ref="ab"), _edge(a, c, ref="ac"))
        first = in_thread(lambda: _import(edges=forward))
        second = in_thread(lambda: _import(edges=tuple(reversed(forward))))
        finish(first, second)
        r1, r2 = first[1].value, second[1].value
        assert r1.success and r2.success, (r1.errors, r2.errors)
        for target in (b, c):
            assert Edge.objects.filter(edge_type=PLAIN, from_entity_id=a, to_entity_id=target).count() == 1

    @pytest.mark.spec("req-grid-entity-natural-key-13")
    def test_two_batches_naming_the_same_ref_nodes_in_opposite_orders_both_succeed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tap_grid.grift import importer

        monkeypatch.setattr(importer, "resolve_identity", _wait_after_first(resolve_identity))
        forward = (_ref_panel("p"), _ref_panel("q"))
        first = in_thread(lambda: _import(nodes=forward))
        second = in_thread(lambda: _import(nodes=tuple(reversed(forward))))
        finish(first, second)
        r1, r2 = first[1].value, second[1].value
        assert r1.success and r2.success, (r1.errors, r2.errors)
        for slug in ("lock-order-p", "lock-order-q"):
            assert Entity.objects.filter(entity_type="panel", name=slug.removeprefix("lock-order-")).count() == 1


@pytest.mark.django_db
class TestAPermissiveBatchCountsWhatItCommitted:
    @pytest.mark.spec("req-grid-import-grift-results")
    def test_a_skipped_dangling_edge_leaves_the_committed_deletes_counted(self) -> None:
        a, b = _seed("a", "b")
        (existing,) = [str(uuid.uuid4())]
        assert _import(edges=(_edge(a, b, entity_id=existing),)).success
        dangling = _edge(a, str(uuid.uuid4()))  # an endpoint that names nothing: skipped in permissive mode
        result = _import(
            edges=(dangling,),
            sections={
                "deletes": {
                    "on_missing": "error",
                    "on_tombstoned": "ignore",
                    "edges": [{"entity_id": existing, "entity_type": "edge", "reason": "no longer observed"}],
                    "nodes": [],
                }
            },
            dangling_edge_mode="permissive",
        )
        assert result.success, result.errors
        (batch,) = result.imported_batches
        assert (batch.edges_deleted, batch.edges_skipped, batch.errors_count) == (1, 1, 0)
        assert Entity.objects.get(pk=existing).deleted_at is not None
