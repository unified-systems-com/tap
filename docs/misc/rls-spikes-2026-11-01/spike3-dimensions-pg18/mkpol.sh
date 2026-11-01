#!/bin/bash
cfg=$1
arr() { echo "EXISTS (SELECT 1 FROM jsonb_array_elements(current_setting('tap.scope', true)::jsonb) AS s(v) WHERE $1 @> s.v)"; }
slots() { local c=$1; echo "($c @> (current_setting('tap.scope', true)::jsonb -> 0) OR $c @> (current_setting('tap.scope', true)::jsonb -> 1) OR $c @> (current_setting('tap.scope', true)::jsonb -> 2) OR $c @> (current_setting('tap.scope', true)::jsonb -> 3))"; }
cat <<SQL
DO \$\$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY['tap_entity','spike_finding'] LOOP
 EXECUTE format('DROP POLICY IF EXISTS pol ON %I', t); EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', t); END LOOP; END \$\$;
SQL
[ "$cfg" = V0 ] && exit 0
case $cfg in
 L_arr)        ent="$(arr dimensions)"; typ="EXISTS (SELECT 1 FROM tap_entity e WHERE e.id = spike_finding.entity_id AND $(arr e.dimensions))";;
 C_gin_arr)    ent="$(arr dimensions)"; typ="$(arr dims_gin)";;
 C_gin_slots)  ent="$(slots dimensions)"; typ="$(slots dims_gin)";;
 C_gpo_arr)    ent="$(arr dimensions)"; typ="$(arr dims_gpo)";;
 C_gpo_slots)  ent="$(slots dimensions)"; typ="$(slots dims_gpo)";;
 C_none_slots) ent="$(slots dimensions)"; typ="$(slots dims_none)";;
esac
cat <<SQL
ALTER TABLE tap_entity ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol ON tap_entity FOR SELECT TO spike_search USING ($ent);
ALTER TABLE spike_finding ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol ON spike_finding FOR SELECT TO spike_search USING ($typ);
SQL
