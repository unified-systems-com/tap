"""`jsonschema_validate` is `jsonschema.validate` with each schema checked once (tap#1280).

`jsonschema.validate` re-runs `check_schema` on every call; on the GRIFT import path that cost more
than the validation itself. The cached helper must raise exactly what `jsonschema.validate` raises,
while checking each distinct schema against its metaschema only once.
"""

from __future__ import annotations

import uuid
from typing import Any

import jsonschema
import pytest

from tap import jsonfiles
from tap.jsonfiles import jsonschema_validate

pytestmark = pytest.mark.spec("req-tap-json-loader-6")


def _schema() -> dict[str, Any]:
    """A schema no other test has cached: a unique title gives it its own key."""
    return {
        "title": f"probe-{uuid.uuid4()}",
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string", "minLength": 1}, "tags": {"type": "array"}},
        "additionalProperties": False,
    }


@pytest.mark.parametrize(
    "instance",
    [{}, {"name": ""}, {"name": 3}, {"name": "x", "extra": 1}, {"name": "x", "tags": "no"}, []],
    ids=["missing", "too-short", "wrong-type", "extra", "nested", "not-object"],
)
def test_a_failing_instance_raises_what_jsonschema_validate_raises(instance):
    schema = _schema()
    with pytest.raises(jsonschema.ValidationError) as expected:
        jsonschema.validate(instance=instance, schema=schema)
    for _ in range(2):  # the cold call and the cached one
        with pytest.raises(jsonschema.ValidationError) as actual:
            jsonschema_validate(instance, schema)
        assert type(actual.value) is type(expected.value)
        assert str(actual.value) == str(expected.value)
        assert actual.value.message == expected.value.message
        assert list(actual.value.absolute_path) == list(expected.value.absolute_path)
        assert actual.value.validator == expected.value.validator


def test_a_valid_instance_passes():
    jsonschema_validate({"name": "Frodo", "tags": []}, _schema())


def test_an_invalid_schema_raises_schema_error_on_every_call():
    schema = {"title": f"probe-{uuid.uuid4()}", "type": "no-such-type"}
    with pytest.raises(jsonschema.SchemaError) as expected:
        jsonschema.validate(instance={}, schema=schema)
    for _ in range(2):
        with pytest.raises(jsonschema.SchemaError) as actual:
            jsonschema_validate({}, schema)
        assert str(actual.value) == str(expected.value)


def test_check_schema_runs_once_across_repeated_calls(monkeypatch):
    calls: list[Any] = []
    cls = jsonschema.validators.validator_for(_schema())
    original = cls.check_schema.__func__

    def counting(c: Any, /, s: Any, **kw: Any) -> Any:
        calls.append(s)
        return original(c, s, **kw)

    monkeypatch.setattr(cls, "check_schema", classmethod(counting))
    schema = _schema()
    for _ in range(5):
        jsonschema_validate({"name": "Sam"}, schema)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema_validate({"name": ""}, schema)
    jsonschema_validate({"name": "Sam"}, dict(schema))  # an equal schema in a different dict shares it
    assert len(calls) == 1


def test_mutating_the_schema_after_a_call_takes_effect():
    """The key is the schema's content, not its identity: a mutated dict is a new schema."""
    schema = _schema()
    jsonschema_validate({"name": "x"}, schema)
    schema["properties"]["name"]["minLength"] = 2
    with pytest.raises(jsonschema.ValidationError):
        jsonschema_validate({"name": "x"}, schema)
    restored = _schema() | {"title": schema["title"]}  # the original content, a fresh dict
    jsonschema_validate({"name": "x"}, restored)  # the first validator was not changed by the mutation


def test_the_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(jsonfiles, "_VALIDATOR_CACHE_MAX", 3)
    monkeypatch.setattr(jsonfiles, "_validators", {})
    for _ in range(10):
        jsonschema_validate({"name": "x"}, _schema())
    assert len(jsonfiles._validators) == 3
