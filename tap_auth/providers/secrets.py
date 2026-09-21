"""Resolve auth provider secrets from the mounted ``*.secret.json`` store.

Provider client credentials live in the same ``*.secret.json`` files as the rest
of TAP's runtime secrets (one shared, gitignored, bind-mounted store), under the
``auth`` scope. File discovery and envelope shape come from the app-neutral
``tap.runtime_secrets`` resolver (shared with tap_cares, so there is one resolver
not two). tap_auth still resolves directly here rather than through the
*tap-cares registry*, because allauth settings are built at settings-import time
— before ``tap_cares.ready()`` loads that registry, and tap_auth must not depend
on the tap_cares app. tap_auth owns the OAuth-client data-block schema
(``tap_auth/schemas/oauth_client_secret.schema.json``) and validates against it
here. ONE schema and ONE resolver cover both provider types: an OIDC client
credential and a plain OAuth 2.0 one carry the same two fields, and the envelope's
``kind`` (``oidc_client`` / ``oauth2_client``) names which protocol issued it.

Secret material is returned in memory only and never logged in full
(req-tap-auth-providers-3 / the threat model in req-tap-auth-capabilities).
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

from django.conf import settings
from jsonschema import Draft202012Validator

from tap.jsonfiles import JsonFileError, load_json_file, load_schema
from tap.runtime_secrets import RuntimeSecretError, find_secret_file
from tap.secrets_root import resolve as resolve_secrets_root
from tap_auth.providers.base import ProviderError

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "oauth_client_secret.schema.json"


@functools.lru_cache(maxsize=1)
def _oauth_client_validator() -> Draft202012Validator:
    # Multi-error reporting (iter_errors) is kept deliberately here — a malformed
    # provider secret should surface every problem at once (req-tap-json-adoption).
    return Draft202012Validator(load_schema(_SCHEMA_PATH))


def _secrets_root() -> Path:
    # Prefer the live settings (so test fixtures overriding TAP_SECRETS_ROOT
    # work), but fall back to the canonical settings-free lookup
    # (tap.secrets_root, req-tap-cares-secrets-root-resolution) when settings is
    # not yet configured — build_socialaccount_providers runs DURING tap.settings
    # import, where the lazy django.conf.settings object is mid-initialization and
    # its attributes are not reliably accessible. Unset ⇒ raise: a provider
    # without a resolvable store is a hard error (this edge's unset-policy).
    if settings.configured:
        # settings.py always defines it (req-tap-cares-secrets-root-resolution),
        # so a defensive default here would only mask a broken settings module.
        root = settings.TAP_SECRETS_ROOT
        if root:
            return Path(root)
    resolved = resolve_secrets_root()
    if resolved is None:
        raise ProviderError("TAP_SECRETS_ROOT is not configured; cannot resolve provider secrets")
    return resolved


def resolve_oauth_client_secret(key: str, *, scope: str = "auth") -> dict[str, str]:
    """Return ``{'client_id': ..., 'client_secret': ...}`` for an OAuth provider.

    Discovers the file via the shared ``tap.runtime_secrets`` resolver, then
    validates the whole secret file against the OAuth-client schema (so a
    malformed secret fails loud and specific, not as a mystery login error) and
    returns only the ``data`` block. Used by every provider type — OIDC and plain
    OAuth 2.0 alike — so the client-credential envelope has one reader.
    """
    try:
        path = find_secret_file(_secrets_root(), scope, key)
    except RuntimeSecretError as exc:
        raise ProviderError(str(exc)) from exc
    try:
        doc: dict[str, Any] = load_json_file(path)
    except JsonFileError as exc:
        raise ProviderError(f"secret {scope}:{key} ({path.name}) is unreadable/invalid JSON: {exc}") from exc
    errors = sorted(_oauth_client_validator().iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        detail = "; ".join(f"{list(e.path) or '<root>'}: {e.message}" for e in errors)
        raise ProviderError(f"secret {scope}:{key} ({path.name}) failed oauth client schema: {detail}")
    data = doc["data"]
    return {"client_id": str(data["client_id"]), "client_secret": str(data["client_secret"])}


def secret_exists(key: str, *, scope: str = "auth") -> bool:
    """True if a resolvable secret file exists for ``scope:key`` (no validation)."""
    try:
        find_secret_file(_secrets_root(), scope, key)
    except RuntimeSecretError, ProviderError:
        return False
    return True
