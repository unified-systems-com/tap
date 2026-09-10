"""The core's plugin contract, made explicit — for every plugin installed in THIS stack.

Spec: specs/spec-dev-validation.md (req-dev-validation-bom-lane-4);
      tap_plugins/specs/spec-tap-plugin-architecture.md (req-tap-plugin-arch-manifest,
      req-tap-plugin-arch-surfaces, req-tap-plugin-arch-dependencies);
      tap_web/specs/spec-web-panel.md (req-web-panel-obj).

"Installed successfully" is weak evidence that core still honours what a plugin was written
against. This suite says what the contract IS, per installed plugin: the manifest loads and
every surface it declares is registered; the plugin's migrations are clean and applied; its
GRIFT bundles import through the seeding service and a typed node reads back through the
service layer; its extension hooks (API router, panel types, collectors) are mounted where the
contract says. It runs wherever pytest runs, over whatever is installed — in the `core_ci` lane
that is the fixtures plus the canary, in the BOM lane the full set. A check that does not
apply to a plugin skips WITH the reason, never silently.
"""

from __future__ import annotations

import io
import json
from typing import Any

import pytest
from django.apps import apps
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.template.loader import get_template

from tap.plugin_testing import installed_plugin_slugs
from tap_plugins.base import TapPluginConfig

INSTALLED = installed_plugin_slugs()


def _config(slug: str) -> TapPluginConfig:
    for cfg in apps.get_app_configs():
        if isinstance(cfg, TapPluginConfig) and cfg.label == slug:
            return cfg
    raise AssertionError(f"no TapPluginConfig registered for installed plugin {slug!r}")


_PARAMS: list[Any] = list(INSTALLED) or [
    pytest.param(None, marks=pytest.mark.skip(reason="no plugin installed in this stack"))
]


@pytest.fixture(params=_PARAMS)
def plugin(request: pytest.FixtureRequest) -> TapPluginConfig:
    return _config(request.param)


# --- registration ----------------------------------------------------------------------


@pytest.mark.spec("req-dev-validation-bom-lane-4")
def test_manifest_loads_and_names_the_plugin(plugin: TapPluginConfig) -> None:
    """req-tap-plugin-arch-manifest: the app config carries a parsed manifest whose slug is the label."""
    manifest = plugin.manifest
    assert manifest is not None, f"{plugin.label}: no manifest loaded"
    assert manifest.slug == plugin.label
    assert manifest.plugin_version, f"{plugin.label}: manifest declares no plugin_version"


@pytest.mark.spec("req-dev-validation-bom-lane-4")
def test_declared_models_are_registered_entity_types(plugin: TapPluginConfig) -> None:
    """req-tap-plugin-arch-surfaces: every manifest model resolves in the grid's type registry."""
    from tap_grid.registry import get_model_class

    manifest = plugin.manifest
    if not manifest.models:
        pytest.skip(f"{plugin.label} declares no models")
    for entry in manifest.models:
        cls = get_model_class(entry.slug)
        assert (
            f"{cls.__module__}.{cls.__qualname__}" == entry.class_path
        ), f"{plugin.label}: {entry.slug} is registered to {cls.__module__}.{cls.__qualname__}, manifest says {entry.class_path}"


@pytest.mark.spec("req-dev-validation-bom-lane-4")
def test_declared_edges_are_registered_as_declared(plugin: TapPluginConfig) -> None:
    """req-tap-plugin-arch-surfaces: what a manifest edge declares, core registered — exactly that.

    An edge type with `sources`/`targets` must be in the constraints registry with those very
    endpoint sets; a declared `property_schema` and `default_dimensions` must read back equal. A
    wildcard edge with neither declares nothing for core to register (the manifest IS its
    registration), so it is counted, not asserted.
    """
    from tap_grid.constraints import get_edge_default_dimensions, get_edge_property_schema, get_edge_type_constraints

    manifest = plugin.manifest
    if not manifest.edges:
        pytest.skip(f"{plugin.label} declares no edge types")
    problems: list[str] = []
    for entry in manifest.edges:
        if entry.sources is not None or entry.targets is not None:
            constraints = get_edge_type_constraints(entry.slug)
            if constraints is None:
                problems.append(f"{entry.slug}: constrained in the manifest, absent from the constraints registry")
            else:
                # A registered side is a set (allow-list), the WILDCARD sentinel (any) or None
                # (unconstrained); the manifest spells both of the last two as null.
                def _norm(side: object) -> list[str] | None:
                    return sorted(side) if isinstance(side, (set, frozenset, list)) else None

                got = (_norm(constraints.sources), _norm(constraints.targets))
                want = (_norm(entry.sources), _norm(entry.targets))
                if got != want:
                    problems.append(f"{entry.slug}: registered endpoints {got} != declared {want}")
        if entry.property_schema is not None and get_edge_property_schema(entry.slug) != entry.property_schema:
            problems.append(f"{entry.slug}: registered property_schema differs from the manifest's")
        if entry.default_dimensions is not None and get_edge_default_dimensions(entry.slug) != entry.default_dimensions:
            problems.append(f"{entry.slug}: registered default_dimensions differ from the manifest's")
    assert not problems, f"{plugin.label}: " + "; ".join(problems)


@pytest.mark.spec("req-dev-validation-bom-lane-4")
def test_declared_dependencies_are_installed(plugin: TapPluginConfig) -> None:
    """req-tap-plugin-arch-dependencies: a non-optional depends_on names a plugin this stack installed."""
    manifest = plugin.manifest
    required = [d.slug for d in manifest.depends_on if not d.optional]
    if not required:
        pytest.skip(f"{plugin.label} declares no required dependencies")
    missing = sorted(set(required) - set(INSTALLED))
    assert not missing, f"{plugin.label}: required dependencies not installed: {missing}"


# --- migrations ------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.spec("req-dev-validation-bom-lane-4")
def test_migrations_are_clean_and_applied(plugin: TapPluginConfig) -> None:
    """The plugin's models match its migrations, and every migration is applied to the test DB."""
    if not plugin.models_module:
        pytest.skip(f"{plugin.label} ships no models module")
    out = io.StringIO()
    # --check exits non-zero when a migration would be generated: the model/migration drift a
    # plugin release forgot. Called per app so one plugin's drift names that plugin.
    call_command("makemigrations", plugin.label, "--check", "--dry-run", stdout=out, stderr=out)
    executor = MigrationExecutor(connection)
    graph = executor.loader.graph
    leaves = [node for node in graph.leaf_nodes() if node[0] == plugin.label]
    if not leaves:
        pytest.skip(f"{plugin.label} has no migrations")
    plan = executor.migration_plan(leaves)
    assert plan == [], f"{plugin.label}: unapplied migrations in the test DB: {[m.name for m, _ in plan]}"


# --- GRIFT -----------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.spec("req-dev-validation-bom-lane-4")
def test_grift_bundles_import_and_a_typed_node_reads_back(plugin: TapPluginConfig) -> None:
    """Every declared bundle imports through the seeding service; one plugin-typed node round-trips.

    The read-back goes through `tap_grid.services.get_node` (the canonical read path), not the
    ORM: the contract is "a node the plugin ships is reachable the way every consumer reaches it".
    """
    from tap_auth.actors import BOOTLOADER, acting_as, get_builtin_actor
    from tap_grid import services
    from tap_plugins.seeding import seed_plugin

    manifest = plugin.manifest
    if not manifest.grift:
        pytest.skip(f"{plugin.label} declares no GRIFT bundles")
    actor = get_builtin_actor(BOOTLOADER)
    with acting_as(actor):
        outcomes = seed_plugin(plugin, actor=actor)
    failed = [
        o
        for o in outcomes
        if getattr(o, "errors", None) or getattr(o, "status", "ok") not in ("ok", "imported", "skipped")
    ]
    assert outcomes, f"{plugin.label}: seed_plugin attempted no bundle"
    assert not failed, f"{plugin.label}: bundle outcomes with errors: {failed}"

    # One node of a type this plugin owns, from the first bundle that carries one.
    owned_prefix = f"{plugin.label}__"
    candidate: dict[str, Any] | None = None
    for bundle in manifest.grift:
        document = json.loads((manifest.plugin_root / bundle.path).read_text(encoding="utf-8"))
        for batch in document.get("batches", []):
            for wrapped in batch.get("nodes", []):
                entity = wrapped.get("entity", {})
                if str(entity.get("entity_type", "")).startswith(owned_prefix):
                    candidate = wrapped
                    break
            if candidate:
                break
        if candidate:
            break
    if candidate is None:
        pytest.skip(f"{plugin.label}: its bundles carry no node of a {owned_prefix}* type (visualization-only GRIFT)")
    entity = candidate["entity"]
    with acting_as(actor):
        obj = services.get_node(entity["entity_id"])
    assert str(obj.entity.entity_type) == entity["entity_type"]
    assert obj.entity.name == entity.get("name"), f"{plugin.label}: round-trip name mismatch on {entity['entity_id']}"


# --- extension hooks -------------------------------------------------------------------


@pytest.mark.spec("req-dev-validation-bom-lane-4")
def test_api_router_is_mounted_under_the_plugin_prefix(plugin: TapPluginConfig) -> None:
    """A plugin that exposes a router is mounted at /api/v1/plugins/<label>/ and nowhere else."""
    from tap_api.api import api

    router = plugin.get_api_router()
    if router is None:
        pytest.skip(f"{plugin.label} exposes no API router")
    prefix = f"/api/v1/plugins/{plugin.label}/"
    paths = list(api.get_openapi_schema().get("paths", {}))
    assert any(
        p.startswith(prefix) for p in paths
    ), f"{plugin.label}: router exposed but no path under {prefix}; paths={paths[:5]}"


@pytest.mark.spec("req-dev-validation-bom-lane-4")
def test_panel_types_render_their_templates(plugin: TapPluginConfig) -> None:
    """req-web-panel-obj: every panel type registered under the plugin's scope names a loadable view."""
    from tap_web.registry import panel_type_registry

    scoped = panel_type_registry.all().get(plugin.label, {})
    if not scoped:
        pytest.skip(f"{plugin.label} registers no panel types")
    for key, cls in scoped.items():
        view = getattr(cls, "view", None)
        assert view, f"{plugin.label}: panel type {key!r} declares no view"
        get_template(view)


@pytest.mark.spec("req-dev-validation-bom-lane-4")
def test_collectors_carry_valid_registry_keys(plugin: TapPluginConfig) -> None:
    """Every collector registered under the plugin's scope has a key the registry's validator accepts."""
    from tap_cares.registry import collector_registry

    scoped = collector_registry.all().get(plugin.label, {})
    if not scoped:
        pytest.skip(f"{plugin.label} registers no collectors")
    for key, cls in scoped.items():
        assert key, f"{plugin.label}: empty collector key"
        collector_registry.get(key, scope=plugin.label)  # resolves back through the registry
        assert getattr(cls, "collector_key", key) is not None
