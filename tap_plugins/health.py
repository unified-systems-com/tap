"""The `plugins-loaded` health probe (req-tap-health-probes-9).

Owned by `tap_plugins` and registered from its own `ready()`, so the dependency
runs `tap_plugins` → `tap_health` rather than core importing up into plugin code
(the inversion established by req-tap-health-probe-registry-3).

**What it answers:** did this process actually load the plugin set it was told to
run? That is the runtime half of the three-state model the plugin-loading race
exposed (`tap_plugins/specs/spec-tap-plugin-lifecycle-v1.md`): the boot profile is
DESIRED, a DB registry is persisted-ACTUAL, and the Django app registry is
RUNTIME-LOADED. Nothing was checking the last one against the first, so a process
that silently loaded a different plugin set looked perfectly healthy — which is
precisely how a registered type ended up with no migrated table.

The desired set comes from `preboot.resolved_plugin_app_configs()` — the one
authoritative resolver (`TAP_PLUGINS` env → the entrypoint's persisted file →
warned discovery). This probe deliberately does NOT re-derive it: re-deriving
"the plugin set" a second way is the bug this probe exists to catch.
"""

from __future__ import annotations

import logging

from django.apps import apps

from tap_health.results import ProbeResult

logger = logging.getLogger(__name__)


def probe_plugins_loaded() -> ProbeResult:
    """Every plugin this process was told to run is present in the app registry.

    Runs entirely in memory (env/file read + the loaded app registry) — no DB, no
    network — so it reports truthfully even when the database is unreachable.
    """
    from tap.preboot import resolved_plugin_app_configs

    try:
        desired = list(resolved_plugin_app_configs())
    except Exception as exc:  # noqa: BLE001 — report, never raise.
        logger.warning("[b7a2] health: could not resolve the desired plugin set: %s", exc)
        return ProbeResult.unknown("plugins.unresolvable", detail=str(exc))

    # An AppConfig path may be given as "pkg.apps.FooConfig" or as the app module
    # "pkg"; compare on the app module, which is what the registry keys on.
    loaded_modules = {config.name for config in apps.get_app_configs()}

    missing = sorted(path for path in desired if _app_module(path) not in loaded_modules)
    if missing:
        return ProbeResult.unhealthy(
            "plugins.not_loaded",
            detail=f"{len(missing)} declared plugin(s) not loaded: {', '.join(missing)}",
            reasoning=(
                "The process was told to run these plugins but their apps are absent from the "
                "Django app registry, so their types, migrations and routes are not live."
            ),
            context={"missing": missing, "desired_count": len(desired)},
        )
    return ProbeResult.healthy(context={"desired_count": len(desired)})


def _app_module(app_config_path: str) -> str:
    """The app module for an AppConfig path (`pkg.apps.FooConfig` → `pkg`)."""
    parts = app_config_path.split(".")
    if len(parts) >= 3 and parts[-2] == "apps":
        return ".".join(parts[:-2])
    return app_config_path


__all__ = ["probe_plugins_loaded"]
