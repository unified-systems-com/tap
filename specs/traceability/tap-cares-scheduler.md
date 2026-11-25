<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_cares/specs/spec-tap-cares-scheduler.md`

| Bucket | Count |
| --- | ---: |
| mapped | 4 |
| unbuilt | 2 |
| unaccounted | 6 |
| 0-ACID (payable) | 10 |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-tap-cares-scheduler-cron` | Implemented | Implemented | `Schedule.validate` | — |
| `req-tap-cares-scheduler-fire-model` | Implemented | Implemented | `ScheduleFire` | — |
| `req-tap-cares-scheduler-model` | Implemented | Implemented | `Schedule` | — |
| `req-tap-cares-scheduler-tick` | Implemented | Implemented | `scheduler_tick` | — |
