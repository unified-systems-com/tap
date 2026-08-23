"""Redaction helper for structured diagnostic data.

TAP-IMPLEMENTS: req-tap-cares-secrets-redaction@efffb824245f/97d2cccf2633 (derivation) — the
    recursive redaction helper every diagnostic surface routes through.

req-tap-cares-secrets-redaction (spec-tap-cares-secrets.md).

`redact(value)` returns a deep copy of `value` with the values of any
mapping key whose name contains a sensitive substring replaced with the
mask. Lists and tuples are recursed into; scalars pass through unchanged.

This is a defensive belt for diagnostics, exception context, and run
records. Capability code that already has a typed `Secret` in hand should
keep `secret.data` out of every log line it writes — the redactor only
catches what reaches it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Final

DEFAULT_MASK: Final[str] = "***REDACTED***"

# Substrings (case-insensitive) that mark a mapping key as sensitive.
# Adding patterns here is cheap; removing them is not — false negatives are
# the failure mode that matters.
_SENSITIVE_SUBSTRINGS: Final[tuple[str, ...]] = (
    "secret",
    "token",
    "password",
    "passwd",
    "private_key",
    "privatekey",
    "credential",
    "api_key",
    "apikey",
)


def _is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(needle in lowered for needle in _SENSITIVE_SUBSTRINGS)


def redact(
    value: Any,
    *,
    mask: str = DEFAULT_MASK,
    extra_sensitive: Iterable[str] = (),
) -> Any:
    """Recursively redact sensitive-looking values from `value`.

    Mappings: every key whose name contains a sensitive substring has its
    value replaced with `mask`; other values are recursed into.

    Lists and tuples: recursed into element-by-element; the original
    container type is preserved.

    Scalars: returned unchanged.

    `extra_sensitive` lets a caller add per-call sensitive substrings (e.g.
    a kind-specific field name) without mutating module state.
    """
    extras = tuple(s.lower() for s in extra_sensitive)

    def _sensitive(key: Any) -> bool:
        if _is_sensitive_key(key):
            return True
        if not isinstance(key, str) or not extras:
            return False
        lowered = key.lower()
        return any(needle in lowered for needle in extras)

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: (mask if _sensitive(k) else _walk(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(item) for item in node]
        if isinstance(node, tuple):
            return tuple(_walk(item) for item in node)
        return node

    return _walk(value)
