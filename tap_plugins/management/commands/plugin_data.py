"""``manage.py plugin_data`` — list plugin data directories, or purge one.

`tap_plugins/specs/spec-tap-plugin-data-directory.md`, `req-tap-plugin-datadir-lifecycle`.

    manage.py plugin_data list
    manage.py plugin_data purge <slug> [--yes] [--delete-state]

``list`` prints every directory with its status (declared, orphan, stray) and the facts the plugin
report carries. ``purge`` is the only deletion path core provides: it prints what it will delete,
needs ``--yes``, needs ``--delete-state`` as well for a ``"state"`` directory or an orphan whose
description is missing or says ``"state"``, and refuses while another TAP process has the plugin
loaded. To purge an installed plugin's directory, stop the services that load it first.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "List plugin data directories, or purge one plugin's directory."

    def add_arguments(self, parser: Any) -> None:
        sub = parser.add_subparsers(dest="action", required=True)
        sub.add_parser("list", help="Every plugin data directory with its status and facts.")
        purge = sub.add_parser("purge", help="Delete one plugin's data directory.")
        purge.add_argument("slug")
        purge.add_argument("--yes", action="store_true", help="Confirm the deletion.")
        purge.add_argument(
            "--delete-state",
            action="store_true",
            help='Also required for a "state" directory, or an orphan not known to be a cache.',
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["action"] == "list":
            self._list()
        else:
            self._purge(options["slug"], confirm=options["yes"], confirm_state=options["delete_state"])

    def _list(self) -> None:
        from tap_plugins.datadir import _placement, _report

        declared = _placement.declared_directories()
        instance = _report.instance_section(set(declared))
        if instance["volume_enabled"]:
            verdict = instance["verdict"]
            state = "usable" if verdict["usable"] else f"UNUSABLE: {verdict['reason']}"
            self.stdout.write(f"volume root: {instance['volume_root']} ({state})")
            fs = instance["filesystem"]
            if fs:
                self.stdout.write(
                    f"  filesystem={fs['type']} free_bytes={fs['free_bytes']} free_inodes={fs['free_inodes']}"
                )
        else:
            self.stdout.write(f"volume: not enabled; caches go under {instance['ephemeral_root']}")
        for slug, (declaration, _version) in declared.items():
            section = _report.plugin_section(slug, declaration)
            measured = section["measurement"]
            size = (
                f"{measured['allocated_bytes']} bytes, {measured['entry_count']} entries"
                + ("" if measured["complete"] else " (partial)")
                if measured["available"]
                else f"not measured: {measured['reason']}"
            )
            self.stdout.write(
                f"declared  {slug}: {section['durability']} at {section['path']} ({section['location']}); {size}"
                + ("" if section["as_provisioned"] or not section["exists"] else f"; {section['detail']}")
            )
        for slug in instance["orphans"]:
            self.stdout.write(f"orphan    {slug}")
        for name in instance["strays"]:
            self.stdout.write(f"stray     {name}")

    def _purge(self, slug: str, *, confirm: bool, confirm_state: bool) -> None:
        from tap_plugins.datadir import PluginDataDirectoryError
        from tap_plugins.datadir._purge import PurgeRefused, plan, purge

        try:
            the_plan = plan(slug)
        except (PurgeRefused, PluginDataDirectoryError) as exc:
            raise CommandError(str(exc)) from exc
        measured = the_plan.measurement
        self.stdout.write(f"Will delete: {the_plan.path}")
        self.stdout.write(f"  status={the_plan.status} durability={the_plan.durability}")
        if measured.get("available"):
            partial = "" if measured.get("complete") else " (partial count)"
            self.stdout.write(
                f"  measured {measured['allocated_bytes']} bytes, {measured['entry_count']} entries{partial}"
            )
        try:
            removed = purge(the_plan, confirm=confirm, confirm_state=confirm_state)
        except (PurgeRefused, PluginDataDirectoryError) as exc:
            raise CommandError(f"Nothing deleted: {exc}") from exc
        self.stdout.write(
            self.style.SUCCESS(f"Purged {the_plan.path}: {removed['bytes']} bytes, {removed['entries']} entries.")
        )
