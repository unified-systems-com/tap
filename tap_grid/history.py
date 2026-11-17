"""TAP History service — minimal plumbing for the history system.

History is a standalone capability independent of FLIP and perspective.
It records durable change timelines for domain objects.

Architecture notes:
- Every concrete BaseModel subclass gets history tracking via the
  TapHistoricalRecords manager declared on the abstract BaseModel, unless the
  type opts out with ``TRACK_HISTORY = False`` (req-grid-history-optout).
- Actor information is threaded through the history user context here;
  call set_history_user(user) at the start of request handling.
- Composable queries (timeline, between, latest_before, as_of) are
  intentionally deferred to the time-travel implementation pass.

History Scope Configuration:
  Per-model enablement is built (req-grid-history-optout): a type that declares
  ``TRACK_HISTORY = False`` gets no Historical<Type> model, table, manager or
  signal handlers. Retention policy (revision-count and time-based) and any
  per-app or grid-wide setting remain backlogged under req-grid-history-scope.
"""

from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING, Any

from simple_history.models import HistoricalRecords

if TYPE_CHECKING:
    # Generic over AUTH_USER_MODEL — not the concrete tap_auth.User
    # (req-tap-auth-user-model-5).
    from django.contrib.auth.models import AbstractUser


_history_user: contextvars.ContextVar[AbstractUser | None] = contextvars.ContextVar(
    "history_user",
    default=None,
)


def _get_history_user(instance: object = None, **kwargs: object) -> AbstractUser | None:
    """Return the current history user from context.

    Signature matches django-simple-history's get_user callback:
        get_user(instance, **kwargs)

    Args:
        instance: The model instance being saved (passed by DSH).
        **kwargs: Additional kwargs from DSH (ignored).
    """
    return _history_user.get()


def get_history_user() -> AbstractUser | None:
    """Return the current history user from context.

    Public getter for application code (e.g. batch service) that needs the
    current actor without going through the DSH callback signature.
    """
    return _history_user.get()


def set_history_user(user: AbstractUser | None) -> None:
    """Set the current user for history context.

    Call this at the start of authenticated request handling so that
    history entries carry actor identity. Clear (set to None) on teardown.
    """
    _history_user.set(user)


class HistoryNotTracked(LookupError):
    """Raised when history is asked of a type that declares ``TRACK_HISTORY = False``.

    A type without history has no timeline, which is not the same as an empty one: an
    empty result would read as "never changed". Consumers that can answer without
    history check :func:`is_history_enabled` first; consumers that cannot raise this
    (req-grid-history-optout-4).
    """

    def __init__(self, model_class: type) -> None:
        name = getattr(model_class, "ENTITY_TYPE", model_class.__name__)
        super().__init__(
            f"no history for this type: {name} declares TRACK_HISTORY = False (req-grid-history-optout)."
        )
        self.model_class = model_class


class TapHistoricalRecords(HistoricalRecords):
    """``HistoricalRecords`` that honours a per-model ``TRACK_HISTORY`` declaration.

    Declared once on the abstract ``BaseModel`` with ``inherit=True``, simple-history
    builds a ``Historical<Type>`` model for every concrete subclass when that subclass's
    ``class_prepared`` signal fires (``HistoricalRecords.finalize``). simple-history has
    no per-subclass exclusion for an inherited manager, so this skips ``finalize`` for a
    subclass whose ``TRACK_HISTORY`` is false: no history model, no table in the
    migration state, no ``history`` descriptor and no save/delete signal handlers. Every
    other sender goes through the stock ``finalize`` unchanged, so a type that does not
    opt out gets exactly the history model it had before (req-grid-history-optout-2).
    """

    def finalize(self, sender: type, **kwargs: Any) -> None:
        """Build ``sender``'s history model unless it declares ``TRACK_HISTORY = False``.

        TAP-IMPLEMENTS: req-grid-history-optout@da89a0e8b5f5/d68de3c234c5 (derivation) — the one place a type's history model is built or withheld
        """
        if sender is not self.cls and not getattr(sender, "TRACK_HISTORY", True):
            return
        super().finalize(sender, **kwargs)


def is_history_enabled(model_class: type) -> bool:
    """Return True if history tracking is enabled for a model class.

    History is determined by the presence of a django-simple-history
    HistoricalRecords manager (``history`` attribute) on the class. Every
    concrete BaseModel subclass has one unless it declares
    ``TRACK_HISTORY = False`` (req-grid-history-optout), in which case
    TapHistoricalRecords never attaches it.
    """
    return hasattr(model_class, "history")


# ---------------------------------------------------------------------------
# TAP History Service Adapter
# ---------------------------------------------------------------------------


class HistoryService:
    """TAP history service adapter for a model instance.

    Wraps the current history backend (django-simple-history) with a
    stable TAP API so the rest of the codebase never couples directly
    to DSH internals. Backend can be swapped without changing call sites.

    Usage::

        from tap_grid.history import get_history_service
        svc = get_history_service(my_dimension_instance)
        records = svc.raw_records()  # DSH queryset, for low-level use

    Composable query methods (timeline, between, latest_before, as_of)
    are intentionally not implemented here. They belong to the
    time-travel pass and require tombstone semantics and indexing
    decisions that are still in progress. See spec-grid-history.md
    req-grid-history-query and spec-grid-history-timetravel-BACKLOG.md.
    """

    def __init__(self, instance: Any) -> None:
        self._instance = instance

    def is_enabled(self) -> bool:
        """Return True if history is enabled for this instance's model."""
        return is_history_enabled(self._instance.__class__)

    def raw_records(self) -> Any:
        """Return the django-simple-history queryset for this instance.

        Ordered newest-first by history_date (TAP transaction time).

        Raises:
            HistoryNotTracked: the model declares ``TRACK_HISTORY = False``. An
                untracked type has no timeline, and an empty list would read as
                "never changed" (req-grid-history-optout-4).

        Note: Use this only when you need DSH internals directly. Higher-level
        callers should prefer the composable query methods when they are
        implemented (time-travel pass).
        """
        if not self.is_enabled():
            raise HistoryNotTracked(self._instance.__class__)
        return self._instance.history.all()

    def timeline(self) -> Any:
        """Return ordered change history for this instance.

        Raises:
            NotImplementedError: Composable queries are backlogged.
                Implement in the time-travel pass (req-grid-history-query).
        """
        raise NotImplementedError(
            "timeline() is not yet implemented. "
            "Composable history queries are deferred to the time-travel pass. "
            "See spec-grid-history.md req-grid-history-query."
        )

    def between(self, start: Any, end: Any) -> Any:
        """Return history entries within a bounded time window.

        Raises:
            NotImplementedError: Composable queries are backlogged.
        """
        raise NotImplementedError(
            "between() is not yet implemented. "
            "Composable history queries are deferred to the time-travel pass. "
            "See spec-grid-history.md req-grid-history-query."
        )

    def latest_before(self, timestamp: Any) -> Any:
        """Return the latest stored entry prior to a timestamp cutoff.

        Raises:
            NotImplementedError: Composable queries are backlogged.
        """
        raise NotImplementedError(
            "latest_before() is not yet implemented. "
            "Composable history queries are deferred to the time-travel pass. "
            "See spec-grid-history.md req-grid-history-query."
        )

    def as_of(self, timestamp: Any) -> Any:
        """Return the object state at a specific point in time.

        Raises:
            NotImplementedError: Composable queries are backlogged.
        """
        raise NotImplementedError(
            "as_of() is not yet implemented. "
            "Composable history queries are deferred to the time-travel pass. "
            "See spec-grid-history.md req-grid-history-query."
        )


def get_history_service(instance: Any) -> HistoryService:
    """Return the TAP history service for a model instance.

    Args:
        instance: A domain model instance (BaseModel subclass).

    Returns:
        HistoryService bound to the given instance.
    """
    return HistoryService(instance)


def get_historical_records(instance: Any) -> Any:
    """Convenience wrapper — return raw history records for an instance.

    Equivalent to get_history_service(instance).raw_records().
    Use this for tests and one-off inspections; prefer HistoryService for
    application code so call sites can be swapped to the composable query
    methods once the time-travel pass is implemented.
    """
    return get_history_service(instance).raw_records()
