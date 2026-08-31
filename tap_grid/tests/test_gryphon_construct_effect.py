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

from tap_grid.exceptions import SearchExecutionError
from tap_grid.gryphon import explain_gryphon_raw

pytestmark = pytest.mark.django_db(databases=["default", "search_readonly"])


def _issued(query: str, inputs: dict[str, Any] | None = None) -> list[tuple[str, tuple[Any, ...]]]:
    """The ordered (sql, params) pairs a query's execution issued."""
    capture = explain_gryphon_raw(query, inputs or {})["sql"]
    return [(stmt.sql, tuple(stmt.params or ())) for stmt in capture.statements]


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
    # Labelless bare scan with a map — consumed by REJECTION (there is no model
    # to resolve `data.k` against); lands in the rejection branch above.
    pytest.param(
        'MATCH (n {name: "x"}) RETURN n',
        "MATCH (n) RETURN n",
        id="node-inline-prop-labelless-rejects",
    ),
    # Third instance of the pattern (#247): a path variable parses onto
    # MatchClause.path_var and nothing reads it. strict xfail — when path_var is
    # bound or rejected, this flips loudly and the marker comes off.
    pytest.param(
        "MATCH p = (a:batch)-[e]->(b:batch) RETURN a",
        "MATCH (a:batch)-[e]->(b:batch) RETURN a",
        id="path-var",
        marks=pytest.mark.xfail(
            strict=True,
            reason="path_var parsed and discarded — accept-and-drop, tracked in #247",
        ),
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

    def test_labelless_optional_node_map_rejected(self):
        # Same question at the OPTIONAL MATCH site (w_node.label is None →
        # declared_types=None); same answer, same ordering guarantee.
        with pytest.raises(SearchExecutionError, match="without a node label"):
            _issued(
                'MATCH (t:batch) OPTIONAL MATCH (t)-[:X]->(w {name: "x"}) '
                "RETURN t.entity_id AS a, COUNT(w) AS c"
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
