---
title: 0.5.0 Compatibility Break Plan
date: 2026-11-27
status: proposal
audience:
  - developer
  - llm
related:
  - tap#1251
  - tap#1275
  - tap#1288
  - tap#1387
  - docs/misc/doc-0.5-compatibility-inventory-2026-11-27.md
  - docs/misc/doc-0.5-ci-review-2026-11-27.md
---

> This is a snapshot of the claude.ai doc at revision 32, written by the hard-things and make-it-fast sessions after Codex reviewed revision 24. It is kept here for the record. At the time of this snapshot, none of its decisions had been ruled on. The two make-it-fast reports under Sources are committed beside this file. Their links below point to those copies, not to the original local handoff paths. Where the plan says Codex reviewed it, or that review findings "held", that is the authors' account. The review itself was run outside this repository and is not committed here, so treat those statements as narrative, not evidence. The plan's claims about the code cite file:line and can be checked directly.

# 0.5.0 Compatibility Break Plan

Nov 27, 2026 · George Chamales

No production database exists yet, only our local session stacks, so TAP resets its migration history once, now, and keeps compatibility from that reset release forward. Anything older is refused by name, with the reload path. One declared floor enforces this for databases, records, GRIFT documents and plugins. Fresh installs build from the models, and CI proves the upgrade path we support instead of replaying history. Nothing here is built until the decisions below are ruled.

## Decisions

Fourteen rulings settle the plan, and I recommend yes to each. R is the reset release (D11). D12–D14, and the revised D5 and D6, come from Codex's review of PR #1397 (hard-things r198); each of its six findings held against the code. The five open rows from the code inventory follow below.

| ID | Decision | Recommendation |
| --- | --- | --- |
| D1 | Compatibility runs from R forward. A database, record, GRIFT document or plugin from before R is refused, not upgraded. Every local session stack reloads once. | Yes. No production database exists, so nothing real is lost. |
| D2 | One declared floor, R, set in one place and read by boot, record loading, GRIFT, plugin CI and plugin release. | Yes. One concept instead of five drifting checks. |
| D3 | A fresh real install builds its database from the models: `install.schema_from_models` defaults to true. | Yes. Then no install anywhere replays history. |
| D4 | A hard reset: delete every app's migration chain, in core and in every plugin, and generate one fresh `0001_baseline` from the models, with no `replaces`. | Yes. It is the cleanest end state, and with no production databases nothing needs `replaces`. |
| D5 | From R, every release upgrades from R and from every later release, including an install that skipped releases. There is no further reset after R. A squash happens only for a measured benefit, and it keeps its `replaces` until a written support-policy change retires that bridge. | Yes. Dropping replaces one minor later strands an install that skipped that minor, because Django needs the bridge to read its history. And once R is released, someone may have adopted it. |
| D6 | CI proves an upgrade with two separate checks. Schema: the upgraded database's schema equals a fresh model-built head. Meaning: a versioned, populated fixture, written through the source release's own service and GRIFT surface, keeps its identities, references, live and tombstoned rows, history and revision pins, FLIP, dimensions, timestamps and plugin data, except for each migration's declared transformations. Both run from R and from the latest supported release, nightly, on migration PRs and on release, and the stock-versus-shallow comparison runs on the populated upgrade too. From-zero replay runs on release and on named triggers. | Yes. An empty database cannot show a migration that corrupts data, and today's row digest skips every timestamp column (tap/schema\_parity.py:229). |
| D7 | `product-health` boots its products from the models, following D3. | Yes. Otherwise it is the last from-zero replay outside the triggers. |
| D8 | Delete the 23 delete-at-0.5 paths in one series of PRs. | Yes. Each is cited and has no live caller. |
| D9 | Merge the nine CI duplications. Images are pulled or built one way: the provenance-verified way. | Yes. Today one copy skips the attestation check. |
| D10 | Rule now, build in the next hard-things session after the Monday regscale work. The reset is a fleet pass, run by agents as wave 3 was. The 360-minute limit stays until D6 lands, then gitlab and anchore return to the 90-minute default. | Yes. None of this is on the Monday path. |
| D11 | R is v0.5.1. v0.5.0 is marked superseded: its database and plugin floors are not supported. | Yes. It keeps 0.5 as the line you named. A reset breaks 0.5.0, so 0.6.0 would be the strict semver choice, but nothing runs 0.5.0. |
| D12 | The storage shape every TAP model inherits (BaseModel, its history models and the spine copies) is a plugin contract from R. Approved shared-field changes land in the reset. A later change either carries a core-owned upgrade for existing plugin tables or is declared a compatibility break; raising a model version or a plugin floor does not count. CI adds a row that runs an unchanged released plugin wheel on newer core against an upgraded database, starting from a pinned product composition. | Yes. Today a shared field forces every plugin to regenerate migrations and release (tap\_grid/spine\_copies.py:471), and a reset does not remove that coupling. |
| D13 | Every migration effect the models cannot carry (RunSQL, a RunPython that seeds rows, a trigger) names its fresh-install treatment in the same PR. The reset carries every such effect of the deleted chains into the baseline or a shared init hook. From-zero triggers widen beyond Django's pin to every migration-bearing dependency and to shared init code, such as the spine-copy triggers. | Yes. The model build refuses RunSQL and skips RunPython (tap\_boot/model\_schema.py), so with D3 as the default an unnamed effect is lost on every fresh install. |
| D14 | The compatibility promise is written down. From R, TAP keeps the supported plugin and service APIs, GRIFT and model-version evolution, the boot and manifest formats, and the meaning of persisted data. A bumped version with a refusal is error handling, not compatibility. | Yes. Without a definition, each check decides for itself what compatible means. |

Inventory rows that need a call:

| Row | Question | Recommendation |
| --- | --- | --- |
| Build-baked plugins | Are in-tree, build-baked plugins supported after 0.5? | No. Delete the empty transition set; the flat-layout and logging rows then stand. |
| `tap-plugin-` prefix | Keep barring non-plugins from the prefix? | Keep. It guards against typosquatting; it accepts nothing old. |
| `safe_json` (tap#255) | Remove it now, or keep it until #255 closes? | Remove it once administrivia, fedramp\_20x\_ksi and samsite have released off it, and make that a condition of their 0.5 releases. |
| `USES_LAYOUT` fallback | Migrate core's entity viewer, or un-deprecate the fallback? | Migrate the entity viewer to `USES_PROJECTION`, then delete the fallback. |
| model\_links v1→v2 | Replace the steps with the floor? | Yes, under D2: a v1 record is refused, naming the floor. |

## The line

R, the reset release, is the oldest release TAP supports; v0.5.0 (tag `af6c940e`) is superseded by it. Before 0.5 TAP promised no upgrade path (spec-tap-boot-v0, Schema From Models), and with no field deployments a reload costs nothing.

| Thing | Kept from R forward | Before R |
| --- | --- | --- |
| Database | Upgrades by migration from R or any later release, including skipped releases (D5) | Refused at boot, naming the floor and the reload path; every local stack reloads once |
| Grid records (model\_links) | Read and upgraded from v2 | v1 refused (today it is upgraded) |
| GRIFT documents | Format "1" | Format "0" refused; `TAP_REQUIRE_GRIFT_VERSIONS=0` and `restamp_grift` deleted |
| Plugin floor (`requires_tap`) | `>=` R | Refused by plugin CI and plugin release (today a pre-0.5 floor resolves silently) |
| Plugin naming and layout | `<slug>-tap`, in-package boot records | The `tap-plugin-` names, the flat layout and repo-root CI records are deleted |

Each refusal is explicit and names what to do, under the explicit-over-silent rule.

## One floor

One constant, `COMPAT_FLOOR = "0.5.1"` (R), read by every check below, replaces five checks that would otherwise each pick their own minimum.

- **Boot, schema.** One shared preflight, used by the entrypoint, `cold_boot_gate` and every supported init or migrate path, reads `django_migrations` before choosing a road. It covers only the TAP-owned apps, core's and each installed plugin's. Django's `auth`, `contenttypes` and other third-party apps keep their own migration names and are never checked. Per app: an app with rows but none from its recognised baseline lineage (`0001_baseline`, or a later squash that replaces it) is refused, naming the floor and the reload command. An app with no rows is a fresh install of that app, such as a plugin added to an existing R database, and migrates normally. The existing refusal of a database newer than the code stays. The new name matters: every core app already has a `0001_initial`, so a reset that reused that name would be read as already applied on an old database. The check runs before the `migrate_from_models` branch, because that branch runs plain `migrate` on any non-empty database (req-boot-schema-from-models-2).
- **Records.** `tap_grid/model_links.py` and `tap_cares/model_links.py` drop their v1→v2 steps and refuse a record below the version its type had at R. The floor is per type: a type added after R, such as the coming RunConfiguration, starts at its own v1 and is never refused for it. The link validator changes with them: `declaration_problems` (`tap_grid/version_links.py:158`) requires a link from version 1, so a type whose oldest version is 2 is still refused today; the chain must start at the type's floor. This interacts with req-grid-entity-model-version-10 and -14.
- **GRIFT.** Format "0" and its restamp are deleted. Rule 11 (spec-grift-v0.md:1388) assumes nothing is above version 1, but spine and batch have been at version 2 since 0.5.0, so the format "0" reader may already misread.
- **Plugins.** `tap/ci_harness.py:150-158` refuses a `requires_tap` floor or `latest_ref` below the floor, with the reason. `plugin-release-sbom.yml` refuses the same floor at release. Preboot enforces it at load too: `_requires_tap_gate` (`tap/preboot.py:1089`) skips a plugin that declares no `requires_tap`, and now refuses it, as well as a floor below R. Before R exists, plugin candidates are tested through an explicit candidate-harness override, because plugin CI requires the floor to resolve to a released tag.
- **Separate identifiers.** The release version, the migration lineage, the GRIFT format and each type's model version are related boundaries with different identifiers. `COMPAT_FLOOR` names the release, and each check maps it to its own identifier as it stood at R.

The floor moves only by a written support-policy change (D5). After R there is no further reset. Every check follows the one constant.

## Stand-up

Today every new field install replays every migration from zero. `install.schema_from_models` defaults to false (`tap/preboot.py:1350-1369`), and `docker-compose.yml:474-480` leaves it unset on purpose. That default dates from before 0.5, when "the safe road for a real install is the one it already had" (req-boot-schema-from-models-6).

With D3 the default is true everywhere. An empty database is built from the models, with every migration recorded as applied. Any other database is checked against the floor, then migrated normally. CI and dev stacks already do this: the model build takes 63–85 s on anchore and gitlab, against 262–301 s with the shallow reload and 98–115 min on stock Django (nightly runs 45855721522 and 45855715519).

make-it-fast first proposed measuring the baseline's real migrate before flipping, then withdrew it. A from-models build is already the proven road in every CI lane, and nightly parity proves it equals the migrations. A squash would only make the old road faster for no caller.

The baked-instance seed (tap#1387) builds on the same baseline: a seed made at 0.5.x head is upgraded by migration like any other database.

The shallow reload (`tap_boot/shallow_reload.py`) stays. Real installs still migrate at every upgrade, and big plugins add big migrations.

## Migrations

With no production database, a hard reset (D4) is the best option: every pre-R migration file goes, and nothing is kept for databases nobody has. Core has 43 migration files (tap\_grid 24, tap\_web 6, tap\_viz 4, tap\_cares 4, tap\_files 3, tap\_auth 2); the plugins add the rest, most in aws\_core, gitlab-tap and anchore-tap.

| Option | Existing databases | Plugin dependencies on core names | Upgrade parity | Cost |
| --- | --- | --- | --- | --- |
| Hard reset to `0001_baseline` (recommended) | Local stacks reload once; there are no production databases | Every plugin resets with core: one fleet pass, as wave 3 was | Passes: the baseline is R, so no old names exist | Fleet pass; the shortest end state |
| Regenerate with `replaces` | Keep working, though nobody needs them | Still resolve, so plugins can move one at a time | Passes | Keeps `replaces` to drop later. This becomes the policy once production exists (D5) |
| Bulk-operation squash (aws\_core's `_bulk.py` in core) | Keep working | Still resolve | Passes | Faster only on the stock from-zero road, which D3 and D6 take out of use (tap#1251) |
| No squash | Keep working | No change | Passes | Keeps every pre-0.5 file and its RunPython steps forever |

How the reset is built:

1. Precondition: `makemigrations --check` is clean at core head, and in each plugin at its head, so the models equal the end state of the chain being deleted.
2. Core: delete each app's migrations and generate `0001_baseline` from the models. The 8 core files with RunPython (tap\_grid 0005, 0010, 0012 and 0023; tap\_cares 0003; tap\_web 0002 and 0003; tap\_viz 0002) are dropped. Nightly parity already shows a model-built database has the same rows as a migrated one, so they add nothing to an empty database. Any `CreateExtension` moves into the baseline.
3. Prove it: a model build and a from-zero migrate of the baselines must match on schema, rows and recorded migrations. Then cut R.
4. Plugins, in migration-dependency order: the `*_core` plugins first (compliance\_core, computing\_core, identity\_core and the rest), then their dependents. In each one, delete the chain and generate `0001_baseline` depending on the `0001_baseline` of each app it depends on, which must already be released or pinned to its reset branch. Set `requires_tap >= 0.5.1` and release. Agents prepare all the plugin PRs against core's branch before core merges, so the window in which plugin nightlies are red against core main is the time it takes to merge and release them. The pilot, run end to end first, is the first core plugin in that order, or gitlab-tap if it has no plugin dependencies.
5. Reload every local session stack and the CI fixture plugins (grid-fixtures-tap and the core\_ci fixtures).

## CI after 0.5

No job in any of the 17 workflows tests an upgrade from an older release today, and the release gate never migrates at all. make-it-fast reviewed every workflow at origin/main `21e4e525`; the rows that change are below. The full review, with the rows that stay, is in Sources.

| Workflow (job) | Proves today | After 0.5 |
| --- | --- | --- |
| product-lines (setup) | `migrations_changed` from a diff regex (112-119), which misses a Django pin, `shallow_reload.py` and `schema_parity.py` changes | Two outputs: from-zero triggers (`migrations/*.py`, the Django version in `uv.lock` or `pyproject.toml:43`, `shallow_reload.py`, `schema_parity.py`, `migrate_from_models`) and upgrade-parity triggers |
| product-lines (migrations) | Core from zero on three roads, 75–112 s | Split. Upgrade parity: boot `R's tap-web and tap-db images`, swap in head, compare with a fresh model build on a new `upgraded` road. Run it nightly, on dispatch, on migration PRs and on release. From-zero runs on triggers only |
| product-lines (gate) | Fails a skipped migrations job on schedule, dispatch or a migration PR | One rule per job, keyed to its trigger; fix spec-dev-validation.md:814 and the 384 comment, which disagree with the code |
| core-ci | Allows only the `line` and `cold-boot` lanes (55-66) | Add an `upgrade` lane, so product-lines and the release gate call one body |
| publish-release-tags | core-ci `line` and `cold-boot` only (45-61) | Add the upgrade lane and the from-zero lane |
| product-health | A product's real profile on `:latest`, replaying from zero | Model-built (D7), or a product upgrade from its last release |
| plugin-ci (conformance) | Accepts any existing floor tag (`tap/ci_harness.py:150-158`) | Refuses a floor below `COMPAT_FLOOR` |
| plugin-ci (`schema_parity` road) | Plugin from zero, then three-road parity | Add an upgrade road: a pinned product composition (a valid core, plugin and dependency set at R or at the latest supported release), then plugin head; and an unchanged released plugin wheel on newer core against the upgraded database (D12). Boot model-built, which saves about 13 min of duplicate replay on aws\_core |
| plugin-nightly (migrations) | From-zero parity against core main, nightly; gitlab 122 min and anchore 104 min at the 360 limit | Nightly row becomes plugin upgrade parity; from zero runs on a plugin migration PR, a plugin release or a core trigger change. The 360 override is removed (D10) |
| plugin-nightly (owner-issue) | Night verdict | Re-key to the new row |
| plugin-release-sbom | Nothing checks `requires_tap` | Refuses a floor below `COMPAT_FLOOR` |

No baseline database exists anywhere, so the upgrade lane mints one each run from R's released images. For core that costs about what today's job does, 75–112 s. Once the plugin floors are at R (0.5.1), the old-harness fallbacks in plugin-ci (821-822, 838-842, 586) never fire and are deleted.

The populated fixture (D6) is built once per supported source release, through that release's own service and GRIFT surface, and kept as a versioned CI artifact. Its meaning check compares timestamps too; only the columns a migration declares it transforms are exempt.

## Compatibility code

make-it-fast swept origin/main for compatibility paths and read each hit in context: 23 are deleted at 0.5, 11 are kept, and 5 need a call (in Decisions). There were also 29 false positives. The per-file table is in Sources.

| Group | Paths | Verdict |
| --- | --- | --- |
| Repo-root CI records and the `boot_profile` input | plugin-ci.yml, the `_external/<slug>` alias, `validate` `legacy_record`, the `--ci-record` flag and their tests | Delete; tap#365 is closed and no caller passes it |
| `tap-plugin-<slug>` distribution names | plugin\_identity, the preboot wheelhouse fallback, the validator, sbom `plugin_release` and 6 test files | Delete; tap#147 is closed and no org repo uses the prefix |
| Flat `plugins/<slug>/` layout and the `plugins.<slug>` logger | source\_scan, `_resolve_package_root`, tap/logging.py | Delete, subject to the build-baked decision |
| GRIFT format "0" | `TAP_REQUIRE_GRIFT_VERSIONS=0`, `restamp_grift` and its tests | Delete (One floor) |
| Dead aliases | `_NODE_REGISTRY` and the other upper-case aliases, `_ENTITY_MODEL_REGISTRY`, `serialize_entity_envelope`, the no-op `clear_registry()` | Delete; no caller |
| Old payloads and images | The pre-#473 two-argument task payload; an image that has a wheel-cache seed but no manifest | Delete; a missing manifest becomes an abort |
| Kept | The FIPS `legacy` rollback (a security toggle), tap#1237's workaround (open), live wrappers and re-exports, the stamped-cache clear, and the live identity exceptions | Keep |

The deletions amend six specs: spec-tap-boot-bootstrap, spec-tap-plugin-architecture, spec-tap-logging, spec-grift-v0, spec-grid-entity and spec-viz-panel.

## Standardize

The review found nine pieces of CI written more than once; each becomes one shared step or action (D9).

| Duplication | Copies | Why it matters |
| --- | --- | --- |
| Web image pull-or-build | `ci-web-image/action.yml:24-58` and `plugin-ci.yml:571-709` | One checks no attestation and tries once; the other verifies provenance and tries three times. Keep the verified one |
| Boot and health-poll loop | Six, in core-ci, product-lines, api-fuzz, plugin-ci and product-health | Different time limits, and three use `uv run` without `--no-sync` |
| Container uid alignment | Six | The same block, copied |
| Empty secrets root | Five, with variants | The same block, copied |
| The `schema_parity` road | product-lines 390-443 and plugin-ci | Upgrade parity lands once, as a core-ci lane plus a plugin-ci road |
| Test-DB template build | core-ci and plugin-ci | The same steps |
| Owner-issue job | product-lines and plugin-nightly | Drifted: `is_bot` is checked in one only, and the fork exit exists in one only |
| Trivy scan | publish-images, publish-release-tags, trivy-nightly | Three copies; separately, `:0.5.0`, the supported release, is not rescanned nightly |
| Small repeats | PR-author env, `setup-python`, a stale header in `docker-compose.ci.yml` naming the retired `all-plugins.yml` | Housekeeping |

## Order of work

Everything up to R ships as one release candidate, reviewed in several PRs. The refusal then never lands before the baselines it looks for, and R is not cut until its upgrade harness has run. Earlier drafts put the refusal first, which would have refused databases freshly made by the same code, since they still record `0001_initial`.

1. Rulings on D1–D14 and the five inventory calls.
2. Commit make-it-fast's inventory and CI review beside the plan, with their reviewed commit (`21e4e525`), so the deletions follow a published checklist. Then the core PRs for the 23 deletions, in groups by the table above; they need no floor.
3. Core PR: the upgrade harness. That is the `upgraded` road in `tap.schema_parity`, the populated fixture and its meaning check, and the stock-versus-shallow comparison on a populated upgrade. Before R exists it runs against the pinned candidate with a representative later migration.
4. The core candidate branch: the reset to `0001_baseline`, with every RunSQL or seed effect of the deleted chains carried over (D13), together with `COMPAT_FLOOR`, the shared boot preflight, the D3 default flip, the record and GRIFT floors, the version-link validator change and the preboot refusal, with their spec amendments. In parallel, agents prepare every plugin's reset PR against that branch, tested through the candidate-harness override.
5. Candidate acceptance, observed before anything merges: both fresh-install roads (models and migrate), a restart, the refusal of an old database, a reset plugin added to an existing candidate database, and the unchanged-released-plugin row (D12).
6. Merge core and cut R (v0.5.1). Then merge and release each plugin in dependency order, the core plugins first.
7. Reload every local session stack and the CI fixtures, and mint R's populated fixture.
8. Core PR: the CI lanes. That is the core-ci upgrade lane, the product-lines split and gate, the release-gate lanes, the plugin-ci upgrade road and floor refusal, the plugin-nightly row and the plugin-release floor check. Then remove the 360 overrides on gitlab-tap and anchore-tap.
9. The CI merges (D9), any time after step 8.

## Sources

- make-it-fast, the compatibility inventory with per-file verdicts at origin/main `21e4e525`: [doc-0.5-compatibility-inventory-2026-11-27.md](doc-0.5-compatibility-inventory-2026-11-27.md)
- make-it-fast, the CI review with per-workflow verdicts and durations: [doc-0.5-ci-review-2026-11-27.md](doc-0.5-ci-review-2026-11-27.md)
- `specs/spec-tap-boot-v0.md`, Schema From Models: req-boot-schema-from-models-2, -5, -6, and line 399 for RunPython and RunSQL
- Measured nightlies at the 360 limit: gitlab-tap run 45855715519 and anchore-tap run 45855721522; [tap#1288 comment](https://github.com/unified-systems-com/tap/issues/1288#issuecomment-7200203329)
- The root cause of the slow stock road: [tap#1251](https://github.com/unified-systems-com/tap/issues/1251)
- Django's handling of `replaces`, where a squash is recorded once all its replaced names are applied, is from the framework's migration executor. It matters only for the D5 policy once production exists, and is tested then.
