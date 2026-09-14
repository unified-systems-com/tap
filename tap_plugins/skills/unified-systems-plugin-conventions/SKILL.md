---
name: unified-systems-plugin-conventions
description: The unified-systems-com organisation's OWN plumbing for a plugin repository — AI-review shims, plugin-ci caller, Codacy/Sonar configs, licence, DCO, ruleset expectations, naming, release. Run by new-plugin only when the plugin targets unified-systems-com; every other owner never sees it.
argument-hint: <slug>
---

# unified-systems-com Plugin Repository Conventions

> **This skill is organisation-specific.** TAP itself assumes none of it. `new-plugin` and
> `create-plugin-spec` are owner-neutral and invoke this skill only when the author answered
> "unified-systems-com" to *where does the plugin live*. Another organisation writes its own
> equivalent; this file is the worked example.
>
> Canonical location: `tap_plugins/skills/unified-systems-plugin-conventions/SKILL.md`; `.claude/skills/…`
> is a wiring symlink (`scripts/wire-skills.sh`). Edit the canonical. Run from a TAP core checkout with the
> plugin checked out under `_dev-plugins/<slug>/` (`spawn-session.sh … --dev-plugins <slug>`).

## What the org ruleset already does to a new repo (no action; know it)

The moment a repository exists under `unified-systems-com`:

- The default branch is **PR-only**; direct pushes and force-pushes are refused. Bootstrap `main` with
  the first commit only (`README.md`, `LICENSE`, `.gitignore`); everything else arrives by PR.
- **Copilot code review** is attached to every PR automatically.
- Plugin repos require **zero approving reviews** (tap core's `main` requires one). Merging is still a
  human decision on any PR an agent opened.
- **Private vulnerability reporting** and the org-default `SECURITY.md` (from `unified-systems-com/.github`)
  apply. Do not add a repo-level `SECURITY.md`.
- **Repositories are public** (openness is the strategy). Confirm with George before creating a private one.

## First PR wave — the files this org's plugin repos carry

Copy from the TAP core checkout you are running in, at a **named commit**, and diff before committing;
never from another plugin repo's default branch (a mutable source that would inject workflow code into
every new repo). Record the source commit in the PR body.

| File | Source | Why |
| --- | --- | --- |
| `.github/workflows/ai-review-capture.yml` | tap `.github/workflows/ai-review-capture.yml` | Stage 1 of the Unified AI Review: unprivileged capture of the PR diff (`specs/spec-cicd-ai-review.md`). |
| `.github/workflows/ai-review.yml` | tap `.github/workflows/ai-review.yml` | Stage 2: the privileged review with the vendor keys; posts the Codex / Grok verdicts. Runs the **default-branch** definition, so both files must be on `main` before any PR in the repo gets a seat — a repo without them fails silently. |
| `.github/workflows/ci.yml` | `_dev-plugins/zizmor/.github/workflows/ci.yml` shape | Thin caller of tap's reusable `plugin-ci.yml` (`req-tap-plugin-extdev-repo-ci`), pinned to a tap `main` SHA, `plugin_slug: <slug>`, `secrets.harness_pat: ${{ secrets.TAP_CORE_RO_PAT }}`. Boots the plugin's in-package `ci` record and runs `pytest --pyargs tap_plugin.<slug>` on every PR. |
| `.codacy.yaml` | any sibling plugin repo | Bandit B101 excluded from tests only; committed engine config, never UI state. |
| `.sonarcloud.properties` | any sibling plugin repo | Migrations excluded from duplication; committed, never UI state. |
| `LICENSE` | any sibling | Apache-2.0. |

Fix the spec-path comment on line 2 of both shim files to the cross-repo form
(`# Spec: unified-systems-com/tap :: specs/spec-cicd-ai-review.md …`) — the only line that differs from
tap's copy; the pins must not.

## Things only an org admin can do (ask George; do not guess they are done)

- **Org secrets visibility.** `OPENAI_API_KEY`, `XAI_API_KEY` (AI review) and `TAP_CORE_RO_PAT` (plugin-ci)
  are org secrets. Whether a NEW repo sees them depends on their visibility setting, which an agent token
  cannot read. If the review stage or the ci lane fails on a missing secret, this is the cause.
- **SonarCloud and Codacy project onboarding** — the repo must be added in each tool's UI before the
  committed config does anything.
- **Renovate** tracks only tap core (`RENOVATE_REPOSITORIES`, tap#446); plugin repos get no bot PRs until
  that list changes.

## Conventions this org holds every plugin to

- **Identity:** dist `<slug>-tap`, repo named the same (`zizmor-tap`, `git-serious-tap`, `dcom-tap`). A repo
  created under the legacy `tap-plugin-<slug>` name is renamed (`gh repo rename`); GitHub redirects the old
  name.
- **DCO:** every non-merge commit carries `Signed-off-by` (`git commit -s`; tap's `scripts/hooks-install`
  applies it automatically in a tap checkout). Never hand-author a sign-off for someone else.
- **Issue trailers:** every commit range names its issue — `Closes: owner/repo#n` / `Part-of: owner/repo#n` /
  `No-issue: <reason>`. `PR# <n> - <repo>` / `Issue# <n> - <repo>` in prose, with the URL beside it for humans.
- **Boot pins by released tag**, never a branch; a plugin's `ci` record pins its dependencies at tags and
  itself at a commit.
- **Release** with `scripts/release-plugin.sh` from a `--dev-plugins` workspace: strict validation + the
  plugin's tests, PR-based landing, immutable `v<x.y.z>` tag. A release advances no consumer's pin.
- **Never `ruff format` / `black` a plugin's existing file** (no formatter config in plugin repos; it
  reformats the world). Never `git add -A` in a shared worktree.
- **AI-review triage:** after opening any PR, `scripts/pr-review-triage <pr> --wait` from the tap checkout;
  read every seat including suppressed findings; fix-worthy findings go onto the PR branch.

## Checklist

- [ ] Repo named `<slug>-tap`, public, bootstrap-only first commit on `main`.
- [ ] Six files above landed by PR, shim pins diffed against tap at a named commit, source commit in the PR body.
- [ ] Org-admin items asked of George, not assumed.
- [ ] First real PR got its AI review; if not, the secrets-visibility item is the first suspect.
