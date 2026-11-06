<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `specs/spec-tap-boot-v0.md`

| Bucket | Count |
| --- | ---: |
| mapped | 7 |
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
| `req-boot-phases` | Implemented | Implemented | `<module>` | — |
| `req-boot-profile` | Implemented | Verified | `<module>` | `req-boot-profile-6` |
| `req-boot-required-secrets` | Implemented | Implemented | `<module>` | — |
| `req-boot-search-role` | Implemented | Implemented | `<module>` | — |
| `req-boot-web-branding` | Implemented | Verified | `branding_from_section` | `req-boot-web-branding-1`, `req-boot-web-branding-3`, `req-boot-web-branding-4`, `req-boot-web-branding-5`, `req-boot-web-branding-6`, `req-boot-web-branding-7` |
| `req-boot-web-section` | Implemented | Verified | `landing_from_section` | `req-boot-web-section-1`, `req-boot-web-section-2`, `req-boot-web-section-3`, `req-boot-web-section-4` |
