<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_grid/specs/spec-grid-traversal-language.md`

| Bucket | Count |
| --- | ---: |
| mapped | 16 |
| unbuilt | 1 |
| unaccounted | 5 |
| 0-ACID (payable) | 3 |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-grid-traversal-lang-bare-match` | Implemented | Implemented | `_execute_bare_type_scan` | — |
| `req-grid-traversal-lang-combinators` | Implemented | Implemented | `_apply_predicate_to_qs` | — |
| `req-grid-traversal-lang-envelope-paths` | In Development | Implemented | `_resolve_orm_path` | — |
| `req-grid-traversal-lang-filters` | Implemented | Verified | `_apply_predicate_to_qs` | `req-grid-traversal-lang-filters-1` |
| `req-grid-traversal-lang-in` | Implemented | Implemented | `InComparison` | — |
| `req-grid-traversal-lang-is-null` | Implemented | Implemented | `IsNullComparison` | — |
| `req-grid-traversal-lang-observation` | Implemented | Implemented | `ObservationComparison` | — |
| `req-grid-traversal-lang-param-null` | Implemented | Implemented | `_fold_param_predicates` | — |
| `req-grid-traversal-lang-params` | Implemented | Implemented | `GryphonAST.required_params` | — |
| `req-grid-traversal-lang-patterns` | Implemented | Implemented | `_execute_type_scan` | — |
| `req-grid-traversal-lang-regex` | Implemented | Implemented | `_comparison_to_q` | — |
| `req-grid-traversal-lang-returns` | Implemented | Implemented | `_is_graph_envelope_return` | — |
| `req-grid-traversal-lang-shape` | Implemented | Verified | `_repeated_variable_equality_filters` | `req-grid-traversal-lang-shape-6` |
| `req-grid-traversal-lang-storage` | Implemented | Tested | — | `req-grid-traversal-lang-storage-3` |
| `req-grid-traversal-lang-string-match` | Implemented | Implemented | `_comparison_to_q` | — |
| `req-grid-traversal-lang-temporal-offset` | Implemented | Verified | `TemporalComparison`, `_temporal_to_q` | `req-grid-traversal-lang-temporal-offset-1`, `req-grid-traversal-lang-temporal-offset-10`, `req-grid-traversal-lang-temporal-offset-11`, `req-grid-traversal-lang-temporal-offset-12`, `req-grid-traversal-lang-temporal-offset-13`, `req-grid-traversal-lang-temporal-offset-14`, `req-grid-traversal-lang-temporal-offset-15`, `req-grid-traversal-lang-temporal-offset-16`, `req-grid-traversal-lang-temporal-offset-17`, `req-grid-traversal-lang-temporal-offset-18`, `req-grid-traversal-lang-temporal-offset-19`, `req-grid-traversal-lang-temporal-offset-2`, `req-grid-traversal-lang-temporal-offset-20`, `req-grid-traversal-lang-temporal-offset-21`, `req-grid-traversal-lang-temporal-offset-22`, `req-grid-traversal-lang-temporal-offset-23`, `req-grid-traversal-lang-temporal-offset-24`, `req-grid-traversal-lang-temporal-offset-25`, `req-grid-traversal-lang-temporal-offset-3`, `req-grid-traversal-lang-temporal-offset-4`, `req-grid-traversal-lang-temporal-offset-5`, `req-grid-traversal-lang-temporal-offset-6`, `req-grid-traversal-lang-temporal-offset-7`, `req-grid-traversal-lang-temporal-offset-8`, `req-grid-traversal-lang-temporal-offset-9` |
