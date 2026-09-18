"""The edge-declaration predicate and its static reader (Issue# 583 - tap).

Stdlib-only, host-runnable: no Django here. The Django check and validate_plugin share
this module so the fact — does a declared edge type resolve? — is derived once.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tap.edge_declarations import (
    EdgeDeclaration,
    declarations_of,
    edge_types_in,
    owner_plugin_of,
    read_declarations,
    unresolved,
)


class TestEdgeTypesIn:
    def test_outbound_entries_yield_their_edge_slugs_once_each(self) -> None:
        value = [
            {"nodes": [{"type": "a"}], "edges": [{"type": "X__p"}, {"type": "Y__p"}]},
            {"nodes": [{"type": "b"}], "edges": [{"type": "X__p"}]},
        ]
        assert edge_types_in("OUTBOUND_EDGES", value) == ["X__p", "Y__p"]

    def test_containment_is_a_tuple_of_slugs(self) -> None:
        assert edge_types_in("CONTAINMENT_EDGES", ("X__p", "Y__p", "X__p")) == ["X__p", "Y__p"]

    def test_empty_and_malformed_yield_nothing(self) -> None:
        assert edge_types_in("OUTBOUND_EDGES", []) == []
        assert edge_types_in("OUTBOUND_EDGES", None) == []
        assert edge_types_in("INBOUND_EDGES", [{"edges": "not-a-list"}, "junk"]) == []


@pytest.mark.spec("req-grid-service-delete-cascade-17")
class TestUnresolved:
    def test_names_exactly_the_declarations_that_do_not_resolve(self) -> None:
        decls = declarations_of(
            "p__thing",
            "p.models.Thing",
            {
                "OUTBOUND_EDGES": [{"edges": [{"type": "OK__p"}, {"type": "GONE__p"}]}],
                "CONTAINMENT_EDGES": ("GONE__p",),
            },
        )
        bad = unresolved(decls, {"OK__p"})
        assert [(d.attribute, d.edge_type) for d in bad] == [
            ("OUTBOUND_EDGES", "GONE__p"),
            ("CONTAINMENT_EDGES", "GONE__p"),
        ]
        assert all(d.owner == "p__thing" and d.where == "p.models.Thing" for d in bad)

    def test_everything_resolves_is_empty(self) -> None:
        decls = [EdgeDeclaration("t", "OUTBOUND_EDGES", "A", "w")]
        assert unresolved(decls, {"A"}) == []

    def test_owner_plugin_is_the_suffix_or_none_for_core(self) -> None:
        assert owner_plugin_of("PG_LINKS__grid_fixtures") == "grid_fixtures"
        assert owner_plugin_of("PRODUCED_BATCH") is None
        assert owner_plugin_of("__x") is None


def _package(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "pkg"
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body), encoding="utf-8")
    return root


@pytest.mark.spec("req-tap-plugin-validate-codepaths-4")
class TestReadDeclarations:
    def test_reads_literals_and_names_the_entity_type(self, tmp_path: Path) -> None:
        root = _package(
            tmp_path,
            {
                "models/thing.py": """
                    class Thing(BaseModel):
                        ENTITY_TYPE: ClassVar[str] = "p__thing"
                        OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
                            {"nodes": [{"type": "p__other"}], "edges": [{"type": "LINKS__p"}, {"type": "NESTS__p"}]},
                        ]
                        CONTAINMENT_EDGES = ("NESTS__p",)
                """,
            },
        )
        found, unreadable = read_declarations(root)
        assert unreadable == []
        assert [(d.owner, d.attribute, d.edge_type) for d in found] == [
            ("p__thing", "OUTBOUND_EDGES", "LINKS__p"),
            ("p__thing", "OUTBOUND_EDGES", "NESTS__p"),
            ("p__thing", "CONTAINMENT_EDGES", "NESTS__p"),
        ]
        assert found[0].where == "models/thing.py:4"  # the dedented body starts with a blank line

    def test_a_non_literal_is_reported_not_guessed(self, tmp_path: Path) -> None:
        root = _package(
            tmp_path, {"models.py": "class T:\n    ENTITY_TYPE = 'p__t'\n    OUTBOUND_EDGES = build_edges()\n"}
        )
        found, unreadable = read_declarations(root)
        assert found == []
        assert [(u.owner, u.attribute) for u in unreadable] == [("p__t", "OUTBOUND_EDGES")]

    def test_tests_and_migrations_are_skipped_and_a_class_without_entity_type_uses_its_name(
        self, tmp_path: Path
    ) -> None:
        root = _package(
            tmp_path,
            {
                "tests/test_x.py": "class Fake:\n    CONTAINMENT_EDGES = ('IGNORED__p',)\n",
                "migrations/0001.py": "class M:\n    CONTAINMENT_EDGES = ('IGNORED__p',)\n",
                "mixins.py": "class Mixin:\n    CONTAINMENT_EDGES = ('SEEN__p',)\n",
            },
        )
        found, _ = read_declarations(root)
        assert [(d.owner, d.edge_type) for d in found] == [("Mixin", "SEEN__p")]

    @pytest.mark.parametrize("bad", ["def broken(:\n", ""])
    def test_unparseable_or_empty_files_are_ignored(self, tmp_path: Path, bad: str) -> None:
        root = _package(tmp_path, {"models.py": bad})
        assert read_declarations(root) == ([], [])
