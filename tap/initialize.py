"""The initializer: one installation's identity, minted once and kept (req-tap-bake-initializer).

A product image started from a deploy config has no source of identity of its own. This module,
run first by ``docker/entrypoint.sh`` in a product image whose deploy config names an installation
volume, gives it one. It mints the secret key, the database role passwords and the grid id once,
keeps them in the installation's state store, and hands them to the rest of the start. Like
pre-boot it is settings-free: it runs before Django reads a single setting, because the settings
it would read are what it produces.

This is the first slice (tap#1328). It has no seed, so the only roads are:

- an empty database and no identity: activate, then Finish (the full initialization);
- an active identity: Finish only (a restart, or a replacement container);
- a pending identity: re-apply the stored values, never mint again;
- anything else: refuse, writing nothing.

Activation mints first and writes second (`req-tap-bake-activate`): every value is minted and
stored as ``pending`` before anything changes, applied idempotently from the stored value, then
marked ``active``. An interruption between any two writes therefore never mints a second value.

The whole run holds a session advisory lock on the cluster's maintenance database, keyed on the
installation's database, so a second start waits instead of racing (`req-tap-bake-initializer-1`).

CLI:

- ``python -m tap.initialize run``: classify, activate if needed, write the hand-off env file.
  Prints ``activated``, ``finish`` or ``skipped`` on stdout for the entrypoint.
- ``python -m tap.initialize mark finish``: record that boot (Finish) completed.
- ``python -m tap.initialize mark first-login``: record that the one-time admin link was issued.
- ``python -m tap.initialize status first-login``: print ``issued`` or ``pending``.

Spec: specs/spec-tap-baked-instance.md (`req-tap-bake-initializer`, `req-tap-bake-activate`,
`req-tap-bake-installation-identity`).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import secrets
import shlex
import sys
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, quote, unquote, urlsplit, urlunsplit

import psycopg
from psycopg import sql

from tap.logging import abort

logger = logging.getLogger("tap.initialize")

STATE_SCHEMA = "tap.installation-identity/1"
IDENTITY_FILE = "identity.json"
HANDOFF_PATH = Path("/run/tap/installation.env")
MAINTENANCE_DB = "postgres"

# Statuses of the identity record.
PENDING = "pending"
ACTIVE = "active"

# Roads (`req-tap-bake-initializer`'s classification table, the rows this slice has).
ROAD_ACTIVATE = "activate"
ROAD_RESUME = "resume"
ROAD_FINISH = "finish"
ROAD_LEGACY = "legacy"


class InitializeError(RuntimeError):
    """The initializer refuses: the stores disagree, or hold something it does not recognise."""


# =============================================================================
# The installation's state store
# =============================================================================


@dataclass(frozen=True)
class StateStore:
    """The installation's private directory: a volume of the stack, never the image's layer."""

    root: Path

    @property
    def identity_path(self) -> Path:
        return self.root / IDENTITY_FILE

    def read(self) -> dict[str, Any] | None:
        path = self.identity_path
        if not path.exists():
            return None
        record: dict[str, Any] = json.loads(path.read_text())
        if record.get("schema") != STATE_SCHEMA:
            raise InitializeError(f"{path}: schema {record.get('schema')!r}, expected {STATE_SCHEMA!r}")
        return record

    def write(self, record: dict[str, Any]) -> None:
        """Replace the record atomically, readable by this user only."""
        tmp = self.root / f".{IDENTITY_FILE}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(record, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.identity_path)


def mint_identity() -> dict[str, Any]:
    """Every value activation needs, minted at once from a CSPRNG (`req-tap-bake-installation-identity`).

    TAP-IMPLEMENTS: req-tap-bake-installation-identity@45d3dcbecc3a/d6493e142d3a (derivation) — the one place an
        installation's secrets and grid id are minted.
    """
    return {
        "schema": STATE_SCHEMA,
        "status": PENDING,
        "activation_id": str(uuid.uuid7()),
        "grid_id": str(uuid.uuid7()),
        "secret_key": secrets.token_urlsafe(64),
        "owner_password": secrets.token_urlsafe(32),
        "search_password": secrets.token_urlsafe(32),
        "progress": {"activate": "started"},
        "first_login": "pending",
    }


# =============================================================================
# The database: connection, lock and classification
# =============================================================================


@dataclass(frozen=True)
class Target:
    """The installation's database, parsed from the deploy config's bootstrap ``DATABASE_URL``."""

    url: str

    @property
    def parts(self) -> SplitResult:
        return urlsplit(self.url)

    @property
    def dbname(self) -> str:
        return self.parts.path.lstrip("/")

    @property
    def user(self) -> str:
        return unquote(self.parts.username or "")

    @property
    def bootstrap_password(self) -> str:
        return unquote(self.parts.password or "")

    def with_password(self, password: str, dbname: str | None = None) -> str:
        p = self.parts
        host = p.hostname or ""
        netloc = f"{quote(self.user, safe='')}:{quote(password, safe='')}@{host}"
        if p.port:
            netloc += f":{p.port}"
        return urlunsplit((p.scheme, netloc, "/" + (dbname or self.dbname), p.query, p.fragment))


def connect(
    target: Target, passwords: list[str], dbname: str | None = None, *, wait: float = 60.0
) -> psycopg.Connection:
    """Connect with the first password that works, waiting for the server to come up.

    An activated installation's owner password is the stored one; until activation has re-keyed
    the role it is the deploy config's bootstrap password. Trying the stored value first means a
    restart after an interrupted re-key still gets in (`req-tap-bake-activate-5`).
    """
    deadline = time.monotonic() + wait
    last: Exception | None = None
    while True:
        for password in dict.fromkeys(p for p in passwords if p):
            try:
                return psycopg.connect(target.with_password(password, dbname), autocommit=True, connect_timeout=5)
            except psycopg.OperationalError as exc:
                last = exc
                if "password authentication failed" in str(exc):
                    continue
        if time.monotonic() > deadline:
            raise InitializeError(f"cannot connect to the installation's database server: {last}")
        time.sleep(1)


@contextmanager
def installation_lock(conn: psycopg.Connection, dbname: str) -> Iterator[None]:
    """A session advisory lock in the maintenance database, keyed on the installation's database.

    Held on a connection to ``postgres``, not to the installation's own database, so it survives
    that database being dropped and recreated (`req-tap-bake-initializer`).
    """
    key = f"tap-initializer:{dbname}"
    logger.info("[i1a0] initializer: waiting for the installation lock (%s)", key)
    conn.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", [key])
    logger.info("[i1a1] initializer: holding the installation lock")
    try:
        yield
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", [key])


def database_contents(conn: psycopg.Connection) -> tuple[int, bool]:
    """(relations outside the system schemas, whether Django's migration table exists)."""
    row = conn.execute(
        """
        SELECT count(*),
               bool_or(c.relname = 'django_migrations' AND n.nspname = 'public')
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
          AND n.nspname NOT LIKE 'pg_temp_%' AND n.nspname NOT LIKE 'pg_toast_temp_%'
          AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
        """
    ).fetchone()
    if row is None:  # an aggregate always returns a row; this is the type checker's case
        raise InitializeError("the catalogue query returned no row")
    return int(row[0]), bool(row[1])


def classify(identity: dict[str, Any] | None, relations: int, has_tap_schema: bool) -> str:
    """The one road for what the stores hold, or a refusal naming what was found (`-initializer-7`)."""
    if identity is not None and identity["status"] == PENDING:
        return ROAD_RESUME
    if identity is not None and identity["status"] == ACTIVE:
        # Activation creates no tables; migrate does, during Finish. Until Finish has completed once,
        # an empty database is this installation still being built, by a concurrent start or by one
        # that was interrupted, not stores that disagree.
        if relations == 0 and identity["progress"].get("finish") == "done":
            raise InitializeError(
                "the installation's identity is active but its database is empty: the stores disagree. "
                "If the database was deliberately reset, remove the installation volume too and start again"
            )
        return ROAD_FINISH
    if identity is not None:
        raise InitializeError(f"identity status {identity['status']!r} is not one this initializer knows")
    if relations == 0:
        return ROAD_ACTIVATE
    if has_tap_schema:
        return ROAD_LEGACY
    raise InitializeError(
        f"the installation's database holds {relations} relation(s) but no TAP schema and there is no "
        "identity: refusing to initialize over it"
    )


# =============================================================================
# Activation and the hand-off
# =============================================================================


def apply_owner_password(conn: psycopg.Connection, user: str, password: str) -> None:
    """Set the owning role's password to the stored value; setting it again changes nothing."""
    # ALTER ROLE takes no bind parameters, so the statement is composed, not concatenated: psycopg's
    # sql.Identifier quotes the role name and sql.Literal quotes the password, both server-side safe.
    statement = sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(user), sql.Literal(password))
    conn.execute(statement)  # nosemgrep — psycopg.sql composition above, no string concatenation


def handoff_env(target: Target, identity: dict[str, Any]) -> dict[str, str]:
    """What the rest of the start reads: the identity, never a deploy-config default."""
    return {
        "SECRET_KEY": identity["secret_key"],
        "DATABASE_URL": target.with_password(identity["owner_password"]),
        "TAP_SEARCH_READONLY_PASSWORD": identity["search_password"],
        "TAP_GRID_ID": identity["grid_id"],
        "TAP_INSTALLATION_ACTIVATION_ID": identity["activation_id"],
    }


def write_handoff(env: dict[str, str], path: Path) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        for key, value in env.items():
            fh.write(f"{key}={shlex.quote(value)}\n")


def run(
    store: StateStore,
    target: Target,
    *,
    handoff: Path = HANDOFF_PATH,
    minter: Callable[[], dict[str, Any]] = mint_identity,
) -> str:
    """Classify the stores, activate if needed, and write the hand-off; return the road taken.

    TAP-IMPLEMENTS: req-tap-bake-initializer@3137d9b6e56b/7f798e4546ec (derivation) — the one place an installation
        is classified and its road chosen, under the installation lock.
    TAP-IMPLEMENTS: req-tap-bake-activate@757ddecd2b5e/7f798e4546ec (enforcement) — values are stored pending
        before any is applied, applied from the stored values, and never minted twice.
    """
    identity = store.read()
    stored = identity["owner_password"] if identity else ""
    maint = connect(target, [stored, target.bootstrap_password], MAINTENANCE_DB)
    with maint, installation_lock(maint, target.dbname):
        identity = store.read()  # another start may have activated while this one waited
        stored = identity["owner_password"] if identity else ""
        with connect(target, [stored, target.bootstrap_password]) as conn:
            road = classify(identity, *database_contents(conn))
            logger.info("[i1a2] initializer: road %s", road)
            if road == ROAD_LEGACY:
                logger.warning(
                    "[i1a3] initializer: this database was initialized before the initializer existed; "
                    "leaving its identity to the deploy config"
                )
                return road
            if road == ROAD_ACTIVATE:
                identity = minter()
                store.write(identity)  # pending: from here the store is the source of truth
            if identity is None:  # classify returns resume or finish only with an identity present
                raise InitializeError("no identity to apply")
            if road in (ROAD_ACTIVATE, ROAD_RESUME):
                apply_owner_password(conn, target.user, identity["owner_password"])
                identity = {**identity, "status": ACTIVE, "progress": {**identity["progress"], "activate": "done"}}
                store.write(identity)
                logger.info(
                    "[i1a4] initializer: activated installation (grid id %s, activation %s)",
                    identity["grid_id"],
                    identity["activation_id"],
                )
        write_handoff(handoff_env(target, identity), handoff)
    return "activated" if road in (ROAD_ACTIVATE, ROAD_RESUME) else ROAD_FINISH


_STORE_RE = re.compile(r"^/[A-Za-z0-9._/-]+$")


def _store_from_env() -> StateStore:
    root = os.environ.get("TAP_INSTALLATION_DIR", "")
    if not _STORE_RE.match(root) or ".." in root:
        raise InitializeError(f"TAP_INSTALLATION_DIR {root!r} is not an absolute path")
    path = Path(root)
    if not path.is_dir() or not os.access(path, os.W_OK):
        raise InitializeError(f"{path} is not a writable directory: mount the installation volume there")
    return StateStore(path)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="tap.initialize", description="Initialize this installation once.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="classify, activate if needed, write the hand-off env file")
    mark = sub.add_parser("mark", help="record a one-time step as done")
    mark.add_argument("what", choices=["finish", "first-login"])
    status = sub.add_parser("status", help="print whether a one-time step is done")
    status.add_argument("what", choices=["first-login"])
    args = parser.parse_args(argv)
    try:
        store = _store_from_env()
        if args.command == "run":
            print(run(store, Target(os.environ.get("DATABASE_URL", ""))))
            return 0
        identity = store.read()
        if identity is None or identity["status"] != ACTIVE:
            raise InitializeError("the installation is not activated")
        if args.command == "mark" and args.what == "finish":
            store.write({**identity, "progress": {**identity["progress"], "finish": "done"}})
            return 0
        if args.command == "mark":
            store.write({**identity, "first_login": "issued"})
            return 0
        print(identity.get("first_login", "pending"))
        return 0
    except (InitializeError, OSError, ValueError, psycopg.Error) as exc:
        abort(logger, "initialize", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
