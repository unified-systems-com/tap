# Fleet Bot Automation — Discovery and Credentials

## Philosophy

`org-bots` runs two fleet-wide automations against `tap` and every TAP plugin and product
repository: Renovate (dependency updates, including fixes for known vulnerabilities) and
release-please (version bumps and releases). Both need an answer to the same two questions:
**which repositories does this touch**, and **what can go wrong if the credential behind it
leaks**.

**A hand-maintained list is a promise nobody is on the hook to keep.** The first version of
`org-bots` read a hardcoded `FLEET` array in `renovate/global.js` and a hardcoded `RELEASE_REPOS`
string in the release-please workflow. Neither was derived from anything, so a new plugin
repository got no coverage from either tool unless a human remembered to add its name to a file
in a *different* repository. This is the same failure shape `spec-tap-serving.md` names for
`DEBUG` and `spec-tap-plugin-dependency-resolution.md` names for hand-authored install lists: a
fact about the fleet, restated by hand, in a place nothing checks against the fleet's actual
state.

**Discovery is a property the repository declares about itself, not a separate list.** A
repository is in scope for automation because of something visible ON that repository (a topic),
never because a different repository's config file happens to still mention its name.

**The standard configuration, run plainly.** Each bot is one scheduled job that covers the whole
fleet in one run, as an org-owned GitHub App. That is how `org-bots` first ran (2026-09-25), and
it is the configuration these tools are documented and tested in by their own projects. Between
2026-09-27 and 2026-11-05 the fleet tried a different design, a separate outside account with no
role on any repository that opened every PR from its own forks, so that no org App needed write.
GitHub's anti-abuse flagged that account on its first fleet-wide run and later suspended it, and
the slicing, rotation and pacing added to protect it made both bots slow and fragile: Renovate's
schedule stayed off for two weeks, and a rotation that advanced only on success left scheduled
release-please stuck on one slice for days. The fork design is retired (George, 2026-11-19). The
paragraphs that argued for it are gone from this spec; `git log` keeps them.

**A write credential is bounded by where it lives and what each run asks for, not by having no
role.** The Apps hold real write access. What keeps that acceptable is stated as requirements
below rather than assumed: each App's private key exists in exactly one place; every run mints a
short-lived token that names only that run's repositories and only the permissions the job needs;
and neither bot merges anything, so a human reads every change before it reaches a default
branch.

**A powerful credential is never copied to where it is used.** The fix for "no hardcoded list"
must never be "give every repository its own copy of the key". An App installed on every
repository can mint a token for any of them, so a copy of its key in N repositories' secret
stores is N leak surfaces for one org-wide credential. `org-bots` acts *on behalf of* each
discovered repository; no repository is handed the means to act for itself.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | No Hand-Maintained Fleet List | Neither tool's scope is a list a human must remember to update when a repository is created. |
| 2. | Both Bots Run Unattended Over The Whole Fleet | A scheduled run of each bot covers `tap` and every discovered repository, with no slicing, no rotation and no hand dispatch needed to keep coverage current. |
| 3. | Credential Reach And Exposure Are Both Named | Each App's key lives in one place and is never distributed; each run's token names only that run's repositories and the permissions its job needs. Neither bound is assumed to follow from the other. |
| 4. | A Human Merges Every Change | Neither tool merges anything. A dependency update and a release PR each wait for a human; a release is tagged only after a human has merged its release PR. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-cicd-fleet-bot-discovery | [The Fleet Is Discovered By Topic](#the-fleet-is-discovered-by-topic) | Proposed | Replaces `renovate/global.js`'s hardcoded `FLEET` array |
| req-cicd-fleet-bot-discovery-core-pinned | [Core Stays Explicitly Pinned](#core-stays-explicitly-pinned) | Proposed | `tap` is a singleton, not part of a growing list — no drift risk in naming it directly |
| req-cicd-fleet-bot-release-phase1 | [Release PRs Are Opened Centrally, Over The Same Discovery](#release-prs-are-opened-centrally-over-the-same-discovery) | Proposed | `release-please release-pr` run from `org-bots` as the `tap-release-please` App, over the same topic discovery Renovate uses |
| req-cicd-fleet-bot-release-phase2 | [A Merged Release PR Is Tagged By The App](#a-merged-release-pr-is-tagged-by-the-app) | Proposed | Rewritten 2026-11-19: tagging moved from a maintainer's machine to the same hourly run; `scripts/cut-release.sh` stays as the hand fallback |
| req-cicd-fleet-bot-no-app-key-distribution | [App Keys Live Only In `org-bots`](#app-keys-live-only-in-org-bots) | Proposed | Rewritten 2026-11-19: the Apps hold write again; the key is still never copied |
| req-cicd-fleet-bot-shared-credential-bound | [A Run's Token Is Bounded By What The Run Asks For](#a-runs-token-is-bounded-by-what-the-run-asks-for) | Proposed | Rewritten 2026-11-19: replaces "a fleet-shared credential holds no role anywhere" |
| req-cicd-fleet-bot-paced | [The Bots Run Unpaced; Hand-Run Fleet Changes Are Paced](#the-bots-run-unpaced-hand-run-fleet-changes-are-paced) | Proposed | Added 2026-09-29 after GitHub flagged the fork bot; the bot half reversed 2026-11-19 |

### The Fleet Is Discovered By Topic

----
RID: `req-cicd-fleet-bot-discovery`

Status: `Proposed`

A deterministic step in `org-bots` (`scripts/discover_fleet.py`) lists
`GET /orgs/unified-systems-com/repos`, keeps each repository whose owner is `unified-systems-com`
and whose topics include `tap-plugin`, drops archived and disabled repositories, and hands the
result to each bot. Renovate receives it as an explicit `repositories` list in its global
configuration (`autodiscover` stays off). Every repository carrying that GitHub topic is
processed, and nothing else.

**Why not Renovate's own `autodiscover` + `autodiscoverTopics`.** On GitHub, Renovate
autodiscovers from `GET /installation/repositories` for an App token (`fetchRepositories`/`getRepos`
in `modules/platform/github/index.js`, read from the Renovate 44.115.10 image `org-bots` pins):
whatever the token can see. Each run's token is deliberately narrowed before Renovate starts
([`req-cicd-fleet-bot-shared-credential-bound`](#a-runs-token-is-bounded-by-what-the-run-asks-for)),
so what the token can see is a consequence of discovery, not a definition of the fleet, and
release-please has no autodiscovery at all. One discovery, done once from the org's own
repository list with a workflow's read-only `GITHUB_TOKEN`, serves both bots and scopes both
tokens. The search API is not used either: right after the topic was first applied its index
briefly returned 22 of the 24 tagged repositories, while the org repository list returned all 24.

**Discovery refuses rather than guesses.** No repository carrying the topic, a tagged repository
whose name is not a plain repository name, or `org-bots` itself carrying the topic each stop
discovery with an error — never an empty or partial run. `org-bots` is refused by name: the
repository that runs the automation is never one of its targets.

**Why a topic filter, not every repository in the organization.** The Apps are installed on
every repository so that a new plugin needs no installation step
([`req-cicd-fleet-bot-no-app-key-distribution`](#app-keys-live-only-in-org-bots)), which makes
the topic the only thing standing between "the App can reach it" and "the bots act on it". A
repository that was never meant to be part of the fleet (an archived experiment, the org's
website, a supply-chain repository that pins by hand) must not get dependency-bump PRs it did not
ask for, and must not be named in a write token. The topic is a repository declaring "I am a TAP
plugin" about itself, moved onto the repository the decision is actually about.

**Setting the topic** is part of `new-plugin`'s scaffold (`Issue# 203 - tap`, "new-plugin emits
the baseline by default"), so a new plugin repository self-registers at creation rather than
needing a second step anyone can forget.

**The `only` workflow-dispatch input** narrows a hand-dispatched run to one named repository,
and "bypasses the fleet run" must not mean "bypasses the owner qualifier too". `only=<name>`
means "run against exactly this repository" — but that repository must be `tap` or a discovered
one, checked the same way, and any other name is refused. `only` narrows *which* in-scope
repository runs; it must never be a second path into scope for a repository discovery itself
would exclude.

**A GitHub topic is a global, public string — nothing about it is scoped to this organization on
its own.** Any repository anywhere on GitHub could carry a `tap-plugin` topic for reasons that
have nothing to do with this fleet, and a discovery query that matches on the topic alone would
include it. Discovery must therefore be qualified by ownership, not topic alone — listing
`GET /orgs/unified-systems-com/repos` already confines the answer to this organization, but
that boundary must be an explicit, checked fact in this requirement's own terms (each entry's
owner compared with `unified-systems-com`), not an inherited side effect of which endpoint
happened to be called.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-fleet-bot-discovery-1 | Topic Replaces The Array | Proposed | `renovate/global.js` contains no hardcoded list of plugin/product repository names; scope comes from topic discovery (`org-bots/scripts/discover_fleet.py`), handed to Renovate as its `repositories` list. | Renovate's native autodiscovery reads what the token can see, which discovery itself decides; see the section text |
| req-cicd-fleet-bot-discovery-2 | New Plugins Self-Register | Proposed | `new-plugin`'s scaffold applies the topic to a repository it creates, with no separate registration step. | Pairs with `Issue# 203 - tap` |
| req-cicd-fleet-bot-discovery-3 | Dispatch Narrows, Never Widens Scope | Proposed | `only=<name>` restricts a manual run to one named repository, but that repository must be `tap` or pass the same `unified-systems-com`-ownership and `tap-plugin`-topic checks discovery itself applies — any other name is refused. | `only` narrows within scope; it is not a second, unqualified path into scope |
| req-cicd-fleet-bot-discovery-4 | Discovery Is Owner-Qualified, Not Topic-Alone | Proposed | The topic match is explicitly restricted to `unified-systems-com`-owned repositories (listing the organization's own repositories and checking each entry's owner), verified as a stated requirement rather than assumed from the token's incidental reach. | The topic string alone is global and public; anything outside this org sharing it must never be discovered |

### Core Stays Explicitly Pinned

----
RID: `req-cicd-fleet-bot-discovery-core-pinned`

Status: `Proposed`

`tap` core keeps its own explicit entry in `renovate/global.js` (`SELF_CONFIGURED`) rather than
being topic-discovered, and is named beside the discovered repositories for release-please the
same way. It is a singleton with its own `renovate.json5`, not one member of a growing fleet —
the drift `req-cicd-fleet-bot-discovery` exists to close is specifically about a list that grows
and is forgotten; a list of one repository that never changes carries none of that risk, and
topic-tagging core alongside every plugin would blur the distinction between "the host" and "the
fleet" for no safety gain. Named or discovered, `tap` is covered by the same scheduled run as
every other repository.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-fleet-bot-discovery-core-pinned-1 | Core Is Named, Not Discovered | Proposed | `tap`'s own Renovate configuration is an explicit `SELF_CONFIGURED` entry, never gated on a topic. | |

### Release PRs Are Opened Centrally, Over The Same Discovery

----
RID: `req-cicd-fleet-bot-release-phase1`

Status: `Proposed`

Release-please's PR-creation stage (`release-please release-pr`) runs from `org-bots`, hourly,
as the org-owned `tap-release-please` GitHub App, over the identical topic discovery
[`req-cicd-fleet-bot-discovery`](#the-fleet-is-discovered-by-topic) provides for Renovate (the
same `tap-plugin` topic, found by the same `org-bots/scripts/discover_fleet.py`, then iterated).
One discovery mechanism serves both tools; a repository tagged once gets both Renovate and
release-please coverage, with nothing for `new-plugin` to scaffold beyond the topic itself. There
is no reusable per-repository workflow file, so there is no separate enrollment gap to close for
release-please. A discovered repository that does not yet carry release-please's own
`release-please-config.json` and `.release-please-manifest.json` has nothing to release and is
skipped with a visible notice, not a failure; those two files are the release definition itself,
not a registration step. `tap` is named alongside the discovered repositories exactly as for
Renovate ([`req-cicd-fleet-bot-discovery-core-pinned`](#core-stays-explicitly-pinned)).

**One run covers every repository.** The run is not sliced, rotated or capped: a scheduled run
iterates `tap` and every discovered repository, and one repository failing does not stop the
others (the run still ends red and names it).

**Why a per-repository workflow was rejected, and stays rejected.** An earlier draft moved this
stage into a reusable workflow each plugin repository calls, with the credential held as an
org-level secret every caller reads directly. GitHub cannot scope an organization secret by
topic (visibility is only `all`, `private`, or an explicit repository list), so that design
either recreates a hand-maintained repository list or exposes the credential to every workflow
in every repository the secret reaches. The centralized design needs no organization secret at
all; see [`req-cicd-fleet-bot-no-app-key-distribution`](#app-keys-live-only-in-org-bots).

**The release PR is authored by the App, so the repository's own checks run on it.** A PR
pushed with a repository's ambient `GITHUB_TOKEN` does **not** trigger new workflow runs
(GitHub's own rule). A PR opened with an App installation token does, with no "Approve and run"
step, because its branch is in the target repository itself and its author is an account of
type `Bot`. A repository whose sign-off or issue-link check exempts bot authors must name the
App's bot user by id; the bot never adds a `Signed-off-by` trailer, because an automated system
does not certify the DCO.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-fleet-bot-release-phase1-1 | Same Mechanism, Same Credential | Retired | `release-please release-pr --fork` continues to run from `org-bots`, authenticated exactly as it is today — this requirement changes discovery only. | Reversed 2026-11-19: fork mode is retired; `-6` states the App mechanism |
| req-cicd-fleet-bot-release-phase1-2 | No Hardcoded RELEASE_REPOS | Proposed | The repositories release-please runs on come from the same `tap-plugin` topic discovery `req-cicd-fleet-bot-discovery` provides, under the same `unified-systems-com` owner qualifier (`req-cicd-fleet-bot-discovery-4`) — not the topic alone. | Inherits the org-scoping requirement, doesn't restate a separate one |
| req-cicd-fleet-bot-release-phase1-3 | Credential Never Leaves `org-bots` | Proposed | The `tap-release-please` App's private key is not made an organization secret, not copied to any repository, and not passed to any per-repository workflow — it is read only inside `org-bots`' own run. | Same rule, restated for the App key; the fork bot's token it once described is gone |
| req-cicd-fleet-bot-release-phase1-4 | CI Triggers On The Resulting PR, Approval Model Stated Precisely | Retired | Checks run normally on the fork-authored PR because a `GITHUB_TOKEN`-authored PR (which would not trigger checks at all) is never used for this stage. Approval is a human-*initiated*, rule-*decided* batch: a human chooses when to run `approve_bot_runs.py`; within that run, every waiting run passing its identity/structural rules is approved, none individually selected. | Retired 2026-11-19 with fork mode: an App-authored PR waits behind no "Approve and run" gate; `-7` states what replaces it |
| req-cicd-fleet-bot-release-phase1-5 | One Topic Covers Both Tools | Proposed | A repository tagged for Renovate discovery is, by the same tag, in scope for release-please discovery — no second registration step, no per-repo workflow file to forget. | Replaces the reverted `new-plugin`-scaffolds-a-caller-workflow approach |
| req-cicd-fleet-bot-release-phase1-6 | Release PRs Are Opened By The App, Whole Fleet Per Run | Proposed | `release-please release-pr` runs from `org-bots` on a schedule, authenticated with a `tap-release-please` installation token, over `tap` and every discovered repository in one run, with no slice, rotation or cap on new release PRs. | `org-bots#41` |
| req-cicd-fleet-bot-release-phase1-7 | The Repository's Own Checks Run On The Release PR | Proposed | The release PR is opened with the App's token, never a `GITHUB_TOKEN`, so the target repository's checks run on it without an approval step; the bot adds no `Signed-off-by` trailer. | A check that exempts bots must name the App's bot user by id |

### A Merged Release PR Is Tagged By The App

----
RID: `req-cicd-fleet-bot-release-phase2`

Status: `Proposed`

Nothing is released until a human merges a repository's release PR. Once one has been merged,
the same hourly run that opens release PRs tags the merge commit and publishes the GitHub Release
(`release-please github-release`), with the same `tap-release-please` installation token. The tag
is created with the App's token so that the repository's tag-push workflows (`release-sbom.yml`)
run on it; a tag made with a `GITHUB_TOKEN` would trigger nothing.

The human act this stage rests on is the merge, not the tag. Merging the release PR is a
reviewed, attributed decision on the target repository; the tag that follows is the mechanical
record of it, and is made within the hour without anyone having to remember.

`scripts/cut-release.sh` — the same two steps from a maintainer's machine, with their own
`gh auth token` — stays as the hand fallback for a repository the App cannot serve or a release
that cannot wait for the next run. It is not the normal road.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-fleet-bot-release-phase2-1 | Cut-Release Is Unchanged | Retired | `scripts/cut-release.sh`'s behavior, invocation, and credential model are identical before and after this spec lands. | Retired 2026-11-19: cutting by hand is the fallback, not the road; `-2` and `-3` state the road |
| req-cicd-fleet-bot-release-phase2-2 | Only A Human-Merged Release PR Is Tagged | Proposed | The scheduled run tags and publishes a release only for a release PR a human has merged; it never merges one itself. | |
| req-cicd-fleet-bot-release-phase2-3 | The Tag Starts The Repository's Tag Workflows | Proposed | The tag is created with the App's installation token, not a `GITHUB_TOKEN`, so the target repository's tag-push workflows run on it. | `release-sbom.yml` is the consumer today |

### App Keys Live Only In `org-bots`

----
RID: `req-cicd-fleet-bot-no-app-key-distribution`

Status: `Proposed`

Two org-owned GitHub Apps hold write on the fleet: `tap-renovate` (`contents`, `pull-requests`
and `workflows` write, `vulnerability-alerts` read) and `tap-release-please` (`contents` and
`pull-requests` write). Both are installed on **all repositories** in the organization (George,
2026-11-19), so a new plugin repository is covered the moment it carries the topic and no run can
fail because someone forgot to add a repository to an installation.

**An App installed on every repository can mint a token for any of them, which is exactly why
its key is held in one place.** Each App's private key exists only as a secret of the `bots`
environment of `org-bots`, which deploys from `main` only, so the key is handed to nothing but a
workflow already merged to `main` there. It is never an organization secret, never copied into a
plugin repository's or `tap`'s own secret store, and never passed to a workflow in another
repository. Copying it into twenty-plus repositories' secret stores would turn each into an
independent leak surface for one organization-wide-write credential.

**From 2026-09-27 to 2026-11-19 this requirement said the opposite end state**: that neither App
should hold write at all, with both uninstalled once the fork bot covered their work. That end
state is withdrawn with the fork design. What survives is the half that was always sound — the
key is not distributed.

**`tap`'s own copies are deleted.** `tap` once ran its own Renovate and release-please workflows
with App credentials held as `tap`-repository secrets (retired 2026-09-29). Those secrets are
named, so their absence is checked by name: `RENOVATE_APP_ID`, `RENOVATE_APP_PRIVATE_KEY`,
`TAP_RELEASE_PLEASE_APP_PRIVATE_KEY`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-fleet-bot-no-app-key-distribution-1 | No Org App Holds Write, Enforced | Retired | A periodic check queries `GET /orgs/unified-systems-com/installations` and fails if any installed GitHub App's `permissions` object holds `write` or `admin` for any resource. No allowlist: an App that needs to be there anyway is `-2`'s named, sequenced exception, not an entry in this check. | Reversed 2026-11-19: the two bot Apps hold write by design |
| req-cicd-fleet-bot-no-app-key-distribution-2 | Removal Is Sequenced, Not Assumed | Retired | The Apps are uninstalled and their keys deleted only after `tap`'s own `renovate.yml` and `release-please.yml` are retired (amended 2026-09-29: `tap` is served by hand in the meantime, not by the fork bot); until then `-1`'s check is expected to fail rather than being treated as broken. | Retired 2026-11-19 with `-1`: the Apps are not removed |
| req-cicd-fleet-bot-no-app-key-distribution-3 | `tap`'s Own App Secrets Are Deleted | Proposed | `RENOVATE_APP_ID`, `RENOVATE_APP_PRIVATE_KEY` and `TAP_RELEASE_PLEASE_APP_PRIVATE_KEY` are absent from `tap`'s repository secrets, checked by the known name of each — not an inventory. | Narrowed 2026-11-19 from five names: the two `org-bots` environment secrets are where the keys now live |
| req-cicd-fleet-bot-no-app-key-distribution-4 | Secret-Name Inventory Stays Supplementary | Proposed | A periodic allowlist-based inventory of plugin repositories' secret names (catching an unexpected name, not just a missing canonical one) remains as a *supplementary* detective check, not the primary enforcement. | |
| req-cicd-fleet-bot-no-app-key-distribution-5 | Each App Key Lives In One Environment | Proposed | Each App's private key exists only as a secret of `org-bots`' `bots` environment, which deploys from `main` only; it is not an organization secret and is not present in any other repository's secrets. | The primary rule since 2026-11-19 |
| req-cicd-fleet-bot-no-app-key-distribution-6 | Both Apps Are Installed On All Repositories | Proposed | `tap-renovate` and `tap-release-please` are installed with repository access "All repositories", so adding a repository to the fleet has no installation step. | George, 2026-11-19; which repositories a run acts on is discovery's decision, not the installation's |

### A Run's Token Is Bounded By What The Run Asks For

----
RID: `req-cicd-fleet-bot-shared-credential-bound`

Status: `Proposed`

An App installed on every repository is the widest credential in the organization. What a single
run can reach is narrowed at the moment its token is minted, and that narrowing — not the App's
installation — is the bound this requirement states.

- **The token names only the run's repositories.** The mint step passes an explicit
  `repositories` list: `tap` plus the discovered fleet for a scheduled run, or the one repository
  a dispatch names. It is never minted for the whole installation, and an empty or malformed list
  stops the run before the mint, because an unscoped mint would cover every repository the App is
  installed on.
- **The token carries only the permissions its job needs.** Renovate's: `contents`,
  `pull-requests` and `workflows` write (`workflows` so it can bump the pinned `uses:` SHAs under
  `.github/workflows`) and `vulnerability-alerts` read (so it sees each repository's Dependabot
  alerts and opens the fix as a `security` PR). Release-please's: `contents` and `pull-requests`
  write, and no `workflows` permission, so it cannot edit a workflow file. Neither holds
  administration.
- **The token lasts for the run.** It expires within the hour, and the mint action revokes it
  in its post step when the job ends (`actions/create-github-app-token`, `skip-token-revoke`
  left at its default of false).
- **Nothing merges on its own.** `automerge` is off for Renovate and release-please never merges
  a release PR, so nothing reaches a default branch without a human merging it. That is a bound
  on default branches only; the next paragraphs say what a token can do short of a merge.
- **A target repository's own config cannot run commands with the token.** Renovate's global
  configuration allows exactly one post-upgrade command, anchored and argument-free, from a
  read-only mount (the boot-record digest refresh), and the shell executor is off.
- **The code that holds the token is pinned.** The Renovate image is pinned by digest and every
  action by commit SHA, so a moved tag cannot swap what receives the token.

**What this does not bound, stated so it is not assumed.** One scheduled run holds a write token
over the whole fleet for up to an hour. A compromise of that job — the pinned image, a pinned
action, or the runner — reaches every fleet repository's branches in one token lifetime, not a
slice of them. The fork design and the slicing after it were both attempts to shrink that reach,
and both were given up for reliability (George, 2026-11-19). The controls above reduce the ways
to get there; they do not make the reach small. Two paths in particular stop short of a merge
and are not closed by "a human merges every change":

- **A bot PR runs the target's workflows before anyone reads it.** An App-authored PR is a
  branch in the target repository, so the repository's `pull_request` workflows run on it at
  once, from the PR's own copy of the workflow files, with whatever secrets and token
  permissions those workflows are given. Renovate's token can write workflow files. A
  compromised Renovate run can therefore execute code in a target repository's Actions when the
  PR opens. Under the fork design, fork isolation and the "Approve and run" gate stopped this;
  nothing in this spec replaces them, and `allowedCommands` does not reach it, because the code
  runs in the target's Actions, not in Renovate.
- **The release token can tag without a merged release PR.** "Only a human-merged release PR is
  tagged" ([`req-cicd-fleet-bot-release-phase2`](#a-merged-release-pr-is-tagged-by-the-app))
  describes what the run does. The token's `contents` write would let a compromised run create
  a tag and a release directly, which starts the tag-push workflows. No tag ruleset is required
  here to bind tags to a merged release PR.

Both are accepted with the App model, not solved by it. A control for either (secrets held
behind environments on PR workflows, a tag ruleset) would be a new requirement, not an
implication of the ones above.

**From 2026-09-27 to 2026-11-19 this requirement was "A Fleet-Shared Credential Holds No Role
Anywhere"**, and its guards on fork-triggered jobs (`-2`, `-4`, `-5`, `-6`, `-7`) were moved to
`unified-systems-com/git-serious-double-tap#63` as a proposal for a TAP-specific watch ruleset
(George, Q68c, 2026-09-28). Those guards are about what a fork-triggered job can reach, which
matters for every outside contributor's PR whether or not a fork bot exists, so the proposal
stands on its own there. The rows stay below, retired, so their ids are never reused.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-fleet-bot-shared-credential-bound-1 | No Shared Credential Holds A Role | Retired | Every credential used identically across more than one repository in the fleet holds no write role on any of them. | Reversed 2026-11-19: the Apps hold write; `-8` to `-11` state the bound |
| req-cicd-fleet-bot-shared-credential-bound-2 | `pull_request_target` Is Fleet-Guarded, Not Just Absent | Retired | A CI guard fails closed if any fleet workflow adds `pull_request_target`, rather than the fleet merely happening not to use it today. | Moved to git-serious-double-tap#63 as a proposal (George, Q68c, 2026-09-28) |
| req-cicd-fleet-bot-shared-credential-bound-3 | Auto-Approval Is Named As A Capability | Retired | The credential's threat model documents "bypasses the human Approve-and-run click for this identity" as a real capability the credential grants, not an absence of one. | Retired 2026-11-19 with fork mode: no identity is auto-approved; `scripts/approve_bot_runs.py` is unused by the App lane |
| req-cicd-fleet-bot-shared-credential-bound-4 | Effective Token Permission Is Fleet-Guarded, Not Just The Org Default | Retired | A guard fails closed if the *effective* permission a fork-triggered job runs with is ever write — covering the organization default, any explicit job- or workflow-level `permissions:` block that widens it, and GitHub's separate "workflows can approve pull requests" / write-back setting for fork PRs — not the org default alone. | Moved to git-serious-double-tap#63 as a proposal (George, Q68c, 2026-09-28) |
| req-cicd-fleet-bot-shared-credential-bound-5 | No Credential Path Into Fork-Triggered Jobs Is Fleet-Guarded | Retired | A guard fails closed if any fleet workflow's `pull_request`-triggered job gains a credential through *any* path — a direct `secrets.*` reference, a reusable-workflow call that inherits or is passed secrets, `id-token: write` (OIDC-minted cloud credentials, which exist outside GitHub's own secret-withholding guarantee), or a self-hosted runner (which does not carry GitHub-hosted runners' isolation guarantees at all). `pull_request_target` and direct `secrets.*` references are the sharpest versions of this failure, not the only ones. | Moved to git-serious-double-tap#63 as a proposal (George, Q68c, 2026-09-28) |
| req-cicd-fleet-bot-shared-credential-bound-6 | The Fork Bot's Own Standing Is Audited, Not Assumed | Retired | A periodic check queries the GitHub API for the fork bot account's (id 334543231) actual organization membership, base permission level, collaborator grants, and team memberships across the fleet, and fails loudly if any of them is ever non-empty. | Moved to git-serious-double-tap#63 as a proposal (George, Q68c, 2026-09-28); the account is since suspended |
| req-cicd-fleet-bot-shared-credential-bound-7 | `workflow_run` Consumers Are Allowlisted And Data-Only, Enforced | Retired | A guard fails closed on any fleet workflow triggered by `workflow_run` unless it is on an explicit allowlist of reusable workflows pinned by commit SHA — today, `unified-ai-review`'s `review.yml` only. Every allowlisted consumer must never check out the triggering run's PR head ref or sha, never execute, install, or shell-source content the fork-triggered run produced, and keep every secrets-bearing job in it read-only. | Moved to git-serious-double-tap#63 as a proposal (George, Q68c, 2026-09-28) |
| req-cicd-fleet-bot-shared-credential-bound-8 | The Token Names Only The Run's Repositories | Proposed | Each run's installation token is minted with an explicit `repositories` list — `tap` plus the discovered fleet, or the one repository a dispatch names — and a run with an empty or malformed list stops before the mint. | The App is installed on all repositories; an unscoped mint would cover all of them |
| req-cicd-fleet-bot-shared-credential-bound-9 | The Token Carries Only The Job's Permissions | Proposed | Renovate's token holds `contents`, `pull-requests` and `workflows` write and `vulnerability-alerts` read; release-please's holds `contents` and `pull-requests` write; neither holds any other permission. | Stated on the mint step, not inherited from the App's full grant |
| req-cicd-fleet-bot-shared-credential-bound-10 | Neither Bot Merges | Proposed | Renovate runs with `automerge` off and release-please never merges a release PR, so no change reaches a default branch without a human merging it. | Goal 4 |
| req-cicd-fleet-bot-shared-credential-bound-11 | Repository Config Cannot Run Commands With The Token | Proposed | Renovate's global configuration allows only the one anchored, argument-free boot-record refresh command from a read-only mount, with the shell executor off, so a target repository's own Renovate config cannot execute anything else while the token is held. | `allowedCommands`, `allowShellExecutorForPostUpgradeCommands` in `renovate/global.js` |

### The Bots Run Unpaced; Hand-Run Fleet Changes Are Paced

----
RID: `req-cicd-fleet-bot-paced`

Status: `Proposed`

On 2026-09-28 the fork bot's first fleet-wide runs opened about 50 PRs and renamed 22 forks in
twenty minutes, and GitHub's anti-abuse flagged the two-day-old account: the account and
everything it had created went invisible to everyone else, and the pipeline stopped until an
appeal. Everything fleet-wide was then paced: the bots covered one slice of the fleet per run,
rotated, behind random delays and per-run caps, and people were held to the same rule.

**The bots are no longer paced (George, 2026-11-19).** That account is gone. Renovate and
release-please run as org-owned GitHub Apps, which are not a young user account and are the
configuration both tools are built for. The slices cost more than they protected: a full pass of
the fleet took eight runs, Renovate's schedule was left off for two weeks, and a rotation that
moved only on success pinned scheduled release-please to one failing slice for days. Each bot
now covers the whole fleet in every scheduled run — Renovate nightly, release-please hourly —
with no slicing, rotation, random start, per-run cap, or pause, and with Renovate's own default
pull-request limits.

**People are still paced.** A maintainer's own account doing a fleet-wide change by hand (a pin
bump, a rename pass, a config sweep) is a burst of cross-repository activity from one user
account, which is the shape that was flagged, and losing a maintainer's account would be worse
than losing a bot's.

- **By hand**: one repository at a time; a pilot repository first, and the batch stops if the
  pilot is not green or a PR fails to open; PRs opened minutes apart at random, merges spaced at
  random. The 2026-09-28 fleet pin bump (24 repositories, bom-bom Q74) is the worked example.
- **"Succeeded" is checked, not assumed**: after a bot run, one of its PRs must resolve for someone
  other than the bot. The flagged run reported success while every PR it opened was hidden.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-fleet-bot-paced-1 | Bot Runs Are Sliced And Randomly Paced | Retired | Renovate touches at most one slice of the fleet per run and starts after a random delay; release-please caps new release PRs per run and pauses a random interval after each. | Reversed 2026-11-19; `-4` states what replaces it |
| req-cicd-fleet-bot-paced-2 | Hand-Run Fleet Changes Follow The Same Rule | Proposed | A fleet-wide change made from a person's account is piloted on one repository, stops on the first failure, and opens and merges one repository at a time with random gaps. | Documented in `org-bots` README, "The ramp"; confirmed standing 2026-11-19 |
| req-cicd-fleet-bot-paced-3 | A Run's PRs Are Checked To Exist | Proposed | After a bot run, at least one of the PRs it reports opening resolves for an account other than the bot. | A green run is not evidence its PRs are visible |
| req-cicd-fleet-bot-paced-4 | Each Scheduled Bot Run Covers The Whole Fleet | Proposed | Renovate runs on a daily schedule and release-please on an hourly one; each scheduled run covers `tap` and every discovered repository, with no slice, rotation, random delay, per-run cap or pause, and Renovate's pull-request limits are its defaults. | `org-bots#41` |

## Non-Goals

- **Shrinking a run's reach below "the whole fleet".** One job per repository with a
  single-repository token each would bound a compromised run to one repository. It was considered
  on 2026-11-19 and not taken: the goal is the standard configuration, run plainly.
- **The fork-triggered-job guards.** They moved to `unified-systems-com/git-serious-double-tap#63`
  and concern every outside contributor's PR, not the bots.
- **`scripts/approve_bot_runs.py`.** It served the fork bot's "Approve and run" gate and is
  unused by the App lane; removing it from `org-bots` is that repository's housekeeping.
- **Each repository's own Renovate rules.** How dependencies are grouped, pinned and labelled is
  repository configuration (`org-bots/renovate/preset.js`, or a repository's own
  `renovate.json5`), not a fleet-credential question.

## Related

`Issue# 200 - tap` (the plugin-fleet housekeeping epic), `Issue# 854 - tap` (release-please),
`Issue# 856 - tap` (Renovate discovery). `Issue# 879 - tap` tracked finishing the fork-bot
rollout and was closed as not planned on 2026-11-19. `org-bots#41` is the change that returns
both bots to whole-fleet scheduled runs.
