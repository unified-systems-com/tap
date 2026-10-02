"""Edge identity declarations: the shape, the registry, and every core edge type declaring one.

Spec: ``req-grid-edge-identity-declaration`` and ``req-grid-edge-identity-7`` in
``tap_grid/specs/spec-grid-edge.md``; ``req-grid-edge-produced-batch-claims-1``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured

from tap_grid.core_edges import CORE_EDGE_TYPES
from tap_grid.edge_identity import (
    Discriminator,
    EdgeIdentity,
    _edge_identity_registry,
    get_edge_identity,
    parse_edge_identity,
    register_edge_identity,
)
from tap_plugins.base import TapPluginConfig

SPEC_1 = pytest.mark.spec("req-grid-edge-identity-declaration-1")
SPEC_2 = pytest.mark.spec("req-grid-edge-identity-declaration-2")
SPEC_3 = pytest.mark.spec("req-grid-edge-identity-declaration-3")
SPEC_4 = pytest.mark.spec("req-grid-edge-identity-declaration-4")
SPEC_6 = pytest.mark.spec("req-grid-edge-identity-declaration-6")
SPEC_7 = pytest.mark.spec("req-grid-edge-identity-declaration-7")
CORE_DECLARE = pytest.mark.spec("req-grid-edge-identity-7")
PRODUCED_BATCH_PLAIN = pytest.mark.spec("req-grid-edge-produced-batch-claims-1")
MANIFEST_ONCE = pytest.mark.spec("req-tap-plugin-manifest-v0-edge-identity-3")

SCOPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scope": {"type": "string"},
        "rule": {"type": "object", "properties": {"type": {"type": "string"}}},
        "opaque": {"type": "object"},
    },
}
SCOPE = {
    "path": "scope",
    "description": "The dependency scope as the manifest states it; in the key because two can hold at once.",
}


@pytest.fixture
def clean_registry() -> Iterator[None]:
    """Leave the process-wide registry exactly as it was: tests register throwaway slugs."""
    before = _edge_identity_registry.all()
    yield
    _edge_identity_registry._reset_for_testing(before)


class TestTheShape:
    @SPEC_1
    def test_an_empty_list_is_the_plain_key(self) -> None:
        identity = parse_edge_identity("T", {"discriminators": []})
        assert identity == EdgeIdentity()
        assert not identity.keyless and identity.paths == ()

    @SPEC_1
    @pytest.mark.parametrize(
        "raw",
        [
            {},
            {"discriminators": [], "keyless": {"reason": "both"}},
            {"discriminators": [], "unique": True},
            {"keyed": []},
            [],
            "plain",
            None,
        ],
    )
    def test_exactly_one_of_discriminators_and_keyless(self, raw: Any) -> None:
        with pytest.raises(ImproperlyConfigured):
            parse_edge_identity("T", raw)

    @SPEC_2
    def test_a_discriminator_is_an_object_with_a_path_and_a_description(self) -> None:
        identity = parse_edge_identity("T", {"discriminators": [SCOPE]}, property_schema=SCOPE_SCHEMA)
        assert identity.discriminators == (Discriminator(path="scope", description=SCOPE["description"]),)
        assert identity.paths == ("scope",)

    @SPEC_2
    @pytest.mark.parametrize(
        "entry",
        [
            "scope",
            {"path": "scope"},
            {"path": "scope", "description": ""},
            {"path": "scope", "description": "   "},
            {"path": "", "description": "x"},
            {"path": "scope", "description": "x", "volatile": False},
        ],
    )
    def test_a_bare_string_or_a_missing_description_is_refused(self, entry: Any) -> None:
        with pytest.raises(ImproperlyConfigured):
            parse_edge_identity("T", {"discriminators": [entry]}, property_schema=SCOPE_SCHEMA)

    @SPEC_2
    def test_two_discriminators_cannot_share_a_path(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="declared twice"):
            parse_edge_identity("T", {"discriminators": [SCOPE, SCOPE]}, property_schema=SCOPE_SCHEMA)

    @SPEC_2
    @pytest.mark.parametrize("path", ["scope.", "rule..type", "rule.0"])
    def test_a_path_obeys_the_natural_key_grammar(self, path: str) -> None:
        """One parser for edge and node paths: an empty segment or an all-digit key is refused."""
        entry = {"path": path, "description": "x"}
        with pytest.raises(ImproperlyConfigured):
            parse_edge_identity("T", {"discriminators": [entry]}, property_schema=SCOPE_SCHEMA)

    @SPEC_6
    def test_keyless_says_why(self) -> None:
        identity = parse_edge_identity("T", {"keyless": {"reason": "records an act of this grid"}})
        assert identity.keyless and identity.keyless_reason == "records an act of this grid"

    @SPEC_6
    @pytest.mark.parametrize("keyless", [{}, {"reason": ""}, {"reason": "  "}, {"reason": "x", "why": "y"}, "because"])
    def test_keyless_without_a_reason_is_refused(self, keyless: Any) -> None:
        with pytest.raises(ImproperlyConfigured):
            parse_edge_identity("T", {"keyless": keyless})


class TestResolvesThroughThePropertySchema:
    @SPEC_3
    def test_a_nested_path_resolves_level_by_level(self) -> None:
        entry = {"path": "rule.type", "description": "x"}
        assert parse_edge_identity("T", {"discriminators": [entry]}, property_schema=SCOPE_SCHEMA).paths == (
            "rule.type",
        )

    @SPEC_3
    def test_a_level_that_says_nothing_further_is_not_a_failure(self) -> None:
        entry = {"path": "opaque.anything", "description": "x"}
        assert parse_edge_identity("T", {"discriminators": [entry]}, property_schema=SCOPE_SCHEMA).paths == (
            "opaque.anything",
        )

    @SPEC_3
    @pytest.mark.parametrize("path", ["missing", "rule.kind"])
    def test_a_path_the_schema_does_not_declare_is_refused(self, path: str) -> None:
        with pytest.raises(ImproperlyConfigured, match="not among the schema's properties"):
            parse_edge_identity(
                "T", {"discriminators": [{"path": path, "description": "x"}]}, property_schema=SCOPE_SCHEMA
            )

    @SPEC_3
    def test_discriminators_without_a_property_schema_are_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="needs a property_schema"):
            parse_edge_identity("T", {"discriminators": [SCOPE]}, property_schema=None)

    @SPEC_3
    def test_a_schema_with_no_properties_cannot_hold_a_discriminator(self) -> None:
        with pytest.raises(ImproperlyConfigured, match="declares no properties"):
            parse_edge_identity("T", {"discriminators": [SCOPE]}, property_schema={"type": "object"})

    @SPEC_3
    def test_the_plain_key_needs_no_property_schema(self) -> None:
        assert parse_edge_identity("T", {"discriminators": []}, property_schema=None) == EdgeIdentity()


@pytest.mark.usefixtures("clean_registry")
class TestTheRegistry:
    @SPEC_4
    @MANIFEST_ONCE
    def test_a_second_declaration_for_one_type_is_a_configuration_error(self) -> None:
        register_edge_identity("TEST_IDENTITY_ONCE", {"discriminators": []})
        with pytest.raises(ImproperlyConfigured):
            register_edge_identity("TEST_IDENTITY_ONCE", {"keyless": {"reason": "a different opinion"}})
        assert get_edge_identity("TEST_IDENTITY_ONCE") == EdgeIdentity()

    @SPEC_4
    def test_an_identical_second_declaration_is_still_refused(self) -> None:
        """No merge, and no special case for agreement either: one home per declaration."""
        register_edge_identity("TEST_IDENTITY_TWICE", {"discriminators": []})
        with pytest.raises(ImproperlyConfigured):
            register_edge_identity("TEST_IDENTITY_TWICE", {"discriminators": []})

    @SPEC_7
    def test_the_registered_value_is_what_every_consumer_reads(self) -> None:
        registered = register_edge_identity(
            "TEST_IDENTITY_READ", {"discriminators": [SCOPE]}, property_schema=SCOPE_SCHEMA
        )
        assert get_edge_identity("TEST_IDENTITY_READ") is registered

    @SPEC_7
    def test_an_undeclared_type_reads_as_none_not_as_plain(self) -> None:
        """Three states, never two: undeclared is neither plain nor keyless."""
        assert get_edge_identity("TEST_IDENTITY_NEVER_DECLARED") is None

    @SPEC_3
    def test_without_an_explicit_schema_the_registered_one_is_used(self) -> None:
        from tap_grid.constraints import _edge_property_schema_registry, register_edge_property_schema

        schemas_before = _edge_property_schema_registry.all()
        try:
            register_edge_property_schema("TEST_IDENTITY_SCHEMA", SCOPE_SCHEMA)
            assert register_edge_identity("TEST_IDENTITY_SCHEMA", {"discriminators": [SCOPE]}).paths == ("scope",)
        finally:
            _edge_property_schema_registry._reset_for_testing(schemas_before)


def _core_edge_slugs() -> set[str]:
    """Every edge type a core app defines: the grid-standard edges plus each first-party app's
    ``edge_types`` list. Plugins (TapPluginConfig subclasses) declare theirs in .edge.json files
    and are not core."""
    slugs = set(CORE_EDGE_TYPES)
    for config in apps.get_app_configs():
        if isinstance(config, TapPluginConfig):
            continue
        for entry in getattr(config, "edge_types", ()) or ():
            slugs.add(entry["slug"])
    return slugs


class TestCoreTypesDeclare:
    @CORE_DECLARE
    def test_every_core_edge_type_declares_its_identity(self) -> None:
        slugs = _core_edge_slugs()
        undeclared = sorted(slug for slug in slugs if get_edge_identity(slug) is None)
        assert undeclared == [], f"core edge types without an identity declaration: {undeclared}"

    @CORE_DECLARE
    def test_the_census_of_core_types_is_what_the_guard_walks(self) -> None:
        """A guard that walks nothing passes everything: pin that it sees the four core homes."""
        slugs = _core_edge_slugs()
        for expected in ("PRODUCED_BATCH", "USES_PANEL", "SCHEDULED_TARGET", "USES_PROJECTION"):
            assert expected in slugs

    @CORE_DECLARE
    def test_the_lifecycle_edges_are_keyless_and_the_standing_ones_plain(self) -> None:
        keyless = {"HAS_COLLECTION_JOB", "HAS_FIRED", "TRIGGERED_JOB"}
        for slug in _core_edge_slugs():
            identity = get_edge_identity(slug)
            assert identity is not None
            assert identity.keyless is (slug in keyless), slug
            if not identity.keyless:
                assert identity.paths == (), f"{slug} declares discriminators; no core type has any today"

    @PRODUCED_BATCH_PLAIN
    def test_produced_batch_is_a_plain_key(self) -> None:
        assert get_edge_identity("PRODUCED_BATCH") == EdgeIdentity()
