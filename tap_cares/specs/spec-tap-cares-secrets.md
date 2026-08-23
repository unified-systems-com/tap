# tap-cares Secrets Specification

## Philosophy

tap-cares secrets are local runtime inputs for collectors, receivers, emitters, actions, and other tap-cares capabilities that need sensitive material to interact with external systems.

v0 secrets are deliberately boring. Secret values live off-grid in a dedicated mounted secrets directory. tap-cares loads explicitly named JSON files from that directory into an internal scoped registry at Django startup. Runtime code resolves secrets through tap-cares helper functions rather than reading files directly or passing raw `scope:key` strings through capability code.

The grid may eventually know about secret references, health, usage, policy, and schema metadata. The grid does not store secret values in v0.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Local-first   | Support local/offline deployments with secrets mounted into the TAP container |
| 2. | Obvious       | Make secret files visually unmistakable and easy to ignore in git |
| 3. | Controlled    | Route secret access through one tap-cares resolver and registry |
| 4. | Minimal       | Avoid premature vault, encryption, and schema infrastructure |
| 5. | Future-ready  | Leave room for on-grid Secret metadata and generated secret files |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-cares-secrets-scope | [Secrets Scope](#secrets-scope) | Implemented | Secret material is off-grid runtime data |
| req-tap-cares-secrets-files | [Secret Files](#secret-files) | Implemented | Recursive `*.secret.json` discovery under a configured secrets root |
| req-tap-cares-secrets-root-resolution | [Secrets Root Resolution](#secrets-root-resolution) | Implemented | Exactly two canonical `TAP_SECRETS_ROOT` lookups — `settings.TAP_SECRETS_ROOT` inside Django, `tap/secrets_root.py` outside — every other consumer uses one of the two; literals live once; guard-pinned |
| req-tap-cares-secrets-resilient-load | [Resilient Load And Failure Surfacing](#resilient-load-and-failure-surfacing) | Implemented | Bad files are recorded (not crash-raised); `required_for_boot` escalates to blocking; surfaced via system check + the `tap_health` secrets probe |
| req-tap-cares-secrets-shape | [Secret JSON Shape](#secret-json-shape) | Implemented | Minimal required JSON object fields |
| req-tap-cares-secrets-registry | [Secret Registry And Resolution](#secret-registry-and-resolution) | Implemented | Internal `ScopedRegistry` plus `SecretRef` / `resolve_secret` helpers |
| req-tap-cares-secrets-validation | [Consumer Validation](#consumer-validation) | Implemented | Consumers validate kind-specific secret data |
| req-tap-cares-secrets-redaction | [Redaction And Failure Behavior](#redaction-and-failure-behavior) | Implemented | Secret material must not leak into logs or run records |
| req-tap-cares-secrets-consumer-kinds | [Consumer-Defined Secret Kinds](#consumer-defined-secret-kinds) | Implemented | Kind `data` shapes are owned by consuming plugin/collector specs, not here |
| req-tap-cares-secrets-consumer-scoping | [Consumer-First Scoping](#consumer-first-scoping) | Implemented | `scope` names *who consumes* the secret (owner namespace = plugin `<slug>` / app / install-system label), not the provider; `kind` carries the type. Directories stay non-semantic |
| req-tap-cares-secrets-conditional-validation | [Conditional Validation Lives In Health Probes](#conditional-validation-lives-in-health-probes) | Implemented | Whether a secret is *needed* is per-consumer conditional logic owned by health probes, not a static declaration; tap_cares owns only generic file-level load/format |
| req-tap-cares-secrets-rotation | [Rotation Semantics](#rotation-semantics) | Implemented | v0 is restart-to-rotate; atomic reload / staleness / rotation-due are named-deferred |
| req-tap-cares-secrets-leak-guard | [Source-Control Leak Guard](#source-control-leak-guard) | Implemented | A committed `*.secret.json` (or an envelope-shaped file outside the mount) fails a CI-guarded scan — push-protection beyond `.gitignore` |
| req-tap-cares-secrets-credential-patterns | [Credential Pattern Guard](#credential-pattern-guard) | Implemented | Self-identifying credential shapes (`github_pat_…`, `AKIA…`, PEM armor) fail a hard-zero scan across **every** text file — the leak guard reads only `*.json` |
| req-tap-cares-secrets-precommit | [Pre-Commit Enforcement](#pre-commit-enforcement) | Implemented | Both leak scans run in `.githooks/pre-commit` over staged files, so a credential is refused before the commit object exists |
| req-tap-cares-secrets-history-audit | [History Audit Before Publication](#history-audit-before-publication) | Implemented | A repository may not change visibility to public until a full-history credential scan is clean — the tree being clean says nothing about the commits |
| req-tap-cares-secrets-size-guard | [Secret Size Guard](#secret-size-guard) | Implemented | 1 MiB default ceiling per secret file, raised per-file via `metadata.max_bytes` — guards the dumb/malicious-oversize case while allowing a deliberately large secret |
| req-tap-cares-secrets-cross-scope-concern | [Cross-Scope Access Concern](#cross-scope-access-concern) | Implemented | Detective `CONCERN` tripwire — a plugin resolving the install-system `tap_plugins.source` scope emits a security `CONCERN`; the interim detective half of the deferred least-privilege enforcement |
| req-tap-cares-secrets-future-secret-model | [Future Secret BaseModel](#future-secret-basemodel) | Backlog | Future on-grid Secret metadata and file generation |
| req-tap-cares-secrets-future-encryption | [Future Encryption At Rest](#future-encryption-at-rest) | Backlog | Encrypted file format explicitly deferred |
| req-tap-cares-secrets-future-access-control | [Future Secret Access Control](#future-secret-access-control) | Backlog | `scope`'s least-privilege story is a naming convention today; investigate enforcing it so a caller can only resolve secrets it owns |

## Secrets Scope
----
RID: `req-tap-cares-secrets-scope`
Status: `Implemented`

tap-cares secrets are off-grid runtime material loaded from the local filesystem. The secret registry is an in-process runtime registry, not TAP-managed graph state.

Secret values must not be stored in:

- TAP-managed node fields
- TAP-managed edge properties
- GRIFT batches
- CollectionJob results
- scheduler configuration
- plugin manifests
- source-controlled fixtures

On-grid objects may later store non-secret references such as `aws:prod-readonly`, but those references are not secret material.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-scope-1 | Off-Grid Material | Implemented | Secret values live outside the TAP grid in mounted files. | |
| req-tap-cares-secrets-scope-2 | References Only | Implemented | On-grid objects may store secret references, but not secret values. | Future collector config/authenticator work. |
| req-tap-cares-secrets-scope-3 | No Direct File Reads | Implemented | Collectors and other consumers resolve secrets through tap-cares, not by reading secret files directly. | |

## Secret Files
----
RID: `req-tap-cares-secrets-files`
Status: `Implemented`

The runtime secret root is configured by deployment settings, with a Docker Compose secrets mount as the expected local/container mechanism.

At Django startup, tap-cares scans the configured secrets root recursively. Directories are non-semantic and exist only to help operators organize multiple sets of secrets. Only files whose basename matches:

```text
<key>.secret.json
```

are loaded. Non-matching files are ignored. Dotfiles are ignored.

The `*.secret.json` suffix is mandatory so secret files are visually obvious and can be ignored by source control. The repository-level `.gitignore` must ignore `*.secret.json`. Example or template files must use a non-matching suffix such as `.secret.example.json`.

The file declares its canonical identity. Directory names do not contribute to identity. The basename `<key>` must match the JSON object's `key` field so humans browsing the mounted folder see the same local key that tap-cares registers.

Duplicate `scope:key` values are configuration errors even when they appear in different directories. Like other per-file faults they are recorded, not crash-raised, per the resilient-load contract (`req-tap-cares-secrets-resilient-load`).

### Shared Resolver (Development)

The low-level mechanics of reading this store — discovering a `<key>.secret.json` by `scope`/`key` and validating the canonical envelope shape — live in the app-neutral `tap/runtime_secrets.py`, **not** in tap_cares. tap_cares is the *major* secrets manager: it owns the registry, the resilient-load report, the system check, the health probe, the basename/key match, and `required_for_boot` semantics, and it builds the rich `Secret` on top of the shared envelope. tap_auth resolves provider client credentials from the same store at settings-import time (before `tap_cares.ready()` runs) and so calls the shared resolver directly rather than importing tap_cares — keeping the two apps free of a cross-dependency. The resolver is import-safe (no Django settings access at import); each caller supplies the secrets root and re-wraps the resolver's neutral `RuntimeSecretError` in its own domain exception.

**Pluggable source seam (being added).** The resolver is disk-only today. `spec-tap-plugin-dependency-resolution.md` `req-tap-plugin-depres-sources` adds a source-provider seam so a manifest may route its *value* to an external store while its envelope stays disk-resident and TAP-owned: an optional `metadata.source` (absent ⇒ the built-in disk source, unchanged) plus a `metadata.source_ref` locator, dispatched to a provider discovered via the `tap.secret_sources` entry-point group (disk in core, cloud stores from a slim allow-listed distribution, e.g. `aws_secrets_source`). This does not change the required envelope fields, discovery, or the size/leak guards — see that spec for the seam design, trust-gating, and the AWS Secrets Manager worked example.

### Example Layout

```text
/run/tap-secrets/
  aws/prod-readonly.secret.json
  aws/dev-sandbox.secret.json
  github/fedramp-source.secret.json
```

### Multi-Session Host Convention

In the multi-session dev workflow (`specs/spec-dev-multisession.md`),
docker-compose.yml bind-mounts `./tap_secrets` (relative to each session's
worktree) into `/run/tap-secrets:ro`. `scripts/spawn-session.sh` provisions
that host path before `dc up` runs:

- If `$HOME/tap-secrets/` exists, the spawn script symlinks
  `<worktree>/tap_secrets -> $HOME/tap-secrets/` so a single host-side
  secrets directory feeds every session. `rm -rf` and `git worktree remove`
  do not follow the symlink, so despawn never touches the shared directory.
- Otherwise the spawn script creates an empty per-session directory; the
  loader no-ops cleanly and the operator can populate the session's
  `tap_secrets/` later. Despawn deletes any `*.secret.json` files it finds
  there — the despawn plan output flags this so a forgotten real secret is
  not silently nuked.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-files-1 | Recursive Discovery | Implemented | tap-cares recursively scans the configured secrets root at startup. | |
| req-tap-cares-secrets-files-2 | Secret Suffix | Implemented | Only `*.secret.json` files are loaded. | |
| req-tap-cares-secrets-files-3 | Git Ignore | Implemented | The repository ignores `*.secret.json`. | |
| req-tap-cares-secrets-files-4 | Directory Non-Semantic | Implemented | Directories help organization but do not define scope, key, or kind. | |
| req-tap-cares-secrets-files-5 | Basename Matches Key | Implemented | The filename's `<key>` portion must match the JSON object's `key` field. | |
| req-tap-cares-secrets-files-6 | Duplicate Guard | Implemented | Duplicate `scope:key` values are recorded as load failures (degraded unless `required_for_boot`), not crash-raised. | See `req-tap-cares-secrets-resilient-load`. |

## Secrets Root Resolution
----
RID: `req-tap-cares-secrets-root-resolution`
Status: `Implemented`
Tags: `Security`

`req-tap-cares-secrets-files` made the low-level resolver import-safe by having "each caller
supply the secrets root" — sound layering that left *who supplies the root* unspecified. The
2026-08 derive-the-same-fact-twice audit (#3) found the vacuum filled by five independent
inline resolutions: management commands restating `settings or env or "/run/tap-secrets"` in
full, `tap_cares.apps` restating a defensive variant, and the settings-free sites each reading
the env var themselves. Independent resolutions of *where credentials come from* can diverge
per entry point — for a secrets surface, that is not tolerable drift.

**The contract: exactly two canonical lookups, one per world** — an intentional duplicate
pair, tagged `TAP-KNOWN-DUPE(secrets-root)` at both sites per `req-tap-known-dupes`
(`specs/spec-tap-known-dupes.md`): the env read exists twice by design because settings-free
callers cannot import settings, and the tag makes each side point at its partner.

- **Inside Django: `settings.TAP_SECRETS_ROOT`.** Unchanged, and deliberately in
  `settings.py`'s house style (`os.environ.get("TAP_SECRETS_ROOT", "/run/tap-secrets")`):
  settings.py is the one file that projects environment variables into Python variables, and
  this variable follows the same pattern as every other. Every Django-side consumer
  (management commands, app `ready()` hooks, loaders) reads `settings.TAP_SECRETS_ROOT` —
  never the env var, never a literal.
- **Outside Django: `tap/secrets_root.py`.** A stdlib-only leaf (the same import-safety
  discipline as `tap/runtime_secrets.py`) owning the env-var name and the read:
  `resolve() -> Path | None`, env-or-None, **no default**. The settings-free callers apply
  their own documented unset-policies at their own edges:
  - `tap/preboot.py` — None ⇒ "no source-credential store", proceed (public sources only).
  - `tap_auth/providers/secrets.py` — settings when configured (test overrides), else
    `resolve()`, else raise `ProviderError` (it runs mid-settings-import; a provider
    without a resolvable store is a hard error).
  - `tap/boot_pointer.py` — `resolve()` else its host-side default `~/tap-secrets`
    (a GnuPG-style operator tool: `--secrets-root` flag > env > home default; the host
    literal lives only there).

**Prior-art grounding (2026-08-12 sweep).** Supervised-runtime secret stores are
*injection-first*: systemd credentials (`$CREDENTIALS_DIRECTORY`, consumer carries no
default), SPIFFE (`SPIFFE_ENDPOINT_SOCKET` as the sole well-known contract), Vault Agent
(operator-configured sink). Docker Swarm is the fixed-well-known-path school
(`/run/secrets`). TAP's container resolution is env-first with a Docker-school fallback that
equals what compose injects anyway. Host-side operator tools (GnuPG `--homedir` >
`GNUPGHOME` > `~/.gnupg`; pass) are the flag > env > home-default school `boot_pointer`
already follows.

**Named deferral (`req-sec-honest-risk`).** The systemd school would drop the in-container
default entirely (env unset ⇒ no credentials). TAP keeps it because settings.py is uniformly
dev-first — every env var there carries a dev default, including higher-stakes ones
(`SECRET_KEY`, `DATABASE_URL`). Making this one variable injection-required alone buys
inconsistency, not safety. The right unit of change is a **production strictness pass**
flipping the whole settings env family to injection-required at once; when that lands, the
container default here drops with the rest.

The boot-time `required_secrets` preflight is a fail-fast operator-UX gate, not a security
boundary — necessity truth is owned by per-consumer health probes
(`req-tap-cares-secrets-conditional-validation`) — and it consumes `settings.TAP_SECRETS_ROOT`
like any other Django-side consumer.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-root-resolution-1 | Two Canonical Lookups Only | Implemented | The `TAP_SECRETS_ROOT` env var is read in exactly two files: `tap/settings.py` and `tap/secrets_root.py`. Guard-pinned. | |
| req-tap-cares-secrets-root-resolution-2 | Django Consumers Use Settings | Implemented | Every Django-side consumer reads `settings.TAP_SECRETS_ROOT`; none re-reads the env var or restates a default. | Kills the audit-#3 triple restatements. |
| req-tap-cares-secrets-root-resolution-3 | Settings-Free Edges Own Their Unset-Policy | Implemented | Settings-free callers use `tap.secrets_root.resolve()` (env-or-None, no default); each caller's unset behavior (proceed / raise / host-default) is applied and documented at its own edge. | preboot / providers / boot_pointer. |
| req-tap-cares-secrets-root-resolution-4 | Literals Live Once | Implemented | `"/run/tap-secrets"` appears in Python only in `tap/settings.py`; the host default `~/tap-secrets` only in `tap/boot_pointer.py`. Guard-pinned. | Compose/docs/help-strings excepted. |
| req-tap-cares-secrets-root-resolution-5 | Strictness Pass Deferral Named | Implemented | The in-container default's removal is tied to the future whole-family production strictness pass, not done piecemeal. | systemd-school alignment, deferred. |

## Resilient Load And Failure Surfacing
----
RID: `req-tap-cares-secrets-resilient-load`
Status: `Implemented`

Secret loading at Django startup is **resilient, not crash-fast**. A single
malformed, mis-keyed, invalid-token, or duplicate secret file must never abort
`django.setup()` and crash-loop the instance — doing so kills the very surfaces
(`manage.py`, `manage.py health`, a shell) an operator needs to diagnose and fix it.

Instead the loader registers every valid file and records each bad file as a
non-secret `SecretLoadFailure` (source path, redacted structural reason, the
`scope:key` when determinable, and the file's `required_for_boot` flag) in a
process-wide `secret_load_report`. Exactly one fault still raises: a `root`
that exists but is not a directory — a gross mount/deploy misconfiguration of
the root itself, not a per-file fault.

**One load, three readers.** The single report populated in
`TapCaresConfig.ready` is consumed by three independent surfaces, separating
*validation* (strict, at the gate) from *process startup* (resilient):

| Reader | Degraded failure | `required_for_boot` failure |
| --- | --- | --- |
| `tap_cares` system check (`manage.py check`, `runserver`, validation gate) | `Warning` `tap_cares.W001` | `Error` `tap_cares.E001` — fails the build |
| `tap_health` secrets probe (running instance; WSGI/ASGI runs no checks) | `degraded` | `unhealthy` |
| boot | proceeds | refuses |

The `required_for_boot` boolean (see Secret JSON Shape) is what escalates a
recorded failure from degrade to blocking. It is read from the file's
`metadata` — best-effort even from a malformed-but-parseable file, since a bad
file can still self-declare that its failure must block standup; only a literal
`true` escalates. A file too broken to parse at all degrades (it cannot be
proven required) and is still recorded loudly.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-resilient-load-1 | No Crash-Loop | Implemented | A per-file load fault is recorded in `secret_load_report`, never raised, so startup does not crash-loop. | Non-directory root is the sole still-raising case. |
| req-tap-cares-secrets-resilient-load-2 | Failure Record Shape | Implemented | Each failure carries source path, redacted reason, optional `scope:key`, and `required_for_boot`; no secret material. | |
| req-tap-cares-secrets-resilient-load-3 | Blocking Escalation | Implemented | A failure whose file declared `required_for_boot: true` is blocking; others degrade. | |
| req-tap-cares-secrets-resilient-load-4 | System Check Surface | Implemented | The `tap_cares` check emits `E001` for blocking failures and `W001` for degraded ones. | Fails `manage.py check` / the validation gate. |
| req-tap-cares-secrets-resilient-load-5 | Health Surface | Implemented | The `tap_health` secrets probe (via `run_health()` / `manage.py health`) reports `unhealthy` on a blocking failure and `degraded` otherwise. | Covers running instances where system checks do not run; the unauthenticated `/healthz` was parked (`req-tap-health-exposure-4`). |

## Secret JSON Shape
----
RID: `req-tap-cares-secrets-shape`
Status: `Implemented`

Each v0 secret file must contain one JSON object with these top-level fields:

| Field | Required | Description |
| --- | :---: | --- |
| `scope` | Yes | Scoped registry scope, e.g. `aws` |
| `key` | Yes | Local key within the scope, e.g. `prod-readonly` |
| `kind` | Yes | Consumer-defined secret kind, e.g. `aws_static_access_key` |
| `description` | Yes | Free-form operator note explaining what this secret is and why it exists |
| `data` | Yes | Secret material object consumed by capability-specific code |
| `metadata` | No | Non-secret operator metadata useful for diagnostics |

v0 tap-cares validates only the minimal structural shape needed for registration. It does not validate kind-specific schemas.

#### Reserved metadata: `required_for_boot`

`metadata.required_for_boot` is a reserved boolean (default `false`). It
declares the *consequence of this file failing to load*, not a property of the
secret — chosen as an explicit boolean rather than an opaque policy enum so its
full meaning is visible at the file. When `true`, a load failure for this file
is **blocking** (fails the build / 503s health); when absent or `false`, a
load failure merely **degrades** the instance. It governs the present-but-
malformed (and duplicate) case; an entirely absent secret is handled at run
time by `resolve_secret` (`req-tap-cares-secrets-redaction-3`). When present it
must be a boolean (a non-boolean is itself a structural load failure). See
`req-tap-cares-secrets-resilient-load`.

#### Reserved metadata: `max_bytes`

`metadata.max_bytes` is a reserved positive integer that **raises** this file's
size ceiling above the 1 MiB default (`req-tap-cares-secrets-size-guard`). It is
raise-only — it cannot lower the default — and a non-positive-integer value is a
structural load failure. Absent, the default applies.

### Example

```json
{
  "scope": "aws_core",
  "key": "prod-readonly",
  "kind": "aws_static_access_key",
  "description": "Read-only AWS credentials used by the TAP aws_core collector.",
  "data": {
    "access_key_id": "AKIA...",
    "secret_access_key": "...",
    "region": "us-east-1"
  },
  "metadata": {
    "account_id": "123456789012",
    "required_for_boot": false
  }
}
```

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-shape-1 | JSON Object | Implemented | A secret file contains exactly one JSON object. | |
| req-tap-cares-secrets-shape-2 | Declared Identity | Implemented | The object declares `scope` and `key`. | |
| req-tap-cares-secrets-shape-3 | Kind Declared | Implemented | The object declares a `kind` string for consumer-side validation. | |
| req-tap-cares-secrets-shape-4 | Description Required | Implemented | The object includes free-form `description` text explaining the secret. | |
| req-tap-cares-secrets-shape-5 | Data Object | Implemented | The object includes a `data` object containing the secret material. | |
| req-tap-cares-secrets-shape-6 | No Kind Schema In Core | Implemented | tap-cares v0 does not ship or enforce kind-specific schemas. | Consumers validate their own shapes. |
| req-tap-cares-secrets-shape-7 | Required-For-Boot Flag | Implemented | `metadata.required_for_boot`, when present, is a boolean declaring that a load failure for this file is blocking. | See `req-tap-cares-secrets-resilient-load`. |

## Secret Registry And Resolution
----
RID: `req-tap-cares-secrets-registry`
Status: `Implemented`

tap-cares exposes an internal `secret_registry` backed by TAP's existing `ScopedRegistry` pattern. The registry value is a rich runtime object, not a raw dictionary, so label/description/kind/source-path metadata travels with the secret while the generic registry stays unchanged.

Consumers should use typed helpers rather than raw strings:

```python
ref = SecretRef(scope="aws_core", key="prod-readonly")
secret = resolve_secret(ref)
```

`SecretRef` is the stable non-secret reference shape. `resolve_secret(...)` returns a runtime `Secret` object that exposes metadata and secret data to trusted runtime code. Direct access to `secret_registry` is reserved for the secrets subsystem and tests.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-registry-1 | Scoped Registry | Implemented | Secrets are loaded into a dedicated `ScopedRegistry`. | |
| req-tap-cares-secrets-registry-2 | Rich Runtime Object | Implemented | Registry values carry `SecretRef`, `kind`, `description`, `data`, optional metadata, and source path. | |
| req-tap-cares-secrets-registry-3 | SecretRef Helper | Implemented | Runtime code can pass `SecretRef` objects instead of raw `scope:key` strings. | |
| req-tap-cares-secrets-registry-4 | Resolver Helper | Implemented | `resolve_secret(ref)` is the public access path for secret consumers. | |

## Consumer Validation
----
RID: `req-tap-cares-secrets-validation`
Status: `Implemented`

Kind-specific validation belongs to the consumer that understands the external system. tap-cares v0 does not centralize secret schemas because plugins and collectors will define many different secret shapes.

A consumer that requires AWS static credentials must validate that a resolved secret has the expected `kind` and required `data` fields before using it. Invalid consumer-specific shape fails the run visibly.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-validation-1 | Core Minimal Validation | Implemented | tap-cares validates only registration-level shape. | |
| req-tap-cares-secrets-validation-2 | Consumer Owns Kind Validation | Implemented | Consumers validate `kind` and `data` requirements before use. | `require_secret_kind(...)` accepts a consumer-owned JSON Schema. |
| req-tap-cares-secrets-validation-3 | Visible Invalid Shape | Implemented | A malformed-for-consumer secret fails the capability run with a structured redacted error. | |

## Redaction And Failure Behavior
----
RID: `req-tap-cares-secrets-redaction`
Status: `Implemented`

Secrets must not leak through logs, exceptions, run records, debug payloads, or rendered UI. tap-cares should provide a recursive redaction helper for structured diagnostics. At minimum, keys containing sensitive words such as `secret`, `token`, `password`, `private_key`, or `credential` are redacted.

Missing secrets do not prevent TAP from starting and do not remove collector capability nodes. A run that requires a missing secret fails visibly with a structured, redacted error in the run record. A *malformed* secret behaves the same way for non-blocking files — it is recorded, the instance degrades, and a run that needs it fails at run time — extending this missing-secret philosophy to bad files rather than crash-looping startup (`req-tap-cares-secrets-resilient-load`).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-redaction-1 | Redaction Helper | Implemented | tap-cares provides a helper to redact secret-shaped values from structured diagnostics. | |
| req-tap-cares-secrets-redaction-2 | No Secret Logs | Implemented | Secret material is never intentionally logged or persisted in run records. | Enforced by consumer discipline and redaction helpers. |
| req-tap-cares-secrets-redaction-3 | Missing Secret Run Failure | Implemented | Missing required secrets fail the run visibly rather than failing registration or startup. | `resolve_secret(...)` raises at runtime; consumers record failures. |

## Consumer-Defined Secret Kinds
----
RID: `req-tap-cares-secrets-consumer-kinds`
Status: `Implemented`

The secrets subsystem is kind-agnostic. `tap_cares` owns the *mechanics* —
`*.secret.json` discovery, the in-process registry, `SecretRef` /
`resolve_secret`, the `require_secret_kind` validation harness, redaction, and
string-keyed `kind` dispatch — and enumerates **no** kind-specific `data`
fields.

The *shape* of a given kind's `data` (its fields, which are required, and the
JSON Schema it validates against) is defined and owned by the consuming plugin
or collector spec. The consumer supplies that schema at its own boundary via
`require_secret_kind(secret, "<kind>", data_schema=<consumer schema>)`
(`req-tap-cares-secrets-validation`). Adding a new secret kind is therefore a
consumer-side spec + schema change, not an edit to this spec.

The reference example is the AWS static-credentials kind
(`aws_static_access_key`), owned by the aws_core plugin's
`spec-aws-core-secrets.md` (its aws-static secret requirement; the plugin and
its specs now live in the aws_core plugin repo). It was previously enumerated
here as a local aws-static requirement; that requirement and its ACIDs were
relocated to `aws_core` when this ownership boundary was made explicit, so the
generic subsystem carries no AWS-specific shape.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-consumer-kinds-1 | Subsystem Owns Mechanics | Implemented | File discovery, registry, resolution, `require_secret_kind`, redaction, and string `kind` dispatch are `tap_cares`-owned and kind-agnostic. | |
| req-tap-cares-secrets-consumer-kinds-2 | Consumer Owns Shape | Implemented | A kind's `data` fields and validation JSON Schema live in the consuming plugin/collector spec and are supplied to `require_secret_kind(..., data_schema=...)`; this spec enumerates none. | `data_schema` is a caller-supplied parameter, not a `tap_cares` constant. |
| req-tap-cares-secrets-consumer-kinds-3 | Reference Example | Implemented | `aws_static_access_key` is owned by the aws_core plugin's `spec-aws-core-secrets.md` (its aws-static secret requirement); this spec links it as the example, not the definition. | Relocated from this spec's former local aws-static requirement. |

## Consumer-First Scoping
----
RID: `req-tap-cares-secrets-consumer-scoping`
Status: `Implemented`

The `scope` field names **who consumes** a secret — the owning plugin/service — **not** which
provider issued the credential. The store is organized by consumer, not by credential type. This is
the axis-separation that keeps the store legible as it grows: a single provider (`github`) can serve
several consumers, and one consumer can hold credentials from several providers, so keying by
consumer is stable where keying by provider is not.

- **`scope` = the consumer's canonical namespace.** For a plugin, that is its **`<slug>`** — which
  rides the slug's conformance-gated uniqueness (`req-tap-plugin-arch-slug-register`,
  `doc-plugin-slug-load-bearing`), so the secret namespace inherits collision-freedom for free. The
  slug alone is already globally unique, so the `tap_plugin/` Python-package prefix is redundant in the
  secret namespace and is omitted (`github_core`, not `tap_plugin/github_core`). For a core app or an
  install *system*, it is the app/system label (`tap_auth`, `tap_cares`, `tap_plugins.source`).
- **`scope` is a flat, opaque label** under the canonical scoped-token grammar
  (`tap.registry.SCOPED_TOKEN_PATTERN`: ASCII alphanumerics plus `_.-`, no `/`) — shared with the
  collector registry and the pre-boot resolver, so the grammar cannot drift across read paths. A
  compound label uses `.` (`tap_plugins.source` = "the source subsystem of the install system"), not a
  path separator: `scope` is a namespace key, never a filesystem path. Keeping it flat also keeps it a
  clean key the deferred least-privilege enforcement can bind to
  ([Future Secret Access Control](#future-secret-access-control)).
- **`kind` still carries the credential *type*** (`github_pat`, `aws_static_access_key`). Location and
  type are orthogonal axes: **the `scope` says who uses it; the `kind` says what it is.** So two
  consumers can hold the same `kind` under different `scope`s, each validating with its own
  `data_schema` (`req-tap-cares-secrets-consumer-kinds`).
- **Infrastructure credentials belong to the app that consumes them, not to a plugin.** The plugin
  *source-install* credential (the git PAT the pre-boot installer uses) is owned by the install
  system, so its `scope` is `tap_plugins.source` — **not** under a plugin's `<slug>`. A plugin must never
  be able to resolve the credential that installs its siblings.
- **This is a convention on the `scope` *value*, not a change to `req-tap-cares-secrets-files-4`.**
  Directories stay non-semantic: the `scope`/`key` *fields* remain authoritative (recursively
  discovered), and the directory layout only mirrors `scope` for human navigation. `key` still
  matches the basename (`req-tap-cares-secrets-files-5`).

**Legacy — migrated 2026-07-03.** The former `github/collector` and `aws/boto_collector` secrets were
*provider-first* (`scope` = provider). They are now consumer-first (`github_core/collector`,
`aws_core/boto_collector`): the file's `scope` field, its `SecretRef` callsite, and the file location
were updated together. There is no dual-support window — `scope` is authoritative (recursively
discovered), so code and envelope move atomically. `auth` (an app, not a plugin) was deliberately left
as-is. The install-system credential was realigned from `tap_plugins/source` to `tap_plugins.source`
when the token grammar was centralized and made flat (2026-07-04): the same infra-not-a-plugin meaning,
now a valid scoped token on every read path (the pre-boot resolver previously accepted the `/` while the
tap_cares registry rejected it — the two-loader drift that degraded the secret's registry view).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-consumer-scoping-1 | Scope Is The Consumer | Implemented | `scope` names the owning consumer's canonical namespace, not the issuing provider. | |
| req-tap-cares-secrets-consumer-scoping-2 | Namespace Form | Implemented | Plugins scope under their `<slug>` (bare — the slug is already globally unique, so the `tap_plugin/` package prefix is omitted); core apps / install systems under the app/system label. `scope` is a flat opaque token (`SCOPED_TOKEN_PATTERN`, no `/`); a compound label uses `.` (`tap_plugins.source`), not a path separator. | |
| req-tap-cares-secrets-consumer-scoping-3 | Kind Carries The Type | Implemented | The credential type stays in `kind`; it is orthogonal to `scope`. Same `kind`, different `scope`s, per-consumer `data_schema`. | |
| req-tap-cares-secrets-consumer-scoping-4 | Infra Is App-Owned | Implemented | An infrastructure credential is scoped to the app that consumes it (e.g. `tap_plugins.source`), never under a plugin's namespace. | Least privilege: a plugin cannot resolve its siblings' install credential — a naming convention today; enforcement is [Future Secret Access Control](#future-secret-access-control). |
| req-tap-cares-secrets-consumer-scoping-5 | Directory Stays Non-Semantic | Implemented | This is a convention on the `scope` value; `req-tap-cares-secrets-files-4`/`-5` are unchanged (fields authoritative, basename==key). | |
| req-tap-cares-secrets-consumer-scoping-6 | Legacy Migration | Implemented | The former provider-scoped `github/collector`, `aws/boto_collector` are now consumer-first (`github_core/collector`, `aws_core/boto_collector`), migrated 2026-07-03. | Fields + `SecretRef` callsites + file moves; `auth` left as-is. `tap_plugins/source` → `tap_plugins.source` (flat-grammar realign, 2026-07-04). |

## Conditional Validation Lives In Health Probes
----
RID: `req-tap-cares-secrets-conditional-validation`
Status: `Implemented`

Whether a given secret is *needed* is not a static fact that can be written down once — it is a predicate over a consumer's configuration and grid state. The github collector pulling only public repos needs no token; the aws collector used only to ingest GRIFT files from another service, or to model a system on the design dimension, needs no credentials; an auth provider needs its `oidc_client` secret only when that provider is configured. A flat "expected secrets" list cannot express "required *if* …" without becoming a logic engine.

TAP already has that logic engine: the `tap_health` probe system (`spec-tap-health-v0.md`). So TAP does **not** maintain a static expected-secret declaration — no on-grid `SecretReference` table in v0 (that stays [Future Secret BaseModel](#future-secret-basemodel)), and no code-level required-secret list. **Conditional necessity is evaluated by the consuming app's own health probe**, reusing its existing self-test logic where it has one. The probe runs the consumer's own conditional check and validates presence + shape against the kind schema the consumer owns — which is also where the "validate known kinds earlier" goal is satisfied: a malformed *present* AWS or OIDC secret is reported at health time, before the consumer's next run, not as a mystery failure later.

**Division of labor (the boundary):**

- **`tap_cares` + `tap/runtime_secrets` (necessity-agnostic, generic):** file discovery, envelope load/format validation, and surfacing a *present-but-malformed* file — via the `secrets` health probe and the resilient-load system check (`req-tap-cares-secrets-resilient-load`). This layer never opines on whether a given secret is *needed*.
- **Per-consumer health probe (auth, each collector — owned by the consumer that knows its own config/state):** conditional necessity ("do I even need a key, given how I'm configured?") + presence + kind-shape. Reuses the consumer's offline self-test as the single source of truth so boot-time and runtime checks cannot drift.

`required_for_boot` (`req-tap-cares-secrets-shape-7`) stays **narrow** and must not be conflated with this: it means "if this file is *present* and fails to load, that failure is blocking." It does **not** mean "this file must exist." Conditional must-exist is the probe's job.

The auth providers health probe (`spec-tap-auth-v0.md` `req-tap-auth-providers`) is the worked reference; collectors mirror it through the `CollectorBase` offline self-test.

**Boot-profile declaration composes with this rule, not against it.** `req-boot-required-secrets` (`spec-tap-boot-v0.md`, Proposed) lets a boot profile declare the secrets its composition requires. That is not the static list this section forbids: the forbidden shape is **TAP itself** keeping a global expected-secret inventory (code-level or on-grid). A profile is one operator's config-as-code (`req-boot-trust`) declaring its own composition's dependencies — the same "the declaration IS the requirement" contract as the install path's per-source `credential` key (`req-tap-plugin-arch-source-secret-5`) — with conditionality carried structurally by which population steps are enabled, not by a logic engine. `tap_cares` stays necessity-agnostic (this layer neither reads nor enforces the declaration); `tap_boot` owns that contract, and per-consumer probes/self-tests remain the runtime authority for conditional necessity and liveness.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-conditional-validation-1 | Necessity Is Conditional | Implemented | Whether a secret is needed is a per-consumer predicate over config/state, not a static declaration; TAP keeps no static expected-secret list and no on-grid `SecretReference` in v0. | Profile-declared `required_secrets` (`req-boot-required-secrets`) is one composition's config-as-code, not a TAP-kept list — see the composition note above. |
| req-tap-cares-secrets-conditional-validation-2 | Probe Ownership | Implemented | The consuming app's health probe evaluates conditional necessity + presence + kind-shape, reusing its offline self-test as the single source of truth. | Auth is the reference; collectors mirror via `CollectorBase`. |
| req-tap-cares-secrets-conditional-validation-3 | Generic Layer Stays Necessity-Agnostic | Implemented | `tap_cares`/`tap.runtime_secrets` own only discovery + format + present-but-malformed surfacing; they never opine on necessity. | |
| req-tap-cares-secrets-conditional-validation-4 | required_for_boot Stays Narrow | Implemented | `required_for_boot` means "a present-but-broken file blocks boot," never "this file must exist." | Prevents conflation with conditional presence. |

## Rotation Semantics
----
RID: `req-tap-cares-secrets-rotation`
Status: `Implemented`

**v0 contract: restart to rotate.** Secrets are read exactly **once per process, at startup** — `tap_cares` loads the mount into `secret_registry` in `ready()`, and `tap_auth` resolves provider secrets even earlier, at settings-import. A change to a secret file on disk therefore has **no effect on a running process**. To rotate a secret: replace the file on the mount, then restart the process (container).

This is acceptable for v0 and is written down deliberately rather than left implicit. It matches TAP's broader restart-to-reload posture (no external cache; code changes already require a restart) and the rotation cadence of dev and early single-tenant deployments is low enough that a restart is cheap. Prior art points the other way for later: Kubernetes mounted-secret volumes update *eventually*; AWS/Vault emphasize caching, TTLs, leases, rotation, and revocation. TAP does none of that yet, by choice.

**Named-deferred (the risks left open, deliberately):**

- **Atomic in-process reload** — re-read the mount into the registry without a restart.
- **Staleness detection** — source `mtime` / content digest so the instance can know its in-memory value has diverged from disk.
- **Health surfacing** — a probe reporting a loaded secret as `stale` (differs from disk) or `rotation_due`. (The `rotation_due` notion is coupled to rotation existing; it is *not* built ahead of it.)
- **Vault-style lifecycle** — TTL / lease / revocation and short-lived credential exchange (relates to the short-lived-credentials backlog and [Future Secret BaseModel](#future-secret-basemodel)).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-rotation-1 | Restart To Rotate | Implemented | Secrets load once at process startup; rotating a secret requires replacing the file and restarting the process. | The documented v0 contract. |
| req-tap-cares-secrets-rotation-2 | No Hot Reload | Implemented | A change to a secret file does not affect a running process; there is no in-process reload in v0. | Stated as an explicit limitation, not a gap. |
| req-tap-cares-secrets-rotation-3 | Staleness Detection | Proposed | Detect that an in-memory secret has diverged from disk (mtime/digest). | Backlog |
| req-tap-cares-secrets-rotation-4 | Rotation Health Surface | Proposed | A health probe surfaces `stale` / `rotation_due`. | Backlog; gated on rotation existing. |
| req-tap-cares-secrets-rotation-5 | Atomic Reload / Lifecycle | Proposed | In-process atomic reload and vault-style TTL/lease/revocation. | Backlog |

## Source-Control Leak Guard
----
RID: `req-tap-cares-secrets-leak-guard`
Status: `Implemented`

The repository `.gitignore` ignores `*.secret.json` (`req-tap-cares-secrets-files-3`), but an ignore rule is bypassable (`git add -f`) and does nothing about a real secret renamed to dodge the suffix. The leak guard is **push-protection beyond ignore**, modeled on GitHub secret-scanning / push-protection: a scan that refuses to let a secret enter version control in the first place. It keeps secret *values* out of source control, the same way `req-tap-cares-secrets-scope` keeps them off the grid.

The scan is a CI-guarded `pytest` surface, mirroring the log-site-token and JSON-filename scanners (`tap.runtime_secrets` hosts the scan logic; `tap/tests/` is the enforcement). It is a **filesystem walk** (no git dependency, so it runs in-container like the sibling scanners) over the repository tree's `*.json` files, **excluding** vendored/cache dirs and the live secrets mount (`tap_secrets` — a gitignored symlink to the off-grid store). It fails on:

1. **Any `*.secret.json` file** — a secret file in the tree. High-signal, zero false positives.
2. **Any `*.json` file whose content is envelope-shaped** — a top-level object carrying the full canonical secret envelope (`scope` + `key` + `kind` + `data`) — outside allowed locations. Allowed: test fixtures/scaffolding and explicit `*.secret.example.json` templates. This catches a real secret renamed to evade the `.secret.json` suffix.

A hit is therefore either a committed leak or a stray real secret a developer dropped in the tree outside the mount — both must be removed (and the credential rotated). This surface is registered in the Validation Map (`spec-dev-validation.md`). It is enforced both per-commit (`.githooks/pre-commit`, `req-tap-cares-secrets-precommit`) and in CI (`pytest`).

This guard covers *envelope-shaped* material only, and only in `*.json`. Raw credentials in any other file type are the sibling `req-tap-cares-secrets-credential-patterns` guard's job; the two are complementary and neither subsumes the other.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-leak-guard-1 | No Secret Files In The Tree | Implemented | A `*.secret.json` file anywhere in the scanned tree fails the scan. | Push-protection beyond `.gitignore`. |
| req-tap-cares-secrets-leak-guard-2 | No Disguised Secrets | Implemented | A file whose content is the canonical secret envelope fails, outside test fixtures and `*.secret.example.json` templates. | Catches suffix-evasion. |
| req-tap-cares-secrets-leak-guard-3 | Mount + Vendored Dirs Excluded | Implemented | The walk excludes the live secrets mount (`tap_secrets`) and vendored/cache dirs, so the legitimate off-grid store is never flagged. | |
| req-tap-cares-secrets-leak-guard-4 | Map-Registered Surface | Implemented | The guard has a row in the `spec-dev-validation.md` Validation Map. | Co-change discipline. |

## Credential Pattern Guard
----
RID: `req-tap-cares-secrets-credential-patterns`
Status: `Implemented`

The leak guard (`req-tap-cares-secrets-leak-guard`) is structural and reads only `*.json`. That leaves an entire class uncovered: a raw token pasted into a `.py`, `.md`, `.sh`, `.yml` or `.env`, or a PEM private key — a GitHub App signing key, for instance — dropped in as a `.pem`. Neither the envelope scan nor `.gitignore` (which globs `*.secret.json`) sees any of it. This guard walks **every text file** in the tree for credential shapes that identify themselves.

**Issuer prefixes, not entropy — and this is an evidence-based choice, not a preference.** A full-history `gitleaks` run over this repository on 2026-07-22 (1,198 commits) returned 13 findings, *all* from its entropy-based `generic-api-key` rule and *all* false positives: log-site-id constants, an AWS `OriginAccessControlId` in a test fixture, `s3cret-pw-xyz` in a superuser test, and `authz denied:` lines in committed log samples. Entropy cannot distinguish "opaque identifier" from "credential" in a codebase whose fixtures are full of the former. The patterns here key on the issuer's own prefix and length instead (`github_pat_`, `gh[pousr]_`, `AKIA`/`ASIA`, PEM armor, `xox[baprs]-`, `AIza`), which is self-identifying and matched **zero** of the 874 text files in the tree.

That zero is what licenses a **hard zero** rather than a ratcheting baseline. Every other ceiling guard in this repo carries a baseline of accepted debt; this one must not, because an accepted-debt list of leaked credentials is not a coherent object. New matches fail, full stop.

**What it deliberately does not catch** (`req-sec-honest-risk`): AWS *secret* access keys, database passwords, and bare high-entropy strings with no distinguishing prefix. Those are entropy problems and belong in the per-push `gitleaks` CI step, where a human triages. This surface is the fast exact layer and does not claim to be a general secret scanner. Saying so here is the point — a guard that implied full coverage would be worse than one that admits its edge.

A documentation example or test vector that must show a real-looking token may carry the `TAP-CREDENTIAL-OK` marker on the same line — the narrow, review-visible escape hatch, mirroring `# noqa: TAP-LOG-ID`.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-credential-patterns-1 | All Text Files Scanned | Implemented | The walk covers every decodable UTF-8 file, not just `*.json`. | Closes the leak guard's file-type blind spot. |
| req-tap-cares-secrets-credential-patterns-2 | Self-Identifying Shapes Only | Implemented | Patterns key on issuer prefix + length; no entropy heuristic. | Evidence: 13/13 entropy findings were false positives. |
| req-tap-cares-secrets-credential-patterns-3 | Hard Zero, No Baseline | Implemented | Any match fails; there is no accepted-debt baseline file. | Deliberate divergence from the ceiling-ratchet guards. |
| req-tap-cares-secrets-credential-patterns-4 | Masked Failure Output | Implemented | Failure output masks the matched body, keeping the issuer prefix only. | CI logs are themselves a disclosure surface. |
| req-tap-cares-secrets-credential-patterns-5 | Reviewable Exemption | Implemented | A line carrying `TAP-CREDENTIAL-OK` is skipped. | Same idiom as `# noqa: TAP-LOG-ID`. |
| req-tap-cares-secrets-credential-patterns-6 | Mount + Vendored Dirs Excluded | Implemented | The walk excludes `tap_secrets` and vendored/cache/coverage dirs. | The legitimate off-grid store is never scanned. |

## Pre-Commit Enforcement
----
RID: `req-tap-cares-secrets-precommit`
Status: `Implemented`
Trace: `non-python` — .githooks/precommit_secret_scan.py

Both leak scans previously ran only as `pytest` guards, which meant a credential was caught *after* the commit object existed and possibly after it was pushed to a branch. For a repository whose history is destined to become public that is the wrong side of the line: rewriting history is far more expensive than refusing the commit. The `secret-leak` guard's own docstring described it as "push-protection" and said it "fails the commit" — a comment asserting a guarantee the implementation did not provide.

`.githooks/pre-commit` closes it. `core.hooksPath` is already set to `.githooks` (the post-checkout/post-merge/post-rewrite hooks live there), so the hook is picked up with no per-developer setup. It scans **staged content only** — via `git diff --cached` — so it is fast enough to keep, and it imports `tap.credential_patterns` and `tap.runtime_secrets` directly with no Django configured.

A client-side hook is bypassable (`git commit --no-verify`), which is exactly why the CI guards remain the authority. The hook is the cheap early catch, not the enforcement boundary; claiming otherwise would repeat the error it fixes.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-precommit-1 | Staged Content Scanned | Implemented | The hook scans staged blobs, not the working tree. | Catches exactly what is about to be committed. |
| req-tap-cares-secrets-precommit-2 | Filename + Pattern Scans Run | Implemented | The staged-`*.secret.json` filename rule and the full credential-pattern scan both run. | |
| req-tap-cares-secrets-precommit-5 | Envelope-Content Scan Is CI-Only | Implemented | The envelope-shape scan is NOT in the hook — it needs `jsonschema`, absent on a bare host. Stated in the hook, not hidden. | `secret-leak` guard still enforces it. |
| req-tap-cares-secrets-precommit-6 | Fails Loud Without python3 | Implemented | A missing interpreter blocks the commit rather than passing silently. | A no-op scanner reads as green. |
| req-tap-cares-secrets-precommit-3 | No Setup Required | Implemented | Delivered via the existing `core.hooksPath = .githooks`. | No per-developer install step to forget. |
| req-tap-cares-secrets-precommit-4 | Not The Authority | Implemented | Bypassable by design; the CI guards remain enforcing. | Documented, not implied. |

## History Audit Before Publication
----
RID: `req-tap-cares-secrets-history-audit`
Status: `Implemented`

A clean working tree says nothing about the 1,198 commits behind it. Once a repository is public its history is cloned and indexed permanently, so a credential committed and later removed is still disclosed — and rotation after the fact is the only remedy. Publication is therefore gated on a **full-history** scan, not a tree scan.

The audit runs `gitleaks git` over the complete object graph. Findings are triaged by a human — the entropy rules that make it useful here are the same ones that make it noisy, and the triage record belongs with the decision. The scan **must not** be run from a git worktree with the object store unmounted: doing so exits 0 having read nothing, which is a false green (observed 2026-07-22, and the reason this requirement names the failure mode explicitly).

**Audit record.** Core repository `tap`, full history at `7fb1c06a`, scanned 2026-07-22: 13 findings, all triaged false positives, **no real credentials**. The 16 evicted plugin repositories carry history extracted from this monorepo and are **not yet audited** — each requires its own clean scan before its visibility changes.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-history-audit-1 | Full History, Not Tree | Implemented | The scan covers all commits, not the checked-out tree. | A tree scan cannot clear a history. |
| req-tap-cares-secrets-history-audit-2 | Gate On Visibility Change | Implemented | No repository becomes public without a clean, triaged audit. | Publication is irreversible. |
| req-tap-cares-secrets-history-audit-3 | False-Green Guarded | Implemented | The scan must run where the git object store is readable; a worktree with an unmounted `.git` exits 0 having scanned nothing. | Observed failure, 2026-07-22. |
| req-tap-cares-secrets-history-audit-4 | Per-Repository | Proposed | Each evicted plugin repository needs its own audit. | Core done; 16 plugin repos outstanding. |

## Secret Size Guard
----
RID: `req-tap-cares-secrets-size-guard`
Status: `Implemented`

A single secret file is size-checked before it is trusted: `tap/runtime_secrets` rejects a file larger than **1 MiB** (`DEFAULT_SECRET_MAX_BYTES`) unless the file **raises its own ceiling** with an optional `metadata.max_bytes` field (a positive integer). The effective limit is the larger of the default and the declared value, so the field is **raise-only** — it cannot lower the default or reject a sub-default file. A consumer that legitimately needs a large secret (a future collector consuming a deliberately big credential blob) opts in by declaring `metadata.max_bytes` on that secret file; everything else is guarded at 1 MiB against an accidental or malicious oversize file (a misnamed log, a runaway write, a bad paste).

The override lives in the secret file's `metadata` (it travels with the secret and the loader reads it anyway), so the guard is uniform across both load paths with no per-caller wiring:

- `load_secret_envelope` — the **bulk-load path** the tap_cares loader uses for every discovered secret — honors the per-file `metadata.max_bytes` override.
- `find_secret_file` — tap_auth's small-reference-secret discovery path — applies the fixed 1 MiB cap to each candidate *before* reading it, so discovery cannot slurp an oversized file; the file it returns is already within the cap.

**Threat model (named, honest).** The secrets mount is operator-controlled, so this guard targets the *dumb/accidental* oversize case, not a hostile actor who already controls the mount (such an actor would simply supply malicious credential *values*). It is not a hard DoS defense: on the override path a file over the default is read once before its declared ceiling is checked. A **pre-read absolute ceiling** that fails truly pathological files (multi-GB) before any read is the general `req-tap-json-size-guard` on `load_json_file`, deferred there.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-size-guard-1 | Default Ceiling | Implemented | A secret file larger than 1 MiB is rejected with a `RuntimeSecretError`. | `DEFAULT_SECRET_MAX_BYTES`. |
| req-tap-cares-secrets-size-guard-2 | Per-File Override | Implemented | `metadata.max_bytes` (a positive integer) raises the ceiling for that file; the effective limit is `max(default, declared)`. | Raise-only; enables deliberately large secrets. |
| req-tap-cares-secrets-size-guard-3 | Malformed Override Rejected | Implemented | A `metadata.max_bytes` that is not a positive integer fails envelope parsing. | |
| req-tap-cares-secrets-size-guard-4 | Uniform Across Paths | Implemented | The override is honored on the bulk-load path; the discovery path applies the fixed default before reading each candidate. | |
| req-tap-cares-secrets-size-guard-5 | Hostile-Mount Ceiling Deferred | Proposed | A pre-read absolute ceiling that fails pathological files before any read. | Folds into `req-tap-json-size-guard`. |

## Cross-Scope Access Concern
----
RID: `req-tap-cares-secrets-cross-scope-concern`
Status: `Implemented`

`resolve_secret` is an unguarded lookup today — any code that reaches it can resolve any `scope:key` (the preventive least-privilege control is deferred, [Future Secret Access Control](#future-secret-access-control)). We cannot *prevent* a plugin (arbitrary Python) from resolving a scope it does not own, but we are not powerless: we **observe and alarm**. This is the first instance of the security-posture `CONCERN` discipline (`spec-security-posture.md`, `req-sec-concern-gaps`) — the *detective* half of the same edge whose *preventive* half is the deferred enforcement.

`resolve_secret` emits a `CONCERN` (`spec-tap-logging.md`, `req-tap-logging-concern-signal`; `message_code = CONCERN`, `security`-tagged, `concern_type = cross_scope_secret_access`) when a **plugin** on the call stack resolves a secret outside its own scope.

**Narrow v0 — the zero-false-positive case only.** The tripwire fires solely when a `tap_plugin.<slug>` frame is resolving the install-system scope (`SOURCE_SECRET_SCOPE` = `tap_plugins.source`) — a plugin reaching for the credential that installs its siblings, which has no legitimate case. Broader plugin-resolves-another-plugin's-scope detection carries false positives (a shared-utility plugin) and is a deliberate fast-follow, not shipped in the v0 tripwire, so the concern stream stays clean. Caller identity is best-effort (`tap.caller_identity.calling_plugin_slug`, a stack read a determined plugin can evade); that residual is accepted per `req-sec-honest-risk`. The check is non-blocking (fires open — the resolution proceeds) and is skipped entirely for any non-install scope, so it adds no cost to normal secret resolution.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-cross-scope-concern-1 | Tripwire Fires | Implemented | A plugin frame resolving `SOURCE_SECRET_SCOPE` emits a `security` `CONCERN` (`concern_type = cross_scope_secret_access`). | Highest-signal, zero-false-positive case. |
| req-tap-cares-secrets-cross-scope-concern-2 | Non-Blocking | Implemented | The concern fires open — the resolution proceeds; the check is skipped for any non-install scope. | Detective, not preventive. |
| req-tap-cares-secrets-cross-scope-concern-3 | No False-Positive Fire | Implemented | A non-plugin caller (framework/core/pre-boot installer) resolving the install scope does not fire; nor does a plugin resolving its own scope. | Steady-state clean. |
| req-tap-cares-secrets-cross-scope-concern-4 | Secret-Free Signal | Implemented | The concern names the plugin slug, scope, and key — never secret material. | |
| req-tap-cares-secrets-cross-scope-concern-5 | Preventive Counterpart Named | Implemented | The requirement links its deferred preventive control (`req-tap-cares-secrets-future-access-control`) per the `CONCERN` discipline. | Detection now, prevention later. |

## Future Secret BaseModel
----
RID: `req-tap-cares-secrets-future-secret-model`
Status: `Backlog`

A future TAP-managed `Secret` or `SecretReference` BaseModel may make secrets grid-accessible without placing secret values on the grid. This model would exercise the dual-existence pattern: an on-grid node for metadata, policy, references, health, usage edges, and schema intent; an off-grid registry/file entry for the actual secret material.

The future model is also a likely place to define or reference a schema for a secret kind. A management command could use that schema and on-grid metadata to generate a starter `<key>.secret.json` file for an operator to fill in outside source control.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-future-secret-model-1 | Backlog Requirement Exists | Backlog | On-grid secret metadata is tracked as a named future requirement. | |
| req-tap-cares-secrets-future-secret-model-2 | Values Stay Off-Grid | Backlog | Any future Secret BaseModel stores references and metadata, not secret values. | |
| req-tap-cares-secrets-future-secret-model-3 | Schema Home Candidate | Backlog | A future Secret BaseModel may define or reference a schema used to generate secret files. | |
| req-tap-cares-secrets-future-secret-model-4 | Generator Command Candidate | Backlog | A future management command may generate starter `<key>.secret.json` files from Secret metadata/schema. | |

## Future Encryption At Rest
----
RID: `req-tap-cares-secrets-future-encryption`
Status: `Backlog`

Encryption at rest for mounted secret files is explicitly deferred. v0 does not define the encrypted file format, key derivation, envelope shape, cipher choice, or reload behavior.

Future encryption work should preserve the v0 runtime contract: after successful decryption, tap-cares receives the same logical secret object shape described in [Secret JSON Shape](#secret-json-shape).

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-future-encryption-1 | Backlog Requirement Exists | Backlog | File encryption is tracked without committing to a format in v0. | |
| req-tap-cares-secrets-future-encryption-2 | Runtime Shape Preserved | Backlog | Future decryption yields the v0 logical secret object shape before registration. | |

## Future Secret Access Control
----
RID: `req-tap-cares-secrets-future-access-control`
Status: `Backlog`

**The honest gap.** `resolve_secret(ref)` is an **unguarded registry lookup** today: any
runtime code that can reach the resolver can resolve *any* `scope:key`. The consumer-first
`scope` convention ([Consumer-First Scoping](#consumer-first-scoping)) *names* an ownership
boundary — and `req-tap-cares-secrets-consumer-scoping-4` even states the intent as "least
privilege: a plugin cannot resolve its siblings' install credential" — but nothing **enforces**
it. `scope` is a namespace label (a `dict` key on `ScopedRegistry`) that buys collision-free
keying and a human/AI-readable owner tag; it is **not** an access-control boundary. So the
least-privilege language in the scoping requirements is, as of v0, **aspirational** — recorded
here per the honest-risk posture (`spec-security-posture.md` `req-sec-honest-risk`) rather than
implied complete.

**What to investigate (someday).** Harden the secret access mechanism so `scope` graduates from
a naming convention into an *enforced* least-privilege boundary — resolution gated on the calling
actor/capability actually owning (or being explicitly granted) the requested `scope`, so a plugin
genuinely cannot resolve another plugin's — or the install system's `tap_plugins.source` —
credentials. Natural design inputs when the work is picked up:

- **The capability system (`tap_auth`).** Gate `resolve_secret` on a capability keyed to the
  scope (e.g. a `secrets.resolve:<scope>` grant, or the caller's bound program-actor owning the
  scope), so the boundary rides the same policy engine as the rest of TAP rather than a parallel
  check. Fits the fine-grained-capabilities direction (read-vs-write, per-owner separability).
- **The future Secret BaseModel** ([Future Secret BaseModel](#future-secret-basemodel)). An
  on-grid Secret/SecretReference node is the obvious home for scope ownership, grant edges, and
  policy metadata — access control and the on-grid model likely land together.
- **Trigger.** Demand-gated like the rest of the secrets backlog: the boundary matters most once
  more than one *mutually-distrusting* consumer (multiple customer plugins, a real multi-tenant
  or partner deployment) shares one instance's mount. Single-operator dev/demo does not exercise
  it. The cheap edges available *now* are (1) keeping the token grammar tight and opaque (no `/`) so a
  scope stays a clean key an enforcement layer can bind to later, and (2) the shipped **detective**
  counterpart — the [Cross-Scope Access Concern](#cross-scope-access-concern) tripwire
  (`req-tap-cares-secrets-cross-scope-concern`) that alarms today where this enforcement will block
  tomorrow. When enforcement lands, the same caller-scope-vs-`ref.scope` comparison flips from log to deny.

This is investigation-not-commitment: it does not fix a cipher, a policy shape, or an enforcement
point. It records that the enforcement is missing and names where it would attach.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-secrets-future-access-control-1 | Backlog Requirement Exists | Backlog | The gap between the named least-privilege intent and the unenforced resolver is tracked as a named future requirement. | Honest-risk: not implied complete. |
| req-tap-cares-secrets-future-access-control-2 | Resolver Authorization | Backlog | Investigate gating `resolve_secret` on the calling actor/capability owning or being granted the requested `scope`. | Reuse `tap_auth`, not a parallel check. |
| req-tap-cares-secrets-future-access-control-3 | Scope As Enforced Boundary | Backlog | Under the hardened mechanism, a consumer cannot resolve a `scope` it does not own — the `consumer-scoping-4` least-privilege claim becomes enforced, not aspirational. | Multi-consumer / multi-tenant trigger. |
| req-tap-cares-secrets-future-access-control-4 | On-Grid Model Alignment | Backlog | Scope ownership / grants likely live on the future Secret BaseModel; access control and that model are expected to co-design. | Links `req-tap-cares-secrets-future-secret-model`. |
