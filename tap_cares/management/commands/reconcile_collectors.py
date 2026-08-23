"""Materialize the on-grid Collector node for every registered collector.

A standalone collector-node reconcile: app `ready()` registers each collector
runner in memory (read-only, req-tap-plugin-load-v0-ready-readonly); this command
creates/updates the matching `Collector` grid node, run as the named
`tap_bootloader` actor — so no graph write happens before auth bootstrap exists.

`manage.py boot` runs `reconcile_collector_nodes()` itself at the start of its
population phase (spec-tap-boot-v0, req-boot-population), so the spawn flow no
longer calls this command directly; it is retained as an idempotent, standalone
operator/diagnostic command.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from tap_auth.actors import BOOTLOADER, acting_as, get_builtin_actor
from tap_cares.registry import reconcile_collector_nodes


class Command(BaseCommand):
    help = "Materialize on-grid Collector nodes from the registry, as tap_bootloader."

    def handle(self, *args: Any, **options: Any) -> None:
        # This command is the interim boot orchestrator: IT sets the actor context,
        # and reconcile_collector_nodes() simply inherits it — tap_cares carries no
        # bootloader knowledge. The future tap_boot population phase takes this over.
        with acting_as(get_builtin_actor(BOOTLOADER)):
            summary = reconcile_collector_nodes()
        self.stdout.write(
            self.style.SUCCESS(
                f"Reconciled collector nodes: {summary['created']} created, "
                f"{summary['updated']} updated, {summary['unchanged']} unchanged."
            )
        )
