---
title: 0.5 compatibility-code inventory
date: 2026-11-27
status: record
reviewed_commit: 21e4e525
audience:
  - developer
  - llm
related:
  - docs/misc/doc-0.5-compatibility-break-plan-2026-11-27.md
---

> A read-only review by the make-it-fast session of origin/main at `21e4e525`, which is v0.5.0 (`af6c940e`) plus 8 commits. It is the checklist the 0.5 Compatibility Break Plan cites. Line numbers are as of that commit. Statements below that a delegated reviewer did the sweep, or that certain claims were spot-checked, are the session's own account, not a committed review record. Every row cites file:line at `21e4e525`, so each one can be re-checked against that commit.

# Pre-0.5 compatibility code: per-file verdicts (item 6)

From make-it-fast, for hard-things' 0.5 lock-in artifact. A read-only sweep of origin/main at `21e4e525` (v0.5.0 is tag `af6c940e`). The sweep was done by a delegated reviewer. make-it-fast spot-checked four rows against origin/main: plugin_identity.py:81-86, tap_cares/tasks.py:277-282, grift/upgrade.py:17-23 and entity-viewer.grift.json:156-163. All four hold.

**Verdicts:** 23 delete-at-0.5, 5 decide, 11 keep, out of 39 rows. There are also 29 false positives.

## Method

- **Grep:** `backward.?compat|legacy|deprecat|pre-0\.5|WORKAROUND\(|shim|old (format|name|key)|for compatibility|still accept`, excluding migrations and traceability. It matched 67 files and 228 lines, and every hit was read in context.
- **Specs:** scanned for Deprecated, Deprecating and Retired statuses.
- **Beyond the grep:** two paths it misses were followed by hand. One is GRIFT format "0" and its restamp. The other is the model_links v1→v2 steps.
- **Issues**, checked with `gh issue view`:

| Issue | State |
| --- | --- |
| tap#1237 (the only WORKAROUND tag) | OPEN |
| tap#255 | OPEN |
| tap#996 | OPEN |
| tap#147 | CLOSED |
| tap#365 | CLOSED |
| tap#473 | CLOSED |
| tap#425 | CLOSED |

- **Org code search:** no repo outside tap has a `tap-plugin-*` distribution name, passes `boot_profile:`, or references `serialize_entity_envelope`, `_ENTITY_MODEL_REGISTRY` or `_NODE_REGISTRY`. The search then hit the rate limit, so the other aliases were checked only against the local `_dev-plugins` checkouts.

## Compatibility paths

| file:line | what it keeps compatible (old → new) | verdict | reason |
|---|---|---|---|
| .github/workflows/plugin-ci.yml:21,104-111,279,294-297,305,329 | the deprecated `boot_profile` input (repo-root `ci/nightly.boot.json`) → the in-package `tap_plugin/<slug>/boot/ci.boot.json`, passed on as `validate_plugin --ci-record` | delete-at-0.5 | It's the retired CI-record form of req-boot-bootstrap-ci-record-2. tap#365 is CLOSED, and no org caller passes `boot_profile:`. Amend spec-tap-boot-bootstrap.md:456,460. |
| .github/workflows/plugin-ci.yml:440-445,500-516 | the `_external/<slug>` symlink alias and the staging of an explicit `boot_profile` record → the in-package `ci` record | delete-at-0.5 | Its comment says to drop it once samsite and aws_core ship `ci` records, and tap#365 is closed. Goes with the row above. |
| tap_plugins/validate/service.py:194-197,311,1138-1185 | `legacy_record` / `ci_record=`, a repo-root record reported as info → in-package only | delete-at-0.5 | It's the same retired form. `--strict` then fails a plugin with no in-package record, which is the end state of req-boot-bootstrap-ci-record-6. |
| tap_plugins/validate_plugin/__main__.py:103-112 | the `--ci-record` flag, marked DEPRECATED | delete-at-0.5 | Only plugin-ci.yml:296 passes it. |
| tap_plugins/tests/test_validate_ci_record.py:6,112-127 | tests of the legacy-record path | delete-at-0.5 | Goes with the code. |
| tap/plugin_identity.py:81-86,98-110,131-139,167 | the `tap-plugin-<slug>` distribution name → `<slug>-tap` | delete-at-0.5 | tap#147 is CLOSED, and no org repo or pyproject uses the prefix. Amend req-tap-plugin-arch-identity-2 (spec-tap-plugin-architecture.md:517,555). |
| tap/preboot.py:429-436,540-561,1033,1046-1060 | preboot's wheelhouse fallback for a prefix-named wheel, and the `[fcf7]` warning | delete-at-0.5 | Same naming transition. |
| tap_plugins/validate/service.py:1045-1060 | a prefix `[project].name` reported as "DEPRECATED" info → a failure | delete-at-0.5 | Same naming transition. The docstring near :985 is also stale. |
| tap_plugins/validate/repo.py:2028,2299 | first-party detection that accepts the prefix | delete-at-0.5 | Docstrings only; the behaviour follows plugin_identity. |
| scripts/sbom/plugin_release.py:90,94-109 | `dist_name_from_wheel`, which lets a prefix-named wheel release | delete-at-0.5 | Same naming transition. |
| tap/tests/test_preboot.py:125,189,393-405; tap/tests/test_plugin_identity.py:128-130; tap/tests/test_sbom_plugin_release.py:77,160; tap_plugins/tests/test_validate_service.py:619-628; tap_plugins/tests/test_validate_repo.py:2107,2409 | tests that the prefix is accepted | delete-at-0.5 | Go with the naming rows. |
| tap/source_scan.py:104,121-124 | the flat `plugins/<slug>/tap-plugin.toml` layout → package mode | delete-at-0.5 | Retired 2026-07-02, and `plugins/` holds only `__init__.py`. Subject to the BUILD_BAKED decide row. |
| tap_plugins/validate/service.py:267-287,985-1010 | the flat-layout branch of `_resolve_package_root` | delete-at-0.5 | Same layout. Subject to the BUILD_BAKED row. |
| tap_plugins/tests/test_validate_service.py:599 | the flat-layout test | delete-at-0.5 | Goes with the row above. |
| tap/logging.py:88-93,118 | the retired `plugins.<slug>` logger namespace | delete-at-0.5 | No `plugins.*` app remains. Also remove tap/tests/test_logging_plugin_loggers.py:29,74-77, and amend req-tap-logging-plugin-loggers-5 (spec-tap-logging.md:427). |
| docker/entrypoint.sh:69,76,258-271 | an image with a wheel-cache seed but no manifest, skipped with a warning | delete-at-0.5 | Dockerfile:328,334 always ship the two together, so a missing manifest becomes an abort. Also remove tap/tests/test_entrypoint_image_stamp.py:117-125. |
| tap_cares/tasks.py:251,279-281 | the pre-#473 two-argument task payload (`lifecycle_batch_entity_id=""`) | delete-at-0.5 | #473 predates 0.5, and the only producer (tap_cares/services/__init__.py:701) passes three arguments. tap_cares/tests/test_no_request_actor.py:139,235 need the third. |
| tap_grid/constraints.py:150-155 | the upper-case registry aliases (`_NODE_REGISTRY` and others) | delete-at-0.5 | No references (the org search was partial). Specs spec-grid-node and spec-grid-edge mention the names. |
| tap_grid/registry.py:41-42 | the `_ENTITY_MODEL_REGISTRY` alias | delete-at-0.5 | No references. |
| tap_grid/grift/subgraph.py:186-197; tap_grid/grift/__init__.py:46,81 | `serialize_entity_envelope` → `build_spine_surface` | delete-at-0.5 | No caller anywhere. |
| tap_grid/flip.py:45-46 | the no-op `clear_registry()` | delete-at-0.5 | No caller; dead code. |
| tap_grid/grift/upgrade.py:17-23,47-51,61-64 | `TAP_REQUIRE_GRIFT_VERSIONS=0`, which reads GRIFT format "0" → "1" only | delete-at-0.5 | It exists for pinned pre-0.5 plugin releases. Rule 11 (spec-grift-v0.md:1388) holds only while nothing is above version 1, but spine and batch have been at version 2 since 0.5.0, so it may already misread. Amend spec-grift-v0.md:1389,1401 and spec-grid-entity.md:1401. |
| tap_grid/management/commands/restamp_grift.py; tap_grid/grift/restamp.py | `restamp_grift`, which converts "0" → "1" | delete-at-0.5 | It only converts pre-0.5 documents, and a reload is acceptable. Also remove tap_grid/tests/test_grift_restamp.py and test_grift_versions.py:101-102,318. |
| tap/preboot.py:99-112,1244-1250 | the empty `BUILD_BAKED_PLUGIN_SLUGS` transition set | decide | Call: are build-baked (in-tree) plugins supported after 0.5? If not, delete it with test_preboot.py:521-557, and the flat-layout and logging rows stand. If yes, those rows become keep. |
| tap/plugin_identity.py:146-153; scripts/sbom/plugin_release.py:222-228 | `is_plugin_dist_name` still treats the prefix as plugin-shaped (a namespace reservation) | decide | It's anti-typosquat protection, not acceptance. Call: keep barring non-plugins from the prefix? |
| tap_web/utils.py:1-7,42-56 | `safe_json` → Django `json_script`, used by administrivia, fedramp_20x_ksi and samsite | decide | tap#255 is OPEN, and whether those plugins' current releases still import it is unconfirmed. Call: remove now and require their 0.5 releases to migrate, or keep until #255 closes. |
| tap_viz/panels/graph_panel/__init__.py:346-363; tap_viz/apps.py:46-49 | the panel→`USES_LAYOUT` fallback when there is no `USES_PROJECTION` | decide | spec-viz-panel.md:27 marks it Deprecated, but core's own tap_web/data/entity-viewer.grift.json:156-163 still uses it. Call: migrate the entity viewer then delete, or un-deprecate. |
| tap_cares/model_links.py:23-25; tap_grid/model_links.py:24,27 | the v1→v2 steps for spine, batch, collection_job, schedule and schedule_fire | decide | v0.5.0 already writes v2, so v1 records come only from pre-0.5 exports. Call: replace them with a declared floor that refuses v1. That interacts with req-grid-entity-model-version-10/-14. |
| docker/activate-fips-system-wide.sh (and the Dockerfiles, test_container_user.py:106,109) | the `TAP_FIPS_ACTIVATION=legacy` rollback | keep | A security toggle, not version compatibility. |
| tap_files/apps.py:36-38 | `WORKAROUND(unified-systems-com/tap#1237)` | keep | tap#1237 is OPEN. |
| tap_grid/context.py:1-31 | the `get_batch_id`/`set_batch_id` wrappers | keep | Live callers: batch.py:24,236 and cascade_corpus/runner.py:142-157. |
| tap_grid/registry.py:23-24 | the re-export from tap.registry | keep | Live importers: admin.py:22 and constraints.py:38. |
| tap_grid/grift/__init__.py:13 | the package re-exports | keep | It's the public surface; 48 importers. |
| tap_grid/services/__init__.py:2197-2204 | the `create_edge` wrapper | keep | Current API. |
| tap/settings.py:1021-1027 | `STATICFILES_DIRS` guarded on the vendor dir | keep | A bare host run needs it; only the "legacy image" comment wording is stale. |
| docker/entrypoint.sh:65-66,86-91 | a cache with no stamp is cleared | keep | Fails safe. |
| tap_cares/specs/spec-tap-cares-collector.md:98,272,276 | uuid5 collector ids | keep | Live identity; a pending redesign. |
| tap_grid/specs/spec-grid-uuid-selection.md:28,151-155,164 | the grandfathered KSI v5 namespace | keep | A live identity exception. |
| tap_grid/specs/spec-grid-service-write.md:443 | null on a non-null field is dropped | keep | Current behaviour. |

## False positives

The 29 false positives, all omitted:

- review-workflow "shims";
- the podman forwarder;
- third-party "legacy" (psycopg2, CycloneDX tools, OpenAI `sk-`, allauth aliases);
- fixture strings;
- "legacy behaviour" meaning an optional field's default;
- guards that refuse old forms;
- the tap#996 JS-routes ratchet;
- Deprecated or Retired spec rows with no code path left.

The list with lines is available on request.
