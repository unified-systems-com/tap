"""Below the gate: who is acting, and the one log record each gateway operation leaves.

`specs/spec-tap-file-store.md`, `req-tap-files-logging` and `req-tap-files-gateway-3`. The record
wraps the capability gate, so a refusal is recorded as surely as a read. It never carries bytes,
and the logical name is left out altogether: it is caller-chosen text, and the identifier already
names the file.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any, TypeVar

from tap_auth.errors import AuthzError
from tap_files.services.contract import FILE_OPERATION_CODE
from tap_files.store.errors import FileIntegrityError, FileStoreError, StoreBusy
from tap_files.store.layout import check_identifier
from tap_files.store.protocol import ObjectStat, OpenedFile, StoredResult

logger = logging.getLogger("tap_files.operations")

F = TypeVar("F", bound=Callable[..., Any])

DONE, REFUSED, FAILED = "done", "refused", "failed"
_LEVELS = {DONE: logging.INFO, REFUSED: logging.WARNING, FAILED: logging.ERROR}


def acting_user(caller_context: Any) -> Any:
    """The actor a gated call runs as: an explicit context's user, else the ambient one.

    The same resolution the capability gate makes (`tap_auth.enforcement`), so the actor recorded
    as a version's writer is the actor that was authorised.
    """
    if caller_context is not None and getattr(caller_context, "user", None) is not None:
        return caller_context.user
    from tap_grid.caller_context import get_caller_context

    ambient = get_caller_context()
    return ambient.user if ambient is not None else None


def actor_key(user: Any) -> str | None:
    """An actor's stable key: its primary key, the identity batches record, never a name or email."""
    return None if user is None else str(user.pk)


def outcome_of(exc: BaseException) -> str:
    """Refused when the request was declined as asked; failed when something went wrong."""
    if isinstance(exc, AuthzError):
        return REFUSED
    if isinstance(exc, FileStoreError) and not isinstance(exc, (FileIntegrityError, StoreBusy)):
        return REFUSED
    return FAILED


def _facts(result: Any) -> dict[str, Any]:
    if isinstance(result, (StoredResult, OpenedFile)):
        return {"version": result.version, "digest": result.digest, "size": result.size}
    if isinstance(result, ObjectStat):
        head = result.version(result.head)
        return {"version": result.head, "digest": head.digest, "size": head.size}
    if isinstance(result, bool):
        return {"exists": result}
    return {}


def _entity_id(identifier: Any) -> str | None:
    try:
        return check_identifier(identifier)
    except FileStoreError:
        return None


def recorded(operation: str) -> Callable[[F], F]:
    """Emit exactly one ``FILE_OPERATION`` record for every call, whatever its outcome.

    TAP-IMPLEMENTS: req-tap-files-logging@904e177b50b7/572e3a096f8a (enforcement) — one record per
        gateway operation, refusals and reads included, and never the content.
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            identifier = args[0] if args else kwargs.get("identifier")
            user = acting_user(kwargs.get("caller_context"))
            data: dict[str, Any] = {
                "operation": operation,
                "identifier": identifier if isinstance(identifier, str) else repr(identifier),
                "actor": actor_key(user),
                "actor_kind": getattr(user, "user_kind", None),
            }
            try:
                result = fn(*args, **kwargs)
            except BaseException as exc:
                outcome = outcome_of(exc)
                version = getattr(exc, "version", None) or getattr(exc, "head", None)
                data.update(outcome=outcome, reason_class=type(exc).__name__, version=version)
                _emit(operation, outcome, data)
                raise
            data.update(outcome=DONE, **_facts(result))
            _emit(operation, DONE, data)
            return result

        return wrapper  # type: ignore[return-value]

    return decorator


def _emit(operation: str, outcome: str, data: dict[str, Any]) -> None:
    logger.log(
        _LEVELS[outcome],
        "[a1a0] files: %s %s %s (actor %s, version %s)",
        operation,
        outcome,
        data["identifier"],
        data["actor"],
        data.get("version"),
        extra={
            "message_code": FILE_OPERATION_CODE,
            "message_data": data,
            "entity_id": _entity_id(data["identifier"]),
        },
    )


__all__ = ["DONE", "FAILED", "REFUSED", "acting_user", "actor_key", "outcome_of", "recorded"]
