# Local Execution — Code This Repository Runs On Your Machine

## Philosophy

Most of what a repository ships is inert until someone chooses to run it. A subset is not: git hooks, editor and agent configuration, task definitions, install scripts. That subset **executes on a contributor's own machine**, often automatically, often before anyone has read it.

The governing rule is:

> Anything this repository ships that runs on a developer's machine is code-owned, is configuration pointing at a reviewable script rather than logic hidden in a config file, and is armed by an explicit human decision. Cloning must never execute.

Three observations drive it:

- **The blast radius is other people's computers.** Whoever can land a change to a hook runs commands on every contributor who has armed it. That is a wider grant than merge access to application code, and it deserves at least the same review — which means being *listed*, so a reviewer is summoned rather than relied upon to notice.
- **Surprise is the vulnerability, not execution.** Hooks are genuinely useful: TAP's pre-commit scan is the only layer that acts before a credential enters a commit object. The defect is not that code runs; it is that it runs without the person having been shown what it does. A disclosed, opted-into hook and a silently-armed one have identical capability and completely different consent.
- **A rule nothing checks will drift.** This spec exists because a `PostToolUse` hook was proposed under a governance-titled PR in 2026-08, into a directory covered by no CODEOWNERS rule, no spec, and no guard — and which `tap/source_scan.py`'s `DEFAULT_EXCLUDE_DIRS` causes every in-repo tree-walking guard to skip. Nothing was malicious and nothing noticed. Prose alone would not have.

This spec deliberately **does not** claim the surface is dangerous today. TAP's own hooks are small, network-free, and bypassable. It claims that the surface should be *governed like* the surfaces that defeat every other control, because that is the class it belongs to and the cost of saying so is near zero.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Cloning Is Inert | Obtaining the source never runs the source. |
| 2. | Arming Is A Choice | A human decides, having been shown what will run. |
| 3. | Executable Surfaces Are Owned | Every path that can execute locally has a code owner. |
| 4. | Logic Is Reviewable | Behavior lives in scripts that can be read, linted and tested — never inlined in config. |

## Prior Art

This is a well-settled problem and TAP is adopting the consensus rather than inventing one.

**Git itself** is the strongest precedent: `.git/hooks/` is deliberately unversioned and no clone or pull ever installs a hook. `core.hooksPath` must be set locally, on purpose. The friction is the security property.

**`pre-commit`** (pre-commit.com) is the reference implementation of the config/logic split: `.pre-commit-config.yaml` is checked in and contains no code; hooks come from external repositories pinned by `rev` and install into an isolated cache; and `pre-commit install` is an explicit act, so cloning alone does nothing. Its `repo: local` escape hatch is exactly the risky mode.

**`direnv`** contributes the sharpest property: `.envrc` is checked in, but requires `direnv allow` per directory, and it hashes the file so that *any* edit revokes consent until re-approved. That defeats the "it was fine when I trusted it" case.

**VS Code Workspace Trust** reaches the same answer from the editor side — opening an untrusted folder disables tasks, debug and extension execution until a human trusts it, once, per folder.

**npm `postinstall`** is the cautionary tale. Automatic execution on fetch is how `event-stream` and `ua-parser-js` propagated, and the ecosystem has been retracting it ever since: `--ignore-scripts` in CI, pnpm's `onlyBuiltDependencies`, Bun's `trustedDependencies`. The direction of travel across every ecosystem is auto-run being replaced by explicit allowlists.

TAP's contribution is not novelty. It is applying the rule to *agent* configuration (`.claude/`), which is new enough that the convention had not yet reached it, and making the ownership mechanical rather than remembered.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-dev-localexec-clone-inert | [Cloning Never Executes](#cloning-never-executes) | In Force | Obtaining the source must not run any of it |
| req-dev-localexec-consent | [Arming Is A Human Decision](#arming-is-a-human-decision) | Implemented | Disclosed, explicit, per-clone; never a side effect of another command |
| req-dev-localexec-owned | [Executable Surfaces Are Code-Owned](#executable-surfaces-are-code-owned) | In Force | Every locally-executing path carries a CODEOWNERS rule |
| req-dev-localexec-config-not-logic | [Config Points, Scripts Decide](#config-points-scripts-decide) | In Force | Behavior in a reviewable file; config holds a pointer |

---

### Cloning Never Executes
----
RID: `req-dev-localexec-clone-inert`
Status: `In Force`

Obtaining the repository — clone, fetch, pull, checkout, or a worktree add — must never cause repository-supplied code to run.

#### Implementation

- This is git's own default and TAP does not weaken it: `.githooks/` is inert until `core.hooksPath` is set, and setting it is `req-dev-localexec-consent`.
- The rule binds new surfaces too. A future task runner, editor config, devcontainer `postCreateCommand`, or agent hook is in scope the moment it can execute without a human having asked for it.
- The test is a thought experiment with one right answer: *if a stranger clones this repository and runs nothing, has any of our code executed?* If yes, that is a defect regardless of what the code does.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-localexec-clone-inert-1 | Clone Runs Nothing | In Force | A fresh clone with no further commands executes no repository-supplied code. | Git's default; the requirement is that TAP never adds a mechanism that breaks it. |

---

### Arming Is A Human Decision
----
RID: `req-dev-localexec-consent`
Status: `Implemented`
Trace: `non-python` — scripts/hooks-install

Installing repository-supplied hooks is a deliberate act by the person whose machine will run them, taken after being shown what will run. It is never a side effect of a command issued for another purpose.

#### Implementation

- `scripts/hooks-install` owns the decision: it describes each hook in `.githooks/` in plain language, states that none reach the network, states what declining costs, and then asks. `--yes` installs for automation, `--status` reports, `--uninstall` reverses.
- `scripts/spawn-session.sh` **offers** rather than performs. Until 2026-08-28 it ran `git config core.hooksPath .githooks` silently; a contributor's first commit was then rewritten by a hook they had never seen.
- The same script is the plain-clone path, so a contributor who never runs `spawn-session.sh` has the identical door. One path for everyone; a maintainer-only affordance would be a defect.
- **Consent is per-clone, not per-worktree.** `core.hooksPath` is written to the shared config and every worktree of a clone shares one git dir, so a single yes arms every worktree. The prompt says so, because a prompt that implies a narrower scope than it grants is worse than no prompt.
- Declining is safe by construction, and this is what makes the choice real rather than theatre. Both hooks that change an outcome are independently re-checked server-side: DCO by `scripts/check-dco` (pre-push and the `dco` CI job) and secrets by the `gitleaks` job plus the `secret-pattern` / `secret-leak` guards. Declining costs *earlier feedback*, never coverage.
- The one honest cost is stated rather than smoothed over: without the pre-commit hook a credential can enter local history and be caught later instead of never, and history rewriting is the only remedy once one lands.

#### Why the default flipped

`CONTRIBUTING.md` requires that the named human signer "personally review the contribution and deliberately authorize the `Signed-off-by` certification," and that "an automated system must not certify the DCO." A silently-armed hook that stamps that trailer from `git config` contradicted the repository's own published policy. The policy was right; the default was wrong.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-localexec-consent-1 | Spawn Does Not Arm Silently | Implemented | `spawn-session.sh` offers the install and honors a decline; it never sets `core.hooksPath` without disclosure. | `TAP_SPAWN_HOOKS=1/0` for automation; unset asks on a TTY, skips without one. |
| req-dev-localexec-consent-2 | Disclosure Before The Ask | Implemented | The prompt names each hook, what it does, that none reach the network, and what declining costs. | A yes to an undescribed question is not consent. |
| req-dev-localexec-consent-3 | Scope Is Stated | Implemented | The prompt states that the decision is per-clone and covers every worktree. | `core.hooksPath` is shared config. |
| req-dev-localexec-consent-4 | Declining Loses No Coverage | Implemented | Every hook that changes an outcome is re-checked server-side, so a decline costs feedback latency only. | DCO: `check-dco` + `dco` job. Secrets: `gitleaks` + the pytest guards. |
| req-dev-localexec-consent-5 | One Path For Everyone | Implemented | The plain-clone contributor and the spawn user install by the same command. | No maintainer-only affordance. |
| req-dev-localexec-consent-6 | Reversible | Implemented | `--uninstall` removes the setting; `--status` reports it without changing anything. | Consent that cannot be withdrawn is not consent. |

---

### Executable Surfaces Are Code-Owned
----
RID: `req-dev-localexec-owned`
Status: `In Force`

Every repository path that can execute on a contributor's machine carries a `.github/CODEOWNERS` rule, so that changing one summons a reviewer rather than depending on one noticing.

#### Implementation

- The set today is `/.githooks/`, `/.claude/`, and `/scripts/hooks/`, listed in the build/exec plumbing block of `.github/CODEOWNERS` alongside the Dockerfiles and compose files. That block already describes its members as "the surfaces where a single change defeats every other control"; these belong to it by the same logic, differing only in running locally rather than in CI.
- Adding a new locally-executing surface **without** adding its CODEOWNERS rule in the same change is a defect. The rule composes with `req-cicd-ai-review-least-privilege-5`, which states the CI half of the same idea.
- Ownership is the control that does not depend on a scanner. `.claude` is inside `DEFAULT_EXCLUDE_DIRS` (`tap/source_scan.py`), so every in-repo guard that walks the tree — including `SecretPatternGuard`, which otherwise reads every file looking for credential shapes — silently skips it. CI `gitleaks` does scan it, so the gap is one layer rather than total; but a reviewer summoned by CODEOWNERS is unaffected by walker configuration.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-localexec-owned-1 | Current Set Is Owned | In Force | `/.githooks/`, `/.claude/` and `/scripts/hooks/` each carry a CODEOWNERS rule. | Landed 2026-08-28. |
| req-dev-localexec-owned-2 | New Surfaces Arrive Owned | In Force | A change introducing a locally-executing path adds its CODEOWNERS rule in the same change. | Currently reviewed; a coverage guard is the intended mechanization. |

---

### Config Points, Scripts Decide
----
RID: `req-dev-localexec-config-not-logic`
Status: `In Force`

Configuration that arms local execution names a script. It does not contain the behavior.

#### Implementation

- `.claude/settings.json` holds a matcher and a path, and nothing else. The hook body lives at `scripts/hooks/pr-triage-nudge`, where it can be read in a diff, linted, and tested — none of which is true of an escaped one-liner inside JSON.
- The consequence is intended: a file that contains no logic has nothing to change, so it moves almost never, and any movement is conspicuous.
- A locally-executing script states its own limits in its header, and the statement is a reviewable claim rather than decoration. `pr-triage-nudge` asserts three: it only reads, it cannot fail the tool call, and its whole effect is one string injected into the agent's context.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-localexec-config-not-logic-1 | No Inlined Behavior | In Force | Config that arms local execution references a script path; it does not embed the logic. | Reviewability is the reason, not aesthetics. |
| req-dev-localexec-config-not-logic-2 | Scripts State Their Limits | In Force | A locally-executing script's header states what it may and may not do. | Turns "trust me" into a checkable claim. |

---

## Relationship To Other Specs

- **`specs/spec-security-posture.md`** — this spec is an instance of `req-sec-cheap-edges`: the ownership and consent edges cost almost nothing to lay while the surface is already open, and would be a retrofit later. `req-sec-honest-risk` is why the residual cost of declining hooks is stated rather than smoothed over.
- **`specs/spec-cicd-ai-review.md`** — `req-cicd-ai-review-least-privilege-5` is the CI-side half: CODEOWNERS covers build/exec plumbing. This spec is the developer-machine half of the same principle.
- **`tap_cares/specs/spec-tap-cares-secrets.md`** — `req-tap-cares-secrets-precommit` owns the pre-commit secret scan's behavior. This spec owns whether and how it is armed.
- **`specs/spec-cicd-hardening.md`** — `req-cicd-dco-signoff` owns the trailer and its enforcement. This spec owns the fact that the applying hook is opted into.
- **`specs/spec-dev-multisession.md`** — `spawn-session.sh` is the invoker that offers the install; the decision itself belongs here.

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed | Requirement has been designed but not yet accepted for implementation. |
| Approved for Development | Requirement is accepted and ready to be implemented. |
| In Development | Actively being worked on. |
| Implemented | Has been written. |
| Verified | Has met the acceptance criteria. |
| In Force | Standing doctrine: in effect now, and never "completed". Expects conformance from other work rather than an implementation of its own. |
| Refactoring | In the process of being re-worked. |
| Deprecating | In the process of being deprecated. |
| Deprecated | No longer part of the current architecture. |
