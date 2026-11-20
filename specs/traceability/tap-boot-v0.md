<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `specs/spec-tap-boot-v0.md`

| Bucket | Count |
| --- | ---: |
| mapped | 8 |
| excluded | 1 |
| unbuilt | 8 |
| unaccounted | 8 |
| 0-ACID (payable) | 0 |

## Exclusions

Reasons verbatim from each `Trace:` line; ⚠ marks zero-ACID exempt.

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-boot-spawn-bridge` | non-python |  | scripts/spawn-session.sh |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-boot-app` | Implemented | Implemented | `<module>`, `<module>` | — |
| `req-boot-phases` | Implemented | Verified | `<module>` | `req-boot-phases-5`, `req-boot-phases-6`, `req-boot-phases-7` |
| `req-boot-profile` | Implemented | Verified | `<module>` | `req-boot-profile-6` |
| `req-boot-required-secrets` | Implemented | Implemented | `<module>` | — |
| `req-boot-schema-from-models` | Implemented | Verified | `<module>`, `<module>` | `req-boot-schema-from-models-1`, `req-boot-schema-from-models-2`, `req-boot-schema-from-models-3`, `req-boot-schema-from-models-4`, `req-boot-schema-from-models-5`, `req-boot-schema-from-models-6` |
| `req-boot-search-role` | Implemented | Implemented | `<module>` | — |
| `req-boot-web-branding` | Implemented | Verified | `branding_from_section` | `req-boot-web-branding-1`, `req-boot-web-branding-3`, `req-boot-web-branding-4`, `req-boot-web-branding-5`, `req-boot-web-branding-6`, `req-boot-web-branding-7` |
| `req-boot-web-section` | Implemented | Verified | `landing_from_section` | `req-boot-web-section-1`, `req-boot-web-section-2`, `req-boot-web-section-3`, `req-boot-web-section-4` |
