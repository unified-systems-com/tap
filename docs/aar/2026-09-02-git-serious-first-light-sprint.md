# AAR — git-serious first light: one day, six sessions, one approver

**Subject:** the *process* of the 2026-09-02 sprint (spilling into the morning of 09-03) — six concurrent
Claude sessions and one human landing the git-serious machinery view, the status wall, the bypass-actor
model, the App-permission ledger and the outputs collector across three repositories. The features have
their own records (git-serious-tap#35, tap#325, github-core#31/#48); this report is about how we worked.
**Companion:** `docs/misc/doc-dev-lessons-2026-09-02-status-wall-day.md` (the tables session's thirteen
keystroke-level rules from the same day; not repeated here).
**Date:** 2026-09-03. Written by the viz session (story-viz-git-serious).

## 1. Goal vs. Outcome (read this first)

**Goal:** turn the "what should the landing page show" discussion into a working machinery view of the tap
repository's CI system, and use the day to exercise the product's own process (spec-first via the skills,
issue-driven, AI-review triage).
**Outcome:** achieved and then some — first light of the machinery view in about four hours from the
decision, three wall ports merged on top of it, the bypass-actor model settled, all 55 GitHub App
permissions classified with a fail-closed ledger, releases/artifacts/packages collected by an agent, and
two prior-art passes (merge queues, scanner governance) that changed repository settings. The cost was
roughly three hours of humans-plus-agents on merge mechanics, one twelve-minute window in which
github-core main could not boot, and four defects that a shared-branch, sole-approver model produced by
construction. None lost data.

## 2. Timeline (UTC)

- **09-02 16:30** Landing-page discussion. Decisions: machinery view of ONE repository is the landing; sources
  right, outputs left with a `flow` sign; nesting `github.com ⊃ account ⊃ repo ⊃ workflow ⊃ job`;
  third parties top, human outputs bottom; module + spec in github_core, instance in git-serious.
- **17:00** Spec drafted first (add-panel skill), github-core PR#32; six issues filed and linked as sub-issues of
  git-serious-tap#35 (github-core#28–31, tap#293).
- **17:40** Core `ranked` layout; module written; edges reach the client typed on `label` only — found by probing
  the live scene, fixed; first render.
- **18:00** Stack-runtime re-entrancy overflow on the branch deck (tap#304, the tap#289 class) — fixed; **first
  light** (git-serious-tap PR#40, github-core PR#41).
- **18:30–19:00** Chrome pass (shared `chrome.js`, upper-left labels, per-side padding), fullscreen black-canvas
  bug fixed by an agent (CSS `background` shorthand), dynamic workflows marked, 75% graph row.
- **19:30** Bypass actors: no count node; `counted` state; red only when a bypass happened (github-core#40 spec,
  #39 make-it-right, git-serious#37).
- **20:00–21:00** Outputs agent builds releases/artifacts/packages (github-core PR#50); App-permission pass → ledger
  PR#48; George grants 24 → 29 read permissions; installation accepted; packages measured CLOSED to Apps.
- **21:00–23:00** Three wall ports (git-serious PR#43/#44/#45) merged onto the machinery branch; one reused batch
  id caught by the importer.
- **09-03 14:50–16:24** tap PR#307 approved four times, dismissed four times ("merge-base changed"); rulesets
  changed twice; the last-push rule found to discount criticalsec's approvals; #307 merges at 16:24.
- **16:00** tap#325 built: scanner ratchet (main's absolute Sonar/Codacy state, nightly, two-sided).
- **16:46** github-core merge sequence: stacked PR#41 auto-closed when its parent's branch was deleted → PR#70;
  collector conflict resolved; merged. **16:48–17:00** main unbootable: two `0005` migration leaves; PR#72.
- **17:10** Conflict on PR#316: a regeneration from a dot-path worktree rewrote 45 fragments as unaccounted and
  was pushed; reverted within minutes; regenerated correctly in the container.

## 3. What Went Well

- **Decision → spec → first light in one afternoon**, with the skill's spec-first flow doing the pacing. The
  spec's ACIDs were written as done-tests to be OBSERVED, and eleven were, the same day.
- **Issue-driven development held under load.** 57 issues opened across three repos in one day, each filed in
  the breath it was found (tap 31, github-core 22, git-serious 4). Threads stayed in issues, not in sessions.
- **The AI review ensemble found real defects**, not lint: explicit `permissions: {}` inheriting instead of
  revoking, placeholders that never retired, a re-execution that lost the repository's name, an org-wide
  7-hex prefix join in the outputs collector, orphan jobs floating outside github.com. Every round was taken.
- **Measured, not assumed.** The App's permissions were read from the App, not memory; packages were probed and
  found closed to Apps even with the permission granted; the bypass count was proven by the #11 probe; the
  ledger diff is computed from the live App. Each measurement changed a plan.
- **Peer coordination by message worked.** Ordering agreements (wall ports after the machinery landing),
  honest incident reports from peers (the deleted branch, the reused ids), and conflict clearing on request
  — no session stepped on another's working tree.
- **Reuse over reinvention.** The ranked layout, the numeric ratchet, the one-issue upsert, the extract refresh,
  the fake-`gh` test fixture — each was an existing house shape extended, found by reading first.
- **Two research agents** turned "what's the best practice" into sourced, ranked findings that corrected the
  session's own earlier advice (keep dismiss-stale → turn it off).

## 4. What Went Wrong

- **Approvals evaporated.** With dismiss-on-push on, GitHub dismissed #307's approval every time main moved
  under it — four times — and a cached recompute dismissed one with nothing moving at all. Hours were spent
  before the timeline was read.
- **A rule that discounts the approver.** "Require approval of the most recent reviewable push" silently
  discounted criticalsec's approvals (an outside collaborator), shown only in the PR page's small print. The
  docs do not say so. Found by A/B on two PRs.
- **Two `0005` migrations, one main.** Parallel branches numbered from the same parent; both merged green;
  main could not boot for twelve minutes. A third `0005` (PR#50) was queued to repeat it.
- **A stacked PR closed itself.** Merging the parent spec and deleting its branch closed the child PR rather than
  retargeting it; a `;` where `&&` belonged then deleted the child's branch for a minute.
- **Ids minted from a pool.** Twice, a batch id copied from a pool earlier in the day collided with an existing
  entity; the importer caught both, one after a merge.
- **Verification with masked exit codes.** `pytest … | tail -1` hid a red twice; a commit with a failing guard was
  pushed each time before the next run showed it.
- **A generator that trusts an empty scan.** From a worktree under `.claude/`, the source scanner saw zero files
  and the traceability sync rewrote every fragment as unaccounted; the result read like a regeneration and was
  pushed before "0 claims" was read.
- **The same issue built twice.** Two sessions implemented github-core#45 independently (PR#51 and PR#67), one
  filed in the evening, one the next morning on instruction; the collision was noticed after both were open.
- **Nobody was watching the scanners.** Sonar's quality gate on main was red with nine vulnerabilities and Codacy
  held 171 High/Error findings, under green PR checks that judge only new code. Found only because the merge-queue
  question forced the read.
- **False confidence from selectors that matched nothing** (the `edge_type` attribute that the client never
  carries) — the same shape as the tables session's rule 1, met independently.

## 5. Root Causes (blameless, plural)

1. **Concurrency without a queue or an ownership map.** Six sessions promoting into one main, one human approving,
   no serialisation. Every merge invalidated every other approval by design; migration numbers and batch ids were
   minted locally with no shared counter; two sessions could pick up one issue.
2. **Shared session branches.** Peers committing on the same session branch meant one promote carried 27 commits from
   several sessions, and attributing a Codacy finding needed `git blame`.
3. **Undocumented platform semantics.** GitHub's dismissal-on-merge-base-change and the last-push rule's treatment of
   outside collaborators are not in the docs; both were learned by experiment.
4. **Generators and checks that pass on absence.** A scan that finds nothing, a pipe that hides an exit code, a
   selector that matches nothing — each rendered "nothing found" as "fine". The house rule names this; the day
   produced three fresh instances.
5. **Local numbering of a global sequence.** Migrations are a linear graph per app; branches number them without
   seeing each other; CI checked model changes but never leaf count.

## 6. Impact

- Roughly three hours across human and agents on merge mechanics (approvals, conflicts, renumbering, the branch
  delete), against about eleven hours of feature work; net strongly positive.
- Twelve minutes of an unbootable github-core main; no data loss; no bad state reached any DB that had applied a leaf.
- Roadmap: the machinery view exists ahead of the MVP trim; permissions and outputs are unblocked; the merge-queue
  and scanner-governance decisions are made and partly applied (rulesets changed; queue pending).

## 7. Corrective / Preventive Actions

- [ ] **Merge queue on tap main** — George: drop SonarCloud/Codacy from required checks, add the queue rule (batch
      1–5, non-failing-only, timeout ≈ 2× gate). Promote script: enqueue instead of merge. *(tap#325 thread; owner George,
      then the viz session for the script change.)*
- [x] **Rulesets:** dismiss-stale OFF, last-push-approval OFF in both `org-require-pr` and `main-required-checks`
      (2026-09-03). Recorded in memory so it is not re-enabled.
- [ ] **Single-migration-leaf guard in plugin-ci and product-lines** — tap#329. Runs on the merged tree.
- [ ] **Traceability generator fails closed on an empty scan; dot-path ancestors not skipped** — tap#330.
- [x] **Scanner ratchet nightly, two-sided, one issue** — tap#325 built on `session/viz-git-serious`; ACID 7 after promote.
- [ ] **Claim before build.** A session comments "claimed by <session>" on the issue before writing code, and checks
      for a claim first. *(Process rule → AGENTS.md; no tooling yet. If it recurs, an issue label.)*
- [ ] **One session, one branch.** Sessions sharing a worktree take separate branches off the session branch and
      promote individually, so a promote carries one author's work. *(L — costs promote time; decide with George.)*
- [x] **Retarget a stacked child to main before deleting the merged parent's branch** (tables session's rule).
- [x] **Mint every id at the moment of use** (tables session's rule 2); bundles assert no in-bundle collision.
- [x] **`set -o pipefail` and capture the return code separately before any commit** (this session's rule → memory).
- [x] **Regenerate traceability only from a dot-free, container-visible path** (memory) — until tap#330 lands.

## 8. Lessons → Durable Rules

- **A shared main needs a queue before it needs faster approvals.** Speed of approval shrank the window; it never
  removed the race. The queue removes it and keeps the approval honest.
- **Read the platform's small print with an A/B, not the docs.** Two PRs, one difference, one answer.
- **Sequences that must be unique need a shared counter or a CI check on the merged tree** — migrations, ids,
  issue claims. Local minting plus parallel branches is a collision generator.
- **Absence must be loud in every tool we own**: a scan with zero sources, a pipe with a hidden exit code, a
  selector that matches nothing. If a check can pass by not looking, it will.
- **The record beats the memory.** The timeline of #307, the PR page's reviewers box, the events feed — each
  answered in seconds what reasoning had circled for an hour.

Mirrored to agent memory (`merge-queue-and-scanner-governance`, `viz-git-serious-session-state`) and to
`AGENTS.md` in the same change.
