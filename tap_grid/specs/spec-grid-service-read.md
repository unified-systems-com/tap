# Grid Service Read Specification

## Philosophy

The TAP service layer should expose a small, explicit read surface for direct object lookup and type discovery while routing richer graph retrieval through search. This keeps direct reads simple, predictable, and easy to secure, while preserving the search system as the canonical expressive read mechanism.

## Goals

|    |                  |                                                                                 |
| :---: | ---           | ---                                                                             |
| 1. | Narrow            | Direct read APIs are intentionally small and limited                            |
| 2. | Discoverable      | Clients can inspect node and edge types, schemas, constraints, and hotlinks     |
| 3. | Self-Describing   | Read responses can identify their associated schemas and representation contract |


## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-service-read-direct | [Direct Object Reads](#direct-object-reads) | Implemented | get_object, get_node, get_edge, resolve_entity |
| req-grid-service-read-discovery | [Discovery Reads](#discovery-reads) | Implemented | list_node_types, describe_node_type, list_edge_types, describe_edge_type, describe_service_capabilities |
| req-grid-service-read-search | [Search Boundary](#search-boundary) | Implemented | Rich reads go through search; no neighborhood helpers on service layer |
| req-grid-service-read-schemas | [Schema Delivery For Reads](#schema-delivery-for-reads) | In Development | Schema refs defined in NodeTypeDescription; inline schema delivery not yet built |


### Direct Object Reads
----
RID: `req-grid-service-read-direct`

Status: `Implemented`

The direct read surface provides a small set of single-object lookups plus a generic wrapper for callers that have an object reference but do not want to branch on node versus edge handling themselves.

#### Status Details
Implemented in `tap_grid/services.py`. All four functions exist and are tested.

#### Implementation
Direct read API:

- `resolve_entity(target)` — return the Entity row for an entity UUID
- `get_node(target)` — return the typed domain node instance; raises `ServiceConstraintError` if entity is an edge
- `get_edge(target)` — return the Edge instance
- `get_object(target)` — detect entity type and dispatch to `get_node` or `get_edge`

All functions accept `str | uuid.UUID` and raise `ServiceNotFoundError` on miss.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-read-direct-1 | Generic Object Wrapper | Implemented | Direct reads include a generic wrapper for node/edge dispatch. | `get_object()` |
| req-grid-service-read-direct-2 | IDs And Instances Accepted | Implemented | Single-object read APIs accept object IDs and model instances. | str or uuid.UUID |
| req-grid-service-read-direct-3 | JSON Or Model Return | Proposed | Direct reads support JSON-safe and native model return modes. | Native model return implemented; JSON-safe envelope mode deferred |

#### Future
Decide whether a direct `get_entity()` helper is needed for internal plumbing only. Add JSON-safe envelope return mode when clients need it.


### Discovery Reads
----
RID: `req-grid-service-read-discovery`

Status: `Implemented`

The service layer provides machine-usable discovery so clients can understand type shape, constraints, hotlinks, and operation support without importing server-side code.

#### Status Details
Implemented in the `tap_grid/services/` gateway package. `NodeTypeDescription`, `EdgeTypeDescription`, and `ServiceCapabilities` dataclasses defined in `tap_grid/service_types.py`.

#### Implementation
Discovery read API (each gated on `grid.discover` per `req-grid-service-gateway-gated` — introspecting the type/schema catalog is a distinct, less-sensitive capability than reading graph data):

- `list_node_types()` — sorted list of registered entity type slugs
- `describe_node_type(type_slug)` — returns `NodeTypeDescription` with schemas, hotlinks, outbound/inbound constraint edge types
- `list_edge_types()` — sorted list of registered edge type slugs
- `describe_edge_type(edge_type)` — returns `EdgeTypeDescription` with allowed sources/targets and property schema
- `describe_service_capabilities()` — returns `ServiceCapabilities` with all node/edge types, write verbs, and read functions

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-read-discovery-1 | Node Type Discovery Supported | Implemented | The service layer can list and describe node types. | |
| req-grid-service-read-discovery-2 | Edge Type Discovery Supported | Implemented | The service layer can list and describe edge types. | |
| req-grid-service-read-discovery-3 | Discovery Includes Constraints And Hotlinks | Implemented | Type discovery publishes constraint and hotlink information. | |
| req-grid-service-read-discovery-4 | Discovery Bundles Schemas By Default | Implemented | Discovery responses include schemas inline via NodeTypeDescription.schemas. | |

#### Future
Add discovery metadata for deprecation and lifecycle state once the broader service contract stabilizes.


### Search Boundary
----
RID: `req-grid-service-read-search`

Status: `Implemented`

Direct read APIs are intentionally narrow. Graph neighborhoods, complex filtering, traversal, pagination-heavy retrieval, and other richer read behavior should go through the shared search service rather than growing the direct read surface.

#### Status Details
The direct read surface is intentionally limited to four single-object lookups and five discovery functions. No neighborhood or traversal helpers exist on the service layer.

#### Implementation
Direct reads do not grow convenience helpers for graph traversal or complex retrieval. Complex retrieval is expressed as a Search and executed through `spec-grid-search.md`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-read-search-1 | Rich Reads Route To Search | Implemented | Complex retrieval beyond direct lookup and discovery is handled through search rather than custom read helpers. | |
| req-grid-service-read-search-2 | No Neighborhood Helper Contract | Implemented | The service layer does not define a dedicated graph neighborhood helper as part of the direct read surface. | |

#### Future
Revisit if time-travel or comparison reads require a separate read family rather than pure search.


### Schema Delivery For Reads
----
RID: `req-grid-service-read-schemas`

Status: `In Development`

Read results should be self-describing without making every ordinary response unnecessarily heavy.

#### Status Details
`NodeTypeDescription.schemas` inlines all three schemas for a type. Schema ref strings (e.g. `"character:create"`) are the planned identifier format but are not yet attached to ordinary single-object read responses.

#### Implementation
`describe_node_type()` includes the full schema dict inline. Ordinary `get_node()` / `get_edge()` / `get_object()` return native model instances without schema refs.

Deferred for ordinary reads:
- Schema refs attached to ReadResult
- Optional inline schema map for batch results
- Deduplicated schema refs at the top level of multi-object responses

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-service-read-schemas-1 | Single Reads Use Refs By Default | Proposed | Ordinary single-object reads identify applicable schemas via schema refs by default. | Deferred; discovery bundles schemas |
| req-grid-service-read-schemas-2 | Inline Schemas Optional | Proposed | Callers may request inline resolved schemas for ordinary reads. | Deferred |
| req-grid-service-read-schemas-3 | Multi-Object Reads Deduplicate | Proposed | Search and batch-style responses publish shared schema refs rather than repeating them per object. | Deferred |

#### Future
Define caching guidance for clients that consume schema IDs frequently.


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
