<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_grid/specs/spec-grid-entity.md`

| Bucket | Count |
| --- | ---: |
| mapped | 13 |
| unbuilt | 7 |
| retired | 1 |
| unaccounted | 2 |
| 0-ACID (payable) | 0 |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-grid-entity-base` | Implemented | Tested | — | `req-grid-entity-base-4` |
| `req-grid-entity-batch-pointers` | In Development | Implemented | `_pointer_batch` | — |
| `req-grid-entity-collection-time` | In Development | Verified | `settle_window` | `req-grid-entity-collection-time-1` |
| `req-grid-entity-crud` | Implemented | Tested | — | `req-grid-entity-crud-2` |
| `req-grid-entity-event-time` | In Development | Implemented | `derive` | — |
| `req-grid-entity-internal` | Implemented | Tested | — | `req-grid-entity-internal-2` |
| `req-grid-entity-model-version` | In Development | Verified | `complete_start_checks`, `register_type` | `req-grid-entity-model-version-23` |
| `req-grid-entity-natural-key` | Proposed | Verified | `resolve_identity` | `req-grid-entity-natural-key-13`, `req-grid-entity-natural-key-14`, `req-grid-entity-natural-key-15`, `req-grid-entity-natural-key-16`, `req-grid-entity-natural-key-17`, `req-grid-entity-natural-key-18`, `req-grid-entity-natural-key-26`, `req-grid-entity-natural-key-27` |
| `req-grid-entity-resolve` | Implemented | Tested | — | `req-grid-entity-resolve-2`, `req-grid-entity-resolve-3`, `req-grid-entity-resolve-4` |
| `req-grid-entity-spine` | Implemented | Tested | — | `req-grid-entity-spine-4` |
| `req-grid-entity-spine-version` | In Development | Implemented | `record_after_migrate` | — |
| `req-grid-entity-type` | Implemented | Tested | — | `req-grid-entity-type-2`, `req-grid-entity-type-3` |
| `req-grid-entity-validation` | Implemented | Tested | — | `req-grid-entity-validation-10`, `req-grid-entity-validation-11`, `req-grid-entity-validation-12`, `req-grid-entity-validation-14`, `req-grid-entity-validation-15`, `req-grid-entity-validation-6`, `req-grid-entity-validation-7`, `req-grid-entity-validation-8`, `req-grid-entity-validation-9` |
