-- 03_load.sql failed at VACUUM ANALYZE (parallel worker needs /dev/shm > docker's 64MB); data+indexes+GRANT had committed. Redo with parallel off.
SET max_parallel_maintenance_workers=0;
VACUUM ANALYZE tap_entity; VACUUM ANALYZE spike_finding; VACUUM ANALYZE tap_edge;
SELECT count(*) total, count(deleted_at) dead FROM tap_entity;
SELECT count(*) edges, count(*) FILTER (WHERE ee.deleted_at IS NULL AND (f.deleted_at IS NOT NULL OR t.deleted_at IS NOT NULL)) live_touching_dead, count(*) FILTER (WHERE ee.deleted_at IS NOT NULL) dead_edges FROM tap_edge x JOIN tap_entity ee ON ee.id=x.entity_id JOIN tap_entity f ON f.id=x.from_entity_id JOIN tap_entity t ON t.id=x.to_entity_id;
SELECT pg_size_pretty(pg_total_relation_size('tap_entity')) ent, pg_size_pretty(pg_total_relation_size('spike_finding')) f, pg_size_pretty(pg_total_relation_size('tap_edge')) ed;
