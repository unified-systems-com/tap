"""Canonical TAP capability registry (req-tap-auth-capabilities).

TAP capabilities are the platform's public authorization vocabulary; Django
permissions are the backend projection. The **source of truth** is the
version-controlled declarative file ``tap_auth/tap_auth.capabilities.json`` (schema:
``tap_auth/schemas/capabilities.schema.json``); this module is the thin loader
that validates it and exposes the in-memory registry. The `Capability` DB table
and the projected `auth.Permission` rows are hard-synced from `CAPABILITIES`
(tap_auth/sync.py), and runtime authorization checks resolve capabilities by
their public name (e.g. ``grid.read``).

The public name is the contract (``grid.read``); the projected Django permission
codename is an implementation detail (``grid_read``), via `codename_for()`.

Role bundles (the least-privilege capability sets granted to the protected
built-in groups) live in ``tap_auth/tap_auth.roles.json`` (loaded by `tap_auth.roles`),
**not here** — moving them out of this file is `req-tap-auth-roles`.

An installed plugin may add capabilities in ``tap_plugin/<slug>/<slug>.capabilities.json``,
named ``<slug>.<action>`` only (req-tap-auth-plugin-declarations). They join the registry
here, so ``authorize``/``can``/``requires_capability`` and the hard sync treat them like any
other capability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from tap.jsonfiles import JsonFileError, load_json_file
from tap_auth.plugin_declarations import CAPABILITIES_SUFFIX, plugin_auth_files

_DATA_PATH = Path(__file__).resolve().parent / "tap_auth.capabilities.json"
_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "capabilities.schema.json"

# The declarer recorded for capabilities and roles in tap_auth's own files.
CORE_DECLARER = "tap_auth"


class RiskLevel(StrEnum):
    """Risk/classification metadata for a capability (req-tap-auth-capabilities-7).

    Queryable from the DB so a future AI/Paladin actor can reason about how
    dangerous an action is without code access.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class CapabilitySpec:
    """One capability definition in the canonical registry."""

    name: str
    """Public TAP vocabulary, e.g. ``grid.read``."""
    description: str
    """Human-readable meaning, stored on the Capability row."""
    risk: RiskLevel
    description_json: dict[str, Any] = field(default_factory=dict)
    """Optional structured context, synced to ``Capability.description_json``."""
    declared_by: str = CORE_DECLARER
    """Who declared it: ``tap_auth`` for the core file, else the declaring plugin's slug
    (req-tap-auth-plugin-declarations). Synced to ``Capability.declared_by``."""


def _read_capability_file(path: Path, *, label: str, declared_by: str) -> tuple[CapabilitySpec, ...]:
    """Load + validate one capabilities file against the shared schema.

    Fails loud (`ImproperlyConfigured`) on a missing/unreadable file, a schema
    violation, or a name repeated within the file — never a silent partial registry.
    """
    try:
        data = load_json_file(path, schema=_SCHEMA_PATH)
    except JsonFileError as exc:
        raise ImproperlyConfigured(f"{label}: {exc}") from exc

    specs = tuple(
        CapabilitySpec(
            name=c["name"],
            description=c["description"],
            risk=RiskLevel(c["risk"]),
            description_json=c.get("description_json", {}),
            declared_by=declared_by,
        )
        for c in data["capabilities"]
    )
    names = [s.name for s in specs]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ImproperlyConfigured(f"{label} has duplicate capability names: {duplicates}")
    return specs


def namespace_of(name: str) -> str:
    """The namespace of a capability or role name: the text before its first dot."""
    return name.split(".", 1)[0]


def codename_for(name: str) -> str:
    """Project a public capability name to its Django permission codename.

    ``grid.read`` -> ``grid_read``. The public name is the contract; the codename
    is storage. Checked via ``has_perm("tap_auth.grid_read")`` semantics, but TAP
    authorization never calls ``has_perm`` directly (it ignores ``is_superuser``).
    """
    return name.replace(".", "_")


def _confine_plugin_capabilities(
    slug: str, specs: tuple[CapabilitySpec, ...], *, label: str, reserved: frozenset[str]
) -> None:
    """Refuse a plugin capability file that reaches outside the plugin's own namespace.

    A plugin may only name capabilities ``<slug>.<action>``, and its slug may not be a
    namespace core already uses, so a plugin can neither shadow a core capability nor
    mint one that reads as core authority (req-tap-auth-plugin-declarations).
    """
    if slug in reserved:
        raise ImproperlyConfigured(
            f"{label}: plugin slug '{slug}' is a core capability namespace ({sorted(reserved)}); "
            "a plugin may not declare capabilities in it"
        )
    outside = sorted(s.name for s in specs if namespace_of(s.name) != slug)
    if outside:
        raise ImproperlyConfigured(
            f"{label}: plugin '{slug}' may only declare capabilities named '{slug}.<action>'; " f"refusing {outside}"
        )


def _load_capabilities() -> tuple[CapabilitySpec, ...]:
    """Load the core registry, then every installed plugin's declared capabilities.

    Core loads first and defines the reserved namespaces. Each plugin file is
    schema-validated and confined to its own namespace; a name declared twice
    anywhere fails loud.
    """
    core = _read_capability_file(_DATA_PATH, label="tap_auth.capabilities.json", declared_by=CORE_DECLARER)
    reserved = frozenset(namespace_of(s.name) for s in core)
    specs = list(core)
    for files in plugin_auth_files():
        if files.capabilities_path is None:
            continue
        label = f"{files.slug}{CAPABILITIES_SUFFIX}"
        declared = _read_capability_file(files.capabilities_path, label=label, declared_by=files.slug)
        _confine_plugin_capabilities(files.slug, declared, label=label, reserved=reserved)
        specs.extend(declared)
    names = [s.name for s in specs]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ImproperlyConfigured(f"capability names declared more than once: {duplicates}")
    # Two names can project to one Django codename ('cares.run_collectors' and
    # 'cares_run.collectors' are both 'cares_run_collectors'), which would make them share
    # one Permission row, so a grant of one would be a grant of the other. Refuse it.
    by_codename: dict[str, list[str]] = {}
    for name in names:
        by_codename.setdefault(codename_for(name), []).append(name)
    shared = sorted(group for group in by_codename.values() if len(group) > 1)
    if shared:
        raise ImproperlyConfigured(f"capability names project to the same permission codename: {shared}")
    return tuple(specs)


# Canonical capability registry: tap_auth.capabilities.json, then each installed plugin's
# <slug>.capabilities.json, loaded at import. Operation-level (not model-level).
CAPABILITIES: tuple[CapabilitySpec, ...] = _load_capabilities()

# The namespaces the core file uses. A plugin may not declare capabilities or roles in one.
CORE_NAMESPACES: frozenset[str] = frozenset(
    namespace_of(c.name) for c in CAPABILITIES if c.declared_by == CORE_DECLARER
)

ALL_CAPABILITY_NAMES: tuple[str, ...] = tuple(c.name for c in CAPABILITIES)

# The capability each op-class requires at the write backstop (req-tap-auth-policy
# On By Default), checked statelessly against what the actor holds. A create/update
# op requires grid.write; a delete op requires grid.delete *specifically*. Broad
# covers (grid.import_grift, grid.admin) deliberately do NOT satisfy the delete
# check — so a bootloader cannot tombstone through an import cover (the collector
# role holds grid.delete directly, interim and global)
# (doc-auth-per-app-standards "split cover semantics"). The grift importer
# authorizes grid.delete explicitly in its own scope when its batch contains
# removals, so an actor lacking it gets a clean denial rather than tripping this
# structural net.
WRITE_CAPABILITY: str = "grid.write"
DELETE_CAPABILITY: str = "grid.delete"
# Reconciliation authority: the reconcile verb's own capability, distinct from delete — a
# collector never deletes; the verb does, on evidence (req-grid-reconcile-verb).
RECONCILE_CAPABILITY: str = "grid.reconcile"

# The remaining write-class capabilities: hard-purge and GRIFT batch import. Named
# here with the other grid.* names so every consumer derives the spelling from one
# place (tap_grid/write_guard.py reads them on call, not at import, to keep clear of
# the import cycle through tap_auth.enforcement).
PURGE_CAPABILITY: str = "grid.purge"
IMPORT_GRIFT_CAPABILITY: str = "grid.import_grift"

# The single capability every graph READ requires (the read backstop checks for
# exactly this on the Search dispatch chokepoint).
READ_CAPABILITY: str = "grid.read"

# Discovery of registered types/schemas via the service layer (read-adjacent,
# separately named so read and discover stay independently grantable).
DISCOVER_CAPABILITY: str = "grid.discover"

_BY_NAME: dict[str, CapabilitySpec] = {c.name: c for c in CAPABILITIES}

# Every Python-side name constant must exist in the JSON registry — fail loud at
# import so a constant cannot drift from tap_auth.capabilities.json (whose entries
# are the source of truth) and silently authorize nothing.
for _constant in (
    WRITE_CAPABILITY,
    DELETE_CAPABILITY,
    RECONCILE_CAPABILITY,
    PURGE_CAPABILITY,
    IMPORT_GRIFT_CAPABILITY,
    READ_CAPABILITY,
    DISCOVER_CAPABILITY,
):
    if _constant not in _BY_NAME:
        raise ImproperlyConfigured(f"capability constant '{_constant}' is not defined in tap_auth.capabilities.json")
del _constant


def get_capability(name: str) -> CapabilitySpec | None:
    """Return the registered CapabilitySpec for ``name``, or None if unknown."""
    return _BY_NAME.get(name)
