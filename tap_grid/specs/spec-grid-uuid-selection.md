# UUID Selection

## Philosophy

UUIDs are TAP's universal identity primitive. `entity_id`, edge `entity_id`, `batch_id`, and any plugin-internal UUID-bearing key all share one expectation: they are produced by a documented scheme that is appropriate to the *origin of the identity*, and never hand-shaped to look pretty.

Different identities have different origins. An entity created by a user click in TAP has identity that begins inside TAP — its UUID should be time-rooted, statistically unique, and trivially mintable. An entity that mirrors an external authoritative source (a FedRAMP KSI control, an AWS resource discovered via API, a row in an upstream catalog) has identity that lives outside TAP — its UUID must be *reproducible*, so that re-running ingestion in any grid produces the same UUID for the same upstream entity.

This spec defines the menu of allowed UUID schemes, the criteria for choosing one, and what is forbidden. It supersedes `req-grift-seed-ids` in `spec-grift-v0.md` (which only described one specific authoring convention, now deprecated) and parents `spec-grift-seed-ids-real-uuid7.md` (the one-shot migration that brings hand-authored seed data into compliance with this menu).

## Goals

|     |                |                                                                                                       |
| :-: | ---            | ---                                                                                                   |
| 1.  | Documented     | Every UUID-producing code path in TAP names the scheme it uses and the rationale for that choice      |
| 2.  | Origin-Driven  | Scheme choice follows from where the identity comes from, not from author convenience                 |
| 3.  | Reproducible Where Required | Mirrored external data has a stable, repeatable identity contract that survives reinstalls and cross-grid ingestion |
| 4.  | No Hand-Shaping | No code path or authoring convention produces UUIDs by curating bits that the chosen scheme says should be random |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-uuid-menu | [Allowed Schemes](#allowed-schemes) | Proposed | The menu: v7, v5, v4 with constrained applicability |
| req-grid-uuid-v7-runtime | [v7 for Runtime Mints](#v7-for-runtime-mints) | Proposed | Code paths that mint UUIDs at runtime use organic `uuid.uuid7()` |
| req-grid-uuid-v7-seed | [v7 for Hand-Authored Seed Data](#v7-for-hand-authored-seed-data) | Proposed | Static seed UUIDs in grift files are organic `uuid.uuid7()` values minted at author time |
| req-grid-uuid-v5-mirror | [v5 for Mirrored External Identity](#v5-for-mirrored-external-identity) | Proposed | UUIDs derived from an external authoritative source use `uuid.uuid5(namespace, key)` |
| req-grid-uuid-v5-namespace-contract | [v5 Namespace Contract](#v5-namespace-contract) | Proposed | v5 namespaces are per-plugin, organic v7, frozen, documented |
| req-grid-uuid-v4-test-fixtures | [v4 for Test Fixtures](#v4-for-test-fixtures) | Proposed | `uuid.uuid4()` is allowed only for transient test data, never for persisted production identity |
| req-grid-uuid-no-handshaping | [No Hand-Shaped UUIDs](#no-hand-shaped-uuids) | Proposed | UUIDs whose "random" bits are author-curated are forbidden, regardless of version nibble |

## Allowed Schemes
----
RID: `req-grid-uuid-menu`

Status: `Proposed`

TAP recognizes three UUID schemes. Every UUID produced by code or checked into the repository MUST conform to one of them.

| Scheme | Use it when                                                                                                                            | Why                                                            |
| ---    | ---                                                                                                                                    | ---                                                            |
| **v7** | Identity originates inside TAP — runtime mint, hand-authored seed, ad-hoc user write, batch_id for an interactive operation.            | Time-rooted, sortable, statistically unique. The default.      |
| **v5** | Identity is a mirror of an external authoritative source where re-running ingestion across grids must produce the same UUID for the same upstream entity. | Deterministic from `(namespace, key)`. Reproducible without coordination. |
| **v4** | Transient test fixtures only. Never for production identity, never persisted to a real grid.                                            | No time, no determinism. Useful only when you genuinely don't care about either. |

UUIDv1, UUIDv6, and any other RFC 9562 version are NOT in the menu for v0. Adding one requires extending this spec.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-uuid-menu-1 | Closed Menu | Proposed | Production code and seed data produce only v7, v5, or (in tests) v4 UUIDs. | |
| req-grid-uuid-menu-2 | Documented Choice | Proposed | Each UUID-producing code path names its scheme in a docstring or in a referenced spec. | Plugin-internal helpers may reference the parent plugin's authoring doc. |

## v7 for Runtime Mints
----
RID: `req-grid-uuid-v7-runtime`

Status: `Proposed`

Code paths that mint UUIDs at runtime — `BaseModel.save()` for new entities, batch service `start_batch()`, edge creation, plugin code that creates new TAP-managed nodes — MUST use organic `uuid.uuid7()` from the Python 3.14 stdlib (or any RFC 9562-conformant generator).

Runtime mints MUST NOT pre-shape any bits of the resulting UUID. The full 74 bits of randomness specified by RFC 9562 (`rand_a` and `rand_b`) must be populated.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-uuid-v7-runtime-1 | Stdlib Generator | Proposed | Runtime UUIDs are produced by `uuid.uuid7()` (or equivalent conformant generator). | |
| req-grid-uuid-v7-runtime-2 | No Pre-Shaping | Proposed | No runtime code path zeroes, masks, or otherwise curates bits of the generated UUID before persisting it. | |

## v7 for Hand-Authored Seed Data
----
RID: `req-grid-uuid-v7-seed`

Status: `Proposed`

Hand-authored UUIDs in grift files (`plugins/*/grift/*.grift.json`) — `entity_id`, `from_entity_id`, `to_entity_id`, and any in-payload UUID reference — MUST be organic `uuid.uuid7()` values minted at author time and pasted into the file. Once minted and committed, the UUID is the canonical identifier for that entity forever; it is not regenerated on import or on reseed.

Authors mint seed UUIDs with:

```
$ python -c "import uuid; print(uuid.uuid7())"
```

For batches, mint as many as needed in advance:

```
$ python -c "import uuid; [print(uuid.uuid7()) for _ in range(10)]"
```

The migration of existing hand-authored seed data into compliance with this requirement is covered by `spec-grift-seed-ids-real-uuid7.md`.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-uuid-v7-seed-1 | Organic Seed UUIDs | Proposed | Every hand-authored UUID in a grift file is an organic `uuid.uuid7()` value with full random `rand_a` and `rand_b`. | |
| req-grid-uuid-v7-seed-2 | Mint at Author Time | Proposed | Authors run a UUIDv7 generator and paste the output. They do not edit the resulting bits. | |

## v5 for Mirrored External Identity
----
RID: `req-grid-uuid-v5-mirror`

Status: `Proposed`

When an entity in TAP mirrors a row in an external authoritative source — the FedRAMP KSI control catalog, an AWS API listing, a SaaS vendor's resource graph, an upstream-maintained reference dataset — and re-running ingestion in any grid (this one, a fresh install, a peer's grid) must produce the same UUID for the same upstream entity, the entity's UUID MUST be derived as `uuid.uuid5(namespace, name)`.

Concretely:

- `namespace`: a per-plugin v7 UUID (see `req-grid-uuid-v5-namespace-contract`).
- `name`: a stable string formed from the upstream identity. Convention: `f"{kind}:{key}"` where `kind` discriminates entity types within the namespace and `key` is the upstream identifier (e.g. `"ksi_indicator:KSI-CNA-01"`).

Edges between v5-derived entities are themselves v5, computed from the same namespace and a `name` that incorporates the endpoint UUIDs and the edge type, so the entire mirrored subgraph is reproducible.

This requirement does not extend to entities that are *informed by* external data but whose identity is TAP-internal (e.g. a Genericom AWS demo VPC — it represents a fictional VPC, not a real one ingested from AWS APIs; its identity is hand-authored under v7).

### Reference Implementation

`plugins/fedramp_20x_ksi/skills/refresh-ksi-catalog/refresh.py` — function `ns_uuid(namespace, kind, key)` is the canonical pattern.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-uuid-v5-mirror-1 | Deterministic Derivation | Proposed | UUIDs for mirrored entities are produced by `uuid.uuid5(namespace, name)` where both arguments are stable. | |
| req-grid-uuid-v5-mirror-2 | Reproducible Across Grids | Proposed | Two TAP installations ingesting the same upstream source with the same plugin version produce identical entity UUIDs. | |
| req-grid-uuid-v5-mirror-3 | Subgraph Reproducibility | Proposed | Edges between v5-derived entities are themselves v5-derived, so the entire mirrored subgraph is reproducible. | |
| req-grid-uuid-v5-mirror-4 | Scope Boundary | Proposed | Entities whose identity is TAP-internal (even if their data is informed by external systems) use v7, not v5. | |

## v5 Namespace Contract
----
RID: `req-grid-uuid-v5-namespace-contract`

Status: `Proposed`

A v5 namespace UUID is part of a plugin's frozen public contract. Bumping it changes every UUID the plugin emits, breaking identity for all downstream consumers.

### Rules for New v5 Namespaces

- Each plugin that uses v5 picks **one** namespace UUID.
- The namespace UUID MUST itself be an organic `uuid.uuid7()` value, minted once and checked in. It MUST NOT be hand-shaped.
- The namespace is stored in a stable, plugin-owned location (convention: `plugins/<plugin>/skills/<skill>/pinned/uuid_namespace.txt`, or the plugin equivalent for non-skill ingestion).
- The plugin documents the `(kind, key)` convention used for the v5 `name` argument. This convention is also frozen.
- Bumping the namespace UUID OR the key convention is a breaking change requiring a one-shot rewrite + reseed (the playbook in `spec-grift-seed-ids-real-uuid7.md` is the reference pattern).

### Grandfathered Namespaces

The FedRAMP KSI catalog namespace at `plugins/fedramp_20x_ksi/skills/refresh-ksi-catalog/pinned/uuid_namespace.txt` is grandfathered. Its current value (`0197fed0-4000-7000-8000-000000000100`) was minted under the now-deprecated synthetic v7 convention. Re-minting it would invalidate every existing KSI entity UUID for no operational benefit (no external system depends on those IDs other than the plugin itself). This namespace is treated as load-bearing and immutable; the spec accepts the synthetic-shaped namespace as a one-time historical exception.

Any *new* v5 namespace authored after this spec is approved MUST be organic v7. The grandfather clause does not extend.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-uuid-v5-namespace-contract-1 | Organic Namespace | Proposed | New v5 namespace UUIDs are organic `uuid.uuid7()` values. | |
| req-grid-uuid-v5-namespace-contract-2 | Frozen Namespace | Proposed | A plugin's v5 namespace UUID, once committed, is treated as immutable. Bumping it is a breaking change. | |
| req-grid-uuid-v5-namespace-contract-3 | Documented Key Convention | Proposed | Each plugin using v5 documents its `(kind, key)` convention in plugin-owned docs. | |
| req-grid-uuid-v5-namespace-contract-4 | KSI Grandfather | Proposed | The existing FedRAMP 20x KSI namespace is exempted from the organic-v7 requirement. | One-time exception; no other grandfather clauses are granted. |

## v4 for Test Fixtures
----
RID: `req-grid-uuid-v4-test-fixtures`

Status: `Proposed`

`uuid.uuid4()` is allowed exclusively for transient test data — fixtures created by factory-bot-style helpers, ephemeral test entities created and discarded inside a single test, mock objects.

v4 MUST NOT be used:

- For any UUID that is persisted to a real grid (production, staging, dev).
- For any UUID that ships in a grift file.
- For any UUID returned from production code paths.

The reason v4 is allowed at all is convenience: test fixtures don't need time-sortability and don't need reproducibility, and mandating v7 there would just be ceremony.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-uuid-v4-test-fixtures-1 | Test-Only | Proposed | `uuid.uuid4()` calls exist only in test files (`test_*.py`, `tests/`, fixture helpers). | |
| req-grid-uuid-v4-test-fixtures-2 | Not Persisted | Proposed | No code path persists a v4 UUID to a real grid. | |

## No Hand-Shaped UUIDs
----
RID: `req-grid-uuid-no-handshaping`

Status: `Proposed`

A UUID is hand-shaped when an author curates bits that the chosen scheme says should be random. The known failure modes:

- **Strict synthetic v7** — `xxxxxxxx-xxxx-7000-8000-xxxxxxxxxxxx` with a counter-shaped tail. Zeroed `rand_a` and zeroed high bits of `rand_b`. The pattern codified by the deprecated `req-grift-seed-ids` in `spec-grift-v0.md`. The pattern that produced the 2026-04-27 genericom collision documented in `spec-grift-seed-ids-real-uuid7.md`.
- **Per-batch shared prefix v7** — `<batch-prefix>-c8...`-style IDs where `rand_a` and the high bits of `rand_b` are shared across every entity in a batch and only the tail varies. The LOTR pattern. Less catastrophic (the random tail prevents collisions) but still author-curated.
- **v5 with hand-shaped namespace** — using v5 correctly with a namespace UUID that is itself hand-shaped. The KSI scheme as currently implemented; grandfathered per `req-grid-uuid-v5-namespace-contract`, forbidden going forward.

All three are forbidden going forward. Existing instances of the first two are migrated to organic v7 by `spec-grift-seed-ids-real-uuid7.md`. The third is addressed by the grandfather clause for the single existing case.

### Future Linting

A future spec MAY add an importer-side advisory that flags newly-introduced hand-shaped UUIDs in any grift bundle whose `started_at` postdates this spec's approval. v0 does not include this lint.

### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-uuid-no-handshaping-1 | No Synthetic v7 | Proposed | No code path or grift file produces UUIDs with the strict synthetic v7 pattern. | Migration covered by `spec-grift-seed-ids-real-uuid7.md`. |
| req-grid-uuid-no-handshaping-2 | No Per-Batch Prefix v7 | Proposed | No code path or grift file produces UUIDs that share `rand_a` and high bits of `rand_b` across multiple entities. | Same migration spec extends to LOTR's pattern. |
| req-grid-uuid-no-handshaping-3 | Organic Namespaces Only | Proposed | New v5 namespace seeds are organic v7. KSI is grandfathered. | |

## Open Questions

- **Cross-plugin v5 namespace registry**: collisions between two plugins' v5 namespaces are statistically impossible if both follow the organic-v7 rule, so a registry is unnecessary. If multiple plugins ever ingest the same upstream source, they could intentionally share a namespace — but that is a coordination decision between plugin authors, not a TAP-wide one. Out of scope for v0.
- **Content-hash IDs**: a future requirement might want UUIDs whose value changes when underlying content changes (true content-hash addressing). v5 doesn't satisfy that — its `name` argument can encode content, but then the "ID" is a hash of content, not a stable identity. This is a different primitive (likely belongs in a separate `spec-grid-content-address` if we ever need it). Explicitly out of scope here.
- **Grid-scoped uniqueness**: combining `entity_id` with `TAP_GRID_ID` for global cross-grid addressing is covered (or will be) by aliases/perspectives backlog specs, not here.

## Non-Goals

- A central registry of v5 namespace UUIDs across plugins.
- Defining new UUID versions beyond RFC 9562's published versions.
- Changing the `entity_id` storage type or any ORM-level UUID handling.
- Retroactively re-minting the grandfathered KSI namespace.
- Validating or linting hand-shaped UUIDs at import time in v0.
