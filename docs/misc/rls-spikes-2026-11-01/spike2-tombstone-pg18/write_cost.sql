\timing on
-- 10,000 live findings: tombstone entity only, then entity + typed row, each rolled back so data is unchanged
BEGIN;
UPDATE tap_entity SET deleted_at=now(), updated_at=now(), version=version+1 WHERE id IN (SELECT entity_id FROM spike_finding f JOIN tap_entity e ON e.id=f.entity_id WHERE e.deleted_at IS NULL ORDER BY f.id LIMIT 10000);
ROLLBACK;
BEGIN;
WITH t AS (SELECT f.entity_id FROM spike_finding f JOIN tap_entity e ON e.id=f.entity_id WHERE e.deleted_at IS NULL ORDER BY f.id LIMIT 10000),
 u1 AS (UPDATE tap_entity SET deleted_at=now(), updated_at=now(), version=version+1 WHERE id IN (SELECT entity_id FROM t) RETURNING 1)
UPDATE spike_finding SET deleted_at=now() WHERE entity_id IN (SELECT entity_id FROM t);
ROLLBACK;
