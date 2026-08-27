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
