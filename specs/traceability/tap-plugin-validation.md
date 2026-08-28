<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_plugins/specs/spec-tap-plugin-validation.md`

| Bucket | Count |
| --- | ---: |
| mapped | 16 |
| unbuilt | 1 |
| unaccounted | 1 |
| 0-ACID (payable) | 0 |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-tap-plugin-validate-cli` | Implemented | Implemented | `main` | — |
| `req-tap-plugin-validate-codepaths` | Implemented | Implemented | `_check_manifest_parse` | — |
| `req-tap-plugin-validate-compat` | Implemented | Implemented | `_check_requires_tap` | — |
| `req-tap-plugin-validate-deps` | Implemented | Implemented | `_check_declared_dependencies` | — |
| `req-tap-plugin-validate-exit` | Implemented | Implemented | `main` | — |
| `req-tap-plugin-validate-help` | Implemented | Implemented | `_build_parser` | — |
| `req-tap-plugin-validate-home` | Implemented | Implemented | `<module>` | — |
| `req-tap-plugin-validate-identity` | Implemented | Implemented | `_check_identity_coherence` | — |
| `req-tap-plugin-validate-levels` | Implemented | Implemented | `validate_plugin` | — |
| `req-tap-plugin-validate-loads` | Implemented | Implemented | `_run_loads_checks` | — |
| `req-tap-plugin-validate-mgmt` | Implemented | Implemented | `<module>` | — |
| `req-tap-plugin-validate-output` | Implemented | Implemented | `ValidationResult` | — |
| `req-tap-plugin-validate-runs` | Implemented | Implemented | `_run_runs_checks` | — |
| `req-tap-plugin-validate-schema` | Implemented | Implemented | `ValidationResult.to_json` | — |
| `req-tap-plugin-validate-scope` | Implemented | Implemented | `validate_plugin` | — |
| `req-tap-plugin-validate-strict` | Implemented | Implemented | `validate_plugin` | — |
