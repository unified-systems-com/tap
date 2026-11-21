"""The shallow reload for ``manage.py migrate`` (req-boot-shallow-reload, tap#1275).

Most of these run operations against small migration states built here, so each fallback and each
repoint is seen on its own. One replays the installed migration graph of every app that is not a
plugin twice in memory, once per road, and requires the same schema-editor SQL migration by
migration and the same rendered models; the nightly parity job (``tap.schema_parity``) does the
same for real databases with the plugins in. The last pins the Django code the reload rests on.
"""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Iterator
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.conf import settings
from django.core.management import get_commands, load_command_class
from django.core.management.commands.migrate import Command as DjangoMigrateCommand
from django.db import connection, migrations, models
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.migration import Migration
from django.db.migrations.operations.special import RunPython
from django.db.migrations.state import ModelState, ProjectState, StateApps
from django.db.models.fields.related import ForeignKey, ForeignObject, ManyToManyField, RelatedField
from django.db.models.options import Options

from tap_boot import shallow_reload
from tap_boot.management.commands.migrate import Command as TapMigrateCommand

APP = "shallow_case"


def _pk() -> models.BigAutoField[Any, Any]:
    return models.BigAutoField(primary_key=True)


def _states() -> list[ModelState]:
    """A hub, two models that point at it, one that points at those, and a proxy."""
    return [
        ModelState("tap_grid", "Entity", [("id", _pk())]),
        ModelState(
            APP,
            "Node",
            [
                ("id", _pk()),
                ("entity", models.OneToOneField("tap_grid.Entity", models.CASCADE)),
                ("code", models.CharField(max_length=10, unique=True)),
            ],
        ),
        ModelState(APP, "Other", [("id", _pk()), ("entity", models.OneToOneField("tap_grid.Entity", models.CASCADE))]),
        ModelState(
            APP,
            "Link",
            [
                ("id", _pk()),
                ("node", models.ForeignKey(f"{APP}.Node", models.CASCADE)),
                ("by_code", models.ForeignKey(f"{APP}.Node", models.CASCADE, to_field="code", related_name="+")),
                ("nodes", models.ManyToManyField(f"{APP}.Node", related_name="linked")),
            ],
        ),
        ModelState(APP, "NodeProxy", [], options={"proxy": True}, bases=(f"{APP}.node",)),
    ]


@pytest.fixture
def state() -> Iterator[ProjectState]:
    project = ProjectState()
    for model_state in _states():
        project.add_model(model_state)
    project.apps  # noqa: B018 — render, as the executor does before the first migration
    project.__dict__[shallow_reload._MARK] = True
    with shallow_reload.installed() as on:
        assert on
        yield project


def _model(state: ProjectState, name: str) -> type[models.Model]:
    return state.apps.get_model(APP if "." not in name else name.split(".")[0], name.split(".")[-1])


def _classes(state: ProjectState) -> dict[str, type[models.Model]]:
    return {m._meta.label_lower: m for m in state.apps.get_models(include_auto_created=True)}


def _dangling(state: ProjectState) -> list[str]:
    """Every rendered relation that points at a class the registry no longer holds."""
    registered = set(_classes(state).values())
    dangling = []
    for model in registered:
        fields: list[Any] = [*model._meta.local_fields, *model._meta.local_many_to_many]
        for field in fields:
            if field.is_relation and field.remote_field.model not in registered:
                dangling.append(f"{model._meta.label}.{field.name}")
    return dangling


@pytest.mark.spec("req-boot-shallow-reload-1")
def test_an_operation_rerenders_only_its_model_and_repoints_the_rest(state: ProjectState) -> None:
    before = _classes(state)
    migrations.AddField("Node", "note", models.TextField(default="")).state_forwards(APP, state)
    after = _classes(state)

    changed = {label for label in before if after.get(label) is not before[label]}
    assert changed == {f"{APP}.node", f"{APP}.nodeproxy"}  # the touched model and what inherits from it
    node = after[f"{APP}.node"]
    link = after[f"{APP}.link"]
    assert link._meta.get_field("node").related_model is node
    assert link._meta.get_field("by_code").related_model is node
    assert link._meta.get_field("nodes").related_model is node
    nodes: Any = link._meta.get_field("nodes")
    through = nodes.remote_field.through
    assert through._meta.get_field("node").related_model is node
    assert after[f"{APP}.nodeproxy"].__bases__ == (node,)
    reverse = node._meta.get_fields(include_hidden=True)
    assert {rel.related_model for rel in reverse if rel.auto_created and not rel.concrete} == {link, through}
    assert _dangling(state) == []
    assert state.is_delayed


@pytest.mark.spec("req-boot-shallow-reload-1")
def test_a_new_model_is_rendered_alone(state: ProjectState) -> None:
    before = _classes(state)
    migrations.CreateModel(
        "Late", [("id", _pk()), ("entity", models.OneToOneField("tap_grid.Entity", models.CASCADE))]
    ).state_forwards(APP, state)
    after = _classes(state)

    assert {label for label in after if after[label] is not before.get(label)} == {f"{APP}.late"}
    assert after[f"{APP}.late"]._meta.get_field("entity").related_model is after["tap_grid.entity"]
    assert _dangling(state) == []


_FALLBACKS = {
    "the hub itself": ("tap_grid", migrations.AddField("Entity", "note", models.TextField(default=""))),
    "a primary key": (APP, migrations.AlterField("Node", "id", models.AutoField(primary_key=True))),
    "a to_field target": (APP, migrations.AlterField("Node", "code", models.CharField(max_length=20, unique=True))),
    "the table": (APP, migrations.AlterModelTable("Node", "renamed_node")),
}


@pytest.mark.spec("req-boot-shallow-reload-2")
@pytest.mark.parametrize("case", sorted(_FALLBACKS))
def test_djangos_reload_runs_where_the_narrow_case_fails(state: ProjectState, case: str) -> None:
    app_label, operation = _FALLBACKS[case]
    entity = _classes(state)["tap_grid.entity"]
    shallow_reload.stats.reset()
    operation.state_forwards(app_label, state)

    assert shallow_reload.stats.fallback >= 1
    assert shallow_reload.stats.shallow == 0
    assert _classes(state)["tap_grid.entity"] is not entity  # Django re-rendered the hub's neighbourhood


@pytest.mark.spec("req-boot-shallow-reload-2")
def test_a_model_already_referred_to_is_djangos_to_render(state: ProjectState) -> None:
    later = models.ForeignKey(f"{APP}.Later", models.CASCADE, null=True)
    migrations.AddField("Other", "later", later).state_forwards(APP, state)
    shallow_reload.stats.reset()
    migrations.CreateModel("Later", [("id", _pk())]).state_forwards(APP, state)
    after = _classes(state)

    assert (shallow_reload.stats.shallow, shallow_reload.stats.fallback) == (0, 1)
    assert after[f"{APP}.other"]._meta.get_field("later").related_model is after[f"{APP}.later"]


@pytest.mark.spec("req-boot-shallow-reload-2")
def test_a_rename_leaves_its_referrers_to_djangos_reload(state: ProjectState) -> None:
    link = _classes(state)[f"{APP}.link"]
    migrations.RenameModel("Node", "Knot").state_forwards(APP, state)
    after = _classes(state)

    assert after[f"{APP}.link"] is not link
    assert after[f"{APP}.link"]._meta.get_field("node").related_model is after[f"{APP}.knot"]
    assert f"{APP}.node" not in after


@pytest.mark.spec("req-boot-shallow-reload-2")
def test_a_field_unrelated_to_what_others_see_stays_shallow(state: ProjectState) -> None:
    shallow_reload.stats.reset()
    migrations.AlterField("Other", "entity", models.OneToOneField("tap_grid.Entity", models.PROTECT)).state_forwards(
        APP, state
    )
    migrations.AddIndex("Node", models.Index(fields=["code"], name="node_code_idx")).state_forwards(APP, state)
    assert (shallow_reload.stats.shallow, shallow_reload.stats.fallback) == (2, 0)


@pytest.mark.spec("req-boot-shallow-reload-3")
def test_a_clone_keeps_djangos_reload(state: ProjectState) -> None:
    clone = state.clone()
    entity = _classes(clone)["tap_grid.entity"]
    shallow_reload.stats.reset()
    migrations.AddField("Node", "note", models.TextField(default="")).state_forwards(APP, clone)

    assert shallow_reload.stats.shallow == shallow_reload.stats.fallback == 0
    assert _classes(clone)["tap_grid.entity"] is not entity


@pytest.mark.spec("req-boot-shallow-reload-3")
def test_the_off_switch_and_the_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    command = load_command_class(get_commands()["migrate"], "migrate")
    assert isinstance(command, TapMigrateCommand) and isinstance(command, DjangoMigrateCommand)
    assert ProjectState.reload_model is shallow_reload.STOCK_RELOAD_MODEL  # nothing outside the command
    assert MigrationExecutor._migrate_all_forwards is shallow_reload.STOCK_MIGRATE_ALL_FORWARDS  # type: ignore[attr-defined]
    monkeypatch.setenv(shallow_reload.ENV, "0")
    with shallow_reload.installed() as on:
        assert not on
        assert ProjectState.reload_model is shallow_reload.STOCK_RELOAD_MODEL
    monkeypatch.setenv(shallow_reload.ENV, "1")
    with shallow_reload.installed() as on:
        assert on
        assert ProjectState.reload_model is not shallow_reload.STOCK_RELOAD_MODEL
    assert ProjectState.reload_model is shallow_reload.STOCK_RELOAD_MODEL


@pytest.mark.spec("req-boot-shallow-reload-3")
def test_the_forward_plan_marks_its_state_and_renders_borrowed_classes_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[bool, bool]] = []

    def stock(executor: Any, state: ProjectState, *args: Any, **kwargs: Any) -> ProjectState:
        seen.append((state.__dict__.get(shallow_reload._MARK, False), "apps" in state.__dict__))
        return state

    monkeypatch.setattr(shallow_reload, "STOCK_MIGRATE_ALL_FORWARDS", stock)
    pre_migrate = ProjectState()
    for model_state in _states():
        pre_migrate.add_model(model_state)
    pre_migrate.apps  # noqa: B018 — the pre_migrate render the migrate command makes
    borrowed = pre_migrate.clone()  # its classes belong to pre_migrate's registry, as on an upgrade
    advanced = shallow_reload._migrate_all_forwards(None, borrowed)  # type: ignore[arg-type]
    own_apps = advanced.apps  # the executor's fresh render: every class its own
    shallow_reload._migrate_all_forwards(None, advanced)  # type: ignore[arg-type]

    assert seen == [(True, False), (True, True)]  # marked both times; only the borrowed render dropped
    assert advanced.__dict__["apps"] is own_apps
    assert shallow_reload._MARK not in advanced.__dict__  # unmarked once the plan returns


def _core_plan(loader: MigrationLoader) -> list[Migration]:
    """The forward plan of every app that is not a plugin, as a migrate from zero orders it."""
    plugin_labels = {
        config.label
        for config in django_apps.get_app_configs()
        if f"{type(config).__module__}.{type(config).__name__}" in settings.TAP_PLUGINS_APPS
    }
    plan: list[Migration] = []
    seen: set[tuple[str, str]] = set()
    for leaf in sorted(loader.graph.leaf_nodes()):
        if leaf[0] in plugin_labels:
            continue
        for key in loader.graph.forwards_plan(leaf):
            if key not in seen:
                seen.add(key)
                plan.append(loader.graph.nodes[key])
    return plan


def _fingerprint(state: ProjectState) -> dict[str, Any]:
    shape = {}
    for model in state.apps.get_models(include_auto_created=True):
        fields = []
        for field in [*model._meta.local_fields, *model._meta.local_many_to_many]:
            target = field.related_model._meta.label_lower if field.is_relation and field.related_model else None
            fields.append((field.name, field.column, type(field).__name__, target))
        shape[model._meta.label_lower] = (model._meta.db_table, sorted(fields, key=lambda f: f[0]))
    return shape


def _replay(shallow: bool) -> tuple[list[tuple[str, list[str]]], dict[str, Any]]:
    loader = MigrationLoader(None, ignore_no_migrations=True)
    state = ProjectState(real_apps=loader.unmigrated_apps)
    state.apps  # noqa: B018 — the executor's first render
    if shallow:
        state.__dict__[shallow_reload._MARK] = True
    sql = []
    for migration in _core_plan(loader):
        with connection.schema_editor(collect_sql=True, atomic=migration.atomic) as editor:
            state = migration.apply(state, editor, collect_sql=True)
        sql.append((f"{migration.app_label}.{migration.name}", list(editor.collected_sql)))
    # What the schema editor saw: the registry as the last operation left it, before any fresh render.
    return sql, _fingerprint(state)


@pytest.mark.django_db
@pytest.mark.spec("req-boot-shallow-reload-4")
def test_core_migrations_give_the_same_sql_and_models_on_both_roads(monkeypatch: pytest.MonkeyPatch) -> None:
    # Django's own delayed reloads leave relations pointing at replaced classes until the next
    # full render; the shallow road must not add to them.
    dangling: list[str] = []
    real = shallow_reload.shallow_reload

    def watched(state: ProjectState, chosen: shallow_reload.Plan) -> None:
        before = set(_dangling(state))
        real(state, chosen)
        dangling.extend(sorted(set(_dangling(state)) - before))

    monkeypatch.setattr(shallow_reload, "shallow_reload", watched)
    stock_sql, stock_models = _replay(shallow=False)
    with shallow_reload.installed() as on:
        assert on
        shallow_sql, shallow_models = _replay(shallow=True)
        took_shallow = shallow_reload.stats.shallow

    assert took_shallow > 0  # the replay exercised the shallow road, not only its fallbacks
    assert [name for name, _ in shallow_sql] == [name for name, _ in stock_sql]
    for (name, stock), (_, shallow) in zip(stock_sql, shallow_sql, strict=True):
        assert shallow == stock, name  # in order: the shallow road may not reorder what the editor runs
    assert shallow_models == stock_models
    assert dangling == []


# The Django code the shallow reload replaces, wraps, mirrors or relies on, by source digest. A
# Django upgrade that changes one fails here until someone has re-read it against
# tap_boot/shallow_reload.py and re-pinned it; the replay above then says whether it still holds.
_DJANGO_SOURCES = {
    ProjectState.reload_model: "c381c7527cc0880f",  # replaced; the fallback calls it
    ProjectState._find_reload_model: "fff55cca5b1d1d5d",  # type: ignore[attr-defined]  # the fan-out the shallow road skips
    ProjectState._reload: "849340d844b1841d",  # type: ignore[attr-defined]  # mirrored by shallow_reload.shallow_reload
    ProjectState.clone: "dd177ed489f74166",  # must not carry the state's __dict__ (the mark)
    ProjectState.clear_delayed_apps_cache: "7f678f50584fa957",  # the delayed contract
    MigrationExecutor._migrate_all_forwards: "e13cbd9b4817571c",  # type: ignore[attr-defined]  # wrapped; renders a state with no apps
    Migration.apply: "9549a1ccbbdff05c",  # one clone per operation as from_state
    RunPython.database_forwards: "eef9fc2331d506b2",  # full render for data migrations
    StateApps.render_multiple: "84ce3559ac2939dd",
    StateApps.bulk_update: "3388642d7d31d742",  # clears every model's caches after a render
    StateApps.register_model: "31fbfa75bf784dcf",
    StateApps.unregister_model: "cb0c9c45afcb1dc1",
    RelatedField.do_related_class: "567f3992b4aba9d5",  # the repoint
    RelatedField.set_attributes_from_rel: "92d1db884cdf3e14",
    ForeignObject.contribute_to_related_class: "9a529f7f8093e8b7",
    ForeignKey.contribute_to_related_class: "67cdd1b5f14daa65",
    ManyToManyField.contribute_to_related_class: "fe0d1c5de39aa577",
    Options._populate_directed_relation_graph: "d4922db0d25e2abd",  # type: ignore[attr-defined]  # reverse relations found by label
    inspect.unwrap(DjangoMigrateCommand.handle): "6702070f29ab781e",  # the command the override wraps
}


@pytest.mark.spec("req-boot-shallow-reload-6")
@pytest.mark.parametrize("function", list(_DJANGO_SOURCES), ids=lambda f: f.__qualname__)
def test_the_django_code_it_rests_on_is_unchanged(function: Any) -> None:
    digest = hashlib.sha256(inspect.getsource(function).encode()).hexdigest()[:16]
    assert digest == _DJANGO_SOURCES[function], (
        f"{function.__module__}.{function.__qualname__} changed in this Django: re-read it against "
        "tap_boot/shallow_reload.py, then re-pin its digest here"
    )
