# Panel Entity Resolution Specification

## Philosophy

Several TAP panels render content derived from a single on-grid entity. The entity is picked one of two ways: either the caller deep-links by passing the entity's `entity_id` as a URL query parameter (bookmarkable, stable across time), or the panel falls back to *a specific entity that a configured Gryphon query selects* when the URL is bare (always-render-something default). Either way, the rendered page should make it clear which path was taken so the user knows whether they're looking at a deep-linked entity or one picked by the fallback.

The configured shape is a **Gryphon query**, written by the panel author directly in config alongside a human-readable description of *why* that query is the right fallback for this panel. There is no enumerated "selection strategy" — the query *is* the strategy. A panel wanting "latest by timestamp" writes `ORDER BY n.data.<sort_field> DESC LIMIT 1`. A panel wanting "single match expected, surface ambiguity" writes `LIMIT 2` and lets the helper report the row count. A panel wanting "first by name" writes `ORDER BY n.name ASC LIMIT 1`. The helper does not enumerate strategies, parse the query, or construct it from disassembled config fields; it runs the query Gryphon-side and reports what came back.

A third path — **relative (context-derived) resolution** — is proposed (`req-web-panel-entity-resolution-relative`): resolve the panel's entity by traversing the grid *from* the entity the host page is about (whose id is in the URL) to a related target, e.g. a batch-summary panel dropped on a collection-run page resolving "the batch this run produced." It is the fallback mechanism with one change — the Gryphon query is bound to a URL-derived context id and hops an edge, instead of running with empty parameters — so it reuses the same count semantics, error states, and result shape. It does not change the two paths below; it inserts between them in the resolution order.

This spec governs **panel-side resolution**. Per-emission identity semantics for the *entities themselves* (why nodes accumulate over time rather than upserting in place, when and why a discriminator field carries a particular value) live with the relevant collector spec. This spec does not govern those decisions; it governs what panels do once those nodes exist.

**Dependency on Gryphon.** This spec presumes Gryphon supports `ORDER BY` + `LIMIT` on graph-envelope returns for type-scans — the common "latest" fallback shape is the demand-shape behind that ask. The wishlist entry sits in Bucket A of [`docs/misc/doc-dev-gryphon-wishlist.md`](../../docs/misc/doc-dev-gryphon-wishlist.md). The helper module is built against that surface; the resolution path runs entirely inside Gryphon with no Python-side sort and no candidate-set materialization.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Bookmarkable | A bare URL like `/<consumer>/<page>` (no query string) renders the entity that the panel's fallback Gryphon query selects. |
| 2. | Deep-linkable | A URL with the canonical entity_id query parameter renders that specific entity. |
| 3. | Honest About Source | When the panel resolved via fallback rather than URL, the template context exposes `used_fallback` and `fallback_description` so the rendered page shows "Showing fallback selection: <description>." Users never see "the entity" without knowing how it was picked and why. |
| 4. | Minimal Helper, N Callers | Resolution lives in one named module under `tap_web` — two narrow lookup operations plus an orchestrator. Consumer panels call the orchestrator. The helper does not construct Gryphon queries from disassembled config fields; panels declare their fallback query directly. |
| 5. | Polished Failures | Each failure phase (no URL var with no fallback, URL miss, fallback empty, fallback ambiguous, transient Gryphon error) renders a distinct user-readable error state — not a stack trace. |
| 6. | No Privileged Defaults | The helper does not bake in domain-specific entity types, field names, or queries. Every panel that wants a fallback supplies its own Gryphon query and a human-readable description of what it picks. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-panel-entity-resolution-config | [Panel Config Contract](#panel-config-contract) | Implemented | `entity_id_var` + optional `fallback.{query, description}`; multi-entity panels use `<role>_entity_id_var` + `fallback.<role>.{query, description}` |
| req-web-panel-entity-resolution-order | [Resolution Order](#resolution-order) | Implemented | URL deep link wins; fallback Gryphon query runs only when URL var is empty |
| req-web-panel-entity-resolution-helper | [Shared Helper Module](#shared-helper-module) | Implemented | `tap_web.panels.entity_resolution` — `_lookup_by_entity_id`, `_run_fallback_query`, `EntityResolution`, `resolve_entity` |
| req-web-panel-entity-resolution-result-shape | [EntityResolution Dataclass](#entityresolution-dataclass) | Implemented | Fields: `entity_id`, `var_name`, `node`, `error`, `used_fallback`, `fallback_description`, `fallback_count`, `ok` (derived) |
| req-web-panel-entity-resolution-template | [Template Surface Conventions](#template-surface-conventions) | Implemented | `used_fallback` and `fallback_description` propagate to context; banner shows description when fallback fired |
| req-web-panel-entity-resolution-errors | [Polished Error States](#polished-error-states) | Implemented | Distinct messages per failure phase; entity_id, var_name, and fallback_description echoed as relevant |
| req-web-panel-entity-resolution-empty-state | [Empty-State Distinction](#empty-state-distinction) | Implemented | Single-entity panels SHOULD render `fallback_count == 0` as an informational empty state, not a red error block |
| req-web-panel-entity-resolution-multi | [Multi-Entity Panels](#multi-entity-panels) | Implemented | Per-role resolution + per-role fallback sub-block when a panel needs more than one entity |
| req-web-panel-entity-resolution-relative | [Relative (Context-Derived) Resolution](#relative-context-derived-resolution) | Proposed | Resolve the target by traversing from a URL context entity; the fallback mechanism bound to `$context_id` over an edge |
| req-web-panel-entity-resolution-tests | [Test Coverage Requirements](#test-coverage-requirements) | Implemented | Each consumer mocks the helpers and exercises URL-wins / fallback-fires / no-URL-no-fallback / fallback-empty / fallback-ambiguous paths |

### Panel Config Contract
----
RID: `req-web-panel-entity-resolution-config`
Status: `Implemented`

A single-entity panel declares two config fields:

- `entity_id_var` — the **name** of the URL query parameter the panel reads. The panel does not hardcode the URL parameter name; consumers pick whatever fits the host page's naming.
- `fallback` — an optional block describing the Gryphon query that picks the entity when the URL var is empty. When present, the block carries two fields:
  - `query` — a Gryphon query string. The panel author writes the query; the helper executes it verbatim. The query's `ORDER BY` / `LIMIT` shape determines the resolution semantics: `ORDER BY ... DESC LIMIT 1` for "latest"; `LIMIT 2` for "single match expected, surface ambiguity"; `ORDER BY name ASC LIMIT 1` for "first by name"; whatever the panel's intent calls for. For sort-by-timestamp queries the panel author SHOULD include `AND <sort_field> IS NOT NULL` in the WHERE clause for defense in depth — PostgreSQL's native DESC ordering puts NULLs first, so a NULL sort field would otherwise win silently. Gryphon string literals use double quotes per its grammar; in JSON config that's `\"oscal_ssp\"`, not `'oscal_ssp'`.
  - `description` — a human-readable rationale for the query (e.g., "Latest oscal_ssp compliance artifact by fetched_at — the most recent SSP emission on the grid"). Shown in the fallback banner and in error messages so users and operators can immediately understand what the fallback resolves to and why.

If the `fallback` block is absent, the panel returns its "no entity specified" error when the URL var is empty.

Single-entity shape:

```json
{
  "entity_id_var": "<page-variable-name>",
  "fallback": {
    "query": "MATCH (n:<entity_type>) WHERE n.data.<field> = \"<value>\" AND n.data.<sort_field> IS NOT NULL ORDER BY n.data.<sort_field> DESC LIMIT 1",
    "description": "<human-readable rationale for the query>"
  }
}
```

Concrete example (ROSCALE OSCAL SSP workbench):

```json
{
  "entity_id_var": "oscal_ssp_artifact_entity_id",
  "fallback": {
    "query": "MATCH (a:compliance_artifact) WHERE a.data.kind = \"oscal_ssp\" AND a.data.fetched_at IS NOT NULL ORDER BY a.data.fetched_at DESC LIMIT 1",
    "description": "Latest oscal_ssp compliance artifact by fetched_at — the most recent SSP emission on the grid."
  }
}
```

Multi-entity shape (see `req-web-panel-entity-resolution-multi`) — per-role `<role>_entity_id_var` keys at the top, per-role sub-blocks under `fallback`:

```json
{
  "<role-a>_entity_id_var": "<page-variable-name-a>",
  "<role-b>_entity_id_var": "<page-variable-name-b>",
  "fallback": {
    "<role-a>": {
      "query": "MATCH ...",
      "description": "..."
    },
    "<role-b>": {
      "query": "MATCH ...",
      "description": "..."
    }
  }
}
```

Both `query` and `description` are required when a `fallback` block is present — a partially-specified fallback is a config error. The platform has no defaults; every consumer states explicitly what the fallback resolves to and why. A panel that wants no fallback omits the `fallback` block entirely.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-entity-resolution-config-1 | URL Var Name In Config | Implemented | The panel reads `panel.config["entity_id_var"]` for single-entity panels, or `panel.config["<role>_entity_id_var"]` for multi-entity panels, and uses that string as the key into `request.GET`. | |
| req-web-panel-entity-resolution-config-2 | Fallback Optional | Implemented | A panel config without a `fallback` block is valid; the resolver returns its "no entity specified" error if the URL var is empty. | |
| req-web-panel-entity-resolution-config-3 | Fallback Fields Required | Implemented | When `fallback` is present, both `query` (Gryphon string) and `description` (human-readable rationale) MUST be set. A partially-specified fallback is a config error. | |
| req-web-panel-entity-resolution-config-4 | Author Owns Query Semantics | Implemented | The query's `LIMIT` and `ORDER BY` shape determine resolution semantics; the helper does not modify, wrap, or interpret the query. A `LIMIT 1` query returns 0 or 1 rows; a `LIMIT 2` query returns 0, 1, or 2 rows; the helper treats counts the same way regardless of how the LIMIT was set. | |

### Resolution Order
----
RID: `req-web-panel-entity-resolution-order`
Status: `Implemented`

Per role / per entity:

1. **Explicit URL deep link wins.** If `request.GET[var_name]` is non-empty (after stripping whitespace), look up that `entity_id` via the helper's labelless deep-link Gryphon query (`MATCH (n) WHERE n.entity_id = $entity_id`). If found → `EntityResolution(node=<n>, used_fallback=False)`. If not found → polished "Entity not found for entity_id '<id>'" error.
2. **Fallback when URL var is empty AND `fallback.query` is configured.** Run the panel's configured Gryphon query verbatim. If the query returns exactly one row → `EntityResolution(node=<n>, used_fallback=True, fallback_description=<config description>, fallback_count=1)`. If it returns zero rows → polished "fallback query returned no entities yet — <description>" error. If it returns two or more rows → polished "fallback ambiguous: query returned N entities — <description>" error.
3. **Neither URL var nor fallback configured** → polished "no entity specified; append `?<var_name>=<entity_id>` to the URL" error.

Explicit URL deep link MUST win even when fallback is configured. This is the bookmarkable-deep-link guarantee: a URL with an entity_id reproduces a specific historical view regardless of what the fallback query currently picks.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-entity-resolution-order-1 | URL Wins | Implemented | When both URL var has a value AND `fallback` is configured, the resolver uses the URL value and never runs the fallback query. | |
| req-web-panel-entity-resolution-order-2 | Fallback Marks Itself | Implemented | When the fallback query fires, the result's `used_fallback` is True and `fallback_description` is populated from config. | |
| req-web-panel-entity-resolution-order-3 | Explicit URL Miss Is Distinct | Implemented | URL var supplied but entity_id not on the grid produces a different error message than "no entity specified." | |

### Shared Helper Module
----
RID: `req-web-panel-entity-resolution-helper`
Status: `Implemented`

The canonical helpers live at **`tap_web/panels/entity_resolution.py`** and consist of:

- `EntityResolution` (dataclass) — result shape (see `req-web-panel-entity-resolution-result-shape`).
- `_lookup_by_entity_id(entity_id) -> dict | None` — runs the labelless Gryphon `MATCH (n) WHERE n.entity_id = $entity_id` and returns the envelope node or `None`. The helper does not require an `entity_type` parameter; entity_id is spine-level and the labelless MATCH scans the spine table once.
- `_run_fallback_query(query) -> tuple[list[dict], int]` — runs the panel-supplied Gryphon query verbatim and returns the `(nodes, count)` tuple. The helper does not interpret or modify the query; the count is what the database returned (capped by whatever LIMIT the query carries). Transient Gryphon errors raise.
- `resolve_entity(panel, request, *, role=None, default_var_name) -> EntityResolution` — the orchestrator panels call. Reads config, walks the resolution order from `req-web-panel-entity-resolution-order`, dispatches between the deep-link and fallback paths, returns the result.

No consumer plugin re-implements these helpers. Consumer plugins migrate any local equivalents to import from this canonical module; the per-plugin migration steps live in each consumer plugin's spec.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-entity-resolution-helper-1 | Canonical Module | Implemented | The helpers live at `tap_web/panels/entity_resolution.py`; no consumer plugin re-implements them. | |
| req-web-panel-entity-resolution-helper-2 | Helper Is Narrow | Implemented | The helper executes Gryphon queries; it does not construct them from disassembled config fields, parse them, or wrap them. The panel author owns the query and its semantics. | |
| req-web-panel-entity-resolution-helper-3 | Stable Return Shape | Implemented | `_lookup_by_entity_id` returns an envelope node dict or `None`; `_run_fallback_query` returns `(nodes, count)`; neither raises on "not found." Transient Gryphon errors raise. | |
| req-web-panel-entity-resolution-helper-4 | Orchestrator Path Dispatch | Implemented | `resolve_entity` reads the URL var first and runs the configured fallback query only when the URL var is empty. The orchestrator signature does not change as new fallback shapes appear — because the fallback shape IS a Gryphon query, Gryphon's evolution covers it. | |

### EntityResolution Dataclass
----
RID: `req-web-panel-entity-resolution-result-shape`
Status: `Implemented`

The result shape:

```python
@dataclass
class EntityResolution:
    entity_id: str                          # the entity_id that was resolved (or attempted)
    var_name: str                           # which URL var name was read
    node: dict[str, Any] | None             # the on-grid node (Gryphon envelope shape), or None on failure
    error: str | None                       # polished user-readable error, or None on success
    used_fallback: bool = False             # True iff the fallback path won
    fallback_description: str | None = None # the human-readable rationale from config, propagated for banner/errors
    fallback_count: int | None = None       # row count from the fallback query; None for deep-link or no-fallback paths

    @property
    def ok(self) -> bool:
        return self.node is not None and self.error is None
```

The dataclass MUST NOT grow consumer-specific fields. Consumer-specific derived state lives on the consumer panel's context dict, not on `EntityResolution`. This keeps the result shape stable across panel types.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-entity-resolution-result-shape-1 | Stable Fields | Implemented | The seven fields + `ok` property listed above are the entire public surface; new fields require this spec to bump. | |
| req-web-panel-entity-resolution-result-shape-2 | No Consumer Coupling | Implemented | The dataclass does not carry consumer-specific derived state. Consumers derive that downstream from `node`. | |

### Template Surface Conventions
----
RID: `req-web-panel-entity-resolution-template`
Status: `Implemented`

Consumer panels MUST propagate at minimum these fields from their `EntityResolution` to template context:

- `used_fallback` (bool)
- `fallback_description` (str | None)
- `entity_id` (str)
- `var_name` (str)

And render a fallback banner when `used_fallback` is True. **The canonical banner markup is the
shared partial `tap_web/templates/tap_web/partials/fallback_banner.html`** (styled by
`.tap-fallback-banner` in the globally-loaded `panels.css`); consumers `{% include %}` it —
optionally passing a consumer-specific `fallback_lead` sentence — rather than authoring their own
banner markup, so a banner improvement lands on every consumer at once. The banner SHOULD identify:

- That the panel auto-resolved (not a deep link)
- Which URL var name would override the fallback (so users know how to deep-link to a specific entity)
- The `fallback_description` text (so users know what the fallback picked and why)
- The entity_id that was picked (so users can copy it into a stable bookmark)

Multi-entity panels render one banner row per role that fell back, or a combined banner that names which entities came from fallback and why.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-entity-resolution-template-1 | used_fallback Propagated | Implemented | The bool reaches the template context unchanged. | |
| req-web-panel-entity-resolution-template-2 | Banner When True | Implemented | The template includes a visible banner with the fallback `description` when `used_fallback` is True. | |
| req-web-panel-entity-resolution-template-3 | Banner Identifies Override Path | Implemented | The banner tells the user which URL var to use to deep-link to a specific entity. | |

### Polished Error States
----
RID: `req-web-panel-entity-resolution-errors`
Status: `Implemented`

Five failure phases, each with a distinct `error` message on the `EntityResolution`:

| Phase | When | Error message shape |
| --- | --- | --- |
| `source` | No URL var set, no `fallback` configured | "No entity specified. Expected page variable '<var_name>' in the URL." |
| `load` (URL miss) | URL var supplied, entity_id not found on the grid | "Entity not found for entity_id '<id>'." |
| `load` (fallback empty) | Fallback query returned zero rows | "Fallback query returned no entities yet — <fallback_description>. Verify the underlying source has emitted at least one matching entity." |
| `load` (fallback ambiguous) | Fallback query returned two or more rows | "Fallback ambiguous: query returned <N> entities — <fallback_description>. Refine the query (add `ORDER BY ... LIMIT 1` or tighten `WHERE`)." |
| `load` (transient) | Gryphon raised | "Entity lookup failed: <exc>" or "Fallback query failed: <exc>" — logged with a stable short-id for grep-ability |

Templates SHOULD show the error phase as a small `[load]` tag adjacent to the error message so support / debugging conversations can quickly point at the failure layer.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-entity-resolution-errors-1 | Distinct Per Phase | Implemented | Each failure phase produces a distinguishable error string; templates can pattern-match. | |
| req-web-panel-entity-resolution-errors-2 | Echo The Inputs | Implemented | The error string includes the entity_id, var_name, or fallback_description that was attempted, so users can fix the URL or config. | |
| req-web-panel-entity-resolution-errors-3 | Short-Id Logging | Implemented | Transient (exception) failures log with a stable short-id so they're greppable in container logs. | |

### Empty-State Distinction
----
RID: `req-web-panel-entity-resolution-empty-state`
Status: `Implemented`

The resolver returns a polished error for three structurally different cases — empty grid (`fallback_count == 0`), ambiguous fallback (`fallback_count >= 2`), and broken/missing inputs (`fallback_count is None` — URL miss, no var configured, or transient Gryphon exception). The `EntityResolution` dataclass exposes `fallback_count` precisely so consumer panels can tell these apart and render them differently.

Single-entity panels SHOULD render the empty case as **informational**, not as an error, because an empty grid on a freshly-stood-up environment is an expected starting condition — not a failure. The other two cases stay as error renderings: ambiguity is a config bug the author needs to fix; broken inputs are something genuinely wrong.

A reasonable mapping:

| `resolution.error is not None` AND … | UI tone |
| --- | --- |
| `fallback_count == 0` | Informational empty state — gray/blue panel, an icon like `📭`, a guidance message that names how to populate the source (e.g., "Run the samsite collector to land the first OSCAL SSP"). The resolver's default `error` text can be displayed verbatim or overridden by panel-specific guidance. |
| `fallback_count >= 2` | Error panel — red, "Refine the fallback query in panel config" guidance. This is a config bug; surface it loudly. |
| `fallback_count is None` (URL miss / no fallback configured / transient exception) | Error panel — red. The phase distinction is already in `resolution.error`. |

Panels MAY override the resolver's default empty-state message with panel-specific actionable guidance (e.g., "No OSCAL SSP on the grid yet — once the samsite collector runs nightly, the latest SSP will appear here"). The resolver's `fallback_description` remains visible so the user still sees what was searched for.

For multi-entity panels, the empty-state distinction interacts with [Required vs Degraded](#multi-entity-panels): a `degraded` role with `fallback_count == 0` likely renders as an informational note inline with the rest of the panel; a `required` role with `fallback_count == 0` blocks the panel rendering entirely and surfaces as the panel-level empty state.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-entity-resolution-empty-state-1 | fallback_count Distinguishes Cases | Implemented | Panels checking `resolution.error` MUST also inspect `resolution.fallback_count` before deciding whether to render error vs informational empty state. | All four consumer panels (ROSCALE SSP, ROSCALE POA&M, KSI scoreboard, VDR ingestion health) thread `fallback_count` from the resolution into template context; templates branch on it. |
| req-web-panel-entity-resolution-empty-state-2 | Empty Is Informational | Implemented | `fallback_count == 0` renders in an informational tone, not red/error styling. | All four panels render slate-blue `*-empty-state` blocks with a `📭` icon and panel-specific actionable guidance — distinct from the red `*-error-state` block used for URL miss / ambiguous / transient. |
| req-web-panel-entity-resolution-empty-state-3 | Ambiguous Stays Error | Implemented | `fallback_count >= 2` renders as an error — it's a config bug, not an expected state. | Templates check `fallback_count == 0` for the informational branch; everything else (URL miss, ambiguous, transient) falls through to the error styling. |
| req-web-panel-entity-resolution-empty-state-4 | fallback_description Preserved | Implemented | Even when the panel overrides the resolver's message, `fallback_description` MUST remain visible so users know what the panel was looking for. | Each panel's empty-state block surfaces `{{ fallback_description }}` inline alongside the panel-specific actionable guidance. |

### Multi-Entity Panels
----
RID: `req-web-panel-entity-resolution-multi`
Status: `Implemented`

Some panels need more than one entity to render (e.g., the FedRAMP 20x KSI scoreboard joins the latest SSP and the latest POA&M). For these:

- Each entity has a **role** name that prefixes its config keys: `<role>_entity_id_var`, and the role appears as a sub-block under `fallback` (`fallback.<role>`) carrying its own `query` + `description`.
- Each entity is resolved independently. One can fall back while another deep-links; one can miss while another succeeds.
- The panel decides per role whether the entity is **required** (missing it is a hard error) or **degraded** (missing it lets the panel render in a reduced mode and surface a warning).
- Each role's `used_fallback` and `fallback_description` propagate separately to context (e.g. `<role-a>_used_fallback`, `<role-a>_fallback_description`) so the template can show a combined banner that names which entities came from fallback and why.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-entity-resolution-multi-1 | Per-Role Config | Implemented | The config carries one `<role>_entity_id_var` per role plus a `fallback` block with per-role sub-blocks each holding `query` + `description`. | |
| req-web-panel-entity-resolution-multi-2 | Independent Resolution | Implemented | Each role is resolved through `resolve_entity` separately; one role's failure does not short-circuit the other. | |
| req-web-panel-entity-resolution-multi-3 | Required vs Degraded | Implemented | The panel declares per-role whether absence is a hard fail or a degraded render; both modes are valid. | |

### Relative (Context-Derived) Resolution
----
RID: `req-web-panel-entity-resolution-relative`
Status: `Proposed`

The two implemented paths resolve a panel's entity either by a direct `entity_id` of *its own type* in the URL, or by a static fallback query that takes no input. Neither lets a generic, droppable panel resolve an entity **relative to the entity the host page is about**. A page keyed by `?<context_var>=<X>` whose panel wants a *related* entity Y — reachable from X by a graph hop — has no path: the URL carries X's id (often a different type), and the static fallback query cannot see X.

Relative resolution adds that path. The panel declares a **context variable** (the URL var holding the id of the entity the page is about) and a **parameterized Gryphon traversal** that, bound to that id, returns the target. It is the `fallback` mechanism (`req-web-panel-entity-resolution-config`) with exactly one difference: the query is executed with `{"context_id": <url value>}` instead of `{}`. Everything else — author owns the query, `LIMIT`/`ORDER BY` shape *is* the strategy, the helper neither parses nor wraps it, count semantics (0 → empty, 1 → resolved, ≥2 → ambiguous) — is identical.

**Config shape (single-entity):**

```json
{
  "entity_id_var": "<target-url-var>",
  "relative": {
    "context_var": "<url-var-holding-the-context-entity-id>",
    "query": "MATCH (ctx) WHERE ctx.entity_id = $context_id MATCH (ctx)-[:<EDGE_TYPE>]->(t:<target_type>) RETURN t ORDER BY ... LIMIT 1",
    "description": "<human-readable rationale: what relationship this traverses and why>"
  }
}
```

**Binding contract.** The helper binds exactly one parameter — `$context_id` — to `request.GET[context_var]` (whitespace-stripped). The name is fixed so the contract is explicit and the author references it in the `WHERE` clause; the author owns all other query structure. The helper does not inject the hop, the label, or the ordering — the traversal is wholly the author's, exactly as with `fallback`.

**Resolution order (inserts into `req-web-panel-entity-resolution-order`).** Per role:

1. **Direct URL deep link** (`entity_id_var` present, non-empty) — wins, unchanged. A bookmarked target id always reproduces a specific view.
2. **Relative resolution** — if `relative` is configured AND `relative.context_var` is present + non-empty in the URL: bind `$context_id`, run the traversal. One row → `EntityResolution(node=<t>, used_relative=True, context_entity_id=<X>)`. Zero rows → polished "no related entity — <description>" empty state. Two-or-more → polished "relative resolution ambiguous: N entities — <description>" error (author adds `ORDER BY … LIMIT 1` or tightens the hop).
3. **Static fallback** — if `fallback` is configured and neither of the above produced an entity (target var empty AND no usable context). Unchanged.
4. **Error** — "no entity specified," unchanged.

Rationale: most-specific-wins. An explicit target id pins a bookmark; a present context derives from *what the page is about*; the static fallback is the always-render-something default. A page may legitimately configure both `relative` (works when opened in context) and `fallback` (works when opened bare).

**Multiplicity is single — collections are out of scope.** Relative resolution resolves exactly ONE target, like fallback. A context entity related to *many* targets that all matter (e.g. a run that imported several batches) is a **collection**, rendered by a list-capable surface (the shared card looped), not a single-entity panel. "The one related target" is expressed with `ORDER BY … LIMIT 1`; a genuine 1:N where every element matters stays a list concern. This is exactly why the CARES run page renders its batches inline rather than via a single dropped panel — and why this seam does not, by itself, replace that rendering.

**Graph-edge prerequisite.** Relative resolution traverses Gryphon **edges**, not typed-row JSON fields. The relationship MUST exist as a first-class edge on the grid. Where a relationship is currently carried in a JSON field, promoting it to an edge is a prerequisite — and is independently desirable (queryable, graph-visible, history-bearing). The promotion lives in the relationship-owner's spec, not here. **Concretely for the motivating case:** the canonical producer→batch edge — `req-grid-edge-produced-batch` (`tap_grid/specs/spec-grid-edge.md`): `<producer> --PRODUCED_BATCH--> Batch` carrying a `disposition` property ∈ {`imported`, `skipped`} — **is now built (`Implemented`).** The CARES collector runtime creates these edges at terminal state and the former `CollectionJob.grift_batches` JSONField has been removed. So the prerequisite this requirement named is **satisfied**: a batch-summary panel dropped on a run page can now traverse `PRODUCED_BATCH` for "the batch this run produced." Relative resolution itself remains unbuilt — it is no longer *blocked*, just not yet implemented; this requirement was a second consumer that helped motivate that edge.

**Gryphon dependency.** The traversal needs parameterized multi-hop edge matching (`MATCH (a) WHERE a.entity_id = $p MATCH (a)-[:T]->(b) …`). Gryphon supports this today (Gridkin `multi_hop` / `multi_edge` / `edge_type_scan`). When this requirement is built, a Gridkin scenario MUST cover the parameterized-context traversal shape (bound `$context_id` + one hop + `ORDER BY … LIMIT 1`, and the edge-property filter form `-[r:T]->()  WHERE r.<prop> = "<value>"`), per the Gryphon-failures-not-okay discipline.

**`EntityResolution` additions.** Two generic (non-consumer) fields parallel to the fallback pair: `used_relative: bool` and `context_entity_id: str | None` (the id bound as `$context_id`). When this graduates, `req-web-panel-entity-resolution-result-shape` bumps to include them. Templates surface a banner analogous to the fallback banner — "Showing the <description> for <context_entity_id>" — and a `context_var`-based hint for how to deep-link the target directly.

**Helper change.** `resolve_entity` gains the relative branch between deep-link and fallback. `_run_fallback_query(query)` generalizes to run with a params dict (`fallback` passes `{}`; relative passes `{"context_id": <id>}`) — or a sibling `_run_relative_query(query, context_id)`. Narrowness preserved: still "run the author's query, report `(nodes, count)`," no parsing or wrapping.

**Composition with `variable_map`** (`req-web-panel-inputs`, Proposed). The two are orthogonal and compose: `variable_map` moves a *value* from page to panel-local input; relative resolution turns a context *id* into a *related entity* via traversal. Once page→panel input mapping lands, `context_var` can be fed from a page variable rather than read directly from `request.GET`, the same migration `entity_id_var` will make. This requirement does not block on `variable_map`; it reads the URL directly in the interim, exactly as the implemented paths do.

**Concrete example (illustrative — not contract).** A `batch-summary` panel dropped on a collection-run page (`?entity_id=<CollectionJob>`), resolving the batch the run imported:

```json
{
  "entity_id_var": "batch_entity_id",
  "relative": {
    "context_var": "entity_id",
    "query": "MATCH (j) WHERE j.entity_id = $context_id MATCH (j)-[r:PRODUCED_BATCH]->(b:batch) WHERE r.disposition = \"imported\" RETURN b ORDER BY b.data.started_at DESC LIMIT 1",
    "description": "The most-recent batch this collection run imported (PRODUCED_BATCH, disposition=imported)."
  }
}
```

This config is inert until `PRODUCED_BATCH` edges exist (see the graph-edge prerequisite). A run that imported *multiple* batches resolves only the most recent here by `LIMIT 1`; showing all of them remains the inline-card (collection) concern.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-entity-resolution-relative-1 | Config Fields Required | Proposed | When a `relative` block is present, `context_var`, `query`, and `description` MUST all be set; a partial block is a config error. The platform bakes in no default context var, edge type, or query. | |
| req-web-panel-entity-resolution-relative-2 | Single Fixed Bound Param | Proposed | The helper binds exactly `$context_id` to `request.GET[context_var]` and runs the query verbatim; it does not inject hops, labels, ordering, or any other parameter. | |
| req-web-panel-entity-resolution-relative-3 | Order Placement | Proposed | Relative resolution runs after a direct URL deep link and before the static fallback; an explicit target id still wins, and a configured static fallback still fires when there is no usable context. | |
| req-web-panel-entity-resolution-relative-4 | Count Semantics Reused | Proposed | 0 / 1 / ≥2 rows map to empty / resolved / ambiguous exactly as for `fallback`; `fallback_count` (or an equivalent) carries the count so panels render informational-empty vs error per `req-web-panel-entity-resolution-empty-state`. | |
| req-web-panel-entity-resolution-relative-5 | Single Target Only | Proposed | Relative resolution resolves at most one target. Rendering a 1:N relationship where all targets matter is a collection concern, not this requirement. | |
| req-web-panel-entity-resolution-relative-6 | Edge Prerequisite Stated | Proposed | The traversed relationship must be a first-class grid edge. For the producer→batch case this is `req-grid-edge-produced-batch` — now `Implemented` (edges created by the CARES runtime; `CollectionJob.grift_batches` removed). The prerequisite is satisfied; this requirement is no longer blocked, only unbuilt. | |
| req-web-panel-entity-resolution-relative-7 | Result Fields + Banner | Proposed | `EntityResolution` exposes `used_relative` + `context_entity_id`; templates show a banner naming the relationship description and the context entity, and how to deep-link the target directly. | |
| req-web-panel-entity-resolution-relative-8 | Gridkin Coverage | Proposed | A Gridkin scenario covers the parameterized-context single-hop traversal (bound `$context_id`, `ORDER BY … LIMIT 1`, and the edge-property-filtered form) before this ships. | |

### Test Coverage Requirements
----
RID: `req-web-panel-entity-resolution-tests`
Status: `Implemented`

Each consumer panel MUST have unit tests (no Django/DB setup required) covering:

- **Explicit URL deep link wins over fallback** — both URL var and fallback configured; only `_lookup_by_entity_id` is called.
- **Fallback fires when URL var empty** — URL var absent, fallback configured; `_run_fallback_query` is called and `used_fallback` is True.
- **No URL var, no fallback** — polished "no entity specified" error.
- **Fallback query returned zero rows** — polished "fallback query returned no entities yet — <description>" error.
- **Fallback query returned two or more rows** — polished "fallback ambiguous" error. (The panel author wrote `LIMIT 2` or higher to detect this; for `LIMIT 1` queries this path is unreachable and the test is skipped.)

Tests mock the two lookup helpers (`_lookup_by_entity_id`, `_run_fallback_query`) at the importing module's path, not at `tap_web.panels.entity_resolution`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-entity-resolution-tests-1 | Per-Consumer Coverage | Implemented | Each consumer panel has the resolution-path tests listed above (skipping fallback-ambiguous for panels whose fallback query uses `LIMIT 1`). | |
| req-web-panel-entity-resolution-tests-2 | Query-Shape Tests In Helper Home | Implemented | Helper-home tests at `tap_web/tests/test_panel_entity_resolution.py` verify the two lookup helpers issue the right Gryphon shapes (labelless `MATCH (n) WHERE n.entity_id = $eid` for the deep-link; panel-supplied query verbatim for the fallback) and unpack envelope vs. `(nodes, count)` results correctly. The engine's actual sort and limit correctness is exercised by the Gryphon Gridkin suite, not by these tests. | |

## Future Work

Not in v0 scope but worth naming as future seams:

- **Fallback query config-time validation.** Today the helper only discovers a malformed Gryphon query at request time. A registration-time check (parse the query when the panel registers; surface parse errors at boot) catches typos and field-name drift earlier. Worth adding once Gryphon's parser exposes a "parse-only" surface.
- **Multi-step / chained fallback (A → B → C).** v0 supports exactly one fallback query. A panel wanting "try the latest SSP from this collector; if that's empty fall back to a generic placeholder; if THAT's empty render a setup-guidance state" needs three queries chained with priority. The contract would be a `fallback` *list* instead of a single block, evaluated top-to-bottom until one returns ≥1 row. Not on the critical path — once Gryphon adds `UNION` (wishlist F2), panel authors can express priority-cascading in a single query; that's the cheaper unlock to wait for. Promote this seam if a real consumer hits the "I need different fallbacks per condition" shape that `UNION` can't express.
- **Edit-mode resolution.** The current resolution is read-only. If a panel ever needs to *write* to the resolved entity, the helper grows a `for_edit=True` mode that locks or branches per the data model's edit semantics. Out of scope.
- **History timeline panel.** ~~A panel that resolves *N* versions rather than just the latest, for drift / regression visualization.~~ **Graduated** → [`spec-web-panel-sequence-navigation-v0`](spec-web-panel-sequence-navigation-v0.md). The sequence-nav panel resolves the full ordered sequence (a newest-first query, no `LIMIT 1`) and renders Older/Newer + position, reusing this module's `_run_fallback_query`. It is the deliberate companion to `resolve_entity`: that picks *which* entity is current, sequence-nav reports *where in the sequence* it sits.
