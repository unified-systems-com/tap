"""Removal by edge identity: a `deletes.edges` target names its edge by identity and ends the live match.

Spec: ``req-grid-import-grift-edge-removal`` in ``tap_grid/specs/spec-grid-import-grift.md``
(Issue# 915 - tap). The fixture edge types belong to grid_fixtures, which declares no identities
yet, so the tests declare them for their own duration, as ``test_grift_edge_identity`` does:

- ``PG_LINKS__grid_fixtures``: a plain key, identified by (type, source, target);
- ``SCHEMA_LINK__grid_fixtures``: discriminated by ``proficiency``;
- ``WILDCARD_LINK__grid_fixtures``: keyless.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from django.db import transaction

from tap_grid.cascade_corpus.timing import finish, in_thread
from tap_grid.edge_identity import IncompleteEdgeKey, _edge_identity_registry, register_edge_identity
from tap_grid.exceptions import ServiceValidationError
from tap_grid.grift import grift_import
from tap_grid.models import Edge, Entity
from tap_grid.natural_key import AmbiguousIdentity
from tap_grid.services import delete_edge_by_entity, find_edge_by_identity
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc
from tap_grid.tests.test_grift_edge_endpoints import _key, _panel

PLAIN = "PG_LINKS__grid_fixtures"
DISCRIMINATED = "SCHEMA_LINK__grid_fixtures"
KEYLESS = "WILDCARD_LINK__grid_fixtures"

SPEC = {n: pytest.mark.spec(f"req-grid-import-grift-edge-removal-{n}") for n in range(1, 9)}


@pytest.fixture(autouse=True)
def declared() -> Iterator[None]:
    before = _edge_identity_registry.all()
    register_edge_identity(PLAIN, {"discriminators": []})
    register_edge_identity(
        DISCRIMINATED,
        {"discriminators": [{"path": "proficiency", "description": "The skill level; two can hold at once."}]},
    )
    register_edge_identity(KEYLESS, {"keyless": {"reason": "fixture: every submission is a new edge"}})
    yield
    _edge_identity_registry._reset_for_testing(before)


def _node(entity_type: str = "grid_fixtures__node", name: str = "n") -> dict[str, Any]:
    return {
        "entity": {"entity_id": str(uuid.uuid4()), "entity_type": entity_type, "name": name, "dimensions": {}},
        "node": {"name": name, "description": ""},
    }


def _edge(from_id: str, to_id: str, edge_type: str = PLAIN, *, entity_id: str | None = None, **props: Any) -> Any:
    return {
        "entity": {"entity_id": entity_id or str(uuid.uuid4()), "entity_type": "edge", "dimensions": {}},
        "edge": {"from_entity_id": from_id, "to_entity_id": to_id, "edge_type": edge_type, "properties": props},
    }


def _import(
    *, nodes: tuple[Any, ...] = (), edges: tuple[Any, ...] = (), deletes: Any = None, purges: Any = None
) -> Any:
    container = _batch_container(_batch_entity_id(), nodes=list(nodes), edges=list(edges))
    if deletes is not None:
        container["deletes"] = deletes
    if purges is not None:
        container["purges"] = purges
    return grift_import(_minimal_doc([container]))


def _deletes(*edges: Any, nodes: tuple[Any, ...] = (), on_missing: str = "error", on_tombstoned: str = "ignore") -> Any:
    return {"on_missing": on_missing, "on_tombstoned": on_tombstoned, "edges": list(edges), "nodes": list(nodes)}


def _by_identity(source: Any, target: Any, edge_type: str = PLAIN, **extra: Any) -> dict[str, Any]:
    return {"edge_type": edge_type, "from": source, "to": target, "reason": "no longer observed", **extra}


def _at(entity_id: str) -> dict[str, str]:
    return {"entity_id": entity_id}


def _codes(result: Any) -> list[str]:
    return [e.code for e in result.errors]


def _ids(*nodes: Any) -> list[str]:
    result = _import(nodes=nodes)
    assert result.success, result.errors
    return [n["entity"]["entity_id"] for n in nodes]


def _write(*edges: Any) -> list[str]:
    result = _import(edges=edges)
    assert result.success, result.errors
    return [e["entity"]["entity_id"] for e in edges]


def _live(entity_id: str) -> bool:
    return Entity.objects.get(pk=uuid.UUID(entity_id)).deleted_at is None


@pytest.fixture
def pair() -> tuple[str, str]:
    a, b = _ids(_node(name="a"), _node(name="b"))
    return a, b


@pytest.fixture
def schema_pair() -> tuple[str, str]:
    a, b = _ids(_node("grid_fixtures__constrained_source", "src"), _node("grid_fixtures__dual_endpoint", "dst"))
    return a, b


@pytest.mark.django_db
class TestTheShape:
    @SPEC[1]
    def test_an_id_and_an_identity_together_is_a_schema_failure(self, pair: tuple[str, str]) -> None:
        a, b = pair
        (edge,) = _write(_edge(a, b))
        both = {**_by_identity(_at(a), _at(b)), "entity_id": edge, "entity_type": "edge"}
        result = _import(deletes=_deletes(both))
        assert "schema_validation_failed" in _codes(result)
        assert _live(edge)

    @SPEC[1]
    def test_neither_form_is_a_schema_failure(self) -> None:
        result = _import(deletes=_deletes({"reason": "names nothing"}))
        assert "schema_validation_failed" in _codes(result)

    @SPEC[1]
    def test_a_node_delete_takes_no_identity_form(self, pair: tuple[str, str]) -> None:
        a, b = pair
        result = _import(deletes=_deletes(nodes=(_by_identity(_at(a), _at(b)),)))
        assert "schema_validation_failed" in _codes(result)

    @SPEC[1]
    def test_a_purge_takes_no_identity_form(self, pair: tuple[str, str], settings: Any) -> None:
        settings.DEBUG = True  # purges are DEBUG-only; the refusal must be the shape's
        a, b = pair
        (edge,) = _write(_edge(a, b))
        result = _import(purges={"on_missing": "error", "edges": [_by_identity(_at(a), _at(b))], "nodes": []})
        assert "schema_validation_failed" in _codes(result)
        assert _live(edge)

    @SPEC[7]
    def test_an_expected_version_is_a_schema_failure(self, pair: tuple[str, str]) -> None:
        a, b = pair
        (edge,) = _write(_edge(a, b))
        result = _import(deletes=_deletes(_by_identity(_at(a), _at(b), entity_expected_version=1)))
        assert "schema_validation_failed" in _codes(result)
        assert _live(edge)


@pytest.mark.django_db
class TestTheLiveMatch:
    @SPEC[2]
    def test_it_ends_the_live_edge_and_no_other(self, pair: tuple[str, str]) -> None:
        a, b = pair
        (c,) = _ids(_node(name="c"))
        ab, ac = _write(_edge(a, b), _edge(a, c))
        result = _import(deletes=_deletes(_by_identity(_at(a), _at(b))))
        assert result.success, result.errors
        assert not _live(ab)
        assert _live(ac)
        assert result.counts.edges_deleted == 1

    @SPEC[2]
    def test_endpoints_named_by_key_are_found_on_the_grid(self) -> None:
        source, target = _panel("source"), _panel("target")
        a, b = _ids(source, target)
        (edge,) = _write(_edge(a, b))
        result = _import(deletes=_deletes(_by_identity(_key("source"), _key("target"))))
        assert result.success, result.errors
        assert not _live(edge)

    @SPEC[2]
    def test_the_discriminators_pick_the_edge(self, schema_pair: tuple[str, str]) -> None:
        a, b = schema_pair
        master, novice = _write(
            _edge(a, b, DISCRIMINATED, proficiency="master"), _edge(a, b, DISCRIMINATED, proficiency="novice")
        )
        target = _by_identity(_at(a), _at(b), DISCRIMINATED, discriminators={"proficiency": "master"})
        result = _import(deletes=_deletes(target))
        assert result.success, result.errors
        assert not _live(master)
        assert _live(novice)

    @SPEC[2]
    def test_no_live_match_is_missing_and_an_error_by_default(self, pair: tuple[str, str]) -> None:
        a, b = pair
        result = _import(deletes=_deletes(_by_identity(_at(a), _at(b))))
        assert _codes(result) == ["removal_target_missing"]

    @SPEC[2]
    @pytest.mark.parametrize(("on_missing", "warned"), [("warn", True), ("ignore", False)])
    def test_no_live_match_follows_on_missing(self, pair: tuple[str, str], on_missing: str, warned: bool) -> None:
        a, b = pair
        result = _import(deletes=_deletes(_by_identity(_at(a), _at(b)), on_missing=on_missing))
        assert result.success, result.errors
        assert any(w.code == "removal_target_missing_warned" for w in result.warnings) is warned

    @SPEC[2]
    def test_an_endpoint_key_that_names_nothing_is_missing(self, pair: tuple[str, str]) -> None:
        a, b = pair
        (edge,) = _write(_edge(a, b))
        result = _import(deletes=_deletes(_by_identity(_key("nobody"), _at(b))))
        assert _codes(result) == ["removal_target_missing"]
        assert _live(edge)

    @SPEC[2]
    def test_a_tombstoned_edge_never_matches_so_on_tombstoned_does_not_apply(self, pair: tuple[str, str]) -> None:
        a, b = pair
        (edge,) = _write(_edge(a, b))
        assert delete_edge_by_entity(edge).success
        result = _import(deletes=_deletes(_by_identity(_at(a), _at(b)), on_missing="ignore", on_tombstoned="error"))
        assert result.success, result.errors


@pytest.mark.django_db
class TestReplay:
    @SPEC[3]
    def test_a_replayed_delete_ends_the_edge_that_came_back(self, pair: tuple[str, str]) -> None:
        a, b = pair
        target = _by_identity(_at(a), _at(b))
        (first,) = _write(_edge(a, b))
        assert _import(deletes=_deletes(target)).success
        (returned,) = _write(_edge(a, b))  # the relationship returns under a new id
        assert returned != first and _live(returned)
        replay = _import(deletes=_deletes(target))
        assert replay.success, replay.errors
        assert not _live(returned)
        assert not _live(first)


@pytest.mark.django_db(transaction=True)
class TestTwoDeleters:
    @SPEC[2]
    def test_ending_the_same_edges_in_opposite_orders_does_not_deadlock(
        self, pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each batch looks one edge up, then waits until the other has looked one up too.

        Taken in document order, each batch would hold one edge's lock while waiting for the
        other's, a deadlock Postgres breaks by failing one batch. Taken in lock-key order, both
        batches start with the same edge: the second waits for the first to commit, and both succeed.
        """
        from tap_grid.grift import importer

        a, b = pair
        (c,) = _ids(_node(name="c"))
        ab, ac = _write(_edge(a, b), _edge(a, c))
        both_looked = threading.Barrier(2, timeout=3)
        real_lookup = find_edge_by_identity  # the function the importer imported
        waited = threading.local()

        def look_up_then_wait(*args: Any, **kwargs: Any) -> Any:
            found = real_lookup(*args, **kwargs)
            if not getattr(waited, "once", False):
                waited.once = True
                try:
                    both_looked.wait()
                except threading.BrokenBarrierError:
                    pass  # the other batch is queued on this one's lock, which is the point
            return found

        monkeypatch.setattr(importer, "find_edge_by_identity", look_up_then_wait)
        forward = (_by_identity(_at(a), _at(b)), _by_identity(_at(a), _at(c)))
        first = in_thread(lambda: _import(deletes=_deletes(*forward, on_missing="ignore")))
        second = in_thread(lambda: _import(deletes=_deletes(*reversed(forward), on_missing="ignore")))
        finish(first, second)
        r1, r2 = first[1].value, second[1].value
        assert r1.success and r2.success, (r1.errors, r2.errors)
        assert not _live(ab) and not _live(ac)


@pytest.mark.django_db
class TestAmbiguity:
    @SPEC[4]
    def test_two_live_matches_abort_the_batch_naming_both(self, pair: tuple[str, str]) -> None:
        a, b = pair
        (one,) = _write(_edge(a, b))  # explicit ids bypass the lookup, so two can stand
        (two,) = _write(_edge(a, b))
        result = _import(deletes=_deletes(_by_identity(_at(a), _at(b))))
        assert _codes(result) == ["identity_ambiguous"]
        assert one in result.errors[0].message and two in result.errors[0].message
        assert _live(one) and _live(two)


@pytest.mark.django_db
class TestAnIncompleteIdentity:
    @SPEC[5]
    @pytest.mark.parametrize("discriminators", [None, {"proficiency": None}, {"proficiency": ""}])
    def test_a_missing_null_or_empty_discriminator_is_refused(
        self, schema_pair: tuple[str, str], discriminators: Any
    ) -> None:
        a, b = schema_pair
        (edge,) = _write(_edge(a, b, DISCRIMINATED, proficiency="master"))
        extra = {} if discriminators is None else {"discriminators": discriminators}
        result = _import(deletes=_deletes(_by_identity(_at(a), _at(b), DISCRIMINATED, **extra)))
        assert _codes(result) == ["incomplete_edge_key"]
        assert _live(edge)

    @SPEC[5]
    def test_an_undeclared_discriminator_is_refused(self, schema_pair: tuple[str, str]) -> None:
        a, b = schema_pair
        named = {"proficiency": "master", "since": "2026"}
        result = _import(deletes=_deletes(_by_identity(_at(a), _at(b), DISCRIMINATED, discriminators=named)))
        assert _codes(result) == ["schema_validation_failed"]

    @SPEC[5]
    def test_discriminators_on_a_plain_type_are_refused(self, pair: tuple[str, str]) -> None:
        a, b = pair
        result = _import(deletes=_deletes(_by_identity(_at(a), _at(b), discriminators={"proficiency": "x"})))
        assert _codes(result) == ["schema_validation_failed"]

    @SPEC[5]
    @pytest.mark.parametrize("edge_type", [KEYLESS, "UNDECLARED_LINK__grid_fixtures"])
    def test_a_keyless_or_undeclared_type_cannot_be_named_by_identity(
        self, pair: tuple[str, str], edge_type: str
    ) -> None:
        a, b = pair
        result = _import(deletes=_deletes(_by_identity(_at(a), _at(b), edge_type)))
        assert _codes(result) == ["removal_identity_unkeyed"]


@pytest.mark.django_db
class TestDuplicates:
    @SPEC[6]
    def test_an_id_target_and_an_identity_target_of_one_edge(self, pair: tuple[str, str]) -> None:
        a, b = pair
        (edge,) = _write(_edge(a, b))
        by_id = {"entity_id": edge, "entity_type": "edge", "reason": "gone"}
        result = _import(deletes=_deletes(by_id, _by_identity(_at(a), _at(b))))
        assert _codes(result) == ["duplicate_removal_target"]
        assert _live(edge)

    @SPEC[6]
    def test_two_identity_targets_of_one_edge(self, pair: tuple[str, str]) -> None:
        a, b = pair
        (edge,) = _write(_edge(a, b))
        result = _import(deletes=_deletes(_by_identity(_at(a), _at(b)), _by_identity(_at(a), _at(b))))
        assert _codes(result) == ["duplicate_removal_target"]
        assert _live(edge)

    @SPEC[6]
    def test_an_edge_the_batch_also_upserts(self, pair: tuple[str, str]) -> None:
        a, b = pair
        (edge,) = _write(_edge(a, b))
        result = _import(edges=(_edge(a, b, entity_id=edge),), deletes=_deletes(_by_identity(_at(a), _at(b))))
        assert _codes(result) == ["entity_id_in_upsert_and_removal"]
        assert _live(edge)


@pytest.mark.django_db
class TestResolutionIsARead:
    @SPEC[8]
    def test_an_actor_refused_read_is_refused_the_resolution(
        self, pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tap_auth import policy
        from tap_auth.capabilities import READ_CAPABILITY

        a, b = pair
        (edge,) = _write(_edge(a, b))
        real_authorize = policy.authorize
        asked: list[str] = []

        def refuse_read(ctx: Any, capability: str, *args: Any, **kwargs: Any) -> Any:
            if capability == READ_CAPABILITY and kwargs.get("operation") == "grift_import_removal_identity":
                asked.append(capability)
                raise PermissionError("grid.read refused for this test")
            return real_authorize(ctx, capability, *args, **kwargs)

        monkeypatch.setattr(policy, "authorize", refuse_read)
        result = _import(deletes=_deletes(_by_identity(_at(a), _at(b))))
        assert asked == [READ_CAPABILITY]
        assert not result.success
        assert _live(edge)


@pytest.mark.django_db
class TestASkippedBatch:
    def test_its_warning_counts_identity_targets(self, pair: tuple[str, str]) -> None:
        a, b = pair
        container = _batch_container(_batch_entity_id())
        assert grift_import(_minimal_doc([container])).success
        container["deletes"] = _deletes(_by_identity(_at(a), _at(b)))
        result = grift_import(_minimal_doc([container]))
        (warning,) = [w for w in result.warnings if w.code == "skipped_batch_had_removals"]
        assert "deletes.edges=1" in warning.message


@pytest.mark.django_db
class TestTheVerb:
    @SPEC[2]
    def test_it_finds_the_live_edge_or_nothing(self, pair: tuple[str, str]) -> None:
        a, b = pair
        (edge,) = _write(_edge(a, b))
        with transaction.atomic():
            assert str(find_edge_by_identity(PLAIN, a, b, {})) == edge
            assert find_edge_by_identity(PLAIN, b, a, {}) is None

    @SPEC[4]
    def test_two_live_matches_are_ambiguous(self, pair: tuple[str, str]) -> None:
        a, b = pair
        _write(_edge(a, b))
        _write(_edge(a, b))
        with transaction.atomic(), pytest.raises(AmbiguousIdentity):
            find_edge_by_identity(PLAIN, a, b, {})

    @SPEC[5]
    @pytest.mark.parametrize(
        ("edge_type", "discriminators"),
        [(KEYLESS, {}), ("UNDECLARED_LINK__grid_fixtures", {}), (DISCRIMINATED, {}), (PLAIN, {"x": 1})],
    )
    def test_only_a_plain_identity_by_exactly_its_paths(
        self, pair: tuple[str, str], edge_type: str, discriminators: dict[str, Any]
    ) -> None:
        a, b = pair
        with transaction.atomic(), pytest.raises(ServiceValidationError):
            find_edge_by_identity(edge_type, a, b, discriminators)

    @SPEC[5]
    def test_an_empty_discriminator_is_refused(self, schema_pair: tuple[str, str]) -> None:
        a, b = schema_pair
        with transaction.atomic(), pytest.raises(IncompleteEdgeKey):
            find_edge_by_identity(DISCRIMINATED, a, b, {"proficiency": ""})


@pytest.mark.django_db(transaction=True)
class TestOutsideATransaction:
    def test_the_verb_refuses_to_run_without_one(self) -> None:
        """The lock is transaction-scoped; a match outside one would release it before the delete."""
        with pytest.raises(ServiceValidationError, match="inside the caller's transaction"):
            find_edge_by_identity(PLAIN, str(uuid.uuid4()), str(uuid.uuid4()), {})


@pytest.mark.django_db
def test_a_deleted_edge_stays_deleted_on_a_second_identity_delete(pair: tuple[str, str]) -> None:
    """Ending a relationship twice is the second delete finding nothing, not an error about the first."""
    a, b = pair
    (edge,) = _write(_edge(a, b))
    target = _by_identity(_at(a), _at(b))
    assert _import(deletes=_deletes(target)).success
    again = _import(deletes=_deletes(target, on_missing="ignore"))
    assert again.success, again.errors
    assert not _live(edge)
    assert Edge.all_objects.filter(entity_id=uuid.UUID(edge)).count() == 1
