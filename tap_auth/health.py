"""tap_auth health probe — configured providers' offline self-test outcome.

req-tap-auth-providers (spec-tap-auth-v0.md);
req-tap-cares-secrets-conditional-validation (spec-tap-cares-secrets.md).

The worked reference for the per-consumer conditional-secret-validation pattern:
the runtime view of what boot already gates at standup. For every configured
provider it runs the provider's own **offline** self-test (shape + secret
presence + local derivations) and aggregates the result. Whether a provider
needs a secret is the provider's own conditional logic — no providers configured
is healthy (local auth only) — so this probe carries no necessity opinion of its
own; it reuses `self_test` as the single source of truth shared with boot.

Registered from `tap_auth`'s own `ready()` so the dependency runs the right way
(tap_auth -> tap_health). The probe body runs later, so it is `ready()`-safe.
"""

from __future__ import annotations

import logging

from tap_health.results import ProbeResult, exception_detail

logger = logging.getLogger(__name__)


def probe_auth_providers() -> ProbeResult:
    """Report the offline self-test outcome across all configured providers.

    `critical=False` at registration: boot already hard-gates `critical_for_boot`
    providers at standup, so this surfaces a *runtime* regression (e.g. a secret
    deleted under a running instance, or a provider misconfigured) as a loud but
    non-blocking `degraded` overall verdict. The probe still chooses its own
    per-probe status — `unhealthy` on a FAIL, `degraded` on a WARN-only run.
    """
    from tap_auth.providers.base import SelfTestPhase, SelfTestStatus
    from tap_auth.providers.registry import UnknownProviderType, get_provider
    from tap_auth.providers.wiring import iter_provider_configs

    try:
        configs = iter_provider_configs()
    except Exception as exc:  # noqa: BLE001 — malformed TAP_AUTH_PROVIDERS; report, never raise.
        logger.warning("[9f60] health: auth providers config error: %s", exc)
        return ProbeResult.unhealthy("auth.providers.config_error", detail=exception_detail(exc))

    if not configs:
        return ProbeResult.healthy(detail="no auth providers configured (local auth only)")

    failed: list[str] = []
    warned: list[str] = []
    for config in configs:
        try:
            provider = get_provider(config.type)
        except UnknownProviderType:
            failed.append(f"{config.id}:unknown_type")
            continue
        try:
            secrets = provider.resolve_secrets(config)
        except Exception:  # noqa: BLE001 — a missing/unreadable secret is the signal self_test reports.
            secrets = {}
        try:
            results = [r for r in provider.self_test(config, secrets, live=False) if r.phase is SelfTestPhase.OFFLINE]
        except Exception as exc:  # noqa: BLE001 — a buggy self_test must not crash the probe.
            logger.warning("[fbf0] health: provider %s self_test raised: %s", config.id, exc)
            failed.append(f"{config.id}:selftest_raised")
            continue
        for result in results:
            if result.status is SelfTestStatus.FAIL:
                failed.append(f"{config.id}:{result.check}")
            elif result.status is SelfTestStatus.WARN:
                warned.append(f"{config.id}:{result.check}")

    if failed:
        return ProbeResult.unhealthy(
            "auth.providers.selftest_failed",
            detail=f"{len(failed)} provider offline self-test check(s) failed",
            context={"failed": failed, "warned": warned},
        )
    if warned:
        return ProbeResult.degraded(
            "auth.providers.selftest_warned",
            detail=f"{len(warned)} provider offline self-test warning(s)",
            context={"warned": warned},
        )
    return ProbeResult.healthy(detail=f"{len(configs)} provider(s): offline self-test OK")


__all__ = ["probe_auth_providers"]
