"""The store's scope: core, one store, format-blind (`req-tap-files-scope`).

`specs/spec-tap-file-store.md`. These pin what the earlier work already built: the store imports no
plugin, only the store reaches under the root, and no store operation looks at what a file is.
"""

from __future__ import annotations

import ast
import hashlib
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
@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("page.html", b"<html><script>alert(1)</script></html>"),
        ("report.pdf", b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF"),
        ("archive.zip", b"PK\x03\x04" + bytes(range(64))),
        ("program", b"\x7fELF\x02\x01\x01" + bytes(57)),
        ("sbom.json", b'{"bomFormat": "CycloneDX", "specVersion": "1.7"}'),
        ("empty.txt", b""),
        ("noise.bin", bytes(range(256)) * 4),
        ("mislabelled.pdf", b"<html>not a pdf</html>"),
    ],
)
def test_every_kind_of_content_is_stored_the_same_way(tmp_path: Path, name: str, data: bytes) -> None:
    # Round 1 of the AI review on PR# 1247 - tap: different content and claimed types, each shaped
    # to trip a sniffing branch, must produce the same structure; only the digest and size differ,
    # and they are the bytes' own.
    store = LocalBackend(tmp_path)
    store.initialise()
    identifier = layout.urn(str(uuid.uuid4()))
    result = store.create(identifier, name, io.BytesIO(data), "t")
    objdir = store.ocfl / layout.object_path(identifier)
    files = sorted("/".join(p.relative_to(objdir).parts[:2]) for p in objdir.rglob("*") if p.is_file())
    (content,) = list((objdir / "v1" / "content").iterdir())
    assert (result.digest, result.size) == (hashlib.sha256(data).hexdigest(), len(data))
    assert files == [
        "0=ocfl_object_1.1",
        "inventory.json",
        "inventory.json.sha256",
        "v1/content",
        "v1/inventory.json",
        "v1/inventory.json.sha256",
    ]
    assert oct(content.stat().st_mode & 0o777) == "0o440"
    assert store.verify(identifier, deep=True).ok
    opened = store.open(identifier)
    try:
        assert opened.stream.read() == data and opened.name == name
    finally:
        opened.close()


@SPEC("req-tap-files-scope-3")
def test_no_store_code_looks_at_a_type_or_a_suffix() -> None:
    # The stored filename copies a logical name's extension (req-tap-files-naming), which is naming,
    # not a branch on type; nothing else in the store or the gateway reads a suffix or a type.
    forbidden = {"suffix", "suffixes", "splitext", "mimetypes", "guess_type", "magic", "media_type", "content_type"}
    allowed = {("tap_files/store/layout.py", "stored_filename")}
    found = []
    for path in [*(REPO_ROOT / "tap_files/store").glob("*.py"), *(REPO_ROOT / "tap_files/services").glob("*.py")]:
        rel = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
            names |= {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
            if names & forbidden and (rel, fn.name) not in allowed:
                found.append(f"{rel}::{fn.name}: {sorted(names & forbidden)}")
        if "import mimetypes" in path.read_text(encoding="utf-8"):
            found.append(f"{rel}: imports mimetypes")
    assert not found, found
