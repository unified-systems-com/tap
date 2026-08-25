# TAP Flaw v0 Specification

## Philosophy

A **Flaw** is a detected *should-never-happen* condition: an invariant that TAP's own design guarantees, violated at runtime. It is categorically different from an **error** (an *expected* failure — bad input, a denied authorization, an upstream timeout) and orthogonal to **severity** (how bad the impact is). A Flaw says one specific thing: *something that was supposed to be impossible happened; a human must investigate and patch.*

The motivation is field operations and on-call sanity. When TAP runs in a customer's environment, the operator — and TAP's developers — need an unambiguous, machine-routable signal that separates "the system worked as designed and told a user no" from "the system's own guarantees were violated." Without that separation, on-call drowns: a `CRITICAL` log line could be a routine operational event *or* a latent code defect, and you cannot tell which one is worth waking up for. The whole point of a Flaw is to make "wake a human" rare, precise, and actionable.

The core doctrine is:

> A Flaw is a violated invariant, classified by *who must fix it*. It is orthogonal to severity. Every Flaw is emitted as a structured, machine-routable signal so a field instance can surface it for investigation and patching — and so a human is paged only for things that were supposed to be impossible.

Routing rides three orthogonal, machine-readable axes, so a router (eventually an AI on-call) never has to read code to dispatch: **blame class** (`req-flaw-classes`) — who must fix it; **domain tags** (`req-flaw-domain-tags`) — which specialty it belongs to; and **severity** — how urgent. The axes compose: the auth gate Flaw is `class=code` + `tags=[security]`.

Two distinctions carry the design:

- **Flaw vs error.** Errors are part of normal operation and are handled in normal control flow (a `capability_denied` is an error, not a Flaw). A Flaw is a breach of a guarantee — the code, an app/plugin, or the instance is mis-wired. If a "Flaw" can fire during correct operation, it is miscategorized.
- **Reporting vs handling.** *Reporting* a Flaw is uniform and mandatory. *Handling* its impact is per-Flaw: some Flaws are fatal to the operation (abort), some fatal to standup (refuse boot), some are fail-closed-and-continue (degrade safely, keep serving). This mirrors the Linux kernel's `BUG_ON` (halt) vs `WARN_ON_ONCE` (warn, continue) split — TAP needs both, under one reporting contract.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Distinct From Errors | A Flaw is a violated invariant, never an expected error or a user denial. |
| 2. | Blame-Classified | Every Flaw names the remediation owner via a class (`code` / `app` / `instance`). |
| 3. | Severity-Orthogonal | Flaw-ness is independent of impact; a Flaw may fail closed safely or break the instance. |
| 4. | Machine-Routable | Flaws carry blame class + domain tags + severity, emitted structured so telemetry / Paladin / on-call can route them without reading code. |
| 5. | Actionable, Not Noisy | A Flaw that fires in normal operation is a bug in the Flaw, not a Flaw in the system. |

## Roadmap Alignment

This spec supports `plan/road-products.md`:

- `step-rampart-first-paying-customer` (Rampart deployed in a company without direct involvement). Operating a field instance safely requires a clear "should-never-happen" signal so the developer is not paged for routine events and *is* paged — with enough context to patch — for genuine defects.
- It is the runtime, live-emitted counterpart to the **Paladin** post-mortem foundation's `failure_class` taxonomy (`docs/postmortems/`), and a building block of Paladin's eventual observe-and-report capability.

## Prior Art

This spec formalizes a well-trodden distinction rather than inventing one:

- **Design by Contract (Eiffel / Bertrand Meyer)** — contract violations are categorically distinct from errors, and *which clause* failed assigns blame: a **precondition** violation is the *caller's* fault; a **postcondition / invariant** violation is the *supplier's* fault. This maps directly onto TAP's blame classes (a plugin breaking a platform contract = caller/`app`; TAP's own invariant breached = supplier/`code`).
- **Linux kernel `BUG_ON()` vs `WARN_ON_ONCE()`** — a should-never-happen taxonomy fully orthogonal to log levels: `BUG` = invariant violated, halt; `WARN_ON_ONCE` = suspicious, fire once, continue. TAP's reporting-vs-handling split and "fire once" discipline follow this.
- **Rust `panic!` / `unreachable!()` vs `Result<T, E>`** — the language separates "bug, should-never-happen" from "expected, handle it."
- **Error-tracking (Sentry / Rollbar / Honeycomb)** — institutionalize "unexpected exception = a human must look," routed to a different destination than operational logs. TAP's structured `flaw_class` field is the same idea made first-class.
- **Existing TAP machinery** — the structured, actor-aware logging in `tap/logging.py` (`spec-tap-logging.md`) carries the Flaw field; the auth `unguarded_operation` error (`spec-tap-auth-v0.md`, `req-tap-auth-policy`) is the first concrete `code` Flaw.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-flaw-concept | [Flaw Concept](#flaw-concept) | Proposed | A detected invariant violation; distinct from errors/denials |
| req-flaw-classes | [Blame-Domain Classes](#blame-domain-classes) | Proposed | `code` / `app` / `instance`; future `grid` named, not built |
| req-flaw-domain-tags | [Routing Domain Tags](#routing-domain-tags) | Proposed | Registered domain-tag vocabulary (security/operational/data/…) for specialty routing |
| req-flaw-severity-orthogonal | [Orthogonal To Severity](#orthogonal-to-severity) | Proposed | Flaw class is independent of impact/severity |
| req-flaw-emission | [Structured Emission](#structured-emission) | Proposed | Exception hierarchy + structured `flaw_class` field on the log record |
| req-flaw-handling | [Reporting vs Handling](#reporting-vs-handling) | Proposed | Reporting is uniform/mandatory; impact handling is per-Flaw |
| req-flaw-actionable | [Actionable, Not Noisy](#actionable-not-noisy) | Proposed | A Flaw must never fire in correct operation; no crying wolf |
| req-flaw-telemetry | [Field Surfacing](#field-surfacing) | Proposed | Flaws are the phone-home signal; durable transport deferred |
| req-flaw-first-instances | [First Instances](#first-instances) | Proposed | `unguarded_operation` (code), plugin collision (app), capability drift (instance) |

---

### Flaw Concept
----
RID: `req-flaw-concept`  
Status: `Proposed`

A Flaw is a detected violation of an invariant TAP's design guarantees — categorically distinct from an expected error.

#### Implementation

- A Flaw type hierarchy lives in a core module (e.g. `tap.flaws`): a base `Flaw` exception with per-class subclasses (`req-flaw-classes`). The concrete module path is an implementation choice; the contract is one base type and a small, fixed set of class subtypes.
- A `Flaw` is raised (or reported via a `report_flaw(...)` helper) only when an invariant that *should be impossible to violate* is found violated.
- Flaws are **not** used for: expected errors (bad input, validation failure), authorization denials (`capability_denied` et al. are errors, not Flaws), anticipated failure modes (upstream unavailable), or control flow. Those remain ordinary errors.
- A Flaw always carries: its class (`req-flaw-classes`), the violated-invariant identity (a short stable token/name), the callsite, and safe context (no secrets, redacted per `spec-tap-auth-v0.md` / `spec-tap-logging.md`).
- The auth `unguarded_operation` error is reframed as the first `code` Flaw; it is an instance of this hierarchy, not a parallel mechanism.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-flaw-concept-1 | Base Type | Proposed | A single `Flaw` base type exists with a fixed set of class subtypes. | |
| req-flaw-concept-2 | Not Errors | Proposed | Expected errors / denials / anticipated failures are not Flaws. | |
| req-flaw-concept-3 | Carries Context | Proposed | Every Flaw carries class, invariant identity, callsite, and safe context. | |

---

### Blame-Domain Classes
----
RID: `req-flaw-classes`  
Status: `Proposed`

Every Flaw is classified by *who must fix it*. The class — not the severity — is what routes a Flaw to its remediation owner.

#### Implementation

- v0 classes:
  - **`code`** — TAP core violated its own invariant. Owner: TAP developers. Example: an unguarded service operation reached a mutation/read without an authorization decision. (Design-by-Contract: a supplier/invariant violation.)
  - **`app`** — a plugin/app broke a platform contract it was required to honor. Owner: the plugin author (and TAP, which enforces the contract). Example: two plugins resolving to the same mount prefix / a plugin overwriting another's name. (Design-by-Contract: a caller/precondition violation.)
  - **`instance`** — the instance is misconfigured or in an inconsistent runtime state not attributable to core code or a single plugin's contract breach. Owner: the operator. Example: capability sync detects undeclared drift between the registry and the DB.
- Each class declares its **remediation owner** and its **routing destination** (where a field instance surfaces it — `req-flaw-telemetry`).
- The class set is **extensible**: new classes add without reshaping existing ones. A **`grid`** class — the grid's own data is internally inconsistent — is a named, deferred future member (Backlog), not built in v0.
- The `flaw_class` vocabulary is shared with Paladin's post-mortem `failure_class` so the live signal and the post-mortem record speak the same language.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-flaw-classes-1 | Three v0 Classes | Proposed | `code`, `app`, `instance` exist, each with a declared owner + routing. | |
| req-flaw-classes-2 | Extensible | Proposed | A new class (e.g. `grid`) can be added without reshaping existing ones. | |
| req-flaw-classes-3 | Shared Vocabulary | Proposed | `flaw_class` aligns with Paladin's `failure_class` taxonomy. | |

---

### Routing Domain Tags
----
RID: `req-flaw-domain-tags`  
Status: `Proposed`

Beyond *who fixes it* (`flaw_class`), every Flaw carries one or more **domain tags** naming *which concern it belongs to*, so Flaws route to the right on-call specialty without anyone reading the code.

#### Implementation

- A Flaw carries `flaw_tags`: one or more values from the **shared registered domain-tag vocabulary**, orthogonal to `flaw_class` (blame) and severity (impact). This is the third routing axis — class → who fixes, tags → which specialty, severity → how urgent.
- **The vocabulary is defined once at the logging layer** (`spec-tap-logging.md`, `req-tap-logging-domain-tags`; code home `tap/logging_domain_tags.py`) and inherited by every reserved signal that carries tags — `FLAW`'s `flaw_tags` and `CONCERN`'s `tags` draw from the same set, so a tag means one thing across signals. It was extracted from this spec when `CONCERN` became a second consumer; the vocabulary (`security`, `operational`, `data`, `config`, `integration`) and its "registered, described, no ad-hoc strings" contract now live there. The auth `unguarded_operation` Flaw is tagged `security`.
- The vocabulary is **declared, described, and registered** — a code/spec registry, each tag with a human-readable description — exactly like the capability registry, and for the same reason: a future routing system (eventually AI on-call) reads the tag registry plus routing rules declaratively and dispatches **without investigating code paths**. Same "metadata queryable, not code-access" affordance as the real `Capability` table (`spec-tap-auth-v0.md`).
- A Flaw may carry **more than one** tag — flexibility lives here: a Flaw can be both `security` and `config`. Routing rules resolve precedence among a Flaw's tags.
- Standardness lives in the registry: using a tag absent from it is itself a `code` Flaw (mirrors "unknown capability fails", `req-tap-auth-capabilities`). Extending the vocabulary means adding a registered, described tag — never emitting an ad hoc string, which would defeat code-free routing.
- **Routing rules** — which `(flaw_class, flaw_tags, severity)` dispatches to which team / AI on-call — are declarative config, deferred (Backlog) until there are teams to route to. v0 establishes the axis and the registry so the data is already route-ready.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-flaw-domain-tags-1 | Tag Axis | Proposed | Every Flaw carries ≥1 domain tag, orthogonal to class and severity. | |
| req-flaw-domain-tags-2 | Registered Vocabulary | Proposed | Tags come from a declared, described registry; an unknown tag is itself a `code` Flaw. | |
| req-flaw-domain-tags-3 | Routing-Ready | Proposed | `class` + `tags` + `severity` is sufficient for a declarative router to dispatch without code investigation. | |

---

### Orthogonal To Severity
----
RID: `req-flaw-severity-orthogonal`  
Status: `Proposed`

Flaw class is independent of severity and impact. The two axes answer different questions.

#### Implementation

- Severity answers *how bad is the impact* (degraded request vs broken instance). Flaw class answers *who must fix it, and that it should have been impossible*. A Flaw record carries both, set independently.
- A Flaw may be low-impact (the unguarded auth gate fails closed — safe, the request is denied, the instance keeps serving) or high-impact (a plugin name collision breaks standup). Both are Flaws of equal *flaw* standing; only their severity/handling differ.
- `CRITICAL` (and the other log levels) remain the impact axis and are not overloaded to mean "defect." A Flaw is identified by its `flaw_class` field, not by being logged at a particular level.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-flaw-severity-orthogonal-1 | Two Axes | Proposed | Flaw class and severity are recorded independently. | |
| req-flaw-severity-orthogonal-2 | Level Not Overloaded | Proposed | A Flaw is identified by `flaw_class`, not by log level alone. | |

---

### Structured Emission
----
RID: `req-flaw-emission`  
Status: `Proposed`

A Flaw is emitted as a structured, machine-filterable signal, not a free-text log line.

#### Implementation

- A Flaw rides TAP's fixed-field structured message object (`spec-tap-logging.md`, `req-tap-logging-message-object`) — it does **not** add new envelope fields. A Flaw is the reserved `message_code = FLAW`, whose `message_data` payload carries `{flaw_class, flaw_tags, invariant_id, handling}`. `message_code` is the object's discriminator, so the Flaw shape is exactly the kind of structured payload that model is built to host.
- Selection is reliable at the envelope level: `message_code = FLAW` is a contract discriminator (not opaque payload), so "is this a Flaw" is a clean filter on the structured sink; a Flaw-aware consumer then reads `flaw_class` / `flaw_tags` from `message_data` to route. The nine-field envelope stays intact while Flaws remain first-class and machine-selectable.
- Emission goes through one path (the `Flaw` exception's reporting or a `report_flaw(...)` helper) so the `FLAW` `message_data` shape is uniform across every callsite — no per-site ad hoc formatting.
- The record carries the actor/request/task context already bound on the envelope (`entity_id`/`task_result_id` per `req-tap-logging-entity-ref`/`req-tap-logging-task-ref`) and the actor context (`req-tap-auth-logging`); `message_data` is redacted before any handler sees it (`req-tap-logging-message-object-5`), so Flaw context inherits redaction for free.
- Existing TAP logging site-token discipline (`req-tap-logging-site-ids`) still applies to the underlying log call.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-flaw-emission-1 | Reserved message_code | Proposed | A Flaw emits a `message_code=FLAW` record whose `message_data` carries `flaw_class`, `flaw_tags`, `invariant_id`, `handling`; no new envelope fields. | |
| req-flaw-emission-2 | One Path | Proposed | Flaws emit through one uniform reporting path, not per-site formatting. | |
| req-flaw-emission-3 | Filterable | Proposed | `message_code=FLAW` cleanly selects all Flaws; `flaw_class`/`flaw_tags` route them. | |

---

### Reporting vs Handling
----
RID: `req-flaw-handling`  
Status: `Proposed`

Reporting a Flaw is uniform and mandatory. Handling its impact is chosen per-Flaw.

#### Implementation

- **Reporting is mandatory and uniform**: a detected Flaw is always emitted (`req-flaw-emission`). A Flaw is never swallowed, downgraded to a routine log, or silently continued past.
- **Handling is per-Flaw**, along the kernel `BUG` vs `WARN` axis:
  - *fatal-to-operation* (`abort_operation`) — abort the current operation (e.g. raise, roll back the batch).
  - *fatal-to-standup* (`refuse_boot`) — refuse to boot / come up (e.g. a plugin contract violation at boot).
  - *fail-closed-and-continue* (`fail_closed_continue`) — deny the specific request safely and keep serving (e.g. the unguarded gate fails closed for that op; the instance stays up).
  - *observe-and-continue* (`observe_continue`) — the pure `WARN_ON_ONCE` analog: record the violation and let the operation **proceed unchanged**. A detection tripwire, not a block — it denies nothing. Reserved for a control whose false-positive cost is catastrophic and whose blocking value is marginal (a real attacker could bypass it anyway), where alerting for incident-response review beats prevention. This handling fails *open*, deliberately and loudly; the residual risk (the flagged operation still ran) must be named at the callsite per `spec-security-posture` honest-risk. Emits at WARNING — nothing was blocked — but the `security` tag, not the level, is what routes it.
- The choice is recorded with the Flaw so a reader knows whether the instance is still trustworthy. Fail-closed-and-continue must be genuinely safe (no partial mutation, no data leak) — degrade, never limp. Observe-and-continue makes no safety claim about the operation itself — its value is the signal, so it is only appropriate where the block would cost more than the exposure it prevents.
- A Flaw must not be "handled" by suppression: catching a Flaw to continue without reporting is itself a `code` Flaw.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-flaw-handling-1 | Always Reported | Proposed | A detected Flaw is always emitted; never swallowed or downgraded. | |
| req-flaw-handling-2 | Per-Flaw Impact | Proposed | Handling (abort / refuse-boot / fail-closed-continue / observe-continue) is chosen per Flaw and recorded. | |
| req-flaw-handling-4 | Observe-Continue Is Detection | Proposed | `observe_continue` records the Flaw and proceeds unchanged (WARN_ON_ONCE); it blocks nothing, emits at WARNING, and is reserved for controls where a hard block would cost more than the exposure it prevents. The residual risk must be named at the callsite. | Boot out-of-band invocation tripwire is the first consumer (`tap_boot.orchestrator`) |
| req-flaw-handling-3 | No Silent Suppression | Proposed | Catching a Flaw to continue without reporting is itself a `code` Flaw. | |

---

### Actionable, Not Noisy
----
RID: `req-flaw-actionable`  
Status: `Proposed`

A Flaw must be worth a human's attention every time it fires. Noise defeats the entire purpose.

#### Implementation

- A Flaw represents a genuine should-never-happen invariant. If a condition can occur during correct operation, it is **not** a Flaw — model it as an ordinary error. Miscategorizing an expected condition as a Flaw is itself a defect.
- Flaws are de-duplicated / rate-limited where a single defect could fire in a hot loop (the kernel `WARN_ON_ONCE` lesson): report the defect, do not spam the on-call signal. (v0 may report-every-time; "once"/aggregation semantics are noted in Backlog if volume demands.)
- The bar: every Flaw that reaches on-call should be actionable — it names a real invariant, a real callsite, and a real owner. A field instance's Flaw stream should be empty in steady state; a non-empty stream means real work.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-flaw-actionable-1 | Genuine Invariants Only | Proposed | A condition that can occur in correct operation is an error, not a Flaw. | |
| req-flaw-actionable-2 | Steady-State Empty | Proposed | A correctly-running instance emits no Flaws. | |

---

### Field Surfacing
----
RID: `req-flaw-telemetry`  
Status: `Proposed`

Flaws are the signal a deployed instance surfaces for investigation and patching.

#### Implementation

- A Flaw is shaped to be routed back to the operator and/or TAP developers — it is the "phone home, something that should be impossible happened" signal that lets a field instance be operated without paging a human for routine events.
- v0 scope: structured emission (`req-flaw-emission`) plus clear local surfacing (logs an operator can find, and a class that distinguishes a Flaw from routine output). A **durable phone-home transport** (outbound reporting channel, aggregation service) is deferred — but the v0 signal is *shaped* so that transport can consume it without rework.
- Flaws feed the Paladin observe-and-report foundation: the runtime `flaw_class` stream is the live counterpart to the post-mortem `failure_class` corpus, so Paladin can eventually correlate live Flaws with post-mortem patterns.
- Routing is two-dimensional: `flaw_class` selects the fix-owner (`code` → TAP developers, `app` → the plugin author and TAP, `instance` → the operator), while `flaw_tags` (`req-flaw-domain-tags`) select the on-call **specialty** (security, operational, data, …) — eventually disparate on-call teams (likely AI). The two axes compose, and the eventual routing rules match on both plus severity.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-flaw-telemetry-1 | Surfaced For Investigation | Proposed | Flaws are surfaced as the field-investigation signal, distinct from routine logs. | |
| req-flaw-telemetry-2 | Transport-Ready | Proposed | The v0 signal is shaped so a future durable phone-home transport consumes it without rework. | |
| req-flaw-telemetry-3 | Paladin Feed | Proposed | The `flaw_class` stream feeds the Paladin observe-and-report foundation. | |

---

### First Instances
----
RID: `req-flaw-first-instances`  
Status: `Proposed`

v0 wires three concrete Flaws, one per class, to prove the mechanism end to end.

#### Implementation

- **`code` Flaw — `unguarded_operation` (implemented, and class-aware).** A mutation or Gryphon/Search read reaches its commit/return point with no authorization decision recorded, OR a node/edge write reaches the ORM outside a service-layer write scope (`spec-tap-auth-v0.md`, `req-tap-auth-policy` / `req-tap-auth-orm-read-backstop` / `req-tap-auth-write-batch-routing`). Tags: `[security]`. Handling: abort-operation (fails closed). Emission is via `tap.flaws.report_service_layer_bypass`, wired at the two backstops (`tap_auth.enforcement._raise_unguarded` for the read/commit gates; `tap_grid.write_guard.enforce_service_write` for the ORM write gate). **Blame is decided from the offending callsite, not hard-coded `code`:** a bypass from `plugins/<slug>/…` emits an `app` Flaw (the plugin author must route through the service layer), first-party code emits `code` (`flaw_class_for_path`). So this single mechanism produces *both* the `code` and one form of the `app` instance, and every Flaw names the offending callsite for routing. This is the originating instance.
- **`app` Flaw — plugin mount/name collision.** Two plugins resolve to the same `/plugins/<label>/` mount prefix, or a plugin overwrites another plugin's name (existing guards: `tap_api.resolve_plugin_mounts` `ImproperlyConfigured`; the GRIFT `envelope_payload_name_mismatch` / rename discipline). Tags: `[integration]`. Handling: fatal-to-standup. These existing hard errors are reclassified as `app` Flaws so they emit the structured signal.
- **`instance` Flaw — capability sync drift.** Capability sync finds undeclared drift between the canonical registry and the DB projection (`spec-tap-auth-v0.md`, `req-tap-auth-capabilities`). Tags: `[security, config]`. Handling: fatal-to-operation (the sync hard-fails). It is an `instance` Flaw — misconfiguration / weird instance state, not core code at fault.
- Wiring these three proves the hierarchy, the structured emission, and all three classes against real code paths.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-flaw-first-instances-1 | Code Instance | Implemented | `unguarded_operation` emits a `security` Flaw at both the enforcement backstop and the ORM write gate, class-aware by offending callsite (`code` for first-party, `app` for `plugins/`). Impl: `tap.flaws.report_service_layer_bypass`; proof: `tap/tests/test_flaws.py`, `tap_grid/tests/test_write_guard.py`. | |
| req-flaw-first-instances-2 | App Instance | Proposed | Plugin mount/name collision emits an `app` Flaw. | |
| req-flaw-first-instances-3 | Instance Instance | Proposed | Capability sync drift emits an `instance` Flaw. | |

---

## Backlog

- **`grid` Flaw class** — the grid's own data is internally inconsistent (dangling edges, broken invariants on the spine). Named here; deferred.
- Durable phone-home transport — an outbound reporting channel / aggregation endpoint a field instance reports Flaws to.
- `WARN_ONCE`-style de-duplication / rate-limiting and aggregation for hot-path Flaws, if volume demands.
- A queryable on-grid Flaw record (a node/model), so Flaws are first-class graph-visible artifacts — intersects the Paladin model and `feedback_create_the_dedicated_node_type`.
- Operator-facing Flaw surface (a panel / page listing recent Flaws and their classes).
- Declarative routing-rule configuration — which `(flaw_class, flaw_tags, severity)` dispatches to which team / AI on-call — likely a boot-profile / config concern. v0 establishes the axes + tag registry; the rules come when there are teams to route to.

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
