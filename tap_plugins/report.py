"""Read-only plugin registry/report service (req-tap-plugin-arch-install-registry -3/-5).

The single service-layer source for "what plugins is this instance running, from where,
in what shape, and how do they depend on each other." A SERIALIZATION of facts Django +
package metadata already hold — not a computation and not a graph write (so it sits inside
the tap_ai v0 read-only boundary). Both consumers call ``build_report()``:

- ``manage.py plugins`` (text + ``--json``) — the operator/CLI surface.
- the administrivia plugin status page — the human surface (gated by ``plugins.read``).

The output validates against ``schemas/plugin-report.schema.json`` before return, so a
drift between this code and the published contract fails loud here rather than downstream.

Service seam (per the routing discipline): today the facts are package/Django metadata,
not grid entities, so this reads them directly. When plugins graduate to grid nodes
(the demand-gated rung 2), this function's body swaps to a service-layer grid read and
NEITHER consumer changes — the interface is the point.
"""

from __future__ import annotations

import importlib.metadata
import json
import logging
from pathlib import Path
from typing import Any

from tap import plugin_deps
from tap.jsonfiles import validate_json
from tap.preboot import direct_url_vcs_rev, dist_name_for_slug

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "plugin-report.schema.json"
SCHEMA_VERSION = 1


def _provenance(dist_name: str) -> dict[str, Any]:
    """Resolve (version, commit, source, mode) from installed distribution metadata.

    Reads PEP 610 ``direct_url.json`` for provenance: editable/path installs are
    ``checkout`` mode, git/wheel installs are ``package`` mode. Missing metadata degrades
    to ``unknown``/``package`` rather than failing — a report is best-effort ground truth.
    """
    try:
        dist = importlib.metadata.distribution(dist_name)
    except importlib.metadata.PackageNotFoundError:
        return {"version": None, "commit": None, "source": "unknown", "mode": "package"}

    version = dist.version
    commit: str | None = None
    source = "unknown"
    mode = "package"

    raw = dist.read_text("direct_url.json")
    if raw:
        try:
            info = json.loads(raw)
        except json.JSONDecodeError:
            info = {}
        vcs = info.get("vcs_info") or {}
        dir_info = info.get("dir_info") or {}
        archive = info.get("archive_info") or {}
        if vcs:
            source, mode = "git", "package"
            commit = direct_url_vcs_rev(info)
        elif dir_info:
            if dir_info.get("editable"):
                source, mode = "editable", "checkout"
            else:
                source, mode = "path", "checkout"
        elif archive:
            source, mode = "wheel", "package"

    return {"version": version, "commit": commit, "source": source, "mode": mode}


def _surface_counts(declared: int, loaded: int | None) -> dict[str, int | None]:
    return {"declared": declared, "loaded": loaded}


def _plugin_configs() -> list[Any]:
    """Return the loaded TapPluginConfig instances, sorted by slug (label)."""
    from django.apps import apps

    from tap_plugins.base import TapPluginConfig

    configs = [ac for ac in apps.get_app_configs() if isinstance(ac, TapPluginConfig)]
    return sorted(configs, key=lambda ac: ac.label)


def get_plugin_report() -> dict[str, Any]:
    """Capability-gated service entry for the plugin report — authorize, then build.

    The web/UI path (the administrivia plugin-status panel) routes THROUGH here, not
    through ``build_report()`` directly, so the ``plugins.read`` capability is enforced in
    the service layer (the single gate point the discipline calls for) — not per-panel.
    Raises ``AuthzError`` for a caller lacking ``plugins.read`` (propagates to a clean 403
    at the panel view). The plugin registry is the instance's software bill of materials,
    so it sits above ``grid.read``.

    ``build_report()`` remains the ungated pure builder for the trusted CLI
    (``manage.py plugins``), matching the ``manage.py health`` convention.

    NOTE (forward-compat): once the in-flight service-layer refactor routes all grid /
    sub-grid reads through the service layer with capability gating there, this explicit
    authorize + the direct ``EntityType`` read inside ``build_report()`` converge on that
    gate; this wrapper is the seam that makes that a swap-behind-the-interface.
    """
    from tap_auth import policy
    from tap_grid.caller_context import get_caller_context

    policy.authorize(get_caller_context(), "plugins.read", operation="plugin_report")
    return build_report()


def build_report() -> dict[str, Any]:
    """Build the validated plugin report (see module docstring + the JSON schema).

    Returns a dict conforming to ``plugin-report.schema.json``. Read-only: no grid writes.
    """
    from tap_grid.models import EntityType

    configs = _plugin_configs()

    # First pass: identity + declared deps (needed to invert into required_by).
    declared_by_slug: dict[str, list[plugin_deps.DeclaredDep]] = {}
    observed_by_slug: dict[str, set[str]] = {}
    for ac in configs:
        pkg_dir = Path(ac.path)
        declared_by_slug[ac.label] = plugin_deps.read_declared_depends_on(pkg_dir)
        observed_by_slug[ac.label] = plugin_deps.scan_observed_imports(pkg_dir, ac.label)

    # Invert declared edges → required_by (who depends on X).
    required_by: dict[str, list[str]] = {slug: [] for slug in declared_by_slug}
    for slug, deps in declared_by_slug.items():
        for dep in deps:
            required_by.setdefault(dep.slug, [])
            required_by[dep.slug].append(slug)

    # All registered EntityType slugs (for declared-vs-loaded surface counts). We check
    # global registration, NOT plugin_name ownership: a plugin may DECLARE a type it
    # reuses from core (e.g. aws_core declaring the core CONTAINS/PROTECTS edges), which
    # registers under core, not the plugin. "Loaded" answers "did the declared type
    # register at all" — a declared>loaded gap is then a genuine load failure, not a
    # false alarm on legitimate core-reuse.
    registered_slugs: set[str] = set(EntityType.objects.all().values_list("slug", flat=True))

    plugins: list[dict[str, Any]] = []
    for ac in configs:
        slug = ac.label
        manifest = getattr(ac, "_manifest", None)
        prov = _provenance(dist_name_for_slug(slug))

        declared = declared_by_slug[slug]
        observed = observed_by_slug[slug]
        declared_slugs = {d.slug for d in declared}
        depends_on = sorted(declared_slugs)
        undeclared = sorted(observed - declared_slugs)

        # Declared surface counts from the manifest.
        if manifest is not None:
            model_slugs = {m.slug for m in manifest.models}
            edge_slugs = {e.slug for e in manifest.edges}
            n_models, n_edges = len(model_slugs), len(edge_slugs)
            n_editors, n_searches, n_grift = len(manifest.editors), len(manifest.searches), len(manifest.grift)
            name = manifest.name
            manifest_valid = True
        else:
            model_slugs, edge_slugs = set(), set()
            n_models = n_edges = n_editors = n_searches = n_grift = 0
            name = ac.verbose_name or slug
            manifest_valid = False

        # Loaded surface counts: declared model/edge slugs that are registered (anywhere).
        loaded_models = len(model_slugs & registered_slugs)
        loaded_edges = len(edge_slugs & registered_slugs)

        plugins.append(
            {
                "slug": slug,
                "name": name,
                "distribution": dist_name_for_slug(slug),
                "version": prov["version"],
                "commit": prov["commit"],
                "source": prov["source"],
                "mode": prov["mode"],
                "app_config": f"{type(ac).__module__}.{type(ac).__qualname__}",
                "load_health": {
                    "loaded": True,
                    "manifest_valid": manifest_valid,
                    "detail": "" if manifest_valid else "manifest not loaded on AppConfig",
                },
                "surfaces": {
                    "models": _surface_counts(n_models, loaded_models),
                    "edges": _surface_counts(n_edges, loaded_edges),
                    "editors": _surface_counts(n_editors, None),
                    "searches": _surface_counts(n_searches, None),
                    "grift": _surface_counts(n_grift, None),
                },
                "dependencies": {
                    "depends_on": depends_on,
                    "required_by": sorted(required_by.get(slug, [])),
                    "observed_imports": sorted(observed),
                    "undeclared_imports": undeclared,
                    "declared_detail": [
                        {
                            "slug": d.slug,
                            "min_version": d.min_version,
                            "optional": d.optional,
                            "note": _note_for(manifest, d.slug),
                        }
                        for d in declared
                    ],
                },
            }
        )

    report = {"schema_version": SCHEMA_VERSION, "plugin_count": len(plugins), "plugins": plugins}
    validate_json(report, SCHEMA_PATH, source="plugin-report")
    return report


def _note_for(manifest: Any, dep_slug: str) -> str:
    """Pull the intent note for a declared dependency from the full manifest, if present."""
    if manifest is None:
        return ""
    for entry in getattr(manifest, "depends_on", []):
        if entry.slug == dep_slug:
            return str(entry.note)
    return ""
