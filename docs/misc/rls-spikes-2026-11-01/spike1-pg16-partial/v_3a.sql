-- V3a: V1 with STABLE SQL function wrapper
DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['tap_entity','spike_finding','tap_edge'] LOOP
 EXECUTE format('DROP POLICY IF EXISTS pol ON %I', t); EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', t); END LOOP; END $$;
CREATE OR REPLACE FUNCTION spike_live(u uuid) RETURNS boolean LANGUAGE sql STABLE AS $$ SELECT EXISTS (SELECT 1 FROM tap_entity e WHERE e.id=u AND e.deleted_at IS NULL) $$;
ALTER TABLE tap_entity ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol ON tap_entity FOR SELECT TO spike_search USING (deleted_at IS NULL);
ALTER TABLE spike_finding ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol ON spike_finding FOR SELECT TO spike_search USING (spike_live(entity_id));
ALTER TABLE tap_edge ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol ON tap_edge FOR SELECT TO spike_search USING (spike_live(entity_id));
GRANT EXECUTE ON FUNCTION spike_live(uuid) TO spike_search;
