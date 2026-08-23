# AI Integration Specification

## Philosophy

For most of software history a system's operation has been a function of two players: **the code** (what runs) and **the humans** (who build, operate, and use it). TAP is being built in an era where that is no longer true. There is a **third player** — the **AI assistants** that observe, guide, support, and increasingly *operate* the system: internal support AIs, in-product concierges and guides, on-call incident responders, and external/integrated agents. This spec is TAP's center of gravity for **Player 3**.

It has two faces, and they are deliberately held in one spec because they are one idea seen from two sides:

- **Posture — build *so that* AI can operate.** A standing engineering discipline: treat an AI helper as a first-class consumer of the system's state, decisions, failures, and affordances, co-equal with a human operator. Prefer machine-legible signals, declarative queryable metadata, and AI-operable procedures over surfaces only a human reading code can use. This is the generalization the `CONCERN` discipline (`spec-security-posture.md`, `req-sec-concern-gaps`) is a single instance of — a `CONCERN` exists *because* an internal security AI monitors it.
- **Integration — the AI assistants built *into* the system.** The `tap_ai` surface and the assistants it hosts: the customer-facing user-simulating guide, the onboarding concierge, the internal on-call/diagnostic AIs, and (later) agentic helpers that act under a named actor. The read-only graph-reasoning surface that turns "TAP has your data on a graph" into "and an AI walks you through it."

**v0 is deliberately bounded and read-only.** Like the secrets subsystem, v0 AI is boring on purpose: it *reads* the graph — traverses, summarizes, explains, suggests — and **must not write core graph state** (`req-ai-readonly-v0`, mirroring the standing TAP AI Rule). Suggestions are surfaced to a human or a named actor, never silently applied. When AI eventually mutates state, it does so through the existing service layer under a named delegated actor (`req-tap-auth-actor-model`, on-behalf-of) — never a parallel mutation API. The agentic, writing, plugin-generating future is named here and deferred, not built ahead of demand.

**The beanbag is the existence proof.** The most sophisticated AI integration in TAP's story already runs every day: George building TAP live inside Claude Code — reading the graph, generating plugins, adapting code, tailoring the system in conversation. That dev-environment "beanbag" is the north star for what integrated in-product AI becomes; the roadmap's in-app AI is the productized descendant of the thing already building it.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Player 3 Is First-Class | Treat AI assistants as a primary consumer of system state/decisions/failures, co-equal with humans. |
| 2. | Machine-Legible By Default | Emit structured, routable signals and declarative queryable metadata; prefer them over human-only prose or code-reading. |
| 3. | Name The AI Consumer | Where a surface or signal exists for an AI to act on, say which AI and what it does — legibility is a designed contract, not a hope. |
| 4. | Read-Only, Least-Privilege v0 | v0 AI reads the graph and suggests; it never writes core graph state, and any future write rides the service layer under a named actor. |
| 5. | Bake It In At Construction | AI-legibility is a cheap-now / expensive-to-retrofit edge; lay it while building the surface (esp. the plugin system), per the security-posture reversibility argument. |

## Prior Art

- **Structured, machine-first observability** — OpenTelemetry semantic conventions, structured events over grep-the-string logs: the recognition that machines, not just humans, consume operational output. TAP's structured message object + reserved signals (`spec-tap-logging.md`) are this idea, aimed at an AI consumer.
- **RAG over your own data** — retrieval-augmented generation grounding an LLM in a specific, trusted corpus. TAP's corpus is the graph; `tap_ai` is read-only RAG/traversal over it.
- **Agentic assistants with least-privilege tool-use** — modern agents act through scoped tools under explicit permission. TAP's answer is the capability system + named actors (`spec-tap-auth-v0.md`): when AI acts, it acts as a bounded, named actor, not an ambient god-process.
- **Self-describing systems** — schemas, descriptions, and registries that let a consumer reason without reading source. TAP already requires descriptions on JSON structures and keystones, and ships declarative capability/tag/discovery registries ("metadata queryable, not code-access").
- **AI for on-call / post-mortem** — routing incidents to specialists by machine-readable class. TAP's Paladin foundation + FLAW routing axes (`spec-tap-flaw-v0.md`) are shaped for an eventual AI on-call.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-ai-player-three | [Player 3 Is First-Class](#player-3-is-first-class) | In Force | The reframe: an AI operator is a primary, designed-for consumer of the system |
| req-ai-machine-legible | [Machine-Legible By Default](#machine-legible-by-default) | In Force | Structured routable signals + queryable metadata over human-only prose / code-reading |
| req-ai-name-the-consumer | [Name The AI Consumer](#name-the-ai-consumer) | In Force | A surface/signal built for an AI names which AI monitors/acts and what it does |
| req-ai-operable-procedures | [AI-Operable Procedures](#ai-operable-procedures) | In Force | Skills/runbooks as first-class AI-executable procedures; `/diagnose-failed-session-spawn` is the first instance |
| req-ai-readonly-v0 | [Read-Only v0](#read-only-v0) | In Force | `tap_ai` reads/summarizes/suggests; never writes core graph state; future writes ride the service layer under a named actor |
| req-ai-roles | [AI Role Taxonomy](#ai-role-taxonomy) | Proposed | Internal / integrated / external assistants — named, not all built |
| req-ai-surface | [The tap_ai Surface](#the-tap_ai-surface) | Proposed | The read-only graph-reasoning app: RAG/traversal, Claude-backed, capability-gated, actor-bound |
| req-ai-first-integration | [First Integration — User-Simulating Guide](#first-integration--user-simulating-guide) | Proposed | The launch-ready demo wow: a read-only guide that walks the 20x story |
| req-ai-agentic-future | [Agentic Future](#agentic-future) | Backlog | Tool-using, service-layer-writing, plugin-generating AI under a delegated actor — named, deferred |

---

### Player 3 Is First-Class
----
RID: `req-ai-player-three`
Status: `In Force`

The system's operation is a function of **code + humans + AI**. An AI assistant — internal support system, in-product concierge, on-call responder, integrated agent — is a **primary consumer** of the system's state, decisions, failures, and affordances, to be designed for deliberately, not accommodated after the fact.

#### Implementation

- When building any surface, ask the design question explicitly: *how does an AI helper observe, operate, and reason about this?* — alongside "how does a human?" and "what does the code do?".
- This is a **standing filter**, like the security posture: it applies whenever work touches a surface an AI would consume, not as a separate feature.
- It is **bounded by the same discipline as the security posture** — take the cheap, foundational, build-once legibility edges (`req-ai-machine-legible`); do not build speculative agentic machinery ahead of demand (`req-ai-agentic-future`).

#### Player-3 affordances already laid

These were built (some before the discipline was named) *because* an AI consumer made them worth it — the evidence the reframe is real:

- **The structured message object** (`spec-tap-logging.md`, `req-tap-logging-message-object`) — "the object, not the string, is the record": a machine-consumable event, not a line to grep.
- **The reserved signal family** (`FLAW` / `ABORT` / `CONCERN`, `req-tap-logging-reserved-signals`) with the shared **domain-tag** routing vocabulary (`req-tap-logging-domain-tags`) — machine-selectable events with stable routing keys.
- **`CONCERN`** (`spec-security-posture.md`, `req-sec-concern-gaps`) — a detective signal whose primary consumer *is* an internal security AI.
- **Declarative queryable registries** — capabilities, domain tags, and the service-layer discovery system: "metadata queryable, not code-access."
- **Paladin + FLAW routing** (`spec-tap-flaw-v0.md`) — a `flaw_class`/`flaw_tags` stream shaped for an eventual AI on-call.
- **AI-operable skills** — `/diagnose-failed-session-spawn` reads the `TAP-ABORT` sentinel and diagnoses.
- **Self-describing state** — required descriptions on JSON structures and grid keystones, so an AI reads context instead of guessing.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-ai-player-three-1 | Designed-For Consumer | In Force | Surfaces an AI would consume are designed with the AI consumer in mind, not retrofitted. | |
| req-ai-player-three-2 | Standing Filter | In Force | The reframe applies as a standing filter across work, bounded by the cheap-edge discipline. | Parallels `spec-security-posture.md`. |

---

### Machine-Legible By Default
----
RID: `req-ai-machine-legible`
Status: `In Force`

Prefer surfaces an AI can consume without reading source: **structured, routable signals** and **declarative, described, queryable metadata** — over human-only prose, unstructured logs, or state only legible by reading code.

#### Implementation

- **Signals** carry a stable machine key and a described routing axis (the reserved-signal `message_code` + `message_data`; the domain-tag vocabulary). A new operational event an AI should act on is a structured signal, not a bespoke log string.
- **Metadata is declarative and described** — registries (capabilities, tags, collectors, types) carry human/AI-readable descriptions so a consumer dispatches and reasons *without investigating code paths*. This is the same "metadata queryable, not code-access" affordance across the platform.
- **State is self-describing** — JSON structures and grid nodes carry descriptions (the standing JSON-descriptions discipline), so an AI reading the graph gets intent, not just values.
- This is the **cheap, foundational edge**: adding structure/description while building a surface is near-free; retrofitting an opaque surface for an AI consumer later is expensive (`req-sec-cheap-edges` reasoning, applied to legibility).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-ai-machine-legible-1 | Structured Over String | In Force | An operational event an AI should consume is emitted as a structured signal with a stable key, not a bespoke log string. | |
| req-ai-machine-legible-2 | Declarative Metadata | In Force | Dispatch/reasoning metadata is a described, queryable registry, not something an AI must read code to recover. | |
| req-ai-machine-legible-3 | Self-Describing State | In Force | Graph/JSON state carries descriptions so an AI reads intent, not only values. | Ties the JSON-descriptions + keystone disciplines. |

---

### Name The AI Consumer
----
RID: `req-ai-name-the-consumer`
Status: `In Force`

Where a surface or signal exists *for an AI to act on*, the spec that defines it **names which AI consumes it and what it does** — so legibility is a designed contract with a stated consumer, not an unowned hope that "some AI might use this someday."

#### Implementation

- A signal/surface built for AI consumption states its consumer in prose: e.g. `CONCERN` names "an internal security AI monitors the stream"; `FLAW` names "eventually an AI on-call routes on `flaw_class`/`flaw_tags`."
- Naming the consumer forces the payload to be *sufficient* for that consumer — it is the design check that keeps a "machine-legible" signal from being legible in principle but useless in practice.
- An unnamed "for AI" affordance is suspect the same way an unjustified capability split is: if no consumer can be named, the affordance is speculative (defer it) or mis-scoped (a plain human surface).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-ai-name-the-consumer-1 | Stated Consumer | In Force | A surface/signal built for AI names the consuming AI and its action in the defining spec. | |
| req-ai-name-the-consumer-2 | Payload Sufficiency | In Force | The named consumer's needs justify the signal's payload; an affordance with no nameable consumer is deferred, not shipped. | |

---

### AI-Operable Procedures
----
RID: `req-ai-operable-procedures`
Status: `In Force`

Operational procedures — diagnostics, runbooks, recovery flows — are authored as **first-class, AI-executable procedures**, not tribal knowledge or human-only docs. An AI support system should be able to *run* a procedure, not merely read about it.

#### Implementation

- Repo **skills** (`<app>/skills/`, wired by `scripts/wire-skills.sh`) are the v0 vehicle: a skill is a named, described, executable procedure an AI (or a human) invokes. `/diagnose-failed-session-spawn` is the first instance — it reads the `TAP-ABORT` sentinel and pinpoints the failing boot step.
- A procedure keys off **machine-legible signals** (`req-ai-machine-legible`) rather than screen-scraping human output: `/diagnose-failed-session-spawn` works *because* `ABORT` is a structured sentinel.
- More are converging from several angles (spawn repair, validation triage); the discipline is to write the runbook as an operable skill, so the knowledge is executable, not narrative.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-ai-operable-procedures-1 | Runbooks Are Executable | In Force | An operational procedure is authored as an AI-invokable skill, not human-only prose, where feasible. | `/diagnose-failed-session-spawn` is the reference. |
| req-ai-operable-procedures-2 | Signal-Keyed | In Force | A procedure keys off structured signals, not scraped human output. | Depends on `req-ai-machine-legible`. |

---

### Read-Only v0
----
RID: `req-ai-readonly-v0`
Status: `In Force`

**v0 AI must not write core graph state.** `tap_ai` reads the graph — traverses, summarizes, explains, suggests — and surfaces its output to a human or a named actor. This is the standing TAP AI Rule made a first-class requirement.

#### Implementation

- `tap_ai` is a **read-only** consumer of the graph in v0: RAG, traversal, summarization, suggestion. No `TAP-managed` node/edge writes; no parallel mutation API; background AI work must not silently mutate graph state (`spec-*` background-task rule).
- **Suggestions are proposals, not actions** — surfaced for a human/actor to accept, never auto-applied to the grid.
- **When AI eventually writes** (`req-ai-agentic-future`), it goes through the **existing service layer under a named delegated actor** (`req-tap-auth-actor-model`; the on-behalf-of delegation placeholder `req-tap-auth-ai-placeholder`) — the same chokepoint, authz, FLIP, and provenance as any other write. AI never gets a bypass. `is_superuser` is not a service bypass (`spec-tap-auth-v0.md`); neither is "it's the AI."
- Reading the *existing* graph (not the plugin refactor) is what lets the first AI integration **parallelize** with the plugin work per the roadmap fork.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-ai-readonly-v0-1 | No Graph Writes | In Force | v0 `tap_ai` performs no writes to TAP-managed nodes/edges. | Standing TAP AI Rule. |
| req-ai-readonly-v0-2 | Suggestions Not Actions | In Force | AI output is surfaced as a proposal for a human/actor, never auto-applied. | |
| req-ai-readonly-v0-3 | Future Writes Ride The Service Layer | In Force | Any future AI write goes through the service layer under a named delegated actor, with full authz/FLIP/provenance; no parallel mutation path, no bypass. | `req-tap-auth-actor-model` / `-ai-placeholder`. |

---

### AI Role Taxonomy
----
RID: `req-ai-roles`
Status: `Proposed`

The assistants TAP builds toward, named so scope stays honest — **not all are built in v0.** Three families by where the AI sits relative to the product:

- **Internal (operate the platform, not customer-facing).**
  - *On-call / incident AI* — consumes the `FLAW` / `ABORT` / `CONCERN` streams and the Paladin post-mortem corpus; routes and responds by `flaw_class`/`flaw_tags`/`concern_type`.
  - *Diagnostics* — boot/spawn/validation failure triage (`/diagnose-failed-session-spawn` is the first).
  - *Security monitor* — the named consumer of the `CONCERN` stream (`req-sec-concern-gaps`).
- **Integrated (in-product, customer-facing).**
  - *User-simulating demo guide* — the launch-ready first integration (`req-ai-first-integration`): walks a viewer through the 20x samsite story.
  - *Onboarding concierge / assistant* — what a user meets when the instance is up and configured; grows in complexity and customization over time (roadmap `step-rampart-first-paying-customer` "AI Onboard").
  - *Assessment / analysis helper* — summarizes findings, explains KSI/compliance status, answers "why does this matter."
  - *Plugin-development assistant* — the in-app descendant of the beanbag: helps author/adapt plugins (the "plugin-dev plugin"). Deep/agentic; mostly `req-ai-agentic-future`.
- **External (partner / third-party AI integrating with TAP).** A partner's AI reaching TAP through an API/MCP surface. Named; deferred.

Each role, when built, obeys `req-ai-readonly-v0` (v0) and names its consumer/surface (`req-ai-name-the-consumer`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-ai-roles-1 | Named Not Built | Proposed | The internal/integrated/external role taxonomy is enumerated so scope is honest; only the demand-driven roles are built. | |
| req-ai-roles-2 | First Roles | Proposed | The v0 roles are the internal diagnostic/security consumers (already emerging) and the user-simulating demo guide. | |

---

### The tap_ai Surface
----
RID: `req-ai-surface`
Status: `Proposed`

`tap_ai` is the sixth scaffolding app (per CLAUDE.md build order) — the **read-only graph-reasoning surface**: RAG + graph traversal + summarization/suggestion over the TAP graph, exposed to the integrated assistants.

#### Implementation

- **Read-only over the graph** (`req-ai-readonly-v0`): reads through the service-layer read path, capability-gated, under a **named actor** (a program actor, or a delegated on-behalf-of actor for a user-facing session). No `User=None`.
- **Provider: Claude.** Backed by the latest Claude models (the Opus / Sonnet / Haiku family; model selection is an implementation/config choice, deliberately **not** pinned in canon so it does not age). Provider credentials resolve through the secrets subsystem (`spec-tap-cares-secrets.md`) as a consumer-scoped secret, never in code.
- **Does not depend on the plugin refactor** — it reads the *existing* graph, which is why the first AI integration parallelizes with plugin work (roadmap fork).
- **Capability-gated and least-privilege** — AI reads are authorized like any other read; the AI actor holds a bounded read capability set, not a god-bit.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-ai-surface-1 | Read-Only Graph Reasoning | Proposed | `tap_ai` provides RAG/traversal/summarization over the graph via the service-layer read path, capability-gated, actor-bound. | |
| req-ai-surface-2 | Claude-Backed, Unpinned | Proposed | Backed by the latest Claude models; the specific model is config, not canon; credentials resolve via the secrets subsystem. | |
| req-ai-surface-3 | Plugin-Independent | Proposed | The surface reads the existing graph and does not depend on the plugin refactor. | Enables the roadmap parallelization. |

---

### First Integration — User-Simulating Guide
----
RID: `req-ai-first-integration`
Status: `Proposed`

The launch-ready **demo wow** (`plan/road-rampart.md` `step-rampart-launch-ready`, item 4): a real, integrated, read-only AI guide that walks a viewer through the samsite FedRAMP-20x story on the graph — the capability that lets a customer conversation include "and here's the AI walking you through it."

#### Implementation

- **Read-only** (`req-ai-readonly-v0`): it narrates and navigates the *existing* graph — the architecture, a finding, the KSI scoreboard — it does not mutate.
- It is the first concrete `tap_ai` consumer and the proof of the surface (`req-ai-surface`).
- Genuinely useful, not a parlor trick: it reads real graph state and explains it, so it is a leave-behind capability, not a demo-only script.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-ai-first-integration-1 | Walks The 20x Story | Proposed | A read-only guide navigates and explains the samsite 20x graph (architecture → finding → KSI scoreboard). | The launch-ready done-test's AI half. |
| req-ai-first-integration-2 | Real, Not Scripted | Proposed | It reasons over real graph state, not a canned script; useful as a leave-behind. | |

---

### Agentic Future
----
RID: `req-ai-agentic-future`
Status: `Backlog`

The deeper, tool-using, **writing** AI is named here and deferred: agentic assistants that take actions, generate and adapt plugins, permute system state, and operate more autonomously — the productized descendant of the beanbag.

#### Implementation (deferred — named, not built)

- **Writes ride the service layer under a delegated actor** (`req-ai-readonly-v0-3`): when agentic AI mutates state, it is a named on-behalf-of actor through the one chokepoint, with full authz/FLIP/provenance — never a bypass.
- **Tool-use is capability-scoped** — an agent's tools are bounded capabilities, not ambient power; least privilege applies to AI exactly as to a program actor.
- **Plugin generation / a plugin-dev assistant** — the in-app beanbag; the "plugin-dev plugin." Deferred until the plugin system is wrapped and the write-path actor model for AI is real.
- Do **not** build agentic/writing machinery ahead of the read-only surface and a real demand (roadmap: deeper/agentic AI is explicitly out of scope for the launch-ready step).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-ai-agentic-future-1 | Named, Deferred | Backlog | Agentic/writing/plugin-generating AI is tracked as a named future, not built in v0. | |
| req-ai-agentic-future-2 | Actor-Bound Writes | Backlog | Agentic writes ride the service layer under a delegated actor with full authz/FLIP/provenance; tools are capability-scoped. | No AI bypass. |

---

## Relationship To Other Specs

- **`spec-security-posture.md`** — the sibling doctrine. The `CONCERN` discipline (`req-sec-concern-gaps`) is a concrete instance of build-for-AI; this spec is its generalization. Both are standing filters that judge whether a cheap, foundational edge should be laid while the surface is open.
- **`spec-tap-logging.md`** — the machine-legible substrate: the structured message object, the reserved signals, and the domain-tag routing vocabulary an AI consumes.
- **`spec-tap-flaw-v0.md`** — Paladin + `flaw_class`/`flaw_tags` shaped for AI on-call routing.
- **`spec-tap-auth-v0.md`** — the actor model + capability system that bounds an AI actor (delegated on-behalf-of, least privilege, no bypass) when AI eventually acts.
- **`spec-tap-cares-secrets.md`** — where `tap_ai`'s provider credentials resolve (consumer-scoped, off-grid).
- **`plan/road-rampart.md`** / **`plan/product-map.md`** — the first AI integration is a launch-ready gate item; the concierge/onboard and agentic paths are later steps.

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed | Requirement has been designed but not yet accepted for implementation. |
| Approved for Development | Requirement is accepted and ready to be implemented. |
| In Development | Actively being worked on. |
| Implemented | Has been written. |
| Verified | Has met the acceptance criteria. |
| In Force | Standing doctrine: in effect now, and never "completed". Expects conformance from other work rather than an implementation of its own. |
| Refactoring | In the process of being re-worked. |
| Deprecating | In the process of being deprecated. |
| Deprecated | No longer part of the current architecture. |
