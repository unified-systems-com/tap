"""Gryphon read-scope guard — the executor reaches the grid only through the read scope.

`req-grid-traversal-exec-read-scope-12`. Every Gryphon read must be built from the base
relations and scoped joins in `tap_grid/gryphon/read_scope.py`, which is what makes a
retired node or edge invisible at every hop (`Issue# 811 - tap`). This guard flags, anywhere
in `tap_grid/gryphon/` outside that module:

- manager access — `.objects`, `.all_objects`, `._base_manager`, `._default_manager`. A
  manager is exactly how a read escaped the scope before: a `LiveManager` scopes only a
  queryset's root, and the spine's default manager scopes nothing;
- a reverse-edge lookup string — a string literal or f-string part naming `edges_out` /
  `edges_in`. That relation is where scoping is needed and easy to forget, so its paths are
  built by `read_scope.reverse_edge_path` and nowhere else. Docstrings are prose, not
  lookups, and are exempt.

This is the SECONDARY enforcement, a review-time catch for the common mistake. The primary
one runs on every read: the compiled-query check in `read_scope.assert_query_scoped`, which
refuses to execute a queryset with an unscoped relation however it was built. A syntactic
check cannot promise that (a lookup can be assembled at runtime); it can promise that the
obvious spellings never reach review unnoticed.

A hard lint with no baseline: after the read scope landed there is nothing to grandfather.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tap.guards.base import REPO_ROOT, Guard

_GRYPHON_DIR = REPO_ROOT / "tap_grid" / "gryphon"
_SCOPE_MODULE = "read_scope.py"
_MANAGER_ATTRIBUTES = frozenset({"objects", "all_objects", "_base_manager", "_default_manager"})
_REVERSE_EDGE_NAMES = ("edges_out", "edges_in")


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """ids of the string constants that are docstrings (or other bare string statements)."""
    exempt: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for stmt in body:
            if (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            ):
                exempt.add(id(stmt.value))
    return exempt


def read_scope_offenders(source: str, label: str) -> list[str]:
    """Every unscoped-relation spelling in one module's source, as ``label:line: why``."""
    tree = ast.parse(source)
    exempt = _docstring_nodes(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _MANAGER_ATTRIBUTES:
            found.append(
                f"{label}:{node.lineno}: `.{node.attr}` — build the relation with "
                "read_scope.node_relation / edge_relation / refetch_*"
            )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in exempt:
            for name in _REVERSE_EDGE_NAMES:
                if name in node.value:
                    found.append(
                        f"{label}:{node.lineno}: reverse-edge lookup {node.value!r} — build it with "
                        "read_scope.reverse_edge_path and scope it with read_scope.edge_scope_filters"
                    )
                    break
    return found


class GryphonReadScopeGuard(Guard):
    slug = "gryphon-read-scope"
    map_row = "Gryphon read scope"
    rid = "req-grid-traversal-exec-read-scope"
    description = (
        "A Gryphon read built from a manager or a hand-written reverse-edge lookup escapes the read "
        "scope: a LiveManager scopes only a queryset's root, so a retired edge at hop 1 was returned "
        "while the same edge at hop 0 was not (tap#811)."
    )

    def check(self) -> None:
        offenders: list[str] = []
        for path in sorted(_GRYPHON_DIR.rglob("*.py")):
            if path.name == _SCOPE_MODULE:
                continue
            label = str(path.relative_to(REPO_ROOT))
            offenders.extend(read_scope_offenders(Path(path).read_text(encoding="utf-8"), label))
        assert not offenders, (  # nosec B101
            "Gryphon code outside tap_grid/gryphon/read_scope.py reaches the grid without the read "
            "scope (req-grid-traversal-exec-read-scope-12):\n  " + "\n  ".join(offenders)
        )
