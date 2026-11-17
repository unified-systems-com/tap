"""The file store gateway: the gated operations programs call on stored bytes.

`specs/spec-tap-file-store.md`, `req-tap-files-gateway`. Every export is an operation carrying its
capability (`req-service-boundary-guard`). The actor is the caller context's, and no operation takes
one as an argument. No operation writes a grid node or edge: the holding helper (tap#1228) writes the
`tap_file` node through the grid's service layer once the bytes are stored here.

Results, errors and capability names are in :mod:`tap_files.services.contract`. Below this gate sit
boot's initialisation and recovery and the operator's check command, and nothing else reaches the
backend (`req-tap-files-gateway-5`, guard: files-backend-reach).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, BinaryIO

from tap_auth.enforcement import requires_capability
from tap_auth.errors import MissingActor
from tap_files.services._record import acting_user, actor_key, recorded
from tap_files.services.contract import FILES_CREATE, FILES_READ, FILES_UPDATE
from tap_files.store import get_store
from tap_files.store.protocol import ObjectStat, OpenedFile, StoredResult

if TYPE_CHECKING:
    from tap_grid.caller_context import CallerContext

__tap_contract_modules__ = ("contract",)


def _writer(caller_context: CallerContext | None) -> str:
    """The version's writer: the actor the capability gate authorised, never one the caller names.

    TAP-IMPLEMENTS: req-tap-files-gateway@fbeb4b71f4b9/17bac122c6cf (enforcement) — the writer recorded in
        a version's inventory entry comes from the caller context, here and nowhere else.
    """
    key = actor_key(acting_user(caller_context))
    if key is None:  # the gate admits no call without an actor; this keeps it true below the gate
        raise MissingActor("a file store write needs a named actor")
    return key


@recorded("store_file")
@requires_capability(FILES_CREATE, operation="store_file")
def store_file(
    identifier: str,
    name: str,
    stream: BinaryIO,
    *,
    reason: str = "",
    expected_digest: str | None = None,
    caller_context: CallerContext | None = None,
) -> StoredResult:
    """Store a new file as version 1 of the object *identifier* (``urn:uuid:`` of its node's entity)."""
    return get_store().create(
        identifier, name, stream, _writer(caller_context), reason=reason, expected_digest=expected_digest
    )


@recorded("add_file_version")
@requires_capability(FILES_UPDATE, operation="add_file_version")
def add_file_version(
    identifier: str,
    expected_version: int,
    name: str,
    stream: BinaryIO,
    *,
    reason: str = "",
    expected_digest: str | None = None,
    caller_context: CallerContext | None = None,
) -> StoredResult:
    """Add a version on top of *expected_version*; a stale expectation is a :class:`VersionConflict`."""
    return get_store().add_version(
        identifier,
        expected_version,
        name,
        stream,
        _writer(caller_context),
        reason=reason,
        expected_digest=expected_digest,
    )


@recorded("rename_file")
@requires_capability(FILES_UPDATE, operation="rename_file")
def rename_file(
    identifier: str,
    expected_version: int,
    name: str,
    *,
    reason: str = "",
    caller_context: CallerContext | None = None,
) -> StoredResult:
    """Record a new logical name as a new version that stores no new bytes."""
    return get_store().rename(identifier, expected_version, name, _writer(caller_context), reason=reason)


@recorded("open_file")
@requires_capability(FILES_READ, operation="open_file")
def open_file(
    identifier: str, version: int | None = None, *, caller_context: CallerContext | None = None
) -> OpenedFile:
    """A verified read of *version* (the head when omitted); the caller closes the stream."""
    return get_store().open(identifier, version)


@recorded("file_info")
@requires_capability(FILES_READ, operation="file_info")
def file_info(identifier: str, *, caller_context: CallerContext | None = None) -> ObjectStat:
    """The object's head and every version's name, digest, size, time and writer."""
    return get_store().stat(identifier)


@recorded("file_exists")
@requires_capability(FILES_READ, operation="file_exists")
def file_exists(identifier: str, *, caller_context: CallerContext | None = None) -> bool:
    """Whether an object is stored under *identifier*."""
    return get_store().exists(identifier)


__all__ = ["add_file_version", "file_exists", "file_info", "open_file", "rename_file", "store_file"]
