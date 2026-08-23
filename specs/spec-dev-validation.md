# Development Validation

## Philosophy

For the current solo dog-food window (one developer, running real security assessments from the system on a laptop, through roughly mid-2026), the developer's own usage *is* the de facto whole-system integration suite. That is why the Steady-Queue-class transaction-visibility bug was caught at all — not by a test, but by the system being used. The automated validation gate's job is therefore deliberately narrow: catch what hands-on usage *cannot* — a cold boot from zero, the spawn-off-`main` path, and a capability that has gone "cold" (built but no longer exercised in the daily loop) — in the window between the moments the developer would otherwise notice. Its primary purpose is protecting the multi-session workflow: a rotted or broken `main` silently poisons every session spawned from it.

This spec is the **center of gravity for validation tracking**. It owns the cross-cutting pre-push gate and an authoritative **Validation Map**; it *references* the leaf validation surfaces (spawn-env smoke, teardown, the log-site scanner, the task-backend async-delivery tiers) rather than re-specifying them. As environments multiply, stage-validation and prod-validation become additive: new Map rows and sibling specs under this index, not divergent reinventions.

The discipline running through every requirement here is honest coverage accounting, adopted from the false-confidence failure mode named in `docs/aar/2026-05-16-aws-collector-sprint-sprawl.md` §4 and `spec-tap-cares-task-backend.md`: **a requirement whose only guard is a one-time manual check or "the suite still passes" is effectively unguarded, and MUST be labeled CI-unguarded — by design, not by oversight.** "Green" is only meaningful if known-broken is enumerated in the repository and never in a human's memory.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Honest Validation Map | One authoritative inventory of every validation surface, what it proves, when it runs, and its honest guard status. |
| 2. | Cold-Path Coverage | The gate asserts what dog-fooding structurally cannot: cold boot, spawn-off-`main`, and cold flows. |
| 3. | Binary Gate | Green means green. Known-broken is enumerated in-repo with per-entry justification and ratchets toward zero. |
| 4. | Pre-Push Enforcement | The promote path runs the gate and refuses to advance `origin/main` on red. |
| 5. | Additive Future | Stage- and prod-validation slot in as new Map rows + sibling specs, never as parallel reinventions. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-dev-validation-map | [Validation Map](#validation-map) | Implemented | The spine: authoritative inventory of every validation surface |
| req-dev-validation-smoke-gate | [Cold-Boot Smoke Gate](#cold-boot-smoke-gate) | Implemented | Ordered cold-boot-one-cycle, halt-on-failure (`manage.py cold_boot_gate` / `scripts/gate`). Since 2026-08-10 a REQUIRED CI job (`product-lines.yml` `cold-boot`) — no boot authority exists only on a laptop; the promote's local run is optional fast feedback (`TAP_PROMOTE_LOCAL_BOOT_GATES=1`, or automatic when the server gate is inactive). |
| req-dev-validation-real-backend | [Real-Backend Fidelity](#real-backend-fidelity) | Implemented | Gate runs the real task backend, never `ImmediateBackend` |
| req-dev-validation-lean-boot | [Lean-Boot Independence Gate](#lean-boot-independence-gate) | Implemented | Fresh, isolated, lean-installed stack boots `core`; catches core→plugin-dep import leakage (`scripts/gate-lean`). Since 2026-08-10 a REQUIRED CI job (`product-lines.yml` `lean-boot`); local run optional (`TAP_PROMOTE_LOCAL_BOOT_GATES=1`, or automatic when the server gate is inactive). |
| req-dev-validation-api-fuzz | [Live-API Property Fuzz](#live-api-property-fuzz) | Implemented | schemathesis over the live Ninja OpenAPI schema (one reusable `api-fuzz.yml`, two callers): a REQUIRED promote gate (deterministic pinned seed, findings fail) + a nightly random-seed exploration lane (`api-fuzz-nightly.yml`, report-only); viewer-role differential is the open tail |
| req-dev-validation-canary-tier | [Canary Test Tier](#canary-test-tier) | Proposed | `-m smoke` blast-radius subset; does not substitute for the gate |
| req-dev-validation-known-broken | [Known-Broken Manifest](#known-broken-manifest) | Implemented | In-repo, ratchets down; named here as the house convention |
| req-dev-validation-collection-complete | [Collection Completeness](#collection-completeness) | Implemented | Every test file on disk is collected by the gate run; discovery not an allow-list; validates the validator |
| req-dev-validation-promote-hook | [Promote-Path Enforcement](#promote-path-enforcement) | Implemented | Reciprocal of `req-dev-multisession-promote-gate` |
| req-dev-validation-ratchet-harness | [Reusable Ratchet Harness](#reusable-ratchet-harness) | Implemented | `tap/ratchet.py` + `tap.guards` harness; every bespoke ratchet migrated onto it (provenance-schema sub-req deferred as YAGNI) |
| req-dev-validation-mypy-ratchet | [Static Typing Ratchet](#static-typing-ratchet) | Implemented | `mypy .` strict-mode error set frozen per file+error-code and ratcheting down; blocks new errors. Install-aware (filters to core + installed-plugin rows on both sides — see [spec-tap-plugin-validation-distribution.md](spec-tap-plugin-validation-distribution.md)) |
| req-dev-validation-suite-tiers | [Suite Tiering & Performance](#suite-tiering--performance) | Partially Implemented | xdist full + `--fast` lanes built (`scripts/test`); relevance-gated Gryphon-corpus selection built (coarse affected lane for the one dominant-cost corpus); profiled `slow` designations + full test-impact analysis + per-profile fast lane still to build (coupled to the streamlined boot profiles) |
| req-dev-validation-all-plugins-lane | [All-Plugins CI Lane](#all-plugins-ci-lane) | Proposed | Server-side lane that boots the full plugin union and runs the whole suite — the blocking all-plugins authority a focused local stack structurally cannot be once plugins leave the monorepo. Local validates what's installed here; this lane owns all-plugins truth. The boot record IS the known-good-set (BOM) it verifies. |
| req-dev-validation-product-line-lanes | [Per-Product-Line CI Lanes](#per-product-line-ci-lanes) | Implemented | Validate each product line (a plugin-pack + boot profile) on its own free GitHub-hosted runner, in parallel across lines — parallelism along the product axis, not arbitrary shards. `test_all` + `samsite` lanes green; `test_all` union lane wired as the promote gate. Ran on AWS CodeBuild 2026-07-08 → 2026-08-10, retired by the measured free-runner consolidation (identical job ~9 min; in-account-IAM rationale lapsed with the public plugin repos). |
| req-dev-validation-meta-integrity | [Guard-System Meta-Integrity](#guard-system-meta-integrity) | Partially Implemented | The gates must resist being disabled by a code push (who guards the guards). The enforcement *machinery* — harness, scanner engines, ratchet core, the runner + honesty meta-tests, CI/gate config, and the allowlists/vocabularies embedded in guards — is **review-always**; only a ratchet baseline *shrinking* and *coverage-adding* changes are self-safe directions. The real trust anchor is **out-of-band** (branch protection + required check + `CODEOWNERS`), because no in-repo check can protect itself; the in-repo layer makes tampering loud, the platform layer makes it blocked. Built: the in-repo loud layer (`-3`, guard-integrity guard) and the `CODEOWNERS` file; pending: the branch-protection settings (`-2`) that make `CODEOWNERS` bite. |

Leaf surfaces referenced by the Map are owned elsewhere: spawn-env smoke in [spec-dev-multisession-smoketest.md](spec-dev-multisession-smoketest.md), teardown in [spec-dev-multisession-teardown.md](spec-dev-multisession-teardown.md), the log-site scanner in [spec-tap-logging.md](spec-tap-logging.md), and the async-delivery tiers in [spec-tap-cares-task-backend.md](../tap_cares/specs/spec-tap-cares-task-backend.md) (`req-tap-cares-task-backend-backlog-2`). This spec does not re-specify them.

Keeping the validation authority itself **plugin-agnostic** — so evicting a plugin lifts its guards, ratchet-baseline rows, and declared Map surfaces out cleanly rather than stranding central references — is specified in [spec-tap-plugin-validation-distribution.md](spec-tap-plugin-validation-distribution.md). The install-aware ratchet filtering it defines (a plugin-spanning ratchet compares core + installed-plugin rows only) is what lets a focused local stack run the mypy ratchet and the profile-resolution guard green while this lane owns full-set truth.

### Validation Map
----
RID: `req-dev-validation-map`
Status: `Implemented`

The Validation Map is the spine of this spec and the single authoritative inventory of every validation surface in TAP. A surface that is not in the Map is, by definition, unaccounted-for. The Map is **generated from the code**, not hand-maintained: a guarded surface earns its row by being a discovered `Guard` (`tap.guards`), and a non-guard surface (a behavioral suite, a gate step, a manual/deferred procedure) earns its row from `tap.guards.surfaces.DECLARED_SURFACES`. Adding a validation surface therefore means adding its guard or its declared-surface entry — each carrying a requirement `rid` that is machine-checked to resolve — and regenerating; that addition is the reviewable decision. The Map records, per surface, its cadence and its honest guard status using the vocabulary below — including surfaces that are deliberately manual or deferred, so the validation posture and every gap are visible in one place rather than implied behind green checkmarks.

#### Guard-status vocabulary

- **CI-guarded** — failure is caught automatically by a committed test/gate that runs without human initiative (e.g. `pytest`).
- **Gate-guarded** — caught automatically by the pre-push gate ([Cold-Boot Smoke Gate](#cold-boot-smoke-gate)) before `origin/main` advances.
- **Manual (CI-unguarded by design)** — verified only when a human runs a documented procedure; labeled as such deliberately, not by oversight.
- **Named, deferred** — a known gap with an owning spec/backlog entry and a deferral trigger; not yet guarded.

#### The Map

The inventory below is **generated** from the code — the discovered `Guard`
classes (`tap.guards`) plus the declared non-guard surfaces
(`tap.guards.surfaces.DECLARED_SURFACES`) — by `manage.py guards --sync-map`, and
a meta-test (`test_spec_map_in_sync`) fails if this block drifts from that output.
So the guarded rows can never fall out of step with the guards that enforce them,
and every row's Requirement is machine-checked to resolve to a real requirement
(`test_guard_rid_resolves` / `test_declared_surface_rid_resolves`). Edit a guard or
`DECLARED_SURFACES`, then run `manage.py guards --sync-map`; do not hand-edit the
block. Rich per-surface rationale lives in each owning spec and in each guard's
`description` (`manage.py guards`), not duplicated here (`req-dev-validation-map-4`).

<!-- BEGIN GENERATED MAP — manage.py guards --sync-map -->

| Surface | Requirement | Cadence | Status | Enforced by |
| --- | --- | --- | --- | --- |
| `record_*` site tokens | `req-tap-cares-collector-job-model-15` | Per-commit (`pytest`) | CI-guarded | `tap_cares.guards.record_site` (via `tap/tests/test_guards.py`) |
| AI review (Unified AI Review harness) | `req-cicd-ai-review-ensemble` | Per-PR (advisory comment on every PR incl. forks) | Advisory (non-blocking by design — Phase 1 of req-cicd-ai-review-graduation) | `.github/workflows/ai-review-capture.yml` + `.github/workflows/ai-review.yml` shims → SHA-pinned `unified-ai-review` reusable workflows |
| All-plugins CI lane (free-runner fallback) | `req-dev-validation-all-plugins-lane` | CI + promote fallback (TAP_PROMOTE_CI_WORKFLOW) | Retained fallback — lane PROVEN GREEN in a real Actions run; superseded as the promote gate by the product-line `test_all` lane, kept as the sharded fallback | `.github/workflows/all-plugins.yml` (boots the `test_all` union, runs the full lane); `promote-to-main.sh` Step 2.6 runs it when `TAP_PROMOTE_CI_WORKFLOW=all-plugins.yml` |
| Assembled-instance health | `req-tap-health-exposure-4` | Per-commit (`pytest`) + per-spawn (`manage.py health --set readiness` gate) | Partially guarded — CI-guarded units + per-spawn exec gate; full live cold-boot run Named, deferred | `tap_health/tests/` + `spawn-session.sh` health gate; folds into the cold-boot cycle |
| Async-delivery — tier 1 (transactional integrity) | `req-tap-cares-task-backend-transactional-integrity-1` | Per-commit (`pytest`) | CI-guarded | `tap_cares` `TestTransactionalIntegrity` |
| Async-delivery — tiers 2–3 (worker/queue/lifecycle) | `req-tap-cares-task-backend-backlog-2` | Deferred | Named, deferred | backlog — no fork/queue/lifecycle harness yet |
| Authz coverage | `req-tap-auth-policy-9` | Per-commit (`pytest`) | CI-guarded | `tap.guards.authz` (via `tap/tests/test_guards.py`) |
| Canary tier | `req-dev-validation-canary-tier` | Pre-push + per-commit | Gate-guarded *(target)* — Named, deferred until implemented | blast-radius subset (target); not yet built |
| Cold-boot system cycle | `req-dev-validation-smoke-gate` | CI (`product-lines.yml` `cold-boot` job, REQUIRED via `gate`; tier-gated — docs/specs-tier diffs skip it, req-dev-validation-product-line-lanes-7) + optional local pre-push (`TAP_PROMOTE_LOCAL_BOOT_GATES=1`; automatic when the server gate is inactive) | Gate-guarded | `tap_boot/management/commands/cold_boot_gate.py` |
| Collection completeness | `req-dev-validation-collection-complete` | Per-commit (`pytest`) | CI-guarded | `tap.guards.collection_addopts`, `tap.guards.collection_completeness` (via `tap/tests/test_guards.py`) |
| Coverage-disposition integrity | `req-tap-traceability-disposition` | Per-commit (`pytest`) | CI-guarded | `tap.guards.disposition_integrity` (via `tap/tests/test_guards.py`) |
| Credential pattern leak guard | `req-tap-cares-secrets-credential-patterns` | Per-commit (`pytest`) | CI-guarded | `tap.guards.secret_pattern` (via `tap/tests/test_guards.py`) |
| Credential-bind provenance | `req-tap-auth-credential-bind-provenance` | Per-commit (`pytest`) | CI-guarded | `tap_auth.guards.credential_bind` (via `tap/tests/test_guards.py`) |
| Crypto Bill-of-Materials (every provider, not just OpenSSL) | `req-fips-crypto-bom-ci` | Per-commit (`pytest`) | CI-guarded (fail-closed) | `tap.crypto_bom` (via `tap/tests/test_crypto_bom.py`): fingerprints every ELF artifact for crypto-provider signatures (Go/Rust `ring`/`aws-lc`/`libsodium`/bundled-OpenSSL/…) and fails on any provider not dispositioned VALIDATED/out-of-boundary/unreached in `tap.crypto_providers` — catches the silent non-OpenSSL leak `tap.fips` cannot see (L17); scans the `test_all` plugin union |
| DCO sign-off trailers (both roads to main) | `req-cicd-dco-signoff` | Pre-push (`scripts/check-dco`, wired into `promote-to-main.sh`) + CI (`product-lines.yml` `dco` job) | Gate-guarded (enforcing since 2026-08-12, when CONTRIBUTING.md + DCO landed at the repo root as approved policy) | `scripts/check-dco` (every non-merge, non-bot commit added over origin/main carries `Signed-off-by`); the trailer itself is applied by `.githooks/prepare-commit-msg` |
| Dev passkey import stays shell-only | `req-tap-auth-passkey-dev-bootstrap` | Per-commit (`pytest`) | CI-guarded | `tap_auth.guards.dev_passkey_import` (via `tap/tests/test_guards.py`) |
| Direct-write coverage | `req-tap-auth-policy-9` | Per-commit (`pytest`) | CI-guarded | `tap.guards.direct_write` (via `tap/tests/test_guards.py`) |
| Direct-write exemption freshness | `req-tap-auth-policy-9-unused-exemption` | Per-commit (`pytest`) | CI-guarded | `tap.guards.direct_write` (via `tap/tests/test_guards.py`) |
| Family-B public surface (pre-boot/boot) | `req-service-boundary-family-b-surface` | Per-commit (`pytest`) | CI-guarded | `tap.guards.public_surface` (via `tap/tests/test_guards.py`) |
| FIPS mode enforcement (declared vs actual) | `req-cicd-base-image-lifecycle-6` | Per-boot (`docker/entrypoint.sh`) | Boot-gated (fail-closed) | `tap.fips` (`python -m tap.fips`): executes crypto and asserts a non-approved primitive is refused when TAP_FIPS_MODE=1 — proves the declared mode is enforced, never inspects files (D13/D15); TAP-ABORT on mismatch |
| Guard-system integrity | `req-dev-validation-meta-integrity-3` | Per-commit (`pytest`) | CI-guarded | `tap.guards.guard_integrity` (via `tap/tests/test_guards.py`) |
| Implementation claim code staleness | `req-tap-traceability-code-staleness` | Per-commit (`pytest`) | CI-guarded | `tap.guards.implements_code_staleness` (via `tap/tests/test_guards.py`) |
| Implementation claim integrity | `req-tap-traceability-roles` | Per-commit (`pytest`) | CI-guarded | `tap.guards.implements_integrity` (via `tap/tests/test_guards.py`) |
| Implementation claim shape | `req-tap-traceability-claim` | Per-commit (`pytest`) | CI-guarded | `tap.guards.implements_shape` (via `tap/tests/test_guards.py`) |
| Implementation claim staleness | `req-tap-traceability-staleness` | Per-commit (`pytest`) | CI-guarded | `tap.guards.implements_staleness` (via `tap/tests/test_guards.py`) |
| Implementation claim uniqueness | `req-tap-traceability-uniqueness` | Per-commit (`pytest`) | CI-guarded | `tap.guards.implements_uniqueness` (via `tap/tests/test_guards.py`) |
| JSON-file naming | `req-tap-json-naming` | Per-commit (`pytest`) | CI-guarded | `tap.guards.json_naming` (via `tap/tests/test_guards.py`) |
| Known-dupe group integrity | `req-tap-known-dupes` | Per-commit (`pytest`) | CI-guarded | `tap.guards.known_dupes` (via `tap/tests/test_guards.py`) |
| Lean-boot core independence (import-leakage class) | `req-dev-validation-lean-boot` | CI (`product-lines.yml` `lean-boot` job, REQUIRED via `gate`; tier-gated — docs/specs-tier diffs skip it, req-dev-validation-product-line-lanes-7) + optional local pre-push (`TAP_PROMOTE_LOCAL_BOOT_GATES=1`; automatic when the server gate is inactive) | Gate-guarded | `scripts/gate-lean` (isolated `tap_leanboot` stack, core-only venv; catches core→plugin-dep imports the full-venv cold-boot gate cannot) |
| Live-API property fuzz (schemathesis over the Ninja OpenAPI schema) | `req-dev-validation-api-fuzz` | CI (`product-lines.yml` `api-fuzz` job, REQUIRED via `gate`; dedicated `core_dev` stack; full-tier only) | Gate-guarded — in the `gate` aggregator's `needs` (2026-08-11); findings fail the step, verdict deterministic via a pinned `--seed` | schemathesis (pinned version + pinned seed, `uvx`, runner-side) against the live booted API — two passes, no-5xx + schema-conformance: unauthenticated (the auth wall must reject, never crash) and authenticated (in-job boot auth phase + minted DB session + CSRF pair, 200-canary fail-closed); the reusable `.github/workflows/api-fuzz.yml`, called in gate posture; viewer-role differential is the named next rung |
| Live-API property fuzz — nightly exploration (random seed) | `req-dev-validation-api-fuzz` | Nightly (`api-fuzz-nightly.yml`, cron `47 9 * * *` + `workflow_dispatch`) | Report-only (by design) — the same reusable `api-fuzz.yml` in exploration posture: random seed, deep example budget, `fail_on_findings: false`; a finding is a `::warning::` + artifact, never a red | `.github/workflows/api-fuzz-nightly.yml` → `api-fuzz.yml` (seed empty/random, `max_examples: 200`) — discovers NEW bugs off the promote path so a fresh finding never blocks a merge; triage → fix → bump the gate seed |
| Log-site tokens | `req-tap-logging-site-id-scanner` | Per-commit (`pytest`) | CI-guarded | `tap.guards.log_site_baseline`, `tap.guards.log_site_format`, `tap.guards.log_site_uniqueness` (via `tap/tests/test_guards.py`) |
| Migration completeness (`makemigrations --check`) | `req-dev-validation-smoke-gate` | Pre-push (`cold_boot_gate` step `schema:makemigrations`) | Gate-guarded | `cold_boot_gate` step `schema:makemigrations` |
| Per-plugin crypto posture (conformance) | `req-fips-crypto-bom-conformance` | Per-plugin (`validate_plugin`; `--strict` in conformance CI) | Conformance-guarded (warn; strict→fail) | `tap_plugins.validate` `crypto-providers` check → `tap.crypto_bom.scan_plugin`: reports a plugin's shipped/declared crypto providers so a leak is visible at authoring time |
| Per-plugin repo CI (reusable workflow) | `req-tap-plugin-extdev-repo-ci` | Per-PR in external plugin repos (`workflow_call`) | In development — conformance job is the solid core; boot-and-test is the dial-in surface for Aug-1 | `.github/workflows/plugin-ci.yml` — `validate_plugin --strict` against a pinned core harness on free runners, plus an opt-in boot-and-test job |
| Per-product-line CI lanes (free GitHub runners) | `req-dev-validation-product-line-lanes` | Pre-push (promote-triggered `test_all` union) + CI (every line on PR; tier-gated — docs-tier diffs skip the lanes, specs-tier runs `test_all` only, req-dev-validation-product-line-lanes-7) | Gate-guarded — both lanes (`test_all`, `samsite`) proven green; the `test_all` union lane is the promote gate (option B). Ran on AWS CodeBuild until the measured ~9-min free-runner spike retired it (Terraform/account teardown pending, deliberately last) | `.github/workflows/product-lines.yml` (per-line free `ubuntu-latest` runners: `test_all` union + `samsite`); `promote-to-main.sh` Step 2.6 dispatches `line=test_all` and blocks on it (req-dev-multisession-ci-gate) |
| Per-profile boot resolution | `req-dev-validation-smoke-gate` | Per-commit (`pytest`) + pre-push (`cold_boot_gate`) | CI-guarded + Gate-guarded | `tap_boot.guards.profile_resolution` (via `tap/tests/test_guards.py`) |
| Plugin compatibility floor (requires_tap) | `req-tap-plugin-extdev-compat-floor` | Pre-boot (`python -m tap.preboot`) + author-time (`validate_plugin`) | CI-guarded | `tap.preboot._requires_tap_gate` (reject-at-boot) + the `requires-tap` `validate_plugin` check; unit-guarded by `tap/tests/test_core_version.py` and `tap/tests/test_preboot.py`, exercised end-to-end by the cold-boot gate (grid_fixtures declares a floor) |
| Plugin release SBOM (identity + conformance gates) | `req-cicd-sbom-10` | Per-plugin-release (plugin-release-sbom reusable workflow) | CI-guarded | `scripts/sbom/plugin_release.py` fail-closed gates before wheel/SBOM attestation; `tap/tests/test_sbom_plugin_release.py` |
| Plugin report contract | `req-tap-plugin-arch-install-registry-3` | Per-commit (`pytest`) + on every report build | CI-guarded | `tap_plugins/tests/test_report.py` (schema validation) |
| Read-only search write detection | `req-grid-search-readonly.sec-6` | Per-commit (`pytest`) | CI-guarded | `tap_grid/tests/test_search_readonly_guard.py` |
| Recurring-task uniqueness | `req-tap-cares-task-backend-recurring-scope-4` | Per-commit (`pytest`) | CI-guarded | `tap_cares.guards.recurring` (via `tap/tests/test_guards.py`) |
| Referenced RID integrity | `req-docs-rid-integrity` | Per-commit (`pytest`) | CI-guarded | `tap.guards.rid_integrity` (via `tap/tests/test_guards.py`) |
| Requirement accounting (Unaccounted ratchet) | `req-tap-traceability-accounting` | Per-commit (`pytest`) | CI-guarded | `tap.guards.unaccounted_ratchet` (via `tap/tests/test_guards.py`) |
| SBOM canary guard (TAP-specific truths) | `req-cicd-sbom-7` | Per-publish (publish-images manifest job) | CI-guarded | `scripts/sbom/generate.py` `check_canaries` before attestation; `tap/tests/test_sbom_generate.py` |
| SBOM conformance (schema + minimum elements) | `req-cicd-sbom-11` | Per-publish (publish-images manifest job) | CI-guarded | `scripts/sbom/generate.py` fail-closed gates before attestation; `tap/tests/test_sbom_generate.py` |
| Schedule grift target integrity | `req-tap-cares-collector-model-10` | Per-commit (`pytest`) | CI-guarded | `tap_cares.guards.schedule_grift` (via `tap/tests/test_guards.py`) |
| Scripted plugin release pre-release guard (release-plugin) | `req-dev-workspace-release` | Operator-invoked at plugin release time (`scripts/release-plugin.sh`) | Built 2026-07-09 — refuses a red release; pure pin-bump core unit-guarded | `scripts/release-plugin.sh` runs `validate_plugin --strict` + the plugin suite in-container before tagging (refuse-on-red), then bumps consuming boot profiles via `tap.plugin_release`; the bump core is unit-guarded by `tap/tests/test_plugin_release.py` |
| Secret leak guard | `req-tap-cares-secrets-leak-guard` | Per-commit (`pytest`) | CI-guarded | `tap.guards.secret_leak` (via `tap/tests/test_guards.py`) |
| Secrets-root resolution single source | `req-tap-cares-secrets-root-resolution` | Per-commit (`pytest`) | CI-guarded | `tap.guards.secrets_root_resolution` (via `tap/tests/test_guards.py`) |
| Service-layer boundary coverage | `req-service-boundary-guard` | Per-commit (`pytest`) | CI-guarded | `tap.guards.service_boundary` (via `tap/tests/test_guards.py`) |
| Service-layer boundary import encapsulation | `req-service-boundary-inviolability` | Per-commit (`pytest`) | CI-guarded | `tap.guards.service_boundary_imports` (via `tap/tests/test_guards.py`) |
| Spawn-env health | `req-dev-multisession-smoketest-runtime` | Per-spawn | Manual (CI-unguarded by design) | `spec-dev-multisession-smoketest.md` documented procedure |
| Spec-marker resolution | `req-tap-test-spec-linkage` | Per-commit (`pytest`) | CI-guarded | `tap.guards.spec_marker` (via `tap/tests/test_guards.py`) |
| Static typing (mypy) | `req-dev-validation-mypy-ratchet` | Per-commit (`pytest`) | CI-guarded | `tap.guards.mypy` (via `tap/tests/test_guards.py`) |
| System FIPS-provider gate (core + all plugins, global) | `req-fips-crypto-bom-system-gate` | Per-boot (`docker/entrypoint.sh`, when `TAP_FIPS_MODE=1`) | Boot-gated (fail-closed) | `python -m tap.crypto_bom --gate`: under FIPS mode, scans the assembled environment (core + every installed plugin) and TAP-ABORTs on any non-validated provider unless an OPERATOR `fips_waivers` entry (boot profile, mandatory reason) excuses it — a plugin cannot excuse itself (declare-vs-decide) |
| Teardown correctness | `req-dev-multisession-teardown-cleanup` | Per-despawn | Manual (CI-unguarded by design) | `spec-dev-multisession-teardown.md` documented procedure |
| Verified-status evidence | `req-tap-traceability-status` | Per-commit (`pytest`) | CI-guarded | `tap.guards.verified_evidence` (via `tap/tests/test_guards.py`) |
| Web render smoke (login/landing) | `req-web-nav-chrome-read-free-3` | Per-commit (`pytest -m smoke`) | CI-guarded | `tap_auth/tests/test_login_wall.py` (`@pytest.mark.smoke`) |
| Wheel-cache seed integrity (verify-before-seed) | `req-cicd-supply-chain-provenance-2` | Per-boot (entrypoint) + per-commit (`pytest`) | CI-guarded | `docker/seed_manifest.py` verify in `docker/entrypoint.sh` (fail-closed TAP-ABORT); `tap/tests/test_seed_manifest.py` |
| Workflow least privilege (token boundary) | `req-cicd-runner-least-privilege` | Per-commit (`pytest`) | CI-guarded | `tap.guards.workflow_least_privilege` (via `tap/tests/test_guards.py`) |

<!-- END GENERATED MAP -->

Rows marked *(target)* describe the intended state once this spec is implemented; their guard status is honestly `Named, deferred` until then. The Map is regenerated (`manage.py guards --sync-map`) in the same change as any new or retired validation surface, and reviewed when it changes — the change to the guard/declared-surface set (and the resulting block diff) *is* the visible decision.

**Collection-scope caveat (a guard that isn't collected does not guard).** A test that the default `pytest` run does not collect is **invisible to the gate** — it passes when named explicitly and silently protects nothing otherwise. This let the 2026-07-01 login regression ship green: `tap_auth`, `tap_boot`, and `tap_cares` all sat outside the `testpaths` **allow-list**, so their tests (including `test_login_wall.py`'s render assertions) were never in the gate. The allow-list is fail-open over a scattered per-app layout — a new app is uncollected until someone remembers to list it. The fix is structural, not another list entry: `pyproject.toml` no longer sets `testpaths`, so pytest **discovers** every test file from the repo root (an ignore-list, fail-safe), and [Collection Completeness](#collection-completeness) asserts the outcome so the scope can never silently narrow again. See that requirement.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-validation-map-1 | Map is authoritative | Implemented | Every validation surface in the repository has exactly one row in the Map. A surface absent from the Map is treated as unaccounted-for. | The Map is generated from the discovered guards + `DECLARED_SURFACES`, so a guard/surface with no row cannot exist. |
| req-dev-validation-map-2 | Honest guard status | Implemented | Each row's guard status uses the defined vocabulary; manual/deferred surfaces are labeled explicitly, never implied. | Counters the false-confidence failure mode. Status is carried per-guard and per-declared-surface, rendered into the row. |
| req-dev-validation-map-3 | Co-change discipline | Implemented | Adding, moving, or retiring a validation surface anywhere REQUIRES updating its Map row in the same change. | Enforced mechanically: adding a guard/surface changes the generated block, and `test_spec_map_in_sync` fails until it is regenerated. |
| req-dev-validation-map-4 | References, not copies | Implemented | The Map points at owning specs; it does not duplicate their requirements or acceptance criteria. | Prevents cross-spec drift. Rich "why" lives in guard `description` + owning specs. |
| req-dev-validation-map-5 | Generated, not hand-maintained | Implemented | The Map inventory is generated from the discovered guards + `DECLARED_SURFACES` by `manage.py guards --sync-map`; a meta-test fails if the committed block drifts from that output. Guarded rows cannot fall out of step with the code that enforces them. | `tap/tests/test_guards.py::test_spec_map_in_sync`. Closes the stale-Map-row drift class (an "Enforced by" pointer going stale unnoticed). |
| req-dev-validation-map-6 | Every surface resolves to a requirement | Implemented | Each guard's `rid` and each declared surface's `rid` resolves to a requirement actually defined in some spec (RID heading or requirements-table cell), not merely referenced. A surface cannot point at a requirement that does not exist. | Replaces the prior "map_row ∈ prose table" check. Caught `req-dev-validation-mypy-ratchet` being referenced-but-undefined. |

### Cold-Boot Smoke Gate
----
RID: `req-dev-validation-smoke-gate`
Status: `Implemented`

The gate is an ordered, deterministic, halt-on-failure check that a freshly-built environment can boot from zero and complete one real end-to-end cycle. It adopts the established shape of [spec-dev-multisession-smoketest.md](spec-dev-multisession-smoketest.md): an ordered set of checks with expected outcomes, run top-to-bottom, where any failure halts and is reported. It runs **inside the existing compose image** — never a reimplemented environment — because the container's Python build differs from a stock host interpreter and an environment that does not reproduce the image will diverge.

The cycle, in order:

1. Fresh database (no pre-existing state).
2. `migrate` applies cleanly from zero.
3. `import_plugin_grift --all` seeds plugin data (strict; a failed bundle fails the gate).
4. One real collector runs to a terminal `CollectionJob` state through the real task backend ([Real-Backend Fidelity](#real-backend-fidelity)).
5. One scheduler fire is evaluated.
6. Resulting grid state is asserted (the collector's expected nodes/edges/batch landed).

It is explicitly **not** broad correctness coverage — that is the canary tier and the deferred per-flow suites. It is one ordered run on a fresh database with no per-test isolation; this is intentional and matches the per-session isolated-Postgres model rather than fighting transactional-rollback semantics. Wall-clock budget: **correctness and real-backend fidelity over speed**. A 10+ minute promote that the developer steps away from is explicitly acceptable (the human is offline during it by design); the gate is not optimized for latency at the cost of fidelity. The cold-boot cycle is fixed; the canary tier is the tunable lever if total time must be bounded.

**As built (Phase 1).** The gate is `manage.py cold_boot_gate` (in `tap_boot`), the single artifact local dev, `scripts/gate`, and `scripts/promote-to-main.sh` all invoke identically. `scripts/gate` provisions a **fresh scratch database** on the running stack's Postgres (a management command cannot cleanly `migrate`-from-zero its own connection), points the command's `DATABASE_URL` at it, and drops it on exit — so the cycle runs inside the existing compose image (req-...-5) without a second stack or touching the session DB. The ordered steps: `schema:migrate` (createcachetable→migrate from zero) → `schema:makemigrations` (`--check`) → `profiles:resolve` (every *installable* profile resolves; see the per-profile axis below) → `seed:boot-test_all` (strict `test_all` union boot — the seed path across every plugin; formerly `seed:boot-base` before the 2026-07-03 baseline flip renamed `base`→`test_all`) → `collector:cycle` (real backend + in-process drain + PRODUCED_BATCH assertion, scheduler evaluated in the same drain) → `health`. **Measured wall-clock: ~66–107s** (green path). Because `seed:boot-test_all` boots the full plugin union, the gate is a **full-install** check: the promote runs it with `--skip-if-not-installable`, so a focused session (where `test_all` is not installable) skips it loudly and the [all-plugins CI lane](#all-plugins-ci-lane) owns full cold-boot truth (`req-dev-validation-smoke-gate-8`). `profiles:resolve` is install-aware through the same shared filter (`tap_boot.profile.installable_profile_ids`) that backs both the pytest profile-resolution guard and this skip predicate. The collector fired is the **deterministic offline canary** `grid_fixtures:canary` (`--collector` overrides it to drive a real domain collector): a `CollectorBase` in the neutral `grid_fixtures` fixtures plugin that emits a fixed two-node/one-edge `grid_fixtures__*` GRIFT batch from inline constants — **no network, no credentials, no filesystem read** — so the gate's real-backend cycle positively asserts grid mutation without ever flaking on an upstream being down. It is self-contained (emits its own plugin's vocabulary) and, like all of `grid_fixtures`, installs only into dev/test profiles, never a lean customer profile. Per-commit guard: `plugins/grid_fixtures/tap_plugin/grid_fixtures/tests/test_canary_collector.py`.

**Per-profile axis (agenda item 5).** The gate cold-resolves **every shipped `boot/*.boot.json` profile** against the live registries (`boot --check` → the zero-mutation pre-resolution the real boot runs), rather than making pytest discovery plugin-aware (which would fight the design and require de-hardcoding lotr from the core suites). This is the axis that catches the same bug class as the 2026-07-02 `base`-profile break — and, on the build of this gate, immediately caught a live one: `boot/samsite.boot.json`'s four fire-collector keys were still on their stale module-path scopes (`tap_plugin.aws_core.collectors.boto3_collector.collector:boto3`) after the collector-identity refactor repointed only the grift `SCHEDULED_TARGET` edges, so `boot --profile samsite` — the live-demo profile behind the active roadmap Done-Test — aborted at resolution. Fixed to `scope:key` (`aws_core:boto3`, …) and regression-locked by `tap_boot/tests/test_shipped_profiles_resolve.py`. Firing collectors that need live network/creds (aws, github) is out of the hermetic gate by design; the break lives in resolution, before any firing.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-validation-smoke-gate-1 | Cold boot from zero | Implemented | The gate starts from a fresh database; `migrate` applies with no pre-existing schema/data. | `scripts/gate` provisions a fresh scratch DB; step `schema:migrate`. |
| req-dev-validation-smoke-gate-2 | Seed is strict | Implemented | Strict seed; any failed bundle fails the gate. | Step `seed:boot-test_all` runs the real `test_all` (union) boot (population seeds through the same `seed_plugin` op `import_plugin_grift` uses); aligns with `req-dev-multisession-spawn-import-strict-1`. Renamed from `seed:boot-base` in the 2026-07-03 baseline flip. |
| req-dev-validation-smoke-gate-3 | One real cycle | Implemented | A collector reaches a terminal `CollectionJob` state and a scheduler fire is evaluated within one ordered run. | Step `collector:cycle`; the in-process drain dispatches the scheduler queue in the same run. |
| req-dev-validation-smoke-gate-4 | Grid state asserted | Implemented | The cycle's expected grid mutation is positively asserted, not inferred from absence of error. | Counters the false-confidence failure mode. Asserted via `PRODUCED_BATCH` edges (disposition `imported`); a documented idempotent no-op (e.g. `DIFF_EMPTY`) is a valid SUCCESSFUL outcome, not a gate failure. **Drift resolved (2026-06-11):** `req-grid-edge-produced-batch` is built; the `grift_batches` field is removed. |
| req-dev-validation-smoke-gate-5 | Runs in the compose image | Implemented | The gate executes inside the existing compose stack image, not a reconstructed environment. | The container Python build is non-stock. `scripts/gate` runs the command via `dc exec web`. |
| req-dev-validation-smoke-gate-6 | Halt and report | Implemented | The first failing check halts the run and reports the failing step; the gate exits non-zero. | Verified live (a bogus `--collector` halts at step 5, skips step 6, exits 1). |
| req-dev-validation-smoke-gate-7 | Every installable profile resolves | Implemented | The gate cold-resolves every shipped boot profile whose plugins are installed in this stack against the live registries (per-profile axis); a rotted fire-collector key or missing plugin/bundle fails the gate. | Step `profiles:resolve` + per-commit `test_shipped_profiles_resolve.py`. Install-aware via the single shared filter `tap_boot.profile.installable_profile_ids` (the same one the pytest guard and the focused-skip check below use — one definition, no drift). On a full stack that is every profile. Caught + fixed the live `samsite` break on build. 2026-08-09: samsite re-homed out of `boot/` (`req-boot-bootstrap-samsite-rehome`); its resolve coverage now lives in the plugin's shipped suite — see the Map's samsite-record row. |
| req-dev-validation-smoke-gate-8 | Focused-stack skip (full-install gate) | Implemented | Step `seed:boot-test_all` boots the whole `test_all` union, so this gate is inherently a **full-install** check. On a focused stack (a plugin subset installed — `test_all` not installable) the promote invokes it with `--skip-if-not-installable`; the gate emits a loud SKIP and exits 0, delegating full cold-boot truth to the all-plugins CI lane. | The local gate validates what's installed; the [all-plugins CI lane](#all-plugins-ci-lane) (`req-dev-validation-all-plugins-lane`) boots `test_all` on a full-install runner and owns full-set truth. Mirrors the install-aware pytest lane (`req-dev-validation-collection-complete-4`) and profile-resolution guard. The full-stack predicate is `"test_all" in installable_profile_ids(...)`. A standalone `scripts/gate` (no flag) still runs fully — the skip is opt-in, so the gate stays honest for a full manual check. |

### Real-Backend Fidelity
----
RID: `req-dev-validation-real-backend`
Status: `Implemented`

This is the load-bearing requirement. The gate MUST exercise the cycle against the **real DB-backed task backend**, never the pytest `ImmediateBackend` substitute. `ImmediateBackend` runs the task inline in the enqueuing transaction, which masks exactly the bug class that motivated this spec: a row enqueued in a transaction a separate worker connection cannot yet see. A gate that runs under the substitute backend would have stayed green through the Steady-Queue incident and is therefore not a gate at all for this failure class.

This positions the gate as the real-backend, post-commit, in-process-drain tier: higher fidelity than any `ImmediateBackend` test, and complementary to — not a replacement for — the deferred out-of-process real-worker tiers owned by `spec-tap-cares-task-backend.md` `req-tap-cares-task-backend-backlog-2` (tier 2: real `SteadyQueueBackend` + worker polled for terminal state; tier 3: fork-safety CI smoke job). Those tiers remain `Named, deferred` in the Map; this requirement does not absorb them.

**Mechanism (Phase-0 proven, Phase-1 shared).** The in-process drain — extracted to `tap_cares/dev_validation.py:drain_ready_executions` and shared by the Phase-0 spike and the Phase-1 gate — is the production Steady Queue primitives without the supervisor/fork/thread-pool/polling-loop that normally *drive* them: `ScheduledExecution.dispatch_next_batch()` → `ReadyExecution.objects.claim(queues, limit, process_id)` → `ClaimedExecution.perform()`, looped to empty or a deadline. Two concrete facts established by the Phase-0 spike (`tap_cares/management/commands/dev_validation_spike.py`, run inside the compose image under real `tap.settings`): (1) `ReadyExecution.claim` short-circuits to `[]` when `process_id is None`, so the drain MUST register a synthetic `steady_queue` `Process` (no heartbeat/supervisor/fork) and pass its id, deregistering after; (2) under `manage.py` (autocommit, not pytest), `run_collection`'s `transaction.on_commit` enqueue fires immediately and the `Job`+`ReadyExecution` rows are committed before the drain claims them — the real commit boundary `ImmediateBackend` never crosses. The spike proved the linchpin end-to-end (real enqueue → commit → drain → terminal `CollectionJob`) and proved teeth (no-drain ⇒ job stays `READY` ⇒ non-zero exit; a `FAILED` collector ⇒ non-zero exit surfacing the readiness reason). Grid-state assertion counts `CollectionJob --PRODUCED_BATCH--> Batch` edges with `disposition="imported"` (the Phase-0 `grift_batches` drift is now closed — see the note on `req-dev-validation-smoke-gate-4`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-validation-real-backend-1 | Not `ImmediateBackend` | Implemented | The gate configures the real DB-backed task backend; `ImmediateBackend` is never used in the gate path. | `cold_boot_gate` refuses to run under `ImmediateBackend` (`_guard_real_backend`). |
| req-dev-validation-real-backend-2 | Terminal state via real backend | Implemented | The collector reaches a terminal `CollectionJob` state through the real backend's enqueue→commit→drain path, not an inline call. | Shared `drain_ready_executions`: synthetic `Process` + `ReadyExecution.claim` + `ClaimedExecution.perform` loop; `claim` requires a non-null `process_id`. Verified live (SUCCESSFUL, 1 batch imported). |
| req-dev-validation-real-backend-3 | Defers tiers 2–3 honestly | Implemented | Out-of-process real-worker concurrency/fork/lifecycle coverage is explicitly out of scope here and tracked under `req-tap-cares-task-backend-backlog-2`. | No scope absorption; no parallel vocabulary. |

### Canary Test Tier
----
RID: `req-dev-validation-canary-tier`
Status: `Proposed`

A `@pytest.mark.smoke` marker designates the high-signal canary subset of the fast test suite: tests whose failure means "the foundation moved, dive deep," as opposed to "one feature regressed." The promotion criterion is **blast radius, not importance**: a test earns the marker only if it sits on the trunk — its failure predicts mass downstream failure (e.g. service-layer Entity creation, plugin GRIFT import landing on the grid, registry collector resolution). A narrow test of one feature's edge case is not a canary even when the feature is important. The criterion is deliberately answerable in seconds at test-authoring time, by the author — the only person who reliably knows a test's blast radius — because retrofitting canary designation later is archaeology that does not happen.

The canary tier runs under the standard fast-test environment (including `ImmediateBackend`) and therefore **does not and cannot substitute for** the [Cold-Boot Smoke Gate](#cold-boot-smoke-gate) / [Real-Backend Fidelity](#real-backend-fidelity): tagging a unit test `smoke` does not close the real-backend gap. The gate is both: the cold-boot real-backend cycle *and* `pytest -m smoke`.

Canary membership is governed as a bounded, reviewed set (see [Known-Broken Manifest](#known-broken-manifest) for the shared house pattern): the marker lives in the test, but the *set* of markers is enumerated with a one-line "what breaks downstream if this fails" per entry, and a fitness cap (runtime or count) forces eviction when a better-upstream canary supersedes one.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-validation-canary-tier-1 | Marker exists | Proposed | `@pytest.mark.smoke` is a registered marker; `pytest -m smoke` selects the canary subset. | |
| req-dev-validation-canary-tier-2 | Blast-radius criterion | Proposed | A test earns `smoke` only if its failure predicts broad downstream failure (trunk, not branch). Importance alone is explicitly insufficient. | |
| req-dev-validation-canary-tier-3 | Authored, not retrofitted | Proposed | Canary designation is applied at test-authoring time and is part of the test-writing workflow, not a later audit. | |
| req-dev-validation-canary-tier-4 | Does not substitute for the gate | Proposed | The canary tier never replaces the real-backend cold-boot gate; both run. | The substitution-backend blind spot. |
| req-dev-validation-canary-tier-5 | Bounded, justified membership | Proposed | The canary set is enumerated with a per-entry downstream-failure justification and a fitness cap that forces eviction. | Same house pattern as the known-broken manifest. |

### Known-Broken Manifest
----
RID: `req-dev-validation-known-broken`
Status: `Implemented`

Known-broken state is enumerated in a committed manifest, never held in human memory. The gate exits non-zero on any failure **not** listed, and also on any listed entry that no longer fails (stale entries are removed so the manifest ratchets toward zero). Each entry carries a one-line reason and owning context. The manifest is seeded at landing with whatever is genuinely known-broken at that moment — possibly empty.

This requirement also **names, once, the house convention** the repository has independently reached for repeatedly: a *bounded, reviewed, in-repo manifest that ratchets down* is TAP's canonical mechanism for honest coverage accounting. Its instances are the log-site-ID baseline (`spec-tap-logging.md`), the authz-coverage baseline (`spec-tap-auth-v0.md` `req-tap-auth-policy-9`), the direct-write-coverage baseline (`tap/guards/baselines/direct_write.txt`), the Gryphon executor branch-coverage floor (`tap_grid/gryphon/coverage-baseline.json`, per the Gridkin executor-branch-coverage requirement in the gryphon_playground plugin repo), this known-broken manifest, canary-set membership ([Canary Test Tier](#canary-test-tier)), and honest `CI-unguarded` spec-status labeling (`spec-tap-cares-task-backend.md`). New honesty mechanisms SHOULD follow this pattern rather than invent a parallel one — and, per [Reusable Ratchet Harness](#reusable-ratchet-harness), should increasingly share its *implementation*, not just its shape.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-validation-known-broken-1 | In-repo, not in memory | Implemented | Known-broken is a committed manifest; the gate never depends on a human remembering an exclusion. | `tap_boot/tap_boot.cold_boot_gate_known_broken.json`. |
| req-dev-validation-known-broken-2 | Ratchets down | Implemented | A failure not in the manifest fails the gate; a manifest entry that no longer fails also fails the gate until removed. | Both directions verified live (tolerate path GREEN; stale entry → RED). |
| req-dev-validation-known-broken-3 | Per-entry justification | Implemented | Each entry has a one-line reason and owning context. | Missing `step`/`reason` fails the gate. |
| req-dev-validation-known-broken-4 | Seeded at landing | Implemented | The manifest is seeded with whatever is known-broken when the gate lands; an empty manifest (effective strict mode) is the preferred state. | Seeded **empty** — the gate lands green with no known-broken. |
| req-dev-validation-known-broken-5 | Named house convention | Implemented | The bounded-reviewed-ratcheting-manifest pattern is named here as canonical; other honesty mechanisms reference it rather than reinvent. | One vocabulary across sessions. |

### Collection Completeness
----
RID: `req-dev-validation-collection-complete`
Status: `Implemented`

Every test file that exists on disk MUST be collected by the default full-repo `pytest` run, except a small, justified set of intentional exclusions. This is the guard that **validates the validator**: without it, "green" silently means "the subset pytest happened to collect passed," and the subset can drift narrower than the code with no signal.

#### Status Details

This requirement exists because of a concrete miss. The 2026-07-01 login regression shipped green while `test_login_wall.py` was red, because `pyproject.toml` `testpaths` was an **allow-list** (`["tap", "tap_grid", …]`) that omitted whole apps — `tap_auth`, `tap_boot`, `tap_cares` — so their tests were never collected by the gate. No ordinary test can catch this: the failure is in the collection scope, one layer beneath the tests.

#### Implementation

- **Discovery, not an allow-list.** `pyproject.toml` sets no `testpaths`; pytest discovers every `test_*.py`/`*_test.py` from the repo root, minus `norecursedirs` (`.venv`, `node_modules`, `build`, `dist`, dot-dirs) and the explicit `--ignore`s in `addopts`. Discovery is fail-safe (a new test dir is collected automatically); an allow-list is fail-open (a new app is uncollected until someone remembers it). The reversibility argument of `spec-security-posture.md` applies: coverage config should fail toward over-collection, never under.
- **Outcome-based guard.** `tap/tests/test_collection_completeness.py` enumerates the on-disk test files and diffs them against the set a full `pytest --collect-only .` run collects (real `addopts`, marker filter overridden to a tautology so opt-in `-m` tests are not false orphans). Any file on disk but not collected fails the guard, naming the orphan. Being outcome-based, it catches every cause — a re-introduced `testpaths`, a stray `--ignore`, an import error that drops a module — not just the original mechanism.
- **Single visible ledger of holes.** The guard's `_IGNORED_DIRS` is the one place deliberate coverage exclusions live; each entry is justified and MUST correspond to an `--ignore=` in `addopts`. A real `--ignore` not mirrored there surfaces as an orphan, forcing the exclusion to be recorded rather than hidden. The ledger currently holds one entry: `_dev-plugins`, the editable plugin-repo checkouts created by `spawn --dev-plugins` (`spec-dev-plugin-workspace.md`). Those are working copies of *other repositories* that happen to sit inside the worktree; collecting them would make this lane's result depend on which plugins a developer has checked out — the same non-determinism the ignore-list design exists to prevent — and it is the exact behaviour of a normal session, where those plugins are git-installed into the already-pruned `.venv`. Their coverage is owned by their own repo CI and by `release-plugin.sh`'s pre-release gate.

#### Development

This is the honest-coverage-accounting discipline of this spec turned on the test suite itself: the Map's `CI-guarded` rows each *assume* their test is collected, and nothing verified that assumption until now. The guard is cheap (one `--collect-only` subprocess, no test execution) and structural, so the class cannot silently recur.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-validation-collection-complete-1 | Discovery, not allow-list | Implemented | `pyproject.toml` sets no `testpaths`; test collection is repo-root discovery minus an explicit ignore-list. | Fail-safe over the scattered per-app layout. |
| req-dev-validation-collection-complete-2 | Every file collected | Implemented | A guard asserts every on-disk `test_*.py`/`*_test.py`, minus justified `_IGNORED_DIRS`, is collected by a full-repo run. | `tap/tests/test_collection_completeness.py`. |
| req-dev-validation-collection-complete-3 | Justified holes only | Implemented | Each intentional exclusion is a justified `_IGNORED_DIRS` entry mirrored by an `addopts` `--ignore`; an unmirrored ignore fails the guard. | The single visible ledger of coverage holes. |
| req-dev-validation-collection-complete-4 | Install-aware for plugins | Implemented | Plugin tests live inside the package (`tap_plugin/<slug>/tests/`); the walk collects *installed* plugins' tests, and the guard subtracts *uninstalled* plugins' test files (via `tap.plugin_testing`) as a legitimate, delegated hole. Fully strict in the all-plugins lane (nothing uninstalled); relaxed per focused stack, with that coverage owned by [`req-dev-validation-all-plugins-lane`](#all-plugins-ci-lane). | Not a silent narrowing: the delegation is to a named, gated lane. Distinct from `_IGNORED_DIRS` (permanent, hand-listed holes) — this hole is dynamic per stack. |

### Reusable Ratchet Harness
----
RID: `req-dev-validation-ratchet-harness`
Status: `Implemented`

> **BUILT (2026-07-02, session/validation-creation).** Extracted on demand once the
> shape had its third-plus caller (per the discipline below). `tap/ratchet.py` holds
> the Django-free compare core (`ratchet_ceiling` / `ratchet_floor` /
> `read_baseline_set`); `tap.guards` adds the `Guard` / `CeilingRatchet` base and the
> filesystem-discovered, distributed guard set. Every bespoke ratchet migrated onto it
> (authz, direct-write, log-site ×3, gryphon coverage-floor, mypy, known-broken). The
> one deferred sub-req is the provenance-carrying baseline schema (`-2`), YAGNI until a
> consumer needs it. The section below records the original demand signal + design.

#### Why now (the demand signal)

The ratcheting-baseline pattern is no longer one mechanism — it is at least four, and
two of them (the direct-write-coverage baseline and the Gryphon executor
branch-coverage floor) landed *on the same day, in independent sessions, blind to
each other*, each hand-rolling its own "measure → compare to a committed number/set →
fail on regression → tell the human to bump on improvement" loop. Independent
convergence on one shape is the signal that the shape wants a shared core. The cost
of not extracting it is N slightly-different failure messages, N slightly-different
ratchet-direction bugs, and N places the dev-validation gate must special-case when
it comes to invoke them.

#### What generalizes vs. what stays bespoke

The **measurement** is irreducibly per-surface and MUST stay bespoke — a static AST
scan (log-site, authz), a runtime `coverage.py` run (Gryphon branch, direct-write), a
full smoke cycle. Do not try to unify measurement; that way lies a framework nobody
can read.

What generalizes is everything *after* the current value is in hand:

- **Baseline artifact schema.** A common committed shape: the ratchet value
  (scalar / count / set / manifest), plus provenance (`measured_at_commit`, what was
  measured over, a human `note`). Today each invents its own file format
  (`.json`, `.txt`, inline constant).
- **Compare + ratchet-direction.** One helper each for the two directions —
  *floor* (must not decrease; coverage %) and *ceiling→zero* (must not increase;
  uncovered-count / known-broken). Both share: fail on regression with a uniform,
  actionable message; on an *un-locked improvement*, fail-or-warn telling the human to
  bump the baseline so gains are captured (the single most-repeated hand-rolled bit).
- **Honest-status reporting.** Every ratchet already owes a Validation Map row with a
  guard-status label; the harness can emit the row stub and the standard
  `Manual (CI-unguarded by design)` vs `CI-guarded` phrasing so labeling can't drift.
- **Sub-point tolerance + integer flooring** for float metrics (the Gryphon ratchet's
  `int(current) < floor` rule) so wobble is not a false regression.

Sketch: a small `tap/ratchet.py` exposing `ratchet_floor(current, baseline_path, ...)`
and `ratchet_ceiling(current, baseline_path, ...)` over a shared baseline schema, with
uniform exit codes and messages. The existing callers (Gryphon
`scripts/gryphon-coverage-ratchet`, the authz/direct-write/log-site guards) migrate to
it incrementally; none is rewritten speculatively.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-validation-ratchet-harness-1 | Shared compare core | Implemented | A single helper implements the floor and ceiling-to-zero ratchet directions, with one actionable regression message and one improvement/bump message, replacing per-caller copies. | `tap/ratchet.py` (`ratchet_ceiling` / `ratchet_floor` / `read_baseline_set`); `tap.guards.CeilingRatchet` wraps the ceiling direction. Measurement stays bespoke per surface. |
| req-dev-validation-ratchet-harness-2 | Common baseline schema | Deferred | Ratchet baselines share a committed artifact shape carrying the value plus provenance (`measured_at_commit`, scope, note). | Deferred as YAGNI: baselines remain line-per-entry text (each with a header comment); no consumer needs structured provenance yet. Revisit if a caller does. |
| req-dev-validation-ratchet-harness-3 | Emits its Map row | Implemented | The harness produces the surface's Validation Map row with standard guard-status phrasing so honest-status labeling cannot drift. | Realized more strongly than a stub: guards carry `map_row`/`rid`/`cadence`/`status`, and `render_map_markdown()` generates the row (`req-dev-validation-map-5`). |
| req-dev-validation-ratchet-harness-4 | Incremental migration, no speculative rewrite | Implemented | Existing ratchets migrate to the shared core only as they are next touched; the harness is built when it would have its second or third real caller, not before. | Migrated: authz, direct-write, log-site (×3), gryphon coverage-floor, mypy, known-broken. Guards against framework-ahead-of-demand. |

### Static Typing Ratchet
----
RID: `req-dev-validation-mypy-ratchet`
Status: `Implemented`

`pyproject.toml` sets mypy `strict=true`, but for a long time nothing *gated* on it, so the error set drifted to ~1200. Auditing that debt found it is overwhelmingly noise, not latent bugs — django-stubs dynamic-ORM friction (`attr-defined`, `type-arg`) plus a `no-untyped-call` cascade off untyped test fixtures — so a clean-to-zero sweep would be a ~1200-line, near-zero-value diff. The value is **forward**: freeze the audited debt and block anything *new*. `mypy .` is ratcheted through the shared [Reusable Ratchet Harness](#reusable-ratchet-harness) core (`CeilingRatchet`), keyed per `path:error-code:count` (never line numbers, so an edit that shifts lines does not churn the baseline); a new error bumps a count, which fails both teeth (new key present, and the ratchet notices the recorded key is stale). A genuinely-new `union-attr`/`None`-access on new code therefore fails at authoring time, while the baselined debt ratchets down as files are cleaned. The same change also fixed the package-mode namespace-plugin resolution (`[tool.mypy] exclude` + `py.typed` markers) that made `mypy .` double-walk and abort with "Source file found twice".

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-validation-mypy-ratchet-1 | Strict mypy is gated | Implemented | A per-commit guard runs `mypy .` and fails on any error outside the committed baseline. | `tap/guards/mypy.py::MypyRatchet` via `tap/tests/test_guards.py`. |
| req-dev-validation-mypy-ratchet-2 | Line-drift-proof key | Implemented | The baseline keys each entry by `path:error-code:count`, not line number, so unrelated edits do not churn it; a new error of the same code bumps the count and fails. | Known blind spot: fix+regress of the same code in the same file leaves the count unchanged (acceptable — the surface is noise). |
| req-dev-validation-mypy-ratchet-3 | Debt is audited and honest | Implemented | The baselined errors are recorded as audited debt (django-stubs friction + test fixture cascade), and the ratchet only moves down; a reviewed typing change re-baselines via one command. | `manage.py guards --sync-mypy`. |

### Suite Tiering & Performance
----
RID: `req-dev-validation-suite-tiers`
Status: `Proposed`

> **Forward note, not a build (jotted 2026-07-01).** Seeded for the
> validation-focused session. The corpus has grown fast (the Gryphon suites alone
> now run 7–18 minutes), and a full run has crept onto the inner loop. This is the
> tiering + acceleration strategy to pull it back off. `req-dev-validation-canary-tier`
> already owns the *membership discipline* of the fast tier; this requirement owns
> the *tiering model and the performance levers* around it.

#### The model: fast / affected / full

Three lanes, and the load-bearing insight is that the fix is usually *when each
lane runs*, not making the full run fast. A 15-minute full suite is fine if it runs
at the promote gate and not on every save.

- **Fast (smoke) — seconds, every save / pre-commit.** A curated blast-radius
  subset, governed by `-m smoke` and the membership rules in
  [Canary Test Tier](#canary-test-tier) (a test earns `smoke` only if its failure
  predicts broad downstream failure — importance alone is insufficient).
- **Affected — ~a minute, per chunk.** The tests touching what changed, selected by
  marker (`-m "not slow"`) or by test-impact analysis (below).
- **Full — the slow run, at the pre-push gate / CI only.** Everything, including the
  DB-heavy integration suites. Slow is acceptable here *by design*; this lane is the
  binary gate, not the inner loop.

#### As built — relevance-gated corpus (2026-07-08)

The first increment of the affected lane is deliberately narrow: it targets the one
surface that actually dominates the clock — the Gryphon corpus
(`plugins/gryphon_playground`, 7–18 min). Rather than per-test impact analysis
(`testmon`, deferred), `scripts/test` makes a single coarse decision: **run the corpus
only when the diff since `origin/main` touches the executor's footprint**, otherwise
skip it with a loud, logged notice. This lets `gryphon_playground` stay in the tree
(keeping the corpus available to other sessions and as Player-3 food-for-thought)
without taxing every unrelated local edit.

- **Footprint** (conservative — errs toward *running*, because the executor compiles
  onto shared grid machinery, so a false *skip* would be a silent-wrong-result
  false-green, precisely what the corpus exists to catch): `tap_grid/`,
  `plugins/gryphon_playground/`, `plugins/grid_fixtures/`, `tap_api/routers/gryphon.py`.
  The `tap_grid/` prefix is intentionally coarse (the whole grid read/materialization/
  edge layer, not just `tap_grid/gryphon/`); narrowing it to the executor's true
  transitive-import set — *derived*, not hand-authored, to avoid drift — is a later
  optimization. The wins land on the common cases that touch none of these: `tap_web`,
  `tap_viz`, `tap_auth`, docs/specs, and non-fixture plugin work.
- `--fast` remains the unconditional force-skip; `--gryphon` is the new unconditional
  force-run. An undeterminable merge-base (detached/shallow clone) or a
  non-interactive invocation defaults to **running** the corpus (fail toward
  correctness).
- **Gate safety** (`req-dev-validation-suite-tiers-4`): auto-selection is a
  *local-interactive accelerator only*. The promote gate invokes `scripts/test
  --gryphon` (explicit force-full) and the all-plugins CI lane runs `pytest -n 4`
  directly (never through `scripts/test`), so neither can inherit a relevance-skip.
  The corpus stays an un-sampled gate.

#### Acceleration levers, ranked by ROI for this DB-bound suite

1. **Parallelize first — `pytest-xdist -n auto`.** The single biggest win for a
   DB-heavy Django suite, and low-effort. `TAP_TEST_JOBS` caps the worker count
   (`scripts/test` resolves it host-side, default `auto`) — the pressure valve for a
   host running several TAP stacks in one Docker VM, where `-n auto` sizes by CPU,
   ignores memory, and the OOM killer then reaps workers mid-run ("node down: Not
   properly terminated" + cross-worker collection mismatch; observed 2026-08-09,
   five stacks / 7.75 GiB VM). `pytest-django` gives each xdist worker its
   *own* test database, so it does **not** violate the standing "run overlapping
   suites as one invocation or they deadlock the test DB" rule — that rule is about
   two separate pytest *processes* sharing *one* DB; xdist is one process, N workers,
   N separate DBs. Expect roughly `cores`× on the full run.
2. **Profile before cutting — `pytest --durations=25`.** Time is rarely spread evenly;
   it concentrates in a handful of DB-seeding integration tests. Mark the offenders
   `slow` and add them to `smoke` only if they meet the blast-radius bar.
3. **Attack the per-test DB cost — the real hot spot.** `@pytest.mark.django_db(transaction=True)`
   is expensive (it truncates tables between tests rather than rolling back a
   transaction); it is genuinely required where `on_commit`/service-layer hooks fire
   (e.g. the Gridkin GRIFT seed) but should not be the default elsewhere. `--reuse-db`
   skips migrate/create-DB between local runs. A *separate* shared-seed "fast Gridkin"
   lane (seed a fixture once, run its read-only scenarios against it) would collapse
   much of the per-scenario cost — a speed lane only, since it trades away the
   per-scenario isolation the Gridkin runner contract (`spec-gridkin-v0.md`,
   gryphon_playground plugin repo) requires of the canonical suite.
4. **Test-impact analysis for the affected lane — `pytest-testmon`.** Runs only tests
   whose covered code changed (same lineage as the branch-coverage data the ratchets
   now collect). A local accelerator for deciding *what to run fast*, never a
   substitute for the full gate — its tracking DB can go stale on config/env changes.

#### Anti-patterns to avoid

- The fast tier drifting into "the important tests" instead of the blast-radius set
  (the canary-tier bar exists precisely to prevent this).
- Optimizing before `--durations` says where the time is.
- Trusting an affected/impact lane as a gate — it accelerates the inner loop; the
  full lane is what refuses the push.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-validation-suite-tiers-1 | Three named lanes | Partially Implemented | The suite exposes fast (`-m smoke`), affected (`-m "not slow"` or impact-selected), and full lanes, with a documented "which runs when". | Built: full + `--fast` lanes (`scripts/test`, documented in `docs/misc/test-parallelization-xdist-notes.md`), plus the relevance-gated Gryphon-corpus selection (`suite-tiers-5`) as the first affected-lane increment. Missing: general per-test impact selection + the `-m smoke` fast tier (membership owned by `req-dev-validation-canary-tier`). |
| req-dev-validation-suite-tiers-2 | Parallel full run | Implemented | The full lane runs under `pytest-xdist` with per-worker databases; this does not conflict with the shared-DB single-invocation rule. | `scripts/test` (`-n auto`), kept out of `addopts` on purpose. Highest-ROI lever; delivered. |
| req-dev-validation-suite-tiers-3 | Profiled, not guessed | Proposed | `slow` designations follow from `--durations` evidence, not intuition. | |
| req-dev-validation-suite-tiers-4 | Impact lane is not a gate | Implemented | Any test-impact/affected selection accelerates the inner loop only; the pre-push gate always runs the full lane. | Counters the substitution-backend blind spot. Enforced for the corpus-relevance lane (`suite-tiers-5`): the promote gate calls `scripts/test --gryphon` (force-full), the all-plugins CI lane runs `pytest -n 4` directly (never via `scripts/test`), and a non-interactive `scripts/test` also force-runs — so no gate path can inherit a relevance-skip. |
| req-dev-validation-suite-tiers-5 | Relevance-gated corpus | Implemented | The default local lane runs the Gryphon corpus only when the diff since `origin/main` (merge-base through working tree, incl. untracked) touches the executor footprint; `--fast` force-skips, `--gryphon` force-runs; an undeterminable base or a non-interactive run defaults to running it. | Coarse path-based first increment of the affected lane, scoped to the one dominant-cost corpus. Footprint (conservative, errs toward running): `tap_grid/`, `plugins/gryphon_playground/`, `plugins/grid_fixtures/`, `tap_api/routers/gryphon.py`. Local-interactive accelerator only — never weakens the gate (`suite-tiers-4`). `scripts/test`. |

### Lean-Boot Independence Gate
----
RID: `req-dev-validation-lean-boot`
Status: `Implemented`
Trace: `non-python` — scripts/gate-lean

The cold-boot gate ([Cold-Boot Smoke Gate](#cold-boot-smoke-gate)) runs inside the **already-running stack's venv** — a per-compose-project named volume (`venv:/app/.venv`) that holds whatever the container's boot profile installed (the full `test_all` union under the promote gate). That venv-sharing is a **structural blind spot** for one failure class: a **core** (`tap_*`) module that imports a **plugin-only** dependency (e.g. `requests`, `jwt`, `boto3`). In a full venv the leaked package is already importable, so the import silently succeeds and the leak stays invisible — yet a real **lean deployment** (the `core` product baseline, a customer with a minimal plugin set, or a plugin evicted to its own repo) would fail to boot with `ModuleNotFoundError`. Booting `core` *in-process* inside the full-venv gate has **zero teeth** here; only a genuinely separate, lean-**installed** environment catches it.

**As built.** `scripts/gate-lean` stands up a **throwaway session in its own compose project** (`tap_leanboot`) — which gives it its **own `venv` named volume**, i.e. a **core-only virtualenv** — via the real spawn-off-`main` path (`scripts/spawn-session.sh --boot core`, worktree written under `WORKTREE_BASE` in system tmp, non-interactive). It boots the zero-plugin `core` profile and gates on `manage.py health --set readiness`. Because the venv is core-only, any core module that reaches for a plugin-only dependency fails at pre-boot / migrate / boot — exactly the class the in-container gate cannot see. On **any** exit the throwaway is nuked (containers, volumes, networks, worktree, branch, registry row) via `despawn-session.sh --yes` (a commitless throwaway is always CLEAN); on **failure** diagnostics (`compose ps` + web logs) are captured to a sibling `*-diag.log` **before** teardown so a red gate is debuggable — deeper post-mortem via the `/diagnose-failed-session-spawn` skill. Proven both directions on build: `core` boots healthy in isolation (GREEN, ~clean teardown, zero residue), and an injected core `import boto3` is caught RED with the `ModuleNotFoundError` captured to the diag log.

This is the second half of `req-boot-minimal-baseline-5` (spec-tap-boot-v0.md): the baseline flip made `core` the product baseline and the union a test-only tier; this gate is what keeps `core` **honestly** bootable in isolation as the code evolves.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-validation-lean-boot-1 | Isolated lean venv | Implemented | The gate boots in a separate compose project so the venv is a fresh, core-only install — not the running stack's full venv. | `scripts/gate-lean` → `tap_leanboot` project → own `venv` volume. The venv-sharing blind spot is the whole reason it exists. |
| req-dev-validation-lean-boot-2 | Real spawn standup path | Implemented | The gate exercises the actual `spawn-session.sh` standup (build → pre-boot → migrate → boot → health), not a bespoke reimplementation. | Faithful to the path a real spawn / customer standup takes; also transitively smoke-tests `spawn-session.sh`. Branches the throwaway from the invoking worktree's **HEAD** (`TAP_SPAWN_BASE_REF`), so under a promote it tests the just-merged tree — the exact tree about to become `origin/main`, which local `main` does not yet point at. |
| req-dev-validation-lean-boot-3 | Catches import leakage | Implemented | A core module importing a plugin-only dependency fails the gate. | Verified: an injected `import boto3` in a core module → RED with `ModuleNotFoundError: No module named 'boto3'` captured. |
| req-dev-validation-lean-boot-4 | Bulletproof teardown | Implemented | On any exit (success, failure, interrupt) the throwaway is fully nuked; no containers/volumes/worktree/branch/registry residue. | Trap → `despawn-session.sh --yes` with an inline `compose down -v` + `worktree remove` fallback. Throwaway lives in system tmp, never `~/tap-sessions`. |
| req-dev-validation-lean-boot-5 | Diagnose before nuke | Implemented | On failure, diagnostics are captured to a durable log before teardown so a red gate is debuggable. | Sibling `*-diag.log` (survives the worktree nuke); `/diagnose-failed-session-spawn` skill for the post-mortem. |

#### Future

- **Fast-fail on crash-loop — resolved 2026-07-03** (`req-boot-abort-signal`, spec-tap-boot-v0.md). A leak no longer waits out the 300s readiness timeout: the standup pipeline emits the `ABORT` signal (`req-tap-logging-abort-signal`) on fatal failure, and `spawn-session.sh` Step 5 tails for the rendered `TAP-ABORT:` line and checks the container-exited/restarting state — so a leak reds in seconds with its reason. `gate-lean` inherits it.
- **Profile matrix.** Today the gate boots `core` (strictest signal). A follow-on could sweep `core` + `core_dev` (and, once plugins are evicted, a representative lean customer profile) if a leak class emerges that only a non-empty lean set exposes.

### Live-API Property Fuzz

RID: `req-dev-validation-api-fuzz`
Status: `In Development`

The CI boot gates stand up a REAL, healthy, HTTP-serving instance and — before this
requirement — health-checked it and threw it away. The standup is the expensive part;
tests aimed at the live instance before teardown are nearly free (George's observation,
2026-08-10, the demand signal here). Django Ninja auto-generates the OpenAPI schema, and
schemathesis (Hypothesis-based) derives property tests FROM that schema — the same
second-engine-oracle pattern as the Gryphon differential fuzzer, pointed at the API.

**As built:** the boot + throwaway-admin + session/CSRF-mint + schemathesis two-pass logic
lives ONCE, in the reusable workflow `.github/workflows/api-fuzz.yml`
(`workflow_call`, inputs `seed` / `max_examples` / `fail_on_findings`), called in two
postures so the gate and the nightly explorer can never drift: the **required gate**
(`product-lines.yml` `api-fuzz`, pinned seed / small budget / fail-on-findings) and the
**nightly exploration lane** (`api-fuzz-nightly.yml`, random seed / deep budget /
report-only). Both boot a dedicated
`core_dev` stack (fast, secrets-free), fetch `/api/v1/openapi.json`, and run
schemathesis (version-PINNED; bumps are deliberate diffs) in TWO passes with
the same two checks — no input may produce a 5xx, and every response must match its
declared schema. **Unauthenticated pass:** the auth wall must reject, never crash.
**Authenticated pass** (design record: `docs/misc/doc-api-fuzz-auth-design.md`): the job
runs `manage.py boot --profile core_dev` with per-run-random `DJANGO_SUPERUSER_*` env
(the same canonical auth-phase path spawn uses — no credential ever lives in a boot
profile, `req-boot-secrets`), mints a real DB session via the DEBUG-fail-closed
drive-browser `mint_session.py`, pairs it with the `csrftoken` cookie + `X-CSRFToken`
header (ninja's `django_auth` is `APIKeyCookie(csrf=True)` — without the CSRF pair every
write op collapses to 403), and fuzzes the surface BEHIND the wall as `tap_admin`
(highest-capability actor = maximal reachable surface; the service layer stays fully
engaged). A **200-canary** on `GET /api/v1/entities/` fails the step loudly if the
minted session doesn't actually authenticate — an "authenticated" pass that silently
fuzzes 401s is the failure mode this requirement exists to forbid. **Enforcement:** the
job is in the `gate` aggregator's `needs` (tier-gated like the boot gates — runs only on
the `full` tier), findings FAIL the step (no `|| true`; bash pipefail carries
schemathesis's exit through the log `tee`), and both passes are **deterministic** — a
pinned `--seed` makes the verdict a function of the code, not the day's random draw, so a
promote is never blocked by a fresh example finding a latent bug on unrelated code. The
gate earned this: it found + forced fixes for 8 real 5xx classes (unvalidated pagination,
past-`bigint` offsets, explicit-null PATCH, escaped parse errors, NUL bytes) across its
first two runs, then ran clean. Both passes' findings still land as run artifacts.

**The exploration lane (built 2026-08-11):** `api-fuzz-nightly.yml` runs the reusable
workflow every night (cron `47 9 * * *`, `workflow_dispatch` for manual) with an EMPTY
seed (schemathesis draws a fresh random seed each run), `max_examples: 200` (~10× the
gate — it has the time), and `fail_on_findings: false` (a finding is a `::warning::` +
the uploaded artifact, never a red). This is where NEW bugs get discovered, off the
promote path, so a fresh finding never blocks a merge; when it finds one, triage the
artifact, fix, and — if worth locking in — bump the gate's pinned seed to cover it.

**Named open tail:** (1) the nightly explorer's findings are today a `::warning::` a human
must read — a future rung opens a tracking issue automatically; (2) a
`tap_viewer`-role DIFFERENTIAL pass — viewer writes must 403, never 500 or succeed
(authz-differential correctness is NOT covered by the admin-only pass; deliberately
deferred 2026-08-10); (3) richer surface under `test_all` (plugin API routers) once
runtime cost is measured; (4) if the stateful phase proves non-deterministic under the
required gate (worker interleaving / server-state feedback), drop to `--workers 1` or
gate only the deterministic phases; (5) promote `mint_session.py` to a `manage.py`
command with a log line now that this is gate-load-bearing (the minted session bypasses
the login audit path — accepted on a discarded CI stack, named here).

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-validation-api-fuzz-1 | Unauthenticated fuzz runs in CI | Implemented | schemathesis over the live schema, no-5xx + schema-conformance checks, report artifact uploaded. | Now gate-blocking (see -2). |
| req-dev-validation-api-fuzz-2 | Gate flip | Implemented | In the `gate` aggregator's `needs` (2026-08-11); findings fail the step (no `\|\| true`), verdict deterministic via a pinned `--seed`. Tier-gated like the boot gates (full-tier only). | Earned it: 8 real 5xx found + fixed, then clean. |
| req-dev-validation-api-fuzz-3 | Authenticated surface | Implemented | Fuzz behind session auth with a throwaway credential: in-job boot auth phase + minted DB session + CSRF pair, 200-canary fail-closed, admin-role pass — now gate-blocking. | Viewer-role differential deferred to the open tail. |
| req-dev-validation-api-fuzz-4 | Random-seed exploration lane | Implemented | `api-fuzz-nightly.yml` runs the reusable `api-fuzz.yml` nightly with an empty (random) seed, `max_examples: 200`, `fail_on_findings: false` — discovers NEW bugs off the promote path. | One reusable workflow; the gate and this lane are two callers, cannot drift. Auto-issue-on-finding is the open tail. |

#### Known-flake ledger (cross-session)

Now that this job is gate-blocking, a failure in its **harness standup** (stack boot, admin
mint, session mint — everything before the first fuzz request) is a **false red on the
promote path**, not a fuzz finding. Sessions MUST append recurrences here rather than
re-running past them silently — this ledger is the cross-worktree memory that
distinguishes "one-off infra flake" from "recurring boot-path concurrency defect".
Disposition rule: a setup-phase failure is re-run once and logged; **on recurrence**, it
graduates to a real investigation (boot-path concurrency under CI's cold Postgres) and
the job's retry/demotion posture gets a deliberate decision — a required gate that reds
on its own scaffolding erodes trust in every red. Feeds the flaky-test-tracking half of
`req-cicd-pipeline-observability` (spec-cicd-hardening.md).

| Date | Where | Symptom | Disposition |
| --- | --- | --- | --- |
| 2026-08-11 | PR #22 run (typing-only deps diff) | `psycopg.errors.DeadlockDetected` in the job's boot auth phase ("Run boot with a throwaway admin"), before any fuzz request | Initially judged harness flake (system under test byte-identical to main at runtime). Gate was green only because that PR's workflow snapshot predated the gate flip. **RECURRED same day — superseded by the next row.** |
| 2026-08-11 | Multiple additional api-fuzz failures on other runs, same day | `psycopg.errors.UndefinedTable` in the boot `grid_infra` phase before any fuzz request — flaky, a DIFFERENT table each run (`grid_fixtures__constrained_source`, then the CORE table `tap_arrangement`) | **ROOT-CAUSED + FIXED (session/unified); api-fuzz green after b70d7f93.** The victim being a *core* table (tap_viz `tap_arrangement`, not a plugin) proved the real root is a **migrate-vs-boot RACE**, not the plugin divergence: the readiness gate polled `manage.py health`, which checks DB reachability + the cache table — both true once the entrypoint's `createcachetable` runs, which PRECEDES `migrate` — so health went green while `migrate` was still applying migrations, and boot's `grid_infra` granted `SELECT` on a not-yet-migrated table (whichever migration hadn't been reached). Fix in the right layer: a **critical `migrations` readiness probe** in tap_health (`MigrationExecutor` plan empty == current), so `manage.py health` — and every readiness consumer polling it — waits for migrations by construction; the per-workflow `migrate --check` band-aid was reverted. A SEPARATE latent bug surfaced alongside and was also fixed: the two-source `INSTALLED_APPS` divergence (`TAP_PLUGINS` authoritative via `preboot.resolved_plugin_app_configs()`, collapsing the settings.py/plugin_testing.py copies) — real, but not this flake's cause. Full probe-set follow-ups are recorded in `spec-tap-health-v0.md` (`req-tap-health-selection` + the deferred probe list). |

### Promote-Path Enforcement
----
RID: `req-dev-validation-promote-hook`
Status: `Implemented`
Trace: `non-python` — scripts/promote-to-main.sh

The promote path MUST run the gate before advancing `origin/main` and refuse to push on red. This covers `scripts/promote-to-main.sh`, `scripts/promote-all-sessions.sh` (via the per-session script), and the documented manual fallback sequence. **As built the promote path composes three validation surfaces** (Step 2.5): the **full pytest lane** (`scripts/test --gryphon` — `--gryphon` forces the Gryphon corpus on unconditionally so the gate never inherits the local relevance-skip of `req-dev-validation-suite-tiers-5`) — which catches unit/functional regressions the cold-boot cycle structurally cannot (e.g. a stale collector key red'ing a unit test — the exact class that shipped to `main` red *because no promote gate existed yet*: the 2026-07-02 collector-identity refactor left the module-path key in `test_orchestrator.py`'s `_KSI_COLLECTOR` fixture, and the ungated promote published it) — then the **cold-boot gate** (`scripts/gate`), then the **lean-boot independence gate** (`scripts/gate-lean`, [above](#lean-boot-independence-gate)) which catches the core→plugin-dep import-leakage class the full-venv cold-boot gate structurally cannot. All three must be green; any red aborts before the atomic push. This is the reciprocal of `req-dev-multisession-promote-gate` in [spec-dev-multisession.md](spec-dev-multisession.md): that spec owns the requirement *on the promote workflow*; this requirement owns the gate *contract it invokes*. The two cross-reference and MUST stay consistent.

The gate runs after the pre-push merge (so it validates the exact tree that will become `origin/main`) and before the atomic dual-refspec push. On red, the push does not happen and the failure is reported; `origin/main` is never advanced past a tree that failed the gate. This is the mechanical enforcement of the otherwise prose-only "no messy/broken state to main" discipline that protects every spawned session.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-validation-promote-hook-1 | Gate before push | Implemented | The promote path runs the gate after the pre-push merge and before the atomic push. | `scripts/promote-to-main.sh` Step 2.5 (after merge, before atomic push): full lane (`scripts/test --gryphon`, force-full) → cold-boot gate → lean-boot gate. Validates the exact tree that becomes `origin/main`. |
| req-dev-validation-promote-hook-2 | Red blocks the push | Implemented | A failing gate aborts the promote; `origin/main` is not advanced. | `scripts/gate` non-zero → `fail` before Step 3. |
| req-dev-validation-promote-hook-3 | Covers script and fallback | Implemented | Enforcement applies to `promote-to-main.sh`, the all-sessions orchestrator, and the documented manual sequence. | `promote-all-sessions.sh` calls `promote-to-main.sh` per session (transitive). |
| req-dev-validation-promote-hook-4 | Reciprocal consistency | Implemented | This requirement and `req-dev-multisession-promote-gate` cross-reference and stay consistent; neither restates the other's substance. | |

### All-Plugins CI Lane
----
RID: `req-dev-validation-all-plugins-lane`
Status: `Proposed`

**The trigger fired early, via a path not originally listed.** [Server-side CI](#out-of-scope-v0) was deferred (v0) until "a second contributor" made "did you run it locally?" un-answerable by trust. Plugin **eviction** fired an equivalent trigger first: once a plugin's source leaves the monorepo, a focused local stack *structurally cannot* run that plugin's tests, so "the local gate is green" stops meaning "all plugins are green." The response is a **local/CI split**: the local promote gate validates *what is installed in this stack*; a **server-side all-plugins lane** owns *all-plugins truth*. It stands up the existing compose image and boots the `test_all` union (per the Out-Of-Scope constraint — it does not reimplement the environment).

**The boot record is the known-good-set (BOM) the lane verifies.** A boot record's `install.plugins[]` already pins each plugin's source+rev with an integrity digest ([spec-tap-boot-bootstrap.md](spec-tap-boot-bootstrap.md)); that *is* a bill-of-materials in the sense Jenkins (`bom-<line>.x`), Backstage (`versions` manifest), and Airflow (`constraints-*`) use one — a pinned set verified to work *together*. Adopting a new plugin version is therefore: bump its rev in the record → the all-plugins lane re-verifies the whole set → promote. That is the `can-i-deploy` gate semantics (Pact) implemented over TAP's own BOM: never trust "latest × latest," only "this set, tested together." The lane's **hard gate on promote is legitimate here** — TAP's plugin set is small and first-party/curated, so it is the Airflow "in-repo providers hard-gate" case, not the Jenkins PCT "soft gate over a third-party universe" case.

**Prior-art placement.** TAP is in the Airflow/Ansible bucket (plugins extracted to their own repos, in-process Python packages, independent release); the convergent answer there is a min-core floor + a plugin-CI matrix against real core (incl. HEAD) + a pinned known-good-set — *not* a Terraform-style wire protocol (overkill in-process) nor Pact contracts (HTTP bodies can't see Python signature/type/exception breakage). See the plugin-testing prior-art sweep.

**Runner choice — shard the free lane, don't buy hardware.** A measured green run spends **~95% of wall-clock in the pytest lane** (1292s of ~21.5 min; build+boot is a ~100s fixed tax, and the image-layer cache — `cache-from/to type=gha`, landed `f051ba9e` — is a real hit, ~40s vs minutes cold). That single number decides the runner question: the lane is near-perfectly shardable, and it is Postgres-I/O-bound, so *N independent Postgres instances* (one per shard) relieves the bottleneck better than *more cores on one box* (where one Postgres shares them). The winning lever is therefore **matrix-sharding across free 2-core runners** (`-lane-7`), not GitHub org-only larger runners (8-core = $0.022/min, no included minutes, forces an org migration + the promote→PR-gate redesign) and not AWS self-hosted (more cost + a standing ops surface, no faster than sharding for this workload). Baseline CI is ~free on the personal account (~$0–20/mo at the 2026 $0.006/min rate), so nothing here is a *cost* play — it is a wall-clock play at ~$5/mo. The full evaluation, including where AWS *does* earn its keep (AWS-native Bedrock / `aws_core` testing — a capability axis, not a speed axis; see the Out-Of-Scope AWS-native runner entry), is [doc-dev-validation-ci-runner-strategy.md](../docs/misc/doc-dev-validation-ci-runner-strategy.md).

| Sub-RID | Name | Status | Acceptance | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-validation-all-plugins-lane-1 | Local/CI split | Proposed | The local gate validates only installed plugins (install-aware collection, `req-dev-validation-collection-complete`); the all-plugins lane is the sole authority that every shipped plugin's tests pass. | Closes the focused-session gap that was previously bypassed. |
| req-dev-validation-all-plugins-lane-2 | Boots the union in the real image | Proposed | The lane boots the `test_all` union (v2: from git-installed, test-carrying wheels) in the compose image and runs the full pytest lane; it does not reimplement the environment. | v1 drafted at `.github/workflows/all-plugins.yml` (monorepo checkout). Not yet a proven pipeline — GitHub Actions is not exercisable from the dev loop. |
| req-dev-validation-all-plugins-lane-3 | Blocking on promote (BOM verify) | Proposed | `promote-to-main.sh` triggers the lane on the merged tree and refuses to advance `origin/main` on red (option B: trigger + poll, keeps the atomic push). Reciprocal of `req-dev-multisession-ci-gate`. | The `can-i-deploy`-over-the-boot-record gate. |
| req-dev-validation-all-plugins-lane-4 | Plugin-side CI vs. core | Proposed | Each evicted plugin repo's CI installs core + the plugin + its declared test dependencies and runs the plugin's tests, at minimum against **core-main** (drift early-warning); a min/latest-core matrix is a later addition. This is where a plugin change is validated *as it is pushed*. | Needs core to be git-consumable by the plugin CI (clone the monorepo @ref + boot). Publishing a `tap-core` package + tagging core releases (for a min/latest matrix) is deferred. |
| req-dev-validation-all-plugins-lane-5 | Plugin ships its own test/CI boot profile | Proposed | A plugin ships a minimum test boot record (`boot/*.boot.json` inside the package) that CI pulls and boots. It declares the plugin's cross-plugin **test** dependencies so CI pulls and tests them alongside — a self-contained mini-BOM scoped to "what this plugin needs to be tested." | Reuses the shippable-boot-record machinery; a concrete, exercised home for `req-tap-plugin-arch-dependencies` "declare-now" deps. |
| req-dev-validation-all-plugins-lane-6 | Min-core floor (load-time) | Proposed | Plugins declare a supported core-version range and core refuses to load an out-of-range plugin at boot. | The cheapest foundational edge (P1; universal across ecosystems). Owned by [spec-tap-plugin-architecture.md](../tap_plugins/specs/spec-tap-plugin-architecture.md) `req-tap-plugin-arch-min-core`; named here as the load-time complement to this lane. |
| req-dev-validation-all-plugins-lane-7 | Sharded execution (free-runner parallelism) | Parked | **PARKED 2026-07-08 — superseded by per-product-line CodeBuild lanes (`req-dev-validation-product-line-lanes`).** Built + exercised on CI (proved the machinery + aggregate gate + that even-split is non-viable — shards ran 51s/10min/25min-timeout, so `.test_durations` is mandatory — and surfaced the xdist test-DB flake fixed via the pre-migrated template, `TAP_TEST_DB_TEMPLATE`). Shelved as a documented free-runner fallback (commit `aa902128`) because per-product-line lanes parallelize along a *meaningful* axis (profile boundaries) and the AWS-native capability is wanted anyway. Original design retained below for reference. — The lane runs as a `matrix` of N shards (start N=3) across free 2-core runners: each shard does the cached build → boots its **own** `test_all` stack → runs a disjoint, duration-balanced slice of the suite (`pytest-split`, committed `.test_durations`; composes with per-shard xdist as `--splits N --group G -n 4`); the union of shards ≡ the single-lane test set. A single aggregate gate job (`needs:` all shards) is the one status the promote path polls, so `req-dev-validation-all-plugins-lane-3` / `req-dev-multisession-ci-gate` wiring changes minimally. The aggregate fails closed if any shard reds. | Wall-clock ~21.5min→~8–9min at N=3 (the test lane is ~95% of wall-clock, so the ~100s per-shard build+boot tax is cheap and each shard's own Postgres relieves the I/O bottleneck). **Balance by duration, not by logical boundary:** the dominant-cost gryphon corpus (`plugins/gryphon_playground`) is *subdivided across* shards, never pinned to its own shard — a dedicated shard would become the long pole (~14min) and gut the win. It subdivides cleanly because it is hundreds of small parametrized nodes (~99 gridkin scenarios + ~180+ fuzz cases + metamorphic + internals) with no monolithic long pole (the campaign/soak is `skipif`-gated off in the lane); fuzz node-ids are seed-stable so `.test_durations` stays valid (rolling the seed/counts → graceful even-split fallback, refresh durations). The CI lane keeps running the **full** corpus (no `--ignore`) — `scripts/test`'s executor-footprint relevance-gate stays a *local* inner-loop accelerator, never applied to this all-plugins-truth gate. Same single validation surface (not a new Map row — `req-dev-validation-map-3` is triggered by add/move/retire, not by internal parallelism; the declared-surface `description` gets the shard note at implementation via `--sync-map`). Composes with the layer cache already on `main` (every shard's `cache-from: type=gha` hits the same warm cache — no build-once-to-registry step). Decision record: [doc-dev-validation-ci-runner-strategy.md](../docs/misc/doc-dev-validation-ci-runner-strategy.md). |

### Per-Product-Line CI Lanes
----
RID: `req-dev-validation-product-line-lanes`
Status: `Proposed`

**The parallelization axis is the product, not the test suite.** TAP's products *are*
boot profiles: a product line = a plugin-pack + boot profile (`samsite`; a FedRAMP line
— now the evicted `fedramp_20x_ksi` repo; customer-specific lines). Rather than shard one
monolithic `test_all` run for speed (parked `req-dev-validation-all-plugins-lane-7`),
validate **each product line on its own lane** — booting *that line's profile*, running
*that line's tests* (install-aware collection, `req-dev-validation-collection-complete`,
scopes to core + the booted profile's plugins), in parallel across lines. This
parallelizes along a *meaningful* boundary (each lane validates a real deliverable),
scales with the business (new line = new lane), and sidesteps the monolithic-`test_all`
sharding flakiness because each lane is a deterministic, smaller profile. `test_all`
remains one lane (the union superset).

**Vehicle: free GitHub-hosted runners (`ubuntu-latest`).** Each lane is an ordinary
matrix job on a free 4-vCPU runner; the CI compose overlay (tmpfs + fsync-off
Postgres) and the per-profile pre-migrated template DB
(`scripts/build-test-template` + `TAP_TEST_DB_TEMPLATE`) make setup fast and
race-free anywhere. **Runner history:** the lanes ran on per-line AWS CodeBuild
runners (8 vCPU, in-account IAM — decision 2026-07-08) until the CodeBuild-cancel
spike (2026-08-10) measured the identical `test_all` job at ~9 min on a free runner
vs ~7 min on CodeBuild — under the consolidation threshold, and the in-account-IAM
rationale had lapsed (all plugin repos public since 2026-08-08; no Secrets Manager
round-trip; no Bedrock lane exists yet). CodeBuild retired; the Terraform under
`ci/terraform/codebuild-runners/` remains in-repo as the worked example until the
account-180731181784 teardown (deliberately last in the migration plan). If an
in-account lane returns (e.g. live Bedrock), that Terraform is the restore point.
Full evaluation + measurements:
[doc-dev-validation-ci-runner-strategy.md](../docs/misc/doc-dev-validation-ci-runner-strategy.md).

| Sub-RID | Name | Status | Acceptance | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-validation-product-line-lanes-1 | One lane per product line | Implemented | Each product line (profile) has a lane that boots *that* profile and runs *that* line's tests; lines run in parallel. Adding a line = one workflow matrix entry. | Meaningful (product) axis. `test_all` is the union superset lane. Both lanes proven green on CodeBuild (2026-07-08) and on free runners (2026-08-10 spike + first flipped gate run). |
| req-dev-validation-product-line-lanes-2 | ~~CodeBuild GHA runner~~ Free GHA runner | Superseded | Was: each lane on an AWS CodeBuild project registered as a GHA runner. Superseded 2026-08-10 by the measured free-runner consolidation (identical job ~9 min vs ~7; `-n auto` tuned: 233s@4 workers vs 256s@8 on 4 vCPU). | Terraform retained in-repo as the restore point until the account teardown; see the Vehicle prose above. |
| req-dev-validation-product-line-lanes-3 | Per-profile template clone | Implemented | Each lane builds a per-profile pre-migrated template DB and workers clone it (`TAP_TEST_DB_TEMPLATE`), eliminating the per-worker migrate-from-zero race + speeding setup. | `scripts/build-test-template`; `tap/test_settings.py`. Tier-0 RAM-backed Postgres (`docker-compose.ci.yml`) gave a further ~3.9× on the test lane. |
| req-dev-validation-product-line-lanes-4 | In-account capability, least-privilege per line | Implemented | Each lane's IAM role is per-line (grants can diverge) and grants only what that line tests need — native Bedrock and/or scoped `aws_core` STS, plus a per-line `GetSecretValue` grant on the plugin-pull secret for lines that git-install private plugins (`needs_plugin_pull`). The AWS-native reason to run CI here. | `ci/terraform/codebuild-runners/iam.tf`, `secrets.tf`; reuse the External-ID discipline from `plugins/aws_core/.../handoff/cross-account-role.yaml`. |
| req-dev-validation-product-line-lanes-5 | IaC in-repo, state out | Implemented | The provisioning is Terraform tracked in-repo; state + real tfvars (ARNs/account ids) are gitignored, never committed. The plugin-pull secret is a shell only (no `secret_version`) so no secret material lands in tfstate. | `ci/terraform/codebuild-runners/.gitignore`, `terraform.tfvars.example`, `secrets.tf`. |
| req-dev-validation-product-line-lanes-6 | Promote-gate + Map row when live | Implemented | The `test_all` union lane is wired as the promote gate (`promote-to-main.sh` Step 2.6 dispatches `line=test_all`, option B, reciprocal of `req-dev-multisession-ci-gate`), superseding the free-runner `all-plugins.yml` — which is retained as the fallback via `TAP_PROMOTE_CI_WORKFLOW=all-plugins.yml`. Map row added via `DECLARED_SURFACES` ("Per-product-line CI lanes (free GitHub runners)"). | The gate bootstrap-skips the one promote that first lands `product-lines.yml` on `origin/main`, by construction (same detection as the original all-plugins gate). |
| req-dev-validation-product-line-lanes-7 | Change-tier gating (docs/specs shortcut) | Implemented | The `setup` job classifies the diff vs `origin/main` with `scripts/change-tier` (fail-closed: empty/missing-base/unknown paths → `full`): **docs** (inert documentation only — `docs/`, `plan/`, root `*.md`, LICENSE/NOTICE) skips the product lanes, boot gates, and api-fuzz; **specs** (any `specs/` markdown — parsed by tests: the Map-sync meta-test, RID resolution) runs the full `test_all` pytest lane (which contains every spec-consuming test by construction — no curated subset to maintain) and skips the boot gates + non-core lanes; **full** runs the whole battery. The `gate` aggregator accepts a skip ONLY where the tier justifies it; any other skip, a cancelled job, or a failed `setup` remains a failure. `secret-scan` and `dco` are always-on: docs leak credentials too, and docs commits still need sign-offs. The promote's local fast lane applies the same tier (docs → skip local pytest/boot; never in sole-authority mode). | Same PR flow, same single required check — retires the loud admin direct-push as the everyday docs shortcut. Trust note: the classifier runs from the PR's tree, the same trust model as every check on `pull_request`; the merge-queue endgame (`merge_group` runs the base branch's workflow) is the enforcement backstop for untrusted PRs. |

### Guard-System Meta-Integrity
----
RID: `req-dev-validation-meta-integrity`
Status: `Proposed`

The Map, the guards, and the ratchets are worth exactly what it costs to disable them. This requirement protects the validation system from being weakened — accidentally or intentionally — by the ordinary act of changing code. *Who guards the guards* is the whole subject, and its answer is layered: the in-repo mechanisms make tampering **loud**; only an out-of-band platform control makes it **blocked**.

**Threat model.** A gate can be neutralized many ways, easiest-to-catch to hardest: neuter a `check()` (make it `pass`); broaden an allowlist or loosen a pattern; delete a guard module (discovery drops it); land a real violation and its baseline line in one commit; or — the softest, highest-leverage target — **stop running the suite at all** by editing the runner (`tap/tests/test_guards.py`), the CI workflow, the gate scripts, or the pytest config. That last class dominates: it touches no guard, it removes them from the critical path, and it collapses every in-repo self-check at once (all of which fire only if the suite runs). A subtler variant disables the honesty meta-tests first, then everything downstream goes quiet.

**What already self-defends — but only while the suite runs.** Deleting a guard trips `test_spec_map_in_sync` (the generated Map no longer equals the committed block). A fabricated baseline line trips the ratchet's stale-entry tooth (`tap.ratchet.ratchet_ceiling` fails on `baseline − current`). A guard pointing at a non-existent requirement trips `test_guard_rid_resolves`. These make casual tampering loud — but none survive an edit to the runner or CI config, and none catch the violation-and-baseline-in-one-commit move (its added line is not stale).

**The seam (`-1`).** The enforcement *machinery* is separated from the *policy data* it consumes, and the two are governed by the **direction** a change moves, not merely by file type:

- **Machinery — review-always.** The harness and bases (`tap/guards/**` except `tap/guards/baselines/**`), the scanner engines (`tap/source_scan.py`, `tap/direct_write_coverage.py`, `tap/authz_coverage.py`, and every per-app / per-plugin `**/guards/**`), the ratchet core (`tap/ratchet.py`), the Map generator and declared-surface list (`tap/guards/report.py`, `tap/guards/surfaces.py`), the runner and the honesty meta-tests (`tap/tests/test_guards.py`), the CI/gate configuration (`.github/workflows/**`, `ci/terraform/**`, `scripts/gate*`, `scripts/promote*`), and the test configuration (`pyproject.toml`). **The allowlists and provenance vocabularies embedded inside guard modules are machinery too** — broadening one is a weakening move, so it correctly sits on the review-always side.
- **Self-safe directions — open.** Only two changes are safe *by construction*: a ratchet **baseline shrinking** (growth-by-fabrication is already forbidden by the stale tooth; genuine shrink is the goal), and a change that **adds coverage** (a new guard, a new declared surface, a new Map row). Everything that *removes* or *loosens* is a weakening move on the review-always side. The intuition that "the lists and maps grow and shift" holds for coverage-adding growth; it does **not** extend to growing an allowlist or an exemption set — that is loosening, and reviewed.

**Out-of-band anchor (`-2`).** No in-repo check can ultimately protect itself: the same push that weakens a guard can weaken its self-check. The regress terminates only at controls that live in the **platform's settings**, which a code push cannot edit:
- **Branch protection on `main`** — PRs only (no direct push), the guard/gate status check (the `test_all` lane) required and non-bypassable, branch up-to-date.
- **Required status check** — because the required-check contract lives in repo settings, a workflow edit that drops the guard lane cannot self-authorize.
- **`CODEOWNERS`** over the machinery paths above, with **George as sole code-owner**, so any PR touching the machinery needs his explicit approval. Solo today, this still converts a casual, automated, or AI-actor change to the machinery into a deliberate, reviewed human act — the point under the [AI-integration posture](spec-ai-integration.md): an assistant that can *edit* a guard must not be able to *disable* one without a human in the loop.

**In-repo loud layer (`-3`).** Defense-in-depth that fails fast rather than quietly: a **guard-integrity guard** asserting the discovered guard set is a superset of a committed manifest (removing a guard fails until the manifest — machinery — is edited, which `CODEOWNERS` then gates) and that no `check()` is a trivial `pass`/`return True`. The existing honesty meta-tests are the rest of this layer. It is recursive by design: the harness and the meta-tests are themselves machinery, so weakening *them* is a machinery edit — loud in-repo, gated out-of-band.

**Named limits (`-4`, honest risk).** Stated, not implied:
- A repo **admin can bypass branch protection**. Trust ultimately reduces to the admin set; these controls make disabling a gate a deliberate, logged, reviewed act, not an impossible one. For the pre-customer / solo phase that is the right calibration.
- The **violation-and-baseline-in-one-commit** hole is not closeable by the ratchet alone; it lives on the reviewed side of the seam.
- The **self-protection regress** is real: any in-repo layer can be edited by whoever can merge; only the out-of-band anchor (`-2`) actually blocks, and only as far as the admin set is trusted.

| RID | Name | Status | Description | Failure it prevents |
| --- | --- | :---: | --- | --- |
| req-dev-validation-meta-integrity-1 | Machinery / data seam | Proposed | Enforcement machinery is review-always; only baseline-shrink and coverage-add are self-safe directions; embedded allowlists/vocabularies are machinery. | A weakening change (neutered `check()`, broadened allowlist, dropped guard) merging as if it were routine policy data. |
| req-dev-validation-meta-integrity-2 | Out-of-band anchor | Proposed | Branch protection + a required, non-bypassable guard status check + `CODEOWNERS` (sole owner: George) over the machinery paths. The trust anchor lives in platform settings a push cannot edit. `.github/CODEOWNERS` is authored (machinery paths → `@notgeorge`, baselines carved out as data); the branch-protection + required-check + require-code-owner-review **settings** are the remaining step (applied in the repo admin UI, not in-repo). | Disabling the gates by editing the runner/CI config, or merging a machinery change with no human approval. |
| req-dev-validation-meta-integrity-3 | In-repo loud layer | Implemented | The guard-integrity guard (`tap/guards/guard_integrity.py`): asserts the discovered guard set ⊇ the committed floor `tap/guards/guard_manifest.txt`, and that no discovered guard's `check()` is a no-op (`pass`/`return`/`...`/`assert True`) — the neutering the Map-sync meta-test cannot see. Recursively covers the harness (it floors itself). Proof: `tap/tests/test_guard_integrity.py`. Hard lint, no baseline. | A silent guard deletion or a gutted `check()` passing CI unnoticed. |
| req-dev-validation-meta-integrity-4 | Named limits | Proposed | Admin bypass, the violation-and-baseline-in-one-commit hole, and the self-protection regress are named, not implied. | A false sense that the gates are tamper-proof rather than tamper-evident-plus-gated. |

**Home and graduation.** This requirement lives here, in the guard system's own spec, because today it *is* validation-of-the-validators — protecting the guard system this spec owns — and it is right-sized (four sub-reqs). Its out-of-band anchor (`-2`) is the same server-side settings surface as [spec-cicd-hardening.md](spec-cicd-hardening.md) `req-cicd-branch-protection`, which now also carries the require-code-owner-review dimension this contract adds; the CI/pipeline deferred backlog is canonical there. Meta-integrity **graduates to its own spec** (a `spec-repo-integrity.md`, absorbing this family as its internal-tamper-resistance section) when it stops being "protect the guards" and becomes "protect the repository's integrity" — i.e. when commit signing / attestation, supply-chain provenance (`req-cicd-supply-chain-provenance`), or branch-protection-as-code (committed GitHub rulesets) enter scope. That trigger is a concrete event, not a vague size threshold; naming it here defers the ceremony without losing the thread.

## Prior Art

The guard/ratchet harness was built bespoke and reached its shape by convergent
evolution — it had never been put through the repository's own [prior-art-search
discipline](../CLAUDE.md) *after* the fixes went in. This section records the external
processes it matches, so a future guard models on a proven pattern rather than
reinvents. Three surveys (2026-07-21) ground four design axes; the callsite-identity
model's SARIF lineage is recorded separately in `spec-tap-callsite-identity.md`'s own
Prior Art section.

### Ratcheting baselines — freeze the debt, block the new

The [house convention](#known-broken-manifest) — a bounded, reviewed, in-repo manifest
that ratchets toward zero — is the established migration-linting pattern: PHPStan and
Psalm baseline files, RuboCop's `.rubocop_todo.yml`, ESLint `--max-warnings`,
TypeScript strict-mode migration, and the `betterer` tool all freeze an audited debt
set and fail only *new* violations. TAP's `CeilingRatchet` (keyed on a drift-proof
occurrence_key, never a line number) is this pattern shared across every bespoke
ratchet via [Reusable Ratchet Harness](#reusable-ratchet-harness).

### Resolution-dependent lint rules — resolve names, don't match strings

A rule whose correctness depends on *which* class a name refers to must not match by
bare class name (`req-tap-auth-policy-9-name-resolution`: `tap_auth.User` was flagged
only because the graph-managed `computing_core.User` shares the string — a false
positive whose only "coverage" of the line was the collision itself). The industry
answer is a **per-file import binder**: pyflakes' `ImportationFrom` binds a local name
to its source module by *parsing, not importing*; Ruff and Semgrep build exactly this
file-local binder and **deliberately stop there** — cross-module type inference
(Pylint/astroid's inference engine, CodeQL's global dataflow) is disproportionately
expensive and unnecessary when the origin is stated in the file's own `import` line.
TAP's `tap.source_scan.build_import_bindings` models pyflakes' binding, and — per the
security-posture fail-closed doctrine — keeps the conservative bare-name match wherever
resolution is ambiguous (star/relative import, local shadow), so a genuine graph write
is never dropped by a resolution gap.

### Interprocedural preconditions — make the property local, don't build a checker

"Caller must invoke X before Y" is an interprocedural dataflow property the harness's
local, structural guards cannot express (the 2026-07 finding: a zero-proof-of-possession
dev-import gate lived only in a docstring and was ignored at four call sites). The
endorsed fix is to *change the property's shape*, not buy a bigger analysis engine:
relocating the precondition into the callee makes gating **true-by-construction** and
locally checkable — a textbook instance of **"parse, don't validate"** (Alexis King)
and **"make illegal states unrepresentable"** (Minsky), with the **modular-Hoare**
rationale (the callee asserts its own precondition; a caller-side obligation the harness
cannot see becomes a callee-local invariant it can). The closest prior-art exemplar for
the problem *shape* ("Y is only safe if X happened upstream") is the Checker Framework's
**"Must Call"** checker and its **RLC#** port: even those dedicated engines avoid
whole-program dataflow and instead **re-localize** the property to method-boundary
annotations. The strictly-stronger ideal is a **capability/typestate token**
(hold-a-proof-to-call), which a dynamically-typed codebase cannot cheaply carry — so the
runtime gate-in-callee is the right substitute, backstopped by a cheap structural
*containment* guard (the dangerous symbol is importable only inside an approved
surface). Semgrep's documented inability to express statement sequencing confirms this
is an ordinary limitation, not a TAP-specific gap.

### Suppression escape hatches — scope them, and let stale ones rot loudly

An inline exemption (`# TAP-WRITE-COV: <reason>`) can be silenced by a **true but
orthogonal** reason (the annotation that explained why there was no `authorize()` while
the real risk was an unmentioned precondition). Two established defenses apply.
**Unused-suppression detection** — mypy `warn_unused_ignores`, Pylint
`useless-suppression`, ESLint `reportUnusedDisableDirectives` all fail a suppression
that no longer suppresses anything; TAP's `DirectWriteExemptionGuard`
(`req-tap-auth-policy-9-unused-exemption`) is this, tokenize-precise so a marker inside
a string literal is never mistaken for a live comment. **Obligation-scoped suppression**
— mypy's `# type: ignore[code]` requires naming the specific error, so an ignore for
code A cannot mask a later, different code B on the same line; a `# TAP-WRITE-COV[obligation]`
scoping plus a structured classification enum (the Coverity/SARIF `justification`
tradition) is the proposed next step, **deferred, not yet built**. No mainstream linter
enforces a *positive* "what makes this safe" argument — that is adapted from safety-case
engineering, not off-the-shelf tooling.

## Out Of Scope (v0)

- **Out-of-process real-worker integration (tiers 2–3).** Owned by `spec-tap-cares-task-backend.md` `req-tap-cares-task-backend-backlog-2`. Trigger: the persistent customer-hosted instance, or the strategy doc sequencing it sooner.
- **Broad per-flow correctness suite.** The gate is cold-boot-one-cycle plus the canary tier, not exhaustive integration. Trigger: a capability going "cold" (built, no longer in the daily assessment loop) earns a targeted integration test for *that* flow first.
- **Server-side CI (e.g. GitHub Actions).** ~~The pre-push gate is local for the solo window.~~ **Trigger fired early (2026-07-07), via a path not listed here: plugin eviction.** Once a plugin's source leaves the monorepo, a focused local stack cannot run its tests, so the local gate stops meaning "all plugins green" — an equivalent loss-of-trust to the "second contributor" trigger. Promoted to [`req-dev-validation-all-plugins-lane`](#all-plugins-ci-lane) (Proposed). As required, it stands up the existing compose image rather than reimplementing the environment. The "second contributor" path remains the trigger for the *fuller* PR-gated model (option A); the eviction-driven lane is the minimal server-side surface (option B).
- **Per-product-line CodeBuild lanes** — no longer out of scope: promoted to the active requirement [`req-dev-validation-product-line-lanes`](#per-product-line-ci-lanes) (Implemented), superseding the parked free-runner sharding. Artifacts authored (`ci/terraform/codebuild-runners/`, `.github/workflows/product-lines.yml`); CodeConnections app authorized + Terraform applied (account 180731181784); `test_all` + `samsite` lanes proven green (2026-07-08); the `test_all` union lane is the promote gate. GitHub's postponed-not-cancelled 2026 $0.002/min self-hosted charge is the standing tail risk.
- **Stage- and prod-validation.** Sibling specs and new Map rows when those environments exist. Trigger: the persistent customer-hosted instance inflection.

## Future

The deferral triggers above are deliberately concrete, not "later":

1. **Persistent customer-hosted instance.** The named inflection point: the system runs where the developer is not watching it. At that point dog-fooding stops being the safety net and the deferred tiers' demand signal has objectively fired — Shape-2/3 worker integration, the *fuller* server-side CI (PR-gated, option A), and stage/prod-validation siblings become warranted. (A narrow slice of server-side CI — the [all-plugins lane](#all-plugins-ci-lane) — was pulled forward early by plugin eviction; see Out Of Scope.)
2. **A capability going "cold."** The earlier, sharper trigger: the moment a flow leaves the daily assessment loop it loses its only coverage (dog-fooding). That specific flow is the first to earn a targeted integration test, well before the broader inflection.

Tier sequencing across this spec and `spec-tap-cares-task-backend.md` `req-tap-cares-task-backend-backlog-2` is currently forward-referenced (by that backlog entry) to a strategy doc that does not yet exist. Until it does, this Future section plus the [Validation Map](#validation-map) are the interim sequencing home; creating the strategy doc and migrating sequencing into it is itself a deferred item, not part of v0 of this spec.

## Status Vocabulary

Standard TAP states: `Proposed`, `Approved for Development`, `In Development`, `Implemented`, `Verified`, `Refactoring`, `Deprecating`, `Deprecated`, `Backlog`.
