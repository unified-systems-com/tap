# TAP per-product-line CI runners (AWS CodeBuild)

Terraform for the per-product-line CI lanes (spec-dev-validation.md
`req-dev-validation-product-line-lanes`). Each product line (a boot profile) gets one
AWS CodeBuild project that registers as a **GitHub Actions self-hosted runner**. The
lane itself lives in `.github/workflows/product-lines.yml`; this module provisions the
compute + identity it runs on.

**Retired.** No workflow runs on these runners any more. The lane keys below (`test_all`,
`samsite`) name the resources still deployed in account 180731181784 and are kept so the
module matches them until the teardown; neither boot profile exists in tap now (the union
was retired with tap#638, samsite moved to its own repository).

## Why CodeBuild (not an EC2 fleet, not a SaaS runner)

Managed AWS service (no AMI/NAT/autoscaler to own), EC2-mode compute supports
docker-in-docker (our compose stack needs it), and it runs **in our account** — so the
lane carries an IAM role for native Bedrock / `aws_core` STS testing (the capability
axis; no long-lived creds in GitHub secrets). Full evaluation:
`docs/misc/doc-dev-validation-ci-runner-strategy.md`.

## What it creates

- A CodeConnections **GitHub connection** (unless you supply an existing one).
- Per product line: a **CodeBuild project** (EC2-mode, privileged), a **webhook** on
  `WORKFLOW_JOB_QUEUED`, a **CloudWatch log group**, and a **per-line IAM role**
  (base: logs + connection + reports; capability: Bedrock, optional `aws_core` STS).

## Apply

Prereqs: Terraform ≥ 1.10 (native S3 state locking), AWS creds for the **aws_core account**
(us-east-1), `aws` CLI.

```bash
cd ci/terraform/codebuild-runners
cp terraform.tfvars.example terraform.tfvars   # optional — the defaults match production
terraform init                                 # configures the S3 backend
terraform plan
```

### Credentials gotcha

Terraform's AWS provider does **not** understand the newer `aws login` credential source
(`aws configure list` reporting `TYPE: login`) — it reports *"No valid credential sources
found"* even though the `aws` CLI itself works fine. Either use the SSO profile
(`AWS_PROFILE=aws_core`, needs a live `aws sso login`) or hand Terraform the CLI's
resolved credentials:

```bash
eval "$(aws configure export-credentials --format env)"
terraform plan
```

## State lives in S3 (`tap-ci-tfstate`)

State is in the `tap-ci-tfstate` bucket (versioned, SSE-S3, public access blocked,
TLS-only bucket policy) under key `codebuild-runners/terraform.tfstate`, with **native S3
locking** (`use_lockfile = true` — no DynamoDB table).

**Why, in one sentence:** this module's state was originally local to a dev worktree and
was *lost when that session was despawned*, leaving the CI infra live-but-unmanaged; the
recovery (2026-07-21) was a `terraform import` of all 16 resources.

The bucket is **bootstrap infra, deliberately not managed by this module** (it must exist
before `terraform init` can run). It is tagged `ManagedBy=manual-bootstrap`; the exact
`aws s3api` commands that create it are recorded in the `backend` comment in `versions.tf`.

### If state is ever lost again

Nothing is destroyed — the infra keeps running, it is just unmanaged. Re-import:

```bash
eval "$(aws configure export-credentials --format env)"
terraform init
CONN=$(aws codeconnections list-connections \
  --query "Connections[?ConnectionName=='tap-ci-github'].ConnectionArn" --output text)
terraform import 'aws_codeconnections_connection.github[0]' "$CONN"
for L in test_all samsite; do
  terraform import "aws_cloudwatch_log_group.line[\"$L\"]"   "/codebuild/tap-ci-$L"
  terraform import "aws_iam_role.line[\"$L\"]"               "tap-ci-$L-role"
  terraform import "aws_iam_role_policy.base[\"$L\"]"        "tap-ci-$L-role:base"
  terraform import "aws_iam_role_policy.capability[\"$L\"]"  "tap-ci-$L-role:capability"
  terraform import "aws_iam_role_policy.plugin_pull[\"$L\"]" "tap-ci-$L-role:plugin-pull"
  terraform import "aws_codebuild_project.line[\"$L\"]"      "tap-ci-$L"
  terraform import "aws_codebuild_webhook.line[\"$L\"]"      "tap-ci-$L"
done
terraform import 'aws_secretsmanager_secret.github_plugins_ro[0]' 'tap-ci/github-plugins-ro'
```

Then `terraform plan` should report **0 to add, 0 to destroy**. Two attributes are not
readable back from the API and so always show as an in-place change until applied once:
`aws_secretsmanager_secret`'s `recovery_window_in_days` (a delete-time parameter) and
`force_overwrite_replica_secret`. Applying them mutates state only, not the live secret —
and never its value (see `secrets.tf`).

### The one interactive step (unavoidable)

CodeConnections requires a human to authorize the GitHub App once:

1. First `apply` with `codeconnection_arn = ""` creates the connection **PENDING**.
2. AWS console → **Developer Tools → Settings → Connections** → select
   `tap-ci-github` → **Update pending connection** → install/authorize the AWS
   Connector for GitHub on `unified-systems-com/tap`.
3. (Optional) paste the now-authorized ARN into `terraform.tfvars` as
   `codeconnection_arn` so future applies reuse it explicitly.

Until authorized, projects exist but builds cannot fetch the repo.

## Wire the workflow

`terraform output runner_labels` prints the exact `runs-on` label per line. They match
`.github/workflows/product-lines.yml` (`codebuild-tap-ci-<line>-…`) as long as
`name_prefix` stays `tap-ci` and the `product_lines` keys match the workflow matrix.
**Adding a line = add a `product_lines` entry here AND a matrix entry in the workflow.**

## Scope down before real use

- Replace `Bedrock` / `sts` `resources = ["*"]` with specific model / role ARNs.
- ~~Consider an S3 state backend~~ — done 2026-07-21, see **State lives in S3** above.
- Add a budget alarm (out of scope of this module).

## Named open edges (deliberately not closed here)

- **`.terraform.lock.hcl` is gitignored**, so provider versions are resolved fresh per
  checkout rather than pinned by hash. Committing it is the standard supply-chain edge
  (reproducible provider selection); left as-is to avoid changing the repo's terraform
  ignore convention inside an unrelated change.
- **The state bucket has no lifecycle rule** expiring noncurrent versions, so state
  history grows unbounded. Negligible at this size; name it, don't build it.

## Caveats (first draft — validate on apply)

- The `source.auth { type = "CODECONNECTIONS" }` wiring can vary by AWS provider
  version. The load-bearing requirement is an **authorized** CodeConnections GitHub
  connection in the account; if the provider rejects the inline `auth`, drop it.
- Confirm the chosen `codebuild_image` ships Docker + `docker compose` v2.
