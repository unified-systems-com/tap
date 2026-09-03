<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_cares/specs/spec-tap-cares-secrets.md`

| Bucket | Count |
| --- | ---: |
| excluded | 6 |
| unbuilt | 3 |
| unaccounted | 13 |
| 0-ACID (payable) | 4 |

## Exclusions

Reasons verbatim from each `Trace:` line; ⚠ marks zero-ACID exempt.

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-tap-cares-secrets-consumer-kinds` | narrative | ⚠ | the mechanics-vs-kinds ownership split; each side's substance is specified elsewhere |
| `req-tap-cares-secrets-cross-scope-concern` | narrative | ⚠ | documents a deliberately deferred control; nothing derives it until the least-privilege work lands |
| `req-tap-cares-secrets-history-audit` | process | ⚠ | a completed, human-triaged pre-publication audit; the record is the artifact |
| `req-tap-cares-secrets-precommit` | non-python | ⚠ | .githooks/precommit_secret_scan.py |
| `req-tap-cares-secrets-scope` | narrative | ⚠ | the umbrella statement; the checkable substance lives in the sibling requirements |
| `req-tap-cares-secrets-validation` | narrative | ⚠ | a deliberate non-centralization ruling; consumers own kind-specific validation |
