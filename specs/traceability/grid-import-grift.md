<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_grid/specs/spec-grid-import-grift.md`

| Bucket | Count |
| --- | ---: |
| mapped | 12 |
| unbuilt | 3 |
| unaccounted | 2 |
| 0-ACID (payable) | 4 |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-grid-import-grift-batch` | Implemented | Implemented | `_execute_grift_batch` | — |
| `req-grid-import-grift-batch-scoped-sweep` | Implemented | Implemented | `_run_batch_scoped_sweep` | — |
| `req-grid-import-grift-dangling` | Implemented | Tested | — | `req-grid-import-grift-dangling-1` |
| `req-grid-import-grift-force-reimport` | Implemented | Tested | — | `req-grid-import-grift-force-reimport-1` |
| `req-grid-import-grift-identity` | Implemented | Tested | — | `req-grid-import-grift-identity-1`, `req-grid-import-grift-identity-2` |
| `req-grid-import-grift-preflight` | Implemented | Implemented | `_run_preflight` | — |
| `req-grid-import-grift-provenance` | Implemented | Tested | — | `req-grid-import-grift-provenance-1` |
| `req-grid-import-grift-removal-preflight` | Verified | Verified | `_validate_removal_section` | `req-grid-import-grift-removal-preflight-1` |
| `req-grid-import-grift-removals` | Implemented | Tested | — | `req-grid-import-grift-removals-1`, `req-grid-import-grift-removals-2` |
| `req-grid-import-grift-results` | Implemented | Implemented | `GriftImportResult` | — |
| `req-grid-import-grift-scope` | Implemented | Implemented | `<module>` | — |
| `req-grid-import-grift-sweep-purge` | Implemented | Implemented | `_apply_sweep_purge` | — |
