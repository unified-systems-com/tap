"""App-neutral runtime-secret file/envelope resolver (spec-tap-cares-secrets.md).

The single low-level mechanic for reading the shared ``*.secret.json`` store:
discover a file by ``scope``/``key`` and parse/validate the canonical envelope
(``scope``, ``key``, ``kind``, ``description``, ``data``, optional
``metadata``). It lives in ``tap/`` — next to ``tap/jsonfiles.py`` — rather than
in any ``tap_*`` app so that both ``tap_cares`` (the major secrets manager: it
owns the registry, resilient-load report, system check, and health probe) and
``tap_auth`` (which resolves provider client secrets at settings-import time,
before ``tap_cares.ready()`` runs) share one resolver instead of two divergent
copies.

This module is deliberately **import-safe**: it touches no Django settings at
import time and imports no ``tap_*`` app, so ``tap_auth`` can call it while the
settings module is still being built. Callers supply the secrets root; root
resolution (settings vs. env) and all policy (registry registration, blocking
escalation, ``required_for_boot`` semantics, consumer kind schemas) stay with
the calling app.

Errors raise the neutral :class:`RuntimeSecretError`; callers re-wrap it in
their own domain exception (``SecretLoadError`` / ``ProviderError``) per the
shared-loader pattern in ``req-tap-json-adoption``. The envelope-shape messages
match the field-validation contract the tap_cares loader has always emitted, so
the structural reason a caller records is unchanged.

Secret material is returned in memory only; this module never logs ``data``.

The manifest is always read from disk, but a manifest may route its *value* to an
external store via ``metadata.source`` (``req-tap-plugin-depres-sources``): the source-aware
entry point :func:`resolve_secret_envelope` dispatches to a registered provider in
``tap.secret_sources`` (disk built-in, cloud stores plugin-contributed) and returns the
fetched value in ``data``. Absent a source, behavior is unchanged (inline ``data``). The
provider layer is lazy-imported so the disk path — and core — stay cloud-SDK-free.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from tap.jsonfiles import JsonFileError, load_json_file
from tap.registry import validate_scoped_token
from tap.secret_naming import SECRET_EXAMPLE_SUFFIX, SECRET_SUFFIX

# The built-in source: the value is inline in the envelope's `data`. A manifest with no
# `metadata.source` (or this value) never leaves disk. Kept as a local constant — mirrors
# `tap.secret_sources.DISK_SOURCE` — so the common disk path imports no source machinery
# and this module stays standalone unless a secret actually routes to an external source.
_DISK_SOURCE = "disk"

# The canonical envelope fields every `*.secret.json` declares
# (req-tap-cares-secrets-shape). `metadata` is optional and validated separately.
REQUIRED_FIELDS = ("scope", "key", "kind", "description", "data")

# Default ceiling on a single secret file's size (req-tap-cares-secrets-size-guard),
# enforced before the file is trusted. A secret file may RAISE its own ceiling
# with `metadata.max_bytes` (e.g. a future collector that consumes a deliberately
# large secret); absent that field, 1 MiB guards the common case against an
# accidental or malicious oversize file. The mount is operator-controlled, so this
# catches dumb/accidental oversize, not a hostile multi-GB OOM — a pre-read
# absolute ceiling for that is the general `req-tap-json-size-guard`.
DEFAULT_SECRET_MAX_BYTES = 1024 * 1024  # 1 MiB


class RuntimeSecretError(Exception):
    """A secret file could not be discovered or its envelope is malformed.

    Neutral and app-independent: callers catch it and re-raise their own domain
    exception (``SecretLoadError`` in tap_cares, ``ProviderError`` in tap_auth).
    """


@dataclass(frozen=True)
class SecretEnvelope:
    """The validated, non-policy shape of one ``*.secret.json`` file.

    Carries the canonical fields plus the source path. ``data`` and ``metadata``
    are returned as plain mappings — freezing/registration is the caller's job
    (tap_cares wraps these in a ``Secret``). ``__repr__`` omits ``data`` and
    ``metadata`` so an envelope interpolated into a log line cannot leak material.
    """

    scope: str
    key: str
    kind: str
    description: str
    data: Mapping[str, Any]
    metadata: Mapping[str, Any]
    source_path: Path

    @property
    def qualified(self) -> str:
        """The ``scope:key`` string used for registry lookup and diagnostics."""
        return f"{self.scope}:{self.key}"

    def __repr__(self) -> str:
        return f"SecretEnvelope(qualified={self.qualified!r}, kind={self.kind!r}, source={self.source_path})"


def parse_secret_envelope(payload: Any, path: Path) -> SecretEnvelope:
    """Validate an in-memory secret ``payload`` and return its envelope.

    Validates only the canonical envelope shape — the required fields and their
    types. App-specific policy (basename/key match, ``required_for_boot``
    boolean semantics, consumer kind schemas) is intentionally left to callers.

    Raises:
        RuntimeSecretError: on any structural problem, with a message whose
            substring matches the long-standing tap_cares field-validation
            contract (so a caller recording the reason is unchanged).
    """
    if not isinstance(payload, dict):
        raise RuntimeSecretError(f"Secret file {path} must contain a JSON object, got {type(payload).__name__}.")

    missing = [field for field in REQUIRED_FIELDS if field not in payload]
    if missing:
        raise RuntimeSecretError(f"Secret file {path} is missing required field(s): {missing}.")

    scope = payload["scope"]
    key = payload["key"]
    kind = payload["kind"]
    description = payload["description"]
    data = payload["data"]
    metadata = payload.get("metadata", {})

    if not isinstance(scope, str) or not isinstance(key, str):
        raise RuntimeSecretError(f"Secret file {path}: scope and key must be strings.")
    # Enforce the canonical scoped-token grammar on EVERY read path (pre-boot
    # included), so a malformed scope/key fails loud and identically everywhere
    # instead of one path silently diverging (the two-loader drift this module
    # and the tap_cares registries now share one grammar to prevent).
    validate_scoped_token(scope, error_cls=RuntimeSecretError, label="secret scope")
    validate_scoped_token(key, error_cls=RuntimeSecretError, label="secret key")
    if not isinstance(kind, str) or not kind:
        raise RuntimeSecretError(f"Secret file {path}: kind must be a non-empty string.")
    if not isinstance(description, str) or not description.strip():
        raise RuntimeSecretError(f"Secret file {path}: description must be a non-empty string.")
    if not isinstance(data, dict):
        raise RuntimeSecretError(f"Secret file {path}: data must be a JSON object.")
    if not isinstance(metadata, dict):
        raise RuntimeSecretError(f"Secret file {path}: metadata must be a JSON object when present.")
    if "max_bytes" in metadata:
        declared = metadata["max_bytes"]
        if isinstance(declared, bool) or not isinstance(declared, int) or declared <= 0:
            raise RuntimeSecretError(f"Secret file {path}: metadata.max_bytes must be a positive integer when present.")
    # Source-routing (req-tap-plugin-depres-sources-7): a manifest may route its VALUE to an
    # external source. `source` names the provider (absent/"disk" => inline `data`);
    # `source_ref` is that provider's opaque locator. Validate shape here so a malformed
    # routing fails loud at parse, identically on every read path.
    if "source" in metadata:
        source = metadata["source"]
        if not isinstance(source, str) or not source:
            raise RuntimeSecretError(f"Secret file {path}: metadata.source must be a non-empty string when present.")
    if "source_ref" in metadata and not isinstance(metadata["source_ref"], dict):
        raise RuntimeSecretError(f"Secret file {path}: metadata.source_ref must be a JSON object when present.")

    return SecretEnvelope(
        scope=scope,
        key=key,
        kind=kind,
        description=description,
        data=data,
        metadata=metadata,
        source_path=path,
    )


def _stat_size(path: Path) -> int:
    """File size in bytes, as a neutral :class:`RuntimeSecretError` on failure."""
    try:
        return path.stat().st_size
    except OSError as exc:
        raise RuntimeSecretError(f"cannot stat secret file {path}: {exc}") from exc


def _declared_max_bytes(metadata: Mapping[str, Any]) -> int | None:
    """The file's own ``metadata.max_bytes`` override, or None when unset.

    ``parse_secret_envelope`` already rejects a malformed value, so by here it is
    either a positive int or absent.
    """
    declared = metadata.get("max_bytes")
    return declared if isinstance(declared, int) and not isinstance(declared, bool) and declared > 0 else None


def load_secret_envelope(path: Path, *, default_max_bytes: int = DEFAULT_SECRET_MAX_BYTES) -> SecretEnvelope:
    """Read ``path`` and return its validated, size-checked :class:`SecretEnvelope`.

    TAP-IMPLEMENTS: req-tap-cares-secrets-size-guard@a6c58fd3926e/e384c8471039 (enforcement)
        — the pre-trust size rejection (DEFAULT_SECRET_MAX_BYTES) happens here.

    Enforces the size guard (req-tap-cares-secrets-size-guard): the file must be
    no larger than ``default_max_bytes`` (1 MiB) unless it raises its own ceiling
    via ``metadata.max_bytes``; the effective limit is the larger of the two. This
    is the bulk-load path the tap_cares loader uses, so the per-file override is
    honored for every loaded secret.

    Raises:
        RuntimeSecretError: on an unreadable file, malformed JSON, a structural
            envelope problem, or a file over its effective size limit.
    """
    try:
        payload = load_json_file(path)
    except JsonFileError as exc:
        raise RuntimeSecretError(str(exc)) from None
    envelope = parse_secret_envelope(payload, path)
    limit = max(default_max_bytes, _declared_max_bytes(envelope.metadata) or 0)
    size = _stat_size(path)
    if size > limit:
        raise RuntimeSecretError(
            f"secret file {path} is {size} bytes, over the {limit}-byte limit; "
            f"raise it with metadata.max_bytes if this is intentional."
        )
    return envelope


def find_secret_file(root: Path, scope: str, key: str, *, max_bytes: int = DEFAULT_SECRET_MAX_BYTES) -> Path:
    """Locate the ``<key>.secret.json`` whose envelope declares ``scope``/``key``.

    Directories under the root are organizational only
    (req-tap-cares-secrets-files-4), so we match the basename glob then confirm
    the declared ``scope``/``key`` inside. Returns the first deterministic match.

    Each candidate is size-guarded against ``max_bytes`` (default 1 MiB) *before*
    it is read, so discovery cannot slurp an oversized file. This path (tap_auth's
    small reference secrets) applies a fixed cap; the per-file ``metadata.max_bytes``
    override is honored by :func:`load_secret_envelope`, the bulk-load path a
    deliberately large secret would use.

    Raises:
        RuntimeSecretError: when the root is not a directory, a candidate is
            oversized or unreadable, or no file declares the requested
            ``scope``/``key``.
    """
    if not root.is_dir():
        raise RuntimeSecretError(f"secrets root {root} does not exist; cannot resolve {scope}:{key}")
    for path in sorted(root.rglob(f"{key}{SECRET_SUFFIX}")):
        size = _stat_size(path)
        if size > max_bytes:
            raise RuntimeSecretError(f"secret file {path} is {size} bytes, over the {max_bytes}-byte limit.")
        try:
            doc = load_json_file(path)
        except JsonFileError as exc:
            raise RuntimeSecretError(f"secret file {path} is unreadable/invalid JSON: {exc}") from exc
        if isinstance(doc, dict) and doc.get("scope") == scope and doc.get("key") == key:
            return path
    raise RuntimeSecretError(
        f"no secret file found for {scope}:{key} under {root} "
        f"(expected a '{key}{SECRET_SUFFIX}' with scope='{scope}', key='{key}')"
    )


def _apply_source(envelope: SecretEnvelope) -> SecretEnvelope:
    """Resolve the envelope's VALUE through its named source, or return it unchanged.

    The manifest is always disk-resident; only the value may live elsewhere. A manifest
    with no ``metadata.source`` (or ``source == "disk"``) keeps its inline ``data`` — the
    built-in disk source, unchanged. A named source dispatches to a registered provider
    (``tap.secret_sources``); the fetched value replaces ``data``. The provider layer is
    **lazy-imported** so the disk path pulls in no source machinery and core stays
    cloud-SDK-free until a secret actually routes to an external store. A source failure
    is re-wrapped as :class:`RuntimeSecretError` so callers keep catching one type.
    """
    source = envelope.metadata.get("source")
    if not source or source == _DISK_SOURCE:
        return envelope
    from tap.secret_sources import SecretSourceError, resolve_sourced_data  # lazy: no cloud SDK in core

    ref = envelope.metadata.get("source_ref", {})
    try:
        data = resolve_sourced_data(str(source), ref, scope=envelope.scope, key=envelope.key)
    except SecretSourceError as exc:
        raise RuntimeSecretError(str(exc)) from exc
    return replace(envelope, data=dict(data))


def resolve_secret_envelope(
    root: Path, scope: str, key: str, *, default_max_bytes: int = DEFAULT_SECRET_MAX_BYTES
) -> SecretEnvelope:
    """Discover, load, and source-resolve the envelope for ``scope``/``key`` under ``root``.

    This is the **source-aware** resolve entry point: after reading the disk manifest it
    dispatches through :func:`_apply_source`, so a secret routed to an external store
    (``metadata.source``) returns its fetched value transparently. Callers that want the
    raw on-disk manifest without source resolution use :func:`load_secret_envelope`.
    """
    path = find_secret_file(root, scope, key, max_bytes=default_max_bytes)
    envelope = load_secret_envelope(path, default_max_bytes=default_max_bytes)
    return _apply_source(envelope)


# --------------------------------------------------------------------------- #
# leak guard (req-tap-cares-secrets-leak-guard)
# --------------------------------------------------------------------------- #

# Path segments that mark test scaffolding, exempt from the envelope-content
# check (a fixture may legitimately embed an example envelope). Mirrors the
# `_TEST_SEGMENTS` exemption in `tap/jsonfiles.py`.
_LEAK_TEST_SEGMENTS: frozenset[str] = frozenset({"tests", "fixtures", "expected", "snapshots"})

# `SECRET_EXAMPLE_SUFFIX` (tap.secret_naming, imported above) marks the explicit,
# non-secret template: a `<key>.secret.example.json` is a checked-in placeholder,
# never real material, so it is allowed to be both committed and envelope-shaped.


@dataclass(frozen=True)
class SecretLeak:
    """One file that leaks secret material into version control."""

    path: str
    reason: str


def _looks_like_envelope(payload: Any) -> bool:
    """True if ``payload`` is the canonical secret envelope (scope+key+kind+data).

    A schema file (`properties`/`type` keys) or a boot/grift document does not
    carry all four envelope fields at the top level, so the signature is
    high-specificity — a real secret renamed to dodge the `.secret.json` suffix.
    """
    return isinstance(payload, dict) and all(field in payload for field in REQUIRED_FIELDS)


def scan_paths_for_secret_leaks(repo_root: Path, rel_paths: Iterable[str]) -> list[SecretLeak]:
    """Find files that leak secret material into the repository tree.

    Pure over ``rel_paths`` (repo-relative `.json` files) so it is unit-testable;
    the enforcement test supplies the walked file list. Flags:

    1. any ``*.secret.json`` (a real secret file), and
    2. any ``*.json`` whose content is the canonical secret envelope, outside
       test scaffolding and ``*.secret.example.json`` templates (a secret renamed
       to evade the suffix).

    The caller is responsible for excluding the live secrets mount and
    vendored/cache dirs so the legitimate off-grid store is never passed in.
    """
    leaks: list[SecretLeak] = []
    for rel in rel_paths:
        rel_path = Path(rel)
        name = rel_path.name
        if name.endswith(SECRET_EXAMPLE_SUFFIX):
            continue  # explicit non-secret template
        if name.endswith(SECRET_SUFFIX):
            leaks.append(SecretLeak(path=rel, reason="committed *.secret.json file"))
            continue
        if not name.endswith(".json"):
            continue
        if _LEAK_TEST_SEGMENTS & set(rel_path.parts):
            continue  # fixtures may embed example envelopes
        try:
            payload = load_json_file(repo_root / rel_path)
        except JsonFileError:
            continue  # unparseable / unreadable is not this guard's concern
        if _looks_like_envelope(payload):
            leaks.append(SecretLeak(path=rel, reason="canonical secret envelope in a non-.secret.json file"))
    return leaks


__all__ = [
    "SECRET_SUFFIX",
    "SECRET_EXAMPLE_SUFFIX",
    "REQUIRED_FIELDS",
    "DEFAULT_SECRET_MAX_BYTES",
    "RuntimeSecretError",
    "SecretEnvelope",
    "parse_secret_envelope",
    "load_secret_envelope",
    "find_secret_file",
    "resolve_secret_envelope",
    "SecretLeak",
    "scan_paths_for_secret_leaks",
]
