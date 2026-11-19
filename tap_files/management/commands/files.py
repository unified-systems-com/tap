"""`manage.py files check` — the report-only file store check (`req-tap-files-check`).

  manage.py files check            # human table
  manage.py files check --deep     # also re-hash every content file
  manage.py files check --json     # the report as JSON (tap_files/schemas/check-report.schema.json)
  manage.py files check --strict   # a notice fails too

Exit codes: 0 nothing to report (or only notices without ``--strict``), 1 a fault was found (or a
notice under ``--strict``), 2 the store is not enabled. The command writes nothing and takes no lock;
recovery is boot's (`req-tap-files-write`).
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand

from tap_auth.actors import BOOTLOADER, acting_as, get_builtin_actor
from tap_files.check import FileStoreNotEnabled, run_check

EXIT_FAULT = 1
EXIT_NOT_ENABLED = 2


class Command(BaseCommand):
    help = "Report on the file store against itself and the grid; changes nothing (exit 0 clean / 1 fault / 2 off)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("action", choices=["check"], help="The only action: check.")
        parser.add_argument("--deep", action="store_true", help="Also re-hash every content file against its digest.")
        parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
        parser.add_argument("--strict", action="store_true", help="Fail on a notice too.")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            # The grid is read as the bootloader, as the other operator commands read it.
            with acting_as(get_builtin_actor(BOOTLOADER)):
                report = run_check(deep=options["deep"])
        except FileStoreNotEnabled as exc:
            self.stderr.write(str(exc))
            raise SystemExit(EXIT_NOT_ENABLED) from None
        if options["json"]:
            self.stdout.write(json.dumps(report.as_json(), indent=2, sort_keys=True))
        else:
            self._table(report)
        if report.failed(strict=options["strict"]):
            raise SystemExit(EXIT_FAULT)

    def _table(self, report: Any) -> None:
        mode = "deep" if report.deep else "shallow"
        self.stdout.write(f"File store {report.root} ({mode} check)")
        for f in report.findings:
            where = f"  [{f.path}]" if f.path else ""
            self.stdout.write(f"  {f.severity.upper():6}  {f.kind:28}  {f.subject}  {f.detail}{where}")
        for item in report.quarantine:
            self.stdout.write(f"  QUARANTINE  {item['item']}  was {item['was'] or '?'}: {item['why']}")
        totals = ", ".join(f"{v} {k}" for k, v in report.totals.items())
        faults = sum(f.severity == "fault" for f in report.findings)
        notices = len(report.findings) - faults
        self.stdout.write(f"  {faults} fault(s), {notices} notice(s); {totals}")
