<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_grid/specs/spec-grid-edge.md`

| Bucket | Count |
| --- | ---: |
| mapped | 4 |
| unbuilt | 1 |
| unaccounted | 7 |
| 0-ACID (payable) | 2 |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-grid-edge-identity` | Implemented | Verified | `_resolve_edge_identities`, `resolve_edge_identity` | `req-grid-edge-identity-7` |
| `req-grid-edge-identity-declaration` | Proposed | Verified | `parse_edge_identity`, `register_edge_identity` | `req-grid-edge-identity-declaration-1`, `req-grid-edge-identity-declaration-2`, `req-grid-edge-identity-declaration-3`, `req-grid-edge-identity-declaration-4`, `req-grid-edge-identity-declaration-6`, `req-grid-edge-identity-declaration-7` |
| `req-grid-edge-produced-batch-claims` | Proposed | Tested | — | `req-grid-edge-produced-batch-claims-1` |
| `req-grid-edge-schema-required` | Proposed | Implemented | `validate_edge_properties` | — |
