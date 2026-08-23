# TAP Testing Specification

## Philosophy

Tests are how we know TAP works. The testing strategy should be simple enough that running the full suite is a single command, organized enough that a developer can run a subset for fast feedback, and structured enough that each application's tests are self-contained and focused on the behavior that application owns.

TAP is a Django project with multiple applications and a plugin system. Each application owns its domain behavior and should own its tests. The testing framework should make it easy to write good tests and hard to write tests that depend on hidden state or cross-application coupling.

In v0 all tests are developer-facing. User-facing verification and self-test capabilities are a future concern.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Single Command | `pytest` at the repo root runs every test in the project |
| 2. | Scoped Runs   | A developer can run tests for a single application or plugin in isolation |
| 3. | Clear Ownership | Every test lives in the application or plugin that owns the behavior it validates |
| 4. | Service-Layer First | Application-level tests prefer the service layer for setup and assertions over direct ORM manipulation |
| 5. | Spec Linkage  | Tests link to spec acceptance criteria via `@pytest.mark.spec` markers |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-test-discovery | [Test Discovery](#test-discovery) | Implemented | pytest configuration and test path layout |
| req-tap-test-layout | [Test Layout By Application](#test-layout-by-application) | In Development | Where tests live and what they cover |
| req-tap-test-fixtures | [Shared Fixtures](#shared-fixtures) | In Development | Root conftest and application-level conftest patterns |
| req-tap-test-conventions | [Test Conventions](#test-conventions) | In Development | Naming, style, and structural conventions |
| req-tap-test-accompaniment | [Tests Accompany Change](#tests-accompany-change) | Implemented | Standing policy: behavior changes ship with tests; warnings fixed, never accumulated (OpenSSF `test_policy`/`warnings`) |
| req-tap-test-spec-linkage | [Spec Linkage](#spec-linkage) | In Development | Connecting tests to acceptance criteria |
| req-tap-test-plugins | [Plugin Test Integration](#plugin-test-integration) | In Development | How plugin tests fit into the overall suite |
| req-tap-test-hermetic-plugins | [Plugin Tests Are Hermetic](#plugin-tests-are-hermetic) | Proposed | Plugins must be self-contained for testing; cross-plugin dependencies require explicit approval |
| req-tap-test-live-integration-backlog | [Live-Integration Test Harness (Backlog)](#live-integration-test-harness-backlog) | Backlog | A designed system for exercising live external integrations (GitHub, AWS, Rekor, etc.) on a cadence we control |

### Test Discovery
----
RID: `req-tap-test-discovery`
Status: `Implemented`

pytest discovers and runs all project tests from a single invocation.

#### Status Details
Implemented in `pyproject.toml` under `[tool.pytest.ini_options]`.

#### Implementation

**Configuration** (`pyproject.toml`):

```toml
[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "tap.settings"
testpaths = ["tap_grid", "tap_plugins", "tap_api", "tap_web", "tap_viz", "plugins"]
python_files = ["test_*.py", "*_test.py"]
addopts = "-v --tb=short"
```

**Running tests:**

| Scope | Command |
| --- | --- |
| Full suite | `scripts/dc exec web uv run pytest` |
| Single app | `scripts/dc exec web uv run pytest tap_grid/` |
| Single plugin | `scripts/dc exec web uv run pytest plugins/lotr/` |
| Single file | `scripts/dc exec web uv run pytest tap_grid/tests/test_services.py` |
| Single test | `scripts/dc exec web uv run pytest tap_grid/tests/test_services.py::test_name` |
| By marker | `scripts/dc exec web uv run pytest -m "spec"` |

Use **`scripts/dc`**, not bare `docker compose`. Bare `docker compose` from a worktree only auto-loads `.env`, so it silently lands on the primary checkout's `tap` project on port 8000 even when the worktree's `.env.local` overrides `COMPOSE_PROJECT_NAME` and ports. Test runs would target the wrong project's Postgres — passing or failing against state the worktree's developer can't see in the browser. `scripts/dc` cascades `.env.local` on top of `.env` via `--env-file .env --env-file .env.local`, hitting the worktree's actual project. See `spec-dev-multisession.md` `req-dev-multisession-env-cascade-1`.

The `testpaths` list is ordered to match the application scaffolding priority. New applications should be added here when they gain tests.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-test-discovery-1 | Single Command Full Suite | Implemented | `pytest` at repo root discovers and runs all application and plugin tests. | |
| req-tap-test-discovery-2 | Per-App Isolation | Implemented | `pytest <app>/` runs only that application's tests. | |
| req-tap-test-discovery-3 | Per-Plugin Isolation | Implemented | `pytest plugins/<name>/` runs only that plugin's tests. | |
| req-tap-test-discovery-4 | Standard File Patterns | Implemented | Test files match `test_*.py` or `*_test.py`. | |

#### Future
As the project grows, pytest markers or labels may be added for categorizing tests (e.g. `slow`, `integration`) beyond spec linkage.

### Test Layout By Application
----
RID: `req-tap-test-layout`
Status: `In Development`

Each Django application owns a `tests/` directory containing tests for the behavior it is responsible for.

#### Implementation

| Application | `tests/` Directory | Owns |
| --- | --- | --- |
| `tap_grid` | `tap_grid/tests/` | Entity, Edge, BaseModel, service layer, FLIP, batch, history, dimensions, search, registry, GRIFT import, validation, constraints, icons |
| `tap_plugins` | `tap_plugins/tests/` | Plugin system machinery: discovery, manifest loading, registration, validation harness |
| `tap_api` | `tap_api/tests/` | API endpoints, serialization, auth, versioning, plugin API mounting |
| `tap_web` | `tap_web/tests/` | Web shell, panels, editors, page rendering, template behavior |
| `tap_viz` | `tap_viz/tests/` | Visualization models, views, Cytoscape integration |
| `plugins/<name>` | `plugins/<name>/tests/` | Plugin-specific behavior: custom editors, search runners, domain logic. See `spec-tap-plugin-testing.md`. |

Each `tests/` directory must contain an `__init__.py`.

**Ownership rule:** A test belongs to the application that owns the behavior under test, not the application that triggers it. For example, a test that verifies search execution belongs in `tap_grid/tests/`, even if a plugin search runner is the subject, because search execution is grid-owned behavior.

**Exception:** Plugin-specific tests that validate a plugin's unique functionality (e.g. a custom editor's form validation logic) belong in that plugin's `tests/` directory.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-test-layout-1 | Tests Dir Per App | In Development | Each application with testable behavior has a `tests/` directory with `__init__.py`. | |
| req-tap-test-layout-2 | Ownership By Behavior | In Development | Tests live in the application that owns the behavior being tested. | |
| req-tap-test-layout-3 | No Cross-App Test Dependencies | In Development | Application tests do not import from other applications' test modules. | |

#### Future
If test count grows large within an application, subdirectories within `tests/` (e.g. `tests/search/`, `tests/service/`) may be introduced.

### Shared Fixtures
----
RID: `req-tap-test-fixtures`
Status: `In Development`

Shared test fixtures live at the appropriate scope — but the UNIVERSAL harness
fixtures do **not** live in a conftest at all, and this is load-bearing.

#### Implementation

**The harness plugin (`tap/pytest_harness.py`):** The fixtures every suite in the
system depends on — `default_caller_context` (autouse; binds the `tap_test` actor
`CallerContext` with a fresh `batch_id` per DB test), the `django_db_setup`
auth-bootstrap seeding, and the `_service_write_hatch` — are a real pytest plugin
loaded via `-p tap.pytest_harness` in the configfile's `addopts` (with the
`pythonpath = ["."]` ini making the module importable at plugin-load time).

They moved out of the root conftest on 2026-08-09 because **conftest loading
depends on the invocation mode**: pytest 9.1 stopped loading the rootdir conftest
chain for `--pyargs`-resolved packages, which silently stripped the harness from
`pytest --pyargs tap_plugin.<slug>` — the per-plugin CI lane's exact invocation
and the documented evicted-plugin completion check — failing every plugin DB test
with `MissingActor` while the same files passed by path. `addopts` is the correct
carrier because it rides the same `[tool.pytest.ini_options]` block that delivers
`DJANGO_SETTINGS_MODULE` to those runs, so the harness provably travels wherever
Django settings do. (A `pytest11` entry point would be the textbook mechanism,
but the root project is a virtual — non-installed — uv project with no
distribution to register one from.)

**Root `conftest.py`:** Rootdir-scoped *collection* configuration only
(`collect_ignore` for uninstalled-plugin test dirs). Load-bearing fixtures must
not be moved back here.

**Application `conftest.py`:** Contains fixtures specific to that application's test needs. Example: `tap_api/tests/conftest.py` provides API client fixtures.

**Plugin `conftest.py`:** Plugins may provide their own `conftest.py` in `tests/` for plugin-specific fixtures.

Fixtures should be placed at the narrowest scope that makes sense:
- Harness plugin: truly universal fixtures (caller context, auth seeding, write hatch)
- App conftest: app-specific helpers (API clients, web request factories)
- Test file: fixtures used only in that file

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-test-fixtures-1 | Harness Caller Context | Implemented | The harness plugin provides the autouse `default_caller_context` fixture in every invocation mode. | Was "Root conftest provides..."; relocated 2026-08-09, see -4. |
| req-tap-test-fixtures-2 | Narrowest Scope Placement | In Development | Fixtures live at the narrowest conftest scope that covers their usage. | |
| req-tap-test-fixtures-3 | No Fixture Leakage | In Development | App-level fixtures do not depend on other apps' conftest files. | |
| req-tap-test-fixtures-4 | Invocation Independence | Implemented | The harness fixtures load under `pytest --pyargs tap_plugin.<slug>` (the per-plugin CI invocation), and the guard proving it can also detect their absence. | Guard: `tap/tests/test_pytest_harness_invocation.py` — positive arm (fixture visible under --pyargs) + negative arm (blanked `addopts` makes the same probe report absence). Born from the pytest 9.0.2→9.1.1 upgrade breaking every plugin suite's DB tests. |

#### Future
Factory-based test data generation (e.g. factory_boy) may be introduced when the number of model types makes manual setup painful.

### Test Conventions
----
RID: `req-tap-test-conventions`
Status: `In Development`

Tests follow consistent naming, style, and structural conventions.

#### Implementation

**Naming:**
- Test files: `test_<topic>.py` (e.g. `test_services.py`, `test_search_orm.py`)
- Test functions: `test_<what_it_does>` — describe the behavior, not the method (e.g. `test_create_entity_assigns_uuid` not `test_create`)
- Test classes: optional, use when grouping related tests (e.g. `TestSearchExecution`)

**Style:**
- Arrange-Act-Assert structure
- One logical assertion per test where practical
- Use early returns and `pytest.raises` for negative scenarios
- Prefer service-layer setup over direct ORM writes for TAP-managed data (per CLAUDE.md)
- Direct ORM setup is appropriate when intentionally testing model-level behavior

**Database:**
- Tests use Django's test database (created and destroyed per test run)
- PostgreSQL features (JSON fields, constraints) are available and should be tested
- Tests requiring cross-database-alias visibility (e.g. search readonly) must declare `databases=["default", "search_readonly"]` and use `transaction=True`

**What to test:**
- Test behavior, not implementation
- Test both positive and negative scenarios
- Test boundary conditions and edge cases for critical paths
- Do not test Django framework behavior (e.g. that `CharField` enforces `max_length`)

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-test-conventions-1 | Service Layer Setup Preferred | In Development | Application-level tests prefer service-layer setup over direct ORM writes. | |
| req-tap-test-conventions-2 | Behavior Over Implementation | In Development | Tests validate observable behavior rather than internal implementation details. | |
| req-tap-test-conventions-3 | Positive And Negative Scenarios | In Development | Tests cover both success and failure paths. | |

#### Future
Linting or custom pytest plugins may enforce naming conventions automatically.

### Tests Accompany Change
----
RID: `req-tap-test-accompaniment`
Status: `Implemented`

The project's standing test-and-quality policy (the OpenSSF Best Practices `test_policy`
and `warnings` criteria): changes that add or modify behavior include tests for that
behavior, and bug fixes include a regression test where the behavior is well-defined. The
full suite (`scripts/test`) must be green before a change reaches `main`, and code returns
clean from the formatters, linters, and type checker (`black`, `ruff`, `mypy`) — warnings
are fixed, not accumulated, and any suppression (`# noqa`, `# type: ignore`) carries a
justification at the line. Baseline ratchets (`spec-dev-validation.md`) may hold
pre-existing debt, but only ever ratchet down.

CLAUDE.md states this policy operationally for in-repo development; CONTRIBUTING.md (in
legal review as of 2026-08-10) states it for external contributors; the promote gate and
CI lanes enforce it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-test-accompaniment-1 | Tests accompany behavior change | Implemented | New or changed behavior lands with tests; recent history evidences the policy in practice. | OpenSSF `test_policy` / `tests_are_added`. |
| req-tap-test-accompaniment-2 | Warnings addressed, never accumulated | Implemented | Lint/type/format gates run in CI; suppressions are justified in-line; baselines only ratchet down. | OpenSSF `warnings` / `warnings_fixed` / `warnings_strict`. |

### Spec Linkage
----
RID: `req-tap-test-spec-linkage`
Status: `In Development`

Tests are connected to spec acceptance criteria through pytest markers.

#### Implementation

Tests reference acceptance criteria using `@pytest.mark.spec`:

```python
@pytest.mark.spec("req-example-dimension-core-1")
def test_dimensions_json_shape():
    ...
```

A single test may reference multiple ACIDs. A requirement moves to `Verified` status when all of its acceptance criteria have passing, linked tests.

The `spec` marker is registered in `pyproject.toml`:

```toml
markers = [
    "spec: link a test to one or more spec acceptance criteria by ACID",
]
```

Not every test needs a spec link. Tests that cover implementation details, edge cases beyond the spec, or exploratory scenarios may omit the marker.

**Resolution is enforced; coverage is not yet.** The `spec-marker-resolution` guard
(`tap/guards/spec_marker.py`) asserts every ACID named in a `@pytest.mark.spec` resolves to
a criterion that actually exists — a hard lint with no baseline, since every marker in the
tree already resolved when it landed. Until then the marker was registered and used but
**consumed by nothing**, so a test could cite a criterion that had been renamed or never
existed and the link would read as sound while pointing nowhere.

The other half — walking the markers to report which acceptance criteria have no linked
test, and deriving `Verified` from that — is the status-derivation work, not built. This
requirement stays `In Development` until it is: a resolving marker proves the citation is
real, not that the criterion is covered.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-test-spec-linkage-1 | Marker Registered | Implemented | `spec` marker is registered in pytest config. | |
| req-tap-test-spec-linkage-2 | ACID As Argument | In Development | The marker takes one or more ACID strings as arguments. | |
| req-tap-test-spec-linkage-3 | Verified Status Convention | In Development | A requirement reaches Verified when all ACIDs have linked passing tests. | |

#### Future
A spec-coverage report tool could scan tests for `@pytest.mark.spec` and cross-reference with spec files to identify untested acceptance criteria.

### Plugin Test Integration
----
RID: `req-tap-test-plugins`
Status: `In Development`

Plugin tests are discovered and run as part of the full test suite alongside application tests.

#### Implementation

Plugin tests live in `plugins/<name>/tests/` and are discovered via the `plugins` entry in `testpaths`. They participate in the same pytest run as application tests and have access to the same root fixtures.

Plugin tests fall into two categories:

1. **Plugin validation tests** — standardized tests provided by the plugin system (`tap_plugins`) that any plugin can run to verify structural correctness. See `spec-tap-plugin-testing.md` in `tap_plugins/specs/`.

2. **Plugin-specific tests** — hand-written tests for net-new functionality unique to the plugin (custom editors, search runners, domain logic).

The plugin system's own machinery tests (manifest loading, registration, validation harness) live in `tap_plugins/tests/`, not in individual plugins.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-test-plugins-1 | Plugins In Test Paths | Implemented | `plugins` is included in pytest `testpaths`. | |
| req-tap-test-plugins-2 | Plugin Tests Discovered | In Development | Tests in `plugins/<name>/tests/` are discovered by `pytest`. | |
| req-tap-test-plugins-3 | Root Fixtures Available | In Development | Plugin tests have access to root conftest fixtures (e.g. `default_caller_context`). | |
| req-tap-test-plugins-4 | Two Categories | In Development | Plugin testing is split between standardized validation and plugin-specific behavior tests. | |

#### Future
User-facing verification testing (running self-tests on a live system) is explicitly deferred. When it is introduced, it will likely be specified as a separate requirement in this spec or in a dedicated product-level testing spec.

### Plugin Tests Are Hermetic
----
RID: `req-tap-test-hermetic-plugins`
Status: `Proposed`

A plugin's tests must exercise the plugin using **only the plugin's own artifacts** plus core TAP types. Reaching across to another plugin's `grift/`, `static/`, `templates/`, or `tests/fixtures/` because those artifacts happen to be sitting in the tree is a **coincidental dependency** that breaks the moment the upstream plugin is renamed, de-registered, or restructured — and the breakage is invisible to whoever is changing the upstream.

The phrasing that matters: **depend-by-approval, not depend-because-it-happens-to-be-there.**

**Why this is here as its own requirement.** The genericom / KSI / lotr fixture coupling caused real pain when genericom was de-registered (2026-05-19): plugins that had been quietly using genericom data as test fixtures — without that dependency being a declared contract — broke for reasons no one could find without spelunking. `lotr` had by accident become load-bearing for ~19 core test suites — unwound 2026-07-02 by extracting the neutral `grid_fixtures` vocabulary the core suites now build their fixtures from, leaving lotr install-only + self-testing (nothing outside `plugins/lotr/` depends on it). That state should never recur elsewhere.

#### Implementation

**A plugin's `tests/fixtures/`** may contain only:

1. Artifacts the plugin itself generates (synthesized GRIFT, dataclass-built `VerificationResult`s, etc.).
2. Artifacts the plugin has vendored explicitly from a third party — accompanied by a `LICENSE` / `SOURCE` note in the fixture file or a sibling README explaining where it came from and why.
3. Artifacts produced by an **approved cross-plugin contract** (see below).

**A plugin's `grift/`** seed files may reference only:

1. Entity types and edge types declared by the plugin's own manifest.
2. Core TAP types (`Entity`, `Edge`, dimensions).
3. Types declared by an approved cross-plugin dependency.

**A plugin's `templates/` and `static/`** may reference only:

1. The plugin's own template paths and static URLs.
2. Core `tap_web` / `tap_viz` template / static paths.
3. Paths declared by an approved cross-plugin dependency.

**Approved cross-plugin dependencies.** When a plugin genuinely needs another plugin to function (e.g. `sigstore_core`'s `SIGNED_BY_IDENTITY` edge targets `github_workflow`, which is a `github_core` model), the dependency must be:

- **Stated in the dependent plugin's own spec** under a "Plugin Dependencies" section (or equivalent), naming the upstream plugin, the specific symbols / models / edges / fixtures relied upon, and the contract those upstream pieces must keep.
- **Narrow.** Reach for the minimum surface that satisfies the need. "We use `github_workflow.path` to resolve SAN URIs" is narrow; "we read whatever `github_core` happens to seed" is not.
- **Acknowledged on the upstream side** at some point in the future via a designed plugin-dependency declaration mechanism (currently does not exist in code; tracked here as a sub-requirement).

**Live-system fixtures.** Reaching out to the real GitHub / AWS / Rekor / etc. at test time is *not* cross-plugin coupling but it is *not* hermetic either. Such tests belong behind `@pytest.mark.live_fetch` (already configured in the root `pyproject.toml` to skip by default), and are subject to `req-tap-test-live-integration-backlog` below.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-test-hermetic-plugins-1 | Fixtures Owned | Proposed | A plugin's `tests/fixtures/` contains only plugin-owned, explicitly-vendored, or approved-cross-plugin artifacts. | |
| req-tap-test-hermetic-plugins-2 | GRIFT Hermetic | Proposed | A plugin's `grift/` files reference only the plugin's own types, core TAP types, or approved-cross-plugin types. | |
| req-tap-test-hermetic-plugins-3 | Templates / Static Hermetic | Proposed | A plugin's templates / static assets reference only the plugin's own paths, core paths, or approved-cross-plugin paths. | |
| req-tap-test-hermetic-plugins-4 | Cross-Plugin Deps Declared | Proposed | A plugin that depends on another plugin states the dependency in its own spec with the narrow contract named. | A first-class plugin-dependency declaration mechanism is future work — see Future below. |
| req-tap-test-hermetic-plugins-5 | Coincidental Deps Refused | Proposed | A new test or fixture that introduces an undeclared cross-plugin reference must be refused on review and reworked to be hermetic (or to declare the dependency). | This is a review-time rule, not a runtime guard. |

#### Future

A first-class **plugin-dependency declaration mechanism** is open work. The shape it should take: a plugin's `tap-plugin.toml` carries a `[dependencies]` section naming upstream plugins it requires; the plugin validation harness loads that section, fails structural validation if a declared upstream is missing, and the dependency surfaces in plugin listings and during promote-gate evaluation. This lets coincidental dependencies become detectable: if `sigstore_core` tests reach into `samsite/.well-known/`-shaped artifacts but `tap-plugin.toml` doesn't declare a samsite dependency, validation refuses the test. Until that mechanism exists, this requirement is a review-time discipline.

**Coincidental vs. deliberate is the real axis — and this rule's scope is in flux.** Everything above targets *coincidental* dependencies (reaching into another plugin's fixtures / grift / static because they happen to be sitting there). A *deliberately published, reusable surface* is a different and legitimate case that this requirement does not yet model: the page/panel architecture was built precisely so one plugin can define a panel (e.g. `roscale`'s `oscal_workbench`) and another plugin can mount it as a movable subject. That is an **intended** cross-plugin dependency, not a coincidental one — "depend-by-approval" *approving*, not the trap to prevent. Today both the coincidental kind (refuse) and the deliberate kind (a roscale panel reused by samsite) are governed by the same informal "approved cross-plugin contract" hand-wave, which is doing too much work to cover two opposite intents. **Backlogged decision:** the next time a real cross-plugin dependency comes up, graduate this from review-time discipline into a designed plugin-dependency model — declared `[dependencies]`, named narrow contracts, versioning, and detectable breakage — rather than adding another ad-hoc approval. The movable-panel case (samsite mounting roscale's OSCAL renderer) is the current motivating example; if the OSCAL renderer is consumed cross-plugin it should be reachable from a shared home or declared, not reached-into.

### Live-Integration Test Harness (Backlog)
----
RID: `req-tap-test-live-integration-backlog`
Status: `Backlog`

TAP now has plugins that pull from live external systems on a cadence (`github_core` pulls GitHub; `aws_core` pulls AWS; `sigstore_core`'s verifier will pull TUF trust roots and, in v1, may pull Rekor). The TAP suite has no designed way to exercise those live-pull paths over time. Today the situation is:

- `@pytest.mark.live_fetch` exists at the pytest level and is skipped from `addopts` by default.
- There is no schedule, no environment matrix, and no result-tracking surface for live tests.
- There is no contract for what live tests are "supposed" to do — smoke a known query? probe shape stability? assert quotas? verify auth still works? all of the above on different cadences?

A designed live-integration test harness should answer:

- **What gets exercised, on what cadence?** A daily smoke that pulls a tiny known shape from each live integration is different from a weekly full-shape probe that asserts schema stability.
- **Where do results land?** A per-run record on the grid (a `live_integration_run` node) seems right — durable, queryable, historical, surfaces drift over time.
- **How are credentials managed?** Live tests need real credentials with read-only scopes. Plugin-owned secret kinds (`github_pat`, AWS profile, etc.) are the existing pattern; live tests would consume the same secrets the live collectors do.
- **What constitutes failure?** A live integration that returns "schema as expected, zero results" is different from "auth failed" is different from "schema drifted." The harness needs structured pass/warn/fail/skip outcomes per integration.
- **Where do the test specifications live?** In each plugin's `tests/live/` directory, presumably, with shared harness primitives in `tap_plugins` or a new `tap_cares` surface.

This is genuine v1 design work and is parked as Backlog until either (a) a live integration breaks silently in a way the missing harness would have caught, or (b) the cadence of live-collector usage makes the absence of probing visibly painful. v0 plugins should continue to use `@pytest.mark.live_fetch` for any live-touching tests they add, with a comment noting that such tests will graduate to the harness when it exists.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-test-live-integration-backlog-1 | Harness Designed | Backlog | A designed harness for live-integration exercise lands, with answers to the open questions above. | |
| req-tap-test-live-integration-backlog-2 | Live Tests Migrated | Backlog | Existing `@pytest.mark.live_fetch` tests across `github_core`, `aws_core`, and `sigstore_core` migrate to the harness. | |
| req-tap-test-live-integration-backlog-3 | Result Recording | Backlog | Live-integration runs record structured per-integration outcomes on the grid for drift tracking. | |
