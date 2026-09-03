# Grid User Context Specification

## Philosophy

User context is the durable server-side state that tells TAP how this user is currently viewing the graph. It exists so graph services can honor user-scoped context such as time travel without requiring every page, panel, or API client to become context-aware on its own.

The first version is intentionally narrow. It stores only the user's current time-travel position, but it should be designed as an extensible envelope for future context dimensions such as perspective, active draft, or other scoped viewing modes.

## Goals

|    |              |                                                                                           |
| :---: | ---       | ---                                                                                       |
| 1. | Server-Side  | Context is resolved on the server so all TAP surfaces can share the same view semantics   |
| 2. | Service-Layer | Grid reads/searches can consume context without every caller re-implementing it          |
| 3. | Time-Travel Ready | The first context field supports the historical `as_of` experience                   |
| 4. | Explicit      | Explicit per-call overrides remain possible and win over stored ambient context          |
| 5. | Extensible    | The model leaves room for future context dimensions and change notifications             |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-userctx-record | [Per-User Context Record](#per-user-context-record) | Proposed | Each user has a server-side current-context record or equivalent durable projection |
| req-grid-userctx-time | [Current Time Context](#current-time-context) | Proposed | V1 stores a user-scoped current transaction-time cutoff |
| req-grid-userctx-resolution | [Context Resolution Rules](#context-resolution-rules) | Proposed | Explicit call parameters override ambient stored context |
| req-grid-userctx-service | [Service-Layer Context Integration](#service-layer-context-integration) | Proposed | Reads/searches consult effective user context when historical parameters are absent |
| req-grid-userctx-mutation | [Context Mutation Surface](#context-mutation-surface) | Proposed | TAP exposes a first-class way to read and update user context |
| req-grid-userctx-events | [Context Change Notifications](#context-change-notifications) | Backlog | Listener notification is deferred but reserved as part of the design |

## Explanation

User context is not just a web-view convenience object. It is a server-side execution aid that lets TAP answer the question:

"When this user asks for graph data right now, what world are they looking at?"

The initial use case is time travel. The viewer, editor, API, and any later surfaces should all be able to resolve the same user-scoped historical view through the service layer.

This context model applies to both `human` and `programmatic` users. A human may carry context across viewer pages, while a programmatic actor may use the same mechanism to maintain consistent graph-view semantics across service calls.

This capability composes directly with `spec-grid-history-timetravel.md`. Time travel continues to be a service-layer feature with an explicit `as_of` option. User context adds an ambient per-user default so callers do not have to thread that option manually through every request path.

### Per-User Context Record
----
RID: `req-grid-userctx-record`

Status: `Proposed`

TAP should maintain a durable current-context record per authenticated user.

#### Status Details
Proposed as the minimum server-side state needed to make historical viewing follow the user across pages and entry points.

#### Implementation
The storage contract should be:

1. Each authenticated TAP user may have one current-context record.
2. The record is server-side and durable across requests.
3. The context record is keyed to the canonical TAP user, not to a browser tab, panel instance, or session row.
4. The shape may be represented as a dedicated model, a one-to-one extension, or another durable server-owned store, but it must behave like a first-class TAP concept.
5. Absence of a context record means the user is in default current-state mode.
6. The same contract applies whether the user is `human` or `programmatic`.

#### Development
This should be modeled at the account level first. Tab-level or session-level context may still be useful later, but it solves a different problem.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-userctx-record-1 | One Context Per User | Proposed | TAP supports a durable current-context record keyed to the canonical user. | |
| req-grid-userctx-record-2 | Server-Owned State | Proposed | User context is stored and resolved on the server rather than only in client-side memory. | |
| req-grid-userctx-record-3 | Default Means Current State | Proposed | If no context record exists, TAP resolves reads and searches in ordinary current-state mode. | |

#### Future
If collaborative or multi-tab semantics later matter, TAP may add narrower scopes beneath the user-level default rather than weakening the server-side user context contract.

### Current Time Context
----
RID: `req-grid-userctx-time`

Status: `Proposed`

The first user-context field is the user's current historical transaction-time cutoff.

#### Status Details
Proposed as the narrow v1 scope needed to support the time-travel design already being discussed.

#### Implementation
The v1 field contract should be:

1. The context record may store `current_time` or an equivalent field name representing transaction-time `as_of`.
2. The timestamp is interpreted using the same semantics as `timetravel_as_of` in `spec-grid-history-timetravel.md`.
3. A null or absent value means current-state mode.
4. The field does not imply range semantics, replay semantics, or write-into-the-past semantics.
5. The field is ambient view state, not historical truth metadata stored on graph objects.

#### Development
Keeping this to one timestamp is the cleanest first pass. It solves the important problem without prematurely freezing broader context vocabulary.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-userctx-time-1 | Single Historical Cutoff | Proposed | V1 user context stores one transaction-time cutoff rather than a range or replay state machine. | |
| req-grid-userctx-time-2 | Null Means Present Day | Proposed | An absent or null time context resolves to current-state reads. | |
| req-grid-userctx-time-3 | Same Semantics As Time Travel | Proposed | The stored time context reuses the same historical semantics as explicit `timetravel_as_of` service calls. | |

#### Future
Later context fields may add perspective, dimension, active draft, or UI-specific scrubbing metadata, but those should be additive to this minimal contract.

### Context Resolution Rules
----
RID: `req-grid-userctx-resolution`

Status: `Proposed`

TAP should resolve an effective context by combining explicit call parameters with the user's stored ambient context, with explicit per-call parameters taking precedence.

#### Status Details
Proposed because without a clear precedence rule, historical reads will become surprising very quickly.

#### Implementation
The precedence rules should be:

1. An explicit per-call historical argument such as `timetravel_as_of` wins over stored user context.
2. If no explicit historical argument is supplied, TAP may consult the authenticated user's current context.
3. If neither exists, TAP reads current canonical state.
4. System/internal calls with `user=None` do not inherit any user-scoped context unless a caller explicitly supplies one.
5. Effective context resolution should happen once in the service layer, not independently in every endpoint or panel.

#### Development
This rule preserves both convenience and predictability. Ambient context is helpful; silent override of explicit parameters is not.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-userctx-resolution-1 | Explicit Beats Ambient | Proposed | Explicit `as_of` or equivalent per-call parameters override stored user context. | |
| req-grid-userctx-resolution-2 | Ambient Used When Explicit Missing | Proposed | Service calls without an explicit historical override may consult the user's stored context. | |
| req-grid-userctx-resolution-3 | No Hidden Context For System Calls | Proposed | Internal/system calls do not silently inherit user context when no authenticated user is present. | |

#### Future
If TAP later supports stacked context scopes such as request, tab, user, and organization defaults, that layering should extend this same precedence model.

### Service-Layer Context Integration
----
RID: `req-grid-userctx-service`

Status: `Proposed`

Grid reads and searches should resolve effective historical context at the service layer rather than requiring UI code to push that behavior into every downstream call.

#### Status Details
Proposed as the architectural counterpart to `req-grid-history-tt-service` in `spec-grid-history-timetravel.md`.

#### Implementation
The integration contract should be:

1. Direct-read and search services continue to accept an explicit optional `as_of` parameter.
2. When that parameter is absent, services may consult the current authenticated user's context record.
3. The service layer resolves the effective historical cutoff before deciding whether to use canonical fast-path reads or historical reconstruction.
4. Response metadata for historical objects continues to follow `req-grid-history-tt-meta`.
5. Panels and pages remain mostly ordinary consumers of returned data; history-aware presentation logic is limited to reacting to metadata on the returned object.

#### Development
This is the design move that keeps "context-aware" behavior from leaking into every panel implementation.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-userctx-service-1 | Reads Consult Effective Context | Proposed | Grid read services use resolved effective context when explicit historical parameters are absent. | |
| req-grid-userctx-service-2 | Searches Consult Effective Context | Proposed | Grid search services use resolved effective context when explicit historical parameters are absent. | |
| req-grid-userctx-service-3 | Historical Metadata Still Returned | Proposed | Historical responses continue to identify themselves as historical even when the time-travel cutoff came from user context rather than an explicit parameter. | |

#### Future
Later work may add helper utilities that resolve effective context once per request and hand it to multiple service calls, but the semantic ownership should remain in the service layer.

### Context Mutation Surface
----
RID: `req-grid-userctx-mutation`

Status: `Proposed`

TAP should expose a first-class mutation surface for reading, setting, and clearing user context.

#### Status Details
Proposed so the context capability is not trapped inside one web view implementation.

#### Implementation
The mutation surface should provide:

1. A service-level API to fetch effective current context for a user.
2. A service-level API to set or replace the stored context.
3. A service-level API to clear the stored context and return to default current-state behavior.
4. HTTP/API endpoints or view routes that call the same service-level APIs.
5. Authorization rules that prevent one user from mutating another user's context except through explicit admin/system flows.

#### Development
The important part is not the first endpoint shape. The important part is that there is one canonical mutation path shared by web and API surfaces.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-userctx-mutation-1 | Get Set Clear Supported | Proposed | TAP exposes a first-class way to read, set, and clear user context. | |
| req-grid-userctx-mutation-2 | Service API Shared By Surfaces | Proposed | Web and API mutation routes use the same underlying user-context service behavior. | |
| req-grid-userctx-mutation-3 | User Ownership Enforced | Proposed | Ordinary users can mutate only their own current context unless a higher-privilege flow explicitly allows otherwise. | |

#### Future
Bulk context presets, saved viewpoints, and admin support tools may later build on this mutation surface.

### Context Change Notifications
----
RID: `req-grid-userctx-events`

Status: `Backlog`

User-context changes should eventually support listener notification, but event delivery is not required for the first implementation.

#### Status Details
Intentionally deferred. This is useful for time-travel scrubbing, synchronized panels, and real-time UI updates, but it is not necessary to establish the underlying server-side context model.

#### Implementation
The deferred notification contract should reserve room for:

1. publish-on-change events when a user's context is updated
2. request-local listeners for coordinated server work
3. future websocket or SSE fan-out for active clients

The first implementation does not need to deliver any of these features.

#### Development
This is backlog because the main risk right now is not lack of events. It is lack of a clean canonical context record and precedence model.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-userctx-events-1 | Notification Reserved As Future Capability | Backlog | The user-context design reserves room for change notifications without requiring them in v1. | |
| req-grid-userctx-events-2 | No Event Dependency In V1 | Backlog | The first implementation of user context does not depend on real-time listener delivery to function correctly. | |

#### Future
When the scrubbing UI arrives, a follow-on spec should define delivery guarantees, payload shape, and how notification behavior composes with request-local and cross-tab state.
