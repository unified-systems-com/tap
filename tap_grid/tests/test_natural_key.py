"""The natural-key derivation (``req-grid-entity-natural-key``).

These test the derivation in isolation — no database, no models. The guard asserting
that every registered entity type has DECLARED a key or declared itself keyless comes
with the type classifications, not here.
"""

from __future__ import annotations

import json
import uuid

import pytest

from tap_grid.natural_key import (
    KEYLESS,
    TAP_NATURAL_KEY_NAMESPACE,
    Keyless,
    NaturalKeyError,
    canonicalize,
    key_document,
    natural_key,
)


class TestDeterminism:
    def test_same_inputs_same_key(self) -> None:
        a = natural_key("x__thing", {"stable_id": "12345", "forge": "github.com"})
        b = natural_key("x__thing", {"stable_id": "12345", "forge": "github.com"})
        assert a == b is not None

    def test_property_order_does_not_matter(self) -> None:
        """Canonicalization is what makes the key independent of dict order."""
        a = natural_key("x__thing", {"forge": "github.com", "stable_id": "12345"})
        b = natural_key("x__thing", {"stable_id": "12345", "forge": "github.com"})
        assert a == b

    def test_key_is_reproducible_by_hand(self) -> None:
        """Anyone holding the document can recompute the key — that IS the contract."""
        doc = {"type": "x__thing", "stable_id": "12345"}
        expected = uuid.uuid5(TAP_NATURAL_KEY_NAMESPACE, json.dumps(doc, sort_keys=True, separators=(",", ":")))
        assert natural_key("x__thing", {"stable_id": "12345"}) == expected


class TestTypeIsInTheDocument:
    def test_two_types_same_values_differ(self) -> None:
        """req-grid-entity-natural-key-4: the type is a member, not a namespace."""
        a = natural_key("git_core__git_repository", {"stable_id": "1"})
        b = natural_key("github_core__github_repository", {"stable_id": "1"})
        assert a != b

    def test_type_appears_in_the_document(self) -> None:
        doc = key_document("x__thing", {"stable_id": "1"})
        assert doc is not None
        assert doc["type"] == "x__thing"


class TestDimensionInvariance:
    def test_nothing_outside_the_document_can_move_the_key(self) -> None:
        """req-grid-entity-natural-key-3: invariance is what makes correlation work.

        There is no dimensions parameter to pass — the derivation cannot see them.
        This test states that as an executable claim rather than a comment.
        """
        assert natural_key.__code__.co_varnames[: natural_key.__code__.co_argcount] == (
            "entity_type",
            "properties",
        )


class TestAbsentValuesYieldNoKey:
    @pytest.mark.parametrize("missing", [None, ""])
    def test_absent_constituting_value_is_no_key_not_an_error(self, missing: object) -> None:
        """A repository whose payload carried no stable id genuinely cannot be
        correlated. The honest record is a null key, never a key over a hole."""
        assert key_document("x__thing", {"stable_id": missing}) is None
        assert natural_key("x__thing", {"stable_id": missing}) is None

    def test_one_absent_value_voids_the_whole_key(self) -> None:
        assert natural_key("x__thing", {"forge": "github.com", "stable_id": None}) is None


class TestValueDomain:
    """The constraint canonicalize() rests on. Ruled 2026-09-15: restrict the domain
    rather than take a JCS dependency."""

    def test_str_and_int_are_permitted(self) -> None:
        assert natural_key("x__thing", {"a": "s", "b": 7}) is not None

    def test_float_is_refused(self) -> None:
        with pytest.raises(NaturalKeyError, match="float"):
            natural_key("x__thing", {"ratio": 1.5})

    def test_bool_is_refused_before_int(self) -> None:
        """bool is an int subclass in Python, so an isinstance(int) test admits it
        silently and True would canonicalize differently from 1."""
        with pytest.raises(NaturalKeyError, match="bool"):
            natural_key("x__thing", {"flag": True})

    @pytest.mark.parametrize("bad", [[1], {"k": "v"}, (1,), uuid.uuid4(), 1.0])
    def test_other_types_are_refused(self, bad: object) -> None:
        with pytest.raises(NaturalKeyError):
            natural_key("x__thing", {"prop": bad})

    def test_non_ascii_property_name_is_refused(self) -> None:
        """Key ordering is where this canonical form could diverge from JCS."""
        with pytest.raises(NaturalKeyError, match="ASCII"):
            natural_key("x__thing", {"nàme": "v"})

    def test_non_ascii_VALUE_is_fine(self) -> None:
        """Only key ordering diverges; string values serialize identically."""
        assert natural_key("x__thing", {"name": "café"}) is not None


class TestCanonicalForm:
    def test_compact_and_sorted(self) -> None:
        assert canonicalize({"b": 2, "a": 1}) == '{"a":1,"b":2}'

    def test_unicode_is_not_escaped(self) -> None:
        assert canonicalize({"a": "café"}) == '{"a":"café"}'


class TestKeylessSentinel:
    def test_keyless_is_not_none_and_not_a_tuple(self) -> None:
        """Three states, not two: undeclared (None) must stay distinguishable from
        deliberately keyless (KEYLESS)."""
        assert KEYLESS is not None
        assert not isinstance(KEYLESS, tuple)
        assert isinstance(KEYLESS, Keyless)

    def test_keyless_is_falsy_safe(self) -> None:
        """A truthiness test must not silently treat KEYLESS as 'no declaration'."""
        assert bool(KEYLESS) is True
