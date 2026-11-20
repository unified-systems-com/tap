<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `specs/spec-tap-file-store.md`

| Bucket | Count |
| --- | ---: |
| mapped | 19 |
| unbuilt | 11 |
| 0-ACID (payable) | 0 |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-tap-files-capabilities` | Implemented | Tested | — | `req-tap-files-capabilities-1`, `req-tap-files-capabilities-2`, `req-tap-files-capabilities-3`, `req-tap-files-capabilities-4`, `req-tap-files-capabilities-5` |
| `req-tap-files-check` | Implemented | Implemented | `LocalBackend.survey` | — |
| `req-tap-files-directory` | Implemented | Implemented | `_directory_ops` | — |
| `req-tap-files-download` | Implemented | Implemented | `download` | — |
| `req-tap-files-gateway` | Implemented | Verified | `_writer` | `req-tap-files-gateway-1`, `req-tap-files-gateway-2`, `req-tap-files-gateway-3`, `req-tap-files-gateway-4`, `req-tap-files-gateway-5` |
| `req-tap-files-health` | Implemented | Implemented | `probe_files` | — |
| `req-tap-files-history` | Implemented | Tested | — | `req-tap-files-history-1`, `req-tap-files-history-2` |
| `req-tap-files-hold` | Implemented | Implemented | `hold_file` | — |
| `req-tap-files-immutable` | Implemented | Tested | — | `req-tap-files-immutable-1`, `req-tap-files-immutable-2`, `req-tap-files-immutable-3`, `req-tap-files-immutable-4`, `req-tap-files-immutable-5`, `req-tap-files-immutable-6` |
| `req-tap-files-interface` | Implemented | Tested | — | `req-tap-files-interface-1`, `req-tap-files-interface-2`, `req-tap-files-interface-3` |
| `req-tap-files-logging` | Implemented | Verified | `recorded` | `req-tap-files-logging-1`, `req-tap-files-logging-2`, `req-tap-files-logging-3`, `req-tap-files-logging-4` |
| `req-tap-files-mount-gate` | Implemented | Verified | `run_gate`, `LocalBackend.initialise` | `req-tap-files-mount-gate-1`, `req-tap-files-mount-gate-10`, `req-tap-files-mount-gate-2`, `req-tap-files-mount-gate-3`, `req-tap-files-mount-gate-4`, `req-tap-files-mount-gate-5`, `req-tap-files-mount-gate-6`, `req-tap-files-mount-gate-7`, `req-tap-files-mount-gate-8`, `req-tap-files-mount-gate-9` |
| `req-tap-files-naming` | Implemented | Verified | `object_path` | `req-tap-files-naming-1`, `req-tap-files-naming-2`, `req-tap-files-naming-3`, `req-tap-files-naming-4`, `req-tap-files-naming-5`, `req-tap-files-naming-6`, `req-tap-files-naming-7`, `req-tap-files-naming-8` |
| `req-tap-files-node` | Implemented | Implemented | `TapFile` | — |
| `req-tap-files-ocfl` | Implemented | Tested | — | `req-tap-files-ocfl-3`, `req-tap-files-ocfl-4`, `req-tap-files-ocfl-5` |
| `req-tap-files-read` | Implemented | Verified | `LocalBackend.open` | `req-tap-files-read-1`, `req-tap-files-read-2`, `req-tap-files-read-3`, `req-tap-files-read-4`, `req-tap-files-read-5`, `req-tap-files-read-6`, `req-tap-files-read-7`, `req-tap-files-read-8` |
| `req-tap-files-root` | Implemented | Verified | `get_store` | `req-tap-files-root-1`, `req-tap-files-root-2`, `req-tap-files-root-3`, `req-tap-files-root-4`, `req-tap-files-root-5` |
| `req-tap-files-scope` | Implemented | Implemented | `FilesRootResolutionGuard.check` | — |
| `req-tap-files-write` | Implemented | Verified | `LocalBackend.create`, `LocalBackend.recover` | `req-tap-files-write-1`, `req-tap-files-write-10`, `req-tap-files-write-11`, `req-tap-files-write-12`, `req-tap-files-write-13`, `req-tap-files-write-14`, `req-tap-files-write-15`, `req-tap-files-write-16`, `req-tap-files-write-17`, `req-tap-files-write-2`, `req-tap-files-write-3`, `req-tap-files-write-4`, `req-tap-files-write-5`, `req-tap-files-write-6`, `req-tap-files-write-7`, `req-tap-files-write-8`, `req-tap-files-write-9` |
