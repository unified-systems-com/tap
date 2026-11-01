CREATE TABLE tap_entity(
 id uuid PRIMARY KEY, entity_type varchar(255) NOT NULL, name varchar(255) NOT NULL DEFAULT '',
 dimensions jsonb NOT NULL DEFAULT '{}', originating_grid_id uuid, version integer NOT NULL DEFAULT 1,
 deleted_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE spike_finding(
 id bigserial PRIMARY KEY, entity_id uuid NOT NULL UNIQUE REFERENCES tap_entity(id) DEFERRABLE INITIALLY DEFERRED,
 status text NOT NULL, severity int NOT NULL, title text NOT NULL, score double precision NOT NULL,
 dims_none jsonb NOT NULL DEFAULT '{}', dims_gin jsonb NOT NULL DEFAULT '{}', dims_gpo jsonb NOT NULL DEFAULT '{}');
