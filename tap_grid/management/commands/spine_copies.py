"""
Management command for the spine copies on typed rows (req-grid-entity-spine-copies rule 10).

Usage:
    docker compose exec web uv run python manage.py spine_copies            # check: report, write nothing
    docker compose exec web uv run python manage.py spine_copies --repair   # reinstall triggers, fill rows

The database keeps ``spine_deleted_at`` and ``spine_dimensions`` on every typed row equal to the entity
row by triggers that ``migrate`` installs. A session that disables triggers (a restore, a replication
apply) leaves them out of step. The check counts the differing rows per typed table and the tables
that keep no copy, and exits non-zero when it finds any, so a script can act on it; it changes
nothing. ``--repair`` reinstalls the triggers and the type map and brings every row into step with one
set-based statement per table.

It is also the diagnostic for the boot's column gate (rule 20): a registered typed table without the
two columns, which boot refuses to start on, is listed with its app and the remedy. ``--repair``
cannot fix that one; the plugin's migration has to be regenerated.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from tap_grid.spine_copies import check, missing_columns, repair


class Command(BaseCommand):
    help = "Check the spine copies on typed rows against their entity rows, or repair them"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--repair", action="store_true", help="Reinstall the triggers and bring every row into step")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["repair"]:
            filled = repair()
            for table, rows in sorted(filled.items()):
                self.stdout.write(f"repaired {table}: {rows} row(s)")
            self.stdout.write(f"repaired {sum(filled.values())} row(s) in {len(filled)} table(s)")
        report = check()
        missing = missing_columns()
        for gap in missing:
            self.stdout.write(f"missing columns: {gap.describe()}")
        for table, rows in sorted(report.drifted.items()):
            self.stdout.write(f"out of step: {table}: {rows} row(s)")
        self.stdout.write(report.summary())
        if not report.clean or missing:
            raise CommandError(
                "the spine copies are not in step on every typed table, or a table lacks a column (above). Rows "
                "out of step or a table with no trigger: run spine_copies --repair. A table missing a column (boot "
                "refuses to start on one): regenerate its app's migrations against this core (manage.py "
                f"makemigrations {' '.join(sorted({gap.app_label for gap in missing})) or '<app>'}, depending on "
                "tap_grid 0023_spine_copies, and 0024_history_event_time for a history table), raise the plugin's "
                "requires_tap to this core, and migrate. A table that does not exist: migrate the app that owns it."
            )
