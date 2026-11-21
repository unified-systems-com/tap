"""`manage.py migrate` — Django's migrate, with the shallow reload on its forward plan (tap#1275).

Exactly Django's command (every option, every signal, the same output) run inside
``tap_boot.shallow_reload.installed()``, which re-renders only the model each migration operation
touched instead of every model that shares a foreign key target with it. ``TAP_MIGRATE_SHALLOW_RELOAD=0``
makes it Django's command unchanged. See ``tap_boot.shallow_reload`` and ``req-boot-shallow-reload`` in
``specs/spec-tap-boot-v0.md``.
"""

from __future__ import annotations

from typing import Any

from django.core.management.commands.migrate import Command as DjangoMigrateCommand

from tap_boot import shallow_reload


class Command(DjangoMigrateCommand):
    def handle(self, *args: Any, **options: Any) -> None:
        with shallow_reload.installed():
            if not shallow_reload.enabled() and options["verbosity"] >= 2:
                self.stdout.write(f"Shallow reload off ({shallow_reload.ENV}); Django's reload throughout.")
            super().handle(*args, **options)
