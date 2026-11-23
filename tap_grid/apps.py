from django.apps import AppConfig


class TapCoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tap_grid"
    verbose_name = "TAP Core"

    def ready(self) -> None:
        # Registers the deployment-configuration checks by import (no DB access here —
        # the checks run later, so this does not breach the no-DB-in-ready() rule).
        from django.db.backends.signals import connection_created

        from tap_grid import checks  # noqa: F401

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

        # Generate the natural-key search index for every registered model from its
        # NATURAL_KEY declaration (req-grid-entity-natural-key-12). Pure _meta writes,
        # no DB. ready() is the first moment every model has its fields, and every
        # app's models — plugins included — import before any ready() runs, so the
        # migration autodetector and the test runner both see the generated indexes.
        from tap_grid.models import install_natural_key_indexes

        install_natural_key_indexes()

        # The spine natural key catch-up runs after every migrate (req-grid-entity-natural-key-23),
        # once, for this app's post_migrate, by which point every app's migrations have applied.
        from django.db.models.signals import post_migrate

        from tap_grid.spine_natural_key import sync_after_migrate

        post_migrate.connect(sync_after_migrate, sender=self, dispatch_uid="tap_grid.spine_natural_key_sync")

        # The live dimension vocabulary (req-grid-dimension-reference-9) forgets its per-process table
        # the moment a Dimension node is written, retired or purged here, so the next resolution reads
        # the change (a tombstone is a queryset update, so the delete path invalidates explicitly too).
        # Signal wiring only, no DB.
        from django.db.models.signals import post_delete, post_save

        from tap_grid.live_dimensions import invalidate, invalidate_entity
        from tap_grid.models import Dimension, Entity

        for label, signal in (("post_save", post_save), ("post_delete", post_delete)):
            signal.connect(invalidate, sender=Dimension, dispatch_uid=f"tap_grid.live_dimensions.{label}.dimension")
            signal.connect(invalidate_entity, sender=Entity, dispatch_uid=f"tap_grid.live_dimensions.{label}.entity")

        # Register the grid-population probe from tap_grid's own boundary
        # (req-tap-health-probe-registry-3). Registration only appends a callable —
        # no DB here; the probe body runs later at run_health() time.
        from tap_grid.health import probe_grid_tables, probe_history_agreement
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
        # Not critical (req-grid-history-optout-9): a disagreement between a type's
        # TRACK_HISTORY, its EntityType.track_history and its history model is made visible
        # (degraded), but every history consumer asks the class-built answer, so none of
        # them is misled into a wrong result. The probe's docstring carries the reasoning.
        register_health_probe(
            "grid.history_agreement",
            probe_history_agreement,
            sets=(READINESS,),
            group="tap_grid",
            critical=False,
        )

        # The spine version the database is at is recorded each time migrations are applied
        # (req-grid-entity-spine-version rule 2). Signal wiring only, no DB.
        from tap_grid.spine_version import record_after_migrate

        post_migrate.connect(record_after_migrate, sender=self, dispatch_uid="tap_grid.spine_version_record")

        self.compare_versions_at_start()

    def compare_versions_at_start(self) -> None:
        """The version checks a process makes as it starts, before it serves anything.

        Reads the database, as the type catalog's registration always has here.
        """
        from django.db import OperationalError, ProgrammingError

        from tap_grid.spine_version import refuse_newer_database

        # A database at a greater spine version than this code declares was written by a newer
        # core: refuse to start against it (req-grid-entity-spine-version rule 2). A database
        # with no record yet passes; migrate is what brings it up.
        refuse_newer_database()

        try:
            # Core's own node and edge types get a catalog row and an applied version, as a
            # plugin's types do from its manifest (req-grid-entity-model-version rule 6). The
            # comparison of declared and applied versions happens here too, and a type whose
            # rows are at a greater version than its class declares stops the start (rule 4).
            from tap_grid.model_version import register_core_types

            register_core_types()
        except OperationalError, ProgrammingError:
            # DB not ready yet (e.g. during initial migrate, or before the version column exists).
            pass
