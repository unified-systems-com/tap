"""The file store's errors (`specs/spec-tap-file-store.md`).

Every failure a caller can see is one of these. An integrity failure is one error whatever its cause
(`req-tap-files-read`), distinct from a missing object or version, which is not found.
"""

from __future__ import annotations


class FileStoreError(Exception):
    """Base of every file store error."""


class FileStoreNotEnabled(FileStoreError):
    """``TAP_FILES_ROOT`` is unset: this instance has no file store (`req-tap-files-root-5`)."""


class StoredFileNotFound(FileStoreError):
    """No object under that identifier, or no such version of it."""


class ObjectExists(FileStoreError):
    """A create named an identifier that already has an object (`req-tap-files-immutable-5`)."""


class VersionConflict(FileStoreError):
    """The writer's expected version is not the head (`req-tap-files-immutable-4`)."""

    def __init__(self, identifier: str, expected: int, head: int, head_digest: str) -> None:
        super().__init__(f"{identifier}: expected version {expected}, but the head is version {head}")
        self.identifier = identifier
        self.expected = expected
        self.head = head
        self.head_digest = head_digest


class DigestMismatch(FileStoreError):
    """The bytes supplied do not have the digest the caller declared (`req-tap-files-write-3`)."""


class InvalidLogicalName(FileStoreError):
    """A logical name that is not one path element (`req-tap-files-naming`)."""


class InvalidIdentifier(FileStoreError):
    """An identifier that is not ``urn:uuid:`` and a canonical lower-case UUID."""


class StoreBusy(FileStoreError):
    """Another writer holds the object's lock beyond the bound a writer waits (`req-tap-files-write`)."""


class StoreRootRefused(FileStoreError):
    """The root holds content that is not this store's; core never adopts it (`req-tap-files-mount-gate`)."""


class FileIntegrityError(FileStoreError):
    """Stored content or its inventory does not match what was recorded (`req-tap-files-read`).

    Carries the identifier, the version and the kind of failure, and never any of the content.
    """

    def __init__(self, identifier: str, version: int | None, kind: str, detail: str = "") -> None:
        where = f"{identifier} v{version}" if version else identifier
        super().__init__(f"{where}: integrity failure ({kind}){': ' + detail if detail else ''}")
        self.identifier = identifier
        self.version = version
        self.kind = kind


__all__ = [
    "DigestMismatch",
    "FileIntegrityError",
    "FileStoreError",
    "FileStoreNotEnabled",
    "InvalidIdentifier",
    "InvalidLogicalName",
    "ObjectExists",
    "StoreBusy",
    "StoreRootRefused",
    "StoredFileNotFound",
    "VersionConflict",
]
