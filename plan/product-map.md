# Product Map

`product-map` — the standing **product taxonomy**: the stable shape of what we build, how it is
organized, and how it reaches people. This is the companion to [`road-products.md`](road-products.md):
the roadmap is the time-ordered progression (which outcome, by when); this map is the shape. The
roadmap references this map; this map carries no timelines (the roadmap's Timeline Table is the
single source of truth for dates, `req-roadmap-timeline-table`).

Last meaningful revision: 2026-08-25.

---

## Emergence

The grid is a foundational concept from which higher and more complex forms can emerge. TAP is the
first instantiation of the grid — if we do it right, in very short order it won't be the only one.

On TAP we've built skills to define new nodes and edges. On top of that we built the collector and
plugin skills, which call the node/edge/collector skills beneath them. On top of the plugin skill we
will define a **create-product skill** — calling the plugin-creation skills (and others TBD) to stand
up the machinery necessary to manage a standalone product and make it available for use by anyone,
with adjacent sub-skills for building CI/CD, product documentation, launch website, and community
support / interaction.

Above that is the **product line** — a suite of tools / plugin packs. Each of these builds rests on an
emergent skill scaffolding whose existence enables the higher-order configuration to come into being.
Each will need to include how to manage and evolve its components over time — which will necessitate
standardizing versioning throughout the stack, including base models, edges, collectors, and plugins,
because in security you never do anything once.

### Emergent after the fact

We do the thing manually the first time (or two), then build the skill from that. No rung of the
scaffold is authored speculatively: each is extracted from a concrete instance and validated by the
next one. The create-product skill is distilled from building git-serious by hand, and proven when it
stands up the second product.

Extraction is not finished until the instance it came from is retired or demoted to a projection. If a
higher rung lands and its precursor stays independently authoritative, a sequential design becomes a
parallel one and the duplication anti-pattern arrives late. Every rung must either subsume its
precursor or explicitly name it a generated view.

### Emergence is recursion in the outward direction

The requirements and specification process we're developing here is — and always has been — the
precursor to upload to the grid. What's been missing is the running software to get us there, which is
the exact thing we're using the specs / reqs to build.

Manual-first is sequential, not parallel, so it is not the derive-a-fact-twice anti-pattern:
duplication means two live derivations that can drift, while the manual rung is the only derivation
there is. It is the design phase.

Ordinary recursion travels inward, decomposing toward a base case that terminates it. Outward
recursion has no natural floor — which is why **demand is the base case**. Absent a demand signal,
building outward is not emergence but infinite abstraction, the exact overbuilding the roadmap's red
flags exist to catch.

### The ladder

| Rung | Skill layer | Status |
| --- | --- | --- |
| Node / Edge | `add-model`, `add-edge` | Built |
| Collector | `build-collector` | Built |
| Plugin | plugin-creation skills | Built |
| Product | create-product skill | To extract from the git-serious build |
| Product line | ??? | ops, security, compliance |
| Initiative | initiative skills | Rampart; composes the lines and boots as one appliance |

---

## Initiatives, product lines, products

The taxonomy is a **composition hierarchy, not a type hierarchy**. Each level is the same kind of
thing — a repo with a boot profile — differing only in what it composes:

| Level | Composes | Example |
| --- | --- | --- |
| Plugin | nodes, edges, collectors, pages | `aws-core-tap` |
| Product | plugins | `git-serious-tap` |
| Product line | products | ops, security, compliance |
| Initiative | product lines | `rampart-tap` |

**An initiative-level repo is also a plugin, and that is how this all wires together.** In the near
future someone runs `uv launch rampart-tap` and it pulls down an appliance that is Rampart; during the
install they talk through which components from ops / security / compliance they want right off the
bat; those plugins are pulled into the bootloader and slotted into place, and the whole thing comes up
and just works.

That is the payoff of one uniform kind: the bootloader walks a composition tree without needing to
know which rung it is standing on, and a level can be added or collapsed without inventing new
machinery. It is also why the `-tap` suffix is uniform and why role is never encoded in a name — the
manifest declares what a package composes, and the boot profile *is* the composition.

**Platform work is a cross-cutting concern.** It exists independent of any initiative. TAP is a means,
not an end — the substrate every level of the tree stands on, never a peer of the things it carries.
Every initiative will drive work on the platform, not the other way around, so TAP remains a solo repo
by design, referenced from plugins and product repos accordingly.

Treating TAP as a peer would imply it competes for priority with its consumers, and would open a
channel for platform work with no demand behind it. Platform work is always derived demand.
Mechanically this needs no new machinery: core work lives in the TAP repo with its own release-driven
milestones, and the demand relationship is carried by the sub-issue edge — a product repo's epic has
sub-issues in the TAP repo, so the parent records what pulled it. A core issue with no parent is either
ordinary maintenance (security patches, dependency bumps, CI upkeep) or platform work nobody asked for.

---

## A product is an over-arching plugin with its own repo

A product lives as an over-arching plugin — Git-Serious is its own plugin with its own repo. That gives us
the ability to assign milestones inside that product to that repo. We can then coordinate across other
plugins, such as sub-plugins in their own repos, but that becomes the product-specific locus of
organization.

The product repo is both a code artifact and the coordination point. The boot profile that composes the
product is the same artifact that defines what the product *is*, so "what's in Git-Serious?" is answered by
reading a pinned record rather than a document. It also anchors the versioning story: a product release
is a pinned composition of sub-plugin versions — the boot-record-as-BOM pattern already proven in the
field.

Two mechanics stay distinct. A **milestone** can only hold issues from its own repo, so it tracks what
ships from the product repo. Cross-repo dependencies — a core capability in the TAP repo, a collector
change in aws_core — ride **sub-issues**, which do cross repos and roll up.

Open to verify: whether the plugin system accepts a composition-only plugin (dependencies, boot profile,
and pages but no models or collectors of its own), or whether `validate_plugin --strict` expects more.
If it doesn't, that is a small conformance gap to close, not a reason to change the shape.

### Naming

Plugins and products carry a **`-tap` suffix**: `rampart-tap`, `git-serious-tap`, `vuln-triage-tap`,
`aws-core-tap`. TAP is the base layer, not the over-arching capability — prefixing everything with
`tap-` would be like calling a distribution `linux-ubuntu`. The suffix reads as the adjective it is
("for TAP"), mirrors Maven's `<name>-maven-plugin` convention for community plugins, and gives a
searchable string for finding everything that works on TAP.

Two constraints hold this together:

- **Rename distributions and repos; never rename slugs.** Internal identity stays `aws_core` regardless
  of what the package is called. Collector identity has broken on a module-path rename before, which is
  why scope is keyed to slug.
- **Lock names before publication.** Registry names are effectively permanent — PyPI has no rename.
  Nothing is published yet (plugins install from git source), so this is the last cheap moment.

**The existing repos do not follow this convention yet, and that is deliberate.** They carry the older
prefix scheme (`tap-plugin-aws-core`, `tap-plugin-samsite`, `tap-plugin-github-core`). Aligning them is
a rename wave we will have to do — **but not yet**. Two rules in the meantime:

- **New repos use the convention** (`git-serious-tap`). Do not create anything new with the old prefix.
- **Do not rename an existing repo opportunistically.** The wave lands deliberately, in one pass, with
  its own trigger — not as a drive-by tidy when someone notices the mismatch.

Why it can wait: the permanence that forces the naming lock is a *registry* property. GitHub renames
are cheap and auto-redirect; PyPI names cannot be changed at all. So the expensive decision is already
made, and the cosmetic one can follow. The cost to check before that wave runs is that boot records pin
git URLs — a rename leans on GitHub's redirect until those records are bumped, so the redirect path
through the install flow wants proving before anything with a pinned consumer is renamed.

---

## Initiative: Rampart (secops)

All things infrastructure / security / cloud / ops-facing. Three product lines are emerging: **ops**,
**security**, **compliance**.

### Product line: ops

**git-serious** — the application for observing and monitoring a complex gitops deployment. Our first
customer is us: we want to view and understand the whole CI/CD system we just built. Classic scratching
our own itch, and demoing on the one system we control and know inside and out.

git-serious is...unusual... it's on the emergent path to Rampart, because anybody who's running
something in GitHub is likely building something that could benefit from Rampart. It operates in a
quasi-product space as a plugin pack / sub-product that could stand on its own.

It's like this — git-serious is the movie *Iron Man 1*. It's a standalone movie with a self-contained
plot and central figure (GitHub / other git servers), but it's going to very quickly join the greater
Avengers cast as part of the Rampart initiative. (The MCU / Avengers arc is where the concept of
initiative came from.)

That makes git-serious the widest door into the initiative, which is the strategic reason it goes first
rather than merely the fastest to build. It also sets a design rule: **standalone integrity first,
composability second, no forward dependency.** Iron Man 1 works completely for someone who never sees
another Marvel film, so git-serious must be fully coherent alone — no Rampart concepts leaking into its
UI or docs, no upgrade-nagging. What it may have is the post-credits seam: shared vocabulary, the same
grid, boot, and plugin model, so it composes into Rampart later without rework.

Its shape:

- **Form.** An over-arching product plugin in its own repo, with a boot profile that slots in the
  necessary stuff underneath. Ships as a self-contained appliance build — plugins baked into the image,
  simple docker launch command.
- **AI-driven install and config.** A fleshed-out config and management AI skill set. Skill-based, so
  executable by anyone with an AI account — which, if they're running git-serious, is literally everyone
  we care about. This release is explicitly a test of AI-driven install and config.
- **Platform extensibility.** We're building against GitHub.com, but this should be extensible to other
  git platforms by users and the interested. The neutral git/CI vocabulary (repo, branch, pipeline run,
  protection rule) lives in a `git_core`-style substrate plugin, with the GitHub collector as its first
  implementation — extensibility by vocabulary, not pre-built adapters.
- **Translated pages.** Needed, because we want this to spread as far as possible. `USE_I18N` is on but
  nothing is marked today, so the rule is mark-as-you-write for every new page plus one bounded retrofit
  of the existing templates. Only UI chrome is a gettext problem: docs and landing pages need their own
  toolchain, collected data stays verbatim, and AI-generated explanation is generated in the reader's
  language rather than translated. Translation is also the best non-code contribution on-ramp we have.
  Open risks, named rather than solved: who reviews a translation (a mistranslated security finding is
  worse than an untranslated one, so machine output ships labeled as machine output), which languages
  (pick from real signal), and RTL layout if that signal appears.
- **Purpose.** Get the application into the field and being used by people in real environments. First
  contact with the customer.

**code-paths** — tracing application-level capabilities and code flows. Another product we'll pull on
later. It'll bleed into security and compliance, but its origin story is that it's going to be the tool
I build to observe and understand wtf code you're writing. So maybe "ops" isn't quite the right word,
but it's close enough, because I struggle to call what I'm doing as a human in our relationship
"development" any more.

The vision: a world where narrative, specs, requirements, ACIDs, testing, execution graphs and critical
paths are all available under gryphon-search. Most of that graph already exists — requirements, ACIDs,
implementation claims, and spec-marked tests are a graph today, stored as markdown fragments and code
annotations and queried by greps. Execution graphs and critical paths are the genuinely new nodes. So
code-paths is less "build a new system" than "project the traceability system we already maintain onto
the grid we already have," after which *which requirements have no test*, *what breaks if I change this
function*, and *what governs this code* become queries instead of tooling.

Naming a product line for the artifact rather than the job is a weak position — "architecture" describes
the object, "ops" describes what someone does. Line names are a field in the tracker and cheap to
change; product names become repos and registry packages and are not.

**Discovery / observability** — the capability that shows someone what's actually running in their cloud
account, built from what the aws_core collector brings in. Lives in ops; security applies activities
around that visibility, and compliance reads the same picture.

### Product line: security

**vuln-triage** — the Criticalsec process for vuln severity ranking against critical paths in a cloud
service. Requires the path primitives in TAP, proven out on samsite and to be productized into grid
primitives. The methodology keeps its own name in prose; the package does not carry it.

### Product line: compliance

**FedRAMP-20x** — managing a complex org's certification and monitoring, including continuous tests
against live KSIs.

---

## Enabling capability

Not products: platform and shared-plugin work the lines pull on. Kept together so the demand
relationship stays visible and no line owns the substrate.

**Grid mutability.** The additive-only approach applies only to the currently-running aws_core collector.
Deletion reconcile fixes that so the view on the grid is accurate to what's in the cloud — and it is a
prerequisite for git-serious release, not a Rampart-only concern: git-serious observes a system that
changes constantly, where runners go away and repos get mothballed, so an additive-only view would be
wrong about the thing the product exists to show.

Reconcile **tombstones** the grid node (observed until T, then absent) rather than erasing it. History
and FLIP are the audit story; erasing rows would destroy the evidence trail. This is node-level absence
and a new axis: the existing convention governs field-level absence (`null` = unobserved, `""` =
observed-empty), so tombstoning wants its own state rather than an overloaded field null. It is a
grid-semantics decision and belongs in the grid spec, not inside a collector.

Design constraints:

1. **Absence must be proven, not inferred.** "Not found" can also mean a failed API call, reduced
   permissions, truncated pagination, an unscanned region, or throttling. A run must assert complete
   enumeration of a scope before absence means anything; a partial scan reconciles nothing. Fail closed.
   (Complete enumeration is materially easier against a git platform than against a cloud account.)
2. **Reconcile only within enumerated scope** — account, region, type. Nothing outside what this run
   enumerated, and nothing another collector owns.
3. **Tombstone, never erase.**
4. **Reconcile authority is its own capability,** separate from read, granted per run config.
5. **Baked-in config is a degenerate run config,** not a parallel code path.

**Collector run configs.** The first genuine core expansion — the surface carrying a run's permissions,
including authority to reconcile grid-side absence on an aws_core run. For git-serious we continue with
the baked-in collector / secret config, shipped as **explicitly unstable**: the alpha posture means we
reserve the right to change its shape, which buys time to let experience from the field determine the
real shape rather than sorting it out up front. Scar tissue comes from promising stability, not from
changing things.

**Read-only against the observed system.** Reconcile deletes the grid's *representation*, never the cloud
resource. We aren't nuking stuff out of real AWS accounts at this time. Collectors observe; they do not
mutate what they observe, and the credentials a run holds stay read-only, so a compromised or buggy run
cannot destroy customer infrastructure. Remediation would be a different capability, a different
credential, and a different conversation.

**aws_core expansion.** Building out aws_core; importing git-serious for CI/CD. aws_core needs a
feature / CI cycle to detect new AWS services in their cloud catalog and keep a running tab of new things
needing a dedicated pass to integrate — then we run the skill to add them to the base models and such.
Fully automated updates are a future nice-to-have, not the target: integrating a service is judgment
work, and a queue of "AWS shipped this, we haven't looked at it" is honest and actionable where
auto-generated collectors would land unreviewed types on the grid. Detection itself is cheap and native,
since botocore ships a service model for every AWS service and a CI job riding the existing dependency
bump can diff the inventory.

**Coverage delta.** A generated delta of what's not collected today in aws_core, giving us a burn-down
list and telling people what's not there. Derived, never hand-maintained: the manifest already declares
what aws_core collects. It doubles as the honesty surface the security posture asks for — naming what is
deliberately left open rather than implying completeness. Botocore enumerates services and operations
rather than collectable resource types, so the service-level delta derives automatically while
resource-type coverage inside a covered service stays curated.

**Path primitives.** Productizing the samsite path proof-of-concept into grid primitives with traversal
support — the capability vuln-triage ranks against, and the foundation code-paths later builds on.

Expansion driven by 20x should follow the KSI catalog's demands rather than chasing AWS service coverage
for its own sake.

---

## Posture: alpha, in public, blast-radius constrained

We are leaning hard into alpha / preview / YMMV / just-make-it-work territory. Perfection is not the
goal — proving the concept and demonstrating that others can bring it up, use it, find issues, fix them,
and submit improvements is the name of the game. The focus is gaining users and feedback.

We carry a solid security story for CI/CD operations, combining what we've built recently with the
foundation of the TAP system to this point. We're threading a needle: useful in critical environments,
but blast-radius constrained to keep us off any critical paths until there's sufficient use in the field
for the system to stabilize under its own operational pressure.

---

## Distribution

Everything is freeware. Cloud-marketplace presence is an opt-in, optional support channel — no additional
licensing — and a repeatable distribution model for the future. Onboarding runs in parallel for AWS,
Azure, and Google Cloud; the nice thing about shipping Docker talking to GitHub is that we don't need to
build out the cloud-specific scanners yet, so one artifact lists everywhere.

Sequencing: all three registrations start together because they are calendar time, but one listing goes
live first to prove the motion — three simultaneous review cycles against a moving alpha means three sets
of resubmissions. Each marketplace requires a support statement and an EULA/privacy policy, and under
this model that statement says community/best-effort. Google's container listings have historically
expected a GKE-deployable shape, which a docker-run appliance may not fit as cleanly as the others.

Plugins graduate from git-source installs to the native registry (PyPI via uv), which is the
adopt-native-distribution posture. Trusted publishing (OIDC from Actions, no long-lived tokens) is the
mechanism. Naming must be locked before first publication.

**Signing ladder.** Pinned digests plus the existing content-hash floor cover the friends and private
previews; sigstore-signed images are a public-alpha gate; TUF stays deferred. The standing supply-chain
trigger — the first non-George user playing with the system — fires at the friends preview, and this is
its resolution.

---

## Named seams

Not built. Each waits on a demand trigger.

- **Central hub** — an ongoing TAP instance managing the overarching strategy, reached for once
  operational complexity demands offloading to the grid. A standing git-serious instance watching our own
  org is the embryo of this, so the seam likely arrives through dogfooding rather than a decision.
- **Stack-wide versioning** — standardized versioning for base models, edges, and collectors. Plugins
  already carry versioning through uv, tags, and `requires_tap`. Trigger: the first breaking change
  shipped to a field instance.
- **Product-line skill rung** — extracted only after two products exist.
