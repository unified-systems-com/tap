---
name: add-edge
description: Add a new TAP edge type to a plugin. Use when introducing a new relationship between entity types (e.g. HAS_EVIDENCE from finding to evidence).
allowed-tools: Read Write Edit Bash(scripts/dc *) Bash(grep *) Bash(find *) Bash(ls *) Glob Grep
argument-hint: <plugin_slug> <EDGE_SLUG>
---

# Add a New Edge Type

You are introducing a new edge type that connects two entity types in the TAP graph. The edge becomes a first-class type that GRIFT can seed, the service layer can create/replace/delete, and queries (gryphon, hotlink) can traverse.

## Authoritative Sources (read these first; do not guess from memory)

- **[`tap_grid/specs/spec-grid-edge.md`](../../specs/spec-grid-edge.md)** — Edge model, type system, source/target enforcement, dimensions on edges.
- **[`tap_grid/schemas/edge-definition.schema.json`](../../schemas/edge-definition.schema.json)** — JSON Schema for `.edge.json` files. Validate against this.
- **[`tap_plugins/specs/spec-tap-plugin-manifest-v0.md`](../../../tap_plugins/specs/spec-tap-plugin-manifest-v0.md)** — manifest registration of edge types.
- **[`tap_grid/specs/spec-grid-hotlink.md`](../../specs/spec-grid-hotlink.md)** — read this if the edge is the materialization of a JSON reference inside a hotlink-bearing field.
- **[`tap_grid/specs/spec-grid-service-write.md`](../../specs/spec-grid-service-write.md)** — `create_edge` / `replace_edge` semantics, idempotency, dimension defaults.

If a spec contradicts a pattern in code, flag it to the user — do not silently work around it.

## Step 1: Confirm the Shape With the User

Before authoring the edge file, gather:

1. **Plugin slug** the edge belongs to (e.g. `fedramp_20x_ksi`).
2. **Edge slug** (`SCREAMING_SNAKE_CASE`, e.g. `HAS_EVIDENCE`). The slug is the canonical edge type — used in service-layer calls, GRIFT, and gryphon queries. Edge slugs should be compact semantic predicates that help `source node + edge + target node` read like a coherent sentence.
3. **Human-readable name** and **description** (one or two sentences explaining what the edge represents and when to use it).
4. **`sources` and `targets`** — list the entity-type slugs allowed at each end. Wildcard (`omit`) is permitted but should be justified; explicit lists are strongly preferred for typed plugins.
5. **`property_schema`** — MANDATORY if the edge will ever carry properties; omit only for property-free edges (req-grid-edge-schema-required: properties are optional, carrying them is not — writing non-empty properties to a schema-less edge type warns today and fails closed from core 0.2.0). Use it whenever the edge carries semantically meaningful data (e.g. an enum that classifies the relationship — a `support_kind` enum is a textbook example). EXCEPTION: never declare the `hotlink` key — it is system-owned, validated centrally by the hotlink machinery, and the registry rejects schemas that redeclare it (req-grid-edge-schema-required-5). A hotlink-only edge type needs no schema at all.
6. **`default_dimensions`** — what dimensions does every new edge of this type carry? Edges should match the dimension convention of their participating entities. Dimension-less edges, like dimension-less nodes, are a design red flag.
7. **Hotlink integration** — is this edge the materialization of a JSON reference on a model? If yes, plan the `HOTLINKS` declaration on the model alongside the edge.

Write down the agreed shape before generating the file; it becomes the spec section in Step 5.

### Edge naming checklist

Edge slugs follow one form: **`<ACTION>_<OBJECT>`** — a mechanical verb plus the noun it acts on. The edge **points in the direction of action initiation** (the initiator is the `source`), independent of which way data flows.

- **Mechanical, not philosophical.** Name what physically happens, not a role or interpretation. Prefer `RETRIEVES_CERT_FROM` over `PROTECTS`, `RETRIEVES_CONTENT_FROM` over `BACKED_BY`. "Protects", "backed by", "depends on" describe a philosophical relationship, not a mechanism.
- **Keep the object noun.** A bare verb with an obvious missing object is wrong: `ROUTES_TRAFFIC` not `ROUTES`, `WRITES_LOGS` not `WRITES`, `PULLS_IMAGE` not `PULLS`, `ASSUMES_ROLE` not `ASSUMES`.
- **`_TO` is never used.** Forward — action direction matches data direction, or there is no data — is the unmarked default. `ROUTES_TRAFFIC`, never `ROUTES_TRAFFIC_TO`.
- **`_FROM` is reserved.** Append `_FROM` **iff** the edge carries data *and* that data flows opposite the action/edge direction (a "data-backwards" edge). Example: `aws_cloudfront_distribution RETRIEVES_CONTENT_FROM aws_s3_bucket` — CloudFront initiates the pull (edge points CloudFront→S3) but content flows S3→CloudFront. Non-data edges (auth, containment, association) **never** take `_FROM`: `ASSUMES_ROLE`, `PARTITIONED_INTO_SUBNET` stay bare. This keeps data-reversal visible everywhere the slug appears (queries, GRIFT, logs, rendered graph) with no hidden edge field.
- **Don't repeat endpoint type names — but don't collapse distinct relationships into one bare verb either.** If the endpoints already supply the nouns, keep the slug compact (`PARTITIONED_INTO_SUBNET`, not `VPC_PARTITIONED_INTO_SUBNET`) — don't turn a slug into a paragraph. The failure mode to avoid is the opposite one: a bare generic verb is acceptable *only* when the edge is one specific relationship over a coherent endpoint set. See "One edge, one relationship" next.
- **One edge, one relationship.** An edge type represents a single relationship over a coherent set of endpoint pairs. A verb standing in for *several distinct relationships* across many concrete type pairs is the real defect — the same sin as a philosophical name, because it hides what actually connects to what. A `CONTAINS` covering region→AZ *and* VPC→subnet *and* cluster→service, or a `RESIDES_IN` spanning 15 source types → 4 targets, is not one edge; split it into specific per-relationship edges (`DIVIDED_INTO_AZ`, `PARTITIONED_INTO_SUBNET`, `RUNS_TASK`). Generalized "X is inside Y" across many pairs is **not an edge at all** — it is a transitive, derived **reified-path** concept (`docs/misc/grid-native-paths-notes.md`): assert the specific local edges and let paths compute the general case. Do not introduce a generic containment/`CONTAINS` edge.
- **Locative/relational prepositions are not flow markers** and are out of scope of the `_TO` rule. `BELONGS_TO_ACCOUNT`, `RESIDES_IN`, `HAS_POLICY_ACCESS_TO`, `BOUND_TO_AZ` keep their inherent preposition — that `_TO`/`_IN` is part of a membership/locative predicate, not a redundant direction marker.

`_FROM` collision footnote: `_FROM` is reserved for data-reversal on mechanical resource edges. If a future edge legitimately wants a *relational* `_FROM` (e.g. `INHERITS_FROM`) that is not data-backwards, the incumbent data-reversal meaning wins by weight of existing edges — the new edge picks a synonym. Flag it and reassess the convention if it recurs; do not silently overload `_FROM`.

### Property schema design checklist

When the edge carries an enum (e.g. `support_kind: passing | violation | informational`), confirm with the user:

- **Required vs. optional?** If the edge has no useful default, list it under `required`.
- **`additionalProperties: false`?** Default to true (yes, forbid extras). New properties should be explicit additions, not silent expansions.
- **Vocabulary alignment** with sibling enums elsewhere in the plugin (e.g. don't use `passing` here if the rest of the plugin uses `compliant`).

## Step 2: Author the `.edge.json` File

Create `<plugin>/edges/<EDGE_SLUG>.edge.json` matching `edge-definition.schema.json`:

```json
{
  "slug": "<EDGE_SLUG>",
  "name": "<Human Name>",
  "description": "<Sentence explaining what the edge represents.>",
  "sources": ["<source_entity_type>"],
  "targets": ["<target_entity_type>"],
  "property_schema": {
    "type": "object",
    "required": ["<key>"],
    "additionalProperties": false,
    "properties": {
      "<key>": {"type": "string", "enum": ["<v1>", "<v2>"]}
    }
  },
  "default_dimensions": {
    "<dim_key>": "<dim_value>"
  }
}
```

### Field rules (per `edge-definition.schema.json`)

- `slug`, `name`, `description` are required and must be non-empty.
- `slug` **must** equal both the filename (minus `.edge.json`) and the manifest key.
- `sources` and `targets` are arrays of entity-type slugs; omit either to allow wildcard at that end.
- `property_schema` is a JSON Schema object; the service layer validates edge properties against it on create/update (net of the system-owned `hotlink` key, which it must not declare). Required whenever the edge carries properties; a schema-less type may only ever write empty properties.
- `default_dimensions` is a flat string-to-string map applied at edge creation when the caller doesn't specify dimensions.

## Step 3: Register in the Plugin Manifest

Edit `<plugin>/tap-plugin.toml`. Under `[edges]`, add the edge:

```toml
[edges]
<EDGE_SLUG> = "edges/<EDGE_SLUG>.edge.json"
```

The manifest key on the left **must** equal the edge file's `slug`. Any mismatch surfaces as a manifest validation error.

## Step 4: Validate and Smoke-Test

Validate the manifest and edge files:

```bash
scripts/dc exec web uv run python manage.py validate_plugin <plugin> --level structure
```

Then smoke-test creating an edge of the new type via the service layer (Django shell or a test):

```python
from tap_grid.services import create_edge
from tap_grid.caller_context import CallerContext

ctx = CallerContext()
edge = create_edge(
    from_target="<source_entity_id>",
    to_target="<target_entity_id>",
    edge_type="<EDGE_SLUG>",
    payload={"properties": {"<key>": "<value>"}},
    caller_context=ctx,
)
```

Confirm:

- Sources / targets that violate the type's declared `sources`/`targets` are rejected with a clear error.
- Properties outside the `property_schema` are rejected.
- `default_dimensions` are applied when the caller omits dimensions.

## Step 5: Update or Add the Spec

Edges, like models, must be spec-driven. Either:

- Add a new requirement to an existing plugin spec, OR
- Add an "Edge Types" subsection that documents the new edge alongside its peers.

The requirement should cover:

- Sources / targets the edge accepts.
- Property schema (especially any enums that drive validation logic).
- Default dimensions.
- Whether the edge is hotlink-bearing (and which model owns the hotlink).
- Status: `In Development` → `Implemented` after Step 7 passes.

If the edge replaces or supersedes an existing edge type, update the deprecated edge's requirement and add a migration note.

## Step 6: Author GRIFT Seed Data (if applicable)

If the plugin needs reference data using this edge type, add edges in a GRIFT bundle. Read [`tap_grid/specs/spec-grift-v0.md`](../../specs/spec-grift-v0.md) for format and idempotency rules.

GRIFT envelope shape for an edge:

```json
{
  "entity": {
    "entity_id": "<uuidv7>",
    "entity_type": "edge",
    "name": "<source label> <EDGE_SLUG> <target label>",
    "dimensions": {"<dim>": "<value>"}
  },
  "edge": {
    "from_entity_id": "<source-uuid>",
    "to_entity_id": "<target-uuid>",
    "edge_type": "<EDGE_SLUG>",
    "properties": {"<key>": "<value>"}
  }
}
```

UUIDv7 batch / entity / edge ids should come from `scripts/uuid7`. Iteration follows the canonical paths in [`tap_plugins/specs/spec-tap-plugin-architecture.md`](../../../tap_plugins/specs/spec-tap-plugin-architecture.md) (`req-tap-plugin-arch-iterative-dev`): version-bump for shipping, `--force-batches` for dev iteration only.

## Step 7: Tests

Add tests that exercise the edge through the service layer:

- **Type acceptance**: edges with allowed source/target types are created successfully.
- **Type rejection**: edges with disallowed source/target types are rejected with a clear error.
- **Property schema**: required properties are enforced; unknown properties are rejected.
- **Default dimensions**: applied when caller doesn't override.
- **Idempotency**: GRIFT re-import of an edge with the same `entity_id` is a no-op (per the importer contract).

Place tests in `<plugin>/tests/test_<edge_slug>.py` or a more general edge-suite test file when adding many at once.

## Step 8: Verify and Sync

```bash
# Run the edge tests.
scripts/dc exec web uv run pytest <plugin>/tests/test_<edge_slug>.py -v

# Run the plugin manifest test.
scripts/dc exec web uv run pytest <plugin>/tests/test_<plugin>_manifest.py -v

# Re-import GRIFT if you added seed data.
scripts/dc exec web uv run python manage.py import_plugin_grift <plugin>
```

Once green:

- Flip the spec requirement Status from `In Development` → `Implemented`.
- Update the spec's requirement-status table.
- If docs reference any RIDs you changed, follow the doc-spec sync rules in [`specs/spec-docs.md`](../../../specs/spec-docs.md).

## Common Mistakes (do not commit any of these)

- **Slug case mismatch.** The edge slug, filename, and manifest key must match exactly. `Has_Evidence` ≠ `HAS_EVIDENCE`.
- **`additionalProperties: true` (or omitted) on `property_schema`.** Default to `false`. Silent property growth makes the edge type's contract unstable.
- **Bare generic or philosophical edge slugs.** Bare verbs (`USES`, `RUNS`, `HAS`, `ROUTES`, `STORES`, `PULLS`) need the object noun (`ROUTES_TRAFFIC`, `WRITES_LOGS`, `PULLS_IMAGE`). Philosophical names (`PROTECTS`, `BACKED_BY`, `DEPENDS_ON`) describe a role, not a mechanism — name the action. Never use `_TO` (forward is unmarked); use `_FROM` only for a genuine data-backwards edge, never as a plain direction marker.
- **One edge conflating many relationships.** A single edge type whose `sources`/`targets` span multiple unrelated concrete type pairs (a `CONTAINS` doing region→AZ + VPC→subnet + cluster→service; a `RESIDES_IN` at 15→4) is standing in for several relationships at once — split it into specific per-relationship edges. Generalized containment/inside-ness is a reified-path concern, not one mega-edge (`docs/misc/grid-native-paths-notes.md`). Never introduce a generic `CONTAINS`.
- **Wildcard sources/targets without justification.** Typed plugins should constrain edge endpoints. Wildcards are appropriate for cross-plugin edges (e.g. `HAS_FINDING` from any asset to a finding), but they should be a deliberate choice, not the default.
- **Forgetting `default_dimensions`.** Edges should carry the same dimension convention as their endpoints; missing dimensions cause silent scoping bugs later.
- **Authoring GRIFT edges without a UUIDv7.** Use `scripts/uuid7`; never hand-shape edge entity_ids.
- **Skipping the hotlink declaration** when the edge is the materialization of a JSON reference. Without it, the JSON and the edge set will drift.
