-- name|sql
a|SELECT count(*) FROM spike_finding WHERE status='open'
b|SELECT count(*) FROM spike_finding f JOIN tap_entity e ON e.id=f.entity_id WHERE f.status='open' AND e.deleted_at IS NULL
c|SELECT * FROM spike_finding WHERE entity_id=(SELECT entity_id FROM spike_finding OFFSET 123456 LIMIT 1)
d|SELECT from_entity_id FROM tap_edge WHERE edge_type='X'
e|SELECT count(*) FROM tap_edge x JOIN tap_entity t ON t.id=x.to_entity_id WHERE x.edge_type='AFFECTS'
f|SELECT status, severity, count(*), avg(score), max(length(title)) FROM spike_finding GROUP BY 1,2
