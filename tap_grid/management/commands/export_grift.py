"""Serialise this grid to a re-importable GRIFT v0 document.

Usage:
    docker compose exec web uv run python manage.py export_grift --output /app/snapshot.grift.json
    docker compose exec web uv run python manage.py export_grift --output - --compact
    docker compose exec web uv run python manage.py export_grift \\
        --output /app/last-week.grift.json --since 2026-09-14T00:00:00Z

The reverse direction of `manage.py import_plugin_grift`: what this writes,
that reads. The document names a single batch whose provenance says the rows
were CAPTURED from a run on a date — it never claims live collection.

Scope is the whole grid, optionally bounded on `Entity.updated_at`. There is no
selection or reachability logic and no redaction (Issue# 736 - tap).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.utils.dateparse import parse_datetime

from tap_grid.grift.exporter import SKIP_SAMPLE_CAP, GriftExportResult, export_grid


class Command(BaseCommand):
    help = "Serialise this grid to a re-importable GRIFT v0 document."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--output",
            dest="output",
            required=True,
            help="Path to write the .grift.json document to, or '-' for stdout.",
        )
        parser.add_argument(
            "--since",
            dest="since",
            default=None,
            help=(
                "ISO 8601 lower bound on Entity.updated_at. Nodes outside the window are "
                "left out, and any edge that loses an endpoint with them is left out too "
                "(and counted) so the document stays self-contained."
            ),
        )
        parser.add_argument(
            "--until",
            dest="until",
            default=None,
            help="ISO 8601 upper bound on Entity.updated_at.",
        )
        parser.add_argument(
            "--name",
            dest="name",
            default="",
            help="Human-readable name for the captured batch.",
        )
        parser.add_argument(
            "--description",
            dest="description",
            default="",
            help=(
                "Prose APPENDED to the batch's provenance sentence. It cannot replace it: "
                "the captured-not-collected claim is not the operator's to edit."
            ),
        )
        parser.add_argument(
            "--batch-entity-id",
            dest="batch_entity_id",
            default=None,
            help=(
                "UUID for the batch this export mints. Defaults to a fresh UUIDv7. Reusing "
                "an id a target grid already holds makes the document INERT there — the "
                "importer skips an already-imported batch."
            ),
        )
        parser.add_argument(
            "--compact",
            dest="compact",
            action="store_true",
            default=False,
            help="Write minified JSON (no indentation). Smaller file, unreadable diff.",
        )
        parser.add_argument(
            "--allow-invalid",
            dest="allow_invalid",
            action="store_true",
            default=False,
            help=(
                "Write the document even when the importer's own validators reject a "
                "record in it. Off by default: an export that cannot be re-imported is a "
                "file, not a snapshot."
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        since = self._parse_bound(options["since"], "--since")
        until = self._parse_bound(options["until"], "--until")
        if since is not None and until is not None and until < since:
            raise CommandError("--until is earlier than --since; the window is empty.")

        result = export_grid(
            since=since,
            until=until,
            batch_entity_id=options["batch_entity_id"] or None,
            name=options["name"],
            description=options["description"],
        )

        payload = (
            json.dumps(
                result.document,
                indent=None if options["compact"] else 2,
                separators=(",", ":") if options["compact"] else None,
                sort_keys=False,
                ensure_ascii=False,
            )
            + "\n"
        )
        # The reported size is the size of the BYTES WRITTEN, trailing newline
        # included — a reported figure that is a byte off the file on disk is a
        # small false declaration, and the whole point of this command's output
        # is that its numbers can be trusted.
        size_bytes = len(payload.encode("utf-8"))

        self._report(result, size_bytes)

        if result.issues and not options["allow_invalid"]:
            for issue in result.issues[:20]:
                self.stderr.write(self.style.ERROR(f"  {issue.code} at {issue.path}: {issue.message}"))
            if len(result.issues) > 20:
                self.stderr.write(self.style.ERROR(f"  ... and {len(result.issues) - 20} more."))
            raise CommandError(
                f"{len(result.issues)} record(s) in this grid cannot be expressed as a re-importable "
                "GRIFT document; refusing to write. Re-run with --allow-invalid to write it anyway."
            )

        destination = options["output"]
        if destination == "-":
            sys.stdout.write(payload)
            return

        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Wrote {path} ({size_bytes:,} bytes)."))

    # ------------------------------------------------------------------

    def _parse_bound(self, raw: str | None, flag: str) -> datetime | None:
        if not raw:
            return None
        parsed = parse_datetime(raw)
        if parsed is None:
            raise CommandError(f"{flag} is not an ISO 8601 datetime: {raw!r}")
        if parsed.tzinfo is None:
            raise CommandError(f"{flag} must carry a timezone offset (e.g. ...Z or +00:00): {raw!r}")
        return parsed

    def _report(self, result: GriftExportResult, size_bytes: int) -> None:
        self.stdout.write(f"Batch {result.batch_entity_id} captured at {result.captured_at.isoformat()}")
        self.stdout.write(f"Serialised size: {size_bytes:,} bytes ({size_bytes / 1_048_576:.2f} MiB)")
        self.stdout.write(f"Nodes: {result.node_total} across {len(result.node_counts)} type(s)")
        for entity_type, count in result.node_counts.items():
            self.stdout.write(f"    {count:>8}  {entity_type}")
        self.stdout.write(f"Edges: {result.edge_total} across {len(result.edge_counts)} type(s)")
        for edge_type, count in result.edge_counts.items():
            self.stdout.write(f"    {count:>8}  {edge_type}")

        if not result.skipped:
            self.stdout.write("Skipped: none.")
            return
        self.stdout.write(self.style.WARNING("Skipped (exact counts; ids are a sample, not the set):"))
        for reason, count in result.skipped.items():
            sample = result.skipped_sample.get(reason, [])
            shown = ", ".join(sample)
            more = "" if count <= SKIP_SAMPLE_CAP else f" (+{count - SKIP_SAMPLE_CAP} more not listed)"
            self.stdout.write(self.style.WARNING(f"    {count:>8}  {reason}: {shown}{more}"))
