# RLS tombstone spike (PARTIAL: timings incomplete)
Engine: repo's own tap-db:0.2.2 image = PostgreSQL 16.14 (Wolfi, FIPS). NOTE the repo compose uses PG 16, not 18.
Data (EXPLAIN-free counts, queries run): 3,000,000 tap_entity rows (1M findings + 2M edge entities), 147,190 tombstoned (4.9%: 3% of nodes plus edges touching them),
1M spike_finding, 2M tap_edge, 117,305 dead edges, 0 live edges touching dead endpoints. Indexes mirror 0001 + Edge Meta. uuids are v4 (real is v7); md5() unavailable under FIPS.
Container capped 3g/2cpu; removed with volume at end. Machine load during runs: 35 -> 12 (8 cores). Scripts beside this file.
## Correctness (verified by running queries; load-independent)
- V1 and V2 as spike_search: spike_finding 970,115 rows (not 1,000,000), tap_entity 2,852,810 rows with 0 tombstones, tap_edge 1,882,695 (not 2,000,000); point lookup of a dead id returns 0 in finding/entity/edge; joins from entity or from edge cannot reach a tombstone; EXISTS on dead returns 0. Typed-only query (shape a) IS filtered.
- BYPASSRLS role, table owner, superuser: see everything (1,000,000 / 3,000,000 / 147,190 tombstones). FORCE RLS on owner with policy only TO spike_search: owner sees 0 rows (default deny), so FORCE needs an owner policy.
- V1 plan: RLS EXISTS is NOT converted to a semi-join. It stays a correlated SubPlan on tap_entity_pkey per row; filter shows (deleted_at IS NULL) AND (deleted_at IS NULL) on tap_entity (double filter, harmless); parallel scan is lost (Seq Scan, not Parallel). Shape b under V1 combines the SubPlan and the explicit join.
- V2 drift trap: denormalised deleted_at is NOT maintained by tombstoning tap_entity. Tombstoned a live finding in tap_entity only: spike_search still saw the typed row (1) while tap_entity hid it (0). V2 needs the tombstone writer (or trigger) to update the typed table and edge in the same transaction.
- V3b (policy NOT IN (SELECT id FROM tap_entity WHERE deleted_at IS NOT NULL)) is WRONG: the subselect is itself RLS-filtered so it is empty; spike_search saw 1,000,000 rows. Trap.
- V3a (STABLE SQL function wrapper): correct (970,115 rows) but not inlined, parallel-unsafe by default; plan = Seq Scan with spike_live(entity_id) as filter, cost 279k vs 22k baseline. Not recommended.
- V3c (owner-run view spike_dead + NOT IN): correct; plan = Parallel Seq Scan with hashed SubPlan (each of 3 workers builds a 147k hash via bitmap scan). One EXPLAIN ANALYZE under load 18: 22.8 s (unreliable, IO wait), not a proven fix.
## Timings
Only run-one-variant-at-a-time under load 25-38, widely noisy, medians of 7: V0 (no RLS) as spike_search a 155ms b 1678 c 54 d 759 e 3429 f 498. A first V1 run was invalid (policies had not been created: psql \i inside container). The second V1 run, load ~20-35, got a ~10,460 ms median (runs 5.5-19.9 s) vs 155 ms for V0 on shape a, b 11,326, c 2,023, d 16,828 (runs 7-39 s) ; single clean EXPLAIN ANALYZE a=5,487 ms (400k SubPlan probes at ~0.010 ms each). The ratio is large (~35-100x on a) even allowing for load, but absolute numbers are unreliable (spread >>1.5x). e and f under V1 and ALL V2 / V3c timings were NOT obtained: the requested interleaved run (R=4, with uptime per timing) was started and killed at handback; interleave.sh and summarize.py exist to rerun.
## Untested
Django ORM path, Gryphon corpus SQL-text comparison, V2 timings, write-path cost of denormalising, partial-index benefit, session-variable policy (sketch below is unverified).
## Enable / disable SQL
V1/V2 enable: ALTER TABLE t ENABLE ROW LEVEL SECURITY; CREATE POLICY pol ON t FOR SELECT TO spike_search USING (...); disable: DROP POLICY pol ON t; ALTER TABLE t DISABLE ROW LEVEL SECURITY. See v_1.sql, v_2.sql, v_2_prep.sql.
Session-variable sketch (UNTESTED): USING (deleted_at IS NULL OR current_setting('tap.show_tombstones', true) = 'on').
