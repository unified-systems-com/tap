\timing on
-- 10,000 rows change one dimension value. Entity only, then entity + each copy variant. Each rolled back.
\echo === entity only
BEGIN; UPDATE tap_entity SET dimensions = dimensions || '{"env":"dev"}', version=version+1, updated_at=now() WHERE id IN (SELECT entity_id FROM spike_finding ORDER BY id LIMIT 10000); ROLLBACK;
\echo === entity + dims_none (copy, no index)
BEGIN; WITH t AS (SELECT entity_id FROM spike_finding ORDER BY id LIMIT 10000), u AS (UPDATE tap_entity SET dimensions = dimensions || '{"env":"dev"}', version=version+1, updated_at=now() WHERE id IN (SELECT entity_id FROM t) RETURNING 1) UPDATE spike_finding SET dims_none = dims_none || '{"env":"dev"}' WHERE entity_id IN (SELECT entity_id FROM t); ROLLBACK;
\echo === entity + dims_gin (copy, GIN jsonb_ops)
BEGIN; WITH t AS (SELECT entity_id FROM spike_finding ORDER BY id LIMIT 10000), u AS (UPDATE tap_entity SET dimensions = dimensions || '{"env":"dev"}', version=version+1, updated_at=now() WHERE id IN (SELECT entity_id FROM t) RETURNING 1) UPDATE spike_finding SET dims_gin = dims_gin || '{"env":"dev"}' WHERE entity_id IN (SELECT entity_id FROM t); ROLLBACK;
\echo === entity + dims_gpo (copy, GIN jsonb_path_ops)
BEGIN; WITH t AS (SELECT entity_id FROM spike_finding ORDER BY id LIMIT 10000), u AS (UPDATE tap_entity SET dimensions = dimensions || '{"env":"dev"}', version=version+1, updated_at=now() WHERE id IN (SELECT entity_id FROM t) RETURNING 1) UPDATE spike_finding SET dims_gpo = dims_gpo || '{"env":"dev"}' WHERE entity_id IN (SELECT entity_id FROM t); ROLLBACK;
