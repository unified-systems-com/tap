# Proposal: make `unified-systems-com/org-bots` public

Status: **proposal, not applied.** The maintainer has chosen this direction and asked for
independent review before anything is changed. Nothing below has been done yet except the
read-only audit.

## Decision sought

Make org-bots public and give it a real second reviewer, in an order that never leaves it
public without an approval requirement (revised after the first review pass):

1. **CODEOWNERS first:** `* @notgeorge` becomes `* @notgeorge @criticalsec`, merged under
   today's rules. GitHub ignores `@criticalsec` until it has write access. Adding it now matters:
   if CODEOWNERS named only notgeorge when step 2 lands, the PR fixing it could never merge. Its
   author would be the sole code owner, and an author can't approve their own PR.
2. **Ruleset second:** a repository ruleset on `main` with 1 approving review, code-owner review,
   approval of the most recent push, and stale approvals dismissed on push. From here org-bots
   merges are frozen until step 5, and that freeze is intended: nothing merges unreviewed.
3. **Close the unused surfaces:** turn off the wiki (enabled, never used). Once public, turn on
   secret scanning, push protection and private vulnerability reporting (free on public
   repositories).
4. **Flip to public.**
5. **Add `criticalsec` as an outside collaborator with write access** (free on a public repo). The
   maintainer accepts the invitation.
6. **Prove it:** a test PR from notgeorge must be unmergeable until criticalsec approves it.

## Why

- **Nothing in it is secret.** It holds automation code and configuration: the Renovate global
  config and preset, the release-please runner, `scripts/cut-release.sh`,
  `scripts/approve_bot_runs.py`, a vendored copy of tap's boot-record digest code, tests, and a
  README with the threat model. Keeping it private only hides how the controls work; relying on
  that would be security through obscurity. The controls should hold with the design known.
- **It gives org-bots real review.** Today the only account with write access is `notgeorge`
  (admin). That is also the identity the maintainer's automation (Claude Code) acts as, so the
  code-owner rule is satisfied by the author and org-bots#6-#9 merged with 0 reviews. On a
  public repo, `criticalsec` can be a free outside collaborator, which is exactly how `tap`
  works today (tap#732, #849, #850, #851, #853: authored by notgeorge, approved and merged by
  criticalsec, under tap's repo ruleset requiring 1 approval).

## What becomes visible, and what was checked

Every surface that becomes public was inventoried and scanned. gitleaks v8.28.0 was used
throughout; a positive control (a planted `ghp_…` token in a scratch repo) is caught.

| Surface | Inventory | Result |
| --- | --- | --- |
| Git history, all refs | `--mirror` clone: 10 branches, 9 PR heads, 1 PR merge ref, 11 non-merge commits | gitleaks over `--all`: **no leaks** |
| Actions run logs | 67 runs. All 61 with logs were downloaded; the other 6 are Renovate runs cancelled before starting (no logs exist) | gitleaks over all 61: **no leaks**; 0 token-shaped strings; the debug run's `authorization` header is masked |
| Artifacts | 2, both CodeQL SARIF (`sarif-artifact-actions`, `sarif-artifact-python`) | 0 results each; gitleaks **no leaks** |
| Caches | 4 CodeQL overlay databases | Usable by workflows, not downloadable by the public |
| Issues and PRs | 9 threads (#1-#9: bodies, comments, review comments, review bodies) | gitleaks **no leaks** |
| Releases, tags, deploy keys | 0, 0, 0 | Nothing to expose |
| Wiki | Enabled, no wiki repository exists | Turned off in step 3 |
| Packages | Not checked: the auditing token lacks `read:packages` | org-bots has no workflow that publishes a package |
| Secrets and variables | Repository: none. Environment `bots`: secrets `FORK_BOT_TOKEN`, `TAP_RELEASE_PLEASE_PRIVATE_KEY`, `TAP_RENOVATE_PRIVATE_KEY`; variables `FORK_BOT_ID`, `FORK_BOT_LOGIN` (public values) | Environment secrets are never readable from the repository; `bots` deploys from `main` only |
| Workflows a stranger could trigger | On main: `renovate.yml`, `release-please.yml` (`workflow_dispatch` only, needs write) | No `pull_request`/`pull_request_target` workflow. A fork PR can trigger only GitHub's CodeQL default setup (read-only). The org requires approval for every run from outside contributors |

## What changes for an attacker, and why it's acceptable

- **They can read the approver's rules and the threat model.** Those controls are written to
  hold when known: identity by numeric id, fork parentage, head-sha match, per-file diff shapes,
  impostor-commit ancestry for `unified-systems-com/*` shas, and a human-started batch run.
- **They can fork org-bots and open PRs.** Such a PR merges only with `criticalsec`'s approval
  (step 4), and none of org-bots' secret-bearing workflows run on `pull_request`.
- **The fork bot (`tap-renovate-remote`) can now see and fork org-bots.** Its token still can't
  write to org-bots, and the approver's fleet list and Renovate's repo list must never include
  org-bots. The wave adopting topic discovery (tap#856) must never apply the `tap-plugin` topic
  to org-bots, and the approver should refuse it by name.

## Questions for reviewers

1. Is there anything in a public org-bots, its history, its run logs, or its issue/PR text,
   that an attacker could use and that the controls above don't cover?
2. With every log scanned clean, is there still a reason to delete old Actions run logs before
   the flip?
3. Does the revised order (CODEOWNERS, then ruleset, then flip, then collaborator) leave any
   window, or any way to lock org-bots that step 1 doesn't prevent?
