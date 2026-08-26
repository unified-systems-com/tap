---
audience: [llm, developer]
covers:
  - doc-dev-validation-ci-runner-strategy.md
  - ../../ci/terraform/codebuild-runners/README.md
  - ../../specs/spec-security-posture.md
assumes:
  - Reader knows the AWS CodeBuild per-product-line CI lanes are stood up (Terraform in ci/terraform/codebuild-runners/, account 180731181784, keyless SSO) and that they register as ephemeral GitHub Actions self-hosted runners via a CodeConnections GitHub App.
  - Reader knows the secret-source seam (spec-tap-plugin-dependency-resolution.md req-tap-plugin-depres-sources) now resolves the github-plugins-ro credential from AWS Secrets Manager in the cloud and disk locally.
  - This is a ROADMAP doc — a phased migration thought through in advance, not a spec and not yet built. Phase 0 is today's reality; Phases 1–4 are the level-up.
provides: |
  The target hardened state for the AWS↔GitHub trust relationship the CI lanes depend on:
  a read-only-where-possible connection, the unavoidable write surface isolated onto a
  disposable machine (bot) account inside a GitHub Organization, least-privilege and
  auditable. Enumerates every trust edge today with its privilege and blast radius,
  states honestly what is and is not reducible to read-only, and lays out a four-phase
  migration ladder with concrete actions, what each buys, and the decisions to settle
  first.
---

# GitHub ↔ AWS Connection Hardening — Read-Only, Bot-Isolated, Org-Backed (Roadmap)

> A roadmap doc for a migration we are **not yet executing** — queued up and thought
> through so the level-up is a decision, not a scramble. Phase 0 is today's reality
> (personal account, broad App on one repo); Phases 1–4 harden it. The animating goal:
> **AWS should hold read-only access to GitHub wherever the mechanism allows, and where a
> write is unavoidable it should be exercised through a disposable, scoped, auditable
> identity — never the human owner's personal account.**

## 1. Thesis — minimize the standing write, isolate what remains

Standing up AWS-native CI created a durable trust edge: AWS can act on GitHub. Today that
edge runs through the **AWS Connector for GitHub** App — *as of 2026-08-08 installed on
the `unified-systems-com` org (scoped to `tap` only), no longer under the personal
`notgeorge` account; the connection was recreated and authorized by George during the org
migration* — holding `Administration:write` + `Repository hooks:write` on the
`tap` repo. That is more standing power than the *human owner's personal identity* should
lend to an automated, AI-operated system — and it is the exact asymmetric surface the
security posture says to harden while it is cheap ([spec-security-posture.md](../../specs/spec-security-posture.md)).

The thesis has three moves, in priority order:

1. **Read-only where the mechanism allows.** Some trust flows (pulling private plugins,
   checking out code) are *inherently* read-only and should carry no write scope. Others
   (registering a runner, creating a webhook) *require* write. Separate them and grant
   each exactly its need — never a single broad credential spanning both.
2. **Isolate the unavoidable write onto a disposable identity.** The runner-registration
   write cannot be made read-only (§3), so the goal shifts from *eliminate* to *contain*:
   move it off the personal account onto a **machine (bot) account** whose entire reach is
   the CI repos, inside a **GitHub Organization** where that scoping is clean rather than
   cosmetic. If the CI trust is ever compromised, the blast radius is a login-less bot with
   admin on two CI repos — not the identity that owns everything.
3. **Make it auditable and revocable.** Every edge should be attributable to a named
   identity, scoped to named repos, expiring where possible, and revocable in one action —
   so the org audit log answers "what can AWS do to GitHub, and who authorized it?" without
   reading Terraform.

This is the identity-isolation half of the same cheap-edge discipline the secret-source
seam just applied to the *value* half: the plugin-pull credential already moved to AWS
Secrets Manager, read-only, fetched by ambient IAM ([doc-dev-validation-ci-runner-strategy.md](doc-dev-validation-ci-runner-strategy.md)
machine-account section; the seam is `req-tap-plugin-depres-sources`).

## 2. The trust edges today (Phase 0)

Every place AWS and GitHub currently trust each other, with direction, what carries it,
its privilege, and the blast radius if that carrier leaks:

| # | Edge (direction) | Carrier | Privilege | Blast radius if compromised |
| --- | --- | --- | --- | --- |
| E1 | **AWS → GitHub**: register ephemeral runner | AWS Connector App (under `notgeorge`) | `Administration:write` on `tap` | Repo admin on `tap`: settings, collaborators, delete, protection rules |
| E2 | **AWS → GitHub**: WORKFLOW_JOB_QUEUED webhook | same App | `Repository hooks:write` on `tap` | Create/alter/read repo webhooks (exfil push events) |
| E3 | **AWS → GitHub**: (unused breadth) | same App | `Contents:read`, `Commit statuses:write`, `Pull requests:write` | Carried by the shared App manifest; not exercised by our use, cannot be declined per-permission |
| E4 | **Job → GitHub**: checkout `tap` | GHA `GITHUB_TOKEN` (per-job, auto) | `contents:read` (default) | Ephemeral, per-job, auto-expiring — already ideal |
| E5 | **Job → GitHub**: pull private plugin repos | `github-plugins-ro` PAT (now in Secrets Manager) | `contents:read` on plugin repos | Read of plugin source; **already read-only**, ambient-IAM-fetched, no GitHub-held-in-CI copy |
| E6 | **GitHub → AWS**: job's AWS access | CodeBuild instance **IAM role** (in-account) | Scoped role (Bedrock, one Secrets Manager ARN) | In-account, no GitHub-held AWS credential exists — **already ideal** |

Two edges are already where we want them: **E4** (per-job token) and **E6** (the job runs
*inside* AWS with an instance role, so there is no long-lived AWS credential stored in
GitHub at all — the thing OIDC exists to avoid, avoided structurally by the CodeBuild
model). **E5** is read-only and, since the source seam, ambient-IAM-resolved. The hardening
target is **E1–E3**: the App's write surface and the personal identity holding it.

## 3. What is — and is not — reducible to read-only (honest accounting)

The security posture says name what is deliberately left open rather than imply
completeness. So, plainly:

- **E1 (runner registration) is irreducibly a write.** Registering a self-hosted runner
  calls `POST /repos/{o}/{r}/actions/runners/registration-token`, which requires
  `Administration` write. A just-in-time / ephemeral runner still needs that token. There
  is no read-only path to a self-hosted runner. Registering at the **org** level instead
  (`/orgs/{org}/actions/runners/...`) trades repo-admin for *org*-admin — a *wider* blast
  radius, not narrower — so repo-scoped registration stays preferable; runner **groups**
  can bound which repos an org runner serves if we ever go org-level.
- **E2 (webhook) is irreducibly a write** (`Repository hooks:write`) — the runner is
  triggered by a webhook the App must create.
- **These two writes are the price of AWS-native CI.** The alternative — GitHub-hosted
  runners — needs *no* CodeConnections App and *no* GitHub write at all, but forfeits the
  in-account IAM that is the entire reason to run CI in AWS (native Bedrock / `aws_core`
  testing). So the write surface is not a mistake to fix; it is a **deliberate cost** to
  *contain*. Hardening isolates and scopes it; it does not delete it.
- **E3 (unused breadth) cannot be trimmed per-permission** — a GitHub App declares a fixed
  permission manifest; the AWS Connector is a single shared App serving CodeBuild-source
  builds and CodePipeline too, so it requests `Contents` / `Commit statuses` /
  `Pull requests` that our runner use never exercises. The only knob is *which repos* the
  installation covers. So the mitigation for E3 is **repo scoping + identity isolation**,
  not manifest trimming.
- **E5 can be made *more* read-only-shaped** — a long-lived PAT (even fine-grained,
  `contents:read`) is a standing bearer credential. A **GitHub App installation token**
  (§4, Phase 3) is short-lived (~1h), minted per-run, scoped to selected repos + exactly
  `contents:read` — strictly better. That is the one place "more read-only" is available on
  a flow that is already read-only.

**Bottom line:** E4/E5/E6 are read-only or ephemeral already; E1/E2 are irreducible
writes; the whole game is *whose identity holds E1–E3 and how tightly it is scoped*.

## 4. The hardened target state (Phase 4 end-state)

- **A GitHub Organization owns the CI repos.** `tap` (and the evicted plugin repos) live
  under an org, not a personal namespace. This is the inflection the sibling enterprise-CI
  note already flags as needed for **branch protection + required status checks** — which
  is what turns the `product-lines` lane into an *enforced* gate, not just a runnable one.
- **A machine (bot) account, `tap-ci-bot`, is the CI identity.** A login-less GitHub user,
  an org member via a **scoped team** granting access to *only* the CI repos. The
  CodeConnections connection is authorized **as the bot**, so E1–E3's `Administration` /
  `hooks` writes are held by a disposable identity whose entire reach is the CI repos — the
  personal owner account is off the machine trust path entirely.
- **The write App is installed on the bot, scoped to selected repos.** The AWS Connector
  App installation covers only the CI repos; its unavoidable manifest breadth (E3) is
  bounded by that repo selection and by being held by the bot.
- **The read-only plugin pull is a short-lived App installation token.** E5 graduates from
  a Secrets-Manager PAT to a first-party GitHub App (owned by the org) whose private key is
  the only long-lived secret, held in Secrets Manager and read by ambient IAM; the lane
  mints a ~1h `contents:read` installation token per run. (If the App is judged not worth
  the key-management, a fine-grained `contents:read` PAT owned by the *bot* in Secrets
  Manager is the acceptable floor — still off the personal account.)
- **Everything is attributable and revocable.** Org audit log streams (optionally to AWS),
  every edge is a named identity scoped to named repos, and killing CI access is one action
  (suspend the bot / revoke the installation), not a Terraform hunt.

## 5. The migration ladder — phased, with actions

Each phase stands alone and buys real hardening; do them in order but stop wherever the
risk/effort trade flattens for the current stage of the company.

### Phase 0 — baseline *(superseded 2026-08-08: the org transfer happened — the App now
sits on `unified-systems-com`, still scoped to `tap` only, authorized by George rather
than a machine identity; E1–E3 now sit on the org via a human authorization, so the
remaining gap is the `tap-ci-bot` graduation, not the org move)*
Personal `notgeorge`; AWS Connector App with `Administration`+`hooks` write on `tap`;
plugin-pull credential in Secrets Manager, read-only (E5 done). **Named open risk:**
E1–E3 write surface sits on the personal identity.

### Phase 1 — scope & read-only-ify what needs no org (cheap, do now)
- Confirm the App installation is **selected-repos = {`tap`}**, not all-repos.
- Confirm `github-plugins-ro` in Secrets Manager is a **fine-grained** PAT scoped to
  `contents:read` on *only* the plugin repos (not a classic all-scope PAT). *(The seam that
  fetches it is already built and read-only; this is about the token's own scope.)*
- Add a **budget alarm** and **CloudTrail** review on the CodeBuild role's
  `secretsmanager:GetSecretValue` (detective control on E5/E6).
- **Buys:** least-privilege on the read-only flows; no org needed. **Cost:** an afternoon.

### Phase 2 — create the GitHub Organization
- Create the org; **transfer** `tap` (and evicted plugin repos) into it.
- Turn on org **branch protection / rulesets**, **secret scanning + push protection**,
  and (optionally) **audit-log streaming** to an S3/CloudWatch sink.
- Re-point the `origin` remotes and any `notgeorge/tap` references (Terraform
  `github_owner`, workflow `runs-on` labels are unaffected; the CodeConnections connection
  will need re-authorization against the org — see Phase 3).
- **Buys:** the substrate for required checks + bot scoping; the trust-boundary inflection.
  **Cost:** a focused migration; forces the promote→PR-gate redesign (its own project —
  see the enterprise-CI note).

### Phase 3 — introduce the machine bot & re-home the writes
- Create `tap-ci-bot` (login-less), add as an org member via a **team** granting *only* the
  CI repos.
- **Re-authorize the CodeConnections connection as the bot** (Developer Tools → Connections
  → the bot completes the GitHub App install on the org, selected-repos = CI repos). The
  `Administration`/`hooks` writes (E1–E3) now belong to the bot.
- Migrate E5 to a **first-party org GitHub App** minting a per-run `contents:read`
  installation token (App private key in Secrets Manager, read by ambient IAM), OR — the
  acceptable floor — reissue `github-plugins-ro` as a fine-grained PAT owned by the **bot**.
- Remove the App installation and any PAT from the **personal** account.
- **Buys:** the personal identity leaves the machine trust path; blast radius of a CI
  compromise collapses to a scoped bot. **Cost:** the interactive App re-auth + a token-mint
  step in the lane.

### Phase 4 — enforce & attribute
- Make the `product-lines` lane a **required status check** on the protected default branch
  (the promote gate becomes a real gate; `req-dev-validation-product-line-lanes-6`).
- Split identities if warranted (fine-grained caps discipline): a **separate bot or App per
  trust flow** — one for runner registration (write), one for plugin pull (read) — so no
  single credential spans read+write.
- Wire org audit-log + CloudTrail into one review surface; document the one-action
  revocation runbook.
- **Buys:** enforcement + full attribution + read/write identity separation. **Cost:**
  incremental; largely policy + a second bot/App.

## 6. Decisions to settle before executing

- **Org name & timing.** The org is also wanted for company formation / branch protection;
  align this migration with that moment rather than doing it twice. What is the org slug,
  and does `tap` transfer or get recreated?
- **Repo transfer vs. collaborator.** Transferring `tap` into the org (clean) vs. adding the
  bot as an admin collaborator on the personal repo (cosmetic isolation — the personal
  account still owns it). The doc assumes transfer; confirm.
- **App vs. fine-grained PAT for E5.** A first-party GitHub App gives short-lived tokens but
  adds one long-lived secret (the App private key) and App-management overhead. A bot-owned
  fine-grained `contents:read` PAT is simpler but is a standing bearer token. Which floor?
- **One bot vs. per-flow bots/Apps.** Fine-grained-capability doctrine leans toward
  separating the write (runner registration) identity from the read (plugin pull) identity.
  Worth the extra management now, or a Phase-4 refinement?
- **Runner registration scope.** Keep repo-scoped registration (narrower blast radius) vs.
  org-level runners with runner groups (fewer connections, wider admin). Default: repo-scoped.
- **Does the CodeConnections App even support org re-auth cleanly**, or does moving to the
  org mean a fresh connection + Terraform `codeconnection_arn` swap? (Likely a fresh
  connection; plan for the one interactive re-auth.)

## 7. Prior art / references

- **GitHub machine accounts** — a login-less user representing automation; ToS-permitted,
  scoped via org team membership. The standard identity-isolation primitive.
- **GitHub fine-grained PATs** — per-repo, per-permission, expiring; the read-only floor for
  E5 (`contents:read` only).
- **GitHub App installation tokens** — short-lived (~1h), minted from an App private key +
  installation id, scoped to selected repos + exact permissions; the read-only *ceiling* for
  E5. GitHub's own recommended pattern over long-lived PATs for automation.
- **GitHub OIDC → cloud role assumption** — the keyless GitHub→cloud pattern; **not needed
  here** because the CodeBuild model runs the job *inside* AWS with an instance role (E6),
  structurally avoiding a GitHub-held AWS credential. Relevant only if CI ever moves to
  GitHub-hosted runners.
- **AWS CodeConnections security model** — the AWS Connector for GitHub is a shared GitHub
  App AWS operates; the connection's authorizing identity and the App's selected-repos are
  the two scoping levers (E1–E3).
- **Least-privilege self-hosted runners** — ephemeral / just-in-time runners minimize a
  compromised-runner window but do not reduce the `Administration:write` needed to register
  them; repo-scoped beats org-scoped for blast radius.
- **Branch protection / required status checks / rulesets** — org-level enforcement that
  turns a runnable lane into a required gate (Phase 4).

## 8. Pointers

- **The connection this hardens:** [ci/terraform/codebuild-runners/README.md](../../ci/terraform/codebuild-runners/README.md)
  (the App auth, the one interactive install step)
- **The strategy + the machine-account graduation note it deepens:** [doc-dev-validation-ci-runner-strategy.md](doc-dev-validation-ci-runner-strategy.md)
- **The read-only value half already built:** `spec-tap-plugin-dependency-resolution.md`
  `req-tap-plugin-depres-sources` (the secret-source seam; E5's value now in Secrets Manager)
- **The standing discipline it serves:** [spec-security-posture.md](../../specs/spec-security-posture.md)
  (cheap foundational edges; name the risks left open)
- **The required-check inflection:** [doc-dev-validation-enterprise-ci-strategy.md](doc-dev-validation-enterprise-ci-strategy.md)
  (org migration for branch protection + required checks) and `req-dev-validation-product-line-lanes-6`
