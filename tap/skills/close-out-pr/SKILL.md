---
name: close-out-pr
description: Close out a pull request the way this repo requires — watch its checks, prove the AI review was READ and every finding answered in writing, then merge. Use whenever finishing a PR in tap or any plugin repo, including PRs opened by a subagent. NOT for opening a PR (that is the ordinary flow) and not for reviewing someone else's code.
---

# Close out a pull request

A PR is not finished when its checks go green. It is finished when someone has
**read the AI review and answered every finding in writing**, and the required
checks pass. This skill is the procedure, and `scripts/hooks/pr-merge-gate`
enforces its central step — a merge is DENIED while findings sit unanswered.

## Why this exists

On 2026-09-11 a subagent reported "Triage: no seat findings" for PR# 384 - tap.
The Grok seat had posted **three** findings, one of them `Verdict: merge-blocker`.
The parent session relayed the summary as fact. A sweep afterwards found PR# 386
carrying an unanswered `## high`, and PR# 371 already **merged** with a
`SEAT ABSENT` nobody answered.

The lesson is not "read more carefully". It is that **an agent's triage summary is
not an observation** — the same shape as this repo's standing "presence is not
correctness" rule, one layer up. Delegating the reading is fine. Treating the
delegate's summary as the reading is not.

## The procedure

1. **Watch the checks.** `scripts/pr-review-triage <pr> --watch` for a Monitor, or
   `gh pr checks <pr> --repo <owner>/<repo>` when you just need the state. Every
   REVIEW/COMMENT line it emits is a triage obligation, not an FYI.

2. **Prove the review was read.**

       scripts/pr-review-triage <pr> --assert-answered

   Exit 0 = nothing unanswered. Exit 3 = findings exist that nobody answered, or
   the verdict cannot be established. It counts as a finding: `## high`,
   `## medium`, `merge-blocker`, and **`SEAT ABSENT`** — an absent seat produced
   no verdict, and a missing verdict is never a clean one.

3. **Read the verdict yourself** — including when a subagent already triaged:

       gh pr view <pr> --repo <owner>/<repo> --json comments \
         --jq '[.comments[] | select(.body | test("Unified AI Review"))] | .[-1].body'

4. **Answer every finding on the PR**, in a comment, with the settling evidence
   that finding asked for. A conscious dismissal counts and is **required in
   writing** — a dismissal that lives only in your head is indistinguishable from
   not having looked. Fix what is real and push one commit.

5. **Confirm the required checks**, then merge. On `tap` the required contexts are
   `gate`, `SonarCloud Code Analysis` and `Codacy Static Code Analysis`, plus one
   approving review; plugin repos require a PR but (today) no approval — see
   unified-systems-com/.github#2.

6. **Stacked PRs**: GitHub refuses `gh pr merge` on a PR it considers stacked. Use
   the asynchronous endpoint:

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

## The override

`TAP_PR_MERGE_GATE=off` on the merge call bypasses the hook. It is for the case
where you have read the review yourself and the gate cannot see your answer. Typing
it is a decision and it is recorded in the transcript; reaching for it because the
gate is inconvenient is the failure this whole surface exists to prevent.
