<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `specs/spec-cicd-sbom.md`

| Bucket | Count |
| --- | ---: |
| excluded | 5 |
| unbuilt | 4 |
| unaccounted | 6 |
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
