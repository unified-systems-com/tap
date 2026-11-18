"""Holding a file: store the bytes through the gateway, then write the nodes that represent them.

`specs/spec-tap-file-store.md`, `req-tap-files-hold`. This is the one writer of `tap_file`,
`tap_directory`, `CONTAINS_TAP_DIRECTORY` and `CONTAINS_TAP_FILE` (`req-tap-files-node`, ruled
2026-11-17), so the rules no grid declaration can hold are held here:

- every `tap_file` is held, because the bytes are stored before its node is written;
- a directory has at most one parent and a file sits in at most one directory, because a containment
  edge is written only beside the node it makes, and only into a node that has no parent yet;
- a path agrees with its chain of containment edges, because both are derived from the same path;
- a replaced file never keeps the format record of its old bytes, because the patch that records the
  new bytes removes the file's ``FILE_CONTENTS`` edge in the same write.

The caller attaches the format record for the bytes in its own batch, naming the identifier this
returns. A file and its record do not land together, and that is accepted (ruled 2026-11-17).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, BinaryIO, cast

from django.db import transaction

from tap_auth.capabilities import WRITE_CAPABILITY
from tap_auth.enforcement import assert_program_actor, requires_capability
from tap_files.models import TapDirectory, TapFile, path_problem
from tap_files.services import add_file_version, file_info, store_file
from tap_files.services.contract import StoredResult
from tap_grid.service_types import WriteOperation

if TYPE_CHECKING:
    from tap_grid.caller_context import CallerContext

FILE_TYPE = TapFile.ENTITY_TYPE
DIRECTORY_TYPE = TapDirectory.ENTITY_TYPE
CONTAINS_FILE = "CONTAINS_TAP_FILE"
CONTAINS_DIRECTORY = "CONTAINS_TAP_DIRECTORY"
FILE_CONTENTS = "FILE_CONTENTS"
_URN = "urn:uuid:"


class HoldError(Exception):
    """The file could not be held as asked; the message says why, and what the store now holds."""


@dataclass(frozen=True)
class HeldFile:
    """What holding produced: the node's entity id, the object identifier, and the store's facts."""

    entity_id: uuid.UUID
    identifier: str
    file_version: int
    sha256: str
    size_bytes: int
    #: False when the bytes were already the version the node records, and nothing was written.
    changed: bool


def identifier_for(entity_id: uuid.UUID | str) -> str:
    """The store identifier of a `tap_file`: ``urn:uuid:`` and its entity id (`req-tap-files-hold-3`)."""
    return _URN + str(entity_id).lower()


def _split(path: str) -> tuple[list[str], str]:
    problem = path_problem(path)
    if problem:
        raise HoldError(f"{path!r}: {problem}")
    parts = path[1:].split("/")
    return ["/" + "/".join(parts[: i + 1]) for i in range(len(parts) - 1)], parts[-1]


def _resolve_actor(caller_context: CallerContext | None) -> CallerContext | None:
    if caller_context is not None and caller_context.user is not None:
        return caller_context
    from tap_grid.caller_context import get_caller_context

    return get_caller_context() or caller_context


def _write(operations: list[WriteOperation], caller_context: CallerContext | None, label: str) -> None:
    """One labelled batch of the helper's own, written by the caller's actor through the bypass.

    The helper's write is one unit (`req-tap-files-hold`), so it mints its own batch rather than
    joining one the caller's context holds, and names it (`req-grid-service-batch-label-required`).
    """
    from tap_grid.caller_context import CallerContext
    from tap_grid.services import write_batch

    own = CallerContext(
        user=caller_context.user if caller_context is not None else None,
        batch_name=label,
        batch_description="The file store's holding helper (req-tap-files-hold).",
    )
    # Reached only from hold_file, which is gated on grid.write; write_batch re-checks the actor too.
    result = write_batch(  # TAP-AUTHZ-COV: gated by hold_file
        operations, caller_context=own, _internal_only_bypass=True
    )
    if not result.success:
        errors = [e for r in result.results for e in r.errors] + list(result.errors)
        raise HoldError(f"the grid refused the write: {errors}")


def _directory_ops(
    dirs: list[str], caller_context: CallerContext | None
) -> tuple[list[WriteOperation], uuid.UUID | None]:
    """Create each directory on the path that does not exist yet, under the identity lock.

    A directory is made only together with its one containment edge from its parent, so no
    directory gains a second parent here. Returns the operations and the innermost directory's id.
    """
    from tap_grid.services import resolve_identity

    ops: list[WriteOperation] = []
    parent: uuid.UUID | None = None
    for path in dirs:
        resolution = resolve_identity(DIRECTORY_TYPE, {"path": path}, caller_context=caller_context)
        here = uuid.UUID(str(resolution.entity_id))
        if not resolution.found:
            ops.append(
                WriteOperation(
                    verb="create_node",
                    type_slug=DIRECTORY_TYPE,
                    entity_id=here,
                    payload={"name": path.rsplit("/", 1)[1], "path": path},
                )
            )
            if parent is not None:
                ops.append(_link(parent, here, CONTAINS_DIRECTORY))
        parent = here
    return ops, parent


def _link(parent: uuid.UUID, child: uuid.UUID, edge_type: str) -> WriteOperation:
    return WriteOperation(verb="create_edge", from_target=parent, to_target=child, edge_type=edge_type, payload={})


def _held(entity_id: uuid.UUID, result: StoredResult, changed: bool) -> HeldFile:
    return HeldFile(entity_id, result.identifier, result.version, result.digest, result.size, changed)


@requires_capability(WRITE_CAPABILITY, operation="hold_file")
def hold_file(
    path: str,
    stream: BinaryIO,
    *,
    media_type: str | None = None,
    reason: str = "",
    caller_context: CallerContext | None = None,
) -> HeldFile:
    """Hold the bytes in *stream* as the file at *path*, and return what was written.

    TAP-IMPLEMENTS: req-tap-files-hold@95d4c1ff3a4e/2fa7aa5d4175 (enforcement) — bytes are stored
        before any node, the node carries only what the store returned, and a replacement drops the
        old bytes' format record in the same write.

    A new path is a new file: an entity id is minted, the bytes stored under it, and the node, any
    missing directories and their containment edges written in one batch. An existing path is the
    same file: a new version is stored after the store's head (or the head is used when it already
    holds these bytes, as after a refused grid write) and the node is patched, naming the version
    it was read at. A caller that is not a program actor is refused before anything is stored.
    """
    ctx = _resolve_actor(caller_context)
    assert_program_actor(ctx, operation="hold_file")
    dirs, name = _split(path)
    existing = cast("TapFile | None", TapFile.objects.filter(path=path).select_related("entity").first())
    if existing is None:
        return _hold_new(path, dirs, name, stream, media_type, reason, ctx)
    return _hold_version(existing, stream, media_type, reason, ctx)


def _hold_new(
    path: str,
    dirs: list[str],
    name: str,
    stream: BinaryIO,
    media_type: str | None,
    reason: str,
    ctx: CallerContext | None,
) -> HeldFile:
    entity_id = uuid.uuid4()
    stored = store_file(identifier_for(entity_id), name, stream, reason=reason, caller_context=ctx)
    from tap_grid.services import resolve_identity

    with transaction.atomic():
        resolution = resolve_identity(FILE_TYPE, {"path": path}, caller_context=ctx, provisional=entity_id)
        if resolution.found:
            raise HoldError(
                f"{path!r} was held by another writer meanwhile; the bytes just stored under "
                f"{stored.identifier} are recorded by no node, and the check reports them"
            )
        ops, parent = _directory_ops(dirs, ctx)
        ops.append(
            WriteOperation(
                verb="create_node",
                type_slug=FILE_TYPE,
                entity_id=entity_id,
                payload={
                    "name": name,
                    "path": path,
                    "media_type": media_type,
                    "size_bytes": stored.size,
                    "sha256": stored.digest,
                    "file_version": stored.version,
                },
            )
        )
        if parent is not None:
            ops.append(_link(parent, entity_id, CONTAINS_FILE))
        _write(ops, ctx, f"hold {path}")
    return _held(entity_id, stored, True)


def _hold_version(
    node: TapFile, stream: BinaryIO, media_type: str | None, reason: str, ctx: CallerContext | None
) -> HeldFile:
    from tap_grid.models import Edge

    entity_id = node.entity_id
    identifier = identifier_for(entity_id)
    # The store may be ahead of the node after a refused grid write: store after its head, and when
    # the head already holds these bytes the store says so and writes nothing.
    head = file_info(identifier, caller_context=ctx).head
    stored = add_file_version(identifier, head, node.name, stream, reason=reason, caller_context=ctx)
    if stored.version == node.file_version:
        return _held(entity_id, stored, False)
    payload: dict[str, object] = {"sha256": stored.digest, "size_bytes": stored.size, "file_version": stored.version}
    if media_type is not None:
        payload["media_type"] = media_type
    ops = [
        WriteOperation(
            verb="patch_node",
            target=entity_id,
            payload=payload,
            entity_expected_version=node.entity.version,
        )
    ]
    # The old bytes' format record no longer describes this file (req-tap-files-hold-9).
    for edge in Edge.objects.filter(from_entity_id=entity_id, edge_type=FILE_CONTENTS):
        ops.append(WriteOperation(verb="delete_edge", target=edge.entity_id, reason="resolved"))
    _write(ops, ctx, f"hold {node.path} v{stored.version}")
    return _held(entity_id, stored, True)


__all__ = ["HeldFile", "HoldError", "hold_file", "identifier_for"]
