"""Temporal offset comparison — `req-grid-traversal-lang-temporal-offset`.

`WHERE base +/- hours(x) <op> now()` shifts a date-time field by whole hours and compares it with
the query clock or a supplied instant; `LOOKUP p = (:label {k: v})` selects exactly one row of an
unlinked node as the source of `x`. Parser tests need no database; the executor tests build a
small leaf -> node graph from the generic grid_fixtures types, where the lookup rows are further
nodes that no edge reaches.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from tap_grid.exceptions import SearchExecutionError
from tap_grid.gryphon import execute_gryphon_raw, explain_gryphon_raw, parse_gryphon
from tap_grid.gryphon.ast_nodes import (
    DotStep,
    FieldPath,
    LookupClause,
    NotPred,
    NowRef,
    ParamRef,
    TemporalComparison,
    TemporalOffset,
)
from tap_grid.gryphon.parser import GryphonParseError

HOP = "MATCH (f:grid_fixtures__leaf)-[:PG_LINKS__grid_fixtures]->(a:grid_fixtures__node) "
LOOKUP_GOLD = 'LOOKUP p = (:grid_fixtures__node {kind: "policy-gold"}) '
DUE = "a.data.observed_at + hours(p.data.severity_score) < now()"
NOW = datetime(2026, 3, 10, tzinfo=UTC)


def _path(var: str, *names: str) -> FieldPath:
    return FieldPath(var, tuple(DotStep(n) for n in names))


def _where_leaf(text: str) -> TemporalComparison:
    """Parse a query and return its single WHERE leaf, which must be a temporal comparison."""
    where = parse_gryphon(text).where_clause
    assert where is not None
    assert isinstance(where.predicate, TemporalComparison)
    return where.predicate


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class TestTemporalOffsetParser:
    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-1")
    def test_offset_forms_parse_to_a_temporal_leaf(self):
        assert _where_leaf(HOP + LOOKUP_GOLD + f"WHERE {DUE} RETURN a.name AS n") == TemporalComparison(
            offset=TemporalOffset(
                base=_path("a", "data", "observed_at"), sign="+", hours=_path("p", "data", "severity_score")
            ),
            op="<",
            operand=NowRef(),
        )

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-1")
    @pytest.mark.parametrize(
        ("text", "sign", "hours", "op", "operand"),
        [
            ("a.data.observed_at - hours(12) >= $t", "-", 12, ">=", ParamRef("t")),
            ("a.data.observed_at + hours($h) <= now()", "+", ParamRef("h"), "<=", NowRef()),
            ("a.data.observed_at + HOURS(1) > NOW()", "+", 1, ">", NowRef()),
        ],
    )
    def test_literal_and_param_hours_and_every_operator(self, text, sign, hours, op, operand):
        leaf = _where_leaf(HOP + f"WHERE {text} RETURN a.name AS n")
        assert (leaf.offset.sign, leaf.offset.hours, leaf.op, leaf.operand) == (sign, hours, op, operand)

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-2")
    def test_lookup_clause_parses_with_literal_and_param_keys(self):
        ast = parse_gryphon(
            HOP + 'LOOKUP p = (:grid_fixtures__node {kind: "policy-gold", severity_score: $s}) '
            f"WHERE {DUE} RETURN a.name AS n"
        )
        assert ast.lookup_clauses == (
            LookupClause("p", "grid_fixtures__node", {"kind": "policy-gold", "severity_score": ParamRef("s")}),
        )

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-2")
    def test_lookup_needs_at_least_one_property(self):
        with pytest.raises(GryphonParseError):
            parse_gryphon(HOP + f"LOOKUP p = (:grid_fixtures__node) WHERE {DUE} RETURN a.name AS n")

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-2")
    def test_duplicate_lookup_variable_is_a_parse_error(self):
        with pytest.raises(GryphonParseError, match="more than once"):
            parse_gryphon(HOP + LOOKUP_GOLD + 'LOOKUP p = (:grid_fixtures__node {kind: "x"}) ' f"WHERE {DUE}")

    def test_parameters_in_a_lookup_and_a_leaf_are_required_params(self):
        ast = parse_gryphon(
            HOP + "LOOKUP p = (:grid_fixtures__node {kind: $k}) "
            "WHERE a.data.observed_at + hours(p.data.severity_score) < $when RETURN a.name AS n"
        )
        assert ast.required_params() == frozenset({"k", "when"})

    def test_keyword_spellings_remain_usable_as_field_names(self):
        """`now`, `hours` and `lookup` are keywords only where the grammar expects them."""
        ast = parse_gryphon(
            HOP + "WHERE a.data.now = 1 AND a.data.hours = 2 AND a.data.lookup = 3 RETURN a.name AS n"
        )
        assert ast.where_clause is not None

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-5")
    @pytest.mark.parametrize(
        ("clause", "match"),
        [
            ("WHERE p.data.severity_score = 1 AND " + DUE + " RETURN a.name AS n", "WHERE comparison"),
            (f"WHERE {DUE} RETURN p.data.severity_score AS n", "RETURN"),
            (f"WHERE {DUE} RETURN a.name AS n ORDER BY p.data.severity_score", "ORDER BY"),
            ("WHERE p.data.observed_at + hours(p.data.severity_score) < now() RETURN a.name AS n", "base of"),
        ],
    )
    def test_lookup_variable_used_outside_hours_is_rejected(self, clause, match):
        with pytest.raises(GryphonParseError, match=match):
            parse_gryphon(HOP + LOOKUP_GOLD + clause)

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-5")
    @pytest.mark.parametrize("clashing", ["a", "f"])
    def test_lookup_variable_sharing_a_match_name_is_rejected(self, clashing):
        text = (
            "MATCH (f:grid_fixtures__leaf)-[:PG_LINKS__grid_fixtures]->(a:grid_fixtures__node) "
            f'LOOKUP {clashing} = (:grid_fixtures__node {{kind: "x"}}) '
            f"WHERE a.data.observed_at + hours({clashing}.data.severity_score) < now() RETURN a.name AS n"
        )
        with pytest.raises(GryphonParseError, match="also bound by a MATCH"):
            parse_gryphon(text)

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-5")
    def test_an_unnamed_node_binds_its_label_so_a_lookup_cannot_take_it(self):
        text = (
            "MATCH (:grid_fixtures__leaf)-[:PG_LINKS__grid_fixtures]->(a:grid_fixtures__node) "
            'LOOKUP grid_fixtures__leaf = (:grid_fixtures__node {kind: "x"}) '
            "WHERE a.data.observed_at + hours(grid_fixtures__leaf.data.severity_score) < now() RETURN a.name AS n"
        )
        with pytest.raises(GryphonParseError, match="also bound by a MATCH"):
            parse_gryphon(text)

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-5")
    def test_match_variable_inside_hours_is_rejected(self):
        with pytest.raises(GryphonParseError, match="must read a field of a LOOKUP variable"):
            parse_gryphon(HOP + "WHERE a.data.observed_at + hours(f.data.severity_score) < now() RETURN a.name AS n")

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-20")
    def test_lookup_no_temporal_comparison_reads_is_rejected(self):
        with pytest.raises(GryphonParseError, match="no temporal comparison reads it"):
            parse_gryphon(HOP + LOOKUP_GOLD + 'WHERE a.data.kind = "x" RETURN a.name AS n')

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-12")
    @pytest.mark.parametrize("op", ["=", "!="])
    def test_equality_on_a_temporal_comparison_is_rejected(self, op):
        with pytest.raises(GryphonParseError, match=r"<, <=, >, >="):
            parse_gryphon(HOP + f"WHERE a.data.observed_at + hours(1) {op} now() RETURN a.name AS n")

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-17")
    def test_arithmetic_in_return_is_rejected_naming_where(self):
        with pytest.raises(GryphonParseError, match="Arithmetic in RETURN.*WHERE"):
            parse_gryphon(HOP + "RETURN a.data.observed_at + hours(1) AS due")

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-17")
    def test_arithmetic_in_order_by_is_rejected_naming_where(self):
        with pytest.raises(GryphonParseError, match="Arithmetic in ORDER BY.*WHERE"):
            parse_gryphon(HOP + "RETURN a.name AS n ORDER BY a.data.observed_at + hours(1)")

    def test_negated_leaf_nests_under_not(self):
        where = parse_gryphon(HOP + "WHERE NOT a.data.observed_at + hours(1) < now() RETURN a.name AS n").where_clause
        assert where is not None
        assert isinstance(where.predicate, NotPred)
        assert isinstance(where.predicate.operand, TemporalComparison)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


@pytest.fixture
def fixed_clock():
    return lambda: NOW


class _TemporalFixture:
    """A leaf -> node graph whose nodes carry `observed_at`, plus unlinked policy nodes.

    Alerts (hours of age at NOW = 2026-03-10T00:00:00Z, gold window 24h, silver 48h):
    - boundary   observed exactly 24h before NOW  (due exactly at the boundary)
    - overdue    observed 48h before NOW
    - fresh      observed 12h before NOW
    - unobserved observed_at is NULL
    """

    def _build(self) -> None:
        from tap_plugin.grid_fixtures.models import PgLeaf as _PgLeaf
        from tap_plugin.grid_fixtures.models import PgNode as _PgNode

        PgLeaf: Any = _PgLeaf
        PgNode: Any = _PgNode

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Edge, Entity

        ambient = get_caller_context()
        assert ambient is not None
        set_caller_context(CallerContext(user=ambient.user, batch_id=str(uuid.uuid4())))

        def make(model: Any, entity_type: str, name: str, **fields: Any) -> Any:
            entity = Entity.objects.create(entity_type=entity_type, name=name)
            return model.objects.create(entity=entity, name=name, **fields)

        leaf = make(PgLeaf, "grid_fixtures__leaf", "leaf")
        rows = [
            ("boundary", NOW - timedelta(hours=24)),
            ("overdue", NOW - timedelta(hours=48)),
            ("fresh", NOW - timedelta(hours=12)),
            ("unobserved", None),
        ]
        for name, seen in rows:
            alert = make(PgNode, "grid_fixtures__node", name, observed_at=seen, kind="alert", severity_score=1)
            Edge.objects.create(
                entity=Entity.objects.create(entity_type="edge"),
                from_entity=leaf.entity,
                to_entity=alert.entity,
                edge_type="PG_LINKS__grid_fixtures",
            )
        # Unlinked policy rows: no edge reaches them.
        make(PgNode, "grid_fixtures__node", "gold", kind="policy-gold", severity_score=24)
        make(PgNode, "grid_fixtures__node", "silver", kind="policy-silver", severity_score=48)
        make(PgNode, "grid_fixtures__node", "blank", kind="policy-blank", severity_score=1, tags={"window": None})
        make(PgNode, "grid_fixtures__node", "negative", kind="policy-negative", severity_score=-12)

    def _names(self, query: str, inputs: dict[str, Any] | None = None, clock=lambda: NOW) -> list[str]:
        rows = execute_gryphon_raw(query, inputs or {}, clock=clock)["rows"]
        return sorted(r["n"] for r in rows)


DB = pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])


@DB
class TestTemporalOffsetExecutor(_TemporalFixture):
    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-13")
    def test_boundary_is_exact(self):
        """With `<` a row exactly at the boundary instant does not match; with `<=` it does."""
        self._build()
        strict = self._names(HOP + LOOKUP_GOLD + f"WHERE {DUE} RETURN a.name AS n")
        inclusive = self._names(
            HOP + LOOKUP_GOLD + "WHERE a.data.observed_at + hours(p.data.severity_score) <= now() RETURN a.name AS n"
        )
        assert strict == ["overdue"]
        assert inclusive == ["boundary", "overdue"]

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-9")
    def test_null_base_never_matches_and_matches_its_negation(self):
        self._build()
        positive = self._names(HOP + LOOKUP_GOLD + f"WHERE {DUE} RETURN a.name AS n")
        negated = self._names(HOP + LOOKUP_GOLD + f"WHERE NOT {DUE} RETURN a.name AS n")
        assert "unobserved" not in positive
        assert negated == ["boundary", "fresh", "unobserved"]

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-14")
    def test_composes_with_and_or_not(self):
        self._build()
        base = HOP + LOOKUP_GOLD
        assert self._names(base + f'WHERE {DUE} AND a.name = "fresh" RETURN a.name AS n') == []
        assert self._names(base + f'WHERE {DUE} OR a.name = "fresh" RETURN a.name AS n') == ["fresh", "overdue"]
        assert self._names(base + f'WHERE NOT ({DUE} OR a.name = "fresh") RETURN a.name AS n') == [
            "boundary",
            "unobserved",
        ]

    def test_literal_offset_param_instant_and_minus_sign(self):
        self._build()
        # observed + 36h < NOW: only the 48h-old row.
        assert self._names(HOP + "WHERE a.data.observed_at + hours(36) < now() RETURN a.name AS n") == ["overdue"]
        # a supplied instant replaces now(): observed + 12h < 2026-03-09T00:00:00Z -> only "overdue" (48h old).
        assert self._names(
            HOP + "WHERE a.data.observed_at + hours($h) < $t RETURN a.name AS n",
            {"h": 12, "t": "2026-03-09T00:00:00Z"},
        ) == ["overdue"]
        # observed - 12h > NOW - 40h ... a minus offset: (observed - 12h) >= 2026-03-08T12:00:00Z -> boundary, fresh.
        assert self._names(
            HOP + "WHERE a.data.observed_at - hours(12) >= $t RETURN a.name AS n", {"t": "2026-03-08T12:00:00Z"}
        ) == ["boundary", "fresh"]

    def test_lookup_key_may_be_a_param(self):
        self._build()
        assert self._names(
            HOP + "LOOKUP p = (:grid_fixtures__node {kind: $tier}) "
            "WHERE a.data.observed_at + hours(p.data.severity_score) < now() RETURN a.name AS n",
            {"tier": "policy-silver"},
        ) == []
        assert self._names(
            HOP + "LOOKUP p = (:grid_fixtures__node {kind: $tier}) "
            "WHERE a.data.observed_at + hours(p.data.severity_score) < now() RETURN a.name AS n",
            {"tier": "policy-gold"},
        ) == ["overdue"]

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-19")
    def test_negative_stored_offset_and_a_param_hours_value(self):
        self._build()
        # hours = -12 moves the deadline 12h EARLIER than the observation: observed - 12h < now.
        negative = 'LOOKUP p = (:grid_fixtures__node {kind: "policy-negative"}) '
        assert self._names(HOP + negative + f"WHERE {DUE} RETURN a.name AS n") == [
            "boundary",
            "fresh",
            "overdue",
        ]
        # ages: boundary 24h, overdue 48h, fresh 12h; only the 48h row is older than 40h
        assert self._names(HOP + "WHERE a.data.observed_at + hours($h) < now() RETURN a.name AS n", {"h": 40}) == [
            "overdue"
        ]

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-4")
    def test_the_embedded_subquery_carries_the_liveness_scope(self):
        """The main query's own scalar subquery excludes tombstones, not only the counting read."""
        self._build()
        captured = explain_gryphon_raw(HOP + LOOKUP_GOLD + f"WHERE {DUE} RETURN a.name AS n", {}, clock=lambda: NOW)
        main = [s.sql for s in captured["sql"].statements if "LIMIT 2" not in s.sql][0]
        assert 'U1."deleted_at" IS NULL' in main
        assert "SELECT U0." in main

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-16")
    def test_order_by_and_limit_follow_the_one_hop_path(self):
        """An aggregate RETURN keeps ORDER BY / LIMIT; a plain projection or envelope refuses them."""
        self._build()
        rows = execute_gryphon_raw(
            HOP + LOOKUP_GOLD + f"WHERE {DUE} RETURN a.data.kind AS k, COUNT(a) AS c ORDER BY c LIMIT 5",
            {},
            clock=lambda: NOW,
        )["rows"]
        assert rows == [{"k": "alert", "c": 1}]
        with pytest.raises(SearchExecutionError, match="ORDER BY / LIMIT"):
            self._names(HOP + LOOKUP_GOLD + f"WHERE {DUE} RETURN a.name AS n ORDER BY n")

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-25")
    def test_a_refused_shape_issues_no_lookup_sql(self):
        from tap_grid.gryphon import capture_sql

        self._build()
        refused = (
            "MATCH (a:grid_fixtures__node) " + LOOKUP_GOLD + f"WHERE {DUE}",  # node-only
            HOP + LOOKUP_GOLD + f"WHERE {DUE} RETURN a.name AS n ORDER BY n",  # ORDER BY without aggregate
            HOP + LOOKUP_GOLD + "WHERE zz.data.observed_at + hours(p.data.severity_score) < now()",  # unbound base
        )
        for query in refused:
            with capture_sql() as capture:
                with pytest.raises(SearchExecutionError):
                    execute_gryphon_raw(query, {}, clock=lambda: NOW)
            assert not any("severity_score" in s.sql for s in capture.statements), query

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-15")
    def test_one_hop_envelope_filters_and_no_where_returns_everything(self):
        self._build()
        filtered = execute_gryphon_raw(HOP + LOOKUP_GOLD + f"WHERE {DUE}", {}, clock=lambda: NOW)
        assert sorted(n["name"] for n in filtered["nodes"] if n["entity_type"] == "grid_fixtures__node") == ["overdue"]
        everything = execute_gryphon_raw(HOP, {})
        assert sorted(n["name"] for n in everything["nodes"] if n["entity_type"] == "grid_fixtures__node") == [
            "boundary",
            "fresh",
            "overdue",
            "unobserved",
        ]

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-15")
    def test_count_over_the_pattern(self):
        self._build()
        rows = execute_gryphon_raw(
            HOP + LOOKUP_GOLD + f"WHERE {DUE} RETURN COUNT(a) AS due", {}, clock=lambda: NOW
        )["rows"]
        assert rows == [{"due": 1}]

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-24")
    def test_base_on_either_end_and_inbound_hop(self):
        """The base may belong to the target end (above) or the source end of an inbound pattern."""
        self._build()
        inbound = (
            "MATCH (a:grid_fixtures__node)<-[:PG_LINKS__grid_fixtures]-(f:grid_fixtures__leaf) "
            + LOOKUP_GOLD
            + f"WHERE {DUE} RETURN a.name AS n"
        )
        assert self._names(inbound) == ["overdue"]
        negated = inbound.replace(f"WHERE {DUE}", f"WHERE NOT {DUE}")
        assert self._names(negated) == ["boundary", "fresh", "unobserved"]

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-11")
    def test_clock_is_read_once_and_captured_sql_is_stable(self):
        self._build()
        calls: list[int] = []

        def clock() -> datetime:
            calls.append(1)
            return NOW

        query = HOP + LOOKUP_GOLD + f"WHERE {DUE} RETURN a.name AS n"
        first = explain_gryphon_raw(query, {}, clock=clock)
        assert len(calls) == 1
        second = explain_gryphon_raw(query, {}, clock=clock)
        assert [s.sql for s in first["sql"].statements] == [s.sql for s in second["sql"].statements]
        assert [s.params for s in first["sql"].statements] == [s.params for s in second["sql"].statements]

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-25")
    def test_counting_read_runs_first_and_carries_no_stage_label_of_its_own(self):
        """The count (at most two rows) precedes the main query, and adds no stage to the executor's inventory."""
        self._build()
        captured = explain_gryphon_raw(HOP + LOOKUP_GOLD + f"WHERE {DUE} RETURN a.name AS n", {}, clock=lambda: NOW)
        statements = captured["sql"].statements
        assert "LIMIT 2" in statements[0].sql
        assert sum("LIMIT 2" in s.sql for s in statements) == 1
        # it runs inside the dispatch stage that follows it; an unlabelled statement would trip the
        # Gridkin snapshot-stage tripwire, and a new label would change the stage inventory
        assert all(s.stage in {"advanced", "single-hop"} for s in statements)

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-18")
    def test_lowering_is_plain_orm_composition(self):
        """Rung 1: the emitted SQL is built from Django lookups and expressions, with no raw fragment."""
        import inspect

        from tap_grid.gryphon import executor

        for fn in (executor._temporal_to_q, executor._lookup_value_expr, executor._typed_data_lane_source):
            source = inspect.getsource(fn)
            assert "RawSQL" not in source, fn.__name__
            assert "Func(" not in source, fn.__name__
            assert "class " not in source, fn.__name__


@DB
class TestTemporalOffsetLookup(_TemporalFixture):
    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-3")
    def test_zero_rows_is_an_error(self):
        self._build()
        with pytest.raises(SearchExecutionError, match="matched no row"):
            self._names(
                HOP + 'LOOKUP p = (:grid_fixtures__node {kind: "policy-none"}) ' f"WHERE {DUE} RETURN a.name AS n"
            )

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-3")
    def test_more_than_one_row_is_an_error(self):
        self._build()
        with pytest.raises(SearchExecutionError, match="more than one row"):
            # every alert shares kind "alert"
            self._names(HOP + 'LOOKUP p = (:grid_fixtures__node {kind: "alert"}) ' f"WHERE {DUE} RETURN a.name AS n")

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-10")
    def test_null_selected_field_is_an_error_not_a_match_or_an_empty_result(self, monkeypatch):
        """A null offset lowered to FALSE would become TRUE under NOT, so it is refused in both polarities."""
        from tap_plugin.grid_fixtures.models import PgNode

        monkeypatch.setattr(
            PgNode,
            "FIELD_CRUD_SCHEMA",
            {
                **PgNode.FIELD_CRUD_SCHEMA,
                "tags": {"type": "object", "properties": {"window": {"type": ["integer", "null"]}}},
            },
        )
        self._build()
        for prefix in ("", "NOT "):
            with pytest.raises(SearchExecutionError, match="hours field is null"):
                self._names(
                    HOP
                    + 'LOOKUP p = (:grid_fixtures__node {kind: "policy-blank"}) '
                    + f"WHERE {prefix}a.data.observed_at + hours(p.data.tags.window) < now() RETURN a.name AS n"
                )

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-10")
    def test_null_lookup_key_is_an_error(self):
        self._build()
        with pytest.raises(SearchExecutionError, match="property 'kind' is null"):
            self._names(
                HOP + "LOOKUP p = (:grid_fixtures__node {kind: $k}) " f"WHERE {DUE} RETURN a.name AS n", {"k": None}
            )

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-10")
    def test_null_instant_and_null_hours_param_are_errors(self):
        self._build()
        with pytest.raises(SearchExecutionError, match="null instant"):
            self._names(HOP + "WHERE a.data.observed_at + hours(1) < $t RETURN a.name AS n", {"t": None})
        with pytest.raises(SearchExecutionError, match="received a null value"):
            self._names(HOP + "WHERE a.data.observed_at + hours($h) < now() RETURN a.name AS n", {"h": None})

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-4")
    def test_a_tombstoned_lookup_row_is_never_selected(self):
        from django.utils import timezone

        from tap_grid.models import Entity

        self._build()
        Entity.objects.filter(name="gold").update(deleted_at=timezone.now())
        with pytest.raises(SearchExecutionError, match="matched no row"):
            self._names(HOP + LOOKUP_GOLD + f"WHERE {DUE} RETURN a.name AS n")

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-25")
    def test_a_second_row_appearing_after_the_count_is_a_search_error(self, monkeypatch):
        """sqlstate 21000 from the main query's scalar subquery is mapped, not leaked as a database error.

        A write cannot run inside a read gate, so the row "appearing between the two statements" is
        simulated: the counting read passes on the real one-row relation, then the context handed to
        the main query carries a relation that matches several rows.
        """
        from dataclasses import replace

        from tap_grid.gryphon import executor

        self._build()
        real = executor._prepare_temporal

        def widen_after_the_count(*args: Any, **kwargs: Any) -> Any:
            ctx = real(*args, **kwargs)
            assert ctx is not None
            source = ctx.lookups["p"]
            wider = source.relation.model._default_manager.using("search_readonly").filter(kind__startswith="policy-")
            return replace(ctx, lookups={"p": replace(source, relation=wider)})

        monkeypatch.setattr(executor, "_prepare_temporal", widen_after_the_count)
        with pytest.raises(SearchExecutionError, match="matched more than one row when the query ran"):
            execute_gryphon_raw(HOP + LOOKUP_GOLD + f"WHERE {DUE}", {}, clock=lambda: NOW)
        with pytest.raises(SearchExecutionError, match="matched more than one row when the query ran"):
            execute_gryphon_raw(HOP + LOOKUP_GOLD + f"WHERE {DUE} RETURN a.name AS n", {}, clock=lambda: NOW)


@DB
class TestTemporalOffsetRefusals(_TemporalFixture):
    """Every shape or value the leaf cannot be applied to is refused loudly, never dropped."""

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-16")
    @pytest.mark.parametrize(
        ("query", "match"),
        [
            ("MATCH (a:grid_fixtures__node) WHERE a.data.observed_at + hours(1) < now() RETURN a.name AS n", "node-only"),
            (
                "MATCH (h:grid_fixtures__hub)-[:PG_LINKS__grid_fixtures]->(f:grid_fixtures__leaf)"
                "-[:PG_LINKS__grid_fixtures]->(a:grid_fixtures__node) "
                "WHERE a.data.observed_at + hours(1) < now() RETURN a.name AS n",
                "multi-hop",
            ),
            (
                "MATCH (f:grid_fixtures__leaf)-[:PG_LINKS__grid_fixtures]-(a:grid_fixtures__node) "
                "WHERE a.data.observed_at + hours(1) < now() RETURN a.name AS n",
                "undirected",
            ),
            (
                "MATCH (a:grid_fixtures__node) OPTIONAL MATCH (a)<-[:PG_LINKS__grid_fixtures]-(g:grid_fixtures__leaf) "
                "WHERE a.data.observed_at + hours(1) < now() RETURN a.name AS n, COUNT(g) AS c",
                "OPTIONAL MATCH",
            ),
            (
                HOP + "NOT EXISTS { MATCH (x:grid_fixtures__leaf)-[:PG_LINKS__grid_fixtures]->(a) } "
                "WHERE a.data.observed_at + hours(1) < now() RETURN a.name AS n",
                "NOT EXISTS",
            ),
            (
                "MATCH (a) WHERE a.data.observed_at + hours(1) < now() RETURN a",
                "node-only",
            ),
            (
                HOP + "MATCH (g:grid_fixtures__hub) WHERE a.data.observed_at + hours(1) < now() RETURN a.name AS n",
                "more than one MATCH",
            ),
            (
                HOP + "WHERE a.data.observed_at + hours(1) < now() RETURN a.name AS n ORDER BY n",
                "ORDER BY / LIMIT",
            ),
        ],
    )
    def test_unsupported_shape_is_rejected(self, query, match):
        self._build()
        with pytest.raises(SearchExecutionError, match=match):
            execute_gryphon_raw(query, {}, clock=lambda: NOW)

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-23")
    def test_a_second_match_clause_is_refused(self):
        self._build()
        query = HOP + "MATCH (g:grid_fixtures__hub) WHERE a.data.observed_at + hours(1) < now() RETURN a.name AS n"
        with pytest.raises(SearchExecutionError, match="more than one MATCH"):
            execute_gryphon_raw(query, {}, clock=lambda: NOW)

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-24")
    @pytest.mark.parametrize(
        "query",
        [
            # a base variable no MATCH node binds, with and without a lookup, positive and negated
            HOP + LOOKUP_GOLD + "WHERE zz.data.observed_at + hours(p.data.severity_score) < now() RETURN a.name AS n",
            HOP + LOOKUP_GOLD + "WHERE NOT zz.data.observed_at + hours(p.data.severity_score) < now() RETURN a.name AS n",
            HOP + "WHERE zz.data.observed_at + hours(1) < now() RETURN a.name AS n",
            # an unnamed labelled node binds nothing, though its label reads like a variable
            "MATCH (:grid_fixtures__leaf)-[:PG_LINKS__grid_fixtures]->(a:grid_fixtures__node) "
            "WHERE grid_fixtures__leaf.data.observed_at + hours(1) < now() RETURN a.name AS n",
        ],
    )
    # The general single-MATCH rule (req-grid-traversal-lang-shape-10) now refuses these first;
    # the temporal check still owns a base that IS bound but is not a node (an edge variable).
    def test_a_base_variable_the_pattern_does_not_name_is_refused_not_dropped(self, query):
        self._build()
        with pytest.raises(SearchExecutionError, match="does not bind|not a named node variable"):
            self._names(query)

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-16")
    def test_a_temporal_leaf_inside_not_exists_names_the_supported_form(self):
        self._build()
        inner = "{ MATCH (a)<-[:PG_LINKS__grid_fixtures]-(g:grid_fixtures__leaf) WHERE a.data.observed_at + hours(1) < now() }"
        with pytest.raises(SearchExecutionError, match="NOT EXISTS"):
            self._names(HOP + f"NOT EXISTS {inner} RETURN a.name AS n")
        with pytest.raises(SearchExecutionError, match="NOT EXISTS"):
            self._names(
                HOP + LOOKUP_GOLD + "NOT EXISTS { MATCH (a)<-[:PG_LINKS__grid_fixtures]-(g:grid_fixtures__leaf) "
                "WHERE a.data.observed_at + hours(p.data.severity_score) < now() } RETURN a.name AS n"
            )

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-21")
    def test_other_data_errors_are_not_blamed_on_the_temporal_leaf(self):
        """An invalid regex is the caller's own error; it must not read as a malformed stored value."""
        from django.db import DataError

        self._build()
        with pytest.raises(DataError):
            self._names(HOP + 'WHERE a.name =~ "(" AND a.data.observed_at + hours(1) < now() RETURN a.name AS n')

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-21")
    def test_an_offset_that_leaves_the_timestamp_range_is_a_search_error(self):
        self._build()
        with pytest.raises(SearchExecutionError, match="outside the supported range"):
            self._names(HOP + "WHERE a.data.observed_at + hours($h) < now() RETURN a.name AS n", {"h": 10**10})

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-6")
    @pytest.mark.parametrize("field", ["a.data.severity_score", "a.data.kind", "a.created_at", "a.entity_id"])
    def test_a_base_that_is_not_a_declared_date_time_is_rejected(self, field):
        self._build()
        with pytest.raises(SearchExecutionError, match="(takes only a date-time|typed data-lane field)"):
            self._names(HOP + f"WHERE {field} + hours(1) < now() RETURN a.name AS n")

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-7")
    def test_hours_that_is_not_an_integer_is_rejected(self):
        self._build()
        with pytest.raises(SearchExecutionError, match=r"hours\(\) takes only an integer"):
            self._names(
                HOP + 'LOOKUP p = (:grid_fixtures__node {kind: "policy-gold"}) '
                "WHERE a.data.observed_at + hours(p.data.kind) < now() RETURN a.name AS n"
            )

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-7")
    @pytest.mark.parametrize("value", [1.5, True, "3"])
    def test_a_param_that_is_not_a_whole_number_is_rejected(self, value):
        self._build()
        with pytest.raises(SearchExecutionError, match="whole number"):
            self._names(HOP + "WHERE a.data.observed_at + hours($h) < now() RETURN a.name AS n", {"h": value})

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-8")
    def test_a_param_instant_that_is_not_iso_8601_is_rejected(self):
        self._build()
        with pytest.raises(SearchExecutionError, match="ISO-8601"):
            self._names(HOP + "WHERE a.data.observed_at + hours(1) < $t RETURN a.name AS n", {"t": "yesterday"})

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-22")
    def test_a_naive_param_instant_and_a_naive_clock_are_rejected(self):
        self._build()
        with pytest.raises(SearchExecutionError, match="naive"):
            self._names(HOP + "WHERE a.data.observed_at + hours(1) < $t RETURN a.name AS n", {"t": "2026-03-10T00:00:00"})
        with pytest.raises(SearchExecutionError, match="naive"):
            self._names(
                HOP + "WHERE a.data.observed_at + hours(1) < now() RETURN a.name AS n",
                clock=lambda: datetime(2026, 3, 10),
            )
        with pytest.raises(SearchExecutionError, match="not a date-time"):
            self._names(
                HOP + "WHERE a.data.observed_at + hours(1) < now() RETURN a.name AS n",
                clock=cast("Any", lambda: "2026-03-10T00:00:00Z"),
            )

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-20")
    def test_a_lookup_whose_only_use_folds_away_is_rejected(self):
        self._build()
        with pytest.raises(SearchExecutionError, match="not used by any temporal comparison"):
            self._names(
                HOP + 'LOOKUP p = (:grid_fixtures__node {kind: "policy-gold"}) '
                f"WHERE $skip IS NULL OR {DUE} RETURN a.name AS n",
                {"skip": None},
            )


@DB
class TestTemporalOffsetJsonFields(_TemporalFixture):
    """A date-time and an hours value held inside a JSON column behave exactly like native columns."""

    SCHEMA = {
        "type": "object",
        "properties": {
            "seen": {"type": ["string", "null"], "format": "date-time"},
            "window": {"type": ["integer", "null"]},
        },
    }

    def _json_build(self, monkeypatch) -> None:
        from tap_plugin.grid_fixtures.models import PgNode as _PgNode

        PgNode: Any = _PgNode
        self._build()
        monkeypatch.setattr(PgNode, "FIELD_CRUD_SCHEMA", {**PgNode.FIELD_CRUD_SCHEMA, "tags": self.SCHEMA})
        for node in PgNode.objects.all():
            seen = node.observed_at
            node.tags = {"seen": seen.isoformat() if seen else None, "window": node.severity_score}
            node.save()
        # A missing key and an explicit JSON null, on alerts the native column says are observed.
        PgNode.objects.filter(name="fresh").update(tags={})
        PgNode.objects.filter(name="unobserved").update(tags={"seen": None})

    JSON_DUE = "a.data.tags.seen + hours(p.data.tags.window) < now()"

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-9")
    def test_json_base_and_json_hours_match_the_native_answer(self, monkeypatch):
        self._json_build(monkeypatch)
        positive = self._names(HOP + LOOKUP_GOLD + f"WHERE {self.JSON_DUE} RETURN a.name AS n")
        assert positive == ["overdue"]

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-9")
    def test_missing_key_and_json_null_key_are_null_bases_under_not(self, monkeypatch):
        """A key that is present but JSON null is SQL NULL only after the cast; NOT must still match it."""
        self._json_build(monkeypatch)
        negated = self._names(HOP + LOOKUP_GOLD + f"WHERE NOT {self.JSON_DUE} RETURN a.name AS n")
        assert negated == ["boundary", "fresh", "unobserved"]

    @pytest.mark.spec("req-grid-traversal-lang-temporal-offset-21")
    def test_a_malformed_stored_date_time_fails_loudly_on_both_result_paths(self, monkeypatch):
        from tap_plugin.grid_fixtures.models import PgNode as _PgNode

        PgNode: Any = _PgNode
        self._json_build(monkeypatch)
        PgNode.objects.filter(name="boundary").update(tags={"seen": "n/a", "window": 1})
        base = HOP + LOOKUP_GOLD + f"WHERE {self.JSON_DUE}"
        with pytest.raises(SearchExecutionError, match="stored value could not be used") as row_path:
            execute_gryphon_raw(base + " RETURN a.name AS n", {}, clock=lambda: NOW)
        assert row_path.value.__cause__ is not None  # the driver error stays on __cause__, server-side
        with pytest.raises(SearchExecutionError, match="stored value could not be used"):
            execute_gryphon_raw(base, {}, clock=lambda: NOW)
