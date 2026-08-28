# Domain Articles

## Philosophy

TAP's documentation has had two layers and needed a third. **Specs** say what TAP *requires* of a concept. **Docs** (`docs/`, [spec-docs.md](spec-docs.md)) say how to *operate* it. Neither says what the concept **is in the world** — and that is the layer that keeps costing us.

A worked example. `github_ruleset` has a `bypass_actors` field. The spec says we store it; the doc says how to collect it. What neither could say, because there was nowhere to put it, is that *reading* `bypass_actors` requires **write** access to the ruleset — an owner-minted PAT sees it, a read-only GitHub App gets it silently omitted. That fact is not a requirement, not a procedure, and not a code comment. It is knowledge about the domain, discovered by executing a call and reading the response, and every session that lacks it pays for it again. The same shape repeats: PAT grants and App installations are App-only and 404 to any token; GraphQL serves GitHub's configuration layer while REST serves the operation layer, so there are no Actions runs or jobs in GraphQL at all; a `github_actions_job` is an **execution**, not the declaration in the workflow YAML — the distinction every other tool in the field conflates.

A **domain article** is where those live: one markdown file per node type and per edge type, beside the models. It reads like an encyclopedia entry, not a code comment — what the concept is, why we modelled it this way, which natural key is load-bearing, what it deliberately excludes, and what a credential can actually see.

Three audiences, and the third sets the format. Future maintainers and outside contributors read these beside the code. **Player 3** ([spec-ai-integration.md](spec-ai-integration.md)) — the AI assistants that observe and reason about TAP — reads them *instead of* the vendor's API reference, which it cannot hold in context. So articles are **markdown, machine-first**: greppable, diffable, and guard-checkable. This is a deliberate, stated exception to the house rule that briefing material for a human is authored as styled HTML; rendering articles prettily inside TAP is a later and separate concern, and it reads from this same source.

The discipline that makes the layer survive is [Coverage and Field Completeness](#coverage-and-field-completeness): a field added to a model without a paragraph in its article reds the build. That is the derive-a-fact-once rule (CLAUDE.md) applied to documentation — an article physically cannot drift from the model it describes.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | A Home for Domain Knowledge | Every node and edge type has one place recording what the concept is in the world and why it is modelled this way. |
| 2. | Cannot Drift | The article is mechanically tied to the model's field set, so it cannot fall behind unnoticed. |
| 3. | Answerable Update Question | Each article pins its authoritative source *with a version*, so "this standard revised — which of our models does it touch?" is one query. |
| 4. | Machine-First | Markdown beside the code, so an AI assistant grounds itself in TAP's own words rather than a vendor's API reference. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-domain-articles-layer | [The Layer](#the-layer) | Implemented | What a domain article is, where it lives, and what it must not become |
| req-domain-articles-sections | [Article Shape](#article-shape) | Implemented | The required sections, and the per-model authoritative-source pin |
| req-domain-articles-coverage | [Coverage and Field Completeness](#coverage-and-field-completeness) | Implemented | Ratcheted: every registered type has a conforming, field-complete article |

### The Layer
----
RID: `req-domain-articles-layer`
Status: `Implemented`

A domain article is a markdown file at `<plugin>/domain/<concept>.md`, beside the models it describes — **not** under `specs/`, because it states no requirement, and not under `docs/`, because it is not a procedure. Its filename stem is the owner-local half of the type's slug: `github_core__github_workflow` is documented by `domain/github_workflow.md`, and the edge `EXECUTES_WORKFLOW__github_core` by `domain/EXECUTES_WORKFLOW.md`.

**Dimensions are the third declared vocabulary**, and until this spec the only one nothing explained. A dimension key (`github.observation`, `tap.meta`) partitions the grid, is written into every entity's `dimensions` JSONB under a GIN index — so it is effectively immutable — and admits a set of values whose meanings live nowhere. `github.observation: declaration|execution` encodes the vocabulary corpus's single largest finding and landed across an entire plugin with no record of what its two values mean. Dimension articles live one level down, at `<owner>/domain/dimensions/<key>.md`, so a dotted key can never shadow a type stem.

Dimension articles are owed by **every** owner, `tap_*` apps included — the one place this layer reaches beyond plugins. Node and edge articles are plugin-only because an app's node types model TAP's own furniture, which its specs already define. A dimension is not furniture: it is a vocabulary, and an unexplained vocabulary is a problem wherever it is declared. Ownership follows the declaring package.

An article says what the concept **is in the world**. Where TAP's own requirements bear on it, the article **links the spec and does not restate it** — a restatement is a second derivation of the same fact and will drift from the first. Symmetrically, an article is not a place for procedure: how to collect the type belongs in `docs/`.

The one section that must never be written from documentation alone is [Observability](#article-shape). Not because vendor documentation lies — TAP's most valuable observability facts were all documented correctly, and reading them was not the mistake — but because documentation describes the *permitted* path and this section is about the *denied* one. No page said that a caller refused `bypass_actors` receives HTTP 200 with the field silently absent rather than an error, which is precisely what makes absence read as "nobody can bypass" instead of "we could not look"; and a neighbouring endpoint's 403 was documented nowhere at all. Write this section from an observed response, say which credential observed it, and record what has *not* been tested rather than leaving the gap implicit.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-domain-articles-layer-1 | Location and naming | Implemented | An article lives at `<plugin>/domain/<stem>.md`, where the stem is the owner-local half of the node's `ENTITY_TYPE` or the edge's slug. | Derived once in `tap.domain_articles`. |
| req-domain-articles-layer-2 | Markdown, machine-first | Implemented | Articles are authored as markdown beside the code, greppable and guard-checkable; any pretty rendering reads from this source. | Stated exception to the styled-HTML briefing convention. |
| req-domain-articles-layer-4 | Dimensions are articled too | Implemented | A dimension key declared by any model's `DEFAULT_DIMENSIONS` or edge's `default_dimensions` owes an article at `<owner>/domain/dimensions/<key>.md`, in every owner including `tap_*` apps. | The one deliberate exception to plugin-only scoping. |
| req-domain-articles-layer-3 | Links the spec, never restates it | Implemented | Where TAP's requirements bear on the concept the article cites the RID rather than reproducing the requirement. | Reviewed, not machine-checked; the RID-integrity guard catches a citation that stops resolving. |

### Article Shape
----
RID: `req-domain-articles-sections`
Status: `Implemented`

Every article carries these `##` sections. The first five are the authored core; the rest each exist because their absence cost time.

- **Blurb** — one line: what this is and why it exists.
- **Purpose** — what the model is for inside TAP.
- **Goals** — what modelling it is meant to make possible.
- **Identity** — the natural key, and why it is that. Load-bearing and effectively immutable; the single most-forgotten fact.
- **Boundaries** — what this model deliberately does *not* cover. Recording that a question was asked and settled is what stops it being re-litigated.
- **Neutrality** — forge-neutral or vendor-specific, and the test applied. Carries the reasoning behind the corpus's per-concept marking.
- **Observability** — which credential and permission populate it, and what is **not** observable at all. Written from an executed call.
- **Authoritative Source** — see below.
- **Prior Art** — discrete links to other instances of the concept. Prior Art exists to track *change*, so an entry carries the version or date it describes; a bare URL is not an entry.
- **Fields** (nodes), **Endpoints** (edges) or **Values** (dimensions) — the terms the article must account for. For a node, every field: why it is there, where it came from, what justifies it. For an edge, its endpoints and every dimension key it stamps. For a dimension, every value it admits: what the value means, and why the set admits it.

**Authoritative Source** states three keys as `- **Key:** value` lines — `Source`, `Version`, and `Retrieved`. The pin lives on the model rather than in a global source register, and that placement is the requirement: it makes the update question answerable with one query — *this standard revised, which of our models does it touch?* — which is the seam a scheduled research pass hangs off. A register answers "what do we cite"; only a per-model pin answers "what breaks".

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-domain-articles-sections-1 | Required sections present | Implemented | Every article carries each required `##` section for its kind; nodes end in `Fields`, edges in `Endpoints`. | Deeper headings nest inside a section without hiding it. |
| req-domain-articles-sections-2 | Authoritative source pinned | Implemented | The Authoritative Source section states `Source`, `Version` and `Retrieved` as parseable `- **Key:** value` lines. | The per-model pin, not a central register. |
| req-domain-articles-sections-4 | Values section on dimensions | Implemented | A dimension article carries a `Values` section naming every value any model or edge gives that key. | A term may be written alone or with its value (`github.surface: actions`); both account for it. |
| req-domain-articles-sections-3 | Prior Art carries versions | Implemented | A Prior Art entry bearing a URL also carries the version or date it describes. | A bare URL cannot track change. |

### Coverage and Field Completeness
----
RID: `req-domain-articles-coverage`
Status: `Implemented`

Every node type and edge type a plugin registers owes an article, and **every key in a model's `FIELD_CRUD_SCHEMA` owes a per-field explanation**. The second half is the load-bearing one: it makes an article that has quietly fallen behind its model a build failure rather than a plausible-looking lie.

The same tooth applies to the other two vocabularies. An **edge** must account, in its Endpoints section, for every dimension key it stamps — the check that would have caught six articles going stale the day `github.observation` was added across a plugin. A **dimension** must account for every value any model or edge gives it.

A declaration the scanner cannot resolve is **reported, never read as empty**. A model may hoist its schema or dimensions to a constant and import it; the scanner follows one hop within the owner's own tree, and anything it still cannot resolve becomes a finding. Silently measuring zero terms would let an article that explains nothing pass the coverage check — a false green, which for a coverage guard is worse than a failure.

Enforced as a ratchet, not a hard lint. The layer is new and the concepts already modelled predate it; a guard that reds every plugin on the day it lands gets disabled instead of drained. Each owner records its debt in **its own** baseline at `<plugin>/guards/baselines/domain_articles.txt` — visible, shrinking, and carried into the plugin's wheel, so eviction takes the debt with it rather than stranding rows centrally (`req-tap-plugin-validation-distribution-principle`).

Scope for node and edge articles is plugin owners; dimension articles are owed by every owner (`req-domain-articles-layer-4`). Plugins model concepts that exist in the world independent of TAP; the `tap_*` apps model TAP's own furniture — pages, panels, arrangements, batches — which their specs already define and about which there is no outside world to research. Widening the scope would manufacture a baseline that could never honestly drain.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-domain-articles-coverage-1 | Every registered type has an article | Implemented | A node or edge type declared by a plugin with no article at its expected path is a finding. | |
| req-domain-articles-coverage-2 | Field completeness | Implemented | Every `FIELD_CRUD_SCHEMA` key must appear as an inline-code token in the article's Fields section; a new field with no paragraph is a finding. | Resolves a schema assigned from a module-level constant, so hoisting it cannot produce a false green. |
| req-domain-articles-coverage-4 | Dimension value coverage | Implemented | Every value any model or edge gives a dimension key appears in that dimension's `Values` section. | |
| req-domain-articles-coverage-5 | Edge dimension coverage | Implemented | Every dimension key an edge stamps appears in its `Endpoints` section, so an article cannot assert the opposite of its manifest. | Landed after exactly that drift occurred. |
| req-domain-articles-coverage-6 | No silent empty measure | Implemented | A `FIELD_CRUD_SCHEMA` or `DEFAULT_DIMENSIONS` bound to an unresolvable name is a finding; the scanner resolves one import hop within the owner before giving up. | Caught `tap_web`, which reads as zero dimensions without the hop. |
| req-domain-articles-coverage-7 | Orphan articles | Implemented | An article under `domain/` or `domain/dimensions/` with no registered type or dimension behind it is a finding. | The symmetric check: a rename leaves an article reading as current. |
| req-domain-articles-coverage-3 | Per-owner baseline | Implemented | Debt is recorded in the owning plugin's own baseline and ratchets toward zero; a stale entry fails so a written article cannot linger as an exception. | Central guard code names no plugin slug. |
