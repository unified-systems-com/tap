# Proposal: make `unified-systems-com/org-bots` public

Status: **proposal, not applied.** The maintainer has chosen this direction and asked for
independent review before anything is changed. Nothing below has been done yet except the
read-only audit.

## Decision sought

Flip `org-bots` from private to public, then give it a real second reviewer:

1. Make the repository public.
2. Add `criticalsec` as an outside collaborator with write access (free on a public repo; on the
   private repo this failed: the Team plan's two seats are full).
3. Change `.github/CODEOWNERS` from `* @notgeorge` to `* @criticalsec`.
4. Add a repository ruleset on `org-bots` main: 1 approving review, code-owner review, approval of
   the most recent push, dismiss stale approvals on push. (The org-wide ruleset requires code-owner
   review but 0 approvals.)

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

| Surface | Check | Result |
| --- | --- | --- |
| Git history, all refs (10 branches, 9 PR heads, 1 PR merge ref) | `gitleaks git --log-opts=--all` over a `--mirror` clone | 11 non-merge commits scanned, **no leaks**. Positive control: a planted `ghp_…` token in a scratch repo is caught. |
| Actions run logs (67 runs: 43 renovate, 4 release-please, the rest CodeQL/push/PR) | The one `LOG_LEVEL=debug` Renovate run (36331565961) downloaded and scanned | 10 masked `***` values, 0 token-shaped strings, the one `authorization` header masked, gitleaks **no leaks**. Info-level runs log less. |
| Secrets | `FORK_BOT_TOKEN` and two App private keys are **environment** secrets in `bots` | Not readable from the repository; public visibility does not expose environment secrets. The `bots` environment deploys from `main` only. |
| Workflows a stranger could trigger | Triggers on main | `renovate.yml` and `release-please.yml`: `workflow_dispatch` only (needs write). No `pull_request` / `pull_request_target` workflow. A fork PR can trigger only GitHub's CodeQL default setup (read-only). The org requires approval for every run from outside contributors (`all_external_contributors`). |
| Issues / PR text | Titles, bodies, review comments | Engineering discussion; no credentials (bodies reference secrets by name only). |

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
2. Should the old Actions run logs be deleted before the flip, even though the scan is clean?
3. Is the sequencing safe: flip first (so the collaborator is free), then CODEOWNERS, then the
   ruleset? During the window between flip and ruleset, org-bots is public with the old
   self-review. Should the ruleset go first, with a temporary bypass?
4. Anything to enable on the flip: secret scanning, push protection, private vulnerability
   reporting?
