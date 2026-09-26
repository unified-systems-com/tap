"""scope.sec-5 — every raw Gryphon entrypoint binds the read-only search alias by default.

`req-grid-traversal-exec-scope.sec-5`. The stored-Search path already ran on
`search_readonly` (`_SEARCH_DB_ALIAS`), but the *raw* Gryphon entrypoints
(`execute_gryphon`, `execute_gryphon_raw`, `_execute_gryphon_raw_impl`,
`explain_gryphon_raw`) defaulted `db_alias="default"` — the **writable** connection.
Many live callers omit `db_alias` (the API router, batch counts, several panels), so the
read-only backstop the security design assumes (the write-block Flaw, the role-pinned
resource GUCs, the future least-privilege DB grant) was *not engaged* on the live raw path.
This pins the read-only alias as the fail-safe default so it cannot be silently omitted.
"""

import inspect

import pytest

from tap_grid.gryphon import executor

_READONLY_ALIAS = "search_readonly"


@pytest.mark.parametrize(
    "fn",
    [executor.execute_gryphon, executor._execute_gryphon_raw_impl],
    ids=lambda f: f.__name__,
)
def test_raw_entrypoint_defaults_to_readonly_alias(fn):
    """The undecorated raw entrypoints default db_alias to the read-only alias."""
    default = inspect.signature(fn).parameters["db_alias"].default
    assert default == _READONLY_ALIAS, (
        f"{fn.__name__} defaults db_alias to {default!r}; a caller that omits db_alias "
        f"would run on a writable connection (scope.sec-5)."
    )


@pytest.mark.django_db(databases=["default", "search_readonly"])
def test_execute_gryphon_raw_binds_readonly_when_alias_omitted(monkeypatch):
    """Behavioral (decorator-agnostic): calling the gated raw entrypoint with no
    db_alias reaches the executor body on the read-only alias."""
    seen: dict[str, str] = {}

    def _spy(query, inputs, *, db_alias, layer, scope):
        seen["db_alias"] = db_alias
        seen["scope"] = scope
        return {"nodes": [], "edges": []}

    monkeypatch.setattr(executor, "_execute_gryphon_raw_impl", _spy)
    executor.execute_gryphon_raw("MATCH (a:program) RETURN a", {})
    assert seen["db_alias"] == _READONLY_ALIAS
    # The same call also reaches the body under the default read scope
    # (req-grid-traversal-exec-read-scope-1).
    from tap_grid.gryphon.read_scope import LiveNow

    assert isinstance(seen["scope"], LiveNow)
