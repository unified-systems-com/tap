---
name: close-out-pr
description: Close out a pull request the way this repo requires — watch its checks, read the AI review yourself, answer every finding in writing, then merge. Use whenever finishing a PR in tap or any plugin repo, including PRs opened by a subagent, and after every push to one. NOT for opening a PR (that is the ordinary flow) and not for reviewing someone else's code.
allowed-tools: Read Bash(scripts/pr-review-triage *) Bash(gh pr *) Bash(gh issue *) Bash(gh api *) Bash(git log *) Bash(git status *) Bash(git diff *) Bash(git add *) Bash(git commit *) Bash(git push *) Bash(scripts/dc *) Bash(python3 *) Grep Glob
argument-hint: <pr-number>
---

# Close out a pull request

A PR is not finished when its checks go green. It is finished when someone has
**read the AI review and answered every finding in writing**, and the required
checks pass.

Nothing enforces this. There is no hook and no gate — the one that was built was
withdrawn as unsound (see *What is deliberately not here*). This skill is the
procedure, and running it is a decision you make each time.

## Why this exists

On 2026-09-11 a subagent reported "Triage: no seat findings" for PR# 384 - tap.
The Grok seat had posted **three** findings, one of them `Verdict: merge-blocker`.
The parent session relayed the summary as fact. A sweep afterwards found PR# 386
carrying an unanswered `## high`, and PR# 371 already **merged** with a
`SEAT ABSENT` nobody answered.

It recurred on 2026-09-21, in a session that had read the operator memories
describing exactly this. After pushing to PR# 166 - tap-plugin-github-core and
un-drafting it, the session armed a **hand-rolled `gh pr checks` loop** rather than
`scripts/pr-review-triage --watch`. A checks-only loop cannot see reviews or bot
comments at all, so it reported silence while the Codex and Grok seats each carried
findings — two of them valid and fix-worthy. They were read only because the
operator asked, unprompted, whether a close-out procedure was being followed.

The lesson is not "read more carefully". It is that **an agent's triage summary is
not an observation**, and **a watcher that cannot see reviews reports their absence** —
the same shape as this repo's standing "presence is not correctness" rule, one layer
up. Delegating the reading is fine. Treating the delegate's summary as the reading
is not. Absence of evidence is not evidence of absence.

## The procedure

1. **Arm the watcher — on open, and again after every push.**

       scripts/pr-review-triage <pr> --watch 300

   Arm it as a Monitor, not a background write-to-log, which wakes nobody. It emits
   one line per new review, per bot comment and per `mergeStateStatus` transition,
   plus a `CHECKFAIL` line the moment any INDIVIDUAL check goes red — so a Sonar or
   Codacy red is workable immediately instead of after the whole gate resolves.
   Every REVIEW/COMMENT line it emits is a triage obligation, not an FYI.

   It resolves `{owner}/{repo}` from the working directory, so run it from a
   worktree of the PR's own repo. There is no `--repo` flag, and its absence is not
   a reason to hand-roll a loop. Un-drafting counts as an open: it triggers a fresh
   review run.

   Cadence: `--watch 300`, at most two watchers at once, and stop one when its PR
   merges. Three watchers hit GitHub's secondary burst limit — a 403 on the Actions
   endpoints while `rate_limit` still reports thousands remaining.

2. **Read the verdict yourself** — including, especially, when a subagent already
   triaged it:

       scripts/pr-review-triage <pr>

       gh pr view <pr> --repo <owner>/<repo> --json comments \
         --jq '[.comments[] | select(.body | test("Unified AI Review"))] | .[-1].body'

   Read **all three surfaces**: review summaries (including the suppressed findings
   Copilot hides inside a `<details>` block), inline review comments, and the bot
   issue comments where the unified review lands. Reading two of the three is worse
   than reading none — the output looks complete while silently omitting a seat.

   The unified review comment is **edited in place** on every rerun, so re-read it
   after each push rather than trusting what you read last time.

   A seat that did not run is `SEAT ABSENT` — a missing verdict, never a clean one.
   A repository with no ai-review workflow at all is a **bug to file**, not a quiet
   pass.

3. **Answer every finding on the PR**, in a comment, with the settling evidence that
   finding asked for. A conscious dismissal counts and is **required in writing** — a
   dismissal that lives only in your head is indistinguishable from not having
   looked. Fix what is real and push **one** commit; fixing per-finding as they
   arrive manufactures the next review round.

   A finding that is real but out of scope gets **filed as an issue** and named in
   the reply, rather than silently widening this PR.

4. **Confirm the required checks, then merge.** On `tap` the required contexts are
   `gate`, `SonarCloud Code Analysis` and `Codacy Static Code Analysis`, plus one
   approving review. Plugin repos require a PR but, today, no approval — see
   unified-systems-com/.github#2.

   Query `state` and `mergedAt`, never `mergeStateStatus`: a merged PR returns
   `UNKNOWN`, which reads as pending.

5. **Stacked PRs**: GitHub refuses `gh pr merge` on a PR it considers stacked, and a
   PR merged into a feature branch closes nothing. Retarget the child to `main`
   BEFORE deleting its parent branch, then use the asynchronous endpoint:

       gh api -X PUT -H "X-GitHub-Api-Version: 2026-03-10" \
         repos/<owner>/<repo>/pulls/<n>/merge-async -f merge_method=merge

## Known false positive: `except A, B:` is valid Python 3.14

Reviewer models trained before Python 3.14 report unparenthesised
`except TypeError, ValueError:` as a Python-2 `SyntaxError` and escalate it to
`merge-blocker`. [PEP 758](https://peps.python.org/pep-0758/) makes it **valid** on
3.14, which TAP requires. It happened twice on 2026-09-11 (PR# 384, PR# 386).

Settle it, do not "fix" valid code:

    python3 -c "import ast; ast.parse(open('<file>').read()); print('parses')"
    scripts/dc exec -T web python3 -c "import sys; print(sys.version)"

Then reply on the PR with both outputs. Do not add parentheses to satisfy a
reviewer about a language version it does not know.

## What is deliberately not here

An earlier version of this skill documented an `--assert-answered` exit code, a
`PreToolUse` merge-gate hook, and a `TAP_PR_MERGE_GATE=off` override. **None of
them exist**, and this section is here so nobody goes looking for them or
reimplements them.

PR# 392 - tap was closed not-actionable on 2026-09-10. The "answered" check was
proven unsound against its own module: an unanswered `## medium` followed by a
human comment reading *"rebasing onto main, will look at this later"* exited **0**,
and three findings answered by one comment naming only finding A exited **0**. It
treated any non-bot comment newer than the finding as an answer, per-PR rather than
per-finding. Not matching is unconditionally permissive.

The hook half could not bind a merge in any case: a `PreToolUse` hook is
client-side and opt-in by design (`req-dev-localexec-consent`), so it is invisible
to the GitHub UI and to any session without hooks installed. A seatbelt, not a lock.

What was sound and is worth reviving inside a real gate: the **coverage** predicate —
*a review exists and every required seat reported*. Enforcement belongs where the
merge decision is made, which is the design drafted in Issue# 398 - tap (all
requirements `Proposed`). Issue# 390 - tap tracks the gate.

Until one of those lands, the honest statement is the one at the top: nothing
enforces this, so run the procedure on purpose.
