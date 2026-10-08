<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_grid/specs/spec-grid-edge.md`

| Bucket | Count |
| --- | ---: |
| mapped | 5 |
| unbuilt | 1 |
| unaccounted | 7 |
| 0-ACID (payable) | 2 |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-grid-edge-identity` | Implemented | Verified | `_resolve_edge_identities`, `resolve_edge_identity` | `req-grid-edge-identity-4`, `req-grid-edge-identity-7` |
| `req-grid-edge-identity-declaration` | Proposed | Verified | `register_edge_identity`, `check_edge_identity` | `req-grid-edge-identity-declaration-1`, `req-grid-edge-identity-declaration-2`, `req-grid-edge-identity-declaration-3`, `req-grid-edge-identity-declaration-4`, `req-grid-edge-identity-declaration-6`, `req-grid-edge-identity-declaration-7` |
| `req-grid-edge-internal` | Implemented | Verified | `is_internal_edge_type`, `_refuse_internal_edge_type` | `req-grid-edge-internal-3`, `req-grid-edge-internal-5`, `req-grid-edge-internal-7` |
| `req-grid-edge-produced-batch-claims` | Implemented | Verified | `_link_produced_batches` | `req-grid-edge-produced-batch-claims-1`, `req-grid-edge-produced-batch-claims-5` |
| `req-grid-edge-schema-required` | Proposed | Implemented | `validate_edge_properties` | — |
