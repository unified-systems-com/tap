# Grid Dual-Existence Pattern Specification

## Philosophy

Some TAP capabilities exist in two places at once: as a **sub-grid** runtime registration (a Python class, callable, or registry entry visible only to in-process code) and as an **on-grid** TAP-managed entity (a `BaseModel` node visible to the rest of the platform). The two halves describe the same logical capability and must stay coupled — the on-grid node is the platform's record that a capability exists; the sub-grid registration is the executable binding that lets it run.

The first concrete consumer of the pattern is `tap_cares.Collector`. Emitters, Actions, Receivers, and potentially `Plugin` itself are expected to follow. The pattern is named here so each subsystem does not reinvent it.

The pattern as it stands is a v0 codification of conventions that have been emerging across `tap_cares`, `tap_grid`'s search system, and the `tap_plugins` registration surface. Each subsystem currently glues the two halves together informally. This spec defines the shared shape so future capabilities arrive with one consistent mental model and one consistent set of files to write.

## Vocabulary

- **Sub-grid side** — the in-process Python representation of a capability: a class registered in a `ScopedRegistry`, a callable, an `AppConfig.ready()` hook. Behavioral. Lives in code.
- **Grid side** — the on-grid TAP-managed node representing the capability's existence: a `BaseModel` subclass with an `Entity` row on the spine. Inspectable, linkable, traversable. Lives in the database.
- **Registration entry point** — the single function plugin code calls to declare a capability. Registers the sub-grid side AND ensures the grid side exists. Idempotent on reload.
- **Trigger entity** — a separate node type (scheduler row, event record, rule activation) that decides when a capability runs. Not part of the dual-existence pattern itself; the pattern composes with whatever trigger model a subsystem chooses.

## Goals

|    |                          |                                                                 |
| :---: | ---                   | ---                                                             |
| 1. | Single Registration Surface | One plugin-side call registers both halves of a capability       |
| 2. | Deterministic Identity   | The on-grid node's entity_id is derived from the sub-grid registry key, stable across reloads and across grids |
| 3. | Internal-Only Grid Side  | The grid node is not user-creatable through the generic service layer; the registration entry point is the only legitimate creator |
| 4. | Idempotent Re-registration | Plugin reload upserts the grid node; identity stays stable; mutable descriptive fields refresh |
| 5. | Discoverable             | The grid is the platform-visible catalog of registered capabilities |
| 6. | Composable               | The pattern composes with separate trigger entities (scheduler, event ingress) without entangling them |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-dual-existence-pattern | [Dual-Existence Pattern](#dual-existence-pattern) | Proposed | The canonical shape: sub-grid registry + grid node, joined by deterministic identity and a single registration entry point |
| req-grid-dual-existence-identity | [Deterministic Identity Derivation](#deterministic-identity-derivation) | Proposed | UUIDv5 over a subsystem namespace plus the registry key |
| req-grid-dual-existence-internal-only | [Grid Side Is Internal-Only](#grid-side-is-internal-only) | Proposed | Grid models carry `INTERNAL_ONLY = True`; trusted-internal create is the sole legal path |
| req-grid-dual-existence-flavors | [Pattern Flavors](#pattern-flavors) | Proposed | Two flavors: plugin-declared capability vs user-creatable + code-attached |
| req-grid-dual-existence-naming | [Naming Convention](#naming-convention) | Proposed | `<Thing>` model + `<thing>_registry` + `register_<thing>(...)` |
| req-grid-dual-existence-consolidation | [Consolidated Registration Mechanism](#consolidated-registration-mechanism) | Backlog | Future shared helper for `_ensure_<thing>_node`; today each subsystem implements its own |
| req-grid-dual-existence-teardown | [Tear-Down Semantics](#tear-down-semantics) | Backlog | What happens to the grid node when a plugin uninstalls or stops calling `register_<thing>` |

---

## Dual-Existence Pattern
----
RID: `req-grid-dual-existence-pattern`
Status: `Proposed`

A dual-existence capability has two halves that arrive together:

1. **Sub-grid:** an entry in a `ScopedRegistry` (or equivalent in-process registration mechanism) that maps a `scope:key` string to a Python class or callable.
2. **Grid:** a `BaseModel` subclass instance — a node on the entity spine — that represents the capability for inspection, linking, and observability.

The two halves are joined by a registration entry point that performs both registrations atomically from the caller's perspective:

```python
def register_<thing>(
    key: str,
    cls: type[<ThingBase>],
    *,
    name: str,
    description: str,
    # ... subsystem-specific fields ...
) -> None:
    """Register a <thing> capability.

    Performs two coupled actions:
    1. Registers `cls` in `<thing>_registry` under `scope:key`
       (scope is inferred from cls.__module__).
    2. Upserts the on-grid <Thing> node with deterministic entity_id
       via the trusted-internal create path.
    """
```

The entry point is called at plugin load time — typically inside the plugin's `AppConfig.ready()`. Calling it again on subsequent reloads is idempotent: the same `scope:key` produces the same entity_id, and the upsert refreshes mutable descriptive fields without disturbing identity, dimensions, history, or version semantics.

Idempotency must extend to **concurrent first-create across processes**, not just sequential reloads. Because the entry point runs in `AppConfig.ready()`, and a deployment commonly starts several processes at once (e.g. a web server and a task-queue worker), two processes can reach the create path simultaneously on a fresh database. The non-atomic check-then-create is a race: one process wins the `entity_id` primary key, the other's create fails on the unique constraint. The entry point must treat that lost race as success — re-read the now-present node and fall through to the descriptive-field upsert rather than raising (the `get_or_create` race-safety pattern). A create whose failure leaves no row behind is still a real error. (Originating failure: the loser raised and crashed a Steady Queue supervisor at spawn time, so collector jobs sat un-drained — `tap_cares` registry, 2026-05-28.)

**Materialization may be deferred.** Where `AppConfig.ready()` must stay read-only with respect to graph state (`req-tap-plugin-load-v0-ready-readonly`), the on-grid half may be split out of the registration entry point and applied later by an explicit reconcile under a bound actor, rather than written inline at `ready()`. The collector consumer does exactly this — `register_collector(...)` records the descriptor at `ready()`, and `reconcile_collector_nodes()` materializes the node afterward (see `spec-tap-cares-collector.md`). The pattern's identity and idempotency guarantees are unchanged; only the *timing and caller* of the on-grid write move. Under this split the concurrent-first-create race above does not arise for that consumer, because the single deferred reconcile — not each process's `ready()` — performs the write.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-dual-existence-pattern-1 | Two-Half Registration | Proposed | The pattern defines two coupled halves: a sub-grid registry entry and an on-grid `BaseModel` node, joined by a single registration entry point. | |
| req-grid-dual-existence-pattern-2 | One Caller Surface | Proposed | Plugin code calls one function (`register_<thing>(...)`) which performs both registrations; the caller is not required to coordinate them separately. | |
| req-grid-dual-existence-pattern-3 | Idempotent Reload | Proposed | Repeated calls with the same `scope:key` upsert the grid node without creating duplicates or destabilizing identity. | |
| req-grid-dual-existence-pattern-4 | Behavior Stays Sub-Grid | Proposed | Executable behavior (the registered class or callable) lives only on the sub-grid side. The grid node carries identity and descriptive metadata, never logic. | |
| req-grid-dual-existence-pattern-5 | Concurrent-Create Safe | Proposed | When two processes hit the create path at once on a fresh DB, the loser re-reads and falls through to the upsert rather than raising; only a create leaving no row behind is fatal. | |

---

## Deterministic Identity Derivation
----
RID: `req-grid-dual-existence-identity`
Status: `Proposed`

The on-grid node's `entity_id` is derived deterministically from the sub-grid registry key so the same capability always points at the same grid node across reloads and across grids.

The canonical derivation is UUIDv5 of the qualified registry key against a subsystem-specific namespace:

```python
entity_id = uuid.uuid5(NAMESPACE_<THING>, f"{scope}:{key}")
```

Each subsystem owns a namespace UUID that lives as a module-level constant alongside its `register_<thing>(...)` helper. Namespaces are distinct per subsystem so collisions across subsystems are impossible by construction.

The derivation rule means:

- The same plugin loaded on two TAP installations produces the same `entity_id` for the same capability. Cross-grid references (federation, audit, comparisons) align without coordination.
- Reloading a plugin does not produce a duplicate grid node. Identity is content-addressable; the registration call's job is to ensure the row exists and matches.
- The qualified registry key (`scope:key`) is the only input to identity, so renaming a capability is a real identity change — a new `scope:key` yields a new `entity_id`. This is intentional: a renamed capability is a new capability for grid-level provenance purposes.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-dual-existence-identity-1 | UUIDv5 From Registry Key | Proposed | The on-grid node's `entity_id` is `uuid5(NAMESPACE_<THING>, f"{scope}:{key}")`. | |
| req-grid-dual-existence-identity-2 | Subsystem-Specific Namespace | Proposed | Each subsystem declares its own namespace UUID constant, distinct from other subsystems. | |
| req-grid-dual-existence-identity-3 | Stable Across Reloads | Proposed | Repeated registration of the same `scope:key` produces the same `entity_id`. | |
| req-grid-dual-existence-identity-4 | Stable Across Grids | Proposed | The same registration on two TAP installations produces the same `entity_id` for the same capability. | |
| req-grid-dual-existence-identity-5 | Rename Is New Identity | Proposed | Changing `scope` or `key` changes `entity_id`; renamed capabilities are new capabilities for grid-provenance purposes. | |

---

## Grid Side Is Internal-Only
----
RID: `req-grid-dual-existence-internal-only`
Status: `Proposed`

The `BaseModel` subclass on the grid side of a dual-existence capability must declare `INTERNAL_ONLY: ClassVar[bool] = True` (see `req-grid-entity-internal` in `spec-grid-entity.md`). This closes the generic service-layer create/patch/replace/delete verbs and the GRIFT importer to ad-hoc creation of the capability.

The only legal creation path is the subsystem's `register_<thing>(...)` helper, which uses `_create_node_internal(...)` (see `req-grid-service-write-internal-create` in `spec-grid-service-write.md`) to construct the node while preserving the full write pipeline (validation, name sync from `get_name()`, version, history, provenance, FLIP).

The honest threat-model framing: this is a tripwire against accidental misuse, not a wall against in-process malicious code. Any in-process Python can import and call private helpers. The real security boundary lives at the network ingress layer (`tap_api`, panel POST handlers, etc.). Inside the process, the leading underscore convention plus the `INTERNAL_ONLY` flag are sufficient discipline.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-dual-existence-internal-only-1 | Grid Model Internal-Only | Proposed | Every dual-existence grid model sets `INTERNAL_ONLY: ClassVar[bool] = True`. | |
| req-grid-dual-existence-internal-only-2 | Generic CRUD Closed | Proposed | `create_node`, `patch_node`, `replace_node`, `delete_node`, and GRIFT import all reject dual-existence types via the existing INTERNAL_ONLY gate. | |
| req-grid-dual-existence-internal-only-3 | Trusted-Internal Sole Creator | Proposed | The subsystem's `register_<thing>(...)` helper is the only legal creator path, and it uses `_create_node_internal(...)` from `tap_grid.services`. | |
| req-grid-dual-existence-internal-only-4 | Tripwire Not Wall | Proposed | The pattern is documented as a discipline tripwire for accidental misuse; in-process malicious code is out of scope and is addressed at the network ingress layer. | |

---

## Pattern Flavors
----
RID: `req-grid-dual-existence-flavors`
Status: `Proposed`

Dual-existence comes in two recognizable flavors. This spec primarily addresses the second.

### Flavor 1: User-creatable + code-attached

The grid node is **freely user-creatable** through the public service layer (no `INTERNAL_ONLY`); the sub-grid side is a registered runner that gets bound to the node by a registry-key field on the node.

The canonical precedent is `tap_grid.Search`:

- Grid side: `Search(BaseModel)`, ordinary user-creatable rows representing saved queries.
- Sub-grid side: `search_runner_registry` — registered callables addressable by `scope:key`.
- Binding: each `Search` row carries a `runner_key` field that resolves to a registered callable at execution time.

This flavor is appropriate when the grid node represents a user-owned thing (a saved query, a user-authored rule), and the sub-grid registration is a library of execution backends the user can pick from.

The dual-existence pattern described in the rest of this spec is **not** the right shape for this flavor. The user-creatable flavor uses ordinary `create_node`, has no trusted-internal entry point, and does not derive identity from the registry key.

### Flavor 2: Plugin-declared capability

The grid node represents the **existence of a capability shipped by a plugin** — not a user-created thing. The sub-grid and grid sides arrive together through the plugin's registration call. The grid node is `INTERNAL_ONLY`.

Examples (current and anticipated):

- **`Collector`** (current): `tap_cares.registry.register_collector(...)` registers the runner class read-only at `ready()`; `tap_cares.registry.reconcile_collector_nodes()` materializes the on-grid `Collector` node afterward under a bound actor (deferred so `ready()` stays read-only per `req-tap-plugin-load-v0-ready-readonly`).
- **`Emitter`** (future): an emitter plugin declares an outbound integration; the grid `Emitter` node represents the capability for inspection, scheduling, and audit.
- **`Action`** / **`Alert`** (future): rule-based reactions to grid state; each `Action` is a grid node with a sub-grid implementation.
- **`Receiver`** (future): inbound event ingestion endpoints; same shape.
- **`Plugin`** (possible future, meta-level): each installed plugin as its own grid node, tracking which capabilities it registered and when it was last loaded.

This spec's requirements describe Flavor 2. Flavor 1 is documented here only so future authors don't try to force `Search`-shaped things through the `INTERNAL_ONLY` pattern.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-dual-existence-flavors-1 | Two Flavors Distinguished | Proposed | The spec distinguishes user-creatable + code-attached (Search) from plugin-declared capability (Collector, Emitter, Action). | |
| req-grid-dual-existence-flavors-2 | Pattern Applies To Flavor 2 | Proposed | The `INTERNAL_ONLY` + deterministic-identity + single-registration shape applies only to plugin-declared capabilities. | |
| req-grid-dual-existence-flavors-3 | Flavor 1 Documented | Proposed | The user-creatable flavor is described so authors do not misapply this spec to user-owned grid nodes. | |

---

## Naming Convention
----
RID: `req-grid-dual-existence-naming`
Status: `Proposed`

The dual-existence pattern uses a uniform naming family across subsystems. For a capability called `<Thing>`:

| Surface | Name | Location |
| --- | --- | --- |
| Grid model class | `<Thing>` (PascalCase) | `<owner_app>/models/<thing>.py` |
| Grid entity type slug | `<thing>` (snake_case) | `<Thing>.ENTITY_TYPE` |
| Sub-grid registry | `<thing>_registry` | `<owner_app>/registry.py` |
| Registration entry point | `register_<thing>(...)` | `<owner_app>/registry.py` |
| Trusted-internal helper | `_ensure_<thing>_node(...)` | `<owner_app>/registry.py` (colocated with `register_<thing>`) |
| Namespace UUID constant | `NAMESPACE_<THING>` | `<owner_app>/registry.py` |
| Registry key format | `scope:key` (validated) | per `req-grid-registry-scope-validators` |
| On-grid node default dimension | `{"<owner_app>": "<thing>"}` | per `<Thing>.DEFAULT_DIMENSIONS` |

This convention is already followed informally by the search system (`Search` + `search_runner_registry` + `register_search_runner`) and is being formalized by the collector system as the second example. Future subsystems should follow it directly.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-dual-existence-naming-1 | Uniform Names Across Subsystems | Proposed | Each dual-existence subsystem uses the `<Thing>` / `<thing>_registry` / `register_<thing>(...)` family. | |
| req-grid-dual-existence-naming-2 | Registry Key Format Validated | Proposed | The `scope:key` format is enforced via `validate_key` / `validate_scope` on the underlying `ScopedRegistry` per `req-grid-registry-scope-validators`. | |
| req-grid-dual-existence-naming-3 | Default Dimension Pattern | Proposed | The on-grid node's `DEFAULT_DIMENSIONS` is `{"<owner_app>": "<thing>"}`. | |

---

## Consolidated Registration Mechanism
----
RID: `req-grid-dual-existence-consolidation`
Status: `Backlog`

Today each subsystem implements its own trusted-internal helper (`_ensure_collector_node`, future `_ensure_emitter_node`, etc.) alongside its `register_<thing>` entry point. The helpers are near-identical: derive the deterministic UUIDv5, call `_create_node_internal` (or patch the existing node), set the descriptive fields.

Once the pattern has been built out across two or three subsystems and the right shape is visible from real code, the helpers should consolidate into a single shared mechanism — likely a generic registration utility in `tap_grid` that takes a model class, a registry-key namespace, and the descriptive fields, and does the deterministic-upsert work in one place.

The consolidation is deferred for the same reason most reusable abstractions are deferred: extracting from one case is premature, extracting from two is right-sized. Extracting from one (Collector alone) produces an abstraction shaped by KSI's specific concerns. Extracting from two or three (Collector plus Emitter plus Action) produces an abstraction that survives the next case unchanged.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-dual-existence-consolidation-1 | Backlog Requirement Exists | Backlog | A future shared registration mechanism is tracked as a named backlog requirement. | |
| req-grid-dual-existence-consolidation-2 | Triggered By Second Subsystem | Backlog | Implementation begins when a second dual-existence subsystem (Emitter, Action, or Receiver) starts being built and the duplication pattern is concrete. | |
| req-grid-dual-existence-consolidation-3 | Subsystem-Side API Unchanged | Backlog | Consolidation must preserve the plugin-facing `register_<thing>(...)` API; only the trusted-internal helpers move into shared code. | |

---

## Tear-Down Semantics
----
RID: `req-grid-dual-existence-teardown`
Status: `Backlog`

When a plugin is uninstalled, or when a previously-registered capability stops being declared on plugin reload, the on-grid node is left in place by default. Whether the capability is currently registered is a property derivable at runtime from `<thing>_registry.has(scope:key)`.

Future work should decide:

- Whether the grid node should be marked unavailable (status field) when the runner is missing, so Administrivia surfaces can render the difference clearly.
- Whether plugin uninstallation should tombstone (`Entity.deleted_at`) the capability's grid node, preserving the historical record but excluding it from live queries.
- Whether a separate `unregister_<thing>(...)` entry point should exist for plugins that want to cleanly retract a capability.

For v0, the conservative default is: grid nodes persist; runner-availability checks happen at execution time; tear-down is a deliberate operation tracked by this backlog requirement.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-dual-existence-teardown-1 | Backlog Requirement Exists | Backlog | Tear-down semantics are tracked as a named backlog requirement. | |
| req-grid-dual-existence-teardown-2 | Default Is Persistence | Backlog | v0 default is to leave the grid node in place when the runner is unregistered; availability is derived at execution time. | |
| req-grid-dual-existence-teardown-3 | Future Options Named | Backlog | The Backlog requirement lists the candidate tear-down strategies (status field, tombstone, explicit `unregister_<thing>`). | |

---

## Cross-References

- `tap_grid/specs/spec-grid-entity.md` — `req-grid-entity-internal` defines the `INTERNAL_ONLY` class attribute and its semantics.
- `tap_grid/specs/spec-grid-service-write.md` — `req-grid-service-write-internal-create` defines `_create_node_internal`, the trusted-internal entry point used by every dual-existence registration helper.
- `tap_grid/specs/spec-grid-registry.md` — `req-grid-registry-scope-validators` defines the `scope:key` format enforced by every dual-existence registry.
- `tap_grid/specs/spec-grid-search.md` — `Search` is the canonical example of the user-creatable + code-attached flavor (Flavor 1).
- `tap_cares/specs/spec-tap-cares-collector.md` — `Collector` is the first concrete example of the plugin-declared capability flavor (Flavor 2).

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed | Requirement is named but not yet built |
| Approved for Development | Requirement is accepted and ready to be implemented |
| In Development |  |
| Implemented |  |
| Verified |  |
| Refactoring |  |
| Deprecating |  |
| Deprecated | Not part of the current architecture and should not be implemented |
| Backlog | Tracked for future work; not in scope for current implementation |
