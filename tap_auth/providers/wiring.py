"""Build allauth's SOCIALACCOUNT_PROVIDERS from TAP provider configs.

This is the bridge between TAP's declarative provider config and allauth. It runs
at settings-build time (so allauth sees the providers from first request) and is
also used by boot's provider-validation phase (req-tap-auth-boot). Secrets are
resolved into memory here and embedded in the allauth APPS list — which lives in
*settings*, never the DB (req-tap-auth-providers-3: allauth's SocialApp DB row
would persist the secret; the settings APPS path keeps it in memory only).

``build_socialaccount_providers`` is intentionally tolerant of resolution
failures at settings-build time when ``critical_for_boot`` is False: a provider
whose live IdP is unavailable should not prevent the process from importing
settings (req-tap-auth-providers-6). A *malformed* static config or a missing
secret on a ``critical_for_boot`` provider raises — that is a deploy-time error
the boot phase surfaces loudly. The richer offline/live self-test gating belongs
to the boot phase (increment 4); this function only does enough to assemble
allauth settings.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any

from django.conf import settings

from tap_auth.providers.base import ProviderConfig, ProviderError
from tap_auth.providers.registry import UnknownProviderType, get_provider

logger = logging.getLogger(__name__)


def build_socialaccount_providers(
    raw_configs: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return a SOCIALACCOUNT_PROVIDERS dict for the given provider configs.

    Each config is parsed, its provider implementation resolved, its secret
    resolved, and its allauth APPS entry built. Entries are grouped by the
    ALLAUTH ENGINE the provider declares (``Provider.allauth_provider``), e.g.::

        {"openid_connect": {"APPS": [...]}, "github": {"APPS": [...]}}

    That grouping key used to be the module constant ``openid_connect``, which was
    correct only while google_oidc was the sole provider type: a github_oauth entry
    filed there would have been handed to allauth's OIDC engine, which reads
    ``app.settings["server_url"]`` and would have raised KeyError on the first login
    — a runtime failure for a configuration mistake the wiring made, not the
    operator. The engine is now a fact each provider states about itself
    (req-tap-auth-github-oauth).

    Empty input → empty dict (no providers configured; local auth only).
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in raw_configs:
        config = ProviderConfig.from_dict(raw)
        try:
            provider = get_provider(config.type)
        except UnknownProviderType:
            # Unknown types fail immediately (req-tap-auth-providers).
            raise
        try:
            secrets = provider.resolve_secrets(config)
            entry = provider.build_allauth_settings(config, secrets)
        except ProviderError:
            if config.critical_for_boot:
                # A critical provider that cannot be assembled is a hard error.
                raise
            # Non-critical: log loudly and skip — login via this provider is
            # unavailable, but the process still starts (req-tap-auth-providers-6).
            logger.warning(
                "[9c88] non-critical provider %s could not be assembled; login unavailable",
                config.id,
            )
            continue
        grouped.setdefault(provider.allauth_provider, []).append(entry)

    return {engine: {"APPS": apps} for engine, apps in grouped.items()}


def iter_provider_configs() -> list[ProviderConfig]:
    """Parse ``settings.TAP_AUTH_PROVIDERS`` into ProviderConfig objects."""
    return [ProviderConfig.from_dict(raw) for raw in (getattr(settings, "TAP_AUTH_PROVIDERS", []) or [])]


def get_provider_config(provider_id: str) -> ProviderConfig | None:
    """Return the configured ProviderConfig with id ``provider_id``, or None.

    Used by the social adapter to resolve the access policy for an incoming
    login by its allauth provider id. That equals the TAP provider id for EVERY
    engine, not just openid_connect: allauth stamps ``SocialAccount.provider`` from
    ``Provider.sub_id``, which is ``app.provider_id or app.provider`` — so as long
    as each APPS entry carries ``provider_id``, the lookup key is the TAP id.
    A provider whose ``build_allauth_settings`` omitted ``provider_id`` would stamp
    the engine name instead and silently miss its own policy here, which
    ``pre_social_login`` turns into a denial ("this login provider is not
    configured") rather than an open door."""
    for config in iter_provider_configs():
        if config.id == provider_id:
            return config
    return None
