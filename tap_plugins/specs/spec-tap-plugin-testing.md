# Plugin Testing Specification

## Philosophy

Plugins extend TAP with new node types, edge types, editors, searches, and seed data. Every plugin should be verifiable — both that its structural declarations are correct and that its custom behavior works as intended. The plugin system should make structural validation free: if you followed the conventions, a standardized test suite catches your mistakes. Custom behavior tests are the plugin author's responsibility, but the framework should make them easy to write.

This spec covers the plugin validation harness provided by `tap_plugins` and the conventions for per-plugin tests. The overall testing strategy is defined in `specs/spec-tap-testing.md`.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Free Validation | A plugin gets structural validation tests automatically by following conventions |
| 2. | Clear Boundary | Plugin system tests (in `tap_plugins`) are distinct from individual plugin tests (which ride inside each plugin package at `plugins/<slug>/tap_plugin/<slug>/tests/`) |
| 3. | Actionable Failures | Validation failures tell the plugin author exactly what is wrong and where |
| 4. | Composable | Plugin authors can mix standardized validation with their own custom tests |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-plugin-test-system | [Plugin System Tests](#plugin-system-tests) | In Development | Tests for the plugin machinery itself |
| req-tap-plugin-test-in-package | [In-Package Tests + Install-Aware Collection](#in-package-tests--install-aware-collection) | Implemented | Plugin tests live inside the package (`tap_plugin/<slug>/tests/`) so the wheel carries them; collection is install-aware (uninstalled plugins skipped, not hard-errored) |
| req-tap-plugin-test-harness | [Plugin Validation Harness](#plugin-validation-harness) | Backlog | Standardized validation that any plugin can run |
| req-tap-plugin-test-sandbox | [Sandbox-Aware Test Exclusion](#sandbox-aware-test-exclusion) | Backlog | A standardized convention for gracefully excluding plugin tests that need live external resources when running in sandboxed / offline / cloud-build environments |
| req-tap-plugin-test-custom | [Plugin-Specific Tests](#plugin-specific-tests) | In Development | Conventions for hand-written plugin tests |

### Plugin System Tests
----
RID: `req-tap-plugin-test-system`
Status: `In Development`

The plugin system's own machinery is tested in `tap_plugins/tests/`.

#### Status Details
In Development. The plugin system exists and is functional but its test coverage is evolving.

#### Implementation

Plugin system tests live in `tap_plugins/tests/` and validate the framework, not any specific plugin. They answer: "does the plugin machinery work?"

These tests cover:

- **Manifest loading:** TOML parsing, field validation, unknown key rejection
- **Plugin discovery:** `TapPluginConfig` auto-derivation of `name`, `label`, `verbose_name`
- **Model registration:** Manifest-declared models resolve to concrete TAP-managed classes
- **Edge type loading:** `.edge.json` parsing, schema validation, constraint registration
- **Editor registration:** Descriptor class resolution and entity type matching
- **Search runner registration:** Callable resolution and scoped registry integration
- **GRIFT auto-import:** Bundle path validation, upsert idempotency, database-not-ready tolerance
- **Path validation:** Required directories, undeclared file warnings, path traversal rejection

These tests use real plugins (e.g. LOTR, administrivia) as test fixtures, but the subject under test is the framework behavior, not the plugin content.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-test-system-1 | Tests In tap_plugins | In Development | Plugin system tests live in `tap_plugins/tests/`. | |
| req-tap-plugin-test-system-2 | Framework Not Plugin | In Development | System tests validate plugin machinery, not individual plugin content. | |
| req-tap-plugin-test-system-3 | Real Plugin Fixtures | In Development | System tests may use real installed plugins as test fixtures. | |

#### Future
A minimal test-only fixture plugin (not LOTR) may be introduced to decouple system tests from the example plugins.

### In-Package Tests + Install-Aware Collection
----
RID: `req-tap-plugin-test-in-package`
Status: `Implemented`

Once plugins are extracted from the monorepo into their own git repos and shipped as
wheels (`tap-plugin-<slug>`, `uv pip install git+…`), a plugin's tests must travel
**with the package**, not sit in a monorepo-only sibling directory. So plugin tests
live **inside the installable package** at `plugins/<slug>/tap_plugin/<slug>/tests/`
(a `tests` subpackage under the `tap_plugin.<slug>` namespace), and the build config
(`only-include = ["tap_plugin/<slug>"]`) carries them into the wheel. The tests are
therefore present in every environment the package is installed into — dev, CI, and a
customer/production checkout — not just a monorepo clone.

This is deliberate and always-on (no separate dev-wheel variant — that was considered
and rejected as YAGNI). Two payoffs beyond "CI can run them":

- **All-plugins CI coverage.** The server-side all-plugins lane
  ([spec-dev-validation.md](../../specs/spec-dev-validation.md)
  `req-dev-validation-all-plugins-lane`) installs the plugin set and collects each
  plugin's in-package tests alongside the core walk — the authoritative full-set
  coverage a focused local stack can no longer run.
- **AI-legible corpus (Player 3).** The shipped test corpus is food-for-thought for
  the onboard/integrated AI assistants that observe, maintain, and reason about a
  plugin ([spec-ai-integration.md](../../specs/spec-ai-integration.md)) — a maintaining
  agent that has the package has its behavioral contract, not just its code.

**Install-aware collection.** Because not every plugin is installed in every stack (a
focused session provisions only its subset), collection is **fail-safe, not
fail-closed**: an *uninstalled* plugin's on-disk tests are **skipped/ignored, not
hard-errored** at collection (`req-dev-validation-collection-complete-4`). Two seams
implement this, both keyed off the installed set (`tap.plugin_testing.installed_plugin_slugs()`,
which honors `TAP_PLUGINS` else entry-point discovery):

- Root `conftest.py` computes `collect_ignore` for the test dirs of plugins present on
  disk but not installed, so a focused session does not ImportError at collection.
- A plugin test file that must resolve its own source root skips module-level when it
  is not running off a checkout (`tap.plugin_testing.find_plugin_source_root(__file__)`
  returns `None` → `pytest.mark.skipif`).

The consequence: absence of a plugin **degrades coverage** (fewer tests run) rather
than **breaking the run** (collection error). The all-plugins lane is what restores
full coverage; the local lane owns whatever is installed.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-test-in-package-1 | Tests Inside the Package | Implemented | Plugin tests live at `plugins/<slug>/tap_plugin/<slug>/tests/` and are carried into the wheel by `only-include = ["tap_plugin/<slug>"]`. | Present in dev, CI, and installed/production checkouts. |
| req-tap-plugin-test-in-package-2 | Uninstalled ⇒ Skipped, Not Errored | Implemented | Collection ignores/skips the tests of plugins present on disk but not installed; a focused stack collects cleanly. | Root `conftest.py` `collect_ignore` + `find_plugin_source_root` module-skip. |
| req-tap-plugin-test-in-package-3 | Keyed Off Installed Set | Implemented | The installed set is `tap.plugin_testing.installed_plugin_slugs()` (honors `TAP_PLUGINS`, else entry-point discovery); both collection seams use it. | Single source of "what is installed". |
| req-tap-plugin-test-in-package-4 | All-Plugins Lane Restores Coverage | Implemented | Full-set coverage is owned by the server-side all-plugins lane, which installs the set and collects every plugin's in-package tests. | Cross-ref `req-dev-validation-all-plugins-lane`. |

#### Future

A plugin may ship its own **minimum test/CI boot profile** (a `boot/*.boot.json` record
inside the package, reusing the shippable-boot-record machinery) that declares the
cross-plugin test dependencies it needs booted alongside it (e.g. samsite needs
roscale/sigstore_core/github_core/aws_core). A plugin-repo CI job pulls and boots that
profile, exercising the declared deps rather than merely declaring them — the concrete
home for `req-tap-plugin-arch-dependencies` "declare-now" deps. See
[spec-dev-validation.md](../../specs/spec-dev-validation.md)
`req-dev-validation-all-plugins-lane` sub-req 5.

### Plugin Validation Harness
----
RID: `req-tap-plugin-test-harness`
Status: `Backlog`

`tap_plugins` provides a standardized validation harness that any plugin can run to verify its structural correctness.

#### Status Details
Backlog. Deferred until TAP has a use case for new plugin development. The compliance validator will be built when plugin authors need it, not before.

#### Implementation

The validation harness is a pytest base class (or set of fixtures) that lives in `tap_plugins`. A plugin's test suite can use it to automatically validate:

**Manifest integrity:**
- `tap-plugin.toml` parses as valid TOML
- All required top-level fields are present and non-empty
- `manifest_version` matches the expected version
- No unknown top-level keys

**Model declarations:**
- Every `[models]` entry resolves to a concrete TAP-managed model class
- Each resolved class has an `ENTITY_TYPE` matching the manifest slug key
- Each model class has a corresponding migration

**Edge declarations:**
- Every `[edges]` entry points to an existing `.edge.json` file
- Each edge definition file parses as valid JSON
- Each edge definition has required fields (`slug`, `name`, `description`)
- Each edge file `slug` matches its manifest key
- `sources` and `targets` (when present) reference entity types declared in this plugin or in registered plugins
- No unknown keys in edge definition files

**Editor declarations:**
- Every `[editors]` entry resolves to a concrete `EditorDescriptor` class
- Each descriptor's entity type matches the manifest key

**Search declarations:**
- Every `[searches]` entry resolves to a callable
- Each callable is registered (or registrable) in the scoped search runner registry

**GRIFT declarations:**
- Every `[grift]` entry points to an existing `.grift.json` file
- Each GRIFT file parses as valid JSON
- Each GRIFT file conforms to the GRIFT v0 envelope schema
- Node references within GRIFT files reference entity types declared in this plugin or in registered plugins

**Full load cycle:**
- The plugin can complete a full registration and GRIFT import cycle without errors
- After import, entities declared in GRIFT files exist on the grid

#### Usage

A plugin author adds a single test file to get all structural validation:

```python
# plugins/my_plugin/tap_plugin/my_plugin/tests/test_plugin_validation.py

from tap_plugins.testing import PluginValidationTestCase


class TestMyPluginValidation(PluginValidationTestCase):
    plugin_slug = "my_plugin"
```

The base class discovers the plugin by slug, loads its manifest, and runs all applicable structural checks. Checks are skipped gracefully when a manifest section is absent (e.g. no `[editors]` means editor checks are skipped).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-test-harness-1 | Base Class Exists | Backlog | `tap_plugins.testing` provides `PluginValidationTestCase`. | |
| req-tap-plugin-test-harness-2 | Manifest Integrity Checks | Backlog | The harness validates manifest TOML structure and field presence. | |
| req-tap-plugin-test-harness-3 | Model Resolution Checks | Backlog | The harness validates that declared model classes resolve and match slugs. | |
| req-tap-plugin-test-harness-4 | Edge File Checks | Backlog | The harness validates edge definition files parse, have required fields, and match slugs. | |
| req-tap-plugin-test-harness-5 | Editor Resolution Checks | Backlog | The harness validates editor descriptor resolution and entity type matching. | |
| req-tap-plugin-test-harness-6 | Search Callable Checks | Backlog | The harness validates search runner callable resolution. | |
| req-tap-plugin-test-harness-7 | GRIFT File Checks | Backlog | The harness validates GRIFT files parse and conform to the v0 envelope schema. | |
| req-tap-plugin-test-harness-8 | Full Load Cycle | Backlog | The harness validates the plugin can complete registration and GRIFT import. | |
| req-tap-plugin-test-harness-9 | Graceful Section Skip | Backlog | Missing manifest sections (e.g. no `[editors]`) cause checks to be skipped, not to fail. | |
| req-tap-plugin-test-harness-10 | Actionable Failure Messages | Backlog | Validation failures include the manifest key, file path, or class path that failed. | |

#### Future
The validation harness may evolve into a `manage.py validate_plugin <slug>` management command for non-test-suite usage. A `--strict` flag could treat warnings (undeclared files) as errors.

### Sandbox-Aware Test Exclusion
----
RID: `req-tap-plugin-test-sandbox`
Status: `Backlog`

Some plugin tests can only pass with access to live external resources: a real
upstream URL, cloud credentials, an STS identity call, a container-only binary,
or a network round-trip. Today TAP runs in a developer Docker stack with full
internet, so these tests run fine. As TAP work moves toward sandboxed,
offline, or cloud-build execution (the satellite/outpost direction), those
tests must be **gracefully excluded** — deselected or skipped, never failed —
so the deterministic core suite stays green with zero external access.

#### Status Details

Backlog. There is one concrete prototype today: the `live_fetch` pytest marker
(registered in `pyproject.toml`, default-deselected via
`addopts = -m 'not live_fetch'`), used by the FedRAMP KSI collector's opt-in
real-upstream test. This requirement generalizes that one-off into a single
TAP-wide convention plugin authors can rely on, rather than each plugin
inventing its own marker. Deferred until sandboxed/offline execution is
actually being built; specified now so the convention is designed once, not
retrofitted per plugin.

#### Motivating Case

The default-on collector phase-1 self-test gate
(`tap_cares/specs/spec-tap-cares-collector.md`
`req-tap-cares-collector-self-test-10`) runs a collector's `self_test()` as
phase 1 of *every* `CollectionJob`. A collector whose `self_test()` performs a
live external probe (KSI's read-only upstream HEAD; the AWS collector's STS
`GetCallerIdentity`) therefore makes every collection-run test transitively
depend on that live resource. On a developer laptop with internet that
succeeds; in a sandboxed/offline run it would not. The deterministic suite
already avoids this for the *collection* path by overriding the data-fetch seam
(KSI's `_fetch_upstream_bytes`); the missing piece is a parallel, standardized
way to (a) stub the self-test probe so phase 2 is still exercised
deterministically, and (b) mark genuinely live-only tests for graceful
exclusion.

#### Implementation

The convention has three parts:

- **One canonical marker.** A single registered pytest marker (working name
  `requires_live_external`) supersedes ad-hoc per-plugin markers. `live_fetch`
  is folded in as the first adopter (kept as an alias or migrated). Plugin
  authors apply the marker; they do not edit the root `pyproject.toml` per
  plugin.
- **One selection signal.** Sandboxed / offline / cloud-build runners
  deselect the marker through a single documented mechanism (a pytest `-m`
  expression and/or an environment variable such as `TAP_SANDBOX=1` honored by
  a shared conftest), so a build environment opts out in one place rather than
  per suite.
- **A self-test stub seam.** Collectors whose `self_test()` performs live
  external I/O expose a deterministic override point (mirroring the existing
  data-fetch seam) so collection-run tests can exercise phase 2 without the
  live probe and without marking the whole test live-only. Tests that
  *intentionally* assert real live behavior carry the marker and are excluded
  in sandboxed runs.

Graceful exclusion means deselect/skip with a clear reason, never a failure: a
fully offline run of the core suite must be green.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-test-sandbox-1 | Canonical Marker | Backlog | One TAP-wide registered pytest marker designates tests that require live external resources; plugins use it instead of inventing per-plugin markers. | Generalizes today's `live_fetch`. |
| req-tap-plugin-test-sandbox-2 | Single Selection Signal | Backlog | Sandboxed / offline / cloud-build environments deselect the marker through one documented mechanism (pytest `-m` and/or a shared-conftest env var), not per-suite wiring. | |
| req-tap-plugin-test-sandbox-3 | Graceful, Never Failing | Backlog | Excluded tests are deselected or skipped with a reason; a fully offline run of the core suite is green. | |
| req-tap-plugin-test-sandbox-4 | Self-Test Stub Seam | Backlog | A collector whose `self_test()` does live external I/O exposes a deterministic override point so collection-run tests exercise phase 2 without the live probe. | Cross-ref `req-tap-cares-collector-self-test-10`; mirrors KSI's `_fetch_upstream_bytes` seam. |
| req-tap-plugin-test-sandbox-5 | live_fetch Folded In | Backlog | The existing `live_fetch` marker and its default `addopts` deselect are absorbed into the canonical convention (alias or migration), not left as a parallel one-off. | |
| req-tap-plugin-test-sandbox-6 | Harness Surfacing | Backlog | The plugin validation harness (`req-tap-plugin-test-harness`), when built, documents/surfaces the convention so new plugins adopt it by default. | |

#### Future

The same marker taxonomy is the natural place to add other categorizations
anticipated by `specs/spec-tap-testing.md` (`slow`, `integration`). When TAP
gains true sandboxed satellites/outposts, the selection signal can be driven by
the sandbox runtime itself rather than a build-time flag.

### Plugin-Specific Tests
----
RID: `req-tap-plugin-test-custom`
Status: `In Development`

Plugins may include hand-written tests for behavior unique to that plugin.

#### Status Details
In Development. LOTR's custom tests live in-package at `plugins/lotr/tap_plugin/lotr/tests/` (relocated from the retired monorepo-only `plugins/lotr/tests/` layout; see [req-tap-plugin-test-in-package](#in-package-tests--install-aware-collection)).

#### Implementation

Plugin-specific tests live **inside the package** at `plugins/<slug>/tap_plugin/<slug>/tests/` (so the wheel carries them — see [req-tap-plugin-test-in-package](#in-package-tests--install-aware-collection)) and validate net-new functionality that the standardized harness cannot cover:

- **Custom editor logic:** Form validation rules, field transformations, save behavior
- **Custom search runners:** Runner callable returns expected results for known data
- **Domain constraints:** Plugin-specific business rules beyond what edge/model declarations encode
- **Complex edge scenarios:** Multi-hop or conditional relationships unique to the plugin's domain

**Conventions:**
- Test files follow the standard `test_*.py` naming pattern
- Tests have access to root conftest fixtures (e.g. `default_caller_context`)
- Tests may use `conftest.py` in the plugin's in-package `tests/` directory for plugin-specific fixtures
- A test that must resolve its own source root (e.g. to read fixture files off the checkout) guards with `tap.plugin_testing.find_plugin_source_root(__file__)` and skips module-level when it returns `None` — so the file is inert when its plugin is installed-but-not-from-a-checkout
- Tests should use the service layer for entity/edge setup, not direct ORM writes
- Test file names should be prefixed with the plugin slug for clarity when viewing full-suite output (e.g. `test_lotr_constraints.py` not `test_constraints.py`)

**What not to test in plugins:**
- Framework behavior (manifest loading, GRIFT import mechanics) — that belongs in `tap_plugins/tests/`
- Core grid behavior (entity creation, edge constraints) — that belongs in `tap_grid/tests/`
- The standardized validation checks — use the harness instead

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-test-custom-1 | Tests In Plugin Package | In Development | Plugin-specific tests live in-package at `plugins/<slug>/tap_plugin/<slug>/tests/`. | See `req-tap-plugin-test-in-package`. |
| req-tap-plugin-test-custom-2 | Slug-Prefixed File Names | In Development | Test file names are prefixed with the plugin slug. | |
| req-tap-plugin-test-custom-3 | Service Layer Setup | In Development | Plugin tests use the service layer for TAP-managed data setup. | |
| req-tap-plugin-test-custom-4 | No Framework Testing | In Development | Plugin tests do not duplicate framework or core grid test coverage. | |

#### Future
If plugins grow complex enough to warrant integration test suites (e.g. testing a plugin's API endpoints), conventions for those will be added here.
