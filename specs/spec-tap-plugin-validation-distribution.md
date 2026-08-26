# Plugin Validation Distribution

## Philosophy

The validation authority — guards, ratchets, the Validation Map, and their baselines — grew up in a monorepo where every plugin's source sat in-tree and "installed" was indistinguishable from "present." In that world it was harmless for a central file to name a plugin: `tap/guards/surfaces.py` could declare a gridkin surface enforced by a `gryphon_playground` test; `tap/guards/baselines/mypy.txt` could carry a plugin's type-debt rows; `tap/guards/_collection_scan.py` could hardcode `plugins/genericom`.

Plugin eviction breaks that assumption. Once a plugin lives in its own repo and ships as a wheel, a central authority that names it is **stranded** the moment it leaves: the Map declares a surface enforced by a repo that is no longer here, a ratchet baseline carries rows for source that is no longer on disk, and a focused stack that installs a subset red's on assertions about plugins it never had. This spec is the **center of gravity for keeping the validation authority plugin-agnostic**: plugin-specific validation metadata must live *in the plugin* and be *discovered/contributed* by the central authority — never hardcoded centrally. It is the validation-side analogue of the plugin-testing install-awareness in [spec-tap-plugin-testing.md](../tap_plugins/specs/spec-tap-plugin-testing.md) and reports up to the validation center of gravity in [spec-dev-validation.md](spec-dev-validation.md).

The guiding asymmetry (the [security-posture](spec-security-posture.md) cheap-edge discipline applied to validation): a plugin-agnostic central authority costs a little discovery plumbing now and makes eviction a clean lift-out; a polluted one costs an expensive, error-prone archaeology pass at every eviction. Lay the edge while the plugin system is still being wrapped.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Plugin-Agnostic Center | No central guard/ratchet/Map file names a specific plugin; plugin-specific validation metadata is contributed, not hardcoded. |
| 2. | Clean Eviction | Evicting a plugin removes its validation surfaces, guards, and baseline rows *with it* — no stranded central references, no manual archaeology. |
| 3. | Install-Aware Comparison | A ratchet or guard whose surface spans plugins compares like-for-like over what *this* stack has installed; the all-plugins CI lane owns full-set truth. |
| 4. | Discovery Over Registration | Contribution mirrors the guard model: drop a file in the owner's package; the center discovers it. No central list to edit per plugin. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-plugin-validation-distribution-principle | [The Principle](#the-principle) | Proposed | Standing rule: plugin-specific validation metadata lives in the plugin, discovered/contributed, never hardcoded centrally |
| req-tap-plugin-validation-distributed-guards | [Distributed Guards](#distributed-guards) | Implemented | Guards already discovered per-owner incl `plugins/<slug>/…/guards/` (`discover_guards()`) — the reference model |
| req-tap-plugin-validation-no-central-slugs | [No Central Plugin Slugs](#no-central-plugin-slugs) | Partially Implemented | Central guard/ratchet code must not hardcode a plugin slug; generic-iterate or plugin-own. genericom hardcode removed; no automated guard yet |
| req-tap-plugin-validation-install-aware-ratchets | [Install-Aware Ratchets](#install-aware-ratchets) | Partially Implemented | Cross-plugin ceiling ratchets filter to core + installed on both sides (mypy done); per-owner baseline slices are the endgame |
| req-tap-plugin-validation-contributed-surfaces | [Contributed Declared-Surfaces](#contributed-declared-surfaces) | Proposed | `DECLARED_SURFACES` becomes a discovery pass across owners; a plugin owns its Map rows and they leave with it |
| req-tap-plugin-validation-eviction-clean | [Clean-Eviction Acceptance](#clean-eviction-acceptance) | Proposed | The end-to-end test: removing a plugin's package leaves zero central validation references and greens the gate |

### The Principle
----
RID: `req-tap-plugin-validation-distribution-principle`
Status: `Proposed`

Plugin-specific validation metadata — a guard, a ratchet baseline row, a declared Map surface, a collection-ignore entry — MUST live in the owning plugin's package and be discovered or contributed by the central authority. The central authority (`tap/guards/`, `tap/ratchet.py`, `tap/guards/surfaces.py`, `tap/guards/baselines/`) MUST remain plugin-agnostic: it may iterate over *discovered* or *installed* plugins generically, but it MUST NOT hardcode a specific plugin slug, path, or surface.

The test of correctness is eviction: removing a plugin's package from disk (the post-eviction reality) MUST NOT strand a central reference to it, and MUST NOT red a gate for a stack that never had it. This is a **standing filter**, not a one-time cleanup — every new guard, ratchet, or Map surface is judged against it at authoring time, the same way [spec-security-posture.md](spec-security-posture.md) and [spec-ai-integration.md](spec-ai-integration.md) are standing filters.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-validation-distribution-principle-1 | Center is plugin-agnostic | Proposed | No file under `tap/guards/` or `tap/ratchet.py` hardcodes a plugin slug/path; plugin-specifics are discovered or contributed. | |
| req-tap-plugin-validation-distribution-principle-2 | Standing filter | Proposed | New guards/ratchets/surfaces are judged against this principle at authoring time, not retrofitted. | Cross-ref the CLAUDE.md validation discipline. |

### Distributed Guards
----
RID: `req-tap-plugin-validation-distributed-guards`
Status: `Implemented`

Guards are already distributed and are the **reference model** for the rest of this spec. `discover_guards()` (`tap/guards/discovery.py`) walks every owner via the filesystem — `tap/guards/` for cross-cutting whole-repo guards, and each `<app>/guards/` and `plugins/<slug>/…/guards/` for owner-specific ones. Adding a guard is dropping a file in the right `guards/` package; there is no central import list. A plugin that ships guards under its package carries them into its wheel and takes them when it leaves.

The remaining requirements extend this same discovery model to the two central authorities that do **not** yet follow it: the ratchet baselines and the declared-surfaces Map.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-validation-distributed-guards-1 | Per-owner discovery | Implemented | `discover_guards()` finds guards in `tap/guards/`, every `<app>/guards/`, and `plugins/<slug>/…/guards/`. | |
| req-tap-plugin-validation-distributed-guards-2 | Reference model | Implemented | Contributed surfaces and per-owner baselines mirror this discovery mechanism. | Design constraint on the Proposed reqs below. |

### No Central Plugin Slugs
----
RID: `req-tap-plugin-validation-no-central-slugs`
Status: `In Development`

No file under the central authority may hardcode a specific plugin slug or path. A guard or ratchet that needs to reason about plugins does so generically — iterating the *discovered* plugins (filesystem/entry-point) or the *installed* set (`tap.plugin_testing.installed_plugin_slugs()`), never a literal.

Done: the `plugins/genericom` literal in `tap/guards/_collection_scan.py` `_IGNORED_DIRS` was removed (genericom itself was deleted). The set holds exactly one entry today — `_dev-plugins`, the plugin-workspace checkout root (`spec-dev-plugin-workspace.md`). That entry is **consistent with this requirement**: it names a generic, plugin-agnostic *directory*, not a slug, and it covers whichever plugins a developer happens to have checked out rather than any named one. Remaining: no automated guard yet asserts the center stays slug-free — that guard (a scan of `tap/guards/` + `tap/ratchet.py` for plugin-slug literals) is the natural enforcement and is itself a generic, plugin-agnostic check.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-validation-no-central-slugs-1 | No hardcoded slug | Partially Implemented | Central guard/ratchet code contains no plugin-slug literal; genericom removed. | Other central files audited clean in the 2026-07-07 pass except the Proposed surfaces/baselines below. |
| req-tap-plugin-validation-no-central-slugs-2 | Enforced by a guard | Proposed | A generic guard scans `tap/guards/`+`tap/ratchet.py` for plugin-slug literals and fails on a new one. | Belt to the standing filter. |

### Install-Aware Ratchets
----
RID: `req-tap-plugin-validation-install-aware-ratchets`
Status: `In Development`

A ceiling ratchet whose measured surface spans plugin code (the mypy ratchet is the canonical case: `mypy .` + the django-stubs plugin introspect `INSTALLED_APPS`) produces a *different* measured set on a focused stack than on the full-install one — so a frozen full-install baseline false-reds on rows for plugins that simply are not here.

**Interim (done):** such a ratchet filters BOTH its measured set and its baseline to *core paths + paths of installed plugins* before comparing, so it compares like-for-like over whatever this stack has; the all-plugins CI lane (`test_all` installs everything) filters nothing and enforces the full set. Implemented for the mypy ratchet (`MypyRatchet.check()`); the profile-resolution guard (`ProfileResolutionGuard`) applies the same install-aware predicate to shipped-profile resolution.

**Endgame (proposed):** per-owner baseline slices. Instead of one central `tap/guards/baselines/mypy.txt` carrying every plugin's rows, a plugin ships its own baseline slice under its package; the ratchet composes core + the slices of installed plugins. Eviction then removes a plugin's baseline rows *with the plugin*, and the filter becomes unnecessary because the rows were never centrally held. The interim filter is forward-compatible: it already scopes comparison by installed plugin, so moving rows into per-owner slices is a mechanical follow-on, not a redesign.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-validation-install-aware-ratchets-1 | Filter both sides | Implemented | A plugin-spanning ratchet filters measured + baseline to core + installed-plugin paths before comparing. | `MypyRatchet.check()`. |
| req-tap-plugin-validation-install-aware-ratchets-2 | Full-set truth in CI | Implemented | The all-plugins lane installs everything, so the filter no-ops and the full set is enforced. | Cross-ref `req-dev-validation-all-plugins-lane`. |
| req-tap-plugin-validation-install-aware-ratchets-3 | Per-owner slices | Proposed | Plugin baseline rows move into per-owner slices shipped in the plugin package; the ratchet composes core + installed slices. | Endgame; makes eviction lift-out clean. |

### Contributed Declared-Surfaces
----
RID: `req-tap-plugin-validation-contributed-surfaces`
Status: `Proposed`

`tap/guards/surfaces.py` `DECLARED_SURFACES` is a single hardcoded tuple — the Validation Map's negative-space inventory (the Named-but-deferred and gate-guarded-but-slow surfaces that no `check()` covers). Unlike guards, it has **no discovery**, so it cannot self-distribute. Today it carries plugin-specific rows — most sharply the six `req-gridkin-*` surfaces whose `enforced_by` points at `gryphon_playground` tests, a plugin that is already evicted to git: the central Map now declares surfaces enforced by an external repo.

The design-out mirrors `discover_guards()`: add a `discover_declared_surfaces()` pass that walks each owner and collects an owner-exported `DECLARED_SURFACES` (e.g. `<owner>/guards/surfaces.py`), then the Map generation unions them. A plugin then owns its Map rows; eviction removes them with the package. The central `surfaces.py` keeps only genuinely cross-cutting core surfaces.

**Modeling RULED 2026-08-20 (George; ledger row 4): the contract comes home, the corpus stays evicted.** The Gridkin *spec* — the RID home, the conformance contract for a core language — belongs in `tap_grid/specs/`; the `gryphon_playground` repo keeps the corpus implementation and cites core RIDs, which is the allowed direction. That satisfies the boundary rule (core cites only core) and gives Wave E's per-repo accounting a legal citation target. The mechanical move (relocating the spec file from the plugin repo, fixing core skill/doc citations) is cross-repo work deferred to the next plugin-workspace session. This requirement only makes the Map able to *express* the answer cleanly whichever way it lands: if gridkin stays core, its surfaces stay in the central `surfaces.py`; if it stays a plugin, gryphon_playground exports them and they travel with it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-validation-contributed-surfaces-1 | Discovery pass | Proposed | A `discover_declared_surfaces()` walks owners and unions owner-exported surfaces into the Map, mirroring `discover_guards()`. | |
| req-tap-plugin-validation-contributed-surfaces-2 | Plugin-owned rows | Proposed | A plugin's declared surfaces live in its package and leave with it on eviction. | The six `req-gridkin-*` rows are the motivating case. |
| req-tap-plugin-validation-contributed-surfaces-3 | Core keeps cross-cutting only | Proposed | The central `surfaces.py` retains only genuinely cross-cutting core surfaces after the migration. | |

### Clean-Eviction Acceptance
----
RID: `req-tap-plugin-validation-eviction-clean`
Status: `Proposed`

The end-to-end acceptance property that ties the others together: removing a plugin's package from disk (the post-eviction reality) MUST leave **zero** dangling central validation references and MUST green the gate for a stack that does not install it. Concretely, after a plugin is evicted:

- no central guard/ratchet/Map file names it (`req-tap-plugin-validation-no-central-slugs`);
- its baseline rows are gone (per-owner slices) or filtered out (install-aware ratchets);
- its declared Map surfaces are gone (contributed surfaces);
- its guards left with the package (already distributed).

This is the single observable that proves the distribution is complete. It is best expressed as a test that simulates eviction (drop a plugin from the installed set + remove its source) and asserts the full guard/ratchet/Map suite stays green with no stranded references.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-plugin-validation-eviction-clean-1 | No stranded references | Proposed | After eviction, no central validation file references the plugin. | The union of the other reqs. |
| req-tap-plugin-validation-eviction-clean-2 | Gate greens without it | Proposed | A stack that does not install the plugin passes the full guard/ratchet/Map suite. | Already true for the install-aware ratchets + profile guard + core-test guards. |
| req-tap-plugin-validation-eviction-clean-3 | Simulated-eviction test | Proposed | A test drops a plugin from the installed set + source and asserts the suite stays green with no dangling references. | The observable that proves completeness. |
