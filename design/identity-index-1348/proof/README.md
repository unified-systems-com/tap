Issue 1348 prototype. Scratch only; nothing here is in a repo.

- today_locks.py — today's real code (tap_grid.grift.importer._take_identity_locks with the real
  identity_lock_key / edge_lock_key), run in the hard-things web image against a throwaway database.
- schema.sql, proto.py — the toy grid and the three write paths (today's shape, partial unique index +
  ON CONFLICT, mutex rows), the functional checks, and the two-writer race.
- scale.py — the index path at 200,000 keys.
- run-*.txt — captured output.

Servers: (1) a throwaway postgres container from ghcr.io/unified-systems-com/tap-db:latest with Postgres
defaults (max_locks_per_transaction=64, max_connections=100, tmpfs, --rm), stopped afterwards; (2) a
private database idxproof_1348 on tap_hard-things-db-1 (max_locks_per_transaction=512), dropped afterwards.
Runner: docker run --rm on the hard-things web image, worktree and venv mounted read-only, throwaway
SECRET_KEY, no secrets.
