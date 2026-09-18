"""The generated search (``req-grid-entity-natural-key-10`` and ``-12``).

``find_existing`` is generated from a type's ``NATURAL_KEY`` declaration: a composite
filter on the typed table over exactly the declared fields, live rows only, no
dimension participating; nothing on zero, the row on one, and a raise on more — never a
silent selection. Nothing on the write path calls it yet; that is the gate in front of
identity phase 3, and a scan here keeps it that way until the gate is built on purpose.

``panel`` is the fixture: keyed on ``slug``, and its slug is deliberately not unique
(``tap_web/models.py``), so two live rows sharing declared values are legal at the
model layer — which is exactly the ambiguity the search must refuse to resolve.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from tap_grid.models import BaseModel, Batch, natural_key_index_name
from tap_grid.natural_key import KEYLESS, AmbiguousIdentity, Keyless
from tap_grid.services import create_node, delete_node, update_entity

_PANEL_FIELDS: dict[str, Any] = {"name": "Identity", "view": "tap_web/panels/identity.html"}


def _panel(slug: str) -> Any:
    from tap_web.models import Panel

    result = create_node("panel", {"slug": slug, **_PANEL_FIELDS})
    assert result.success, result.errors
    return Panel.objects.get(entity_id=result.entity_id)


@pytest.mark.django_db
class TestFindExisting:
    def test_zero_matches_is_none(self) -> None:
        from tap_web.models import Panel

        assert Panel.find_existing(slug="nobody-made-this") is None

    def test_one_match_is_the_row(self) -> None:
        from tap_web.models import Panel

        made = _panel("one-of-a-kind")
        found = Panel.find_existing(slug="one-of-a-kind")
        assert found is not None
        assert found.entity_id == made.entity_id

    def test_two_live_matches_raise_naming_both(self) -> None:
        from tap_web.models import Panel

        first = _panel("twins")
        second = _panel("twins")
        with pytest.raises(AmbiguousIdentity) as excinfo:
            Panel.find_existing(slug="twins")
        err = excinfo.value
        assert err.entity_type == "panel"
        assert err.properties == {"slug": "twins"}
        assert {str(c) for c in err.candidates} == {str(first.entity_id), str(second.entity_id)}
        assert "never selects" in str(err)

    def test_tombstoned_row_is_not_found(self) -> None:
        from tap_web.models import Panel

        made = _panel("retired")
        delete_node(made.entity_id)
        assert Panel.find_existing(slug="retired") is None

    def test_dimensions_do_not_participate(self) -> None:
        """-10: a node whose dimensions changed between two runs still finds itself."""
        from tap_web.models import Panel

        made = _panel("moved-perspective")
        update_entity(made.entity, dimensions={"tap.web": "somewhere-else", "collected.from": "a-second-path"})
        found = Panel.find_existing(slug="moved-perspective")
        assert found is not None
        assert found.entity_id == made.entity_id

    def test_absent_constituting_value_is_none_without_a_query(self, django_assert_num_queries: Any) -> None:
        from tap_web.models import Panel

        with django_assert_num_queries(0):
            assert Panel.find_existing(slug=None) is None
            assert Panel.find_existing(slug="") is None

    def test_exactly_the_declared_properties(self) -> None:
        from tap_web.models import Panel

        with pytest.raises(ValueError, match=r"missing=\['slug'\], unexpected=\['name'\]"):
            Panel.find_existing(name="not a constituting property")

    def test_keyless_type_has_no_search(self) -> None:
        assert isinstance(Batch.NATURAL_KEY, Keyless)
        with pytest.raises(TypeError, match="KEYLESS"):
            Batch.find_existing()

    def test_undeclared_type_is_a_configuration_error(self) -> None:
        """Three states, not two: `None` is 'nobody decided', and the search says so
        rather than treating it as keyless."""

        class _Undeclared:
            ENTITY_TYPE = "undeclared"
            NATURAL_KEY = None
            NATURAL_KEY_REASON = ""

        with pytest.raises(ImproperlyConfigured, match="has not declared NATURAL_KEY"):
            BaseModel.find_existing.__func__(_Undeclared)  # type: ignore[attr-defined]


class TestIndexIsGeneratedFromTheDeclaration:
    """-12: every keyed core type has an index-backed path over exactly its declared
    fields, and it came from the declaration rather than from a second authored copy."""

    CORE_PREFIXES = ("tap_grid.", "tap_web.", "tap_viz.", "tap_cares.", "tap_api.", "tap_boot.", "tap_ai.", "tap.")

    def _keyed_core_models(self) -> list[tuple[str, type[BaseModel]]]:
        from tap_grid.registry import get_model_class, list_entity_types

        out: list[tuple[str, type[BaseModel]]] = []
        for entity_type in sorted(list_entity_types()):
            model = get_model_class(entity_type)
            module = getattr(model, "__module__", "")
            if ".tests." in module or module.endswith(".tests"):
                continue
            if not module.startswith(self.CORE_PREFIXES):
                continue
            declared = getattr(model, "NATURAL_KEY", None)
            if declared is None or isinstance(declared, Keyless):
                continue
            assert issubclass(model, BaseModel)
            out.append((entity_type, model))
        return out

    def test_there_are_keyed_types_to_check(self) -> None:
        assert {t for t, _ in self._keyed_core_models()} == {"page", "panel"}

    def test_every_keyed_type_is_index_backed(self) -> None:
        missing: list[str] = []
        for entity_type, model in self._keyed_core_models():
            declared = list(model.NATURAL_KEY)  # type: ignore[arg-type]
            single = model._meta.get_field(declared[0]) if len(declared) == 1 else None
            own_index = single is not None and (getattr(single, "unique", False) or getattr(single, "db_index", False))
            generated = any(list(index.fields) == declared for index in model._meta.indexes)
            if not (own_index or generated):
                missing.append(entity_type)
        assert missing == [], f"Keyed types with no index over their declared fields: {missing}"

    def test_generated_index_is_visible_to_migrations(self) -> None:
        """The autodetector reads only indexes the Meta declared; a generated index that
        lives on the class but not in `original_attrs` would never reach the database."""
        from tap_web.models import Panel

        names = [index.name for index in Panel._meta.indexes]
        assert "nk_web_panel" in names
        assert Panel._meta.original_attrs.get("indexes") is Panel._meta.indexes

    def test_keyless_types_get_no_index(self) -> None:
        assert not any(index.name.startswith("nk_") for index in Batch._meta.indexes)

    def test_index_names_are_unique_across_long_tables(self) -> None:
        """A prefix truncation would give two long tables sharing 27 characters one name
        (Codex on #566); the digest of the full table name keeps them apart, within 30."""
        a = natural_key_index_name("plugin_very_long_table_name_alpha_variant")
        b = natural_key_index_name("plugin_very_long_table_name_bravo_variant")
        assert a != b
        assert len(a) <= 30 and len(b) <= 30
        assert a.startswith("nk_plugin_very_long_")
        assert natural_key_index_name("web_panel") == "nk_web_panel"

    def test_generated_names_are_unique_across_registered_models(self) -> None:
        from tap_grid.registry import get_model_class, list_entity_types

        names: dict[str, str] = {}
        for entity_type in list_entity_types():
            model = get_model_class(entity_type)
            if not (isinstance(model, type) and issubclass(model, BaseModel)):
                continue
            name = natural_key_index_name(model._meta.db_table)
            assert (
                name not in names or names[name] == model._meta.db_table
            ), f"{model._meta.db_table} and {names[name]} would share the index name {name}"
            names[name] = model._meta.db_table


class TestNothingCallsTheSearchYet:
    """The write path does not resolve until the gate. An AST scan of every REFERENCE —
    not a token grep, which a docstring would satisfy, and not only ``Call`` nodes, which an
    alias like ``finder = Panel.find_existing`` would evade (Codex on #566, rounds 1 and 2) —
    is what makes an early caller loud instead of quietly making the placeholder
    load-bearing. The one form no static scan catches is ``getattr(cls, "find_existing")``
    with a string; that is a deliberate evasion, not an accident, and code review owns it.

    The scan covers THIS repository's app trees — core. Plugins are wheels installed
    from their own repositories (``tap_plugin.*`` resolves into site-packages, and the
    root ``plugins/`` is a namespace stub), so they are outside any in-tree scan; their
    conformance is phase 3's, per repository (Grok on #569). A scanned directory that
    is missing is a failure, not a silent pass.
    """

    ALLOWED_REFERENCES = {"tap_grid/tests/test_find_existing.py", "tap_grid/services/__init__.py"}
    # tap_ai is the planned sixth app (CLAUDE.md) and has no tree yet; listing it here silently
    # scanned nothing until the missing-dir check below was made loud (Grok on #569).
    APP_DIRS = ("tap_grid", "tap_web", "tap_viz", "tap_api", "tap_boot", "tap_cares", "tap_plugins", "tap")

    def _repo_root(self) -> Path:
        import tap_grid

        return Path(tap_grid.__file__).resolve().parent.parent

    def _walk(self) -> list[tuple[str, ast.AST]]:
        root = self._repo_root()
        out: list[tuple[str, ast.AST]] = []
        for app in self.APP_DIRS:
            base = root / app
            assert base.is_dir(), f"scanned app dir missing: {base} — a missing dir must not pass silently"
            for path in base.rglob("*.py"):
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                except OSError, SyntaxError:  # pragma: no cover
                    continue
                out.append((str(path.relative_to(root)), tree))
        return out

    def _references(self) -> set[str]:
        """Files that name ``find_existing`` anywhere except as the definition itself:
        a call, an alias, an attribute read, a bare name — any of them."""
        hits: set[str] = set()
        for rel, tree in self._walk():
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "find_existing":
                    hits.add(rel)
                elif isinstance(node, ast.Name) and node.id == "find_existing":
                    hits.add(rel)
        return hits

    def _definitions(self) -> set[str]:
        return {
            rel
            for rel, tree in self._walk()
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "find_existing"
        }

    def test_scan_found_the_definition(self) -> None:
        """Guard the guard: a scan that parses nothing passes silently."""
        assert self._definitions() == {"tap_grid/models.py"}

    def test_every_scanned_dir_exists(self) -> None:
        """Grok on #569: `if not base.is_dir(): continue` would let a renamed app tree
        drop out of the scan without a sound."""
        root = self._repo_root()
        assert all((root / app).is_dir() for app in self.APP_DIRS), [
            a for a in self.APP_DIRS if not (root / a).is_dir()
        ]

    def test_scan_found_this_file_referencing_it(self) -> None:
        assert "tap_grid/tests/test_find_existing.py" in self._references()

    def test_an_alias_is_a_reference(self) -> None:
        """Codex on #566 round 2: ``finder = Panel.find_existing`` must not evade the scan."""
        tree = ast.parse("finder = Panel.find_existing\nfinder(slug='x')\n")
        assert any(isinstance(n, ast.Attribute) and n.attr == "find_existing" for n in ast.walk(tree))

    def test_no_write_path_references_it(self) -> None:
        extra = sorted(self._references() - self.ALLOWED_REFERENCES)
        assert extra == [], (
            f"These files reference find_existing: {extra}. Resolution on the write path is the gate "
            "in front of identity phase 3 (req-grid-entity-natural-key-9); build it deliberately "
            "and extend ALLOWED_REFERENCES when you do."
        )


def test_keyless_sentinel_is_what_the_search_checks() -> None:
    """Belt and braces: the sentinel the search branches on is the one models declare."""
    assert Batch.NATURAL_KEY is KEYLESS
