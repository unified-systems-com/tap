"""Migration-state speedup: a migration state registry keeps its own swappable-settings cache.

What Django does (read in 6.0.8; the shared clear arrived in 4.2):

- ``Apps.get_swappable_settings_name`` is decorated with ``@functools.cache`` on the class, so every
  ``Apps`` instance, the global registry and every migration ``StateApps``, shares one cache.
- ``Apps.clear_cache`` empties that shared cache (``self.get_swappable_settings_name.cache_clear()``,
  added for Django ticket #34687 in 4.2).
- ``StateApps.register_model`` calls ``clear_cache`` for every model it renders, so each partial reload
  of migration state empties the shared cache once per re-rendered model.
- The only caller, ``RelatedField.swappable_setting`` (``deconstruct()`` of every FK), asks the GLOBAL
  registry (``django.apps.apps``). With the cache gone, each call rescans every installed model.

So the migration state was throwing away an answer it never uses and cannot change: the global
registry's answer depends on settings and on the global registry's models, and a ``StateApps``
rendering a model alters neither. With about 2,000 installed models, that rescan was 93 of the 200 s
of ``grid_fixtures.0002`` (unified-systems-com/tap#1251).

The patch: ``StateApps`` gets its own per-registry cache for ``get_swappable_settings_name``. Django's
``Apps.clear_cache`` still runs unchanged on a ``StateApps``, and its
``self.get_swappable_settings_name.cache_clear()`` now clears that registry's own cache only, which is
the one its own models could invalidate. The global registry and any other ``Apps`` keep the stock
shared cache and still clear it themselves when they change. Nothing is patched on ``Apps``.

The answer also reads settings (``Options.swapped`` reads ``AUTH_USER_MODEL`` at call time). In stock
Django a settings change reaches every registry because the cache is shared: the ``setting_changed``
receiver for ``AUTH_USER_MODEL`` clears the global registry, which empties it for all. Here every
``setting_changed`` bumps a generation instead, and a per-registry cache filled under an older
generation is dropped on its next read, so no registry answers from settings that have changed.
Settings change only under ``override_settings``, so this costs nothing in a migrate.

This is worth sending upstream. Django ticket #37214 ("Performance regression with end to end
migrations on v5.x", open) reports migrations doubling in time after 4.2 and suspects the
swappable-settings caching change from #34687; the mechanism above is a likely cause (not confirmed
on that ticket). Search https://code.djangoproject.com before filing anything new. Remove this
module once Django gives each registry its own cache or stops ``StateApps`` clearing the shared one.

``tap_grid/tests/test_migration_state.py`` fails loudly if Django renames or reshapes what this
relies on, so an upgrade cannot silently disable or break it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from django.apps.registry import Apps
from django.core.signals import setting_changed
from django.db.migrations.state import StateApps

logger = logging.getLogger(__name__)

#: Where a StateApps keeps its own answers, in its instance ``__dict__``.
_CACHE_ATTR = "_tap_swappable_settings_cache"

#: The Django method this module overrides on StateApps (and reads from Apps).
_PATCHED_NAME = "get_swappable_settings_name"

#: Bumped on every ``setting_changed``; a per-registry cache from an older generation is stale.
_settings_generation = 0


def _settings_changed(**_kwargs: object) -> None:
    global _settings_generation
    _settings_generation += 1


class _BoundSwappableCache:
    """``get_swappable_settings_name`` bound to one registry, with a ``cache_clear`` for that registry only.

    It mirrors the call shape Django's ``Apps`` uses (``self.get_swappable_settings_name(to_string)``
    and ``self.get_swappable_settings_name.cache_clear()``), so ``Apps.clear_cache`` runs unmodified.
    """

    __slots__ = ("_registry", "_compute")

    def __init__(self, registry: Apps, compute: Callable[[Apps, str], str | None]) -> None:
        self._registry = registry
        self._compute = compute

    def __call__(self, to_string: str) -> str | None:
        cached: tuple[int, dict[str, str | None]] | None = self._registry.__dict__.get(_CACHE_ATTR)
        generation, cache = cached if cached is not None else (None, None)
        if generation != _settings_generation or cache is None:
            cache = {}
            self._registry.__dict__[_CACHE_ATTR] = (_settings_generation, cache)
        if to_string not in cache:
            cache[to_string] = self._compute(self._registry, to_string)
        return cache[to_string]

    def cache_clear(self) -> None:
        self._registry.__dict__.pop(_CACHE_ATTR, None)


class PerRegistrySwappableCache:
    """Descriptor installed as ``StateApps.get_swappable_settings_name``: one cache per registry."""

    def __init__(self, compute: Callable[[Apps, str], str | None]) -> None:
        self.compute = compute

    def __get__(self, registry: Apps | None, owner: type | None = None) -> Any:
        if registry is None:
            return self
        return _BoundSwappableCache(registry, self.compute)


def install_state_apps_swappable_cache() -> bool:
    """Give ``StateApps`` its own swappable-settings cache (tap#1251). Idempotent; True when in effect.

    If Django no longer has the shape this relies on, it changes nothing and logs a warning: a missing
    speedup must not stop a boot. The guard tests in ``test_migration_state.py`` fail on that state.
    """
    if isinstance(StateApps.__dict__.get(_PATCHED_NAME), PerRegistrySwappableCache):
        return True
    shared = Apps.__dict__.get(_PATCHED_NAME)
    compute = getattr(shared, "__wrapped__", None)
    if not callable(compute) or not callable(getattr(shared, "cache_clear", None)):
        logger.warning(
            "[0999] Apps.get_swappable_settings_name is no longer a functools cache; the StateApps "
            "swappable-cache speedup (tap#1251) is not installed"
        )
        return False
    if _PATCHED_NAME in StateApps.__dict__:
        logger.warning(
            "[163c] StateApps already defines get_swappable_settings_name; the StateApps "
            "swappable-cache speedup (tap#1251) is not installed"
        )
        return False
    setting_changed.connect(_settings_changed, dispatch_uid="tap_grid.migration_state.settings_changed")
    setattr(StateApps, _PATCHED_NAME, PerRegistrySwappableCache(compute))
    return True
