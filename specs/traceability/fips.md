<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `specs/spec-fips.md`

| Bucket | Count |
| --- | ---: |
| mapped | 7 |
| excluded | 1 |
| unbuilt | 1 |
| 0-ACID (payable) | 0 |

## Exclusions

Reasons verbatim from each `Trace:` line; ⚠ marks zero-ACID exempt.

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-fips-pin-currency` | non-python |  | scripts/verify-openssl-release |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-fips-crypto-bom` | Implemented | Tested | — | `req-fips-crypto-bom-1`, `req-fips-crypto-bom-2` |
| `req-fips-crypto-bom-ci` | Implemented | Tested | — | `req-fips-crypto-bom-ci-1` |
| `req-fips-crypto-bom-conformance` | Implemented | Tested | — | `req-fips-crypto-bom-conformance-3` |
| `req-fips-crypto-bom-jvm` | Implemented | Tested | — | `req-fips-crypto-bom-jvm-1`, `req-fips-crypto-bom-jvm-2` |
| `req-fips-crypto-bom-source` | Implemented | Tested | — | `req-fips-crypto-bom-source-1`, `req-fips-crypto-bom-source-2`, `req-fips-crypto-bom-source-3` |
| `req-fips-crypto-bom-system-gate` | Implemented | Tested | — | `req-fips-crypto-bom-system-gate-2`, `req-fips-crypto-bom-system-gate-3` |
| `req-fips-crypto-bom-waivers` | Implemented | Tested | — | `req-fips-crypto-bom-waivers-1`, `req-fips-crypto-bom-waivers-2` |
