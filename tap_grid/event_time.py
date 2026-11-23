"""Event time on the spine: the declaration, the one reader, and the overlap test.

``req-grid-entity-event-time`` (spec-grid-entity.md). A model says which of its own fields state
when the thing happened or held in the world; the grid copies them into ``Entity.event_start``,
``event_end`` and ``event_precision`` on every save, and stamps what the start means as the row's
``tap.time`` dimension. This module holds:

- the declaration a node model carries beside ``NATURAL_KEY`` (:class:`Moment`, :class:`Interval`,
  :data:`NO_EVENT_TIME`) and the registry of what edge types declare in their definitions;
- :func:`read_value`, the one reader that turns a declared value into a start, an end and a level.
  No plugin writes its own (rule 21);
- the reader function a declaration may name beside a field (rules 23 to 28): a plugin's own
  function from its source's form to a value :func:`read_value` reads, and core's two for epoch
  seconds and milliseconds (:func:`from_epoch_seconds`, :func:`from_epoch_milliseconds`);
- :func:`derive`, which applies a declaration to a row's values;
- :func:`overlapping`, the overlap test the grid publishes (rule 6).

The forms a value may take are those of the FHIR R4 ``dateTime`` type, as published, with nothing
added (rule 10). A reader function does not add a form: what it returns is read by the same one
reader. Nothing here reads the database or imports a model at module scope.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from types import FunctionType
from typing import Any, Final

__all__ = [
    "EVENT_KINDS",
    "EVENT_PRECISIONS",
    "FHIR_DATETIME_PATTERN",
    "NO_EVENT_TIME",
    "SPINE_EVENT_FIELDS",
    "TIME_DIMENSION",
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
    "edge_declaration_problems",
    "derive_for_instance",
    "from_epoch_milliseconds",
    "from_epoch_seconds",
    "get_edge_event_time",
    "kind_problem",
    "overlapping",
    "overlaps",
    "read_value",
    "reader_name",
    "register_edge_event_time",
    "resolve_reader",
]

# What `event_start` means: the values of the `tap.time` dimension core seeds
# (tap_grid/data/dimensions.grift.json). This tuple is the copy a declaration is checked against
# where no grid is loaded (a class body, a static scan); a test holds it equal to the seed's
# `values`, and where the live vocabulary is available the dimension's own list decides.
EVENT_KINDS: Final[tuple[str, ...]] = ("occurred", "created", "first_seen", "published")
# The levels of precision, coarsest first (rule 10). There is no hour or minute level.
EVENT_PRECISIONS: Final[tuple[str, ...]] = ("year", "month", "day", "second")
# The three spine columns, in the order the canonical surface carries them.
SPINE_EVENT_FIELDS: Final[tuple[str, ...]] = ("event_start", "event_end", "event_precision")
# The dimension that carries the kind on the row (rule 3). The name is dimension_map's; it is
# repeated here as a literal so this module still imports nothing from the grid at module scope.
TIME_DIMENSION: Final[str] = "tap.time"

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


# A reader function (rules 23 to 28): given the value a declared field holds, in whatever form the
# source sent it, it returns a value :func:`read_value` reads (a date, a date-time with a zone, or
# FHIR ``dateTime`` text) or None for "no time". A declaration names one as the function itself or
# as its import path, ``package.module:function``; an edge type's definition can only use the path.
Reader = Callable[[Any], Any] | str | None
_READER_PATH: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*")


# A member path (rule 29): the keys that lead from a JSON field's value to the member that holds
# the time. Given as one key or a sequence of keys; kept as a tuple of text keys.
Member = tuple[str, ...] | None


def _member_path(member: Any, label: str) -> Member:
    """A declared member path as a tuple of keys, or None where none is declared.

    Keys are text. A position in a list is not accepted: it is not a name, and the member it
    reaches changes when the source reorders or prepends.
    """
    if member is None:
        return None
    keys = (member,) if isinstance(member, str) else member
    if not isinstance(keys, (list, tuple)) or not keys or not all(isinstance(key, str) and key for key in keys):
        raise EventTimeDeclarationError(
            f"{label} is a key or a sequence of keys, each a non-empty text key of a JSON object; "
            f"got {str(member)[:80]!r}. A position in a list is not a member"
        )
    return tuple(keys)


def member_label(name: str, member: Member) -> str:
    """How a declared value is named in a message: the field, and the member path inside it."""
    return name + "".join(f"[{key[:80]!r}]" for key in member or ())


@dataclass(frozen=True)
class Moment:
    """The thing happened at one time: ``field`` holds it, ``kind`` says what it means.

    ``reader`` names the function that turns the field's stored value into a form the grid reads,
    for a field the source fills in a form of its own (rule 23). ``member`` names the member of a
    JSON field that holds the time (rule 29); a reader is then given that member's value.
    """

    field: str
    kind: str
    reader: Reader = None
    member: Any = None

    def __post_init__(self) -> None:
        _check_kind(self.kind)
        _check_reader(self.reader, "reader")
        object.__setattr__(self, "member", _member_path(self.member, "member"))


@dataclass(frozen=True)
class Interval:
    """The thing began to hold at ``start`` and held until ``end``, when the source states an end.

    ``reader`` reads the start and ``end_reader`` reads the end, each on its own: a source's two
    times do not always share a form, and an end often has an "unset" marker the start has not.
    """

    start: str
    kind: str
    end: str | None = None
    reader: Reader = None
    end_reader: Reader = None
    member: Any = None
    end_member: Any = None

    def __post_init__(self) -> None:
        _check_kind(self.kind)
        _check_reader(self.reader, "reader")
        _check_reader(self.end_reader, "end_reader")
        if self.end_reader is not None and self.end is None:
            raise EventTimeDeclarationError("end_reader reads the end, and this interval names no end")
        # ``member`` is the start's and ``end_member`` the end's, each on its own, as the readers are.
        object.__setattr__(self, "member", _member_path(self.member, "member"))
        object.__setattr__(self, "end_member", _member_path(self.end_member, "end_member"))
        if self.end_member is not None and self.end is None:
            raise EventTimeDeclarationError("end_member is inside the end, and this interval names no end")


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


def _check_reader(reader: Any, label: str) -> None:
    """A reader is a module-level function or the import path of one (rule 26).

    A function given directly must be one its own ``module:name`` reaches again: the version
    record keeps that name, and a process that imports the declaration afresh must find the same
    function under it. So a lambda, a function made inside another, a bound method and a
    ``functools.partial`` are refused here, when the declaration is written. Whether a path
    resolves is checked when it is first needed and by plugin validation.
    """
    if reader is None:
        return
    if isinstance(reader, str):
        if _READER_PATH.fullmatch(reader) is None:
            raise EventTimeDeclarationError(
                f"{label} is a function or its import path, 'package.module:function'; got {reader[:80]!r}"
            )
        return
    qualified = getattr(reader, "__qualname__", "")
    if not isinstance(reader, FunctionType) or not qualified or "<" in qualified or "." in qualified:
        raise EventTimeDeclarationError(
            f"{label} must be a function defined at module level, or its import path "
            f"'package.module:function'; got {_callable_label(reader)}. A lambda, a function made inside "
            "another, a bound method and a functools.partial have no name an import can reach: write a "
            "module-level function that does the same and name that"
        )


def _callable_label(reader: Any) -> str:
    """What an unusable reader is, for a message: its type and whatever name it has."""
    name = getattr(reader, "__qualname__", None) or getattr(reader, "__name__", None)
    return f"a {type(reader).__name__}" + (f" ({str(name)[:80]})" if name else "")


# Import paths already resolved, so a path is imported once per process.
_resolved_readers: dict[str, Callable[[Any], Any]] = {}


def resolve_reader(reader: Reader) -> Callable[[Any], Any] | None:
    """The function a declaration names, or None where it names none.

    A path is ``package.module:function``, a function at module level. It is imported the first
    time it is needed and kept. :class:`EventTimeDeclarationError` where it does not resolve or
    does not name something callable.
    """
    if reader is None:
        return None
    if not isinstance(reader, str):
        return reader
    found = _resolved_readers.get(reader)
    if found is None:
        from django.utils.module_loading import import_string

        try:
            target = import_string(reader.replace(":", "."))
        except Exception as error:  # noqa: BLE001 — whatever the import raised, the path did not resolve
            raise EventTimeDeclarationError(
                f"reader {reader!r} does not resolve to a function ({type(error).__name__})"
            ) from error
        if not callable(target):
            raise EventTimeDeclarationError(f"reader {reader!r} names a {type(target).__name__}, not a function")
        _resolved_readers[reader] = found = target
    return found


def reader_name(reader: Reader) -> str | None:
    """The name a version record keeps for a reader: its import path. Never its code (rule 28)."""
    if reader is None:
        return None
    if isinstance(reader, str):
        return reader
    return f"{getattr(reader, '__module__', '?')}:{getattr(reader, '__qualname__', type(reader).__qualname__)}"


def _readers(declaration: Declaration) -> tuple[tuple[str, Reader], ...]:
    """Each reader a declaration names, with the argument that names it."""
    if isinstance(declaration, Moment):
        return (("reader", declaration.reader),)
    if isinstance(declaration, Interval):
        return (("reader", declaration.reader), ("end_reader", declaration.end_reader))
    return ()


def reader_problems(declaration: Declaration) -> list[str]:
    """What is wrong with the reader functions a declaration names; empty when they are sound.

    A path must resolve to a function. A function given directly is already known to be at module
    level (:func:`_check_reader`); here its own ``module:name`` must reach that same function,
    because the version record keeps the name (rule 28).
    """
    problems: list[str] = []
    for label, reader in _readers(declaration):
        if reader is None:
            continue
        if isinstance(reader, str):
            try:
                resolve_reader(reader)
            except EventTimeDeclarationError as error:
                problems.append(f"{label}: {error}")
            continue
        # Refused at declaration time unless it is a module-level function; what is left to check
        # is that its own name reaches it, which a function rebound or deleted after it was
        # declared would not.
        name = reader_name(reader)
        try:
            reached = resolve_reader(name)
        except EventTimeDeclarationError as error:
            problems.append(f"{label}: {error}")
            continue
        if reached is not reader:
            problems.append(f"{label}: {name} names a different function from the one declared")
    return problems


def kind_problem(kind: str) -> str | None:
    """Why a kind is not a value of the ``tap.time`` dimension, or None.

    Where the grid's vocabulary is loaded and declares ``tap.time``, the dimension's own ``values``
    decide, so a term added to the dimension is accepted without a change here. Where it is not
    (a static scan, a grid whose core vocabulary has not landed), :data:`EVENT_KINDS` decides.
    """
    allowed: tuple[str, ...] | None = EVENT_KINDS
    try:
        from tap_grid.dimension_names import UnknownDimension, declared

        try:
            allowed = declared(TIME_DIMENSION).values
        except UnknownDimension:
            allowed = EVENT_KINDS
    except Exception:  # noqa: BLE001 — no database, apps not loaded: fall back to the static list
        allowed = EVENT_KINDS
    if allowed is not None and kind not in allowed:
        return f"event kind {kind!r} is not a value of the {TIME_DIMENSION!r} dimension ({', '.join(allowed)})"
    return None


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
    # A definition is JSON, so a reader is named by its import path and never given as a function.
    for key in ("reader", "end_reader"):
        if key in definition and not isinstance(definition[key], str):
            raise EventTimeDeclarationError(f"{key} is an import path, 'package.module:function'")
    # A member path has one spelling in a definition, a list of keys, so one path has one record.
    for key in ("member", "end_member"):
        if key in definition and not isinstance(definition[key], list):
            raise EventTimeDeclarationError(f"{key} is a list of keys")
    if shape == "moment":
        unknown = set(definition) - {"shape", "field", "kind", "reader", "member"}
        name = definition.get("field")
        if unknown or not isinstance(name, str) or not name:
            raise EventTimeDeclarationError(
                "a moment names one field, a kind and at most a reader and a member, and nothing else"
            )
        return Moment(field=name, kind=kind, reader=definition.get("reader"), member=definition.get("member"))
    if shape == "interval":
        unknown = set(definition) - {"shape", "start", "end", "kind", "reader", "end_reader", "member", "end_member"}
        start = definition.get("start")
        end = definition.get("end")
        if unknown or not isinstance(start, str) or not start or not (end is None or (isinstance(end, str) and end)):
            raise EventTimeDeclarationError(
                "an interval names a start, an optional end, a kind and at most a reader and a member "
                "for each, and nothing else"
            )
        return Interval(
            start=start,
            end=end,
            kind=kind,
            reader=definition.get("reader"),
            end_reader=definition.get("end_reader"),
            member=definition.get("member"),
            end_member=definition.get("end_member"),
        )
    raise EventTimeDeclarationError(f"event_time shape {shape!r} is not 'moment' or 'interval'")


# What each edge type declares in its definition (rule 20). An edge type that declares nothing
# has no entry and no event time; that is the default and needs no statement.
_edge_event_time: dict[str, Moment | Interval] = {}


def edge_declaration_problems(definition: Any, property_schema: Any) -> list[str]:
    """What is wrong with an edge type's ``event_time`` entry; empty when it is sound.

    The entry must parse, and every property key it names must be one the edge type's own
    ``property_schema`` defines. A key the schema does not define can never hold a value, so the
    declaration would register and every edge of the type would have no event time (rule 20).
    """
    try:
        declaration = declaration_from_definition(definition)
    except EventTimeDeclarationError as error:
        return [str(error)]
    properties = property_schema.get("properties") if isinstance(property_schema, dict) else None
    if not isinstance(properties, dict):
        return ["event_time names edge properties, and the edge type has no property_schema that defines any"]
    wrong_kind = kind_problem(declaration.kind)
    return (
        ([f"event_time: {wrong_kind}"] if wrong_kind else [])
        + [
            f"event_time names {name!r}, which the edge type's property_schema does not define"
            for name in declared_fields(declaration)
            if name not in properties
        ]
        + [
            f"event_time names a member of {name!r}, which the edge type's property_schema does not define "
            "as an object"
            for name, member in _members(declaration)
            if member is not None and name in properties and not _may_be_object(properties[name])
        ]
        + [f"event_time {problem}" for problem in reader_problems(declaration)]
    )


def _members(declaration: Declaration) -> tuple[tuple[str, Member], ...]:
    """Each declared name with the member path inside it, None where the value is the name's own."""
    if isinstance(declaration, Moment):
        return ((declaration.field, declaration.member),)
    if isinstance(declaration, Interval):
        start = ((declaration.start, declaration.member),)
        return start if declaration.end is None else (*start, (declaration.end, declaration.end_member))
    return ()


def _may_be_object(schema: Any) -> bool:
    """Whether a property's JSON Schema lets it hold an object: it says so, or states no type."""
    stated = schema.get("type") if isinstance(schema, dict) else None
    if stated is None:
        return True
    return "object" in (stated if isinstance(stated, list) else [stated])


def register_edge_event_time(edge_type: str, definition: Any) -> None:
    """Record an edge type's ``event_time`` declaration at startup.

    A reader the definition names by path is imported here, once, so a path that does not resolve
    stops the load naming the edge type, and no edge of the type is ever written without it.
    """
    declaration = declaration_from_definition(definition)
    for label, reader in _readers(declaration):
        try:
            resolve_reader(reader)
        except EventTimeDeclarationError as error:
            raise EventTimeDeclarationError(f"edge type {edge_type!r} event_time {label}: {error}") from error
    _edge_event_time[edge_type] = declaration


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


_BEYOND: Final[str] = "its unit ends after the last time the grid can store"


def _start_of_year(year: int) -> datetime:
    if year > 9999:
        raise Unreadable(_BEYOND)
    return datetime(year, 1, 1, tzinfo=UTC)


def _start_of_month(year: int, month: int) -> datetime:
    if year > 9999:
        raise Unreadable(_BEYOND)
    return datetime(year, month, 1, tzinfo=UTC)


def _after(start: datetime, width: timedelta) -> datetime:
    try:
        return start + width
    except OverflowError as error:
        raise Unreadable(_BEYOND) from error


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


def _shown(text: str) -> str:
    """A text value as a message quotes it: whole when short, cut when long."""
    return repr(text) if len(text) <= 80 else f"{text[:77]!r}... ({len(text)} characters)"


def _moment(text: str) -> datetime:
    """A matched full date-time as an aware UTC datetime, its fraction cut to microseconds."""
    head, zone = (text[:-1], "+00:00") if text.endswith("Z") else (text[:-6], text[-6:])
    whole, _, fraction = head.partition(".")
    try:
        parsed = datetime.fromisoformat(f"{whole}.{(fraction + '000000')[:6]}{zone}")
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError) as error:
        raise Unreadable(f"{_shown(text)} is not a time the grid can store") from error


def _why_not(text: str) -> str:
    """Say which rule a text value breaks, for the two cases an author will actually meet."""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}(:\d{2})?", text):
        return f"{text!r} stops at the hour or the minute; a time is given to the second, with a zone"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?", text):
        return f"{_shown(text)} has a time of day and no time zone"
    return f"{_shown(text)} is not a year, a year and month, a date, or a date and time with a zone"


# ---------------------------------------------------------------------------
# Reader functions
# ---------------------------------------------------------------------------

_EPOCH: Final[datetime] = datetime(1970, 1, 1, tzinfo=UTC)
_EPOCH_TEXT: Final[re.Pattern[str]] = re.compile(r"[+-]?[0-9]+(\.[0-9]+)?")


def _from_epoch(value: Any, microseconds_per_unit: int, unit: str) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise TypeError(f"an epoch count is a number or numeric text, not a {type(value).__name__}")
    # Text is digits, with an optional sign and an optional fraction, and nothing else: no
    # exponent, no separators, and no space before or after. Padding is not stripped, because the
    # field holds what the source sent and a padded count is not what this function was told to
    # expect; a plugin whose source pads strips in a reader of its own.
    if isinstance(value, str) and _EPOCH_TEXT.fullmatch(value) is None:
        raise ValueError(f"not a count of {unit}: text must be digits, with an optional sign and fraction")
    try:
        number = Decimal(value) if isinstance(value, (str, Decimal)) else Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError(f"not a count of {unit}") from error
    # A count with more than twenty digits is past year 9999 in either unit; refuse it before
    # turning an exponent like 1e999999 into an integer.
    if not number.is_finite() or number.adjusted() > 20:
        raise ValueError(f"not a count of {unit} the grid can store")
    try:
        return _EPOCH + timedelta(microseconds=int((number * microseconds_per_unit).to_integral_value(ROUND_FLOOR)))
    except OverflowError as error:
        raise ValueError(f"a count of {unit} outside the years 0001 to 9999") from error


def from_epoch_seconds(value: Any) -> datetime:
    """A reader for a field that holds seconds since 1970-01-01T00:00:00Z (rule 27).

    Takes a whole number, a float, or numeric text (``1763805600``, ``"1763805600"``,
    ``"1763805600.25"``) and returns that instant in UTC, to the microsecond. Text is digits with
    an optional sign and fraction; text with a space before or after it, an exponent or a
    separator raises, as anything that is not a number does, so the grid reports the value and
    stores no event time. The result must fall in the years 0001 to 9999; a count outside them
    raises.

    It reads a number as a number and guesses nothing: a negative count is an instant before
    1970, so ``-1`` is ``1969-12-31T23:59:59Z`` and ``0`` is the epoch itself. A source that uses
    such a value to mean "unset" needs a reader of the plugin's own that returns None for it and
    calls this for the rest.
    """
    return _from_epoch(value, 1_000_000, "seconds")


def from_epoch_milliseconds(value: Any) -> datetime:
    """A reader for a field that holds milliseconds since 1970-01-01T00:00:00Z (rule 27).

    As :func:`from_epoch_seconds`, in milliseconds.
    """
    return _from_epoch(value, 1_000, "milliseconds")


def _member_value(value: Any, member: Member) -> Any:
    """The member a path names inside a JSON value, or None where it is not there (rule 30).

    A key that is absent, a value on the way that is not an object, and a member that is null all
    mean the source stated no time: nothing is read and nothing is reported.
    """
    for key in member or ():
        if not isinstance(value, dict):
            return None
        value = value.get(key)
        if value is None:
            return None
    return value


def _through(reader: Reader, value: Any) -> Any:
    """A declared field's stored value as its reader function gives it (rules 23 to 25).

    With no reader the value is returned as it is. An empty value is not passed to the function:
    nothing in, nothing out, and a function need not handle None. The function's failure, or a
    return the grid cannot read as a time, is :class:`Unreadable`, which the derivation turns into
    a warning and an empty event time while the write goes on. Only the exception's class is
    named; its message may quote the value at any length.
    """
    if reader is None or value is None or value == "":
        return value
    try:
        function = resolve_reader(reader)
    except EventTimeDeclarationError as error:
        raise Unreadable(f"its reader function cannot be loaded ({error})") from error
    assert function is not None  # noqa: S101 — narrowed for the type checker; reader is not None here
    try:
        read = function(value)
    except Exception as error:  # noqa: BLE001 — a reader is an author's code, run on a value nothing has checked
        raise Unreadable(f"its reader function failed ({type(error).__name__[:80]})") from error
    if read is None or read == "":
        return None
    if isinstance(read, bool) or not isinstance(read, (date, str)):
        raise Unreadable(
            f"its reader function returned a {type(read).__name__[:80]}, " "not a date, a date-time with a zone or text"
        )
    return read


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Derived:
    """The spine values for one row (three columns and the kind), and what could not be stored and why."""

    event_start: datetime | None = None
    event_end: datetime | None = None
    kind: str | None = None
    event_precision: str | None = None
    warnings: tuple[str, ...] = field(default=(), compare=False)

    def as_columns(self) -> dict[str, Any]:
        """The three event columns of ``Entity``."""
        return {name: getattr(self, name) for name in SPINE_EVENT_FIELDS}

    def as_dimensions(self) -> dict[str, str | None]:
        """The row's ``tap.time`` dimension: the kind where an event time was derived, else removed.

        A row with no event time carries no ``tap.time`` value (rule 9): the kind says what the start
        means, and there is no start.
        """
        return {TIME_DIMENSION: self.kind if self.event_start is not None else None}


_EMPTY: Final[Derived] = Derived()
WARNING_CODE: Final[str] = "event_time_not_stored"


def _empty(name: str, why: str) -> Derived:
    return Derived(warnings=(f"{WARNING_CODE}: {name}: {why}; the spine event time is left empty",))


def _coarser(left: str, right: str) -> str:
    return left if EVENT_PRECISIONS.index(left) <= EVENT_PRECISIONS.index(right) else right


def derive(declaration: Declaration, values: Any) -> Derived:
    """Apply a declaration to a row's values: the event values (three columns and the kind), or all empty with a warning.

    ``values`` is called with a declared name and returns that field's (or property's) value.
    Nothing is defaulted (rule 9): an empty declared value gives no event time. A value that
    cannot be stored truthfully gives none either, and a warning naming the field (rule 12).
    Where the declaration names a reader function, the stored value goes through it first and
    what it returns is read as any declared value is (rules 23 to 25).

    TAP-IMPLEMENTS: req-grid-entity-event-time@57aa1083f3bf/12c3b961652c (derivation) — rules 5 to 10 and 12: one pair,
        widened to the unit a coarse value names, never defaulted, empty with a warning when it
        cannot be stored truthfully.
    """
    if isinstance(declaration, Moment):
        try:
            stored = _member_value(values(declaration.field), declaration.member)
            reading = read_value(_through(declaration.reader, stored))
        except Unreadable as error:
            return _empty(member_label(declaration.field, declaration.member), str(error))
        if reading is None:
            return _EMPTY
        return Derived(reading.start, reading.end_exclusive, declaration.kind, reading.level)
    if isinstance(declaration, Interval):
        try:
            stored = _member_value(values(declaration.start), declaration.member)
            start = read_value(_through(declaration.reader, stored))
        except Unreadable as error:
            return _empty(member_label(declaration.start, declaration.member), str(error))
        if start is None:
            return _EMPTY
        if declaration.end is None:
            return Derived(start.start, None, declaration.kind, start.level)
        try:
            stored = _member_value(values(declaration.end), declaration.end_member)
            end = read_value(_through(declaration.end_reader, stored))
        except Unreadable as error:
            return _empty(member_label(declaration.end, declaration.end_member), str(error))
        if end is None:
            return Derived(start.start, None, declaration.kind, start.level)
        # The end is before the start when its unit is over by the time the start's begins. Equal
        # bounds are a real zero-length span only when both are exact moments; two coarse units
        # that merely touch (a start of 2 November, an end of 1 November) are reversed, and
        # storing them equal would read as a moment.
        both_moments = start.level == "second" and end.level == "second"
        if end.end_exclusive < start.start or (end.end_exclusive == start.start and not both_moments):
            return _empty(
                member_label(declaration.end, declaration.end_member),
                f"the end is before the start in {member_label(declaration.start, declaration.member)}",
            )
        return Derived(start.start, end.end_exclusive, declaration.kind, _coarser(start.level, end.level))
    return _EMPTY


def declaration_for(instance: Any) -> Declaration:
    """The declaration that applies to a row: the edge type's for an edge, else the model class's."""
    if getattr(type(instance), "ENTITY_TYPE", None) == "edge":
        return get_edge_event_time(getattr(instance, "edge_type", ""))
    return getattr(type(instance), "EVENT_TIME", None)


def derive_for_instance(instance: Any) -> Derived:
    """The event values for a typed row, from the fields (or edge properties) it declares."""
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
    (rules 2 and 21). A field read through a reader function may hold anything the source sends,
    a number included, since the function is what turns it into one of those (rule 23).
    """
    from django.core.exceptions import FieldDoesNotExist
    from django.db import models

    declaration = getattr(model_cls, "EVENT_TIME", None)
    if declaration is None or isinstance(declaration, NoEventTime):
        return []
    if not isinstance(declaration, (Moment, Interval)):
        return [f"EVENT_TIME is a {type(declaration).__name__}; it is a Moment, an Interval or NO_EVENT_TIME"]
    problems: list[str] = []
    wrong_kind = kind_problem(declaration.kind)
    if wrong_kind:
        problems.append(f"EVENT_TIME: {wrong_kind}")
    through_reader = {
        name
        for name, reader in (
            ((declaration.field, declaration.reader),)
            if isinstance(declaration, Moment)
            else ((declaration.start, declaration.reader), (declaration.end, declaration.end_reader))
        )
        if name is not None and reader is not None
    }
    problems.extend(f"EVENT_TIME {problem}" for problem in reader_problems(declaration))
    for name, member in _members(declaration):
        try:
            model_field = model_cls._meta.get_field(name)
        except FieldDoesNotExist:
            problems.append(f"EVENT_TIME names {name!r}, which is not a field of {model_cls.__name__}")
            continue
        if member is not None:
            # A member is inside a JSON value, so the field that holds it is a JSON field (rule 29).
            # What the member holds is read as a field's value is, or through the reader named.
            if not isinstance(model_field, models.JSONField):
                problems.append(
                    f"EVENT_TIME names a member of {name!r}, a {type(model_field).__name__}; "
                    "a member is named inside a JSON field"
                )
            continue
        if name in through_reader:
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


def _check_window(window_start: datetime, window_end: datetime) -> None:
    """Refuse a window that is empty or reversed (rule 6): its end must be after its start."""
    if not window_start < window_end:
        raise ValueError(f"a window's end must be after its start; got {window_start!s} to {window_end!s}")


def overlaps(
    event_start: datetime | None, event_end: datetime | None, window_start: datetime, window_end: datetime
) -> bool:
    """Whether one stored pair may fall in the half-open window ``[window_start, window_end)``.

    The start is inclusive and the end exclusive (rule 6). A moment, stored with both equal, is in
    the window when it is at or after the window's start and before its end. An empty end means
    the source states none, so the row is a possible match for every window after its start
    (rule 19). A row with no event time matches nothing. A window whose end is not after its start
    is refused: it is empty or reversed, and an open-ended row would otherwise match it.
    """
    _check_window(window_start, window_end)
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

    _check_window(window_start, window_end)
    start, end = f"{prefix}event_start", f"{prefix}event_end"
    return Q(**{f"{start}__lt": window_end}) & (
        Q(**{f"{end}__isnull": True})
        | Q(**{f"{end}__gt": window_start})
        | (Q(**{end: F(start)}) & Q(**{f"{start}__gte": window_start}))
    )
