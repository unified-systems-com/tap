<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `specs/spec-tap-requirement-traceability.md`

| Bucket | Count |
| --- | ---: |
| mapped | 11 |
| excluded | 1 |
| unaccounted | 1 |
| 0-ACID (payable) | 0 |

## Exclusions

Reasons verbatim from each `Trace:` line; ⚠ marks zero-ACID exempt.

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-tap-traceability-minting` | non-python |  | scripts/implements-tag |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-tap-traceability-accounting` | Implemented | Implemented | `<module>`, `bucket_of`, `render_accounting_markdown` | — |
| `req-tap-traceability-acid-floor` | Implemented | Implemented | `<module>` | — |
| `req-tap-traceability-claim` | Implemented | Implemented | `<module>`, `collect_claims` | — |
| `req-tap-traceability-code-staleness` | Implemented | Implemented | `<module>`, `code_hash_of` | — |
| `req-tap-traceability-disposition` | Implemented | Implemented | `<module>`, `_parse_disposition` | — |
| `req-tap-traceability-disputed` | Implemented | Implemented | `disputed` | — |
| `req-tap-traceability-fragments` | Implemented | Verified | `render_traceability_fragments`, `sync_traceability_fragments`, `fragment_drift` | `req-tap-traceability-fragments-1`, `req-tap-traceability-fragments-3`, `req-tap-traceability-fragments-4` |
| `req-tap-traceability-roles` | Implemented | Implemented | `<module>` | — |
| `req-tap-traceability-staleness` | Implemented | Implemented | `<module>`, `stale_claims` | — |
| `req-tap-traceability-status` | Implemented | Implemented | `<module>`, `collect_evidence`, `render_evidence_markdown` | — |
| `req-tap-traceability-uniqueness` | Implemented | Implemented | `<module>`, `duplicate_claim_groups` | — |
