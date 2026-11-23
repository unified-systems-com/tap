# GRIFT v0 Specification

## Philosophy

GRIFT, the Grid Interchange Format, is TAP's JSON-based interchange format for moving graph data between files and grids. GRIFT v0 is intentionally small, strict, and practical: it should be easy to validate, easy to diff, and sufficient to refactor plugin seed data such as the LOTR dataset into portable JSON files.

GRIFT's node and edge lanes are full-object interchange: they do not describe patches, history replay, or FLIP state. The write sections (`req-grift-write-sections`, Proposed) add three more ways to write a record: insert only, update the fields sent, and replace whole. They carry enough canonical information for an importer to choose its own create, replace, upsert, or skip behavior while preserving universal entity identity through `entity_id`. GRIFT's removal lanes are explicit identity-targeted operations, declared separately from node and edge upserts.

GRIFT also carries an optional **optimistic concurrency** contract. Any mutating target — an upsert envelope or a removal target — may declare the version of the local entity it expects to act on. The importer enforces that expectation atomically: if the local version has moved on, the conflicting batch fails loud rather than overwriting state the author did not see. This is the same model Kubernetes uses with `resourceVersion`, Postgres SERIALIZABLE uses with `40001 serialization_failure`, and event-sourcing frameworks use with `entity_expected_version` on aggregate writes. The author's mental model is "apply if the grid still matches my plan, else tell me." Senders that need to recover from a conflict re-read, re-plan, and resubmit.

## Goals

|    |              |                                                                 |
| :---: | ---       | ---                                                             |
| 1. | Portable      | TAP entities can be exported, shared, and re-imported as JSON   |
| 2. | Strict        | Unknown keys and malformed objects are rejected                 |
| 3. | Canonical     | Identity is preserved through explicit `entity_id` values       |
| 4. | Batch-Aware   | Imports can preserve originating batch structure and metadata   |
| 5. | Lightweight   | v0 excludes history, FLIP transport, and semantic dedupe logic |

## Terminology

- GRIFT document: the complete top-level JSON object
- metadata: the top-level GRIFT metadata object
- reserved object: the top-level `_reserved` object reserved for future extension
- entity envelope: the canonical entity metadata wrapper used by batch, node, and edge records
- batch container: one item in the top-level `batches` array
- batch entity: the `batch_entity` envelope for the serialized batch itself
- batch node: the `batch_node` payload for the serialized batch model
- node object: one item in a batch `nodes` array, consisting of `entity` plus `node`
- edge object: one item in a batch `edges` array, consisting of `entity` plus `edge`
- node payload: the `node` object containing typed full-object node data
- edge payload: the `edge` object containing typed full-object edge data and explicit endpoints
- removal section: an optional batch-level `deletes` or `purges` object containing explicit removal targets
- removal target: one item in a removal section's `edges` or `nodes` array, consisting of `entity_id`, `entity_type`, `reason`, and an optional `entity_expected_version`
- expected version: an optional integer on a mutating target (upsert envelope or removal target) declaring the local `Entity.version` the sender believes is current; a mismatch at execution time aborts the batch with a `entity_version_conflict` issue
- version conflict: the importer's detection that a mutating target's `entity_expected_version` does not match the local `Entity.version` at the moment of execution

## JSON Schemas

GRIFT v0 should publish machine-readable JSON Schemas in addition to prose requirements.

These schemas are normative for structure and basic field validation. Model-specific node, batch, and edge-property validation remains type-driven and is defined by the importing TAP installation's model registry and field contract.

### `GriftEntityEnvelope`

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["entity_id", "entity_type", "dimensions"],
  "properties": {
    "entity_id": {
      "type": "string",
      "format": "uuid"
    },
    "entity_type": {
      "type": "string",
      "minLength": 1
    },
    "name": {
      "type": "string",
      "minLength": 1
    },
    "dimensions": {
      "type": "object",
      "additionalProperties": {
        "type": "string"
      }
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    },
    "updated_at": {
      "type": "string",
      "format": "date-time"
    },
    "deleted_at": {
      "oneOf": [
        {
          "type": "null"
        },
        {
          "type": "string",
          "format": "date-time"
        }
      ]
    },
    "entity_expected_version": {
      "type": "integer",
      "minimum": 1,
      "description": "Optional optimistic-concurrency declaration: the local Entity.version the sender expects to act on. Enforced by the importer at execution time. Omitted means 'don't check' (legacy / first-write behavior)."
    }
  }
}
```

### `GriftNodeObject`

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["entity", "node"],
  "properties": {
    "entity": {
      "$ref": "#/$defs/GriftEntityEnvelope"
    },
    "node": {
      "type": "object"
    },
    "retirement": {
      "$ref": "#/$defs/GriftRetirement"
    }
  }
}
```

### `GriftEdgePayload`

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["from_entity_id", "to_entity_id", "edge_type", "properties"],
  "properties": {
    "from_entity_id": {
      "type": "string",
      "format": "uuid"
    },
    "to_entity_id": {
      "type": "string",
      "format": "uuid"
    },
    "edge_type": {
      "type": "string",
      "minLength": 1
    },
    "properties": {
      "type": "object"
    }
  }
}
```

### `GriftEdgeObject`

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["entity", "edge"],
  "properties": {
    "entity": {
      "$ref": "#/$defs/GriftEntityEnvelope"
    },
    "edge": {
      "$ref": "#/$defs/GriftEdgePayload"
    },
    "retirement": {
      "$ref": "#/$defs/GriftRetirement"
    }
  }
}
```

### `GriftBatchContainer`

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["batch_entity", "batch_node", "nodes", "edges"],
  "properties": {
    "batch_entity": {
      "$ref": "#/$defs/GriftEntityEnvelope"
    },
    "batch_node": {
      "type": "object"
    },
    "nodes": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/GriftNodeObject"
      }
    },
    "edges": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/GriftEdgeObject"
      }
    },
    "deletes": {
      "$ref": "#/$defs/GriftDeletesSection"
    },
    "purges": {
      "$ref": "#/$defs/GriftPurgesSection"
    },
    "contents": {
      "$ref": "#/$defs/GriftContents"
    }
  }
}
```

### `GriftRetirement`

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["retired_at", "batch_id", "reason", "metadata"],
  "properties": {
    "retired_at": { "type": "string", "format": "date-time" },
    "batch_id": { "type": ["string", "null"], "format": "uuid" },
    "reason": { "type": ["string", "null"], "minLength": 1 },
    "metadata": { "type": "object" }
  }
}
```

### `GriftContents`

```json
{
  "type": "object",
  "required": ["tombstones"],
  "properties": {
    "tombstones": {
      "type": "object",
      "additionalProperties": false,
      "required": ["included", "nodes", "edges"],
      "properties": {
        "included": { "type": "boolean" },
        "nodes": { "type": "integer", "minimum": 0 },
        "edges": { "type": "integer", "minimum": 0 }
      }
    }
  },
  "additionalProperties": {
    "type": "object",
    "required": ["included"],
    "properties": { "included": { "type": "boolean" } }
  }
}
```

### `GriftRemovalTarget`

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["entity_id", "entity_type", "reason"],
  "properties": {
    "entity_id": {
      "type": "string",
      "format": "uuid"
    },
    "entity_type": {
      "type": "string",
      "minLength": 1
    },
    "reason": {
      "type": "string",
      "minLength": 1
    },
    "entity_expected_version": {
      "type": "integer",
      "minimum": 1,
      "description": "Optional optimistic-concurrency declaration: the local Entity.version the sender expects to remove. Enforced by the importer at execution time. Omitted means 'don't check'."
    }
  }
}
```

### `GriftDeletesSection`

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["on_missing", "on_tombstoned", "edges", "nodes"],
  "properties": {
    "on_missing": {
      "enum": ["error", "warn", "ignore"]
    },
    "on_tombstoned": {
      "enum": ["error", "warn", "ignore"]
    },
    "edges": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/GriftRemovalTarget"
      }
    },
    "nodes": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/GriftRemovalTarget"
      }
    }
  }
}
```

### `GriftPurgesSection`

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["on_missing", "edges", "nodes"],
  "properties": {
    "on_missing": {
      "enum": ["error", "warn", "ignore"]
    },
    "edges": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/GriftRemovalTarget"
      }
    },
    "nodes": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/GriftRemovalTarget"
      }
    }
  }
}
```

### `GriftDocument`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:tap:grift:v0:document",
  "type": "object",
  "additionalProperties": false,
  "required": ["metadata", "_reserved", "batches"],
  "properties": {
    "metadata": {
      "type": "object",
      "additionalProperties": false,
      "required": ["grift_version"],
      "properties": {
        "grift_version": { "type": "string", "minLength": 1 },
        "spine_version": { "type": "integer", "minimum": 1 },
        "type_versions": { "type": "object", "additionalProperties": { "type": "integer", "minimum": 1 } }
      },
      "allOf": [
        {
          "if": { "properties": { "grift_version": { "const": "0" } }, "required": ["grift_version"] },
          "then": { "properties": { "spine_version": false, "type_versions": false } }
        },
        {
          "if": { "properties": { "grift_version": { "const": "1" } }, "required": ["grift_version"] },
          "then": { "required": ["spine_version", "type_versions"] }
        }
      ]
    },
    "_reserved": {
      "type": "object"
    },
    "batches": {
      "type": "array",
      "items": {
        "$ref": "#/$defs/GriftBatchContainer"
      }
    }
  },
  "$defs": {
    "GriftEntityEnvelope": {
      "type": "object",
      "additionalProperties": false,
      "required": ["entity_id", "entity_type", "dimensions"],
      "properties": {
        "entity_id": {
          "type": "string",
          "format": "uuid"
        },
        "entity_type": {
          "type": "string",
          "minLength": 1
        },
        "name": {
          "type": "string",
          "minLength": 1
        },
        "dimensions": {
          "type": "object",
          "additionalProperties": {
            "type": "string"
          }
        },
        "created_at": {
          "type": "string",
          "format": "date-time"
        },
        "updated_at": {
          "type": "string",
          "format": "date-time"
        },
        "deleted_at": {
          "oneOf": [
            {
              "type": "null"
            },
            {
              "type": "string",
              "format": "date-time"
            }
          ]
        },
        "entity_expected_version": {
          "type": "integer",
          "minimum": 1,
          "description": "Optional optimistic-concurrency declaration: the local Entity.version the sender expects to act on. Enforced by the importer at execution time."
        }
      }
    },
    "GriftNodeObject": {
      "type": "object",
      "additionalProperties": false,
      "required": ["entity", "node"],
      "properties": {
        "entity": {
          "$ref": "#/$defs/GriftEntityEnvelope"
        },
        "node": {
          "type": "object"
        }
      }
    },
    "GriftEdgePayload": {
      "type": "object",
      "additionalProperties": false,
      "required": ["from_entity_id", "to_entity_id", "edge_type", "properties"],
      "properties": {
        "from_entity_id": {
          "type": "string",
          "format": "uuid"
        },
        "to_entity_id": {
          "type": "string",
          "format": "uuid"
        },
        "edge_type": {
          "type": "string",
          "minLength": 1
        },
        "properties": {
          "type": "object"
        }
      }
    },
    "GriftEdgeObject": {
      "type": "object",
      "additionalProperties": false,
      "required": ["entity", "edge"],
      "properties": {
        "entity": {
          "$ref": "#/$defs/GriftEntityEnvelope"
        },
        "edge": {
          "$ref": "#/$defs/GriftEdgePayload"
        }
      }
    },
    "GriftBatchContainer": {
      "type": "object",
      "additionalProperties": false,
      "required": ["batch_entity", "batch_node", "nodes", "edges"],
      "properties": {
        "batch_entity": {
          "$ref": "#/$defs/GriftEntityEnvelope"
        },
        "batch_node": {
          "type": "object"
        },
        "nodes": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/GriftNodeObject"
          }
        },
        "edges": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/GriftEdgeObject"
          }
        },
        "deletes": {
          "$ref": "#/$defs/GriftDeletesSection"
        },
        "purges": {
          "$ref": "#/$defs/GriftPurgesSection"
        }
      }
    },
    "GriftRemovalTarget": {
      "type": "object",
      "additionalProperties": false,
      "required": ["entity_id", "entity_type", "reason"],
      "properties": {
        "entity_id": {
          "type": "string",
          "format": "uuid"
        },
        "entity_type": {
          "type": "string",
          "minLength": 1
        },
        "reason": {
          "type": "string",
          "minLength": 1
        },
        "entity_expected_version": {
          "type": "integer",
          "minimum": 1,
          "description": "Optional optimistic-concurrency declaration: the local Entity.version the sender expects to remove. Enforced by the importer at execution time."
        }
      }
    },
    "GriftDeletesSection": {
      "type": "object",
      "additionalProperties": false,
      "required": ["on_missing", "on_tombstoned", "edges", "nodes"],
      "properties": {
        "on_missing": {
          "enum": ["error", "warn", "ignore"]
        },
        "on_tombstoned": {
          "enum": ["error", "warn", "ignore"]
        },
        "edges": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/GriftRemovalTarget"
          }
        },
        "nodes": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/GriftRemovalTarget"
          }
        }
      }
    },
    "GriftPurgesSection": {
      "type": "object",
      "additionalProperties": false,
      "required": ["on_missing", "edges", "nodes"],
      "properties": {
        "on_missing": {
          "enum": ["error", "warn", "ignore"]
        },
        "edges": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/GriftRemovalTarget"
          }
        },
        "nodes": {
          "type": "array",
          "items": {
            "$ref": "#/$defs/GriftRemovalTarget"
          }
        }
      }
    }
  }
}
```

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grift-format | [Document Format](#document-format) | Implemented | Top-level GRIFT JSON document |
| req-grift-envelope | [Entity Envelope](#entity-envelope) | Implemented | Canonical entity metadata carried in every object |
| req-grift-batch | [Batch Container](#batch-container) | Implemented | Serialized TAP batches wrap nodes and edges |
| req-grift-node | [Node Object](#node-object) | Implemented | Full-object node interchange contract |
| req-grift-edge | [Edge Object](#edge-object) | Implemented | Full-object edge interchange contract |
| req-grift-edge-identity-surface | [Edge Identity Document Surface](#edge-identity-document-surface) | Implemented | The three document shapes edge identity adds: an endpoint named by type and natural key, a removal target named by edge identity, and the batch `edge_cases` section carrying authority claims |
| req-grift-validation | [Validation Rules](#validation-rules) | Implemented | Strict schema and sanity rules |
| req-grift-seed-ids | [Seed Data ID Convention](#seed-data-id-convention) | Deprecated | Superseded by [spec-grid-uuid-selection.md](spec-grid-uuid-selection.md) and [spec-grift-seed-ids-real-uuid7.md](spec-grift-seed-ids-real-uuid7.md) |
| req-grift-order | [Canonical Export Ordering](#canonical-export-ordering) | Backlog | Export ordering (no exporter yet) |
| req-grift-stored-files | [Stored Files](#stored-files) | Backlog | How the bytes of a stored file follow its node from one grid to another; GRIFT carries the node, not the bytes |
| req-grift-import-deletes | [Imperative Removal Sections](#imperative-removal-sections) | Approved for Development | Explicit batch-level delete and purge operations; not desired-state reconciliation |
| req-grift-concurrency-version | [Optimistic Concurrency Via Expected Version](#optimistic-concurrency-via-expected-version) | Implemented | Optional `entity_expected_version` on any mutating target declares the local `Entity.version` the sender expects; the importer aborts the batch on mismatch |
| req-grift-retirement | [Retirement Block](#retirement-block) | Implemented | A node or edge object may carry the entity's retirement in its source grid as plain data: retired-at time, retiring batch id, reason, metadata |
| req-grift-contents | [Contents Declaration](#contents-declaration) | Implemented | A batch declares what kinds of record it carries; the importer verifies the declaration against the batch and decides whether it accepts each kind |
| req-grift-export | [Grid Export](#grid-export) | Implemented | `manage.py export_grift` serialises a grid, retired rows included, optionally narrowed by dimension, batch or reachability |
| req-grift-header-versions | [Version Declarations In The Header](#version-declarations-in-the-header) | In Development | `metadata.spine_version` and `metadata.type_versions`: the spine version and the version of each type the document carries, beside `grift_version` |
| req-grift-write-sections | [Write Sections](#write-sections) | Proposed | Optional `inserts`, `updates` and `replaces` sections beside `nodes` and `edges`, for nodes and edges |
| req-grift-insert-only | [Insert-Only Records](#insert-only-records) | Proposed | A record in `inserts` is created if absent and leaves an existing row untouched |
| req-grift-partial-update | [Updates Without Required Fields](#updates-without-required-fields) | Proposed | A record in `updates` writes the fields it carries, and an edge the keys it carries in `properties` |
| req-grift-yield | [Yielding To Another Source](#yielding-to-another-source) | Proposed | Under `on_other_source: yield` a field another source asserted is skipped and reported |
| req-grift-full-replace | [Full Replace](#full-replace) | Proposed | A record in `replaces` is the whole object; omitted fields reset |
| req-grift-collection-window | [Collection Window](#collection-window) | Proposed | `collected`: when a collector read each object, stated per record or once per batch, kept apart from the record's fields; format `"1"` only; an export states each row's spine pair |
| req-grift-v0-nongoals | [v0 Non-Goals](#v0-non-goals) | Implemented | Explicit exclusions for this version |

## Document Format
----
RID: `req-grift-format`

Status: `Implemented`

### Top-Level Shape

A GRIFT document is raw JSON. It is not JSON Lines, NDJSON, JSONC, or any other extended format.

The top-level object contains exactly these keys:

- `metadata`
- `_reserved`
- `batches`

`metadata` contains:

- `grift_version`: string, required. `"1"` states versions; `"0"` is the earlier form, which states none
- `spine_version`, `type_versions`: required at `"1"`, refused at `"0"` (`req-grift-header-versions`)

`_reserved` contains:

- an object reserved for future extension
- in v0 it may be empty

`batches` contains:

- an array of batch containers
- it may be empty

Unknown top-level keys are invalid.

### Example

```json
{
  "metadata": {
    "grift_version": "0"
  },
  "_reserved": {},
  "batches": []
}
```

### Example Document With Data

```json
{
  "metadata": {
    "grift_version": "0"
  },
  "_reserved": {},
  "batches": [
    {
      "batch_entity": {
        "entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc001",
        "entity_type": "batch",
        "name": "Initial LOTR import",
        "dimensions": {},
        "created_at": "2026-04-06T15:00:00Z",
        "updated_at": "2026-04-06T15:00:00Z",
        "deleted_at": null
      },
      "batch_node": {
        "name": "Initial LOTR import",
        "description": "Imports seed entities and edges for the LOTR plugin.",
        "description_json": null,
        "source": "plugin:lotr",
        "metadata": {
          "dataset": "lotr"
        }
      },
      "nodes": [
        {
          "entity": {
            "entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc101",
            "entity_type": "character",
            "name": "Frodo Baggins",
            "dimensions": {},
            "created_at": "2026-04-06T15:00:00Z",
            "updated_at": "2026-04-06T15:00:00Z",
            "deleted_at": null
          },
          "node": {
            "name": "Frodo Baggins",
            "bio": "A hobbit of the Shire who inherits the One Ring."
          }
        }
      ],
      "edges": [
        {
          "entity": {
            "entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc201",
            "entity_type": "edge",
            "name": "WIELDS",
            "dimensions": {},
            "created_at": "2026-04-06T15:00:00Z",
            "updated_at": "2026-04-06T15:00:00Z",
            "deleted_at": null
          },
          "edge": {
            "from_entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc101",
            "to_entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc102",
            "edge_type": "WIELDS",
            "properties": {}
          }
        }
      ]
    }
  ]
}
```

## Entity Envelope
----
RID: `req-grift-envelope`

Status: `Implemented`

Every batch, node, and edge object carries an `entity`-style envelope containing canonical entity metadata from the TAP entity spine.

### Envelope Fields

Required:

- `entity_id`: UUIDv7 string
- `entity_type`: string
- `dimensions`: object

Optional:

- `name`: non-empty string
- `created_at`: RFC 3339 UTC datetime string
- `updated_at`: RFC 3339 UTC datetime string
- `deleted_at`: RFC 3339 UTC datetime string or `null`

### Envelope Rules

- `entity_id` is the sole identity key. Identity matching is by `entity_id` only.
- `dimensions` is always present, even when empty.
- `dimensions` is a flat string-to-string map.
- On import, `dimensions` is merged with the target type's defaults using the explicit-wins rule defined in `req-grid-dimension-dc` (node types contribute `DEFAULT_DIMENSIONS`; edge types contribute their registered `default_dimensions`). Envelope keys win over defaults. See `req-grid-dimension-dc-5`.
- `name` is the canonical human-readable identifier when present.
- If `name` is present it must not be an empty string.
- `created_at` and `updated_at` are optional in v0, but if present they are imported and validated.
- `deleted_at` is optional; if present it is validated for timestamp sanity (see below) but **not applied** by node or edge upsert. An envelope's `deleted_at` does not mark the imported entity deleted. Import-time deletion intent is declared only through the batch-level `deletes` section or a node or edge object's `retirement` block (`req-grift-retirement`), and hard-delete intent only through the batch-level `purges` section.
- A batch envelope must use `entity_type == "batch"`.
- An edge envelope must use `entity_type == "edge"`.

### Timestamp Sanity Rules

If present:

- `updated_at >= created_at`
- `deleted_at >= updated_at`
- `deleted_at` may not exist unless `updated_at` also exists

If `created_at` is absent, no inferred creation time is assumed by the file format.

## Batch Container
----
RID: `req-grift-batch`

Status: `Implemented`

GRIFT batches preserve serialized TAP batch structure and group imported nodes and edges under their originating batch.

### Batch Shape

Each item in `batches` is an object with these required keys:

- `batch_entity`
- `batch_node`
- `nodes`
- `edges`

It may also contain these optional keys:

- `deletes`
- `purges`
- `contents` (`req-grift-contents`)

Unknown keys are invalid.

`batch_entity` is an entity envelope for the batch itself.

`batch_node` is the batch model payload.

`nodes` is an array of node objects and is always present.

`edges` is an array of edge objects and is always present.

`deletes`, when present, is an imperative removal section for ordinary tombstone deletes. It is not inferred from absent `nodes` or `edges`.

`purges`, when present, is an imperative removal section for DEBUG-only hard deletes. It is not inferred from absent `nodes` or `edges`.

### Batch Payload

`batch_node` is validated as a full-object payload against the `batch` model field contract:

- validate field shapes using the model's `FIELD_CRUD_SCHEMA`
- required fields are `REPLACE_REQUIRED` if declared, otherwise `CREATE_REQUIRED`
- patch-only fields are excluded from GRIFT payload validation

In current TAP implementations this may be realized by validating against the synthesized `SERVICE_CRUD_SCHEMA["replace"]` schema, but that is an implementation detail rather than the canonical GRIFT contract.

### Batch Field Semantics

In v0:

- actor identity is omitted from the serialized batch object
- batch naming uses the `name` field on both `batch_entity` and `batch_node`
- `batch_entity.entity_type` must be `"batch"`

### Example Batch Container

```json
{
  "batch_entity": {
    "entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc001",
    "entity_type": "batch",
    "name": "Initial LOTR import",
    "dimensions": {},
    "created_at": "2026-04-06T15:00:00Z",
    "updated_at": "2026-04-06T15:00:00Z",
    "deleted_at": null
  },
  "batch_node": {
    "name": "Initial LOTR import",
    "description": "Imports seed entities and edges for the LOTR plugin.",
    "description_json": null,
    "source": "plugin:lotr",
    "metadata": {
      "dataset": "lotr"
    }
  },
  "nodes": [],
  "edges": [],
  "deletes": {
    "on_missing": "error",
    "on_tombstoned": "ignore",
    "edges": [],
    "nodes": []
  },
  "purges": {
    "on_missing": "error",
    "edges": [],
    "nodes": []
  }
}
```

### Batch Timestamp Rules

If present:

- `started_at` and `closed_at` must be RFC 3339 UTC datetimes
- `closed_at >= started_at`

Consistency rules:

- `status == "open"` forbids `closed_at`
- `status == "closed"` requires `closed_at`
- `status == "failed"` requires `closed_at`
- `error_message` is only allowed when `status == "failed"`

## Node Object
----
RID: `req-grift-node`

Status: `Implemented`

Each node object is a serialized TAP node. An exporter writes every field; a sender that can assert only some of a node's fields may omit the rest, and an importer routing to an existing entity then leaves the omitted fields alone (`req-grid-import-grift-ordering-8`).

### Node Shape

Each item in `nodes` is an object with these keys:

- `entity` (required)
- `node` (required)
- `retirement` (optional; present only when the node is retired, `req-grift-retirement`)

Unknown keys are invalid.

`entity` is an entity envelope.

`node` is the typed model payload.

### Node Validation

`node` is validated as a full-object payload against the model's field contract:

- validate field shapes using the model's `FIELD_CRUD_SCHEMA`
- required fields are `REPLACE_REQUIRED` if declared, otherwise `CREATE_REQUIRED`
- `PATCH_EXTRA_FIELDS` are excluded from GRIFT payload validation

In current TAP implementations this may be realized by validating against the synthesized `SERVICE_CRUD_SCHEMA["replace"]` schema.

### Example Node Object

```json
{
  "entity": {
    "entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc101",
    "entity_type": "character",
    "name": "Frodo Baggins",
    "dimensions": {},
    "created_at": "2026-04-06T15:00:00Z",
    "updated_at": "2026-04-06T15:00:00Z",
    "deleted_at": null
  },
  "node": {
    "name": "Frodo Baggins",
    "bio": "A hobbit of the Shire who inherits the One Ring."
  }
}
```

## Edge Object
----
RID: `req-grift-edge`

Status: `Implemented`

Each edge object is a full serialized TAP edge with its own backing entity and explicit endpoint references.

### Edge Shape

Each item in `edges` is an object with these keys:

- `entity` (required)
- `edge` (required)
- `retirement` (optional; present only when the edge is retired, `req-grift-retirement`)

Unknown keys are invalid.

`entity` is an entity envelope for the edge's backing entity.

`edge` contains:

- `from_entity_id`: UUID string, required
- `to_entity_id`: UUID string, required
- `edge_type`: string, required
- `properties`: object, required

### Edge Validation

- `from_entity_id`, `to_entity_id`, and `edge_type` are GRIFT-level required fields
- `properties` is always present, even when empty
- `properties` is validated as a full-object payload against the edge model field contract
- patch-only fields are excluded from GRIFT payload validation
- `entity.entity_type` must be `"edge"`

In current TAP implementations this may be realized by validating `properties` against the synthesized `SERVICE_CRUD_SCHEMA["replace"]` schema for the edge model.

### Example Edge Object

```json
{
  "entity": {
    "entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc201",
    "entity_type": "edge",
    "name": "WIELDS",
    "dimensions": {},
    "created_at": "2026-04-06T15:00:00Z",
    "updated_at": "2026-04-06T15:00:00Z",
    "deleted_at": null
  },
  "edge": {
    "from_entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc101",
    "to_entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc102",
    "edge_type": "WIELDS",
    "properties": {}
  }
}
```

## Edge Identity Document Surface
----
RID: `req-grift-edge-identity-surface`

Status: `Proposed`

Edge identity (`req-grid-edge-identity`) adds three shapes to the GRIFT document. This requirement lists them in one place so the format stays one contract; the behaviour of each is the importer's and is specified there. Each shape is added to `grift-document.schema.json` in the same change as the importer code that honours it, so no field is ever accepted and then dropped. All three have landed: the endpoint by natural key (Issue# 914 - tap), removal by identity (Issue# 915 - tap) and the `edge_cases` section (Issue# 919 - tap).

#### Status Details
Implemented (Issue# 912 - tap; epic Issue# 911 - tap). The `edge_cases` section's schema is `GriftEdgeCases` / `GriftAuthorityClaim`, closed; its behaviour is `req-grid-reconcile-edge-authority`, a dry-run until Issue# 920 - tap.

#### Implementation
| Shape | Where | Behaviour |
| --- | --- | --- |
| Endpoint by natural key | `GriftEdgePayload`: `from_key` / `to_key` beside `from_entity_id` / `from_ref`, exactly one per endpoint | `{ "entity_type": <type>, "key": { <declared natural-key property>: <value>, ... } }`, resolved by the importer (`req-grid-import-grift-edge-endpoints`) |
| Removal by edge identity | `GriftDeletesSection.edges` target (`GriftEdgeRemovalByIdentity`), as an alternative to `entity_id`; `deletes.nodes` and `purges` stay id-addressed | `{ "edge_type", "from", "to", "discriminators", "reason" }`, each endpoint `{ "entity_id" }` or `{ "entity_type", "key" }` (`GriftRemovalEndpoint`), resolved by the importer (`req-grid-import-grift-edge-removal`) |
| Authority claims | A new optional batch-container member `edge_cases`, whose one defined member is `authority` | An array of `{ "edge_type", "anchor", "direction", "read" }` claims, with a reserved `dimensions` (`req-grid-reconcile-edge-authority`) |

An importer that does not implement a shape fails preflight on a document carrying it, rather than ignoring it. A key never carries an identity, a search or an override of the sender's choosing: it names *which* declared properties to look up, and the receiving grid's declaration decides what they mean (`req-grid-entity-natural-key-2`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grift-edge-identity-surface-1 | Shapes Land With Their Code | Implemented | The schema accepts each of the three shapes only in the change that adds the importer behaviour for it; until then a document carrying one fails preflight. | No accept-and-drop. `edge_cases` landed with its importer step (Issue# 919 - tap). `tap_grid/tests/test_grift_edge_authority.py::TestTheStatementShape::test_the_schema_accepts_a_claim_now_that_the_importer_honours_it`. |
| req-grift-edge-identity-surface-2 | A Key Names, The Grid Decides | Implemented | An endpoint or removal key is read against the receiving grid's own natural-key declaration; the document supplies values for declared properties and nothing else. | `req-grid-entity-natural-key-2`. `tap_grid/tests/test_grift_edge_endpoints.py::TestCompleteKeysOnly::test_an_unsound_key_is_refused_before_anything_is_written`. |
| req-grift-edge-identity-surface-3 | `edge_cases` Is Closed | Implemented | The `edge_cases` section accepts only its defined members; an unknown member fails the document. | Room for the edge overwrite policy without an open-ended bag. `tap_grid/tests/test_grift_edge_authority.py::TestTheStatementShape::test_edge_cases_is_closed`. |


## Validation Rules
----
RID: `req-grift-validation`

Status: `Implemented`

GRIFT v0 is intentionally strict.

### General Rules

- Unknown keys are rejected at every level except `_reserved`
- `_reserved` is reserved for future extension; v0 importers must ignore its contents
- All wrapper keys are part of validation, not informal hints
- Duplicate `entity_id` values anywhere in the file are invalid — two spellings of one UUID are one value (`req-grid-import-grift-identity-4`)
- Duplicate batch `entity_id` values are invalid
- Wrapper arrays are always present, even when empty

Importer workflow, reference resolution, datetime comparison timing, and batch execution behavior are defined separately in the GRIFT importer specification.

## Seed Data ID Convention
----
RID: `req-grift-seed-ids`

Status: `Deprecated`

This requirement previously codified a hand-authored "synthetic UUIDv7" convention for plugin seed `entity_id` values: a fixed plugin-wide timestamp prefix, zeroed `rand_a`, zeroed high bits of `rand_b`, and a hand-curated counter tail. That convention produced UUIDs that were structurally not unique — humans pick low numbers, and on 2026-04-27 a collision in the genericom plugin proved the failure mode.

The convention is replaced by:

- [spec-grid-uuid-selection.md](spec-grid-uuid-selection.md) — defines the menu of allowed UUID schemes (v7, v5, v4) and the criteria for choosing one. UUIDs in seed data are organic `uuid.uuid7()` values. (The v5-for-mirrored-identity rule that spec once carried is superseded by `req-grid-entity-natural-key`, 2026-09-17: entity and edge ids are assigned, never derived.)
- [spec-grift-seed-ids-real-uuid7.md](spec-grift-seed-ids-real-uuid7.md) — the one-shot migration that rewrote every in-tree synthetic UUID to organic v7.

This section is retained as a historical pointer; do not author new IDs under the old convention.

## Canonical Export Ordering
----
RID: `req-grift-order`

Status: `Backlog`

GRIFT exports should be stable and diff-friendly.

Recommended canonical ordering:

- batches sorted by `started_at`
- nodes sorted by `entity.entity_id`
- edges sorted by `entity.entity_id`

Recommended formatting:

- UTF-8 encoded JSON
- pretty-printed
- two-space indentation
- trailing newline
- stable key ordering

These formatting requirements support human readability for type-based plugin data files while still allowing large mixed-type imports.

## Imperative Removal Sections
----
RID: `req-grift-import-deletes`

Status: `Approved for Development`

GRIFT batches may declare explicit removal operations alongside their node and edge upserts. These operations are imperative: they mean "apply these removals as part of this batch." They do **not** mean "make the grid exactly match this file" and they do not infer removals from objects absent from `nodes` or `edges`.

### Removal Section Shape

A batch may include a `deletes` section, a `purges` section, both, or neither.

`deletes` has this shape:

```json
{
  "on_missing": "error",
  "on_tombstoned": "ignore",
  "edges": [
    {
      "entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc201",
      "entity_type": "edge",
      "reason": "Replaced by a canonical relationship."
    }
  ],
  "nodes": [
    {
      "entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc101",
      "entity_type": "character",
      "reason": "No longer part of this seed set."
    }
  ]
}
```

`purges` has this shape:

```json
{
  "on_missing": "error",
  "edges": [],
  "nodes": []
}
```

Rules:

- `edges` and `nodes` are always present inside a removal section, even when empty.
- Removal targets require `entity_id`, `entity_type`, and `reason`.
- `entity_type` is a sanity check against the local Entity row. It is not optional decoration.
- `reason` is required so removal context can be traced from the batch and its event metadata.
- Section-level knobs apply to every target in that section. v0 does not support item-level overrides.

### Section Knobs

Allowed `on_missing` values:

- `error`
- `warn`
- `ignore`

Allowed `deletes.on_tombstoned` values:

- `error`
- `warn`
- `ignore`

Default policy for authors who want conventional behavior:

- `deletes.on_missing = "error"`
- `deletes.on_tombstoned = "ignore"`
- `purges.on_missing = "error"`

A purge operator is asking for DEBUG-only hard deletion. If the target identifier is wrong, they almost certainly want to know loudly rather than have the bundle complete with a "warned" outcome. The conventional policy mirrors `deletes.on_missing` for the same reason: missing identifiers usually mean an authoring mistake, not desired state.

The schema requires the policy fields to be present rather than silently applying defaults. This keeps GRIFT explicit and diffable.

### Semantics

`deletes` performs ordinary TAP tombstone delete behavior through the service layer. History is preserved, `deleted_at` is set, and node deletes tombstone touching edges according to the standard delete contract.

`purges` performs DEBUG-only hard-delete behavior. Purge removes the target row, its Entity spine, relevant history rows, and target-specific BatchEvent rows according to the service-layer purge contract. Purge is for development cleanup and reset workflows, not normal product deletion.

Edge targets are processed before node targets within each section. This lets a bundle explicitly remove relationships before removing nodes and keeps the declared order consistent with TAP's graph shape.

### Non-Goals

- Desired-state reconciliation is out of scope. A future AWS-style authoritative import may trim entities that are no longer present upstream, but this requirement does not define that machinery.
- Removal by query, dimension, type, or batch ownership is out of scope. v0 removal targets explicit entity IDs only.
- Item-level policy overrides are out of scope. Split the work into separate batches if mixed policy is needed.

## Optimistic Concurrency Via Expected Version
----
RID: `req-grift-concurrency-version`

Status: `Implemented`

GRIFT carries an optional optimistic-concurrency contract for mutating targets. A sender that knows the version of an entity it intends to act on may declare that expectation on the mutating target; the importer enforces the expectation atomically at execution time. A mismatch fails the batch loudly rather than silently overwriting state the sender did not see.

This is the same model adopted by Kubernetes (`resourceVersion`), Postgres `SERIALIZABLE` (`40001 serialization_failure`), CockroachDB, AWS Cloud Control, Jira / GitHub API ETags, and event-sourcing frameworks with `entity_expected_version` on aggregate writes. GRIFT adopts it because GRIFT is the primary write surface for the grid, will be exercised by many senders concurrently in the satellite / outpost direction, and central locking does not scale to that shape. OCC pushes the conflict-resolution decision to the sender — which is the only party that knows whether to retry, re-plan, or surface the conflict to its operator — and lets the importer remain stateless about retry policy.

### Scope

Optimistic concurrency applies to **mutating targets**:

- node objects whose envelope's `entity_id` already exists locally and therefore drives a replace (`req-grid-import-grift-batch` / per-entity last-write-wins)
- edge objects whose envelope's `entity_id` already exists locally and therefore drives a replace
- every target inside a `deletes` section
- every target inside a `purges` section

It does NOT apply to:

- node or edge envelopes where the sender omits `entity_expected_version` AND the local grid has no matching entity — these route through the normal create flow with no version check
- batch envelopes (`batch_entity`) — batch identity is governed by `req-grid-import-grift-identity`, not OCC
- `batch_node` payloads (the batch model row, not a contended entity)

#### Declared Expectation On A Missing Local Entity

GRIFT upsert routes create vs. replace from local state, not from the document. The same envelope can route to a replace on one grid (where the entity exists) and a create on another grid (where it doesn't). This asymmetry interacts with OCC: a sender who *declared* `entity_expected_version` is asserting "I expect this entity to exist with version N." Silently demoting that to a create-with-version-ignored would let bundles succeed on a grid where the sender's expectation is wrong by definition (there is no version N — there is no entity).

The contract is therefore: **a node or edge envelope that declares `entity_expected_version` and points at an entity_id with no matching local entity is a version conflict.** It surfaces with `entity_version_conflict` and `actual_entity_version = null`, the same shape used when a local entity exists but its version moved. This makes the contract symmetric — the sender's expectation is enforced regardless of how the local state diverges from it — and makes the bundle's behavior independent of the receiving grid's state, except for the conflict signal itself.

A sender who genuinely intends "create this entity if missing, replace it if present" should omit `entity_expected_version` (the create path is unguarded by design). A sender who declares `entity_expected_version` is explicitly opting out of "create if missing."

### Declaration

The declaration is the optional `entity_expected_version` field on:

- `GriftEntityEnvelope` — for upsert envelopes (nodes, edges)
- `GriftRemovalTarget` — for delete and purge targets

`entity_expected_version` is a positive integer (minimum 1) matching the local `Entity.version` field shape; `Entity.version` is a monotonic counter that starts at 1 on entity creation, so 0 is not a valid expected value. Senders that do not wish to engage OCC for a given target omit the field; the importer then performs the requested write without a version check (existing behavior).

A sender may freely mix targets with and without `entity_expected_version` in the same batch. Each target is enforced independently.

### Enforcement

For every mutating target in an executing batch:

- if `entity_expected_version` is omitted, the importer applies the operation without a version check
- if `entity_expected_version` is present, the importer applies the operation only if the local `Entity.version` matches `entity_expected_version` at the moment of execution
- a mismatch is a `entity_version_conflict` issue and aborts the batch atomically via the standard transactional rollback contract

The version check is enforced by the service-layer verb that performs the mutation, using a single atomic guard on the `Entity` row (a conditional UPDATE or a `SELECT … FOR UPDATE` followed by a compare-and-act, both performed inside the verb's transaction). The race window between version-check and version-mutation is zero, and exactly one `Entity.version` increment is recorded per successful operation. The detailed contract is governed by `req-grid-import-grift-occ` in `spec-grid-import-grift.md` and `req-grid-service-batch-occ` in `spec-grid-service-batch.md`.

### Failure Semantics

A version conflict is **not** a recoverable per-target outcome:

- there is no `on_entity_version_conflict` policy knob analogous to `on_missing` / `on_tombstoned`
- the importer never silently overwrites stale-version state
- the importer never silently skips a target whose version moved
- the batch fails as a whole and rolls back; the sender is responsible for re-reading, re-planning, and (if appropriate) resubmitting

This asymmetry is intentional. `on_missing` / `on_tombstoned` describe expected variations in target state that the bundle author has already decided how to handle in policy text. A version conflict describes a state change the author did not anticipate; the safe response is to surface it loudly, not to apply a default response chosen by the file format.

### Reference Time And Versions

GRIFT already captures a single `reference_time` per import (`req-grid-import-grift-time`) used for timestamp comparison. `entity_expected_version` is a complementary mechanism: `reference_time` governs WHAT counts as a valid imported timestamp; `entity_expected_version` governs whether the local entity has moved since the sender prepared the batch.

The sender is responsible for capturing `entity_expected_version` values that are coherent with one another (e.g. by reading the target entities under a single repeatable-read transaction or by reading them from a recent snapshot). GRIFT does not define how `entity_expected_version` values are obtained; it only enforces them at import.

### Future Work

- a future "weak" version mode might allow targets to declare `entity_expected_version_at_least` semantics for non-conflicting forward-only writes; deferred until a use case lands
- service-layer verbs (`replace_node`, `patch_node`, `delete_node`, `purge_node`, edge siblings) accept an `entity_expected_version` parameter so non-GRIFT callers can use the same contract; defined in `req-grid-service-batch-occ` and the relevant verb specs
- a future TAP client helper library (`tap_client.grift`) is expected to wrap the retry-on-conflict loop; see commentary in `req-grid-import-grift-occ` Client Guidance

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grift-concurrency-version-1 | Optional Field On Envelope And Removal | Approved for Development | `entity_expected_version` is an optional positive integer (minimum 1) field on `GriftEntityEnvelope` and `GriftRemovalTarget`. `Entity.version` starts at 1, so 0 is not a valid expected value. | |
| req-grift-concurrency-version-2 | Applies To Mutating Targets Only | Approved for Development | OCC applies to replace-flow upsert envelopes and to delete / purge removal targets. Envelopes that omit `entity_expected_version` and find no local entity route through the create path with no version check. `batch_entity` and `batch_node` are out of scope. | |
| req-grift-concurrency-version-7 | Declared Expectation Beats Missing Entity | Approved for Development | An envelope that declares `entity_expected_version` and points at an entity_id with no matching local entity is a `entity_version_conflict` with `actual_entity_version = null`. The sender's declared expectation is enforced regardless of whether the local divergence is "wrong version" or "no entity at all." | Makes the contract symmetric and bundle behavior grid-independent. |
| req-grift-concurrency-version-3 | Omitted Means Skip Check | Approved for Development | A target with no `entity_expected_version` proceeds without a version check, preserving existing import behavior. | |
| req-grift-concurrency-version-4 | Mismatch Aborts Batch | Approved for Development | A version mismatch on any in-scope target aborts the batch with a `entity_version_conflict` issue; the batch rolls back atomically. | |
| req-grift-concurrency-version-5 | No Conflict Policy Knob | Approved for Development | The file format does not expose `on_entity_version_conflict`. Version conflicts always fail loud. | |
| req-grift-concurrency-version-6 | Mixed Bundles Permitted | Approved for Development | A single batch may freely mix targets with and without `entity_expected_version`. | |

## Retirement Block
----
RID: `req-grift-retirement`

Status: `Implemented`

A retired entity is still part of a grid's record: it existed, and something retired it. A node or edge object may carry that retirement so a grid can be moved without losing it. The block is plain DATA about the source grid. It describes a retirement that already happened somewhere else, and it is never the importing grid's own provenance: the importing grid records its own act of retiring the row, in its own batch, and keeps the carried block beside that record.

```json
{
  "entity": { "entity_id": "01962ebd-f9d4-7f8a-9b4e-0e4f4d2dc101", "entity_type": "lotr__character", "dimensions": {} },
  "node": { "name": "Boromir" },
  "retirement": {
    "retired_at": "2026-09-24T18:02:11.412000+00:00",
    "batch_id": "01996f3c-1a2b-7c3d-8e4f-5a6b7c8d9e0f",
    "reason": "dropped_from_observation",
    "metadata": { "collector": "lotr" }
  }
}
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grift-retirement-1 | Presence means retired | Implemented | A node or edge object carrying `retirement` describes a retired entity; one without it describes a live entity. The block's keys are exactly `retired_at` (RFC 3339 datetime, required), `batch_id` (UUID or `null`), `reason` (non-empty string or `null`) and `metadata` (object); any other key is invalid. `retired_at` may not be later than the file's reference time. | Envelope `deleted_at` stays validated-and-dropped (`req-grift-envelope`); the block is the one place retirement travels. |
| req-grift-retirement-2 | The block is the source grid's, not the import's | Implemented | `batch_id`, `reason`, `retired_at` and `metadata` name the retirement as the source grid recorded it. An importer does not write any of them into its own provenance (its batch, its FLIP map, the batch of its own retirement event); it keeps the block, unchanged, as data. | Keeps "who retired this, and why" distinct from "who moved it here". |
| req-grift-retirement-3 | Null means not recorded | Implemented | `batch_id` is `null` when the source grid recorded no retiring batch for the row. `reason` is `null` and `metadata` is `{}` when the source grid holds no retirement event for the entity in that batch, as for an edge a plain node delete ended by the endpoint rule. A null is never filled with a guess. | Grid convention: null is unobserved. |

## Contents Declaration
----
RID: `req-grift-contents`

Status: `Implemented`

A batch may say what kinds of record it carries, so a reader knows before importing whether the batch holds more than live state. The shape follows the manifest `[fips]` block's declare-vs-decide split (`specs/spec-fips.md`): the exporter DECLARES, and the declaration is verified against the batch, never trusted; the importer DECIDES which kinds it accepts. Each key under `contents` names one kind of record (an aspect) and holds at least `included`. Later versions add aspects, such as `history` and `flip`, without changing the shape.

```json
"contents": {
  "tombstones": { "included": true, "nodes": 3, "edges": 5 },
  "history": { "included": false },
  "flip": { "included": false }
}
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grift-contents-1 | One object per aspect | Implemented | `contents` is an optional object on the batch container. Every value in it is an object with a boolean `included`. The `tombstones` aspect is required when `contents` is present and holds exactly `included`, `nodes` and `edges`, the counts of retired node and edge objects in the batch. | |
| req-grift-contents-2 | Declaration verified against the batch | Implemented | The importer counts the `retirement` blocks the batch actually carries. `tombstones.included: false` with any block present, or a `nodes` or `edges` count that differs from the blocks present, fails the file at preflight with `contents_mismatch`, and nothing is written. | Declare, then verify. |
| req-grift-contents-3 | The importer decides | Implemented | An aspect declared `included: true` that this importer does not accept fails the file at preflight with `unsupported_contents`. An aspect declared `included: false` is accepted whether or not the importer knows its name. The v0 importer accepts `tombstones` and no other aspect; `history` and `flip` are reserved names for aspects not yet defined. | An importer never silently drops a kind of record it was told is there. |
| req-grift-contents-4 | Absent declaration | Implemented | A batch without `contents` imports as it did before this requirement. Any `retirement` blocks it carries are still validated and applied. | Hand-authored bundles are not required to declare. |
| req-grift-contents-5 | Importers must accept tombstones | Proposed | Whether every GRIFT importer MUST accept `tombstones`, or may refuse them as a policy choice, is not yet decided. | Left open by the 2026-09-25 ruling. |

## Grid Export
----
RID: `req-grift-export`

Status: `Implemented`

`manage.py export_grift` (`tap_grid.grift.exporter.export_grid`) serialises a grid into one GRIFT batch that the importer in `spec-grid-import-grift.md` consumes. By default it exports everything the format can carry, retired rows included. Selectors narrow the export to a subset, and the batch records which selectors produced it.

#### Selectors

| Flag | Selects |
| --- | --- |
| `--dimension KEY=VALUE` | Nodes whose `dimensions[KEY]` equals `VALUE` (for example `--dimension dcom=design`). |
| `--batch ID_OR_NAME` | Nodes the named batch recorded an event against (created, updated or retired). A UUID names a batch by id; anything else names it by exact `name`, and a name must match exactly one batch. |
| `--reachable-from ENTITY_ID` | The node itself and every node connected to it by a path of edges in either direction. Retired edges are followed too, unless `--exclude-tombstones` is given. |
| `--exclude-tombstones` | Leaves retired nodes and edges out. |

Each selector flag may repeat. Repeats of one flag are OR-ed; different flags are AND-ed. Selectors select NODES, and an edge rides when both of its endpoints are exported, the rule that keeps any export importable in `strict` dangling-edge mode.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grift-export-1 | Everything by default | Implemented | With no selector, every node and edge of an exportable type is exported, live or retired. A retired one carries a `retirement` block (`req-grift-retirement`). | |
| req-grift-export-2 | Where the retirement data comes from | Implemented | `retired_at` is the entity's `deleted_at`. `batch_id` is the retiring batch FLIP recorded on the typed row as `flip_map["deleted_at"]`. `reason` and `metadata` come from the entity's delete or unlink `BatchEvent` in that batch, with `reason` lifted out of the metadata. When that event carries an `original_retirement` block (the row's retirement was itself imported, `req-grid-import-grift-retired`), the export carries that block, so a grid-to-grid-to-grid move keeps the first grid's retirement. | |
| req-grift-export-3 | The batch declares its contents | Implemented | Every exported batch carries `contents` (`req-grift-contents`) with the true tombstone counts, `history: {included: false}` and `flip: {included: false}`. | |
| req-grift-export-4 | Selectors select exactly | Implemented | The exported nodes are exactly the nodes every given selector kind admits; the exported edges are exactly the in-scope edges whose endpoints are both exported. A `--batch` name that matches no batch or more than one, or a `--reachable-from` value that names no node, is refused and nothing is exported. | |
| req-grift-export-5 | Every left-out row is counted | Implemented | Retired rows are no longer skipped by default. With `--exclude-tombstones` they are counted under `tombstoned`; a node a selector did not admit is counted under `not_selected`. Every row the export leaves out is still counted under exactly one named reason. | |
| req-grift-export-6 | A subset says it is a subset | Implemented | The batch's `description_json` capture data records the selectors used (`selection`), so a subset export can never be read as a whole grid. | |

## Version Declarations In The Header
----
RID: `req-grift-header-versions`

Status: `In Development`

A document says which definitions wrote it. Beside `grift_version`, which says how to parse the file, the header carries the version of the spine and the version of every type the document carries. An importer uses them to upgrade older records before it validates them, and to refuse a document written by definitions newer than its own. What the versions are and how an import acts on them is specified in `spec-grid-entity.md` (`req-grid-entity-model-version`, `req-grid-entity-spine-version`); this requirement specifies only how they are written in the document.

#### Status Details
In Development. Rules 1 to 9 are built, and rules 10 to 12 as far as they apply before the fleet is moved: format `"0"` is read, and its refusal is behind a switch. Issue# 1284 - tap records the rulings, the one on format `"0"` among them (2026-11-22); Issue# 1288 - tap tracks moving the fleet.

Built:

- The schema (`tap_grid/schemas/grift-document.schema.json`): `spine_version` and `type_versions` are properties of `metadata`, each value an integer of 1 or more; at `grift_version` `"1"` both are required, at `"0"` both are refused, and `metadata` still refuses an unknown key.
- The exporter writes `grift_version` `"1"` with both fields (`build_header` in `tap_grid/grift/upgrade.py`): the spine version the database records, and for every type the document carries or names the version the type catalog records as applied. `build_header` is also the call for any producer that builds a document in code.
- The importer reads `"0"` and `"1"`. At `"1"` a missing `spine_version`, and a carried or named type with no entry in `type_versions`, refuse the document with `version_unstated`, naming what is missing, before validation and before anything is written. A format it does not read is refused with `unsupported_grift_version`, naming the version given and the versions read.

Staged by ruling, and why the requirement is not Implemented:

- Format `"0"` is still read (rule 11). Read on 2026-11-22: every committed GRIFT document in core (six files) and in the plugin repositories (122 files across 29 of the 33 repositories cloned on 2026-11-21, 30 of them in the eight plugins installed in the development stack) is stamped `"0"`, and collectors in 14 repositories build documents in code and stamp them from core's `GRIFT_VERSION` constant. Refusing `"0"` before those are moved would refuse every seed bundle and every collection at once, and a bundle restamped `"1"` is refused by every core release before this one, which a plugin's CI still tests against. So the refusal is behind `TAP_REQUIRE_GRIFT_VERSIONS=1`, and `GRIFT_VERSION` stays `"0"`: it is what an unversioned producer stamps.
- The move (rule 12) is not done: no document in core or in any plugin is restamped, no collector is moved, and the refusal is not the default. It is part of the base-model release (Issue# 1288 - tap).

#### Implementation

```json
{
  "metadata": {
    "grift_version": "1",
    "spine_version": 1,
    "type_versions": {
      "lotr__character": 2,
      "lotr__member_of": 1
    }
  },
  "_reserved": {},
  "batches": []
}
```

1. `metadata.spine_version` is an integer of 1 or more: the spine version of the grid that wrote the document.
2. `metadata.type_versions` is an object. Each key is an entity type slug, for a node type or an edge type, and each value is an integer of 1 or more: the version of that type on the grid that wrote the document.
3. The three numbers are independent. `grift_version` changes when the form of the file changes. `spine_version` changes when the spine changes. A type's version changes when that type's author changes it. None is derived from another, and none is the tap release version.
4. Both fields are required. `type_versions` has an entry for every entity type the document carries or names, in any batch: as a node or edge record, as a removal target, or only by reference, as an edge endpoint or an authority anchor that names an entity by type and natural key. An entry for a type the document does not carry or name is allowed and ignored.
5. One document states one version per type. A document cannot carry records of one type at two versions; records at different versions travel in different documents.
6. The exporter always writes both fields, from the grid's recorded spine version and the type catalog.
7. A document at format `"1"` that omits `spine_version`, or carries a type with no entry in `type_versions`, is refused, naming what is missing. Nothing is assumed for a version a format `"1"` document does not state.
8. The versions describe the document's source. An importer does not store them on any row. Its batch records what it upgraded (`req-grid-entity-model-version` rule 26).
9. Both fields are added to the `metadata` schema as required properties, and `metadata` continues to refuse unknown keys.
10. Adding the two fields moves `grift_version` from `"0"` to `"1"`. An importer refuses a document whose `grift_version` it does not know, naming the version it was given and the versions it reads. An importer built before this requirement therefore refuses a new document for a reason it can state, the format version, and not for an unknown key.
11. A document at format `"0"` states no versions. While it is read, it is read as the spine and every type it carries at version 1, with no upgrade. That reading is true only while no type and no spine is above version 1, so it ends, at the latest, before any type anywhere is raised to version 2.
12. Format `"0"` is read until the fleet is moved, and refused after. The refusal exists now, behind `TAP_REQUIRE_GRIFT_VERSIONS=1`, and names the version. The base-model release (Issue# 1288 - tap) moves the fleet: every committed document in core and in the plugin repositories is restamped `"1"` with both fields, every collector that builds a document in code states them, core's `GRIFT_VERSION` constant moves to `"1"`, and each plugin's tap floor is raised to a core that reads `"1"`. With that release the refusal becomes the default.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grift-header-versions-1 | Export Writes Both | Implemented | An export's `metadata` carries `spine_version` and a `type_versions` entry for every entity type in the document, each equal to what the grid records. |  |
| req-grift-header-versions-2 | Schema Accepts Them | Implemented | A document carrying both fields validates; one whose `spine_version` or any `type_versions` value is not an integer of 1 or more does not. |  |
| req-grift-header-versions-3 | Edge Types Included | Implemented | A document carrying edges has a `type_versions` entry for each edge type. |  |
| req-grift-header-versions-4 | Absent Is Refused | Implemented | A document with no `spine_version`, or carrying a type with no `type_versions` entry, is refused, names what is missing and writes nothing. | Code `version_unstated`, at format `"1"` |
| req-grift-header-versions-5 | Not Stored On Rows | Implemented | After an import no entity or typed row holds the document's stated versions; the import's batch names what was upgraded. | The batch's importer provenance holds `upgraded` |
| req-grift-header-versions-6 | Format Version Moves To 1 | Implemented | An export states `grift_version` `"1"`. An importer refuses a format it does not read, naming the version given and the versions it reads. | An importer that reads only `"0"` is the released one, not run here |
| req-grift-header-versions-7 | Format 0 Is Read Until The Fleet Moves | Implemented | A document stating `"0"` imports with no upgrade and no version refusal; with `TAP_REQUIRE_GRIFT_VERSIONS=1` it is refused, naming the version, and writes nothing. |  |
| req-grift-header-versions-8 | The Fleet States Its Versions | Proposed | No committed GRIFT document in core states `"0"`, `GRIFT_VERSION` is `"1"`, and a document stating `"0"` is refused with no switch set. | Issue# 1288 - tap |

## Write Sections
----
RID: `req-grift-write-sections`

Status: `Proposed`

A batch states how each record is to be written by the section it puts the record in. `nodes` and `edges` stay what they are, an upsert that keeps absent fields. Three optional sections sit beside them, each shaped like the removal sections a batch already has: `inserts` (create only if absent), `updates` (write the fields sent to a row that may already exist, optionally yielding to another source) and `replaces` (replace the whole object). Nodes and edges are both in scope in all three.

#### Status Details
Proposed; nothing is built. The five items it serves were ruled in by the owner as one decision set on Issue# 1284 - tap (Q5 a to e), with the open points of the first draft ruled on 2026-11-23 on the same issue: edges are in scope for all three sections, and the narrow ownership rule of `req-grift-yield` rule 7. This is Phase 2's "GRIFT write semantics" track of the time and observation epic, Issue# 886 - tap.

Today (read) a batch container has `batch_entity`, `batch_node`, `nodes`, `edges` and the optional `deletes`, `purges` and `contents`, and refuses unknown keys (`req-grift-batch`). A record in `nodes` or `edges` whose target exists is applied through `replace_node` / `replace_edge` with `absent="keep"`, the ruling of Issue# 1128 - tap; one whose target does not exist is created (`spec-grid-import-grift.md`, "Per-Entity Last-Write-Wins"). There is no way to say "only if absent", "only the fields I send, without the required ones", "unless another source owns it", or "the whole object, omissions included".

Two things about targets found while writing this (read): identity resolution searches live rows only (`resolve_identity`, `tap_grid/services/__init__.py`), so a record addressed by its natural key does not see a tombstoned row with the same key; Issue# 1170 - tap tracks a lookup that would. And the identity locks a batch takes up front are collected from `nodes` only (`_ref_node_lock_keys`, `tap_grid/grift/importer.py`); the new sections must be added to that collection.

Prior art for putting the write's intent beside the record: a FHIR transaction `Bundle` carries a `request` per entry with its method and an `ifNoneExist` condition (searched: https://hl7.org/fhir/R4/bundle.html, https://hl7.org/fhir/R4/http.html). GRIFT already has its own idiom for the same thing, a section per intent with section-level knobs (`deletes`, `purges`), so this follows GRIFT's idiom and takes only the semantics from the published formats.

#### Implementation
1. A batch container may carry `inserts`, `updates` and `replaces`. Each is an object with `nodes` and `edges`, both always present even when empty, and its knobs, all required: the schema applies no default, as for `deletes` (`req-grift-import-deletes`, "Section Knobs").
2. A member of a section's `nodes` is a node object and a member of its `edges` an edge object, in the shapes `req-grift-node` and `req-grift-edge` define. A `retirement` block is refused in all three sections.
3. Section knobs apply to every record in the section. There is no per-record override, as in the removal sections.
4. An entity appears in at most one write section of a batch (`nodes`/`edges`, `inserts`, `updates`, `replaces`). A second appearance is refused with `duplicate_entity_id`.
5. Order within a batch: every section's nodes before any section's edges, and within each kind `inserts`, then `nodes`/`edges`, then `updates`, then `replaces`; then `deletes`, then `purges`. Array order holds inside a section.
6. Batch-local `ref`s and key endpoints work across the sections of one batch, and the identity locks a batch takes before its writes cover every section.
7. `metadata.type_versions` names every type any section carries, and the upgrade (`req-grid-entity-model-version` rule 21) runs over the records of all sections before anything is validated or written. A step meets partial records in `updates`; a step that needs a field the record does not carry refuses that record, which refuses the document.
8. A record in any write section may state a collection window, and inherits its batch's, in the form `req-grift-collection-window` defines (rules 2 and 4 there); what the grid does with it is `req-grid-entity-collection-time`. A record that names a row is an observation of it whatever it writes: a skipped insert and a fully yielded update move the row's observation pointers and its collection window, and change no value and no FLIP entry (`req-grift-insert-only` rule 7, `req-grift-collection-window` rule 7).
9. A record addressed by `entity_id` whose target is tombstoned is refused with `entity_tombstoned`, in all three sections. Nothing here restores a retired entity. A record addressed by its natural key does not find a tombstoned row (identity resolution reads live rows) and is treated as having no target, as in `nodes` today; whether such a record should see the tombstone waits on Issue# 1170 - tap.
10. Resolving whether a target exists is a read of the grid: the importer authorises `grid.read` in the import's scope before it, as it does for a `ref` (`req-grid-import-grift-identity-5`).
11. `entity_expected_version` is allowed in `updates` and `replaces` and keeps its meaning. In `inserts` it is refused: the section already says what the sender expects.
12. The import result counts records per section and outcome (created, written, unchanged, skipped) and carries one issue per skipped record and per yielded field or key.
13. The sections are part of format `"1"`. No released core reads format `"1"`, so adding them before 0.5.0 changes no reader in the field.

#### Development
A per-record `request` block, as FHIR has, was considered and left out: GRIFT's section knobs have no per-record override, and one section per intent keeps a document diffable. Overloading `entity_expected_version` with `0` for "must not exist" was considered for insert-only and left out: the field's minimum is 1, and a version conflict aborts the batch (`req-grift-concurrency-version-5`), where an insert that finds its row must skip.

Edges were considered for exclusion, since every ticket speaks of nodes. The owner ruled them in, including key-level updates inside an edge's `properties` (`req-grift-partial-update` rule 8), so the shape does not change again when edges need it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grift-write-sections-1 | Three Optional Sections | Proposed | The schema admits `inserts`, `updates` and `replaces` on a batch container, each requiring `nodes`, `edges` and its knobs, and still refuses any other key. | |
| req-grift-write-sections-2 | One Section Per Entity | Proposed | A batch naming one entity in two write sections is refused with `duplicate_entity_id` and writes nothing. | |
| req-grift-write-sections-3 | Order | Proposed | An edge in `edges` whose endpoint is a node created by `inserts` of the same batch is written. | |
| req-grift-write-sections-4 | Upgrade Covers Every Section | Proposed | A version-1 record in `updates` of a document stating version 1, imported where the type is at version 2, is written as the step returns it. | |
| req-grift-write-sections-5 | Tombstoned Target Refused By Id | Proposed | A record in any of the three sections addressed by the `entity_id` of a tombstoned entity fails with `entity_tombstoned`. | |
| req-grift-write-sections-6 | Locks Cover Every Section | Proposed | A batch whose `inserts` and `updates` name keyed nodes takes their identity locks before any write, in the one sorted order. | |

## Insert-Only Records
----
RID: `req-grift-insert-only`

Status: `Proposed`

A record in `inserts` is created when no row exists for it and leaves an existing row exactly as it is. Issue# 1071 - tap.

#### Status Details
Proposed; nothing is built. Today (read in Issue# 1071 - tap, run on 2026-10-19 before keep-absent landed) a node sent under an existing identity replaces the row; since Issue# 1128 - tap an omitted field is kept, but every field sent still replaces, and a sender cannot say "leave it if it is there". A collector must read first and write after, with a gap.

Rule 4 for a record addressed by a natural key is verified by reading the code, not by a test: `resolve_identity` takes a transaction-scoped advisory lock on the type and key values and then searches, inside the batch's transaction, so a second writer of the same key waits and finds the first one's row (`tap_grid/services/__init__.py`, the `pg_advisory_xact_lock` in `resolve_identity`; `_take_identity_locks` in `tap_grid/grift/importer.py`). Rule 4 for a record addressed by `entity_id` is an assumption: no code was read that settles what a concurrent create of the same id does.

Prior art: FHIR conditional create. With no match the server creates; with one match it ignores the request; with several it answers 412 (searched: https://hl7.org/fhir/R4/http.html). HTTP's `If-None-Match: *` on a `PUT` is the same intent (memory, RFC 9110, not fetched).

```json
"inserts": {
  "on_existing": "skip",
  "nodes": [
    { "entity": { "ref": "task-1", "entity_type": "ecs_task", "dimensions": {} },
      "node": { "arn": "arn:aws:ecs:...:task/abc", "name": "abc" } }
  ],
  "edges": []
}
```

#### Implementation
1. `on_existing` is `skip`, `warn` or `error`. `skip` leaves the row and reports the record as skipped at info severity; `warn` does the same at warning severity; `error` fails the batch.
2. A record whose target does not exist is created exactly as a record in `nodes` or `edges` would be: full validation, required fields required.
3. A record whose target exists writes no value to it: no field, no envelope `name` or `dimensions`, no FLIP entry, no revision, no history row. It is still an observation of the row (rule 7).
4. The check and the create are one step inside the batch transaction. For a record addressed by natural key, both happen under the identity lock for that type and key. For a record addressed by `entity_id`, a create that loses to a concurrent create of the same id is treated as "exists".
5. A natural key that matches more than one live row fails the batch, as it does today (FHIR's 412).
6. A keyless type has nothing to find: a record of it addressed by `ref` is always created.
7. A skipped record is an observation of the row by this batch. It moves the observation pointers (`last_observed_batch_id`, `last_observed_at`) and the row's collection window, to the window the record states or to empty when it states none (`req-grift-collection-window` rule 7), and it changes no value and no FLIP entry, writes no history row and does not change the revision. The window then says when this batch read the object, not when the values the row keeps were read (`req-grift-collection-window` rule 1).
8. An edge in `inserts` follows the same rules, its target found by `entity_id` or by its type's identity declaration.

#### Development
`on_exists: skip` on the plain `nodes` array, the first shape the issue suggested, has nowhere to live: `nodes` is an array, and a per-record flag is the override GRIFT rules out.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grift-insert-only-1 | Absent Is Created | Proposed | An `inserts` record for an identity with no row creates the row. | |
| req-grift-insert-only-2 | Existing Is Untouched | Proposed | An `inserts` record for an identity with a live row leaves every field, the name, the dimensions, `flip_map` and the revision as they were, and the result reports it skipped; `last_observed_batch_id` and the collection window move to the inserting batch's. | The issue's done-test; rule 7 |
| req-grift-insert-only-3 | No Gap | Proposed | Two imports inserting the same keyed identity at once create one row; the other reports a skip. | Needs two connections |
| req-grift-insert-only-4 | Error Policy | Proposed | With `on_existing: error` an existing target fails the batch and nothing is written. | |
| req-grift-insert-only-5 | Edges Too | Proposed | An edge in `inserts` whose identity matches a live edge leaves its `properties` and `flip_map` unchanged. | |

## Updates Without Required Fields
----
RID: `req-grift-partial-update`

Status: `Proposed`

A record in `updates` writes the fields it carries to an existing row and need not carry the type's required fields. For an edge, it writes the keys it carries inside `properties`. Issue# 1173 - tap.

#### Status Details
Proposed; nothing is built. Today (read) required fields stay required under keep-absent: "validation is unchanged, so a keep-absent payload must still carry them" (`req-grid-service-write-keepabsent`, the ruling of Issue# 1128 - tap), and `req-grift-node` validates every `node` as a full object. A sender adding one fact to a node it did not create must send every required field, and each replaces the stored value. `patch_node` has no such requirement and the importer never calls it (read in Issue# 1173 - tap, not re-read here).

Prior art: JSON Merge Patch. A member absent from the patch is left alone; a member present replaces; `null` removes (searched: https://www.rfc-editor.org/rfc/rfc7396.html). GRIFT's keep-absent rules are these already, with one local difference kept from Issue# 1128 - tap: `null` on a field that cannot be null resets it to its default. Rule 3 below narrows that for `updates`.

```json
"updates": {
  "on_missing": "ignore",
  "on_other_source": "overwrite",
  "nodes": [
    { "entity": { "ref": "c-1", "entity_type": "ecs_container", "dimensions": {} },
      "node": { "arn": "arn:aws:ecs:...:container/xyz", "image_digest": "sha256:..." } }
  ],
  "edges": []
}
```

#### Implementation
1. Where the target exists, `node` is validated field by field against `FIELD_CRUD_SCHEMA` and the required list is not applied. The fields a natural key needs to find the row are still needed, because without them there is no target.
2. The write follows the keep-absent rules as they stand (`req-grid-service-write-keepabsent-2` to `-4`, `-6`): absent kept, present replaces whole, FLIP on what changed or was first asserted. A field tracked per key (`req-grid-flip-nested`) is written key by key instead.
3. An explicit `null` on a required field is refused with the field named, where keep-absent in `nodes` resets it to its default.
4. `on_missing` is `error`, `warn`, `ignore` or `create`. The first three are the removal sections' values with the same meaning. `create` creates the row, and then the required fields are required; a record that lacks them fails the batch naming them.
5. The envelope's `name` and `dimensions` are applied as for a record in `nodes`, except under `on_other_source: yield` (`req-grift-yield` rule 8).
6. `on_other_source: overwrite` is the behaviour above. `yield` is `req-grift-yield`.
7. A record that changes nothing is an observation, as for any write (`req-grid-flip-change`).
8. An edge in `updates` writes the keys it carries inside `properties` and leaves the others, absent keys included whoever owns them, by `req-grid-flip-nested` rules 4 to 6: an edge's `properties` is tracked per key for every edge type, with no opt-in. The keys the edge type's identity declaration names locate the edge and are not changed by an update; a record that would change one is refused naming it. Endpoints are not changed by an update.

#### Development
Making required fields required-on-create-only for every record in `nodes` was the other shape Issue# 1173 - tap names. It needs no new section, and it leaves the sender unable to say what should happen when the row is not there: the create would fail on the missing fields and abort the batch. The section's `on_missing` is that answer. Calling `patch_node` was not chosen as the contract because `PATCH_EXTRA_FIELDS` are excluded from GRIFT payloads.

An edge's `properties` is per-key for every edge type because it is the edge's only writeable object, so an update that replaced it whole would not be partial at all; the cost the per-key opt-in guards against on nodes, large `configuration` objects, does not arise for edge properties in the fleet today (designed, not measured).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grift-partial-update-1 | No Required Re-Send | Proposed | An `updates` record carrying one optional field and none of the type's required fields writes that field to an existing row and leaves the required fields' values and FLIP entries as they were. | The issue's case |
| req-grift-partial-update-2 | Missing Target Policy | Proposed | With `on_missing: ignore` a record whose target does not exist writes nothing and is reported; with `error` the batch fails; with `create` and the required fields present the row is created; with `create` and one missing the batch fails naming it. | |
| req-grift-partial-update-3 | Null On Required Refused | Proposed | An explicit `null` on a required field in `updates` is refused, naming the field. | |
| req-grift-partial-update-4 | Edge Properties By Key | Proposed | An edge holding `{"a":1,"b":2}` in `properties`, sent in `updates` with `{"b":3}`, ends `{"a":1,"b":3}` with `a`'s entry unchanged. | Owner ruling, Issue# 1284 - tap |
| req-grift-partial-update-5 | Edge Identity Unchanged | Proposed | An `updates` record that would change a property the edge type's identity names is refused naming it. | |

## Yielding To Another Source
----
RID: `req-grift-yield`

Status: `Proposed`

Under `on_other_source: yield`, a record in `updates` writes a field only where no other source has asserted the field's current value. Issue# 1172 - tap.

#### Status Details
Proposed; nothing is built. Today (read, Issue# 1172 - tap) a sender can send a field, which replaces it whoever wrote it, or omit it, which leaves a stale value of its own in place, or read `flip_map` first and decide, with a gap. FLIP already names the batch that set each field's current value, and the batch carries `source` and `actor` (`req-grid-flip-map-2`, `req-grid-flip-batch-1`; `Batch.source` read in `tap_grid/models.py`). Not verified: that every collector sets `Batch.source`, and distinctly from every other collector.

Which source has the final say on a value is **not decided** here. Yield lets a second-hand source step aside and lets a closer source take a value from it; it does not rank two sources that both write with `overwrite`, or a source against an operator's edit. That needs a hierarchy of provenance, which the owner has deferred: Issue# 1341 - tap.

Prior art: Kubernetes Server-Side Apply. Each field has managers; an apply that would change a field another manager owns is a conflict; the applier may force it, omit the field, or match the value and share it (searched: https://kubernetes.io/docs/reference/using-api/server-side-apply/). The mapping: a manager is a source, `overwrite` is a forced apply, `yield` is an apply that drops the conflicting field in place of failing. The issue asks for a skip that is reported, not an error, so that either collector can run first.

#### Implementation
1. A **source** is the `source` of the batch a FLIP entry points at. Two batches are the same source when their `source` values are equal and not empty.
   A batch whose `source` is empty cannot write under `yield`: an `updates` section with `on_other_source: yield` in such a batch refuses the document, naming the batch. Without a source a yielding writer would yield to its own earlier writes, which count as another source's, and could never correct a value it wrote.
2. Under `yield`, a field the record carries is written when the field has no FLIP entry, or its entry points at a batch of the same source as the writing batch. Otherwise the field is skipped: its value, its entry and nothing else about it change.
3. Each skipped field is reported in the result as a warning naming the entity, the field and the other source. It is never dropped silently.
4. The judgement is made inside the write, on the row as locked for the write. There is no read-then-write gap.
5. A record all of whose fields are skipped writes no field and is an observation.
6. `yield` on a field of a type with FLIP off (`req-grid-flip-default`) is refused: there is nothing to judge by.
7. An entry written by a yielding write records that it was yielded (`req-grid-flip-nested` rule 10 gives the form). A later write by a **different** source in `nodes`, in `updates` with `overwrite`, or in `replaces`, that carries the **same** value moves the entry to the writing batch **only when the entry was yielded**; the moved entry is not yielded. An entry not written by a yielding write never moves on a confirming write, whoever sends it. This is the one exception to `req-grid-flip-change` rule 3, ruled by the owner on Issue# 1284 - tap (2026-11-23).
8. A change of owner under rule 7 with no change of value is an observation, not an update: it writes no history row and does not change the revision, `updated_at` or `last_changed_batch_id` (`req-grid-history-reobservation`). It is still a write of provenance, and it needs a path of its own. Today a write that changes no value skips the typed save, and with it the FLIP stamp (`_execute_write_pipeline`, `tap_grid/services/_impl.py`: an unchanged classification records an `observe` event and calls `instance.save` only when something changed). Building rule 7 adds a provenance-only write: on the row as locked for the write (rule 4), it rewrites the moved entries of `flip_map` and nothing else, with no typed save, no history row and no revision. The batch's existing event for the object (the `observe` event an unchanged write records) lists each transferred field path, a tracked key as its field and key, with the previous attribution (batch id, yielded) and the new one. No second event is written.
9. Under `yield` the envelope's `name` and `dimensions` are not applied to a row that exists. They are applied on a create.
10. No precedence between sources is declared anywhere. The closer source writes with `overwrite`; a second-hand source writes with `yield`. Which is which is the collector author's statement, made by the section and knob it uses.

#### Development
Fill-only (write only where the stored value is null) was set aside in the issue: a source could never refresh its own value. A declared precedence table between sources was considered and left out for 0.5.0; it belongs to Issue# 1341 - tap. Failing the batch on a conflict, as Server-Side Apply does, was left out for the reason in the issue.

Without rule 7 the design has a hole (designed, not observed): a provider that writes the same value a second-hand source already wrote does not move the entry, by `req-grid-flip-change`, so the field stays the second-hand source's, which can later overwrite a value the provider confirmed. A wider rule was considered, that any different source confirming a value takes it. It was not chosen: two sources that both write with `overwrite` and agree would then take the field from each other on every pass, a write on every unchanged pass, which is what Issue# 322 - tap removed. The narrow rule costs one flag on a yielded entry.

#### Future
Which source has the final say on a value, and whether a ranking of sources, kinds of source, operators or a per-field declaration decides it: Issue# 1341 - tap.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grift-yield-1 | Other Source's Field Is Left | Proposed | Source B writes `name`; source A sends `name` under `yield`: value and entry are B's, and the result names the field as yielded to B. | |
| req-grift-yield-2 | Own Field Is Refreshed | Proposed | Source A wrote `image`; A sends a new `image` under `yield`: it is written and stamped. | |
| req-grift-yield-3 | Unstamped Field Is Written | Proposed | A field with no FLIP entry is written under `yield`, and its entry records that it was yielded. | |
| req-grift-yield-4 | Either Runs First | Proposed | A then B (overwrite) then A (yield), and B then A (yield), end with the same values for the fields B sends. | The owner's ruling in the issue |
| req-grift-yield-5 | Confirming Takes A Yielded Field | Proposed | A wrote `name` under `yield`; B sends the same `name` with `overwrite`: the entry is B's and not yielded, no history row is written, the revision is unchanged; A's later different `name` under `yield` is skipped. | Rule 7 |
| req-grift-yield-6 | Confirming Does Not Take An Overwritten Field | Proposed | A wrote `name` with `overwrite`; B sends the same `name` with `overwrite`: the entry stays A's, and nothing is written. | Rule 7; Issue# 322 - tap |
| req-grift-yield-7 | No Gap | Proposed | The judgement uses the row as locked for the write. | Needs two connections |
| req-grift-yield-8 | A Yielding Write Needs A Source | Proposed | A document whose batch has an empty `source` and an `updates` section with `on_other_source: yield` is refused, naming the batch, and writes nothing. | |
| req-grift-yield-9 | A Transfer Is Recorded, Not Revised | Proposed | A wrote `name` under `yield`; B sends the same `name` with `overwrite`. The row's `flip_map` entry for `name` is B's batch, not yielded; the typed row's history count, revision, `updated_at` and `last_changed_batch_id` are as before; and B's `observe` event for the object lists `name` with the previous attribution (A's batch, yielded) and the new one (B's batch, not yielded). | Rule 8; the provenance-only write path |

## Full Replace
----
RID: `req-grift-full-replace`

Status: `Proposed`

A record in `replaces` is the whole object: a field it omits is reset, not kept.

#### Status Details
Proposed; nothing is built. Since Issue# 1128 - tap an omitted field in `nodes` is kept (read: `spec-grid-import-grift.md`, "Absent Fields On Upsert"). A sender that holds the whole truth of an object can clear a field only by sending `null` for each one by name, and an object key only by re-sending the field. The service verb already has the behaviour: `replace_node` with `absent="reset"`, its default (`req-grid-service-write-keepabsent-1`).

Prior art: HTTP `PUT` replaces the representation whole (memory: RFC 9110, not fetched).

```json
"replaces": {
  "on_missing": "create",
  "nodes": [ { "entity": { "entity_id": "0196...", "entity_type": "panel", "dimensions": {} },
               "node": { "title": "Inventory", "config": {} } } ],
  "edges": []
}
```

#### Implementation
1. `node` is validated as a full object: required fields required (`req-grift-node`, "Node Validation").
2. A field the record omits is reset to its model default. A field it carries replaces whole, a per-key tracked field included (`req-grid-flip-nested` rule 8), and an edge's `properties` included.
3. FLIP moves on the fields whose value changed, including a reset that changed the value (`req-grid-flip-change` rule 5), and on a field or key asserted for the first time (no entry yet). A field or key replaced with an identical value keeps its owner, a per-key tracked field and an edge's `properties` judged key by key (`req-grid-flip-nested` rule 8). The one exception is the narrow ownership rule: an entry written by a yielding write moves to the replacing batch when the replace confirms its value from a different source (`req-grift-yield` rules 7 and 8). Entries it writes are not yielded.
4. `on_missing` is `error`, `warn`, `ignore` or `create`.
5. There is no `on_other_source`. A full replace is a statement of the whole object and does not yield.
6. The envelope's `name` and `dimensions` are applied as for a record in `nodes`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grift-full-replace-1 | Omitted Is Reset | Proposed | A `replaces` record omitting an optional field that holds a value leaves it at the model default with a FLIP entry for the writing batch. | |
| req-grift-full-replace-2 | Required Still Required | Proposed | A `replaces` record lacking a required field is refused. | |
| req-grift-full-replace-3 | Same Record In Nodes Keeps It | Proposed | The same record in `nodes` leaves the omitted field's value. | The difference from upsert |
| req-grift-full-replace-4 | Edge Properties Replaced Whole | Proposed | An edge holding `{"a":1,"b":2}` sent in `replaces` with `{"b":3}` ends `{"b":3}`. | |
| req-grift-full-replace-5 | Identical Replace Moves No Owner | Proposed | Source B wrote a per-key tracked map `{"a":1,"b":2}` with `overwrite` (no entry yielded). Source A sends the same field as `{"a":1,"b":2}` in `replaces`: every key's entry is still B's, and no history row is written. Had B written `b` under `yield`, `b`'s entry alone would move to A, not yielded. | Rule 3; `req-grid-flip-nested` rule 8; Issue# 322 - tap |

## Collection Window
----
RID: `req-grift-collection-window`

Status: `Proposed`

A document says when the collector read each object it carries. The statement is a window, a start and an end on the collector's own clock, and it sits beside the record, never inside the fields the record writes. A batch may state one window for all its records, and a record may state its own in place of it. What the window means and what the grid does with it is `req-grid-entity-collection-time` (`spec-grid-entity.md`); this requirement specifies only how a document states it, and how an export writes it.

#### Status Details
Proposed; nothing is built. This is the GRIFT document form that `req-grid-entity-collection-time` rule 2 names, and that `req-grift-write-sections` rule 8 points at. The design was ruled by the owner on 2026-11-23, on Issue# 1284 - tap (Q50): all seven decisions (A to G, under Development) as recommended. Nothing in it is open.

What exists today (read at tap main `34fbda8a` and this branch at `662dcde1` with `git show`; nothing was run):

- The write-batch form is built. `WriteOperation.collected` (`tap_grid/service_types.py`) takes a `CollectionWindow(start, end)` beside the operation's `payload`, each bound a timezone-aware datetime or ISO 8601 text with a zone. `settle_window` (`tap_grid/collection_time.py`) turns it into the stored pair or into nothing and a `collection_time_not_recorded` warning (no zone, text that is not a time, end before start); `order_warnings` reports `collection_time_older_read` and `collection_time_out_of_order` and corrects nothing.
- The database refuses a half-set pair and an end before its start, on `Entity` and on `BatchEvent` (`req-grid-entity-collection-time` rule 6).
- The importer states no window. None of the `WriteOperation(...)` calls in `tap_grid/grift/importer.py` passes `collected`, so every row a GRIFT import names, collectors' included, leaves the import with an empty pair (`req-grid-entity-collection-time` rule 5 and its Status Details).
- The import result does not carry an operation's warnings to its caller (`req-grid-entity-event-time`, Status Details, the same gap for `event_time_not_stored`): the three `collection_time_*` warnings are raised in the write operation's result and go no further. Building this requirement includes carrying them into the import result's `warnings` (rules 9 and 10).
- The document has nowhere to put one. The schema's batch container admits `batch_entity`, `batch_node`, `nodes`, `edges`, `deletes`, `purges`, `contents` and `edge_cases`; a node or edge object admits `entity`, the payload and `retirement`; all refuse an unknown key (`tap_grid/schemas/grift-document.schema.json`). `GriftRemovalTarget` is one definition shared by the `deletes` and `purges` sections, so admitting `collected` on a delete target and refusing it on a purge target (rules 2 and 5) needs the purge section's items to name a target that does not admit it. The spine table in `spec-grid-entity.md` says the envelope does not carry `collected_start`, and it still does not.
- The exporter writes no collection time. `_entity_envelope` (`tap_grid/grift/exporter.py`) emits `entity_id`, `entity_type`, `dimensions` and `name` only; `grep collected` over the exporter finds nothing but the word "collection" in prose.
- The importer checks envelope times in code, not by the schema's `format` (no format checker is used): `_check_datetime` parses with Django's `parse_datetime`, and `_make_aware` gives a time with no zone the server's zone. A window must not take that path: a bound with no zone is not recorded (rule 9).

The rulings this follows, on Issue# 1284 - tap: the spine pair belongs to the latest batch to name the object, empty included, and a late older read moves it and warns (third set, 2026-11-22, which reverses the "does not move backwards" of the second set); a value that cannot be stored truthfully is left off with a warning, where the design record proposed a hard stop (first set, 2026-11-21); and this form's seven decisions (Q50, 2026-11-23).

Prior art read for the shape (each page opened on 2026-11-23):

- STIX 2.1 `observed-data` states one window, `first_observed` and `last_observed`, for a group of objects it references by `object_refs`, apart from those objects' own properties, and requires `last_observed` to be "greater than or equal to" `first_observed`; its timestamps "MUST be represented in the UTC timezone" (https://docs.oasis-open.org/cti/stix/v2.1/os/stix-v2.1-os.html, sections 2.16.1 and 4.14). That is the batch-level window.
- OpenTelemetry logs carry `ObservedTimestamp`, "Time when the event was observed by the collection system", on each record beside `Timestamp`, the source's time; the `Resource` shared by many records may be recorded "only once per batch" (https://opentelemetry.io/docs/specs/otel/logs/data-model/). That is the per-record window, with a batch-level shared part.
- Elastic Common Schema keeps `event.created`, "when the event was first read by an agent, or by your pipeline", apart from `@timestamp`, the time extracted from the event (https://www.elastic.co/guide/en/ecs/current/ecs-event.html). OCSF keeps `metadata.logged_time`, "when the logging system collected and logged the event", inside a `metadata` object apart from the event's fields (https://schema.ocsf.io/1.3.0/objects/metadata).
- FHIR keeps who-made-this-and-when in a separate `Provenance` resource that names its subjects by reference (`target`) and states `occurred[x]` as a period (https://hl7.org/fhir/R4/provenance.html). That is the keyed-map shape, set aside under Development. `meta.lastUpdated` is the receiving server's own time: "the server SHALL update this item to the current time on the server" (https://hl7.org/fhir/R4/resource.html), the same rule as the grid's `updated_at`, and not a collection time.
- CycloneDX states one `metadata.timestamp`, "when the BOM was created", for the whole document, and no per-component read time was found in the part of the schema page read (https://cyclonedx.org/docs/1.6/json/). A document-level time only.

#### Implementation

```json
{
  "batch_entity": { "entity_id": "0196...", "entity_type": "batch", "dimensions": {} },
  "batch_node": { "name": "aws inventory 2026-11-23", "source": "collector:aws_core" },
  "collected": { "start": "2026-11-23T14:00:02Z", "end": "2026-11-23T14:03:41Z" },
  "nodes": [
    { "entity": { "ref": "i-1", "entity_type": "aws_ec2_instance", "dimensions": {} },
      "node": { "instance_id": "i-0abc", "state": "running" } },
    { "entity": { "ref": "i-2", "entity_type": "aws_ec2_instance", "dimensions": {} },
      "node": { "instance_id": "i-0def", "state": "stopped" },
      "collected": { "start": "2026-11-23T14:05:10Z", "end": "2026-11-23T14:05:10Z" } },
    { "entity": { "ref": "i-3", "entity_type": "aws_ec2_instance", "dimensions": {} },
      "node": { "instance_id": "i-0fed", "state": "running" },
      "collected": null }
  ],
  "edges": []
}
```

Here `i-1` was read in the batch's window, `i-2` in a call of its own, and `i-3` states none (it came from a cache, say) and gets an empty pair.

```json
"GriftCollectionWindow": {
  "type": "object",
  "additionalProperties": false,
  "required": ["start", "end"],
  "properties": {
    "start": { "type": "string", "minLength": 1 },
    "end": { "type": "string", "minLength": 1 }
  }
}
```

1. **The window.** A collection window is an object with exactly `start` and `end`, both required, each an RFC 3339 date-time text with a zone (`Z` or an offset). `end` equals `start` when the object was read in one call. It carries no precision: its width is the precision (`req-grid-entity-collection-time` rule 1). **What it means on a row:** the row's window is the collection window asserted by the latest batch that addressed the row (`req-grid-entity-collection-time` rule 5). It says when that batch's collector read the object. It does not date every value the row holds: a batch that addressed the row and wrote nothing (a skipped insert, a fully yielded update), or wrote some fields of a row other sources wrote the rest of, moves the window and leaves values other batches wrote, read at other times. When a value was read is answered by its FLIP entry's batch and that batch's event for the object, which carries the window that batch stated.
2. **Where it sits.** The key is `collected`. It may appear:
   - on a batch container, as the batch's window;
   - on a node object and an edge object, in `nodes`, `edges` and the `nodes` and `edges` of `inserts`, `updates` and `replaces` (`req-grift-write-sections`), beside `entity`, the payload and `retirement`;
   - on a target in `deletes`, whether named by `entity_id` (`GriftRemovalTarget`) or by edge identity (`GriftEdgeRemovalByIdentity`).

   It never appears inside `node`, inside an edge's `properties`, inside the entity envelope, or inside `batch_node`. A model field that happens to be called `collected` is that model's own field and unrelated.
3. **Keyed by object through its record.** A record names one object, by `entity_id`, `ref`, natural key or edge identity, so a window on a record is keyed by that object, whichever way the record addresses it. This is the shape `WriteOperation.collected` has (`req-grid-entity-collection-time` Status Details) and the shape `retirement` already has in a document. There is no second map from object to window.
4. **Which window a record states.** For each record, in this order: the record's own `collected` when the record has the key; otherwise the batch's `collected` when the batch has one; otherwise none. A record's `"collected": null` states none and the batch's window does not apply to it. `null` is refused on a batch container, where leaving the key out says the same.
5. **Not on purges, not inferred.** `collected` on a `purges` target is refused: a purge removes the row and its batch events, so nothing would hold the window. The schema gives the purge section's items a target definition that does not admit the key, since `GriftRemovalTarget` is shared with `deletes` today. The batch's window does not apply to purge targets, to the edges a node's retirement ends (`req-grid-entity-collection-time`, Status Details, "As built"), to rows the dangling sweep tombstones, or to `edge_cases` claims, none of which is a record the batch stated a read for. A window is never taken from `batch_node.started_at` or `closed_at`, from the envelope's times, or from the import's reference time (`req-grid-entity-collection-time` rule 3).
6. **What the importer does with it.** The window a record states is passed as `WriteOperation.collected` on every operation the importer makes for that record: the create or the replace, and, for a record carrying a `retirement` block, the retirement after it, so the pair the batch leaves on the row is the stated one. A record that states none passes nothing. Everything after that is the write-batch form's, unchanged: the settling, the pair on the batch event and on the spine, the late-older-read warning, the order warnings.
7. **Every write that names the object.** The pair moves wherever the batch names the object, changed or not (`req-grid-entity-collection-time` rule 4). So the window is recorded for a record in `inserts` that finds its row and skips (`req-grift-insert-only` rule 7), for a record in `updates` all of whose fields are yielded (`req-grift-yield` rule 5), and for an unchanged record in `nodes`. In each of these the row keeps values another batch wrote, and the window is this batch's assertion of when it read the object, in the meaning rule 1 gives, not a date on those values. A record that writes nothing and names no row records nothing and is not warned about: `updates` or `replaces` with `on_missing` `ignore` or `warn` and no target, a `deletes` target skipped under `on_missing` or `on_tombstoned`, a batch skipped as `batch_already_imported`, and every record of a batch that fails.
8. **Validation of the shape.** These refuse the document at preflight with `schema_validation_failed`, naming the path, and write nothing: `collected` that is not an object (or `null` on a batch container); a missing `start` or `end`; any other key; a bound that is not a non-empty text; `collected` on a purge target, on `batch_node`, in the envelope, or anywhere rule 2 does not name; and `collected` anywhere in a document at format `"0"` (rule 12).
9. **Validation of the values.** A bound that does not read as a date-time, a bound with no zone, and an end before its start are not refusals. The window is not recorded, the record's row gets an empty pair as if it stated none, and the import result carries the `collection_time_not_recorded` warning with the reason, naming the record's path and object (`req-grid-entity-collection-time` rule 6, and the 2026-11-21 ruling that chose a warning over a hard stop). A bound with no zone is never given the server's zone, as `_make_aware` does for envelope times. The batch's window is settled once at preflight: when it cannot be recorded, the result carries one warning naming the batch and the number of records that relied on it, not one per record, and those records state none.
10. **Order is reported, not refused.** A window that ends after the time of the write, or before the object's event time starts, is written as stated and reported with `collection_time_out_of_order`; a window that ends before the one the row carries moves the pair and is reported with `collection_time_older_read`. Both reach the import result's warnings. Neither is a refusal: the import's reference time bounds the envelope's and the retirement block's times (`timestamp_in_future`), not collection time, which rule 7 of `req-grid-entity-collection-time` reports and never corrects. Two batches of one document that name one object are two writes in order, and the second's window is the one the row keeps.
11. **Never a field, never FLIP.** A window writes no typed field, no FLIP entry, no history row and no revision; it does not change `updated_at`, `last_changed_batch_id`, the entity's `version`, the event-time columns or the `tap.time` dimension. It is not a field for `on_other_source: yield` to judge, `on_existing` to protect or `entity_expected_version` to guard, and it makes no record a change that would otherwise be unchanged (`req-grid-history-reobservation`). A version conflict aborts the batch, and with it every window the batch stated.
12. **Format `"1"` only.** `collected` is part of format `"1"`, with the write sections (`req-grift-write-sections` rule 13). A document at format `"0"` that carries it is refused (rule 8), naming the key and that it needs format `"1"`. No released core reads format `"1"`, so adding the key now changes no reader in the field; adding it to `"0"` would make a released importer refuse a new document for an unknown key, not for the version it can name (`req-grift-header-versions` rule 10). It lands before 0.5.0, inside format `"1"`. Once a core that reads `"1"` is released, a key added after that needs format `"2"`; this one is not added to `"1"` after such a release without a new ruling.
13. **No version moves.** The spine columns exist already, so this form raises neither `spine_version` nor any type's version, and `type_versions` gains no entry for it. `contents` gains no aspect: a window is part of a record, not a kind of record, and an importer that does not read it refuses the key.
14. **The export states the spine pair.** The exporter writes `collected` on each node and edge object whose spine row has both `collected_start` and `collected_end`, from those two columns, in UTC; a row whose pair is empty gets no key, never `null`. It writes no `collected` on the batch it mints: that batch read nothing, and one window for rows read at many times would be false, which is the reason `req-tap-cares-collector-version` defers `metadata.collector` on an export. The per-pass pairs on batch events are not exported, as no other part of a batch's history is (`contents.history` is `included: false`). The pair is data about the row on the source grid, as a `retirement` block is data about its retirement, and the export carries it in the meaning rule 1 gives: the collection window asserted by the latest batch that addressed the row there. It is not a date on each value the exported object carries; a value may have been read by an earlier batch, at another time, and the export does not say which (per-value provenance is FLIP, which the export does not carry: `contents.flip` is `included: false`). Imported, it becomes the import batch's statement for that row in the same meaning, and the batch's `source` still says it is a capture (`req-grift-export`, "Honest provenance").
15. **Lands with its code.** The schema admits `collected` in the same change as the importer code that honours it and the exporter code that writes it, as `req-grift-edge-identity-surface-1` requires for its shapes: no window is accepted and dropped. The same change adds `GriftCollectionWindow` and the `collected` properties (on `GriftBatchContainer`, `GriftNodeObject`, `GriftEdgeObject`, the delete targets `GriftRemovalTarget` and `GriftEdgeRemovalByIdentity`, and not on a purge target) to this spec's JSON Schemas section; until then the fragment above is the definition.

#### Development
The owner ruled the seven decisions below on 2026-11-23 (Issue# 1284 - tap, Q50), each as it was recommended.

**A. Where the window sits: a batch-level `collected`, a per-record `collected` that takes its place, and `null` on a record to state none** (rules 2 to 4). One key, keyed by object through the record that already addresses it however it does, as the built `WriteOperation.collected` is; the batch window spares a one-pass collector from repeating itself and expands at preflight, so the grid still stores per object. Two alternatives were set aside:

- *A keyed map in the batch* (`"collection": {"default": {...}, "by_object": {"<entity_id>": {...}}}`), the FHIR `Provenance` shape and the one rule 2 of `req-grid-entity-collection-time` reads most literally. A record addressed by `ref`, natural key or edge identity has no `entity_id` in the document, so the map needs a second key form for each, resolved by its own lookup; a map key naming no record of the batch is a new failure to refuse; and the window sits away from the record it describes, which a reviewer of a diff has to join by hand. The per-record key is keyed by object through the record, which is how the built write-batch form already reads rule 2. FHIR's separation fits FHIR because a `Provenance` is a resource with a life of its own; a window is not.
- *Per record only, no batch window*: simpler, one way to say it, and the OpenTelemetry and ECS precedent. Not chosen because the common collector reads a whole account in one pass and would repeat one window on every record, which costs bytes and invites a record stamped from a different clock read than its neighbours; and a document written by hand would rarely state one at all. STIX states the window once for a group. The batch window is a shorthand expanded at preflight into per-object statements, so what the grid stores is per object either way.

Two other places were left out for the same reason, that the window must stay apart from what the record writes:

- *In the envelope* (`collected_start` / `collected_end` beside `created_at`). The envelope carries the spine's own fields, `name` and `dimensions` among them, which the write applies to the row; rule 2 keeps the window apart from what the object writes, and `spec-grid-entity.md` says the spine columns are not accepted in the envelope. The envelope's times are also validated and dropped, a different contract from one the grid records.
- *In `batch_node`* (the Batch model's fields, or a reserved key in its `metadata`). `batch_node` is the batch's typed payload; `started_at` and `closed_at` are the batch's own lifecycle, which rule 3 says a reader may use as a best estimate and the grid must never copy into the pair; and `metadata` is free-form, with `collector` its first reserved key, where a per-object fact has no place.

**B. Format `"1"` only** (rule 12). No released core reads `"1"`, so the key reaches no old reader, and an old reader refuses a new document for its version, which it can name. The consequence, accepted: a collector can state a window only once it writes format `"1"`, which ties the collector sweep (Issue# 1289 - tap) to the fleet move (Issue# 1288 - tap). Allowing the key at `"0"` would not loosen that, because every released core refuses it there as an unknown key, so a plugin's floor must be raised either way.

**C. A window whose values are wrong warns; only a malformed shape refuses** (rules 8 and 9). The window is dropped, the row gets an empty pair, and the document imports. It is the rule the grid already holds for the same value (`req-grid-entity-collection-time` rule 6), chosen by the owner on 2026-11-21 over the design record's hard stop, and one bad clock read should not cost a whole collection. Refusing at preflight, as GRIFT refuses `updated_at` before `created_at` (`timestamp_order_invalid`), was considered: it is stricter than the grid's own rule for the same value, and a collector with a broken clock is caught by the warning.

**D. An export states windows, per object from the spine pair, never at batch level** (rule 14). The pair is the window asserted by the latest batch that addressed the row, not a date on each of its values (rule 1), and the export carries it with that meaning; leaving it out would empty every pair on a replay (`req-grid-entity-collection-time` rule 5), a loss with nothing gained. The reason the collector-version spec deferred `metadata.collector` (one capture batch would claim one collector for many) does not apply to a per-object fact, and it is why the export writes no batch window.

**E. Removals: a `deletes` target may state a window and inherits the batch's; a `purges` target may not** (rules 2 and 5). The write-batch form already records a window on a retirement, and a collector that deletes what it found gone read that absence in its pass; a purge erases the events that would hold it. The cost, accepted: a hand-written cleanup batch with a window stamps its deletes too; an author who does not mean that puts the deletes in a batch of their own.

**F. Timing: this lands with the write sections, before 0.5.0, inside format `"1"`** (rule 12). After a core that reads `"1"` is released, a new key needs format `"2"`.

**G. Cross-references, amended in the same change as this requirement:** `req-grid-entity-collection-time` rule 2 and its Status Details "Not built" bullet name this requirement as the document form; the Notes of `req-grid-entity-collection-time-3` no longer say a document cannot state one; `req-grift-write-sections` rule 8 cites this RID; and the issue-code list in `spec-grid-import-grift.md` admits the three `collection_time_*` warnings in an import result.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grift-collection-window-1 | A Record States Its Window | Proposed | A node in `nodes` with `collected` creates a row whose spine pair, and whose batch event's pair, are the stated window in UTC; the node's typed fields and `flip_map` are what they would be without the key. | |
| req-grift-collection-window-2 | The Batch Window Applies | Proposed | In a batch with `collected` and three nodes, one with its own window, one with none and one with `"collected": null`, the rows' pairs are the record's window, the batch window and empty, in that order. | Rule 4 |
| req-grift-collection-window-3 | No Window Is An Empty Pair | Proposed | A batch and records stating no window leave every row's pair empty, and neither bound equals the import's reference time or the batch's `started_at`. | Rule 5; `req-grid-entity-collection-time-2` |
| req-grift-collection-window-4 | Every Section | Proposed | A node and an edge in each of `inserts`, `updates` and `replaces` with `collected` each record it; an `inserts` record that finds its row and skips, and an `updates` record all of whose fields are yielded, move the pair and write no history row. | Rule 7; needs the write sections |
| req-grift-collection-window-5 | Edges And Retirements | Proposed | An edge object with `collected` records it on the edge's row; a `deletes` node target with `collected` records it on the retired node, and the edges the retirement ends have an empty pair; a record carrying a `retirement` block leaves the stated window on the retired row. | |
| req-grift-collection-window-6 | Shape Refused | Proposed | `collected` with a missing `end`, an extra key, a number as a bound, on a purge target, inside `node`, inside the envelope, or `null` on a batch container refuses the document with `schema_validation_failed` naming the path, and writes nothing. | Rule 8 |
| req-grift-collection-window-7 | Bad Values Warn | Proposed | A record whose window has an end before its start, a bound with no zone, or a bound that is not a time imports with an empty pair and a `collection_time_not_recorded` warning in the import result naming the path; a batch window with no zone gives one warning naming the batch and the count of records that relied on it. | Rule 9; Decision C |
| req-grift-collection-window-8 | Late Older Read Warns | Proposed | A document whose window ends before the one the row carries moves the pair to it and the import result carries `collection_time_older_read` naming the object and both windows; a window ending after the time of the write is written and the import result carries `collection_time_out_of_order`. | Rule 10 |
| req-grift-collection-window-9 | Never A Field | Proposed | Re-importing an unchanged record with a new window moves only the pair and `last_observed_*`: version, `updated_at`, `last_changed_batch_id`, history count, `flip_map`, the event-time columns and `tap.time` are unmoved. | Rule 11; `req-grid-entity-collection-time-3` through a document |
| req-grift-collection-window-10 | Format 0 Refuses It | Proposed | A document at format `"0"` carrying `collected` anywhere is refused, naming the key and format `"1"`; the same document at `"1"` imports. | Rule 12 |
| req-grift-collection-window-11 | Export Writes The Pair | Proposed | Exporting a grid with one row whose pair is set and one whose pair is empty writes `collected` with the pair in UTC on the first object, no key on the second, and no `collected` on the batch. | Rule 14 |
| req-grift-collection-window-12 | Round Trip Keeps The Pair | Proposed | Importing that export into an empty grid gives each row the source's pair, and each of the import batch's events the same pair, with no warning. | Rule 14 |
| req-grift-collection-window-13 | A Skipped Insert Moves The Window, Not The Value | Proposed | Source B's batch stores `state: "new"` on a row with a window of today. Source A's `inserts` record for the same row, `state: "old"`, collected yesterday, is skipped: the row keeps `"new"` and B's FLIP entry, its spine pair is A's window (yesterday) with `collection_time_older_read` in the result, and B's batch event still carries today's window. Exported, the object carries `state: "new"` and `collected` with A's window, which under rule 14 is the window of the latest batch that addressed the row, not the time `"new"` was read. | Rules 1, 7 and 14; `req-grift-insert-only` rule 7 |
| req-grift-collection-window-14 | A Partial Update To A Mixed-Source Row | Proposed | A row whose `image` is source B's and whose `owner` is source A's. A's `updates` record carrying only `owner`, with a window, writes `owner` and moves the spine pair to A's window; `image` keeps B's value and entry, and B's batch event keeps B's window, which is where the read time of `image` is found. | Rules 1 and 7 |

## Stored Files
----
RID: `req-grift-stored-files`

Status: `Backlog`

A node may represent a file whose bytes are kept in the file store (`specs/spec-tap-file-store.md`)
and not in the database. GRIFT is JSON and carries no bytes, so today a batch that includes such a
node carries the node, with the file's digest, size and file version, and nothing else. Imported into
another grid, the node arrives and the file does not.

How files move between grids is not designed (ruled 2026-11-16: recorded here as backlog). The
questions it has to settle:

- **What the document carries.** The closest prior art is the Git LFS pointer: the interchange
  document carries a small record of digest and size, the bytes travel by a separate channel, and the
  receiver says which digests it lacks before anything is sent.
- **What an import does when the bytes are absent.** Refuse the node, or accept it and record that
  its content is not held. The second needs a third state on the node beside "no file" and "file
  held", in line with the rule that absence is declared and never invented as a value
  (`req-grid-node-observation`).
- **What an export bundles.** Whether an export may produce the files beside the batch, and in what
  layout. The file store's own directory is already a self-describing standard layout, which makes a
  copy of the relevant objects a candidate.
- **Integrity across the move.** The digest on the node is the check that the bytes that arrived are
  the bytes that left.

## v0 Non-Goals
----
RID: `req-grift-v0-nongoals`

Status: `Implemented`

GRIFT v0 explicitly does not define:

- history replay import
- FLIP transport or import
- host transaction timestamp transport
- semantic dedupe beyond `entity_id`
- content hashing for batch equivalence
- source plugin metadata
- actor federation across grids

Future versions may extend `_reserved`, document metadata, and batch comparison behavior without changing the basic entity-envelope-plus-payload model introduced here.
