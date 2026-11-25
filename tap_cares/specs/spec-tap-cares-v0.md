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
| req-tap-cares-v0-emitter | [Emitters](#emitters) | Proposed | Send data outward: on-grid `Emitter`, mandatory deadline, destination in the emitter's own secret, `EmissionJob` run record with an attempt record per request, dry run, operator arming of the emitter's code; no core transport |
| req-tap-cares-v0-action | [Actions](#actions) | Proposed | Generate and track proposed or executable responses to processed data |
| req-tap-cares-v0-scheduler | [Scheduler](#scheduler) | Proposed | Periodically execute collector and emitter capability nodes via the scheduler spec |
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

An emitter sends data, notifications, or artifacts out of TAP through an explicit channel. Examples include email, Signal, GitHub, filesystem export, webhook calls, or future federation transports. v0 specifies emitters that make HTTPS requests to a destination configured in the emitter's own secret. Every other channel is Backlog.

Emitters are side-effecting by default. They declare a deadline, an authored version and the secret they need; they support dry run; and they record each request before they make it.

Emitter execution should be reachable from explicit user intent, an approved action, or a schedule. The system should make it easy to see on the grid what was sent, where it was sent, and why. v0 builds the explicit-intent and schedule paths; the approved-action path waits on `req-tap-cares-v0-action`.

An emitter sends data off the box, so this is security-critical work (`spec-security-posture.md`). v0 secures it with **operator approval and a record**, not with an enforced network boundary. What that leaves open is stated as an accepted risk below (`req-sec-honest-risk`), and the enforcement work is Backlog (Issue# 1369 - tap).

#### The shape

An emitter is the collector's mirror and reuses its machinery rather than inventing a parallel one:

| | Collector | Emitter |
| --- | --- | --- |
| Registration (read-only, at `ready()`) | `register_collector(...)` | `register_emitter(...)` |
| On-grid capability node | `Collector` | `Emitter` |
| Materialization (bound actor, boot) | `reconcile_collector_nodes()` | `reconcile_emitter_nodes()` |
| Sole run entry point | `run_collection(...)` | `run_emission(...)` |
| Task | `run_collector` | `run_emitter` (default queue) |
| Run record | `CollectionJob` | `EmissionJob` (a run under `spec-tap-cares-run.md`, and its own owner job) |
| Capability → run edge | `HAS_COLLECTION_JOB` | `HAS_EMISSION_JOB` |
| Fire → run edge | `TRIGGERED_JOB` | `TRIGGERED_EMISSION` |
| Run configuration | `RunConfiguration --CONFIGURES--> Collector` | `RunConfiguration --CONFIGURES--> Emitter` (`spec-tap-cares-run-configuration.md`) |
| Operator arming switch | `arm_reconcile` | `arm_emitter`, per run configuration |
| Authored version | `COLLECTOR_VERSION` | `EMITTER_VERSION` |

What differs is the direction of the side effect. A collector's effect lands on the grid and is reviewable after the fact as a GRIFT batch; an emitter's effect lands on someone else's system and cannot be taken back. So an operator approves the emitter's code to send, by arming it, and the emitter records each request before it makes it.

**Modelled on the collector.** Core owns the emitter's registration, its job, its lifecycle and its records. The plugin owns its outbound work and how it checks itself, the same way a collector owns its self-test and decides how much outbound work it does (`req-tap-cares-collector-self-test`). Core adds no monitoring on top of an emitter's requests; the security build-out that would is Issue# 1369 - tap.

**Core ships no transport.** An emitter makes its requests with whatever is on the instance (the Python standard library, Django, core's own dependencies) or with libraries it brings through its plugin's dependencies, exactly as a collector does. Core does not wrap, proxy, inspect or allowlist the emitter's network calls. Payloads are the emitter's business too: how it gathers the data (canned outputs, Search over the grid, somewhere else) and how it shapes the bytes are up to it and its plugin's spec. Core owns the registration, the arming, the run record, the deadline and the per-request send record.

#### Registration and the `Emitter` node

```python
def register_emitter(
    key: str,
    cls: type[EmitterBase],
    *,
    scope: str,            # the plugin's stable slug, never inferred
    name: str,
    description: str,
) -> None: ...

def reconcile_emitter_nodes() -> dict[str, int]: ...
```

`register_emitter` writes no grid node (`req-tap-plugin-load-v0-ready-readonly`); `reconcile_emitter_nodes()` is the sole writer of `Emitter` rows, through the trusted-internal batch path. This copies the collector's dual-existence pattern as it stands (`req-tap-cares-collector-registration`, `tap_grid/specs/spec-grid-dual-existence.md`); consolidating the two into one shared mechanism is Issue# 1367 - tap (`req-grid-dual-existence-consolidation`). A class may be registered under several keys, each its own `Emitter`.

Registration validates the class and refuses it, naming the problem, when: `EMITTER_VERSION` is missing from the class's own body or is not an integer of 1 or more; `DEADLINE` is missing or not a positive duration; or `SECRET_KIND` / `SECRET_SCHEMA` is missing. It also refuses a class that declares neither or both of `CONFIG_SCHEMA` and `RUN_CONFIGURATION = NOT_CONFIGURABLE` (`req-tap-cares-runconfig-schema-4`); a not-configurable emitter's configuration, with its `secret_ref`, is seeded by its plugin (`req-tap-cares-runconfig-not-configurable`).

`Emitter` is a standard `BaseModel` (via `add-model`), `INTERNAL_ONLY`, `NATURAL_KEY = (emitter_registry,)` (owner ruling 2026-11-25, as `Collector` declares `(collector_registry,)`), and its id is **assigned**, never derived (`req-grid-entity-natural-key-1`; the Collector's derived id is not copied). Reconcile finds the row by its unique `emitter_registry`. Default dimension `{"tap_cares": "emitter"}`. Fields:

| Field | Notes |
| --- | --- |
| `name`, `description` | From registration |
| `emitter_registry` | `scope:key`, unique per grid |
| `secret_kind` | The envelope kind the class requires (`EmitterBase.SECRET_KIND`) |
| `deadline` | The class's `DEADLINE`, so the bound is visible on the grid; it is not part of what arming approves |
| `emitter_version` | The class's `EMITTER_VERSION` |

Arming is not an `Emitter` field: `send_authority` and the `armed_*` record live on each of the emitter's run configurations (`req-tap-cares-runconfig-emitter-arming`).

A bundle names an emitter only through GRIFT's natural-key endpoint, `{"entity_type": "emitter", "key": {"emitter_registry": "<scope:key>"}}` (`req-grid-import-grift-edge-endpoints`), never by its assigned id. The one bundle edge that may name an emitter is the `CONFIGURES` edge of its plugin's not-configurable seed (`req-tap-cares-runconfig-not-configurable`). No bundle schedules an emitter, and none should: a schedule that sends data off the box is an operator's decision, not an install side effect. Schedules target a configuration's uuid, and the schedule-grift guard (`schedule-grift-targets`) checks both forms (`req-tap-cares-runconfig-seed-guard`).

#### `EmitterBase`

```python
class EmitterBase(ABC):
    EMITTER_VERSION: ClassVar[int]               # in the class's own body; 1 or more
    DEADLINE: ClassVar[timedelta]                # mandatory; the author sets the value
    SECRET_KIND: ClassVar[str]                   # consumer-owned kind (req-tap-cares-secrets-consumer-kinds)
    SECRET_SCHEMA: ClassVar[str]                 # package path of the kind's JSON Schema

    def __init__(self, config: EmitterConfig) -> None: ...   # carries the validated envelope data

    def emit(self, ctx: EmissionContext) -> None:
        """Gather the payload, call ctx.record_send before each request, make the
        request only when the permit allows it, and report each outcome."""

    def on_abort(self, run: EmissionJob) -> None:
        """Optional clean-up after the run was ended from outside (spec-tap-cares-run.md). Default: no-op."""
```

**Deadline.** Every emitter declares `DEADLINE`, an overall bound on one run. The author chooses the value; core sets no default, minimum or maximum, and registration refuses an emitter without one. At task start, before any plugin code runs, the task persists `deadline_at = task_started_at + DEADLINE`, so plugin code that hangs is already under the deadline. Core enforces it at the run level: the mop-up closes a `running` emission past `deadline_at` as `abandoned` with `failure_kind = deadline_exceeded` and, if the run recorded a send, sets its `on_abort` clean-up pending (`req-tap-cares-run-mopup`, `req-tap-cares-run-abort-cleanup`), and `record_send` refuses once `deadline_at` has passed, so no new request can be recorded and therefore none may be made. Core cannot cut a socket that is already open; a request in flight at the deadline is `unknown` unless a late answer is recorded (below).

**Retries are the emitter's concern.** Whether to retry, which statuses count as retryable, how to honor `Retry-After`, connect and read timeouts, and how much of a response to read are decided by the emitter and stated in its plugin's spec. All of it is optional and off by default: one attempt per request unless the emitter opts in. An emitter that does retry records each attempt with `record_send`, chooses its idempotency keys as its destination's own contract requires, decides for itself which requests are safe to repeat, never retries a whole request after the destination accepted part of it, and ends the run rather than wait when a `Retry-After` would carry it past `deadline_at`. Core owns no backoff, re-enqueues nothing, and keeps no cross-run retry: the next fire is a new run.

#### Destination and secret

Destination settings are not nodes. Whoever can edit a node must not be able to point a credential at another host. Each emitter run reads exactly one operator-owned envelope (`spec-tap-cares-secrets.md`): the one its run configuration names in `secret_ref` (`req-tap-cares-runconfig-credential`), which arming binds (`req-tap-cares-runconfig-emitter-arming`). The configuration holds only the reference; the destination stays in the envelope. Its `kind` must equal `SECRET_KIND`, and its `data` is validated against `SECRET_SCHEMA` with `require_secret_kind` before anything else runs. `data` holds the credential and the destination, in whatever shape that emitter's kind defines, and the emitter uses them however it likes. Core does not read the destination: it reserves no key in `data` or in the envelope's `metadata`, and the secrets spec is unchanged.

#### Deferred to Issue# 1369 - tap

The following were drafted for v0 and moved to the security build-out by owner ruling 2026-11-25. Emitters are trusted to do the right thing for now, and these need designing as one system rather than as one-off checks:

- *`destination_grant` and `run_destinations` hooks, with a strict https-origin parse:* core would have to read the emitter's destination, which it no longer does.
- *Arming bound to a destination grant (`armed_grant`):* arming now approves the code (`EMITTER_VERSION` plus `source_hash`), not a destination.
- *Per-run destination selection and `dry_run_reason = destination_unapproved` (was `req-tap-cares-v0-emitter-24`):* without a grant there is nothing to select from.
- *Destinations recorded on the run and on each attempt (`record_send`'s `destinations` keyword):* where an emitter sends is its own responsibility until this lands.
- *Clean-up only against the run's recorded destinations, and refusal when the current grant no longer includes them (`destination_no_longer_granted`):* both depend on the grant.

Generalising destinations to scheme-qualified URIs, declared operations, and data categories remain Backlog in Issue# 1371 - tap.

#### The run: `run_emission` and `EmissionJob`

`run_emission(emitter, *, dry_run, run_configuration=None, caller_context=None, manual_run=False, manual_run_source="") -> EmissionJob` is the sole entry point (the configuration is chosen per `req-tap-cares-runconfig-selection`; an emitter always runs with one), with the same contract shape as `run_collection`: it opens one lifecycle batch (`source = "tap_cares.emitter"`), creates the `EmissionJob` through the trusted-internal create, writes `HAS_EMISSION_JOB`, and enqueues `run_emitter` with JSON-safe ids only. The task body is the sole writer of the job after that, apart from the mop-up's abandon (`req-tap-cares-run-mopup`).

`EmissionJob` adopts the run convention (`spec-tap-cares-run.md`): it carries `RunMixin`'s fields and states, its `owner_job_id` is its own entity id, its close is the conditional write from `running`, and the mop-up closes it from outside. It is also the owner job for any run node an emitter opens for grid writes of its own (`open_run(..., owner_job_id=emission_job_id)`). Status `running` covers the job from kickoff until it closes, queued or executing.

The task runs these steps in order: write `task_started_at` and persist `deadline_at` and the code identity (`emitter_version`, plugin slug, release, commit, `source_hash`), all before any plugin code runs; resolve and validate the envelope; check arming (below); then call `emit(ctx)`. The `EmissionContext` gives the emitter `dry_run`, the deadline, and four calls:

- `ctx.record_send(operation, idempotency_key=None) -> SendPermit` — **required before each request attempt**. It commits an attempt record on the job before any byte of that attempt leaves: an operation label the emitter chooses, the idempotency key if the emitter uses one, and when. No body, digest or size is stored. This is the outbox intent, per attempt. Core does not check the label against any declaration. It refuses a run that is no longer `running`, and a run past `deadline_at`; the `running` check is made under a lock on the job row inside the same transaction that writes the attempt record, so an attempt can never be recorded on a job the mop-up has already abandoned. A proceeding attempt also clears any earlier `delivery_conclusion`; the emitter must conclude again. In a dry run it records the same entry with `outcome = not_sent` and returns a permit whose `proceed` is false; the emitter must not make the request.
- `ctx.record_outcome(permit, outcome, *, response_status=None, remote_reference=None, accepted=None, rejected=None)` — reports what the destination said about one recorded attempt. It is accepted after the run has closed, including after an abandon (late evidence, below): evidence about an attempt already made is not a new effect, so it is allowed where `record_send` is not.
- `ctx.conclude_delivery(outcome, *, accepted=None, rejected=None)` — optional: the emitter's own conclusion about the job's delivery, drawn from its attempts (rule below).
- `ctx.record_versions(*, payload_format=None, destination_api=None)` — the payload format version the emitter produced and the API version the destination reported, recorded on the run.

One run may make several requests (one payload sent as several requests, or several operations), and a request may take several attempts; each attempt has its own record. Requests to more than one destination are Backlog.

`EmissionJob` is `INTERNAL_ONLY`, `KEYLESS` ("a run: an act of this grid"), default dimension `{"tap_cares": "emission_job"}`. Fields, beyond `RunMixin`'s:

| Field | Notes |
| --- | --- |
| `name`, `description` | |
| `outcome` | `not_sent`, `delivered`, `refused`, `partial`, `unknown` (derived below) |
| `dry_run`, `dry_run_reason` | `requested`, `unarmed` or `arm_stale` |
| `manual_run`, `manual_run_source` | As on `CollectionJob` |
| `sends` | The ordered attempt records: operation label, idempotency key when given, recorded time, whether the permit proceeded, and once reported its outcome, HTTP status, `remote_reference`, and accepted / rejected counts |
| `delivery_conclusion` | The emitter's own conclusion from `conclude_delivery`; empty when it gave none, and cleared by any later proceeding attempt |
| `deadline_at` | `task_started_at + DEADLINE`, persisted before any plugin hook runs |
| `emitter_version` | `EMITTER_VERSION` at run time |
| `plugin_slug`, `plugin_release`, `plugin_commit`, `source_hash` | Stamped by core exactly as `req-tap-cares-collector-version` rules 2 and 4 stamp a collector run, from the emitter class |
| `payload_format_version`, `destination_api_version` | From `record_versions`; empty when not reported |
| `task_result_id`, `enqueued_at`, `task_started_at` | |

**Outcomes.** Each `record_send` is an **attempt record**. An attempt's outcome is re-derived as evidence arrives: an explicitly recorded `unknown` may be refined by a later answer, and a definite answer (`delivered`, `refused`, `partial`) is not overwritten. `delivered`: the destination acknowledged with success. `refused`: it answered and declined. `partial`: it accepted some of what the attempt carried and rejected the rest, reported with `accepted` and `rejected` counts; a request the destination partly accepted is never retried whole, by core or by the emitter. `unknown`: the attempt may have reached the destination with no reliable answer back (a timeout after sending, a dropped connection, a worker that died or a deadline that passed after the record committed). `not_sent`: dry runs, and permits that did not proceed. An attempt with no reported outcome is `unknown`, and `unknown` is never rendered as failed-and-not-sent, because the data may be on the other side.

The job's `outcome` is the emitter's `delivery_conclusion` when it gave one and no attempt has proceeded since (a new proceeding attempt clears the conclusion): the emitter knows its destination's contract and may conclude, for example, `delivered` after a timed-out attempt followed by a successful retry that the destination treats as idempotent. When it gave none, core derives the outcome from the attempts: `not_sent` when no attempt proceeded, otherwise `unknown` if any proceeding attempt has no answer or an `unknown` one, `delivered` if all were delivered, `refused` if all were refused, and `partial` for any other mix.

**Late evidence.** An acknowledgement can arrive after the run was closed from outside: an in-flight attempt answered after the deadline abandoned the run. `record_outcome` (and `conclude_delivery`) may still add that evidence to the attempt and re-derive `outcome`, because evidence about an attempt already made is not a new effect. What stays refused after the close is anything that would be one: `record_send`. The run's lifecycle `status` stays `abandoned`, because terminal status is sticky (`req-tap-cares-run-lifecycle`); the attempt records on the grid explain what happened.

The job closes `complete` when `emit` returns and the outcome is `delivered`, or when a dry run returns; any other return closes it `failed` with `failure_kind` set to the outcome; an exception closes it `failed` per the run helper's classification (`req-tap-cares-run-helper`).

**Delivery identity and idempotency keys are the plugin's.** Core neither derives nor reuses keys and keeps no notion of a "logical send" across runs. Whether a key exists, how it is formed, when it may be reused, and how it reaches the destination (a header, a body field) are decided by the emitter from its destination's own contract: Stripe, for one, checks server-side that a reused key comes with the same request, and re-executes a request whose key it has already pruned. A key passed to `record_send` is recorded so an operator can match attempts with the destination's own logs.

**Edges.** `Emitter --HAS_EMISSION_JOB--> EmissionJob` and `ScheduleFire --TRIGGERED_EMISSION--> EmissionJob` are internal-only and keyless, like their collector twins. `EmissionJob --EMITTED_PAYLOAD--> <any node>` (wildcard target, internal-only, keyless) is kept as an edge an emitter **may** write, through `ctx.link_payload_source(entity_id)` on the lifecycle batch, when what it sent was made from an identifiable grid node. Core never requires it, and an emitter whose payload does not come from the grid writes none.

**Dry run.** Every emitter supports dry run, and it is the same run with the requests left out. It resolves and validates the envelope, runs `emit`, and records every send it would make with `outcome = not_sent`, `dry_run = true`. Core's part is structural: every permit in a dry run says do not proceed. Not making the request is the emitter's part, and since emitter code is trusted Python, a dry run is a contract, not a sandbox. A dry run answers "what exactly would be sent, by which operation, and is it configured", which is what an operator needs before arming.

#### Scheduling

`SCHEDULED_TARGET` gains `emitter` as a deliberate second target type (`spec-tap-cares-scheduler.md`, `req-tap-cares-scheduler-scope`); under run configurations the edge targets one of the emitter's `RunConfiguration`s (`req-tap-cares-runconfig-selection`). The scheduler dispatches on the type of the component targeted, calling `run_collection` for a collector and `run_emission(emitter, dry_run=False)` for an emitter, and a fire for any other type fails. Exactly one target per schedule, slot dedupe, no catch-up, and `max_active_runs` are unchanged; for an emitter target, the active runs are the `EmissionJob`s reached through `TRIGGERED_EMISSION` whose status is `running`.

Any write that decides when an emitter sends requires the capability `cares.schedule_emitters`: creating a `Schedule` that targets an emitter (one of its run configurations), retargeting one onto an emitter, and changing an emitter schedule's cadence, enabled state or `max_active_runs`. A write of a `SCHEDULED_TARGET` edge whose target is an `Emitter`, or of any of those fields on a `Schedule` whose target is an `Emitter`, is refused for an actor without it (owner ruling 2026-11-25).

#### Approval stance (v0)

v0 has **no per-delivery approval**. Approval is **arming**:

- An emitter is unarmed when it first appears. While unarmed, every run, scheduled or manual, is a dry run with `dry_run_reason = unarmed`, so a fresh install never sends anything.
- **Arming is per run configuration** (`req-tap-cares-runconfig-emitter-arming`, which amends this list): `arm_emitter` takes a run configuration, and besides `EMITTER_VERSION` and `source_hash` it binds the configuration's revision and its secret ref; a change to any of the four makes runs `arm_stale`. The rest of this list stands with "emitter" read as "the emitter's run configuration".
- `manage.py arm_emitter <scope:key> --on|--off --as <username>` is the one writer of `send_authority` and the `armed_*` fields. It is gated by the capability `cares.arm_emitters` (an operator act that no program actor holds), and it writes on a batch of its own whose metadata is the audit record (operator, shell OS user, emitter, before, after). This mirrors `arm_reconcile` (`req-tap-cares-collector-model-12`). Arming `--on` computes the class's `source_hash` (`req-tap-cares-collector-version` rule 4) and binds the current **`EMITTER_VERSION`** and that **`source_hash`**. What arming approves is: **this code may send**. Where it sends is the emitter's own responsibility (Issue# 1369 - tap). The arming record keeps both values, so a re-arm can show what changed. Arming is refused when the source hash cannot be computed, since an empty hash approves nothing.
- At each run, the arming is checked against the present: an `EMITTER_VERSION` that differs from `armed_emitter_version`, or a `source_hash` that differs from `armed_source_hash` (or could not be computed), makes every run a dry run with `dry_run_reason = arm_stale` until an operator re-arms. Any change to either counts.
- A `Schedule` targeting an armed emitter is the standing policy that authorizes its scheduled sends ("an approved scheduler policy", `req-tap-cares-v0-action`).
- `manage.py run_emitter <scope:key> [--send] --as <username>` is the explicit-intent door. It is gated by `cares.run_emitters`, **defaults to a dry run**, and sends only with `--send` on an armed, non-stale emitter. It sets `manual_run_source = "shell"`.

Proposed → approved → executed action workflows, Administrivia buttons, and an API trigger are Backlog.

**Named accepted risks.**

- *Arming approves the emitter's code to send, not where it sends.* Emitter code is trusted Python in the worker. The operator approves this version and source hash of the emitter to send; where it sends is the emitter's own responsibility until Issue# 1369 - tap, and nothing in core stops it opening a socket to any host or making a request without recording it. The protection is review of the plugin's code plus the operator's approval of that code. What kinds of data leave (data categories) is not declared in v0; it is Backlog in Issue# 1371 - tap, as is any declaration of the operations an emitter performs. Enforcement (destination grants, origin allowlist, resolve-check-pin of addresses, refusal of non-global and metadata addresses, `trust_env` and redirect hygiene, dependency floors, test helpers for these, egress manifests and approval records, network-level egress control) is Backlog under Issue# 1369 - tap. This is the same footing as `req-tap-cares-collector-read-boundary-5`.
- *Who can schedule an armed emitter.* Only an actor holding `cares.schedule_emitters` can point a schedule at an emitter or change when an emitter schedule fires (cadence, enabled state, `max_active_runs`). Deleting such a schedule stops sends and is not gated beyond ordinary `Schedule` permissions.
- *The deadline cannot stop a running thread.* A run closed for its deadline may still be running its code; `record_send` refuses its further requests, and `on_abort`, which runs only if the run recorded a send, must be safe against it.

#### What is recorded, and what is not

No secret value, credential header, payload body, response body, or full request URL with a query string appears on any node, edge, batch, run field or log line, including on failure paths. Exception text passes through the secrets redaction (`req-tap-cares-secrets-redaction`) before it is stored. The response is untrusted data: it is never logged whole, never stored, and never becomes a grid write. What is kept from it is the HTTP status, accepted / rejected counts where the destination reports them, and an emitter-extracted `remote_reference` (the destination's id for what it received). `remote_reference` must be printable: no C0 or C1 control characters, no DEL, and no bidirectional control characters; it has no length cap. What is logged is the emitter key, operation label, outcome, and HTTP status. Storing the payload body itself, so that "what was sent" can be replayed byte for byte, is Backlog. Until then the attempt records, plus `EMITTED_PAYLOAD` where the emitter writes it, are the record; core keeps no digest of what was sent.

#### Prior art, and what it changed

Surveyed 2026-11-24 from documentation; revised 2026-11-25; no code copied.

- **Singer/Meltano targets.** The tap/target split is our collector/emitter split. Rejected: the stdin stream coupling. Where an emitter's data comes from is its own business.
- **Vector sinks and Logstash outputs.** Borrowed: delivered means the destination's response said success (Vector's end-to-end acknowledgements). That is why `delivered` needs an answer, and why a missing answer is `unknown`, not success. Rejected: in-memory or disk buffers and unbounded retry. A buffer is state outside the grid, and the next fire is our retry.
- **Airflow operators and Dagster asset materializations.** Borrowed: one durable record per run, with optional lineage to the asset it was made from (`EMITTED_PAYLOAD`). Rejected: framework-level automatic retries across worker restarts, which would re-send non-idempotent requests.
- **Transactional outbox and Kubernetes Events.** Borrowed: the intent is durable state written before the side effect, here one record per attempt. That gives the `unknown` outcome its meaning after a crash or a deadline.
- **Argo Events sensors and triggers.** Borrowed: the trigger (`Schedule`) is separate from what it fires, and the trigger's own policy is the authorization. Rejected: arbitrary trigger templates that build requests from event data, because our request shape is fixed in reviewed code.
- **Stripe idempotency keys.** What it changed: keys are the plugin's, not core's. Stripe compares a reused key against the original request server-side and prunes keys after a while, after which the same key re-executes; a generic core rule for reusing keys would be wrong for such a destination. Each emitter follows its own destination's contract, and core only records the key it was given. Stripe's key-length rule describes Stripe's API and is not adopted as a limit here.
- **Tenable plugin (this organization).** Borrowed: "settings are not nodes", so the destination lives in the emitter's own secret. Its transport-level allowlist is the shape the egress-enforcement backlog starts from (Issue# 1369 - tap).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-emitter-1 | Declared Side Effects | Retired | — | Retired 2026-11-25 by owner ruling: `SIDE_EFFECTS`, its schema, its registration check and its node field are dropped from v0; the build-out and its prior art are Backlog in Issue# 1371 - tap. |
| req-tap-cares-v0-emitter-2 | Delivery Result | Proposed | Every run writes one `EmissionJob` with the fields above, carrying `RunMixin` and its own id as `owner_job_id`, linked `Emitter --HAS_EMISSION_JOB-->` and, when scheduled, `ScheduleFire --TRIGGERED_EMISSION-->`; `EMITTED_PAYLOAD` is written only when the emitter asks for it. | Promotes `req-tap-cares-v0-run-record-3` for emitters. |
| req-tap-cares-v0-emitter-3 | Dry-Run Shape | Proposed | Every emitter supports dry run: the same steps and the same send records with `dry_run = true` and `outcome = not_sent`; every permit has `proceed` false. | A test of a reference emitter asserts it makes no request in a dry run; for plugin emitters this is a contract. |
| req-tap-cares-v0-emitter-4 | Split Registration, Assigned Identity | Proposed | `register_emitter(key, cls, *, scope, name, description)` writes no grid node; `reconcile_emitter_nodes()` is the sole writer of the `INTERNAL_ONLY` `Emitter`, `NATURAL_KEY = (emitter_registry,)`, found by unique `emitter_registry`, id assigned; a GRIFT bundle names an emitter only by that natural key, and only in a not-configurable seed's `CONFIGURES` edge, never as a schedule target; registration refuses a class missing `EMITTER_VERSION`, `DEADLINE`, `SECRET_KIND` or `SECRET_SCHEMA`. | Copies the collector pattern; consolidation is Issue# 1367 - tap. |
| req-tap-cares-v0-emitter-5 | Payload Through A Published Source | Retired | — | Retired 2026-11-25 by owner ruling, before it reached main: payloads are the emitter's business, so `register_payload_source` and `PayloadDocument` are removed. |
| req-tap-cares-v0-emitter-6 | Digest Derived At The Boundary | Retired | — | Retired 2026-11-25 by owner ruling, before it reached main: core ships no transport and never sees the body. A later owner ruling the same day dropped the digest and size from the send record altogether (`req-tap-cares-v0-emitter-17`). |
| req-tap-cares-v0-emitter-7 | Destination In The Emitter's Secret | Proposed | Each emitter reads one envelope at its own `scope:key`, of kind `SECRET_KIND`, validated against `SECRET_SCHEMA` before any plugin hook runs; the destination lives in that data and the emitter uses it as it likes; core does not read it, reserves no key in the envelope, and no node field holds a destination or credential. | Settings are not nodes. No secrets-spec change. Destination hooks and parsing moved to Issue# 1369 - tap. The envelope is the one the run configuration names, no longer derived from the emitter's key (`req-tap-cares-runconfig-credential`). |
| req-tap-cares-v0-emitter-8 | Bounded Egress | Retired | — | Retired 2026-11-25 by owner ruling, before it reached main: core ships no transport. Egress enforcement is Backlog (Issue# 1369 - tap), named in `req-tap-cares-v0-emitter-21`. |
| req-tap-cares-v0-emitter-9 | Intent Before Send, Outcomes | Proposed | Each attempt's record is committed before its first byte; attempt outcomes are `delivered`, `refused`, `partial` (with accepted / rejected counts), `unknown` and `not_sent`; an attempt with no reported outcome, including in a reaped or deadline-closed job, is `unknown`; the job outcome is the emitter's `delivery_conclusion` when given and is otherwise derived from the attempts as stated. | Outbox, per attempt. |
| req-tap-cares-v0-emitter-10 | Bounded In-Run Retry | Retired | — | Retired 2026-11-25 by owner ruling, before it reached main: retry policy, and any attempt count, belongs to the emitter (`req-tap-cares-v0-emitter-18`). |
| req-tap-cares-v0-emitter-11 | One Entry Point | Proposed | `run_emission(...)` is the sole way to start an emission; it owns the lifecycle batch (`source = "tap_cares.emitter"`), the `EmissionJob` create, `HAS_EMISSION_JOB`, and the enqueue of `run_emitter` with JSON-safe ids. | Same contract shape as `run_collection`. |
| req-tap-cares-v0-emitter-12 | Arming Is The Approval | Proposed | `send_authority` defaults to `false` and is written only by `arm_emitter` (capability `cares.arm_emitters`, audit batch), which binds `EMITTER_VERSION` and the code's `source_hash` and keeps both on the arming record (refusing to arm with an empty hash); an unarmed emitter's runs are dry runs with `dry_run_reason = unarmed`; any change to `EMITTER_VERSION` or `source_hash` makes runs dry runs with `dry_run_reason = arm_stale` until re-armed; `run_emitter` (capability `cares.run_emitters`) dry-runs unless `--send` is given on an armed, non-stale emitter. | Arming approves the code to send. Per-delivery approval waits on `req-tap-cares-v0-action`. Moves to the run configuration and also binds its revision and secret ref (`req-tap-cares-runconfig-emitter-arming`). |
| req-tap-cares-v0-emitter-13 | Nothing Secret Or Received Is Kept | Proposed | No secret value, credential header, payload body, response body, or query-bearing URL appears in any record or log line, including on failure; only the HTTP status, accepted / rejected counts and a printable `remote_reference` (no C0, C1, DEL or bidi controls; no length cap) survive from a response; a response never causes a grid write. | A test fails a send and searches every record and log line. |
| req-tap-cares-v0-emitter-14 | Deferred Work Named | Backlog | Egress enforcement as listed under the named risks, and the destination work listed under "Deferred to Issue# 1369 - tap" (destination hooks and parse, grant binding, per-run selection and `destination_unapproved`, recorded destinations, the clean-up destination rules) (Issue# 1369 - tap); operator-declared CA bundle and proxy support; per-delivery nodes; several destinations per emitter; payload body retention; Administrivia emitter table, run and arm controls; API trigger; action-mediated approval; non-HTTPS channels (email, Signal, filesystem, SFTP); a cooperative stop signal (`req-tap-cares-run-backlog`); a `build-emitter` skill; declared side effects or operations, data categories, and scheme-qualified destination URIs (Issue# 1371 - tap). | Each lands as its own requirement when a consumer needs it. |
| req-tap-cares-v0-emitter-15 | Mandatory Deadline | Proposed | Every emitter declares `DEADLINE` (author-set, no core default or bound) and registration refuses one without it; each run persists `deadline_at` before any plugin hook runs; past it, the mop-up closes the run `abandoned` with `failure_kind = deadline_exceeded` (setting its clean-up pending if it recorded a send), and `record_send` refuses. | Core cannot cut an open socket; an in-flight attempt is `unknown` unless a late answer is recorded. |
| req-tap-cares-v0-emitter-16 | No Core Transport | Proposed | Core provides no HTTP client, transport wrapper, allowlist, retry or backoff for emitters; an emitter uses libraries on the instance or declared in its plugin's dependencies. | Same as collectors. |
| req-tap-cares-v0-emitter-17 | Record Before Each Attempt | Proposed | `record_send(operation, idempotency_key=None)` commits an attempt record before each request attempt and returns a permit; `operation` is a free label not checked against any declaration; it refuses a run not `running` (checked under a lock on the job row in the same transaction as the attempt record) and a run past `deadline_at`; no body, digest or size is stored. | The outbox intent. Owner ruling 2026-11-25 dropped the digest and size. |
| req-tap-cares-v0-emitter-18 | Retry Is The Emitter's, Off By Default | Proposed | Core makes one call to `emit` per run and retries nothing; an emitter that opts into retries records each attempt, chooses keys per its destination's contract, never retries a whole request after partial acceptance, and ends the run rather than wait past `deadline_at` for a `Retry-After`. | Timeouts and response caps are the emitter's too. |
| req-tap-cares-v0-emitter-19 | Key Reused After Unknown | Retired | — | Retired 2026-11-25 by owner ruling, before it reached main: core neither derives nor reuses idempotency keys; delivery identity and keys belong to the emitter and its destination's contract. |
| req-tap-cares-v0-emitter-20 | Version On The Run | Proposed | `EMITTER_VERSION` is an integer of 1 or more declared in the registered class's own body; each run stamps it, the plugin slug, release, commit and source hash as `req-tap-cares-collector-version` does for collectors, and the payload format and destination API versions the emitter reports. | |
| req-tap-cares-v0-emitter-21 | Accepted Risk Named | Proposed | The spec states that the operator approves the emitter's code to send and that where it sends is the emitter's own responsibility until Issue# 1369 - tap, not an enforced boundary; it points to Issue# 1369 - tap for egress enforcement and Issue# 1371 - tap for declarations and data categories. | `req-sec-honest-risk`. |
| req-tap-cares-v0-emitter-22 | Scheduling An Emitter Is Gated | Proposed | Writing a `SCHEDULED_TARGET` edge whose target is an `Emitter` (create or retarget), or changing `cron`, `enabled` or `max_active_runs` on a `Schedule` whose target is an `Emitter`, is refused for an actor without `cares.schedule_emitters`. | Owner ruling 2026-11-25: cadence and enabling are gated too. The target is the emitter's run configuration (`req-tap-cares-runconfig-selection-1`). |
| req-tap-cares-v0-emitter-23 | Abort Clean-Up | Proposed | An emitter may override `on_abort(run)`; when the mop-up ends its job from outside and the job recorded at least one proceeding `record_send`, the clean-up is dispatched per `req-tap-cares-run-abort-cleanup`, once per job, with the current revision of the run's configuration, and is refused (`cleanup_status = refused`, never retried) when the emitter's `source_hash` changed; it never runs after a dry run or an unarmed or `arm_stale` run. | Clean-up destination rules moved to Issue# 1369 - tap. |
| req-tap-cares-v0-emitter-24 | Per-Run Subset Of The Grant | Retired | — | Retired 2026-11-25 by owner ruling: destination grants, per-run selection and `destination_unapproved` moved to the security build-out, Issue# 1369 - tap. |
| req-tap-cares-v0-emitter-25 | Emitter Concludes Delivery | Proposed | `conclude_delivery` sets the job's `outcome` from the emitter's own reading of its attempts (a timed-out attempt then a successful idempotent retry concludes `delivered`); without it, any proceeding attempt with no answer leaves the job `unknown`. A test concludes `delivered`, then records another proceeding attempt, and observes the conclusion cleared and the outcome re-derived from the attempts until the emitter concludes again. | Codex review scenario: an extra attempt after a conclusion. |
| req-tap-cares-v0-emitter-26 | Late Evidence, Sticky Status | Proposed | `record_outcome` on an attempt of a job already closed `abandoned` stores the answer (refining an `unknown`, never overwriting a definite answer) and re-derives `outcome`; `status` stays `abandoned`; `record_send` on that job is refused. | Terminal status is sticky; evidence is not a new effect. |

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
- Schedules target `Collector` or `Emitter` nodes (emitters per `req-tap-cares-v0-emitter`).
- Schedule cadence is a five-field UTC cron expression.
- Missed scheduled slots are counted on the next observed fire through `ScheduleFire.missed_count`; they are not backfilled.
- Schedule overlap is controlled by per-schedule `max_active_runs`.
- Scheduled collection invokes `run_collection(...)` and scheduled emission invokes `run_emission(...)`; the scheduler does not create jobs or enqueue tasks directly.

Schedules should reference collector or emitter capability nodes rather than importing implementation functions directly. Pointing a schedule at an emitter requires `cares.schedule_emitters` (`req-tap-cares-v0-emitter-22`). Schedule state, fire history, missed counts, and links to collection jobs live on the TAP grid rather than in Huey.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-scheduler-1 | Collector Or Emitter Target | Proposed | v0 schedules execute `Collector` or `Emitter` nodes by stable grid identity. | See `spec-tap-cares-scheduler.md`. |
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

The shared shape of a run node, its states, the `run_id` stamp on what it mints, and the mop-up of runs left open are specified in `spec-tap-cares-run.md`.

Run records are TAP graph domain entities by default. The execution of collectors is an on-grid operation tracked with grid capabilities, nodes, edges, and service-layer provenance rather than a separate off-grid subsystem.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-cares-v0-run-record-1 | Every Execution Has A Run Node | Proposed | Each tap-cares execution path creates a durable on-grid run node. | |
| req-tap-cares-v0-run-record-2 | Failure Visibility | Proposed | Failures preserve enough structured error context to explain what failed and where. | |
| req-tap-cares-v0-run-record-3 | Linked Outcomes | Proposed | Run nodes link by edges to GRIFT batches, generated actions, or emitter delivery records they produce. | Emitter delivery records are `EmissionJob` nodes, linked from `Emitter` and `ScheduleFire` (`req-tap-cares-v0-emitter-2`). |
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
- What approval model is needed before actions can execute side-effecting emitters. (v0's stance for scheduled and manual emission is operator arming, `req-tap-cares-v0-emitter-12`; action-mediated approval is still open.)
- How authenticator records should integrate with Django auth, local deployments, and plugin-specific credential needs.
- Whether a future Secret/SecretReference BaseModel should expose secret metadata, schemas, generator commands, health, and usage edges on the grid.
- Whether "Synchronize" should become the explicit second "s" capability in tap-cares.
