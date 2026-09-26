<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_grid/specs/spec-grid-traversal-execution.md`

| Bucket | Count |
| --- | ---: |
| mapped | 6 |
| unbuilt | 5 |
| unaccounted | 2 |
| 0-ACID (payable) | 0 |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-grid-traversal-exec-pipeline` | Implemented | Tested | — | `req-grid-traversal-exec-pipeline-4` |
| `req-grid-traversal-exec-read-scope` | Partially Implemented | Verified | `entity_scope_filters`, `assert_query_scoped` | `req-grid-traversal-exec-read-scope-1`, `req-grid-traversal-exec-read-scope-12`, `req-grid-traversal-exec-read-scope-14`, `req-grid-traversal-exec-read-scope-2`, `req-grid-traversal-exec-read-scope-3`, `req-grid-traversal-exec-read-scope-4`, `req-grid-traversal-exec-read-scope-5`, `req-grid-traversal-exec-read-scope-6`, `req-grid-traversal-exec-read-scope-7`, `req-grid-traversal-exec-read-scope-8`, `req-grid-traversal-exec-read-scope-9` |
| `req-grid-traversal-exec-row-materialization` | Implemented | Implemented | `materialize_rows` | — |
| `req-grid-traversal-exec-scope.sec` | Implemented | Tested | — | `req-grid-traversal-exec-scope.sec-3`, `req-grid-traversal-exec-scope.sec-4` |
| `req-grid-traversal-exec-sql-capture` | Implemented | Implemented | `explain_gryphon_raw` | — |
| `req-grid-traversal-exec-temporal-scope` | — | Tested | — | `req-grid-traversal-exec-temporal-scope-1` |
