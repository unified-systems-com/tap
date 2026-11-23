"""A plugin's own event-time reader, and core's two for epoch counts.

Covers ``req-grid-entity-event-time`` rules 23 to 30 (spec-grid-entity.md); Issue# 1284 - tap. A
declaration may name a function beside its field; the grid calls it with the stored value each
time it derives the spine, and reads what it returns with the one reader. Rows use the neutral
grid_fixtures ``PgNode``: ``description`` is text, ``severity_score`` a whole number and ``tags``
a JSON field. The reader functions are at module level here because a declaration refuses any
other kind.
"""

from __future__ import annotations

import functools
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tap_plugin.grid_fixtures.models.pg_node import PgNode

from tap_grid import event_time, model_definition
from tap_grid.caller_context import CallerContext
from tap_grid.dimension_names import view
from tap_grid.event_time import (
    EventTimeDeclarationError,
    Interval,
    Moment,
    declaration_from_definition,
    declaration_problems,
    edge_declaration_problems,
    from_epoch_milliseconds,
    from_epoch_seconds,
    reader_name,
)
from tap_grid.grift import grift_import
from tap_grid.models import Edge, Entity
from tap_grid.services import create_edge, create_node, patch_node
from tap_grid.tests.test_grift import _batch_container, _batch_entity_id, _minimal_doc

AC = {n: pytest.mark.spec(f"req-grid-entity-event-time-{n}") for n in range(25, 39)}

_TYPE = "grid_fixtures__node"
LINK = "PG_LINKS__grid_fixtures"
HERE = "tap_grid.tests.test_event_time_reader"
SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
# 2026-12-01T18:30:00Z as a count of seconds.
EPOCH = 1796149800
WHEN = datetime(2026, 12, 1, 18, 30, tzinfo=UTC)


# -- reader functions a plugin might write ------------------------------------------------------


def year_only(value: Any) -> Any:
    """A source that knows only the year: the house form is ``Y2026``."""
    return str(value).removeprefix("Y")


def unset_marker(value: Any) -> Any:
    """Epoch seconds, where the source writes ``-1`` for "no time"."""
    return None if str(value) == "-1" else from_epoch_seconds(value)


def always_raises(value: Any) -> Any:
    raise KeyError(f"a secret the message must not carry: {value}")


def returns_a_number(value: Any) -> Any:
    return 42


def returns_spine_values(value: Any) -> Any:
    return (WHEN, WHEN, "second")


def created_member(value: Any) -> Any:
    """Pick one member out of a JSON field: zoned text as it is, a number as epoch seconds."""
    member = value.get("created") if isinstance(value, dict) else None
    if member is None:
        return None
    return from_epoch_seconds(member) if isinstance(member, (int, float)) else member


def states_a_zone(value: Any) -> Any:
    """A source documented to write UTC with no zone: the plugin states the zone, and owns that."""
    return f"{value}Z"


not_a_function = 7


class _Holder:
    def method(self, value: Any) -> Any:
        return value


def _ctx() -> CallerContext:
    return CallerContext(batch_id=str(uuid.uuid7()))


def _create(payload: dict[str, Any]) -> Any:
    result = create_node(_TYPE, payload, caller_context=_ctx())
    assert result.success, result.errors
    return result


def _four(entity_id: Any) -> tuple[Any, ...]:
    row = Entity.objects.get(pk=entity_id)
    return (row.event_start, row.event_end, view(row.dimensions).get("tap.time"), row.event_precision)


def _declare(monkeypatch: pytest.MonkeyPatch, declaration: Any) -> None:
    monkeypatch.setattr(PgNode, "EVENT_TIME", declaration, raising=False)


# ---------------------------------------------------------------------------
# Core's two readers
# ---------------------------------------------------------------------------


class TestCoresEpochReaders:
    @AC[33]
    @pytest.mark.parametrize("value", [EPOCH, float(EPOCH), str(EPOCH), f"+{EPOCH}", f"{EPOCH}.0"])
    def test_seconds_as_a_number_or_as_digits(self, value: Any) -> None:
        assert from_epoch_seconds(value) == WHEN
        assert from_epoch_seconds(value).utcoffset() is not None

    @AC[33]
    @pytest.mark.parametrize("value", [EPOCH * 1000, str(EPOCH * 1000), f"{EPOCH * 1000}.0"])
    def test_milliseconds_as_a_number_or_as_digits(self, value: Any) -> None:
        assert from_epoch_milliseconds(value) == WHEN

    @AC[33]
    def test_a_fraction_is_kept_to_the_microsecond(self) -> None:
        assert from_epoch_seconds(f"{EPOCH}.25") == WHEN.replace(microsecond=250000)
        assert from_epoch_milliseconds(EPOCH * 1000 + 123) == WHEN.replace(microsecond=123000)
        assert from_epoch_seconds(f"{EPOCH}.0000009") == WHEN  # finer than a microsecond is cut short

    @AC[33]
    @pytest.mark.parametrize(
        "value",
        [f" {EPOCH}", f"{EPOCH} ", f"{EPOCH}\n", "", " ", "1e9", "1,796,149,800", "0x10", "soon", "2026-12-01", "NaN"],
    )
    def test_text_that_is_not_plain_digits_is_refused_and_padding_is_not_stripped(self, value: str) -> None:
        with pytest.raises(ValueError, match="count of seconds"):
            from_epoch_seconds(value)

    @AC[33]
    @pytest.mark.parametrize("value", [None, True, False, b"1796149800", [EPOCH], {"s": EPOCH}])
    def test_a_value_that_is_not_a_number_or_text_is_refused(self, value: Any) -> None:
        with pytest.raises(TypeError):
            from_epoch_seconds(value)

    @AC[33]
    def test_no_marker_is_guessed(self) -> None:
        """-1 and 0 are instants; a source that means "unset" by them needs a reader of its own."""
        assert from_epoch_seconds(-1) == datetime(1969, 12, 31, 23, 59, 59, tzinfo=UTC)
        assert from_epoch_seconds("0") == datetime(1970, 1, 1, tzinfo=UTC)
        assert unset_marker("-1") is None

    @AC[33]
    @pytest.mark.parametrize("value", [10**12, -(10**12), "9" * 30, float("inf"), float("nan"), 1e300])
    def test_a_count_outside_the_years_the_grid_stores_is_refused(self, value: Any) -> None:
        with pytest.raises(ValueError):
            from_epoch_seconds(value)

    @AC[33]
    def test_the_range_is_the_years_0001_to_9999(self) -> None:
        assert from_epoch_seconds(-62135596800) == datetime(1, 1, 1, tzinfo=UTC)
        assert from_epoch_seconds(253402300799).year == 9999
        for beyond in (-62135596801, 253402300800):
            with pytest.raises(ValueError):
                from_epoch_seconds(beyond)


# ---------------------------------------------------------------------------
# What a declaration accepts
# ---------------------------------------------------------------------------


class TestTheDeclaration:
    @AC[30]
    def test_a_function_or_its_path_is_accepted(self) -> None:
        assert Moment("a", "occurred", reader=from_epoch_seconds).reader is from_epoch_seconds
        assert Moment("a", "occurred", reader=f"{HERE}:year_only").reader == f"{HERE}:year_only"
        both = Interval("a", "created", end="b", reader=from_epoch_seconds, end_reader=unset_marker)
        assert (both.reader, both.end_reader) == (from_epoch_seconds, unset_marker)
        assert Moment("a", "occurred") == Moment("a", "occurred", reader=None)

    @AC[30]
    @pytest.mark.parametrize(
        "unusable",
        [
            lambda value: value,
            functools.partial(from_epoch_seconds),
            _Holder().method,
            _Holder.method,
            int,
            not_a_function,
        ],
    )
    def test_only_a_module_level_function_can_be_given_directly(self, unusable: Any) -> None:
        with pytest.raises(EventTimeDeclarationError, match="module level"):
            Moment("a", "occurred", reader=unusable)
        with pytest.raises(EventTimeDeclarationError, match="module level"):
            Interval("a", "created", end="b", end_reader=unusable)

    @AC[30]
    def test_a_function_made_inside_another_is_refused(self) -> None:
        def nested(value: Any) -> Any:
            return value

        with pytest.raises(EventTimeDeclarationError, match="module-level function"):
            Moment("a", "occurred", reader=nested)

    @AC[30]
    @pytest.mark.parametrize("path", ["", "no_colon", "pkg.mod:", ":fn", "pkg.mod:Class.method", "pkg mod:fn", "a:b:c"])
    def test_a_path_has_one_form(self, path: str) -> None:
        with pytest.raises(EventTimeDeclarationError, match="package.module:function"):
            Moment("a", "occurred", reader=path)

    @AC[30]
    def test_an_end_reader_needs_an_end(self) -> None:
        with pytest.raises(EventTimeDeclarationError, match="names no end"):
            Interval("a", "created", end_reader=from_epoch_seconds)

    @AC[30]
    def test_a_path_that_does_not_resolve_is_a_problem_plugin_validation_reports(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from tap_plugins.validate.service import _check_event_time_declarations

        def check() -> Any:
            manifest = SimpleNamespace(
                models=[SimpleNamespace(slug=_TYPE, class_path=f"{PgNode.__module__}.{PgNode.__name__}")]
            )
            result: Any = SimpleNamespace(checks=[])
            _check_event_time_declarations(manifest, result)
            return result.checks[-1]

        _declare(monkeypatch, Moment("description", "occurred", reader=f"{HERE}:no_such_function"))
        assert any("does not resolve" in problem for problem in declaration_problems(PgNode))
        missing = check()
        assert missing.status == "fail" and "no_such_function" in str(missing.messages)

        _declare(monkeypatch, Moment("description", "occurred", reader=f"{HERE}:not_a_function"))
        assert any("not a function" in problem for problem in declaration_problems(PgNode))

        _declare(monkeypatch, Moment("description", "occurred", reader=f"{HERE}:year_only"))
        assert declaration_problems(PgNode) == []
        assert check().status == "pass"

    @AC[30]
    def test_a_function_its_own_name_no_longer_reaches_is_a_problem(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys

        _declare(monkeypatch, Moment("description", "occurred", reader=year_only))
        assert declaration_problems(PgNode) == []
        monkeypatch.setattr(sys.modules[__name__], "year_only", unset_marker)
        monkeypatch.setattr(event_time, "_resolved_readers", {})  # a path is imported once per process
        assert any("different function" in problem for problem in declaration_problems(PgNode))

    @AC[34]
    def test_a_field_read_through_a_reader_may_be_of_any_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("severity_score", "tags", "is_open"):
            _declare(monkeypatch, Moment(name, "occurred"))
            assert any("date, a date-time or a text field" in problem for problem in declaration_problems(PgNode))
            _declare(monkeypatch, Moment(name, "occurred", reader=created_member))
            assert declaration_problems(PgNode) == []
        # Each end on its own: a reader on the start does not excuse the end's field type.
        _declare(monkeypatch, Interval("tags", "created", end="severity_score", reader=created_member))
        assert len(declaration_problems(PgNode)) == 1
        _declare(
            monkeypatch,
            Interval("tags", "created", end="severity_score", reader=created_member, end_reader=from_epoch_seconds),
        )
        assert declaration_problems(PgNode) == []
        # A name that is not a field is still a problem, reader or not.
        _declare(monkeypatch, Moment("nope", "occurred", reader=from_epoch_seconds))
        assert any("not a field" in problem for problem in declaration_problems(PgNode))


# ---------------------------------------------------------------------------
# Derivation through a reader
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDerivation:
    @AC[25]
    def test_an_epoch_string_is_read_through_cores_function_and_stays_as_it_was_sent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _declare(monkeypatch, Moment("description", "first_seen", reader=from_epoch_seconds))
        created = _create({"name": "epoch", "description": str(EPOCH)})
        assert _four(created.entity_id) == (WHEN, WHEN, "first_seen", "second")
        assert created.warnings == []
        # The field holds what the source sent, byte for byte (rule 22).
        assert PgNode.objects.get(entity_id=created.entity_id).description == str(EPOCH)

    @AC[25]
    def test_a_whole_number_field_is_read_through_a_reader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _declare(monkeypatch, Moment("severity_score", "occurred", reader=from_epoch_seconds))
        created = _create({"name": "number", "severity_score": EPOCH})
        assert _four(created.entity_id) == (WHEN, WHEN, "occurred", "second")
        assert PgNode.objects.get(entity_id=created.entity_id).severity_score == EPOCH

    @AC[26]
    def test_a_reader_that_returns_a_year_keeps_year_precision(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _declare(monkeypatch, Moment("description", "published", reader=year_only))
        created = _create({"name": "year", "description": "Y2026"})
        assert _four(created.entity_id) == (
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2027, 1, 1, tzinfo=UTC),
            "published",
            "year",
        )
        assert PgNode.objects.get(entity_id=created.entity_id).description == "Y2026"

    @AC[27]
    def test_a_reader_that_returns_nothing_derives_nothing_and_warns_of_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _declare(monkeypatch, Moment("description", "occurred", reader=unset_marker))
        created = _create({"name": "unset", "description": "-1"})
        assert _four(created.entity_id) == (None, None, None, None)
        assert created.warnings == []
        assert PgNode.objects.get(entity_id=created.entity_id).description == "-1"

    @AC[27]
    def test_an_empty_field_is_not_passed_to_the_reader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _declare(monkeypatch, Moment("description", "occurred", reader=always_raises))
        created = _create({"name": "empty", "description": ""})
        assert _four(created.entity_id) == (None, None, None, None)
        assert created.warnings == []

    @AC[28]
    @pytest.mark.parametrize(
        ("reader", "said"),
        [
            (always_raises, "its reader function failed (KeyError)"),
            (returns_a_number, "its reader function returned a int"),
            (returns_spine_values, "its reader function returned a tuple"),
            (f"{HERE}:no_such_function", "its reader function cannot be loaded"),
        ],
    )
    def test_a_reader_that_fails_or_returns_something_else_does_not_fail_the_write(
        self, monkeypatch: pytest.MonkeyPatch, reader: Any, said: str
    ) -> None:
        _declare(monkeypatch, Moment("description", "occurred", reader=reader))
        created = _create({"name": "bad-reader", "description": "the-value-as-sent"})
        assert created.success
        assert _four(created.entity_id) == (None, None, None, None)
        assert len(created.warnings) == 1
        warning = created.warnings[0]
        assert warning.startswith("event_time_not_stored: description: ") and said in warning
        # The exception's class is named and its message, which quotes the value, is not.
        assert "a secret the message must not carry" not in warning and "the-value-as-sent" not in warning
        assert PgNode.objects.get(entity_id=created.entity_id).description == "the-value-as-sent"

    @AC[28]
    def test_what_a_reader_returns_is_read_by_the_one_reader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A reader cannot put a form on the spine that core does not read: rules 10 to 12 still apply."""
        _declare(monkeypatch, Moment("description", "occurred", reader=year_only))
        created = _create({"name": "zoneless", "description": "Y2026-12-01T18:30:00"})
        assert _four(created.entity_id) == (None, None, None, None)
        assert "no time zone" in created.warnings[0]

    @AC[28]
    def test_a_long_value_is_not_quoted_at_length(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _declare(monkeypatch, Moment("description", "occurred", reader=year_only))
        created = _create({"name": "long", "description": "Y" + "x" * 5000})
        assert len(created.warnings[0]) < 400 and "5000 characters" in created.warnings[0]

    @AC[28]
    def test_a_plugins_reader_may_state_a_zone_the_source_leaves_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _declare(monkeypatch, Moment("description", "occurred", reader=states_a_zone))
        created = _create({"name": "stated", "description": "2026-12-01T18:30:00"})
        assert _four(created.entity_id) == (WHEN, WHEN, "occurred", "second")
        assert PgNode.objects.get(entity_id=created.entity_id).description == "2026-12-01T18:30:00"

    @AC[25]
    def test_each_end_of_an_interval_has_its_own_reader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _declare(
            monkeypatch,
            Interval(
                "severity_score", "created", end="description", reader=from_epoch_seconds, end_reader=unset_marker
            ),
        )
        open_ended = _create({"name": "no-expiry", "severity_score": EPOCH, "description": "-1"})
        assert _four(open_ended.entity_id) == (WHEN, None, "created", "second")
        assert open_ended.warnings == []
        closed = _create({"name": "expires", "severity_score": EPOCH, "description": str(EPOCH + 60)})
        assert _four(closed.entity_id) == (WHEN, WHEN.replace(minute=31), "created", "second")
        # With no end reader the end is read as it is stored, whatever the start's reader is.
        _declare(monkeypatch, Interval("severity_score", "created", end="description", reader=from_epoch_seconds))
        plain = _create({"name": "plain-end", "severity_score": EPOCH, "description": "2026-12-02"})
        assert _four(plain.entity_id) == (WHEN, datetime(2026, 12, 3, tzinfo=UTC), "created", "day")

    @AC[34]
    def test_a_json_field_is_passed_to_its_reader_as_the_model_holds_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _declare(monkeypatch, Moment("tags", "created", reader=created_member))
        as_text = _create({"name": "json-text", "tags": {"created": "2026-12-01T19:30:00+01:00", "other": [1]}})
        assert _four(as_text.entity_id) == (WHEN, WHEN, "created", "second")
        as_number = _create({"name": "json-number", "tags": {"created": EPOCH}})
        assert _four(as_number.entity_id) == (WHEN, WHEN, "created", "second")
        absent = _create({"name": "json-absent", "tags": {"other": "x"}})
        assert _four(absent.entity_id) == (None, None, None, None)
        assert as_text.warnings == as_number.warnings == absent.warnings == []
        stored = PgNode.objects.get(entity_id=as_text.entity_id).tags
        assert stored == {"created": "2026-12-01T19:30:00+01:00", "other": [1]}

    @AC[31]
    def test_a_change_to_the_field_is_read_through_the_reader_again(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _declare(monkeypatch, Moment("description", "first_seen", reader=from_epoch_seconds))
        created = _create({"name": "moves", "description": str(EPOCH)})
        result = patch_node(created.entity_id, {"description": str(EPOCH + 3600)}, caller_context=_ctx())
        assert result.success, result.errors
        assert _four(created.entity_id)[0] == WHEN.replace(hour=19)

    @AC[31]
    def test_the_rederive_pass_uses_the_reader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_grid.event_time_rederive import rederive_event_time

        written = _create({"name": "before-the-declaration", "description": str(EPOCH)})
        assert _four(written.entity_id) == (None, None, None, None)
        _declare(monkeypatch, Moment("description", "first_seen", reader=from_epoch_seconds))
        report = rederive_event_time([_TYPE])
        assert report.changed == 1
        assert _four(written.entity_id) == (WHEN, WHEN, "first_seen", "second")
        # A changed function reaches stored rows through the same pass (rule 28).
        _declare(monkeypatch, Moment("description", "first_seen", reader=from_epoch_milliseconds))
        assert rederive_event_time([_TYPE]).changed == 1
        assert _four(written.entity_id)[0] == datetime(1970, 1, 21, 18, 55, 49, 800000, tzinfo=UTC)
        assert PgNode.objects.get(entity_id=written.entity_id).description == str(EPOCH)

    @AC[31]
    def test_an_import_derives_through_the_reader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A document from another grid carries the field as its source sent it and no spine values."""
        from tap_web.models import Panel

        monkeypatch.setattr(Panel, "EVENT_TIME", Moment("description", "published", reader=from_epoch_seconds))
        entity_id = str(uuid.uuid4())
        node = {
            "entity": {
                "entity_id": entity_id,
                "entity_type": "panel",
                "name": "p-reader",
                "dimensions": {"tap.graph": "web"},
            },
            "node": {
                "name": "p-reader",
                "slug": "p-reader",
                "description": str(EPOCH),
                "view": "tap_web/panel_error.html",
            },
        }
        result = grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[node])]))
        assert result.success, [error.message for error in result.errors]
        assert _four(entity_id) == (WHEN, WHEN, "published", "second")
        assert Panel.objects.get(entity_id=entity_id).description == str(EPOCH)


# ---------------------------------------------------------------------------
# Edge types name a reader by path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEdgeTypes:
    def _pair(self) -> tuple[Any, Any]:
        a = PgNode.objects.get(entity_id=_create({"name": "a"}).entity_id)
        b = PgNode.objects.get(entity_id=_create({"name": "b"}).entity_id)
        return a, b

    @AC[29]
    def test_an_edge_type_whose_definition_names_a_reader_by_path_derives_through_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(event_time._edge_event_time, LINK, None)  # restored after the test
        event_time.register_edge_event_time(
            LINK,
            {
                "shape": "moment",
                "field": "since",
                "kind": "first_seen",
                "reader": "tap_grid.event_time:from_epoch_seconds",
            },
        )
        a, b = self._pair()
        edge = create_edge(a.entity, b.entity, LINK, {"since": str(EPOCH)}, caller_context=_ctx())
        assert _four(edge.entity_id) == (WHEN, WHEN, "first_seen", "second")
        assert Edge.objects.get(entity_id=edge.entity_id).properties == {"since": str(EPOCH)}

    @AC[29]
    def test_an_interval_definition_names_a_reader_for_each_end(self) -> None:
        declared = declaration_from_definition(
            {
                "shape": "interval",
                "start": "from",
                "end": "until",
                "kind": "created",
                "reader": "tap_grid.event_time:from_epoch_seconds",
                "end_reader": f"{HERE}:unset_marker",
            }
        )
        assert declared == Interval(
            "from",
            "created",
            end="until",
            reader="tap_grid.event_time:from_epoch_seconds",
            end_reader=f"{HERE}:unset_marker",
        )

    @AC[30]
    def test_a_path_that_does_not_resolve_stops_the_load_naming_the_edge_type(self) -> None:
        before = dict(event_time._edge_event_time)
        for path, why in (
            (f"{HERE}:no_such_function", "does not resolve"),
            (f"{HERE}:not_a_function", "not a function"),
            ("builtins:eval", "not a function at module level"),
            ("os:system", "not a function at module level"),
            ("json:dumps", "not part of an installed app"),
        ):
            with pytest.raises(EventTimeDeclarationError, match=why) as raised:
                event_time.register_edge_event_time(
                    "BROKEN__edge", {"shape": "moment", "field": "since", "kind": "occurred", "reader": path}
                )
            assert "BROKEN__edge" in str(raised.value)
        assert event_time._edge_event_time == before

    @AC[30]
    def test_plugin_validation_fails_an_edge_definition_whose_reader_does_not_resolve(self) -> None:
        from tap_plugins.validate.service import _check_edge_event_time

        schema = {"type": "object", "properties": {"since": {"type": "string"}}}

        def run(entry: dict[str, Any]) -> Any:
            edge = SimpleNamespace(
                slug="LINKS_THING", file_path="edges/links.edge.json", event_time=entry, property_schema=schema
            )
            result: Any = SimpleNamespace(checks=[])
            _check_edge_event_time(SimpleNamespace(edges=[edge]), result)
            return result.checks[-1]

        good = {"shape": "moment", "field": "since", "kind": "first_seen", "reader": f"{HERE}:year_only"}
        assert run(good).status == "pass"
        broken = run({**good, "reader": f"{HERE}:no_such_function"})
        assert broken.status == "fail" and "no_such_function" in str(broken.messages)
        assert edge_declaration_problems({**good, "reader": f"{HERE}:not_a_function"}, schema)

    @AC[29]
    def test_the_edge_definition_schema_takes_a_path_and_nothing_else(self) -> None:
        import jsonschema

        schema = json.loads((SCHEMAS / "edge-definition.schema.json").read_text(encoding="utf-8"))
        base = {"slug": "X__y", "name": "X", "description": "x"}
        moment = {"shape": "moment", "field": "since", "kind": "first_seen", "reader": "pkg.times:read"}
        interval = {
            "shape": "interval",
            "start": "from",
            "end": "until",
            "kind": "created",
            "reader": "pkg.times:read",
            "end_reader": "pkg.times:read_end",
        }
        for entry in (moment, interval):
            jsonschema.validate({**base, "event_time": entry}, schema)
            declaration_from_definition(entry)
        for wrong in (
            {**moment, "reader": "pkg.times.read"},
            {**moment, "reader": 7},
            {**moment, "end_reader": "pkg.times:read"},
            {"shape": "interval", "start": "from", "kind": "created", "end_reader": "pkg.times:read"},
        ):
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate({**base, "event_time": wrong}, schema)
            with pytest.raises(EventTimeDeclarationError):
                declaration_from_definition(wrong)


# ---------------------------------------------------------------------------
# The version record names the function
# ---------------------------------------------------------------------------


class TestTheVersionRecord:
    @AC[32]
    def test_the_definition_names_the_reader_and_only_where_one_is_declared(self) -> None:
        plain = model_definition.event_time_definition(Moment("published_at", "published"))
        assert plain == {"shape": "moment", "field": "published_at", "kind": "published"}
        by_function = model_definition.event_time_definition(Moment("seen", "first_seen", reader=from_epoch_seconds))
        by_path = model_definition.event_time_definition(
            Moment("seen", "first_seen", reader="tap_grid.event_time:from_epoch_seconds")
        )
        assert (
            by_function
            == by_path
            == {**plain, "field": "seen", "kind": "first_seen", "reader": reader_name(from_epoch_seconds)}
        )
        assert reader_name(from_epoch_seconds) == "tap_grid.event_time:from_epoch_seconds"
        interval = model_definition.event_time_definition(
            Interval("a", "created", end="b", reader=from_epoch_seconds, end_reader=unset_marker)
        )
        assert interval["reader"] == "tap_grid.event_time:from_epoch_seconds"
        assert interval["end_reader"] == f"{HERE}:unset_marker"
        assert "end_reader" not in model_definition.event_time_definition(Interval("a", "created", end="b"))
        # Plain data, so the same on every run: no address and no repr of a function.
        assert "0x" not in json.dumps(interval) and "function" not in json.dumps(interval)

    @AC[32]
    def test_a_different_function_is_a_different_definition_and_changed_code_is_not(self) -> None:
        one = model_definition.event_time_definition(Moment("seen", "first_seen", reader=from_epoch_seconds))
        other = model_definition.event_time_definition(Moment("seen", "first_seen", reader=from_epoch_milliseconds))
        assert one != other
        # What the function does is not in the definition: a change of its code is the author's
        # to mark by raising the version by hand (rule 28).
        assert set(one) == {"shape", "field", "kind", "reader"}

    @AC[32]
    @pytest.mark.django_db
    def test_cores_committed_records_are_unchanged(self) -> None:
        """No core type names a reader, so every committed entry still matches its definition."""
        from tap.guards.model_version import core_problems

        assert core_problems() == []
        for owner, states in model_definition.core_states().items():
            for state in states:
                assert "reader" not in json.dumps(state.definition), (owner, state.label)


# ---------------------------------------------------------------------------
# A member inside a JSON field (rules 29 and 30)
# ---------------------------------------------------------------------------

ZONED = "2026-12-01T19:30:00+01:00"


@pytest.mark.django_db
class TestAMemberOfAJsonField:
    @AC[35]
    def test_zoned_text_inside_a_member_is_read_with_no_reader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _declare(monkeypatch, Moment("tags", "created", member="CreationDate"))
        tags = {"CreationDate": ZONED, "other": [1, {"k": "v"}]}
        made = _create({"name": "member-text", "tags": tags})
        assert _four(made.entity_id) == (WHEN, WHEN, "created", "second")
        assert made.warnings == []
        assert PgNode.objects.get(entity_id=made.entity_id).tags == tags

    @AC[35]
    def test_a_count_inside_a_member_goes_through_the_reader_as_the_member_s_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _declare(monkeypatch, Moment("tags", "created", member=("CreatedTimestamp",), reader=from_epoch_seconds))
        as_number = _create({"name": "member-number", "tags": {"CreatedTimestamp": EPOCH}})
        as_digits = _create({"name": "member-digits", "tags": {"CreatedTimestamp": str(EPOCH)}})
        assert _four(as_number.entity_id) == _four(as_digits.entity_id) == (WHEN, WHEN, "created", "second")
        assert PgNode.objects.get(entity_id=as_digits.entity_id).tags == {"CreatedTimestamp": str(EPOCH)}
        # Without the reader a count is not one of the forms the grid reads.
        _declare(monkeypatch, Moment("tags", "created", member="CreatedTimestamp"))
        unread = _create({"name": "member-number-unread", "tags": {"CreatedTimestamp": EPOCH}})
        assert _four(unread.entity_id) == (None, None, None, None)
        assert len(unread.warnings) == 1 and "tags['CreatedTimestamp']" in unread.warnings[0]

    @AC[35]
    def test_a_path_of_two_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _declare(monkeypatch, Moment("tags", "occurred", member=["Status", "StartedAt"]))
        made = _create({"name": "member-nested", "tags": {"Status": {"StartedAt": "2026-12"}}})
        assert _four(made.entity_id)[2:] == ("occurred", "month")
        assert _four(made.entity_id)[0] == datetime(2026, 12, 1, tzinfo=UTC)

    @AC[35]
    def test_an_interval_reads_its_two_ends_from_different_members(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _declare(
            monkeypatch,
            Interval(
                "tags",
                "created",
                end="tags",
                member="created",
                end_member=("lifecycle", "expires"),
                end_reader=unset_marker,
            ),
        )
        open_ended = _create({"name": "member-open", "tags": {"created": ZONED, "lifecycle": {"expires": "-1"}}})
        assert _four(open_ended.entity_id) == (WHEN, None, "created", "second")
        closed = _create(
            {"name": "member-closed", "tags": {"created": ZONED, "lifecycle": {"expires": str(EPOCH + 86400)}}}
        )
        assert _four(closed.entity_id) == (WHEN, WHEN.replace(day=2), "created", "second")
        assert open_ended.warnings == closed.warnings == []

    @AC[36]
    @pytest.mark.parametrize(
        "tags",
        [
            {"other": "x"},
            {"Status": None},
            {"Status": {"StartedAt": None}},
            {"Status": {}},
            {"Status": "running"},
            {"Status": ["2026-12-01"]},
        ],
        ids=["no-key", "null-on-the-way", "null-member", "no-inner-key", "text-on-the-way", "list-on-the-way"],
    )
    def test_a_member_that_is_not_there_states_no_time_and_calls_no_reader(
        self, monkeypatch: pytest.MonkeyPatch, tags: Any
    ) -> None:
        _declare(monkeypatch, Moment("tags", "created", member=("Status", "StartedAt"), reader=always_raises))
        made = _create({"name": "member-absent", "tags": tags})
        assert _four(made.entity_id) == (None, None, None, None)
        assert made.warnings == []
        assert PgNode.objects.get(entity_id=made.entity_id).tags == tags

    @AC[36]
    @pytest.mark.parametrize("held", [["Status"], "Status", 7, None, ""])
    def test_a_field_that_holds_no_object_states_no_time(self, held: Any) -> None:
        """Whatever the field holds in place of an object, the member is not there."""
        declaration = Moment("tags", "created", member=("Status", "StartedAt"), reader=always_raises)
        derived = event_time.derive(declaration, {"tags": held}.get)
        assert (derived.event_start, derived.kind, derived.warnings) == (None, None, ())

    @AC[36]
    def test_a_member_the_grid_cannot_read_warns_naming_the_field_and_the_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _declare(monkeypatch, Moment("tags", "created", member=("Status", "StartedAt")))
        made = _create({"name": "member-unreadable", "tags": {"Status": {"StartedAt": "2026-12-01T18:30"}}})
        assert _four(made.entity_id) == (None, None, None, None)
        assert len(made.warnings) == 1
        assert "tags['Status']['StartedAt']" in made.warnings[0]
        assert PgNode.objects.get(entity_id=made.entity_id).tags == {"Status": {"StartedAt": "2026-12-01T18:30"}}

    @AC[37]
    def test_a_member_named_on_a_field_that_is_not_json_fails_the_declaration_check(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _declare(monkeypatch, Moment("description", "created", member="CreationDate"))
        problems = declaration_problems(PgNode)
        assert len(problems) == 1 and "'description'" in problems[0] and "JSON field" in problems[0]
        # A reader beside it does not excuse the field: the member is still inside a JSON value.
        _declare(monkeypatch, Moment("description", "created", member="CreationDate", reader=from_epoch_seconds))
        assert len(declaration_problems(PgNode)) == 1
        _declare(monkeypatch, Moment("tags", "created", member="CreationDate"))
        assert declaration_problems(PgNode) == []
        _declare(monkeypatch, Interval("tags", "created", end="description", member="a", end_member="b"))
        assert len(declaration_problems(PgNode)) == 1

    @AC[37]
    @pytest.mark.parametrize("member", [(), [], "", ("a", ""), ("a", 0), 0, ("a", None), {"a": "b"}])
    def test_a_path_is_text_keys_and_nothing_else(self, member: Any) -> None:
        with pytest.raises(EventTimeDeclarationError):
            Moment("tags", "created", member=member)
        with pytest.raises(EventTimeDeclarationError):
            Interval("tags", "created", end="tags", end_member=member)

    @AC[37]
    def test_one_key_and_a_sequence_of_one_are_the_same_path_and_an_end_member_needs_an_end(self) -> None:
        assert Moment("tags", "created", member="a") == Moment("tags", "created", member=["a"])
        assert Moment("tags", "created", member="a").member == ("a",)
        assert Moment("tags", "created").member is None
        with pytest.raises(EventTimeDeclarationError, match="names no end"):
            Interval("tags", "created", end_member="a")

    @AC[37]
    def test_an_edge_definition_names_a_member_inside_an_object_property(self) -> None:
        import jsonschema

        schema = json.loads((SCHEMAS / "edge-definition.schema.json").read_text(encoding="utf-8"))
        base = {"slug": "X__y", "name": "X", "description": "x"}
        moment = {"shape": "moment", "field": "detail", "kind": "occurred", "member": ["at"]}
        interval = {
            "shape": "interval",
            "start": "detail",
            "end": "detail",
            "kind": "created",
            "member": ["window", "from"],
            "end_member": ["window", "until"],
            "end_reader": f"{HERE}:unset_marker",
        }
        for entry in (moment, interval):
            jsonschema.validate({**base, "event_time": entry}, schema)
        declared = declaration_from_definition(interval)
        assert isinstance(declared, Interval)
        assert (declared.member, declared.end_member) == (("window", "from"), ("window", "until"))
        for wrong in (
            {**moment, "member": "at"},
            {**moment, "member": []},
            {**moment, "member": ["at", 0]},
            {**moment, "end_member": ["at"]},
            {"shape": "interval", "start": "detail", "kind": "created", "end_member": ["until"]},
        ):
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate({**base, "event_time": wrong}, schema)
            with pytest.raises(EventTimeDeclarationError):
                declaration_from_definition(wrong)
        # The property a member is inside must be one the type's schema lets hold an object.
        as_object = {"type": "object", "properties": {"detail": {"type": "object"}}}
        untyped = {"type": "object", "properties": {"detail": {}}}
        as_text = {"type": "object", "properties": {"detail": {"type": "string"}}}
        assert edge_declaration_problems(moment, as_object) == []
        assert edge_declaration_problems(moment, untyped) == []
        refused = edge_declaration_problems(moment, as_text)
        assert len(refused) == 1 and "'detail'" in refused[0] and "object" in refused[0]
        # An edge's properties are read through the same derivation as a node's fields.
        properties = {"detail": {"window": {"from": ZONED, "until": "-1"}}}
        derived = event_time.derive(declared, properties.get)
        assert (derived.event_start, derived.event_end, derived.kind) == (WHEN, None, "created")
        assert properties == {"detail": {"window": {"from": ZONED, "until": "-1"}}}

    @AC[38]
    def test_a_patch_and_the_rederive_pass_derive_through_the_member(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_grid.event_time_rederive import rederive_event_time

        written = _create({"name": "member-before", "tags": {"CreationDate": ZONED}})
        assert _four(written.entity_id) == (None, None, None, None)
        _declare(monkeypatch, Moment("tags", "created", member="CreationDate"))
        assert rederive_event_time([_TYPE]).changed == 1
        assert _four(written.entity_id) == (WHEN, WHEN, "created", "second")
        result = patch_node(
            written.entity_id, {"tags": {"CreationDate": "2026-12-01T20:30:00+01:00"}}, caller_context=_ctx()
        )
        assert result.success, result.errors
        assert _four(written.entity_id)[0] == WHEN.replace(hour=19)
        assert PgNode.objects.get(entity_id=written.entity_id).tags == {"CreationDate": "2026-12-01T20:30:00+01:00"}

    @AC[38]
    def test_an_import_derives_through_the_member(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tap_web.models import Panel

        monkeypatch.setattr(Panel, "EVENT_TIME", Moment("config", "published", member=("meta", "published")))
        entity_id = str(uuid.uuid4())
        config = {"meta": {"published": ZONED}, "rows": 3}
        node = {
            "entity": {
                "entity_id": entity_id,
                "entity_type": "panel",
                "name": "p-member",
                "dimensions": {"tap.graph": "web"},
            },
            "node": {"name": "p-member", "slug": "p-member", "config": config, "view": "tap_web/panel_error.html"},
        }
        result = grift_import(_minimal_doc([_batch_container(_batch_entity_id(), nodes=[node])]))
        assert result.success, [error.message for error in result.errors]
        assert _four(entity_id) == (WHEN, WHEN, "published", "second")
        assert Panel.objects.get(entity_id=entity_id).config == config

    @AC[38]
    def test_the_definition_names_the_member_and_only_where_one_is_declared(self) -> None:
        plain = model_definition.event_time_definition(Moment("configuration", "created"))
        assert "member" not in plain
        one = model_definition.event_time_definition(Moment("configuration", "created", member="CreationDate"))
        other = model_definition.event_time_definition(Moment("configuration", "created", member="CreatedAt"))
        assert one == {**plain, "member": ["CreationDate"]}
        assert one != other and {k: v for k, v in one.items() if k != "member"} == plain
        as_list = model_definition.event_time_definition(Moment("configuration", "created", member=["CreationDate"]))
        assert as_list == one
        interval = model_definition.event_time_definition(
            Interval("configuration", "created", end="configuration", member="a", end_member=("b", "c"))
        )
        assert (interval["member"], interval["end_member"]) == (["a"], ["b", "c"])
        assert "end_member" not in model_definition.event_time_definition(
            Interval("configuration", "created", end="configuration", member="a")
        )
        assert model_definition.fingerprint("", 1, one) != model_definition.fingerprint("", 1, other)

    @AC[38]
    def test_cores_committed_records_name_no_member_and_are_unchanged(self) -> None:
        from tap.guards.model_version import core_problems

        assert core_problems() == []
        for owner, states in model_definition.core_states().items():
            for state in states:
                assert "member" not in json.dumps(state.definition.get("event_time")), (owner, state.label)


class TestAReaderComesFromInstalledCode:
    """A reader runs on a stored value, so it must be code the operator installed (rule 26)."""

    @AC[30]
    @pytest.mark.parametrize(
        ("path", "why"),
        [
            ("builtins:eval", "not a function at module level"),
            ("os:system", "not a function at module level"),
            ("subprocess:getoutput", "not part of an installed app"),
            ("json:dumps", "not part of an installed app"),
        ],
    )
    def test_a_path_outside_installed_apps_is_refused(self, path: str, why: str) -> None:
        event_time._resolved_readers.pop(path, None)
        with pytest.raises(EventTimeDeclarationError, match=why):
            event_time.resolve_reader(path)
        assert path not in event_time._resolved_readers

    @AC[30]
    def test_a_function_given_directly_from_outside_installed_apps_is_refused(self) -> None:
        import json as json_module

        with pytest.raises(EventTimeDeclarationError, match="not part of an installed app"):
            event_time.resolve_reader(json_module.dumps)

    @AC[30]
    def test_core_s_helpers_and_a_module_level_function_in_core_resolve(self) -> None:
        assert event_time.resolve_reader("tap_grid.event_time:from_epoch_seconds") is from_epoch_seconds
        assert event_time.resolve_reader(f"{HERE}:year_only") is year_only
