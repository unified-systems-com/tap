# GRIFT Envelope Specification

## Philosophy

A canonical TAP graph response — whether from a search, a Gryphon
traversal, a panel context, or a future graph-native API — is a
**subgraph** ([`spec-grift-subgraph`](spec-grift-subgraph.md)) whose
members are **envelopes**. The subgraph spec defines the outer
`{nodes: [], edges: []}` container and the `lite` / `full` / `extended`
return-layer concept. *This* spec defines the canonical per-member
shape: what each entry in `nodes` or `edges` looks like at every layer.

The envelope is honest about TAP's actual structure:

- TAP has a real architectural split between the **Entity spine** (one
  row per entity, common metadata, the identity backbone) and the
  **per-model BaseModel row** (one table per `entity_type`, typed
  domain fields, history-tracked).
- This split is load-bearing — it shows up in CLAUDE.md, in the service
  layer, in spec language. The envelope keeps the split legible so a
  reader of a response can tell what's where.
- TAP also has a **computed-for-render** family of values that don't
  live in either spine or per-model storage but are derived from them
  for rendering — shape hints, colors, icon URLs, computed labels. The
  envelope gives those their own lane rather than mixing them into
  domain data.

The result is a three-lane shape: **top-level spine** (flat, invariant,
Entity-row only), **`data`** (polymorphic-by-`entity_type`, per-model
fields, the polymorphism slot), and **`display`** (consumer-namespaced
computed-for-render). The structure is also extensible — additional
top-level lanes can be added for future use cases such as history,
provenance, perspectives, alternative views, etc., as demand-driven
requirements emerge.

The envelope is *also* honest about not being a fashion statement:

- **Cypher's property-bag node model** doesn't fit because Cypher
  property values must be scalars — TAP holds JSON in `configuration`,
  `tags`, `dimensions` natively. TAP doesn't punt on nested data.
- **JSON:API's `{id, type, attributes, meta}` shape** is one
  well-considered REST convention but isn't dominant in graph-DB land,
  isn't optimized for graph-query responses, and forces collapsing the
  Entity-vs-model split into a single `attributes` bag. The
  internal-vs-external API conversation may pull JSON:API in at the
  HTTP boundary later; the internal envelope keeps TAP's structure
  visible.
- **Cytoscape's `{data: {id, ...}}` model** is the closest cousin —
  the TAP envelope is essentially Cytoscape with the entity identifier
  pulled out to the surface plus the spine alongside it. Anyone who
  has typed `n.data.id` more times than they can count knows exactly
  why we made that choice.

## Goals

| | | |
| :---: | --- | --- |
| 1. | Architecture-Honest | The envelope shape reflects the Entity-vs-per-model split so readers can see what lives where |
| 2. | Polymorphism-Honest | `entity_type` determines the shape of `data` — that invariant is structurally visible |
| 3. | Uniform For Nodes And Edges | Same shape for both; the polymorphism is entirely in `data.*` |
| 4. | Layer-Compatible | Composes cleanly with `lite` / `full` / `extended` from `spec-grift-subgraph` |
| 5. | Future-Extensible | Additional top-level lanes can be added for history, provenance, perspectives, etc. without breaking v0 callers |
| 6. | Round-Trippable | Read shape and write shape are the same; no transformation layer between query result and service-layer write payload |

## Terminology

- **Envelope** — one canonical per-member object in a subgraph (a "node
  envelope" or "edge envelope"). Synonymous with what
  `spec-grift-subgraph` calls a "member."
- **Lane** — one of the top-level structural sections of an envelope
  (top-level spine, `data`, `display`, and future lanes).
- **Surface** / **top-level** — the outermost layer of the envelope,
  reserved for Entity-row spine fields.
- **Spine** — the shared metadata that every TAP-managed entity carries,
  stored on the Entity row (`tap_grid.models.Entity`). The canonical
  field set and order are defined in `spec-grid-entity` § Canonical
  Spine Surface (`req-grid-entity-spine-surface`).
- **Data lane** — the `data` key; holds per-model BaseModel-row fields,
  polymorphic by `entity_type`.
- **Display lane** — the `display` key; holds consumer-namespaced
  computed-for-render values (`tap_viz.{shape, colors, ...}`).
- **Denormalized field** — a field stored in two places (Entity row and
  per-model row) that the envelope mirrors in two lanes. Today: only
  `entity_id` and `name`.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grift-envelope-shape | [Envelope Shape](#envelope-shape) | In Development | Three-lane envelope: spine-flat-at-top, `data`, `display`; extensible |
| req-grift-envelope-spine-surface | [Spine Surface Rule](#spine-surface-rule) | In Development | Top-level fields are Entity-row fields only; canonical order defined in `spec-grid-entity` |
| req-grift-envelope-data-lane | [Data Lane Rule](#data-lane-rule) | In Development | `data` holds per-model BaseModel-row fields; shape varies by `entity_type` |
| req-grift-envelope-display-lane | [Display Lane Rule](#display-lane-rule) | In Development | `display` holds computed-for-render values, consumer-namespaced |
| req-grift-envelope-denormalization | [Denormalized Field Mirroring](#denormalized-field-mirroring) | In Development | `entity_id` and `name` appear at top-level (canonical) AND in `data` (required mirror) |
| req-grift-envelope-edge-uniformity | [Edge Uniformity](#edge-uniformity) | In Development | Edges use the same envelope; polymorphism lives in `data` |
| req-grift-envelope-validation | [Envelope Validation](#envelope-validation) | In Development | API entrypoints validate spine/mirror consistency; reject mismatch — `tap_grid.grift.envelope.parse_envelope_for_write` is the canonical parse-and-split function |
| req-grift-envelope-layer-mapping | [Layer Mapping](#layer-mapping) | In Development | `lite`/`full`/`extended` map to which lanes are populated |
| req-grift-envelope-supersedes | [Supersedes Prior Member Shape](#supersedes-prior-member-shape) | In Development | Reconciled in same change as serializer rewrite — `spec-grift-subgraph` Canonical Member Shape / Lite Member Guidance / Presentation Separation now cross-reference this spec |

## Envelope Shape
----
RID: `req-grift-envelope-shape`

Status: `In Development`

Every envelope in a subgraph has three lanes in v0, with room to grow
additional top-level lanes for future use cases (history, provenance,
perspectives, etc.) as demand-driven requirements emerge.

```json
{
  "entity_id":            "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc101",
  "entity_type":          "aws_lambda",
  "name":                 "samsite-prod-1-opa-compliance",
  "dimensions":           {"cloud": "aws", "aws_account": "180731181784", "aws_region": "us-east-2"},
  "created_at":           "2026-05-20T17:00:00Z",
  "updated_at":           "2026-05-20T19:15:00Z",
  "deleted_at":           null,
  "version":              3,
  "originating_grid_id":  "019e4651-4482-7ef5-ade4-2f38ee3be9e1",

  "data": {
    "entity_id":    "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc101",
    "name":         "samsite-prod-1-opa-compliance",
    "description":  "OPA compliance Lambda for samsite.",
    "function_arn": "arn:aws:lambda:us-east-2:180731181784:function:samsite-prod-1-opa-compliance",
    "runtime":      "nodejs22.x",
    "handler":      "index.handler",
    "memory_size":  128,
    "timeout":      60,
    "tags":         {"Project": "samsite", "Component": "compliance", "Owner": "sam-aydlette"},
    "configuration": {"...plugin-specific blob...": "..."}
  },

  "display": {
    "tap_viz": {
      "shape":    "round-rectangle",
      "colors":   {"fill": "#F2E5C4", "border": "#B89669", "label": "#6E5428"},
      "label":    {"valign": "top", "halign": "center", "position": "outside"},
      "icon_url": "/static/aws_core/icons/aws-lambda.svg",
      "url_id":   "samsite-prod-1-opa-compliance--01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc101"
    }
  }
}
```

The top-level spine field order follows the canonical order defined by
`req-grid-entity-spine-surface`.

### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-grift-envelope-shape-1 | Three Lanes In v0 | Proposed | Envelope structure consists of top-level spine fields, `data`, and `display`. Additional top-level lanes may be added by future specs as demand requires. |
| req-grift-envelope-shape-2 | Lanes Are Ordered | Proposed | Serializers should emit lanes in the order: spine fields (top), `data`, `display`, and any future lanes after. Aids reading. |
| req-grift-envelope-shape-3 | Empty Lanes Are Absent | Proposed | A lane that's not populated for the requested layer is **absent** from the envelope, not present-with-empty-object. |

## Spine Surface Rule
----
RID: `req-grift-envelope-spine-surface`

Status: `In Development`

**Only fields stored on the `Entity` row are surfaced at the top level
of the envelope.** Universal cross-cutting fields stored elsewhere (e.g.
`batch_id` / `flip_map` on BaseModel — see `req-grid-flip-map-3`
"Canonical Object Locality") are *not* surfaced; they live in their
storage lane (`data` in v0).

The canonical set and order of spine fields is defined in
`spec-grid-entity` § Canonical Spine Surface
(`req-grid-entity-spine-surface`). Envelope serializers emit the fields
in that order.

### Status Details

The rule is stricter than "universal fields go flat." Universality is
not the criterion — *storage on the Entity row* is. This keeps the rule
verifiable mechanically (look at the schema, find the row) rather than
semantic (debate which fields are "important enough" to surface).

### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-grift-envelope-spine-1 | Entity-Row Only | Proposed | A field at the top level of an envelope corresponds 1:1 to a field on the `Entity` row, in the canonical order defined by `req-grid-entity-spine-surface`. |
| req-grift-envelope-spine-2 | All Entity Fields Surface | Proposed | Every persisted field on the `Entity` row appears at top level. |
| req-grift-envelope-spine-3 | No Non-Entity Fields At Top | Proposed | Fields stored on BaseModel rows (e.g. `description`, `tags`, `batch_id`, `flip_map`) never appear at top level. |
| req-grift-envelope-spine-4 | Name Is Descriptive, Not An Identifier | Proposed | `name` is human-readable metadata. The stable identifier is `entity_id`. Callers and joins must not depend on `name` immutability. |

## Data Lane Rule
----
RID: `req-grift-envelope-data-lane`

Status: `In Development`

The `data` lane holds **fields stored on the per-model BaseModel row**.
Its shape varies by `entity_type`; callers branch on `entity_type` to
know what to expect inside.

### Implementation

- The fields inside `data` correspond to the per-model class's
  `FIELD_CRUD_SCHEMA` plus the universal BaseModel fields (`description`,
  `batch_id`, `flip_map`).
- `data` contains required `entity_id` and `name` mirrors of the
  top-level values (see [Denormalized Field Mirroring](#denormalized-field-mirroring)).
- For nodes, `data` typically contains: `entity_id` (mirror), `name`
  (mirror), `description`, model-specific scalars, `tags`, model-specific
  JSON blobs, `batch_id`, `flip_map`.
- For edges, `data` typically contains: `entity_id` (mirror), `name`
  (mirror), `description`, `from_entity_id`, `to_entity_id`,
  `edge_type`, `properties`, `batch_id`, `flip_map`.
- `data.entity_type` is **not** present (it's a spine field; surfaces only at top level).

### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-grift-envelope-data-1 | BaseModel Fields Only | Proposed | A field inside `data` corresponds to a field on the per-model BaseModel row. |
| req-grift-envelope-data-2 | Polymorphic By Type | Proposed | The shape of `data` is determined by `entity_type`. Different types have different fields. |
| req-grift-envelope-data-3 | No Spine Fields | Proposed | `entity_type`, `dimensions`, timestamps, `version`, `originating_grid_id` never appear inside `data`. |
| req-grift-envelope-data-4 | Mirrors Required | Proposed | `data.entity_id` and `data.name` MUST appear inside `data`; they MUST equal the top-level values. They are required, not optional. |

## Display Lane Rule
----
RID: `req-grift-envelope-display-lane`

Status: `In Development`

The `display` lane holds **values computed for rendering**, not
persisted. Its sub-keys are **consumer-namespaced** so multiple rendering
contexts can coexist.

### Implementation

- `display` is a dict whose keys are *consumer namespaces* —
  `tap_viz`, and future namespaces such as table panels, info windows,
  or list panels as they emerge.
- The `tap_viz` sub-key is the only consumer namespace populated in v0.
- The shape of `display.tap_viz.*` is governed by
  [`spec-viz-system.md` § Display Hints](../../tap_viz/specs/spec-viz-system.md#display-hints):
  `shape`, `colors {fill, border, label}`, `label {valign, halign, position}`,
  and (computed-not-from-model) `icon_url`, `url_id`.
- The previously flattened layout — where the response had
  `display.colors` instead of `display.tap_viz.colors` — is corrected to
  honor the spec's namespacing (`req-viz-system-display-hints-4` "Viz
  Hints Are Namespaced"). The flat shape was an as-built drift.

### Migration From Existing Extended Layer

The current extended-layer envelope (see `spec-grift-subgraph`
"Canonical Member Shape") promotes `icon_url`, `shape`, and `url_id`
to the top level of the envelope alongside flat `display` contents
(without the `tap_viz` namespace). This spec **moves all of those into
`display.tap_viz.{...}`** when implemented, so the top level remains
strictly spine-only and consumer namespacing is honest.

JS consumers reading `n.icon_url`, `n.shape`, `n.url_id` are updated to
read `n.display.tap_viz.icon_url`, etc. The change is local to the
serializer + a small set of template/JS files.

### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-grift-envelope-display-1 | Consumer-Namespaced | Proposed | `display` contains only consumer-namespaced sub-keys; no flat values directly under `display`. |
| req-grift-envelope-display-2 | Computed Not Stored | Proposed | Values inside `display` are computed at serialization time from `DEFAULT_DISPLAY` + icon resolution + spine data. They are not persisted as such. |
| req-grift-envelope-display-3 | Layout Overrides Composable | Proposed | A future layout may override display hints for a specific projection without changing the underlying model defaults (`req-viz-system-display-hints-6`). Override resolution happens before envelope serialization. |
| req-grift-envelope-display-4 | Flat-Field Promotion Retired | Proposed | The top-level `icon_url`, `shape`, `url_id` fields and the flat `display.colors`/`display.label`/etc. layout are retired; the namespaced `display.tap_viz.*` shape is canonical. |

## Denormalized Field Mirroring
----
RID: `req-grift-envelope-denormalization`

Status: `In Development`

`entity_id` and `name` are stored in two places by design:

- `entity_id`: `Entity.id` (primary key) and per-model `<Model>.id` (also
  the primary key, same UUID — they share identity via the OneToOne).
- `name`: `Entity.name` (the canonical spine value) and per-model
  `<Model>.name` (the per-model field; `BaseModel.save()` syncs to
  `Entity.name`).

Other fields have a single home and never duplicate.

### Implementation

- The envelope mirrors this storage shape: `entity_id` and `name` appear
  at both the top level AND inside `data`.
- **Top-level is canonical.** When a consumer needs to read these
  fields, it reads top-level. The mirror inside `data` exists for two
  practical reasons:
  - **Storage-shape fidelity** — `data` shows what the per-model row
    actually contains. Drop the mirror and `data` would lie about its
    storage.
  - **Round-trip writes** — the envelope shape is also the write-payload
    shape. Keeping the mirror lets callers pass the same shape back
    through the write API without shuffling fields between buckets.
- **Mirrors must equal top-level values** on a well-formed envelope.
  Inequality is a validation error, not a silent override.

### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-grift-envelope-denorm-1 | Two Fields Only | Proposed | Only `entity_id` and `name` are mirrored. Description, dimensions, timestamps, etc. each have a single envelope location. |
| req-grift-envelope-denorm-2 | Top-Level Canonical | Proposed | Consumers reading these fields read from top-level. The convention is documented; ad hoc reads from `data` are valid but discouraged. |
| req-grift-envelope-denorm-3 | Mirror Equality Enforced | Proposed | When both locations are present, they must hold identical values. Envelope validation rejects mismatches. |
| req-grift-envelope-denorm-4 | Future Mirrors Justified | Proposed | Adding a new mirrored field requires explicit storage-shape justification (the field is denormalized in storage too). Mirrors do not exist as a convenience pattern. |

## Edge Uniformity
----
RID: `req-grift-envelope-edge-uniformity`

Status: `In Development`

Edges use the same envelope as nodes. The polymorphism is entirely in
`data.*`.

### Example

```json
{
  "entity_id":   "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc201",
  "entity_type": "edge",
  "name":        "ddqsj3lyxiv8s.cloudfront.net ROUTES_TRAFFIC samsite-prod-1",
  "dimensions":  {"cloud": "aws", "aws_account": "180731181784", "aws_region": "global"},
  "created_at":  "2026-05-20T17:00:00Z",
  "updated_at":  "2026-05-20T17:00:00Z",
  "deleted_at":  null,
  "version":     1,
  "originating_grid_id": "019e4651-4482-7ef5-ade4-2f38ee3be9e1",

  "data": {
    "entity_id":      "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc201",
    "name":           "ddqsj3lyxiv8s.cloudfront.net ROUTES_TRAFFIC samsite-prod-1",
    "description":    "",
    "from_entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc101",
    "to_entity_id":   "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc102",
    "edge_type":      "ROUTES_TRAFFIC",
    "properties":     {}
  },

  "display": {
    "tap_viz": { /* edge display hints */ }
  }
}
```

### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-grift-envelope-edge-1 | Same Envelope Shape | Proposed | Edges and nodes share the same envelope structure: same top-level spine, same `data` / `display` lanes. |
| req-grift-envelope-edge-2 | edge_type Inside Data | Proposed | `edge_type` lives inside `data`, not at top level. It's a per-Edge-row field. |
| req-grift-envelope-edge-3 | edge_type Immutable | Proposed | `edge_type` remains immutable post-creation per existing `Edge` model guard (`tap_grid/services.py:325-328`). |
| req-grift-envelope-edge-4 | Edge Name Is Descriptive | Proposed | Edge names follow a convention (typically `"{from_label_or_id} {edge_type} {to_label_or_id}"` for collector-emitted edges) but are not stable identifiers. The stable identifier is `entity_id`. |
| req-grift-envelope-edge-5 | No `from_name`/`to_name` At Top | Proposed | Computed endpoint labels move into `display.tap_viz.from_label` / `to_label` (or similar). The current flat `from_name` / `to_name` fields on edge envelopes are retired in favor of namespacing under `display`. |

## Envelope Validation
----
RID: `req-grift-envelope-validation`

Status: `In Development`

API entrypoints accepting envelopes as write payloads validate
structural invariants before dispatching to the service layer. The
canonical implementation is `tap_grid.grift.envelope.parse_envelope_for_write`;
no API caller routes through it yet (no envelope-shaped write endpoint
exists in v0), but the function is the foundation any future
envelope-shaped write API uses rather than reinventing the
validate-and-split logic.

### Implementation

A canonical envelope-parser function lives in `tap_grid.grift` (the
implementation home per `req-grift-subgraph-impl`). Pseudocode:

```python
def parse_envelope_for_write(env: dict) -> SplitPayload:
    """Split an envelope into Entity-spine and BaseModel-row write payloads.

    Validates:
      - Required top-level spine fields are present.
      - `data` is present, is a dict.
      - Denormalized mirrors (entity_id, name) inside `data` equal their
        top-level values.
      - `display` is ignored on write — discarded after split.

    Returns:
      SplitPayload(entity_payload={...spine...}, model_payload={...data...})

    Raises:
      EnvelopeValidationError on structural or mirror-mismatch errors.
    """
```

### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-grift-envelope-validation-1 | Mirror Equality Check | Proposed | Validation rejects envelopes whose `data.entity_id` / `data.name` differ from top-level values. |
| req-grift-envelope-validation-2 | Display Discarded On Write | Proposed | Validation discards `display` on the write path; rendering metadata is read-only. |
| req-grift-envelope-validation-3 | Canonical Home In tap_grid.grift | Proposed | The split-and-validate function lives in `tap_grid.grift` alongside the existing serializers, mirroring `req-grift-subgraph-impl`. |

## Layer Mapping
----
RID: `req-grift-envelope-layer-mapping`

Status: `In Development`

The envelope composes with the `lite` / `full` / `extended` return
layers defined in `spec-grift-subgraph`. Each layer is defined by which
lanes are present.

| Layer | Top-level spine | `data` | `display` | Notes |
| --- | :---: | :---: | :---: | --- |
| `lite` | ✓ | — | — | Identity, type, name, dimensions, timestamps. No domain data. Fast graph scans, neighborhood traversals. |
| `full` | ✓ | ✓ | — | Adds the complete per-model `data` block. Canonical interchange shape. |
| `extended` | ✓ | ✓ | ✓ | Adds rendering hints. Panel/viewer use. |

### Implementation Notes

- `full` returns *everything* in `data` — every persisted field on the
  per-model row, no exclusions. Make-it-work demands accepting that
  this may be a lot of data for some entity types (e.g. AWS resources
  collected via boto3 carry a lossless `configuration` JSON blob that
  can run 5–50 KB or more). That's fine for v0.
- A future per-field cost-tier mechanism is named in
  [Future](#future) below; until it lands, callers that want a smaller
  payload use `lite`.

### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-grift-envelope-layer-1 | Lite Is Spine-Only | Proposed | `lite` envelopes contain only the top-level spine; `data` and `display` lanes are absent. |
| req-grift-envelope-layer-2 | Full Is Spine + Data | Proposed | `full` envelopes populate every persisted field on the per-model row inside `data`. No exclusions. |
| req-grift-envelope-layer-3 | Extended Adds Display | Proposed | `extended` envelopes populate `data` (as in `full`) plus `display`. |
| req-grift-envelope-layer-4 | Layer Composition Is Cumulative | Proposed | Each higher layer adds lanes; no layer removes or redefines lanes from a lower layer. Mirrors `spec-grift-subgraph` "Layering Rule". |

## Supersedes Prior Member Shape
----
RID: `req-grift-envelope-supersedes`

Status: `In Development`

When implemented, this spec supersedes specific sections of
`spec-grift-subgraph.md` that define the per-member shape.

### Sections Superseded

- `spec-grift-subgraph` § "Canonical Member Shape" — the `{entity, node}`
  shape for nodes and `{entity, edge}` shape for edges is replaced by
  the envelope defined here.
- `spec-grift-subgraph` § "Lite Member Guidance" — the flat `lite` member
  shape is replaced by the envelope-with-spine-only-lane definition in
  this spec.
- `spec-grift-subgraph` § "Presentation Separation" — the principle is
  preserved (presentation stays out of canonical graph data) but the
  implementation moves to the `display` lane within the envelope rather
  than living as flat top-level fields.

### Sections Retained

The following sections of `spec-grift-subgraph` are unchanged:

- "Subgraph Shape" — the outer `{nodes: [], edges: []}` container.
- "Return Layers" — the `lite`/`full`/`extended` concept (this spec
  defines how envelopes compose with each).
- "Wrapper Envelopes" — search/pagination wrappers around a subgraph.
- "Ordering" — array order expresses graph member order.
- "Implementation Home" — canonical serializers live in `tap_grid.grift`.

### Reconciliation

When this spec moves from `Proposed` to `Implemented`, the superseded
sections of `spec-grift-subgraph.md` are updated in the same change
to either remove or rewrite them with explicit cross-references to
this spec, per the project's no-messy-specs discipline.

### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-grift-envelope-supersedes-1 | Explicit Supersession Recorded | Proposed | This spec names the exact sections of `spec-grift-subgraph` that it replaces. |
| req-grift-envelope-supersedes-2 | Reconciliation On Implementation | Proposed | Moving requirements in this spec from `Proposed` to `Implemented` requires same-change updates to `spec-grift-subgraph` to remove or rewrite superseded sections. |
| req-grift-envelope-supersedes-3 | Subgraph Outer Shape Preserved | Proposed | The `{nodes: [], edges: []}` outer container, the layer concept, the implementation home, and the wrapper-envelope contract are unchanged. |

## Future

- **Additional top-level lanes for history, provenance, perspectives,
  alternative views, etc.** The envelope shape is extensible; new
  top-level lanes can be added by demand-driven specs without breaking
  v0 callers. FLIP / `batch_id` / history embedding all become candidates
  once there's a real need. The exact naming, contents, and timing will
  be settled by those future specs.
- **Per-field cost-tier markers on BaseModel.** A way to flag specific
  per-model fields as "heavy" so they can be excluded from default
  `full` responses. The current motivating example is `configuration`
  on plugin-specific collected resources (the boto3 collector stores a
  lossless 5–50 KB JSON blob there), but the mechanism should be
  field-agnostic so any per-model field can be marked. Until this
  lands, callers wanting a smaller payload use `lite`.
- **Edge denormalization into the node envelope.** In principle, the
  envelope structure could be extended to embed a node's adjacent edges
  inline (e.g. as a separate top-level lane) to compress
  hub-and-spoke graph reads into a single envelope. We don't have a
  good reason to do this today and it would meaningfully complicate the
  shape, but if a future workload genuinely needs the compression
  (huge fan-outs, hot adjacency reads in a tight loop) this is where
  the affordance would land.
- **JSON Schema composition + shipping schemas to clients.** TAP
  already has dual schemas: Entity has its own schema and every
  BaseModel publishes `FIELD_CRUD_SCHEMA` / `FIELD_VALIDATION_SCHEMA`.
  Composing those into a per-envelope JSON Schema is largely a
  serialization exercise — entity-spine schema + the per-type model
  schema bound to `data` = the full envelope contract for that
  `entity_type`. With that composition built, TAP could *ship the
  schema to clients alongside (or instead of) the data*, so client
  code can validate, generate types, build forms, etc. Genuinely
  interesting affordance once we need it.
- **Remove `originating_grid_id`.** The field was added in anticipation
  of cross-grid identity reconciliation that we have not actually
  needed in single-grid v0 work — premature optimization before we knew
  to look out for it. Tracked here so a future envelope or entity
  cleanup pass can pick it up. See also `spec-grid-entity` § Canonical
  Spine Surface Future.
- **External HTTP API surface.** If/when TAP exposes a public HTTP API,
  the JSON:API-or-similar transformation happens at the HTTP boundary,
  layered over the internal envelope. No change to this spec required.
- **JS-side envelope-consumer library.** As of the v0 envelope rollout
  every panel/JS file that reads a TAP graph response repeats a small
  set of accessor patterns. Capture them as a future TAP JS library once
  there's enough demand to factor them out — `make-it-work` means we
  carry the small repetition for now and identify the surface
  organically. Capabilities surfaced so far during real-world JS
  changes:

  1. **Field accessors** — `env.entity_id`, `env.name`,
     `env.data?.<field>`, `env.display?.tap_viz?.<field>`. Today each
     consumer hand-writes `(env.display || {}).tap_viz || {}` chains.
  2. **Envelope → Cytoscape mapping** — `envelopeToCytoscapeNode(env)`
     and `envelopeToCytoscapeEdge(env)`. Panel-graph.js currently builds
     this inline; same pattern exists across any cytoscape-host panel.
  3. **Display-hint applicator** — taking `display.tap_viz.colors`,
     `display.tap_viz.label`, `display.tap_viz.shape` and producing
     either Cytoscape style overrides or table cell styling.
  4. **Endpoint-label resolver** — `from_label` / `to_label` reads with
     fallback to truncated `entity_id` when labels are absent.
  5. **Lane presence checks** — "does this envelope carry `data`?"
     i.e. layer-aware reads to determine if a code path can safely
     access `env.data.<field>` or needs to refetch at a higher layer.
  6. **Mirror-equality assertion** — client-side sanity check that
     `env.entity_id === env.data?.entity_id` and `env.name ===
     env.data?.name`. Useful as a dev-only guard.

  When the library lands, those become its starting API. Until then,
  add to this list whenever a new accessor pattern repeats across two
  or more consumers — that's the demand signal.

## Status Vocabulary

Per the TAP convention used elsewhere in `tap_grid/specs/`:

- `Proposed` — Drafted but not yet approved for build.
- `Approved for Development` — Greenlit to implement; not yet started.
- `In Development` — Actively being built.
- `Implemented` — Behavior is live and the spec describes the as-built.
- `Deprecated` — Scheduled for removal.
