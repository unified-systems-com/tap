---
title: TAP in Two Pages
audience:
  - adopter
  - developer
  - llm
status: draft
---

# TAP in Two Pages

Page one is the **why** — the ideas, no implementation. Page two is the **how** —
the moving parts and where each one lives. Written for a human and their AI
assistant together: every concept on page two links to the spec that defines it,
so an assistant can go from this doc to ground truth without guessing.

---

## Page 1 — The Why

**TAP is The Analogy Platform.**  
The systems we are responsible for — cloud
accounts, deploy pipelines, device fleets, data flows, vendor webs, the
organization itself — long ago outgrew any one person's head. TAP's answer is to build a **working analogy** of
the real system: a model complete enough to *see*, *query*, *check*, and
*explain*, and live enough to stay true as the real system changes. Every
meaningful thing becomes a **node**, every relationship becomes an **edge**, and
the platform's job is to host that model, keep it honest, and put people and AI
assistants to work on it.

**The Grid is the model itself.**   
The grid is TAP's central concept, and it's more than a directed graph — it's five things fused:

- **Graph Data Model** — the nodes and edges: what is true *now*;
- **Dimensions** — an extensible namespace system that can be applied to every node and edge 
  so one grid holds many context at once (an account's resources, a design vs configured vs observed, TAP's own backend page, panel, collector configurations.  Dimensions can be read a slice at a time (soon, we haven't built that yet).
- **Batches** - all changes to the grid state are batched, named, and referenceable thorughout the system.
- **History** — every prior state of nodes and edges, so the grid carries *how it came to be true*,
  not just what is, all referenced by the batch update which changed it;
- **Field-Level Information Provenance (FLIP)**: for every field on every node,
  which write is responsible for its current value, so every claim on the grid
  can answer *"says who?"*;


Everything else in the system exists to serve the grid: collectors feed it,
pages and panels present it, Gryphon queries it, plugins teach it new
vocabulary (and introduce new collectors, pages, panels, gryphon queries).

**All models are wrong, some models tell you why**  
Provenance is not an add-on; it is a constituent of the grid. "Why does the grid say this?" always
has a concrete answer — the data came from / was changed by this collector run, this import, this human, at this
time — and "what did it say before?" always has an answer. Whenever real
decisions ride on the model, this is the point, not a feature: you shall know the truth (and the history of the truth), and it shall set you free...well free-er.

**One world, no trapdoors.**  
The pages of the web UI, the panels on them, the
collectors, their schedules, the saved searches — all of it is *itself* modeled
on the grid, alongside the systems under observation. There is no second, hidden
data model for "the app." One vocabulary, one query surface, one provenance
story, one permission story — for the observed and the observer alike.

**Three players.**  
TAP is built for humans, code, and AI assistants as
co-operators. The grid describes itself: types publish their schemas and
capabilities, each instance carries a
[**keystone**](../tap_grid/specs/spec-grid-keystone.md) explaining what this
particular grid models and why, and operational procedures ship as
[**skills**](../specs/spec-ai-integration.md) an
assistant can drive. An AI landing in a TAP instance is expected to orient
itself by reading the grid — not by asking you to explain your own system to it.



---

## Page 2 — The How

Each part below names its owning spec first — that link is the contract; the
code implements it.

### Specs Driven Development (how TAP is built)

[spec.md](../specs/spec.md) — the spec of specs ·
[spec-dev-validation](../specs/spec-dev-validation.md)

TAP is spec-driven: every behavior has an owning **specification** with numbered
requirements (RIDs like `req-grid-flip-batch`) referenced from code comments,
tests, guards, and docs — so intent survives contact with implementation and
drift is detectable. The stated ambition: the specs should be sufficient to
*re-create the application from whole cloth* — a deliberate move beyond vibe
coding. CI enforces the culture mechanically: a **Validation Map** inventories
every validation surface, and guard suites fail the build when canon and code
disagree. The operating rule for any assistant working here: **before changing
behavior, read the owning spec** ([`specs/`](../specs/) for cross-cutting
concerns, [`<app>/specs/`](../tap_grid/specs/) per app). Above the specs sits
[`architecture.md`](../architecture.md) — the standing architectural contract
the specs elaborate.

### The data model (the grid in PostgreSQL)

The bet: graph capabilities on a plain SQL database — traversal, neighborhoods,
and visual projection, *with* ACID transactions, strong typing, boring backups,
and thirty years of operational maturity.

- **`Entity`** — [spec-grid-entity](../tap_grid/specs/spec-grid-entity.md). The
  spine, one table in ordinary PostgreSQL. Every domain object, whatever its
  type, has a row here carrying its identity (UUIDv7), its type slug, and its
  **dimensions** ([spec-grid-dimension](../tap_grid/specs/spec-grid-dimension.md)).
  Each row also remembers its originating **grid id** — the immutable UUID
  minted per install that gives grids identity for future moves and federation.
- **`BaseModel`** — [spec-grid-node](../tap_grid/specs/spec-grid-node.md). The
  abstract Django model every typed node inherits; typed tables hold each
  type's real fields. A type declares its `ENTITY_TYPE` slug, its field schema
  (used for CRUD validation and discovery), its icon, and its expected outbound
  edges. Plugin-owned types are namespaced `<plugin>__<type>` — e.g.
  `aws_core__aws_account`.
- **`Edge`** — [spec-grid-edge](../tap_grid/specs/spec-grid-edge.md). Directed,
  typed, first-class, in its own table. Edges are BaseModels too, so a
  relationship can carry fields, history, and provenance of its own.
- **Batches, FLIP, history** —
  [spec-grid-flip](../tap_grid/specs/spec-grid-flip.md),
  [spec-grid-history](../tap_grid/specs/spec-grid-history.md). Every write
  happens inside a **batch**; FLIP points each field at the batch responsible
  for its current value; history keeps the states each batch superseded. This
  is the mechanism behind page one's "says who?".
- **The service layer** —
  [spec-service-layer-boundary](../specs/spec-service-layer-boundary.md). The
  canonical read/write path: application code and plugins go through it, never
  raw ORM writes. It enforces schemas, capabilities (authorization), batch
  bookkeeping, and FLIP on every mutation; CI guards catch bypasses. Type
  schemas and capabilities are discoverable through the registry
  ([spec-grid-registry](../tap_grid/specs/spec-grid-registry.md)) — how an AI
  learns what exists without reading model code.
- **Gryphon** — the read-only graph query language, `MATCH`-style patterns
  compiled to SQL and executed under a least-privilege database role
  ([spec-grid-search](../tap_grid/specs/spec-grid-search.md),
  [spec-grid-security](../tap_grid/specs/spec-grid-security.md)):
  `MATCH (a)-[e]->(b) WHERE a.entity_id = $id RETURN a, e, b`. Saved queries
  live on the grid as `Search` nodes.
- **GRIFT** — [spec-grift-v0](../tap_grid/specs/spec-grift-v0.md),
  [spec-grid-import-grift](../tap_grid/specs/spec-grid-import-grift.md). The
  JSON interchange format: batches of nodes and edges for seeding,
  import/export, and portable subgraphs. Plugins ship their seed data as GRIFT
  bundles.

### Pages and panels (the web surface)

[spec-web-page](../tap_web/specs/spec-web-page.md) ·
[spec-web-panel](../tap_web/specs/spec-web-panel.md) ·
[spec-web-navigation](../tap_web/specs/spec-web-navigation.md)

A **`Page`** is a routable web page whose layout is a grid of panel slots; a
**`Panel`** is a data-display component — a template plus optional JS/CSS plus
config — rendered over HTMX. Both are nodes, which means the UI is *data*: a
plugin adds a dashboard by shipping a GRIFT bundle, not by patching the app.
Navigation is derived from discoverable pages; one page is designated the
landing page.

**tap_viz** supplies the graph visualization panels — Cytoscape-based
projections of grid neighborhoods with layouts, nesting, badges, and
arrangements ([spec-viz-projection](../tap_viz/specs/spec-viz-projection.md)).
This is the "see your system" surface.

### Collectors and the scheduler (data in, on cadence)

[spec-tap-cares-collector](../tap_cares/specs/spec-tap-cares-collector.md) ·
[spec-tap-cares-scheduler](../tap_cares/specs/spec-tap-cares-scheduler.md) ·
[spec-tap-cares-secrets](../tap_cares/specs/spec-tap-cares-secrets.md)

A **collector** fetches reality — a cloud API, a web endpoint, a tool's output,
an exported spreadsheet — and lands it on the grid as a GRIFT batch. The Python implementation is
a `CollectorBase` subclass registered under `scope:key`; the grid holds a
`Collector` node representing the capability, and every run is a
`CollectionJob` node recording status, messages, and the batch it produced.
Collectors declare self-tests (including credential health) so a misconfigured
one fails legibly before it runs. (Build one: the
[build-collector skill](../tap_grid/skills/build-collector/SKILL.md).)

A **`Schedule`** is an on-grid cron policy — "run this collector when cron
matches" — with each firing recorded as a `ScheduleFire` node. Because schedules
are nodes, a plugin seeds its collection cadence the same way it seeds anything
else: GRIFT.

Credentials collectors need are **secrets** — envelope files resolved through a
scoped subsystem, never committed, never logged, validated per-consumer.

### Plugins (how everything above is extensible)

[spec-tap-plugin-external-development](../tap_plugins/specs/spec-tap-plugin-external-development.md) ·
[spec-tap-plugin-manifest-v0](../tap_plugins/specs/spec-tap-plugin-manifest-v0.md)

A plugin is a Python package (its own git repo, installed by uv) that can bring:
node and edge **types**, **GRIFT seeds** (reference data, pages, panels,
schedules), **collectors**, **skills** for AI assistants, and its own tests —
declared in a `tap-plugin.toml` manifest and validated by the same admission
checker the platform runs (`manage.py validate_plugin`). Core ships the
substrate and deliberately speaks no domain language at all — every vocabulary
arrives as a plugin. Today's fleet happens to speak AWS, GitHub, sigstore, and
compliance frameworks; yours can speak whatever your systems speak. (Scaffold
one: the [new-plugin skill](../tap_plugins/skills/new-plugin/SKILL.md).)

**Boot profiles** ([`boot/*.boot.json`](../boot/),
[spec-tap-boot-v0](../specs/spec-tap-boot-v0.md)) declare what an instance
*is*: which plugins, from which sources at which pinned versions, seeded and
fired in what order. `manage.py boot --profile X` takes a fresh database to that
declared state — the same contract in dev and deployment. Harness profiles
(`core`/`core_dev`/`test_all`) live in this repo; shippable demo records ride
inside their plugin (e.g. samsite's, fetched by a bootstrap pointer —
[spec-tap-boot-bootstrap](../specs/spec-tap-boot-bootstrap.md)).

### Auth (who may do what)

[`tap_auth/specs/`](../tap_auth/specs/)

TAP is its own identity provider: **passkey-first** (WebAuthn — platform
authenticators or FIDO2 security keys), with local passwords as the
dev/recovery floor and federated OIDC available when configured. Authorization
is **capability-based** and enforced at the service layer, so it protects every
surface — web, API, and future AI — identically.

### Where AI fits

[spec-ai-integration](../specs/spec-ai-integration.md) ·
[spec-grid-keystone](../tap_grid/specs/spec-grid-keystone.md)

Today: assistants operate TAP through skills, read the grid's
self-descriptions (starting from the keystone), and drive the same commands
humans do. The `tap_ai` surface — in-app, read-only graph traversal and
explanation — is the designed next layer: read-only by rule in v0, with any
future writes going through the service layer as a named actor, never a bypass.

---

### What's not built yet (so you don't go looking for it)

Honesty about gaps is house style — a capability named here is absent on
purpose, waiting on demand, not forgotten. The big ones:

- **Traversals and paths.** Gryphon today answers pattern queries —
  neighborhoods, multi-hop matches — but **paths as first-class objects** ("show
  me how a commit becomes a running service", "trace this record from the form
  it entered on to the report it feeds") are not built. This is a planned
  essential ([the roadmap](../plan/road-rampart.md) carries it), and Gryphon is
  where the traversal extensions will land.
- **File hosting.** The grid models *facts about* things; it does not yet store
  **files** — attachments, reports, collected documents as blobs. Today
  file-shaped content either lives in a node's fields or outside TAP entirely.
- **Integrated AI.** The `tap_ai` app — in-app, read-only graph traversal,
  summarization, and explanation — is
  [designed](../specs/spec-ai-integration.md) but not yet built. Today the AI
  story is the *third player* from page one operating from the outside:
  assistants driving skills, reading specs, and using the same commands humans
  do. The in-app concierge is the next layer, read-only by rule in v0.
- **An end-to-end code review.** Getting here was a big push, and the assurance
  story so far is the mechanical one — the spec-linked guard suites, test
  lanes, and validation gates described above — plus targeted spot-checks and
  passes from a handful of the AI security-code-review systems, not a
  front-to-back human read of everything written. A deliberate end-to-end
  review is on the board for after paths, traversals, and files land, around
  the time integrated AI arrives. Until then: treat any surprising corner as
  worth a second look, and report what you find.

Smaller designed-but-deferred seams are marked in the spec tree itself: a
`spec-*-BACKLOG.md` filename (time-travel reads, perspectives, aliases, …) is a
designed seam waiting on demand — `ls specs/ */specs/ | grep BACKLOG` is the
honest inventory.

---

*The specs are canonical for everything summarized here. When this doc and a
spec disagree, the spec wins — and a correction here is welcome.*
