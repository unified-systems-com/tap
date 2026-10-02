"""Edge identity at import: a ref-addressed edge is found by its type's declared identity.

Spec: ``req-grid-edge-identity`` in ``tap_grid/specs/spec-grid-edge.md`` (Issue# 913 - tap).

The fixture edge types belong to grid_fixtures, which declares no identities yet
(unified-systems-com/grid-fixtures-tap#18), so each test declares the ones it needs for its own
duration and the registry is restored afterwards:

- ``PG_LINKS__grid_fixtures``: a plain key, identified by (type, source, target);
- ``SCHEMA_LINK__grid_fixtures``: discriminated by ``proficiency`` (in its property schema);
- ``WILDCARD_LINK__grid_fixtures``: keyless.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from tap_grid import edge_identity as edge_identity_module
from tap_grid.cascade_corpus.timing import finish, in_thread
from tap_grid.edge_identity import _edge_identity_registry, edge_lock_key, register_edge_identity
from tap_grid.exceptions import ServiceValidationError
from tap_grid.grift import grift_import
from tap_grid.models import Edge
from tap_grid.services import delete_edge_by_entity, resolve_edge_identity
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc

PLAIN = "PG_LINKS__grid_fixtures"
DISCRIMINATED = "SCHEMA_LINK__grid_fixtures"
KEYLESS = "WILDCARD_LINK__grid_fixtures"

SPEC = {n: pytest.mark.spec(f"req-grid-edge-identity-{n}") for n in (1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12, 13)}


@pytest.fixture
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


def _node(entity_id: str, entity_type: str = "grid_fixtures__node", name: str = "n") -> dict[str, Any]:
    return {
        "entity": {"entity_id": entity_id, "entity_type": entity_type, "name": name, "dimensions": {}},
        "node": {"name": name, "description": ""},
    }


def _edge(
    from_id: str, to_id: str, edge_type: str, *, ref: str | None = None, entity_id: str | None = None, **props: Any
) -> dict[str, Any]:
    envelope: dict[str, Any] = {"entity_type": "edge", "dimensions": {}}
    envelope.update({"ref": ref} if ref is not None else {"entity_id": entity_id or str(uuid.uuid4())})
    return {
        "entity": envelope,
        "edge": {"from_entity_id": from_id, "to_entity_id": to_id, "edge_type": edge_type, "properties": props},
    }


def _import(*edges: dict[str, Any], nodes: list[dict[str, Any]] | None = None) -> Any:
    return grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=nodes or [], edges=list(edges))]))


def _codes(result: Any) -> list[str]:
    return [e.code for e in result.errors]


def _live(edge_type: str, a: str, b: str) -> list[Any]:
    return list(Edge.objects.filter(edge_type=edge_type, from_entity_id=a, to_entity_id=b))  # live only


@pytest.fixture
def pair() -> tuple[str, str]:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    result = _import(nodes=[_node(a, name="a"), _node(b, name="b")])
    assert result.success, result.errors
    return a, b


@pytest.fixture
def schema_pair() -> tuple[str, str]:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    result = _import(
        nodes=[_node(a, "grid_fixtures__constrained_source", "src"), _node(b, "grid_fixtures__dual_endpoint", "dst")]
    )
    assert result.success, result.errors
    return a, b


@pytest.mark.django_db
@pytest.mark.usefixtures("declared")
class TestAPlainKey:
    @SPEC[2]
    @SPEC[10]
    def test_a_resent_ref_edge_finds_its_edge_and_replaces_it(self, pair: tuple[str, str]) -> None:
        a, b = pair
        assert _import(_edge(a, b, PLAIN, ref="e")).success
        (first,) = _live(PLAIN, a, b)
        second = _import(_edge(a, b, PLAIN, ref="e"))
        assert second.success, second.errors
        (again,) = _live(PLAIN, a, b)
        assert again.entity_id == first.entity_id, "found, not created"
        assert second.imported_batches[0].resolved_refs["e"] == str(first.entity_id)

    @SPEC[1]
    def test_the_same_type_between_other_endpoints_is_another_edge(self, pair: tuple[str, str]) -> None:
        a, b = pair
        c = str(uuid.uuid4())
        assert _import(_edge(a, b, PLAIN, ref="ab"), nodes=[_node(c, name="c")]).success
        assert _import(_edge(a, c, PLAIN, ref="ac")).success
        assert len(_live(PLAIN, a, b)) == 1 and len(_live(PLAIN, a, c)) == 1
        assert _live(PLAIN, a, b)[0].entity_id != _live(PLAIN, a, c)[0].entity_id

    @SPEC[3]
    def test_a_tombstoned_edge_is_not_found_and_a_return_gets_a_new_id(self, pair: tuple[str, str]) -> None:
        a, b = pair
        assert _import(_edge(a, b, PLAIN, ref="e")).success
        (gone,) = _live(PLAIN, a, b)
        assert delete_edge_by_entity(gone.entity_id).success
        back = _import(_edge(a, b, PLAIN, ref="e"))
        assert back.success, back.errors
        (returned,) = _live(PLAIN, a, b)
        assert returned.entity_id != gone.entity_id

    @SPEC[2]
    def test_two_live_matches_fail_the_whole_batch_naming_both(self, pair: tuple[str, str]) -> None:
        a, b = pair
        # Two live identical edges arrive by explicit id (no lookup); a ref then cannot choose.
        assert _import(_edge(a, b, PLAIN), _edge(a, b, PLAIN)).success
        ids = sorted(str(e.entity_id) for e in _live(PLAIN, a, b))
        c = str(uuid.uuid4())
        result = _import(_edge(a, b, PLAIN, ref="which"), nodes=[_node(c, name="c")])
        assert "identity_ambiguous" in _codes(result)
        message = next(e.message for e in result.errors if e.code == "identity_ambiguous")
        assert all(i in message for i in ids)
        assert not Edge.objects.filter(from_entity_id=a, to_entity_id=c).exists()
        from tap_grid.models import Entity

        assert not Entity.objects.filter(pk=uuid.UUID(c)).exists(), "the whole batch rolled back"

    @SPEC[9]
    def test_two_ref_edges_that_are_one_relationship_fail_the_batch(self, pair: tuple[str, str]) -> None:
        a, b = pair
        result = _import(_edge(a, b, PLAIN, ref="one"), _edge(a, b, PLAIN, ref="two"))
        assert "duplicate_edge" in _codes(result)
        assert _live(PLAIN, a, b) == []

    @SPEC[9]
    def test_a_ref_beside_an_explicit_edge_of_the_same_relationship_fails_the_batch(
        self, pair: tuple[str, str]
    ) -> None:
        a, b = pair
        result = _import(_edge(a, b, PLAIN), _edge(a, b, PLAIN, ref="again"))
        assert "duplicate_edge" in _codes(result)
        assert _live(PLAIN, a, b) == []

    @SPEC[11]
    def test_dimensions_do_not_participate(self, pair: tuple[str, str]) -> None:
        a, b = pair
        first = _edge(a, b, PLAIN, ref="e")
        first["entity"]["dimensions"] = {"tap.perspective": "one"}
        assert _import(first).success
        second = _edge(a, b, PLAIN, ref="e")
        second["entity"]["dimensions"] = {"tap.perspective": "two"}
        assert _import(second).success
        assert len(_live(PLAIN, a, b)) == 1


@pytest.mark.django_db
@pytest.mark.usefixtures("declared")
class TestADiscriminatedKey:
    @SPEC[2]
    def test_a_different_discriminator_is_a_second_relationship(self, schema_pair: tuple[str, str]) -> None:
        a, b = schema_pair
        assert _import(_edge(a, b, DISCRIMINATED, ref="n", proficiency="novice")).success
        assert _import(_edge(a, b, DISCRIMINATED, ref="m", proficiency="master")).success
        assert _import(_edge(a, b, DISCRIMINATED, ref="n2", proficiency="novice", primary=True)).success
        rows = _live(DISCRIMINATED, a, b)
        assert sorted(r.properties["proficiency"] for r in rows) == ["master", "novice"]
        (novice,) = [r for r in rows if r.properties["proficiency"] == "novice"]
        assert novice.properties.get("primary") is True, "the found edge was replaced"

    @SPEC[8]
    @pytest.mark.parametrize("props", [{}, {"proficiency": None}, {"proficiency": ""}])
    def test_an_absent_null_or_empty_discriminator_is_rejected(
        self, schema_pair: tuple[str, str], props: dict[str, Any]
    ) -> None:
        a, b = schema_pair
        for _ in range(2):  # re-importing never mints: each attempt is refused and writes nothing
            result = _import(_edge(a, b, DISCRIMINATED, ref="x", **props))
            assert "incomplete_edge_key" in _codes(result)
        assert _live(DISCRIMINATED, a, b) == []


@pytest.mark.django_db
@pytest.mark.usefixtures("declared")
class TestAKeylessType:
    @SPEC[5]
    def test_a_resent_keyless_edge_fails_its_batch(self, pair: tuple[str, str]) -> None:
        a, b = pair
        assert _import(_edge(a, b, KEYLESS, ref="k")).success
        result = _import(_edge(a, b, KEYLESS, ref="k"))
        assert "duplicate_edge" in _codes(result)
        assert len(_live(KEYLESS, a, b)) == 1

    @SPEC[5]
    def test_two_identical_keyless_edges_in_one_batch_fail_it(self, pair: tuple[str, str]) -> None:
        a, b = pair
        result = _import(_edge(a, b, KEYLESS, ref="k1"), _edge(a, b, KEYLESS))
        assert "duplicate_edge" in _codes(result)
        assert _live(KEYLESS, a, b) == []

    @SPEC[5]
    def test_another_spelling_of_the_same_endpoints_is_still_a_duplicate(self, pair: tuple[str, str]) -> None:
        a, b = pair
        result = _import(_edge(a, b, KEYLESS, ref="k1"), _edge(a.upper(), b.upper(), KEYLESS, ref="k2"))
        assert "duplicate_edge" in _codes(result)
        assert _live(KEYLESS, a, b) == []

    @SPEC[5]
    def test_an_edge_addressed_by_its_own_id_is_not_a_duplicate_of_itself(self, pair: tuple[str, str]) -> None:
        a, b = pair
        edge_id = str(uuid.uuid4())
        assert _import(_edge(a, b, KEYLESS, entity_id=edge_id)).success
        again = _import(_edge(a, b, KEYLESS, entity_id=edge_id))
        assert again.success, again.errors
        assert [str(e.entity_id) for e in _live(KEYLESS, a, b)] == [edge_id]

    @SPEC[5]
    def test_an_explicit_keyless_edge_beside_a_live_one_fails(self, pair: tuple[str, str]) -> None:
        a, b = pair
        assert _import(_edge(a, b, KEYLESS)).success
        result = _import(_edge(a, b, KEYLESS))
        assert "duplicate_edge" in _codes(result)
        assert len(_live(KEYLESS, a, b)) == 1


@pytest.mark.django_db
@pytest.mark.usefixtures("declared")
class TestAnUndeclaredType:
    """WILDCARD_LINK's sibling ALT_LINK declares nothing: warn mode until Issue# 928 - tap."""

    UNDECLARED = "ALT_LINK__grid_fixtures"

    @SPEC[6]
    def test_warn_mode_creates_as_before_and_logs(
        self, pair: tuple[str, str], caplog: pytest.LogCaptureFixture
    ) -> None:
        a, b = pair
        caplog.set_level(logging.WARNING, logger="tap_grid.grift.importer")
        assert _import(_edge(a, b, self.UNDECLARED, ref="u")).success
        result = _import(_edge(a, b, self.UNDECLARED, ref="u"))
        assert result.success and result.warnings == [], "warn mode changes no import result"
        assert len(_live(self.UNDECLARED, a, b)) == 2, "no lookup: a re-sent ref creates, as today"
        assert any("[9acf]" in r.getMessage() and self.UNDECLARED in r.getMessage() for r in caplog.records)

    @SPEC[6]
    def test_after_the_flip_an_undeclared_ref_edge_fails_its_batch(
        self, pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        a, b = pair
        monkeypatch.setattr(edge_identity_module, "ENFORCE_EDGE_IDENTITY_DECLARED", True)
        result = _import(_edge(a, b, self.UNDECLARED, ref="u"))
        assert "identity_undeclared" in _codes(result)
        assert _live(self.UNDECLARED, a, b) == []

    @SPEC[6]
    def test_an_explicit_id_edge_is_unaffected_by_the_declaration(
        self, pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        a, b = pair
        monkeypatch.setattr(edge_identity_module, "ENFORCE_EDGE_IDENTITY_DECLARED", True)
        assert _import(_edge(a, b, self.UNDECLARED)).success


@pytest.mark.django_db
@pytest.mark.usefixtures("declared")
class TestALookupIsARead:
    @SPEC[13]
    def test_an_actor_refused_read_is_refused_the_lookup_and_nothing_is_written(
        self, pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tap_auth import policy
        from tap_auth.capabilities import READ_CAPABILITY

        a, b = pair
        real_authorize = policy.authorize
        asked: list[str] = []

        def refuse_read(ctx: Any, capability: str, *args: Any, **kwargs: Any) -> Any:
            if capability == READ_CAPABILITY and kwargs.get("operation") == "grift_import_edge_identity":
                asked.append(capability)
                raise PermissionError("grid.read refused for this test")
            return real_authorize(ctx, capability, *args, **kwargs)

        monkeypatch.setattr(policy, "authorize", refuse_read)
        result = _import(_edge(a, b, PLAIN, ref="e"))
        assert asked == [READ_CAPABILITY], "the importer asked for read before looking an edge up"
        assert not result.success
        assert _live(PLAIN, a, b) == []

    @SPEC[13]
    @SPEC[6]
    def test_an_undeclared_ref_in_warn_mode_reads_nothing_and_needs_no_read(
        self, pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Warn mode leaves the import exactly as it was, authorisation included."""
        from tap_auth import policy
        from tap_auth.capabilities import READ_CAPABILITY

        a, b = pair
        real_authorize = policy.authorize

        def refuse_read(ctx: Any, capability: str, *args: Any, **kwargs: Any) -> Any:
            if capability == READ_CAPABILITY and kwargs.get("operation") in (
                "grift_import_edge_identity",
                "resolve_edge_identity",
            ):
                raise PermissionError("grid.read refused for this test")
            return real_authorize(ctx, capability, *args, **kwargs)

        monkeypatch.setattr(policy, "authorize", refuse_read)
        result = _import(_edge(a, b, "ALT_LINK__grid_fixtures", ref="u"))
        assert result.success, result.errors
        assert len(_live("ALT_LINK__grid_fixtures", a, b)) == 1

    @SPEC[13]
    def test_the_verb_itself_requires_read(self, pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
        """Gated at the service boundary, not only by the importer: any caller is refused."""
        from tap_auth import policy
        from tap_auth.capabilities import READ_CAPABILITY

        a, b = pair
        real_authorize = policy.authorize

        def refuse_read(ctx: Any, capability: str, *args: Any, **kwargs: Any) -> Any:
            if capability == READ_CAPABILITY and kwargs.get("operation") == "resolve_edge_identity":
                raise PermissionError("grid.read refused for this test")
            return real_authorize(ctx, capability, *args, **kwargs)

        monkeypatch.setattr(policy, "authorize", refuse_read)
        with transaction.atomic(), pytest.raises(PermissionError):
            resolve_edge_identity(PLAIN, a, b, {})

    @SPEC[13]
    def test_an_import_with_no_lookup_does_not_ask_for_read(
        self, pair: tuple[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tap_auth import policy
        from tap_auth.capabilities import READ_CAPABILITY

        a, b = pair
        real_authorize = policy.authorize
        asked: list[str] = []

        def record(ctx: Any, capability: str, *args: Any, **kwargs: Any) -> Any:
            if capability == READ_CAPABILITY and kwargs.get("operation") == "grift_import_edge_identity":
                asked.append(capability)
            return real_authorize(ctx, capability, *args, **kwargs)

        monkeypatch.setattr(policy, "authorize", record)
        assert _import(_edge(a, b, PLAIN)).success
        assert asked == []


@pytest.mark.django_db
@pytest.mark.usefixtures("declared")
class TestTheVerb:
    @SPEC[4]
    def test_two_spellings_of_one_endpoint_find_one_edge(self, pair: tuple[str, str]) -> None:
        a, b = pair
        assert _import(_edge(a, b, PLAIN, ref="e")).success
        (edge,) = _live(PLAIN, a, b)
        with transaction.atomic():
            resolution = resolve_edge_identity(PLAIN, a.upper(), b.replace("-", ""), {})
        assert resolution.found and resolution.entity_id == edge.entity_id

    @SPEC[4]
    def test_a_non_uuid_endpoint_is_refused(self) -> None:
        with transaction.atomic(), pytest.raises(ServiceValidationError, match="entity UUIDs"):
            resolve_edge_identity(PLAIN, "not-a-uuid", str(uuid.uuid4()), {})

    @SPEC[6]
    def test_an_undeclared_type_is_reported_not_looked_up(self, pair: tuple[str, str]) -> None:
        a, b = pair
        with transaction.atomic():
            resolution = resolve_edge_identity("ALT_LINK__grid_fixtures", a, b, {})
        assert resolution.undeclared and not resolution.found and resolution.key is None

    @SPEC[12]
    def test_each_looked_up_edge_costs_a_fixed_number_of_queries(self, pair: tuple[str, str]) -> None:
        """The cost the spec asks to record: per looked-up edge, one advisory lock and one bounded
        search over the endpoint-and-type index. Counted, not planned: a plan assertion depends
        on the planner's tie-breaks (Issue# 925 - tap)."""
        a, b = pair
        with transaction.atomic():
            with CaptureQueriesContext(connection) as queries:
                resolve_edge_identity(PLAIN, a, b, {})
        sql = [q["sql"] for q in queries]
        locks = [s for s in sql if "pg_advisory_xact_lock" in s]
        searches = [s for s in sql if '"tap_edge"' in s]
        assert len(locks) == 1 and len(searches) == 1, sql
        assert "LIMIT 11" in searches[0]
        assert sql.index(locks[0]) < sql.index(searches[0]), "the lock is taken before the grid is read"


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("declared")
class TestOutsideATransaction:
    @SPEC[4]
    def test_the_verb_refuses_to_run_without_one(self) -> None:
        """The lock is transaction-scoped; resolution outside one would release it before the write."""
        with pytest.raises(ServiceValidationError, match="inside the caller's transaction"):
            resolve_edge_identity(PLAIN, str(uuid.uuid4()), str(uuid.uuid4()), {})


@SPEC[4]
def test_the_lock_key_is_a_function_of_the_identity() -> None:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    assert edge_lock_key(PLAIN, a, b, {}) == edge_lock_key(PLAIN, uuid.UUID(a), uuid.UUID(b), {})
    # One endpoint, one lock, however it is spelled: upper case and hyphenless are the same UUID.
    assert edge_lock_key(PLAIN, a, b, {}) == edge_lock_key(PLAIN, a.upper(), b.replace("-", ""), {})
    assert edge_lock_key(PLAIN, a, b, {}) != edge_lock_key(PLAIN, b, a, {}), "direction is part of identity"
    assert edge_lock_key(PLAIN, a, b, {}) != edge_lock_key(KEYLESS, a, b, {})
    assert edge_lock_key(DISCRIMINATED, a, b, {"proficiency": "novice"}) != edge_lock_key(
        DISCRIMINATED, a, b, {"proficiency": "master"}
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("declared")
class TestTwoWriters:
    @SPEC[4]
    def test_two_concurrent_imports_of_one_ref_edge_make_one_edge(self, pair: tuple[str, str]) -> None:
        a, b = pair
        first = in_thread(lambda: _import(_edge(a, b, PLAIN, ref="race")))
        second = in_thread(lambda: _import(_edge(a, b, PLAIN, ref="race")))
        finish(first, second)
        r1, r2 = first[1].value, second[1].value
        assert r1.success and r2.success, (r1.errors, r2.errors)
        assert len(_live(PLAIN, a, b)) == 1

    @SPEC[4]
    def test_two_concurrent_keyless_imports_make_one_edge_and_one_failure(self, pair: tuple[str, str]) -> None:
        a, b = pair
        first = in_thread(lambda: _import(_edge(a, b, KEYLESS, ref="race")))
        second = in_thread(lambda: _import(_edge(a, b, KEYLESS, ref="race")))
        finish(first, second)
        outcomes = sorted([first[1].value.success, second[1].value.success])
        assert outcomes == [False, True]
        assert len(_live(KEYLESS, a, b)) == 1
