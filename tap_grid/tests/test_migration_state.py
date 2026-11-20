"""StateApps keeps its own swappable-settings cache (tap_grid/migration_state.py, tap#1251).

Three kinds of test:

- guards: fail loudly when Django renames or reshapes what the patch relies on, so an upgrade can
  neither silently disable the speedup nor leave it patching something that no longer exists;
- correctness: the swappable answer is right after re-renders, for the global registry and for a
  StateApps, including when the swappable model itself is (re)registered;
- equivalence: migration state rendered and reloaded with and without the patch deconstructs every
  FK to the user model identically.

All in memory: no database is touched.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from django.apps import apps as global_apps
from django.apps.registry import Apps
from django.conf import settings
from django.db.migrations.state import ModelState, ProjectState, StateApps
from django.db.models.fields.related import RelatedField
from django.test import override_settings

from tap_grid.migration_state import PerRegistrySwappableCache, install_state_apps_swappable_cache

USER_LABEL = settings.AUTH_USER_MODEL
USER_APP, USER_MODEL = USER_LABEL.lower().split(".")
#: The model that declares ``Meta.swappable = "AUTH_USER_MODEL"`` and is swapped out for the user model.
SWAPPABLE_DECLARER: str = "auth.User"


# --- guards: the Django shape the patch depends on -------------------------------------------------


def test_django_still_shares_one_functools_cache_across_registries() -> None:
    """The patch reads the uncached function from ``__wrapped__`` and relies on ``cache_clear``."""
    shared = Apps.__dict__.get("get_swappable_settings_name")
    assert shared is not None, "Django renamed or removed Apps.get_swappable_settings_name (tap#1251)"
    assert callable(getattr(shared, "__wrapped__", None)), "Apps.get_swappable_settings_name is not a functools cache"
    assert callable(getattr(shared, "cache_clear", None)), "Apps.get_swappable_settings_name has no cache_clear"


def test_django_clear_cache_still_clears_through_the_instance() -> None:
    """``Apps.clear_cache`` must clear via ``self.``, so a StateApps reaches its own cache, not the shared one."""
    source = inspect.getsource(Apps.clear_cache)
    assert "self.get_swappable_settings_name.cache_clear()" in source, (
        "Apps.clear_cache no longer clears the swappable cache through self; re-check tap_grid/migration_state.py"
    )


def test_django_state_apps_still_clears_cache_on_every_register() -> None:
    """The cost the patch removes: StateApps.register_model clearing caches per rendered model."""
    assert "register_model" in StateApps.__dict__, "StateApps.register_model moved; re-check tap#1251"
    assert "self.clear_cache()" in inspect.getsource(StateApps.register_model)


def test_django_fk_deconstruct_still_asks_the_global_registry() -> None:
    """``swappable_setting`` reads the global ``apps``; that is why keeping its cache is the win."""
    source = inspect.getsource(vars(RelatedField)["swappable_setting"].fget)
    assert "apps.get_swappable_settings_name(" in source


def test_patch_is_installed_on_state_apps_only() -> None:
    assert install_state_apps_swappable_cache() is True
    assert isinstance(StateApps.__dict__["get_swappable_settings_name"], PerRegistrySwappableCache)
    assert not isinstance(Apps.__dict__["get_swappable_settings_name"], PerRegistrySwappableCache)
    assert not isinstance(type(global_apps).__dict__.get("get_swappable_settings_name"), PerRegistrySwappableCache)


def test_rendering_migration_state_keeps_the_global_cache() -> None:
    """Behavioural guard: a StateApps re-render must not empty the global registry's cache."""
    shared = Apps.__dict__["get_swappable_settings_name"]
    assert global_apps.get_swappable_settings_name(USER_LABEL) == "AUTH_USER_MODEL"
    before = shared.cache_info()
    state = ProjectState.from_apps(global_apps)
    state.apps  # noqa: B018  full render: one register_model per model
    state.reload_model(USER_APP, USER_MODEL, delay=True)
    assert shared.cache_info().currsize >= before.currsize, "a StateApps render emptied the shared cache"
    misses = shared.cache_info().misses
    assert global_apps.get_swappable_settings_name(USER_LABEL) == "AUTH_USER_MODEL"
    assert shared.cache_info().misses == misses, "the global answer was recomputed after a StateApps render"


def test_global_registry_still_clears_its_own_cache() -> None:
    """The global registry keeps Django's stock behaviour."""
    shared = Apps.__dict__["get_swappable_settings_name"]
    global_apps.get_swappable_settings_name(USER_LABEL)
    assert shared.cache_info().currsize > 0
    global_apps.clear_cache()
    assert shared.cache_info().currsize == 0
    assert global_apps.get_swappable_settings_name(USER_LABEL) == "AUTH_USER_MODEL"


# --- correctness -----------------------------------------------------------------------------------


def test_swappable_answer_is_right_after_re_renders() -> None:
    state = ProjectState.from_apps(global_apps)
    state_apps = state.apps
    assert state_apps.get_swappable_settings_name(USER_LABEL) == "AUTH_USER_MODEL"
    assert state_apps.get_swappable_settings_name("tap_grid.entity") is None
    for _ in range(2):
        state.reload_model(USER_APP, USER_MODEL, delay=True)
        state.reload_model("tap_grid", "entity", delay=True)
    assert state.apps.get_swappable_settings_name(USER_LABEL) == "AUTH_USER_MODEL"
    assert state.apps.get_swappable_settings_name(USER_LABEL.lower()) == "AUTH_USER_MODEL"
    assert state.apps.get_swappable_settings_name("tap_grid.entity") is None
    assert global_apps.get_swappable_settings_name(USER_LABEL) == "AUTH_USER_MODEL"


def test_state_apps_cache_is_per_registry_and_invalidated_by_its_own_registration() -> None:
    """A StateApps that gains the swappable model must stop answering None for it.

    The answer for AUTH_USER_MODEL comes from the model that declares ``Meta.swappable`` and is swapped
    out for it (``auth.User``), not from the user model itself, so that is the model registered here.
    """
    declarer = ModelState.from_model(global_apps.get_model(SWAPPABLE_DECLARER), exclude_rels=True)
    assert declarer.options.get("swappable") == "AUTH_USER_MODEL"
    empty = StateApps([], {})
    assert empty.get_swappable_settings_name(USER_LABEL) is None  # cached as None in this registry
    other = StateApps([], {})
    other.render_multiple([declarer.clone()])
    assert other.get_swappable_settings_name(USER_LABEL) == "AUTH_USER_MODEL"
    assert empty.get_swappable_settings_name(USER_LABEL) is None  # the other registry's answer is its own
    declarer.clone().render(empty)  # register_model -> clear_cache -> this registry's cache only
    assert empty.get_swappable_settings_name(USER_LABEL) == "AUTH_USER_MODEL"
    empty.unregister_model("auth", "user")
    empty.clear_cache()
    assert empty.get_swappable_settings_name(USER_LABEL) is None


def test_a_settings_change_reaches_a_state_apps_cache_as_it_does_in_stock_django(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A StateApps answer cached before ``override_settings(AUTH_USER_MODEL=...)`` is not reused after it.

    Stock Django gets this from the shared cache: the ``AUTH_USER_MODEL`` receiver clears the global
    registry, which empties every registry. Here a ``setting_changed`` generation does it (PR review on
    unified-systems-com/tap#1253). Checked against stock by removing the patch and asking again.
    """
    declarer = ModelState.from_model(global_apps.get_model(SWAPPABLE_DECLARER), exclude_rels=True)

    def answers() -> tuple[str | None, str | None]:
        registry = StateApps([], {})
        registry.render_multiple([declarer.clone()])
        before = registry.get_swappable_settings_name(USER_LABEL)
        with override_settings(AUTH_USER_MODEL=SWAPPABLE_DECLARER):
            after = registry.get_swappable_settings_name(USER_LABEL)
        return before, after

    patched = answers()
    assert patched == ("AUTH_USER_MODEL", None), "a StateApps answered from settings that had changed"
    monkeypatch.delattr(StateApps, "get_swappable_settings_name")
    assert answers() == patched


# --- equivalence -----------------------------------------------------------------------------------


def _user_fk_deconstructions(state: ProjectState) -> dict[tuple[str, str], tuple[Any, ...]]:
    """Every relation to the user model, deconstructed, keyed by (model label, field name)."""
    found: dict[tuple[str, str], tuple[Any, ...]] = {}
    for model in state.apps.get_models(include_auto_created=True):
        for field in model._meta.local_fields + list(model._meta.local_many_to_many):
            if not isinstance(field, RelatedField):
                continue
            if field.remote_field.model._meta.label_lower != USER_LABEL.lower():
                continue
            name, path, args, kwargs = field.deconstruct()
            to = kwargs.get("to")
            found[(model._meta.label_lower, name)] = (
                path,
                tuple(args),
                tuple(sorted((k, repr(v)) for k, v in kwargs.items())),
                getattr(to, "setting_name", None),
            )
    return found


def _render_and_reload() -> dict[tuple[str, str], tuple[Any, ...]]:
    state = ProjectState.from_apps(global_apps)
    state.apps  # noqa: B018
    state.reload_model(USER_APP, USER_MODEL, delay=True)
    state.reload_model("tap_grid", "entity", delay=True)
    return _user_fk_deconstructions(state)


def test_user_fk_deconstruction_is_identical_with_and_without_the_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    patched = _render_and_reload()
    monkeypatch.delattr(StateApps, "get_swappable_settings_name")
    assert "get_swappable_settings_name" not in StateApps.__dict__
    stock = _render_and_reload()
    assert patched, "no relation to the user model was found; the equivalence test proves nothing"
    assert patched == stock
    swappable = {key: value for key, value in patched.items() if value[3] == "AUTH_USER_MODEL"}
    assert swappable, "no FK to the user model deconstructed to settings.AUTH_USER_MODEL"
