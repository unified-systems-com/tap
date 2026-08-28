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

Product repo: https://github.com/unified-systems-com/git-serious-tap (local clone:
`~/tap-products/git-serious-tap` — product repos live beside, not inside, TAP session
worktrees, because despawn deletes the worktree).

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
