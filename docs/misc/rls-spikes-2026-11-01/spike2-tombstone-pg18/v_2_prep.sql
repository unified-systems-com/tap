ALTER TABLE spike_finding ADD COLUMN deleted_at timestamptz;
ALTER TABLE tap_edge ADD COLUMN deleted_at timestamptz;
UPDATE spike_finding f SET deleted_at=e.deleted_at FROM tap_entity e WHERE e.id=f.entity_id AND e.deleted_at IS NOT NULL;
UPDATE tap_edge f SET deleted_at=e.deleted_at FROM tap_entity e WHERE e.id=f.entity_id AND e.deleted_at IS NOT NULL;
CREATE INDEX spike_finding_live_idx ON spike_finding(status) WHERE deleted_at IS NULL;
CREATE INDEX tap_edge_live_type_idx ON tap_edge(edge_type) WHERE deleted_at IS NULL;
SET max_parallel_maintenance_workers=0; VACUUM ANALYZE spike_finding; VACUUM ANALYZE tap_edge;
