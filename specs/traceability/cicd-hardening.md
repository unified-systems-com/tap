<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `specs/spec-cicd-hardening.md`

| Bucket | Count |
| --- | ---: |
| mapped | 4 |
| excluded | 7 |
| unbuilt | 4 |
| 0-ACID (payable) | 0 |

## Exclusions

Reasons verbatim from each `Trace:` line; ⚠ marks zero-ACID exempt.

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-cicd-base-image-sourcing` | non-python |  | docker/postgres/Dockerfile |
| `req-cicd-branch-protection` | external |  | GitHub repository rulesets (protect-default-branches, main-required-checks) |
| `req-cicd-build-once-artifact` | non-python | ⚠ | .github/workflows/publish-images.yml |
| `req-cicd-dep-automation` | non-python | ⚠ | renovate.json5 |
| `req-cicd-product-releases` | non-python |  | .github/workflows/release-please.yml |
| `req-cicd-release-artifacts` | process |  | org release convention; the mechanical tag parsing is |
| `req-cicd-supply-chain-provenance` | non-python |  | .github/workflows/publish-images.yml |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-cicd-dco-signoff` | — | Tested | — | `req-cicd-dco-signoff-2`, `req-cicd-dco-signoff-3`, `req-cicd-dco-signoff-4` |
| `req-cicd-issue-link` | Implemented | Tested | — | `req-cicd-issue-link-1`, `req-cicd-issue-link-2`, `req-cicd-issue-link-3`, `req-cicd-issue-link-4` |
| `req-cicd-runner-least-privilege` | Implemented | Implemented | `<module>` | — |
| `req-cicd-security-scanning` | — | Tested | — | `req-cicd-security-scanning-5` |
