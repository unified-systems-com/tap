"""The spine's own version (req-grid-entity-spine-version rules 1 and 2).

``SPINE_VERSION`` is authored. It covers the ``Entity`` row and the columns core defines on the
edge table and on every typed row through the base model: what they are and what they mean. It
moves only when the spine changes, with the ``tap_grid`` migration that changes it, and by hand
for a change of meaning the fingerprint guard cannot see. It is not the tap release version, the
GRIFT format version or any type's version.

The grid records the version its database is at in the one row of ``SpineVersion``
(``tap_spine_version``), written each time migrations are applied and the database holds every
``tap_grid`` migration this code carries. A database that records a greater version than this code
declares was written by a newer core, and the process refuses to start against it.

Not here yet: the spine's chain of links, the GRIFT header field, and lowering the record when a
migration is reversed (rules 3 to 6). With one spine version there is nothing to lower to.
"""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db import DEFAULT_DB_ALIAS, OperationalError, ProgrammingError, connections

logger = logging.getLogger(__name__)

#: The spine's version. Version 1 is the spine as of tap_grid migration 0022.
SPINE_VERSION = 1

_APP_LABEL = "tap_grid"


class SpineVersionAhead(ImproperlyConfigured):
    """The database records a greater spine version than this code declares."""

    def __init__(self, declared: int, recorded: int) -> None:
        self.declared, self.recorded = declared, recorded
        super().__init__(
            f"This database is at spine version {recorded} and the installed core declares spine version "
            f"{declared}: the code is older than the data. Install the core release that declares spine "
            f"version {recorded} (req-grid-entity-spine-version rule 2)."
        )


def recorded_version(*, using: str = DEFAULT_DB_ALIAS) -> int | None:
    """The spine version the database records, or None where it records none."""
    from tap_grid.models import SpineVersion

    return SpineVersion.objects.using(using).values_list("version", flat=True).first()


def refuse_newer_database(*, using: str = DEFAULT_DB_ALIAS) -> None:
    """Raise :class:`SpineVersionAhead` where the database is at a greater spine version than the code.

    Called at start. A database with no record yet (not migrated to 0022, or empty) has nothing
    to compare, and ``migrate`` is what brings it up. A database that could not be read at all is
    not passed: the check is marked as owed (``tap_grid.model_version.complete_start_checks``).
    """
    try:
        recorded = recorded_version(using=using)
    except OperationalError, ProgrammingError:
        # Not read, so not checked: the check is owed before this process writes anything.
        from tap_grid.model_version import mark_start_incomplete

        mark_start_incomplete("the spine version record could not be read")
        return
    if recorded is not None and recorded > SPINE_VERSION:
        raise SpineVersionAhead(SPINE_VERSION, recorded)


def _schema_is_current(using: str) -> bool:
    """Whether the database holds every ``tap_grid`` migration this code carries.

    A database built from the models (``migrate --run-syncdb`` with migrations switched off, which
    is how ``migrate_from_models`` and ``--nomigrations`` test runs build it) has this code's
    tables by construction.
    """
    from django.db.migrations.loader import MigrationLoader
    from django.db.migrations.recorder import MigrationRecorder

    module_name, _explicit = MigrationLoader.migrations_module(_APP_LABEL)
    if module_name is None:
        return True
    # What this code carries, read from disk by Django's own loader; no connection, so nothing
    # here depends on what the database says is applied.
    loader = MigrationLoader(None, ignore_no_migrations=True)
    carried = {name for app, name in loader.disk_migrations if app == _APP_LABEL}
    recorder = MigrationRecorder(connections[using])
    if not recorder.has_table():
        return False
    applied = {name for app, name in recorder.applied_migrations() if app == _APP_LABEL}
    return carried <= applied


def record_after_migrate(sender: Any, *, using: str = DEFAULT_DB_ALIAS, **kwargs: Any) -> None:
    """Record the spine version the database is now at, once ``migrate`` has applied its plan (rule 2).

    Connected to ``post_migrate`` for ``tap_grid``. Django sends it after a forward migration, a
    reversal, a build from the models and a flush alike, so the test is the database's state and
    not the plan: the record is written only while the database holds every ``tap_grid``
    migration this code carries. A flush empties the table with every other, and the record is
    put back. A record greater than this code declares is left alone: this code did not write
    that spine and must not claim it.

    TAP-IMPLEMENTS: req-grid-entity-spine-version@cf43a85b9421/20f966f690b5 (derivation) — rule 2: the one writer
        of the grid's record of its spine version, run when migrations are applied.
    """
    from django.db import router

    from tap_grid.models import SpineVersion

    if router.allow_migrate_model(using, SpineVersion) and _schema_is_current(using):
        recorded = recorded_version(using=using)
        if recorded is None or recorded < SPINE_VERSION:
            SpineVersion.objects.using(using).update_or_create(id=1, defaults={"version": SPINE_VERSION})
            logger.info("[4d2a] spine version %s recorded on %s", SPINE_VERSION, using)

    # A process whose start could not read the database (the usual case for the first migrate of
    # an empty one) makes the comparison it skipped now that the tables exist.
    from tap_grid.model_version import complete_start_checks, start_incomplete

    if start_incomplete():
        complete_start_checks(using=using)
