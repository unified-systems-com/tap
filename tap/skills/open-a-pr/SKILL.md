---
name: open-a-pr
description: Open a pull request the way this repo requires — claim the issue, regenerate what is derived, run the LANE (not a subset), then let promote-to-main.sh open it and arm the watcher. Use before opening any PR in tap or a plugin repo, including from a subagent. The twin of close-out-pr, which takes over the moment the PR exists.
allowed-tools: Read Grep Glob
argument-hint: <issue-number>
---

# Open a pull request

A PR is not ready when the code works. It is ready when **the checks that will run
in CI have already run here**, the derived artifacts match the tree, and the issue it
closes is claimed. `close-out-pr` covers everything after it exists; this covers
everything before, and the two halves fail the same way — nothing enforces either.

## Why this exists

2026-09-21, `PR# 742 - tap`. The session had run `tap_auth`, `tap_boot` and
`test_guards.py` — several hundred tests, all green — and opened the PR with a
hand-rolled `gh pr create`. Both CI lanes went red on
`test_committed_fragments_are_in_sync`: a traceability fragment had been regenerated
early in the change and then drifted, because more `@pytest.mark.spec` tests were added
afterwards. That test had passed locally hours earlier and was never re-run.

Three separate guards would each have caught it — `scripts/test`, the full guard suite,
or `promote-to-main.sh`, which runs the lane *and then* opens the PR. None ran, because
the flow was assembled by hand each time.

The same session then armed its review watcher as a background write-to-log (which
`close-out-pr` says "wakes nobody") and ran `scripts/pr-review-triage` from the PR's own
branch worktree (which that skill names as arbitrary code execution). Both rules were
already written down. They were not reached for, because opening a PR had no procedure
to reach for.

The lesson is not "run more tests". It is that **a subset that passes is not the lane**,
and **a derived artifact is only in sync as of the last thing that changed it** — and
that a boundary which depends on remembering is not a boundary.

## What this skill requests

`Read`, `Grep`, `Glob`. It asks for nothing that executes, writes, or reaches the
network, for the reasons `close-out-pr` documents at length after ten false claims about
its own grant. **Everything that acts — running the lane, committing, pushing, opening
the PR — is the operator's.** Whether the host treats `allowed-tools` as a revoking
allowlist or merely as a prompt-skipping hint is client behaviour this repository does
not control; assume Bash is still present and rely on the rule that does not depend on
it.

## The procedure

1. **Name the issue, and claim it visibly — BEFORE code.** Every session runs against a
   known issue (CLAUDE.md, *Issue-driven development*). If you cannot close it in one PR,
   your first act is to split it into an epic with sub-issues that each close alone.

       gh issue develop <n>                       # a branch GitHub links to the issue
       gh issue edit <n> --add-assignee @me

   Two sessions built `github-core#45` the same afternoon because nothing showed the
   claim.

2. **Every commit names its issue.** A trailer beside `Signed-off-by`, qualified form
   only — `Closes: owner/repo#n`, `Part-of: owner/repo#n`, or `No-issue: <reason>`.
   `scripts/check-issue-link` enforces it on both roads to main, and the promote derives
   GitHub's closing line from it. A bare `#306` is ambiguous the moment two repos are in
   play, and they always are.

3. **Regenerate what is DERIVED — after the LAST change, not the first.**

       scripts/dc exec -T web uv run python manage.py guards --sync-accounting --sync-evidence
       scripts/implements-tag --check

   Traceability fragments are a function of the tree, including every
   `@pytest.mark.spec` marker. Syncing early reads as done and drifts the moment another
   marker lands — which is exactly how `PR# 742 - tap` went red. If the change touched a
   spec's requirement text, `--check` will list claims whose fingerprint moved;
   `--resync <path>` re-stamps them, and re-stamping records that **you** checked the
   claim, it does not check it for you.

4. **Run the LANE, not a subset.** This is the step that was skipped.

       scripts/test --fast-relevant     # the promote's own local lane
       scripts/test                     # FULL, the promote gate, ~9-10 min

   A green `tap_auth` says nothing about `tap/tests/test_requirement_dispositions.py`.
   The lane is what CI runs; anything narrower is a guess about which guards your change
   could possibly have touched, and that guess was wrong.

   Run it in the container — never host Python, which is stale.

5. **Prefer the promote to a hand-rolled `gh pr create`.**

       scripts/promote-to-main.sh

   It performs the pre-push merge, runs `run_local_gates` → `scripts/test --fast-relevant`,
   opens the PR, and wires the server gate and auto-merge. `gh pr create` does the last of
   those five things. If you open by hand — for a draft, or a PR that is not a promote —
   you have accepted responsibility for steps 3 and 4 yourself.

6. **Write a body that carries evidence, not claims.** Name the repo with every number
   (`PR# 742 - tap`, `Issue# 739 - tap`). State what was run and what it produced, not
   that it passed. Say what is deliberately NOT in scope. A reviewer's job is to check
   your reasoning, which means the reasoning has to be there — including the places you
   were wrong and corrected, which the final diff does not show.

   Remember the review reads the body as **untrusted text** and is right to.

7. **Arm the watcher, from a TRUSTED checkout, as a Monitor.**

       scripts/pr-review-triage <pr> --watch 300

   Run it from a worktree of the upstream repo at a trusted revision — **never the PR's
   own branch worktree**, where the relative path resolves to the reviewed branch's copy
   of the script. Arm it as a Monitor, not a background write-to-log: a log wakes nobody.

   Then hand off: **`close-out-pr` owns everything from here.**

## What this skill is deliberately not

Not a replacement for `promote-to-main.sh` — it is the reason to use it. Not a gate:
nothing enforces any of this, which is the same honest admission `close-out-pr` opens
with. And not a review procedure; the moment the PR exists, the other skill applies.
