"""`manage.py plugins` — the read-only plugin registry/report surface.

req-tap-plugin-arch-install-registry -3/-5 (spec-tap-plugin-architecture.md). Serializes the
facts boot/Django already hold — installed plugins, provenance, install mode, declared
vs loaded surfaces, load health, and the bidirectional cross-plugin dependency graph
(both `depends_on` and `required_by` on every row). Read-only: no graph writes (inside
the tap_ai v0 read boundary). The same `tap_plugins.report.build_report()` service backs
the administrivia status page.

  manage.py plugins           # human-readable table
  manage.py plugins --json    # the full machine/AI report (schema-validated)

The CLI is a trusted operator surface (like `manage.py health`), so it prints the full
report without a capability check; the web/service exposure is gated by `plugins.read`.
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand

from tap_plugins.report import build_report


class Command(BaseCommand):
    help = "Report installed TAP plugins: identity, provenance, surfaces, health, and dependency edges."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="Emit the full machine-readable report as JSON (schema: plugin-report.schema.json).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        report = build_report()
        if options["as_json"]:
            self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
            return
        self._write_human(report)

    def _write_human(self, report: dict[str, Any]) -> None:
        self.stdout.write(self.style.SUCCESS(f"{report['plugin_count']} plugin(s):"))
        for p in report["plugins"]:
            health = p["load_health"]
            status = "ok" if health["loaded"] and health["manifest_valid"] else "DEGRADED"
            styler = self.style.SUCCESS if status == "ok" else self.style.WARNING
            ver = p["version"] or "?"
            commit = f"@{p['commit'][:8]}" if p["commit"] else ""
            self.stdout.write(styler(f"  {p['slug']} ({p['distribution']} {ver}{commit}) [{status}]"))
            self.stdout.write(f"      source={p['source']} mode={p['mode']}")
            s = p["surfaces"]
            self.stdout.write(
                "      surfaces: "
                + ", ".join(
                    f"{k}={v['declared']}" + (f"/{v['loaded']} loaded" if v["loaded"] is not None else "")
                    for k, v in s.items()
                )
            )
            deps = p["dependencies"]
            self.stdout.write(f"      depends_on: {', '.join(deps['depends_on']) or '(none)'}")
            self.stdout.write(f"      required_by: {', '.join(deps['required_by']) or '(none)'}")
            if deps["undeclared_imports"]:
                self.stdout.write(
                    self.style.ERROR(f"      UNDECLARED imports: {', '.join(deps['undeclared_imports'])}")
                )
