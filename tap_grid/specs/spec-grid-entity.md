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
| req-grid-entity-cascade | [Edge-Directed Cascade Deletion](#edge-directed-cascade-deletion) | Backlog | The *mechanism* is now specified as `req-grid-service-delete-cascade` (declared containment, own evaluator, fail-closed). What remains backlogged here is the entity-side half: declaring containment on the model rather than in a collector's manifest |
| req-grid-entity-core-type-catalog | [First-Party Types In The Catalog](#first-party-types-in-the-catalog) | In Development | Core-app types have a catalog row with a name, a kind and an applied version, written for `req-grid-entity-model-version`. Their icons, their descriptions and the single writer run from boot are not built; pick those up when someone cares about the missing icons |
| req-grid-entity-tombstone-managers | [Tombstone State And Manager Surface](#tombstone-state-and-manager-surface) | Approved for Development | `Entity.deleted_at` is the single canonical home of tombstone state; manager defaults differ by surface; both surfaces expose uniform `.live()` / `.tombstoned()` chainable filters |
| req-grid-entity-batch-pointers | [Batch Pointers On The Spine](#batch-pointers-on-the-spine) | In Development | `last_changed_batch_id`, `last_observed_batch_id` and `last_observed_at` on `Entity`: which batch last changed the object, and which last saw it |
| req-grid-entity-event-time | [Event Time On The Spine](#event-time-on-the-spine) | In Development | `event_start`, `event_end` and `event_precision` on `Entity`, and the kind as the row's `time` dimension,, copied from the fields a model declares as its event time |
| req-grid-entity-collection-time | [Collection Time On The Spine](#collection-time-on-the-spine) | In Development | `collected_start` and `collected_end` on `Entity` for the latest observation, and the same pair on each batch event |
| req-grid-entity-model-version | [Model Versions And Upgrade Steps](#model-versions-and-upgrade-steps) | In Development | One authored version per node type and edge type, recorded on the type catalog and stated in GRIFT; an import upgrades older records through the type's steps and is refused at a declared break |
| req-grid-entity-spine-version | [Spine Version](#spine-version) | In Development | The spine's own authored version, separate from the tap release, the GRIFT format version and every type version; recorded on the grid and stated in GRIFT |
| req-grid-entity-spine-copies | [Spine Copies On Typed Rows](#spine-copies-on-typed-rows) | Proposed | `spine_deleted_at` and `spine_dimensions` on every typed row, kept in step with `Entity` by database triggers, recorded in history, with no policy yet |
| req-grid-entity-natural-key | [Assigned Ids, Declared Search](#assigned-ids-declared-search) | Proposed | `Entity.id` is always an assigned UUIDv7; every type declares how it is found (`NATURAL_KEY` or `KEYLESS`) and the search is generated; `Entity.natural_key` publishes each keyed row's declared identity as one readable value, derived on every save and read by no lookup |


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
| `entity_id` | `Entity.id` (renamed for serialization) | UUID, **always assigned** — UUIDv7 in practice. Never derived from content: see `req-grid-entity-natural-key` for why the former deterministic-identity exception was withdrawn. The stable identifier for this row and this observation lifetime. |
| `entity_type` | `Entity.entity_type` | Polymorphism discriminator. Immutable post-create. |
| `name` | `Entity.name` | Human-readable. Descriptive metadata, not a stable identifier (the `entity_id` is). |
| `natural_key` | `Entity.natural_key` | Text or `null`. The row's natural key, derived on every write (spine only): a single-field key's value verbatim (an ARN, a purl, a panel's slug), a multi-field key's field-coerced values joined in declared order (`corp\|fe80::1\|tcp\|443`), derived from the type's `NATURAL_KEY` on every write, for cross-type search. No type prefix — `entity_type` is beside it. `null` for a `KEYLESS` type or an unobserved constituting value. Output only — nothing finds, merges or refuses a row by it — and non-unique by design; pair a search with `entity_type`. See `req-grid-entity-natural-key`. |
| `dimensions` | `Entity.dimensions` | Scoping/partitioning JSON object. |
| `created_at` | audit timestamp | ISO 8601 UTC. |
| `updated_at` | audit timestamp | ISO 8601 UTC. |
| `deleted_at` | `Entity.deleted_at` | Tombstone timestamp or `null`. |
| `version` | `Entity.version` | Monotonic counter; increments on canonical mutation including tombstone. |
| `last_changed_batch_id` | `Entity.last_changed_batch_id` | UUID or `null`. The batch whose write last changed the row (`req-grid-entity-batch-pointers`). Derived on this grid; not accepted on import. |
| `last_observed_batch_id` | `Entity.last_observed_batch_id` | UUID or `null`. The latest batch that wrote or re-observed the row. Derived on this grid; not accepted on import. |
| `last_observed_at` | `Entity.last_observed_at` | ISO 8601 UTC or `null`. When that observation was recorded on this grid. Derived on this grid; not accepted on import. |
| `event_start` | `Entity.event_start` | ISO 8601 UTC or `null`. When the thing happened or began to hold, as its source states it (`req-grid-entity-event-time`). Derived on this grid; not accepted on import. |
| `event_end` | `Entity.event_end` | ISO 8601 UTC or `null`. When it stopped holding; exclusive; equal to `event_start` for a moment. Derived on this grid; not accepted on import. |
| `event_precision` | `Entity.event_precision` | `year`, `month`, `day`, `second` or `null`. Derived on this grid; not accepted on import. |
| `collected_start` | `Entity.collected_start` | ISO 8601 UTC or `null`. When the collector began reading the object, as stated by the latest batch to name it (`req-grid-entity-collection-time`). Written by the grid from the write operation's stated window; not accepted on import. |
| `collected_end` | `Entity.collected_end` | ISO 8601 UTC or `null`. When it finished; equal to `collected_start` for a read in one call. Not accepted on import. |
| `originating_grid_id` | `Entity.originating_grid_id` | Source grid identifier. **Retained** (decision 2026-09-15): the extended-grid case is real and this is its provenance field. Provenance only — never part of an identity or a correlation predicate. See Future. |

The `id` field renames to `entity_id` at the serialization boundary so
"id" is reserved for the inner identity within a polymorphic context
(e.g. when an envelope nests multiple identifier shapes).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-spine-surface-1 | Fields Enumerated | Proposed | The set of Entity-row fields is enumerated above; adding a new field requires updating this requirement. | |
| req-grid-entity-spine-surface-2 | Serialization Order Stable | Proposed | Serializers emit Entity fields in the order specified. Aids reading, diffing, and locating fields by position. | |
| req-grift-entity-spine-surface-3 | entity_id Is UUID, Not UUIDv7-Specific | Refactoring | The `entity_id` is a UUID and callers must not assume UUIDv7 layout. The second half — "deterministic-identity scenarios use UUIDv5" — is **superseded by `req-grid-entity-natural-key`**: ids are always assigned, and content-derived identity moves to `natural_key`. | RID reads `req-grift-…` rather than `req-grid-…`; a pre-existing typo, left alone so existing citations keep resolving. |
| req-grid-entity-spine-surface-4 | Higher-Level Specs Reference, Not Redefine | Proposed | Specs that emit Entity content (envelope, GRIFT, API) reference this requirement rather than restating the field list and order. | |

#### Future

- **~~Remove `originating_grid_id`~~ — reversed 2026-09-15.** The field
  was marked for removal on the grounds that cross-grid identity
  reconciliation had never been needed. The reconciliation design
  (`spec-grid-reconcile.md`) restores the demand: two grids
  independently observing one source mint different `entity_id`s and the
  same `natural_key`, and the origin is what tells a reader which grid
  recorded a row. Retained, with one constraint that was not previously
  stated — **origin is provenance, not identity**: two grids correlate on
  the natural key *despite* differing origins, so `originating_grid_id`
  never appears in a key document or an equality predicate. Federation
  itself remains future work.
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

Status: `In Development`

**What is built.** `req-grid-entity-model-version` rule 6 needs a catalog row and an applied version
for every type an export can carry, so the row itself now exists for each of core's types.
`tap_grid.model_version.register_core_types`, called from `tap_grid`'s `ready()`, walks the entity
model registry for the models core's apps define (sixteen node types; the `edge` model is left out,
its table being the spine's) and each core app's `edge_types` list with `tap_grid`'s own
(seventeen edge types), and writes `slug`, `name` (from `ENTITY_NAME`, else the slug), `kind`,
`track_history`, `plugin_name` (the owning AppConfig's dotted `name`) and, on first registration,
`model_version`. It is additive and never deletes a row.

**What is not built, and the trigger to pick it up.** Icons and descriptions: `ENTITY_ICON` and
`ENTITY_DESCRIPTION` are not copied to a core type's row (the `search` row keeps the icon it had),
so core types still render without icons in the graph view. That is cosmetic, and someone noticing
it is the trigger. The single writer run from boot's population phase is not built either: the write
is still made in `ready()`, by two callers (this function and the plugin loader), both through
`tap_grid.model_version.register_type`.

**Why the icons are missing.** The display-metadata lookups (`batch_resolve_icons`, the viewer
panel) read `EntityType.icon`, which is empty for a core type.

**Proposed shape for the rest** (measured against the as-built code, 2026-08-12; the first point is
built except for `description` and `icon`):

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
| req-grid-entity-internal-6 | Dual-Existence Pattern Consumer | Proposed | Plugin-declared capabilities follow the dual-existence pattern (see `tap_grid/specs/spec-grid-dual-existence.md`): grid-side `INTERNAL_ONLY = True`, sub-grid registry, single `register_<thing>(...)` entry point, an assigned id found on reload by the registry key (`req-grid-dual-existence-identity` is superseded by `req-grid-entity-natural-key`, 2026-09-17). | |

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
| req-grid-entity-validation-7 | JSON Schema Validation | Implemented | `full_validate()` runs `jsonschema.validate(field_value, schema)` for each `"jsonschema"` entry. Violations are collected keyed by field name. A `date` or `datetime` field value is checked as its ISO 8601 string, so a row loaded or saved with a date validates against the same string schema as the payload that wrote it. | |
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
    "enabled": {"type": "boolean"},
}
```

**`FIELD_VALIDATION_SCHEMA`** (`ClassVar[dict[str, dict]]`) is the model-level validation surface. It wraps each validated field in a `{"validation": "jsonschema", "schema": {...}}` (or `"function"`) envelope and is enforced by `full_validate()` on every save. See `req-grid-entity-validation` for the full validation contract.

```python
FIELD_VALIDATION_SCHEMA: ClassVar[dict[str, Any]] = {
    "name": {"validation": "jsonschema", "schema": {"type": "string", "minLength": 1}},
    "status": {"validation": "jsonschema", "schema": {"type": "string"}},
    "count": {"validation": "jsonschema", "schema": {"type": ["integer", "null"]}},
    "enabled": {"validation": "jsonschema", "schema": {"type": "boolean"}},
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

### Assigned Ids, Declared Search
----
RID: `req-grid-entity-natural-key`

Status: `Proposed`

`Entity.id` is **always an assigned identifier** — a UUIDv7 in practice, minted by the service layer at first sight, never derived from content. Identity of the *row* is the grid's to assign. How a row is *found again* from a source's facts is a separate, declared thing: every type declares its constituting properties (`NATURAL_KEY`) or declares that it observes no source object (`KEYLESS`, with a reason), and the search over those properties is generated from the declaration. `Entity.natural_key` **publishes** that declared identity on the spine as one readable value — derived from the declaration on every save, never authored, and read by no lookup (`-19`..`-23`).

#### Status Details
Proposed — `-1` waits on phase 3 (the `tap_cares` Collector exception) and `-7`/`-8` on their own consumers; the gate itself (`-2`, `-3`, `-9`, `-13`) is decided and landed, see *The gate* below. Phase 1 (merged 2026-09-16) landed the column, the per-type declarations on every core model, and the guard that no core type is undeclared. **Rewritten 2026-09-17** after two premise checks. The column had been specified as a UUIDv8 over SHA-256 of a canonical key document under a literal namespace; that hashing is **withdrawn** (see Development) and the column becomes text. The resolution contract — mint on zero, return on one, raise on more than one — is kept, but moves to *The gate* below: it is needed at the moment a retirement can be followed by a return, which is reconcile authority ON (`req-grid-reconcile-verb`), and collectors must have something to emit before they stop deriving ids. Phase 2 ("Cascade First") delivers the placeholder, the generated search, and cascade; nothing in it reads or writes `natural_key`. **Published 2026-11-11** (`-19`..`-23`): the named consumer arrived — cross-type search by a source's own global identifier (aws_core's ARNs, aws-core-tap#224 and the ARN-as-key ruling) — so the column is now filled, by derivation, for every keyed type at once. It stays output only, and the within-dimension uniqueness constraint under *Future* is deferred by ruling (below).

#### Implementation

**Why ids are never derived.** A content-derived id conflates identity with lifetime, and the conflation has a dead end. Collect repository R and run 42; lose visibility to R; retirement cascades to run 42; regain visibility while run 42 remains available at the source. A derived id for run 42 still addresses a terminal tombstone (`req-grid-reconcile-observation-lifetime-3`) — and neither patching that id nor re-minting it is legal. No deletion and no identifier reuse are required to reach that state: a permission gap and a retention window suffice, and the mass case — a credential narrows, then widens — refuses every returning id on every run thereafter. A pure-function id and a terminal tombstone cannot both hold; the tombstone stays terminal, so the id is assigned and the row is found by lookup. A second, independent reason: a pure-function id cannot represent two perspective-local rows for one source object, which perspectives will need.

**Two declarations, one search, one reserved column.**

| | `Entity.id` | `NATURAL_KEY` (declaration) | `Entity.natural_key` (column) |
| --- | --- | --- | --- |
| Produced by | assigned by the service layer | declared on the model | derived from the declaration on every save (`-19`) |
| Identifies | this row and this observation lifetime | how to find the row for a source object | the source object, readably, across types |
| Unique? | yes, primary key | **no** — several live rows may share declared values once perspectives exist | **no**, and never constrained (`-22`) |
| Who points at it | every edge, FK, history row, export, GRIFT reference | the generated search and the patch guard | nothing — output only (`-21`) |
| Used for | addressing | `find_existing(**properties)` | cross-type search by equality or prefix, paired with `entity_type` |

**The declaration.** `NATURAL_KEY: ClassVar[tuple[str, ...] | Keyless | None]` on every model. A tuple names the constituting properties — each a column, or, where the source's identity lives inside a JSON document, a dotted path into a `JSONField` (`"location.route"`, `-14`..`-18`; the payload, search, index and lock all read a path through one parser, compare it typed, and treat a missing key and a JSON `null` as the same unobserved hole while `""` stays searchable); `KEYLESS` with a `NATURAL_KEY_REASON` says the type observes no source object (activity and registration types — a batch, a job, a schedule fire — record something *we* did); `None` means *undeclared* and is a guard failure, never a silent skip. Three states, never two: an undeclared type must never be treated as keyless.

**Constituting properties are the source's stable identifiers wherever one exists.** A repository keyed on its source-assigned numeric id survives rename and transfer as one row with a history of names. A name is constitutive only where the source offers nothing better (a git ref, a secret, a required-check context) — and there a rename is honestly a new object, which is what the source itself says a branch rename is. A dimension value never enters a declaration (`tap#458`, ruled 2026-09-17): the search is dimension-invariant, and a locator that is genuinely constitutive is a property of the model, not a dimension.

**The search is generated, and it ignores dimensions.** `BaseModel.find_existing(**properties)` is generated from the declaration: a composite filter on the typed table over the declared fields, among live rows only. Zero matches returns nothing; exactly one returns the row; more than one raises — never a silent selection. A composite index over the declared fields is generated from the same declaration, one migration per keyed type, so the search is index-backed by construction. No dimension participates: dimension values vary by *collection path*, not only by observer — an account node minted once per repository carries whichever repository was walked last, so a dimension-*equality* lookup would fail to find its own previous write, and a dimension-*containment* lookup would match rows it should not. That is a sequential defect requiring no concurrency at all. When perspectives exist, the search gains an identity-scope argument and the multiple-match case becomes the ordinary multi-perspective case; until then, more than one live row for one set of declared values is a defect and is surfaced as one. `KEYLESS` types have no search. **No write path calls the search until the gate.**

**The published column.** `Entity.natural_key` is text, nullable and non-unique. It is on the spine surface (`SPINE_FIELD_NAMES`, since the corpus decoupling in #487/#490), so the Gryphon envelope carries it on every row. It holds each keyed row's **natural key in the grid's standard form** (`arn:aws:iam::123456789012:role/x`, `corp|fe80::1|tcp|443`, `overview`), searchable across types by equality or prefix. It lives **on the spine only** — no model table carries a copy (ruled 2026-11-11 by George, Q34, after tenable and anchore reviewed it; Issue# 1178 - tap) — and no plugin ships a migration for it.

*Written on every write (`-19`).* The grid derives it from the type's declared columns and never takes it from a caller, the pattern `Entity.name` already follows (`req-grid-node-display`): `BaseModel.save` derives it on create and re-derives it on every update, in the same statement as the name; the service layer's pre-specified-id create derives it when it pre-creates the spine row; the guarded querysets re-derive after an `update()` that touches a constituting column (naming the rows before the write, since the filter may match on the changed column), and after `bulk_update` and `bulk_create`. The GRIFT importer writes through the service layer, so an imported node gets it on create and on every re-import. A `KEYLESS` row's key is `null`. A collector never supplies it: the GRIFT envelope has no field for it (`-7`).

*Format (`-19`), ruled 2026-11-11 by George.* One function, `tap_grid.natural_key.compose_natural_key`, makes every key. Values are **field-coerced first** — each column entry through its model field's `to_python` — so `443` and `"443"` on an integer column, or two spellings of one IPv6 address on an address column, give one key; a value the field cannot coerce stays as given, and the write's own validation refuses it. A **single-field** key is its value verbatim — a type keyed on its ARN stores the ARN, bare, unescaped. A **multi-field** key joins its values **in declared order** with `KEY_SEPARATOR` (`|`), escaping exactly two characters, the escape and the separator (`%` → `%25`, `|` → `%7C`), so an IPv6 address or a path stays readable (`corp|fe80::1|tcp|443`) and the join splits back exactly (`split_key`). There is **no type prefix** (`entity_type` is on the row) and **no per-type format declaration** (the representation is core's).

*Stringification, pinned (`-19`).* Strings verbatim; `true`/`false`; integers canonical, and an integral float as its integer (`1.0` is `1`); a `Decimal` normalised, never in exponent form (`1.50` is `1.5`, `1E+2` is `100`); a UUID lower-case hyphenated; a datetime as ISO-8601 in UTC (`2026-11-11T05:00:00+00:00`; a naive one is read as UTC); a date as ISO-8601; an IP address in `GenericIPAddressField.to_python`'s canonical form (by coercion). `""` is a value and a hole is not: `a|` (the second value empty) is a key, while a `null` second value makes the whole key `null` — never a partial key. A **JSON entry** — a path into a JSON field, or a whole JSON column — renders as compact sorted JSON (non-ASCII as itself, never `\u`-escaped), keeping its JSON type in the string: `123` is `123` and `"123"` is `"123"`. The typed search treats them as two identities (`-15`), and so do the spine key and the lock key built from it; a string under a JSON path therefore carries its quotes.

*The lock key (`-13`).* The identity lock key is unchanged by this work: `<entity_type>` + `\x1f` + the canonical JSON of the constituting values. It is a separate string from the stored key on purpose. A lock needs only to be a stable function of the identity values, and keeping its format means an old and a new importer still serialise on the same lock during a rolling deploy, so they can't both create a row.

*Output only (`-21`).* Nothing finds, merges or refuses a row by the spine key. Resolution is the typed-table search over the declared columns (`-9`, `-12`), unchanged; the spine key is written after it, from the row. This is the spec's own rule, *the glue is never the identity*, applied to the one column that would most tempt a shortcut. **Scope:** the spine finds a node *keyed by* a value — whose declared identity is that value — not a node that merely mentions the value in some field (an ARN in a policy document, an address in a list); that is a search over the type's fields.

*Indexes and no constraint (`-22`), ruled 2026-11-11 by George.* Duplicate keys are allowed, across types and within one: a uniqueness constraint would turn a duplicate into a refused write, so whoever landed a value first — another plugin, a stale row, a hostile import — could block a type's real updates; a duplicate costs a search one extra row, which `entity_type` tells apart. **No plain btree indexes the full value**: a btree index row over ~2700 bytes is an error on insert, and a composed key can be longer (anchore's reach 2300+ characters, more in bytes), so such an index would fail a batch. Instead a **hash index** serves equality (no size limit; it compares the full value), and a **btree over `left(natural_key, 600)` with `text_pattern_ops`** serves prefix search — 600 characters stay under the row limit even at four bytes each. Neither index is partial, so both cover tombstoned rows.

*Searching (`-24`).* `tap_grid.spine_natural_key.find_by_spine_key` builds the query the indexes need. `equals=` compares the full value (the hash index). `prefix=` filters twice: `left(natural_key, 600) LIKE '<first 600 characters>%'` — the expression the prefix index covers — and `natural_key LIKE '<prefix>%'`, the recheck that keeps a prefix longer than 600 exact; both patterns escape `%` and `_`. `entity_type=` narrows to one type; without it the search runs across types. For the leading values of a multi-field key, `tap_grid.natural_key.natural_key_prefix` composes them exactly as the key does and **ends with the separator** — `corp|10.0.1.5|` matches `corp|10.0.1.5|tcp|443` and never `corp|10.0.1.50|…`.

*Tombstones (`-19`, `-22`).* Retirement never touches the key: a tombstoned entity keeps the natural key it had, the indexes cover it, and `find_by_spine_key` returns it unless the caller narrows to live rows.

*Catch-up, drift and recipes (`-23`, `-25`).* A write that changes constituting values without a save or a guarded queryset leaves the key stale; so does a change to a type's `NATURAL_KEY` tuple, or to the composition itself. `tap_grid.spine_natural_key` covers each:
- **the backfill** — migration `tap_grid/0010` runs `sync()` once over every registered type, core and plugin; a type whose table does not exist yet is skipped;
- **a plugin data migration that rewrites key values** — it calls `resync_natural_keys(<entity types>)` afterwards, in a `RunPython` step (the companion to `-8`);
- **a changed recipe** — `sync()` records each type's **fingerprint** (a hash of its slug, its `NATURAL_KEY` tuple and the composition version) in `NaturalKeyRecipe` once its rows are in step; `manage.py sync_spine_natural_keys --changed`, run at every deploy, re-derives each type whose fingerprint differs or was never recorded (including any the backfill skipped);
- **anything else** — `manage.py sync_spine_natural_keys --check` samples each type's rows, compares the stored key with a fresh composition, lists stale recipes, and fails if it finds either.

**The gate — collectors address rows by batch-local refs (ruled 2026-09-17, shape A; landed 2026-09-18; Issue# 571 - tap).** The question the gate asked was how a collector names a row once ids are assigned rather than derived. Two shapes were considered:

- *Refs — chosen.* A collector batch names its nodes with batch-local refs instead of ids (`entity_id` XOR `ref` on the envelope, `from_ref`/`to_ref` on edge endpoints); the importer resolves every ref inside the batch's transaction through `resolve_identity` — the type's declared search among live rows, under an advisory lock keyed by the declaration — assigning a fresh UUIDv7 on none, returning the row on one, and failing the whole batch on more than one; the batch's edges are wired through the `ref → id` map, which comes back on the import result and reaches no record.
- *The supplied id as a handle — struck.* A collector keeps computing what it computes today and the importer remaps a tombstone-only match to a fresh id, storing the handle in `natural_key`. Struck because it makes the supplied id a second identity with its own uniqueness scope — Kubernetes' name beside its UID — which is a natural key by another spelling, and it would quietly make the derived id load-bearing again.

Prior art converged on refs for exactly this problem: ServiceNow's identification engine takes payloads with no record ids and expresses relations by payload index; Salesforce Composite `referenceId`, JSON:API atomic-operations `lid`, and AWS/Stripe client idempotency tokens all let a batch refer to what it just created without choosing its identity. Systems that let the client supply the identity either resurrect the deleted record (CouchDB, DataHub) — rejected here, tombstones are terminal — or grow a second identity (Kubernetes).

*What landed.* Slice 1 (Issue# 593 - tap): the envelope — the exclusive-or lives in the document schema, refs resolve in one pass on a copy of the document before any other preflight read, a blank, reused, unknown or misplaced ref fails the file (`req-grid-import-grift-identity-3`). Slice 2 (Issue# 594 - tap): the verb — `resolve_identity` runs inside each batch's transaction; the constituting values are read against the declaration once and the same values key `pg_advisory_xact_lock`, so two writers resolving one source object serialise and the second finds the first's row; a `KEYLESS` type is always assigned and an undeclared type is refused (`-9`, `-13`). The same batch may not describe one source object twice — two refs with one identity key, a ref beside an explicitly addressed node with the same values, or a ref resolving to a row the batch also addresses by id or names as a removal target — each refused with nothing written (Issue# 602, Issue# 606). Slice 3 (Issue# 595 - tap): this record, and the probe below pinned as a regression test.

*Id-addressed nodes keep today's behaviour, and that behaviour is the probe that made the gate necessary.* A supplied id that matches a tombstone routes to a replace and is refused (`entity_tombstoned`); the batch fails with nothing written and the tombstone is untouched. A collector that kept deriving the same id for a retired thing would fail every batch from then on — `tap_grid/tests/test_grift_identity.py::TestTheProbe` pins both the refusal and its resolution by ref. The ratchet in `test_find_existing.py` names `resolve_identity` as the one write-path caller of the generated search.

**The recorded exception.** The `tap_cares` `Collector` node's id is derived today — `uuid5(NAMESPACE_COLLECTOR, "scope:key")` at `tap_cares/registry.py` — and is the **one named, temporary exception** to this requirement. Five plugin schedule bundles (git_serious, zizmor, fedramp_20x_ksi, samsite ×2) hardcode that id as a `SCHEDULED_TARGET` target and zizmor re-derives it at runtime, so retiring it is a plugin change and lands in phase 3 with them. Until then `req-tap-cares-collector-model-10` describes what the code does, marked as superseded. An exception on the record beats an exception nobody wrote down.

**Cost, stated honestly.** One column-type migration (`uuid → text`); one generated index migration per keyed type; `SPINE_FIELD_NAMES` unchanged; the hash derivation and its backfill command deleted. Deterministic ids provided *implicit* uniqueness — same facts, same id, same row. Assigned ids plus lookup lose it, which is why the gate's transaction takes a lock.

#### Development
The first design draft kept a `derived` identity kind for content and immutable events, on the reasoning that a commit *is* its oid and two collectors should agree without coordination. The second half of that reasoning survives — two collectors that observe the same facts find the same row — but attaching it to the primary key produced the dead end above and a flat internal contradiction (ids "never derived" against "for derived types the natural key equals the id"), and it made perspective-local rows impossible for exactly those types.

The second draft moved the hash one column over: a UUIDv8 over SHA-256 of a canonical key document, with a literal namespace, a canon byte layout and a canonicalization domain. **Withdrawn 2026-09-17.** Tombstoning forced *lookup-by-facts*, not *hash-of-facts*; the hash was inertia from the shape of the old ids. The two-key precedents this requirement cites — Kimball's surrogate beside the natural key, FHIR's logical id beside its business identifier, ServiceNow's `sys_id` beside identification rules, Atlas's `guid` beside `qualifiedName`, Kubernetes' `uid` beside `(namespace, name)` — all keep the second key as plain fields or a composed string. Systems that hash contributing properties (STIX 2.1, OpenCTI) hash them into the *id*, which is the choice rejected above. A hashed, non-unique, non-id key had no precedent; the nearest relative is Data Vault's hashdiff, which is change detection. The narrow lesson from all of them is one rule — **the glue is never the identity**: nothing keys on the search but lookup.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-natural-key-1 | Ids are always assigned | Proposed | No service or collector path derives an `Entity.id` from content; a test asserts no deterministic-id helper is used to mint an entity id. | Supersedes the UUIDv5 half of `req-grift-entity-spine-surface-3`. The `tap_cares` Collector is the recorded exception until phase 3. |
| req-grid-entity-natural-key-2 | Search is declared, never supplied | Implemented | How a row is found is the model's declaration; a collector cannot supply a natural key, a search, or an override. Enforced by omission on the envelope (the GRIFT entity envelope declares no key field and is `additionalProperties: false`) and by construction in the verb, which reads only the type's declaration. | `tap_grid/tests/test_natural_key.py::TestGriftImportRefusesASuppliedKey`, `tap_grid/tests/test_grift_identity.py::TestResolution::test_an_undeclared_type_is_refused`, `tap_grid/tests/test_find_existing.py::test_exactly_the_declared_properties`. Gate slice 3, Issue# 595 - tap. |
| req-grid-entity-natural-key-3 | Not unique | Implemented | Two live rows of one type may share declared values when their dimensions differ; no constraint prevents it. Two live `panel` rows sharing one slug are created through the service layer without complaint; the search then refuses to choose between them. | The correlation property; the constraint arrives with perspectives. `tap_grid/tests/test_find_existing.py::test_two_live_matches_raise_naming_both`, `tap_grid/tests/test_grift_identity.py::TestResolution::test_ambiguity_fails_the_whole_batch_with_one_flaw` (builds the pair). Gate slice 3, Issue# 595 - tap. |
| req-grid-entity-natural-key-4 | Type is in the document | Deprecated | Withdrawn 2026-09-17 with the hashed key document; the search runs on the typed table, so the type is implicit. | |
| req-grid-entity-natural-key-5 | Keyless says why; undeclared fails | Implemented | Activity and registration types declare `KEYLESS` with a `NATURAL_KEY_REASON`; an undeclared core type fails `test_no_core_type_is_undeclared`. Undeclared is never treated as keyless. | `tap_grid/tests/test_natural_key.py`. |
| req-grid-entity-natural-key-6 | Backfill reports collisions | Deprecated | Withdrawn 2026-09-17 with the backfill command; the collision question ("two live rows sharing declared values") belongs to the gate, answered by `find_existing` over a dev grid. | |
| req-grid-entity-natural-key-7 | Read-only on the surfaces | Proposed | `natural_key` appears on the export/Gryphon surface (`SPINE_FIELD_NAMES`) carrying the published value (`null` for a keyless or unobserved row); the GRIFT import envelope is unchanged and a test asserts a supplied `natural_key` is rejected — the value is derived on the receiving grid, never carried in. | Corrected 2026-09-17: the column is on the surface, not excluded. Revised 2026-11-11: it carries values now (`-19`). `tap_grid/tests/test_natural_key.py::TestGriftImportRefusesASuppliedKey`. |
| req-grid-entity-natural-key-8 | A declaration change is a migration | Proposed | Changing a type's `NATURAL_KEY` tuple lands as a migration (the generated index changes with it); no separate version field exists. | |
| req-grid-entity-natural-key-9 | Resolution is deterministic | Implemented | `resolve_identity` assigns on zero matches (the caller's provisional id, else a fresh UUIDv7), returns the row's id on exactly one, and raises `AmbiguousIdentity` on more than one — never silently selecting a row. A `KEYLESS` type is always assigned; an undeclared type is refused (undeclared is never keyless, `-5`). | `tap_grid/services/__init__.py::resolve_identity`; `tap_grid/tests/test_grift_identity.py::TestTheVerb`, `::TestResolution::test_reimporting_a_ref_bundle_finds_the_same_rows`, `::test_a_tombstoned_row_is_not_found_and_a_new_id_is_assigned`, `::test_an_undeclared_type_is_refused`. Issue# 594 - tap (gate slice 2). |
| req-grid-entity-natural-key-10 | Search ignores dimensions | Implemented | `find_existing` matches the declared fields among live rows only; no dimension participates. A node whose dimensions differ between two runs of one collector still finds its existing row. | The account-minted-per-repository case. `tap_grid/tests/test_find_existing.py::TestFindExisting::test_dimensions_do_not_participate`, `::test_tombstoned_row_is_not_found`. |
| req-grid-entity-natural-key-11 | Only the derived write touches the column | Implemented | `Entity.natural_key` is text; no code path outside the model that declares and derives it, the service create path that pre-creates a spine row, the catch-up sync and its command, migrations and the spine field inventory references it; the sentinel module (`tap_grid/natural_key.py`, home of the search and the lock) never does; its help text says the value is derived, never authored, and output only. | Rewritten 2026-11-11 from "Placeholder column is inert" (`-19`). `tap_grid/tests/test_natural_key.py::TestSpineColumn` (field shape, help text, the hash and prefix indexes, and a scan of every app tree for the column name); migrations `0004_entity_natural_key_placeholder`, `0008_entity_natural_key_published`. |
| req-grid-entity-natural-key-12 | Search generated from the declaration | Implemented | Every keyed type has `find_existing` and an index over its declared fields (asserted by introspection); a `KEYLESS` type cannot be searched (`find_existing` raises `TypeError`, it is not absent) and gets no index; on a fixture with one, none and two live rows sharing declared values it returns the row, nothing, and raises. | `BaseModel.find_existing` and `install_natural_key_indexes()` (`tap_grid/models.py`, wired from `TapCoreConfig.ready()`); `tap_grid/tests/test_find_existing.py` (search contract, index introspection, and a scan asserting no write path calls it yet); migration `tap_web/0004_natural_key_search_index`. |
| req-grid-entity-natural-key-13 | Resolution fails closed | Implemented | Ambiguity fails the whole batch with nothing written; the detail (type, ref, every candidate id) is the import's `identity_ambiguous` issue and the one application-class `Flaw` (`invariant_id=identity_ambiguous`, `flaw_class=app`) emitted per failed batch, since the import `Batch` row itself rolls back with the batch. Resolution runs inside the batch transaction under `pg_advisory_xact_lock` keyed by the declaration (`identity_lock_key`, derived from the type and the constituting values, never authored twice), so two writers resolving one source object serialise and the second finds the first's row. The verb refuses to run outside a transaction. Within one batch, two refs — or a ref and an explicitly addressed node — that describe one source object (the same identity key, whether a row exists yet or not) fail the batch as `duplicate_entity_id`: resolution runs before the batch writes, so the search alone cannot see the first of the pair, and the key (returned on `IdentityResolution.key`) can. A found row that the batch also addresses by explicit id, or names as a removal target, is refused the same way (`duplicate_entity_id` / `entity_id_in_upsert_and_removal`, Issue# 606 - tap): preflight's checks saw the provisional id, so they are re-applied to the resolved one. | `tap_grid/grift/importer.py::_resolve_ref_identities`; `tap_grid/natural_key.py::identity_lock_key`; `tap_grid/tests/test_grift_identity.py::TestResolution::test_ambiguity_fails_the_whole_batch_with_one_flaw`, `::test_two_refs_describing_one_object_on_an_empty_grid_fail_the_batch` (Issue# 602 - tap), `::TestTwoWriters` (two connections), `::TestOutsideATransaction`. Issue# 594 - tap. The batch row rolling back is why the detail rides the issue: the collector's run records import failures on its own lifecycle `Batch`. A batch takes all its node identity locks up front, sorted by key, so two batches resolving the same refs in opposite orders never deadlock (Issue# 943 - tap); `tap_grid/tests/test_grift_lock_order.py::TestOppositeOrders`. |
| req-grid-entity-natural-key-14 | An entry may name a path into a JSON field | Implemented | A `NATURAL_KEY` entry is a concrete column name, or a dotted path whose first segment is a concrete `JSONField` and whose remaining segments are object keys (`"location.route"`, `"location.workflow.id"`). A Django field name cannot contain `.`, so an entry with one is unambiguously a path. One parser (`tap_grid.natural_key.split_path`) is the grammar for every consumer — payload extraction, the ORM search term, the index expression and the lock key — so the search, the index and the lock read one declaration (`-12`). An empty segment, and an all-digit key segment (Django's key transform reads it as an array index, so the search would look somewhere the extraction does not), are refused. `find_existing` takes the dotted name as its keyword (`**{"location.route": value}`). | `tap_grid/natural_key.py::split_path`, `::constituting_properties`, `::search`; `tap_grid/tests/test_natural_key_json_path.py::TestGrammar`, `::TestExtraction`, `::TestTheGeneratedSearch`, `::TestResolvedThroughTheImporter::test_reimport_finds_the_same_row_and_a_different_path_value_makes_a_new_one`. Issue# 874 - tap. No core type declares a path (`tap_grid/tests/test_natural_key.py::TestEveryCoreTypeHasDeclared::test_no_core_type_declares_a_json_path`); the first consumer is `zizmor__finding`. |
| req-grid-entity-natural-key-15 | A JSON path is compared typed | Implemented | JSON scalars keep their type end to end: the extracted value is not coerced, the search compares `jsonb` (`123` does not match `"123"`, `true` does not match `1`), the index is over the same `jsonb` expression (never a text cast), and the lock key serialises the type (an integral float and the integer are one identity because `jsonb` numbers compare by value — recursively, since a leaf may be an object or array whose members are compared the same way). The declaration carries no type: the payload's own JSON type is the identity's type, so a source that emits `123` in one run and `"123"` in another is two objects — surfaced as a duplicate, not silently coerced into one. | `tap_grid/natural_key.py::_key_transform`, `::identity_lock_key`; `tap_grid/tests/test_natural_key_json_path.py::TestTheGeneratedSearch::test_typed_equality_a_number_is_not_its_string`, `::TestLockKey`, `::TestTheIndexAnswersTheSearch::test_the_index_is_typed_jsonb_not_text`. Issue# 874 - tap. |
| req-grid-entity-natural-key-16 | Absent, null and empty map onto the grid's convention | Implemented | For a JSON path, a missing key, an explicit JSON `null`, and a missing or non-object parent are all the grid's *unobserved* marker (`None`): `find_existing` answers "not found" without a query and the lock key is `None`, exactly as for a null column. `""` is *observed-empty* and is searched like any value (Issue# 866 - tap) — and, so the lock and the search agree, locked: `identity_lock_key` treats only `None` as a hole. A stored `null` or absent key is never matched by `""`. | `tap_grid/natural_key.py::_extract`, `::identity_lock_key`; `tap_grid/tests/test_natural_key_json_path.py::TestExtraction::test_missing_key_json_null_and_a_non_object_parent_are_all_the_same_hole`, `::TestLockKey::test_only_none_is_a_hole_and_empty_string_is_locked_like_it_is_searched`, `::TestTheGeneratedSearch::test_empty_string_is_searched_and_finds_its_own_row`, `::TestResolvedThroughTheImporter::test_an_empty_path_value_resolves_to_its_own_row_on_reimport`; `tap_grid/tests/test_grift_identity.py::test_the_lock_key_is_a_function_of_the_declaration`. Issue# 874 - tap. |
| req-grid-entity-natural-key-17 | A path that points nowhere is a guard failure | Implemented | A path entry's root must be a concrete `JSONField`; when the model's `FIELD_VALIDATION_SCHEMA` gives that field a JSON Schema with `properties`, each key must be one the schema names, level by level (a level whose schema says nothing is not a failure). `declaration_problems` is the one check: the core guard runs all of it over every core type, and the index install runs the structural part (unknown root, non-JSON root, malformed path) for every registered type at startup, raising `ImproperlyConfigured` naming the entry — a plugin gets a loud boot error rather than an index that was never built. A column-only declaration is not policed at startup any harder than before. | `tap_grid/natural_key.py::declaration_problems`; `tap_grid/tests/test_natural_key.py::TestEveryCoreTypeHasDeclared::test_keyed_properties_exist_on_the_model`; `tap_grid/tests/test_natural_key_json_path.py::TestTheGuard`. Issue# 874 - tap. |
| req-grid-entity-natural-key-18 | A path declaration is indexed by expression | Implemented | A declaration containing a path generates a composite *expression* index named `nk_<table>` (columns as `F(...)`, paths as `KeyTransform` chains — `Index(fields=...)` takes columns only) from the same expressions the search filters on, so PostgreSQL matches one to the other; the plan for the generated search uses the index. It is registered where the migration autodetector reads it and serialises into a reviewable `AddIndex`; changing a declared path is a `RemoveIndex` + `AddIndex` (`-8`). A column-only declaration keeps its `fields=` index byte for byte, so no existing type's migration moves. | `tap_grid/models.py::_install_natural_key_index`; `tap_grid/tests/test_natural_key_json_path.py::TestTheIndexAnswersTheSearch::test_postgres_plans_the_search_on_the_generated_index`, `::TestIndexAndMigration`. Issue# 874 - tap. A plugin adopting a path over rows already written needs its own backfill or invalidation: the declaration is a migration, the data is not. |
| req-grid-entity-natural-key-19 | The spine stores the natural key, derived on every write | Proposed | `Entity.natural_key` is written on every write of a keyed row and never taken from a caller: `BaseModel.save` (create and update), the service layer's pre-specified-id create, the GRIFT importer (through the service layer), and the guarded querysets (`update()` touching a constituting column, `bulk_update` and `bulk_create` re-derive for the rows they wrote). It is `compose_natural_key` over field-coerced values: a single-field key verbatim; a multi-field key joined in declared order with `\|`, escaping only `%` → `%25` and `\|` → `%7C`, splitting back exactly. Pinned stringification: strings verbatim; `true`/`false`; integers canonical; `Decimal` normalised, no exponent; UUID lower-case hyphenated; datetime ISO-8601 UTC; date ISO-8601; IP in `GenericIPAddressField.to_python`'s form; a JSON entry as compact sorted JSON, keeping its type (`123` vs `"123"`). `""` is a value (`a\|`), a hole makes the key `null`. No type prefix; no per-type format; no per-model column. A `KEYLESS` type's key is `null`; a tombstone keeps its key. The identity lock key keeps its existing format (`-13`), so a rolling deploy cannot split one object across two locks. | Ruled 2026-11-11 by George (spine only, Q34; `\|` final). Issue# 1178 - tap. `tap_grid/natural_key.py::compose_natural_key`, `::row_natural_key`, `::split_key`; `BaseModel.derive_natural_key`, `BaseModelQuerySet`; `tap_grid/tests/test_spine_natural_key.py::TestSingleFieldKeys`, `::TestStringificationIsPinned`, `::TestMultiFieldKeys`, `::TestTheWritePaths` (create, patch, pre-specified id, supplied key, keyless, queryset update, bulk update, tombstone, and stored == derived for every keyed live row), `::TestThroughTheImporter`. |
| req-grid-entity-natural-key-20 | A format composes the whole declaration | Deprecated | Withdrawn 2026-11-11 before it shipped: a per-type `NATURAL_KEY_FORMAT` was drafted, and George ruled the representation core's, the same for every type. No model declares a format. | `tap_grid/tests/test_spine_natural_key.py::TestMultiFieldKeys::test_there_is_no_per_model_column_or_format`. Issue# 1178 - tap. |
| req-grid-entity-natural-key-21 | The spine key is output only | Proposed | No lookup, merge or refusal reads `Entity.natural_key`. `resolve_identity`, `find_existing` and the generated search never name the column, and a wrong spine key does not change which row resolution finds. The spine finds nodes keyed by a value, not nodes that merely reference it in a field. | `tap_grid/tests/test_spine_natural_key.py::TestOutputOnly`; the scan in `-11`. Issue# 1178 - tap. |
| req-grid-entity-natural-key-22 | Never unique; indexed without a size limit | Proposed | No unique index or constraint covers `Entity.natural_key`; two rows may hold one value and neither write is refused. No plain btree indexes the full value (an index row over ~2700 bytes is an error on insert). A hash index serves equality; a btree over `left(natural_key, 600)` with `text_pattern_ops` serves prefix search. Neither is partial, so both cover tombstones. A 3000+ byte key stores through the importer and is found by equality and by prefix. | Ruled 2026-11-11 by George (no constraint; anchore's row-size failure). The within-dimension constraint under *Future* is deferred by this ruling. `tap_grid/tests/test_natural_key.py::TestSpineColumn`; `tap_grid/tests/test_spine_natural_key.py::TestOutputOnly::test_a_duplicate_key_refuses_nothing`, `::TestThroughTheImporter::test_a_key_over_the_btree_row_limit_stores_and_is_found`, `::TestTheIndexesAreUsed`; migration `0008_entity_natural_key_published`. Issue# 1178 - tap. |
| req-grid-entity-natural-key-23 | Writes that bypass a save catch up | Proposed | `tap_grid.spine_natural_key.sync(entity_types=None, changed_only=False)` re-derives the key for every row of every registered type (or the named ones) and writes only what differs; it is idempotent, includes tombstoned rows, and skips — and reports — a type whose table or declared columns do not exist yet. Migration `0010_entity_natural_key_backfill` runs it once over every type, core and plugin; no plugin ships a migration for it. A plugin data migration that rewrites constituting values calls `resync_natural_keys(<entity types>)` afterwards. `manage.py sync_spine_natural_keys` runs it by hand. | `tap_grid/spine_natural_key.py`; `tap_grid/tests/test_spine_natural_key.py::TestCatchUpAndDrift`. The sync reads declarations from the registered classes, because historical migration models carry no `NATURAL_KEY`. Issue# 1178 - tap. |
| req-grid-entity-natural-key-24 | Prefix search is exact and index-served | Proposed | `find_by_spine_key(prefix=…)` filters `left(natural_key, 600) LIKE '<first 600>%'` (the index expression) and `natural_key LIKE '<prefix>%'` (the recheck), escaping `%` and `_`; `equals=` compares the full value. `natural_key_prefix(model, leading)` composes a leading run of a multi-field key's values exactly as the key does and ends with the separator (`corp\|10.0.1.5\|`), so it never matches a longer value (`10.0.1.50`). The plans use the prefix and hash indexes. | `tap_grid/spine_natural_key.py::find_by_spine_key`, `tap_grid/natural_key.py::natural_key_prefix`; `tap_grid/tests/test_spine_natural_key.py::TestPrefixes`, `::TestTheIndexesAreUsed` (EXPLAIN). Issue# 1178 - tap. |
| req-grid-entity-natural-key-25 | Recipe changes and drift are caught | Proposed | `sync()` records each type's fingerprint — a hash of its slug, its `NATURAL_KEY` tuple and `COMPOSITION_VERSION` — in `NaturalKeyRecipe` once its rows are in step. `sync_spine_natural_keys --changed`, run at every deploy, re-derives each type whose fingerprint differs or was never recorded. `sync_spine_natural_keys --check` samples each type's rows, compares the stored key with a fresh composition, lists stale recipes, and fails when it finds either. | `tap_grid/models.py::NaturalKeyRecipe`, `tap_grid/natural_key.py::recipe_fingerprint`, `tap_grid/spine_natural_key.py::check`; migration `0009_naturalkeyrecipe`; `tap_grid/tests/test_spine_natural_key.py::TestCatchUpAndDrift`. Issue# 1178 - tap. |
| req-grid-entity-natural-key-26 | A type states its key's spelling once | Implemented | `BaseModel.normalize_natural_key(values) -> values` is a classmethod over the dict of a type's declared constituting values, a hole as `None`. It is the identity by default, and must be pure, deterministic and idempotent: no instance, no database. `tap_grid.natural_key.normalized_key_values` is the one place it is applied, and it refuses a result that does not carry exactly the declared entries. It is for a rule that spans entries; a rule over one field belongs in that field's `to_python` (-19). Changing a type's rule changes its stored keys, so it ships as a re-key with a migration; that is documented and not yet enforced (`req-grid-entity-model-version` rule 12 is the enforced form, Proposed). | unified-systems-com/tap#1265; maintainer ruling 2026-11-22 (aws-build Q135a, Q135c). `tap_grid/tests/test_natural_key_normalize.py::TestTheHook` |
| req-grid-entity-natural-key-27 | The spelling holds wherever a key is resolved | Implemented | The normalised values, not the payload as sent, are what core locks on (`resolve_identity`'s `identity_lock_key`), what the importer's in-batch index and explicit-node locks are keyed by, what `find_existing` searches (so `find_by_natural_key` too), and what a key that arrives only as a reference resolves through (the importer's `_find_node_by_key`, shared by edge endpoints, removal targets and anchors). `prepare_for_write`'s default writes the normalised values onto the row's own fields, a JSON-path entry into a copy of its document, and the write refuses a row whose key is not a fixed point of the rule after that hook (an override that skipped `super()`, or a rule that is not idempotent). So two spellings of one new key in one batch, or written one after another, land one row, and a short spelling finds it. | unified-systems-com/tap#1265; maintainer ruling 2026-11-22 (aws-build Q135a, Q135b). `tap_grid/tests/test_natural_key_normalize.py::TestWhereItApplies` |

#### Future
- **Aliases.** A `{former_key: reason}` record on the spine, with `reason` a closed vocabulary (`renamed` · `key_definition_changed` · `merged` · `asserted`), keeping a former key findable after a migration or an operator assertion. Designed, deferred.
- **Within-dimension uniqueness — deferred by ruling (2026-11-11, `-22`).** `(entity_type, natural_key, identity_scope) WHERE deleted_at IS NULL` is expressible now that the column holds a composed identifier, but a constraint lets a first writer block a type's updates. Revisit only when perspectives arrive, only type-scoped, and only once the dimension vocabulary is cleaned up (today's keys mix perspective, facet and locator).
- **Grid-to-grid replication** as a third addressing mode (`tap#548`): a replicated row keeps the originating grid's id and skips the search.

### Batch Pointers On The Spine
----
RID: `req-grid-entity-batch-pointers`

Status: `In Development`

The spine records, for every node and edge, the batch that last changed it and the batch that last observed it. "What did this batch change" and "what has not been seen since" become one query on one table, across every type.

#### Status Details
In Development. The three columns, every write that sets them, the spine surface and the import refusal are built (Issue# 323 - tap): the fields on `Entity` in `tap_grid/models.py` (migration `0017_entity_batch_pointers`, `tap_grid` only), the stamp in `BaseModel.save()` and in `_execute_write_pipeline` in `tap_grid/services/_impl.py`. The tests are `tap_grid/tests/test_entity_batch_pointers.py`. Issue# 323 - tap holds the ruling and the prior-art review (`docs/misc/doc-grid-provenance-placement-prior-art.md`).

What is not settled is rule 12. `last_observed_at` is built with no index. One measurement was made on 2026-11-22, on PostgreSQL 18.6, on a synthetic table of one million rows with a pass that names 100,000 of them, one run each on a shared host: the observation write took 2.19 s with no index on `last_observed_at` and 2.73 s with one; a "not seen since" count took 91 ms (one type), 180 ms (all types) and 92 ms (a search matching under 1% of rows) with no index, and 31 ms, 26 ms and 2 ms with one. That is one data point on synthetic data, not the measurement on data of realistic size rule 12 asks for, and no decision has been taken from it.

As built, three things the rules do not spell out:

- A batch's own spine row carries no pointer. A batch cannot be written in a batch, the same reason FLIP is off for it.
- On a create, `last_observed_at` is the row's own `updated_at`, to the microsecond; on a change and on a retirement it is the time written to `updated_at` in the same statement. That is how rule 5's "never earlier than the time of the last change" is met.
- A repeat delete of an already retired object writes nothing (`req-grid-service-delete-tombstone-6`), so it moves no pointer, although the operation names the object. Nothing is recorded for it on the batch either.

Rule 6 is enforced where the pointer is written: inside the write pipeline's scope a save with no batch in context raises and nothing is stored. `write_batch` always resolves a batch before any operation runs, so no supported caller reaches that refusal. Outside the pipeline (a named below-pipeline writer, a test fixture that saves a row directly) there is no batch to name, and the pointers are left as they are; such a row can have null pointers.

The typed-row `batch_id` is still written on every save (rule 10).

#### Implementation

| Field | Type | Meaning |
| --- | --- | --- |
| `last_changed_batch_id` | UUID, nullable, indexed | The batch whose write last changed this object: its create, any operation `req-grid-history-reobservation` classifies as changed, or its retirement. |
| `last_observed_batch_id` | UUID, nullable, indexed | The latest batch that wrote or re-observed this object, changed or not. |
| `last_observed_at` | timestamp, nullable | When that observation was recorded on this grid. |

1. They are plain ids, not foreign keys, matching how batch ids travel in the caller context.
2. `last_changed_batch_id` is set in the same statement that increments `version`, so the two cannot disagree.
3. `last_observed_batch_id` and `last_observed_at` are set for every object an operation names, including a re-observed-unchanged one. That write is a direct row update: it does not increment `version`, does not move `updated_at`, and writes no history.
4. Only an object the batch's operations name is stamped. A pass that fetches a subset stamps that subset; nothing is inferred for objects it did not send.
5. A change is also an observation: after any changed operation `last_observed_batch_id` equals `last_changed_batch_id`, and `last_observed_at` is never earlier than the time of the last change. The one exception is maintenance by the grid itself (`req-grid-entity-model-version` rule 30): a migration that rewrites a row moves `last_changed_batch_id` and leaves the two observation fields where they were, because no source or analyst named the object. After it the two pointers differ, and `last_observed_at` can be earlier than the change.
6. A service-layer write that changes an object with no batch in context fails. It does not leave the pointer null.
7. The pointers describe the current state. `last_changed_batch_id` is the last writer, not a ledger: a batch that changed an object which a later batch changed again is no longer named on the row. The full footprint of a batch is the history rows and the batch's own record.
8. `last_observed_at` is kept on the row so that "when" survives a batch record being pruned.
9. All three join the canonical spine surface (`req-grid-entity-spine-surface`) after `version`, and are readable and filterable through Gryphon. They are derived on the receiving grid and are not accepted from a GRIFT import envelope, the same rule `natural_key` follows.
10. The typed-row `batch_id` is not removed by this requirement. Its removal changes every plugin table and is specified with that release (Issue# 1288 - tap), after a check that the history rows still say which batch produced each version.
11. `last_observed_batch_id` and `last_observed_at` record that a batch named the object, and nothing more. They do not say that a source saw the thing at that time: an analyst's edit and a collector's pass both move them, and what kind of write it was is read from the batch they point at, not from a vocabulary of change types on the row. They do not confirm every field either: a pass that sends two fields and leaves the rest under keep-absent moves them just the same, and nothing on the grid says which unchanged fields a pass asserted. FLIP records which batch last changed each field's value, and an `observe` event names the object and no fields. That is a known limit of this design, not something a consumer can work around by reading FLIP and the batch.
12. Whether `last_observed_at` is indexed is decided by measuring the cost of the write in rule 3 against the cost of a "not seen since" search, on data of realistic size. It is written for every object every pass names, so an index on it is paid on every observation. The two batch pointers are indexed in any outcome.

#### Development
A row-level "last changed by" on the common header is the near-universal placement in comparable systems, and a separate non-versioning "last seen" beside it is the pattern inventory systems converge on. Per-field provenance stays on the typed row (`req-grid-flip-map-3`); the header carries only the three scalars.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-batch-pointers-1 | Create Sets Both | Implemented | After a create, both batch pointers name the creating batch and `last_observed_at` is set. | `TestCreate`: a service create, an import create under a given id, and an edge create. |
| req-grid-entity-batch-pointers-2 | Re-Observation Moves Only Observed | Implemented | After an unchanged re-import in a second batch, `last_changed_batch_id` still names the first batch, `last_observed_batch_id` names the second, `last_observed_at` moved, and `version` and `updated_at` did not. | `TestObservationAndChange`: an unchanged re-import and an unchanged service patch. |
| req-grid-entity-batch-pointers-3 | Change Moves Both | Implemented | After a changed write in a third batch both pointers name the third batch. | `TestObservationAndChange`: a changed patch and a changed replace. |
| req-grid-entity-batch-pointers-4 | Retirement Is A Change | Implemented | A tombstone sets `last_changed_batch_id` to the retiring batch, on the node and on every edge it ends, and agrees with `flip_map["deleted_at"]`. | `TestRetirement`: a node with two edges, checked against `flip_map["deleted_at"]` on all three rows. |
| req-grid-entity-batch-pointers-5 | One Query Per Batch | Implemented | Filtering `Entity` on `last_changed_batch_id` returns every node and edge a batch created or changed and that no later batch has changed, across all types. | `TestOneQueryPerBatch`: two nodes and an edge, then one node changed by a later batch. |
| req-grid-entity-batch-pointers-6 | Unnamed Objects Untouched | Implemented | A batch that names a subset of a type's objects leaves the pointers of the others unchanged. | `TestObservationAndChange.test_a_batch_that_names_a_subset_leaves_the_rest_alone`. |
| req-grid-entity-batch-pointers-7 | No Batch, No Write | Implemented | A changing service-layer write with no batch in context is refused. | `TestNoBatchNoWrite`: a change and a create inside the pipeline's scope with no batch in context. No supported caller reaches the refusal, because `write_batch` always resolves a batch. |
| req-grid-entity-batch-pointers-8 | Not Importable | Implemented | A GRIFT envelope that supplies any of the three fields is rejected. | `TestNotImportable`: one case for each of the three fields. Refused by the envelope's closed key list, as `natural_key` is. |
| req-grid-entity-batch-pointers-9 | Spine Sync Counted | In Development | A re-import that changes only spine `name` or `dimensions` moves `last_changed_batch_id`. | `TestSpineSyncCounted`. Tested for a re-import that changes only `dimensions`, and for a rename. A change of the spine `name` alone is not tested: the type used has a `name` field, and the importer refuses an envelope name that differs from it. |
| req-grid-entity-batch-pointers-10 | Gryphon Reads Them | Implemented | A Gryphon query can filter on `last_changed_batch_id` and compare `last_observed_at` with a time. | `TestGryphonReadsThem`: an equality filter on `last_changed_batch_id` and `<` / `>=` on `last_observed_at`. |

### Event Time On The Spine
----
RID: `req-grid-entity-event-time`

Status: `In Development`

Every node and edge can carry one event time on the spine: when the thing happened or held in the world, as its source states it. A model declares which of its own fields say so, and the grid copies them into one start and end pair on `Entity`. What that start means (that the thing occurred, was created, was first seen or was published) is the row's `time` dimension. "What was happening between 02:00 and 02:10" is then one indexed query across every type and every source.

The grid keeps three kinds of time apart, and this requirement is the first of them:

| Time | Meaning | Where |
| --- | --- | --- |
| Event time | When the thing happened or held in the world, according to the source | This requirement |
| Collection time | When a collector gathered it at the boundary to the grid | `req-grid-entity-collection-time` |
| Grid time | When the grid wrote it | `Entity.created_at` (first written), `Entity.updated_at` (last changed, `req-grid-history-reobservation`), `Entity.last_observed_at` (last seen, `req-grid-entity-batch-pointers`) |

#### Status Details
In Development. Built (Issue# 194 - tap): the three columns on `Entity` (migrations `0018_entity_event_time` and `0019_entity_event_kind_to_time_dimension`, `tap_grid` only, `event_start` indexed and nothing else); the kind as the grid-derived `time` dimension (`tap_grid/dimension_map.py`: `GRID_DERIVED`, `settle`, `with_grid_derived`; core's seed in `tap_grid/data/dimensions.grift.json`); the declaration, the one reader, the derivation and the overlap test in `tap_grid/event_time.py`; the derivation in `BaseModel.save()` and in the pipeline's create under a given id in `tap_grid/services/_impl.py`; the edge type declaration (`event_time` in the edge definition, registered from a manifest or a core app's list); the warning in the operation's result; the spine surface; and the re-derive pass (`tap_grid/event_time_rederive.py`, `manage.py rederive_event_time --as USERNAME [--type SLUG]`) with its `maintenance` batch event type. Proof: `tap_grid/tests/test_entity_event_time.py`.

Not built, and why the requirement is not Implemented:

- The failure half of rule 1. An undeclared node model is reported by plugin validation and does not fail until the collector sweep has reached every plugin (Issue# 1289 - tap). `TAP_REQUIRE_EVENT_TIME_DECLARATION=1` makes it a failure. The report is carried at info severity and worded as a warning, because `--strict` promotes a warning-severity message to a failure and every plugin repository's CI runs `--strict` (`req-tap-plugin-validate-strict`): a true warning would fail the fleet on the day this lands.
- No plugin declares an event time yet. Core's configuration types (`arrangement`, `elevation`, `layout`, `projection`, `page`, `panel`, `collector`, `dimension`, `search`, `keystone`, `tap_file`, `tap_directory`) state that they have none. Four core types are left undeclared because the answer is not obvious from their fields and has not been ruled: `batch` (`started_at`, `closed_at`), `collection_job` (`enqueued_at`, `started_at`, `finished_at`), `schedule` (`enabled_at`, `last_schedule_fired`) and `schedule_fire` (`scheduled_for`, `fired_at`).
- Rule 16's measurement. `event_start` is indexed and nothing else is. No measurement of write cost against window-search cost was made with these columns on real tables.
- The GRIFT import result does not yet carry an operation's warnings to its caller: a value left off the spine during an import is warned of in the write operation's result and not in the import's result.

As built, things the rules do not spell out:

- A node's declaration is a class attribute, `EVENT_TIME`: `Moment(field, kind)`, `Interval(start, kind, end=None)` or `NO_EVENT_TIME`. An edge type's is `"event_time": {"shape": "moment", "field": <key>, "kind": <kind>}` or `{"shape": "interval", "start": <key>, "end": <key>, "kind": <kind>}` in its definition.
- A declaration that is present and wrong (a name that is not a field, a field that holds neither a date nor text, an unknown kind) fails plugin validation now. Only the absence of a declaration is staged.
- A warning has the form `event_time_not_stored: <field>: <why>`. It is reported on an unchanged write as well, since the typed value is still what it was.
- An interval whose start is empty has no event time, whatever its end holds. An interval whose end falls before its start is refused by comparing the end of the end's unit with the start of the start's unit, so `2026-12-01` to `2026-12-01` is one day and not a refusal.
- A save that stores only some fields (`update_fields`) re-derives the event time only when one of the declared fields, or an edge's `properties`, is among them.
- The re-derive pass opens its batch on the first row it changes, so a pass that finds every row in step leaves no batch. It converts retired rows with live ones and never touches a batch's own row. It runs under a named below-pipeline writer, `event_time_rederive`, which may write the three event columns and `dimensions` (for the `time` dimension) and nothing else (`req-tap-auth-write-batch-routing`), and needs an actor with `grid.write`.
- An unchanged write does not repair a spine pair that is already out of step with a changed declaration; the re-derive pass does. This is the position `req-grid-history-reobservation` takes for a stale spine name.
- The kind was first built as a fourth column, `event_kind`, and moved to the `time` dimension before any release (ruled 2026-11-22, recorded on Issue# 1284 - tap). Migration `0019` drops the column and moves no data: a grid that ran `0018` and wrote rows in between runs the re-derive pass, which stamps `time` on every row that has an event time.
- The stored map for a create or a replace is built in one place, `dimension_map.settle`: the type's defaults, the caller's values over them, then the grid's own derived entries. The save and the pipeline's create under a given id pass the kind just derived; the import's comparison of an envelope with the stored row (`spine_delta`) and the post-pass that writes what it found carry the stored row's grid-derived entry over. An envelope never carries `time`, so without this every re-import of a row that has one would differ from the spine, be classified changed and write a history row a pass, which is the defect `req-grid-history-reobservation` removed. `TestTheTimeDimension` holds it.
- A grid whose core vocabulary has not been imported yet has no `time` dimension node. A save there derives the three columns and leaves the dimension unset, without an error; the re-derive pass stamps it once the node exists. Boot imports core's vocabulary as its first grid write, so this is the state between `migrate` and `boot` only.
- The exporter leaves grid-derived entries out of an envelope's `dimensions` (`dimension_map.without_grid_derived`), so a document this grid wrote imports here and elsewhere.
- A declaration's kind is checked against the `time` dimension's own `values` where the grid's vocabulary is loaded (plugin validation), and against the tuple `EVENT_KINDS` in `tap_grid/event_time.py` where it is not (a class body). A test holds that tuple equal to the seed's list. A kind outside the four therefore cannot be declared today even on a grid whose `time` dimension lists it; that is the first thing to change when a fifth term is added.

Issue# 194 - tap and Issue# 1284 - tap hold the rulings. The design record is `docs/misc/doc-grid-time-and-observation-standardization-plan.md`; this requirement departs from it in two places, both recorded on Issue# 1284 - tap: the pair states a duration and not an uncertainty range (rule 5), and a value that cannot be stored truthfully is left off the spine with a warning, where the design record proposed a hard stop (rule 12).

What exists today (read on core main, 2026-11-21): `Entity` carries `created_at` and `updated_at` only. A source's own times are typed fields with a different name on every model, so a search across types by world time is a union over typed tables by someone who knows each field name. `req-grid-history-time` (`spec-grid-history.md`, Proposed) names the same world time `observed_at` on history rows; the two are reconciled, under the name this requirement uses, when either is built.

The forms a value may take and the levels of precision are those of the FHIR `dateTime` type, taken as published (rule 10). How about thirty shipped systems store dates of partial precision was compared on 2026-11-22 (the summary is on Issue# 1284 - tap; one research pass, relayed in summary). The systems that search such dates by time window, four FHIR servers on relational stores among them, keep a derived low and high timestamp for searching and the original text in the source record. This requirement's pair and typed field are that design. It differs from those servers in two places: it stores a precision marker where they imply one from the width of the range, and its end bound is exclusive where theirs is the last instant of the unit. A window search over a start and an end column was run on PostgreSQL 18.6 on 2026-11-22 and needs nothing beyond ordinary comparisons.

Compared on 2026-11-21 with the published schemas of 23 other systems (the summary is on Issue# 1284 - tap). The split into three times matches Elastic Common Schema, OCSF, Google SecOps and Azure Monitor. Rule 9 is stricter than those four, which substitute the receive time when a source time is missing or implausible and leave no marker; OpenTelemetry's log model takes the position this requirement takes.

#### Implementation

| Field | Type | Meaning |
| --- | --- | --- |
| `event_start` | timestamp with time zone, nullable | When the thing happened, or began to hold. |
| `event_end` | timestamp with time zone, nullable | When it stopped holding. Equal to `event_start` for an exact moment. Empty when the source states no end. |
| `event_precision` | short text, nullable | How exact the source value was: `year`, `month`, `day` or `second`. Anything coarser than `second` means the stored pair is widened (rule 10). |

What `event_start` means is not a column. It is the row's value of the `time` dimension (`req-grid-dimension-core-vocabulary` in `spec-grid-dimension.md`): `occurred`, `created`, `first_seen` or `published`.

The pattern a text value must match is the one FHIR R4 publishes for `dateTime` (`https://hl7.org/fhir/R4/datatypes.html#dateTime`, copied from that page on 2026-11-22):

```text
([0-9]([0-9]([0-9][1-9]|[1-9]0)|[1-9]00)|[1-9]000)(-(0[1-9]|1[0-2])(-(0[1-9]|[1-2][0-9]|3[0-1])(T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\.[0-9]+)?(Z|(\+|-)((0[0-9]|1[0-3]):[0-5][0-9]|14:00)))?)?)?
```

1. A model declares its event time as a class attribute beside `NATURAL_KEY`. The declaration states its shape in words, and the number of fields does not decide it. A `moment` names one field: the thing happened at that time. An `interval` names a start field and, optionally, an end field: the thing began to hold at the start and held until the end. Either states the kind. A model with no such time says so explicitly. A model that does neither is caught by plugin validation, in two stages (ruled 2026-11-22, Issue# 1284 - tap). Until the collector sweep has reached every plugin (Issue# 1289 - tap) it is reported as a warning and validation does not fail, strict mode included. After that it is a failure, the rule `NATURAL_KEY` and `KEYLESS` follow. One switch moves validation from the first stage to the second: the environment variable `TAP_REQUIRE_EVENT_TIME_DECLARATION=1`. That is the rule for node types. Edge types declare theirs differently (rule 20).
2. The declaration names fields the model already has. No model adds a column, renames a field or changes a field's type to satisfy this requirement, and no plugin table changes.
3. On every save of a typed row the grid derives the three spine columns from the declared fields and writes them in the statement that already writes `name` and `natural_key`. In that same statement it sets the row's `time` dimension to the declared kind, with source `derived`, where an event time was derived, and removes it where none was: a row with no event time carries no `time` value. Nothing a caller supplies reaches any of these. A GRIFT envelope that supplies one of the three columns is rejected, the rule `natural_key` follows. A value for the `time` dimension is refused from every writer: a service payload's dimensions, an edge's initial dimensions, a GRIFT envelope's `dimensions`, a type's declared default dimensions and an edge type's. No timestamp is ever a dimension value: the start and the end are the typed columns, and the dimension holds only the kind. A save that stores only some of a row's fields derives from what the row holds: a declared field the save leaves out is read from the stored row, never from an unsaved value in memory.
4. The stored values are timezone-aware and in UTC, whatever form the source field takes.
5. The pair states a duration: how long the thing lasted or held. How uncertain a time is, is stated by `event_precision`. The one place the two meet is rule 10: a value less exact than a moment is stored as the interval its unit covers, and the marker says that the width is the source's precision and not the thing's length.
6. `event_start` is inclusive and `event_end` is exclusive. An exact moment is stored with both equal, and the overlap test the grid publishes matches a moment that falls inside the window. A window's end is after its start; the test refuses a window that is empty or reversed, which an open-ended row would otherwise match.
7. An empty `event_end` means the source states no end: the thing still holds, or the source does not say. Only a value the source states closes it. The grid never closes it from the fact that a collector stopped seeing the object. Whether a thing is probably gone is read from reconciliation and the collector's own evidence of what it listed, not from event time and not from `last_observed_at`, which says only that a batch named the object.
8. A long-lived object (an instance, a repository) declares an `interval` whose start is the time its source says it came to exist, kind `created`. If the source has no field for its end the declaration names none, and `event_end` is always empty for that type.
9. An event time is never defaulted. Where the source gives no value the three columns are empty and the row has no `time` value, and empty means not asserted (`req-grid-node-observation`). No write path substitutes a collection time or the write time.
10. The forms a declared field may hold, and the levels of precision, are those of the FHIR `dateTime` type as published, with nothing added: a year (`2026`), a year and month (`2026-12`), a full date (`2026-12-01`), or a full date and time to the second or finer with a zone (`2026-12-01T18:30:00Z`). The levels are `year`, `month`, `day` and `second`. There is no hour or minute level, because FHIR has no value that stops at the hour or the minute. Something an hour wide, such as an hourly rollup, is not an imprecise moment: it is declared as an `interval` with two bounds at level `second`. A value at level `second` is a moment and is stored as rule 6 says, whether or not it carries a fraction of a second. A coarser value is stored as the interval its unit covers. A date with no time of day is stored with `event_start` at the start of that day in UTC, `event_end` at the start of the next day, and `event_precision` `day`; `month` and `year` follow the same form. That is the form for a `moment`. For an `interval`, each stated bound is widened on its own: the start becomes the start of the start value's unit, a stated end becomes the end of the end value's unit, and an end the source does not state stays empty and is not closed at the end of the start's unit. The marker is the coarser of the bounds that are stated. This is the reading ISO 8601 and the Extended Date/Time Format give a reduced-precision date: it names an interval, not its first instant.
11. A source value with a time of day and no time zone is not copied. The grid does not assume a zone.
12. A value the grid cannot store truthfully (rule 11, an end before its start, a value that does not parse) leaves the three spine columns empty and the `time` dimension unset, and adds a warning to the operation's result naming the field. The typed field keeps what the source sent. A future-dated value is stored: a scheduled thing has a real future time. An end is before its start when the end's unit is already over at the moment the start's unit begins: a start of 2 November and an end of 1 November is reversed, although the two stored bounds would be equal. Equal bounds are stored only where both values are exact moments.
13. Where a model has several candidate times, its author declares the one that says when the thing happened in the world, as the source states it. A collection time is never declared. The time the source last edited its own record is not declared when a time for the thing itself exists. A finding is declared at its creation, the choice OCSF and the AWS finding format make.
14. A source's other times (first seen, last seen, published) stay typed fields. They have no copy on the spine.
15. The three columns join the canonical spine surface (`req-grid-entity-spine-surface`) and are readable and filterable through Gryphon. The kind is filtered as any dimension is (`n.dimensions["time"] = "occurred"`, `req-grid-dimension-query-form`), so one query can state a window and a kind.
16. Which of the three are indexed, and with what kind of index, is decided by measuring write cost and window-search cost on data of realistic size, where most long-lived objects have an empty `event_end`. `event_start` is indexed in any outcome.
17. A change to a model's declaration reaches existing rows through a core command that re-derives the spine columns and the `time` dimension from the typed rows. It writes no history and no version, because no typed value changed. It runs as a batch and records, for every row whose spine values it changes, a batch event of a maintenance type of its own, so the change has a record that says what made it. That type is `maintenance`. It is not `create`, `update` or `observe`, and every reader that asks whether a batch saw an object leaves it out: maintenance by the grid is not evidence that a source or an analyst named the object. It does not move `last_observed_batch_id` or `last_observed_at`, because no source or analyst named the objects. It writes a row only while the row is at the version it was read at; a row a save has changed in the meantime already holds a newer event time and is left alone. The `time` dimension is set or removed by a database update of that one key, on a save and in this pass alike, never by writing back a whole dimension map read earlier, so a dimension another writer changed in between is not lost; and the pass's named writer is refused any other `dimensions` value.
18. Event time gives no ordering guarantee across sources: two sources' clocks are not synchronised. A consumer that reads the grid incrementally keys on grid time or on batch, never on event time, because a row whose event time is in the past can arrive at any later moment.
19. A window search returns possible matches, for two separate reasons. A row with precision `day` is returned by every window that overlaps that day: it may have happened in the window. A row with an empty `event_end` is returned by every window after its start: the grid knows when it began and does not know that it still held. `event_precision` `second` says the stated bounds are exact; it does not say the interval is complete. A reader that needs certain matches requires both a precision of `second` and a stored pair that covers or lies inside the window, which an open-ended row never satisfies. The grid does not hide imprecise or open-ended rows from a window search and does not narrow them.
20. An edge type may declare an event time. All edge types share one model class, so the declaration is made in the edge type's definition, beside its property rules, and names keys of the edge's properties where a node's declaration names fields: a `moment` with one key, or an `interval` with a start key and an optional end key, and the kind. What the time of a relationship is, is for the edge type's author to decide. An edge type that declares nothing has no event time: none is the default, no statement of absence is required, and plugin validation does not fail. Its three spine columns are empty and it has no `time` value, which reads as every empty value on the grid reads: not asserted (`req-grid-node-observation`). A declaration that names a key the edge type's own property schema does not define fails plugin validation: it could never hold a value. Every other rule here applies to an edge as it does to a node.
21. A declared field, or a declared property of an edge, is one of three things, and its level is read from which. A date field holds a full date and has level `day`. A date-time field holds a full date and time and has level `second`. A text field holds one of the four forms of rule 10, and its level is read from the text of each value, so one field can hold `2026` on one row and `2026-12-01` on the next. A text value is accepted when it matches the published pattern above and names a real calendar date; any other value is handled by rule 12. A second of 60, which the pattern admits for a leap second, cannot be stored in a timestamp and is handled by rule 12 as well. A fraction of a second finer than the database stores is cut short on the spine. A year, month or day whose unit ends after the last time the grid can store (the last units of the year 9999) is handled by rule 12 too: its interval could not be stored whole. Core provides the one reader that turns a value into a start, an end and a level; no plugin writes its own.
22. The original stays where it was written. The value a spine pair is derived from, or both values for an interval, stays in the body of the model it is derived from, in the form the source gave it. The spine columns are derived from it and never replace it, and no search reads the text: a window search is a comparison on `event_start` and `event_end`.

#### Development
Two designs for precision were considered and withdrawn before this one. The first was a list of six levels taken from the ISO 8601 ladder, with hour and minute; no shipped system found uses those two levels for stored values, and Wikidata defines them and never enabled them. The second was a field type of core's own for a partial date; PostgreSQL has no type that accepts `2026` or `2026-12` (tested on 18.6), and a new type would have been a format of our own. Copying the FHIR value as it stands adds no format, and the three packages found that store partial dates in Django were not fit to adopt.

One time per object on the spine is a narrower choice than the forensic timeline tools make (one entry per timestamp) and than the finding schemas make (several named times side by side). It is the choice that keeps the spine one row per object. The typed fields still hold every time the source gave, and further spine columns can be added later without changing any plugin table.

A value a source states is never dropped to save a write. A source's own "last seen" says when the source saw the thing; the grid's `last_observed_at` says when a batch last named the object on this grid. They answer different questions, and the first stays a typed field. When it moves on every pass it is a change on every pass and writes history on every pass (`req-grid-history-reobservation`); that is the source's data. What a collector should not store is a time it made up itself, such as its own clock at the moment it ran: that is collection time, and it has its own place (`req-grid-entity-collection-time`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-event-time-1 | Declared Moment Is Copied | Implemented | Creating a node whose model declares one event-time field sets `event_start` and `event_end` to that value in UTC, the row's `time` dimension to the declared kind and `event_precision` to `second`. | `TestDeclaredMoment.test_a_declared_moment_is_copied_in_utc`: a value at `+02:00` is stored in UTC with both bounds equal. |
| req-grid-entity-event-time-2 | Declared Span Is Copied | Implemented | A model declaring two fields sets `event_start` and `event_end` from them; an empty end field leaves `event_end` empty. | `TestDeclaredInterval`: a stated end, and an empty end field. |
| req-grid-entity-event-time-3 | Undeclared Model Is Warned Of, Then Fails | In Development | Until the collector sweep is complete, plugin validation reports a model that neither declares an event time nor states that it has none, and does not fail, strict mode included. With `TAP_REQUIRE_EVENT_TIME_DECLARATION=1`, and for every plugin once the sweep is complete, it fails. | Built and observed: the report without a failure, and the failure under the switch (`TestTheDeclarationCheck`). Proposed, not built: the failure as the default. The report is at info severity; see Status Details. |
| req-grid-entity-event-time-4 | Never Defaulted | Implemented | A node whose declared field is empty has all three spine columns empty and no `time` value after create and after update. | `TestDeclaredMoment`: empty after create and after a later patch, and emptied when the value is taken away. |
| req-grid-entity-event-time-5 | Date-Only Value Covers Its Day | Implemented | A declared field holding a date with no time is stored with `event_start` at the start of that day in UTC, `event_end` at the start of the next day and `event_precision` `day`; the typed field is unchanged. | `TestPartialPrecision.test_a_date_with_no_time_covers_its_day`, on a text field holding `2026-12-01`. No model in the test stack has a date field; a date value is covered at the reader (`TestTheReader.test_a_date_field_value_is_a_day`). |
| req-grid-entity-event-time-6 | Zone-Less Value Not Copied | Implemented | A declared field holding a time with no zone leaves the spine fields empty and the result carries a warning naming the field. | `TestPartialPrecision.test_a_value_the_grid_cannot_store_is_left_off_and_reported`, the zone-less case; the warning starts `event_time_not_stored: description:`. |
| req-grid-entity-event-time-7 | End Before Start Not Copied | Implemented | A span whose end precedes its start leaves the spine fields empty, keeps the typed values and warns. | `TestDeclaredInterval.test_an_end_before_its_start_is_not_copied`. |
| req-grid-entity-event-time-8 | Moment Matches A Window | Implemented | The published overlap test returns a node whose moment falls inside the window, and a node whose span overlaps it, and no node whose span ended at the window's start. | `TestTheOverlapTest.test_a_moment_in_the_window_and_an_overlapping_span_match`: also a moment at the window's start (in), one at its end (out), an open-ended row (in) and a row with no event time (out); the filter and the plain function agree on every row. |
| req-grid-entity-event-time-9 | Not Importable | Implemented | A GRIFT envelope that supplies any of the three columns is rejected. | `TestNotImportable`, one case for each of the three. Refused by the envelope's closed key list, as `natural_key` is. |
| req-grid-entity-event-time-10 | Follows The Typed Field | Implemented | Changing the declared field through a patch moves the spine values in the same operation, with one version. | `TestDeclaredMoment.test_a_patch_to_the_declared_field_moves_the_spine_with_one_version`. |
| req-grid-entity-event-time-11 | Re-Derive Writes No History | Implemented | The re-derive command fills the spine values of existing rows, adds no history row and no version, records one batch event for each row it changed under its own batch, and leaves `last_observed_at` where it was. | `TestRederive`: three rows filled, version, `updated_at`, history count and all three batch pointers unchanged, one `maintenance` event per changed row under one batch; a second pass changes nothing and opens no batch; a declaration taken away empties the rows. |
| req-grid-entity-event-time-12 | Gryphon Reads Them | Implemented | A Gryphon query can filter nodes of two different types by one `event_start` window. | `TestGryphonReadsThem`: the same `event_start` window as a query over `grid_fixtures__node` and over `grid_fixtures__hub`, one query per type. A single query spanning both labels was not tried. |
| req-grid-entity-event-time-13 | No Plugin Table Changes | Implemented | Adding the columns, and later dropping the kind column, produces migrations in `tap_grid` only. | `TestSpineSurface.test_the_migration_touches_the_grids_own_tables_only`; `makemigrations --check` reports no changes. |
| req-grid-entity-event-time-14 | Imprecise Value Is A Possible Match | Implemented | A node with precision `day` is returned by a one-hour window inside that day, and is not returned once the search also requires `event_precision` `second`. | `TestTheOverlapTest.test_an_imprecise_value_is_a_possible_match`. |
| req-grid-entity-event-time-15 | Four Forms, Four Levels | Implemented | A text field holding `2026`, `2026-12`, `2026-12-01` and `2026-12-01T18:30:00Z` on four rows gives precisions `year`, `month`, `day` and `second`, the first three stored as the interval the unit covers and the fourth as a moment. | `TestPartialPrecision.test_four_forms_on_four_rows_give_four_levels`, and `TestTheReader.test_the_four_forms`. |
| req-grid-entity-event-time-16 | No Hour Or Minute Value | Implemented | A text value that stops at the hour or the minute (`2026-12-01T18`, `2026-12-01T18:30`), or carries a time with no zone, leaves the spine fields empty and warns; the typed field keeps it. | `TestPartialPrecision` for the hour, the minute and the zone-less value on a row; `TestTheReader.test_what_the_reader_refuses` adds `24:00`, a leap second and a date that is not on the calendar. |
| req-grid-entity-event-time-17 | Original Stays In The Model | Implemented | After a write of a partial date the typed field holds the text as sent, and no spine value has been written back into it. | `TestPartialPrecision.test_a_date_with_no_time_covers_its_day` reads the typed field back as sent. |
| req-grid-entity-event-time-18 | Edge Type Declares Its Own | Implemented | An edge type whose definition declares a moment on a property key has its spine pair set from that property; an edge type that declares nothing passes plugin validation and has all three columns empty and no `time` value. | `TestEdges`: a declared moment on a property key, a change to that property, an undeclared edge type with the three columns empty and no `time` value, and the edge definition schema accepting the declaration and not requiring it. |
| req-grid-entity-event-time-19 | One Reader | Implemented | Every derivation of a spine pair, for a node or an edge, goes through core's one reader; a value it refuses is refused for every type. | `TestEdges.test_a_value_the_one_reader_refuses_is_refused_for_a_node_and_an_edge`: with the reader replaced, a node and an edge are both refused. |
| req-grid-entity-event-time-20 | The Kind Is The `time` Dimension | Implemented | A row with an event time holds `{"v": <kind>, "src": "derived"}` under the `time` dimension's node id; a row with none holds no entry, and gains and loses it as its declared field is set and emptied. The kinds a declaration may name are the seeded dimension's `values`. | `TestTheTimeDimension`: the stored entry, a row that gains and loses it; `TestTheReader.test_the_static_kinds_are_the_seeded_time_dimensions_values`. |
| req-grid-entity-event-time-21 | Not A Writer's | Implemented | A value for `time` in a service create's dimensions, in a GRIFT envelope's `dimensions`, or in a type's declared defaults is refused, and nothing is written. | `TestTheTimeDimension.test_a_writer_may_not_supply_it` (a service create, a declared default, a forged `src: derived`) and `test_an_envelope_that_supplies_it_is_refused`. An edge's initial dimensions and an edge type's `default_dimensions` go through the same two functions and were not tested separately. |
| req-grid-entity-event-time-22 | A Re-Import Is Still Unchanged | Implemented | An unchanged re-import of a node whose type declares an event time adds no history row and no version, records an `observe` event, and leaves the `time` value in place; a re-import that changes only the declared field, or only a caller's dimension, keeps it. | `TestTheTimeDimension`: two unchanged re-imports (version, `updated_at`, history count and the whole dimension map unchanged; events `create`, `observe`, `observe`), a changed declared field, a changed caller dimension. |
| req-grid-entity-event-time-23 | An Export Leaves It Out | Implemented | An exported envelope's `dimensions` hold the row's other dimensions and not `time`, and importing that envelope back changes nothing. | `TestTheTimeDimension.test_an_export_leaves_it_out_and_round_trips`, on the exporter's envelope builder; a whole-document export through the command was not run with a timed row. |
| req-grid-entity-event-time-24 | One Query, A Window And A Kind | Implemented | A Gryphon query filtering `event_start` by a window and `n.dimensions["time"]` by a kind returns the rows of that kind in the window and no others. | `TestGryphonReadsThem.test_one_query_filters_a_window_and_a_kind`, one query per type; a labelless `MATCH (n)` does not support a row projection, so one query across types was not possible. |

### Collection Time On The Spine
----
RID: `req-grid-entity-collection-time`

Status: `In Development`

Collection time is when a collector gathered an object at the boundary to the grid. The spine carries it for the latest batch to name each object, as a start and an end, and each batch event carries it for its own pass.

#### Status Details
In Development. Issue# 194 - tap and Issue# 1284 - tap hold the rulings. This requirement places the latest pair on `Entity`; the design record placed it on the batch event only.

Built (Issue# 194 - tap): the two columns on `Entity` and the same two on `BatchEvent` (migration `0020_entity_collection_time`, `tap_grid` only, no index); the write-batch form; the settling of a stated window and the three reports (`tap_grid/collection_time.py`); and every write that names a batch on a row, which now writes the pair in that same statement: the create and the changing save in `BaseModel.save()`, the create under a given id, the unchanged observation and the two retirement updates in `_execute_write_pipeline` (`tap_grid/services/_impl.py`). Tests: `tap_grid/tests/test_entity_collection_time.py`.

The write-batch form (rule 2), as built: `WriteOperation.collected`, a `CollectionWindow(start, end)` beside the operation's `payload` and never inside it. An operation names one object, so the window is keyed by object through the operation that carries it, the shape `dimensions` and `spine_intent` already have. Each bound is a timezone-aware datetime or an ISO 8601 text with a zone. The single-verb helpers (`create_node`, `patch_node` and the rest) do not take it; a writer that states a window calls `write_batch`.

Not built:

- The GRIFT document form (rule 2). It follows with the other GRIFT forms. Until it exists a GRIFT import states no window for anything, so every row an import names has an empty pair after it (rule 5), collectors included, since they write through the importer.
- Reading the batch event's pair through Gryphon (rule 9). Gryphon reads entities, and a batch event is not one. The spine pair is filterable through Gryphon; the per-pass pair is read from `BatchEvent` rows. This half of rule 9 cannot be met as written.
- No collector states a window. The sweep that moves them onto the form is Issue# 1289 - tap.

As built, things the rules do not spell out:

- A retirement states its window for the node the operation names. The edges that end with it are named by the retiring batch too (`last_observed_batch_id`), and that batch stated no window for them, so their pair is emptied (rule 5). A node retired by a contained cascade is treated the same way.
- A repeat delete of an already retired object writes nothing (`req-grid-service-delete-tombstone-6`), so it moves no pair.
- A window that is not recorded (rule 6) empties the pair like an unstated one: the batch is still the last to name the object.
- "Earlier" in rule 5 compares the stated `collected_end` with the `collected_end` the row carried, read under the row lock the write already holds. A create has nothing to compare with.
- Rule 7 is reported in two cases: the object's event time start is later than the window's end, and the window's end is later than the time of the write. Each is a warning in the operation's result that starts with `collection_time_out_of_order`; an older read arriving late starts with `collection_time_older_read`, and a window left out with `collection_time_not_recorded`.
- A save made outside the write pipeline with no batch in context names no batch on the row and leaves the pair as it is.

#### Implementation

| Field | Type | Meaning |
| --- | --- | --- |
| `Entity.collected_start` | timestamp with time zone, nullable | When the collector began reading this object, as stated by the latest batch to name it. |
| `Entity.collected_end` | timestamp with time zone, nullable | When it finished. Equal to the start when the object was read in one call. |
| `BatchEvent.collected_start`, `BatchEvent.collected_end` | timestamp with time zone, nullable | The same pair, for the pass that event records. |

1. The pair is a window on the collector's own clock. It carries no precision marker: the width of the window is the precision.
2. A collector states the pair for each object it sends, in a part of the write batch and of the GRIFT document that is keyed by object and kept apart from the object's own fields. The write-batch form is specified and built with the spine columns, before the sweep that moves collectors onto it (Issue# 1289 - tap): a collector cannot be asked to state a window until there is somewhere to state it. The GRIFT document form follows with the other GRIFT forms, the last wave of Issue# 1284 - tap.
3. A pair the collector does not state is empty, on the event and on the spine. It is never filled with the write time (`req-grid-node-observation`: empty means not asserted). A reader that wants a best estimate uses the observing batch's own start and close.
4. The spine pair is written in the row update that sets `last_observed_batch_id` and `last_observed_at`, for every object an operation names, changed or not. It writes no history and no version.
5. The spine pair belongs to the batch that last named the object, the one `last_observed_batch_id` points to. It is the pair that batch stated, or empty when that batch stated none, so a pair is never left standing for a pass that did not state one. It is not the latest read by the collector's clock. A batch whose stated `collected_end` is earlier than the one on the spine is an older read arriving late. The pair moves to the earlier window, with everything else that batch wrote, and the operation's result carries a warning that names the object and both windows. This can happen and it is accepted. A late older read can put older values on the row in place of newer ones; the pair then describes the read whose values the row holds, and what the row held before, with its window, is read from history and from the earlier batch's event. That is what history is for. Keeping the later window instead would leave a pair on the row that no longer describes the row's values.
6. Stored values are timezone-aware and in UTC. A pair with no zone, or whose end precedes its start, is not recorded and the operation's result carries a warning. The database holds the same rule for every writer: on the entity row and on a batch event, both bounds are set or neither is, and the end is not before the start.
7. For a thing already true when it was collected, event time is expected not to be later than collection time, and collection time not later than grid time. The grid does not enforce the order. A violation is a signal about a clock and is reported, never corrected.
8. The spine pair is not indexed at first, so that the write in rule 4 stays cheap. An index is added when a search needs one and its write cost has been measured.
9. The spine pair joins the canonical spine surface and is readable and filterable through Gryphon. The pair on a batch event is read from the batch's events: a batch event is not an entity, so Gryphon does not reach it.

#### Development
The per-pass record is the batch event; the spine holds a copy of the newest one so that a search does not join to events. Keeping the copy on the row is the same choice `last_observed_at` makes, for the same reason: a time must survive the pruning of the record it came from.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-collection-time-1 | Stated Pair Is Recorded | Implemented | A write that states a collection window for an object sets the pair on that object's batch event and on its spine row. | `TestStatedPairIsRecorded`: a create, a create under a given id, a changing patch, an edge, and a retirement; `TestSettleWindow` for UTC and a read in one call. |
| req-grid-entity-collection-time-2 | Unstated Pair Stays Empty | Implemented | A write that states none leaves both pairs empty; neither equals the write time. | `TestUnstatedPairStaysEmpty`; `TestSettleWindow.test_nothing_stated_is_an_empty_pair_and_no_warning`. |
| req-grid-entity-collection-time-3 | Unchanged Observation Moves It | Implemented | An unchanged re-import that states a new window moves the spine pair and adds no history row and no version. | `TestUnchangedObservation`: a keep-absent replace, the write a re-import makes, with a new window: version, `updated_at`, history count and `last_changed_batch_id` unmoved, an `observe` event carrying the window. Stated through the write batch; a GRIFT document cannot state one yet. |
| req-grid-entity-collection-time-4 | Later Unstated Pass Empties It | Implemented | After a pass that stated a window, a pass that states none leaves the spine pair empty and `last_observed_at` moved. | `TestUnchangedObservation`: an unchanged pass and a changing pass that state none. |
| req-grid-entity-collection-time-5 | Bad Pair Not Recorded | Implemented | A window whose end precedes its start, or with no zone, is not recorded and the result warns. | `TestBadPairNotRecorded` and `TestSettleWindow`: end before start, no zone on either bound, text that is not a time. |
| req-grid-entity-collection-time-6 | Order Not Enforced | Implemented | A write whose event time is later than its collection time succeeds and the result reports it. | `TestOrderNotEnforced`: event time later than the window, and a window later than the write; an ordinary window reports nothing. |
| req-grid-entity-collection-time-7 | Late Older Read Moves It And Warns | Implemented | After a pass that stated a window, a second pass stating an earlier window moves the spine pair to the earlier window, records that window on its own batch event, moves `last_observed_at`, and the result carries a warning naming the object and both windows. | `TestLateOlderRead`: an unchanged and a changing older read; a later window does not warn. |
| req-grid-entity-collection-time-8 | Stated Without GRIFT | Implemented | A service-layer write batch can state a collection window for an object before any GRIFT form for it exists. | `TestStatedPairIsRecorded.test_a_create_that_states_a_window_sets_the_event_and_the_spine`: `WriteOperation.collected` through `write_batch`, no GRIFT document involved. |

### Model Versions And Upgrade Steps
----
RID: `req-grid-entity-model-version`

Status: `In Development`

Every node type and edge type has a version: a number its author sets. On one grid every row of a type is at the same version, because the migration that ships with a new version rewrites them together. Versions matter where data crosses between grids. A GRIFT document states the version of each type it carries, and an import upgrades older records through steps the type's author keeps, or is refused where the author has declared that no step exists.

#### Status Details
In Development. Rules 1 to 8 are built (Issue# 475 - tap); rules 9 to 33 are not. Issue# 475 - tap holds the first prior-art review, and Issue# 1284 - tap records the rulings and two further comparisons made on 2026-11-21: about 25 systems on upgrading stored data, and about 30 on breaking changes. Each was one research pass over primary documentation, relayed in summary.

What those comparisons support: systems that migrate a whole store keep one version for the store and none on a row; systems whose records arrive at mixed versions keep a version with each record and a chain of upgrade steps; nearly all refuse input newer than the code; and a change of meaning with no change of structure is caught by nothing but its author.

Built:

- The declared version: `MODEL_VERSION` on `BaseModel` (1 unless a class states another) and `version` in an edge definition, beside `property_schema` (`tap_grid/schemas/edge-definition.schema.json`; a core app's `edge_types` entry takes the same key). `tap_grid/model_version.py` reads both.
- The applied version: `EntityType.model_version` (migration `0022_model_and_spine_versions`, `tap_grid` only, no column on `Entity` and no plugin table changed). Its two writers are `register_type`, for a type the catalog has no row for, and `set_applied_version`, the call a migration makes in the transaction that completes its conversion. The catalog refuses any other write that would change it (`EntityType.save` and `EntityTypeQuerySet`).
- The agreement rule. Registration compares at start (`TapPluginConfig._register_types_from_manifest` for a plugin's types, `register_core_types` for core's) and raises `ModelVersionAhead`, which stops the process, where the applied version is the greater. Where the declared version is the greater the process starts, `migrate` runs, and the type is refused in four places, each naming the type and both versions: the write pipeline (`model_version_pending` in the operation's result), `BaseModel.save` (`ModelVersionPending`, for a write that reaches a typed row any other way), the GRIFT importer's preflight (`model_version_pending`, the whole document) and `export_grid` (`ModelVersionPending`). A retirement by id passes.
- Core's types in the catalog (rule 6): a row and an applied version for sixteen node types and seventeen edge types. `req-grid-entity-core-type-catalog` says what is left of that requirement.
- The guard and the record (rules 5 and 7): `tap_grid/model_definition.py` writes a type's definition down and fingerprints it; `tap/guards/model_version.py` checks core's types and the spine against `<app>/<app label>.model_versions.json` in each core app; plugin validation checks a plugin's types against `<slug>.model_versions.json` at the plugin's root (check `model-version-records`); `manage.py model_versions --record` appends an entry and never rewrites one. Core's thirty-three types and the spine are recorded at version 1.
- Author guidance (rule 8) in the `add-model` and `add-edge` skills.

Not built, and why the requirement is not Implemented:

- Links, steps and breaks (rules 9 to 18), the import upgrade and the GRIFT header (rules 19 to 26, `req-grift-header-versions`), the history rules (27 and 28) and the adapter with its edge check (rules 29 to 33). Until the adapter exists a plugin's migration converts its rows itself and calls `set_applied_version` last; such a migration writes no revision, no history and no batch event, which is what rule 29 is there to end. No type in core or in an installed plugin is above version 1, so no such migration exists yet.
- An export does not state the versions it reads from the catalog; the header field is rule 19's. Acceptance criterion 21 is observed as far as the catalog: every type an export of core types carries has an applied version.
- Plugin validation does not yet fail a plugin type that has no committed entry. Every plugin starts with no record, so the absence is reported and the check passes; `TAP_REQUIRE_MODEL_VERSION_RECORD=1` makes it a failure. The report is carried at info severity and worded as a warning, for the reason `req-grid-entity-event-time` gives for its own staged check: `--strict` promotes a warning to a failure and every plugin repository's CI runs `--strict`. A type that has entries is held to them now.
- Edge types that no definition declares. A grid can hold edges of a type named only by a node's `OUTBOUND_EDGES`, with no `.edge.json` and no `edge_types` entry. Such a type has no catalog row and no version.

Limits of what is built, stated so they are not found later:

- A process learns which types are behind when it registers them, and holds that in memory. Before it refuses it reads the catalog again, so a migration applied by another process is seen without a restart. The opposite case is not seen: a process that started in agreement keeps writing after another deployment has migrated the rows under it. That is the general hazard of migrating under running code, and rule 4's registration check catches it at the next start.
- The fingerprint chain shows an edit to an earlier entry that left the stored fingerprints alone, and an edit that re-fingerprinted that entry alone. It cannot show a rewrite of every fingerprint from the edited entry on, since nothing outside the file attests to it; that is for review of the file's history.
- The definition covers what rule 5 lists. An edge type's identity declaration (its discriminators) is not in that list and is not covered, although changing it changes which edges are the same edge. A node type's `EVENT_TIME` declaration is not covered either; it derives spine values and changes no stored field of the type.

#### Implementation

**The version of a type**

1. A model class carries an authored integer version as a class attribute, `MODEL_VERSION`. A model that states none is at version 1. An edge type carries one the same way, beside its property rules: `version` in its edge definition. The edge table all edge types share belongs to core and is covered by `req-grid-entity-spine-version`.
2. A grid holds each type at one version: the one the installed code declares. A new version that changes stored rows ships with the migration that rewrites them, so no row is left behind at an older version. No row carries a version, on `Entity` or on the typed table.
3. Two versions exist for a type and they are different facts. The class declares the version the code understands. `EntityType.model_version` (integer) records the version applied to this grid's data: the version its stored rows are at. The applied version is written by the migration that moves the rows to it, in the transaction that completes the conversion, and by nothing else except the first registration of a type the grid has never held, when there are no rows and applied equals declared. A type that is first catalogued while the grid already holds rows of it is recorded at version 1: those rows were written before versions were recorded, and version 1 is what every type was then. Registration at start does not advance it: start-up code runs before migrations do, so a stamp taken from the loaded class would call rows migrated that are not. A migration that fails leaves the applied version where it was.
4. Ordinary operation requires the declared and the applied version to agree. Where the class declares a greater version than the one applied, the rows are not yet migrated: writes to the type, and imports and exports that carry it, are refused, naming both numbers, until migrations are applied. The migrate command itself runs through the disagreement; that is what it is for. Where the applied version is greater than the class declares, the code is older than the data and registration of the type fails, naming both. One write is allowed through the disagreement: the retirement of an entity named by its id. It is an operation on the spine that reads and writes no field of the type (rule 22), and it is the cleanup a refused migration asks for (rule 32), which would otherwise be blocked by the refusal it is meant to clear. Nothing else is: no create, no update, no restore, and no retirement that names its target by type and key, which would need the type's key at a version the rows are not at.
5. A guard computes a fingerprint of each type's definition (its fields, their types and constraints, its natural key, its service schema, and the edge rules it declares, which are the edge types and endpoint types it allows outbound and inbound; for an edge type, its property rules, its endpoint rules and its event-time declaration) and compares it with the one committed beside the authored version. A definition whose fingerprint changed while its version did not fails the guard in the repository that owns the type. The fingerprint covers what the type's owner declares: the fields the class itself adds, and its own key, schema and edge rules. Fields every type inherits from core's base model (`batch_id` today, the tombstone and dimension copies later) belong to the spine's definition and are covered by `req-grid-entity-spine-version`. A change core makes to an inherited field moves no type's version and needs no link from any plugin.
6. Every type a grid can export has a catalog row with an applied version, core's own node and edge types included, because an export reads the versions it states from the catalog. This requirement needs a row and a version for each of core's types, and does not need their icons, which stay with `req-grid-entity-core-type-catalog`. The `edge` model is not a type in this sense: every edge type shares its table, which belongs to the spine.
7. The committed record is a list with one entry per version, and it only grows. Changing the entry of a version already committed fails the guard. Each entry holds enough of that version's definition for rule 15 to compare two versions: the definition itself, and a fingerprint chained to the entry before it. The record is kept by the type's owner, in one file at the root of the package that defines the types, named `<app label>.model_versions.json`: a plugin's in the plugin's repository, where plugin validation checks it, and core's in each core app, where core's guard does.
8. A change of meaning with no change of definition (a unit, a convention inside a JSON field) is invisible to the guard. The author raises the version by hand, and the type's author guidance says so.

**The chain of versions**

9. For every version after the first, the type's author provides one link from the version before it. A link is either a step or a declared break.
10. A step takes what one record asserts at version N and returns it at version N+1. It reads that record and nothing else: no other record, no database, no network. It does not import the model class, so it keeps working as the class moves on. It is plain code that gives the same output for the same input.
11. What a step is given may be partial. A stored row is complete, but a GRIFT node may omit a field to leave the stored value untouched (`spec-grid-import-grift.md`). A step preserves what was and was not said: it returns a field only where its input carried what that field is derived from, keeps an explicit null as null and an observed empty value as empty, and adds no default. A default for a new field is applied where a row is created, by the model, never by a step; otherwise an old document that sent only a name would arrive asserting a setting its sender never saw. A step that cannot upgrade a partial record without a field it was not given refuses that record and says which field it needs.
12. A link also says what happens to the type's natural key, where the version changes it: a function from a key at version N to the key at N+1, or a refusal. It is applied wherever a document names an entity of the type by key without carrying its record: an edge endpoint, a removal target, an authority anchor.
13. A step declares what it costs: nothing is lost, or the named fields are dropped, or it may refuse some records, with the reason. A step also declares where a field of version N+1 came from when it did not come from the field of the same name: a rename names the one old field, and a field built from an old field names it. The declaration is how the guard tells a rename from a removal beside an addition, so that a rename that loses nothing is not declared as a dropped field, and it is what the adapter follows when it carries source attribution across (rule 31).
14. A declared break says that no step exists from version N to N+1, with the reason, and may name a successor type.
15. The guard compares each version's definition with the one before it. A field removed, a type narrowed, a field made required, a natural key changed or an edge rule tightened fails the guard unless the link declares it: as a rename, as a dropped field, as a step that may refuse, as a tightened edge rule (rule 32), or as a break.
16. A type whose chain is missing a link fails plugin validation.
17. A type may declare the oldest version it still imports. A record older than that is refused, naming the version.
18. Where a change can be expressed on one record, the plugin's data migration for that version calls the same step for the stored rows. A test in the plugin checks that a version-N export upgraded by the step equals the export of the migrated table.

**Import**

19. A GRIFT document states, in its header, the version of every type it carries: `metadata.type_versions` (`req-grift-header-versions` in `spec-grift-v0.md`).
20. A document that carries a type and states no version for it is refused, naming the type. There is no default. The header fields first ship in 0.5.0, so no released grid has written a document that could state them and did not; a document that forgot to state a version is not taken for the oldest one. A document exported before 0.5.0 imports once the fields are added to its header.
21. An import upgrades before it validates and before it writes anything, in this order: parse the document's framing; find every position that names a versioned type, which is every node and edge record and every endpoint, removal target and anchor that names an entity by type and key; upgrade the records (rule 10) and the keys (rule 12) from the stated version to the installed one; re-derive the envelope values that depend on what was upgraded; validate against the installed contracts; resolve identity; execute the batches. The upgrade is part of the import and runs in or beside the GRIFT importer, the one path every inbound write takes.
22. A removal that names an edge by id carries no edge type and needs none. It is an operation on the spine, and no type's link applies to it.
23. A record at a version greater than the installed one refuses the document, naming the type and both versions.
24. A document is refused, and nothing is written, when the chain it would have to cross contains a declared break, or when a step refuses any record. The refusal names the type, the link, and each record refused.
25. A field a step drops is reported in the operation's result, by type and field. It is never dropped without a report.
26. The import's batch records, for each type it upgraded, the version the document stated and the version it was upgraded to. What an import did to a record is read from its batch.

**History**

27. No step rewrites history rows, and they carry no version. A history row written before a version change holds the values that definition wrote, with one exception that follows from rule 28: the history table's columns follow the live model's, so a migration that changes the type of a field the type keeps changes the history table's column with it, and every old value in that column is converted with it. Before the migration changes anything it checks that every history value of that field can be converted, and it is refused if any cannot, naming the type, the field and how many values. The author may instead declare on the link that history values of that field which cannot be converted are discarded. Those values are then left empty in their history rows, the rows themselves stay, and the operation reports how many values were discarded. That option needs somewhere to put an empty value. The history table copies each plain field as the live model defines it, nullability included, so it is available only where the field can be empty in the new definition. Where the new field cannot be empty the option is refused by the guard: there is no truthful value to leave in its place, and a zero or an empty string would be invented data. The author then makes the field nullable, converts every value, or declares a break.
28. A migration that removes a field removes the column from the type's history table as well, because the history model is built from the live model's fields. The old values of that field are then gone from the grid. This is accepted. A step that declares a dropped field (rule 13) is the mark that it will happen, the type's author guidance states it, and an operator who needs the old values takes a database snapshot before migrating.

**Applying a version to stored rows**

29. A plugin's migration applies a step to stored rows through an adapter core provides. It does not write the typed table directly. A Django data migration works on historical models and does not call the grid's save path, so on its own it would change values with no revision, no history and no record of what made the change.
30. The adapter runs as a batch of its own. For every row the step changes it writes the typed row so that the entity's revision moves and one history row is written; records a batch event of the maintenance type `req-grid-entity-event-time` rule 17 defines, which no reader takes for a sighting; sets `last_changed_batch_id` to its batch, because its write is what last changed the row; re-derives the spine values that depend on what changed; and leaves `last_observed_batch_id`, `last_observed_at` and the collection pair where they were, because no source or analyst named the object. A row the step returns unchanged is not written. It converts every row of the type, retired rows with live ones, and a retired row stays retired: the applied version describes all the rows, and a restore after the migration must find a row at the current version. Where the type keeps no history (`TRACK_HISTORY = False`, `req-grid-history-optout`) there is no history table and the adapter writes none; it still moves the revision and records its batch event, and the batch event is then the only record of the change.
31. A FLIP entry stays with the source that asserted the value. The adapter does not work this out from what the step returned; it follows the step's declaration (rule 13). A field the step keeps under its own name keeps its entry, whether or not the step rewrote its value: the grid re-expressed the value and did not assert it. A renamed field's entry moves to the new name with its source and its time unchanged. A new field built from one old field takes that field's entry, and so does each of several new fields split from one old field. A dropped field's entry goes with it. A new field that comes from no old field has no entry until a source asserts it. One case cannot be represented and is refused: a field built from more than one old field. A FLIP entry names one batch for a field, and `first_name` from one batch joined to `last_name` from another has no single source. The guard fails a step that declares such a field, until FLIP can hold more than one source for a field; the author keeps the old fields beside the new one, or declares a break. The maintenance batch is never recorded as the source of a value. This is the exception `req-grid-flip-change` in `spec-grid-flip.md` names.
32. A version may tighten what edges are allowed: a node type stops allowing an edge type or an endpoint type it allowed, or an edge type narrows its endpoint rules. Edge rules are checked only when an edge is written, so without a check the edges written under the old rules would stay on the grid with nothing to say that no write could now create them. The link declares the tightening. Before the migration to that version changes anything, the adapter searches the edge table for live edges the new rules would refuse. If it finds any, the migration is refused and the applied version stays where it was; the refusal gives the count for each edge type and pair of endpoint types, and a sample of edge ids. An operator retires or corrects those edges through an ordinary batch and migrates again. The grid does not retire, delete or re-point an edge in order to pass the check. Retired edges are not checked. The cleanup works under the new code even when the edge type being upgraded is the type of the offending edges, because retirement by id is the one write rule 4 lets through.
33. The adapter writes the applied version (rule 3) in the transaction that completes the conversion. The checks of rules 27 and 32 run first, so a refused migration has changed nothing.

#### Development
A derived hash alone cannot serve as the version: it changes for edits that do not affect stored data, and it gives no order. An authored integer alone is forgotten. The pair is what every comparable system that upgrades data arrived at.

The record lives with the type's owner and not in one central file because the guard has to fail "in the repository that owns the type" (rule 5): a plugin's author raises the version, in the plugin's repository, and that is where the forgotten raise must be caught, before the plugin ships. A record in core for a plugin's types would be checked only when core's guards run with that plugin installed, by someone who cannot fix it. The file name is the singleton form `req-tap-json-naming` already defines. The entry stores the definition and not only its hash because rule 15 compares two versions field by field, and a hash can only say that something changed.

A version on every row was considered and left out. Where one migration moves every row of a type, the row's version always equals the type's, and a second copy of it is one more thing that can disagree. What does differ is a document written by another grid, so that is where the version is stated.

The limit of one record on a step (rule 10) is this requirement's own and not the migration system's: a Django data migration can read and write any table, as core's migration that re-keyed dimensions by node does. That is why the work that needs more than one record, the edge check of rule 32 and anything later that resolves such edges, belongs to the migration and its adapter and not to a step.

What a grid does about a declared break is deliberately not chosen here. Refusing (rule 24) is the behaviour until a way across is built, and each way across can be added as something a break declares on the model class, with no table change. Rule 28 was read from the history library's code and from the add and alter migrations core already carries for history models; no migration in core removes a field, so it has not been observed.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-model-version-1 | Catalog Records The Applied Version | Implemented | A type first registered at version 2 has `model_version` 2. After a migration to version 3 completes it has 3; restarting on version 3 code without migrating leaves it at 2. | A start is the registration call the process makes; a migration is `set_applied_version` in a transaction |
| req-grid-entity-model-version-2 | No Version On A Row | Implemented | Adding versioning produces a migration in `tap_grid` only, adds no column to `Entity`, and changes no plugin table. | `0022_model_and_spine_versions` |
| req-grid-entity-model-version-3 | Applied And Declared Must Agree | Implemented | With the class at version 2 and the catalog at 1, a write to the type is refused naming both and `migrate` runs; with the class at 2 and the catalog at 3, registration of the type fails naming both. | Also refused: a save below the pipeline, an import and an export that carry the type |
| req-grid-entity-model-version-4 | Guard Catches An Unbumped Change | Implemented | Adding a field to a model without changing its version fails the guard, naming the model. | Core's guard for core's types; plugin validation for a plugin's recorded types |
| req-grid-entity-model-version-5 | Committed Versions Do Not Change | Implemented | Editing the committed entry of an earlier version fails the guard. | A rewrite of every later fingerprint is not detectable from the file alone |
| req-grid-entity-model-version-6 | Missing Link Fails Validation | Proposed | A model at version 3 with no link from 2 to 3 fails plugin validation. | |
| req-grid-entity-model-version-7 | Undeclared Removal Fails | Proposed | Removing a field under a step that declares nothing lost fails the guard, and passes once the step names the field as dropped. | |
| req-grid-entity-model-version-8 | Older Import Is Upgraded | Proposed | A document stating version 1 for a type installed at version 2 imports, and the stored row holds what the step returns, validated at version 2. | |
| req-grid-entity-model-version-9 | Newer Import Refused | Proposed | A document stating version 3 for a type installed at version 2 is refused and writes nothing. | |
| req-grid-entity-model-version-10 | A Break Refuses The Import | Proposed | A document that would cross a declared break is refused, writes nothing, and the refusal names the type and the link. | |
| req-grid-entity-model-version-11 | One Refused Record Refuses The Document | Proposed | When a step refuses one record of many, no record is written and the refusal names that record. | |
| req-grid-entity-model-version-12 | Dropped Fields Reported | Proposed | Importing across a step that drops a field succeeds and the result names the type and the field. | |
| req-grid-entity-model-version-13 | Unstated Version Refused | Proposed | A document that carries a type with no stated version is refused, names the type, and writes nothing. | |
| req-grid-entity-model-version-14 | Step And Migration Agree | Proposed | A version-1 export upgraded by the step equals the export of the same rows after the plugin's migration. | |
| req-grid-entity-model-version-15 | Edge Types Are Versioned | Proposed | An edge type at version 2 imports a version-1 edge with its properties upgraded by the type's step. | |
| req-grid-entity-model-version-16 | Batch Records The Upgrade | Proposed | The batch of an import that upgraded a type names that type with the stated and the installed version. | |
| req-grid-entity-model-version-17 | Steps Do Not Rewrite History | Proposed | After a version change that keeps a field and its type, the history rows written before it are unchanged in number and in that field's values. | |
| req-grid-entity-model-version-18 | A Failed Migration Does Not Advance | Implemented | Loading version 2 code against version 1 data and failing the migration leaves the catalog at 1, and ordinary writes to the type stay refused. | The failure is raised after `set_applied_version`, inside its transaction |
| req-grid-entity-model-version-19 | Omission Survives An Upgrade | Proposed | A version 1 document that sends only a node's name imports into a type whose version 2 adds a field with a default, and the stored value of that field is unchanged. | |
| req-grid-entity-model-version-20 | Keys In References Are Upgraded | Proposed | A version 1 document carrying only an edge, whose endpoint is named by a version 1 natural key, resolves that endpoint after the key is upgraded, or is refused before identity is resolved. | |
| req-grid-entity-model-version-21 | Core Types Have Versions | In Development | An export of a grid holding only core types states a version for every type it carries or names. | Every core type has a catalog row and an applied version; the export does not state them until `req-grift-header-versions` is built |
| req-grid-entity-model-version-22 | Inherited Fields Move No Type | Implemented | Removing a field every type inherits from core's base model changes no type's fingerprint entry and fails no plugin's guard. |  |
| req-grid-entity-model-version-23 | Migration Goes Through The Adapter | Proposed | After a migration applies a step that changes a field on ten rows, each row's entity revision has moved by one, each has one new history row, each has a maintenance batch event under the migration's batch, and `last_observed_at` on each is where it was. | |
| req-grid-entity-model-version-24 | FLIP Stays With The Source | Proposed | After a step renames a field, the FLIP entry for that field is under the new name with the source and time it had; no FLIP entry names the migration's batch. | |
| req-grid-entity-model-version-25 | Tightened Edge Rule Is Declared | Proposed | Removing an edge type from a node type's allowed outbound edges without a version change fails the guard; with a version change and no declaration on the link it fails the guard; with both it passes. | |
| req-grid-entity-model-version-26 | Violating Edges Refuse The Migration | Proposed | A migration to a version that tightens an edge rule, on a grid holding one live edge the new rules refuse, changes nothing, leaves the applied version where it was and names that edge; after the edge is retired the same migration completes. | |
| req-grid-entity-model-version-27 | History Values Converted Or Refused | Proposed | A migration that changes a kept field's type converts that field in every history row; with one history value that cannot be converted it is refused before changing anything, and it completes, leaving that one value empty and reporting it, once the link declares such values discarded, where the new field can be empty; where it cannot, the guard refuses the declaration. | |
| req-grid-entity-model-version-28 | Cleanup Works While Versions Disagree | Proposed | With an edge type's class at version 2, its catalog row at 1 and one live edge of that type the new rules refuse: the migration is refused; an update to that edge is refused; retiring it by id succeeds; the same migration then completes. | |
| req-grid-entity-model-version-29 | Live And Retired Rows Both Move | Proposed | After a migration of a type holding live and retired rows, every row is at the applied version, each retired row is still retired with the retirement time it had, and a restored row validates at the new version. | |
| req-grid-entity-model-version-30 | Chain Through Fields The Class No Longer Has | Proposed | A grid at version 1 migrates to version 3 through a version 2 that added a field version 3 removed; both steps run without importing the model class, and the result equals a version-1 export upgraded through the same two steps. | |
| req-grid-entity-model-version-31 | Type Without History | Proposed | A migration of a type declaring `TRACK_HISTORY = False` moves each changed row's revision, records its maintenance batch event, and neither needs nor creates a history table. | |
| req-grid-entity-model-version-32 | Rename Is Not A Drop | Proposed | A step that declares a rename passes the guard with nothing declared dropped, and after migration the field's FLIP entry is under the new name. | |
| req-grid-entity-model-version-33 | Combined Field Refused | Proposed | A step declaring one new field built from two old fields fails the guard, naming the field and the reason. | |

#### Future
Ways across a declared break. None is chosen and they do not exclude each other:

- A successor type, with the link between the two types recorded on the catalog so that a search by type can widen to both. It cannot carry a condition on a field across, since the two types do not share fields.
- Changing an entity's type in place. `Entity.entity_type` is a plain string, ids do not derive from the type, and the stored natural key has no type prefix, so the entity row, its id and every edge to it can stay while the typed row is rebuilt under the new type. It needs the identity to hold, leaves the entity's history split across two history tables, and must be recorded by a batch because `Entity` has no history.
- A place to keep fields the new version cannot hold.
- An explicit switch by which an operator accepts a loss, where rule 25 only reports it.

Ways of resolving edges a tightened rule would refuse (rule 32), and a merge configuration, for the grid or for one GRIFT document, that chooses among them and among the ways across a break above: Issue# 1311 - tap.

### Spine Version
----
RID: `req-grid-entity-spine-version`

Status: `In Development`

The spine has its own version: a number core sets, which moves only when the spine changes. It is not the tap release version, not the GRIFT format version, and not any type's version. A plugin's models can then run on any number of tap releases, because nothing in a type's version or its upgrade steps refers to the spine.

#### Status Details
In Development. Rules 1, 2 and 7 are built; rules 3 to 6 are not. Issue# 1284 - tap records the ruling.

Built:

- `SPINE_VERSION = 1` in `tap_grid/spine_version.py`. Version 1 is the spine as of `tap_grid` migration `0022_model_and_spine_versions`.
- The record: the one row of `SpineVersion` (table `tap_spine_version`, the same migration), written by a `post_migrate` handler each time migrations are applied, while the database holds every `tap_grid` migration the code carries. It is written the same way when the schema is built from the models (`migrate_from_models`) and put back after a `flush`.
- The refusal: `tap_grid`'s `ready()` raises `SpineVersionAhead` where the record is greater than the code declares, so no process starts, `migrate` included. A database with no record yet starts, and `migrate` writes one.
- The guard: `tap/guards/model_version.py` holds the spine's definition (every column of `Entity`, the columns every typed row inherits from the base model, the columns core defines on the edge table, and their constraints) to the entry committed in `tap_grid/tap_grid.model_versions.json`.

Not built, and why the requirement is not Implemented:

- The GRIFT header field, the refusal of a document that states none or a newer one, and the spine's chain of links (rules 3 to 6, `req-grift-header-versions`).
- Lowering the record when a migration is reversed. The handler writes the record only while every `tap_grid` migration is applied, and never lowers one; with a single spine version there is nothing to lower to. It belongs with the chain.

What exists besides: a GRIFT document carries `grift_version`, which describes the form of the file, and nothing that says which spine wrote it.

#### Implementation
1. Core carries an authored integer spine version. It covers the `Entity` row and the columns core defines on the edge table: what they are and what they mean. A tap release that does not change the spine does not move it.
2. The grid records the spine version its database is at, written when migrations are applied. A database that records a version greater than the code declares is refused at start. The record is one row in a table of its own, `tap_spine_version`.
3. A GRIFT document states the spine version in its header, in a field of its own beside `grift_version`: `metadata.spine_version` (`req-grift-header-versions` in `spec-grift-v0.md`). The two move independently: the form of the file can change with the spine untouched, and the spine can change inside an unchanged form.
4. A document that states no spine version is refused; there is no default, on the same terms as `req-grid-entity-model-version` rule 20. One that states a version greater than the grid's is refused, naming both.
5. Core keeps a chain of links for the spine, of the same kind `req-grid-entity-model-version` describes: a step that takes one envelope at version N and returns it at N+1, or a declared break. An import upgrades each envelope through it before it validates.
6. A type's links never read or name the spine version, and the spine's links never read a type's fields. The two chains are applied independently.
7. The guard in `req-grid-entity-model-version` rule 5 applies to the spine: a change to the spine's definition without a change to its version fails in core.

#### Development
The record is a small table and not the `Keystone` node. A keystone is a node: it is read through the spine whose version is in question, it is written through the pipeline with a batch and an actor that a migration does not have, an operator can author several, and it travels in a GRIFT export, where it would carry one grid's spine version into another grid. A value the grid holds about its own database needs none of that, and core already keeps such bookkeeping in tables of its own (`NaturalKeyRecipe`).

The tap release version was considered as the key and left out. Most releases will not change the spine, and development builds between releases can, so a release number neither moves when the spine does nor stays still when it does not. The GRIFT format version was considered too and is kept as a different number; it answers a different question, how to parse the file.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-spine-version-1 | Grid Records It | Implemented | After migrations are applied the grid's recorded spine version equals the one core declares. |  |
| req-grid-entity-spine-version-2 | Newer Database Refused | Implemented | Code declaring spine version 1 does not start against a database recording version 2. | The refusal is raised in `tap_grid`'s `ready()` |
| req-grid-entity-spine-version-3 | Stated In GRIFT | Proposed | An export's header carries the spine version in a field separate from `grift_version`. | |
| req-grid-entity-spine-version-4 | Older Envelope Is Upgraded | Proposed | A document stating spine version 1 imports into a grid at version 2 with each envelope upgraded by core's step. | |
| req-grid-entity-spine-version-5 | Newer Document Refused | Proposed | A document stating a spine version greater than the grid's is refused and writes nothing. | |
| req-grid-entity-spine-version-6 | Independent Of Type Versions | Implemented | Raising the spine version changes no type's version or fingerprint entry, and raising a type's version changes neither the spine's. | Observed on the committed record: the spine's entries and the types' entries are separate lists |
| req-grid-entity-spine-version-7 | Unstated Spine Version Refused | Proposed | A document with no spine version is refused and writes nothing. | |

### Spine Copies On Typed Rows
----
RID: `req-grid-entity-spine-copies`

Status: `Proposed`

Every typed row, node or edge, carries a copy of two values from its entity row: when it was retired, and its dimensions. The copies exist so that a database policy on a typed table can decide what a reader may see from that table's own columns, without a lookup to `Entity` for every row. The database keeps them in step. Nothing but the database writes them, and the entity row stays the authority.

This requirement adds the columns and keeps them true. It adds no policy. Row-level security that reads them is a later requirement, and everything here is shaped so that adding it needs no further change to any plugin table.

#### Status Details
Proposed; nothing is built. Issue# 1147 - tap holds the evidence and Issue# 1284 - tap the rulings: copy both values, keep them in step with a database trigger, add no policies in this round and leave everything ready for them.

What exists today (read on core main, 2026-11-22): `deleted_at` and `dimensions` live on `Entity` only. A live-rows manager filters a query's root by joining to `Entity`; a join, a reverse accessor or a query that never touches `Entity` can still reach a retired row. That is how the ORM search compiler returned retired entities (Issue# 1144 - tap, fixed in PR# 1145 - tap). No model in core (read 2026-11-22) or in clones of 33 plugin repositories taken on 2026-11-21 declares a field named `deleted_at`, `dimensions` or either name below.

What was measured, on PostgreSQL 18.6:

- 2026-11-01, three million entity rows: a policy that looks the retirement up on `Entity` for each row was 3 to 39 times slower than no policy; a policy on a copied column on the typed table was within noise of no policy. For dimensions, an indexed copy was 10 to 40 times faster than the lookup for selective scopes. Every figure was flagged unreliable by the harness for host load, so they are orders of magnitude.
- 2026-11-22, a trigger of the design in rules 4 and 5 on two toy typed tables of 200,000 and 100,000 rows, in one transaction that was rolled back: no row out of step after six ways of writing (typed rows inserted with no copy, 20,000 entities retired by raw SQL on the entity table, dimensions changed by raw SQL, a writer setting the copies wrongly on typed rows, a restore then a rollback to a savepoint, a typed row created after its entity was retired); 7 of 7 rows out of step when the entity rows were changed with triggers disabled; a select-only role under a policy on the copies saw exactly the rows the entity table says are live. Retiring 50,000 entities took 3.0 s with the trigger, against 0.28 s for the update alone plus 0.90 s for one set-based statement to bring the typed table into step. One run each, on a shared host.

Not measured: the real tables, concurrent writers (rule 11), edges, and the cost on an ordinary collection pass.

#### Implementation

| Field on every typed row | Type | Meaning |
| --- | --- | --- |
| `spine_deleted_at` | timestamp with time zone, nullable | A copy of `Entity.deleted_at`. Empty while the entity is live. |
| `spine_dimensions` | JSON object, not null, `{}` by default | A copy of `Entity.dimensions`, in the stored shape, grid-derived entries included. |

**The columns**

1. Both fields are declared once, on core's base model, so every node model and the edge model has them. They are not editable, not part of any service schema or GRIFT payload, and not a field a plugin declares or overrides.
2. They are copies and are named as such. A reader that wants the authority reads `Entity`. Nothing in core computes a result that depends on a copy and the entity row disagreeing.
3. They belong to the spine's definition, not to any type's: they are inherited from core's base model, so adding them moves the spine version (`req-grid-entity-spine-version`) and no type's version, and needs no link from any plugin (`req-grid-entity-model-version` rule 5).

**Keeping them in step**

4. A trigger on the entity table fires after a row's `deleted_at` or `dimensions` changes and writes both values to that entity's typed row. It finds the typed table from the entity's type, through a table core maintains from the model registry that maps each entity type to its table. An entity type with no entry (a type whose plugin is not installed) is left alone.
5. A trigger on every typed table fires before a row is inserted or updated and sets both copies from the entity row, whatever the writer supplied. So a typed row is correct from the moment it exists, and a writer that sets a copy, by mistake or on purpose, is overruled in the same statement.
6. The two triggers are the only writers. No Python code path writes either column. The write guard refuses a save or a queryset update that names one, for every writer, the pipeline included.
7. An update that changes one key of `dimensions` in the database, as the grid's own derived entries are written (`req-grid-entity-event-time` rule 17), fires the trigger of rule 4 as a whole-map write does. The copy is the whole stored map after the statement.
8. The triggers and the type-to-table map are created and kept current by core after migrations are applied, for every typed table registered at that point, the way the natural-key indexes are. A plugin's migration adds the two columns to its tables and nothing else: no plugin writes trigger SQL, and a plugin installed later gets its triggers at its first migrate.
9. Rows that exist when the columns are added are filled by the same pass, one set-based statement for each typed table, before the triggers are relied on.
10. The triggers do not fire when triggers are disabled for a session, which a restore or a replication apply can do. So core provides a check that counts, for each typed table, the rows whose copies differ from their entity row, and a repair that brings them into step by the statement of rule 9. The check runs at boot and reports; a difference is a defect report, not a silent repair. Reporting without repair is right only while nothing trusts the copies, which is the case under this requirement: no policy exists (rule 16) and reads keep the join to `Entity`. It stops being right the day a policy reads them, because a copy left empty by a restore while its entity is retired would then show a retired row. So this requirement binds the one that adds policies: a policy that reads a copy is not enabled, and a role held by such a policy is not served, while the check finds any difference; a difference found then is refused, not reported. A check at boot is not enough for that: a restore or a replication apply can disable triggers on a grid that is already serving. The requirement that adds policies therefore also states when the check is repeated, and that an operation which disables triggers is followed by a clean check before a role held by a policy is served again. Neither is specified here, because nothing reads the copies yet.
11. The copies agree with the entity row under concurrent writers, not only one writer at a time. When one transaction changes an entity's `deleted_at` or `dimensions` while another writes that entity's typed row, the copies equal the entity row once both have committed, in whichever order they ran. The hazard is the trigger of rule 5 reading the entity row as it stood before a change that commits while the trigger's statement waits, and writing that older value over the newer one the trigger of rule 4 put there. So the trigger of rule 5 reads the entity row under a row lock, which makes it wait for a concurrent change and read the committed result, and every write path in core takes its locks in one order, the entity row and then the typed row, as the write pipeline already does. A writer outside core that takes them in the other order may be stopped by the database's deadlock detection and must retry; it is never left with a stale copy. This is specified and not yet demonstrated: a two-session trial is run before the build, and the design of rules 4 and 5 changes if it fails.

**History**

12. Both copies are recorded in each type's history table, so a history row holds the dimensions and the retirement state the entity had at that version. This is the grid's only record of what a row's dimensions used to be: `Entity` has no history table, and a dimension change is otherwise recorded only as the fact that a change happened. The value in a history row is set when the row is written, from the map the write settles on and the entity's `deleted_at`, and not read from the typed row object: the triggers write the typed columns inside the database, after the object was loaded, and on a change of dimensions the typed row is saved before the entity row is written, so the object would still hold the old values. A type that keeps no history (`req-grid-history-optout`) records none, and a history row written before this requirement holds neither, which reads as not recorded.
13. A retirement writes one final history row for the row it retires, and one for each edge the retirement ends, so that the retirement copy in history holds a value and the retirement's reason has a row to be recorded on (`req-grid-service-delete-reason-2`, Issue# 570 - tap). Today a retirement writes no typed history row at all, and a retired row is never written again, so without this the retirement copy would be empty in every history row. The cost is one history row for each retired row: a node with many edges writes that many edge history rows when it is retired. That is accepted; a node with ten thousand edges is a sign that a dimension was wanted.

**What the copies are kept out of**

14. Change detection and provenance: the copies are system-managed. They are left out of the comparison that decides whether a write changed an object, and they have no FLIP entry.
15. The canonical surfaces: the copies are not on the spine surface, in any return layer, or in an export. `deleted_at` and `dimensions` are read from the entity row there, as now.

**Readiness for row-level security**

16. No policy is created by this requirement, and no table has row-level security enabled by it.
17. Indexes on the copies are created by core for each typed table, by the mechanism of rule 8, when a policy that needs them is specified. None is created now: an index is paid for on every write, and which indexes a policy needs depends on the policy's shape, which is not decided. Because core creates them, adding them later changes no plugin's migrations.
18. PostgreSQL only. The triggers are PostgreSQL triggers; `spec-grid-sqlite-portability-BACKLOG.md` already records that the grid's database behaviour is not portable.

**Shipping it**

19. The columns ship in the one core release that changes the base model (Issue# 1288 - tap), with the removal of the typed `batch_id` column, so that every plugin regenerates its migration once. That release raises the floor every plugin states for core.

#### Development
A copy kept by the service layer was the alternative. It was not chosen because the copies are meant to carry security: a stale copy would show a row that should be hidden, so they must agree with the entity row on every path, including a plugin's data migration, a bulk retirement and a statement typed into a database shell, none of which passes through the service layer. The trigger costs about two and a half times a set-based sync on a bulk retirement in the one measurement made, and it is not portable.

The names say "spine" so that `row.spine_dimensions` cannot be mistaken for the authority or for a field of the model. The same names as the entity's columns were used in the first spike; they read as if a typed row owned its dimensions.

Reading the copy in the live-rows manager, in place of the join to `Entity`, is not part of this requirement. With the join a read is right even where a copy has drifted; reading the copy would make every ordinary read depend on it from the first day, in the same release that migrates every plugin's tables. It is a change of code with no migration, so it can follow.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-entity-spine-copies-1 | Every Typed Row Has Them | Proposed | Every registered node model's table and the edge table have both columns, and no model declares either itself. | |
| req-grid-entity-spine-copies-2 | Correct At Insert | Proposed | A typed row created through the service layer, and one inserted with wrong values supplied for both copies, each hold the entity row's values after the insert. | |
| req-grid-entity-spine-copies-3 | Retirement Reaches The Typed Row | Proposed | Retiring a node sets `spine_deleted_at` on its typed row and on the edge row of every edge the retirement ends, equal to the entity rows' values. | |
| req-grid-entity-spine-copies-4 | Dimensions Reach The Typed Row | Proposed | A service patch of dimensions, an import that changes them, and the grid's own key-level write of the `time` dimension each leave `spine_dimensions` equal to `Entity.dimensions`. | |
| req-grid-entity-spine-copies-5 | Raw SQL Is Covered | Proposed | An `UPDATE` of `deleted_at` and of `dimensions` on the entity table, made outside Django, leaves the typed rows' copies equal to the entity rows. | |
| req-grid-entity-spine-copies-6 | No Python Writer | Proposed | A save or a queryset update that names either column is refused by the write guard for every writer; a source scan finds no assignment to either outside the migration that adds them. | |
| req-grid-entity-spine-copies-7 | Triggers Without Plugin SQL | Proposed | A plugin whose migration only adds the two columns has both triggers on each of its tables after migrate, and a type in the map for each of its models. | |
| req-grid-entity-spine-copies-8 | Existing Rows Are Filled | Proposed | After the migration on a grid that already holds rows, no typed row differs from its entity row. | |
| req-grid-entity-spine-copies-9 | Drift Is Found And Repaired | Proposed | After entity rows are changed with triggers disabled, the check reports the number of differing rows for each table, the repair brings it to zero, and the report does not change what any reader sees while no policy exists. | |
| req-grid-entity-spine-copies-10 | Recorded In History | Proposed | After a write that changes only a row's dimensions, the history row that write adds holds the new map in `spine_dimensions` and the one before it holds the old; neither is read from a stale object. | |
| req-grid-entity-spine-copies-15 | Retirement Is In History | Proposed | Retiring a node with two edges adds exactly one history row to the node's type and two to the edge table, each holding `spine_deleted_at` equal to its entity row's `deleted_at` and the retirement's reason; the rows before them hold it empty. | |
| req-grid-entity-spine-copies-16 | Concurrent Writers Agree | Proposed | With two database sessions, one retiring an entity (and, separately, changing its dimensions) and one updating that entity's typed row, in each of the two orders in which they can interleave, the typed row's copies equal the entity row after both commit, or one session is refused by the database and the copies equal the entity row after the other commits. | |
| req-grid-entity-spine-copies-11 | Not A Change | Proposed | A write whose only effect on a typed row is a changed copy is not classified as a change to that row by the copies, and neither column has a FLIP entry. | |
| req-grid-entity-spine-copies-12 | Not On A Surface | Proposed | Neither column appears on the spine surface, in a return layer or in an export. | |
| req-grid-entity-spine-copies-13 | No Policy Yet | Proposed | After migrate, no typed table has row-level security enabled and no policy exists. | |
| req-grid-entity-spine-copies-14 | A Policy Would Agree | Proposed | With a test-only policy on `spine_deleted_at IS NULL` for a select-only role, that role's count of rows in a typed table equals the count of live entities of the type. | |

#### Future
- The policies: a column predicate for retirement, the form of a dimension scope, a scope set for the transaction so a pooled connection cannot leak one, and an administrator's path. They are enabled only on a clean drift check, and fail closed on a difference (rule 10).
- The indexes those policies need, created by core (rule 17).
- The live-rows manager reading the copy in place of the join, once the drift check has been watched on real data (ruled: the join stays for now).

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
