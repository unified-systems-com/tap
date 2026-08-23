"""Validate a TAP plugin's correctness at structure, loads, or runs level.

TAP-IMPLEMENTS: req-tap-plugin-validate-mgmt@bdc303bbdffd/b9a43a32a579 (surface) — the
    Django management-command face of the validator.

Usage:
    docker compose exec web uv run python manage.py validate_plugin plugins/grid_fixtures
    docker compose exec web uv run python manage.py validate_plugin plugins/grid_fixtures --level loads
    docker compose exec web uv run python manage.py validate_plugin plugins/grid_fixtures --level runs
    docker compose exec web uv run python manage.py validate_plugin plugins/grid_fixtures --json
    docker compose exec web uv run python manage.py validate_plugin plugins/grid_fixtures --strict
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Validate a TAP plugin root directory. Supports --level structure (default), "
        "loads (class imports), or runs (service-layer smoke tests with rollback)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "plugin_root",
            type=Path,
            help="Path to the plugin root directory.",
        )
        parser.add_argument(
            "--level",
            default="structure",
            choices=["structure", "loads", "runs"],
            help="Validation level (default: structure).",
        )
        parser.add_argument(
            "--json",
            dest="json_output",
            action="store_true",
            default=False,
            help="Emit machine-readable JSON output.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            default=False,
            help="Promote warnings to failures.",
        )

    def handle(self, **options):
        from tap_plugins.validate.service import validate_plugin

        plugin_root = options["plugin_root"].resolve()

        result = validate_plugin(
            plugin_root,
            level=options["level"],
            strict=options["strict"],
        )

        if options["json_output"]:
            self.stdout.write(result.to_json())
        else:
            self.stdout.write(result.to_human())

        if not result.ok:
            raise CommandError("Plugin validation failed.")
