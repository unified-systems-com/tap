"""Collection time: when a collector gathered an object at the boundary to the grid.

``req-grid-entity-collection-time`` (spec-grid-entity.md). A writer states a window for an object
in its write operation, apart from the object's own fields (``WriteOperation.collected``). The
grid records it on the object's batch event and, for the latest batch to name the object, on the
spine (``Entity.collected_start`` / ``collected_end``). This module holds the two things that
are decided once:

- :func:`settle_window`, which turns what a writer stated into the pair that is stored, or into
  nothing and a warning when it cannot be stored truthfully (rules 3 and 6);
- :func:`order_warnings`, which reports a window that arrives out of order or disagrees with the
  other two kinds of time. The grid reports these and corrects nothing (rules 5 and 7).

Nothing here reads the database or imports a model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

__all__ = [
    "NOT_RECORDED",
    "OLDER_READ",
    "OUT_OF_ORDER",
    "SPINE_COLLECTED_FIELDS",
    "Settled",
    "order_warnings",
    "settle_window",
]

# The two spine columns, in the order the canonical surface carries them.
SPINE_COLLECTED_FIELDS: Final[tuple[str, ...]] = ("collected_start", "collected_end")

# Warning tokens. Each warning starts with one, then names the object where it is known.
NOT_RECORDED: Final[str] = "collection_time_not_recorded"
OLDER_READ: Final[str] = "collection_time_older_read"
OUT_OF_ORDER: Final[str] = "collection_time_out_of_order"


@dataclass(frozen=True)
class Settled:
    """The pair a write records for one object: both set, or both empty. And why, when a stated
    window was left out."""

    start: datetime | None = None
    end: datetime | None = None
    warnings: tuple[str, ...] = ()

    def as_columns(self) -> dict[str, datetime | None]:
        return {"collected_start": self.start, "collected_end": self.end}


_UNSTATED: Final[Settled] = Settled()


def _refused(why: str) -> Settled:
    return Settled(warnings=(f"{NOT_RECORDED}: {why}; no collection time is recorded for this object",))


def _moment(value: Any, which: str) -> datetime | str:
    """One bound as an aware UTC datetime, or the reason it cannot be stored."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return f"the {which} {value!r} is not a date and time"
    if not isinstance(value, datetime):
        return f"the {which} is a {type(value).__name__}, not a date and time"
    if value.tzinfo is None or value.utcoffset() is None:
        return f"the {which} has no time zone"
    return value.astimezone(UTC)


def settle_window(window: Any) -> Settled:
    """The pair to record for what a writer stated (rules 3 and 6).

    Nothing stated gives an empty pair: it is never filled with the write time. A stated window
    is stored timezone-aware and in UTC. One whose bound has no zone or does not read as a time,
    or whose end precedes its start, is not recorded, and the result says why.

    Args:
        window: ``None``, or an object with ``start`` and ``end`` (a ``CollectionWindow``), each
            a datetime or an ISO 8601 text.

    TAP-IMPLEMENTS: req-grid-entity-collection-time@7efec7adb910/bf4ee132f6d1 (derivation) — rules 3 and 6: an unstated
        pair is empty, a stated one is stored in UTC, and one with no zone or an end before its
        start is left out with a warning.
    """
    if window is None:
        return _UNSTATED
    start = _moment(getattr(window, "start", None), "start")
    if isinstance(start, str):
        return _refused(start)
    end = _moment(getattr(window, "end", None), "end")
    if isinstance(end, str):
        return _refused(end)
    if end < start:
        return _refused(f"the end {end.isoformat()} is before the start {start.isoformat()}")
    return Settled(start=start, end=end)


def _span(start: datetime | None, end: datetime | None) -> str:
    return f"{start.isoformat() if start else '?'} to {end.isoformat() if end else '?'}"


def order_warnings(
    settled: Settled,
    *,
    entity_id: Any,
    stored_start: datetime | None,
    stored_end: datetime | None,
    event_start: datetime | None,
    now: datetime,
) -> tuple[str, ...]:
    """What to report about a recorded window. Nothing is corrected and nothing is refused.

    - An older read arriving late (rule 5): the window ends before the one the row carried. The
      pair still moves to it; the warning names the object and both windows.
    - Event time later than collection time, or collection time later than grid time (rule 7):
      a signal about a clock.

    Args:
        settled: The pair this write records.
        entity_id: The object the write names.
        stored_start: The row's ``collected_start`` before this write, None for a create.
        stored_end: The row's ``collected_end`` before this write, None for a create.
        event_start: The object's event time start as this write leaves it.
        now: Grid time for this write.
    """
    if settled.end is None:
        return ()
    found: list[str] = []
    if stored_end is not None and settled.end < stored_end:
        found.append(
            f"{OLDER_READ}: {entity_id}: this batch states the window {_span(settled.start, settled.end)}, "
            f"which ends before the window the row carried, {_span(stored_start, stored_end)}; an older "
            "read arrived late and the row's pair moves to the earlier window"
        )
    if event_start is not None and event_start > settled.end:
        found.append(
            f"{OUT_OF_ORDER}: {entity_id}: the event time {event_start.isoformat()} is later than the "
            f"collection window's end {settled.end.isoformat()}; recorded as stated"
        )
    if settled.end > now:
        found.append(
            f"{OUT_OF_ORDER}: {entity_id}: the collection window's end {settled.end.isoformat()} is later "
            f"than the time of this write {now.isoformat()}; recorded as stated"
        )
    return tuple(found)
