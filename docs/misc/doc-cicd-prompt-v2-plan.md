---
spec: ../../specs/spec-cicd-ai-review.md
audience: [developer, llm]
covers:
  - ../../specs/spec-cicd-ai-review.md
  - req-cicd-ai-review-harness-repo
  - req-cicd-ai-review-graduation
  - req-cicd-ai-review-untrusted-content
update-triggers:
  - The prompts repo lands pack v2 — flip the deliverable statuses below and record the merged SHA
  - The agentic-actions-auditor pass runs — record findings (or the clean bill) in the companion section
  - Observation-window evidence changes a v2 design decision — record the reversal and why
---

# Prompt v2 plan — Trail of Bits methodology imports into the security pack

**Status: BUILDING 2026-08-24 (deliverable 1 open as prompts PR #2). Builds on pack v1 (`packs/security/prompt.md`,
`unified-ai-review-prompts`), which stays live until v2 merges.**

## Why now

Three converging triggers:

1. **The queued ToB imports** (run-sheet section "Trail of Bits methodology imports — queued
   2026-08-20") have two prompt-shaped items — `fp-check` gated verdicts and
   `differential-review` phase ordering — that never got built while the machinery arc landed.
2. **The false-positive lesson is now empirical.** On tap#117 both seats confidently reported a
   "stale ancestry fetch" bug that did not exist — the refuting fetch sat in a hunk outside
   their diff view. Advisory-comment credibility is the graduation currency
   (`req-cicd-ai-review-graduation`); unhedged wrong findings spend it. v1 already demands
   "state what you could not review," but nothing forces a finding to survive its own
   cross-examination before posting.
3. **One PR advances four threads.** Pack v2 is the next natural change to the prompts repo,
   which is: the recorded trigger for bumping the harness self-shim pins (the accepted
   one-revision lag); the first live demonstration of the review-system-reviews-itself loop
   (`req-cicd-ai-review-harness-repo-5` flips Implemented on its evidence); and the behavioral
   proof of the org-scoped seat keys, which unlocks the key-rotation cleanup (delete tap's
   shadowing repo secrets, revoke old vendor keys).

## What v1 already does (keep, do not regress)

Trusted/untrusted input contract with identity-raises-never-lowers; injection-instructions-are-
findings; the seven-lens malicious-change list (cover-story mismatch first); severity discipline;
"silence never reads as a clean bill"; no style commentary. **v2 is a restructure around these
lenses, not a rewrite of them.**

## Design

### 1. Phase-ordered review (`differential-review` skeleton)

Replace the flat lens list with four ordered phases the seat must walk **in order**, spending
attention where risk concentrates. One API call per seat, unchanged — phases are prompt
structure, not extra calls.

- **Phase A — Triage.** Risk-score the changed files from the trusted file list + diff before
  reading deeply: plumbing (.github/**, scripts/**, Dockerfile*, .githooks/**) > dependencies >
  auth/services/migrations/secrets > application code > docs. State the ranking in one line so
  the reader sees where attention went (and where it did not — feeds the limits section).
- **Phase B — Regression context ("why did the old code exist").** For each high-risk hunk,
  reason about what the removed/changed lines were protecting against before judging the new
  lines. This is the xz-lesson phase: smuggled changes look reasonable in isolation and wrong
  only against the purpose of what they replaced. v1 lens 2 (weakened controls) becomes this
  phase's checklist.
- **Phase C — Blast radius.** What does the change now ENABLE, transitively — who calls it,
  what trusts it, what runs it (CI? maintainer machine via .githooks? install-time via build
  hooks?). v1 lenses 1, 3, 4, 7 fold in here.
- **Phase D — Adversarial pass.** Re-read the full diff once assuming a competent attacker
  wrote it to pass phases A–C: the deliberately-boring-looking hunk, the payload split across
  files, the test that pins the malicious behavior in as expected. Lenses 5 and 6 fold in here.

### 2. Gated verdicts (`fp-check` discipline)

Every finding must carry, before it posts:

- **Refutation attempt** — one sentence arguing the finding is a false positive, written in
  good faith ("the guard may exist in a file outside my view", "this may be dead code").
- **Settling evidence** — what a human could check in under a minute to confirm or kill it
  ("grep for X", "read lines N–M of file Y", "run Z").
- **Confidence gate** — if the refutation depends on code the seat cannot see (truncated diff,
  off-diff context, null trusted facts), the finding is REPORTED BUT CAPPED at medium and
  labeled "unverifiable from my view". The tap#117 false-alarm pair would have posted as
  medium-hedged instead of High-confident under this rule.

Findings the seat itself refutes get one summary line ("considered and rejected: …"), not a
full entry — the reader learns the seat looked, without alarm fatigue.

### 3. Kept verbatim from v1

Input contract, injection handling, severity vocabulary, could-not-review section, one-line
verdict. The verdict.json calibration join keys (machinery-side) are untouched — v2 is
prompt-only, zero machinery change.

### Non-goals (named, so scope cannot creep)

- **No second API call** for the fp-check pass. A separate cheap-model devil's-advocate call
  (gpt-5.6-luna is the natural fit) is a recorded FUTURE option if the in-prompt gate proves
  weak; it changes machinery and spend shape, so it waits for observation-window evidence.
- **No new packs.** Code-quality/best-practices packs stay backlogged behind the security
  pack's observation window (spec radar).
- **No PIGuard seating.** The injection pre-screen stays parked until real contributor PR
  traffic (George's standing parking, 2026-08-20).
- **No confidence numbers.** Self-reported percentages stay rejected (spec confidence stance);
  the gate above is categorical (capped-at-medium), not numeric.

## Licensing (the boundary that makes this legal)

`trailofbits/skills` is CC BY-SA 4.0. **Decision at build time (2026-08-24): v2 was written
entirely in our own words from this project's recorded methodology summaries — the METHOD is
imported (phase order, gate discipline), no ToB text was adapted — so the pack remains
Apache-2.0 with a credit comment naming trailofbits/skills (differential-review, fp-check).**
The per-pack LICENSE override stays available if a future pack ever does adapt CC BY-SA text;
this one did not, and declaring Share-Alike on a non-derivative would contaminate without
cause. Nothing is fetched from Trail of Bits at build or run time — ideas entered through this
reviewed plan, not through vendored text.

## Deliverables and order

| # | Deliverable | Where | Status |
| --- | --- | --- | --- |
| 1 | Pack v2: phase-ordered prompt + gated verdicts + credit comment (own-words, Apache-2.0) | `unified-ai-review-prompts` PR #2 (feat/security-pack-v2) | BUILT 2026-08-24, awaiting criticalsec approval |
| 2 | Self-review observes deliverable 1's PR — first live harness-repo-5 evidence; also behavioral proof of org-scoped keys | automatic on PR #2 (self-shims already on prompts main, so the FULL loop fires on this PR) | **EVIDENCE IN 2026-08-24**: first self-review verdict posted on PR #2 — Grok seat delivered 4 real findings against the v2 rewrite itself (packs/** blind spot, dropped specifics, under-reporting bias, hidden-comment credit), all fixed in amendment 774c505. OpenAI seat ABSENT: project spend cap reached (insufficient_quota) — the budget wall + Seats Fail Loud both working; George raises the cap at platform.openai.com → Limits. |
| 3 | George: criticalsec approval on the pack PR (CODEOWNERS `*`) | prompts repo | TODO |
| 4 | Pin bumps: tap shim `prompts-ref` → v2 SHA; harness self-shims machinery+prompts pins (clears the recorded lag) | tap promote + one PR per harness repo | TODO |
| 5 | Key-rotation cleanup — **TRIGGER FIRED 2026-08-24** (org keys behaviorally proven on PR #2: xAI seat green end-to-end; OpenAI key authenticated, blocked only by the spend cap): delete tap repo-level OPENAI/XAI keys, revoke old vendor keys (keep `*-org-2026-08-23`) | George + one gh call each | READY — George's clicks |
| 6 | Spec: ledger entry for the ToB import landing; flip harness-repo-5 Proposed→Implemented on deliverable 2's evidence; record second-opinion item as satisfied-by-design | tap `specs/spec-cicd-ai-review.md` | TODO |
| 7 | Companion: agentic-actions-auditor nine-vector pass against `ai-review*.yml` + both harness workflow sets; findings (or clean bill) recorded here | this doc + fixes as needed | TODO |

## How we judge v2 (against v1, over the observation window)

- **Fewer unhedged false positives**: a wrong finding must at least arrive capped-at-medium with
  its refutation attempt visible (tap#117 is the baseline case).
- **No lost recall on the money findings**: the #108 catches (default-branch gap, behind-state)
  and the three-way #99 convergence (PR-edits-its-own-review-path) are the regression suite —
  v2 must still surface all of them. Before/after check: rerun both diffs through the v2 prompt
  locally (one-off API calls, not CI) and compare.
- **Verdict readability**: the phase-A ranking line + settling-evidence lines make triage faster
  for the human, per George's read of the next few real PRs.

## Rollout risk

Low. Prompt-only; both seats keep the same input contract and output shape; v1 remains one
`prompts-ref` pin-revert away (the pin IS the rollback mechanism — one line in each consumer
shim). The pack PR itself gets two-seat review under v1 before v2 takes effect anywhere.
