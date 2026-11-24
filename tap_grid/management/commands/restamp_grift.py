"""
Restate format "0" GRIFT documents at format "1" (req-grift-header-versions rule 12, Issue# 1288 - tap).

Usage:
    docker compose exec web uv run python manage.py restamp_grift PATH [PATH ...]      # in place
    docker compose exec web uv run python manage.py restamp_grift FILE --out NEW_FILE
    docker compose exec web uv run python manage.py restamp_grift DIRECTORY --check    # report only

A PATH is a document or a directory, which stands for every ``*.grift.json`` beneath it. Each "0"
document gets ``grift_version`` "1", ``spine_version`` 1 and a ``type_versions`` entry of 1 for every
type it carries or names, which is how a "0" document has always been read (rule 11). Only the header's
text changes; every record is left byte for byte as it was (``tap_grid.grift.restamp``).

A document already at "1" is refused, naming it; with ``--check`` it is reported and nothing fails for
it. A document naming a type nothing installed registers is refused, naming the type. ``--check``
writes nothing and exits non-zero when a document would change or is refused, so CI can hold a tree
at "1".
"""

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from tap_grid.grift.restamp import RestampRefused, documents_under, restamp_path


class Command(BaseCommand):
    help = 'Restate format "0" GRIFT documents at format "1", changing only the header'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("paths", nargs="+", help="Documents, or directories of *.grift.json documents")
        parser.add_argument("--out", help="Write the one document named to this path instead of in place")
        parser.add_argument("--check", action="store_true", help="Report what would change; write nothing")

    def handle(self, *args: Any, **options: Any) -> None:
        targets: list[Path] = []
        for raw in options["paths"]:
            path = Path(raw)
            if path.is_dir():
                targets.extend(documents_under(path))
            elif path.is_file():
                targets.append(path)
            else:
                raise CommandError(f"{path}: no such file or directory")
        out = Path(options["out"]) if options.get("out") else None
        if out is not None and len(targets) != 1:
            raise CommandError("--out names one destination, so it takes exactly one document")
        check = options["check"]
        problems: list[str] = []
        pending = 0
        for path in targets:
            try:
                result = restamp_path(path, out=out, write=not check)
            except RestampRefused as refusal:
                problems.append(f"{path}: {refusal}")
                continue
            if not result.changed:
                if check:
                    self.stdout.write(f"{path}: {result.note}")
                else:
                    problems.append(f"{path}: {result.note}; nothing to restamp")
                continue
            pending += 1
            types = ", ".join(sorted(result.header["type_versions"]))
            verb = "would restamp" if check else "restamped"
            self.stdout.write(f"{path}: {verb} to grift_version \"1\" (spine 1; types at 1: {types})")
        for problem in problems:
            self.stderr.write(problem)
        self.stdout.write(f"{len(targets)} document(s); {pending} {'to restamp' if check else 'restamped'}; {len(problems)} refused")
        if problems or (check and pending):
            raise CommandError(
                f"{len(problems)} document(s) refused" if problems else f"{pending} document(s) still at grift_version \"0\""
            )
