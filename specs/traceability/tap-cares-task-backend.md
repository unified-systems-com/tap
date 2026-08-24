<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_cares/specs/spec-tap-cares-task-backend.md`

| Bucket | Count |
| --- | ---: |
| excluded | 3 |
| unbuilt | 1 |
| unaccounted | 7 |
| 0-ACID (payable) | 7 |

## Exclusions

Reasons verbatim from each `Trace:` line; ⚠ marks zero-ACID exempt.

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-tap-cares-task-backend-deployment` | non-python | ⚠ | docker/entrypoint.sh |
| `req-tap-cares-task-backend-huey-removal` | process | ⚠ | a completed removal plan; the commit history is the record |
| `req-tap-cares-task-backend-migration-plan` | process | ⚠ | the executed two-commit landing plan; history is the record |
