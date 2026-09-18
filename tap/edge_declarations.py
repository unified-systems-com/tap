"""Do a model's edge declarations name edge types that exist?

A model declares the edges it may emit or accept (``OUTBOUND_EDGES`` / ``INBOUND_EDGES``)
and the subset that means containment for the cascade (``CONTAINMENT_EDGES``). Each names
edge types by slug. Nothing used to check that those slugs resolve to a DEFINED edge type
(a ``.edge.json`` in some plugin's manifest, or a grid-standard core edge): rename the
definition and every declaration still reads as valid — a citation that does not resolve
reads as verification — while the cascade follows an edge nothing will ever carry
(Issue# 583 - tap).

This module is the one home of that predicate, used from two places so the fact is derived
once: the Django system check in ``tap_grid/checks.py`` (boot time, the full set of loaded
plugins) and ``validate_plugin`` (author time, one plugin against its own manifest and its
declared dependencies). It is stdlib-only and host-runnable: the author-time reader parses
models with ``ast`` and never imports them.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DECLARATION_ATTRIBUTES: tuple[str, ...] = ("OUTBOUND_EDGES", "INBOUND_EDGES", "CONTAINMENT_EDGES")
_SKIP_DIRS = frozenset({"tests", "migrations", "__pycache__"})


@dataclass(frozen=True)
class EdgeDeclaration:
    """One edge type named by one attribute of one model."""

    owner: str  # entity type (runtime) or class name (static)
    attribute: str
    edge_type: str
    where: str  # "module.Class" at runtime, "path:line" statically


@dataclass(frozen=True)
class UnreadableDeclaration:
    """A declaration the static reader could not evaluate (not a literal)."""

    owner: str
    attribute: str
    where: str


def edge_types_in(attribute: str, value: Any) -> list[str]:
    """The edge-type slugs an attribute value names, in declaration order, de-duplicated.

    ``OUTBOUND_EDGES`` / ``INBOUND_EDGES`` are lists of ``{"nodes": [...], "edges":
    [{"type": slug}, ...]}`` entries; ``CONTAINMENT_EDGES`` is a tuple of slugs.
    """
    seen: list[str] = []

    def add(slug: Any) -> None:
        if isinstance(slug, str) and slug and slug not in seen:
            seen.append(slug)

    if attribute == "CONTAINMENT_EDGES":
        for slug in value or ():
            add(slug)
        return seen
    for entry in value or []:
        if not isinstance(entry, dict):
            continue
        for edge in entry.get("edges", []) or []:
            if isinstance(edge, dict):
                add(edge.get("type"))
    return seen


def declarations_of(owner: str, where: str, attributes: dict[str, Any]) -> list[EdgeDeclaration]:
    """Declarations from already-evaluated attribute values (the runtime path)."""
    out: list[EdgeDeclaration] = []
    for attribute in DECLARATION_ATTRIBUTES:
        if attribute not in attributes:
            continue
        for slug in edge_types_in(attribute, attributes[attribute]):
            out.append(EdgeDeclaration(owner, attribute, slug, where))
    return out


def unresolved(declarations: Iterable[EdgeDeclaration], defined: Iterable[str]) -> list[EdgeDeclaration]:
    """Every declaration whose edge type is not in ``defined``."""
    known = set(defined)
    return [d for d in declarations if d.edge_type not in known]


def owner_plugin_of(edge_type: str) -> str | None:
    """The plugin slug an edge type's ``__<plugin>`` suffix names; ``None`` for a core edge."""
    head, sep, tail = edge_type.rpartition("__")
    return tail if sep and head and tail else None


def read_declarations(package_dir: Path) -> tuple[list[EdgeDeclaration], list[UnreadableDeclaration]]:
    """Statically read every model's edge declarations under ``package_dir``.

    Walks ``*.py`` (skipping tests, migrations and caches), and for every class body reads
    the three declaration attributes as literals. A value that is not a literal (a name, a
    call, a comprehension) is reported as unreadable rather than guessed: the caller says
    so, and the boot-time check — which sees the evaluated value — is the authority.
    """
    found: list[EdgeDeclaration] = []
    unreadable: list[UnreadableDeclaration] = []
    for path in sorted(package_dir.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.relative_to(package_dir).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except OSError, SyntaxError:
            continue
        rel = path.relative_to(package_dir).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            owner = _entity_type_of(node) or node.name
            for stmt in node.body:
                target, value = _declaration_in(stmt)
                if target is None or value is None:
                    continue
                where = f"{rel}:{stmt.lineno}"
                try:
                    literal = ast.literal_eval(value)
                except ValueError, SyntaxError, TypeError:
                    unreadable.append(UnreadableDeclaration(owner, target, where))
                    continue
                for slug in edge_types_in(target, literal):
                    found.append(EdgeDeclaration(owner, target, slug, where))
    return found, unreadable


def _declaration_in(stmt: ast.stmt) -> tuple[str | None, ast.expr | None]:
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        name = stmt.target.id
        return (name, stmt.value) if name in DECLARATION_ATTRIBUTES else (None, None)
    if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
        name = stmt.targets[0].id
        return (name, stmt.value) if name in DECLARATION_ATTRIBUTES else (None, None)
    return None, None


def _entity_type_of(cls: ast.ClassDef) -> str | None:
    for stmt in cls.body:
        target, value = None, None
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            target, value = stmt.target.id, stmt.value
        elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            target, value = stmt.targets[0].id, stmt.value
        if target == "ENTITY_TYPE" and isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return None
