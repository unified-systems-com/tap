# Fleet Bot Automation — Discovery and Credentials

## Philosophy

`org-bots` runs two fleet-wide automations against every TAP plugin and product repository:
Renovate (dependency updates) and release-please (version bumps and releases). Both need an
answer to the same two questions, and this spec exists because the current answer to each is
the thing most likely to rot silently: **which repositories does this touch**, and **what can
go wrong if the credential behind it leaks**.

**A hand-maintained list is a promise nobody is on the hook to keep.** Today, Renovate reads a
hardcoded `FLEET` array in `org-bots/renovate/global.js`; release-please reads a hardcoded
`RELEASE_REPOS` string in its own workflow. Neither is derived from anything — a new plugin
repo gets no coverage from either tool unless a human remembers to add its name to a file in a
*different* repository. This is the same failure shape `spec-tap-serving.md` names for `DEBUG`
and `spec-tap-plugin-dependency-resolution.md` names for hand-authored install lists: a fact
about the fleet, restated by hand, in a place nothing checks against the fleet's actual state.

**A credential's blast radius is what decides whether sharing it is safe — not how it's stored.**
The two tools this spec covers sit on opposite sides of that line, and conflating them is the
mistake this spec exists to prevent, stated because an earlier draft of the release-please design
made exactly it: a credential that holds **no role on any repository** (the org-bots fork bot)
is safe to reuse across the whole fleet, because forking a repo and opening a PR from that fork
needs no write grant on the target at all — the same credential used by one repo or by twenty
carries an identical, already-bounded worst case. A credential that holds a **real, org-wide
installed role** (a GitHub App's private key, `contents: write` + `pull-requests: write`
everywhere it's installed) is the opposite: copying it into N repositories' own secret stores
turns N places into a leak surface for one org-wide-privileged key. The fix for "no hardcoded
list" must never be "give every repo its own copy of a powerful credential" — that trades one
problem for a worse one.

**Discovery should be a property the repository declares about itself, not a separate list.**
Both fixes below converge on this: a repository is in scope for automation because of something
visible ON that repository (a topic), never because a different repository's config file happens
to still mention its name.

**"Safe to share" and "safe to distribute" are not the same claim, and an earlier draft of this
spec conflated them too.** A no-role fork-mode credential is safe to *use* across the whole
fleet — its blast radius is capped regardless of how many repositories rely on it. It does not
follow that it is safe to *distribute* as a broadly-visible secret: GitHub cannot scope an
organization secret by topic (visibility is only `all` / `private` / an explicit repository
list), so making it an org secret either recreates a hand-maintained list (defeating
`req-cicd-fleet-bot-discovery`'s own point) or hands the credential to every workflow in every
repository that secret's visibility reaches — not only the one workflow meant to use it. Both
fixes below therefore keep the credential exactly where it already lives — a single environment
in `org-bots`, never copied anywhere — and have `org-bots` act *on behalf of* each discovered
repository rather than handing the repository the means to act for itself.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | No Hand-Maintained Fleet List | Neither tool's scope is a list a human must remember to update when a repository is created. |
| 2. | Credential Blast Radius And Exposure Are Both Named | Every fleet-shared credential holds no role anywhere (bounding its capability) AND is never distributed beyond the single place it already lives (bounding its exposure); neither bound is assumed to follow from the other. |
| 3. | Automation Stops At "A PR Exists" | Neither tool merges, tags, or publishes anything itself; a human reviews and merges every change, and cuts every release, exactly as today. |
| 4. | Release Cutting Stays Human-Attested | `scripts/cut-release.sh` (Phase 2: tag + publish) is unchanged by this spec — this is entirely a Phase 1 (PR creation) and discovery redesign. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-cicd-fleet-bot-discovery | [Renovate Discovers By Topic](#renovate-discovers-by-topic) | Proposed | Replaces `renovate/global.js`'s hardcoded `FLEET` array |
| req-cicd-fleet-bot-discovery-core-pinned | [Core Stays Explicitly Pinned](#core-stays-explicitly-pinned) | Proposed | `tap` is a singleton, not part of a growing list — no drift risk in naming it directly |
| req-cicd-fleet-bot-release-phase1 | [Release-PR Creation Stays Centralized, Discovers By The Same Topic](#release-pr-creation-stays-centralized-discovers-by-the-same-topic) | Proposed | Same `release-please release-pr --fork` mechanism, same credential, already run today from `org-bots` — only `RELEASE_REPOS` is replaced, by the identical topic discovery `req-cicd-fleet-bot-discovery` uses for Renovate |
| req-cicd-fleet-bot-release-phase2 | [Release Cutting Stays Manual And Unchanged](#release-cutting-stays-manual-and-unchanged) | Proposed | `scripts/cut-release.sh` is untouched by this spec |
| req-cicd-fleet-bot-no-app-key-distribution | [An Org-Wide App Key Is Never Copied Per-Repo](#an-org-wide-app-key-is-never-copied-per-repo) | Proposed | Named because an earlier draft of this design got it wrong |
| req-cicd-fleet-bot-shared-credential-bound | [A Fleet-Shared Credential Holds No Role Anywhere](#a-fleet-shared-credential-holds-no-role-anywhere) | Proposed | The general rule `req-cicd-fleet-bot-no-app-key-distribution` is the specific instance of |

### Renovate Discovers By Topic

----
RID: `req-cicd-fleet-bot-discovery`

Status: `Proposed`

Renovate's self-hosted run (`org-bots/.github/workflows/renovate.yml`, `renovate/global.js`)
reads a hardcoded `FLEET` array of ~24 repository names. Replace it with Renovate's own native
`autodiscover: true` + `autodiscoverTopics: ["tap-plugin"]`, which processes every repository
carrying that GitHub topic and nothing else.

**Why a topic filter, not blanket `autodiscover`.** Renovate's fork-mode credential holds no
role on any repository — it forks the target and opens a PR from there, so it needs no write
grant on anything it touches ([`req-cicd-fleet-bot-shared-credential-bound`](#a-fleet-shared-credential-holds-no-role-anywhere)).
That already bounds the worst case of a mis-scoped discovery. `autodiscoverTopics` narrows scope
further than "everything the token can see" for a separate reason: hygiene, not safety — a
repository that was never meant to be part of the fleet (an archived experiment, a private
customer repo with no plugin in it) should not get dependency-bump PRs it did not ask for. The
topic is a repository declaring "I am a TAP plugin" about itself, which is the same bar setting
`FLEET` in `global.js` today requires (write access to that config), just moved onto the
repository the decision is actually about.

**Setting the topic is a one-time bulk action for the current fleet**, and folds into
`new-plugin`'s scaffold going forward (`Issue# 203 - tap`, "new-plugin emits the baseline by
default") so a plugin repository's 14th sibling self-registers at creation rather than needing a
second step anyone can forget.

**The `only` workflow-dispatch input** (a pilot run narrowed to one named repository) needs a
small adjustment: with discovery on, `only=<name>` means "run against exactly this repository,
bypassing topic discovery for this one dispatch" rather than filtering a pre-built array.

**A GitHub topic is a global, public string — nothing about it is scoped to this organization on
its own.** Any repository anywhere on GitHub could carry a `tap-plugin` topic for reasons that
have nothing to do with this fleet, and a discovery query that matches on the topic alone would
include it. Discovery must therefore be qualified by ownership, not topic alone — Renovate's own
`repositories`/platform configuration already operates within a token's accessible scope, but
that scope boundary must be an explicit, checked fact in this requirement's own terms, not an
inherited side effect of how the token happens to be configured today.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-fleet-bot-discovery-1 | Topic Replaces The Array | Proposed | `renovate/global.js` contains no hardcoded list of plugin/product repository names; scope comes from `autodiscoverTopics`. | |
| req-cicd-fleet-bot-discovery-2 | New Plugins Self-Register | Proposed | `new-plugin`'s scaffold applies the topic to a repository it creates, with no separate registration step. | Pairs with `Issue# 203 - tap` |
| req-cicd-fleet-bot-discovery-3 | Pilot Dispatch Still Narrows | Proposed | The `only` workflow-dispatch input still restricts a manual run to one named repository, independent of topic discovery. | |
| req-cicd-fleet-bot-discovery-4 | Discovery Is Owner-Qualified, Not Topic-Alone | Proposed | The topic match is explicitly restricted to `unified-systems-com`-owned repositories (an `org:` qualifier on the query, or the equivalent scoping in Renovate's own configuration), verified as a stated requirement rather than assumed from the token's incidental reach. | The topic string alone is global and public; anything outside this org sharing it must never be discovered |

### Core Stays Explicitly Pinned

----
RID: `req-cicd-fleet-bot-discovery-core-pinned`

Status: `Proposed`

`tap` core keeps its own explicit entry in `renovate/global.js` (`SELF_CONFIGURED`) rather than
being topic-discovered. It is a singleton with its own concurrency limits and its own
`renovate.json5`, not one member of a growing fleet — the drift `req-cicd-fleet-bot-discovery`
exists to close is specifically about a list that grows and is forgotten; a list of one repository
that never changes carries none of that risk, and topic-tagging core alongside every plugin would
blur the distinction between "the host" and "the fleet" for no safety gain.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-fleet-bot-discovery-core-pinned-1 | Core Is Named, Not Discovered | Proposed | `tap`'s own Renovate configuration is an explicit `SELF_CONFIGURED` entry, never gated on a topic. | |

### Release-PR Creation Stays Centralized, Discovers By The Same Topic

----
RID: `req-cicd-fleet-bot-release-phase1`

Status: `Proposed`

**Revision note.** An earlier draft of this requirement moved Phase 1 into a reusable workflow
each plugin repository calls, with the fork-bot credential held as an org-level secret every
caller reads directly. That design does not hold up: GitHub cannot scope an organization secret
by topic, so it either recreates a hand-maintained repository list (as a `selected`-visibility
secret's grant list) or exposes the credential to every workflow in every repository the secret
reaches (as an `all`-visibility secret), not only the intended caller. This section replaces it
with the centralized design below, which needs no organization secret at all.

Release-please's PR-creation stage (`release-please release-pr --fork`) already runs fork-mode,
from `org-bots`, using the same `FORK_BOT_TOKEN` Renovate already uses — this does not change.
What changes is only how `org-bots` decides *which repositories* to run it against: replace the
hardcoded `RELEASE_REPOS` string with the identical topic discovery
[`req-cicd-fleet-bot-discovery`](#renovate-discovers-by-topic) already uses for Renovate (the
same `tap-plugin` topic, queried via the GitHub API from within `org-bots`, then iterated). One
discovery mechanism serves both tools; a repository tagged once gets both Renovate and
release-please coverage, with nothing new for `new-plugin` to scaffold beyond the topic itself —
unlike the reverted per-repo design, **this shape needs no reusable per-repo workflow file at
all**, so there is no separate enrollment gap to close for release-please the way there is for
Renovate: coverage is inherited from the same topic tag, automatically.

**The credential is unchanged from what `org-bots` already holds today** — see
[`req-cicd-fleet-bot-no-app-key-distribution`](#an-org-wide-app-key-is-never-copied-per-repo) for
why a GitHub App's private key was the wrong direction, and
[`req-cicd-fleet-bot-shared-credential-bound`](#a-fleet-shared-credential-holds-no-role-anywhere)
for why this credential is safe to *use* fleet-wide precisely because it is never *distributed*
anywhere — it stays in the single `org-bots` environment it already lives in, and `org-bots` acts
on each discovered repository's behalf rather than handing the repository a means to act for
itself.

**The resulting release PR is fork-authored, so it triggers CI the same way any external
contributor's PR does** — this is a real and separately-solved problem, not assumed: a PR pushed
with a repository's own ambient `GITHUB_TOKEN` does **not** trigger new workflow runs (GitHub's
own rule, and the reason `tap`'s own `release-please.yml` uses a GitHub App token instead of
`GITHUB_TOKEN` for its own release PRs). Fork-authored PRs do not have this problem — they trigger
checks normally — and the "Approve and run" gate a fork PR waits behind is a manual step: George
runs `scripts/approve_bot_runs.py` himself, when he chooses (`Q51`, ruled) — there is no
automated approver and no Actions-write App in this loop at all, which narrows the exposure
further than "the script could run unattended" would.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-fleet-bot-release-phase1-1 | Same Mechanism, Same Credential | Proposed | `release-please release-pr --fork` continues to run from `org-bots`, authenticated exactly as it is today — this requirement changes discovery only. | |
| req-cicd-fleet-bot-release-phase1-2 | No Hardcoded RELEASE_REPOS | Proposed | `RELEASE_REPOS` is replaced by querying the same `tap-plugin` topic `req-cicd-fleet-bot-discovery` uses, under the same `unified-systems-com` owner qualifier (`req-cicd-fleet-bot-discovery-4`) — not the topic alone. | Inherits the org-scoping requirement, doesn't restate a separate one |
| req-cicd-fleet-bot-release-phase1-3 | Credential Never Leaves `org-bots` | Proposed | The fork-bot credential is not made an organization secret, not copied to any repository, and not passed to any per-repo workflow — it is read only inside `org-bots`' own run. | Supersedes the reverted org-secret design |
| req-cicd-fleet-bot-release-phase1-4 | CI Triggers On The Resulting PR | Proposed | Because the PR is fork-authored, its checks run normally (subject to the existing, manual approve-and-run step) — a `GITHUB_TOKEN`-authored PR, which would not trigger checks at all, is never used for this stage. | Verified against `tap`'s own `release-please.yml`, which documents this exact `GITHUB_TOKEN` limitation |
| req-cicd-fleet-bot-release-phase1-5 | One Topic Covers Both Tools | Proposed | A repository tagged for Renovate discovery is, by the same tag, in scope for release-please discovery — no second registration step, no per-repo workflow file to forget. | Replaces the reverted `new-plugin`-scaffolds-a-caller-workflow approach |

### Release Cutting Stays Manual And Unchanged

----
RID: `req-cicd-fleet-bot-release-phase2`

Status: `Proposed`

`scripts/cut-release.sh` — tagging the merged release PR and publishing the GitHub Release — is
untouched by this spec. It still runs from a maintainer's machine, with their own `gh auth token`,
after they have merged the release PR by hand. Nothing in `req-cicd-fleet-bot-release-phase1`
grants any fleet-shared credential the `contents: write` this stage needs; that boundary is
deliberate; see [`req-cicd-fleet-bot-shared-credential-bound`](#a-fleet-shared-credential-holds-no-role-anywhere).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-fleet-bot-release-phase2-1 | Cut-Release Is Unchanged | Proposed | `scripts/cut-release.sh`'s behavior, invocation, and credential model are identical before and after this spec lands. | |

### An Org-Wide App Key Is Never Copied Per-Repo

----
RID: `req-cicd-fleet-bot-no-app-key-distribution`

Status: `Proposed`

`tap` core's own `.github/workflows/release-please.yml` mints an installation token from the
`tap-release-please` GitHub App, using a private key held as a `tap`-repo-level secret. That
works for `tap` because `tap` holds its own copy of a credential it alone trusts itself with. It
does **not** generalize to "give every plugin repository the same pattern": the App is installed
**org-wide** (`repository_selection: all`), so its private key can mint a token for *any*
repository in the org, not just the one holding it. Copying that key into twenty-plus plugin
repositories' own secret stores would turn each one into an independent leak surface for a single
credential with organization-wide write reach — a real regression, not a neutral architectural
choice.

**This requirement is named because an earlier draft of `req-cicd-fleet-bot-release-phase1` got
it wrong** — it proposed exactly that per-repo App-token pattern before the private key's actual
scope (`tap`-repo-level secret, not org-level) was checked. `req-cicd-fleet-bot-release-phase1`'s
fork-mode design is the fix; this requirement exists so the mistake is not repeated by a later
change that reaches for "just mint an App token per repo" without re-deriving why that was
rejected.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-fleet-bot-no-app-key-distribution-1 | No Per-Repo App Key Copies, Enforced | Proposed | A periodic check scans plugin repositories' secret names via the API and fails loudly if an org-wide-installed App's private-key secret name appears in any of them, rather than this staying an unaudited assumption. | Same "enforced, not just currently true" bar as `req-cicd-fleet-bot-shared-credential-bound-2` |

### A Fleet-Shared Credential Holds No Role Anywhere

----
RID: `req-cicd-fleet-bot-shared-credential-bound`

Status: `Proposed`

The general rule `req-cicd-fleet-bot-no-app-key-distribution` is one instance of: any credential
used identically across many repositories in this fleet must hold **no role on any of them** —
its only capability is to fork a repository and open a PR from that fork, which needs no write
grant on the target at all. This is what makes the fork-bot credential (Renovate, and now
release-please's Phase 1) safe to *use* fleet-wide: its blast radius is identical whether one
repository is discovered or twenty, because forking plus opening a PR is all it can ever do, and
a human still reviews and merges every PR it produces.

**"No role anywhere" bounds the credential's capability; it does not by itself bound its
*exposure*, and the two were conflated in an earlier draft.** GitHub cannot scope an organization
secret by topic, so making a no-role credential broadly visible as an org secret still means
every workflow in every repository that visibility reaches can read it — a wider exposure than
the credential's *capability* alone would suggest is necessary. `req-cicd-fleet-bot-release-phase1-3`
closes that the direct way: the credential is never made a secret any repository's own workflow
can read at all. It stays inside `org-bots`, which is what "no role anywhere" is describing —
not "safe to hand out broadly," but "safe for `org-bots` to keep using on the fleet's behalf."

A credential that holds a *real* role on a repository — write access, an installed App with
`contents: write` — is the opposite case, and this spec's decisions never share one of those
across repositories. Where a stage genuinely needs write access (`scripts/cut-release.sh`), it
stays scoped to exactly one operator's own credential, invoked by hand, never distributed.

**"No role" is not the whole blast-radius model, and stating it that way understates the
credential.** `scripts/approve_bot_runs.py`
recognizes this exact identity by numeric id and auto-approves its fork PRs' workflow runs,
fleet-wide. Possessing the credential therefore grants an *indirect* capability beyond "fork and
open a PR": it lets whoever holds it pass as the one identity that skips the human
"Approve and run" click every other outside contributor faces. That is a real capability, not
nothing, and the credential's safety rests on what that capability can reach being small — never
on the capability not existing.

**Worked check, done directly rather than assumed** (feeds `req-cicd-fleet-bot-release-phase1-4`):
what a forged, auto-approved run can reach is bounded by three separate facts, each verified
against this fleet rather than assumed generically — the resulting workflow run holds no secrets
(GitHub does not forward repository/organization secrets to a `pull_request`-triggered run
originating from a fork, and no workflow in this fleet uses `pull_request_target`, the pattern
that would defeat that protection) and a read-only `GITHUB_TOKEN` (the organization's own
default). The worst case is unattributed, sandboxed compute — not write access, not secret
exposure, not a path to merging anything. **All three facts are load-bearing simultaneously**: if
any one stops holding — a workflow starts using `pull_request_target`, the org default flips to
write, or a secret gets passed into a fork-triggered job — the credential's safety argument no
longer holds, which is exactly why `-2` below is an enforced guard and not a documented
assumption.

**All three of the facts the worked check above relies on must be enforced, not just one of
them** — naming three load-bearing facts and gating only one lets an implementation pass every
stated criterion while quietly losing either of the other two. Each of the three needs its own
guard, and each guard needs to check more than its narrowest reading — see `-2`, `-4`, and `-5`
below, and the fourth invariant this section was missing entirely (`-6`): that "no role anywhere"
is itself audited, not assumed to hold just because nobody granted a role on purpose.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-fleet-bot-shared-credential-bound-1 | No Shared Credential Holds A Role | Proposed | Every credential used identically across more than one repository in the fleet holds no write role on any of them. | Enforced by `-6`, not merely stated |
| req-cicd-fleet-bot-shared-credential-bound-2 | `pull_request_target` Is Fleet-Guarded, Not Just Absent | Proposed | A CI guard fails closed if any fleet workflow adds `pull_request_target`, rather than the fleet merely happening not to use it today. | One of three facts the worked check depends on — see `-4`/`-5` for the other two |
| req-cicd-fleet-bot-shared-credential-bound-3 | Auto-Approval Is Named As A Capability | Proposed | The credential's threat model documents "bypasses the human Approve-and-run click for this identity" as a real capability the credential grants, not an absence of one. | This ACID; no code changes it, it exists so the model is stated honestly |
| req-cicd-fleet-bot-shared-credential-bound-4 | Effective Token Permission Is Fleet-Guarded, Not Just The Org Default | Proposed | A guard fails closed if the *effective* permission a fork-triggered job runs with is ever write — covering the organization default, any explicit job- or workflow-level `permissions:` block that widens it, and GitHub's separate "workflows can approve pull requests" / write-back setting for fork PRs — not the org default alone. | The second of the three load-bearing facts; a job-level override or the fork write-token setting can grant write even when the org default stays read-only |
| req-cicd-fleet-bot-shared-credential-bound-5 | No Credential Path Into Fork-Triggered Jobs Is Fleet-Guarded | Proposed | A guard fails closed if any fleet workflow's `pull_request`-triggered job gains a credential through *any* path — a direct `secrets.*` reference, a reusable-workflow call that inherits or is passed secrets, `id-token: write` (OIDC-minted cloud credentials, which exist outside GitHub's own secret-withholding guarantee), or a self-hosted runner (which does not carry GitHub-hosted runners' isolation guarantees at all). `pull_request_target` and direct `secrets.*` references are the sharpest versions of this failure, not the only ones. | The third of the three load-bearing facts |
| req-cicd-fleet-bot-shared-credential-bound-6 | The Fork Bot's Own Standing Is Audited, Not Assumed | Proposed | A periodic check queries the GitHub API for the fork bot account's (id 334543231) actual organization membership, base permission level, collaborator grants, and team memberships across the fleet, and fails loudly if any of them is ever non-empty. "No role anywhere" is a claim about the account's current standing, and standing can drift (a mistaken invite, a team add) independently of anything this spec's other guards would catch — `approve_bot_runs.py` does not check this today, and neither did any earlier draft of this section. | The fourth invariant, distinct from `-2`/`-4`/`-5`: those bound what a *forged run* can reach; this bounds what the *account itself* can reach if its standing ever silently changes |

## Non-Goals

- **Redesigning `scripts/approve_bot_runs.py`'s allowlist or trust model.** It already makes its
  decision from structured API fields only and already excludes new-workflow-file additions;
  this spec does not change it, only names the bound on what an auto-approved run can reach
  (`req-cicd-fleet-bot-shared-credential-bound`).
- **Migrating `tap` core's own release-please mechanism.** `tap` already runs the App-token
  pattern for itself and that continues to work; whether to migrate core onto the same shape as
  the plugin fleet is a separate decision, made explicitly, not swept in here.
- **Deciding the exact topic string, or the shape of the small script/workflow inside `org-bots`
  that queries the topic and iterates `release-please release-pr --fork` over the result.** Those
  are implementation details for the PR that builds this, not spec-level facts.

## Related

`Issue# 200 - tap` (the plugin-fleet housekeeping epic), `Issue# 854 - tap` (release-please,
tracked ahead of this spec landing), `Issue# 856 - tap` (Renovate discovery, same). This spec is
the canonical write-up both issues point back to.
