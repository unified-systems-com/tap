"""Core's own serialization and query-plan surface (tap#487).

These pin what CORE owns, in core, so a change to it reds a core test in the same PR
that makes it — rather than surfacing as a mass failure in a separately released
plugin's oracle corpus.

Why this file exists. `tap-plugin-gryphon-playground`'s gridkin corpus pins 152
response envelopes and 152 compiled-SQL texts. Both are core contracts: the envelope's
top level is `Entity.SPINE_FIELD_NAMES`, and the SQL's column lists are whatever
columns the models declare. So adding one column to `Entity` invalidated ~304
expectations in another repo, forcing a plugin regeneration, a plugin release and a
boot-record pin bump to land a core change (observed on tap#480).

The corpus is not wrong to notice — catching envelope and query-plan change is its
purpose. The problem is ownership: core could not see its own change until a plugin
told it. These tests give core that visibility. The corresponding plugin-side change
— normalizing the core-owned regions instead of pinning them verbatim, so the corpus
keeps asserting query SEMANTICS — is the other half of tap#487.
"""

from __future__ import annotations

import pytest

from tap_grid.models import Edge, Entity

pytestmark = pytest.mark.django_db


# The exact columns, in order, that Django selects for these tables. Pinned rather
# than derived on purpose: deriving them would assert nothing. A column added,
# removed or reordered MUST red this test, because that is a change to the compiled
# SQL of every query touching the table — including every scenario in the gridkin
# corpus.
EXPECTED_ENTITY_COLUMNS = [
    "id",
    "entity_type",
    "name",
    "dimensions",
    "originating_grid_id",
    "version",
    "deleted_at",
    "created_at",
    "updated_at",
]

# The exact top-level keys of a response envelope, in canonical serialization order.
# Pinned as a LITERAL for the same reason as the column lists: comparing the emitted
# surface against SPINE_FIELD_NAMES only catches EMISSION drifting from DECLARATION —
# when both move together (which is what adding a spine field does) they still agree,
# and the test passes while every consumer's envelope has changed. Found by running
# tap#480's diff against an earlier version of this file as a positive control: 1 of 5
# tests failed, and this was the gap.
EXPECTED_SPINE_SURFACE = [
    "entity_id",
    "entity_type",
    "name",
    "dimensions",
    "created_at",
    "updated_at",
    "deleted_at",
    "version",
    "originating_grid_id",
]

EXPECTED_EDGE_COLUMNS = [
    "id",
    "entity_id",
    "batch_id",
    "flip_map",
    "from_entity_id",
    "to_entity_id",
    "edge_type",
    "properties",
]

_WHEN_THIS_REDS = (
    "\n\nIf you meant to change this table's columns: update the list in this file in "
    "the SAME commit, and know what else moves. The compiled SQL of every query "
    "touching this table changes, which includes every scenario in the gridkin corpus "
    "(tap-plugin-gryphon-playground). Until the plugin-side half of tap#487 lands, "
    "that means a corpus regeneration, a plugin release and a boot-record pin bump — "
    "so plan the change as coordinated work, not a one-line migration."
)


class TestCompiledColumnLists:
    """The query-plan half. `SPINE_FIELD_NAMES` has nothing to do with this — Django
    selects every concrete column, so this reflects the TABLE. That is why no
    declaration in core could route around the SQL half of tap#480's failure."""

    def test_entity_columns_are_exactly_as_pinned(self) -> None:
        actual = [f.column for f in Entity._meta.concrete_fields]
        assert actual == EXPECTED_ENTITY_COLUMNS, (
            f"Entity's selected columns changed.\n  expected: {EXPECTED_ENTITY_COLUMNS}\n"
            f"  actual:   {actual}" + _WHEN_THIS_REDS
        )

    def test_edge_columns_are_exactly_as_pinned(self) -> None:
        actual = [f.column for f in Edge._meta.concrete_fields]
        assert actual == EXPECTED_EDGE_COLUMNS, (
            f"Edge's selected columns changed.\n  expected: {EXPECTED_EDGE_COLUMNS}\n"
            f"  actual:   {actual}" + _WHEN_THIS_REDS
        )

    def test_entity_column_list_reaches_the_compiled_sql(self) -> None:
        """Guard the guard: the pinned list is only meaningful if it is what Django
        actually emits. Without this the two could drift and both look fine."""
        sql = str(Entity.objects.all().query)
        for column in EXPECTED_ENTITY_COLUMNS:
            assert f'"{column}"' in sql, f"pinned column {column!r} absent from the compiled SQL: {sql[:300]}"


class TestSpineSurfaceIsExact:
    """The envelope half.

    `test_grift_subgraph.py` already checks every canonical field is PRESENT
    (`assert key in spine`) — a subset test, which an extra key passes. That is
    presence-standing-in-for-correctness, and it is why core did not notice that
    adding a spine field changed every response envelope.
    """

    def _spine(self):
        from tap_grid.grift.subgraph import build_spine_surface
        from tap_grid.services import create_node

        result = create_node("grid_fixtures__constrained_source", {"name": "Contract", "description": "Pinned."})
        assert result.success, f"fixture setup failed: {result.errors}"
        return build_spine_surface(Entity.objects.get(pk=result.entity_id))

    def test_surface_keys_are_exactly_the_canonical_tuple(self) -> None:
        spine = self._spine()
        assert tuple(spine.keys()) == Entity.SPINE_FIELD_NAMES, (
            "the response envelope's spine surface no longer matches "
            "Entity.SPINE_FIELD_NAMES exactly.\n"
            f"  declared: {Entity.SPINE_FIELD_NAMES}\n  emitted:  {tuple(spine.keys())}"
            "\n\nOrder matters: the tuple is the canonical SERIALIZATION order per "
            "spec-grid-entity § Canonical Spine Surface." + _WHEN_THIS_REDS
        )

    def test_surface_matches_the_pinned_literal(self) -> None:
        """The one that catches an envelope CHANGE.

        The test above compares emission to declaration, so a field added to both
        passes it. This compares emission to a literal, so adding a spine field reds
        here — in core, in the same PR — instead of surfacing as ~304 failures in a
        separately released plugin's corpus.
        """
        spine = self._spine()
        assert list(spine.keys()) == EXPECTED_SPINE_SURFACE, (
            "the response envelope's top-level shape changed.\n"
            f"  pinned:  {EXPECTED_SPINE_SURFACE}\n  emitted: {list(spine.keys())}" + _WHEN_THIS_REDS
        )

    def test_no_extra_key_can_slip_in(self) -> None:
        """States the failure the subset check could not catch, as its own test."""
        spine = self._spine()
        extra = sorted(set(spine) - set(Entity.SPINE_FIELD_NAMES))
        assert extra == [], f"spine surface emitted undeclared key(s): {extra}" + _WHEN_THIS_REDS
