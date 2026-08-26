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
