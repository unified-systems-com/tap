# Identity Claims (draft amendment)

Draft for unified-systems-com/tap Issue 1348, for the 0.5.0 core migration wave. It replaces the
per-key advisory lock with a row lock on a claim table. Natural keys stay non-unique:
`req-grid-entity-natural-key-3` and `-22` (ruled 2026-11-11) are unchanged. Amends
`req-grid-entity-natural-key-13` (`spec-grid-entity.md`) and `req-grid-edge-identity` (`spec-grid-edge.md`).
Not yet in any repository.

Status: `Proposed`

Evidence marks: **measured** (this draft's prototype: `identity-claim-proof/run-*.txt`, and the earlier
`identity-index-proof/run-*.txt`), **read** (the code, a spec or a cited page says so), **inferred**
(reasoning, not tested).

## Philosophy

Two writers resolving one source object must serialise, and the second must find the first's row. That
is all the advisory lock was for, and it stays the rule. What changes is where the mutex lives: in a row
of a table, not a slot of the shared lock table. Row locks are kept in the tuple, so a batch of any size
holds a constant number of lock-table entries. Nothing about identity changes: the search, zero / one /
many, `identity_ambiguous`, the one sorted order of Issue# 943.

## The Problem, Measured

- The real importer, today's code, at Postgres defaults (`max_locks_per_transaction` 64,
  `max_connections` 100): one batch of 10,000 ref panels and 10,000 ref edges fails after 36.5 s with
  `execution_failed: out of shared memory`, holding 14,872 advisory locks when it failed. **Measured**
  (`run-default64-import-20000.txt`).
- Today's `_take_identity_locks` alone holds one advisory lock per key: 40,000 keys, 40,000 locks; at
  defaults it fails between 12,000 and 15,000 keys on an idle server. **Measured**
  (`identity-index-proof/run-today-real-code.txt`).
- Row locks do not use the lock table: `max_locks_per_transaction` "is *not* the number of rows that can
  be locked; that value is unlimited". **Read**,
  https://www.postgresql.org/docs/current/runtime-config-locks.html.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-identity-claim | [Identity Claims](#identity-claims) | Proposed | The identity lock is a row lock on `tap_identity_claim`, one row per identity fingerprint, claimed in one sorted pass per kind; every identity rule is unchanged; a batch's lock-table use is constant |

### Identity Claims

RID: `req-grid-identity-claim`

Status: `Proposed`

#### Rules

1. **The table.** `tap_identity_claim`, a plain core table created by core's 0.5.0 migration
   (`migrations.RunSQL`), with no plugin migration:

   | Column | Type | Why |
   | --- | --- | --- |
   | `fingerprint` | `bytea` primary key | The identity (rule 2). The primary key is the only index. |
   | `entity_type` | `varchar(255) NOT NULL` | The node type slug, or `edge:<edge_type>`: diagnosis (`which types hold claims`) and pruning by type. |
   | `recipe` | `smallint NOT NULL` | The fingerprint recipe the row was made with (rule 2). |
   | `claimed_at` | `timestamptz NOT NULL DEFAULT now()` | When the row was first claimed: diagnosis, and age for pruning (rule 9). |

   It is not a Django model, like `tap_spine_type_table` on the `wave3-copies` branch, which is "Not a
   Django model, so ``flush`` (which empties every model table) leaves it alone" (**read**,
   `tap_grid/spine_copies.py:56-58` there). That matters less here than for the type map: a claim
   carries no identity, so a claim left behind by a flush is harmless (rule 9). It holds no grid data and
   is not a classified grid table (`req-grid-table-classification.sec`); the read-only search role is not
   granted it, because a fingerprint of a guessable key (a hostname) is a dictionary-checkable digest of
   grid data.
2. **The fingerprint.** `sha256(recipe || 0x1E || identity_text)`, as 32 bytes, where `identity_text`
   is what the lock key means today, built from **field-coerced** values:
   - A node: `entity_type || 0x1F || compose_natural_key(model, values)`, after
     `normalize_natural_key`. `compose_natural_key` is the spine's stored form
     (`req-grid-entity-natural-key-19`): field-coerced (`"443"` and `443` on an integer column are one
     key), JSON values typed (`123` and `"123"` are two), injective per type. So the fingerprint of any
     stored row can be recomputed from that row. No fingerprint when the key has a hole (as today).
   - An edge: the `edge_lock_key` string, unchanged (both endpoint ids canonicalised, the discriminator
     values canonically serialised and compared typed, as the edge search compares them). Keyless types
     use (type, source, target) as today.
   - One function per kind, beside `identity_lock_key` and `edge_lock_key`, which they replace.
   - `recipe` starts at 1. A change to the recipe changes every fingerprint, so it ships as a migration
     and a release note: every writer must run the new recipe before any writes, because old and new
     writers would claim different rows for one key and stop serialising (River's #1377 hit exactly
     this, see Prior Art). Rows of an old recipe are then pruned.
   - This closes a race today's lock key has, **inferred** from the code and not reproduced:
     `identity_lock_key` canonicalises the raw payload values (`tap_grid/natural_key.py::key_values`
     reads `constituting_properties` of the payload), while `find_existing` filters through the ORM,
     which coerces. Two first writers sending `"443"` and `443` for one integer key column take two
     different locks, both miss, and both create.
3. **The claim, for a batch.** Inside the batch's transaction, in two statements, both sorted by
   fingerprint:

   ```sql
   INSERT INTO tap_identity_claim (fingerprint, entity_type, recipe)
   SELECT f, t, 1 FROM unnest(%(fps)s::bytea[], %(types)s::text[]) AS u(f, t) ORDER BY f
   ON CONFLICT (fingerprint) DO NOTHING;

   SELECT count(*) FROM (SELECT 1 FROM tap_identity_claim WHERE fingerprint = ANY(%(fps)s)
                         ORDER BY fingerprint FOR UPDATE) held;
   ```

   The first statement inserts every new fingerprint (an uncommitted insert is a lock: a second inserter
   of that fingerprint waits for this transaction to end) and skips existing ones without locking them.
   The second row-locks every claimed fingerprint, in order. The count must equal the number claimed; a
   shortfall means a row was pruned between the two statements, and the claim runs again (rule 9).
   Staging is a bound array (`unnest`), not a temporary table (Prior Art: catalog bloat).
4. **One order, as today.** The importer claims every node fingerprint the batch will need, then, once
   every endpoint is final, every edge fingerprint (ref edges, keyless duplicate checks and deletes by
   identity together), exactly where `_take_identity_locks` takes them today. Then the existing
   resolution runs unchanged: the search, zero / one / many, `identity_ambiguous`, the in-batch
   duplicate refusals (`duplicate_entity_id`, `duplicate_edge`), `KeylessEdgeExists`.
5. **The single-key verbs.** `resolve_identity`, `resolve_edge_identity` and `find_edge_by_identity`
   claim their one fingerprint the same way in place of `pg_advisory_xact_lock`, still refusing to run
   outside a transaction. The claim is re-entrant: a fingerprint this transaction already holds is
   skipped by the insert and re-locked by `FOR UPDATE` without waiting (**measured**: 3 re-claims of held
   keys, 1.1 ms, no wait), so the verbs keep claiming after the importer has.
6. **Why the deadlock argument survives.** Issue# 943's argument is that every batch acquires the
   mutexes it shares with another in one global order, so none holds one while waiting for another's.
   With claims:
   - In the insert statement a transaction waits only on another's *uncommitted insert* of the same
     fingerprint. Both insert in fingerprint order, so if T1 waits on T2 at fingerprint `w`, T2 inserted
     `w` first and every fingerprint T1 holds by insertion is below `w`; T2 cannot be waiting on one of
     them, because T2 reaches those before `w`.
   - By the time a transaction runs the `FOR UPDATE` statement, each of its fingerprints is either one it
     inserted or a committed row (an uncommitted insert by another would have stopped it in the insert
     statement). `FOR UPDATE` then waits only on row locks taken in the same order: the classic ordered
     acquisition.
   - Nodes are claimed in full before any edge, as today, so a transaction claiming edges never waits on
     a transaction that is still claiming nodes for a mutex that one holds.
   - **Measured:** two writers of 20,000 fingerprints each, half shared, the shared half in opposite
     orders, released together, five rounds: sorted, 10 of 10 committed, 0 deadlocks; claimed one at a
     time in opposite orders, 5 deadlocks in 5 rounds (`run-claim-toy.txt`). The same with the single
     `DO UPDATE` statement (rule 7's alternative): 0 and 5. The real suites pass on the prototype patch:
     `test_grift_lock_order.py::TestOppositeOrders`, `test_grift_identity.py::TestTwoWriters`,
     `test_grift_edge_identity.py::TestTwoWriters` (a plain key and a keyless type),
     `test_batch_corpus_concurrency.py::TestTiming` (the holder blocks the contender, observed by pid
     through `pg_blocking_pids`), with every other test in those four files: 72 passed in each claim mode, `DO UPDATE` and
     `DO NOTHING` + `FOR UPDATE` (`run-claim-targeted-tests.txt`).
   - The ordering rests on PostgreSQL processing `INSERT ... SELECT ... ORDER BY` in that order, which is
     behaviour, not a guarantee (Tom Lane, Prior Art); the opposite-order tests pin it.
   - **The lazy single-key caller.** A verb called outside the importer, one key at a time, in its own
     order, inside a longer transaction, can still close a cycle with a sorted batch. This is unchanged
     from today: in a forced schedule (the lazy caller holds `b`, the batch takes `a` and queues on `b`,
     the lazy caller asks for `a`) both the advisory lock and the claim give `deadlock detected`, and
     PostgreSQL aborts one side; the batch is atomic and can be retried (**measured**,
     `run-claim-toy.txt`). Callers that take more than one identity must take them in one sorted claim.
7. **`DO NOTHING` then `FOR UPDATE`, not `DO UPDATE`.** Both were measured on 20,000 keys:
   - `INSERT ... ON CONFLICT DO UPDATE SET claimed_at = now()` is one statement, one pass, and
     prune-safe by construction (a pruned row is simply inserted again). But every resend writes a new
     version of every found claim: 20,000 updates, 0 HOT, 20,000 dead tuples per resend of a 20,000-key
     batch, and a second version each time a verb re-claims. **Measured.**
   - `DO NOTHING` + `FOR UPDATE` writes no new version (0 updates, 0 dead tuples after first write and
     resend), at the same speed (first 0.19 s, resend 0.15 s, against 0.13 s and 0.18 s). `FOR UPDATE`
     still marks each tuple and writes WAL ("will result in disk writes", **read**, explicit-locking).
   - Recommend `DO NOTHING` + `FOR UPDATE`: the claim table is rewritten on every collector run otherwise.
     Its one extra duty is rule 3's count check.
   - `DO NOTHING` treats a row another session holds `FOR UPDATE` as a conflict and moves on, rather than
     waiting (**read**, Albe 2026, Prior Art); that is what this design wants, since the `FOR UPDATE`
     statement does the waiting.
8. **Lock-table use is constant.** **Measured** through the real importer, the whole server's entries
   for the importing database at peak:

   | Batch | Today | Claims (`DO UPDATE` mode) |
   | ---: | ---: | ---: |
   | 400 keys | 496 (400 advisory) | 107 |
   | 5,000 keys | 5,108 (5,000 advisory) | 112 |
   | 20,000 keys, defaults server | failed at 14,926 (14,872 advisory) | 118 |

   The claim itself holds about 5 to 7 entries (the table, its primary key, a virtual and a transaction
   id; **measured**, toy). The rest, about 100 here, are relation locks on the tables and indexes the
   batch writes: bounded by the **schema** (how many typed tables, history tables and their indexes one
   batch touches), not by the batch size. What is not bounded by anything here: nothing in identity. A
   batch that touches many plugin types still needs `max_locks_per_transaction` sized for its relation
   locks times concurrent importers, which is a deployment setting, not a batch limit (**inferred**; a
   full plugin set was not measured).
9. **Growth and pruning.** One row per identity ever claimed, about 172 bytes each with its primary key
   (**measured**: 1,000,000 claims, heap 93 MB + index 79 MB after vacuum). That grows no faster than
   `tap_entity`, which keeps tombstones: 10 million identities is about 1.7 GB. **Pruning is not needed
   for 0.5.0.** When it is, the rule is:
   - A claim carries no identity, only a mutex, so **any claim nobody holds may be deleted**; a later
     claimant inserts it again. The pruner takes rows with `FOR UPDATE SKIP LOCKED` and deletes them, in
     bounded slices, optionally only rows older than a horizon (`claimed_at`) so hot identities are not
     churned.
   - **Measured:** with 100 claims held, a prune of 1,000 rows deletes the 900 unheld ones and leaves the
     held 100. A claimant racing an uncommitted prune of its rows waits for the prune (0.49 s) and then
     holds all 10 rows it asked for. With `DO NOTHING` + `FOR UPDATE`, a prune committed between the two
     statements leaves the claimant holding 0 of 10, which rule 3's count check catches and re-claims.
   - A "claim with no live entity" rule is not needed and is costlier (it recomputes fingerprints from
     rows); an unheld claim is always safe to drop.
10. **Cost.** The claim does not change what a batch costs; the search still runs once per key. Through
    the real importer, one batch, first write then resend: 5,000 keys, today 40.6 s / 39.9 s, claims
    40.1 s / 38.3 s (private database, `max_locks_per_transaction` 512); 20,000 keys at defaults, today
    fails, claims 171.8 s / 155.4 s. **Measured** (`run-shared512-import-5000.txt`,
    `run-default64-import-20000.txt`). About 8 ms per key in both, spent in the per-row write pipeline,
    not in identity. In isolation the claim is 0.15 to 0.19 s for 20,000 keys (**measured**, toy).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-identity-claim-1 | No Advisory Lock Per Key | Proposed | The importer and the three verbs take no `pg_advisory_xact_lock` for identity; each identity is a claim row. | Prototype patch: `identity-claim-proof/claim-patch.diff`. |
| req-grid-identity-claim-2 | Constant Lock-Table Use | Proposed | A batch of 10,000 ref nodes and 10,000 ref edges imports on a server at `max_locks_per_transaction = 64`, and the importing database's peak `pg_locks` count differs by no more than a small constant between a 400-key and a 20,000-key batch. | Measured: 107 and 118. Runs against a throwaway server, as the prototype did. |
| req-grid-identity-claim-3 | Rules Unchanged | Proposed | Every existing acceptance of `req-grid-entity-natural-key-13` and `req-grid-edge-identity-1` to `-11` passes unchanged with claims. | Measured: 72 passed across `test_grift_identity.py`, `test_grift_edge_identity.py`, `test_grift_lock_order.py`, `test_batch_corpus_concurrency.py`. |
| req-grid-identity-claim-4 | Opposite Orders, Sorted And Unsorted | Proposed | The opposite-order barrier tests pass; a control that claims one key at a time in opposite orders reproduces `deadlock detected`, so the sort stays load-bearing. | Toy: 0 of 5 and 5 of 5. |
| req-grid-identity-claim-5 | Coerced Fingerprint | Proposed | Two concurrent first writers of one integer-keyed node, one sending `"443"` and one `443`, produce one row. | Rule 2's race; needs a fixture type with an integer key. |
| req-grid-identity-claim-6 | Re-Entrant | Proposed | A transaction that holds a claim claims it again without waiting. | Measured. |
| req-grid-identity-claim-7 | Claims Are Not Grid Data | Proposed | `tap_identity_claim` is absent from the grid-table classification and the search role's grants; `flush` leaves it. | |
| req-grid-identity-claim-8 | A Pruned Claim Is Claimed Again | Proposed | A claim committed-deleted between the insert and the lock is detected by the count and re-claimed; a held claim is never pruned. | Measured in the toy; a pruner itself is not part of 0.5.0. |

#### Spec Amendments

- **`req-grid-entity-natural-key-13`** (`spec-grid-entity.md`): "Resolution runs inside the batch
  transaction under `pg_advisory_xact_lock` keyed by the declaration (`identity_lock_key`, derived from
  the type and the constituting values, never authored twice)" becomes "Resolution runs inside the batch
  transaction holding the identity's claim (`req-grid-identity-claim`: a row lock on its fingerprint,
  derived from the type and the field-coerced constituting values, never authored twice)". The notes'
  "A batch takes all its node identity locks up front, sorted by key" becomes "all its node claims up
  front, in one sorted claim". The `-19` note "The identity lock key keeps its existing format (`-13`),
  so a rolling deploy cannot split one object across two locks" is replaced by rule 2's recipe rule.
  Also the narrative at `spec-grid-entity.md` L923 and L928 ("under an advisory lock keyed by the
  declaration", "the same values key `pg_advisory_xact_lock`").
- **`spec-grid-edge.md` Lock paragraph (L596) and `req-grid-edge-identity-4`**: "the importer takes
  `pg_advisory_xact_lock` keyed by the identity" becomes "the importer claims the identity
  (`req-grid-identity-claim`)"; "Advisory transaction locks are re-entrant" becomes "A claim is
  re-entrant". `-12`'s "one advisory lock and one bounded search per looked-up edge" becomes "one claim
  and one bounded search"; its test
  `test_grift_edge_identity.py::TestTheVerb::test_each_looked_up_edge_costs_a_fixed_number_of_queries`
  counts `pg_advisory_xact_lock` statements and must count claim statements instead. The summary row
  ("under an advisory lock") and L586 likewise.
- **`spec-grid-edge.md` Development note (L611)**, "Why a lookup and not a unique index", stays true and
  is kept; only "The cost is the lock and the extra lookups per edge" becomes "the claim and the extra
  lookups per edge".
- **`tap_grid/tests/test_grift_lock_order.py`**: the done-test stays as it is (it passed on the
  prototype); its docstring's "Identity locks" becomes "Identity claims", and a case is added with the
  sort removed that expects `deadlock detected`.
- Elsewhere: `spec-grift-v0.md` L1461, `spec-grid-reconcile.md` `req-grid-reconcile-verb-5`'s note,
  `spec-grid-batch-corpus.md` L116 ("the identity advisory lock a ref resolution takes"), and the
  docstring of `tap_grid/tests/test_batch_corpus_concurrency.py`.

#### Development

**Considered and not chosen: a partial unique index with `INSERT ... ON CONFLICT`.** Prototyped in
`identity-index-proof/` (spine identity digest, or one constraint per typed table): bounded at 20
lock-table entries for 20,000 and 200,000 keys, 0.22 s for 20,000, no duplicates and no deadlock with two
sorted writers (**measured**). Not chosen, because it makes natural keys unique, which two standing rules
refuse: `req-grid-entity-natural-key-3` ("Two live rows of one type may share declared values when their
dimensions differ; no constraint prevents it") and `-22` ("Never unique", ruled 2026-11-11: a constraint
lets a first writer block a type's updates). Perspectives will need rows that share a key (Issue 907).
The claim table gives the same bounded lock count with identity unchanged. `-22`'s deferred
within-dimension constraint, `(entity_type, natural_key, identity_scope) WHERE deleted_at IS NULL`, can
later sit on the same fingerprint, which is computable from any stored row (rule 2), with the identity
scope added to its input.

**Considered and not chosen: lock striping** (Issue 1348 proposal 1). With n keys over 4,096 slots a
batch takes about `4096·(1−e^(−n/4096))` of them, so large batches serialise on a near-global mutex and
lazy callers deadlock more often (the issue's correction comment). The claim table keeps one mutex per
identity.

**Considered and not chosen: raising `max_locks_per_transaction`.** It must be sized for the largest
batch times concurrent importers, and a standby must match the primary (**read**, runtime-config-locks).
A stopgap, not a fix.

## Chunked Submit And Refuse-Before-Start

- **Refuse before starting** (proposal 3): drop it. There is no identity pool left to compare a batch
  against.
- **Chunked submit with a seal** (proposal 2): after 0.5.0, as its own requirement on `CollectorBase`.
  The lock table no longer motivates it; transaction size and failure scope do. A 20,000-key batch holds
  one transaction for 2.5 to 3 minutes (**measured**), with its WAL, its row locks and its memory, and
  one bad row loses the whole run. Chunks, then one seal batch carrying what only a whole run licenses
  (watermarks, withdrawals, reconcile claims, the collection window), which is the shape of Airbyte's
  state messages and CloudQuery's end-of-sync delete (Prior Art). Chunks find each other's nodes through
  endpoints by natural key (`req-grid-import-grift-edge-endpoints`).
- The qualys `WORKAROUND(unified-systems-com/tap#1348)` chunking can stay until the chunked submit lands;
  once claims land it is no longer needed for the lock table.

## Prior Art

Surveyed 2026-11-23 for this issue. **Read**: the page says so. **Inferred**: reasoning from what was
read, or seen only in a search snippet.

**PostgreSQL locking.**
- Advisory and regular locks share one pool; exhausting it means the server "will be unable to grant
  any locks at all". Row locks are not in it: "there is no limit on the number of rows locked at one
  time", but `SELECT FOR UPDATE` "will result in disk writes". Lock in a consistent order to avoid
  deadlock. **Read**, https://www.postgresql.org/docs/current/explicit-locking.html.
- `max_locks_per_transaction` is per server process or prepared transaction, not a row count, and a
  standby must be set at least as high as the primary. Current docs give a default of 128; v16 gives 64.
  **Read**, https://www.postgresql.org/docs/current/runtime-config-locks.html,
  https://www.postgresql.org/docs/16/runtime-config-locks.html. The tap-db image (PostgreSQL 18.6)
  defaults to 64 (**measured**).
- A would-be inserter of a key another uncommitted transaction inserted "must wait to see if that
  transaction commits". **Read**, https://www.postgresql.org/docs/current/index-unique-checks.html. This
  is the wait rule 6's first bullet relies on.

**`ON CONFLICT`.**
- `DO NOTHING` "doesn't lock any conflicting row, and so won't have to dirty pages" (Geoghegan, 2023).
  **Read**, https://postgresql.org/message-id/CAH2-Wz%3DT-pdQNo0k7-%2BFQxs3OcMVP3Td1NhZ0n3afP1C-g%3D4Ag%40mail.gmail.com.
- `DO NOTHING` moves on past another session's `FOR UPDATE` lock but waits on an uncommitted delete;
  "the documentation is not quite accurate" (Albe, 2026). **Read**,
  https://www.postgresql.org/message-id/83819e975523be4d320141ff1363dfb40c82289b.camel%40cybertec.at.
- `DO UPDATE` locks every conflicting row and may not touch one row twice in a statement ("cardinality
  violation"), so the fingerprints are deduplicated before the claim. **Read**,
  https://www.postgresql.org/docs/current/sql-insert.html.
- A no-op `DO UPDATE` still writes a new tuple and WAL. **Read**,
  https://mergify.com/blog/on-conflict-do-update-rewriting-rows-you-never-changed. HOT needs no indexed
  column changed and free space on the page. **Read**,
  https://www.postgresql.org/docs/current/storage-hot.html. **Measured** here: 20,000 updates, 0 HOT.

**Ordered acquisition.**
- Tom Lane on concurrent `ON CONFLICT DO NOTHING` batches deadlocking: "arrange to order them
  consistently across transactions (eg, sort by primary key before inserting)". **Read**,
  https://postgresql.org/message-id/2587192.1726865228%40sss.pgh.pa.us.
- The order of uniqueness checks is not guaranteed ("I dunno that we 'guarantee' that"); an explicit
  `ORDER BY` in the sub-select prevents flattening, "enough to make it safe". **Read**,
  https://www.postgresql.org/message-id/14928.1578605226%40sss.pgh.pa.us,
  https://www.postgresql.org/message-id/29386.1528813619@sss.pgh.pa.us.

**MERGE.** MERGE "does not guarantee that either INSERT or UPDATE will occur" and raises a unique
violation on a concurrent duplicate. **Read**,
https://www.postgresql.org/docs/current/transaction-iso.html. Not suitable for the claim.

**Comparable systems.**
- **River** (riverqueue) replaced advisory-lock uniqueness ("slow and conflict-prone") with a unique key
  and a partial unique index (PR 590). Its follow-up bugs were in key canonicalisation and the state
  predicate, and a key-format change where "old and new clients may briefly insert duplicates" (#1377).
  **Read**, https://github.com/riverqueue/river/pull/590,
  https://github.com/riverqueue/river/blob/master/CHANGELOG.md. River wanted uniqueness; TAP's rules
  refuse it, so the index half does not transfer. The canonicalisation lessons do: rule 2's coerced
  fingerprint and its recipe rule.
- **DataHub** added, in 2026, an opt-in sorted, deduplicated per-key `pg_advisory_xact_lock` to
  serialise writers of one (urn, aspect). It is the closest analogue to TAP's current design, and its code
  says nothing about the lock-table limit. **Read**,
  https://github.com/datahub-project/datahub/blob/master/metadata-io/src/main/java/com/linkedin/metadata/entity/ebean/EbeanAspectDao.java.
- **OpenCTI** takes one Redis Redlock per deduplicated id; a 12M-operation import stalled on "too many
  concurrent call on the same entity". **Read**,
  https://github.com/OpenCTI-Platform/opencti/blob/master/opencti-platform/opencti-graphql/src/database/redis.ts,
  https://github.com/OpenCTI-Platform/opencti/issues/3019. A per-identity mutex outside the lock table,
  with the same serialisation cost the claim has.
- **Backstage** and **NetBox** retry on deadlock (40P01) under concurrent multi-row writes rather than
  remove the cycle. **Read**,
  https://github.com/backstage/backstage/blob/master/plugins/catalog-backend/src/database/DefaultProviderDatabase.ts,
  https://github.com/backstage/backstage/issues/31868, https://github.com/netbox-community/netbox/issues/22503.
  TAP keeps the sort, and a lazy caller's deadlock (rule 6) is the case a retry covers.

**Staging.** Temporary tables created per transaction leave dead tuples in the system catalogs, "the
most frequent cause of bloated catalogs". **Read**,
https://www.percona.com/blog/what-hurts-in-postgresql-part-one-temporary-tables. Hence `unnest` of
bound arrays in rule 3.

**Chunked runs with a seal.** Airbyte's state message says "all records which came before it have been
successfully written", which makes a sync resumable. **Read**,
https://docs.airbyte.com/platform/understanding-airbyte/airbyte-protocol. CloudQuery's
`overwrite-delete-stale` deletes, at the end of a sync, rows the sync did not touch. **Inferred**
(snippet), https://www.cloudquery.io/docs/core-concepts/syncs.

## Decisions For The Owner

1. **`DO NOTHING` + `FOR UPDATE`, or one `DO UPDATE`.** Recommend `DO NOTHING` + `FOR UPDATE` (rule 7):
   no dead tuple per found claim per run, same speed, at the cost of the count check. `DO UPDATE` is the
   simpler fallback if the extra statement is unwanted.
2. **Fingerprint input for nodes: `compose_natural_key` or the canonical-JSON lock key over coerced
   values.** Recommend `compose_natural_key` (rule 2): it is already the spine's coerced, injective form,
   so a claim can be recomputed from any stored row, and `-22`'s deferred constraint can later reuse it.
3. **Pruning in 0.5.0.** Recommend not: about 172 bytes per identity, growing no faster than
   `tap_entity`. Specify the safe rule now (any unheld claim, `SKIP LOCKED`, optional age horizon) and
   build a pruner when a grid needs it.
4. **Grants.** Recommend the claim table be invisible to the search role (rule 1): a fingerprint is a
   digest of grid data.
5. **Multi-key callers outside the importer.** Recommend a rule that any caller claiming more than one
   identity claims them in one sorted call; the lazy single-key case stays what it is today.
6. **Chunked submit.** Recommend after 0.5.0 as its own requirement (transaction size, failure scope).
   **Refuse-before-start: drop.**

## Suggestions For How To Proceed

0.5.0 is steps 1 to 5; step 6 follows.

1. Land this requirement and the amendments (Spec Amendments above); Codex reviews.
2. The fingerprint functions (rule 2) beside `compose_natural_key` and `edge_lock_key`, with a test of
   the `"443"` / `443` race on a fixture type with an integer key.
3. The core 0.5.0 migration: `RunSQL` creating `tap_identity_claim`. A grid reload is not needed: the
   table starts empty and fills as identities are claimed.
4. `tap_grid/identity_claim.py::claim` (rules 3 and 5), called from `_take_identity_locks` (renamed) and
   the three verbs. The prototype patch is 103 lines including a throwaway migration
   (`identity-claim-proof/claim-patch.diff`); the build drops its prototype-only table check.
5. Tests: the four suites above unchanged; the unsorted control; the 20,000-key import on a
   `max_locks_per_transaction = 64` throwaway server with a flat `pg_locks` peak; the re-entrancy and
   pruned-claim cases; the `-12` query-count test rewritten.
6. After 0.5.0: chunked submit with a seal on `CollectorBase`; thin the qualys workaround onto it. Then,
   only if a grid's claim table grows large, a pruner.

**Risks.**
- The ordering rests on PostgreSQL behaviour, not a guarantee; pinned by the unsorted control.
- A recipe change during a rolling deploy splits one identity across two claims; mitigated by rule 2's
  migration rule (and moot before field deployments).
- Every found claim still writes: `FOR UPDATE` marks the tuple and writes WAL per key per run.
- The per-key search and the per-row write pipeline stay the cost of a batch (about 8 ms per key); a
  qualys-sized run is minutes in one transaction until the chunked submit lands.

## What Could Not Be Established

- The `"443"` / `443` race in today's lock key is from reading the code, not reproduced: no installed
  fixture type is keyed on an integer column.
- Relation-lock counts for a batch that touches many plugin types: the measured batches touched panels,
  one edge type and their history; a full plugin set was not measured.
- A pruner under load: only the three race cases were measured, in raw SQL.
- Mixed old and new importers during a deploy: not tested (old code takes advisory locks, new code
  claims, so they would not serialise with each other; pre-users, a deploy stops writers first).
- Long-run vacuum behaviour of `FOR UPDATE` on a large claim table: not measured.
