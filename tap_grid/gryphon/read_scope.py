"""The Gryphon read scope — the one place that defines what a read may see.

Every Gryphon read runs under exactly one :class:`ReadScope`, applied at every relation the
compiled query touches: the root relation, every joined edge, and both endpoint entities of
every edge (``req-grid-traversal-exec-read-scope``). The default, :data:`DEFAULT_SCOPE`
(:class:`LiveNow`), excludes tombstoned nodes and edges.

Before this module, liveness was a side effect of which manager a queryset started from: a
``LiveManager`` filters only a queryset's ROOT model, so a relation reached through a join
(an edge at hop >= 1, a chain endpoint, a NOT EXISTS inner hop, an OPTIONAL MATCH count) was
unscoped (``Issue# 811 - tap``), and a read rooted at the spine was unscoped too
(``Issue# 802 - tap``). Every correct site was correct by accident.

The module owns three things, and the executor may reach the grid only through them:

1. **Base relations** — :func:`node_relation`, :func:`edge_relation`, :func:`refetch_nodes`,
   :func:`refetch_edges`. The only querysets Gryphon starts from; each carries the scope.
2. **Scoped joins** — :func:`reverse_edge_path` builds every multi-valued hop path, and
   :func:`edge_scope_filters` / :func:`node_scope_filters` return the predicates for a joined
   edge or endpoint. The caller merges them into the SAME ``filter()`` call as the hop's other
   conditions: on a multi-valued relation a separate ``filter()`` makes Django add a second
   JOIN, which would carry the predicate while the hop's own JOIN did not.
3. **Enforcement** — every base relation is a scope-checked queryset. Immediately before it
   executes, the compiled query is walked (:func:`assert_query_scoped`): every spine alias,
   and every grid-table alias, must be bound to a spine alias that carries the active scope's
   predicate. A missing predicate raises :class:`SearchExecutionError` before any SQL runs.
   This checks the property itself, so it holds however the queryset was assembled. The
   ``gryphon-read-scope`` guard (``tap_grid/guards/gryphon_read_scope.py``) is the secondary,
   review-time layer: it flags manager access and reverse-edge lookup strings anywhere in
   ``tap_grid/gryphon/`` outside this module.

Widening: only a caller-supplied scope widens a read, and no widening scope exists yet —
the temporal variants (:class:`AsOf`, :class:`Between`, ``req-grid-traversal-exec-temporal-scope``)
refuse construction, so nothing can fall back to :class:`LiveNow` silently.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Literal

from django.core.exceptions import EmptyResultSet, FullResultSet

from tap_grid.exceptions import SearchExecutionError
from tap_grid.models import BaseModel, BaseModelQuerySet, Edge, Entity, EntityQuerySet

# The Entity field that carries tombstone state (req-grid-entity-tombstone-managers).
_DELETED_AT = "deleted_at"

# Reverse relations from an Entity to the edges it is an endpoint of (`Edge.from_entity` /
# `Edge.to_entity` related names). Multi-valued: every hop past the root edge crosses one.
_EDGES_OUT = "edges_out"
_EDGES_IN = "edges_in"


# ---------------------------------------------------------------------------
# The scope value
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReadScope:
    """What a Gryphon read may see. Construct a concrete variant, never this base."""

    def describe(self) -> str:
        """A short, stable name for the scope (diagnostics and error messages)."""
        raise NotImplementedError


@dataclass(frozen=True)
class LiveNow(ReadScope):
    """The current grid, excluding tombstoned nodes and edges. The default."""

    def describe(self) -> str:
        return "LiveNow"


class _NotBuiltScope(ReadScope):
    """A specified but unbuilt scope: constructing one fails closed."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise SearchExecutionError(
            f"The {type(self).__name__} read scope is not implemented. Temporal scopes are specified "
            "(req-grid-traversal-exec-temporal-scope) but not built, and a read never falls back to the "
            "live grid in their place."
        )


class AsOf(_NotBuiltScope):
    """The grid as it was at one instant (``req-grid-traversal-exec-temporal-scope``). Not built."""


class Between(_NotBuiltScope):
    """The grid's versions across a window (``req-grid-traversal-exec-temporal-scope``). Not built."""


DEFAULT_SCOPE: ReadScope = LiveNow()


def require_scope(scope: object) -> ReadScope:
    """Return ``scope`` if this build can execute it, else refuse.

    The one place a caller's scope is accepted or refused before a read runs. Only :class:`LiveNow` is executable today. A widening scope will additionally require a
    dedicated capability, checked here, when the first one is built
    (``req-grid-traversal-exec-read-scope-13``); until then there is nothing to widen to.
    """
    if isinstance(scope, LiveNow):
        return scope
    raise SearchExecutionError(
        f"Unsupported read scope {scope!r}. Gryphon reads run under LiveNow; no other scope is "
        "implemented (req-grid-traversal-exec-read-scope)."
    )


# ---------------------------------------------------------------------------
# Paths and predicates for joined relations
# ---------------------------------------------------------------------------


def reverse_edge_path(entity_path: str, direction: Literal["out", "in"]) -> str:
    """The ORM path from an Entity (at ``entity_path``) to the edges it is an endpoint of.

    ``"out"`` crosses ``edges_out`` (the entity is the edge's ``from_entity``); ``"in"`` crosses
    ``edges_in``. The relation is multi-valued, so its scope predicates must be merged into the
    same ``filter()`` as the hop's other conditions (see the module docstring).
    """
    relation = _EDGES_OUT if direction == "out" else _EDGES_IN
    return f"{entity_path}__{relation}" if entity_path else relation


def is_reverse_edge_path(path: str) -> bool:
    """True when ``path`` crosses a reverse edge relation — a hop past the root edge."""
    parts = path.split("__")
    return _EDGES_OUT in parts or _EDGES_IN in parts


def entity_scope_filters(scope: ReadScope, entity_path: str) -> dict[str, Any]:
    """Filter kwargs admitting only the spine rows ``scope`` may see, at ``entity_path``.

    TAP-IMPLEMENTS: req-grid-traversal-exec-read-scope@b14d66a73935/f7bd287ff822 (derivation) —
        the one definition of what a scope admits; every base relation and scoped join calls it.

    ``entity_path`` is the ORM path to an Entity row (``""`` for a spine queryset's own row).
    For ``LiveNow`` the predicate is ``deleted_at IS NULL``. Every other helper in this module
    reaches the predicate through here, so the definition of "live" has exactly one home.
    """
    require_scope(scope)
    return {f"{entity_path}__{_DELETED_AT}__isnull" if entity_path else f"{_DELETED_AT}__isnull": True}


def edge_scope_filters(scope: ReadScope, edge_path: str) -> dict[str, Any]:
    """Filter kwargs that scope the edge row at ``edge_path`` (``""`` is the queryset's own edge)."""
    return entity_scope_filters(scope, f"{edge_path}__entity" if edge_path else "entity")


def node_scope_filters(scope: ReadScope, entity_path: str) -> dict[str, Any]:
    """Filter kwargs that scope the Entity at ``entity_path`` (an edge endpoint FK path)."""
    return entity_scope_filters(scope, entity_path)


# ---------------------------------------------------------------------------
# Base relations
# ---------------------------------------------------------------------------


class _ScopeCheckedMixin:
    """Run the compiled-query scope check before any database read of this queryset.

    Every read path Django offers funnels through one of the overridden methods: iteration,
    ``list()``, ``len()``, ``bool()``, ``values()`` / ``values_list()`` iteration and slicing all
    reach ``_fetch_all``; the rest execute their own SQL and are overridden individually.
    """

    _read_scope: ReadScope | None = None

    def _clone(self) -> Any:
        clone = super()._clone()  # type: ignore[misc]
        clone._read_scope = self._read_scope
        return clone

    def _assert_scoped(self) -> None:
        if self._read_scope is None:
            raise SearchExecutionError(
                "Internal: a Gryphon queryset reached execution without a read scope "
                "(req-grid-traversal-exec-read-scope-9)."
            )
        assert_query_scoped(self.query, self.db, self._read_scope)  # type: ignore[attr-defined]

    def _fetch_all(self) -> None:
        if self._result_cache is None:  # type: ignore[attr-defined]
            self._assert_scoped()
        super()._fetch_all()  # type: ignore[misc]

    def iterator(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        self._assert_scoped()
        result: Iterator[Any] = super().iterator(*args, **kwargs)  # type: ignore[misc]
        return result

    def count(self) -> int:
        self._assert_scoped()
        result: int = super().count()  # type: ignore[misc]
        return result

    def exists(self) -> bool:
        self._assert_scoped()
        result: bool = super().exists()  # type: ignore[misc]
        return result

    def aggregate(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self._assert_scoped()
        result: dict[str, Any] = super().aggregate(*args, **kwargs)  # type: ignore[misc]
        return result

    def contains(self, obj: Any) -> bool:
        self._assert_scoped()
        result: bool = super().contains(obj)  # type: ignore[misc]
        return result

    def in_bulk(self, *args: Any, **kwargs: Any) -> dict[Any, Any]:
        self._assert_scoped()
        result: dict[Any, Any] = super().in_bulk(*args, **kwargs)  # type: ignore[misc]
        return result

    def explain(self, *args: Any, **kwargs: Any) -> str:
        self._assert_scoped()
        result: str = super().explain(*args, **kwargs)  # type: ignore[misc]
        return result


class ScopedEntityQuerySet(_ScopeCheckedMixin, EntityQuerySet):
    """A spine queryset that refuses to execute unless every relation it reads is scoped."""


class ScopedBaseModelQuerySet(_ScopeCheckedMixin, BaseModelQuerySet):
    """A typed-row queryset (keeps the ORM read backstop) that refuses to execute unscoped."""


def _scoped(queryset: Any, scope: ReadScope) -> Any:
    queryset._read_scope = scope
    return queryset


def node_relation(scope: ReadScope, model: type[BaseModel] | None = None, *, db_alias: str) -> Any:
    """Typed rows of ``model`` — or spine rows when ``model`` is ``None`` — under ``scope``."""
    if model is None:
        qs = _scoped(ScopedEntityQuerySet(model=Entity, using=db_alias), scope)
        return qs.filter(**entity_scope_filters(scope, ""))
    qs = _scoped(ScopedBaseModelQuerySet(model=model, using=db_alias), scope)
    return qs.filter(**entity_scope_filters(scope, "entity"))


def edge_relation(scope: ReadScope, *, db_alias: str) -> Any:
    """Edge rows under ``scope``: the edge itself AND both of its endpoints.

    Endpoint liveness is also a write-time rule (no live edge onto a tombstone, tap#609); the
    read does not rely on it, so a grid that violates the rule still reads consistently.
    """
    qs = _scoped(ScopedBaseModelQuerySet(model=Edge, using=db_alias), scope)
    return qs.filter(
        **edge_scope_filters(scope, ""),
        **node_scope_filters(scope, "from_entity"),
        **node_scope_filters(scope, "to_entity"),
    )


def refetch_nodes(scope: ReadScope, entity_ids: Iterable[str], *, db_alias: str) -> list[Any]:
    """Re-hydrate spine rows by id under ``scope``, so a re-fetch can never widen an answer."""
    ids = sorted(entity_ids)  # sorted: the IN-list SQL stays deterministic (Gridkin snapshots)
    if not ids:
        return []
    return list(node_relation(scope, None, db_alias=db_alias).filter(pk__in=ids))


def refetch_edges(scope: ReadScope, entity_ids: Iterable[str], *, db_alias: str) -> list[Any]:
    """Re-hydrate edge rows by entity id under ``scope`` (edge and both endpoints)."""
    ids = sorted(entity_ids)
    if not ids:
        return []
    return list(edge_relation(scope, db_alias=db_alias).filter(entity_id__in=ids).select_related("entity"))


# ---------------------------------------------------------------------------
# Enforcement: the compiled-query check
# ---------------------------------------------------------------------------


def _grid_tables() -> tuple[str, frozenset[str]]:
    """The spine table and every grid-table (BaseModel) table, read from the model registry."""
    from django.apps import apps

    domain = frozenset(m._meta.db_table for m in apps.get_models() if issubclass(m, BaseModel) and not m._meta.abstract)
    return Entity._meta.db_table, domain


def _conjunctive_scope_aliases(node: Any) -> set[str]:
    """Aliases whose ``deleted_at IS NULL`` is ANDed at the top of ``node`` (never under OR/NOT).

    A predicate under an OR or a negation does not scope the alias — ``(deleted_at IS NULL OR
    x)`` admits a tombstone — so only an unbroken chain of non-negated ANDs counts.
    """
    from django.db.models.lookups import IsNull
    from django.db.models.sql.where import AND, WhereNode

    found: set[str] = set()
    if isinstance(node, WhereNode):
        if node.negated or node.connector != AND:
            return found
        for child in node.children:
            found |= _conjunctive_scope_aliases(child)
        return found
    if isinstance(node, IsNull) and node.rhs is True:
        target = getattr(node.lhs, "target", None)
        alias = getattr(node.lhs, "alias", None)
        if alias is not None and target is not None and target.model is Entity and target.name == _DELETED_AT:
            found.add(alias)
    return found


def _walk_expressions(node: Any, *, skip: tuple[type, ...] = ()) -> Iterator[Any]:
    """Every expression under ``node`` (where-tree children and expression sources), depth first.

    Instances of a ``skip`` type are neither yielded nor descended into.
    """
    from django.db.models.sql.where import WhereNode

    stack = [node]
    while stack:
        current = stack.pop()
        if current is None or (skip and isinstance(current, skip)):
            continue
        yield current
        if isinstance(current, WhereNode):
            stack.extend(current.children)
            continue
        get_sources = getattr(current, "get_source_expressions", None)
        if callable(get_sources):
            stack.extend(get_sources())
        for side in ("lhs", "rhs"):
            value = getattr(current, side, None)
            if value is not None and hasattr(value, "resolve_expression"):
                stack.append(value)


def _aliases_read_outside_aggregates(node: Any) -> set[str]:
    """Aliases of every column ``node`` reads, not counting columns read inside an aggregate."""
    from django.db.models import Aggregate
    from django.db.models.expressions import Col

    return {expr.alias for expr in _walk_expressions(node, skip=(Aggregate,)) if isinstance(expr, Col)}


def _subqueries(query: Any) -> Iterator[Any]:
    """Every subquery (``Exists``, ``Subquery``, a queryset used as an ``__in`` value) in ``query``."""
    from django.db.models.sql.query import Query

    roots: list[Any] = [query.where, *query.annotations.values()]
    for root in roots:
        for expr in _walk_expressions(root):
            inner = getattr(expr, "query", None)
            if isinstance(inner, Query) and inner is not query:
                yield inner
            if isinstance(expr, Query) and expr is not query:
                yield expr


def _unscoped_aliases(query: Any) -> list[str]:
    """Describe every relation in a COMPILED ``query`` that the LiveNow scope does not bind.

    The rule, per alias in ``query.alias_map``:

    - a spine (``tap_entity``) alias must carry ``deleted_at IS NULL`` itself;
    - a grid-table alias is live exactly when its OWN spine row is: either it was joined FROM a
      spine alias on its own ``entity_id`` (a typed row reached from its entity — the parent
      must then be scoped), or a spine alias is joined FROM it on its ``entity_id`` and that
      spine alias is scoped (an edge's own entity, or a root typed row's entity).

    "Carries the predicate" means ANDed into the WHERE tree. The one other accepted place is an
    aggregate's ``FILTER`` clause (OPTIONAL MATCH's zero-preserving ``Count(..., filter=...)``):
    accepted only when EVERY aggregate in the query carries it and no non-aggregate expression
    reads the alias, so no value computed outside the filtered aggregates can see the row.
    """
    from django.db.models import Aggregate
    from django.db.models.sql.datastructures import Join

    spine_table, domain_tables = _grid_tables()
    scoped = _conjunctive_scope_aliases(query.where)

    aggregates = [a for a in query.annotations.values() if isinstance(a, Aggregate)]
    agg_scoped: set[str] = set()
    if aggregates and all(a.filter is not None for a in aggregates):
        per_aggregate = [_conjunctive_scope_aliases(a.filter.condition) for a in aggregates]
        agg_scoped = set.intersection(*per_aggregate) if per_aggregate else set()
    if agg_scoped:
        outside = _aliases_read_outside_aggregates(query.where)
        for annotation in query.annotations.values():
            outside |= _aliases_read_outside_aggregates(annotation)
        if isinstance(query.group_by, tuple):
            for expr in query.group_by:
                outside |= _aliases_read_outside_aggregates(expr)
        agg_scoped -= outside

    def is_scoped(alias: str) -> bool:
        return alias in scoped or alias in agg_scoped

    problems: list[str] = []
    for alias, join in query.alias_map.items():
        table = join.table_name
        if table == spine_table:
            if not is_scoped(alias):
                problems.append(f"spine alias {alias!r} has no `deleted_at IS NULL`")
            continue
        if table not in domain_tables:
            continue
        # A typed row reached from its own entity: live iff that entity is.
        if isinstance(join, Join) and join.join_cols == (("id", "entity_id"),):
            parent = query.alias_map.get(join.parent_alias)
            if parent is not None and parent.table_name == spine_table:
                if not is_scoped(join.parent_alias):
                    problems.append(f"{table} alias {alias!r} is reached from an unscoped spine alias")
                continue
        own_entity = [
            child_alias
            for child_alias, child in query.alias_map.items()
            if isinstance(child, Join)
            and child.parent_alias == alias
            and child.table_name == spine_table
            and child.join_cols == (("entity_id", "id"),)
        ]
        if not any(is_scoped(a) for a in own_entity):
            problems.append(f"{table} alias {alias!r} is not bound to a scoped spine row")
    return problems


def assert_query_scoped(query: Any, using: str, scope: ReadScope) -> None:
    """Fail closed unless every relation the compiled ``query`` reads is scoped.

    TAP-IMPLEMENTS: req-grid-traversal-exec-read-scope@b14d66a73935/f79849691669 (enforcement) — the
        primary enforcement: the property is checked on the compiled query, not on the source text.

    Compiles a CLONE first, because some joins (``select_related``, ``order_by`` across a
    relation) are only added at compile time; checking the uncompiled query would miss them.
    Compiling issues no SQL. Recurses into every subquery (NOT EXISTS is an ``Exists``).
    """
    require_scope(scope)
    compiled = query.chain()
    try:
        compiled.get_compiler(using=using).as_sql()
    except EmptyResultSet, FullResultSet:
        pass
    pending = [compiled]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        problems = _unscoped_aliases(current)
        if problems:
            raise SearchExecutionError(
                "Refusing to execute a Gryphon read that is not fully scoped to "
                f"{scope.describe()}: " + "; ".join(problems) + ". Every relation a read touches must be "
                "built through tap_grid.gryphon.read_scope (req-grid-traversal-exec-read-scope-9)."
            )
        pending.extend(_subqueries(current))
