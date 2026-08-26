"""SQL capture seam for the Gryphon executor.

The executor compiles a single Gryphon query into *one or more* Django ORM
QuerySets — a type scan produces one; multi-stage patterns (hub-and-spoke,
edge-type scan, the advanced aggregation path) produce several. There is no
single ``QuerySet.query`` that represents "the query".

This module captures the SQL that actually executes during a Gryphon run by
installing a ``connection.execute_wrapper`` for the duration of a
:func:`capture_sql` block. Every ``SELECT`` (or ``WITH``) statement issued
inside the block is recorded, in execution order, tagged with the executor
stage that produced it.

It backs two consumers:

- The Gridkin runner's expected-SQL snapshot — the explain-snapshot requirement
  of ``spec-gridkin-v0.md`` (gryphon_playground plugin repo).
- The future ``gryphon explain`` developer surface — Gryphon wishlist H3.

The seam is read-only and adds no behavior when no capture is active:
:func:`gryphon_stage` is a cheap context-var set, and the execute-wrapper is
installed only inside :func:`capture_sql`. See ``spec-grid-traversal-execution.md``
(``req-grid-traversal-exec-sql-capture``) for the contract.
"""

from __future__ import annotations

import contextlib
import contextvars
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from django.db import connections

# Statements that begin a read — the only ones a read-only query language can
# emit. Filtering to these drops transaction-management noise (SAVEPOINT,
# RELEASE, ROLLBACK, SET) that pytest-django and the connection layer issue
# around the executor call.
_READ_STATEMENT_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)

# psycopg lazily registers custom types (hstore, citext, ranges) by querying the
# PostgreSQL system catalogs (pg_type, pg_range, ...) exactly once, on a
# connection's *first* use. Those queries are driver connection-setup plumbing,
# not Gryphon reads — the executor only ever reads application (`tap_*`) tables,
# never a `pg_` catalog. Whether they land inside a capture depends purely on
# connection warmth, which makes the capture non-deterministic: a Gryphon read
# runs on the `search_readonly` connection (req-grid-traversal-exec-scope.sec-5),
# which a test can reach cold, capturing the one-time registration on the first
# read but not the second. Excluding catalog reads keeps captures independent of
# connection state, for both consumers (the Gridkin snapshot and `gryphon explain`).
_DRIVER_SETUP_RE = re.compile(r"\bFROM\s+(pg_catalog\.)?pg_\w+", re.IGNORECASE)

# Major SQL keywords the renderer breaks a line before, purely so a long
# compiled statement is readable in a committed snapshot. Comparison is
# whitespace-normalized, so this formatting never affects assertions.
_BREAK_BEFORE: tuple[str, ...] = (
    " FROM ",
    " WHERE ",
    " INNER JOIN ",
    " LEFT OUTER JOIN ",
    " LEFT JOIN ",
    " GROUP BY ",
    " HAVING ",
    " ORDER BY ",
    " LIMIT ",
    " OFFSET ",
)


@dataclass(frozen=True)
class CapturedStatement:
    """One SQL statement recorded during a captured Gryphon run.

    ``sql`` is the parameterized statement (``%s`` placeholders); ``params``
    are the bound values. The two are kept separate rather than inlined — it
    is deterministic, sidesteps value-quoting edge cases, and reads cleanly
    (query shape and literal values shown distinctly).
    """

    stage: str | None
    sql: str
    params: tuple[Any, ...]


@dataclass
class SqlCapture:
    """The ordered SQL statements a single Gryphon run executed."""

    statements: list[CapturedStatement] = field(default_factory=list)

    def render(self) -> str:
        """Render the capture as an eyeballable multi-statement text document.

        One labelled block per statement, in execution order — the on-disk
        shape of a Gridkin ``.sql.txt`` side file.
        """
        if not self.statements:
            return "-- (no SQL captured)\n"
        blocks: list[str] = []
        for index, stmt in enumerate(self.statements, start=1):
            stage = stmt.stage or "(unlabelled)"
            lines = [f"-- statement {index} · stage: {stage}", _format_sql(stmt.sql)]
            if stmt.params:
                lines.append(f"-- params: {list(stmt.params)!r}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks) + "\n"


def _format_sql(sql: str) -> str:
    """Break a one-line compiled statement onto multiple lines for readability."""
    out = sql
    for keyword in _BREAK_BEFORE:
        out = out.replace(keyword, "\n" + keyword.strip() + " ")
    return out


# The executor stage currently in scope. None outside a labelled stage.
_current_stage: contextvars.ContextVar[str | None] = contextvars.ContextVar("gryphon_sql_capture_stage", default=None)

# The active capture, or None. Set only inside a capture_sql() block.
_active_capture: contextvars.ContextVar[SqlCapture | None] = contextvars.ContextVar(
    "gryphon_sql_capture_active", default=None
)


@contextlib.contextmanager
def gryphon_stage(label: str) -> Iterator[None]:
    """Tag SQL captured within this block with an executor-stage label.

    Beyond a context-var set/reset this is a no-op, so the executor pays
    effectively nothing for the labels in normal (uncaptured) execution.
    """
    token = _current_stage.set(label)
    try:
        yield
    finally:
        _current_stage.reset(token)


def _capture_wrapper(execute: Any, sql: str, params: Any, many: bool, context: Any) -> Any:
    """``connection.execute_wrapper`` callback — records reads, then runs them."""
    capture = _active_capture.get()
    if (
        capture is not None
        and not many
        and _READ_STATEMENT_RE.match(sql or "")
        and not _DRIVER_SETUP_RE.search(sql or "")
    ):
        capture.statements.append(
            CapturedStatement(
                stage=_current_stage.get(),
                sql=sql,
                params=tuple(params) if params else (),
            )
        )
    return execute(sql, params, many, context)


@contextlib.contextmanager
def capture_sql(*db_aliases: str) -> Iterator[SqlCapture]:
    """Capture the SQL a Gryphon run executes within the block.

    Installs a ``connection.execute_wrapper`` on each named database alias
    (default: every configured alias, so the capture is complete regardless
    of which alias the executor reads from). Only ``SELECT`` / ``WITH``
    statements are recorded.

    Yields the :class:`SqlCapture`; its ``statements`` are populated as the
    wrapped code runs.
    """
    capture = SqlCapture()
    aliases = db_aliases or tuple(connections)
    token = _active_capture.set(capture)
    try:
        with contextlib.ExitStack() as stack:
            for alias in aliases:
                # Establish the connection BEFORE installing the capture wrapper. A connection
                # first opened *inside* the capture fires ``connection_created`` (which the
                # always-on guards use to (re)install their execute_wrappers), desyncing the
                # capture wrapper mid-run and yielding an incomplete, connection-warmth-dependent
                # capture. A Gryphon read now runs on the ``search_readonly`` connection
                # (req-grid-traversal-exec-scope.sec-5), which a caller can reach cold — so
                # ensure it first, making the capture complete and deterministic regardless of
                # warmth. (It also moves psycopg's one-time type registration out of the block.)
                connections[alias].ensure_connection()
                stack.enter_context(connections[alias].execute_wrapper(_capture_wrapper))
            yield capture
    finally:
        _active_capture.reset(token)
