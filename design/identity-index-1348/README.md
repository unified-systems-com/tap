# Identity By Index (draft amendment)

Draft for unified-systems-com/tap Issue 1348, for the 0.5.0 core migration wave. Amends
`spec-grid-entity.md` (`req-grid-entity-natural-key` -3, -13, -22) and `spec-grid-edge.md`
(`req-grid-edge-identity` -4, -5, -12 and its Development note). Not yet in any repository.

Status: `Proposed`

Evidence marks used below: **measured** (this draft's prototype, numbers from
`identity-index-proof/run-*.txt`), **read** (a source or the code says so, cited), **inferred**
(reasoning from what was read or measured, not tested).

## Philosophy

A batch must cost the lock table a constant, not one slot per key. Identity is found by the
database enforcing one live row per identity, not by the importer holding a mutex for every key until
commit. A uniqueness rule that an index cannot express keeps an advisory lock; today none is left
once the rules below hold.

## The Problem, Measured

- Today's code takes one advisory lock per key and holds it to commit. Running the importer's real
  `_take_identity_locks` with the real `identity_lock_key` / `edge_lock_key` over N node keys and N edge
  keys in one transaction holds exactly N+N advisory locks (40,000 keys → 40,000 advisory locks, 2.67 s
  for the lock calls alone). **Measured** (`run-today-real-code.txt`).
- At Postgres defaults (`max_locks_per_transaction` 64, `max_connections` 100, idle server) one
  transaction succeeds at 12,000 keys and fails at 15,000 with `out of shared memory` / `HINT: You might
  need to increase "max_locks_per_transaction"`. **Measured.** The nominal pool is 64 × 100 = 6,400; the
  rest is shared-memory slack, which other sessions' locks consume. **Read**
  (https://www.postgresql.org/docs/current/runtime-config-locks.html).
- Row locks do not use that table: "this is *not* the number of rows that can be locked; that value is
  unlimited". **Read** (https://www.postgresql.org/docs/current/runtime-config-locks.html).

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-identity-claim | [Identity Is Claimed By Index](#identity-is-claimed-by-index) | Proposed | One live row per declared identity, enforced by a partial unique index over a spine identity digest; a batch claims its identities with sorted `INSERT ... ON CONFLICT`; the per-key advisory lock is removed; lock-table use per batch is constant |

### Identity Is Claimed By Index

RID: `req-grid-identity-claim`

Status: `Proposed`

#### Rules

1. **The identity digest.** `Entity` (`tap_entity`) gains `identity_digest bytea NULL`, derived by the
   grid on every write, never taken from a caller, at exactly the write sites that derive
   `Entity.natural_key` (`req-grid-entity-natural-key-19`: `BaseModel.save`, the pre-specified-id create,
   the importer through the service layer, the guarded querysets).
   - A node of a type keyed by a tuple: `sha256(utf8(entity_type || U+001F || natural_key))`, where
     `natural_key` is the stored `compose_natural_key` value (field-coerced, normalised by
     `normalize_natural_key`). Null when `natural_key` is null (a hole, or a `KEYLESS` type).
   - An edge of a type with a declared identity (plain, discriminated or keyless): sha256 of the
     canonical identity string the edge lock key is built from today (`edge:<type>`, both endpoint ids
     canonicalised, each discriminator value canonically serialised). Null for an undeclared type.
   - One derivation function per kind, in `tap_grid/natural_key.py` and `tap_grid/edge_identity.py`, so
     the digest, the search and the stored key read one declaration through one parser.
2. **The index.** One partial unique index on `tap_entity (identity_digest) WHERE deleted_at IS NULL AND
   identity_digest IS NOT NULL`, declared on `Entity.Meta` as `UniqueConstraint(fields=["identity_digest"],
   condition=Q(deleted_at__isnull=True, identity_digest__isnull=False), name="uq_entity_identity_live")`.
   It ships in the core 0.5.0 migration. No plugin migration is needed: every typed row, node or edge,
   has its spine row.
3. **Live rows only.** A tombstone leaves the index the moment `deleted_at` is set, so the returning
   source object inserts a new row with a new id. Tombstones are terminal (`spec-grid-reconcile.md`,
   no restore verb), so no revival path exists; any tool that cleared `deleted_at` while another live
   row held the identity would fail on the index, which is the intended refusal.
4. **The claim, for a batch.** Inside the batch's transaction the importer stages every identity the
   batch names (provisional id, type, natural key, digest; the prototype used `COPY` into an
   `ON COMMIT DROP` temporary table, and the build should use `unnest()` arrays or one session-lived
   temporary table, to avoid catalog bloat; see Prior Art) and claims them in one statement per phase:

   ```sql
   INSERT INTO tap_entity (id, entity_type, natural_key, identity_digest, ...)
   SELECT ... FROM stage ORDER BY identity_digest
   ON CONFLICT (identity_digest) WHERE deleted_at IS NULL AND identity_digest IS NOT NULL
   DO UPDATE SET identity_digest = EXCLUDED.identity_digest
   RETURNING id, identity_digest, (xmax = 0) AS created;
   ```

   A returned `created` row is a new identity under its provisional id; any other returned row is the
   existing live row, now row-locked by this transaction, and its id replaces the provisional one
   exactly where `_resolve_ref_identities` substitutes today. The claim is the lookup: the generated
   search is no longer called on this path.
5. **One order.** Node identities are claimed first, sorted by digest; then edge identities (ref edges
   and keyless duplicate checks together), sorted by digest, once every endpoint is final. A batch that
   also deletes edges by identity first locks the existing live rows of every edge identity it names
   (`SELECT ... WHERE identity_digest = ANY(...) AND deleted_at IS NULL ORDER BY identity_digest FOR
   UPDATE`), then claims. This is the Issue# 943 argument moved from advisory locks to index entries
   and row locks; the order is still load-bearing (rule 9's evidence).
6. **Single writes.** `resolve_identity` and `resolve_edge_identity` claim their one identity with the
   same statement and no `pg_advisory_xact_lock`. `find_edge_by_identity` row-locks the live match
   (`FOR UPDATE`) instead of taking the advisory lock. `find_by_natural_key` is unchanged (a read).
7. **Outcomes keep their codes.** A conflicting claim for a plain or discriminated identity is "found"
   (`req-grid-edge-identity-2`). A conflicting claim for a keyless edge type fails the batch as
   `KeylessEdgeExists` (`req-grid-edge-identity-5`). In-batch duplicates are refused before the claim, as
   today (`duplicate_entity_id`, `duplicate_edge`); the claim statement also refuses them on its own
   (`ON CONFLICT DO UPDATE command cannot affect row a second time`, **measured**), which is a backstop,
   not the reporting path. `AmbiguousIdentity` cannot arise for a constrained identity and stays only
   for rows written before the index existed.
8. **A digest match is checked, never trusted.** On a conflict the claim compares the stored row's
   `entity_type` and `natural_key` (nodes) or endpoints and discriminators (edges) with the staged ones;
   a mismatch fails the batch naming both rows and is never treated as found. (sha256 collisions are not
   a practical concern; the check is what makes a derivation bug loud instead of a silent merge.)
9. **Bounded locks.** A batch's lock-table use does not grow with its size. **Measured:** the claim path
   holds 20 lock-table entries per transaction at 20,000 and at 200,000 keys (relation locks on the
   tables, indexes and temporary tables it touches), and no advisory lock.
10. **Concurrency.** Two writers of one new identity: the second's insert waits on the first's
    uncommitted index entry, then, under READ COMMITTED, finds the committed row and takes the found
    path; if the first rolls back, the second inserts. **Read**
    (https://www.postgresql.org/docs/current/sql-insert.html, "ON CONFLICT DO UPDATE guarantees an atomic
    INSERT or UPDATE outcome"). Two writers in opposite orders: sorted, no deadlock; unsorted, deadlock.
    **Measured** (rule 5 evidence below).
11. **Advisory locks stay only for what the index cannot express.** Today that set is empty. A future
    rule that no index can state (a uniqueness across types, or one that depends on another row's
    state) keeps `pg_advisory_xact_lock`, bounded by taking it per rule, not per key, and must say why.
12. **The derivation is checked.** `sync_spine_natural_keys --check` also compares each sampled row's
    stored digest with a fresh derivation, and `--changed` re-derives digests with keys when a recipe
    changes (`req-grid-entity-natural-key-25`). A re-derivation that makes two live rows collide fails
    on the index and is reported as the duplicate it is.

#### What Changes Elsewhere

- `req-grid-entity-natural-key-3` ("Not unique … no constraint prevents it") and `-22` ("Never unique")
  are **superseded** for identity: two live rows of one keyed type may no longer share declared values.
  `-22`'s index rules for `natural_key` itself (hash for equality, prefix btree, no plain btree) stand;
  the constraint lives on the digest, which has no row-size problem (32 bytes).
- `req-grid-entity-natural-key-13`: "under `pg_advisory_xact_lock` keyed by the declaration" becomes "by
  claiming the identity digest". The identity lock key format stops mattering (nothing shares it during
  a rolling deploy once both sides use the index; pre-0.5.0 reload makes the point moot).
- `req-grid-edge-identity` summary "under an advisory lock … no unique index" becomes "claimed through
  the identity index". `-4` is rewritten to the claim; `-12`'s per-edge cost becomes a per-batch cost.
- The edge spec's Development note (L611): "a database constraint on a key that perspectives will
  later need to share would have to be removed again." Answered: when perspectives arrive the digest
  takes the identity scope as an input (or the index gains an `identity_scope` column); a migration
  replaces the index. That is cheaper than a lock count that grows with every row, and the
  `-3` note already says "the constraint arrives with perspectives".
- `tap_grid/tests/test_grift_lock_order.py::TestOppositeOrders` keeps its done-test (two batches, the
  same refs or edges in opposite orders, both succeed) and loses its assertion on advisory locks; a
  new case runs it with input order deliberately reversed and asserts no `deadlock detected`.

#### Development

**Why a spine digest and not one constraint per typed table.** Both were prototyped. A typed-table
`UniqueConstraint(*index_expressions(NATURAL_KEY), condition=Q(spine_deleted_at=None))`, generated in
`_install_natural_key_index` in place of today's `nk_<table>` index, works as an `ON CONFLICT` arbiter
for column keys and for JSON-path keys (`(location -> 'route')`, typed: `123` and `"123"` are two
identities). **Measured.** It is not chosen because:
- a btree index row over about 2,700 bytes is an error on insert, and long keys are real (the anchore
  failure behind `-22`); a typed-column constraint would refuse them, so long-key types would need a
  hashed expression anyway. **Read** (`-22`, and `PREFIX_INDEX_CHARS` in `tap_grid/natural_key.py`);
- edge identity is declared per edge type in `.edge.json`, not on a model, and every edge type shares
  `tap_edge`; a per-type partial expression index (`... WHERE edge_type = 'scoped' AND spine_deleted_at
  IS NULL`) works as an arbiter (**measured**) but needs runtime-generated DDL per edge type, outside
  Django's migration graph;
- one arbiter on one table gives one statement and one sort across all node types, which is what keeps
  the Issue# 943 argument simple; per-table constraints need a fixed type order and one statement per
  type;
- it needs `spine_deleted_at` on every typed row (the unmerged `wave3-copies` release) and a regenerated
  migration in every plugin. The spine digest needs neither.

The cost of the digest is that the constraint is only as right as the derivation (rules 8 and 12 make a
wrong derivation loud), and that every write site of `natural_key` must also write the digest (the same
list, already guarded by `TestTheWritePaths`).

**Why not mutex rows.** A third path was prototyped: keep today's search and replace each advisory lock
with a row lock on a `(digest)` mutex table (`INSERT ... ON CONFLICT DO UPDATE` in digest order). It is
bounded (22 lock-table entries at 20,000 keys, 0.33 s; **measured**) and changes no identity rule, so it
is the fallback if the owner keeps `-3` and `-22`. It is not chosen: it adds a table that grows with
every identity ever seen, keeps a lock that duplicates what an index states, and keeps `AmbiguousIdentity`
as a reachable state.

**Django.** `UniqueConstraint(fields=..., condition=Q(...))` declares the partial index and migrates
normally. Django's ORM cannot write the claim: `bulk_create(update_conflicts=True, unique_fields=...)`
emits `ON CONFLICT (cols)` without the index predicate, and PostgreSQL refuses a partial index as
arbiter unless the predicate is restated (`there is no unique or exclusion constraint matching the ON
CONFLICT specification`, **measured**). The claim is raw SQL in one module, as the spine-copy triggers
are. See the prior-art section for the Django references.

**Write amplification.** `DO UPDATE` writes a new row version for every found row. On a packed test
table none of the 20,000 resend updates were HOT and all 20,000 became dead tuples. **Measured.** On the
spine this is mostly not new cost: a found row's spine row is rewritten in the same batch anyway (its
observation pointers, `req-grid-entity-batch-pointers`), and `tap_entity` indexes
`last_observed_batch_id`, so those updates are not HOT today either. **Inferred.** Folding the pointer
write into the claim's `DO UPDATE SET` would remove the extra version; left as a build optimisation.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-identity-claim-1 | Bounded Lock Table | Proposed | A batch of 20,000 ref nodes and 20,000 ref edges imports on a server at `max_locks_per_transaction = 64`, and the importing backend's `pg_locks` count during the batch does not exceed a constant independent of the batch size (asserted at two sizes). No advisory lock is held. | Prototype: 20 entries at 20,000 and 200,000 keys. |
| req-grid-identity-claim-2 | One Live Row Per Identity | Proposed | With the index in place, no write path (importer, service create, pre-specified-id create, guarded querysets) can leave two live rows with one identity digest; the second write is found (ref), refused (explicit id or service create of a duplicate), or fails as `KeylessEdgeExists`. | Replaces `-3`'s acceptance test, which built the pair. |
| req-grid-identity-claim-3 | Two Writers, One Row | Proposed | Two connections claim overlapping new identities concurrently: one live row per identity, the second writer reports found for the shared ones, no orphan spine or typed row. | Prototype: 5 rounds × 20,000 keys each, half shared: 0 duplicates, 0 orphans. |
| req-grid-identity-claim-4 | Opposite Orders Do Not Deadlock | Proposed | Two batches naming the same nodes, and the same edges, in opposite document orders both commit; a control with the sort removed reproduces `deadlock detected`. | Prototype: sorted 0/5 deadlocks, unsorted 5/5. `test_grift_lock_order.py` carries both. |
| req-grid-identity-claim-5 | Retirement Releases The Identity | Proposed | A key whose row is tombstoned is claimed again as a new row with a new id; the tombstone keeps its digest. A row tombstoned while a claim waits on it yields a new row for the waiter, never a write onto the tombstone. | First half measured; the waiting case is inferred from PostgreSQL's speculative-insertion retry and must be a barrier test (the Issue# 611 shape). |
| req-grid-identity-claim-6 | Typed JSON Identity | Proposed | A JSON-path key keeps its type: `123` and `"123"` are two identities. | Measured on the typed-table variant; the digest inherits it from `compose_natural_key`. |
| req-grid-identity-claim-7 | Digest Mismatch Is Loud | Proposed | A conflict whose stored type or key differs from the staged one fails the batch naming both rows. | Rule 8. Test by forcing a digest. |
| req-grid-identity-claim-8 | Derivation Drift Is Caught | Proposed | `sync_spine_natural_keys --check` fails when a stored digest differs from a fresh derivation; a recipe change re-derives digests with keys. | Rule 12. |
| req-grid-identity-claim-9 | The Migration Refuses Duplicates | Proposed | The 0.5.0 migration fails, naming the groups, on a grid that already holds two live rows with one identity; the release notes say to reload (no field deployments, 2026-11-13). | A preflight query lists the groups. |

## Prototype

Under `identity-index-proof/` (scratchpad). PostgreSQL 18.6, READ COMMITTED. Toy grid in
`schema.sql`: a spine table, a typed table keyed on two columns with `spine_deleted_at` and a partial
unique index, a JSON-path typed table, an edge table with a digest index and a per-type expression index,
and a mutex table. The "today" path in `proto.py` reproduces today's SQL shape (all advisory locks up
front sorted, then one search and one insert or update per key); the real ORM path does more per key, so
its time is a lower bound for today.

Single writer, 20,000 node keys, one transaction each (private database on `tap_hard-things-db-1`,
`max_locks_per_transaction` 512; `run-shared512-single.txt`):

| Path | First write | Resend (all found) | Lock-table entries held | Advisory |
| --- | ---: | ---: | ---: | ---: |
| Today's shape | 5.53 s | 5.84 s | 20,008 / 20,010 | 20,000 |
| Partial unique index + staging + ON CONFLICT | 0.22 s | 0.23 s | 20 | 0 |
| Mutex rows (fallback) | 0.33 s | 0.34 s | 22 | 0 |

Same on a throwaway server at Postgres defaults (`run-default64-single.txt`): today's shape fails both
times with `out of shared memory`; the index path writes 20,000 in 0.23 s and resends in 0.24 s with 20
entries; 20,000 edges with digests write in 0.44 s and resend reversed in 0.27 s, 21 entries. At
200,000 keys (`run-default64-scale.txt`) the index path writes in 2.84 s, resends in 2.80 s, still 20
entries, no duplicates.

Two concurrent writers, defaults server (`run-default64-concurrent.txt`): each batch 20,000 keys, 10,000
shared, the second batch's shared keys in reverse order, both released together after staging, five
rounds, a third connection sampling `pg_locks` server-wide.

| Claim order | Batches committed | Deadlocks | Live duplicates | Orphans | Peak server-wide locks | Mean round |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Sorted by key | 10 / 10 | 0 | 0 | 0 | 45 | 0.53 s |
| Input order (unsorted) | 5 / 10 | 5 | 0 | 0 | 36 | 1.28 s |

Functional checks (`functional` in `proto.py`): a retired key returns as a new row (2 rows, 1 live); a
JSON-path arbiter finds `{"route": 123}` again and treats `{"route": "123"}` as new; a per-type edge
expression arbiter finds scope `x` again and treats `y` as new; one statement naming one key twice
fails with `CardinalityViolation: ON CONFLICT DO UPDATE command cannot affect row a second time`; an
arbiter without the predicate fails with `there is no unique or exclusion constraint matching the ON
CONFLICT specification`.

## Chunked Submit And Refuse-Before-Start

Once locks are bounded, the lock table no longer limits a batch, so neither proposal is needed for
Issue 1348's failure.
- **Refuse before starting** (proposal 3): drop it. There is no pool left to compare a batch against.
  If memory or statement time ever needs a ceiling, that is a separate, measured row limit.
- **Chunked submit with a seal** (proposal 2): still worth having, for other reasons: transaction
  duration, WAL burst and replica lag, the importer holding a whole document in memory, the per-row
  Python write pipeline (not measured here), and a failure losing a chunk rather than a run. It is not
  on the 0.5.0 critical path for this issue. Its seal carries what only a whole run licenses
  (watermarks, withdrawals, reconcile claims, the collection window). Chunks resolve each other's nodes
  through endpoints by natural key, which exists (`req-grid-import-grift-edge-endpoints`).
- The qualys `WORKAROUND(unified-systems-com/tap#1348)` chunking can stay until the chunked submit
  lands, or be removed once the claim lands if its runs fit comfortably in one transaction.

## Prior Art

Surveyed 2026-11-23 by a research pass for this draft. Each claim carries its source and a mark
(**read**: the page says so; **inferred**: reasoning from what was read). Snippet-only sources are
marked inferred.

**PostgreSQL: `INSERT ... ON CONFLICT`.**
- A partial unique index is inferred as arbiter only when the predicate is restated (`ON CONFLICT (did)
  WHERE is_active`); expression indexes are arbiters when the target names the same expressions.
  **Read**, https://www.postgresql.org/docs/current/sql-insert.html. The prototype reproduces the
  refusal when the predicate is left out (**measured**).
- A partial or expression index cannot become a named constraint ("cannot have expression columns nor
  be a partial index"), so `ON CONFLICT ON CONSTRAINT` cannot reach it; inference is the only way.
  **Read** https://www.postgresql.org/docs/current/sql-altertable.html, consequence **inferred**.
- `DO UPDATE` "will not be allowed to affect any single existing row more than once": a batch must be
  deduplicated first. **Read** (sql-insert.html); **measured**.
- `DO UPDATE` locks every conflicting row; `DO NOTHING` locks none ("DO NOTHING doesn't lock any
  conflicting row", Geoghegan 2023). **Read**, sql-insert.html and
  https://postgresql.org/message-id/CAH2-Wz%3DT-pdQNo0k7-%2BFQxs3OcMVP3Td1NhZ0n3afP1C-g%3D4Ag%40mail.gmail.com.
  This is why rule 4 uses `DO UPDATE`: the claim must also be the mutex for a found row.
- `DO NOTHING` treats another session's `FOR UPDATE` row lock as a conflict and moves on, while it waits
  on an uncommitted delete; "the documentation is not quite accurate" (Albe, 2026). **Read**,
  https://www.postgresql.org/message-id/83819e975523be4d320141ff1363dfb40c82289b.camel%40cybertec.at.
  Another reason not to build the claim on `DO NOTHING`.
- `RETURNING` returns only rows inserted, updated or selected. **Read** (sql-insert.html). Current docs
  also show `ON CONFLICT DO SELECT` ("an atomic INSERT or SELECT outcome"), apparently new in v19
  (**read** for the docs, version **inferred** from a commit snippet): it would let the claim return a
  found row without writing a new version, once TAP's Postgres floor reaches it.
- READ COMMITTED: under `DO UPDATE` each proposed row "will either insert or update", even when no
  version of the conflicting row is visible to the snapshot. **Read**,
  https://www.postgresql.org/docs/current/transaction-iso.html.
- "If a conflicting row has been inserted by an as-yet-uncommitted transaction, the would-be inserter
  must wait." **Read**, https://www.postgresql.org/docs/current/index-unique-checks.html. That wait is
  what makes unsorted overlapping batches deadlock (**measured**: 5 of 5).

**PostgreSQL: the lock table.**
- Advisory and regular locks share one pool; exhausting it means the server "will be unable to grant
  any locks at all". Row locks are not in it ("no limit on the number of rows locked at one time"), but
  `SELECT FOR UPDATE` "will result in disk writes". Lock in a consistent order to avoid deadlock.
  **Read**, https://www.postgresql.org/docs/current/explicit-locking.html.
- `max_locks_per_transaction` is per server process or prepared transaction and "is not the number of
  rows that can be locked; that value is unlimited"; a standby must be set at least as high as the
  primary. Current docs give a default of 128; v16 gives 64. **Read**,
  https://www.postgresql.org/docs/current/runtime-config-locks.html,
  https://www.postgresql.org/docs/16/runtime-config-locks.html. The tap-db image (PostgreSQL 18.6) runs
  64 by default (**measured**). The `× (max_connections + max_prepared_transactions)` sizing is
  **inferred** from that wording.

**MERGE (PG15+).** MERGE "does not guarantee that either INSERT or UPDATE will occur"; a concurrently
inserted duplicate raises a unique violation and "MERGE does not attempt to avoid such errors"; the
MERGE page points to `ON CONFLICT` as the alternative. **Read**,
https://www.postgresql.org/docs/current/transaction-iso.html,
https://www.postgresql.org/docs/current/sql-merge.html; intended behaviour per Herrera 2022, **read**,
https://postgresql.org/message-id/202203191048.fejpvy4fld7d%40alvherre.pgsql. PG17 adds MERGE
`RETURNING` (**read**, https://www.postgresql.org/docs/17/release-17.html). **Inferred:** MERGE is fit
for a single-writer step (a seal), not for the concurrent claim.

**Deadlocks and the sorted-input remedy.**
- Tom Lane on concurrent `DO NOTHING` batches deadlocking: "arrange to order them consistently across
  transactions (eg, sort by primary key before inserting)". **Read**,
  https://postgresql.org/message-id/2587192.1726865228%40sss.pgh.pa.us.
- The order of uniqueness checks is practical behaviour, not a guarantee ("I dunno that we 'guarantee'
  that"); an explicit `ORDER BY` in the sub-select prevents flattening, "enough to make it safe".
  **Read**, https://www.postgresql.org/message-id/14928.1578605226%40sss.pgh.pa.us,
  https://www.postgresql.org/message-id/29386.1528813619@sss.pgh.pa.us. Risk carried into the
  decisions: the deadlock-freedom argument rests on implementation behaviour, so a test must pin it.
- Practitioner write-ups report the same fix (sort by the conflict key, dedupe the batch). **Inferred**
  (snippets): https://lnagle.github.io/debugging-a-deadlock.html, https://habr.com/ru/post/702902.

**River (riverqueue) PR 590.** Replaced advisory-lock uniqueness ("slow and conflict-prone", single
insert only) and a hash-plus-hardcoded-states index with `unique_key`, a `unique_states` bitmask and a
partial unique index whose predicate is a function of the row's state; "does not rely on advisory
locks in any way"; enables bulk unique inserts. **Read**, https://github.com/riverqueue/river/pull/590,
https://github.com/riverqueue/river/releases/tag/v0.12.0. Follow-ups: jobs in conflict with themselves
on state transitions (v0.12.1, #619), building the index `CONCURRENTLY` (#690), empty or encoded keys
(#739, #777), JSON keys containing path syntax (#1387), a key-format change where "old and new clients
may briefly insert duplicates" (#1377), a duplicate across job kinds (#1421). **Read**,
https://github.com/riverqueue/river/releases/tag/v0.12.1,
https://github.com/riverqueue/river/blob/master/CHANGELOG.md. **Inferred:** River's bugs sat in key
canonicalisation and the live-state predicate, not in the index. That is why rules 8 and 12 check the
derivation, and why a digest-recipe change is a re-derive with a migration, never a silent switch.

**Django.**
- `UniqueConstraint(*expressions, condition=Q(...))` gives functional and partial unique indexes; such
  a constraint cannot be deferrable. **Read**, https://docs.djangoproject.com/en/6.1/ref/models/constraints/.
- `bulk_create(update_conflicts=True, unique_fields=...)` takes field names only. A conditional
  constraint makes it fail with "there is no unique or exclusion constraint matching the ON CONFLICT
  specification"; the answer there is raw SQL. Ticket #34943 (constraint names in `bulk_create`) is
  Accepted with no patch. **Read**, https://docs.djangoproject.com/en/6.1/ref/models/querysets/,
  https://forum.djangoproject.com/t/unique-constraint-not-found-in-bulk-creates-unique-fields/42820,
  https://code.djangoproject.com/ticket/34943.
- NetBox ships a conditional expression constraint in Django:
  `UniqueConstraint(Lower('name'), 'site', 'tenant', condition=Q(name__isnull=False), nulls_distinct=False)`.
  **Read**, https://github.com/netbox-community/netbox/blob/main/netbox/dcim/models/devices.py.

**Comparable ingest systems.**
- **OpenCTI** takes Redis Redlock locks per deduplicated id; a 12M-operation import stalled on
  "too many concurrent call on the same entity", answered as "not something you can definitely avoid".
  **Read**, https://github.com/OpenCTI-Platform/opencti/blob/master/opencti-platform/opencti-graphql/src/database/redis.ts,
  https://github.com/OpenCTI-Platform/opencti/issues/3019.
- **DataHub** keys aspects by `(urn, aspect, version)` and, since 2026-08, adds an opt-in sorted, deduped
  per-key `pg_advisory_xact_lock` for write serialisation, while the key and a compare-and-set guard
  identity. It is the closest analogue to TAP's current design, and its code does not mention the
  lock-table limit. **Read**,
  https://github.com/datahub-project/datahub/blob/master/metadata-io/src/main/java/com/linkedin/metadata/entity/ebean/EbeanAspectDao.java;
  a >10k-asset concurrent-update failure, **read**, https://github.com/datahub-project/datahub/issues/7757.
- **Backstage** wraps provider writes in `retryOnDeadlock` (40P01) and still reports recurring deadlocks
  on multi-row `refresh_state` updates. **Read**,
  https://github.com/backstage/backstage/blob/master/plugins/catalog-backend/src/database/DefaultProviderDatabase.ts,
  https://github.com/backstage/backstage/issues/31868.
- **NetBox** has an open request for server-side retry on 40P01 under concurrent writes. **Read**,
  https://github.com/netbox-community/netbox/issues/22503.
- **CloudQuery**'s Postgres destination batches 10,000 rows and, with `COPY`, merges each batch with
  one `INSERT ... ON CONFLICT`, because COPY has no conflict clause. **Read**,
  https://www.cloudquery.io/hub/plugins/destination/cloudquery/postgresql/latest/docs.
- **Dependency-Track** deadlocks were MSSQL-only or partition DDL, not identity. **Read**,
  https://github.com/DependencyTrack/dependency-track/issues/3133,
  https://github.com/DependencyTrack/dependency-track/issues/6343. Its database identity rule was not found.

**Staging table pattern and its cost.** Go's pkgsite uses `CREATE TEMP TABLE ... ON COMMIT DROP`,
`COPY`, then `INSERT ... SELECT ... ON CONFLICT`. **Read**,
https://go.googlesource.com/pkgsite/+/HEAD/internal/database/copy.go. Temp tables created per
transaction leave dead tuples in the system catalogs, "the most frequent cause of bloated catalogs".
**Read**, https://www.percona.com/blog/what-hurts-in-postgresql-part-one-temporary-tables. **Inferred
for TAP:** stage through `unnest()` of array parameters, or one session-lived temp table
`ON COMMIT DELETE ROWS`, rather than a temp table per batch.

**Bloat and HOT.** HOT needs no indexed column changed and free space on the page. **Read**,
https://www.postgresql.org/docs/current/storage-hot.html. A no-op `DO UPDATE` still writes a new tuple
and WAL. **Read**, https://mergify.com/blog/on-conflict-do-update-rewriting-rows-you-never-changed.
**Measured** here: 20,000 resend updates, 0 HOT, 20,000 dead tuples on a packed table.

**Chunked runs with a seal.** CloudQuery's `overwrite-delete-stale` deletes, at the end of a sync, rows
from that source the sync did not touch (**inferred**, docs snippet,
https://www.cloudquery.io/docs/core-concepts/syncs). Airbyte's state message says "all records which
came before it have been successfully written", making syncs resumable. **Read**,
https://docs.airbyte.com/platform/understanding-airbyte/airbyte-protocol. Both are the shape of
proposal 2: chunks, then one step that only a complete run licenses.

**Where this approach has bitten people.** Key canonicalisation and live-state predicate bugs (River).
Deadlocks among concurrent multi-row writes, handled by retry rather than removed (Backstage,
NetBox). Unique violations from MERGE under concurrency. The ORM unable to target a partial arbiter
(Django). No-op `DO UPDATE` bloat. Catalog bloat from temp tables. And DataHub, which in 2026 moved
toward sorted per-key advisory locks, with no sign that it has met the lock-table limit yet.

## Decisions For The Owner

1. **Supersede `req-grid-entity-natural-key-3` and `-22` for identity (one live row per identity,
   enforced).** Both were ruled recently (`-22` on 2026-11-11), and the index contradicts them: today
   two live `panel` rows sharing a slug are created through the service layer without complaint, and
   that is `-3`'s acceptance test. **Recommend: supersede.** A duplicate today does not stay harmless: it
   makes every later import of that key fail as `identity_ambiguous`, so refusing the second write
   moves a persistent failure to the moment it is caused. `-3`'s own note expects the constraint with
   perspectives; 0.5.0 with reload is the cheapest time to add it. If a type genuinely needs duplicate
   live rows, it opts out by declaration and keeps today's search under the mutex-row lock (rule 11),
   rather than every type paying for it.
2. **Where the constraint lives: spine digest or typed-table constraints.** **Recommend: the spine
   digest** (one column, one index, core migration only, no plugin migrations, no dependency on
   `wave3-copies`, no row-size limit, one sort order across types). The typed-table form is the
   alternative if the owner wants the database to compare the stored columns themselves rather than a
   derivation; it then needs a hashed expression for long keys and runtime DDL for edges.
3. **Explicitly addressed and service-layer creates of an existing identity.** With rule 2 of the
   acceptance criteria, an id-addressed create whose key is already live is refused (today it silently
   makes a duplicate). **Recommend: refuse, with an error naming the live row**, not convert to found:
   an explicit id is the caller asserting a new object.
4. **Discriminator or key edits that collide.** An update that changes a row's key onto another live
   row's identity fails on the index. **Recommend: refuse** (it is the duplicate `-3` allowed);
   say so in the write pipeline's error.
5. **Mutex rows as the fallback.** If decision 1 is "keep `-3`/`-22`", **recommend mutex rows** for
   0.5.0 (bounded, semantics unchanged, measured), not lock striping (the correction comment's analysis
   stands).
6. **Chunked submit.** **Recommend: after 0.5.0**, as its own requirement on `CollectorBase`, motivated
   by transaction size, not the lock table. **Refuse-before-start: drop.**
7. **Deletes by identity in the same batch as claims.** Rule 5 locks existing rows first, then claims.
   Two batches remain deadlock-free; a third writer committing a new row of a shared key between one
   batch's lock pass and its claim can still close a cycle, which PostgreSQL detects and the batch
   retries. **Inferred, not measured. Recommend: accept, and measure it in the barrier tests**; a
   zero-window design (claiming deletes inside the one sorted statement) costs placeholder rows.

## Suggestions For How To Proceed

Ordered. Steps 1 to 6 are 0.5.0; step 7 and later follow.

1. **Rule on decisions 1 and 2** (supersede `-3`/`-22` for identity; spine digest). Everything else
   follows from these. If decision 1 is "keep", go to step 1b: mutex rows replace the advisory lock
   inside `resolve_identity` / `resolve_edge_identity` / `_take_identity_locks`, nothing else changes,
   and the rest of this list is post-0.5.0.
2. **Spec first.** Land this requirement and the amendments to `spec-grid-entity.md` and
   `spec-grid-edge.md` (`-3`, `-13`, `-22`, edge `-4`, `-5`, `-12`, the L611 note). Codex reviews it.
3. **Derive the digest** at every `natural_key` write site and in `Edge.save`, with the drift check in
   `sync_spine_natural_keys` (rules 1 and 12). It is pure derivation and can land before the index.
4. **The 0.5.0 core migration** adds the column and the partial unique index, with a preflight query
   that names duplicate groups. Release note: reload the grid.
5. **The claim.** Replace `_take_identity_locks` + the generated search on the importer path with the
   sorted claim (rules 4 to 7), staged through `unnest()` arrays or a session-lived temp table; then the
   single-key verbs (rule 6). Keep `_resolve_ref_identities`' substitution and every issue code.
6. **Tests that pin the argument:** the `test_grift_lock_order.py` barrier tests with an unsorted
   control; two writers on one new key; a 20,000-key batch on a `max_locks_per_transaction = 64`
   server with a flat `pg_locks` count (it can run in the lean lane against a throwaway server, as the
   prototype did); the tombstoned-while-waiting case. Measure one real qualys-sized `grift_import` end to
   end and record it on the requirement.
7. **After 0.5.0:** the chunked submit with a seal on `CollectorBase`, as its own requirement, motivated
   by transaction size and failure scope; then thin the qualys workaround onto it. Drop
   refuse-before-start. Fold the observation-pointer write into the claim's `DO UPDATE` (or adopt `ON
   CONFLICT DO SELECT` when the Postgres floor allows) to cut the extra row version.

**Risks.**
- The digest is only as right as its derivation (River's bug history). Mitigated by rules 8 and 12;
  a recipe change is a migration.
- Deadlock-freedom rests on PostgreSQL checking uniqueness in the `ORDER BY` order, which is behaviour,
  not a guarantee (Tom Lane, cited above). Mitigated by the unsorted-control test; a deadlock, if one
  ever occurs, is detected and the atomic batch is retried, which is no worse than today.
- Superseding two fresh rulings can break callers that create duplicates on purpose; the `-3` panel
  test is the known one. Grep core and first-party plugins for duplicate-creating fixtures before step 4.
- The write pipeline must accept a spine row the claim already inserted (a new path in create); that
  is the largest code change and the least prototyped part.
- A third concurrent writer can still close a cycle around deletes by identity (decision 7).

## What This Draft Could Not Establish

- End-to-end `grift_import` time at 20,000 keys through the real Python write pipeline: the prototype
  is SQL-only. The lock count is measured through the real lock code; the claim's speed is not.
- Whether any shipped type relies on duplicate live rows (the `panel` slug case of `-3`). The
  hard-things grid has none: 0 duplicate live `(entity_type, natural_key)` groups among 1,331 live
  nodes, and 0 duplicate live edge groups by (type, source, target). **Measured, one small grid.** Field
  grids and plugin test fixtures were not checked.
- The claim waiting on a row that another transaction tombstones (acceptance -5's second half):
  inferred from PostgreSQL's documented retry, not exercised.
- The real number of relation locks a large batch takes when it touches many typed tables, their
  indexes and history tables: bounded by the schema, not the batch, but not measured with a full plugin
  set.
- A latent race in today's lock key, inferred and not tested: `identity_lock_key` canonicalises the raw
  payload values, not the field-coerced ones, so `"443"` and `443` on an integer key column take two
  locks while the search treats them as one key; two concurrent first writes could then both miss and
  both create. The digest is derived from the field-coerced composition, which closes it.
- HOT behaviour with a lower `fillfactor` on `tap_entity`, and vacuum load under repeated resends.
