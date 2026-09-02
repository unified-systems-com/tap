---
title: preplugin — zizmor: GitHub Actions workflow audits, consumed onto the grid
date: 2026-09-02
status: planning
audience:
  - developer
  - llm
related_docs:
  - docs/misc/doc-products-git-serious-build-log.md
---

> **Planning doc for `/new-plugin --from-spec docs/misc/preplugin-zizmor-v0.md`.** Authored
> 2026-09-02 in the mvp-git-serious session from the CI/CD security prior-art survey's verdict on
> zizmor (**CONSUME**) and the git-serious feature spec it serves
> (`req-git-serious-workflow-lint-findings`). Facts below marked *observed* were measured this day;
> everything else is *documented* from the sources named. The skill's review pass should treat the
> **Decisions to confirm** section as its bounded clarifying batch.

## Plugin Identity

- **Slug:** `zizmor` — dist `zizmor-tap`, import namespace `tap_plugin.zizmor`, AppConfig
  `tap_plugin.zizmor.apps:ZizmorConfig`, repo `unified-systems-com/tap-plugin-zizmor` (leaf plugin,
  not a `*_core` substrate: it consumes github_core's vocabulary and is consumed by git-serious).
- **Display name:** TAP zizmor
- **Collector:** `ZizmorCollector` — a *derived* collector: it reads workflow YAML github_core has
  already landed on the grid, runs the pinned zizmor binary **offline** over it, and lands typed
  findings attached to the workflow (and job, where the finding locates one). No forge access, no
  credential, no network.
- **Initial entry points:** landing page `/zizmor` (what zizmor is and does, the pinned version,
  current findings, current runs); run page `/zizmor/runs/<run_id>` (summary + details of one
  execution); finding page `/zizmor/findings/<finding_id>`. Every finding and every run in any
  table is a link into its page. Panel types: `zizmor_findings_table`, `zizmor_runs_table`,
  `zizmor_run_summary`, `zizmor_run_detail`, `zizmor_finding_detail`, `zizmor_about`. git-serious
  mounts the findings table on its lint-findings surface and links into the same pages.
- **Default dimensions:** inherit github_core's on every finding — `github.platform`, `github.owner`,
  `github.repo`, `github.surface = "actions"` — plus `github.observation = "declaration"` (a finding
  about the pipeline as *written*), and `zizmor.scanner_version = "<pinned>"` so two scans by two
  versions never merge into one fact.

## Philosophy

Workflow static analysis is a solved commodity. zizmor (zizmorcore; MIT; 41 audits; ~650 adopters
including GitHub itself; Trail of Bits hardened it against a 41,253-workflow corpus) does it better
than we ever will, so the prior-art survey's verdict was one word: consume. Re-implementing any of its
audits is waste. What zizmor cannot do — and what this plugin exists for — is put a finding *beside*
the ruleset that requires the check, the run history of the job it flags, and the credential the job
can reach. That placement is git-serious's whole contribution; the finding itself is zizmor's.

Three consequences shape v0:

1. **The finding is data with provenance, never a verdict we author.** Every finding carries the
   scanner, its exact version, the audit ID, zizmor's own severity and confidence, and the location
   it reported. GUAC's discipline: origin / collector / justification / known-since on every
   assertion, so disagreement between scanners (CodeQL's Actions pack, poutine, later) is data.
2. **Run offline over what we already hold.** github_core's GraphQL config layer inlines every
   workflow file (`GithubWorkflow.configuration.raw_yaml`; *observed* 2026-09-02: 75 workflows for
   our org in one collection). zizmor accepts a directory of workflow files and an `--offline`
   flag. So the collector needs no credential, makes no request, and its result is a pure function
   of grid state plus a pinned binary — reproducible, replayable, and cheap enough to run on every
   github_core collection.
3. **Three states, never two.** A workflow zizmor did not evaluate — because the online-only audits
   were skipped, because the YAML failed to parse, because the binary was absent — renders as *not
   observed by this scanner*, never as clean. Absence of a finding is not a finding of absence.

**Backlogged, not out (make-it-right column):** everything past the first successful execution is
a `Backlog`-status requirement below, not a non-goal — the online audits, the three input kinds
github_core does not collect, the compliance bridge, fix mode, a second scanner. The gate between
them and v0 is one fact: the plugin has to execute once against our org before any of it is real.

## The binary — how a pinned Rust executable rides in a Python plugin

This is the interesting shape and the reason the plugin is worth doing carefully. The answer is the
*adopt native distribution* doctrine: never roll our own package distribution.

**zizmor is on PyPI as a wheel** (*observed* 2026-09-02: `zizmor 1.30.0`, `requires_python >=3.10`;
wheels for manylinux x86_64/aarch64/armv7l, musllinux, macOS x86_64/arm64). Each wheel is one static
binary (`zizmor-1.30.0.data/scripts/zizmor`, 26.6 MB on manylinux_2_28 x86_64), a `RECORD`, the MIT
license — **and its own CycloneDX SBOM** (`zizmor-1.30.0.dist-info/sboms/zizmor.cyclonedx.json`,
400 KB, PEP 770), listing every Rust crate compiled in.

So the plugin declares one Tier-0 runtime dependency, pinned exactly:

```toml
dependencies = ["zizmor==1.30.0"]
```

and everything else falls out of machinery that already exists:

| Concern | How it is handled | Status |
| --- | --- | --- |
| **Pinning** | Exact `==` in `pyproject.toml`; `uv.lock` in the plugin repo; the boot record's install pin (`zizmor-tap@vX.Y.Z`) pins the closure. No cargo, no GitHub-release download, no vendored binary, no checksum we author twice. | Existing |
| **Release SBOM** | `plugin-release-sbom.yml` runs pinned Syft over our wheel: `zizmor` appears as a `pkg:pypi/zizmor@1.30.0` component. | Existing |
| **Crate-level SBOM** | The wheel's embedded CycloneDX (PEP 770) carries the crate tree (`reqwest`, `rustls`, `ring`, `aws-lc-rs`, …). **Verified 2026-09-02 (observed): the pinned Syft (`anchore/syft:v1.51.0`) does NOT ingest it** — a directory scan of the unpacked wheel yields `pkg:pypi/zizmor@1.30.0` plus six file entries and zero crate components, with and without `--select-catalogers +sbom-cataloger` (Syft's PEP 770 support is still an open issue, anchore/syft#737). The embedded document holds 328 components. So the release lane merges it explicitly as a nested component of the plugin's SBOM, keyed to the exact wheel version — a one-time addition to `scripts/sbom/plugin_release.py`, in the plugin's feature issue. | Verified: NOT ingested → the release lane merges it |
| **Deployed closure** | The wheel installs at boot into the container venv (git-source install of the plugin pulls its deps). The boot record is the BOM of what actually runs (`req-boot-*`; "boot-record IS the BOM"). | Existing |
| **Crypto BOM / FIPS** | *Observed* in zizmor's `Cargo.lock`: `ring`, `aws-lc-rs`/`aws-lc-sys`, `rustls`, `rustls-platform-verifier`, `reqwest` — the binary carries two non-OpenSSL providers for TLS. The manifest declares honestly: `[fips] status = "uses-nonvalidated"`, `providers = ["rust-ring", "rust-aws-lc-rs"]`, `reason = "TLS for zizmor's online audits; this plugin invokes zizmor --offline, so the providers are present but never execute a security operation. A FIPS deployment waives per plugin in the boot profile."` A false `compatible` would FAIL conformance; the honest declaration PASSES (`req-fips-crypto-bom-conformance-2`). On the certificate question: AWS-LC has a FIPS 140-3 validated module, but it ships as a *separate* crate (`aws-lc-fips-sys`, selected by aws-lc-rs's `fips` feature); zizmor's `Cargo.toml` pulls `reqwest` with default features, i.e. the non-FIPS `aws-lc-sys` build, and `ring` (never validated) is also linked. **The wheel's binary is not the validated module even though the library it embeds is validatable.** Offline that is moot (unreached); the day online audits ship, TLS executes and the declaration is load-bearing — a FIPS profile then needs either a zizmor built with the `fips` feature (not what PyPI ships) or the operator's per-plugin waiver. Whether `validate_plugin`'s `scan_plugin` resolves a *declared dependency's* wheel to fingerprint the binary is **unverified**. | Declare now; verify scan reach → issue |
| **Vulnerability notification** | Two channels, one gap. (a) **Dependabot alerts are enabled** on every plugin repo (*observed*: 204 on tap-plugin-github-core, git-serious-tap) — the GitHub Advisory DB covers PyPI `zizmor`, so a published advisory alerts the repo. (b) **Renovate** has `pep621` enabled with `osvVulnerabilityAlerts: true`, but `RENOVATE_REPOSITORIES` is `unified-systems-com/tap` only — **plugin repos get no Renovate PRs today**. Onboarding plugin repos to the self-hosted Renovate run is the missing half; zizmor releases every 2–3 weeks (*observed*: v1.26.1 → v1.30.0 across 2026-06-21 → 2026-08-30), so the bump PR is the release notification. (c) Trivy nightly scans *images*; a boot-installed wheel is not in the image, so Trivy does not cover it — the boot-record BOM queried against OSV is the closing move, already parked as the dependency-defense item. | (a) existing; (b) issue; (c) parked |
| **Attestation** | The plugin's own wheel is attested by the release lane (SLSA provenance + SBOM predicates). zizmor's PyPI wheels are published via Trusted Publishing from `zizmorcore/zizmor` — verify the publisher on the first pin bump and record it in the spec as the accepted upstream identity. | Verify once |

Two shapes were considered and rejected. **Fetching the GitHub release binary at install** puts an
unpinned network fetch in the boot path and a checksum we author by hand — presence, not
correctness. **Baking the binary into the tap-web image** makes core carry a product's dependency
and puts a 27 MB Rust binary in every instance that never runs it. The wheel is the lockfile seam
the doctrine names, and every gate we have already reads that seam.

## Goals

| # | Name | Description |
| --- | --- | --- |
| 1 | Consume, Do Not Rebuild | Every finding on the grid is zizmor's, with zizmor's ID, severity, confidence and location; the plugin authors no audit. |
| 2 | Offline And Derived | The collector reads workflow YAML already on the grid and runs the pinned binary offline; no credential, no network, reproducible from grid state. |
| 3 | Provenance On Every Finding | Scanner, exact version, persona, audit ID, known-since and observed-at ride on each finding so scanner disagreement is data. |
| 4 | Three States | Unevaluated workflows render as *not observed by this scanner*, never as clean. |
| 5 | Native Distribution | The binary arrives as the pinned PyPI wheel; pinning, SBOM, crypto-BOM and vulnerability alerts ride existing machinery, with the gaps named rather than papered. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-zizmor-binary | [The Pinned Binary](#the-pinned-binary) | Proposed | Exact PyPI pin; honest `[fips]` declaration; SBOM/alert channels named with their gaps |
| req-zizmor-collector | [Offline Derived Collector](#offline-derived-collector) | Proposed | Materialize `raw_yaml` per repo → `zizmor --offline --format json-v1` → GRIFT batch |
| req-zizmor-finding | [The Finding Node](#the-finding-node) | Proposed | `zizmor__finding` with provenance fields; edges to workflow and job |
| req-zizmor-run | [Runs Are First-Class](#runs-are-first-class) | Proposed | One `zizmor__run` per execution; findings and scanned workflows hang off it; unevaluated = not observed by this scanner |
| req-zizmor-pages | [Landing, Run And Finding Pages](#landing-run-and-finding-pages) | Proposed | `/zizmor`, `/zizmor/runs/<id>`, `/zizmor/findings/<id>`; every table cell drills in |
| req-zizmor-online-audits | [Online Audits, Aligned To The Graph](#online-audits-aligned-to-the-graph) | Backlog | The four API-backed audits via github_core's auth seam; findings land on `github_action`/`USES_ACTION`; FIPS accounting becomes real |
| req-zizmor-input-kinds | [Actions, Dependabot And Pre-commit Inputs](#actions-dependabot-and-pre-commit-inputs) | Backlog | Pulled by github_core collecting three more file kinds |
| req-zizmor-compliance-bridge | [Compliance Bridge](#compliance-bridge) | Backlog | Finding → compliance requirement edges (CICD-SEC-n, SLSA) via compliance_core |
| req-zizmor-fix-mode | [Fixes As Patches](#fixes-as-patches) | Backlog | zizmor's safe fixes surfaced as agent-applicable patches |
| req-zizmor-second-scanner | [A Second Scanner In The Same Shape](#a-second-scanner-in-the-same-shape) | Backlog | poutine / CodeQL Actions pack; scanner disagreement as data |

### The Pinned Binary
----
RID: `req-zizmor-binary`
Status: `Proposed`

The plugin's only Tier-0 runtime dependency is `zizmor==<exact>` from PyPI; the collector locates
the installed binary through the environment (the wheel installs it on `PATH` as `zizmor`) and
refuses to run any other copy. The manifest `[fips]` table declares `uses-nonvalidated` naming
`rust-ring` and `rust-aws-lc-rs` with the offline-invocation reason. The plugin's spec records the
verified upstream publisher identity and the four channels of the table above with their status.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-binary-1 | Exact Pin | Proposed | `pyproject.toml` pins `zizmor==X.Y.Z`; `uv.lock` resolves it; `validate_plugin --strict` passes with the honest `[fips]` declaration. | |
| req-zizmor-binary-2 | Version Stamped | Proposed | Every finding carries the binary's reported version (`zizmor --version`), which equals the pinned version, else the collector aborts before scanning. | Presence is not correctness: the binary that ran is the one that was pinned. |
| req-zizmor-binary-3 | SBOM Presence | Proposed | The plugin's release SBOM lists `pkg:pypi/zizmor@X.Y.Z`; the crate-level embedded SBOM is either ingested or attached as a nested component, and the spec says which. | |
| req-zizmor-binary-4 | Alert Channel Proven | Proposed | A Dependabot alert or Renovate PR fires for a zizmor advisory or release on the plugin repo — demonstrated once with a real bump, not assumed from configuration. | The Renovate half needs plugin-repo onboarding (issue). |

### Offline Derived Collector
----
RID: `req-zizmor-collector`
Status: `Proposed`

`ZizmorCollector` runs after github_core's collection (declared dependency: `github_core`). Per
repository on the grid, it materializes each `GithubWorkflow.configuration.raw_yaml` into a scratch
`.github/workflows/<path>` tree, invokes `zizmor --offline --format json-v1 [--persona <p>]` over
it, and lands one GRIFT batch: the run node, findings, edges to the workflow (and job when the finding's
location names one), and the run's `SCANNED` edges with per-workflow outcomes. Persona defaults to `regular`; `pedantic` / `auditor`
are boot-record configuration. The collector never contacts a network and declares no
`required_secrets`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-collector-1 | Pure Function Of Grid State | Proposed | Two runs over unchanged workflow rows with the same pinned binary produce identical finding sets; no network access is attempted (asserted with egress blocked in the test). | |
| req-zizmor-collector-2 | Our Org, First Light | Proposed | Against the viz session's collected org (75 workflows, *observed*), the collector completes and lands findings whose audit IDs appear in zizmor's documented audit list. | |
| req-zizmor-collector-3 | Fires From The Record | Proposed | A boot record's `fire-collector` step for `zizmor:zizmor` runs after `github_core:github_core` and reports counts in the boot record. | |

### The Finding Node
----
RID: `req-zizmor-finding`
Status: `Proposed`

A typed node `zizmor__finding` (BaseModel, table-prefixed per type ownership) carrying: `audit_id`,
`audit_url`, `severity`, `confidence`, `persona`, `scanner_version`, `summary`, `location` (path,
line, column, job key, step index as reported), `fixes` (zizmor's list of title + disposition safe/unsafe — a finding with a safe fix is a different object, and later a patch an agent can apply), zizmor's raw finding JSON, and
`known_since` (first observation) / `observed_at`. Edges: `PRODUCED__zizmor` from its run; `FLAGS_WORKFLOW__zizmor` (finding →
`github_workflow`) always; `FLAGS_JOB__zizmor` (finding → `workflow_job`) when the location resolves
to a declared job. Naming follows the corpus's edge rules and the SPDX-first check.

**Implementation note (George, 2026-09-02):** `zizmor__finding` is a compliance-level node in
disguise — a scanner's assertion about an asset, which is the same shape compliance_core's `finding`
bridges to a requirement. For the make-it-work phase a scanner-shaped node is fine; the
implementation must record, in the model's docstring and domain article, that surfacing it *beside
other findings* (poutine, CodeQL, git-serious's own conjunction findings, compliance findings) is an
open design that the compliance bridge (`req-zizmor-compliance-bridge`) and a second scanner
(`req-zizmor-second-scanner`) will force — and must not paint itself into a shape that only zizmor
can occupy (no zizmor-only field names where a scanner-neutral one exists).

**Decision to confirm:** mint `zizmor__finding` (recommended — scanner provenance fields do not fit
compliance_core's `finding`, which bridges an asset to a compliance requirement) and add the edge to
a compliance requirement later, versus reusing compliance_core's `finding` now with scanner fields in
`tags`. The register's "reuse, don't mint rivals" rule argues for reuse; the fields argue for a
scanner-shaped node with a later bridge. Recommend mint, name the bridge as the v1 edge.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-finding-1 | Provenance Complete | Proposed | Every landed finding has non-empty `audit_id`, `severity`, `confidence`, `scanner_version` and `observed_at`, and an edge to exactly one workflow. | |
| req-zizmor-finding-2 | Job Resolution Honest | Proposed | A finding whose location names a job that exists on the grid gets `FLAGS_JOB`; one whose job cannot be resolved gets no job edge and records why in `tags`. | |

### Runs Are First-Class
----
RID: `req-zizmor-run`
Status: `Proposed`

Each collector execution lands one `zizmor__run` node: scanner version, persona, audit set,
started/finished, the repositories and workflows it covered, per-workflow outcome
(`evaluated` / `parse-failed` / `skipped`), and finding counts by audit and severity. Findings hang
off the run that produced them (`PRODUCED__zizmor`, run → finding) and the run records what it
scanned (`SCANNED__zizmor`, run → workflow, with the outcome on the edge). This is what makes "no
finding" distinguishable from "not scanned": a workflow with no `SCANNED` edge from the current
run renders as *not observed by this scanner* in every consumer. The four online-only audits are
recorded as `skipped` on every v0 run.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-run-1 | Not Scanned Is Visible | Proposed | Remove one workflow's `SCANNED` edge from the current run; the findings table shows it as *not observed by this scanner*, not as clean. | The three-states rule, mechanized. |
| req-zizmor-run-2 | Counts Match | Proposed | A run's recorded finding counts equal the findings reachable from it by `PRODUCED`; a mismatch fails the collector's own post-check. | Presence is not correctness. |

---
### Landing, Run And Finding Pages
----
RID: `req-zizmor-pages`
Status: `Proposed`

Three pages, built with the add-page / add-panel skills, all Gryphon-backed:

- **Landing `/zizmor`** — an *about* panel (what zizmor is and does, the audit families, the
  pinned scanner version as observed from the binary, persona in use, the offline posture and the
  four audits it therefore skips), the **current findings** table (latest run, filterable by audit
  and severity, with not-observed rows), and the **current runs** table (recent runs with counts and
  outcome).
- **Run `/zizmor/runs/<id>`** — a summary panel (version, persona, coverage: repositories and
  workflows evaluated / parse-failed / skipped, counts by audit and severity, duration) and a
  details panel (every finding the run produced, every workflow it scanned with its outcome).
- **Finding `/zizmor/findings/<id>`** — the finding in full: audit and its documentation link,
  severity, confidence, persona, the location with `feature` text, available fixes, the workflow
  and job it flags with links onto their github_core pages, and the run that produced it.

Every finding cell in any table links to its finding page; every run cell links to its run page.
git-serious's lint-findings surface mounts `zizmor_findings_table` and inherits the links.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-pages-1 | Drill-In Works | Proposed | From the landing page, one click reaches a run page and one click reaches a finding page; from the run page, one click reaches any of its findings. | |
| req-zizmor-pages-2 | Version Is Observed | Proposed | The about panel's scanner version is read from the binary at run time and recorded on the run, never typed into the page. | Derive, don't declare. |

---
### Online Audits, Aligned To The Graph
----
RID: `req-zizmor-online-audits`
Status: `Backlog`

The four audits zizmor cannot run offline — `impostor-commit`, `known-vulnerable-actions`,
`ref-confusion`, `typosquat-uses` — run with a token through **github_core's auth seam, never a
second envelope**. Their findings are about action references, so they must land on nodes and
edges that already exist on the grid by then: `github_action` and `USES_ACTION` (corpus: self tier,
proposed) carrying `pin_kind`, `pinned_sha`, `declared_ref`, `resolves_to_fork` — an impostor-commit
finding points at the exact reference whose SHA does not belong to the canonical repository, and
`known-vulnerable-actions` attaches advisory identifiers to the action version. **Depends on:**
`github_action` built in github_core; the first offline run (`req-zizmor-collector-2`) observed.
**FIPS becomes load-bearing here:** online means TLS executes inside the binary, so the
`uses-nonvalidated` declaration stops being "present but unreached"; a FIPS profile needs a
`fips`-feature build of zizmor or the operator's per-plugin waiver, decided then.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-online-audits-1 | Lands On The Reference | Backlog | An impostor-commit finding has an edge to the `github_action` node and the `USES_ACTION` edge it concerns; none lands on the workflow alone. | |
| req-zizmor-online-audits-2 | One Credential | Backlog | The online run resolves its token through github_core's seam; the plugin declares no `required_secrets` of its own. | |

---
### Actions, Dependabot And Pre-commit Inputs
----
RID: `req-zizmor-input-kinds`
Status: `Backlog`

zizmor audits four input kinds; github_core collects one. When github_core fetches `action.yml`
(the defining side of `github_action`), `.github/dependabot.yml` and pre-commit config — the same
GraphQL config fetch, more paths — the collector materializes them beside the workflows and the
Dependabot audits (`dependabot-cooldown`, `dependabot-execution`) and action audits gain inputs.
**Depends on:** github_core collection additions (friends tier).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-input-kinds-1 | Dependabot Audited | Backlog | A repository with a Dependabot config on the grid receives `dependabot-*` findings attached to that config's node. | |

---
### Compliance Bridge
----
RID: `req-zizmor-compliance-bridge`
Status: `Backlog`

An edge from a finding to the compliance requirement(s) it evidences — OWASP CICD-SEC-n, SLSA
Source/Build, OSPS Baseline — reusing compliance_core's vocabulary rather than minting a rival. The
prior-art survey's §3.7/§3.10 mapping is the seed data. This is what makes a finding an attestation
input rather than a lint line.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-compliance-bridge-1 | Tagged Findings Bridge | Backlog | A `template-injection` finding carries an edge to the CICD-SEC-4 requirement node when compliance_core's catalog holds it. | |

---
### Fixes As Patches
----
RID: `req-zizmor-fix-mode`
Status: `Backlog`

zizmor reports `fixes` per finding (title, disposition safe/unsafe) and can apply them. Surface a
safe fix as a patch an agent can propose against the repository — read-only from the grid's side;
the write is a pull request the operator's own tooling opens. **Depends on:** the agent-operable
review surface (git-serious innovation spec).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-fix-mode-1 | Safe Fix Rendered | Backlog | A finding with a safe fix renders the patch text; the plugin never writes to the forge. | |

---
### A Second Scanner In The Same Shape
----
RID: `req-zizmor-second-scanner`
Status: `Backlog`

poutine or CodeQL's Actions pack lands findings in the same node shape with `scanner` as a
dimension, so two scanners' disagreement on one workflow is a queryable fact. Whether that is a
sibling plugin or a scanner dimension on this one is decided when the second scanner is real.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-second-scanner-1 | Disagreement Queryable | Backlog | For one workflow, a query returns the findings per scanner side by side. | |

---
## Vocabulary dependencies — what this plugin needs that exists, and what it needs that does not

Endpoints this plugin attaches to, checked against the corpus (`spec-github-core-vocabulary.md`) and
the grid as collected 2026-09-02:

| Endpoint | State | v0 handling |
| --- | --- | --- |
| `github_workflow` | built, on the grid | `FLAGS_WORKFLOW__zizmor` always |
| `workflow_job` | built (self tier, PR #4) | `FLAGS_JOB__zizmor` when the location resolves |
| `github_action` + `USES_ACTION` (workflow_job → github_action, `{pin_kind, pinned_sha, declared_ref, resolves_to_fork}`) | **corpus: self tier, proposed, NOT built** | Nine of zizmor's audits are about `uses:` references (`unpinned-uses`, `stale-action-refs`, `ref-confusion`, `impostor-commit`, `known-vulnerable-actions`, `typosquat-uses`, `archived-uses`, `superfluous-actions`, `forbidden-uses`). Attaching those to the workflow alone loses the join the conjunction feature needs (the *mutable reference* leg). **Not zizmor's to mint — github_core's.** v0 carries the `uses` string in the finding's `location`/`tags`; `FLAGS_ACTION__zizmor` is the v1 edge, added the day `github_action` lands. |
| `actions_secret` (proposed, self) | **not built** | `secrets-inherit`, `overprovisioned-secrets`, `secrets-outside-env` findings name secrets by string in `tags` until the node exists. |
| step | **corpus ruling: a field, not a node** ("revisit only if an edge genuinely needs a step as an endpoint") | zizmor reports step indices; the finding keeps them in `location`. A finding needs the job as its endpoint, not the step — the ruling holds. |

**Input kinds zizmor audits that github_core does not collect.** zizmor collects four kinds by
default — workflows, actions (`action.yml`, the in-repo/composite definition side of
`github_action`), Dependabot config (two dedicated audits: `dependabot-cooldown`,
`dependabot-execution`), and pre-commit config. github_core fetches workflows only. v0 audits what
is on the grid; the other three are github_core collection additions (same GraphQL fetch, more
paths), pulled by zizmor's audits, friends tier. zizmor exposes **no parse** — no dump or
collect-only mode; its model crates are Rust-only — so the grid's shape stays github_core's parse,
and the rule holds: vocabulary from collection, findings from scanners, never a shape derived from
the absence of a finding.

So: two nodes and three edges are this plugin's (the catalog below); one node and one edge it
wants are github_core's already-proposed self-tier work, and the plugin's first real findings are
the demand signal that pulls them in. File that as a github_core issue the day the collector first
runs, with the finding counts per audit as the evidence.

## Reference data

None. Findings are collected, never seeded; a fixture pack of zizmor `json-v1` output over the
repo's own workflows drives the tests.

## Icons

A single finding glyph and a scan glyph in the plugin's `static/zizmor/`; reuse github_core's
workflow and job icons on the far side of the edges.

## Decisions to confirm (the skill's clarifying batch)

1. Mint `zizmor__finding` versus reuse compliance_core's `finding` (recommendation above).
2. Repo shape: standalone `tap-plugin-zizmor` from the first commit (recommended — every plugin is
   evicted; the workspace flow is `--dev-plugins zizmor,github_core`).
3. Persona default (`regular`) and whether `--pedantic` is a boot-record option or a fixed choice.
4. Whether the collector runs on every github_core collection (recommended, it is cheap and offline)
   or on its own schedule.

## Issues this doc opens

- The plugin itself (feature issue, parent: git-serious lint-findings feature once step 4 mints it).
- Plugin repos are outside the self-hosted Renovate run (`RENOVATE_REPOSITORIES=unified-systems-com/tap`).
- Verify: pinned Syft and PEP 770 embedded SBOMs; `scan_plugin` reach into a declared dependency's wheel.
