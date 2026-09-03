<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `specs/spec-cicd-sbom.md`

| Bucket | Count |
| --- | ---: |
| mapped | 6 |
| excluded | 5 |
| unbuilt | 4 |
| 0-ACID (payable) | 0 |

## Exclusions

Reasons verbatim from each `Trace:` line; ⚠ marks zero-ACID exempt.

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-cicd-sbom-1` | non-python | ⚠ | scripts/sbom/generate.py |
| `req-cicd-sbom-2` | non-python | ⚠ | scripts/sbom/generate.py |
| `req-cicd-sbom-4` | non-python | ⚠ | .github/workflows/publish-images.yml |
| `req-cicd-sbom-5` | non-python | ⚠ | .github/workflows/publish-images.yml |
| `req-cicd-sbom-6` | non-python | ⚠ | scripts/sbom/generate.py |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-cicd-sbom-10` | Implemented | Tested | — | `req-cicd-sbom-10-1`, `req-cicd-sbom-10-2`, `req-cicd-sbom-10-3` |
| `req-cicd-sbom-11` | Implemented | Tested | — | `req-cicd-sbom-11-1`, `req-cicd-sbom-11-2`, `req-cicd-sbom-11-3` |
| `req-cicd-sbom-12` | Implemented | Tested | — | `req-cicd-sbom-12-1`, `req-cicd-sbom-12-2`, `req-cicd-sbom-12-3`, `req-cicd-sbom-12-4`, `req-cicd-sbom-12-5`, `req-cicd-sbom-12-6` |
| `req-cicd-sbom-13` | Implemented | Tested | — | `req-cicd-sbom-13-1`, `req-cicd-sbom-13-2` |
| `req-cicd-sbom-3` | Implemented | Tested | — | `req-cicd-sbom-3-1`, `req-cicd-sbom-3-2`, `req-cicd-sbom-3-3` |
| `req-cicd-sbom-7` | Implemented | Tested | — | `req-cicd-sbom-7-1`, `req-cicd-sbom-7-2`, `req-cicd-sbom-7-3`, `req-cicd-sbom-7-4` |
