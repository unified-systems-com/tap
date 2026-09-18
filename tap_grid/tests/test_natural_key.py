"""The identity declaration and the placeholder column (``req-grid-entity-natural-key``).

Phase 2 ("Cascade First", 2026-09-17) withdrew the hashed key. What remains to test is
the declaration contract on every core model — three states, not two — the placeholder
column's shape, the guard that nothing reads or writes it yet, and the load-bearing
absence that keeps a collector from supplying one.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from django.db import models as django_models

from tap_grid.natural_key import KEYLESS, Keyless

if TYPE_CHECKING:
    from pathlib import Path

    from tap_grid.models import BaseModel


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
    """The guard that makes the declaration contract real (req-grid-entity-natural-key-5).

    Three states, not two: a type that simply never declared must not be read as
    deliberately keyless. `None` reds this test, so a new core model has to say which
    it is — which is the whole point of having a sentinel rather than using `None`
    for both.
    """

    CORE_PREFIXES = ("tap_grid.", "tap_web.", "tap_viz.", "tap_cares.", "tap_api.", "tap_boot.", "tap_ai.", "tap.")

    def _core_models(self) -> list[tuple[str, type[BaseModel]]]:
        from tap_grid.models import BaseModel
        from tap_grid.registry import get_model_class, list_entity_types

        out: list[tuple[str, type[BaseModel]]] = []
        for entity_type in sorted(list_entity_types()):
            # get_model_class raises only for an unregistered type, and these came
            # from list_entity_types(); a swallowed exception here would let a type
            # drop out of the guard silently.
            model = get_model_class(entity_type)
            # The registry returns a bare `type`; every registered entity type is a
            # BaseModel, and saying so here is what lets NATURAL_KEY be checked at all.
            assert issubclass(model, BaseModel), f"{entity_type} is registered but is not a BaseModel"
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
        resolve — it would read as a declaration while finding nothing."""
        broken: list[str] = []
        for entity_type, model in self._core_models():
            declared = model.NATURAL_KEY
            # Undeclared (None) is its own failure, reported by the declaration test above.
            if declared is None or isinstance(declared, Keyless):
                continue
            field_names = {f.name for f in model._meta.get_fields() if getattr(f, "concrete", False)}
            for prop in declared:
                if prop not in field_names:
                    broken.append(f"{entity_type}.{prop}")
        assert broken == [], f"Declared constituting properties that are not model fields: {broken}"

    def test_keyed_types_are_the_expected_two(self) -> None:
        """Core is almost entirely keyless, and that is the finding, not an accident:
        core is furniture. It authors its own objects, so their identity arrives in a
        GRIFT declaration rather than needing to be recognised. The declaration's real
        consumers are the collectors in the plugins."""
        keyed = {t for t, m in self._core_models() if not isinstance(m.NATURAL_KEY, Keyless)}
        assert keyed == {"page", "panel"}, (
            f"Expected only page and panel to be keyed in core; got {sorted(keyed)}. "
            "If a new core type is genuinely observed rather than authored, update "
            "this test deliberately and say why in the commit."
        )


class TestPlaceholderColumn:
    """req-grid-entity-natural-key-11: the column is text, inert, and says so.

    A placeholder that something quietly reads or writes is a second way to find a
    row. The scan below is the guard: the only code allowed to know the column exists
    is the model that declares it, its migrations, the spine-surface inventories, and
    this test.
    """

    # Files that may mention the column by name. Everything else in the app trees is
    # a violation — including a "helpful" service-layer stamp or a query on it. The
    # trees are core's: plugins are wheels from their own repositories, outside any
    # in-tree scan, and their conformance is phase 3's (Grok on #569).
    ALLOWED = {
        "tap_grid/models.py",
        "tap_grid/tests/test_natural_key.py",
        "tap_grid/tests/test_core_serialization_contract.py",
    }
    # tap_ai is the planned sixth app (CLAUDE.md) and has no tree yet; listing it here silently
    # scanned nothing until the missing-dir check below was made loud (Grok on #569).
    APP_DIRS = ("tap_grid", "tap_web", "tap_viz", "tap_api", "tap_boot", "tap_cares", "tap_plugins", "tap")
    _TOKEN = re.compile(r"\bnatural_key\b")
    # The module import is the declaration sentinel, not the column.
    _IMPORT = re.compile(r"from tap_grid\.natural_key import")

    def _repo_root(self) -> Path:
        from pathlib import Path

        import tap_grid

        return Path(tap_grid.__file__).resolve().parent.parent

    def _referencing_files(self) -> set[str]:
        root = self._repo_root()
        hits: set[str] = set()
        for app in self.APP_DIRS:
            base = root / app
            assert base.is_dir(), f"scanned app dir missing: {base} — a missing dir must not pass silently"
            for path in base.rglob("*.py"):
                if "/migrations/" in str(path):
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:  # pragma: no cover
                    continue
                lines = [ln for ln in text.splitlines() if self._TOKEN.search(ln) and not self._IMPORT.search(ln)]
                if lines:
                    hits.add(str(path.relative_to(root)))
        return hits

    def test_column_is_a_text_placeholder(self) -> None:
        from tap_grid.models import Entity

        field = Entity._meta.get_field("natural_key")
        assert isinstance(field, django_models.TextField), f"natural_key is {type(field).__name__}, expected TextField"
        assert field.null and field.blank and getattr(field, "db_index", False)
        assert not field.unique, "the placeholder is non-unique by design (req-grid-entity-natural-key-3)"
        help_text = str(field.help_text)
        assert "placeholder" in help_text.lower(), "the help text must say what this column is"
        assert "gate" in help_text.lower(), "the help text must name the trigger that makes it load-bearing"

    def test_the_sentinel_module_is_not_exempt(self) -> None:
        """Codex on #564: exempting tap_grid/natural_key.py wholesale would let a future
        read or write of the column hide in the one module named after it."""
        assert "tap_grid/natural_key.py" not in self.ALLOWED
        assert "tap_grid/natural_key.py" not in self._referencing_files()

    def test_scan_found_the_model_itself(self) -> None:
        """Guard the guard: a scan that reads nothing passes silently."""
        assert "tap_grid/models.py" in self._referencing_files()

    def test_nothing_reads_or_writes_the_placeholder(self) -> None:
        extra = sorted(self._referencing_files() - self.ALLOWED)
        assert extra == [], (
            f"These files reference Entity.natural_key: {extra}. The column is a placeholder "
            "that nothing reads or writes until the gate in front of phase 3 "
            "(req-grid-entity-natural-key-11). If you are building that gate, extend "
            "ALLOWED deliberately and flip the AC."
        )


class TestGriftImportRefusesASuppliedKey:
    """req-grid-entity-natural-key-2 and -7: a collector cannot supply or override a key.

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
        node["entity"]["natural_key"] = "github:repository:12345"  # the whole point
        doc = _minimal_doc([_batch_container("01a00000-0000-7000-8000-00000000c0de", nodes=[node])])

        result = grift_import(doc)
        assert not result.success, "the envelope must refuse a supplied natural_key"
        assert any(
            "natural_key" in e.message for e in result.errors
        ), f"refused, but not for the right reason: {[e.message for e in result.errors]}"
