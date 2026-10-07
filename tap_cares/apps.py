"""tap_cares application configuration."""

from typing import Any

from django.apps import AppConfig


class TapCaresConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tap_cares"
    verbose_name = "TAP Cares"

    # The edge types tap_cares writes, as definitions (same format as TapWebConfig.edge_types;
    # processed by register_edge_types_from_list() on startup). Each declares its identity
    # (req-grid-edge-identity-declaration). The three lifecycle edges are keyless: each records
    # something this grid did once, its target minted in the same code path as the edge, so
    # there is no source relationship to find again. SCHEDULED_TARGET is a standing,
    # operator-declared relationship and a plain key. The three lifecycle edges are also
    # internal-only (req-grid-edge-internal): bookkeeping this subsystem writes about itself, which
    # the generic edge verbs and GRIFT refuse; SCHEDULED_TARGET stays public because schedules are
    # authored in GRIFT.
    edge_types: list[dict[str, Any]] = [
        {
            "slug": "HAS_COLLECTION_JOB",
            "internal_only": True,
            "sources": [{"type": "collector"}],
            "targets": [{"type": "collection_job"}],
            "identity": {
                "keyless": {
                    "reason": (
                        "One edge per collection run, written by run_collection beside the job it creates; "
                        "it records an act of this grid, not an observed relationship."
                    )
                }
            },
        },
        {
            # Scheduler edges — req-tap-cares-scheduler-edges.
            "slug": "SCHEDULED_TARGET",
            "sources": [{"type": "schedule"}],
            "targets": [{"type": "collector"}],
            "identity": {"discriminators": []},
        },
        {
            "slug": "HAS_FIRED",
            "internal_only": True,
            "sources": [{"type": "schedule"}],
            "targets": [{"type": "schedule_fire"}],
            "identity": {
                "keyless": {
                    "reason": (
                        "One edge per scheduler fire, written with the fire it records; it is the "
                        "fire history of this grid, not an observed relationship."
                    )
                }
            },
        },
        {
            "slug": "TRIGGERED_JOB",
            "internal_only": True,
            "sources": [{"type": "schedule_fire"}],
            "targets": [{"type": "collection_job"}],
            "identity": {
                "keyless": {
                    "reason": (
                        "One edge per fire that starts a run, written when the job is created; it "
                        "records an act of this grid, not an observed relationship."
                    )
                }
            },
        },
    ]

    def ready(self) -> None:
        # Load runtime secrets from the configured mount root into
        # secret_registry. No-op when the root is missing or empty; fails
        # loud on malformed files or duplicate `scope:key` so an operator
        # notices before any capability runs.
        # See tap_cares/specs/spec-tap-cares-secrets.md.
        from django.conf import settings

        from tap_cares.secrets.loader import load_secrets

        load_secrets(settings.TAP_SECRETS_ROOT)

        # Register the secret-load system check. Importing only registers the
        # check function; it reads secret_load_report (populated just above)
        # when it runs under `manage.py check` / `runserver` — no DB access
        # here, so this is ready()-safe. See tap_cares/checks.py.
        from tap_cares import checks  # noqa: F401
        from tap_cares.health import probe_secrets

        # Register the secrets health probe from tap_cares's own boundary so the
        # dependency runs tap_cares -> tap_health (not core importing up into
        # tap_cares). See tap_cares/health.py and spec-tap-health-v0.md.
        from tap_health.registry import register_health_probe
        from tap_health.selection import READINESS

        # Readiness only: missing/malformed secret material is not fixed by a
        # restart. `critical=True` with the probe choosing its own status — it
        # reports `unhealthy` for a required-for-boot failure and `degraded`
        # otherwise (req-tap-health-probes-6).
        register_health_probe("secrets", probe_secrets, sets=(READINESS,), group="tap_cares", critical=True)

        # Register tap_cares-owned edge types. Plugins use the manifest path
        # (tap-plugin.toml + edges/*.edge.json); first-party apps declare an
        # `edge_types` class attribute (above) and register it through the same registries.
        from tap_plugins.base import register_edge_types_from_list

        register_edge_types_from_list(self.edge_types)

        # Import the Steady Queue task module so its @recurring scheduler
        # tick is registered with steady_queue at startup. Steady Queue's
        # Configuration.RecurringTask.discover() picks up @recurring
        # callsites from imported modules; importing here makes the
        # scheduler tick discoverable in every process (web and supervisor).
        #
        # Guarded on backend: under tests we configure ImmediateBackend
        # (tap/test_settings.py), where @task() returns a plain Django Task
        # that lacks the .serialize() method steady_queue's @recurring
        # wrapper expects. Skipping the import there avoids an import-time
        # AttributeError and is correct anyway — tests don't run the
        # steady_queue supervisor, so a recurring task registration would
        # have no effect.
        from django.conf import settings

        backend_path = settings.TASKS.get("default", {}).get("BACKEND", "")
        if backend_path == "steady_queue.backend.SteadyQueueBackend":
            from tap_cares import task_backend  # noqa: F401
