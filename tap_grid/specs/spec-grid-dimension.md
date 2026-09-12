# Grid Dimension Specification

## Philosophy

Entities are the base node of the grid / graph and the place where data about a thing is defined and resides. Dimensionality extends that core model by giving entities a formal way to describe the contexts, namespaces, and perspectives they occupy without losing the coherence of the base entity spine.

## Goals

|    |                    |                                                                                           |
| :---: | ---             | ---                                                                                       |
| 1. | Multi-Dimensional  | Entities can exist in multiple dimensions and contain the metadata to explain how / where |
| 2. | Multi-Axis, Flat   | Each key is one independent axis; an entity carries as many as apply. Nothing is nested    |
| 3. | Accessible         | Entity dimensions are easily found, queried, indexed and will be leveraged lots of ways   |


## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-dimension-em | [Dimensions on Entity Model](#dimensions-on-entity-model) | Implemented | Adds the dimensions field to the canonical entity record |
| req-grid-dimension-dc | [Default Dimension Application](#default-dimension-application) | Implemented | Applies declared default dimensions when an entity is created |
| req-grid-dimension-dn | [Dimension Node](#dimension-node) | Implemented | Introduces a first-class node for dimension definitions |
| req-grid-dimension-hc | [House Conventions](#house-conventions) | Approved for Development | The flat labeled-set reading of the column, and the `dcom` axis (design / configuration / operation) every designed system shares |


## Explanation
#### The Why
The concept of dimensionality is essential to the grid data model. The ability to formally establish a dimension for an entity, and for that entity to occupy multiple dimensions simultaneously, is what opens up a huge amount of optionality while maintaining coherence. If we're being honest here we're re-discovering namespaces and calling them something else because it sounds cooler and fits with the grid backronym of a "graphical representation of interesting dimensions".

This walks a line between configuration and convention which allows both to co-exist. The use of JSON and extensibility makes the concept of dimensions truly multi-dimensional.

Individual `Entity` instances can set whatever dimension values they need, which leans toward a tagging model in the initial implementation. Default dimensions will be applied automatically if they are defined on the entity model. This is a convenience for entity types that we know will always need a given dimension, such as web pages, which will always be on the `tap.graph: web` dimension.

#### Important Distinction: Dimensions and edges serve different purposes:

| Concept | Purpose |
| --- | --- |
| Dimensions | Stable, shared metadata used to partition, scope, index, and interpret entities across a dataset or across blended datasets |
| Edges | Graph-native relationships that model facts and links inside the dataset itself |

Dimensions should generally be closer to fixed and broadly shared. Edges should generally represent facts that can be traversed, updated, or reinterpreted over time.

**Rule of thumb**: If representing a collection would require a bajillion edges applied across a large portion of the dataset and most / all entity types, it is probably a dimension instead of an edge. Dimensions exist in part because that kind of broad, repeated scoping metadata is simpler and more coherent to represent directly than as an enormous set of repeated edges.

#### Edges have Dimensions Too
Since edges are entities they can have dimensions applied to them as well. This will be useful in situations where a `page-USES_PANEL->panel` relationship uses a `USES_PANEL` edge with the `tap.graph: web` dimension applied automatically to keep these entities in the same namespace. Edge dimensions live on the backing Entity.

Edge types declare their own `default_dimensions` in `TapPluginConfig.edge_types` entries — the same place that `property_schema` and topology constraints are declared. At app startup these are loaded into the `_EDGE_DEFAULT_DIMENSIONS_REGISTRY` in `tap_grid/constraints.py`. When an Edge is saved, `Edge.save()` looks up the edge type in that registry and applies the declared dimensions as the base for the Edge's backing Entity. Caller-supplied `_initial_dimensions` are merged on top using the same explicit-wins rule as node types.

This means a `USES_PANEL` edge carries `tap.graph: web` because the `USES_PANEL` edge type declares it — not because of anything about its source node. See `req-grid-dimension-dc` for the full merge semantics.

#### Background
My first inclination was to have this be a simple database column with the dimension as a standard, user-defined value which could possibly be extended through naming conventions ala `env.staging.xyz` where the idea of an environment was meant to support teams running a single TAP instance to cover dev / stage / prod. At the same time, there's the fundamental concept of design -> config -> operation, which is another dimension, and there are other dimensions that data may itself operate in such as employees in the human dimension, machines in the computer dimension, and the collection of humans as teams managing fleets of computers, and layout / search / panels / page entities which I want to manage as nodes and edges but don't want them to get in the way of the actual data.

The alternative to a column would be to have a dimension be a node and edges between nodes used to define which nodes point to which dimension. That would be leaning in super hard to the entity-edge paradigm, but it doesn't quite feel right. It would result in a ton of edges, which would choke up the database, and it also moves the concept of dimension out of the node itself. That distance feels wrong somehow versus having dimension directly encoded as a concept that exists slightly above the graph model itself.

After reading through how others have implemented namespaces in `JSONField`, it seems like following that pattern makes the most sense and that philosophically, dimensions exist in a different conceptual space than nodes and edges (although we'll introduce the concept of a dimension node because it's going to come in handy much sooner than I think).

#### Questions for the Future
How are dimensions and projects related? Dimension, project, grid?  
How can dimensions be leveraged in a security context?  
Projects / grid installs that make dimension nodes expected (or list a subset of preferred nodes that are security / app weight bearing)?

#### Future (idea): Dimensions as a database-enforced security gate (Postgres RLS)

One concrete answer to "how can dimensions be leveraged in a security context?" is to
push scoping down to the database with **Postgres Row-Level Security**. Today authorization
is enforced in the application: the capability backstops at the service layer, and — as of
`req-tap-auth-orm-read-backstop` — a structural read backstop at the ORM chokepoint that
fails closed when a caller reads TAP-managed rows without holding `grid.read`. That guard is
app-layer: it defends against forgotten gates in TAP's own code, not against a bypass that
sidesteps the ORM (raw SQL, a `psql` session, a future non-Django reader).

RLS is the ceiling: policies on the entity/edge tables keyed on a per-transaction session
variable (e.g. `SET LOCAL tap.dimensions = ...`, `SET LOCAL tap.capabilities = ...`) so the
database itself refuses rows outside the caller's scope. Even code that never touches the
service layer cannot read across the boundary. Because `dimensions` already lives on `Entity`
as an indexed JSONB field (`req-grid-dimension-em`), it is the natural partitioning key for
such policies.

The compelling shape is a **combination of dimension and capability down-scoping**: a policy
that admits a row only when (a) the actor holds the capability the operation requires AND
(b) the row's `dimensions` intersect the actor's granted dimension scope. That unifies the
two axes TAP already models — *what* you may do (capabilities) and *which slice* you may see
(dimensions) — into a single database-level filter, and is the natural home for the
dimension-scoped **read** authorization that `spec-tap-auth-v0.md` already reserves ("pushed
into query planning/execution, never a post-fetch filter").

Deliberately deferred, not planned: RLS is heavy to retrofit, ties authz to DB session state,
and is coarser than per-capability app logic. The sequencing note is that it becomes
compelling **once dimensions are used as a scoping boundary at all** — do RLS as the follow-on
from a "dimension as a security scope" feature, not before. Named here so the option is
recorded rather than rediscovered. See `req-tap-auth-orm-read-backstop` and the
dimension-scoped authorization note in `spec-tap-auth-v0.md`.


### Dimensions on Entity Model
----
RID: `req-grid-dimension-em`

Status: `Implemented`

#### Status Details
Implemented in `tap_grid/models.py` as a `JSONField` on `Entity` with a `GinIndex`. Tests in `tap_grid/tests/test_dimensions.py` under `TestEntityDimensionsField`.

#### Implementation
Add a `dimensions` column to the `Entity` model using Django `models.JSONField`. In Postgres this is stored as JSONB. The default value is an empty object and the field is not nullable.

A GIN index is added on the `dimensions` field to support JSONB containment queries (`@>`) without full table scans. This is required to meet the Accessible goal.

If defined, the JSON shape follows these constraints:

| Constraint | Description |
| --- | --- |
| Flat Object | Use a flat JSON object, not nested namespace objects |
| One Key, One Axis | A key names one axis and its value names the entity's position on it; the set of keys is flat and open. Keys with a `.` in them are owner-prefixed spellings (`tap.graph`, `github.surface`), not a hierarchy — see `req-grid-dimension-hc` |
| Lower Case | Always use lower case |
| Value Types | Allow values to be `string` |


#### Development

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-dimension-em-1 | Dimensions Column Exists | Implemented | `Entity` includes a `dimensions` JSON field with a default empty object. | |
| req-grid-dimension-em-2 | Dimensions Column Required | Implemented | The `dimensions` field is non-nullable at the model and database layer. | |
| req-grid-dimension-em-3 | GIN Index Exists | Implemented | A GIN index is defined on the `dimensions` field in `Entity.Meta.indexes`. | Required for performant containment queries. |


#### Future
Consider reserved dimensions or the ability for plugins / apps to reserve them.
Dimension validation options - can be applied at the model or service layer once use cases are understood.



### Default Dimension Application
----
RID: `req-grid-dimension-dc`

Status: `Implemented`

There will be entities that will always want to set a default dimension. The example driving the initial implementation is pages and panels on a web interface. Each will be entities so we can leverage nodes and edges, but I don't want them mucking up the data they're being used to describe.

Having pages in a separate dimension is helpful because that distinction meets our rule of thumb: all the pages and all the panels will be in a self-contained graph, with limited / no interplay with the data (beyond accessing search nodes), and the pages will never change dimensions to become data.

In order to simplify / standardize that we'll define a `DEFAULT_DIMENSIONS` field that will be applied whenever an entity is created.

#### Status Details
Implemented in `tap_grid/models.py`. `BaseModel.save()` merges `DEFAULT_DIMENSIONS` with `_initial_dimensions` on the auto-creation path. `Edge.save()` looks up the edge type in `_EDGE_DEFAULT_DIMENSIONS_REGISTRY` and applies those dimensions before delegating. `tap_grid/services.py` applies the same merge on the prespecified-entity-id create path used by GRIFT imports. Tests in `tap_grid/tests/test_dimensions.py` under `TestDefaultDimensions` and `TestEdgeDefaultDimensions`.

#### Implementation
`DEFAULT_DIMENSIONS` is a `ClassVar[dict[str, str]]` declared on a `BaseModel` subclass. It is applied during the auto-Entity creation path inside `BaseModel.save()` — the branch that fires when `entity_id` is `None`.

Merge semantics: `DEFAULT_DIMENSIONS` provides the base. Any dimensions passed explicitly by the caller are merged on top. Explicit keys win over defaults for any shared key.

```python
# Pseudocode inside BaseModel.save() auto-creation path
base = dict(getattr(self.__class__, "DEFAULT_DIMENSIONS", {}))
caller_supplied = getattr(self, "_initial_dimensions", {})
dimensions = {**base, **caller_supplied}
Entity.objects.create(..., dimensions=dimensions)
```

**Edge default dimensions**: Edge types declare `default_dimensions` in `TapPluginConfig.edge_types`. At startup, `TapPluginConfig._register_edge_constraints()` loads these into `_EDGE_DEFAULT_DIMENSIONS_REGISTRY` in `tap_grid/constraints.py`. When an Edge is created, `Edge.save()` calls `get_edge_default_dimensions(edge_type)` and merges the result with any caller-supplied `_initial_dimensions` using the same explicit-wins rule.

**Prespecified-entity-id create path**: the TAP service layer also supports creating nodes and edges with caller-specified `entity_id` values (used by GRIFT imports). `WriteOperation.dimensions` carries caller-supplied dimensions into this path. `tap_grid/services.py` merges them with the type's defaults (`DEFAULT_DIMENSIONS` for nodes, edge-type `default_dimensions` for edges) using the same explicit-wins rule before creating the Entity row. The merge result matches the auto-creation path for the same inputs.

Default dimensions applied at creation are not enforced after that point. They may be changed or removed without a validation error.

#### Development

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-dimension-dc-1 | Defaults Applied On Create | Implemented | Creating a BaseModel instance whose class defines `DEFAULT_DIMENSIONS` populates those dimensions on the new `Entity`. | |
| req-grid-dimension-dc-2 | Defaults Are Not Mandatory | Implemented | After creation, default dimensions may be changed or removed without causing a validation error. | |
| req-grid-dimension-dc-3 | Explicit Wins on Merge | Implemented | When a caller supplies dimensions at create time, explicit keys override matching keys from `DEFAULT_DIMENSIONS`. Non-overlapping keys from both are present in the result. | |
| req-grid-dimension-dc-4 | Edge Default Dimensions | Implemented | Creating an `Edge` applies the `default_dimensions` registered for its edge type in `_EDGE_DEFAULT_DIMENSIONS_REGISTRY`, with the same merge semantics. Edge types declare `default_dimensions` in `TapPluginConfig.edge_types`. | |
| req-grid-dimension-dc-5 | Prespecified-Id Path Honors Merge | Implemented | Creating a node or edge with a caller-specified `entity_id` (e.g. via GRIFT import) merges `WriteOperation.dimensions` over the type's defaults using the same explicit-wins rule as the auto-creation path. | Closes a prior gap where the prespecified-id path ignored caller dimensions and edge-type defaults. |


#### Future

TAP should move toward a stricter future where every TAP-managed type defines at least one meaningful default dimension. In that future, dimension-less models or edge types should be treated as a design error to justify explicitly rather than an acceptable default.


### Dimension Node
----
RID: `req-grid-dimension-dn`

Status: `Implemented`

#### Status Details
Implemented in `tap_grid/models.py` as `class Dimension(BaseModel)`. Tests in `tap_grid/tests/test_dimensions.py` under `TestDimensionNode`.

#### Implementation
`Dimension` is declared in `tap_grid/models.py` alongside `Edge` as a fundamental graph concept. It is a concrete `BaseModel` subclass with `ENTITY_TYPE = "dimension"`, a `name` field, a `description` field, and `DEFAULT_DIMENSIONS = {"tap.meta": "dimension"}`.

#### Development

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-dimension-dn-1 | Dimension Node Exists | Implemented | A `Dimension` model is declared in `tap_grid/models.py` as a `BaseModel` subclass with `ENTITY_TYPE = "dimension"`. | |
| req-grid-dimension-dn-2 | Dimension Nodes Tagged | Implemented | `Dimension` declares `DEFAULT_DIMENSIONS = {"tap.meta": "dimension"}`. | |
| req-grid-dimension-dn-3 | Dimension Node Carries Core Fields | Implemented | `Dimension` includes `name` and `description` fields. | |

#### Future
Confirm that dimension nodes should remain optional in the initial implementation.  
Define whether dimension nodes should eventually constrain specific inbound or outbound edge types. For the initial implementation, allow any inbound and outbound edges.


### House Conventions
----
RID: `req-grid-dimension-hc`

Status: `Approved for Development`

#### Status Details
Ruled 2026-09-12 (tap#448) after a naming pass that started as "greater dimension first or last in a dotted
key" and ended by noticing the question was wrong. The column is a flat JSON object: a **labeled set** of
independent axes, each key one axis, each value that entity's position on it. An entity carries as many axes
as apply (`tap.graph`, `github.surface`, `dcom` side by side) and a containment query matches any subset. There
is no hierarchy to spell, so the separator inside a key carries no meaning. Goal 2 was rewritten accordingly.

Two kinds of key exist and the difference is *ownership*, not shape:

| Kind | Who mints it | Examples |
| --- | --- | --- |
| Realm-owned | The plugin or app that owns the concept; prefix is the owner (`tap.`, `github.`, `git.`, `zizmor.`) | `tap.graph: web`, `github.surface: actions`, `git.object: blob` |
| House convention | Core, for an axis every designed system shares; short bare key, reserved | `dcom` |

#### The `dcom` axis
`dcom` is the design → configuration → operation axis this spec's Background named on day one. It is a house
convention: specific to *designed* systems, so widely usable but not universal, and applicable to everything
TAP collects.

| Value | Meaning | Mutability | Examples |
| --- | --- | --- | --- |
| `design` | Intent that precedes any concrete instance: a spec, a policy as authored, an architecture | Edited | a requirement, a ruleset as a document |
| `configuration` | A declared instance the system reads to decide what MAY happen; it has history and changes under you | Versioned; changes are FLIPs on the node | a workflow file, a job as declared, an environment's protection rules, a `runs-on` label set |
| `operation` | Something that HAPPENED: a run, a scan, a job execution, a finding a scanner emitted | Immutable once recorded | a workflow run, a job execution, a zizmor run and its findings |

Rules that fall out of the axis:

1. **Key names the axis, value names the position.** Never `configuration: true` beside `operation: true`;
   one key, one of three values, and an entity carries exactly one or none.
2. **The value is a property of the observation, not of the thing.** The same repository's workflow file is
   `configuration`; the run of it is `operation`. Nothing carries both.
3. **Edges carry it too**, from the edge type's `default_dimensions` (`req-grid-dimension-dc-4`). An edge whose
   source union spans both sides (github_core's `REFERENCES_RESOURCE`) declares none and is stamped from its
   source endpoint at emit time.
4. **Only edges derived from the `configuration` side can go stale.** An `operation` never changes, so nothing
   derived from it needs re-checking; an edge derived from the *content* of a `configuration` node records
   the node version it was derived against (tap#447) and is marked potentially out of date when that node
   FLIPs. `dcom` is the axis that stale check reads — one key across every plugin, which is why the axis is
   core-owned rather than one `<vendor>.observation` per collector.
5. **Not a lifecycle state, timestamp, confidence or provenance.** `operation` does not mean recent, finished
   or successful (those are fields on the run); whether a link was observed or inferred is an edge property.

Migration from `github.observation` (`declaration` → `configuration`, `execution` → `operation`) is the owning
plugins' work: github-core#120 and zizmor-tap#38 (where a scan run is re-classified from declaration to
`operation`, and a finding is an operation stamped against a configuration version).

#### Implementation
Spec-only in this requirement. Enforcement (reserving `dcom` and its three values at the service layer; a
guard that no plugin mints a second key for the same axis) is `req-grid-dimension-em`'s "Dimension validation
options" future, and lands with the first plugin migration.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-dimension-hc-1 | Flat Set Stated | Implemented | The spec states the column is a flat set of independent axes and retires the dot-hierarchy goal. | This section. |
| req-grid-dimension-hc-2 | `dcom` Defined | Implemented | Key `dcom`, values `design` / `configuration` / `operation`, with the mutability rule per value. | This section. |
| req-grid-dimension-hc-3 | Plugins Adopt | Approved for Development | github_core and zizmor carry `dcom` on every Actions-surface node and edge; no `github.observation` remains. | github-core#120, zizmor-tap#38. |
| req-grid-dimension-hc-4 | Reserved at the Service Layer | Proposed | Writing `dcom` with a value outside the three, or a second key for the same axis, is refused by the service layer. | With the first migration. |

#### Future
A `Dimension` node per house-convention axis (`req-grid-dimension-dn`) carrying this table as data, so Player 3
reads the vocabulary from the grid rather than from this file.


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
| Deprecated |  |

## RID Format

`req-<application>-<specification>-<feature>-<sub-feature>`

## Requirements Format

`RID: \`...\``  
`Status: \`...\``

| Sub-Sections | (as needed) |
| --- | --- |
| Status Details |  |
| Implementation |  |
| Development |  |
| Acceptance Criteria |  |
| Future |  |
