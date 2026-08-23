"""TapPluginConfig — base class for TAP plugins.

Plugins subclass this and provide a tap-plugin.toml manifest at their root.
The manifest declares TAP-managed model types, edge types, editor descriptors,
search runners, and bundled GRIFT files.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from django.apps import AppConfig
from django.db import OperationalError, ProgrammingError

logger = logging.getLogger(__name__)


def register_edge_types_from_list(edge_types: list[dict[str, Any]]) -> None:
    """Register edge constraints, property schemas, and default dimensions.

    Utility for non-plugin apps that need to register edge types without a manifest.
    Processes a list of edge type dicts using the legacy {slug, sources, targets, ...} shape.
    """
    from tap_grid.constraints import (
        register_edge_default_dimensions,
        register_edge_property_schema,
        register_edge_type_constraints,
    )

    for et in edge_types:
        slug = et["slug"]
        sources = et.get("sources")
        targets = et.get("targets")

        if sources is not None or targets is not None:
            register_edge_type_constraints(slug, sources, targets)

        if "property_schema" in et:
            register_edge_property_schema(slug, et["property_schema"])

        if "default_dimensions" in et:
            register_edge_default_dimensions(slug, et["default_dimensions"])


class TapPluginConfig(AppConfig):
    """Base AppConfig for TAP plugins.

    Subclass this and provide a tap-plugin.toml manifest at the plugin root::

        class MyPluginConfig(TapPluginConfig):
            name = "my_plugin"

    ``label`` and ``verbose_name`` are read from ``tap-plugin.toml`` (slug and
    name respectively) so they don't need to be declared here.  Explicit class
    attributes still take precedence if you need to override them.
    """

    # Resolved at ready() time; None until then.
    _manifest: Any = None  # PluginManifest | None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Auto-derive ``name`` from the subclass module path if not explicitly set."""
        super().__init_subclass__(**kwargs)
        if "name" not in cls.__dict__:
            cls.name = cls.__module__.rsplit(".", 1)[0]

    def __init__(self, app_name: str, app_module: Any) -> None:
        """Populate label/verbose_name from tap-plugin.toml before Django reads them."""
        toml_path = Path(app_module.__file__).parent / "tap-plugin.toml"
        if toml_path.exists():
            import tomllib

            with open(toml_path, "rb") as fh:
                data = tomllib.load(fh)
            if "label" not in type(self).__dict__ and "slug" in data:
                self.label = data["slug"]
            if "verbose_name" not in type(self).__dict__ and "name" in data:
                self.verbose_name = data["name"]
        super().__init__(app_name, app_module)

    @property
    def manifest(self) -> Any:
        """Return the loaded PluginManifest, or None if not yet loaded."""
        return self._manifest

    def ready(self) -> None:
        self._load_and_validate_manifest()
        self._register_edges_from_manifest()
        self._register_types_from_manifest()
        self._register_editors_from_manifest()
        self._register_searches_from_manifest()
        # NOTE: ready() must not perform queries or mutations against TAP-managed
        # graph state. Grift import is an explicit operator action via the
        # `manage.py import_plugin_grift` management command. See
        # req-tap-plugin-load-v0-ready-readonly in spec-tap-plugin-load-lifecycle-v0.md.

    def get_api_router(self) -> Any:
        """Return a ninja.Router for this plugin, or None.

        Override to expose endpoints at /api/v1/plugins/<label>/...
        tap_api discovers and mounts these automatically.
        """
        return None

    # ---------------------------------------------------------------------------
    # Manifest loading
    # ---------------------------------------------------------------------------

    def _plugin_root(self) -> Path:
        """Return the filesystem root of this plugin package."""
        import importlib

        mod = importlib.import_module(self.name)
        return Path(mod.__file__).parent  # type: ignore[arg-type]

    def _load_and_validate_manifest(self) -> None:
        """Load tap-plugin.toml and run structural + path validation."""
        from tap_plugins.manifest import (
            PluginManifestError,
            load_manifest,
            validate_manifest_classes,
            warn_undeclared_convention_files,
        )

        root = self._plugin_root()
        try:
            manifest = load_manifest(root)
        except PluginManifestError as exc:
            raise RuntimeError(f"Plugin '{self.name}' failed manifest validation: {exc}") from exc

        try:
            validate_manifest_classes(manifest)
        except PluginManifestError as exc:
            raise RuntimeError(f"Plugin '{self.name}' manifest class validation failed: {exc}") from exc

        warn_undeclared_convention_files(manifest)
        self._manifest = manifest

    # ---------------------------------------------------------------------------
    # Edge registration
    # ---------------------------------------------------------------------------

    def _register_edges_from_manifest(self) -> None:
        """Register edge constraints, property schemas, and default dimensions from manifest."""
        if self._manifest is None:
            return

        from tap_grid.constraints import (
            register_edge_default_dimensions,
            register_edge_property_schema,
            register_edge_type_constraints,
        )

        for edge in self._manifest.edges:
            sources = [{"type": s} for s in edge.sources] if edge.sources is not None else None
            targets = [{"type": t} for t in edge.targets] if edge.targets is not None else None

            if sources is not None or targets is not None:
                register_edge_type_constraints(edge.slug, sources, targets)

            if edge.property_schema is not None:
                register_edge_property_schema(edge.slug, edge.property_schema)

            if edge.default_dimensions is not None:
                register_edge_default_dimensions(edge.slug, edge.default_dimensions)

    # ---------------------------------------------------------------------------
    # Type registration
    # ---------------------------------------------------------------------------

    def _register_types_from_manifest(self) -> None:
        """Register entity and edge types into the EntityType table from manifest."""
        if self._manifest is None:
            return

        try:
            from django.utils.module_loading import import_string

            from tap_grid.models import EntityType, EntityTypeKind

            for model_entry in self._manifest.models:
                cls = import_string(model_entry.class_path)
                EntityType.objects.update_or_create(
                    slug=model_entry.slug,
                    defaults={
                        "name": getattr(cls, "ENTITY_NAME", model_entry.slug),
                        "icon": getattr(cls, "ENTITY_ICON", ""),
                        "description": getattr(cls, "ENTITY_DESCRIPTION", ""),
                        "plugin_name": self.name,
                        # The writer is the only place that knows which kind this is
                        # (the manifest separates models from edges), so it stamps it
                        # here — req-grid-entity-type-kind.
                        "kind": EntityTypeKind.NODE,
                    },
                )

            for edge in self._manifest.edges:
                EntityType.objects.update_or_create(
                    slug=edge.slug,
                    defaults={
                        "name": edge.name,
                        "icon": "",
                        "description": edge.description,
                        "plugin_name": self.name,
                        "kind": EntityTypeKind.EDGE,
                    },
                )

        except OperationalError, ProgrammingError:
            logger.debug("[26a8] EntityType table not ready; skipping type registration.")

    # ---------------------------------------------------------------------------
    # Editor registration
    # ---------------------------------------------------------------------------

    def _register_editors_from_manifest(self) -> None:
        """Register editor descriptors declared in the manifest."""
        if self._manifest is None or not self._manifest.editors:
            return

        from django.utils.module_loading import import_string

        from tap_web.registry import register_editor

        for entry in self._manifest.editors:
            cls = import_string(entry.class_path)
            register_editor(cls())

    # ---------------------------------------------------------------------------
    # Search registration
    # ---------------------------------------------------------------------------

    def _register_searches_from_manifest(self) -> None:
        """Register search runner callables declared in the manifest."""
        if self._manifest is None or not self._manifest.searches:
            return

        from django.utils.module_loading import import_string

        from tap_grid.registry import register_search_runner

        for entry in self._manifest.searches:
            runner = import_string(entry.callable_path)
            register_search_runner(entry.runner_key, runner)
