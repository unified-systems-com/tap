# tap-cares Specification

## Philosophy

tap-cares is TAP's runtime plumbing for moving facts between the outside world and the local grid.

The name's an acronym for Collect, Act, Receive, Emit, Schedule.

The purpose of tap-cares is to create the foundations for automation products inside TAP. It exists to make ingestion, outbound communication, inbound reception, and scheduled operation first-class on-grid TAP capabilities with clear safety boundaries, observable runs, and service-layer graph writes. It should make routine data movement boring, inspectable, and repeatable, while preserving TAP's rule that users (humans and eventually ai) and local policy remain in charge of graph mutation and external side effects.

tap-cares also acts as a future skill-tree anchor. As each subsystem stabilizes, it should gain a specification and a companion skill so agents can move from architecture, to requirements, to scaffolded implementation in the spirit of TAP rather than inventing local one-off machinery.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Pluggable     | Let TAP apps and plugins publish collectors, receivers, emitters, actions, and schedules as on-grid capabilities without hard-coding domain behavior in tap-cares |
| 2. | Observable    | Record every run, input, output, decision, GRIFT batch, and side effect on the grid with enough detail to debug failures and explain changes |
| 3. | Service-Layer | Route TAP-managed node and edge mutations through the grid service layer, preserving provenance and avoiding parallel write paths |
| 4. | Safe          | Separate data collection, GRIFT batch execution, action planning, and external side effects so each boundary can be reviewed and controlled |
| 5. | Skill-Ready   | Structure capabilities so future agent skills can scaffold and extend them consistently |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-cares-v0-scope | [System Scope](#system-scope) | Proposed | Defines tap-cares as runtime data movement and operation plumbing |
| req-tap-cares-v0-capability-nodes | [Capability On-Grid Nodes](#capability-on-grid-nodes) | Proposed | On-grid nodes and edges for tap-cares capabilities |
| req-tap-cares-v0-collector | [Collectors](#collectors) | Proposed | Pull data from external or local sources into structured collection results |
| req-tap-cares-v0-receiver | [Receivers](#receivers) | Proposed | Open an inbound surface and accept pushed data |
| req-tap-cares-v0-emitter | [Emitters](#emitters) | Proposed | Send data or notifications outward through explicit channels |
| req-tap-cares-v0-action | [Actions](#actions) | Proposed | Generate and track proposed or executable responses to processed data |
| req-tap-cares-v0-scheduler | [Scheduler](#scheduler) | Proposed | Periodically execute collector capability nodes via the scheduler spec |
| req-tap-cares-v0-secrets | [Secrets](#secrets) | Implemented | Mounted `*.secret.json` files resolved through tap-cares runtime registry |
| req-tap-cares-v0-merge | [Grid Merge Contract](#grid-merge-contract) | Proposed | Normalize collected or received data into GRIFT batches for service-layer grid writes |
| req-tap-cares-v0-run-record | [Run Records And Observability](#run-records-and-observability) | Proposed | On-grid execution records for debugging, audit, and UI/API visibility |
| req-tap-cares-v0-authenticator | [Authenticator Management](#authenticator-management) | Proposed | Phase 2 credential/authenticator abstraction for external systems |
| req-tap-cares-v0-ksi-collector | [FedRAMP 20x KSI Collector](#fedramp-20x-ksi-collector) | Proposed | Initial implementation target replacing the git workstream refresh path |
| req-tap-cares-v0-skills | [Skill Tree Alignment](#skill-tree-alignment) | Proposed | Future skills for scaffolding and extending each subsystem |
| req-tap-cares-v0-capability-toggles | [Capability Enable/Disable](#capability-enabledisable) | Backlog | Deferred: enabling/disabling capability nodes (and plugins) converges on a feature-flag system |

## System Scope
----
RID: `req-tap-cares-v0-scope`

Status: `Proposed`

tap-cares owns the runtime patterns for:

- collecting data from external or local sources
- receiving inbound data pushed to TAP
- emitting data or notifications from TAP
- producing actions from processed data
- scheduling recurring operation execution
- normalizing collected or received data into TAP graph mutations
- recording execution state and failures on the grid with enough detail to diagnose problems

tap-cares does not own domain schemas. Domain plugins own the entity types, edge types, constraints, pages, and domain-specific interpretation of source data. tap-cares provides the common runtime affordances those plugins use.

tap-cares does not bypass TAP's graph rules. Any mutation of TAP-managed nodes or edges, including tap-cares capability nodes and run records, must route through the service layer. Direct ORM writes are allowed only for migrations and low-level tests that are explicitly below the service layer.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-scope-1 | Runtime Boundary | Proposed | The spec clearly separates tap-cares runtime plumbing from plugin-owned domain schemas. | |
| req-tap-cares-v0-scope-2 | Service-Layer Mutations | Proposed | All TAP-managed node and edge mutations initiated by tap-cares are required to use the service layer. | |

## Capability On-Grid Nodes
----
RID: `req-tap-cares-v0-capability-nodes`

Status: `Proposed`

tap-cares should store each implemented capability on the grid. Each collector, receiver, emitter, action, and schedule should have its own grid node, associated edges, and companion nodes as needed, such as a collector job or a collector instance running on the host. These submodules exist on the grid, unlike plugins, models, and other code-level metadata that are tracked in non-grid registries.

Each submodule or capability family should add its own node model, or more than one model when needed, to provide the foundational framework that implementations use. Discovery of tap-cares capabilities should therefore be grid discovery, not a separate Python-only registry lookup.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-capability-nodes-1 | Capability Nodes | Proposed | Each capability implementation is represented by a node on the grid. | |
| req-tap-cares-v0-capability-nodes-2 | Capability Models | Proposed | Capability families define the TAP models their implementations use. | |
| req-tap-cares-v0-capability-nodes-3 | Grid Discovery | Proposed | Capability discovery reads on-grid capability nodes and edges rather than relying only on Python imports. | |


## Collectors
----
RID: `req-tap-cares-v0-collector`

Status: `Proposed`

A collector pulls data from a source and returns a structured collection result. Sources may be remote network systems, local files, plugin-managed repositories, APIs, or other read surfaces.

The collector model and registry mapping are specified in `spec-tap-cares-collector.md`.

Collectors should separate source access from grid mutation. A collector run may fetch, validate, normalize, and summarize data, but the decision to merge into the grid should pass through the GRIFT batch based grid merge contract.

Collector outputs should be deterministic where the source allows. They should include source identity, source version or cursor information, collection timestamps, parsed records, warnings, errors, and a draft GRIFT batch when grid mutation is applicable.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-collector-1 | Structured Result | Proposed | Collector runs return structured data rather than relying on free-form logs as the integration contract. | |
| req-tap-cares-v0-collector-2 | No Implicit Grid Mutation | Proposed | Collection and GRIFT batch execution are separate phases, even when executed in one user-facing operation. | |
| req-tap-cares-v0-collector-3 | Source Cursor | Proposed | Collectors can report source version, cursor, ETag, commit SHA, timestamp, or an equivalent source position when available. | |
| req-tap-cares-v0-collector-4 | Draft GRIFT Batch | Proposed | Collectors that propose grid changes output or reference a GRIFT batch for review and execution. | |

## Receivers
----
RID: `req-tap-cares-v0-receiver`

Status: `Proposed`

A receiver accepts inbound data pushed into TAP. Examples include a local HTTP endpoint, webhook target, socket listener, file drop, or future message queue subscription.

Receivers should make trust boundaries explicit. They must validate payload shape before authoring or executing any GRIFT batch, record request metadata useful for debugging, and avoid treating inbound content as instructions.

Receivers are not required for the first FedRAMP 20x KSI collector milestone, but their contract should be defined early so collectors and receivers share the same normalization and merge path.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-receiver-1 | Explicit Inbound Surface | Proposed | Receivers declare the inbound mechanism they expose and how that mechanism is enabled. | |
| req-tap-cares-v0-receiver-2 | Validate Before Batch | Proposed | Receiver payloads are validated before creating GRIFT batches or service-layer writes. | |
| req-tap-cares-v0-receiver-3 | Content As Data | Proposed | Receiver implementations treat inbound strings and payloads as data, not agent instructions. | |

## Emitters
----
RID: `req-tap-cares-v0-emitter`

Status: `Proposed`

An emitter sends data, notifications, or artifacts out of TAP through an explicit channel. Examples include email, Signal, GitHub, filesystem export, webhook calls, or future federation transports.

Emitters are side-effecting by default. They should declare their side effects, dry-run support, payload contract, delivery result shape, retry behavior, and required authenticator.

Emitter execution should be reachable from explicit user intent, an approved action, or a schedule. The system should make it easy to see on the grid what was sent, where it was sent, and why.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-emitter-1 | Declared Side Effects | Proposed | Emitters declare what external side effects they may perform. | |
| req-tap-cares-v0-emitter-2 | Delivery Result | Proposed | Emitter runs record on-grid structured delivery status, including success, failure, and destination metadata. | |
| req-tap-cares-v0-emitter-3 | Dry-Run Shape | Proposed | Emitters define whether dry-run is supported and what a dry-run result contains. | |

## Actions
----
RID: `req-tap-cares-v0-action`

Status: `Proposed`

Actions are responses generated from processed data. They may represent alerts, notifications, remediation suggestions, follow-up collection, or an emitter invocation.

v0 actions should be explicit and inspectable. They may be proposed by processing logic, but autonomous side effects remain out of scope unless a human or an approved scheduler policy has authorized execution.

Actions should preserve the distinction between:

- a finding or condition observed in the grid
- a proposed response to that condition
- an approved or executed response
- the side effects produced by execution

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-action-1 | Proposed Actions | Proposed | Processing can create proposed actions without executing side effects. | |
| req-tap-cares-v0-action-2 | Execution State | Proposed | Actions track state such as proposed, approved, executed, failed, skipped, or canceled. | |
| req-tap-cares-v0-action-3 | Side-Effect Boundary | Proposed | Action execution that emits data or mutates the grid records the responsible trigger and run context on the grid. | |

## Scheduler
----
RID: `req-tap-cares-v0-scheduler`

Status: `Proposed`

The scheduler periodically executes on-grid tap-cares capability nodes. The first scheduler target is recurring collection for the FedRAMP 20x KSI catalog.

The scheduler is specified in `spec-tap-cares-scheduler.md`.

v0 scheduler scope is intentionally narrow:

- Huey evaluates schedules once per minute.
- Schedules target `Collector` nodes only.
- Schedule cadence is a five-field UTC cron expression.
- Missed scheduled slots are counted on the next observed fire through `ScheduleFire.missed_count`; they are not backfilled.
- Schedule overlap is controlled by per-schedule `max_active_runs`.
- Scheduled collection invokes `run_collection(...)`; it does not create jobs or enqueue collector tasks directly.

Schedules should reference collector capability nodes rather than importing implementation functions directly. Schedule state, fire history, missed counts, and links to collection jobs live on the TAP grid rather than in Huey.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-scheduler-1 | Collector Target | Proposed | v0 schedules execute `Collector` nodes by stable grid identity. | See `spec-tap-cares-scheduler.md`. |
| req-tap-cares-v0-scheduler-2 | Durable Schedule | Proposed | Enabled state, UTC cron expression, processed-slot cursor, and max active run limit are stored durably. | |
| req-tap-cares-v0-scheduler-3 | Durable Fire History | Proposed | Each evaluated due slot creates a `ScheduleFire` recording triggered, skipped, or failed scheduler decision state. | |
| req-tap-cares-v0-scheduler-4 | No Catch-Up Execution | Proposed | Missed slots are counted but not backfilled. | |
| req-tap-cares-v0-scheduler-5 | run_collection Boundary | Proposed | Scheduled execution calls `run_collection(...)` and does not reach behind the collector runtime boundary. | |

## Grid Merge Contract
----
RID: `req-tap-cares-v0-merge`

Status: `Proposed`

The grid merge contract normalizes collected or received data into GRIFT batches and executes those batches as TAP-managed graph mutations.

The merge path should:

- validate normalized records before a GRIFT batch is authored or executed
- produce a GRIFT batch that can be inspected before execution
- write nodes and edges through the TAP service layer
- record source provenance and run context
- report creates, updates, skips, deprecations, and errors
- avoid silent overwrites

GRIFT batches are the only interchange shape for tap-cares grid mutation. Collectors and receivers may have source-specific parsing formats, but once they propose a graph change, that change must be represented as a GRIFT batch and executed through the standard GRIFT import/service-layer path.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-merge-1 | Inspectable GRIFT Batch | Proposed | A merge produces an inspectable GRIFT batch before executing service-layer writes. | |
| req-tap-cares-v0-merge-2 | Batch Execution | Proposed | Grid mutation executes through the standard GRIFT batch import path and TAP service layer. | |
| req-tap-cares-v0-merge-3 | Outcome Summary | Proposed | Batch execution results report created, updated, skipped, deprecated, errored, and warning counts. | |
| req-tap-cares-v0-merge-4 | Run Provenance | Proposed | Executed GRIFT batches are linked to the tap-cares run node that produced or approved them. | |

## Secrets
----
RID: `req-tap-cares-v0-secrets`

Status: `Implemented`

tap-cares secrets are local runtime inputs for capabilities that need sensitive material, such as AWS collectors. The v0 design is specified in `spec-tap-cares-secrets.md`.

v0 secrets are loaded from a configured mounted directory at Django startup. The loader scans recursively and considers only files named `*.secret.json`. Each file declares its own `scope`, `key`, `kind`, required free-form `description`, and `data` object. Directories are organizational only. The repository ignores `*.secret.json` so real secret files are not accidentally committed.

Secret files are loaded into an internal `ScopedRegistry`; consumers resolve them through a `SecretRef` / `resolve_secret(...)` helper surface rather than passing raw strings or reading files directly. tap-cares performs only minimal registration-shape validation. Consumer-specific validation belongs to the collector, receiver, emitter, or action that knows the secret kind.

Missing or invalid secrets fail the capability run visibly with redacted structured errors. Secret values are not stored on the grid in v0. A future `Secret` or `SecretReference` BaseModel may expose secret metadata, schema intent, policy, health, and usage relationships on the grid while keeping secret values off-grid.

Encryption at rest for secret files is a backlog requirement and deliberately does not define a v0 file format.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-secrets-1 | Mounted Secret Files | Implemented | tap-cares loads secret material from a configured mounted directory. | See `spec-tap-cares-secrets.md`. |
| req-tap-cares-v0-secrets-2 | Obvious File Pattern | Implemented | Only `*.secret.json` files are loaded and the repo ignores that pattern. | |
| req-tap-cares-v0-secrets-3 | Registry Resolution | Implemented | Runtime consumers resolve secrets through tap-cares helpers backed by a dedicated scoped registry. | |
| req-tap-cares-v0-secrets-4 | Consumer Validation | Implemented | Secret-kind validation belongs to the consumer rather than centralized tap-cares schemas in v0. | `require_secret_kind(...)` accepts consumer-owned schemas. |
| req-tap-cares-v0-secrets-5 | No Grid Values | Implemented | Secret values are not stored on TAP-managed nodes, edges, GRIFT batches, or run records. | Backend stores values in the in-process registry only. |
| req-tap-cares-v0-secrets-6 | Future Secret Model Deferred | Backlog | A future on-grid Secret metadata model and generator command are tracked in the secrets spec. | |

## Run Records And Observability
----
RID: `req-tap-cares-v0-run-record`

Status: `Proposed`

tap-cares should record durable on-grid run records for every collector, receiver, emitter, action, and scheduled execution.

Run records should make failures visible. They should store execution state, timing, triggering actor, capability key, input summary, source cursor, output summary, warnings, errors, and links to any GRIFT batch, action, or emission records produced by the run.

Run records are TAP graph domain entities by default. The execution of collectors is an on-grid operation tracked with grid capabilities, nodes, edges, and service-layer provenance rather than a separate off-grid subsystem.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-run-record-1 | Every Execution Has A Run Node | Proposed | Each tap-cares execution path creates a durable on-grid run node. | |
| req-tap-cares-v0-run-record-2 | Failure Visibility | Proposed | Failures preserve enough structured error context to explain what failed and where. | |
| req-tap-cares-v0-run-record-3 | Linked Outcomes | Proposed | Run nodes link by edges to GRIFT batches, generated actions, or emitter delivery records they produce. | |
| req-tap-cares-v0-run-record-4 | Grid Queryable | Proposed | Run records can be discovered through normal TAP graph query and visualization capabilities. | |


## Authenticator Management
----
RID: `req-tap-cares-v0-authenticator`

Status: `Proposed`

Authenticator management is a known phase 2 requirement. The AWS collection target will require TAP to manage credentials, roles, profiles, tokens, or other source-specific authentication material.

v0 should avoid designing a credential vault prematurely. The runtime secret file and resolver contract in `spec-tap-cares-secrets.md` provides the immediate secret-material boundary while leaving an explicit interface for collectors, receivers, and emitters to declare authenticator needs without embedding secrets in schedules or capability nodes.

Authenticator design must account for local-first deployments, secret redaction in logs, rotation, least privilege, and non-secret execution contexts such as local files.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-authenticator-1 | Declared Auth Needs | Proposed | Capability nodes can declare authenticator requirements without storing secret values. | |
| req-tap-cares-v0-authenticator-2 | No Secret Logs | Proposed | Run records and errors redact secrets and sensitive credential material. | |
| req-tap-cares-v0-authenticator-3 | Phase 2 Boundary | Proposed | tap-cares can resolve mounted runtime secrets without committing TAP to a full credential-management or vault design. | See `spec-tap-cares-secrets.md`. |

## FedRAMP 20x KSI Collector
----
RID: `req-tap-cares-v0-ksi-collector`

Status: `Proposed`

The first implementation target for tap-cares is a collector for the `fedramp_20x_ksi` plugin. It should pull the latest FedRAMP 20x KSI catalog updates and merge them into the local grid's KSI theme and indicator set through a GRIFT batch.

This replaces the prior git workstream based collection path. The old path generated plugin-authored GRIFT waves through a submodule and CI workflow. tap-cares brings the runtime collection and merge behavior in-house so local installations can observe what happened, why it happened, and where it failed.

The initial KSI collector should preserve the safety posture of the old refresh tooling:

- source content is treated as data, not instructions
- source origin and schema drift are checked where applicable
- mass deletion or deprecation events require explicit review
- source position is recorded
- GRIFT batch results are visible
- failures are recorded in tap-cares run records

The collector may still reuse deterministic parsing, validation, diff, and UUID behavior from the existing refresh tooling where that logic remains sound, but the operational home shifts from plugin-maintainer authorship tooling to tap-cares runtime collection.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-ksi-collector-1 | Latest KSI Collection | Proposed | A collector capability node can identify and fetch the latest FedRAMP 20x KSI source data. | |
| req-tap-cares-v0-ksi-collector-2 | Safe Diff | Proposed | The collector produces a structured diff and GRIFT batch for KSI themes and indicators before execution. | |
| req-tap-cares-v0-ksi-collector-3 | Local Grid Merge | Proposed | Approved KSI changes are merged into local KSI theme and indicator entities through GRIFT batch execution and the service layer. | |
| req-tap-cares-v0-ksi-collector-4 | Visible Failure | Proposed | Fetch, validation, diff, and GRIFT batch execution failures appear in tap-cares run records. | |
| req-tap-cares-v0-ksi-collector-5 | Scheduled Refresh | Proposed | The KSI collector can be executed by a durable schedule once scheduler support exists. | |

## Skill Tree Alignment
----
RID: `req-tap-cares-v0-skills`

Status: `Proposed`

Each tap-cares subsystem should eventually have a companion skill. The purpose is to help agents implement TAP-consistent capabilities by following architecture, specs, on-grid capability contracts, and local code patterns.

Expected skill families include:

- create or extend a collector
- create or extend a receiver
- create or extend an emitter
- create or extend an action
- create or extend a schedule
- add tap-cares run observability
- add a plugin-specific tap-cares capability

Skills should reinforce one another. A collector skill should know how to produce GRIFT batches and run records. A scheduler skill should know how to target on-grid capability nodes. An emitter skill should know how action execution and delivery results relate.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-skills-1 | Skill Targets Named | Proposed | The spec names the expected skill families that will grow around tap-cares. | |
| req-tap-cares-v0-skills-2 | Specs Before Scaffolding | Proposed | Future skills instruct agents to inspect architecture and specs before generating code. | |
| req-tap-cares-v0-skills-3 | Reinforcing Contracts | Proposed | Skills share capability-node, run-record, and GRIFT batch concepts rather than creating isolated workflows. | |

## Capability Enable/Disable
----
RID: `req-tap-cares-v0-capability-toggles`

Status: `Backlog`

Enabling and disabling tap-cares capability nodes (Collectors, Receivers, Emitters, Actions, Schedules) is deliberately out of scope for v0.

The same need exists for plugins themselves. A general-purpose toggle quickly converges on a feature-flag system with per-grid state, scoping, and audit. v0 does not commit to that design. Capability nodes that are present on the grid are considered eligible to run; disablement is achieved by not creating the node or by removing it.

When this is addressed, the design should account for:

- consistent toggle semantics across capabilities and plugins
- on-grid state visible to admin and audit surfaces
- interaction with schedules (a disabled capability should not be silently re-enabled by an active schedule)
- per-dimension scoping if/when dimensions gain a stronger role

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-capability-toggles-1 | Backlog Requirement Exists | Backlog | Capability and plugin enable/disable is tracked as a named backlog requirement rather than designed ad hoc. | |
| req-tap-cares-v0-capability-toggles-2 | Unified With Plugin Toggle | Backlog | Future design considers capability toggles and plugin toggles as one feature-flag-shaped problem. | |

## Development Notes

Initial sequencing is expected to be:

1. Define the tap-cares architecture and update `architecture.md` / `CLAUDE.md` touchpoints.
2. Define the collector contract in more detail.
3. Define the scheduler contract in enough detail to run collectors periodically.
4. Implement the FedRAMP 20x KSI collector and GRIFT batch merge path.
5. Define the secrets runtime contract before implementing collectors that need external credentials.
6. Add action behavior only when collection/merge processing produces a concrete need for alerts or notifications.
7. Defer full authenticator management until the AWS collection target requires per-capability credential metadata beyond runtime secret references.

## Future

Open questions for follow-up specs:

- Which tap-cares run record and execution edge types should ship in the initial model set.
- How much GRIFT batch detail should be stored directly on-grid versus referenced as an artifact.
- How schedules should run in production: Django Tasks, management command plus cron, long-running worker, or another local-first mechanism.
- What approval model is needed before actions can execute side-effecting emitters.
- How authenticator records should integrate with Django auth, local deployments, and plugin-specific credential needs.
- Whether a future Secret/SecretReference BaseModel should expose secret metadata, schemas, generator commands, health, and usage edges on the grid.
- Whether "Synchronize" should become the explicit second "s" capability in tap-cares.
