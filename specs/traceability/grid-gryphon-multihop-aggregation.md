<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_grid/specs/spec-grid-gryphon-multihop-aggregation.md`

| Bucket | Count |
| --- | ---: |
| mapped | 9 |
| unbuilt | 1 |
| unaccounted | 1 |
| 0-ACID (payable) | 0 |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-grid-gryphon-count` | Implemented | Implemented | `_compute_rows` | — |
| `req-grid-gryphon-limit` | Implemented | Tested | — | `req-grid-gryphon-limit-1`, `req-grid-gryphon-limit-2`, `req-grid-gryphon-limit-3` |
| `req-grid-gryphon-multihop` | Implemented | Implemented | `_build_chain_queryset` | — |
| `req-grid-gryphon-multihop-envelope` | Implemented | Implemented | `_build_chain_queryset` | — |
| `req-grid-gryphon-not-exists` | Implemented | Implemented | `_apply_not_exists` | — |
| `req-grid-gryphon-optional-match` | Implemented | Implemented | `_execute_optional_match` | — |
| `req-grid-gryphon-order-by` | Implemented | Implemented | `_resolve_order_cols` | — |
| `req-grid-gryphon-order-by-envelope` | Implemented | Implemented | `_apply_order_limit_typescan_envelope` | — |
| `req-grid-gryphon-rows` | Implemented | Implemented | `_compute_rows` | — |
