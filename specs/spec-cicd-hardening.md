# CI/CD Pipeline Hardening

## Philosophy

TAP's development pipeline reached a good place by instinct: trunk-based development, an
automated fail-closed gate before `main` advances, cloud CI on AWS CodeBuild, and a
parallelized promote (`~8 min`, gryphon corpus deferred to the cloud). Measured against
professional git/build/deploy practice, the **integration and testing** halves are
pro-grade to ahead of the field. What is missing is **enforcement** (the gate is a
client-side convention, not a server-enforced invariant) and most of the **deploy** half —
though no longer all of it: as of 2026-08-09 TAP publishes immutable, SLSA-attested
multi-arch images to GHCR on every main push (`req-cicd-build-once-artifact` /
`req-cicd-supply-chain-provenance`, both Partial). Still absent: environments, continuous
delivery, and the promote-the-same-bytes deploy discipline those images will feed.

This spec is a standing **doctrine + backlog**, in the same spirit as
[spec-security-posture.md](spec-security-posture.md): it states the guiding principles for
a professional CI/CD pipeline, records honestly where TAP already complies, and holds the
prioritized ladder of work to close the gaps. It is the thing a session "works through" —
requirement by requirement — to lock the pipeline down.

The core doctrine:

> A pipeline's guarantees must be **enforced where they cannot be bypassed** (server-side
> at the forge), **shifted left** (security and correctness caught at authoring/merge, not
> in production), and **built once and promoted** (immutable, versioned, signed artifacts
> move through environments — never rebuilt per environment). Measure the pipeline so its
> health is a fact, not a feeling.

The synthesizing insight that motivates most of this backlog: TAP's promote flow
**orchestrates the pipeline client-side, in a bash script** (`scripts/promote-to-main.sh`).
That script is genuinely sophisticated — atomic dual-refspec push, a transient-tolerant
CI join-poll, fail-closed gating — but because it runs on a laptop, its guarantees are a
*convention*: a direct `git push origin HEAD:main` bypasses every gate, and each session
runs its own copy of the script (they converge late). In effect TAP **hand-built a merge
queue.** The forge now ships that as a product (GitHub merge queue; Mergify; Bors), and
TAP's nearest neighbors — Backstage, Grafana, dbt, Supabase, Temporal, Hasura — nearly all
run *PR → required checks → merge queue → semver release → signed artifact*, server-enforced.
The strategic question this spec keeps live is **how long to keep hand-rolling versus
adopting forge-native primitives.** Hand-rolling buys offline capability, zero lock-in, and
total control (real assets for a solo, AI-driven flow); it costs server-side enforcement and
convergence consistency. Both are defensible — the point is to make it a *decision*.

This doctrine coexists with accepted, deliberately-deferred risk (see **Accepted Risk**
below). Pre-launch, with no customers and a solo maintainer, the deploy half is rightly
parked; this spec names it so it is tracked, not forgotten.

## What TAP Already Does Right

Named honestly so the doctrine measures against a real baseline, and so these are not
regressed while closing the gaps:

- **Trunk-based development** — short-lived session branches, frequent integration to one
  trunk. The model DORA/*Accelerate* identifies as the highest-performing.
- **Automated pre-merge gate, fail-closed** — red never advances `main`
  (`req-dev-validation-promote-hook`, `req-dev-multisession-ci-gate`).
- **Atomic pushes** — both refs advance or neither (`req-dev-multisession-push-workflow-3`).
- **Infrastructure as Code** — Terraform, state out of the repo, secret *shells* not values
  (`ci/terraform/codebuild-runners/`).
- **Least-privilege, per-lane IAM** — each CI lane grants only what it tests
  (`req-dev-validation-product-line-lanes-4`).
- **Secrets discipline** — none in the repo, a pluggable Secrets-Manager seam, health-probe
  validation (`req-tap-plugin-depres-sources`, [spec-tap-cares-secrets](../tap_cares/specs/spec-tap-cares-secrets.md)).
- **Dependency pinning** — `uv.lock`.
- **Environment parity** — one Docker image across dev and CI.
- **Testing depth ahead of the field** — the gryphon correctness ladder (differential
  oracle + metamorphic + fuzzing) and the honest, machine-generated
  [Validation Map](spec-dev-validation.md) (`req-dev-validation-map`).

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Enforce Server-Side | The gate must be un-bypassable at the forge, not a client-side convention. |
| 2. | Shift Security Left | SAST, dependency, secret, and container scanning run as a standing CI layer, not post-incident. |
| 3. | Build Once, Promote | Produce immutable, versioned, signed artifacts and move the *same* bytes through environments. |
| 4. | Deliver Continuously | Environments, progressive delivery, and rollback — the unbuilt deploy half. |
| 5. | Measure The Pipeline | Track the four DORA metrics and flaky tests; pipeline health is a fact, not a feeling. |
| 6. | Decide, Don't Default | Choose hand-rolled vs forge-native (merge queue) deliberately; don't drift into either. |

## Prior Art

Standard, current practice this spec draws on: **trunk-based development** and the **four
DORA metrics** (deployment frequency, lead time, change-failure rate, MTTR) from
*Accelerate*; **branch protection / required status checks / merge queues** (GitHub, GitLab,
Mergify, Bors); **shift-left security** — SAST (CodeQL, Semgrep, Bandit), SCA / dependency
audit (Dependabot, `pip-audit`, Renovate), secret scanning (gitleaks, trufflehog), container
scanning (Trivy, Grype); **build-once-deploy-many** and config-in-env (12-factor); **supply
chain** — SLSA provenance levels, Sigstore/cosign signing, CycloneDX/SPDX SBOMs; **progressive
delivery** (canary, blue-green). Nearest neighbors — Backstage (changesets, versioned plugin
releases), Grafana (signed plugins + catalog), dbt (PR-gated DAG tests), Supabase / Temporal /
Hasura — share the *PR → required checks → merge queue → semver → signed artifact* shape.
TAP's **boot-record-as-BOM** is conceptually *ahead* of the SBOM curve; this spec ties it to
the standard formats and signing the ecosystem expects.

## Requirements

Ordered as the recommended sequence: the first three are cheap, foundational, build-once
edges (an afternoon each) squarely in the [security-posture](spec-security-posture.md)
cheap-edge doctrine; the rest are the larger deploy-half build, rightly deferred toward launch.

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-cicd-base-image-sourcing | [Source Base Images Off Anonymous Docker Hub](#source-base-images-off-anonymous-docker-hub) | Implemented | Container base images resolve from AWS's credential-free public ECR mirror, not docker.io — removes the anonymous-pull `429` single point of failure on the promote gate. First cheap edge landed. |
| req-cicd-base-image-lifecycle | [Self-Host Base-Image Currency + Minimization](#self-host-base-image-currency--minimization) | Proposed | **Wolfi is the standard base** (`-3`, decided 2026-07-09; spike: OS-CVEs 311→0), carrying exactly TAP's runtime binaries, plus a self-hosted auto-patch loop + CVE gate instead of a managed hardened catalog. **FIPS is on by default** (`-6`), via the self-built OpenSSL 3.0 #4282 provider (`-5`, spike-proven end-to-end 2026-07-09), selected by `ARG TAP_FIPS=1` and asserted fail-closed at boot. Alternatives (DHI, UBI-micro) are **parked, not eliminated**. Docs: [doc-hardened-base-image-landscape](../docs/misc/doc-hardened-base-image-landscape.md) (landscape) · [doc-fips-assessment-record](../docs/misc/doc-fips-assessment-record.md) (FIPS decisions, lessons, verification suite). |
| req-cicd-branch-protection | [Enforce The Gate Server-Side](#enforce-the-gate-server-side) | Proposed | Protect `main` at the forge with a bypass for the promote identity; the gate stops being bypassable. Closes the biggest hole. |
| req-cicd-runner-least-privilege | [Runner Least Privilege](#runner-least-privilege) | Partial | Job = token boundary: read-only default token, explicit per-workflow grants, write scopes job-level only, no unannotated third-party co-tenancy with a write token, third-party actions SHA-pinned. Enforcement guard LIVE (`workflow-least-privilege`); tag ruleset (`-5`) the open tail. |
| req-cicd-dco-signoff | [DCO Sign-Off Enforcement](#dco-sign-off-enforcement) | Implemented | Auto-applied `Signed-off-by` trailer (versioned hook) + ENFORCING trailer check on both roads to main since 2026-08-12, when `CONTRIBUTING.md` + `DCO` landed at the repo root as approved policy. |
| req-cicd-security-scanning | [Shift-Left Security Scanning](#shift-left-security-scanning) | Partial | SAST + dependency audit + secret scan + container scan as a standing CI layer. All four live: gitleaks, Dependabot alerts, CodeQL, and Trivy (publish-time + nightly, report-only — the gate flip is the open tail). |
| req-cicd-dep-automation | [Automate Dependency Updates](#automate-dependency-updates) | Proposed | Dependabot/Renovate on `uv.lock` — pinned deps rot without it. |
| req-cicd-build-once-artifact | [Build Once, Promote The Artifact](#build-once-promote-the-artifact) | Partial | Immutable multi-arch images published to GHCR on main push (publish-images.yml); dev + CI pull instead of rebuilding. Deploy-side promote-the-same-bytes open (no environments yet). |
| req-cicd-supply-chain-provenance | [Sign Artifacts, Emit SBOM](#sign-artifacts-emit-sbom) | Partial | SLSA provenance attestations live on the published images; cosign signing, plugin-wheel attestations + CycloneDX/SPDX SBOM open. |
| req-cicd-product-releases | [Product Releases](#product-releases) | Proposed | Semver product releases carrying release notes; cutting the first release must update `SECURITY.md`'s supported-versions statement. Consumers pin a version via `.env` (`-3`, Implemented 2026-08-13) rather than tracking `:latest`. |
| req-cicd-continuous-delivery | [Continuous Delivery](#continuous-delivery) | Proposed | Environments (staging/prod), progressive delivery, and a rollback path. The unbuilt deploy half. |
| req-cicd-live-instance-testing | [Live Instances In CI For Operational Testing](#live-instances-in-ci-for-operational-testing) | Proposed | Stand up running TAP instances inside the CI process as targets for operational tests — API fuzzing (Schemathesis), write-path stateful fuzzing, DAST, live smoke. Generalizes the cold-boot gate from "boots healthy" to "operates correctly". |
| req-cicd-pipeline-observability | [Measure The Pipeline](#measure-the-pipeline) | Proposed | The four DORA metrics + systematic flaky-test tracking. |

### Source Base Images Off Anonymous Docker Hub

RID: `req-cicd-base-image-sourcing`
Status: `Implemented`
Trace: `non-python` — docker/postgres/Dockerfile

The promote gate's cloud CI (`product-lines.yml`, the `test_all` lane gating **every** promote
to `origin/main`) builds the web image on a GitHub Actions runner, and that build pulled its
base image **anonymously from `docker.io`**. GHA's hosted runners share a pool of egress IPs
across all of GitHub's customers, so Docker Hub's anonymous per-IP pull limit is frequently
already exhausted at push time → `429 Too Many Requests` on the manifest HEAD → `buildx` dies
in ~25s → the promote aborts. This is a **nondeterministic single point of failure on the
critical path to shipping anything** — not specific to any one change (it blocked a passkey
promote three times running, 2026-07-09), with no backpressure we control. Two base images
were exposed at the time: `python:3.14-slim` (`Dockerfile`) and `postgres:16-alpine`
(`docker-compose.yml`); both were later replaced by digest-pinned `cgr.dev/chainguard/wolfi-base`
(the 2026-07-21 Wolfi cutover + the 2026-08-09 digest pins), which is not a Docker Hub pull at all.

**Fix (the cheap, foundational edge):** resolve Docker Official Images through **AWS's public
ECR mirror** (`public.ecr.aws/docker/library/<image>`) — a credential-free mirror not subject
to Docker Hub's limit. Two one-line base changes; no new secret, no new infra; self-applying
(the commit that swaps the base is the commit whose CI uses it, so it lands through the gate
without a lucky retry) and it fixes local dev too. This is the `spec-security-posture.md`
cheap-edge play: near-zero marginal cost now, removes a class of availability failure.

| RID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-base-image-sourcing-1 | No anonymous Docker Hub base pulls | Implemented | No build/dev/CI base image is pulled anonymously from `docker.io`; all Docker Official Images resolve via `public.ecr.aws/docker/library/*`. | Originally `Dockerfile` (`python:3.14-slim`) + `docker-compose.yml` (`postgres:16-alpine`); since the Wolfi cutover both bases are digest-pinned `cgr.dev` pulls, satisfying this by construction. |
| req-cicd-base-image-sourcing-2 | Rate-limit-free promote gate | Implemented | The promote gate's image build no longer depends on Docker Hub's anonymous quota, so a shared-runner IP exhaustion cannot red the gate. | Removes the observed `429` SPOF. |

**Named residual (deferred, not hidden):** we still trust AWS's mirror rather than a copy we
pin and control, and tags are mutable. Full supply-chain control — a **private ECR pull-through
cache with digest-pinned bases** (and, later, hardened/minimized base images; see the
base-image-strategy survey) — is deferred and composes with `req-cicd-build-once-artifact` /
`req-cicd-supply-chain-provenance`. The v0 edge buys availability now; provenance is the next
layer when air-gap/attestation demand arrives.

### Self-Host Base-Image Currency + Minimization

RID: `req-cicd-base-image-lifecycle`
Status: `In Development`

Sourcing base images off a rate-limit-free mirror (`req-cicd-base-image-sourcing`) fixes
*availability*; it does nothing for *attack surface* or *CVE currency*. The market answer is a
paid managed-hardened-image catalog (Chainguard, Docker Hardened Images, Red Hat Hardened
Images, Minimus). TAP's answer is to **self-host the same two properties — currency and
minimization — with free/OSS tooling**, keeping the runtime-install architecture intact and
avoiding a per-image subscription — even the hard FIPS requirement (`-5`) is met by
**self-building the free OpenSSL 3.0 #4282 provider**, not by buying a validated image. The
full landscape survey, the decision criteria, the re-evaluation triggers, and the FIPS
recipe live in the doc: [doc-hardened-base-image-landscape](../docs/misc/doc-hardened-base-image-landscape.md).
The **FIPS decision record, lessons learned, assessment methodology, and a re-runnable
verification suite** — written as a handoff artifact for a future AI or human assessor —
live in [doc-fips-assessment-record](../docs/misc/doc-fips-assessment-record.md).

**Grounding evidence (spike, 2026-07-09).** A real build of `cgr.dev/chainguard/wolfi-base`
+ `apk add python-3.14 git bash postgresql-client curl` + the copied `uv` binary: Python
**3.14.6** present (Wolfi tracks latest — Google Distroless / UBI lag on Debian/RHEL Python),
TAP's full dependency closure `uv sync`'d cleanly (glibc manylinux wheels, no source builds —
the Alpine/musl trap avoided), the from-git plugin path worked (`git ls-remote` over TLS), and
Trivy OS-package CVEs came in at **0, versus 311 (8 critical / 63 high) on `python:3.14-slim`** —
*with* git/bash/uv still on board.

**Corrected decision criterion (2026-07-09).** An earlier draft claimed the base must ship a
**package manager** because TAP installs deps + plugins at runtime, and on that basis ruled out
every fixed/distroless image. **That reasoning is wrong and is retracted.** `uv sync` and
`uv pip install git+https://…` are *Python-package* operations, not *OS-package* operations:
they need `python`, `uv`, `git`, `bash` (+ `sed`/`grep`/`coreutils`), all of which can be baked at
**build** time by any means. TAP's own `Dockerfile` already demonstrates this —
`COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/` installs `uv` with no package manager
involved. Proven by spike (`spikes/distroless/`, both `BUILD_EXIT=0`): a **true distroless**
runtime (`cgr.dev/chainguard/python:latest` — no `apk`, no `apt`, not even `/bin/sh`) and a
`ubi9/ubi-micro` runtime built via Red Hat's `dnf --installroot` both run `uv sync` of TAP's real
closure *and* the from-git plugin install with **zero package manager present**.

Wolfi is therefore chosen on criteria that actually hold, not on a false constraint:

1. **Python-3.14 currency.** `requires-python = ">=3.14"` is the hard filter. Measured: Wolfi
   **3.14.6**, UBI9 `python3.14` **3.14.5**, Google Distroless `python3-debian13` **3.13.5** (out).
2. **In-image, host-independent FIPS.** The load-bearing difference (see `-5`). Upstream OpenSSL
   lets the *image* turn FIPS on. Red Hat **deliberately disables `openssl fipsinstall`** and
   derives FIPS from the **host kernel** (`fips=1`) — a container we ship cannot enable it alone.
   For a self-hosted product on customer-controlled hosts, in-image FIPS is the only portable answer.
3. **A measured zero-CVE floor** and a vendor that rebuilds nightly, with `apko`/`melange` as the
   free, OSS, vendor-independence hedge (build our own image from the Wolfi feed, no subscription).

**Alternatives are PARKED, not eliminated** (2026-07-09) — see the doc for the full measured
matrix and `spikes/distroless/README.md` for the working builds. Reopen if: (a) the compliance
authority **rejects vendor-affirmed OE** portability (then the RHEL/host-FIPS path becomes
correct, and `ubi-micro` + `dnf --installroot` is already proven to work); (b) we adopt a
bake-once model; or (c) Wolfi's Python currency or CVE floor regresses. Docker Hardened Images
live at **`dhi.io`** (not `docker.io`) and require an authenticated pull (**HTTP 401** anonymous),
which cuts against `req-cicd-base-image-sourcing`'s anonymous-pull property; their free
`3.14-fips` variant is **unverified**.

| RID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-base-image-lifecycle-1 | Digest-pinned auto-patch loop | Partial | Base images are digest-pinned (2026-08-09); **Renovate LIVE self-hosted** the same day (renovate.json5 + .github/workflows/renovate.yml, GHA daily cron, org-owned `tap-renovate` GitHub App token — not the Mend app; repo-write stays in-house). First bot PR (#19, github-actions group) opened + server-side BLOCKED on the `gate` check — the ruleset + bot loop proven end-to-end. **PR-only**: auto-merge-on-green is the open tail. | Composes `req-cicd-dep-automation`. Dependabot can't update `uv.lock`/track `cgr.dev` → Renovate; keep Dependabot *Alerts* for the advisory feed. Credential: app id + PEM key as repo Actions secrets (manage-secret reviewed; scanner covers PEM armor). App perms (verify via `GET /orgs/<org>/installations` — a missed checkbox here presents as branches-with-no-PRs): contents/pull_requests/workflows/issues RW + checks/statuses/dependabot-alerts R. Standing config lessons: schedules defer PR creation INVISIBLY (none in PR-only mode; `config:recommended` ships its own lockFileMaintenance schedule needing an explicit override). Deferred tails: plugin-repo rollout (app installed org-wide; per-repo opt-in via a shared preset — natural tenant of the org `.github` repo — paired with plugin release automation, else bumps sit unreleased on plugin mains), and the `github-tags` lookup quirk under app tokens — RESOLVED 2026-08-10: root cause was aquasecurity's org IP allow list rejecting App-token API reads (platform gap, community#178332, no consumer-side fix); trivy-action is hand-SHA-pinned + Renovate-ignored with the reason recorded in renovate.json5. |
| req-cicd-base-image-lifecycle-2 | Image CVE gate | Partial | Trivy scans the published images at publish time (publish-images.yml `scan` job) and nightly (trivy-nightly.yml), SARIF → code scanning; report-only. Open: flip to a pre-push gate (fail on High/Critical WITH a fix, after a week of signal); optional Copacetic stays deferred. | Realizes `req-cicd-security-scanning-4` (2026-08-09). The spike's 311→0 is this gate's baseline signal. Waivers: `.trivyignore`, mandatory reason per entry. |
| req-cicd-base-image-lifecycle-3 | Curated-minimal Wolfi base — **the standard base** | Proposed · **decided 2026-07-09** | The web **and** DB image bases become a curated-minimal **Wolfi** base carrying exactly TAP's runtime binaries (`python-3.14 git bash coreutils sed grep postgresql-client` + copied `uv`). **Wolfi is now the standard base; alternatives are parked** (see the corrected criterion above). Start: `wolfi-base` + `apk` (digest-pinned via `-1`). Graduate: self-built **apko/melange** image (reproducible, our registry, self-generated SBOM) — this is also the vendor-independence hedge, since the Wolfi feed is Apache-2.0 and free of any subscription. | `git`/`bash`/`curl` are **named, itemized attack-surface line-items**, present because the runtime-plugin-install architecture requires them and kept current by `-1`. `sed`/`grep` **must be present** — git's porcelain in `/usr/libexec/git-core` are shell scripts, and `uv pip install git+https://…` (which runs `git submodule update`) dies with `sed: command not found` without them (spike-found). **`wolfi-base` already satisfies this via busybox**, verified by a real from-git install; no extra `apk add` is needed. The requirement bites only on a *true* distroless runtime (`chainguard/python:latest`, which has no shell at all). The base need not ship a package manager at runtime (`spikes/distroless/`) — Wolfi is chosen on Python-3.14 currency, in-image FIPS, and CVE floor, not on `apk`. |
| req-cicd-base-image-lifecycle-4 | Minimal-binary off-ramps | Proposed | Named levers to shrink the binary set when cost/benefit flips — **not now** (`git` = 0 CVEs on Wolfi today). (A) Watch **uv #12324** (embedded git via gitoxide): if it ships, delete `git` for free. (B) An `archive`-tarball plugin source type (`https://forge/.../archive/<sha>.tar.gz`, fetched by uv's own HTTPS, sha256-pinned like the boot record) drops **both `git` and `curl`** — take it when we adopt the bake-once variant. | End-state minimum runtime = `python + uv + app` (+ psql for snapshot, a POSIX-sh/Python entrypoint instead of bash). Off-ramps are byproducts of the bake-once move, not standalone chores. |
| req-cicd-base-image-lifecycle-5 | FIPS crypto — self-built OpenSSL 3.0 #4282 | **Spike-proven** · targeted ~2026-09 | **Hard requirement (not demand-gated).** Web + DB containers execute crypto through the **free upstream OpenSSL 3.0.9 FIPS provider (CMVP #4282)** — no vendor/Chainguard module. Build the validated `fips.so` per the #4282 security policy in a builder stage; run it against the base's **modern libcrypto** (OpenSSL guarantees a certified `fips.so` is binary-compatible with any *later* libcrypto → no OpenSSL-3.0-LTS-EOL exposure); activate with `openssl fipsinstall` (integrity MAC, run **in-image**) + an `openssl.cnf` setting `default_properties = fips=yes` + `ENV OPENSSL_CONF`. Python stdlib crypto inherits it with **NO Python rebuild** (Wolfi's python dynamically links system OpenSSL); `cryptography`/`webauthn` need **`--no-binary cryptography`** (its wheel bundles its own OpenSSL) built against system OpenSSL, baked at build time, with `CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1`. Algorithms (P-256, SHA-256, HMAC, PBKDF2, AES-GCM) all FIPS-approved → no redesign. **Spike (2026-07-09, `spikes/fips/Dockerfile.fips`) proved every step end-to-end:** 3.0.9 `fips.so` built on Wolfi; Wolfi's system OpenSSL **3.6.3** `fipsinstall`'d + self-tested it (binary-compat confirmed); providers activate (md5 refused); Python stdlib `_hashlib` md5 blocked with no rebuild; `cryptography 49.0.0 --no-binary` links system OpenSSL and does **P-256 ECDSA verify** (the passkey path) through FIPS while md5 → `InternalError`. Config gotchas now in the recipe: (a) `openssl_conf` MUST precede `.include fipsmodule.cnf` (else it's swallowed into `[fips_sect]` and no providers activate); (b) re-`.include /etc/ssl/ca.cnf`, which pointing `OPENSSL_CONF` at our file otherwise displaces (breaks `openssl req`; TLS trust unaffected); (c) **an empty `ossl-modules/` is NOT evidence of the crypto boundary** — `default`/`base` are compiled into `libcrypto`, not files, so the *config* is the boundary and must be treated as an integrity-critical asset. See [doc-hardened-base-image-landscape](../docs/misc/doc-hardened-base-image-landscape.md) § Spike evidence. | Named risks: (1) **OE vendor-affirmed portability** — Wolfi isn't a tested operational environment in #4282's policy. **ACCEPTED + OWNED (George, 2026-07-09)**, not a blocker: the fallback is a base-image swap (Chainguard validated-FIPS image, same family) rather than a rewrite. See the residuals below for the full escalation ladder; (2) `fips=yes` disables non-approved algos globally — audit Django/deps for import-time MD5/etc. (`usedforsecurity=False`); (3) `fipsinstall` must run in-image + re-run if `fips.so` bytes change. **Postgres SPIKE-PROVEN** (`spikes/fips/Dockerfile.postgres`): fips provider activates; PG links system libcrypto; initdb+start OK; `scram-sha-256` auth works (an `md5`-auth cluster would hard-fail); `gen_random_uuid()`/`sha256()` OK; **`SELECT md5()` refused** (a server-side crypto surface the Django audit cannot see — re-check when plugins add SQL); TLS restricted to `TLS_AES_*_GCM_*`. Wolfi ships `postgresql-16-oci-entrypoint` honouring the same `POSTGRES_*` contract ⇒ drop-in, not a reimplementation, at the exact same **16.14**. **⚠️ NON-CRYPTO HAZARD: collation.** The outgoing `postgres:16-alpine` is musl and is *labelled* `en_US.utf8` but *sorts like* `C`; Wolfi is glibc where `en_US.utf8` is a real, different collation. Carrying the label across silently changes text sort + index ordering. Use `initdb --encoding=UTF8 --locale=C` (reproduces today's actual behaviour, and is immune to glibc-upgrade index invalidation) and **recreate the data volume** — `datcollate` is recorded in the cluster. **`--encoding=UTF8` is REQUIRED, not optional (built 2026-07-21):** `initdb --locale=C` with no explicit encoding silently defaults to `SQL_ASCII`, under which `varchar(n)` counts bytes and multibyte UTF-8 overflows (the spike's ASCII-only `ORDER BY` missed this; see doc-fips-assessment-record.md §5.4). **DB image built + validated 2026-07-21** (`docker/postgres/Dockerfile`, wolfi-base + `postgresql-16` + oci-entrypoint + gosu + the FIPS recipe): `server_encoding=UTF8`, `datcollate=C`, sort parity, `SELECT md5()` refused, `scram-sha-256`, `gen_random_uuid()`/`sha256()` OK, full lane green under double-FIPS. |
| req-cicd-base-image-lifecycle-6 | FIPS build mode — flagged, **default on** | **Implemented (web + DB) 2026-07-21 · CI dual-gate pending** | The `-5` recipe is selected by a single build flag, `ARG TAP_FIPS` (**default `1`**), on both the web and DB images. `TAP_FIPS=1` builds the validated 3.0.9 `fips.so`, runs `openssl fipsinstall` in-image, writes the FIPS `openssl.cnf`, and sets `ENV OPENSSL_CONF`; `TAP_FIPS=0` skips all of it and leaves the stock provider set. **`cryptography` is built `--no-binary` in BOTH modes** so the dependency closure and the system-OpenSSL linkage are identical and only *provider activation* differs — otherwise non-FIPS silently passes on a bundled-OpenSSL wheel and FIPS breaks at the far end of the pipeline. The image **declares its own mode machine-legibly**: OCI label `org.tap.fips=true|false` + `ENV TAP_FIPS_MODE`, so CI, the boot record, `/healthz`, and an AI operator can all read the posture without executing crypto. **FIPS-on is the default and the published artifact; `TAP_FIPS=0` is an explicitly-requested escape hatch, never a silent fallback.** **As built (web, 2026-07-21):** real `Dockerfile` `ossl-builder` stage + `fips-${TAP_FIPS}` selector, `docker-compose.yml` build arg, `[tool.uv] no-binary-package = ["cryptography"]` + `CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1`, fail-closed boot self-check `tap.fips` (Validation Map row under this RID) + unit tests, and the `req-tap-auth-google-oidc-fips-algorithm` OIDC rescue. **One hard-fail found + fixed:** `OPENSSL_CONF` is process-global, so `psycopg[binary]`'s bundled OpenSSL broke SCRAM (`could not generate nonce`) under FIPS → switched to **`psycopg[c]`** (system libpq) — the psycopg analog of `cryptography --no-binary` (doc-fips-assessment-record.md L17). **DB image (stage D) DONE:** `docker/postgres/Dockerfile` (wolfi-base + `postgresql-16` 16.14 + `postgresql-16-oci-entrypoint` + gosu + the FIPS recipe), initdb `--encoding=UTF8 --locale=C` (UTF8 required — `--locale=C` alone silently gives SQL_ASCII; §5.4), volume recreated. Pending: CI dual-gating of both `TAP_FIPS` variants. | **Assert, don't assume (fail closed).** A boot check must *prove* the declared mode: when `TAP_FIPS_MODE=1`, verify the `fips` provider is active **and** that a non-approved primitive is actually refused (`_hashlib.new("md5")` raises), else emit `TAP-ABORT` and refuse to serve. Never infer FIPS from the absence of an error — the spike's first pass "parsed" a config that activated **nothing** and silently ran the default provider. Adds a validation surface ⇒ needs a [Validation Map](spec-dev-validation.md) row (`req-dev-validation-map`) in the implementing change. CI builds and gates **both** variants so `TAP_FIPS=0` cannot rot. |

**FIPS is specced in [spec-fips.md](spec-fips.md)** — the FIPS center of gravity. The base-image FIPS
recipe (`-5`) and build flag + boot assertion (`-6`) keep their home here (they are base-image build
concerns), but the whole FIPS posture — the crypto Bill-of-Materials (`req-fips-crypto-bom`), the
per-plugin conformance, the boot-time global gate, and the operator waivers — reads from that one spec,
which indexes `-5`/`-6` in its FIPS Requirement Map.

**Named residuals + triggers (deferred, not hidden):**
- We own the **rebuild cadence + break-glass** when an auto-patch PR reds (the price of not buying an SLA).
- Until `-3` graduates to self-built apko, we trust `cgr.dev`'s `wolfi-base` (digest-pinned since 2026-08-09; `-1`'s remaining half is Renovate-driven bumps — until then, bumps are manual per the procedure at the Dockerfile pins).
- **FIPS is decided** (`-5`/`-6`): self-built OpenSSL 3.0 #4282 provider, no vendor module, **on by default**. **OE vendor-affirmed portability is an ACCEPTED, OWNED risk (George, 2026-07-09)** — not a blocker. It is cheap to be wrong about because every fallback is a **base-image swap, not a rewrite** (the payoff of staying in the Wolfi family). Ladder, cheapest first: (1) swap to **Chainguard's validated FIPS image** — same family, our `fips.so`/`fipsinstall` steps fall away, `--no-binary cryptography` + the fail-closed boot assertion still mandatory, near-zero switching cost; (2) evaluate **DHI's free `3.14-fips`** (`dhi.io`, $0 — **UNVERIFIED**: 401 on pull, FIPS activation model unconfirmed); (3) last resort **UBI + host-derived FIPS** (already-proven `ubi-micro` + `dnf --installroot`; RHEL 9 *is* a tested OE, but the deployment host must run `fips=1`, which we cannot guarantee on customer infrastructure). Full analysis: [doc-fips-assessment-record](../docs/misc/doc-fips-assessment-record.md) § 7.1.
- **`fips=yes` vs non-approved primitives — audited, not assumed** (spike `spikes/fips/` + a full call-site sweep, 2026-07-09). Under a strict `fips`+`base` provider set with **no `default` provider**:
  - **SHA-1 is FIPS-approved as a hash** and is served by the `fips` provider. `hashlib.sha1()` works. Only MD5 hard-fails.
  - `hashlib.md5()` → `UnsupportedDigestmodError`; `hashlib.md5(usedforsecurity=False)` **succeeds**, served by `_hashlib` from a **separate non-FIPS `OSSL_LIB_CTX`** that CPython maintains for exactly this purpose. FIPS 140-3 permits non-approved algorithms for non-security uses, and `usedforsecurity=False` is the auditor-recognized signal — but it is a **reachable non-validated path**, and should be named as such rather than implied absent.
  - `hashlib.sha256()` is `_hashlib`-backed (genuinely the validated module); Wolfi's CPython ships **no** `_md5`/`_sha1`/`_sha2`/`_sha3` built-ins to silently fall back to. `_blake2` *is* built in — a small non-validated in-process implementation remains importable.
  - **TAP's own code is clean:** zero `md5`, zero `sha1`, zero `uuid3`; the only primitives are `hashlib.sha256` (13 call sites) and `hmac.compare_digest` (2). **`uuid5` (17 files, deterministic node/edge ids) is SHA-1-based and is safe** — CPython 3.14's `uuid5` passes `usedforsecurity=False`, and SHA-1 is approved regardless.
  - **Dependency closure:** the only bare `hashlib.md5()` calls are Django's legacy `MD5PasswordHasher` (**not** in Django's default `PASSWORD_HASHERS`, and TAP does not override them → unreachable) and `faker` (test-only). Bare `sha1()` in `cryptography`, `webauthn`, `oauthlib`, `django.template.loaders.cached` all work (approved). **No runtime hard-fail surface.**
  - Loading the `default` provider to widen the escape hatch is **not** required and should be resisted. Re-run the sweep on dependency bumps (`-1` auto-patch PRs) — a new bare `md5()` in a runtime dep is a boot-breaking regression under `TAP_FIPS=1`.
- **Alternatives are parked, not eliminated** (2026-07-09; measured matrix in the survey doc, working builds in `spikes/distroless/`). Reopen when: (a) the compliance authority rejects vendor-affirmed OE (→ RHEL/host-FIPS); (b) we adopt a bake-once/distroless variant (the runtime-install architecture does **not** block this — proven); (c) Wolfi's Python-3.14 currency or CVE floor regresses. `dhi.io` needs an authenticated pull (**401**), which conflicts with `req-cicd-base-image-sourcing`; its free `3.14-fips` variant is **unverified**.

### Enforce The Gate Server-Side

RID: `req-cicd-branch-protection`
Status: `Implemented`
Trace: `external` — GitHub repository rulesets (protect-default-branches, main-required-checks)

**Implemented 2026-08-09 as two layered repository rulesets** on the default branch:
`protect-default-branches` (pre-existing: deletion + force-push blocked for **everyone**,
deliberately no bypass) and `main-required-checks` (id 20613528: the `gate` status check —
product-lines' stable required-check job — must be green on pushed commits, with a
**Repository-admin bypass** covering the promote flow's direct atomic pushes, whose fresh
merge commits cannot yet carry check runs; the promote's own parallel gate remains their
validation). Everything that is not an admin push — a rogue direct push, a future
contributor, a bot merge — now needs a green `gate` server-side. Linear history is
deliberately NOT required (promote's pre-push merge produces merge commits by design).
`strict_required_status_checks_policy` is off (branch-up-to-date is the promote merge's job).

This is also the **blocking half** of the guard meta-integrity contract
([spec-dev-validation.md](spec-dev-validation.md) `req-dev-validation-meta-integrity-2`): the
in-repo `.github/CODEOWNERS` fence over the guard/validation machinery is authored but *inert*
until this ruleset requires code-owner review. One settings action lands both — protect `main`
*and* require code-owner review over the machinery paths — so it is captured here as the single
canonical branch-protection to-do.

**Status detail (2026-08-10, two live promotes — theory corrected same day):** the first
observation suggested a *duplicate-context* failure (a cancelled cloud attempt's FAILED
`gate` check beside the green one). The second promote disproved that: a lone green `gate`
check on the SHA still evaluated as a violation. The durable finding: **checks produced by
the cloud run on the throwaway `_ci-gate/<session>` ref do not satisfy ruleset evaluation
for a direct push to `main` at all** — so the promote flow structurally cannot pass this
rule on merit, and every promote push rides the admin bypass. The `-2` rationale stands,
now with the precise mechanism. Client-side `-4` (below) makes the bypass loud and guards
against a genuinely red/missing gate. Decision (George, 2026-08-10): **skip the interim
dedicated-bypass-identity rung** — go directly to the PR-flow endgame, where the gate runs
on the pull request itself, evaluation is natural, and the bypass list empties to match
`protect-default-branches`. Do NOT relax the rule's `integration_id` pin to accept
API-posted statuses — that would make the gate forgeable by anything holding
`statuses: write`.

**Update (2026-08-10, later the same day): the PR-flow endgame is LIVE.** The promote
script's default road is now the PR flow (pre-push merge → PR → server gate → auto-merge;
proven on PRs #26–#28), and change-tier gating
(`req-dev-validation-product-line-lanes-7`) makes it the *everyday* road for docs/specs
diffs too — the admin direct push is bootstrap/skip-hatch only
(`req-dev-multisession-push-workflow-7`). Consequence: **emptying the bypass list to match
`protect-default-branches` is now an actionable settings step**, no longer blocked on flow
rework; it rides naturally with the mandatory-PR flip and the `-3` code-owner-review rung.

| RID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-branch-protection-1 | Protect main | Implemented | Layered rulesets: deletion + force-push blocked un-bypassably; the `gate` check required on `main` pushes (2026-08-09, ruleset `main-required-checks`). Linear history deliberately not required. | Server-enforced floor for *everyone and everything* else. |
| req-cicd-branch-protection-2 | Bypass for the promote identity | Implemented | Repository-admin bypass on the required-check ruleset — the promote's direct atomic push survives; the un-bypassable deletion/force-push layer still applies to admins. | Keeps the client-side flow; adds the server-side backstop. The alternative — adopt a PR/merge-queue flow — is the [Goal 6](#goals) decision, tracked but not forced here. |
| req-cicd-branch-protection-3 | Require code-owner review over machinery | Proposed | The ruleset also **requires review from Code Owners**, so a PR touching the guard/validation machinery (the `.github/CODEOWNERS` paths — harness, scanner engines, ratchet core, runner + meta-tests, CI/gate config) needs the code-owner's approval. This is the blocking half of `req-dev-validation-meta-integrity-2`; without it, CODEOWNERS is authored but does nothing. Confirm the code-owner handle resolves — GitHub silently ignores an unresolvable owner. | Makes disabling a gate a deliberate, reviewed act rather than a silent code push. |
| req-cicd-branch-protection-4 | Red-gate abort + loud bypass telemetry | Implemented | `promote-to-main.sh` asserts pre-push that the LATEST `gate` check on the pushed SHA is green (aborting, main untouched, on red/missing/pending), and hard-warns on any `Bypassed rule violations` remote message post-push. It does NOT make the push satisfy the rule — throwaway-ref checks never do (see status detail); the bypass stays structural until the PR flow. | The PR-flow rework empties the bypass list; interim dedicated-identity rung deliberately skipped (2026-08-10). |


### Runner Least Privilege

RID: `req-cicd-runner-least-privilege`
Status: `Implemented`

**The job is the token boundary.** Every GitHub Actions job receives its own short-lived
`GITHUB_TOKEN`; per-job `permissions:` blocks are therefore a real, enforced isolation
seam — not a convention. This requirement pins the seam: the *validating* CI surface is
structurally incapable of writing, and the few write operations (image publish, SARIF
upload, Renovate's App-credentialed PRs) are isolated in jobs that contain nothing else.
The 2026-03-19 trivy-action compromise (mutable tags retargeted to imposter commits
carrying a credential stealer) is the demand signal for the SHA-pinning half; the token
model is the co-tenancy half.

Trust-delta doctrine (decided 2026-08-10, the watcher-paradox discussion): **prefer
controls from parties already inside the trust boundary.** This is why runner *egress*
control is a NAMED OPEN RISK (see `spec-security-posture.md`) rather than a third-party
agent: a root-privileged vendor watcher defending against compromised third-party code is
a trust-delta of one new root; GitHub's announced native egress firewall is a trust-delta
of zero, and we wait for it.

**Scope limits (named, so this requirement does not overclaim):** it governs `GITHUB_TOKEN`
grants only — the `tap-renovate` App's power is invisible to workflow files and is covered
by App-permission review + the main ruleset; it is static (declared grants + co-tenancy,
not runtime data flow); it covers the core repo now — plugin repos' thin caller workflows
join via the org-`.github`/shared-preset wave.

The `# guard-allow: req-cicd-runner-least-privilege — <reason>` annotation, on the line(s)
immediately above a step, is the review-visible escape hatch for *justified* co-tenancy
(the `docker/*` steps that ARE a job's write; the trivy scanner whose job carries only
`security-events: write` for a first-party upload step). The future guard enforces
annotation presence, not zero exceptions.

| RID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-runner-least-privilege-1 | Read-only default token | Implemented | Repo `default_workflow_permissions=read`, `can_approve_pull_request_reviews=false` (verified 2026-08-10). | The floor under everything else. |
| req-cicd-runner-least-privilege-2 | Explicit per-workflow grants | Implemented | Every workflow declares a top-level `permissions:` block; top-level grants are read-only; write scopes appear only at job level (audited 2026-08-10: all seven workflows conform). | Inherited defaults are not a posture. |
| req-cicd-runner-least-privilege-3 | No unannotated write-job co-tenancy | Implemented | In any job whose token carries a write scope, every third-party `uses:` is either the job's own write operation or carries the `guard-allow` annotation; scan/build-job checkouts set `persist-credentials: false` so the token is never left readable in `.git` config. | The practical leak path is persisted git credentials. |
| req-cicd-runner-least-privilege-4 | Third-party actions SHA-pinned | Implemented | `helpers:pinGitHubActionDigests` maintains `@<sha> # vX.Y.Z` pins; trivy-action hand-pinned (its org IP allow list blocks Renovate lookups), SHA verified an ancestor of upstream's default branch. Digest sweep merged 2026-08-10 (PR #24, squash; every pin ancestor- or release-tag-verified). | Bump hygiene: `compare` API, `ahead_by: 0` — imposter commits are not ancestors. |
| req-cicd-runner-least-privilege-5 | Same-org refs: protected tags | Proposed | Same-org `uses:` refs stay tag-based (floating `v1` is the two-mains design); compensating control = a `v*` TAG RULESET (update/delete blocked, bypass = release identity only) — a tag-move is the SILENT write path (no commit, no PR, no gate), exactly the trivy attack mechanics. | Immutable per-version tags + plugin-repo Renovate bumps is the endgame alternative. |
| req-cicd-runner-least-privilege-6 | Enforcement guard | Implemented | `tap/guards/workflow_least_privilege.py` in the fenced guard harness: explicit-permissions, co-tenancy/annotation, and SHA-pin predicates over `.github/workflows/*.yml`; PyYAML (dev group, `safe_load` only) as parser; zero-baseline fail-closed, landed 2026-08-10 (13 predicate unit tests; live tree clean — first run caught the unannotated `docker/login` in the manifest job); Map row generated; slug added to the guard-manifest floor. | CODEOWNERS-fenced; watched by the guard-integrity guard. |


### DCO Sign-Off Enforcement

RID: `req-cicd-dco-signoff`

CONTRIBUTING.md (in legal review as of 2026-08-10) requires a DCO `Signed-off-by` trailer
on every commit, with two policy-stated exemptions: merge commits (DCO convention) and
commits authored by automated dependency-update tooling, which a maintainer certifies at
merge — normally by squash-merging with their own sign-off. A published policy without
mechanics is a latent lie the day it lands, so the mechanics land **first, report-only**,
and flip to enforcing in the same change that lands CONTRIBUTING.md + the DCO text at the
repo root. The certification act is review-and-submit, not the mechanical trailer — the
tooling below applies trailers; humans certify by submitting (this is CONTRIBUTING's own
framing, and it puts maintainer and contributor on the identical path).

| RID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-dco-signoff-1 | Sign-off applied automatically | Implemented | `.githooks/prepare-commit-msg` appends the committer's `Signed-off-by` trailer to every non-merge commit, from the committer's git identity. | Lives in the versioned `.githooks/` dir `spawn-session.sh` wires via `core.hooksPath`, so every contributor session gets it — no per-machine setup, no maintainer special case. |
| req-cicd-dco-signoff-2 | Trailer check on both roads to main | Implemented | `scripts/check-dco` verifies every non-merge, non-bot commit added over `origin/main` carries the trailer; wired into the promote's local gates and the `dco` job in `product-lines.yml` (the PR road + the promote's dispatched cloud gate). | ONE artifact, MANY invokers (the `scripts/gate` pattern). Bot exemption: `renovate`/`dependabot`/`github-actions` `[bot]` authors. |
| req-cicd-dco-signoff-3 | Enforcement flips with the policy | Implemented | Landed 2026-08-12: `CONTRIBUTING.md` + `DCO` at the repo root, and `scripts/check-dco` now FAILS on a missing trailer — the enforcing default lives in the script itself (escape hatch `TAP_DCO_REPORT_ONLY=1`) rather than an env var per invoker, so an ad-hoc run can never be quieter than the gate. | Approval provenance (stated exactly, because this document is itself a provenance instrument): outside counsel reviewed and approved the **contribution terms** (the v1 draft — licensing, prospective grant, employer authority, AI-assisted contributions); the **v2 additions** (contribution process, tests/code-quality bar, and the two sign-off-mechanics paragraphs) were authored in-repo and approved by the **project steward**, not re-reviewed by counsel. Pre-flight before flipping: no open PR and no live session branch carried an unsigned commit (two 3-week/3-month-stale branches did; both long superseded). The red spells out both remediation forms (`--amend -s`, `rebase --exec`) and the hooksPath caveat for plain clones. Composes with `req-cicd-branch-protection`: under mandatory PRs the `dco` job becomes a required check. |
| req-cicd-dco-signoff-4 | Remediation without rewriting history | Implemented | An unsigned commit may be certified retroactively by a later **individual remediation commit** (`I, <name> <email>, hereby add my Signed-off-by to this commit: <sha>`), itself signed, whose declared identity matches BOTH its own author and the target commit's author. `scripts/check-dco` accepts this form; CONTRIBUTING documents it. | Prior art: the reference DCO app (dcoapp/app) supports exactly this, and its stated advantage is the one our amend/rebase advice lacked — history does not change, so a shared branch is not broken under other people. Format and identity rules follow that implementation verbatim so ecosystem knowledge transfers. **Third-party remediation** (`On behalf of X, I, Y, hereby add…`) is deliberately NOT accepted: certifying another person's right to submit is a materially larger statement than certifying your own, and enabling it is a steward policy call, not a mechanical convenience. Behaviorally guarded by `tap/tests/test_check_dco.py` (signed passes, unsigned fails, bot exempt, remediation certifies, cross-identity remediation rejected). |

### Shift-Left Security Scanning

RID: `req-cicd-security-scanning`

All four sub-layers are now live (the 2026-08 wave: gitleaks gate, Dependabot alerts,
CodeQL default setup, Trivy publish-time + nightly image scans). The open tails are
quality-of-enforcement, not coverage: the Trivy gate flip (report-only → fail on
High/Critical-with-fix, `req-cicd-base-image-lifecycle-2`) and CodeQL's conversion from
config-invisible default setup to a reviewed in-repo advanced setup. Each directly serves
the [security posture](spec-security-posture.md).

| RID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-security-scanning-1 | Secret scanning | Implemented | gitleaks (pinned 8.30.1) runs as the `secret-scan` job gating every product-lines run; stdlib pre-commit staged scan + in-repo credential-pattern guards complement it. | Tree-scan (`gitleaks dir`) only — full-history scanning is GitHub secret scanning's job (free on public repos, org toggle). |
| req-cicd-security-scanning-2 | Dependency / vuln audit | Implemented | GitHub Dependabot **alerts** enabled 2026-08-08 (all 25 initial alerts cleared same day). | Alerts only — update PRs are Renovate's job (`req-cicd-dep-automation`, Dependabot can't do `uv.lock`). |
| req-cicd-security-scanning-3 | SAST | Implemented | CodeQL via GitHub default setup, enabled 2026-08-08; initial 15 alerts triaged (fixes + dismissed FPs). | Default setup is config-invisible in-repo; converting to advanced setup (reviewed `codeql.yml`) is a named follow-up. |
| req-cicd-security-scanning-4 | Container image scan | Implemented | Trivy on both published images (`tap-web` incl. its baked Python closure, `tap-db`): publish-time scan + nightly rot sweep, SARIF into code scanning under per-image categories. Report-only; the High/Critical-with-fix gate flip is tracked under `req-cicd-base-image-lifecycle-2`. | 2026-08-09. Waiver ledger: `.trivyignore` (mandatory reason per entry). Grype deliberately skipped (second FP stream, no second signal). |

### Automate Dependency Updates

RID: `req-cicd-dep-automation`
Status: `Implemented`
Trace: `non-python` — renovate.json5

TAP pins (`uv.lock`) but pinned dependencies rot — security patches do not land until
someone notices. **Implemented 2026-08-09 (PR-only)**: self-hosted Renovate (see
`req-cicd-base-image-lifecycle-1` for the full wiring) opens grouped update PRs across the
three write surfaces — Dockerfile digest pins, `uv.lock` via pep621, pinned GitHub Action
versions — plus immediate OSV-vulnerability PRs. Composes with
`req-cicd-security-scanning-2` (the audit tells you *what* is vulnerable; the bot *fixes*
it), and the update PRs flow through the `pull_request` product-lines gate, which the
`main-required-checks` ruleset makes a server-side merge precondition.

### Build Once, Promote The Artifact

RID: `req-cicd-build-once-artifact`
Status: `Implemented`
Trace: `non-python` — .github/workflows/publish-images.yml

**Implemented for the dev/CI artifact (2026-08-09).** `.github/workflows/publish-images.yml`
builds `tap-web` + `tap-db` (TAP_FIPS=1, multi-arch amd64+arm64 on native runners) on every
main push and publishes to **GHCR** as `latest` + `sha-<short>`, with SLSA provenance
attestations and per-arch `buildcache-*` refs. Consumers: spawn (the single dev/adopter entry point) pulls instead of
building (compose `image:` fields, anonymous pulls); CI lanes use the registry cache as
eviction fallback. The web image carries a pre-compiled wheel cache (Dockerfile `deps-warm`
stage → `/opt/uv-cache-seed`) so first boot creates the venv from built wheels in seconds
instead of compiling cryptography/psycopg from source (the venv itself is always created at
runtime by `uv sync` — deliberately, after a cp-seeded venv proved uv-hostile on the CI
runner).

**Registry decision: GHCR, not ECR** (this section previously said ECR): the repos went
public 2026-08, making GHCR free with unlimited anonymous pulls and `GITHUB_TOKEN`-only
push — no new credential, no pull-rate problem (the Docker Hub 429 lesson). ECR Public
remains the base-image availability mirror (`req-cicd-base-image-sourcing`).

Still open under this RID: promoting the *same bytes* through deploy environments
(build-once-deploy-many is moot until there are environments), the parked template-bake
idea (bake the migrated DB into the image), and product release versioning (semver for the
app, not just plugins).

### Sign Artifacts, Emit SBOM

RID: `req-cicd-supply-chain-provenance`
Status: `Implemented`
Trace: `non-python` — .github/workflows/publish-images.yml

**First slice implemented (2026-08-09):** the published `tap-web`/`tap-db` images carry
SLSA Build L2 provenance via `actions/attest-build-provenance` (Sigstore public-good
instance; verify against a content-addressed ref — resolve your tag to a digest first
(`docker buildx imagetools inspect <ref>:<tag>`), then
`gh attestation verify oci://ghcr.io/unified-systems-com/tap-web@sha256:<digest>
--owner unified-systems-com`; a tag-form verify answers "what this tag points at RIGHT
NOW", not "the artifact I resolved" — teach the digest form, per
req-cicd-supply-chain-provenance-1). Still open: plugin-wheel attestations and cosign-style
signatures. SBOM emission has graduated to its own specification —
[spec-cicd-sbom.md](spec-cicd-sbom.md) (Proposed 2026-08-20; groundwork record in
[doc-cicd-sbom-groundwork](../docs/misc/doc-cicd-sbom-groundwork.md)).

Beyond that slice: no other artifact signing (Sigstore/cosign — notable given a
`sigstore_core` plugin exists), no SBOM (CycloneDX/SPDX). TAP's **boot-record-as-BOM** is conceptually
ahead — it is a declarative, verified bill of materials — but it is not yet connected to the
standard formats and signing the ecosystem consumes. Grafana signing every plugin is the
nearest-neighbor precedent. Sequenced after `req-cicd-build-once-artifact` (you sign and
attest the artifact you publish).

**Plugin release signing lands here.** `req-tap-plugin-extdev-signing`
(`spec-tap-plugin-external-development.md`) — signed plugin release tags / boot-record digests
verified at install, closing the moved-tag / compromised-repo gap — is the plugin-artifact
face of this same signing capability. It is **pinned to the GitHub-org refactor** because the
publisher/signing identity is org-rooted: building it before the org exists means rebuilding
it against the new identity root. So plugin signing is deferred to this requirement's wave,
not built speculatively now; for the Aug-1 friendly-developer phase the trust boundary
(TAP-controlled org, repos, read-only PAT, known developers) is tight enough to defer
enforcement. Grafana (signed plugins) and Terraform (GPG-verified provider tags) are the
precedents for both faces — one signing story, two layers (image artifact + plugin tag).

| RID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-supply-chain-provenance-1 | Digest-Threaded Publish Pipeline | Implemented | Every inter-job hop in the image publish pipeline (`publish-images.yml`) MUST be content-addressed: build legs push by digest (no staging tags), digests travel to the manifest job as workflow artifacts, the merge consumes `ref@digest` only, and the merge MUST verify fail-closed — before attesting — that the just-tagged index's children are exactly the built digests. No attestation may be produced for bytes that were ever referenced through a mutable name between build and signature. | Built 2026-08-20. Rationale: tags are the registry's only mutable references, so a tag-based hop gives any `packages:write` holder a TOCTOU window to swap content between jobs — and the attestation step would then *sign the tampered bytes*, laundering the tamper behind an honest signature. Workflow artifacts are integrity-held by the same GitHub infra that signs the attestation (no new trust root). BuildKit's embedded provenance is disabled on the build legs (`provenance: false`) — the provenance lane is GitHub attestations, and a bare single-platform manifest is what makes the strict children-equality check possible. Named residual (open, accepted): registry **build-cache poisoning** — the `buildcache-<arch>` tags are mutable and a forged cache entry could inject layers into an honest build *before* the first digest exists; digest threading cannot see it. Same blast-radius answer as the runner-compromise residual: confined to our own `packages:write` surface. |
| req-cicd-supply-chain-provenance-2 | Verified Wheel-Cache Seed | Implemented | The web image's pre-compiled wheel-cache seed (`/opt/uv-cache-seed`, Dockerfile `deps-warm` stage) MUST ship with a hash manifest generated INSIDE the attested build — per-file sha256 keyed by **relative path**, **excluding the manifest itself** (it is generated under `/root/.cache/uv` in `deps-warm` and verified under `/opt/uv-cache-seed`; absolute paths would never match), stored alongside the seed and therefore covered by the image digest. Before seeding an empty uv-cache volume the entrypoint MUST verify the seed against the manifest as a **full bidirectional reconciliation**: hash mismatch, files MISSING from the seed, and EXTRA unmanifested files are all failures — a partial or padded seed must not pass as "mostly fine." Semantics split three ways: an **absent** seed MAY degrade cleanly (uv compiles/downloads with lock-hash verification — the existing path); a seed **with a manifest that fails verification** is a fail-closed boot abort (`TAP-ABORT`, req-boot-abort-signal), never a degrade, because a corrupt seed inside an immutable image means image corruption or tamper, not staleness; a seed **without any manifest** (a legacy image predating this requirement, running under a newer tree — a DESIGNED state: compose executes the entrypoint from the dev bind mount while the image lags until the next pull) is NOT seeded and NOT fatal — warn loudly and degrade to the lock-hash-verified slow path. The invariant is NEVER SEED UNVERIFIED BYTES, not 'every image must carry a manifest': manifest-stripping is not a distinct attack (whoever could strip it could modify the seed; image immutability is that boundary), and abort-on-absent bricked every legacy-image boot on first contact (PR #86 lean-boot red, 2026-08-20). The verification result MUST be emitted as machine-legible boot evidence when the boot-record/observability surface is available (the check runs before tap.preboot / `manage.py boot` — an early pre-boot scratch record that the boot record later absorbs satisfies this). | Proposed and BUILT 2026-08-20 (groundwork record §3.4; `docker/seed_manifest.py` + `deps-warm` generation + entrypoint verify; proven against the live 11,989-file seed incl. tamper/padding/relocation cases; Validation Map row synced). Closes the boot half of the content-addressing story: build-time inputs are verified by `uv.lock` sha256 hashes and the build is attested, but the boot-time seed copy was a bare `cp` and warm-cache `uv sync` does NOT re-verify hashes on cache hits — so "first boot runs the attested bytes" was implied by image immutability, never verified at use. Scope honesty: verifies image→volume at SEED time only. Explicit non-goals, unchanged: re-verifying a non-empty volume on later boots (the volume is HOST-trust domain — an attacker who can write it can equally patch the venv or the process; verification there adds no boundary), and the compile-output/runner residual (a hash manifest a compromised builder writes attests the tampered bytes — that layer belongs to provenance, not manifests). Cache MISSES still verify via lock hashes at acquisition. At implementation the boot check is a validation surface → Validation Map row in the same change (spec-dev-validation.md). Implementation guidance (Codex review 2026-08-20): generator + verifier as one tiny **stdlib-only Python** module (python exists in-container before `uv sync`; avoids BusyBox/coreutils find-sort-quoting divergence — and stdlib-only is already the house rule for pre-venv code, req/host-runnable boundary); the `docker/entrypoint.sh` "degrades cleanly" comment MUST be split when this lands (absent → degrade; invalid → abort) — a stale comment contradicting a fail-closed check is exactly the drift the docs discipline exists to catch. |

### Product Releases

RID: `req-cicd-product-releases`
Status: `Implemented`
Trace: `non-python` — .github/workflows/release-please.yml

TAP core ships **product-level releases** (resolved 2026-08-20 — this body previously said
"no product releases, the right pre-launch posture"; the 2026-08 release wave overtook that
and George ruled the machinery IS the implementation). A release is a contract surface: what
a version means, what it contains, and what is supported. The shipped shape: release-please
computes the version from conventional commits and cuts semver tag + GitHub Release with
notes when a maintainer merges the gated release PR; `publish-release-tags.yml` promotes the
already-attested `:sha-<short>` image manifest to `:X.Y.Z` — same bytes, same digest,
attestation intact; consumers pin `TAP_VERSION` (`-3`); and the root `SECURITY.md`
supported-versions statement names the latest tagged release line as the supported tier —
the consumer of the contract, updated when releases became real (`-2`).

**Update 2026-08-13 — the consumer half now exists.** Releases and the machinery below are
built; what was missing was any way for a consumer to *choose* one. `docker-compose.yml`
defaulted both images to `:latest`, which `publish-images.yml` republishes on **every main
push**, and the `TAP_WEB_IMAGE`/`TAP_DB_IMAGE` overrides that could have pinned a version
appeared in exactly one file and were documented nowhere — so the release ceremony was
decorative for anyone running the default: every promote reached them. `.env` now pins both
images to `TAP_VERSION` (one literal, bumped by release-please so it cannot go stale), and
development explicitly opts *out* via `.env.local`. The default is now the release; tracking
main's tip is the deliberate choice.

| RID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-cicd-product-releases-1 | Semver product releases with release notes | Implemented | Product-level releases MUST use semantic versioning — semver git tags published as GitHub Releases, each carrying human-readable release notes that summarize major changes and name any fixed vulnerabilities. | OpenSSF Best Practices `release_notes` criterion; legitimately N/A until the first release exists. **When the first release is cut, update the project's OpenSSF Best Practices entry**: refresh the `version_unique` answer (unique versions then = the semver tags, not just SHA identifiers), confirm `version_semver`/`version_tags`, and flip `release_notes`/`release_notes_vulns` off N/A. **Machinery (2026-08-10):** the release-please PR lane (`release-please.yml` + manifest config; pre-1.0 mapping breaking→minor, feat/fix→patch — the "0.1.x warns, 0.2.0 enforces" contract language) computes the version from conventional commits and cuts tag+Release only when a maintainer merges the gated release PR; `publish-release-tags.yml` then promotes the already-attested `:sha-<short>` manifest to `:X.Y.Z` — same bytes, same digest, attestation intact. Writes ride the org-owned `tap-release-please` GitHub App (Renovate's trust model; app-token PRs trigger the required checks, default-token PRs never do and would sit unmergeable; both workflow jobs keep read-scoped tokens per req-cicd-runner-least-privilege). The release PR carries a bot `uv lock` refresh — the lock records core's own version and a version-only bump invalidates it (verified). **Retag race closed (2026-08-19):** `publish-images.yml`'s newest-main-wins cancellation (`cancel-in-progress`) cancelled the v0.1.2 release commit's build when the next merge landed 13s behind it, so `:sha-<short>` never published and the tag promotion timed out — release-commit pushes (`chore(main): release` prefix) and `ref`-input backfill dispatches now run in isolated concurrency groups that later pushes cannot cancel; per-arch results are pushed by digest and merged content-addressed end to end (`req-cicd-supply-chain-provenance-1`, which supersedes the brief per-commit staging tags) so overlapping runs cannot pair mismatched arches; a backfill dispatch builds a named commit and publishes only its `:sha-<short>`, never moving `:latest`. |
| req-cicd-product-releases-2 | SECURITY.md tracks the release model | Implemented | Cutting the first product release MUST update the root `SECURITY.md` supported-versions statement (today: latest `main` + latest published images, no backports) to name which releases receive security fixes. | The tripwire that keeps the published policy honest once a release cadence exists. |
| req-cicd-product-releases-3 | Consumers Pin A Version, Not A Moving Tag | Implemented | The shipped `.env` pins `tap-web` and `tap-db` to the SAME `TAP_VERSION` (one literal; both images are artifacts of one gated commit, so a mixed pair is never valid). release-please bumps that pin on release (`extra-files`), so it cannot go stale. `docker-compose.yml` REQUIRES the image vars (`:?`) rather than falling back to `:latest` — an unset var fails loudly instead of silently shipping main's tip. Development opts out explicitly: `spawn-session.sh` writes the `:latest` pair into the session's `.env.local`. **Pull-only base (2026-08-19):** the `build:` stanzas moved out of `docker-compose.yml` into the opt-in `docker-compose.build.yml` overlay (`scripts/dc build` stacks it automatically; spawn's pull-fallback invokes it explicitly) — so a missing pinned tag now hard-fails `up` instead of silently substituting an unattested from-source build, which is how the v0.1.2 publish gap ran undetected for four days. CI is the named exception: `docker-compose.ci.yml` pins the db to `:latest` because the version pin is a consumer contract, not a CI contract — a release PR bumps `TAP_VERSION` to a version whose images only exist after the merge, so gating the pin on the release branch is structurally unsatisfiable (the 0.1.3 release PR proved it). | **Gotcha, verified against Compose v2:** an override MUST set both image refs, NOT `TAP_VERSION` — `.env` interpolates its refs before `.env.local` is read, so overriding the version there silently does nothing. Both the `.env` comment and the spawn heredoc say so at the point of use. |

### Continuous Delivery

RID: `req-cicd-continuous-delivery`
Status: `Backlog`

The entire deploy half is unbuilt: no staging/prod **environments**, no deploy automation,
no **progressive delivery** (canary/blue-green), no **rollback** path, no product-level
release versioning. This is *expected* pre-launch and is parked by the
[Rampart roadmap](../plan/road-rampart.md) for post-launch — named here so it is tracked,
not a blind spot. TAP has **CI, not CI/CD**: "promote to main" is *integration*, not
*deployment*. Depends on `req-cicd-build-once-artifact` (you deploy the artifact you built).

### Live Instances In CI For Operational Testing

RID: `req-cicd-live-instance-testing`
Status: `Backlog`

Stand up **running TAP instances as part of the CI process** and operate them as test
targets — the class of validation that only exists against a live product, not a test
database. The mechanism already half-exists: the cold-boot gate and `gate-lean` spawn
throwaway stacks and assert "boots healthy, no import leaks"; this requirement generalizes
that seam to "operate the running product and test what it does". Nightly/soak tier, not
the promote gate — these are long-running, findings-oriented lanes.

The backlog riding this requirement (in rough sequence):

1. **API fuzzing** — Schemathesis over the Django Ninja OpenAPI schema, hitting every
   core + plugin-registered router with schema-valid and malformed requests; oracles come
   free (no 5xx, response-schema conformance, capability gates refuse).
2. **Write-path stateful fuzzing** — a Hypothesis `RuleBasedStateMachine` driving
   generated sequences of service-layer mutations (create/observe/edge/FLIP/purge/OCC)
   against the live instance, checking grid-spine invariants after every step. Pays down
   the read/write asymmetry: Gryphon fuzzes the read path; nothing generates adversarial
   mutation sequences. Deliberately deferred until this requirement provides the target
   (decided 2026-08-10).
3. **DAST** — OWASP ZAP baseline (headers/CSP/cookies unauthenticated; authenticated scan
   later via a minted session, the drive-browser pattern).
4. **Live smoke / operational checks** — the spec-dev-multisession-smoketest battery run
   mechanically instead of by an attached developer.

Depends on `req-cicd-build-once-artifact` (the instance under test should be the published
artifact, not a rebuild). Feeds `req-cicd-security-scanning` (DAST is its dynamic half) and
the OpenSSF Scorecard fuzzing check (Schemathesis/Hypothesis are recognized engines).

### Measure The Pipeline

RID: `req-cicd-pipeline-observability`
Status: `Backlog`

No measurement of the four **DORA metrics** (deployment frequency, lead time for changes,
change-failure rate, MTTR) and no systematic **flaky-test tracking** (flakes are fixed
reactively today). The instinct already exists in the gryphon findings/fuzz-campaign ledgers
— this applies the same pattern to the pipeline itself. Lower priority pre-launch; it becomes
load-bearing once there is a delivery cadence to improve.

## Accepted Risk (deliberately deferred, not hidden)

- **The deploy half's remainder** (`req-cicd-continuous-delivery`, plus the deploy-side
  halves of `req-cicd-supply-chain-provenance` and `req-cicd-build-once-artifact` — both
  Partial since 2026-08-09: images published + attested, but no environments to promote
  them through) is parked pre-launch — no customers, no environments to deliver to yet.
  Right call; tracked for launch-time.
- **Client-side orchestration** remains the model for now (Goal 6). Its bypassability is
  mitigated the moment `req-cicd-branch-protection` lands; its convergence lag (per-session
  script copies) is accepted for a solo flow.
- **Tier-0 local Postgres** runs with `fsync=off` — a corruption-on-unclean-shutdown risk
  and a minor dev/prod parity divergence, accepted because the dev/test cluster is
  reproducible (see `docker-compose.yml`).

## Relationship To Other Specs

- [spec-dev-validation.md](spec-dev-validation.md) owns the *validation surfaces* and the
  Validation Map (what runs, what it proves, honest guard status). This spec owns the
  *pipeline enforcement + delivery* posture around them.
- [spec-dev-multisession.md](spec-dev-multisession.md) owns the promote/push workflow this
  spec proposes to enforce server-side.
- [spec-security-posture.md](spec-security-posture.md) is the parent doctrine: the first
  three requirements here are its cheap-foundational-edges applied to the pipeline.
- [plan/road-rampart.md](../plan/road-rampart.md) sequences the deploy half toward launch.

## Requirement Review Needed

Open questions where the spec and the tree disagree. Recorded, not decided. Indexed across all
specs in [doc-tap-requirement-review-ledger.md](../docs/misc/doc-tap-requirement-review-ledger.md).

### Product releases exist while the requirement says they must not yet — RESOLVED 2026-08-20 (George)

**Ruling: the release machinery is the implementation.** Body rewritten to describe what
shipped; status `Implemented`, mapped `non-python` to `release-please.yml` (the primary of the
release lane). The supported-versions obligation (`-2`) was found already met — the root
`SECURITY.md` names the latest tagged release line as the supported tier — so the tripwire had
fired and been honored; the ACID is flipped to match. `-1`'s note about refreshing the OpenSSF
Best Practices release answers stays as the one possibly-outstanding external click.
