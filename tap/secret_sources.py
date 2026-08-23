"""App-neutral pluggable secret-source seam.

``runtime_secrets`` reads a secret's *envelope* from disk; this module resolves its
*value* from the source the envelope names. Absent a source, the value is the envelope's
inline ``data`` — the built-in **disk source**, today's behavior unchanged. A named
source dispatches to a provider discovered from the ``tap.secret_sources`` entry-point
group: disk in core, cloud stores contributed by a slim, allow-listed distribution
(e.g. ``aws-secrets-source``, homed in the hardened ``tap-build-dependencies`` repo and
installed at image build time), so **no cloud SDK enters core** until such a distribution
is installed.

Spec: ``specs/spec-tap-plugin-dependency-resolution.md`` ``req-tap-plugin-depres-sources`` /
``-trust`` / ``-bootstrap``. The manifest stays TAP-owned and disk-resident (envelope,
descriptions, guards); only the opaque value moves.

Design constraints (mirroring ``runtime_secrets`` and ``plugin_source_auth``, which this
serves): **import-safe / settings-free / no ``tap_*`` app import** — it resolves at
preboot, before Django is configured. The provider distribution (and its cloud SDK) is
imported lazily, only when a secret actually names that source. Secret material is
returned in memory only; this module never logs a fetched value.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# The entry-point group a cloud secret-source provider advertises. Mirrors the
# `tap.plugins` group `tap.preboot.discover_entry_points()` reads — distribution
# metadata, settings-free, no package import needed to *see* a provider.
SECRET_SOURCES_ENTRY_POINT_GROUP = "tap.secret_sources"

# The built-in source: the value is inline in the envelope's `data` (the disk store).
# A secret with no `metadata.source` (or `source == DISK_SOURCE`) never leaves disk.
DISK_SOURCE = "disk"

# Trust allow-list (req-tap-plugin-depres-trust-2): only these DISTRIBUTIONS may register a
# secret source. An entry point advertised by any other distribution is ignored (never
# loaded) — "any installed distribution registers a credential source" is exactly the
# hijack surface this closes. Widen deliberately, never by default. The disk source is
# core-resident and is never gated by this list. Compared under PEP 503 normalization so
# the declared name (`aws-secrets-source`) and any underscore/case variant match.
_ALLOWED_SOURCE_DISTRIBUTIONS: frozenset[str] = frozenset({"aws-secrets-source"})


def _normalize_dist(name: str | None) -> str | None:
    """PEP 503 name normalization (lowercase; runs of ``_.-`` → single ``-``)."""
    if name is None:
        return None
    out = []
    prev_sep = False
    for ch in name.lower():
        if ch in "_-.":
            if not prev_sep:
                out.append("-")
            prev_sep = True
        else:
            out.append(ch)
            prev_sep = False
    return "".join(out)


class SecretSourceError(Exception):
    """A secret named a source that could not be honored.

    Raised when a secret routes to an unregistered source, or a registered provider
    fails to fetch. Neutral and app-independent: ``runtime_secrets`` re-wraps it in
    ``RuntimeSecretError`` so callers keep catching one resolver exception type.
    """


@runtime_checkable
class SecretSource(Protocol):
    """A provider that fetches a secret's value from an external store.

    ``name`` is the routing token a manifest's ``metadata.source`` names. ``fetch``
    returns the effective ``data`` mapping — exactly what the envelope would have held
    inline on disk — given the manifest's ``metadata.source_ref`` locator. The store
    authenticates via **ambient cloud IAM**, never a TAP secret
    (``req-tap-plugin-depres-bootstrap-3``), so there is no resolution recursion.
    """

    name: str

    def fetch(self, ref: Mapping[str, Any], *, scope: str, key: str) -> Mapping[str, Any]:
        """Return the secret value for ``scope``/``key`` located by ``ref``."""
        ...


# Module-level registry. Populated once per process from allow-listed entry points, plus
# any test-registered source. Keyed by the source `name` a manifest routes to.
_REGISTRY: dict[str, SecretSource] = {}
_DISCOVERED = False


def register_source(source: SecretSource) -> None:
    """Register a source provider under its ``name``.

    Raises ``SecretSourceError`` on a duplicate name so two providers cannot silently
    claim the same routing token (last-write-wins would be a hijack vector).
    """
    name = source.name
    if not isinstance(name, str) or not name:
        raise SecretSourceError(f"secret source {source!r} has an invalid name")
    if name == DISK_SOURCE:
        raise SecretSourceError(f"secret source name '{DISK_SOURCE}' is reserved for the built-in disk source")
    existing = _REGISTRY.get(name)
    if existing is not None and existing is not source:
        raise SecretSourceError(f"secret source '{name}' is already registered")
    _REGISTRY[name] = source


def _discover() -> None:
    """Load allow-listed ``tap.secret_sources`` providers from distribution metadata.

    Settings-free and idempotent (scans once per process). An entry point from a
    distribution not on ``_ALLOWED_SOURCE_DISTRIBUTIONS`` is skipped with a warning and
    never loaded — the trust gate is enforced *before* the provider module is imported,
    so an untrusted distribution's code never runs here.
    """
    global _DISCOVERED
    if _DISCOVERED:
        return
    importlib.invalidate_caches()
    for ep in importlib.metadata.entry_points(group=SECRET_SOURCES_ENTRY_POINT_GROUP):
        dist_name = ep.dist.name if ep.dist is not None else None
        if _normalize_dist(dist_name) not in _ALLOWED_SOURCE_DISTRIBUTIONS:
            logger.warning(
                "[df47] ignoring non-allow-listed secret source entry point name=%s dist=%s",
                ep.name,
                dist_name,
            )
            continue
        provider = ep.load()()  # entry point resolves to the class; instantiate it
        register_source(provider)
    _DISCOVERED = True


def resolve_sourced_data(source_name: str, ref: Mapping[str, Any], *, scope: str, key: str) -> Mapping[str, Any]:
    """Fetch the value for a secret whose envelope routes to ``source_name``.

    Fails loud (``req-tap-plugin-depres-sources-4``) if the source is unregistered — never a
    silent degrade to an empty or disk value. ``ref`` is the envelope's
    ``metadata.source_ref``. A provider ``fetch`` failure is re-raised as
    ``SecretSourceError`` with the secret's ``scope``/``key`` for diagnostics (the value
    itself is never included).
    """
    _discover()
    provider = _REGISTRY.get(source_name)
    if provider is None:
        raise SecretSourceError(
            f"secret {scope}:{key} routes to source '{source_name}' but no such source is "
            f"registered — is its provider distribution installed and allow-listed?"
        )
    try:
        data = provider.fetch(ref, scope=scope, key=key)
    except SecretSourceError:
        raise
    except Exception as exc:  # provider-boundary: normalize any SDK/IO failure
        raise SecretSourceError(f"source '{source_name}' failed to fetch {scope}:{key}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise SecretSourceError(
            f"source '{source_name}' returned {type(data).__name__} for {scope}:{key}, expected a JSON object"
        )
    return data


def _reset_for_testing(registry: dict[str, SecretSource] | None = None, *, discovered: bool = False) -> None:
    """Reset the module registry between tests (mirrors ``ScopedRegistry._reset_for_testing``)."""
    global _DISCOVERED
    _REGISTRY.clear()
    if registry:
        _REGISTRY.update(registry)
    _DISCOVERED = discovered


__all__ = [
    "SECRET_SOURCES_ENTRY_POINT_GROUP",
    "DISK_SOURCE",
    "SecretSourceError",
    "SecretSource",
    "register_source",
    "resolve_sourced_data",
]
