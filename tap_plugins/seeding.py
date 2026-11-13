"""Reusable plugin-GRIFT seeding ops — the boot-agnostic seed-plugin path.

`import_plugin_grift` (the management command) and `tap_boot`'s population phase
(`seed-plugin` step, req-boot-population) share this single import path so dev
and customer standup seed plugins identically. The command keeps its CLI
concerns (argument parsing, dry-run, lint, rich reporting); the actual
plugin → bundles → `grift_import` work lives here and returns structured
outcomes for callers to format/log as they see fit.

No boot logic lives here: `seed_plugin` takes an explicit `actor` and writes
through the GRIFT importer exactly like any other caller; whoever calls it
supplies the actor (the bootloader, in boot).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.apps import apps

from tap_plugins.base import TapPluginConfig

logger = logging.getLogger(__name__)


class PluginNotFound(LookupError):
    """Raised when a requested plugin slug is not a loaded TAP plugin."""


@dataclass
class BundleOutcome:
    """The result of importing one declared GRIFT bundle.

    `read_error` is set when the bundle file could not be read/parsed; otherwise
    `result` carries the `grift_import` result object (`.success`, `.counts`,
    `.errors`, `.imported_batches`, `.skipped_batches`).
    """

    slug: str
    bundle_name: str
    bundle_path: str
    read_error: str | None = None
    result: Any | None = None

    @property
    def ok(self) -> bool:
        return self.read_error is None and self.result is not None and self.result.success


def all_tap_plugins() -> list[TapPluginConfig]:
    """Every loaded TAP plugin, in INSTALLED_APPS order (the canonical seed order)."""
    return [c for c in apps.get_app_configs() if isinstance(c, TapPluginConfig)]


def resolve_tap_plugin(slug: str) -> TapPluginConfig:
    """Resolve a plugin slug to its loaded config; raise `PluginNotFound` if unknown.

    This is the pre-resolution boot uses to fail loud on an unknown `seed-plugin`
    key before any population step mutates the grid (req-boot-population-4).
    """
    for config in all_tap_plugins():
        if config.manifest and config.manifest.slug == slug:
            return config
    available = sorted(c.manifest.slug for c in all_tap_plugins() if c.manifest)
    raise PluginNotFound(f"No TAP plugin with slug '{slug}' in INSTALLED_APPS. Available: {available}")


def seed_plugin(
    config: TapPluginConfig,
    *,
    actor: Any,
    bundle_name: str | None = None,
    force_batches: tuple[str, ...] = (),
    sweep_strict: bool = False,
    purge: bool = False,
) -> list[BundleOutcome]:
    """Import a plugin's declared GRIFT bundles in manifest order as `actor`.

    Returns one `BundleOutcome` per attempted bundle. A bundle that fails to read
    yields a `read_error` outcome and does not stop the rest — the caller decides
    how a failure aborts (boot honors the profile's `on_failure`). Strict upsert
    semantics and the DEBUG-gated force/sweep/purge flags are passed straight
    through to `grift_import` (req-grid-import-grift-*).
    """
    from tap_grid.grift import grift_import
    from tap_grid.grift.retired import RetiredCollisionError, strip_retired_types

    manifest = config.manifest
    if manifest is None:
        return [
            BundleOutcome(
                slug=config.name,
                bundle_name="(no manifest)",
                bundle_path="",
                read_error="No manifest loaded",
            )
        ]

    bundles = manifest.grift
    if bundle_name is not None:
        bundles = [b for b in bundles if b.name == bundle_name]

    outcomes: list[BundleOutcome] = []
    for bundle in bundles:
        grift_path = manifest.plugin_root / bundle.path
        try:
            with open(grift_path) as fh:
                document = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            outcomes.append(
                BundleOutcome(
                    slug=manifest.slug,
                    bundle_name=bundle.name,
                    bundle_path=str(bundle.path),
                    read_error=str(exc),
                )
            )
            continue

        # Retired entity types (tap_grid.registry.retire_entity_type) are dropped here,
        # not failed: an older plugin pin must not become an upgrade cliff.
        try:
            document, retired = strip_retired_types(document)
        except RetiredCollisionError as exc:
            logger.error("[188f] seed %s/%s refused: %s", manifest.slug, bundle.name, exc)
            outcomes.append(
                BundleOutcome(
                    slug=manifest.slug, bundle_name=bundle.name, bundle_path=str(bundle.path), read_error=str(exc)
                )
            )
            continue
        if retired.stripped:
            logger.warning(
                "[d7d5] seed %s/%s: stripped %d node(s) of retired entity type(s) and %d edge(s) touching them — "
                "re-publish the bundle without them. %s",
                manifest.slug,
                bundle.name,
                len(retired.nodes),
                retired.edges,
                "; ".join(f"{t}: {r}" for t, r in retired.reasons.items()),
            )

        result = grift_import(  # TAP-AUTHZ-COV: boot/CLI standup population (seed_plugin, actor=bootloader); not request-reachable
            document,
            # "warn" is the historical seed value faithfully carried over from the
            # former import_plugin_grift fire path; the importer types this str
            # internally (the public Literal is narrower). Preserved to keep seed
            # behavior identical — not a place to change semantics in this pass.
            dangling_edge_mode="warn",  # type: ignore[arg-type]
            actor=actor,
            force_batches=list(force_batches) or None,
            sweep_strict=sweep_strict,
            purge=purge,
        )
        outcomes.append(
            BundleOutcome(
                slug=manifest.slug,
                bundle_name=bundle.name,
                bundle_path=str(bundle.path),
                result=result,
            )
        )
    return outcomes


DIMENSION_BUNDLE = "dimension"
"""The ``[grift]`` bundle name a plugin declares its Dimension nodes under (req-tap-plugin-manifest-v0-grift-11)."""


@dataclass(frozen=True)
class DimensionBundle:
    """One dimension vocabulary bundle: who declares it, a label naming it, and its file."""

    slug: str
    label: str
    path: Path


def dimension_bundles() -> list[DimensionBundle]:
    """The dimension vocabulary bundles, in import order: core's first, then each installed plugin's
    ``[grift] dimension`` bundle in INSTALLED_APPS order (req-boot-phases-5). Installed means in
    INSTALLED_APPS, whether or not a profile seeds the plugin."""
    from tap_grid.live_dimensions import CORE_SEED

    bundles = [DimensionBundle("tap_grid", "tap_grid/dimension (data/dimensions.grift.json)", CORE_SEED)]
    for config in all_tap_plugins():
        manifest = config.manifest
        if manifest is None:
            continue
        for entry in manifest.grift:
            if entry.name == DIMENSION_BUNDLE:
                label = f"{manifest.slug}/{entry.name} ({entry.path})"
                bundles.append(DimensionBundle(manifest.slug, label, Path(manifest.plugin_root) / entry.path))
    return bundles


def _not_only_dimensions(document: Any) -> str | None:
    """Why a dimension bundle holds more than Dimension nodes, or None. It is imported on every grid,
    whether or not the profile seeds its plugin, so anything else in it would land unasked."""
    if not isinstance(document, dict):
        return "not a GRIFT document object"
    for index, batch in enumerate(document.get("batches") or []):
        if not isinstance(batch, dict):
            return f"batch {index} is not an object"
        for section in ("edges", "deletes", "purges"):
            if batch.get(section):
                return f"batch {index} carries {section}; a dimension bundle declares Dimension nodes only"
        for node in batch.get("nodes") or []:
            entity_type = ((node or {}).get("entity") or {}).get("entity_type") if isinstance(node, dict) else None
            if entity_type != "dimension":
                return (
                    f"batch {index} declares a {entity_type!r} node; a dimension bundle declares Dimension nodes only"
                )
    return None


def seed_dimension_vocabulary(*, actor: Any, extra: list[DimensionBundle] | None = None) -> list[BundleOutcome]:
    """Import every dimension vocabulary bundle (:func:`dimension_bundles`, then ``extra``) as ``actor``.

    Stops at the first bundle that does not import, and returns the outcomes so far, the failing one
    last: later bundles stamp the dimensions earlier ones declare (every Dimension node carries
    core's ``tap.meta``). Each bundle's seed batch has a fixed id, so a re-run skips it and writes
    nothing, and the plugin's own seed-plugin step later skips it the same way.
    """
    from tap_grid.grift import grift_import

    outcomes: list[BundleOutcome] = []
    for bundle in [*dimension_bundles(), *(extra or [])]:
        outcome = BundleOutcome(slug=bundle.slug, bundle_name=bundle.label, bundle_path=str(bundle.path))
        outcomes.append(outcome)
        try:
            with open(bundle.path, encoding="utf-8") as fh:
                document = json.load(fh)
        except (OSError, ValueError) as exc:
            outcome.read_error = str(exc)
            return outcomes
        problem = _not_only_dimensions(document)
        if problem is not None:
            outcome.read_error = problem
            return outcomes
        outcome.result = grift_import(  # TAP-AUTHZ-COV: boot standup (actor=bootloader); not request-reachable
            document, dangling_edge_mode="strict", actor=actor
        )
        if not outcome.ok:
            return outcomes
    return outcomes
