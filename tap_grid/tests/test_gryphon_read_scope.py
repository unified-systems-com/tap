"""Read scope — every Gryphon read sees only live nodes and edges (`req-grid-traversal-exec-read-scope`).

Repro corpus for `Issue# 811 - tap`: liveness was a side effect of which model a queryset
started from. `Edge.objects` is a `LiveManager`, so a retired edge at hop 0 of a pattern was
excluded, while the same edge reached through a join (hop >= 1, an endpoint, a NOT EXISTS inner
hop, an OPTIONAL MATCH count) was not. Each test below names the shape and asserts the answer a
reader of the grid would expect; the non-vacuity tests pin that the same queries still return
the live answer when nothing is retired.

The graph is built fresh per test from the neutral `grid_fixtures__node` vocabulary:

    A -PG_LINKS-> B -PG_LINKS-> C          (the two-hop chain)
    A -PG_LINKS-> D                        (a second out-edge of A, for counts)
    G -PG_OPTIONAL-> H -PG_OPTIONAL-> B    (a two-hop guard chain onto B)
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

import pytest

from tap_grid.exceptions import SearchExecutionError
from tap_grid.models import Search
from tap_grid.search import execute_search

LINKS = "PG_LINKS__grid_fixtures"
GUARDS = "PG_OPTIONAL__grid_fixtures"
NODE = "grid_fixtures__node"

TWO_HOP_ROWS = (
    f"MATCH (a:{NODE})-[:{LINKS}]->(b:{NODE})-[:{LINKS}]->(c:{NODE}) WHERE a.entity_id = $a RETURN c.name AS c"
)
TWO_HOP_ENVELOPE = f"MATCH (a:{NODE})-[:{LINKS}]->(b:{NODE})-[:{LINKS}]->(c:{NODE}) WHERE a.entity_id = $a"
TWO_HOP_INBOUND_ROWS = (
    f"MATCH (c:{NODE})<-[:{LINKS}]-(b:{NODE})<-[:{LINKS}]-(a:{NODE}) WHERE c.entity_id = $c RETURN a.name AS a"
)
UNGUARDED_TARGETS = (
    f"MATCH (s:{NODE})-[:{LINKS}]->(t:{NODE}) "
    f"NOT EXISTS {{ MATCH (g)-[:{GUARDS}]->(h)-[:{GUARDS}]->(t) }} "
    "RETURN t.name AS t"
)
OUT_DEGREE = f"MATCH (t:{NODE}) OPTIONAL MATCH (t)-[:{LINKS}]->(w:{NODE}) RETURN t.name AS t, COUNT(w) AS n"


def _search(query: str) -> Search:
    return Search(search_type="gryphon", root="node", name="read-scope", definition={"query": query})


def _run(query: str, **inputs: Any) -> dict[str, Any]:
    return execute_search(_search(query), inputs={k: str(v) for k, v in inputs.items()})


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestReadScopeRetiredElements:
    """A retired element is invisible to every shape of read, not only to the root relation."""

    def _graph(self) -> dict[str, Any]:
        """Build the fixture graph; return nodes and edges by name."""
        from tap_plugin.grid_fixtures.models import PgNode

        from tap_grid.caller_context import get_caller_context, set_caller_context
        from tap_grid.models import Edge, Entity

        # Retirement below mints a batch through the service layer, and a minted batch must
        # carry the harness label (req-grid-service-batch-label-required) under its own id.
        ambient = get_caller_context()
        assert ambient is not None  # nosec B101
        set_caller_context(replace(ambient, batch_id=str(uuid.uuid4())))

        nodes: dict[str, Any] = {}
        for name in ("A", "B", "C", "D", "G", "H"):
            entity = Entity.objects.create(entity_type=NODE, name=name)
            PgNode.objects.create(entity=entity, name=name, kind="island")
            nodes[name] = entity

        edges: dict[str, Any] = {}
        for label, src, dst, edge_type in (
            ("AB", "A", "B", LINKS),
            ("BC", "B", "C", LINKS),
            ("AD", "A", "D", LINKS),
            ("GH", "G", "H", GUARDS),
            ("HB", "H", "B", GUARDS),
        ):
            edges[label] = Edge.objects.create(
                entity=Entity.objects.create(entity_type="edge", name=label),
                from_entity=nodes[src],
                to_entity=nodes[dst],
                edge_type=edge_type,
            )
        return {"nodes": nodes, "edges": edges}

    def _retire_edge(self, edge: Any) -> None:
        from tap_grid.services import delete_edge_by_entity

        result = delete_edge_by_entity(str(edge.entity_id), reason="operator")
        assert result.success, result.errors  # nosec B101 — a refused retirement makes the test vacuous

    def _tombstone_endpoint_leaving_edges_live(self, entity: Any) -> None:
        """Tombstone a node's spine row WITHOUT ending its edges.

        The write path never produces this state (a retired node ends its incident edges,
        tap#609), which is exactly why it is built by hand here: the read scope must not
        depend on the write rule, so the read has to be tested against a grid that breaks it.
        """
        from django.utils import timezone

        from tap_grid.models import Entity

        Entity.objects.filter(pk=entity.pk).update(deleted_at=timezone.now())

    # ------------------------------------------------------------------
    # Joined edges (req-grid-traversal-exec-read-scope-3)
    # ------------------------------------------------------------------

    def test_live_two_hop_chain_is_matched(self) -> None:
        """Non-vacuity: with nothing retired, the two-hop chain returns its far node."""
        g = self._graph()
        rows = _run(TWO_HOP_ROWS, a=g["nodes"]["A"].pk)["rows"]
        assert [r["c"] for r in rows] == ["C"]

    def test_retired_edge_at_hop_0_is_not_matched(self) -> None:
        """Control: the root edge was already scoped by its manager."""
        g = self._graph()
        self._retire_edge(g["edges"]["AB"])
        rows = _run(TWO_HOP_ROWS, a=g["nodes"]["A"].pk)["rows"]
        assert rows == [], f"retired hop-0 edge matched: {len(rows)} row(s)"

    @pytest.mark.spec("req-grid-traversal-exec-read-scope-3")
    def test_retired_edge_at_hop_1_is_not_matched(self) -> None:
        """The tap#811 repro: the same retirement one hop further out must also return nothing."""
        g = self._graph()
        self._retire_edge(g["edges"]["BC"])
        rows = _run(TWO_HOP_ROWS, a=g["nodes"]["A"].pk)["rows"]
        assert rows == [], f"retired hop-1 edge matched: {len(rows)} row(s)"

    @pytest.mark.spec("req-grid-traversal-exec-read-scope-3")
    def test_retired_edge_at_hop_1_is_not_matched_inbound(self) -> None:
        """The same defect with the chain written right to left (`<-` hops use `edges_in`)."""
        g = self._graph()
        self._retire_edge(g["edges"]["AB"])  # hop 1 when the chain is anchored on C
        rows = _run(TWO_HOP_INBOUND_ROWS, c=g["nodes"]["C"].pk)["rows"]
        assert rows == [], f"retired inbound hop-1 edge matched: {len(rows)} row(s)"

    # ------------------------------------------------------------------
    # Rows and envelope agree (req-grid-traversal-exec-read-scope-6)
    # ------------------------------------------------------------------

    @pytest.mark.spec("req-grid-traversal-exec-read-scope-6")
    def test_rows_and_envelope_agree_about_a_retired_hop(self) -> None:
        """The row form and the graph-envelope form of one pattern must tell the same story.

        Before the read scope the row form returned the far node through the retired hop, and
        the envelope's re-fetches used different managers for nodes and edges, so the two
        forms had no common definition of what was visible. Both now build from the scope.
        """
        g = self._graph()
        self._retire_edge(g["edges"]["BC"])
        rows = _run(TWO_HOP_ROWS, a=g["nodes"]["A"].pk)["rows"]
        envelope = _run(TWO_HOP_ENVELOPE, a=g["nodes"]["A"].pk)
        envelope_names = sorted(n["name"] for n in envelope["nodes"])
        assert rows == [], f"rows: {rows}"
        assert envelope_names == [], f"envelope nodes: {envelope_names}"
        assert envelope["edges"] == [], f"envelope edges: {[e['entity_id'] for e in envelope['edges']]}"

    def test_rows_and_envelope_agree_on_a_live_chain(self) -> None:
        """Non-vacuity for the agreement test."""
        g = self._graph()
        rows = _run(TWO_HOP_ROWS, a=g["nodes"]["A"].pk)["rows"]
        envelope = _run(TWO_HOP_ENVELOPE, a=g["nodes"]["A"].pk)
        assert [r["c"] for r in rows] == ["C"]
        assert sorted(n["name"] for n in envelope["nodes"]) == ["A", "B", "C"]
        assert len(envelope["edges"]) == 2

    # ------------------------------------------------------------------
    # Endpoints (req-grid-traversal-exec-read-scope-4)
    # ------------------------------------------------------------------

    @pytest.mark.spec("req-grid-traversal-exec-read-scope-4")
    def test_live_edge_onto_a_tombstoned_endpoint_is_not_matched(self) -> None:
        """An edge whose far endpoint is tombstoned is not a match, even if the edge is live."""
        g = self._graph()
        self._tombstone_endpoint_leaving_edges_live(g["nodes"]["D"])
        rows = _run(
            f"MATCH (a:{NODE})-[:{LINKS}]->(d) WHERE a.entity_id = $a RETURN d.name AS d",
            a=g["nodes"]["A"].pk,
        )["rows"]
        assert sorted(r["d"] for r in rows) == ["B"], f"rows: {rows}"

    @pytest.mark.spec("req-grid-traversal-exec-read-scope-4")
    def test_envelope_omits_a_tombstoned_endpoint(self) -> None:
        """The single-hop envelope must not re-hydrate a tombstoned endpoint either."""
        g = self._graph()
        self._tombstone_endpoint_leaving_edges_live(g["nodes"]["D"])
        envelope = _run(f"MATCH (a:{NODE})-[:{LINKS}]->(d) WHERE a.entity_id = $a", a=g["nodes"]["A"].pk)
        names = sorted(n["name"] for n in envelope["nodes"])
        assert names == ["A", "B"], f"envelope nodes: {names}"
        assert len(envelope["edges"]) == 1

    # ------------------------------------------------------------------
    # Subqueries and counts (req-grid-traversal-exec-read-scope-5)
    # ------------------------------------------------------------------

    @pytest.mark.spec("req-grid-traversal-exec-read-scope-5")
    def test_optional_match_count_excludes_a_retired_edge(self) -> None:
        """OPTIONAL MATCH counts only live optional edges; a zero stays a zero row."""
        g = self._graph()
        self._retire_edge(g["edges"]["AD"])
        rows = {r["t"]: r["n"] for r in _run(OUT_DEGREE)["rows"]}
        assert rows["A"] == 1, f"A's out-degree counted a retired edge: {rows['A']}"
        assert rows["C"] == 0

    @pytest.mark.spec("req-grid-traversal-exec-read-scope-5")
    def test_optional_match_count_excludes_a_tombstoned_endpoint(self) -> None:
        """The optional node's own liveness is part of the optional join."""
        g = self._graph()
        self._tombstone_endpoint_leaving_edges_live(g["nodes"]["D"])
        rows = {r["t"]: r["n"] for r in _run(OUT_DEGREE)["rows"]}
        assert rows["A"] == 1, f"A's out-degree counted a tombstoned neighbour: {rows['A']}"
        assert "D" not in rows, "the tombstoned node itself must not be a mandatory row"

    def test_optional_match_count_on_a_live_grid(self) -> None:
        """Non-vacuity for the count tests."""
        self._graph()
        rows = {r["t"]: r["n"] for r in _run(OUT_DEGREE)["rows"]}
        assert rows == {"A": 2, "B": 1, "C": 0, "D": 0, "G": 0, "H": 0}

    @pytest.mark.spec("req-grid-traversal-exec-read-scope-5")
    def test_not_exists_ignores_a_retired_inner_hop_1_edge(self) -> None:
        """A guard chain broken at its second hop no longer guards B, so B is unguarded."""
        g = self._graph()
        self._retire_edge(g["edges"]["HB"])
        targets = sorted(r["t"] for r in _run(UNGUARDED_TARGETS)["rows"])
        assert targets == ["B", "C", "D"], f"unguarded targets: {targets}"

    def test_not_exists_ignores_a_retired_inner_hop_0_edge(self) -> None:
        """Control: breaking the guard chain at its root was already honoured."""
        g = self._graph()
        self._retire_edge(g["edges"]["GH"])
        targets = sorted(r["t"] for r in _run(UNGUARDED_TARGETS)["rows"])
        assert targets == ["B", "C", "D"], f"unguarded targets: {targets}"

    def test_not_exists_on_a_live_grid(self) -> None:
        """Non-vacuity: with the guard chain intact, B is guarded."""
        self._graph()
        targets = sorted(r["t"] for r in _run(UNGUARDED_TARGETS)["rows"])
        assert targets == ["C", "D"], f"unguarded targets: {targets}"

    @pytest.mark.spec("req-grid-traversal-exec-read-scope-7")
    def test_not_exists_correlates_on_the_structural_hop(self) -> None:
        """A correlated far node binds to the inner pattern's own hop, not to any edge onto it.

        Not a liveness case, and not something the scope adds: the correlation used to be a
        separate `filter()`, which on a reverse (multi-valued) path makes Django add a second
        join. That join carried no edge type, so an H->B edge of the WRONG type satisfied the
        correlation while H's PG_OPTIONAL edge to somewhere else satisfied the structure.
        Folding the correlation into the hop's single `filter()` is the same-join rule the
        scope predicates rely on (req-grid-traversal-exec-read-scope-7).
        """
        from tap_grid.models import Edge, Entity

        g = self._graph()
        self._retire_edge(g["edges"]["HB"])
        # H now reaches B only by a PG_LINKS edge, and has a live PG_OPTIONAL edge elsewhere.
        Edge.objects.create(
            entity=Entity.objects.create(entity_type="edge", name="HB-links"),
            from_entity=g["nodes"]["H"],
            to_entity=g["nodes"]["B"],
            edge_type=LINKS,
        )
        Edge.objects.create(
            entity=Entity.objects.create(entity_type="edge", name="HC-guard"),
            from_entity=g["nodes"]["H"],
            to_entity=g["nodes"]["C"],
            edge_type=GUARDS,
        )
        targets = sorted(r["t"] for r in _run(UNGUARDED_TARGETS)["rows"])
        # B is reached by A->B and H->B (both PG_LINKS) and no PG_OPTIONAL chain ends on it.
        # C is now guarded by G->H->C.
        assert targets == ["B", "B", "D"], f"unguarded targets: {targets}"

    # ------------------------------------------------------------------
    # Default scope (req-grid-traversal-exec-read-scope-1, -2)
    # ------------------------------------------------------------------

    @pytest.mark.spec("req-grid-traversal-exec-read-scope-2")
    def test_labelled_and_labelless_scans_omit_a_retired_node(self) -> None:
        """Root relations: both spellings of a node scan exclude a retired node."""
        from tap_grid.services import delete_node

        g = self._graph()
        assert delete_node(str(g["nodes"]["D"].pk), reason="operator").success  # nosec B101
        labelled = sorted(n["name"] for n in _run(f"MATCH (n:{NODE})")["nodes"])
        labelless = sorted(n["name"] for n in _run(f'MATCH (n) WHERE n.entity_type = "{NODE}"')["nodes"])
        assert labelled == labelless == ["A", "B", "C", "G", "H"]


class TestReadScopeValue:
    """The scope value itself (req-grid-traversal-exec-read-scope-1, req-grid-traversal-exec-temporal-scope-1)."""

    @pytest.mark.spec("req-grid-traversal-exec-read-scope-1")
    def test_default_scope_is_live_now(self) -> None:
        from tap_grid.gryphon.read_scope import DEFAULT_SCOPE, LiveNow

        assert isinstance(DEFAULT_SCOPE, LiveNow)

    @pytest.mark.spec("req-grid-traversal-exec-temporal-scope-1")
    @pytest.mark.parametrize("name", ["AsOf", "Between"])
    def test_temporal_scopes_fail_closed(self, name: str) -> None:
        """Constructing a temporal scope is refused until it is built — never a silent LiveNow."""
        from tap_grid.gryphon import read_scope

        with pytest.raises(SearchExecutionError, match="not implemented"):
            getattr(read_scope, name)()

    @pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
    @pytest.mark.spec("req-grid-traversal-exec-read-scope-8")
    def test_query_text_cannot_widen_the_scope(self) -> None:
        """Only the caller's argument selects a scope; an unknown scope value is refused."""
        from tap_grid.gryphon.executor import execute_gryphon_raw

        with pytest.raises(SearchExecutionError, match="scope"):
            execute_gryphon_raw(f"MATCH (n:{NODE})", {}, scope=object())  # type: ignore[arg-type]


@pytest.mark.spec("req-grid-traversal-exec-read-scope-9")
@pytest.mark.django_db(databases=["default"])
class TestCompiledQueryCheck:
    """The primary enforcement refuses an unscoped relation however the queryset was built.

    Each case starts from a scoped base relation and adds exactly one unscoped relation, then
    asserts execution is refused before any SQL runs. The counterpart — every relation the
    executor itself builds passes — is the whole executor suite running with the check live.
    """

    def _live(self) -> Any:
        """A fresh LiveNow, imported lazily so collection needs no Django."""
        from tap_grid.gryphon.read_scope import LiveNow

        return LiveNow()

    def test_scoped_base_relations_pass(self) -> None:
        from tap_grid.gryphon import read_scope

        assert list(read_scope.node_relation(self._live(), None, db_alias="default")[:1]) is not None
        assert read_scope.edge_relation(self._live(), db_alias="default").count() >= 0

    def test_a_reverse_edge_join_without_its_scope_is_refused(self) -> None:
        """The tap#811 shape, built by hand: a hop through `edges_out` with no edge predicate."""
        from tap_grid.gryphon import read_scope

        qs = read_scope.node_relation(self._live(), None, db_alias="default").filter(edges_out__edge_type=LINKS)
        with pytest.raises(SearchExecutionError, match="tap_edge alias .* not bound to a scoped spine row"):
            list(qs)

    def test_a_far_endpoint_without_its_scope_is_refused(self) -> None:
        """A second hop's edge scoped but its far endpoint not."""
        from tap_grid.gryphon import read_scope

        scope = self._live()
        hop = read_scope.reverse_edge_path("to_entity", "out")
        qs = read_scope.edge_relation(scope, db_alias="default").filter(
            **read_scope.edge_scope_filters(scope, hop), **{f"{hop}__to_entity__name": "C"}
        )
        with pytest.raises(SearchExecutionError, match="spine alias .* has no `deleted_at IS NULL`"):
            qs.count()

    def test_a_scope_predicate_under_or_does_not_count(self) -> None:
        """`deleted_at IS NULL OR name = x` admits tombstones, so it does not scope the alias."""
        from django.db.models import Q

        from tap_grid.gryphon import read_scope
        from tap_grid.models import Entity

        qs = read_scope._scoped(read_scope.ScopedEntityQuerySet(model=Entity, using="default"), self._live())
        qs = qs.filter(Q(deleted_at__isnull=True) | Q(name="x"))
        with pytest.raises(SearchExecutionError, match="has no `deleted_at IS NULL`"):
            qs.exists()

    def test_an_unscoped_subquery_is_refused(self) -> None:
        """The check recurses into subqueries — NOT EXISTS is an `Exists`."""
        from django.db.models import Exists, OuterRef

        from tap_grid.gryphon import read_scope
        from tap_grid.models import Edge

        inner = Edge.all_objects.filter(from_entity=OuterRef("pk"))
        qs = read_scope.node_relation(self._live(), None, db_alias="default").filter(~Exists(inner))
        with pytest.raises(SearchExecutionError, match="tap_edge alias"):
            list(qs)

    def test_a_query_that_can_read_nothing_is_not_refused(self) -> None:
        """An empty `IN ()` compiles to EmptyResultSet: Django runs no SQL, so nothing is read."""
        from tap_grid.gryphon import read_scope

        assert list(read_scope.node_relation(self._live(), None, db_alias="default").filter(pk__in=[])) == []

    def test_values_and_iterator_paths_are_checked(self) -> None:
        from tap_grid.gryphon import read_scope

        qs = read_scope.node_relation(self._live(), None, db_alias="default").filter(edges_in__edge_type=LINKS)
        with pytest.raises(SearchExecutionError):
            list(qs.values_list("pk", flat=True))
        with pytest.raises(SearchExecutionError):
            next(qs.iterator())


@pytest.mark.spec("req-grid-traversal-exec-read-scope-12")
class TestStaticGuard:
    """The secondary enforcement flags the obvious spellings; a probe proves it can fire."""

    def test_the_gryphon_package_is_clean(self) -> None:
        from tap_grid.guards.gryphon_read_scope import GryphonReadScopeGuard

        GryphonReadScopeGuard().check()

    @pytest.mark.parametrize(
        "line",
        [
            "qs = Entity.objects.filter(pk=1)",
            "qs = Edge.all_objects.all()",
            "qs = model._base_manager.all()",
            "qs = model._default_manager.all()",
            'path = "to_entity__edges_out"',
            'path = f"{shared}__edges_in"',
        ],
    )
    def test_each_unscoped_spelling_is_flagged(self, line: str) -> None:
        from tap_grid.guards.gryphon_read_scope import read_scope_offenders

        assert len(read_scope_offenders(line + "\n", "probe.py")) == 1

    def test_docstrings_are_prose_not_lookups(self) -> None:
        from tap_grid.guards.gryphon_read_scope import read_scope_offenders

        source = 'def f():\n    """Hop 1 crosses `to_entity__edges_out`."""\n    return 1\n'
        assert read_scope_offenders(source, "probe.py") == []
