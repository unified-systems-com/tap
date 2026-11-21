"""A shallow reload for ``manage.py migrate``: re-render only the model an operation touched (tap#1275).

Every migration operation that changes a model's state calls ``ProjectState.reload_model``, and
Django (``django/db/migrations/state.py``, ``_find_reload_model``) then re-renders the model, every
model related to it, AND every model related to each of its foreign key targets, even with
``delay=True``. Every grid model has a one-to-one to ``tap_grid.Entity`` and every history model a
foreign key to ``Entity`` and to the user model, so one ``AddField`` on any grid model re-renders
about 2,000 models once ``aws_core`` is installed: 25 to 35 s per plugin migration (tap#1251).
Neither hub changes in a plugin migration.

This re-renders the touched model and its subclasses only. The models that point AT the touched
model keep their classes and have that relation repointed at the new class, by the same Django
code a fresh render runs (``Field.do_related_class``). Whenever the narrow case does not hold the
reload is Django's own, unchanged:

* the touched model, or a model that inherits from it, is ``tap_grid.Entity`` or the user model;
* what a referring model sees of it changed: its table, its bases, ``managed``/``proxy``, its
  primary key, or a field another model's ``to_field`` names (so an added, removed, altered or
  renamed primary key or referenced field, an ``AlterModelTable``);
* the model is not rendered yet but a model state already refers to it (a model created earlier
  in the same migration that points at it);
* a referring field is of a type whose relation wiring is not Django's own.

A ``RenameModel`` needs no rule of its own: ``ProjectState.rename_model`` re-renders the renamed
model's referrers with Django's reload directly (``reload_models``, which this does not replace),
and only its last step, the reload of the new name, comes here.

Why repointing is enough in the narrow case: a referring model's columns and constraints are
derived from the target's table and the target field, and the fallbacks above are exactly the
changes to those. Reverse relations are read through the app registry by label (``Options``'
relation tree), so they follow the new class once the registry's caches are cleared, which every
render here does. What is NOT the same as stock is the identity of classes Django would have
replaced: a model this road leaves alone is the same object in the state before and after the
operation. Django's schema editor reads a model's reverse relations only when that model's primary
key, a referenced field or its table changes (``_alter_field``, ``alter_db_table``), and those are
the fallbacks, where Django's own reload runs and takes its own snapshot.

Scope. Active only while ``manage.py migrate`` runs (``tap_boot/management/commands/migrate.py``),
and inside it only for the forward plan (``MigrationExecutor._migrate_all_forwards``) and only on
the one state that plan advances: every clone of it (each operation's ``from_state``) and every
other state, ``sqlmigrate``'s and a backwards plan's among them, keeps Django's reload. The state
is marked delayed, so ``RunPython`` and ``post_migrate`` get a full fresh render, as they do after
Django's own delayed reloads. Before the forward plan the state is rendered fresh unless every
class in it already belongs to its registry (an upgrade starts from classes rendered for the
``pre_migrate`` signal, whose reverse relations would be read from that frozen registry).

Off switch: ``TAP_MIGRATE_SHALLOW_RELOAD=0`` (or ``false``/``off``/``no``) restores Django's reload.

Guards: ``tap/schema_parity.py`` replays the migrations both ways nightly and fails on any
difference in schema, rows or recorded migrations; ``tap_boot/tests/test_shallow_reload.py``
replays every installed migration both ways in memory and requires the same schema-editor SQL and
the same rendered models, and fails when the Django code this rests on changes.

Prior art, read and not depended on: the patch in Django Forum thread 29038 (reload only the
touched model) and django-fastmig 0.1.1 (BSD-3), which this follows in repointing through
``do_related_class`` and which it narrows: no relation graph, no "strong" reload, one Django
method replaced instead of nine. Upstream, Django #29898 would make this unnecessary.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.state import ProjectState, StateApps
from django.db.migrations.utils import get_references
from django.utils.functional import cached_property as django_cached_property

logger = logging.getLogger(__name__)

ENV = "TAP_MIGRATE_SHALLOW_RELOAD"
_OFF = {"0", "false", "off", "no"}

# The key on a ProjectState's __dict__ that puts it on the shallow road. A clone does not carry it
# (ProjectState.clone builds a new state), which is what keeps every from_state on Django's road.
_MARK = "_tap_shallow_reload"

# The code the patches replace, captured at import, before anything here can have replaced it.
STOCK_RELOAD_MODEL = ProjectState.reload_model
STOCK_MIGRATE_ALL_FORWARDS = MigrationExecutor._migrate_all_forwards  # type: ignore[attr-defined]

ModelKey = tuple[str, str]


@dataclass
class Stats:
    """What one migrate did, for its closing log line and for the tests."""

    shallow: int = 0
    rendered: int = 0
    repointed: int = 0
    fallback: int = 0

    def reset(self) -> None:
        self.shallow = self.rendered = self.repointed = self.fallback = 0


stats = Stats()


def enabled() -> bool:
    """Whether the off switch is unset (the default) rather than set off."""
    return os.environ.get(ENV, "").strip().lower() not in _OFF


def _hubs() -> set[ModelKey]:
    user_app, user_model = settings.AUTH_USER_MODEL.split(".")
    return {("tap_grid", "entity"), (user_app, user_model.lower())}


def _key(model: type[models.Model]) -> ModelKey:
    return model._meta.app_label, model._meta.model_name  # type: ignore[return-value]


def _registered(apps: StateApps, key: ModelKey) -> type[models.Model] | None:
    return apps.all_models.get(key[0], {}).get(key[1])


def _base_labels(bases: Any, app_label: str) -> tuple[str, ...]:
    labels = []
    for base in bases:
        if isinstance(base, str):
            labels.append((base if "." in base else f"{app_label}.{base}").lower())
        elif isinstance(base, type) and issubclass(base, models.Model) and base is not models.Model:
            labels.append(base._meta.label_lower)
    return tuple(labels)


def _signature(field: models.Field[Any, Any]) -> tuple[Any, ...]:
    """A field as a referring model's column sees it, for rendered and state fields alike."""
    _, path, args, kwargs = field.deconstruct()
    # ``serialize`` is set False on a rendered primary key and says nothing about a column.
    kwargs = {k: (str(v).lower() if k == "to" else v) for k, v in kwargs.items() if k != "serialize"}
    return path, tuple(args), sorted(kwargs.items(), key=lambda item: item[0])


def _surface_unchanged(state: ProjectState, key: ModelKey, old: type[models.Model], referenced: set[str]) -> bool:
    """Whether a model that refers to ``key`` sees the same thing in the new state as in ``old``."""
    model_state = state.models[key]
    options = old._meta.original_attrs
    for option in ("db_table", "managed", "proxy"):
        if model_state.options.get(option) != options.get(option):
            return False
    if _base_labels(model_state.bases, key[0]) != _base_labels(old.__bases__, key[0]):
        return False
    pk = old._meta.pk
    if pk is None:
        return False
    for name in {pk.name, *referenced}:
        try:
            old_field = old._meta.get_field(name)
        except FieldDoesNotExist:
            return False
        if old_field.model is not old:
            continue  # inherited (a proxy's or a child's): the model that declares it is checked
        new_field = model_state.fields.get(name)
        if new_field is None or new_field.primary_key != (name == pk.name):
            return False
        if _signature(new_field) != _signature(old_field):  # type: ignore[arg-type]
            return False
    return True


def _standard_wiring(field: Any) -> bool:
    """Whether the field relates through Django's own code, so a repoint does what a render would."""
    if not isinstance(field, models.ForeignObject | models.ManyToManyField):
        return False
    return all(
        getattr(type(field), name).__module__.startswith("django.db.models.fields")
        for name in ("contribute_to_related_class", "do_related_class", "set_attributes_from_rel")
    )


def _forward_relations(model: type[models.Model]) -> list[Any]:
    opts = model._meta
    return [f for f in (*opts.local_fields, *opts.local_many_to_many) if f.is_relation and f.remote_field]


@dataclass
class Plan:
    render: set[ModelKey]
    referring: list[type[models.Model]]


def plan(state: ProjectState, key: ModelKey) -> Plan | None:
    """The models to re-render and the classes to repoint, or None when Django's reload must run."""
    apps = state.apps
    hubs = _hubs()
    if key in hubs:
        return None
    old = _registered(apps, key)
    if old is None:
        # Not rendered yet: a CreateModel, or the new name of a RenameModel. Rendering it alone is
        # right only when nothing refers to it yet; a model that does (the renamed model's
        # referrers, a model created earlier in the same migration that points at it) is Django's.
        if next(get_references(state, key), None) is not None:
            return None
        return Plan({key}, [])
    render = {key}
    queue = [old]
    while queue:
        for sub in queue.pop().__subclasses__():
            sub_key = _key(sub)
            if _registered(apps, sub_key) is sub and sub_key not in render:
                if sub_key in hubs:
                    return None
                render.add(sub_key)
                queue.append(sub)
    referring: dict[ModelKey, type[models.Model]] = {}
    for rendered_key in render:
        model = _registered(apps, rendered_key)
        assert model is not None  # every key in render is registered: the touched model and its subclasses
        referenced: set[str] = set()
        reverse: list[Any] = [
            rel
            for rel in model._meta.get_fields(include_parents=False, include_hidden=True)
            if rel.auto_created and not rel.concrete and rel.is_relation
        ]
        for rel in reverse:
            field = rel.field
            source = field.model
            owner = source._meta.auto_created
            if _key(source) in render or (isinstance(owner, type) and _key(owner) in render):
                continue  # re-rendered itself, or an auto-created through table a re-render replaces
            if not _standard_wiring(field):
                return None
            referenced.update(n for n in (getattr(rel, "field_name", None), *getattr(field, "to_fields", ())) if n)
            referring[_key(source)] = source
        if rendered_key in state.models and not _surface_unchanged(state, rendered_key, model, referenced):
            return None
    return Plan(render, list(referring.values()))


def _clear_cached(obj: Any) -> None:
    """Drop every cached_property value on ``obj`` (and a ManyToManyField's ``_m2m_*_cache``)."""
    for cls in type(obj).__mro__:
        for name, attr in vars(cls).items():
            if isinstance(attr, cached_property | django_cached_property):
                obj.__dict__.pop(name, None)
    for name in [n for n in obj.__dict__ if n.startswith("_m2m_") and n.endswith("_cache")]:
        del obj.__dict__[name]


def _repoint(apps: StateApps, model: type[models.Model], render: set[ModelKey]) -> int:
    """Point ``model``'s relations to a re-rendered model at its new class; returns how many."""
    count = 0
    for field in _forward_relations(model):
        rel = field.remote_field
        target = rel.model
        if isinstance(target, type) and _key(target) in render:
            current = _registered(apps, _key(target))
            if current is not None and current is not target:
                _clear_cached(field)
                _clear_cached(rel)
                rel.model = current
                field.do_related_class(current, model)
                count += 1
        through = getattr(rel, "through", None)
        if isinstance(through, type) and issubclass(through, models.Model) and through._meta.auto_created:
            # An auto-created through table holds a foreign key to each end; its class lives as
            # long as the class that declared the many-to-many, which is not being replaced.
            count += _repoint(apps, through, render)
    return count


def _auto_throughs(model: type[models.Model]) -> list[ModelKey]:
    throughs = []
    for field in model._meta.local_many_to_many:
        through = field.remote_field.through
        if isinstance(through, type) and through._meta.auto_created:
            throughs.append(_key(through))
    return throughs


def shallow_reload(state: ProjectState, chosen: Plan) -> None:
    """Re-render ``chosen.render``, then repoint ``chosen.referring`` at the new classes."""
    apps = state.apps
    state.is_delayed = True
    with apps.bulk_update():
        for key in chosen.render:
            old = _registered(apps, key)
            if old is not None:
                # Django drops these as part of the related set; a re-render creates new ones.
                for through_key in _auto_throughs(old):
                    apps.unregister_model(*through_key)
            apps.unregister_model(*key)
    to_render = [m for m in apps.real_models if (m.app_label, m.name_lower) in chosen.render]
    to_render += [state.models[key] for key in sorted(chosen.render) if key in state.models]
    apps.render_multiple(to_render)
    with apps.bulk_update():
        for model in chosen.referring:
            stats.repointed += _repoint(apps, model, chosen.render)
    stats.shallow += 1
    stats.rendered += len(to_render)


def _reload_model(self: ProjectState, app_label: str, model_name: str, delay: bool = False) -> None:
    """``ProjectState.reload_model`` while installed: shallow on a marked state when the plan allows, else Django's.

    TAP-IMPLEMENTS: req-boot-shallow-reload@6d92de3f32dd/d05ad83ddd1d (derivation) — the one place a
        migrate's reload chooses between the shallow road and Django's own.
    """
    if self.__dict__.get(_MARK) and "apps" in self.__dict__:
        chosen = plan(self, (app_label, model_name))
        if chosen is not None:
            shallow_reload(self, chosen)
            return
        stats.fallback += 1
    STOCK_RELOAD_MODEL(self, app_label, model_name, delay)


def _render_is_own(state: ProjectState) -> bool:
    apps = state.__dict__.get("apps")
    return apps is not None and all(m._meta.apps is apps for m in apps.get_models(include_auto_created=True))


def _migrate_all_forwards(self: MigrationExecutor, state: ProjectState, *args: Any, **kwargs: Any) -> ProjectState:
    if "apps" in state.__dict__ and not _render_is_own(state):
        del state.__dict__["apps"]  # the executor renders it fresh, as it does for an unrendered state
    state.__dict__[_MARK] = True
    try:
        advanced: ProjectState = STOCK_MIGRATE_ALL_FORWARDS(self, state, *args, **kwargs)
        return advanced
    finally:
        state.__dict__.pop(_MARK, None)


@contextlib.contextmanager
def installed() -> Iterator[bool]:
    """Put the forward plan of migrates run inside this block on the shallow road; yields whether it did."""
    if not enabled() or ProjectState.reload_model is _reload_model:
        yield False
        return
    stats.reset()
    ProjectState.reload_model = _reload_model  # type: ignore[method-assign]
    MigrationExecutor._migrate_all_forwards = _migrate_all_forwards  # type: ignore[attr-defined]
    try:
        yield True
    finally:
        ProjectState.reload_model = STOCK_RELOAD_MODEL  # type: ignore[method-assign]
        MigrationExecutor._migrate_all_forwards = STOCK_MIGRATE_ALL_FORWARDS  # type: ignore[attr-defined]
        if stats.shallow or stats.fallback:
            logger.info(
                "[29ac] shallow reload: %s shallow reload(s) rendering %s model(s), %s relation(s) repointed, "
                "%s Django reload(s) where the narrow case did not hold",
                stats.shallow,
                stats.rendered,
                stats.repointed,
                stats.fallback,
            )
