"""Per-model history opt-out (req-grid-history-optout in spec-grid-history.md).

The fixture type here is built in the test, not shipped by a plugin: a concrete ``BaseModel``
subclass declaring ``TRACK_HISTORY = False``, registered for the duration of one test, with its
table created through the schema editor inside the test's transaction (the rollback drops it).
Shipping it in the fixtures plugin would put a model with no history table into every test
database, which is the change under test, not a precondition of it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any, ClassVar

import pytest
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from django.db import connection, models
from django.db.migrations.state import ProjectState
from django.db.models.signals import post_delete, post_save
from tap.plugin_testing import requires_plugins
from tap_plugin.grid_fixtures.models import ConstrainedSource

from tap_grid.grid_tables import history_tables, read_guarded_tables
from tap_grid.grift.importer import grift_import
from tap_grid.grift.upgrade import build_header
from tap_grid.history import HistoryNotTracked, get_history_service, is_history_enabled
from tap_grid.models import BaseModel, Batch, BatchEvent, Dimension, Edge, Entity, Keystone, Search
from tap_grid.registry import _entity_model_registry
from tap_grid.services import create_node, delete_node, patch_node, purge_node


def _stated(document: dict[str, Any]) -> dict[str, Any]:
    """State the format "1" header a restamp gives a hand-built document: the spine and every type at 1."""
    document["metadata"] = build_header(document, unversioned=True)
    return document

UNTRACKED_TYPE = "tap_grid__history_scope_untracked"
UNTRACKED_TABLE = "tap_grid__history_scope_untracked"

SPEC_DEFAULT = pytest.mark.spec("req-grid-history-optout-1")
SPEC_NO_MODEL = pytest.mark.spec("req-grid-history-optout-2")
SPEC_DECLARATION = pytest.mark.spec("req-grid-history-optout-3")
SPEC_DEGRADE = pytest.mark.spec("req-grid-history-optout-4")
SPEC_MIGRATION = pytest.mark.spec("req-grid-history-optout-5")
SPEC_SPINE = pytest.mark.spec("req-grid-history-optout-6")
SPEC_CORE = pytest.mark.spec("req-grid-history-optout-7")


def _forget(model_name: str) -> None:
    apps.all_models["tap_grid"].pop(model_name.lower(), None)
    apps.clear_cache()


@pytest.fixture
def untracked_model() -> Iterator[Any]:
    """A concrete node type that opts out of history, registered for this test only."""
    saved = _entity_model_registry.all()
    try:

        class HistoryScopeUntracked(BaseModel):
            ENTITY_TYPE: ClassVar[str] = UNTRACKED_TYPE
            ENTITY_NAME: ClassVar[str] = "History Scope Untracked"
            NATURAL_KEY: ClassVar[tuple[str, ...]] = ("name",)
            TRACK_HISTORY: ClassVar[bool] = False
            FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
                "name": {"type": "string", "minLength": 1},
                "status": {"type": ["string", "null"]},
            }
            CREATE_REQUIRED: ClassVar[list[str]] = ["name"]

            name = models.CharField(max_length=255, blank=True, default="")
            status = models.CharField(max_length=64, null=True, blank=True, default=None)

            class Meta(BaseModel.Meta):
                app_label = "tap_grid"
                db_table = UNTRACKED_TABLE

            def get_name(self) -> str:
                return self.name

        yield HistoryScopeUntracked
    finally:
        _forget("HistoryScopeUntracked")
        _entity_model_registry._reset_for_testing(saved)


@pytest.fixture
def untracked_table(untracked_model: Any, db: Any) -> Any:
    """The fixture type with its table, created inside the test transaction."""
    with connection.schema_editor() as editor:
        editor.create_model(untracked_model)
    return untracked_model


# ---------------------------------------------------------------------------
# -1 Default on / -7 core types keep history
# ---------------------------------------------------------------------------


@SPEC_DEFAULT
def test_every_loaded_type_that_does_not_opt_out_has_history() -> None:
    """Default ON: no installed type opts out today, so every concrete BaseModel subclass loaded
    in this process carries its history manager and a Historical model in the app registry."""
    concrete = [m for m in apps.get_models() if issubclass(m, BaseModel)]
    assert concrete, "no concrete BaseModel subclasses loaded"
    for model in concrete:
        if model.TRACK_HISTORY:
            assert is_history_enabled(model), model
            assert model.history.model._meta.db_table == f"{model._meta.app_label}_historical{model._meta.model_name}"


@SPEC_DEFAULT
def test_the_base_default_is_true() -> None:
    assert BaseModel.TRACK_HISTORY is True
    assert ConstrainedSource.TRACK_HISTORY is True
    assert is_history_enabled(ConstrainedSource)


@SPEC_CORE
@pytest.mark.parametrize("model", [Edge, Batch, Dimension, Search, Keystone])
def test_core_types_keep_history(model: type[BaseModel]) -> None:
    """Edge history is one table for every edge type, and the batch, dimension, search and
    keystone timelines are the platform's own audit trail: none of them opts out."""
    assert model.TRACK_HISTORY is True
    assert is_history_enabled(model)


# ---------------------------------------------------------------------------
# -2 No history model, table, manager or signal handlers
# ---------------------------------------------------------------------------


@SPEC_NO_MODEL
def test_untracked_type_has_no_history_manager(untracked_model: Any) -> None:
    assert not is_history_enabled(untracked_model)
    assert not hasattr(untracked_model, "history")
    assert not hasattr(untracked_model._meta, "simple_history_manager_attribute")


@SPEC_NO_MODEL
def test_untracked_type_has_no_historical_model(untracked_model: Any) -> None:
    names = {m.__name__ for m in apps.get_app_config("tap_grid").get_models()}
    assert "HistoryScopeUntracked" in names
    assert "HistoricalHistoryScopeUntracked" not in names


@SPEC_NO_MODEL
@SPEC_MIGRATION
def test_migration_state_has_the_table_but_no_history_table(untracked_model: Any) -> None:
    """What makemigrations would write: the type's own model, and no Historical model beside it."""
    state = ProjectState.from_apps(apps)
    assert ("tap_grid", "historyscopeuntracked") in state.models
    assert ("tap_grid", "historicalhistoryscopeuntracked") not in state.models
    # A tracked type's history model is in the same state, for contrast.
    label = ConstrainedSource._meta.app_label
    assert (label, "historicalconstrainedsource") in state.models


@SPEC_NO_MODEL
def test_untracked_type_has_no_history_signal_handlers(untracked_model: Any) -> None:
    for signal in (post_save, post_delete):
        receivers = signal._live_receivers(untracked_model)
        flat = [r for group in receivers for r in (group if isinstance(group, list) else [group])]
        assert not any("simple_history" in getattr(r, "__module__", "") for r in flat)
        assert not any(type(getattr(r, "__self__", None)).__name__.endswith("HistoricalRecords") for r in flat)


# ---------------------------------------------------------------------------
# -3 Declaration shape
# ---------------------------------------------------------------------------


@SPEC_DECLARATION
def test_a_non_bool_declaration_is_refused_at_class_creation() -> None:
    saved = _entity_model_registry.all()
    try:
        with pytest.raises(ImproperlyConfigured, match="TRACK_HISTORY must be True or False"):

            class _Truthy(BaseModel):
                ENTITY_TYPE: ClassVar[str] = "tap_grid__history_scope_truthy"
                NATURAL_KEY: ClassVar[tuple[str, ...]] = ("name",)
                TRACK_HISTORY = "no"  # type: ignore[assignment]  # the mistake under test
                FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {"name": {"type": "string"}}
                name = models.CharField(max_length=10)

                class Meta(BaseModel.Meta):
                    app_label = "tap_grid"
    finally:
        _forget("_Truthy")
        _entity_model_registry._reset_for_testing(saved)


@SPEC_DECLARATION
def test_an_abstract_intermediate_opts_out_its_subtree() -> None:
    saved = _entity_model_registry.all()
    try:

        class _UntrackedFamily(BaseModel):
            TRACK_HISTORY: ClassVar[bool] = False

            class Meta(BaseModel.Meta):
                abstract = True

        class HistoryScopeChild(_UntrackedFamily):
            ENTITY_TYPE: ClassVar[str] = "tap_grid__history_scope_child"
            NATURAL_KEY: ClassVar[tuple[str, ...]] = ("name",)
            FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {"name": {"type": "string"}}
            name = models.CharField(max_length=10)

            class Meta(BaseModel.Meta):
                app_label = "tap_grid"

        assert not is_history_enabled(HistoryScopeChild)
    finally:
        _forget("HistoryScopeChild")
        _entity_model_registry._reset_for_testing(saved)


# ---------------------------------------------------------------------------
# -6 Writes and service-layer flows work; the spine and batch record still answer
# ---------------------------------------------------------------------------


@SPEC_SPINE
def test_create_patch_delete_through_the_service_layer(untracked_table: Any) -> None:
    created = create_node(UNTRACKED_TYPE, {"name": "alpha", "status": "new"})
    assert created.success, created.errors
    entity_id = created.entity_id
    assert entity_id is not None

    patched = patch_node(entity_id, {"status": "changed"})
    assert patched.success, patched.errors
    row = untracked_table.objects.get(entity_id=entity_id)
    assert row.status == "changed"

    # Who, when, which batch and what operation survive without a history table.
    entity = Entity.objects.get(pk=entity_id)
    assert entity.version == 2
    assert entity.created_at <= entity.updated_at
    assert str(entity.last_changed_batch_id) == patched.batch_id
    assert row.flip_map.get("status") == patched.batch_id
    events = list(BatchEvent.objects.filter(entity_id=entity_id).order_by("timestamp"))
    assert [e.batch_id for e in events] == [
        Batch.objects.get(entity_id=created.batch_id).pk,
        Batch.objects.get(entity_id=patched.batch_id).pk,
    ]
    assert all(e.actor_id is not None for e in events)

    deleted = delete_node(entity_id, reason="operator")
    assert deleted.success, deleted.errors
    entity.refresh_from_db()
    assert entity.deleted_at is not None
    assert entity.version == 3
    assert not untracked_table.objects.filter(entity_id=entity_id).exists()
    assert untracked_table.all_objects.filter(entity_id=entity_id).exists()


@SPEC_SPINE
def test_grift_import_and_re_import(untracked_table: Any) -> None:
    node_id = str(uuid.uuid4())

    def doc(status: str) -> dict[str, Any]:
        return _stated({
            "metadata": {},
            "_reserved": {},
            "batches": [
                {
                    "batch_entity": {
                        "entity_id": str(uuid.uuid4()),
                        "entity_type": "batch",
                        "name": "history scope",
                        "dimensions": {},
                    },
                    "batch_node": {"name": "history scope", "source": "test", "metadata": {}},
                    "nodes": [
                        {
                            "entity": {
                                "entity_id": node_id,
                                "entity_type": UNTRACKED_TYPE,
                                "name": "beta",
                                "dimensions": {},
                            },
                            "node": {"name": "beta", "status": status},
                        }
                    ],
                    "edges": [],
                }
            ],
        })

    first = grift_import(doc("one"))
    assert first.success, first.errors
    second = grift_import(doc("two"))
    assert second.success, second.errors
    assert untracked_table.objects.get(entity_id=node_id).status == "two"


# ---------------------------------------------------------------------------
# -4 Every history consumer degrades explicitly
# ---------------------------------------------------------------------------


@SPEC_DEGRADE
def test_history_service_says_no_history_rather_than_empty(untracked_table: Any) -> None:
    created = create_node(UNTRACKED_TYPE, {"name": "gamma"})
    row = untracked_table.objects.get(entity_id=created.entity_id)
    svc = get_history_service(row)
    assert svc.is_enabled() is False
    with pytest.raises(HistoryNotTracked, match="no history for this type"):
        svc.raw_records()


@SPEC_DEGRADE
@pytest.mark.django_db
def test_history_service_still_returns_records_for_a_tracked_type() -> None:
    created = create_node("grid_fixtures__constrained_source", {"name": "delta", "description": "x"})
    row = ConstrainedSource.objects.get(entity_id=created.entity_id)
    assert len(list(get_history_service(row).raw_records())) >= 1


@SPEC_DEGRADE
def test_read_guard_covers_the_table_and_names_no_history_table(untracked_model: Any) -> None:
    assert UNTRACKED_TABLE in read_guarded_tables()
    assert not any("historyscopeuntracked" in t for t in history_tables())


@SPEC_DEGRADE
def test_purge_node_on_an_untracked_type(untracked_table: Any, settings: Any) -> None:
    settings.DEBUG = True
    created = create_node(UNTRACKED_TYPE, {"name": "epsilon"})
    entity_id = created.entity_id
    assert entity_id is not None
    result = purge_node(entity_id, reason="history scope test")
    assert result.success, result
    assert not Entity.objects.filter(pk=entity_id).exists()
    assert not untracked_table.all_objects.filter(entity_id=entity_id).exists()
    assert not BatchEvent.objects.filter(entity_id=entity_id).exists()


@SPEC_DEGRADE
def test_grift_sweep_purge_on_an_untracked_type(untracked_table: Any, settings: Any) -> None:
    """The force re-import sweep with purge hard-deletes a dropped node; for an untracked type it
    has no history rows to delete and must not reach for a manager that is not there."""
    settings.DEBUG = True
    batch_id = str(uuid.uuid4())
    node_id = str(uuid.uuid4())

    def doc(nodes: list[dict[str, Any]]) -> dict[str, Any]:
        return _stated({
            "metadata": {},
            "_reserved": {},
            "batches": [
                {
                    "batch_entity": {"entity_id": batch_id, "entity_type": "batch", "name": "b", "dimensions": {}},
                    "batch_node": {"name": "b", "source": "test", "metadata": {}},
                    "nodes": nodes,
                    "edges": [],
                }
            ],
        })

    node = {
        "entity": {"entity_id": node_id, "entity_type": UNTRACKED_TYPE, "name": "zeta", "dimensions": {}},
        "node": {"name": "zeta"},
    }
    assert grift_import(doc([node])).success
    result = grift_import(doc([]), force_batches=[batch_id], purge=True)
    assert result.success, result.errors
    assert any(s.action == "purge" for s in result.imported_batches[0].swept_entities)
    assert not Entity.objects.filter(pk=node_id).exists()


# ---------------------------------------------------------------------------
# -8 Recorded on EntityType, stamped by registration
# ---------------------------------------------------------------------------

SPEC_RECORD = pytest.mark.spec("req-grid-history-optout-8")
SPEC_AGREEMENT = pytest.mark.spec("req-grid-history-optout-9")
SPEC_VALIDATOR = pytest.mark.spec("req-grid-history-optout-10")

_UNTRACKED_PATH = "tests.history_scope.Untracked"
_TRACKED_PATH = "tap_plugin.grid_fixtures.models.ConstrainedSource"


class _ModelEntry:
    def __init__(self, slug: str, class_path: str) -> None:
        self.slug = slug
        self.class_path = class_path


class _EdgeEntry:
    def __init__(self, slug: str) -> None:
        self.slug = slug
        self.name = slug.title()
        self.description = ""


class _Manifest:
    def __init__(self, models_: list[_ModelEntry], edges: list[_EdgeEntry]) -> None:
        self.models = models_
        self.edges = edges


@pytest.fixture
def import_untracked(untracked_model: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Make the fixture type importable by a class path, as a manifest entry names it."""
    from django.utils import module_loading

    real = module_loading.import_string

    def _import(path: str) -> Any:
        return untracked_model if path == _UNTRACKED_PATH else real(path)

    monkeypatch.setattr(module_loading, "import_string", _import)
    return untracked_model


def _register(manifest: _Manifest) -> None:
    from tap_plugins.base import TapPluginConfig

    config = TapPluginConfig.__new__(TapPluginConfig)
    config._manifest = manifest
    config.name = "history_scope_plugin"
    config._register_types_from_manifest()


@SPEC_RECORD
@pytest.mark.django_db
def test_registration_stamps_track_history_from_the_class(import_untracked: Any) -> None:
    from tap_grid.models import EntityType

    _register(
        _Manifest(
            [_ModelEntry(UNTRACKED_TYPE, _UNTRACKED_PATH), _ModelEntry(ConstrainedSource.ENTITY_TYPE, _TRACKED_PATH)],
            [_EdgeEntry("HISTORY_SCOPE_EDGE")],
        )
    )
    assert EntityType.objects.get(slug=UNTRACKED_TYPE).track_history is False
    assert EntityType.objects.get(slug=ConstrainedSource.ENTITY_TYPE).track_history is True
    assert EntityType.objects.get(slug="HISTORY_SCOPE_EDGE").track_history is True


@SPEC_RECORD
@pytest.mark.django_db
def test_re_registration_moves_a_stale_row_to_the_class(import_untracked: Any) -> None:
    """The stamp runs on every load, so a row written while the type still kept history follows
    the class at the next registration rather than outliving the flip."""
    from tap_grid.models import EntityType, EntityTypeKind

    EntityType.objects.create(slug=UNTRACKED_TYPE, name="x", kind=EntityTypeKind.NODE, track_history=True)
    _register(_Manifest([_ModelEntry(UNTRACKED_TYPE, _UNTRACKED_PATH)], []))
    assert EntityType.objects.get(slug=UNTRACKED_TYPE).track_history is False


@SPEC_RECORD
@pytest.mark.django_db
def test_the_field_defaults_true_and_core_search_is_stamped_from_its_class(monkeypatch: pytest.MonkeyPatch) -> None:
    from tap_grid.model_version import register_core_types
    from tap_grid.models import EntityType, Search

    field = EntityType._meta.get_field("track_history")
    _, _, _, kwargs = field.deconstruct()
    assert kwargs["default"] is True
    assert kwargs["db_index"] is True
    # Core's types are stamped by the registration tap_grid's ready() runs, from the class, on every load.
    register_core_types()
    assert EntityType.objects.get(slug="search").track_history is Search.TRACK_HISTORY
    monkeypatch.setattr(Search, "TRACK_HISTORY", not Search.TRACK_HISTORY)
    register_core_types()
    assert EntityType.objects.get(slug="search").track_history is Search.TRACK_HISTORY


# ---------------------------------------------------------------------------
# -9 Agreement check and probe
# ---------------------------------------------------------------------------


@SPEC_AGREEMENT
@pytest.mark.django_db
def test_every_loaded_type_agrees() -> None:
    """Class, catalog row and history model agree for every type this process loaded."""
    from tap_grid.history import history_agreement_problems

    assert history_agreement_problems() == []


@SPEC_AGREEMENT
def test_agreement_holds_for_an_opted_out_type_with_a_matching_row(untracked_model: Any) -> None:
    from tap_grid.history import history_agreement_problems

    assert history_agreement_problems(recorded={UNTRACKED_TYPE: False}) == []
    assert history_agreement_problems(recorded={}) == [], "a missing row is not a disagreement"


@SPEC_AGREEMENT
def test_agreement_finds_a_row_that_disagrees_with_class_and_model(untracked_model: Any) -> None:
    from tap_grid.history import history_agreement_problems

    problems = history_agreement_problems(recorded={UNTRACKED_TYPE: True})
    assert [p.entity_type for p in problems] == [UNTRACKED_TYPE]
    (problem,) = problems
    assert problem.declared is False and problem.recorded is True and problem.has_history_model is False
    assert problem.disagreements == ("row vs class", "row vs model")


@SPEC_AGREEMENT
def test_agreement_finds_a_tracked_type_whose_row_says_untracked() -> None:
    from tap_grid.history import history_agreement_problems

    problems = history_agreement_problems(recorded={ConstrainedSource.ENTITY_TYPE: False})
    assert [(p.entity_type, p.disagreements) for p in problems] == [
        (ConstrainedSource.ENTITY_TYPE, ("row vs class", "row vs model"))
    ]


@SPEC_AGREEMENT
def test_agreement_finds_a_class_whose_history_model_disagrees(
    untracked_model: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A history model attached outside TapHistoricalRecords: the class says no history, yet a
    Historical model exists. The row (stamped from the class) agrees with the class only."""
    from tap_grid import history as history_mod

    monkeypatch.setattr(history_mod, "is_history_enabled", lambda cls: cls is untracked_model or hasattr(cls, "history"))
    problems = history_mod.history_agreement_problems(recorded={UNTRACKED_TYPE: False})
    assert [(p.entity_type, p.disagreements) for p in problems] == [
        (UNTRACKED_TYPE, ("class vs model", "row vs model"))
    ]
    assert "TRACK_HISTORY=False" in str(problems[0])


@SPEC_AGREEMENT
@pytest.mark.django_db
def test_agreement_reads_the_catalog_rows(untracked_model: Any) -> None:
    from tap_grid.history import history_agreement_problems
    from tap_grid.models import EntityType, EntityTypeKind

    EntityType.objects.create(slug=UNTRACKED_TYPE, name="x", kind=EntityTypeKind.NODE, track_history=True)
    assert [p.entity_type for p in history_agreement_problems()] == [UNTRACKED_TYPE]
    EntityType.objects.filter(slug=UNTRACKED_TYPE).update(track_history=False)
    assert history_agreement_problems() == []


@SPEC_AGREEMENT
@pytest.mark.django_db
def test_probe_reports_a_disagreement_and_is_healthy_without_one(untracked_model: Any) -> None:
    from tap_grid.health import probe_history_agreement
    from tap_grid.models import EntityType, EntityTypeKind
    from tap_health.results import ProbeStatus

    assert probe_history_agreement().status is ProbeStatus.HEALTHY
    EntityType.objects.create(slug=UNTRACKED_TYPE, name="x", kind=EntityTypeKind.NODE, track_history=True)
    result = probe_history_agreement()
    assert result.status is ProbeStatus.UNHEALTHY
    assert result.code == "grid.history_disagreement"
    assert result.context["disagreements"] == [UNTRACKED_TYPE]
    assert UNTRACKED_TYPE in (result.detail or "")


@SPEC_AGREEMENT
def test_probe_is_a_non_critical_readiness_probe() -> None:
    from tap_health.registry import health_probe_registry
    from tap_health.selection import READINESS

    probe = health_probe_registry.get("grid.history_agreement")
    assert probe.critical is False
    assert READINESS in probe.sets
    assert probe.group == "tap_grid"


# ---------------------------------------------------------------------------
# -10 validate_plugin lists opt-outs as info
# ---------------------------------------------------------------------------


def _validation_result() -> Any:
    from tap_plugins.validate.service import ValidationResult

    return ValidationResult(ok=True, level="loads", plugin_path="/nowhere", strict=True)


@SPEC_VALIDATOR
def test_validator_lists_opted_out_types_as_info(import_untracked: Any) -> None:
    from tap_plugins.validate.service import _check_history_opt_outs

    result = _validation_result()
    _check_history_opt_outs(
        _Manifest(
            [_ModelEntry(UNTRACKED_TYPE, _UNTRACKED_PATH), _ModelEntry(ConstrainedSource.ENTITY_TYPE, _TRACKED_PATH)],
            [],
        ),
        result,
    )
    (check,) = result.checks
    assert check.id == "history-opt-outs"
    assert check.status == "pass"
    assert {m.severity for m in check.messages} == {"info"}
    assert [m.path for m in check.messages] == [_UNTRACKED_PATH]
    assert check.details == {"opted_out": [UNTRACKED_TYPE]}


@SPEC_VALIDATOR
def test_validator_says_so_when_nothing_opts_out() -> None:
    from tap_plugins.validate.service import _check_history_opt_outs

    result = _validation_result()
    _check_history_opt_outs(_Manifest([_ModelEntry(ConstrainedSource.ENTITY_TYPE, _TRACKED_PATH)], []), result)
    (check,) = result.checks
    assert check.status == "pass" and check.details == {"opted_out": []}
    assert check.messages[0].severity == "info"


@SPEC_VALIDATOR
@requires_plugins("validation_sample")  # the loads level imports the fixture plugin
def test_the_check_runs_at_the_loads_level_and_passes_strict() -> None:
    """Wired into the loads level, and an info listing never fails a ``--strict`` run."""
    from pathlib import Path

    import tap_plugins
    from tap_plugins.validate.service import validate_plugin

    root = Path(tap_plugins.__file__).resolve().parent / "tests" / "fixtures" / "validation_sample"
    result = validate_plugin(root, level="loads", strict=True)
    check = next(c for c in result.checks if c.id == "history-opt-outs")
    assert check.status == "pass"
    assert all(m.severity == "info" for m in check.messages)
