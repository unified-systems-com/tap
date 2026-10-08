# 2026-09-29 — Absent is not failed: a conformance check instructed an eight-repository outage

## 1. Goal vs. Outcome

**Goal:** close a gap the conformance checker could not see — eleven plugin repositories had no
release-SBOM lane, so a first release would publish an unattested wheel.

**Outcome:** the gap was closed, and on the way we discovered that a *different* check in the same
file had already caused a live outage: eight of twenty-four plugin repositories had no working CI for
roughly two hours, because a session correctly followed that check's own instruction. Three separate
tools reported the broken fleet as healthy, including two written the same day by the people
diagnosing it.

## 2. Timeline

All times UTC, 2026-09-29.

| Time | Event |
| --- | --- |
| 21:15 | A session opens `fix/drop-stale-contents-write-grant` across plugin repositories, citing `repo-caller-permissions` as the source of the finding. |
| 21:16-21:22 | Merged. Eight repositories' caller job grant becomes `{security-events: write}` alone. Every `ci` run in those eight is `startup_failure` from this point: zero jobs, no log. |
| 21:42 | An unrelated pass opens eleven release-lane PRs. Seven land in the broken eight. |
| ~21:45 | The break is noticed — not by a red check, but because `okta-tap#24` showed six checks where `dcom-tap#18` showed eight. |
| ~21:50 | Diagnosed: a job-level `permissions:` block REPLACES the workflow-level grant rather than merging with it, so a block naming only `security-events` grants no `contents`, and `plugin-ci.yml` has two jobs declaring `contents: read`. |
| ~21:55 | A first audit by `grep` reports all 24 repositories healthy — it had matched the workflow-level `contents: read`, not the job block. Re-audited by parsing: 8 broken, 16 healthy, matching the 8 failures exactly. |
| ~22:00 | bom-bom, holding the fix, discloses that its own merge gate counted *non-passing* checks, so an absent check set read as clean, and it had merged two PRs on no CI at all. |
| ~22:05 | bom-bom finds the root of the root: `test_the_narrow_grant_passes` asserted the broken shape conformant. |
| ~22:10 | The check is corrected; run against all 24 real `ci.yml` files it fails exactly the eight, no false positives, none missed. |

## 3. What Went Well

- **The break was found by a discrepancy, not a signal.** Nothing alerted. It surfaced because two
  PRs in the same batch had different check counts, and somebody asked why.
- **Every diagnostic claim was re-derived rather than relayed.** Two sessions independently parsed all
  twenty-four `ci.yml` files and arrived at the same eight.
- **Both sessions disclosed their own tooling's blindness unprompted.** bom-bom volunteered that its
  merge gate had merged on no CI; this session volunteered that its eleven-PR watcher had the same
  defect, written *after* diagnosing bom-bom's.
- **The fix was sequenced correctly once understood.** Eleven release-lane PRs were held rather than
  merged on a check set that could not exist, and the fleet is being made conformant before the check
  that demands it merges.
- **The pre-push hook did its job.** It refused a commit with no issue trailer, and the fix was local
  rather than `--no-verify`.

## 4. What Went Wrong

- **A conformance check told a reader to do the thing that broke production.** Its over-grant warning
  said to remove `contents: write` "in the same change that adds `security-events: write`". Followed
  literally — the only way to read it — that produces the failing grant.
- **A test asserted the failing shape was conformant**, under the name
  `test_the_narrow_grant_passes`. The name is the defect in miniature: narrowness was treated as the
  goal, and nobody asked what the callee needs.
- **A constant's comment stated a falsehood** — "the single permission a caller of the reusable lane
  needs" — which is what the message and the test were both derived from.
- **Three separate tools read the broken fleet as healthy**, each for the same reason: they counted
  failures, and a startup failure produces no failed checks at all.
  1. `gh pr checks` — omits checks that never existed rather than reporting them.
  2. bom-bom's merge gate — counted non-passing checks; an empty set passed.
  3. this session's eleven-PR watcher — counted pending and failed; reported all eleven clean.
- **A `grep`-based audit gave a confident wrong answer** (24 healthy) by matching the workflow-level
  grant instead of the job block.
- **A link checker built during the same session reported a live directory as dangling**, because it
  enumerated `git ls-tree -r`, which lists files and never directories — and the false finding was
  acted on, replacing a correct `postmortems/` reference with `aar/` and conflating two deliberately
  distinct corpora.
- **The first attempt at the fix reproduced the original error's shape**, treating an absent job block
  as "grants nothing" when an absent block inherits.

## 5. Root Causes

Blameless and plural. The session that broke the fleet did exactly what it was told.

1. **The check modelled one required scope when the callee declares two.** Everything downstream — the
   constant's comment, the warning's wording, the test's name and assertion — is a faithful expression
   of that single wrong premise. This is the primary cause.
2. **`permissions:` replace-not-merge semantics were never encoded anywhere.** The checker, its tests
   and its docstring all read as though a job block added to the workflow grant. GitHub's actual rule
   is replacement, and that rule is the difference between a narrow grant and no grant.
3. **Absent and failed were conflated at three independent layers.** Not one bug: a platform
   behaviour (`startup_failure` yields no checks), plus two gates that asked "did anything fail?"
   instead of "is what I require present and passing?". The question is the defect, not the code.
4. **A conformance finding was treated as an instruction.** The check said what to remove and named
   only one scope to keep; a reader reasonably inferred the complement. A check that prescribes a fix
   owns the correctness of that prescription.
5. **Text-matching stood in for parsing at two points** — the grant audit and the link audit — and
   both produced confident, wrong, *reassuring* answers. Reassuring is the dangerous direction.
6. **Repository-scope checks read files, so no file-reading check can ever see this class of failure.**
   The nightly fleet sweep is green on eight repositories that cannot run CI. That is not a defect in
   the sweep; it is a boundary nobody had stated.

## 6. Impact

- **Eight repositories with no CI for ~2 hours**: okta, duo, teleport, gitlab, gruntwork,
  deployment-environment, project-management-core, gryphon-playground.
- **Two PRs merged with no CI at all** (`project-management-core-tap#16`, `gruntwork-tap#17`), each a
  one-line deletion, both on a gate that read absent as clean.
- **Eleven release-lane PRs blocked**, seven of them unverifiable until the grants are repaired.
- **No production or data impact.** The affected lanes are CI only, nothing was released, and the
  wheels and grid were untouched.
- **One incorrect docs change made and reverted within the same session** (the `postmortems/` link).

## 7. Corrective / Preventive Actions

- [x] `REQUIRED_CALLER_GRANT` becomes the *set* the callee needs: `contents: read` **and**
      `security-events: write`.
- [x] The over-grant message says **narrow to `contents: read`**, never "remove", and states the
      replace-not-merge rule inline where a reader will hit it.
- [x] A missing `contents` **fails** rather than warns — it is a refusal today, not a ratchet.
- [x] Inheritance modelled explicitly (`_workflow_permissions`): an absent job block inherits; a
      present one replaces. The two states are never collapsed.
- [x] `test_the_narrow_grant_passes` inverted into `test_security_events_alone_fails`, named as the
      regression it is, plus a test asserting the *wording* says narrow rather than remove.
- [x] Verified against the live fleet in both directions: exactly the eight fail, zero false
      positives, zero missed.
- [x] `req-tap-plugin-validate-repo-8` rewritten and renamed "Caller Grants Every Permission The Lane
      Needs", carrying this incident as its rationale.
- [x] The eight grants repaired (bom-bom), paced, with okta as the pilot.
- [x] bom-bom's merge gate now requires the `tap /` checks to be **present and passing**.
- [ ] **This session's PR watcher must assert presence, not absence of failure.** Written, diagnosed,
      and still wrong at the time of writing — the honest state.
- [ ] **A check that can see a startup failure.** No file-reading check can. Candidate: the fleet
      sweep also reads each repository's most recent default-branch `ci` conclusion, so `startup_failure`
      becomes visible somewhere.
- [ ] **A guard that a prescriptive check's prescription is tested.** Where a message tells the reader
      what to change, a test should assert that following it yields a conformant repository.

## 8. Lessons → Durable Rules

- **Absent is not failed.** Any gate that decides on "did anything fail?" is blind to a whole class of
  outage. The question must be "is what I require present and passing?". Three tools got this wrong in
  one afternoon, two of them written by the people diagnosing the first.
- **A check that prescribes a fix owns that fix.** Prescriptive wording is an instruction, and a
  faithful reader following it is not the failure — the wording is.
- **A test named for the property you want will happily assert the bug.** `test_the_narrow_grant_passes`
  tested narrowness, which was the goal, instead of sufficiency, which was the requirement.
- **Grep for a reassuring answer, parse for a true one.** Both text-matched audits in this incident
  returned "everything is fine" and both were wrong; a tool that cannot see a category of thing
  reports its absence as a finding.
- **State a checker's boundary in the checker.** "These checks read files" implies "these checks
  cannot see a run that never started" — which needed saying before it mattered, not after.
