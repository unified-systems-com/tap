"""Consumer-side secret validation.

req-tap-cares-secrets-validation (spec-tap-cares-secrets.md).

`require_secret_kind(secret, expected_kind, *, data_schema=...)` is the
typed entry point a consumer (collector, receiver, emitter, action) calls
right after `resolve_secret(ref)` to assert that the resolved secret
matches the kind and shape the consumer requires.

tap-cares v0 deliberately does not centralize secret schemas — plugins
will define many kinds with different shapes. This helper accepts a JSON
schema supplied by the consumer so consumer code can validate `secret.data`
against the schema it already maintains alongside the capability.

Validation failures surface as `SecretValidationError` with a structured,
redacted context payload so the run record can preserve diagnostic detail
without leaking secret material.
"""

from __future__ import annotations

from typing import Any

import jsonschema

from tap.jsonfiles import jsonschema_validate
from tap_cares.exceptions import SecretValidationError
from tap_cares.secrets.models import Secret
from tap_cares.secrets.redaction import redact


def require_secret_kind(
    secret: Secret,
    expected_kind: str,
    *,
    data_schema: dict[str, Any] | None = None,
) -> None:
    """Assert that `secret` matches `expected_kind` and (optionally) `data_schema`.

    Args:
        secret: The resolved Secret returned by `resolve_secret(ref)`.
        expected_kind: The exact `kind` string the consumer expects.
        data_schema: Optional JSON Schema describing `secret.data`. When
            provided, validated via `jsonschema.validate`; on failure the
            schema path is preserved in the error context but the offending
            value is redacted.

    Raises:
        SecretValidationError: on kind mismatch or schema validation failure.
    """
    if secret.kind != expected_kind:
        raise SecretValidationError(
            f"Secret {secret.ref.qualified!r} has kind {secret.kind!r}, " f"expected {expected_kind!r}."
        )

    if data_schema is None:
        return

    try:
        jsonschema_validate(dict(secret.data), data_schema)
    except jsonschema.ValidationError as exc:
        # Preserve the schema path and the validator that failed; the
        # offending instance value is dropped on purpose. Errors travel
        # through run records, so the message must be safe to persist.
        path = list(exc.absolute_path)
        raise SecretValidationError(
            f"Secret {secret.ref.qualified!r} (kind {secret.kind!r}) failed schema "
            f"validation at path {path!r}: {exc.validator} = {redact(exc.validator_value)}"
        ) from None
