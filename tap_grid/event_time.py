"""Event time on the spine: the declaration, the one reader, and the overlap test.

``req-grid-entity-event-time`` (spec-grid-entity.md). A model says which of its own fields state
when the thing happened or held in the world; the grid copies them into ``Entity.event_start``,
``event_end``, ``event_kind`` and ``event_precision`` on every save. This module holds:

- the declaration a node model carries beside ``NATURAL_KEY`` (:class:`Moment`, :class:`Interval`,
  :data:`NO_EVENT_TIME`) and the registry of what edge types declare in their definitions;
- :func:`read_value`, the one reader that turns a declared value into a start, an end and a level.
  No plugin writes its own (rule 21);
- :func:`derive`, which applies a declaration to a row's values;
- :func:`overlapping`, the overlap test the grid publishes (rule 6).

The forms a value may take are those of the FHIR R4 ``dateTime`` type, as published, with nothing
added (rule 10). Nothing here reads the database or imports a model at module scope.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

__all__ = [
    "EVENT_KINDS",
    "EVENT_PRECISIONS",
    "FHIR_DATETIME_PATTERN",
    "NO_EVENT_TIME",
    "SPINE_EVENT_FIELDS",
    "Derived",
    "EventTimeDeclarationError",
    "Interval",
    "Moment",
    "NoEventTime",
    "Reading",
    "Unreadable",
    "declaration_for",
    "declaration_from_definition",
    "declaration_problems",
    "declaration_required",
    "declared_fields",
    "derive",
    "derive_for_instance",
    "get_edge_event_time",
    "overlapping",
    "overlaps",
    "read_value",
    "register_edge_event_time",
]

# What `event_start` means: a closed list core owns (the field table of the requirement).
EVENT_KINDS: Final[tuple[str, ...]] = ("occurred", "created", "first_seen", "published")
# The levels of precision, coarsest first (rule 10). There is no hour or minute level.
EVENT_PRECISIONS: Final[tuple[str, ...]] = ("year", "month", "day", "second")
# The four spine columns, in the order the canonical surface carries them.
SPINE_EVENT_FIELDS: Final[tuple[str, ...]] = ("event_start", "event_end", "event_kind", "event_precision")

# The pattern FHIR R4 publishes for `dateTime` (https://hl7.org/fhir/R4/datatypes.html#dateTime),
# copied from that page on 2026-11-22 and printed in the requirement. Not to be edited by hand.
FHIR_DATETIME_PATTERN: Final[str] = (
    r"([0-9]([0-9]([0-9][1-9]|[1-9]0)|[1-9]00)|[1-9]000)"
    r"(-(0[1-9]|1[0-2])(-(0[1-9]|[1-2][0-9]|3[0-1])"
    r"(T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\.[0-9]+)?"
    r"(Z|(\+|-)((0[0-9]|1[0-3]):[0-5][0-9]|14:00)))?)?)?"
)
_FHIR_DATETIME: Final[re.Pattern[str]] = re.compile(FHIR_DATETIME_PATTERN)

# The one switch that turns an undeclared node model from a listed fact into a validation failure
# (rule 1). Off until every plugin in the fleet has declared; see the requirement's Status Details.
REQUIRE_DECLARATION_ENV: Final[str] = "TAP_REQUIRE_EVENT_TIME_DECLARATION"


def declaration_required() -> bool:
    """Whether plugin validation fails a node model that declares no event time and no absence."""
    return os.environ.get(REQUIRE_DECLARATION_ENV, "") == "1"


class EventTimeDeclarationError(Exception):
    """A declaration that cannot be applied: an unknown shape, kind or field."""


class Unreadable(Exception):
    """A value the grid cannot store truthfully as an event time (rule 12). The message says why."""


@dataclass(frozen=True)
class Moment:
    """The thing happened at one time: ``field`` holds it, ``kind`` says what it means."""

    field: str
    kind: str

    def __post_init__(self) -> None:
        _check_kind(self.kind)


@dataclass(frozen=True)
class Interval:
    """The thing began to hold at ``start`` and held until ``end``, when the source states an end."""

    start: str
    kind: str
    end: str | None = None

    def __post_init__(self) -> None:
        _check_kind(self.kind)


class NoEventTime:
    """A model's explicit statement that it has no event time (rule 1)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "NO_EVENT_TIME"


NO_EVENT_TIME: Final[NoEventTime] = NoEventTime()

Declaration = Moment | Interval | NoEventTime | None


def _check_kind(kind: str) -> None:
    if kind not in EVENT_KINDS:
        raise EventTimeDeclarationError(f"event kind {kind!r} is not one of {', '.join(EVENT_KINDS)}")


def declared_fields(declaration: Declaration) -> tuple[str, ...]:
    """The field names (or, for an edge type, property keys) a declaration reads."""
    if isinstance(declaration, Moment):
        return (declaration.field,)
    if isinstance(declaration, Interval):
        return (declaration.start,) if declaration.end is None else (declaration.start, declaration.end)
    return ()


def declaration_from_definition(definition: Any) -> Moment | Interval:
    """An edge type's ``event_time`` entry (a JSON object) as a declaration (rule 20).

    ``{"shape": "moment", "field": <property key>, "kind": <kind>}`` or
    ``{"shape": "interval", "start": <property key>, "end": <property key, optional>, "kind": <kind>}``.
    """
    if not isinstance(definition, dict):
        raise EventTimeDeclarationError("event_time must be an object")
    shape = definition.get("shape")
    kind = definition.get("kind")
    if not isinstance(kind, str):
        raise EventTimeDeclarationError("event_time needs a kind")
    if shape == "moment":
        unknown = set(definition) - {"shape", "field", "kind"}
        name = definition.get("field")
        if unknown or not isinstance(name, str) or not name:
            raise EventTimeDeclarationError("a moment names one field and a kind, and nothing else")
        return Moment(field=name, kind=kind)
    if shape == "interval":
        unknown = set(definition) - {"shape", "start", "end", "kind"}
        start = definition.get("start")
        end = definition.get("end")
        if unknown or not isinstance(start, str) or not start or not (end is None or (isinstance(end, str) and end)):
            raise EventTimeDeclarationError("an interval names a start, an optional end and a kind, and nothing else")
        return Interval(start=start, end=end, kind=kind)
    raise EventTimeDeclarationError(f"event_time shape {shape!r} is not 'moment' or 'interval'")


# What each edge type declares in its definition (rule 20). An edge type that declares nothing
# has no entry and no event time; that is the default and needs no statement.
_edge_event_time: dict[str, Moment | Interval] = {}


def register_edge_event_time(edge_type: str, definition: Any) -> None:
    """Record an edge type's ``event_time`` declaration at startup."""
    _edge_event_time[edge_type] = declaration_from_definition(definition)


def get_edge_event_time(edge_type: str) -> Moment | Interval | None:
    """The declaration an edge type made, or None when it made none."""
    return _edge_event_time.get(edge_type)


# ---------------------------------------------------------------------------
# The one reader
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Reading:
    """One declared value, read: the unit it names as a half-open interval in UTC, and its level.

    For level ``second`` the value is a moment and ``start`` equals ``end_exclusive``.
    """

    start: datetime
    end_exclusive: datetime
    level: str


def _unit(year: int, month: int | None, day: int | None) -> tuple[datetime, datetime, str]:
    if month is None:
        _real_year(year)
        return datetime(year, 1, 1, tzinfo=UTC), _start_of_year(year + 1), "year"
    if day is None:
        _real_year(year)
        following = (year + 1, 1) if month == 12 else (year, month + 1)
        return datetime(year, month, 1, tzinfo=UTC), _start_of_month(*following), "month"
    try:
        start = datetime(year, month, day, tzinfo=UTC)
    except ValueError as error:
        raise Unreadable(f"{year:04d}-{month:02d}-{day:02d} is not a calendar date") from error
    return start, _after(start, timedelta(days=1)), "day"


def _real_year(year: int) -> None:
    if not 1 <= year <= 9999:
        raise Unreadable(f"year {year} is outside 0001 to 9999")


def _start_of_year(year: int) -> datetime:
    return datetime.max.replace(tzinfo=UTC) if year > 9999 else datetime(year, 1, 1, tzinfo=UTC)


def _start_of_month(year: int, month: int) -> datetime:
    return datetime.max.replace(tzinfo=UTC) if year > 9999 else datetime(year, month, 1, tzinfo=UTC)


def _after(start: datetime, width: timedelta) -> datetime:
    try:
        return start + width
    except OverflowError:
        return datetime.max.replace(tzinfo=UTC)


def read_value(value: Any) -> Reading | None:
    """Read one declared value (rules 10, 11, 21). None for an empty value; :class:`Unreadable` otherwise.

    A date is a full date, level ``day``. A date-time is a moment, level ``second``, and must carry
    a zone. Text is one of the four FHIR ``dateTime`` forms and its level is read from the text.
    A fraction of a second finer than a microsecond is cut short.

    req-grid-entity-event-time rules 10, 11 and 21: the one reader from a declared value to a
    start, an end and a level, for nodes and edges alike.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise Unreadable("a time of day with no time zone")
        moment = value.astimezone(UTC)
        return Reading(moment, moment, "second")
    if isinstance(value, date):
        start, end, level = _unit(value.year, value.month, value.day)
        return Reading(start, end, level)
    if not isinstance(value, str):
        raise Unreadable(f"a {type(value).__name__} is not a date, a date-time or text")
    if _FHIR_DATETIME.fullmatch(value) is None:
        raise Unreadable(_why_not(value))
    date_part, _, time_part = value.partition("T")
    pieces = date_part.split("-")
    year = int(pieces[0])
    month = int(pieces[1]) if len(pieces) > 1 else None
    day = int(pieces[2]) if len(pieces) > 2 else None
    start, end, level = _unit(year, month, day)
    if not time_part:
        return Reading(start, end, level)
    if time_part[6:8] == "60":
        raise Unreadable("a second of 60 (a leap second) cannot be stored in a timestamp")
    moment = _moment(value)
    return Reading(moment, moment, "second")


def _moment(text: str) -> datetime:
    """A matched full date-time as an aware UTC datetime, its fraction cut to microseconds."""
    head, zone = (text[:-1], "+00:00") if text.endswith("Z") else (text[:-6], text[-6:])
    whole, _, fraction = head.partition(".")
    try:
        parsed = datetime.fromisoformat(f"{whole}.{(fraction + '000000')[:6]}{zone}")
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError) as error:
        raise Unreadable(f"{text!r} is not a time the grid can store") from error


def _why_not(text: str) -> str:
    """Say which rule a text value breaks, for the two cases an author will actually meet."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}(:\d{2})?", text):
        return f"{text!r} stops at the hour or the minute; a time is given to the second, with a zone"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?", text):
        return f"{text!r} has a time of day and no time zone"
    return f"{text!r} is not a year, a year and month, a date, or a date and time with a zone"


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Derived:
    """The four spine values for one row, and what could not be stored and why."""

    event_start: datetime | None = None
    event_end: datetime | None = None
    event_kind: str | None = None
    event_precision: str | None = None
    warnings: tuple[str, ...] = field(default=(), compare=False)

    def as_columns(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in SPINE_EVENT_FIELDS}


_EMPTY: Final[Derived] = Derived()
WARNING_CODE: Final[str] = "event_time_not_stored"


def _empty(name: str, why: str) -> Derived:
    return Derived(warnings=(f"{WARNING_CODE}: {name}: {why}; the spine event time is left empty",))


def _coarser(left: str, right: str) -> str:
    return left if EVENT_PRECISIONS.index(left) <= EVENT_PRECISIONS.index(right) else right


def derive(declaration: Declaration, values: Any) -> Derived:
    """Apply a declaration to a row's values: the four spine values, or all empty with a warning.

    ``values`` is called with a declared name and returns that field's (or property's) value.
    Nothing is defaulted (rule 9): an empty declared value gives four empty fields. A value that
    cannot be stored truthfully gives four empty fields and a warning naming the field (rule 12).

    TAP-IMPLEMENTS: req-grid-entity-event-time@ea9b0b4fc048/164aad0509ac (derivation) — rules 5 to 10 and 12: one pair,
        widened to the unit a coarse value names, never defaulted, empty with a warning when it
        cannot be stored truthfully.
    """
    if isinstance(declaration, Moment):
        try:
            reading = read_value(values(declaration.field))
        except Unreadable as error:
            return _empty(declaration.field, str(error))
        if reading is None:
            return _EMPTY
        return Derived(reading.start, reading.end_exclusive, declaration.kind, reading.level)
    if isinstance(declaration, Interval):
        try:
            start = read_value(values(declaration.start))
        except Unreadable as error:
            return _empty(declaration.start, str(error))
        if start is None:
            return _EMPTY
        if declaration.end is None:
            return Derived(start.start, None, declaration.kind, start.level)
        try:
            end = read_value(values(declaration.end))
        except Unreadable as error:
            return _empty(declaration.end, str(error))
        if end is None:
            return Derived(start.start, None, declaration.kind, start.level)
        if end.end_exclusive < start.start:
            return _empty(declaration.end, f"the end is before the start in {declaration.start}")
        return Derived(start.start, end.end_exclusive, declaration.kind, _coarser(start.level, end.level))
    return _EMPTY


def declaration_for(instance: Any) -> Declaration:
    """The declaration that applies to a row: the edge type's for an edge, else the model class's."""
    if getattr(type(instance), "ENTITY_TYPE", None) == "edge":
        return get_edge_event_time(getattr(instance, "edge_type", ""))
    return getattr(type(instance), "EVENT_TIME", None)


def derive_for_instance(instance: Any) -> Derived:
    """The four spine values for a typed row, from the fields (or edge properties) it declares."""
    declaration = declaration_for(instance)
    if not isinstance(declaration, (Moment, Interval)):
        return _EMPTY
    if getattr(type(instance), "ENTITY_TYPE", None) == "edge":
        properties = instance.properties if isinstance(instance.properties, dict) else {}
        return derive(declaration, properties.get)
    return derive(declaration, lambda name: getattr(instance, name, None))


def declaration_problems(model_cls: Any) -> list[str]:
    """What is wrong with a node model's ``EVENT_TIME``; empty when it is sound or absent.

    A declared name must be a concrete field of the model that holds a date, a date-time or text
    (rules 2 and 21).
    """
    from django.core.exceptions import FieldDoesNotExist
    from django.db import models

    declaration = getattr(model_cls, "EVENT_TIME", None)
    if declaration is None or isinstance(declaration, NoEventTime):
        return []
    if not isinstance(declaration, (Moment, Interval)):
        return [f"EVENT_TIME is a {type(declaration).__name__}; it is a Moment, an Interval or NO_EVENT_TIME"]
    problems: list[str] = []
    for name in declared_fields(declaration):
        try:
            model_field = model_cls._meta.get_field(name)
        except FieldDoesNotExist:
            problems.append(f"EVENT_TIME names {name!r}, which is not a field of {model_cls.__name__}")
            continue
        if not isinstance(model_field, (models.DateField, models.CharField, models.TextField)):
            problems.append(
                f"EVENT_TIME names {name!r}, a {type(model_field).__name__}; "
                "an event time is read from a date, a date-time or a text field"
            )
    return problems


# ---------------------------------------------------------------------------
# The overlap test
# ---------------------------------------------------------------------------


def overlaps(
    event_start: datetime | None, event_end: datetime | None, window_start: datetime, window_end: datetime
) -> bool:
    """Whether one stored pair may fall in the half-open window ``[window_start, window_end)``.

    The start is inclusive and the end exclusive (rule 6). A moment, stored with both equal, is in
    the window when it is at or after the window's start and before its end. An empty end means
    the source states none, so the row is a possible match for every window after its start
    (rule 19). A row with no event time matches nothing.
    """
    if event_start is None or event_start >= window_end:
        return False
    if event_end is None:
        return True
    if event_end == event_start:
        return event_start >= window_start
    return event_end > window_start


def overlapping(window_start: datetime, window_end: datetime, *, prefix: str = "") -> Any:
    """The published overlap test as a filter: rows whose event time may fall in the window.

    The same rule as :func:`overlaps`. ``prefix`` reaches the spine from another model
    (``"entity__"`` from a typed row). A default range of zero width is empty in PostgreSQL and
    matches nothing, which is why a moment is compared and not turned into a range.

    req-grid-entity-event-time rules 6 and 19: the published overlap test, in which a moment
    inside the window matches and possible matches are kept.
    """
    from django.db.models import F, Q

    start, end = f"{prefix}event_start", f"{prefix}event_end"
    return Q(**{f"{start}__lt": window_end}) & (
        Q(**{f"{end}__isnull": True})
        | Q(**{f"{end}__gt": window_start})
        | (Q(**{end: F(start)}) & Q(**{f"{start}__gte": window_start}))
    )
