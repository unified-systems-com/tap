<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_plugins/specs/spec-tap-plugin-architecture.md`

| Bucket | Count |
| --- | ---: |
| mapped | 9 |
| excluded | 3 |
| disputed | 1 |
| unbuilt | 14 |
| 0-ACID (payable) | 0 |

## Exclusions

Reasons verbatim from each `Trace:` line; ⚠ marks zero-ACID exempt.

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-tap-plugin-arch-scope` | narrative |  | the umbrella definition of what a plugin is; the checkable substance lives in the sibling arch requirements (django, manifest, surfaces, layout, runtime, tests) |
| `req-tap-plugin-arch-skills` | non-python |  | scripts/wire-skills.sh |
| `req-tap-plugin-arch-slug-register` | non-python |  | docs/doc-plugin-slug-load-bearing.md |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-tap-plugin-arch-django` | Implemented | Implemented | `TapPluginConfig` | — |
| `req-tap-plugin-arch-iterative-dev` | Implemented | Implemented | `_run_preflight` | — |
| `req-tap-plugin-arch-layout` | Implemented | Implemented | `_check_core_files` | — |
| `req-tap-plugin-arch-manifest` | Implemented | Implemented | `TapPluginConfig._load_and_validate_manifest` | — |
| `req-tap-plugin-arch-python-deps` | Implemented | Implemented | `_install_plugins` | — |
| `req-tap-plugin-arch-runtime` | Implemented | Implemented | `TapPluginConfig.ready` | — |
| `req-tap-plugin-arch-source-secret` | Implemented | Implemented | `<module>` | — |
| `req-tap-plugin-arch-surfaces` | Implemented | Implemented | `PluginManifest` | — |
| `req-tap-plugin-arch-tests` | Implemented | Implemented | `_check_tests_dir` | — |
