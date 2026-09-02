# zizmor Plugin Specification

## Plugin Identity

- **Slug:** `zizmor`
- **Display name:** TAP zizmor
- **Description:** GitHub Actions workflow audits, consumed offline onto the grid — zizmor's findings beside the workflows, jobs, rulesets and credentials they concern.
- **Distribution:** dist `zizmor-tap`; import namespace `tap_plugin.zizmor`; AppConfig `tap_plugin.zizmor.apps:ZizmorConfig`; standalone repo `unified-systems-com/zizmor-tap` from the first commit (every plugin is evicted; development runs through `spawn-session.sh <label> --boot-file <record> --dev-plugins zizmor,github_core`). A leaf plugin, not a `*_core` substrate: it consumes github_core's vocabulary and is consumed by git-serious.
- **Collector:** `ZizmorCollector` (`CollectorBase`; registry key `zizmor:zizmor`) — a *derived* collector: it reads workflow YAML github_core has already landed on the grid, runs the pinned zizmor binary **offline** over it, and lands typed findings attached to the workflow (and job, where the finding locates one). No forge access, no credential, no network.
- **Trigger:** its own `schedule` node (tap_cares scheduler; seeded by this plugin's GRIFT, user-editable) plus a boot-record `fire-collector` step for first light. See `req-zizmor-trigger`.
- **Initial entry points:** landing page `/zizmor`; run page `/zizmor/runs/<run_id>`; finding page `/zizmor/findings/<finding_id>`. Panel types: `zizmor_about`, `zizmor_findings_table`, `zizmor_runs_table`, `zizmor_run_summary`, `zizmor_run_detail`, `zizmor_finding_detail`. Pages, panels and searches ship as one GRIFT document (`grift/pages.grift.json`). git-serious mounts `zizmor_findings_table` on its lint-findings surface and links into the same pages.
- **Default dimensions (on every plugin-owned node and edge):** inherit github_core's — `github.platform`, `github.owner`, `github.repo`, `github.surface = "actions"` — plus `github.observation = "declaration"` (a finding is about the pipeline as *written*) and `zizmor.scanner_version = "<version read from the binary>"`, so findings from two scanner releases are separate partitions and never merge into one fact.
- **Persona:** fixed `regular` in v0, recorded on every run; `pedantic` / `auditor` are a Backlog boot-record option.

## Philosophy

Workflow static analysis is a solved commodity. zizmor (zizmorcore; MIT; 41 audits; ~650 adopters
including GitHub itself; Trail of Bits hardened it against a 41,253-workflow corpus) does it better
than we ever will, so the prior-art survey's verdict (`doc-git-serious-cicd-security-prior-art.md`,
§2.4) was one word: consume. Re-implementing any of its audits is waste. What zizmor cannot do — and
what this plugin exists for — is put a finding *beside* the ruleset that requires the check, the run
history of the job it flags, and the credential the job can reach. That placement is git-serious's
whole contribution (`req-git-serious-workflow-lint-findings`); the finding itself is zizmor's.

Three consequences shape v0:

1. **The finding is data with provenance, never a verdict we author.** Every finding carries the
   scanner, its exact version, the audit ID, zizmor's own severity and confidence, and the location
   it reported. GUAC's discipline: origin / collector / justification / known-since on every
   assertion, so disagreement between scanners (CodeQL's Actions pack, poutine, later) is data.
2. **Run offline over what we already hold.** github_core's GraphQL config layer inlines every
   workflow file (`GithubWorkflow.configuration.raw_yaml`; *observed* 2026-09-02: 75 workflows for
   our org in one collection). zizmor accepts a directory of workflow files and `--offline`. So the
   collector needs no credential, makes no request, and its result is a pure function of grid state
   plus a pinned binary — reproducible and replayable.
3. **Three states, never two.** A workflow zizmor did not evaluate — because the online-only audits
   were skipped, because the YAML failed to parse, because the binary was absent — renders as *not
   observed by this scanner*, never as clean. Absence of a finding is not a finding of absence.

**Scope.** v0 is the first execution against our own organisation and the pages to read it. Everything
past that — the online audits, the three input kinds github_core does not collect, the compliance
bridge, fix mode, a second scanner — is a `Backlog` requirement below, not a non-goal (make-it-right
column). The gate between them and v0 is one fact: the plugin has to execute once before any of it
is real.

**Provenance markers.** Claims marked *observed* were measured on 2026-09-02; everything else is
*documented* from the sources named.

## Goals

| # | Name | Description |
| --- | --- | --- |
| 1 | Consume, Do Not Rebuild | Every finding on the grid is zizmor's, with zizmor's ID, severity, confidence and location; the plugin authors no audit. |
| 2 | Offline And Derived | The collector reads workflow YAML already on the grid and runs the pinned binary offline; no credential, no network, reproducible from grid state. |
| 3 | Provenance On Every Finding | Scanner, exact version, persona, audit ID, known-since and observed-at ride on each finding, and each run records which github_core collection it read. |
| 4 | Three States | Unevaluated workflows render as *not observed by this scanner*, never as clean. |
| 5 | Native Distribution | The binary arrives as the pinned PyPI wheel; pinning, SBOM, crypto-BOM and vulnerability alerts ride existing machinery, with the gaps named rather than papered. |
| 6 | Legible Runs | Every execution is a first-class node with its own page; every finding drills into its own page. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-zizmor-binary | [The Pinned Binary](#the-pinned-binary) | Proposed | Exact PyPI pin; honest `[fips]` declaration; SBOM/alert channels named with their gaps |
| req-zizmor-collector | [Offline Derived Collector](#offline-derived-collector) | Proposed | Materialize `raw_yaml` per repo → `zizmor --offline --format json-v1` → GRIFT batch |
| req-zizmor-trigger | [Own Schedule, With A Staleness Guard](#own-schedule-with-a-staleness-guard) | Proposed | Seeded `schedule` node + boot-record first light; a run names the github_core collection it read and skips while one is active |
| req-zizmor-finding | [The Finding Node](#the-finding-node) | Proposed | `zizmor__finding` with provenance fields; edges to run, workflow and job. A compliance-level node in disguise — see the implementation note |
| req-zizmor-run | [Runs Are First-Class](#runs-are-first-class) | Proposed | One `zizmor__run` per execution; findings and scanned workflows hang off it; unevaluated = not observed by this scanner |
| req-zizmor-pages | [Landing, Run And Finding Pages](#landing-run-and-finding-pages) | Proposed | `/zizmor`, `/zizmor/runs/<id>`, `/zizmor/findings/<id>`; every table cell drills in |
| req-zizmor-online-audits | [Online Audits, Aligned To The Graph](#online-audits-aligned-to-the-graph) | Backlog | The four API-backed audits via github_core's auth seam; findings land on `github_action`/`USES_ACTION`; FIPS accounting becomes real |
| req-zizmor-input-kinds | [Actions, Dependabot And Pre-commit Inputs](#actions-dependabot-and-pre-commit-inputs) | Backlog | Pulled by github_core collecting three more file kinds |
| req-zizmor-persona | [Persona As Configuration](#persona-as-configuration) | Backlog | `pedantic` / `auditor` selectable per boot record |
| req-zizmor-compliance-bridge | [Compliance Bridge](#compliance-bridge) | Backlog | Finding → compliance requirement edges (CICD-SEC-n, SLSA) via compliance_core |
| req-zizmor-fix-mode | [Fixes As Patches](#fixes-as-patches) | Backlog | zizmor's safe fixes surfaced as agent-applicable patches |
| req-zizmor-second-scanner | [A Second Scanner In The Same Shape](#a-second-scanner-in-the-same-shape) | Backlog | poutine / CodeQL Actions pack; scanner disagreement as data |

### The Pinned Binary
----
RID: `req-zizmor-binary`
Status: `Proposed`

The plugin's only Tier-0 runtime dependency is `zizmor==<exact>` from PyPI. The collector locates the
installed binary through the environment (the wheel installs it on `PATH` as `zizmor`), reads its
version at run time, and refuses to run when that version differs from the pinned one. The manifest
`[fips]` table declares `uses-nonvalidated`, naming `rust-ring` and `rust-aws-lc-rs`, with the
offline-invocation reason. The plugin records the verified upstream publisher identity and the state
of each supply-chain channel below.

#### Implementation

**Adopt native distribution — never roll our own package distribution.** zizmor is on PyPI as a
wheel (*observed* 2026-09-02: `zizmor 1.30.0`, `requires_python >=3.10`; manylinux x86_64 / aarch64
/ armv7l, musllinux, macOS x86_64 / arm64). Each wheel is one static binary
(`zizmor-1.30.0.data/scripts/zizmor`, 26.6 MB on manylinux_2_28 x86_64), a `RECORD`, the MIT license
— **and its own CycloneDX SBOM** (`zizmor-1.30.0.dist-info/sboms/zizmor.cyclonedx.json`, 400 KB,
PEP 770, 328 components) listing every Rust crate compiled in.

```toml
dependencies = ["zizmor==1.30.0"]
```

| Concern | How it is handled | Status |
| --- | --- | --- |
| **Pinning** | Exact `==` in `pyproject.toml`; `uv.lock` in the plugin repo; the boot record's install pin (`zizmor-tap@vX.Y.Z`) pins the closure. No cargo, no GitHub-release download, no vendored binary, no checksum we author twice. | Existing |
| **Release SBOM** | `plugin-release-sbom.yml` runs pinned Syft over our wheel: `zizmor` appears as `pkg:pypi/zizmor@1.30.0`. | Existing |
| **Crate-level SBOM** | *Verified 2026-09-02 (observed):* the pinned Syft (`anchore/syft:v1.51.0`) does **not** ingest the embedded PEP 770 document — a directory scan of the unpacked wheel yields `pkg:pypi/zizmor@1.30.0`, six file entries and zero crate components, with and without `--select-catalogers +sbom-cataloger` (upstream: anchore/syft#737, open). The release lane therefore merges the embedded document explicitly as a nested component keyed to the exact wheel version — a one-time addition to `scripts/sbom/plugin_release.py` (tap#302). | Verified: not ingested → the release lane merges it |
| **Deployed closure** | The wheel installs at boot into the container venv (git-source install of the plugin pulls its deps). The boot record is the BOM of what actually runs. | Existing |
| **Crypto BOM / FIPS** | *Observed* in zizmor's `Cargo.lock`: `ring`, `aws-lc-rs`/`aws-lc-sys`, `rustls`, `rustls-platform-verifier`, `reqwest` — two non-OpenSSL providers, for TLS. AWS-LC has a FIPS 140-3 validated module, but it ships as a separate crate (`aws-lc-fips-sys`, selected by aws-lc-rs's `fips` feature); zizmor's `Cargo.toml` pulls `reqwest` with default features, i.e. the non-FIPS `aws-lc-sys`, and `ring` (never validated) is linked too. **The wheel's binary is not the validated module even though the library it embeds is validatable.** Manifest: `[fips] status = "uses-nonvalidated"`, `providers = ["rust-ring", "rust-aws-lc-rs"]`, `reason = "TLS for zizmor's online audits; this plugin invokes zizmor --offline, so the providers are present but never execute a security operation. A FIPS deployment waives per plugin in the boot profile."` A false `compatible` fails conformance; the honest declaration passes (`req-fips-crypto-bom-conformance-2`). Whether `validate_plugin`'s `scan_plugin` fingerprints a *declared dependency's* wheel is unverified (tap#302). | Declared; scan reach to verify |
| **Vulnerability notification** | (a) Dependabot alerts are enabled on every plugin repo (*observed*: 204 on `vulnerability-alerts`), so a GitHub Advisory against PyPI `zizmor` alerts the repo. (b) Renovate has `pep621` + `osvVulnerabilityAlerts` enabled but `RENOVATE_REPOSITORIES` names tap alone — plugin repos get no bump PRs (tap#303, under the plugin-baseline issue #269). zizmor releases every 2–3 weeks (*observed*: v1.26.1 → v1.30.0, 2026-06-21 → 2026-08-30); the bump PR is the release notification. (c) Trivy nightly scans images; a boot-installed wheel is not in the image — the boot-record BOM against OSV is the closing move, parked with the dependency-defense thread. | (a) existing; (b) tap#303; (c) parked |
| **Attestation** | The plugin's own wheel is attested by the release lane (SLSA provenance + SBOM predicates). zizmor's PyPI wheels are published via Trusted Publishing from `zizmorcore/zizmor` — verify on the first pin bump and record the accepted upstream identity here. | Verify once |

Rejected shapes: fetching the GitHub release binary at install (an unpinned network fetch in the boot
path plus a hand-authored checksum — presence, not correctness); baking the binary into the tap-web
image (core carrying a product's dependency, 27 MB in every instance that never runs it).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-binary-1 | Exact Pin | Proposed | `pyproject.toml` pins `zizmor==X.Y.Z`; `uv.lock` resolves it; `validate_plugin --strict` passes with the honest `[fips]` declaration. | |
| req-zizmor-binary-2 | Version Stamped | Proposed | Every run and finding carries the binary's reported version (`zizmor --version`), which equals the pinned version, else the collector aborts before scanning. | The binary that ran is the one that was pinned. |
| req-zizmor-binary-3 | SBOM Presence | Proposed | The plugin's release SBOM lists `pkg:pypi/zizmor@X.Y.Z` and carries the embedded crate-level document as a nested component. | |
| req-zizmor-binary-4 | Alert Channel Proven | Proposed | A Dependabot alert or Renovate PR fires for a zizmor advisory or release on the plugin repo — demonstrated once with a real bump, not assumed from configuration. | The Renovate half is tap#303. |

### Offline Derived Collector
----
RID: `req-zizmor-collector`
Status: `Proposed`

`ZizmorCollector` reads, per repository on the grid, each `GithubWorkflow.configuration.raw_yaml`,
materializes them into a scratch `.github/workflows/<path>` tree, invokes
`zizmor --offline --format json-v1 --persona regular` over it, and lands one GRIFT batch: the run
node, the findings, edges from each finding to its workflow (and job when the finding's location
names one), and the run's `SCANNED` edges with per-workflow outcomes. The scratch tree lives for the
duration of one subprocess call and is removed on exit. The collector never contacts a network and
declares no `required_secrets`. Manifest `depends_on` names `github_core` (Tier 1: it imports
github_core's models to resolve workflow and job endpoints).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-collector-1 | Pure Function Of Grid State | Proposed | Two runs over unchanged workflow rows with the same pinned binary produce identical finding sets; no network access is attempted (asserted with egress blocked in the test). | |
| req-zizmor-collector-2 | Our Org, First Light | Proposed | Against the viz session's collected org (75 workflows, *observed*), the collector completes and lands findings whose audit IDs appear in zizmor's documented audit list. | The gate for every Backlog requirement. |
| req-zizmor-collector-3 | Scratch Is Ephemeral | Proposed | After a run, no materialized workflow file remains on disk; a failed run leaves nothing either. | |

### Own Schedule, With A Staleness Guard
----
RID: `req-zizmor-trigger`
Status: `Proposed`

The collector runs on its **own schedule**: this plugin's GRIFT seeds a tap_cares `schedule` node
targeting `zizmor:zizmor` (default cron `23 */6 * * *`, off the hour; user-editable, since
`Schedule` is user-creatable per `req-tap-cares-scheduler-model-6`). The boot record also carries a
`fire-collector` step for `zizmor:zizmor` after `github_core:github_core`, so first light happens at
boot. Because the schedule is independent of github_core's collection, the run guards its own
freshness: it records the github_core `collection_job` (and batch) whose rows it read, and a fire
that finds a github_core collection job active is finalized as *skipped* with that reason rather than
scanning rows mid-write.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-trigger-1 | Seeded Schedule Fires | Proposed | After seeding, the schedule node exists with the default cron, and a tick at a matching slot creates a `ScheduleFire` that runs the collector. | |
| req-zizmor-trigger-2 | Fires From The Record | Proposed | A boot record's `fire-collector` step for `zizmor:zizmor`, ordered after `github_core:github_core`, runs and reports counts in the boot record. | Tier-2 data order stays profile-explicit. |
| req-zizmor-trigger-3 | Skips While Upstream Writes | Proposed | With a github_core collection job active, a scheduled fire finalizes as skipped naming that job; no run node is created. | |
| req-zizmor-trigger-4 | Source Recorded | Proposed | Every run names the github_core collection job it read. | Provenance, not only timing. |

### The Finding Node
----
RID: `req-zizmor-finding`
Status: `Proposed`

A typed node `zizmor__finding` (BaseModel, table-prefixed per type ownership) carrying: `audit_id`,
`audit_url`, `severity`, `confidence`, `persona`, `scanner_version`, `summary`, `location` (path,
row, column, symbolic route, job key, step index, and the `feature` text as reported), `fixes`
(zizmor's list of title + disposition safe/unsafe), the raw finding JSON, `known_since` (first
observation) and `observed_at`. Edges: `PRODUCED__zizmor` from its run; `FLAGS_WORKFLOW__zizmor`
(finding → `github_workflow`) always; `FLAGS_JOB__zizmor` (finding → `workflow_job`) when the
location resolves to a declared job. Naming follows the vocabulary corpus's edge rules and the
SPDX-first check.

#### Implementation

**A compliance-level node in disguise (George, 2026-09-02).** `zizmor__finding` is a scanner's
assertion about an asset — the same shape compliance_core's `finding` bridges to a requirement. For
the make-it-work phase a scanner-shaped node is the decision. The implementation records, in the
model's docstring and its domain article, that surfacing it *beside other findings* (poutine, CodeQL,
git-serious's conjunction findings, compliance findings) is an open design that
`req-zizmor-compliance-bridge` and `req-zizmor-second-scanner` will force — and it must not paint
itself into a shape only zizmor can occupy: no zizmor-only field names where a scanner-neutral one
exists (`severity`, `confidence`, `scanner_version`, `location`, `fixes` are neutral; `audit_id` is
zizmor's vocabulary and is kept as the neutral `rule_id` with `audit_id` in tags if the second scanner
arrives).

**Endpoints, checked against the corpus (`spec-github-core-vocabulary.md`) and the grid as
collected 2026-09-02:**

| Endpoint | State | v0 handling |
| --- | --- | --- |
| `github_workflow` | built, on the grid | `FLAGS_WORKFLOW__zizmor` always |
| `workflow_job` | built (self tier) | `FLAGS_JOB__zizmor` when the location resolves |
| `github_action` + `USES_ACTION` (`{pin_kind, pinned_sha, declared_ref, resolves_to_fork}`) | corpus: self tier, proposed, **not built** | Nine audits are about `uses:` references (`unpinned-uses`, `stale-action-refs`, `ref-confusion`, `impostor-commit`, `known-vulnerable-actions`, `typosquat-uses`, `archived-uses`, `superfluous-actions`, `forbidden-uses`). Attaching them to the workflow alone loses the join the conjunction feature needs. Not zizmor's to mint — github_core's. v0 carries the `uses` string in `location`; `FLAGS_ACTION__zizmor` is added the day `github_action` lands. File the github_core issue on first light, with finding counts per audit as the evidence. |
| `actions_secret` | proposed, **not built** | Secrets audits name secrets by string in `tags` until the node exists. |
| step | corpus ruling: a field, not a node | zizmor reports step indices; the finding keeps them in `location`. A finding needs the job as its endpoint; the ruling holds. |

zizmor exposes **no parse** — no dump or collect-only mode; its model crates are Rust-only — so the
grid's shape stays github_core's parse. Vocabulary comes from collection, findings from scanners;
never a shape derived from the absence of a finding.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-finding-1 | Provenance Complete | Proposed | Every landed finding has non-empty `audit_id`, `severity`, `confidence`, `scanner_version` and `observed_at`, an edge from its run, and an edge to exactly one workflow. | |
| req-zizmor-finding-2 | Job Resolution Honest | Proposed | A finding whose location names a job that exists on the grid gets `FLAGS_JOB`; one whose job cannot be resolved gets no job edge and records why in `tags`. | |
| req-zizmor-finding-3 | Neutral Shape Recorded | Proposed | The model docstring and domain article carry the compliance-node note and name the two Backlog requirements that will force the design. | |

### Runs Are First-Class
----
RID: `req-zizmor-run`
Status: `Proposed`

Each collector execution lands one `zizmor__run` node: scanner version, persona, audit set,
started/finished, the github_core collection job it read, the repositories and workflows it covered,
per-workflow outcome (`evaluated` / `parse-failed` / `skipped`), and finding counts by audit and
severity. Findings hang off the run that produced them (`PRODUCED__zizmor`, run → finding) and the
run records what it scanned (`SCANNED__zizmor`, run → workflow, with the outcome on the edge). A
workflow with no `SCANNED` edge from the current run renders as *not observed by this scanner* in
every consumer. The four online-only audits are recorded as `skipped` on every v0 run.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-run-1 | Not Scanned Is Visible | Proposed | Remove one workflow's `SCANNED` edge from the current run; the findings table shows it as *not observed by this scanner*, not as clean. | The three-states rule, mechanized. |
| req-zizmor-run-2 | Counts Match | Proposed | A run's recorded finding counts equal the findings reachable from it by `PRODUCED`; a mismatch fails the collector's own post-check. | Presence is not correctness. |

### Landing, Run And Finding Pages
----
RID: `req-zizmor-pages`
Status: `Proposed`

Three pages, built with the add-page / add-panel skills, all Gryphon-backed, shipped in
`grift/pages.grift.json`:

- **Landing `/zizmor`** — `zizmor_about` (what zizmor is and does, the audit families, the scanner
  version as observed from the binary, the persona in use, the offline posture and the four audits it
  therefore skips), `zizmor_findings_table` (latest run, filterable by audit and severity, with
  not-observed rows), and `zizmor_runs_table` (recent runs with counts and outcome).
- **Run `/zizmor/runs/<id>`** — `zizmor_run_summary` (version, persona, source collection, coverage:
  repositories and workflows evaluated / parse-failed / skipped, counts by audit and severity,
  duration) and `zizmor_run_detail` (every finding the run produced, every workflow it scanned with
  its outcome).
- **Finding `/zizmor/findings/<id>`** — `zizmor_finding_detail`: audit and its documentation link,
  severity, confidence, persona, the location with `feature` text, available fixes, the workflow and
  job it flags with links onto their github_core pages, and the run that produced it.

Every finding cell in any table links to its finding page; every run cell links to its run page.
git-serious's lint-findings surface mounts `zizmor_findings_table` and inherits the links.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-pages-1 | Drill-In Works | Proposed | From the landing page, one click reaches a run page and one click reaches a finding page; from the run page, one click reaches any of its findings. | |
| req-zizmor-pages-2 | Version Is Observed | Proposed | The about panel's scanner version is read from the binary at run time and recorded on the run, never typed into the page. | Derive, don't declare. |

### Online Audits, Aligned To The Graph
----
RID: `req-zizmor-online-audits`
Status: `Backlog`

The four audits zizmor cannot run offline — `impostor-commit`, `known-vulnerable-actions`,
`ref-confusion`, `typosquat-uses` (the prior-art survey also flagged `archived-uses`; verify on first
run) — run with a token through **github_core's auth seam, never a second envelope**. Their findings
are about action references, so they must land on nodes and edges that exist on the grid by then:
`github_action` and `USES_ACTION` carrying `pin_kind`, `pinned_sha`, `declared_ref`,
`resolves_to_fork` — an impostor-commit finding points at the exact reference whose SHA does not
belong to the canonical repository, and `known-vulnerable-actions` attaches advisory identifiers to
the action version. Depends on: `github_action` built in github_core; `req-zizmor-collector-2`
observed. **FIPS becomes load-bearing here:** online means TLS executes inside the binary, so the
`uses-nonvalidated` declaration stops being "present but unreached"; a FIPS profile then needs a
`fips`-feature build of zizmor (not what PyPI ships) or the operator's per-plugin waiver.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-online-audits-1 | Lands On The Reference | Backlog | An impostor-commit finding has an edge to the `github_action` node and the `USES_ACTION` edge it concerns; none lands on the workflow alone. | |
| req-zizmor-online-audits-2 | One Credential | Backlog | The online run resolves its token through github_core's seam; the plugin declares no `required_secrets` of its own. | |

### Actions, Dependabot And Pre-commit Inputs
----
RID: `req-zizmor-input-kinds`
Status: `Backlog`

zizmor audits four input kinds; github_core collects one. When github_core fetches `action.yml` (the
defining side of `github_action`), `.github/dependabot.yml` and pre-commit config — the same GraphQL
config fetch, more paths — the collector materializes them beside the workflows, and the Dependabot
audits (`dependabot-cooldown`, `dependabot-execution`) and action audits gain inputs. Depends on:
github_core collection additions (friends tier).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-input-kinds-1 | Dependabot Audited | Backlog | A repository with a Dependabot config on the grid receives `dependabot-*` findings attached to that config's node. | |

### Persona As Configuration
----
RID: `req-zizmor-persona`
Status: `Backlog`

`pedantic` and `auditor` selectable per boot record (collector config), recorded on the run;
`regular` stays the default.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-persona-1 | Persona Recorded | Backlog | A run under `--persona auditor` records `auditor` and its findings carry it. | |

### Compliance Bridge
----
RID: `req-zizmor-compliance-bridge`
Status: `Backlog`

An edge from a finding to the compliance requirement(s) it evidences — OWASP CICD-SEC-n, SLSA
Source/Build, OSPS Baseline — reusing compliance_core's vocabulary rather than minting a rival. The
prior-art survey's §3.7 / §3.10 mapping is the seed data. This is what makes a finding an attestation
input rather than a lint line, and the first requirement that forces the neutral-shape question.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-compliance-bridge-1 | Tagged Findings Bridge | Backlog | A `template-injection` finding carries an edge to the CICD-SEC-4 requirement node when compliance_core's catalog holds it. | |

### Fixes As Patches
----
RID: `req-zizmor-fix-mode`
Status: `Backlog`

zizmor reports `fixes` per finding and can apply them. Surface a safe fix as a patch an agent can
propose against the repository — read-only from the grid's side; the write is a pull request the
operator's own tooling opens. Depends on: the agent-operable review surface (git-serious).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-zizmor-fix-mode-1 | Safe Fix Rendered | Backlog | A finding with a safe fix renders the patch text; the plugin never writes to the forge. | |

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

## Model catalog

| Model | Entity type | Category | Rationale |
| --- | --- | --- | --- |
| `ZizmorFinding` | `zizmor__finding` | finding | The unit zizmor emits, with provenance; a compliance-level node in disguise (see `req-zizmor-finding`). |
| `ZizmorRun` | `zizmor__run` | run | One per execution: version, persona, source collection, coverage, counts; the page's subject and the thing that makes absence honest. |

## Edge types

| Edge | From → To | Properties | Rationale |
| --- | --- | --- | --- |
| `PRODUCED__zizmor` | run → finding | — | Which execution produced the finding. |
| `SCANNED__zizmor` | run → `github_workflow` | `{outcome: evaluated \| parse-failed \| skipped}` | Coverage; the absence of this edge is the not-observed state. |
| `FLAGS_WORKFLOW__zizmor` | finding → `github_workflow` | — | Every finding locates a workflow file. |
| `FLAGS_JOB__zizmor` | finding → `workflow_job` | — | When the location names a declared job; the conjunction join. |

## Reference data

No domain seed data — findings are collected, never seeded. Two GRIFT documents ship: `grift/pages.grift.json`
(the three pages, six panel types and their searches) and `grift/schedule.grift.json` (the collector's
`schedule` node). A fixture pack of zizmor `json-v1` output over the plugin repo's own workflows drives
the tests.

## Icons

Two `currentColor` glyphs in `static/zizmor/icons/`: `zizmor-finding` and `zizmor-run`. Workflow and
job icons on the far side of the edges are github_core's.
