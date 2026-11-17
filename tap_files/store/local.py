"""The local backend: an OCFL 1.1 storage root on the local filesystem.

`specs/spec-tap-file-store.md`: `req-tap-files-root` (the four directories), `-mount-gate`
(initialisation), `-ocfl`, `-naming`, `-immutable`, `-write` (the write path and recovery) and
`-read` (verified reads). The only module that opens, lists or stats a path under the file store
root (`req-tap-files-interface-1`).

Writes never leave a partial file where a reader can find it: bytes stream to `staging/` while
hashed, the result is built and synced there, and moved into `ocfl/` by renames whose order makes
every interruption recoverable. For a new version the root inventory's replacement is the commit
point. Nothing under `ocfl/` is ever unlinked; recovery moves what an interrupted write left to
`quarantine/` and copies a root inventory only from a version inventory the store wrote and can
verify.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import secrets
import shutil
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import unquote

from tap.logging_signals import concern
from tap_files.store import inventory as inv
from tap_files.store.errors import (
    DigestMismatch,
    FileIntegrityError,
    ObjectExists,
    StoreBusy,
    StoredFileNotFound,
    StoreRootRefused,
    VersionConflict,
)
from tap_files.store.layout import (
    LAYOUT_CONFIG,
    LAYOUT_EXTENSION,
    check_identifier,
    check_logical_name,
    encode_identifier,
    object_path,
    parse_stored_filename,
    stored_filename,
)
from tap_files.store.protocol import ObjectStat, OpenedFile, StoredResult, VerifyResult, VersionInfo

logger = logging.getLogger(__name__)

OCFL_DIR, STAGING_DIR, QUARANTINE_DIR, LOCKS_DIR = "ocfl", "staging", "quarantine", "locks"
ROOT_DIRS = (OCFL_DIR, STAGING_DIR, QUARANTINE_DIR, LOCKS_DIR)
LAYOUT_FILE = "ocfl_layout.json"
CHUNK = 1024 * 1024
#: How long a writer, or a reader confirming a mismatch, waits for an object's lock.
LOCK_WAIT_S = 10.0
_LOCK_POLL_S = 0.02


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_new(path: Path, data: bytes, mode: int = 0o644) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


class LocalBackend:
    """The store on one local root. Construct with the root; nothing is touched until a call."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.ocfl = self.root / OCFL_DIR
        self.staging = self.root / STAGING_DIR
        self.quarantine = self.root / QUARANTINE_DIR
        self.locks = self.root / LOCKS_DIR

    # ------------------------------------------------------------------ test seams

    def _step(self, name: str) -> None:
        """A named point in a write; tests replace this to interrupt a write exactly there."""

    def _write_chunk(self, fd: int, data: bytes) -> None:
        """One bounded write into staging; tests replace this to simulate a full volume."""
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]

    # ------------------------------------------------------------------ initialisation

    def initialise(self) -> str:
        """Initialise an empty root, accept this store's own, refuse anything else.

        TAP-IMPLEMENTS: req-tap-files-mount-gate@c5a9542d429d/d039358d6d68 (derivation) — core never adopts
            content it did not create and never initialises over existing files.

        Returns ``"initialised"`` or ``"existing"``; raises :class:`StoreRootRefused` naming what it found.
        """
        entries = sorted(p.name for p in self.root.iterdir())
        if not entries:
            for name in ROOT_DIRS:
                os.mkdir(self.root / name, 0o750)
            _write_new(self.ocfl / inv.STORAGE_ROOT_MARKER, inv.STORAGE_ROOT_MARKER_TEXT.encode("ascii"))
            layout = {"extension": LAYOUT_EXTENSION, "description": "OCFL hash and identifier n-tuple storage layout"}
            _write_new(self.ocfl / LAYOUT_FILE, (json.dumps(layout, indent=2) + "\n").encode("ascii"))
            ext = self.ocfl / "extensions" / LAYOUT_EXTENSION
            ext.mkdir(parents=True)
            _write_new(ext / "config.json", (json.dumps(LAYOUT_CONFIG, indent=2) + "\n").encode("ascii"))
            for path in (ext, ext.parent, self.ocfl, self.root):
                _fsync_dir(path)
            logger.info("[1d69] files: initialised an empty store root at %s", self.root)
            return "initialised"
        problem = self._foreign(entries)
        if problem:
            raise StoreRootRefused(f"{self.root} is not empty and is not this store's: {problem}")
        return "existing"

    def _foreign(self, entries: list[str]) -> str:
        unexpected = [e for e in entries if e not in ROOT_DIRS]
        if unexpected:
            return f"unexpected entries {unexpected}"
        try:
            marker = (self.ocfl / inv.STORAGE_ROOT_MARKER).read_text(encoding="ascii")
            layout = json.loads((self.ocfl / LAYOUT_FILE).read_text(encoding="utf-8"))
            config = json.loads(
                (self.ocfl / "extensions" / LAYOUT_EXTENSION / "config.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            return f"no readable OCFL storage root ({type(exc).__name__}: {exc})"
        if marker != inv.STORAGE_ROOT_MARKER_TEXT:
            return "the storage-root marker is not OCFL 1.1"
        if layout.get("extension") != LAYOUT_EXTENSION or config != LAYOUT_CONFIG:
            return "the storage root uses a different layout"
        return ""

    def _require_ready(self) -> None:
        if not (self.ocfl / inv.STORAGE_ROOT_MARKER).is_file():
            raise StoreRootRefused(f"{self.root} has not been initialised; boot initialises it")

    # ------------------------------------------------------------------ locks

    def _lock_path(self, identifier: str) -> Path:
        return self.locks / f"{encode_identifier(identifier)}.lock"

    @contextmanager
    def _locked(self, identifier: str, *, wait: float = LOCK_WAIT_S) -> Iterator[None]:
        """Hold the object's exclusive ``flock`` for the block; :class:`StoreBusy` after *wait*.

        A lock file is never deleted: an unlinked lock file can be locked twice.
        """
        fd = os.open(self._lock_path(identifier), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        try:
            deadline = time.monotonic() + wait
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise StoreBusy(f"{identifier} is being written by another process") from None
                    time.sleep(_LOCK_POLL_S)
            yield
        finally:
            os.close(fd)

    # ------------------------------------------------------------------ reading an object's state

    def _object_dir(self, identifier: str) -> Path:
        return self.ocfl / object_path(identifier)

    def _read_pair(self, objdir: Path, where: str = "") -> tuple[bytes, bytes] | None:
        base = objdir / where if where else objdir
        try:
            return (base / inv.INVENTORY).read_bytes(), (base / inv.SIDECAR).read_bytes()
        except FileNotFoundError:
            return None

    def _inventory(self, identifier: str, *, confirm_with_lock: bool = True) -> dict[str, Any]:
        """The object's verified root inventory, confirming a mismatch under the lock before calling it one."""
        objdir = self._object_dir(identifier)
        pair = self._read_pair(objdir)
        if pair is None:
            raise StoredFileNotFound(f"no object {identifier}")
        data = inv.parse(*pair)
        if data is None and confirm_with_lock:
            # A write may be between replacing the root inventory and its sidecar.
            with self._locked(identifier):
                pair = self._read_pair(objdir)
                data = inv.parse(*pair) if pair else None
        if data is None or data["id"] != identifier:
            raise self._integrity(
                identifier, None, "inventory", "the root inventory does not match its sidecar or schema"
            )
        return data

    def _integrity(self, identifier: str, version: int | None, kind: str, detail: str) -> FileIntegrityError:
        error = FileIntegrityError(identifier, version, kind, detail)
        logger.error("[8d2f] files: integrity failure: %s", error)
        concern(logger, "files", "stored_file_integrity", f"{identifier} {kind}")
        return error

    def _stream_to(self, target: Path, stream: BinaryIO) -> tuple[str, int]:
        """Copy *stream* into a new file at *target* in bounded chunks, hashing as it goes."""
        digest = hashlib.sha256()
        size = 0
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            while True:
                chunk = stream.read(CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
                self._write_chunk(fd, chunk)
            os.fsync(fd)
        finally:
            os.close(fd)
        return digest.hexdigest(), size

    def _new_staging(self, identifier: str) -> Path:
        path = self.staging / f"{encode_identifier(identifier)}.{secrets.token_hex(6)}"
        os.mkdir(path, 0o700)
        return path

    # ------------------------------------------------------------------ writes

    def create(
        self,
        identifier: str,
        name: str,
        stream: BinaryIO,
        actor: str,
        reason: str = "",
        expected_digest: str | None = None,
    ) -> StoredResult:
        """Store a new object at version 1 (put-if-absent).

        TAP-IMPLEMENTS: req-tap-files-write@bdc69ac51e75/435732a87cc3 (derivation) — the write path: lock,
            stream and hash into staging, build, sync, then move into place.
        """
        uuid_text = check_identifier(identifier)
        check_logical_name(name)
        self._require_ready()
        with self._locked(identifier):
            self.recover_object(identifier, locked=True)
            objdir = self._object_dir(identifier)
            if objdir.exists():
                raise ObjectExists(f"{identifier} already has an object")
            stage = self._new_staging(identifier)
            try:
                staged_obj = stage / "object"
                content = staged_obj / "v1" / "content"
                content.mkdir(parents=True)
                temp = content / ".incoming"
                self._step("staged")
                digest, size = self._stream_to(temp, stream)
                self._step("hashed")
                if expected_digest is not None and expected_digest != digest:
                    raise DigestMismatch(f"{identifier}: expected {expected_digest}, received {digest}")
                filename = stored_filename(name, identifier, 1, digest)
                os.rename(temp, content / filename)
                os.chmod(content / filename, 0o444)
                record = inv.VersionRecord(1, digest, name, _now(), actor, self._message("create", reason))
                data = inv.serialise(inv.build(identifier, [record], {digest: [f"v1/content/{filename}"]}))
                side = inv.sidecar_text(data)
                _write_new(staged_obj / inv.OBJECT_MARKER, inv.OBJECT_MARKER_TEXT.encode("ascii"))
                for where in (staged_obj, staged_obj / "v1"):
                    _write_new(where / inv.INVENTORY, data)
                    _write_new(where / inv.SIDECAR, side)
                self._step("built")
                for path in (content, staged_obj / "v1", staged_obj):
                    _fsync_dir(path)
                self._step("synced")
                made = self._make_parents(objdir.parent)
                self._step("parents_made")
                os.rename(staged_obj, objdir)
                self._step("renamed")
                for path in [objdir.parent, *made]:
                    _fsync_dir(path)
                self._step("dirs_synced")
            except Exception:
                shutil.rmtree(stage, ignore_errors=True)
                self._prune_empty_parents(objdir.parent)
                raise
            shutil.rmtree(stage, ignore_errors=True)
        logger.info("[4620] files: created %s v1 (%s, %d bytes)", uuid_text, digest, size)
        return StoredResult(identifier, 1, digest, size)

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
        """Store new bytes as the next version; refuse a stale expected version."""
        check_identifier(identifier)
        check_logical_name(name)
        self._require_ready()
        with self._locked(identifier):
            self.recover_object(identifier, locked=True)
            data = self._inventory(identifier, confirm_with_lock=False)
            versions = inv.records(data)
            head = versions[-1]
            stage = self._new_staging(identifier)
            try:
                temp = stage / ".incoming"
                self._step("staged")
                digest, size = self._stream_to(temp, stream)
                self._step("hashed")
                if expected_digest is not None and expected_digest != digest:
                    raise DigestMismatch(f"{identifier}: expected {expected_digest}, received {digest}")
                if expected_version != head.number:
                    raise VersionConflict(identifier, expected_version, head.number, head.digest)
                if digest == head.digest and name == head.name:
                    # A retry offering the bytes the head already holds: told so, and nothing is stored.
                    return StoredResult(identifier, head.number, digest, size, stored=False)
                number = head.number + 1
                filename = stored_filename(name, identifier, number, digest)
                manifest = dict(data["manifest"])
                if digest in manifest:
                    os.unlink(temp)
                    content_paths: list[str] = []
                else:
                    content_paths = [f"{inv.vname(number)}/content/{filename}"]
                    manifest[digest] = content_paths
                record = inv.VersionRecord(number, digest, name, _now(), actor, self._message("add_version", reason))
                result = self._commit_version(identifier, data, versions, record, manifest, stage, temp, filename)
            finally:
                shutil.rmtree(stage, ignore_errors=True)
        logger.info("[dc31] files: added %s v%d (%s, %d bytes)", identifier, number, digest, size)
        return StoredResult(identifier, result, digest, size)

    def rename(self, identifier: str, expected_version: int, name: str, actor: str, reason: str = "") -> StoredResult:
        """Record a new logical name as the next version; no bytes are written."""
        check_identifier(identifier)
        check_logical_name(name)
        self._require_ready()
        with self._locked(identifier):
            self.recover_object(identifier, locked=True)
            data = self._inventory(identifier, confirm_with_lock=False)
            versions = inv.records(data)
            head = versions[-1]
            if expected_version != head.number:
                raise VersionConflict(identifier, expected_version, head.number, head.digest)
            number = head.number + 1
            record = inv.VersionRecord(number, head.digest, name, _now(), actor, self._message("rename", reason))
            stage = self._new_staging(identifier)
            try:
                self._step("staged")
                self._commit_version(identifier, data, versions, record, dict(data["manifest"]), stage, None, None)
            except Exception:
                shutil.rmtree(stage, ignore_errors=True)
                raise
            shutil.rmtree(stage, ignore_errors=True)
            size = self._content_size(identifier, data, head.digest)
        logger.info("[609b] files: renamed %s at v%d", identifier, number)
        return StoredResult(identifier, number, head.digest, size)

    def _commit_version(
        self,
        identifier: str,
        data: dict[str, Any],
        versions: list[inv.VersionRecord],
        record: inv.VersionRecord,
        manifest: dict[str, list[str]],
        stage: Path,
        temp: Path | None,
        filename: str | None,
    ) -> int:
        """Build a version directory in staging, move it in, then replace the root pair (the commit)."""
        objdir = self._object_dir(identifier)
        vdir = stage / inv.vname(record.number)
        vdir.mkdir()
        if temp is not None and temp.exists() and filename is not None:
            content = vdir / "content"
            content.mkdir()
            os.rename(temp, content / filename)
            os.chmod(content / filename, 0o444)
            _fsync_dir(content)
        new = inv.serialise(inv.build(identifier, [*versions, record], manifest))
        side = inv.sidecar_text(new)
        _write_new(vdir / inv.INVENTORY, new)
        _write_new(vdir / inv.SIDECAR, side)
        _write_new(stage / ".root-inventory", new)
        _write_new(stage / ".root-sidecar", side)
        self._step("built")
        _fsync_dir(vdir)
        _fsync_dir(stage)
        self._step("synced")
        os.rename(vdir, objdir / inv.vname(record.number))
        _fsync_dir(objdir)
        self._step("version_moved")
        os.replace(stage / ".root-inventory", objdir / inv.INVENTORY)
        _fsync_dir(objdir)
        self._step("root_inventory_replaced")
        os.replace(stage / ".root-sidecar", objdir / inv.SIDECAR)
        _fsync_dir(objdir)
        self._step("root_sidecar_replaced")
        return record.number

    def _make_parents(self, parent: Path) -> list[Path]:
        made: list[Path] = []
        missing = []
        cursor = parent
        while not cursor.exists():
            missing.append(cursor)
            cursor = cursor.parent
        for path in reversed(missing):
            os.mkdir(path, 0o750)
            made.append(path)
        return made

    def _prune_empty_parents(self, parent: Path) -> None:
        """Remove empty hashed parents left by a create that did not finish; only empty ones, only under ocfl/."""
        cursor = parent
        while cursor != self.ocfl and self.ocfl in cursor.parents:
            try:
                os.rmdir(cursor)
            except OSError:
                return
            cursor = cursor.parent

    @staticmethod
    def _message(operation: str, reason: str) -> str:
        return f"{operation}: {reason}" if reason else operation

    # ------------------------------------------------------------------ reads

    def open(self, identifier: str, version: int | None = None) -> OpenedFile:
        """Verify the requested version's bytes against the inventory, then return that same descriptor.

        TAP-IMPLEMENTS: req-tap-files-read@5bd5dcf0a848/979828599411 (enforcement) — no byte leaves the store
            before the whole content file has been hashed and matched.
        """
        check_identifier(identifier)
        self._require_ready()
        data = self._inventory(identifier)
        versions = inv.records(data)
        number = versions[-1].number if version is None else version
        if not 1 <= number <= len(versions):
            raise StoredFileNotFound(f"{identifier} has no version {number}")
        record = versions[number - 1]
        paths = data["manifest"].get(record.digest)
        if not paths:
            raise self._integrity(identifier, number, "manifest", "no content path for the version's digest")
        path = self._object_dir(identifier) / paths[0]
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            raise self._integrity(identifier, number, "content_missing", "the content file is missing") from None
        try:
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = os.read(fd, CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
            if digest.hexdigest() != record.digest:
                raise self._integrity(identifier, number, "content_digest", "the content does not match its digest")
            os.lseek(fd, 0, os.SEEK_SET)
        except BaseException:
            os.close(fd)
            raise
        return OpenedFile(identifier, number, record.name, record.digest, size, os.fdopen(fd, "rb"))

    def stat(self, identifier: str) -> ObjectStat:
        """The head and every version's name, digest, size, time and actor; reads no content."""
        check_identifier(identifier)
        self._require_ready()
        data = self._inventory(identifier)
        versions = tuple(
            VersionInfo(r.number, r.name, r.digest, self._content_size(identifier, data, r.digest), r.created, r.actor)
            for r in inv.records(data)
        )
        return ObjectStat(identifier, versions[-1].number, versions)

    def _content_size(self, identifier: str, data: dict[str, Any], digest: str) -> int:
        paths = data["manifest"].get(digest) or []
        try:
            return os.lstat(self._object_dir(identifier) / paths[0]).st_size if paths else -1
        except FileNotFoundError:
            return -1

    def exists(self, identifier: str) -> bool:
        check_identifier(identifier)
        return (self._object_dir(identifier) / inv.OBJECT_MARKER).is_file()

    def identifiers(self) -> Iterator[str]:
        """Every object identifier, read from the layout's last path level; opens no inventory."""
        if not self.ocfl.is_dir():
            return
        for first in sorted(self.ocfl.iterdir()):
            if first.name == "extensions" or not first.is_dir() or len(first.name) != 3:
                continue
            for second in sorted(first.iterdir()):
                for third in sorted(second.iterdir()):
                    for objdir in sorted(third.iterdir()):
                        if (objdir / inv.OBJECT_MARKER).is_file():
                            yield unquote(objdir.name)

    # ------------------------------------------------------------------ verify

    def verify(self, identifier: str, deep: bool = False) -> VerifyResult:
        """Check an object's structure against this specification; with *deep*, re-hash every content file."""
        check_identifier(identifier)
        objdir = self._object_dir(identifier)
        findings: list[str] = []
        try:
            if (objdir / inv.OBJECT_MARKER).read_text(encoding="ascii") != inv.OBJECT_MARKER_TEXT:
                findings.append("object marker is not OCFL 1.1")
        except OSError:
            return VerifyResult(identifier, False, ("no object marker",))
        pair = self._read_pair(objdir)
        data = inv.parse(*pair) if pair else None
        if data is None:
            return VerifyResult(identifier, False, (*findings, "root inventory missing, mismatched or invalid"))
        if data["id"] != identifier:
            findings.append("inventory id differs from the identifier")
        head = len(data["versions"])
        expected = {inv.OBJECT_MARKER, inv.INVENTORY, inv.SIDECAR, *(inv.vname(n) for n in range(1, head + 1))}
        present = {p.name for p in objdir.iterdir()}
        if present != expected:
            findings.append(f"object root holds {sorted(present ^ expected)} beyond or short of what OCFL allows")
        for n in range(1, head + 1):
            vpair = self._read_pair(objdir, inv.vname(n))
            if vpair is None or inv.parse(*vpair) is None:
                findings.append(f"{inv.vname(n)} inventory missing, mismatched or invalid")
        head_pair = self._read_pair(objdir, inv.vname(head))
        if head_pair and pair and head_pair[0] != pair[0]:
            findings.append("root inventory differs from the head version's")
        uuid_text = check_identifier(identifier)
        for digest, paths in data["manifest"].items():
            for rel in paths:
                path = objdir / rel
                try:
                    st = os.lstat(path)
                except FileNotFoundError:
                    findings.append(f"{rel} is missing")
                    continue
                if stat.S_IMODE(st.st_mode) != 0o444:
                    findings.append(f"{rel} is not read-only")
                try:
                    f_uuid, f_version, f_digest = parse_stored_filename(Path(rel).name)
                    if (f_uuid, f"v{f_version}", f_digest) != (uuid_text, rel.split("/")[0], digest):
                        findings.append(f"{rel} is misnamed")
                except ValueError:
                    findings.append(f"{rel} is not a stored filename")
                if deep and self._hash(path) != digest:
                    findings.append(f"{rel} does not match its digest")
        return VerifyResult(identifier, not findings, tuple(findings))

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(CHUNK), b""):
                digest.update(chunk)
        return digest.hexdigest()

    # ------------------------------------------------------------------ recovery

    def recover(self) -> list[str]:
        """Put right what interrupted writes left, for every object; skip any object being written.

        TAP-IMPLEMENTS: req-tap-files-write@bdc69ac51e75/8a88d5d86c16 (enforcement) — the recovery sweep:
            quarantine, never unlink; restore a root pair only from a verified version inventory.
        """
        actions: list[str] = []
        for entry in sorted(self.staging.iterdir()) if self.staging.is_dir() else []:
            identifier = unquote(entry.name.split(".", 1)[0])
            try:
                with self._locked(identifier, wait=0):
                    if entry.exists():
                        actions.append(self._quarantine(entry, "staging left by an interrupted write"))
            except StoreBusy:
                continue
        for identifier in list(self._object_candidates()):
            try:
                actions.extend(self.recover_object(identifier, locked=False))
            except StoreBusy:
                continue
        return actions

    def _object_candidates(self) -> Iterator[str]:
        """Every object directory, and every hashed parent chain, under ocfl/ (markers optional)."""
        if not self.ocfl.is_dir():
            return
        for first in sorted(self.ocfl.iterdir()):
            if first.name == "extensions" or not first.is_dir():
                continue
            for second in sorted(first.iterdir()):
                for third in sorted(second.iterdir()):
                    children = sorted(third.iterdir())
                    if not children:
                        self._prune_empty_parents(third)
                    for objdir in children:
                        yield unquote(objdir.name)

    def recover_object(self, identifier: str, *, locked: bool) -> list[str]:
        """Recover one object; *locked* says the caller already holds its lock."""
        if not locked:
            with self._locked(identifier, wait=0):
                return self.recover_object(identifier, locked=True)
        actions: list[str] = []
        objdir = self._object_dir(identifier)
        for entry in sorted(self.staging.glob(f"{encode_identifier(identifier)}.*")) if self.staging.is_dir() else []:
            actions.append(self._quarantine(entry, "staging left by an interrupted write"))
        if not objdir.exists():
            self._prune_empty_parents(objdir.parent)
            return actions
        pair = self._read_pair(objdir)
        if pair is None or inv.parse(*pair) is None:
            actions.extend(self._repair_root_pair(identifier, objdir, pair))
        pair = self._read_pair(objdir)
        data = inv.parse(*pair) if pair else None
        if data is None:
            return actions
        head = len(data["versions"])
        for vdir in sorted(objdir.glob("v*")):
            if vdir.is_dir() and vdir.name[1:].isdigit() and int(vdir.name[1:]) > head:
                actions.append(self._quarantine(vdir, f"version above the head v{head}: interrupted before its commit"))
        return actions

    def _repair_root_pair(self, identifier: str, objdir: Path, pair: tuple[bytes, bytes] | None) -> list[str]:
        valid: list[tuple[int, bytes, bytes]] = []
        for vdir in objdir.glob("v*"):
            if not (vdir.is_dir() and vdir.name[1:].isdigit()):
                continue
            vpair = self._read_pair(objdir, vdir.name)
            if vpair is not None and inv.parse(*vpair) is not None:
                valid.append((int(vdir.name[1:]), *vpair))
        if pair is not None:
            for number, vinv, vside in valid:
                if vinv == pair[0]:
                    self._replace_root(objdir, None, vside)
                    return [f"{identifier}: root sidecar completed from v{number} (the commit had happened)"]
        if not valid:
            logger.error("[4456] files: %s has no valid version inventory; left as it is", identifier)
            return [f"{identifier}: invalid, no version inventory to restore from"]
        number, vinv, vside = max(valid)
        self._replace_root(objdir, vinv, vside)
        logger.error("[ba0d] files: integrity finding: %s root inventory restored from v%d", identifier, number)
        concern(logger, "files", "stored_file_integrity", f"{identifier} root inventory restored from v{number}")
        return [f"{identifier}: root inventory pair restored from v{number}"]

    def _replace_root(self, objdir: Path, inventory_bytes: bytes | None, sidecar_bytes: bytes) -> None:
        for data, name in ((inventory_bytes, inv.INVENTORY), (sidecar_bytes, inv.SIDECAR)):
            if data is None:
                continue
            # Named for its object, like every staging entry, so that object's lock governs it.
            temp = self.staging / f"{objdir.name}.restore-{secrets.token_hex(6)}"
            _write_new(temp, data)
            os.replace(temp, objdir / name)
            _fsync_dir(objdir)

    def _quarantine(self, path: Path, why: str) -> str:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        target = self.quarantine / f"{stamp}-{path.name}"
        os.rename(path, target)
        note = {"was": str(path.relative_to(self.root)), "why": why, "found_at": _now()}
        _write_new(self.quarantine / f"{target.name}.note.json", (json.dumps(note, indent=2) + "\n").encode("utf-8"))
        _fsync_dir(self.quarantine)
        logger.warning("[ec1d] files: recovery moved %s to quarantine: %s", note["was"], why)
        return f"quarantined {note['was']}: {why}"


#: The write steps a test can interrupt, in order, per operation.
CREATE_STEPS = ("staged", "hashed", "built", "synced", "parents_made", "renamed", "dirs_synced")
VERSION_STEPS = (
    "staged",
    "hashed",
    "built",
    "synced",
    "version_moved",
    "root_inventory_replaced",
    "root_sidecar_replaced",
)
RENAME_STEPS = ("staged", "built", "synced", "version_moved", "root_inventory_replaced", "root_sidecar_replaced")

__all__ = ["CREATE_STEPS", "LocalBackend", "RENAME_STEPS", "ROOT_DIRS", "VERSION_STEPS"]
