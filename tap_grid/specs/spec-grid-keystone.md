# Grid Keystone Specification

## Philosophy

A **keystone** is a node that says what this TAP instance *is*: what it models, what it's for, where it came from, and where to start. It exists so that anyone landing cold — a human, or an agent with no prior context — can read the grid and understand the instance instead of having to be told. The recurring failure it fixes: instance context lives in someone's head, or scattered across specs and chat history, and has to be re-explained every session. Put it on the grid as a node and it becomes discoverable, queryable, and versioned like everything else.

The name is borrowed from the keystone of an arch — the stone that locks the structure and tells you the whole thing is intentional. Here it's the stone that anchors the *meaning* of the grid.

A keystone is **self-describing**. Rather than force every instance into one fixed context schema — an approach that either over-constrains (you can't say the thing you need to) or rots into an unvalidated junk drawer — each keystone carries both its context data (`context_json`) *and the JSON Schema that defines and documents that data* (`context_schema_json`). The schema travels with the data: a reader gets the values and, in the same node, the legend for what every value means (via the schema's `description` keywords). The instance's creator owns the shape; the platform owns only the envelope.

This keeps two of our standing rules satisfied at once. "JSON formats need a schema, validated at load": the keystone's *outer* shape is fixed and validated, and its *open* inner field is made safe by requiring it to carry and conform to its own schema. "Declarative shapes over code / readable by agents without code access": an outside agent reads one node and has both the facts and their meaning, no source required.

## Home: the spine

The keystone lives in `tap_grid` — the spine — alongside the grid's other **infrastructure entity types** (`edge`, `dimension`, `search`, `batch` are all spine-resident `BaseModel`s). The rule that *domain* models live in plugins is intact; keystone is not a domain model, it's instance-meta infrastructure, so it belongs with its peers in core. The reason it must be core rather than a plugin: instance self-description has to be available in *every* TAP instance regardless of which domain plugins are loaded, and must not vanish because a plugin was de-registered — a keystone in a de-registerable plugin could take the instance's own identity down with it. The spine is the one place guaranteed present.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Discoverable | Instance context is a queryable node, not tribal knowledge or scattered prose. |
| 2. | Self-Describing | Each keystone ships its context *and* the JSON Schema documenting that context. |
| 3. | Creator-Owned Shape | The platform fixes the envelope; the creator defines the context schema, as loose or strict as they like. |
| 4. | Validated at Load | The context schema must be a valid JSON Schema, and the context must conform to it — fail loud. |
| 5. | Spine-Resident | Defined in `tap_grid` so it is plugin-independent and never de-registerable. |
| 6. | Deterministic Read Order | Multiple keystones are allowed; the oldest by entity creation is the foundational read. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-keystone-model | [Keystone Model](#keystone-model) | Implemented | `keystone` BaseModel in `tap_grid`; fields name, description, context_json, context_schema_json |
| req-grid-keystone-spine-home | [Spine Home](#spine-home) | Implemented | Defined in core `tap_grid` alongside edge/dimension/search/batch; plugin-independent, non-de-registerable |
| req-grid-keystone-self-describing | [Self-Describing Context](#self-describing-context) | Implemented | `context_json` paired with `context_schema_json` (a JSON Schema) in the same node |
| req-grid-keystone-validation | [Load-Time Validation](#load-time-validation) | Implemented | Schema is meta-valid; context conforms; required-pairing; via the whole-record `validate()` hook |
| req-grid-keystone-multiplicity | [Multiplicity & Read Order](#multiplicity--read-order) | Implemented | No singleton enforcement; read oldest-first by entity `created_at` |
| req-grid-keystone-discovery | [Discovery Convention](#discovery-convention) | Implemented | Documented "read the keystone first" rule for agents/humans |
| req-grid-keystone-edges | [Edges](#edges) | Deferred | No platform-defined edges in v0; creators may add their own |

## Requirements

### Keystone Model
----
RID: `req-grid-keystone-model`
Status: `Implemented`

`Keystone` is a `BaseModel` subclass (`ENTITY_TYPE = "keystone"`) defined in `tap_grid`. Every instance gets an Entity spine row, history, and is reachable through the service layer, GRIFT, Gryphon, and edges like any other node. Fields:

- **`name`** — short identifier for the instance/subject (e.g. "Samsite"). Drives `get_name()`.
- **`description`** — human prose, read top-down: the "what is this and why" narrative. A guaranteed-readable entry even when the structured context is sparse.
- **`context_json`** — the structured context: an open JSON object whose shape the creator chooses.
- **`context_schema_json`** — a JSON Schema (Draft 2020-12) that defines *and documents* `context_json`. Its per-property `description` keywords are the "context for the context."

The platform defines no required keys inside `context_json` — keeping the model generic (no consumer vocabulary baked into the spine). Typical creator-chosen keys: `purpose`, `subject`, `sources` (provenance), `fidelity`, `entry_points`, `scope`. Those live in the instance, never in this contract.

### Spine Home
----
RID: `req-grid-keystone-spine-home`
Status: `Implemented`

The model is defined in `tap_grid`, not a plugin, joining the spine's existing infrastructure entity types (`edge`, `dimension`, `search`, `batch`). It registers its entity type through the standard `BaseModel.__init_subclass__` → `register_entity_type` path at import time; no plugin manifest entry is involved. Spine residence is reserved for grid infrastructure/meta types like these; domain models still live in plugins.

### Self-Describing Context
----
RID: `req-grid-keystone-self-describing`
Status: `Implemented`

`context_json` and `context_schema_json` are a pair shipped in the same node. The schema is a real JSON Schema, not freeform prose — so it both validates the data and documents it (every property carries a `description`), and any standard tool or agent already understands it. The schema is the creator's: it may be as permissive as `{"type": "object", "additionalProperties": true}` or as strict as they want. The platform never dictates the inner shape — only that, if there is context, there is a schema describing it.

### Load-Time Validation
----
RID: `req-grid-keystone-validation`
Status: `Implemented`

Validation runs through the whole-record `validate()` hook (`full_validate()`), so it fires on every service-layer / GRIFT write — fail loud, no silent bad context:

1. If `context_json` is non-empty, `context_schema_json` MUST be present (you must describe your context).
2. If `context_schema_json` is present, it MUST be a valid JSON Schema (`Draft202012Validator.check_schema`).
3. If `context_schema_json` is present, `context_json` MUST validate against it.

Per-field `FIELD_VALIDATION_SCHEMA` independently asserts both context fields are objects; the cross-field conformance check is the `validate()` hook's job.

### Multiplicity & Read Order
----
RID: `req-grid-keystone-multiplicity`
Status: `Implemented`

There is no single-keystone enforcement (the grid has no single-instance constraint mechanism today, and forcing one is not worth it). Multiple keystones are valid and useful — later ones layer refinements or describe additional subjects. The **convention is to read oldest-first**, ordered by the entity's `created_at` (a spine field — intrinsic, set once at creation via `auto_now_add`, and inviolable on the grid). The oldest keystone is the foundational instance context; newer ones are read after it as additional layers. Updating the foundational context means editing the oldest node in place (its history captures the change), not superseding it with a newer node.

Canonical Gryphon read:

```
MATCH (k:keystone) RETURN k ORDER BY k.created_at ASC
```

### Discovery Convention
----
RID: `req-grid-keystone-discovery`
Status: `Implemented`

A keystone nobody reads is just another node. The convention — recorded in `AGENTS.md` and `CLAUDE.md` — is that when an agent or human needs to know what this instance is, they query the keystones (oldest-first) **before** asking. This closes the loop: the node holds the context, and the reader knows to look.

### Edges
----
RID: `req-grid-keystone-edges`
Status: `Backlog`

v0 defines no platform edges from the keystone. The arch metaphor invites `DESCRIBES`-style edges (keystone → the boundary / account / projection it anchors), making the modeled system reachable by walking out from the keystone — but which anchors matter is instance-specific, so this is left to creators rather than baked into the platform. Pointers to entry points live in `context_json` instead. May graduate to a platform edge type once a consistent need emerges.
