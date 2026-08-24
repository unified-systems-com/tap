<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `specs/spec-dev-multisession.md`

| Bucket | Count |
| --- | ---: |
| excluded | 10 |
| unbuilt | 4 |
| unaccounted | 1 |
| 0-ACID (payable) | 0 |

## Exclusions

Reasons verbatim from each `Trace:` line; ⚠ marks zero-ACID exempt.

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-dev-multisession-admin-bootstrap` | non-python |  | scripts/spawn-session.sh |
| `req-dev-multisession-ci-gate` | non-python |  | .github/workflows/product-lines.yml |
| `req-dev-multisession-compose-parameterized` | non-python |  | docker-compose.yml |
| `req-dev-multisession-env-cascade` | non-python |  | scripts/dc |
| `req-dev-multisession-host-readiness` | non-python |  | scripts/spawn-session.sh |
| `req-dev-multisession-port-registry` | non-python | ⚠ | scripts/spawn-session.sh |
| `req-dev-multisession-promote-all-script` | non-python |  | scripts/promote-all-sessions.sh |
| `req-dev-multisession-promote-script` | non-python |  | scripts/promote-to-main.sh |
| `req-dev-multisession-push-workflow` | process |  | the branch-and-promote discipline developers follow; scripts automate steps, the rule is the requirement |
| `req-dev-multisession-spawn-script` | non-python |  | scripts/spawn-session.sh |
