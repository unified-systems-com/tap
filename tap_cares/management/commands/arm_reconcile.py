"""Arm or disarm a collector's reconcile authority — the operator's switch (Issue# 655 - tap).

``Collector`` is INTERNAL_ONLY, so the switch is not reachable through the public verbs; this
command calls the one sanctioned path, ``tap_cares.services.arm_reconcile``, as the named
operator (``--as``), who must hold ``cares.arm_reconcile``. The shell is a trusted surface: the
operator names themself, and the audit batch records that name. Off stays the default.

    manage.py arm_reconcile <collector_registry> --on [--budget N] --as <username>
    manage.py arm_reconcile <collector_registry> --off --as <username>
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError, CommandParser

from tap_auth.actors import acting_as
from tap_auth.errors import AuthzError
from tap_cares.exceptions import CollectorNotFoundError
from tap_cares.services import arm_reconcile
from tap_grid.reconcile import ReconcileError


class Command(BaseCommand):
    help = "Arm (--on) or disarm (--off) a collector's reconcile authority, as the named operator."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("collector_registry", help="The Collector node's scope:key (collector_registry).")
        switch = parser.add_mutually_exclusive_group(required=True)
        switch.add_argument("--on", action="store_true", help="Authority on: the collector's runs may retire.")
        switch.add_argument("--off", action="store_true", help="Authority off (the default): runs retire nothing.")
        parser.add_argument(
            "--budget", type=int, default=None, help="Falsifier budget per run; omit for the class default."
        )
        parser.add_argument(
            "--as", dest="operator", required=True, help="Username of the operator (must hold cares.arm_reconcile)."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        user_model = get_user_model()
        try:
            operator = user_model.objects.get(username=options["operator"])
        except user_model.DoesNotExist as exc:
            raise CommandError(f"no user {options['operator']!r}") from exc
        try:
            with acting_as(operator):
                record = arm_reconcile(
                    options["collector_registry"], authority=bool(options["on"]), budget=options["budget"]
                )
        except AuthzError as exc:
            raise CommandError(f"refused: {exc}") from exc
        except (CollectorNotFoundError, ReconcileError) as exc:
            raise CommandError(str(exc)) from exc
        after = record["after"]
        self.stdout.write(
            self.style.SUCCESS(
                f"{record['collector']}: reconcile authority {'ON' if after['authority'] else 'OFF'} "
                f"(budget {after['budget']!r}), was {record['before']['authority']}/{record['before']['budget']!r}; "
                f"audit batch {record['batch']} by {record['operator']}"
            )
        )
