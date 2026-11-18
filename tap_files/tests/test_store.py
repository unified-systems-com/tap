"""The file store engine (`specs/spec-tap-file-store.md`, tap#1208).

One test per acceptance criterion of the requirements tap#1208 builds, marked with its id. The
behavioural suite runs against the local backend and an in-memory backend written here, which is the
proof that the protocol is the contract (`req-tap-files-interface-2`). Cross-process criteria are in
``test_store_processes.py``.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import stat
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

import pytest

from tap import volume_mount
from tap.logging_signals import CONCERN_MESSAGE_CODE
from tap_files.store import inventory as inv
from tap_files.store import layout
from tap_files.store.errors import (
    DigestMismatch,
    FileIntegrityError,
    FileStoreNotEnabled,
    InvalidLogicalName,
    ObjectExists,
    StoredFileNotFound,
    StoreRootRefused,
    VersionConflict,
)
from tap_files.store.local import CREATE_STEPS, RENAME_STEPS, VERSION_STEPS, LocalBackend
from tap_files.store.protocol import ObjectStat, OpenedFile, StoredResult, VerifyResult, VersionInfo

_REPO = Path(__file__).resolve().parents[2]


def new_id() -> str:
    return layout.urn(str(uuid.uuid4()))


def data(text: str | bytes) -> io.BytesIO:
    return io.BytesIO(text.encode() if isinstance(text, str) else text)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_all(opened: OpenedFile) -> bytes:
    try:
        return opened.stream.read()
    finally:
        opened.close()


@pytest.fixture
def store(tmp_path: Path) -> LocalBackend:
    root = tmp_path / "files"
    root.mkdir()
    backend = LocalBackend(root)
    backend.initialise()
    return backend


def tree(path: Path) -> dict[str, tuple[bytes, int]]:
    """Every file under *path*: bytes and modification time."""
    return {
        p.relative_to(path).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(path.rglob("*"))
        if p.is_file()
    }


class _Killed(BaseException):
    """Stands in for the process dying: not an Exception, so no cleanup handler catches it."""


def kill_at(backend: LocalBackend, step: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(name: str) -> None:
        if name == step:
            raise _Killed(step)

    monkeypatch.setattr(backend, "_step", fake)


# =========================================================================== in-memory backend


class MemoryBackend:
    """A second backend written for the tests: the same protocol, no filesystem."""

    def __init__(self) -> None:
        self._objects: dict[str, list[tuple[str, bytes, str]]] = {}

    def create(
        self,
        identifier: str,
        name: str,
        stream: BinaryIO,
        actor: str,
        reason: str = "",
        expected_digest: str | None = None,
    ) -> StoredResult:
        layout.check_identifier(identifier)
        layout.check_logical_name(name)
        raw = stream.read()
        if expected_digest is not None and expected_digest != sha(raw):
            raise DigestMismatch(identifier)
        if identifier in self._objects:
            raise ObjectExists(identifier)
        self._objects[identifier] = [(name, raw, actor)]
        return StoredResult(identifier, 1, sha(raw), len(raw))

    def add_version(
        self,
        identifier: str,
        expected_version: int,
        name: str,
        stream: BinaryIO,
        actor: str,
        reason: str = "",
        expected_digest: str | None = None,
    ) -> StoredResult:
        versions = self._get(identifier)
        layout.check_logical_name(name)
        raw = stream.read()
        if expected_version != len(versions):
            raise VersionConflict(identifier, expected_version, len(versions), sha(versions[-1][1]))
        if (name, raw) == versions[-1][:2]:
            return StoredResult(identifier, len(versions), sha(raw), len(raw), stored=False)
        versions.append((name, raw, actor))
        return StoredResult(identifier, len(versions), sha(raw), len(raw))

    def rename(self, identifier: str, expected_version: int, name: str, actor: str, reason: str = "") -> StoredResult:
        versions = self._get(identifier)
        layout.check_logical_name(name)
        if expected_version != len(versions):
            raise VersionConflict(identifier, expected_version, len(versions), sha(versions[-1][1]))
        raw = versions[-1][1]
        versions.append((name, raw, actor))
        return StoredResult(identifier, len(versions), sha(raw), len(raw))

    def open(self, identifier: str, version: int | None = None) -> OpenedFile:
        versions = self._get(identifier)
        number = len(versions) if version is None else version
        if not 1 <= number <= len(versions):
            raise StoredFileNotFound(identifier)
        name, raw, _actor = versions[number - 1]
        return OpenedFile(identifier, number, name, sha(raw), len(raw), io.BytesIO(raw))

    def stat(self, identifier: str) -> ObjectStat:
        versions = self._get(identifier)
        infos = tuple(VersionInfo(i, n, sha(r), len(r), "now", a) for i, (n, r, a) in enumerate(versions, start=1))
        return ObjectStat(identifier, len(versions), infos)

    def exists(self, identifier: str) -> bool:
        return identifier in self._objects

    def identifiers(self) -> Iterator[str]:
        yield from sorted(self._objects)

    def verify(self, identifier: str, deep: bool = False) -> VerifyResult:
        return VerifyResult(identifier, identifier in self._objects)

    def _get(self, identifier: str) -> list[tuple[str, bytes, str]]:
        layout.check_identifier(identifier)
        if identifier not in self._objects:
            raise StoredFileNotFound(identifier)
        return self._objects[identifier]


@pytest.fixture(params=["local", "memory"])
def backend(request: pytest.FixtureRequest, tmp_path: Path) -> Any:
    if request.param == "memory":
        return MemoryBackend()
    root = tmp_path / "files"
    root.mkdir()
    local = LocalBackend(root)
    local.initialise()
    return local


# =========================================================================== interface


@pytest.mark.spec("req-tap-files-interface-2")
def test_the_behavioural_suite_passes_on_both_backends(backend: Any) -> None:
    ident = new_id()
    first = backend.create(ident, "report.json", data("one"), "collector")
    assert (first.version, first.digest, first.size) == (1, sha(b"one"), 3)
    assert backend.exists(ident) and ident in list(backend.identifiers())
    second = backend.add_version(ident, 1, "report.json", data("two!"), "collector")
    assert second.version == 2
    renamed = backend.rename(ident, 2, "report-final.json", "collector")
    assert renamed.version == 3 and renamed.digest == sha(b"two!")
    assert read_all(backend.open(ident)) == b"two!"
    assert read_all(backend.open(ident, 1)) == b"one"
    status = backend.stat(ident)
    assert status.head == 3 and [v.name for v in status.versions] == ["report.json", "report.json", "report-final.json"]
    with pytest.raises(VersionConflict):
        backend.add_version(ident, 1, "x", data("three"), "collector")
    with pytest.raises(ObjectExists):
        backend.create(ident, "again", data("x"), "collector")
    with pytest.raises(StoredFileNotFound):
        backend.open(new_id())
    with pytest.raises(StoredFileNotFound):
        backend.open(ident, 9)
    assert backend.add_version(ident, 3, "report-final.json", data("two!"), "collector").stored is False


@pytest.mark.spec("req-tap-files-interface-1")
def test_only_the_local_backend_touches_the_root() -> None:
    from tap.guards.discovery import discover_guards

    next(g for g in discover_guards() if g.slug == "files-root-resolution").check()
    for path in (_REPO / "tap_files").rglob("*.py"):
        rel = path.relative_to(_REPO).as_posix()
        if "/tests/" in rel or rel.endswith("store/local.py"):
            continue
        text = path.read_text(encoding="utf-8")
        assert "os.scandir" not in text and ".iterdir()" not in text, rel


@pytest.mark.spec("req-tap-files-interface-3")
def test_an_unknown_backend_fails_startup_by_name(settings: Any) -> None:
    from tap_files.checks import check_backend

    settings.TAP_FILES_BACKEND = "s3"
    errors = check_backend()
    assert len(errors) == 1 and errors[0].id == "tap_files.E001" and "'local'" in errors[0].msg
    settings.TAP_FILES_BACKEND = "local"
    assert check_backend() == []


# =========================================================================== root


@pytest.mark.spec("req-tap-files-root-1")
def test_the_root_is_one_setting_with_no_default() -> None:
    from django.conf import settings

    text = (_REPO / "tap" / "settings.py").read_text(encoding="utf-8")
    assert 'TAP_FILES_ROOT = os.environ.get("TAP_FILES_ROOT") or ""' in text
    assert isinstance(settings.TAP_FILES_ROOT, str)


@pytest.mark.spec("req-tap-files-root-5")
def test_not_enabled_is_one_clear_error(settings: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_files.store import get_store

    settings.TAP_FILES_ROOT = ""
    touched: list[Any] = []
    real_lstat = os.lstat

    def recording_lstat(*args: Any, **kwargs: Any) -> os.stat_result:
        touched.append(args)
        return real_lstat(*args, **kwargs)

    monkeypatch.setattr(os, "lstat", recording_lstat)
    with pytest.raises(FileStoreNotEnabled, match="not enabled"):
        get_store()
    assert touched == []


@pytest.mark.spec("req-tap-files-root-3")
def test_nothing_foreign_under_the_ocfl_root(store: LocalBackend, monkeypatch: pytest.MonkeyPatch) -> None:
    a, b = new_id(), new_id()
    store.create(a, "a.txt", data("a"), "t")
    store.add_version(a, 1, "a.txt", data("aa"), "t")
    store.rename(a, 2, "b.txt", "t")
    kill_at(store, "parents_made", monkeypatch)
    with pytest.raises(_Killed):
        store.create(b, "b.txt", data("b"), "t")
    monkeypatch.undo()
    store.recover()
    top = {p.name for p in store.ocfl.iterdir()}
    assert top - {"extensions", inv.STORAGE_ROOT_MARKER, "ocfl_layout.json"} <= {n for n in top if len(n) == 3}
    for path in store.ocfl.rglob("*"):
        if path.is_dir():
            assert any(path.iterdir()), f"empty directory left: {path}"


@pytest.mark.spec("req-tap-files-root-4")
def test_the_gate_refuses_overlapping_roots(tmp_path: Path, settings: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_files.boot import FileStoreGateError, run_gate

    monkeypatch.setattr(volume_mount, "root_device", lambda: -1)
    files = tmp_path / "files"
    files.mkdir()
    settings.TAP_FILES_ROOT = str(files)
    for plugin_root in (files, files / "inner", tmp_path):
        plugin_root.mkdir(exist_ok=True)
        settings.TAP_PLUGIN_DATA_ROOT = str(plugin_root)
        with pytest.raises(FileStoreGateError, match="separate volumes"):
            run_gate()
    settings.TAP_PLUGIN_DATA_ROOT = ""


# =========================================================================== mount gate


@pytest.fixture
def gate(tmp_path: Path, settings: Any, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(volume_mount, "root_device", lambda: -1)
    root = tmp_path / "files"
    root.mkdir()
    settings.TAP_FILES_ROOT = str(root)
    settings.TAP_PLUGIN_DATA_ROOT = ""
    return root


@pytest.mark.django_db
@pytest.mark.spec("req-tap-files-mount-gate-1")
def test_an_unmounted_root_aborts_boot(
    gate: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from django.core.management import call_command
    from django.core.management.base import CommandError

    from tap.logging_signals import ABORT_MESSAGE_CODE

    monkeypatch.setattr(volume_mount, "root_device", lambda: os.stat(gate).st_dev)
    caplog.set_level(logging.ERROR)
    with pytest.raises(CommandError, match="not a mounted volume"):
        call_command("boot", "--allow-empty")
    aborts = [r for r in caplog.records if getattr(r, "message_code", None) == ABORT_MESSAGE_CODE]
    assert len(aborts) == 1 and "not a mounted volume" in aborts[0].getMessage()


@pytest.mark.spec("req-tap-files-mount-gate-7")
def test_not_enabled_boots_and_creates_nothing(tmp_path: Path, settings: Any) -> None:
    from tap_files.boot import run_gate

    settings.TAP_FILES_ROOT = ""
    before = sorted(tmp_path.rglob("*"))
    assert run_gate() == {"enabled": False}
    assert sorted(tmp_path.rglob("*")) == before


@pytest.mark.spec("req-tap-files-mount-gate-2")
def test_an_empty_root_is_initialised(gate: Path) -> None:
    from tap_files.boot import run_gate

    assert run_gate()["state"] == "initialised"
    assert sorted(p.name for p in gate.iterdir()) == ["locks", "ocfl", "quarantine", "staging"]
    ocfl = gate / "ocfl"
    assert (ocfl / "0=ocfl_1.1").read_text() == "ocfl_1.1\n"
    assert json.loads((ocfl / "ocfl_layout.json").read_text())["extension"] == layout.LAYOUT_EXTENSION
    assert (
        json.loads((ocfl / "extensions" / layout.LAYOUT_EXTENSION / "config.json").read_text()) == layout.LAYOUT_CONFIG
    )
    assert sorted(p.relative_to(ocfl).as_posix() for p in ocfl.rglob("*")) == [
        "0=ocfl_1.1",
        "extensions",
        f"extensions/{layout.LAYOUT_EXTENSION}",
        f"extensions/{layout.LAYOUT_EXTENSION}/config.json",
        "ocfl_layout.json",
    ]


@pytest.mark.spec("req-tap-files-mount-gate-3")
def test_foreign_content_is_refused_and_untouched(gate: Path) -> None:
    from tap_files.boot import FileStoreGateError, run_gate

    (gate / "someone-elses.txt").write_text("not ours")
    before = tree(gate)
    with pytest.raises(FileStoreGateError, match="not this store's"):
        run_gate()
    assert tree(gate) == before
    with pytest.raises(StoreRootRefused):
        LocalBackend(gate).initialise()


@pytest.mark.spec("req-tap-files-mount-gate-4")
def test_a_second_boot_changes_nothing(gate: Path) -> None:
    from tap_files.boot import run_gate

    run_gate()
    store = LocalBackend(gate)
    store.create(new_id(), "a", data("a"), "t")
    before = tree(gate / "ocfl")
    assert run_gate()["state"] == "existing"
    assert tree(gate / "ocfl") == before


@pytest.mark.spec("req-tap-files-mount-gate-5")
def test_one_mount_test_for_both_volumes() -> None:
    import inspect

    from tap_files import boot
    from tap_plugins.datadir import _placement

    assert "check_volume" in inspect.getsource(boot) and "check_volume" in inspect.getsource(_placement)
    for module in (boot, _placement):
        assert "st_dev" not in inspect.getsource(module)


# =========================================================================== OCFL


@pytest.mark.spec("req-tap-files-ocfl-3")
def test_every_sidecar_matches(store: LocalBackend) -> None:
    ident = new_id()
    store.create(ident, "a", data("a"), "t")
    store.add_version(ident, 1, "a", data("b"), "t")
    store.rename(ident, 2, "c", "t")
    sidecars = list(store.ocfl.rglob(inv.SIDECAR))
    assert len(sidecars) == 4
    for side in sidecars:
        assert inv.sidecar_digest(side.read_bytes()) == sha((side.parent / inv.INVENTORY).read_bytes())


@pytest.mark.spec("req-tap-files-ocfl-4")
def test_inventories_follow_the_schema(store: LocalBackend) -> None:
    from tap.jsonfiles import JsonFileError, validate_json

    ident = new_id()
    store.create(ident, "a", data("a"), "t")
    for path in store.ocfl.rglob(inv.INVENTORY):
        validate_json(json.loads(path.read_bytes()), inv.SCHEMA_PATH)
    bad = {
        "id": ident,
        "type": inv.INVENTORY_TYPE,
        "digestAlgorithm": "sha512",
        "head": "v1",
        "manifest": {},
        "versions": {},
    }
    with pytest.raises(JsonFileError):
        inv.serialise(bad)
    objdir = store.ocfl / layout.object_path(ident)
    broken = json.loads((objdir / inv.INVENTORY).read_bytes())
    broken["digestAlgorithm"] = "md5"
    raw = (json.dumps(broken) + "\n").encode()
    os.replace(_write_tmp(store, raw), objdir / inv.INVENTORY)
    os.replace(_write_tmp(store, inv.sidecar_text(raw)), objdir / inv.SIDECAR)
    with pytest.raises(FileIntegrityError):
        store.open(ident)
    assert not store.verify(ident).ok


def _write_tmp(store: LocalBackend, raw: bytes) -> Path:
    path = store.staging / f"t{uuid.uuid4().hex}"
    path.write_bytes(raw)
    return path


@pytest.mark.spec("req-tap-files-ocfl-5")
def test_readable_cold_with_the_standard_library(store: LocalBackend) -> None:
    ident = new_id()
    store.create(ident, "cold.txt", data("cold"), "t")
    store.add_version(ident, 1, "cold.txt", data("colder"), "t")
    listing = []
    for marker in store.ocfl.rglob("0=ocfl_object_1.1"):
        objdir = marker.parent
        inventory = json.loads((objdir / "inventory.json").read_text())
        for vname, version in sorted(inventory["versions"].items()):
            ((digest, names),) = version["state"].items()
            path = objdir / inventory["manifest"][digest][0]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
            listing.append((inventory["id"], names[0], vname, digest))
    assert [entry[2] for entry in listing] == ["v1", "v2"] and listing[0][0] == ident


# =========================================================================== naming


@pytest.mark.spec("req-tap-files-naming-1")
def test_the_directory_comes_from_the_identifier_only(store: LocalBackend) -> None:
    a, b = new_id(), new_id()
    store.create(a, "same.txt", data("same"), "t")
    store.create(b, "same.txt", data("same"), "t")
    dir_a, dir_b = store.ocfl / layout.object_path(a), store.ocfl / layout.object_path(b)
    assert dir_a != dir_b and dir_a.is_dir() and dir_b.is_dir()
    store.add_version(a, 1, "same.txt", data("new"), "t")
    store.rename(a, 2, "other.txt", "t")
    assert (store.ocfl / layout.object_path(a)) == dir_a and dir_a.is_dir()


@pytest.mark.spec("req-tap-files-naming-2")
def test_the_layout_matches_the_extension() -> None:
    assert layout.object_path("object-01") == "3c0/ff4/240/object-01"
    assert layout.object_path("urn:uuid:01a1e3b1-25c0-7d4a-9b1c-2f6e5a7b8c9d") == (
        "568/a1f/6b7/urn%3auuid%3a01a1e3b1-25c0-7d4a-9b1c-2f6e5a7b8c9d"
    )


@pytest.mark.spec("req-tap-files-naming-7")
def test_the_layout_is_declared_in_the_store(store: LocalBackend) -> None:
    assert (
        json.loads((store.ocfl / "ocfl_layout.json").read_text())["extension"]
        == "0003-hash-and-id-n-tuple-storage-layout"
    )
    config = json.loads((store.ocfl / "extensions" / layout.LAYOUT_EXTENSION / "config.json").read_text())
    assert (config["digestAlgorithm"], config["tupleSize"], config["numberOfTuples"]) == ("sha256", 3, 3)


@pytest.mark.spec("req-tap-files-naming-6")
def test_the_identifier_is_a_urn(store: LocalBackend) -> None:
    entity = uuid.uuid4()
    ident = layout.urn(str(entity).upper())
    assert ident == f"urn:uuid:{entity}"
    store.create(ident, "a", data("a"), "t")
    inventory = json.loads((store.ocfl / layout.object_path(ident) / inv.INVENTORY).read_bytes())
    assert inventory["id"] == ident
    for bad in (str(entity), f"urn:uuid:{str(entity).upper()}", "urn:uuid:not-a-uuid"):
        with pytest.raises(Exception, match="urn:uuid"):
            store.create(bad, "a", data("a"), "t")


@pytest.mark.spec("req-tap-files-naming-3")
def test_every_content_name_carries_all_four(store: LocalBackend) -> None:
    ident = new_id()
    store.create(ident, "a+b.json", data("one"), "t")
    store.add_version(ident, 1, "a+b.json", data("two"), "t")
    for content in store.ocfl.rglob("content/*"):
        uuid_text, version, digest = layout.parse_stored_filename(content.name)
        assert digest == sha(content.read_bytes())
        assert f"v{version}" == content.parent.parent.name
        assert f"urn:uuid:{uuid_text}" == ident


@pytest.mark.spec("req-tap-files-naming-4")
@pytest.mark.parametrize(
    "name", ["../escape.txt", ".hidden", "nul\x00byte", "new\nline", "a+b+c", "s" * 300, "CON", "..", ""]
)
def test_hostile_names_stay_inside_or_are_refused(store: LocalBackend, name: str) -> None:
    ident = new_id()
    try:
        store.create(ident, name, data("x"), "t")
    except InvalidLogicalName:
        assert not store.exists(ident)
        return
    content = list((store.ocfl / layout.object_path(ident) / "v1" / "content").iterdir())
    assert len(content) == 1 and "/" not in content[0].name
    outside = [
        p for p in store.root.rglob("*") if p.is_file() and store.ocfl not in p.parents and "locks" not in p.parts
    ]
    assert outside == []


@pytest.mark.spec("req-tap-files-naming-8")
@pytest.mark.parametrize("name", ["é" * 100 + ".json", "a" * 255, "s" * 100 + "." + "e" * 16])
def test_the_stored_name_fits_one_path_element(store: LocalBackend, name: str) -> None:
    ident = new_id()
    store.create(ident, name, data("x"), "t")
    (content,) = (store.ocfl / layout.object_path(ident) / "v1" / "content").iterdir()
    assert content.name.isascii() and len(content.name.encode()) <= 255
    assert read_all(store.open(ident)) == b"x" and store.stat(ident).version(1).name == name


@pytest.mark.spec("req-tap-files-naming-5")
def test_the_logical_name_is_kept_exactly(store: LocalBackend) -> None:
    ident = new_id()
    name = "Rapport annuel — été 2026.pdf"
    store.create(ident, name, data("pdf"), "t")
    assert store.open(ident).name == name
    inventory = json.loads((store.ocfl / layout.object_path(ident) / inv.INVENTORY).read_bytes())
    assert inventory["versions"]["v1"]["state"][sha(b"pdf")] == [name]


# =========================================================================== immutability


@pytest.mark.spec("req-tap-files-immutable-1")
def test_earlier_versions_are_untouched(store: LocalBackend) -> None:
    ident = new_id()
    store.create(ident, "a", data("one"), "t")
    v1 = store.ocfl / layout.object_path(ident) / "v1"
    before = tree(v1)
    store.add_version(ident, 1, "a", data("two"), "t")
    store.rename(ident, 2, "b", "t")
    assert tree(v1) == before


@pytest.mark.spec("req-tap-files-immutable-2")
def test_a_rename_stores_no_bytes(store: LocalBackend) -> None:
    ident = new_id()
    store.create(ident, "a", data("one"), "t")
    count = len(list(store.ocfl.rglob("content/*")))
    result = store.rename(ident, 1, "b", "t")
    assert result.version == 2 and result.digest == sha(b"one")
    assert len(list(store.ocfl.rglob("content/*"))) == count
    v2 = store.ocfl / layout.object_path(ident) / "v2"
    assert sorted(p.name for p in v2.iterdir()) == [inv.INVENTORY, inv.SIDECAR]


@pytest.mark.spec("req-tap-files-immutable-3")
def test_there_is_no_delete_operation() -> None:
    from tap_files.store.protocol import StoreBackend

    names = {n for n in dir(StoreBackend) if not n.startswith("_")}
    assert names == {"create", "add_version", "rename", "open", "stat", "exists", "identifiers", "verify"}
    source = (_REPO / "tap_files" / "store" / "local.py").read_text(encoding="utf-8")
    # The only unlink in the store removes a staged temporary file, never a path under ocfl/.
    assert source.count("os.unlink(") == 1 and "os.unlink(temp)" in source
    assert "os.remove(" not in source and "shutil.rmtree(self.ocfl" not in source


@pytest.mark.spec("req-tap-files-immutable-4")
def test_a_stale_writer_is_refused(store: LocalBackend) -> None:
    ident = new_id()
    store.create(ident, "a", data("one"), "t")
    store.add_version(ident, 1, "a", data("two"), "t")
    before = tree(store.ocfl)
    with pytest.raises(VersionConflict) as raised:
        store.add_version(ident, 1, "a", data("three"), "t")
    assert (raised.value.expected, raised.value.head) == (1, 2)
    with pytest.raises(VersionConflict) as raised:
        store.rename(ident, 1, "b", "t")
    assert (raised.value.expected, raised.value.head) == (1, 2)
    assert tree(store.ocfl) == before


@pytest.mark.spec("req-tap-files-immutable-5")
def test_create_is_put_if_absent(store: LocalBackend) -> None:
    ident = new_id()
    store.create(ident, "a", data("one"), "t")
    before = tree(store.ocfl)
    with pytest.raises(ObjectExists):
        store.create(ident, "a", data("other"), "t")
    assert tree(store.ocfl) == before


@pytest.mark.spec("req-tap-files-immutable-6")
def test_content_is_read_only(store: LocalBackend) -> None:
    ident = new_id()
    store.create(ident, "a", data("one"), "t")
    store.add_version(ident, 1, "a", data("two"), "t")
    files = list(store.ocfl.rglob("content/*"))
    assert len(files) == 2
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o440 for p in files)
    source = (_REPO / "tap_files" / "store" / "local.py").read_text(encoding="utf-8")
    assert "O_RDWR" not in source.replace("os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)", "")


# =========================================================================== write path


@pytest.mark.spec("req-tap-files-write-1")
def test_bytes_are_exact(store: LocalBackend) -> None:
    raw = os.urandom(3 * 1024 * 1024 + 17)
    ident = new_id()
    result = store.create(ident, "blob.bin", data(raw), "t")
    assert result.digest == sha(raw) and result.size == len(raw)
    (content,) = store.ocfl.rglob("content/*")
    assert content.read_bytes() == raw


@pytest.mark.spec("req-tap-files-write-2")
def test_a_full_disk_fails_cleanly(store: LocalBackend, monkeypatch: pytest.MonkeyPatch) -> None:
    import errno

    def full(fd: int, chunk: bytes) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(store, "_write_chunk", full)
    ident = new_id()
    with pytest.raises(OSError, match="No space"):
        store.create(ident, "a", data("x" * 10), "t")
    assert not store.exists(ident) and list(store.staging.iterdir()) == []
    assert not (store.ocfl / layout.object_path(ident)).parent.exists()


@pytest.mark.spec("req-tap-files-write-3")
def test_a_declared_digest_is_checked(store: LocalBackend) -> None:
    ident = new_id()
    with pytest.raises(DigestMismatch):
        store.create(ident, "a", data("one"), "t", expected_digest=sha(b"two"))
    assert not store.exists(ident) and list(store.staging.iterdir()) == []
    assert store.create(ident, "a", data("one"), "t", expected_digest=sha(b"one")).version == 1


@pytest.mark.spec("req-tap-files-write-4")
@pytest.mark.parametrize("step", CREATE_STEPS[:5])
def test_an_interrupted_create_leaves_no_object(
    store: LocalBackend, step: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ident = new_id()
    kill_at(store, step, monkeypatch)
    with pytest.raises(_Killed):
        store.create(ident, "a", data("one"), "t")
    monkeypatch.undo()
    assert not store.exists(ident)
    store.recover()
    assert list(store.staging.iterdir()) == []
    assert not store.exists(ident)
    for path in store.ocfl.rglob("*"):
        if path.is_dir():
            assert any(path.iterdir()), path
    if step != "staged":
        assert any(store.quarantine.iterdir())
    assert store.create(ident, "a", data("one"), "t").version == 1


@pytest.mark.spec("req-tap-files-write-5")
@pytest.mark.parametrize("step", VERSION_STEPS[:5])
def test_an_interrupted_version_keeps_the_old_head(
    store: LocalBackend, step: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ident = new_id()
    store.create(ident, "a", data("one"), "t")
    kill_at(store, step, monkeypatch)
    with pytest.raises(_Killed):
        store.add_version(ident, 1, "a", data("two"), "t")
    monkeypatch.undo()
    assert read_all(store.open(ident)) == b"one"
    store.recover()
    assert store.verify(ident, deep=True).ok and store.stat(ident).head == 1


@pytest.mark.spec("req-tap-files-write-7")
def test_memory_stays_constant(store: LocalBackend) -> None:
    import tracemalloc

    from tap_files.store.local import CHUNK

    class Endless(io.RawIOBase):
        def __init__(self, total: int) -> None:
            self.left = total

        def readable(self) -> bool:
            return True

        def read(self, n: int = -1) -> bytes:
            n = min(n if n > 0 else CHUNK, self.left)
            self.left -= n
            return b"\x5a" * n

    tracemalloc.start()
    try:
        store.create(new_id(), "big.bin", Endless(32 * CHUNK), "t")  # type: ignore[arg-type]
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 6 * CHUNK, peak


@pytest.mark.spec("req-tap-files-write-8")
def test_recovery_removes_no_content(store: LocalBackend, monkeypatch: pytest.MonkeyPatch) -> None:
    ident = new_id()
    store.create(ident, "a", data("one"), "t")
    kill_at(store, "version_moved", monkeypatch)
    with pytest.raises(_Killed):
        store.add_version(ident, 1, "a", data("two"), "t")
    monkeypatch.undo()
    contents = {sha(p.read_bytes()) for p in store.root.rglob("content/*")}
    store.recover()
    after = {sha(p.read_bytes()) for p in store.root.rglob("content/*")}
    assert contents == after == {sha(b"one"), sha(b"two")}


@pytest.mark.spec("req-tap-files-write-9")
@pytest.mark.parametrize(
    ("operation", "step"), [("version", s) for s in VERSION_STEPS] + [("rename", s) for s in RENAME_STEPS]
)
def test_every_interruption_point_recovers(
    store: LocalBackend, operation: str, step: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    ident = new_id()
    store.create(ident, "a", data("one"), "t")
    kill_at(store, step, monkeypatch)
    with pytest.raises(_Killed):
        if operation == "version":
            store.add_version(ident, 1, "a", data("two"), "t")
        else:
            store.rename(ident, 1, "b", "t")
    monkeypatch.undo()
    store.recover()
    result = store.verify(ident, deep=True)
    assert result.ok, result.findings
    committed = step in ("root_inventory_replaced", "root_sidecar_replaced")
    assert store.stat(ident).head == (2 if committed else 1)
    expected = (b"two" if operation == "version" else b"one") if committed else b"one"
    assert read_all(store.open(ident)) == expected


@pytest.mark.spec("req-tap-files-write-10")
def test_the_root_pair_is_restored_from_a_version(store: LocalBackend, caplog: pytest.LogCaptureFixture) -> None:
    ident = new_id()
    store.create(ident, "a", data("one"), "t")
    store.add_version(ident, 1, "a", data("two"), "t")
    objdir = store.ocfl / layout.object_path(ident)
    os.replace(_write_tmp(store, b"0" * 64 + b"  inventory.json\n"), objdir / inv.SIDECAR)
    store.recover()
    assert read_all(store.open(ident)) == b"two"
    os.replace(_write_tmp(store, b'{"tampered": true}\n'), objdir / inv.INVENTORY)
    caplog.set_level(logging.WARNING)
    actions = store.recover()
    assert any("restored from v2" in a for a in actions)
    assert any("restored from v2" in r.getMessage() for r in caplog.records)
    assert read_all(store.open(ident)) == b"two"
    for name in ("v1", "v2"):
        os.replace(_write_tmp(store, b"broken"), objdir / name / inv.INVENTORY)
    os.replace(_write_tmp(store, b"broken"), objdir / inv.INVENTORY)
    before = tree(objdir)
    actions = store.recover()
    assert any("invalid" in a for a in actions) and tree(objdir) == before
    assert not store.verify(ident).ok


@pytest.mark.spec("req-tap-files-write-12")
def test_destination_directories_are_synced(store: LocalBackend, monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_files.store import local

    synced: list[Path] = []
    real = local._fsync_dir

    def recording(path: Path) -> None:
        synced.append(Path(path))
        real(path)

    monkeypatch.setattr(local, "_fsync_dir", recording)
    ident = new_id()
    store.create(ident, "a", data("one"), "t")
    objdir = store.ocfl / layout.object_path(ident)
    parents = [objdir.parent, objdir.parent.parent, objdir.parent.parent.parent]
    assert all(p in synced for p in parents)
    synced.clear()
    store.add_version(ident, 1, "a", data("two"), "t")
    assert synced.count(objdir) >= 3  # after the version move and after each root replacement


@pytest.mark.spec("req-tap-files-write-13")
def test_a_retry_after_a_failed_grid_write(store: LocalBackend) -> None:
    ident = new_id()
    store.create(ident, "a", data("one"), "t")
    store.add_version(ident, 1, "a", data("two"), "t")  # its grid write is then refused
    with pytest.raises(VersionConflict):
        store.add_version(ident, 1, "a", data("two"), "t")
    head = store.stat(ident).head
    assert head == 2
    before = tree(store.ocfl)
    again = store.add_version(ident, head, "a", data("two"), "t")
    assert (again.version, again.stored) == (2, False)
    assert tree(store.ocfl) == before


# =========================================================================== read path


@pytest.mark.spec("req-tap-files-read-1")
def test_altered_content_is_refused(store: LocalBackend) -> None:
    ident = new_id()
    store.create(ident, "a", data("original"), "t")
    (content,) = store.ocfl.rglob("content/*")
    content.chmod(0o644)
    content.write_bytes(b"0riginal")
    with pytest.raises(FileIntegrityError) as raised:
        store.open(ident)
    assert raised.value.kind == "content_digest"


@pytest.mark.spec("req-tap-files-read-2")
def test_an_altered_inventory_is_refused(store: LocalBackend) -> None:
    ident = new_id()
    store.create(ident, "a", data("original"), "t")
    objdir = store.ocfl / layout.object_path(ident)
    raw = (objdir / inv.INVENTORY).read_bytes().replace(b'"a"', b'"b"')
    os.replace(_write_tmp(store, raw), objdir / inv.INVENTORY)
    with pytest.raises(FileIntegrityError):
        store.open(ident)


@pytest.mark.spec("req-tap-files-read-3")
def test_missing_content_is_integrity_and_a_missing_object_is_not_found(store: LocalBackend) -> None:
    ident = new_id()
    store.create(ident, "a", data("one"), "t")
    (content,) = store.ocfl.rglob("content/*")
    content.unlink()
    with pytest.raises(FileIntegrityError) as raised:
        store.open(ident)
    assert raised.value.kind == "content_missing"
    with pytest.raises(StoredFileNotFound):
        store.open(new_id())


@pytest.mark.spec("req-tap-files-read-4")
def test_verified_before_the_first_byte(store: LocalBackend, monkeypatch: pytest.MonkeyPatch) -> None:
    ident = new_id()
    store.create(ident, "a", data(b"good" * 1000 + b"Z"), "t")
    (content,) = store.ocfl.rglob("content/*")
    content.chmod(0o644)
    raw = content.read_bytes()
    content.write_bytes(raw[:-1] + b"Y")
    delivered: list[Any] = []

    def recording_fdopen(*args: Any, **kwargs: Any) -> io.BytesIO:
        delivered.append(args)
        return io.BytesIO()

    monkeypatch.setattr(os, "fdopen", recording_fdopen)
    with pytest.raises(FileIntegrityError):
        store.open(ident)
    assert delivered == []


@pytest.mark.spec("req-tap-files-read-5")
def test_any_version_is_readable(store: LocalBackend) -> None:
    ident = new_id()
    store.create(ident, "first.txt", data("one"), "t")
    store.add_version(ident, 1, "second.txt", data("two"), "t")
    store.add_version(ident, 2, "third.txt", data("three"), "t")
    opened = store.open(ident, 1)
    assert (opened.name, read_all(opened)) == ("first.txt", b"one")


@pytest.mark.spec("req-tap-files-read-6")
def test_an_integrity_failure_raises_a_finding(store: LocalBackend, caplog: pytest.LogCaptureFixture) -> None:
    ident = new_id()
    store.create(ident, "a", data("original"), "t")
    (content,) = store.ocfl.rglob("content/*")
    content.chmod(0o644)
    content.write_bytes(b"changed!")
    caplog.set_level(logging.WARNING)
    with pytest.raises(FileIntegrityError):
        store.open(ident)
    concerns = [r for r in caplog.records if getattr(r, "message_code", None) == CONCERN_MESSAGE_CODE]
    findings = [r for r in caplog.records if "integrity failure" in r.getMessage()]
    assert len(concerns) == 1 and ident in concerns[0].getMessage() and "content_digest" in concerns[0].getMessage()
    assert len(findings) == 1 and "original" not in findings[0].getMessage()


@pytest.mark.spec("req-tap-files-read-8")
def test_the_verified_descriptor_is_delivered(store: LocalBackend, monkeypatch: pytest.MonkeyPatch) -> None:
    ident = new_id()
    store.create(ident, "a", data("payload"), "t")
    (content,) = store.ocfl.rglob("content/*")
    opens: list[int] = []
    real_open = os.open

    def recording(path: Any, *args: Any, **kwargs: Any) -> int:
        fd = real_open(path, *args, **kwargs)
        if Path(path) == content:
            opens.append(fd)
        return fd

    monkeypatch.setattr(os, "open", recording)
    opened = store.open(ident)
    try:
        assert len(opens) == 1 and opened.stream.fileno() == opens[0] and opened.stream.tell() == 0
        assert opened.stream.read() == b"payload"
    finally:
        opened.close()


# =========================================================================== history


@pytest.mark.spec("req-tap-files-history-1")
def test_every_version_is_named_in_the_inventory(store: LocalBackend) -> None:
    ident = new_id()
    store.create(ident, "a", data("one"), "alice", reason="first")
    store.add_version(ident, 1, "a", data("two"), "bob")
    store.rename(ident, 2, "b", "carol")
    inventory = json.loads((store.ocfl / layout.object_path(ident) / inv.INVENTORY).read_bytes())
    versions = inventory["versions"]
    assert sorted(versions) == ["v1", "v2", "v3"]
    assert [versions[v]["user"]["name"] for v in ("v1", "v2", "v3")] == ["alice", "bob", "carol"]
    assert versions["v1"]["message"] == "create: first" and all(versions[v]["created"] for v in versions)
    assert [list(versions[v]["state"].values())[0][0] for v in ("v1", "v2", "v3")] == ["a", "a", "b"]


@pytest.mark.spec("req-tap-files-history-2")
def test_past_bytes_are_retrievable(store: LocalBackend) -> None:
    ident = new_id()
    store.create(ident, "a", data("one"), "t")
    store.add_version(ident, 1, "a", data("two"), "t")
    past = store.stat(ident).version(1)
    opened = store.open(ident, past.number)
    assert opened.digest == past.digest and sha(read_all(opened)) == past.digest


# =========================================================================== round 2 of the AI review on PR# 1233


@pytest.mark.spec("req-tap-files-mount-gate-9")
@pytest.mark.parametrize("name", ["ocfl", "staging", "quarantine", "locks"])
def test_a_linked_store_directory_is_refused(tmp_path: Path, name: str) -> None:
    import shutil

    elsewhere = tmp_path / "elsewhere"
    root = tmp_path / "files"
    root.mkdir()
    real = LocalBackend(root)
    real.initialise()
    shutil.move(str(root / name), elsewhere)
    (root / name).symlink_to(elsewhere)
    before = tree(elsewhere)
    with pytest.raises(StoreRootRefused, match="not a real directory"):
        LocalBackend(root).initialise()
    with pytest.raises(StoreRootRefused, match="not a real directory"):
        LocalBackend(root).create(new_id(), "a", data("a"), "t")
    assert tree(elsewhere) == before


@pytest.mark.spec("req-tap-files-write-14")
def test_only_a_trustworthy_version_restores_the_root(store: LocalBackend) -> None:
    ident, other = new_id(), new_id()
    store.create(ident, "a", data("one"), "t")
    store.create(other, "b", data("other"), "t")
    objdir = store.ocfl / layout.object_path(ident)
    foreign = store.ocfl / layout.object_path(other)
    # An injected v9: another object's valid inventory pair.
    (objdir / "v9").mkdir()
    for name in (inv.INVENTORY, inv.SIDECAR):
        (objdir / "v9" / name).write_bytes((foreign / name).read_bytes())
    os.replace(_write_tmp(store, b"broken"), objdir / inv.INVENTORY)
    actions = store.recover_object(ident, locked=False)
    assert any("restored from v1" in a for a in actions), actions
    assert read_all(store.open(ident)) == b"one"


@pytest.mark.spec("req-tap-files-write-17")
def test_a_root_naming_another_object_is_not_trusted(store: LocalBackend) -> None:
    ident, other = new_id(), new_id()
    store.create(ident, "a", data("one"), "t")
    for n, text in ((1, "two"), (2, "three")):
        store.add_version(ident, n, "a", data(text), "t")
    store.create(other, "b", data("other"), "t")
    objdir = store.ocfl / layout.object_path(ident)
    foreign = store.ocfl / layout.object_path(other)
    # The other object's root pair is valid, and its head (v1) would put v2 and v3 above it.
    for name in (inv.INVENTORY, inv.SIDECAR):
        (objdir / name).write_bytes((foreign / name).read_bytes())
    actions = store.recover_object(ident, locked=False)
    assert any("restored from v3" in a for a in actions), actions
    assert not any("quarantine" in a.lower() or "above the head" in a for a in actions), actions
    assert sorted(p.name for p in objdir.glob("v*")) == ["v1", "v2", "v3"]
    assert read_all(store.open(ident)) == b"three"


@pytest.mark.spec("req-tap-files-write-17")
def test_a_foreign_root_with_no_version_to_restore_from_moves_nothing(store: LocalBackend) -> None:
    ident, other = new_id(), new_id()
    store.create(ident, "a", data("one"), "t")
    store.add_version(ident, 1, "a", data("two"), "t")
    store.create(other, "b", data("other"), "t")
    objdir = store.ocfl / layout.object_path(ident)
    foreign = store.ocfl / layout.object_path(other)
    for target in (objdir, objdir / "v1", objdir / "v2"):
        for name in (inv.INVENTORY, inv.SIDECAR):
            (target / name).write_bytes((foreign / name).read_bytes())
    before = sorted(str(p.relative_to(objdir)) for p in objdir.rglob("*"))
    actions = store.recover_object(ident, locked=False)
    assert any("invalid" in a for a in actions), actions
    assert sorted(str(p.relative_to(objdir)) for p in objdir.rglob("*")) == before
    assert not list(store.quarantine.iterdir())


@pytest.mark.spec("req-tap-files-write-15")
def test_short_writes_are_completed(store: LocalBackend, monkeypatch: pytest.MonkeyPatch) -> None:
    real_write = os.write

    def one_byte(fd: int, buf: Any) -> int:
        return real_write(fd, bytes(buf[:1]))

    monkeypatch.setattr(os, "write", one_byte)
    ident = new_id()
    store.create(ident, "short.json", data("short writes"), "t")
    monkeypatch.undo()
    result = store.verify(ident, deep=True)
    assert result.ok, result.findings
    assert read_all(store.open(ident)) == b"short writes"


@pytest.mark.spec("req-tap-files-write-16")
def test_shared_parents_do_not_collide(store: LocalBackend) -> None:
    # Two identifiers whose layout paths share the first hashed level.
    first = new_id()
    prefix = layout.object_path(first).split("/")[0]
    second = next(i for i in (new_id() for _ in range(100000)) if layout.object_path(i).startswith(prefix + "/"))
    go_r, go_w = os.pipe()
    pids = []
    for ident in (first, second):
        pid = os.fork()
        if pid == 0:  # pragma: no cover — the child
            code = 1
            try:
                os.read(go_r, 1)
                store.create(ident, "a", data(os.urandom(50000)), "t")
                code = 0
            finally:
                os._exit(code)
        pids.append(pid)
    os.write(go_w, b"gg")
    codes = []
    for pid in pids:
        _pid, status = os.waitpid(pid, 0)
        codes.append(os.waitstatus_to_exitcode(status))
    assert codes == [0, 0] and store.exists(first) and store.exists(second)


@pytest.mark.spec("req-tap-files-mount-gate-10")
@pytest.mark.parametrize("level", ["parent", "object", "content"])
def test_no_link_below_the_ocfl_root(store: LocalBackend, tmp_path: Path, level: str) -> None:
    import shutil

    ident = new_id()
    store.create(ident, "a", data("one"), "t")
    objdir = store.ocfl / layout.object_path(ident)
    target = {"parent": objdir.parent.parent.parent, "object": objdir, "content": objdir / "v1" / "content"}[level]
    outside = tmp_path / f"outside-{level}"
    shutil.move(str(target), outside)
    target.symlink_to(outside)
    before = tree(outside)
    with pytest.raises(FileIntegrityError, match="symbolic link"):
        store.open(ident)
    if level == "content":
        # A new version writes v2/ and recovery reads the object root: neither passes through
        # v1/content, so neither is redirected; verify reports the link.
        result = store.verify(ident)
        assert not result.ok and any("symbolic link" in f for f in result.findings), result.findings
    else:
        for call in (
            lambda: store.add_version(ident, 1, "a", data("two"), "t"),
            lambda: store.recover_object(ident, locked=False),
            lambda: store.create(ident, "b", data("b"), "t"),
        ):
            with pytest.raises(FileIntegrityError, match="symbolic link"):
                call()
    assert tree(outside) == before
