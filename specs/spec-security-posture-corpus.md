# Security Posture Corpus Specification

## Philosophy

TAP needs a durable security-assurance memory, not a one-off vulnerability scan. Generic scanners are useful, but they answer only part of the question: "does this code resemble a known bad pattern?" TAP also needs to answer the inverse question: **which security controls do we expect this system to satisfy, what evidence says it does or does not, and where has TAP deliberately accepted a gap?**

The security posture corpus is the repo-owned answer to that question. It is a top-level `security/` directory containing machine-readable controls, schemas, named reports, and optional helper scripts. It is not a Django app, not runtime product code, and not an autonomous patching mechanism. It is assurance material: explicit, inspectable, versioned, and accretive.

The core doctrine is:

> Security review should evaluate TAP against an explicit control ledger. Every finding maps to a control, an authority, TAP-specific evidence, a status, and a next verification step. Patches come later, by explicit request.

This intentionally reverses the usual AI vulnerability-scanner loop. Instead of "find a vulnerability, invent a patch," TAP starts with "state the expected posture, collect evidence, identify drift." Over time the corpus becomes a living map of TAP's security obligations and best-practice candidates across Django, Python, OWASP, database usage, identity, browser posture, and TAP-specific invariants.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Evidence First | Security reviews produce control-mapped evidence and findings, not automatic patches. |
| 2. | Durable Ledger | Security expectations live in versioned repo artifacts that outlast any one agent session. |
| 3. | Domain Separation | Controls are organized by security domain so specialist passes can work without inventing separate rubrics. |
| 4. | Spec Reconciliation | TAP-specific controls are reconciled against existing specs before reports are generated or baselines replaced. |
| 5. | Repeatable Reports | Reviews emit both machine-readable and human-readable reports with stable status and severity vocabulary. |
| 6. | Refreshable Controls | External best-practice controls are periodically refreshed against current upstream sources instead of being treated as frozen mirrors. |

## Prior Art

This spec follows established assurance patterns rather than inventing a scanner from scratch:

- **Django deployment checks** - `manage.py check --deploy` is a framework-provided posture check for production settings.
- **OWASP ASVS** - a verification standard for application security controls, useful as a control ledger and evidence map rather than a patch generator, including application-level third-party component inventory and remediation expectations.
- **NIST SSDF** - a secure software development framework that explicitly covers monitoring public and user-reported vulnerabilities in software and third-party components.
- **Bandit** - Python AST-based detection for common Python security issues; useful as an optional evidence source, not the source of TAP policy.
- **Semgrep** - custom rule support for repository-specific secure-coding checks; useful later when TAP controls deserve deterministic pattern checks.
- **HTTP Observatory** - HTTP response-header posture evaluation; useful as a model for deployed-surface evidence.
- **pip-audit** - Python dependency vulnerability auditing; useful as a separate dependency-risk evidence source.

These tools are inputs and inspirations. TAP's corpus owns the TAP-specific control map, obligations, accepted risks, and report contract.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-sec-corpus-root | [Security Directory](#security-directory) | Proposed | Top-level `security/` owns controls, schemas, reports, and optional scripts |
| req-sec-corpus-controls | [Control Ledger](#control-ledger) | Proposed | Domain-separated JSON controls are the canonical review input |
| req-sec-corpus-evidence-modes | [Evidence Modes](#evidence-modes) | Proposed | Controls declare whether static, dynamic, manual, or external evidence is needed |
| req-sec-corpus-obligations | [Obligation Levels](#obligation-levels) | Proposed | Distinguish TAP-required controls from advisory best-practice candidates |
| req-sec-corpus-spec-sweep | [Spec Sweep Reconciliation](#spec-sweep-reconciliation) | Proposed | Reports sweep specs for TAP security requirements and flag missing/diverged controls before replacing baselines |
| req-sec-corpus-schemas | [Schema-Validated Formats](#schema-validated-formats) | Proposed | Every structured security artifact has a JSON Schema and validates loud |
| req-sec-corpus-reports | [Review Reports](#review-reports) | Proposed | JSON is canonical; Markdown is generated or companion human-readable output |
| req-sec-corpus-severity | [Severity Scale](#severity-scale) | Proposed | Findings use one low/medium/high/critical impact heuristic |
| req-sec-corpus-supply-chain | [Supply Chain Controls](#supply-chain-controls) | Proposed | Dependency inventory, vulnerability monitoring, remediation timing, and provenance are first-class controls |
| req-sec-corpus-workflow | [Review Workflow](#review-workflow) | Proposed | Specialist phases share one ledger; multi-agent execution is optional |
| req-sec-corpus-refresh | [Control Refresh Workflow](#control-refresh-workflow) | Proposed | External controls can be refreshed independently against current upstream sources |
| req-sec-corpus-scripts | [Lightweight Automation](#lightweight-automation) | Proposed | v0 uses stdlib/repo tools first; external scanners are optional adapters |

---

### Security Directory
----
RID: `req-sec-corpus-root`  

Status: `Proposed`

Security posture assurance artifacts live in a top-level `security/` directory at the repository root.

#### Implementation

The directory shape is:

```text
security/
  controls/
    django.json
    python.json
    postgres.json
    tap-specific.json
    # Later domains:
    owasp-asvs.json
    auth-oidc.json
    supply-chain.json
  schemas/
    security-control.schema.json
    security-report.schema.json
  reports/
    <date-or-review-id>.<llm>.<json|md>
  scripts/
    <optional helper scripts>
```

- `security/` is assurance material, not runtime application code.
- `controls/` is the canonical control ledger.
- External-domain files are maintained as citations and TAP-applicability summaries, not wholesale mirrors of upstream standards.
- v0 starts with `django.json`, `python.json`, `postgres.json`, and `tap-specific.json`. These are relatively tractable, directly applicable to the current codebase, and mostly support static code/config review.
- `supply-chain.json` is designed here but deferred until TAP starts building the real CI/CD environment, because supply-chain controls need recurring jobs, dependency inventory, alerting, and remediation workflow to be meaningful.
- `schemas/` validates every structured security artifact introduced by this spec.
- `reports/` holds committed, named posture reviews and baselines only.
- Report filenames include the responsible LLM/agent owner before the extension, for example `2026-06-26-static-baseline.codex.json` and `2026-06-26-static-baseline.claude.md`.
- `scripts/` is optional and contains helper automation only after the manual workflow has taught the shape.
- Routine local runs may write scratch output outside committed reports, but named baselines intended to become shared project memory are committed under `security/reports/`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sec-corpus-root-1 | Top-Level Home | Proposed | The corpus lives at repository-root `security/`, not inside a Django app or plugin. | |
| req-sec-corpus-root-2 | Domain Controls | Proposed | `security/controls/` contains separate domain files; v0 starts with Django, Python, Postgres, and TAP-specific controls. | |
| req-sec-corpus-root-3 | Reports Are Selective | Proposed | Only named reviews and baselines are committed under `security/reports/`; routine local scratch output is not treated as project memory. | |
| req-sec-corpus-root-4 | Report Owner In Filename | Proposed | Committed report filenames include the LLM/agent owner as `<reportname>.<llm>.<json|md>`. | |

---

### Control Ledger
----
RID: `req-sec-corpus-controls`  

Status: `Proposed`

A security control is a machine-readable statement of expected or recommended posture, with authority, scope, review guidance, and evidence hooks.

#### Implementation

Each control records, at minimum:

- stable `id`
- `title`
- `domain`
- `obligation` (`required`, `recommended`, `candidate`, or `accepted-risk`)
- `authority` references, which may include TAP specs, Django docs, OWASP ASVS identifiers, provider docs, or internal doctrine
- `statement`
- `rationale`
- `scope`
- `evidence_modes`, one or more of `static`, `dynamic`, `manual`, or `external`
- `evidence_guidance`
- `review_guidance`
- optional `automated_checks`
- optional `related_controls`
- optional `upstream_version` for external standards, framework versions, or provider guidance
- optional `last_reviewed_at`
- optional `refresh_guidance`

Control IDs are stable and domain-prefixed, for example:

- `django.deploy.debug-disabled`
- `python.exec.no-shell-unsafe`
- `owasp-asvs.auth.session-cookie-secure`
- `supply-chain.monitoring.sca-run-recurring`
- `postgres.connection.search-path-controlled`
- `auth-oidc.google.hd-claim-required`
- `tap.auth.no-user-none-service-boundary`

The control ledger is not a scanner output. It is the input to review.

External-domain controls (`django.json`, `python.json`, `owasp-asvs.json`, and similar) should avoid copying large upstream standards into TAP. They should capture the TAP-applicable control summary, cite the upstream authority precisely, record the upstream version or documentation date when known, and describe how to refresh the control. The durable TAP-specific decisions still live in `tap-specific.json`; the external files are the current best-practice lens used to evaluate TAP against a moving world.

Supply-chain controls live in `supply-chain.json` rather than being folded into generic Python checks. Python package vulnerability scanning is one evidence source, but the domain also covers component inventory, vulnerability-source monitoring, remediation timeframes, dependency provenance, and dependency-confusion risk. This domain is intentionally deferred from the first operational slice until CI/CD work makes recurring monitoring and remediation workflow real.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sec-corpus-controls-1 | Stable IDs | Proposed | Every control has a stable, domain-prefixed `id`. | |
| req-sec-corpus-controls-2 | Authority Required | Proposed | Every control cites at least one authority or explicit TAP accepted-risk decision. | |
| req-sec-corpus-controls-3 | Evidence Guidance | Proposed | Every control describes what evidence a reviewer should collect. | |
| req-sec-corpus-controls-4 | Ledger Is Input | Proposed | Review reports reference controls; reports do not become the canonical definition of the controls themselves. | |
| req-sec-corpus-controls-5 | External Controls Cite, Do Not Mirror | Proposed | External-domain controls summarize TAP-applicable expectations and cite upstream sources rather than copying whole upstream standards. | |
| req-sec-corpus-controls-6 | Evidence Mode Declared | Proposed | Every control declares whether it can be evaluated statically, dynamically, manually, externally, or by a combination. | |

---

### Obligation Levels
----
RID: `req-sec-corpus-obligations`  

Status: `Proposed`

The corpus distinguishes binding TAP requirements from external best-practice candidates and accepted risks.

#### Implementation

`obligation` values:

| Obligation | Meaning |
| --- | --- |
| `required` | TAP has adopted this as binding policy, usually by a TAP spec or explicit security doctrine. A failing required control is TAP non-conformance. |
| `recommended` | A recognized external or internal best practice that TAP should consider or usually follow, but has not yet made binding everywhere. |
| `candidate` | A newly identified or experimental control under evaluation. It should gather evidence without implying policy failure. |
| `accepted-risk` | A known gap or open posture TAP has deliberately accepted. Reports should verify the risk remains bounded as described. |

Promotion is explicit:

- An external best practice becomes `required` only when a TAP spec, doctrine, or accepted design decision adopts it.
- A `recommended` or `candidate` control may produce a report finding, but the finding is framed as a gap, decision point, or hardening opportunity unless it also violates a TAP requirement.
- An `accepted-risk` control is not a free pass: reports check whether the implementation still matches the accepted-risk boundary.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sec-corpus-obligations-1 | Required Means Binding | Proposed | `required` controls cite TAP authority and failed required controls are reported as non-conformance. | |
| req-sec-corpus-obligations-2 | Best Practice Is Distinct | Proposed | External best-practice controls can be represented without automatically becoming TAP law. | |
| req-sec-corpus-obligations-3 | Accepted Risks Are Checked | Proposed | `accepted-risk` controls are reviewed to ensure the actual system still matches the stated boundary. | |

---

### Evidence Modes
----
RID: `req-sec-corpus-evidence-modes`  

Status: `Proposed`

Controls declare what kind of evidence can evaluate them.

#### Implementation

`evidence_modes` values:

| Mode | Meaning |
| --- | --- |
| `static` | Evidence can be gathered from source code, configuration, lockfiles, specs, schemas, templates, or other on-disk artifacts without running TAP. |
| `dynamic` | Evidence requires a running TAP instance, live HTTP requests, browser interaction, a database connection, or runtime behavior. |
| `manual` | Evidence requires human/agent judgment over architecture, design intent, accepted risk, or source interpretation that is not reducible to a deterministic check yet. |
| `external` | Evidence requires current external sources or services, such as upstream security docs, vulnerability feeds, package indexes, provider metadata, or deployed HTTP header observations. |

v0 review is **static-first**:

- The first operational control files should prioritize controls that can be evaluated statically against the repository: Django settings/config, Python code patterns, Postgres/database usage, and TAP-specific spec/code invariants.
- A static review may report a dynamic-only or external-only control as `unknown`, `deferred-by-spec`, or `recommended-gap`, but it must not mark that control `pass` unless the required evidence mode was actually exercised.
- Controls may list multiple modes. For example, secure-cookie settings can be checked statically in Django settings and dynamically through response behavior in a running instance.
- Dynamic analysis is a planned expansion: once a reliable local/customer-like runtime exists, reports should add running-instance checks for HTTP headers, session/cookie behavior, auth redirects, CSRF behavior, database runtime settings, and deployed posture.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sec-corpus-evidence-modes-1 | Modes Declared | Proposed | Every control declares one or more evidence modes. | |
| req-sec-corpus-evidence-modes-2 | Static First | Proposed | The first operational slice prioritizes statically evaluable controls. | |
| req-sec-corpus-evidence-modes-3 | No Unearned Pass | Proposed | A report does not mark a control `pass` without collecting evidence for the modes required by that control. | |
| req-sec-corpus-evidence-modes-4 | Dynamic Planned | Proposed | Dynamic analysis is represented in control metadata even when v0 reviews do not run it yet. | |

---

### Spec Sweep Reconciliation
----
RID: `req-sec-corpus-spec-sweep`  

Status: `Proposed`

Before a security report is finalized or a TAP-specific control baseline is replaced, the review process sweeps existing specs for security-relevant requirements and reconciles them against `security/controls/tap-specific.json`.

#### Implementation

The sweep reads security-relevant TAP specs and requirement tables, including at minimum:

- `specs/spec-security-posture.md`
- `specs/spec-tap-boot-v0.md`
- `tap_auth/specs/spec-tap-auth-v0.md`
- `tap_grid/specs/spec-grid-security.md`
- `tap_web/specs/spec-web-panel-security.md`
- any spec whose title, RID, notes, or prose references auth, authorization, security, secrets, CSRF, XSS, OIDC, boot trust, deployment posture, audit, logging, raw SQL, or accepted risk

The sweep compares spec-derived requirements to `tap-specific.json` and reports:

- `missing-control`: a security-relevant TAP requirement has no corresponding TAP-specific control
- `diverged-control`: a TAP-specific control's statement, obligation, or authority no longer matches its source spec
- `orphan-control`: a TAP-specific control cites a TAP requirement that no longer exists or has been deprecated
- `promotion-candidate`: an external recommended/candidate control appears to have been adopted by a TAP spec and should become `required`
- `external-refresh-candidate`: an external standard, framework, or provider version appears newer than the control's recorded `upstream_version`
- `risk-boundary-drift`: an accepted-risk control no longer matches the bounded risk described in the spec

The report must surface reconciliation findings **before** replacing any committed report baseline or generated TAP-specific control snapshot. Replacement is explicit and inspectable; no report run silently rewrites the project's security memory.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sec-corpus-spec-sweep-1 | Specs Are Swept | Proposed | Security reports include a sweep of existing specs for TAP security requirements. | |
| req-sec-corpus-spec-sweep-2 | Missing Controls Flagged | Proposed | A TAP security requirement without a corresponding TAP-specific control is reported as `missing-control`. | |
| req-sec-corpus-spec-sweep-3 | Divergence Flagged | Proposed | Controls that no longer match cited TAP specs are reported before any baseline replacement. | |
| req-sec-corpus-spec-sweep-4 | No Silent Replacement | Proposed | Reports and generated snapshots are not silently overwritten when reconciliation findings exist. | |

---

### Schema-Validated Formats
----
RID: `req-sec-corpus-schemas`  

Status: `Proposed`

Every structured format introduced by the security corpus ships with a JSON Schema and validates loud.

#### Implementation

- Control files validate against `security/schemas/security-control.schema.json`.
- Report files validate against `security/schemas/security-report.schema.json`.
- Schema validation fails loud on unknown required structure, malformed authority references, invalid obligation/status values, duplicate control IDs, or invalid report finding statuses.
- The schemas are authored in the same implementation change that first creates the corresponding JSON artifacts.
- Loader and report-generation code validates before using or replacing any structured artifact.

This follows TAP's standing rule for new on-disk structured-data formats: no ad hoc unvalidated JSON.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sec-corpus-schemas-1 | Schemas Ship With JSON | Proposed | The first implementation of security JSON files includes corresponding JSON Schemas. | |
| req-sec-corpus-schemas-2 | Validate Loud | Proposed | Invalid control or report files fail loudly before review output is trusted. | |
| req-sec-corpus-schemas-3 | Duplicate IDs Rejected | Proposed | Duplicate control IDs across domain files are validation errors. | |

---

### Review Reports
----
RID: `req-sec-corpus-reports`  

Status: `Proposed`

Security reviews produce both machine-readable and human-readable output.

#### Implementation

JSON is canonical. Markdown is either generated from JSON or maintained as a companion human-readable report that cites the JSON report ID.

Each report records:

- report ID and timestamp
- report owner LLM/agent identifier, matching the filename owner segment
- model provider and concrete model name
- optional model/runtime metadata relevant to reproducibility, such as tool availability, browsing status, or review prompt/profile ID
- repository revision or working-tree status summary
- control set version or hash
- sources consulted
- spec-sweep reconciliation results
- findings, each mapped to a control ID
- evidence with file/line references, command outputs, or explicit "not checked" reasons
- status per finding
- severity where applicable
- next verification step

Report filenames use:

```text
security/reports/<reportname>.<llm>.<json|md>
```

The `<llm>` segment is a short stable owner label such as `codex`, `claude`, or another agreed agent identifier. The JSON body remains canonical and records the more precise model, for example provider `OpenAI` with model `GPT-5-Codex`, or provider `Anthropic` with the concrete Claude model used.

Two reports with the same `reportname`, repository revision, control-set hash, evidence modes, and review scope are expected to be comparable across LLM owners. Divergence is useful signal: it should be inspected as either a report-quality issue, an ambiguous control, insufficient evidence guidance, or a genuine judgment difference that should be made explicit.

Finding statuses:

| Status | Meaning |
| --- | --- |
| `pass` | Evidence supports the control. |
| `fail` | Evidence contradicts a required control or a recommended control being evaluated as a hardening failure. |
| `unknown` | Evidence is insufficient; the report names what remains to check. |
| `recommended-gap` | A recommended/candidate control is not met, but TAP has not adopted it as binding. |
| `accepted-risk` | The control is intentionally open and still matches its stated boundary. |
| `deferred-by-spec` | A gap is explicitly deferred by a TAP spec or roadmap non-goal. |

Severity is required for `fail` and `recommended-gap` findings, and optional for `unknown`, `accepted-risk`, and `deferred-by-spec` findings. Severity describes impact if the finding is exploited or materializes, not how embarrassing the missing control looks in isolation.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sec-corpus-reports-1 | JSON Canonical | Proposed | Machine-readable JSON is the canonical report format. | |
| req-sec-corpus-reports-2 | Markdown Available | Proposed | Every named review has human-readable Markdown output or a generated Markdown rendering path. | |
| req-sec-corpus-reports-3 | Findings Map To Controls | Proposed | Every finding references a control ID or a spec-sweep reconciliation item. | |
| req-sec-corpus-reports-4 | Unknown Is Explicit | Proposed | Unknowns are allowed only when the report states what evidence could resolve them. | |
| req-sec-corpus-reports-5 | Severity Required For Gaps | Proposed | `fail` and `recommended-gap` findings include a severity from the spec-defined scale. | |
| req-sec-corpus-reports-6 | LLM Metadata Required | Proposed | Every report records the owner LLM/agent label, model provider, and concrete model name. | |
| req-sec-corpus-reports-7 | Comparable Runs | Proposed | Reports with the same report name, repo revision, control-set hash, evidence modes, and scope can be compared across LLM owners. | |

---

### Severity Scale
----
RID: `req-sec-corpus-severity`  

Status: `Proposed`

Security findings use one coarse impact scale: `low`, `medium`, `high`, or `critical`.

#### Implementation

Severity is a human-impact heuristic based on the "blood pressure" of the people responsible for, using, or trusting the platform if the issue were exploited or materialized:

| Severity | Heuristic | Meaning |
| --- | --- | --- |
| `low` | A user, customer, or owner would be annoyed. | Local inconvenience, limited exposure, noisy but contained operational risk, or a defense-in-depth miss with little direct exploitability. |
| `medium` | A user, customer, or owner would be angry. | Meaningful security degradation, plausible misuse path, moderate data exposure, or a control failure that materially weakens a protected boundary. |
| `high` | A user, customer, or owner would be furious. | Serious compromise of authentication, authorization, sensitive data, integrity, or deployment safety for one important tenant, operator, instance, or workflow. |
| `critical` | Everyone relevant would be furious. | Broad or systemic compromise, unauthenticated administrative reach, credential or secret exposure at platform scale, multi-instance/customer blast radius, or a failure that destroys trust in TAP's security posture. |

Severity is related to, but distinct from, obligation:

- A failed `required` control is always a conformance failure, but its severity still depends on impact.
- A `recommended-gap` can be `high` or `critical` if the real exploit impact is high, even before TAP has promoted the control to `required`.
- A `low` required-control failure still needs fixing or explicit spec change; low severity does not make non-conformance acceptable.
- Where uncertainty is substantial, the finding should say what evidence would move the severity up or down.

This scale is intentionally lightweight for v0. If repeated reports show the heuristic is too coarse or inconsistent, TAP may replace it with a fuller likelihood/impact model in a later spec revision.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sec-corpus-severity-1 | Four-Level Scale | Proposed | Finding severity is one of `low`, `medium`, `high`, or `critical`. | |
| req-sec-corpus-severity-2 | Impact-Based | Proposed | Severity describes expected impact if exploited or materialized, not merely obligation level. | |
| req-sec-corpus-severity-3 | Obligation Distinct | Proposed | Reports distinguish conformance status from exploit/materialization impact. | |

---

### Supply Chain Controls
----
RID: `req-sec-corpus-supply-chain`  

Status: `Proposed`

Supply-chain vulnerability monitoring is a first-class security-control domain.

#### Implementation

Supply-chain controls are **specified now but deferred from the first operational slice**. They become active implementation work when TAP starts building its real CI/CD environment. The reason is practical: meaningful supply-chain assurance requires recurring execution, dependency inventory/SBOM handling, alert intake, and remediation workflow. A one-off local scan is useful evidence, but it is not supply-chain monitoring.

`security/controls/supply-chain.json` covers the controls required to know what TAP depends on, whether those dependencies have known vulnerabilities, whether vulnerable dependencies have breached remediation expectations, and whether dependencies come from expected sources.

The initial control cluster should include:

- `supply-chain.inventory.sbom-present` - maintain an inventory or SBOM of third-party components and transitive dependencies.
- `supply-chain.monitoring.vulnerability-sources` - monitor authoritative vulnerability sources for TAP's software and third-party components.
- `supply-chain.monitoring.sca-run-recurring` - run software composition analysis or equivalent dependency vulnerability checks on a recurring basis.
- `supply-chain.remediation.timeframes-defined` - define risk-based remediation timeframes for vulnerable dependencies and library updates.
- `supply-chain.remediation.no-breached-timeframes` - detect dependencies whose known vulnerabilities have exceeded the documented remediation timeframe.
- `supply-chain.provenance.expected-repositories` - verify dependencies are obtained from expected, trusted, maintained repositories.
- `supply-chain.provenance.dependency-confusion-guard` - detect or prevent dependency-confusion exposure.

Primary authorities:

- NIST SSDF SP 800-218, especially the vulnerability-response and third-party-component practices in `RV.1` and `PW.4`.
- OWASP ASVS 5.0, especially V15 controls for third-party component inventory, vulnerable component remediation, and trusted dependency sources.

When this domain is activated, the first useful implementation is likely a committed dependency inventory plus a recurring Python dependency vulnerability check over the locked environment. That is a thin slice, not the whole domain: SBOM generation, transitive provenance checks, dependency-confusion controls, and external alert ingestion can follow as separate controls and evidence sources.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sec-corpus-supply-chain-1 | First-Class Deferred Domain | Proposed | Supply-chain controls live in `security/controls/supply-chain.json`, not only as generic Python checks, but implementation is deferred until real CI/CD work. | |
| req-sec-corpus-supply-chain-2 | Monitoring Covered | Proposed | The domain includes recurring monitoring for known vulnerabilities in TAP dependencies. | |
| req-sec-corpus-supply-chain-3 | Inventory Covered | Proposed | The domain includes a component inventory or SBOM control. | |
| req-sec-corpus-supply-chain-4 | Remediation Covered | Proposed | The domain includes risk-based remediation timeframes and breached-timeframe detection. | |
| req-sec-corpus-supply-chain-5 | Provenance Covered | Proposed | The domain includes trusted-source and dependency-confusion controls. | |

---

### Review Workflow
----
RID: `req-sec-corpus-workflow`  

Status: `Proposed`

Security posture reviews follow a shared workflow so specialist passes remain consistent.

#### Implementation

The review process:

1. Read TAP context: `AGENTS.md`, `architecture.md`, active roadmap step, and relevant security/auth/boot/grid/web specs.
2. Load and validate the control ledger.
3. Run the spec sweep and reconcile `tap-specific.json`.
4. Check whether any external-domain controls are stale or need refresh against newer upstream sources.
5. Collect deterministic evidence where available.
6. Perform specialist passes using the shared ledger:
   - Django/settings/deployment
   - Python/static-safety
   - OWASP ASVS/control mapping
   - Postgres/database configuration, ORM use, and query-safety posture
   - auth/OIDC/session/CSRF
   - frontend/header/XSS surface
   - dependency posture
   - supply-chain inventory, vulnerability monitoring, remediation, and provenance (deferred until CI/CD unless explicitly in scope)
7. Consolidate findings into one report.

Specialist agents are optional. If subagents are used, they receive the relevant controls and return evidence and candidate findings; they do not invent a parallel security rubric. The main reviewer owns consolidation, severity, and final wording.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sec-corpus-workflow-1 | Shared Ledger | Proposed | All specialist passes evaluate against the same validated control ledger. | |
| req-sec-corpus-workflow-2 | Specialist Phases Defined | Proposed | The workflow defines domain passes without requiring multi-agent execution. | |
| req-sec-corpus-workflow-3 | Consolidated Report | Proposed | The final review is one report, not disconnected specialist outputs. | |
| req-sec-corpus-workflow-4 | Freshness Checked | Proposed | The review notes stale external controls or newer upstream versions before treating the ledger as current. | |

---

### Control Refresh Workflow
----
RID: `req-sec-corpus-refresh`  

Status: `Proposed`

External-domain controls can be refreshed independently from running a full TAP security posture review.

#### Implementation

The refresh workflow is a security-corpus maintenance task, suitable for a dedicated skill or agent workflow. It asks: "Has the world changed, and should TAP's control ledger change with it?"

The workflow:

1. Load and validate the current control ledger.
2. For each external-domain file, inspect recorded `upstream_version`, `last_reviewed_at`, `authority`, and `refresh_guidance`.
3. Check authoritative upstream sources for new versions, changed guidance, deprecated recommendations, and new controls that appear relevant to TAP.
4. Propose control updates as explicit diffs:
   - add new candidate/recommended controls
   - update `upstream_version` and authority citations
   - mark controls deprecated when upstream guidance changes
   - flag controls that TAP has implicitly adopted and should be promoted to `required`
   - flag new upstream guidance that should trigger a fresh TAP posture review
5. Run the spec sweep so `tap-specific.json` remains reconciled with TAP specs.
6. Validate updated control files before they replace the previous ledger.

The refresh workflow may browse current authoritative documentation because external security guidance changes over time. It should prefer primary sources: framework documentation, provider security docs, OWASP project materials, and official tool documentation. It should not copy large upstream texts into TAP; it should cite sources and summarize TAP-applicable controls.

Refreshing controls is separate from scanning TAP. A refresh may produce no codebase findings at all; its output is an updated ledger, a list of proposed ledger changes, or a recommendation to run a new review because upstream guidance changed.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sec-corpus-refresh-1 | Independent Workflow | Proposed | External-control refresh can run without a full codebase posture review. | |
| req-sec-corpus-refresh-2 | Primary Sources | Proposed | Refresh uses authoritative upstream sources for framework, provider, and standard changes. | |
| req-sec-corpus-refresh-3 | Explicit Diffs | Proposed | Refresh proposes or applies inspectable control-ledger diffs, never silent rewrites. | |
| req-sec-corpus-refresh-4 | Trigger Reviews | Proposed | New or changed upstream guidance can be reported as a reason to run a fresh TAP security review. | |

---

### Lightweight Automation
----
RID: `req-sec-corpus-scripts`  

Status: `Proposed`

v0 automation is lightweight, deterministic, and dependency-conservative.

#### Implementation

- The first implementation may be entirely manual plus schemas.
- Helper scripts should use Python stdlib and existing project dependencies before adding anything new.
- Scripts should collect evidence, validate artifacts, and render reports; they should not patch code.
- External scanners (`bandit`, `semgrep`, `pip-audit`, ZAP, HTTP header scanners) are optional adapters, not required dependencies.
- A scanner result becomes evidence only after it is mapped to a TAP control and reviewed for false positives.
- New third-party dependencies require explicit approval under TAP's dependency discipline.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sec-corpus-scripts-1 | No Patching | Proposed | Security corpus scripts collect and report evidence; they do not edit application code. | |
| req-sec-corpus-scripts-2 | No Required New Dependencies | Proposed | v0 does not require new third-party packages. | |
| req-sec-corpus-scripts-3 | Scanner Output Is Evidence | Proposed | External scanner output is mapped to controls before appearing as findings. | |

---

## Relationship To Other Specs

- **`specs/spec-security-posture.md`** - doctrine for when TAP builds security edges. This spec is the concrete corpus used to evaluate whether those edges exist and still hold.
- **`tap_auth/specs/spec-tap-auth-v0.md`** - primary source for TAP-specific authN/authZ controls, including actor invariants, provider policy, local password behavior, and deploy posture.
- **`specs/spec-tap-boot-v0.md`** - source for boot trust, profile validation, secret-reference, and deploy standup controls.
- **`tap_grid/specs/spec-grid-security.md`** - source for grid and plugin/security controls.
- **`tap_web/specs/spec-web-panel-security.md`** - source for web rendering, CSRF, safe JSON, and panel security controls.
- **`specs/spec-tap-testing.md`** - future home for CI integration and test linkage once security corpus checks become automated gates.

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed | Requirement has been designed but not yet accepted for implementation. |
| Approved for Development | Requirement is accepted and ready to be implemented. |
| In Development | Actively being worked on. |
| Implemented | Has been written. |
| Verified | Has met the acceptance criteria. |
| Refactoring | In the process of being re-worked. |
| Deprecating | In the process of being deprecated. |
| Deprecated | No longer part of the current architecture. |
