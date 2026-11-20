"""`manage.py migrate_from_models` — build an EMPTY database from the models, else migrate (tap#1258).

On an empty database (no table but the cache's, nothing recorded) it creates every table from the
models and records every migration as applied, so a later plain ``migrate`` applies only what is
genuinely new. On any other database it is exactly ``migrate``. The boot entrypoint runs it in
place of ``migrate`` when the ``install.schema_from_models`` boot variable resolves true
(``TAP_BOOT_INSTALL__SCHEMA_FROM_MODELS``); see ``tap_boot.model_schema`` and
``req-boot-schema-from-models`` in ``specs/spec-tap-boot-v0.md``.
"""

from __future__ import annotations

import time
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DEFAULT_DB_ALIAS

from tap_boot.model_schema import BUILT, SchemaFromModelsRefused, migrate_from_models


class Command(BaseCommand):
    help = "Build an empty database's schema from the models and record every migration; migrate any other."

    # Like `migrate`: the checks run below with this database named, so the DB-tagged ones
    # (tap_health E001, the cache table) run too, which a plain BaseCommand check would skip.
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--database", default=DEFAULT_DB_ALIAS, help="Database alias (default: default).")
        parser.add_argument(
            "--noinput",
            "--no-input",
            action="store_false",
            dest="interactive",
            help="Accepted for parity with migrate; this command never prompts.",
        )
        parser.add_argument("--skip-checks", action="store_true", help="Skip system checks.")

    def handle(self, *args: Any, **options: Any) -> None:
        database = options["database"]
        if not options["skip_checks"]:
            self.check(databases=[database])
        started = time.monotonic()
        try:
            path = migrate_from_models(database, verbosity=options["verbosity"])
        except SchemaFromModelsRefused as exc:
            raise CommandError(str(exc)) from exc
        took = time.monotonic() - started
        if path == BUILT:
            self.stdout.write(f"Built the schema from the models and recorded every migration ({took:.1f}s).")
        else:
            self.stdout.write(f"Database already had a schema: migrated normally ({took:.1f}s).")
