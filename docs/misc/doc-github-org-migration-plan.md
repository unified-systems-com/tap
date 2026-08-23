---
title: GitHub Organization Migration Plan
spec: tap_plugins/specs/spec-tap-plugin-external-development.md
audience:
  - llm
  - developer
status: plan
---

# GitHub Organization Migration Plan

Move the TAP repositories from the personal account `notgeorge` to a GitHub **Organization**.

Decided 2026-07-21 as the next GitHub-cleanup work. Nothing is broken today — this is
optionality plus Aug-1 external-developer readiness, and it unblocks two already-deferred
requirements. Written up so it does not live only in a chat log.

## Why — the forcing functions, in the order they actually bit

1. **Token sprawl.** A personal account has **no organization-level Actions secrets**, so
   the `TAP_CORE_RO_PAT` that the per-repo CI needs must be set on **every plugin repo**
   and re-set on every one at each rotation. That friction is why a broad read-only PAT
   was chosen over per-repo scoping (2026-07-21) — the secure option was the inconvenient
   one. An org inverts that: one org secret with a repo allowlist, or better, a **GitHub
   App** whose installation tokens are short-lived, per-repo scoped, auto-rotating, and
   not tied to a human account.
2. **Governance applied once instead of seventeen times.** Org rulesets push branch
   protection / required checks / required reviews across every plugin repo from one
   place. Today "protect `main` everywhere" is a per-repo config that will drift. The
   external-dev kit already calls for protected main + PR-back review.
3. **`CODEOWNERS` can only name individual users** on a personal account. The
   guard-integrity work uses CODEOWNERS; team ownership (`@org/team`) needs an org, and
   it is how the single-named-owner bottleneck goes away.
4. ~~**Signing is blocked on this.**~~ **CORRECTED 2026-07-22 — this driver was wrong.**
   `req-tap-plugin-extdev-signing` (#5) and `req-cicd-supply-chain-provenance` are *not*
   unblocked by the org. GitHub gates artifact attestations by repository visibility, not
   by org membership: *"If you are on a GitHub Free, GitHub Pro, or GitHub Team plan,
   artifact attestations are only available for public repositories. To use artifact
   attestations in private or internal repositories, you must be on a GitHub Enterprise
   Cloud plan."* Worse, GHEC's private-repo attestations use GitHub's **own** Sigstore
   instance with **no transparency log**, whereas public repos use the Sigstore Public
   Good Instance **with** a public immutable log. So the private path costs $21/user/mo
   for the strictly *weaker* provenance artifact. Signing is blocked on the
   **public/private decision**, not on the org and not on money. *(Resolved: repos went
   public 2026-08; SLSA attestations on the published container images went live
   2026-08-09 via `publish-images.yml` on the Sigstore Public Good Instance —
   `req-cicd-supply-chain-provenance` is Partial.)*
5. **External developers arrive ~Aug 1.** On a personal account every external dev is a
   collaborator on personal repos. An org gives scoped teams and a boundary between "our
   plugins" and "theirs" — and avoids onboarding devs under a credential model we then
   migrate underneath them.
6. ~~**A home for the package index.**~~ **FALSIFIED 2026-07-22.** GitHub Packages
   supports npm, RubyGems, Maven, Gradle, NuGet and Docker/OCI. **Python/PyPI is absent
   from the registry table entirely** — it is not a supported ecosystem at any tier in
   2026, and the org "linked artifacts" / virtual registry is metadata only and hosts no
   package files. Org-scoped GitHub Packages is not "the natural answer" for the deferred
   `index` / `wheelhouse` source paths (`req-tap-plugin-arch-sources-3` / `-6`); it is not an
   answer. Those need a different home — git+https as today, AWS CodeArtifact, S3 behind
   a PEP 503 index, or self-hosted devpi — independent of this migration.

## Measured inventory (2026-07-21 — verified, not estimated)

### Repositories: 17 under `notgeorge`

| Class | Repos | Migrate? |
| --- | --- | --- |
| Core | `tap` | yes |
| Live plugins (in boot profiles) | `tap-plugin-` + `administrivia`, `computing-core`, `roscale`, `identity-core`, `aws-core`, `sigstore-core`, `github-core`, `compliance-core`, `fedramp-20x-ksi`, `samsite`, `grid-fixtures`, `gryphon-playground` (12) | yes |
| Deferred but real | `tap-plugin-aws-secrets-source` (build-bake eviction still open) | yes — **RE-HOMED 2026-08-09**, see below |
| Dead weight | `tap-plugin-aws`, `tap-plugin-genericom` (plugin deleted) | ~~yes~~ **no — REVERSED 2026-08-08** |
| Stays behind | `tap-plugin-lotr` (already archived) | **no** — stays on `notgeorge` as the archaeology shelf |

Verified 2026-07-22: all three dead repos have **zero** references anywhere in this
repo — no boot profile, no code, no config. Leaving any of them behind is free.
`tap-plugin-lotr` in particular is already archived, and transferring an archived repo
would mean unarchive → transfer → re-archive for no gain.

**RE-HOMED 2026-08-09 — `aws_secrets_source` moved to `tap-build-dependencies`;
`tap-plugin-aws-secrets-source` archived.** The nightly plugin matrix's first run
flagged what the extraction commit had said all along (*"Not a grid plugin"*): the
artifact is a **bootstrap-tier secret-source provider** — it installs at image build,
below the plugin system, because in CI the credential that installs plugins can itself
arrive through it — so a `tap-plugin-*` name promised a contract it was never meant to
meet. It now lives in **`unified-systems-com/tap-build-dependencies`**: the loudly-named,
hardened home for build-time dependencies that don't fit the plugin system (rulesets:
no force-push/deletion, protected tags, linear history, secret push-protection;
CODEOWNERS committed as the one-toggle path to required-review). Trust model: the
load-bearing install-time controls are core's `_ALLOWED_SOURCE_DISTRIBUTIONS` allowlist
plus consumers pinning exact revs; the repo gates are defense-in-depth over writes.
Core's in-tree `plugins/aws_secrets_source/` copy (byte-identical at the move) remains
the LIVE one until the build-bake eviction completes: wire image builds to install from
`tap-build-dependencies` at a pinned rev, prove green, then delete the in-tree copy.

**REVERSED 2026-08-08 — `tap-plugin-aws` and `tap-plugin-genericom` now stay behind too,
so 14 repos migrate, not 16.** The 2026-07-22 decision to bring them was made when the end
state was a private org. It is now public-everything, and these two are not going public
(publishing dead code whose plugin was deleted is a choice with no upside). Carrying two
*private* repos into a public-everything org reintroduces exactly the friction the migration
removes: no artifact attestations without Enterprise Cloud, org secrets that behave
differently on private repos, and a same-owner `uses:` constraint if either ever gets CI.
They join `tap-plugin-lotr` on the archaeology shelf. Both are Apache-2.0 licensed as of
2026-08-08, so reviving or publishing one later needs no further licensing work.

**14 repos migrate:** `tap` + the 13 plugin repos above.

One-way caveat: if a repo saw >100 clones or >100 Actions runs in the week before
transfer, GitHub *permanently retires* the old `notgeorge/<name>` — you cannot recreate a
placeholder there afterwards. Also note redirects are destroyed permanently if a new repo
is ever created at an old name.

### In-repo changes: ~30 functional lines, ZERO code

| What | Count | Note |
| --- | --- | --- |
| Boot-profile `url:` entries | 26 across 4 committed profiles (`core_dev` 1, `soak` 2, `samsite` 11, `test_all` 12) | pure data |
| `.github/workflows/plugin-ci.yml` → `harness_repo` default | 1 | |
| `ci/terraform/codebuild-runners/variables.tf` → `github_owner` default | 1 | |
| `scripts/spawn-session.sh` help examples | 2 | cosmetic |
| Test fixture URLs (`test_plugin_source_auth`, `test_dev_workspace`, `test_plugin_release`) | 3 | synthetic strings |
| Docs / specs prose | ~20 | follow-up, non-blocking |

**No code changes at all.** Nothing derives a repository URL from the owner — the
boot-record `url`/`credential` is the authority and the slug is deliberately never used to
derive a URL (`spec-dev-plugin-workspace.md`). That decision is what makes this a config
migration rather than a refactor. **Do not regress it** by introducing owner-derived URLs.

## The one real risk: the PAT cliff

Fine-grained PATs are scoped to a **resource owner**. The moment the repos become
org-owned, a user-owned PAT scoped to *user* repos loses access — and an org can
additionally **require approval** for fine-grained PATs (the likely surprise). At transfer
time, plugin git-install breaks **everywhere simultaneously**: local boot, both CodeBuild
lanes, and per-repo CI.

Two amplifiers:

- **`~/tap-secrets` is shared host state** — symlinked into every session worktree, so
  re-issuing the token mutates *every live session at once*.
- The same credential is duplicated in **AWS Secrets Manager** (`tap-ci/github-plugins-ro`)
  for the CodeBuild lanes. Both copies must move together or the lanes go red.

Everything else is low-drama and reversible. **GitHub redirects old URLs for git
operations**, so boot profiles keep working after the transfer — which usefully decouples
the URL rewrite (step 5) from the transfer itself (step 3).

### Two credentials, do not conflate them

| Credential | Reads | Lives in | Consumers |
| --- | --- | --- | --- |
| `github-plugins-ro` | plugin repos (**404 on core** — verified) | `~/tap-secrets/tap_plugins/…`, AWS Secrets Manager | local pre-boot install, CodeBuild lanes |
| `TAP_CORE_RO_PAT` (`harness_pat`) | core `tap` only | GitHub Actions repo secret on the plugin repo | per-repo CI conformance job |

They point in **opposite directions** and must stay separate even while both are broad.

## The second real risk: reusable workflows are same-owner-only

**Discovered 2026-07-22, confirmed in GitHub docs.** Private reusable workflows can be
shared *only* with repos owned by the same user or organization. The `access_level` enum
is `none | user | organization`, and the UI offers only the value matching the repo's own
owner type — there is **no setting** that lets an org-owned repo call a **user**-owned
private repo's reusable workflow, or the reverse.

Compounding it: *"GitHub Actions does not support redirects for actions or reusable
workflows."* Unlike git operations, a `uses:` reference breaks the instant the owner
changes, and the error (`workflow was not found`) is identical to "file missing" and
"Actions disabled" — it will not tell you which.

**Therefore core and every plugin repo that has CI must transfer as ONE wave, with every
`uses:` rewritten in that same wave.** Today that unit is exactly `{tap,
tap-plugin-grid-fixtures}` — small only because the other 11 plugin repos have no CI yet.
The deliberate hold on wiring them (see "Not yet done") is load-bearing, not merely tidy.

Note this constraint is about **owner matching, not tier** — sharing a private repo's
reusable workflow org-wide is not a paid feature.

## Sequence

Each step independently verifiable; risk-ordered so the scary part is proven on one repo.

**Revised 2026-07-22.** Three changes from the original ordering, all forced by
verification: the credential swap moves *into* the pilot; the URL rewrite and promote
happen *before* core moves; and core moves last, welded to `grid-fixtures`,
CodeConnections and Terraform.

| # | Step | Gate |
| --- | --- | --- |
| 0 | **Decide.** — *closed 2026-07-22, see Decisions below* | — |
| 1 | Create org `unified-systems-com`; upgrade to **Team**; install AWS Connector GitHub App on it. **Transfer nothing.** | Org exists, app installed |
| 2 | **PILOT: transfer `grid-fixtures` only.** Pause its CI workflow first (it *will* break — deliberately, not mysteriously). Re-issue an org-scoped PAT into a **session-local** secrets dir. | Redirect resolves; local boot green on `core_dev` — *without touching `~/tap-secrets`* |
| 3 | Transfer the remaining 11 live plugins + `aws-secrets-source` + `tap-plugin-aws` + `tap-plugin-genericom`. | All clone with the org PAT |
| 4 | **Credential swap:** `~/tap-secrets` **and** AWS Secrets Manager together. | Scratch spawn installs all plugins; both CodeBuild lanes green — *core still on `notgeorge`, so the gate still works* |
| 5 | Rewrite 26 boot URLs + 2 defaults + 3 test fixtures; promote. | `scripts/gate` green; promote gate green |
| 6 | **ATOMIC:** transfer `tap`; rewrite `grid-fixtures`' `uses:`; Actions `access_level` → `organization`; new CodeConnections; `terraform apply`. | `terraform plan` clean; real `product-lines` run green; `grid-fixtures` CI green |
| 7 | Org hardening: org secret replaces per-repo `TAP_CORE_RO_PAT`; delete per-repo copy; org rulesets; CODEOWNERS; wire the 11 remaining plugin CIs. | A plugin repo's CI passes on the **org** secret; per-repo secret deleted |
| 8 | Docs/specs prose sweep. | — |
| 9 | **Retire the AWS account** (`180731181784`) — see below. **Strictly last.** | New account carries the CI substrate + samsite; old account closed |

Steps 2–4 are the disruptive window (a few hours, much of it GitHub UI work only George
can do). 5–8 are ordinary work. Step 9 is a separate project of its own and is deliberately
fenced off at the end — see below.

### Why the reordering was necessary

- **The credential cliff arrives at step 2, not step 4.** The CodeBuild `test_all` lane
  git-installs all 12 plugins, `grid-fixtures` included. A fine-grained PAT has exactly
  one resource owner, so the moment `grid-fixtures` is org-owned the existing token 404s
  on it. The swap cannot wait.
- **Step 5's gate depended on step 6.** CodeBuild's project source is
  `https://github.com/${var.github_owner}/${var.github_repo}.git` with `github_repo =
  "tap"` — the lanes are bound to **core** — and `promote-to-main.sh` step 2.6 dispatches
  `product-lines.yml` onto them. Transferring core kills the promote gate until
  CodeConnections + `terraform apply` is redone, so "promote through the normal gate"
  cannot be verified if core moved in step 3.
- **`TAP_SECRETS_ROOT` is an env var** and `tap_secrets` is a per-worktree symlink to the
  shared store, so the pilot can point *one session only* at a private secrets dir. The
  "shared host state mutates every live session" amplifier disappears for step 2.

## Do this during the migration, not after

**Move plugin-pull from a PAT to a GitHub App installation token.** It is the end state
regardless; doing it *during* the transfer avoids a second credential swap, and it removes
the "read-everything token sitting in a repo secret" pattern **before** external developers
inherit it. An external dev holding a token that reads the whole account is a materially
different risk from us holding one — and anyone who can push a workflow to their own plugin
repo can exfiltrate whatever secret that repo holds.

## Step 9 (backlog): retire the AWS account

**Decided 2026-08-08.** AWS account `180731181784` gets stood down and replaced. The driver
is disclosure hygiene, not a live incident: the account id is spread across public-bound git
history and — as the audit below establishes — cannot be recalled by editing. Retiring the
account is the compensating control that makes the disclosure inert, and it is strictly
cheaper than rewriting the history of every repo. *"It's unnecessary to give anyone the
knowledge of where my stuff sits."*

**Why it must be last.** That account is not a bystander to this migration; it currently
carries most of the substrate the earlier steps depend on:

- the **CodeBuild product-line lanes** — the promote gate itself (`product-lines.yml`,
  `line=test_all`), which step 6 rebuilds against the org;
- the **CodeConnections** app installation step 6 recreates, and the **Terraform** that
  defines those lanes;
- the **S3 tfstate backend** recovered in `09b179f2`, a stated prerequisite for step 6;
- the **AWS Secrets Manager** copy of the plugin-pull credential that step 4 swaps;
- the **samsite deployment** itself — the reference assessment target the `samsite` boot
  profile collects from.

Doing this before step 8 would mean rebuilding the CI substrate twice and losing the promote
gate mid-migration, which is the same failure mode that already forced core to move last.

**Rough shape of the work** (not planned in detail — that is the point of backlogging it):
stand up the replacement account; re-run the CodeBuild Terraform against it with a fresh
CodeConnections; migrate the tfstate bucket; re-create the collector IAM principal and
re-issue the collector secret; redeploy samsite and repoint `artifact_manifest.json`; verify
a real promote runs green end to end on the new account; only then close the old one.

**Not a blocker for going public.** The disclosure is an account id, not a credential, and
this step makes it moot on its own schedule.

## Decisions — locked 2026-07-22

| Decision | Value | Note |
| --- | --- | --- |
| Org name | **`unified-systems-com`** | Verified available. Matches `unified-systems.com`. `unified-systems` (org, 0 repos, dormant since Jan 2024) and `unifiedsystems` (user, dormant since 2015) are both squatted. Renaming later is *not* free — Actions `uses:` refs do not redirect and provenance claims are historical. |
| Tier | **Team**, $4/user/mo, from step 1 | Eventual state is public repos, but stealth/private for the next several months; buy CODEOWNERS + rulesets + branch protection on private repos now to build the muscle memory. Tier is a slider, not a one-way door — revisit at step 7. |
| Repos migrating | **16** | All except `tap-plugin-lotr`, which stays on `notgeorge` (already archived; transferring it would mean unarchive → transfer → re-archive for no gain). |
| Plugin-pull credential | **Fine-grained PAT**, org-scoped | Not a smell: the credential is already stored as an envelope, fed via `GIT_ASKPASS`, redacted in `__repr__`, never interpolated into the URL. See "GitHub App" below. |

### GitHub App — parked, not rejected

The original plan recommended moving plugin-pull to a GitHub App *during* the migration.
Two findings changed that:

1. **It is cheaper than assumed** — the seam already exists. `SecretSource.fetch()`
   returns "exactly what the envelope would have held inline on disk", so a `github_app`
   provider mints the 1-hour installation token and `plugin_source_auth.py` never knows
   the difference. The schema *already* documents `x-access-token` as working for "both
   fine-grained/classic PATs **and** GitHub App installation tokens". By the
   `aws_secrets_source` precedent (58 lines of provider + 29 pyproject + 93 tests) this is
   a slim out-of-core distribution plus a one-line widening of
   `_ALLOWED_SOURCE_DISTRIBUTIONS` — **no core pre-boot change**.
2. **It may be unnecessary.** `plugin_source_auth.py` implements conditional necessity —
   *"a git source with no `credential` is public and never raises"*. If the primary
   plugins go public, their boot-record sources declare no `credential` at all and the
   plugin-pull token ceases to exist. Same for `TAP_CORE_RO_PAT` if core goes public.

So build it only if the private product line needs authenticated pull. Aim it at
`TAP_CORE_RO_PAT` first when it comes up — that is the read-everything token external
developers' repos will actually hold.

## Resolved questions (verified 2026-07-22)

- **Free vs Team tier** — RESOLVED. Rulesets, protected branches and CODEOWNERS are all
  *"public repositories with GitHub Free"* only; on a Free org a CODEOWNERS file in a
  private repo does nothing. Worse for driver #1: *"Organization-level secrets and
  variables are **not accessible by private repositories** for GitHub Free."* **Team is
  the floor** for the migration's own justification. Add-ons deliberately skipped: Secret
  Protection $19/active committer, Code Security $30/committer — 5–7× the plan cost.
- **CodeConnections** — RESOLVED: must be **recreated**. There is no `UpdateConnection`
  API for connections; the connection rides a specific GitHub App installation, and AWS
  states a connection bound to a dead installation *"will not revive… you will need to
  create a new connection."* The console browser authorization is unavoidable, and *"to
  create the connection, you must be the GitHub organization owner."* Terraform already
  models this (`codeconnection_arn = ""` → creates one PENDING).
- **Org PAT-approval policy** — RESOLVED, and it is **not** the feared surprise.
  Require-approval *is* the default on a new org, but *"fine-grained personal access
  tokens created by organization owners will not need approval."* George is the owner, so
  his re-issued token is auto-approved. The friction lands on external devs later.

## Still open

- **Which repos go public, and when.** This is the real architectural fork: it decides the
  signing story (driver #4), whether the plugin-pull credential exists at all, and whether
  Team is the end state. Likely a **mixed org** — public substrate (`grid-fixtures`, the
  `*_core` plugins, `gryphon-playground`) alongside private products (`samsite`,
  `fedramp-20x-ksi`). Visibility is per-repo and boot records already carry per-source
  credentials, so a public plugin simply drops its `credential` key.
- **Publishing is a one-way door.** Once a repo is public its history is cloned and
  indexed permanently, so any credential *ever* committed is exposed for good — a check of
  the current tree is not sufficient. `scan_paths_for_secret_leaks` only detects a
  committed secret-*envelope* JSON file; it is not a general scanner and does not read
  history. A real history audit (gitleaks/trufflehog over full history) is a prerequisite
  for any flip, and GitHub push protection — Secret Protection add-on, $19/committer — is
  the control that best defends that door going forward.

  **Audit run 2026-08-08 — no credentials, but the AWS account id is unrecallable.** All 29
  repos under `notgeorge` were scanned exhaustively: every blob in each object store
  (deduplicated, *including* objects unreachable from any ref), not merely the tip trees or
  the reachable commit graph. `tap-plugin-samsite` was used as a planted positive control so
  a scan that silently read nothing could not report clean — the false-green failure mode
  that already bit the core credential audit once.

  Result: **zero real AWS access keys anywhere.** The only credential-shaped hits were 207
  occurrences of `AKIAIOSFODNN7EXAMPLE` <!-- TAP-CREDENTIAL-OK: AWS's published doc placeholder, quoted as the audit finding -->
  — AWS's own canonical documentation placeholder — in vendored third-party Teleport docs,
  not our code. (Quoting it here tripped the new pre-commit hook on the first commit
  attempt; resolved with the documented marker rather than `--no-verify`.)

  AWS account id `180731181784` is present in six repos: `tap` (**195 blobs** in history vs
  4 files at HEAD), `tap-plugin-aws-core` (16 / 1 — test fixtures), `tap-plugin-samsite`
  (4 / 2), `tap-plugin-roscale` (4 / 1 — an OSCAL fixture), `samsite` (4 / 1), and `rampart`
  (4 / **0** — history only). Core's spread is monorepo-era residue from when samsite,
  aws_core and roscale lived inside it.

  **Decision: do not rewrite history for this.** An account id is not a credential, and the
  codebase already takes that position in `account_mismatch_error` — *"Account ids are
  non-secret identifiers and are safe to surface in the message"* — while
  the aws-static secret requirement (`spec-aws-core-secrets.md`, aws_core plugin repo)
  has operators writing their own into a config file.
  Rewriting ~1,200 commits of core to hide a value we classify as non-secret is a bad trade.

  **And HEAD is not being scrubbed either (decided 2026-08-08).** A tree-level scrub is
  cosmetic while the history ships, so it buys nothing on its own; the id is fine where it
  sits. Step 9 above is the whole remedy — once the account is closed the disclosure is
  inert everywhere at once, in history and at HEAD, across every repo, with no edits.

## Status of the work this plan came out of (all landed, `origin/main` `f9fec738`)

- Migration squash + re-release wave complete; plugin fleet on post-squash tags.
- CodeBuild tfstate recovered into S3 (prerequisite for step 6).
- `plugin-ci.yml` — the reusable per-plugin CI — **fixed and proven green** on
  `tap-plugin-grid-fixtures` (2026-07-21). It had never compiled; three defects were found
  by finally running it. This is CI lane 2 of the three-lane model.
- Core Actions `access_level` set `none` → `user` so plugin repos can call it.

### Not yet done, and NOT blocked on the org

- **11 remaining plugin repos have no CI.** Deliberately held: each one wired now is one
  re-configured after the migration. Wire them in step 7, using the org secret.
- `roscale`'s in-package manifest test resolves its plugin root to `/app` when run from an
  installed wheel (validates core as a plugin, fails). Latent today; will surface when lane
  2 runs against installed plugins.
- `plugin-ci.yml` pins `astral-sh/setup-uv@v5`, which triggers a Node 20 deprecation
  warning on GitHub runners.

## The legal / copyright wave (added 2026-08-08 — the remaining standard docs)

The migration's disruptive phase completed 2026-08-08 (all 14 repos public on the org, CI
rebuilt and green, zero standing credentials). What remains is the **documents wave**,
gated on two external events: the copyright assignment to Unified Systems LLC closing
(days away) and legal review of the contribution docs.

**Delivery vehicle — an org-level `.github` repository.** GitHub applies community health
files in a public org repo named `.github` as *defaults for every repo in the org* that
lacks its own copy (surfaced in issue/PR flows and community profiles as if committed
locally). Write each doc once there; all 14 repos inherit; any repo can override by
carrying its own. This turns "apply the model fleet-wide" into one repo's worth of work.
The repo must be public. LICENSE/NOTICE are NOT inheritable this way — those stay per-repo.

Checklist, in dependency order:

1. **Copyright swap** (on assignment closing): `Copyright 2026 George Chamales` →
   `Copyright 2026 Unified Systems LLC` in all 16 LICENSE files (14 org repos + the two
   shelved dead repos if ever revived — lotr excluded, archived) and core's NOTICE. One
   mechanical pass; the LICENSE files are otherwise byte-identical canonical Apache 2.0.
2. **CONTRIBUTING.md** (George's draft, in legal review) + **DCO** (verbatim 1.1, text at
   developercertificate.org): the sign-off model. Lives in `.github` repo as the org
   default; core may carry a tailored copy.
3. **GOVERNANCE.md**: single-maintainer model (BDFL-style) stated once for legibility;
   the maintainer's title is **Philosopher King For Now**, and the structure "is neither
   constitutional nor a lifetime sentence" (George's wording — keep it). Contributor
   ladder: contributors (fork+PR, no org membership) → triagers (future team, `triage`
   role) → `maintainers` team (`maintain` role, exists, membership by invitation) → org
   owner (break-glass only, not a working identity).
4. **CODE_OF_CONDUCT.md**: Contributor Covenant unless legal prefers otherwise.
5. **SECURITY.md**: points at GitHub private vulnerability reporting (enabled on all 14
   repos 2026-08-08); supported-versions statement; response expectations; safe-harbor
   language (legal input needed on that clause).
6. **Issue / PR templates + SUPPORT.md**: PR template reminds about DCO sign-off.
7. **CODEOWNERS flip** (independent of legal): `@notgeorge` → `@unified-systems-com/
   maintainers` (team exists with `maintain` on all 14). Needs its own reviewed commit —
   the file self-owns.
8. **After the wave**: enable require-code-owner-review only when the maintainers team has
   a second member (a sole code owner cannot approve their own PR — deadlock); the
   require-PR repo ruleset on core waits on the promote-via-PR rewrite either way.
