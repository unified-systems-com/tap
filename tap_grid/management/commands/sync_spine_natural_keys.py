"""
Management command to keep Entity.natural_key true to every keyed row (req-grid-entity-natural-key-23, -25).

Usage:
    docker compose exec web uv run python manage.py sync_spine_natural_keys [--type SLUG ...]
    docker compose exec web uv run python manage.py sync_spine_natural_keys --changed   # at deploy
    docker compose exec web uv run python manage.py sync_spine_natural_keys --check [--sample N]

BaseModel.save keeps the spine natural key current on every write. The plain run re-derives every
row (or the named types) and writes what differs. ``--changed`` re-derives only the types whose
recipe fingerprint — slug, NATURAL_KEY tuple, composition version — no longer matches the one
recorded when they were last derived, or that have none; run it at every deploy. ``--check`` reads
only: it samples each type's rows, compares the stored key with a fresh composition, lists stale
recipes, and fails when it finds either.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from tap_grid.spine_natural_key import check, sync


class Command(BaseCommand):
    help = "Re-derive Entity.natural_key (all, named types, or changed recipes), or check it for drift"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--type", action="append", dest="types", help="Limit to this entity type (repeatable)")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--changed", action="store_true", help="Only types whose recipe fingerprint changed")
        mode.add_argument("--check", action="store_true", help="Report drift and stale recipes; write nothing")
        parser.add_argument("--sample", type=int, default=200, help="Rows sampled per type by --check")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["check"]:
            drift = check(options.get("types"), sample=options["sample"])
            self.stdout.write(f"rows sampled: {drift.sampled}")
            for entity_type in drift.stale_recipes:
                self.stdout.write(f"stale recipe: {entity_type}")
            for entity_type, rows in sorted(drift.drifted.items()):
                self.stdout.write(f"drift: {entity_type}: {len(rows)} sampled row(s), e.g. {rows[0]}")
            for entity_type, reason in sorted(drift.skipped.items()):
                self.stdout.write(f"skipped {entity_type}: {reason}")
            if not drift.clean:
                raise CommandError(
                    "spine natural keys are stale; run sync_spine_natural_keys --changed (or without it)"
                )
            return
        report = sync(options.get("types"), changed_only=options["changed"])
        self.stdout.write(f"types read: {report.types}  rows read: {report.rows}  rows written: {report.written}")
        for entity_type, reason in sorted(report.skipped.items()):
            self.stdout.write(f"skipped {entity_type}: {reason}")
