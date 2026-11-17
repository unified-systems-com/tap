"""The store's backend protocol: whole-file operations and nothing a plain object store can't do.

`specs/spec-tap-file-store.md`, `req-tap-files-interface`. No partial write, no append, no in-place
edit, no rename of stored bytes, no listing by name, no lock a caller can hold. OCFL is the local
backend's on-disk format and is not part of this protocol.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import BinaryIO, Protocol


@dataclass(frozen=True)
class StoredResult:
    """What a write returns: the object's new head, or the version that already held the bytes."""

    identifier: str
    version: int
    digest: str
    size: int
    #: False when the bytes offered were already the head's and nothing was written.
    stored: bool = True


@dataclass(frozen=True)
class VersionInfo:
    number: int
    name: str
    digest: str
    size: int
    created: str
    actor: str


@dataclass(frozen=True)
class ObjectStat:
    identifier: str
    head: int
    versions: tuple[VersionInfo, ...]

    def version(self, number: int) -> VersionInfo:
        return self.versions[number - 1]


@dataclass
class OpenedFile:
    """A verified read: the stream is the descriptor whose bytes were hashed, at its first byte."""

    identifier: str
    version: int
    name: str
    digest: str
    size: int
    stream: BinaryIO

    def close(self) -> None:
        self.stream.close()


@dataclass(frozen=True)
class VerifyResult:
    identifier: str
    ok: bool
    findings: tuple[str, ...] = field(default_factory=tuple)


class StoreBackend(Protocol):
    """Every operation the store offers; the gateway (tap#1209) is the only caller outside tests."""

    def create(
        self,
        identifier: str,
        name: str,
        stream: BinaryIO,
        actor: str,
        reason: str = "",
        expected_digest: str | None = None,
    ) -> StoredResult: ...

    def add_version(
        self,
        identifier: str,
        expected_version: int,
        name: str,
        stream: BinaryIO,
        actor: str,
        reason: str = "",
        expected_digest: str | None = None,
    ) -> StoredResult: ...

    def rename(
        self, identifier: str, expected_version: int, name: str, actor: str, reason: str = ""
    ) -> StoredResult: ...

    def open(self, identifier: str, version: int | None = None) -> OpenedFile: ...

    def stat(self, identifier: str) -> ObjectStat: ...

    def exists(self, identifier: str) -> bool: ...

    def identifiers(self) -> Iterator[str]: ...

    def verify(self, identifier: str, deep: bool = False) -> VerifyResult: ...


__all__ = ["ObjectStat", "OpenedFile", "StoreBackend", "StoredResult", "VerifyResult", "VersionInfo"]
