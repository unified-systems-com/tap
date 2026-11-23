"""
Management command to re-derive the spine's event time (req-grid-entity-event-time rule 17).

Usage:
    docker compose exec web uv run python manage.py rederive_event_time --as USERNAME [--type SLUG ...]

BaseModel.save keeps Entity.event_start, event_end and event_precision, and the row's `tap.time` dimension, current on every
changing write. Run this after a model's EVENT_TIME declaration (or an edge type's ``event_time``)
changes, so the rows already stored follow it. It writes no history and no version. It runs as a
batch and records one ``maintenance`` event for each row whose spine values it changed; nothing
reads that event as a sighting, and the last-observed pointers do not move.

``--as`` names the actor the batch is recorded under; the actor needs ``grid.write``.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser


class Command(BaseCommand):
    help = "Re-derive Entity.event_* from the typed rows (all types, or the named ones)"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--as", dest="actor", required=True, help="Username the maintenance batch is recorded under"
        )
        parser.add_argument("--type", action="append", dest="types", help="Limit to this entity type (repeatable)")

    def handle(self, *args: Any, **options: Any) -> None:
        from django.contrib.auth import get_user_model

        from tap_auth.errors import AuthzError
        from tap_grid.caller_context import CallerContext
        from tap_grid.event_time_rederive import rederive_event_time

        user = get_user_model().objects.filter(username=options["actor"]).first()
        if user is None:
            raise CommandError(f"no user named {options['actor']!r}")
        try:
            report = rederive_event_time(options.get("types"), caller_context=CallerContext(user=user))
        except ValueError as error:
            raise CommandError(str(error)) from error
        except AuthzError as error:
            raise CommandError(f"{options['actor']!r} may not re-derive event time: {error}") from error
        self.stdout.write(f"types read: {report.types}  rows read: {report.rows}  rows changed: {report.changed}")
        for entity_type, count in sorted(report.by_type.items()):
            self.stdout.write(f"changed {entity_type}: {count}")
        if report.warnings:
            self.stdout.write(f"values that could not be stored (left empty): {report.warnings}")
        if report.batch_id:
            self.stdout.write(f"batch: {report.batch_id}")
