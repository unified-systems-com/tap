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


class TestEveryCoreTypeHasDeclared:
    """The guard that makes the declaration contract real (phase 1.3).

    Three states, not two: a type that simply never declared must not be read as
    deliberately keyless. `None` reds this test, so a new core model has to say which
    it is — which is the whole point of having a sentinel rather than using `None`
    for both.
    """

    CORE_PREFIXES = ("tap_grid.", "tap_web.", "tap_viz.", "tap_cares.", "tap_api.", "tap_boot.", "tap_ai.", "tap.")

    def _core_models(self) -> list[tuple[str, type]]:
        from tap_grid.registry import get_model_class, list_entity_types

        out = []
        for entity_type in sorted(list_entity_types()):
            try:
                model = get_model_class(entity_type)
            except Exception:  # pragma: no cover - a registry miss is its own test
                continue
            module = getattr(model, "__module__", "")
            # Test fixtures register throwaway types; they are not core vocabulary.
            if ".tests." in module or module.endswith(".tests"):
                continue
            if module.startswith(self.CORE_PREFIXES):
                out.append((entity_type, model))
        return out

    def test_core_models_exist_to_check(self) -> None:
        """Guard the guard: a filter that matches nothing passes silently."""
        assert len(self._core_models()) >= 15

    def test_no_core_type_is_undeclared(self) -> None:
        undeclared = [t for t, m in self._core_models() if getattr(m, "NATURAL_KEY", None) is None]
        assert undeclared == [], (
            f"These core entity types have not declared a natural key: {undeclared}. "
            "Declare the constituting properties as a tuple, or KEYLESS with a "
            "NATURAL_KEY_REASON saying why there is no source object. `None` is "
            "'nobody decided', which is not an answer (req-grid-entity-natural-key)."
        )

    def test_keyless_types_say_why(self) -> None:
        silent = [
            t
            for t, m in self._core_models()
            if isinstance(m.NATURAL_KEY, Keyless) and not getattr(m, "NATURAL_KEY_REASON", "").strip()
        ]
        assert silent == [], f"KEYLESS without a reason: {silent}"

    def test_keyed_properties_exist_on_the_model(self) -> None:
        """A constituting property that does not exist is a citation that does not
        resolve — it would read as a declaration while deriving nothing."""
        broken: list[str] = []
        for entity_type, model in self._core_models():
            declared = model.NATURAL_KEY
            if isinstance(declared, Keyless):
                continue
            field_names = {f.name for f in model._meta.get_fields() if getattr(f, "concrete", False)}
            for prop in declared:
                if prop not in field_names:
                    broken.append(f"{entity_type}.{prop}")
        assert broken == [], f"Declared constituting properties that are not model fields: {broken}"

    def test_keyed_types_are_the_expected_two(self) -> None:
        """Core is almost entirely keyless, and that is the finding, not an accident:
        core is furniture. It authors its own objects, so their identity arrives in a
        GRIFT declaration rather than needing to be recognised. The natural-key
        machinery's real consumers are the collectors in the plugins."""
        keyed = {t for t, m in self._core_models() if not isinstance(m.NATURAL_KEY, Keyless)}
        assert keyed == {"page", "panel"}, (
            f"Expected only page and panel to be keyed in core; got {sorted(keyed)}. "
            "If a new core type is genuinely observed rather than authored, update "
            "this test deliberately and say why in the commit."
        )


class TestOnlyOneDerivation:
    """req-grid-entity-natural-key-2 depends on there being exactly one derivation.

    The precise invariant is not "nobody calls uuid5" — plenty of code legitimately
    does, for boot-record digests and for a collector's own registry id. It is that
    **nobody else can reach the natural-key namespace**, because without it you
    cannot produce a key that would collide with a real one. Guarding the namespace
    rather than the primitive is what makes this a correctness test instead of a
    style test.
    """

    ALLOWED = {"tap_grid/natural_key.py", "tap_grid/tests/test_natural_key.py"}

    def _repo_root(self):
        from pathlib import Path

        import tap_grid

        return Path(tap_grid.__file__).resolve().parent.parent

    def _referencing_files(self) -> set[str]:
        root = self._repo_root()
        app_dirs = (
            "tap_grid",
            "tap_web",
            "tap_viz",
            "tap_api",
            "tap_boot",
            "tap_ai",
            "tap_cares",
            "tap_plugins",
            "tap",
        )
        hits: set[str] = set()
        for app in app_dirs:
            base = root / app
            if not base.is_dir():
                continue
            for path in base.rglob("*.py"):
                try:
                    if "TAP_NATURAL_KEY_NAMESPACE" in path.read_text(encoding="utf-8"):
                        hits.add(str(path.relative_to(root)))
                except OSError:  # pragma: no cover
                    continue
        return hits

    def test_scan_found_the_module_itself(self) -> None:
        """Guard the guard: a scan that reads nothing passes silently."""
        assert "tap_grid/natural_key.py" in self._referencing_files()

    def test_no_second_site_reaches_the_namespace(self) -> None:
        extra = sorted(self._referencing_files() - self.ALLOWED)
        assert extra == [], (
            f"These files reference TAP_NATURAL_KEY_NAMESPACE: {extra}. A natural key has "
            "exactly one derivation (req-grid-entity-natural-key-2); a second site could "
            "mint a colliding key and would drift from the first the moment a recipe "
            "changed. Call tap_grid.natural_key.natural_key() instead."
        )


class TestGriftImportRefusesASuppliedKey:
    """req-grid-entity-natural-key-2: a collector cannot supply or override a key.

    This is enforced by OMISSION — the GRIFT entity envelope is
    `additionalProperties: false` and simply does not declare `natural_key`, so a
    document carrying one is refused by the schema. That is a load-bearing absence,
    which is exactly the kind that gets "helpfully" added later by someone making
    export and import symmetric. This test is what makes removing it loud.
    """

    @pytest.mark.django_db
    def test_a_supplied_natural_key_is_refused(self) -> None:
        # Reuse test_grift's document helpers rather than restating the envelope
        # shape here. Hand-building it failed twice on required keys I had not
        # copied (`batch_node`, then `edges`) — which is the derive-twice problem
        # in miniature: a second copy of a schema shape drifts from the first.
        from tap_grid.grift import grift_import
        from tap_grid.tests.test_grift import _batch_container, _character_node, _minimal_doc

        node = _character_node("01a00000-0000-7000-8000-00000000beef", name="Smuggler")
        node["entity"]["natural_key"] = "01a00000-0000-5000-8000-00000000dead"  # the whole point
        doc = _minimal_doc([_batch_container("01a00000-0000-7000-8000-00000000c0de", nodes=[node])])

        result = grift_import(doc)
        assert not result.success, "the envelope must refuse a supplied natural_key"
        assert any(
            "natural_key" in e.message for e in result.errors
        ), f"refused, but not for the right reason: {[e.message for e in result.errors]}"
