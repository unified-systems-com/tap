---
title: AWS Cross-Account Collection — Activation Runbook (Sam handoff)
date: 2026-07-08
status: handoff
audience:
  - developer
  - llm
spec: plugins/aws_core/specs/spec-aws-core-secrets.md
related_docs:
  - plugins/aws_core/tap_plugin/aws_core/collectors/boto3_collector/handoff/README.md
---

# AWS Cross-Account Collection — Activation Runbook

The engineering for cross-account AWS collection is **built and on `main`**; what
remains is the **operational activation** with the partner (Sam) and the **first
live verification**. This doc is the parked next-steps checklist so that work is
not lost. It is the operator/human procedure; the in-package
[`handoff/README.md`](../../plugins/aws_core/tap_plugin/aws_core/collectors/boto3_collector/handoff/README.md)
is the detailed partner-facing runbook + the artifacts, and
`spec-aws-core-secrets.md` (the `aws_assumed_role` secret requirement, aws_core plugin repo) is the contract.

## Where this stands (already done, do NOT redo)

- `aws_assumed_role` secret kind + STS AssumeRole path (mandatory External ID,
  assert-on-land, audited assume) — shipped in `tap-plugin-aws-core` **v0.1.1**
  and the monorepo copy; `samsite.boot.json` pins aws_core to `v0.1.1`.
- Committed handoff artifacts under
  `plugins/aws_core/tap_plugin/aws_core/collectors/boto3_collector/handoff/`:
  `cross-account-role.yaml` (CloudFormation), `cross-account-role.tf` (Terraform),
  `collector-principal-policy.json` (our-side assume-only policy), `README.md`.
- **Not yet done:** the real IAM setup, the secret, and a live collection. The
  assume-role path has **never run against a real AWS role** — every test fakes STS.
  The done-test below is the true validation still owed.

## Prerequisites

- Admin (or IAM-write) access to **our** primary AWS account.
- A channel to Sam, who has admin on the **partner** account running the samsite
  next-iteration app.
- Access to `TAP_SECRETS_ROOT` (`~/tap-secrets`, the shared host mount — see the
  gotcha below).

## Steps

### 1. Mint the collector IAM principal (our account — one-time)

- Create IAM user **`tap-aws-core-collector`** in our primary account.
- Attach the inline policy in
  `handoff/collector-principal-policy.json`, replacing `<PARTNER_ACCOUNT_ID>` with
  Sam's account id. The role name is fixed (`TapAwsCoreCollectorReadOnly`, the CFN
  default), so the full role ARN is predictable and you can fill this in **before**
  Sam runs the stack (non-circular by design).
- Create an **access key** for the user → becomes the secret's `base` credentials.
- Record the user's ARN, e.g. `arn:aws:iam::<OUR_ACCT_ID>:user/tap-aws-core-collector`.

Because this user can do nothing but `sts:AssumeRole` on Sam's read-only role, a
leak of its key is low-value.

### 2. Generate the External ID (one-time, per partner)

- Mint an unguessable string, e.g. `python -c "import secrets; print(secrets.token_urlsafe(24))"`.
- Keep it with the secret (step 5); hand a copy to Sam (step 3). **Never** let Sam
  pick his own — the vendor mints it (confused-deputy guard).

### 3. Send Sam the onboarding bundle

- The **collector principal ARN** (step 1).
- The **External ID** (step 2).
- `handoff/cross-account-role.yaml` (default), or `cross-account-role.tf` if Sam
  already runs Terraform. Point him at the "What the partner does" section of
  `handoff/README.md`.

### 4. Sam creates the role and returns three things

From the CloudFormation stack Outputs (or Terraform outputs):

- `RoleArn` → `data.role_arn`
- `AccountId` → `data.expected_account_id`
- the **region(s)** samsite runs in → `data.regions_allowed`

Sam can inspect the read-only grant (`SecurityAudit`) before accepting, and revoke
by deleting the stack.

### 5. Wire the `aws_assumed_role` secret

Drop `aws_core/boto_collector.secret.json` under `TAP_SECRETS_ROOT`, kind
`aws_assumed_role` — the exact shape is in `handoff/README.md` ("Wire it into the
collector secret"). Minimum `data`: `role_arn`, `external_id`, `expected_account_id`,
`base: {access_key_id, secret_access_key}`, `regions_allowed`.

> **Gotcha:** `~/tap-secrets` is a shared host mount symlinked into every session —
> editing a `*.secret.json` mutates all sessions live. Coordinate before touching it.

### 6. Live-verify (the done-test)

Fire the aws_core `boto3` collector against Sam's account. Its `self_test` runs
**before** any collection and exercises the whole chain:

1. secret resolves + validates (kind `aws_assumed_role`, shape OK),
2. region scope present,
3. STS reachable → **AssumeRole with the External ID** → `GetCallerIdentity` →
   **assert-on-land** (resolved account == `expected_account_id`).

The collector fires via the population/boot path (the samsite profile seeds + fires
`aws_core:boto3`), or a targeted collector run. Confirm:

- the self-test checks are **green** against the live role (not the faked-STS unit tests),
- a real collection **imports AWS nodes** from Sam's account onto the grid, and the
  per-run `AWS_CALL_LEDGER` records the AssumeRole + the reads.

**Done when:** the self-test is green against Sam's live role AND a real collection
lands samsite's AWS resources on the grid.

## Deferred / related (see thread discussion — items 2 & 3)

_Pending a decision on whether these belong here or elsewhere:_

- **Spec ACIDs**: the `aws_assumed_role` secret requirement's 7 ACIDs (`spec-aws-core-secrets.md`, aws_core plugin repo) are `Proposed` —
  bump to Approved/Implemented on review.
- **Keyless/ambient base identity**: declared future branch (backlog) for when the
  collector runs on AWS compute (instance/task role) — drops the static base key.
- **Scripted plugin-release path** (`release-plugin.sh`): v0.1.1 was released
  direct-to-repo by hand; a scripted mirror+tag+boot-rev-bump is deferred. Captured
  as its own decision doc: [`doc-plugin-release-path-decision.md`](doc-plugin-release-path-decision.md).
