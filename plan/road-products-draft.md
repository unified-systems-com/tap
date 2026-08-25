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
| Initiative | — | The top rung; see below |

## Initiatives

**Initiatives** sit above product lines and plugin sets. Up to this point we've been discussing
work inside the **Rampart initiative** — which encompasses all things infrastructure / security /
cloud / ops-facing capabilities.

*[agent-draft: An initiative is the widest demand-side grouping: a domain of capability, not a
thing we ship. Product lines crystallize inside it; plugin sets and products realize those. It
is the natural top rung of the emergence ladder — the level at which we decide what family of
problems we are in, while everything below it decides what we build for that family.]*

**Platform work is a cross-cutting concern — ruled 2026-08-25.** It exists independent of any
initiative. TAP is a means, not an end. Every initiative will drive work on the platform, not
the other way around, so TAP remains a solo repo by design, referenced from plugins and product
repos accordingly.

*[agent-draft: This is load-bearing beyond taxonomy. Making TAP an initiative would put it on
the same axis as Rampart, implying the two compete as peers for priority — and would open a
channel for platform work with no demand behind it, which is precisely the overbuilding the
roadmap doctrine exists to prevent. Platform work is always DERIVED demand, and the structure
should make that impossible to forget.*

*Mechanically this needs no new machinery: core work lives in the TAP repo with its own
release-driven milestones, and the demand relationship is carried by the sub-issue edge — a
product repo's epic has sub-issues in the TAP repo, so the parent tells you which initiative
pulled it. A core issue with no parent is either ordinary maintenance (security patches,
dependency bumps, CI upkeep — legitimately unparented) or platform work nobody asked for, which
is the smell worth catching. That makes the doctrine checkable rather than merely stated.]*

*[GEORGE: one ruling still open — is git-serious inside the Rampart initiative (ops-facing, so
presumably yes) or its own?]*

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
- **Translated pages:** needed for git-serious — we want this to spread as far as possible.
  *[agent-draft: Ground truth 2026-08-25 — `USE_I18N=True` is set but nothing is marked: 34
  core templates, zero `{% trans %}`, no locale dirs. So the rule is mark-as-you-write for
  every new git-serious page (free at authoring time), plus one bounded mechanical retrofit
  pass over the existing 34. Three surfaces, only one of which gettext solves: UI chrome
  (gettext), docs/landing pages (separate toolchain), and dynamic content — collected data
  stays verbatim, while AI-generated explanation is naturally generated in the reader's
  language. Translation is also the best non-code contribution on-ramp we have, which serves
  the adoption posture directly. Open risks to name rather than solve now: who reviews a
  translation (a mistranslated security finding is worse than an untranslated one — machine
  output ships labeled as machine output), which languages (pick from real signal, don't
  guess), and RTL layout if that signal ever appears.]*

## Product = an over-arching plugin with its own repo

A product lives as an over-arching plugin — Rampart will be its own plugin with its own repo.
That gives us the ability to assign milestones inside that product to that repo. We can then
coordinate across other plugins, such as sub-plugins in their own repos, but that becomes the
product-specific locus of organization.

*[agent-draft: This makes the product repo both a code artifact and the coordination point,
which is the useful part — the boot profile that composes the product is the same artifact that
defines what the product IS, so "what's in Rampart?" is answered by reading a pinned record
rather than a wiki. It also anchors the versioning story ("in security you never do anything
once"): a product release is a pinned composition of sub-plugin versions — the boot-record-as-BOM
pattern already proven in the field.*

*Two mechanics to keep straight, because they're easy to conflate: a **milestone** can only hold
issues from its own repo, so it tracks what ships FROM the product repo; cross-repo dependencies
(a core capability in the TAP repo, a collector change in aws_core) ride **sub-issues**, which
do cross repos and roll up. The Project is the pane over both. Trying to make milestones do
cross-repo coordination is the standard way this setup frustrates people.*

*One thing to verify before committing: whether the plugin system accepts a composition-only
plugin — dependencies, boot profile, and pages but no models or collectors of its own — or
whether `validate_plugin --strict` expects more. If it doesn't, that's a small conformance gap
to close, not a reason to change the shape.]*

## Product line: Rampart (secops)

A suite of tools / plugin packs performing various aspects of secops:

- **Discovery and observability** — building out aws_core, importing git-serious for CI/CD.
  aws_core will need a feature / CI cycle to detect and update itself with new AWS services.
  That's a longer pole, but should be considered when going through the expansion of the
  aws_core scanner to track the things we'll need for 20x.
  *[agent-draft: Split that into two claims of very different size. **Detect** is cheap and
  native: botocore ships a service model for every AWS service and updates ~daily, so a CI job
  riding the existing Renovate botocore bump can diff the service/operation inventory and
  report what's new — no scraping, no guessing, and it lands as an annotation on a PR we
  already review. **Update itself** is the long pole: generating a collector needs judgment
  about which resources matter, their identity, and their projection — so it follows
  emergent-after-the-fact, extracted after enough types have been added by hand through the
  add-aws-type skill.]*

  **Detection target (decided 2026-08-25):** the CI job detects new AWS services in their cloud
  catalog and keeps a running tab of new things we need a dedicated pass to integrate — then we
  run the skill to add them to the base models and such. Fully automated updates are a future
  nice-to-have, not the target. *[agent-draft: the ledger is the saner shape because integrating
  a service is judgment work; a queue of "AWS shipped this, we haven't looked at it" is honest
  and actionable, while auto-generated collectors would land unreviewed types on the grid.]*

  **Coverage delta / burn-down list.** Generate a delta of what's not collected today in
  aws_core, so we have a burn-down list and so people know what's not there.
  *[agent-draft: derive it, never hand-maintain it — the manifest already declares what aws_core
  collects, so delta = (botocore's service inventory) − (manifest declarations), published as a
  generated page in the plugin repo. It doubles as the honesty surface the security posture
  demands: name what's deliberately left open rather than implying completeness. One caveat on
  granularity — botocore enumerates services and operations, not collectable resource types, so
  the service-level delta derives automatically while resource-type coverage inside a covered
  service stays a curated list.]*

  **Constraint on the 20x expansion:** *[agent-draft: let the KSI catalog's demands drive which
  types get added, not AWS service coverage for its own sake — coverage-chasing is the
  doctrine's own red flag.]*
- **Vulnerability triage** — the Criticalsec process for vuln severity ranking against critical
  paths in a cloud service. Requires the path primitives in TAP (POC'd on samsite; to be
  productized into grid primitives — see the paths step).
- **Deletion reconcile.** The additive-only approach applies only to the currently-running
  aws_core collector. We'll need to fix that for Rampart to support deletions in an account, so
  the view on the grid is accurate to what's in the cloud. Reconcile **tombstones** the grid
  node (observed until T, then absent) rather than erasing it — the history stays.
- **Collector run configs.** To be implemented as part of Rampart — the first genuine core
  expansion. For git-serious we continue with the baked-in collector / secret config. The run
  config is where we put the permissions on an aws_core collector run to tombstone **grid nodes**
  whose resources are no longer found in the account.

  **Read-only against the observed system (ruled 2026-08-25).** Reconcile deletes the grid's
  *representation*, never the cloud resource. We aren't nuking stuff out of real AWS accounts at
  this time. *[agent-draft: collectors observe; they do not mutate what they observe. The AWS
  credentials a run holds stay read-only, so a compromised or buggy run cannot destroy customer
  infrastructure — the blast-radius fence that keeps us off critical paths. "At this time" is
  George's phrasing and leaves remediation as a future question; it would be a different
  capability, a different credential, and a different conversation.]*
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
Onboarding also starts for Azure and Google Cloud marketplaces. The nice thing about shipping
Docker talking to GitHub is that we don't need to build out the cloud-specific scanners yet.

*[agent-draft: That cloud-agnosticism is the leverage worth stating outright — the product
observes GitHub, not the cloud it runs on, so one artifact lists in all three marketplaces with
no per-cloud collector work. Onboarding is calendar time (each of the three has its own
registration, agreements, and review lead time), so all three start in parallel now; but only
ONE listing goes live first to prove the motion, because three simultaneous review cycles
against a moving alpha means three sets of resubmissions. Two things to verify before dates
get attached: each marketplace demands a support statement and an EULA/privacy policy — under
the dana model that statement must honestly say community/best-effort — and Google's container
listings have historically expected a GKE-deployable shape, which a docker-run appliance may
not fit as cleanly as AWS and Azure.]*

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
  GitHub points back.*

  *GitHub-native mapping (no third-party tool — we're building the tool we'd want, so onboarding
  onto something we'd migrate off is wasted motion):*

  | Layer | GitHub mechanism | Notes |
  | --- | --- | --- |
  | Initiative | Issue Type `Initiative` + Project single-select field | Org-level types are live (Task/Bug/Feature today; add Initiative/Epic) |
  | Product line | Project single-select field | Taxonomy, not work — a field, never an issue |
  | Product | Its own umbrella-plugin repo | The product-specific locus of organization |
  | Feature / epic | Issue Type `Epic`, sub-issue of the initiative | Native parent→child roll-up, works cross-repo |
  | Task | Issue Type `Task`, sub-issue of the epic | The atomic unit |
  | Dated ship gate | Milestone in the product repo | What the roadmap step's `Tracking:` points at |
  | Cross-repo dependency | Sub-issue from the product repo into core / a sub-plugin repo | Milestones can't cross repos; sub-issues can |
  | The single pane | One org Project + Roadmap view | Cross-repo; date fields drive the timeline |

  *Thin by design — three issue levels, not five; no sprints/iterations; milestones only for
  dated external gates. Everything above is GraphQL-readable, so agents can maintain it and the
  whole taxonomy exports cleanly when the grid eventually eats it (the central-hub seam). Design
  rule for that migration: keep meaning in fields and links (which map to nodes and edges), never
  in board-column position or issue ordering (which don't).]*

## Timeline Table

| Step ID | Name | Timeline Target | Status | Note |
| --- | --- | --- | :---: | --- |
| step-products-git-serious-friends-preview | git-serious to friends | 2026-08-30 | Proposed | Tentative target: preview to friends by EOW |
| step-products-git-serious-private-preview | git-serious private preview | 2026-09-06 | Proposed | The following week |
| step-products-git-serious-public-alpha | git-serious public alpha | ~2026-09-15 | Proposed | Mid-September launch |
| step-products-grid-paths | Path primitives in TAP | ~2026-09-07 | Proposed | Rolling first; productize the samsite path POC; gates triage |
| step-products-collector-run-configs | Collector run configs | ~2026-09-07 | Proposed | First genuine core expansion; carries deletion-reconcile authority; follows paths |
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
Timeline Target: `~2026-09-07 (rolling first, ahead of collector run configs)`
Objective: *[agent-draft: The samsite path POC becomes real grid path primitives + Gryphon
traversal support — the platform capability the Criticalsec triage process ranks against.]*
Non-Goals: *[agent-draft: general graph-theory sprawl; path features beyond what triage
demands. Fenced hard — this is the largest platform lift in the plan.]*

### step-products-collector-run-configs
Status: `Proposed`
Timeline Target: `~2026-09-07 (week after next)`
Objective: Collector run configs land as the first genuine core expansion — the surface that
carries a run's permissions, including authority to reconcile **grid-side** absence (tombstoning,
never erasure) on an aws_core run. Sequencing: paths first, then collector config. git-serious continues on the
baked-in collector / secret config.
Non-Goals: any write, delete, or remediation against the observed cloud account — reconcile
tombstones grid nodes only, and collector credentials stay read-only. No hard deletion of grid
rows: history survives reconcile.
*[GEORGE: Done-Test.]*

*[agent-draft — design constraints this step should not ship without:*

1. ***Absence must be proven, not inferred.*** *"Not found" can mean deleted — or a failed API
   call, reduced permissions, truncated pagination, an unscanned region, or throttling. A run
   must assert "I completely enumerated scope S" before absence means anything; a partial scan
   reconciles nothing. Fail-closed, since silently erasing real infrastructure from a compliance
   tool destroys evidence.*
2. ***Reconcile only within enumerated scope*** *(account + region + type). Nothing outside what
   this run actually enumerated, and nothing another collector owns, may be reconciled away.*
3. **Tombstone, don't erase — ruled 2026-08-25.** *Absence is recorded as "observed until T,
   then absent," never as a row deletion. History/FLIP is the audit story that made the demo
   land, and erasing rows would destroy the evidence trail that differentiates the product.
   This extends the existing null=unobserved convention with a third state and is a
   grid-semantics decision — it belongs in the grid spec, not inside a collector.*

   *Prior work already anticipated this: `req-grid-node-observation` deferred "reconciliation
   no-clobber" on 2026-06-30 with the note that live collectors would give it teeth, naming
   `spec-grid-import-grift.md` / the write path as its home. That trigger is now firing. Note
   the axis is new — the existing convention governs FIELD-level absence (null = unobserved,
   `""` = observed-empty); a tombstone is NODE-level absence (the resource itself is gone), so
   it wants its own state rather than an overloaded field null.*
4. ***Reconcile authority is its own capability,*** *separate from read (fine-grained-capabilities
   standard), granted per run config.*
5. ***Baked-in config should be a degenerate run config,*** *not a parallel code path — otherwise
   git-serious and Rampart derive the same fact twice.]*

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
4. Start marketplace seller onboarding in parallel for AWS, Azure, and Google Cloud (calendar
   lead time; independent of the alpha). AWS listing goes live first; the others follow once
   the motion is proven.
5. i18n groundwork: wire LocaleMiddleware + locale dirs, mark-as-you-write for new git-serious
   pages, and schedule the bounded retrofit of the 34 existing templates.
6. Naming-lock decision list for PyPI: product names, plugin package namespace.
