# GRIFT v0 Specification

## Philosophy

GRIFT, the Grid Interchange Format, is TAP's JSON-based interchange format for moving graph data between files and grids. GRIFT v0 is intentionally small, strict, and practical: it should be easy to validate, easy to diff, and sufficient to refactor plugin seed data such as the LOTR dataset into portable JSON files.

GRIFT's node and edge lanes are full-object interchange: they do not describe patches, history replay, or FLIP state. They carry enough canonical information for an importer to choose its own create, replace, upsert, or skip behavior while preserving universal entity identity through `entity_id`. GRIFT's removal lanes are explicit identity-targeted operations, declared separately from node and edge upserts.

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
    }
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
        "grift_version": {
          "type": "string",
          "minLength": 1
        }
      }
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
| req-grift-validation | [Validation Rules](#validation-rules) | Implemented | Strict schema and sanity rules |
| req-grift-seed-ids | [Seed Data ID Convention](#seed-data-id-convention) | Deprecated | Superseded by [spec-grid-uuid-selection.md](spec-grid-uuid-selection.md) and [spec-grift-seed-ids-real-uuid7.md](spec-grift-seed-ids-real-uuid7.md) |
| req-grift-order | [Canonical Export Ordering](#canonical-export-ordering) | Backlog | Export ordering (no exporter yet) |
| req-grift-import-deletes | [Imperative Removal Sections](#imperative-removal-sections) | Approved for Development | Explicit batch-level delete and purge operations; not desired-state reconciliation |
| req-grift-concurrency-version | [Optimistic Concurrency Via Expected Version](#optimistic-concurrency-via-expected-version) | Implemented | Optional `entity_expected_version` on any mutating target declares the local `Entity.version` the sender expects; the importer aborts the batch on mismatch |
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

- `grift_version`: string, required

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
- `deleted_at` is optional; if present it is validated for timestamp sanity (see below) but **not applied** by node or edge upsert. An envelope's `deleted_at` does not mark the imported entity deleted. Import-time deletion intent is declared only through the batch-level `deletes` section, and hard-delete intent only through the batch-level `purges` section.
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

Each node object is a full serialized TAP node.

### Node Shape

Each item in `nodes` is an object with exactly these keys:

- `entity`
- `node`

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

Each item in `edges` is an object with exactly these keys:

- `entity`
- `edge`

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

## Validation Rules
----
RID: `req-grift-validation`
Status: `Implemented`

GRIFT v0 is intentionally strict.

### General Rules

- Unknown keys are rejected at every level except `_reserved`
- `_reserved` is reserved for future extension; v0 importers must ignore its contents
- All wrapper keys are part of validation, not informal hints
- Duplicate `entity_id` values anywhere in the file are invalid
- Duplicate batch `entity_id` values are invalid
- Wrapper arrays are always present, even when empty

Importer workflow, reference resolution, datetime comparison timing, and batch execution behavior are defined separately in the GRIFT importer specification.

## Seed Data ID Convention
----
RID: `req-grift-seed-ids`
Status: `Deprecated`

This requirement previously codified a hand-authored "synthetic UUIDv7" convention for plugin seed `entity_id` values: a fixed plugin-wide timestamp prefix, zeroed `rand_a`, zeroed high bits of `rand_b`, and a hand-curated counter tail. That convention produced UUIDs that were structurally not unique — humans pick low numbers, and on 2026-04-27 a collision in the genericom plugin proved the failure mode.

The convention is replaced by:

- [spec-grid-uuid-selection.md](spec-grid-uuid-selection.md) — defines the menu of allowed UUID schemes (v7, v5, v4) and the criteria for choosing one. UUIDs in seed data are organic `uuid.uuid7()` values; mirrored external identity uses `uuid.uuid5(namespace, key)` with an organic v7 namespace.
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
