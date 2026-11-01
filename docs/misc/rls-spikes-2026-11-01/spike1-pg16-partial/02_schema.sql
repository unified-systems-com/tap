-- mirrors tap_grid 0001 Entity + Edge model; indexes: pk, entity_type, originating_grid_id, deleted_at (db_index), GIN dimensions
CREATE TABLE tap_entity(
 id uuid PRIMARY KEY, entity_type varchar(255) NOT NULL, name varchar(255) NOT NULL DEFAULT '',
 dimensions jsonb NOT NULL DEFAULT '{}', originating_grid_id uuid, version integer NOT NULL DEFAULT 1,
 deleted_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE spike_finding(
 id bigserial PRIMARY KEY, entity_id uuid NOT NULL UNIQUE REFERENCES tap_entity(id) DEFERRABLE INITIALLY DEFERRED,
 status text NOT NULL, severity int NOT NULL, title text NOT NULL, score double precision NOT NULL);
CREATE TABLE tap_edge(
 id bigserial PRIMARY KEY, entity_id uuid NOT NULL UNIQUE REFERENCES tap_entity(id) DEFERRABLE INITIALLY DEFERRED,
 from_entity_id uuid NOT NULL REFERENCES tap_entity(id) DEFERRABLE INITIALLY DEFERRED,
 to_entity_id uuid NOT NULL REFERENCES tap_entity(id) DEFERRABLE INITIALLY DEFERRED,
 edge_type varchar(255) NOT NULL, properties jsonb NOT NULL DEFAULT '{}');
