"""The grid side of the file store: `tap_file` and `tap_directory`, core types owned by this app.

`specs/spec-tap-file-store.md`, `req-tap-files-node` and `req-tap-files-directory` (ruled 2026-11-17).
Both are internal-only: the generic verbs and GRIFT refuse them, and the holding helper
(`tap_files.holding`) writes them through the trusted-internal path after the bytes are stored. No
plugin is needed for either to exist, and none is imported here.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from django.core.exceptions import ValidationError
from django.db import models

from tap_grid.models import BaseModel

SHA256_PATTERN = "^[0-9a-f]{64}$"
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def path_problem(path: Any) -> str | None:
    """Why *path* is not a logical path, or ``None`` when it is one (`req-tap-files-node-5`).

    A path starts with ``/``, separates with ``/``, and has no empty, ``.`` or ``..`` element, no
    trailing separator and no control character. It says where a node sits on the grid and never
    names anything on disk.
    """
    if not isinstance(path, str) or not path.startswith("/"):
        return "a path starts with '/'"
    if _CONTROL.search(path):
        return "a path holds no control character"
    if path.endswith("/"):
        return "a path has no trailing '/'"
    elements = path[1:].split("/")
    if any(element in ("", ".", "..") for element in elements):
        return "a path has no empty, '.' or '..' element"
    return None


def _check_path(path: Any, name: Any) -> None:
    problem = path_problem(path)
    if problem:
        raise ValidationError({"path": [f"{path!r}: {problem}"]})
    if path.rsplit("/", 1)[1] != name:
        raise ValidationError({"path": [f"{path!r} must end with '/' and the name {name!r}"]})


class TapFile(BaseModel):
    """A file TAP holds: its bytes are in the file store under this node's entity identifier.

    Found again by its path, which is its directory's path, a ``/`` and its name. It carries what the
    store returned about the bytes and nothing of the bytes themselves; what they are is recorded on
    a format record joined by ``FILE_CONTENTS``.
    """

    ENTITY_TYPE: ClassVar[str] = "tap_file"
    ENTITY_NAME: ClassVar[str] = "File"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "A file TAP holds in its file store. The node records where the file sits and what the store "
        "returned about its bytes; the bytes are downloaded through the store."
    )
    ENTITY_ICON: ClassVar[str] = "file"
    # Which dimensions held files carry is undecided (req-tap-files-dimensions, Backlog).
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {}
    INTERNAL_ONLY: ClassVar[bool] = True
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("path",)

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, dict[str, Any]]] = {
        "name": {"type": "string", "minLength": 1, "maxLength": 255},
        "path": {"type": "string", "minLength": 2, "maxLength": 4096},
        "media_type": {"type": ["string", "null"], "maxLength": 255},
        "size_bytes": {"type": "integer", "minimum": 0},
        "sha256": {"type": "string", "pattern": SHA256_PATTERN},
        "file_version": {"type": "integer", "minimum": 1},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name", "path", "size_bytes", "sha256", "file_version"]
    FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict[str, Any]]] = {
        "size_bytes": {"validation": "jsonschema", "schema": {"type": "integer", "minimum": 0}},
        "sha256": {"validation": "jsonschema", "schema": {"type": "string", "pattern": SHA256_PATTERN}},
        "file_version": {"validation": "jsonschema", "schema": {"type": "integer", "minimum": 1}},
    }

    name = models.CharField(max_length=255)
    path = models.CharField(max_length=4096, db_index=True)
    # Null means the writer declared no media type; nothing inspects the bytes to fill it in.
    media_type = models.CharField(max_length=255, null=True, blank=True, default=None)  # noqa: DJ001  (req-tap-files-node-2)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    file_version = models.PositiveIntegerField()

    class Meta(BaseModel.Meta):
        db_table = "tap_file"

    def validate(self) -> None:
        _check_path(self.path, self.name)

    def get_name(self) -> str:
        return self.name or ""

    def __str__(self) -> str:
        return self.path or self.name


class TapDirectory(BaseModel):
    """A named container of held files and other directories, with at most one parent.

    Retiring a directory retires what it contains (`CONTAINMENT_EDGES`); the store keeps the bytes.
    """

    ENTITY_TYPE: ClassVar[str] = "tap_directory"
    ENTITY_NAME: ClassVar[str] = "Directory"
    ENTITY_DESCRIPTION: ClassVar[str] = (
        "A directory in TAP's own tree of held files: a name and a path, containing files and other "
        "directories. It exists on the grid only, never on disk."
    )
    ENTITY_ICON: ClassVar[str] = "folder"
    # Which dimensions directories carry is undecided (req-tap-files-dimensions, Backlog).
    DEFAULT_DIMENSIONS: ClassVar[dict[str, str]] = {}
    INTERNAL_ONLY: ClassVar[bool] = True
    NATURAL_KEY: ClassVar[tuple[str, ...]] = ("path",)

    OUTBOUND_EDGES: ClassVar[list[dict[str, Any]]] = [
        {"nodes": [{"type": "tap_directory"}], "edges": [{"type": "CONTAINS_TAP_DIRECTORY"}]},
        {"nodes": [{"type": "tap_file"}], "edges": [{"type": "CONTAINS_TAP_FILE"}]},
    ]
    CONTAINMENT_EDGES: ClassVar[tuple[str, ...]] = ("CONTAINS_TAP_DIRECTORY", "CONTAINS_TAP_FILE")

    FIELD_CRUD_SCHEMA: ClassVar[dict[str, dict[str, Any]]] = {
        "name": {"type": "string", "minLength": 1, "maxLength": 255},
        "path": {"type": "string", "minLength": 2, "maxLength": 4096},
    }
    CREATE_REQUIRED: ClassVar[list[str]] = ["name", "path"]

    name = models.CharField(max_length=255)
    path = models.CharField(max_length=4096, db_index=True)

    class Meta(BaseModel.Meta):
        db_table = "tap_directory"

    def validate(self) -> None:
        _check_path(self.path, self.name)

    def get_name(self) -> str:
        return self.name or ""

    def __str__(self) -> str:
        return self.path or self.name


__all__ = ["SHA256_PATTERN", "TapDirectory", "TapFile", "path_problem"]
