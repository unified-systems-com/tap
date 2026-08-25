# Products Roadmap + Map — DRAFT (2026-08-24)

Status: `Draft — assembled in the 2026-08-24 strategy session`
Purpose: Stage the replacement for the existing demand layer. On approval this splits into
`plan/road-products.md` (via `git mv road-rampart.md`) and a rewritten `plan/product-map.md`,
and the superseded files (`road-rampart-refresh-draft.md`, `strategy-original-recovered.md`,
`strat-sam-demo.md`) are deleted at HEAD — git history is the posterity archive.

**Authorship convention (per AGENTS.md):** George authors strategy content. Text in this draft
is George's session prose verbatim (typo-level cleanup only). Markers like
*[agent-draft: …]* are agent-proposed wording George explicitly agreed to in discussion but has
not yet written in his own voice — bless, rewrite, or cut each one. Markers like
*[GEORGE: …]* are empty slots only George can fill.

---

# Part A — Product Map (replaces `product-map.md`)

## Emergence: the grid and what grows from it

The concept of emergence is fundamentally that the grid is a foundational concept from which
higher and more complex forms can emerge. TAP is the first instantiation of the grid — if we do
it right, in very short order it won't be the only one.

On TAP we've built skills to define new nodes and edges. On top of that we built the collector
and plugin skills, which call the node/edge/collector skills beneath them. On top of the plugin
skill we will define a **create-product skill** — calling the plugin-creation skills (and others
TBD) to stand up the machinery necessary to manage a standalone product and make it available
for use by anyone, with adjacent sub-skills for building CI/CD, product documentation, launch
website, and community support / interaction.

Above that is the **product line** — a suite of tools / plugin packs. Each of these builds
rests on an emergent skill scaffolding whose existence enables the higher-order configuration
to come into being. Each will need to include how to manage and evolve its components over
time — which will necessitate standardizing versioning throughout the stack, including base
models, edges, collectors, and plugins, because in security you never do anything once.

**Emergent after the fact (the discipline).** We do the thing manually the first time (or two),
then build the skill from that. *[agent-draft: No rung of the scaffold is authored
speculatively — each is extracted from a concrete instance and validated by the next one. The
create-product skill is distilled from building git-serious by hand and proven when it stands
up the second product.]*

The ladder:

| Rung | Skill layer | Status |
| --- | --- | --- |
| Node / Edge | `add-model`, `add-edge` | Built |
| Collector | `build-collector` | Built |
| Plugin | plugin-creation skills | Built |
| Product | create-product skill | To extract from the git-serious build |
| Product line | TBD | Emerges after ≥2 products |

## Product: git-serious

The application for observing and monitoring a complex gitops deployment. Our first customer is
us: we want to view and understand the whole CI/CD system we just built — classic scratching
our own itch, and demoing on the one system we control and know inside and out.

- **Form:** an overarching product plugin, in its own repo under the unified-systems org, with
  a boot profile that slots in the necessary stuff underneath. Ships as a self-contained
  appliance build — plugins baked into the image, simple docker launch command.
- **AI-driven install and config:** a fleshed-out config and management AI skill set (the
  samsite-POC pattern). Skill-based, so executable by anyone with an AI account — which, if
  they're running git-serious, is literally everyone we care about. This release is explicitly
  a test of AI-driven install and config.
- **Platform extensibility:** we're building against GitHub.com, but this should be extensible
  to other git platforms by users and the interested. *[agent-draft: the neutral git/CI
  vocabulary (repo, branch, pipeline run, protection rule, …) lives in a `git_core`-style
  substrate plugin — the proven `*_core` extraction pattern — with the GitHub collector as its
  first implementation. Extensibility by vocabulary, not pre-built adapters.]*
- **Purpose:** get the application into the field and being used by people in real
  environments. First contact with the customer.

## Product line: Rampart (secops)

A suite of tools / plugin packs performing various aspects of secops:

- **Discovery and observability** — building out aws_core, importing git-serious for CI/CD.
- **Vulnerability triage** — the Criticalsec process for vuln severity ranking against critical
  paths in a cloud service. Requires the path primitives in TAP (POC'd on samsite; to be
  productized into grid primitives — see the paths step).
- **Rampart-20x** — capable of managing a complex org's certification and monitoring.

The prior map's solution-set taxonomy is dropped until demand; other demand signals have
appeared and are taking the lead.

**Semaphore** (critical-infrastructure vertical) remains the planned second product line, gated
on Rampart demonstrably working in the field.

## Posture: alpha, in public, blast-radius constrained

A key design element: we are leaning hard into alpha / preview / YMMV / just-make-it-work
territory. Perfection is not the goal — proving the concept and demonstrating that others can
bring it up, use it, find issues, fix them, and submit improvements is the name of the game.
The focus is gaining users and feedback.

We carry a solid security story for CI/CD operations — what we've been building over the last
two weeks combined with the firm foundation of the TAP system to this point. We're threading a
needle: useful in critical environments, but blast-radius constrained to keep us off any
critical paths until there's sufficient use in the field for the system to stabilize under its
own operational pressure.

Everything is freeware. Cloud-marketplace presence (Amazon first) is an opt-in, optional
support channel — no additional licensing — and a repeatable distribution model for the future.

## Distribution

*[agent-draft: Plugins graduate from git-source installs to the native registry (PyPI via uv) —
the adopt-native-distribution doctrine. Registry names are permanent, so the naming lock
(products, plugin package namespace) gates publication. PyPI trusted publishing (OIDC from
Actions, no long-lived tokens) is the mechanism. Signing ladder: pinned digests + content-hash
floor for the friends/private previews; sigstore-signed images are a public-alpha gate; TUF
stays deferred.]*

## Named seams (back pocket, not built)

- **Central hub** — an ongoing TAP instance managing the overarching strategy. Not on the
  roadmap; reached for once operational complexity demands offloading to the grid.
- **Stack-wide versioning** — standardized versioning for base models, edges, collectors,
  plugins. *[agent-draft: trigger = the first breaking change shipped to a field instance;
  plugins already carry versioning via uv/tags/`requires_tap`.]*
- **Product-line skill rung** — extracted only after two products exist.

---

# Part B — Roadmap (replaces the step/timeline content of `road-rampart.md`)

## Doctrine

*[agent-draft: Carried forward unchanged from road-rampart.md: the Strategic Rule ("does this
directly help the active step's Done-Test?"), Platform Ambition vs Product Discipline, the
Red/Green flags, and the AI Thread Instructions. Removed: the 2026-06-24 posture paragraph
(superseded by Part A's posture) and monetization framing throughout.]*

**New doctrine entries:**

- **Emergence** — see Part A. Emergent after the fact: manual first (or twice), skill second.
- **Contention rule** — *[agent-draft: when tracks contend for attention, the track closest in
  calendar time to a real external user wins.]*
- **Supply-chain trigger status** — *[agent-draft: the "first non-George user" trigger FIRES at
  the git-serious friends preview. Resolution: digest floor now, sigstore at public alpha, TUF
  deferred — see Part A Distribution.]*
- **Public-repo content rule** — *[agent-draft: from 2026-08-24 forward the demand layer names
  no customers, teams, or individuals and carries no commercial detail. It speaks of products,
  capabilities, and users in aggregate; engagement specifics live off-repo. Historical names
  already in git history are not restated in new text.]*
- **Tracking** — *[agent-draft: doctrine + step fences are canon here; execution tracking lives
  in GitHub — per-repo milestones hold the dated work items, one org Project (Roadmap view)
  spans repos. Steps carry a one-directional `Tracking:` link to their milestone. Nothing in
  GitHub points back.]*

## Timeline Table

| Step ID | Name | Timeline Target | Status | Note |
| --- | --- | --- | :---: | --- |
| step-products-git-serious-friends-preview | git-serious to friends | 2026-08-30 | Proposed | Tentative target: preview to friends by EOW |
| step-products-git-serious-private-preview | git-serious private preview | 2026-09-06 | Proposed | The following week |
| step-products-git-serious-public-alpha | git-serious public alpha | ~2026-09-15 | Proposed | Mid-September launch |
| step-products-grid-paths | Path primitives in TAP | ~2026-09-15 | Proposed | Productize the samsite path POC; gates triage |
| step-products-rampart-preview | Rampart private preview | 2026-09-30 | Proposed | Discovery + triage + paths, in front of a real team |
| step-products-20x-continuous | 20x continuous KSI tests | ~2026-10-31 | Proposed | Timing TBD; MCP read-only as first AI integration |

**Closeouts of prior steps** *(full narratives live in git history)*:

| Step ID | Status | Closeout |
| --- | --- | --- |
| step-rampart-sam-demo | Achieved | (was "Completed" — vocabulary fix) Demo delivered 2026-05-31, second demo same week; samsite retained as demo/test target |
| step-rampart-launch-ready | Achieved | Auth, boot, installable plugins landed; the first-AI leg folds forward into the git-serious skill set and the 20x MCP surface |
| step-rampart-first-paid-assessment | Superseded | *[agent-draft: Engagement tracking moves off-repo per the public-repo content rule; the demand layer no longer carries named engagements or commercial work.]* |
| step-rampart-first-paying-customer | Superseded | By the adoption-first product ladder above |
| step-rampart-self-sufficiency | Superseded | By the adoption-first posture (Part A) |
| step-rampart-big-bang | Superseded | The public alpha arc is the public launch |

## Steps

### step-products-git-serious-friends-preview
Status: `Proposed`
Timeline Target: `2026-08-30`
Objective: *[agent-draft: A friend stands up git-serious against their own GitHub org using the
docker command + the AI install/config skill, and sees a legible projection of their CI/CD.]*
Done-Test: *[agent-draft: At least one non-us org ingested by a non-George operator; the
friction log from their AI-driven install is captured. (The foreign-org element is the guard
against dogfood overfit — our org is the demo, theirs is the test.)]*
Non-Goals: *[agent-draft: marketplace listing; signing beyond pinned digests; git platforms
beyond GitHub.com; gitops-cluster (ArgoCD/Flux) collectors; perfection.]*
Tracking: *(milestone in the git-serious repo, once created)*

First work item: *[agent-draft: inventory diff — what the git-serious story needs (CI runs,
branch protections, rulesets, review posture, Actions pins, …) vs what `github_core` collects
today. That gap is the EOW build list.]*

### step-products-git-serious-private-preview
Status: `Proposed`
Timeline Target: `2026-09-06`
*[GEORGE: fence — proposed shape: multiple outside orgs; install skill survives without George
on the call; issue channel live.]*

### step-products-git-serious-public-alpha
Status: `Proposed`
Timeline Target: `~2026-09-15`
*[GEORGE: fence — proposed shape: anyone can boot it; sigstore-signed images (the gate);
quickstart docs; community support minimal viable (README, issue templates, SECURITY.md already
org-wide); marketplace listing live if seller registration has cleared; naming locked before
any PyPI publication.]*

### step-products-grid-paths
Status: `Proposed`
Timeline Target: `~2026-09-15`
Objective: *[agent-draft: The samsite path POC becomes real grid path primitives + Gryphon
traversal support — the platform capability the Criticalsec triage process ranks against.]*
Non-Goals: *[agent-draft: general graph-theory sprawl; path features beyond what triage
demands. Fenced hard — this is the largest platform lift in the plan.]*

### step-products-rampart-preview
Status: `Proposed`
Timeline Target: `2026-09-30`
Objective: Components for discovery and triage, developed in parallel along with the path
implementation (POC'd on samsite) — private preview end of September.
*[GEORGE: Done-Test — no names per standing doctrine; the shape to fill in: an external team
runs the preview against their own environment and <observable signal>.]*

### step-products-20x-continuous
Status: `Proposed`
Timeline Target: `~2026-10-31 (exact timing TBD)`
Objective: The capability to demonstrate core functions: implement continuous tests against a
handful of live KSIs (including vuln mgmt).
*[agent-draft: First AI integration rides here as an MCP plugin (read-only, per the v0 AI rule)
ahead of a baked-in full AI management capability — and the MCP surface may be worth pulling
earlier into git-serious, since preview users' own agents are the natural first consumers.]*

---

# Part C — Mechanical follow-through (agent work, ONLY after George's explicit thumbs-up — nothing below touches GitHub until then)

1. `git mv plan/road-rampart.md plan/road-products.md`; fold Part B in; rewrite
   `plan/product-map.md` from Part A; delete this draft + the three superseded files.
2. Update navigation pointers (CLAUDE.md, AGENTS.md; grep the ~9 spec/docs references to
   `road-rampart.md` / `product-map.md` and fix paths in the same PR — docs-tier gate).
3. Stand up the org Project ("TAP Products", Roadmap view) + milestones; add `Tracking:` links.
4. Start AWS Marketplace seller registration (calendar lead time; independent of the alpha).
5. Naming-lock decision list for PyPI: product names, plugin package namespace.
