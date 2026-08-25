# Products Roadmap

`road-products` — the product roadmap. Governed by [spec-roadmap.md](../specs/spec-roadmap.md).

This is the demand/intent layer above specs: which work matters, in what order, by when, and why. It
exists to keep development — human and AI threads — focused on the path most likely to put real
software in front of real people. The stable shape it serves (emergence, initiatives, product lines,
naming, distribution) lives in [`product-map.md`](product-map.md).

---

## Doctrine

Standing, cross-cutting guidance. 

Status: Stable; read this to know how to judge whether work is on-path.

### Strategic posture (2026-08-25)

TAP is the center of gravity, the immediate critical path is **adoption**: getting working software into the hands of people who will run it, break it, fix it, expand it, and drive demand signals. The near-term
progression is git-serious (our own CI/CD, first customer is us) into the field, then Rampart's ops, triage and compliance capabilities behind them.

Strategy documents in this repo speak about products, capabilities, and users. 
They do not name customers, teams, or individuals, and they do not carry commercial detail — engagement specifics live off-repo.

### WOG (Way of the Grid)

The philosophy in `wog/` is central to our considerations. Entries are cited by name the way PEPs are:
`WOG-Oneness`, with multi-word entries connected by a dash — `WOG-Chaotic-Majority`. This is what makes
the P in PKFN load bearing rather than bad poetry about esoterica.

The corpus's structure, citation mechanics, and the derivations it already underwrites are specified
in [`spec-wog.md`](../specs/spec-wog.md) — tiers carried by file (`req-wog-tiers`), the name as
identity (`req-wog-identity`), citation form (`req-wog-citation`), and guard-enforced resolution of
every citation (`req-wog-resolution`). Settled entries govern; in-process entries argue.

### Emergence

Products and capabilities emerge from demand signals, scaffolding on top of one another and reaching across
product lines and plugins to tackle real-world problems.

See [`product-map.md`](product-map.md). Emergent after the fact is the mechanism of formalization: do it manually the first time (or two), then build the skill from that. Extraction is not complete until the precursor is retired or demoted to
a projection. Demand is the base case of outward recursion.  Classic. Make it work, make it right, make it fast.

### Strategic Rule

When evaluating any work, ask:

> Does this directly help the active step's Done-Test?

If no, the work is probably not current-path unless it is fixing a blocker.

### Contention

Several tracks run in parallel with one operator. When they contend, **the track closest in calendar
time to a real external user wins.** Targets are made explicit and then moved as needed; delivering
early is always an option. Missing your own target is just sloppy.

### Tracking

Doctrine and step fences are canon here. Execution tracking lives in GitHub, and nothing in GitHub
points back into this file.

| Layer | GitHub mechanism |
| --- | --- |
| Initiative | Issue Type `Initiative` + a Project single-select field |
| Product line | Project single-select field — taxonomy, not work |
| Product | its own umbrella-plugin repo |
| Feature / epic | Issue Type `Epic`, sub-issue of the initiative |
| Task | Issue Type `Task`, sub-issue of the epic |
| Dated ship gate | Milestone in the product repo |
| Cross-repo dependency | sub-issue from the product repo into core or a sub-plugin repo |
| Sprint | Project iteration field (one week) |
| The single pane | one org Project with a Roadmap view |

Thin by design: three issue levels rather than five, milestones only for dated external gates.
Everything is GraphQL-readable, so agents can maintain it and the taxonomy exports cleanly when the grid
eventually takes it over. Keep meaning in fields and links, which map to nodes and edges — never in
board-column position or manual ordering, which map to nothing.

Steps carry a `Tracking:` line pointing at their milestone once created.

### Sprints

An epic is a **scope** container; a sprint is a **time** container. They are orthogonal: epics span
sprints, and a sprint holds slices of several epics. One-week boxes, matching the cadence of the
external gates they lead up to.

Sprints exist here for one reason — to identify whether the bite being taken on is too big to chew.
Now that real time-based deadlines exist, a time-boxed collection of tasks is the thing that makes
over-commitment visible early rather than at the deadline.

The measurement is **carryover**: what was committed to the iteration versus what closed inside it.
Carryover is counted in items and needs no estimates, so there is no velocity, no points, and no
sizing. Rising carryover across consecutive iterations is the signal that a plan is fiction, and it
arrives in week two rather than week four. If carryover later proves to be dominated by a few
oversized items, a coarse size field is extracted then — from the instances, not authored ahead of
them.

Two rules make the signal mean anything:

- **Commit at the start.** An iteration's contents are set when it opens; anything added mid-flight is
  recorded as added rather than folded in silently. Without this, carryover measures nothing.
- **Contention outranks commitment.** When a track closer to a real external user displaces sprint
  work, the external user wins and the displacement shows up as carryover. That is information about
  real capacity, not a failure to be smoothed away.

### Platform Ambition vs Product Discipline

The platform can eventually support many use cases; the current mission is to make real use cases
undeniably real and use **adoption to drive stability in tap core**.  Many eyes make bugs shallow,
and in the age of AI the number of eyes is economical given our (~50k loc).

A feature is **suspect** if its main justification is: "useful eventually" / "the platform should have
this" / "makes the architecture more complete" / "would be elegant" / "necessary for the full vision."

A feature is **stronger** if its justification is: "gets the product in front of a real user" / "helps
assess a real system" / "makes findings visible" / "explains compliance status" / "reduces manual work"
/ "makes the leave-behind more valuable."

### Development Heuristic

Prefer: make it work for the first real use case → over: make it generally correct for all future use cases.
Prefer: one clear path → over: a flexible framework with no visible immediate or near-term payoff.
Prefer: a rough but working product → over: a beautifully generalized substrate.
Prefer: a feature that helps a human understand a real system → over: one that satisfies architectural completeness.

### Red Flags

- Building anything before a specific demand signal demands it.
- Adding capabilities because they are "obviously part of the platform."
- Expanding visualization before the work needs the additional view.
- Expanding AI integration before the workflow is clear.
- Building full compliance policy machinery before demonstrating a few checks.
- Making install, federation, or plugin systems robust before first field use.
- Refactoring for elegance without immediate delivery benefit.
- Chasing features that would be impressive but not necessary for the active step.
- Platform work with no demand pulling it.

### Green Flags

- Makes a real system visible.
- Turns raw collected data into understandable entities and relationships.
- Surfaces security/compliance issues and explains why they matter.
- Produces a simple, compelling visual that would make Edward Tufte nod in agreement.
- Helps a knowledgeable person say "yes, this is useful."
- Creates reusable patterns for the next product.
- Keeps the codebase understandable and tractable.
- Supports rapid iteration after feedback.

### Product Needs

What a product other people can use actually needs: defined scope with real-world usability;
extensibility from inside the app; documentation; an installation process; security; bug fixes; in-place
updates that don't break their stuff; alpha and beta users to make it real. Not all required now — tracked here so
step scoping stays honest about the distance to a product.

### AI Thread Instructions

When asked to implement, plan, review, or propose, first assess whether the work supports the active
step — do not simply comply. Respond with a brief strategic check: (1) path alignment to the active
step's Done-Test; (2) scope risk and whether a smaller version exists; (3) minimum useful version;
(4) defer list; (5) recommendation — proceed, narrow, defer, or replace with a simpler step. Use direct
language. Be skeptical of elegant overbuilding.

---

## Timeline Table

Quick-glance index. Per-step `Timeline Target` is authoritative; this table is its mirror, kept in sync
in the same edit (`req-roadmap-timeline-table`).

| Step ID | Name | Timeline Target | Status | Note |
| --- | --- | --- | :---: | --- |
| [step-products-git-serious-friends](#step-products-git-serious-friends) | git-serious to friends | 2026-08-30 | Proposed | First outside hands; friction log is the deliverable |
| [step-products-grid-mutability](#step-products-grid-mutability) | Grid mutability | 2026-09-06 | Proposed | Tombstone semantics; gates git-serious release |
| [step-products-git-serious-private](#step-products-git-serious-private) | git-serious private preview | 2026-09-06 | Proposed | Multiple outside orgs; install skill runs unattended |
| [step-products-grid-paths](#step-products-grid-paths) | Path primitives | ~2026-09-07 | Proposed | Rolling first; gates triage |
| [step-products-collector-run-configs](#step-products-collector-run-configs) | Collector run configs | ~2026-09-07 | Proposed | First genuine core expansion; follows paths |
| [step-products-git-serious-alpha](#step-products-git-serious-alpha) | git-serious public alpha | ~2026-09-22 | Proposed | Sigstore gate; marketplace listing if registration cleared |
| [step-products-rampart-preview](#step-products-rampart-preview) | Rampart private preview | mid-2026-10 | Proposed | Discovery + triage + paths in front of an external team |
| [step-products-20x-continuous](#step-products-20x-continuous) | 20x continuous KSI tests | ~2026-11 (TBD) | Proposed | Likely deeper; other things moving in the background |

**Closeouts.** Full narratives remain in git history.

| Step ID | Status | Closeout |
| --- | --- | --- |
| step-rampart-sam-demo | Achieved | Demo delivered 2026-05-31, second demo the same week; samsite retained as a demo and test target |
| step-rampart-launch-ready | Achieved | Auth, boot, and installable plugins landed; the first-AI leg folds forward into the git-serious skill set and the 20x MCP surface |
| step-rampart-first-paid-assessment | Superseded | Engagement tracking moves off-repo; the demand layer no longer carries named engagements |
| step-rampart-first-paying-customer | Superseded | By the adoption-first product ladder above |
| step-rampart-self-sufficiency | Superseded | By the adoption-first posture |
| step-rampart-big-bang | Superseded | The public alpha arc is the public launch |

---

## Steps

Steps are ordered but may overlap; concurrency is shown by the timeline table, not by ordering.

### step-products-git-serious-friends
Status: `Proposed`
Timeline Target: `2026-08-30`
Objective: A friend stands up git-serious against their own git platform using the docker command and
the AI install/config skill, and sees a legible projection of their CI/CD.
Done-Test: At least one org that is not ours is ingested by an operator who is not George, and the
friction log from their AI-driven install is captured.
Non-Goals: marketplace listing; signing beyond pinned digests; git platforms beyond GitHub.com;
cluster-side gitops (ArgoCD/Flux) collectors; polish.

Our own CI/CD is the demo; someone else's org is the test. Our setup is idiosyncratic enough that it
only proves the collector against shapes we hand-built, so the ask is "point it at yours," not "look at
ours."

First work item: an inventory diff of what the git-serious story needs — CI runs, branch protections,
rulesets, review posture, action pins — against what `github_core` collects today. That gap is the
build list.

### step-products-grid-mutability
Status: `Proposed`
Timeline Target: `2026-09-06`
Objective: The grid can represent node-level absence, so a collector that completely enumerates a scope
can tombstone what is no longer there and the view stays accurate to the observed system.
Done-Test: A resource removed from an observed account or org is tombstoned on the next complete run,
its history remains queryable, and a deliberately partial run tombstones nothing.
Non-Goals: the authority layer (which run may reconcile — that is run configs); any write, delete, or
remediation against the observed system; hard deletion of grid rows.
Depends-on: `req-grid-node-observation` (the field-level absence convention this extends); the
reconciliation seam named in `spec-grid-import-grift.md`.

A prerequisite for git-serious release rather than a Rampart-only concern: git-serious observes a system
that changes constantly, where runners go away and repos get mothballed. This is the expensive-to-retrofit
half of reconcile, so it lands while the surface is open; the policy layer follows with run configs.

### step-products-git-serious-private
Status: `Proposed`
Timeline Target: `2026-09-06`
Objective: git-serious runs in multiple outside organizations without George on the call.
Done-Test: Multiple outside orgs are ingested; the AI install skill carries an operator through setup
unattended; an issue channel is live and receiving real reports.
Non-Goals: public listing; paid anything; support commitments beyond best-effort.

### step-products-grid-paths
Status: `Proposed`
Timeline Target: `~2026-09-07 (rolling first, ahead of collector run configs)`
Objective: The samsite path proof-of-concept becomes real grid path primitives with traversal support —
the platform capability triage ranks against.
Done-Test: Paths are first-class on the grid and traversable by query, and a path through a real
collected system can be retrieved and rendered.
Non-Goals: general graph-theory sprawl; path features beyond what triage demands; the code-paths product.

The largest platform lift in the plan, and fenced accordingly.

### step-products-collector-run-configs
Status: `Proposed`
Timeline Target: `~2026-09-07`
Objective: Collector run configs land as the first genuine core expansion — the surface carrying a run's
permissions, including authority to reconcile grid-side absence on an aws_core run.
Done-Test: An aws_core run configured with reconcile authority tombstones a resource deleted from the
account; the same run without that authority does not; and a run config is the only place that authority
is expressed.
Non-Goals: any write, delete, or remediation against the observed cloud account — reconcile tombstones
grid nodes only, and collector credentials stay read-only. No hard deletion of grid rows. No migration of
git-serious off its baked-in config.

Sequencing: paths first, then collector config. git-serious continues on the baked-in collector / secret
config, shipped as explicitly unstable. Design constraints are in
[`product-map.md`](product-map.md#enabling-capability); the load-bearing ones are that absence must be
proven before it is acted on, that reconcile stays inside the enumerated scope, and that baked-in config
is a degenerate run config rather than a parallel code path.

### step-products-git-serious-alpha
Status: `Proposed`
Timeline Target: `~2026-09-22`
Objective: Anyone can boot git-serious and use it against their own git platform.
Done-Test: A stranger boots the published image and reaches a working instance without our help, and
issues arrive from people we did not recruit.
Non-Goals: paid listing; stability promises on config shape; git platforms beyond GitHub.com; support
commitments beyond community best-effort.

Gates: sigstore-signed images (the supply-chain trigger's resolution); quickstart documentation;
marketplace listing live if seller registration has cleared; naming locked before any registry
publication.

### step-products-rampart-preview
Status: `Proposed`
Timeline Target: `mid-2026-10`
Objective: Rampart's discovery and triage capabilities, standing on the path primitives, go in front of
an external team running against their own environment.
Done-Test: An external team runs the preview against their own environment, and triage ranks real
findings against real paths in a way a knowledgeable person agrees is useful.
Non-Goals: productized billing; multi-tenant polish; full compliance machinery; anything aimed at a
public launch.

### step-products-20x-continuous
Status: `Proposed`
Timeline Target: `~2026-11 (TBD)`
Objective: Demonstrate core 20x functions — continuous tests against a handful of live KSIs, including
vulnerability management.
Done-Test: Continuous tests run unattended against live KSIs and produce results a compliance
practitioner accepts as evidence-shaped.
Non-Goals: full KSI coverage; certification claims; a baked-in AI management capability.

The first AI integration rides here as an MCP plugin — read-only, per the v0 AI rule — ahead of a
baked-in capability. That surface may be worth pulling earlier into git-serious, since preview users'
own agents are its natural first consumers. Timing is likely to move further out; other things are
moving in the background, and that is what explicit targets are for.

---

## Future

- **Structured strategy system.** A fuller strategy/tactic taxonomy is a captured good idea, not built.
  Demand trigger: a single step grows enough internal sub-actions to need its own file
  (`req-roadmap-primitive`).
- **Grid-native roadmap.** Roadmaps eventually live on the grid rather than in markdown. See the central
  hub seam in [`product-map.md`](product-map.md#named-seams).
