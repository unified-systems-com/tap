SELECT current_user;
\echo -- typed table only, no tap_entity touched: total rows (expect 1000000*0.97 ~ live only)
SELECT count(*) AS finding_rows FROM spike_finding;
\echo -- bare tap_entity
SELECT count(*) AS entity_rows, count(*) FILTER (WHERE deleted_at IS NOT NULL) AS tombstones_seen FROM tap_entity;
\echo -- edges (touches only tap_edge)
SELECT count(*) AS edge_rows FROM tap_edge;
\echo -- reverse/joined: entity -> finding, tombstoned entity ids must not appear
SELECT count(*) FROM tap_entity e JOIN spike_finding f ON f.entity_id=e.id;
\echo -- known tombstoned finding id: direct lookup returns 0 rows?
CREATE TEMP TABLE _x(id uuid); 
