"""Detection backstop: a write attempted on the read-only search connection.

The ``search_readonly`` DB alias (``tap/settings.py``) runs with
``default_transaction_read_only=on``, so any write reaching it is rejected by
PostgreSQL — ``psycopg.errors.ReadOnlySqlTransaction``, SQLSTATE ``25006``
(``req-grid-search-readonly.sec``). That rejection *prevents* the write and
preserves grid integrity, but on its own it is **silent**: it surfaces as a
generic query error, indistinguishable from a malformed query, and no alert
fires. A guard that only prevents is half a guard — in production, an actor
probing the traversal engine for a write primitive would trip the read-only lock
and we would never know.

This module makes the block **loud**. It attaches a `connection.execute_wrapper`
to the ``search_readonly`` connection only; when a statement fails with the
read-only rejection, it emits a `security` Flaw (the response-triggering alert)
and then re-raises the original error unchanged — the write stays blocked, and
now it is also detectable anywhere the system runs.

Companion to :mod:`tap_grid.read_guard` (which enforces ``grid.read`` on the same
connection). Scoped to the ``search_readonly`` alias because writes on the
``default`` connection are legitimate and guarded by the service-layer write
pipeline (:mod:`tap_grid.write_guard`); only the read-only search surface should
never see a write. Wired on ``connection_created`` (see ``tap_grid/apps.py``) so
the guard is unforgettable — it rides every read-only connection without a
per-callsite registration step.

The wrapper adds a bare ``try/except`` to the read-only execute path; the happy
path (every search SELECT) pays only that, and the SQLSTATE inspection runs only
when a statement has already failed.
"""

from __future__ import annotations

import logging
from typing import Any

from tap.db_aliases import SEARCH_READONLY

logger = logging.getLogger(__name__)

# SQLSTATE 25006 = read_only_sql_transaction. PostgreSQL raises this for any write
# (INSERT/UPDATE/DELETE/DDL) inside a read-only transaction. Django wraps the
# psycopg error as django.db.InternalError with the psycopg cause carrying the
# code (the Django wrapper's own `.sqlstate` is None), so the chain must be walked.
_READONLY_WRITE_SQLSTATE = "25006"

_READONLY_ALIAS = SEARCH_READONLY


def _is_readonly_write_rejection(exc: BaseException) -> bool:
    """True iff ``exc`` — or any error in its cause/context chain — is a PG 25006.

    Walks ``__cause__``/``__context__`` (cycle-guarded) because Django re-wraps the
    psycopg ``ReadOnlySqlTransaction`` (which carries ``sqlstate``) as an
    ``InternalError`` (which does not).
    """
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if getattr(cur, "sqlstate", None) == _READONLY_WRITE_SQLSTATE:
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def _readonly_write_guard(
    execute: Any,
    sql: str,
    params: Any,
    many: bool,  # noqa: FBT001
    context: Any,
) -> Any:
    """execute_wrapper that raises a security Flaw on a read-only write rejection.

    Runs the statement; if it fails with SQLSTATE 25006, emits the Flaw (the alert)
    and re-raises the original error so the write stays blocked and the caller's
    existing error handling is unchanged.
    """
    try:
        return execute(sql, params, many, context)
    except Exception as exc:
        if _is_readonly_write_rejection(exc):
            # Import here to keep tap_grid import-time free of tap.flaws and to
            # avoid any import cycle; the cost is paid only on the failure path.
            from tap.flaws import report_readonly_write_blocked

            statement_head = sql.strip().split(None, 1)[0].upper() if sql.strip() else "<empty>"
            report_readonly_write_blocked(
                message=(
                    "write attempted on the read-only search connection "
                    f"({_READONLY_ALIAS}) — rejected by PostgreSQL "
                    f"(SQLSTATE {_READONLY_WRITE_SQLSTATE})"
                ),
                logger=logger,
                sqlstate=_READONLY_WRITE_SQLSTATE,
                statement_head=statement_head,
            )
        raise


def install_readonly_write_guard(connection: Any, **_kwargs: Any) -> None:
    """Attach the read-only write-detection wrapper to the search_readonly connection.

    Idempotent, and a no-op for every other alias — only the read-only search
    connection should never carry a write. Wired to ``connection_created`` so every
    search_readonly connection (request, task, command, shell) carries the guard.
    """
    if getattr(connection, "alias", None) != _READONLY_ALIAS:
        return
    if _readonly_write_guard not in connection.execute_wrappers:
        connection.execute_wrappers.append(_readonly_write_guard)
