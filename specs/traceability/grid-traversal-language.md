<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_grid/specs/spec-grid-traversal-language.md`

| Bucket | Count |
| --- | ---: |
| mapped | 14 |
| unbuilt | 1 |
| unaccounted | 5 |
| 0-ACID (payable) | 3 |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-grid-traversal-lang-bare-match` | Implemented | Implemented | `_execute_bare_type_scan` | — |
| `req-grid-traversal-lang-combinators` | Implemented | Implemented | `_apply_predicate_to_qs` | — |
| `req-grid-traversal-lang-envelope-paths` | In Development | Implemented | `_resolve_orm_path` | — |
| `req-grid-traversal-lang-filters` | Implemented | Implemented | `_apply_predicate_to_qs` | — |
| `req-grid-traversal-lang-in` | Implemented | Implemented | `InComparison` | — |
| `req-grid-traversal-lang-is-null` | Implemented | Implemented | `IsNullComparison` | — |
| `req-grid-traversal-lang-observation` | Implemented | Implemented | `ObservationComparison` | — |
| `req-grid-traversal-lang-params` | Implemented | Implemented | `GryphonAST.required_params` | — |
| `req-grid-traversal-lang-patterns` | Implemented | Implemented | `_execute_type_scan` | — |
| `req-grid-traversal-lang-regex` | Implemented | Implemented | `_comparison_to_q` | — |
| `req-grid-traversal-lang-returns` | Implemented | Implemented | `_is_graph_envelope_return` | — |
| `req-grid-traversal-lang-shape` | Implemented | Tested | — | `req-grid-traversal-lang-shape-6` |
| `req-grid-traversal-lang-storage` | Implemented | Tested | — | `req-grid-traversal-lang-storage-3` |
| `req-grid-traversal-lang-string-match` | Implemented | Implemented | `_comparison_to_q` | — |
