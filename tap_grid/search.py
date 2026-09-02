"""Search execution service — the single entry point for running TAP searches.

All search consumers (panels, API endpoints, tests) call execute_search().
No caller invokes execution modes or ORM queries directly.

Read-only enforcement: all queries run through the "search_readonly" DB alias,
which has PostgreSQL default_transaction_read_only=on. Writes are rejected at
the database level (req-grid-search-readonly.sec).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import time
from typing import TYPE_CHECKING, Any, cast

import jsonschema  # type: ignore[import-untyped]
from django.core.exceptions import ValidationError

from tap.db_aliases import SEARCH_READONLY
from tap_auth.capabilities import READ_CAPABILITY
from tap_auth.enforcement import requires_capability
from tap_grid.exceptions import SearchExecutionError
from tap_grid.grift.subgraph import SubgraphLayer

if TYPE_CHECKING:
    from tap_grid.models import Search

# DB alias used for all search execution. Configured in settings.py with
# PostgreSQL default_transaction_read_only=on.
_SEARCH_DB_ALIAS = SEARCH_READONLY

# Keys required at the top level of every canonical result envelope.
_ENVELOPE_KEYS = frozenset({"nodes", "edges"})


@requires_capability(READ_CAPABILITY, operation="execute_search")
def execute_search(
    search: Search,
    inputs: dict[str, Any] | None = None,
    *,
    limit: int | None = None,
    offset: int | None = None,
    layer: SubgraphLayer = "full",
) -> dict[str, Any]:
    """Execute a Search and return the canonical 4-key graph envelope.

    Read enforcement (req-tap-auth-service-boundary): Search is TAP's canonical
    graph read interface, and this is the single dispatch point above the orm/
    gryphon/module execution modes. `grid.read` is authorized here for the active
    CallerContext (resolved from the contextvar) before any mode runs, so every
    read goes through one gate. An unauthorized/absent actor fails closed.

    Args:
        search:  The Search model instance to execute.
        inputs:  Domain-specific execution inputs. Validated against
                 search.input_schema when present.
        limit:   Number of primary-side results to return. Clamped to
                 search.max_limit if set. None means use search.default_limit
                 (which itself may be None, meaning unpaginated).
        offset:  Zero-based offset into the primary-side results. Defaults to 0.
        layer:   GRIFT subgraph return layer (lite, full, extended).

    Returns:
        If paginated: {"count": int, "limit": int, "offset": int, "results": envelope}
        If unpaginated: {"nodes": [...], "edges": [...], "info": {...}, "warnings": {...}}

    Raises:
        ValidationError: inputs fail input_schema validation.
        SearchExecutionError: hard failure during execution.
    """
    validated_inputs = _validate_inputs(search, inputs or {})
    effective_limit, warnings = _resolve_limit(search, limit)
    effective_offset = offset or 0

    start_time = time.monotonic()

    if search.search_type == "module":
        raw_result = _execute_module_search(search, validated_inputs, _SEARCH_DB_ALIAS, layer=layer)
    elif search.search_type == "orm":
        raw_result = _execute_orm_search(
            search,
            validated_inputs,
            _SEARCH_DB_ALIAS,
            effective_limit,
            effective_offset,
            layer=layer,
        )
    elif search.search_type == "gryphon":
        raw_result = _execute_gryphon_search(search, validated_inputs, _SEARCH_DB_ALIAS, layer=layer)
    else:
        raise SearchExecutionError(f"Unknown search_type: {search.search_type!r}")

    elapsed_ms = round((time.monotonic() - start_time) * 1000)

    envelope = _normalize_envelope(raw_result)
    envelope["warnings"].update(warnings)
    envelope["info"].update(
        {
            "search_type": search.search_type,
            "root": search.root,
            "elapsed_ms": elapsed_ms,
        }
    )

    if effective_limit is not None:
        count = len(envelope["nodes"]) if search.root == "node" else len(envelope["edges"])
        return {
            "count": count,
            "limit": effective_limit,
            "offset": effective_offset,
            "results": envelope,
        }

    return envelope


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def inputs_from_query(search: Search, params: Mapping[str, str], *, reserved: Iterable[str] = ("limit", "offset", "page_size")) -> dict[str, Any]:
    """Pick a search's declared inputs out of a query string and coerce them by its own schema.

    A URL carries strings; a search's ``input_schema`` may declare an integer (a GitHub
    workflow id), a number or a boolean. Without coercion the string validates against
    nothing or — worse — passes a permissive schema and silently matches no rows, which
    renders as an empty table rather than an error. This is the ONE place that
    translation happens (derive-a-fact-once): every panel that forwards page parameters
    to a search calls it. Keys the schema does not declare are ignored, as are paging
    keys; a search with no schema receives nothing (it declared no inputs).

    Args:
        search: The Search whose ``input_schema`` names the accepted inputs.
        params: The query parameters (``request.GET`` or any string mapping).
        reserved: Keys that belong to the panel, never to the search.

    Returns:
        The coerced inputs, ready for :func:`execute_search`. Empty when nothing applies.
    """
    schema = search.input_schema if isinstance(search.input_schema, dict) else None
    properties = schema.get("properties") if schema else None
    if not isinstance(properties, dict):
        return {}
    out: dict[str, Any] = {}
    for key, sub in properties.items():
        if key in reserved or key not in params:
            continue
        raw = params[key]
        kind = sub.get("type") if isinstance(sub, dict) else None
        kinds = kind if isinstance(kind, list) else [kind]
        value: Any = raw
        try:
            if "integer" in kinds:
                value = int(raw)
            elif "number" in kinds:
                value = float(raw)
            elif "boolean" in kinds:
                value = raw.strip().lower() in ("1", "true", "yes", "on")
        except (TypeError, ValueError):
            value = raw  # let jsonschema report it as a type error, with the key named
        out[key] = value
    return out


def _validate_inputs(search: Search, inputs: dict[str, Any]) -> dict[str, Any]:
    """Validate execution inputs against search.input_schema, filling schema defaults first.

    A top-level property that is absent from ``inputs`` and declares a JSON Schema
    ``default`` takes that default before validation (req-grid-search-obj-5-2), so a
    search that names a ``$param`` can still run when the caller — a page opened
    without a query string, a badge refresh — supplied nothing. Only top-level
    properties are defaulted; a caller-supplied value is never overridden.

    Returns the (possibly defaulted) inputs if validation passes or no schema is set.
    Raises ValidationError on schema violation.
    """
    if not search.input_schema:
        return inputs
    schema = search.input_schema
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if isinstance(properties, dict):
        defaults = {
            key: sub["default"]
            for key, sub in properties.items()
            if isinstance(sub, dict) and "default" in sub and key not in inputs
        }
        if defaults:
            inputs = {**defaults, **inputs}
    try:
        jsonschema.validate(instance=inputs, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ValidationError({"inputs": [exc.message]}) from exc
    return inputs


def _resolve_limit(search: Search, caller_limit: int | None) -> tuple[int | None, dict[str, Any]]:
    """Apply pagination rules and return (effective_limit, warnings).

    1. caller_limit overrides search.default_limit.
    2. Effective limit is clamped to search.max_limit if set.
    3. Clamping is recorded in warnings.
    """
    warnings: dict[str, Any] = {}
    effective = caller_limit if caller_limit is not None else search.default_limit

    if effective is not None and search.max_limit is not None and effective > search.max_limit:
        warnings["max_limit_clamped"] = {
            "requested": effective,
            "clamped_to": search.max_limit,
        }
        effective = search.max_limit

    return effective, warnings


def _normalize_envelope(raw: Any) -> dict[str, Any]:
    """Ensure the raw result is a valid 4-key envelope.

    Raises SearchExecutionError if nodes/edges keys are missing.
    Adds empty info/warnings dicts if absent.
    """
    if not isinstance(raw, dict) or not _ENVELOPE_KEYS.issubset(raw.keys()):
        raise SearchExecutionError(
            f"Search result must be a dict with at least 'nodes' and 'edges' keys. "
            f"Got: {type(raw).__name__} with keys {sorted(raw.keys()) if isinstance(raw, dict) else 'N/A'}"
        )
    envelope: dict[str, Any] = {
        "nodes": raw["nodes"],
        "edges": raw["edges"],
        "info": dict(raw.get("info") or {}),
        "warnings": dict(raw.get("warnings") or {}),
    }
    # Preserve rows if the executor populated them (aggregating gryphon queries).
    # Per req-grid-gryphon-rows the field is always present in the envelope;
    # non-aggregating queries will produce an empty list here.
    if "rows" in raw:
        envelope["rows"] = list(raw["rows"])
    return envelope


# ---------------------------------------------------------------------------
# Execution mode stubs — filled in by later phases
# ---------------------------------------------------------------------------


def _execute_module_search(
    search: Search,
    validated_inputs: dict[str, Any],
    db_alias: str,
    *,
    layer: SubgraphLayer = "full",
) -> dict[str, Any]:
    """Resolve and invoke a module search runner.

    Looks up the runner via search_runner_registry. Raises SearchRunnerNotFoundError
    if the key is not registered. Raises SearchExecutionError if the runner raises
    or returns a malformed result.
    """
    from tap_grid.registry import get_search_runner

    runner_key: str = search.definition.get("runner_key", "")
    if not runner_key:
        raise SearchExecutionError("Module search definition is missing 'runner_key'.")

    runner = get_search_runner(runner_key)  # raises SearchRunnerNotFoundError on miss

    try:
        result = runner(search, validated_inputs, db_alias=db_alias, layer=layer)
    except Exception as exc:
        raise SearchExecutionError(f"Runner '{runner_key}' raised an exception: {exc}") from exc

    return cast(dict[str, Any], result)


def _execute_gryphon_search(
    search: Search,
    validated_inputs: dict[str, Any],
    db_alias: str,
    *,
    layer: SubgraphLayer = "full",
) -> dict[str, Any]:
    """Parse and execute a gryphon search."""
    from tap_grid.gryphon import execute_gryphon

    try:
        return execute_gryphon(search, validated_inputs, db_alias=db_alias, layer=layer)
    except Exception as exc:
        raise SearchExecutionError(f"Gryphon search execution failed: {exc}") from exc


def _execute_orm_search(
    search: Search,
    validated_inputs: dict[str, Any],
    db_alias: str,
    limit: int | None,
    offset: int,
    *,
    layer: SubgraphLayer = "full",
) -> dict[str, Any]:
    """Compile and execute an ORM DSL search."""
    from tap_grid.orm_compiler import compile_orm_query

    try:
        return compile_orm_query(search, db_alias, limit=limit, offset=offset, layer=layer)
    except Exception as exc:
        raise SearchExecutionError(f"ORM search execution failed: {exc}") from exc
