---
title: Plugin Refactor — Install / Pre-Boot / Snapshot Implementation Handoff
date: 2026-06-30
status: handoff
audience:
  - llm
  - developer
related_docs:
  - docs/misc/doc-plugin-system-refactor-framing.md
  - docs/misc/doc-boot-tap-boot-handoff.md
related_specs:
  - specs/spec-tap-boot-v0.md
  - tap_plugins/specs/spec-tap-plugin-architecture.md
  - tap_plugins/specs/spec-tap-plugin-type-ownership-v0.md
---

# Plugin Refactor — Install / Pre-Boot / Snapshot Implementation Handoff

> **Status update — install MVP IMPLEMENTED + validated (2026-07-01).** The packaging spike
> (below) ran green, and the install machinery is built and validated: `tap/preboot.py`
> (settings-free pre-boot: install → discover → static coherence guard → snapshot → `TAP_PLUGINS`),
> the profile `install` section (`tap_boot/schemas/boot.schema.json`), settings consumption of
> `TAP_PLUGINS`, the `docker/entrypoint.sh` pre-boot stage, `git` added to the Dockerfile, and the
> dev snapshot-disable in spawn. `genericom` is migrated to package-mode as the one real install
> target; `plugins/genericom/genericom.boot.json` is the validation profile (plugin-owned, booted via `--boot-file`); `tap/tests/test_preboot.py`
> covers the units. The related boot/plugin-arch spec reqs are flipped to `Implemented`
> (MVP) / `Partially Implemented`. **Transition state (UPDATED 2026-07-01):** the mechanical
> follow-on is DONE — the entire samsite plugin set (`fedramp_20x_ksi`, `github_core`, `roscale`,
> `computing_core`, `administrivia`, `aws_core`, `sigstore_core`, `lotr`, `samsite`) is migrated to
> package-mode (`tap_plugin.<slug>`), out of hardcoded `INSTALLED_APPS`, and installed via the
> `samsite` boot profile's `install` section; only `gryphon_playground` stays build-baked (held for
> the in-flight gryphon-engine refactor). The pre-boot conformance + reconciliation gates verify all
> 9 at boot; the full suite is green. See "Install MVP — as-built" near the end. The spike section +
> decisions below remain the design record.
>
> **Original status (2026-06-30): shovel-ready specs.** All requirements were `Proposed`; this note
> handed a fresh session the design decisions so implementation would not re-litigate them.

## What this is

The plugin refactor turns plugins from build-baked Django apps into **installable code** (the
WordPress-style direction in `doc-plugin-system-refactor-framing.md`). Two halves, two prior
owners, now both spec-complete:

1. **Type-ownership slug-rename** (`spec-tap-plugin-type-ownership-v0.md`) — every plugin-owned
   node/edge type carries its slug (`<slug>__name` nodes, `NAME__<slug>` edges); core stays bare.
2. **Install / pre-boot / registry** (`req-tap-plugin-arch-install-registry` + the new boot reqs) —
   uv-package install from a boot profile, executed in a pre-Django pre-boot stage.

## Build order (forced by the type-ownership sequencing)

The slug-rename must land **in-monorepo, before any plugin repo extraction** (a global rename is
far cheaper before plugins split into N repos), and the install work *is* what does extraction. So:

1. **Slug-rename sweep** (proof plugin `gryphon_playground`) — see *Coordination* below; it is
   currently blocked on a parallel session finishing ~45 TCK/Cypher test-gap scenarios.
2. **Install MVP**: package-mode-first via uv git-source → pre-boot stage → samsite boot profile.

The slug-rename and the install work are otherwise independent; do the rename as its own focused
pass, then the install work.

**Recommended first move on the install half: a uv package-mode spike** (decided 2026-06-30). Before
wiring the pre-boot stage, prove the packaging shape end-to-end on one plugin — make it a
wheel-buildable package with a `tap.plugins` entry point whose key **equals the slug**, install it
via `uv` (path/editable first, then git-source), and confirm Django loads its `app_config` and
`importlib.metadata.entry_points()` discovers it **without** a `plugins/<slug>` source layout, with
package data (`tap-plugin.toml`, `grift/`, `static/`) still reachable. Do it throwaway (an isolated
worktree, no shared `uv.lock` churn), surface any landmines (namespace packages, package-data
inclusion, Django app discovery from site-packages), and fold the proven recipe back into this doc.
This retires the install MVP's biggest unknown before committing the build.

## Package-mode recipe — PROVEN (spike run 2026-07-01)

The spike ran both locked stages (toy `spiketoy`, then the real grift-only `genericom`) inside the
session's web container, in throwaway `/tmp` (invisible to host git), with **zero `.venv`/`uv.lock`
churn**. Both passed. The recipe below is proven end-to-end; the install MVP builds on it.

**Isolation primitive (use this, not a fresh worktree stack):** `uv run --no-project --with <spec>`
gives a bare ephemeral env for pure-mechanism proofs; `PYTHONPATH=/app uv run --with <spec>` overlays
the wheel on the full TAP env (project deps + `tap`/`tap_web`/…) without mutating `.venv` or `uv.lock`.
`<spec>` is a built wheel, a directory (`--with-editable <dir>`), or a git requirement
(`<dist> @ git+…@<rev>`). All three install modes proved discovery + AppConfig load.

**The packaging shape (per plugin):**

1. **Layout = top-level `<slug>` package.** Transform `plugins/<slug>/*` → a `<slug>/` package dir
   with a sibling top-level `pyproject.toml`. Everything the running plugin needs — `tap-plugin.toml`,
   `grift/`, `static/`, `templates/`, `panels/` — lives **inside** the `<slug>/` package. Exclude
   non-runtime dirs (`specs/`, `tests/`) from the wheel.
2. **`pyproject.toml` (hatchling):**
   ```toml
   [project]
   name = "tap-plugin-<slug>"          # dist name (hyphens); the wheel/PyPI/git identity
   version = "0.1.0"
   requires-python = ">=3.14"

   [project.entry-points."tap.plugins"]
   <slug> = "<slug>.apps:<Slug>Config"  # entry-point KEY == slug; value = AppConfig

   [build-system]
   requires = ["hatchling"]
   build-backend = "hatchling.build"

   [tool.hatch.build.targets.wheel]
   packages = ["<slug>"]                # top-level import name == slug
   ```
   Hatchling ships **all** files under the package dir by default — `tap-plugin.toml`, `grift/*.json`,
   `static/`, `templates/` are included with **no `MANIFEST.in` / `package_data`** stanza. (Confirmed
   by inspecting the built wheel's namelist.) This is a hatchling advantage over setuptools; the
   existing `plugins/<slug>/pyproject.toml` workspace members already use hatchling.
3. **Discovery + load** (what the install MVP wires): `importlib.metadata.entry_points(group="tap.plugins")`
   → each `ep.name` is the slug, `ep.value` (`module:attr`) → `INSTALLED_APPS` entry as `module.attr`.
   Django loads the AppConfig from **site-packages** (no `plugins/<slug>` source layout); `ready()`
   runs there, manifest validates, package data resolves via `Path(app_module.__file__).parent`, and
   Django's app-dirs template/static finders see `templates/` + `static/` because `AppConfig.path`
   points into site-packages.

**Self-reference rewrite recipe** (`plugins.<slug>.` → `<slug>.`):

- **Python imports** — intra-plugin `from plugins.<slug>.x import …` → `from <slug>.x import …`.
  (`genericom`: only its two `apps.py` panel imports. Bigger plugins: any module cross-import, e.g.
  `administrivia`'s `plugins.administrivia.tap_cares…`.)
- **Manifest `[models]` / `[edges]` class paths** — `plugins.<slug>.models.X` → `<slug>.models.X`.
  (`genericom` is grift-only and has none; the rewrite is mechanically identical to the import rewrite.
  Models-bearing plugins — `aws_core`, `github_core`, `sigstore_core`, `computing_core`,
  `fedramp_20x_ksi` — must do this and add nothing else structural.)
- **`AppConfig.name` needs no edit** — `TapPluginConfig.__init_subclass__` auto-derives `name` from
  the module path, so a top-level `<slug>.apps` module yields `name="<slug>"` for free.
- **DO NOT rewrite grift `source` provenance strings** (`"batch_node": {"source": "plugins.<slug>"}`).
  That field is a free-text `batch.source` label (like `"scanner:aws"`), **not** an import path — it
  is not load-bearing. Optionally align it to `<slug>` for provenance consistency; not required to load.

**Landmines surfaced (record these so the MVP doesn't rediscover them):**

- **`git` is not in the web image.** Debian trixie `web` container has `apt` but no `git`; a git-source
  install (`git+https`/`git+file`) fails with `git: command not found`. **Add `git` to the web
  Dockerfile** — it is a runtime dependency of the install stage, not just a dev convenience.
- **`ScopedRegistry` scope moves.** Panel/editor/etc. registration scope is inferred from
  `value.__module__`, so it shifts `plugins.<slug>.*` → `<slug>.*`. Short-key lookups
  (`registry.get("<slug>-open-alerts")`) are **scope-transparent** and keep working (proven); only a
  hardcoded fully-qualified `plugins.<slug>:key` lookup or a persisted scope string would break. Grep
  for `plugins.<slug>:` before extracting a plugin.
- **`sys.path` split is expected and fine:** the plugin loads from site-packages; the app tree
  (`tap`, `tap_web`, …) loads from source. In the container the entrypoint runs from `/app`, so `/app`
  is on the path; a standalone script needs `PYTHONPATH=/app`.
- **Editable installs resolve from the source dir** (not site-packages) — that is correct for
  `--with-editable`/dev mode; only wheel and git-source installs land in site-packages.

**Bottom line:** the existing `plugins/<slug>/pyproject.toml` workspace members are 80% there —
they already use hatchling. Package-mode adds (a) the `tap.plugins` entry point, (b)
`packages = ["<slug>"]` with the contents moved into a `<slug>/` subdir, and (c) the `plugins.<slug>.`
→ `<slug>.` rewrite. No namespace-package machinery, no `MANIFEST.in`, no `package_data` needed.

## Coordination — the gryphon_playground rename (read before touching it)

- The rename was run + **verified once** in the `plugins` session (304 tests green, diff confirmed
  rename-only). It is **stashed**, not committed, on branch `session/plugins`:
  `stash@{0}` — "gryphon_playground type-ownership rename (verified, 304 green) — superseded by post-TCK re-sweep".
- It is **stale**: a parallel session is adding ~45 TCK/Cypher scenarios to `gryphon_playground`
  in **bare-name** form. Merging the stash against those new files is the hard way.
- **Do this instead:** once the TCK scenarios land and merge, **drop the stash and re-run the
  mechanical sweep over the unified corpus.** The rename is fully reproducible from
  `spec-tap-plugin-type-ownership-v0.md` (§ "Sweep cost model & proof-plugin selection"); re-running is
  cheaper and safer than reconciling a 200-file diff. Run it wherever the corpus is freshest
  (ideally a continuation of the TCK session).
- Rename method (proven): context-aware rewrite, **not** blind sed. Rewrite only type-slug *values*,
  manifest keys, edge slugs, Gryphon query tokens, data `type` fields, and `db_table` identifiers
  (single→double-underscore). **Leave alone** module paths, filenames, class names, and prose. Add
  a `db_table` rename migration. Regenerate `expected/*` oracles via `GRIDKIN_UPDATE_SNAPSHOTS=1`,
  then verify a clean run **without** the flag. Confirm the oracle diff is rename-only (symmetric
  added/removed line counts = pure 1:1 swaps, no row-set changes).
- After `gryphon_playground` proves the template, the cross-plugin-edge plugins follow
  (`sigstore_core`, `aws_core`, `github_core`, `fedramp_20x_ksi`, `samsite`); `lotr` is the other
  corpus-heavy plugin.

## Install / pre-boot — the decisions, so you don't re-derive them

Spec homes: `spec-tap-boot-v0.md` `req-boot-preboot` / `req-boot-install-section` /
`req-boot-snapshot` / `req-boot-variable-resolution`; `spec-tap-plugin-architecture.md`
`req-tap-plugin-arch-install-registry`.

**Entrypoint order:** `uv sync → pre-boot (install plugins → [switch] snapshot DB → verify) → migrate → manage.py boot (auth → population)`.

1. **Pre-boot is a settings-free stage in `docker/entrypoint.sh`.** It runs before Django reads
   settings (it *generates* `TAP_PLUGINS`), so it cannot be a Django app or `manage.py` command.
   Its logic is a settings-free Python module in **`tap/`** (app-neutral, import-safe), reading the
   boot profile as plain JSON. `tap_boot` owns the *contract* (the profile shape); `tap/` *executes*
   the pre-Django phases. (K8s `initContainers` shape.)
2. **Install MVP = package mode, via uv git-source.** A plugin is a real wheel-buildable package
   with a `tap.plugins` entry point whose key **equals the slug**. "github-first" = `<dist> @ git+https://…@<rev>`, which is the *same* mechanism as a PyPI install (source-URL change only) — **not** a git submodule, **not** vendored source under `plugins/`. Checkout/dev mode (uv path/editable) comes after the package path is proven.
3. **No load-bearing `plugins/<slug>` symlink.** Package-mode code loads from where uv installs it.
   The **registry/report** is the canonical inspection surface (a `manage.py plugins`-style command /
   generated report now; grid-native plugins-as-entities later). Converge its shape with `/healthz`
   and the deferred boot report (`req-boot-report`) — all three are "observable assembled-instance
   truth". Any `plugins/<slug>` pointer is optional tooling-only, specified separately if ever added.
4. **Two profile sections — `install` vs `population`.** `install` = the (reproducible, shared)
   plugin set; `population` = (per-deployment) ordering/seeding/firing. NetBox's
   `local_requirements.txt`-vs-`PLUGINS` split. **Two-layer drift guard:** static profile-coherence
   in pre-boot (every `population` slug is also in `install`; pre-migrate, document-level), plus
   runtime availability in boot pre-population (`req-boot-population-7`, extends the existing
   `req-boot-population-4` in-memory pre-resolution). Both fail loud.
5. **Pre-migrate snapshot, switch defaults true.** Full schema+data snapshot as pre-boot's last act,
   while the DB is **quiescent** (app not started). **Serial + verify before `migrate`** (the
   restore-point guarantee; `pg_dump` ACCESS SHARE vs migrate ACCESS EXCLUSIVE would contend).
   **Restore is a deliberate human action, never auto.** `pg_dump` now; copy-on-write volume
   snapshot is the scale upgrade path. Build it as a **callable primitive in `tap/`** so a later
   periodic snapshot system (concurrent/online, against a live DB) is "call it on a schedule +
   retention". Dev disables via the env override; a skip logs loud (WARNING).
6. **Roll-forward recovery, never roll-back** (`req-boot-idempotent-3`). A migrated-but-unpopulated
   DB is *incomplete, not inconsistent*; recovery is fix-config-and-re-run (`migrate` is
   forward-idempotent). Never reverse-migrate; destructive-migration recovery is snapshot restore.
   **No transaction spans `migrate` + `population`.**
7. **Boot-variable resolution** (`req-boot-variable-resolution`): precedence `flag > env > profile
   > default`; env mapping `TAP_BOOT_<SECTION>__<KEY>` (e.g.
   `TAP_BOOT_INSTALL__SNAPSHOT_BEFORE_MIGRATE`); resolve-once and record effective-value + source in
   the report (so an override is never a silent profile divergence). Settings-free resolver in
   `tap/`. The snapshot switch is the first key; wire env+profile+default now, reserve the flag layer.

## MVP scope vs deferred

- **MVP:** package-mode uv git-source install; pre-boot stage in entrypoint; `install` section +
  both drift guards; pre-migrate snapshot (`pg_dump`, switch+dev-disable); registry/report as
  inspection surface; boot-variable resolver (env+profile+default); samsite boots from a profile.
- **Deferred (named, don't build now):** checkout/dev-mode polish; volume snapshots; periodic
  snapshot scheduler + retention; CLI-flag override layer; plugin config (`TAP_PLUGIN_CONFIG` stays
  an empty reserved seam — samsite keeps config in collector secrets); plugin dependency resolution;
  updates/rollback/enable-disable/signing/grants (the `doc-plugin-system-refactor-framing.md`
  "ecosystem board").

## Install MVP — as-built (2026-07-01)

What shipped this session (machinery-first, minimal install set — George's call):

- **`tap/preboot.py`** — the settings-free pre-boot module (`python -m tap.preboot --profile <id>`).
  Order: resolve snapshot switch → install `install` plugins (idempotent `is_satisfied` skip) →
  `discover_entry_points` (identity check: entry-point key must == slug) → `static_coherence_guard`
  → `take_snapshot` (`pg_dump -Fc` + `pg_restore --list` verify). Emits `TAP_PLUGINS` (AppConfig
  paths) on **stdout**; all logs to **stderr**. Any failure → `PrebootError` → exit 1 → entrypoint
  aborts before `migrate` (DB untouched). Includes the boot-variable resolver (`resolve_var`,
  env > profile > default, `TAP_BOOT_<SECTION>__<KEY>`, empty-env-as-absent) and the snapshot primitive.
- **`tap_boot/schemas/boot.schema.json`** — new `install` section (`plugins[]` with `slug`/`enabled`/
  `note`/`source`, where `source` is a `oneOf` git/editable/path; `snapshot_before_migrate` switch).
- **`tap/settings.py`** — consumes `TAP_PLUGINS` env → splices AppConfigs into `INSTALLED_APPS`
  before `tap_api`. `BUILD_BAKED_PLUGIN_SLUGS` (in `tap/preboot.py`) is the transition set; a test
  keeps it equal to the hardcoded `INSTALLED_APPS` plugins.
- **`docker/entrypoint.sh`** — pre-boot stage inserted after `uv sync`, before `createcachetable`/
  `migrate` (snapshot precedes all schema changes): `TAP_PLUGINS="$(uv run python -m tap.preboot …)"`.
  `manage.py boot` was **deliberately kept at spawn-time** (not moved into the entrypoint) so a
  container restart does not re-fire collectors.
- **`Dockerfile`** — `git` added (was missing; required for git-source plugin installs).
- **`plugins/genericom/`** — migrated to package-mode (nested `genericom/` package + pyproject with
  the `tap.plugins` entry point) as the one real install target. `plugins/genericom/genericom.boot.json`
  is the validation profile (plugin-owned, booted via `--boot-file`; moved out of `boot/` 2026-07-02).
  `tap/tests/test_preboot.py` covers the units.
- **Security edge — `tap/logging.py:discover_scan_roots`** (found + fixed this session): the authZ-
  coverage AND log-site scanners discovered plugin roots by `plugins/<slug>/tap-plugin.toml`.
  Package-mode nests it at `plugins/<slug>/<slug>/tap-plugin.toml`, so **migrating a plugin to
  package-mode silently hid its code from both scanners** — a real security-posture gap. Fixed to
  recognize both layouts. Any future in-repo package-mode migration stays scanned. (A fully extracted
  plugin in its own repo carries its own scanning — out of the monorepo scanners' scope by construction.)

**Validated:** editable/path/git install modes (spike); pre-boot install → discover → guard →
snapshot → `TAP_PLUGINS`; idempotent reboot no-op; env snapshot-disable (loud WARNING); static
coherence guard sad-path abort; settings load genericom package-mode into the real app registry;
full container restart runs the entrypoint pre-boot stage; instance healthy. `tap_boot`+`tap`+
`tap_plugins` suites green except one **pre-existing-red** test unrelated to this work
(`test_json_filename_convention` on `plugins/gryphon_playground/scenarios/tck-coverage.json`, red on
main `a40419e`).

**Immediate follow-on — DONE (2026-07-01):** the samsite plugin set (`fedramp_20x_ksi`,
`github_core`, `roscale`, `computing_core`, `administrivia`, `aws_core`, `sigstore_core`, `lotr`,
`samsite`) is migrated to package-mode, moved out of hardcoded `INSTALLED_APPS` into the `samsite`
profile `install` section, with `plugins.<slug>.` collector keys / manifest `[models]` paths /
cross-plugin imports rewritten to `tap_plugin.<slug>`. `BUILD_BAKED_PLUGIN_SLUGS` is down to
`{gryphon_playground}` (held for the in-flight gryphon-engine refactor). Each migration folded in the
source-identity / versioning / Tier-0 dependency declarations at authoring time; the pre-boot
conformance + reconciliation gates verify all 9 at boot; the full suite is green. The Done-test
("samsite plugins uv-installed") passes. Still open: the registry/report inspection surface
(`req-tap-plugin-arch-install-registry` -3/-5), the plugin `depends_on` schema + consistency gate +
resolver (deferred, declare-now — `samsite` is the first real cross-plugin dependency), and the
plugin-creation skill bump below.

## Also bump

- **The plugin-creation skill** (`doc-plugin-system-refactor-framing.md` "refactor skill") — once
  the install shape is dialed in, update the skill so generated plugins are package-mode-compliant
  (wheel-buildable, `tap.plugins` entry point = slug, slug-namespaced types).

## Validation

- Tests via the containerized stack: `scripts/dc exec -T web uv run pytest …` (multi-session
  worktree — always `scripts/dc`, never raw `docker compose`; host Python is stale).
- Done-test for the install MVP: a fresh instance stands up from a samsite-class boot profile with
  its plugins uv-installed, migrated, seeded, and collected — and a reboot is a fast no-op (no
  re-pull). Promotion is gated on the dev-validation suite (`spec-dev-validation.md`).
