"""Provisioning for the least-privilege read-only search role (``tap_gryphon_ro``).

TAP-IMPLEMENTS: req-boot-search-role@e7469cffdc86/e8c3499fff8b (derivation) — the
    least-privilege search-role provisioning the boot grid-infra phase calls.

``req-grid-search-readonly-role.sec`` + ``req-boot-search-role``. The ``search_readonly``
connection authenticates as this role so a Gryphon read is constrained at the *database*
level to the grid: ``SELECT`` on exactly the model-layer-derived grid tables plus the
spine, and nothing else. It is the defense-in-depth backstop beneath the in-code field-path
allowlist (``req-grid-traversal-lang-relation-guard.sec``): if an in-code guard ever leaked,
a read reaching a non-grid table (e.g. ``tap_user``) is denied by PostgreSQL with SQLSTATE
42501, which trips the broad permission-denied Flaw (:mod:`tap_grid.db_permission_guard`).

The grant set is **derived from the model layer** (:mod:`tap_grid.grid_tables`, the shared
single source of truth also consumed by the ORM read backstop), not hand-maintained, so it
cannot drift from the models and a newly-added grid table is covered automatically (and a
non-grid table is never granted — the fail-safe direction).

Utility statements (``CREATE ROLE`` / ``ALTER ROLE … SET``) do not accept bind parameters, so
identifiers and literals are validated against strict charsets and safe-quoted rather than
parameterized. The provisioning connection is the table-owning application role (it holds the
grant + CREATEROLE authority); the read-only role never gains privilege-granting authority.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from django.db import IntegrityError, InternalError, ProgrammingError, transaction

logger = logging.getLogger(__name__)


def search_role_name() -> str:
    """The role name to provision — read from settings, never restated here.

    ``settings.SEARCH_READONLY_ROLE`` is authoritative because the
    ``search_readonly`` connection AUTHENTICATES as it; a provisioner that
    hardcoded its own default would create a different role than the one the
    connection uses whenever the operator overrides the env var
    (2026-08 value-level sweep, finding 3).
    """
    from django.conf import settings

    return str(settings.SEARCH_READONLY_ROLE)


# `tap_gryphon_ro` lives in PostgreSQL's CLUSTER-GLOBAL role catalog (pg_authid), shared by every
# database in the server. Concurrent reconcilers of the same role tuple — parallel xdist test
# workers (each on its own test database but ONE shared cluster) or concurrent app-instance boots
# (hot-swap / blue-green against a shared cluster) — collide as "tuple concurrently updated". The
# conflict is benign and self-clearing, so provisioning retries (see req-grid-db-role-concurrency.sec).
_ROLE_PROVISION_MAX_ATTEMPTS = 5
_CONCURRENT_UPDATE_MARKER = "tuple concurrently updated"
# The check-then-CREATE race's two faces (req-grid-db-role-concurrency.sec): both
# provisioners see the cluster-global role absent; the loser's CREATE ROLE fails
# with UniqueViolation on pg_authid (concurrent, uncommitted winner) or
# DuplicateObject "role ... already exists" (committed winner). Either way the
# retry's next pass sees the role and takes the ALTER path.
_DUPLICATE_ROLE_MARKERS = ("pg_authid_rolname_index", "already exists")

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# GUC values are simple tokens (e.g. "30s", "64MB", "1GB", "on"); reject anything else.
_GUC_VALUE_RE = re.compile(r"^[A-Za-z0-9]+$")


def _validate_identifier(name: str) -> str:
    """Return ``name`` if it is a safe SQL identifier, else raise ValueError."""
    if not _IDENT_RE.match(name):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name


def _quote_literal(value: str) -> str:
    """Single-quote a SQL string literal, escaping embedded quotes."""
    return "'" + value.replace("'", "''") + "'"


def _validate_guc_value(value: str) -> str:
    if not _GUC_VALUE_RE.match(value):
        raise ValueError(f"unsafe GUC value: {value!r}")
    return value


def search_role_grant_tables() -> list[str]:
    """Tables the read-only search role may ``SELECT``: every classified grid table.

    Delegates to the shared single source of truth (:mod:`tap_grid.grid_tables`,
    req-grid-table-classification.sec), which derives the set from the ``GRID_TABLE_ROLE``
    classification on the models (names from ``Meta.db_table``). Every returned name is a
    validated identifier (model-derived, but validated defensively because it is interpolated
    into DDL). Provisioning additionally reconciles against tables that actually exist.
    """
    from tap_grid.grid_tables import search_role_grant_tables as _grant_tables

    return sorted(_validate_identifier(t) for t in _grant_tables())


def provision_search_role(
    connection: Any,
    *,
    password: str,
    database: str,
    gucs: dict[str, str],
    tables: list[str] | None = None,
) -> list[str]:
    """Idempotently provision ``tap_gryphon_ro`` using ``connection`` (the owning role).

    Creates/updates the role, resets its table privileges and grants ``SELECT`` on exactly the
    allowlist (the classified grid tables that exist in the database — declared-but-absent
    tables are loudly skipped, req-grid-table-classification.sec-6), grants ``CONNECT``/
    ``USAGE``, and pins the resource-bound GUCs on the role. Re-running reconciles the grants
    to the current classification. Returns the actually-granted table list (for logging / the
    validation loop).

    Args:
        connection: A Django DB connection whose role owns the tables and can CREATE ROLE.
        password: The login password to set on the role.
        database: The database name to grant CONNECT on.
        gucs: ``{guc_name: value}`` to pin via ``ALTER ROLE … SET`` (values are validated).
        tables: Grant-set override (defaults to :func:`search_role_grant_tables`).
    """
    role_name = search_role_name()
    role = _validate_identifier(role_name)
    db = _validate_identifier(database)
    declared_tables = sorted(tables) if tables is not None else sorted(search_role_grant_tables())
    declared_tables = [_validate_identifier(t) for t in declared_tables]
    pw = _quote_literal(password)

    from tap_grid.grid_tables import classified_but_absent

    def _reconcile() -> list[str]:
        # `transaction.atomic` opens a SAVEPOINT when the caller is already in a transaction
        # (e.g. a test), so a retry after a concurrent-update rollback does not poison the
        # caller's surrounding transaction; in autocommit (boot) it is a plain atomic reconcile.
        with transaction.atomic(using=connection.alias), connection.cursor() as cur:
            # 1. Ensure the role exists with LOGIN + password (idempotent).
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role_name])
            if cur.fetchone() is None:
                cur.execute(f'CREATE ROLE "{role}" LOGIN PASSWORD {pw}')
            else:
                cur.execute(f'ALTER ROLE "{role}" LOGIN PASSWORD {pw}')

            # 2. Reconcile the classified set against the tables that actually EXIST
            #    (req-grid-table-classification.sec-6): a classified model whose table was
            #    never migrated (test-fixture model classes; a registered-type-without-a-
            #    table plugin state) must not abort provisioning. Skipping is the fail-safe
            #    direction — not-granted is merely unreadable, never over-exposed — but it
            #    is LOUD, naming every skipped table.
            missing = classified_but_absent(cur, declared=declared_tables)
            granted = [t for t in declared_tables if t not in set(missing)]
            if missing:
                logger.warning(
                    "[f468] search-role grant skipping %d classified-but-absent table(s): %s "
                    "(class exists, table does not — req-grid-table-classification.sec-6)",
                    len(missing),
                    ", ".join(missing),
                )

            # 3. Reset table privileges, then grant SELECT on exactly the allowlist. REVOKE ALL
            #    first so a table dropped from the classification loses access on the next
            #    reconcile.
            cur.execute(f'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "{role}"')
            cur.execute(f'GRANT CONNECT ON DATABASE "{db}" TO "{role}"')
            cur.execute(f'GRANT USAGE ON SCHEMA public TO "{role}"')
            for table in granted:
                cur.execute(f'GRANT SELECT ON "{table}" TO "{role}"')

            # 4. Pin the resource-bound GUCs on the role (req-grid-search-readonly-role.sec-6).
            for guc_name, guc_value in gucs.items():
                gname = _validate_identifier(guc_name)
                gval = _validate_guc_value(str(guc_value))
                cur.execute(f'ALTER ROLE "{role}" SET {gname} = {_quote_literal(gval)}')
        return granted

    # Retry on the benign cluster-global concurrency conflict (req-grid-db-role-concurrency.sec).
    # An advisory lock cannot serialize this: advisory locks are per-DATABASE, but the contended
    # role is cluster-global — so retry is the correct tool.
    granted_tables: list[str] = []
    for attempt in range(1, _ROLE_PROVISION_MAX_ATTEMPTS + 1):
        try:
            granted_tables = _reconcile()
            break
        except InternalError as exc:
            if _CONCURRENT_UPDATE_MARKER not in str(exc) or attempt == _ROLE_PROVISION_MAX_ATTEMPTS:
                raise
            logger.warning(
                "[8db6] search-role provisioning hit a concurrent cluster-global role update "
                "(attempt %d/%d) — retrying (req-grid-db-role-concurrency.sec)",
                attempt,
                _ROLE_PROVISION_MAX_ATTEMPTS,
            )
            time.sleep(0.02 * attempt)
        except (IntegrityError, ProgrammingError) as exc:
            # The CREATE ROLE loser of the check-then-create race (see
            # _DUPLICATE_ROLE_MARKERS). Anything else re-raises untouched.
            if (
                not any(marker in str(exc) for marker in _DUPLICATE_ROLE_MARKERS)
                or attempt == _ROLE_PROVISION_MAX_ATTEMPTS
            ):
                raise
            logger.warning(
                "[95ec] search-role provisioning lost the concurrent CREATE ROLE race "
                "(attempt %d/%d) — retrying via the ALTER path (req-grid-db-role-concurrency.sec)",
                attempt,
                _ROLE_PROVISION_MAX_ATTEMPTS,
            )
            time.sleep(0.02 * attempt)

    logger.info(
        "[5ac3] provisioned search role %s with SELECT on %d tables",
        role_name,
        len(granted_tables),
    )
    return granted_tables
