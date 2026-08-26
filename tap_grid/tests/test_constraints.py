"""Tests for edge constraint validation."""

from collections.abc import Iterator

import pytest
from django.core.exceptions import ImproperlyConfigured

from tap.pytest_harness import isolated_registry
from tap_grid.constraints import (
    WILDCARD,
    _edge_property_schema_registry,
    _edge_type_registry,
    _node_registry,
    _parse_constraint_list,
    get_constraints,
    get_edge_property_schema,
    get_edge_type_constraints,
    register_constraints,
    register_edge_property_schema,
    register_edge_type_constraints,
    validate_edge,
    validate_edge_properties,
)
from tap_grid.exceptions import EdgePropertyValidationError, InvalidEdgeError


class TestParseConstraintList:
    """Test _parse_constraint_list function."""

    def test_parses_basic_constraint(self) -> None:
        constraints = [
            {
                "nodes": [{"type": "concept"}],
                "edges": [{"type": "APPLIES_TO"}],
            },
        ]
        result = _parse_constraint_list(constraints)
        assert result == {"APPLIES_TO": {"concept"}}

    def test_parses_multiple_nodes(self) -> None:
        constraints = [
            {
                "nodes": [{"type": "concept"}, {"type": "precept"}],
                "edges": [{"type": "APPLIES_TO"}],
            },
        ]
        result = _parse_constraint_list(constraints)
        assert result == {"APPLIES_TO": {"concept", "precept"}}

    def test_parses_multiple_edges(self) -> None:
        constraints = [
            {
                "nodes": [{"type": "concept"}],
                "edges": [{"type": "APPLIES_TO"}, {"type": "DEPENDS_ON"}],
            },
        ]
        result = _parse_constraint_list(constraints)
        assert result == {
            "APPLIES_TO": {"concept"},
            "DEPENDS_ON": {"concept"},
        }

    def test_parses_wildcard_when_nodes_absent(self) -> None:
        constraints = [
            {
                "edges": [{"type": "REFERENCES"}],
            },
        ]
        result = _parse_constraint_list(constraints)
        assert result["REFERENCES"] is WILDCARD

    def test_merges_nodes_for_same_edge_type(self) -> None:
        constraints = [
            {
                "nodes": [{"type": "concept"}],
                "edges": [{"type": "APPLIES_TO"}],
            },
            {
                "nodes": [{"type": "precept"}],
                "edges": [{"type": "APPLIES_TO"}],
            },
        ]
        result = _parse_constraint_list(constraints)
        assert result == {"APPLIES_TO": {"concept", "precept"}}

    def test_wildcard_takes_precedence(self) -> None:
        constraints = [
            {
                "nodes": [{"type": "concept"}],
                "edges": [{"type": "APPLIES_TO"}],
            },
            {
                # Wildcard for same edge type
                "edges": [{"type": "APPLIES_TO"}],
            },
        ]
        result = _parse_constraint_list(constraints)
        assert result["APPLIES_TO"] is WILDCARD


class TestRegisterConstraints:
    """Test register_constraints and get_constraints."""

    def test_registers_and_retrieves_constraints(self) -> None:
        register_constraints(
            "test_entity",
            outbound=[{"nodes": [{"type": "target"}], "edges": [{"type": "LINKS_TO"}]}],
            inbound=None,
        )
        constraints = get_constraints("test_entity")
        assert constraints is not None
        assert constraints.outbound == {"LINKS_TO": {"target"}}
        assert constraints.inbound is None

    def test_returns_none_for_unregistered(self) -> None:
        assert get_constraints("nonexistent_type") is None


class TestValidateEdge:
    """Test validate_edge function."""

    @pytest.fixture(autouse=True)
    def setup_constraints(self) -> None:
        """Register test constraints, restoring registry state after each test."""
        saved = _node_registry.all()
        # source_node: can only create VALID_EDGE to target_node
        register_constraints(
            "source_node",
            outbound=[{"nodes": [{"type": "target_node"}], "edges": [{"type": "VALID_EDGE"}]}],
            inbound=None,
        )
        # target_node: can only receive VALID_EDGE from source_node
        register_constraints(
            "target_node",
            outbound=None,
            inbound=[{"nodes": [{"type": "source_node"}], "edges": [{"type": "VALID_EDGE"}]}],
        )
        # blocked_node: cannot create any outbound edges
        register_constraints(
            "blocked_node",
            outbound=[],
            inbound=None,
        )
        # wildcard_node: can create WILD_EDGE to any node type
        register_constraints(
            "wildcard_node",
            outbound=[{"edges": [{"type": "WILD_EDGE"}]}],
            inbound=None,
        )
        yield
        _node_registry._reset_for_testing(saved)

    def test_valid_edge_passes(self) -> None:
        # Should not raise
        validate_edge("source_node", "target_node", "VALID_EDGE")

    def test_invalid_edge_type_raises(self) -> None:
        with pytest.raises(InvalidEdgeError) as exc_info:
            validate_edge("source_node", "target_node", "INVALID_EDGE")
        assert "cannot create 'INVALID_EDGE' edges" in str(exc_info.value)

    def test_invalid_target_raises(self) -> None:
        with pytest.raises(InvalidEdgeError) as exc_info:
            validate_edge("source_node", "wrong_target", "VALID_EDGE")
        assert "cannot create 'VALID_EDGE' edge to wrong_target" in str(exc_info.value)

    def test_blocked_outbound_raises(self) -> None:
        with pytest.raises(InvalidEdgeError) as exc_info:
            validate_edge("blocked_node", "target_node", "ANY_EDGE")
        assert "cannot create any outbound edges" in str(exc_info.value)

    def test_invalid_inbound_source_raises(self) -> None:
        with pytest.raises(InvalidEdgeError) as exc_info:
            validate_edge("wrong_source", "target_node", "VALID_EDGE")
        assert "cannot receive 'VALID_EDGE' edge from wrong_source" in str(exc_info.value)

    def test_wildcard_allows_any_target(self) -> None:
        # Should not raise for any target
        validate_edge("wildcard_node", "any_target", "WILD_EDGE")
        validate_edge("wildcard_node", "another_target", "WILD_EDGE")

    def test_unregistered_types_pass(self) -> None:
        # No constraints = no restrictions
        validate_edge("unregistered_from", "unregistered_to", "ANY_EDGE")


class TestRegisterEdgeTypeConstraints:
    """Test register_edge_type_constraints and get_edge_type_constraints."""

    def test_registers_basic_constraint(self) -> None:
        register_edge_type_constraints(
            "TEST_EDGE",
            sources=[{"type": "source_type"}],
            targets=[{"type": "target_type"}],
        )
        constraints = get_edge_type_constraints("TEST_EDGE")
        assert constraints is not None
        assert constraints.sources == {"source_type"}
        assert constraints.targets == {"target_type"}

    def test_registers_wildcard_source(self) -> None:
        register_edge_type_constraints(
            "WILD_SOURCE_EDGE",
            sources=None,  # Wildcard
            targets=[{"type": "target"}],
        )
        constraints = get_edge_type_constraints("WILD_SOURCE_EDGE")
        assert constraints is not None
        assert constraints.sources is WILDCARD
        assert constraints.targets == {"target"}

    def test_registers_wildcard_target(self) -> None:
        register_edge_type_constraints(
            "WILD_TARGET_EDGE",
            sources=[{"type": "source"}],
            targets=None,  # Wildcard
        )
        constraints = get_edge_type_constraints("WILD_TARGET_EDGE")
        assert constraints is not None
        assert constraints.sources == {"source"}
        assert constraints.targets is WILDCARD

    def test_registers_both_wildcards(self) -> None:
        register_edge_type_constraints(
            "FULLY_WILD_EDGE",
            sources=None,
            targets=None,
        )
        constraints = get_edge_type_constraints("FULLY_WILD_EDGE")
        assert constraints is not None
        assert constraints.sources is WILDCARD
        assert constraints.targets is WILDCARD

    def test_merges_multiple_registrations(self) -> None:
        register_edge_type_constraints(
            "MERGE_EDGE",
            sources=[{"type": "a"}],
            targets=[{"type": "x"}],
        )
        register_edge_type_constraints(
            "MERGE_EDGE",
            sources=[{"type": "b"}],
            targets=[{"type": "y"}],
        )
        constraints = get_edge_type_constraints("MERGE_EDGE")
        assert constraints is not None
        assert constraints.sources == {"a", "b"}
        assert constraints.targets == {"x", "y"}

    def test_wildcard_takes_precedence_in_merge(self) -> None:
        register_edge_type_constraints(
            "MERGE_WILD_EDGE",
            sources=[{"type": "a"}],
            targets=[{"type": "x"}],
        )
        register_edge_type_constraints(
            "MERGE_WILD_EDGE",
            sources=None,  # Wildcard overrides
            targets=[{"type": "y"}],
        )
        constraints = get_edge_type_constraints("MERGE_WILD_EDGE")
        assert constraints is not None
        assert constraints.sources is WILDCARD
        assert constraints.targets == {"x", "y"}

    def test_returns_none_for_unregistered(self) -> None:
        assert get_edge_type_constraints("NONEXISTENT_EDGE") is None


class TestValidateEdgeWithEdgeConstraints:
    """Test validate_edge with Permission Union (node OR edge constraints)."""

    @pytest.fixture(autouse=True)
    def setup_constraints(self) -> None:
        """Register node and edge constraints for testing, restoring state after each test."""
        saved_nodes = _node_registry.all()
        saved_edges = _edge_type_registry.all()
        # Node with specific outbound/inbound constraints
        register_constraints(
            "constrained_node",
            outbound=[{"nodes": [{"type": "allowed_target"}], "edges": [{"type": "NODE_ALLOWED"}]}],
            inbound=[{"nodes": [{"type": "allowed_source"}], "edges": [{"type": "NODE_ALLOWED"}]}],
        )
        # Node with explicit block (empty list)
        register_constraints(
            "blocked_outbound_node",
            outbound=[],
            inbound=None,
        )
        register_constraints(
            "blocked_inbound_node",
            outbound=None,
            inbound=[],
        )
        # Unconstrained node (no constraints registered)
        # (just don't register anything for "unconstrained_node")

        # Edge constraint that grants permission
        register_edge_type_constraints(
            "EDGE_ALLOWED",
            sources=[{"type": "constrained_node"}, {"type": "unconstrained_node"}],
            targets=[{"type": "constrained_node"}, {"type": "unconstrained_node"}],
        )
        # Edge constraint with wildcard source
        register_edge_type_constraints(
            "WILD_SOURCE",
            sources=None,  # Any source
            targets=[{"type": "specific_target"}],
        )
        # Edge constraint with wildcard target
        register_edge_type_constraints(
            "WILD_TARGET",
            sources=[{"type": "specific_source"}],
            targets=None,  # Any target
        )
        yield
        _node_registry._reset_for_testing(saved_nodes)
        _edge_type_registry._reset_for_testing(saved_edges)

    def test_node_constraint_alone_allows(self) -> None:
        """Node constraint allows edge, no edge constraint needed."""
        validate_edge("constrained_node", "allowed_target", "NODE_ALLOWED")

    def test_edge_constraint_alone_allows(self) -> None:
        """Edge constraint allows edge even when node doesn't list edge type."""
        # constrained_node doesn't have EDGE_ALLOWED in its OUTBOUND_EDGES
        # but edge constraint grants permission
        validate_edge("constrained_node", "unconstrained_node", "EDGE_ALLOWED")

    def test_edge_constraint_allows_unknown_edge_type(self) -> None:
        """Edge constraint allows edge type that node doesn't know about."""
        validate_edge("unconstrained_node", "unconstrained_node", "EDGE_ALLOWED")

    def test_node_explicit_block_overrides_edge_constraint(self) -> None:
        """Node's explicit block (OUTBOUND_EDGES=[]) cannot be overridden."""
        # Even though EDGE_ALLOWED allows blocked_outbound_node, the block wins
        with pytest.raises(InvalidEdgeError) as exc_info:
            validate_edge("blocked_outbound_node", "unconstrained_node", "EDGE_ALLOWED")
        assert "cannot create any outbound edges" in str(exc_info.value)

    def test_inbound_block_overrides_edge_constraint(self) -> None:
        """Node's explicit inbound block cannot be overridden."""
        with pytest.raises(InvalidEdgeError) as exc_info:
            validate_edge("unconstrained_node", "blocked_inbound_node", "EDGE_ALLOWED")
        assert "cannot receive any inbound edges" in str(exc_info.value)

    def test_edge_wildcard_source_allows_any_source(self) -> None:
        """Edge constraint with wildcard source allows any source type."""
        # specific_target must accept the edge (it's unconstrained)
        register_constraints("specific_target", outbound=None, inbound=None)
        validate_edge("random_source_1", "specific_target", "WILD_SOURCE")
        validate_edge("random_source_2", "specific_target", "WILD_SOURCE")

    def test_edge_wildcard_target_allows_any_target(self) -> None:
        """Edge constraint with wildcard target allows any target type."""
        register_constraints("specific_source", outbound=None, inbound=None)
        validate_edge("specific_source", "random_target_1", "WILD_TARGET")
        validate_edge("specific_source", "random_target_2", "WILD_TARGET")

    def test_neither_allows_fails(self) -> None:
        """When neither node nor edge constraints allow, validation fails."""
        with pytest.raises(InvalidEdgeError):
            validate_edge("constrained_node", "wrong_target", "UNKNOWN_EDGE")

    def test_permission_union_both_allow(self) -> None:
        """When both node and edge constraints allow, edge is valid."""
        # NODE_ALLOWED is allowed by node, and we'll also register edge constraint
        register_edge_type_constraints(
            "NODE_ALLOWED",
            sources=[{"type": "constrained_node"}],
            targets=[{"type": "allowed_target"}],
        )
        validate_edge("constrained_node", "allowed_target", "NODE_ALLOWED")


class TestEdgePropertySchemaRegistry:
    """req-grid-edge-properties: in-memory schema registry."""

    @pytest.fixture(autouse=True)
    def isolate_registry(self) -> None:
        """Snapshot and restore the property schema registry around each test."""
        with isolated_registry(_edge_property_schema_registry):
            yield

    def test_register_and_retrieve(self) -> None:
        """Registered schema is returned by get_edge_property_schema (properties-2)."""
        schema = {"type": "object", "properties": {"id": {"type": "string"}}}
        register_edge_property_schema("HAS_CONFIG", schema)
        assert get_edge_property_schema("HAS_CONFIG") == schema

    def test_missing_returns_none(self) -> None:
        """get_edge_property_schema returns None for unregistered edge type (properties-6)."""
        assert get_edge_property_schema("UNKNOWN_TYPE") is None

    def test_duplicate_registration_raises(self) -> None:
        """Registering a second schema for the same edge type raises ImproperlyConfigured (properties-3)."""
        schema = {"type": "object"}
        register_edge_property_schema("DOUBLE_REG", schema)
        with pytest.raises(ImproperlyConfigured, match="already registered"):
            register_edge_property_schema("DOUBLE_REG", {"type": "string"})

    def test_different_slugs_are_independent(self) -> None:
        """Each slug maintains its own schema."""
        schema_a = {"type": "object", "properties": {"a": {"type": "string"}}}
        schema_b = {"type": "object", "properties": {"b": {"type": "integer"}}}
        register_edge_property_schema("EDGE_A", schema_a)
        register_edge_property_schema("EDGE_B", schema_b)
        assert get_edge_property_schema("EDGE_A") == schema_a
        assert get_edge_property_schema("EDGE_B") == schema_b


class TestValidateEdgeProperties:
    """req-grid-edge-properties: validate_edge_properties behavior."""

    @pytest.fixture(autouse=True)
    def isolate_registry(self) -> None:
        """Snapshot and restore the property schema registry around each test."""
        with isolated_registry(_edge_property_schema_registry):
            yield

    def test_valid_properties_pass(self) -> None:
        """Properties matching the schema do not raise (properties-4)."""
        register_edge_property_schema(
            "TYPED_EDGE",
            {
                "type": "object",
                "required": ["label"],
                "properties": {"label": {"type": "string"}},
            },
        )
        validate_edge_properties("TYPED_EDGE", {"label": "hello"})

    def test_invalid_properties_raise(self) -> None:
        """Properties violating the schema raise EdgePropertyValidationError (properties-8)."""
        register_edge_property_schema(
            "STRICT_EDGE",
            {
                "type": "object",
                "required": ["count"],
                "properties": {"count": {"type": "integer"}},
            },
        )
        with pytest.raises(EdgePropertyValidationError):
            validate_edge_properties("STRICT_EDGE", {"count": "not-an-int"})

    def test_missing_required_field_raises(self) -> None:
        """Missing required field raises EdgePropertyValidationError."""
        register_edge_property_schema(
            "REQ_EDGE",
            {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}},
        )
        with pytest.raises(EdgePropertyValidationError):
            validate_edge_properties("REQ_EDGE", {})

    def test_no_schema_skips_validation(self) -> None:
        """Any payload is accepted when no schema is registered (properties-6, properties-7)."""
        # Should not raise even with unusual values
        validate_edge_properties("UNREGISTERED", {"anything": [1, None, True]})

    def test_schema_author_controls_strictness(self) -> None:
        """Without additionalProperties:false, extra fields are accepted (properties-9)."""
        register_edge_property_schema(
            "LENIENT_EDGE",
            {"type": "object", "properties": {"known": {"type": "string"}}},
        )
        # Extra field allowed because schema doesn't declare additionalProperties: false
        validate_edge_properties("LENIENT_EDGE", {"known": "hi", "extra": 42})

    def test_additional_properties_false_rejects_extra(self) -> None:
        """Schema with additionalProperties:false rejects extra fields (properties-9)."""
        register_edge_property_schema(
            "STRICT_EXTRA_EDGE",
            {
                "type": "object",
                "properties": {"known": {"type": "string"}},
                "additionalProperties": False,
            },
        )
        with pytest.raises(EdgePropertyValidationError):
            validate_edge_properties("STRICT_EXTRA_EDGE", {"known": "hi", "extra": 42})


class TestEdgePropertyLanes:
    """req-grid-edge-schema-required: the two-lane model — system-owned keys
    validate centrally via their owning machinery; the remainder demands a
    per-type schema (warn mode on 0.1.x, fail-closed from 0.2.0)."""

    @pytest.fixture(autouse=True)
    def isolate_registry(self) -> Iterator[None]:
        """Snapshot and restore the property schema registry around each test."""
        with isolated_registry(_edge_property_schema_registry):
            yield

    _HOTLINK = {"model": "layout", "spec": "layout-arrangements", "value": "some-id"}

    def test_hotlink_only_on_schemaless_type_is_silent(self, caplog) -> None:
        """A hotlink-only payload needs no type schema and produces no warning (required-5)."""
        import logging

        with caplog.at_level(logging.WARNING, logger="tap_grid.constraints"):
            validate_edge_properties("BARE_EDGE", {"hotlink": dict(self._HOTLINK)})
        assert not [r for r in caplog.records if "[d393]" in r.getMessage()]

    def test_schemaless_type_with_net_properties_warns(self, caplog) -> None:
        """Warn mode (0.1.x): non-system properties without a schema log, not raise (required-1)."""
        import logging

        with caplog.at_level(logging.WARNING, logger="tap_grid.constraints"):
            validate_edge_properties("BARE_EDGE", {"free": "form"})
        warnings = [r.getMessage() for r in caplog.records if "[d393]" in r.getMessage()]
        assert warnings and "BARE_EDGE" in warnings[0] and "req-grid-edge-schema-required-1" in warnings[0]

    def test_enforce_flip_raises(self, monkeypatch) -> None:
        """The 0.2.0 posture: same input fails closed once the flip lands (required-1/-3)."""
        from tap_grid import constraints as c

        monkeypatch.setattr(c, "ENFORCE_EDGE_SCHEMA_REQUIRED", True)
        with pytest.raises(EdgePropertyValidationError, match="req-grid-edge-schema-required-1"):
            validate_edge_properties("BARE_EDGE", {"free": "form"})

    def test_malformed_hotlink_payload_rejected_any_type(self) -> None:
        """The system lane validates hotlink shape centrally, schema or not (required-5)."""
        with pytest.raises(EdgePropertyValidationError, match="hotlink payload"):
            validate_edge_properties("BARE_EDGE", {"hotlink": {"model": "layout"}})

    def test_schema_never_sees_system_keys(self) -> None:
        """A strict (additionalProperties: false) type schema coexists with hotlink (required-5)."""
        register_edge_property_schema(
            "STRICT_EDGE",
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"label": {"type": "string"}},
            },
        )
        validate_edge_properties("STRICT_EDGE", {"label": "ok", "hotlink": dict(self._HOTLINK)})

    def test_registration_rejects_system_key_redeclaration(self) -> None:
        """Per-type schemas may not redeclare system-owned keys (required-5)."""
        with pytest.raises(ImproperlyConfigured, match="system-owned"):
            register_edge_property_schema(
                "GREEDY_EDGE",
                {"type": "object", "properties": {"hotlink": {"type": "object"}}},
            )

    def test_empty_properties_always_legal(self, caplog) -> None:
        """Schema-less types stay fully usable with empty properties (required-2)."""
        import logging

        with caplog.at_level(logging.WARNING, logger="tap_grid.constraints"):
            validate_edge_properties("BARE_EDGE", {})
            validate_edge_properties("BARE_EDGE", None)
        assert not [r for r in caplog.records if "[d393]" in r.getMessage()]
