<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `specs/spec-wog.md`

| Bucket | Count |
| --- | ---: |
| mapped | 5 |
| 0-ACID (payable) | 0 |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-wog-citation` | Implemented | Implemented | `Entry.citation` | — |
| `req-wog-entry-shape` | Implemented | Verified | `WogEntryShapeGuard.check` | `req-wog-entry-shape-1` |
| `req-wog-identity` | Implemented | Implemented | `WogNameUniquenessGuard.check` | — |
| `req-wog-resolution` | Implemented | Implemented | `WogCitationResolutionGuard.check` | — |
| `req-wog-tiers` | Implemented | Verified | `entries` | `req-wog-tiers-1` |
