"""Settings-free pre-boot stage: install package-mode plugins, snapshot the DB.

This module runs in ``docker/entrypoint.sh`` BEFORE Django reads settings — it is
what *generates* ``TAP_PLUGINS`` (which settings then consumes), so it cannot be a
Django app or a ``manage.py`` command. It is deliberately import-safe and
``django``-free (`req-boot-preboot-1`): it reads the boot profile as plain JSON and
talks to the environment directly. ``tap_boot`` owns the profile *contract*
(the schema + the population reader); ``tap/`` *executes* the pre-Django phases —
the Kubernetes ``initContainers`` shape (`req-boot-preboot-2`).

Order (`req-boot-preboot`): resolve the snapshot switch → install the profile's
``install`` plugins (idempotent) → discover their entry points into ``TAP_PLUGINS``
→ static coherence guard → pre-migrate snapshot. Any failure is fatal and aborts
before ``migrate`` runs, leaving the database untouched (`req-boot-preboot-4`).

CLI: ``python -m tap.preboot --profile <id>``. Human/progress output goes to
stderr; the single ``TAP_PLUGINS`` value is printed to stdout (last line) so the
entrypoint can capture it with ``TAP_PLUGINS="$(python -m tap.preboot ...)"``.

Spec: specs/spec-tap-boot-v0.md (`req-boot-preboot`, `req-boot-install-section`,
`req-boot-snapshot`, `req-boot-variable-resolution`, `req-boot-idempotent-3`).
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from tap import plugin_deps
from tap.boot_naming import profile_path, step_enabled
from tap.logging import abort
from tap.plugin_identity import NAMESPACE_PACKAGE as NAMESPACE_PACKAGE
from tap.plugin_identity import TAP_PLUGINS_ENTRY_POINT_GROUP as TAP_PLUGINS_ENTRY_POINT_GROUP
from tap.plugin_identity import dist_name_for_slug as dist_name_for_slug
from tap.plugin_source_auth import GitCredential, SourceAuthError, git_askpass_env, resolve_git_credential

logger = logging.getLogger(__name__)

# Narrow, declared public surface. pre-boot is an un-gateable Family-B layer
# (spec-service-layer-boundary): it runs before Django/settings and before the
# capability system exists, so it cannot be gated — its defense is a small, explicit
# public surface. `__all__` is that surface; the public-surface ceiling ratchet
# (tap/guards/public_surface.py) freezes it and only lets it shrink. It lists what an
# external module genuinely imports (settings → discover_entry_points; tap_plugins →
# dist_name_for_slug / NAMESPACE_PACKAGE / TAP_PLUGINS_ENTRY_POINT_GROUP /
# direct_url_vcs_rev, the one PEP 610 rev derivation shared with tap_plugins.report) plus the CLI
# orchestration entry (run_preboot / main) and the fatal-condition contract
# (PrebootError), plus the boot-variable resolver trio (ResolvedVar / env_var_name /
# resolve_var) — the shape req-boot-variable-resolution-4 reserved for post-Django
# reuse, consumed by tap_boot's collector-preflight toggle (req-boot-obs-preflight).
# Every other helper — install, is-satisfied, uv-install-args, the
# identity / reconciliation / dependency / coherence guards, snapshot — is `_`-sealed.
# Leaked surface is zero; the ceiling ratchet holds it there.
__all__ = [
    "PrebootError",
    "ResolvedVar",
    "env_var_name",
    "resolve_var",
    "NAMESPACE_PACKAGE",
    "TAP_PLUGINS_ENTRY_POINT_GROUP",
    "dist_name_for_slug",
    "direct_url_vcs_rev",
    "discover_entry_points",
    "resolved_plugin_app_configs",
    "run_preboot",
    "main",
]

# Repo root = the directory that holds `tap/` and `boot/`. tap/preboot.py lives at
# <root>/tap/preboot.py, so two parents up is the root. Settings-free — no BASE_DIR.
REPO_ROOT = Path(__file__).resolve().parent.parent

# --- Build-baked plugin transition set ---------------------------------------
# Plugins still hardcoded in settings.INSTALLED_APPS (not yet package-mode). The
# static coherence guard treats these as "available" without an `install` entry so
# a legacy profile whose population names build-baked plugins still passes.
#
# EMPTY as of 2026-07-02: the initial plugin migration is COMPLETE. Every shipped
# plugin (the samsite set + gryphon_playground) is package-mode (`tap_plugin.<slug>`),
# installed via a profile `install` section and discovered through its `tap.plugins`
# entry point. No plugin is hardcoded in INSTALLED_APPS anymore, so this set is empty
# (a future re-introduced build-baked plugin would re-add its slug here). Kept honest
# against settings by tap/tests/test_preboot.py::test_build_baked_matches_installed_apps
# (which now asserts the empty set equals zero hardcoded `plugins.*` INSTALLED_APPS entries).
BUILD_BAKED_PLUGIN_SLUGS: frozenset[str] = frozenset()

# TAP_PLUGINS_ENTRY_POINT_GROUP / NAMESPACE_PACKAGE / dist_name_for_slug are DEFINED in
# tap/plugin_identity.py (stdlib-only) and re-exported above, so the conformance gate can
# import them without pulling this module's Django-bearing dependency chain. They remain
# part of this module's public surface — callers need not care where they live.


class PrebootError(Exception):
    """Raised on any fatal pre-boot condition. Aborts the standup before migrate."""


# =============================================================================
# Boot-variable resolution (req-boot-variable-resolution)
# =============================================================================


@dataclass(frozen=True)
class ResolvedVar:
    """A resolved boot variable plus the provenance of the winning value."""

    value: Any
    source: str  # "env" | "profile" | "default"  (flag layer reserved)


def env_var_name(section: str, key: str) -> str:
    """Systematic env mapping ``TAP_BOOT_<SECTION>__<KEY>`` (`req-boot-variable-resolution-2`)."""
    return f"TAP_BOOT_{section.upper()}__{key.upper()}"


def _coerce_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resolve_var(
    section: str,
    key: str,
    *,
    profile_section: dict[str, Any] | None,
    default: Any,
    is_bool: bool = False,
) -> ResolvedVar:
    """Resolve a boot variable by the precedence ladder (`req-boot-variable-resolution-1`).

    Precedence: flag > env > profile > default. The flag layer is reserved for the
    MVP (no CLI-flag override yet), so the effective ladder is env > profile > default.
    Resolve-once: this returns a single effective value plus its source so the caller
    records it (no silent profile divergence, `req-boot-variable-resolution-3`).
    """
    env_name = env_var_name(section, key)
    raw_env = os.environ.get(env_name)
    # An empty/whitespace-only env value means "unset" — docker-compose materializes
    # an unmapped ${VAR:-} as "" in the container, and that must NOT read as a real
    # override (else a prod standup that leaves the var unset would parse "" as False
    # and silently disable the snapshot). Fall through to profile/default.
    if raw_env is not None and raw_env.strip() != "":
        value = _coerce_bool(raw_env) if is_bool else raw_env
        return ResolvedVar(value, "env")

    if profile_section is not None and key in profile_section:
        return ResolvedVar(profile_section[key], "profile")

    return ResolvedVar(default, "default")


# =============================================================================
# Profile reading (plain JSON, settings-free — req-boot-install-section-2)
# =============================================================================


def _boot_dir() -> Path:
    return REPO_ROOT / "boot"


def _read_profile(profile_id: str) -> dict[str, Any]:
    """Read ``boot/<profile_id>.boot.json`` as plain JSON (no Django, no schema).

    Pre-boot only needs the ``install`` section; it is consumed here as plain JSON
    before settings exist, not by a ``req-boot-sections`` handler (`req-boot-install-section-2`).
    Schema validation is the Django-side ``tap_boot.profile`` reader's job at boot.
    """
    path = profile_path(_boot_dir(), profile_id)
    if not path.is_file():
        raise PrebootError(f"boot profile '{profile_id}' not found at {path}")
    try:
        with open(path, "rb") as fh:
            data: dict[str, Any] = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise PrebootError(f"boot profile '{profile_id}' unreadable: {exc}") from exc
    return data


def _install_plugin_specs(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the enabled plugin entries from the ``install`` section (order preserved)."""
    install = profile.get("install") or {}
    return [p for p in install.get("plugins", []) if step_enabled(p)]


def _population_seed_slugs(profile: dict[str, Any]) -> list[str]:
    """Return enabled ``seed-plugin`` slugs from ``population`` (for the coherence guard)."""
    population = profile.get("population") or {}
    return [
        step["plugin"]
        for step in population.get("steps", [])
        if step.get("type") == "seed-plugin" and step_enabled(step)
    ]


# =============================================================================
# Plugin install (req-boot-install-section, req-boot-preboot-3 idempotency)
# =============================================================================


def _installed_distribution(dist_name: str) -> importlib.metadata.Distribution | None:
    try:
        return importlib.metadata.distribution(dist_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def direct_url_vcs_rev(info: dict[str, Any]) -> str | None:
    """The pinned commit of a parsed PEP 610 ``direct_url.json`` record, or None.

    ``commit_id`` (the resolved commit) with ``requested_revision`` fallback — the one
    derivation of install-provenance rev, shared with `tap_plugins.report` so the
    reboot-idempotency check (req-boot-preboot-3) and the install-registry report
    (req-tap-plugin-arch-install-registry-3) cannot drift on what "the pinned rev" means.
    Callers own file reading and error posture (preboot fails loud, report degrades).
    """
    vcs = info.get("vcs_info") or {}
    return vcs.get("commit_id") or vcs.get("requested_revision")


def _installed_git_rev(dist: importlib.metadata.Distribution) -> str | None:
    """Return the pinned commit id of a VCS install, or None if not a VCS install."""
    raw = dist.read_text("direct_url.json")
    if not raw:
        return None
    return direct_url_vcs_rev(json.loads(raw))


def _is_satisfied(entry: dict[str, Any]) -> bool:
    """True if the plugin is already installed to the requested source (`req-boot-preboot-3`).

    git: satisfied when the installed VCS commit matches the pinned rev (reboot no-op,
    no re-pull). wheelhouse: satisfied when the installed distribution is at the pinned
    version (install-by-version from immutable wheels — the filesystem twin of `index`).
    editable/path: satisfied when the distribution is present — an editable
    install is a live source link, so it needs no reinstall to pick up code changes.
    """
    slug = entry["slug"]
    source = entry["source"]
    dist = _installed_distribution(dist_name_for_slug(slug))
    if dist is None:
        return False
    if source["type"] == "git":
        return bool(_installed_git_rev(dist) == source["rev"])
    if source["type"] == "wheelhouse":
        return bool(dist.version == source["version"])
    return True  # editable / path: presence is enough


# The uv-pip target environment, passed explicitly (--python) on every install
# as the venv DIRECTORY — never the interpreter path, and never left to
# discovery. Both alternatives failed on the CodeBuild CI runner with the seeded
# venv (uv 0.12.x): discovery/VIRTUAL_ENV refused the venv outright ("No
# virtual environment found"), and `--python .venv/bin/python3` canonicalized
# the symlink chain (python3 -> python -> /usr/bin/python3) and silently
# installed into the SYSTEM environment — 12 plugins into /usr while the
# identity check read the venv (runs 31325649334/31326033361). The directory
# form pins the env root with no interpreter probing. The venv location is a
# stable contract (compose volume, entrypoint, uv project layout).
_VENV_DIR = REPO_ROOT / ".venv"


def _uv_pip_install() -> list[str]:
    """The common ``uv pip install`` prefix targeting the project venv explicitly."""
    return ["uv", "pip", "install", "--python", str(_VENV_DIR)]


def _uv_install_args(entry: dict[str, Any]) -> list[str]:
    """Build the ``uv pip install`` argument list for one plugin source."""
    source = entry["source"]
    stype = source["type"]
    if stype == "git":
        spec = f"{dist_name_for_slug(entry['slug'])} @ git+{source['url']}@{source['rev']}"
        return [*_uv_pip_install(), spec]
    if stype == "editable":
        return [*_uv_pip_install(), "--editable", str(REPO_ROOT / source["path"])]
    if stype == "path":
        return [*_uv_pip_install(), str(REPO_ROOT / source["path"])]
    if stype == "wheelhouse":
        # Offline / airgapped (req-tap-plugin-arch-sources-6): install by version from a
        # mounted directory of pre-built wheels. --no-index forbids PyPI so a missing
        # wheel (plugin or its Tier-0 deps) fails loud instead of silently fetching;
        # no network, no credential. The filesystem twin of the `index` path.
        find_links = _resolve_wheelhouse_dir(source["dir"])
        spec = f"{dist_name_for_slug(entry['slug'])}=={source['version']}"
        return [*_uv_pip_install(), "--no-index", "--find-links", str(find_links), spec]
    raise PrebootError(f"plugin '{entry['slug']}': unknown source type '{stype}'")


def _resolve_wheelhouse_dir(raw: str) -> Path:
    """Resolve a wheelhouse ``dir``: an absolute mount path as-is, else repo-relative.

    A real airgapped wheelhouse is an attached volume at an absolute path
    (e.g. ``/run/tap-wheelhouse``); a dev/local one can sit under the repo root.
    """
    candidate = Path(raw)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _secrets_root() -> Path | None:
    """The ``TAP_SECRETS_ROOT`` directory for pre-boot credential resolution, or None.

    Settings-free (`req-boot-preboot`): delegates to the canonical outside-Django
    lookup (`tap.secrets_root`, req-tap-cares-secrets-root-resolution), since Django
    is not configured yet. Absent ⇒ no source-credential store, so only
    public/editable/path sources can install (git sources that *declare* a credential
    then fail loud in :func:`_install_plugins`).
    """
    from tap.secrets_root import resolve

    return resolve()


def _run_install(args: list[str], cred: GitCredential | None) -> subprocess.CompletedProcess[str]:
    """Run one ``uv pip install``, feeding git credentials via ``GIT_ASKPASS`` when present.

    The token is passed to the child through the askpass env overlay only — never in
    ``args`` (which preboot logs) and never in the URL (`req-tap-plugin-arch-source-secret-4`).
    """
    # Scrub uv-run leakage from the child env: on the CI runner `uv run` launches
    # preboot WITHOUT activation env (no VIRTUAL_ENV, no venv-first PATH) while on
    # dev machines it sets both — inheriting that inconsistency gave uv-pip a
    # different environment-resolution starting point per machine. The child gets
    # ONLY the explicit --python target (see _VENV_DIR).
    child_env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "UV_RUN_RECURSION_DEPTH")}
    if cred is None:
        return subprocess.run(args, cwd=str(REPO_ROOT), capture_output=True, text=True, env=child_env)
    with git_askpass_env(cred) as overlay:
        return subprocess.run(args, cwd=str(REPO_ROOT), capture_output=True, text=True, env={**child_env, **overlay})


def _install_plugins(entries: list[dict[str, Any]]) -> None:
    """Install each enabled plugin, skipping any already satisfied (idempotent)."""
    secrets_root = _secrets_root()
    for entry in entries:
        slug = entry["slug"]
        if _is_satisfied(entry):
            logger.info("[a245] pre-boot install: '%s' already satisfied — no-op", slug)
            continue
        try:
            cred = resolve_git_credential(secrets_root, entry.get("source", {}))
        except SourceAuthError as exc:
            logger.error("[0d9b] pre-boot install: source credential error for '%s': %s", slug, exc)
            raise PrebootError(f"plugin '{slug}' source credential could not be resolved: {exc}") from exc
        if cred is not None:
            logger.info("[9934] pre-boot install: '%s' authenticating to %s as %s", slug, cred.host, cred.username)
        args = _uv_install_args(entry)
        logger.info("[a83c] pre-boot install: '%s' via %s", slug, " ".join(args))
        result = _run_install(args, cred)
        if result.returncode != 0:
            logger.error("[b1f5] pre-boot install FAILED for '%s': %s", slug, result.stderr.strip())
            raise PrebootError(f"plugin '{slug}' install failed (exit {result.returncode})")
        logger.info("[c5d5] pre-boot install: '%s' installed", slug)


# =============================================================================
# Entry-point discovery → TAP_PLUGINS (identity check: key == slug)
# =============================================================================


def discover_entry_points() -> dict[str, str]:
    """Map ``tap.plugins`` entry-point name (== slug) → AppConfig dotted path.

    Reads distribution metadata (entry_points.txt) — no package import needed, so a
    just-installed dist is visible in-process without its editable ``.pth`` being active.
    """
    importlib.invalidate_caches()
    discovered: dict[str, str] = {}
    # Scan the TARGET venv's site-packages explicitly (path=...) rather than this
    # process's sys.path view: on the CodeBuild runner, `uv run` launches preboot
    # without activation env, and installs are targeted at _VENV_DIR by flag — so
    # the only trustworthy statement of "what is installed" is the filesystem of
    # the environment we install into. distributions(path=...) builds fresh
    # Distribution objects with no FastPath caching of a stale earlier scan.
    for dist in importlib.metadata.distributions(path=_venv_site_packages()):
        for ep in dist.entry_points:
            if ep.group == TAP_PLUGINS_ENTRY_POINT_GROUP:
                discovered[ep.name] = ep.value.replace(":", ".")  # module:attr -> module.attr
    return discovered


# TAP_PLUGINS is authoritative. Pre-boot resolves the profile's package-mode set ONCE; the
# entrypoint exports it AND persists it here so sibling execs (manage.py boot,
# import_plugin_grift, pytest) that do not inherit the env var read the SAME set. Live
# entry-point discovery is a last-resort ONLY — importlib.metadata's mtime-based FastPath
# cache can disagree across processes, which let the migrate process and a boot process
# build different INSTALLED_APPS (a registered type with no migrated table — the
# plugin-loading race, 2026-08-11). Env override for tests; /run is tmpfs, rewritten every
# boot, so the file is never stale.
TAP_PLUGINS_FILE_DEFAULT = "/run/tap-plugins"


def resolved_plugin_app_configs() -> list[str]:
    """The authoritative package-mode plugin AppConfig paths for THIS process.

    Resolution order (TAP_PLUGINS-authoritative): the ``TAP_PLUGINS`` env var → the
    persisted copy the entrypoint wrote to ``TAP_PLUGINS_FILE`` → a warned last-resort
    live discovery for processes launched outside the entrypoint (a bare local
    ``manage.py``). Env/file preserve pre-boot's profile order; the discovery fallback
    sorts. Single-sourced so ``tap.settings`` (INSTALLED_APPS) and every other consumer
    resolve the identical set and cannot diverge.
    """
    env = os.environ.get("TAP_PLUGINS")
    if env is not None:
        return env.split()
    path = os.environ.get("TAP_PLUGINS_FILE", TAP_PLUGINS_FILE_DEFAULT)
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().split()
    except FileNotFoundError:
        pass
    logger.warning(
        "[3398] TAP_PLUGINS unset and no persisted set at %s — falling back to live "
        "entry-point discovery, which is NOT authoritative (importlib.metadata mtime-cache "
        "race). Launch via docker/entrypoint.sh or set TAP_PLUGINS.",
        path,
    )
    return sorted(discover_entry_points().values())


def _venv_site_packages() -> list[str]:
    """The target venv's site-packages dir(s), located on disk (never via sys.path)."""
    return [str(p) for p in sorted(_VENV_DIR.glob("lib/python*/site-packages"))]


def _resolve_tap_plugins(entries: list[dict[str, Any]], discovered: dict[str, str]) -> list[str]:
    """Return the AppConfig paths for the installed plugins, enforcing key == slug.

    Identity mismatch (a plugin whose entry-point key does not equal its declared
    slug, or that exposes no ``tap.plugins`` entry point) is fatal (`req-boot-preboot`).
    """
    app_configs: list[str] = []
    for entry in entries:
        slug = entry["slug"]
        if slug not in discovered:
            site_dirs = _venv_site_packages()
            dist_infos = sorted(p.name for d in site_dirs for p in Path(d).glob("*.dist-info"))
            raise PrebootError(
                f"plugin '{slug}' installed but exposes no '{TAP_PLUGINS_ENTRY_POINT_GROUP}' "
                f"entry point whose key equals the slug (identity mismatch). "
                f"Discovered keys: {sorted(discovered) or '(none)'}. "
                f"Scanned {site_dirs or '(no site-packages found)'}; "
                f"dist-infos present: {dist_infos or '(none)'}"
            )
        app_configs.append(discovered[slug])
    return app_configs


# =============================================================================
# Conformance gate (req-tap-plugin-arch-identity-5): dist == entry-key == namespace == manifest slug
# =============================================================================


def _namespace_segment(app_config_path: str) -> tuple[str, str]:
    """Split a dotted AppConfig path (``tap_plugin.<slug>.apps.<Cls>``) into (top, segment)."""
    parts = app_config_path.split(".")
    top = parts[0] if parts else ""
    segment = parts[1] if len(parts) > 1 else ""
    return top, segment


def _manifest_path_for(entry: dict[str, Any], dist: importlib.metadata.Distribution) -> Path:
    """Locate the plugin's shipped ``tap-plugin.toml`` WITHOUT importing the package.

    A just-installed editable package is not importable in the install process (its
    finder loads at interpreter startup, so ``find_spec`` misses it) — so we read the
    manifest from the filesystem instead. Mode-aware: editable/path installs read the
    source tree; git/index installs read the built copy the distribution shipped into
    site-packages (``dist.locate_file``). Both resolve to ``<pkg>/tap-plugin.toml``.
    """
    slug = entry["slug"]
    source = entry.get("source", {})
    if source.get("type") in ("editable", "path"):
        return REPO_ROOT / source["path"] / NAMESPACE_PACKAGE / slug / "tap-plugin.toml"
    return Path(str(dist.locate_file(f"{NAMESPACE_PACKAGE}/{slug}/tap-plugin.toml")))


def _read_manifest_slug(manifest_path: Path) -> str | None:
    """Read the ``slug`` field from a ``tap-plugin.toml`` at ``manifest_path``, or None."""
    import tomllib

    if not manifest_path.is_file():
        return None
    with open(manifest_path, "rb") as fh:
        loaded: dict[str, Any] = tomllib.load(fh)
    value = loaded.get("slug")
    return value if isinstance(value, str) else None


def _manifest_slug(entry: dict[str, Any], dist: importlib.metadata.Distribution) -> str | None:
    """Return the shipped manifest ``slug`` for an installed plugin — the "actual" side."""
    return _read_manifest_slug(_manifest_path_for(entry, dist))


def _read_manifest_requires_tap(manifest_path: Path) -> str | None:
    """Read the optional ``requires_tap`` field from a ``tap-plugin.toml``, or None.

    Raw ``tomllib`` read (no full manifest load / edge-schema import) — the same
    import-free discipline as ``_read_manifest_slug``, because the just-installed
    package is not importable in the install process.
    """
    import tomllib

    if not manifest_path.is_file():
        return None
    with open(manifest_path, "rb") as fh:
        loaded: dict[str, Any] = tomllib.load(fh)
    value = loaded.get("requires_tap")
    return value if isinstance(value, str) and value else None


def _conformance_gate(entries: list[dict[str, Any]], discovered: dict[str, str]) -> None:
    """Fail closed unless every plugin's four identities agree (`req-tap-plugin-arch-identity-5`).

    Distribution name (``tap-plugin-<slug>``), entry-point key, import namespace segment
    (``tap_plugin.<slug>``), and manifest ``slug`` must all equal the install slug. Owners
    set the namespace/dist/entry-point in their own package; TAP enforces agreement here —
    the "verify declared matches actual" backstop against typosquat/confusion for
    hand-authored or third-party plugins (the plugin-creation skill emits conformant ones).
    Runs after ``_resolve_tap_plugins`` (which already guarantees entry-point key == slug).
    """
    for entry in entries:
        slug = entry["slug"]
        app_config = discovered[slug]

        dist_name = dist_name_for_slug(slug)
        dist = _installed_distribution(dist_name)
        if dist is None:
            raise PrebootError(
                f"conformance gate: plugin '{slug}' has no installed distribution named "
                f"'{dist_name}' — the distribution name must be tap-plugin-<slug>."
            )

        top, segment = _namespace_segment(app_config)
        if top != NAMESPACE_PACKAGE or segment != slug:
            raise PrebootError(
                f"conformance gate: plugin '{slug}' AppConfig '{app_config}' is not under the "
                f"'{NAMESPACE_PACKAGE}.{slug}' namespace (got top='{top}', segment='{segment}'). "
                f"The import namespace segment must equal the slug (req-tap-plugin-arch-identity-3)."
            )

        manifest_slug = _manifest_slug(entry, dist)
        if manifest_slug != slug:
            raise PrebootError(
                f"conformance gate: plugin '{slug}' manifest slug is {manifest_slug!r}, expected "
                f"'{slug}' — tap-plugin.toml slug must equal the install slug / entry-point key."
            )

    logger.info("[be29] pre-boot conformance gate passed: %d plugin(s) identity-verified", len(entries))


# =============================================================================
# Compatibility-floor gate (req-tap-plugin-extdev-compat-floor): requires_tap
# =============================================================================


def _requires_tap_gate(entries: list[dict[str, Any]]) -> None:
    """Fail closed unless the running core satisfies every plugin's ``requires_tap``.

    A plugin's manifest may declare ``requires_tap`` — a PEP 440 range of core (``tap``)
    versions it supports. This gate reads each shipped manifest (import-free) and refuses
    to proceed when the running core version falls outside a declared range — the VS Code
    ``engines.vscode`` model: reject at boot with a legible message, never load-then-crash
    deep in operation. Plugins that declare no floor are skipped (allowed in v0). The core
    version is resolved lazily and only when a plugin actually declares a floor, so a
    profile of floor-less plugins never depends on it. See ``spec-tap-plugin-external-development.md``.
    """
    from tap.core_version import CoreVersionError, core_satisfies_requires_tap, core_tap_version

    checked = 0
    core_version: str | None = None
    for entry in entries:
        slug = entry["slug"]
        dist = _installed_distribution(dist_name_for_slug(slug))
        if dist is None:
            # The conformance gate (run first) already fails closed on a missing
            # distribution; nothing to add here.
            continue
        requires_tap = _read_manifest_requires_tap(_manifest_path_for(entry, dist))
        if requires_tap is None:
            continue

        if core_version is None:
            try:
                core_version = core_tap_version()
            except CoreVersionError as exc:
                raise PrebootError(
                    f"compatibility gate: plugin '{slug}' declares requires_tap={requires_tap!r} but the "
                    f"running core version cannot be determined ({exc})."
                ) from exc

        try:
            satisfied = core_satisfies_requires_tap(requires_tap, core_version=core_version)
        except ValueError as exc:
            # A malformed specifier is normally caught at manifest parse; a bad
            # value that reached an installed manifest is still fatal here.
            raise PrebootError(f"compatibility gate: plugin '{slug}': {exc}") from exc

        if not satisfied:
            raise PrebootError(
                f"compatibility gate: plugin '{slug}' requires TAP {requires_tap} but the running core is "
                f"{core_version} — not loading. Update the plugin's requires_tap, or run a core version in range."
            )
        checked += 1

    logger.info("[c96b] pre-boot compatibility gate passed: %d plugin(s) with a requires_tap floor satisfied", checked)


# =============================================================================
# Install reconciliation guard (req-boot-install-section-5): declared vs actual
# =============================================================================


def _reconciliation_guard(entries: list[dict[str, Any]], discovered: dict[str, str]) -> None:
    """Fail closed if a package-mode plugin is installed on disk but not declared+enabled.

    Reconciles DECLARED (the profile's enabled ``install`` set) against ACTUAL (the
    ``tap.plugins`` entry points discovered in the venv). The *missing* direction —
    declared but not installed — is already fatal in ``_resolve_tap_plugins`` (identity
    mismatch). This closes the *other* direction: an installed package-mode distribution
    that NO enabled ``install`` entry declares — a stale install left from a prior profile,
    a plugin the profile ``enabled: false``-d but never got uninstalled, or an undeclared /
    manually-installed plugin. Loading undeclared code at standup is exactly the
    supply-chain surface the declared-vs-actual posture guards, so it fails closed
    (`spec-security-posture` `req-sec-cheap-edges`: over-restriction relaxes cheaply,
    omission retrofits expensively).

    Build-baked plugins are invisible here (they carry no ``tap.plugins`` entry point), so
    the check is scoped to package-mode plugins by construction. In the normal entrypoint
    flow ``uv sync --all-packages`` prunes package-mode dists before pre-boot reinstalls the
    enabled set, so extras are normally zero; a non-empty set means real venv/profile drift.
    """
    install_slugs = {e["slug"] for e in entries}
    extras = sorted(set(discovered) - install_slugs)
    if extras:
        raise PrebootError(
            f"install reconciliation: package-mode plugin(s) {extras} are installed (they expose a "
            f"'{TAP_PLUGINS_ENTRY_POINT_GROUP}' entry point) but are not a declared+enabled `install` "
            f"entry in this profile — undeclared code must not load at standup. Add them to `install`, "
            f"or remove the stale install (uv pip uninstall). "
            f"Declared+enabled: {sorted(install_slugs) or '(none)'}."
        )
    logger.info(
        "[226f] pre-boot install reconciliation passed: %d installed == %d declared package-mode plugin(s)",
        len(discovered),
        len(install_slugs),
    )


# =============================================================================
# Dependency consistency gate (req-tap-plugin-arch-dependencies-4)
# =============================================================================


def _installed_version(slug: str) -> str | None:
    """Best-effort installed distribution version for a plugin slug, or None."""
    dist = _installed_distribution(dist_name_for_slug(slug))
    return dist.version if dist is not None else None


def _dependency_consistency_guard(entries: list[dict[str, Any]]) -> None:
    """Fail closed on plugin dependency divergence (declared vs observed vs install order).

    The Tier-1 sibling of ``_reconciliation_guard`` (spec ``req-tap-plugin-arch-dependencies-4``).
    Cross-checks three facts already in hand — each plugin's manifest ``depends_on``
    (declared intent), the AST-observed ``tap_plugin.<other>`` imports (derived code graph,
    ``tap.plugin_deps``), and the profile install order — and raises ``PrebootError`` on:

    1. an undeclared cross-plugin import (declared ⊇ observed),
    2. a dependency missing from / ordered after its dependent in the install set,
    3. a violated ``min_version`` floor.

    Scoped to in-repo plugin packages by construction (a fully-extracted site-packages
    plugin is out of the scanner's reach — the same caveat the log/authz scanners carry).
    Captures CODE dependencies only; the runtime-*data* (collector-produced) ordering
    stays profile-explicit by design (``req-tap-plugin-arch-dependencies-3``).
    """
    install_order = [e["slug"] for e in entries]
    packages = plugin_deps.discover_plugin_packages(REPO_ROOT)

    declared: dict[str, list[plugin_deps.DeclaredDep]] = {}
    observed: dict[str, set[str]] = {}
    versions: dict[str, str | None] = {}
    for slug in install_order:
        pkg = packages.get(slug)
        if pkg is None:
            continue  # out-of-repo / unscannable — cannot observe, skip (documented caveat)
        declared[slug] = plugin_deps.read_declared_depends_on(pkg)
        observed[slug] = plugin_deps.scan_observed_imports(pkg, slug)
        versions[slug] = _installed_version(slug)

    violations = plugin_deps.compute_violations(install_order, declared, observed, versions)
    if violations:
        joined = "\n  - ".join(violations)
        raise PrebootError(f"plugin dependency consistency gate failed:\n  - {joined}")

    edge_count = sum(len(v) for v in observed.values())
    logger.info(
        "[3b7e] pre-boot dependency consistency gate passed: %d cross-plugin import edge(s) across %d scanned plugin(s), all declared + ordered",
        edge_count,
        len(observed),
    )


# =============================================================================
# Static coherence guard (req-boot-install-section-3)
# =============================================================================


def _static_coherence_guard(profile: dict[str, Any], install_slugs: set[str]) -> None:
    """Fail loud (pre-migrate) if a population seed-plugin slug is neither installed nor build-baked."""
    available = install_slugs | BUILD_BAKED_PLUGIN_SLUGS
    missing = [s for s in _population_seed_slugs(profile) if s not in available]
    if missing:
        raise PrebootError(
            f"static coherence guard: population seed-plugin(s) {missing} are neither in the "
            f"profile's `install` section nor build-baked. Add them to `install` or fix the typo. "
            f"(installed={sorted(install_slugs) or '(none)'}, build-baked={sorted(BUILD_BAKED_PLUGIN_SLUGS)})"
        )
    logger.info("[ff21] pre-boot static coherence guard passed")


# =============================================================================
# Pre-migrate snapshot (req-boot-snapshot)
# =============================================================================


def _snapshot_dir() -> Path:
    return Path(os.environ.get("TAP_SNAPSHOT_DIR", str(REPO_ROOT / ".tap-snapshots")))


def _pg_conn_args() -> tuple[list[str], dict[str, str]]:
    """Parse DATABASE_URL into pg_dump connection flags + a PGPASSWORD env overlay."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise PrebootError("snapshot: DATABASE_URL is not set")
    parsed = urlparse(url)
    if not parsed.path or parsed.path == "/":
        raise PrebootError(f"snapshot: DATABASE_URL has no database name: {url}")
    flags = [
        "--host",
        parsed.hostname or "localhost",
        "--port",
        str(parsed.port or 5432),
        "--username",
        unquote(parsed.username or "postgres"),
        "--dbname",
        parsed.path.lstrip("/"),
    ]
    env_overlay = {"PGPASSWORD": unquote(parsed.password)} if parsed.password else {}
    return flags, env_overlay


def _take_snapshot() -> Path:
    """Take a verified full-DB snapshot (`pg_dump -Fc`) and return its path.

    Callable primitive (`req-boot-snapshot-6`): a future periodic snapshot system
    reuses this. The snapshot is verified restorable (`pg_restore --list`) before the
    caller proceeds to migrate (`req-boot-snapshot-3`). Restore is a deliberate human
    action, never automatic (`req-boot-snapshot-4`).
    """
    flags, env_overlay = _pg_conn_args()
    out_dir = _snapshot_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"pre-migrate-{stamp}.dump"

    env = {**os.environ, **env_overlay}
    dump = subprocess.run(
        ["pg_dump", "--format=custom", "--file", str(out_path), *flags],
        capture_output=True,
        text=True,
        env=env,
    )
    if dump.returncode != 0:
        raise PrebootError(f"snapshot: pg_dump failed (exit {dump.returncode}): {dump.stderr.strip()}")

    # Verify: file exists, non-empty, and pg_restore can read its table of contents.
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise PrebootError(f"snapshot: pg_dump produced no/empty file at {out_path}")
    listing = subprocess.run(["pg_restore", "--list", str(out_path)], capture_output=True, text=True)
    if listing.returncode != 0:
        raise PrebootError(f"snapshot: verification failed — {out_path} not restorable: {listing.stderr.strip()}")

    logger.info("[409c] pre-boot snapshot written + verified: %s (%d bytes)", out_path, out_path.stat().st_size)
    return out_path


def _maybe_snapshot(profile: dict[str, Any]) -> Path | None:
    """Resolve the snapshot switch and take a snapshot unless disabled.

    Switch defaults true on absence (`req-boot-snapshot-2`); a disabled snapshot logs
    loud (WARNING) — a disabled safety net must announce itself.
    """
    install_section = profile.get("install") or {}
    resolved = resolve_var(
        "install",
        "snapshot_before_migrate",
        profile_section=install_section,
        default=True,
        is_bool=True,
    )
    logger.info("[7d43] snapshot_before_migrate = %s (source: %s)", resolved.value, resolved.source)
    if not resolved.value:
        logger.warning(
            "[5d5d] pre-boot snapshot DISABLED (source: %s) — proceeding to migrate with NO restore point",
            resolved.source,
        )
        return None
    return _take_snapshot()


# =============================================================================
# Orchestration + CLI
# =============================================================================


def run_preboot(profile_id: str) -> list[str]:
    """Execute the pre-boot stage for a profile; return the resolved TAP_PLUGINS list.

    install → discover (identity) → static coherence guard → snapshot. Any failure
    raises PrebootError; the caller aborts before migrate (`req-boot-preboot-4`).
    """
    logger.info("[43c1] pre-boot stage starting for profile '%s'", profile_id)
    profile = _read_profile(profile_id)

    entries = _install_plugin_specs(profile)
    _install_plugins(entries)

    discovered = discover_entry_points()
    app_configs = _resolve_tap_plugins(entries, discovered)
    _conformance_gate(entries, discovered)
    _requires_tap_gate(entries)
    _reconciliation_guard(entries, discovered)
    _dependency_consistency_guard(entries)
    install_slugs = {e["slug"] for e in entries}

    _static_coherence_guard(profile, install_slugs)

    _maybe_snapshot(profile)

    logger.info("[70b4] pre-boot stage complete: %d package-mode plugin(s) -> TAP_PLUGINS", len(app_configs))
    return app_configs


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="tap.preboot", description="TAP settings-free pre-boot stage.")
    parser.add_argument("--profile", required=True, help="boot profile id (boot/<id>.boot.json)")
    args = parser.parse_args(argv)

    try:
        app_configs = run_preboot(args.profile)
    except PrebootError as exc:
        abort(logger, "preboot", str(exc))
        return 1

    # stdout carries ONLY the TAP_PLUGINS value (space-separated) for the entrypoint.
    print(" ".join(app_configs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
