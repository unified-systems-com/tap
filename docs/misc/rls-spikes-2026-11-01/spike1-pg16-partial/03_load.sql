\timing on
CREATE TEMP TABLE n AS SELECT g AS rn, gen_random_uuid() AS id, (random()<0.03) AS dead FROM generate_series(1,1000000) g;
CREATE INDEX ON n(rn);
INSERT INTO tap_entity(id,entity_type,name,dimensions,originating_grid_id,deleted_at,created_at,updated_at)
 SELECT id,'spike_finding','f'||rn, jsonb_build_object('tap.graph','g'||(rn%50)), '00000000-0000-0000-0000-000000000001',
   CASE WHEN dead THEN now()-(random()*interval '30 days') END, now()-(random()*interval '90 days'), now() FROM n;
INSERT INTO spike_finding(entity_id,status,severity,title,score)
 SELECT id, (ARRAY['open','open','closed','triaged','suppressed'])[1+(rn%5)], rn%5, 'finding '||rn||' '||repeat('x',20+rn%40), random()*10 FROM n;
CREATE TEMP TABLE e AS SELECT g, gen_random_uuid() AS eid, 1+floor(random()*1000000)::int AS a, 1+floor(random()*1000000)::int AS b,
   (ARRAY['AFFECTS','OWNS','DEPENDS_ON','HAS_FINDING','X'])[1+(g%5)] AS t FROM generate_series(1,2000000) g;
CREATE TEMP TABLE e2 AS SELECT e.*, na.id AS fid, nb.id AS tid, (na.dead OR nb.dead) AS dead FROM e JOIN n na ON na.rn=e.a JOIN n nb ON nb.rn=e.b;
INSERT INTO tap_entity(id,entity_type,name,dimensions,originating_grid_id,deleted_at,created_at,updated_at)
 SELECT eid,'edge','', '{"tap.graph":"g"}', '00000000-0000-0000-0000-000000000001',
   CASE WHEN dead THEN now()-(random()*interval '30 days') END, now()-(random()*interval '90 days'), now() FROM e2;
INSERT INTO tap_edge(entity_id,from_entity_id,to_entity_id,edge_type) SELECT eid,fid,tid,t FROM e2;
CREATE INDEX tap_entity_entity_type_idx ON tap_entity(entity_type);
CREATE INDEX tap_entity_grid_idx ON tap_entity(originating_grid_id);
CREATE INDEX tap_entity_deleted_at_idx ON tap_entity(deleted_at);
CREATE INDEX idx_entity_dimensions_gin ON tap_entity USING gin(dimensions);
CREATE INDEX tap_edge_edge_type_idx ON tap_edge(edge_type);
CREATE INDEX idx_edge_from_type ON tap_edge(from_entity_id, edge_type);
CREATE INDEX idx_edge_to_type ON tap_edge(to_entity_id, edge_type);
CREATE INDEX tap_edge_from_idx ON tap_edge(from_entity_id);
CREATE INDEX tap_edge_to_idx ON tap_edge(to_entity_id);
GRANT SELECT ON tap_entity, spike_finding, tap_edge TO spike_search, spike_bypass;
SET max_parallel_maintenance_workers=0; VACUUM ANALYZE tap_entity; VACUUM ANALYZE spike_finding; VACUUM ANALYZE tap_edge;
SELECT count(*) total, count(deleted_at) dead FROM tap_entity;
SELECT count(*) edges, count(*) FILTER (WHERE ee.deleted_at IS NULL AND (f.deleted_at IS NOT NULL OR t.deleted_at IS NOT NULL)) live_touching_dead FROM tap_edge x JOIN tap_entity ee ON ee.id=x.entity_id JOIN tap_entity f ON f.id=x.from_entity_id JOIN tap_entity t ON t.id=x.to_entity_id;
SELECT pg_size_pretty(pg_total_relation_size('tap_entity')) ent, pg_size_pretty(pg_total_relation_size('spike_finding')) f, pg_size_pretty(pg_total_relation_size('tap_edge')) ed;
