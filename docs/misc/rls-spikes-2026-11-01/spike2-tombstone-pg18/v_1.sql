DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['tap_entity','spike_finding','tap_edge'] LOOP
 EXECUTE format('DROP POLICY IF EXISTS pol ON %I', t); EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', t); END LOOP; END $$;
ALTER TABLE tap_entity ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol ON tap_entity FOR SELECT TO spike_search USING (deleted_at IS NULL);
ALTER TABLE spike_finding ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol ON spike_finding FOR SELECT TO spike_search USING (EXISTS (SELECT 1 FROM tap_entity e WHERE e.id = spike_finding.entity_id AND e.deleted_at IS NULL));
ALTER TABLE tap_edge ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol ON tap_edge FOR SELECT TO spike_search USING (EXISTS (SELECT 1 FROM tap_entity e WHERE e.id = tap_edge.entity_id AND e.deleted_at IS NULL));
