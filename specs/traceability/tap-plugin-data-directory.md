<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_plugins/specs/spec-tap-plugin-data-directory.md`

| Bucket | Count |
| --- | ---: |
| mapped | 12 |
| unbuilt | 3 |
| 0-ACID (payable) | 0 |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-tap-plugin-datadir-accessor` | Implemented | Verified | `data_dir` | `req-tap-plugin-datadir-accessor-1`, `req-tap-plugin-datadir-accessor-2`, `req-tap-plugin-datadir-accessor-3`, `req-tap-plugin-datadir-accessor-4`, `req-tap-plugin-datadir-accessor-5` |
| `req-tap-plugin-datadir-backup-facts` | Implemented | Tested | — | `req-tap-plugin-datadir-backup-facts-1` |
| `req-tap-plugin-datadir-health` | Implemented | Tested | — | `req-tap-plugin-datadir-health-1`, `req-tap-plugin-datadir-health-2`, `req-tap-plugin-datadir-health-3`, `req-tap-plugin-datadir-health-4`, `req-tap-plugin-datadir-health-5` |
| `req-tap-plugin-datadir-lifecycle` | Implemented | Verified | `hold_shared`, `purge` | `req-tap-plugin-datadir-lifecycle-1`, `req-tap-plugin-datadir-lifecycle-10`, `req-tap-plugin-datadir-lifecycle-11`, `req-tap-plugin-datadir-lifecycle-12`, `req-tap-plugin-datadir-lifecycle-13`, `req-tap-plugin-datadir-lifecycle-2`, `req-tap-plugin-datadir-lifecycle-3`, `req-tap-plugin-datadir-lifecycle-4`, `req-tap-plugin-datadir-lifecycle-5`, `req-tap-plugin-datadir-lifecycle-6`, `req-tap-plugin-datadir-lifecycle-7`, `req-tap-plugin-datadir-lifecycle-8`, `req-tap-plugin-datadir-lifecycle-9` |
| `req-tap-plugin-datadir-manifest` | Implemented | Verified | `_parse_data_directory`, `_check_data_directory` | `req-tap-plugin-datadir-manifest-1`, `req-tap-plugin-datadir-manifest-2`, `req-tap-plugin-datadir-manifest-3`, `req-tap-plugin-datadir-manifest-4`, `req-tap-plugin-datadir-manifest-5`, `req-tap-plugin-datadir-manifest-6`, `req-tap-plugin-datadir-manifest-7` |
| `req-tap-plugin-datadir-mount-gate` | Implemented | Verified | `run_gate`, `check_volume` | `req-tap-plugin-datadir-mount-gate-1`, `req-tap-plugin-datadir-mount-gate-2`, `req-tap-plugin-datadir-mount-gate-3`, `req-tap-plugin-datadir-mount-gate-4`, `req-tap-plugin-datadir-mount-gate-5`, `req-tap-plugin-datadir-mount-gate-6`, `req-tap-plugin-datadir-mount-gate-7`, `req-tap-plugin-datadir-mount-gate-8` |
| `req-tap-plugin-datadir-nongoals` | Implemented | Tested | — | `req-tap-plugin-datadir-nongoals-1` |
| `req-tap-plugin-datadir-provision` | Implemented | Verified | `provision` | `req-tap-plugin-datadir-provision-1`, `req-tap-plugin-datadir-provision-2`, `req-tap-plugin-datadir-provision-3`, `req-tap-plugin-datadir-provision-4`, `req-tap-plugin-datadir-provision-5`, `req-tap-plugin-datadir-provision-6`, `req-tap-plugin-datadir-provision-7`, `req-tap-plugin-datadir-provision-8` |
| `req-tap-plugin-datadir-report` | Implemented | Verified | `measure` | `req-tap-plugin-datadir-report-1`, `req-tap-plugin-datadir-report-2`, `req-tap-plugin-datadir-report-3`, `req-tap-plugin-datadir-report-4`, `req-tap-plugin-datadir-report-5`, `req-tap-plugin-datadir-report-6`, `req-tap-plugin-datadir-report-7`, `req-tap-plugin-datadir-report-8`, `req-tap-plugin-datadir-report-9` |
| `req-tap-plugin-datadir-root` | Implemented | Verified | `place` | `req-tap-plugin-datadir-root-1`, `req-tap-plugin-datadir-root-2`, `req-tap-plugin-datadir-root-3`, `req-tap-plugin-datadir-root-4`, `req-tap-plugin-datadir-root-5` |
| `req-tap-plugin-datadir-scope` | Implemented | Tested | — | `req-tap-plugin-datadir-scope-1`, `req-tap-plugin-datadir-scope-2` |
| `req-tap-plugin-datadir-sharing` | Implemented | Tested | — | `req-tap-plugin-datadir-sharing-1` |
