---
name: build-collector
description: Build a new TAP collector — a CollectorBase subclass that fetches data from somewhere (cloud API, signed web URLs, a tool's output) and lands typed nodes + edges on the grid as a GRIFT batch. Use when adding a new ingestion source.
allowed-tools: Read Write Edit WebFetch WebSearch Bash(scripts/dc *) Bash(scripts/log-site-id *) Bash(scripts/uuid7 *) Bash(grep *) Bash(find *) Bash(ls *) Glob Grep
argument-hint: <plugin_slug> <collector_key>
---

# Build a New TAP Collector

You are adding a new ingestion source to TAP. The collector is a `CollectorBase` subclass that runs (on a schedule or on demand), fetches data from somewhere, decomposes it into typed nodes and edges per the plugin's model catalog, and submits one GRIFT batch through `self.submit_grift(...)`. The `tap_cares` runtime handles registration, scheduling, result persistence, and the abort-on-rejection safety default.

## Authoritative Sources

Read these before writing code; do not guess from memory.

- **[`tap_cares/collectors/base.py`](../../../tap_cares/collectors/base.py)** — the `CollectorBase` ABC. `run()` is abstract; `record_info`/`record_warn`/`record_error` accumulate structured events; `submit_grift(document)` is the only path to grid writes and defaults to **abort-on-rejection** (a GRIFT-rejected batch raises `GriftRejectedError` automatically — every collector inherits the safe default).
- **[`tap_cares/registry.py`](../../../tap_cares/registry.py)** — `register_collector(key, cls, *, name, description)`. Called from the plugin's `apps.py` `ready()`. Key must match `^[A-Za-z0-9][A-Za-z0-9_.\-]*$`.
- **[`tap_cares/specs/spec-tap-cares-collector.md`](../../../tap_cares/specs/spec-tap-cares-collector.md)** — the collector subsystem spec.
- **[`tap_grid/schemas/grift-document.schema.json`](../../schemas/grift-document.schema.json)** — the GRIFT document schema your batches are validated against. Read this *before* assembling batches; the gotchas section below names the easy traps.

## Reference Implementations

All three live in **their own repositories** now (plugin eviction), so read them there rather than
in this tree — `tap-plugin-aws-core`, `tap-plugin-github-core`, `tap-plugin-samsite`.

| Reference | Shape | Read it for |
| --- | --- | --- |
| **`aws_core`** — `collectors/boto3_collector/` | **Manifest as engine.** `aws_resource_manifest.json` holds 17 entries and the collector literally loops `for entry in entries`. No per-service classes. | What an executable manifest looks like: `source`, `items_path`, `natural_key`, a `fields` **map**, `edges`, and a `custom_fn` escape hatch for the shapes a table cannot express. |
| **`github_core`** — `collectors/github_collector/` | **Manifest as contract, engine procedural.** The manifest declares 15 sources and *derives the least-privilege permission set*; the collector calls the endpoints in hand-written Python. | Permission declaration, multi-transport collection (REST + GraphQL + file reads), degradation handling, and vendor-spec conformance. |
| **`samsite`** — `collectors/compliance_collector/` | **Fetch-and-verify.** A manifest of URLs; fetch over HTTPS, verify signatures, decompose. No credentials. | The no-credential case, and signature verification as part of ingestion. |

All subclass `CollectorBase`, register the same way, and submit one GRIFT batch per run.

### The direction of travel: the manifest is the engine

`aws_core` and `github_core` arrived at the same concept from opposite ends and **each built the
half the other lacks** — aws_core is executable but declares no permissions; github_core declares
permissions rigorously but its manifest cannot force the code to obey it. Neither is the finished
shape. **Build toward the union**, and prefer declaring a capability in the manifest over writing
it in the collector.

A collector manifest should be able to express, and a new collector should use whichever of these
apply:

| Capability | What it declares | Reference |
| --- | --- | --- |
| **Mapping** | our field name ← their response key, as a **map** not a list | `aws_core` |
| **Permissions** | the grant each source needs, in the vendor's canonical grammar, so least-privilege is a **union over sources** rather than hand-listed | `github_core` |
| **Dependencies** | that one entry needs another's output (github_core's refs index feeds ruleset→ref resolution) — declare the ordering rather than encoding it in call order | *neither yet* |
| **Custom tweaks** | a named escape hatch for what the table cannot express, so the exception is visible instead of dissolving the table | `aws_core`'s `custom_fn` |
| **Failure posture** | what a refused source means — `degrade_with_warning` vs abort | `github_core` |
| **Absence semantics** | what it means when a thing you could see is **not** in the response | *neither yet* — see below |

Where the manifest cannot yet express something, say so in the manifest's own description rather
than letting the code silently become the only record.

## The discipline that outranks the rest: absence is not an answer

Every collector meets this, and it has cost more than any other class of mistake in this codebase:
**a missing fact and a negative fact must never render the same way.** A count of `0` that means
"we were not allowed to look" is worse than an error, because it is reassuring and it is wrong.

Four ways it arrives, all seen in production collectors:

1. **A refused source.** `github_core`'s runner listing needs repo administration; without it the
   API returns `403`, the collector degrades with a warning and continues — so an empty runner set
   means *either* "no self-hosted runners" *or* "not allowed to look". Opposite findings, identical
   bytes. Whatever renders it must carry three states, not two.
2. **An incomplete walk.** Paginate to the end of the chain, and **record whether you got there**.
   `github_core`'s client sets `last_walk_complete` for exactly this: a page-cap stop must never be
   mistaken for a complete enumeration by anything downstream.
3. **A field the transport does not carry.** If one transport returns a field and another does not,
   write `None`, not a default. The grid convention is `null` = unobserved, `""` = observed-empty,
   and defaulting to a plausible value asserts an absence you never looked for.
4. **A rule you did not attempt.** When enrichment cannot run — a cross-plugin vocabulary is not
   installed — record *that you skipped it*, do not emit nothing. `github_core`'s `SkippedRule` is
   the pattern.

### Additive-only is a defect, not a phase

Both committed cloud collectors are additive-only today: they upsert what they found and **never
tombstone**, so a deleted resource stays on the grid looking exactly as live as a real one. That is
a known gap being worked, not a pattern to copy.

The grid already has the primitive — `Entity.deleted_at`, `.live()` / `.tombstoned()`, and
`delete_node` / `delete_edge_by_entity` in the service layer. What is missing is the collector
knowing when absence is *admissible as evidence*, which depends on the type:

```
may_tombstone(type) =
      the credential could reach every source for this type
  AND absence from a complete read actually MEANS deletion for this type
  AND the walk was complete AND the scope was unfiltered
```

The middle clause is a property of the object, not of the API, so it has to be **declared**:
a deleted repository is gone; an Actions run that has aged out of retention is **not** deleted and
tombstoning it would destroy history; a relation whose matching rule changed was *re-derived*, not
ended. Declare it per type or do not reconcile — never reconcile by default.

If your source is version-controlled (a git host), you get something better than absence:
a commit that **removes** a file is positive proof of deletion. Prefer it wherever it exists.

## Step 1: Confirm the Shape With the User

Before code:

1. **Plugin** (e.g. `aws_core`, `samsite`) — the collector lives inside an existing plugin.
2. **Collector key** (e.g. `boto3`, `samsite-compliance`) — token pattern `^[A-Za-z0-9][A-Za-z0-9_.\-]*$`, distinctive enough to recognize across plugins.
3. **Source pattern** — manifest-driven enumeration or fetch-and-verify (or something else; flag).
4. **What goes on the grid** — which node types and edge types the collector emits, all of which must already be specced + registered in the plugin (use the **add-model** and **add-edge** skills first if not).
5. **Identity strategy** — what is the natural key per node type, and does it dedup across runs (per the plugin's identity spec)?
6. **Credentials / config** — none, or via `TAP_SECRETS_ROOT`? Plugin-self-config, never core infra. **If this collector needs a credential, stop and run the [manage-secret](../../../tap_cares/skills/manage-secret/SKILL.md) skill first** — it owns scoping, the `kind` data schema, redaction, and teaching the leak scanner the credential's shape. Do not wire a secret from memory; a mistake here is not recoverable by editing.
7. **Schedule** — manual-only in v0, or recurring (GRIFT-seeded schedule)?

Write the agreed shape down; it becomes the spec section in Step 8.

## Step 2: Create the Collector Package

Layout, with the per-module job:

```
plugins/<plugin>/collectors/<collector_slug>/
├── __init__.py
├── <manifest>.json              # declarative source (resource set / URL set)
├── <manifest>.schema.json       # JSON Schema for the manifest; fail-loud at load
├── manifest.py                  # load_manifest() with lru_cache + schema validation
├── identity.py                  # NAMESPACE_<X>, node_entity_id, edge_entity_id
├── decompose.py | projection.py # source rows / artifacts -> node + edge envelopes
├── batch.py                     # assemble_batch(...) -> GRIFT document
└── collector.py                 # the CollectorBase subclass
```

A simpler collector can fuse files (e.g. fold `batch.py` into `collector.py`). A more elaborate one splits further (the boto3 collector splits credentials, RGTA tags, transforms, an audit ledger). Pick the minimum that's readable.

## Step 3: The Declarative Manifest

The manifest is **data, not code**. An agent reads the manifest and knows what the collector fetches without reading collector code — this is the [declarative-shapes-over-code](../../../AGENTS.md) discipline.

Ship a JSON Schema in the same change ([JSON-formats-need-a-schema](../../../AGENTS.md)). At load, validate; on failure, raise a typed `<X>ManifestError` — the collector turns this into `record_error(MANIFEST_INVALID)` + abort.

The boto3 collector's `aws_resource_manifest.json` declares per-service / per-resource probes; the samsite collector's `artifact_manifest.json` declares URL paths and handling modes; github_core's `github_collection_manifest.json` declares the permission each source needs. All are single sources of truth.

### Hold the manifest against the vendor's own description, if there is one

If the API you are collecting publishes a machine-readable description — an OpenAPI document, a
service model, a published schema — **conform the manifest to it in a test**. This is not
optional polish; it closes a gap that has no other cover.

The reason is specific: a hand-written client and a hand-written manifest mean nobody is keeping
your endpoint paths and field names current except you. A retired endpoint fails loudly on the
next run, but a **renamed field just starts arriving as `None`**, and the node lands looking
merely sparse rather than wrong. Nothing in the build catches it.

The worked example is `github_core`'s `test_openapi_conformance.py`:

- A refresh script pulls the vendor's description and writes a **small pinned extract** — just the
  paths you call and the properties they return. Do not vendor a 12 MB spec, and do not fetch it
  inside the test: the suite must stay offline and hermetic.
- The refresh is a **deliberate maintainer act** whose output rides a PR. Never regenerate as part
  of a build — a vendor change that silently updated your own expectations is precisely the drift
  you were trying to detect. Offer a `--check` mode for a nightly.
- **State what the conformance does not cover**, in the test's docstring, so a green run is not
  over-read. For github_core that is GraphQL sources, file reads, and permissions — GitHub's
  description carries no structured permission metadata at all, so the triples have no upstream to
  conform to and had to be authored.

When there is no published description, say so in the manifest description. "We checked and there
isn't one" is a finding worth recording; silence reads as nobody having looked.

## Step 4: Identity Helpers

Frozen `uuid5` namespace + deterministic id derivation:

```python
NAMESPACE_<COLLECTOR>: Final[uuid.UUID] = uuid.uuid5(uuid.NAMESPACE_DNS, "tap.<plugin>.<collector_slug>")

def node_entity_id(entity_type: str, natural_key: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE_<COLLECTOR>, f"{entity_type}:{natural_key}")

def edge_entity_id(edge_type: str, from_key: str, to_key: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE_<COLLECTOR>, f"edge:{edge_type}:{from_key}->{to_key}")
```

**The namespace is frozen.** Changing it re-identifies every node on every grid the collector has ever touched — not permitted post-v0. The natural-key schema per entity type is the contract; record it in the spec.

## Step 5: Decomposition / Projection

The function(s) that turn source data (an API response row, a parsed artifact) into GRIFT envelopes. Per-envelope shapes:

**Node envelope:**
```python
{
    "entity": {
        "entity_id": "<uuid str>",
        "entity_type": "<your_node_type>",   # the model's ENTITY_TYPE
        "name": "<display name>",
        "dimensions": {"compliance": "..."},  # or {} if dimension-less (justify)
    },
    "node": {
        "name": "<display name>",
        # … typed model fields …
    },
}
```

**Edge envelope (gotchas live here — read carefully):**
```python
{
    "entity": {
        "entity_id": "<uuid str>",
        "entity_type": "edge",          # <-- LITERAL "edge", not the slug
        "name": "<EDGE_SLUG>",          # the slug goes here, in name
        "dimensions": {},
    },
    "edge": {
        "from_entity_id": "<uuid str>",
        "to_entity_id": "<uuid str>",
        "edge_type": "<EDGE_SLUG>",     # the slug
        "properties": {},               # <-- REQUIRED, even if empty
    },
}
```

If a node model has no `tags`/`configuration` fields (most don't outside `aws_core`), don't emit them — `additionalProperties: false` will reject unknown fields.

## Step 6: GRIFT Batch Assembly

One run = one batch. Shape:

```python
{
    "metadata": {"grift_version": "0"},
    "_reserved": {},
    "batches": [{
        "batch_entity": {"entity_id": <uuid>, "entity_type": "batch", "name": ..., "dimensions": {}},
        "batch_node": {
            "source": "plugins.<plugin>.collectors.<slug>",
            "name": ...,
            "description": ...,
            "description_json": {"format": "tap.<plugin>.collection-v0", "data": {<run summary>}},
        },
        "nodes": [<node envelopes>],
        "edges": [<edge envelopes>],
    }],
}
```

The boto3 and samsite `batch.py` modules are minimal — copy the shape, change the labels.

## Step 7: The Collector Class

```python
class <X>Collector(CollectorBase):

    def _abort(self, site: str, code: str, message: str) -> None:
        self.record_error(site, code, message)
        raise <X>CollectorError(message)

    def run(self) -> None:
        self.record_info(_SITE_RUN_STARTED, "RUN_STARTED", "...")

        try:
            manifest = load_manifest()
        except ManifestError as exc:
            self._abort(_SITE_MANIFEST_INVALID, "MANIFEST_INVALID", str(exc))

        # Fetch / enumerate.
        # Decompose.
        # Assemble batch + submit.

        document = assemble_batch(...)
        self.submit_grift(document)   # abort-on-rejection by default

        self.summary = f"Submitted {len(nodes)} node(s) + {len(edges)} edge(s)."
        self.record_info(_SITE_RUN_FINISHED, "RUN_FINISHED", self.summary)
```

**Site tokens.** Every `record_*` call needs a `site` — a 4-hex token unique within the file. **Mint them with `scripts/log-site-id N`; never guess.** Module-level `_SITE_<NAME> = "<hex>"` constants are the convention.

**Failure mode.** Per-item failures (one fetch fails, one document doesn't parse) are `record_warn(...)` + `continue` — visible, not fatal. Unrecoverable failures are `_abort(...)` (records `record_error` and raises). The `tap_cares` task body turns the raise into a `FAILED` terminal patch.

**GRIFT rejection.** `submit_grift` defaults to `on_rejection="abort"` (see [GRIFT-atomic-batch-rejection memory + spec](../../../tap_cares/specs/spec-tap-cares-collector.md)). Don't override unless you have a multi-batch partial-success need and you've thought through what to do with the errors.

## Step 8: Register the Collector

In `plugins/<plugin>/apps.py`:

```python
class <Plugin>Config(TapPluginConfig):
    def ready(self) -> None:
        super().ready()  # MUST run first — loads tap-plugin.toml

        # Inside ready(), not at module top — keeps apps loading light.
        from plugins.<plugin>.collectors.<slug>.collector import <X>Collector
        from tap_cares.registry import register_collector

        register_collector(
            key="<collector_key>",
            cls=<X>Collector,
            name="<Display Name>",
            description="<one paragraph>",
        )
```

Registration is dual-existence: it both registers the runner class and upserts the on-grid `Collector` node.

## Step 9: Live-Test

Restart the container so plugin `ready()` re-runs. Then invoke the collector:

```bash
./scripts/dc restart web
./scripts/dc exec -T web uv run python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','tap.settings')
django.setup()
from tap_cares.models import Collector
from tap_cares.services import run_collection
from tap_grid.caller_context import CallerContext
c = [c for c in Collector.objects.select_related('entity') if 'YOUR COLLECTOR' in (c.entity.name or '')][0]
job = run_collection(c, caller_context=CallerContext(), manual_run=True, manual_run_source='dev-test')
print('job:', job.entity_id)
"
```

Poll the `CollectionJob` until `SUCCESSFUL` / `FAILED`; inspect `j.results['info' | 'warn' | 'error']` and `j.summary`. Verify counts of grid rows for each model the collector emits.

## Step 10: Spec, Tests, Commit, Promote

- **Spec.** A `spec-<plugin>-<collector>-v0.md` in `plugins/<plugin>/specs/` per the agreed shape from Step 1. Requirements as `Proposed`; tighten to `Implemented` after live verification.
- **Tests.** Unit tests for the decomposition (synthetic input → expected node/edge counts and identities) and the manifest loader (invalid manifests fail loud). Integration is the live run.
- **Promote.** Full sweep, then `scripts/promote-to-main.sh` ([Promote sessions to main memory](../../../AGENTS.md)).

## Gotchas — the ones that bit on the way through

Read these before you submit a batch and find out the hard way:

1. **Edge envelope `entity.entity_type` must be the literal string `"edge"`** — *not* the edge slug. The slug goes in `entity.name` and `edge.edge_type`. Mismatch → `entity_type_mismatch`, full-batch rejection.
2. **Edge envelope `edge.properties` is REQUIRED** — empty `{}` is fine; missing the field is a schema-validation failure.
3. **Don't emit fields the model doesn't have.** `additionalProperties: false` rejects extras (the boto3 collector emits `tags`/`configuration` because the aws models have them; most fedramp models don't — don't emit those there).
4. **Don't import `uuid_extensions`** — it's not a default dep. Use stdlib `uuid.uuid4()` for per-run batch ids unless you've already added the package.
5. **`super().ready()` MUST be the first thing in your plugin's `ready()`** — it loads the manifest. Skip it and the plugin's edges/models aren't registered.
6. **Mint site tokens with `scripts/log-site-id`** — never hand-pick a hex. The scanner enforces format and within-file uniqueness.
7. **Stale workers eat code changes.** After any code change touching the collector module, `./scripts/dc restart web` before you re-run. The worker keeps imports cached.
8. **Scale breaks what one item hides.** `github_core` collected one repository cleanly and then failed at nineteen, three ways: a shared node emitted once per repo tripped GRIFT's duplicate-id rejection and **nothing landed**; one transient error aborted the whole run; and a run naming a since-deleted workflow made the batch's edges dangle and rejected everything. Dedupe shared nodes across the run, drop dangling edges and *say how many*, and let one item's failure be recorded rather than fatal. Test at plural, not at one.
9. **An empty result and a refused result need different code paths.** Do not let a `403` become an empty list two frames later. Record which it was, at the point you know.
10. **A collector's SDK dependency must be FIPS-clean** (`spec-fips.md`, standing filter). Collectors reach cloud APIs, so they tend to pull an SDK/HTTP client — and TAP runs FIPS-on by default. Before adding one, run the **Dependencies FIPS check** from the [`new-plugin`](../../../tap_plugins/skills/new-plugin/SKILL.md) skill: an SDK that bundles its own OpenSSL (a `[binary]` wheel) or uses non-OpenSSL crypto (Rust `ring`/`aws-lc-rs`, `libsodium`, a bundled Go binary) is NOT the validated module and either breaks or runs silently non-FIPS. Prefer libs that link the system OpenSSL (boto3 does — it signs via `cryptography`/OpenSSL); if a non-validated provider is unavoidable, declare it in the plugin's manifest `[fips]` table (`status = "uses-nonvalidated"` + reason). The crypto-BOM boot gate fails-closed on an un-waived non-validated provider, so an un-declared SDK crypto surface will refuse to serve under `TAP_FIPS=1`.
