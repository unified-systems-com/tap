<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `specs/spec-dev-validation.md`

| Bucket | Count |
| --- | ---: |
| mapped | 10 |
| excluded | 3 |
| unbuilt | 4 |
| 0-ACID (payable) | 0 |

## Exclusions

Reasons verbatim from each `Trace:` line; ⚠ marks zero-ACID exempt.

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-dev-validation-all-plugins-lane` | narrative |  | superseded 2026-09-09 by `req-dev-validation-product-line-lanes-6` (tap#364); the lane and its promote fallback are deleted, nothing maps to code; kept as the decision record |
| `req-dev-validation-lean-boot` | non-python |  | scripts/gate-lean |
| `req-dev-validation-promote-hook` | non-python |  | scripts/promote-to-main.sh |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-dev-validation-baseline-vocabulary` | Implemented | Implemented | `missing_baseline_plugins`, `pytest_collection_modifyitems` | — |
| `req-dev-validation-bom-lane` | Implemented | Tested | — | `req-dev-validation-bom-lane-2`, `req-dev-validation-bom-lane-4` |
| `req-dev-validation-collection-complete` | Implemented | Implemented | `<module>` | — |
| `req-dev-validation-known-broken` | Implemented | Implemented | `<module>` | — |
| `req-dev-validation-map` | Implemented | Implemented | `<module>` | — |
| `req-dev-validation-mypy-ratchet` | Implemented | Implemented | `<module>` | — |
| `req-dev-validation-product-line-lanes` | Proposed | Tested | — | `req-dev-validation-product-line-lanes-7`, `req-dev-validation-product-line-lanes-8`, `req-dev-validation-product-line-lanes-9` |
| `req-dev-validation-ratchet-harness` | Implemented | Verified | `<module>` | `req-dev-validation-ratchet-harness-5` |
| `req-dev-validation-real-backend` | Implemented | Implemented | `<module>` | — |
| `req-dev-validation-smoke-gate` | Implemented | Implemented | `<module>` | — |
