---
title: 0.5 CI review: workflow-by-workflow verdicts
date: 2026-11-27
status: record
reviewed_commit: 21e4e525
audience:
  - developer
  - llm
related:
  - docs/misc/doc-0.5-compatibility-break-plan-2026-11-27.md
---

> A read-only review by the make-it-fast session of origin/main at `21e4e525`, which is v0.5.0 (`af6c940e`) plus 8 commits. It is the checklist the 0.5 Compatibility Break Plan cites. Line numbers are as of that commit.

# CI after 0.5: workflow-by-workflow verdicts (items 1 and 7)

From make-it-fast, for hard-things' 0.5 lock-in artifact. This is a read-only review of origin/main at `21e4e525`: v0.5.0 (`af6c940e`) plus 8 commits, with no code or migration change between them (46 migration files at both refs).

A delegated reviewer did the review. make-it-fast spot-checked four of its claims against origin/main, and all four hold:

- `tap/schema_parity.py:313-315` fails on any `django_migrations` mismatch;
- `publish-release-tags.yml:45-61` calls only the core-ci `line` and `cold-boot` lanes;
- `tap/ci_harness.py:150-158` accepts any existing floor tag;
- the comment at `product-lines.yml:384` says "Nightly and on dispatch only", while the `if:` at 391 also runs the job on a migration PR.

Durations are `completedAt − startedAt` per job, taken from `gh run view --json jobs`, including the plugin repos with `-R`.

## Findings that change the plan

1. **No 0.5.0 baseline database exists anywhere CI could start from.**
   - `bake-product-image.yml` bakes code only; `docker/bake-product-image.sh:38` never migrates.
   - `scripts/build-test-template:63-69` rebuilds an empty template on every run.
   - No dump file is tracked.
   - The only raw material is the released images `tap-web:0.5.0` and `tap-db:0.5.0` (publish-release-tags run 45692359253).
   - An upgrade already works mechanically: on a populated database the entrypoint migrates normally (`docker/entrypoint.sh:420-442`).
   - `tap.schema_parity` hard-codes three roads (`tap/schema_parity.py:325-329`), so an "upgraded" road is new code.
   - Core's from-zero replay costs only 75–112 s, so minting the baseline in each run costs about what today's job does.

2. **A reset breaks upgrade parity unless the reset carries `replaces`.** After a reset to a fresh 0001, a 0.5.0 database still holds `django_migrations` rows under the old names. `schema_parity.compare` fails on any (app, name) mismatch (`tap/schema_parity.py:313-315`), so upgrade parity goes red. **Decide one of:**
   - reset with a 0001 carrying `replaces=[the 0.5.0 chain]`, kept for as long as a 0.5.0 database can exist;
   - drop upgrade parity;
   - drop the reset.

   No migration in the repo uses `replaces` today.

3. **Real installs DO migrate from zero today.** `install.schema_from_models` defaults to False (`tap/preboot.py:1350-1369`), and `docker-compose.yml:474-480` leaves it unset "so … a real install keeps its real migrations". Every new field install therefore replays from zero. **Decide one:**
   - flip the default for real installs (hard-things' Q82a);
   - keep from-zero as a supported fresh-install road, which then needs coverage more often than the triggers give it.

4. **Nothing in the release gate replays migrations or tests an upgrade.**
   - `publish-release-tags.yml:45-61` calls only core-ci `line` and `cold-boot`, and both build the schema from models (`docker-compose.ci.yml:36`, `core-ci.yml:79,195`).
   - The `migrations` job lives only in `product-lines.yml:390-443`. The release gate can't call it, because `core-ci.yml:21-24,55-66` allow only `line` and `cold-boot`.
   - So the plan's "release" trigger needs a new core-ci lane.
   - No job in any of the 17 workflows exercises an upgrade from an older release.

5. **Plugin floor.**
   - `tap.ci_harness.resolve` accepts any `v<floor>` tag that exists (`tap/ci_harness.py:150-158`), with no minimum. Since v0.1.x–v0.4.9 still exist, a pre-0.5 floor resolves silently and the plugin's PR lane tests against a deprecated core.
   - On such a harness:
     - below v0.4.2 there is no schema_parity, so it migrates from zero (`plugin-ci.yml:821-822`);
     - below v0.4.3 there is no shallow reload;
     - unless the harness Dockerfile defaults to `TAP_FIPS=1`, the image is rebuilt cold (`plugin-ci.yml:586,544-548,658-709`).
   - `makemigrations --check` runs against the floor core (`plugin-ci.yml:926-962`), so after a reset each plugin's floor must be at least the core release that carries the reset.
   - Observed: aws-core-tap (run 45870050363) and grid-fixtures-tap (run 45870513972) already resolve `floor=0.5.0` → `af6c940e`.
   - Correction to my earlier pointer: `plugin-ci.yml:92` is the `harness_ref` input description; the resolution step is at 241-250.

6. **Docs disagree with the code on the migrations skip rule.**
   - The `product-lines.yml:384` comment says nightly and dispatch only, but the `if:` at 391 also runs the job on PRs with `migrations_changed`; 11 such PR runs were seen.
   - `specs/spec-dev-validation.md:814` says the gate accepts the skip on every other event, but `product-lines.yml:563` fails it when `MIGRATIONS_CHANGED=true`.
   - `specs/spec-tap-boot-v0.md:412` matches the code.
   - The change regex at `product-lines.yml:113` matches `migrations/__init__.py` too, and is true whenever the merge-base is empty.
   - It does not detect a Django pin change (`pyproject.toml:43`, `uv.lock`), a `tap_boot/shallow_reload.py` change, or a `tap/schema_parity.py` change.

## Table

| workflow (job) | what it proves or does today | trigger and typical duration | verdict after 0.5 | reason |
|---|---|---|---|---|
| product-lines.yml (setup) | Computes `tier` (`scripts/change-tier`, 109) and `migrations_changed` from a diff regex (112-119). | PR, merge_group, dispatch, schedule `23 8 * * *` (26-62). 6–12 s. | change | Replace `migrations_changed` with the from-zero triggers: `migrations/*.py`; a Django version change in `uv.lock` or `pyproject.toml:43`; `tap_boot/shallow_reload.py`; `tap/schema_parity.py`; `migrate_from_models`. Add a separate output for upgrade parity. |
| product-lines.yml (migrations) | Boots core_ci with `SCHEMA_FROM_MODELS=false`, so the entrypoint migrates from zero and a TAP-ABORT fails (396-438). Then `tap.schema_parity` compares stock, shallow and model-built on schema, rows and `django_migrations` (`tap/schema_parity.py:325-360`). Covers core and the core_ci fixtures only. | Schedule, dispatch, and migration PRs (391). 75–96 s, with one 734 s outlier (run 45677774777, not investigated). Migration PRs 88–112 s over 11 runs. | change | Split it in two. (a) Upgrade parity: boot `tap-web:0.5.0`/`tap-db:0.5.0` with v0.5.0's core_ci on real migrations, swap in the head image (whose entrypoint migrates the populated database), and compare against a fresh model-built head with a new `upgraded` road. Run it nightly, on dispatch, on migration PRs and on release. (b) Run the three-road from-zero check on the triggers only. The time saved is small for core, about 90 s a night; the gain is in what each check means. The boot's own from-zero migrate repeats the shallow build (on by default, `tap_boot/shallow_reload.py:111-112`), so it could boot model-built. Depends on finding 2. |
| product-lines.yml (gate) | The single required check. It fails a migrations skip on schedule or dispatch, or on a PR with `migrations_changed` (556-567). | Every run. 2–4 s. | change | Give each job one rule keyed to its new trigger output; a trigger-only job may skip on schedule. `tap/tests/test_product_lines_gate.py` pins the shape (585). Update `spec-dev-validation.md:814` and `spec-tap-boot-v0.md:412,440`. |
| product-lines.yml (line → core-ci line) | The core walk and fixture suites on a model-built template (`core-ci.yml:148-149`). | Non-docs tiers. PR 12m43s–23m40s; nightly 729–1384 s. | keep | Never migrates. |
| product-lines.yml (cold-boot → core-ci cold-boot) | `scripts/gate` on a scratch database, including `schema:makemigrations` (`tap/guards/surfaces.py:624-628`). | full/boot tiers. 248–942 s. | keep | Model-built. Its makemigrations check is what surfaces a models-only change. |
| product-lines.yml (lean-boot) | `scripts/gate-lean`, a spawn of the `core` profile (213). | full/boot tiers. 91–103 s. | keep | Model-built (`docker-compose.yml:477-479`). |
| product-lines.yml (api-fuzz → api-fuzz.yml) | A deterministic schemathesis run against core_dev (`api-fuzz.yml:48-50`). | full/boot tiers. 122–746 s. | keep | Model-built. |
| product-lines.yml (secret-scan, dco, rids, pins, pr-title, owner-issue) | Trailer, RID, pin and title checks, and the owner issue (589-648). | 6–21 s each. | keep | Out of scope. |
| core-ci.yml (lane-check, line, cold-boot) | The one definition shared by the PR gate and the release gate (14-24). | As above. | change | Add a `migrations`/`upgrade` lane and extend the allowlist at 55-66, so product-lines and publish-release-tags call one body instead of the second copy at `product-lines.yml:390-443`. |
| publish-release-tags.yml (core-ci-line, core-ci-cold-boot) | core_ci on the tag commit before promotion (45-61). | `v*` tag. v0.5.0: 1152 s and 371 s; v0.4.9: 1137 s and 317 s. | change | Add the upgrade-parity and from-zero lanes (finding 4). |
| publish-release-tags.yml (candidate, release-cve-scan, release-cve-sarif, retag) | Waits for `:sha-<short>`, gates High/Critical CVEs that have a fix, verifies attestations, retags `X.Y.Z` (66-332). | Tag. 6 s / 22–26 s / 12–14 s / 39–80 s. | keep | Produces the `:0.5.0` images the baseline would be minted from. |
| publish-images.yml (build, manifest, sbom, attest-sbom, promote-latest, scan) | Builds and attests `tap-web`/`tap-db` as `:sha-<short>` and `:latest` (39-69, 85-550). | Main push and dispatch. Build 77–172 s; sbom 181–247 s. | keep | Images only. |
| bake-product-image.yml (build, publish) | A product image from tap-web plus a boot record, with no database (72-207). | `workflow_call` from products. Not measured. | keep | Holds no database state, so it's not a baseline source. |
| product-health.yml (boot-and-check) | Boots a product's real profile on `:latest` without the CI overlay, so `schema_from_models` is false and the real migrations replay from zero (109-121; `tap/preboot.py:1350-1369`). | `workflow_call` from products. Not measured. | decide | A from-zero replay outside the triggers. Options: keep it as the fresh-install proof (finding 3); set `TAP_BOOT_INSTALL__SCHEMA_FROM_MODELS=true`; or turn it into a product upgrade from the last release to latest. |
| api-fuzz-nightly.yml (explore) | A random-seed, 200-example fuzz (40-52). | Schedule. 177–184 s. | keep | Model-built. |
| plugin-ci.yml (conformance) | Resolves the harness from the `requires_tap` floor (241-250; `tap/ci_harness.py:50-66,143-158`), then runs `validate_plugin --strict` (276-306). | Plugin PR/push. 14–27 s. | change | Refuse a floor below 0.5.0, with the reason, in `tap.ci_harness` or the validator (finding 5). |
| plugin-ci.yml (repo-scope) | `validate_plugin --repo` (366-431). | 8–25 s. | keep | Optionally add a check that `latest_ref` is not below 0.5.0. |
| plugin-ci.yml (boot-and-test, default road) | Pulls (provenance-verified) or builds `tap-web:sha-<harness>` (571-709), boots `SCHEMA_FROM_MODELS=true` (781), then runs ci_fast, `makemigrations --check` (926-962) and xdist. | Plugin PR. aws-core-tap 517 s; grid-fixtures-tap 103 s. Nightly main 593–880 s. | keep | With a floor of at least 0.5.0, the old-harness fallbacks (821-822, 838-842, 586) never fire and can be dropped later. |
| plugin-ci.yml (boot-and-test, `schema_parity` road) | A from-zero boot, then `tap.schema_parity`; fails closed without the module (158-169, 972-981). | Only via plugin-nightly `migrations`. Not measured. | change | Add an upgrade road: the plugin's last release on core v0.5.0, then plugin head on the harness. Booting model-built removes a duplicate replay, about 13 min for aws_core (`plugin-nightly.yml:91-94`, 784). |
| plugin-ci.yml (scan-dependencies, upload-dependency-sarif) | Trivy on the dependency closure (1311-1511). | 32–50 s / 12–17 s. | keep | Out of scope. |
| plugin-nightly.yml (main) | plugin-ci against core main (129-141). | Caller cron. 105–880 s. | keep | The ceiling row. |
| plugin-nightly.yml (newest-release, latest) | `releases/latest` or `latest_ref` (149-177), then plugin-ci at that tag (184-197). | Caller cron. Not observed. | keep | Resolves to v0.5.x on its own. A `latest_ref` pinned below 0.5 still passes 172: decide whether to refuse it. |
| plugin-nightly.yml (migrations) | A from-zero `schema_parity` row against core main, on by default (78-97, 206-220). | Caller cron, 90-minute timeout. Absent from the sampled runs. | change | Move from-zero to plugin triggers (a plugin migration PR, a plugin release, a core trigger-set change), and make the nightly row plugin upgrade parity. Update `tap/tests/test_plugin_ci_workflow.py:877-887`. |
| plugin-nightly.yml (owner-issue) | The night verdict (290-301). | 4–5 s. | change | Re-key 290-302 and 324 to the new row, and update `test_plugin_ci_workflow.py:286`. |
| plugin-release-sbom.yml (release-sbom, attest) | Wheel, SBOM and attestations at the plugin tag (71-302). | Plugin tag. Not measured. | decide | Nothing on a plugin release checks `requires_tap`. Should a release refuse a floor below 0.5.0? |
| trivy-nightly.yml (scan) | Trivy on `:latest` (33-42). | Schedule. 36 s. | keep | Note: `:0.5.0`, the supported release, isn't rescanned nightly. That's a separate call. |
| grype-nightly.yml, sbom-vulnerability-evidence.yml, sbom-evidence-dispatch.yml, ai-review*.yml | Out of migration scope. | — | keep | — |

## Duplication a standardization pass should merge

1. **The boot and health-poll loop, six copies with different bounds:**
   - `core-ci.yml:122-144,232-251`;
   - `product-lines.yml:420-438`;
   - `api-fuzz.yml:88-106`;
   - `plugin-ci.yml:794-813,884-902`;
   - `product-health.yml:120-137`.

   The core-ci, api-fuzz and product-health copies use `uv run` without `--no-sync`.
2. **Container uid alignment:**
   - `core-ci.yml:103-116,215-228`;
   - `product-lines.yml:410-417`;
   - `api-fuzz.yml:71-84`;
   - `plugin-ci.yml:758-771`;
   - `product-health.yml:100-107`.
3. **Empty secrets root:**
   - `core-ci.yml:91-94,204-207`;
   - `product-lines.yml:405-408`;
   - `api-fuzz.yml:60-63`;
   - variants at `plugin-ci.yml:563-569,715-718`.
4. **Web image pull-or-build, two implementations with different trust.** `.github/actions/ci-web-image/action.yml:24-58` makes no attestation check and one build attempt. `plugin-ci.yml:571-709` verifies provenance and makes three attempts.
5. **The schema_parity road appears twice:** `product-lines.yml:390-443` and `plugin-ci.yml:772-782,972-981`. Upgrade parity should land once, as a core-ci lane plus a plugin-ci road.
6. **The test-DB template build:** `core-ci.yml:148-149,257-259`; `plugin-ci.yml:847-848`.
7. **Owner-issue:** `product-lines.yml:589-648` and `plugin-nightly.yml:242-335` have drifted. The `is_bot` check is at 622 but not at 287, and the fork exit exists only at 272-275.
8. **Trivy, three times:** `publish-images.yml:513-550`, `publish-release-tags.yml:122-209`, `trivy-nightly.yml:32-70`.
9. **Smaller repeats:**
   - the PR-author env triple, `product-lines.yml:195-198,213-216,278-281,295-298`;
   - `setup-python`, at `product-lines.yml:236-241,273-275,311-313` and `plugin-ci.yml:493-495`;
   - a stale header, `docker-compose.ci.yml:1-3`, which still names the retired `all-plugins.yml`.

## Not measured

- `bake-product-image.yml` and `product-health.yml`, which run in product repos.
- The plugin-nightly `latest` and `migrations` rows. They were absent from the sampled nightlies, perhaps because those callers pin an older or bespoke plugin-nightly; not checked.
- `plugin-release-sbom.yml` and `sbom-*`.
- The core_ci fixture repos' own floors.
