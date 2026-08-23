"""`manage.py guards` — the generated Validation Map (guards are the system of record).

Enumerates every registered `Guard` and prints what each declares about itself, so
the Validation Map is *read off the code* rather than hand-maintained. `--check` runs
each guard and reports live pass/fail; `--json` emits machine-readable output;
`--map` prints the generated Map table (guards ∪ declared surfaces); `--sync-map`
writes that table into the generated block in `spec-dev-validation.md`; `--sarif`
emits a SARIF 2.1.0 log of the callsite ratchets' per-offense findings.

Lives in tap_boot (the dev-validation gate's home, alongside `cold_boot_gate`).
Read-only except `--sync-map`/`--sync-mypy`, which regenerate committed artifacts
from the code (reviewed changes only).
"""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from tap.guards.base import REPO_ROOT
from tap.guards.report import MAP_BEGIN, MAP_END, build_report, render_map_markdown, render_sarif

_SPEC_PATH = REPO_ROOT / "specs" / "spec-dev-validation.md"


class Command(BaseCommand):
    help = "List the registered development-time guards (the generated Validation Map)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--check",
            action="store_true",
            help="Run each guard's check() and report live pass/fail (slower: some fork pytest).",
        )
        parser.add_argument("--json", action="store_true", help="Emit JSON instead of a table.")
        parser.add_argument(
            "--map",
            action="store_true",
            help="Print the generated Validation Map table (guards ∪ declared surfaces).",
        )
        parser.add_argument(
            "--sarif",
            action="store_true",
            help="Emit a SARIF 2.1.0 log of the callsite ratchets' per-offense findings (baselined debt as suppressed).",
        )
        parser.add_argument(
            "--sync-map",
            action="store_true",
            help="Write the generated Map into the marked block in spec-dev-validation.md (reviewed changes only).",
        )
        parser.add_argument(
            "--sync-mypy",
            action="store_true",
            help="Regenerate the mypy ratchet baseline from the current `mypy .` state (reviewed changes only).",
        )
        parser.add_argument(
            "--sync-evidence",
            action="store_true",
            help=(
                "Write the generated requirement-evidence report into the marked block in "
                "spec-tap-requirement-traceability.md (reviewed changes only)."
            ),
        )
        parser.add_argument(
            "--sync-accounting",
            action="store_true",
            help=(
                "Write the generated full-corpus accounting into the marked block in "
                "spec-tap-requirement-traceability.md (reviewed changes only)."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["sync_accounting"]:
            self._sync_accounting()
            return
        if options["sync_evidence"]:
            self._sync_evidence()
            return
        if options["sync_mypy"]:
            self._sync_mypy()
            return
        if options["sync_map"]:
            self._sync_map()
            return
        if options["map"]:
            self.stdout.write(render_map_markdown())
            return
        if options["sarif"]:
            self.stdout.write(json.dumps(render_sarif(), indent=2))
            return

        rows = build_report(run_checks=options["check"])

        if options["json"]:
            self.stdout.write(json.dumps([r.as_dict() for r in rows], indent=2))
            return

        self.stdout.write(f"{len(rows)} registered guard(s):\n")
        for row in rows:
            if row.passed is None:
                status = ""
            elif row.passed:
                status = self.style.SUCCESS("  PASS")
            else:
                status = self.style.ERROR("  FAIL")
            rid_flag = "" if row.rid_resolves else self.style.WARNING("  [rid unresolved]")
            self.stdout.write(f"• {row.slug}{status}{rid_flag}")
            self.stdout.write(f"    map row: {row.map_row}")
            self.stdout.write(f"    rid:     {row.rid}")
            self.stdout.write(f"    module:  {row.module}")
            self.stdout.write(f"    why:     {row.description}")
            if row.error:
                self.stdout.write(self.style.ERROR(f"    error:   {row.error}"))
            self.stdout.write("")

    def _sync_evidence(self) -> None:
        """Replace the marked block in the traceability spec with the evidence report.

        Same shape as `_sync_map`: a generated artifact committed into the spec, with a
        drift test asserting the committed copy equals what the tree now produces. That is
        what makes the report a *consumer* of the claims rather than a thing someone could
        forget to look at.
        """
        from tap.spec_trace import EVIDENCE_BEGIN, EVIDENCE_END, render_evidence_markdown

        path = REPO_ROOT / "specs" / "spec-tap-requirement-traceability.md"
        text = path.read_text(encoding="utf-8")
        try:
            before, rest = text.split(EVIDENCE_BEGIN, 1)
            _, after = rest.split(EVIDENCE_END, 1)
        except ValueError as exc:
            raise CommandError(
                f"Could not find the evidence markers ({EVIDENCE_BEGIN!r} … {EVIDENCE_END!r}) in {path}."
            ) from exc
        path.write_text(before + render_evidence_markdown(REPO_ROOT) + after, encoding="utf-8")
        self.stdout.write("Synced the generated evidence report into spec-tap-requirement-traceability.md.")

    def _sync_accounting(self) -> None:
        """Replace the marked block in the traceability spec with the full-corpus accounting.

        The evidence report's complement: that one is read for contradictions, this one for
        progress — the Unaccounted headline is the Definition of Done's progress bar
        (`req-tap-traceability-accounting-3`).
        """
        from tap.spec_trace import ACCOUNTING_BEGIN, ACCOUNTING_END, render_accounting_markdown

        path = REPO_ROOT / "specs" / "spec-tap-requirement-traceability.md"
        text = path.read_text(encoding="utf-8")
        try:
            before, rest = text.split(ACCOUNTING_BEGIN, 1)
            _, after = rest.split(ACCOUNTING_END, 1)
        except ValueError as exc:
            raise CommandError(
                f"Could not find the accounting markers ({ACCOUNTING_BEGIN!r} … {ACCOUNTING_END!r}) in {path}."
            ) from exc
        path.write_text(before + render_accounting_markdown(REPO_ROOT) + after, encoding="utf-8")
        self.stdout.write("Synced the generated accounting into spec-tap-requirement-traceability.md.")

    def _sync_map(self) -> None:
        """Replace the marked block in spec-dev-validation.md with the generated Map."""
        text = _SPEC_PATH.read_text(encoding="utf-8")
        try:
            before, rest = text.split(MAP_BEGIN, 1)
            _, after = rest.split(MAP_END, 1)
        except ValueError as exc:
            raise CommandError(
                f"Could not find the Map markers ({MAP_BEGIN!r} … {MAP_END!r}) in {_SPEC_PATH}."
            ) from exc
        updated = before + render_map_markdown() + after
        _SPEC_PATH.write_text(updated, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Synced the generated Map into {_SPEC_PATH.name}."))

    def _sync_mypy(self) -> None:
        """Regenerate the mypy ratchet baseline from the current `mypy .` state.

        Single source of the header + sort order the guard reads back, so a reviewed
        typing change re-baselines in one command instead of by hand.
        """
        from tap.guards.mypy import BASELINE_PATH, mypy_error_counts

        counts = mypy_error_counts()
        lines = sorted(f"{key}:{count}" for key, count in counts.items())
        header = [
            "# mypy strict-mode baseline (req-dev-validation-mypy-ratchet). One line per file+error-code:",
            "#   <path>:<error-code>:<count>",
            "# Frozen debt, mostly django-stubs friction + test no-untyped-call cascade (audited: not bugs).",
            "# A NEW error bumps a count -> ratchet fails. Regenerate ONLY for a reviewed change:",
            "#   manage.py guards --sync-mypy",
        ]
        BASELINE_PATH.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
        self.stdout.write(
            self.style.SUCCESS(f"Wrote {len(lines)} baseline line(s), {sum(counts.values())} total mypy error(s).")
        )
