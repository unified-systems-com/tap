-- V3c: dead-set via owner-run view (bypasses RLS), policy = NOT IN (hashed SubPlan over ~147k tombstoned ids)
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['tap_entity','spike_finding','tap_edge'] LOOP
 EXECUTE format('DROP POLICY IF EXISTS pol ON %I', t); EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', t); END LOOP; END $$;
CREATE OR REPLACE VIEW spike_dead AS SELECT id FROM tap_entity WHERE deleted_at IS NOT NULL;
GRANT SELECT ON spike_dead TO spike_search;
ALTER TABLE tap_entity ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol ON tap_entity FOR SELECT TO spike_search USING (deleted_at IS NULL);
ALTER TABLE spike_finding ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol ON spike_finding FOR SELECT TO spike_search USING (entity_id NOT IN (SELECT id FROM spike_dead));
ALTER TABLE tap_edge ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol ON tap_edge FOR SELECT TO spike_search USING (entity_id NOT IN (SELECT id FROM spike_dead));
