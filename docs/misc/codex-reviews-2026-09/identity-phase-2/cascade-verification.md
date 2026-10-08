# Cascade review verification

Core main: `7100d9e20eabe57b7b487067dc980a7774cb4dc6`.
Cascade implementation: PR #568 head `064678a59950ef43e32bc3dbc11d0b95571ed20b`.

The probe extracts the exact deletion branch and two helpers from the pinned implementation. ORM operations use in-memory doubles; no database is opened. The harness provides a legal child-query order with the self-edge before the two other children. No ORDER BY in the actual query rules that order out. This is a control-flow reproduction, not an integration-test result.

Executed in the existing TAP container using `/app/.venv/bin/python` (project Python 3.14). Output:

```
success: True
node liveness: {'00000000-0000-0000-0000-000000000001': False, '00000000-0000-0000-0000-000000000002': False, '00000000-0000-0000-0000-000000000003': True}
provenance entity IDs: ['00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002']
expected: refuse closure of 3 nodes with cap=2, retain all nodes
```

`cascade-cap-probe.py` accepts the pinned `_impl.py` source path and verifies its SHA256 before execution. Run it in the project runtime; the host Python is too old. The run used an equivalent stdin bundle embedding that source so no container files had to change.

No project test suite or fresh GRIFT tombstone integration fixture was executed in this review. Importer refusal is a source trace; the report explicitly requires the one-fixture integration test. Existing tests and PR descriptions were inspected, not represented as this review's test results.

Issues filed and parented to #140: #572 (cap/self-loop), #573 (edge provenance).
