"""
Management command for the committed record of type versions (req-grid-entity-model-version rules 5 and 7).

Usage:
    docker compose exec web uv run python manage.py model_versions --check
    docker compose exec web uv run python manage.py model_versions --record
    docker compose exec web uv run python manage.py model_versions --record --app <dotted app or plugin name>

Each core app and each plugin keeps a ``<app label>.model_versions.json`` at its package root: for every type it
owns, one entry per version, holding that version's definition and a chained fingerprint.

``--check`` reports a definition that changed while its version did not, an entry that was edited
after it was recorded, and a type with no entry. It exits non-zero on any of those.

``--record`` appends the entry for each declared version the record does not hold yet. It never
rewrites an entry: a type whose definition changed at an unchanged version is reported and left
alone, because the fix is to raise the version, not to re-record it.

With no ``--app`` it covers core's own apps. A plugin author names their plugin.
"""

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser


class Command(BaseCommand):
    help = "Check or extend the committed record of node, edge and spine versions"

    def add_arguments(self, parser: CommandParser) -> None:
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--check", action="store_true", help="Compare the code with the committed record")
        mode.add_argument("--record", action="store_true", help="Append entries for versions not yet recorded")
        parser.add_argument("--app", action="append", dest="apps", help="Dotted app or plugin name (repeatable)")

    def handle(self, *args: Any, **options: Any) -> None:
        from tap_grid.model_definition import (
            TypeState,
            app_record_path,
            append_entry,
            entries_for,
            load_record,
            type_problems,
            unrecorded,
            write_record,
        )

        owners = self._owners(options.get("apps"))
        problems: list[str] = []
        added = 0
        for owner, states in sorted(owners.items()):
            path: Path = app_record_path(owner)
            try:
                record = load_record(path)
            except ValueError as error:
                raise CommandError(str(error)) from error
            before = len(problems)
            for state in states:
                problems.extend(f"{owner}: {problem}" for problem in type_problems(state, entries_for(record, state)))
            if options["check"]:
                missing: list[TypeState] = unrecorded(states, record)
                problems.extend(f"{owner}: {state.label} has no committed entry in {path.name}" for state in missing)
                continue
            if len(problems) > before:
                continue
            changed = False
            for state in states:
                try:
                    if append_entry(record, state):
                        changed = True
                        added += 1
                        self.stdout.write(f"recorded {owner}: {state.label} version {state.version}")
                except ValueError as error:
                    problems.append(f"{owner}: {error}")
            if changed:
                write_record(path, record)
        for problem in problems:
            self.stderr.write(problem)
        if problems:
            raise CommandError(f"{len(problems)} problem(s) in the committed record of type versions")
        if options["record"]:
            self.stdout.write(f"{added} entr{'y' if added == 1 else 'ies'} recorded")
        else:
            self.stdout.write(f"{sum(len(states) for states in owners.values())} type(s) in step with their record")

    def _owners(self, names: list[str] | None) -> dict[str, list[Any]]:
        from django.apps import apps

        from tap_grid.model_definition import core_states, plugin_states

        core = core_states()
        if not names:
            return core
        owners: dict[str, list[Any]] = {}
        for name in names:
            if name in core:
                owners[name] = core[name]
                continue
            config = next((c for c in apps.get_app_configs() if name in (c.name, c.label)), None)
            manifest = getattr(config, "_manifest", None)
            if config is None or manifest is None:
                raise CommandError(f"{name!r} is neither a core app that owns types nor an installed plugin")
            owners[config.name] = plugin_states(manifest)
        return owners
