"""tap_cares secret registry.

TAP-IMPLEMENTS: req-tap-cares-secrets-registry@d7c79a437827/f4f8d7e0d194 (derivation) — the
    in-process ScopedRegistry the loader populates and consumers resolve from.

req-tap-cares-secrets-registry (spec-tap-cares-secrets.md).

`secret_registry` is a `ScopedRegistry[Secret]` populated at Django startup
by `tap_cares.secrets.loader.load_secrets`. Consumer code should not touch
the registry directly — resolve secrets via `resolve_secret(ref)` so the
SecretRef boundary stays the single typed entry point
(req-tap-cares-secrets-registry-4).

Scope/key token format is the canonical scoped-registry grammar in
`tap.registry` (`SCOPED_TOKEN_PATTERN`): ASCII alphanumerics plus `_.-`, must
start with an alphanumeric, no `/`. The same validator runs on register() and
get() so malformed inputs fail loud at the boundary instead of mid-lookup, and
it is shared with the collector registry and the pre-boot secret resolver so the
grammar cannot drift across read paths.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from tap.caller_identity import calling_plugin_slug
from tap.logging_signals import concern
from tap.plugin_source_auth import SOURCE_SECRET_SCOPE
from tap.registry import ScopedRegistry, validate_scoped_token
from tap_cares.exceptions import (
    InvalidSecretRegistryKeyError,
    SecretNotFoundError,
)
from tap_cares.secrets.models import Secret, SecretLoadFailure, SecretRef

logger = logging.getLogger(__name__)


def _validate_secret_token(value: str) -> None:
    """Reject malformed scope or key tokens at the registry boundary.

    Delegates to the canonical grammar in `tap.registry`, shared with the
    collector registry and the pre-boot resolver.
    """
    validate_scoped_token(value, error_cls=InvalidSecretRegistryKeyError, label="secret registry")


secret_registry: ScopedRegistry[Secret] = ScopedRegistry(
    "secret",
    validate_key=_validate_secret_token,
    validate_scope=_validate_secret_token,
    title="Secret Registry",
    description="Scoped registry of tap_cares runtime secrets loaded from mounted files.",
)


@dataclass
class SecretLoadReport:
    """Process-wide record of the last `load_secrets` run's failures.

    Populated by the loader at startup (one load) and read by three consumers
    (the `tap_health` secrets probe, the `tap_cares` system check, and boot).
    A failed file degrades the instance rather than crash-looping startup; a
    failure whose file declared `required_for_boot: true` is *blocking* and
    escalates from degrade to fail-the-build / fail-health
    (req-tap-cares-secrets-resilient-load).
    """

    failures: list[SecretLoadFailure] = field(default_factory=list)

    def reset(self) -> None:
        """Clear recorded failures so a re-load starts from a clean slate."""
        self.failures.clear()

    @property
    def blocking(self) -> list[SecretLoadFailure]:
        """Failures that must block boot / fail the build (required_for_boot)."""
        return [f for f in self.failures if f.required_for_boot]

    @property
    def degraded(self) -> list[SecretLoadFailure]:
        """Failures that degrade the instance but do not block boot."""
        return [f for f in self.failures if not f.required_for_boot]


# Process-wide singleton. Tests pass an isolated report= to load_secrets so
# this is never mutated under test (mirrors the registry= convention).
secret_load_report = SecretLoadReport()


def resolve_secret(ref: SecretRef) -> Secret:
    """Return the registered Secret for `ref`.

    Raises:
        InvalidSecretRegistryKeyError: if `ref.scope` or `ref.key` is malformed.
        SecretNotFoundError: if no secret is registered for `scope:key`.
    """
    _concern_on_install_scope_access(ref)
    try:
        return secret_registry.get(ref.key, scope=ref.scope)
    except KeyError:
        raise SecretNotFoundError(
            f"No secret registered for {ref.qualified!r}. " f"Registered: {secret_registry.keys()}"
        ) from None


def _concern_on_install_scope_access(ref: SecretRef) -> None:
    """Detective `CONCERN` tripwire: a plugin resolving the install-system scope.

    The first instance of the plugin-safety `CONCERN` discipline
    (`spec-security-posture.md`, `req-sec-concern-gaps`). We cannot *prevent* a
    plugin (arbitrary Python) from calling `resolve_secret` for a scope it does not
    own — the preventive least-privilege control is deferred
    (`req-tap-cares-secrets-future-access-control`) — so we **observe and alarm**.

    NARROW v0 — the highest-signal, zero-false-positive case only: a plugin frame on
    the stack resolving `SOURCE_SECRET_SCOPE`, i.e. reaching for the credential that
    installs its siblings (a plugin must never resolve that). Fires before the
    lookup so a *probe* for a non-existent install secret is caught too. Broader
    plugin-resolves-another-plugin's-scope detection is a fast-follow (it carries
    false positives — a shared-utility plugin — so it is not in the v0 tripwire).

    Non-blocking and fires open (the resolution proceeds); the check is skipped
    entirely for the common case (any scope that is not the install scope), so it
    adds no cost to normal secret resolution. Best-effort caller identity — a
    determined plugin can evade the stack read; that residual is accepted per
    `req-sec-honest-risk`.
    """
    if ref.scope != SOURCE_SECRET_SCOPE:
        return
    caller_slug = calling_plugin_slug()
    if caller_slug is None:
        return
    concern(
        logger,
        "secrets",
        "cross_scope_secret_access",
        f"plugin {caller_slug!r} resolved the install-system scope {ref.scope!r} "
        f"(key {ref.key!r}) — the credential that installs plugins; a plugin must not resolve it",
    )
