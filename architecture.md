# TAP Architecture

The Analagy Platform (TAP) is a general-purpose systems-mastery platform that blends humans, AI, and
software, developed for immediate applications in security, compliance, and operations.

This document describes TAP **as it is built**. It is the orientation surface: the thing a cold reader —
human or AI — reads first to learn the shape of the system and where the real canon lives. It was
originally written (2026-05) as a scaffolding brief for a system that did not exist yet; that brief is
kept verbatim in the appendix, because the design choices it recorded still hold and the reasoning is
worth having.

**Where canon lives.** Specifications (`specs/`, `<app>/specs/`) are authoritative for behavior; this
document is a map, and where it is less precise or has drifted, the specs win. Three other surfaces
matter before you act:

- **The keystone** — `MATCH (k:keystone) RETURN k ORDER BY k.created_at ASC`, oldest first. It is a node
  on the grid that says what *this instance* is, what it models, and where its data came from
  (`tap_grid/specs/spec-grid-keystone.md`). An instance describes itself; this document describes the platform.
- **The roadmap** — `plan/road-products.md` (the Active step's objective, done-test, non-goals, and the
  standing Doctrine) and `plan/product-map.md` (the product taxonomy). Neither carries dates.
- **CLAUDE.md** — the operational summary and the standing filters that govern how work is done here.

---

## Core concepts

- **Entity** — the graph spine and canonical reference for TAP-managed nodes and edges. It holds
  cross-cutting metadata: identity, dimensions, timestamps, provenance, and related higher-order
  capabilities. Every TAP-managed node has a backing Entity.
- **Edge** — a directed, typed relationship between two entities. A first-class TAP object with its own
  table and its own backing Entity on the spine.
- **Identity — two keys, not one.** Entity ids are assigned UUIDv7. Alongside them, a **natural key** is
  *derived* from each type's declared constituting properties, so the same real-world object observed
  twice resolves to one row (`tap_grid/specs/spec-grid-entity.md`, `spec-grid-reconcile.md`). Assigned
  identity is what the grid points at; the derived key is how an observation finds what it already knows.
- **Dimensions** — the scoping and partitioning model carried on the Entity spine, letting one node/edge
  model hold multiple graph contexts without fragmenting. Currently a flat JSON object; a 2026-09-20
  ruling moves dimensions to being nodes in their own right (see *Rulings since the original brief*).
- **History and FLIP** — field-level information provenance: per-data-item history and change tracking,
  not audit logs. A core grid concept, not a separate product domain.
- **Service layer** — the canonical contract between applications and TAP-managed graph data. Node and
  edge reads and writes, batch-backed writes, discovery, and constraints go through it. Direct ORM
  mutation of graph state is a defect outside migrations and deliberate model-level tests.
- **Gryphon** — TAP's graph query and traversal language for read-only graph-shaped search and
  neighborhood retrieval.
- **GRIFT** — the Grid Interchange Format: TAP's canonical JSON contract for graph interchange, defining
  batch-oriented file interchange and the portable subgraph shapes used for node/edge responses.
- **Grid** — the totality of the data modelled on the SQL-based graph implementation.
- **System** — a bounded collection of entities and edges representing something being managed, such as
  a cloud SaaS service.
- **Plugin** — an installable package that introduces new entity types, edge types, constraints,
  collectors, pages and behaviors, and which may depend on other plugins.
- **Product** — an umbrella plugin whose **boot record is what it is**: a named composition of plugins,
  pins and seeded data that stands up one usable thing (`plan/product-map.md`).

---

## Subsystems

The Django apps, by what each one owns rather than by build order.

| App | Owns |
| --- | --- |
| `tap_grid` | The core data model: Entity, Edge, dimensions, history/FLIP, the service layer, Gryphon, GRIFT, keystone, reconciliation. Everything else depends on it. |
| `tap_plugins` | Plugin identity, manifests, dependency declaration and resolution, validation (`validate_plugin`), load lifecycle, and the registry-backed discovery of TAP-managed types. |
| `tap_boot` | All boot. First in `INSTALLED_APPS`. Takes a fresh database to a usable, populated, self-describing instance declaratively and with zero human interaction; the boot profile and its record are the bill of materials for what an instance is. |
| `tap_auth` | Authentication and authorization as a platform-wide plane: actors, capabilities, policy, and the login chokepoint. TAP is its own identity authority, passwordless-primary with passkeys (WebAuthn), with OIDC as a complementary path and a capability gate that bootstrap sits beneath. |
| `tap_cares` | Collect, Act, Receive, Emit, Schedule — the runtime plumbing that moves facts between the outside world and the local grid: collectors, receivers, emitters, actions, schedules, run records, GRIFT-batch-backed updates, and the runtime secrets those need. |
| `tap_api` | API versioning, auth, and global API behavior on Django Ninja; plugins mount routers only under a namespaced prefix it controls. |
| `tap_web` | Pages, panels, templates and assets — the expressive dashboard and UI substrate that plugins extend, plus the auth templates. |
| `tap_viz` | Visualization: graph-native panels rendered with Cytoscape inside the page/panel system. |
| `tap_health` | A deliberately small, dependency-free pair that exercises the *real* assembled instance, closing the class of failure where an instance boots "successfully" and is still subtly broken. |
| `tap` | The project core: settings, logging conventions, serving (the boundary between the deployed artifact and the network), runtime secrets resolution, and the cross-cutting guards. |

Two things that look like apps and are not: `tap_secrets/` in a worktree is a **symlink to the host
secret store** (`~/tap-secrets`), shared across every session; and there is **no `tap_ai` app** — AI is
currently a posture plus read-only surfaces (see below), not a module.

---

## Fundamental design choices

These are the differentiators that distinguish TAP from existing CRM, compliance and systems-management
tools, and they are critical to the project's success.

1. **Graph capabilities in a standard SQL database.** An entity-table spine plus a dedicated edge table
   support directed graphs across the domain, giving the strong typing, security and ACID guarantees
   that most graph databases lack while keeping the useful parts of the graph model for traversal
   (recursive CTEs on Postgres). Field-level information provenance (FLIP) is essential and requires
   balancing graph and SQL concepts.
2. **Query and interchange are first-class graph concepts.** A native graph query surface (Gryphon) and a
   native graph interchange surface (GRIFT), rather than ad hoc payloads in either direction.
3. **Dimensions.** Multiple graph contexts, namespaces and perspectives on one spine, without
   fragmenting the node/edge model. Other scoping concepts — realms, environments, pocket dimensions —
   may be explored later.
4. **Visualization.** Humans view and interact with the data graphically: Google Maps meets Visio.
5. **Plugin system.** Rather than over-specifying the domains the platform can serve, the core implements
   first principles that apply to all systems — graph and traversal, history, schema management,
   security — and plugins define domain, interactions and customization, including components outside
   Django and Python such as containers and remote services. Plugins can be scaffolded and can depend on
   other plugins.
6. **AI integration built in, not shoe-horned.** RAG-able capabilities throughout the application, data
   model and plugin system, so an AI helper can traverse the graph, summarize state, suggest actions and
   point out gaps. Agentic alignment is a ground-up priority; v0 AI has no control ability.
7. **Federation, eventually.** Extended queries, import/export and synchronization with other TAP or
   similar systems. The details come later, but the core schema carries what that will need, such as
   where an entity originated.

---

## Rulings since the original brief

Each of these postdates the 2026-05 brief and changes something it asserts. The owning spec is canon;
these paragraphs exist so a reader is not surprised.

**Reconciliation, natural keys and tombstoning** (`tap_grid/specs/spec-grid-reconcile.md`,
`spec-grid-entity.md`). A collector is additive-only until something tells it otherwise, and "not found"
is not the same fact as "deleted" — it is also a failed call, a narrowed credential, a truncated page or
a plan boundary. TAP therefore separates the thing, our record of it, and our current observation of it:
identity is an assigned UUIDv7 plus a derived natural key; retirement records
`DROPPED_FROM_OBSERVATION` under a named scope rather than deleting; and deletion cascades along
containment. Falsifiers, evidence completeness and shadow nodes for known unknowns belong to the same
model.

**Dimensions become nodes** (ruled 2026-09-20, epic `tap#708`). Dimensions gain assigned identity as
nodes that nothing points at — no inbound edges — rather than remaining only a flat JSON object on the
spine. The concept keeps its role; its representation changes.

**Keystone** (`tap_grid/specs/spec-grid-keystone.md`). An instance is self-describing: a keystone node
carries human prose plus structured context and the schema documenting it, so anyone landing cold learns
what this instance is from the grid itself rather than from tribal knowledge.

**FIPS is default-ON** (`specs/spec-fips.md`, `ARG TAP_FIPS=1`). Every cryptographic *provider* that can
execute in the deployed artifact must be the validated module, a validated equivalent, proven unreached,
or explicitly out of boundary — a crypto bill of materials, not a grep for weak algorithms. Adding a
dependency, native binary or plugin means keeping it FIPS-clean or accounting for it.

**Security posture** (`specs/spec-security-posture.md`). Where a foundational defensive edge can be laid
at near-zero marginal cost while a surface is already open, lay it: over-restriction relaxes cheaply,
omission retrofits expensively. Risks deliberately left open get named rather than implied away.

**AI integration posture** (`specs/spec-ai-integration.md`). Build for the third player alongside code
and humans: prefer machine-legible, declarative, queryable metadata over human-only prose, name the AI
consumer of any for-AI surface, and author operational procedures as AI-operable skills. v0 AI is
read-only and must never write core graph state; any future write rides the service layer under a named
delegated actor.

**Validation is architectural.** Parallel automated sessions branch off `main` and promote back to it, so
integrity is maintained by a pre-push validation gate rather than per-session memory.
`specs/spec-dev-validation.md` is the center of gravity, and its Validation Map is the authoritative
inventory of every validation surface with its honest guard status.

---

## TAP runtime loop (conceptual)

- Prerequisite: TAP installed, plugins added to define schemas and functionality, configured for the use case.
- Ingest or discover facts about a system.
- Normalize them into entities and edges.
- Route node and edge reads and writes through the service layer.
- Express graph-native reads through search and Gryphon; exchange graph data as GRIFT-shaped subgraphs
  where portable responses are intended.
- Record provenance at field level.
- Reconcile what was found against what is on the grid — including what is no longer observable.
- Evaluate relationships and constraints.
- Accept recommendations or actions.
- Update the graph and provenance.
- Present state to humans and AI via graph visualization, alerts, tables and dashboards.

---

## Critical, essential elements

1. Written in Python and Django with Postgres, Django Ninja for the customer-facing API and Django admin
   for standard admin operations. The deployed artifact is a web image and a database image, run together
   by compose (`tap-web`, `tap-db`).
2. Extends the base Django ORM: Entity as the graph spine, typed BaseModel tables for domain data, and a
   dedicated Edge table with backing Entity rows.
3. Uses Cytoscape as the user-facing graphical view system.
4. Graph objects are scoped and partitioned using dimensions on the Entity spine.
5. Plugins isolate capabilities and may depend on other plugins. They are installable Python packages —
   wheel-buildable distributions with a `tap.plugins` entry point, consumed via uv — composed by a boot
   profile, not a source tree the core imports.
6. Every place in the architecture where a touch point or surface can support AI integration is
   considered one.
7. TAP is its own identity authority: passwordless-primary passkey authentication, an explicit
   capability model, and bootstrap sitting beneath the capability gate as a root of trust.
8. Each installation is single-tenant, though dimensions and security policy may scope access to parts
   of the graph.
9. All entity ids are assigned UUIDv7; natural keys are derived alongside them.
10. Data objects carry their own icon for use in visualizations, graphs and tables.
11. No phone-home and no dependency on a vendor service: an instance's data and operations are local to
    the application. Collectors do reach the systems they observe — that is the point of a collector —
    but only the systems an operator points them at, with credentials the operator supplies.
12. Federation remains a distant target.
13. Node and edge operations go through the TAP service layer rather than direct ORM access.
14. TAP-managed types are discoverable through registry-backed service-layer discovery rather than only
    through Python imports.
15. One canonical graph interchange contract for portable node and edge responses: GRIFT and
    GRIFT-defined subgraphs.
16. Graph-native reads are expressed through TAP search capabilities, including Gryphon, rather than
    proliferating one-off graph query helpers.
17. TAP-managed graph state may reference runtime capabilities and sensitive runtime inputs by stable
    keys, but executable code and secret material resolve only through trusted runtime registries. The
    grid makes these references durable, inspectable, schedulable and related to other graph objects; it
    must not become an arbitrary code loader or a secret-value store.

---

## What TAP is definitely not

1. A product built for one system or use case. The core capabilities apply to all systems; plugins carry
   domain specificity.
2. Just another CRM, GRC or CMS built on standard CRUD and SQL concepts. Graph plus plugins enable
   exactly those use cases and many more.
3. A toy good for small projects. It is built to scale to the largest systems humanity has created, and
   bigger.
4. A shoe-horned AI money play. AI was an accelerator from day one, with full awareness of the
   technology's strengths and weaknesses.

### Explicit non-goals (v0)

- Agentic actions that modify the graph
- Multi-tenant SaaS
- Full OSCAL parity
- Cross-organization federation

---

## Products

A product is an umbrella plugin whose boot record is what it is. The taxonomy lives in
`plan/product-map.md`; the ordered progression lives in `plan/road-products.md`.

**git-serious** — the product line currently being built, and the one TAP runs against itself. It
observes a GitHub account's CI/CD system — repositories, workflows, actions, runners, rulesets,
secrets, identities and their configuration — and makes it legible on the grid. Its plugin set spans the
neutral substrates (`git_core`, `identity_core`, `compliance_core`), the vendor vocabulary and collector
(`github_core`), auditing (`zizmor`), the admin pages (`administrivia`), and the product plugin itself
(`git-serious-tap`). Its boot profile lives in the product's own repo, not here. Plugins and products
carry a `-tap` suffix.

**Rampart** — a planned product line for continuous compliance of SaaS services, whose plugin set
defines infrastructure, control and signal entities; dashboards for visualization and compliance
monitoring; continuous ingestion to keep the graph current; and FedRAMP 20x for initial control
satisfaction, extensible to other regimes. Rampart is explicitly read-only in its initial pass: it
presents a compliance scorecard for humans to remediate outside Rampart, with enough context to suggest
what to do.

### Pithy blurbs

- Wordpress / Salesforce / ServiceNow for managing systems
- Google Maps meets Visio meets Wikipedia
- Semantic web for humans instead of homo economicus
- Palantir for the people
- From Knowledge Graph to Wisdom Map

---

## Still not formally defined

1. How future scoping concepts beyond dimensions — pocket dimensions, perspectives — should be modelled.
   Perspectives are partly shaped by the reconciliation work but are not settled.

---

## Appendix: the original scaffolding brief (2026-05)

Kept verbatim for provenance. It was written as instructions to an architect scaffolding a system that
did not yet exist; where it conflicts with the body above, the body and the specs win.

> You are a senior software architect working with a single developer of moderate experience who has
> world-class architectural experience and instincts.
>
> You will scaffold a Python/Django-based system strictly according to the following architecture.md.
>
> Rules:
> - Do not invent concepts not present in the document.
> - Treat the specifications as the canonical source of truth when this document is less precise or has drifted.
> - Treat Entity as the canonical graph spine and higher-order metadata layer for TAP-managed nodes and edges.
> - Do not introduce multi-tenancy.
> - Do not introduce autonomous agent actions.
> - Start with the core data model first, then the plugin interfaces.
> - Prefer clarity and inspectability over cleverness.
>
> Generate code incrementally and explain design decisions briefly.
>
> **Step-wise priority goals for v0:** 1. `tap_grid` — core data model, entity and edge tables connecting
> to standard ORM data tables, including service-layer decisions that touch multiple tables. 2.
> `tap_plugins` — minimal plugin management to seed data types for testing. 3. `tap_api` — API versioning,
> auth and global API behavior on Django Ninja. 4. `tap_web` — assets and helpers for expressive
> dashboards and UIs which plugins extend. 5. `tap_viz` — visualization via Cytoscape. 6. `tap_cares` —
> on-grid automation plumbing. 7. `tap_ai` — initial RAG / LLM surfaces, read-only traversal,
> summarization and suggestion helpers.
>
> **Once v0 is complete:** 1. Rampart plugin set. 2. Refinements for ease of use, installation
> streamlining, user documentation. 3. First customer for Rampart to identify successes and pain points.
> 4. Extend deployments to other Rampart customers to establish a financial base. 5. Expand to other
> domains.
