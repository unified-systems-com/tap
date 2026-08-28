---
title: git-serious — George's impressions register (from the prior-art read)
date: 2026-08-27
status: active
audience:
  - developer
  - llm
spec: specs/spec-roadmap.md
related_docs:
  - docs/misc/doc-products-git-serious-build-log.md
---

# Impressions register

Nineteen observations George recorded after reading the CI/CD security prior-art survey
(2026-08-27). Captured verbatim in substance so none is lost, each with a disposition. **Several are
strategy-grade ideas, not backlog items** — they are marked as such, because the failure mode for a
list like this is that the ideas get filed as tasks and the strategy evaporates.

Disposition key: **ANSWER-PENDING** (a question with work in flight) · **CANON** (belongs in a spec
or the roadmap) · **BACKLOG** (a tracked item) · **NOTED** (recorded, no action yet).

| # | Observation | Disposition |
| ---: | --- | --- |
| 1 | How many of the 60+ SpecterOps Cypher queries can Gryphon run today, and what are the functional gaps? | **ANSWER-PENDING** — analysis in flight; deliverable includes a query-by-query verdict and a ranked missing-feature list |
| 2 | How many of these tools are generic across forges? Keep an eye on what generalises to a grid projection vs what is service-specific. | **PARTLY ANSWERED** — the vocabulary corpus marks every concept neutral/specific; the kernel and Gitea tests both support the split. Needs a forge-comparison pass for the *tooling* half |
| 3 | For GitHub: do service-specific operations apply to GHE, and what extra capability does GHE expose that Cloud does not? | **ANSWER-PENDING** — not yet researched. Known already: the audit log is an Enterprise feature, which is item 16's crux |
| 4 | **General-purpose config-security rule packs, like anti-virus/YARA rules** — teams publishing their internal checks. Potentially industry-changing. | **CANON** — strategy-grade. See "Rule packs" below |
| 5 | Change-over-time is the missing signal; likely needs time-travel in Gryphon to compare prior shape to current shape. | **CANON + ANSWER-PENDING** — the corpus already establishes history as our differentiator; the Gryphon analysis includes a dedicated time-travel assessment |
| 6 | Building our own graph engine is the biggest win — none of these services run at scale without serious Neo4j licensing. | **NOTED** — an economic argument for Gryphon worth writing into the strategy properly |
| 7.1 | Which tools guard against **AI services operating inside repos** — prompt-injection detection on inputs? AI agents are human-like accounts with new attack vectors. | **ANSWER-PENDING** — not covered by the sweep; a real gap |
| 7.2 | Which tools incorporate **apps and third-party integrations**? TAP can build collectors from the third parties themselves — insight where others see a perimeter. | **CANON** — strategy-grade differentiator. See "Past the event horizon" below |
| 8 | **Supply chain** is the next target after git-serious, before (or possibly after) code-paths. Track what we learn to extract supply chains onto the grid. | **CANON** — a product-map entry, not a backlog item |
| 9 | Model GUAC's own CI/CD as a demo, if enough public information exists. | **BACKLOG** — a fun, low-cost demo candidate |
| 10 | **Intent is the missing capability.** Every scanner uses static rules to find misconfiguration; none starts by understanding the system under observation. Criticality of repos/workflows is absent. They are the modern equivalent of static malware signatures. | **CANON** — strategy-grade. The sharpest observation in the set |
| 11 | **VIA NEGATIVA.** A system is secure if it does exactly what it needs to and nothing else. Understand the shape of the pipeline, then remove every other capability. Inverts the play: define the intended path, then arrive at security by subtraction — and detect drift when configuration changes but intention has not. | **CANON** — strategy-grade, and the natural partner to item 10 |
| 12 | **More than security.** What makes it stick is dovetailing into an overall capability for understanding and managing pipelines that admins and security teams converge on. Not a single pane of glass — everyone on the same page. | **CANON** — positioning; affects the product's framing, not just its features |
| 13 | **Operational principles.** Teams should define their operational principles for CI/CD execution; these become the core validators. Do ours first. Principles need a visualisation-side representation. | **CANON + BACKLOG** — ours are drafted (see below); the viz representation is a build item |
| 14 | Paths system needed next week. | **BACKLOG** — already tracked as core work |
| 15 | The GitHub App needs thinking: it points at the *user's* git-serious instance, not ours, and asks them to run code in their environment. | **ANSWER-PENDING** — needs a design pass; the friends-milestone credential decision depends on it |
| 16 | Audit logging is hard with a scheduled pull unless the App gives a heads-up on change. The gap between snapshot and realtime. | **CANON** — a named architectural seam; ties to items 3, 5, 15 |
| 17 | **git-serious-incidents** — a batch pack of modelled historical incidents someone can investigate and view. | **BACKLOG** — excellent demo and teaching artifact; the corpus and incident table are most of the raw material |
| 18 | **Eyes on the prize.** A POC to scratch our own itch, promote TAP, and attract contributions that stabilise core. Make it great and splashy, in service of that goal. | **CANON** — the standing filter for everything above |
| 19 | **Plugin hitlist** — publish ideas others can implement themselves, to demonstrate how easy it is. | **BACKLOG** — an ecosystem-seeding move; pairs with the plugin-ecosystem rungs already in the product map |
| 21 | OCSF — what would it take to present a proposal once our approach has settled? | **BACKLOG** — the vacancy is real (zero CI/CD vocabulary, none proposed). Propose from evidence *after* the corpus survives contact with a second forge, not from design |
| 22 | **SBOM needs first-class support** — likely its own plugin with base models, possibly further plugins for common formats. | **CANON** — lands with `supply_chain_core` (ruling 4). purl is the settled identity; CycloneDX/SPDX are the format layer |
| 23 | **Authoritative source named in the model** — if we track one, list it, so we can watch it and catch updates. | **CANON** — the missing piece of the domain-background doc. Per-model source pinning is what lets a scheduled job diff *per model* rather than globally |
| 24 | **Chaotic Majority in action** — a million things can go wrong; what matters is that the handful of operational principles go right. | **CANON** — `WOG-Chaotic-Majority` applied to this domain, and the argument for principles-as-validators over exhaustive rules |
| 25 | **Supply-chain incidents as grid representations** — generate models of real incidents, categorise with our vocabulary, analyse, extract lessons. A repeatable process: build grid representations of the real world, learn, extract. EU-CRA and similar as feeds. | **CANON + BACKLOG** — generalises item 17 from CI/CD to any incident domain. "Model the world, then learn from the model" is a TAP-wide method, not a git-serious feature |
| 26 | **Design vs Config vs Operation (DCOM)** — operational principles are the design, parsed workflow setup is the config, execution logs are the operation. Three graphs that map to one another; design states what shape the other two should have; config graph should look like ops graph. This is what dimensions are for. | **CANON** — see "DCOM" below. The strongest structural idea in the set |
| 27 | **Defined dimensions** — define the standard dimensions for this problem space up front; bake dimension definition into `build-domain-vocabulary`, since dimensions must be wired into base models and used during collection. Arguably more fundamental than base models. | **CANON + SKILL CHANGE** — first cut below; the skill gains a dimensions step |
| 28 | **GraphQL** — GitHub is standardised on it; use it in the collector rather than hammering REST with TLS handshakes and rate limits. | **BACKLOG, evidenced** — today's org run lost 6 of 19 repos to transient TLS timeouts because REST needs a call per workflow, per run, per job. The collection manifest is declarative, so the transport is swappable beneath it |
| 30 | **Principles precede design, and must be executable.** Principles may exist independently of the design, the way requirements precede code: everything in the design should implement one. They must be expressible as Gryphon queries or modules — a way to demonstrate the thing is what it says it is. This is the essence of deterministic security: define what the system should do and how strict to be, and the validations *emerge from* the principles, applicable to design, config and operation alike. | **CANON** — see "Principles as predicate" below. Foundational; supersedes the placement in item 26 |
| 29 | **Module and ORM searches are escape hatches worth keeping** — less glamorous than traversals but deterministic, nameable, version-controlled, manageable, and able to carry far more logic. Treat modules as their own investigation class / capability; eventually they call AI endpoints and the old "wire in a Python module as a search" idea becomes a powerful search-and-execution tool. | **CANON** — see "The module search" below. Already built and unused |

## The four that are strategy, not backlog

**Intent (10) and via negativa (11) are one idea seen from two sides.** Every tool surveyed applies
static rules to find bad configuration. None establishes what the system is *for* first. The
inversion: derive the intended shape of a pipeline from observation, express it as the set of things
that must be able to happen, and then treat everything else as removable. Security becomes
subtraction from a known-good shape rather than pattern-matching against a list of known-bad ones.
The detection that falls out is the valuable half — **if the configuration changed and the intention
did not, something is wrong** — and it needs no rule author to have anticipated the specific attack.
This is also the honest answer to why a graph beats a linter: a linter cannot hold intent.

**Rule packs (4)** are the distribution mechanism for the *other* half — the known-bad knowledge that
does exist and that teams currently cannot share. YARA is the precedent: a portable, writable,
publishable format turned private detection knowledge into a commons. Nothing equivalent exists for
CI/CD configuration. Note the tension with item 10, and keep both: packs carry transferable
knowledge, intent carries local truth, and a system that has only packs is the thing item 10
criticises.

**Past the event horizon (7.2).** Every commercial tool stops at the boundary of the forge, because
their model of the world stops there. We can write a collector against the third party itself and
pull its configuration onto the same graph. That is a structural advantage, not a feature: their
perimeter is our ingest.

**More than security (12).** The security framing is how the space is legible today, but the durable
version is a shared picture that platform teams and security teams both operate from. That is a
positioning decision with product consequences — it argues for the ops/legibility surfaces being
first-class rather than a means to a findings list.

## DCOM — design, config, operation (item 26)

Three graphs of the same system, at different removes from reality:

| Layer | What it is | Where it comes from |
| --- | --- | --- |
| **Design** | The operational principles a team commits to | Declared by the team; the statement of intent |
| **Config** | The pipeline as written — workflows, rulesets, permissions, pins | Parsed from the forge |
| **Operation** | The pipeline as it actually ran — runs, jobs, actors, outcomes | Execution logs and run history |

**Design states what shape the other two should have. Config and operation should agree with each
other.** Every interesting question is a disagreement between two of these layers:

- config ≠ design → the pipeline is not built the way we said it would be
- operation ≠ config → something ran that the configuration does not explain
- config changed, design did not → **drift**, which is item 11's detection, and the one that needs
  no rule author to have anticipated the attack

This is the mechanism that makes **via negativa (11)** implementable. Via negativa needs a statement
of intended shape to subtract from; *design* is that statement. It is also the answer to **intent
(10)**: the reason every scanner is a static-rule engine is that none of them has a design layer to
compare against.

Dimensions are the axis that separates the layers on one grid — see item 27.

## The module search — already built, unused (item 29)

`tap_grid/search.py` dispatches three search types today: `module`, `orm`, and `gryphon`. Plugins
register Python runners off their own manifest (`tap_plugins/base.py`), and
`req-grid-search-module` is marked **Implemented**. The seam exists and nothing uses it.

The property that matters: a module search is a **named, versioned, reviewable artifact**. It has a
slug and an entity on the grid, ships in a plugin with a version, passes through code review, can
hold arbitrary logic, and returns the same envelope a traversal does — so panels, pages and the API
cannot tell the difference. *A traversal is a query someone wrote; a module is a capability someone
published.*

Consequences worth holding:

- **For hard questions the module is the better primitive, not the fallback.** Ranking findings
  against critical paths, adjudicating a conjunction, reconstructing an incident — these want code,
  not a cleverer pattern. Traversal gaps should be triaged with the question "does a module do this
  better?" and the answer recorded in the divergence ledger.
- **This is the rule-pack idea (item 4) arriving through a door we already built.** YARA rules are
  files; ours would be modules on the grid that can query the graph, hold logic, and eventually call
  a model. A better substrate than a rule DSL, obtained without designing one.
- **Two constraints, both already written down.** `req-grid-search-canonical-read` treats module
  registration as deliberate **break-glass** — a module bypasses the canonical read interface
  because it can do anything the ORM can; `req-grid-search-canonical-read-5` (Proposed) wants a
  logged opt-in. If modules become a *product* surface, and especially if third parties ship them,
  that requirement stops being optional. And the AI-endpoint step crosses the v0 read-only AI rule:
  cheap to write the boundary down now, expensive once someone has shipped one.

## Principles as predicate — item 30

The correction that matters: **principles are not the design layer, they sit above all three.** They
are the predicate each layer is judged against.

```
PRINCIPLES   statements of intent, each with an executable expression
    | governs
DESIGN       the intended shape         -> must trace to a principle
CONFIG       what is actually written   -> must satisfy the principles
OPERATION    what actually ran          -> must satisfy the principles
```

One principle yields several evaluations. *Pin what executes* is checked against config (are the
refs immutable?) and against operation (did anything actually run from a mutable ref?) — and the two
can disagree, which is itself the finding.

**The analogy is exact and the machinery already exists.** TAP runs this discipline on itself:
requirements with RIDs, acceptance criteria, tests that cite them, `TAP-IMPLEMENTS` claims binding
code to requirements, guards enforcing the binding, and traceability hunting the unaccounted in both
directions. Item 30 turns that outward — the operator's CI/CD system gets requirements (principles),
acceptance criteria (expressions), and implementations (config and operation).

**The executable primitive is already built.** `Search` dispatches `gryphon`, `orm` and `module` and
returns a uniform envelope, so a principle is a statement plus an edge to its validating Search.
This settles item 29 permanently: **modules are load-bearing, not a fallback** — some principles
cannot be a graph pattern and need a real program.

Four design constraints worth fixing now:

- **Strictness is a parameter of the expression**, not a new principle. Otherwise one principle
  forks into forty near-identical ones.
- **Status must be honest.** `declared` (prose) -> `expressible` -> `expressed` (a Search exists) ->
  `evaluated` (it ran, with evidence). A principle stuck at `declared` is a promise; the gap belongs
  in the open rather than papered over, for the same reason traceability tracks Unaccounted.
- **Coverage is asymmetric.** "Every principle has an expression" is checkable immediately; "every
  design element traces to a principle" needs design modelled at all, and design is the least-built
  layer. Say so up front.
- **Two authors.** We ship a default set — the product's opinion, and what makes git-serious *say
  something*. The operator writes theirs — their truth, and what makes it theirs. Neither may
  masquerade as the other.

**This is also the compliance story arriving early.** A principle plus expression plus evaluation
plus evidence *is* an attestation, and `attestation` appeared in seven independent standards in the
sweep — so these records are exportable in a vocabulary auditors already speak. A FedRAMP KSI is a
principle with a test wearing a regime's clothing.

### Placement — decided 2026-08-27

**Not TAP core.** Core's job is to make principles *expressible*, and it already does: typed
nodes/edges from plugins, `Search` with three dispatch modes, `execute_search`, `schedule`, history,
dimensions. Nothing in core needs to grow; a gap, if one appears, gets named as a specific gap
pulled by a specific consumer rather than assumed in advance. (The first instinct — "this is
general, therefore core" — is the roadmap's own red flag: *adding capabilities because they are
obviously part of the platform*.)

**A substrate plugin owns the vocabulary: `dcom_core`** (distribution `dcom-core-tap`). It defines
`principle`, its edge to the Search expressing it, its edge to what it governs, and an evaluation
record — reusing `compliance_core`'s `evidence` and `finding` rather than minting rivals.

Named `dcom_core` deliberately: these principles are **specific to the design/config/operation
validation process**, not universal first principles, and the name should not over-claim. The
collision with Microsoft's Distributed Component Object Model was raised and dismissed on the
grounds that plugin slugs are seen only deep inside TAP, where the context is unambiguous. `_core`
over `_principles` because it matches the substrate convention that signals "depended upon downward"
and leaves room for the rest of DCOM if the layers themselves ever want modelling.

**Consumers, in order:** git-serious (first, and what pulls it into existence), `fedramp_20x_ksi`
(a KSI *is* a principle with a test), code-paths later. Three consumers, one vocabulary, none of it
in core — the multi-pay-off shape the product map argues for.

## Operational principles — ours, drafted 2026-08-27

Item 13 says to define ours first and take it for a spin. These are extracted from what our
pipelines already do; they are the candidate validators.

1. **One required check, computed** — the gate is an aggregator that judges every lane explicitly,
   in code, in the repository.
2. **Fail toward more work** — unknown state means the heaviest tier; shortcuts are positively
   justified or not taken.
3. **Define the standard once** — one reusable admission workflow, called by every repository.
4. **Untrusted input never meets privilege** — where a privileged step is needed, the untrusted half
   is stripped and its output crosses as data, never as text interpolated into a shell.
5. **Pin what executes** — third-party actions by full commit hash; a moving reference is a
   deliberate, written-down exception.
6. **Least privilege, declared** — `permissions: {}` then grant per job; nothing inherits.
7. **The same road for everyone** — every change reaches main through the gate, maintainer included.

Each should acquire a machine-checkable expression and a visualisation. The interesting property is
that violations of 4, 5, 6 and 7 are all *observable from the graph we are already building*.
