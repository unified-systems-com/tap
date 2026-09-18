"""Batch-local refs on the GRIFT envelope — the gate, shape A (Issue# 571 - tap; this slice
Issue# 593 - tap).

A collector that has not yet learned a node's id names it with a batch-local ``ref`` instead
of an ``entity_id`` — exactly one of the two, which the document schema enforces — and an edge
endpoint may name a node of the same batch by ``from_ref`` / ``to_ref``. Refs are resolved to
ids in ONE pass, before preflight reads anything, so every later stage — preflight, execution,
provenance, events — sees only ids. A ref never reaches a record; the ``ref → id`` map is
returned on the import result, which is where a collector learns what it was given.

Resolution is the seam. Here the resolver is :func:`mint_only`: every ref mints a fresh
UUIDv7 and nothing is looked up. Slice 2 (Issue# 594 - tap) replaces it with
``resolve_identity`` — ``find_existing`` under a lock, mint on none — without touching the
envelope contract in this module.

The input document is never mutated: a document that carries refs is deep-copied first, so
importing the same dict twice presents refs twice (the second import is not silently
id-addressed by the first's minting).
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

IdentityResolver = Callable[[dict[str, Any]], str]
"""Given a node or edge envelope that carries a ``ref``, return the id it resolves to."""

_ENDPOINTS = (("from_entity_id", "from_ref"), ("to_entity_id", "to_ref"))


def mint_only(envelope: dict[str, Any]) -> str:
    """The slice-1 resolver: a fresh UUIDv7 for every ref, no lookup (the stub slice 2 replaces)."""
    return str(uuid.uuid7())


@dataclass(frozen=True)
class RefIssue:
    """A ref problem found before preflight; the importer turns it into a ``GriftIssue``."""

    code: str
    message: str
    path: str
    batch_entity_id: str | None


@dataclass
class RefResolution:
    """The document with every ref rewritten to an id, plus what each ref became."""

    document: dict[str, Any]
    resolved: dict[str, dict[str, str]] = field(default_factory=dict)
    """``batch_entity_id → {ref: entity_id}`` for every batch that carried a ref."""
    issues: list[RefIssue] = field(default_factory=list)


def uses_refs(document: dict[str, Any]) -> bool:
    """True when any envelope or edge endpoint in the document names a ref."""
    for batch in _batches(document):
        if "ref" in _envelope(batch.get("batch_entity")):
            return True
        for node in _items(batch, "nodes"):
            if "ref" in _envelope(node.get("entity")):
                return True
        for edge in _items(batch, "edges"):
            if "ref" in _envelope(edge.get("entity")):
                return True
            payload = edge.get("edge")
            if isinstance(payload, dict) and any(ref_key in payload for _, ref_key in _ENDPOINTS):
                return True
    return False


def resolve_refs(document: dict[str, Any], *, resolver: IdentityResolver = mint_only) -> RefResolution:
    """Rewrite every ref in ``document`` to an id, on a copy; report what could not be resolved.

    TAP-IMPLEMENTS: req-grid-import-grift-identity@bf2b55d2fd9f/ffd1838762d5 (derivation) — the one
        pass that turns a batch-local ref into the id every later stage and record sees
        (acceptance -3); the id itself is assigned by the resolver, never derived from the ref.

    Runs after JSON-schema validation (so shapes are trusted and the ``entity_id`` XOR ``ref``
    rule has already held) and before any other preflight read. Refs are batch-local: a node
    ref is unique within its batch across nodes and edges, and an endpoint ref names a node of
    the same batch. A batch entity is never a ref — it is the import identity.
    """
    if not uses_refs(document):
        return RefResolution(document=document)

    resolved_document = copy.deepcopy(document)
    resolution = RefResolution(document=resolved_document)
    for batch_idx, batch in enumerate(_batches(resolved_document)):
        _resolve_batch(batch, f"$.batches[{batch_idx}]", resolver, resolution)
    return resolution


def _resolve_batch(
    batch: dict[str, Any], batch_path: str, resolver: IdentityResolver, resolution: RefResolution
) -> None:
    batch_envelope = _envelope(batch.get("batch_entity"))
    batch_entity_id = batch_envelope.get("entity_id")
    if "ref" in batch_envelope:
        resolution.issues.append(
            RefIssue(
                "ref_not_allowed",
                f"A batch is addressed by entity_id, never by ref, at {batch_path}.batch_entity.ref",
                f"{batch_path}.batch_entity.ref",
                batch_entity_id,
            )
        )
        return

    refs: dict[str, str] = {}
    node_refs: set[str] = set()
    for idx, node in enumerate(_items(batch, "nodes")):
        path = f"{batch_path}.nodes[{idx}].entity"
        ref = _take_ref(_envelope(node.get("entity")), path, refs, batch_entity_id, resolver, resolution)
        if ref is not None:
            node_refs.add(ref)
    for idx, edge in enumerate(_items(batch, "edges")):
        path = f"{batch_path}.edges[{idx}]"
        _take_ref(_envelope(edge.get("entity")), f"{path}.entity", refs, batch_entity_id, resolver, resolution)
        payload = edge.get("edge")
        if not isinstance(payload, dict):
            continue
        for id_key, ref_key in _ENDPOINTS:
            if ref_key not in payload:
                continue
            target = payload.pop(ref_key)
            if target in node_refs:
                payload[id_key] = refs[target]
                continue
            resolution.issues.append(
                RefIssue(
                    "unknown_ref",
                    f"Edge endpoint {ref_key}={target!r} names no node ref of this batch at {path}.edge.{ref_key}",
                    f"{path}.edge.{ref_key}",
                    batch_entity_id,
                )
            )
    if refs and batch_entity_id is not None:
        resolution.resolved[batch_entity_id] = refs


def _take_ref(
    envelope: dict[str, Any],
    path: str,
    refs: dict[str, str],
    batch_entity_id: str | None,
    resolver: IdentityResolver,
    resolution: RefResolution,
) -> str | None:
    """Replace ``envelope["ref"]`` with a resolved ``entity_id``; return the ref, or None if there was none."""
    if "ref" not in envelope:
        return None
    ref = envelope.pop("ref")
    if not isinstance(ref, str) or not ref.strip():
        resolution.issues.append(
            RefIssue("invalid_ref", f"ref must be a non-empty string at {path}.ref", f"{path}.ref", batch_entity_id)
        )
        return None
    if ref in refs:
        resolution.issues.append(
            RefIssue(
                "duplicate_ref", f"ref {ref!r} is used twice in one batch at {path}.ref", f"{path}.ref", batch_entity_id
            )
        )
        return None
    envelope["entity_id"] = refs[ref] = resolver(envelope)
    return ref


def _batches(document: dict[str, Any]) -> list[dict[str, Any]]:
    batches = document.get("batches") if isinstance(document, dict) else None
    return [b for b in (batches or []) if isinstance(b, dict)]


def _items(batch: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [i for i in (batch.get(key) or []) if isinstance(i, dict)]


def _envelope(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
