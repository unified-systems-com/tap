# Grid Security Specification

## Philosophy

Some security requirements in TAP are local to one subsystem, but others are platform-level contracts that higher-level functionality must inherit rather than redefine. These requirements belong close to the grid/platform layer so web, plugins, APIs, and future runtimes can reference one authoritative security baseline.

The first requirement in this specification addresses third-party vendored components checked into the TAP repository. Once external code is copied into TAP and shipped as part of the platform, TAP needs a consistent provenance and tracking contract rather than ad hoc comments or undocumented downloads.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Platform-Level | Define security contracts that apply across TAP subsystems rather than only one app |
| 2. | Traceable | Third-party vendored code and assets have explicit provenance and version tracking |
| 3. | Auditable | Humans and tooling can inspect what external components are present in TAP |
| 4. | Reusable | Higher-level specs such as web and plugins can delegate to one grid-level requirement |
| 5. | Evolvable | Lightweight manifest tracking today does not block later SPDX or CycloneDX adoption |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-thirdparty-manifest.sec | [Third-Party Component Manifest](#third-party-component-manifest) | Proposed | Platform-level contract for tracking third-party code and assets — both vendored in TAP source AND downloaded by the build process |
| req-grid-icon-static-svg.sec | [Static Svg Icon Security](#static-svg-icon-security) | Proposed | Security contract for shipped app/plugin SVG icons |
| req-grid-icon-upload-svg.sec | [Uploaded Svg Icon Security](#uploaded-svg-icon-security) | Backlog | Future security contract for user-uploaded SVG icons |
| req-grid-flip-write-batch.sec | [Domain Writes Must Use Batch Context](#domain-writes-must-use-batch-context) | Backlog | All domain object mutations must occur within an active batch context for auditability |
| req-grid-db-permission-flaw.sec | [Database Permission Errors Emit A Flaw](#database-permission-errors-emit-a-flaw) | Implemented | Any PostgreSQL permission-denied (SQLSTATE 42501) on any Django connection emits a `security` Flaw at a single connection-layer chokepoint; generalizes the read-only write-block guard and forward-proofs least-privilege DB roles |
| req-grid-db-role-concurrency.sec | [Cluster-Global Role Provisioning Is Concurrency-Safe](#cluster-global-role-provisioning-is-concurrency-safe) | Implemented | Provisioners of cluster-global PostgreSQL objects (roles/databases/tablespaces) reconcile in a savepoint and retry on `tuple concurrently updated` — parallel test workers and concurrent instance boots on a shared cluster collide otherwise; advisory locks (per-database) can't serialize it |
| req-grid-table-classification.sec | [Grid Table Classification Is Declared Once And Derived Everywhere](#grid-table-classification-is-declared-once-and-derived-everywhere) | Verified | Every security consumer of "which tables are grid tables" derives from one model-declared classification (`GRID_TABLE_ROLE`); spine is core-only, a BaseModel can never claim it, and the DB grant reconciles against tables that actually exist |

---

### Third-Party Component Manifest
----
RID: `req-grid-thirdparty-manifest.sec`
Status: `Proposed`
Tags: `Security`

Third-party code or assets shipped as part of a TAP runtime image must be tracked in a machine-readable manifest. This is a platform-level supply-chain security requirement: once a component is part of what TAP runs, its provenance, version, and license must not rely on memory, commit archaeology, or informal comments.

The contract covers two artifact-delivery modes:

- **Source-vendored components** — files committed under the owning app's static / vendor tree (browser libraries, CSS, copied Python code, etc.). Integrity is verified against the committed file at audit time.
- **Build-time-downloaded components** — artifacts pulled by the build process (a Dockerfile `RUN`, an installer script) that land inside the runtime image without entering source control (build tools, runtime binaries that are too large to vendor sensibly). Integrity is enforced at build time by verifying the downloaded artifact against a manifest-pinned checksum before installing.

Both modes use the same `third_party_manifest.toml` at the owning app's root, with `[[component]]` entries that share most of the same fields and diverge only on how the integrity hash is named and where the artifact lives.

#### Status Details
New cross-cutting security requirement proposed so subsystems such as `tap_web` can vendor browser libraries AND pin build-time-downloaded binaries (e.g. the `tailwindcss` CLI) under one TAP-wide manifest contract.

#### Implementation
- This requirement applies to third-party components shipped as part of a TAP runtime image, including:
  - JavaScript libraries
  - CSS libraries
  - front-end assets
  - copied Python code from external projects
  - other shipped third-party source artifacts
  - build-time-downloaded binaries (CLIs, tools) installed into the image at build time
- Each third-party component must have an entry in a machine-readable manifest maintained in the repository.
- The manifest is the canonical TAP record for component provenance.
- Each TAP app or plugin that ships third-party components maintains its own manifest file at the app root named `third_party_manifest.toml`.
- The canonical authoring format is TOML.
- The manifest must record, at minimum:
  - component name
  - version
  - local file path or file set (empty when the component is build-time-downloaded and not in source)
  - upstream source location
  - license identifier or license reference
  - integrity data — either a single `checksum_sha256` for source-vendored files OR per-platform `checksum_sha256_<os>_<arch>` keys for build-time-downloaded binaries
- The manifest uses one `[[component]]` entry per third-party component.
- Each `[[component]]` entry must define:
  - `name`
  - `version`
  - `files`
  - `source_url`
  - `license`
  - one of: `checksum_sha256` (source-vendored) OR one-or-more `checksum_sha256_<os>_<arch>` (build-time-downloaded)
- `files` is an array of repository-relative file paths. For build-time-downloaded components it is `[]`.
- `license` should use an SPDX license identifier when one exists; otherwise it must use a clear license reference string.
- `checksum_sha256` represents the integrity value of the committed file set.
- `checksum_sha256_<os>_<arch>` keys (one per supported platform variant) capture the integrity hash of the corresponding upstream release artifact. The build step that downloads each variant MUST compute its SHA-256 and compare against the manifest-pinned value before installing; mismatch MUST abort the build (`req-grid-thirdparty-manifest.sec-10`). Platform suffixes use the convention `<os>_<arch>` with underscores (e.g. `linux_x64`, `linux_arm64`, `macos_arm64`) so the key is a valid bare TOML identifier and grep-friendly.
- `version` should record the upstream component version. If a legacy vendored artifact does not expose a determinable version, `version = "unknown"` may be used temporarily until provenance is cleaned up.
- SPDX or CycloneDX may be generated from the canonical manifest later, but they are not required as the hand-authored source format in v1.
- Higher-level TAP subsystems that ship third-party components must comply with this requirement rather than define incompatible local tracking formats.

Canonical TOML shape — **source-vendored** variant (committed files):

```toml
[[component]]
name = "tabulator"
version = "6.3.0"
files = [
  "tap_web/static/tap_web/js/lib/tabulator.min.js",
  "tap_web/static/tap_web/css/lib/tabulator.min.css",
]
source_url = "https://github.com/olifolkerd/tabulator/releases/tag/6.3.0"
license = "MIT"
checksum_sha256 = "..."
```

Canonical TOML shape — **build-time-downloaded** variant (binary installed into the image by the Dockerfile):

```toml
[[component]]
name = "tailwindcss"
version = "3.4.17"
# Build-time CLI binary. The Dockerfile downloads the per-arch release
# from source_url at image build, verifies its SHA-256 against the
# matching checksum_sha256_<os>_<arch> below, and installs to
# /usr/local/bin/tailwindcss. Nothing is committed to source.
files = []
source_url = "https://github.com/tailwindlabs/tailwindcss/releases/tag/v3.4.17"
license = "MIT"
checksum_sha256_linux_x64 = "..."
checksum_sha256_linux_arm64 = "..."
```

#### Development
Keep the first requirement focused on provenance and auditability, not full vulnerability management. The immediate problem is knowing what third-party code is present in the repo, where it came from, and what version and license it carries.

This requirement is intentionally broader than browser JavaScript. If TAP defines the contract only for `js/lib/`, the same problem will reappear for vendored CSS, copied Python helpers, or other embedded third-party assets.

Keep the manifest intentionally small and hand-maintainable. It should be realistic for contributors to update when vendoring one library, while still being strict enough for future validation tooling.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-thirdparty-manifest.sec-1 | Machine-Readable Manifest Required | Proposed | Third-party components shipped in a TAP runtime image must be represented in a machine-readable manifest, regardless of whether they are vendored in source or downloaded at build time. | |
| req-grid-thirdparty-manifest.sec-2 | Canonical Location And Format | Proposed | Each app or plugin that ships third-party components keeps a `third_party_manifest.toml` file at its own root and uses TOML as the authoring format. | |
| req-grid-thirdparty-manifest.sec-3 | Minimum Provenance Fields | Proposed | Manifest entries record name, version, repository-relative files (empty for build-time-downloaded), upstream source, license, and integrity data. | |
| req-grid-thirdparty-manifest.sec-4 | Fixed Component Entry Shape | Proposed | Each component is represented by one `[[component]]` TOML entry using the required canonical keys for the appropriate delivery mode. | |
| req-grid-thirdparty-manifest.sec-5 | Temporary Unknown Version Escape Hatch | Proposed | Legacy vendored artifacts may use `version = "unknown"` only when a concrete upstream version cannot currently be determined. | |
| req-grid-thirdparty-manifest.sec-6 | Platform-Level Contract | Proposed | Higher-level TAP subsystems that ship third-party components adhere to this grid-level requirement instead of inventing incompatible local rules. | |
| req-grid-thirdparty-manifest.sec-7 | Not Limited To JavaScript | Proposed | The requirement applies to all third-party components shipped in TAP runtime images, not only browser libraries. | |
| req-grid-thirdparty-manifest.sec-8 | SPDX Or CycloneDX Compatible Future | Proposed | TAP may later generate SPDX or CycloneDX artifacts from the canonical manifest without changing the core requirement. | |
| req-grid-thirdparty-manifest.sec-9 | Build-Time-Downloaded Components Recorded | Proposed | Components downloaded by the build process (not committed to source) MUST still appear in the manifest with `files = []`, per-platform `checksum_sha256_<os>_<arch>` keys for each supported variant, and the same name/version/source_url/license fields as source-vendored entries. | |
| req-grid-thirdparty-manifest.sec-10 | Build-Time Integrity Verification | Proposed | The build step that installs a build-time-downloaded component MUST compute the SHA-256 of the downloaded artifact and compare against the manifest-pinned `checksum_sha256_<os>_<arch>` for the platform it is installing, aborting the build on mismatch. | The manifest is the single source of truth for the expected hash; build scripts read from it rather than carrying duplicate hardcoded values. |

#### Future
- Add tooling to validate that vendored files and manifest entries stay in sync.
- Consider SBOM export generation in SPDX and/or CycloneDX format.
- Consider attaching vulnerability scanning and license-policy enforcement to manifest entries.

---

### Static Svg Icon Security
----
RID: `req-grid-icon-static-svg.sec`
Status: `Proposed`
Tags: `Security`

Shipped TAP SVG icons are safer than arbitrary user-supplied SVG content, but they still require a clear security contract because SVG is an XML-based format that can carry active or unsafe constructs. Static SVG icons must be constrained to trusted app/plugin assets and rendered through a narrow image-oriented path.

#### Status Details
New cross-cutting security requirement proposed to support the grid icon specification while keeping the threat model explicit.

#### Implementation
- This requirement applies to shipped static SVG icons owned by TAP apps and plugins.
- Static SVG icons must resolve only from validated app/plugin static icon directories defined by the icon specification.
- Static SVG icons must not be loaded from remote URLs.
- V1 static SVG icons should be rendered as image assets rather than inline executable markup.
- Static icon consumers must not require arbitrary raw SVG markup injection to render an icon.
- Validation must reject icon path traversal outside the owning app/plugin icon directory.

This requirement exists because SVG can carry:
- script elements
- event handler attributes
- embedded foreign content
- external references
- unexpectedly expensive rendering payloads

Keeping shipped icons as trusted static assets referenced through constrained image-style rendering significantly narrows the risk surface.

#### Development
This requirement does not claim that every shipped SVG has been sanitized. Its purpose is to constrain lookup, source, and rendering behavior so TAP does not accidentally widen the SVG attack surface by treating icons as arbitrary markup.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-icon-static-svg.sec-1 | Trusted Static Source Only | Proposed | Shipped SVG icons resolve only from validated app/plugin static icon directories. | |
| req-grid-icon-static-svg.sec-2 | No Remote Icon Sources | Proposed | Static SVG icon resolution rejects remote URLs and other non-local sources. | |
| req-grid-icon-static-svg.sec-3 | Constrained Rendering Path | Proposed | V1 static SVG icons are rendered as image assets rather than inline arbitrary SVG markup. | |
| req-grid-icon-static-svg.sec-4 | Path Traversal Rejected | Proposed | Icon path validation rejects traversal outside the owning app/plugin icon directory. | |

#### Future
If TAP later allows richer SVG rendering modes, define separate hardening rules for those modes rather than silently broadening this requirement.

---

### Uploaded Svg Icon Security
----
RID: `req-grid-icon-upload-svg.sec`
Status: `Backlog`
Tags: `Security`

User-uploaded SVG icons are a distinct security surface and require stricter controls than shipped static app/plugin icons. Even if early rendering uses only image-style embedding, TAP should not accept arbitrary uploaded SVGs without a dedicated sanitization and publication contract.

#### Status Details
Backlog security requirement created now so future user-uploaded icon support does not silently inherit the looser trust assumptions used for shipped static icons.

#### Implementation
Future work must define:
- sanitization of uploaded SVG content before storage or publication
- stripping or rejecting active content such as scripts, event handlers, `foreignObject`, unsafe CSS, and external references
- behavior when sanitization fails
- storage and serving rules for uploaded SVGs
- approved rendering modes for uploaded SVGs
- file size and complexity limits to reduce denial-of-service or rendering abuse risks

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-icon-upload-svg.sec-1 | Uploaded Svg Security Requirement Exists | Backlog | TAP tracks a dedicated security requirement for user-uploaded SVG icons. | |
| req-grid-icon-upload-svg.sec-2 | Sanitization Required Before Publication | Backlog | Future uploaded SVG support must sanitize or reject unsafe SVG content before publication. | |
| req-grid-icon-upload-svg.sec-3 | External References Controlled | Backlog | Future uploaded SVG support must strip or reject remote references and other unsafe linked resources. | |
| req-grid-icon-upload-svg.sec-4 | Rendering Contract Explicit | Backlog | Future uploaded SVG support must define and constrain allowed rendering modes explicitly. | |

#### Future
Define the upload pipeline, sanitization toolchain, and storage/publication model once user-uploaded icons become an active product feature.

---

### Domain Writes Must Use Batch Context
----
RID: `req-grid-flip-write-batch.sec`
Status: `Backlog`
Tags: `Security`, `FLIP`

All mutations to domain objects (BaseModel subclasses) must occur within an active batch context so that every change is attributable to a known operational unit with actor, source, and timing metadata.

#### Status Details
Partially enforced: FLIP-enabled models already raise `NoBatchContextError` if saved without a batch context. The remaining gap is that models without FLIP enabled can still be saved without a batch, bypassing provenance entirely.

#### Implementation
The full enforcement requires:

1. A `pre_save` hook (signal or ORM override) that checks for an active batch context before any `BaseModel` save.
2. An explicit opt-out mechanism for legitimate batch-free writes such as migrations, fixtures, and one-time setup commands.
3. Audit tooling to detect and flag writes that bypass the batch contract.

#### Development
A codebase audit is needed to identify all current write paths that operate outside batch context and either wrap them in `batch_context()` or formally exempt them. Until full enforcement is in place, FLIP-enabled models provide the strongest guarantee.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-flip-write-batch.sec-1 | FLIP Models Enforce Batch | Backlog | FLIP-enabled models raise NoBatchContextError when saved without an active batch context. | Already implemented |
| req-grid-flip-write-batch.sec-2 | All BaseModel Writes Require Batch | Backlog | A pre-save gate prevents any BaseModel subclass from being saved without a batch context, regardless of FLIP enablement. | Requires codebase audit first |
| req-grid-flip-write-batch.sec-3 | Exemption Mechanism Exists | Backlog | Legitimate batch-free writes (migrations, fixtures, setup) have an explicit, auditable opt-out rather than silently bypassing the gate. | |
| req-grid-flip-write-batch.sec-4 | Codebase Audit Complete | Backlog | All existing write paths have been reviewed and either wrapped in batch_context() or formally exempted. | |

#### Future
Once the batch gate is in place, TAP may add monitoring or alerting for writes that use the exemption path in production.

---

### Database Permission Errors Emit A Flaw
----
RID: `req-grid-db-permission-flaw.sec`
Status: `Implemented`
Tags: `Security`

A PostgreSQL "permission denied" (SQLSTATE `42501`, `insufficient_privilege`) reaching the
application is a should-never-happen, security-relevant event: it means code tried to touch
a table or column its database role is not granted — the signature of a guard that leaked,
a misconfiguration, or a probe. This requirement makes every such rejection **loud**,
across every database connection, at a single chokepoint — not only on the read-only search
connection.

#### Status Details
This generalizes the existing, narrower detection guard. `req-grid-search-readonly.sec-6`
already turns a *write* rejection on the `search_readonly` connection (SQLSTATE `25006`)
into a `security` Flaw. That guard is deliberately scoped, because a write on the `default`
connection is legitimate. A *permission-denied read/write* (`42501`) is different: it is
anomalous on **any** connection, and it becomes a load-bearing signal as TAP moves toward
least-privilege roles — first the search read-only role (`req-grid-search-readonly-role.sec`),
and later a non-god-mode application role. Rather than wire a guard per role as those land,
TAP places one broad guard now.

#### Implementation

- A `connection.execute_wrapper` is installed on **every** database connection/alias (wired
  unconditionally on `connection_created`, generalizing `tap_grid/search_readonly_guard.py`).
  On a statement that fails with SQLSTATE `42501`, it emits a `security` Flaw — carrying the
  offending table/statement head, the connection alias, and the caller/actor context — then
  re-raises the original error unchanged. The DB's denial stands; it is now also detectable.
- The `25006` write-block guard stays `search_readonly`-scoped (a write on `default` is
  legitimate). The `42501` guard is universal (a permission-denied is anomalous everywhere).
  The two are distinct SQLSTATEs with distinct scopes.
- **Highest-value case:** a `42501` on the `search_readonly` role means an in-code Gryphon
  guard (`req-grid-traversal-exec-searchable.sec` / `req-grid-traversal-lang-relation-guard.sec`)
  leaked and the database caught it — the tripwire that the primary guard has a gap.
- **Escalation tip — when this Flaw fires in practice, it may be time to build the deferred
  execute-time table-scope guard** (`req-grid-traversal-exec-table-guard.sec`, `Proposed`).
  That guard is deferred precisely because the layers around it close the exploit paths and
  this Flaw makes the DB's catch loud; recurring `42501`s on the search connection mean the
  database has become the *first* line of defense instead of the last — the signal that
  pre-execution blocking with precise in-app attribution (actor, query, table, *before* the
  statement runs) is now worth its build cost. Treat repeated occurrences as the demand this
  deferral was waiting for.
- **New-role rule (single-chokepoint invariant).** Any new database role or connection alias
  MUST route through this guard; a role/alias that deliberately bypasses it names why per
  `req-sec-honest-risk`. This preserves the "one chokepoint" guarantee so a future god-mode
  side-channel cannot dodge detection.
- **Honest caveat** (`req-sec-honest-risk`). This covers only access through Django's
  connection layer — all app code, tasks, commands, migrations, raw cursors,
  `.count()/.exists()`. Access that bypasses Django entirely (a direct `psycopg` connection,
  `psql`, external tooling) is out of scope for this app-level guard; database-side audit
  (`pgaudit` / PostgreSQL logging) is the backstop there, deferred.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-db-permission-flaw.sec-1 | 42501 Emits A Security Flaw | Implemented | A statement failing with SQLSTATE `42501` on any Django connection emits a `security` Flaw before the error propagates. | |
| req-grid-db-permission-flaw.sec-2 | Every Connection Covered | Implemented | The guard is installed on every alias via `connection_created`, not scoped to one connection — so a new least-privilege role is covered without new wiring. | Single chokepoint. |
| req-grid-db-permission-flaw.sec-3 | Original Error Preserved | Implemented | The guard re-raises the original database error unchanged; it only adds detection, it does not alter control flow or the DB's denial. | |
| req-grid-db-permission-flaw.sec-4 | Distinct From Write-Block Guard | Implemented | The `42501` guard is separate from and broader than the `search_readonly` `25006` write-block guard (`req-grid-search-readonly.sec-6`); the two cover different SQLSTATEs and scopes. | |
| req-grid-db-permission-flaw.sec-5 | New Roles Route Through The Guard | Implemented | Any new DB role/alias routes through this guard, or names the exception per `req-sec-honest-risk`; no privileged side-channel dodges detection. | Single-chokepoint invariant. |

#### Future
Database-side audit (`pgaudit` / PG logging) to cover access that bypasses the Django
connection layer entirely; correlate DB-side `42501` with the app-side Flaw.

---

### Cluster-Global Role Provisioning Is Concurrency-Safe
----
RID: `req-grid-db-role-concurrency.sec`
Status: `Implemented`

As TAP grows subdivided, purpose-specific least-privilege database roles (the read-only search
role `tap_gryphon_ro` today; per-surface or per-tenant roles anticipated), their provisioning
must account for a PostgreSQL fact that is easy to forget: **roles are CLUSTER-GLOBAL.** A
PostgreSQL "cluster" is one server instance hosting many databases; roles, tablespaces, and
databases live in shared catalogs (`pg_authid`, …) common to every database in that server —
unlike tables/schemas, which are per-database.

Any code that `CREATE`/`ALTER`/`GRANT`/`REVOKE`s a cluster-global object — **especially in a
boot or reconciliation path that runs once per instance/worker** — can therefore be executed
**concurrently against the same catalog tuple** by:

- **parallel test workers** — pytest-xdist gives each worker its own *database* but they share
  one *cluster*, so N workers each running boot all reconcile the same role; and
- **concurrent application-instance boots** against a shared cluster — hot-swapping a web
  container, blue/green, or any multi-instance-shared-database topology.

PostgreSQL rejects two transactions updating the same catalog tuple at once with
`tuple concurrently updated` (a benign, self-clearing `InternalError`). Provisioners of
cluster-global objects **must be concurrency-safe**: reconcile inside a savepoint
(`transaction.atomic`, so a retry cannot poison the caller's surrounding transaction) and
**retry** on that error with a small bounded backoff. A PostgreSQL **advisory lock is not a
substitute** — advisory locks are scoped *per database*, so they cannot serialize a
cluster-global mutation across the different databases the concurrent callers connect to;
retry is the correct tool. `tap_grid/search_role.py::provision_search_role` is the reference
implementation.

Named risk deliberately left open (`req-sec-honest-risk`): the retry is **bounded** (a small
attempt cap); pathological *sustained* contention would exhaust it and re-raise the original
error — fail-loud by design, never a silent give-up.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-db-role-concurrency.sec-1 | Cluster-Global Provisioners Retry | Implemented | Every provisioner that mutates a cluster-global object (role/database/tablespace) retries on `tuple concurrently updated`. | `provision_search_role` is the reference. |
| req-grid-db-role-concurrency.sec-2 | Savepoint Isolates The Caller | Implemented | Provisioning reconciles inside `transaction.atomic`, so a retry rolls back only its own work — not the caller's surrounding transaction (e.g. a test). | |
| req-grid-db-role-concurrency.sec-3 | Retry, Not Advisory Locks | Implemented | Serialization uses bounded retry, NOT a per-database advisory lock (which cannot serialize a cluster-global mutation across databases). | The load-bearing gotcha. |
| req-grid-db-role-concurrency.sec-4 | New Cluster-Global Roles Follow The Pattern | Proposed | Any newly added cluster-global DB-role/object provisioner adopts the savepoint+retry pattern (or names the exception per `req-sec-honest-risk`). Consider extracting a shared helper once a second site exists. | Forward-proofs subdivided per-purpose roles. |
| req-grid-db-role-concurrency.sec-5 | Bounded And Fail-Loud | Implemented | The retry is bounded; exhaustion re-raises the original error rather than silently giving up. | |

#### Future
Extract the savepoint+retry into a reusable helper (context manager / decorator) when a second
cluster-global provisioner is built — today `provision_search_role` is the sole site, so the
pattern lives inline with a comment pointing here (YAGNI until the second caller).

---

### Grid Table Classification Is Declared Once And Derived Everywhere
----
RID: `req-grid-table-classification.sec`
Status: `Verified`
Tags: `Security`

Two independent security layers each need the answer to one question — **"which database
tables hold TAP-managed grid data?"** — and each previously computed it on its own: the ORM
read backstop (`req-tap-auth-orm-read-backstop`, `tap_grid/read_guard.py`) filtered
`apps.get_models()` and hand-typed `tap_entity_type`; the least-privilege search-role grant
(`req-grid-search-readonly-role.sec`, `tap_grid/search_role.py`) walked the type registry and
hand-listed a `_SPINE_TABLES` tuple. Independent derivations of the same fact drift, and drift
here is a security defect in one of two directions: a table the DB grant covers but the guard
misses is **readable-at-SQL-but-unguarded** (leak); a table the guard covers but the grant
misses is a **spurious 42501 denial** (breakage). The 2026-08-11 derive-the-same-fact-twice
audit ranked this its #1 finding.

**Design (prior-art-grounded).** Classification is **declared on the model class and derived
by every consumer** — the pattern Django recommends for custom model metadata (class-level
attributes, since `Meta` rejects unknown options), SQLAlchemy institutionalizes as the
`Table.info` bag that Alembic filters on, and TAP already uses (`ENTITY_TYPE`,
`INTERNAL_ONLY`, the proposed `GRYPHON_SEARCHABLE`):

- **`GRID_TABLE_ROLE`** is a class-level declaration with exactly two values:
  - `"domain"` — declared **once, on `BaseModel` itself**, and inherited by every concrete
    subclass. A plugin author cannot forget to classify a domain model: subclassing IS the
    classification (the structural half; cf. Rails `ApplicationRecord`).
  - `"spine"` — declared **explicitly** on the grid-infrastructure models that are NOT
    BaseModels: `Entity` and `EntityType`. (`Edge` and `Dimension` are BaseModels and arrive
    via inheritance; the old four-name spine tuple over-listed them.)
- **Table names always come from `Meta.db_table` on the classified model** — no consumer or
  helper may re-type a grid table name as a string literal.
- **One derivation module** (`tap_grid/grid_tables.py`) scans loaded models for the
  classification and exposes the consumer sets. Both the read backstop and the search-role
  grant MUST consume it; a future third consumer (the traversal-execution table guard,
  `req-grid-traversal-exec-table-guard.sec`) MUST consume it too.

**Classification is a privilege boundary, so who may declare it is the security question**
(declare-vs-decide, as in the plugin FIPS posture: a component can never exempt itself):

- **A BaseModel can never claim spine.** `BaseModel.__init_subclass__` — the existing
  class-definition-time chokepoint — rejects ANY `GRID_TABLE_ROLE` declaration in a subclass
  body with `ImproperlyConfigured`, including a redundant `"domain"` (domain-ness is
  inherited, not declared; a declarable value invites a later edit). Spine membership drives
  the DB grant and the read guard's one exemption, so a plugin model that could declare
  itself spine would be writing its own security policy.
- **Explicit classification is core-only.** The derivation honors an explicit
  `GRID_TABLE_ROLE` in a class body only on models owned by the `tap_grid` app. Any other
  model declaring it — including a plain non-BaseModel Django model in a plugin, the door
  `__init_subclass__` cannot see — is a **fail-closed error** at derivation time (raise +
  `security` Flaw), never silently honored and never silently skipped. Mirrors the
  type-ownership boot gate's core-vs-plugin discipline.

**The class-vs-table gap (desired vs persisted).** The classification answers "what SHOULD be
covered"; the DB grant executes against "what EXISTS." A classified model class whose table
was never migrated (test-fixture models; the registered-type-without-a-table plugin-loading
flake of 2026-08-11) must not abort provisioning: at provision time the grant set is
reconciled against the tables that actually exist in the database, and a declared-but-absent
table is **skipped with a loud WARNING** naming the table. Not-granting is the fail-safe
direction (unreadable, never over-exposed) — the same reason Alembic filters against
*reflected* DB state rather than trusting the class layer.

**The one deliberate consumer asymmetry, pinned.** `Entity` is granted to the search role
(the executor always reads the spine) but is exempt from the ORM read backstop (its reads are
pervasive below the service boundary and the Entity API carries its own gate — the named open
edge of `req-tap-auth-orm-read-backstop`). This is a per-model policy of the read-guard
consumer, expressed against the model class (never a string), and the resulting relationship
— **grant set == read-guarded set ∪ {Entity's table}** — is pinned by a guard test so an edit
to either consumer that breaks the relationship fails loudly.

Named alternative deliberately deferred (`req-sec-honest-risk`): moving grid tables into a
dedicated PostgreSQL schema would make the grant one statement (`GRANT … ON ALL TABLES IN
SCHEMA` + `ALTER DEFAULT PRIVILEGES` for future tables — the DB-native prior art, cf.
django-tenants). Django's multi-schema friction makes it an expensive edge that waits for
demand; default-privileges WITHOUT a dedicated schema is explicitly rejected (it would
auto-grant future non-grid tables — fail-open).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-table-classification.sec-1 | Classification Declared On The Model | Implemented | Every grid table's classification is a class-level `GRID_TABLE_ROLE` declaration: `"domain"` inherited from `BaseModel`, `"spine"` declared explicitly on the non-BaseModel infrastructure models. Table names come only from `Meta.db_table`. | The marker-attribute prior-art pattern. |
| req-grid-table-classification.sec-2 | One Derivation, Every Consumer | Implemented | The read backstop, the search-role grant, and any future table-scope consumer derive their sets from the single shared module (`tap_grid/grid_tables.py`); none holds its own list or re-types a table name. | Kills the #1 audit finding. |
| req-grid-table-classification.sec-3 | A BaseModel Can Never Claim Spine | Implemented | `BaseModel.__init_subclass__` rejects any `GRID_TABLE_ROLE` declaration in a subclass body (including redundant `"domain"`) with `ImproperlyConfigured` at class-definition time. | Declare-vs-decide; self-exemption closed at the chokepoint. |
| req-grid-table-classification.sec-4 | Explicit Classification Is Core-Only | Implemented | The derivation honors an explicit `GRID_TABLE_ROLE` only on `tap_grid`-owned models; any other declarer (incl. non-BaseModel plugin models) is a fail-closed error + `security` Flaw at derivation time. | Closes the door `__init_subclass__` cannot see. |
| req-grid-table-classification.sec-5 | Consumer Relationship Pinned | Implemented | A guard test pins grant set == read-guarded set ∪ {`Entity`'s table}, and that the spine set is exactly {`Entity`, `EntityType`} — changing either is a deliberate, reviewed spec+test change. | The Entity asymmetry stays visible, never drifts silently. |
| req-grid-table-classification.sec-6 | Grant Reconciles Against Existing Tables | Implemented | Provisioning grants only classified tables that exist in the database; a classified-but-absent table is skipped with a loud WARNING naming it, never an abort and never a silent drop. | Fail-safe direction: not-granted = unreadable. |

#### Future
- The `GRYPHON_SEARCHABLE` opt-in gate (`req-grid-traversal-exec-searchable.sec`), when it
  lands, narrows the *grant* consumer to a searchable subset — it composes with this
  classification (searchable ⊆ domain), it does not replace it.
- A dedicated `grid` PostgreSQL schema (the deferred DB-native alternative above) would let
  `ALTER DEFAULT PRIVILEGES` cover future tables at creation time; revisit on demand.

---

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed |  |
| Approved for Development | Requirement is accepted and ready to be implemented |
| In Development |  |
| Implemented |  |
| Verified |  |
| Refactoring |  |
| Deprecating |  |
| Deprecated | Not part of the current architecture and should not be implemented |

## RID Format

`req-<application>-<specification>-<feature>-<sub-feature>`

## Requirements Format

`RID: `...``
`Status: `...``

| Sub-Sections | (as needed) |
| --- | --- |
| Status Details |  |
| Implementation |  |
| Development |  |
| Acceptance Criteria |  |
| Future |  |
