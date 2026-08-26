from django.apps import AppConfig


class TapCoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tap_grid"
    verbose_name = "TAP Core"

    def ready(self) -> None:
        from django.db import OperationalError, ProgrammingError
        from django.db.backends.signals import connection_created

        # Layer 2 of the read backstop (req-tap-auth-orm-read-backstop): attach the
        # SQL execute_wrapper to every DB connection as it is created, so reads
        # that bypass BaseModelQuerySet._fetch_all (.count/.exists/.raw/cursor) and
        # non-BaseModel catalog tables (EntityType) still fail closed. Wiring here
        # (not per-request) makes the guard unforgettable.
        from tap_grid.read_guard import install_read_sql_guard

        connection_created.connect(install_read_sql_guard, dispatch_uid="tap_grid.read_guard")

        # Detection backstop for the read-only search connection
        # (req-grid-search-readonly.sec-6): attach an execute_wrapper to the
        # search_readonly alias that turns PostgreSQL's silent read-only write
        # rejection (SQLSTATE 25006) into a loud security Flaw before re-raising.
        # The write stays blocked; this adds the response-triggering alert. Wiring
        # here (not per-callsite) makes the alert unforgettable.
        from tap_grid.search_readonly_guard import install_readonly_write_guard

        connection_created.connect(install_readonly_write_guard, dispatch_uid="tap_grid.search_readonly_guard")

        # Broad detection backstop for insufficient-privilege denials
        # (req-grid-db-permission-flaw.sec): attach an execute_wrapper to *every*
        # connection that turns PostgreSQL's SQLSTATE 42501 into a loud security Flaw
        # before re-raising. A 42501 means an in-code guard leaked and the DB caught it;
        # wired unconditionally (not per-alias) so it forward-proofs the least-privilege
        # DB roles without per-role wiring.
        from tap_grid.db_permission_guard import install_db_permission_guard

        connection_created.connect(install_db_permission_guard, dispatch_uid="tap_grid.db_permission_guard")

        # Register grid-standard edge types (e.g. PRODUCED_BATCH). Pure
        # in-memory registry writes — no DB — so this runs unconditionally,
        # before the DB-touching bootstrap below.
        from tap_grid.core_edges import register_core_edges

        register_core_edges()

        # Register the grid-population probe from tap_grid's own boundary
        # (req-tap-health-probe-registry-3). Registration only appends a callable —
        # no DB here; the probe body runs later at run_health() time.
        from tap_grid.health import probe_grid_tables
        from tap_health.registry import register_health_probe
        from tap_health.selection import READINESS

        # Critical: a classified model whose table does not exist is exactly the
        # schema/registry divergence that makes grid reads fail at the database.
        register_health_probe(
            "grid.tables",
            probe_grid_tables,
            sets=(READINESS,),
            group="tap_grid",
            critical=True,
        )

        try:
            from tap_grid.models import EntityType, EntityTypeKind

            EntityType.objects.update_or_create(
                slug="search",
                defaults={
                    "name": "Search",
                    "plugin_name": "tap_grid",
                    "icon": "search",
                    "kind": EntityTypeKind.NODE,
                },
            )
        except OperationalError, ProgrammingError:
            # DB not ready yet (e.g. during initial migrate).
            pass
