# Review Readiness: Structured Evidence And A GitHub Merge Gate

## Philosophy

**Draft for discussion. All requirements and acceptance criteria are Proposed.**
This document does not authorize implementation, enable blocking, or change repository rules.

A merge should depend on evidence that the current change received its required reviews and
that the resulting obligations were settled. A reminder cannot establish that. Neither can a
later comment, a Markdown heading, or an agent's assertion that it read the review.

GitHub enforces the merge condition. The review harness publishes structured evidence and a
deterministic evaluator computes readiness. Local tools explain the result. TAP observes it.
This establishes an attributable decision, not proof that a reviewer or triager was correct.

### Placement, Demand, And Existing Contracts

The [unified-ai-review README](https://github.com/unified-systems-com/unified-ai-review#design-provenance)
names TAP's [AI review spec](spec-cicd-ai-review.md) as its governing specification. This companion
elaborates `req-cicd-ai-review-gate`, `req-cicd-ai-review-verdict-ledger`, and
`req-cicd-ai-review-graduation`; machinery implementation belongs in `unified-ai-review`.

Tracking context: [tap#390](https://github.com/unified-systems-com/tap/issues/390).
This is a proposed replacement for that issue's shell gate / comment-timestamp design, not a
claim that its current done-test has been met. Related proposals:
[tap-dev-hooks#2](https://github.com/unified-systems-com/tap-dev-hooks/pull/2) and
[tap#392](https://github.com/unified-systems-com/tap/pull/392).
No issue, sprint commitment, or existing PR is changed by this draft.

The active [git-serious-self step](../plan/road-products.md#step-products-git-serious-self)
asks us to understand our own CI/CD through a running console. Explicit review obligations make
that state observable. Building the collector and console is subsequent work, not part of this
gate's first implementation.

**Existing policy remains authoritative until amended:** security high/critical findings block;
hygiene advises; graduation requires observed calibration; standing bypass lists remain empty.
The broader medium/all-findings triage in tap#390 is an unresolved policy difference. This draft
does not silently replace the existing threshold or introduce a maintainer-only bypass.

## Goals And Scope

| Goal | Observable result |
| --- | --- |
| Review the right change | Evidence identifies repository, PR, exact head, policy, and review generation. |
| Know what is missing | Pending, absent, failed, stale, and unresolved are distinct reasons. |
| Make triage attributable | Each disposition identifies the finding, actor, reason, and evidence. |
| Enforce at GitHub | Browser, CLI, API, and auto-merge obey the same required check. |
| Make operation legible | A maintainer can follow each blocker to its evidence and next action. |

First slice: one structured review contract, one disposition contract, one deterministic evaluator,
one GitHub check, and behavioral enforcement proof on a selected repository.

Non-goals: interpreting arbitrary discussion; proving a dismissal is substantively correct;
autonomous remediation or acceptance of risk; replacing human approval rules; a general policy
engine; matching findings across commits; a new TAP subsystem; UI or collector implementation;
automatically granting blocking authority to third-party review comments.

## Proposed Flow

1. A trusted controller resolves PR identity and selects policy from the protected configuration.
   It creates a review generation and establishes a non-success readiness state.
2. The existing unprivileged capture / privileged review separation produces seat results.
   The privileged stage continues to treat PR content as data and never executes it.
3. The harness validates and retains a structured review result. The readable review is rendered
   from that result, so the gate and the comment describe the same findings.
4. A triager deliberately submits dispositions through an authenticated interface. The controller
   validates identity, authority, schema, and exact evidence references before accepting them.
5. The evaluator reads an authoritative snapshot and publishes `review-readiness` for the exact
   applicable commit. Its summary names blockers and links to evidence and triage actions.
6. GitHub permits merging only when the required check and all other repository rules are met.

## Requirements

| RID | Name | Status |
| --- | --- | :---: |
| req-cicd-readiness-evidence | Structured review evidence | Proposed |
| req-cicd-readiness-disposition | Explicit finding dispositions | Proposed |
| req-cicd-readiness-evaluation | Deterministic readiness decision | Proposed |
| req-cicd-readiness-enforcement | Trusted GitHub enforcement | Proposed |
| req-cicd-readiness-lifecycle | Freshness, retries, and retained history | Proposed |
| req-cicd-readiness-operation | Rollout and operator experience | Proposed |

### Structured Review Evidence

RID: `req-cicd-readiness-evidence`

Status: `Proposed`

#### Implementation

The harness owns versioned JSON Schemas for policy, review results, and dispositions. They ship
with their loaders and validation in the implementing change. This document describes contracts;
it introduces no executable format or unvalidated data file.

| Result field | Required meaning |
| --- | --- |
| Schema version | Explicit supported contract version; unsupported versions are invalid. |
| Repository ID and full name, PR number | Stable identity plus readable presentation; names alone are insufficient. |
| Head SHA and reviewed base SHA | Exact change context; policy specifies when a base change invalidates review. |
| Generation, run ID, and attempt | Trusted identity for this review execution; timestamps do not select authority. |
| Policy digest and machinery/prompt revisions | Exact required seats, applicability, and decision policy used. |
| Seat records | Seat/model identity and `pending`, `completed`, `failed`, or `absent`, with failure reason. |
| Findings | Unique IDs within generation/seat, category, severity, explanation, location, and evidence links. |
| Coverage | Reviewed scope and any truncation/exclusions; incomplete required coverage cannot appear clean. |

Blocking status is derived by trusted policy from validated finding attributes, not freely chosen
by the model. Policy also defines applicability/exemptions and authorized triagers. A PR cannot
change the policy applied to itself. Required seat identities come from that policy, not from
whichever responses happened to arrive. No required-seat set means invalid policy unless the
policy explicitly declares the change exempt.

An empty findings list means clean only after every required seat completed with valid output
and required coverage. A failed/malformed result is never normalized to an empty list.
Unrelated bot comments, native approvals, and prose summaries are not substitutes for this contract.

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-cicd-readiness-evidence-1 | Validated contracts | Proposed | Reject missing fields, unsupported versions, duplicate finding IDs, malformed seat output, and policy/result identity mismatches. |
| req-cicd-readiness-evidence-2 | Complete means complete | Proposed | Missing required seats or truncated required coverage cannot produce clean readiness, even when the available findings list is empty. |
| req-cicd-readiness-evidence-3 | One source | Proposed | Rendered finding IDs/severities and evaluator inputs derive from the same validated result; a clean unrelated bot comment changes neither. |

### Explicit Finding Dispositions

RID: `req-cicd-readiness-disposition`

Status: `Proposed`

#### Implementation

A disposition contains repository/PR/head, review generation, finding ID, disposition type,
nonempty reason, evidence references, authenticated actor ID, and controller receipt identity/time.
The controller derives actor identity from authentication; it never trusts an `actor` supplied
inside the submitted payload. A team membership or repository role authorizes actions only when
the protected policy explicitly says so. Ownership custom properties confer no authority.

| Disposition | Meaning | Effect on readiness |
| --- | --- | --- |
| `fixed` | Identifies a candidate fix commit and verification evidence. | Does not itself clear the finding; a review of the changed head must establish readiness. |
| `dismissed` | Claims the finding does not apply, with reason and evidence. | Clears this finding only when actor and disposition are permitted by policy. |
| `accepted-risk` | Explicitly accepts the finding's residual risk, with rationale/evidence. | Clears this finding only when policy permits that actor to accept this class of risk. |

Submission is explicit and machine-validated; arbitrary PR comments do not count. A batch may
submit several dispositions, but each finding has its own record. Reject the whole submission
when any entry is invalid or stale. No automatic cross-head or cross-generation carry-forward.
Corrections append a superseding record; accepted records are not edited in place.

A missing seat is a coverage failure, not a finding someone can dismiss. Recovery requires a
successful review or the separately governed exception path.

Authentication proves which account acted, not whether a human or an agent used its credentials.
Do not label a disposition human approval merely because the account is not a bot.

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-cicd-readiness-disposition-1 | Deliberate decision | Proposed | A later "rebased" comment leaves all findings unresolved; a valid disposition affects only its named finding. |
| req-cicd-readiness-disposition-2 | Authority and scope | Proposed | Reject forged actors, unauthorized actors/types, unknown findings, stale generations, and mismatched heads. |
| req-cicd-readiness-disposition-3 | Fix verification | Proposed | A `fixed` record without a fresh review cannot clear a blocker; a new head is evaluated independently. |

### Deterministic Readiness Decision

RID: `req-cicd-readiness-evaluation`

Status: `Proposed`

#### Implementation

The evaluator is a small pure function over validated policy, current PR identity, selected review
generation, and accepted dispositions. Fetching and publishing live outside it. It returns state,
reason codes, unresolved finding IDs, missing seats, and evidence references. It performs no LLM
call, Markdown parsing, shell-command recognition, or timestamp-based inference of acknowledgement.

| Condition | Domain state | GitHub publication |
| --- | --- | --- |
| Review queued or required seats still running | `pending` | Non-completed check; never success. |
| Absent/failed seat, invalid evidence, unavailable authority, or exhausted timeout | `blocked` | Failure with explicit reason. |
| Evidence belongs to an old head/policy/generation | `stale` | Non-success; request the applicable review. |
| Blocking finding lacks an allowed disposition | `blocked` | Failure with finding links. |
| Required reviews complete and all blocking obligations settled | `ready` | Success. |
| Explicit policy exemption, evaluated by trusted controller | `exempt` | Success with policy and exemption evidence. |

Nonblocking findings remain visible in summaries. They do not become mandatory dispositions
unless an approved policy change makes them so. Success means the declared policy is satisfied,
not that the PR is secure or that all reviewers agreed.

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-cicd-readiness-evaluation-1 | Decision matrix | Proposed | Table-driven cases cover every state, including missing data, mixed seat outcomes, partial dispositions, and explicit exemption. |
| req-cicd-readiness-evaluation-2 | Reproducible verdict | Proposed | Identical authoritative inputs produce identical decisions, independent of fetch order and unrelated comments. |

### Trusted GitHub Enforcement

RID: `req-cicd-readiness-enforcement`

Status: `Proposed`

#### Implementation

The adopting repository requires `review-readiness` on its protected target branch. Publishing
authority is separate from model execution and PR-authored code. The controller uses trusted,
pinned machinery and derives PR/artifact provenance from GitHub's authenticated event/API data.
Artifact contents cannot nominate another PR, trusted producer, or successful review generation.

The publisher receives only permissions needed to read evidence and publish the check; model
workers receive no check-publication, merge, repository-content-write, or rules-administration
credentials. Disposition submission grants no merge authority.

The deployment must prove that an untrusted PR workflow cannot publish an accepted lookalike
check. Selecting the GitHub Actions App as expected source does not by itself identify one trusted
workflow. Choose and verify a sufficiently isolated publisher or supported required-workflow
mechanism before enabling enforcement; a new App is not authorized by this draft.

Do not represent failure/absence using `neutral` or `skipped`: GitHub can accept those conclusions
for required checks. A missing controller must leave the required context unsatisfied. Test actual
merge refusal, not merely the presence of a ruleset entry or a red workflow job.

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-cicd-readiness-enforcement-1 | Merge refusal observed | Proposed | On a fixture PR, observe refusal through browser, CLI/API, and auto-merge with unresolved findings or missing evidence; observe eligibility after legitimate settlement. Other checks remain independently enforced. |
| req-cicd-readiness-enforcement-2 | Producer integrity | Proposed | A same-named check from an unauthorized producer or PR-controlled workflow cannot satisfy the rule. |
| req-cicd-readiness-enforcement-3 | Failure paths | Proposed | Missing workflow, cancelled run, skipped seat, API failure, malformed artifact, and insufficient permissions cannot yield accepted success. |

### Freshness, Retries, And Retained History

RID: `req-cicd-readiness-lifecycle`

Status: `Proposed`

#### Implementation

Reconcile on PR open/reopen, head changes, relevant base/policy changes, review completion,
explicit reruns, and disposition acceptance/supersession. Select generations through trusted
controller state; never choose whichever successful result completed last. Record superseded
generations and retry attempts. Replayed events are idempotent.

Before publishing success, re-read applicable PR/policy/generation state and reject an outdated
evaluation. Serialize generation selection and publication for each PR. A slow old run must not
overwrite the result of a newer run. Starting a same-head rerun must invalidate prior readiness
before admitting that rerun; a failed rerun must not expose a previous success as current.

GitHub events and check updates are asynchronous. The implementation must document and test the
remaining merge race around same-head invalidation and policy changes. It must not claim atomic
merge-time enforcement from event handling alone. Resolving this is a rollout blocker.

For merge queues, bind results to the actual merge-group context and handle `merge_group` events;
individual PR-head success cannot simply be relabelled as group success. Queue use is unsupported
until this is implemented and behaviorally verified, and that constraint must be checked at rollout.

Retain accepted results, dispositions, policy identities, and decision history beyond mutable PR
comments. Define the storage and retention policy before implementation. Expired/deleted evidence
is unavailable, not clean; TAP ingestion is not a prerequisite or the sole authoritative store.

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-cicd-readiness-lifecycle-1 | Stale success refused | Proposed | A new head, superseding generation, or applicable policy change prevents old evidence from establishing current readiness. |
| req-cicd-readiness-lifecycle-2 | Concurrency | Proposed | Out-of-order completions, duplicate events, and a failed same-head rerun cannot restore superseded success; test the publication/merge race explicitly. |
| req-cicd-readiness-lifecycle-3 | Retention and queues | Proposed | Missing retained evidence blocks; enabled merge queues either pass dedicated group tests or prevent rollout. |

### Rollout And Operator Experience

RID: `req-cicd-readiness-operation`

Status: `Proposed`

#### Implementation

| Owner | Work |
| --- | --- |
| `unified-ai-review` | Schemas, structured outputs, authenticated disposition interface, evaluator, trusted publication, history, and reusable integration tests. |
| Adopting repositories / org governance | Protected policy, pinned integration, required-check configuration, authorized triagers, and enforcement verification. |
| TAP development tooling | Read/display readiness; update close-out procedure and the Validation Map when implemented. |
| `tap-dev-hooks` | Optional thin explanation of GitHub readiness; no authoritative local verdict or environment-variable bypass. |
| `github_core` (follow-on) | Collect readiness/evidence with source identity and freshness, through a declared contract. |
| `double-tap` (follow-on) | Present blockers and next actions across repositories, weighted by importance. |

First implement and observe advisory readiness using the same evaluator. Measure false positives,
review latency, missing-seat frequency, and triage burden. Resolve the decisions below and obtain
the existing spec's recorded graduation decision before requiring the check on a selected repo.
Expand only after the behavioral acceptance tests are observed there. This is not fleet-wide
configuration authorization.

Retain empty standing bypass lists. An emergency exception uses the existing governed break-glass
procedure, with actor, reason, exact PR/head, missing obligations, and actual merge outcome recorded.
It remains visibly an exception; no synthetic clean review or `TAP_PR_MERGE_GATE=off` can satisfy
the GitHub check. Any new exception authority requires an explicit policy amendment.

The check summary answers: what was reviewed, what policy applies, what blocks merging, and what
action will resolve it. Link directly to a finding, rerun, or disposition interface. Permission
and fetch failures say unknown/unavailable, never "no findings".

#### Acceptance Criteria

| ACID | Title | Status | Description |
| --- | --- | :---: | --- |
| req-cicd-readiness-operation-1 | Measured graduation | Proposed | Activation cites calibration evidence and resolved decisions; the Validation Map records the observed guard, not just its declaration. |
| req-cicd-readiness-operation-2 | Explainable exceptions | Proposed | A break-glass merge retains its missing obligations and actor/reason; local environment changes cannot turn the server check green. |
| req-cicd-readiness-operation-3 | Maintainer walkthrough | Proposed | An operator follows a blocker to evidence, submits an allowed disposition, and observes recomputed readiness without reading implementation code. |

## Decisions Required Before Build / Rollout

These are unresolved design questions, not approved sprint work. The document can be reviewed
now; an implementation issue must settle its applicable questions before entering a sprint.

| Decision | Recommendation / constraint |
| --- | --- |
| Blocking versus triage scope | Preserve security high/critical blocking initially. Explicitly decide whether medium or other findings require acknowledgement; amend the governing spec if broadening. |
| Disposition authority | Define permitted actors and disposition types in protected policy; use the same procedure for author and maintainer. Decide whether agents acting through personal credentials may accept risk. |
| Publisher isolation | Verify the organization's available GitHub enforcement mechanisms; demonstrate rejection of same-App lookalike checks before selecting the deployment. |
| Submission and evidence storage | Prefer an authenticated GitHub-native workflow interface and controller-owned, schema-validated records. Select exact transport, append/supersession behavior, retention period, and recovery path. Ordinary comments alone are insufficient. |
| Same-head rerun and policy-change races | Prove the check lifecycle against GitHub's real merge behavior; narrow the guarantee or change the mechanism if stale success can still authorize a merge. |
| Base changes and merge queues | Define reviewed-diff freshness and confirm queue use. Do not enable on queue-protected branches without merge-group support. |
| Graduation and pilot | Select one adopting repository and cite calibration evidence. No standing bypass actor is added for convenience. |

## Relationship To Existing Work

On approval, amend tap#390's implementation plan/done-test and the relevant gate/graduation
requirements together; the two designs must not remain competing canon. Retire timestamp-based
`--assert-answered` authority as consumers move to readiness. Keep any useful review-listing and
watch functionality. Adapt the local hook only after the server check is real.

No runtime, collector, workflow, schema artifact, or repository setting is changed by this draft.

## GitHub Constraints Consulted

- [Troubleshooting required status checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks): accepted conclusions, expected producer, and merge-group triggering.
- [Available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets): required checks, expected App source, and required workflows.

## Status Vocabulary

`Proposed` means designed for review, not accepted for implementation. `Approved for Development`
requires resolved design questions. `Implemented` requires landed machinery. `Verified` requires
observed acceptance evidence, including actual GitHub merge enforcement.
