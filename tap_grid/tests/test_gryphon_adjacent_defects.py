"""A bracketed dimension key is one literal key (`req-grid-dimension-query-form-4`, tap#1125).

Before the repair, `_json_spine_inner_path` returned the key and four resolvers spliced it into an
`entity__dimensions__<key>` string that Django re-split on `__`: `tap__cloud` matched nothing, and a
key spelled like a lookup (`isnull`, `contains`, ...) was re-read as that lookup.
"""

import pytest

from tap_grid.gryphon import explain_gryphon_raw
from tap_grid.service_types import WriteOperation
from tap_grid.services import write_batch

pytestmark = pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])

NODE = "grid_fixtures__node"
# Every key below is either a Django lookup/transform name or contains `__`.
LOOKUP_KEYS = ["isnull", "contains", "regex", "exact", "gt", "in", "startswith", "tap__cloud", "a__b"]


def _create_nodes(keys: list[str]) -> dict[str, str]:
    """One node per key, carrying only that key with the value `v-<key>`; returns key -> entity_id."""
    result = write_batch(
        [
            WriteOperation(
                verb="create_node",
                type_slug=NODE,
                payload={"name": f"Key {key}", "kind": "fixture"},
                dimensions={key: f"v-{key}"},
            )
            for key in keys
        ],
        batch_name="Literal dimension keys",
        batch_description="One node per authored flat dimension key",
    )
    assert result.success, result
    return {key: str(res.entity_id) for key, res in zip(keys, result.results, strict=True)}


def _ids(query: str) -> set[str]:
    cap = explain_gryphon_raw(query, {})
    assert cap["sql"].statements
    return {str(node["entity_id"]) for node in cap["envelope"]["nodes"]}


@pytest.mark.spec("req-grid-dimension-query-form-4")
def test_literal_dimension_key():
    """The issue's own reproduction: a flat key containing `__`, read by a labelless scan."""
    ids = _create_nodes(["tap__cloud"])
    assert _ids('MATCH (n) WHERE n.dimensions["tap__cloud"] = "aws" RETURN n') == set()
    assert _ids('MATCH (n) WHERE n.dimensions["tap__cloud"] = "v-tap__cloud" RETURN n') == {ids["tap__cloud"]}


@pytest.mark.spec("req-grid-dimension-query-form-4")
@pytest.mark.parametrize("label", ["", ":" + NODE], ids=["labelless", "typed"])
def test_lookup_named_keys_each_match_only_their_own_entity(label):
    ids = _create_nodes(LOOKUP_KEYS)
    for key in LOOKUP_KEYS:
        query = f'MATCH (n{label}) WHERE n.dimensions["{key}"] = "v-{key}" RETURN n'
        assert _ids(query) == {ids[key]}, key
        # Presence, absence and inequality read the same literal key.
        assert _ids(f'MATCH (n{label}) WHERE n.dimensions["{key}"] IS NOT NULL RETURN n') == {ids[key]}, key
        others = {i for k, i in ids.items() if k != key}
        assert _ids(f'MATCH (n{label}) WHERE n.dimensions["{key}"] IS NULL RETURN n') >= others, key
        assert not _ids(f'MATCH (n{label}) WHERE n.dimensions["{key}"] IS NULL RETURN n') & {ids[key]}, key


@pytest.mark.spec("req-grid-dimension-query-form-4")
@pytest.mark.parametrize(
    "predicate, matches",
    [
        ('n.dimensions["isnull"] =~ "^v-"', True),
        ('n.dimensions["isnull"] STARTS_WITH "v-"', True),
        ('n.dimensions["isnull"] IN ["v-isnull", "x"]', True),
        ('n.dimensions["isnull"] != "v-isnull"', False),
        ('n.dimensions["isnull"] > "a"', True),
        ('n.dimensions["isnull"] < "a"', False),
    ],
)
def test_every_comparison_operator_reads_the_literal_key(predicate, matches):
    ids = _create_nodes(["isnull", "other"])
    found = _ids(f"MATCH (n:{NODE}) WHERE {predicate} RETURN n")
    assert (ids["isnull"] in found) is matches, (predicate, found)
    assert ids["other"] not in found  # `other` has no `isnull` key: unobserved never matches


@pytest.mark.spec("req-grid-dimension-query-form-4")
def test_double_underscore_key_is_not_a_nested_path():
    """`a__b` is one key; entities holding keys `a` and `b` are not matched through it."""
    ids = _create_nodes(["a", "b", "a__b"])
    assert _ids('MATCH (n) WHERE n.dimensions["a__b"] = "v-a__b" RETURN n') == {ids["a__b"]}
    assert _ids('MATCH (n) WHERE n.dimensions["a__b"] = "v-a" RETURN n') == set()


@pytest.mark.spec("req-grid-dimension-query-form-4")
@pytest.mark.parametrize("label", ["", ":" + NODE], ids=["labelless", "typed"])
def test_absent_literal_key_is_empty_not_an_error(label):
    _create_nodes(["present"])
    assert _ids(f'MATCH (n{label}) WHERE n.dimensions["isnull"] = "x" RETURN n') == set()
    assert _ids(f'MATCH (n{label}) WHERE n.dimensions["no__such"] = "x" RETURN n') == set()


@pytest.mark.spec("req-grid-dimension-query-form-4")
def test_edge_chain_reads_literal_keys_on_both_endpoints_and_the_edge():
    nodes = write_batch(
        [
            WriteOperation(
                verb="create_node",
                type_slug="grid_fixtures__nesting_container",
                payload={"name": "Realm"},
                dimensions={"isnull": "v-src"},
            ),
            WriteOperation(
                verb="create_node",
                type_slug="grid_fixtures__constrained_target",
                payload={"name": "Place", "description": ""},
                dimensions={"tap__cloud": "v-dst"},
            ),
        ],
        batch_name="Literal key chain nodes",
        batch_description="Endpoints for the edge chain",
    )
    assert nodes.success, nodes
    src, dst = (str(r.entity_id) for r in nodes.results)
    edge = write_batch(
        [
            WriteOperation(
                verb="create_edge",
                from_target=src,
                to_target=dst,
                edge_type="NESTING_LINK__grid_fixtures",
                dimensions={"contains": "v-edge"},
            )
        ],
        batch_name="Literal key chain nodes",
        batch_description="Endpoints for the edge chain",
    )
    assert edge.success, edge
    base = (
        "MATCH (r:grid_fixtures__nesting_container)-[e:NESTING_LINK__grid_fixtures]->"
        "(l:grid_fixtures__constrained_target) "
    )

    def hits(where: str) -> set[str]:
        return _ids(base + f"WHERE {where} RETURN l")

    assert hits('e.dimensions["contains"] = "v-edge"') == {dst}
    assert hits('l.dimensions["tap__cloud"] = "v-dst"') == {dst}
    assert hits('r.dimensions["isnull"] = "v-src"') == {dst}
    assert hits('e.dimensions["contains"] = "v-dst"') == set()
    assert hits('e.dimensions["isnull"] IS NOT NULL') == set()


@pytest.mark.spec("req-grid-dimension-query-form-4")
def test_envelope_order_by_reads_the_literal_key():
    ids = _create_nodes(["tap__cloud"])
    cap = explain_gryphon_raw(
        f'MATCH (n:{NODE}) WHERE n.dimensions["tap__cloud"] IS NOT NULL RETURN n ORDER BY n.dimensions["tap__cloud"] DESC',
        {},
    )
    assert {str(n["entity_id"]) for n in cap["envelope"]["nodes"]} == {ids["tap__cloud"]}


@pytest.mark.spec("req-grid-dimension-query-form-4")
@pytest.mark.parametrize("label", ["", ":" + NODE], ids=["labelless", "typed"])
def test_the_key_is_a_bound_parameter_not_sql_text(label):
    _create_nodes(["tap__cloud"])
    cap = explain_gryphon_raw(f'MATCH (n{label}) WHERE n.dimensions["tap__cloud"] = "aws" RETURN n', {})
    statements = [st for st in cap["sql"].statements if "dimensions" in st.sql]
    assert statements
    for st in statements:
        assert "tap__cloud" not in st.sql, st.sql
        assert "tap__cloud" in repr(st.params), st.params
