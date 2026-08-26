# Grid Entity Specification

## Philosophy

This specification captures the current architectural intent for the entity layer. The current direction favors clean abstraction layers: `Entity` as the base for higher layer concepts of `Node` and `Edge` defined as the BaseModel.  Within that model, the entity spine remains the canonical reference for a single concrete node or edge instance.

## Goals

|    |              |                                                                                 |
| :---: | ---       | ---                                                                             |
| 1. | Canonical    | Entity is the canonical reference system-of-record for grid data                |
| 2. | Dimensioned  | Entity models store the dimensionality information for their nodes and edges    |
| 3. | Metadata     | Entity instance contains the metadata common across all nodes and edges         |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-entity-spine | [Entity Spine Mapping](#entity-spine-mapping) | Implemented | `Entity` is the canonical node instance for nodes and edges |
| req-grid-entity-type | [Entity Type Declaration](#entity-type-declaration) | Implemented | BaseModel subclasses declare `ENTITY_TYPE`; registered in the model registry |
| req-grid-entity-base | [BaseModel Auto-Creates Entity](#basemodel-auto-creates-entity) | Implemented | `BaseModel.save()` auto-creates its Entity atomically when none is set |
| req-grid-entity-type-kind | [Type Catalog Discriminates Node vs Edge](#type-catalog-discriminates-node-vs-edge) | Implemented | `EntityType.kind` (`node`/`edge`) — the catalog holds both because edges ARE entities; the writer stamps it and the API exposes and filters on it |
| req-grid-entity-resolve | [Entity Resolution](#entity-resolution) | Implemented | `Entity.resolve()` uses the model registry to return the concrete typed object |
| req-grid-entity-ee | [Entities Are Entities](#entities-are-entities) | Deprecated | Significant architectural shift; explicitly not part of current direction |
| req-grid-entity-validation | [BaseModel Field Validation](#basemodel-field-validation) | Implemented | Three-layer validation (JSON Schema, per-field functions, whole-record hook) on derived model fields; hooked into save() |
| req-grid-entity-internal | [Internal-Only Model Types](#internal-only-model-types) | Implemented | Some model types are graph-native but not writable through the default service-layer CRUD surface |
| req-grid-entity-crud | [Service-Layer CRUD Schema](#service-layer-crud-schema) | Implemented | `FIELD_CRUD_SCHEMA` declares the service-layer write surface; dual schema requirement with `FIELD_VALIDATION_SCHEMA` |
| req-grid-entity-constraints | [Known Model Constraints](#known-model-constraints) | Implemented | Documented field name collisions and other BaseModel authoring constraints |
| req-grid-entity-metadata | [Canonical Entity Metadata](#canonical-entity-metadata) | In Development | Platform-level canonical metadata contract for entity instances: `name`, `description`, `description_json`. `name` is fully implemented; `description` and `description_json` are pending. |
| req-grid-entity-display | [Display Metadata](#display-metadata) | In Development | `DEFAULT_DISPLAY` class attribute implemented on `BaseModel`; instance-level `display` JSONField deferred |
| req-grid-entity-cascade | [Edge-Directed Cascade Deletion](#edge-directed-cascade-deletion) | Backlog | When an entity is deleted, cascades should be expressible in terms of edge relationships, not just Django's raw FK CASCADE |
| req-grid-entity-core-type-catalog | [First-Party Types In The Catalog](#first-party-types-in-the-catalog) | Backlog | Core-app types are absent from `EntityType` (only plugins write rows), so they render without icons. Pick this up when someone cares about the missing icons |
| req-grid-entity-tombstone-managers | [Tombstone State And Manager Surface](#tombstone-state-and-manager-surface) | Approved for Development | `Entity.deleted_at` is the single canonical home of tombstone state; manager defaults differ by surface; both surfaces expose uniform `.live()` / `.tombstoned()` chainable filters |


## Explanation

An `Entity` entry on the Entity Table (also called the Entity Spine) represents a single canonical concrete typed (BaseModel) instance. Every typed model instance built on `BaseModel` will corresponds to exactly one `Entity` through a one-to-one mapping. This keeps the cross-cutting metadata on the spine while allowing typed tables such as `Character` to hold type-specific fields and allows edges to be defined as having a source Entity ID and a destination Entity ID.

This specification distinguishes three related but different concerns:
- canonical entity instance metadata
- type registry/catalog metadata
- presentation/display hints

Canonical entity instance metadata is governed by `req-grid-entity-metadata`.
That requirement is about the standard metadata contract for a concrete entity instance. `EntityType.name` was aligned as part of the same refactor that introduced this contract.

### Background
The Entity Spine is what makes traversal across Entity types consistent without having to duplicate the metadata fields on every BaseModel derived table.  Honestly I could have gone that route but for reasons even I'm not clear on we're going with the spine approach first.


## Requirements

### Entity Spine Mapping
----
RID: `req-grid-entity-spine`
Status: `Implemented`

#### Status Details
Implemented and verified. The entity spine mapping was the original architecture; the auto-creation and confirmation behavior was added in the session that produced `req-grid-entity-base`.

#### Implementation
The mapping is:

| Layer | Role |
| --- | --- |
| `Entity` | Canonical concrete reference for every BaseModel instance containing cross-cutting metadata |
| `BaseModel` subclass | Typed one-to-one implementation of an instance that references the Entity Id|

`BaseModel.save()` creates a new Entity automatically when a new instance is saved without an existing entity. On save it stores the appropriate Entity and typed class into its particular table. See `req-grid-entity-base` for the full auto-creation behavior.

#### Development
The initial implementation didn't automatically tie Entity and BaseModel creation together. `req-grid-entity-base` closes that gap. The `entity` OneToOneField is non-nullable at the schema level; the `save()` override ensures the field is populated before Django's insert, so no schema change was required.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-spine-1 | Entity Is Canonical Instance | Implemented | `Entity` is treated as the canonical concrete base instance stored in the entity spine. | |
| req-grid-entity-spine-2 | One-to-One Extension | Implemented | Each typed entity model extending `BaseModel` maps to exactly one `Entity` through a one-to-one relationship. | |
| req-grid-entity-spine-3 | BaseModel Creates Entity | Implemented | When saving a new BaseModel instance without an entity set, an `Entity` is automatically created using the subclass's `ENTITY_TYPE` and `get_name()`. See `req-grid-entity-base`. | |
| req-grid-entity-spine-4 | BaseModel Confirms Entity | Implemented | When saving a BaseModel instance that already has an entity set, it confirms the Entity exists on the spine and that its `entity_type` matches the subclass's `ENTITY_TYPE`. Raises `ValueError` otherwise. | |

#### Future


---

### Canonical Spine Surface
----
RID: `req-grid-entity-spine-surface`
Status: `Proposed`

The set of fields stored on the `Entity` row, and their canonical order
when serialized, is fixed and reusable across TAP. Higher-level specs
that emit `Entity` content (envelopes, GRIFT documents, API responses)
reference this requirement rather than redefining the order.

#### Implementation

The canonical Entity-row fields, in their canonical serialization order:

| Field | Source | Notes |
| --- | --- | --- |
| `entity_id` | `Entity.id` (renamed for serialization) | UUID. Typically UUIDv7 for collector- and service-emitted entities; UUIDv5 for deterministic-identity scenarios (e.g. the boto3 collector's `uuid5(NS, "<type>:<natural_key>")`). The stable identifier. |
| `entity_type` | `Entity.entity_type` | Polymorphism discriminator. Immutable post-create. |
| `name` | `Entity.name` | Human-readable. Descriptive metadata, not a stable identifier (the `entity_id` is). |
| `dimensions` | `Entity.dimensions` | Scoping/partitioning JSON object. |
| `created_at` | audit timestamp | ISO 8601 UTC. |
| `updated_at` | audit timestamp | ISO 8601 UTC. |
| `deleted_at` | `Entity.deleted_at` | Tombstone timestamp or `null`. |
| `version` | `Entity.version` | Monotonic counter; increments on canonical mutation including tombstone. |
| `originating_grid_id` | `Entity.originating_grid_id` | Source grid identifier. Premature in v0; flagged for removal. See Future. |

The `id` field renames to `entity_id` at the serialization boundary so
"id" is reserved for the inner identity within a polymorphic context
(e.g. when an envelope nests multiple identifier shapes).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-spine-surface-1 | Fields Enumerated | Proposed | The set of Entity-row fields is enumerated above; adding a new field requires updating this requirement. | |
| req-grid-entity-spine-surface-2 | Serialization Order Stable | Proposed | Serializers emit Entity fields in the order specified. Aids reading, diffing, and locating fields by position. | |
| req-grift-entity-spine-surface-3 | entity_id Is UUID, Not UUIDv7-Specific | Proposed | The `entity_id` is a UUID. Callers must not assume UUIDv7 layout; deterministic-identity scenarios use UUIDv5. | |
| req-grid-entity-spine-surface-4 | Higher-Level Specs Reference, Not Redefine | Proposed | Specs that emit Entity content (envelope, GRIFT, API) reference this requirement rather than restating the field list and order. | |

#### Future

- **Remove `originating_grid_id`.** The field was added in anticipation
  of cross-grid identity reconciliation; in practice we have not needed
  it and it carries no current meaning in single-grid workflows. Marked
  for removal — exact migration path TBD when removal is scheduled.
- **`description` / `description_json` on the spine.** The canonical
  entity metadata contract (`req-grid-entity-metadata`) names these as
  universal but they're currently stored on `BaseModel`, not on the
  Entity row. If they ever migrate to the spine, they join this surface
  in the canonical order between `name` and `dimensions`.

---

### Entity Type Declaration
----
RID: `req-grid-entity-type`
Status: `Implemented`

#### Status Details
Implemented and verified. All concrete BaseModel subclasses across `tap_grid`, `tap_flip`, `tap_viz`, and all plugins now declare `ENTITY_TYPE`.

#### Implementation
Each non-abstract BaseModel subclass declares `ENTITY_TYPE` in its class body:

```python
class Concept(BaseModel):
    ENTITY_TYPE: ClassVar[str] = "concept"
```

During `__init_subclass__`, any subclass that declares `ENTITY_TYPE` in its own `__dict__` (not inherited) is registered in the model registry in `tap_grid/registry.py`:

```python
_ENTITY_MODEL_REGISTRY: dict[str, type] = {}

def register_entity_type(entity_type: str, model_cls: type) -> None:
    ...  # raises ImproperlyConfigured on duplicate slug registered to a different class

def get_model_class(entity_type: str) -> type:
    ...  # raises KeyError with descriptive message if not found
```

`__init_subclass__` also switches edge constraint registration to use `ENTITY_TYPE` as the key (previously used `cls.__name__.lower()`), with a fallback for abstract intermediaries that define edge shapes without declaring a concrete type.

Registered types as of implementation: `edge`, `concept`, `precept`, `batch`, `layout`, `dimension`, `character`, `location`, `artifact`, `race`, `faction`, `sentinel`, `citadel`, `wanderer`.

#### Development
`__init_subclass__` already handled FLIP config and edge constraint registration. Adding the model registry there keeps all class-level setup in one place and avoids a separate `AppConfig.ready()` import dance. Using `cls.__dict__.get("ENTITY_TYPE")` (not `getattr`) ensures only classes that explicitly declare the attribute are registered — inherited values from abstract parents do not accidentally trigger registration.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-type-1 | ENTITY_TYPE Required | Implemented | Every concrete BaseModel subclass declares `ENTITY_TYPE: ClassVar[str]`. Attempting to save a subclass without it raises `ImproperlyConfigured`. | |
| req-grid-entity-type-2 | Registry Population | Implemented | `__init_subclass__` registers the subclass in `_ENTITY_MODEL_REGISTRY` keyed by `ENTITY_TYPE`. | |
| req-grid-entity-type-3 | No Duplicate Types | Implemented | Registering a duplicate `ENTITY_TYPE` raises `ImproperlyConfigured` at class definition time. | |
| req-grid-entity-type-4 | Abstract Subclasses Excluded | Implemented | Abstract BaseModel subclasses omit `ENTITY_TYPE` and are not registered. | |

#### Future
Consider a management command or system check that validates all registered entity types against the current entity spine contents to surface data integrity issues at startup.

The `entity_types` list in `TapPluginConfig` (and equivalent `apps.py` declarations) is a separate layer from the in-memory model registry: the model registry (`_ENTITY_MODEL_REGISTRY`) is populated automatically at class-definition time and is sufficient for all functional operations. The `EntityType` DB table exists solely to serve the API's type catalogue with display metadata (`name`, `icon`, `description`, `plugin_name`). This creates duplication — the same type is declared once in the model and again in `apps.py`. The natural resolution is to add `DISPLAY_NAME`, `DESCRIPTION`, `ICON` as class vars on `BaseModel` subclasses and have `__init_subclass__` (or a `ready()`-time sweep of the model registry) populate `EntityType` automatically, eliminating the `entity_types` list entirely.

---

### First-Party Types In The Catalog
----
RID: `req-grid-entity-core-type-catalog`
Status: `Backlog`

**Trigger to pick this up:** someone notices that core types — `page`, `panel`, `layout`,
`collector`, `batch`, `keystone`, `dimension`, `schedule`, `projection`, `arrangement` and the rest,
about fifteen in total — render without icons in the graph view. That is the only user-visible
consequence today, and it is cosmetic, which is why this is Backlog rather than scheduled.

**Why they are missing.** `EntityType` rows are written only by the plugin loader from a manifest
(plus the single `search` row from `tap_grid`'s own `ready()`), and first-party apps ship no manifest.
The types themselves work perfectly — they are registered in the in-code model registry by
`BaseModel.__init_subclass__` — they simply have no catalog row, so the display-metadata lookups
(`batch_resolve_icons`, the viewer panel) find nothing for them.

**Proposed shape** (measured against the as-built code, 2026-08-12):

- One function that walks the entity model registry and upserts a row per registered type: `slug`
  from `ENTITY_TYPE`, `name` from `ENTITY_NAME` falling back to the slug, `description`/`icon` from
  `ENTITY_DESCRIPTION`/`ENTITY_ICON` defaulting to empty, `kind` = node.
- **Gotcha that will silently break icons if missed:** `plugin_name` must be the owning AppConfig's
  dotted `name` (e.g. `tap_web`), *not* `app_label` — `resolve_icon_path` resolves the owning app by
  looping app configs and comparing `config.name == entity_type.plugin_name`.
- Run it from **boot's population phase**, not `ready()` — `ready()` has no DB access, and the
  existing plugin write violates that rule today (it is the source of the "accessing the database
  during app initialization" warning). Having the plugin loader call the same function instead of
  writing rows itself collapses this to one writer and removes that violation.
- Additive only: it must never delete rows. Reclamation is a separate, deliberately parked decision
  (`req-tap-plugin-lifecycle-v1-departure`).

**Extensibility, which is the point.** Adding a core model then requires only the class vars plugins
already use — declare `ENTITY_TYPE` (already mandatory) plus optionally `ENTITY_NAME`/`ENTITY_ICON`/
`ENTITY_DESCRIPTION` — and the type appears at the next boot with no registration list, manifest
entry, migration, or code change anywhere else. One convention across core and plugins. This is the
direction already sketched at the end of [Entity Type Declaration](#entity-type-declaration).

**Cost split.** The mechanism is roughly thirty lines plus a call site. The rest is *content*: each
type wanting an icon needs a kebab-case `ENTITY_ICON` key and an SVG in its app's static directory.
That content is incremental — landing the mechanism alone gives every core type a correctly-named
catalog row (fixing the completeness half), and icons fill in per model afterwards with no further
code, degrading exactly as today when absent.

**Out of scope.** Edge types: core edges register constraints only, have nowhere to declare display
metadata, and the icon path is node-only. Also out of scope is the deeper question of what the type
record *is* — provenance (which plugin or which core app), model version, and the fields that follow
— which is the same reconciliation problem as plugin lifecycle one level down and is parked with it
(`tap_plugins/specs/spec-tap-plugin-lifecycle-v1.md`). This requirement deliberately does not settle it:
it writes `plugin_name` exactly as the existing writer does.

### Type Catalog Discriminates Node vs Edge
----
RID: `req-grid-entity-type-kind`
Status: `Implemented`

The `EntityType` catalog holds **node types and edge types alike**, and that is correct, not a defect: edges *are* entities (`Edge` is a `BaseModel`, so every edge carries a backing `Entity` — `req-grid-entity-spine`), and a plugin manifest declares both. What the catalog lacked was a way to tell them apart, so a consumer reading it could not answer "what node types exist?" without already knowing which slugs happen to be edges.

Measured before the fix (a healthy booted instance): 87 catalog rows against 30 in-code node models and 12 in-code core edge types. The bulk of the remainder are plugin-declared edge types — legitimately catalogued, simply indistinguishable.

#### Implementation

- `EntityType.kind` is a `TextChoices` field (`node` / `edge`), indexed.
- **The writer stamps it**, because the writer is the only place that knows: the manifest lists `models` and `edges` separately (`tap_plugins/base.py::_register_types_from_manifest`). It cannot be recovered downstream — the in-code edge registry is populated only when plugins load, so a sweep in a bare process would see core edges alone and misclassify every plugin edge as a node.
- **Empty means "not yet classified", never "node".** Rows written before the field existed keep `""` until their writer next runs; because the loader uses `update_or_create`, they self-heal on the next plugin load. A consumer must treat `""` as unknown — the API's `?kind=node` deliberately does not match them.
- `GET /api/v1/entity-types/` exposes `kind` and accepts `?kind=node|edge`. An unrecognised value returns an empty list rather than the unfiltered catalog: over-returning is the dangerous direction for a typo'd filter.

#### Known gaps (not closed by this requirement)

Two, both measured on a live instance after this landed, and both about *which rows exist* rather than how they are labelled:

1. **First-party types are absent.** Rows are written only by the plugin loader (plus the `search` row from `tap_grid`'s own `ready()`), and first-party apps ship no manifest — so ~15 registered node types (`page`, `panel`, `layout`, `collector`, `batch`, `keystone`, …) have no row and therefore no `kind`. Tracked as [req-grid-entity-core-type-catalog](#first-party-types-in-the-catalog) (Backlog, with the proposed mechanism and its gotchas); the discriminator here is a prerequisite for closing it, since a completeness sweep must record which kind it registers.
2. **Rows outlive their plugin.** The catalog has no removal path. Measured on a long-lived dev database (first migrated three weeks earlier) whose plugin set had since narrowed to `grid_fixtures` alone: 56 rows owned by `aws_core` — a plugin no longer installed in that container — written early in the database's life and untouched by any transaction since, with zero corresponding entities (types registered, population never run). Rows are written only by `TapPluginConfig`, so the plugin must have been in `INSTALLED_APPS` at the time; when it left the app set nothing reclaimed its rows. They stay `kind=""` because only the declaring plugin's loader can classify them, so an API consumer sees types the instance cannot serve. This is an accumulated-state condition, not something a fresh instance exhibits. Whether a type row should be removed, tombstoned, or retained-and-marked when its plugin leaves the boot profile is an open decision, and it belongs with the plugin update/uninstall design in `tap_plugins/specs/spec-tap-plugin-lifecycle-v1.md` rather than here.

This is also why `""` must not be read as `node`: the unclassified rows on that instance were predominantly *edges*, so a `node` default would have actively mislabelled them.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-type-kind-1 | Both Kinds Catalogued | Implemented | The catalog holds node types and edge types; edge rows are not removed. | edges are entities (`req-grid-entity-spine`) |
| req-grid-entity-type-kind-2 | Writer Stamps The Kind | Implemented | The manifest loader sets `kind` on both its model and edge writes; nothing infers it later. | only the writer knows |
| req-grid-entity-type-kind-3 | Empty Is Unknown | Implemented | `""` means unclassified and never matches a `kind` filter; rows self-heal on the next plugin load. | must not be read as `node` |
| req-grid-entity-type-kind-4 | API Exposes And Filters | Implemented | `kind` is in the API schema; `?kind=` narrows; an unknown value returns empty, not everything. | fail-closed filter |

### BaseModel Auto-Creates Entity
----
RID: `req-grid-entity-base`
Status: `Implemented`

#### Status Details
Implemented and verified. All 265 tests pass including the new auto-creation, entity confirmation, and edge endpoint validation tests.

#### Implementation
`BaseModel.save()` is overridden to handle Entity auto-creation:

```python
def save(self, *args, **kwargs):
    entity_type = getattr(self.__class__, "ENTITY_TYPE", None)
    if entity_type is None:
        raise ImproperlyConfigured(...)

    if self.entity_id is None:
        with transaction.atomic():
            base_dims = dict(getattr(self.__class__, "DEFAULT_DIMENSIONS", {}))
            caller_dims = getattr(self, "_initial_dimensions", {})
            self.entity = Entity.objects.create(
                entity_type=entity_type,
                name=self.get_name(),
                dimensions={**base_dims, **caller_dims},
            )
            super().save(*args, **kwargs)
    else:
        self._confirm_entity()
        super().save(*args, **kwargs)
        Entity.objects.filter(pk=self.entity_id).update(updated_at=timezone.now())
```

`get_name()` returns `""` by default; subclasses override it to provide a meaningful label. `Edge` overrides it to produce `"<from_id> --[<type>]--> <to_id>"`.

`_confirm_entity()` validates that the entity exists and its `entity_type` matches `self.ENTITY_TYPE`. Raises `ValueError` if either check fails.

`DEFAULT_DIMENSIONS` (optional `ClassVar[dict[str, str]]` on BaseModel subclasses) seeds the `dimensions` field on the auto-created Entity. Caller-supplied `_initial_dimensions` are merged on top. See `spec-grid-dimension.md` for full dimension semantics.

`Edge` overrides `save()` to add endpoint validation before delegating to `BaseModel.save()`:
- Confirms `from_entity` exists on the spine; raises `ValueError` if not.
- Confirms `to_entity` exists on the spine; raises `ValueError` if not.
- Inherits `DEFAULT_DIMENSIONS` from the source node's model class.
This check runs before any write, so a failed validation leaves no orphaned Entity row.

`create_edge()` in `tap_grid/services.py` was refactored to rely on `Edge.save()` auto-creation rather than manually pre-creating the backing Entity.

#### Development
`transaction.atomic()` ensures the Entity row and the domain model row are either both committed or both rolled back. Without this, a failure between the two creates an orphaned Entity row on the spine.

Passing an explicit `entity=` on construction remains valid for migration compatibility and testing. The `_confirm_entity()` path handles that case and enforces consistency rather than silently accepting whatever is passed.

The dimensions integration was added concurrently with the dimension spec work; the Entity `dimensions` JSONField and the `DEFAULT_DIMENSIONS` class variable on BaseModel were introduced as part of `spec-grid-dimension.md`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-base-1 | Auto-Creation on Save | Implemented | Saving a new BaseModel subclass instance without `entity` set automatically creates an `Entity` row with the correct `entity_type` and `name`. | |
| req-grid-entity-base-2 | Atomic Transaction | Implemented | Entity creation and BaseModel row insertion are wrapped in `transaction.atomic()`. A failure in either rolls back both. | |
| req-grid-entity-base-3 | Overridable Name | Implemented | `get_name()` returns `""` by default; subclasses may override to provide a meaningful name without requiring callers to set it. | |
| req-grid-entity-base-4 | Explicit Entity Still Valid | Implemented | Passing an explicit `entity=` remains valid; the save path skips auto-creation and instead confirms the entity (spine-4). | |
| req-grid-entity-base-5 | create_edge Refactored | Implemented | `tap_grid/services.py create_edge()` no longer manually creates its backing Entity; it relies on `Edge.save()` auto-creation instead. | |
| req-grid-entity-base-6 | Edge Endpoint Validation | Implemented | `Edge.save()` confirms both `from_entity` and `to_entity` exist on the spine before any write. Raises `ValueError` with a clear message identifying which endpoint is missing. | |
| req-grid-entity-base-7 | No Orphan on Failed Validation | Implemented | A failed endpoint check in `Edge.save()` leaves no orphaned Entity row on the spine. | |

#### Future
Once FLIP is fully active, Entity creation through this path should be recorded as a provenance event. In v0 this is deferred; the mechanism should be hookable so FLIP can be wired in without changing this code.

---

### Internal-Only Model Types
----
RID: `req-grid-entity-internal`
Status: `Implemented`

Some `BaseModel` subclasses are first-class graph objects but should not be writable through the default service-layer create, patch, replace, and delete verbs. These are internal-only model types.

#### Status Details
Implemented. `BaseModel` declares `INTERNAL_ONLY: ClassVar[bool] = False`. `Batch` sets `INTERNAL_ONLY = True`. The generic write pipeline in `tap_grid/services.py` checks `INTERNAL_ONLY` after resolving `model_cls` for all node verbs and raises `ServiceUnsupportedOperationError`. FLIP stamping is also suppressed for internal-only types.

#### Implementation
The internal-only model contract is:

1. `BaseModel` subclasses may declare `INTERNAL_ONLY: ClassVar[bool] = True`.
2. `INTERNAL_ONLY = False` is the default for ordinary model types.
3. Internal-only model types remain first-class entities on the spine and may still be readable, traversable, and linkable according to other rules.
4. Internal-only model types are not writable through the default service-layer create, patch, replace, and delete surface.
5. Internal-only model types may still be managed through dedicated subsystem services.

`Batch` is the first intended example of an internal-only model type.

#### Development
This gives TAP a clean way to distinguish:

- graph-native objects that should exist on the spine
- from objects that ordinary callers should not mutate through generic CRUD verbs

That boundary will likely be useful in several places beyond batches.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-internal-1 | Internal Only Class Variable | Implemented | `BaseModel` subclasses may declare `INTERNAL_ONLY` to mark the type as not writable through the default service CRUD surface. | `INTERNAL_ONLY: ClassVar[bool] = False` on `BaseModel`; `Batch` sets `True` |
| req-grid-entity-internal-2 | Default Is False | Implemented | Model types are not internal-only unless they explicitly declare that capability. | `BaseModel.INTERNAL_ONLY = False` default |
| req-grid-entity-internal-3 | Still First-Class Entities | Implemented | Internal-only model types remain graph-native entities rather than second-class hidden tables. | `Batch` extends `BaseModel`, has Entity on spine |
| req-grid-entity-internal-4 | Dedicated Services Still Allowed | Implemented | Internal-only model types may still be managed through dedicated subsystem services. | `tap_grid/batch.py` service functions and `_ensure_batch` in `tap_grid/services.py` are the v0 example, using direct ORM. |
| req-grid-entity-internal-5 | Trusted-Internal Create Path | Proposed | New INTERNAL_ONLY types are created through `_create_node_internal` in `tap_grid/services.py` (see `req-grid-service-write-internal-create` in `spec-grid-service-write.md`), which runs the full write pipeline minus the INTERNAL_ONLY gate. | Canonical for `Collector`, `CollectionJob`, and future `Emitter`/`Action`. `Batch`'s existing direct-ORM path remains and may be migrated incidentally. |
| req-grid-entity-internal-6 | Dual-Existence Pattern Consumer | Proposed | Plugin-declared capabilities follow the dual-existence pattern (see `tap_grid/specs/spec-grid-dual-existence.md`): grid-side `INTERNAL_ONLY = True`, sub-grid registry, single `register_<thing>(...)` entry point, deterministic UUIDv5 identity. | |

---

### Canonical Entity Metadata
----
RID: `req-grid-entity-metadata`
Status: `In Development`

TAP needs one canonical metadata contract for entity instances so higher-level capabilities can rely on stable terms and do not each invent their own naming surface. The standard metadata contract for a TAP entity instance is:
- `name`
- `description`
- `description_json`

#### Status Details
`name` is fully implemented across the codebase: `Entity.name`, `EntityType.name`, `Search.name`, `Page.name`, `Panel.name`, `LandingPage.name`, and all API schemas, serializers, seed data, and tests are aligned. `description` and `description_json` are not yet implemented.

#### Implementation
The canonical entity instance metadata contract is:
- `name`: required text string; the canonical human-readable identifier for the instance
- `description`: optional text string; the canonical plain-text descriptive field
- `description_json`: optional JSON blob; the canonical structured descriptive field

This requirement applies conceptually to TAP entity instances backed by `BaseModel`.

Cross-spec terminology rule:
- `name` is the canonical spec term for entity instance identity text
- `description` is the canonical spec term for plain-text descriptive content
- `description_json` is the canonical spec term for structured descriptive content
- `title` should only be used when a spec is describing a current implementation detail that has not yet been aligned
- `display_name` should only be used when referring to legacy implementation terminology or non-instance registry/type metadata

This requirement is about canonical entity instance metadata only.
`description` and `description_json` are pending implementation.

#### Development
`name` is the only implemented field from this contract. All uses of `title` and `display_name` as entity instance metadata terms have been removed from the codebase and replaced with `name`.

Higher-level specifications should reference this requirement and use `name`, `description`, and `description_json` as the canonical terms for entity instance metadata.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-metadata-1 | Canonical Metadata Contract Exists | Implemented | TAP entity instances have a canonical metadata contract consisting of `name`, `description`, and `description_json` at the specification level. | |
| req-grid-entity-metadata-2 | Name Is Canonical Required Identifier | Implemented | `name` is the required canonical human-readable identifier for an entity instance. | |
| req-grid-entity-metadata-3 | Description Is Canonical Plain Text Field | Proposed | `description` is the canonical optional plain-text descriptive field for an entity instance. | |
| req-grid-entity-metadata-4 | Description Json Is Canonical Structured Field | Proposed | `description_json` is the canonical optional structured descriptive field for an entity instance. | |
| req-grid-entity-metadata-5 | Higher-Level Specs Align | Implemented | Higher-level TAP specifications align their entity instance metadata terminology to this contract. | |
| req-grid-entity-metadata-6 | Legacy Terms Are Non-Canonical | Implemented | `title` and `display_name` have been removed as entity instance metadata terms from all models, APIs, serializers, templates, seed data, and tests. | |

#### Future
Define the implementation and migration strategy for aligning models, APIs, and storage with this metadata contract.

Define how the canonical metadata contract should map onto concrete storage fields, API schemas, and generic serialization layers.

---

### Display Metadata
----
RID: `req-grid-entity-display`
Status: `In Development`

TAP-managed objects need a lightweight way to carry presentation-oriented metadata such as label resolution hints and future visualization/display guidance. This metadata belongs on `BaseModel` for now and is distinct from core domain data. Canonical icon behavior is defined separately in `spec-grid-icon.md`.

#### Status Details
Backlog requirement created to capture a growing set of display concerns without prematurely turning them into dedicated database columns or web-only features.

#### Implementation
Proposed direction:
- `display` is an optional JSON field on `BaseModel`
- `display` defaults to `{}`
- `display` stores instance-level display overrides
- model/type definitions may declare `DEFAULT_DISPLAY` for type-wide display defaults
- consumers resolve effective display metadata from model defaults plus instance overrides

This metadata is intended for presentation concerns such as:
- label / name resolution strategy
- future Cytoscape or graph visualization hints
- future hierarchy or representation hints used by clients

`display` is not intended to replace core domain fields or graph relationships.

Current direction keeps `display` on `BaseModel`. If TAP later introduces a broader generic metadata mechanism, storage may be revisited at the `Entity` level.

#### Development
Use `display` as a presentation-specific bucket rather than a general metadata junk drawer. The field exists to support multiple consumers (`web`, `viz`, admin, and future interfaces) with one consistent mechanism.

Keep the first version lightweight: capture the concept, the storage location, and the separation between defaults and overrides before defining detailed schema or merge semantics.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-display-1 | Display Lives On BaseModel | Backlog | Proposed direction is that `display` lives on `BaseModel` rather than `Entity`. | May be revisited if a broader metadata system emerges. |
| req-grid-entity-display-2 | Display Defaults Empty | Backlog | Proposed direction is that instance `display` defaults to `{}`. | |
| req-grid-entity-display-3 | Model Defaults Supported | Implemented | `DEFAULT_DISPLAY: ClassVar[dict[str, Any]] = {}` added to `BaseModel`; subclasses override per type. | |
| req-grid-entity-display-4 | Instance Overrides Supported | Backlog | Proposed direction is that instance `display` may override model/type display defaults. | |
| req-grid-entity-display-5 | Presentation Concerns Only | Backlog | `display` is intended for presentation concerns such as label resolution and visualization hints rather than core domain data. | Canonical icon behavior is defined separately in `spec-grid-icon.md`. |

#### Future
Define concrete merge semantics for `DEFAULT_DISPLAY` plus instance `display`.

Define the initial standardized keys under `display`, starting with label/name resolution and visualization hints. Canonical icon behavior is defined separately in `spec-grid-icon.md`.

If TAP later introduces a broader metadata object, revisit whether `display` should remain on `BaseModel` or move to `Entity`.

---

### Entity Resolution
----
RID: `req-grid-entity-resolve`
Status: `Implemented`

#### Status Details
Implemented and verified. `entity.resolve()` and `resolve_entity()` are live and tested for `Concept`, `Precept`, and `Edge`.

#### Implementation
`Entity` has a `resolve()` instance method:

```python
def resolve(self) -> "BaseModel":
    from tap_grid.registry import get_model_class
    model_cls = get_model_class(self.entity_type)
    return model_cls.objects.get(entity_id=self.pk)
```

`tap_grid/registry.py` provides a module-level helper for resolving from a UUID alone:

```python
def resolve_entity(entity_id: UUID) -> "BaseModel":
    entity = Entity.objects.get(pk=entity_id)
    return entity.resolve()
```

Two DB hits total: one for the Entity row (to get `entity_type`), one for the concrete table. If the Entity is already in hand, `entity.resolve()` skips the first hit.

#### Development
Django's `related_name="%(class)s"` on the OneToOneField creates reverse accessors (`entity.concept`, `entity.edge`, etc.) but using them requires knowing the type in advance. `resolve()` replaces the need to try accessors speculatively and provides a stable API surface that does not change as new entity types are added.

The model registry is always fully populated before any request or task can call `resolve()` because `__init_subclass__` fires at class definition time during app startup.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-resolve-1 | Resolve Returns Typed Object | Implemented | `entity.resolve()` returns the concrete BaseModel subclass instance corresponding to that Entity. | |
| req-grid-entity-resolve-2 | resolve_entity Helper | Implemented | `resolve_entity(entity_id)` in `tap_grid/registry.py` resolves from a UUID without requiring a pre-fetched Entity instance. It is **below-the-gate model-layer machinery**, the UUID-keyed peer of `Entity.resolve()` — deliberately NOT in the module's `__all__`, because a public export invites application code to reach it instead of the capability-gated service read (`tap_grid.services.resolve_entity` / `get_node`). | De-exported 2026-08-12 (code-clone sweep C8): the helper is spec'd and stays, the ungated *public surface* is what was removed. |
| req-grid-entity-resolve-3 | Unregistered Type Raises Error | Implemented | Resolving an entity whose `entity_type` is not in the registry raises `KeyError` with a descriptive message listing registered types. | |
| req-grid-entity-resolve-4 | Edge Resolves Correctly | Implemented | `entity.resolve()` works for entities whose type is `"edge"`, returning the `Edge` instance. | |

#### Future
Consider caching the resolved object on the Entity instance (e.g., `_resolved`) to avoid repeat DB hits when resolve() is called multiple times in the same request. A `select_related` variant that pre-fetches the typed object in a single JOIN query would be a further optimization if graph traversal volume warrants it.

---

### BaseModel Field Validation
----
RID: `req-grid-entity-validation`
Status: `Implemented`

Allows any `BaseModel` subclass (node or edge) to declare enhanced validation rules on top of Django's built-in field type coercion. The validation concerns **fields defined on the derived model** (e.g. `Concept.summary`, `Precept.statement`), not the BaseModel infrastructure fields (`entity_id`, `ENTITY_TYPE`, etc.), which BaseModel already guards internally.

#### `FIELD_VALIDATION_SCHEMA` — the single source of truth

`FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]]` is the explicit registry of validated fields. It has two responsibilities:

1. **Declare which fields are validated.** Any field not listed is completely ignored by `full_validate()`.
2. **Declare how each field is validated.** Each entry is a typed descriptor with a required `"validation"` key.

Two validation types are supported:

**`"jsonschema"`** — validate the field's value against a JSON Schema:

```python
FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]] = {
    "summary": {
        "validation": "jsonschema",
        "schema": {"type": "string", "minLength": 1, "maxLength": 5000},
    },
    "tags": {
        "validation": "jsonschema",
        "schema": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
    },
}
```

Schema authors control nullability via `{"type": ["string", "null"]}` or `anyOf`; no special-casing of `None` is performed by the framework.

**`"function"`** — validate the field via an instance method named `validate_<fieldname>(self) -> None`. The method reads `self.<fieldname>` directly and raises `django.core.exceptions.ValidationError` on failure:

```python
FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]] = {
    "tags": {"validation": "function"},
}

def validate_tags(self) -> None:
    if any(";" in t for t in self.tags):
        raise ValidationError({"tags": "Tags may not contain semicolons."})
```

Declaring `"validation": "function"` without a matching `validate_<fieldname>()` method is a configuration error (see Startup Invariants below).

#### Layer 2 — Whole-record hook

Override `validate(self) -> None` for cross-field or business-rule validation that spans multiple fields. The base implementation is a no-op. Raise `ValidationError` with a field-keyed dict for field errors, or a plain message for non-field (`__all__`) errors:

```python
class DateRangeNode(BaseModel):
    def validate(self) -> None:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValidationError({"start_date": ["Must be before end_date."]})
```

#### Startup invariants enforced by `__init_subclass__`

`BaseModel.__init_subclass__` checks the following at **class definition time** (i.e. at startup, before any request is served). Any violation raises `ImproperlyConfigured` immediately:

| Check | Error condition |
| --- | --- |
| Valid `"validation"` key | An entry in `FIELD_VALIDATION_SCHEMA` has a `"validation"` value other than `"jsonschema"` or `"function"` |
| Schema present for jsonschema entries | An entry with `"validation": "jsonschema"` is missing the `"schema"` key |
| Method present for function entries | An entry with `"validation": "function"` has no corresponding `validate_<field>()` method on the class |
| No undeclared validators | A `validate_<field>()` method exists but `field` is not listed in `FIELD_VALIDATION_SCHEMA` |
| Keys are real fields | A `FIELD_VALIDATION_SCHEMA` key does not correspond to a field declared on the derived model |

The last two checks enforce bidirectional consistency: `FIELD_VALIDATION_SCHEMA` and `validate_*` methods must always be in sync. There is no silent fallback.

#### Escape hatch — `@dangerously_ignore_validator`

A method named `validate_<something>` that is intentionally not yet wired into `FIELD_VALIDATION_SCHEMA` must be decorated with `@dangerously_ignore_validator`. This suppresses the "undeclared validator" startup check for that method, allowing authors to pre-stage validation code without fully activating it:

```python
class Concept(BaseModel):
    @dangerously_ignore_validator
    def validate_tags(self) -> None:
        # pre-staged but not yet in FIELD_VALIDATION_SCHEMA — suppresses startup error
        ...
```

`@dangerously_ignore_validator` is a one-line marker decorator defined in `tap_grid.models`. It sets a flag attribute on the method so `__init_subclass__` can skip it. The name is deliberately alarming — it signals that a validator exists but is not running, which is an unusual and potentially risky state.

#### Orchestration — `full_validate()`

`BaseModel.full_validate(self) -> None` runs all declared validators and collects every error before raising:

1. For each field in `FIELD_VALIDATION_SCHEMA`:
   - If `"validation": "jsonschema"`: call `jsonschema.validate(field_value, schema)`; collect any violation message keyed by field name.
   - If `"validation": "function"`: call `validate_<field>(self)`; merge any raised `ValidationError` into the error dict.
2. Call `validate(self)` (whole-record hook); merge its errors.
3. If any errors were collected, raise `ValidationError(collected_dict)`.

All errors are gathered before raising — callers receive the complete picture in a single exception, not just the first failure.

#### Integration with `save()`

`BaseModel.save()` calls `full_validate()` before entity auto-creation or any DB write. The escape hatch `skip_validation=True` bypasses it entirely (needed for data migrations, test fixtures, and admin bulk operations):

```python
concept.save()                      # validation runs
concept.save(skip_validation=True)  # validation skipped
```

#### Edge compatibility

`Edge` extends `BaseModel` and inherits the full validation mechanism. The existing edge property schema registry (`_edge_property_schema_registry`) continues to operate as a separate mechanism for `Edge.properties` and is unaffected.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-validation-1 | FIELD_VALIDATION_SCHEMA Declaration | Implemented | A BaseModel subclass may declare `FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, dict]]`; default is `{}`. Fields not listed are ignored by `full_validate()`. | |
| req-grid-entity-validation-2 | Typed Validation Entries | Implemented | Each entry in `FIELD_VALIDATION_SCHEMA` must have `"validation": "jsonschema"` or `"validation": "function"`. Any other value raises `ImproperlyConfigured` at class definition time. | |
| req-grid-entity-validation-3 | jsonschema Entry Requires Schema Key | Implemented | An entry with `"validation": "jsonschema"` that lacks a `"schema"` key raises `ImproperlyConfigured` at class definition time. | |
| req-grid-entity-validation-4 | function Entry Requires Method | Implemented | An entry with `"validation": "function"` that has no matching `validate_<field>()` method on the class raises `ImproperlyConfigured` at class definition time. | |
| req-grid-entity-validation-5 | Undeclared Validator Raises | Implemented | A `validate_<field>()` method (without `@dangerously_ignore_validator`) whose field is not in `FIELD_VALIDATION_SCHEMA` raises `ImproperlyConfigured` at class definition time. | |
| req-grid-entity-validation-6 | FIELD_VALIDATION_SCHEMA Keys Are Real Fields | Implemented | A `FIELD_VALIDATION_SCHEMA` key that does not match a field declared on the derived model raises `ImproperlyConfigured` at class definition time. | |
| req-grid-entity-validation-7 | JSON Schema Validation | Implemented | `full_validate()` runs `jsonschema.validate(field_value, schema)` for each `"jsonschema"` entry. Violations are collected keyed by field name. | |
| req-grid-entity-validation-8 | Function Validation | Implemented | `full_validate()` calls `validate_<field>(self)` for each `"function"` entry. Raised `ValidationError` messages are merged into the error dict. | |
| req-grid-entity-validation-9 | Whole-Record Hook | Implemented | `full_validate()` calls `self.validate()` after per-field checks. Base implementation is a no-op. Raised errors are merged into the collection. | |
| req-grid-entity-validation-10 | Error Collection | Implemented | `full_validate()` collects all errors from all sources before raising. The final `ValidationError` is in Django dict form `{field: [messages]}`. | |
| req-grid-entity-validation-11 | full_validate Standalone | Implemented | `full_validate()` can be called without saving. Returns normally if all checks pass; raises `ValidationError` if any fail. | |
| req-grid-entity-validation-12 | save() Integration | Implemented | `BaseModel.save()` calls `full_validate()` before any DB write or entity auto-creation. | |
| req-grid-entity-validation-13 | skip_validation Escape Hatch | Implemented | `save(skip_validation=True)` bypasses `full_validate()` entirely. | |
| req-grid-entity-validation-14 | @dangerously_ignore_validator Decorator | Implemented | A `validate_<field>()` method decorated with `@dangerously_ignore_validator` is excluded from startup invariant checks and never called by `full_validate()`. | |
| req-grid-entity-validation-15 | Applies to Edge | Implemented | `Edge` inherits the full validation mechanism. The existing edge property schema registry is unaffected. | |

#### Future

Consider supporting a combined entry type (e.g. `"validation": "jsonschema+function"`) for fields that need both structural schema validation and custom business-rule logic in a single field declaration.

Consider exposing `full_validate()` as a Ninja API endpoint so frontends can perform round-trip validation on partial data (e.g. as a user fills out a form field-by-field) without triggering a save.

---

### Service-Layer CRUD Schema
----
RID: `req-grid-entity-crud`
Status: `Implemented`

Every concrete `BaseModel` subclass must declare `FIELD_CRUD_SCHEMA` alongside `FIELD_VALIDATION_SCHEMA`. These are two separate schema systems that serve different purposes.

#### Implementation

**`FIELD_CRUD_SCHEMA`** (`ClassVar[dict[str, dict]]`) is the service-layer write surface. It declares which fields are writable via the TAP service layer (`create_node`, `replace_node`, `patch_node`) and provides plain JSON Schema for each field. The service layer synthesizes `SERVICE_SCHEMAS` from this at class definition time.

```python
FIELD_CRUD_SCHEMA: ClassVar[dict[str, Any]] = {
    "name": {"type": "string", "minLength": 1},
    "status": {"type": "string"},
    "count": {"type": ["integer", "null"]},
    "configuration": {"type": "object"},
}
```

**`FIELD_VALIDATION_SCHEMA`** (`ClassVar[dict[str, dict]]`) is the model-level validation surface. It wraps each validated field in a `{"validation": "jsonschema", "schema": {...}}` (or `"function"`) envelope and is enforced by `full_validate()` on every save. See `req-grid-entity-validation` for the full validation contract.

```python
FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
    "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
    "status": {"validation": "jsonschema", "schema": {"type": "string"}},
    "count": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
    "configuration": {"validation": "jsonschema", "schema": {"type": "object"}},
}
```

**Both are required.** Omitting `FIELD_CRUD_SCHEMA` raises `ImproperlyConfigured` at class definition time.

**`CREATE_REQUIRED`** (`ClassVar[list[str]]`) lists fields that must be present in a `create_node` payload. All entries must be keys in `FIELD_CRUD_SCHEMA`.

**`REPLACE_REQUIRED`** (`ClassVar[list[str]]`, optional) lists fields required for `replace_node`. If not declared, defaults to `CREATE_REQUIRED`.

**Nullable fields** in the Django model (`null=True`) must use nullable JSON Schema types in both schemas: `{"type": ["string", "null"]}` or `{"type": ["integer", "null"]}`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-crud-1 | FIELD_CRUD_SCHEMA Required | Implemented | Every concrete BaseModel subclass must declare `FIELD_CRUD_SCHEMA`. | Enforced at class definition time via `__init_subclass__` |
| req-grid-entity-crud-2 | SERVICE_SCHEMAS Synthesized | Implemented | `SERVICE_SCHEMAS` for create, replace, and patch verbs are synthesized from `FIELD_CRUD_SCHEMA` at class definition time. | |
| req-grid-entity-crud-3 | Dual Schema Requirement | Implemented | Both `FIELD_CRUD_SCHEMA` and `FIELD_VALIDATION_SCHEMA` must be declared. They serve different purposes and are not interchangeable. | |
| req-grid-entity-crud-4 | CREATE_REQUIRED Validated | Implemented | All entries in `CREATE_REQUIRED` must be keys in `FIELD_CRUD_SCHEMA`. | Enforced at class definition time |
| req-grid-entity-crud-5 | Nullable Types Consistent | Implemented | Fields using `null=True` on the Django model must use nullable JSON Schema types in both schemas. | |

---

### Known Model Constraints
----
RID: `req-grid-entity-constraints`
Status: `Implemented`

Documents known constraints and field name collisions that affect `BaseModel` subclass authoring.

#### Implementation

**django-simple-history field name collision:** The field name `instance_type` is reserved by django-simple-history's `HistoricalRecord` model. Declaring a Django field named `instance_type` on any `BaseModel` subclass causes a `TypeError` at runtime when the historical record attempts to save:

```
TypeError: HistoricalMyModel() got unexpected keyword arguments: 'instance_type'
```

This collision occurs because django-simple-history uses `instance_type` internally to reference the content type of the tracked model. Models that would naturally use this field name must choose an alternative (e.g. `ec2_type`, `node_type`, `endpoint_instance_type`).

The TAP plugin validation system's `runs` level detects this collision by exercising the full write pipeline including history recording.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-constraints-1 | instance_type Reserved | Implemented | `instance_type` must not be used as a Django field name on BaseModel subclasses due to django-simple-history collision. | |
| req-grid-entity-constraints-2 | Collision Detected By Validator | Implemented | The plugin validation system's `runs` level catches this collision via the full write pipeline. | |

#### Future

If additional field name collisions are discovered, document them here. Consider adding a startup check that validates field names against a known-reserved list.

---

### Entities Are Entities
----
RID: `req-grid-entity-ee`
Status: `Deprecated`

#### Status Details
This concept is intentionally shelved. It was a one-off idea rather than a thoroughly developed architectural requirement, and it introduces a major abstraction shift that is not justified by the current direction of the project.

#### Implementation
Do not implement this requirement as part of the current grid model work.

#### Development
The project is converging on a cleaner layered model:

| Layer | Role |
| --- | --- |
| Entity / Edge | Low-level graph primitives and concrete data instances |
| Graph | A coherent graph composed of those primitives |
| Dimensions | Higher-level scoping and organizational metadata applied across the graph |

Forcing entities themselves to be entities collapses abstraction layers in a way that may be possible, but is not desirable for the current design. If this idea is revisited later, it should be reintroduced with a fresh spec and a stronger architectural case.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-ee-1 | Concept Withdrawn | Deprecated | The `Entities Are Entities` concept is not part of the current implementation direction. | |
| req-grid-entity-ee-2 | Preserve Context Only | Deprecated | This spec is retained only as historical context, not as an active implementation target. | |

#### Future

---

### Edge-Directed Cascade Deletion
----
RID: `req-grid-entity-cascade`
Status: `Backlog`

When an entity is deleted, the graph may have opinions about what else should go. Today, deletion cascades are handled entirely by Django's `on_delete=CASCADE` on the FK between a typed model and its `Entity` spine row — which is correct for keeping the spine consistent, but knows nothing about the graph. Edge relationships can encode richer semantics: deleting a `Concept` that `DEPENDS_ON` another should perhaps propagate that deletion forward; deleting a `Precept` that `APPLIES_TO` many concepts probably should not.

This requirement is the foundation for making deletion a graph-aware, policy-driven operation rather than a raw relational cascade.

#### Future

Questions to resolve when this is picked up:

- **Where do cascade policies live?** Candidates: `OUTBOUND_EDGES` / `INBOUND_EDGES` entries on the model, a separate `CASCADE_POLICY` class variable, or a service-layer policy registry.
- **Directionality**: should deletion cascade along outbound edges (things this entity points to), inbound edges (things pointing at this entity), or both, depending on policy?
- **Cycles**: the graph may contain cycles; cascade logic must guard against infinite loops.
- **Transactionality**: multi-hop cascades should be atomic; partial deletes are worse than no delete.
- **Interaction with FLIP**: every deletion — including cascade-triggered ones — must be recorded as a provenance event. Cascade chains may need a shared batch ID so the audit trail shows the full causal chain.
- **Soft delete**: edge-directed cascade is a natural hook point for introducing soft-delete semantics (mark deleted rather than destroy rows), which would make the whole thing reversible.

---

### Tombstone State And Manager Surface
----
RID: `req-grid-entity-tombstone-managers`
Status: `Approved for Development`

Tombstone state has exactly one canonical home: `Entity.deleted_at`. Typed `BaseModel` subclasses do not carry a per-row tombstone flag; their default `LiveManager` joins through the FK to `Entity` and filters by `entity__deleted_at__isnull=True`. This means the spine is the single source of truth for whether an entity is live or tombstoned, and structural drift between the two surfaces is impossible — there is no second flag to fall out of sync.

What does differ between the two surfaces is the **default manager behavior**, and that asymmetry is intentional:

| Surface | Default `objects` returns | `all_objects` exists? |
| --- | --- | --- |
| `Entity` | Live AND tombstoned rows | No (default = all) |
| BaseModel subclass | Live rows only (via `LiveManager`) | Yes (returns all rows) |

The defaults match each surface's typical consumer. Spine queries are dominated by internal infrastructure (GRIFT identity checks, batch-scoped sweep, force-reimport, history, audit) that needs to see tombstoned rows by default; live-only filtering would require every internal call to opt back in. Typed-row queries are dominated by application code that wants live data by default; including tombstoned rows would silently leak deleted state into business logic.

The cost of this asymmetry is learnability: a reader who knows the BaseModel pattern (`objects = live`, `all_objects = both`) may assume Entity follows the same shape and reach for `Entity.all_objects` (which does not exist). Two mitigations apply: this requirement, and the uniform chainable filters defined below.

#### Implementation

Both surfaces expose two QuerySet methods so explicit-intent filtering uses the same vocabulary on the spine and on typed rows. The methods are chainable and compose with normal QuerySet operations:

```python
# Spine surface — default manager returns both; chainables narrow.
Entity.objects.live()              # live entities only
Entity.objects.tombstoned()        # tombstoned entities only

# Typed-row surface — `objects` is LiveManager (already live-filtered);
# `all_objects` is the unfiltered manager. Chainables apply to either.
Character.objects.live()           # no-op vs default (LiveManager already filters)
Character.all_objects.live()       # narrow back to live
Character.all_objects.tombstoned() # tombstoned characters only — canonical typed-row tombstone query
```

```python
Entity.objects.live().filter(entity_type="character")
Character.all_objects.tombstoned().filter(updated_at__lt=cutoff)
```

##### Typed-row gotcha: prefer `all_objects.tombstoned()` over `objects.tombstoned()`

`Character.objects.tombstoned()` looks like it should "return tombstoned characters," but it does not. `Character.objects` is `LiveManager`, whose `get_queryset()` already applies `.live()` (filter `entity__deleted_at__isnull=True`); the `.tombstoned()` chain on top adds the opposite predicate (filter `entity__deleted_at__isnull=False`); the two predicates AND together to never-true and the result is always empty. This is honest queryset composition — the chained filters compose, they don't replace each other — but the typo-shaped invitation is real.

**Rule:** for BaseModel-subclass tombstone queries, use `Model.all_objects.tombstoned()`. `Model.objects.tombstoned()` is structurally well-defined but always empty; it is not the canonical surface and should not appear in production call sites.

The spine surface does not have this gotcha because `Entity.objects` is not pre-filtered — `Entity.objects.tombstoned()` and `Entity.all_objects.tombstoned()` (which does not exist on Entity) would behave identically.

##### How the chainables are wired

The two methods are implemented on two QuerySet subclasses (`EntityQuerySet` and `BaseModelQuerySet`) because the filter expression differs:

- `EntityQuerySet.live()` filters `deleted_at__isnull=True` (the field is on this table).
- `BaseModelQuerySet.live()` filters `entity__deleted_at__isnull=True` (the field is on the related Entity via FK).

The existing `LiveManager` continues to apply `.live()` at construction time so the BaseModel subclass default is unchanged. Adding `.live()` / `.tombstoned()` is purely additive; no existing call site changes behavior.

#### Development

Two designs were considered for tightening this surface:

1. **Symmetrize the defaults** — add a `LiveEntityManager` to `Entity` so the spine's `objects` filters tombstones by default, matching typed rows. Rejected for v0: every existing `Entity.objects` call site would need to be audited to decide whether the intent was "any entity" (force-reimport, sweep, GRIFT identity check, history) or "live entity"; the wrong choice would silently change behavior. The current asymmetry is correct for the dominant consumer of each surface.
2. **Parameterize the existing managers** — let callers say `Entity.objects(include_tombstoned=False)` or similar. Rejected: not idiomatic Django and mixes "manager default" with "caller intent" in one surface. The two-manager pattern + chainable filter is the standard idiom.

The chosen approach (additive `.live()` / `.tombstoned()` methods) gives callers a uniform expression for explicit-intent filtering without changing any defaults or requiring a code audit.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-tombstone-managers-1 | Single Canonical Home | Approved for Development | `Entity.deleted_at` is the single source of truth for tombstone state; typed `BaseModel` rows carry no per-row tombstone flag and instead read the spine through the FK. | Drift is structurally impossible. |
| req-grid-entity-tombstone-managers-2 | Default Manager Asymmetry Documented | Approved for Development | `Entity.objects` returns both live and tombstoned rows by default; BaseModel subclass `objects` (via `LiveManager`) returns live rows only. Both defaults are intentional given each surface's typical consumer. | |
| req-grid-entity-tombstone-managers-3 | Chainable `.live()` And `.tombstoned()` | Approved for Development | Both `Entity` managers and BaseModel subclass managers expose `.live()` and `.tombstoned()` queryset methods. The two methods compose with normal QuerySet operations; BaseModel-subclass tombstone queries use the unfiltered manager surface, `Model.all_objects.tombstoned()`. | Implementation uses two QuerySet subclasses keyed by the appropriate filter expression. See the typed-row gotcha in Implementation. |
| req-grid-entity-tombstone-managers-4 | No Default Behavior Change | Approved for Development | Adding `.live()` / `.tombstoned()` does not alter the queryset any existing call site receives by default. The methods are additive opt-in filters. | |
| req-grid-entity-tombstone-managers-5 | LiveManager Uses `.live()` Internally | Approved for Development | `LiveManager.get_queryset()` applies `.live()` so the BaseModel-subclass default matches the chainable filter expression. | Single source of truth for the live filter. |

#### Future

If a future use case emerges where the spine surface's default of "include tombstoned" causes confusion or correctness drift (e.g. a new admin tool that lists entities and accidentally surfaces tombstones), the right next move is to either symmetrize the defaults (deferred Option A from this Development section) or introduce a typed `LiveEntityQuerySet` exit point exposed for that use case. Neither is needed in v0.

---

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
