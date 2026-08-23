# Plugins Architecture Specification

## Philosophy

TAP plugins are the primary mechanism for introducing domain-specific behavior without weakening TAP's core graph and service-layer contracts. A plugin should be easy to review, easy to scaffold, and easy to validate. In v0, that means the plugin's architecture should stay small, explicit, and manifest-driven.

This specification is intentionally broader than the manifest specification and intentionally lighter than a full lifecycle or packaging spec. Its job is to answer a practical authoring question: what are the core pieces a TAP plugin is expected to contain, and how should those pieces fit together?

The guiding principle is that a plugin's TAP-facing load surface should be inspectable before reading arbitrary implementation code. The manifest is therefore central, but the plugin also includes code, assets, data, specs, skills, and tests organized by clear conventions.

Plugins may be developed as standalone git repositories and integrated into TAP as git submodules under `plugins/`. Everything needed to understand, validate, test, and maintain the plugin should live inside the plugin directory, but the TAP plugin contract should not depend on when that repo/submodule boundary is established.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Simple        | A new plugin author can understand the minimum plugin shape quickly |
| 2. | Inspectable   | The plugin's TAP-facing contract is declared in one manifest-driven architecture |
| 3. | Self-Contained | Each plugin is a complete git repo with code, specs, skills, icons, tests, and CI |
| 4. | Consistent    | Plugins use the same package structure and extension points across domains |
| 5. | Testable      | Every plugin includes both structural validation and plugin-specific behavior tests |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-plugin-arch-scope | [Plugin Scope](#plugin-scope) | Implemented | Defines what a TAP plugin is architecturally |
| req-tap-plugin-arch-django | [Django App Foundation](#django-app-foundation) | Implemented | Every plugin is a Django app using `TapPluginConfig` |
| req-tap-plugin-arch-manifest | [Manifest Contract](#manifest-contract) | Implemented | Every plugin has a manifest conforming to the manifest spec |
| req-tap-plugin-arch-surfaces | [Declared TAP Surfaces](#declared-tap-surfaces) | Implemented | Models, edges, editors, searches, and GRIFT are manifest-declared |
| req-tap-plugin-arch-layout | [Package Layout](#package-layout) | Implemented | Core files, convention directories, and self-contained repo structure |
| req-tap-plugin-arch-repo | [Repository Structure](#repository-structure) | Implemented | Plugins are self-contained git repos integrated as submodules |
| req-tap-plugin-arch-install-registry | [Install Resolution And Plugin Registry](#install-resolution-and-plugin-registry) | Partially Implemented | Plugin-refactor MVP (2026-07-01): entry-point discovery, no-symlink uv-owned loading, identity separation, and `TAP_PLUGINS` generation are built (`tap/preboot.py`) and carry the **entire plugin set** — 10 package-mode plugins (2026-07-02: `gryphon_playground` migrated, build-baked set now empty) install + discover through the profile `install` section. The registry/report inspection surface (-3/-5/-11) is now built as a **read-model**: `tap_plugins.report.build_report()` + `manage.py plugins [--json]` (schema-validated, gated by `plugins.read`); plugins-as-grid-entities + cytoscape view stay deferred |
| req-tap-plugin-arch-slug-register | [Slug Load-Bearing Register](#slug-load-bearing-register) | Implemented | The slug is the load-bearing, immutable-by-guardrail canonical identity; `docs/doc-plugin-slug-load-bearing.md` registers every place it is load-bearing, and any change that adds a new slug-dependent coupling updates that register in the same change |
| req-tap-plugin-arch-identity | [Plugin Identity & Naming](#plugin-identity--naming) | Implemented | Applied across the full samsite plugin set (9 plugins, 2026-07-01): namespace `tap_plugin.<slug>` (PEP 420, -3), dist `tap-plugin-<slug>` (-2), slug identity (-1), and the pre-boot **conformance gate** (`tap/preboot.py:conformance_gate`, -5) all live + tested — the gate verifies all four agree for every discovered plugin at boot. Standalone-repo move (-4) is convention, not yet exercised |
| req-tap-plugin-arch-sources | [Multi-Path Source Resolution](#multi-path-source-resolution) | Proposed | Design locked 2026-07-01; `wheelhouse` offline path added 2026-07-02. `git` path **Implemented** 2026-07-03 (authed source, `req-tap-plugin-arch-source-secret`); `wheelhouse` install path **prototyped 2026-07-03** — `uv pip install --no-index --find-links <dir> tap-plugin-<slug>==<version>` in `preboot.uv_install_args`/`is_satisfied` + boot schema, proven end-to-end on the zero-dep leaf `fedramp_20x_ksi` (offline, credential-free cold boot). Deferred: the multi-plugin **dependency-closure** wheelhouse (Tier-0 dep wheels), `sha256` manifest, signing, and the formal strategy registry. Source-type strategy registry (`git` bootstrap → `index` durable = private-bucket+dumb-pypi → `wheelhouse` offline/airgapped = mounted pre-built-wheel directory → future `grid`); credentials resolved from `TAP_SECRETS_ROOT`, never in the profile (the `wheelhouse` path needs none). Migrated plugins use `editable` locally; the samsite demo git-installs `fedramp_20x_ksi` |
| req-tap-plugin-arch-source-secret | [Plugin-Source Credential](#plugin-source-credential) | Implemented | The authed-git-source install credential (built 2026-07-03, `tap/plugin_source_auth.py`): `kind` `github_pat`, boot-specific `data_schema`, consumer-first `scope` `tap_plugins.source`, resolved in **pre-boot** via app-neutral `tap/runtime_secrets`; fed via `GIT_ASKPASS` never token-in-URL; conditional necessity + per-source `credential` selection (`-6`) |
| req-tap-plugin-arch-source-least-priv | [Least-Privilege Source Self-Check](#least-privilege-source-self-check) | Backlog | Warn (non-dev) if the instance can *write* its plugin source (git token has push / mounted source is `W_OK`) — an over-scoped credential/mount. A per-source health probe |
| req-tap-plugin-arch-install-security | [Package Security Guard Integration](#package-security-guard-integration) | Backlog | Plugin preboot installs consume the platform package-security policy (`spec-tap-package-security-v0`): full-closure known-malicious guard before `uv pip install`, wheel-only/no-build non-dev posture, package-security projection in the plugin report |
| req-tap-plugin-arch-versioning | [Version Naming & Integrity](#version-naming--integrity) | Implemented | VCS-derived PEP 440 via `hatch-vcs` (`source = "vcs"`, `root = "../.."` monorepo-transition override, `fallback_version`) applied to all 9 migrated plugins (-1, -2). Index byte-integrity / append-only / signing (-3/-4/-5) stay deferred (no index yet) |
| req-tap-plugin-arch-min-core | [Minimum Core Version](#minimum-core-version) | Proposed | Plugin declares a supported TAP-core version range; core refuses to load an out-of-range plugin at boot — the load-time compatibility floor (the cheapest cross-repo-compat edge, universal across plugin ecosystems) |
| req-tap-plugin-arch-dependencies | [Plugin Dependencies](#plugin-dependencies) | Partially Implemented | Tier 0 (package deps → uv/pyproject, -1) built across the set. Tier 1/2 (-2/-3/-4) built 2026-07-02: manifest `depends_on` schema (slug + min-version + optional + note), the import-graph AST scanner (`tap/plugin_deps.py`), and the pre-boot `dependency_consistency_guard` (declared ⊇ observed, order, min-version — fail closed) are live; `samsite` declares its real edges. Only the topological-sort resolver stays deferred (declare-now, resolver-later — hand-ordering fine at N=10) |
| req-tap-plugin-arch-skills | [Plugin Skills](#plugin-skills) | Implemented | Plugins may ship Claude Code skills for plugin-specific automation |
| req-tap-plugin-arch-runtime | [Runtime Boundaries](#runtime-boundaries) | Implemented | TAP-facing startup behavior flows through the plugin contract |
| req-tap-plugin-arch-tests | [Testing Requirements](#testing-requirements) | Implemented | Plugins include plugin-specific tests and participate in shared validation |
| req-tap-plugin-arch-iterative-dev | [Iterative Development](#iterative-development) | Implemented | Canonical patterns for revising GRIFT content during and after initial import |
| req-tap-plugin-arch-python-deps | [Plugin Python Dependencies](#plugin-python-dependencies) | Implemented | Per-plugin `pyproject.toml` owns Tier-0 deps; plugins install profile-driven via the pre-boot `install` section (editable), not uv workspace membership (`members = []`). Deps resolve at install time — not in the root `uv.lock` during the transition (`github_core` declares `PyYAML`) |
| req-tap-plugin-arch-core-packaging | [Core Apps As Workspace Members](#core-apps-as-workspace-members) | Backlog | Core `tap_*` apps could each become a uv **workspace member** with its own `pyproject.toml` + deps — package-mode for core, mirroring plugins — scoping deps to their consumer (e.g. `requests`/`django-allauth[socialaccount]` → `tap_auth`). The reason plugins can't be workspace members (profile-gating breaks the reconciliation guard) does **not** apply: core apps are always installed. Payoff: dep locality + independently-shippable core (the extraction endgame). Cost: N pyprojects + it *formalizes* the inter-app dependency edges — so sequence it **after** app-interdependency reduction, not now |
| req-tap-plugin-arch-dev-deps | [Developer Mode Dependencies](#developer-mode-dependencies) | Partially Implemented | Per-plugin PEP 735 `[dependency-groups]` `dev` group so an evicted plugin is standalone-testable; dev deps never enter a deployed instance. **Cheap edge landed 2026-07-02:** the `new-plugin` scaffold now seeds a `dev` group so new plugins are born self-contained. **Backfill** (add a `dev` group to the ~11 existing plugins) stays demand-gated on eviction — part of the full-eviction plan. Design note: `doc-plugin-dependency-scoping-backlog` |
| req-tap-plugin-arch-slim-install | [Install-Footprint Slimming](#install-footprint-slimming) | Backlog | Ship only what a deployment uses, across three layers: Python extras (Layer A), Docker image variants for system binaries (Layer B), and the already-built plugin-granularity install section (Layer C). Demand-gated on a deployment that needs a smaller footprint. Not critical path (design note: `doc-plugin-dependency-scoping-backlog`) |
| req-tap-plugin-arch-isolation | [Plugin Type Ownership & DB Isolation](#plugin-type-ownership--db-isolation) | Proposed | Plugin-refactor pickup: owner-namespaced types + hard-included per-plugin DB guards |
| req-tap-plugin-arch-hooks | [Plugin Hook System](#plugin-hook-system) | Backlog | Future Simon Willison DJP/pluggy-style hook surface for plugin injection points throughout TAP. The FIPS crypto-BOM (`req-fips-crypto-bom`) is the reference first candidate (boot-gate + conformance-check seams); trigger is a *second* cross-cutting consumer, not FIPS alone |
| req-tap-plugin-arch-nongoals | [v0 Non-Goals](#v0-non-goals) | Proposed | Explicitly deferred concerns |

### Plugin Scope
----
RID: `req-tap-plugin-arch-scope`
Status: `Implemented`

A TAP plugin is a Django app package that contributes domain-specific TAP behavior.

#### Implementation

Architecturally, a plugin may contribute:

- TAP-managed model types
- edge types
- editor descriptors
- search runners
- bundled GRIFT data
- optional API routes and web assets layered on top of those TAP-managed surfaces

A plugin is not just an arbitrary Django app dropped into `INSTALLED_APPS`. To count as a TAP plugin, it must follow the TAP plugin contract and publish its TAP-facing shape through the manifest and plugin conventions.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-scope-1 | TAP Extension Unit | Implemented | A plugin is the standard TAP unit for domain-specific extension. | |
| req-tap-plugin-arch-scope-2 | TAP Contract Required | Implemented | A Django app is only a TAP plugin if it follows the TAP plugin contract. | |
| req-tap-plugin-arch-scope-3 | Domain-Specific Surface | Implemented | Plugins contribute domain-specific types, behaviors, data, or presentation. | |

### Django App Foundation
----
RID: `req-tap-plugin-arch-django`
Status: `Implemented`

Every TAP plugin is a Django app built on `TapPluginConfig`.

#### Implementation

In v0:

- the plugin is a Python package
- `apps.py` contains exactly one subclass of `tap_plugins.base.TapPluginConfig`
- that subclass should remain minimal and normally use `pass`
- the plugin is installed through Django's normal `INSTALLED_APPS` mechanism

This keeps plugin discovery aligned with Django rather than inventing a separate registry mechanism.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-django-1 | Django App Package | Implemented | Every plugin is a Django app package. | |
| req-tap-plugin-arch-django-2 | TapPluginConfig Base | Implemented | `apps.py` defines exactly one `TapPluginConfig` subclass. | |
| req-tap-plugin-arch-django-3 | Standard Installation | Implemented | Plugins are discovered through `INSTALLED_APPS`. | |
| req-tap-plugin-arch-django-4 | Minimal AppConfig Body | Implemented | The plugin `AppConfig` should normally be declarative and minimal. | |

### Manifest Contract
----
RID: `req-tap-plugin-arch-manifest`
Status: `Implemented`

Every plugin has a manifest that conforms to the manifest specification.

#### Implementation

The plugin root must contain `tap-plugin.toml`. That file is the canonical declaration of the plugin's TAP-facing load surface and must conform to [`spec-tap-plugin-manifest-v0.md`](/Users/george/Documents/code/tap/tap_plugins/specs/spec-tap-plugin-manifest-v0.md).

At minimum, the architecture requires:

- a manifest file at the plugin root
- manifest identity fields that name the plugin
- manifest-declared TAP surfaces rather than hidden one-off registration
- strict validation against the manifest rules

This requirement is architecture-specific because the manifest is not just one file among many. It is the plugin's reviewable contract with TAP.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-manifest-1 | Manifest Required | Implemented | Every plugin has `tap-plugin.toml` at the plugin root. | |
| req-tap-plugin-arch-manifest-2 | Manifest Spec Compliance | Implemented | The manifest conforms to the plugin manifest specification. | |
| req-tap-plugin-arch-manifest-3 | Canonical TAP Declaration | Implemented | The manifest is the canonical declaration of the plugin's TAP-facing surfaces. | |

### Declared TAP Surfaces
----
RID: `req-tap-plugin-arch-surfaces`
Status: `Implemented`

Plugins publish TAP-facing capabilities through explicit declared surfaces.

#### Implementation

In v0, the canonical declared surfaces are:

- `models`: TAP-managed model types
- `edges`: edge type definitions
- `editors`: typed editor descriptors
- `searches`: search runner callables
- `grift`: bundled GRIFT assets

These surfaces are optional individually, but if a plugin contributes one of them, it should do so through the manifest and the associated conventions/specifications.

API routers, templates, static assets, and other implementation files may also exist, but they are supporting implementation details rather than the primary TAP declaration surface.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-surfaces-1 | Canonical Surface Set | Implemented | v0 architecture recognizes models, edges, editors, searches, and GRIFT as the canonical TAP surfaces. | |
| req-tap-plugin-arch-surfaces-2 | Explicit Declaration | Implemented | Contributed TAP surfaces are declared explicitly rather than inferred from arbitrary files. | |
| req-tap-plugin-arch-surfaces-3 | Optional By Need | Implemented | A plugin may omit any canonical surface it does not use. | |

### Package Layout
----
RID: `req-tap-plugin-arch-layout`
Status: `Implemented`

Plugins are self-contained packages with a required core shape plus convention directories for optional surfaces.

#### Implementation

Every plugin must contain:

- `__init__.py`
- `apps.py`
- `tap-plugin.toml`
- `tests/`

Every plugin should contain:

- `specs/` — plugin-specific specifications documenting architecture, decisions, and future plans
- `static/<plugin_label>/icons/` — SVG icons for declared entity types (per `spec-grid-icon.md`)

Depending on what the plugin contributes, it may also contain:

- `models/` — TAP-managed model types (required when `[models]` declared)
- `edges/` — edge definition files (required when `[edges]` declared)
- `editors/` — editor descriptors
- `searches/` — search runner callables
- `grift/` — bundled GRIFT seed data (required when `[grift]` declared)
- `templates/` — Django templates
- `api/` — API router modules
- `skills/` — Claude Code skills for plugin-specific automation (see `req-tap-plugin-arch-skills`)
- `migrations/` — Django migrations for plugin models

Convention directories improve readability, but they are not themselves the load contract. Only declared manifest entries and TAP extension hooks define what TAP loads.

The plugin directory is the complete, self-contained unit. Everything needed to understand, validate, test, and maintain the plugin lives inside it — code, specs, skills, icons, seed data, and CI configuration — whether the plugin is still being developed in-tree or has already been split into its own repository.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-layout-1 | Core Required Files | Implemented | Every plugin includes `__init__.py`, `apps.py`, `tap-plugin.toml`, and `tests/`. | |
| req-tap-plugin-arch-layout-2 | Convention Directories Allowed | Implemented | Plugins may organize optional surfaces under standard directories such as `models/`, `edges/`, `editors/`, `searches/`, and `grift/`. | |
| req-tap-plugin-arch-layout-3 | Conventions Do Not Auto-Load | Implemented | Directory presence alone does not define plugin load behavior. | |
| req-tap-plugin-arch-layout-4 | Self-Contained Unit | Implemented | The plugin directory contains everything needed to understand, validate, test, and maintain the plugin. | |
| req-tap-plugin-arch-layout-5 | Specs Directory Expected | Implemented | Plugins should include a `specs/` directory with plugin-specific specifications. | |
| req-tap-plugin-arch-layout-6 | Plugin-Owned Standalone-Test Profile | Implemented | A plugin MAY ship a standalone-test boot profile, plugin-owned (travels with the plugin at extraction), NOT a top-level `boot/` profile, that stands up just that plugin on the `core` floor for standalone testing. **Location superseded** by `spec-tap-boot-bootstrap.md` `req-boot-bootstrap-records-in-package`: records move from the plugin *root* (`plugins/<slug>/<slug>.boot.json`) to *inside the package* at `plugins/<slug>/tap_plugin/<slug>/boot/<name>.boot.json`, as package data, so they ride the wheel and are fetchable by every source type (a root-level file does not ship in the wheel). A plugin may now ship **several** records (instance flavors) in its `boot/` dir. Boots via `spawn-session.sh --from <path-or-pointer>` (`--boot-file` is a deprecated alias). | Reinforces `req-tap-plugin-arch-layout-4` (self-contained). See `spec-tap-boot-bootstrap` (location + multi-record + pointer) and `spec-tap-boot-v0` `req-boot-minimal-baseline`. |

### Repository Structure
----
RID: `req-tap-plugin-arch-repo`
Status: `Implemented`

Plugins support a standalone-repository workflow and integrate into a TAP installation as git submodules.

#### Implementation

Each plugin may live in its own git repository. When it does, the plugin repo is the single source of truth for all plugin-owned assets: code, specs, skills, icons, seed data, tests, and CI configuration.

TAP installations integrate plugins by adding them as git submodules under the `plugins/` directory:

```bash
git submodule add <plugin-repo-url> plugins/<plugin_label>
```

This preserves the existing development workflow — plugins appear as local directories under `plugins/`, `INSTALLED_APPS` references them by path, Docker bind-mounts work, and `pytest` discovers their tests — while also supporting an independent plugin version history, CI pipeline, and release cadence when the standalone repo shape is used.

The plugin repo does not need to be a pip-installable package in v0. It is a Django app package that lives on the Python path via the TAP project's directory structure. If a plugin needs its own dependencies (e.g. `boto3`), it may declare them in a `pyproject.toml` and be added as a path dependency in TAP's `pyproject.toml`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-repo-1 | Standalone Repo Supported | Implemented | A plugin may live in its own git repository. | |
| req-tap-plugin-arch-repo-2 | Submodule Integration | Implemented | TAP installations may integrate plugins as git submodules under `plugins/`. | |
| req-tap-plugin-arch-repo-3 | No Pip Package Required | Implemented | Plugins are Django app packages on the Python path; pip packaging is not required in v0. | |
| req-tap-plugin-arch-repo-4 | Independent Version History | Implemented | When a plugin uses its own repository, it has commit history independent of the TAP host repo. | |

#### Future

Later work may define plugin dependency resolution, version compatibility constraints between plugins and TAP core, and automated plugin discovery beyond manual submodule addition.

### Install Resolution And Plugin Registry
----
RID: `req-tap-plugin-arch-install-registry`
Status: `Proposed`

The plugin refactor separates TAP plugin desired state, Python package
resolution, installed-plugin discovery, and TAP runtime registry/reporting into
distinct layers. This prevents uv's package-management metadata from becoming a
surrogate for TAP's plugin model while still using uv for the work it is good at:
repeatable Python dependency resolution and installation.

#### Implementation Direction

The proposed install architecture has four layers:

1. **Boot profile desired state.** The boot profile is the authored source of
   truth for an instance. Its plugin section declares which TAP plugin slugs the
   instance wants, where they may be obtained from, which credential reference is
   used for private sources, which surfaces are enabled, and whether the plugin
   is loaded in checkout/development mode or package/production mode. The
   boot-profile *shape* of this — the `install` section, its separation from the
   deployment-specific `population` section, and the cross-section drift guard —
   is owned by `specs/spec-tap-boot-v0.md` (`req-boot-install-section`); this
   spec owns the packaging/discovery/registry mechanics the section resolves to.
2. **uv package resolution.** uv owns Python package resolution and installation.
   The root `pyproject.toml` and `uv.lock` describe the Python environment.
   `uv.lock` records the exact resolved package graph for reproducible installs;
   it does not answer TAP-domain questions such as plugin slugs, enabled
   surfaces, migration status, or health.
3. **Python package discovery.** Installed TAP plugin packages advertise
   themselves through Python package metadata: a `tap.plugins` entry point group
   read via `importlib.metadata`. Pre-boot deliberately scopes that read to the
   TARGET venv's `site-packages` (`distributions(path=...)`) rather than the
   running process's `sys.path` view — the process's own environment proved
   untrustworthy under `uv run` on CI runners (2026-08-09), and the install
   target is the only authoritative statement of what is installed. Discovery
   still keys on declared metadata, never on scanning for arbitrary code.
4. **TAP plugin registry and reports.** TAP owns the runtime registry/report:
   slug, package/distribution name, resolved version or commit, `app_config`,
   manifest path, requested and loaded surfaces, install mode, provenance,
   generated settings contribution, migration/static outcomes, and load health.
   This registry/report is the auditable source of what TAP attempted, what it
   resolved, what it loaded, and why startup failed if it failed.

The four layers are intentionally not interchangeable. A package may be present
in `uv.lock` without being an enabled TAP plugin. A TAP plugin may be declared in
the boot profile but fail to resolve or load. The registry/report is where those
states become visible to humans and future AI operators.

#### MVP Direction

The installable-plugin MVP targets package/production mode first. TAP should make
uv-backed package installation work end-to-end, then add or refine
checkout/development mode once the production path is proven. Checkout mode
remains important for plugin authoring, debugging, and rapid edits, but it should
not delay the package-mode shape.

In package mode, a plugin is a real Python package with package metadata,
package data for plugin-owned assets, and a `tap.plugins` entry point. The entry
point key must equal the TAP plugin `slug`; this is the simplest validation path
and reinforces that `slug` is the ecosystem identity. The entry point target,
plugin manifest, and generated registry record must agree on slug and
`app_config` before the plugin is added to generated settings.

#### Plugin Location And Inspection

In package mode, plugin code lives where uv installs it in the active Python
environment. TAP should not coerce package installs into a custom source-tree
layout, and the runtime load path should not depend on a generated
`plugins/<slug>` symlink.

The canonical inspection surface for an assembled instance is the TAP
registry/report, not the filesystem. That report records the TAP slug,
distribution/package name, `app_config`, manifest location, installed version or
resolved commit, source provenance, requested and loaded surfaces, generated
settings contribution, migration/static outcomes, and load health.

The `plugins/<slug>/` path remains meaningful for checkout/development mode:

```text
plugins/<slug>/
```

In checkout/development mode this path may be a real working tree, path
dependency, or editable install target for a plugin under active edit. In
package/production mode, TAP may later add optional tooling conveniences such as
a generated pointer file or symlink for human navigation, but that is explicitly
not part of the MVP load contract. If such a convenience is added, it must be
specified as disposable tooling state and must protect checkout-mode working
trees from package-mode regeneration.

#### Identity Boundaries

TAP plugin identity remains distinct from Python packaging identity:

- `slug` is the globally unique TAP plugin identity.
- Python distribution/package names are uv/PyPA identities and may differ from
  `slug`.
- `app_config` is the Django import path TAP adds to generated settings.
- source URL plus resolved revision/version is provenance, not TAP identity.
- `plugins/<slug>` is a checkout/development convention or optional tooling
  convenience, not the package-mode import root.

This preserves the existing slug-centered TAP model while allowing production
package installs to use normal Python packaging conventions.

#### Generated Settings

The pre-Django install/boot wrapper writes generated plugin settings before
Django imports project settings. The target setting names are:

- `TAP_PLUGINS`: ordered plugin `app_config` entries generated from the resolved
  boot profile and registry/discovery result
- `TAP_PLUGIN_CONFIG`: plugin-scoped configuration values, initially generated
  as an empty mapping until plugin-specific configuration is specified

`TAP_PLUGINS` is the settings-time bridge into `INSTALLED_APPS`.
`TAP_PLUGIN_CONFIG` reserves the NetBox-like configuration shape without forcing
plugin-specific config into shared infrastructure.

#### Closed Review Outcomes (2026-06-30)

The following review outcomes are accepted design decisions for this requirement.
They sharpen the four-layer direction without changing its shape.

- **Install source: github-first is uv git-source, which *is* package mode —
  not git submodules.** "github-first" must mean a plugin installed as a real
  package from a git URL (`<dist> @ git+https://…@<rev>`), which uv clones to its
  cache, builds, and installs into the venv. It is emphatically **not**
  `git submodule add` (source vendored into the host tree — the prior dependency
  nightmare). Because a uv git-source install and a PyPI install are the *same*
  mechanism (same wheel, same `tap.plugins` entry point, same generated-settings
  path) differing only in the source URL, github-first is strictly **on the
  glide-path**: graduating a plugin to an index is a one-line source change with
  zero rework. The thing proven first is therefore the *packaging shape* (a
  wheel-buildable package + entry point installed from git), not publishing.
  Dev/checkout mode is a uv **path/editable** install of the plugin under active
  edit — distinct from the git-source consume path, and why checkout mode does
  not need the `plugins/<slug>` symlink gymnastics. The install source is a uv
  git-source package install, not a submodule.
- **The running-plugin registry/report is the inspection surface.** The
  authoritative "what is installed / enabled + its config + load health" is a
  queryable report (layer 4 — a `manage.py plugins`-style command / generated
  report now; plugins-as-grid-entities, Gryphon-queryable, later). The
  filesystem symlink at `plugins/<slug>` is not a load-bearing mechanism for
  package-mode installs; it is, at most, optional tooling for path-hardcoded
  workflows such as pytest discovery or bind mounts. The registry/report is a
  first-class deliverable and should converge with `/healthz` and the deferred
  boot report (`req-boot-report`) because all three are "observable
  assembled-instance truth" surfaces that should share a shape.
- **The pre-Django install wrapper's home is `docker/entrypoint.sh`.** It is the
  only process-launch slot that runs before Django imports settings, and it
  already hosts `uv sync` + `migrate`. The *logic* is a settings-free Python
  module the entrypoint calls (not bash, not `manage.py` — which would need the
  settings it is generating); it must run **before `migrate`** (so plugin
  migrations apply) and be **idempotent / fast on reboot** (the "reboot just
  works" requirement — already-installed plugins are a no-op, no re-pull). This
  is the next entry in the one-canonical-provisioning-sequence the 2026-06-26
  health/provisioning AAR established (`specs/spec-tap-health-v0.md`,
  `docs/aar/2026-06-26-tap-cache-latent-provisioning.md`). The wrapper's
  settings-free *home* and lifecycle (the named **pre-boot stage**, its
  `tap/`-resident logic, the pre-migrate **database snapshot** it takes, and the
  **boot-variable resolution** ladder it honors) are specified on the boot side
  in `specs/spec-tap-boot-v0.md` (`req-boot-preboot`, `req-boot-snapshot`,
  `req-boot-variable-resolution`). Entrypoint order:
  `uv sync → pre-boot (install → snapshot) → migrate → manage.py boot`.
- **Plugin config is deliberately deferred.** Keep the reserved
  `TAP_PLUGIN_CONFIG` seam empty; samsite continues to carry config in collector
  secrets under `TAP_SECRETS_ROOT`. A formal plugin-config mechanism is its own
  future spec (`spec-tap-plugin-config-v0`), demand-triggered by the first plugin
  whose config genuinely cannot be a secret (e.g. a Google Workspace/IdP plugin
  or per-customer instance config). Reserve the seam; do not fill it now.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-install-registry-1 | Four Layers Defined | Proposed | The architecture distinguishes boot profile desired state, uv package resolution, Python package discovery, and TAP registry/reporting. | |
| req-tap-plugin-arch-install-registry-2 | uv Boundary | Proposed | `uv.lock` is treated as the Python package resolution record, not the TAP plugin registry. | |
| req-tap-plugin-arch-install-registry-3 | TAP Registry Boundary | Implemented | TAP owns the auditable record — `tap_plugins.report.build_report()` serializes slug, distribution, version/commit, source, mode, app_config, declared-vs-loaded surfaces, load health, and bidirectional dependency edges (schema-validated). | Read-model; grid-native later |
| req-tap-plugin-arch-install-registry-4 | Entry Point Discovery | Implemented | Package-mode plugins advertise via a `tap.plugins` entry point whose key equals the slug; `tap/preboot.py:discover_entry_points` + identity check enforce key==slug. Proven with `genericom`. | |
| req-tap-plugin-arch-install-registry-5 | Registry Inspection Surface | Implemented | `manage.py plugins [--json]` is the canonical read-only inspection surface (schema `plugin-report.schema.json`), gated for web/service use by the `plugins.read` capability. | Grid-native + cytoscape view deferred |
| req-tap-plugin-arch-install-registry-6 | uv-Owned Package Location | Implemented | Package-mode plugin code loads from where uv installs it (site-packages / editable source); no `plugins/<slug>` symlink for runtime loading. Proven with `genericom`. | |
| req-tap-plugin-arch-install-registry-7 | Identity Separation | Implemented | slug, distribution name (`tap-plugin-<slug>`), Django `app_config` (TAP_PLUGINS entry), source provenance (git/editable/path), and install path are kept distinct in `tap/preboot.py`. | |
| req-tap-plugin-arch-install-registry-8 | Generated Settings Names | Implemented | The bridge uses `TAP_PLUGINS` (generated by pre-boot, consumed by settings). `TAP_PLUGIN_CONFIG` stays a reserved empty seam. | |
| req-tap-plugin-arch-install-registry-9 | Package Mode First | Proposed | The MVP proves uv-backed package-mode install before refining checkout/development mode. | |
| req-tap-plugin-arch-install-registry-10 | Optional Pointer State | Proposed | Any future `plugins/<slug>` pointer/symlink for package-mode installs is tooling-only, disposable, and specified separately before implementation. | |
| req-tap-plugin-arch-install-registry-11 | Registry Report Deliverable | Implemented | `manage.py plugins` ships as a first-class read-only report, shaped like `manage.py health` (`--json` + human), text-and-json parity. | |
| req-tap-plugin-arch-install-registry-12 | Git Source Is Package Mode | Proposed | GitHub-first plugin consumption uses uv git-source package installs, not git submodules or vendored source under `plugins/`. | |

### Slug Load-Bearing Register
----
RID: `req-tap-plugin-arch-slug-register`
Status: `Implemented`

The slug is *the one stable identity* (`req-tap-plugin-arch-identity-1`) and, by design, the most
load-bearing identifier in the plugin system: internal code layout is free to move as long as the
slug holds, which concentrates all stability requirements onto the slug. A slug change is therefore
a **first-class breaking operation** — a coordinated rename across the identity quadruple + every
profile/`depends_on`/secret-path reference, plus a data migration for the persistent-identity
couplings — not a casual edit.

Because that blast radius grows every time a new subsystem keys off the slug, it is **tracked, not
memorized.** `docs/doc-plugin-slug-load-bearing.md` is the canonical register of every place the slug
is load-bearing, split into the anchor (the identity quadruple), current mechanical couplings,
current data/persistent-identity couplings, proposed/incoming couplings (things actively loading the
slug up — e.g. secret paths and owner-namespaced entity types), and deliberate non-couplings (the
logging path, which anchors on the module path *because* it is an internal-only label).

#### Implementation

- **Update trigger (the governing discipline):** any change that adds, removes, or alters a
  slug-dependent coupling MUST update the register in the same change. Adding a subsystem that keys
  off the slug without a register row is the drift this requirement exists to prevent.
- **Immutable-by-guardrail:** the `conformance_gate` already makes accidental slug drift impossible
  (the quadruple must move in lockstep or boot fails closed), so the slug is safe to anchor external
  contracts and persistent identities on. This requirement documents *why that guarantee is
  load-bearing* rather than adding new enforcement.
- **The discriminator** (recorded in the register) governs *whether* a new identifier should anchor
  on the slug at all: external contracts and persistent identities anchor on the slug (resolved from
  declared identity, never by string-splitting `__name__`); internal-only labels anchor on the module
  path (logging).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-slug-register-1 | Register Exists | Implemented | `docs/doc-plugin-slug-load-bearing.md` enumerates every place the slug is load-bearing, tiered by mechanical / data / proposed / non-coupling. | |
| req-tap-plugin-arch-slug-register-2 | Update-In-Same-Change | Implemented | Adding/removing/altering a slug-dependent coupling updates the register in the same change. | The doc's `covers:` list names the requirements whose changes trigger a review. |
| req-tap-plugin-arch-slug-register-3 | Slug Is Immutable-By-Guardrail | Implemented | Slug changes are gated by `conformance_gate` (quadruple lockstep, fail-closed); a slug change is treated as a first-class breaking operation. | No new enforcement; documents the existing guarantee. |
| req-tap-plugin-arch-slug-register-4 | Anchor Discriminator | Implemented | New identifiers anchor on the slug (resolved from declared identity) when they are external contracts or persistent identities; on the module path only when internal-only labels. | Never string-split `__name__` to recover the slug. |

### Plugin Identity & Naming
----
RID: `req-tap-plugin-arch-identity`
Status: `In Development`

The identifiers a plugin carries are deliberately distinct concepts, and keeping
them distinct is what lets a plugin move between a standalone repo and a monorepo,
or between git-source and index install, without changing its identity. Design
locked 2026-07-01 after a prior-art survey (Python/PyPI, npm, Go modules, Rust,
Maven, Terraform providers, VS Code); the Terraform-provider shape
(`terraform-provider-<type>` repo + registry namespace) is the closest analog.

The identity chain:

1. **Slug — the one true identity.** The `tap.plugins` entry-point key, the
   `tap-plugin.toml` `slug`, and the namespace segment. Short, stable, human. TAP
   enforces slug uniqueness in its own boot/registry — because TAP owns the whole
   (private) index, it does not need PyPI's PEP 541 name-dispute machinery.
2. **Distribution name — `tap-plugin-<slug>`** (PEP 503 normalized). What uv
   installs and what the private index lists. The `tap-plugin-` prefix is the
   ownership signal; in a *private* index squatting is structurally impossible, so
   the public-PyPI objection to bare prefixes (PEP 423, deferred) does not apply.
3. **Import namespace — `tap_plugin.<slug>`** (PEP 420 native namespace package).
   Chosen over a top-level `<slug>` import so a plugin never collides with an
   unrelated package in the shared runtime, and so the import path is stable even
   if the dist name ever changes. Singular `tap_plugin` avoids collision with the
   plural `tap_plugins` management app. **Lead with the namespace from the start**
   — it is cheap to author now and expensive to retrofit across N repos later. A
   plugin dist ships `tap_plugin/<slug>/…` with **no** `tap_plugin/__init__.py`
   (so dists share the namespace); the entry point is
   `<slug> = "tap_plugin.<slug>.apps:<Slug>Config"`.
4. **Repository — decoupled and free.** The repo name is *not* load-bearing
   (convention: mirror the slug for a standalone repo, `plugins/<slug>/` in a
   monorepo). Repo-path-as-identity (Go/Actions) is explicitly rejected: it is the
   worst fit for the standalone-plus-monorepo mix TAP will have from day one.
5. **Provenance — recorded post-install** (resolved version/commit + integrity
   hash), surfaced by the deferred registry/report.

**Owners set the namespace; TAP enforces it.** The namespace/dist/entry-point live
in the plugin author's package (the plugin-creation skill emits them correctly).
TAP therefore adds a **pre-boot conformance gate** (extending the existing
entry-point identity check) that fails closed at install if dist name,
entry-point key, namespace segment, and manifest slug do not all agree — the
"verify declared matches actual" security-posture move against typosquat/confusion.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-identity-1 | Slug Is Identity | Implemented | The entry-point key == `tap-plugin.toml` slug == namespace segment is the one stable identity; uniqueness enforced in TAP boot/registry. | Enforced by `conformance_gate` |
| req-tap-plugin-arch-identity-2 | Distribution Name | Implemented | Distribution is `tap-plugin-<slug>` (PEP 503 normalized); the private index provides ownership. | `dist_name_for_slug`; gate-checked |
| req-tap-plugin-arch-identity-3 | Namespace Package | Implemented | Import path is the PEP 420 namespace `tap_plugin.<slug>` (no `tap_plugin/__init__.py`); adopted from the first migration, not retrofitted. | Distinct from the `tap_plugins` app |
| req-tap-plugin-arch-identity-4 | Repo Decoupled | Proposed | Repo name is convention-only, not load-bearing; identity survives standalone↔monorepo moves. Repo-path-as-identity rejected. | Not yet exercised (all plugins in-monorepo) |
| req-tap-plugin-arch-identity-5 | Conformance Gate | Implemented | Pre-boot fails closed if dist name, entry-point key, namespace segment, and manifest slug disagree. Owners set, TAP enforces. | `tap/preboot.py:conformance_gate` + 6 tests |

### Multi-Path Source Resolution
----
RID: `req-tap-plugin-arch-sources`
Status: `Proposed`

Where a plugin's bits come from is a separate axis from what the plugin *is*
(`req-tap-plugin-arch-identity`). TAP resolves sources through a **source-type
strategy registry** so adding a way to obtain plugins is adding one strategy, not
editing the pre-boot core. Each strategy answers three questions: how to turn the
locator into an install, how to check idempotency (`is_satisfied`), and which
`TAP_SECRETS_ROOT` credential it needs. The `install`-section `source` field is
the discriminated union that selects the strategy. Design locked 2026-07-01;
prior art is the pluggable-fetcher pattern (Nix fetchers, Terraform module source
addressing, uv/pip source types).

Source types:

- **`git` — the bootstrap/dev path (now).** `tap-plugin-<slug> @ git+<url>@<ref>`,
  with `#subdirectory=<slug>` for a monorepo. Private-repo auth uses a git
  credential helper (`url.insteadOf` / `GIT_ASKPASS`) fed a token from
  `TAP_SECRETS_ROOT` — **never a token embedded in the URL** (it would leak into
  the venv's `direct_url.json`). Reproducibility on this path resolves the ref to
  a commit SHA (there is no immutable index behind it).
- **`editable` / `path` — local/dev.** Resolve from the source tree.
- **`index` — the durable/production target.** A private **PEP 503 static index =
  a private object bucket (S3/GCS) + `dumb-pypi`**, consumed natively by uv
  (`[[tool.uv.index]]`). Install is by version (`tap-plugin-<slug>==<version>`);
  no git rev in the profile. **GitHub Releases was evaluated and rejected** as an
  index backend (2026-07-01 verification): private-repo release assets are private
  (good) but are not `--find-links`-consumable — the browser download URL
  dead-ends under token auth, only the REST asset-ID endpoint works, and there is
  no parseable simple-index page. GitHub Packages does not serve a Python index at
  all. A single index credential lives in `TAP_SECRETS_ROOT` and reaches uv via
  `~/.netrc` (or `UV_INDEX_<NAME>_*`), so nothing is embedded in config.
- **`wheelhouse` — the offline / airgapped path.** A **mounted directory of
  pre-built wheels** (a PEP 427 flat "wheelhouse"), consumed with
  `uv pip install --no-index --find-links <dir> tap-plugin-<slug>==<version>`. It is
  the **filesystem twin of `index`** — the same install-by-version-from-immutable-
  wheels model, but the wheels arrive on an attached volume instead of over HTTP, so
  it needs **no network and no credential**. That is the whole point: boot a
  container with a *get-plugins-here* volume mounted and reach nothing external — no
  git remote, no private repo, no bucket. Two properties make it honest:
  - **The wheelhouse must also contain the plugins' Tier-0 PyPI dependencies as
    wheels** (`boto3`, `PyYAML`, …). An airgapped install cannot reach PyPI for them
    either, and `--no-index` turns a missing transitive dependency into a **loud
    failure**, not a silent network fetch. So the wheelhouse is the offline index for
    *everything the instance installs*, not just the plugins — the standard
    `pip download → wheelhouse → --no-index install` airgap pattern.
  - **Wheels are built where the git tags live** (a network+git-capable CI/dev env:
    `uv build --wheel` per plugin + `uv pip download` for the dependency closure into
    one directory), then transferred as an opaque artifact. This is the clean side of
    the `hatch-vcs` split (`req-tap-plugin-arch-versioning`): version derivation needs git
    **at build time**; the resulting wheel is git-free **at install time**. A *tagless*
    build degrades to the `fallback_version = "0.0.0"` (safe, but meaningless) — so
    building in an env without the tag is the one real footgun, not a crash.

  Idempotency (`is_satisfied`): the distribution is present at the wheel's version.
  **Trust boundary:** whoever populates and mounts the volume vouches for its
  contents — the airgap moves trust to the artifact-transfer step. An optional
  in-wheelhouse `sha256` manifest, and later artifact **signing**, are the integrity
  layers; they share the `index` path's deferred-signing edge
  (`req-tap-plugin-arch-versioning-5`) and are built only when an untrusted-transfer
  threat is real.
- **`grid` — future.** Pull a plugin artifact (+ provenance) from another running
  TAP/grid instance; credential is a TAP-instance token. Drops into the same
  three-method strategy interface with no pre-boot change — the payoff of the
  registry.

**Sequencing:** `git` carries the near-term critical path (make the samsite set
installable for the first customer) without standing up index infra; the
bucket+`dumb-pypi` `index` is the durable target, built when per-repo git auth and
rebuild-from-source actually bite. `wheelhouse` is the offline **answer to monorepo
eviction** — once a plugin leaves the monorepo its `editable` source disappears, and
for a deployment that will not grant git/network/repo access the offline wheelhouse is
the only remaining install path. It is **not critical path** (2026-07-02): the eviction
that motivates it is itself deferred, so the design is locked and shovel-ready but the
build is **demand-gated** on (a) a healthy leaf plugin to pilot and (b) a deployment
that actually needs airgapped install. Its first proof — **held** — is a single-plugin
pilot (`fedramp_20x_ksi`: leaf, no cross-plugin deps, imported by no core suite): build
wheel → mount volume → throwaway profile → boot → tests green, touching nothing
load-bearing. The profile carries **no** secrets on any path; `wheelhouse` and `grid`
reach for no credential at all.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-sources-1 | Strategy Registry | Proposed | Source types resolve through a registered-strategy interface (install spec, `is_satisfied`, credential scope); adding a type adds a strategy, not pre-boot edits. | |
| req-tap-plugin-arch-sources-2 | Git Bootstrap Path | Implemented | `git` source install (`uv_install_args`) + private auth via a `GIT_ASKPASS` credential helper fed from `TAP_SECRETS_ROOT`, never a token in the URL (`req-tap-plugin-arch-source-secret`, built 2026-07-03). `#subdirectory` for monorepos stays available via the source `url`. | Strategy-registry shape (`-1`) still Proposed — this path is the if/elif in `uv_install_args`, not yet a registered strategy. |
| req-tap-plugin-arch-sources-3 | Index Durable Path | Proposed | The durable index is a private bucket + `dumb-pypi` (PEP 503 static); install by version; one credential via netrc. GitHub Releases/Packages rejected as backends. | Verified 2026-07-01 |
| req-tap-plugin-arch-sources-4 | No Secrets In Profile | Proposed | The profile carries only locators; every credential resolves from `TAP_SECRETS_ROOT`. | |
| req-tap-plugin-arch-sources-5 | Grid Source Reserved | Proposed | A future `grid` source (pull from another TAP instance) is a drop-in strategy; named, not built. | |
| req-tap-plugin-arch-sources-6 | Offline Wheelhouse Path | Proposed | A `wheelhouse` source installs plugins **and their Tier-0 dependency closure** from a mounted directory of pre-built wheels via `uv pip install --no-index --find-links <dir>`; no network, no credential. Wheels are CI-built where the git tag lives (tagless ⇒ `0.0.0` fallback); `is_satisfied` = dist present at the wheel version; the mounted volume is the trust boundary, with an optional `sha256` manifest + signing sharing the deferred edge of `-versioning-5`. | Filesystem twin of `-3`; **not critical path** — demand-gated on eviction + a healthy leaf plugin. Pilot (held): `fedramp_20x_ksi` |

### Plugin-Source Credential
----
RID: `req-tap-plugin-arch-source-secret`
Status: `Implemented`

Built 2026-07-03: `tap/plugin_source_auth.py` (settings-free) resolves the credential in pre-boot via
`tap/runtime_secrets`, validates its `data` against the install-owned schema
(`tap/schemas/github_pat_source_secret.schema.json`), and feeds it to `git` via a short-lived
owner-only `GIT_ASKPASS` script — the token never enters the URL or the logged install args.
Wired into `tap/preboot.py::install_plugins`; per-source selection (`-6`) via the git source's optional
`credential` key. Unit-covered by `tap/tests/test_plugin_source_auth.py`.

The `git` source's private-repo auth (`req-tap-plugin-arch-sources-2`) needs a credential. It is a
regular TAP secret (`spec-tap-cares-secrets`), specified here as its owning consumer
(`req-tap-cares-secrets-consumer-kinds`: a kind's `data` shape is owned by the consuming spec). The
first GitHub distribution target is `git+https` package installs (`req-tap-plugin-arch-install-registry-12`),
so this is the credential that unblocks it.

- **Kind `github_pat`** — the same credential *type* the `github_core` collector uses. Sharing the
  kind is correct (`req-tap-cares-secrets-consumer-scoping`: `kind` is the type axis); the two do
  **not** share a `data_schema` — the collector's schema requires `repos`/`initial_run_limit`, which
  are meaningless to a git credential.
- **Boot-specific `data_schema`** (owned here): `token` (required), `host` (default `github.com`, GHE
  override), `username` (default `x-access-token` — works for both PATs and App installation tokens
  over https). No `repos` — the git credential helper scopes by **host**, not a repo list.
- **Consumer-first `scope` `tap_plugins.source`** (`req-tap-cares-secrets-consumer-scoping`): owned by
  the install system, **not** a plugin. A plugin must never resolve the credential that installs its
  siblings.
- **Resolved in the pre-boot stage** via the app-neutral `tap/runtime_secrets`
  (`req-tap-cares-secrets-files` Shared Resolver) — **not** `tap_cares`, which is Django/app-level and
  would violate the settings-free, no-`tap_*`-import pre-boot contract (`req-boot-preboot`). This is the
  same shared resolver `tap_auth` calls at settings-import time.
- **Fed to git via `GIT_ASKPASS`**, never interpolated into the URL — a token in the URL leaks into the
  venv's `direct_url.json` (the standing rule in `req-tap-plugin-arch-sources-2`).
- **Conditional necessity** (`req-tap-cares-secrets-conditional-validation`): required only when the
  profile declares an authed `git` source (a private repo). Public git, `editable`, `path`, and
  `wheelhouse` sources need no credential, so it is not `required_for_boot` by default — it becomes
  required exactly when an authed git source is in the install set.
- **Description required** on the envelope (`req-tap-cares-secrets-shape-4`), scoped read-only to the
  plugin repos (see `req-tap-plugin-arch-source-least-priv`).

**Operator step** — drop the secret under `TAP_SECRETS_ROOT` (the dev bind-mount is `tap_secrets/`,
gitignored). Filename is `<key>.secret.json`; the profile's git source names the key via `credential`
(omit `credential` to use the default key `source`):

Name the key for **what the credential is**, not `source` — a self-describing key (host · repo-set ·
privilege) keeps the store honest and lets per-source selection pick between orgs later:

```json
// tap_plugins/github-plugins-ro.secret.json   (under TAP_SECRETS_ROOT; dir mirrors the scope)
{
  "scope": "tap_plugins.source",
  "key": "github-plugins-ro",
  "kind": "github_pat",
  "description": "Fine-grained read-only PAT (Contents: Read-only) for the unified-systems-com/tap-plugin-* repos.",
  "data": { "token": "github_pat_XXXXXXXX" }
}
```

```jsonc
// the matching profile install entry (host/username default to github.com / x-access-token)
{ "slug": "fedramp_20x_ksi", "enabled": true,
  "source": { "type": "git", "url": "https://github.com/unified-systems-com/tap-plugin-fedramp-20x-ksi.git",
              "rev": "v0.1.0", "credential": "github-plugins-ro" } }
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-source-secret-1 | Kind Shared, Schema Not | Implemented | Uses `kind` `github_pat` (shared type) with its own boot `data_schema` (`token`/`host`/`username`), enforced by `tap/schemas/github_pat_source_secret.schema.json` (`additionalProperties:false` rejects the collector's `repos`-bearing schema). | |
| req-tap-plugin-arch-source-secret-2 | Consumer-First Infra Scope | Implemented | Scoped `tap_plugins.source` (install system), never `tap_plugin/<slug>/…` (`SOURCE_SECRET_SCOPE`). | Least privilege across plugins. |
| req-tap-plugin-arch-source-secret-3 | Pre-Boot App-Neutral Resolution | Implemented | Resolved via `tap/runtime_secrets` in pre-boot, not `tap_cares` (would break the settings-free / no-app-import contract). | Same resolver `tap_auth` uses. |
| req-tap-plugin-arch-source-secret-4 | No Token In URL | Implemented | Fed to git via a temp owner-only `GIT_ASKPASS` script (token in child env, not the script body); never interpolated into the URL or the logged args. `GIT_TERMINAL_PROMPT=0` forbids an interactive hang. The mechanism lives once, in the stdlib-only `tap/git_invocation.py` leaf, shared with the host-side stage-0 fetcher that cannot import this module (`req-boot-bootstrap-stage0-4`). | Extends `req-tap-plugin-arch-sources-2`. |
| req-tap-plugin-arch-source-secret-5 | Conditional Necessity | Implemented | Enforced at pre-boot resolve time: a git source that **declares** a `credential` requires it (missing/absent-store ⇒ `PrebootError`); a git source with **no** `credential` is public (no auth). No implicit default key. editable/path never resolve. | The `credential` ref IS the declaration (settings-free, so not a `tap_cares` health probe). |
| req-tap-plugin-arch-source-secret-6 | Per-Source Selection | Implemented | A git source's optional `credential` key names *which* secret (under scope `tap_plugins.source`) to use, so plugins pull from different private repos/orgs in one profile; absent ⇒ public (no auth). A repo's PAT never sees another repo. | George 2026-07-02. A descriptive per-repo credential key, no vague fleet default. |

### Least-Privilege Source Self-Check
----
RID: `req-tap-plugin-arch-source-least-priv`
Status: `Backlog`

A least-privilege verifier for the plugin source: the instance should be able to **read** its source
and nothing more. If it can **write** the source, the credential or the mount is over-scoped — surface
a warning. This is the cheap, foundational defensive edge the security posture favors
(`spec-security-posture.md`, `req-sec-cheap-edges`), and it catches the most common credential
misconfiguration (an operator grabbing a broad token because it was easy).

- **Generalizes across source types** — one principle, one probe per type: a `git` source →
  `GET /repos/{owner}/{repo}` and warn if `.permissions.push` is true (reflects *effective* access
  across classic PAT / fine-grained PAT / App token, not just declared scopes); a `wheelhouse` / `path`
  source → `os.access(dir, W_OK)` (a source volume mounted read-write when it only needs read is the
  same over-scoping).
- **It is a health probe**, so it belongs in the plugin-source secret's per-consumer conditional-
  validation logic (`req-tap-cares-secrets-conditional-validation`) — the git check is a network call.
- **Non-dev, warn-only.** Gate the warning off developer mode (a broad key is often legitimate in dev),
  and keep it a warning, not fail-closed — it is a misconfiguration hint, not a boot gate.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-source-least-priv-1 | Write Access Is A Warning | Backlog | If the instance can write its plugin source, emit a warning (over-scoped credential/mount). | |
| req-tap-plugin-arch-source-least-priv-2 | Per-Source Probe | Backlog | `git` → repo `permissions.push`; `wheelhouse`/`path` → directory `W_OK`. One principle, per-type probe. | |
| req-tap-plugin-arch-source-least-priv-3 | Non-Dev, Warn-Only | Backlog | Gated off developer mode; a warning, never fail-closed. | |

### Package Security Guard Integration
----
RID: `req-tap-plugin-arch-install-security`
Status: `Backlog`

Plugin preboot installs consume the platform package-security policy defined in
[`spec-tap-package-security-v0-BACKLOG.md`](../../specs/spec-tap-package-security-v0-BACKLOG.md).
This plugin spec owns the integration point only: every enabled profile install
entry is a package-security scan target before TAP invokes `uv pip install`.
The classifier, policy modes, OSV behavior, health probes, report schema, and
scheduled rechecks are owned by the platform package-security spec, not duplicated
here.

#### Implementation Direction

The pre-Django install flow becomes:

1. resolve enabled plugin install entries from the boot profile
2. resolve source credentials where needed
3. build a package-security plan for each plugin and its dependency closure
4. apply the package-security policy
5. only then invoke `uv pip install` for entries that passed
6. include each plugin's package-security summary in the plugin report after boot

The guard applies to every plugin source type (`git`, `index`, `wheelhouse`,
`path`, `editable`) rather than treating local/dev sources as categorically safe.
For non-dev package sources, plugin installs follow the platform no-build /
wheel-only posture. Local dev sources may use relaxed policy only through the
platform package-security policy, and the effective relaxation is reported.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-install-security-1 | Preboot Calls Guard | Backlog | `tap/preboot.py` runs the package-security guard for every enabled plugin install entry before invoking `uv pip install`. | |
| req-tap-plugin-arch-install-security-2 | Full Closure Target | Backlog | The plugin package and all transitive dependencies are included in the scan target with `plugin:<slug>` attribution. | |
| req-tap-plugin-arch-install-security-3 | All Source Types Covered | Backlog | `git`, `index`, `wheelhouse`, `path`, and `editable` sources are all sent through the guard; unsupported safe planning fails under enforce mode. | |
| req-tap-plugin-arch-install-security-4 | Non-Dev Wheel-Only | Backlog | Non-dev plugin package installs use no-build / wheel-only posture as required by the platform package-security spec. | |
| req-tap-plugin-arch-install-security-5 | Plugin Report Projection | Backlog | `manage.py plugins --json` includes each plugin's package-security summary once the platform report/schema exists. | |
| req-tap-plugin-arch-install-security-6 | Platform Policy Is Canonical | Backlog | Plugin architecture does not define a parallel malware/CVE policy; it links to `spec-tap-package-security-v0`. | |

### Version Naming & Integrity
----
RID: `req-tap-plugin-arch-versioning`
Status: `In Development`

Plugin versions are **VCS-derived, self-contained, and PEP 440-native**, chosen
2026-07-01 after surveying Go pseudo-versions, Cargo, npm, uv, Terraform, and Nix
lockfiles. The goal (stated by George) is the Go property — the identifier carries
its own meaning and is always available — realized the Pythonic way rather than by
porting Go's exact string format or a hand-maintained `go.sum`.

- **Version = `hatch-vcs`-derived PEP 440.** The build tool computes the version
  from git: a tag → clean (`1.4.0`); untagged → `1.4.1.dev3+g5a6b7c8` = base
  version + commit distance + short **commit hash**, all in one string, baked into
  the wheel metadata. No hand-maintained version file. The embedded commit hash is
  the Go-style "context in the name": the same version string cannot name two
  different *sources* (a different commit ⇒ a different version). PEP 440 local
  segments (`+g…`) are index-only (rejected by public PyPI) — which our private
  index permits.
- **Integrity is layered and sidecar-free.** The version pins the *source*; the
  *wheel bytes* are pinned by the index's per-file `sha256` (PEP 503 `#sha256=`),
  which uv/pip verify on download. So identity is self-contained in the name and
  byte-integrity is automatic from the index — no hand-maintained lockfile. On the
  offline `wheelhouse` path (`req-tap-plugin-arch-sources-6`) there is no HTTP index to
  supply the hash, so the byte-integrity surface is the **volume itself** (the
  artifact-transfer step is the trust boundary); an optional `sha256` manifest shipped
  *in* the wheelhouse is the same defense moved onto the filesystem, deferred with the
  signing edge below until an untrusted-transfer threat is real.
- **Immutability is enforced, not assumed.** A self-hosted index does not enforce
  version immutability the way public PyPI does, so CI treats the index as
  **append-only** (or enables bucket object-versioning); a changed `sha256` under
  an existing version is the tamper tell.
- **Signing is the deferred edge.** Hashing defends against corruption and
  accidental re-publish; a *hostile index* that changes both the wheel and its
  published hash is defeated only by artifact **signing**, which stays a named,
  deferred integrity layer (with reproducible builds as the bonus that would make
  the commit-in-version transitively byte-pinning).
- **Git bootstrap path** keeps a resolved commit SHA as its pin, since there is no
  immutable index behind it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-versioning-1 | VCS-Derived Version | Implemented | Versions are `hatch-vcs`-computed PEP 440 (`{tag}.dev{n}+g{sha}`); no hand-maintained version field. | `source = "vcs"` + `root = "../.."` (monorepo-transition override, removed on extraction) + `fallback_version` |
| req-tap-plugin-arch-versioning-2 | Self-Contained Identity | Implemented | The version string carries base + distance + commit; the same version cannot name two different sources. | Go-style, Pythonic. Pre-tag builds fall back to `0.0.0`; a `v*` tag lights up derivation with no edit |
| req-tap-plugin-arch-versioning-3 | Index Byte-Integrity | Proposed | Wheel byte integrity is the index's per-file `sha256`, verified by uv/pip on download; no separate lockfile. On the offline `wheelhouse` path the volume/transfer step is the trust boundary; an in-wheelhouse `sha256` manifest is the filesystem analog. | Offline analog: `req-tap-plugin-arch-sources-6` |
| req-tap-plugin-arch-versioning-4 | Append-Only Index | Proposed | CI treats the index as append-only (or bucket-versioned); a version is never re-published with different bytes. | |
| req-tap-plugin-arch-versioning-5 | Signing Deferred | Proposed | Artifact signing (hostile-index defense) and reproducible builds are named, deferred edges. | |

### Plugin Dependencies
----
RID: `req-tap-plugin-arch-dependencies`
Status: `In Development`

Plugin dependency management is deliberately small: **lean on uv for the hard
80%, declare the TAP-specific 20% now, defer the resolver.** Design locked
2026-07-01 after surveying Django (apps vs migrations), NetBox, pytest/pluggy,
Debian dpkg, Jenkins, OSGi, WordPress, VS Code, Helm, and uv. The throughlines:
everyone punts library-version resolution to the package manager; the clean
designs separate "must be installed" from "must be live before me"; anything with
a *state/data* prerequisite needs a declared DAG + topological sort (Django solves
this only in migrations, and NetBox/pytest fail it); and a single shared runtime
means one version wins, resolved whole-graph, fail-closed (uv/Jenkins, not OSGi).

Three dependency kinds, three homes — **declare all three during the migration;
the resolver that consumes the ordering DAG is deferred until hand-ordering bites:**

- **Tier 0 — package/code deps → `pyproject.toml`.** `dependencies =
  ["tap-plugin-aws-core>=0.1"]`, including plugin→plugin. uv resolves the closure
  and the version diamonds and fails closed. This is the hard part, and it is
  already free. Bonus: the `install` section can then name only top-level plugins
  and let uv pull the closure. (Use version specifiers, not git-URLs, in pyproject
  so deps stay index-resolvable.)
- **Tier 1 — load/registration order → `tap-plugin.toml` `depends_on`.** Slug
  edges (optionally `slug>=min_version`, `optional`). Meaning: "my `ready()`
  type/edge registration needs theirs first." Django's migration `dependencies`
  is the in-stack model; Debian's `Depends` (ordering-only, benign cycles
  tolerated) is the vocabulary.
- **Tier 2 — seed order → mostly rides on the same `depends_on`.** The nuance:
  the genuinely *runtime-data* dependency — needing collector-produced node
  **instances** (e.g. samsite-compliance scoping the `aws_account` *rows* a
  collector produced, not another plugin's seed) — stays **explicit in the profile
  order** — Debian (Pre-Depends is rare/discouraged) and the auditability argument
  both say do not auto-resolve runtime-data ordering. Do **not** confuse this with
  needing another plugin's entity **types** registered (e.g. samsite's grift querying
  `aws_core__aws_account`): that is a schema/install dependency and belongs in Tier-0
  `pyproject.toml dependencies`, not the profile. samsite needs both — aws_core
  *installed* (Tier 0) for the types, and aws_core's *collector fired first* (Tier 2,
  profile) for the rows.

Consumers: a cheap **boot-time gate now** (validate declared min-versions; validate
that the hand-ordering is *consistent* with `depends_on` — fail loud if a profile
orders B before its declared dep A), and NetBox-style platform-version gating that
fails closed. The **topological-sort resolver is deferred** (≈ Django's
`topological_sort.py`, with explicit cycle detection and fail-closed on
unsatisfied/too-old deps) — built when manual ordering actually breaks. Do **not**
build OSGi-style multi-version coexistence or a second version resolver; one
runtime = one version, and that is uv's job.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-dependencies-1 | Package Deps Via uv | Implemented | Plugin→plugin and library deps are declared in `pyproject.toml` (version specifiers) and resolved by uv, fail-closed on diamonds. | Tier 0. Demonstrated: github_core's PyYAML resolves through its pre-boot editable install |
| req-tap-plugin-arch-dependencies-2 | Load-Order Declared | Implemented | Load/registration order is declared as `depends_on` slug edges in `tap-plugin.toml` (min-version + optional + intent `note` supported); parsed by `tap_plugins.manifest`. | Tier 1. `samsite` declares its real edges (sigstore_core/github_core/roscale) |
| req-tap-plugin-arch-dependencies-3 | Seed-Order Split | Implemented | Plugin-level code order rides on `depends_on` (code imports only); runtime-data (collector-produced node *instances*) ordering stays explicit in the profile. **Correction 2026-07-07:** the earlier claim that samsite's aws_core dep "is data, declared nowhere" conflated node *instances* (runtime data → profile) with entity *types* (schema → install). samsite's landing + compliance are built on 9 aws_core entity types (queried by string in its grift Gryphon) and it owns aws_core's collector schedule, so aws_core must be **installed** — a Tier-0 install dep, now declared in samsite's `pyproject.toml dependencies`, and correctly still NOT a `depends_on` (samsite imports no aws_core *code*). | Tier 2. See the Tier-0-vs-boot-record install-closure discussion (open) |
| req-tap-plugin-arch-dependencies-4 | Boot Consistency Gate | Implemented | Pre-boot `dependency_consistency_guard` fails closed on: an undeclared cross-plugin import (declared ⊇ AST-observed), a dep missing-from / ordered-after its dependent, or a violated min-version. Scanner + pure check in `tap/plugin_deps.py`, gate in `tap/preboot.py`. Resolver (topo-sort) still deferred. | |
| req-tap-plugin-arch-dependencies-5 | One Runtime One Version | Proposed | No second version resolver, no OSGi-style coexistence; one shared runtime resolves to one version via uv, fail-closed. | |

### Minimum Core Version
----
RID: `req-tap-plugin-arch-min-core`
Status: `Proposed`

Now that plugins live in their own repos and release independently ([spec-tap-boot-bootstrap.md](../../specs/spec-tap-boot-bootstrap.md)), a plugin and TAP core advance on separate mainlines and can drift out of compatibility. Every mature plugin ecosystem answers this first with the cheapest possible edge: the plugin **declares which core versions it supports**, and the host **refuses to load an out-of-range plugin** — `engines.vscode` (cannot be `*`), Ansible `requires_ansible`, `apache-airflow>=`, Grafana `grafanaDependency`, dbt `require-dbt-version`. TAP has no such floor today; a plugin built against a newer core silently ImportErrors (or worse, mis-behaves) against an older one.

`req-tap-plugin-arch-dependencies` covers plugin→plugin and plugin→PyPI deps; this is the missing **plugin→core** dimension. It is the load-time complement to the server-side [all-plugins CI lane](../../specs/spec-dev-validation.md#all-plugins-ci-lane) (`req-dev-validation-all-plugins-lane`): the lane proves a set works *together* at promote; this floor keeps a bad pairing from *loading* at boot on any instance, gated next to the existing identity/deps conformance gates.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-min-core-1 | Declared floor | Proposed | The plugin manifest (`tap-plugin.toml`) carries a supported TAP-core version range (e.g. `requires_tap = ">=X,<Y"`), VCS-derived to match the core versioning scheme. | Honest-support discipline: only claim what the plugin's CI actually tests (see `req-dev-validation-all-plugins-lane-4`). |
| req-tap-plugin-arch-min-core-2 | Load-time gate | Proposed | Pre-boot / boot refuses to load a plugin whose declared range excludes the running core version, with an actionable message — fail-closed, beside the identity + dependency conformance gates. | Silent runtime break → loud refuse-to-load. |
| req-tap-plugin-arch-min-core-3 | Core version legible | Proposed | The running core exposes a comparable version the gate can check against (a `tap-core` version, VCS-derived like the plugins). | Prerequisite; also what a plugin repo's CI pins/matrixes against (`req-dev-validation-all-plugins-lane-4`). |

### Plugin Skills
----
RID: `req-tap-plugin-arch-skills`
Status: `Implemented`

Plugins may ship Claude Code skills for plugin-specific automation.

#### Implementation

Skills are Claude Code instruction files that automate plugin-specific tasks such as catalog refresh, data collection, or code generation. A plugin's skills live inside the plugin directory at:

```
skills/<skill-name>/SKILL.md
```

Skills ship with the plugin and are part of the plugin's self-contained repo. The plugin author is responsible for skill content and maintenance.

Plugin skills are not automatically discovered by the TAP host's Claude Code session. Plugin authors and users invoke them by directing Claude to read and follow the skill file, or by configuring their own discovery mechanism. TAP does not maintain symlinks, copies, or other indirection between plugin skills and the host project's `skills/` directory.

Skills should reference TAP specs and schemas by path rather than embedding format knowledge, to prevent drift between the skill's instructions and TAP's authoritative format definitions.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-skills-1 | Skills Directory Convention | Implemented | Plugin skills live at `skills/<skill-name>/SKILL.md` inside the plugin directory. | |
| req-tap-plugin-arch-skills-2 | Self-Contained | Implemented | Skills ship with the plugin repo; no host-level indirection required. | |
| req-tap-plugin-arch-skills-3 | No Auto-Discovery Guarantee | Implemented | TAP does not guarantee automatic skill discovery from plugin subdirectories. | |
| req-tap-plugin-arch-skills-4 | Reference By Path | Implemented | Skills reference TAP specs and schemas by path, not embedded format knowledge. | |

#### Future

If Claude Code adds deeper nested skill discovery, plugin skills may become automatically available. Until then, invocation is the plugin author's responsibility.

### Runtime Boundaries
----
RID: `req-tap-plugin-arch-runtime`
Status: `Implemented`

Plugin startup should be contract-driven rather than ad hoc.

#### Implementation

The plugin architecture expects TAP-facing registration to flow through `TapPluginConfig` and the manifest-backed loader behavior. Plugin authors should not rely on hidden side effects in arbitrary module import paths to publish TAP-managed types or other plugin-owned surfaces.

This does not forbid ordinary Python implementation code. It does mean that the plugin's TAP contract should remain inspectable and that startup behavior should preserve the boundaries established by the plugin infrastructure.

A plugin's *configuration* is part of this boundary. A plugin must not place its configuration in `docker-compose.yml`, core settings, or other shared infrastructure — that couples the plugin to the host and breaks the self-contained-unit shape (`req-tap-plugin-arch-layout-4`). Plugins self-configure through plugin-owned mechanisms; in v0 this is on-disk secrets discovered under `TAP_SECRETS_ROOT` (e.g. the AWS Steampipe collector resolving a well-known `SecretRef`). A durable on-grid plugin-configuration model is future work; the removed `AWS_CORE_STEAMPIPE_COLLECTOR` compose entry was this anti-pattern.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-runtime-1 | Contract-Driven Startup | Implemented | TAP-facing startup behavior flows through the plugin contract rather than arbitrary side effects. | |
| req-tap-plugin-arch-runtime-2 | Implementation Still Allowed | Implemented | Plugins may include ordinary implementation code behind the declared contract. | |
| req-tap-plugin-arch-runtime-3 | Inspectable Load Shape | Implemented | A reviewer can understand the plugin's TAP-facing load shape without reading arbitrary startup logic. | |
| req-tap-plugin-arch-runtime-4 | Self-Contained Configuration | Implemented | A plugin's configuration does not live in `docker-compose.yml`, core settings, or other shared infrastructure; plugins self-configure through plugin-owned mechanisms (v0: on-disk secrets under `TAP_SECRETS_ROOT`). | Durable on-grid plugin config is future work. |

### Plugin Type Ownership & DB Isolation
----
RID: `req-tap-plugin-arch-isolation`
Status: `Proposed`

The plugin refactor adopts owner-namespaced plugin types **and** hard-includes per-plugin database-level guards built on that naming. This requirement exists so the refactor *picks both up* rather than rediscovering them.

#### Implementation

- **Type ownership (pick up in the refactor).** Every plugin-contributed type carries its owning plugin's slug inside the identifier string — plugin node types and tables prefixed `<slug>__<name>`, plugin edge types suffixed `<NAME>__<slug>`, core types unqualified. The full design — the plugin-slug traction point (slugs are already unique via Django app-label), the placement rationale, collision-as-loud-lint, reuse-by-qualified-reference, display-strip, and the verbose-explicit-names doctrine — is specified in [`spec-tap-plugin-type-ownership-v0.md`](spec-tap-plugin-type-ownership-v0.md). The refactor is the implementing vehicle; this is the load-bearing cross-reference so it is not forgotten.
- **DB isolation is hard-included, not optional.** The `<slug>__*` table-naming foundation (`req-tap-plugin-type-db-affordance`) MUST be paired in the refactor with actual per-plugin DB-level guards on plugin actions — least-privilege so a malicious or over-reaching plugin cannot directly read/write outside its own namespace and the sanctioned core read surface. This is a deliberate **security edge taken because the cost is near-zero on a surface we are already rewriting** (`spec-security-posture.md`, `req-sec-cheap-edges`): the naming foundation is free during the rename, and it makes per-plugin grants/RLS a configuration concern rather than a future migration. The *naming foundation* is the non-negotiable, build-once part; the *enforcement mechanism* (table-prefix grants/RLS now, Postgres schemas later) may land incrementally, but the refactor must not ship the type rename without laying the guard foundation it enables.
- This sits alongside the standing reality (`req-tap-plugin-arch-runtime`, `req-tap-plugin-arch-nongoals`) that v0 plugins still have broad in-process execution leeway — an honestly-accepted risk (`spec-security-posture.md`, `req-sec-honest-risk`). The DB guard is one cheap, foundational layer of defense-in-depth against that leeway, not a claim of full plugin sandboxing.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-isolation-1 | Type Ownership Adopted | Proposed | The refactor adopts owner-namespaced plugin types per `spec-tap-plugin-type-ownership-v0.md`. | |
| req-tap-plugin-arch-isolation-2 | DB Guard Foundation Laid | Proposed | The `<slug>__*` table-naming foundation is laid in the refactor (non-negotiable, build-once). | |
| req-tap-plugin-arch-isolation-3 | Per-Plugin DB Guards | Proposed | Per-plugin DB-level least-privilege guards are built on that foundation (mechanism may land incrementally; the foundation may not be skipped). | |

### Testing Requirements
----
RID: `req-tap-plugin-arch-tests`
Status: `Implemented`

Every plugin includes tests, including plugin-specific tests for plugin-owned behavior.

#### Implementation

The plugin architecture requires a `tests/` directory in the plugin package and expects authors to include plugin-specific tests consistent with [`spec-tap-plugin-testing.md`](/Users/george/Documents/code/tap/tap_plugins/specs/spec-tap-plugin-testing.md).

Architecturally this means:

- plugins participate in shared plugin validation and framework-level checks
- plugin authors add hand-written tests for plugin-specific behavior
- plugin tests live with the plugin so they evolve with the plugin's domain logic

This requirement exists even for simple plugins. A lightweight plugin may only need a small number of tests, but it should still prove its domain-specific behavior and structural correctness.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-tests-1 | Tests Directory Required | Implemented | Every plugin includes a `tests/` directory. | |
| req-tap-plugin-arch-tests-2 | Plugin-Specific Tests Required | Implemented | Plugin authors include plugin-specific tests for plugin-owned behavior. | |
| req-tap-plugin-arch-tests-3 | Testing Spec Alignment | Implemented | Plugin tests follow the plugin testing specification. | |

### Iterative Development
----
RID: `req-tap-plugin-arch-iterative-dev`
Status: `Implemented`

GRIFT content is versioned and idempotent. Once a batch has been imported, editing the file in place and re-running the importer does nothing — the importer skips batches whose `batch_entity.entity_id` it has already seen (`req-grid-import-grift-identity`). Plugins must therefore pick one of two canonical paths when revising GRIFT content, and must never rely on silent re-import of edited content.

#### Implementation

**Path 1 — Version bump (durable, always valid).**

Create a new batch to carry the change. The batch's `batch_entity.entity_id` is fresh (new UUID, commonly `uuid4()` or `uuid7()`), its name reflects the version (`"<topic> v0.5.0"` → `"<topic> v0.6.0"`), and its description names what changed in this revision. Node and edge `entity_id` values inside the batch stay stable — those are the TAP identities the importer upserts on. The new batch co-exists with the prior batch(es) in the grid's batch history; node/edge changes apply via upsert.

This is the path for:

- Every change that ships in a plugin release.
- Recurring importers that pull authoritative data on a schedule (in which case a stable `batch_entity.entity_id` per source + force re-import on each pull, per the Future note in `spec-grid-import-grift.md`, handles absences as deletions).
- Any environment where `DEBUG=False`.

**Path 2 — Force re-import (dev iteration only, DEBUG-gated).**

For rapid iteration on grift content during active development, the importer exposes `--force-batches=<id>[,<id>...]` to re-execute a batch whose id already exists locally. This is formally specified in `req-grid-import-grift-force-reimport` and its companion requirements:

- `--force-batches=<id>` — re-apply the named batch. Upserts new/changed nodes and edges; leaves unchanged content untouched.
- `--force-batches=<id> --sweep-strict` — only execute if the sweep can run cleanly (`req-grid-import-grift-batch-scoped-sweep` Strict Mode). Aborts before any writes if any candidate would be skipped by guardrails.
- `--force-batches=<id> --purge` — hard-delete swept entities and their batch-scoped history rows instead of tombstoning (`req-grid-import-grift-sweep-purge`). Use when accumulated tombstones from rapid iteration would obscure rather than document the grid.
- Combined: `--force-batches=<id> --sweep-strict --purge` — clean hard-delete or nothing.

All four forms are permitted if and only if `DEBUG=True`. There is no alternate flag, override, settings key, environment variable, or command-line argument that enables force re-import, sweep purge, or their strict variant in any other configuration. The gate prevents dev ergonomics from leaking into production deploys; it is not a security boundary and is not a substitute for deployment discipline.

#### Development

The version-bump path is the answer for nearly every real change. Force re-import exists solely to remove the friction of generating a new UUID and bumping names twenty times an hour while authoring a grift file. Once content stabilizes, the final state should land as a durable version-bumped batch so the grid's batch history reads as a coherent release progression rather than a series of force overwrites.

A common grift-authoring flow:

1. Write the initial `plugins/<name>/grift/<topic>.grift.json` with a v0.1.0 batch.
2. Import once to establish baseline.
3. Iterate: edit content, `import_plugin_grift <name> --force-batches=<id>` (or add `--purge` if orphans accumulate) until the content settles.
4. When done iterating, leave the batch's id alone if the content matches what will ship; otherwise, bump the batch's id + name for the next development wave.

Avoid these patterns:

- **Silent edits without a path**: editing grift content and re-running the importer with no flags. The edit will be ignored and the divergence will cause confusion an hour later. Always pick either path explicitly.
- **Force re-import as a normal operation**: force re-import is a development tool, not a release mechanism. If the change needs to ship, it wants a version-bumped batch with a coherent name and description.
- **Cross-plugin force re-import**: `--force-batches` names specific batch ids; there is no flag to force an entire plugin or file, by design. Don't synthesize one.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-iterative-dev-1 | Version Bump Documented | Implemented | Plugin authors must be able to find canonical guidance that a version-bumped batch is the durable path for revising grift content. | |
| req-tap-plugin-arch-iterative-dev-2 | Force Re-Import Documented | Implemented | Plugin authors must be able to find canonical guidance that `--force-batches` is the dev iteration path, DEBUG-gated, and scoped to specific batch ids. | |
| req-tap-plugin-arch-iterative-dev-3 | Sweep Semantics Named | Implemented | Plugin-scoped guidance references `req-grid-import-grift-batch-scoped-sweep` and its strict/purge variants rather than restating them. | Keeps one authoritative home for sweep rules |
| req-tap-plugin-arch-iterative-dev-4 | Anti-Pattern Called Out | Implemented | Plugin guidance explicitly warns against silent-edit-no-path and against force re-import as a release mechanism. | |


### Plugin Python Dependencies
----
RID: `req-tap-plugin-arch-python-deps`
Status: `Implemented`

Plugins may need third-party Python packages that are not required by TAP core. Examples include cloud SDKs for collectors, service-specific API clients, file parsers, or emitter transports.

The shape is plugin-local dependency ownership without fragmenting a TAP deployment into unrelated Python environments. Each plugin owns its dependency declaration in its own `pyproject.toml`, and installation is driven by the pre-boot `install` section.

Under this shape:

- the root TAP `pyproject.toml` owns TAP core dependencies and the developer `[dependency-groups]`
- **plugin installation is profile-driven via the pre-boot `install` section** (`req-boot-install-section`), **not** uv workspace membership: the root workspace is deliberately empty (`[tool.uv.workspace] members = []`), and `tap/preboot.py` editable-installs (during the monorepo transition) only the plugins a boot profile declares+enables — matching the reconciliation guard's "undeclared code must not load". Blanket workspace membership (which would install every plugin regardless of profile) was superseded by this in the package-mode migration (2026-07-02, `74b71fdc`)
- each plugin that needs Python dependencies includes its own `pyproject.toml`
- plugin-local `pyproject.toml` files declare ordinary Python package dependencies for that plugin
- the root `uv.lock` records the **root/core** environment (incl. the dev group); a plugin's Tier-0 deps resolve at its (editable) install time from its own `pyproject.toml` and are **not** pinned in the root lock during the transition — pinned reproducibility for plugin deps arrives with pinned sources (wheel version / git rev / index version; the `wheelhouse` carries the fully-pinned closure, `req-tap-plugin-arch-sources-6`)
- plugin `tap-plugin.toml` continues to declare TAP-facing surfaces such as models, edges, searches, and GRIFT; it does not become a Python package manager manifest

This keeps plugin directories self-contained enough to be split back into standalone repositories later. A plugin-local `pyproject.toml` can move with the plugin repo, while the TAP installation can consume it as a uv workspace member, path dependency, or git dependency depending on the deployment shape.

This requirement provides dependency declaration and lockfile ownership, not runtime import isolation. Python does not prevent one installed package from importing another package present in the same environment. TAP may add validation or linting later to detect undeclared imports, but uv workspace membership alone is not a security boundary.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-python-deps-1 | Profile-Driven Install | Implemented | Plugin installation is driven by the pre-boot `install` section (editable during the monorepo transition), not uv workspace membership; the root workspace is deliberately empty (`members = []`). Only profile-declared+enabled plugins install. | Superseded blanket workspace membership in the package-mode migration (`74b71fdc`), so installation matches the install-section + reconciliation-guard model. |
| req-tap-plugin-arch-python-deps-2 | Plugin Local pyproject | Implemented | A plugin that needs third-party Python packages declares them in `plugins/<slug>/pyproject.toml`. | Plugin-local dependency metadata moves with a future standalone plugin repo. First proof: `plugins/github_core/pyproject.toml` declaring `PyYAML`. |
| req-tap-plugin-arch-python-deps-3 | Dependency Resolution | Implemented | A plugin's Tier-0 deps resolve at its (editable) install time from its own `pyproject.toml`; the root `uv.lock` covers the core/dev environment. `docker/entrypoint.sh` runs `uv sync --all-packages` (root + dev group), then pre-boot editable-installs each declared plugin. | Plugin deps are not pinned in the root lock during the transition; pinned reproducibility arrives with `wheelhouse`/git/index sources (`req-tap-plugin-arch-sources`). |
| req-tap-plugin-arch-python-deps-4 | Manifest Separation | Implemented | `tap-plugin.toml` does not declare uv-installable Python package dependencies; Python dependencies stay in `pyproject.toml`. | The TAP manifest remains the TAP-facing load contract. |
| req-tap-plugin-arch-python-deps-5 | No Isolation Claim | Implemented | The spec explicitly states that uv workspaces do not enforce runtime import isolation between plugins. | Future linting may detect undeclared imports. |
| req-tap-plugin-arch-python-deps-6 | Standalone Repo Compatible | Implemented | The dependency shape works whether a plugin is in-tree, a git submodule, a path dependency, or a standalone repository. | |


### Core Apps As Workspace Members
----
RID: `req-tap-plugin-arch-core-packaging`
Status: `Backlog`
Revisit When: `after app-interdependency reduction has cleaned the tap_* dependency graph; when independently-shippable core apps become a concrete need (repo extraction)`

Today the core `tap_*` apps (`tap_auth`, `tap_grid`, `tap_web`, `tap_api`, `tap_cares`, `tap_boot`, `tap_health`, `tap_viz`, `tap_ai`) are Django app directories inside the **single** root `tap` project — they share the one root `pyproject.toml`, so their third-party dependencies (e.g. `requests` and `django-allauth[socialaccount]`, imported directly by `tap_auth`) must be declared at the top level, not scoped to the app that uses them.

**uv workspaces could change that.** A workspace is N packages, each with its own `pyproject.toml` + dependency list, sharing one lockfile and venv. Making each core app a workspace member (`tap_auth/pyproject.toml` declaring `requests`, etc.) would put dependencies **closest to their consumer** — package-mode for core, mirroring what the plugins already are.

The load-bearing insight: **the reason plugins cannot be workspace members does not apply to core apps.** Plugins are excluded from the workspace (`members = []`, `req-tap-plugin-arch-python-deps-1`) because membership installs *every* member unconditionally, which breaks the profile-gated `reconciliation_guard` ("undeclared code must not load at standup"). Core apps have no such gate — they are *always* installed, always in `INSTALLED_APPS`. The entrypoint already runs `uv sync --all-packages`, which would install exactly the core members; core apps expose no `tap.plugins` entry point, so they stay invisible to the plugin reconciliation. It is mechanically compatible.

**Payoff:** dependency locality; each app's third-party surface is visible and owned; the concrete substrate for independently-shippable / extractable core apps (the same endgame as plugin repo extraction).

**Cost / why not now:** it is a real refactor (a `pyproject.toml` + build backend per app, dist naming) and — more importantly — it forces the **inter-app dependencies to be declared** (`tap-auth` → `tap-grid` → …). That is double-edged: it surfaces the coupling honestly, but it also *cements* today's app-to-app edges into metadata. So this is explicitly sequenced **after** the app-interdependency reduction (push shared mechanics down into `tap/` or `tap_grid`), not as a way to solve a single undeclared dependency (for which the root `pyproject.toml` + a clear comment is correctly sized).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-core-packaging-1 | Per-App pyproject | Backlog | Each core `tap_*` app that carries third-party deps declares them in its own `pyproject.toml`, scoped to that app. | Mirrors the plugin per-slug `pyproject.toml` shape. |
| req-tap-plugin-arch-core-packaging-2 | Workspace Membership Allowed For Core | Backlog | Core apps are declared as uv workspace members (`[tool.uv.workspace] members`), which is safe because they are always installed — unlike plugins (`req-tap-plugin-arch-python-deps-1`). | The profile-gating objection is plugin-specific. |
| req-tap-plugin-arch-core-packaging-3 | Declared Inter-App Deps | Backlog | Cross-app dependencies (`tap-auth` → `tap-grid`, …) are declared explicitly; the graph is cleaned via interdependency reduction *before* being cemented. | Sequencing gate: do the reduction first. |


### Developer Mode Dependencies
----
RID: `req-tap-plugin-arch-dev-deps`
Status: `In Development`

A plugin's **develop/test** dependency closure (test framework, factories, linters) is a
separate axis from its runtime closure (`req-tap-plugin-arch-python-deps`, Tier 0). This
requirement records per-plugin **developer mode** as a deliberate backlog target. Full
rationale, mechanism, and the boot-boundary rule: `doc-plugin-dependency-scoping-backlog`
(Part A). Not critical path (2026-07-02: everything runs in developer mode for the
foreseeable future).

#### Status Details

Backlog, but formalizing a **current-reality** gap, not a purely-future feature. Today every
plugin `pyproject.toml` carries `dependencies = []` and **no dev dependencies**; plugin tests
run only because they execute inside the **shared root venv**, which carries the root's
`[dependency-groups]` `dev` group. So a plugin **free-rides** on the root dev group and has no
independent developer-mode story — fine in the monorepo, broken the moment a plugin is
`uv sync`'d standalone in its own repo (runtime deps only, no `pytest`/factories → its suite
cannot run). Developer mode is the dev-dependency sibling of the airgapped `wheelhouse`
source (`req-tap-plugin-arch-sources-6`): both are things a self-contained plugin needs that the
monorepo hides.

#### Implementation Direction

- **PEP 735 dependency groups** — a `dev` group in the plugin's own `pyproject.toml`
  (`[dependency-groups]`, the same standard the root uses), pulled with `uv sync --group dev`
  / `uv run --group dev pytest`. Dev-group deps **never ship in the wheel** (development
  metadata, not package metadata). Not `[project.optional-dependencies]` — extras are for
  opt-in *runtime* features (`req-tap-plugin-arch-slim-install`, Layer A), a different purpose.
- **Boot boundary (must hold):** developer mode is a local-checkout workflow, **never** a
  boot/install-section concept. Dev deps must not enter a deployed instance through the boot
  `install` path — the same discipline as "the profile carries no secrets." No `dev: true` in
  a profile, ever.
- **Cheap edge (safe pre-demand) — DONE 2026-07-02:** the `new-plugin` scaffold
  (`tap_plugins/skills/new-plugin/SKILL.md`) seeds every new plugin's `pyproject.toml` with a
  `[dependency-groups]` `dev` group (`pytest`, `pytest-django`, `factory-boy`), so the
  free-riding habit does not calcify. The **backfill** to the ~11 existing plugins remains
  demand-gated and is folded into the full-eviction plan.
- **Two-tier testing (with eviction):** running each plugin's suite against *its own* dev
  group instead of the shared root venv is the "two-tier plugin testing" build; it consumes
  into `spec-tap-plugin-testing.md`.

#### Demand Triggers

The first plugin eviction to a standalone repo, or any need to run a plugin's suite outside
the shared root venv.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-dev-deps-1 | Per-Plugin Dev Group | Backlog | A plugin declares its develop/test tooling in its own PEP 735 `[dependency-groups]` `dev` group; not in `[project.dependencies]`, not in extras. | |
| req-tap-plugin-arch-dev-deps-2 | Never In The Wheel | Backlog | Dev-group deps stay out of wheel metadata and out of any deployed instance; there is no boot/install-section path that installs them. | Same discipline as no-secrets-in-profile |
| req-tap-plugin-arch-dev-deps-3 | Standalone Testable | Backlog | With its `dev` group installed, a plugin's suite runs in its own checkout without the shared root venv. | The two-tier-testing target; pairs with eviction |
| req-tap-plugin-arch-dev-deps-4 | Scaffold Seeds It | Backlog | The `new-plugin` scaffold gives a new plugin a baseline `dev` group so free-riding does not calcify. | Cheap edge, safe pre-demand |

### Install-Footprint Slimming
----
RID: `req-tap-plugin-arch-slim-install`
Status: `Backlog`

An instance should not ship packages (or system binaries) it does not use. This records
install-footprint slimming as a deliberate backlog target. Full model:
`doc-plugin-dependency-scoping-backlog` (Part B). Not critical path — the plugin system
already delivers the coarse version (Layer C below), and the expensive layers wait for a
deployment that genuinely needs a smaller footprint.

#### Status Details

Backlog. The slim-down spans **three layers, three tools** — the common error is assuming
Python extras reach all three:

- **Layer A — Python packages → extras.** `[project.optional-dependencies]` gate PyPI deps
  (`pip install tap[saml]`). Real win for providers with heavy deps (`django-allauth[saml]`
  → `python3-saml` + `xmlsec` system libs). Caveat: Google/generic-OIDC ship *inside* core
  allauth, so slimming those is **config-level, not package-level** — extras help features
  that pull their *own* PyPI deps.
- **Layer B — system binaries → Docker image variants / build args.** `git`,
  `postgresql-client`, `curl` come from `apt-get`; **extras cannot touch the OS layer.**
  Dropping git is an image-build switch. It correlates with the source strategy: a
  `wheelhouse`-only airgapped deployment (`req-tap-plugin-arch-sources-6`) needs no git binary,
  no network, no credential — the slimmest image drops out of that choice.
- **Layer C — TAP plugins → already delivered (coarse).** The boot `install` section +
  per-plugin Tier-0 deps already means an instance does not ship `boto3` unless it installs
  `aws_core`, etc. Extras (Layer A) would add sub-plugin granularity.

Cross-cutting discipline (cheap edge to keep now): **fail loud at boot if config activates a
feature whose dependency or binary is absent** — the NetBox failure-mode TAP's static
coherence guards already prevent for plugin slugs (`req-boot-install-section-3`).

#### Demand Triggers

A deployment (early adopter / customer) whose footprint, attack surface, or airgap
constraints make the full image genuinely too large — not before.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-slim-install-1 | Extras For Optional Python Deps | Backlog | Optional *runtime* Python features are gated with `[project.optional-dependencies]` (in-wheel, consumer opt-in), distinct from dev groups. | Layer A; e.g. `[saml]` |
| req-tap-plugin-arch-slim-install-2 | Image Variants For Binaries | Backlog | System binaries (git, etc.) are slimmed via Docker build args / image variants, not Python packaging. | Layer B; correlates with `wheelhouse` |
| req-tap-plugin-arch-slim-install-3 | Plugin Granularity Already Built | Backlog | The install section + per-plugin Tier-0 deps already scope dependencies at plugin granularity; extras add sub-plugin granularity. | Layer C, existing |
| req-tap-plugin-arch-slim-install-4 | Coherence Fail-Loud | Backlog | Config that activates a feature whose dep/binary is absent fails loud at boot, not at first request. | Extends `req-boot-install-section-3` |


### Plugin Hook System
----
RID: `req-tap-plugin-arch-hooks`
Status: `Backlog`

TAP should eventually support a general plugin hook system: explicit extension
points throughout the application where plugins can inject behavior, presentation,
validation, commands, routing, or other narrowly-scoped contributions without
requiring TAP core to know each plugin's implementation details.

This is **not** part of the installable-plugin MVP. It is a named backlog target
so the current packaging/refactor work does not accidentally foreclose it, and so
future demand signals can graduate it into a dedicated spec rather than another
round of ad hoc registries.

#### Candidate first adopter — the FIPS crypto-BOM (discussed 2026-07-21)

The FIPS crypto Bill-of-Materials ([spec-fips.md](../../specs/spec-fips.md),
`req-fips-crypto-bom`) is the concrete first candidate for this hook surface, and a
useful forcing function for what the seams should be. It is a self-contained scanner
(~700 lines, near-pure-stdlib) that today **hardcodes into three core lifecycle points**:
a fail-closed **boot gate** (run from `docker/entrypoint.sh` after pre-boot), a
**per-plugin conformance check** (`validate_plugin`), and a **CI gate** (a pytest over
the installed union). Those three are exactly the kind of extension points a hook layer
would formalize — a `boot_gate` hook and a `conformance_check` hook — most naturally as
entry-point registries in TAP's existing grain (the `tap.plugins` / `tap.secret_sources`
entry-point pattern) rather than a full `pluggy` dependency.

Two honest boundaries from that discussion, so this candidate is not oversold:

- **The hook system would make the crypto-BOM *scanner* pluggable, not the whole FIPS
  story.** FIPS is three layers: the build recipe (Dockerfile FIPS stages, `ARG TAP_FIPS`,
  the entrypoint boot order) is *irreducibly core* — a plugin cannot change the base image
  or the OpenSSL provider — while only the scanner + policy layer is plugin-shaped. So even
  under hooks, FIPS stays a hybrid (recipe in core, scanner as a plugin); it is not a
  fully self-contained plugin, and extracting the scanner alone today would be a split-brain
  against an irreducibly-core recipe.
- **FIPS alone is not the trigger to build the hook layer.** It already works in core and is
  already flag-optional (`TAP_FIPS=0`). The honest trigger is a *second* cross-cutting concern
  wanting the same seam (a compliance scanner, a policy engine, an audit hook); FIPS is the
  reference/proof-of-shape, not the justification. The cheap edge that keeps the door open at
  near-zero cost — if desired before the hook layer is built — is to make the boot-gate and
  conformance-check seams entry-point registries now, turning the eventual extraction into a
  lift rather than a rewrite.

#### Prior Art

The target shape is informed by:

- **Simon Willison's DJP plugin system for Django.** DJP is the direct prior art:
  a Django plugin mechanism built on `pluggy`. A Django project configures DJP
  once in `settings.py` (`djp.settings(globals())`) and `urls.py`
  (`djp.urlpatterns()`), after which installed DJP-enabled packages can
  contribute Django settings changes, `INSTALLED_APPS`, middleware, URL
  patterns, and other hook-backed behavior without each plugin requiring custom
  project edits. DJP plugins implement hooks with `@djp.hookimpl` and are
  discovered through Python package entry points.
- **Datasette / LLM plugin lineage.** DJP inherits lessons from Simon Willison's
  broader plugin work: broad documented hook catalogs, tiny hook implementation
  modules, separate plugin packages, and plugin templates / testing patterns that
  make publishing many small plugins practical.
- **NetBox plugin architecture.** NetBox is the closest domain/platform neighbor:
  a Django-based platform for network/infrastructure systems management whose
  plugins are packaged Django apps. NetBox plugins can add models, URLs/views,
  template content injections, navigation items, middleware, plugin-scoped
  configuration, and NetBox-version compatibility limits. Its install path is
  deliberately operational rather than hot-load magic: install the Python package,
  add the plugin to configuration, provide plugin config, run migrations, collect
  static assets, then restart WSGI/workers. Its restrictions are equally useful:
  plugins may not modify core models, register URLs outside `/plugins`, override
  core templates, modify core settings, or disable core components. TAP/Rampart
  is broader and graph-native, but NetBox is a high-value prior-art target for
  both what to adapt and what boundaries to keep.
- **pluggy / pytest-style hooks.** pluggy formalizes the split between hook
  specifications (`hookspec`) and hook implementations (`hookimpl`), validates
  implementations against specifications, supports opt-in arguments so specs can
  evolve without breaking existing implementations, and offers call-order/result
  controls such as first-result hooks.
- **Ushahidi-style application hooks.** The historical value is the product
  capability: hooks placed throughout the app let plugins participate in real
  workflows and UI seams, not only declare data types at startup.

This prior art is inspiration only. TAP should not copy upstream code into the
repository. If `pluggy` itself becomes the chosen implementation dependency, that
requires the normal explicit dependency approval at implementation time.

#### Implementation Direction

A future hook system should have these properties:

- Core TAP apps define named hook specifications at intentional extension points.
- Hook specifications are documented and versioned as part of the owning app's
  spec, not invented by individual plugins.
- Plugins declare hook implementations through an inspectable manifest surface or
  a clearly-named convention module; arbitrary import side effects are not enough.
- Hook invocation is explicit at the callsite: a reader should be able to see
  where plugin behavior may enter a workflow.
- Hook behavior must respect existing TAP boundaries: graph writes still go
  through the service layer, boot remains explicit, and security-sensitive hooks
  require a source-material security pass before implementation.
- Hook failures have defined behavior per hook: fail-loud, collect warnings,
  first-result fallback, or ignore-`None`; no silent catch-all swallowing.
- Hook ordering and result-composition semantics are declared by the hook spec,
  not by plugin load accidents.
- Hook registration and invocation are observable enough for debugging and future
  Paladin-style health checks.

#### Demand Triggers

This backlog item should graduate when TAP has at least one concrete extension
point that is awkward to model with the existing manifest surfaces and registries.
Likely triggers include:

- multiple plugins wanting to contribute to the same page, panel, menu, or action
  surface
- plugin-specific validation or transformation around a shared workflow
- plugin-owned collector lifecycle participation beyond today's explicit boot
  steps
- customer/plugin code needing to add commands, routes, permission checks, or UI
  affordances without modifying TAP core

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-arch-hooks-1 | Backlog Target Named | Backlog | The plugin architecture records a future general hook system as a deliberate target, not an oversight. | |
| req-tap-plugin-arch-hooks-2 | MVP Boundary Preserved | Backlog | The hook system is explicitly outside the installable-plugin MVP. | |
| req-tap-plugin-arch-hooks-3 | Prior Art Captured | Backlog | The future design references DJP/pluggy-style Django hooks, NetBox's Django infrastructure plugin model, and Ushahidi-style app injection points as prior art. | |
| req-tap-plugin-arch-hooks-4 | Explicit Hook Specs | Backlog | Future hooks are owned by core apps as named, documented hook specifications with declared ordering/result/failure semantics. | |
| req-tap-plugin-arch-hooks-5 | No Ad Hoc Side Effects | Backlog | Plugin hook implementations are declared through an inspectable surface or clear convention rather than hidden import side effects. | |
| req-tap-plugin-arch-hooks-6 | Service And Security Boundaries | Backlog | Hook implementations do not bypass TAP service-layer, boot, auth, or security-sensitive boundaries. | |


### v0 Non-Goals
----
RID: `req-tap-plugin-arch-nongoals`
Status: `Proposed`

The current implemented v0 plugin architecture does not yet define or ship:

- plugin dependency resolution or version compatibility constraints
- concrete package-mode install, update, or uninstall workflows
- plugin enablement state or marketplace concepts
- non-Python runtime packaging such as containers
- security review or permission declarations for plugin code
- automatic skill discovery from plugin subdirectories
- general hook/injection points beyond the current manifest-declared surfaces

Those concerns may become future plugin architecture layers, but they are intentionally outside this authoring spec.

#### Future

- Define how TAP handles plugin-declared model types whose Python classes import correctly but whose backing database tables or migration state are not present.
- Define version compatibility constraints between plugins and TAP core.
- Define plugin dependency resolution when plugins depend on other plugins.
- Implement package-mode uv installation, package entry point discovery, generated plugin settings, and the TAP registry/report shape (`req-tap-plugin-arch-install-registry`).
- Define a general hook/injection system once real extension-point demand exists (`req-tap-plugin-arch-hooks`).
