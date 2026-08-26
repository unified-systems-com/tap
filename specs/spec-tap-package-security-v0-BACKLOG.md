# TAP Package Security v0 Specification

## Philosophy

TAP now treats Python packages as part of the platform boundary, not just as a
developer convenience. Core dependencies arrive through `uv sync`, and
profile-selected plugins arrive through the pre-Django install stage as uv-backed
packages from git, index, path, editable, and later wheelhouse sources. That
makes the package resolver an authority path: if a known-malicious package enters
the environment, TAP may import and execute it before any app-level guard can
react.

This spec defines the backlog target for a first package-security layer. The
initial priority is the "known-malicious package" class: OSV records from the
OpenSSF Malicious Packages database, identified by the `MAL-` advisory prefix.
A match in any resolved dependency closure is treated as an incident-class
condition, not as an ordinary dependency warning. Known CVEs remain important,
but they are a monitoring and health-notification surface in v0, not a boot
blocker.

Because uv's malware check is currently a preview feature, TAP must not build
its policy on "the upstream flag exists today" alone. TAP owns the policy and
the observable report; uv and OSV are evidence sources and execution helpers.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Fail Before Load | Known-malicious packages are blocked before install/import/load whenever TAP controls the install path. |
| 2. | Full Closure | The guard evaluates the full resolved dependency closure, not only the direct plugin or root package. |
| 3. | One Policy Surface | Root sync, plugin preboot installs, scheduled rechecks, reports, and health probes share one package-security policy. |
| 4. | Observable Decisions | Every scan records what was checked, what source was queried, what policy decided, and why. |
| 5. | Secure Defaults | Enforcement is on for every profile; report-only/disabled modes and exceptions are explicit break-glass affordances that never leave health green. |
| 6. | Online First | v0 assumes online OSV access. Offline advisory snapshots and signed wheelhouse manifests are deep backlog. |

## Prior Art And Source Material

- **uv malware checks** - uv documents on-sync malware checking as a preview
  feature. With `UV_MALWARE_CHECK=1`, uv checks locked dependencies against OSV
  during sync and terminates the sync on a malware advisory. The preview feature
  name is `malware-check` and can be enabled through `UV_PREVIEW_FEATURES`.
  Source: <https://docs.astral.sh/uv/concepts/projects/sync/#malware-checks>
  and <https://docs.astral.sh/uv/concepts/preview/>.
- **uv audit** - uv also exposes `uv audit`, backed by OSV-format services, with
  text, JSON, and SARIF output. This is the right model for CVE visibility, but
  not the first install-time fail-closed guard. Source:
  <https://docs.astral.sh/uv/reference/cli/#uv-audit>.
- **uv no-build / wheel-only safety** - uv's `--no-build` / `--only-binary :all:`
  path prevents resolving by running arbitrary Python build code. This is the
  package-install posture TAP wants for non-dev plugin package sources. Source:
  <https://docs.astral.sh/uv/reference/cli/>.
- **OSV schema** - OSV records use stable database prefixes in the `id` field;
  `MAL` is the prefix for the Malicious Packages Repository, with OSV-formatted
  records available through the OSV API. Source:
  <https://ossf.github.io/osv-schema/>.
- **OpenSSF malicious-packages** - the OpenSSF repository defines malicious
  package scope separately from ordinary vulnerability reports, including
  typosquatting, account takeover, malicious prebuilt binaries, dependency
  confusion, and install/use behavior that would require incident response.
  Source: <https://github.com/ossf/malicious-packages>.
- **OSV API** - OSV supports single and batched package/version queries and
  returning full advisory records by ID. The v0 TAP online scanner should use
  those stable API shapes. Source: <https://google.github.io/osv.dev/api/>.
- **TAP health system** - `spec-tap-health-v0` already provides first-party
  probe registration, four-state status, grouping, criticality, and trusted CLI
  projection. Package-security drift belongs there after boot.
- **TAP plugin report** - `tap_plugins.report.build_report()` and
  `plugin-report.schema.json` already provide the assembled-plugin inspection
  surface. Package-security status should extend that report instead of creating
  a separate plugin-only report.

These sources are input, not copied implementation. TAP must write its own small
integration layer and must keep source-material checks current before promoting
this backlog item to implementation.

## Relationship To Other Specs

- **`tap_plugins/specs/spec-tap-plugin-architecture.md`** - plugin preboot installs
  are the first high-value consumer of this package-security policy. The plugin
  spec carries only the integration requirement; this spec owns the policy.
- **`specs/spec-tap-health-v0.md`** - runtime package-security drift and known
  CVE notification surface through first-party health probes.
- **`specs/spec-dev-validation.md`** - the validation map should gain package
  security rows when guards/checks are implemented.
- **`specs/spec-security-posture-corpus.md`** - supply-chain controls should cite
  this spec when the security control ledger graduates from proposed assurance
  material to active package-security evidence.
- **`specs/spec-tap-boot-v0.md`** - the pre-Django boot stage is where
  install-time package security must run for plugins, because Django settings do
  not exist yet.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-pkg-security-scope | [Package Security Scope](#package-security-scope) | Backlog | Covers root sync, plugin package installs, scheduled rechecks, report surfaces, and health probes |
| req-tap-pkg-security-policy | [Policy Configuration](#policy-configuration) | Backlog | Settings-free enforcement policy; secure default; break-glass relaxations are loud |
| req-tap-pkg-security-malware | [Known-Malicious Guard](#known-malicious-guard) | Backlog | `MAL-*` advisory match fails closed before install/load |
| req-tap-pkg-security-closure | [Resolved Closure Plan](#resolved-closure-plan) | Backlog | Scan the full dependency closure without installing or executing target packages |
| req-tap-pkg-security-wheel-only | [Wheel-Only Non-Dev Installs](#wheel-only-non-dev-installs) | Backlog | Non-dev package sources must not build sdists during guarded install |
| req-tap-pkg-security-uv | [uv Integration](#uv-integration) | Backlog | Use uv's malware/audit features where they fit; TAP owns the policy/report |
| req-tap-pkg-security-cve | [Known Vulnerability Visibility](#known-vulnerability-visibility) | Backlog | CVEs/advisories are reported and surfaced through health; not a v0 boot block |
| req-tap-pkg-security-report | [Package Security Report](#package-security-report) | Backlog | Structured report and plugin-report projection |
| req-tap-pkg-security-health | [Health And Scheduled Rechecks](#health-and-scheduled-rechecks) | Backlog | Health probes read cached scan state; scheduler can refresh it |
| req-tap-pkg-security-online | [Online First, Offline Later](#online-first-offline-later) | Backlog | v0 queries OSV live; offline support is named deep backlog |
| req-tap-pkg-security-validation | [Validation](#validation) | Backlog | Tests and guards prove fail-closed behavior and report shape |
| req-tap-pkg-security-nongoals | [v0 Non-Goals](#v0-non-goals) | Backlog | Offline advisory mirror, signature verification, SBOM governance, and remediation workflows deferred |

### Package Security Scope
----
RID: `req-tap-pkg-security-scope`
Status: `Backlog`

Package security is a platform-level concern covering every Python package TAP
installs or continues to run.

#### Implementation Direction

In v0 the in-scope package surfaces are:

- root/core project sync through `uv sync`
- profile-driven plugin installs in `tap/preboot.py`
- later scheduled rechecks over the installed environment
- package-security fields in the plugin report
- package-security health probes for post-boot drift

The policy is not plugin-specific. Plugins are simply the first place where TAP
is dynamically installing package artifacts based on profile state.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-pkg-security-scope-1 | Root And Plugin Coverage | Backlog | The package-security policy covers root sync and plugin package installs. | |
| req-tap-pkg-security-scope-2 | Runtime Drift Named | Backlog | The same policy has a scheduled/runtime recheck path for packages already installed. | |
| req-tap-pkg-security-scope-3 | Plugin Is A Consumer | Backlog | Plugin install security is specified as a consumer of this platform policy, not as a standalone plugin-only rule. | |

### Policy Configuration
----
RID: `req-tap-pkg-security-policy`
Status: `Backlog`

The package-security policy is controlled by settings-free boot policy, not by
Django `settings.py`.

#### Implementation Direction

The plugin install guard runs before Django imports settings, so `settings.py`
cannot be the source of truth for install-time enforcement. The effective policy
should be resolved through the same style of boot-variable ladder used by the
preboot stage: environment/profile/default, recorded once, and emitted in the
security report.

The policy mode vocabulary is:

| Mode | Meaning |
| --- | --- |
| `enforce` | Known-malicious findings fail the operation before install/load. Default for every profile. |
| `report_only` | Findings are reported, but the operation continues. Break-glass only; health must report that enforcement is bypassed. |
| `disabled` | No online package-security query is made. Break-glass only; health must report that coverage is absent. |

Known-malicious exceptions are deliberately narrower than a general allow-list.
An exception must name the exact `ecosystem`, normalized package name, version,
advisory ID, reason, approver, and expiry. Exceptions are break-glass relief
valves, not profile defaults. If an exception allows a package with a `MAL-*`
finding to remain installed or loadable, TAP must preserve that truth in health:
the instance is running with known-malicious package risk accepted for a named,
expiring reason. The system may keep running, but it must not look healthy.

Runtime settings may mirror the effective policy for UI/reporting, but they do
not authorize pre-install enforcement.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-pkg-security-policy-1 | Settings-Free Source Of Truth | Backlog | Install-time policy resolves before Django settings exist and does not depend on `settings.py`. | |
| req-tap-pkg-security-policy-2 | Enforce By Default | Backlog | Every profile defaults to `enforce` for known-malicious package findings. | |
| req-tap-pkg-security-policy-3 | Break-Glass Only | Backlog | `report_only`, `disabled`, and known-malicious exceptions are explicit break-glass states, never profile-default relaxations. | |
| req-tap-pkg-security-policy-4 | Effective Policy Reported | Backlog | Reports record the resolved mode, source, exception set, and whether a beta uv feature was involved. | |
| req-tap-pkg-security-policy-5 | Exceptions Expire | Backlog | Every exception has an expiry and exact advisory/package/version match; broad package or source exceptions are rejected. | |
| req-tap-pkg-security-policy-6 | Break-Glass Health Is Red | Backlog | A bypassed known-malicious finding or disabled guard is visible in health and cannot be collapsed into healthy state. | |

### Known-Malicious Guard
----
RID: `req-tap-pkg-security-malware`
Status: `Backlog`

A package matched by an OSV `MAL-*` advisory is treated as known malicious and
fails closed before install/load when policy mode is `enforce`.

#### Implementation Direction

The classifier is:

- advisory `id` starts with `MAL-`; or
- any advisory alias starts with `MAL-`.

The scanner should preserve full OSV advisory metadata in the report, including
`database_specific.malicious-packages-origins` when present, but the classifier
does not depend on that database-specific field. The stable cross-source signal
is the `MAL` database prefix.

The guard checks the resolved dependency closure for:

- root packages synced by the project lock
- every enabled plugin package
- every transitive dependency introduced by those packages
- local/path/editable package names and versions when metadata is available

No source type is categorically skipped. If a source type cannot produce a
pre-install package/version plan safely, the guard fails as unsupported under
`enforce` rather than silently treating it as clean.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-pkg-security-malware-1 | `MAL-*` Classifier | Backlog | `MAL-*` in OSV `id` or aliases is the known-malicious classifier. | |
| req-tap-pkg-security-malware-2 | Fail Closed Before Load | Backlog | In `enforce` mode, a match aborts before package install/import/plugin discovery proceeds. | |
| req-tap-pkg-security-malware-3 | No Source-Type Skip | Backlog | Git, index, wheelhouse, path, and editable sources all enter the guard; unsupported safe planning is a failure in `enforce`. | |
| req-tap-pkg-security-malware-4 | Full Advisory Preserved | Backlog | Reports retain advisory IDs, aliases, summary, affected package/version, references, source service, and malicious-package origins when present. | |

### Resolved Closure Plan
----
RID: `req-tap-pkg-security-closure`
Status: `Backlog`

The package-security guard evaluates a resolved dependency closure before
installing or loading packages.

#### Implementation Direction

TAP should introduce a settings-free package-security planner used by the
preboot installer and by later scheduled scans. The planner emits a structured
plan of package coordinates:

- ecosystem, initially `PyPI`
- normalized package name
- version
- requested-by surface (`root`, `plugin:<slug>`, later other surfaces)
- direct/transitive relationship
- source type (`lock`, `git`, `index`, `wheelhouse`, `path`, `editable`)
- hash or artifact URL when available

The planner must not install target packages, import target code, or run target
build hooks. For non-dev package sources it should use uv resolution paths with
no-build/wheel-only constraints. The exact uv command shape is an implementation
choice, but the observable contract is the plan above plus tests proving a
malware match is blocked before install.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-pkg-security-closure-1 | Structured Plan | Backlog | The guard consumes a structured package plan, not console text parsing. | |
| req-tap-pkg-security-closure-2 | Full Closure | Backlog | The plan includes transitive dependencies as well as direct plugin/root packages. | |
| req-tap-pkg-security-closure-3 | No Target Execution | Backlog | Planning does not import target packages or run target build hooks. | |
| req-tap-pkg-security-closure-4 | Requested-By Attribution | Backlog | Every package coordinate records which root/plugin surface introduced it. | |

### Wheel-Only Non-Dev Installs
----
RID: `req-tap-pkg-security-wheel-only`
Status: `Backlog`

Non-dev package installs must avoid source builds during the guarded install
path.

#### Implementation Direction

For non-dev plugin sources, TAP should require wheel-compatible resolution and
install with uv's no-build / only-binary posture. An sdist-only dependency is a
loud install-policy failure, not a reason to execute arbitrary build code during
boot.

Editable and path sources remain supported for development, but they are not a
reason to skip package-security scanning. Their dependency closure still enters
the guard. If local source metadata cannot be resolved without executing local
build code, that is allowed only under an explicit break-glass relaxed policy
and must be health-visible.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-pkg-security-wheel-only-1 | Non-Dev No-Build | Backlog | Non-dev package installs use no-build / wheel-only constraints. | |
| req-tap-pkg-security-wheel-only-2 | sdist Is Loud | Backlog | A package requiring source build in non-dev fails with an install-policy error. | |
| req-tap-pkg-security-wheel-only-3 | Dev Sources Still Scanned | Backlog | Editable/path sources are scanned where metadata permits and are never categorically ignored. | |

### uv Integration
----
RID: `req-tap-pkg-security-uv`
Status: `Backlog`

TAP uses uv's security features where they fit, while keeping TAP's own policy
and report stable.

#### Implementation Direction

The root project sync should run with uv's malware check enabled when TAP's
policy mode is `enforce` or `report_only`:

- `UV_MALWARE_CHECK=1`
- `UV_PREVIEW_FEATURES` including `malware-check` while uv marks it preview

Plugin installs currently use `uv pip install`, which is not the same project
sync path described by uv's on-sync malware-check documentation. The plugin
preboot path therefore needs the TAP package-security guard before invoking
`uv pip install`.

Because uv's malware feature is preview, TAP should record the uv version and
whether a preview feature was used on every package-security result. "Pinning
uv" means replacing a floating installer/image such as `ghcr.io/astral-sh/uv:latest`
with an exact uv version or image digest so upstream preview behavior cannot
change underneath a TAP boot. v0 does not require pinning while TAP owns the
pre-install policy; pinning becomes required before TAP treats uv preview
behavior as the sole enforcement mechanism for any path.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-pkg-security-uv-1 | Root Sync Enables uv Malware Check | Backlog | Root `uv sync` uses uv malware checking when package-security policy is active. | |
| req-tap-pkg-security-uv-2 | Plugin Path Has TAP Guard | Backlog | Profile-driven plugin `uv pip install` is guarded by TAP's pre-install package-security planner/checker. | |
| req-tap-pkg-security-uv-3 | uv Version Recorded | Backlog | Reports record the uv version and preview-feature usage. | |
| req-tap-pkg-security-uv-4 | No Direct Reliance On Preview Semantics | Backlog | TAP's policy/report contract remains stable if uv changes preview feature names or exact command behavior. | |
| req-tap-pkg-security-uv-5 | Pin Before Sole Reliance | Backlog | Any path that relies solely on uv preview malware enforcement pins uv to an exact version or digest first. | |

### Known Vulnerability Visibility
----
RID: `req-tap-pkg-security-cve`
Status: `Backlog`

Known vulnerabilities and adverse package statuses are visible, but they do not
block boot/install in v0.

#### Implementation Direction

The v0 CVE path should use `uv audit` or an OSV-compatible query over the same
package plan. Its output is normalized into the package-security report and into
health. The initial health behavior is:

- no vulnerable packages: healthy
- known CVE/advisory findings: degraded or non-critical unhealthy, preserving
  details for the trusted CLI/rich report
- scanner unavailable: unknown/degraded depending on whether a previous cached
  result exists

Severity thresholds, remediation SLAs, ignore policies, and automatic upgrades
are future decisions. v0 should surface the fact that CVEs exist without
refusing to boot a package set that is not known malicious.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-pkg-security-cve-1 | CVEs Do Not Block v0 Boot | Backlog | Ordinary CVE/advisory findings are report/health signals, not install blockers. | |
| req-tap-pkg-security-cve-2 | Same Package Plan | Backlog | CVE auditing runs over the same resolved package plan used by the malware guard. | |
| req-tap-pkg-security-cve-3 | Health Notification | Backlog | Known CVEs produce a visible package-security health status with trusted detail. | |
| req-tap-pkg-security-cve-4 | Future Policy Named | Backlog | Severity thresholds, remediation SLA, and vulnerability exceptions are explicitly deferred. | |

### Package Security Report
----
RID: `req-tap-pkg-security-report`
Status: `Backlog`

Every package-security run produces a structured report, and plugin-facing
facts are projected into the plugin report.

#### Implementation Direction

The package-security report is the canonical runtime artifact. It should include:

- schema version
- generated timestamp
- policy mode and policy-source provenance
- uv version and feature flags used
- advisory source (`osv` URL, query time, response status)
- scan target (`root`, `plugin:<slug>`, `installed_environment`)
- resolved package plan
- known-malicious findings
- vulnerability findings
- policy decision (`pass`, `blocked`, `report_only_findings`, `unknown`)
- exception records applied, if any

The first implementation does not need to overbuild durable report storage:
install-time malware guard outcomes are operationally binary (`pass` or
`blocked`, with break-glass states reported loudly). The immediate requirement is
that the decision be observable in logs, health, and the plugin report projection.

Durable report persistence is backlog on the future `tap_files` layer. Once TAP
has a first-class file/artifact storage surface, package-security reports should
be stored on disk through that mechanism. At that point the report format is a
new structured on-disk artifact and must ship with a JSON Schema and validate at
load. The plugin report should project the per-plugin subset: security status,
last scan timestamp, package count, malicious finding count, vulnerability
finding count, and policy decision. The plugin report remains a projection; it
does not become the canonical scanner output.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-pkg-security-report-1 | tap_files Persistence Deferred | Backlog | Durable on-disk package-security reports wait for `tap_files`; when persisted, the format has a JSON Schema and validates loudly at load/build. | |
| req-tap-pkg-security-report-2 | Policy Decision Recorded | Backlog | Reports record the policy mode, result, findings, exceptions, source service, and uv version. | |
| req-tap-pkg-security-report-3 | Plugin Projection | Backlog | `manage.py plugins --json` projects per-plugin package-security status once the guard exists. | |
| req-tap-pkg-security-report-4 | Trusted Detail Boundary | Backlog | Rich advisory/package detail is available only on trusted surfaces; coarse surfaces do not leak unnecessary environment detail. | |

### Health And Scheduled Rechecks
----
RID: `req-tap-pkg-security-health`
Status: `Backlog`

Package-security state is re-checkable after boot and visible through TAP health.

#### Implementation Direction

The install-time guard catches packages known to be malicious at install time.
A package may become known-malicious or vulnerable later. TAP should therefore
provide a recheck path that reuses the package-security planner/checker against
the installed environment or cached install report.

The scheduler is the natural trigger surface once this graduates:

- a scheduled package-security recheck refreshes the cached report daily by
  default
- the health probe reads the latest cached result rather than performing a slow
  network query on the health request path
- a known-malicious finding in the installed environment is critical/unhealthy
- CVE findings are non-critical/degraded unless a future vulnerability policy
  says otherwise

The scheduled recheck cadence is a runtime settings knob, because it runs after
Django settings exist and is operational policy rather than install-time
authority. The same settings surface is the future home for runtime advisory
source configuration once TAP supports vulnerability sources other than the
default OSV endpoint. If a future implementation needs to change the pre-Django
install-time advisory source as well, it must add a settings-free boot-policy
mirror; preboot cannot import `settings.py`.

Break-glass states are health-visible. If the guard is disabled, in report-only
mode, or carrying an exception that permits a `MAL-*` package to run, the health
probe reports that state explicitly. A bypassed known-malicious finding is
critical/unhealthy even though the break-glass policy allowed boot or install to
continue.

The first health probes should be first-party app probes, not plugin-contributed
probes.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-pkg-security-health-1 | Cached Health Input | Backlog | Health reads the latest package-security report/cache; it does not run an online scanner in the request path. | |
| req-tap-pkg-security-health-2 | MAL Is Critical | Backlog | A known-malicious finding in the installed environment makes the package-security health probe critical/unhealthy. | |
| req-tap-pkg-security-health-3 | CVEs Degrade | Backlog | Known vulnerabilities surface as visible degraded/non-critical health state in v0. | |
| req-tap-pkg-security-health-4 | Daily Scheduler Refresh | Backlog | A scheduled task refreshes package-security state daily by default using the same scanner contract. | |
| req-tap-pkg-security-health-5 | Runtime Settings | Backlog | Recheck cadence and future runtime advisory-source selection are configurable through Django settings. | |
| req-tap-pkg-security-health-6 | Break-Glass Health Signal | Backlog | Disabled/report-only mode or a known-malicious exception is health-visible; bypassed `MAL-*` risk is critical/unhealthy. | |

### Online First, Offline Later
----
RID: `req-tap-pkg-security-online`
Status: `Backlog`

v0 uses online OSV lookups. Offline support is explicitly deferred.

#### Implementation Direction

The first implementation may require network access to OSV and should fail
loudly under `enforce` when the malware check cannot obtain a result before
install. In `report_only`, an unavailable scanner records an `unknown` result
and continues.

Offline support is deep backlog and should not contort v0. The likely future
shape is a signed advisory snapshot or wheelhouse security manifest produced in
connected CI and consumed during airgapped boot.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-pkg-security-online-1 | OSV Online Source | Backlog | v0 queries OSV live for malware/vulnerability evidence. | |
| req-tap-pkg-security-online-2 | Enforce Requires Result | Backlog | In `enforce`, inability to check known-malicious status before install fails loud. | |
| req-tap-pkg-security-online-3 | Offline Named Deferred | Backlog | Advisory snapshots, offline mirrors, and signed wheelhouse security manifests are named backlog items, not v0 requirements. | |

### Validation
----
RID: `req-tap-pkg-security-validation`
Status: `Backlog`

Package-security behavior is guarded by deterministic tests before being relied
on in boot.

#### Implementation Direction

Validation should cover:

- `MAL-*` classifier on `id` and aliases
- full dependency closure attribution
- pre-install fail-closed ordering for plugin installs
- break-glass policy modes and health-red signaling
- exception exact-match and expiry behavior
- schema validation for package-security report
- plugin-report projection shape
- health status derivation from cached reports

Once implemented, `spec-dev-validation.md` should add package-security rows to
the generated validation map.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-pkg-security-validation-1 | Classifier Tests | Backlog | Tests prove `MAL-*` classifier behavior for advisory `id` and aliases. | |
| req-tap-pkg-security-validation-2 | Pre-Install Ordering Test | Backlog | A malicious dependency fixture aborts before the install command runs. | |
| req-tap-pkg-security-validation-3 | Policy Tests | Backlog | Tests cover enforce/report_only/disabled modes, exception exact-match/expiry, and health-red break-glass behavior. | |
| req-tap-pkg-security-validation-4 | Report Schema Tests | Backlog | Package-security report and plugin-report projection validate against schemas. | |
| req-tap-pkg-security-validation-5 | Health Tests | Backlog | Health status derives correctly from cached malicious and CVE findings. | |

### v0 Non-Goals
----
RID: `req-tap-pkg-security-nongoals`
Status: `Backlog`

#### Non-Goals

- Offline OSV/advisory mirrors.
- Artifact signing, Sigstore verification, or TUF-style repository metadata.
- SBOM governance beyond optional uv export evidence.
- Automatic remediation or dependency upgrades.
- CVE severity thresholds or remediation SLAs.
- Silent allow-listing of known-malicious package advisories.
- A general plugin-contributed health-probe system.
- Scanning non-Python package ecosystems.
- Autonomous agent actions in response to package-security findings.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-pkg-security-nongoals-1 | Deferrals Named | Backlog | Offline, signing, SBOM, remediation, CVE policy, and non-Python ecosystems are explicitly deferred. | |
| req-tap-pkg-security-nongoals-2 | No Autonomous Remediation | Backlog | Findings do not trigger autonomous install/upgrade/remove actions in v0. | |
