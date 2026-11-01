\timing on
CREATE TEMP TABLE n AS SELECT g AS rn, gen_random_uuid() AS id,
 (ARRAY['prod','stage','dev','test'])[1+floor(random()*4)::int] AS env,
 'g'||floor(random()*50)::int AS graph, 't'||floor(random()*200)::int AS team,
 CASE WHEN random()<0.2 THEN (ARRAY['vdr','ksi','pain'])[1+floor(random()*3)::int] END AS rule,
 CASE WHEN random()<0.3 THEN 'u'||floor(random()*1000)::int END AS owner
 FROM generate_series(1,:N) g;
INSERT INTO tap_entity(id,entity_type,name,dimensions,originating_grid_id)
 SELECT id,'spike_finding','f'||rn,
  jsonb_strip_nulls(jsonb_build_object('tap.graph',graph,'env',env,'team',team,'fedramp.rule',rule,'owner',owner)),
  '00000000-0000-0000-0000-000000000001' FROM n;
INSERT INTO spike_finding(entity_id,status,severity,title,score,dims_none,dims_gin,dims_gpo)
 SELECT n.id,(ARRAY['open','open','closed','triaged','suppressed'])[1+(n.rn%5)], n.rn%5, 'finding '||n.rn||' '||repeat('x',20+n.rn%40), random()*10,
  e.dimensions, e.dimensions, e.dimensions FROM n JOIN tap_entity e ON e.id=n.id;
CREATE INDEX tap_entity_entity_type_idx ON tap_entity(entity_type);
CREATE INDEX idx_entity_dimensions_gin ON tap_entity USING gin(dimensions);
CREATE INDEX spike_finding_dims_gin ON spike_finding USING gin(dims_gin);
CREATE INDEX spike_finding_dims_gpo ON spike_finding USING gin(dims_gpo jsonb_path_ops);
GRANT SELECT ON tap_entity, spike_finding TO spike_search, spike_bypass;
SET max_parallel_maintenance_workers=0; VACUUM ANALYZE tap_entity; VACUUM ANALYZE spike_finding;
SELECT count(*) FROM tap_entity;
SELECT relname, pg_size_pretty(pg_relation_size(oid)) AS size FROM pg_class WHERE relname IN ('tap_entity','spike_finding','idx_entity_dimensions_gin','spike_finding_dims_gin','spike_finding_dims_gpo') ORDER BY relname;
