Issue 1348, claim-table prototype. Scratch only; nothing here is in a repository.

- code-today/, code-claim/: `git archive HEAD` copies of the hard-things worktree (tracked files only,
  so no secrets). code-claim carries the prototype patch, claim-patch.diff: tap_grid/identity_claim.py
  (the claim), _take_identity_locks and the three verbs calling it, and a RunSQL migration. Mounted
  read-only into docker run --rm on the hard-things web image with the venv volume read-only.
- bench_import.py: the real grift_import, one batch of N ref panels (keyed on slug) and E ref edges
  (PG_LINKS__grid_fixtures, plain), first write then resend, with a pg_locks sampler.
- claim_toy.py: claim-table properties in raw SQL (modes, size, re-entrancy, two writers, lazy caller,
  pruning races).
- run-*.txt: captured output.

Databases: idclaim_1348 on tap_hard-things-db-1 (max_locks_per_transaction 512), and a throwaway
tap-db:latest container at Postgres defaults (64 x 100, tmpfs, --rm) holding idclaim, claimtoy and the
pytest test database. All dropped / stopped afterwards.
