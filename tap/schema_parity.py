"""Prove a model-built database equals a migrated one (req-boot-schema-from-models-5, tap#1258).

TAP-IMPLEMENTS: req-boot-schema-from-models@0481fbc263d3/44a94aa89a4c (enforcement) — the nightly
    check that the real migrations still run from zero and still produce exactly the schema the
    models build.

CI, dev stacks and test databases build their schema from the models (``manage.py
migrate_from_models``) and no longer replay the migrations. Two things could then rot unseen:
a migration that no longer applies from zero, and a migration history whose end state has drifted
from the models (a hand-edited migration, a ``RunPython`` that seeds rows, SQL a model cannot
describe). This replays both roads into two scratch databases and compares them:

* the schema, as ``pg_dump --schema-only`` text, one statement per entry, order-insensitive, with
  column order and generated object names taken out (``canonical``) and the understood
  differences in ``KNOWN_DIFFERENCES`` accepted by name: both reported, neither failed;
* the rows each road leaves behind (post_migrate's content types, permissions, the default
  site, …), per table, with surrogate ``id`` and timestamp columns left out;
* the ``django_migrations`` rows, by (app, name).

Runs INSIDE the web container, settings-free on purpose (the two builds are separate
``manage.py`` processes pointed at their own scratch database), with the stack's
``DATABASE_URL`` naming the server and credentials. Exit 0 on parity, 1 on any difference with
the difference printed, 2 when a build itself fails. Usage::

    uv run --no-sync python -m tap.schema_parity [--keep]
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess  # nosec B404 — fixed argv only (this interpreter + manage.py, pg_dump), never a shell
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATED = "migrated"
MODELS = "models"


@dataclass
class Build:
    road: str
    database: str
    command: str
    seconds: float = 0.0
    returncode: int | None = None
    output: str = ""


@dataclass
class Snapshot:
    statements: list[str]
    tables: dict[str, tuple[int, str]] = field(default_factory=dict)
    migrations: set[tuple[str, str]] = field(default_factory=set)


def _url_for(database: str) -> str:
    url = urlparse(os.environ["DATABASE_URL"])
    return urlunparse(url._replace(path="/" + database))


def _admin_connection() -> Any:
    import psycopg

    url = urlparse(os.environ["DATABASE_URL"])
    return psycopg.connect(
        host=url.hostname,
        port=url.port,
        user=url.username,
        password=url.password,
        dbname="postgres",
        autocommit=True,
    )


def _recreate(database: str, *, drop_only: bool = False) -> None:
    from psycopg import sql

    with _admin_connection() as admin, admin.cursor() as cursor:
        cursor.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
            (database,),
        )
        drop = sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database))
        cursor.execute(drop)  # nosemgrep  # nosec B608 — the name is quoted by psycopg.sql.Identifier
        if not drop_only:
            create = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database))
            cursor.execute(create)  # nosemgrep  # nosec B608 — the name is quoted by psycopg.sql.Identifier


def _start(build: Build) -> subprocess.Popen[str]:
    env = {**os.environ, "DATABASE_URL": _url_for(build.database)}
    # The cache table first, as the entrypoint does (the tap_health check needs it); it takes a second.
    subprocess.run(  # nosec B603  # nosemgrep — fixed argv: this interpreter + manage.py, no shell
        [sys.executable, "manage.py", "createcachetable"], cwd=REPO_ROOT, env=env, check=True
    )
    return subprocess.Popen(  # nosec B603  # nosemgrep — fixed argv: this interpreter + manage.py + a Build constant, no shell
        [sys.executable, "manage.py", build.command, "--noinput"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def run_builds(builds: list[Build]) -> None:
    """Run both builds at once: the migrate is the long one, and the model build overlaps it."""
    started = time.monotonic()

    def wait(build: Build, process: subprocess.Popen[str]) -> None:
        build.output, _ = process.communicate()
        build.returncode = process.returncode
        build.seconds = time.monotonic() - started

    threads = [threading.Thread(target=wait, args=(build, _start(build))) for build in builds]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


# pg_dump text that varies run to run without saying anything about the schema.
_NOISE = re.compile(r"^(--.*|SET .*|SELECT pg_catalog\.set_config.*|\\(un)?restrict .*)$")

# Names PostgreSQL or Django GENERATE, which depend on the order objects were created in, not on
# what they are: a NOT NULL constraint's name (PostgreSQL 18 names them, and a truncated name
# collides into `_not_null1`), an identity column's sequence name (same truncation), and a
# Django-generated constraint or index name (a unique added by AlterField is `<col>_<hash>_uniq`,
# the same unique in CREATE TABLE is `<col>_key`). A difference in these alone is reported, not
# failed: nothing reads them by name.
_GENERATED_NAMES = (
    (re.compile(r"CONSTRAINT \S+ NOT NULL"), "NOT NULL"),
    (re.compile(r"SEQUENCE NAME \S+ "), "SEQUENCE NAME <generated> "),
    (re.compile(r"ADD CONSTRAINT \S+ "), "ADD CONSTRAINT <generated> "),
    (re.compile(r"^CREATE (UNIQUE )?INDEX \S+ ON "), r"CREATE \1INDEX <generated> ON "),
)
_CREATE_TABLE = re.compile(r"^(CREATE TABLE \S+ \( )(.*)( \))$")
_TOP_LEVEL_COMMA = re.compile(r", (?![^()]*\))")

_M2M_QUIRK = "auto-created M2M id: bigint migrated, integer from the models (Django state quirk)"

#: Differences that are real, understood, and accepted — each with the reason. Keyed by table, but
#: only the id width is accepted: a table's statements must match exactly once the id column's
#: bigint/integer is set aside (``_id_width_neutral``), so any other drift there still fails.
#: Django renders the migration state with stub app configs that carry no ``default_auto_field``,
#: so an auto-created many-to-many table of an app whose AppConfig pins ``AutoField`` (auth,
#: socialaccount) gets ``settings.DEFAULT_AUTO_FIELD`` (bigint) when MIGRATED and the app's own
#: AutoField (integer) when built from the MODELS. Both ids work; the models are the truth.
KNOWN_DIFFERENCES: dict[str, str] = {
    "public.auth_group_permissions": _M2M_QUIRK,
    "public.socialaccount_socialapp_sites": _M2M_QUIRK,
}


_ID_WIDTH = re.compile(r"\b(id (?:bigint|integer)|AS (?:bigint|integer))\b")


def _id_width_neutral(statement: str) -> str:
    """The statement with the id column's width (and its identity sequence's) set aside."""
    return _ID_WIDTH.sub(lambda m: m.group(1).rsplit(" ", 1)[0] + " <int>", statement)


def schema_statements(dump: str) -> list[str]:
    """``pg_dump --schema-only`` text as a sorted list of whitespace-normalised statements."""
    lines = [line for line in dump.splitlines() if line.strip() and not _NOISE.match(line.strip())]
    statements = [" ".join(chunk.split()) for chunk in "\n".join(lines).split(";\n")]
    return sorted(s.rstrip(";") for s in statements if s.strip())


def canonical(statement: str) -> str:
    """The statement with column order and generated names taken out of it.

    Column order: a migration appends an added column at the end, the models list it where it is
    declared, and PostgreSQL addresses columns by name.
    """
    for pattern, replacement in _GENERATED_NAMES:
        statement = pattern.sub(replacement, statement)
    table = _CREATE_TABLE.match(statement)
    if table:
        columns = sorted(_TOP_LEVEL_COMMA.split(table.group(2)))
        statement = table.group(1) + ", ".join(columns) + table.group(3)
    return statement


def _table_of(statement: str) -> str | None:
    match = re.match(r"^(?:CREATE TABLE|ALTER TABLE(?: ONLY)?) (\S+)", statement)
    return match.group(1) if match else None


def _dump_schema(database: str) -> str:
    pg_dump = shutil.which("pg_dump")
    if pg_dump is None:
        raise RuntimeError("pg_dump is not on PATH; the schema comparison needs it")
    argv = [pg_dump, "--schema-only", "--no-owner", "--no-privileges", "--dbname", _url_for(database)]
    result = subprocess.run(  # nosec B603  # nosemgrep — fixed argv: the resolved pg_dump + a scratch database URL
        argv,  # nosemgrep
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _table_rows(cursor: Any, table: str) -> tuple[int, str]:
    """(row count, digest of the rows), order-insensitive.

    Left out: the surrogate ``id`` (a sequence is an accident of insertion order) and every
    timestamp column (``applied``, ``synced_at``: when this run wrote the row, not what it wrote).
    """
    from psycopg import sql

    cursor.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s ORDER BY column_name",
        (table,),
    )
    columns = [name for name, kind in cursor.fetchall() if name != "id" and not kind.startswith("timestamp")]
    if not columns:
        count = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
        cursor.execute(count)  # nosemgrep  # nosec B608 — the name is quoted by psycopg.sql.Identifier
        return int(cursor.fetchone()[0]), ""
    selected = sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    query = sql.SQL("SELECT {} FROM {}").format(selected, sql.Identifier(table))
    cursor.execute(query)  # nosemgrep  # nosec B608 — every name is quoted by psycopg.sql.Identifier
    rows = sorted(json.dumps(row, default=str, sort_keys=True) for row in cursor.fetchall())
    return len(rows), hashlib.sha256("\n".join(rows).encode()).hexdigest()


def snapshot(database: str) -> Snapshot:
    import psycopg

    shot = Snapshot(statements=schema_statements(_dump_schema(database)))
    with psycopg.connect(_url_for(database)) as conn, conn.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")
        for (table,) in cursor.fetchall():
            shot.tables[table] = _table_rows(cursor, table)
        cursor.execute("SELECT app, name FROM django_migrations")
        shot.migrations = {(app, name) for app, name in cursor.fetchall()}
    return shot


def compare(migrated: Snapshot, models: Snapshot) -> tuple[list[str], list[str]]:
    """(problems, notes) between the two roads; no problems means parity.

    Notes name what differs only in column order or generated names, and the accepted
    KNOWN_DIFFERENCES: reported so a reader sees them, never failed.
    """
    problems: list[str] = []
    notes: list[str] = []
    left = Counter(canonical(s) for s in migrated.statements)
    right = Counter(canonical(s) for s in models.statements)
    only_migrated, only_models = left - right, right - left
    for table, reason in sorted(KNOWN_DIFFERENCES.items()):
        mine = [s for s in only_migrated if _table_of(s) == table]
        theirs = [s for s in only_models if _table_of(s) == table]
        if (mine or theirs) and Counter(map(_id_width_neutral, mine)) == Counter(map(_id_width_neutral, theirs)):
            notes.append(f"accepted difference in {table}: {reason}")
            for statement in mine:
                del only_migrated[statement]
            for statement in theirs:
                del only_models[statement]
    if only_migrated or only_models:
        diff = difflib.unified_diff(
            sorted(only_migrated.elements()), sorted(only_models.elements()), MIGRATED, MODELS, lineterm="", n=0
        )
        problems.append("schema differs (pg_dump --schema-only; column order and generated names aside):")
        problems.extend("  " + line for line in diff if not line.startswith("@@"))
    cosmetic = [
        s
        for s in sorted(set(migrated.statements) ^ set(models.statements))
        if canonical(s) not in only_migrated
        and canonical(s) not in only_models
        and canonical(s) in left
        and canonical(s) in right
    ]
    if cosmetic:
        notes.append(f"{len(cosmetic)} statement(s) differ only in column order or generated names, e.g.:")
        notes.extend("  " + s[:200] for s in cosmetic[:6])
    for table in sorted(set(migrated.tables) | set(models.tables)):
        a, b = migrated.tables.get(table), models.tables.get(table)
        if a != b:
            problems.append(f"rows differ in {table}: migrated {a and a[0]} row(s), models {b and b[0]}")
    for app, name in sorted(migrated.migrations ^ models.migrations):
        side = MIGRATED if (app, name) in migrated.migrations else MODELS
        problems.append(f"django_migrations: {app}.{name} recorded only by the {side} road")
    return problems, notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tap.schema_parity", description=__doc__.split("\n\n")[0])
    parser.add_argument("--prefix", default="tap_parity", help="scratch database name prefix")
    parser.add_argument("--keep", action="store_true", help="leave the two scratch databases for inspection")
    args = parser.parse_args(argv)

    builds = [
        Build(MIGRATED, f"{args.prefix}_migrated", "migrate"),
        Build(MODELS, f"{args.prefix}_models", "migrate_from_models"),
    ]
    for build in builds:
        _recreate(build.database)
    try:
        run_builds(builds)
        for build in builds:
            took = f"{build.seconds:.1f}s"
            print(f"{build.road:>8}: manage.py {build.command} finished in {took} (exit {build.returncode})")
        failed = [build for build in builds if build.returncode != 0]
        for build in failed:
            print(f"::error::the {build.road} build failed (manage.py {build.command}):\n{build.output[-6000:]}")
        if failed:
            return 2
        problems, notes = compare(snapshot(builds[0].database), snapshot(builds[1].database))
    finally:
        if not args.keep:
            for build in builds:
                _recreate(build.database, drop_only=True)
    if notes:
        print("\n".join(notes))
    if problems:
        print("::error::a model-built database differs from a migrated one:")
        print("\n".join(problems))
        return 1
    print("parity: the model-built database equals the migrated one (schema, rows, recorded migrations)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
