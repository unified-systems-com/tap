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
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser, OutputWrapper
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

        # When the document goes to stdout, the human report goes to STDERR.
        # Otherwise `export_grift --output - | grift_import` — the usage this
        # command's own docstring advertises — ships a JSON stream with
        # "Batch <uuid> captured at ..." nailed to the front of it, which is not
        # GRIFT and never will be (found by the PR's AI review, both seats).
        destination = options["output"]
        report_stream = self.stderr if destination == "-" else self.stdout
        self._report(result, size_bytes, report_stream)

        if result.issues and not options["allow_invalid"]:
            for issue in result.issues[:20]:
                self.stderr.write(self.style.ERROR(f"  {issue.code} at {issue.path}: {issue.message}"))
            if len(result.issues) > 20:
                self.stderr.write(self.style.ERROR(f"  ... and {len(result.issues) - 20} more."))
            raise CommandError(
                f"{len(result.issues)} record(s) in this grid fail the importer's own document and "
                "per-record validators; refusing to write. Re-run with --allow-invalid to write it "
                "anyway. (Passing is necessary, not sufficient: `full_validate` and the edge-type "
                "constraint checks run against the database of the grid being imported INTO, which "
                "this cannot reach.)"
            )

        if destination == "-":
            # `self.stdout`, not `sys.stdout`: the wrapper is what `call_command`
            # captures, so the payload is testable and a caller-supplied stream
            # is honoured. The payload already ends in a newline, so the wrapper
            # adds none.
            self.stdout.write(payload)
            return

        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_private(path, payload)
        self.stdout.write(self.style.SUCCESS(f"Wrote {path} ({size_bytes:,} bytes, mode 0600)."))

    # ------------------------------------------------------------------

    def _write_private(self, path: Path, payload: str) -> None:
        """Write the document readable only by its owner.

        This file is the WHOLE grid with no redaction — the widest artifact this
        system produces. `Path.write_text()` would create it at the process
        umask, commonly 0644, so on a shared volume or a multi-tenant container
        every local user and sidecar gets a copy of everything (found by the
        PR's AI review). The cheap, foundational edge is to never create it
        readable in the first place: 0600 at creation, not a chmod after, so
        there is no window where the bytes exist at 0644.

        `os.open`'s mode applies only when the file is CREATED, and is masked by
        the umask (so it can land stricter, never looser). An existing file — a
        re-cut over yesterday's snapshot — keeps whatever mode it had, so
        `fchmod` follows and sets exactly 0600 on the descriptor either way.
        """
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        descriptor = os.open(path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
        except BaseException:
            os.close(descriptor)
            raise
        # `fdopen` takes ownership of the descriptor from here; closing it in an
        # error path above this line would be a double close.
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)

    def _parse_bound(self, raw: str | None, flag: str) -> datetime | None:
        if not raw:
            return None
        parsed = parse_datetime(raw)
        if parsed is None:
            raise CommandError(f"{flag} is not an ISO 8601 datetime: {raw!r}")
        if parsed.tzinfo is None:
            raise CommandError(f"{flag} must carry a timezone offset (e.g. ...Z or +00:00): {raw!r}")
        return parsed

    def _report(self, result: GriftExportResult, size_bytes: int, out: OutputWrapper) -> None:
        out.write(f"Batch {result.batch_entity_id} captured at {result.captured_at.isoformat()}")
        out.write(f"Serialised size: {size_bytes:,} bytes ({size_bytes / 1_048_576:.2f} MiB)")
        out.write(f"Nodes: {result.node_total} across {len(result.node_counts)} type(s)")
        for entity_type, count in result.node_counts.items():
            out.write(f"    {count:>8}  {entity_type}")
        out.write(f"Edges: {result.edge_total} across {len(result.edge_counts)} type(s)")
        for edge_type, count in result.edge_counts.items():
            out.write(f"    {count:>8}  {edge_type}")

        if not result.skipped:
            out.write("Skipped: none.")
            return
        out.write(self.style.WARNING("Skipped (exact counts; ids are a sample, not the set):"))
        for reason, count in result.skipped.items():
            sample = result.skipped_sample.get(reason, [])
            shown = ", ".join(sample)
            more = "" if count <= SKIP_SAMPLE_CAP else f" (+{count - SKIP_SAMPLE_CAP} more not listed)"
            out.write(self.style.WARNING(f"    {count:>8}  {reason}: {shown}{more}"))
