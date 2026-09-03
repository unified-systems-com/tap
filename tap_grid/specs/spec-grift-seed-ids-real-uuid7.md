# GRIFT Seed Data IDs — Real UUIDv7

## Philosophy

`entity_id` is TAP's canonical cross-grid, cross-instance, cross-plugin identifier. The point of UUIDv7 is universal uniqueness — every reference, every join, every export/re-import keys on `entity_id`, and nothing else. That contract only holds if the IDs are actually random.

This spec is the one-shot migration that brings hand-authored seed UUIDs into compliance with `spec-grid-uuid-selection.md` (the parent spec defining the allowed UUID schemes). Two hand-shaped patterns currently exist in tree:

1. **Strict synthetic v7** — codified by `req-grift-seed-ids` in `spec-grift-v0.md` (now Deprecated). Plugins pick a single 48-bit timestamp prefix, zero out `rand_a` and the high bits of `rand_b`, and hand-curate the remaining 48 bits as a counter — often broken into category sub-ranges like `…-0003xxxxxxxx` for "network objects, record N". This is not a UUIDv7; it is a UUIDv7-shaped string with the universally-unique part removed. 499 IDs in tree.
2. **Per-batch shared prefix v7** — `xxxxxxxx-xxxx-7XXX-XXXX-X8...`-style IDs where `rand_a` and the high bits of `rand_b` are shared across every entity in a batch and only the tail varies. The pattern in `plugins/lotr/grift/*.grift.json`. Less catastrophic (random tails prevent collisions) but still author-curated and forbidden by `req-grid-uuid-no-handshaping`. 136 IDs across 5 batches in tree.

This spec retires both. All affected seed `entity_id` values are rewritten to organic `uuid.uuid7()` in a single pass; the synthetic-v7 prose in `spec-grift-v0.md` is removed; the dev database is dropped and reseeded.

The FedRAMP 20x KSI namespace (`plugins/fedramp_20x_ksi/skills/refresh-ksi-catalog/pinned/uuid_namespace.txt`) is grandfathered per `req-grid-uuid-v5-namespace-contract` and is NOT touched by this migration. Its descendants (the v5-derived KSI entity UUIDs in `ksi-initial-2026-04-23.grift.json`) are also untouched.

## Goals

|     |               |                                                                  |
| :-: | ---           | ---                                                              |
| 1.  | Universally Unique | Seed `entity_id` values carry the full 74 bits of randomness specified by RFC 9562; collisions across plugins, batches, and grids are statistically impossible |
| 2.  | Standard       | Seed IDs are indistinguishable from runtime-generated IDs; no separate validator path or authoring convention |
| 3.  | Cheap          | Authors run `python -c "import uuid; print(uuid.uuid7())"` once per new entity; no curated counters or per-plugin timestamp prefixes |
| 4.  | Complete       | No hand-curated UUIDs remain in tree after the rewrite |

## Motivating Incident

On 2026-04-27, an in-progress migration of `plugins/genericom/grift/pages.grift.json` to the v1 elevation-entity-chain shape minted two new entities at:

- `01965b01-4000-7000-8000-000300000001`
- `01965b01-4000-7000-8000-000300000002`

These IDs already existed in the same plugin's `network.grift.json` bundle — claimed by `aws_vpc` "genericom-prod-vpc" and `aws_internet_gateway` "genericom-prod-igw". The author was reaching for "the next low slot in a fresh `0003`-prefixed sub-range" and hit a sub-range that the network bundle had already partially filled. Re-import surfaced the collision as a `preflight entity_type_mismatch` error; the page rendered a `Panel Error` because the projection could not be re-imported and was stuck in the v0 inline shape.

Two synthetic IDs colliding inside a single plugin proves the convention's failure mode: humans pick low numbers. A 48-bit random tail does not.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grift-seed-ids-real | [Real UUIDv7 for All Seed IDs](#real-uuidv7-for-all-seed-ids) | Proposed | All hand-authored seed `entity_id` values use organic `uuid.uuid7()` |
| req-grift-seed-ids-rewrite | [One-Shot Rewrite + Reseed](#one-shot-rewrite--reseed) | Proposed | All in-tree synthetic IDs are rewritten to organic UUIDv7s in a single pass; dev databases are dropped and reimported |
| req-grift-seed-ids-deprecate-synthetic | [Remove Synthetic Convention](#remove-synthetic-convention) | Proposed | `req-grift-seed-ids` in `spec-grift-v0.md` becomes `Deprecated`; the authoring convention is removed from prose |

## Real UUIDv7 for All Seed IDs
----
RID: `req-grift-seed-ids-real`

Status: `Proposed`

All hand-authored seed `entity_id` values in plugin GRIFT files MUST be valid RFC 9562 UUIDv7 values produced by `uuid.uuid7()` (Python 3.14 stdlib) or any conforming UUIDv7 generator. The full 74 bits of randomness specified by RFC 9562 must be populated; authors MUST NOT zero out `rand_a` or the high bits of `rand_b`.

`entity_id` is the canonical, universal, cross-everything identifier. It is the only key by which entities are referenced across grifts, plugins, grids, and instances. Hand-curating any of its bits breaks that contract.

### Authoring Workflow

```
$ python -c "import uuid; print(uuid.uuid7())"
01963fa1-9c7d-7a4b-8e91-3d2f8c1b0a47
```

Paste the output into the grift JSON. The ID is now permanent for that entity.

For batches creating multiple entities, mint as many IDs as needed in advance:

```
$ python -c "import uuid; [print(uuid.uuid7()) for _ in range(10)]"
```

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grift-seed-ids-real-1 | Organic UUIDv7 | Proposed | Seed `entity_id` values are produced by an RFC 9562-conformant generator with full random `rand_a` and `rand_b`. | |
| req-grift-seed-ids-real-2 | No Hand-Curated Bits | Proposed | Authors do not hand-edit `rand_a`, `rand_b`, or the timestamp bits of seed IDs. | |
| req-grift-seed-ids-real-3 | Tooling | Proposed | The recommended `python -c "import uuid; print(uuid.uuid7())"` snippet is documented in plugin authoring docs. | Doc lives under `docs/`; ties into the docs-spec drift convention. |

## One-Shot Rewrite + Reseed
----
RID: `req-grift-seed-ids-rewrite`

Status: `Proposed`

Every synthetic `entity_id` currently in tree is rewritten to a freshly minted organic UUIDv7 in a single pass. The rewrite is a one-time migration; after it lands there is no remaining hand-curated UUID anywhere in the repository.

### Implementation

A one-shot script (`scripts/rewrite_synthetic_uuids.py`) executes the rewrite:

1. Walk every `plugins/*/grift/*.grift.json` file and collect every UUID matching one of the two hand-shaped patterns:
   - **Strict synthetic v7** — `xxxxxxxx-xxxx-7000-8000-xxxxxxxxxxxx` (zeroed `rand_a`, zeroed high bits of `rand_b`).
   - **Per-batch shared prefix v7** — UUIDs whose `(timestamp, rand_a, high-bits-of-rand_b)` prefix is shared by ≥2 entities in the same batch. Detected by grouping every v7-shaped UUID in a file by its first 18 hex characters and flagging any group of size ≥2.
   The KSI namespace UUID and any v5-derived UUID (version nibble `5`) are excluded from detection. Build a single global `old_uuid → new_uuid` map by minting one `uuid.uuid7()` per distinct old UUID.
2. Apply the map to every grift file: `entity_id`, `from_entity_id`, `to_entity_id`, and any in-payload references (`default_elevation_id`, `layouts: [...]`, `search_id`, `target_elevation_id`, etc.). The map is global, so cross-file edge references stay intact.
3. Audit non-grift references with ripgrep (e.g. `rg '01965b[01][01]-4000-7000-8000-' -g '!*.grift.json'`) for every plugin prefix and rewrite or remove any hits. Spots that historically reference synthetic IDs: `tap_plugins/`, `plugins/*/static/`, `plugins/*/templates/`, tests, and spec example IDs.
4. Emit a sidecar `scripts/uuid-rewrite-map.json` capturing the full `old_uuid → new_uuid` map for one PR cycle's traceability. The sidecar is deleted in a follow-up commit once the rewrite PR has merged.
5. Drop the dev database (`docker compose down -v`), migrate, and run `import_plugin_grift --all`. Smoke-test the genericom landing page (the badges/info-window variants), the EC2 internal projection, and the LOTR saga projection.

The rewrite script is one-shot and is itself removed once the migration is complete; it does not become permanent tooling.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grift-seed-ids-rewrite-1 | Global Map | Proposed | All synthetic IDs across all grift files are rewritten using a single global `old → new` map so cross-file edge references survive. | |
| req-grift-seed-ids-rewrite-2 | Non-Grift Audit | Proposed | Non-grift code paths (Python, JS, templates, tests) that reference synthetic IDs are rewritten or removed in the same PR. | |
| req-grift-seed-ids-rewrite-3 | Reseed Verified | Proposed | Dev DB is dropped + reimported and the genericom badges, EC2 internal, and LOTR saga pages render without panel errors. | |
| req-grift-seed-ids-rewrite-4 | No Synthetic Residue | Proposed | After the rewrite, `rg` finds zero UUIDs matching the synthetic pattern in tree. | |

## Remove Synthetic Convention
----
RID: `req-grift-seed-ids-deprecate-synthetic`

Status: `Proposed`

`req-grift-seed-ids` in `spec-grift-v0.md` is moved from `Proposed` to `Deprecated` in the same PR as the rewrite. The body prose for that requirement is reduced to a one-paragraph historical note pointing readers here; the structural-template, ACIDs, and "Future" section are removed. The requirements table at the top of `spec-grift-v0.md` is updated accordingly.

The doc-spec drift convention (`req-docs-drift-conventions`) applies — any docs that reference the synthetic convention are updated in the same PR.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grift-seed-ids-deprecate-synthetic-1 | Spec Updated | Proposed | `req-grift-seed-ids` in `spec-grift-v0.md` is `Deprecated` with a link to this spec; requirements table and body match. | |
| req-grift-seed-ids-deprecate-synthetic-2 | Docs Updated | Proposed | Any `docs/` references to the synthetic convention are updated in the same PR. | Find via `grep -r req-grift-seed-ids docs/`. |

## Open Questions

- **Idempotency anchor**: today the importer keys idempotency on `entity_id`. After the rewrite, every existing grift entity gets a new ID; that's correct (the old IDs were never canonical, just hand-jammed placeholders) but worth noting in the PR description so reviewers don't read the diff as identity churn.

## Non-Goals

- Changing the GRIFT envelope shape — `entity_id` remains a UUID string at the JSON level.
- Adding any new import-time validation that blocks the import. The synthetic-shape detector lives only inside the one-shot rewrite script.
- Defining a central registry of plugin timestamp prefixes (irrelevant once IDs are organic).
- Preserving any synthetic IDs anywhere in the repository.
