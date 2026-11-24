-- Toy grid for the Issue 1348 prototype. Mirrors the shapes that matter, not TAP's full schema:
--   ent   : the spine (tap_entity): id, type, composed natural key, deleted_at, observation pointer.
--   det   : a typed table keyed on two columns (qid, host_id), with the wave3 spine copy
--           spine_deleted_at, and the proposed partial unique index over live rows.
--   route : a typed table keyed on a JSON path (location.route): an expression partial unique index.
--   edge  : tap_edge, with a stored identity digest (sha256 of the canonical edge identity) and a
--           partial unique index over live rows; plus one per-type expression index to show that
--           shape also works as an ON CONFLICT arbiter.
--   idlock: option B, a mutex-row table replacing advisory locks with row locks.
DROP TABLE IF EXISTS edge, det, route, ent, idlock CASCADE;

CREATE TABLE ent (
    id uuid PRIMARY KEY,
    entity_type text NOT NULL,
    natural_key text,
    deleted_at timestamptz,
    last_observed_batch uuid,
    version int NOT NULL DEFAULT 1
);

CREATE TABLE det (
    entity_id uuid PRIMARY KEY REFERENCES ent(id) DEFERRABLE INITIALLY DEFERRED,
    qid int NOT NULL,
    host_id text NOT NULL,
    payload text,
    spine_deleted_at timestamptz
);
-- What a regenerated plugin migration would carry (UniqueConstraint(fields=..., condition=Q(spine_deleted_at=None))).
CREATE UNIQUE INDEX det_nk_live ON det (qid, host_id) WHERE spine_deleted_at IS NULL;

CREATE TABLE route (
    entity_id uuid PRIMARY KEY REFERENCES ent(id) DEFERRABLE INITIALLY DEFERRED,
    location jsonb NOT NULL,
    spine_deleted_at timestamptz
);
-- UniqueConstraint(KeyTransform("route", "location"), condition=Q(spine_deleted_at=None)).
CREATE UNIQUE INDEX route_nk_live ON route ((location -> 'route')) WHERE spine_deleted_at IS NULL;

CREATE TABLE edge (
    entity_id uuid PRIMARY KEY REFERENCES ent(id) DEFERRABLE INITIALLY DEFERRED,
    edge_type text NOT NULL,
    from_id uuid NOT NULL REFERENCES ent(id) DEFERRABLE INITIALLY DEFERRED,
    to_id uuid NOT NULL REFERENCES ent(id) DEFERRABLE INITIALLY DEFERRED,
    properties jsonb NOT NULL DEFAULT '{}',
    identity_digest bytea,
    spine_deleted_at timestamptz
);
CREATE UNIQUE INDEX edge_identity_live ON edge (identity_digest)
    WHERE spine_deleted_at IS NULL AND identity_digest IS NOT NULL;
-- The per-type alternative: one partial expression index per discriminated edge type.
CREATE UNIQUE INDEX edge_scoped_live ON edge (from_id, to_id, (properties -> 'scope'))
    WHERE edge_type = 'scoped' AND spine_deleted_at IS NULL;
CREATE INDEX edge_from_type ON edge (from_id, edge_type);

CREATE TABLE idlock (digest bytea PRIMARY KEY);
