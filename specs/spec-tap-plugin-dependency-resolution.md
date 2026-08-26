# Plugin Dependency Resolution & Secret Materialization

## Philosophy

Today the boot record's `install.plugins[]` is a hand-authored, explicitly-ordered install list, and every plugin's `pyproject.dependencies` is empty (samsite is the first exception, landed 2026-07-07) — so **the boot record is the de-facto install-closure**, and `uv` is driven one plugin at a time (`uv pip install --editable <path>` / a git URL / `--find-links <wheelhouse>`) with git credentials fed through `GIT_ASKPASS`. That is correct for a curated first-party set on one machine, but it does not carry to three things TAP is moving toward:

- **Self-describing, self-installable plugins** — `uv pip install tap-plugin-samsite` should pull its own closure, not require a boot record to enumerate every transitive dep.
- **Mixed public/private registries with per-registry auth** — a private customer plugin (their samsite, their sigstore) importing a public `aws_core` from our index, each registry with its own credentials.
- **Cloud secret stores** — resolving those credentials from AWS Secrets Manager / Vault when launched in the cloud, without baking cloud SDK code into core.

This spec moves plugin install to **uv-native resolution**. Plugins declare Tier-0 deps; uv resolves the closure against per-package-routed indexes; the boot record **narrows to policy** (which indexes, which credentials, which top-level plugins) plus the seed/collector-fire ordering uv never owned; and the resolved **`uv.lock` becomes the auditable known-good-set** (the BOM the two-mains work leans on). Secrets are materialized just-in-time through `keyring` — uv's only integration path — backed by a first-party `runtime_secrets` shim, and cloud secret stores are surfaced as **plugin-contributed sources** so no cloud SDK enters core until a cloud plugin is installed.

The throughline is TAP's standing discipline: lean on the ecosystem tool (uv) for the hard 80%, keep TAP as the **policy + audit** authority for the 20% that is ours, and lay the security edges — dependency-confusion, credential non-leak, trust-gated registration — while the seam is open ([spec-security-posture.md](spec-security-posture.md) cheap-edge). It is the realization of the Tier-0 half of [spec-tap-plugin-architecture.md](../tap_plugins/specs/spec-tap-plugin-architecture.md) `req-tap-plugin-arch-dependencies`, evolves the from-git install machinery in [spec-tap-boot-bootstrap.md](spec-tap-boot-bootstrap.md), and extends the secret model in [spec-tap-cares-secrets.md](../tap_cares/specs/spec-tap-cares-secrets.md).

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | uv-Resolved Closure | Plugins self-declare deps; uv resolves; the boot record shrinks to policy + ordering. |
| 2. | Mixed Registries | Per-package routing to public/private indexes, each with its own authentication. |
| 3. | Secret Authority Stays TAP | keyring and uv are *consumers*; `runtime_secrets` is the store; cloud sources are plugin-contributed, not core-baked. |
| 4. | Auditable BOM | `uv.lock` is the pinned, verifiable known-good-set; integrity-verified like today's boot record. |
| 5. | Security Edges By Construction | Dependency-confusion, credential non-leak, and trust-gated source registration are designed in, not retrofitted. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-plugin-depres-tier0 | [Tier-0 uv Resolution](#tier-0-uv-resolution) | Proposed | Plugins declare pyproject `dependencies`; uv resolves the closure. samsite is the first (landed) |
| req-tap-plugin-depres-versions | [Real Per-Plugin Versions](#real-per-plugin-versions) | Proposed | Retire the `0.0.0` hatch-vcs fallback; per-plugin tags so version specifiers resolve |
| req-tap-plugin-depres-indexes | [Mixed-Registry Routing](#mixed-registry-routing) | Proposed | `[[tool.uv.index]]` + `[tool.uv.sources]` per-package routing to public/private indexes |
| req-tap-plugin-depres-confusion | [Dependency-Confusion Guardrails](#dependency-confusion-guardrails) | Proposed | `explicit = true` private indexes + `--index-strategy first-index` |
| req-tap-plugin-depres-nobuild | [Wheels-Only Production Install](#wheels-only-production-install) | Proposed | `--only-binary :all:` — install is non-executing; `ready()` is the sole code-execution boundary |
| req-tap-plugin-depres-bootemit | [Boot Record Emits uv Config](#boot-record-emits-uv-config) | Proposed | Boot record carries index list + routing + credential bindings; narrows to policy + order |
| req-tap-plugin-depres-lock | [uv.lock As BOM](#uvlock-as-bom) | Proposed | The resolved lockfile is the pinned, integrity-verified known-good-set |
| req-tap-plugin-depres-keyring | [Keyring-Subprocess Materialization](#keyring-subprocess-materialization) | Proposed | `--keyring-provider subprocess` → a first-party `runtime_secrets`-backed keyring backend in core |
| req-tap-plugin-depres-sources | [Pluggable Secret Sources](#pluggable-secret-sources) | Proposed | `tap.secret_sources` entry-point registry; disk in core, cloud via a slim `aws_secrets_source` distro (Decision A). **Being implemented now**, CI-driven (`req-dev-validation-product-line-lanes`) |
| req-tap-plugin-depres-bootstrap | [Two-Phase Bootstrap Ordering](#two-phase-bootstrap-ordering) | Proposed | Source-provider distros are bootstrap-tier; ambient cloud IAM for the store. First slice **preinstalls** the provider (Decision B); general two-phase engine deferred |
| req-tap-plugin-depres-trust | [Trust Boundary & Gated Registration](#trust-boundary--gated-registration) | Proposed | keyring backend core-only; source registration allow-listed (`{aws_secrets_source}`); a secret resolves only via its named source |
| req-tap-plugin-depres-registry-flaws | [Scoped-Registry FLAW Integration](#scoped-registry-flaw-integration) | Open | Collisions / blocked overwrites in the routing + source registries emit FLAW-tagged, severity-appropriate signals — **deferred to a separate design discussion** |

### Tier-0 uv Resolution
----
RID: `req-tap-plugin-depres-tier0`
Status: `Proposed`

Every plugin declares its cross-plugin and third-party install dependencies in `pyproject.toml` `dependencies` (Tier-0, [spec-tap-plugin-architecture.md](../tap_plugins/specs/spec-tap-plugin-architecture.md) `req-tap-plugin-arch-dependencies-1`). uv resolves the closure; the boot record's `install.plugins[]` then names only the **top-level** plugins an instance wants, and uv pulls their transitive deps. This is distinct from `depends_on` (Tier-1, code-import *registration* order) and the profile's fire-collector order (Tier-2, runtime-data *seed* order) — uv owns **install** only; those two orderings stay in the boot record (see `req-tap-plugin-depres-bootemit`).

**Landed first step:** samsite now declares `tap-plugin-{aws-core,sigstore-core,github-core,roscale}` (2026-07-07). Verified that uv resolves them against the deps-first install order without reaching an index.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-depres-tier0-1 | Plugins declare deps | Proposed | Every plugin's `pyproject.dependencies` lists its cross-plugin install deps; uv resolves the closure. | samsite done; remaining ten to populate. |
| req-tap-plugin-depres-tier0-2 | Boot record names top-level only | Proposed | `install.plugins[]` may name only top-level plugins; uv pulls transitive deps. | The install *list* shrinks; ordering does not move here. |
| req-tap-plugin-depres-tier0-3 | Tiers stay distinct | Proposed | Tier-0 (install, uv) does not absorb Tier-1 (`depends_on`, registration) or Tier-2 (profile, seed). | A data/schema dep is Tier-0; a code-import is Tier-1; a node-instance dep is Tier-2. |

### Real Per-Plugin Versions
----
RID: `req-tap-plugin-depres-versions`
Status: `Proposed`

Every plugin currently reports version `0.0.0` — the hatch-vcs `root = "../.."` fallback, because the monorepo carries no per-plugin git tags (the "MONOREPO-TRANSITION ARTIFACT" markers). Version specifiers (`tap-plugin-aws-core>=0.1`) cannot resolve until each plugin carries its own version. This requirement retires the fallback: per-plugin release tags (already the eviction-release model — `tap-plugin-aws-core` shipped `v0.1.1`) become the version source, so pyproject deps can carry meaningful lower bounds and uv.lock pins exact versions.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-depres-versions-1 | Per-plugin version source | Proposed | Each plugin derives its version from its own tag/metadata, not the repo root fallback. | Pairs with the eviction-release tagging. |
| req-tap-plugin-depres-versions-2 | Specifiers resolve | Proposed | A dep like `tap-plugin-aws-core>=0.1` resolves against the real installed/indexed version. | Unblocks version pinning in uv.lock. |

### Mixed-Registry Routing
----
RID: `req-tap-plugin-depres-indexes`
Status: `Proposed`

An instance may pull plugins from more than one registry — a public TAP index and one or more private (customer) indexes. uv expresses this natively:

- **`[[tool.uv.index]]`** — named indexes (`name`, `url`, and `explicit` / `default` flags).
- **`[tool.uv.sources]`** — routes a specific package to a specific index: `tap-plugin-aws-core = { index = "tap-public" }`, or to git.
- **Per-index auth** — `UV_INDEX_<NAME>_USERNAME` / `_PASSWORD`, or the keyring provider (`req-tap-plugin-depres-keyring`).

This routing config is **deployment-level** — it is *not* baked into a built wheel (`[tool.uv.sources]` is dev metadata stripped at build). A published wheel declares only the abstract name `tap-plugin-aws-core`; *where* it resolves from and *what* auth is used is the consuming instance's decision — which is why it belongs in the boot record (`req-tap-plugin-depres-bootemit`), the per-instance authority.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-depres-indexes-1 | Named indexes | Proposed | Multiple `[[tool.uv.index]]` entries with per-index URL + flags are supported in the resolved config. | |
| req-tap-plugin-depres-indexes-2 | Per-package routing | Proposed | `[tool.uv.sources]` routes each package to its index/git source. | Package → registry → secret. |
| req-tap-plugin-depres-indexes-3 | Routing is deployment-level | Proposed | A plugin wheel never hardcodes its registry; routing lives in the instance's boot-emitted config. | Correct separation of plugin identity from deployment policy. |

### Dependency-Confusion Guardrails
----
RID: `req-tap-plugin-depres-confusion`
Status: `Proposed`

In a mixed public/private world, a private package name (`tap-plugin-acme-sigstore`) must **never** be resolvable from the public index — otherwise an attacker publishing that name to PyPI could shadow the customer's private plugin (the classic dependency-confusion attack). Two uv mechanisms, both required:

- **`explicit = true`** on every private index — it is used *only* for packages that name it in `[tool.uv.sources]`, never searched for public names.
- **`--index-strategy first-index`** (not `unsafe-best-match`) — stop at the first index that has a name rather than hunting across indexes for a "better" version.

Per the [security posture](spec-security-posture.md), these are baked in from the first design, not retrofitted; a review guard should assert every private index is `explicit`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-depres-confusion-1 | Private indexes are explicit | Proposed | Every non-default index carrying private names is `explicit = true`. | Guard-enforced. |
| req-tap-plugin-depres-confusion-2 | First-index strategy | Proposed | Resolution uses `first-index`, never `unsafe-best-match`, across indexes. | |
| req-tap-plugin-depres-confusion-3 | Named risk | Proposed | The dependency-confusion threat is named in the security posture's honest-risk register with these as the mitigation. | |

### Wheels-Only Production Install
----
RID: `req-tap-plugin-depres-nobuild`
Status: `Proposed`

uv executes code at install time **only when it builds from source** — an sdist, a git source, a path, or an `--editable` install invokes the PEP 517 build backend (`hatchling` + `hatch-vcs`, which shells out to `git`) in an isolated env and runs arbitrary Python. Installing a **wheel** is strictly unpack-to-`site-packages` — no execution; uv reads `METADATA` straight from the zip to resolve.

Production / boot plugin resolution therefore runs **`--only-binary :all:`** (wheels only, building forbidden). The payoff is a sharp, small trust boundary: plugin *install* is provably non-executing, and the **sole** code-execution boundary in the whole bootstrap is the explicit, trust-gated `AppConfig.ready()` registration ([spec-tap-boot-bootstrap.md](spec-tap-boot-bootstrap.md)) — not "any build backend of any transitive dep can run arbitrary code." Import time is a separate, TAP-owned boundary and is unaffected.

This is a **named split**, not an accident: dev and CI still install `--editable` / from source (which build, and which `hatch-vcs` *needs* in order to derive versions), a legitimately higher-trust surface. Pairs with `req-tap-plugin-depres-versions` — published wheels carry a real baked-in version, retiring the build-time `hatch-vcs` execution in production. A review guard should assert the production resolve path carries `--only-binary`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-depres-nobuild-1 | Production is wheels-only | Proposed | The boot/production plugin resolve runs `--only-binary :all:`; building from source is forbidden there. | Install is non-executing. |
| req-tap-plugin-depres-nobuild-2 | ready() is the sole exec boundary | Proposed | With wheels-only install, the only code-execution point in bootstrap is the gated `AppConfig.ready()` registration. | Named in the security posture. |
| req-tap-plugin-depres-nobuild-3 | Dev/CI build surface is named | Proposed | Editable/sdist/git installs (which run the build backend) are confined to dev + CI, recorded as an accepted higher-trust surface. | Not an accident. |

### Boot Record Emits uv Config
----
RID: `req-tap-plugin-depres-bootemit`
Status: `Proposed`

The boot record stops being the install *list* and becomes the install *policy*: it declares the index set, the per-package routing, and the credential bindings (`index → secret`), and the boot stage **emits** the corresponding uv config (`[[tool.uv.index]]` + `[tool.uv.sources]` + materialized auth) for the instance, then invokes a single `uv sync` / resolve rather than N per-plugin installs. What stays in the boot record and does **not** move to uv: the Tier-1 registration order (`depends_on`) and the Tier-2 collector-fire / seed order — uv never owned those. The credential-binding half already exists for git (`GIT_ASKPASS` + the `github-plugins-ro` secret); this generalizes it to indexes.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-depres-bootemit-1 | Boot emits uv config | Proposed | The boot stage generates the instance's `[[tool.uv.index]]` + `[tool.uv.sources]` + auth from the boot record's policy. | |
| req-tap-plugin-depres-bootemit-2 | Single resolve | Proposed | Install becomes one uv resolve/sync over the top-level set, not per-plugin explicit installs. | Two-phase where bootstrap sources are needed (`req-tap-plugin-depres-bootstrap`). |
| req-tap-plugin-depres-bootemit-3 | Order stays in the record | Proposed | Registration (Tier-1) and seed/fire (Tier-2) ordering remain boot-record concerns, not uv's. | |

### uv.lock As BOM
----
RID: `req-tap-plugin-depres-lock`
Status: `Proposed`

The audit surface moves from the hand-authored install list to the **resolved `uv.lock`** — the pinned, exact-version, hashed closure. It is the known-good-set the all-plugins CI lane verifies and the boot pointer integrity-checks (the role the `[[boot.records]]` sha256 plays today, [spec-tap-boot-bootstrap.md](spec-tap-boot-bootstrap.md)). This preserves — arguably strengthens — the auditability the two-mains / BOM work relies on: a lockfile is more precise and machine-verifiable than a prose install list.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-depres-lock-1 | Lock is the BOM | Proposed | `uv.lock` (pinned + hashed) is the recorded known-good-set for an instance. | Replaces/augments the install list as the audit artifact. |
| req-tap-plugin-depres-lock-2 | Integrity-verified | Proposed | The lockfile is integrity-checked on boot, as the boot record is today. | Reuses the boot-pointer verification model. |
| req-tap-plugin-depres-lock-3 | CI verifies the set | Proposed | The all-plugins CI lane resolves/verifies against the lock. | Cross-ref `req-dev-validation-all-plugins-lane`. |

### Keyring-Subprocess Materialization
----
RID: `req-tap-plugin-depres-keyring`
Status: `Proposed`

uv (0.11) integrates with credentials only via `--keyring-provider subprocess`, which shells out to the `keyring` CLI. TAP therefore ships **one first-party keyring backend, in core**, that translates uv's `keyring get <index-url> <username>` into a `runtime_secrets` resolution. Consequences:

- **uv is a credential *consumer*, never a store.** Secrets resolve just-in-time through the keyring subprocess and never transit environment variables (avoiding the env-leak surface the `secret-leak` guard exists for). Env-var materialization (`UV_INDEX_<NAME>_PASSWORD`) is the documented fallback for simple cases only.
- **The routing key is the index *URL*.** uv passes the URL as the keyring `service`; the backend maps `(url, username) → secret`, so the boot-record credential binding must be reconstructable from the URL (`index-url → secret`), not only the index name.
- **`keyring` is a trusted dependency.** It is the credential layer under pip/twine/poetry/uv, maintained by the setuptools maintainer (jaraco); adding it is near-zero marginal supply-chain risk.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-depres-keyring-1 | Core keyring backend | Proposed | A first-party `keyring` backend in core resolves index creds via `runtime_secrets`; installed in the boot env. | Never a plugin — supply-chain boundary. |
| req-tap-plugin-depres-keyring-2 | No env transit | Proposed | Credentials resolve just-in-time via the keyring subprocess; env-var materialization is a documented fallback only. | Honors the `secret-leak` guard. |
| req-tap-plugin-depres-keyring-3 | URL-keyed binding | Proposed | The credential binding resolves from the index URL uv passes as the keyring service. | Design the boot binding as `index-url → secret`. |

### Pluggable Secret Sources
----
RID: `req-tap-plugin-depres-sources`
Status: `Proposed`

`runtime_secrets` is disk-only today. This requirement adds a **source-provider seam** so a secret's config names its *source*, and the resolver dispatches to a registered provider — **disk in core, cloud stores contributed by plugins**. Providers are discovered via a new `tap.secret_sources` entry-point group, read from distribution metadata the same **settings-free at preboot** way `discover_entry_points()` reads `tap.plugins` — so a source is available at install/resolve time, before the Django app registry boots.

```toml
# in aws_core's pyproject — present only if aws_core is installed
[project.entry-points."tap.secret_sources"]
aws_secrets_manager = "tap_plugin.aws_core.secret_sources:AwsSecretsManagerSource"
```

No cloud SDK enters core: boto3 rides with `aws_core` (which already carries it), and the AWS Secrets Manager source reuses aws_core's existing AWS credential machinery. A secret whose config says `source = "aws_secrets_manager"` fails loud if aws_core is not installed — correct, not silent. The source-provider registry is a `ScopedRegistry` mirroring `secret_registry`.

**The seam is deliberately general — not a keyring/uv special case.** We build it to serve the keyring shim (`req-tap-plugin-depres-keyring`), but because *every* TAP secret consumer already resolves through `runtime_secrets` (collectors, `oidc_client`, the `github-plugins-ro` git credential, boot), the source seam generalizes to all of them for free. The consequences, recorded here as intended design:

- **`~/tap-secrets` is demoted from "the store" to "the disk source"** — the built-in, always-present-in-core, default backend. It is one source among several, not a privileged one.
- **The manifest stays TAP-owned; only the value moves.** A secret's envelope/metadata — kind, description, consumer, provenance, JSON schema, and the `source` routing itself — remains in TAP (and becomes *more* important: it is the routing table). The external store holds only the opaque value. This preserves the descriptions/legibility discipline ([json-structures-require-descriptions]); a cloud secret blob is illegible, TAP's manifest is what stays queryable by security and AI.
- **Migration is per-secret, not big-bang.** Each secret names its own source, so an instance can move one secret to a cloud store and leave the rest on disk.
- **The disk + ambient floor is irreducible.** The disk source is always core-resident, and the store's own auth is ambient cloud IAM (`req-tap-plugin-depres-bootstrap`), never a TAP secret — so bootstrap-critical secrets can never be trapped behind a plugin-contributed source. This floor is the trust anchor, not a limitation.
- **Read-only in v0.** `runtime_secrets` *resolves* values from a source; it does not create or rotate them. Secret creation/rotation stays out-of-band (the store directly, or IaC). A write path is explicitly out of scope for v0.

#### Design Decisions (2026-07-08)

Settled while pulling this seam forward to serve the AWS CodeBuild CI lanes (`spec-dev-validation.md` `req-dev-validation-product-line-lanes`), which need the `github-plugins-ro` git credential resolved from AWS Secrets Manager in the cloud and from disk locally — the exact "works local and cloud" case this seam exists for.

- **Routing lives in the envelope `metadata`, not a new required field.** A manifest names its source with `metadata.source` (absent ⇒ the built-in disk source, today's behavior unchanged) and locates the value with `metadata.source_ref` (provider-specific, e.g. `{"secret_id": "tap-ci/github-plugins-ro"}`). The canonical `data` object stays required: for a disk secret it holds the value inline; for a sourced secret it is `{}` and the provider *returns* the effective `data`. The manifest is **always disk-resident** — only the value moves — so discovery, the size/leak guards, and `scope`/`key`/`kind`/`description` legibility are unchanged.
- **Decision A — a slim, dedicated source-provider distribution, NOT `aws_core`.** The provider ships as a minimal package (working name `aws_secrets_source`: boto3 + one `AwsSecretsManagerSource` class + the `tap.secret_sources` entry point) rather than dragging all of `aws_core` into every cloud profile. Rationale: source providers must be **bootstrap-tier** (installable with no secret, `req-tap-plugin-depres-bootstrap-1`), and the fine-grained-capability discipline favors a purpose-built public distribution over a heavy dependency. It contributes only a secret source — it is *not* a grid plugin (no `tap.plugins` entry, no BaseModel, no collectors). Supersedes this section's earlier "aws_core ships it" framing.
- **The provider protocol is minimal:** `fetch(ref: Mapping, *, envelope) -> Mapping` returns the effective `data`. The registry is a settings-free `ScopedRegistry` populated from `tap.secret_sources` at preboot (mirroring `discover_entry_points()` for `tap.plugins`), so a source is available at install/resolve time before the Django app registry boots.

#### Worked Example — `github-plugins-ro` on CodeBuild vs. locally

- **Locally:** `~/tap-secrets/.../github-plugins-ro.secret.json` has the PAT inline in `data` and no `metadata.source` ⇒ disk source, unchanged.
- **On CodeBuild:** the lane materializes a **routing manifest** (no secret material — safe to generate in the workflow) with `metadata.source = "aws_secrets_manager"` and `metadata.source_ref = {"secret_id": "tap-ci/github-plugins-ro"}`. At boot, `tap/plugin_source_auth.py` resolves the credential through `runtime_secrets` exactly as today; the seam dispatches to the `AwsSecretsManagerSource`, which calls `GetSecretValue` using the **CodeBuild role's ambient IAM** (`req-tap-plugin-depres-bootstrap-3` — store auth is ambient, never a TAP secret, so no resolution recursion). The value is fed to `GIT_ASKPASS` and the private plugins install. The Terraform (`ci/terraform/codebuild-runners/`) creates the Secrets Manager secret (empty shell; the PAT is populated out-of-band, never in git) and grants the lane role `secretsmanager:GetSecretValue` on that one ARN.
- **Cross-scope note:** `github-plugins-ro` lives in the install-system `tap_plugins.source` scope, whose resolution trips the detective `CONCERN` tripwire (`spec-tap-cares-secrets.md` `req-tap-cares-secrets-cross-scope-concern`). The install system resolving its own scope is the legitimate case; the seam does not change who resolves it, only where the value comes from.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-depres-sources-1 | Source seam | Proposed | A secret declares its source via `metadata.source`; `runtime_secrets` dispatches to a registered provider (absent ⇒ disk). | Disk is the built-in; manifest stays disk-resident. |
| req-tap-plugin-depres-sources-2 | Entry-point discovery | Proposed | Sources are discovered from `tap.secret_sources` distribution metadata, settings-free at preboot. | Mirrors `discover_entry_points()`. |
| req-tap-plugin-depres-sources-3 | Cloud sources are plugin-contributed | Proposed | A slim, dedicated `aws_secrets_source` distribution ships the AWS Secrets Manager source (boto3); core carries no cloud SDK. | **Decision A** — not `aws_core`; bootstrap-tier, source-only (no `tap.plugins`). |
| req-tap-plugin-depres-sources-4 | Missing source fails loud | Proposed | A secret naming an unregistered source raises, never silently degrades. | |
| req-tap-plugin-depres-sources-5 | Seam is general | Proposed | The source seam serves all `runtime_secrets` consumers, not just keyring; `~/tap-secrets` becomes the disk source; the manifest stays TAP-owned while only the value moves; migration is per-secret. | Deliberately general by design. |
| req-tap-plugin-depres-sources-6 | Read-only in v0 | Proposed | `runtime_secrets` resolves values from a source; it does not create or rotate them. A write path is out of scope for v0. | Rotation stays in the store / IaC. |
| req-tap-plugin-depres-sources-7 | Routing in envelope metadata | Proposed | Routing is `metadata.source` + `metadata.source_ref`; `data` stays required (inline for disk, `{}` + provider-returned for a source). | No change to required fields or the guards. |

### Two-Phase Bootstrap Ordering
----
RID: `req-tap-plugin-depres-bootstrap`
Status: `Proposed`

A secret-source provider that lives in a plugin creates an ordering constraint: resolving a private plugin's index credential from AWS Secrets Manager needs aws_core's source *loaded*, but source providers come *from* installed plugins. Resolution: **secret-source-provider plugins are bootstrap-tier** — installable without a *plugin-supplied* secret. Install proceeds in two phases:

1. **Bootstrap** — public / no-secret plugins, including the source-provider plugins (e.g. a public `aws_core`), install and register their sources.
2. **Gated** — private plugins whose index credentials the now-registered sources can resolve.

The store *itself* authenticates via **ambient cloud IAM** (an instance role), never a TAP secret — so there is no resolution recursion.

**Decision B (2026-07-08) — first slice preinstalls the source provider; the general two-phase-install engine is deferred.** The `aws_secrets_source` distribution is public and secret-free, so for the CI lanes it is simply **baked into the CodeBuild image** (or installed in a pre-boot step) — present and registered before boot resolves the git credential. This satisfies bootstrap-tier (`-1`) and ambient auth (`-3`) on the concrete case *now* without building the general bootstrap-vs-gated install ordering (`-2`), which stays `Proposed` until a deployment needs source-provider install ordering it cannot preinstall. Get the concrete case working, generalize when a second case demands it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-depres-bootstrap-1 | Source providers are bootstrap-tier | Proposed | A distribution contributing a secret source installs without a plugin-supplied secret. | `aws_secrets_source` is public/secret-free — the exemplar. |
| req-tap-plugin-depres-bootstrap-2 | Two-phase install | Proposed | Bootstrap distributions (+ their sources) resolve before secret-gated private plugins. | **Deferred** (Decision B): CI preinstalls the provider instead; general engine awaits a second case. |
| req-tap-plugin-depres-bootstrap-3 | Ambient store auth | Proposed | The secret store authenticates via ambient cloud IAM, not a TAP secret — no recursion. | CodeBuild role's `GetSecretValue`. |

### Trust Boundary & Gated Registration
----
RID: `req-tap-plugin-depres-trust`
Status: `Proposed`

Distributing secret sources to plugins opens a surface: a malicious plugin could register a source that intercepts credential resolution. The boundary:

- **The keyring backend is core-only** — a plugin is never the uv-facing credential shim.
- **Source registration is trust-gated** — an explicit first-party **allow-list of distributions** permitted to register a `tap.secret_sources` provider (initially `{aws_secrets_source}`), enforced at registration time in core. Not "any installed distribution registers a credential source": an unlisted distribution's entry point is ignored (and the attempt is a security-relevant signal, see `req-tap-plugin-depres-registry-flaws`). The disk source is core-resident and always available, never gated.
- **A secret resolves only via the source named in its own config** — a registered source cannot claim secrets bound to another source, so even a permitted source cannot hijack resolution. The resolver passes a source only its own `source_ref`, never the manifest of a secret routed elsewhere.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-depres-trust-1 | Core-only backend | Proposed | The keyring backend ships in core; no plugin can supply it. | |
| req-tap-plugin-depres-trust-2 | Gated source registration | Proposed | Only trusted (first-party / allow-listed) plugins may register a secret source. | |
| req-tap-plugin-depres-trust-3 | No cross-source hijack | Proposed | A secret dispatches only to its named source; a source cannot claim others' secrets. | |

### Scoped-Registry FLAW Integration
----
RID: `req-tap-plugin-depres-registry-flaws`
Status: `Backlog`

**Deferred to a separate design discussion** (George, 2026-07-07). The registries this spec introduces — the secret-source provider registry and the index/routing registry — are `ScopedRegistry` instances, and in a *credential-routing* context a silent collision or a blocked overwrite is a security event, not a benign no-op: two providers claiming `aws_secrets_manager`, or an attempt to overwrite an index→secret binding, must be logged **loudly and proudly** with the appropriate FLAW category, tags, and severity — never swallowed.

The open design question is *how*: `ScopedRegistry.register()` today (`tap.registry`) enforces the token grammar and rejects malformed input, but collision/overwrite handling and its coupling to the FLAW signal (`tap.logging` / `tap.logging_signals`) is not parameterized. Likely shape: pass a **FLAW category** (and severity) into the registry so `register()` emits the correctly-tagged FLAW on a blocked overwrite/collision — but that touches the shared registry used by collectors, secrets, panels, edges, etc., so it needs its own pass rather than being decided here. This requirement is a **forward reference**; its acceptance criteria are set in that discussion.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-depres-registry-flaws-1 | Loud on collision/overwrite | Open | Collisions and blocked overwrites in the routing + source registries emit a FLAW with category/tags/severity. | Design in the separate scoped-registry-FLAW discussion. |
| req-tap-plugin-depres-registry-flaws-2 | Registry passes FLAW category | Open | `ScopedRegistry` is (likely) extended to carry a FLAW category so register-time violations are tagged correctly across all its consumers. | Cross-cutting; affects collector/secret/panel/edge registries. |

## Plan (phasing)

Ordered so each phase is independently landable and the security edges precede the exposure they guard:

1. **Tier-0 population + versions** (`-tier0`, `-versions`) — populate every plugin's pyproject deps (samsite done); cut per-plugin version tags; retire the `0.0.0` fallback. Prereq for everything.
2. **Secret source seam** (`-sources`, `-trust`) — add the `runtime_secrets` source-provider registry + `tap.secret_sources` discovery + the disk source in core; trust-gated registration. No cloud code yet. (Depends on the FLAW discussion for the registry wiring — see below.)
3. **Keyring backend** (`-keyring`) — the core `keyring` backend over `runtime_secrets`; env-var fallback documented. Now uv can pull authenticated indexes.
4. **Mixed registries + confusion guardrails** (`-indexes`, `-confusion`) — `[[tool.uv.index]]` + `[tool.uv.sources]` routing with `explicit` private indexes + `first-index`. Guardrails land *with* the first private index, never after.
5. **Boot emits uv config + lock BOM** (`-bootemit`, `-lock`, `-nobuild`) — the boot record generates uv config and drives a single wheels-only (`--only-binary`) resolve; `uv.lock` becomes the verified BOM; two-phase bootstrap ordering (`-bootstrap`).
6. **First cloud source** (`-sources` cont.) — aws_core's AWS Secrets Manager source, as the proof that cloud stores are a plugin bolt-on.

The **scoped-registry FLAW integration** (`-registry-flaws`) is a cross-cutting prerequisite for phase 2's registry wiring and is designed in its own discussion before that phase lands.

## Worked example — a private customer plugin over a public dependency

Acme runs a private TAP instance: **their** samsite and **their** sigstore plugin live in Acme's private index; they import **our** public `aws_core`.

```toml
# emitted by the boot record for Acme's instance (deployment-level, not in any wheel)
[[tool.uv.index]]
name = "tap-public"
url  = "https://index.tap.example/simple"

[[tool.uv.index]]
name = "acme"
url  = "https://pkgs.acme.example/simple"
explicit = true                         # never searched for public names (confusion guard)

[tool.uv.sources]
tap-plugin-aws-core      = { index = "tap-public" }   # our public plugin, no secret
tap-plugin-acme-sigstore = { index = "acme" }         # their private plugin
tap-plugin-samsite       = { index = "acme" }         # their private plugin
```

- **Install phase 1 (bootstrap):** `tap-plugin-aws-core` pulls from the public index with no credential; if it also carries the AWS Secrets Manager source, that source registers now.
- **Credential resolution:** the `acme` index credential is bound (in the boot record) to a secret whose `source` is `aws_secrets_manager`; uv calls `keyring get https://pkgs.acme.example/simple <user>` → the core keyring backend → `runtime_secrets` → aws_core's SM source (authenticated by the instance's ambient IAM role) → the credential, never touching env.
- **Install phase 2 (gated):** `tap-plugin-samsite` and `tap-plugin-acme-sigstore` resolve from the `acme` index with that credential; `--index-strategy first-index` guarantees their names are never sought on the public index.
- **Audit:** the resolved `uv.lock` pins every package + hash — the verifiable known-good-set for Acme's instance.
