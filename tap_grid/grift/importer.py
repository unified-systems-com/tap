"""GRIFT v0 importer — Grid Interchange Format.

TAP-IMPLEMENTS: req-grid-import-grift-scope@24f7ce8e15a8/4f42fb85c091 (derivation) — this
    module IS the GRIFT importer the requirement scopes.

Parses, validates, and imports a GRIFT document into the local TAP grid.

Public API:
    grift_import(document, *, dangling_edge_mode, actor) -> GriftImportResult
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import jsonschema
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from tap.jsonfiles import load_schema
from tap_grid.batch import close_batch, create_batch
from tap_grid.caller_context import CallerContext
from tap_grid.exceptions import ServiceValidationError
from tap_grid.grift.refs import resolve_refs, substitute_ids
from tap_grid.models import BaseModel, Entity
from tap_grid.natural_key import AmbiguousIdentity, Keyless, constituting_properties, identity_lock_key
from tap_grid.service_types import WriteOperation
from tap_grid.services import (
    find_by_natural_key,
    find_edge_by_identity,
    resolve_edge_identity,
    resolve_identity,
    write_batch,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass


GRIFT_VERSION = "0"
IMPORT_MODE = "upsert"
_GRIFT_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "grift-document.schema.json"

# ---------------------------------------------------------------------------
# Result types (mirror the JSON schema in spec-grid-import-grift.md)
# ---------------------------------------------------------------------------


@dataclass
class GriftIssue:
    """One validation or execution issue from a GRIFT import run."""

    code: str
    message: str
    phase: Literal["parse", "schema", "validation", "preflight", "execution"]
    path: str
    entity_id: str | None
    batch_entity_id: str | None
    entity_type: str | None
    operation: str | None
    from_entity_id: str | None = None
    to_entity_id: str | None = None
    edge_entity_id: str | None = None
    # Optimistic-concurrency diagnostic fields populated by
    # req-grid-import-grift-occ for `entity_version_conflict` issues so
    # clients can implement retry-or-surface logic without parsing the
    # message. Both are `None` for non-OCC issues. `actual_entity_version`
    # is also `None` when the target entity was missing entirely.
    entity_expected_version: int | None = None
    actual_entity_version: int | None = None


@dataclass
class GriftCounts:
    """Aggregate counts for a completed GRIFT import."""

    batches_imported: int = 0
    batches_skipped: int = 0
    batches_force_reimported: int = 0
    nodes_imported: int = 0
    edges_imported: int = 0
    edges_skipped: int = 0
    entities_swept: int = 0
    entities_purged: int = 0
    sweep_skipped: int = 0
    entities_upserted: int = 0
    # Imperative removal sections (req-grift-import-deletes).
    edges_deleted: int = 0
    nodes_deleted: int = 0
    edges_purged: int = 0
    nodes_purged: int = 0
    removals_skipped: int = 0
    # Retired entities carried by a `retirement` block (req-grid-import-grift-retired).
    edges_retired: int = 0
    nodes_retired: int = 0
    retirements_skipped: int = 0
    # Edges authority claims would remove; a dry-run removes none (req-grid-reconcile-edge-authority-6).
    edges_proposed: int = 0
    errors: int = 0
    warnings: int = 0


@dataclass
class GriftSweptEntity:
    """Per-entity record for an entity tombstoned or purged by a batch-scoped sweep."""

    entity_id: str
    entity_type: str
    action: Literal["tombstone", "purge"]
    reason: str  # always "orphaned" for now; reserved for future taxonomy


@dataclass
class GriftSweepSkipped:
    """Per-entity record for a sweep candidate that failed a guardrail."""

    entity_id: str
    entity_type: str
    reason: Literal["sweep_skipped_external_write", "sweep_skipped_referenced"]


@dataclass
class GriftUpsertedEntity:
    """Per-entity record for a node or edge whose entity_id already existed in
    the grid and was replaced in-place by this batch's content.

    Emitted to make GRIFT's last-write-wins-per-entity contract visible during
    development. See req-grid-import-grift-ordering.
    """

    entity_id: str
    entity_type: str
    name: str | None
    kind: Literal["node", "edge"]


@dataclass
class GriftImportedBatch:
    """Per-batch summary for a successfully imported batch."""

    batch_entity_id: str
    path: str
    nodes_imported: int
    edges_imported: int
    edges_skipped: int
    errors_count: int
    warnings_count: int
    # Force-reimport specific fields (default empty for normal imports).
    force_reimported: bool = False
    swept_entities: list[GriftSweptEntity] = None  # type: ignore[assignment]
    sweep_skipped: list[GriftSweepSkipped] = None  # type: ignore[assignment]
    sweep_strict_aborted: bool = False
    # Per-entity upsert visibility: nodes/edges whose entity_id already existed
    # in the grid and were replaced in-place by this batch. See
    # req-grid-import-grift-ordering.
    upserted_entities: list[GriftUpsertedEntity] = None  # type: ignore[assignment]
    # Imperative removal sections (req-grift-import-deletes).
    edges_deleted: int = 0
    nodes_deleted: int = 0
    edges_purged: int = 0
    nodes_purged: int = 0
    removals_skipped: int = 0
    # Retired entities carried by a `retirement` block (req-grid-import-grift-retired).
    edges_retired: int = 0
    nodes_retired: int = 0
    retirements_skipped: int = 0
    # Batch-local refs and the ids they resolved to (the gate, shape A —
    # Issue# 593 - tap): the one place a collector learns what its refs became.
    resolved_refs: dict[str, str] = None  # type: ignore[assignment]
    # Edges this batch declined to write because an endpoint did not resolve, each with the id of
    # its `skip` BatchEvent (req-grid-import-grift-edge-endpoints-8). Empty for a batch that
    # failed: its skip events rolled back with it, and its issues name the endpoints instead.
    skips: list[dict[str, Any]] = None  # type: ignore[assignment]
    # Each authority claim's outcome, with the id of its batch-level `authority_proposed` event
    # (req-grid-reconcile-edge-authority-7), and how many edges the claims would remove. Empty for a
    # batch that failed: its events rolled back with it.
    authority: list[dict[str, Any]] = None  # type: ignore[assignment]
    edges_proposed: int = 0

    def __post_init__(self):
        if self.resolved_refs is None:
            self.resolved_refs = {}
        if self.skips is None:
            self.skips = []
        if self.authority is None:
            self.authority = []
        if self.swept_entities is None:
            self.swept_entities = []
        if self.sweep_skipped is None:
            self.sweep_skipped = []
        if self.upserted_entities is None:
            self.upserted_entities = []


@dataclass
class GriftSkippedBatch:
    """Per-batch record for a batch that was skipped (e.g. already imported)."""

    batch_entity_id: str
    path: str
    reason: str


@dataclass
class GriftImportResult:
    """Full result of a grift_import() call.

    TAP-IMPLEMENTS: req-grid-import-grift-results@aebcf375e05f/c082f212b815 (derivation) — the
        structured result the importer returns.
    """

    success: bool
    grift_version: str
    import_mode: str
    dangling_edge_mode: str
    reference_time: str
    counts: GriftCounts
    imported_batches: list[GriftImportedBatch]
    skipped_batches: list[GriftSkippedBatch]
    errors: list[GriftIssue]
    warnings: list[GriftIssue]


# ---------------------------------------------------------------------------
# Internal preflight state
# ---------------------------------------------------------------------------


@dataclass
class _PreflightResult:
    ok: bool
    batches_to_import: list[tuple[int, dict[str, Any]]]
    batches_to_skip: list[GriftSkippedBatch]
    dangling_edge_ids: set[str]
    issues: list[GriftIssue]
    # Side-channel: removal sections parsed during preflight, keyed by
    # batch_idx. Avoids mutating the input document (which would fail strict
    # JSON-schema validation on a repeat import of the same dict object).
    parsed_removals_by_idx: dict[int, Any] = None  # type: ignore[assignment]
    # Side-channel: what each batch's refs resolved to, keyed by batch_entity_id
    # (the gate, shape A — Issue# 593 - tap). Surfaced per imported batch.
    resolved_refs: dict[str, dict[str, str]] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.parsed_removals_by_idx is None:
            self.parsed_removals_by_idx = {}
        if self.resolved_refs is None:
            self.resolved_refs = {}


# ---------------------------------------------------------------------------
# Schema sets
# ---------------------------------------------------------------------------

_DOC_REQUIRED = frozenset(["metadata", "_reserved", "batches"])
_DOC_ALLOWED = frozenset(["metadata", "_reserved", "batches"])
_METADATA_ALLOWED = frozenset(["grift_version"])
_BATCH_REQUIRED = frozenset(["batch_entity", "batch_node", "nodes", "edges"])
# Removal sections (`deletes`, `purges`) are optional per
# req-grift-import-deletes; presence is detected at parse time and validated
# in removal preflight. They are NOT in _BATCH_REQUIRED.
_BATCH_ALLOWED = frozenset(
    ["batch_entity", "batch_node", "nodes", "edges", "deletes", "purges", "contents", "edge_cases"]
)
_NODE_REQUIRED = frozenset(["entity", "node"])
_NODE_ALLOWED = frozenset(["entity", "node", "retirement"])
_EDGE_REQUIRED = frozenset(["entity", "edge"])
_EDGE_ALLOWED = frozenset(["entity", "edge", "retirement"])
_ENVELOPE_REQUIRED = frozenset(["entity_id", "entity_type", "dimensions"])
# `entity_expected_version` is the optional OCC declaration on upsert
# envelopes (req-grift-concurrency-version). The importer parses and
# threads it through to the service-layer verb's pipeline-level guard.
_ENVELOPE_ALLOWED = frozenset(
    [
        "entity_id",
        "entity_type",
        "name",
        "dimensions",
        "created_at",
        "updated_at",
        "deleted_at",
        "entity_expected_version",
    ]
)
_EDGE_PAYLOAD_REQUIRED = frozenset(["edge_type", "properties"])
_EDGE_PAYLOAD_ALLOWED = frozenset(["from_entity_id", "to_entity_id", "from_key", "to_key", "edge_type", "properties"])
#: Each endpoint is named by exactly one of these after the ref pass: an id, or a type and natural
#: key resolved inside the batch transaction (req-grid-import-grift-edge-endpoints-1).
_EDGE_ENDPOINT_FORMS: tuple[tuple[str, str, str], ...] = (
    ("from", "from_entity_id", "from_key"),
    ("to", "to_entity_id", "to_key"),
)

# Removal-section schema (req-grift-import-deletes). `entity_expected_version`
# is the optional OCC declaration on a removal target (same contract as on
# upsert envelopes).
_REMOVAL_TARGET_REQUIRED = frozenset(["entity_id", "entity_type", "reason"])
_REMOVAL_TARGET_ALLOWED = frozenset(["entity_id", "entity_type", "reason", "entity_expected_version"])
_DELETES_REQUIRED = frozenset(["on_missing", "on_tombstoned", "edges", "nodes"])
_DELETES_ALLOWED = frozenset(["on_missing", "on_tombstoned", "edges", "nodes"])
_PURGES_REQUIRED = frozenset(["on_missing", "edges", "nodes"])
_PURGES_ALLOWED = frozenset(["on_missing", "edges", "nodes"])
_REMOVAL_POLICY_VALUES = frozenset(["error", "warn", "ignore"])
# The retirement block a retired node or edge carries (req-grift-retirement).
_RETIREMENT_KEYS = frozenset(["retired_at", "batch_id", "reason", "metadata"])
# Contents aspects this importer accepts when declared included (req-grift-contents-3).
_ACCEPTED_CONTENTS = frozenset(["tombstones"])
_TOMBSTONES_KEYS = frozenset(["included", "nodes", "edges"])

# Codes that are always treated as hard errors (not warnings).
_ERROR_CODES = frozenset(
    [
        "invalid_json",
        # The parse boundary (Issue# 630 - tap, ruled 2026-09-18): a document the decoder
        # could read but GRIFT refuses — a repeated object key, a number outside the JSON
        # grammar — and a document version this importer does not speak.
        "duplicate_json_key",
        "non_finite_number",
        "unsupported_grift_version",
        "schema_validation_failed",
        "duplicate_entity_id",
        "duplicate_batch_id",
        "unknown_entity_type",
        "payload_validation_failed",
        "timestamp_in_future",
        "timestamp_order_invalid",
        "entity_type_mismatch",
        "envelope_payload_name_mismatch",
        "dangling_edge",  # hard error in strict mode; warning surfaced separately in permissive
        "execution_failed",
        "force_reimport_refused_production",
        "sweep_purge_refused_production",
        "sweep_strict_aborted",
        "force_reimport_batch_not_found",
        "purge_requires_force_reimport",
        # Imperative removal section codes (req-grift-import-deletes,
        # req-grid-import-grift-removal-preflight).
        "duplicate_removal_target",
        "entity_id_in_upsert_and_removal",
        "removal_identity_unkeyed",
        "removal_target_missing",
        "removal_target_tombstoned",
        "removal_entity_type_mismatch",
        "grift_purge_refused_production",
        "removal_execution_failed",
        # Optimistic concurrency (req-grift-concurrency-version,
        # req-grid-import-grift-occ).
        "entity_version_conflict",
        # Batch-local refs (the gate, shape A — Issue# 593 - tap). The entity_id XOR ref
        # rule itself is the document schema's (`schema_validation_failed`).
        "ref_not_allowed",
        "invalid_ref",
        "duplicate_ref",
        "unknown_ref",
        # Identity resolution of ref nodes inside the batch transaction (gate slice 2,
        # Issue# 594 - tap): the declared search found more than one live row, or the
        # type has declared no search at all.
        "identity_ambiguous",
        "identity_undeclared",
        # Edge identity (req-grid-edge-identity, Issue# 913 - tap): an edge whose declared key
        # has a hole, and two edges of one batch (or a keyless edge and a live one) that are
        # the same relationship. An undeclared type is a logged warning in warn mode and
        # `identity_undeclared` after the flip (Issue# 928 - tap).
        "incomplete_edge_key",
        "duplicate_edge",
        # Endpoints by natural key (req-grid-import-grift-edge-endpoints): refused at preflight.
        "incomplete_endpoint_key",
        "endpoint_type_unkeyed",
        "endpoint_key_mismatch",
        # The contents declaration (req-grift-contents): a declaration the batch does not
        # match, or an aspect this importer does not accept.
        "contents_mismatch",
        "unsupported_contents",
        # Authority claims (req-grid-reconcile-edge-authority): a claim refused at preflight, and two
        # claims over one scope in a batch.
        "authority_dimensions_reserved",
        "authority_internal_edge_type",
        "duplicate_authority_claim",
    ]
)


# ---------------------------------------------------------------------------
# Issue factory
# ---------------------------------------------------------------------------


def _issue(
    code: str,
    message: str,
    phase: str,
    path: str,
    *,
    entity_id: str | None = None,
    batch_entity_id: str | None = None,
    entity_type: str | None = None,
    operation: str | None = None,
    from_entity_id: str | None = None,
    to_entity_id: str | None = None,
    edge_entity_id: str | None = None,
    entity_expected_version: int | None = None,
    actual_entity_version: int | None = None,
) -> GriftIssue:
    return GriftIssue(
        code=code,
        message=message,
        phase=phase,  # type: ignore[arg-type]
        path=path,
        entity_id=entity_id,
        batch_entity_id=batch_entity_id,
        entity_type=entity_type,
        operation=operation,
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
        edge_entity_id=edge_entity_id,
        entity_expected_version=entity_expected_version,
        actual_entity_version=actual_entity_version,
    )


# ---------------------------------------------------------------------------
# The parse boundary (req-grid-import-grift-preflight-3)
# ---------------------------------------------------------------------------


class _JsonRefused(ValueError):
    """A document the decoder could read but GRIFT refuses; carries the issue code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _refuse_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``object_pairs_hook``: a repeated key would silently drop the earlier value (RFC 8259 §4)."""
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise _JsonRefused(
                "duplicate_json_key",
                f"Duplicate object key {key!r}: the later value would silently replace the earlier one",
            )
        obj[key] = value
    return obj


def _refuse_non_finite(token: str) -> float:
    """``parse_float`` and ``parse_constant``: ``NaN``, ``Infinity``, ``-Infinity`` and a literal that
    overflows to infinity are outside the JSON grammar (RFC 8259 §6) and PostgreSQL cannot store them."""
    value = float(token)
    if not math.isfinite(value):
        raise _JsonRefused(
            "non_finite_number", f"Number {token!r} is not finite: outside the JSON grammar and unstorable"
        )
    return value


def _parse_document(raw: str | bytes) -> tuple[Any, GriftIssue | None]:
    """Decode the ``str | bytes`` arm. The one decoder configuration; every failure is a
    ``parse``-phase issue at ``$`` and never a raise (Issue# 630 - tap).

    Bytes decode as ``json.loads`` auto-detects them from the first bytes — UTF-8, UTF-16 or
    UTF-32, a BOM tolerated — while text carrying a BOM is refused with the syntax errors. The
    decoder's own failures — a syntax error, undecodable bytes (``UnicodeDecodeError``), an
    integer literal past the interpreter's digit limit (``ValueError``), nesting past its
    recursion limit (``RecursionError``) — become ``invalid_json``; the two refusals GRIFT adds
    on top carry their own codes. A parsed dict never passes through here.
    """
    try:
        document = json.loads(
            raw,
            object_pairs_hook=_refuse_duplicate_keys,
            parse_float=_refuse_non_finite,
            parse_constant=_refuse_non_finite,
        )
    except _JsonRefused as exc:
        return None, _issue(exc.code, str(exc), "parse", "$")
    except (ValueError, RecursionError) as exc:
        return None, _issue("invalid_json", f"Invalid JSON ({type(exc).__name__}): {exc}", "parse", "$")
    return document, None


# ---------------------------------------------------------------------------
# Low-level validators
# ---------------------------------------------------------------------------


def _check_uuid(value: Any, path: str, issues: list[GriftIssue], *, batch_entity_id: str | None = None) -> str | None:
    """Validate value is a UUID string. Returns its canonical spelling if valid, else None.

    The one canonicaliser (Issue# 630 - tap): ``uuid.UUID`` accepts upper-case, braced and
    ``urn:uuid:`` forms, so the returned string is the lowercase hyphenated form and every
    later comparison — file-wide duplicates, upsert-versus-removal, endpoint resolution,
    skip-if-exists — sees one spelling per id. Callers write it back onto the preflight copy.
    """
    if not isinstance(value, str):
        issues.append(
            _issue(
                "schema_validation_failed",
                f"Expected UUID string at {path}, got {type(value).__name__}",
                "schema",
                path,
                batch_entity_id=batch_entity_id,
            )
        )
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        issues.append(
            _issue(
                "schema_validation_failed",
                f"Invalid UUID at {path}: {value!r}",
                "schema",
                path,
                batch_entity_id=batch_entity_id,
            )
        )
        return None


def _check_datetime(
    value: Any, path: str, issues: list[GriftIssue], *, batch_entity_id: str | None = None
) -> datetime | None:
    """Validate value is an RFC 3339 datetime string. Returns parsed datetime or None."""
    if value is None:
        return None
    if not isinstance(value, str):
        issues.append(
            _issue(
                "schema_validation_failed",
                f"Expected datetime string at {path}, got {type(value).__name__}",
                "schema",
                path,
                batch_entity_id=batch_entity_id,
            )
        )
        return None
    dt = parse_datetime(value)
    if dt is None:
        issues.append(
            _issue(
                "schema_validation_failed",
                f"Invalid datetime at {path}: {value!r}",
                "schema",
                path,
                batch_entity_id=batch_entity_id,
            )
        )
    return dt


def _make_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return timezone.make_aware(dt)
    return dt


# ---------------------------------------------------------------------------
# Entity envelope validator
# ---------------------------------------------------------------------------


def _validate_envelope(
    envelope: Any,
    path: str,
    issues: list[GriftIssue],
    *,
    reference_time: datetime,
    batch_entity_id: str | None = None,
) -> str | None:
    """Validate a GriftEntityEnvelope. Returns the canonical entity_id string if valid, and
    writes that spelling back onto the envelope (a preflight copy, never the caller's dict)."""
    if not isinstance(envelope, dict):
        issues.append(
            _issue(
                "schema_validation_failed",
                f"Entity envelope at {path} must be an object",
                "schema",
                path,
                batch_entity_id=batch_entity_id,
            )
        )
        return None

    for key in envelope:
        if key not in _ENVELOPE_ALLOWED:
            issues.append(
                _issue(
                    "schema_validation_failed",
                    f"Unknown key '{key}' in entity envelope at {path}.{key}",
                    "schema",
                    f"{path}.{key}",
                    batch_entity_id=batch_entity_id,
                )
            )

    for req in _ENVELOPE_REQUIRED:
        if req not in envelope:
            issues.append(
                _issue(
                    "schema_validation_failed",
                    f"Missing required field '{req}' in entity envelope at {path}",
                    "schema",
                    f"{path}.{req}",
                    batch_entity_id=batch_entity_id,
                )
            )

    entity_id = _check_uuid(envelope.get("entity_id", ""), f"{path}.entity_id", issues, batch_entity_id=batch_entity_id)
    if entity_id is not None:
        # One spelling from here on: the preflight copy carries the canonical id so every
        # later reader (endpoint resolution, execution, the result) sees what preflight compared.
        envelope["entity_id"] = entity_id

    if "entity_type" in envelope:
        if not isinstance(envelope["entity_type"], str) or not envelope["entity_type"]:
            issues.append(
                _issue(
                    "schema_validation_failed",
                    f"entity_type must be a non-empty string at {path}.entity_type",
                    "schema",
                    f"{path}.entity_type",
                    batch_entity_id=batch_entity_id,
                )
            )

    if "dimensions" in envelope:
        dims = envelope["dimensions"]
        if not isinstance(dims, dict):
            issues.append(
                _issue(
                    "schema_validation_failed",
                    f"dimensions must be an object at {path}.dimensions",
                    "schema",
                    f"{path}.dimensions",
                    batch_entity_id=batch_entity_id,
                )
            )
        else:
            for k, v in dims.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    issues.append(
                        _issue(
                            "schema_validation_failed",
                            f"dimensions must be string-to-string at {path}.dimensions",
                            "schema",
                            f"{path}.dimensions",
                            batch_entity_id=batch_entity_id,
                        )
                    )
                    break

    if "name" in envelope and envelope["name"] is not None:
        if not isinstance(envelope["name"], str) or not envelope["name"]:
            issues.append(
                _issue(
                    "schema_validation_failed",
                    f"name must be a non-empty string at {path}.name",
                    "schema",
                    f"{path}.name",
                    batch_entity_id=batch_entity_id,
                )
            )

    # Timestamp validation and ordering.
    created_at = _check_datetime(
        envelope.get("created_at"), f"{path}.created_at", issues, batch_entity_id=batch_entity_id
    )
    updated_at = _check_datetime(
        envelope.get("updated_at"), f"{path}.updated_at", issues, batch_entity_id=batch_entity_id
    )
    deleted_at_raw = envelope.get("deleted_at")
    deleted_at = (
        _check_datetime(deleted_at_raw, f"{path}.deleted_at", issues, batch_entity_id=batch_entity_id)
        if deleted_at_raw is not None
        else None
    )

    if deleted_at_raw is not None and "updated_at" not in envelope:
        issues.append(
            _issue(
                "timestamp_order_invalid",
                f"deleted_at requires updated_at to also be present at {path}",
                "validation",
                f"{path}.deleted_at",
                entity_id=entity_id,
                batch_entity_id=batch_entity_id,
            )
        )

    if created_at and updated_at and _make_aware(updated_at) < _make_aware(created_at):
        issues.append(
            _issue(
                "timestamp_order_invalid",
                f"updated_at must be >= created_at at {path}",
                "validation",
                f"{path}.updated_at",
                entity_id=entity_id,
                batch_entity_id=batch_entity_id,
            )
        )

    if updated_at and deleted_at and _make_aware(deleted_at) < _make_aware(updated_at):
        issues.append(
            _issue(
                "timestamp_order_invalid",
                f"deleted_at must be >= updated_at at {path}",
                "validation",
                f"{path}.deleted_at",
                entity_id=entity_id,
                batch_entity_id=batch_entity_id,
            )
        )

    for ts_name, ts_val in [("created_at", created_at), ("updated_at", updated_at), ("deleted_at", deleted_at)]:
        if ts_val is not None and _make_aware(ts_val) > reference_time:
            issues.append(
                _issue(
                    "timestamp_in_future",
                    f"{ts_name} is in the future at {path}.{ts_name}",
                    "validation",
                    f"{path}.{ts_name}",
                    entity_id=entity_id,
                    batch_entity_id=batch_entity_id,
                )
            )

    return entity_id


# ---------------------------------------------------------------------------
# Retirement block and contents declaration (req-grift-retirement, req-grift-contents)
# ---------------------------------------------------------------------------


def _validate_retirement_block(
    retirement: Any,
    path: str,
    issues: list[GriftIssue],
    *,
    reference_time: datetime,
    batch_entity_id: str | None,
    entity_id: str | None,
) -> None:
    """Check one ``retirement`` block (req-grift-retirement-1).

    The document schema holds the shape; this adds what the schema cannot: a
    parseable ``retired_at`` no later than the reference time, and a ``batch_id``
    in its one canonical spelling (req-grid-import-grift-identity-4), written back.
    """
    if not isinstance(retirement, dict):
        issues.append(
            _issue(
                "schema_validation_failed",
                f"retirement must be an object at {path}",
                "schema",
                path,
                batch_entity_id=batch_entity_id,
                entity_id=entity_id,
            )
        )
        return
    for key in sorted(set(retirement) ^ _RETIREMENT_KEYS):
        state = "Unknown" if key in retirement else "Missing required"
        issues.append(
            _issue(
                "schema_validation_failed",
                f"{state} key '{key}' in retirement at {path}",
                "schema",
                f"{path}.{key}",
                batch_entity_id=batch_entity_id,
                entity_id=entity_id,
            )
        )
    retired_at = _check_datetime(
        retirement.get("retired_at"), f"{path}.retired_at", issues, batch_entity_id=batch_entity_id
    )
    if retired_at is not None and _make_aware(retired_at) > reference_time:
        issues.append(
            _issue(
                "timestamp_in_future",
                f"retired_at is in the future at {path}.retired_at",
                "validation",
                f"{path}.retired_at",
                entity_id=entity_id,
                batch_entity_id=batch_entity_id,
            )
        )
    if retirement.get("batch_id") is not None:
        canonical = _check_uuid(retirement["batch_id"], f"{path}.batch_id", issues, batch_entity_id=batch_entity_id)
        if canonical is not None:
            retirement["batch_id"] = canonical
    reason = retirement.get("reason")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        issues.append(
            _issue(
                "schema_validation_failed",
                f"retirement reason must be a non-empty string or null at {path}.reason",
                "schema",
                f"{path}.reason",
                batch_entity_id=batch_entity_id,
                entity_id=entity_id,
            )
        )
    if "metadata" in retirement and not isinstance(retirement["metadata"], dict):
        issues.append(
            _issue(
                "schema_validation_failed",
                f"retirement metadata must be an object at {path}.metadata",
                "schema",
                f"{path}.metadata",
                batch_entity_id=batch_entity_id,
                entity_id=entity_id,
            )
        )


def _validate_contents(
    contents: Any,
    *,
    retired_nodes: int,
    retired_edges: int,
    path: str,
    issues: list[GriftIssue],
    batch_entity_id: str | None,
) -> None:
    """Verify a batch's ``contents`` declaration and decide on it (req-grift-contents).

    Declare-vs-decide: the declaration is checked against the retirement blocks the
    batch actually carries, never trusted (-2), and an aspect declared included that
    this importer does not accept is refused rather than silently dropped (-3).
    """
    if not isinstance(contents, dict):
        issues.append(
            _issue(
                "schema_validation_failed",
                f"contents must be an object at {path}",
                "schema",
                path,
                batch_entity_id=batch_entity_id,
            )
        )
        return
    for aspect, declared in sorted(contents.items()):
        aspect_path = f"{path}.{aspect}"
        if not isinstance(declared, dict) or not isinstance(declared.get("included"), bool):
            issues.append(
                _issue(
                    "schema_validation_failed",
                    f"contents aspect '{aspect}' must be an object with a boolean 'included' at {aspect_path}",
                    "schema",
                    aspect_path,
                    batch_entity_id=batch_entity_id,
                )
            )
            continue
        if declared["included"] and aspect not in _ACCEPTED_CONTENTS:
            issues.append(
                _issue(
                    "unsupported_contents",
                    f"The batch declares it includes '{aspect}', which this importer does not accept "
                    f"(it accepts {sorted(_ACCEPTED_CONTENTS)}); nothing was imported.",
                    "preflight",
                    aspect_path,
                    batch_entity_id=batch_entity_id,
                )
            )

    tombstones = contents.get("tombstones")
    if not isinstance(tombstones, dict):
        issues.append(
            _issue(
                "schema_validation_failed",
                f"contents must declare 'tombstones' at {path}.tombstones",
                "schema",
                f"{path}.tombstones",
                batch_entity_id=batch_entity_id,
            )
        )
        return
    if set(tombstones) != _TOMBSTONES_KEYS or not all(
        isinstance(tombstones[k], int) and not isinstance(tombstones[k], bool) and tombstones[k] >= 0
        for k in ("nodes", "edges")
    ):
        issues.append(
            _issue(
                "schema_validation_failed",
                f"contents.tombstones must hold exactly included, nodes and edges (non-negative "
                f"integers) at {path}.tombstones",
                "schema",
                f"{path}.tombstones",
                batch_entity_id=batch_entity_id,
            )
        )
        return
    # The counts must be the batch's own, and "not included" must mean none are carried.
    miscounted = (tombstones["nodes"], tombstones["edges"]) != (retired_nodes, retired_edges)
    undeclared = not tombstones["included"] and bool(retired_nodes or retired_edges)
    if miscounted or undeclared:
        issues.append(
            _issue(
                "contents_mismatch",
                f"The batch declares tombstones {tombstones!r} but carries {retired_nodes} retired "
                f"node(s) and {retired_edges} retired edge(s).",
                "preflight",
                f"{path}.tombstones",
                batch_entity_id=batch_entity_id,
            )
        )


# ---------------------------------------------------------------------------
# Node payload validator
# ---------------------------------------------------------------------------


def _validate_node_payload(
    payload: Any,
    entity_type: str,
    path: str,
    issues: list[GriftIssue],
    *,
    batch_entity_id: str | None = None,
    entity_id: str | None = None,
) -> bool:
    """Validate node payload against the model's replace schema. Returns True if valid."""
    from tap_grid.registry import get_model_class

    if not isinstance(payload, dict):
        issues.append(
            _issue(
                "schema_validation_failed",
                f"node payload at {path} must be an object",
                "schema",
                path,
                entity_id=entity_id,
                batch_entity_id=batch_entity_id,
            )
        )
        return False

    try:
        model_cls = get_model_class(entity_type)
    except KeyError:
        issues.append(
            _issue(
                "unknown_entity_type",
                f"Unknown entity type '{entity_type}' at {path}",
                "validation",
                path,
                entity_id=entity_id,
                batch_entity_id=batch_entity_id,
                entity_type=entity_type,
            )
        )
        return False

    replace_schema = model_cls.SERVICE_CRUD_SCHEMA.get("replace", {})
    if replace_schema:
        # Mirror the service write path's null semantics BEFORE validating
        # (req-grid-service-write-observation-2): an explicit null on a known
        # non-null field is dropped — treated as absent — exactly as the write
        # path's preparation will do again at write time. Validating the raw
        # payload here rejected batches the service layer itself would accept
        # (a collector's graceful-missing None, e.g. an AWS response field the
        # API omitted). Null on a null-permitting field and null on an UNKNOWN
        # field are preserved, so clears still earn FLIP and
        # additionalProperties:false still rejects strangers.
        from tap_grid.null_semantics import prepare_null_payload

        try:
            jsonschema.validate(instance=prepare_null_payload(payload, replace_schema), schema=replace_schema)
        except jsonschema.ValidationError as exc:
            issues.append(
                _issue(
                    "payload_validation_failed",
                    exc.message,
                    "validation",
                    f"{path}.{exc.json_path}" if exc.json_path != "$" else path,
                    entity_id=entity_id,
                    batch_entity_id=batch_entity_id,
                    entity_type=entity_type,
                )
            )
            return False

    return True


# ---------------------------------------------------------------------------
# Edge payload validator
# ---------------------------------------------------------------------------


def _endpoint_key_is_sound(
    endpoint: Any,
    path: str,
    issues: list[GriftIssue],
    *,
    batch_entity_id: str | None,
    entity_id: str | None,
) -> bool:
    """Check an endpoint named by type and natural key, without reading the grid.

    The type must declare a ``NATURAL_KEY`` (a ``KEYLESS`` or undeclared type has nothing to find
    it by), and the key must carry exactly the declared properties, none of them null: a hole
    would find nothing and look like an unresolved endpoint, so it is refused here instead
    (``req-grid-import-grift-edge-endpoints-3``). ``""`` is observed-empty and is a value, as for
    nodes (``req-grid-entity-natural-key-16``).

    TAP-IMPLEMENTS: req-grid-import-grift-edge-endpoints@36d488ac168c/736330ee28b7 (enforcement) —
        the preflight refusal of a key endpoint that could never resolve honestly: an unkeyed
        type, a missing or null declared property, or a property the type does not declare.
    """
    from tap_grid.natural_key import Keyless
    from tap_grid.registry import get_model_class

    def refuse(code: str, message: str) -> bool:
        issues.append(_issue(code, message, "validation", path, entity_id=entity_id, batch_entity_id=batch_entity_id))
        return False

    if (
        not isinstance(endpoint, dict)
        or set(endpoint) != {"entity_type", "key"}
        or not isinstance(endpoint["key"], dict)
    ):
        return refuse("schema_validation_failed", f"An endpoint key at {path} is {{entity_type, key: {{...}}}}")
    entity_type = endpoint["entity_type"]
    try:
        model_cls = get_model_class(entity_type)
    except KeyError:
        return refuse("unknown_entity_type", f"Unknown entity type {entity_type!r} for the endpoint at {path}")
    declared = getattr(model_cls, "NATURAL_KEY", None)
    if declared is None or isinstance(declared, Keyless):
        state = "is keyless" if isinstance(declared, Keyless) else "declares no NATURAL_KEY"
        return refuse(
            "endpoint_type_unkeyed",
            f"{entity_type} {state}, so an endpoint cannot name it by key at {path}; address it by id or ref",
        )
    key = endpoint["key"]
    undeclared = sorted(set(key) - set(declared))
    if undeclared:
        return refuse(
            "endpoint_key_mismatch",
            f"The endpoint key at {path} names {undeclared}, which {entity_type} does not declare; its NATURAL_KEY is "
            f"{list(declared)}",
        )
    holes = [name for name in declared if key.get(name) is None]
    if holes:
        return refuse(
            "incomplete_endpoint_key",
            f"The endpoint key at {path} has no value for {holes} of {entity_type}'s NATURAL_KEY {list(declared)}; "
            "an incomplete key is refused, never looked up",
        )
    return True


def _validate_edge_payload(
    payload: Any,
    path: str,
    issues: list[GriftIssue],
    *,
    batch_entity_id: str | None = None,
    entity_id: str | None = None,
) -> bool:
    """Validate GriftEdgePayload shape. Returns True if structurally valid."""
    if not isinstance(payload, dict):
        issues.append(
            _issue(
                "schema_validation_failed",
                f"edge payload at {path} must be an object",
                "schema",
                path,
                entity_id=entity_id,
                batch_entity_id=batch_entity_id,
            )
        )
        return False

    for key in payload:
        if key not in _EDGE_PAYLOAD_ALLOWED:
            issues.append(
                _issue(
                    "schema_validation_failed",
                    f"Unknown key '{key}' in edge payload at {path}.{key}",
                    "schema",
                    f"{path}.{key}",
                    entity_id=entity_id,
                    batch_entity_id=batch_entity_id,
                )
            )

    for req in _EDGE_PAYLOAD_REQUIRED:
        if req not in payload:
            issues.append(
                _issue(
                    "schema_validation_failed",
                    f"Missing required field '{req}' in edge payload at {path}",
                    "schema",
                    f"{path}.{req}",
                    entity_id=entity_id,
                    batch_entity_id=batch_entity_id,
                )
            )

    ok = True
    for side, id_field, key_field in _EDGE_ENDPOINT_FORMS:
        given = [f for f in (id_field, key_field) if f in payload]
        if len(given) != 1:
            issues.append(
                _issue(
                    "schema_validation_failed",
                    f"The {side} endpoint at {path} needs exactly one of {id_field} and {key_field} "
                    f"(or a {side}_ref, resolved before this check); found {given or 'neither'}",
                    "schema",
                    f"{path}.{id_field}",
                    entity_id=entity_id,
                    batch_entity_id=batch_entity_id,
                )
            )
            ok = False
        elif key_field in payload and not _endpoint_key_is_sound(
            payload[key_field], f"{path}.{key_field}", issues, batch_entity_id=batch_entity_id, entity_id=entity_id
        ):
            ok = False
    for uuid_field in ("from_entity_id", "to_entity_id"):
        if uuid_field not in payload:
            continue
        canonical = _check_uuid(payload[uuid_field], f"{path}.{uuid_field}", issues, batch_entity_id=batch_entity_id)
        if canonical is None:
            ok = False
            continue
        payload[uuid_field] = canonical  # one spelling: endpoint resolution compares against node ids

    if "edge_type" in payload and (not isinstance(payload["edge_type"], str) or not payload["edge_type"]):
        issues.append(
            _issue(
                "schema_validation_failed",
                f"edge_type must be a non-empty string at {path}.edge_type",
                "schema",
                f"{path}.edge_type",
                entity_id=entity_id,
                batch_entity_id=batch_entity_id,
            )
        )
        ok = False

    if "properties" in payload and not isinstance(payload["properties"], dict):
        issues.append(
            _issue(
                "schema_validation_failed",
                f"properties must be an object at {path}.properties",
                "schema",
                f"{path}.properties",
                entity_id=entity_id,
                batch_entity_id=batch_entity_id,
            )
        )
        ok = False

    return ok


# ---------------------------------------------------------------------------
# Removal-section preflight helper (req-grid-import-grift-removal-preflight)
# ---------------------------------------------------------------------------


@dataclass
class _ParsedRemovalTarget:
    """One removal target parsed from a `deletes` or `purges` section.

    `kind` is "edge" or "node" depending on which sub-array the target was
    listed under; `section` is "deletes" or "purges"; `path` is the JSONPath
    pointing at this target in the document for diagnostics. `batch_entity_id`
    is the owning batch's entity_id, captured so cross-document issues can
    cite which batch declared the duplicate target. `entity_expected_version`
    is the optional OCC declaration (req-grift-concurrency-version); when
    set, the importer passes it to the delete/purge verb as the
    `entity_expected_version` keyword and the verb performs the version
    check inside the same batch transaction.
    """

    entity_id: str
    entity_type: str
    reason: str
    section: Literal["deletes", "purges"]
    kind: Literal["edge", "node"]
    path: str
    batch_entity_id: str
    entity_expected_version: int | None = None


@dataclass
class _ParsedIdentityRemoval:
    """One `deletes.edges` target that names its edge by identity (req-grid-import-grift-edge-removal).

    It has no id until the batch executes: it ends whichever live edge of ``edge_type`` matches
    between the two endpoints then. Each endpoint is ``{"entity_id": ...}`` (canonical) or a key
    form ``{"entity_type", "key"}``; ``discriminators`` holds each declared path's value.
    """

    edge_type: str
    endpoints: dict[str, dict[str, Any]]  # "from" / "to" -> the endpoint as the target names it
    discriminators: dict[str, Any]
    reason: str
    path: str
    batch_entity_id: str


@dataclass
class _ParsedRemovalSections:
    """Parsed removal sections for one batch.

    Populated by ``_validate_removal_section`` during file-preflight; used by
    `_execute_grift_batch` to drive the transaction-scoped target checks
    (`req-grid-import-grift-removal-preflight`) and the actual delete/purge
    verbs (`req-grid-import-grift-removals`).
    """

    deletes_on_missing: Literal["error", "warn", "ignore"] | None = None
    deletes_on_tombstoned: Literal["error", "warn", "ignore"] | None = None
    purges_on_missing: Literal["error", "warn", "ignore"] | None = None
    deletes_edges: list[_ParsedRemovalTarget] = None  # type: ignore[assignment]
    deletes_nodes: list[_ParsedRemovalTarget] = None  # type: ignore[assignment]
    purges_edges: list[_ParsedRemovalTarget] = None  # type: ignore[assignment]
    purges_nodes: list[_ParsedRemovalTarget] = None  # type: ignore[assignment]
    deletes_edge_identities: list[_ParsedIdentityRemoval] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.deletes_edges is None:
            self.deletes_edges = []
        if self.deletes_nodes is None:
            self.deletes_nodes = []
        if self.purges_edges is None:
            self.purges_edges = []
        if self.purges_nodes is None:
            self.purges_nodes = []
        if self.deletes_edge_identities is None:
            self.deletes_edge_identities = []

    def has_purge_targets(self) -> bool:
        return bool(self.purges_edges or self.purges_nodes)

    def has_any_targets(self) -> bool:
        return bool(
            self.deletes_edges
            or self.deletes_nodes
            or self.purges_edges
            or self.purges_nodes
            or self.deletes_edge_identities
        )

    def all_targets(self) -> list[_ParsedRemovalTarget]:
        """Every id-addressed target; an identity-addressed one has no id until the batch executes."""
        return self.deletes_edges + self.deletes_nodes + self.purges_edges + self.purges_nodes


def _validate_edge_cases(
    edge_cases: dict[str, Any],
    path: str,
    issues: list[GriftIssue],
    *,
    batch_entity_id: str | None,
) -> None:
    """Refuse at preflight an authority claim that could never be judged honestly.

    The schema has already held the shape: a claim's ``edge_type``, ``anchor``, ``direction`` and
    ``read`` are present, the last two from their closed sets, and ``edge_cases`` has no other
    member (``req-grift-edge-identity-surface-3``). Here: ``dimensions`` is reserved and refused
    while present (Issue# 907 - tap); the edge type must not be internal-only, because what a claim
    proposes is a removal the generic path would refuse (``req-grid-edge-internal``); a key anchor
    must be one that could resolve. Edge types are open, as for the edges themselves: a type with no
    live edge in scope proposes nothing.
    """
    from tap_grid.constraints import is_internal_edge_type

    for idx, claim in enumerate(edge_cases.get("authority", [])):
        claim_path = f"{path}.authority[{idx}]"

        def refuse(code: str, message: str, where: str = claim_path) -> None:
            issues.append(_issue(code, message, "validation", where, batch_entity_id=batch_entity_id))

        if "dimensions" in claim:
            refuse(
                "authority_dimensions_reserved",
                f"The claim at {claim_path} carries dimensions, which are reserved until dimension-scoped claims "
                "exist (Issue# 907 - tap); a claim scoped by them cannot be honoured yet, so it is refused",
                f"{claim_path}.dimensions",
            )
        edge_type = claim["edge_type"]
        if is_internal_edge_type(edge_type):
            refuse(
                "authority_internal_edge_type",
                f"The claim at {claim_path} covers {edge_type!r}, an internal-only edge type: only the subsystem "
                "that owns it writes or removes it (req-grid-edge-internal)",
                f"{claim_path}.edge_type",
            )
        anchor = claim["anchor"]
        if "entity_id" not in anchor:
            _endpoint_key_is_sound(
                anchor, f"{claim_path}.anchor", issues, batch_entity_id=batch_entity_id, entity_id=None
            )


def _validate_removal_section(
    section_obj: Any,
    section_kind: Literal["deletes", "purges"],
    batch_path: str,
    batch_entity_id: str,
    issues: list[GriftIssue],
) -> tuple[
    Literal["error", "warn", "ignore"] | None,
    Literal["error", "warn", "ignore"] | None,
    list[_ParsedRemovalTarget],
    list[_ParsedRemovalTarget],
    list[_ParsedIdentityRemoval],
]:
    """Validate one `deletes` or `purges` section's shape and collect targets.

    TAP-IMPLEMENTS: req-grid-import-grift-removal-preflight@0844f41f72bc/f26d5e3424bb (derivation)
        — the file-level (state-free) phase of removal preflight.

    Returns a tuple ``(on_missing, on_tombstoned, edge_targets, node_targets, identity_targets)``.
    ``on_tombstoned`` is always ``None`` for the purges section, and ``identity_targets`` (the
    `deletes.edges` targets that name their edge by identity) is empty for it. Invalid
    targets are skipped with hard-error issues recorded against ``issues``;
    valid targets are returned in declaration order. Cross-section and
    cross-document duplicate checks happen at the caller level after every
    batch has been parsed.
    """
    section_path = f"{batch_path}.{section_kind}"

    if not isinstance(section_obj, dict):
        issues.append(
            _issue(
                "schema_validation_failed",
                f"{section_kind} section at {section_path} must be an object",
                "schema",
                section_path,
                batch_entity_id=batch_entity_id,
            )
        )
        return None, None, [], [], []

    required = _DELETES_REQUIRED if section_kind == "deletes" else _PURGES_REQUIRED
    allowed = _DELETES_ALLOWED if section_kind == "deletes" else _PURGES_ALLOWED

    for key in section_obj:
        if key not in allowed:
            issues.append(
                _issue(
                    "schema_validation_failed",
                    f"Unknown key '{key}' in {section_kind} section at {section_path}",
                    "schema",
                    f"{section_path}.{key}",
                    batch_entity_id=batch_entity_id,
                )
            )

    for req in required:
        if req not in section_obj:
            issues.append(
                _issue(
                    "schema_validation_failed",
                    f"Missing required key '{req}' in {section_kind} section at {section_path}",
                    "schema",
                    f"{section_path}.{req}",
                    batch_entity_id=batch_entity_id,
                )
            )

    on_missing = section_obj.get("on_missing")
    if on_missing is not None and on_missing not in _REMOVAL_POLICY_VALUES:
        issues.append(
            _issue(
                "schema_validation_failed",
                f"{section_kind}.on_missing must be one of {sorted(_REMOVAL_POLICY_VALUES)}; got {on_missing!r}",
                "schema",
                f"{section_path}.on_missing",
                batch_entity_id=batch_entity_id,
            )
        )
        on_missing = None

    on_tombstoned = None
    if section_kind == "deletes":
        on_tombstoned = section_obj.get("on_tombstoned")
        if on_tombstoned is not None and on_tombstoned not in _REMOVAL_POLICY_VALUES:
            issues.append(
                _issue(
                    "schema_validation_failed",
                    f"deletes.on_tombstoned must be one of {sorted(_REMOVAL_POLICY_VALUES)}; got {on_tombstoned!r}",
                    "schema",
                    f"{section_path}.on_tombstoned",
                    batch_entity_id=batch_entity_id,
                )
            )
            on_tombstoned = None

    def _parse_targets(sub_array: Any, sub_kind: Literal["edges", "nodes"]) -> list[_ParsedRemovalTarget]:
        sub_path = f"{section_path}.{sub_kind}"
        if not isinstance(sub_array, list):
            issues.append(
                _issue(
                    "schema_validation_failed",
                    f"{sub_path} must be an array",
                    "schema",
                    sub_path,
                    batch_entity_id=batch_entity_id,
                )
            )
            return []

        target_kind: Literal["edge", "node"] = "edge" if sub_kind == "edges" else "node"
        parsed: list[_ParsedRemovalTarget] = []
        seen_in_this_sub: set[str] = set()

        for idx, target in enumerate(sub_array):
            target_path = f"{sub_path}[{idx}]"

            if not isinstance(target, dict):
                issues.append(
                    _issue(
                        "schema_validation_failed",
                        f"Removal target at {target_path} must be an object",
                        "schema",
                        target_path,
                        batch_entity_id=batch_entity_id,
                    )
                )
                continue

            # A `deletes.edges` target without an id names its edge by identity; the document
            # schema has already held the exclusive-or (req-grid-import-grift-edge-removal-1).
            if section_kind == "deletes" and sub_kind == "edges" and "entity_id" not in target:
                by_identity = _parse_identity_removal(target, target_path, batch_entity_id, issues)
                if by_identity is not None:
                    identity_targets.append(by_identity)
                continue

            for key in target:
                if key not in _REMOVAL_TARGET_ALLOWED:
                    issues.append(
                        _issue(
                            "schema_validation_failed",
                            f"Unknown key '{key}' in removal target at {target_path}",
                            "schema",
                            f"{target_path}.{key}",
                            batch_entity_id=batch_entity_id,
                        )
                    )

            for req_key in _REMOVAL_TARGET_REQUIRED:
                if req_key not in target:
                    issues.append(
                        _issue(
                            "schema_validation_failed",
                            f"Missing required key '{req_key}' in removal target at {target_path}",
                            "schema",
                            f"{target_path}.{req_key}",
                            batch_entity_id=batch_entity_id,
                        )
                    )

            if not all(k in target for k in _REMOVAL_TARGET_REQUIRED):
                continue

            normalized_eid = _check_uuid(
                target["entity_id"], f"{target_path}.entity_id", issues, batch_entity_id=batch_entity_id
            )
            if normalized_eid is None:
                continue
            target["entity_id"] = normalized_eid  # one spelling on the preflight copy

            entity_type = target["entity_type"]
            if not isinstance(entity_type, str) or not entity_type:
                issues.append(
                    _issue(
                        "schema_validation_failed",
                        f"Removal target entity_type at {target_path} must be a non-empty string",
                        "schema",
                        f"{target_path}.entity_type",
                        batch_entity_id=batch_entity_id,
                    )
                )
                continue

            reason = target["reason"]
            if not isinstance(reason, str) or not reason.strip():
                issues.append(
                    _issue(
                        "schema_validation_failed",
                        f"Removal target reason at {target_path} must be a non-empty string",
                        "schema",
                        f"{target_path}.reason",
                        batch_entity_id=batch_entity_id,
                    )
                )
                continue

            # Optional OCC declaration (req-grift-concurrency-version).
            target_expected_version: int | None = target.get("entity_expected_version")
            if target_expected_version is not None:
                if not isinstance(target_expected_version, int) or target_expected_version < 1:
                    issues.append(
                        _issue(
                            "schema_validation_failed",
                            f"Removal target entity_expected_version at {target_path} must be "
                            "a positive integer (minimum 1); Entity.version starts at 1.",
                            "schema",
                            f"{target_path}.entity_expected_version",
                            batch_entity_id=batch_entity_id,
                        )
                    )
                    continue

            # Static type-vs-list sanity (req-grid-import-grift-removal-preflight
            # "Transaction-Scoped Target Checks"). The dynamic per-row check
            # happens inside the batch transaction; this catches obvious
            # authoring mistakes at file-preflight.
            if target_kind == "edge" and entity_type != "edge":
                issues.append(
                    _issue(
                        "removal_entity_type_mismatch",
                        f"Removal target at {target_path} is in the 'edges' list but "
                        f"declares entity_type={entity_type!r}; edge removals must declare entity_type='edge'",
                        "preflight",
                        f"{target_path}.entity_type",
                        entity_id=normalized_eid,
                        batch_entity_id=batch_entity_id,
                        entity_type=entity_type,
                    )
                )
                continue
            if target_kind == "node" and entity_type == "edge":
                issues.append(
                    _issue(
                        "removal_entity_type_mismatch",
                        f"Removal target at {target_path} is in the 'nodes' list but "
                        f"declares entity_type='edge'; node removals must declare a node entity_type",
                        "preflight",
                        f"{target_path}.entity_type",
                        entity_id=normalized_eid,
                        batch_entity_id=batch_entity_id,
                        entity_type=entity_type,
                    )
                )
                continue

            # Duplicate within this sub-array.
            if normalized_eid in seen_in_this_sub:
                issues.append(
                    _issue(
                        "duplicate_removal_target",
                        f"Removal target entity_id {normalized_eid} appears more than once " f"in {sub_path}",
                        "preflight",
                        f"{target_path}.entity_id",
                        entity_id=normalized_eid,
                        batch_entity_id=batch_entity_id,
                    )
                )
                continue
            seen_in_this_sub.add(normalized_eid)

            parsed.append(
                _ParsedRemovalTarget(
                    entity_id=normalized_eid,
                    entity_type=entity_type,
                    reason=reason,
                    section=section_kind,
                    kind=target_kind,
                    path=target_path,
                    batch_entity_id=batch_entity_id,
                    entity_expected_version=target_expected_version,
                )
            )

        return parsed

    identity_targets: list[_ParsedIdentityRemoval] = []
    edge_targets = _parse_targets(section_obj.get("edges", []), "edges")
    node_targets = _parse_targets(section_obj.get("nodes", []), "nodes")

    return on_missing, on_tombstoned, edge_targets, node_targets, identity_targets


def _parse_identity_removal(
    target: dict[str, Any],
    path: str,
    batch_entity_id: str,
    issues: list[GriftIssue],
) -> _ParsedIdentityRemoval | None:
    """Check a `deletes.edges` target that names its edge by identity, without reading the grid.

    The type must declare a plain identity: a keyless type has no identity to name and an
    undeclared one has none yet, so neither can be addressed this way. ``discriminators`` must
    carry exactly the declared paths, none absent, null or empty
    (``req-grid-import-grift-edge-removal-5``), and each endpoint is an id or a sound key.

    TAP-IMPLEMENTS: req-grid-import-grift-edge-removal@9b28437e0c32/acbf43103511 (enforcement) — the
        preflight refusal of an identity-addressed delete that could never match honestly: an
        unkeyed type, an incomplete or undeclared discriminator, an unsound endpoint.
    """
    from tap_grid.edge_identity import get_edge_identity, incomplete_paths

    def refuse(code: str, message: str, at: str = path) -> None:
        issues.append(_issue(code, message, "preflight", at, batch_entity_id=batch_entity_id, entity_type="edge"))

    edge_type = target["edge_type"]
    identity = get_edge_identity(edge_type)
    if identity is None or identity.keyless:
        state = "is keyless" if identity is not None else "declares no identity"
        refuse(
            "removal_identity_unkeyed",
            f"{edge_type} {state}, so the delete at {path} cannot name its edge by identity; name it by entity_id",
            f"{path}.edge_type",
        )
        return None
    given = target.get("discriminators")
    if given is None and identity.paths:
        given = {}
    if given is not None and not identity.paths:
        refuse(
            "schema_validation_failed",
            f"{edge_type} declares no discriminators, so the delete at {path} carries none",
            f"{path}.discriminators",
        )
        return None
    discriminators: dict[str, Any] = dict(given or {})
    undeclared = sorted(set(discriminators) - set(identity.paths))
    if undeclared:
        refuse(
            "schema_validation_failed",
            f"The delete at {path} names discriminators {undeclared}, which {edge_type} does not declare; "
            f"it declares {list(identity.paths)}",
            f"{path}.discriminators",
        )
        return None
    holes = incomplete_paths({p: discriminators.get(p) for p in identity.paths})
    if holes:
        refuse(
            "incomplete_edge_key",
            f"The delete at {path} has no value for {holes} of {edge_type}'s discriminators; an incomplete "
            "identity is refused, never looked up",
            f"{path}.discriminators",
        )
        return None
    endpoints: dict[str, dict[str, Any]] = {}
    for side in ("from", "to"):
        endpoint = target[side]
        at = f"{path}.{side}"
        if "entity_id" in endpoint:
            canonical = _check_uuid(endpoint["entity_id"], f"{at}.entity_id", issues, batch_entity_id=batch_entity_id)
            if canonical is None:
                return None
            endpoints[side] = {"entity_id": canonical}
        elif _endpoint_key_is_sound(endpoint, at, issues, batch_entity_id=batch_entity_id, entity_id=None):
            endpoints[side] = endpoint
        else:
            return None
    return _ParsedIdentityRemoval(
        edge_type=edge_type,
        endpoints=endpoints,
        discriminators=discriminators,
        reason=target["reason"],
        path=path,
        batch_entity_id=batch_entity_id,
    )


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def _load_grift_schema() -> dict[str, Any]:
    """Load and cache the GRIFT document JSON Schema."""
    return load_schema(_GRIFT_SCHEMA_PATH)


def _validate_document_schema(document: dict[str, Any], issues: list[GriftIssue]) -> bool:
    """Validate document against the GRIFT JSON Schema. Returns True if valid."""
    schema = _load_grift_schema()
    try:
        jsonschema.validate(instance=document, schema=schema)
        return True
    except jsonschema.ValidationError as exc:
        message = exc.message
        if exc.validator == "oneOf" and exc.context:
            # The envelope's entity_id XOR ref rule (and the edge endpoints' twin) is a
            # oneOf; jsonschema's own message names neither side, so spell them out.
            alternatives = "; ".join(sorted({c.message for c in exc.context}))
            message = f"{exc.message} — exactly one must hold: {alternatives}"
        issues.append(
            _issue(
                "schema_validation_failed",
                f"GRIFT document schema validation failed: {message}",
                "schema",
                exc.json_path if hasattr(exc, "json_path") else "$",
            )
        )
        return False


def validate_grift_document(document: dict[str, Any]) -> list[GriftIssue]:
    """Validate a parsed GRIFT document against the GRIFT JSON Schema, without
    touching the database.

    Returns the list of issues; an empty list means the document is structurally
    valid. This is the public pre-flight / dry-run validation surface — the same
    document-schema check the real importer runs (single source of truth). It is
    structural only: per-record model validation (``full_validate``) runs against
    the database during a real import and is therefore out of scope here.
    """
    issues: list[GriftIssue] = []
    _validate_document_schema(document, issues)
    return issues


def _run_preflight(
    document: dict[str, Any],
    *,
    reference_time: datetime,
    dangling_edge_mode: Literal["strict", "permissive"],
    force_batches: set[str] | None = None,
) -> _PreflightResult:
    """Full-file preflight pass. No mutations — returns a _PreflightResult.

    TAP-IMPLEMENTS: req-tap-plugin-arch-iterative-dev@223f7d13fe50/b274eab851e8 (enforcement) —
        the skip-if-already-imported check here is what makes edited-in-place GRIFT
        content inert: a seen batch_entity_id is skipped (absent an explicit force),
        so plugins MUST version-bump or force-reimport, never rely on silent re-import.


    TAP-IMPLEMENTS: req-grid-import-grift-preflight@66dca68b3459/b274eab851e8 (derivation) — the
        full-file, mutation-free preflight pass.

    When ``force_batches`` contains a batch's entity_id, the default
    skip-if-exists guard is bypassed and that batch is added to
    batches_to_import even when a Batch row already exists locally.
    """
    issues: list[GriftIssue] = []
    force_batches = force_batches or set()

    # --- JSON Schema structural validation ---
    if not _validate_document_schema(document, issues):
        return _PreflightResult(
            ok=False, batches_to_import=[], batches_to_skip=[], dangling_edge_ids=set(), issues=issues
        )

    # --- Top-level structure ---
    for key in document:
        if key not in _DOC_ALLOWED:
            issues.append(_issue("schema_validation_failed", f"Unknown top-level key '{key}'", "schema", f"$.{key}"))

    for req in _DOC_REQUIRED:
        if req not in document:
            issues.append(
                _issue("schema_validation_failed", f"Missing required top-level key '{req}'", "schema", f"$.{req}")
            )

    if any(i.code == "schema_validation_failed" for i in issues):
        return _PreflightResult(
            ok=False, batches_to_import=[], batches_to_skip=[], dangling_edge_ids=set(), issues=issues
        )

    # --- Batch-local refs → ids (the gate, shape A — Issue# 593 - tap) ---
    # One pass, on a copy, before anything below reads an entity_id: from here
    # on every stage sees ids only, and a ref can reach no record. A ref that
    # cannot be resolved fails the file here, before any other check runs.
    resolution = resolve_refs(document)
    for ref_issue in resolution.issues:
        issues.append(
            _issue(
                ref_issue.code,
                ref_issue.message,
                "preflight",
                ref_issue.path,
                batch_entity_id=ref_issue.batch_entity_id,
            )
        )
    if resolution.issues:
        return _PreflightResult(
            ok=False, batches_to_import=[], batches_to_skip=[], dangling_edge_ids=set(), issues=issues
        )
    document = resolution.document

    # --- metadata ---
    metadata = document["metadata"]
    if not isinstance(metadata, dict):
        issues.append(_issue("schema_validation_failed", "metadata must be an object", "schema", "$.metadata"))
    else:
        for key in metadata:
            if key not in _METADATA_ALLOWED:
                issues.append(
                    _issue(
                        "schema_validation_failed", f"Unknown key '{key}' in metadata", "schema", f"$.metadata.{key}"
                    )
                )
        gv = metadata.get("grift_version")
        if gv is None:
            issues.append(
                _issue(
                    "schema_validation_failed",
                    "Missing grift_version in metadata",
                    "schema",
                    "$.metadata.grift_version",
                )
            )
        elif not isinstance(gv, str) or not gv:
            issues.append(
                _issue(
                    "schema_validation_failed",
                    "grift_version must be a non-empty string",
                    "schema",
                    "$.metadata.grift_version",
                )
            )
        elif gv != GRIFT_VERSION:
            # req-grid-import-grift-preflight-4: this importer speaks GRIFT v0 only; an unknown
            # version refuses the file rather than guessing at its meaning (Issue# 630 - tap).
            issues.append(
                _issue(
                    "unsupported_grift_version",
                    f"grift_version {gv!r} is not supported: this importer reads GRIFT version {GRIFT_VERSION!r} only",
                    "preflight",
                    "$.metadata.grift_version",
                )
            )

    if not isinstance(document.get("_reserved"), dict):
        issues.append(_issue("schema_validation_failed", "_reserved must be an object", "schema", "$._reserved"))

    if not isinstance(document.get("batches"), list):
        issues.append(_issue("schema_validation_failed", "batches must be an array", "schema", "$.batches"))
        return _PreflightResult(
            ok=False, batches_to_import=[], batches_to_skip=[], dangling_edge_ids=set(), issues=issues
        )

    if any(i.code in ("schema_validation_failed", "unsupported_grift_version") for i in issues):
        return _PreflightResult(
            ok=False, batches_to_import=[], batches_to_skip=[], dangling_edge_ids=set(), issues=issues
        )

    # --- Per-batch validation ---
    all_entity_ids: set[str] = set()
    all_batch_ids: set[str] = set()
    # Entity IDs that will be present after this import (in-file nodes, excluding edges).
    file_node_ids: set[str] = set()
    dangling_edge_ids: set[str] = set()
    batches_to_import: list[tuple[int, dict[str, Any]]] = []
    batches_to_skip: list[GriftSkippedBatch] = []
    parsed_removals_by_idx: dict[int, _ParsedRemovalSections] = {}

    for batch_idx, batch_container in enumerate(document["batches"]):
        batch_path = f"$.batches[{batch_idx}]"

        if not isinstance(batch_container, dict):
            issues.append(
                _issue("schema_validation_failed", f"Batch at {batch_path} must be an object", "schema", batch_path)
            )
            continue

        for key in batch_container:
            if key not in _BATCH_ALLOWED:
                issues.append(
                    _issue(
                        "schema_validation_failed",
                        f"Unknown key '{key}' in batch at {batch_path}.{key}",
                        "schema",
                        f"{batch_path}.{key}",
                    )
                )

        for req in _BATCH_REQUIRED:
            if req not in batch_container:
                issues.append(
                    _issue(
                        "schema_validation_failed",
                        f"Missing required key '{req}' in batch at {batch_path}",
                        "schema",
                        f"{batch_path}.{req}",
                    )
                )

        if not all(k in batch_container for k in _BATCH_REQUIRED):
            continue

        # Validate batch_entity envelope.
        batch_entity_id = _validate_envelope(
            batch_container["batch_entity"],
            f"{batch_path}.batch_entity",
            issues,
            reference_time=reference_time,
        )
        if batch_entity_id is None:
            continue

        # batch_entity.entity_type must be "batch".
        if batch_container["batch_entity"].get("entity_type") != "batch":
            got = batch_container["batch_entity"].get("entity_type")
            issues.append(
                _issue(
                    "entity_type_mismatch",
                    f"batch_entity.entity_type must be 'batch', got '{got}'",
                    "validation",
                    f"{batch_path}.batch_entity.entity_type",
                    entity_id=batch_entity_id,
                    batch_entity_id=batch_entity_id,
                )
            )

        # Duplicate batch-level checks.
        if batch_entity_id in all_batch_ids:
            issues.append(
                _issue(
                    "duplicate_batch_id",
                    f"Duplicate batch entity_id '{batch_entity_id}'",
                    "preflight",
                    f"{batch_path}.batch_entity.entity_id",
                    entity_id=batch_entity_id,
                    batch_entity_id=batch_entity_id,
                )
            )
            continue
        all_batch_ids.add(batch_entity_id)

        if batch_entity_id in all_entity_ids:
            issues.append(
                _issue(
                    "duplicate_entity_id",
                    f"Duplicate entity_id '{batch_entity_id}'",
                    "preflight",
                    f"{batch_path}.batch_entity.entity_id",
                    entity_id=batch_entity_id,
                    batch_entity_id=batch_entity_id,
                )
            )
            continue
        all_entity_ids.add(batch_entity_id)

        # Validate batch_node payload against Batch replace schema.
        if not isinstance(batch_container["batch_node"], dict):
            issues.append(
                _issue(
                    "schema_validation_failed",
                    f"batch_node at {batch_path}.batch_node must be an object",
                    "schema",
                    f"{batch_path}.batch_node",
                    batch_entity_id=batch_entity_id,
                )
            )
        else:
            from tap_grid.models import Batch

            replace_schema = Batch.SERVICE_CRUD_SCHEMA.get("replace", {})
            if replace_schema:
                try:
                    jsonschema.validate(instance=batch_container["batch_node"], schema=replace_schema)
                except jsonschema.ValidationError as exc:
                    issues.append(
                        _issue(
                            "payload_validation_failed",
                            exc.message,
                            "validation",
                            f"{batch_path}.batch_node",
                            entity_id=batch_entity_id,
                            batch_entity_id=batch_entity_id,
                        )
                    )

        # nodes/edges must be arrays.
        if not isinstance(batch_container["nodes"], list):
            issues.append(
                _issue(
                    "schema_validation_failed",
                    f"nodes at {batch_path}.nodes must be an array",
                    "schema",
                    f"{batch_path}.nodes",
                    batch_entity_id=batch_entity_id,
                )
            )
            continue
        if not isinstance(batch_container["edges"], list):
            issues.append(
                _issue(
                    "schema_validation_failed",
                    f"edges at {batch_path}.edges must be an array",
                    "schema",
                    f"{batch_path}.edges",
                    batch_entity_id=batch_entity_id,
                )
            )
            continue

        # Retirement blocks this batch carries, counted for its contents declaration.
        retired_nodes = 0
        retired_edges = 0

        # Validate each node object.
        for node_idx, node_obj in enumerate(batch_container["nodes"]):
            node_path = f"{batch_path}.nodes[{node_idx}]"

            if not isinstance(node_obj, dict):
                issues.append(
                    _issue(
                        "schema_validation_failed",
                        f"Node at {node_path} must be an object",
                        "schema",
                        node_path,
                        batch_entity_id=batch_entity_id,
                    )
                )
                continue

            for key in node_obj:
                if key not in _NODE_ALLOWED:
                    issues.append(
                        _issue(
                            "schema_validation_failed",
                            f"Unknown key '{key}' in node at {node_path}.{key}",
                            "schema",
                            f"{node_path}.{key}",
                            batch_entity_id=batch_entity_id,
                        )
                    )

            for req in _NODE_REQUIRED:
                if req not in node_obj:
                    issues.append(
                        _issue(
                            "schema_validation_failed",
                            f"Missing required key '{req}' in node at {node_path}",
                            "schema",
                            f"{node_path}.{req}",
                            batch_entity_id=batch_entity_id,
                        )
                    )

            if not all(k in node_obj for k in _NODE_REQUIRED):
                continue

            node_entity_id = _validate_envelope(
                node_obj["entity"],
                f"{node_path}.entity",
                issues,
                reference_time=reference_time,
                batch_entity_id=batch_entity_id,
            )
            if node_entity_id is None:
                continue

            if node_entity_id in all_entity_ids:
                issues.append(
                    _issue(
                        "duplicate_entity_id",
                        f"Duplicate entity_id '{node_entity_id}'",
                        "preflight",
                        f"{node_path}.entity.entity_id",
                        entity_id=node_entity_id,
                        batch_entity_id=batch_entity_id,
                    )
                )
                continue
            all_entity_ids.add(node_entity_id)
            file_node_ids.add(node_entity_id)

            entity_type = node_obj["entity"].get("entity_type", "")
            _validate_node_payload(
                node_obj["node"],
                entity_type,
                f"{node_path}.node",
                issues,
                batch_entity_id=batch_entity_id,
                entity_id=node_entity_id,
            )
            if "retirement" in node_obj:
                retired_nodes += 1
                _validate_retirement_block(
                    node_obj["retirement"],
                    f"{node_path}.retirement",
                    issues,
                    reference_time=reference_time,
                    batch_entity_id=batch_entity_id,
                    entity_id=node_entity_id,
                )

            # Identity Sanity for redundant identity-bearing fields. The GRIFT
            # envelope can carry `name` alongside the typed model payload that
            # also carries `name` (the model's name field is the source of
            # truth; the envelope's name is the spine projection). When both
            # are declared, they must agree exactly. Bundles that omit
            # `entity.name` (or set it empty) are unaffected — the spine
            # projection is materialized from the model's name on import.
            # See spec-grid-import-grift.md req-grid-import-grift-preflight
            # "Identity Sanity".
            envelope_name = node_obj["entity"].get("name")
            payload = node_obj.get("node")
            if (
                envelope_name
                and isinstance(payload, dict)
                and isinstance(payload.get("name"), str)
                and payload["name"]
                and envelope_name.strip() != payload["name"].strip()
            ):
                issues.append(
                    _issue(
                        "envelope_payload_name_mismatch",
                        (
                            f"Envelope name {envelope_name!r} does not match "
                            f"node payload name {payload['name']!r}. The "
                            f"GRIFT envelope's `name` is a projection of the "
                            f"typed model's name field; the two must match "
                            f"exactly when both are declared."
                        ),
                        "validation",
                        f"{node_path}.entity.name",
                        entity_id=node_entity_id,
                        batch_entity_id=batch_entity_id,
                        entity_type=entity_type,
                    )
                )

        # Validate each edge object.
        for edge_idx, edge_obj in enumerate(batch_container["edges"]):
            edge_path = f"{batch_path}.edges[{edge_idx}]"

            if not isinstance(edge_obj, dict):
                issues.append(
                    _issue(
                        "schema_validation_failed",
                        f"Edge at {edge_path} must be an object",
                        "schema",
                        edge_path,
                        batch_entity_id=batch_entity_id,
                    )
                )
                continue

            for key in edge_obj:
                if key not in _EDGE_ALLOWED:
                    issues.append(
                        _issue(
                            "schema_validation_failed",
                            f"Unknown key '{key}' in edge at {edge_path}.{key}",
                            "schema",
                            f"{edge_path}.{key}",
                            batch_entity_id=batch_entity_id,
                        )
                    )

            for req in _EDGE_REQUIRED:
                if req not in edge_obj:
                    issues.append(
                        _issue(
                            "schema_validation_failed",
                            f"Missing required key '{req}' in edge at {edge_path}",
                            "schema",
                            f"{edge_path}.{req}",
                            batch_entity_id=batch_entity_id,
                        )
                    )

            if not all(k in edge_obj for k in _EDGE_REQUIRED):
                continue

            edge_entity_id = _validate_envelope(
                edge_obj["entity"],
                f"{edge_path}.entity",
                issues,
                reference_time=reference_time,
                batch_entity_id=batch_entity_id,
            )
            if edge_entity_id is None:
                continue

            if edge_obj["entity"].get("entity_type") != "edge":
                got = edge_obj["entity"].get("entity_type")
                issues.append(
                    _issue(
                        "entity_type_mismatch",
                        f"edge entity envelope must have entity_type='edge', got '{got}'",
                        "validation",
                        f"{edge_path}.entity.entity_type",
                        entity_id=edge_entity_id,
                        batch_entity_id=batch_entity_id,
                    )
                )

            if edge_entity_id in all_entity_ids:
                issues.append(
                    _issue(
                        "duplicate_entity_id",
                        f"Duplicate entity_id '{edge_entity_id}'",
                        "preflight",
                        f"{edge_path}.entity.entity_id",
                        entity_id=edge_entity_id,
                        batch_entity_id=batch_entity_id,
                    )
                )
                continue
            all_entity_ids.add(edge_entity_id)

            _validate_edge_payload(
                edge_obj["edge"], f"{edge_path}.edge", issues, batch_entity_id=batch_entity_id, entity_id=edge_entity_id
            )
            if "retirement" in edge_obj:
                retired_edges += 1
                _validate_retirement_block(
                    edge_obj["retirement"],
                    f"{edge_path}.retirement",
                    issues,
                    reference_time=reference_time,
                    batch_entity_id=batch_entity_id,
                    entity_id=edge_entity_id,
                )

        if "contents" in batch_container:
            _validate_contents(
                batch_container["contents"],
                retired_nodes=retired_nodes,
                retired_edges=retired_edges,
                path=f"{batch_path}.contents",
                issues=issues,
                batch_entity_id=batch_entity_id,
            )
        if "edge_cases" in batch_container:
            _validate_edge_cases(
                batch_container["edge_cases"], f"{batch_path}.edge_cases", issues, batch_entity_id=batch_entity_id
            )

        # --- Removal section preflight (req-grid-import-grift-removal-preflight) ---
        # Validate optional `deletes` and `purges` sections: shape, target
        # shape, within-section duplicates, static type-vs-list sanity. Stash
        # parsed sections on the batch_container under `_parsed_removals` so
        # the executor can drive transaction-scoped checks + verb calls
        # without re-parsing.
        parsed_removals = _ParsedRemovalSections()
        if "deletes" in batch_container:
            (
                parsed_removals.deletes_on_missing,
                parsed_removals.deletes_on_tombstoned,
                parsed_removals.deletes_edges,
                parsed_removals.deletes_nodes,
                parsed_removals.deletes_edge_identities,
            ) = _validate_removal_section(
                batch_container["deletes"],
                "deletes",
                batch_path,
                batch_entity_id,
                issues,
            )
        if "purges" in batch_container:
            (
                parsed_removals.purges_on_missing,
                _ignored,
                parsed_removals.purges_edges,
                parsed_removals.purges_nodes,
                _no_identities,
            ) = _validate_removal_section(
                batch_container["purges"],
                "purges",
                batch_path,
                batch_entity_id,
                issues,
            )

        # Cross-section duplicate inside this batch: same entity_id appearing
        # under more than one of deletes.edges / deletes.nodes / purges.edges /
        # purges.nodes (across sub-arrays, including same-target-in-both-
        # delete-and-purge and node-vs-edge mix). Within-sub-array dupes were
        # caught by the helper.
        per_batch_seen: dict[str, _ParsedRemovalTarget] = {}
        for target in parsed_removals.all_targets():
            if target.entity_id in per_batch_seen:
                first = per_batch_seen[target.entity_id]
                issues.append(
                    _issue(
                        "duplicate_removal_target",
                        f"Removal target entity_id {target.entity_id} appears in both "
                        f"{first.section}.{first.kind}s and {target.section}.{target.kind}s "
                        f"within {batch_path}",
                        "preflight",
                        f"{target.path}.entity_id",
                        entity_id=target.entity_id,
                        batch_entity_id=batch_entity_id,
                    )
                )
                continue
            per_batch_seen[target.entity_id] = target

        # Purge DEBUG gate (req-grid-import-grift-removal-preflight "Purge
        # Gate"). Fires on declaration, not on outcome — a purges section
        # with at least one declared target is refused under DEBUG=False
        # regardless of whether targets end up being skipped at execution
        # time.
        if parsed_removals.has_purge_targets():
            from django.conf import settings as _settings

            if not getattr(_settings, "DEBUG", False):
                issues.append(
                    _issue(
                        "grift_purge_refused_production",
                        f"purges section in {batch_path} is refused: DEBUG=False. "
                        "Purge is permitted only when DEBUG=True; see req-grid-service-purge.",
                        "preflight",
                        f"{batch_path}.purges",
                        batch_entity_id=batch_entity_id,
                    )
                )

        # Stash for the executor (keyed by batch_idx to avoid mutating the
        # input document; mutating would break second-import re-validation).
        parsed_removals_by_idx[batch_idx] = parsed_removals

        # Check batch idempotency: already exists locally?
        # req-grid-import-grift-force-reimport: bypass the skip-if-exists guard
        # when this batch_entity_id is in the explicit force_batches set.
        from tap_grid.models import Batch

        already_exists = Batch.all_objects.filter(entity_id=batch_entity_id).exists()

        if already_exists and batch_entity_id not in force_batches:
            batches_to_skip.append(
                GriftSkippedBatch(batch_entity_id=batch_entity_id, path=batch_path, reason="batch_already_imported")
            )
            # req-grid-import-grift-skipped-batch-removals: if the skipped
            # batch declared removal targets, emit a loud warning so the
            # operator sees that their explicit `deletes`/`purges` did not
            # fire. The normal [skip] line + skipped_batches[] entry covers
            # upsert-only batches; for removal-bearing batches we add a
            # distinct warning with the --force-batches recipe.
            if parsed_removals.has_any_targets():
                de = len(parsed_removals.deletes_edges) + len(parsed_removals.deletes_edge_identities)
                dn = len(parsed_removals.deletes_nodes)
                pe = len(parsed_removals.purges_edges)
                pn = len(parsed_removals.purges_nodes)
                issues.append(
                    _issue(
                        "skipped_batch_had_removals",
                        (
                            f"Batch {batch_entity_id} was skipped (already imported) but its "
                            f"document container declared removal targets: "
                            f"deletes.edges={de}, deletes.nodes={dn}, "
                            f"purges.edges={pe}, purges.nodes={pn}. "
                            f"These removals did NOT fire. To re-run this batch with the "
                            f"removals applied, invoke with --force-batches={batch_entity_id}."
                        ),
                        "preflight",
                        batch_path,
                        batch_entity_id=batch_entity_id,
                    )
                )
        elif already_exists and batch_entity_id in force_batches:
            # Force re-import: skip the guard and include this batch in
            # batches_to_import. Execution-time code distinguishes force re-imports
            # by checking whether a Batch row already exists.
            batches_to_import.append((batch_idx, batch_container))
        elif Entity.objects.filter(pk=uuid.UUID(batch_entity_id)).exclude(entity_type="batch").exists():
            issues.append(
                _issue(
                    "entity_type_mismatch",
                    f"entity_id '{batch_entity_id}' exists locally but is not a batch",
                    "preflight",
                    f"{batch_path}.batch_entity.entity_id",
                    entity_id=batch_entity_id,
                    batch_entity_id=batch_entity_id,
                )
            )
        else:
            batches_to_import.append((batch_idx, batch_container))

    # --- Dangling edge resolution ---
    # Only check batches we'll actually import.
    for batch_idx, batch_container in batches_to_import:
        batch_path = f"$.batches[{batch_idx}]"
        batch_entity_id = batch_container["batch_entity"]["entity_id"]

        for edge_idx, edge_obj in enumerate(batch_container.get("edges", [])):
            edge_path = f"{batch_path}.edges[{edge_idx}]"
            edge = edge_obj.get("edge", {})
            edge_entity_id = edge_obj.get("entity", {}).get("entity_id")

            if not isinstance(edge, dict):
                continue

            from_id = edge.get("from_entity_id")
            to_id = edge.get("to_entity_id")
            is_dangling = False

            for endpoint_id, field_name in ((from_id, "from_entity_id"), (to_id, "to_entity_id")):
                if not endpoint_id:
                    continue
                # Resolve against: (1) in-file node ids, (2) LIVE grid entities. A tombstoned
                # endpoint is dangling: no live edge may point at a tombstone (Issue# 609 -
                # tap, ruled 2026-09-18), and the service layer would refuse the edge anyway.
                if endpoint_id not in file_node_ids:
                    try:
                        exists = Entity.objects.filter(pk=uuid.UUID(endpoint_id), deleted_at__isnull=True).exists()
                    except ValueError, TypeError:
                        exists = False

                    if not exists:
                        is_dangling = True
                        if dangling_edge_mode == "strict":
                            issues.append(
                                _issue(
                                    "dangling_edge",
                                    f"Edge endpoint {field_name}='{endpoint_id}' not found in file or grid",
                                    "preflight",
                                    f"{edge_path}.edge.{field_name}",
                                    entity_id=edge_entity_id,
                                    batch_entity_id=batch_entity_id,
                                    from_entity_id=from_id,
                                    to_entity_id=to_id,
                                    edge_entity_id=edge_entity_id,
                                )
                            )
                        else:
                            if edge_entity_id:
                                dangling_edge_ids.add(edge_entity_id)

            if is_dangling and dangling_edge_mode == "permissive" and edge_entity_id:
                dangling_edge_ids.add(edge_entity_id)

    # --- Identity sanity: entity_type consistency for existing entities ---
    # For each node/edge being imported, if it already exists in the grid its
    # entity_type must match what the GRIFT file declares.  One bulk query covers
    # all batches to import; invalid UUIDs are skipped (already flagged above).
    grift_types: dict[str, tuple[str, str, str | None]] = {}  # normalized_id -> (type, path, batch_eid)
    for batch_idx_s, batch_container_s in batches_to_import:
        batch_path_s = f"$.batches[{batch_idx_s}]"
        batch_eid_s = batch_container_s["batch_entity"]["entity_id"]
        for node_idx_s, node_obj_s in enumerate(batch_container_s.get("nodes", [])):
            raw_eid = node_obj_s.get("entity", {}).get("entity_id")
            raw_type = node_obj_s.get("entity", {}).get("entity_type", "")
            if raw_eid and raw_type:
                try:
                    grift_types[str(uuid.UUID(raw_eid))] = (
                        raw_type,
                        f"{batch_path_s}.nodes[{node_idx_s}].entity.entity_type",
                        batch_eid_s,
                    )
                except ValueError, AttributeError:
                    pass
        for edge_idx_s, edge_obj_s in enumerate(batch_container_s.get("edges", [])):
            raw_eid = edge_obj_s.get("entity", {}).get("entity_id")
            if raw_eid:
                try:
                    grift_types[str(uuid.UUID(raw_eid))] = (
                        "edge",
                        f"{batch_path_s}.edges[{edge_idx_s}].entity.entity_type",
                        batch_eid_s,
                    )
                except ValueError, AttributeError:
                    pass

    if grift_types:
        for entity_uuid, grid_type in Entity.objects.filter(pk__in=[uuid.UUID(eid) for eid in grift_types]).values_list(
            "id", "entity_type"
        ):
            norm = str(entity_uuid)
            if norm not in grift_types:
                continue
            grift_type, sanity_path, batch_eid_s = grift_types[norm]
            if grift_type != grid_type:
                issues.append(
                    _issue(
                        "entity_type_mismatch",
                        f"Entity {norm} exists in grid as '{grid_type}' but GRIFT declares '{grift_type}'",
                        "preflight",
                        sanity_path,
                        entity_id=norm,
                        batch_entity_id=batch_eid_s,
                        entity_type=grift_type,
                    )
                )

    # --- Cross-document removal duplicates + upsert/removal cross-section
    # duplicates (req-grid-import-grift-removal-preflight). Same entity_id may
    # not appear under more than one removal target across the entire document
    # (handled via duplicate_removal_target). Same entity_id may not appear
    # both as an upsert (in `nodes`/`edges`) AND as a removal target anywhere
    # in the document (handled via entity_id_in_upsert_and_removal). ---
    seen_removal_ids: dict[str, _ParsedRemovalTarget] = {}
    for batch_idx_s, batch_container_s in batches_to_import:
        parsed = parsed_removals_by_idx.get(batch_idx_s)
        if parsed is None:
            continue
        for target in parsed.all_targets():
            prior = seen_removal_ids.get(target.entity_id)
            if prior is not None and prior is not target:
                issues.append(
                    _issue(
                        "duplicate_removal_target",
                        f"Removal target entity_id {target.entity_id} appears more than once "
                        f"across the document (first at {prior.path}, again at {target.path})",
                        "preflight",
                        f"{target.path}.entity_id",
                        entity_id=target.entity_id,
                        batch_entity_id=batch_container_s["batch_entity"]["entity_id"],
                    )
                )
            else:
                seen_removal_ids[target.entity_id] = target

    if seen_removal_ids:
        upsert_and_removal_collisions = seen_removal_ids.keys() & all_entity_ids
        for collision_eid in sorted(upsert_and_removal_collisions):
            target = seen_removal_ids[collision_eid]
            issues.append(
                _issue(
                    "entity_id_in_upsert_and_removal",
                    f"entity_id {collision_eid} appears both as an upsert (nodes/edges) "
                    f"and as a removal target ({target.section}.{target.kind}s) in the same "
                    "document. Split into separate documents if upsert-then-remove is intended.",
                    "preflight",
                    f"{target.path}.entity_id",
                    entity_id=collision_eid,
                    batch_entity_id=target.batch_entity_id,
                )
            )

    # Decide overall ok: any hard-error issue means preflight failed.
    has_hard_error = any(i.code in _ERROR_CODES for i in issues)
    ok = not has_hard_error

    return _PreflightResult(
        ok=ok,
        batches_to_import=batches_to_import,
        batches_to_skip=batches_to_skip,
        dangling_edge_ids=dangling_edge_ids,
        issues=issues,
        parsed_removals_by_idx=parsed_removals_by_idx,
        resolved_refs=resolution.resolved,
    )


# ---------------------------------------------------------------------------
# Batch execution
# ---------------------------------------------------------------------------


class _BatchFailed(Exception):
    """Raised inside _execute_grift_batch to trigger atomic rollback."""


class _SweepStrictAborted(Exception):
    """Raised inside _execute_grift_batch when --sweep-strict + a guardrail miss."""


class _BatchRowFailed(Exception):
    """Raised inside _execute_grift_batch when the batch row itself could not be written —
    the importer's own write from document strings — so the failure is reported at the
    batch_node path with the operation named (Issue# 630 - tap)."""

    def __init__(self, operation: str, path: str) -> None:
        super().__init__(f"{operation} failed at {path}")
        self.operation = operation
        self.path = path


# ---------------------------------------------------------------------------
# Removal-phase helpers (req-grid-import-grift-removals,
# req-grid-import-grift-removal-preflight)
# ---------------------------------------------------------------------------


@dataclass
class _RemovalPhasePlan:
    """Output of the transaction-scoped removal-target check phase.

    Carries the targets that survived policy application (existence,
    tombstone-state, entity_type sanity) and are ready to feed to the
    write_batch deletes / direct purge calls, plus per-target diagnostic
    issues and skip counts.
    """

    executable_deletes: list[_ParsedRemovalTarget]
    executable_purges: list[_ParsedRemovalTarget]
    removals_skipped: int
    issues: list[GriftIssue]


def _check_and_lock_removal_targets(
    parsed_removals: _ParsedRemovalSections,
    batch_path: str,
    batch_entity_id: str,
) -> _RemovalPhasePlan:
    """Run transaction-scoped checks for one batch's removal targets.

    MUST be called inside an open ``transaction.atomic()`` block. Acquires a
    row-level ``SELECT … FOR UPDATE`` on each target's Entity row, then
    applies the section policies (on_missing for deletes and purges,
    on_tombstoned for deletes) to decide which targets are executable, which
    are skipped, and which raise hard errors. The lock is held until the
    surrounding transaction commits or rolls back, closing the read-then-act
    race that Postgres READ COMMITTED otherwise leaves open.
    """
    executable_deletes: list[_ParsedRemovalTarget] = []
    executable_purges: list[_ParsedRemovalTarget] = []
    removals_skipped = 0
    issues: list[GriftIssue] = []

    all_targets = parsed_removals.all_targets()
    if not all_targets:
        return _RemovalPhasePlan(
            executable_deletes=[],
            executable_purges=[],
            removals_skipped=0,
            issues=[],
        )

    # Acquire row-level locks on every target's Entity row. The lock holds
    # for the rest of the transaction; subsequent reads observe the same
    # state policy decisions are based on. The Entity model's default
    # manager does not auto-filter tombstoned rows (unlike BaseModel
    # subclasses), so Entity.objects already returns the rows we need for
    # both `on_tombstoned` and purge semantics.
    target_uuids = [uuid.UUID(t.entity_id) for t in all_targets]
    locked_rows = {str(row.pk): row for row in Entity.objects.select_for_update().filter(pk__in=target_uuids)}

    def _apply_policy(
        target: _ParsedRemovalTarget,
        on_missing: Literal["error", "warn", "ignore"] | None,
        on_tombstoned: Literal["error", "warn", "ignore"] | None,
        is_purge: bool,
    ) -> Literal["execute", "skip"] | None:
        """Return the outcome for one target, or None if a hard error was emitted."""
        nonlocal removals_skipped

        # Defaults: error on missing, ignore on tombstoned (per spec recommendation).
        policy_on_missing = on_missing or "error"
        policy_on_tombstoned = on_tombstoned or "ignore"

        entity = locked_rows.get(target.entity_id)

        # Missing target.
        if entity is None:
            if policy_on_missing == "error":
                issues.append(
                    _issue(
                        "removal_target_missing",
                        f"Removal target {target.entity_id} not found locally "
                        f"(section={target.section}, on_missing=error).",
                        "execution",
                        target.path,
                        entity_id=target.entity_id,
                        batch_entity_id=batch_entity_id,
                        entity_type=target.entity_type,
                        operation="purge" if is_purge else "delete",
                    )
                )
                return None
            if policy_on_missing == "warn":
                issues.append(
                    _issue(
                        "removal_target_missing_warned",  # warning code
                        f"Removal target {target.entity_id} not found locally; "
                        f"section={target.section} on_missing=warn — skipping.",
                        "execution",
                        target.path,
                        entity_id=target.entity_id,
                        batch_entity_id=batch_entity_id,
                        entity_type=target.entity_type,
                        operation="purge" if is_purge else "delete",
                    )
                )
            removals_skipped += 1
            return "skip"

        # entity_type sanity (vs declared, vs sub-array list).
        if entity.entity_type != target.entity_type:
            issues.append(
                _issue(
                    "removal_entity_type_mismatch",
                    f"Removal target {target.entity_id} has local entity_type="
                    f"{entity.entity_type!r} but the bundle declared {target.entity_type!r}.",
                    "execution",
                    target.path,
                    entity_id=target.entity_id,
                    batch_entity_id=batch_entity_id,
                    entity_type=entity.entity_type,
                    operation="purge" if is_purge else "delete",
                )
            )
            return None
        if target.kind == "edge" and entity.entity_type != "edge":
            issues.append(
                _issue(
                    "removal_entity_type_mismatch",
                    f"Removal target {target.entity_id} is in the 'edges' list but "
                    f"the local entity has entity_type={entity.entity_type!r}.",
                    "execution",
                    target.path,
                    entity_id=target.entity_id,
                    batch_entity_id=batch_entity_id,
                    entity_type=entity.entity_type,
                    operation="purge" if is_purge else "delete",
                )
            )
            return None
        if target.kind == "node" and entity.entity_type == "edge":
            issues.append(
                _issue(
                    "removal_entity_type_mismatch",
                    f"Removal target {target.entity_id} is in the 'nodes' list but "
                    "the local entity has entity_type='edge'.",
                    "execution",
                    target.path,
                    entity_id=target.entity_id,
                    batch_entity_id=batch_entity_id,
                    entity_type=entity.entity_type,
                    operation="purge" if is_purge else "delete",
                )
            )
            return None

        # Tombstone state (deletes only; purges accept tombstoned targets).
        if not is_purge and entity.deleted_at is not None:
            if policy_on_tombstoned == "error":
                issues.append(
                    _issue(
                        "removal_target_tombstoned",
                        f"Delete target {target.entity_id} is already tombstoned "
                        f"(deleted_at set); on_tombstoned=error.",
                        "execution",
                        target.path,
                        entity_id=target.entity_id,
                        batch_entity_id=batch_entity_id,
                        entity_type=target.entity_type,
                        operation="delete",
                    )
                )
                return None
            if policy_on_tombstoned == "warn":
                issues.append(
                    _issue(
                        "removal_target_tombstoned_warned",
                        f"Delete target {target.entity_id} is already tombstoned; " f"on_tombstoned=warn — skipping.",
                        "execution",
                        target.path,
                        entity_id=target.entity_id,
                        batch_entity_id=batch_entity_id,
                        entity_type=target.entity_type,
                        operation="delete",
                    )
                )
            removals_skipped += 1
            return "skip"

        return "execute"

    # Deletes: edges then nodes (within-section order preserved).
    for target in parsed_removals.deletes_edges + parsed_removals.deletes_nodes:
        outcome = _apply_policy(
            target,
            parsed_removals.deletes_on_missing,
            parsed_removals.deletes_on_tombstoned,
            is_purge=False,
        )
        if outcome == "execute":
            executable_deletes.append(target)

    # Purges: edges then nodes.
    for target in parsed_removals.purges_edges + parsed_removals.purges_nodes:
        outcome = _apply_policy(
            target,
            parsed_removals.purges_on_missing,
            None,
            is_purge=True,
        )
        if outcome == "execute":
            executable_purges.append(target)

    return _RemovalPhasePlan(
        executable_deletes=executable_deletes,
        executable_purges=executable_purges,
        removals_skipped=removals_skipped,
        issues=issues,
    )


def _record_removal_reason_event(
    target: _ParsedRemovalTarget,
    batch: Any,
    actor: Any,
) -> None:
    """Emit a BatchEvent capturing the GRIFT-bundle reason for one removal target.

    Co-exists with the standard provenance BatchEvent that the service-layer
    write pipeline records inside ``_execute_write_pipeline``. The standard
    event records "the delete happened"; this event captures "and here is the
    GRIFT-bundle reason for it." Searchable by ``metadata.grift_operation``.

    For tombstone deletes: the typed Entity row still exists (deleted_at set)
    so the event is emitted against the target's entity_id. For purges:
    callers route the summary through a batch-level event instead via
    ``_record_purge_summary_event`` so the trace survives the Entity row
    deletion.
    """
    from tap_grid.models import BatchEvent, BatchEventType

    is_purge = target.section == "purges"
    event_type = BatchEventType.UNLINK if target.kind == "edge" else BatchEventType.DELETE
    BatchEvent.objects.create(
        batch=batch,
        event_type=event_type,
        entity_id=uuid.UUID(target.entity_id),
        entity_type=target.entity_type,
        actor=actor,
        metadata={
            "grift_operation": "purge" if is_purge else "delete",
            "grift_target_path": target.path,
            "grift_target_kind": target.kind,
            "reason": target.reason,
        },
    )


def _record_purge_summary_event(
    target: _ParsedRemovalTarget,
    batch: Any,
    actor: Any,
    outcome: Literal["applied", "missing", "warned", "ignored"],
) -> None:
    """Emit a batch-level summary BatchEvent for one purge target.

    Recorded against the BATCH Entity (not the purged entity) so it survives
    the purge. The purged target's identity travels in metadata. See
    req-grid-import-grift-removals Provenance And Reason Capture.
    """
    from tap_grid.models import BatchEvent, BatchEventType

    BatchEvent.objects.create(
        batch=batch,
        event_type=BatchEventType.UNLINK if target.kind == "edge" else BatchEventType.DELETE,
        entity_id=batch.entity.id,
        entity_type="batch",
        actor=actor,
        metadata={
            "grift_operation": "purge",
            "target_entity_id": target.entity_id,
            "target_entity_type": target.entity_type,
            "target_kind": target.kind,
            "grift_target_path": target.path,
            "reason": target.reason,
            "outcome": outcome,
        },
    )


def _execute_grift_batch(
    batch_container: dict[str, Any],
    *,
    batch_idx: int,
    dangling_edge_ids: set[str],
    actor: Any,
    reference_time: datetime,
    dangling_edge_mode: str,
    force_batches: set[str] | None = None,
    sweep_strict: bool = False,
    purge: bool = False,
    parsed_removals: _ParsedRemovalSections | None = None,
    refs: dict[str, str] | None = None,
    read_boundary: datetime | None = None,
) -> tuple[GriftImportedBatch, list[GriftIssue]]:
    """Import one GRIFT batch atomically. Returns (batch_summary, issues).

    ``read_boundary`` is when the run that submitted the document opened, derived by
    ``grift_import`` from the caller's bound batch and never from the document; ``None`` when no
    run submitted it, and then an authority claim proposes nothing.

    ``refs`` is the batch's ``ref → provisional id`` map from preflight; inside the
    transaction each ref node is resolved through ``resolve_identity`` and a found row's
    id replaces the provisional one everywhere the batch names it (gate slice 2).

    TAP-IMPLEMENTS: req-grid-import-grift-batch@320946903a46/9166bb22373c (derivation) — each
        batch executes as its own import unit here.
    """
    from tap_grid.models import Batch

    batch_path = f"$.batches[{batch_idx}]"
    issues: list[GriftIssue] = []
    # This batch's own copy: key endpoints that do not resolve join it at execution.
    dangling_edge_ids = set(dangling_edge_ids)
    unresolved_keys: dict[str, list[dict[str, Any]]] = {}
    skips: list[dict[str, Any]] = []
    nodes_imported = 0
    edges_imported = 0
    edges_skipped = 0
    edges_deleted = 0
    nodes_deleted = 0
    edges_purged = 0
    nodes_purged = 0
    removals_skipped = 0
    edges_retired = 0
    nodes_retired = 0
    retirements_skipped = 0
    swept_entities: list[GriftSweptEntity] = []
    sweep_skipped: list[GriftSweepSkipped] = []
    sweep_strict_aborted = False
    upserted_entities: list[GriftUpsertedEntity] = []
    authority: list[dict[str, Any]] = []
    edges_proposed = 0
    committed = False

    batch_entity = batch_container["batch_entity"]
    batch_node = batch_container["batch_node"]
    batch_entity_id = batch_entity["entity_id"]
    force_batches = force_batches or set()
    is_force_reimport = (
        batch_entity_id in force_batches and Batch.all_objects.filter(entity_id=batch_entity_id).exists()
    )

    # Build importer provenance for description_json.
    importer_data: dict[str, Any] = {
        "importer": "grift",
        "grift_version": GRIFT_VERSION,
        "import_mode": IMPORT_MODE,
        "dangling_edge_mode": dangling_edge_mode,
        "imported_at": reference_time.isoformat(),
        "source_batch_entity_id": batch_entity_id,
    }
    for src_key, dest_key in (
        ("created_at", "source_created_at"),
        ("updated_at", "source_updated_at"),
    ):
        if batch_entity.get(src_key):
            importer_data[dest_key] = batch_entity[src_key]
    for src_key, dest_key in (
        ("started_at", "source_started_at"),
        ("closed_at", "source_closed_at"),
    ):
        if batch_node.get(src_key):
            importer_data[dest_key] = batch_node[src_key]

    # Merge importer metadata into description_json per spec-grid-import-grift
    # req-grid-import-grift-provenance. Four cases:
    #   1. incoming missing/empty/malformed -> emit importer format alone
    #   2. incoming already tap.grift.import.v0 -> overwrite (avoid nested duplicates)
    #   3. incoming has a custom format with dict data -> preserve caller format and
    #      nest importer metadata under reserved key `_tap_grift_import` to avoid
    #      key collisions with caller-owned data
    #   4. incoming has a format but data shape is wrong -> fall back to case 1
    incoming_desc = batch_node.get("description_json") or {}
    merged_desc_json: dict[str, Any]
    if not isinstance(incoming_desc, dict) or not incoming_desc:
        merged_desc_json = {"format": "tap.grift.import.v0", "data": importer_data}
    elif incoming_desc.get("format") == "tap.grift.import.v0":
        merged_desc_json = {"format": "tap.grift.import.v0", "data": importer_data}
    elif isinstance(incoming_desc.get("format"), str) and isinstance(incoming_desc.get("data"), dict):
        merged_data = {**incoming_desc["data"], "_tap_grift_import": importer_data}
        merged_desc_json = {"format": incoming_desc["format"], "data": merged_data}
    else:
        merged_desc_json = {"format": "tap.grift.import.v0", "data": importer_data}

    final_refs: dict[str, str] = dict(refs or {})
    try:
        with transaction.atomic():
            batch_row_op = "refresh_batch" if is_force_reimport else "create_batch"
            # The batch row is the one write the importer makes from document strings itself
            # (batch_node.name, .description, .metadata); a value the database cannot store —
            # a NUL, an unpaired surrogate — surfaces named by its path, not by the driver
            # alone (Issue# 630 - tap). write_batch attributes its own ops per op.
            try:
                if is_force_reimport:
                    # req-grid-import-grift-force-reimport: re-apply the existing
                    # batch's content in place. The Batch row and its Entity already
                    # exist; don't call create_batch (which would collide). We may
                    # refresh batch metadata (name, description) to reflect the
                    # revised content, but the identity stays fixed.
                    batch = Batch.all_objects.get(entity_id=batch_entity_id)
                    new_name = batch_node.get("name") or batch_entity.get("name") or batch.name
                    new_description = batch_node.get("description") or batch.description
                    if new_name != batch.name or new_description != batch.description:
                        batch.name = new_name
                        batch.description = new_description
                        batch.save(update_fields=["name", "description"])
                    # If the batch was previously closed, reopen-then-reclose on
                    # success. Status is managed by close_batch at the bottom.
                    from tap_grid.models import BatchStatus

                    if batch.status != BatchStatus.OPEN:
                        batch.status = BatchStatus.OPEN
                        batch.closed_at = None
                        batch.save(update_fields=["status", "closed_at"])
                else:
                    # Normal path: create the batch with the preserved entity_id.
                    batch = create_batch(
                        entity_id=batch_entity_id,
                        name=batch_node.get("name") or batch_entity.get("name") or "",
                        source=batch_node.get("source") or "",
                        description=batch_node.get("description") or "",
                        description_json=merged_desc_json,
                        metadata=batch_node.get("metadata") or {},
                        actor=actor,
                    )

            except Exception as exc:
                raise _BatchRowFailed(batch_row_op, f"{batch_path}.batch_node") from exc

            ctx = CallerContext(user=actor, batch_id=batch_entity_id)

            # Ref nodes resolve to their existing rows here, under the batch's own
            # transaction and the verb's lock, so resolution and creation commit
            # together (req-grid-entity-natural-key-13). A found row's id replaces the
            # provisional one the preflight minted, everywhere this batch names it.
            if final_refs:
                substitutions = _resolve_ref_identities(
                    batch_container,
                    final_refs,
                    batch_path=batch_path,
                    batch_entity_id=batch_entity_id,
                    ctx=ctx,
                    issues=issues,
                    parsed_removals=parsed_removals,
                )
                if substitutions:
                    substitute_ids(batch_container, substitutions)
                    final_refs = {ref: substitutions.get(pid, pid) for ref, pid in final_refs.items()}

            # Endpoints named by type and natural key resolve against this batch's nodes, then the
            # live grid (req-grid-import-grift-edge-endpoints), after node refs and before edge
            # identity, so every endpoint is final when edges are looked up.
            unresolved_keys = _resolve_endpoint_keys(
                batch_container,
                batch_path=batch_path,
                batch_entity_id=batch_entity_id,
                ctx=ctx,
                issues=issues,
                dangling_edge_ids=dangling_edge_ids,
                dangling_edge_mode=dangling_edge_mode,
            )

            # Edges are found by their type's declared identity, after the nodes, so every
            # endpoint is final (req-grid-edge-identity). A found edge's id replaces the
            # provisional one, and the op builder below then routes it to replace_edge,
            # the same write path a found node takes (req-grid-edge-identity-10).
            edge_substitutions = _resolve_edge_identities(
                batch_container,
                final_refs,
                batch_path=batch_path,
                batch_entity_id=batch_entity_id,
                ctx=ctx,
                issues=issues,
                parsed_removals=parsed_removals,
                dangling_edge_ids=dangling_edge_ids,
            )
            if edge_substitutions:
                substitute_ids(batch_container, edge_substitutions)
                final_refs = {ref: edge_substitutions.get(pid, pid) for ref, pid in final_refs.items()}

            # Build operations: determine create vs replace per entity before executing.
            ops: list[WriteOperation] = []
            op_meta: list[dict[str, Any]] = []  # parallel metadata for error reporting
            # Spine-sync intents for existing-entity replaces: the service-layer
            # replace verb leaves Entity spine fields untouched (per its docstring),
            # but on re-import the bundle's envelope is authoritative for spine
            # values. We capture the bundle's envelope-side `name` and `dimensions`
            # for every replace_node target and apply them in a post-pass after
            # the batch succeeds. See req-grid-import-grift-batch (Spine Sync).
            replace_spine_intents: list[dict[str, Any]] = []
            # Objects carrying a `retirement` block, retired after every upsert
            # (req-grid-import-grift-retired-1): (path, entity_id, entity_type, block).
            retire_nodes: list[tuple[str, str, str, dict[str, Any]]] = []
            retire_edges: list[tuple[str, str, str, dict[str, Any]]] = []

            def _tombstone_stands(path: str, entity_id: str, entity_type: str) -> bool:
                """An existing tombstone is left as it is (req-grid-import-grift-retired-3)."""
                nonlocal retirements_skipped
                if not Entity.objects.filter(pk=uuid.UUID(entity_id), deleted_at__isnull=False).exists():
                    return False
                retirements_skipped += 1
                issues.append(
                    _issue(
                        "retired_target_already_tombstoned",
                        f"Retired object {entity_id} is already tombstoned here; left as it is.",
                        "execution",
                        path,
                        entity_id=entity_id,
                        batch_entity_id=batch_entity_id,
                        entity_type=entity_type,
                        operation="skip",
                    )
                )
                return True

            for node_idx, node_obj in enumerate(batch_container.get("nodes", [])):
                node_entity_id = node_obj["entity"]["entity_id"]
                entity_type = node_obj["entity"]["entity_type"]
                envelope_name = node_obj["entity"].get("name")
                envelope_dims = node_obj["entity"].get("dimensions") or {}
                envelope_expected_version = node_obj["entity"].get("entity_expected_version")
                payload = node_obj["node"]
                node_path = f"{batch_path}.nodes[{node_idx}]"

                if "retirement" in node_obj:
                    if _tombstone_stands(node_path, node_entity_id, entity_type):
                        continue
                    retire_nodes.append((node_path, node_entity_id, entity_type, node_obj["retirement"]))

                entity_exists = Entity.objects.filter(pk=uuid.UUID(node_entity_id)).exists()

                # req-grift-concurrency-version-7 (Declared Expectation Beats
                # Missing Entity): an envelope that declares
                # entity_expected_version and points at an entity_id with no
                # matching local entity is a `entity_version_conflict` with
                # actual_entity_version=null, regardless of whether the
                # bundle would otherwise route to create or replace. Surface
                # this as a hard execution error and roll the batch back.
                if envelope_expected_version is not None and not entity_exists:
                    issues.append(
                        _issue(
                            "entity_version_conflict",
                            f"Envelope at {node_path}.entity declared "
                            f"entity_expected_version={envelope_expected_version} but no "
                            f"local entity exists with entity_id={node_entity_id}.",
                            "execution",
                            f"{node_path}.entity.entity_expected_version",
                            entity_id=node_entity_id,
                            batch_entity_id=batch_entity_id,
                            entity_type=entity_type,
                            operation="replace_node",
                            entity_expected_version=envelope_expected_version,
                            actual_entity_version=None,
                        )
                    )
                    raise _BatchFailed()

                if entity_exists:
                    ops.append(
                        WriteOperation(
                            verb="replace_node",
                            target=node_entity_id,
                            payload=payload,
                            entity_expected_version=envelope_expected_version,
                        )
                    )
                    replace_spine_intents.append(
                        {
                            "entity_id": node_entity_id,
                            "envelope_name": envelope_name,
                            "envelope_dims": envelope_dims,
                        }
                    )
                    upserted_entities.append(
                        GriftUpsertedEntity(
                            entity_id=node_entity_id,
                            entity_type=entity_type,
                            name=envelope_name,
                            kind="node",
                        )
                    )
                else:
                    ops.append(
                        WriteOperation(
                            verb="create_node",
                            type_slug=entity_type,
                            payload=payload,
                            entity_id=node_entity_id,
                            dimensions=envelope_dims,
                        )
                    )
                op_meta.append(
                    {"path": node_path, "entity_id": node_entity_id, "entity_type": entity_type, "kind": "node"}
                )

            for edge_idx, edge_obj in enumerate(batch_container.get("edges", [])):
                edge_entity_id = edge_obj["entity"]["entity_id"]
                edge = edge_obj["edge"]
                envelope_dims = edge_obj["entity"].get("dimensions") or {}
                envelope_expected_version = edge_obj["entity"].get("entity_expected_version")
                edge_path = f"{batch_path}.edges[{edge_idx}]"

                if edge_entity_id in dangling_edge_ids:
                    edges_skipped += 1
                    issues.append(
                        _issue(
                            "dangling_edge",
                            f"Skipping dangling edge {edge_entity_id} (permissive mode)",
                            "execution",
                            edge_path,
                            entity_id=edge_entity_id,
                            batch_entity_id=batch_entity_id,
                            entity_type="edge",
                            operation="skip",
                            from_entity_id=edge.get("from_entity_id"),
                            to_entity_id=edge.get("to_entity_id"),
                            edge_entity_id=edge_entity_id,
                        )
                    )
                    skips.append(
                        _record_edge_skip(
                            batch_entity_id,
                            edge_entity_id,
                            edge,
                            unresolved_keys.get(edge_entity_id, []),
                            {n["entity"]["entity_id"] for n in batch_container.get("nodes", [])},
                        )
                    )
                    continue

                if "retirement" in edge_obj:
                    if _tombstone_stands(edge_path, edge_entity_id, "edge"):
                        continue
                    retire_edges.append((edge_path, edge_entity_id, "edge", edge_obj["retirement"]))

                properties = edge.get("properties") or {}
                edge_exists = Entity.objects.filter(pk=uuid.UUID(edge_entity_id)).exists()

                # req-grift-concurrency-version-7 — same declared-on-missing
                # rule as for node envelopes.
                if envelope_expected_version is not None and not edge_exists:
                    issues.append(
                        _issue(
                            "entity_version_conflict",
                            f"Envelope at {edge_path}.entity declared "
                            f"entity_expected_version={envelope_expected_version} but no "
                            f"local entity exists with entity_id={edge_entity_id}.",
                            "execution",
                            f"{edge_path}.entity.entity_expected_version",
                            entity_id=edge_entity_id,
                            batch_entity_id=batch_entity_id,
                            entity_type="edge",
                            operation="replace_edge",
                            entity_expected_version=envelope_expected_version,
                            actual_entity_version=None,
                            edge_entity_id=edge_entity_id,
                        )
                    )
                    raise _BatchFailed()

                if edge_exists:
                    ops.append(
                        WriteOperation(
                            verb="replace_edge",
                            target=edge_entity_id,
                            payload={"properties": properties},
                            entity_expected_version=envelope_expected_version,
                        )
                    )
                    upserted_entities.append(
                        GriftUpsertedEntity(
                            entity_id=edge_entity_id,
                            entity_type="edge",
                            name=edge_obj["entity"].get("name"),
                            kind="edge",
                        )
                    )
                else:
                    ops.append(
                        WriteOperation(
                            verb="create_edge",
                            from_target=edge["from_entity_id"],
                            to_target=edge["to_entity_id"],
                            edge_type=edge["edge_type"],
                            payload={"properties": properties},
                            entity_id=edge_entity_id,
                            dimensions=envelope_dims,
                        )
                    )
                op_meta.append({"path": edge_path, "entity_id": edge_entity_id, "entity_type": "edge", "kind": "edge"})

            # --- Retirement phase (req-grid-import-grift-retired). Each retired object
            # was written above; it is retired here, in the same write_batch call, edges
            # first so each records its own retirement instead of being ended silently by
            # its endpoint's. The retirement is the import's act; the source grid's block
            # rides on its event as data, never as this grid's provenance (-2). ---
            if retire_nodes or retire_edges:
                from tap_auth import policy
                from tap_auth.capabilities import DELETE_CAPABILITY

                policy.authorize(ctx, DELETE_CAPABILITY, operation="grift_import_retire")
                for path, entity_id, entity_type, block in retire_edges + retire_nodes:
                    is_edge = entity_type == "edge"
                    ops.append(
                        WriteOperation(
                            verb="delete_edge" if is_edge else "delete_node",
                            target=entity_id,
                            reason="grift_import",
                            metadata={"grift_operation": "retire", "original_retirement": block},
                            cascade="none",
                        )
                    )
                    op_meta.append(
                        {
                            "path": f"{path}.retirement",
                            "entity_id": entity_id,
                            "entity_type": entity_type,
                            "kind": "retire_edge" if is_edge else "retire_node",
                        }
                    )

            # --- Imperative removal phase (req-grid-import-grift-removals,
            # req-grid-import-grift-removal-preflight). Transaction-scoped
            # target checks with row-level locks decide which deletes survive
            # policy (on_missing / on_tombstoned) and which purges are
            # executable. Deletes are appended to the write_batch call so the
            # pre-commit consistency phase (hotlinks etc.) sees the post-delete
            # graph. Purges run after write_batch returns, still inside the
            # batch transaction. ---
            removal_plan: _RemovalPhasePlan | None = None
            if parsed_removals is not None and parsed_removals.has_any_targets():
                # A delete that names its edge by identity becomes an id target here, once it has
                # matched the live edge it ends (req-grid-import-grift-edge-removal).
                by_identity, identity_skips = _resolve_removal_identities(
                    parsed_removals, batch_container, batch_entity_id=batch_entity_id, ctx=ctx, issues=issues
                )
                parsed_removals = replace(
                    parsed_removals,
                    deletes_edges=parsed_removals.deletes_edges + by_identity,
                    deletes_edge_identities=[],
                )
                removal_plan = _check_and_lock_removal_targets(parsed_removals, batch_path, batch_entity_id)
                issues.extend(removal_plan.issues)
                removals_skipped = removal_plan.removals_skipped + identity_skips
                if any(i.code in _ERROR_CODES for i in removal_plan.issues):
                    raise _BatchFailed()

                # A removal batch tombstones nodes/edges. Because deletes are
                # appended as WriteOperations to write_batch (bypassing the
                # delete_node/delete_edge verbs' own grid.delete decorators),
                # authorize grid.delete explicitly here, in the import's scope, so
                # an actor whose bundle excludes it (tap_bootloader, tap_cares.collector)
                # gets a clean CapabilityDenied rather than tripping the write_batch
                # delete backstop as an UnguardedOperation. "Boot cannot tombstone"
                # is thereby literally true (doc-auth-per-app-standards "split cover
                # semantics", open decision #3).
                if removal_plan.executable_deletes:
                    from tap_auth import policy
                    from tap_auth.capabilities import DELETE_CAPABILITY

                    policy.authorize(ctx, DELETE_CAPABILITY, operation="grift_import_delete")

                # Append delete WriteOperations to the same write_batch call.
                # Per-target entity_expected_version (req-grift-concurrency-version)
                # flows through to the pipeline OCC guard.
                for target in removal_plan.executable_deletes:
                    if target.kind == "edge":
                        ops.append(
                            WriteOperation(
                                verb="delete_edge",
                                target=target.entity_id,
                                entity_expected_version=target.entity_expected_version,
                            )
                        )
                    else:
                        ops.append(
                            WriteOperation(
                                verb="delete_node",
                                target=target.entity_id,
                                entity_expected_version=target.entity_expected_version,
                            )
                        )
                    op_meta.append(
                        {
                            "path": target.path,
                            "entity_id": target.entity_id,
                            "entity_type": target.entity_type,
                            "kind": "removal_delete_edge" if target.kind == "edge" else "removal_delete_node",
                            "removal_target": target,
                        }
                    )

            # Execute all node + edge + delete ops in one write_batch call (atomic).
            # Gated by grift_import's authorized('grid.import_grift') one+ frames up,
            # which the per-function authz-coverage scanner cannot see across the call.
            if ops:
                batch_result = write_batch(ops, caller_context=ctx)  # TAP-AUTHZ-COV: gated by grift_import
                any_failure = False
                # write_batch returns `results` truncated at the first failing op
                # (services.py raises _BailOut on per-op failure), so results may
                # be shorter than op_meta. zip(strict=False) deliberately stops at
                # the shorter iterator, which is the right behavior: the user has
                # already seen the failing op's per-op errors and trailing ops
                # never executed. strict=True here surfaced as a confusing
                # `zip() argument 2 is longer than argument 1` traceback on top
                # of the real per-op error.
                for op_result, meta in zip(batch_result.results, op_meta, strict=False):
                    if op_result.success:
                        if meta["kind"] == "node":
                            nodes_imported += 1
                        elif meta["kind"] == "edge":
                            edges_imported += 1
                        elif meta["kind"] == "retire_edge":
                            edges_retired += 1
                        elif meta["kind"] == "retire_node":
                            nodes_retired += 1
                        elif meta["kind"] == "removal_delete_edge":
                            edges_deleted += 1
                            _record_removal_reason_event(meta["removal_target"], batch, actor)
                        elif meta["kind"] == "removal_delete_node":
                            nodes_deleted += 1
                            _record_removal_reason_event(meta["removal_target"], batch, actor)
                    else:
                        any_failure = True
                        # Collect every per-op error as its own issue. Don't
                        # short-circuit on the first failed op — the batch's
                        # pre-commit consistency phase (req-grid-service-batch-
                        # precommit-consistency) can attribute hotlink failures
                        # to multiple ops, and the GRIFT report should surface
                        # all of them in one pass so the bundle author sees the
                        # complete fix list rather than discovering them one
                        # rerun at a time.
                        for err in op_result.errors:
                            # OCC conflicts surface with their own code +
                            # detail payload so callers can implement
                            # retry-or-surface logic (req-grid-import-grift-occ-3).
                            if err.code == "entity_version_conflict":
                                detail = err.detail or {}
                                issues.append(
                                    _issue(
                                        "entity_version_conflict",
                                        err.message,
                                        "execution",
                                        meta["path"],
                                        entity_id=meta["entity_id"],
                                        batch_entity_id=batch_entity_id,
                                        entity_type=meta["entity_type"],
                                        operation=op_result.operation,
                                        entity_expected_version=detail.get("entity_expected_version"),
                                        actual_entity_version=detail.get("actual_entity_version"),
                                    )
                                )
                                continue
                            issues.append(
                                _issue(
                                    "execution_failed",
                                    f"{err.code} while executing {op_result.operation} at {meta['path']}: {err.message}",
                                    "execution",
                                    meta["path"],
                                    entity_id=meta["entity_id"],
                                    batch_entity_id=batch_entity_id,
                                    entity_type=meta["entity_type"],
                                    operation=op_result.operation,
                                )
                            )
                # A batch-level failure — the write's own transaction rolled back on an
                # exception or a deadlock — arrives as BatchWriteResult.errors with every
                # per-op result that preceded it still marked success (Codex, Issue# 605 -
                # tap). Nothing those results describe persisted, so the batch fails here
                # before spine sync and close could commit on top of the rollback.
                for batch_error in batch_result.errors:
                    any_failure = True
                    issues.append(
                        _issue(
                            "execution_failed",
                            f"{batch_error.code}: {batch_error.message}",
                            "execution",
                            batch_path,
                            batch_entity_id=batch_entity_id,
                            operation="write_batch",
                        )
                    )
                if not batch_result.success and not any_failure:
                    any_failure = True
                    issues.append(
                        _issue(
                            "execution_failed",
                            "write_batch reported failure without a per-op or batch-level error",
                            "execution",
                            batch_path,
                            batch_entity_id=batch_entity_id,
                            operation="write_batch",
                        )
                    )
                if any_failure:
                    raise _BatchFailed()

                # req-grid-import-grift-batch (Spine Sync): for every successful
                # replace_node, propagate the bundle's envelope-side spine fields
                # (name, dimensions) to the Entity row when they differ. The
                # service-layer replace verb intentionally leaves spine fields
                # alone, but the GRIFT envelope is the bundle's declared truth on
                # every import — so on re-import a renamed or re-dimensioned
                # entity's spine must move with it. Direct Entity.objects.update
                # is used (not save()) to avoid bumping version on a pure spine
                # sync and to keep this post-pass cheap.
                if replace_spine_intents:
                    _sync_spine_for_replaced_nodes(replace_spine_intents)

            # --- Purge phase (req-grid-import-grift-removals). Purges run
            # OUTSIDE write_batch because the service-layer purge verbs are not
            # write_batch-routable in v0; they execute inside the same per-batch
            # transaction.atomic() so any failure rolls back the entire batch
            # (upserts, deletes, partial purges). Each purge emits a
            # batch-level summary BatchEvent so the trace survives the purged
            # Entity row.
            #
            # Known limitation (slice 1): purges do not feed the hotlink
            # pre-commit consistency phase. If a purge removes an edge that a
            # surviving node's HOTLINKS references and that node was not
            # written in this batch, no validation runs. Acceptable for v0;
            # generalized consistency-phase-as-hook is a future seam.
            if removal_plan is not None and removal_plan.executable_purges:
                from tap_grid.exceptions import (
                    ServiceConflictError,
                    ServiceNotFoundError,
                    ServiceValidationError,
                )
                from tap_grid.exceptions import ServiceVersionConflictError as _SVCE
                from tap_grid.services import purge_edge, purge_node

                # Purge edges first, then nodes (matches the documented order).
                edge_purges = [t for t in removal_plan.executable_purges if t.kind == "edge"]
                node_purges = [t for t in removal_plan.executable_purges if t.kind == "node"]
                for target in edge_purges + node_purges:
                    try:
                        if target.kind == "edge":
                            purge_edge(
                                target.entity_id,
                                caller_context=ctx,
                                entity_expected_version=target.entity_expected_version,
                                reason=target.reason,
                            )
                            edges_purged += 1
                        else:
                            purge_node(
                                target.entity_id,
                                caller_context=ctx,
                                entity_expected_version=target.entity_expected_version,
                                reason=target.reason,
                            )
                            nodes_purged += 1
                        _record_purge_summary_event(target, batch, actor, outcome="applied")
                    except _SVCE as exc:
                        # OCC mismatch / declared-on-missing — surface with the
                        # detail payload so callers can implement retry-or-surface
                        # logic (req-grid-import-grift-occ-3).
                        issues.append(
                            _issue(
                                "entity_version_conflict",
                                f"Purge of {target.kind} {target.entity_id} failed OCC: "
                                f"expected={exc.entity_expected_version}, "
                                f"actual={exc.actual_entity_version}",
                                "execution",
                                target.path,
                                entity_id=target.entity_id,
                                batch_entity_id=batch_entity_id,
                                entity_type=target.entity_type,
                                operation="purge",
                                entity_expected_version=exc.entity_expected_version,
                                actual_entity_version=exc.actual_entity_version,
                            )
                        )
                        raise _BatchFailed() from exc
                    except (ServiceConflictError, ServiceNotFoundError, ServiceValidationError) as exc:
                        issues.append(
                            _issue(
                                "removal_execution_failed",
                                f"Purge of {target.kind} {target.entity_id} failed: " f"{type(exc).__name__}: {exc}",
                                "execution",
                                target.path,
                                entity_id=target.entity_id,
                                batch_entity_id=batch_entity_id,
                                entity_type=target.entity_type,
                                operation="purge",
                            )
                        )
                        raise _BatchFailed() from exc

            # req-grid-import-grift-batch-scoped-sweep: on force re-import,
            # detect entities the previous ingestion of this batch created
            # that are absent in the revised content, and tombstone (or purge)
            # them via the service-layer delete path. Runs inside the
            # transaction so a strict-mode abort rolls everything back.
            if is_force_reimport:
                swept_entities, sweep_skipped = _run_batch_scoped_sweep(
                    batch_entity_id=batch_entity_id,
                    batch_container=batch_container,
                    caller_ctx=ctx,
                    sweep_strict=sweep_strict,
                    purge=purge,
                    skipped_edge_ids=frozenset(dangling_edge_ids),
                )
                # Emit the FORCE_REIMPORT batch event.
                _emit_force_reimport_event(
                    batch=batch,
                    nodes_imported=nodes_imported,
                    edges_imported=edges_imported,
                    edges_skipped=edges_skipped,
                    swept_entities=swept_entities,
                    sweep_skipped=sweep_skipped,
                    purge=purge,
                    sweep_strict=sweep_strict,
                    actor=actor,
                )

            # Authority claims are judged last, against the grid as this batch leaves it
            # (req-grid-reconcile-edge-authority): a dry-run that records and removes nothing.
            claims = (batch_container.get("edge_cases") or {}).get("authority") or []
            if claims:
                authority = _apply_authority_claims(
                    claims,
                    batch_container,
                    batch=batch,
                    batch_path=batch_path,
                    batch_entity_id=batch_entity_id,
                    ctx=ctx,
                    actor=actor,
                    read_boundary=read_boundary,
                    dangling_edge_ids=dangling_edge_ids,
                    skips=skips,
                    issues=issues,
                )
                edges_proposed = sum(claim["proposed"] for claim in authority)

            close_batch(batch)
            committed = True

    except _BatchFailed:
        # Atomic block already rolled back; clear upsert tracking since none
        # of those replaces actually persisted. Its skip events rolled back too.
        upserted_entities = []
        skips = []
    except _SweepStrictAborted as exc:
        # Strict mode: surface an error and keep the skipped list for the report.
        sweep_strict_aborted = True
        # exc.args[0] carries the list of skipped candidates assembled by
        # _run_batch_scoped_sweep before it raised.
        if exc.args and isinstance(exc.args[0], list):
            sweep_skipped = exc.args[0]
        # Any writes made in this atomic block rolled back with the exception.
        nodes_imported = 0
        edges_imported = 0
        edges_skipped = 0
        swept_entities = []
        upserted_entities = []
        skips = []
        issues.append(
            _issue(
                "sweep_strict_aborted",
                f"Strict sweep aborted: {len(sweep_skipped)} candidate(s) failed guardrails.",
                "execution",
                batch_path,
                batch_entity_id=batch_entity_id,
            )
        )
    except _BatchRowFailed as exc:
        issues.append(
            _issue(
                "execution_failed",
                f"{exc.operation} failed at {exc.path}: {exc.__cause__}",
                "execution",
                exc.path,
                batch_entity_id=batch_entity_id,
                operation=exc.operation,
            )
        )
    except Exception as exc:
        issues.append(_issue("execution_failed", str(exc), "execution", batch_path, batch_entity_id=batch_entity_id))

    if not committed:
        # The batch's transaction rolled back, and its authority events with it.
        authority = []
        edges_proposed = 0

    errors_count = sum(
        1
        for i in issues
        if i.code in ("execution_failed", "sweep_strict_aborted", "removal_execution_failed") or i.code in _ERROR_CODES
    )
    warnings_count = sum(
        1
        for i in issues
        if i.code
        in (
            "dangling_edge",
            "removal_target_missing_warned",
            "removal_target_tombstoned_warned",
            "retired_target_already_tombstoned",
        )
    )

    # On rollback the removal counters are stale (the work didn't persist).
    # `_BatchFailed` clears upserted_entities above for the same reason;
    # mirror that for removal stats so they don't lie about partial success.
    if any(i.code in _ERROR_CODES for i in issues) or sweep_strict_aborted:
        edges_deleted = 0
        nodes_deleted = 0
        edges_purged = 0
        nodes_purged = 0
        edges_retired = 0
        nodes_retired = 0

    return (
        GriftImportedBatch(
            batch_entity_id=batch_entity_id,
            path=batch_path,
            nodes_imported=nodes_imported,
            edges_imported=edges_imported,
            edges_skipped=edges_skipped,
            errors_count=errors_count,
            warnings_count=warnings_count,
            force_reimported=is_force_reimport,
            swept_entities=swept_entities,
            sweep_skipped=sweep_skipped,
            sweep_strict_aborted=sweep_strict_aborted,
            upserted_entities=upserted_entities,
            edges_deleted=edges_deleted,
            nodes_deleted=nodes_deleted,
            edges_purged=edges_purged,
            nodes_purged=nodes_purged,
            removals_skipped=removals_skipped,
            edges_retired=edges_retired,
            nodes_retired=nodes_retired,
            retirements_skipped=retirements_skipped,
            resolved_refs=final_refs,
            skips=skips,
            authority=authority,
            edges_proposed=edges_proposed,
        ),
        issues,
    )


def _explicit_identity_key(node_obj: dict[str, Any]) -> str | None:
    """The identity key of an explicitly addressed node, or None when its type has none."""
    from tap_grid.registry import get_model_class

    try:
        model_cls = cast(type[BaseModel], get_model_class(node_obj["entity"]["entity_type"]))
    except KeyError:
        return None
    declared = model_cls.NATURAL_KEY
    if declared is None or isinstance(declared, Keyless):
        return None
    return identity_lock_key(model_cls.ENTITY_TYPE, constituting_properties(declared, node_obj["node"]))


def _resolve_ref_identities(
    batch_container: dict[str, Any],
    refs: dict[str, str],
    *,
    batch_path: str,
    batch_entity_id: str,
    ctx: CallerContext,
    issues: list[GriftIssue],
    parsed_removals: _ParsedRemovalSections | None = None,
) -> dict[str, str]:
    """Resolve every ref node of one batch; return ``provisional id → found id`` for the rows that exist.

    Fails the batch (``_BatchFailed``) on the first ref whose type has no declared search,
    or whose search matched more than one live row — the latter is also reported as one
    application-class Flaw per failed batch: the declaration is too thin to tell two
    source objects apart, and that is the plugin author's contract to fix. Two refs of one
    batch that describe one source object — the same identity key, whether a row exists
    yet or not — fail it too (Issue# 602 - tap): resolution runs before the batch writes,
    so the search alone cannot see the first of the pair. A found row that this batch also
    addresses by explicit id, or names as a removal target, is refused the same way (Issue#
    606 - tap): preflight's duplicate and upsert-versus-removal checks saw the provisional id,
    so they are re-applied here against the id the ref actually resolved to. Refs are
    batch-local, so a row another batch of the file wrote explicitly is simply an existing
    row to this one — sequential batches, not a collision.
    """
    from tap.flaws import HANDLING_ABORT_OPERATION, AppFlaw

    ref_of = {pid: ref for ref, pid in refs.items()}
    substitutions: dict[str, str] = {}
    taken: set[str] = set()
    keys_seen: dict[str, tuple[str, str | None]] = {}  # identity key -> (who, its entity_id if explicit)
    explicit_ids = {
        item["entity"]["entity_id"]
        for section in ("nodes", "edges")
        for item in batch_container.get(section, [])
        if item["entity"]["entity_id"] not in ref_of
    }
    removal_targets = {t.entity_id: t for t in parsed_removals.all_targets()} if parsed_removals else {}
    # An explicitly addressed node keeps today's behaviour (no search, no lock), but its
    # declared values still name a source object: a ref in the same batch that describes
    # that object must not create it a second time (Grok on PR# 604 - tap). Its key is the
    # same derivation the verb uses, read once from the declaration; undeclared and
    # keyless types have no key and take no part.
    for node_obj in batch_container.get("nodes", []):
        if node_obj["entity"]["entity_id"] in ref_of:
            continue
        explicit_key = _explicit_identity_key(node_obj)
        if explicit_key is not None:
            explicit_id = node_obj["entity"]["entity_id"]
            keys_seen.setdefault(explicit_key, (f"entity_id {explicit_id}", explicit_id))
    for node_idx, node_obj in enumerate(batch_container.get("nodes", [])):
        provisional = node_obj["entity"]["entity_id"]
        if provisional not in ref_of:
            continue
        ref = ref_of[provisional]
        entity_type = node_obj["entity"]["entity_type"]
        path = f"{batch_path}.nodes[{node_idx}].entity.ref"
        try:
            resolution = resolve_identity(  # TAP-AUTHZ-COV: gated by grift_import
                entity_type, node_obj["node"], caller_context=ctx, provisional=provisional
            )
        except ServiceValidationError as exc:
            issues.append(
                _issue(
                    "identity_undeclared",
                    f"ref {ref!r}: {exc}",
                    "execution",
                    path,
                    batch_entity_id=batch_entity_id,
                    entity_type=entity_type,
                )
            )
            raise _BatchFailed() from exc
        except AmbiguousIdentity as exc:
            candidates = [str(c) for c in exc.candidates]
            issues.append(
                _issue(
                    "identity_ambiguous",
                    f"ref {ref!r}: {exc}",
                    "execution",
                    path,
                    batch_entity_id=batch_entity_id,
                    entity_type=entity_type,
                )
            )
            AppFlaw.report(
                invariant_id="identity_ambiguous",
                tags=["data", "integration"],
                handling=HANDLING_ABORT_OPERATION,
                message=(
                    f"Batch {batch_entity_id} failed: {entity_type} ref {ref!r} matched "
                    f"{len(candidates)} live rows — the NATURAL_KEY declaration cannot tell them apart."
                ),
                logger=logger,
                batch_entity_id=batch_entity_id,
                entity_type=entity_type,
                candidates=candidates,
            )
            raise _BatchFailed() from exc
        if resolution.key is not None:
            if resolution.key in keys_seen:
                who, partner_id = keys_seen[resolution.key]
                issues.append(
                    _issue(
                        "duplicate_entity_id",
                        f"ref {ref!r} describes the same {entity_type} as {who} "
                        "of this batch (identical constituting values); one source object, one node",
                        "execution",
                        path,
                        entity_id=partner_id,
                        batch_entity_id=batch_entity_id,
                        entity_type=entity_type,
                    )
                )
                raise _BatchFailed()
            keys_seen[resolution.key] = (f"ref {ref!r}", None)
        if not resolution.found:
            continue
        found = str(resolution.entity_id)
        if found in explicit_ids:
            issues.append(
                _issue(
                    "duplicate_entity_id",
                    f"ref {ref!r} resolves to {found}, which this batch also addresses by entity_id; "
                    "one source object, one write",
                    "execution",
                    path,
                    entity_id=found,
                    batch_entity_id=batch_entity_id,
                    entity_type=entity_type,
                )
            )
            raise _BatchFailed()
        if found in removal_targets:
            target = removal_targets[found]
            issues.append(
                _issue(
                    "entity_id_in_upsert_and_removal",
                    f"ref {ref!r} resolves to {found}, which this batch also names as a removal target "
                    f"({target.section}.{target.kind}s at {target.path}); split upsert-then-remove into "
                    "separate documents if that is intended",
                    "execution",
                    path,
                    entity_id=found,
                    batch_entity_id=batch_entity_id,
                    entity_type=entity_type,
                )
            )
            raise _BatchFailed()
        if found in taken:
            issues.append(
                _issue(
                    "duplicate_entity_id",
                    f"ref {ref!r} resolves to {found}, which another ref of this batch already resolved to",
                    "execution",
                    path,
                    entity_id=found,
                    batch_entity_id=batch_entity_id,
                    entity_type=entity_type,
                )
            )
            raise _BatchFailed()
        taken.add(found)
        substitutions[provisional] = found
        logger.debug("[b7ec] ref %s of batch %s resolved to existing %s %s", ref, batch_entity_id, entity_type, found)
    return substitutions


def _resolve_endpoint_keys(
    batch_container: dict[str, Any],
    *,
    batch_path: str,
    batch_entity_id: str,
    ctx: CallerContext,
    issues: list[GriftIssue],
    dangling_edge_ids: set[str],
    dangling_edge_mode: str,
) -> dict[str, list[dict[str, Any]]]:
    """Resolve every endpoint named by type and natural key; return the ones that resolved to nothing.

    Runs inside the batch transaction after the batch's node refs resolved, so this batch's nodes
    carry their final ids. Each key is looked up among this batch's own nodes first, then the
    live grid through the type's generated search (a tombstoned node is never found). A match
    rewrites the endpoint to an id; more than one match fails the batch as ``identity_ambiguous``.
    Nothing is ever created for an endpoint. An endpoint that names nothing is unresolved: strict
    mode fails the batch as ``dangling_edge``; permissive mode adds the edge to this batch's skip
    set, and the returned map says which endpoint did not resolve, for its skip event.

    Resolving a key reads the grid and tells the submitter what it found, so the import
    authorises ``grid.read`` first (``req-grid-import-grift-edge-endpoints-9``).

    TAP-IMPLEMENTS: req-grid-import-grift-edge-endpoints@36d488ac168c/1bce761f7421 (derivation) —
        the resolution of a key endpoint: batch first, then the live grid, ambiguity refused,
        nothing minted, an unresolved endpoint left to the dangling-edge mode, under grid.read.
    """
    from tap_auth import policy
    from tap_auth.capabilities import READ_CAPABILITY
    from tap_grid.registry import get_model_class

    edges = batch_container.get("edges", [])
    keyed = [e for e in edges if "from_key" in e["edge"] or "to_key" in e["edge"]]
    if not keyed:
        return {}
    policy.authorize(ctx, READ_CAPABILITY, operation="grift_import_endpoint_keys")
    batch_keys = _batch_node_keys(batch_container)

    unresolved: dict[str, list[dict[str, Any]]] = {}
    strict_unresolved = False
    for edge_idx, edge_obj in enumerate(edges):
        payload = edge_obj["edge"]
        edge_id = edge_obj["entity"]["entity_id"]
        for side, id_field, key_field in _EDGE_ENDPOINT_FORMS:
            if key_field not in payload:
                continue
            endpoint = payload[key_field]
            entity_type = endpoint["entity_type"]
            model_cls: Any = get_model_class(entity_type)
            properties = {name: endpoint["key"][name] for name in model_cls.NATURAL_KEY}
            path = f"{batch_path}.edges[{edge_idx}].edge.{key_field}"
            try:
                found = _find_node_by_key(entity_type, properties, batch_keys, ctx)
            except AmbiguousIdentity as exc:
                issues.append(
                    _issue(
                        "identity_ambiguous",
                        f"The {side} endpoint at {path}: {exc}",
                        "execution",
                        path,
                        entity_id=edge_id,
                        batch_entity_id=batch_entity_id,
                        entity_type="edge",
                        operation="resolve_endpoint_key",
                    )
                )
                raise _BatchFailed() from exc
            if found is not None:
                payload[id_field] = found
                del payload[key_field]
                continue
            if dangling_edge_mode == "strict":
                # Every unresolved endpoint is listed before the batch fails, so one run names
                # them all (req-grid-import-grift-edge-endpoints-7).
                issues.append(
                    _issue(
                        "dangling_edge",
                        f"The {side} endpoint at {path} names no live {entity_type} with {properties!r}",
                        "execution",
                        path,
                        entity_id=edge_id,
                        batch_entity_id=batch_entity_id,
                        entity_type="edge",
                        operation="resolve_endpoint_key",
                        edge_entity_id=edge_id,
                    )
                )
                strict_unresolved = True
                continue
            dangling_edge_ids.add(edge_id)
            unresolved.setdefault(edge_id, []).append({"endpoint": side, "entity_type": entity_type, "key": properties})
    if strict_unresolved:
        raise _BatchFailed()
    return unresolved


def _batch_node_keys(batch_container: dict[str, Any]) -> dict[str, list[str]]:
    """This batch's nodes by (type, identity key): the batch is the first place a key is found."""
    from tap_grid.registry import get_model_class

    batch_keys: dict[str, list[str]] = {}
    for node_obj in batch_container.get("nodes", []):
        entity_type = node_obj["entity"]["entity_type"]
        declared = getattr(get_model_class(entity_type), "NATURAL_KEY", None)
        if not isinstance(declared, tuple):
            continue
        key = identity_lock_key(entity_type, constituting_properties(declared, node_obj["node"]))
        if key is not None:
            batch_keys.setdefault(key, []).append(node_obj["entity"]["entity_id"])
    return batch_keys


def _find_node_by_key(
    entity_type: str, properties: dict[str, Any], batch_keys: dict[str, list[str]], ctx: CallerContext
) -> str | None:
    """The node a type and natural key name: this batch's nodes first, then the live grid. Never mints.

    The caller has authorised ``grid.read``. Raises ``AmbiguousIdentity`` when more than one
    node of the batch, or more than one live row, matches.
    """
    in_batch = batch_keys.get(identity_lock_key(entity_type, properties) or "", [])
    if len(in_batch) > 1:
        raise AmbiguousIdentity(entity_type, properties, list[object](in_batch))
    if in_batch:
        return in_batch[0]
    row_id = find_by_natural_key(entity_type, properties, caller_context=ctx)  # TAP-AUTHZ-COV: grid.read by caller
    return str(row_id) if row_id is not None else None


def _resolve_removal_identities(
    parsed_removals: _ParsedRemovalSections,
    batch_container: dict[str, Any],
    *,
    batch_entity_id: str,
    ctx: CallerContext,
    issues: list[GriftIssue],
) -> tuple[list[_ParsedRemovalTarget], int]:
    """Find the live edge each identity-addressed delete names now; return them as id targets.

    Runs inside the batch transaction, after this batch's nodes and edges have their final ids.
    Each endpoint is an id, or a key found among this batch's nodes, then the live grid; then the
    edge is found among live edges between the two, under the identity lock, through
    :func:`find_edge_by_identity`. The delete ends whichever live edge matches at this moment, so
    a relationship that was retired and came back under a new id is the new edge. A target that
    matches nothing is missing and follows ``deletes.on_missing``; a tombstoned edge never
    matches, so ``on_tombstoned`` does not apply. More than one match, a target naming an edge
    another target of this batch names, or an edge this batch also upserts, fails the batch, every
    such target listed first. Resolving reads the grid, so the import authorises ``grid.read``.

    The endpoints are found first, since that takes no lock; then the edges are looked up in the
    order of their lock keys, not the document's, so two batches ending overlapping relationships
    take those locks in one order and never each hold one while waiting for the other's.

    TAP-IMPLEMENTS: req-grid-import-grift-edge-removal@9b28437e0c32/5baf02cc1901 (derivation) — the
        resolution of a delete by identity: the live match at execution, missing by on_missing,
        ambiguity and duplicates refused, under grid.read and the identity lock.

    Returns:
        The resolved targets, as id-addressed `deletes.edges` targets, and how many were skipped
        as missing under ``on_missing`` warn or ignore.
    """
    from tap_auth import policy
    from tap_auth.capabilities import READ_CAPABILITY
    from tap_grid.edge_identity import edge_lock_key
    from tap_grid.registry import get_model_class

    targets = parsed_removals.deletes_edge_identities
    if not targets:
        return [], 0
    policy.authorize(ctx, READ_CAPABILITY, operation="grift_import_removal_identity")
    on_missing = parsed_removals.deletes_on_missing or "error"
    batch_keys = _batch_node_keys(batch_container)
    named = {t.entity_id: t.path for t in parsed_removals.all_targets()}
    upserted = {edge_obj["entity"]["entity_id"] for edge_obj in batch_container.get("edges", [])}
    resolved: list[_ParsedRemovalTarget] = []
    skipped = 0
    failed = False

    def note(code: str, message: str, path: str, entity_id: str | None = None) -> None:
        issues.append(
            _issue(
                code,
                message,
                "execution",
                path,
                entity_id=entity_id,
                batch_entity_id=batch_entity_id,
                entity_type="edge",
                operation="delete",
            )
        )

    def missing(target: _ParsedIdentityRemoval) -> bool:
        """Apply ``deletes.on_missing`` to a target that matched nothing; True when it fails the batch."""
        nonlocal skipped
        message = f"The delete at {target.path} matches no live {target.edge_type} edge"
        if on_missing == "error":
            note("removal_target_missing", f"{message} (section=deletes, on_missing=error).", target.path)
            return True
        if on_missing == "warn":
            note("removal_target_missing_warned", f"{message}; on_missing=warn — skipping.", target.path)
        skipped += 1
        return False

    def endpoint_id(endpoint: dict[str, Any]) -> str | None:
        if "entity_id" in endpoint:
            return str(endpoint["entity_id"])
        model_cls: Any = get_model_class(endpoint["entity_type"])
        properties = {name: endpoint["key"][name] for name in model_cls.NATURAL_KEY}
        return _find_node_by_key(endpoint["entity_type"], properties, batch_keys, ctx)

    located: list[tuple[str, _ParsedIdentityRemoval, str, str]] = []  # (lock key, target, from, to)
    for target in targets:
        try:
            source, sink = endpoint_id(target.endpoints["from"]), endpoint_id(target.endpoints["to"])
        except AmbiguousIdentity as exc:
            note("identity_ambiguous", f"The delete at {target.path}: {exc}", target.path)
            failed = True
            continue
        if source is None or sink is None:
            failed = missing(target) or failed
            continue
        located.append((edge_lock_key(target.edge_type, source, sink, target.discriminators), target, source, sink))

    for _, target, source, sink in sorted(located, key=lambda entry: entry[0]):
        try:
            found_id = find_edge_by_identity(  # TAP-AUTHZ-COV: gated by grift_import + grid.read above
                target.edge_type, source, sink, target.discriminators, caller_context=ctx
            )
        except AmbiguousIdentity as exc:
            note("identity_ambiguous", f"The delete at {target.path}: {exc}", target.path)
            failed = True
            continue
        if found_id is None:
            failed = missing(target) or failed
            continue
        found = str(found_id)
        if found in named:
            note(
                "duplicate_removal_target",
                f"The delete at {target.path} matches edge {found}, which {named[found]} also names",
                target.path,
                found,
            )
            failed = True
            continue
        if found in upserted:
            note(
                "entity_id_in_upsert_and_removal",
                f"The delete at {target.path} matches edge {found}, which this batch also upserts. Split into "
                "separate documents if upsert-then-remove is intended.",
                target.path,
                found,
            )
            failed = True
            continue
        named[found] = target.path
        resolved.append(
            _ParsedRemovalTarget(
                entity_id=found,
                entity_type="edge",
                reason=target.reason,
                section="deletes",
                kind="edge",
                path=target.path,
                batch_entity_id=batch_entity_id,
            )
        )
    if failed:
        raise _BatchFailed()
    return resolved, skipped


def _record_edge_skip(
    batch_entity_id: str,
    edge_entity_id: str,
    edge: dict[str, Any],
    unresolved_keys: list[dict[str, Any]],
    batch_node_ids: set[str],
) -> dict[str, Any]:
    """Write the skip event for one edge a permissive batch left out, and describe it for the result.

    Each endpoint that did not resolve is named as the batch named it: a key that found no live
    node, or an id that names neither a node of this batch nor a live entity. This runs while the
    batch's operations are being assembled, before its nodes are written, so a node this batch
    creates is resolved by membership in ``batch_node_ids``, as preflight resolves it, never by a
    database lookup that cannot see it yet.
    """
    from tap_grid.batch import record_skip_event

    endpoints = list(unresolved_keys)
    for side, id_field, _ in _EDGE_ENDPOINT_FORMS:
        endpoint_id = edge.get(id_field)
        if endpoint_id is None or endpoint_id in batch_node_ids:
            continue
        if not Entity.objects.filter(pk=uuid.UUID(endpoint_id), deleted_at__isnull=True).exists():
            endpoints.append({"endpoint": side, "entity_id": endpoint_id})
    metadata = {"edge_type": edge["edge_type"], "unresolved": endpoints, "reason": "unresolved_endpoint"}
    event = record_skip_event(batch_entity_id, edge_entity_id, metadata)
    return {"event_id": str(event.id), "edge_entity_id": edge_entity_id, **metadata}


def _resolve_edge_identities(
    batch_container: dict[str, Any],
    refs: dict[str, str],
    *,
    batch_path: str,
    batch_entity_id: str,
    ctx: CallerContext,
    issues: list[GriftIssue],
    parsed_removals: _ParsedRemovalSections | None,
    dangling_edge_ids: set[str],
) -> dict[str, str]:
    """Find each ref-addressed edge of one batch by its type's declared identity.

    Returns ``provisional id -> found id`` for the edges that already exist. Runs after the
    batch's node refs resolved, so every endpoint is a final id. Fails the batch
    (``_BatchFailed``) on an incomplete key, an ambiguous match, a keyless edge that duplicates
    another, or two edges of this batch that are one relationship.

    Which edges are looked up: an edge whose own envelope is a ``ref``. An edge addressed by
    an explicit id keeps today's behaviour (``req-grid-edge-identity-6``); only its keyless
    duplicate check runs, since a keyless edge equal to another is refused however it is
    addressed (``-5``). An undeclared type is created as before, with a warning, until the
    switch flips (``ENFORCE_EDGE_IDENTITY_DECLARED``, Issue# 928 - tap). Looking an edge up is
    a read of the grid, so the import authorises ``grid.read`` first (``-13``).

    TAP-IMPLEMENTS: req-grid-edge-identity@b9c04d9c5b2e/185c91e3f9f1 (enforcement) — the importer
        step that applies edge identity to a batch: which edges are looked up, the in-batch and
        keyless duplicate rules, the read authorisation, and the warn-mode switch for
        undeclared types (acceptance -5, -6, -9, -13).
    """
    from tap.flaws import HANDLING_ABORT_OPERATION, AppFlaw
    from tap_auth import policy
    from tap_auth.capabilities import READ_CAPABILITY
    from tap_grid import edge_identity as edge_identity_module
    from tap_grid.edge_identity import (
        IncompleteEdgeKey,
        KeylessEdgeExists,
        edge_identity_values,
        edge_lock_key,
        get_edge_identity,
        incomplete_paths,
    )

    edges = batch_container.get("edges", [])
    if not edges:
        return {}
    ref_of = {pid: ref for ref, pid in refs.items()}

    def reads_the_grid(edge_obj: dict[str, Any]) -> bool:
        """A declared type's ref is looked up; a keyless type's edge is checked for a live duplicate.

        An undeclared type's ref reads nothing in warn mode, so it must not need read either: warn
        mode leaves the import exactly as it was (req-grid-edge-identity-6).
        """
        identity = get_edge_identity(edge_obj["edge"]["edge_type"])
        if identity is None:
            return False
        return identity.keyless or edge_obj["entity"]["entity_id"] in ref_of

    # Reading the grid for an edge tells the submitter what is there, so it needs read, not only
    # import (req-grid-edge-identity-13). The verb is gated on read too; asking once here fails the
    # batch before any write with one clear refusal.
    if any(reads_the_grid(e) for e in edges if e["entity"]["entity_id"] not in dangling_edge_ids):
        policy.authorize(ctx, READ_CAPABILITY, operation="grift_import_edge_identity")

    explicit_ids = {
        item["entity"]["entity_id"]
        for section in ("nodes", "edges")
        for item in batch_container.get(section, [])
        if item["entity"]["entity_id"] not in ref_of
    }
    removal_targets = {t.entity_id: t for t in parsed_removals.all_targets()} if parsed_removals else {}
    substitutions: dict[str, str] = {}
    taken: set[str] = set()
    keys_seen: dict[str, str] = {}  # lock key -> who in this batch already named that relationship
    keyless_pairs: dict[tuple[str, str, str], str] = {}
    # An explicitly addressed edge keeps today's behaviour (no lookup), but it still names a
    # relationship: a ref in the same batch describing the same one must not create it twice.
    # Its key is the derivation the verb uses, read once from the declaration; an undeclared or
    # keyless type, or an incomplete key, has none.
    for edge_obj in edges:
        envelope_id = edge_obj["entity"]["entity_id"]
        if envelope_id in ref_of or envelope_id in dangling_edge_ids:
            continue
        payload = edge_obj["edge"]
        identity = get_edge_identity(payload["edge_type"])
        if identity is None or identity.keyless:
            continue
        values = edge_identity_values(identity, payload.get("properties") or {})
        if not incomplete_paths(values):
            explicit_key = edge_lock_key(
                payload["edge_type"], payload["from_entity_id"], payload["to_entity_id"], values
            )
            keys_seen.setdefault(explicit_key, f"entity_id {envelope_id}")

    def fail(code: str, message: str, path: str, edge_type: str, entity_id: str | None = None) -> _BatchFailed:
        issues.append(
            _issue(
                code,
                message,
                "execution",
                path,
                entity_id=entity_id,
                batch_entity_id=batch_entity_id,
                entity_type="edge",
                operation="resolve_edge_identity",
            )
        )
        return _BatchFailed()

    for edge_idx, edge_obj in enumerate(edges):
        envelope_id = edge_obj["entity"]["entity_id"]
        payload = edge_obj["edge"]
        edge_type = payload["edge_type"]
        path = f"{batch_path}.edges[{edge_idx}]"
        if envelope_id in dangling_edge_ids:
            continue  # skipped in permissive mode; there is no relationship to identify
        identity = get_edge_identity(edge_type)
        from_id, to_id = payload["from_entity_id"], payload["to_entity_id"]
        is_ref = envelope_id in ref_of
        who = f"ref {ref_of[envelope_id]!r}" if is_ref else f"entity_id {envelope_id}"

        if identity is not None and identity.keyless:
            # One spelling per endpoint, as the lock key and the verb read it (preflight already
            # canonicalises GRIFT ids, req-grid-import-grift-identity-4; this keeps the guard right
            # whoever fills the payload).
            pair = (edge_type, str(uuid.UUID(str(from_id))), str(uuid.UUID(str(to_id))))
            if pair in keyless_pairs:
                raise fail(
                    "duplicate_edge",
                    f"{who} and {keyless_pairs[pair]} of this batch are both {edge_type} {from_id} -> {to_id}; "
                    "the type is keyless, so two identical edges cannot be told apart (req-grid-edge-identity-5)",
                    path,
                    edge_type,
                    envelope_id,
                )
            keyless_pairs[pair] = who
        if not is_ref:
            if identity is not None and identity.keyless:
                try:
                    resolve_edge_identity(  # TAP-AUTHZ-COV: gated by grift_import + grid.read above
                        edge_type, from_id, to_id, payload.get("properties") or {}, caller_context=ctx
                    )
                except KeylessEdgeExists as exc:
                    others = [str(c) for c in exc.candidates if str(c) != envelope_id]
                    if others:
                        raise fail("duplicate_edge", f"{who}: {exc}", path, edge_type, envelope_id) from exc
            continue

        ref = ref_of[envelope_id]
        if identity is None:
            if edge_identity_module.ENFORCE_EDGE_IDENTITY_DECLARED:
                raise fail(
                    "identity_undeclared",
                    f"ref {ref!r}: edge type {edge_type} declares no identity, so a ref-addressed edge of it "
                    "cannot be found again (req-grid-edge-identity-6). Declare discriminators or keyless on "
                    "its edge definition.",
                    f"{path}.entity.ref",
                    edge_type,
                )
            # Warn mode logs, as the edge-schema rule's warn mode does ([d393]): the import's result
            # is unchanged until the flip, so producers can declare first.
            logger.warning(
                "[9acf] ref %s of batch %s: edge type %s declares no identity; created without a lookup, as "
                "before. Declare one on its edge definition before Issue# 928 - tap makes this a refusal "
                "(req-grid-edge-identity-6).",
                ref,
                batch_entity_id,
                edge_type,
            )
            continue
        try:
            resolution = resolve_edge_identity(  # TAP-AUTHZ-COV: gated by grift_import + grid.read above
                edge_type,
                from_id,
                to_id,
                payload.get("properties") or {},
                caller_context=ctx,
                provisional=envelope_id,
            )
        except IncompleteEdgeKey as exc:
            raise fail("incomplete_edge_key", f"ref {ref!r}: {exc}", f"{path}.edge.properties", edge_type) from exc
        except KeylessEdgeExists as exc:
            raise fail("duplicate_edge", f"ref {ref!r}: {exc}", path, edge_type) from exc
        except AmbiguousIdentity as exc:
            candidates = [str(c) for c in exc.candidates]
            AppFlaw.report(
                invariant_id="identity_ambiguous",
                tags=["data", "integration"],
                handling=HANDLING_ABORT_OPERATION,
                message=(
                    f"Batch {batch_entity_id} failed: {edge_type} ref {ref!r} matched {len(candidates)} live "
                    "edges — the edge type's identity declaration cannot tell them apart."
                ),
                logger=logger,
                batch_entity_id=batch_entity_id,
                entity_type="edge",
                candidates=candidates,
            )
            raise fail("identity_ambiguous", f"ref {ref!r}: {exc}", f"{path}.entity.ref", edge_type) from exc
        if resolution.key is not None and not identity.keyless:
            if resolution.key in keys_seen:
                raise fail(
                    "duplicate_edge",
                    f"ref {ref!r} and {keys_seen[resolution.key]} of this batch are the same {edge_type} "
                    "relationship (identical endpoints and discriminators); one relationship, one edge "
                    "(req-grid-edge-identity-9)",
                    f"{path}.entity.ref",
                    edge_type,
                )
            keys_seen[resolution.key] = f"ref {ref!r}"
        if not resolution.found:
            continue
        found = str(resolution.entity_id)
        if found in explicit_ids:
            raise fail(
                "duplicate_entity_id",
                f"ref {ref!r} resolves to edge {found}, which this batch also addresses by entity_id; one "
                "relationship, one write",
                f"{path}.entity.ref",
                edge_type,
                found,
            )
        if found in removal_targets:
            target = removal_targets[found]
            raise fail(
                "entity_id_in_upsert_and_removal",
                f"ref {ref!r} resolves to edge {found}, which this batch also names as a removal target "
                f"({target.section}.{target.kind}s at {target.path}); split upsert-then-remove into separate "
                "documents if that is intended",
                f"{path}.entity.ref",
                edge_type,
                found,
            )
        if found in taken:
            raise fail(
                "duplicate_entity_id",
                f"ref {ref!r} resolves to edge {found}, which another ref of this batch already resolved to",
                f"{path}.entity.ref",
                edge_type,
                found,
            )
        taken.add(found)
        substitutions[envelope_id] = found
        logger.debug(
            "[fff7] edge ref %s of batch %s resolved to existing %s %s", ref, batch_entity_id, edge_type, found
        )
    return substitutions


# ---------------------------------------------------------------------------
# Spine-field sync for replaced nodes (req-grid-import-grift-batch / Spine Sync)
# ---------------------------------------------------------------------------


def _apply_authority_claims(
    claims: list[dict[str, Any]],
    batch_container: dict[str, Any],
    *,
    batch: Any,
    batch_path: str,
    batch_entity_id: str,
    ctx: CallerContext,
    actor: Any,
    read_boundary: datetime | None,
    dangling_edge_ids: set[str],
    skips: list[dict[str, Any]],
    issues: list[GriftIssue],
) -> list[dict[str, Any]]:
    """Judge each authority claim and record what it would remove, removing nothing.

    Runs inside the batch's transaction after every write the batch makes, so the scope is read
    as this batch leaves it. A claim states that, for its edge type at its anchor in its
    direction, the batch's edges are the total allowed set; every other live edge in that scope,
    whoever wrote it, is a proposed removal (``req-grid-reconcile-edge-authority``). This is the
    dry-run: each proposal is an ``authority_proposed`` event on the edge, each claim's outcome one
    on the batch, and no edge is removed, ended or changed.

    Only a ``complete`` read licenses a proposal; a claim with no producing run has no read
    boundary and proposes nothing. Each proposal is fenced against its locked row: an edge any
    batch but this one created, updated or linked after the run opened, this run's other batches
    included, is ``rejected_stale``.

    Every claimed anchor is locked before any scope is read, so the record is the whole scope: an
    edge created concurrently at an anchor either committed before the read or waits for this batch.

    Raises ``_BatchFailed`` for two claims over one scope, and for an anchor key that names more
    than one node. Computing proposals reads the grid, so ``grid.read`` is authorised first.

    TAP-IMPLEMENTS: req-grid-reconcile-edge-authority@c4551f3f9ef9/6489bf991327 (derivation) — the one
        place a claim's scope, its asserted set and its proposals are derived, fenced and recorded.
    """
    from tap_auth import policy
    from tap_auth.capabilities import READ_CAPABILITY
    from tap_grid.edge_identity import edge_identity_values, get_edge_identity
    from tap_grid.models import BatchEvent, BatchEventType, Edge
    from tap_grid.registry import get_model_class

    policy.authorize(ctx, READ_CAPABILITY, operation="grift_import_edge_authority")

    batch_keys = _batch_node_keys(batch_container)
    claims_path = f"{batch_path}.edge_cases.authority"

    def anchor_id(anchor: dict[str, Any]) -> str | None:
        if "entity_id" in anchor:
            live = Entity.objects.filter(pk=uuid.UUID(anchor["entity_id"]), deleted_at__isnull=True)
            return anchor["entity_id"] if live.exclude(entity_type="edge").exists() else None
        model_cls: Any = get_model_class(anchor["entity_type"])
        properties = {name: anchor["key"][name] for name in model_cls.NATURAL_KEY}
        return _find_node_by_key(anchor["entity_type"], properties, batch_keys, ctx)

    resolved: list[str | None] = []
    failed = False
    for idx, claim in enumerate(claims):
        try:
            resolved.append(anchor_id(claim["anchor"]))
        except AmbiguousIdentity as exc:
            issues.append(
                _issue(
                    "identity_ambiguous",
                    f"The claim at {claims_path}[{idx}]: {exc}",
                    "execution",
                    f"{claims_path}[{idx}].anchor",
                    batch_entity_id=batch_entity_id,
                )
            )
            resolved.append(None)
            failed = True

    # One claim per scope (-4): an anchor named twice, by id and by key, is one scope.
    first_at: dict[tuple[str, str, str], int] = {}
    for idx, (claim, found) in enumerate(zip(claims, resolved, strict=True)):
        named = found if found is not None else json.dumps(claim["anchor"], sort_keys=True)
        scope = (claim["edge_type"], named, claim["direction"])
        if scope in first_at:
            issues.append(
                _issue(
                    "duplicate_authority_claim",
                    f"The claims at {claims_path}[{first_at[scope]}] and [{idx}] cover one scope ({claim['edge_type']} "
                    f"{claim['direction']} at {named}); a batch makes one claim per scope, after every rule "
                    "that emits the type has contributed",
                    "execution",
                    f"{claims_path}[{idx}]",
                    batch_entity_id=batch_entity_id,
                )
            )
            failed = True
        else:
            first_at[scope] = idx
    if failed:
        raise _BatchFailed()

    # Hold every claimed anchor before reading any scope. An edge is created only under a lock on
    # both its endpoints, so no edge can join a scope between the read below and this batch's
    # commit: a concurrent create either committed first and is read, or waits for this batch.
    # One lock set in id order, so two batches claiming the same anchors in opposite orders never
    # wait on each other (the lesson of Issue# 943 - tap).
    list(
        Entity.objects.select_for_update()
        .filter(pk__in=sorted({uuid.UUID(found) for found in resolved if found is not None}))
        .order_by("pk")
        .values_list("pk", flat=True)
    )

    written = {
        e["entity"]["entity_id"]
        for e in batch_container.get("edges", [])
        if e["entity"]["entity_id"] not in dangling_edge_ids
    }
    edges_by_id = {e["entity"]["entity_id"]: e["edge"] for e in batch_container.get("edges", [])}
    summaries: list[dict[str, Any]] = []
    for idx, (claim, found) in enumerate(zip(claims, resolved, strict=True)):
        edge_type, direction, read = claim["edge_type"], claim["direction"], claim["read"]
        anchor_field, far_field = (
            ("from_entity_id", "to_entity_id") if direction == "outbound" else ("to_entity_id", "from_entity_id")
        )
        scope_record = {
            "edge_type": edge_type,
            "anchor": claim["anchor"],
            "anchor_entity_id": found,
            "direction": direction,
        }
        summary: dict[str, Any] = {
            "path": f"{claims_path}[{idx}]",
            **scope_record,
            "read": read,
            "read_boundary": read_boundary.isoformat() if read_boundary is not None else None,
            "outcome": "not_claimed",
            "reason": None,
            "asserted": 0,
            "asserted_skipped": [],
            "proposed": 0,
            "rejected_stale": 0,
        }
        if read != "complete":
            summary["reason"] = read
        elif read_boundary is None:
            summary["reason"] = "no_read_boundary"
        elif found is None:
            summary["reason"] = "anchor_unresolved"
        else:
            summary["outcome"] = "claimed"
            in_scope = {
                str(entity_id)
                for entity_id in Edge.objects.filter(edge_type=edge_type, **{anchor_field: found}).values_list(
                    "entity_id", flat=True
                )
            }
            asserted = in_scope & written
            # A skipped edge names an endpoint nothing live answers to, so no live edge in scope can be
            # it; it counts as asserted and is listed, so a relationship the batch could not wire is
            # never read as one it denied (-3).
            summary["asserted_skipped"] = [
                skip["event_id"]
                for skip in skips
                if skip["edge_type"] == edge_type
                and edges_by_id.get(skip["edge_entity_id"], {}).get(anchor_field) == found
            ]
            summary["asserted"] = len(asserted) + len(summary["asserted_skipped"])
            candidates = sorted(in_scope - asserted)
            # Lock in id order, so two writers judging overlapping scopes never wait on each other
            # (the lesson of Issue# 943 - tap), then keep only what is still live under the lock.
            locked = list(
                Entity.objects.select_for_update()
                .filter(pk__in=[uuid.UUID(c) for c in candidates], deleted_at__isnull=True)
                .order_by("pk")
                .values_list("pk", flat=True)
            )
            observed: dict[str, set[str]] = {}
            for entity_id, observer in (
                BatchEvent.objects.filter(
                    entity_id__in=locked,
                    event_type__in=[BatchEventType.CREATE, BatchEventType.UPDATE, BatchEventType.LINK],
                    timestamp__gt=read_boundary,
                )
                .exclude(batch__entity_id=batch_entity_id)
                .values_list("entity_id", "batch__entity_id")
            ):
                observed.setdefault(str(entity_id), set()).add(str(observer))
            declaration = get_edge_identity(edge_type)
            events = []
            # django-stubs types the LiveManager's rows as BaseModel, not Edge.
            for edge in cast("list[Edge]", list(Edge.objects.filter(entity_id__in=locked).order_by("entity_id"))):
                edge_id = str(edge.entity_id)
                stale = sorted(observed.get(edge_id, ()))
                outcome = "rejected_stale" if stale else "proposed"
                summary[outcome] += 1
                discriminators = (
                    edge_identity_values(declaration, edge.properties or {})
                    if declaration is not None and not declaration.keyless
                    else {}
                )
                events.append(
                    BatchEvent(
                        batch=batch,
                        event_type=BatchEventType.AUTHORITY_PROPOSED,
                        entity_id=edge.entity_id,
                        entity_type="edge",
                        model_name="Edge",
                        actor=actor,
                        metadata={
                            "record": "proposal",
                            "outcome": outcome,
                            "claim": {**scope_record, "read": read},
                            "identity": {
                                "edge_type": edge_type,
                                "from_entity_id": str(edge.from_entity_id),
                                "to_entity_id": str(edge.to_entity_id),
                                "discriminators": discriminators,
                            },
                            "far_entity_id": str(getattr(edge, far_field)),
                            "observed_by": stale,
                        },
                    )
                )
            BatchEvent.objects.bulk_create(events)
        claim_event = BatchEvent.objects.create(
            batch=batch,
            event_type=BatchEventType.AUTHORITY_PROPOSED,
            entity_id=batch.entity.id,
            entity_type="batch",
            model_name="Batch",
            actor=actor,
            metadata={"record": "claim", **summary},
        )
        summaries.append({"event_id": str(claim_event.id), **summary})
    return summaries


def _sync_spine_for_replaced_nodes(replace_intents: list[dict[str, Any]]) -> None:
    """Propagate envelope-side spine fields onto existing Entity rows.

    For each intent in ``replace_intents`` (the bundle's envelope `name` and
    `dimensions` for an entity that already existed at import time), update
    the Entity row in-place when the persisted value differs from the
    bundle's declaration. This makes the GRIFT envelope authoritative for
    spine values on every import — the service-layer ``replace_node`` verb
    deliberately leaves spine fields untouched, so without this post-pass a
    renamed or re-dimensioned entity in a re-imported bundle would silently
    drift between model-side ``name`` and spine-side ``Entity.name``.

    Uses ``Entity.objects.filter(...).update(...)`` rather than ``save()`` so
    a pure spine sync does not bump the entity's version counter (the version
    field tracks logical, model-level mutations) and to keep the post-pass
    cheap. ``updated_at`` is bumped explicitly to reflect that something on
    the row did change.
    """
    if not replace_intents:
        return

    now = timezone.now()
    for intent in replace_intents:
        entity_uuid = uuid.UUID(intent["entity_id"])
        envelope_name = intent.get("envelope_name")
        envelope_dims = intent.get("envelope_dims") or {}

        # Read the persisted spine values to decide whether anything needs to
        # change. A no-op update should not bump updated_at.
        try:
            persisted = Entity.objects.values("name", "dimensions").get(pk=entity_uuid)
        except Entity.DoesNotExist:
            continue

        update_fields: dict[str, Any] = {}
        if envelope_name is not None and envelope_name != persisted["name"]:
            update_fields["name"] = envelope_name
        if envelope_dims and envelope_dims != (persisted["dimensions"] or {}):
            update_fields["dimensions"] = envelope_dims

        if update_fields:
            update_fields["updated_at"] = now
            Entity.objects.filter(pk=entity_uuid).update(**update_fields)


# ---------------------------------------------------------------------------
# Batch-scoped sweep (req-grid-import-grift-batch-scoped-sweep / sweep-purge)
# ---------------------------------------------------------------------------


def _run_batch_scoped_sweep(
    *,
    batch_entity_id: str,
    batch_container: dict[str, Any],
    caller_ctx: CallerContext,
    sweep_strict: bool,
    purge: bool,
    skipped_edge_ids: frozenset[str] = frozenset(),
) -> tuple[list[GriftSweptEntity], list[GriftSweepSkipped]]:
    """Detect and remove entities the prior version of this batch created that

    TAP-IMPLEMENTS: req-grid-import-grift-batch-scoped-sweep@caf1167ea250/c098e4b6e7fc (derivation)
        — the force-reimport omission sweep.
    are absent in the revised content. Returns (swept_entities, sweep_skipped).

    Raises ``_SweepStrictAborted`` with the skipped-candidate list if
    ``sweep_strict`` is set and any candidate fails a guardrail. The
    enclosing transaction rolls back, undoing all upserts applied by the
    revised batch.

    Guardrails:
      A. Ownership — no BatchEvent exists for this entity with a different
         batch_id. If another batch has written to the entity, skip it.
      B. Referential integrity — no edge survives the sweep referencing the
         candidate in either direction. An edge survives the sweep if it
         exists and is not itself being swept, or if the revised batch's new
         edge list points at the candidate.

    If ``purge`` is set, surviving candidates are hard-deleted along with
    their batch-scoped BatchEvent rows and domain-model history. Default is
    tombstone via service-layer delete.
    """
    from django.db.models import Q

    from tap_grid.models import BatchEvent, BatchEventType, Edge, Entity

    # --- Build the new-version id sets (post-apply state). ---
    new_node_ids: set[str] = {n["entity"]["entity_id"] for n in batch_container.get("nodes", [])}
    # An edge this revision skipped for an unresolved endpoint (``skipped_edge_ids``, permissive
    # mode) was not written by it: it is absent from the new state, so its earlier write is a sweep
    # candidate, and it keeps no endpoint alive (req-grid-import-grift-edge-endpoints-6).
    written_edges = [e for e in batch_container.get("edges", []) if e["entity"]["entity_id"] not in skipped_edge_ids]
    new_edge_ids: set[str] = {e["entity"]["entity_id"] for e in written_edges}
    new_edge_endpoints: list[tuple[str, str]] = [
        (e["edge"]["from_entity_id"], e["edge"]["to_entity_id"]) for e in written_edges
    ]

    # --- Candidates: live entities this batch first wrote that are absent from the new sets. ---
    # A node's first write is a ``create`` event and an edge's a ``link`` event. An entity already
    # tombstoned (by an earlier sweep, an explicit removal or a cascade) is not a candidate.
    first_writes: dict[str, str] = {
        str(ev["entity_id"]): ev["entity_type"]
        for ev in BatchEvent.objects.filter(batch__entity_id=batch_entity_id)
        .filter(Q(event_type=BatchEventType.CREATE) | Q(event_type=BatchEventType.LINK, entity_type="edge"))
        .values("entity_id", "entity_type")
    }
    first_write_ids = [uuid.UUID(e) for e in first_writes]
    live = set(Entity.objects.filter(pk__in=first_write_ids, deleted_at__isnull=True).values_list("pk", flat=True))
    candidate_entity_ids: list[tuple[str, str]] = [  # (entity_id, entity_type)
        (eid, etype)
        for eid, etype in first_writes.items()
        if uuid.UUID(eid) in live and eid not in (new_edge_ids if etype == "edge" else new_node_ids)
    ]
    # Edges first: a node's referential guardrail discounts only an edge already cleared to go,
    # never one this sweep will keep.
    candidate_entity_ids.sort(key=lambda c: c[1] != "edge")

    if not candidate_entity_ids:
        return [], []

    swept: list[GriftSweptEntity] = []
    skipped: list[GriftSweepSkipped] = []
    cleared: list[tuple[str, str]] = []  # candidates that passed both guardrails
    cleared_edge_ids: list[uuid.UUID] = []

    # --- Evaluate guardrails per candidate. ---
    for entity_id_str, entity_type in candidate_entity_ids:
        # Guardrail A — ownership. Any event for this entity from a different batch?
        external_writes_exist = (
            BatchEvent.objects.filter(entity_id=entity_id_str).exclude(batch__entity_id=batch_entity_id).exists()
        )
        if external_writes_exist:
            skipped.append(
                GriftSweepSkipped(
                    entity_id=entity_id_str,
                    entity_type=entity_type,
                    reason="sweep_skipped_external_write",
                )
            )
            continue

        # Guardrail B — referential integrity (node candidates only).
        # For an edge candidate, Guardrail B is implicit: the edge itself is
        # being swept, so edges-referencing-edges doesn't apply (TAP's edge
        # model rejects edge-as-endpoint). So we only check for nodes.
        if entity_type != "edge":
            candidate_uuid = uuid.UUID(entity_id_str)
            # Existing edges that touch this node AND are not being swept.
            surviving_existing = (
                Edge.all_objects.filter(Q(from_entity_id=candidate_uuid) | Q(to_entity_id=candidate_uuid))
                .filter(entity__deleted_at__isnull=True)
                .exclude(entity_id__in=cleared_edge_ids)
            )
            if surviving_existing.exists():
                skipped.append(
                    GriftSweepSkipped(
                        entity_id=entity_id_str,
                        entity_type=entity_type,
                        reason="sweep_skipped_referenced",
                    )
                )
                continue

            # New-version edges that point at this candidate.
            touched_by_new = any(entity_id_str in (from_id, to_id) for from_id, to_id in new_edge_endpoints)
            if touched_by_new:
                skipped.append(
                    GriftSweepSkipped(
                        entity_id=entity_id_str,
                        entity_type=entity_type,
                        reason="sweep_skipped_referenced",
                    )
                )
                continue

        cleared.append((entity_id_str, entity_type))
        if entity_type == "edge":
            cleared_edge_ids.append(uuid.UUID(entity_id_str))

    # --- Strict-mode abort: any skip cancels the entire force re-import. ---
    if sweep_strict and skipped:
        raise _SweepStrictAborted(skipped)

    # --- Apply deletions. ---
    if purge:
        swept = _apply_sweep_purge(cleared, batch_entity_id)
    else:
        swept = _apply_sweep_tombstone(cleared, caller_ctx)

    return swept, skipped


def _apply_sweep_tombstone(
    cleared: list[tuple[str, str]],
    caller_ctx: CallerContext,
) -> list[GriftSweptEntity]:
    """Tombstone each cleared candidate via the service-layer delete path.

    Routes through ``write_batch`` so tombstone cascade (to connected edges)
    and batch-scoped provenance both fire via the standard pipeline.
    """
    from tap_grid.service_types import WriteOperation
    from tap_grid.services import write_batch

    ops: list[WriteOperation] = []
    for eid, etype in cleared:
        verb = "delete_edge" if etype == "edge" else "delete_node"
        ops.append(WriteOperation(verb=verb, target=eid))
    if ops:
        # A sweep tombstones nodes/edges, so authorize grid.delete explicitly here — grift_import's
        # scope only authorizes grid.import_grift, so without this an actor lacking grid.delete
        # (tap_bootloader / tap_cares.collector) would trip the write_batch delete backstop as an
        # UnguardedOperation instead of a clean denial. Symmetric with the imperative-removal path.
        # The marker exempts the write_batch call (the scanner can't see a bare authorize).
        from tap_auth import policy
        from tap_auth.capabilities import DELETE_CAPABILITY

        policy.authorize(caller_ctx, DELETE_CAPABILITY, operation="grift_sweep_tombstone")
        write_batch(ops, caller_context=caller_ctx)  # TAP-AUTHZ-COV: explicit grid.delete authorize above

    return [
        GriftSweptEntity(
            entity_id=eid,
            entity_type=etype,
            action="tombstone",
            reason="orphaned",
        )
        for eid, etype in cleared
    ]


def _apply_sweep_purge(
    cleared: list[tuple[str, str]],
    batch_entity_id: str,
) -> list[GriftSweptEntity]:
    """Hard-delete each cleared candidate along with this batch's BatchEvent

    TAP-IMPLEMENTS: req-grid-import-grift-sweep-purge@3830e6186280/ce9bc321fb52 (derivation) — the
        opt-in hard-delete escalation of the sweep.
    rows and any domain-model history tied to the candidate.

    Guardrail A guarantees the only history rows/events to delete are this
    batch's own; if that assumption ever fails mid-run, we abort loudly
    rather than touch anything we shouldn't.
    """
    from tap_grid.models import BatchEvent, Edge, Entity
    from tap_grid.registry import get_model_class

    swept: list[GriftSweptEntity] = []

    for entity_id_str, entity_type in cleared:
        candidate_uuid = uuid.UUID(entity_id_str)

        # Verify Guardrail A one last time: no events with a foreign batch_id.
        # If one appears here, we raise; the enclosing transaction rolls back
        # the whole force re-import (including any prior purges in this run).
        foreign_events = (
            BatchEvent.objects.filter(entity_id=candidate_uuid).exclude(batch__entity_id=batch_entity_id).exists()
        )
        if foreign_events:
            raise RuntimeError(
                f"Purge integrity check failed for {entity_id_str}: foreign-batch events found. "
                "Aborting the entire force re-import."
            )

        # Hard-delete this batch's events for the entity.
        BatchEvent.objects.filter(
            entity_id=candidate_uuid,
            batch__entity_id=batch_entity_id,
        ).delete()

        # Hard-delete domain-model history rows for the entity, if the entity
        # type has a registered model class with a HistoricalRecords manager.
        if entity_type != "edge":
            try:
                model_cls = get_model_class(entity_type)
            except KeyError:
                model_cls = None
            if model_cls is not None and hasattr(model_cls, "history"):
                model_cls.history.filter(entity_id=candidate_uuid).delete()

        # For node entities, cascade-hard-delete attached edges (the domain
        # Edge rows, their BaseModel history, and their own Entity spines).
        if entity_type != "edge":
            from django.db.models import Q as _Q

            attached_edges = list(
                Edge.all_objects.filter(
                    _Q(from_entity_id=candidate_uuid) | _Q(to_entity_id=candidate_uuid)
                ).values_list("entity_id", flat=True)
            )
            if attached_edges:
                # Edge history rows are on the Edge model.
                Edge.history.filter(entity_id__in=attached_edges).delete()
                BatchEvent.objects.filter(
                    entity_id__in=attached_edges,
                    batch__entity_id=batch_entity_id,
                ).delete()
                # Deleting the edge's Entity spine cascades the Edge row via
                # the OneToOneField(on_delete=CASCADE) on BaseModel.
                Entity.objects.filter(pk__in=attached_edges).delete()

        # Finally, hard-delete the candidate Entity itself. For edge candidates,
        # this removes the Edge row and its history via cascade; for node
        # candidates, this removes the domain row + anything else referencing
        # the Entity.
        if entity_type == "edge":
            Edge.history.filter(entity_id=candidate_uuid).delete()
        Entity.objects.filter(pk=candidate_uuid).delete()

        swept.append(
            GriftSweptEntity(
                entity_id=entity_id_str,
                entity_type=entity_type,
                action="purge",
                reason="orphaned",
            )
        )

    return swept


def _emit_force_reimport_event(
    *,
    batch: Any,
    nodes_imported: int,
    edges_imported: int,
    edges_skipped: int,
    swept_entities: list[GriftSweptEntity],
    sweep_skipped: list[GriftSweepSkipped],
    purge: bool,
    sweep_strict: bool,
    actor: Any,
) -> None:
    """Emit the FORCE_REIMPORT BatchEvent so the audit trail reads as
    'initial ingest → force re-import(s) → further activity'.
    """
    from tap_grid.models import BatchEvent, BatchEventType

    BatchEvent.objects.create(
        batch=batch,
        event_type=BatchEventType.FORCE_REIMPORT,
        entity_id=batch.entity_id,
        entity_type="batch",
        actor=actor,
        metadata={
            "nodes_imported": nodes_imported,
            "edges_imported": edges_imported,
            "edges_skipped": edges_skipped,
            "entities_swept": len(swept_entities),
            "entities_purged": sum(1 for s in swept_entities if s.action == "purge"),
            "sweep_skipped": len(sweep_skipped),
            "purge": purge,
            "sweep_strict": sweep_strict,
            "swept_entity_ids": [s.entity_id for s in swept_entities],
            "sweep_skipped_reasons": {s.entity_id: s.reason for s in sweep_skipped},
        },
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def grift_import(
    document: dict[str, Any] | str | bytes,
    *,
    dangling_edge_mode: Literal["strict", "permissive"] = "strict",
    actor: Any = None,
    force_batches: list[str] | set[str] | None = None,
    sweep_strict: bool = False,
    purge: bool = False,
) -> GriftImportResult:
    """Authorize, then import a GRIFT v0 document (req-tap-auth-service-boundary).

    GRIFT import requires `grid.import_grift`; a force-reimport `purge`
    additionally requires `grid.purge` (and DEBUG, enforced downstream). `actor`
    defaults to the active CallerContext actor when not passed explicitly, so
    callers that already set the context (tests, web/API) need not re-pass it;
    the import command passes `tap_bootloader`. Delegates to `_grift_import_impl`.
    """
    from tap_auth import policy
    from tap_auth.capabilities import IMPORT_GRIFT_CAPABILITY, PURGE_CAPABILITY
    from tap_auth.enforcement import authorized
    from tap_grid.caller_context import CallerContext, get_caller_context

    _active = get_caller_context()
    if actor is None:
        actor = _active.user if _active is not None else None
    _auth_ctx = CallerContext(user=actor)
    with authorized(_auth_ctx, IMPORT_GRIFT_CAPABILITY, operation="grift_import"):
        if purge:
            policy.authorize(_auth_ctx, PURGE_CAPABILITY, operation="grift_import_purge")
        return _grift_import_impl(
            document,
            dangling_edge_mode=dangling_edge_mode,
            actor=actor,
            force_batches=force_batches,
            sweep_strict=sweep_strict,
            purge=purge,
            read_boundary=_producing_run_opened(_active),
        )


def _producing_run_opened(active: Any) -> datetime | None:
    """When the run that submitted this import opened, or ``None`` when no run did.

    A collection run opens its lifecycle batch before any collector code executes and binds it as
    the caller's batch for the whole run (``req-tap-cares-collector-run-collection-10``), stamped at
    creation with the run's reconcile configuration, which nothing writes afterwards. So the bound
    batch carrying that stamp is the producing run, and its opening precedes every read a claim
    rests on (``req-grid-reconcile-edge-authority-8``). Derived from the caller, never from the
    document: a document cannot name its own boundary.
    """
    from collections.abc import Mapping

    from tap_grid.models import Batch
    from tap_grid.reconcile import RUN_CONFIG_KEY

    batch_id = getattr(active, "batch_id", None)
    if not batch_id:
        return None
    # django-stubs types the manager's rows as BaseModel, not Batch.
    run = cast("Batch | None", Batch.all_objects.filter(entity_id=batch_id).first())
    if run is None or not isinstance((run.metadata or {}).get(RUN_CONFIG_KEY), Mapping):
        return None
    opened: datetime = run.started_at
    return opened


def _grift_import_impl(
    document: dict[str, Any] | str | bytes,
    *,
    dangling_edge_mode: Literal["strict", "permissive"] = "strict",
    actor: Any = None,
    force_batches: list[str] | set[str] | None = None,
    sweep_strict: bool = False,
    purge: bool = False,
    read_boundary: datetime | None = None,
) -> GriftImportResult:
    """Import a GRIFT v0 document into the local TAP grid.

    Validates the full document before any mutation (preflight), then executes
    each batch atomically using upsert semantics (create if new, replace if
    present by entity_id).

    Args:
        document: GRIFT document as a parsed dict, JSON string, or bytes.
        dangling_edge_mode: "strict" fails preflight on any dangling edge;
            "permissive" skips only the offending edges and continues.
        actor: Optional User to record as the import actor.
        force_batches: Optional collection of batch_entity_id strings to
            force re-import (bypass the skip-if-exists guard). Permitted
            if and only if Django's DEBUG setting is True.
            See req-grid-import-grift-force-reimport.
        sweep_strict: If True, a force re-import aborts before any writes
            if any sweep candidate fails a guardrail. Only meaningful with
            force_batches. See req-grid-import-grift-batch-scoped-sweep.
        purge: If True, force re-import hard-deletes swept entities (and
            their batch-scoped history) instead of tombstoning. Permitted
            if and only if DEBUG=True. Only meaningful with force_batches.
            See req-grid-import-grift-sweep-purge.

    Returns:
        GriftImportResult describing every phase of the import.
    """
    from django.conf import settings

    reference_time = timezone.now()

    # Normalise force_batches to a set of strings.
    force_batches_set: set[str] = set(force_batches or [])

    # --purge only makes sense with force_batches; check this first so the
    # error surfaces consistently whether or not DEBUG is set.
    if purge and not force_batches_set:
        return GriftImportResult(
            success=False,
            grift_version="",
            import_mode=IMPORT_MODE,
            dangling_edge_mode=dangling_edge_mode,
            reference_time=reference_time.isoformat(),
            counts=GriftCounts(errors=1),
            imported_batches=[],
            skipped_batches=[],
            errors=[
                _issue(
                    "purge_requires_force_reimport",
                    "--purge requires --force-batches; no batches were named for force re-import.",
                    "preflight",
                    "$",
                )
            ],
            warnings=[],
        )

    # req-grid-import-grift-force-reimport env gate: permitted iff DEBUG=True.
    # There is no alternate flag, override, or settings key that enables it
    # in any other configuration. Refuse with a dedicated error code so the
    # operator sees exactly why it was rejected.
    if force_batches_set and not settings.DEBUG:
        return GriftImportResult(
            success=False,
            grift_version="",
            import_mode=IMPORT_MODE,
            dangling_edge_mode=dangling_edge_mode,
            reference_time=reference_time.isoformat(),
            counts=GriftCounts(errors=1),
            imported_batches=[],
            skipped_batches=[],
            errors=[
                _issue(
                    "force_reimport_refused_production",
                    "Force re-import is permitted if and only if DEBUG=True. " "Refusing the invocation.",
                    "preflight",
                    "$",
                )
            ],
            warnings=[],
        )
    # req-grid-import-grift-sweep-purge env gate: same invariant, applied
    # independently so --purge refusals are distinguishable.
    if purge and not settings.DEBUG:
        return GriftImportResult(
            success=False,
            grift_version="",
            import_mode=IMPORT_MODE,
            dangling_edge_mode=dangling_edge_mode,
            reference_time=reference_time.isoformat(),
            counts=GriftCounts(errors=1),
            imported_batches=[],
            skipped_batches=[],
            errors=[
                _issue(
                    "sweep_purge_refused_production",
                    "--purge is permitted if and only if DEBUG=True. " "Refusing the invocation.",
                    "preflight",
                    "$",
                )
            ],
            warnings=[],
        )

    # Parse JSON input: the str | bytes arm, one decoder, never a raise.
    if isinstance(document, (str, bytes)):
        document, parse_issue = _parse_document(document)
        if parse_issue is not None:
            return GriftImportResult(
                success=False,
                grift_version="",
                import_mode=IMPORT_MODE,
                dangling_edge_mode=dangling_edge_mode,
                reference_time=reference_time.isoformat(),
                counts=GriftCounts(errors=1),
                imported_batches=[],
                skipped_batches=[],
                errors=[parse_issue],
                warnings=[],
            )

    # Extract grift_version before full validation (best effort).
    grift_version = ""
    if isinstance(document, dict):
        meta = document.get("metadata", {})
        if isinstance(meta, dict):
            grift_version = str(meta.get("grift_version", ""))

    preflight = _run_preflight(
        document,
        reference_time=reference_time,
        dangling_edge_mode=dangling_edge_mode,
        force_batches=force_batches_set,
    )

    # If any named force_batches didn't resolve to an existing batch in the
    # file, surface that explicitly — silent no-op would be confusing.
    if force_batches_set:
        file_batch_ids = {
            (batch.get("batch_entity") or {}).get("entity_id")
            for batch in (document.get("batches") if isinstance(document, dict) else []) or []
        }
        file_batch_ids.discard(None)
        missing = force_batches_set - file_batch_ids
        for mb in sorted(missing):
            preflight.issues.append(
                _issue(
                    "force_reimport_batch_not_found",
                    f"Requested force re-import of batch '{mb}' which is not present in the document.",
                    "preflight",
                    "$.batches",
                    batch_entity_id=mb,
                )
            )
            preflight.ok = False

    # Separate preflight issues into errors and warnings.
    # In permissive mode, dangling_edge issues are warnings (they just get skipped).
    def _is_error(issue: GriftIssue) -> bool:
        if issue.code == "dangling_edge" and dangling_edge_mode == "permissive":
            return False
        return issue.code in _ERROR_CODES

    errors: list[GriftIssue] = [i for i in preflight.issues if _is_error(i)]
    warnings: list[GriftIssue] = [i for i in preflight.issues if not _is_error(i)]

    if not preflight.ok:
        return GriftImportResult(
            success=False,
            grift_version=grift_version,
            import_mode=IMPORT_MODE,
            dangling_edge_mode=dangling_edge_mode,
            reference_time=reference_time.isoformat(),
            counts=GriftCounts(
                batches_skipped=len(preflight.batches_to_skip), errors=len(errors), warnings=len(warnings)
            ),
            imported_batches=[],
            skipped_batches=preflight.batches_to_skip,
            errors=errors,
            warnings=warnings,
        )

    # Execute each batch.
    imported_batches: list[GriftImportedBatch] = []
    exec_issues: list[GriftIssue] = []

    for batch_idx, batch_container in preflight.batches_to_import:
        summary, batch_issues = _execute_grift_batch(
            batch_container,
            batch_idx=batch_idx,
            dangling_edge_ids=preflight.dangling_edge_ids,
            actor=actor,
            reference_time=reference_time,
            dangling_edge_mode=dangling_edge_mode,
            force_batches=force_batches_set,
            sweep_strict=sweep_strict,
            purge=purge,
            parsed_removals=preflight.parsed_removals_by_idx.get(batch_idx),
            refs=preflight.resolved_refs.get(batch_container["batch_entity"]["entity_id"], {}),
            read_boundary=read_boundary,
        )
        imported_batches.append(summary)
        exec_issues.extend(batch_issues)

    # Single source of truth for hard-error classification across phases:
    # `_is_error` (defined above) is the canonical classifier — it consults
    # `_ERROR_CODES` AND applies the permissive-mode carve-out for
    # `dangling_edge` issues. Reusing the same helper for execution-phase
    # issues eliminates the prior duplicate frozenset that risked drifting
    # when new codes landed AND correctly treats execution-phase dangling-
    # edge "skipped in permissive" records as warnings, not errors.
    exec_errors = [i for i in exec_issues if _is_error(i)]
    exec_warnings = [i for i in exec_issues if not _is_error(i)]

    all_errors = errors + exec_errors
    all_warnings = warnings + exec_warnings

    # Batches that executed successfully. A force re-import that aborted via
    # --sweep-strict is counted as a failure (nothing landed) but still has
    # an entry in imported_batches for reporting.
    successfully_imported = [b for b in imported_batches if not b.sweep_strict_aborted and b.errors_count == 0]

    counts = GriftCounts(
        batches_imported=len(successfully_imported),
        batches_skipped=len(preflight.batches_to_skip),
        batches_force_reimported=sum(1 for b in successfully_imported if b.force_reimported),
        nodes_imported=sum(b.nodes_imported for b in imported_batches),
        edges_imported=sum(b.edges_imported for b in imported_batches),
        edges_skipped=sum(b.edges_skipped for b in imported_batches),
        entities_swept=sum(len(b.swept_entities) for b in imported_batches),
        entities_purged=sum(sum(1 for s in b.swept_entities if s.action == "purge") for b in imported_batches),
        sweep_skipped=sum(len(b.sweep_skipped) for b in imported_batches),
        entities_upserted=sum(len(b.upserted_entities) for b in imported_batches),
        edges_deleted=sum(b.edges_deleted for b in imported_batches),
        nodes_deleted=sum(b.nodes_deleted for b in imported_batches),
        edges_purged=sum(b.edges_purged for b in imported_batches),
        nodes_purged=sum(b.nodes_purged for b in imported_batches),
        removals_skipped=sum(b.removals_skipped for b in imported_batches),
        edges_retired=sum(b.edges_retired for b in imported_batches),
        nodes_retired=sum(b.nodes_retired for b in imported_batches),
        retirements_skipped=sum(b.retirements_skipped for b in imported_batches),
        edges_proposed=sum(b.edges_proposed for b in imported_batches),
        errors=len(all_errors),
        warnings=len(all_warnings),
    )

    return GriftImportResult(
        success=len(all_errors) == 0,
        grift_version=grift_version,
        import_mode=IMPORT_MODE,
        dangling_edge_mode=dangling_edge_mode,
        reference_time=reference_time.isoformat(),
        counts=counts,
        imported_batches=imported_batches,
        skipped_batches=preflight.batches_to_skip,
        errors=all_errors,
        warnings=all_warnings,
    )
