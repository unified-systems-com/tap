"""tap_cares collector registry.

req-tap-cares-collector-registry, req-tap-cares-collector-registration
(spec-tap-cares-collector.md).

Mirrors the search runner registry pattern in `tap_grid/registry.py`:
    - `collector_registry` is a ScopedRegistry[type[CollectorBase]] using the
      validator hooks added by req-grid-registry-scope-validators
    - `register_collector(key, cls, *, scope, name, description)` is the
      read-only half of dual-existence registration: it registers the runner
      class and records the on-grid node descriptor in memory, writing no grid
      node (req-tap-plugin-load-v0-ready-readonly). `scope` is REQUIRED and must be
      the plugin's stable slug — a collector's derived entity id is a durable,
      cross-referenced grid key, so its identity input must be an explicit
      declaration, never inferred from `cls.__module__` (which module renames
      silently change — see req-tap-cares-collector-model-10).
    - `reconcile_collector_nodes()` is the deferred grid-side half: the sole path
      that materializes the on-grid Collector node (deterministic UUIDv5
      identity) under a caller-bound actor. See
      `tap_grid/specs/spec-grid-dual-existence.md`.
    - `_validate_collector_token` enforces the scope:key format by deferring to
      the canonical grammar in `tap.registry` (shared with the secret registry
      and the pre-boot resolver, so the grammar cannot drift). The Collector
      model's validate() hook calls it too so model-side and registry-side
      enforcement cannot drift (req-tap-cares-collector-registry-10).
"""

from __future__ import annotations

import uuid
from typing import Final

from django.core.exceptions import ImproperlyConfigured

from tap.registry import ScopedRegistry, validate_scoped_token
from tap_auth.enforcement import requires_capability
from tap_cares.collectors.base import CollectorBase
from tap_cares.exceptions import (
    CollectorNotFoundError,
    InvalidCollectorRegistryKeyError,
)

# Deterministic UUIDv5 namespace for Collector grid-side identity.
# Derived once from a stable seed string; the value is frozen for the lifetime
# of the v0 collector subsystem. Changing this value would re-identify every
# Collector node on every grid — not permitted (req-tap-cares-collector-registration-8).
NAMESPACE_COLLECTOR: Final[uuid.UUID] = uuid.uuid5(uuid.NAMESPACE_DNS, "tap_cares.collector")


def _validate_collector_token(value: str) -> None:
    """Reject malformed scope or key tokens.

    Delegates to the canonical grammar in `tap.registry` so collector, secret,
    and pre-boot-resolver token checks share one source of truth. Used as both
    validate_scope and validate_key on collector_registry, and invoked by
    Collector.validate() on each half of the persisted `collector_registry`
    field so model and registry stay aligned.
    """
    validate_scoped_token(value, error_cls=InvalidCollectorRegistryKeyError, label="collector registry")


collector_registry: ScopedRegistry[type[CollectorBase]] = ScopedRegistry(
    "collector",
    validate_key=_validate_collector_token,
    validate_scope=_validate_collector_token,
    title="Collector Registry",
    description="Scoped registry of registered tap_cares collector classes.",
)

# Node-descriptor metadata captured at registration (app `ready()` time) and
# consumed by `reconcile_collector_nodes()`. Keyed by qualified `scope:key`.
# `register_collector` stashes here INSTEAD OF writing the grid, so `ready()` stays
# read-only w.r.t. graph state (req-tap-plugin-load-v0-ready-readonly); the Collector
# node is materialized later by an explicit reconcile, under whatever actor its
# caller has bound.
_COLLECTOR_NODE_METADATA: dict[str, dict[str, str]] = {}


def register_collector(
    key: str,
    cls: type[CollectorBase],
    *,
    scope: str,
    name: str,
    description: str,
) -> None:
    """Register a collector capability — the read-only half of dual existence.

    Runs at app `ready()` and performs NO graph write (req-tap-plugin-load-v0-ready-readonly):

      1. Registers `cls` in `collector_registry` under `scope:key`. `scope` is
         REQUIRED and must be the plugin's stable slug. It is deliberately NOT
         inferred from `cls.__module__`: a collector's derived entity id is a
         durable, cross-referenced grid key (the reconcile key for its on-grid
         Collector node and a hardcoded edge target in schedule grift bundles),
         so a module rename must never silently change it. Making scope an
         explicit declaration is what keeps that identity stable across
         package-layout refactors (req-tap-cares-collector-model-10).
      2. Records the on-grid node descriptor (`name`/`description`) in
         `_COLLECTOR_NODE_METADATA` for later materialization.

    The on-grid `Collector` node (deterministic identity
    `uuid5(NAMESPACE_COLLECTOR, "{scope}:{key}")`) is upserted separately by
    `reconcile_collector_nodes()` — an explicit reconcile its caller runs under a
    bound actor (boot today; plugin install/configure conceivably later). Splitting
    the two halves keeps `ready()` from writing the grid before a named actor exists:
    a fresh standup that wrote at `ready()` would either fail closed (no actor) or be
    silently masked, leaving an empty Collector inventory.

    Rejects anything that is not a CollectorBase subclass
    (req-tap-cares-collector-module-class-6). `name` and `description` are
    required: every collector that lands on the grid carries human-readable
    identity for Administrivia surfaces (req-tap-cares-collector-registration-3).

    Spec: req-tap-cares-collector-registration.
    """
    if not (isinstance(cls, type) and issubclass(cls, CollectorBase)):
        raise ImproperlyConfigured(f"register_collector: {cls!r} must be a subclass of CollectorBase.")

    # In-memory registration of the runner class (validates the token format and
    # raises on a duplicate before anything is recorded).
    collector_registry.register(key, cls, scope=scope)

    # Record the node descriptor for the deferred grid-side materialization.
    qualified_key = f"{scope}:{key}"
    _COLLECTOR_NODE_METADATA[qualified_key] = {"name": name, "description": description}


@requires_capability("cares.reconcile_collectors")
def reconcile_collector_nodes() -> dict[str, int]:
    """Materialize the on-grid Collector node for every registered collector, in one batch.

    The deferred grid-side half of dual-existence registration
    (spec-grid-dual-existence): `register_collector` records the runner class and
    node descriptor in memory at app `ready()` (read-only,
    req-tap-plugin-load-v0-ready-readonly); this creates or updates the matching grid
    node. Splitting the two keeps `ready()` from writing before a named actor exists.

    Actor: runs under whatever actor the **caller** has bound — this function takes
    no actor and imports no built-in, so tap_cares carries no caller-specific
    config; the write inherits the ambient context like any other service call.
    Whoever calls it creates the nodes as their own actor. Today that caller is the
    boot orchestrator (the `reconcile_collectors` command binds `tap_bootloader`); a
    plugin install/configure flow could run the same reconcile under a different
    actor in future.

    Idempotent: re-running converges — creates missing nodes, patches drifted
    `name`/`description`, no-ops the rest — so it is safe to re-apply. Returns counts
    keyed `created` / `updated` / `unchanged`.

    Fails loud: a collector registered in `collector_registry` with no recorded node
    descriptor is an internal-consistency violation (`register_collector` records both
    halves together) and raises `ImproperlyConfigured` rather than skipping the node —
    boot relies on this reconcile, so a missing descriptor must never be a partial,
    silent skip-as-success.
    """
    from tap_cares.models import Collector
    from tap_grid.service_types import WriteOperation
    from tap_grid.services import write_batch

    summary = {"created": 0, "updated": 0, "unchanged": 0}
    registered = collector_registry.keys()  # sorted fully-qualified "scope:key"
    if not registered:
        return summary

    # Resolve the desired node descriptors, then read the existing rows in one
    # query so the diff (create vs. patch vs. no-op) is computed in memory.
    desired: list[tuple[str, uuid.UUID, dict[str, str]]] = []
    for qualified_key in registered:
        meta = _COLLECTOR_NODE_METADATA.get(qualified_key)
        if meta is None:
            # A runner registered in collector_registry with no recorded node
            # descriptor is an internal-consistency violation: register_collector
            # records both halves in one call, so this state means a registration
            # path bypassed it. Boot materializes Collector nodes through this
            # reconcile, so a missing descriptor must fail loud — never a partial
            # reconcile that silently omits a node while reporting success.
            raise ImproperlyConfigured(
                f"reconcile_collector_nodes: collector {qualified_key!r} is registered in "
                f"collector_registry but has no node descriptor; register_collector records "
                f"both halves together, so this indicates a registration path that bypassed it."
            )
        desired.append((qualified_key, uuid.uuid5(NAMESPACE_COLLECTOR, qualified_key), meta))

    existing_by_id = {c.entity_id: c for c in Collector.objects.filter(entity_id__in=[eid for _, eid, _ in desired])}

    # Diff every registered collector against the grid, accumulating one
    # WriteOperation per node that needs a create or a patch.
    ops: list[WriteOperation] = []
    for qualified_key, entity_id, meta in desired:
        existing = existing_by_id.get(entity_id)
        if existing is None:
            ops.append(
                WriteOperation(
                    verb="create_node",
                    type_slug="collector",
                    payload={
                        "name": meta["name"],
                        "description": meta["description"],
                        "collector_registry": qualified_key,
                    },
                    entity_id=entity_id,
                )
            )
            summary["created"] += 1
            continue
        # collector_registry is identity-bearing and never patched here.
        drift: dict[str, str] = {}
        if existing.name != meta["name"]:
            drift["name"] = meta["name"]
        if existing.description != meta["description"]:
            drift["description"] = meta["description"]
        if drift:
            ops.append(WriteOperation(verb="patch_node", target=entity_id, payload=drift))
            summary["updated"] += 1
        else:
            summary["unchanged"] += 1

    if not ops:
        return summary

    # One batch for the whole reconcile: every collector node lands together under a
    # single batch_id — one visible, atomic operation on the grid (all converge or
    # none do; an idempotent re-apply heals a transient failure). Runs under whatever
    # actor the caller bound upstream (e.g. the reconcile_collectors boot command);
    # write_batch inherits it from the ambient context. INTERNAL_ONLY would block the
    # public batch path, so this uses the trusted-internal `_internal_only_bypass` —
    # the same escape hatch `_create_node_internal` wraps, now over N ops at once.
    result = write_batch(  # TAP-AUTHZ-COV: runs under the caller-bound program actor; grid.write re-checked at the write backstop
        ops,
        _internal_only_bypass=True,
    )
    if not result.success:
        failed = [(r.operation, [(e.code, e.message) for e in r.errors]) for r in result.results if not r.success]
        raise ImproperlyConfigured(
            f"reconcile_collector_nodes: batch of {len(ops)} op(s) failed "
            f"(batch errors={[(e.code, e.message) for e in result.errors]}; op errors={failed})"
        )
    return summary


def get_collector(collector_key: str) -> type[CollectorBase]:
    """Return the collector class for a fully-qualified 'scope:key'.

    Raises:
        InvalidCollectorRegistryKeyError: if the key format is invalid.
        CollectorNotFoundError: if no class is registered for the key.
    """
    try:
        return collector_registry.get(collector_key)
    except KeyError:
        raise CollectorNotFoundError(
            f"No collector registered for key '{collector_key}'. " f"Registered: {collector_registry.keys()}"
        ) from None
