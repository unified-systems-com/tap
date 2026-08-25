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

Products and capabilities emerge from demand signals, scaffolding on top of one another and reaching across initiatives, product lines, products, and plugins to tackle real-world problems.  It's recursive in reverse.

See [`product-map.md`](product-map.md). Emergence after the fact is the mechanism of formalization: do it manually the first time (or two), then build the skill from that. Extraction is not complete until the precursor is retired and / or the pre-standardized instance proceeds to the future using the same maintenance processes that future instances will utilize (it's a great place to build that maintenance process). Classic make it work, make it right, make it fast approach.

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
| Initiative | Project single-select field — Rampart |
| Product line | Project single-select field — ops / security / compliance |
| Product | its own umbrella-plugin repo — a container, not an issue |
| Roadmap step | Issue Type `Epic` in that product's repo |
| Component work pulled by a step | Issue Type `Epic` in the repo where the work lands, sub-issue of the epic that pulls it |
| Task | Issue Type `Task`, sub-issue of an epic |
| Dated ship gate | Milestone in the product repo, matching the step's Timeline Target |
| Cross-repo dependency | sub-issue reaching from one repo's epic into another repo |
| Sprint | Project iteration field (one week) |
| Size | Project single-select field — S / M / L |
| The single pane | one org Project with a Roadmap view |

A product is a repo holding several epics, not one big epic — each dated outcome in the roadmap is its
own epic, and the ones that pull core work parent an epic in the repo where that work lands. So the
usual depth is epic → task, going one deeper where a cross-repo epic hangs off the epic demanding it.
Depth follows the work; it is not a quota. Initiative and product line are board *fields* rather than
issue levels — the composition hierarchy they describe lives in boot profiles, not in issue trees
(see [`product-map.md`](product-map.md)).

Epic and milestone are not redundant: the milestone carries the date and the in-repo progress bar, the
epic carries the tree that crosses repos. A step with no cross-repo children needs only the milestone.

Thin by design: milestones only for dated external gates, no issue level invented that the work does
not already have. Everything is GraphQL-readable, so agents can maintain it and the taxonomy exports cleanly when the grid
eventually takes it over. Keep meaning in fields and links, which map to nodes and edges — never in
board-column position or manual ordering, which map to nothing.

Steps carry a `Tracking:` line pointing at their milestone once created.

**One entry per fact.** A step's fence — Objective, Done-Test, Non-Goals, Depends-on — is canon and
lives here. Its decomposition into epics, tasks, sizes, sprint assignment and status lives only in
GitHub. Neither restates the other, so there is no second copy of the work breakdown to keep in sync
(`WOG-Oneness`).

### Sprints

An epic is a **scope** container; a sprint is a **time** container. They are orthogonal: epics span
sprints, and a sprint holds slices of several epics. One-week boxes, matching the cadence of the
external gates they lead up to.

Sprints exist here for one reason — to identify whether the bite being taken on is too big to chew.
Now that real time-based deadlines exist, a time-boxed collection of tasks is the thing that makes
over-commitment visible early rather than at the deadline.

Two instruments, one prospective and one retrospective.

**Size (S / M / L)** is the prospective read: what am I taking on, judged before the sprint opens.
Size keys on **uncertainty and span, not hours** — what blows up a calendar here is a design question
hiding inside the work, not work that is merely large and known.

**We are allowed to do hard things. They just shouldn't be unknowns.** Difficulty is not the
disqualifier; unresolved questions are. A hard, large, well-understood task is admissible — you know
what you are building and roughly what it will take. The same task with an open design question inside
it is not, because the question will consume the sprint and the estimate was never about the work.
Resolving the unknown is itself a task, and usually a small or medium one: the path work is the
example, where the structuring and concepts were settled in an earlier session, leaving hard-but-known
implementation behind it.

| Size | Means | Sprint admission |
| --- | --- | --- |
| S | One sitting. Known shape, no open questions. | Admits freely. |
| M | Several sessions. Known shape, more surface. | Admits; a sprint of all-M is already a full sprint. |
| L | Carries an unresolved question, spans repos or gates, or needs a design decision first — *not* merely difficult. | **Unscoped large tasks should not enter a sprint.** Scope then decompose into S/M first, it's not like we're doing rocket science here (yet)|

That last row is the gate: L is not an estimate, it is an instruction to break the work down before
committing to it. A sprint that admits an L is a sprint that has already lost the ability to tell you
whether the bite was too big.

**Carryover** is the retrospective read: what was committed to the iteration versus what closed inside
it. Rising carryover across consecutive iterations is the signal that a plan is (bad) fiction, and it arrives
in week two rather than week four.

The loop between them is the point — comparing the sizes going in against the carryover coming out is
what calibrates the sizes over a few sprints. So sizes are set when an item enters a sprint and are
**not revised retroactively**: resizing an item after discovering it was hard destroys the only
evidence that it was mis-sized.

Sizes stay ordinal labels. They are never converted to numbers or summed — the moment S/M/L becomes
1/3/8 it is points, and points reintroduce velocity, which measures nothing real when the work is
carried by one human and a variable number of agents.

Two rules make the signal mean anything:

- **Commit at the start.** An iteration's contents are set when it opens; anything added mid-flight is
  recorded as added rather than folded in silently. Without this, carryover measures nothing.
- **Contention outranks commitment.** When a track closer to a real external user displaces sprint
  work, the external user wins and the displacement shows up as carryover. That is information about
  real capacity, not a failure to be smoothed away.

**Clock-time awareness.** Size is also a rough conceptual track of how much clock time a session is
consuming. Burning a lot of time on a small task means one of two things, and both are worth catching:
either it was never small, or the bigger tasks are being avoided. The second reading is the more
useful one — time sunk into small work is a common shape for avoidance, and it looks like productivity
from the inside.

There is no precise tracking for this today and none is being built. It is a personal awareness
practice, with one honest limitation to work around: an AI thread has no internal sense of elapsed
time and cannot be relied on to notice that a session has run long. It can read a clock when asked,
so ask. A latent signal already exists if this ever needs teeth — commit timestamps against the items
they close would derive real elapsed time per task from data already being written — but that is a
named seam, not a plan.

### Platform Ambition vs Product Discipline

The platform can eventually support many use cases; the current mission is to make real use cases
undeniably real and use **adoption to drive stability in TAP core**.  Many eyes make bugs shallow,
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
| [step-products-git-serious-self](#step-products-git-serious-self) | git-serious on our own repo | 2026-08-30 | Proposed | Ours standing and legible; demo to friends creates the pull |
| [step-products-git-serious-friends](#step-products-git-serious-friends) | Friends install their own | 2026-09-06 | Proposed | First outside org; friction log is the deliverable |
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

### step-products-git-serious-self
Status: `Proposed`
Timeline Target: `2026-08-30`
Objective: git-serious is standing, pointed at our own repo, and we can look at our own CI/CD and
understand it — then show it off to friends.
Done-Test: A running git-serious instance projects our own org's CI/CD legibly enough that looking at
it teaches us something we did not already know about our own pipeline, and it survives being
demonstrated to someone else.
Non-Goals: anyone else installing it; marketplace listing; signing beyond pinned digests; git platforms
beyond GitHub.com; cluster-side gitops (ArgoCD/Flux) collectors; polish.

Scratching our own itch, on the one system we control and know inside and out. The demo to friends is
what turns this into demand for the next step — they see ours, they want one.

First work item: an inventory diff of what the git-serious story needs — CI runs, branch protections,
rulesets, review posture, action pins — against what `github_core` collects today. That gap is the
build list.

### step-products-git-serious-friends
Status: `Proposed`
Timeline Target: `2026-09-06`
Objective: Friends install their own git-serious and point it at their own organizations.
Done-Test: At least one org that is not ours is ingested by an operator who is not George, using the
docker command and the AI install/config skill, and the friction log from their install is captured.
Non-Goals: public listing; paid anything; support commitments beyond best-effort; git platforms beyond
GitHub.com.

Ours is the demo; theirs is the test. Our setup is idiosyncratic enough that it only proves the
collector against shapes we hand-built, so the ask is "point it at yours," not "look at ours." The
friction log is the real deliverable — this is the first field test of AI-driven install and config.

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
Depends-on: grid mutability (tombstoning) — an additive-only view is wrong about a system whose
runners and repos come and go, so release waits on it; path primitives and collector run configs
follow behind it. Constraints in [`product-map.md`](product-map.md#enabling-capability); work tracked
in GitHub.

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
- **Retros.** Not adopted, worth considering. All the cool kids do them.

  The instrument sprints already provide is *quantitative* — carryover says whether the bite was too
  big. A retro is the *qualitative* half: why it was too big, what kept getting interrupted, which
  estimate was wrong for a reason worth remembering. Sizes calibrate against carryover on their own;
  they do not explain themselves.

  Some of this already happens under another name. The AARs in `docs/aar/` are retros for a completed
  arc, and this roadmap's step closeouts record outcomes. What is missing is the short, regular kind
  tied to the sprint boundary rather than to finishing something big.

  Demand trigger: **two or three sprints run with carryover that nobody can explain.** That is the
  point at which the number is telling us something the numbers cannot decode. Adopting one before
  then is ceremony ahead of signal — and a retro with a single participant is a diary, so the shape
  worth borrowing (a written pass over what carried and why, ~15 minutes, findings that become items
  rather than feelings) matters more than the ritual.
