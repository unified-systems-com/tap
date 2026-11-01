\echo == truth (owner/bypass sees all): dead typed rows, dead edges
SELECT (SELECT count(*) FROM spike_finding f JOIN tap_entity e ON e.id=f.entity_id WHERE e.deleted_at IS NOT NULL) dead_findings,
       (SELECT count(*) FROM tap_edge x JOIN tap_entity e ON e.id=x.entity_id WHERE e.deleted_at IS NOT NULL) dead_edges,
       (SELECT count(*) FROM tap_entity WHERE deleted_at IS NOT NULL) dead_entities, current_user;
