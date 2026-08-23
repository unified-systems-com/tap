---
title: Non-Grid Surface Inventory
date: 2026-06-24
status: review-inventory
audience:
  - developer
  - llm
related_docs:
  - docs/misc/doc-auth-per-app-standards.md
  - docs/misc/doc-auth-codepath-inventory.md
related_specs:
  - architecture.md
  - plan/road-rampart.md
  - specs/spec-tap-boot-v0.md
  - specs/spec-tap-settings.md
  - tap_grid/specs/spec-grid-registry.md
  - tap_plugins/specs/spec-tap-plugin-load-lifecycle-v0.md
---

# Non-Grid Surface Inventory

This pass maps the surfaces that need guard treatment beyond the obvious grid read and write paths. The core pattern that emerged is that TAP has several different kinds of state and control planes living beside the graph:

- grid data plane: `Entity`, `Edge`, typed `BaseModel` rows, batches, GRIFT, and Gryphon/search.
- graph-adjacent control plane: registries, type declarations, constraints, edge schemas, plugin manifests, page/panel descriptors, and startup declarations that shape what graph operations mean.
- non-grid durable control plane: users, capabilities, protected groups, settings-derived runtime configuration, task queues, scheduler cursors if treated as runtime metadata, and future boot state.
- runtime/host plane: page dispatch, panel rendering/actions, API router mounting, scheduler ticks, task execution, collector runners, boot phases, management commands, and Django admin.
- secret/external plane: secret files, secret registry, outbound collector clients, static client assets, and plugin-owned code references.

The useful framing is not "everything must be a grid operation." It is "everything needs an owning boundary." Grid mutations should go through batch/service machinery. Non-grid state needs app-specific service boundaries, explicit actors/capabilities, schema validation, and loud failure when a surface appears outside its contract.

## Cross-Cutting Guard Types

These are the guard families that recur across apps:

- Registration guard: startup registries should accept only validated, conforming declarations; duplicates and malformed declarations should refuse boot or fail the current operation loudly.
- Invocation guard: page/panel actions, API handlers, scheduler ticks, task bodies, collector runs, boot handlers, and management commands need an explicit actor/context before doing protected work.
- Mutation guard: grid-backed writes go through grid service/batch paths; non-grid durable writes go through an app-owned service or a tightly named bootstrap command; ephemeral runtime cursors need a documented carveout.
- Configuration guard: declarative files need schema validation, path confinement, unknown-key rejection, and validate-before-apply behavior.
- Secret guard: configuration carries secret references, not secret values; consumers validate secret kind/data shape; logs and grid rows never receive raw secret values.
- External-operation guard: outbound clients need explicit configuration, timeouts, bounded retries, redaction, and, where appropriate, HTTPS-only or host allowlist rules.
- Conformance guard: plugin, panel, collector, editor, search, API router, and boot-handler registrations should be protocol/base-class checked rather than duck-typed.
- Operator/dev guard: dangerous commands and bypasses should be DEBUG/test-only or explicit bootstrap surfaces, not ambient runtime affordances.
- Observability guard: guard failures should become structured `Flaw`s or clear command errors, not swallowed exceptions.
- Static-analysis guard: direct ORM graph writes, direct graph ORM reads in user surfaces, ad hoc recurring tasks, mutable graph admins, module-search usage, and startup DB writes are all candidates for CI ratchets.

## tap_grid

### Runtime Registries

The grid app owns the generic registry primitives and several high-impact registries:

- `tap_grid.registry.meta_registry`
- `tap_grid.registry.entity_model_registry`
- `tap_grid.registry.search_runner_registry`
- `tap_grid.constraints.node_constraint_registry`
- `tap_grid.constraints.edge_type_registry`
- `tap_grid.constraints.edge_property_schema_registry`
- `tap_grid.constraints.edge_default_dimensions_registry`

These are in-memory control-plane surfaces. They do not directly mutate grid rows, but they decide which types exist, which edges are valid, which schemas apply, and which read/query backends can run. A bad registration can therefore change the security meaning of later grid operations.

Current code already has several registry-local guards:

- `Registry` rejects duplicate keys by default.
- `Registry` allows duplicate handling only when an explicit `merge_fn` is supplied.
- `ScopedRegistry` rejects duplicate `(scope, key)` pairs by default.
- `ScopedRegistry` can validate scope/key tokens at both registration and lookup.
- failed validator registration leaves the registry unchanged.
- `_reset_for_testing(...)` is the only provided bulk-mutation helper and is explicitly test-scoped by name/docstring.
- `meta_registry` gives a read-only operational inventory through admin tooling.

The missing guard is a lifecycle guard: there is not yet a generic `freeze()` / `is_frozen` / mutation-phase mechanism that refuses `register()` after startup. So today the registries are append-only by API shape and convention, not by runtime phase enforcement. The recommendation is to make this lifecycle explicit on the shared registry primitives:

- registries start mutable during construction/startup;
- `freeze()` marks a registry immutable once app/plugin/boot registration completes;
- `is_frozen` makes that state inspectable from tests, admin tooling, and health checks;
- `register()` refuses mutation after freeze, even for merge-enabled registries;
- `_reset_for_testing(...)` remains the test-only escape hatch and should be the only path that can deliberately replace state;
- future dynamic plugin install/uninstall should use a designed transaction or shadow-registry publish flow, not direct mutation of frozen registries.

Guard shape:

- registrations should be startup-only or explicitly lifecycle-managed;
- each registry should have a description and owner;
- duplicate/merge behavior should be deliberate and tested;
- freeze behavior should be available on the shared `Registry` / `ScopedRegistry` primitives and applied before request/task handling;
- values should be validated against expected class/protocol/schema;
- search runner registration should remain feature-gated/inert unless explicitly enabled.

### Durable Type Metadata

`EntityType` is durable control-plane metadata. Current code writes it from startup paths, including core app `ready()` and plugin manifest registration. That is graph-adjacent, not ordinary grid data, but it is still a database mutation with security and lifecycle implications.

Guard shape:

- decide whether `EntityType` writes become boot/type-service operations, an explicit `grid.admin` capability, or a named startup exemption;
- avoid silent app-start DB mutation once boot machinery exists;
- keep type declarations declarative and app-owned;
- fail loudly on slug/path/app ownership violations.

### Django Admin

The Django admin currently exposes graph-backed models and type metadata as an operator plane. `Entity`, `Edge`, `EntityType`, `Batch`, and some app-owned `BaseModel` subclasses can be edited through admin paths that do not naturally express TAP batch/service semantics.

Guard shape:

- graph-backed admin screens should be read-only by default, or admin actions should route through explicit service/batch verbs;
- type metadata admin should be treated as a high-privilege control-plane surface;
- Django staff/superuser permissions should not be the only guard for TAP-managed graph mutation.

## tap_auth

Auth has legitimate non-grid durable state:

- `User`
- `Capability`
- `ProtectedGroup`
- projected Django `Group`/`Permission`
- future auth provider configuration
- caller context and authorization ledger runtime state

`sync_auth` is currently the explicit bootstrap command for capabilities, protected groups, and built-in program actors. That direct ORM shape is defensible as bootstrap machinery, but it should stay named and isolated.

Guard shape:

- user/provider/group/capability management needs an auth-owned service boundary distinct from the grid service layer;
- protected built-ins need lifecycle invariants enforced outside admin convenience paths;
- bootstrap sync should be explicit, idempotent, and eventually owned by the boot auth phase;
- request, task, scheduler, collector, and boot entrypoints need ledger/context reset and actor binding;
- `user=None` should remain invalid at protected boundaries, with public surfaces explicitly classified rather than falling through.

## tap_plugins

The plugin system is a major non-grid control plane. Current surfaces include:

- `tap-plugin.toml`
- declared model metadata;
- edge JSON declaration files;
- editor descriptors;
- module search runners;
- bundled GRIFT declarations;
- plugin API routers;
- plugin validation commands;
- plugin `AppConfig.ready()` registration.

The manifest system is already the right direction: declarative, readable, and path-confined. The remaining risk is that not every plugin surface is manifest-shaped yet, and some startup registration paths still perform durable metadata writes.

Guard shape:

- expand manifest declarations over time for panels, collectors, API routers, static/client assets, and other plugin-owned surfaces;
- keep plugin file paths confined to the plugin directory;
- reject unknown manifest sections and malformed declarations;
- require plugin `ready()` methods to chain to the base loader and avoid graph mutation;
- give runs-level plugin validation an explicit validation actor and rollback contract;
- require plugin API routers to mount only under their namespace and declare capability/public behavior;
- keep module search behind a deliberate feature flag.

## tap_web

`tap_web` is where grid-backed content meets non-grid host behavior. Pages and panels are graph objects, but routing, rendering, action dispatch, synthetic panel composition, editor registration, and reserved URL prefixes are host surfaces.

Current surfaces include:

- page route catch-all;
- `/panel` and `/object` host routes;
- reserved URL prefix registry;
- `panel_type_registry`;
- editor registry;
- panel render/action/config code;
- synthetic panel composition;
- page navigation and breadcrumb discovery;
- template and HTMX request handling.

`panel_type_registry` uses the shared `ScopedRegistry` duplicate guard. The editor registry is weaker: it is currently a plain dict keyed by entity type, and `register_editor(...)` overwrites an existing descriptor for the same entity type. Recommendation: move the editor registry onto the shared registry abstraction, or give it equivalent semantics explicitly: duplicate policy, description/provenance, test-only reset, and `freeze()` / `is_frozen` lifecycle behavior.

This is the main place where a standard layer above the grid service layer would pay off. The grid can say whether a user may read or mutate graph state, but the host layer still needs to decide whether a user may invoke a panel action, edit a panel config, resolve a target object, render a synthetic composition, or discover a page path.

Guard shape:

- create a page/panel host service layer that owns page lookup, panel lookup, render, config, and action dispatch;
- require panel types to implement a real base class/protocol with declared capabilities and supported operations;
- route panel config and action writes through the host layer, which then delegates to grid service/batch operations when graph state changes;
- classify page/panel discovery separately from object read authorization;
- make auth failures fail closed and visible instead of being swallowed as "panel unavailable";
- keep route-prefix reservation as a boot/test-enforced control-plane rule.

## tap_viz

`tap_viz` is mostly graph-modeled, but it contributes host/runtime surfaces through panel registration and client runtime definitions:

- `GraphPanelType` registration into `tap_web`;
- projection/layout/arrangement resolution;
- navigation rules inside graph panel configuration;
- static JavaScript layout file references such as layout `js_file`;
- admin registration for layout-like graph objects.

Guard shape:

- treat graph panel resolution as a `tap_web` panel host operation, not an independent read path;
- validate navigation rules as URL-producing policy, especially external URLs;
- confine client runtime asset references to known static paths;
- avoid mutable admin paths for graph-backed visualization models unless they route through service verbs.

## tap_cares

CARES has the densest set of non-grid runtime surfaces:

- collector runner registry;
- collector node dual-registration;
- task queue and task bodies;
- scheduler tick and schedule claim logic;
- schedule runtime cursors;
- collection job runtime state;
- secret file loader and secret registry;
- boot collector profile command;
- dev validation commands;
- external clients in collectors;
- collector result accumulators and GRIFT submission.

The collector registry is especially important because it is dual-existence: one side is an in-memory Python runner class; the other side is an on-grid `Collector` node. That is not just a grid write concern. It is a binding between executable code and graph-visible identity.

Guard shape:

- collector registration should be declarative and app/plugin-owned, with runner-class conformance checks;
- the code-to-node binding should be boot/service-owned rather than a silent broad-exception startup write;
- human trigger authorization should happen before switching to the `tap_collector` runtime actor;
- scheduler ticks should bind a `tap_scheduler` actor at the boundary;
- task bodies should bind a `tap_collector` actor/context before patching jobs, linking batches, or submitting GRIFT;
- scheduler cursor fields need a decision: either they are grid facts updated through service/batch paths, or they are explicit runtime metadata with a named carveout;
- collector code should be statically checked for direct graph ORM writes and direct node/edge creation outside GRIFT/batch submission;
- secret references should be resolved through the secret registry only, with kind/schema validation at the consumer;
- outbound collectors should enforce timeouts, bounded retries, redaction, and source-specific safety rules.

## tap_boot

`tap_boot` is not fully built yet, but the boot spec already gives TAP the right shape for a non-grid orchestration plane:

- boot profiles;
- app-registered section handlers;
- schema validation;
- semantic validation;
- plan/apply separation;
- fixed boot phases;
- boot actor creation before privileged work;
- population actions such as plugin GRIFT import and boot collector firing.

Boot should become the owner for several things that currently leak through startup hooks or development commands.

Guard shape:

- app boot sections validate before any apply step;
- handlers receive only their own section data;
- boot actor and auth phase run before population work;
- no secret values in boot profiles, only secret references;
- startup DB writes move to boot-owned apply phases or explicit management commands;
- boot apply failures should refuse boot or abort the current profile, not continue silently.

## tap_api

The API layer is mostly transport and routing, but that still makes it a non-grid guard surface:

- `NinjaAPI` construction;
- session authentication;
- exception-to-HTTP translation;
- core router inclusion;
- plugin router discovery and mounting;
- plugin route namespace collision detection;
- public API root;
- unauthenticated or lightly-authenticated schema/discovery endpoints such as entity-type listing.

Guard shape:

- every route should be classified as public, authenticated-public, capability-gated, or internal/dev;
- plugin routers should declare their route/capability behavior and remain namespace-confined;
- duplicate mounts should refuse boot;
- existence-sensitive endpoints should authorize before lookup or deliberately document public discovery behavior;
- auth and authz exceptions should translate consistently and avoid leaking protected object existence.

## Settings, Static Assets, Logging, And Dev Tools

Several cross-app surfaces are not grid data but still affect security posture:

- deployment settings such as `TAP_SECRETS_ROOT`, task backend settings, and session/product labels;
- static assets referenced by graph or plugin declarations;
- logging configuration and log-site-id validation;
- `Flaw` reporting;
- management commands such as plugin validation, GRIFT import, boot collector firing, sync auth, purge, and dev validation spikes.

Guard shape:

- mutable deployment configuration should eventually belong to boot/config machinery, not scattered app-specific settings;
- graph or manifest references to static/client assets need path confinement;
- dangerous management command flags should stay DEBUG/test gated;
- command output should identify which actor/capability/bootstrap mode is in effect;
- `Flaw` should be used for structural invariant violations that require operator attention.

## Static Analysis Candidates

These checks would give TAP earlier warning when a new bypass surface appears:

- direct `objects.create`, `save`, `delete`, `update`, or `_internal` grid mutation outside approved service internals, migrations, tests, and named bootstrap code;
- direct graph ORM reads from page/panel/API/user-facing paths where Gryphon/search should be the path;
- DB writes inside `AppConfig.ready()`;
- `@recurring` task declarations outside the scheduler owner;
- mutable Django admin classes for graph-backed models;
- ad hoc module-level dict registries, especially control-plane registries that should use `Registry` or `ScopedRegistry`;
- calls to `register()` after the registry freeze phase;
- plugin `ready()` overrides that fail to call `super().ready()`;
- panel registrations that do not subclass the approved panel base;
- collector classes that import graph models/services directly instead of emitting GRIFT through collector APIs;
- module search runner registration or invocation when the feature flag is disabled;
- manifest path declarations that escape plugin roots;
- secret value logging or use of raw secret dictionaries outside validation helpers.

## Suggested Near-Term Decisions

1. Define the TAP state-boundary taxonomy explicitly: grid data, graph-adjacent control plane, non-grid durable state, ephemeral runtime state, external/secret state, and operator/dev surfaces.
2. Decide the fate of `EntityType` writes: boot/type-service, `grid.admin` service, or a narrowly documented startup exemption.
3. Treat Django admin as a first-class operator surface and make graph-backed admin mutation either read-only or service-routed.
4. Specify the `tap_web` page/panel host layer before deeper authz work; this is the clearest missing architecture boundary.
5. Specify task/scheduler/collector actor binding before more CARES authz work; background execution currently needs an explicit runtime boundary.
6. Let `tap_boot` absorb startup DB writes, auth sync, plugin population, and boot collector firing rather than leaving them in app `ready()` or development commands.
7. Extend plugin manifests gradually so plugins declare all host surfaces they contribute, not just models/edges/editors/searches/GRIFT.
8. Add `freeze()` / `is_frozen` lifecycle semantics to `Registry` and `ScopedRegistry`, and migrate weaker plain-dict registries such as `tap_web`'s editor registry onto that standard or an equivalent explicit policy.
9. Add static-analysis ratchets once the allowlist is explicit, starting with startup DB writes, mutable graph admin, ad hoc dict registries, post-freeze registry mutation, panel direct ORM access, and collector direct graph writes.

The short version: batch and Gryphon guard the graph data plane, but TAP also needs guard contracts for registration, host invocation, boot orchestration, background runtime, secrets/external clients, and operator tooling. Those contracts should be simpler than a giant policy language: named boundaries, explicit actors, declarative declarations, fail-loud registration, and static analysis for known bypass shapes.
