# Plugin External-Development Contract

## Philosophy

TAP is opening plugin development beyond the core team. External developers will
clone the core TAP repository as a **development harness**, build plugins in their
own git repositories, validate and CI those plugins against a known-good core, and
release them as git tags that boot profiles pin. This spec is the canonical record
of the **contract** that makes that safe and repeatable: how a plugin declares the
core it targets, how conformance is checked before release, how per-repo CI runs,
how the core↔plugin wire contract versions independently of product versions, and
how release artifacts are trusted.

It is deliberately grounded in prior art. The compatibility model follows VS Code
(`engines.vscode`, reject-on-mismatch at install) and Terraform (a coarse plugin
*protocol* version negotiated at load, decoupled from product semver). The
conformance model follows Salesforce AppExchange / Grafana / Datadog `ddev` — ship
the developer the same admission checker the platform runs, so conformance
converges before submission rather than at a review wall. Per-repo CI follows the
GitHub `workflow_call` reusable-workflow pattern on free generic runners. Release
trust follows Terraform / Grafana / VS Code signed artifacts verified at install.
See the 2026-07-09 prior-art synthesis in the eviction thread for the full
comparison.

This spec **owns the five-requirement contract** and its build sequencing. The
implementing mechanisms extend their home specs (`spec-tap-plugin-manifest-v0.md` for
the manifest field, `spec-tap-plugin-validation.md` for the conformance checks,
`spec-cicd-hardening.md` for signing); this spec is the umbrella that names them as
one agreed set and records what is built now versus deferred.

## The development model (context)

The external-developer loop, for reference (the "plugin workspace"):

- **Harness** — a clone of the core TAP repository. It is present in full (specs +
  tests included — external agents need them); it is *not* git-installed as a
  package. Core is the harness, not a dependency.
- **Workspace** — the harness plus N editable plugin-repo checkouts (the ones being
  edited) plus the rest git-installed at pinned tags. A mixed editable+git boot
  profile runs against it (proven 2026-07-09: an 8-git + 4-editable profile booted
  healthy). Coupled cross-plugin changes check out both plugins editable in one
  workspace and release in dependency order — the same mechanism, not a special
  case.
- **Release** — push a tag; consuming boot profiles bump their pinned rev
  (substrate-first). Products (e.g. Rampart-20x, Teleport) live in *private* product
  repositories, segregated at the repo boundary, never in the shared dev kit.

The five requirements below are the machine-enforced edges of that loop.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Fail-closed compatibility | A plugin that does not fit the running core is refused at boot with a legible message, never run-then-crash. |
| 2. | Self-service conformance | The developer runs the platform's own admission checker locally and in their own CI; green means shippable. |
| 3. | Reusable, pinned CI | One core-authored workflow runs a plugin repo's scoped validation against a known-good core on free runners. |
| 4. | Independent versioning | The core↔plugin wire contract versions on its own cadence, so core can iterate fast without churning every plugin's declared range. |
| 5. | Trusted artifacts | Release tags are signed and verified at install, closing the moved-tag / compromised-repo gap. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-plugin-extdev-compat-floor | [Compatibility Floor (`requires_tap`)](#compatibility-floor-requires_tap) | In Development | #1 — plugin declares a PEP 440 core-version range; boot refuses on mismatch. Build now. |
| req-tap-plugin-extdev-conformance | [Shippable Conformance Gate](#shippable-conformance-gate) | In Development | #3 — the existing `validate_plugin` checker is the admission gate the dev runs locally + in CI; add the compat check + release-gate framing. Build now. |
| req-tap-plugin-extdev-repo-ci | [Reusable Per-Repo CI](#reusable-per-repo-ci) | In Development | #4 — a `workflow_call` workflow in the core repo, pinned harness, scoped validation on free GH runners. Build now. |
| req-tap-plugin-extdev-protocol | [Grid-Plugin Protocol Version](#grid-plugin-protocol-version) | Proposed (Deferred) | #2 — a coarse wire-contract integer negotiated at boot, decoupled from product semver. **Pinned to the GitHub-org refactor** (CI/CD hardening); defining the contract surface rides that wave. |
| req-tap-plugin-extdev-signing | [Signed Release Artifacts](#signed-release-artifacts) | Proposed (Deferred) | #5 — signed tags / boot-record digests verified at install. **Pinned to the GitHub-org refactor** — signing identity is org-rooted; building it pre-org means rebuilding it. Cross-refs `req-cicd-supply-chain-provenance`. |

### Compatibility Floor (`requires_tap`)
----
RID: `req-tap-plugin-extdev-compat-floor`
Status: `In Development`

A plugin declares the range of core (`tap`) versions it supports, and boot refuses
to load a plugin whose declared range excludes the running core — before Django
starts the app, not deep in operation.

#### Implementation

- **Declaration.** A new optional top-level manifest field `requires_tap` is a
  PEP 440 version specifier string (e.g. `">=0.1,<0.2"`), parsed with
  `packaging.specifiers.SpecifierSet`. It joins the manifest under
  `req-tap-plugin-manifest-v0-top`; an absent field means "no declared floor" (allowed
  in v0, nudged by the conformance check). This is the VS Code `engines.vscode`
  model. When the protocol version (`req-tap-plugin-extdev-protocol`) lands it joins
  `requires_tap` as a sibling top-level field, or both promote to a `[compat]`
  table at that time.
- **Core version source.** The running core version is
  `importlib.metadata.version("tap")` when core ships installed metadata, falling
  back to `[project].version` in `<REPO_ROOT>/pyproject.toml` (present in the
  cloned-core harness, where core is on the path but not pip-installed). A single
  helper resolves it; the fallback chain covers both the harness and a future
  packaged core.
- **Enforcement (reject-on-mismatch at boot).** A pre-boot gate in `tap/preboot.py`
  — a sibling to `_conformance_gate`, reading each plugin's shipped manifest the
  same import-free way (`_manifest_path_for` / raw `tomllib`) — parses each
  declared `requires_tap` and raises `PrebootError` (fail-closed, the TAP-ABORT
  path) if the running core version is not contained in the range. A malformed
  specifier is itself a hard failure. An absent field is skipped (advisory only in
  v0).
- **Author-time surface.** The conformance checker gains a `requires_tap` structure
  check (see `req-tap-plugin-extdev-conformance` / `req-tap-plugin-validate-compat`): absent
  → **info** (recommend declaring it — non-fatal, since `requires_tap` is optional in
  v0, so it must not fail even under `--strict`); present-but-unsatisfied-by-the-harness-core
  → fail, so the developer sees a real mismatch at author time in their own harness.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-extdev-compat-floor-1 | Manifest Field | In Development | `requires_tap` is an optional top-level PEP 440 specifier string; malformed values are rejected at parse time. | Extends `req-tap-plugin-manifest-v0-top`. |
| req-tap-plugin-extdev-compat-floor-2 | Boot Refuses On Mismatch | In Development | A pre-boot gate raises `PrebootError` when the running core version is outside a plugin's declared `requires_tap`. | Fail-closed, not run-then-crash. |
| req-tap-plugin-extdev-compat-floor-3 | Core Version Resolved Robustly | In Development | Core version resolves from installed metadata, falling back to `pyproject.toml` in the cloned-core harness. | |
| req-tap-plugin-extdev-compat-floor-4 | Absent Is Allowed In v0 | In Development | A plugin with no `requires_tap` boots; the conformance check notes it informationally (non-fatal, not even under `--strict`) to encourage declaring it. | Tighten to a warning/failure in a later version once all TAP-owned plugins declare it. |

### Shippable Conformance Gate
----
RID: `req-tap-plugin-extdev-conformance`
Status: `In Development`

The developer runs TAP's own plugin admission checker — the same one CI and the
PR-back review run — so conformance converges before submission. The checker
already exists (`spec-tap-plugin-validation.md`: `validate_plugin`, three levels,
standalone CLI + management command, JSON schema). This requirement frames it as
the external-developer conformance gate and closes the remaining gap.

#### Implementation

- The conformance gate **is** the existing `validate_plugin` capability. It ships in
  `tap_plugins/` (core), so a cloned-core harness carries it to every external
  developer at no extra cost.
- **Gap closed now:** a `requires_tap` structure check (`req-tap-plugin-validate-compat`)
  is added to the `structure` level so a declared compat floor is checked at author time
  (absent is informational, not a failure — optional in v0),
  and the reusable CI (`req-tap-plugin-extdev-repo-ci`) invokes
  `python -m tap_plugins.validate_plugin --strict` as its conformance step. The
  standalone `structure` level needs no Django, so it runs in a bare checkout;
  `loads`/`runs` run in the booted harness.
- **Framing:** "conformance" is the union of the existing checks (identity
  coherence, declared dependencies, manifest structure, icons, service-layer
  smoke) plus the compat floor. No parallel second checker is introduced —
  `req-tap-plugin-validate-codepaths` (no divergent validation logic) still holds.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-extdev-conformance-1 | Ships In Harness | Implemented | The checker lives in `tap_plugins/` and travels with a cloned-core harness. | Already true. |
| req-tap-plugin-extdev-conformance-2 | Compat Check Added | In Development | The `structure` level checks `requires_tap` (absent → info/non-fatal; declared-but-unsatisfied → fail). | New: `req-tap-plugin-validate-compat`. |
| req-tap-plugin-extdev-conformance-3 | CI Runs It Strict | In Development | The reusable per-repo CI runs `validate_plugin --strict` as its conformance step. | Wired by `req-tap-plugin-extdev-repo-ci`. |
| req-tap-plugin-extdev-conformance-4 | Single Source Of Truth | Implemented | Conformance reuses TAP's real validation codepaths; no divergent second checker. | `req-tap-plugin-validate-codepaths`. |

### Reusable Per-Repo CI
----
RID: `req-tap-plugin-extdev-repo-ci`
Status: `In Development`

A single reusable GitHub Actions workflow, authored in the core repository, that a
plugin repository calls to validate itself against a known-good core on free
generic runners — the same validation entrypoint that runs locally.

#### Implementation

- **Shape.** `.github/workflows/plugin-ci.yml` with `on: workflow_call`. A plugin
  repo's own CI is a thin caller:
  `uses: unified-systems-com/tap/.github/workflows/plugin-ci.yml@<tag>`, passing its plugin
  slug(s) and boot profile as inputs. This is the GitHub reusable-workflow +
  float-forward-major-tag pattern.
- **Pinned harness.** The workflow checks out the core repo at a **pinned ref**
  (the `harness_ref` input, defaulting to a released core tag) — so results are
  reproducible and the plugin is always tested against a real, known-good core, not
  a moving target. Reciprocal of the monorepo `all-plugins.yml` lane, which owns
  full-set truth; this lane owns *one external plugin against pinned core*.
- **Scoped validation.** The workflow: (1) checks out core at `harness_ref` +
  the caller's plugin; (2) runs `validate_plugin --strict` on the plugin (structure,
  Django-free — fast, no boot); (3) boots the caller's profile and runs the plugin's
  own in-package tests + boot-verify (`loads`/`runs` conformance). It does **not**
  run the full gryphon corpus — that is the heavy integration path (CodeBuild),
  never external. Free runners only.
- **Local parity.** The same steps are invocable locally (the validate CLI + a boot
  profile), so a developer's laptop and their CI agree.
- **Credentials.** Private sibling plugins that the profile git-installs resolve
  through the read-only `github-plugins-ro` PAT, never the write-capable
  CodeConnections app.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-extdev-repo-ci-1 | Reusable Workflow | In Development | Core ships a `workflow_call` workflow a plugin repo invokes with `uses:`. | |
| req-tap-plugin-extdev-repo-ci-2 | Pinned Harness | In Development | The workflow tests against core checked out at a pinned `harness_ref`. | Reproducible, known-good. |
| req-tap-plugin-extdev-repo-ci-3 | Scoped, Free Runners | In Development | Validation is scoped to the caller's plugin set on free generic runners; no full corpus. | CodeBuild stays internal. |
| req-tap-plugin-extdev-repo-ci-4 | Conformance Step | In Development | The workflow runs `validate_plugin --strict` as a step. | Ties to `req-tap-plugin-extdev-conformance`. |
| req-tap-plugin-extdev-repo-ci-5 | Local Parity | In Development | The same validation entrypoint runs locally. | |

### Grid-Plugin Protocol Version
----
RID: `req-tap-plugin-extdev-protocol`
Status: `Proposed`

**Deferred — pinned to the GitHub-org refactor under CI/CD hardening.**

A coarse, slow-moving integer that versions *only* the core↔plugin wire contract
(the service-layer surface, boot hooks, registry shapes, edge-type APIs a plugin
calls) — decoupled from core's product version. Core advertises the protocols it
accepts (`accepts_protocol = [N-1, N]`); a plugin declares the protocol it needs
(`provides_protocol = N`); they negotiate at boot on the integer, not the product
version. This is Terraform's plugin-protocol model: product versions move
constantly, the protocol changes rarely, so a plugin spans many core releases
untouched, and a core that accepts a *range* lets one plugin straddle a migration
(Terraform's mux).

#### Rationale for deferral

`requires_tap` (build now) already gives a fail-closed floor. The protocol version
is the durable upgrade, but its cost is *defining the contract surface* — enumerating
what the core↔plugin contract actually is — which is most cheaply done as part of
the org refactor / CI/CD hardening wave rather than speculatively now. This is a
named deferral, not an omission: the org refactor is the trigger to build it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-extdev-protocol-1 | Protocol Field | Proposed (Deferred) | Plugins declare `provides_protocol`; core declares `accepts_protocol` (a range). | Home: manifest + a core constant. |
| req-tap-plugin-extdev-protocol-2 | Boot Negotiation | Proposed (Deferred) | Boot refuses a plugin whose `provides_protocol` is outside core's `accepts_protocol`. | Sibling to the compat gate. |
| req-tap-plugin-extdev-protocol-3 | Decoupled Cadence | Proposed (Deferred) | The protocol integer bumps only on breaking contract changes, independent of product semver. | The whole point. |

### Signed Release Artifacts
----
RID: `req-tap-plugin-extdev-signing`
Status: `Proposed`

**Deferred — pinned to the GitHub-org refactor under CI/CD hardening. Signing
identity is org-rooted; building it before the org exists means rebuilding it.**

Release tags (or the boot-record digests that pin them) are signed with a publisher
key and verified at install/boot; a mismatch refuses the plugin. This closes the
moved-tag / compromised-repo gap that a bare git tag (mutable, forgeable) leaves
open. Prior art: Terraform (GPG at `init`), Grafana (PGP, refuses unsigned in prod),
VS Code (registry-signed). Extends the existing integrity-verified boot-record path
to publisher signatures.

#### Rationale for deferral

For the Aug-1 friendly-developer phase the trust boundary is already tight — TAP
controls the org, the repos, and the read-only PAT, and the developers are known.
Signing earns its keep when the publisher set widens or for the customer/appliance
delivery. Per the security posture (cheap-now / expensive-later), the *seam* is
worth laying early — but its identity root is the org, so it rides the org refactor.
Cross-references `req-cicd-supply-chain-provenance` (Sigstore/cosign + SBOM), which
is the same signing capability at the artifact layer.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-extdev-signing-1 | Signed Tags/Digests | Proposed (Deferred) | Release tags or boot-record digests are signed by a publisher key. | Org-rooted identity. |
| req-tap-plugin-extdev-signing-2 | Verified At Install | Proposed (Deferred) | Boot verifies the signature and refuses on mismatch. | Extends integrity-verified boot-record. |
| req-tap-plugin-extdev-signing-3 | Standard Provenance | Proposed (Deferred) | Aligns with `req-cicd-supply-chain-provenance` (Sigstore/cosign, SBOM). | One signing story, two layers. |

## Non-Goals (this contract, now)

- A plugin **registry / marketplace** (discovery, ratings, central index). The
  roadmap ranks marketplace ecosystems as Lower; git-repo-per-plugin + boot-record
  pins is the v0 distribution model. A curated git-index-of-manifests (krew/Datadog
  model) for discovery/trust is a candidate later, not now.
- **Graceful "fall-forward"** degradation (Shopify's serve-oldest-supported). v0 is
  hard-refuse on compat mismatch; a degrade mode is a later decision.
- A plugin **scaffolding generator** command. The plugin-creation skill fills this
  role today; a first-class `tap new-plugin` generator is deferred.
