"""The file store gateway's contract: what a caller catches, receives and names, and no operation.

`specs/spec-tap-file-store.md`, `req-tap-files-gateway` and `req-service-boundary-model-3`. Callers
import results, errors and capability names from here; the operations are in the gateway itself.
"""

from __future__ import annotations

from tap_files.store.errors import (
    DigestMismatch,
    FileIntegrityError,
    FileStoreError,
    FileStoreNotEnabled,
    InvalidIdentifier,
    InvalidLogicalName,
    ObjectExists,
    StoreBusy,
    StoredFileNotFound,
    VersionConflict,
)
from tap_files.store.protocol import ObjectStat, OpenedFile, StoredResult, VersionInfo

FILES_CREATE = "files.create"
FILES_READ = "files.read"
FILES_UPDATE = "files.update"
FILES_DELETE = "files.delete"

#: The ``message_code`` of the one record each gateway operation emits (`req-tap-files-logging`).
FILE_OPERATION_CODE = "FILE_OPERATION"

__all__ = [
    "FILES_CREATE",
    "FILES_DELETE",
    "FILES_READ",
    "FILES_UPDATE",
    "FILE_OPERATION_CODE",
    "DigestMismatch",
    "FileIntegrityError",
    "FileStoreError",
    "FileStoreNotEnabled",
    "InvalidIdentifier",
    "InvalidLogicalName",
    "ObjectExists",
    "ObjectStat",
    "OpenedFile",
    "StoreBusy",
    "StoredFileNotFound",
    "StoredResult",
    "VersionConflict",
    "VersionInfo",
]
