# Grid Service Layer Specification

## Philosophy

The TAP service layer is the canonical contract between applications and TAP-managed graph data. It sits between callers and the ORM, establishes a single conformance surface for all node and edge operations, and concentrates validation, constraint enforcement, schema publication, batching, and future security controls in one place.

The service layer exists so that callers do not need to understand Django model internals, plugin-specific implementation details, or the full stack of graph invariants in order to read or write TAP data safely. This is especially important for plugins, APIs, bots, and other upstream systems that should interact with TAP through a stable, explicit contract rather than direct model saves.

This specification is the top-level contract. Lower-level operational details are defined in:

- `spec-grid-service-read.md`
- `spec-grid-service-write.md`
- `spec-grid-service-delete.md`
- `spec-grid-service-batch.md`
- `spec-grid-service-errors.md`

### North star — the grid absorbs its sub-grid

A standing architectural target (not a v0 build item): TAP's "sub-grid" systems — plugins, the scheduler, registries, config — progressively gain **grid-side representations** (BaseModel-backed node types on the Entity spine), so they are read through this one service layer instead of bespoke introspection APIs. Each system that makes the move inherits, for free, the gated read path (`req-grid-service-gateway-gated`), FLIP/history/dimensions, and entity-type + dimensional authz — collapsing N introspection surfaces × N gating schemes into one. This is reflective self-representation (cf. Postgres `pg_catalog`, Kubernetes objects-in-etcd, Datomic schema-as-data); TAP already does it with on-grid keystones. It resolves the three grid-access surface types (BaseModel data / Entity spine / sub-grid) toward "surface 3 collapses into surface 1 over time."

The caveat that keeps it honest: an **irreducible bootstrap core** — the grid engine, the type-slug→model registry, pre-boot, boot — must exist *before* the grid can hold a node, so it stays sub-grid by necessity. The target is "everything above the bootstrap core becomes a grid node," not "everything."

The discipline this implies **now** (cheap edge, not a retrofit): a new sub-grid system SHOULD get a BaseModel-backed node type by default rather than accreting another bespoke table + introspection API to fold in later; and capability names SHOULD follow the representation (a domain cap like `plugins.read` while sub-grid; `grid.read` on that type once it is a grid node). Retrofitting existing sub-grid systems waits for demand.

## Goals

|    |                  |                                                                                              |
| :---: | ---           | ---                                                                                          |
| 1. | Canonical         | All node and edge operations flow through one service contract                               |
| 2. | Discoverable      | Clients can discover object shape, constraints, hotlinks, and supported operations           |
| 3. | Schema-Backed     | Every public representation and payload is described by stable TAP JSON Schemas              |
| 4. | Enforced          | Validation, batching, and future security hooks happen at one choke-point                    |
| 5. | Portable          | Clients can operate through JSON-safe representations without importing Django model classes  |


## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-service-scope | [Service Layer Scope](#service-layer-scope) | Proposed | Canonical scope and non-conformant bypasses |
| req-grid-service-objects | [Canonical Objects And Addressing](#canonical-objects-and-addressing) | In Development | Public object kinds and accepted target forms |
| req-grid-service-public | [Public API Surface](#public-api-surface) | In Development | Public entry points vs internal plumbing |
| req-grid-service-gateway-gated | [Gateway Capability Gating](#gateway-capability-gating) | Implemented | Structural floor today (every non-`_` gateway callable gated); `__all__` converges as the public manifest without shrinking the enforced set (union, not substitution) |
| req-grid-service-discovery | [Discovery And Capability Publication](#discovery-and-capability-publication) | Implemented | list_node_types, describe_node_type, list_edge_types, describe_edge_type, describe_service_capabilities |
| req-grid-service-schemas | [Schema Publication And Identity](#schema-publication-and-identity) | In Development | Stable schema IDs, refs, bundling, model publication |
| req-grid-service-response | [Representation And Response Modes](#representation-and-response-modes) | In Development | JSON envelopes, model return mode, schema refs |
| req-grid-service-pipeline | [Common Service Pipeline](#common-service-pipeline) | Implemented | Shared execution order for reads and writes |
| req-grid-service-pipeline-context | [Caller Context](#caller-context) | Implemented | CallerContext shape and threading contract |


### Service Layer Scope
----
RID: `req-grid-service-scope`

Status: `Proposed`

The TAP service layer is the canonical path for all persistence-visible operations on TAP-managed nodes and edges. Application code, plugin code, background work, and user-driven flows that create, update, link, unlink, read, or delete graph data should use the service layer rather than direct ORM calls.

This requirement is intentionally broad. TAP should be able to identify mutation paths that bypass the service layer as non-conformant.

#### Status Details
This reflects the intended architecture. Current implementation still contains direct model save paths and legacy helpers that predate this contract.

#### Implementation
In scope:

- node reads and writes
- edge reads and writes
- single-object lookup helpers
- search-backed richer reads
- batch-backed write execution
- schema publication and discovery for nodes and edges
- enforcement of graph invariants, hotlinks, and related service-layer rules

Out of scope:

- user, group, and authentication administration
- plugin management administration
- migrations that operate below the node/edge abstraction
- tests intentionally exercising behavior at or below the grid/ORM layer
- Django admin behavior outside the future admin-specific service surface

Direct ORM writes in these out-of-scope areas are allowed by design. Direct ORM writes elsewhere are non-conformant.

#### Development
This scope is intentionally narrower than “all database access” and broader than “just convenience CRUD wrappers.” It is specifically about TAP-managed graph data.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-scope-1 | Nodes And Edges In Scope | Proposed | All TAP-managed node and edge operations are defined as service-layer concerns. | |
| req-grid-service-scope-2 | Admin Areas Excluded | Proposed | User/group management and plugin administration are explicitly out of scope for this service contract. | |
| req-grid-service-scope-3 | Bypasses Identifiable | Proposed | The specification treats direct non-admin ORM access for node/edge operations as non-conformant. | |
| req-grid-service-scope-4 | Migrations May Bypass | Proposed | Migrations and low-level tests may bypass the service layer because they operate below the graph contract. | |

#### Future
Add a conformance audit that can identify call sites or operational flows that mutate graph data outside the service layer.


### Canonical Objects And Addressing
----
RID: `req-grid-service-objects`

Status: `In Development`

The service layer exposes a limited set of canonical object kinds and accepted addressing forms so callers can work uniformly without binding themselves to Django model import patterns.

#### Status Details
This requirement defines the public contract shape. Implementation is not yet centralized.

#### Implementation
Canonical public object kinds:

- node
- edge
- batch write request/result
- discovery bundles for node types, edge types, and service capabilities

Accepted addressing forms:

- model instance
- entity or edge identifier
- type slug plus payload for new object creation

Registry/slug-driven resolution is the canonical external mechanism for node type selection. Callers may pass model instances as a convenience in Python, but public object creation should not require importing model classes up front.

Bare `Entity` handling is internal plumbing. Public callers should think in terms of nodes and edges. Generic object wrappers may dispatch from entity-backed identifiers to node or edge behavior internally.

#### Development
This keeps the public contract object-centric and portable while still allowing Python callers to pass native objects when they already have them.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-objects-1 | Public Object Kinds Limited | Proposed | The service layer publishes a small set of canonical object and result kinds instead of exposing arbitrary model internals. | |
| req-grid-service-objects-2 | IDs And Instances Accepted | Implemented | Service calls may accept object IDs and model instances as target forms. | |
| req-grid-service-objects-3 | Slug Driven Creation | Implemented | Public object creation is specified in terms of type slugs and payloads rather than model-class imports. | |
| req-grid-service-objects-4 | Entity Is Internal Plumbing | Implemented | Bare `Entity` handling is internal support behavior rather than the primary public contract. | |

#### Future
Define whether non-Python callers should also be able to submit opaque object references beyond IDs.


### Public API Surface
----
RID: `req-grid-service-public`

Status: `In Development`

The service layer should expose clear public entry points for common intents while still sharing a common internal dispatcher/pipeline for enforcement and response shaping.

#### Status Details
Current code has a small set of mutation helpers and separate search service logic, but not yet a complete public surface.

#### Implementation
The public API surface should include:

- generic object lookup wrapper: `get_object(...)`
- node-specific reads/writes
- edge-specific reads/writes
- search entry point for rich reads
- batch write entry point
- discovery entry points for node types, edge types, and service capabilities

These public entry points should share one internal execution stack for normalization, validation, batching, persistence, error wrapping, and schema-aware response shaping.

Public entry points are preferred over one single write verb because they preserve caller intent. A shared internal dispatcher may still orchestrate common processing.

#### Development
This balances readability for callers with maintainability for TAP itself.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-public-1 | Explicit Public Verbs | Implemented | The service contract publishes intention-revealing entry points for node, edge, batch, and discovery operations. | |
| req-grid-service-public-2 | Generic Object Wrapper | Implemented | A generic object wrapper dispatches reads across node and edge representations. | `get_object()` |
| req-grid-service-public-3 | Shared Internal Pipeline | Implemented | Public entry points ultimately execute through a shared service-layer pipeline rather than independent ad hoc logic. | |

#### Future
Define naming conventions and module boundaries for public entry points versus internal plumbing helpers.
(Realized by `req-grid-service-gateway-gated`.)


### Gateway Capability Gating
----
RID: `req-grid-service-gateway-gated`

Status: `Implemented`

This is TAP's **reference instance of the guarded service-layer boundary convention** (`spec-service-layer-boundary.md`). The general rules — the two-zone gateway/below-gate separation (`req-service-boundary-model`), export-as-contract with the union invariant (`req-service-boundary-export`), and the reusable location guard (`req-service-boundary-guard`) — are owned there and are not restated here; this requirement records only what is specific to the grid layer.

The service layer is the only sanctioned path to grid state, so every exported public name it exposes MUST be capability-gated — no public grid-touching entry point may reach node/edge/spine state without an authorization check. The gate is enforced by **location/export**, not by a "does this look like a privileged sink?" heuristic: that heuristic being too narrow is what let the Entity-spine reads (`resolve_entity`/`get_node`/`get_edge`/`get_object`) ship ungated (2026-07-02 read-gap closure).

The grid layer's export contract follows the convention: `tap_grid.services.__all__` is the reviewable public manifest, but enforcement is the **union** of the structural floor (no ungated non-`_` gateway callable) and manifest consistency — `__all__` names the surface, never shrinks what is enforced (`req-service-boundary-export`). `__init__.py` stays a thin package gateway that re-exports public entry points and owns `__all__`, while substantial implementation lives in focused public modules or `_`-prefixed helpers by fit.

#### Implementation
`tap_grid.services` is a package with a gateway/helper contract:

- **Public gateway/export manifest** — `tap_grid/services/__init__.py` is the package gateway. It should grow an explicit `__all__` listing the exported public gateway names. Every exported public gateway callable carries `@requires_capability(<cap>, operation=...)`, naming the specific capability it needs (`grid.read` for the reads, `grid.write`/`grid.delete`/`grid.purge` for mutations, `grid.discover` for the discovery reads). The one exception is a function whose required capability varies per call — `write_batch`, whose batch may mix `grid.write` and `grid.delete` ops each authorized at dispatch — marked with the reviewed `@gates_per_operation` marker instead of a single static gate. Future non-`_` service submodules are public only when intentionally documented and exported; their names do not become public merely by existing.
- **Helpers below the gate** — `tap_grid/services/_impl.py` (and any `_`-prefixed module) holds pure logic and below-service-boundary machinery. These run *after* a gateway function has authorized the caller and carry no gate. The import is strictly one-way (`__init__` → `_impl`, never back).

The gated-internal write cluster (`_create_node_internal`/`_patch_node_internal` and their `_for_test` variants) is `_`-prefixed but retains `@requires_capability` and lives with `write_batch` in `__init__.py`, because it calls `write_batch` (keeping it out of `_impl` preserves the one-way import).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-gateway-gated-1 | Public Gateway Fully Gated | Implemented | Every non-`_` top-level callable in the `tap_grid.services` gateway modules carries `@requires_capability` or `@gates_per_operation`. | The structural floor the guard enforces today. `__all__`-manifest convergence is `-gated-5` (Proposed). |
| req-grid-service-gateway-gated-2 | Helpers Below The Gate | Implemented | Pure helpers live in `_impl.py`; the `__init__` → `_impl` import is one-way. | |
| req-grid-service-gateway-gated-3 | Export-Scoped Lint | Implemented | A per-commit guard enumerates the gateway modules and fails on any ungated non-`_` public callable — no baseline, no allowlist (a hard lint, not a ratchet). | `tap_grid/guards/service_gateway.py`, enforced via `tap/tests/test_guards.py`; Validation Map row in `spec-dev-validation.md`. |
| req-grid-service-gateway-gated-4 | Per-Operation Marker Is Narrow | Implemented | `@gates_per_operation` is used only where one static capability cannot express the requirement (`write_batch`); a static gate is always preferred. | |
| req-grid-service-gateway-gated-5 | Export Manifest Convergence | Proposed | `tap_grid.services.__all__` becomes the reviewable public manifest, and the guard cross-checks it against the structural floor: `__all__` must equal the gated public set. `__all__` may rename the authoritative inventory but never shrink what is enforced. | Union, not substitution: an `__all__`-only check would reopen the ungated-but-importable gap. |

#### Future
Fold the location lint into the future cold-boot/dev-validation gate, and — as `tap_auth` and plugins adopt the same guarded-service-boundary pattern (`req-tap-auth-service-boundary`) — generalize the guard from `tap_grid/services/`-hardcoded into a **reusable boundary primitive** any guarded service package declares itself into, rather than per-app copies. As domain submodules (`nodes.py`, `edges.py`) are split out for readability, the guard scans them as gateway modules under the same **union** invariant — a public submodule name does not escape the structural floor by living outside `__init__.py`.


### Discovery And Capability Publication
----
RID: `req-grid-service-discovery`

Status: `Implemented`

The service layer publishes machine-usable discovery information so clients, plugins, and bots can inspect TAP types and operate intelligently without importing Python code or reverse-engineering model internals.

#### Status Details
This is a new requirement driven by the need for upstream systems to understand node/edge shape, constraints, and hotlinks through a stable contract.

#### Implementation
Discovery should include:

- available node types
- available edge types
- supported operations per type
- JSON Schema references for read/create/patch/replace payloads
- node constraint metadata
- edge constraint metadata
- hotlink metadata
- service-level capabilities such as response modes and schema delivery modes

Discovery responses should include full resolved schemas by default. Ordinary object reads should return schema references by default and may optionally inline resolved schemas.

Constraint and hotlink publication are first-class parts of discovery. Clients should be able to inspect them directly rather than inferring them from prose or plugin code.

#### Development
JSON Schema is the backbone for representation shape, but some graph concepts are TAP-native capability metadata rather than plain payload shape. Discovery therefore needs both schemas and structured capability publication.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-discovery-1 | Node Type Discovery | Implemented | The service layer can list and describe node types. | |
| req-grid-service-discovery-2 | Edge Type Discovery | Implemented | The service layer can list and describe edge types. | |
| req-grid-service-discovery-3 | Constraints Published | Implemented | Discovery includes node and edge constraints in machine-usable form. | |
| req-grid-service-discovery-4 | Hotlinks Published | Implemented | Discovery includes hotlink metadata in machine-usable form. | |
| req-grid-service-discovery-5 | Discovery Includes Resolved Schemas | Implemented | describe_node_type() includes full inline schemas. | |

#### Future
Add discovery-time indicators for lifecycle/deprecation, recommended usage patterns, and future authorization hints once the security pass lands.


### Schema Publication And Identity
----
RID: `req-grid-service-schemas`

Status: `In Development`

Every public representation and capability contract in the service layer should have a stable TAP schema identity and a standard publication mechanism.

#### Status Details
This formalizes schema publication as a required responsibility of model authors, not an optional convenience.

#### Implementation
Every concrete `BaseModel` subclass must declare inline `SERVICE_CRUD_SCHEMA` on the model class. At minimum, this publication point should include:

- read payload schema
- create payload schema
- patch payload schema
- replace payload schema
- constraint schema
- hotlink schema

The service layer uses the model registry to resolve a node type slug to its model class, then retrieves published schemas from that standard location.

Schema publication is mandatory. Missing required schemas are startup/configuration errors.

Schema identity uses stable versioned TAP IDs, for example:

- `tap.schema.core.node-envelope.v1`
- `tap.schema.node.character.read.v1`
- `tap.schema.constraints.node.character.v1`
- `tap.schema.hotlinks.node.character.v1`

Shared schemas such as dimensions also receive their own IDs and are referenced from payload schemas rather than duplicated.

#### Development
Keeping `SERVICE_CRUD_SCHEMA` inline on the model class makes schema ownership explicit and keeps model/schema drift visible during development.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-schemas-1 | All BaseModel Subclasses Publish Schemas | Implemented | Every concrete `BaseModel` subclass must publish `SERVICE_CRUD_SCHEMA`. | |
| req-grid-service-schemas-2 | Missing Schemas Break Startup | Implemented | Missing required service schemas are treated as configuration errors during startup. | |
| req-grid-service-schemas-3 | Registry Lookup Is Canonical | Implemented | Service-layer schema retrieval resolves model classes through the existing registry keyed by type slug. | |
| req-grid-service-schemas-4 | Stable Versioned Schema IDs | Proposed | Every public service schema has a stable versioned TAP schema ID. | |
| req-grid-service-schemas-5 | Shared Schemas Reused By Ref | Proposed | Shared representations such as dimensions publish their own schema IDs and are referenced rather than duplicated. | |

#### Future
Add startup sanity checks that compare service schemas against model field definitions and surface drift early.


### Representation And Response Modes
----
RID: `req-grid-service-response`

Status: `In Development`

The service layer supports both transport-safe JSON representations and native model returns, but the canonical cross-system contract is schema-backed JSON-safe envelopes.

#### Status Details
This requirement defines the representation contract needed for APIs, plugins, and bots while still preserving ergonomics for internal Python callers.

#### Implementation
Canonical transport envelopes:

- node envelope
- edge envelope
- write result envelope
- batch result envelope
- error envelope

Node and edge transport envelopes should:

- include top-level identity metadata such as `kind`, `id`, and `type`
- place the mutable/readable object payload under `data`
- use schema refs to identify envelope, payload, constraint, and hotlink schemas

Response modes should support:

- minimal
- standard
- verbose

Return modes should support:

- JSON-safe service representation
- native model return for Python callers

Search and batch/multi-object responses should publish deduplicated top-level schema refs and may optionally inline resolved schemas.

#### Development
The contract separates response detail level from representation format. A caller can ask for JSON plus minimal, or JSON plus verbose, or native model plus standard, as long as the service contract defines the behavior.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-response-1 | Data Nested Under Data Key | Proposed | Node and edge transport envelopes place payload fields under `data`. | |
| req-grid-service-response-2 | JSON And Model Return Modes | Proposed | Callers may request JSON-safe or native model return modes where applicable. | |
| req-grid-service-response-3 | Response Detail Modes | Implemented | The service layer defines minimal, standard, and verbose response detail levels. | |
| req-grid-service-response-4 | Ordinary Reads Use Schema Refs By Default | Proposed | Single-object reads return schema refs by default and may inline schemas on request. | |
| req-grid-service-response-5 | Batch Responses Deduplicate Schema Refs | Proposed | Multi-object responses publish shared schema refs at the top level rather than repeating them per object. | |

#### Future
Add explicit compatibility guarantees for response mode evolution and schema delivery defaults.


### Common Service Pipeline
----
RID: `req-grid-service-pipeline`

Status: `Implemented`

All public service entry points should execute through a common pipeline so that validation, batching, error handling, and future security hooks do not drift between operations.

#### Status Details
This is currently only partially centralized across existing helpers and services.

#### Implementation
The shared pipeline should be documented in this order:

1. input normalization
2. security/authz hook stub
3. object load and resolution
4. schema validation and strict field rejection
5. model `full_clean()`
6. graph invariant checks
7. service-layer policy and constraint checks
8. hotlink validation
9. transactional/batch execution
10. persistence
11. batch/provenance recording
12. response shaping and schema references
13. safe error wrapping

For clarity:

- graph invariant checks are cross-object graph rules that should always hold, such as disallowing edges-between-edges and enforcing graph/topology consistency
- service-layer policy and constraint checks are TAP-managed operational rules layered above model validation, such as edge constraint enforcement, immutable field rules, operation support checks, and other cross-object contract rules
- hotlink validation remains its own stage because it is a distinct cross-object consistency system with its own declarations and semantics

Reads and writes may skip irrelevant stages, but they should still follow the same conceptual ordering.

#### Development
This requirement matters as much for future maintenance as for immediate implementation. The service layer is useful precisely because it gives TAP one consistent place to keep adding cross-cutting concerns.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-pipeline-1 | Shared Pipeline Documented | Implemented | The specification defines a common execution pipeline for public service operations. | |
| req-grid-service-pipeline-2 | Full Clean Required On Writes | Implemented | Write operations call `full_clean()` as part of the shared pipeline. | |
| req-grid-service-pipeline-3 | Security Hook Reserved | Implemented | The shared pipeline includes a defined location for future authorization enforcement. | |
| req-grid-service-pipeline-4 | Constraint And Hotlink Stages Present | Implemented | The shared pipeline includes explicit graph-constraint and hotlink validation stages. | |

#### Future
Split the common pipeline into formally reusable internal primitives once the operational specs are implemented and stable.


### Caller Context
----
RID: `req-grid-service-pipeline-context`

Status: `Implemented`

All public service functions accept an explicit CallerContext that carries the identity and batch scope of the calling operation. CallerContext is the mechanism through which actor identity, batch_id, and future authorization information flow through the pipeline without threading Django request objects into the service layer.

#### Status Details
This requirement formalises the CallerContext contract so that actor identity and batch_id are first-class service parameters from day one, even where their enforcement is initially minimal. Retrofitting this after the fact would require changing every service function signature.

#### Implementation
CallerContext carries at minimum:

- `user: User | None` — the acting user. None indicates a system or internal caller.
- `batch_id: str | None` — an existing batch scope to join. None means the service layer generates a new batch_id for this operation.

CallerContext is derived from Django primitives:

- **For requests, exactly once, at the middleware.** `CallerContextMiddleware` (tap_auth)
  derives the context from `request.user` — using Django's canonical
  `is_authenticated` predicate — and binds it on the contextvar for the request
  lifecycle. Request-scoped code (API routes, web views, panels) **consumes** that
  bound context via `require_caller_context()`; it does not rebuild one from
  `request.user`. Two derivations of request identity means two definitions of
  "authenticated" on an authorization surface: before the 2026-08 derive-the-same-
  fact-twice collapse (audit finding #4) four hand-rolled route builders used a
  `hasattr(request.user, "pk")` predicate that the middleware does not, and nothing
  held them together. `require_caller_context()` fails closed
  (`NoCallerContextError`) when nothing is bound — a route reached outside the
  middleware is a wiring bug, never an invented identity.
- In management commands and background tasks there is no request middleware: the entry
  boundary binds a named program actor via `tap_auth.acting_as` (the no-request analogue —
  see `spec-tap-auth-v0.md`), or the caller constructs an explicit CallerContext.
- Service functions accept CallerContext as a typed parameter. They do not accept raw Django request objects.

CallerContext is not user-writable payload. Callers provide identity context; the service layer controls what is done with it (batch_id generation, future authz checks).

The security/authz hook at pipeline step 2 operates against CallerContext. When authorization is implemented, CallerContext will be the primary input to those checks.

#### Development
CallerContext is intentionally minimal at this stage. Do not add fields beyond user and batch_id until a concrete need exists. The shape should be stable before the first service function is implemented.

#### Backlog: contextvar propagation discipline

CallerContext is carried through the pipeline on a module-level `ContextVar`
(`tap_grid/caller_context.py`), and a growing set of enforcement mechanisms now
depend on that same contextvar being correctly propagated: the write/read
backstops resolve the active actor from it, and the ORM read backstop
(`req-tap-auth-orm-read-backstop`, `tap_grid/read_guard.py`) reads it — plus its
own bypass flag and per-context grant memo — on every graph read. Contextvars
propagate to the same task and to threads that inherit a copied context, but they
are **not** inherited across a bare `ThreadPoolExecutor`/manual-thread boundary
unless the context is explicitly copied, and async tasks carry their own copy.

The failure mode is asymmetric and mostly safe: a lost context reads as
`user=None` → the backstops **fail closed** (over-deny), not open. But two sharp
edges deserve a written owner before we lean harder on this: (1) a background
worker that spawns threads without `contextvars.copy_context()` will silently
over-deny graph reads/writes, which looks like a permissions bug, not a
threading bug; and (2) the read-guard bypass (`unguarded_read()`) and grant memo
live on contextvars too, so the same propagation rules govern whether an
escape-hatch or a cached decision survives a thread hop. Backlog item: document
the propagation contract here (and in `read_guard.py`), and decide whether TAP
should provide a context-preserving executor wrapper rather than relying on each
caller to remember `copy_context()`. This composes with the "carry the approval
set on CallerContext itself" direction in `spec-tap-auth-v0.md`
(`req-tap-auth-policy` backlog), which would put even more weight on this axis.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-pipeline-context-1 | All Service Functions Accept CallerContext | Implemented | Every public service function accepts a CallerContext parameter. | |
| req-grid-service-pipeline-context-2 | User And Batch ID Fields | Implemented | CallerContext carries at minimum a user field and a batch_id field. | |
| req-grid-service-pipeline-context-3 | No Raw Request Objects | Implemented | Service functions accept CallerContext, not Django HttpRequest objects. | |
| req-grid-service-pipeline-context-4 | None User Is Valid | Implemented | A CallerContext with user=None is valid and represents a system or internal caller. | |
| req-grid-service-pipeline-context-5 | Authz Hook Uses Context | In Development | The reserved security/authz pipeline step operates against CallerContext. | |
| req-grid-service-pipeline-context-6 | One Request-Identity Derivation | Implemented | Request identity is derived exactly once, by `CallerContextMiddleware` (Django's `is_authenticated` predicate); request-scoped code consumes the bound context via `require_caller_context()` and never rebuilds one from `request.user`. Guard-pinned by test. | Audit #4 collapse: four route builders carried a second, divergent predicate. |
| req-grid-service-pipeline-context-7 | Unbound Context Fails Closed | Implemented | `require_caller_context()` raises `NoCallerContextError` when no context is bound, rather than returning an invented or anonymous identity. | A route outside the middleware is a wiring bug — loud. |

#### Future
Add role, permission scope, or realm context to CallerContext when the authorization specification is written.


## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed |  |
| Approved for Development | Requirement is accepted and ready to be implemented |
| In Development |  |
| Implemented |  |
| Verified |  |
| Refactoring |  |
| Deprecating |  |
| Deprecated | Not part of the current architecture and should not be implemented |
