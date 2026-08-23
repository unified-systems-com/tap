"""TAP Flaw — the should-never-happen defect signal (spec-tap-flaw-v0.md).

A **Flaw** is a detected violation of an invariant TAP's design guarantees. It is
categorically distinct from an ordinary error (an *expected* failure — bad input,
a denied authorization, an upstream timeout) and orthogonal to severity. A Flaw
says: *something that was supposed to be impossible happened; a human must
investigate and patch.*

Routing rides three orthogonal, machine-readable axes so a router (eventually an
AI on-call) never has to read code to dispatch:

- ``flaw_class`` — who must fix it: ``code`` (TAP core's bug), ``app`` (a
  plugin/app broke a contract), ``instance`` (misconfig / weird instance state).
- ``flaw_tags`` — which specialty it belongs to, from the shared registered
  domain-tag vocabulary (:data:`tap.logging_domain_tags.DOMAIN_TAGS`, one or more
  per Flaw) — the same vocabulary the ``CONCERN`` signal draws from, so a tag
  means one thing across every signal (`req-tap-logging-domain-tags`).
- severity — how urgent (the log level), derived here from the Flaw's handling.

Emission rides TAP's structured logging object as the reserved
``message_code = "FLAW"`` with a ``message_data`` payload
``{flaw_class, flaw_tags, invariant_id, handling}`` (spec-tap-logging.md). The
structured logging object is not built yet, so v0 attaches that payload to the
``LogRecord`` via stdlib ``extra=`` — the data is already structured on the
record for a future JSON handler — and renders a human-readable text line today.
When the structured object lands, this becomes a handler/formatter change, not a
callsite rewrite.

See: spec-tap-flaw-v0.md (req-flaw-concept, req-flaw-classes,
req-flaw-domain-tags, req-flaw-emission, req-flaw-handling).
"""

from __future__ import annotations

import logging
import traceback
from typing import Any, ClassVar

from tap.logging_domain_tags import DOMAIN_TAGS, domain_tag_problems

# The domain-tag vocabulary is shared across every structured signal and now
# lives in `tap.logging_domain_tags` (req-tap-logging-domain-tags), so `FLAW` and
# `CONCERN` cannot drift. `FLAW_TAGS` is retained as the FLAW-facing alias — a
# Flaw's `flaw_tags` must come from this set; an unknown tag is a producer defect
# reported as `flaw_api_misuse` (a `code` Flaw) in `report`.
FLAW_TAGS: dict[str, str] = DOMAIN_TAGS

# ---------------------------------------------------------------------------
# Handling (req-flaw-handling) — impact handling, recorded with the Flaw.
# ---------------------------------------------------------------------------
HANDLING_ABORT_OPERATION = "abort_operation"
HANDLING_REFUSE_BOOT = "refuse_boot"
HANDLING_FAIL_CLOSED_CONTINUE = "fail_closed_continue"
# The pure WARN_ON_ONCE analog: a suspicious invariant violation is *recorded* and
# the operation is allowed to PROCEED unchanged — a detection tripwire, not a block.
# Distinct from fail-closed-continue (which denies the specific operation but keeps
# serving): observe-continue denies nothing. It is the honest handling for a control
# whose false-positive cost is catastrophic (e.g. bricking boot) and whose blocking
# value is marginal — where alerting for incident-response review beats prevention.
# The security instinct is inverted deliberately: we fail *open* here, but loudly.
HANDLING_OBSERVE_CONTINUE = "observe_continue"

_HANDLINGS: frozenset[str] = frozenset(
    {HANDLING_ABORT_OPERATION, HANDLING_REFUSE_BOOT, HANDLING_FAIL_CLOSED_CONTINUE, HANDLING_OBSERVE_CONTINUE}
)

# Severity is orthogonal to flaw_class and derived from impact: refusing to boot is
# CRITICAL; an aborted op or a fail-closed-and-continue is ERROR; an observe-continue
# blocked nothing (WARN_ON_ONCE) so it is WARNING. A Flaw is identified by
# message_code=FLAW + flaw_class + tags, never by level alone — so a security-tagged
# observe-continue still routes to incident response despite the lower level.
_HANDLING_LEVEL: dict[str, int] = {
    HANDLING_REFUSE_BOOT: logging.CRITICAL,
    HANDLING_ABORT_OPERATION: logging.ERROR,
    HANDLING_FAIL_CLOSED_CONTINUE: logging.ERROR,
    HANDLING_OBSERVE_CONTINUE: logging.WARNING,
}

FLAW_MESSAGE_CODE = "FLAW"


class Flaw(Exception):
    """A detected should-never-happen invariant violation.

    `Flaw` is the base; use a concrete subclass (`CodeFlaw`, `AppFlaw`,
    `InstanceFlaw`) whose `flaw_class` names the remediation owner. Construct and
    emit through :meth:`report` — the one blessed path — which validates, emits
    the structured signal, and returns the instance so the caller may ``raise``
    it (fatal handling) or continue (fail-closed handling).
    """

    #: The blame-domain class. Set by each concrete subclass; unset on the base.
    flaw_class: ClassVar[str] = ""

    def __init__(
        self,
        *,
        invariant_id: str,
        tags: list[str],
        handling: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.invariant_id = invariant_id
        self.tags = list(tags)
        self.handling = handling
        self.flaw_message = message
        self.context = dict(context or {})

    def message_data(self) -> dict[str, Any]:
        """Return the ``message_data`` payload for the ``FLAW`` message code."""
        return {
            "flaw_class": self.flaw_class,
            "flaw_tags": list(self.tags),
            "invariant_id": self.invariant_id,
            "handling": self.handling,
            **({"context": self.context} if self.context else {}),
        }

    @classmethod
    def report(
        cls,
        *,
        invariant_id: str,
        tags: list[str],
        handling: str,
        message: str,
        logger: logging.Logger,
        **context: Any,
    ) -> Flaw:
        """Construct, validate, emit, and return a Flaw (the one emission path).

        Args:
            invariant_id: Short stable token naming the violated invariant.
            tags: One or more domain tags from :data:`FLAW_TAGS`.
            handling: One of the ``HANDLING_*`` constants.
            message: Human-readable description (no secrets).
            logger: The calling module's logger, so the record's name is the
                callsite path per the logging convention.
            **context: Extra safe (redactable) structured context.

        Returns:
            The constructed Flaw instance, so the caller may ``raise`` it.
        """
        if cls is Flaw:
            raise TypeError("Report a concrete Flaw subclass (CodeFlaw/AppFlaw/InstanceFlaw), not Flaw itself.")

        problems = domain_tag_problems(tags) + _handling_problems(handling)
        if problems:
            # Misusing the Flaw API (bad tag / handling) is itself a `code` Flaw.
            # Valid tags here, so this reports exactly once with no further recursion.
            CodeFlaw.report(
                invariant_id="flaw_api_misuse",
                tags=["operational"],
                handling=HANDLING_FAIL_CLOSED_CONTINUE,
                message=f"Invalid Flaw report for invariant {invariant_id!r}: {'; '.join(problems)}",
                logger=logger,
                offending_invariant_id=invariant_id,
            )

        flaw = cls(invariant_id=invariant_id, tags=tags, handling=handling, message=message, context=context)
        _emit(flaw, logger)
        return flaw


class CodeFlaw(Flaw):
    """TAP core violated its own invariant — the bug is ours."""

    flaw_class: ClassVar[str] = "code"


class AppFlaw(Flaw):
    """A plugin/app broke a platform contract it was required to honor."""

    flaw_class: ClassVar[str] = "app"


class InstanceFlaw(Flaw):
    """The instance is misconfigured or in an inconsistent runtime state."""

    flaw_class: ClassVar[str] = "instance"


# ---------------------------------------------------------------------------
# Service-layer-bypass helper — the class-aware emitter for the grid guards.
# ---------------------------------------------------------------------------
#
# The read/write ORM backstops (`tap_grid.read_guard` / `tap_grid.write_guard`)
# and the enforcement backstop fire when graph data is read or mutated outside the
# service layer. Blame belongs to *whoever made the offending call*: a bypass from
# a plugin is the plugin author's contract violation (`app`); a bypass from
# first-party code is TAP core's bug (`code`). This helper decides that from the
# offending call's file path and emits the security Flaw accordingly, so a router
# never has to read code to know who fixes it.

# Infra modules that sit between the offending callsite and the Flaw emit — skipped
# when locating who bypassed the service layer.
_BYPASS_INFRA_MARKERS: tuple[str, ...] = (
    "/tap/flaws.py",
    "/tap_grid/read_guard.py",
    "/tap_grid/write_guard.py",
    "/tap_grid/search_readonly_guard.py",
    "/tap_grid/models.py",
    "/tap_auth/enforcement.py",
)


def flaw_class_for_path(path: str | None) -> type[Flaw]:
    """Blame class for a service-layer bypass, by where the offending call lives.

    A path under ``plugins/`` is an :class:`AppFlaw` (a plugin bypassed the service
    layer); anything else (first-party ``tap_*`` code, or an unknown path) is a
    :class:`CodeFlaw`. Pure function so the classification is unit-testable without
    synthesizing a call stack.
    """
    if path and "/plugins/" in path:
        return AppFlaw
    return CodeFlaw


def _offending_callsite() -> tuple[str | None, str]:
    """Best-effort (path, "path:lineno in func") of the code that bypassed the
    service layer — the first stack frame outside the guard/ORM/enforcement
    infrastructure and outside third-party packages."""
    for frame in reversed(traceback.extract_stack()):
        fn = frame.filename
        if any(marker in fn for marker in _BYPASS_INFRA_MARKERS):
            continue
        if "/site-packages/" in fn or "/dist-packages/" in fn:
            continue
        return fn, f"{fn}:{frame.lineno} in {frame.name}"
    return None, "<unknown>"


def report_service_layer_bypass(
    *,
    invariant_id: str,
    message: str,
    logger: logging.Logger,
    **context: Any,
) -> Flaw:
    """Emit a `security` Flaw for a grid read/write that bypassed the service layer.

    The blame class (`code` vs `app`) is decided by where the offending call lives
    (see :func:`flaw_class_for_path`). Always `security`-tagged and
    operation-aborting. The offending callsite is woven into the message and rides
    ``message_data.context.offending_callsite`` for structured routing.

    Args:
        invariant_id: Stable token naming the violated invariant (e.g.
            ``unguarded_operation`` / ``grid_write_service_layer_bypass``).
        message: Human-readable description (no secrets).
        logger: The calling module's logger, so the record name is the callsite.
        **context: Extra safe structured context merged into ``message_data``.

    Returns:
        The emitted Flaw, so the caller may ``raise`` it or continue.
    """
    path, site = _offending_callsite()
    flaw_cls = flaw_class_for_path(path)
    return flaw_cls.report(
        invariant_id=invariant_id,
        tags=["security"],
        handling=HANDLING_ABORT_OPERATION,
        message=f"{message} — offending callsite: {site}",
        logger=logger,
        offending_callsite=site,
        **context,
    )


def report_readonly_write_blocked(
    *,
    message: str,
    logger: logging.Logger,
    **context: Any,
) -> Flaw:
    """Emit a `security` Flaw when a write is attempted on the read-only search connection.

    The `search_readonly` DB alias (tap/settings.py) runs with
    ``default_transaction_read_only=on``, so any write reaching it is rejected by
    PostgreSQL (SQLSTATE 25006, `req-grid-search-readonly.sec`). That rejection
    preserves grid integrity but is otherwise *silent* — it surfaces as a generic
    query error, indistinguishable from a malformed query. This Flaw is the
    response-triggering alert (`req-grid-search-readonly.sec-6`): a write
    attempt on the read-only traversal surface is a should-never-happen event —
    either a core executor defect or an injection that escaped bind-parameter
    safety — and a human (eventually an on-call AI) must investigate.

    Blame class is decided by the offending callsite (core executor → `code`; a
    plugin runner → `app`), matching :func:`report_service_layer_bypass`. Always
    `security`-tagged and operation-aborting. The caller re-raises the original DB
    error after this returns; the write itself stays blocked.

    Args:
        message: Human-readable description (no secrets — never the SQL text).
        logger: The calling module's logger, so the record name is the callsite.
        **context: Extra safe structured context merged into ``message_data``.

    Returns:
        The emitted Flaw.
    """
    path, site = _offending_callsite()
    flaw_cls = flaw_class_for_path(path)
    return flaw_cls.report(
        invariant_id="search_readonly_write_blocked",
        tags=["security"],
        handling=HANDLING_ABORT_OPERATION,
        message=f"{message} — offending callsite: {site}",
        logger=logger,
        offending_callsite=site,
        **context,
    )


def report_db_permission_denied(
    *,
    message: str,
    logger: logging.Logger,
    **context: Any,
) -> Flaw:
    """Emit a `security` Flaw when PostgreSQL denies a statement for insufficient privilege.

    SQLSTATE 42501 (``insufficient_privilege``) is raised whenever a database role is
    denied a `SELECT`/write it is not granted. Unlike the read-only-write block
    (:func:`report_readonly_write_blocked`, scoped to the ``search_readonly`` alias and
    SQLSTATE 25006), this is the **broad** detection chokepoint: it fires for a 42501 on
    *any* connection, alias, or role (``req-grid-db-permission-flaw.sec``). It is wired
    unconditionally at the ORM connection layer so it forward-proofs the least-privilege
    DB roles — the day a Gryphon read reaches a table the search role is not granted, the
    DB denies it (the integrity half) and this Flaw fires (the detection half).

    A 42501 is the highest-value signal in the defense-in-depth set: it means an in-code
    guard (the field-path allowlist / table-scope guard) leaked and the database caught
    what the application did not. Honest scope: this catches only Django-ORM connections;
    a direct psycopg / psql / external-tool path bypasses it (that is pgaudit / DB-log
    territory, a later backstop).

    Blame class is decided by the offending callsite (core executor → `code`; a plugin
    runner → `app`), matching :func:`report_readonly_write_blocked`. Always
    `security`-tagged and operation-aborting; the caller re-raises the original DB error
    after this returns, so the denial stands.

    Args:
        message: Human-readable description (no secrets — never the SQL text).
        logger: The calling module's logger, so the record name is the callsite.
        **context: Extra safe structured context merged into ``message_data``.

    Returns:
        The emitted Flaw.
    """
    path, site = _offending_callsite()
    flaw_cls = flaw_class_for_path(path)
    return flaw_cls.report(
        invariant_id="db_permission_denied",
        tags=["security"],
        handling=HANDLING_ABORT_OPERATION,
        message=f"{message} — offending callsite: {site}",
        logger=logger,
        offending_callsite=site,
        **context,
    )


def _handling_problems(handling: str) -> list[str]:
    """Return human-readable problems with a handling value (empty = fine)."""
    if handling not in _HANDLINGS:
        return [f"unknown handling {handling!r}; valid: {sorted(_HANDLINGS)}"]
    return []


def _emit(flaw: Flaw, logger: logging.Logger) -> None:
    """Emit the Flaw as a structured ``message_code=FLAW`` log record.

    The structured payload rides ``extra=`` so it is already on the record for a
    future JSON handler; the text line is the human rendering for today's
    console handler. ``stacklevel`` points the record at the caller of
    :meth:`Flaw.report`, not at this helper.
    """
    level = _HANDLING_LEVEL.get(flaw.handling, logging.ERROR)
    payload = flaw.message_data()
    logger.log(
        level,
        "[961d] FLAW class=%s invariant=%s tags=%s handling=%s | %s",
        flaw.flaw_class,
        flaw.invariant_id,
        flaw.tags,
        flaw.handling,
        flaw.flaw_message,
        extra={"message_code": FLAW_MESSAGE_CODE, "message_data": payload},
        stacklevel=3,
    )
