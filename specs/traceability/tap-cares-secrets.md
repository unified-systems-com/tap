<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_cares/specs/spec-tap-cares-secrets.md`

| Bucket | Count |
| --- | ---: |
| mapped | 11 |
| excluded | 6 |
| unbuilt | 3 |
| unaccounted | 2 |
| 0-ACID (payable) | 4 |

## Exclusions

Reasons verbatim from each `Trace:` line; ⚠ marks zero-ACID exempt.

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-tap-cares-secrets-consumer-kinds` | narrative | ⚠ | the mechanics-vs-kinds ownership split; each side's substance is specified elsewhere |
| `req-tap-cares-secrets-cross-scope-concern` | narrative | ⚠ | documents a deliberately deferred control; nothing derives it until the least-privilege work lands |
| `req-tap-cares-secrets-history-audit` | process | ⚠ | a completed, human-triaged pre-publication audit; the record is the artifact |
| `req-tap-cares-secrets-precommit` | non-python | ⚠ | .githooks/precommit_secret_scan.py |
| `req-tap-cares-secrets-scope` | narrative | ⚠ | the umbrella statement; the checkable substance lives in the sibling requirements |
| `req-tap-cares-secrets-validation` | narrative | ⚠ | a deliberate non-centralization ruling; consumers own kind-specific validation |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-tap-cares-secrets-credential-patterns` | Implemented | Implemented | `<module>` | — |
| `req-tap-cares-secrets-files` | Verified | Verified | `<module>` | `req-tap-cares-secrets-files-1`, `req-tap-cares-secrets-files-2` |
| `req-tap-cares-secrets-leak-guard` | Implemented | Implemented | `<module>` | — |
| `req-tap-cares-secrets-redaction` | Verified | Verified | `<module>` | `req-tap-cares-secrets-redaction-1`, `req-tap-cares-secrets-redaction-2` |
| `req-tap-cares-secrets-registry` | Verified | Verified | `<module>` | `req-tap-cares-secrets-registry-1` |
| `req-tap-cares-secrets-resilient-load` | Verified | Verified | `<module>` | `req-tap-cares-secrets-resilient-load-1`, `req-tap-cares-secrets-resilient-load-2`, `req-tap-cares-secrets-resilient-load-3` |
| `req-tap-cares-secrets-root-resolution` | Verified | Verified | `resolve` | `req-tap-cares-secrets-root-resolution-1`, `req-tap-cares-secrets-root-resolution-2` |
| `req-tap-cares-secrets-rotation` | Implemented | Implemented | `<module>` | — |
| `req-tap-cares-secrets-shape` | Implemented | Tested | — | `req-tap-cares-secrets-shape-1`, `req-tap-cares-secrets-shape-2`, `req-tap-cares-secrets-shape-3`, `req-tap-cares-secrets-shape-4` |
| `req-tap-cares-secrets-size-guard` | Verified | Verified | `load_secret_envelope` | `req-tap-cares-secrets-size-guard-1` |
| `req-tap-cares-secrets-store-shape` | Implemented | Verified | `report_stray_store_files` | `req-tap-cares-secrets-store-shape-1`, `req-tap-cares-secrets-store-shape-2`, `req-tap-cares-secrets-store-shape-3` |
