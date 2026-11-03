"""Construct-has-effect: every construct the parser accepts must change the emitted SQL.

The accept-and-drop reproduction harness for #196, and the durable guard against the
class. Gryphon's doctrine is apply-or-reject, never accept-and-drop; the mechanical
form of that rule is: for any construct, the query carrying it must either

* emit **different SQL** than the same query without it (applied), or
* be **rejected** with ``SearchExecutionError`` (refused).

A query that is accepted and emits byte-identical SQL has dropped the construct — the
one outcome the doctrine forbids. That is precisely what `#196` documents for node
inline property maps, and what #247 documents for ``MATCH p =`` path variables.

Why this asserts on SQL when the Gridkin discipline prefers answer-oracles: the oracle
answers *"is the answer correct"*; this file answers *"was the construct consumed at
all"* — a question about EFFECT, not shape. A dropped filter and a working filter can
both produce a well-formed envelope; only the issued SQL distinguishes "filtered" from
"ignored" without depending on seeded data. Do not "correct" this file toward the
oracle: both instruments are needed, and the answer-level coverage lives in the Gridkin
corpus (gryphon_playground). The vacuity trap the corpus doctrine worries about is
handled explicitly — a capture with no statements fails, never passes.

Uses the core-registered ``batch`` type (scalar columns ``name``/``source``) so this
file depends on no plugin — the data-lane allowlist tests established that vehicle.
"""

from typing import Any

import pytest
from psycopg.types.json import Json, Jsonb

from tap_grid.exceptions import SearchExecutionError
from tap_grid.gryphon import explain_gryphon_raw

pytestmark = pytest.mark.django_db(databases=["default", "search_readonly"])


def _issued(query: str, inputs: dict[str, Any] | None = None) -> list[tuple[str, tuple[Any, ...]]]:
    """The ordered (sql, params) pairs a query's execution issued."""
    capture = explain_gryphon_raw(query, inputs or {})["sql"]
    # psycopg JSON wrappers have identity equality, so compare their stable
    # representations too: equal edge-map predicates must not look different
    # merely because the two executions allocated different Jsonb objects.
    return [
        (stmt.sql, tuple(repr(param) if isinstance(param, (Json, Jsonb)) else param for param in (stmt.params or ())))
        for stmt in capture.statements
    ]


def _assert_construct_has_effect(with_construct: str, without_construct: str) -> None:
    """The pair-wise effect assertion.

    Rejection of the WITH form is a pass — refusing a construct honors
    apply-or-reject. Acceptance with identical SQL is the failure this file exists
    to catch. Empty captures fail loudly on either side: a query that emits no SQL
    at all proves nothing (the ``field_absent`` vacuous-pass lesson from the
    Gridkin corpus, recorded in bare_match.gridkin.json).
    """
    try:
        issued_with = _issued(with_construct)
    except SearchExecutionError:
        return  # refused = consumed; apply-or-reject honored
    issued_without = _issued(without_construct)
    assert issued_with, f"vacuous: no SQL captured for {with_construct!r}"
    assert issued_without, f"vacuous: no SQL captured for {without_construct!r}"
    assert issued_with != issued_without, (
        "ACCEPT-AND-DROP: the construct changed nothing.\n"
        f"  with:    {with_construct}\n"
        f"  without: {without_construct}\n"
        "Identical SQL and params were issued for both, so the construct was parsed "
        "and then silently discarded — the outcome apply-or-reject forbids. Either "
        "apply it (route it into the queryset) or reject it with a clear error."
    )


CASES = [
    # Duplicate authored constraints must never collapse to the later value.
    # The shared parser must refuse before any dispatch/parameter extraction.
    pytest.param(
        'MATCH (b:batch {name: "required", name: "later"}) RETURN b',
        'MATCH (b:batch {name: "later"}) RETURN b',
        id="duplicate-inline-node-key",
    ),
    pytest.param(
        'MATCH (a:batch {name: "required", name: "later"})-[e]->(b:batch) RETURN a, b',
        'MATCH (a:batch {name: "later"})-[e]->(b:batch) RETURN a, b',
        id="duplicate-inline-chain-node-key",
    ),
    pytest.param(
        'MATCH (a:batch)-[e {kind: "required", kind: "later"}]->(b:batch) RETURN a, b',
        'MATCH (a:batch)-[e {kind: "later"}]->(b:batch) RETURN a, b',
        id="duplicate-inline-edge-key",
    ),
    pytest.param(
        'MATCH (t:batch {name: "required", name: "later"}) OPTIONAL MATCH (t)-[:X]->(w:batch) '
        "RETURN t.entity_id AS a, COUNT(w) AS c",
        'MATCH (t:batch {name: "later"}) OPTIONAL MATCH (t)-[:X]->(w:batch) ' "RETURN t.entity_id AS a, COUNT(w) AS c",
        id="duplicate-inline-optional-mandatory-key",
    ),
    pytest.param(
        'MATCH (t:batch) OPTIONAL MATCH (t)-[:X]->(w:batch {name: "required", name: "later"}) '
        "RETURN t.entity_id AS a, COUNT(w) AS c",
        'MATCH (t:batch) OPTIONAL MATCH (t)-[:X]->(w:batch {name: "later"}) ' "RETURN t.entity_id AS a, COUNT(w) AS c",
        id="duplicate-inline-optional-node-key",
    ),
    # The #196 defect: node inline property map, string value. The WHERE-spelled
    # control below proves the same filter IS expressible, so a drop here is a
    # defect in the construct, not in the field path.
    pytest.param(
        'MATCH (b:batch {name: "x"}) RETURN b',
        "MATCH (b:batch) RETURN b",
        id="node-inline-prop-string",
    ),
    # The boolean form — the shape 30+ of the BloodHound org-setting queries use
    # (`{is_open: true}`). Against a CharField this must land in the rejection
    # branch (type strictness) or change the SQL; today it is silently dropped.
    pytest.param(
        "MATCH (b:batch {name: true}) RETURN b",
        "MATCH (b:batch) RETURN b",
        id="node-inline-prop-boolean",
    ),
    # Inline map on a chain-hop node — the _build_chain_queryset site, distinct
    # from the type-scan site above (#196 names both).
    pytest.param(
        'MATCH (a:batch {name: "x"})-[e]->(b:batch) RETURN a, b',
        "MATCH (a:batch)-[e]->(b:batch) RETURN a, b",
        id="node-inline-prop-on-chain",
    ),
    # CONTROL — the same predicate spelled via WHERE has always worked; this pins
    # the harness itself (a broken capture would fail here first).
    pytest.param(
        'MATCH (b:batch) WHERE b.data.name = "x" RETURN b',
        "MATCH (b:batch) RETURN b",
        id="control-where-filter",
    ),
    # CONTROL — the EDGE inline map is the half that was built (executor.py:1798);
    # green here + red above is the node/edge asymmetry #196 describes.
    pytest.param(
        "MATCH (a:batch)-[e {weight: 1}]->(b:batch) RETURN a, b",
        "MATCH (a:batch)-[e]->(b:batch) RETURN a, b",
        id="control-edge-inline-prop",
    ),
    # The OPTIONAL MATCH pair — the optional node's map constrains the join
    # (site 4a) and the mandatory anchor's map filters the outer scan (4b).
    pytest.param(
        'MATCH (t:batch) OPTIONAL MATCH (t)-[:X]->(g:batch {name: "x"}) ' "RETURN t.entity_id AS a, COUNT(g) AS c",
        "MATCH (t:batch) OPTIONAL MATCH (t)-[:X]->(g:batch) RETURN t.entity_id AS a, COUNT(g) AS c",
        id="node-inline-prop-on-optional-node",
    ),
    pytest.param(
        'MATCH (t:batch {name: "x"}) OPTIONAL MATCH (t)-[:X]->(g:batch) ' "RETURN t.entity_id AS a, COUNT(g) AS c",
        "MATCH (t:batch) OPTIONAL MATCH (t)-[:X]->(g:batch) RETURN t.entity_id AS a, COUNT(g) AS c",
        id="node-inline-prop-on-optional-anchor",
    ),
    pytest.param(
        'MATCH (t:batch) OPTIONAL MATCH (t {name: "required"})-[:X]->(w:batch) '
        "RETURN t.entity_id AS a, COUNT(w) AS c",
        "MATCH (t:batch) OPTIONAL MATCH (t)-[:X]->(w:batch) RETURN t.entity_id AS a, COUNT(w) AS c",
        id="node-inline-prop-on-optional-repeated-anchor",
    ),
    # Labelless bare scan with a map — consumed by REJECTION (there is no model
    # to resolve `data.k` against); lands in the rejection branch above.
    pytest.param(
        'MATCH (n {name: "x"}) RETURN n',
        "MATCH (n) RETURN n",
        id="node-inline-prop-labelless-rejects",
    ),
    # Was the third accept-and-drop instance (#247), pinned here as a strict
    # xfail until 2026-08-31, when the executor gained the rejection above the
    # dispatch fork — the marker came off exactly as designed (strict xfail →
    # XPASS → loud). Now consumed via the rejection branch; real binding ships
    # with variable-length paths (#259).
    pytest.param(
        "MATCH p = (a:batch)-[e]->(b:batch) RETURN a",
        "MATCH (a:batch)-[e]->(b:batch) RETURN a",
        id="path-var-rejects",
    ),
    # tap#743 — a variable reused at a SECOND position inside ONE pattern is a
    # join ("the same `a` on both ends"). Before the fix the closing `(a)` was
    # bound-first-occurrence-only and contributed no constraint at all, so this
    # emitted byte-identical SQL to the distinct-variable form below: the exact
    # accept-and-drop shape, and a superset answer.
    pytest.param(
        "MATCH (a:batch)-[:X]->(b:batch)<-[:Y]-(a) RETURN a.name AS n",
        "MATCH (a:batch)-[:X]->(b:batch)<-[:Y]-(c) RETURN a.name AS n",
        id="node-var-reused-in-pattern",
    ),
    # The single-hop envelope road to the same lowering: a self-loop.
    pytest.param(
        "MATCH (a:batch)-[e:X]->(a:batch) RETURN a, e",
        "MATCH (a:batch)-[e:X]->(b:batch) RETURN a, e",
        id="node-var-self-loop",
    ),
    # The edge half of the same rule — `e` at two hops is one Edge row.
    pytest.param(
        "MATCH (a:batch)-[e:X]->(b:batch)<-[e:Y]-(c:batch) RETURN a.name AS n",
        "MATCH (a:batch)-[e1:X]->(b:batch)<-[e2:Y]-(c:batch) RETURN a.name AS n",
        id="edge-var-reused-in-pattern",
    ),
    # One name, two roles — consumed by REJECTION (no Entity is an Edge row).
    pytest.param(
        "MATCH (a:batch)-[a:X]->(b:batch) RETURN b",
        "MATCH (a:batch)-[e:X]->(b:batch) RETURN b",
        id="node-and-edge-share-a-name-rejects",
    ),
]


@pytest.mark.parametrize(("with_construct", "without_construct"), CASES)
def test_construct_has_effect(with_construct: str, without_construct: str) -> None:
    _assert_construct_has_effect(with_construct, without_construct)


class TestInlineMapMatchesWhereSemantics:
    """The two spellings of one predicate must reject identically.

    `{k: v}` routes through the same allowlist and the same type-strictness
    derivation as `WHERE var.data.k = v` (`_enforce_type_strictness`); these pin
    the equivalence so the inline route can never become a second, laxer path
    into the ORM. The boolean case is the live divergence this caught during
    the #196 fix: the inline form initially slipped `True` to Django, which
    stringified it into `'True'` — accepted-and-wrong — while the WHERE spelling
    of the identical predicate was rejected.
    """

    def test_type_mismatch_rejected_like_where(self):
        with pytest.raises(SearchExecutionError, match="Type mismatch"):
            _issued("MATCH (b:batch {name: true}) RETURN b")

    def test_undeclared_field_rejected_like_where(self):
        with pytest.raises(SearchExecutionError, match="not a declared field"):
            _issued('MATCH (b:batch {nonesuch: "x"}) RETURN b')

    def test_labelless_map_rejected_with_named_remedy(self):
        with pytest.raises(SearchExecutionError, match="require a node label"):
            _issued('MATCH (n {name: "x"}) RETURN n')

    def test_labelless_chain_node_map_rejected(self):
        # PR #253 review asked whether the chain path's `declared_types=None`
        # (for labelless nodes) skips the rejection along with the type check.
        # It does not: the resolver runs BEFORE the type check in
        # _node_inline_prop_filters and raises on a labelless data-lane path.
        # Pinned so the ordering can never silently invert.
        with pytest.raises(SearchExecutionError, match="without a node label"):
            _issued('MATCH (a {name: "x"})-[e]->(b:batch) RETURN a, b')

    def test_path_var_rejected_with_breadcrumb(self):
        # #247: refusal names the unusable binding, the remedy, and where real
        # binding ships (#259) — apply-or-reject with a named road forward.
        with pytest.raises(SearchExecutionError, match="Path variables are not supported"):
            _issued("MATCH p = (a:batch)-[e]->(b:batch) RETURN a")

    def test_path_var_rejected_on_the_optional_match_road(self):
        # The guard sits ABOVE the optional-match dispatch fork; a binding on
        # the mandatory clause of an OPTIONAL query must not slip past it.
        with pytest.raises(SearchExecutionError, match="Path variables are not supported"):
            _issued("MATCH p = (t:batch) OPTIONAL MATCH (t)-[:X]->(w:batch) " "RETURN t.entity_id AS a, COUNT(w) AS c")

    def test_optional_clause_path_binding_is_a_parse_error(self):
        # The GRAMMAR forbids a binding on the optional clause (`optional_match_
        # clause` has no `path_var?` — grammar.lark:33), so the dispatch-fork
        # guard has nothing to cover there; this pins that boundary. If the
        # grammar ever grows the slot, this flips — extend the guard in the same
        # change instead of silently reopening #247 on one road (PR #260 review).
        with pytest.raises(SearchExecutionError, match="parse error"):
            _issued("MATCH (t:batch) OPTIONAL MATCH p = (t)-[:X]->(w:batch) " "RETURN t.entity_id AS a, COUNT(w) AS c")

    def test_labelless_optional_node_map_rejected(self):
        # Same question at the OPTIONAL MATCH site (w_node.label is None →
        # declared_types=None); same answer, same ordering guarantee.
        with pytest.raises(SearchExecutionError, match="without a node label"):
            _issued(
                'MATCH (t:batch) OPTIONAL MATCH (t)-[:X]->(w {name: "x"}) ' "RETURN t.entity_id AS a, COUNT(w) AS c"
            )

    def test_dollar_param_resolves_in_inline_map(self):
        issued = _issued("MATCH (b:batch {name: $v}) RETURN b", {"v": "y"})
        assert any("y" in map(str, params) for _, params in issued)

    def test_inline_and_where_spellings_emit_identical_sql(self):
        # The strongest form of "the rules apply identically": not merely both
        # filtered, but the SAME filter — one derivation, two spellings.
        inline = _issued('MATCH (b:batch {name: "x"}) RETURN b')
        where = _issued('MATCH (b:batch) WHERE b.data.name = "x" RETURN b')
        assert inline == where


class TestInPatternVariableReuseIsAJoin:
    """A variable repeated inside ONE pattern unifies — tap#743.

    The asymmetry that made this bug survive: reuse ACROSS MATCH clauses was
    already refused (``_reject_variables_bound_in_multiple_match_clauses``,
    req-grid-traversal-lang-shape-8) and a comma join was already refused, so
    only the in-pattern case was silent. It is the one case where the join is
    actually expressible in the lowering, so the answer is apply, not reject.
    """

    def test_reuse_emits_a_column_equality_not_a_second_scan(self):
        # The proof that "apply" happened as a JOIN and not as an extra scan or a
        # correlated subquery: the emitted SQL compares the two positions'
        # endpoint columns directly, in the one SELECT the chain already had.
        import re

        sql, _ = _issued("MATCH (a:batch)-[:X]->(b:batch)<-[:Y]-(a) RETURN a.name AS n")[0]
        assert re.search(r'"from_entity_id" = \(?[\w".]*"from_entity_id"\)?', sql), sql
        assert sql.count("SELECT") == 1, sql

    def test_reuse_differs_from_distinct_variables(self):
        reused = _issued("MATCH (a:batch)-[:X]->(b:batch)<-[:Y]-(a) RETURN a.name AS n")
        distinct = _issued("MATCH (a:batch)-[:X]->(b:batch)<-[:Y]-(c) RETURN a.name AS n")
        assert reused != distinct

    def test_node_and_edge_sharing_a_name_is_rejected_with_a_remedy(self):
        with pytest.raises(SearchExecutionError, match="names both a node and an edge"):
            _issued("MATCH (a:batch)-[a:X]->(b:batch) RETURN b")

    def test_optional_match_self_reference_is_rejected_with_a_remedy(self):
        # The optional executor is not the chain builder and cannot unify; it
        # refuses rather than counting any matching edge as a self-loop.
        with pytest.raises(SearchExecutionError, match="cannot reuse the MATCH variable"):
            _issued("MATCH (t:batch) OPTIONAL MATCH (t)-[:X]->(t) RETURN t.entity_id AS a, COUNT(t) AS c")


    @pytest.mark.parametrize(
        "query",
        [
            "MATCH (t:batch) OPTIONAL MATCH (t)-[w:X]->(w:batch) RETURN t.entity_id AS id, COUNT(w) AS c",
            "MATCH (t:batch) OPTIONAL MATCH (t)-[t:X]->(w:batch) RETURN t.entity_id AS id, COUNT(w) AS c",
        ],
    )
    def test_optional_match_node_and_edge_sharing_a_name_is_rejected(self, query):
        # The OPTIONAL builder shares the chain path's refusal (one helper), so the
        # rule holds at both sites; before, the edge binding overwrote the node's.
        with pytest.raises(SearchExecutionError, match="names both a node and an edge"):
            _issued(query)

    def test_optional_match_distinct_edge_name_is_still_accepted(self):
        assert _issued("MATCH (t:batch) OPTIONAL MATCH (t)-[e:X]->(w:batch) RETURN t.entity_id AS id, COUNT(w) AS c")

    def test_optional_match_anchor_label_must_match_the_mandatory_label(self):
        with pytest.raises(SearchExecutionError, match="repeats the MATCH variable with a different label"):
            _issued(
                'MATCH (t:batch) OPTIONAL MATCH (t:other {name: "x"})-[:X]->(w:batch) '
                "RETURN t.entity_id AS id, COUNT(w) AS c"
            )


class TestWhereOnAnUnboundVariable:
    """A WHERE leaf on a variable the ONE mandatory MATCH does not bind is refused — tap#1072.

    ``_filter_predicate_for_bindings`` drops a leaf whose variable a clause does not bind. That is
    the multi-MATCH union's rule (shape-5); in a query with ONE mandatory MATCH there is no other
    clause the leaf could belong to, so the drop turned a mistyped variable into no filter at all.
    """

    REMEDY = "does not bind"

    def test_comparison_on_an_unbound_variable_is_refused(self):
        with pytest.raises(SearchExecutionError, match=self.REMEDY):
            _issued('MATCH (a:batch)-[:X]->(b:batch) WHERE zz.data.name = "x" RETURN b.name AS n')

    def test_the_refusal_names_the_unbound_and_the_bound_variables(self):
        with pytest.raises(SearchExecutionError, match=r"'zz'.*bound: 'a', 'b'"):
            _issued('MATCH (a:batch)-[:X]->(b:batch) WHERE zz.data.name = "x" RETURN b.name AS n')

    @pytest.mark.parametrize(
        "where",
        [
            'NOT zz.data.name = "x"',
            'zz.data.name IN ["x", "y"]',
            "zz.data.name IS NULL",
            'b.data.name = "x" AND zz.data.name = "y"',
            'b.data.name = "x" OR zz.data.name = "y"',
        ],
    )
    def test_every_leaf_form_and_combinator_is_refused(self, where):
        with pytest.raises(SearchExecutionError, match=self.REMEDY):
            _issued(f"MATCH (a:batch)-[:X]->(b:batch) WHERE {where} RETURN b.name AS n")

    def test_type_scan_on_an_unbound_variable_is_refused(self):
        with pytest.raises(SearchExecutionError, match=self.REMEDY):
            _issued('MATCH (b:batch) WHERE zz.data.name = "x" RETURN b.name AS n')

    def test_an_unnamed_labelled_node_is_not_addressable_by_its_label(self):
        with pytest.raises(SearchExecutionError, match=self.REMEDY):
            _issued('MATCH (:batch)-[:X]->(b:batch) WHERE batch.data.name = "x" RETURN b.name AS n')

    def test_a_bound_edge_variable_is_still_accepted(self):
        assert _issued('MATCH (a:batch)-[e:X]->(b:batch) WHERE e.data.edge_type = "X" RETURN b.name AS n')

    def test_a_bound_variable_changes_the_sql_as_before(self):
        with_where = _issued('MATCH (a:batch)-[:X]->(b:batch) WHERE b.data.name = "x" RETURN b.name AS n')
        without = _issued("MATCH (a:batch)-[:X]->(b:batch) RETURN b.name AS n")
        assert with_where != without

    def test_a_union_refuses_a_leaf_that_no_clause_binds(self):
        # tap#1084: shape-5's scoping is for a leaf ANOTHER clause binds; a leaf nobody binds is a drop.
        with pytest.raises(SearchExecutionError, match=r"'zz'.*any MATCH clause.*bound: 'a', 'b'"):
            _issued('MATCH (a:batch) MATCH (b:batch) WHERE zz.data.name = "x" RETURN a.name AS n')

    def test_a_union_refuses_an_unbound_leaf_under_not_and_or(self):
        for where in ('NOT zz.data.name = "x"', 'a.data.name = "x" OR zz.data.name = "y"'):
            with pytest.raises(SearchExecutionError, match="any MATCH clause"):
                _issued(f"MATCH (a:batch) MATCH (b:batch) WHERE {where} RETURN a.name AS n")

    def test_a_union_keeps_its_per_clause_scoping(self):
        # One global WHERE over two independent MATCH clauses: a leaf on the other clause's variable
        # must not apply to this one (shape-5). The refusal is for ONE mandatory MATCH only.
        assert _issued('MATCH (a:batch) MATCH (b:batch) WHERE a.data.name = "x" RETURN a.name AS n')

    def test_optional_match_keeps_its_scoping(self):
        assert _issued(
            'MATCH (t:batch) OPTIONAL MATCH (t)-[:X]->(g:batch) WHERE g.data.name = "x" '
            "RETURN t.entity_id AS a, COUNT(g) AS c"
        )


class TestReturnOnAnUnboundVariable:
    """req-grid-traversal-lang-shape-11, tap#1079 (found beside tap#1072).

    A single-node type-scan RETURN item naming a variable the pattern does not bind was skipped
    silently, where the chain road and an aggregate argument both refused it.
    """

    @pytest.mark.parametrize(
        "query",
        [
            "MATCH (a:batch) RETURN b.name AS x",
            "MATCH (a:batch) RETURN a.name AS y, b.name AS x",
            "MATCH (a:batch) RETURN b",
        ],
    )
    def test_type_scan_return_on_an_unbound_variable_is_refused(self, query):
        with pytest.raises(SearchExecutionError, match="Unknown variable 'b' in RETURN"):
            _issued(query)

    def test_a_bound_variable_still_returns(self):
        assert _issued("MATCH (a:batch) RETURN a.name AS x")

    def test_a_union_return_on_another_clauses_variable_is_kept(self):
        assert _issued("MATCH (a:batch) MATCH (b:batch) RETURN a.name AS x, b.name AS y")


class TestInputNullPredicateEffect:
    """`$p IS [NOT] NULL` — req-grid-traversal-lang-param-null.

    This construct is the one place where **identical SQL is the correct outcome**, so
    the effect assertion has to be stated in both directions rather than borrowed from
    ``_assert_construct_has_effect``. The construct's job is to decide whether a filter
    is in the plan at all:

    * input supplied  -> the filter is applied  -> SQL differs from the unfiltered query
    * input NULL      -> the filter is withdrawn -> SQL is byte-identical, *by design*

    The second line is only distinguishable from accept-and-drop because the first line
    exists: the same query, same construct, different input, different plan. A drop
    would flatten both. The third leg is the required-param guard, which is why a
    *forgotten* input cannot masquerade as the withdrawn case.
    """

    OPTIONAL = "MATCH (b:batch) WHERE $name IS NULL OR b.name = $name RETURN b"
    UNFILTERED = "MATCH (b:batch) RETURN b"

    def test_supplied_input_puts_the_filter_in_the_plan(self):
        issued = _issued(self.OPTIONAL, {"name": "x"})
        assert issued, "vacuous: no SQL captured"
        assert issued != _issued(self.UNFILTERED)

    def test_null_input_withdraws_the_filter_from_the_plan(self):
        """Deliberately identical: a withdrawn filter must not leave a no-op predicate
        behind. This is the construct's effect, not its absence."""
        assert _issued(self.OPTIONAL, {"name": None}) == _issued(self.UNFILTERED)

    def test_empty_string_input_is_a_filter_not_a_withdrawal(self):
        issued = _issued(self.OPTIONAL, {"name": ""})
        assert issued != _issued(self.UNFILTERED)

    def test_forgotten_input_cannot_masquerade_as_the_withdrawn_case(self):
        with pytest.raises(SearchExecutionError, match="requires inputs"):
            _issued(self.OPTIONAL, {})

    def test_constant_true_where_is_withdrawn_not_lowered(self):
        """`WHERE $p IS NOT NULL` with a supplied value is a constant TRUE — it filters
        nothing, and the correct plan is the unfiltered one."""
        assert _issued("MATCH (b:batch) WHERE $p IS NOT NULL RETURN b", {"p": "x"}) == _issued(self.UNFILTERED)

    def test_constant_false_where_is_refused(self):
        with pytest.raises(SearchExecutionError, match="constant FALSE"):
            _issued("MATCH (b:batch) WHERE $p IS NOT NULL RETURN b", {"p": None})


@pytest.mark.spec("req-grid-dimension-query-form-2")
@pytest.mark.parametrize(
    "query",
    [
        "MATCH (n) WHERE n.dimensions.tap.cloud IS NOT NULL RETURN n",
        'MATCH (n) WHERE n.dimensions["tap"]["cloud"] IS NOT NULL RETURN n',
        'MATCH (n) WHERE n.dimensions["tap"].cloud = "aws" RETURN n',
    ],
)
def test_bare_dimension_paths_are_refused_before_sql(query: str) -> None:
    with pytest.raises(SearchExecutionError, match=r'\["tap\.cloud"\]'):
        _issued(query)
