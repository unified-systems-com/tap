# Plugin Load Lifecycle v0 Specification

## Philosophy

Plugin load is the first durable contract between TAP core and TAP plugins. In v0 that contract should stay small, explicit, and inspectable: a plugin should declare what TAP-managed model types it introduces, what edge types it contributes, what editor descriptors it provides, what search runners it contributes, and what bundled GRIFT data it makes available, and TAP should know how to load that declaration consistently at startup.

This specification is intentionally narrower than a full plugin lifecycle. It does not define install, uninstall, dependency resolution, enablement state, or migration orchestration. It focuses only on what it means for a plugin to be present in a TAP installation and what must happen when that plugin loads.

The guiding principle for v0 is that the plugin's load shape should be reviewable without digging through arbitrary Python. Python remains the implementation path for execution, but `tap-plugin.toml` should be the high-level declaration surface so humans and future tooling can quickly answer: what models does this plugin add, what edge types does it contribute, what editors does it provide, what searches does it contribute, and what GRIFT files does it publish?

## Goals

|    |              |                                                                                 |
| :---: | ---       | ---                                                                             |
| 1. | Explicit     | Plugin load behavior is defined by a small, specific contract rather than ad hoc startup code |
| 2. | Inspectable  | A plugin exposes a high-level manifest declaring TAP-managed model, edge, editor, search, and GRIFT surfaces |
| 3. | Minimal      | v0 defines only startup/load behavior and defers install, uninstall, and dependencies |
| 4. | Evolvable    | The v0 shape is simple enough to support future plugin tooling and richer lifecycle work |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-plugin-load-v0-scope | [Plugin Load Scope](#plugin-load-scope) | Implemented | Defines what this v0 spec covers and excludes |
| req-tap-plugin-load-v0-contract | [Plugin Load Contract](#plugin-load-contract) | Implemented | Defines what TAP considers plugin load in v0 |
| req-tap-plugin-load-v0-ready-readonly | [Ready Is Read-Only For Graph State](#ready-is-read-only-for-graph-state) | Implemented | `ready()` must not query or mutate TAP-managed graph state |
| req-tap-plugin-load-v0-ready-chain | [Ready Overrides Must Chain To Super](#ready-overrides-must-chain-to-super) | Implemented | A `ready()` override must call `super().ready()` or the manifest never loads |
| req-tap-plugin-load-v0-manifest | [Plugin Manifest Declaration](#plugin-manifest-declaration) | Implemented | High-level declaration surface for models, edges, and GRIFT files |
| req-tap-plugin-load-v0-models | [TAP-Managed Model Publication](#tap-managed-model-publication) | Implemented | Models introduced by a plugin are part of the load contract |
| req-tap-plugin-load-v0-grift | [Bundled GRIFT Publication](#bundled-grift-publication) | Implemented | GRIFT files are declared by the plugin as loadable bundled data |
| req-tap-plugin-load-v0-upsert | [GRIFT Upsert Policy](#grift-upsert-policy) | Implemented | Bundled plugin GRIFT uses strict upsert semantics in v0 |
| req-tap-plugin-load-v0-order | [Load Order And Execution Phases](#load-order-and-execution-phases) | Implemented | Clarifies manifest, class-definition, and startup phases |
| req-tap-plugin-load-v0-nongoals | [v0 Non-Goals](#v0-non-goals) | Proposed | Explicitly deferred lifecycle work |

### Plugin Load Scope
----
RID: `req-tap-plugin-load-v0-scope`
Status: `Proposed`

This specification defines the plugin load lifecycle for TAP-managed plugin capabilities only.

#### Status Details
Proposed as the first formal plugin lifecycle spec. It is meant to anchor upcoming plugin creation and refactoring work without overcommitting to a full package manager or plugin runtime.

#### Implementation
For this specification:

- a plugin is a Django app added to `INSTALLED_APPS`
- the plugin must use the TAP plugin contract rather than behaving as an arbitrary Django app
- the covered surfaces are:
  - TAP-managed model types introduced by the plugin
  - edge types contributed by the plugin
  - editor descriptors declared by the plugin
  - search runners declared by the plugin
  - bundled GRIFT files declared by the plugin
  - plugin startup registration needed to expose those surfaces to TAP

This specification does not govern:

- non-TAP Django models as a general plugin concern
- Python packaging or distribution
- installation or uninstallation workflows
- runtime enable/disable state
- inter-plugin dependency resolution

#### Development
This keeps the first plugin lifecycle spec aligned with the stated goal: formalize how plugins add models and add new data via GRIFT when they load, without prematurely designing the rest of the lifecycle.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-load-v0-scope-1 | TAP Surfaces Only | Proposed | The v0 load lifecycle covers TAP-managed plugin model, edge, editor, search, and GRIFT declaration surfaces only. | |
| req-tap-plugin-load-v0-scope-2 | Django App Basis | Proposed | A v0 TAP plugin is still a Django app registered in `INSTALLED_APPS`. | |
| req-tap-plugin-load-v0-scope-3 | Lifecycle Narrowing | Proposed | Install, uninstall, and dependency management are explicitly outside this v0 scope. | |

#### Future
Later lifecycle specs may extend this baseline to include installation state, compatibility checks, dependency resolution, or operational health reporting.

### Plugin Load Contract
----
RID: `req-tap-plugin-load-v0-contract`
Status: `Proposed`

Plugin load in v0 is a specific startup contract, not an abstract idea.

#### Status Details
Proposed to make plugin startup behavior precise and auditable. TAP already relies on Django app loading plus `TapPluginConfig.ready()`, but the lifecycle has not yet been specified as a first-class contract.

#### Implementation
In v0, plugin load means:

1. the plugin's Django app is present in `INSTALLED_APPS`
2. its Python modules are imported by Django
3. any plugin `BaseModel` subclasses register their TAP model types through existing class-definition hooks
4. the plugin exposes `tap-plugin.toml` describing its TAP-managed model, edge, editor, search, and GRIFT surfaces
5. the plugin's `TapPluginConfig.ready()` execution completes without error
6. TAP applies the startup registrations defined by the plugin contract

`TapPluginConfig.ready()` is the v0 execution hook for plugin load. This is not just an implementation detail for this version; it is the formal startup boundary for the contract defined here.

The load contract is satisfied when TAP can determine, from the plugin's declared surfaces and startup execution, what model types, edge types, editor descriptors, search runners, and bundled GRIFT data the plugin contributes.

#### Development
This requirement intentionally chooses a concrete boundary instead of a softer “plugins somehow load” description. That gives scaffolding and future tests a stable target.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-load-v0-contract-1 | Ready Is Canonical Hook | Proposed | `TapPluginConfig.ready()` is the canonical v0 execution hook for plugin load behavior. | |
| req-tap-plugin-load-v0-contract-2 | Declared Surfaces Visible | Proposed | A loaded plugin exposes its TAP-managed model, edge, editor, search, and GRIFT surfaces through a declared contract rather than only implicit startup side effects. | |
| req-tap-plugin-load-v0-contract-3 | Load Completes Or Fails | Proposed | Plugin load is treated as a concrete startup step that either completes successfully or fails during app startup. | |

#### Future
If TAP later introduces a richer lifecycle manager, it may wrap or replace direct `ready()` usage, but it should preserve the same observable plugin load contract unless a later spec intentionally changes it.

### Ready Is Read-Only For Graph State
----
RID: `req-tap-plugin-load-v0-ready-readonly`
Status: `Implemented`

`TapPluginConfig.ready()` must not query or mutate TAP-managed graph state. Its job is metadata registration only: edge types, model types, editor descriptors, search runners, and any registry-level wiring that comes purely from the plugin manifest. Any work that needs to read or write the graph database — most notably grift bundle import — is the responsibility of explicit operator-invoked tooling, not of plugin startup.

#### Status Details
Implemented as of 2026-04-27. Earlier versions of `TapPluginConfig.ready()` ran `_import_grift_from_manifest()` on every startup. That call has been removed because it (a) violated this rule, (b) ran during every `manage.py` invocation including `migrate`, contending for resources and producing the `RuntimeWarning: Accessing the database during app initialization is discouraged` Django emits, and (c) made startup loud and brittle when bundle JSON drifted from current schemas.

The same code path is still available — and is now the only path — through the existing `manage.py import_plugin_grift` management command.

#### Implementation
- `TapPluginConfig.ready()` retains: `_load_and_validate_manifest`, `_register_edges_from_manifest`, `_register_types_from_manifest`, `_register_editors_from_manifest`, `_register_searches_from_manifest`. None of these touch graph state.
- `_import_grift_from_manifest` and its call site are removed from `tap_plugins/base.py`.
- Operator path: `manage.py import_plugin_grift --all` iterates plugins in `INSTALLED_APPS` order via `apps.get_app_configs()`, which gives the deterministic dependency order developers control through settings.
- Spawn workflow: `scripts/spawn-session.sh` already calls `import_plugin_grift --all` as step 6 — no script change needed for sessions.
- Primary-stack workflow: developers running `manage.py migrate` against the primary stack must follow with `manage.py import_plugin_grift --all` to seed plugin data. Documented in CLAUDE.md and the Phase 1 onboarding doc.

#### Development
This is a deliberate alignment with CLAUDE.md's "background tasks must not silently mutate core graph state in v0; all graph mutations must remain explicit and auditable" and "use Django signals sparingly, require approval before writing them, and document them well." It also matches Django's posture toward migrations: a separate, explicit operator action rather than something that quietly happens during server startup.

The cost is a manual step for developers running migrate against the primary stack. The benefit is that arbitrary `manage.py` invocations no longer hit the database, plugin startup is observably fast, and bundle validation errors no longer get rebroadcast on every server reload.

A future refinement may introduce a richer "plugin data manager" or `post_migrate` integration if developer experience demands it, but that requires its own spec and explicit approval per the signals rule.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-load-v0-ready-readonly-1 | No DB access in ready() | Proposed | `TapPluginConfig.ready()` performs no queries or writes against TAP-managed graph state. | |
| req-tap-plugin-load-v0-ready-readonly-2 | Grift import is operator-invoked | Proposed | The only supported path for grift bundle import is `manage.py import_plugin_grift`. | |
| req-tap-plugin-load-v0-ready-readonly-3 | INSTALLED_APPS order honored | Proposed | `import_plugin_grift --all` imports plugins in `INSTALLED_APPS` order so dependent plugins (e.g. `aws_core` after `computing_core`) load deterministically. | |
| req-tap-plugin-load-v0-ready-readonly-4 | Spawn workflow unchanged | Proposed | `scripts/spawn-session.sh` continues to seed plugin data via the management command (step 6), without relying on `ready()` autorun. | |

#### Future
A separate spec may evaluate whether a `post_migrate` signal or a "plugin data manager" should auto-trigger seeding for fresh DBs in dev environments. That work would need to satisfy CLAUDE.md's signals rule (require approval, document well) and would not relax this requirement; it would layer on top of it.

### Ready Overrides Must Chain To Super
----
RID: `req-tap-plugin-load-v0-ready-chain`
Status: `Implemented`

A `TapPluginConfig` subclass that overrides `ready()` MUST call `super().ready()`. The base `ready()` is the sole carrier of the load contract's startup phase (req-tap-plugin-load-v0-order, req-tap-plugin-load-v0-contract): it loads and validates `tap-plugin.toml` and performs edge/type/editor/search registration. An override that omits `super().ready()` silently severs the plugin from its manifest — `config.manifest` stays `None`, no registration runs, and `manage.py import_plugin_grift` skips the plugin with "No manifest loaded".

#### Status Details
Implemented 2026-05-18. The regression was introduced 2026-05-17 in the aws_core steampipe-collector shell: `AwsCoreConfig.ready()` registered a collector but never chained to `super()`, and the steampipe excision preserved the broken override as a bare `return`. The failure is silent at startup (Django logs nothing; the plugin's model classes still import), so it only surfaced downstream when `scripts/spawn-session.sh` aborted mid-spawn on the non-zero `import_plugin_grift` exit. Fixed by chaining, and guarded by `tap_plugins/tests/test_plugin_ready_contract.py`.

#### Implementation
- Every `TapPluginConfig` subclass that defines its own `ready()` makes `super().ready()` its first statement, before any plugin-specific registration (collectors, panels). `administrivia`, `fedramp_20x_ksi`, and `genericom` already followed this; `aws_core` now does too. `computing_core` and `lotr` do not override `ready()` and inherit the base contract unchanged.
- The invariant is enforced two ways in `tap_plugins/tests/` (plugin-system machinery, not per-plugin behavior — see `specs/spec-tap-testing.md`):
  - a behavioral check that every loaded `TapPluginConfig` exposes a non-`None` `manifest` after startup (catches a missing manifest from any cause);
  - a structural check that any subclass-defined `ready()` source contains a `super().ready()` call (a sharper diagnostic that names the offending class).

#### Development
The behavioral check is the true invariant; the structural check exists because the symptom is otherwise silent and easy to reintroduce when adding a collector/panel registration to a plugin that previously used a bare `pass`. Keeping both is cheap and the structural failure message points directly at the fix ("make `super().ready()` the first statement").

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-load-v0-ready-chain-1 | Override Chains To Super | Implemented | Any `TapPluginConfig` subclass that overrides `ready()` calls `super().ready()`. | Structural source check |
| req-tap-plugin-load-v0-ready-chain-2 | Manifest Always Loaded | Implemented | Every loaded `TapPluginConfig` exposes a non-`None` `manifest` after startup. | Behavioral invariant |
| req-tap-plugin-load-v0-ready-chain-3 | Machinery-Level Guard | Implemented | The invariant is enforced by a `tap_plugins` machinery test, not per-plugin tests. | |

#### Future
A later plugin loader service could enforce the chain structurally — e.g. a sealed template method where the base owns the load steps and plugins supply a separate `register()` hook that cannot bypass them — retiring the convention-plus-test guard.

### Plugin Manifest Declaration
----
RID: `req-tap-plugin-load-v0-manifest`
Status: `Proposed`

Every v0 plugin should expose a manifest file, `tap-plugin.toml`, that declares its TAP-managed load surfaces at a high level.

#### Status Details
Proposed to make plugin shape reviewable without requiring readers to infer intent from arbitrary Python code.

#### Implementation
`tap-plugin.toml` is the canonical declaration surface for plugin load metadata in v0. The manifest should be simple, static, and human-reviewable.

The v0 manifest declares, at minimum:

- manifest schema version
- plugin version
- plugin identity information sufficient to name the plugin
- the TAP-managed model types the plugin introduces
- the edge types the plugin contributes
- the editor descriptors the plugin provides
- the search runners the plugin provides
- the bundled GRIFT files the plugin publishes as part of its loadable data surface

The v0 manifest is intentionally high-level, but it is no longer abstract. In v0:

- the manifest file name is fixed as `tap-plugin.toml`
- the manifest is purely declarative
- unknown keys are rejected
- sections for `models`, `edges`, `editors`, `searches`, and `grift` may be omitted when empty

This specification still leaves room for the dedicated manifest spec to define the exact TOML structure in detail.

The key point is contractual: a plugin must have one inspectable declaration surface that a human or tool can read to understand what TAP-managed types and GRIFT bundles the plugin brings with it.

Python code remains responsible for runtime behavior, but the manifest is the source of truth for review and discovery of these high-level load surfaces.

#### Development
This requirement gives TAP a middle path between two bad extremes:

- hiding all plugin meaning in Python startup code
- overdesigning a heavyweight plugin package format before enough plugins exist

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-load-v0-manifest-1 | Manifest Exists | Proposed | A v0 plugin exposes `tap-plugin.toml` describing its TAP-managed load surfaces. | |
| req-tap-plugin-load-v0-manifest-2 | Identity And Versions Declared | Proposed | The manifest declares plugin identity, manifest schema version, and plugin version. | |
| req-tap-plugin-load-v0-manifest-3 | Models Declared | Proposed | The manifest lists the TAP-managed model types introduced by the plugin. | |
| req-tap-plugin-load-v0-manifest-4 | Edges Declared | Proposed | The manifest lists the edge types contributed by the plugin. | |
| req-tap-plugin-load-v0-manifest-5 | Editors Declared | Proposed | The manifest lists the editor descriptors provided by the plugin. | |
| req-tap-plugin-load-v0-manifest-6 | Searches Declared | Proposed | The manifest lists the search runners provided by the plugin. | |
| req-tap-plugin-load-v0-manifest-7 | GRIFT Files Declared | Proposed | The manifest lists the bundled GRIFT files published by the plugin. | |
| req-tap-plugin-load-v0-manifest-8 | Strict Declarative Surface | Proposed | The manifest is purely declarative and rejects unknown keys in v0. | |

#### Future
The manifest may later grow to include dependency declarations, compatibility ranges, migration hooks, installation metadata, UI contributions, API routers, or capability flags.

### TAP-Managed Model Publication
----
RID: `req-tap-plugin-load-v0-models`
Status: `Proposed`

When a plugin adds models in v0, the relevant concern is TAP-managed model publication rather than arbitrary Django model definition.

#### Status Details
Proposed to match current architecture, where TAP-managed graph types already participate in registry-backed behavior distinct from plain Django models.

#### Implementation
For this specification, “adding models” means the plugin introduces TAP-managed graph model types, typically concrete `BaseModel` subclasses and related TAP type declarations.

This happens in two layers:

1. class-definition-time model registration
2. startup-time plugin metadata registration

At class-definition time, concrete `BaseModel` subclasses already register their `ENTITY_TYPE` and related constraint/service metadata through existing `tap_grid` mechanisms.

At plugin startup time, the plugin load contract publishes the plugin's higher-level type declaration metadata, including the type catalogue information that TAP exposes for discovery and presentation.

The plugin manifest must declare the TAP-managed model types introduced by the plugin using explicit entries rather than directory-wide implicit loading.

Each model declaration is conceptually one TAP type entry, not merely one Python module entry. In v0 each declared model entry should identify:

- the TAP type slug
- the concrete Python class path that implements that type

The manifest is the review and discovery source of truth for the plugin's TAP model surface. The loader validates that the declared concrete class exists, is a concrete TAP-managed model, and agrees with the declared TAP type slug. A mismatch is a plugin load error.

Plugins may organize model code under a `models/` directory by convention. That directory convention improves readability, but directory contents alone do not determine what loads. Only manifest-declared model entries are part of the plugin load contract.

#### Development
This split matters. TAP already has a real distinction between:

- model class registration that happens when Python classes are defined
- plugin startup registration that publishes plugin-owned type metadata

The specification should preserve that distinction instead of flattening both into one vague “load models” step.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-load-v0-models-1 | TAP Model Meaning | Proposed | In this spec, plugin “models” means TAP-managed model types, not arbitrary Django models. | |
| req-tap-plugin-load-v0-models-2 | Explicit Type Entries | Proposed | The plugin manifest declares TAP-managed model types with explicit entries rather than implicit directory loading. | |
| req-tap-plugin-load-v0-models-3 | Concrete Class Paths | Proposed | Each declared model entry identifies a concrete Python class path for the TAP-managed model type. | |
| req-tap-plugin-load-v0-models-4 | Loader Validates Model Contract | Proposed | The loader validates that each declared class exists, is a concrete TAP-managed model, and matches the declared type slug. | |
| req-tap-plugin-load-v0-models-5 | Class Definition Still Matters | Proposed | The manifest does not replace concrete TAP model classes or existing class-definition registration hooks. | |
| req-tap-plugin-load-v0-models-6 | Startup Publishes Type Metadata | Proposed | Plugin load includes startup publication of plugin-owned TAP type metadata needed for discovery and presentation. | |
| req-tap-plugin-load-v0-models-7 | Models Directory Is Convention Only | Proposed | A plugin may organize model code under `models/`, but only manifest-declared entries participate in plugin load. | |

#### Future
Later specs may tighten how manifest model declarations map to concrete classes and may require startup cross-checks that catch drift between manifest declarations and runtime registrations.

### Bundled GRIFT Publication
----
RID: `req-tap-plugin-load-v0-grift`
Status: `Proposed`

Plugins may publish bundled GRIFT data as part of their declared load surface.

#### Status Details
Proposed as the v0 answer to “adding new data via GRIFT” while keeping declaration separate from execution mechanics.

#### Implementation
The plugin manifest declares the GRIFT files that belong to the plugin. These files are part of the plugin's bundled data surface.

In v0, plugin load requires declaration of bundled GRIFT files, not automatic import inside arbitrary plugin startup code. The plugin contract should make these files discoverable and attributable to the plugin through the manifest.

This means:

- the plugin tells TAP which GRIFT files it publishes
- each declared GRIFT entry is explicit rather than inferred from directory contents
- those files are expected to conform to the GRIFT specification
- plugin load makes the declaration available as part of the plugin's runtime shape

The exact execution path that consumes those declared GRIFT files may be implemented by TAP loader logic layered on top of the plugin contract. The important v0 rule is that GRIFT data is declared as part of plugin load rather than hidden in one-off management commands or hard-coded Python startup side effects.

Plugins may organize GRIFT assets under a `data/` directory by convention. As with `models/`, this directory is organizational, not itself a loading rule. Only manifest-declared GRIFT entries are loadable plugin data in v0.

If files exist under the plugin's convention directories but are not declared in the manifest, TAP should warn that those files are present but not part of the load contract. In v0 that condition is a warning rather than a startup error.

#### Development
This deliberately separates two concerns:

- declaration: what data the plugin ships
- execution: when and how TAP imports that data

That separation keeps the plugin contract inspectable while leaving room for importer tooling to mature.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-load-v0-grift-1 | GRIFT Files Are Declared | Proposed | A plugin that publishes bundled graph data declares its GRIFT files in the plugin manifest. | |
| req-tap-plugin-load-v0-grift-2 | Explicit Bundle Entries | Proposed | GRIFT publication uses explicit manifest entries rather than implicit directory-wide loading. | |
| req-tap-plugin-load-v0-grift-3 | Declaration Is Part Of Load Shape | Proposed | Plugin load exposes the declared GRIFT surface as part of the plugin's runtime contract. | |
| req-tap-plugin-load-v0-grift-4 | Data Directory Is Convention Only | Proposed | A plugin may organize GRIFT assets under `data/`, but only manifest-declared entries participate in plugin load. | |
| req-tap-plugin-load-v0-grift-5 | Undeclared Files Warn | Proposed | Files present in convention directories but absent from the manifest produce warnings rather than startup errors in v0. | |
| req-tap-plugin-load-v0-grift-6 | No Hidden Seed Requirement | Proposed | v0 plugin data publication should not rely solely on ad hoc management commands or opaque Python startup logic. | |

#### Future
Later work may define whether declared GRIFT bundles are imported automatically on first load, imported by an administrator action, or synchronized through a more explicit plugin data manager.

### GRIFT Upsert Policy
----
RID: `req-tap-plugin-load-v0-upsert`
Status: `Proposed`

When TAP imports plugin-declared GRIFT data in v0, the importer uses strict upsert semantics.

#### Status Details
Proposed to give plugin-bundled data a concrete and predictable import policy in the first lifecycle spec.

#### Implementation
Strict upsert means:

- identity matching is by GRIFT `entity_id`
- if a declared entity or edge is absent, the importer creates it
- if a declared entity or edge with the same `entity_id` already exists, the importer updates it to the declared canonical GRIFT state
- the importer does not invent fuzzy matching or semantic deduplication in v0

This requirement should compose with `tap_grid/specs/spec-grift-v0.md`, which already treats `entity_id` as canonical identity and intentionally excludes semantic dedupe.

This specification does not redefine GRIFT itself. It defines the v0 policy for plugin-bundled GRIFT imports that happen under the plugin load lifecycle.

Loader validation should distinguish declaration validation from import validation:

- at startup, the loader validates that each declared GRIFT path exists
- when import is invoked, the importer validates that the GRIFT content parses and conforms to the GRIFT contract

#### Development
Using strict upsert in v0 keeps the system deterministic and aligns with the existing GRIFT direction. It is a stronger rule than “import if missing” and avoids plugin data drifting indefinitely once introduced.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-load-v0-upsert-1 | Match By Entity Id | Proposed | Plugin GRIFT import identity matching uses `entity_id` only. | Aligns with GRIFT v0 |
| req-tap-plugin-load-v0-upsert-2 | Missing Objects Created | Proposed | Missing declared objects are created during plugin GRIFT import. | |
| req-tap-plugin-load-v0-upsert-3 | Existing Objects Replaced Canonically | Proposed | Existing objects with matching `entity_id` are updated to the canonical declared GRIFT state. | |
| req-tap-plugin-load-v0-upsert-4 | Startup Checks Path Existence | Proposed | Startup validation confirms that each declared GRIFT path exists. | |
| req-tap-plugin-load-v0-upsert-5 | Import Checks GRIFT Validity | Proposed | GRIFT content validation happens when import is invoked rather than only from file presence at startup. | |
| req-tap-plugin-load-v0-upsert-6 | No Semantic Dedupe | Proposed | v0 plugin GRIFT import does not perform fuzzy or semantic deduplication. | |
| req-tap-plugin-load-v0-dry-run-1 | Dry-Run Validation | Implemented | `import_plugin_grift --dry-run` validates each declared bundle against the GRIFT document schema (via the importer's `validate_grift_document` — single source of truth) without writing to the database, reports any issues, and counts an invalid bundle as an error. Structural only: per-record model validation runs against the DB on a real import. | Shipped ahead of spec and born broken (imported a never-defined `GRIFT_DOCUMENT_SCHEMA`); fixed + tested 2026-05-29. |

#### Future
Later specs may add import modes such as replace-only, create-only, conflict reporting, or scoped import policies per plugin or per data bundle.

### Load Order And Execution Phases
----
RID: `req-tap-plugin-load-v0-order`
Status: `Proposed`

Plugin load in v0 spans multiple phases that should be described explicitly.

#### Status Details
Proposed to prevent confusion about what happens at Python class definition time versus Django app startup time.

#### Implementation
The v0 load lifecycle has three conceptually distinct phases:

1. declaration phase
2. class-definition phase
3. startup phase

Declaration phase:

- the plugin provides `tap-plugin.toml`
- the manifest declares TAP-managed model types, edge types, editor descriptors, search runners, and bundled GRIFT files

Class-definition phase:

- plugin model classes are imported
- concrete TAP-managed model classes perform their existing `tap_grid` registrations

Startup phase:

- Django runs `TapPluginConfig.ready()`
- plugin type metadata and other startup registrations are applied
- TAP can now treat the plugin's manifest-declared surfaces as loaded and available

This specification does not require that the manifest be consumed before every class import in a technical sense. The important contract is conceptual and observable: TAP can describe the plugin's declared surfaces distinctly from the runtime registration side effects that make them active.

#### Development
The existing code already has a real split here. Writing it down now will make future scaffolding and loader work much less hand-wavy.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-load-v0-order-1 | Declaration Phase Exists | Proposed | Plugin load includes a declaration phase in which the plugin manifest describes its surfaces. | |
| req-tap-plugin-load-v0-order-2 | Class Definition Phase Exists | Proposed | Plugin TAP model classes participate in existing class-definition-time registration behavior. | |
| req-tap-plugin-load-v0-order-3 | Startup Phase Exists | Proposed | `TapPluginConfig.ready()` performs the startup phase of the load lifecycle. | |
| req-tap-plugin-load-v0-order-4 | Phases Stay Distinct | Proposed | The spec preserves the distinction between manifest declaration, class-definition registration, and startup registration. | |

#### Future
If TAP later adds a plugin loader service, that service should expose these phases clearly rather than collapsing them into opaque startup magic.

### v0 Non-Goals
----
RID: `req-tap-plugin-load-v0-nongoals`
Status: `Proposed`

This specification intentionally does not define the rest of the plugin lifecycle.

#### Status Details
Proposed so that the first lifecycle spec stays minimal and does not accrete future work by accident.

#### Implementation
Plugin load v0 explicitly does not define:

- plugin installation workflows
- plugin uninstallation workflows
- plugin dependency declaration or resolution
- plugin version compatibility rules
- plugin enable/disable state
- migration orchestration beyond normal Django app behavior
- automatic policy for when declared GRIFT bundles must be executed
- manifest schema freeze beyond the minimum high-level declaration concepts in this spec

#### Development
This is the line that keeps v0 honest. Once a couple more plugins exist, TAP will be in a better position to decide which of these should become first-class lifecycle concepts.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-load-v0-nongoals-1 | Install Deferred | Proposed | The v0 plugin load lifecycle does not define install behavior. | |
| req-tap-plugin-load-v0-nongoals-2 | Uninstall Deferred | Proposed | The v0 plugin load lifecycle does not define uninstall behavior. | |
| req-tap-plugin-load-v0-nongoals-3 | Dependencies Deferred | Proposed | The v0 plugin load lifecycle does not define plugin dependency management. | |
| req-tap-plugin-load-v0-nongoals-4 | Manifest Shape Still Evolvable | Proposed | v0 defines the manifest contract but still leaves room for future refinement beyond its minimum declared concepts. | |

#### Future
The next likely extension points are:

- a concrete manifest schema
- loader-side validation that manifest declarations match runtime registrations
- a dedicated plugin data import surface for declared GRIFT bundles
