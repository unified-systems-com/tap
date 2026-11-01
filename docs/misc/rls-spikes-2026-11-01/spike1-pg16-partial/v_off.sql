DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['tap_entity','spike_finding','tap_edge'] LOOP
 EXECUTE format('DROP POLICY IF EXISTS pol ON %I', t); EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', t); END LOOP; END $$;
