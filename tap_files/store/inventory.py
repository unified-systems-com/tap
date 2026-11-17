"""OCFL inventories: building them, writing them byte-for-byte, and trusting them only after checks.

`specs/spec-tap-file-store.md`, `req-tap-files-ocfl`. Every inventory the store writes validates
against the shipped schema, and every inventory it reads is checked against its sidecar and the
schema before it is used. One digest and one logical path per version.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tap.jsonfiles import JsonFileError, validate_json

INVENTORY = "inventory.json"
SIDECAR = "inventory.json.sha256"
INVENTORY_TYPE = "https://ocfl.io/1.1/spec/#inventory"
STORAGE_ROOT_MARKER = "0=ocfl_1.1"
STORAGE_ROOT_MARKER_TEXT = "ocfl_1.1\n"
OBJECT_MARKER = "0=ocfl_object_1.1"
OBJECT_MARKER_TEXT = "ocfl_object_1.1\n"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "ocfl-inventory.schema.json"


@dataclass(frozen=True)
class VersionRecord:
    """One version as the inventory states it."""

    number: int
    digest: str
    name: str
    created: str
    actor: str
    message: str


def vname(number: int) -> str:
    return f"v{number}"


def vnumber(name: str) -> int:
    return int(name[1:])


def build(identifier: str, versions: list[VersionRecord], manifest: dict[str, list[str]]) -> dict[str, Any]:
    """The inventory for an object with *versions* (oldest first) and *manifest*."""
    return {
        "id": identifier,
        "type": INVENTORY_TYPE,
        "digestAlgorithm": "sha256",
        "head": vname(versions[-1].number),
        "manifest": {digest: sorted(paths) for digest, paths in sorted(manifest.items())},
        "versions": {
            vname(v.number): {
                "created": v.created,
                "state": {v.digest: [v.name]},
                "message": v.message,
                "user": {"name": v.actor},
            }
            for v in versions
        },
    }


def serialise(inventory: dict[str, Any]) -> bytes:
    """The exact bytes written: validated first, then deterministic JSON."""
    validate_json(inventory, SCHEMA_PATH, source="ocfl-inventory")
    return (json.dumps(inventory, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def sidecar_text(inventory_bytes: bytes) -> bytes:
    """OCFL 3.5.6: the digest, whitespace, and the inventory's file name."""
    return f"{hashlib.sha256(inventory_bytes).hexdigest()}  {INVENTORY}\n".encode("ascii")


def sidecar_digest(sidecar_bytes: bytes) -> str:
    parts = sidecar_bytes.decode("ascii", errors="replace").split()
    return parts[0] if len(parts) == 2 and parts[1] == INVENTORY else ""


def parse(inventory_bytes: bytes, sidecar_bytes: bytes) -> dict[str, Any] | None:
    """The inventory, if it matches its sidecar and validates; ``None`` otherwise."""
    if hashlib.sha256(inventory_bytes).hexdigest() != sidecar_digest(sidecar_bytes):
        return None
    try:
        data = json.loads(inventory_bytes)
        validate_json(data, SCHEMA_PATH, source="ocfl-inventory")
    except ValueError, JsonFileError:
        return None
    if not isinstance(data, dict) or vname(len(data["versions"])) != data["head"]:
        return None
    if set(data["versions"]) != {vname(n) for n in range(1, len(data["versions"]) + 1)}:
        return None
    return data


def records(inventory: dict[str, Any]) -> list[VersionRecord]:
    """Every version in the inventory, oldest first."""
    found = []
    for key, body in inventory["versions"].items():
        ((digest, names),) = body["state"].items()
        found.append(
            VersionRecord(vnumber(key), digest, names[0], body["created"], body["user"]["name"], body["message"])
        )
    return sorted(found, key=lambda r: r.number)


__all__ = [
    "INVENTORY",
    "OBJECT_MARKER",
    "OBJECT_MARKER_TEXT",
    "SCHEMA_PATH",
    "SIDECAR",
    "STORAGE_ROOT_MARKER",
    "STORAGE_ROOT_MARKER_TEXT",
    "VersionRecord",
    "build",
    "parse",
    "records",
    "serialise",
    "sidecar_digest",
    "sidecar_text",
    "vname",
    "vnumber",
]
