"""The store's scope: core, one store, format-blind (`req-tap-files-scope`).

`specs/spec-tap-file-store.md`. These pin what the earlier work already built: the store imports no
plugin, only the store reaches under the root, and no store operation looks at what a file is.
"""

from __future__ import annotations

import ast
import inspect
import io
import uuid
from pathlib import Path

import pytest

from tap.guards.base import REPO_ROOT
from tap_files import services
from tap_files.guards.files_backend_reach import FilesBackendReachGuard
from tap_files.guards.files_root_resolution import FilesRootResolutionGuard
from tap_files.store import layout
from tap_files.store.local import LocalBackend

SPEC = pytest.mark.spec
# Plugin code lives in the tap_plugin namespace (wheels) and the in-tree plugins/ package; the
# plugin system itself, tap_plugins, is core.
_PLUGIN_ROOTS = ("tap_plugin", "plugins")


def _imports(path: Path) -> list[str]:
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.append(node.module)
    return found


@SPEC("req-tap-files-scope-1")
def test_the_store_imports_no_plugin() -> None:
    sources = [p for p in (REPO_ROOT / "tap_files").rglob("*.py") if "tests" not in p.relative_to(REPO_ROOT).parts]
    assert sources
    offending = [
        f"{p.relative_to(REPO_ROOT)}: {name}"
        for p in sources
        for name in _imports(p)
        if name.split(".")[0] in _PLUGIN_ROOTS
    ]
    assert not offending, offending
    # That it also works with none installed is the lean-boot gate (the zero-plugin core profile)
    # and the hold-and-download test (req-tap-files-node-1).


@SPEC("req-tap-files-scope-2")
def test_one_store_reaches_under_the_root() -> None:
    # The setting is read in tap_files/config.py alone, and the store is imported only by its named
    # holders; the shared mount test's reserved probe file is the one other write, by design.
    FilesRootResolutionGuard().check()
    FilesBackendReachGuard().check()


@SPEC("req-tap-files-scope-3")
def test_no_store_operation_takes_a_type() -> None:
    for owner in (LocalBackend, services):
        for name, fn in inspect.getmembers(owner, inspect.isfunction):
            if name.startswith("_"):
                continue
            params = set(inspect.signature(fn).parameters)
            assert not params & {"media_type", "content_type", "mime_type", "extension"}, (owner, name)


@SPEC("req-tap-files-scope-3")
def test_a_file_is_stored_the_same_whatever_it_claims_to_be(tmp_path: Path) -> None:
    store = LocalBackend(tmp_path)
    store.initialise()
    data = b"<html><script>alert(1)</script></html>"
    shapes = []
    for name in ("page.html", "page.exe", "page"):
        identifier = layout.urn(str(uuid.uuid4()))
        result = store.create(identifier, name, io.BytesIO(data), "t")
        objdir = store.ocfl / layout.object_path(identifier)
        files = sorted(p.relative_to(objdir).parts[:2] for p in objdir.rglob("*") if p.is_file())
        modes = sorted(oct(p.stat().st_mode & 0o777) for p in objdir.rglob("*") if p.is_file())
        shapes.append((result.digest, result.size, files, modes, store.verify(identifier, deep=True).ok))
    assert shapes[0] == shapes[1] == shapes[2]
