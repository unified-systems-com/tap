"""Startup-time `*.secret.json` loader.

TAP-IMPLEMENTS: req-tap-cares-secrets-resilient-load@a89149ed20fe/1b28490bcc1a (derivation) —
    the accumulate-failures, never-crash startup load lives here.

TAP-IMPLEMENTS: req-tap-cares-secrets-rotation@59577e68435b/1b28490bcc1a (derivation) — the
    read-once-per-process-at-startup contract is this loader's behavior; restart to rotate.

req-tap-cares-secrets-files, req-tap-cares-secrets-shape
(spec-tap-cares-secrets.md).

`load_secrets(root, *, registry=...)` recursively scans `root` for files
whose basename matches `<key>.secret.json`, parses each one, and registers
the resulting `Secret` in the supplied registry. Directories are
non-semantic — they exist only for operator organization. Dotfiles and
non-matching suffixes are ignored.

#### Failure modes (req-tap-cares-secrets-resilient-load)

Loading is *resilient*, not crash-fast: a single bad file must never take
down `django.setup()` and crash-loop the instance. Valid files register;
each bad file is recorded as a `SecretLoadFailure` in the supplied report.
Three readers consume that one report — the `tap_health` secrets probe (run via
`manage.py health` / the internal service), the `tap_cares` system check, and
boot — so the failure surfaces loudly without killing the process or the
diagnostic surfaces you'd use to fix it.

- **Missing or empty root** → silent no-op. TAP installs without runtime
  secrets are normal; capability runs that need a missing secret fail at
  run time via `resolve_secret`, not at startup
  (req-tap-cares-secrets-redaction-3).

- **Non-directory root** → `SecretLoadError`. This is a gross mount/deploy
  misconfiguration of the root itself (not a per-file fault) and still
  raises.

- **Malformed JSON, missing/typed-wrong field, basename ≠ JSON key,
  invalid scope/key token, duplicate `scope:key`** → recorded as a
  `SecretLoadFailure` (not raised). The structural reason and the file's
  `required_for_boot` flag travel with the record. A failure whose file
  declared `required_for_boot: true` is *blocking* — it fails the build
  (system check `Error`) and reports `unhealthy` from the health secrets probe;
  otherwise it *degrades* (system check `Warning`, health probe `degraded`).

A capability that needs an absent-or-degraded secret still fails at run time
via `resolve_secret` with a structured, redacted error — the malformed file
behaves like an absent one plus a loud health/check warning.

Tests pass `tmp_path`-backed `registry=` and `report=` arguments so the
production `secret_registry` / `secret_load_report` are never touched.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from tap.jsonfiles import JsonFileError, discover_json_files, load_json_file
from tap.registry import ScopedRegistry
from tap.runtime_secrets import SECRET_SUFFIX, RuntimeSecretError, load_secret_envelope
from tap_cares.exceptions import (
    InvalidSecretRegistryKeyError,
    SecretLoadError,
)
from tap_cares.secrets.models import Secret, SecretLoadFailure, SecretRef, freeze_mapping
from tap_cares.secrets.registry import SecretLoadReport, secret_load_report, secret_registry

logger = logging.getLogger(__name__)

# The envelope shape (SECRET_SUFFIX, required fields, field-type validation) is
# owned by the app-neutral resolver in `tap/runtime_secrets.py`, shared with
# tap_auth. tap_cares keeps the policy on top: registry registration, the
# resilient-load report, basename/key matching, and `required_for_boot`.

# Opt-in metadata flag: when true, a file that fails to load is *blocking*
# (fails the build / 503s health) rather than merely degrading the instance.
# A boolean — not an enum — so its full meaning is visible at the callsite.
REQUIRED_FOR_BOOT_KEY = "required_for_boot"


def load_secrets(
    root: Path | str | None,
    *,
    registry: ScopedRegistry[Secret] | None = None,
    report: SecretLoadReport | None = None,
) -> list[SecretRef]:
    """Scan `root` and register every valid `<key>.secret.json` file found.

    Resilient by design: a structurally bad file is recorded in `report` and
    skipped, never raised, so one bad secret cannot crash-loop startup
    (req-tap-cares-secrets-resilient-load). Valid files register normally.

    Args:
        root: Directory to scan. If None, missing, or empty, the loader logs
            and returns an empty list — TAP starts normally.
        registry: Target registry. Defaults to the process-wide
            `secret_registry`; tests pass an isolated instance.
        report: Failure report to populate. Defaults to the process-wide
            `secret_load_report`; tests pass an isolated instance. It is
            reset at the start of every call.

    Returns:
        The list of SecretRefs registered, in load order. Recorded failures
        are available on `report.failures` (and `.blocking` / `.degraded`).

    Raises:
        SecretLoadError: only when `root` exists but is not a directory — a
            gross mount/deploy misconfiguration of the root itself, distinct
            from any per-file fault. Per-file faults are recorded, not raised.
    """
    target = registry if registry is not None else secret_registry
    failures = report if report is not None else secret_load_report
    failures.reset()

    if root is None:
        logger.info("[f769] tap-cares secrets: no root configured; skipping load.")
        return []

    root_path = Path(root)
    if not root_path.exists():
        logger.info("[eb76] tap-cares secrets: root %s does not exist; skipping load.", root_path)
        return []
    if not root_path.is_dir():
        raise SecretLoadError(f"tap-cares secrets root {root_path!s} exists but is not a directory.")

    loaded: list[SecretRef] = []
    # discover_json_files sorts deterministically and skips dotfiles/non-files
    # (req-tap-json-discovery); the `secret` role keys the `*.secret.json` glob.
    for path in discover_json_files(root_path, role="secret", recursive=True):
        try:
            secret = _load_secret_file(path)
        except SecretLoadError as exc:
            failures.failures.append(_failure_from_path(path, str(exc)))
            logger.warning("[b3a1] tap-cares secrets: skipping malformed file %s: %s", path, exc)
            continue
        try:
            target.register(secret.ref.key, secret, scope=secret.ref.scope)
        except InvalidSecretRegistryKeyError as exc:
            failures.failures.append(_failure_from_secret(secret, path, str(exc)))
            logger.warning("[c4d2] tap-cares secrets: skipping file with invalid token %s: %s", path, exc)
            continue
        except Exception as exc:
            # ScopedRegistry raises ImproperlyConfigured on duplicate keys.
            reason = f"Duplicate secret {secret.ref.qualified!r}: {exc}"
            failures.failures.append(_failure_from_secret(secret, path, reason))
            logger.warning("[d644] tap-cares secrets: skipping duplicate %s from %s", secret.ref.qualified, path)
            continue
        loaded.append(secret.ref)

    blocking = len(failures.blocking)
    degraded = len(failures.degraded)
    logger.info(
        "[a0f2] tap-cares secrets: loaded %d secret(s) from %s (%d blocking failure(s), %d degraded): %s.",
        len(loaded),
        root_path,
        blocking,
        degraded,
        ", ".join(sorted(ref.qualified for ref in loaded)) or "(none)",
    )
    return loaded


def _load_secret_file(path: Path) -> Secret:
    """Parse `path` and return a Secret. Raises SecretLoadError on any problem.

    Envelope discovery/validation is delegated to the app-neutral resolver; the
    tap_cares-specific policy layered on top is the `required_for_boot` boolean
    check, the basename/key match (req-tap-cares-secrets-files-5), and wrapping
    the result in a registry-ready `Secret`.
    """
    try:
        envelope = load_secret_envelope(path)
    except RuntimeSecretError as exc:
        raise SecretLoadError(str(exc)) from None

    metadata = envelope.metadata
    if REQUIRED_FOR_BOOT_KEY in metadata and not isinstance(metadata[REQUIRED_FOR_BOOT_KEY], bool):
        raise SecretLoadError(f"Secret file {path}: metadata.{REQUIRED_FOR_BOOT_KEY} must be a boolean when present.")

    _check_basename_matches_key(path, envelope.key)

    return Secret(
        ref=SecretRef(scope=envelope.scope, key=envelope.key),
        kind=envelope.kind,
        description=envelope.description,
        data=freeze_mapping(envelope.data),
        metadata=freeze_mapping(envelope.metadata),
        source_path=path,
    )


def _failure_from_secret(secret: Secret, path: Path, reason: str) -> SecretLoadFailure:
    """Build a failure record from a parsed Secret (duplicate / token cases)."""
    return SecretLoadFailure(
        path=str(path),
        reason=reason,
        required_for_boot=bool(secret.metadata.get(REQUIRED_FOR_BOOT_KEY, False)),
        qualified=secret.ref.qualified,
    )


def _failure_from_path(path: Path, reason: str) -> SecretLoadFailure:
    """Build a failure record for a file that failed before producing a Secret.

    Best-effort re-reads the file to recover `required_for_boot` and the
    `scope:key` — a malformed-but-parseable file (e.g. basename ≠ key) can
    still self-declare that its failure must block boot. Anything unreadable
    falls back to non-blocking with no qualified name.
    """
    qualified, required_for_boot = _peek_context(path)
    return SecretLoadFailure(
        path=str(path),
        reason=reason,
        required_for_boot=required_for_boot,
        qualified=qualified,
    )


def _peek_context(path: Path) -> tuple[str | None, bool]:
    """Best-effort extract (`scope:key`, required_for_boot) from a bad file.

    Never raises: a file too broken to parse yields ``(None, False)``. Only a
    literal ``true`` boolean counts as required-for-boot, so a malformed flag
    cannot accidentally escalate a failure to blocking.
    """
    try:
        payload = load_json_file(path)
    except JsonFileError, OSError:
        return None, False
    if not isinstance(payload, dict):
        return None, False
    scope = payload.get("scope")
    key = payload.get("key")
    qualified = f"{scope}:{key}" if isinstance(scope, str) and isinstance(key, str) else None
    metadata = payload.get("metadata")
    required = isinstance(metadata, dict) and metadata.get(REQUIRED_FOR_BOOT_KEY) is True
    return qualified, required


def _check_basename_matches_key(path: Path, key: str) -> None:
    """Enforce req-tap-cares-secrets-files-5: basename `<key>` matches JSON `key`."""
    name = path.name
    if not name.endswith(SECRET_SUFFIX):
        # rglob filter guarantees this, but keep the guard for explicit callers.
        raise SecretLoadError(f"Secret file {path} does not end with {SECRET_SUFFIX}.")
    basename_key = name[: -len(SECRET_SUFFIX)]
    if basename_key != key:
        raise SecretLoadError(
            f"Secret file {path} basename key {basename_key!r} does not match " f"JSON 'key' field {key!r}."
        )


__all__: list[Any] = ["load_secrets", "SECRET_SUFFIX", "REQUIRED_FOR_BOOT_KEY"]
