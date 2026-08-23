"""Tests for search runner registry and search-related exceptions."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from tap.pytest_harness import isolated_registry
from tap_grid.exceptions import (
    EdgePropertyValidationError,
    InvalidEdgeError,
    InvalidSearchDefinitionError,
    SearchExecutionError,
    SearchRunnerNotFoundError,
)
from tap_grid.registry import get_search_runner, register_search_runner, search_runner_registry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runner(name: str = "runner"):
    """Return a trivial callable with a predictable __module__."""

    def runner(search, inputs, *, db_alias):
        return {"nodes": [], "edges": [], "info": {}, "warnings": {}}

    runner.__name__ = name
    runner.__module__ = "tap_grid.tests.fake_module"
    return runner


# ---------------------------------------------------------------------------
# Registry isolation fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolate_search_registry():
    with isolated_registry(search_runner_registry):
        yield


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    def test_invalid_search_definition_error_is_exception(self):
        exc = InvalidSearchDefinitionError("bad definition")
        assert isinstance(exc, Exception)
        assert str(exc) == "bad definition"

    def test_search_runner_not_found_error_is_exception(self):
        exc = SearchRunnerNotFoundError("not found")
        assert isinstance(exc, Exception)

    def test_search_execution_error_is_exception(self):
        exc = SearchExecutionError("hard fail")
        assert isinstance(exc, Exception)

    def test_existing_exceptions_unaffected(self):
        assert issubclass(InvalidEdgeError, Exception)
        assert issubclass(EdgePropertyValidationError, Exception)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestSearchRunnerRegistration:
    def test_register_and_retrieve(self):
        runner = _make_runner()
        register_search_runner("my-search", runner, scope="tap_plugins.example")
        result = get_search_runner("tap_plugins.example:my-search")
        assert result is runner

    def test_scope_inferred_from_module(self):
        runner = _make_runner()
        register_search_runner("my-search", runner)
        # runner.__module__ is "tap_grid.tests.fake_module"
        result = get_search_runner("tap_grid.tests.fake_module:my-search")
        assert result is runner

    def test_duplicate_registration_raises(self):
        runner = _make_runner()
        register_search_runner("dup", runner, scope="my.scope")
        with pytest.raises(ImproperlyConfigured, match="already registered"):
            register_search_runner("dup", _make_runner("other"), scope="my.scope")

    def test_different_scopes_same_key_coexist(self):
        r1 = _make_runner("r1")
        r2 = _make_runner("r2")
        register_search_runner("users", r1, scope="plugin.a")
        register_search_runner("users", r2, scope="plugin.b")
        assert get_search_runner("plugin.a:users") is r1
        assert get_search_runner("plugin.b:users") is r2

    def test_multiple_keys_same_scope(self):
        r1 = _make_runner("r1")
        r2 = _make_runner("r2")
        register_search_runner("alpha", r1, scope="my.plugin")
        register_search_runner("beta", r2, scope="my.plugin")
        assert get_search_runner("my.plugin:alpha") is r1
        assert get_search_runner("my.plugin:beta") is r2


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


class TestSearchRunnerLookup:
    def test_missing_runner_raises_search_runner_not_found(self):
        with pytest.raises(SearchRunnerNotFoundError, match="no-such-key"):
            get_search_runner("scope:no-such-key")

    def test_error_message_lists_registered_keys(self):
        register_search_runner("existing", _make_runner(), scope="my.scope")
        with pytest.raises(SearchRunnerNotFoundError) as exc_info:
            get_search_runner("my.scope:missing")
        assert "my.scope:existing" in str(exc_info.value)

    def test_short_key_ambiguous_raises(self):
        register_search_runner("common", _make_runner("r1"), scope="scope.a")
        register_search_runner("common", _make_runner("r2"), scope="scope.b")
        with pytest.raises(KeyError, match="ambiguous"):
            search_runner_registry.get("common")

    def test_short_key_unambiguous_resolves(self):
        runner = _make_runner()
        register_search_runner("unique-key", runner, scope="only.scope")
        result = search_runner_registry.get("unique-key")
        assert result is runner

    def test_in_operator(self):
        runner = _make_runner()
        register_search_runner("present", runner, scope="s")
        assert "s:present" in search_runner_registry
        assert "s:absent" not in search_runner_registry


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


class TestSearchRunnerRegistryInspection:
    def test_keys_returns_sorted_fq_keys(self):
        register_search_runner("b", _make_runner(), scope="scope")
        register_search_runner("a", _make_runner(), scope="scope")
        assert search_runner_registry.keys() == ["scope:a", "scope:b"]

    def test_scopes_returns_sorted_scopes(self):
        register_search_runner("x", _make_runner(), scope="b.scope")
        register_search_runner("x", _make_runner(), scope="a.scope")
        assert search_runner_registry.scopes() == ["a.scope", "b.scope"]

    def test_all_returns_nested_dict(self):
        runner = _make_runner()
        register_search_runner("search", runner, scope="my.scope")
        result = search_runner_registry.all()
        assert result == {"my.scope": {"search": runner}}

    def test_registry_visible_in_meta_registry(self):
        from tap_grid.registry import meta_registry

        assert "search_runner" in meta_registry
