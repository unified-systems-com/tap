# Grid Dimension Specification

## Philosophy

Entities are the base node of the grid / graph and the place where data about a thing is defined and resides. Dimensionality extends that core model by giving entities a formal way to describe the contexts, namespaces, and perspectives they occupy without losing the coherence of the base entity spine.

## Goals

|    |                    |                                                                                           |
| :---: | ---             | ---                                                                                       |
| 1. | Multi-Dimensional  | Entities can exist in multiple dimensions and contain the metadata to explain how / where |
| 2. | Hierarchical       | Dimensions can be nested via dot notation to form sub-namespaces                          |
| 3. | Accessible         | Entity dimensions are easily found, queried, indexed and will be leveraged lots of ways   |


## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-dimension-em | [Dimensions on Entity Model](#dimensions-on-entity-model) | Implemented | Adds the dimensions field to the canonical entity record |
| req-grid-dimension-dc | [Default Dimension Application](#default-dimension-application) | Implemented | Applies declared default dimensions when an entity is created |
| req-grid-dimension-dn | [Dimension Node](#dimension-node) | Implemented | Introduces a first-class node for dimension definitions |
| req-grid-dimension-node-identity | [Dimension Node Identity](#dimension-node-identity) | Approved for Development | A dimension's identity is an assigned UUIDv7; the dotted name becomes a mutable label. Extends `req-grid-dimension-dn` |
| req-grid-dimension-no-edges | [Nothing Draws an Edge to a Dimension Node](#nothing-draws-an-edge-to-a-dimension-node) | Approved for Development | `INBOUND_EDGES = []` / `OUTBOUND_EDGES = []`. Supersedes the `req-grid-dimension-dn` Future note that allowed any edge |
| req-grid-dimension-reference | [Entities Reference Dimensions by Id, With Provenance](#entities-reference-dimensions-by-id-with-provenance) | Proposed | PROVISIONAL map shape `{<uuid>: {v, src}}`. Amends `req-grid-dimension-em` (flat object / string values) |
| req-grid-dimension-lifecycle | [Dimension Lifecycle Rides Node History](#dimension-lifecycle-rides-node-history) | Approved for Development | Rename and deprecation are the node's history; entity membership is the entity's history — two reads |
| req-grid-dimension-tabled | [Deliberately Tabled Dimension Capabilities](#deliberately-tabled-dimension-capabilities) | Proposed | Records four decisions to defer — mandate, delete-by-dimension, namespace reservation, second map |


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
| Namespaced Keys | Use namespaced keys separated by `.` |
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
~~Define whether dimension nodes should eventually constrain specific inbound or outbound edge types. For the initial implementation, allow any inbound and outbound edges.~~ **Answered 2026-09-20 by `req-grid-dimension-no-edges`: nothing draws an edge to a dimension node.** The open question is closed in the restrictive direction; re-opening it means naming one edge type and one source type, not lifting the block.


## The 2026-09-20 Redesign

The five requirements that follow were ruled on 2026-09-20 and are **design only**. No code
exists for any of them; nothing below is Implemented, and a reader should not infer otherwise
from the detail.

The reasoning — nine prior-art sweeps, the defects each one exposed, and the argument behind
every ruling — is preserved in
[doc-grid-dimension-prior-art.md](../../docs/misc/doc-grid-dimension-prior-art.md). That doc is
the *why*; these requirements are the *what*.

**The trial is `dcom` going first, alone.** Every other dimension key in the system
(`tap_cares`, `compliance`, `tap.meta`, `tap.graph`) stays exactly as it is until the trial
says something.

**Why the original design can change without contradicting its own reasoning.** The
`Background` section above rejected dimension-as-node *because of the edges* — "it would result
in a ton of edges, which would choke up the database". `req-grid-dimension-no-edges` removes
the edges. With the edges gone the objection that produced the JSON-map design no longer
applies. The section also predicted this: "we'll introduce the concept of a dimension node
because it's going to come in handy much sooner than I think."


### Dimension Node Identity
----
RID: `req-grid-dimension-node-identity`

Status: `Approved for Development`

A dimension's identity is an **assigned UUIDv7**, minted at first sight. The dotted name is a
**mutable label** carried on the node, not the thing that identifies it.

This extends `req-grid-dimension-dn`, which established the node but left identity resting on
the name. It applies the standing entity-id ruling (ids are assigned, never derived from a hash
of the thing's facts) to the vocabulary, and it is what makes a rename an edit to one field
rather than a migration across every entity that ever carried the key.

`Dimension` already declares `NATURAL_KEY = KEYLESS` with the reason "authored, not observed: a
dimension is vocabulary TAP declares, and its identity arrives in the GRIFT document that
declares it". Assigned identity is what that declaration implies; this requirement makes the
storage shape honour it.

#### Implementation

The node carries, at minimum:

| Field | Role |
| --- | --- |
| entity id (UUIDv7) | The identity. Assigned once, never changes, never derived from the name |
| `name` | The dotted label. Mutable. Human- and AI-facing only |
| `description` | What the dimension means, for a reader who has only the node |

`name` and `description` already exist on the model. This requirement changes what `name`
*means* (a label, not an identity), not what columns exist.

**Value nodes.** A closed-value axis may publish a node per value (`dcom` ships `dcom.design`,
`dcom.configuration`, `dcom.operation` alongside the axis node `dcom`). These are the
**published expansion** — the dictionary entry a reader consults — and deliberately **not** the
storage form; see `req-grid-dimension-reference`. An open-value key (any forge hostname, say)
publishes no value nodes at all, because minting a node per observed string is the
supernode extreme `req-grid-dimension-no-edges` exists to prevent.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-dimension-node-identity-1 | Identity Is Assigned | Approved for Development | A `Dimension` node's entity id is a UUIDv7 assigned at first sight and never derived from its name or description. | Applies the standing entity-id ruling to the vocabulary. |
| req-grid-dimension-node-identity-2 | Name Is Mutable | Approved for Development | Changing a `Dimension`'s `name` leaves its entity id unchanged, and leaves every entity referencing it correct without a data migration. | The cure for the Dublin Core / `javax`→`jakarta` failure mode. |
| req-grid-dimension-node-identity-3 | Value Nodes Are Expansion, Not Storage | Approved for Development | Value nodes published for a closed-value axis are documentation. No stored entity dimension references a value node's id. | Storage shape is fixed by `req-grid-dimension-reference`. |

#### Future

Whether an axis should *declare* that it is closed-value, and whether that declaration should
be checked against the value nodes it publishes, is unaddressed. Today the distinction is
convention.


### Nothing Draws an Edge to a Dimension Node
----
RID: `req-grid-dimension-no-edges`

Status: `Approved for Development`

`Dimension` declares `INBOUND_EDGES: ClassVar[list] = []` and `OUTBOUND_EDGES: ClassVar[list] =
[]`. No edge may originate at or terminate on a dimension node.

This is the load-bearing half of the redesign. Making a dimension a node is only safe because
nothing points at it: a key held by a large fraction of the grid, modelled with an edge per
holder, is a supernode by arithmetic. It is the objection this spec's own `Background` raised
("it would result in a ton of edges, which would choke up the database") and the objection that
makes graph-modelling guidance elsewhere refuse to promote low-cardinality attributes to nodes.

**Supersedes** the `req-grid-dimension-dn` Future note that said "for the initial
implementation, allow any inbound and outbound edges."

#### Implementation

The empty list is **absolute**, and that is a property of the existing constraint engine rather
than of this requirement:

- `tap_grid/constraints.py` `validate_edge()` implements a Permission Union — an edge is
  allowed if EITHER node OR edge-type constraints permit it, *unless explicitly blocked by the
  node*.
- Phase 1 of that function calls `_is_explicitly_blocked_outbound` /
  `_is_explicitly_blocked_inbound` and raises `InvalidEdgeError` **before** any union is
  computed; edge-type constraints cannot override it.
- `_is_explicitly_blocked_inbound` returns True exactly when the registered inbound constraint
  map is `{}`, and `_parse_constraint_list([])` yields `{}`.

So the declaration is enforced by a code path, not by prose. That distinction is deliberate:
this spec's own dotted-name grammar (`req-grid-dimension-em`) is declared and **not** enforced
anywhere, and three live keys already violate it (`tap_cares`, `compliance`, `dcom`). A
documentary rule is a rule that is already broken and does not say so.

Two mechanisms that could have conflicted with a blanket block, and do not:

- **Batch membership is not an edge.** `batch_id` is stamped on typed rows; the core
  `PRODUCED_BATCH` edge type targets `batch`, not `dimension`. GRIFT can import dimension nodes
  into a batch with inbound edges blocked.
- **No edge type in the tree names `dimension` as a source or target** as of this writing.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-dimension-no-edges-1 | Blocks Declared | Approved for Development | `Dimension` declares both `INBOUND_EDGES = []` and `OUTBOUND_EDGES = []`. | |
| req-grid-dimension-no-edges-2 | Inbound Edge Refused | Approved for Development | Creating any edge whose target is a dimension node raises `InvalidEdgeError`, including for an edge type whose own constraints are wildcard. | Negative test must use a wildcard edge type — a constrained one would pass for the wrong reason. |
| req-grid-dimension-no-edges-3 | Outbound Edge Refused | Approved for Development | Creating any edge whose source is a dimension node raises `InvalidEdgeError`, under the same wildcard condition. | |
| req-grid-dimension-no-edges-4 | Import Unaffected | Approved for Development | A GRIFT batch containing dimension nodes imports successfully with both blocks in place. | Guards the batch-membership finding above against regression. |

#### Future

**Dimension-to-dimension edges** are a foreseeable and deliberately unopened door: broader /
narrower, successor-after-rename, and an axis grouping its own values. The useful property is
that `INBOUND_EDGES = []` opens by **replacing the empty list with a map naming one edge type
and one source type** — which opens exactly one door and no others. The reverse ordering (ship
permissive, restrict later) cannot be done at all once edges exist, because restricting means
deleting data.

The reason not to open it now is that the dotted name already carries the axis-to-value
relationship, and an edge duplicating a fact the name carries is a second copy to keep in sync.
The edge becomes worth building when it carries a fact the name **cannot** — a rename successor
being the obvious first one.


### Entities Reference Dimensions by Id, With Provenance
----
RID: `req-grid-dimension-reference`

Status: `Proposed`

**PROVISIONAL — to be revisited after the `dcom` trial.**

An entity's `dimensions` map is keyed by the **dimension node's uuid**, and each value is an
object carrying the dimension's value and how it got there:

```json
{
  "01a0c057-8f3d-70cd-b07c-c7523153be64": {
    "v": "configuration",
    "src": "declared"
  }
}
```

| Key | Meaning |
| --- | --- |
| `v` | The dimension's value: a plain **string** |
| `src` | How it got here: `declared` (the caller passed it) \| `default` (applied from `DEFAULT_DIMENSIONS` or an edge type's `default_dimensions`) \| `derived` (computed by some later process) |

#### Why the value is a string and not a value-node id

Value nodes only work for **closed** value sets. An open key — a forge hostname — cannot have a
node per value without minting a node for every string anyone observes. Supporting both shapes
would force every reader, query and migration to branch, which is worse than one shape that is
imperfect for the closed case.

**The accepted cost, stated plainly:** for a closed axis like `dcom`, the stored string
`"configuration"` and the published node named `dcom.configuration` are two copies of one fact
— the shape derive-a-fact-once exists to prevent. The justification is that the node is
*published documentation* and not a second authority, and that two storage shapes are worse.
This is the first thing the `dcom` trial should be asked about.

#### Why provenance is stored before anything reads it

Nothing reads `src` today. It is stored anyway because the asymmetry runs one way: a nested key
costs nothing now and a migration over every entity on the grid costs a great deal later. The
failure being pre-empted is a named one — Terraform's `default_tags` has no property recording
whether a tag came from the global default or the resource, and as a direct consequence there
is still no way to exclude one resource from a default tag. You cannot subtract what you cannot
distinguish.

If the trial shows nobody needs it, dropping a key nothing reads is cheap. That is the right
way round.

#### Amendment to `req-grid-dimension-em`

This requirement **conflicts with two constraints that requirement declares as Implemented**,
and says so rather than contradicting them quietly:

| `req-grid-dimension-em` constraint | Status under this requirement |
| --- | --- |
| Flat Object — "use a flat JSON object, not nested namespace objects" | **Amended.** The map is one level deep: uuid → object. It is still not a nested *namespace* tree, which is what the original constraint was guarding against. |
| Value Types — "allow values to be `string`" | **Amended.** The map's values are objects; the *dimension's* value (`v`) remains a string. |
| Namespaced Keys / Lower Case | **Moved.** These now describe the node's `name` field, not the entity map's keys. The map's keys are uuids. |
| GIN index / containment queries | **Unaffected.** JSONB containment is recursive, so `@> '{"<uuid>": {"v": "configuration"}}'` still matches. Asserted from containment semantics, not measured against this schema — the trial must confirm it. |

`DEFAULT_DIMENSIONS` is typed `ClassVar[dict[str, str]]` on every model that declares one; that
type changes with this requirement, which is part of why this is the largest piece of work in
the redesign and why it is `Proposed` rather than approved.

#### Collectors hardcode dimension guids

A writer that is stamping a dimension already knows, at authoring time, which axis and which
value it means. It uses the **guid**, not a name lookup: a run-time name resolution adds a
lookup, a failure mode, and a dependency on the *current* spelling — which
`req-grid-dimension-node-identity` just made mutable. Hardcoding the guid is what makes the name
safe to rename.

The trade is legibility, mitigated by a comment naming the dimension beside the guid. The
comment is documentation of a fact the guid already fixes; the guid remains the authority and
the comment cannot silently become one.

#### OPEN QUESTION — the trial cannot half-migrate one column

`dcom` going first, alone, is the right size of trial for a *vocabulary*. But the entity
`dimensions` map is **one column shared by every key**, so "dcom moves, nothing else does"
produces a map with uuid-keys and name-keys side by side:

```json
{
  "01a0c057-8f3d-70cd-b07c-c7523153be64": {"v": "configuration", "src": "declared"},
  "tap.meta": "dimension"
}
```

Every reader, every containment query and every merge would then have to branch on "is this
key a uuid or a name?", and a value would be sometimes a string and sometimes an object. That
is two storage shapes in one column — the exact thing `req-grid-dimension-reference`'s own
reasoning rejects for values.

A second, sharper instance of the same problem: `Dimension` itself declares
`DEFAULT_DIMENSIONS = {"tap.meta": "dimension"}`, so under this requirement a dimension node's
own dimensions reference the uuid of the `tap.meta` dimension node — which is itself a
`Dimension`. The `tap.meta` node must exist before any dimension node can be created,
including itself.

Three candidate resolutions, none ruled:

1. **Migrate the whole map at once** and keep the *behaviour* trial scoped to dcom — the shape
   change is all-or-nothing, the learning is still dcom-only.
2. **Accept a dual-read window** with one declared reader function that normalizes both shapes,
   so exactly one place branches, plus a deadline after which the old shape is refused.
3. **Bootstrap `tap.meta` first** as a genesis node created below the normal creation path,
   the way other roots-of-trust are handled.

This must be settled before `req-grid-dimension-reference` moves past `Proposed`. It is the
reason this requirement is the only one in the redesign that is not `Approved for Development`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-dimension-reference-0 | Migration Shape Ruled Before Build | Proposed | The open question above is resolved and recorded here before any code lands. No state exists in which the `dimensions` column carries uuid-keys and name-keys with no single normalizing reader. | Blocks this requirement's promotion out of `Proposed`. |
| req-grid-dimension-reference-1 | Keyed by Node Id | Proposed | An entity's `dimensions` map is keyed by dimension node uuid, never by dotted name. | |
| req-grid-dimension-reference-2 | Value Is a String | Proposed | The `v` member is a plain string. No stored value is a value-node id. | Pairs with `req-grid-dimension-node-identity-3`. |
| req-grid-dimension-reference-3 | Provenance Recorded on Merge | Proposed | The merge in `req-grid-dimension-dc` records `src` per key: `default` for a key supplied by `DEFAULT_DIMENSIONS` or an edge type, `declared` for a caller-supplied key. Explicit-wins is unchanged, and a caller key overriding a default records `declared`. | The merge *rule* does not change; only what it records. |
| req-grid-dimension-reference-4 | Containment Query Still Works | Proposed | A containment query against the GIN index matches an entity by dimension uuid and value without a full table scan. | Guards the Accessible goal through the shape change. |
| req-grid-dimension-reference-5 | Writers Use Guids | Proposed | A writer stamping a dimension references the node's guid directly; no write path resolves a dimension by name. | |

#### Future

The `src` vocabulary is three values because three were foreseeable. A fourth — "inherited from
a container" — is plausible once containment cascades are exercised, and would be an additive
enum change rather than a shape change.

Namespace-prefix search ("everything under `dcom.*`") becomes **two-phase** under this
requirement: resolve names to ids, then query the id set. That is an accepted cost of keeping
`.` as the delimiter, and it is only acceptable while identity lives on the id — if identity
ever leaks back onto the name, it becomes sharp. The related guardrail worth adopting if the
dotted grammar is ever enforced is that a name should not coincide with a namespace, because
the `.` in `git.host` and the `.` in a value like `github.com` are the same character meaning
two different things.


### Dimension Lifecycle Rides Node History
----
RID: `req-grid-dimension-lifecycle`

Status: `Approved for Development`

A dimension node is a spine node, so it carries history: all concrete `BaseModel` subclasses get
history tracking via the `HistoricalRecords` manager declared on the abstract `BaseModel`. Rename
and deprecation are **reads of that timeline**, not new machinery.

This is deprecation infrastructure other vocabularies had to hand-build. A semantic-convention
rename elsewhere required inventing a schema-file format plus a dual-emit opt-in so consumers
could migrate; TAP gets the timeline because the dimension is a node.

#### The boundary, stated precisely

| Question | Answered by | Read |
| --- | --- | --- |
| What did this key mean in March? When was it renamed, deprecated, and by whom? | The **dimension node's** history | One node's timeline |
| Did *this entity* carry that key in March? When did it gain it? | The **entity's** history | That entity's timeline |

The node's history is **the key's life**. Whether a given entity ever carried it is the
**entity's** history — a separate read, against a different object.

Conflating the two is how a deprecation appears handled when it is not: the node's timeline
says "deprecated, superseded by X" and a reader concludes the entities moved, because the
reassuring record exists. Nothing in the node's timeline says anything about any entity. Two
reads, always.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-dimension-lifecycle-1 | Rename Is Recorded | Approved for Development | Changing a dimension node's `name` produces a history record carrying the prior name and the actor. | Uses existing history; no new mechanism. |
| req-grid-dimension-lifecycle-2 | Deprecation Is Three-State | Approved for Development | A deprecated dimension records a successor, an explicit "no successor" (deliberately removed), or says nothing (not deprecated). Absence of a successor must not render as "removed with no successor". | Three states, never two. Carrier not yet chosen — see Future. |
| req-grid-dimension-lifecycle-3 | Two Reads Are Distinct | Approved for Development | Any surface reporting a dimension's lifecycle states which object it read. A node-history read must not be presented as evidence about entity membership. | Documentation and API-surface obligation, not a data-shape one. |

#### Future

The carrier for the deprecation state is **undecided**: a field on the node, a value in the
node's own dimensions map, or a successor *edge* — which is currently blocked by
`req-grid-dimension-no-edges` and is the strongest candidate for the one door that block might
later open, since a rename successor is a fact the dotted name cannot carry.

A **usage back-index** — "what currently carries this dimension?" — is the natural companion to
a deprecation and is not specified here. Elsewhere it is the mechanism that turns the blast
radius of a vocabulary change from a guess into a query. It is a read over the existing GIN
index rather than new storage.


### Deliberately Tabled Dimension Capabilities
----
RID: `req-grid-dimension-tabled`

Status: `Proposed`

Four capabilities were raised on 2026-09-20 and **deliberately deferred**. They are recorded as
decisions with reasoning so they are not re-proposed as if new, and so that the conditions under
which each should be revisited are written down rather than remembered.

#### T1 — No mandate

Dimensions are **not** made mandatory.

The evidence is a public-record failure at scale: a biological-sample repository with 6.6
million records, metadata mandatory, and no structural validation, produced **15% of fields
using names absent from its own data dictionary** and **only 27% of Boolean values valid**
(arXiv:1708.01286). Mandating presence without validating correctness manufactures a
declaration that exists and is false — which is worse than a missing one, because nobody goes
looking for the thing the record says is handled.

The same split shows up in product form elsewhere: a cloud tag-policy service explicitly cannot
enforce that a tag *exists*, so presence enforcement has to live in a separate policy denying
the create call. Presence and correctness are two problems and need two mechanisms.

`req-grid-dimension-dc`'s own `Future` section argues toward a stricter world where a
dimension-less type is a design error. T1 does not delete that ambition; it declines to act on
it **before there is a validator**, because a mandate without a validator is the outcome above.

**Revisit when:** a dimension-key validator exists and is enforced in a code path — not in
prose.

#### T2 — No general-purpose delete-by-dimension

Instead: **custom per-case deletion functions**, with AWS account teardown as the first
canonical example.

Selection and deletion authority are kept apart deliberately elsewhere: labels select,
ownership references govern cascade, and they are different mechanisms because a label is a
*view* over a set and a view is not a mandate to destroy its members. A delete-by-label
primitive turns every accidentally-broad selector into a data-loss event, and selectors are
broad by nature — that is what they are for.

TAP already models this separation from the other direction: `CONTAINMENT_EDGES` is a dedicated
cascade declaration, explicitly *not* a flag inside `OUTBOUND_EDGES`, which is edge permission
only (`req-grid-service-delete-cascade`). Delete-by-dimension would reintroduce exactly the
conflation that declaration exists to avoid.

**Revisit when:** three or more per-case deletion functions exist and are observed to share a
common shape — at which point the abstraction is discovered rather than guessed.

#### T3 — No namespace reservation needed

Core's dimension nodes land at boot and a plugin cannot overwrite an existing node. **First-mover
occupancy replaces a reserved prefix.**

What makes this work is the **immutability of an existing node — structural — not the prefix —
documentary**. A reserved-prefix convention is a rule that must be remembered; an existing node
is a fact that must be contended with. TAP gets the coordination point for free because the
node *is* the registry entry, and gets the reservation for free because the node already
exists.

The corollary is the thing to watch: this holds only while "a plugin cannot overwrite an
existing node" is true and enforced. If that ever becomes a soft rule, T3 silently becomes
false and nothing will announce it.

**Revisit when:** the no-overwrite property changes, or a plugin is observed shipping a node
that shadows a core one.

#### T4 — The second map, raised and parked

The labels-vs-annotations split found elsewhere — one key grammar, two stores, differing on
whether the value is indexed — exists because people inevitably want to attach load-bearing
data that is not a search key, and forcing that into the selectable store either bloats the
index or corrupts the grammar.

TAP may need the same split. It does not need it yet.

**Revisit when:** someone first wants to put something **structured** — an object, a list, a
blob — in a dimension value. That request is the second map asking to be born. Note the
awkwardness it will arrive with: `req-grid-dimension-reference` already puts a nested object in
the map, so "values are strings" is no longer a clean line to hold, and the argument will be
harder to hear than it would have been. Watch for the **intent** — a value that is data rather
than a label — not for the shape.

(Distinct from, and neither advanced nor blocked by, the draft "pocket dimension" overlay
concept in `spec-grid-dimension-pocket-BACKLOG.md`, which is an isolation mechanism wearing the
same word.)

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-dimension-tabled-1 | Tabling Is Recorded, Not Implied | Proposed | Each tabled capability carries its reasoning and an explicit revisit condition in this spec. | The requirement is satisfied by this section existing and staying accurate. |
| req-grid-dimension-tabled-2 | No Mandate Ships Without a Validator | Proposed | No change makes any dimension mandatory while the dotted-name grammar remains unenforced. | T1. |
| req-grid-dimension-tabled-3 | No Generic Delete-by-Dimension | Proposed | The service layer exposes no delete-by-dimension primitive. Deletion driven by a dimension is a named per-case function. | T2. |


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
