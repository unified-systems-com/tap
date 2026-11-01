-- V3b: V1 with uncorrelated IN (hashable subplan) instead of correlated EXISTS
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['tap_entity','spike_finding','tap_edge'] LOOP
 EXECUTE format('DROP POLICY IF EXISTS pol ON %I', t); EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', t); END LOOP; END $$;
ALTER TABLE tap_entity ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol ON tap_entity FOR SELECT TO spike_search USING (deleted_at IS NULL);
ALTER TABLE spike_finding ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol ON spike_finding FOR SELECT TO spike_search USING (entity_id NOT IN (SELECT id FROM tap_entity WHERE deleted_at IS NOT NULL));
ALTER TABLE tap_edge ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol ON tap_edge FOR SELECT TO spike_search USING (entity_id NOT IN (SELECT id FROM tap_entity WHERE deleted_at IS NOT NULL));
