"""Grid-specific registries and helpers.

The **generic** registry machinery (`Registry`, `ScopedRegistry`,
`meta_registry`) is a platform-wide capability and now lives in
``tap/registry.py`` — a peer of ``tap/jsonfiles.py`` — so apps build registries
without importing the graph app. They are re-exported here for backward
compatibility (``from tap_grid.registry import Registry`` keeps working), but
new non-grid code should import them from ``tap.registry`` directly.

This module owns the registries that *do* depend on the graph:
  entity_model registry + `register_entity_type` / `get_model_class` / `resolve_entity`
  search_runner registry + `register_search_runner` / `get_search_runner`
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured

# Re-exported for backward compatibility; canonical home is tap.registry.
from tap.registry import Registry, ScopedRegistry, meta_registry

if TYPE_CHECKING:
    from tap_grid.models import BaseModel, Entity


# ---------------------------------------------------------------------------
# Entity model registry — maps entity_type slugs to concrete ORM model classes.
# Populated at class-definition time via BaseModel.__init_subclass__.
# ---------------------------------------------------------------------------

_entity_model_registry: Registry[type] = Registry(
    "entity_model",
    title="Entity Model Registry",
    description="Maps entity type slugs to their Django ORM model classes.",
)

# Backward compatibility: some callers import _ENTITY_MODEL_REGISTRY directly.
_ENTITY_MODEL_REGISTRY = _entity_model_registry


# ---------------------------------------------------------------------------
# Public API (backward compatible)
# ---------------------------------------------------------------------------


def register_entity_type(entity_type: str, model_cls: type) -> None:
    """Register a model class for the given entity_type slug.

    Called from BaseModel.__init_subclass__ for every concrete subclass that
    declares ENTITY_TYPE.

    Re-registering the same class for the same type is idempotent (no-op).
    Registering a different class for an already-registered type raises
    ImproperlyConfigured.
    """
    if entity_type in _entity_model_registry:
        existing = _entity_model_registry.get(entity_type)
        if existing is model_cls:
            return
        raise ImproperlyConfigured(
            f"Entity type '{entity_type}' is already registered to {existing.__name__}. "
            f"Cannot also register {model_cls.__name__}."
        )
    _entity_model_registry.register(entity_type, model_cls)


def list_entity_types() -> list[str]:
    """Return a sorted list of all registered entity type slugs."""
    return _entity_model_registry.keys()


def get_model_class(entity_type: str) -> type:
    """Return the model class registered for the given entity_type slug.

    Raises KeyError with a descriptive message if the type is unknown.
    """
    try:
        return _entity_model_registry.get(entity_type)
    except KeyError:
        raise KeyError(
            f"No model registered for entity type '{entity_type}'. "
            f"Registered types: {_entity_model_registry.keys()}"
        ) from None


def resolve_entity(entity_id: UUID) -> BaseModel:
    """Resolve an entity_id to its typed model instance (req-grid-entity-resolve-2).

    **Below the service boundary — not a public read API.** This is the
    UUID-keyed peer of ``Entity.resolve()``: model-layer machinery for callers
    that already sit under the gate (the ORM read backstop still applies to the
    fetch itself). Application code must use the capability-gated service read
    (``tap_grid.services.resolve_entity`` / ``get_node``), which additionally
    enforces ``grid.read``, coerces the id, and raises service exceptions.
    Deliberately absent from ``__all__`` so an import of this module does not
    offer it as a convenient way around that gate (2026-08 code-clone sweep,
    finding C8).

    Costs two DB queries: one to fetch the Entity (for its entity_type), one for
    the concrete domain object. If you already hold the Entity instance, call
    ``entity.resolve()`` directly and save the first.
    """
    from tap_grid.models import Entity

    entity: Entity = Entity.objects.get(pk=entity_id)
    return entity.resolve()


# ---------------------------------------------------------------------------
# Search runner registry — maps scoped keys to module search runner callables.
# Populated at AppConfig.ready() time by plugins that provide module runners.
# ---------------------------------------------------------------------------

search_runner_registry: ScopedRegistry[Callable[..., Any]] = ScopedRegistry(
    "search_runner",
    title="Search Runner Registry",
    description="Scoped registry of callable search runners keyed by runner ID.",
)


def register_search_runner(
    key: str,
    runner: Callable[..., Any],
    scope: str | None = None,
) -> None:
    """Register a search runner callable under a scoped key.

    Scope is auto-inferred from runner.__module__ if not provided.
    Duplicate registration of the same (scope, key) pair raises ImproperlyConfigured.
    """
    search_runner_registry.register(key, runner, scope=scope)


def get_search_runner(runner_key: str) -> Callable[..., Any]:
    """Return the runner callable for a fully-qualified 'scope:key' runner_key.

    Raises SearchRunnerNotFoundError with a descriptive message if not found.
    """
    from tap_grid.exceptions import SearchRunnerNotFoundError

    try:
        return search_runner_registry.get(runner_key)
    except KeyError:
        raise SearchRunnerNotFoundError(
            f"No search runner registered for key '{runner_key}'. "
            f"Registered runners: {search_runner_registry.keys()}"
        ) from None


__all__ = [
    # Re-exported generic machinery (canonical home: tap.registry).
    "Registry",
    "ScopedRegistry",
    "meta_registry",
    # Grid-specific.
    "register_entity_type",
    "list_entity_types",
    "get_model_class",
    "search_runner_registry",
    "register_search_runner",
    "get_search_runner",
]
