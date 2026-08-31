# Panel Data Export Spec

## Philosophy

A panel is, at the end of the day, a server-built bundle of JSON that some client
renderer turns into pixels. Today the only way to see that JSON is to load the page
in a browser and reach into the rendered client (Cytoscape's in-memory graph, a
table's DOM, …). That conflates three different questions — *what did the server
emit?*, *what did the client render?*, and *is the browser showing stale state?* —
and it makes headless inspection (by a developer, a test, a CI check, or an agent)
slow and unreliable.

Panel Data Export gives a panel's server-side render data a **first-class, headless,
JSON form**: the exact data the panel produced, available without a browser, off the
same code path the live panel uses. It is panel-type-agnostic — a `tap_web` core
capability — because `tap_web` owns the panel process and every present and future
viz system (graphs today; whatever complex surfaces come later) sits on top of it.
The first concrete consumer is `tap_viz`'s graph panel.

This is the panel analog of the Gryphon introspection tools (`explain_gryphon_raw`,
Gridkin snapshots): a structured, verifiable view of a thing that otherwise only
exists at runtime. The guiding rule is **structure from JSON, aesthetics from the
rendered view** — the export answers "is the data/wiring right?", not "does it look
good?".

## Goals

|    |                  |                                                                                                      |
| :---: | ---           | ---                                                                                                  |
| 1. | Headless        | A panel's render data is obtainable as JSON with no browser and no client runtime. |
| 2. | Faithful        | The export is byte-for-intent identical to what the live panel render produced — same code path, never a parallel serializer that can drift. |
| 3. | Panel-agnostic  | The capability lives in `tap_web` and works for any panel type; each panel type contributes its own data shape. |
| 4. | Input-aware     | A panel can be exported as it would render under a given set of inputs (the same inputs the live render consumes). |
| 5. | Schema'd        | The output is a versioned envelope with a published JSON Schema, validated at the boundary. |
| 6. | API-ready       | The serializer is shaped so a future read-only API door can expose the same output, without redesign. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-panel-data-export-capability | [Headless Export Capability](#headless-export-capability) | Proposed | `tap_web` core: a panel's server render data is serializable to JSON outside the HTMX render path |
| req-web-panel-data-export-fidelity | [Same-Path Fidelity](#same-path-fidelity) | Proposed | The export reuses the panel type's live data path; no parallel serializer |
| req-web-panel-data-export-inputs | [Input-Parameterized Export](#input-parameterized-export) | Proposed | Export accepts the same inputs the live panel consumes |
| req-web-panel-data-export-envelope | [Versioned Envelope + Schema](#versioned-envelope--schema) | Proposed | Output is a versioned envelope validated against a published JSON Schema |
| req-web-panel-data-export-command | [Dev Command Surface](#dev-command-surface) | Proposed | A management command emits a panel's export JSON (the v0 surface) |
| req-web-panel-data-export-graph | [Graph Panel Shape (tap_viz)](#graph-panel-shape-tap_viz) | Proposed | The graph panel contributes its nodes/edges/projection export shape — the immediate consumer |
| req-web-panel-data-export-api.future | [Future API Door](#future-api-door) | Backlog | A read-only, versioned API surface over the same serializer; deliberately deferred |

## Invariants

- **One source of truth.** The export and the live render derive from the same
  server code path. An export that can disagree with what renders is worse than no
  export, because it lies with authority.
- **Read-only.** Exporting a panel never mutates grid state. It is a projection of
  existing data through the panel's render logic.
- **Pre-layout, server-truth scope.** The export is the *data + display hints* the
  server emits. Client-computed geometry (node positions, z-order, resolved
  computed styles) is explicitly out of scope — that lives in the rendered client
  and is a separate introspection surface (a future runtime state hook), not this
  one. Conflating them would make the API promise something the server cannot
  produce.

---

### Headless Export Capability
----
RID: `req-web-panel-data-export-capability`
Status: `Proposed`

`tap_web` exposes a core function that, given a panel and a request-like input
context, returns the panel's server-built render data as structured JSON, without
going through the HTMX fragment render or any browser.

#### Status Details
This is the foundational requirement. It generalizes the existing panel render path
(panel type → `get_view_context(panel, request)`) into a reusable, headless,
serialized form owned by `tap_web` core rather than any single panel type or viz
plugin.

#### Implementation
- A core helper (e.g. `tap_web.panel_export.export_panel_data(panel, *, inputs)`)
  resolves the panel's type from its `view` field (per `req-web-panel-registry` /
  `req-web-panel-obj`) and invokes that type's existing server-side data build.
- The panel type's `get_view_context(cls, panel, request)` is the canonical build.
  The export either (a) parses the JSON payloads already present in that context
  (e.g. the graph panel's `graph_nodes_json` / `graph_edges_json` /
  `graph_projection_json`), or (b) the panel type exposes a sibling that returns the
  same data that `get_view_context` hands to `json_script` for embedding. Either way
  the *data* is produced by exactly one code path (see Same-Path Fidelity).
- The function returns Python objects (dict/list), not pre-rendered strings, so
  every surface (command now, API later) can serialize them as it sees fit.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-data-export-capability-1 | Core Helper Exists | Proposed | `tap_web` provides a documented function that returns a panel's render data as structured JSON given a panel + inputs. | Lives in `tap_web`, not a panel-type or viz plugin. |
| req-web-panel-data-export-capability-2 | No Browser Required | Proposed | The export runs server-side with no client runtime and no HTMX fragment render. | |
| req-web-panel-data-export-capability-3 | Panel-Type Dispatch | Proposed | The capability resolves the panel type via `view` and delegates the data shape to that type. | Reuses the panel registry. |

#### Future
Panel types that have no meaningful render data (pure static panels) may return an
empty payload; the envelope still carries panel metadata.


### Same-Path Fidelity
----
RID: `req-web-panel-data-export-fidelity`
Status: `Proposed`

The export MUST derive its data from the same server code path that the live panel
render uses. A second, export-only serializer is prohibited.

#### Status Details
This is the load-bearing invariant. The entire value of the export is that it tells
the truth about what renders; a divergent path silently reintroduces the "is this
real?" problem the export exists to kill.

#### Implementation
- The export calls the panel type's `get_view_context` (or a factored-out data
  method that `get_view_context` itself calls) — never a reimplementation of the
  search execution + display resolution.
- If a panel type needs to factor its data build out of `get_view_context` to make
  it cleanly serializable, the refactor must keep `get_view_context` as a thin
  wrapper over that same method, so the render path and the export path remain one.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-data-export-fidelity-1 | Single Build Path | Proposed | Live render and export obtain panel data from one shared function; no parallel serializer exists. | |
| req-web-panel-data-export-fidelity-2 | Drift Test | Proposed | A test asserts the export payload matches the data embedded by the live render for a representative panel. | Guards against silent divergence. |

#### Future
If a panel type's render context grows render-only fields (purely presentational
strings), the spec may define a documented subset that the export carries, but the
data fields must still come from the shared path.


### Input-Parameterized Export
----
RID: `req-web-panel-data-export-inputs`
Status: `Proposed`

A panel's output depends on its inputs (e.g. a context `entity_id`). The export
accepts those inputs and produces the panel data as it would render under them.

#### Status Details
The live render reads inputs from the request (`request.GET`, panel inputs per
`req-web-panel-inputs`). The export must accept an equivalent input mapping so a
caller can export a panel in a specific context, not just its input-free default.

#### Implementation
- The export accepts an `inputs` mapping and constructs the request-like object the
  panel type expects (or passes inputs through the same resolution the live path
  uses).
- With no inputs supplied, the export produces the panel's default/no-input render
  data.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-data-export-inputs-1 | Inputs Accepted | Proposed | The export accepts an inputs mapping mirroring the live render's inputs. | |
| req-web-panel-data-export-inputs-2 | Default Without Inputs | Proposed | With no inputs, the export returns the panel's no-input render data. | |


### Versioned Envelope + Schema
----
RID: `req-web-panel-data-export-envelope`
Status: `Proposed`

The export output is a versioned envelope: panel identity + metadata, the panel
type, a schema version, and a panel-type-specific `payload`. The envelope has a
published JSON Schema and is validated at the boundary.

#### Status Details
Per the project's "JSON formats need a schema" rule, this is a structured data
format and so requires a schema authored in the same change and validated on
produce. The envelope is panel-type-agnostic; the `payload` shape is contributed by
each panel type (graph panel shape in `req-web-panel-data-export-graph`).

#### Implementation
- Envelope (illustrative, not final):
  ```json
  {
    "schema": "tap.panel-export/v0",
    "panel": { "entity_id": "...", "slug": "...", "name": "...", "view": "..." },
    "panel_type": "graph",
    "inputs": { },
    "warnings": [ ],
    "payload": { }
  }
  ```
- The JSON Schema lives alongside the producing code (e.g.
  `tap_web/schemas/panel-export.schema.json`) and validates the envelope; per-type
  `payload` schemas are referenced/contributed by the owning panel type.
- `warnings` carries non-fatal issues surfaced during the data build (e.g. nesting
  resolution warnings) so a headless consumer sees them without a console.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-data-export-envelope-1 | Versioned Envelope | Proposed | Output carries a schema/version tag, panel metadata, panel type, inputs echo, and a payload. | |
| req-web-panel-data-export-envelope-2 | Published Schema | Proposed | A JSON Schema for the envelope is authored in the same change and validated on produce. | |
| req-web-panel-data-export-envelope-3 | Warnings Surfaced | Proposed | Non-fatal build warnings are carried in the envelope, not just logged. | |


### Dev Command Surface
----
RID: `req-web-panel-data-export-command`
Status: `Proposed`

The v0 surface is a management command that prints a panel's export envelope to
stdout, addressable by panel UUID or slug, with optional inputs.

#### Status Details
A dev/CI/agent affordance — fast, cacheless, scriptable, no browser. This is the
only surface built in v0; the API door is deferred (see Future API Door).

#### Implementation
- `manage.py export_panel_data <panel-uuid-or-slug> [--input key=value ...] [--pretty]`
  resolves the panel, calls the core export helper, validates the envelope, and
  writes JSON to stdout.
- Resolution mirrors the panel URL convention (`<slug>--<uuid>`): UUID is
  authoritative, slug is convenience.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-data-export-command-1 | Command Emits Envelope | Proposed | The command writes a validated export envelope as JSON to stdout. | |
| req-web-panel-data-export-command-2 | Panel Addressing | Proposed | The command resolves a panel by UUID (authoritative) or slug. | |
| req-web-panel-data-export-command-3 | Inputs Pass-Through | Proposed | `--input` values reach the export as panel inputs. | |

#### Future
A `--diff` mode that compares the current export against a saved snapshot would make
this a regression guard for board/projection changes (the panel analog of Gridkin
snapshot tests).


### Graph Panel Shape (tap_viz)
----
RID: `req-web-panel-data-export-graph`
Status: `Proposed`

The `tap_viz` graph panel contributes its export `payload`: the nodes and edges it
emits (GRIFT extended-layer format, including resolved display hints) plus the
serialized projection definition when projection-hosted. This is the immediate
consumer that motivated the capability.

#### Status Details
The graph panel already builds exactly this in `get_view_context`
(`graph_nodes_json`, `graph_edges_json`, `graph_projection_json`). The graph panel's
contribution to the export is to expose that same data through the core export
helper — not to recompute it.

#### Implementation
- Graph `payload` shape (illustrative):
  ```json
  {
    "nodes": [ { "entity_id": "...", "entity_type": "...", "name": "...",
                 "display": { "icon_url": "...", "fill_color": "...", "shape": "...",
                              "label": {} }, "dimensions": {}, "tags": {} } ],
    "edges": [ { "id": "...", "source": "...", "target": "...",
                 "edge_type": "...", "properties": {} } ],
    "projection": { }
  }
  ```
- Node/edge entries are the GRIFT extended-layer envelopes the search produced, so a
  consumer sees exactly the `icon_url` / `fill_color` / `shape` / `label` / parent
  hints the client renderer receives.
- The `projection` field carries the serialized projection definition for
  projection-hosted panels (null otherwise), so a consumer can see the elevation /
  layout / arrangement wiring without the browser.
- Out of scope (per the pre-layout invariant): final positions, z-order, scope-box
  geometry, and computed styles — those are produced by the client runtime.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-data-export-graph-1 | Nodes + Edges Payload | Proposed | The graph payload carries nodes and edges with resolved display hints, from the live build path. | |
| req-web-panel-data-export-graph-2 | Projection Included | Proposed | The serialized projection definition is included for projection-hosted panels. | |
| req-web-panel-data-export-graph-3 | No Client Geometry | Proposed | The payload contains no client-computed positions/z-order/computed styles. | Those belong to a future runtime-state surface. |

#### Future
A companion client-side runtime-state hook (e.g. `window.__tapGraphState()` in
DEBUG) would cover the out-of-scope geometry for the cases where the rendered layout
itself is under inspection. Out of scope for this spec; noted as the complementary
surface.


### Future API Door
----
RID: `req-web-panel-data-export-api.future`
Status: `Backlog`

A read-only API endpoint over the same export serializer, so the panel export is
reachable programmatically (other tools, eventually sandboxed satellite/outpost
agents consuming structured board state). Deliberately deferred — built when there
is a consumer, not speculatively.

#### Status Details
Captured now only to keep the v0 design API-ready: the core helper returns plain
objects and the envelope is schema'd and versioned, so wrapping it in an endpoint
later is additive, not a redesign. No public surface is built in v0.

#### Implementation (when undertaken)
- Versioned under `tap_api` (`/api/v1/...`), owned by `tap_api`'s versioning/auth, not
  a plugin-namespaced router (the capability is core, applicable to any panel).
- Read-only; standard authentication and authorization.
- Addresses a panel by entity UUID; accepts inputs as query/body params; returns the
  same validated envelope the command produces.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-panel-data-export-api.future-1 | Deferred, Not Built | Backlog | No API surface is implemented in v0; the serializer is merely kept API-ready. | |
| req-web-panel-data-export-api.future-2 | Same Serializer | Backlog | When built, the endpoint reuses the core export helper + envelope; no third serializer. | |

#### Future
Define auth scope, pagination/size limits for large boards, and whether post-layout
runtime state is ever exposable server-side (likely not) when this is picked up.

---

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed |  |
| Approved for Development | Requirement is accepted and ready to be implemented |
| In Development |  |
| Implemented |  |
| Verified |  |
| Refactoring |  |
| Deprecating |  |
| Deprecated | Not part of the current architecture and should not be implemented |

## RID Format

`req-<application>-<specification>-<feature>-<sub-feature>`

## Requirements Format

`RID: \`...\``
`Status: \`...\``

| Sub-Sections | (as needed) |
| --- | --- |
| Status Details |  |
| Implementation |  |
| Development |  |
| Acceptance Criteria |  |
| Future |  |
