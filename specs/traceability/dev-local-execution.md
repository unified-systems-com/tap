<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `specs/spec-dev-local-execution.md`

| Bucket | Count |
| --- | ---: |
| mapped | 1 |
| excluded | 3 |
| doctrine | 3 |
| 0-ACID (payable) | 0 |

## Exclusions

Reasons verbatim from each `Trace:` line; ⚠ marks zero-ACID exempt.

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-dev-localexec-consent` | non-python |  | scripts/hooks-install |
| `req-dev-localexec-elevated-review` | non-python |  | .github/workflows/product-lines.yml |
| `req-dev-localexec-reconsent` | non-python |  | .githooks/_consent_check.sh |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-dev-localexec-merge-gate` | Implemented | Tested | — | `req-dev-localexec-merge-gate-1`, `req-dev-localexec-merge-gate-2` |
