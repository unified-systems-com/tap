"""Plugin manifest reader and validator for tap-plugin.toml.

Implements req-tap-plugin-manifest-v0-* from spec-tap-plugin-manifest-v0.md.

Public API:
    load_manifest(plugin_root) -> PluginManifest
    validate_manifest_classes(manifest) -> None
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tap.boot_records import BootRecordManifestError, declared_record_digests
from tap.jsonfiles import JsonFileError, load_json_file, load_schema

logger = logging.getLogger(__name__)

_ALLOWED_TOP_KEYS = {
    "manifest_version",
    "plugin_version",
    "slug",
    "name",
    "description",
    "requires_tap",
    "depends_on",
    "models",
    "edges",
    "editors",
    "searches",
    "grift",
    "boot",
    "fips",
}
_DEPENDS_ON_KEYS = {"slug", "min_version", "optional", "note"}
_BOOT_RECORD_KEYS = {"name", "description", "sha256"}
_FIPS_KEYS = {"status", "reason", "providers"}
_FIPS_STATUSES = {"compatible", "uses-nonvalidated"}
_REQUIRED_TOP_KEYS = {"manifest_version", "plugin_version", "slug", "name"}

_EDGE_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "tap_grid" / "schemas" / "edge-definition.schema.json"


def _load_edge_schema() -> dict[str, Any]:
    """Load and cache the edge definition JSON Schema."""
    return load_schema(_EDGE_SCHEMA_PATH)


class PluginManifestError(Exception):
    """Raised when a tap-plugin.toml is invalid or fails validation."""


@dataclass
class DependencyEntry:
    """One depends_on entry: a cross-plugin load-order dependency (Tier 1).

    Slug edge to another plugin the declaring plugin's ``ready()``-time type/edge
    registration (or import-time code) needs present first. ``min_version`` is an
    optional PEP 440 floor; ``optional`` marks a soft dependency (absence tolerated);
    ``note`` documents *why* the dependency exists (AI-/security-readable intent).
    See spec-tap-plugin-architecture.md req-tap-plugin-arch-dependencies-2.
    """

    slug: str
    min_version: str | None
    optional: bool
    note: str


@dataclass
class ModelEntry:
    """One [models] entry declaring a TAP-managed model type."""

    slug: str
    class_path: str


@dataclass
class EdgeEntry:
    """One [edges] entry + the parsed contents of its .edge.json file."""

    slug: str
    file_path: str  # relative to plugin root
    name: str
    description: str
    sources: list[str] | None  # None = wildcard
    targets: list[str] | None  # None = wildcard
    property_schema: dict[str, Any] | None
    default_dimensions: dict[str, Any] | None


@dataclass
class EditorEntry:
    """One [editors] entry declaring an editor descriptor."""

    entity_type: str
    class_path: str


@dataclass
class SearchEntry:
    """One [searches] entry declaring a search runner callable."""

    runner_key: str
    callable_path: str


@dataclass
class GriftEntry:
    """One [grift] entry declaring a bundled GRIFT data file."""

    name: str
    path: str


@dataclass
class BootRecordEntry:
    """One [[boot.records]] entry: a shippable boot record enumerated in the manifest.

    The record itself lives at ``tap_plugin/<slug>/boot/<name>.boot.json`` and rides the
    artifact (``req-boot-bootstrap-records-in-package``). The manifest is the *index* of
    the records (``req-boot-bootstrap-discovery``): ``name`` is the ``#<record>`` selector,
    ``description`` the short flavor label, and ``sha256`` the referrer-held integrity digest
    (``req-boot-bootstrap-record-version``) — machine-managed by ``scripts/boot-record-hash``
    and enforced against the record's content by the ``tap/tests/test_boot_records.py`` guard.
    There is deliberately no per-record version: a record's version is the plugin's.
    """

    name: str
    description: str
    sha256: str


@dataclass
class FipsDeclaration:
    """The plugin author's declared FIPS crypto posture (the ``[fips]`` table).

    A FACTUAL declaration that the crypto-BOM conformance scan VERIFIES — not a permission. A plugin
    cannot excuse itself from a deployment's FIPS posture; only the operator waives (the boot profile's
    ``fips_waivers``). This is the "declare" half of declare-vs-decide (``req-fips-crypto-bom``):

    - ``status = "compatible"`` — the plugin claims it uses only FIPS-validated crypto (the system
      OpenSSL #4282 provider). If the conformance scan finds a non-validated provider the plugin
      ships/pulls, conformance FAILS: the declaration is false.
    - ``status = "uses-nonvalidated"`` — the honest acknowledgement that the plugin uses non-FIPS
      crypto. Requires a ``reason`` (the author's justification, mandatory — mirrors the operator
      waiver's required reason). Conformance PASSES (it is honest), but a FIPS-mode system still needs
      an operator waiver to run it. ``providers`` optionally names the specific non-validated providers
      the author acknowledges (e.g. ``["libsodium"]``), for precision + legibility.

    Absent ``[fips]`` = undeclared: the scan still runs, and a detected non-validated provider is a
    conformance *warning* (declare it), never assumed compatible. See ``req-tap-plugin-manifest-v0-fips``.
    """

    status: str
    reason: str | None
    providers: list[str]


@dataclass
class PluginManifest:
    """Parsed and validated contents of a tap-plugin.toml file."""

    manifest_version: str
    plugin_version: str
    slug: str
    name: str
    description: str
    requires_tap: str | None
    depends_on: list[DependencyEntry]
    models: list[ModelEntry]
    edges: list[EdgeEntry]
    editors: list[EditorEntry]
    searches: list[SearchEntry]
    grift: list[GriftEntry]
    boot_records: list[BootRecordEntry]
    fips: FipsDeclaration | None
    plugin_root: Path


def load_manifest(plugin_root: Path) -> PluginManifest:
    """Load, parse, and validate tap-plugin.toml at *plugin_root*.

    Args:
        plugin_root: Absolute path to the plugin root directory.

    Returns:
        A validated PluginManifest.

    Raises:
        PluginManifestError: If the manifest is missing, malformed, or fails validation.
    """
    manifest_path = plugin_root / "tap-plugin.toml"
    if not manifest_path.exists():
        raise PluginManifestError(f"Missing tap-plugin.toml at {plugin_root}")

    try:
        with open(manifest_path, "rb") as fh:
            raw: dict[str, Any] = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise PluginManifestError(f"tap-plugin.toml is not valid TOML: {exc}") from exc

    _validate_top_level(raw, manifest_path)

    requires_tap = _parse_requires_tap(raw.get("requires_tap"), manifest_path)
    depends_on = _parse_depends_on(raw.get("depends_on", []), raw["slug"], manifest_path)
    models = _parse_models(raw.get("models", {}), manifest_path)
    edges = _parse_edges(raw.get("edges", {}), manifest_path, plugin_root)
    editors = _parse_editors(raw.get("editors", {}), manifest_path)
    searches = _parse_searches(raw.get("searches", {}), manifest_path)
    grift = _parse_grift(raw.get("grift", {}), manifest_path)
    boot_records = _parse_boot_records(raw.get("boot", {}), manifest_path)
    fips = _parse_fips(raw.get("fips"), manifest_path)

    manifest = PluginManifest(
        manifest_version=raw["manifest_version"],
        plugin_version=raw["plugin_version"],
        slug=raw["slug"],
        name=raw["name"],
        description=raw.get("description", ""),
        requires_tap=requires_tap,
        depends_on=depends_on,
        models=models,
        edges=edges,
        editors=editors,
        searches=searches,
        grift=grift,
        boot_records=boot_records,
        fips=fips,
        plugin_root=plugin_root,
    )

    _validate_convention_dirs(manifest)
    _validate_grift_paths(manifest)

    return manifest


# ---------------------------------------------------------------------------
# Section parsers
# ---------------------------------------------------------------------------


def _parse_requires_tap(raw_value: Any, manifest_path: Path) -> str | None:
    """Parse the optional top-level ``requires_tap`` compatibility floor.

    A PEP 440 version specifier string (e.g. ``">=0.1,<0.2"``) naming the range of
    core (``tap``) versions this plugin supports. Absent → None (no declared floor,
    allowed in v0). A malformed specifier is a hard manifest error — the shared
    validator in ``tap.core_version`` is the single specifier-parsing implementation,
    reused by the pre-boot compatibility gate. See ``req-tap-plugin-extdev-compat-floor``.
    """
    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value:
        raise PluginManifestError(f"'requires_tap' must be a non-empty string in {manifest_path}")

    from tap.core_version import parse_requires_tap

    try:
        parse_requires_tap(raw_value, source=str(manifest_path))
    except ValueError as exc:
        raise PluginManifestError(str(exc)) from exc
    return raw_value


def _parse_depends_on(raw_deps: Any, own_slug: str, manifest_path: Path) -> list[DependencyEntry]:
    """Parse the optional ``depends_on`` array of tables (Tier 1 load-order edges).

    Each entry is a table: required ``slug``; optional ``min_version`` (PEP 440 floor),
    ``optional`` (bool, default false), and ``note`` (free-text intent). A plugin may
    not depend on itself. The consistency gate (``tap.preboot``) checks these declared
    edges against the observed cross-plugin imports and the profile install order.
    """
    if not isinstance(raw_deps, list):
        raise PluginManifestError(f"'depends_on' must be an array of tables in {manifest_path}")

    entries: list[DependencyEntry] = []
    seen: set[str] = set()
    for item in raw_deps:
        if not isinstance(item, dict):
            raise PluginManifestError(f"each depends_on entry must be a table with a 'slug' key in {manifest_path}")
        unknown = set(item) - _DEPENDS_ON_KEYS
        if unknown:
            raise PluginManifestError(f"depends_on entry has unknown keys {sorted(unknown)} in {manifest_path}")

        slug = item.get("slug")
        if not isinstance(slug, str) or not slug:
            raise PluginManifestError(f"depends_on entry must have a non-empty string 'slug' in {manifest_path}")
        if slug == own_slug:
            raise PluginManifestError(f"depends_on: plugin '{own_slug}' cannot depend on itself in {manifest_path}")
        if slug in seen:
            raise PluginManifestError(f"duplicate depends_on slug '{slug}' in {manifest_path}")
        seen.add(slug)

        min_version = item.get("min_version")
        if min_version is not None and (not isinstance(min_version, str) or not min_version):
            raise PluginManifestError(f"depends_on.{slug}.min_version must be a non-empty string in {manifest_path}")

        optional = item.get("optional", False)
        if not isinstance(optional, bool):
            raise PluginManifestError(f"depends_on.{slug}.optional must be a boolean in {manifest_path}")

        note = item.get("note", "")
        if not isinstance(note, str):
            raise PluginManifestError(f"depends_on.{slug}.note must be a string in {manifest_path}")

        entries.append(DependencyEntry(slug=slug, min_version=min_version, optional=optional, note=note))

    return entries


def _parse_models(raw_models: Any, manifest_path: Path) -> list[ModelEntry]:
    if not isinstance(raw_models, dict):
        raise PluginManifestError(f"'models' must be a table in {manifest_path}")

    entries: list[ModelEntry] = []
    for slug, class_path in raw_models.items():
        if not isinstance(class_path, str) or not class_path:
            raise PluginManifestError(f"models.{slug} must be a non-empty string class path in {manifest_path}")
        entries.append(ModelEntry(slug=slug, class_path=class_path))

    return entries


def _parse_edges(raw_edges: Any, manifest_path: Path, plugin_root: Path) -> list[EdgeEntry]:
    if not isinstance(raw_edges, dict):
        raise PluginManifestError(f"'edges' must be a table in {manifest_path}")

    seen_paths: set[str] = set()
    entries: list[EdgeEntry] = []

    for slug, rel_path in raw_edges.items():
        if not isinstance(rel_path, str) or not rel_path:
            raise PluginManifestError(f"edges.{slug} must be a non-empty string path in {manifest_path}")

        if ".." in Path(rel_path).parts:
            raise PluginManifestError(f"edges.{slug} path '{rel_path}' contains path traversal in {manifest_path}")

        if not rel_path.endswith(".edge.json"):
            raise PluginManifestError(
                f"edges.{slug} path '{rel_path}' must use the .edge.json extension in {manifest_path}"
            )

        if rel_path in seen_paths:
            raise PluginManifestError(f"Duplicate edge file path '{rel_path}' in {manifest_path}")
        seen_paths.add(rel_path)

        full_path = plugin_root / rel_path
        if not full_path.exists():
            raise PluginManifestError(
                f"Declared edge path '{rel_path}' not found at {full_path} (plugin manifest: {manifest_path})"
            )

        entry = _load_edge_file(slug, rel_path, full_path, manifest_path)
        entries.append(entry)

    return entries


def _load_edge_file(
    manifest_slug: str,
    rel_path: str,
    full_path: Path,
    manifest_path: Path,
) -> EdgeEntry:
    try:
        data: dict[str, Any] = load_json_file(full_path, schema=_load_edge_schema())
    except JsonFileError as exc:
        raise PluginManifestError(f"Edge file '{rel_path}': {exc}") from exc

    # Slug must match the manifest key.
    file_slug = data["slug"]
    if file_slug != manifest_slug:
        raise PluginManifestError(
            f"Edge file '{rel_path}' slug '{file_slug}' does not match manifest key '{manifest_slug}'"
        )

    return EdgeEntry(
        slug=file_slug,
        file_path=rel_path,
        name=data["name"],
        description=data["description"],
        sources=data.get("sources"),
        targets=data.get("targets"),
        property_schema=data.get("property_schema"),
        default_dimensions=data.get("default_dimensions"),
    )


def _parse_editors(raw_editors: Any, manifest_path: Path) -> list[EditorEntry]:
    if not isinstance(raw_editors, dict):
        raise PluginManifestError(f"'editors' must be a table in {manifest_path}")

    entries: list[EditorEntry] = []
    for entity_type, class_path in raw_editors.items():
        if not isinstance(class_path, str) or not class_path:
            raise PluginManifestError(f"editors.{entity_type} must be a non-empty string class path in {manifest_path}")
        entries.append(EditorEntry(entity_type=entity_type, class_path=class_path))

    return entries


def _parse_searches(raw_searches: Any, manifest_path: Path) -> list[SearchEntry]:
    if not isinstance(raw_searches, dict):
        raise PluginManifestError(f"'searches' must be a table in {manifest_path}")

    entries: list[SearchEntry] = []
    for runner_key, callable_path in raw_searches.items():
        if not isinstance(callable_path, str) or not callable_path:
            raise PluginManifestError(
                f"searches.{runner_key} must be a non-empty string callable path in {manifest_path}"
            )
        entries.append(SearchEntry(runner_key=runner_key, callable_path=callable_path))

    return entries


def _parse_grift(raw_grift: Any, manifest_path: Path) -> list[GriftEntry]:
    if not isinstance(raw_grift, dict):
        raise PluginManifestError(f"'grift' must be a table in {manifest_path}")

    seen_paths: set[str] = set()
    entries: list[GriftEntry] = []

    for name, path in raw_grift.items():
        if not isinstance(path, str) or not path:
            raise PluginManifestError(f"grift.{name} must be a non-empty string path in {manifest_path}")

        if ".." in Path(path).parts:
            raise PluginManifestError(f"grift.{name} path '{path}' contains path traversal in {manifest_path}")

        if path in seen_paths:
            raise PluginManifestError(f"Duplicate GRIFT bundle path '{path}' in {manifest_path}")
        seen_paths.add(path)

        entries.append(GriftEntry(name=name, path=path))

    return entries


def _parse_boot_records(raw_boot: Any, manifest_path: Path) -> list[BootRecordEntry]:
    """Parse the optional ``[boot]`` table's ``records`` array (``req-boot-bootstrap-discovery``).

    Each ``[[boot.records]]`` entry requires a non-empty ``name`` (the ``#<record>`` selector,
    unique) and ``description`` (json-structures-require-descriptions), plus a ``sha256`` string
    (the referrer-held integrity digest). ``sha256`` may be empty here — an empty/placeholder
    digest is a *structural* pass but an *integrity* failure caught by the boot-records guard;
    this validator owns shape, the guard owns content. The record files' presence/coherence is
    likewise the guard's job (it sees the filesystem; this parser sees only the manifest).
    """
    if not isinstance(raw_boot, dict):
        raise PluginManifestError(f"'boot' must be a table in {manifest_path}")
    # Name/duplicate/sha256 structure is the shared declared-digest parse
    # (tap.boot_records.declared_record_digests — the same semantics the stage-0
    # integrity gate and the coherence guard apply); this validator adds the
    # manifest-only checks on top: unknown keys and the description contract.
    try:
        digests = declared_record_digests({"boot": raw_boot})
    except BootRecordManifestError as exc:
        raise PluginManifestError(f"{exc} in {manifest_path}") from exc

    entries: list[BootRecordEntry] = []
    for item in raw_boot.get("records", []):
        unknown = set(item) - _BOOT_RECORD_KEYS
        if unknown:
            raise PluginManifestError(f"boot.records entry has unknown keys {sorted(unknown)} in {manifest_path}")

        name = item["name"]
        description = item.get("description")
        if not isinstance(description, str) or not description:
            raise PluginManifestError(
                f"boot.records '{name}' must have a non-empty string 'description' in {manifest_path}"
            )

        entries.append(BootRecordEntry(name=name, description=description, sha256=digests[name]))

    return entries


def _parse_fips(raw_value: Any, manifest_path: Path) -> FipsDeclaration | None:
    """Parse the optional ``[fips]`` table — the author's declared crypto posture (req-tap-plugin-manifest-v0-fips).

    ``status`` is required and must be ``compatible`` or ``uses-nonvalidated``. A ``reason`` is
    MANDATORY (non-empty) when ``status = "uses-nonvalidated"`` — an author acknowledging non-FIPS
    crypto must justify it, the same discipline the operator waiver requires. ``providers`` is an
    optional list of the specific non-validated provider names acknowledged.
    """
    if raw_value is None:
        return None
    if not isinstance(raw_value, dict):
        raise PluginManifestError(f"'fips' must be a table in {manifest_path}")

    unknown = set(raw_value) - _FIPS_KEYS
    if unknown:
        raise PluginManifestError(f"fips table has unknown keys {sorted(unknown)} in {manifest_path}")

    status = raw_value.get("status")
    if status not in _FIPS_STATUSES:
        raise PluginManifestError(f"fips.status must be one of {sorted(_FIPS_STATUSES)} in {manifest_path}")

    reason = raw_value.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise PluginManifestError(f"fips.reason must be a string in {manifest_path}")
    if status == "uses-nonvalidated" and (not isinstance(reason, str) or not reason.strip()):
        raise PluginManifestError(
            f"fips.reason is required (non-empty) when status='uses-nonvalidated' in {manifest_path} — "
            "a plugin acknowledging non-FIPS crypto must justify it"
        )

    providers = raw_value.get("providers", [])
    if not isinstance(providers, list) or not all(isinstance(p, str) and p for p in providers):
        raise PluginManifestError(f"fips.providers must be a list of non-empty strings in {manifest_path}")

    return FipsDeclaration(
        status=status,
        reason=reason.strip() if isinstance(reason, str) and reason.strip() else None,
        providers=list(providers),
    )


# ---------------------------------------------------------------------------
# Directory and path validators
# ---------------------------------------------------------------------------


def _validate_top_level(raw: dict[str, Any], manifest_path: Path) -> None:
    unknown = set(raw.keys()) - _ALLOWED_TOP_KEYS
    if unknown:
        raise PluginManifestError(f"Unknown top-level keys in {manifest_path}: {sorted(unknown)}")

    for key in _REQUIRED_TOP_KEYS:
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            raise PluginManifestError(f"Required field '{key}' must be a non-empty string in {manifest_path}")

    if raw["manifest_version"] != "0":
        raise PluginManifestError(
            f"Unsupported manifest_version '{raw['manifest_version']}' in {manifest_path}; expected '0'"
        )


def _validate_convention_dirs(manifest: PluginManifest) -> None:
    """Validate that convention directories exist when the corresponding surface is declared."""
    checks = [
        (manifest.models, "models"),
        (manifest.edges, "edges"),
        (manifest.searches, "searches"),
        (manifest.grift, "grift"),
    ]
    for entries, dirname in checks:
        if not entries:
            continue
        dir_path = manifest.plugin_root / dirname
        if not dir_path.is_dir():
            raise PluginManifestError(
                f"Plugin '{manifest.slug}' declares [{dirname}] but is missing "
                f"required '{dirname}/' directory at {manifest.plugin_root}"
            )


def _validate_grift_paths(manifest: PluginManifest) -> None:
    for entry in manifest.grift:
        full_path = manifest.plugin_root / entry.path
        if not full_path.exists():
            raise PluginManifestError(
                f"Declared GRIFT path '{entry.path}' not found at {full_path} " f"(plugin '{manifest.slug}')"
            )


# ---------------------------------------------------------------------------
# Runtime class validation (called after Django app registry is ready)
# ---------------------------------------------------------------------------


def validate_manifest_classes(manifest: PluginManifest) -> None:
    """Validate model, editor, and search callable classes declared in the manifest.

    Called during plugin startup after the Django app registry is ready.

    Args:
        manifest: A loaded PluginManifest.

    Raises:
        PluginManifestError: If any declared class cannot be imported or fails contract checks.
    """
    _validate_model_classes(manifest)
    _validate_editor_classes(manifest)
    _validate_search_callables(manifest)


def _validate_model_classes(manifest: PluginManifest) -> None:
    from django.utils.module_loading import import_string

    for entry in manifest.models:
        try:
            cls = import_string(entry.class_path)
        except ImportError as exc:
            raise PluginManifestError(
                f"Cannot import model class '{entry.class_path}' declared in plugin '{manifest.slug}': {exc}"
            ) from exc

        entity_type = getattr(cls, "ENTITY_TYPE", None)
        if entity_type != entry.slug:
            raise PluginManifestError(
                f"Model class '{entry.class_path}' has ENTITY_TYPE='{entity_type}' "
                f"but manifest declares slug='{entry.slug}' in plugin '{manifest.slug}'"
            )


def _validate_editor_classes(manifest: PluginManifest) -> None:
    from django.utils.module_loading import import_string

    from tap_web.editor import EditorDescriptor

    for entry in manifest.editors:
        try:
            cls = import_string(entry.class_path)
        except ImportError as exc:
            raise PluginManifestError(
                f"Cannot import editor class '{entry.class_path}' declared in plugin '{manifest.slug}': {exc}"
            ) from exc

        try:
            instance = cls()
        except Exception as exc:
            raise PluginManifestError(
                f"Editor class '{entry.class_path}' could not be instantiated in plugin '{manifest.slug}': {exc}"
            ) from exc

        if not isinstance(instance, EditorDescriptor):
            raise PluginManifestError(
                f"Editor class '{entry.class_path}' is not an EditorDescriptor subclass " f"in plugin '{manifest.slug}'"
            )

        if instance.entity_type != entry.entity_type:
            raise PluginManifestError(
                f"Editor class '{entry.class_path}' has entity_type='{instance.entity_type}' "
                f"but manifest declares '{entry.entity_type}' in plugin '{manifest.slug}'"
            )


def _validate_search_callables(manifest: PluginManifest) -> None:
    from django.utils.module_loading import import_string

    for entry in manifest.searches:
        try:
            obj = import_string(entry.callable_path)
        except ImportError as exc:
            raise PluginManifestError(
                f"Cannot import search callable '{entry.callable_path}' declared in plugin '{manifest.slug}': {exc}"
            ) from exc

        if not callable(obj):
            raise PluginManifestError(
                f"Search entry '{entry.runner_key}' resolves to a non-callable "
                f"'{entry.callable_path}' in plugin '{manifest.slug}'"
            )


# ---------------------------------------------------------------------------
# Undeclared file warnings
# ---------------------------------------------------------------------------


def warn_undeclared_convention_files(manifest: PluginManifest) -> None:
    """Warn about files in convention directories that are not declared in the manifest."""
    declared_grift_paths = {entry.path for entry in manifest.grift}
    declared_edge_paths = {entry.file_path for entry in manifest.edges}

    grift_dir = manifest.plugin_root / "grift"
    if grift_dir.is_dir():
        for grift_file in grift_dir.rglob("*.grift.json"):
            rel = str(grift_file.relative_to(manifest.plugin_root))
            if rel not in declared_grift_paths:
                logger.warning(
                    "[5fcb] Plugin '%s': undeclared GRIFT file '%s' in grift/ — not part of load contract",
                    manifest.slug,
                    rel,
                )

    edges_dir = manifest.plugin_root / "edges"
    if edges_dir.is_dir():
        for edge_file in edges_dir.glob("*.edge.json"):
            rel = str(edge_file.relative_to(manifest.plugin_root))
            if rel not in declared_edge_paths:
                logger.warning(
                    "[924b] Plugin '%s': undeclared edge file '%s' in edges/ — not part of load contract",
                    manifest.slug,
                    rel,
                )
