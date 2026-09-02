---
title: git-serious build log — the first product, built by hand
date: 2026-08-26
status: active
audience:
  - developer
  - llm
spec: specs/spec-roadmap.md
related_docs:
  - plan/road-products.md
  - plan/product-map.md
---

# git-serious build log

**Why this file exists.** git-serious is the first product built on TAP, and the meta-scope of
the build is to learn how products get built at all. Per the emergence doctrine
(`product-map.md` → "Emergent after the fact"), the first instance is done **by hand**; the
`create-product` skill and its sub-skills are extracted from this log plus the sessions that
produced it. Every manual step, decision, stumble, and idea recorded here is raw material for
that extraction. Nothing here is canon — the roadmap and specs are; this is the notebook.

Sections are dated. Newest at the bottom. Each entry tags what it is: **step** (a manual thing
we did that a skill will do), **decision** (a ruling, with the why), **lesson** (a stumble and
what it taught), **idea** (unbuilt, unpromised).

Product repo: https://github.com/unified-systems-com/git-serious-tap. Work on it through the
established nested-checkout path — `_dev-plugins/<slug>/` inside a session worktree, provisioned by
`spawn --dev-plugins` (`spec-dev-plugin-workspace.md`). It is gitignored, despawn cleans it up, and
the remote is the truth.

---

## 2026-08-26 — naming the problem

**step — name the problem before anything else.** A product is a self-contained capability
that solves a well-defined problem for a user community. The first act is a one-line
*problem* statement, and it is the hardest one: TAP has been hard to explain from day one
precisely because it is not a thing in itself but a thing you solve problems with. Products
are solutions to problems, built on TAP.

**lesson — a problem line and a promise line are different sentences.** The first draft
("visualize, track, and secure your gitops pipeline") was a *promise* — verbs we do. A problem
line names the pain the reader already feels, in their words, with none of our verbs in it.
Keep both; the problem comes first. Second lesson from the same pass: with four true clauses
(complicated / security-critical / easy to get wrong / impossible to see), lead with the one
that makes the reader wince and is the *cause* of the others.

**decision — the two lines.**
> CI/CD configuration is impossible to see all at once — and getting it wrong is catastrophic.
> Visualize, track, and secure your CI/CD system — for humans and agents.
Rejected tails: "using grid-centric security" (our vocabulary, not theirs — the grid gets its
own key-concept header instead); "using humans and agents" ("using" makes the human a tool;
"for" says who the views are built for, which is the actual claim).

**decision — vocabulary.** *CI/CD* is the product's subject (vendor-neutral, universally
understood). *Forge* is the neutral word for the platform that hosts repos and runs the
pipeline (GitHub, GitLab, Gitea, …) and is the extension seam (`git-core-tap`, tap#144).
*GitHub Actions* is the first shipped implementation (`github_core`). **GitOps is retired from
our vocabulary**: it names a specific practice (git as declarative source of truth for
deployment state, reconciled by Argo/Flux) that is an explicit Non-Goal, and misusing it is the
one thing that makes practitioners stop reading. The product name *git-serious* is already
forge-neutral (git, not GitHub) — no rename pressure.

**step — the manifesto.** Call to action, why, how, how to run it, key concepts. Retouched from
George's draft to the vocabulary above; the concrete scatter list ("workflow files, rulesets,
environments, org settings, bots, apps, third-party services, PATs") stays because
concreteness is what makes it land. Key concepts: *Master complexity*, *Software as a
sophisticated beanbag*, *The grid*. Iron Man 1 rule held: no Rampart, product-line, or
initiative language anywhere in it. Landed as the product repo's README (first commit) with
a pre-alpha status line beneath the promise, since "run the install skill" is a *friends*
milestone promise, not *self*.

**step — inventory diff (git-serious-tap#5), first pass.** Read `github_core` against the
story. It collects account / repo / workflows (+ raw YAML, `uses:` refs) / runs / jobs /
runners / Dependabot-as-app / OIDC issuer, for a **repo list**, as "Actions plumbing for
samsite". The story needs, and it does not collect: org-wide repo enumeration; rulesets /
branch protection / required checks; installed apps + permissions; secret/variable *names* +
environments; the org's fine-grained PAT inventory; action pins (SHA vs tag — derivable from
YAML already parsed); security-feature posture; CODEOWNERS / webhooks / deploy keys / org roles.
**Finding: git-serious is not mostly composition — it needs a real collection wave.** But every
row is a known shape on a working collector (manifest source + model + edges), not an unknown.
Collection lands in `github_core`; the product composes it and owns the pages.

**lesson — read our own CI/CD system as the first fixture.** One `gh api` sweep of the org:
19 repos, 14 workflows, 4 repo rulesets, 4 org-installed apps (Renovate, release-please,
Sonar, Codacy) + Copilot, 6 repo secrets incl. two third-party AI-review keys, 1 environment,
CODEOWNERS, git hooks. Nobody can see that at once today. That sweep *is* the demo script.

**idea — the gate as the first projection.** Candidate design target for the CI/CD projection
page (git-serious-tap#6): for `main`, what must be true for a commit to land — ruleset →
required checks → the workflows that produce them → the pins, apps, and secrets those
workflows touch. Not decided.

**open — scope of milestone 1.** Proposed: move #7 (appliance build) to the friends milestone
(self's Done-Test does not need a docker one-liner, and #7 carries two unknowns: tap#146
composition-only conformance, tap#145 naming chain); split #6 into a design task (S) and a
build (M); expect the Done-Test to be *observed* ~Sep 2 rather than Aug 30, and move the
milestone date explicitly rather than pretend. Awaiting ruling.

**step (process) — strategy lives on PR #159 until it lands.** `plan/road-products.md` and the
refreshed `product-map.md` are not on main yet; this session branched before them. Merge main
forward once #159 lands before citing `step-products-git-serious-self` from code or docs.

**decision — milestone 1 scope and the Aug 28 checkpoint.** #7 (appliance build) moves to
*friends*: self's Done-Test needs a running instance, friends' needs the docker one-liner. It
becomes an epic whose first sub-task (#16, S) scopes the build and populates the rest — and
resolves tap#146 / tap#145 on the way. In place of a date fight, a **checkpoint**: #17,
target 2026-08-28, "first live view of our own pipeline" — something on the board, pulled
live, not the Done-Test. Once observed it sets the next milestone-1 date with real
information. Milestone 1's Aug 30 date is left alone until then. Sprint 1 (Aug 25–31) now
holds #5 (S), #6 (M), #17 (M).

**lesson — checkpoints, not milestones, for internal dates.** Milestones are for dated
external gates (roadmap Tracking section). An internal "first light" date is a Task with the
board's *Target date* field set, sub-issue of the epic. Recording it as a milestone would have
put a non-gate in the only place the roadmap says dates live.

**step — tracker mechanics learned the hard way (skill fodder).** Reparenting a sub-issue is
REST (`DELETE …/issues/{parent}/sub_issue` + `POST …/issues/{new-parent}/sub_issues`, by
database id). Issue *type* (Epic/Task) is GraphQL only (`updateIssueIssueType`). Board
fields go through `gh project item-edit` with option/iteration ids fetched first
(`Size`, `Product line`, `Product`, `Target date`, `Sprint`). `gh issue create` does not
set type or parent — three extra calls per issue. All of it is a `create-product` sub-skill
waiting to happen: "open an epic with sized, sprinted, typed sub-tasks on the board."

**decision — lead with org-level collection.** `github_core` refactors to an *account* scope
(org or user) that enumerates repos itself; the envelope's `repos` becomes an optional filter
(degenerate run config, tap#142 policy). Spec'd as a requirement in `spec-github-core-v0.md`
before code. Cheap edge laid alongside: the run records the scope it completely enumerated,
which is the assertion tap#140 tombstoning needs before absence means anything.

**decision — lead with the new naming convention.** Distribution `git-serious-tap`, slug
`git_serious`, namespace `tap_plugin.git_serious` (namespace is identity; only repos and
distributions carry the convention). That puts tap#145 on the critical path. Its small shape:
the conformance gate **accepts either convention** (new preferred, old permitted with a
deprecation line) and preboot's git-install spec drops the leading name so uv resolves it from
the package's own `pyproject`; flipping the derivation globally would be the 12-repo rename
wave (tap#147), not this week.

**decision — a `provision-github-pat` skill in github_core.** The kind is github_core's, so its
minting lives there (provision-secrets routes `github_pat` to the samsite README today — wrong
home now). Minting is UI-only but verification isn't: the skill derives the least-privilege
permission set from the collection manifest (each source declares its permission — derive
once), verifies the token live, writes the envelope, runs preflight. First sub-skill of #8.
Trade-off named: a PAT is per-person and expires; a GitHub App is the real product credential
(alpha-shaped), deferred.

**rule of practice — modifying downstream skills mid-build.** We may modify a downstream skill
as we go **if the change rests on a rule we know we're keeping**; otherwise we note what needs
to change for the follow-on wave. First application: `new-plugin` refactors to the `<slug>-tap`
convention as part of tap#145.

**sequence to the checkpoint:** tap#145 (M, core) → org-scope spec + code (M, github_core) →
PAT skill (S, github_core) → product skeleton under the new name → boot by pointer → look.

**step — tap#145 built (naming transition).** `tap/plugin_identity.py` is now the one
derivation of both conventions (`dist_name_for_slug` → `<slug>-tap`, `legacy_dist_name_for_slug`,
`dist_names_for_slug`, `installed_plugin_dist_name`); pre-boot's gates, the author-time
validator (legacy = warn, unknown = fail), the plugin report, and the release-SBOM lane all
resolve through it. Git installs are bare `git+url@rev` so uv reads the name from the
checkout's own pyproject; wheelhouse installs ask for whichever convention the wheel present
carries. `new-plugin` emits the suffix. Spec amended (`req-tap-plugin-arch-identity-2`,
`req-tap-plugin-validate-identity-2`), slug register + handoff recipe + workspace spec updated.

**lesson — the sealed-surface ratchet shapes where a derivation can live.** `tap/preboot.py`'s
`__all__` is frozen and may only shrink, so the "which name is this slug installed under"
resolver could not be exported from preboot for the report to use. It went into
`plugin_identity.py` (stdlib-only by contract) with an injectable lookup, and preboot wraps it
with its own monkeypatch-able distribution lookup. The ratchet did its job: it pushed the fact
DOWN into the leaf instead of sideways.

**lesson — "stdlib-only" was enforced as "import-free".** The guard test on
`plugin_identity.py` flagged any `import` line, not non-stdlib ones. Relaxed to
`sys.stdlib_module_names`, which is what the docstring always said.

**follow-on wave (tap#147):** `nightly-plugins.yml` discovers the plugin fleet by the
`tap-plugin-*` repo-name prefix, so a `*-tap` repo is invisible to the nightly skew detector
until discovery moves to the boot-profile roster (the fork-plan's item 4). Also the SBOM lane's
release-tag grammar (`[<dist>-]vX.Y.Z`) and the 12 existing distributions themselves.

**step — org scope built in github_core (branch `feat/org-scope`).** Envelope: `owner` (account
login) and/or `repos`; `anyOf` keeps the samsite repos-only envelope valid; every field
described. Collector: `_resolve_repos` enumerates `/orgs/{owner}/repos` (user fallback),
filters, records `SCOPE_ENUMERATED` with walk completeness (`GithubClient.last_walk_complete`);
batches carry `github.owner`; self-test proves enumeration with one bounded walk; every
manifest source declares its PAT `permission`. Spec: the **Account Scope** requirement in
`github_core`'s own `specs/spec-github-core-v0.md` (6 ACIDs) — cited by title rather than RID
because github_core is evicted, so a bare requirement token from that plugin resolves to nothing from
core and would strand any agent that chased it.
Tests written; they run in the product stack (this session's `core_dev` profile has no
github_core), which is why the product skeleton came next rather than after.

**step — product skeleton (branch `feat/skeleton` on git-serious-tap).** `pyproject`
(`git-serious-tap`, deps by their *current* published names), `tap-plugin.toml` (composition-only,
`[fips] compatible`, `[[boot.records]]` with canonical digest), `apps.py` (pass), the in-package
boot record (administrivia + identity_core + github_core@feat/org-scope + git_serious@feat/skeleton;
collector step declared but disabled until the account PAT lands), `grift/landing.grift.json`
(page `/git-serious`, graph panel over per-label Gryphon searches, minimal projection →
elevation → arrangements-only layout), and the record-resolves test gate adapted from samsite.
Stood up with `spawn-session.sh git-serious-app --boot-file <record> --dev-plugins
git_serious,github_core` — the `--boot-file` + branch-rev tier is exactly the fork/dev flow the
workspace spec describes, and it fits a product's pre-release phase too.

**lesson — a product's first boot is circular, and the record's rev field absorbs it.** The
record ships inside the package it installs, so the first record cannot pin its own release.
Branch revs in the dev record (`feat/skeleton`) resolve it; the first tagged release pins tags
(req-boot-bootstrap-stage0-3: carrier rev and installed rev are independent coordinates).

**lesson — the gh token cannot create workflow files.** Pushing `.github/workflows/ci.yml` was
rejected (`workflow` scope missing) and the contents API returned 404 for the same reason. The
skeleton landed without its CI caller; adding it needs a task-scoped `gh auth refresh -s
workflow` (George's lever under the descope rule) — a `create-product` sub-skill step to
document: "the CI caller needs the workflow scope; elevate, push, drop".

**CORRECTION (2026-08-27) — a convention I invented and should not have.** An earlier revision of
this log recorded that "product repos live beside, not inside, TAP session worktrees" and pointed at
a `~/tap-products/` directory. **Nobody agreed to that.** I created the directory in the first hour,
made the rule up to justify it, and wrote it here in the voice of established practice — which is
how an invention becomes canon by accident.

The established pattern already covered the need: **`_dev-plugins/<slug>/`**, the nested checkout
`spawn --dev-plugins` provisions (`spec-dev-plugin-workspace.md`). It is gitignored, despawn cleans
it up, and it is where the real work ended up anyway — both `git_serious` and `github_core` were
edited there. `~/tap-products` was redundant within the hour and has been removed; everything it
held is on the remote.

Two lessons, and the second is the one that generalises:

- **Reach for the existing pattern before inventing a location.** The worry that prompted this
  (despawn deletes the worktree) was real, and already solved.
- **A build log written in the voice of canon becomes canon.** This document's whole purpose is to
  be mined for the `create-product` skill, so an unexamined sentence here would have told the next
  operator to create a directory nobody sanctioned. When recording a choice, say who made it and
  whether it was agreed — `scope-adherence-no-unrequested-files` exists for exactly this, and I
  walked past it.

**step — research agents (skill candidates).** Two background passes launched 2026-08-26: (1)
the CI/CD *shape* review — our own pipeline inventoried, model/edge gap analysis, icons, landing
story — `scratchpad/cicd-shape-review.md`; (2) the *prior-art / incidents* pass — products, OSS,
name-brand best practices, incident history, "what we don't know" — for the world-model a good
regulator of this product needs. Both are the first instances of a "research the space" skill.

**step — first boot of the product stack (session `git-serious-app`, port 8010).** Booted from the
in-package record via `--boot-file` + `--dev-plugins git_serious,github_core`. Three finds, each a
defect the product exposed in the estate rather than in itself:

- **lesson — a product session must branch from the core it needs.** Spawn branched the new
  worktree from main, which did not yet carry tap#145, so the old conformance gate rejected
  `git-serious-tap`. Merging the session branch into the app worktree and restarting fixed it —
  and proved the transition: the gate accepted the product and warned on the three legacy names.
  Skill note: when a product depends on unmerged core, spawn from the session branch or merge
  before boot.
- **lesson — `required_secrets` must be referenced by an enabled step.** Declaring the PAT while
  the collector step was disabled fails the record gate (`req-boot-required-secrets-4`). The
  honest dev record fires the collector against whatever envelope is placed — which made the
  first boot an end-to-end smoke test of the collector path on the samsite credential.
- **lesson — github_core's grid-link manifest assumed aws_core.** Five link rules name aws_core
  types on one end or the other; without aws_core installed Gryphon rejects the type and the
  whole run failed. Now covered by github_core's **Missing Target Vocabulary Degrades** criterion
  (`spec-github-core-v0.md`, grid-links): rules with an uninstalled endpoint type
  are skipped and recorded (`LINK_RULE_SKIPPED`). The composition-only product is what surfaced
  a plugin's hidden dependency — the first "teaches us something" moment came from the estate,
  not the pipeline.
- **lesson — restart is not population; workers do not autoreload.** `scripts/dc restart web`
  re-runs preboot + migrate + runserver only; population is `manage.py boot`. And the collector
  runs in the steady_queue worker, which keeps the module it loaded — an editable-plugin edit
  needs a stack restart before re-firing (the runserver autoreload is not the worker).

Outcome: `Boot complete.` — collector SUCCESSFUL (1 repo, 7 nodes, 6 spine edges, 5 rules
skipped), `/git-serious` seeded. Still the samsite credential; the org picture waits on the
account PAT.

**checkpoint — first light observed (2026-08-26, two days early, on the wrong credential).**
`/git-serious` renders the live collector output in headless Chromium: platform → account →
repository → workflows, Dependabot as app, the OIDC issuer. Zero console errors. The org picture
waits only on the account PAT. **lesson — the product's own chrome can betray it:** the header reads
RAMPART › git-serious (core's brand), an Iron Man 1 violation no test would catch; the brand fact
needs a home in the composition (git-serious-tap issue filed). **lesson — the dev admin needs a
capability grant, not just a user row:** an ad-hoc superuser got `capability_denied`; membership in
`tap_admin` is what opens the pages (the spawn's `DJANGO_SUPERUSER_USERNAME` bootstrap or
`bootstrap_dev_passkey` does this for real; the drive-browser skill's mint assumes it exists).

**decision — product-specific docs live in the PRODUCT repo (2026-08-26, George).** The three
research passes moved from the session scratchpad into `git-serious-tap/docs/` (PR #19) with
frontmatter, a research banner, and a `docs/README.md` index — not into `tap/docs/misc/`. The rule
generalizes: the platform's docs describe the platform; a product's docs describe that product, and
they ship in the repo that IS the product. A `create-product` skill step follows from it: scaffold
`docs/` + its index in the product repo, and route synthesis there rather than to core's drawer.

**judgment call left in core, flagged not hidden:** this build log stays in `tap/docs/misc/`. Its
consumer is the `create-product` skill extraction (a TAP concern) and most of its lessons are about
TAP machinery — spawn, boot records, the conformance gate — not about git-serious. If that reads
wrong, it moves.

**lesson — a fresh product repo already inherits the org's protection floor.** Pushing docs straight
to `git-serious-tap` main was rejected by the org ruleset ("Changes must be made through a pull
request") — the org-wide security floor applied to a repo created hours earlier, with no per-repo
setup. Exactly the intended behavior, and worth knowing before a `create-product` skill tries to
push a scaffold to main: **the scaffold lands via PR, from the first commit.**

**defect found by looking at the product — the instance is branded RAMPART.** `tap/settings.py:72`
defaults `TAP_PRODUCT_NAME` to `RAMPART`: core ships a product line's brand, so every instance of
every product wears it until an operator sets an env var. Filed as git-serious-tap#18 (friends,
M, Sprint 2) pulling tap#182 (the core mechanism: default to `TAP`, let the boot record declare the
name through the existing boot-variable → env seam, make the hardcoded favicon overridable by the
product plugin, keep `context_processors.branding` as the single derivation). The alternative —
reading the name from the grid keystone at request time — is named and rejected for now, which is
what keeps the task M rather than an L carrying a hidden design question. **The general lesson: a
product is the first consumer that can see the platform's defaults from the outside.**

**lesson — shape is not severity, and a view that confuses them cries wolf.** The shape review
flagged "an AI-provider key reachable via `workflow_run` from a PR-triggered capture" — the exact
conjunction the prior-art pass ranks as the #1 incident pattern of 2025–26. Chased to ground, our
chain is textbook-correct: `capture` is `pull_request` with top-level `permissions: {}`; `review` is
`workflow_run`, guarded on `conclusion == success && event == pull_request`, and **never checks out
PR code** — the only checkout is the prompt pack at a pinned SHA with `persist-credentials: false`.
The diff and PR text arrive as artifacts read from disk in Python, with **no `${{ }}` interpolation
inside any `run:` block** and no use of untrusted `workflow_run` fields; PR title/body are even
split into `ctx/trusted.json` vs `ctx/untrusted.json`, which is prompt-injection awareness most
projects lack. Secrets are passed explicitly, never `inherit`.

The product consequence is a design constraint, not a footnote: **the exposure map must carry enough
detail to adjudicate, or it manufactures false alarms.** A graph that knows only
`secret ← workflow ← trigger` says "medium risk" here and is wrong. The edges have to carry the
mitigating facts — does any job check out PR head, is there `${{ }}` in a `run:`, are permissions
empty at the top level — so the view distinguishes *this shape exists* from *this shape is
exploitable*. That is the difference between our graph and a linter's finding list, and it is the
reason to model `USES_ACTION` / `REFERENCES_SECRET` / `TRIGGERS_WORKFLOW` with properties rather
than as bare edges. Filed as a constraint on git-serious-tap#6 (the projection page), not a defect.

---

## 2026-08-27 — the vocabulary becomes types

**decision — `git_ref`, not `git_branch`.** One type carries branch and tag, with `ref_type` as
the discriminator. The corpus recommended it; the ruling closes decision 2. Two arguments carried
it: tag movement is the detection for three incidents (a tag is a promise of immutability that
anyone with write access can break, which is the `actions/checkout@v4` class), and a ruleset's
target is a single enum spanning `branch|tag|push`, so a split type would fan that join across two
types and two edges for no gain. It was free to choose before the first collection and a migration
after.

**lesson — explain a modelling choice from the bottom of the stack, and the objection dissolves.**
George's answer to the first framing was "I need to understand more — I'm much more familiar with
branches." The framing that worked started below the disagreement: a commit has only a SHA; a ref
is a *name pointing at a SHA*, stored in a file; branches live under `refs/heads/` and tags under
`refs/tags/`, so they are the same structure with different social contracts. From there the
security argument writes itself. The objection that actually mattered — an unfamiliar word — turned
out not to bite at all, because **the slug is a modelling name and never has to reach a reader**:
views render "Branches" and "Tags". Worth remembering as a pattern: when a naming choice meets
unfamiliarity, check whether the name is even user-visible before defending it.

**finding — bypass observability is a property of the TRANSPORT, not of the credential.** Yesterday's
measurement said GitHub returns a ruleset's `bypass_actors` only to a caller with write access, and
that our App therefore cannot see them. Re-measured today with the same credential: **GraphQL
answers `bypassActors` with `totalCount: 0` and no `errors` entry at all**, where REST omits the key
entirely. Checked against an owner credential, every ruleset in our org genuinely has an empty
bypass list — so the distinguishing case (a truthful zero versus a silently filtered connection) is
**untested, and our own organization cannot test it**: proving it would mean adding a bypass actor
to a live ruleset, which is a change to our security posture rather than a measurement. The
derivation shipped is therefore asymmetric:

> `observable = REST carried the key OR GraphQL returned a NON-EMPTY list`

A non-empty answer proves itself — a filtered connection cannot invent actors. An empty one proves
nothing. False presence is impossible here; false absence is the entire risk.

**decision — a property that qualifies an ABSENCE belongs on the node, never on the edge.** The
corpus put `observable` on the `BYPASSES` edge. That is unimplementable as the only home: when the
answer is *none* or *unknown* there are no edges, so a view reading edges renders both as an empty
list — and "nobody can bypass" is the most reassuring thing a security product can say. The three
states moved onto the `github_ruleset` node (`bypass_observability`, with a **null** actor count
when unobservable, never a zero). The edge keeps its `observable` for per-actor provenance when a
merged picture is assembled from several credentials. This generalizes past this domain and is the
most transferable thing the day produced.

**step — the self-tier wave landed in `github_core`.** Six models (`workflow_job`, `git_ref`,
`github_ruleset`, `github_environment`, `actions_cache`, `app_installation`), eleven edges, one
migration, and the config-layer GraphQL query extended to carry rulesets, environments and every ref
alongside the workflow bodies it already inlined — 64 rate-limit points of 5000 for a 19-repo
account, against the ~85 REST calls it replaces. Every sub-connection reports its `totalCount`, so a
page cap becomes a warning rather than a silently short answer.

**decision — `permissions: null` and `permissions: {}` are different facts.** A job with no
`permissions:` block inherits the workflow's; `permissions: {}` grants its token nothing. Collapsing
them reads the most locked-down job in a repository as the most permissive one, and field history
would show a change that never happened. Same discipline as the grid's null-is-unobserved
convention, applied to a place where the *empty* value is the meaningful one.

**lesson — "verified" and "usable" are different claims about a credential.** The GitHub App was
created, installed and proven end-to-end yesterday — and the collector still could not use it,
because the auth seam did not exist and `self_test` reached for `data["token"]`. Building the wave
against an App-only surface (`app_installation`) forced the seam, which is the right order in
hindsight: the type that only an App can populate is what makes App auth non-optional. The
collector now dispatches on the envelope's own `kind`, and the JWT derivation lives in ONE module
that both the collector and the host-side verification script load — so the credential the operator
proves is minted the way the collector will mint it.

**decision — the envelope's `owner` selects the installation.** An App installed into several
accounts, with no `owner` to choose between them, is refused rather than defaulted to the first.
The failure it prevents is silent and plausible: one account's repositories collected under another
account's name.

**lesson — an invariant deserves a decision, not a shrug.** The collection manifest's rule is that
every source declares the permission it needs, because the App's least-privilege set is DERIVED from
those declarations. `/app/installations` has no fine-grained permission — it is App-JWT-level and
describes the App itself — so the choices were to invent a triple (corrupting the derived set) or to
let the field be absent (making omission indistinguishable from an oversight). Neither. The schema
now requires a triple **or** a stated `permission_not_applicable` reason, with a test asserting the
derived set is unchanged by the exemption so it cannot become a back door.

**lesson — re-read the emitters before trusting them.** A repo-scoping bug survived writing and
review-by-eye: `~DEFAULT_BRANCH` resolution keyed on the ref path alone, so a repository defaulting
to `main` would have marked *another* repository's `main` as protected by a ruleset that does not
protect it. Found by reading the code back rather than by a test, then fixed and pinned with one.

**step — the plugin validator earned its keep.** Six new models meant six missing icons, caught
before the PR rather than in review. Drawn to match the Octicons family used elsewhere in the set
but not labelled as Octicons: these concepts have no upstream glyph, and guessing at path data would
be a false attribution.

**step — first light on the new vocabulary.** One collection against `unified-systems-com` with
the App credential: 19 repos, **1014 nodes, 1352 edges**. On the grid: 163 refs (99 branches,
64 tags), 65 declared jobs, 6 rulesets, 4 environments, 220 cache entries, and the App
inventory. Numbers worth keeping because they are the demo:

- **47 of 220 cache entries are scoped to a pull-request ref** — an artifact written from outside
  a branch, sitting in the same repository a privileged job restores from. That is the convergence
  the corpus said `actions_cache` exists to make visible, and it was invisible an hour earlier.
- **8 of 65 declared jobs name an explicit checkout ref**; 32 inherit their permissions and 33
  declare their own. Half the org's jobs make a privilege decision the workflow file does not
  restate, and until today none of it was queryable.
- Every ruleset came back `bypass_observability = unobservable`, with a **null** actor count. That
  is the honest reading of what a read-only credential can see, and it is the cell that would
  otherwise have rendered as "nobody can bypass".

**lesson — the ruling was validated by the first collection, not by the argument.** Our own
organization turns out to have a `tag-protection` ruleset whose target is `tag`, and it resolved
onto a tag ref through the same `PROTECTS` edge as the five branch rulesets. Under `git_branch`
that join would have needed a second node type and a second edge on day one — the hypothetical
in the decision was already sitting in the org that prompted it.

**lesson — read the endpoint, not the noun.** `app_installation` landed exactly ONE node, and the
number was the tell. `/app/installations` answers "where is THIS App installed" — an inventory of
one, about ourselves — while `/orgs/{owner}/installations` answers "which Apps can reach this
account's repositories", which is the question the product exists to ask and the reason the App is
the product credential. Both are App-only surfaces that 404 for a token, which is how the wrong one
passed for the right one. The collector now asks the account first, falls back to its own
installation, and **records which answer it got**, because an inventory of one is not an inventory.
The fix widens the derived permission set by exactly one entry (`organization:administration:read`)
— named in the spec rather than left as an unexplained "exploratory" extra on the App, since the
alternative is a product that promises to show you which Apps reach your repositories and then
shows you itself.

**lesson — the same walk fetched every run's jobs twice.** Pre-existing, invisible at one repo,
and at account scope it is one extra API call per RUN — the largest single thing collected. Found
by watching a 10-minute collection time out against the boot's 600s budget rather than by reading
the code. The runner-matching pass now reuses the payloads the job pass already fetched; the
ordering constraint that caused it (runner nodes are not known until after the run walk) was never
a reason to fetch twice.

---

## 2026-08-27 — day-one retro (George, end of day)

**why a retro is in this file.** Everything above records machinery — spawn, boot records, the
conformance gate, collectors, defects. None of it records what the process cost the human running
it, and the operator is a load-bearing component of product building. If the `create-product` skill
is extracted only from the machinery half, it will produce a skill that builds products and burns
operators. What follows is George's own retro in his words, then observations from the session
(mine, marked as such — per the invented-convention correction above, whose lesson is *say who made
it and whether it was agreed*).

### What worked — George

**lesson — the app held together entering a new domain.** We flew into a space TAP had never
modelled, generated models wildly, and drove toward convergence. Along the way we picked up tips
and tricks for building models and created the wiki-page concept (domain articles). Covered the
waterfront.

**lesson — powering into a new space surfaced a real gap in our own tooling.** Reading the
prior-art corpus against Gryphon found a critical gap, which we pushed through to a fix. Same pass
validated the language capability *and* re-surfaced the module / ORM search paths as the backstop
for complex execution. Entering someone else's domain audited our own.

**idea — the emergence arc is exactly the shape we want.** Nobody in this field has built history,
or tracked prior runs as their own objects on a graph. That is an edge we can slot into and build a
name on, then extend into `supply_chain`, then into `code_paths`. Digging into a totally new space,
covering the waterfront, seeing how fast we can catch up using everything built to this point — and
potentially exceed the state of the art — is exhilarating, and it is the emergence the product map
argues for.

**idea — Tufte-format HTML primers are a game-changer, and generalise past this product.** Using
robots to come up to speed hard and fast on a new subject, with the information distilled and
tailored specifically for the reader, changes how a full-scope analysis of an unfamiliar field gets
approached. Worth treating as a first-class step in any new-domain skill, not a nicety.

### What didn't — George

**lesson — the number of sessions spiralled at ludicrous speed.** Cause: not understanding which
threads were actually running, and thinking a session was the right home for a train of thought.
Immediately lost track and focus; the result is classic thrashing. That is the downside of robots —
the cost of spawning another one is low enough that it stops feeling like a decision.

**lesson — over-compaction plus thrashing produced yolo acceptance.** There were a number of
messages where more information was needed to actually understand the thing, and the recommendation
got taken instead. Not disagreement, not agreement — saturation.

**lesson — pushing through instead of stepping back, and scarcity running in both directions.** The
day was blocked out for this, but the intensity was not anticipated. When it started getting away,
the call was to push through to a conclusion rather than stop and reassess. Classic scarcity —
unwilling to burn the day — combined with the thrill of pushing ahead from the morning, which is
scarcity operating in reverse: seeing ways out and getting excited.

**lesson — six concurrent activities is too many, and they are genuinely distinct.** Named, because
naming them is most of the fix:

1. *Learning about a new space* — never got sufficient headspace; over-compaction made it impossible
   to sit down and read.
2. *Researching the space* — decisive, and could have been used to build a targeted plan.
3. *Building the initial domain models* — good overall, getting toward something repeatable.
4. *Building the product* — which meant digging into github.com and understanding things not fully
   understood going in: bypass actors, rulesets, refs.
5. *Fixing TAP bugs* — which kept appearing all day, and drove thrashing.
6. *Assessing a path beyond the cutting edge* — deep philosophical work, seeing DCOM in action,
   trying to build those primitives while doing all of the above.

**bottom line — George.** Too much, too fast. Two to three times the time would probably have
produced better overall outcomes. What should have happened this pass: learn about git, study the
state of the art, **make issues for the things we need**, and at most do some sprint planning for
the coming week.

### Observations from the session — assistant, not agreed

**reframe — the problem was the missing parking mechanism, not the breadth.** Several of the day's
best outputs *required* the collision: DCOM, principles-as-predicate, the observation-dimension
defect, the coordinate-mismatch finding. None came from the research pass or the build pass alone;
they came from building while holding the research in mind. Run serially, the research would have
been stale abstraction by the time the build surfaced the questions it answers. What was genuinely
too much was that every thought needed a home and the only two homes were *act on it now* or *lose
it* — so sessions became the parking lot, and a parking lot made of sessions is thrashing by
construction. George reached the same fix independently ("we've got a legit issue tracking system
now"). Offered as a counter-read, not a ruling; the operator's own bottom line stands above.

**observation — most of the day's output was leverage, not deliverable, and that combination
reliably feels like thrashing.** A vocabulary corpus, an extracted skill, a design record, a doc
layer, an issue with its decisions pre-staged — none of it ships, all of it makes tomorrow cheaper.
The felt signal is "nothing shipped"; the actual signal is "a lot compounded." Worth being able to
recognise the pattern from the inside, because it recurs on every first day in a new domain.

**observation — the over-compaction was the assistant's, not just a context-window artifact.** The
CI/CD primer was compressed to a density that only works for a reader who already knows the
material; George's report was that it read like "English sentences while having a stroke." When the
reader is coming up to speed on an unfamiliar domain, density is the enemy, not the goal, and the
expanded form should be the default rather than the correction. Second tell, missed on the day:
three recommendations accepted in a row without pushback is not agreement, it is saturation, and
the right response is to slow down and check.

**observation — the concrete cost of session sprawl, for the skill's benefit.** By end of day the
`_dev-plugins/github_core` checkout held another session's uncommitted work — a new ruleset model,
`domain/`, `guards/`, and edits to `collector.py` — with no marker of whose it was or whether it was
safe to commit. Sprawl does not merely diffuse attention; it produces shared mutable state with no
owner.

### Rules and decisions out of the retro

**rule of practice — a session is where work LANDS; a thought goes in an issue.** Spawn when there
is a defined deliverable and a branch. Everything else is `gh issue create`. One line, testable, and
it is the specific discipline whose absence produced today's sprawl.

**decision — tomorrow is a triage and sequencing day, not a learning day.** The learning and the
state-of-the-art study are already done: the overlay survey, the vocabulary corpus, the CI/CD
primer, and the impressions register with dispositions all exist. Starting tomorrow by re-reading
would redo today. The raw material for a backlog is already present — the vision (three questions,
the viz, derived criticality, the tap-shaped panel, principles-first), the corpus's tier column, and
the register's dispositions. The job is converting it, not generating it.

**decision — the planning day gets its own finishable deliverable: a sprint with N sized items, and
nothing else.** A planning day's failure mode is that it feels unproductive around 10am, which
triggers the same scarcity response, and by 11 it has become a building day. A completable
deliverable is the counter.

**rule — the friends filter.** Every self-tier item gets a second question during triage: **does
this choice survive contact with someone else's org?** If not, either fix it now while it is still a
config decision rather than a migration, or file the friends issue alongside it so the discontinuity
is recorded rather than rediscovered later by someone with less context.

**the five self→friends discontinuities**, recorded so the filter has teeth. The gap between the
milestones is not features; it is that *someone else runs it, on their org, with their credentials,
without us in the room*.

1. **The credential.** Neither the owner-PAT nor the App dominates — the App cannot see
   `bypass_actors`, the PAT cannot see installations or PAT grants. Friends needs a credential story
   with a published ceiling. Impression 15 (the App points at the *user's* instance and asks them to
   run code in their environment) is still unanswered and is the largest single discontinuity.
2. **Anything hardcoded to our org.** This is why deriving the tap panel's columns from the gate's
   `needs:` list matters more than it looks — it is the difference between a demo and a product. Same
   for criticality: hand-declared survives self and rots in friends; derived-with-override survives
   both.
3. **Principle authorship, and this is the sharpest one.** Our estate is unusually disciplined —
   sixteen actions pinned by hash, `permissions: {}` throughout, one computed gate, thirteen repos on
   one reusable standard. A normal org scores terribly against those seven principles. If a friend's
   first install reports "37 violations," they conclude the tool is noise and close the tab, and they
   are half right: most of those are differences from *our* opinion, not violations of *their* intent.
   Item 30's two-authors rule is the answer, but for self the distinction is invisible because our set
   *is* the set — so it must be built into the first principle, not retrofitted after the first friend
   is insulted. The mitigation is also an ordering: **show what the system IS before saying what it
   SHOULD BE** — Q3 before Q2, which the vision already picked for unrelated reasons.
4. **Honest partial collection.** Our org is 19 clean repos and the first org run still lost 6 of them
   to transient TLS timeouts before guards went in. A friend's org is larger, rate-limited, and holds
   permissions we do not have. The "not observed" affordance in the visualisation is not polish; it is
   what keeps a partial picture from being a confident lie at scale.
5. **Brand from the boot profile** (git-serious-tap#18) — self-tolerable, friends-fatal, already filed.

### What the `create-product` skill should take from this

**Entering a new domain is at least six distinct activities and the skill must name them.** The six
above are the list. The skill's default should be to sequence them with explicit parking between,
not to run them concurrently because an agent makes concurrency cheap.

**An issue tracker is a precondition, not an output.** The skill should refuse to start the build
phase without a place to park work, because the alternative parking lot is sessions.

**A human-facing primer is a first-class step**, authored expanded rather than compressed, and
produced *before* the build phase rather than during it. The operator cannot make good calls about a
domain they are still assembling in their head between tool calls.

**The research pass should terminate in a targeted plan.** Today's research was decisive and went
straight into building instead of into a plan; the plan is being reconstructed a day later from
documents written for other purposes.

**Record the operator's load, not only the machinery.** This section exists because the rest of the
file did not.

**A product-level CI lane is a step in the process, not a later polish** (added 2026-09-02, tap#290).
The skill must generate the product's CI in two lanes: the seed-only admission gate every plugin
already gets, and a **live lane** — scheduled from `main`, booting the product's record on a real
stack and firing its collectors against a real organization with a read-only credential minted for
CI — whose done-test is correctness, not presence: the collected repository count equals the API's
answer in the same run, the lane finds its own workflow run on the grid, and every surface the
credential cannot read renders *not observable*. Observed on git-serious the day the first live
instance booted: no product had ever run a collector in CI, and the nightly skew detector's roster
(`tap-plugin-*`) did not even see the product repo. A product whose CI never touches the world it is
for has proved that its record resolves, and nothing else.
