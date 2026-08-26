<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_grid/specs/spec-grid-traversal-execution.md`

| Bucket | Count |
| --- | ---: |
| mapped | 4 |
| unbuilt | 4 |
| unaccounted | 2 |
| 0-ACID (payable) | 0 |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-grid-traversal-exec-pipeline` | Implemented | Tested | — | `req-grid-traversal-exec-pipeline-4` |
| `req-grid-traversal-exec-row-materialization` | Implemented | Implemented | `materialize_rows` | — |
| `req-grid-traversal-exec-scope.sec` | Implemented | Tested | — | `req-grid-traversal-exec-scope.sec-3`, `req-grid-traversal-exec-scope.sec-4` |
| `req-grid-traversal-exec-sql-capture` | Implemented | Implemented | `explain_gryphon_raw` | — |
