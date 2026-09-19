"""Collectors never retire (req-grid-reconcile-verb-1; Issue# 652 - tap).

A collector supplies evidence; it never decides, and it never calls a delete verb. This test
walks every collector module — core's and each installed plugin's — by AST and fails on any
reference to a delete verb or to the tombstone column. The reconcile verb is the only path
that retires on reconciliation's behalf, and it lives in ``tap_grid.services``, not in any
collector.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tap.plugin_testing import installed_plugin_slugs

FORBIDDEN_NAMES: frozenset[str] = frozenset(
    {
        "delete_node",
        "delete_edge_by_entity",
        "delete_entity",
        "purge_entity",
        "reconcile",
        "stamp_run_config",
        "write_batch",
        "_patch_node_internal",
        "unguarded_write",
    }
)
#: A verb spelled as a string reaches the pipeline through WriteOperation(verb=...): forbidden too.
FORBIDDEN_STRINGS: frozenset[str] = frozenset({"delete_node", "delete_edge", "delete_entity", "purge"})
FORBIDDEN_ATTRIBUTES: frozenset[str] = frozenset({"deleted_at"})


def _collector_packages() -> list[Path]:
    """Every ``collectors`` package: core's and each installed plugin's, when it has one. Found by
    walking the ``tap_plugin`` namespace on disk — nothing is imported to find them."""
    import tap_plugin

    import tap_cares.collectors

    roots = [Path(tap_cares.collectors.__file__).resolve().parent]
    installed = set(installed_plugin_slugs())
    for location in tap_plugin.__path__:
        for candidate in sorted(Path(location).iterdir()):
            if candidate.name in installed and (candidate / "collectors" / "__init__.py").exists():
                roots.append((candidate / "collectors").resolve())
    return roots


def _modules_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "tests" not in p.parts)


class _Finder(ast.NodeVisitor):
    def __init__(self) -> None:
        self.hits: list[tuple[int, str]] = []

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in FORBIDDEN_NAMES:
            self.hits.append((node.lineno, node.id))
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in FORBIDDEN_NAMES or node.attr in FORBIDDEN_ATTRIBUTES:
            self.hits.append((node.lineno, node.attr))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and node.value in FORBIDDEN_STRINGS:
            self.hits.append((node.lineno, f'"{node.value}"'))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name in FORBIDDEN_NAMES:
                self.hits.append((node.lineno, alias.name))
        self.generic_visit(node)


def _offences(path: Path) -> list[tuple[int, str]]:
    finder = _Finder()
    finder.visit(ast.parse(path.read_text(), filename=str(path)))
    return finder.hits


@pytest.mark.spec("req-grid-reconcile-verb-1")
def test_no_collector_module_names_a_delete_verb_or_the_tombstone_column() -> None:
    offences: list[str] = []
    walked = 0
    for root in _collector_packages():
        for module in _modules_under(root):
            walked += 1
            offences.extend(f"{module}:{line} references {name}" for line, name in _offences(module))
    assert walked > 0, "the walk found no collector module: the search itself is broken"
    assert not offences, "a collector must never retire; the reconcile verb does, on evidence:\n" + "\n".join(offences)


def test_the_finder_catches_each_forbidden_shape(tmp_path: Path) -> None:
    """Positive control: the walk is only as good as the finder."""
    module = tmp_path / "bad.py"
    module.write_text(
        "from tap_grid.services import delete_node\n"
        "def run(svc, row):\n"
        "    svc.delete_edge_by_entity(row)\n"
        "    return row.deleted_at\n"
    )
    assert sorted(name for _, name in _offences(module)) == ["delete_edge_by_entity", "delete_node", "deleted_at"]
    spelled = tmp_path / "spelled.py"
    spelled.write_text('def run(self):\n    op = dict(verb="delete_node")\n    return self.write_batch([op])\n')
    assert sorted(name for _, name in _offences(spelled)) == ['"delete_node"', "write_batch"]
    clean = tmp_path / "ok.py"
    clean.write_text("def run(self):\n    self.submit_grift({})\n    self.record_surface(relation='x')\n")
    assert _offences(clean) == []


def test_every_installed_plugin_collectors_package_is_walked() -> None:
    """Presence, not just correctness: name the packages the walk covers so a plugin whose
    collectors live elsewhere is a visible gap rather than a silent pass."""
    import tap_plugin

    roots = {root.parent.name for root in _collector_packages()}
    assert "tap_cares" in roots
    for slug in installed_plugin_slugs():
        has_collectors = any(
            (Path(location) / slug / "collectors" / "__init__.py").exists() for location in tap_plugin.__path__
        )
        if has_collectors:
            assert slug in roots, f"{slug} has a collectors package the walk did not cover"
