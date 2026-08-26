"""Tests for the TAP gryphon language — parser, executor, Search model, and search service.

Covers spec-grid-traversal-language.md and spec-grid-traversal-execution.md.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from tap_grid.exceptions import SearchExecutionError
from tap_grid.gryphon.ast_nodes import (
    AndPred,
    Comparison,
    DotStep,
    GryphonAST,
    KeyStep,
    LimitClause,
    NotPred,
    OrderByClause,
    OrPred,
    ParamRef,
    WildcardStep,
)
from tap_grid.gryphon.parser import GryphonParseError, parse_gryphon
from tap_grid.models import Search
from tap_grid.search import execute_search

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HUB_SPOKE_QUERY = [
    "MATCH (hub)-[e]-(neighbor)",
    "WHERE hub.entity_id = $entity_id",
    "RETURN hub, e, neighbor",
]

HUB_SPOKE_QUERY_STR = "MATCH (hub)-[e]-(neighbor) WHERE hub.entity_id = $entity_id RETURN hub, e, neighbor"


def _gryphon_search(**kwargs):
    defaults = {
        "name": "Hub and Spoke",
        "search_type": "gryphon",
        "root": "node",
        "definition": {"query": HUB_SPOKE_QUERY},
    }
    defaults.update(kwargs)
    return Search(**defaults)


# ---------------------------------------------------------------------------
# TestGryphonParser — req-grid-traversal-lang-shape / storage / patterns / filters / combinators / params / returns
# ---------------------------------------------------------------------------


class TestGryphonParser:
    def test_hub_spoke_list_form_parses(self):
        ast = parse_gryphon(HUB_SPOKE_QUERY)
        assert isinstance(ast, GryphonAST)
        assert len(ast.match_clauses) == 1

    def test_hub_spoke_string_form_parses(self):
        ast = parse_gryphon(HUB_SPOKE_QUERY_STR)
        assert isinstance(ast, GryphonAST)
        assert len(ast.match_clauses) == 1

    @pytest.mark.spec("req-grid-traversal-lang-storage-3")
    def test_list_and_string_forms_equivalent(self):
        """req-grid-traversal-lang-storage-3: both forms normalize to the same AST."""
        ast_list = parse_gryphon(HUB_SPOKE_QUERY)
        ast_str = parse_gryphon(HUB_SPOKE_QUERY_STR)
        assert ast_list == ast_str

    def test_match_clause_structure(self):
        """req-grid-traversal-lang-patterns: node/edge variables and direction."""
        ast = parse_gryphon(HUB_SPOKE_QUERY)
        mc = ast.match_clauses[0]
        assert mc.path_var is None
        assert len(mc.patterns) == 1
        pattern = mc.patterns[0]
        assert len(pattern.nodes) == 2
        assert len(pattern.edges) == 1
        hub_node = pattern.nodes[0]
        assert hub_node.variable == "hub"
        edge = pattern.edges[0]
        assert edge.variable == "e"
        assert edge.direction == "any"

    def test_outbound_edge_direction(self):
        """req-grid-traversal-lang-patterns-3: directed outbound."""
        ast = parse_gryphon("MATCH (a)-[e]->(b) WHERE a.entity_id = $id RETURN a, e, b")
        edge = ast.match_clauses[0].patterns[0].edges[0]
        assert edge.direction == "out"

    def test_inbound_edge_direction(self):
        """req-grid-traversal-lang-patterns-3: directed inbound."""
        ast = parse_gryphon("MATCH (a)<-[e]-(b) WHERE a.entity_id = $id RETURN a, e, b")
        edge = ast.match_clauses[0].patterns[0].edges[0]
        assert edge.direction == "in"

    def test_typed_edge(self):
        """req-grid-traversal-lang-patterns-2: typed edge."""
        ast = parse_gryphon("MATCH (a)-[e:ON_HOST]-(b) WHERE a.entity_id = $id RETURN a")
        edge = ast.match_clauses[0].patterns[0].edges[0]
        assert edge.edge_type == "ON_HOST"

    def test_node_label(self):
        """req-grid-traversal-lang-patterns-1: node label."""
        ast = parse_gryphon("MATCH (h:host)-[e]-(n) WHERE h.entity_id = $id RETURN h")
        node = ast.match_clauses[0].patterns[0].nodes[0]
        assert node.label == "host"
        assert node.variable == "h"

    def test_path_variable(self):
        """req-grid-traversal-lang-patterns-4: path variable binding."""
        ast = parse_gryphon("MATCH p = (a)-[e]-(b) WHERE a.entity_id = $id RETURN p")
        assert ast.match_clauses[0].path_var == "p"

    def test_where_clause_parsed(self):
        ast = parse_gryphon(HUB_SPOKE_QUERY)
        assert ast.where_clause is not None
        pred = ast.where_clause.predicate
        assert isinstance(pred, Comparison)
        assert pred.field_path.variable == "hub"
        assert isinstance(pred.field_path.steps[0], DotStep)
        assert pred.field_path.steps[0].name == "entity_id"
        assert pred.op == "="
        assert isinstance(pred.value, ParamRef)
        assert pred.value.name == "entity_id"

    def test_and_predicate(self):
        """req-grid-traversal-lang-combinators-1: AND."""
        ast = parse_gryphon('MATCH (n)-[e]-(m) WHERE n.entity_id = $id AND n.name = "web01" RETURN n')
        pred = ast.where_clause.predicate
        assert isinstance(pred, AndPred)

    def test_or_predicate(self):
        """req-grid-traversal-lang-combinators-2: OR."""
        ast = parse_gryphon('MATCH (n)-[e]-(m) WHERE n.entity_id = $id OR n.name = "web01" RETURN n')
        pred = ast.where_clause.predicate
        assert isinstance(pred, OrPred)

    def test_not_predicate(self):
        """req-grid-traversal-lang-combinators-3: NOT."""
        ast = parse_gryphon('MATCH (n)-[e]-(m) WHERE NOT n.name = "excluded" RETURN n')
        pred = ast.where_clause.predicate
        assert isinstance(pred, NotPred)

    def test_bracket_key_access(self):
        """req-grid-traversal-lang-filters-4: keyed JSON access."""
        ast = parse_gryphon('MATCH (n)-[e]-(m) WHERE n.dimensions["tap.graph"] = "web" RETURN n')
        pred = ast.where_clause.predicate
        assert isinstance(pred, Comparison)
        steps = pred.field_path.steps
        assert isinstance(steps[0], DotStep) and steps[0].name == "dimensions"
        assert isinstance(steps[1], KeyStep) and steps[1].key == "tap.graph"

    def test_array_wildcard_access(self):
        """req-grid-traversal-lang-filters-6: array wildcard [*]."""
        ast = parse_gryphon("MATCH (n)-[e]-(m) WHERE n.properties.aliases[*].name = $alias RETURN n")
        pred = ast.where_clause.predicate
        steps = pred.field_path.steps
        assert any(isinstance(s, WildcardStep) for s in steps)

    def test_return_clause_items(self):
        """req-grid-traversal-lang-returns-3: variable returns."""
        ast = parse_gryphon(HUB_SPOKE_QUERY)
        ret = ast.return_clause
        assert ret.items is not None
        assert len(ret.items) == 3
        variables = [item.path.variable for item in ret.items]
        assert "hub" in variables
        assert "e" in variables
        assert "neighbor" in variables

    def test_return_alias(self):
        """req-grid-traversal-lang-returns-5: AS alias."""
        ast = parse_gryphon("MATCH (h)-[e]-(n) WHERE h.entity_id = $id RETURN h.name AS accepted_name")
        ret = ast.return_clause
        assert ret.items is not None
        assert ret.items[0].alias == "accepted_name"

    def test_omitted_return_is_none(self):
        """req-grid-traversal-lang-returns-1: omitted RETURN → items=None → graph envelope."""
        ast = parse_gryphon("MATCH (hub)-[e]-(neighbor) WHERE hub.entity_id = $entity_id")
        assert ast.return_clause.items is None

    def test_required_params_extracted(self):
        ast = parse_gryphon(HUB_SPOKE_QUERY)
        assert ast.required_params() == frozenset({"entity_id"})

    @pytest.mark.spec("req-grid-traversal-exec-scope.sec-3")
    def test_invalid_syntax_raises_parse_error(self):
        """req-grid-traversal-exec-scope.sec-3: unsupported syntax rejected."""
        with pytest.raises(GryphonParseError):
            parse_gryphon("MATCH (")

    def test_empty_string_raises_parse_error(self):
        with pytest.raises(GryphonParseError):
            parse_gryphon("")

    def test_node_only_pattern_parses(self):
        """req-grid-traversal-lang-patterns: node-only MATCH pattern is valid syntax."""
        ast = parse_gryphon("MATCH (c:grid_fixtures__constrained_source) RETURN c.entity_id, c.name")
        mc = ast.match_clauses[0]
        pattern = mc.patterns[0]
        assert len(pattern.nodes) == 1
        assert len(pattern.edges) == 0
        assert pattern.nodes[0].label == "grid_fixtures__constrained_source"

    def test_node_only_no_label_parses(self):
        """Node-only pattern without label is syntactically valid."""
        ast = parse_gryphon("MATCH (n) RETURN n.entity_id")
        pattern = ast.match_clauses[0].patterns[0]
        assert len(pattern.edges) == 0
        assert pattern.nodes[0].label is None


# ---------------------------------------------------------------------------
# TestGryphonExecutor — req-grid-traversal-exec-pipeline
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonExecutor:
    def test_malformed_query_is_a_caller_error_not_a_crash(self):
        """The documented contract of every execute_* entry point is that a
        malformed query raises SearchExecutionError — but GryphonParseError
        escaped the parse call and surfaced as an API 500 (authenticated
        api-fuzz finding, 2026-08-10). Pin the normalization at the chokepoint."""
        from tap_grid.gryphon.executor import execute_gryphon_raw

        with pytest.raises(SearchExecutionError, match="parse error"):
            execute_gryphon_raw("\x13ì", {})

    def test_hub_spoke_returns_hub_and_neighbors(self):
        """Hub-and-spoke traversal returns hub + one-hop neighbors and edges."""
        import uuid

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Edge, Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)

        hub = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Frodo")
        neighbor = Entity.objects.create(entity_type="grid_fixtures__constrained_target", name="The Shire")
        Edge.objects.create(
            entity=Entity.objects.create(entity_type="edge"),
            from_entity=hub,
            to_entity=neighbor,
            edge_type="CONSTRAINED_LINK__grid_fixtures",
        )

        search = Search(
            search_type="gryphon",
            root="node",
            name="test",
            definition={"query": HUB_SPOKE_QUERY},
        )
        result = execute_search(search, inputs={"entity_id": str(hub.pk)})

        node_ids = {n["entity_id"] for n in result["nodes"]}
        assert str(hub.pk) in node_ids
        assert str(neighbor.pk) in node_ids
        assert len(result["edges"]) == 1

    def test_outbound_only_direction(self):
        """Outbound-only pattern excludes inbound-only neighbors."""
        import uuid

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Edge, Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)

        hub = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Frodo")
        outbound_neighbor = Entity.objects.create(entity_type="grid_fixtures__constrained_target", name="Rivendell")
        inbound_neighbor = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Gandalf")
        edge_entity_out = Entity.objects.create(entity_type="edge")
        edge_entity_in = Entity.objects.create(entity_type="edge")
        Edge.objects.create(
            entity=edge_entity_out,
            from_entity=hub,
            to_entity=outbound_neighbor,
            edge_type="VISITED",
        )
        Edge.objects.create(
            entity=edge_entity_in,
            from_entity=inbound_neighbor,
            to_entity=hub,
            edge_type="KNOWS",
        )

        search = Search(
            search_type="gryphon",
            root="node",
            name="test",
            definition={
                "query": "MATCH (hub)-[e]->(neighbor) WHERE hub.entity_id = $entity_id RETURN hub, e, neighbor"
            },
        )
        result = execute_search(search, inputs={"entity_id": str(hub.pk)})
        node_ids = {n["entity_id"] for n in result["nodes"]}
        assert str(outbound_neighbor.pk) in node_ids
        assert str(inbound_neighbor.pk) not in node_ids

    def test_hub_not_found_returns_empty(self):
        """Missing hub entity returns empty nodes/edges with a warning."""
        import uuid

        search = Search(
            search_type="gryphon",
            root="node",
            name="test",
            definition={"query": HUB_SPOKE_QUERY},
        )
        missing_id = str(uuid.uuid4())
        result = execute_search(search, inputs={"entity_id": missing_id})
        assert result["nodes"] == []
        assert result["edges"] == []

    @pytest.mark.spec("req-grid-traversal-exec-scope.sec-4")
    def test_missing_required_input_raises(self):
        """req-grid-traversal-exec-scope.sec-4: inputs validated before execution."""
        search = Search(
            search_type="gryphon",
            root="node",
            name="test",
            definition={"query": HUB_SPOKE_QUERY},
        )
        with pytest.raises(SearchExecutionError, match="entity_id"):
            execute_search(search, inputs={})

    def test_unsupported_multi_hop_raises(self):
        """V1 rejects bounded multi-hop patterns."""
        search = Search(
            search_type="gryphon",
            root="node",
            name="test",
            definition={"query": "MATCH (a)-[e*1..3]-(b) WHERE a.entity_id = $entity_id RETURN a"},
        )
        with pytest.raises(SearchExecutionError, match="[Uu]nsupported"):
            execute_search(search, inputs={"entity_id": "00000000-0000-0000-0000-000000000000"})

    def test_type_scan_returns_projected_rows(self):
        """req-grid-traversal-lang-returns-4: type scan with field projection.

        Projection results are rows, not graph-envelope nodes — they land in
        ``result["rows"]`` (consistent with the advanced executor).
        """
        import uuid

        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)

        for name in ("Frodo", "Sam"):
            entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=name)
            ConstrainedSource.objects.create(entity=entity, name=name, description=f"{name} bio")

        search = Search(
            search_type="gryphon",
            root="node",
            name="test",
            definition={
                "query": "MATCH (c:grid_fixtures__constrained_source) RETURN c.entity_id, c.name, c.data.description"
            },
        )
        result = execute_search(search, inputs={})

        assert "rows" in result
        assert result["nodes"] == []
        assert result["edges"] == []
        assert len(result["rows"]) >= 2
        row = result["rows"][0]
        assert "entity_id" in row
        assert "name" in row
        assert "description" in row

    def test_type_scan_envelope_when_return_omitted(self):
        """req-grid-traversal-lang-returns-1: type scan without RETURN gives graph envelope."""
        import uuid

        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)

        entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Gandalf")
        ConstrainedSource.objects.create(entity=entity, name="Gandalf", description="A wizard.")

        search = Search(
            search_type="gryphon",
            root="node",
            name="test",
            definition={"query": "MATCH (c:grid_fixtures__constrained_source)"},
        )
        result = execute_search(search, inputs={})

        assert "nodes" in result
        node = result["nodes"][0]
        # Graph envelope per spec-grift-envelope: spine at top, data lane below.
        assert "entity_id" in node
        assert "entity_type" in node
        assert "name" in node
        assert "data" in node

    def test_type_scan_no_label_raises(self):
        """Type scan requires a node label to know which entity type to scan."""
        search = Search(
            search_type="gryphon",
            root="node",
            name="test",
            definition={"query": "MATCH (c) RETURN c.entity_id"},
        )
        with pytest.raises(SearchExecutionError, match="[Ll]abel"):
            execute_search(search, inputs={})

    def test_type_scan_unknown_label_raises(self):
        """Type scan with an unregistered entity type raises SearchExecutionError."""
        search = Search(
            search_type="gryphon",
            root="node",
            name="test",
            definition={"query": "MATCH (c:nonexistent_type) RETURN c.entity_id"},
        )
        with pytest.raises(SearchExecutionError, match="[Uu]nknown"):
            execute_search(search, inputs={})


# ---------------------------------------------------------------------------
# TestGryphonEnvelopePaths — req-grid-traversal-lang-envelope-paths
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonEnvelopePaths:
    """Explicit-only envelope-aware paths: `data` and `display` prefixes."""

    def _make_characters(self):
        import uuid

        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)
        out = []
        for name, bio in (("Frodo", "A hobbit."), ("Sam", "Gardener.")):
            entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=name)
            out.append(ConstrainedSource.objects.create(entity=entity, name=name, description=bio))
        return out

    def test_return_data_prefix_resolves_per_model_field(self):
        """req-grid-traversal-lang-envelope-paths-2: data prefix → per-model row."""
        self._make_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="t",
            definition={"query": "MATCH (c:grid_fixtures__constrained_source) RETURN c.entity_id, c.data.description"},
        )
        result = execute_search(search, inputs={})
        bios = {r["description"] for r in result["rows"]}
        assert bios == {"A hobbit.", "Gardener."}

    def test_return_unprefixed_per_model_field_rejected(self):
        """req-grid-traversal-lang-envelope-paths-6: no routing sugar.

        Bare `c.description` is rejected; error message names the explicit form.
        """
        self._make_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="t",
            definition={"query": "MATCH (c:grid_fixtures__constrained_source) RETURN c.entity_id, c.description"},
        )
        # Error message names the explicit form (e.g. `<var>.data.description`) so
        # the caller knows exactly what to write instead.
        with pytest.raises(SearchExecutionError, match=r"data\.description"):
            execute_search(search, inputs={})

    def test_return_display_prefix_rejected_with_extended_layer_hint(self):
        """req-grid-traversal-lang-envelope-paths-3: display rejected in v1; error names the workaround."""
        self._make_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="t",
            definition={
                "query": "MATCH (c:grid_fixtures__constrained_source) RETURN c.entity_id, c.display.tap_viz.shape"
            },
        )
        with pytest.raises(SearchExecutionError, match=r"extended"):
            execute_search(search, inputs={})

    def test_return_spine_field_works_unprefixed(self):
        """req-grid-traversal-lang-envelope-paths-1: spine fields resolve without prefix."""
        self._make_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="t",
            definition={
                "query": "MATCH (c:grid_fixtures__constrained_source) RETURN c.entity_id, c.name, c.entity_type"
            },
        )
        result = execute_search(search, inputs={})
        assert result["rows"]
        assert all("entity_id" in r and "name" in r and "entity_type" in r for r in result["rows"])

    def test_return_walking_into_spine_field_rejected(self):
        """Spine fields are scalars — `n.name.something` errors clearly."""
        self._make_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="t",
            definition={"query": "MATCH (c:grid_fixtures__constrained_source) RETURN c.name.bogus"},
        )
        with pytest.raises(SearchExecutionError, match=r"data"):
            execute_search(search, inputs={})

    def test_return_walking_into_dimensions_spine_field_rejected(self):
        """RETURN projection is deliberately stricter than WHERE (v1 boundary).

        A multi-step walk into the JSON-typed `dimensions` spine field is a valid
        WHERE predicate (`WHERE c.dimensions.region = ...`), but is NOT a v1 RETURN
        projection. The row-materialization unification routes RETURN through the
        shared, more-permissive resolver; this pins that it must not silently widen
        RETURN to accept it (`req-grid-traversal-lang-envelope-paths`).
        """
        self._make_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="t",
            definition={"query": "MATCH (c:grid_fixtures__constrained_source) RETURN c.dimensions.region"},
        )
        with pytest.raises(SearchExecutionError, match=r"walked into"):
            execute_search(search, inputs={})

    def test_return_data_lane_bracket_key_rejected(self):
        """RETURN projection admits dot-steps only in the `data` lane (v1 boundary).

        A bracket-key step (`c.data.tags["team"]`) is accepted by the shared WHERE
        resolver but must be rejected in a v1 RETURN projection — the unification
        must not silently widen it (`req-grid-traversal-lang-envelope-paths`).
        """
        self._make_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="t",
            definition={"query": 'MATCH (c:grid_fixtures__constrained_source) RETURN c.data.tags["team"]'},
        )
        with pytest.raises(SearchExecutionError, match=r"dot-steps"):
            execute_search(search, inputs={})

    def test_return_dotted_path_default_alias_is_last_step(self):
        """When no AS alias is given, the default column name is the last dot-step."""
        self._make_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="t",
            definition={"query": "MATCH (c:grid_fixtures__constrained_source) RETURN c.entity_id, c.data.description"},
        )
        result = execute_search(search, inputs={})
        row = result["rows"][0]
        # `c.data.description` → default key is `bio` (last dot-step), not `data` or `data.description`.
        assert "description" in row


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonTypeScanWhere:
    """Type-scan WHERE filtering — bug fix from samsite landing investigation.

    The type-scan path (`_execute_type_scan`) previously ignored the global
    WHERE clause entirely. Now it applies variable-scoped predicates per
    `_filter_predicate_for_bindings`.
    """

    def _make_characters(self):
        import uuid

        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)
        out = []
        for name, bio in (("Frodo", "A hobbit."), ("Sam", "Gardener."), ("Aragorn", "King.")):
            entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=name)
            out.append(ConstrainedSource.objects.create(entity=entity, name=name, description=bio))
        return out

    def test_where_filter_on_spine_field(self):
        """WHERE on a spine field (n.name) filters the type-scan correctly."""
        self._make_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="t",
            definition={
                "query": 'MATCH (c:grid_fixtures__constrained_source) WHERE c.name = "Frodo" RETURN c.entity_id, c.name'
            },
        )
        result = execute_search(search, inputs={})
        names = {r["name"] for r in result["rows"]}
        assert names == {"Frodo"}

    def test_where_filter_on_data_lane_per_model_field(self):
        """WHERE on n.data.description filters the type-scan via per-model row access."""
        self._make_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="t",
            definition={
                "query": 'MATCH (c:grid_fixtures__constrained_source) WHERE c.data.description = "Gardener." RETURN c.entity_id, c.name'
            },
        )
        result = execute_search(search, inputs={})
        names = {r["name"] for r in result["rows"]}
        assert names == {"Sam"}

    def test_where_with_param_binding(self):
        """WHERE with $param resolves against runtime inputs."""
        self._make_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="t",
            definition={
                "query": "MATCH (c:grid_fixtures__constrained_source) WHERE c.name = $target RETURN c.entity_id, c.name"
            },
        )
        result = execute_search(search, inputs={"target": "Aragorn"})
        names = {r["name"] for r in result["rows"]}
        assert names == {"Aragorn"}

    def test_where_only_applies_to_matching_variable(self):
        """In multi-MATCH, WHERE comparisons only apply to the MATCH that binds the variable.

        Reproduces the samsite-landing-page pattern: an `aws_account`-style
        MATCH using variable `account` is unaffected by a WHERE clause on
        `n.data.tags.Project`, because the WHERE references `n` (which the
        account MATCH does not bind).

        Two type-scan MATCH clauses on different entity types. The
        `realm`-targeted MATCH is unfiltered (the WHERE references `c`,
        not `r`); the `character`-targeted MATCH is filtered. Graph
        envelope return so the dedup key is reliably present.
        """
        import uuid

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)
        self._make_characters()
        # A different entity type that won't be touched by the WHERE.
        realm = Entity.objects.create(entity_type="grid_fixtures__nesting_container", name="Middle-earth")
        from tap_plugin.grid_fixtures.models import NestingContainer  # noqa: PLC0415

        NestingContainer.objects.create(entity=realm, name="Middle-earth")

        search = Search(
            search_type="gryphon",
            root="node",
            name="t",
            definition={
                "query": (
                    "MATCH (r:grid_fixtures__nesting_container) "
                    "MATCH (c:grid_fixtures__constrained_source) "
                    'WHERE c.name = "Frodo"'
                )
            },
        )
        result = execute_search(search, inputs={})
        names = {n["name"] for n in result["nodes"]}
        # WHERE on `c.name = "Frodo"` filters character scan to just Frodo.
        # WHERE doesn't reference `r`, so the realm scan returns
        # Middle-earth unfiltered. Sam and Aragorn are excluded.
        assert "Frodo" in names
        assert "Middle-earth" in names
        assert "Sam" not in names
        assert "Aragorn" not in names


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonDimensionsMultiStep:
    """JSON-typed spine field multi-step access — req-grid-traversal-lang-envelope-paths.

    `dimensions` is the only JSON-typed spine field today. Multi-step access
    (`n.dimensions.<key>`) walks into the JSON via Django nested-key lookup.
    """

    def _make_characters_with_dimensions(self):
        import uuid

        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)
        results = []
        for name, region in (("Frodo", "shire"), ("Sam", "shire"), ("Aragorn", "gondor")):
            entity = Entity.objects.create(
                entity_type="grid_fixtures__constrained_source", name=name, dimensions={"region": region}
            )
            results.append(ConstrainedSource.objects.create(entity=entity, name=name, description=""))
        return results

    def test_dimensions_dot_access_filters(self):
        """WHERE on n.dimensions.<key> filters by spine JSON value."""
        self._make_characters_with_dimensions()
        search = Search(
            search_type="gryphon",
            root="node",
            name="t",
            definition={
                "query": 'MATCH (c:grid_fixtures__constrained_source) WHERE c.dimensions.region = "shire" RETURN c.entity_id, c.name'
            },
        )
        result = execute_search(search, inputs={})
        names = {r["name"] for r in result["rows"]}
        assert names == {"Frodo", "Sam"}

    def test_dimensions_bracket_key_access_filters(self):
        """Bracket-key syntax also works for dimension keys with special chars."""
        # Add a dimension with a dotted key — common in TAP conventions
        # ("tap.graph", "tap.system", etc.).
        self._make_characters_with_dimensions()
        import uuid

        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)
        entity = Entity.objects.create(
            entity_type="grid_fixtures__constrained_source",
            name="Gollum",
            dimensions={"tap.graph": "web"},
        )
        ConstrainedSource.objects.create(entity=entity, name="Gollum", description="")

        search = Search(
            search_type="gryphon",
            root="node",
            name="t",
            definition={
                "query": (
                    'MATCH (c:grid_fixtures__constrained_source) WHERE c.dimensions["tap.graph"] = "web" '
                    "RETURN c.entity_id, c.name"
                )
            },
        )
        result = execute_search(search, inputs={})
        names = {r["name"] for r in result["rows"]}
        assert names == {"Gollum"}


# ---------------------------------------------------------------------------
# TestSearchModelGryphon — Search.validate() gryphon branch
# ---------------------------------------------------------------------------


class TestSearchModelGryphon:
    def test_valid_gryphon_search_validates_ok(self):
        s = Search(
            name="Test",
            search_type="gryphon",
            root="node",
            definition={"query": HUB_SPOKE_QUERY},
        )
        # Should not raise.
        s.validate()

    def test_string_query_validates_ok(self):
        s = Search(
            name="Test",
            search_type="gryphon",
            root="node",
            definition={"query": HUB_SPOKE_QUERY_STR},
        )
        s.validate()

    def test_missing_query_key_raises(self):
        s = Search(
            name="Test",
            search_type="gryphon",
            root="node",
            definition={},
        )
        with pytest.raises(ValidationError) as exc_info:
            s.validate()
        assert "query" in str(exc_info.value)

    def test_invalid_query_syntax_raises(self):
        s = Search(
            name="Test",
            search_type="gryphon",
            root="node",
            definition={"query": "MATCH ("},
        )
        with pytest.raises(ValidationError) as exc_info:
            s.validate()
        assert "parse" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# TestSearchServiceGryphon — execute_search dispatch
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestSearchServiceGryphon:
    @pytest.mark.spec("req-grid-traversal-exec-pipeline-4")
    def test_gryphon_dispatch_returns_canonical_envelope(self):
        """req-grid-traversal-exec-pipeline-4: results normalized into canonical envelope."""
        import uuid

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)

        hub = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Bilbo")

        search = Search(
            search_type="gryphon",
            root="node",
            name="test",
            definition={"query": HUB_SPOKE_QUERY},
        )
        result = execute_search(search, inputs={"entity_id": str(hub.pk)})

        assert "nodes" in result
        assert "edges" in result
        assert "info" in result
        assert "warnings" in result
        assert result["info"]["search_type"] == "gryphon"

    def test_unknown_search_type_raises(self):
        search = Search(
            name="Bad",
            search_type="unknown",
            root="node",
            definition={},
        )
        with pytest.raises(SearchExecutionError, match="Unknown search_type"):
            execute_search(search, inputs={})


# ---------------------------------------------------------------------------
# TestGryphonEdgeTypeScan — edge-type scan execution mode
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonEdgeTypeScan:
    def _setup_realm_locations(self):
        """Create realm→location NESTING_LINK__grid_fixtures edges for testing."""
        import uuid

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Edge, Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)

        realm = Entity.objects.create(entity_type="grid_fixtures__nesting_container", name="Middle-earth")
        mordor = Entity.objects.create(entity_type="grid_fixtures__constrained_target", name="Mordor")
        gondor = Entity.objects.create(entity_type="grid_fixtures__constrained_target", name="Gondor")
        frodo = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Frodo")

        Edge.objects.create(
            entity=Entity.objects.create(entity_type="edge"),
            from_entity=realm,
            to_entity=mordor,
            edge_type="NESTING_LINK__grid_fixtures",
        )
        Edge.objects.create(
            entity=Entity.objects.create(entity_type="edge"),
            from_entity=realm,
            to_entity=gondor,
            edge_type="NESTING_LINK__grid_fixtures",
        )
        # A non-matching edge type to verify filtering.
        Edge.objects.create(
            entity=Entity.objects.create(entity_type="edge"),
            from_entity=frodo,
            to_entity=mordor,
            edge_type="CONSTRAINED_LINK__grid_fixtures",
        )
        return realm, mordor, gondor, frodo

    def test_edge_type_scan_returns_matching_edges(self):
        """Edge-type scan returns all edges of the given type with correct endpoints."""
        realm, mordor, gondor, _frodo = self._setup_realm_locations()

        search = Search(
            search_type="gryphon",
            root="node",
            name="test",
            definition={
                "query": "MATCH (r:grid_fixtures__nesting_container)-[e:NESTING_LINK__grid_fixtures]->(l:grid_fixtures__constrained_target)"
            },
        )
        result = execute_search(search, inputs={})

        node_ids = {n["entity_id"] for n in result["nodes"]}
        assert str(realm.pk) in node_ids
        assert str(mordor.pk) in node_ids
        assert str(gondor.pk) in node_ids
        assert len(result["edges"]) == 2

    def test_edge_type_scan_filters_by_endpoint_type(self):
        """Only edges with matching endpoint types are returned."""
        _realm, _mordor, _gondor, frodo = self._setup_realm_locations()

        search = Search(
            search_type="gryphon",
            root="node",
            name="test",
            definition={
                "query": "MATCH (r:grid_fixtures__nesting_container)-[e:NESTING_LINK__grid_fixtures]->(l:grid_fixtures__constrained_target)"
            },
        )
        result = execute_search(search, inputs={})

        node_ids = {n["entity_id"] for n in result["nodes"]}
        # Frodo is not a realm or location endpoint of NESTING_LINK__grid_fixtures.
        assert str(frodo.pk) not in node_ids

    def test_edge_type_scan_inbound_direction(self):
        """Inbound edge-type scan reverses endpoint label mapping."""
        realm, mordor, gondor, _frodo = self._setup_realm_locations()

        # Inbound: left_node matches to_entity, right_node matches from_entity.
        search = Search(
            search_type="gryphon",
            root="node",
            name="test",
            definition={
                "query": "MATCH (l:grid_fixtures__constrained_target)<-[e:NESTING_LINK__grid_fixtures]-(r:grid_fixtures__nesting_container)"
            },
        )
        result = execute_search(search, inputs={})

        node_ids = {n["entity_id"] for n in result["nodes"]}
        assert str(realm.pk) in node_ids
        assert str(mordor.pk) in node_ids
        assert str(gondor.pk) in node_ids
        assert len(result["edges"]) == 2


# ---------------------------------------------------------------------------
# TestGryphonUnion — multiple MATCH clauses with UNION merge
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonUnion:
    def _setup_graph(self):
        """Create a small graph with realm, locations, characters, and artifacts."""
        import uuid

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Edge, Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)

        realm = Entity.objects.create(entity_type="grid_fixtures__nesting_container", name="Middle-earth")
        mordor = Entity.objects.create(entity_type="grid_fixtures__constrained_target", name="Mordor")
        frodo = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Frodo")
        ring = Entity.objects.create(entity_type="grid_fixtures__dual_endpoint", name="The One Ring")

        Edge.objects.create(
            entity=Entity.objects.create(entity_type="edge"),
            from_entity=realm,
            to_entity=mordor,
            edge_type="NESTING_LINK__grid_fixtures",
        )
        Edge.objects.create(
            entity=Entity.objects.create(entity_type="edge"),
            from_entity=frodo,
            to_entity=mordor,
            edge_type="CONSTRAINED_LINK__grid_fixtures",
        )
        Edge.objects.create(
            entity=Entity.objects.create(entity_type="edge"),
            from_entity=frodo,
            to_entity=ring,
            edge_type="SCHEMA_LINK__grid_fixtures",
        )
        return realm, mordor, frodo, ring

    def test_two_match_clauses_merged(self):
        """Two MATCH clauses return merged, deduplicated results."""
        realm, mordor, frodo, ring = self._setup_graph()

        query = [
            "MATCH (r:grid_fixtures__nesting_container)-[e1:NESTING_LINK__grid_fixtures]->(l:grid_fixtures__constrained_target)",
            "MATCH (c:grid_fixtures__constrained_source)-[e2:SCHEMA_LINK__grid_fixtures]->(a:grid_fixtures__dual_endpoint)",
        ]
        search = Search(
            search_type="gryphon",
            root="node",
            name="test",
            definition={"query": query},
        )
        result = execute_search(search, inputs={})

        node_ids = {n["entity_id"] for n in result["nodes"]}
        assert str(realm.pk) in node_ids
        assert str(mordor.pk) in node_ids
        assert str(frodo.pk) in node_ids
        assert str(ring.pk) in node_ids
        assert len(result["edges"]) == 2

    def test_shared_nodes_deduplicated(self):
        """Nodes appearing in multiple clause results are not duplicated."""
        realm, mordor, frodo, ring = self._setup_graph()

        # Both clauses will return Mordor (as location in NESTING_LINK__grid_fixtures and as target in CONSTRAINED_LINK__grid_fixtures).
        query = [
            "MATCH (r:grid_fixtures__nesting_container)-[e1:NESTING_LINK__grid_fixtures]->(l:grid_fixtures__constrained_target)",
            "MATCH (c:grid_fixtures__constrained_source)-[e2:CONSTRAINED_LINK__grid_fixtures]->(l2:grid_fixtures__constrained_target)",
        ]
        search = Search(
            search_type="gryphon",
            root="node",
            name="test",
            definition={"query": query},
        )
        result = execute_search(search, inputs={})

        node_ids = [n["entity_id"] for n in result["nodes"]]
        # Mordor should appear exactly once despite being in both results.
        assert node_ids.count(str(mordor.pk)) == 1

    def test_four_clause_saga_shape(self):
        """Full four-clause query shape matching the saga demo pattern."""
        realm, mordor, frodo, ring = self._setup_graph()

        query = [
            "MATCH (r:grid_fixtures__nesting_container)-[e1:NESTING_LINK__grid_fixtures]->(l:grid_fixtures__constrained_target)",
            "MATCH (l2:grid_fixtures__constrained_target)-[e2:NESTING_LINK__grid_fixtures]->(l3:grid_fixtures__constrained_target)",
            "MATCH (c:grid_fixtures__constrained_source)-[e3:CONSTRAINED_LINK__grid_fixtures]->(loc:grid_fixtures__constrained_target)",
            "MATCH (c2:grid_fixtures__constrained_source)-[e4:SCHEMA_LINK__grid_fixtures]->(a:grid_fixtures__dual_endpoint)",
        ]
        search = Search(
            search_type="gryphon",
            root="node",
            name="test",
            definition={"query": query},
        )
        result = execute_search(search, inputs={})

        node_ids = {n["entity_id"] for n in result["nodes"]}
        # All four entity types should be represented.
        assert str(realm.pk) in node_ids
        assert str(mordor.pk) in node_ids
        assert str(frodo.pk) in node_ids
        assert str(ring.pk) in node_ids


# ---------------------------------------------------------------------------
# TestGryphonV2Extensions — multi-hop-aggregation spec coverage
#   - NOT EXISTS grammar and correlation
#   - COUNT aggregation + implicit GROUP BY
#   - Edge pattern without a variable: -[:TYPE]-> (regression)
#   - rows envelope field
# ---------------------------------------------------------------------------


class TestGryphonV2ParserExtensions:
    """Parser coverage for the multi-hop-aggregation extension."""

    def test_edge_pattern_without_variable_parses_as_edge_type(self):
        """-[:TYPE]-> (no variable) must bind edge_type, not variable."""
        ast = parse_gryphon("MATCH (a)-[:NESTING_LINK__grid_fixtures]->(b)")
        edge = ast.match_clauses[0].patterns[0].edges[0]
        assert edge.variable is None
        assert edge.edge_type == "NESTING_LINK__grid_fixtures"
        assert edge.direction == "out"

    def test_count_aggregate_in_return(self):
        """COUNT(var) AS alias produces an AggregateReturnItem."""
        from tap_grid.gryphon.ast_nodes import AggregateReturnItem

        ast = parse_gryphon("MATCH (a)-[:R]->(b) RETURN a.entity_id AS id, COUNT(b) AS n")
        items = ast.return_clause.items
        assert items is not None and len(items) == 2
        assert any(isinstance(i, AggregateReturnItem) for i in items)
        agg = next(i for i in items if isinstance(i, AggregateReturnItem))
        assert agg.aggregate.function == "count"
        assert agg.aggregate.argument.variable == "b"
        assert agg.alias == "n"

    def test_not_exists_clause_parses(self):
        """NOT EXISTS { MATCH ... WHERE ... } is a recognized top-level clause."""
        q = (
            "MATCH (a)-[:R1]->(b) "
            'NOT EXISTS { MATCH (c)-[:R2]->(b) WHERE c.entity_type = "grid_fixtures__constrained_source" } '
            "RETURN a.entity_id, COUNT(b) AS n"
        )
        ast = parse_gryphon(q)
        assert len(ast.not_exists_clauses) == 1
        nec = ast.not_exists_clauses[0]
        assert len(nec.match_clause.patterns) == 1
        assert nec.where_clause is not None


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonV2Executor:
    """Executor coverage for COUNT + GROUP BY, NOT EXISTS, and the rows envelope."""

    def _setup_wielders(self):
        """Three characters wielding artifacts (some multi-wielders), for GROUP BY tests."""
        import uuid

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Edge, Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)

        frodo = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Frodo")
        sam = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Sam")
        aragorn = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Aragorn")

        ring = Entity.objects.create(entity_type="grid_fixtures__dual_endpoint", name="One Ring")
        sting = Entity.objects.create(entity_type="grid_fixtures__dual_endpoint", name="Sting")
        anduril = Entity.objects.create(entity_type="grid_fixtures__dual_endpoint", name="Anduril")

        for src, tgt in [(frodo, ring), (frodo, sting), (sam, sting), (aragorn, anduril)]:
            Edge.objects.create(
                entity=Entity.objects.create(entity_type="edge"),
                from_entity=src,
                to_entity=tgt,
                edge_type="SCHEMA_LINK__grid_fixtures",
            )
        return frodo, sam, aragorn, ring, sting, anduril

    def test_count_with_group_by_produces_rows(self):
        """COUNT(artifact) grouped by wielder produces one row per wielder with correct count."""
        frodo, sam, aragorn, *_ = self._setup_wielders()

        search = Search(
            search_type="gryphon",
            root="node",
            name="wielder-counts",
            definition={
                "query": (
                    "MATCH (c:grid_fixtures__constrained_source)-[:SCHEMA_LINK__grid_fixtures]->(a:grid_fixtures__dual_endpoint) "
                    "RETURN c.entity_id AS wielder, COUNT(a) AS count"
                )
            },
        )
        result = execute_search(search, inputs={})
        assert "rows" in result
        rows = {r["wielder"]: r["count"] for r in result["rows"]}
        assert rows[str(frodo.pk)] == 2  # ring + sting
        assert rows[str(sam.pk)] == 1  # sting
        assert rows[str(aragorn.pk)] == 1  # anduril

    def test_not_exists_excludes_correlated_rows(self):
        """NOT EXISTS filters out outer rows whose shared var matches an inner pattern."""
        frodo, sam, aragorn, ring, sting, anduril = self._setup_wielders()

        # Find characters wielding artifacts that Sam does NOT also wield.
        # Sam wields Sting. So expected: Frodo (wields ring AND sting; sting excluded → only ring)
        # and Aragorn (wields anduril, Sam doesn't). Sam himself is not returned because of
        # the anti-join — but actually the anti-join filters on shared artifact not on character.
        # Redo: the query asks "for each outer (c, a) where c wields a, exclude if Sam also
        # wields a." So Frodo-Ring stays (Sam doesn't wield ring), Frodo-Sting excluded,
        # Sam-Sting excluded, Aragorn-Anduril stays.
        # Grouped by c: Frodo=1 (ring), Aragorn=1 (anduril). Sam has no surviving artifacts.
        search = Search(
            search_type="gryphon",
            root="node",
            name="not-wielded-by-sam",
            definition={
                "query": (
                    "MATCH (c:grid_fixtures__constrained_source)-[:SCHEMA_LINK__grid_fixtures]->(a:grid_fixtures__dual_endpoint) "
                    "NOT EXISTS { "
                    "  MATCH (sam:grid_fixtures__constrained_source)-[:SCHEMA_LINK__grid_fixtures]->(a) "
                    '  WHERE sam.name = "Sam" '
                    "} "
                    "RETURN c.entity_id AS wielder, COUNT(a) AS count"
                )
            },
        )
        result = execute_search(search, inputs={})
        rows = {r["wielder"]: r["count"] for r in result["rows"]}
        assert rows.get(str(frodo.pk)) == 1
        assert rows.get(str(aragorn.pk)) == 1
        # Sam is excluded entirely — his only wield (Sting) was anti-joined out.
        assert str(sam.pk) not in rows

    def test_envelope_contains_rows_key(self):
        """Aggregating queries surface the `rows` key in the canonical envelope."""
        self._setup_wielders()

        search = Search(
            search_type="gryphon",
            root="node",
            name="aggregate",
            definition={
                "query": (
                    "MATCH (c:grid_fixtures__constrained_source)-[:SCHEMA_LINK__grid_fixtures]->(a:grid_fixtures__dual_endpoint) "
                    "RETURN c.entity_id AS wielder, COUNT(a) AS count"
                )
            },
        )
        result = execute_search(search, inputs={})
        assert "rows" in result
        assert isinstance(result["rows"], list)
        assert all("wielder" in r and "count" in r for r in result["rows"])

    # ------------------------------------------------------------------
    # Multi-hop executor coverage — req-grid-gryphon-multihop-{1,2,3}
    # ------------------------------------------------------------------

    def _setup_three_layer_chain(self):
        """Characters own realms which contain locations — a 3-layer chain."""
        import uuid

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Edge, Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)

        frodo = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Frodo")
        aragorn = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Aragorn")

        shire = Entity.objects.create(entity_type="grid_fixtures__nesting_container", name="Shire")
        gondor = Entity.objects.create(entity_type="grid_fixtures__nesting_container", name="Gondor")
        arnor = Entity.objects.create(entity_type="grid_fixtures__nesting_container", name="Arnor")

        hobbiton = Entity.objects.create(entity_type="grid_fixtures__constrained_target", name="Hobbiton")
        buckland = Entity.objects.create(entity_type="grid_fixtures__constrained_target", name="Buckland")
        minas_tirith = Entity.objects.create(entity_type="grid_fixtures__constrained_target", name="Minas Tirith")
        annuminas = Entity.objects.create(entity_type="grid_fixtures__constrained_target", name="Annuminas")

        # ConstrainedSource OWNS realm.
        for src, tgt in [(frodo, shire), (aragorn, gondor), (aragorn, arnor)]:
            Edge.objects.create(
                entity=Entity.objects.create(entity_type="edge"),
                from_entity=src,
                to_entity=tgt,
                edge_type="OWNS",
            )
        # NestingContainer NESTING_LINK__grid_fixtures location.
        for src, tgt in [
            (shire, hobbiton),
            (shire, buckland),
            (gondor, minas_tirith),
            (arnor, annuminas),
        ]:
            Edge.objects.create(
                entity=Entity.objects.create(entity_type="edge"),
                from_entity=src,
                to_entity=tgt,
                edge_type="NESTING_LINK__grid_fixtures",
            )
        return {
            "frodo": frodo,
            "aragorn": aragorn,
            "shire": shire,
            "gondor": gondor,
            "arnor": arnor,
            "hobbiton": hobbiton,
            "buckland": buckland,
            "minas_tirith": minas_tirith,
            "annuminas": annuminas,
        }

    def test_two_hop_chain_counts_leaf_per_root(self):
        """req-grid-gryphon-multihop-1: 2-hop chain with COUNT groups correctly."""
        e = self._setup_three_layer_chain()

        # For each character, count locations reachable via owned realms.
        search = Search(
            search_type="gryphon",
            root="node",
            name="two-hop",
            definition={
                "query": (
                    "MATCH (c:grid_fixtures__constrained_source)-[:OWNS]->(r:grid_fixtures__nesting_container)-[:NESTING_LINK__grid_fixtures]->(l:grid_fixtures__constrained_target) "
                    "RETURN c.entity_id AS character, COUNT(l) AS locations"
                )
            },
        )
        result = execute_search(search, inputs={})
        rows = {r["character"]: r["locations"] for r in result["rows"]}
        # Frodo owns Shire (2 locations: Hobbiton, Buckland).
        # Aragorn owns Gondor (1) + Arnor (1) = 2 locations total.
        assert rows[str(e["frodo"].pk)] == 2
        assert rows[str(e["aragorn"].pk)] == 2

    def test_two_hop_chain_with_no_anchor_warning(self):
        """req-grid-gryphon-multihop: no WHERE anchor on a multi-hop emits a warning."""
        self._setup_three_layer_chain()

        search = Search(
            search_type="gryphon",
            root="node",
            name="no-anchor",
            definition={
                "query": (
                    "MATCH (c:grid_fixtures__constrained_source)-[:OWNS]->(r:grid_fixtures__nesting_container)-[:NESTING_LINK__grid_fixtures]->(l:grid_fixtures__constrained_target) "
                    "RETURN c.entity_id AS id, COUNT(l) AS n"
                )
            },
        )
        result = execute_search(search, inputs={})
        # Warning attached by the advanced executor (service layer promotes via envelope).
        assert "multi_hop_no_anchor" in result.get("warnings", {})

    def test_two_hop_intermediate_label_filters(self):
        """req-grid-gryphon-multihop-3: intermediate label acts as a type filter."""
        e = self._setup_three_layer_chain()

        # Same chain but label the intermediate — results should be identical because
        # every realm-typed entity is in fact a realm. Exercises the label pass-through.
        search = Search(
            search_type="gryphon",
            root="node",
            name="labeled-middle",
            definition={
                "query": (
                    "MATCH (c:grid_fixtures__constrained_source)-[:OWNS]->(r:grid_fixtures__nesting_container)-[:NESTING_LINK__grid_fixtures]->(l:grid_fixtures__constrained_target) "
                    'WHERE c.name = "Frodo" '
                    "RETURN c.entity_id AS character, COUNT(l) AS locations"
                )
            },
        )
        result = execute_search(search, inputs={})
        rows = {r["character"]: r["locations"] for r in result["rows"]}
        assert rows[str(e["frodo"].pk)] == 2
        assert str(e["aragorn"].pk) not in rows

    def test_two_hop_with_mixed_directions(self):
        """req-grid-gryphon-multihop-2: each hop's direction is honored independently.

        Pattern: (l:grid_fixtures__constrained_target)<-[:NESTING_LINK__grid_fixtures]-(r:grid_fixtures__nesting_container)<-[:OWNS]-(c:grid_fixtures__constrained_source)
        Reads the same edges backwards — locations → realms → owning characters.
        """
        e = self._setup_three_layer_chain()

        search = Search(
            search_type="gryphon",
            root="node",
            name="mixed-dir",
            definition={
                "query": (
                    "MATCH (l:grid_fixtures__constrained_target)<-[:NESTING_LINK__grid_fixtures]-(r:grid_fixtures__nesting_container)<-[:OWNS]-(c:grid_fixtures__constrained_source) "
                    "RETURN c.entity_id AS character, COUNT(l) AS locations"
                )
            },
        )
        result = execute_search(search, inputs={})
        rows = {r["character"]: r["locations"] for r in result["rows"]}
        assert rows[str(e["frodo"].pk)] == 2
        assert rows[str(e["aragorn"].pk)] == 2

    def test_two_hop_outer_with_not_exists_correlation(self):
        """req-grid-gryphon-not-exists: NOT EXISTS correlated on a variable from a 2-hop outer."""
        import uuid

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Edge, Entity

        e = self._setup_three_layer_chain()

        # Flag one location as "restricted" via an edge from a separate guard entity.
        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)
        guard = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Guard")
        Edge.objects.create(
            entity=Entity.objects.create(entity_type="edge"),
            from_entity=guard,
            to_entity=e["minas_tirith"],
            edge_type="RESTRICTS",
        )

        # Count per character the locations they reach via a realm — excluding any
        # location restricted by some guard character.
        search = Search(
            search_type="gryphon",
            root="node",
            name="two-hop-not-exists",
            definition={
                "query": (
                    "MATCH (c:grid_fixtures__constrained_source)-[:OWNS]->(r:grid_fixtures__nesting_container)-[:NESTING_LINK__grid_fixtures]->(l:grid_fixtures__constrained_target) "
                    "NOT EXISTS { MATCH (g:grid_fixtures__constrained_source)-[:RESTRICTS]->(l) } "
                    "RETURN c.entity_id AS character, COUNT(l) AS locations"
                )
            },
        )
        result = execute_search(search, inputs={})
        rows = {r["character"]: r["locations"] for r in result["rows"]}
        # Frodo: 2 (Shire contains Hobbiton, Buckland) — neither restricted.
        assert rows[str(e["frodo"].pk)] == 2
        # Aragorn: would be 2 (Minas Tirith, Annuminas) but Minas Tirith is restricted → 1.
        assert rows[str(e["aragorn"].pk)] == 1

    def test_multi_hop_inner_not_exists(self):
        """req-grid-gryphon-not-exists: NOT EXISTS inner pattern itself is multi-hop."""
        import uuid

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Edge, Entity

        e = self._setup_three_layer_chain()

        # Set up a 2-hop restriction chain: one guard → restriction → minas tirith.
        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)
        high_guard = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="HighGuard")
        restriction = Entity.objects.create(entity_type="grid_fixtures__nesting_container", name="Restriction Seal")
        Edge.objects.create(
            entity=Entity.objects.create(entity_type="edge"),
            from_entity=high_guard,
            to_entity=restriction,
            edge_type="ISSUES",
        )
        Edge.objects.create(
            entity=Entity.objects.create(entity_type="edge"),
            from_entity=restriction,
            to_entity=e["minas_tirith"],
            edge_type="SEALS",
        )

        # Outer single-hop: character owns realm. Inner NOT EXISTS is a 2-hop chain.
        # Want: count characters whose owned realm contains NO location that is
        # sealed via a 2-hop restriction chain.
        search = Search(
            search_type="gryphon",
            root="node",
            name="multi-hop-inner-not-exists",
            definition={
                "query": (
                    "MATCH (c:grid_fixtures__constrained_source)-[:OWNS]->(r:grid_fixtures__nesting_container)-[:NESTING_LINK__grid_fixtures]->(l:grid_fixtures__constrained_target) "
                    "NOT EXISTS { "
                    "  MATCH (g:grid_fixtures__constrained_source)-[:ISSUES]->(sr:grid_fixtures__nesting_container)-[:SEALS]->(l) "
                    "} "
                    "RETURN c.entity_id AS character, COUNT(l) AS locations"
                )
            },
        )
        result = execute_search(search, inputs={})
        rows = {r["character"]: r["locations"] for r in result["rows"]}
        # Frodo: 2 locations, none sealed → 2
        assert rows[str(e["frodo"].pk)] == 2
        # Aragorn: 2 locations, Minas Tirith sealed → 1
        assert rows[str(e["aragorn"].pk)] == 1

    def test_variable_length_edge_rejected(self):
        """req-grid-gryphon-multihop-4: variable-length edges parse but executor rejects."""
        self._setup_three_layer_chain()

        search = Search(
            search_type="gryphon",
            root="node",
            name="var-length",
            definition={
                "query": (
                    "MATCH (c:grid_fixtures__constrained_source)-[:OWNS*1..3]->(r:grid_fixtures__nesting_container) "
                    "RETURN c.entity_id AS id, COUNT(r) AS n"
                )
            },
        )
        with pytest.raises(SearchExecutionError, match="[Vv]ariable-length"):
            execute_search(search, inputs={})

    def test_two_hop_no_return_graph_envelope(self):
        """req-grid-gryphon-multihop-envelope-1: omitted RETURN returns all nodes and edges."""
        e = self._setup_three_layer_chain()

        search = Search(
            search_type="gryphon",
            root="node",
            name="envelope-all",
            definition={
                "query": (
                    "MATCH (c:grid_fixtures__constrained_source)-[e1:OWNS]->(r:grid_fixtures__nesting_container)-[e2:NESTING_LINK__grid_fixtures]->(l:grid_fixtures__constrained_target)"
                )
            },
        )
        result = execute_search(search, inputs={})

        node_ids = {n["entity_id"] for n in result["nodes"]}
        # All 9 entities in the chain should be present.
        for name in (
            "frodo",
            "aragorn",
            "shire",
            "gondor",
            "arnor",
            "hobbiton",
            "buckland",
            "minas_tirith",
            "annuminas",
        ):
            assert str(e[name].pk) in node_ids, f"{name} missing from nodes"

        # Edges: 3 OWNS + 4 NESTING_LINK__grid_fixtures = 7
        assert len(result["edges"]) == 7
        edge_types = {edg["data"]["edge_type"] for edg in result["edges"]}
        assert edge_types == {"OWNS", "NESTING_LINK__grid_fixtures"}

        # rows should be empty for graph envelope
        assert result.get("rows", []) == []

    def test_two_hop_bare_variable_return_graph_envelope(self):
        """req-grid-gryphon-multihop-envelope-2: RETURN with bare variables returns named entities."""
        e = self._setup_three_layer_chain()

        # Only request the character and location — skip the intermediate realm.
        search = Search(
            search_type="gryphon",
            root="node",
            name="envelope-selected",
            definition={
                "query": (
                    "MATCH (c:grid_fixtures__constrained_source)-[e1:OWNS]->(r:grid_fixtures__nesting_container)-[e2:NESTING_LINK__grid_fixtures]->(l:grid_fixtures__constrained_target) "
                    "RETURN c, l"
                )
            },
        )
        result = execute_search(search, inputs={})

        node_ids = {n["entity_id"] for n in result["nodes"]}
        # Characters and locations should be present.
        assert str(e["frodo"].pk) in node_ids
        assert str(e["aragorn"].pk) in node_ids
        assert str(e["hobbiton"].pk) in node_ids
        # Realms should NOT be in nodes (not requested).
        assert str(e["shire"].pk) not in node_ids

        # Edges should still be returned (connecting edges included automatically).
        assert len(result["edges"]) == 7

    def test_two_hop_graph_envelope_with_where_anchor(self):
        """req-grid-gryphon-multihop-envelope: WHERE anchor scopes the subgraph."""
        e = self._setup_three_layer_chain()

        search = Search(
            search_type="gryphon",
            root="node",
            name="envelope-anchored",
            definition={
                "query": (
                    "MATCH (c:grid_fixtures__constrained_source)-[e1:OWNS]->(r:grid_fixtures__nesting_container)-[e2:NESTING_LINK__grid_fixtures]->(l:grid_fixtures__constrained_target) "
                    'WHERE c.name = "Frodo"'
                )
            },
        )
        result = execute_search(search, inputs={})

        node_ids = {n["entity_id"] for n in result["nodes"]}
        # Only Frodo's chain: Frodo, Shire, Hobbiton, Buckland
        assert str(e["frodo"].pk) in node_ids
        assert str(e["shire"].pk) in node_ids
        assert str(e["hobbiton"].pk) in node_ids
        assert str(e["buckland"].pk) in node_ids
        # Aragorn's chain should not appear.
        assert str(e["aragorn"].pk) not in node_ids
        assert str(e["gondor"].pk) not in node_ids

    def test_two_hop_graph_envelope_deduplication(self):
        """Nodes appearing at multiple positions in the chain are deduplicated."""
        self._setup_three_layer_chain()

        search = Search(
            search_type="gryphon",
            root="node",
            name="envelope-dedup",
            definition={
                "query": (
                    "MATCH (c:grid_fixtures__constrained_source)-[e1:OWNS]->(r:grid_fixtures__nesting_container)-[e2:NESTING_LINK__grid_fixtures]->(l:grid_fixtures__constrained_target)"
                )
            },
        )
        result = execute_search(search, inputs={})

        entity_ids = [n["entity_id"] for n in result["nodes"]]
        # No duplicates.
        assert len(entity_ids) == len(set(entity_ids))


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonInlineEdgePropertyFilter:
    """Regression coverage for req-grid-traversal-lang-filters-1.

    Inline edge property maps `-[:T {key: "value"}]->` must narrow the queryset
    by JSON-key equality on Edge.properties. Prior to the fix the parser
    accepted the map but the executor silently ignored it; queries with
    different filter values produced identical result sets.
    """

    def _setup_findings_with_relationship_types(self):
        """Two findings on one host, each related to the same indicator with a
        different `relationship_type` property value."""
        import uuid

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Edge, Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)

        host = Entity.objects.create(entity_type="host", name="web-1")
        f_violation = Entity.objects.create(entity_type="finding", name="violation-finding")
        f_passing = Entity.objects.create(entity_type="finding", name="passing-finding")
        indicator = Entity.objects.create(entity_type="indicator", name="ksi-test")

        # host HAS_FINDING f_violation; host HAS_FINDING f_passing
        for f in (f_violation, f_passing):
            Edge.objects.create(
                entity=Entity.objects.create(entity_type="edge"),
                from_entity=host,
                to_entity=f,
                edge_type="HAS_FINDING",
            )

        # f_violation -[:RELATED {relationship_type: "violation"}]-> indicator
        Edge.objects.create(
            entity=Entity.objects.create(entity_type="edge"),
            from_entity=f_violation,
            to_entity=indicator,
            edge_type="RELATED",
            properties={"relationship_type": "violation"},
        )
        # f_passing -[:RELATED {relationship_type: "passing"}]-> indicator
        Edge.objects.create(
            entity=Entity.objects.create(entity_type="edge"),
            from_entity=f_passing,
            to_entity=indicator,
            edge_type="RELATED",
            properties={"relationship_type": "passing"},
        )

        return host, f_violation, f_passing, indicator

    def test_inline_edge_property_filter_narrows_results(self):
        """Two queries differing only in the inline filter value must return
        different result sets. Pre-fix, both queries returned identical results.
        """
        host, f_violation, f_passing, indicator = self._setup_findings_with_relationship_types()

        violation_search = Search(
            search_type="gryphon",
            root="node",
            name="count-violations",
            definition={
                "query": (
                    "MATCH (h)-[:HAS_FINDING]->(f:finding)"
                    '-[:RELATED {relationship_type: "violation"}]->(i:indicator) '
                    "RETURN h.entity_id AS host, COUNT(f) AS count"
                )
            },
        )
        passing_search = Search(
            search_type="gryphon",
            root="node",
            name="count-passing",
            definition={
                "query": (
                    "MATCH (h)-[:HAS_FINDING]->(f:finding)"
                    '-[:RELATED {relationship_type: "passing"}]->(i:indicator) '
                    "RETURN h.entity_id AS host, COUNT(f) AS count"
                )
            },
        )

        v_rows = execute_search(violation_search, inputs={}).get("rows", [])
        p_rows = execute_search(passing_search, inputs={}).get("rows", [])

        v_counts = {r["host"]: r["count"] for r in v_rows}
        p_counts = {r["host"]: r["count"] for r in p_rows}

        assert v_counts == {str(host.pk): 1}, "violation filter should match exactly one finding"
        assert p_counts == {str(host.pk): 1}, "passing filter should match exactly one finding"

    def test_inline_edge_property_filter_no_match_returns_empty(self):
        """A filter value that no edge carries returns zero rows."""
        host, *_ = self._setup_findings_with_relationship_types()

        search = Search(
            search_type="gryphon",
            root="node",
            name="no-match",
            definition={
                "query": (
                    "MATCH (h)-[:HAS_FINDING]->(f:finding)"
                    '-[:RELATED {relationship_type: "informational"}]->(i:indicator) '
                    "RETURN h.entity_id AS host, COUNT(f) AS count"
                )
            },
        )
        result = execute_search(search, inputs={})
        assert result.get("rows", []) == []


# ---------------------------------------------------------------------------
# TestGryphonOrderByLimitParser — req-grid-gryphon-order-by / req-grid-gryphon-limit
# ---------------------------------------------------------------------------


class TestGryphonOrderByLimitParser:
    """Parser coverage for the ORDER BY and LIMIT clauses."""

    def test_order_by_parses_ascending_default(self):
        """req-grid-gryphon-order-by-1/-3: a bare ORDER BY term is ascending."""
        ast = parse_gryphon("MATCH (n:grid_fixtures__node) RETURN n.name AS label ORDER BY label")
        assert isinstance(ast.order_by, OrderByClause)
        assert len(ast.order_by.items) == 1
        item = ast.order_by.items[0]
        # Bare-name term parses as a FieldPath with the name as variable and no
        # steps (the back-compatible projection-mode surface). `.key` reproduces
        # the original string-keyed behavior.
        assert item.path.variable == "label"
        assert item.path.steps == ()
        assert item.key == "label"
        assert item.descending is False

    def test_order_by_desc(self):
        """req-grid-gryphon-order-by-3: DESC marks a term descending."""
        ast = parse_gryphon("MATCH (n:grid_fixtures__node) RETURN n.name AS label ORDER BY label DESC")
        assert ast.order_by.items[0].descending is True

    def test_order_by_multi_key(self):
        """req-grid-gryphon-order-by-4: multiple terms are kept in written order."""
        ast = parse_gryphon("MATCH (n:grid_fixtures__node) RETURN n.kind AS k, n.name AS label ORDER BY k, label DESC")
        keys = [(i.key, i.descending) for i in ast.order_by.items]
        assert keys == [("k", False), ("label", True)]

    def test_order_by_field_path_parses_envelope_form(self):
        """req-grid-gryphon-order-by-envelope-1: ORDER BY <var>.<data-lane field> parses to a FieldPath."""
        ast = parse_gryphon("MATCH (n:grid_fixtures__node) ORDER BY n.data.observed_at DESC LIMIT 1")
        item = ast.order_by.items[0]
        assert item.path.variable == "n"
        assert [s.name for s in item.path.steps if isinstance(s, DotStep)] == ["data", "observed_at"]
        assert item.descending is True
        # The `.key` derived property is the last dot-step name — matches
        # `_return_item_key`'s default-alias convention for unaliased RETURN
        # items, so projection-mode lookups stay consistent.
        assert item.key == "observed_at"

    def test_order_by_spine_field_path_parses(self):
        """req-grid-gryphon-order-by-envelope-3: ORDER BY <var>.<spine field> parses."""
        ast = parse_gryphon("MATCH (n:grid_fixtures__node) ORDER BY n.name LIMIT 5")
        item = ast.order_by.items[0]
        assert item.path.variable == "n"
        assert [s.name for s in item.path.steps if isinstance(s, DotStep)] == ["name"]
        assert item.descending is False

    @pytest.mark.spec("req-grid-gryphon-limit-1")
    def test_limit_parses(self):
        """req-grid-gryphon-limit-1: LIMIT captures a non-negative integer count."""
        ast = parse_gryphon("MATCH (n:grid_fixtures__node) RETURN n.name AS label LIMIT 7")
        assert isinstance(ast.limit, LimitClause)
        assert ast.limit.count == 7

    @pytest.mark.spec("req-grid-gryphon-limit-3")
    def test_limit_zero_parses(self):
        """req-grid-gryphon-limit-3: LIMIT 0 is a legal literal."""
        ast = parse_gryphon("MATCH (n:grid_fixtures__node) RETURN n.name AS label LIMIT 0")
        assert ast.limit.count == 0

    def test_order_by_and_limit_absent_by_default(self):
        """A query with neither clause leaves both AST fields None."""
        ast = parse_gryphon("MATCH (n:grid_fixtures__node) RETURN n.name AS label")
        assert ast.order_by is None
        assert ast.limit is None

    def test_duplicate_order_by_rejected(self):
        """Two ORDER BY clauses are a parse error, not a silent drop."""
        with pytest.raises(GryphonParseError, match="one ORDER BY"):
            parse_gryphon("MATCH (n:grid_fixtures__node) RETURN n.name AS l ORDER BY l ORDER BY l")

    def test_duplicate_limit_rejected(self):
        """Two LIMIT clauses are a parse error, not a silent drop."""
        with pytest.raises(GryphonParseError, match="one LIMIT"):
            parse_gryphon("MATCH (n:grid_fixtures__node) RETURN n.name AS l LIMIT 1 LIMIT 2")

    @pytest.mark.spec("req-grid-traversal-lang-shape-6")
    def test_duplicate_where_rejected(self):
        """req-grid-traversal-lang-shape-6: two WHERE clauses are a parse error, not a silent drop."""
        with pytest.raises(GryphonParseError, match="one WHERE"):
            parse_gryphon('MATCH (n:grid_fixtures__node) WHERE n.name = "a" WHERE n.kind = "b" RETURN n')

    @pytest.mark.spec("req-grid-traversal-lang-shape-6")
    def test_duplicate_return_rejected(self):
        """req-grid-traversal-lang-shape-6: two RETURN clauses are a parse error, not a silent drop."""
        with pytest.raises(GryphonParseError, match="one RETURN"):
            parse_gryphon("MATCH (n:grid_fixtures__node) RETURN n.name AS a RETURN n.name AS b")

    def test_single_where_still_parses(self):
        """A single WHERE remains valid — the rejection is for duplicates only."""
        ast = parse_gryphon('MATCH (n:grid_fixtures__node) WHERE n.name = "a" RETURN n')
        assert ast.where_clause is not None


# ---------------------------------------------------------------------------
# TestGryphonOrderByLimitExecutor — req-grid-gryphon-order-by / req-grid-gryphon-limit
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonOrderByLimitExecutor:
    """Executor coverage for ORDER BY / LIMIT — positive path plus rejection cases."""

    def _setup_characters(self):
        """Five characters with distinct bios, for ordering tests."""
        import uuid

        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)

        for name in ("Eowyn", "Aragorn", "Denethor", "Boromir", "Celeborn"):
            entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=name)
            ConstrainedSource.objects.create(entity=entity, name=name, description=f"{name} bio")

    def test_order_by_limit_top_n(self):
        """req-grid-gryphon-order-by-3 / limit-2: ORDER BY DESC + LIMIT yields the top rows."""
        self._setup_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="top-n",
            definition={
                "query": "MATCH (c:grid_fixtures__constrained_source) RETURN c.name AS name ORDER BY name DESC LIMIT 2"
            },
        )
        rows = execute_search(search, inputs={})["rows"]
        assert [r["name"] for r in rows] == ["Eowyn", "Denethor"]

    @pytest.mark.spec("req-grid-gryphon-limit-2")
    def test_limit_caps_row_count(self):
        """req-grid-gryphon-limit-2: LIMIT caps the number of rows returned."""
        self._setup_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="cap",
            definition={
                "query": "MATCH (c:grid_fixtures__constrained_source) RETURN c.name AS name ORDER BY name LIMIT 3"
            },
        )
        rows = execute_search(search, inputs={})["rows"]
        assert [r["name"] for r in rows] == ["Aragorn", "Boromir", "Celeborn"]

    def test_order_by_envelope_on_typescan_returns_ordered_node(self):
        """req-grid-gryphon-order-by-envelope-1: a labelled type-scan envelope
        with ORDER BY by field path returns the right node — the panel-shape
        positive path that the helper used to do in Python."""
        self._setup_characters()
        # Order by spine `name` DESC, take 1 → "Eowyn" (lexically last).
        search = Search(
            search_type="gryphon",
            root="node",
            name="latest-character",
            definition={"query": "MATCH (c:grid_fixtures__constrained_source) ORDER BY c.name DESC LIMIT 1"},
        )
        envelope = execute_search(search, inputs={})
        assert envelope["edges"] == []
        # Envelope output is a list of one node (Eowyn). Layer defaults vary; the
        # spine `name` is canonical across layers.
        nodes = envelope["nodes"]
        assert len(nodes) == 1
        assert nodes[0]["name"] == "Eowyn"

    def test_order_by_envelope_on_data_lane_field_resolves(self):
        """req-grid-gryphon-order-by-envelope-3: ORDER BY <var>.data.<field>
        resolves through the same type-scan ORM-path machinery as WHERE."""
        self._setup_characters()
        # `bio` is a per-model field on ConstrainedSource; addressing it as `c.data.description`
        # routes through `_typescan_orm_path`. Bios sort lexically by name
        # ("Aragorn bio" < "Boromir bio" < ...); ASC LIMIT 1 → "Aragorn".
        search = Search(
            search_type="gryphon",
            root="node",
            name="lowest-bio",
            definition={"query": "MATCH (c:grid_fixtures__constrained_source) ORDER BY c.data.description ASC LIMIT 1"},
        )
        envelope = execute_search(search, inputs={})
        assert len(envelope["nodes"]) == 1
        assert envelope["nodes"][0]["name"] == "Aragorn"

    def test_order_by_envelope_no_order_clause_still_caps(self):
        """req-grid-gryphon-order-by-envelope-2: LIMIT alone on a type-scan
        envelope caps the node list deterministically (spine-name default)."""
        self._setup_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="cap-two",
            definition={"query": "MATCH (c:grid_fixtures__constrained_source) LIMIT 2"},
        )
        envelope = execute_search(search, inputs={})
        nodes = envelope["nodes"]
        assert len(nodes) == 2
        # Default order is spine `name` ascending with entity_id tiebreak.
        assert [n["name"] for n in nodes] == ["Aragorn", "Boromir"]

    def test_order_by_envelope_bare_name_rejected(self):
        """req-grid-gryphon-order-by-envelope-8: ORDER BY <bare-name> in envelope
        mode has no defined meaning (no RETURN aliases) and is rejected."""
        self._setup_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="bad-bare",
            definition={"query": "MATCH (c:grid_fixtures__constrained_source) ORDER BY name"},
        )
        with pytest.raises(SearchExecutionError, match="Envelope-mode ORDER BY must name a field path"):
            execute_search(search, inputs={})

    def test_order_by_envelope_unknown_variable_rejected(self):
        """An ORDER BY field path rooted at an unbound variable raises a clear
        error pointing at the bound variable."""
        self._setup_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="bad-var",
            definition={"query": "MATCH (c:grid_fixtures__constrained_source) ORDER BY x.name LIMIT 1"},
        )
        with pytest.raises(SearchExecutionError, match="not bound by this MATCH pattern"):
            execute_search(search, inputs={})

    def test_order_by_projection_mode_field_path_rejected(self):
        """The new envelope-mode field-path surface is rejected in projection
        mode in v0 — pointed at envelope mode rather than silently coerced."""
        self._setup_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="bad-projection-path",
            definition={
                "query": "MATCH (c:grid_fixtures__constrained_source) RETURN c.name AS name ORDER BY c.data.description"
            },
        )
        with pytest.raises(SearchExecutionError, match="envelope-mode RETURN only"):
            execute_search(search, inputs={})

    def test_order_by_on_hub_and_spoke_envelope_still_rejected(self):
        """req-grid-gryphon-order-by-envelope-9: hub-and-spoke envelope still
        rejects ORDER BY / LIMIT — order semantics undefined across hub/neighbors."""
        search = Search(
            search_type="gryphon",
            root="node",
            name="bad-hub-and-spoke",
            definition={"query": "MATCH (h)-[e]-(n) WHERE h.entity_id = $hub ORDER BY h.name"},
        )
        with pytest.raises(SearchExecutionError, match="single labelled type-scan"):
            execute_search(search, inputs={"hub": "00000000-0000-0000-0000-000000000000"})

    def test_limit_on_hub_and_spoke_envelope_still_rejected(self):
        """req-grid-gryphon-order-by-envelope-9: LIMIT on hub-and-spoke envelope rejected."""
        search = Search(
            search_type="gryphon",
            root="node",
            name="bad-hub-limit",
            definition={"query": "MATCH (h)-[e]-(n) WHERE h.entity_id = $hub LIMIT 5"},
        )
        with pytest.raises(SearchExecutionError, match="single labelled type-scan"):
            execute_search(search, inputs={"hub": "00000000-0000-0000-0000-000000000000"})

    def test_order_by_on_edge_type_scan_envelope_still_rejected(self):
        """req-grid-gryphon-order-by-envelope-9: edge-type scan envelope rejected."""
        search = Search(
            search_type="gryphon",
            root="node",
            name="bad-edge-scan",
            definition={
                "query": "MATCH (a:grid_fixtures__constrained_source)-[e:SCHEMA_LINK__grid_fixtures]->(b:grid_fixtures__dual_endpoint) ORDER BY a.name"
            },
        )
        with pytest.raises(SearchExecutionError, match="single labelled type-scan"):
            execute_search(search, inputs={})

    def test_order_by_on_bare_match_envelope_still_rejected(self):
        """req-grid-gryphon-order-by-envelope-9: labelless MATCH (n) envelope rejected."""
        search = Search(
            search_type="gryphon",
            root="node",
            name="bad-bare-match",
            definition={"query": "MATCH (n) ORDER BY n.name"},
        )
        with pytest.raises(SearchExecutionError, match="single labelled type-scan"):
            execute_search(search, inputs={})

    def test_order_by_on_multihop_envelope_still_rejected(self):
        """req-grid-gryphon-order-by-envelope-9: multi-hop envelope rejected."""
        search = Search(
            search_type="gryphon",
            root="node",
            name="bad-multihop",
            definition={
                "query": (
                    "MATCH (a:grid_fixtures__constrained_source)-[:SCHEMA_LINK__grid_fixtures]->(b:grid_fixtures__dual_endpoint)-[:FOUND_IN]->(c:grid_fixtures__constrained_target) "
                    "WHERE a.entity_id = $root ORDER BY c.name"
                )
            },
        )
        with pytest.raises(SearchExecutionError, match="single labelled type-scan"):
            execute_search(search, inputs={"root": "00000000-0000-0000-0000-000000000000"})

    def test_order_by_on_multi_clause_union_envelope_still_rejected(self):
        """req-grid-gryphon-order-by-envelope-9: multi-clause union envelope rejected
        (no canonical ordering across heterogeneous types)."""
        search = Search(
            search_type="gryphon",
            root="node",
            name="bad-union",
            definition={
                "query": "MATCH (c:grid_fixtures__constrained_source) MATCH (a:grid_fixtures__dual_endpoint) ORDER BY c.name"
            },
        )
        with pytest.raises(SearchExecutionError, match="single labelled type-scan"):
            execute_search(search, inputs={})

    def test_order_by_unknown_key_rejected(self):
        """req-grid-gryphon-order-by-2: an ORDER BY term naming no RETURN output is rejected."""
        self._setup_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="bad-key",
            definition={"query": "MATCH (c:grid_fixtures__constrained_source) RETURN c.name AS name ORDER BY nonsuch"},
        )
        with pytest.raises(SearchExecutionError, match="not a RETURN output"):
            execute_search(search, inputs={})

    def test_order_by_on_single_hop_traversal_rejected(self):
        """ORDER BY on a single-hop graph traversal (hub-and-spoke) in projection mode is rejected."""
        search = Search(
            search_type="gryphon",
            root="node",
            name="bad-hop",
            definition={"query": "MATCH (h)-[e]-(n) RETURN h.entity_id AS id ORDER BY id"},
        )
        with pytest.raises(SearchExecutionError, match="ORDER BY / LIMIT"):
            execute_search(search, inputs={})


# ---------------------------------------------------------------------------
# TestGryphonInListParser — req-grid-traversal-lang-in (+ null literal fix)
# ---------------------------------------------------------------------------


class TestGryphonInListParser:
    """Parser coverage for IN-list membership and the null literal."""

    def test_in_list_parses(self):
        """req-grid-traversal-lang-in-1: `field IN [values]` parses to an InComparison."""
        from tap_grid.gryphon.ast_nodes import InComparison

        ast = parse_gryphon('MATCH (n:grid_fixtures__node) WHERE n.kind IN ["a", "b"] RETURN n.entity_id AS id')
        pred = ast.where_clause.predicate
        assert isinstance(pred, InComparison)
        assert pred.field_path.variable == "n"
        assert pred.values == ("a", "b")

    def test_in_empty_list_parses(self):
        """req-grid-traversal-lang-in-3: an empty IN list is legal and parses."""
        from tap_grid.gryphon.ast_nodes import InComparison

        ast = parse_gryphon("MATCH (n:grid_fixtures__node) WHERE n.kind IN [] RETURN n.entity_id AS id")
        assert isinstance(ast.where_clause.predicate, InComparison)
        assert ast.where_clause.predicate.values == ()

    def test_in_list_with_params_collected(self):
        """req-grid-traversal-lang-in-5: $param list elements are collected as required inputs."""
        ast = parse_gryphon("MATCH (n:grid_fixtures__node) WHERE n.entity_id IN [$a, $b] RETURN n.entity_id AS id")
        assert sorted(ast.required_params()) == ["a", "b"]

    def test_in_list_with_null_member_parses(self):
        """req-grid-traversal-lang-in-4: a null element parses to None inside the list."""
        ast = parse_gryphon(
            "MATCH (n:grid_fixtures__node) WHERE n.severity_score IN [null, 20] RETURN n.entity_id AS id"
        )
        assert ast.where_clause.predicate.values == (None, 20)

    def test_in_composes_with_and(self):
        """req-grid-traversal-lang-in-6: an IN leaf combines with AND like any comparison."""
        ast = parse_gryphon(
            'MATCH (n:grid_fixtures__node) WHERE n.kind IN ["a"] AND n.severity_score > 5 RETURN n.entity_id AS id'
        )
        assert isinstance(ast.where_clause.predicate, AndPred)

    def test_null_literal_in_comparison_parses(self):
        """The null literal parses in a plain comparison — the null_val transformer fix.

        Before the fix, `null_val` did not accept the `/null/i` token lark passes
        under @v_args(inline=True), so any `= null` raised a parse error.
        """
        ast = parse_gryphon("MATCH (n:grid_fixtures__node) WHERE n.observed_at = null RETURN n.entity_id AS id")
        assert isinstance(ast.where_clause.predicate, Comparison)
        assert ast.where_clause.predicate.value is None


# ---------------------------------------------------------------------------
# TestGryphonInListExecutor — req-grid-traversal-lang-in
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonInListExecutor:
    """Executor coverage for IN-list membership."""

    def _setup_characters(self):
        """Four characters with distinct bios."""
        import uuid

        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)

        made = {}
        for name in ("Frodo", "Sam", "Merry", "Pippin"):
            entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=name)
            ConstrainedSource.objects.create(entity=entity, name=name, description=f"{name} bio")
            made[name] = entity
        return made

    def test_in_list_matches_listed_values(self):
        """req-grid-traversal-lang-in-2: IN returns rows whose value is a listed member."""
        self._setup_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="in-names",
            definition={
                "query": (
                    'MATCH (c:grid_fixtures__constrained_source) WHERE c.name IN ["Frodo", "Pippin"] '
                    "RETURN c.name AS name ORDER BY name"
                )
            },
        )
        rows = execute_search(search, inputs={})["rows"]
        assert [r["name"] for r in rows] == ["Frodo", "Pippin"]

    def test_in_empty_list_matches_nothing(self):
        """req-grid-traversal-lang-in-3: IN [] returns no rows."""
        self._setup_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="in-empty",
            definition={
                "query": "MATCH (c:grid_fixtures__constrained_source) WHERE c.name IN [] RETURN c.name AS name"
            },
        )
        assert execute_search(search, inputs={}).get("rows", []) == []

    def test_in_list_with_param_elements(self):
        """req-grid-traversal-lang-in-5: $param list elements resolve at execution time."""
        made = self._setup_characters()
        search = Search(
            search_type="gryphon",
            root="node",
            name="in-params",
            definition={
                "query": "MATCH (c:grid_fixtures__constrained_source) WHERE c.entity_id IN [$a, $b] RETURN c.name AS name ORDER BY name"
            },
        )
        rows = execute_search(
            search,
            inputs={"a": str(made["Merry"].pk), "b": str(made["Sam"].pk)},
        )["rows"]
        assert [r["name"] for r in rows] == ["Merry", "Sam"]


# ---------------------------------------------------------------------------
# TestGryphonOptionalMatchParser — req-grid-gryphon-optional-match
# ---------------------------------------------------------------------------


class TestGryphonOptionalMatchParser:
    """Parser coverage for the OPTIONAL MATCH clause."""

    def test_optional_match_parses(self):
        """req-grid-gryphon-optional-match-1: OPTIONAL MATCH parses into its own clause list."""
        from tap_grid.gryphon.ast_nodes import OptionalMatchClause

        ast = parse_gryphon(
            "MATCH (t:grid_fixtures__node) OPTIONAL MATCH (t)<-[:PG_OPTIONAL__grid_fixtures]-(g:grid_fixtures__node) "
            "RETURN t.entity_id AS target, COUNT(g) AS guards"
        )
        assert len(ast.match_clauses) == 1
        assert len(ast.optional_match_clauses) == 1
        assert isinstance(ast.optional_match_clauses[0], OptionalMatchClause)
        opt_pat = ast.optional_match_clauses[0].patterns[0]
        assert opt_pat.edges[0].edge_type == "PG_OPTIONAL__grid_fixtures"
        assert opt_pat.edges[0].direction == "in"

    def test_optional_match_params_collected(self):
        """$param refs inside an OPTIONAL MATCH pattern are collected as required inputs."""
        ast = parse_gryphon(
            "MATCH (t:grid_fixtures__node) OPTIONAL MATCH (t)-[:E {tier: $tier}]->(w:grid_fixtures__node) "
            "RETURN t.entity_id AS id, COUNT(w) AS c"
        )
        assert "tier" in ast.required_params()


# ---------------------------------------------------------------------------
# TestGryphonOptionalMatchExecutor — req-grid-gryphon-optional-match
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonOptionalMatchExecutor:
    """Executor coverage for OPTIONAL MATCH — zero-preservation plus the v0 scope bounds."""

    def _setup(self):
        """Three characters (with backing ConstrainedSource rows); only Frodo wields an artifact."""
        import uuid

        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Edge, Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)

        chars = {}
        for n in ("Frodo", "Sam", "Merry"):
            entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=n)
            ConstrainedSource.objects.create(entity=entity, name=n, description=f"{n} bio")
            chars[n] = entity
        ring = Entity.objects.create(entity_type="grid_fixtures__dual_endpoint", name="One Ring")
        Edge.objects.create(
            entity=Entity.objects.create(entity_type="edge"),
            from_entity=chars["Frodo"],
            to_entity=ring,
            edge_type="SCHEMA_LINK__grid_fixtures",
        )
        return chars

    def _search(self, query):
        return Search(search_type="gryphon", root="node", name="om", definition={"query": query})

    def test_optional_match_keeps_zero_match_rows(self):
        """req-grid-gryphon-optional-match-2/-3: every character appears; COUNT is 0 where unmatched."""
        chars = self._setup()
        search = self._search(
            "MATCH (c:grid_fixtures__constrained_source) OPTIONAL MATCH (c)-[:SCHEMA_LINK__grid_fixtures]->(a:grid_fixtures__dual_endpoint) "
            "RETURN c.entity_id AS character, COUNT(a) AS wielded"
        )
        rows = {r["character"]: r["wielded"] for r in execute_search(search, inputs={})["rows"]}
        assert rows[str(chars["Frodo"].pk)] == 1
        assert rows[str(chars["Sam"].pk)] == 0
        assert rows[str(chars["Merry"].pk)] == 0

    def test_optional_match_multi_hop_rejected(self):
        """req-grid-gryphon-optional-match-8: a multi-hop optional pattern is rejected in v0."""
        search = self._search(
            "MATCH (c:grid_fixtures__constrained_source) OPTIONAL MATCH (c)-[:SCHEMA_LINK__grid_fixtures]->(a:grid_fixtures__dual_endpoint)-[:IN]->(r:grid_fixtures__nesting_container) "
            "RETURN c.entity_id AS id, COUNT(a) AS c"
        )
        with pytest.raises(SearchExecutionError, match="single-hop"):
            execute_search(search, inputs={})

    def test_optional_match_multiple_clauses_rejected(self):
        """req-grid-gryphon-optional-match-8: more than one OPTIONAL MATCH is rejected in v0."""
        search = self._search(
            "MATCH (c:grid_fixtures__constrained_source) "
            "OPTIONAL MATCH (c)-[:SCHEMA_LINK__grid_fixtures]->(a:grid_fixtures__dual_endpoint) "
            "OPTIONAL MATCH (c)-[:OWNS]->(r:grid_fixtures__nesting_container) "
            "RETURN c.entity_id AS id, COUNT(a) AS c"
        )
        with pytest.raises(SearchExecutionError, match="exactly one OPTIONAL MATCH"):
            execute_search(search, inputs={})

    def test_optional_match_graph_envelope_rejected(self):
        """req-grid-gryphon-optional-match-8: a graph-envelope RETURN is rejected in v0."""
        search = self._search(
            "MATCH (c:grid_fixtures__constrained_source) OPTIONAL MATCH (c)-[:SCHEMA_LINK__grid_fixtures]->(a:grid_fixtures__dual_endpoint)"
        )
        with pytest.raises(SearchExecutionError, match="row-projection"):
            execute_search(search, inputs={})

    def test_optional_match_unanchored_rejected(self):
        """req-grid-gryphon-optional-match-8: the optional pattern must start from the MATCH variable."""
        search = self._search(
            "MATCH (c:grid_fixtures__constrained_source) OPTIONAL MATCH (x:grid_fixtures__dual_endpoint)-[:IN]->(r:grid_fixtures__nesting_container) "
            "RETURN c.entity_id AS id, COUNT(r) AS c"
        )
        with pytest.raises(SearchExecutionError, match="must start from the MATCH variable"):
            execute_search(search, inputs={})

    def test_optional_match_projecting_optional_var_rejected(self):
        """req-grid-gryphon-optional-match-8: the optional variable can only be COUNTed, not projected."""
        self._setup()
        search = self._search(
            "MATCH (c:grid_fixtures__constrained_source) OPTIONAL MATCH (c)-[:SCHEMA_LINK__grid_fixtures]->(a:grid_fixtures__dual_endpoint) "
            "RETURN c.entity_id AS id, a.entity_id AS art"
        )
        with pytest.raises(SearchExecutionError, match="optional variable can only be COUNTed"):
            execute_search(search, inputs={})


# ---------------------------------------------------------------------------
# TestGryphonCombinatorsExecutor — req-grid-traversal-lang-combinators (OR / NOT)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonCombinatorsExecutor:
    """Executor coverage for OR / NOT combinators in WHERE.

    The parser has always produced OrPred / NotPred; these confirm the executor
    now compiles the full predicate tree to a Django Q and runs it, rather than
    rejecting OR / NOT with an unsupported-feature error.
    """

    def _setup(self):
        """Four characters with backing ConstrainedSource rows."""
        import uuid

        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)
        for name in ("Frodo", "Sam", "Merry", "Pippin"):
            entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=name)
            ConstrainedSource.objects.create(entity=entity, name=name, description=f"{name} bio")

    def _search(self, query):
        return Search(search_type="gryphon", root="node", name="comb", definition={"query": query})

    def test_or_predicate_executes(self):
        """req-grid-traversal-lang-combinators-2: OR returns rows matching either branch."""
        self._setup()
        search = self._search(
            'MATCH (c:grid_fixtures__constrained_source) WHERE c.name = "Frodo" OR c.name = "Pippin" '
            "RETURN c.name AS name ORDER BY name"
        )
        rows = execute_search(search, inputs={})["rows"]
        assert [r["name"] for r in rows] == ["Frodo", "Pippin"]

    def test_not_predicate_executes(self):
        """req-grid-traversal-lang-combinators-3: NOT negates a comparison."""
        self._setup()
        search = self._search(
            'MATCH (c:grid_fixtures__constrained_source) WHERE NOT c.name = "Frodo" RETURN c.name AS name ORDER BY name'
        )
        rows = execute_search(search, inputs={})["rows"]
        assert [r["name"] for r in rows] == ["Merry", "Pippin", "Sam"]

    def test_parenthesized_grouping_executes(self):
        """req-grid-traversal-lang-combinators-4: parentheses override precedence.

        ``(Frodo OR Sam) AND NOT Sam`` resolves to just Frodo; without the
        parentheses, AND would bind ``Sam AND NOT Sam`` first.
        """
        self._setup()
        search = self._search(
            'MATCH (c:grid_fixtures__constrained_source) WHERE (c.name = "Frodo" OR c.name = "Sam") AND NOT c.name = "Sam" '
            "RETURN c.name AS name ORDER BY name"
        )
        rows = execute_search(search, inputs={})["rows"]
        assert [r["name"] for r in rows] == ["Frodo"]


# ---------------------------------------------------------------------------
# TestGryphonStringMatchParser — req-grid-traversal-lang-string-match
# ---------------------------------------------------------------------------


class TestGryphonStringMatchParser:
    """Parser coverage for the STARTS_WITH / ENDS_WITH / CONTAINS operators."""

    def test_starts_with_parses(self):
        """req-grid-traversal-lang-string-match-1: STARTS_WITH parses to a Comparison."""
        ast = parse_gryphon('MATCH (n:grid_fixtures__node) WHERE n.name STARTS_WITH "Neigh" RETURN n.entity_id AS id')
        pred = ast.where_clause.predicate
        assert isinstance(pred, Comparison)
        assert pred.op == "starts_with"
        assert pred.value == "Neigh"

    def test_ends_with_and_contains_parse(self):
        """req-grid-traversal-lang-string-match-1: ENDS_WITH / CONTAINS parse to their ops."""
        for keyword, op in (("ENDS_WITH", "ends_with"), ("CONTAINS", "contains")):
            ast = parse_gryphon(f'MATCH (n:grid_fixtures__node) WHERE n.name {keyword} "x" RETURN n.entity_id AS id')
            assert ast.where_clause.predicate.op == op

    def test_string_op_keyword_is_case_insensitive(self):
        """The operator keyword is case-insensitive; the AST `op` normalizes to lower case."""
        ast = parse_gryphon('MATCH (n:grid_fixtures__node) WHERE n.name starts_with "x" RETURN n.entity_id AS id')
        assert ast.where_clause.predicate.op == "starts_with"

    def test_string_match_needle_may_be_param(self):
        """req-grid-traversal-lang-string-match-4: the needle may be a $param."""
        ast = parse_gryphon("MATCH (n:grid_fixtures__node) WHERE n.name ENDS_WITH $suffix RETURN n.entity_id AS id")
        assert "suffix" in ast.required_params()


# ---------------------------------------------------------------------------
# TestGryphonStringMatchExecutor — req-grid-traversal-lang-string-match
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonStringMatchExecutor:
    """Executor coverage for the substring operators — positive path plus needle escaping."""

    def _make(self, *specs):
        """Create characters from (name, bio) tuples."""
        import uuid

        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)
        for name, bio in specs:
            entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=name)
            ConstrainedSource.objects.create(entity=entity, name=name, description=bio)

    def _search(self, query):
        return Search(search_type="gryphon", root="node", name="sm", definition={"query": query})

    def test_starts_with_executes(self):
        """req-grid-traversal-lang-string-match-2: STARTS_WITH filters by prefix."""
        self._make(("Aragorn", "x"), ("Arwen", "x"), ("Boromir", "x"))
        rows = execute_search(
            self._search(
                'MATCH (c:grid_fixtures__constrained_source) WHERE c.name STARTS_WITH "Ar" RETURN c.name AS name ORDER BY name'
            ),
            inputs={},
        )["rows"]
        assert [r["name"] for r in rows] == ["Aragorn", "Arwen"]

    def test_like_metacharacters_in_needle_are_literal(self):
        """req-grid-traversal-lang-string-match-5: a `%` in the needle matches literally.

        If `%` were treated as a LIKE wildcard, `NESTING_LINK__grid_fixtures "100%"` would also match
        "battery 100 then percent"; escaped, it matches only the literal "100%".
        """
        self._make(("Literal", "battery 100% charged"), ("Wildcard", "battery 100 then percent"))
        rows = execute_search(
            self._search(
                'MATCH (c:grid_fixtures__constrained_source) WHERE c.data.description CONTAINS "100%" RETURN c.name AS name'
            ),
            inputs={},
        )["rows"]
        assert [r["name"] for r in rows] == ["Literal"]


# ---------------------------------------------------------------------------
# TestGryphonBareMatchExecutor — req-grid-traversal-lang-bare-match
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonBareMatchExecutor:
    """Executor coverage for labelless MATCH (n) — the bare scan over all node types."""

    def _setup(self):
        """Two characters (which have a `bio` field) and two pg_node rows (which do not)."""
        import uuid

        from tap_plugin.grid_fixtures.models import ConstrainedSource, PgNode

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)
        made = {}
        for name in ("Frodo", "Sam"):
            entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=name)
            ConstrainedSource.objects.create(entity=entity, name=name, description=f"{name} the brave")
            made[name] = entity
        for name in ("Node A", "Node B"):
            entity = Entity.objects.create(entity_type="grid_fixtures__node", name=name)
            PgNode.objects.create(entity=entity, name=name, kind="island")
            made[name] = entity
        return made

    def _search(self, query):
        return Search(search_type="gryphon", root="node", name="bm", definition={"query": query})

    def test_bare_match_unions_node_types_and_excludes_edges(self):
        """req-grid-traversal-lang-bare-match-2/-5: every node type unioned; edges excluded."""
        from tap_grid.models import Edge, Entity

        made = self._setup()
        Edge.objects.create(
            entity=Entity.objects.create(entity_type="edge"),
            from_entity=made["Frodo"],
            to_entity=made["Sam"],
            edge_type="KNOWS",
        )
        result = execute_search(self._search("MATCH (n)"), inputs={})
        assert sorted({node["entity_type"] for node in result["nodes"]}) == [
            "grid_fixtures__constrained_source",
            "grid_fixtures__node",
        ]
        assert len(result["nodes"]) == 4

    def test_bare_match_field_absence_is_silently_non_matching(self):
        """req-grid-traversal-lang-bare-match-3: a type lacking the data field matches nothing, no error.

        `bio` is a ConstrainedSource field; pg_node has no `bio`. The bare scan must skip
        pg_node silently and return only the matching ConstrainedSource.
        """
        self._setup()
        result = execute_search(self._search('MATCH (n) WHERE n.data.description = "Frodo the brave"'), inputs={})
        assert sorted(node["name"] for node in result["nodes"]) == ["Frodo"]

    def test_bare_match_row_projection_rejected(self):
        """req-grid-traversal-lang-bare-match-6: row projection over a bare scan is rejected in v0."""
        with pytest.raises(SearchExecutionError, match="graph-envelope"):
            execute_search(self._search("MATCH (n) RETURN n.entity_id AS id"), inputs={})

    def test_bare_match_order_by_rejected(self):
        """req-grid-traversal-lang-bare-match-6: ORDER BY on a bare scan is rejected in v0."""
        with pytest.raises(SearchExecutionError, match="ORDER BY / LIMIT"):
            execute_search(self._search("MATCH (n) RETURN n.entity_id AS id ORDER BY id"), inputs={})

    def test_bare_match_data_lane_or_rejected(self):
        """A data-lane WHERE on a bare scan must be AND-joined; OR is rejected in v0."""
        with pytest.raises(SearchExecutionError, match="AND-joined"):
            execute_search(
                self._search('MATCH (n) WHERE n.data.kind = "island" OR n.data.kind = "hub"'),
                inputs={},
            )


# ---------------------------------------------------------------------------
# TestGryphonTypelessEdgeScanExecutor — req-grid-traversal-lang-patterns-7
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonTypelessEdgeScanExecutor:
    """Executor coverage for the typeless edge scan — MATCH (a)-[e]-(b), no edge type."""

    def _setup(self):
        """Frodo SCHEMA_LINK__grid_fixtures the Ring and OWNS the Shire — two edges of different types."""
        import uuid

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Edge, Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)
        frodo = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Frodo")
        ring = Entity.objects.create(entity_type="grid_fixtures__dual_endpoint", name="One Ring")
        shire = Entity.objects.create(entity_type="grid_fixtures__nesting_container", name="The Shire")
        for src, tgt, edge_type in ((frodo, ring, "SCHEMA_LINK__grid_fixtures"), (frodo, shire, "OWNS")):
            Edge.objects.create(
                entity=Entity.objects.create(entity_type="edge"),
                from_entity=src,
                to_entity=tgt,
                edge_type=edge_type,
            )

    def _search(self, query):
        return Search(search_type="gryphon", root="node", name="te", definition={"query": query})

    def test_typeless_edge_scan_returns_all_edge_types(self):
        """req-grid-traversal-lang-patterns-7: a labelless edge scans edges of every type.

        Previously `MATCH (a)-[e]-(b)` with no edge type raised an unsupported-
        pattern error; it now scans every edge.
        """
        self._setup()
        result = execute_search(self._search("MATCH (a)-[e]->(b)"), inputs={})
        assert len(result["edges"]) == 2

    def test_typeless_edge_scan_honors_endpoint_labels(self):
        """A labelless edge still filters by the pattern's node labels."""
        self._setup()
        result = execute_search(
            self._search("MATCH (a:grid_fixtures__constrained_source)-[e]->(b:grid_fixtures__dual_endpoint)"), inputs={}
        )
        # The character->artifact SCHEMA_LINK__grid_fixtures edge only; the character->realm OWNS edge is excluded.
        assert len(result["edges"]) == 1


# ---------------------------------------------------------------------------
# TestGryphonIsNullParser — req-grid-traversal-lang-is-null
# ---------------------------------------------------------------------------


class TestGryphonIsNullParser:
    """Parser coverage for the IS NULL / IS NOT NULL predicate."""

    def test_is_null_parses(self):
        """req-grid-traversal-lang-is-null-1: `field IS NULL` parses to IsNullComparison."""
        from tap_grid.gryphon.ast_nodes import IsNullComparison

        ast = parse_gryphon("MATCH (n:grid_fixtures__node) WHERE n.data.observed_at IS NULL")
        pred = ast.where_clause.predicate
        assert isinstance(pred, IsNullComparison)
        assert pred.field_path.variable == "n"
        assert [s.name for s in pred.field_path.steps if isinstance(s, DotStep)] == ["data", "observed_at"]
        assert pred.negated is False

    def test_is_not_null_parses(self):
        """req-grid-traversal-lang-is-null-2: `field IS NOT NULL` parses with negated=True."""
        from tap_grid.gryphon.ast_nodes import IsNullComparison

        ast = parse_gryphon("MATCH (n:grid_fixtures__node) WHERE n.data.observed_at IS NOT NULL")
        pred = ast.where_clause.predicate
        assert isinstance(pred, IsNullComparison)
        assert pred.negated is True

    def test_is_null_composes_with_and(self):
        """req-grid-traversal-lang-is-null-3: IS NULL nests inside an AND tree like any leaf."""
        from tap_grid.gryphon.ast_nodes import IsNullComparison

        ast = parse_gryphon(
            'MATCH (n:grid_fixtures__node) WHERE n.data.observed_at IS NULL AND n.data.kind = "reading"'
        )
        pred = ast.where_clause.predicate
        assert isinstance(pred, AndPred)
        # The IS NULL leaf may be on either side depending on the parser's associativity;
        # locate it by type.
        leaves = [pred.left, pred.right]
        assert any(isinstance(leaf, IsNullComparison) and leaf.negated is False for leaf in leaves)

    def test_is_null_composes_with_not(self):
        """req-grid-traversal-lang-is-null-3: NOT (foo IS NULL) is the equivalent long-form."""
        from tap_grid.gryphon.ast_nodes import IsNullComparison

        ast = parse_gryphon("MATCH (n:grid_fixtures__node) WHERE NOT (n.data.observed_at IS NULL)")
        pred = ast.where_clause.predicate
        assert isinstance(pred, NotPred)
        assert isinstance(pred.operand, IsNullComparison)
        assert pred.operand.negated is False

    def test_bare_is_rejected(self):
        """req-grid-traversal-lang-is-null-5: `field IS` (no NULL) fails parse."""
        with pytest.raises(GryphonParseError):
            parse_gryphon("MATCH (n:grid_fixtures__node) WHERE n.data.observed_at IS")

    def test_value_null_literal_still_parses(self):
        """The `_NULL_KW` terminal is shared with the `value -> null_val` rule —
        an equality comparison against `null` must continue to parse to a
        Comparison leaf with value=None, not be misread as IS NULL."""
        ast = parse_gryphon("MATCH (n:grid_fixtures__node) WHERE n.data.observed_at = null")
        pred = ast.where_clause.predicate
        assert isinstance(pred, Comparison)
        assert pred.op == "="
        assert pred.value is None


# ---------------------------------------------------------------------------
# TestGryphonIsNullExecutor — req-grid-traversal-lang-is-null
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonIsNullExecutor:
    """Executor coverage for IS NULL / IS NOT NULL — positive paths + composition."""

    def _setup_characters_with_bios(self):
        """Five characters, one with a NULL bio — for IS NULL / IS NOT NULL filtering."""
        import uuid

        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)

        # Four characters with bios.
        for name in ("Aragorn", "Boromir", "Celeborn", "Denethor"):
            entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=name)
            ConstrainedSource.objects.create(entity=entity, name=name, description=f"{name} bio")
        # One with bio set to the empty string (the model defaults to ""; null is
        # not allowed on bio, but `is_open`-style optional fields on pg_node would
        # be the cleaner null carrier — the Gridkin scenarios cover that). For
        # the executor IS NULL exec test we exercise the empty-bio path that
        # behaves like a present but empty value, plus a separately set NULL on a
        # spine-adjacent field — see is_not_null filter test below.
        entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name="Eowyn")
        ConstrainedSource.objects.create(entity=entity, name="Eowyn", description="")

    def test_is_not_null_filter_works(self):
        """req-grid-traversal-lang-is-null-2: IS NOT NULL filters out NULL values.
        On ConstrainedSource.description (a non-nullable TextField defaulting to ''), no row is
        ever NULL — so IS NOT NULL returns all 5 rows. The complementary IS NULL
        case returns zero. This confirms the lowering reaches the column and
        produces the right SQL, even though the model field itself can't be
        NULL — Gridkin's pg_node fixture exercises the nullable-column path."""
        self._setup_characters_with_bios()
        search = Search(
            search_type="gryphon",
            root="node",
            name="bio-not-null",
            definition={"query": "MATCH (c:grid_fixtures__constrained_source) WHERE c.data.description IS NOT NULL"},
        )
        envelope = execute_search(search, inputs={})
        assert len(envelope["nodes"]) == 5

    def test_is_null_on_non_nullable_column_returns_empty(self):
        """req-grid-traversal-lang-is-null-1: IS NULL on a non-nullable column
        returns zero rows. Defends against any silent coercion of `''` to NULL."""
        self._setup_characters_with_bios()
        search = Search(
            search_type="gryphon",
            root="node",
            name="bio-is-null",
            definition={"query": "MATCH (c:grid_fixtures__constrained_source) WHERE c.data.description IS NULL"},
        )
        envelope = execute_search(search, inputs={})
        assert envelope["nodes"] == []

    def test_is_not_null_composes_with_and(self):
        """req-grid-traversal-lang-is-null-3: AND with IS NOT NULL narrows the set."""
        self._setup_characters_with_bios()
        search = Search(
            search_type="gryphon",
            root="node",
            name="and-is-not-null",
            definition={
                "query": 'MATCH (c:grid_fixtures__constrained_source) WHERE c.data.description IS NOT NULL AND c.name = "Aragorn"'
            },
        )
        envelope = execute_search(search, inputs={})
        assert len(envelope["nodes"]) == 1
        assert envelope["nodes"][0]["name"] == "Aragorn"

    def test_is_null_composes_with_not(self):
        """req-grid-traversal-lang-is-null-3: NOT (x IS NULL) is equivalent to x IS NOT NULL."""
        self._setup_characters_with_bios()
        search = Search(
            search_type="gryphon",
            root="node",
            name="not-is-null",
            definition={"query": "MATCH (c:grid_fixtures__constrained_source) WHERE NOT (c.data.description IS NULL)"},
        )
        envelope = execute_search(search, inputs={})
        assert len(envelope["nodes"]) == 5


# ---------------------------------------------------------------------------
# TestGryphonObservationParser — req-grid-traversal-lang-observation
# ---------------------------------------------------------------------------


class TestGryphonObservationParser:
    """Parser coverage for the IS KNOWN / IS UNKNOWN observation predicates."""

    def test_is_unknown_parses(self):
        """req-grid-traversal-lang-observation-1: `field IS UNKNOWN` -> ObservationComparison(unknown)."""
        from tap_grid.gryphon.ast_nodes import ObservationComparison

        ast = parse_gryphon("MATCH (n:grid_fixtures__node) WHERE n.data.observed_at IS UNKNOWN")
        pred = ast.where_clause.predicate
        assert isinstance(pred, ObservationComparison)
        assert pred.kind == "unknown"
        assert [s.name for s in pred.field_path.steps if isinstance(s, DotStep)] == ["data", "observed_at"]

    def test_is_known_parses(self):
        """req-grid-traversal-lang-observation-2: `field IS KNOWN` -> ObservationComparison(known)."""
        from tap_grid.gryphon.ast_nodes import ObservationComparison

        ast = parse_gryphon("MATCH (n:grid_fixtures__node) WHERE n.data.observed_at IS KNOWN")
        pred = ast.where_clause.predicate
        assert isinstance(pred, ObservationComparison)
        assert pred.kind == "known"

    def test_is_unknown_composes_with_and(self):
        """req-grid-traversal-lang-observation-3: composes inside an AND tree like any leaf."""
        from tap_grid.gryphon.ast_nodes import ObservationComparison

        ast = parse_gryphon(
            'MATCH (n:grid_fixtures__node) WHERE n.data.observed_at IS UNKNOWN AND n.data.kind = "reading"'
        )
        pred = ast.where_clause.predicate
        assert isinstance(pred, AndPred)
        leaves = [pred.left, pred.right]
        assert any(isinstance(leaf, ObservationComparison) and leaf.kind == "unknown" for leaf in leaves)

    def test_is_known_composes_with_not(self):
        """req-grid-traversal-lang-observation-3: NOT (x IS KNOWN) is the negated long-form."""
        from tap_grid.gryphon.ast_nodes import ObservationComparison

        ast = parse_gryphon("MATCH (n:grid_fixtures__node) WHERE NOT (n.data.observed_at IS KNOWN)")
        pred = ast.where_clause.predicate
        assert isinstance(pred, NotPred)
        assert isinstance(pred.operand, ObservationComparison)
        assert pred.operand.kind == "known"

    def test_bare_is_still_rejected(self):
        """req-grid-traversal-lang-observation-4: bare `IS` (no KNOWN/UNKNOWN/NULL) fails parse."""
        with pytest.raises(GryphonParseError):
            parse_gryphon("MATCH (n:grid_fixtures__node) WHERE n.data.observed_at IS")


# ---------------------------------------------------------------------------
# TestGryphonObservationExecutor — req-grid-traversal-lang-observation
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonObservationExecutor:
    """Executor coverage for IS KNOWN / IS UNKNOWN on a real nullable column.

    Uses the neutral grid_fixtures PgNode (``grid_fixtures__node``) — whose
    ``observed_at`` is a nullable field — so this core suite exercises the genuine
    null axis without depending on any domain plugin. grid_fixtures is present in
    every profile that runs the core suite (core_dev / test_all); the rest of this
    file already targets grid_fixtures__* types the same way. Writes go through the
    service layer (create_node), the canonical path for TAP-managed nodes."""

    _TYPE = "grid_fixtures__node"

    def _setup_nodes(self):
        """Three nodes with an observed timestamp, two with NULL (unobserved) — on the
        nullable ``observed_at`` column, exercising the genuine null axis. observed_at
        is simply omitted for the unobserved rows, so the column is NULL."""
        import uuid

        from tap_grid.caller_context import CallerContext
        from tap_grid.services import create_node

        observed = "2026-01-01T00:00:00Z"
        for i in range(3):
            create_node(
                self._TYPE,
                {"name": f"eth{i}", "kind": "nic", "observed_at": observed},
                caller_context=CallerContext(batch_id=str(uuid.uuid7())),
            )
        for name, kind in (("lo0", "loopback"), ("lo1", "tunnel")):
            create_node(
                self._TYPE,
                {"name": name, "kind": kind},
                caller_context=CallerContext(batch_id=str(uuid.uuid7())),
            )

    def _run(self, query: str) -> list:
        search = Search(search_type="gryphon", root="node", name="obs", definition={"query": query})
        return execute_search(search, inputs={})["nodes"]

    def test_is_unknown_selects_unobserved(self):
        """req-grid-traversal-lang-observation-1: IS UNKNOWN returns only the NULL rows."""
        self._setup_nodes()
        nodes = self._run("MATCH (n:grid_fixtures__node) WHERE n.data.observed_at IS UNKNOWN")
        assert len(nodes) == 2

    def test_is_known_selects_observed(self):
        """req-grid-traversal-lang-observation-2: IS KNOWN returns only the non-NULL rows."""
        self._setup_nodes()
        nodes = self._run("MATCH (n:grid_fixtures__node) WHERE n.data.observed_at IS KNOWN")
        assert len(nodes) == 3

    def test_known_and_unknown_partition_the_set(self):
        """The two predicates partition the null axis: |KNOWN| + |UNKNOWN| == total."""
        self._setup_nodes()
        known = self._run("MATCH (n:grid_fixtures__node) WHERE n.data.observed_at IS KNOWN")
        unknown = self._run("MATCH (n:grid_fixtures__node) WHERE n.data.observed_at IS UNKNOWN")
        all_nodes = self._run("MATCH (n:grid_fixtures__node)")
        assert len(known) + len(unknown) == len(all_nodes) == 5

    def test_is_unknown_composes_with_and(self):
        """req-grid-traversal-lang-observation-3: AND with IS UNKNOWN narrows the set."""
        self._setup_nodes()
        nodes = self._run(
            'MATCH (n:grid_fixtures__node) WHERE n.data.observed_at IS UNKNOWN AND n.data.kind = "loopback"'
        )
        assert len(nodes) == 1
        assert nodes[0]["name"] == "lo0"


# ---------------------------------------------------------------------------
# TestGryphonRegexParser — req-grid-traversal-lang-regex
# ---------------------------------------------------------------------------


class TestGryphonRegexParser:
    """Parser coverage for the `=~` regex match operator."""

    def test_regex_parses_to_comparison_with_op_regex(self):
        """req-grid-traversal-lang-regex-1: `=~` parses to a Comparison with op=='regex'."""
        ast = parse_gryphon('MATCH (n:grid_fixtures__node) WHERE n.name =~ "github" RETURN n.entity_id AS id')
        pred = ast.where_clause.predicate
        assert isinstance(pred, Comparison)
        assert pred.op == "regex"
        assert pred.value == "github"

    def test_regex_needle_may_be_param(self):
        """req-grid-traversal-lang-regex-8: the needle may be a $param."""
        ast = parse_gryphon("MATCH (n:grid_fixtures__node) WHERE n.name =~ $pattern RETURN n.entity_id AS id")
        assert "pattern" in ast.required_params()

    def test_regex_composes_with_and_or_not(self):
        """req-grid-traversal-lang-regex-9: regex composes inside AND / OR / NOT trees."""
        ast = parse_gryphon(
            'MATCH (n:grid_fixtures__node) WHERE n.name =~ "(?i)token" AND NOT (n.name =~ "imposter") '
            "RETURN n.entity_id AS id"
        )
        pred = ast.where_clause.predicate
        assert isinstance(pred, AndPred)
        # Left side is the positive regex comparison; right side is NOT(regex).
        # Locate them by shape (Earley associativity may flip them).
        leaves = [pred.left, pred.right]
        positive = next((leaf for leaf in leaves if isinstance(leaf, Comparison) and leaf.op == "regex"), None)
        assert positive is not None and positive.value == "(?i)token"
        negated = next((leaf for leaf in leaves if isinstance(leaf, NotPred)), None)
        assert negated is not None and isinstance(negated.operand, Comparison)
        assert negated.operand.op == "regex" and negated.operand.value == "imposter"

    def test_regex_on_data_lane_path(self):
        """req-grid-traversal-lang-regex-10: regex on a multi-step data-lane path parses cleanly."""
        ast = parse_gryphon(
            'MATCH (n:grid_fixtures__node) WHERE n.data.tags.url =~ "(?i)github" RETURN n.entity_id AS id'
        )
        pred = ast.where_clause.predicate
        assert isinstance(pred, Comparison)
        assert pred.op == "regex"
        assert pred.field_path.variable == "n"
        # Three dot steps: data, tags, url.
        assert [s.name for s in pred.field_path.steps if isinstance(s, DotStep)] == ["data", "tags", "url"]


# ---------------------------------------------------------------------------
# TestGryphonRegexExecutor — req-grid-traversal-lang-regex
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True, databases=["default", "search_readonly"])
class TestGryphonRegexExecutor:
    """Executor coverage for `=~` — crafted corners that Gridkin's shared fixture
    does not (and should not) carry: a column-NULL row (ConstrainedSource.description is a
    non-nullable TextField but the JSON-key NULL case is the Gridkin witness;
    here we exercise the executor's NULL-pattern short-circuit and the
    metacharacter-in-needle path on crafted ConstrainedSource rows)."""

    def _make(self, *specs):
        """Create characters from (name, bio) tuples."""
        import uuid

        from tap_plugin.grid_fixtures.models import ConstrainedSource

        from tap_grid.caller_context import CallerContext, get_caller_context, set_caller_context
        from tap_grid.models import Entity

        ctx = CallerContext(user=get_caller_context().user, batch_id=str(uuid.uuid4()))
        set_caller_context(ctx)
        for name, bio in specs:
            entity = Entity.objects.create(entity_type="grid_fixtures__constrained_source", name=name)
            ConstrainedSource.objects.create(entity=entity, name=name, description=bio)

    def _search(self, query, **kwargs):
        return Search(search_type="gryphon", root="node", name="re", definition={"query": query, **kwargs})

    def test_regex_search_semantics_substring_match(self):
        """req-grid-traversal-lang-regex-2: `=~` matches the pattern anywhere in
        the value — no implicit anchoring. The pattern `"token"` matches a name
        that has `token` in the middle, not just at the start."""
        self._make(("alpha-token-1", "x"), ("just-text", "x"))
        rows = execute_search(
            self._search(
                'MATCH (c:grid_fixtures__constrained_source) WHERE c.name =~ "token" RETURN c.name AS name ORDER BY name'
            ),
            inputs={},
        )["rows"]
        assert [r["name"] for r in rows] == ["alpha-token-1"]

    def test_regex_explicit_anchors_force_full_match(self):
        """req-grid-traversal-lang-regex-2: `^...$` forces a full-string match;
        only the exactly-equal row matches."""
        self._make(("exact", "x"), ("exact-suffix", "x"), ("prefix-exact", "x"))
        rows = execute_search(
            self._search(
                'MATCH (c:grid_fixtures__constrained_source) WHERE c.name =~ "^exact$" RETURN c.name AS name ORDER BY name'
            ),
            inputs={},
        )["rows"]
        assert [r["name"] for r in rows] == ["exact"]

    def test_regex_case_insensitive_inline_flag(self):
        """req-grid-traversal-lang-regex-4: `(?i)` makes the search case-
        insensitive — Postgres consumes the inline flag unaltered (no executor-
        side rewriting)."""
        self._make(("MixedCase", "x"), ("MIXEDCASE", "x"), ("other", "x"))
        rows = execute_search(
            self._search(
                'MATCH (c:grid_fixtures__constrained_source) WHERE c.name =~ "(?i)mixedcase" RETURN c.name AS name ORDER BY name'
            ),
            inputs={},
        )["rows"]
        # Case-sensitive `=~ "mixedcase"` (no flag) matches neither; with
        # `(?i)` both spellings match. The set is the assertion — sort order
        # between the two equal-modulo-case names is the collation's tiebreaker
        # and not the behavior under test.
        assert sorted(r["name"] for r in rows) == ["MIXEDCASE", "MixedCase"]

    def test_regex_needle_is_regex_text_not_escaped(self):
        """req-grid-traversal-lang-regex-7: `.` is a regex metacharacter (any
        character), not a literal dot — opposite of `NESTING_LINK__grid_fixtures`. The pattern
        `"a.b"` matches `aXb` because `.` is "any char." This is the explicit
        deal of `=~` and must be loud."""
        self._make(("aXb", "x"), ("a.b", "x"), ("axxb", "x"))
        rows = execute_search(
            self._search(
                'MATCH (c:grid_fixtures__constrained_source) WHERE c.name =~ "a.b" RETURN c.name AS name ORDER BY name'
            ),
            inputs={},
        )["rows"]
        # All three names have `a` + single char + `b` somewhere — `aXb`, `a.b`,
        # `axxb` (the substring `axb`? no — axxb has `a`, `x`, `x`, `b`, so the
        # window `a.b` does NOT match `axx`; `a` then any char then `b` requires
        # exactly one char between). So axxb does NOT match. Result: aXb, a.b.
        assert [r["name"] for r in rows] == ["a.b", "aXb"]

    def test_regex_escaped_dot_forces_literal(self):
        """req-grid-traversal-lang-regex-7: `\\.` in the needle forces a literal
        dot — the same fixture row from above shows the inverse: `aXb` does not
        match `"a\\.b"`, only the literal-dot row does."""
        self._make(("aXb", "x"), ("a.b", "x"))
        rows = execute_search(
            self._search(
                'MATCH (c:grid_fixtures__constrained_source) WHERE c.name =~ "a\\.b" RETURN c.name AS name ORDER BY name'
            ),
            inputs={},
        )["rows"]
        assert [r["name"] for r in rows] == ["a.b"]

    def test_regex_null_pattern_returns_empty(self):
        """req-grid-traversal-lang-regex-6: a NULL needle (via `$pattern=None`)
        compiles to a tautologically-false `Q` — the row set is empty, the
        executor does not crash. This is the explicit "NULL pattern doesn't
        crash, doesn't match" contract. The envelope omits the `rows` key
        entirely when the projected row set is empty — same envelope shape
        the Gridkin runner exposes for the matching scenario."""
        self._make(("alpha", "x"), ("beta", "x"))
        envelope = execute_search(
            self._search(
                "MATCH (c:grid_fixtures__constrained_source) WHERE c.name =~ $pattern RETURN c.name AS name ORDER BY name"
            ),
            inputs={"pattern": None},
        )
        assert envelope.get("rows", []) == []

    def test_regex_param_pattern_resolves_at_execution(self):
        """req-grid-traversal-lang-regex-8: $pattern resolves at execution time."""
        self._make(("alpha", "x"), ("ALPHA", "x"), ("beta", "x"))
        rows = execute_search(
            self._search(
                "MATCH (c:grid_fixtures__constrained_source) WHERE c.name =~ $pattern RETURN c.name AS name ORDER BY name"
            ),
            inputs={"pattern": "(?i)alpha"},
        )["rows"]
        assert sorted(r["name"] for r in rows) == ["ALPHA", "alpha"]

    def test_regex_on_spine_entity_type(self):
        """req-grid-traversal-lang-regex-10: regex works on the spine
        entity_type field — a bare type-prefix match for `^character` returns
        every character row regardless of which type-scan executor path the
        query takes."""
        self._make(("aragorn", "x"), ("boromir", "x"))
        rows = execute_search(
            self._search(
                'MATCH (c:grid_fixtures__constrained_source) WHERE c.entity_type =~ "^grid_fixtures__constrained_source" RETURN c.name AS name ORDER BY name'
            ),
            inputs={},
        )["rows"]
        assert sorted(r["name"] for r in rows) == ["aragorn", "boromir"]

    def test_regex_empty_field_value_vs_non_empty_pattern(self):
        """req-grid-traversal-lang-regex-11 (TCK-mined corner): an empty field
        value does not match a non-empty pattern. `'' ~ 'x'` is false in
        Postgres — the empty-string row is dropped. Crafted in test_gryphon
        because PgNode fixture rows all carry non-empty names; here we set
        ConstrainedSource.description to '' inline to exercise the empty-vs-non-empty corner
        without forcing a fixture row."""
        self._make(("with-content", "abc"), ("empty-bio", ""))
        rows = execute_search(
            self._search(
                'MATCH (c:grid_fixtures__constrained_source) WHERE c.data.description =~ "a" RETURN c.name AS name ORDER BY name'
            ),
            inputs={},
        )["rows"]
        assert [r["name"] for r in rows] == ["with-content"]


class TestMaterializeRowsDistinctFailClosed:
    """The shared row backend fails closed on the dormant DISTINCT flag.

    `plan.distinct` is unreachable via a query today (`ReturnClause` has no
    `distinct` field), so these pin the backend contract directly, below the
    service layer: a set flag must *reject*, never silently no-op (`GRY-ARCH-3`)
    — both over an aggregate plan (`req-grid-traversal-exec-row-materialization-14`)
    and over a non-aggregate plan (the not-yet-wired `.values().distinct()`). The
    reject fires before the queryset is touched, so no database is needed.
    """

    def _plan(self, *, distinct: bool, aggregate: bool):
        from tap_grid.gryphon.executor import MaterializationPlan

        return MaterializationPlan(
            queryset=None,
            pre_annotations={},
            group_pairs=(("_c0", "a"),),
            aggregate_annotations={"_agg": object()} if aggregate else {},
            aggregate_pairs=(),
            order_cols=(),
            distinct=distinct,
        )

    def test_distinct_over_aggregate_rejects(self):
        from tap_grid.gryphon.executor import materialize_rows

        with pytest.raises(SearchExecutionError, match=r"aggregate"):
            materialize_rows(self._plan(distinct=True, aggregate=True))

    def test_non_aggregate_distinct_fails_closed(self):
        from tap_grid.gryphon.executor import materialize_rows

        with pytest.raises(SearchExecutionError, match=r"not implemented yet"):
            materialize_rows(self._plan(distinct=True, aggregate=False))
