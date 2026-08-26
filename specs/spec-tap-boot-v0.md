# TAP Boot v0 Specification

## Philosophy

`tap_boot`-style booting is how a TAP instance goes from a fresh database to a usable, populated, self-describing instance — **declaratively, deterministically, and with zero human interaction**. Before `tap_boot`, that journey was split between a flat collector-only boot profile (`tap_cares`' `fire_boot_collectors`) and `scripts/spawn-session.sh`, which did the *actual* ordered standup in bash: migrate → `sync_auth` → `import_plugin_grift` → reconcile → fire collectors → `createsuperuser`. The orchestration lived in a dev shell script, so a customer standup had no declared, reproducible contract. **v0 (landed) closes that gap:** one `manage.py boot` command applies one boot profile in fixed phases, and `spawn-session.sh` calls it.

The core doctrine is:

> One bootloader applies one multi-section boot profile in fixed phases. The profile *is* the configuration: config-as-code, lights-out, zero-touch. Standup is the same path in dev and in a customer's environment.

Boot is **configuration-as-code**, not an interactive wizard. There are no prompts, ever. The profile declares the desired instance state; the bootloader makes it so, idempotently, and fails loud if the profile is malformed.

Boot config is **trusted at the same level as application code**. A privileged operator's boot profile may do powerful, destructive things — overwrite the instance keystone, hard-sync capabilities, deactivate users. The bootloader validates *shape* (schema) and *correctness* (idempotent convergence, ordering), but it does **not** sandbox the operator's intent. The guards exist to stop a malformed profile from silently bricking a zero-touch standup — they are anti-footgun, not anti-operator.

The complexity bar is a real, multi-plugin instance: bringing up a samsite-grade instance (auth + several interdependent plugins + an ordered collector pipeline) exercises enough of the machinery to prove it. We design to that bar and let it teach us where the model needs to bend — in particular, whether collector firing stays a distinct step or becomes something plugins own as they come online.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | One Path | A single bootloader command is the canonical standup for both dev and customer instances. |
| 2. | Config As Code | The boot profile fully declares instance state; standup is zero-touch and lights-out. |
| 3. | Composable | Each capability app owns its profile section's schema and apply logic; the bootloader composes them. |
| 4. | Idempotent | Re-applying a profile converges; standup is repeatable and safe to re-run. |
| 5. | Ordered & Loud | Phases run in a fixed, safe order; the whole profile is validated before anything is applied; failures are loud. |

## v0 Scope (minimal-useful)

v0 builds the **minimal standup path**: a single `manage.py boot` command that runs the existing standup operations in fixed phases under the bootloader actor, replacing the ordered bash steps in `spawn-session.sh` (`req-boot-spawn-bridge`). This is `step-rampart-launch-ready`'s "clean instance bring-up" — one declarative, reproducible command, with the dev path being the seed of the customer path.

All boot logic — command, phase sequencing, boot context, profile handling, logging, and (when built) the section handlers + registry — lives in the **`tap_boot` app**, first in `INSTALLED_APPS`, depending on and calling the capability apps' reusable, boot-agnostic ops. The domain apps stay boot-agnostic: **no boot logic in `tap_grid`/`tap_auth`/`tap_cares`/`tap_plugins`.**

> **Status — v0 landed 2026-06-24.** `manage.py boot --profile <id>` runs `auth → population` and is what `spawn-session.sh` now calls (the old `sync_auth`/`import_plugin_grift`/`reconcile_collectors`/`fire_boot_collectors`/`createsuperuser` steps are gone; `fire_boot_collectors` is removed). The profile is the ordered-steps shape (`boot/<id>.boot.json`, version 1, `population.steps` of `seed-plugin`/`fire-collector`); `boot/core_dev.boot.json` (core + `grid_fixtures`, no collectors) is the plain-spawn default (2026-07-03 baseline flip, `req-boot-minimal-baseline`), and `boot/test_all.boot.json` (the former `base` seed-all union) the test/gate superset. The samsite demo record re-homed into `tap-plugin-samsite` as an in-package record booted by pointer (2026-08-09, `req-boot-bootstrap-samsite-rehome` in `spec-tap-boot-bootstrap.md`). Boot-agnostic ops added/reused: `tap_auth.sync_auth` + new `tap_auth.ensure_initial_admin`, `tap_plugins.seeding.seed_plugin`, `tap_cares.reconcile_collector_nodes` + new `tap_cares.services.fire_collector_and_await`. Phases live as functions in `tap_boot/orchestrator.py` so each becomes a section-handler body when `req-boot-sections` lands. Covered by `tap_boot/tests/` and proven live on samsite (boto3 collector fired a real AWS pull; a missing-secret collector aborted loud). Deferred per below remain `Proposed`.

Deliberately **deferred until a real consumer drives the shape** (skepticism-of-overbuilding, per the Rampart roadmap):

- **App-registered section handlers + registry + per-section schema composition (`req-boot-sections`) and two-layer validate-before-apply (`req-boot-validate`)** — kept `Proposed` as the planned shape, but **not built in v0**. Their first consumer is the authN **Google OIDC provider configuration** (`req-tap-auth-providers`): that config will define the section + schema shape concretely, so it is built when authN lands, not guessed ahead of it. v0 implements the phases directly in the boot command; the structure is chosen so a phase's op-call becomes a handler body later — an additive refactor, not a rewrite.
- **Instance keystone generation (`req-boot-identity`)** — backlog, not critical path. In v0 the instance keystone comes from plugin GRIFT (the samsite bundle already lays down the "Samsite" keystone).
- **`--dry-run`/`plan`, the formal idempotency convergence contract (`req-boot-idempotent`), and a durable boot report (`req-boot-report`)** — deferred; v0 relies on the underlying ops being idempotent and on action logging.
- **Pre-boot stage, install section, pre-migrate snapshot, and boot-variable resolution (`req-boot-preboot`, `req-boot-install-section`, `req-boot-snapshot`, `req-boot-variable-resolution`)** — the installable-plugin path. **Implemented as the plugin-refactor MVP** (`tap/preboot.py`, 2026-07-01; `step-rampart-first-paying-customer`), paired with `req-tap-plugin-arch-install-registry`. The entrypoint now runs a settings-free pre-boot stage (install declared plugins → snapshot) before `migrate`, turning the old hardcoded-build/`migrate`-directly standup into a declared, profile-driven, recoverable install stage. Transition state: build-baked plugins still coexist in `INSTALLED_APPS`; the MVP is validated with the one migrated package-mode plugin (`genericom`), and the full samsite plugin-set migration to package-mode is the mechanical follow-on.

## Roadmap Alignment

This spec supports `plan/road-rampart.md`:

- `step-rampart-first-paying-customer` names the boot loader directly: *"expand to support plugins… boot profiles that you can load and will be smart enough to start up with all plugins and you'll need to figure out the auth system and what it means to self-configure (remember all those places where you hardcoded config in secrets files?)"* and *"Configuration… important settings can be added and set… initially stored as part of the boot profile."*
- It is the substrate `spec-tap-auth-v0.md` (`req-tap-auth-boot`) already assumes: an `auth` section in "the larger TAP boot profile" applied by a bootloader that composes per-app schema fragments. That bootloader is defined here.

## Prior Art

This spec follows well-trodden declarative-provisioning patterns rather than inventing boot machinery:

- **Kubernetes `kubectl apply`** — declarative desired-state that converges idempotently; re-applying the same manifest is a no-op. TAP's idempotent re-apply follows this.
- **Terraform** — config-as-code with `plan` (dry-run) before `apply`, and a hard line between *authoring* config and *applying* it. TAP's `--dry-run` and the boot-applies / authoring-is-separate split mirror this.
- **Helm values / Kustomize** — a single declarative document composed of sections owned by different concerns. TAP's multi-section profile + per-app section handlers mirror this, but composition lives in plain Python (app-registered handlers), not template/`$ref` machinery.
- **cloud-init / Ansible** — zero-touch, no-prompt provisioning from a declarative spec. TAP's lights-out doctrine mirrors this.
- **Django `migrate`** — idempotent forward application already runs in the container entrypoint; boot layers the instance-state convergence above migrations, not inside them.
- **Existing TAP machinery** — the `tap_cares` collector boot profile (`spec-dev-boot-collectors.md`), the `tap_grid` registry's duplicate-key guard (`tap_grid/registry.py`), and the `req-tap-auth-boot` auth-boot ordering are absorbed and generalized rather than replaced.

For the plugin-refactor additions (pre-boot stage, install section, snapshot, variable resolution), a further prior-art pass shaped the design:

- **NetBox plugin model** — splits `local_requirements.txt` (install: which packages, reproducible) from `PLUGINS` / `PLUGINS_CONFIG` (enable + configure, per-deployment). This is exactly TAP's `install`-vs-`population` separation (`req-boot-install-section`); NetBox's failure mode (a slug in `PLUGINS` never installed crashes the instance) is what TAP's static coherence guard prevents earlier.
- **Kubernetes `initContainers`** — declared in one Pod spec but executed as a distinct run-to-completion stage before the main containers; a failed init container means the main containers never start. TAP's pre-boot stage mirrors this: declared in the boot profile (`tap_boot`'s contract), executed before `manage.py boot` by a `tap/` wrapper, fatal-on-failure (`req-boot-preboot`).
- **Viper / Cobra config precedence** — the near-universal `flag > env > config-file > default` ladder for 12-factor apps, with the resolved config (plus provenance) as the single source of truth. TAP's boot-variable resolution adopts this shape (`req-boot-variable-resolution`); env-name mapping (prefix + `__` nesting) follows the Spring Boot / pydantic-settings convention.
- **Managed-database pre-upgrade snapshots** (RDS auto-snapshot before a major-version upgrade; the universal "back up before you migrate" discipline) — the restore point that makes forward-only migrations safe. TAP takes it in pre-boot while the DB is quiescent (`req-boot-snapshot`); `pg_dump` now, copy-on-write volume snapshot as the scale upgrade path.

## Relationship To Other Specs

- **Extended by `specs/spec-tap-boot-observability.md`.** The observability surfaces around this spec's contract: a collector-readiness preflight before population mutates (`req-boot-obs-preflight`), structured self-test checks on the abort path (`req-boot-obs-abort-detail`, extending `req-boot-abort-signal`'s reason), the durable per-run boot record that realizes `req-boot-report`'s deferred report + `req-boot-variable-resolution-3`'s promised provenance surface (`req-boot-obs-record`), and the dev-spawn presentation contract (`req-boot-obs-spawn-presentation`).
- **Extended by `specs/spec-tap-boot-bootstrap.md`.** This spec owns the profile *shape* and phase application (given a profile, stand the instance up). The bootstrap spec sits one level above and owns *where the profile comes from*: a single-command `--from <pointer>` that fetches a boot record out of a versioned plugin artifact (records ship as package data), selects among multiple records per plugin, and stages it as the active profile before pre-boot proceeds. `--from` subsumes `--boot-file`; the pointer resolves through `spec-tap-plugin-architecture.md`'s source machinery. Single-file boot → single-command boot (the netboot lineage).
- **Absorbs `specs/spec-dev-boot-collectors.md`.** Its collector-firing mechanics — firing via `run_collection`, sequential ordered firing, per-profile `on_failure`, opt-in selection — are preserved as the `fire-collector` step-type inside this spec's population phase. The standalone `fire_boot_collectors` framing is generalized into the bootloader; the collector spec's RIDs remain the detailed contract for *how a collector is fired*.
- **Provides the bootloader `req-tap-auth-boot` assumes.** The `auth` section is `tap_auth`'s registered section handler; the auth-boot ordering (capability sync → protected group sync → built-in actor sync → initial admin → provider validation/build → provider/domain deactivation) is that handler's internal apply sequence, run within this spec's `auth` phase.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-boot-app | [Bootloader Ownership](#bootloader-ownership) | Implemented | **v0.** One `manage.py boot`; all boot logic lives in `tap_boot`, which calls capability-app ops |
| req-boot-profile | [Multi-Section Profile](#multi-section-profile) | Implemented | **v0 (minimal).** One profile drives standup (plugins to seed + collectors to fire) via the `population` section; app-owned multi-section composition deferred |
| req-boot-preboot | [Pre-Boot Stage](#pre-boot-stage) | Implemented | **Plugin-refactor MVP (`tap/preboot.py`).** Settings-free entrypoint stage (install plugins → snapshot) before `migrate`; `tap_boot` owns the contract, the `tap/` wrapper executes it. Validated with the one package-mode plugin (`genericom`); `manage.py boot` stays at spawn-time (not relocated into the entrypoint) — deliberate, to avoid collector re-fire on every restart |
| req-boot-install-section | [Install Section](#install-section) | Implemented | **Plugin-refactor MVP.** Profile `install` section (desired plugin set), separate from `population`; static coherence guard in pre-boot. During the transition, build-baked plugins coexist (a `BUILD_BAKED_PLUGIN_SLUGS` transition set, kept honest against `INSTALLED_APPS` by test); the runtime availability half already exists via `resolve_tap_plugin` (`req-boot-population-4`). Full samsite package-mode migration is the follow-on |
| req-boot-minimal-baseline | [Minimal Core Baseline](#minimal-core-baseline) | Implemented | **Baseline flip + lean-boot gate landed 2026-07-03.** `core` (zero plugins) is the product baseline; `core_dev` (core + `grid_fixtures`) is the default a plain spawn / the entrypoint boots; `base` is renamed → `test_all` (the permanent test/gate union). Replaces `base = install-everything`, which does not scale and becomes unwritable once plugins live in their own repos. `core` is kept **honestly** bootable in isolation by the **lean-boot independence gate** (`scripts/gate-lean`, `req-dev-validation-lean-boot`): a fresh, lean-installed stack that catches core→plugin-dep import leakage (the `requests`/`jwt` class) the full-venv cold-boot gate cannot |
| req-boot-snapshot | [Pre-Migrate Snapshot](#pre-migrate-snapshot) | Implemented | **Plugin-refactor MVP.** `pg_dump -Fc` full snapshot before `migrate`, switch defaults true, verify via `pg_restore --list`; restore is a human action; callable `tap/` primitive; dev disables via env (spawn writes it into `.env.local`). Volume-snapshot upgrade path still deferred |
| req-boot-search-role | [Search Read-Only Role Provisioning](#search-read-only-role-provisioning) | Implemented | **Post-migrate.** Idempotent boot step provisions the dedicated `search_readonly` DB role, grants it `SELECT` on only the searchable + spine tables (grant set derived from the model layer via `tap_grid/grid_tables.py`), and pins its resource GUCs (`statement_timeout`/`lock_timeout`/`temp_file_limit`/`work_mem`); realizes `req-grid-search-readonly-role.sec` + `req-grid-traversal-exec-resource-bounds.sec` |
| req-boot-variable-resolution | [Boot Variable Resolution](#boot-variable-resolution) | Implemented | **Plugin-refactor MVP.** Ladder env > profile > default (flag layer reserved); `TAP_BOOT_<SECTION>__<KEY>` env mapping; resolve-once + provenance. Empty-env-as-absent guard (compose materializes unset `${VAR:-}` as `""`) |
| req-boot-sections | [App-Registered Section Handlers](#app-registered-section-handlers) | Proposed | **Deferred** to first consumer (authN Google OIDC config); handlers/registry live in `tap_boot` |
| req-boot-validate | [Validate Before Apply](#validate-before-apply) | Proposed | **Deferred** with `req-boot-sections`. v0 keeps only: schema shape + unknown plugin/collector key fails loud |
| req-boot-phases | [Fixed Phase Order](#fixed-phase-order) | Implemented | **v0: auth → population** (bootloader resolved in auth, bound for population); fuller order is future |
| req-boot-population | [Population Phase](#population-phase) | Implemented | **v0.** Ordered seed-plugin / fire-collector; unknown plugin/collector/bundle aborts before any mutation |
| req-boot-collector-timeout | [Collector Await Timeout](#collector-await-timeout) | Implemented | **v0.** Per-`fire-collector`-step `timeout_seconds` (default 90s); per-collector default is backlog |
| req-boot-collector-criticality | [Per-Collector Boot Criticality](#per-collector-boot-criticality) | Proposed | **Backlog.** Per-`fire-collector`-step criticality overriding the profile-wide `on_failure`; auth-parity with per-provider `critical_for_boot` |
| req-boot-identity | [Identity Section](#identity-section) | Proposed | **Backlog, not critical path.** Generate a keystone only if none exists; v0 keystone comes from plugin GRIFT |
| req-boot-idempotent | [Idempotent Re-Apply](#idempotent-re-apply) | Implemented | **v0 principle** (ops are idempotent; seed + admin re-apply tested); formal convergence contract deferred |
| req-boot-trust | [Config-As-Code Trust Model](#config-as-code-trust-model) | Implemented | **v0.** Boot config is code-level-trusted; guards are anti-footgun, not anti-operator |
| req-boot-secrets | [Secret References Only](#secret-references-only) | Implemented | **v0.** Profiles reference `TAP_SECRETS_ROOT` keys / env, never embed secrets; missing secret fails loud at apply |
| req-boot-required-secrets | [Required Secrets Declaration](#required-secrets-declaration) | Implemented | **Built 2026-08-09** (design locked same day). Top-level `required_secrets` manifest (envelope identity `scope`/`key`/`kind` + least-privilege `note`) plus bare `"scope:key"` consumption refs on population steps; two fail-loud coherence rules (every ref resolves; no entry orphaned by enabled steps) make the dual declaration a checked guard, not a drift point; presence + kind verified **offline** in the population preflight before the live self-tests (`req-boot-obs-preflight`). The host-/provisioning-readable half of the credential story — what the live self-test (in-container, network) cannot provide |
| req-boot-spawn-bridge | [Spawn Bridge](#spawn-bridge) | Implemented | **v0.** `spawn-session.sh` calls the bootloader; dev == customer standup |
| req-boot-report | [Boot Logging](#boot-logging) | Implemented | **v0.** Boot logs actions with secrets redacted; durable report deferred |
| req-boot-abort-signal | [Standup Abort Signal](#standup-abort-signal) | Implemented | **Landed 2026-07-03.** Boot is the first consumer of the logging `ABORT` signal (`req-tap-logging-abort-signal`): preboot/migrate/boot fatal paths emit it and `spawn-session.sh` fast-fails on it (or on the container exiting) instead of the 300s readiness timeout |

---

### Bootloader Ownership
----
RID: `req-boot-app`  
Status: `Implemented`

A single bootloader command is the canonical path that stands a TAP instance up from a fresh, migrated database to a usable, populated, self-describing instance. It is a platform capability, not a plugin.

#### Implementation

- The bootloader is an explicit `manage.py` command (e.g. `manage.py boot`), not silent app-startup mutation.
- It owns: profile resolution and load, full-profile validation, fixed phase sequencing, per-section dispatch to registered handlers, idempotent application, and action logging.
- It does **not** own provider/auth/collector internals — each is owned by its capability app's section handler (`req-boot-sections`). The bootloader is the orchestrator and the contract enforcer.
- **Code home: the `tap_boot` app owns all boot logic.** Everything boot — the `manage.py boot` command, profile handling, the boot context (`tap_bootloader` actor resolution + per-run state), phase sequencing, action logging, and (when built, `req-boot-sections`) the section handlers + their registry — lives in the first-party `tap_boot` app. `tap_boot` sits first in `INSTALLED_APPS` and depends on the capability apps, calling their reusable, boot-agnostic ops (`tap_auth.sync_auth`, the `tap_grid` service layer, `tap_cares` collector firing / reconcile, the plugin GRIFT import path). **No boot logic lives in `tap_grid`/`tap_auth`/`tap_cares`/`tap_plugins`** — the dependency direction is one-way (`tap_boot → everything`), which is also why the section-handler base/registry live in `tap_boot`, not `tap_grid` (nothing below boot imports them). Same rationale as `tap_auth`: a cross-cutting management plane deserves a named app.
- Database migrations remain in the container entrypoint (idempotent, safe to re-run) and are a precondition of boot, not a boot phase.
- The bootloader is the canonical standup for **both** dev (`spawn-session.sh`, `req-boot-spawn-bridge`) and customer deployments, so the path is dog-fooded continuously before a customer sees it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-app-1 | Explicit Command | Proposed | Boot is an explicit `manage.py` command, not startup-time mutation. | |
| req-boot-app-2 | Single Orchestrator | Proposed | One bootloader owns sequencing, validation, and dispatch; sections own their internals. | |
| req-boot-app-3 | Canonical Standup | Proposed | The same bootloader path is used for dev and customer standup. | |
| req-boot-app-4 | tap_boot Code Home | Proposed | All boot logic — command, sequencing, boot context, profile handling, logging, and (when built) section handlers + registry — lives in `tap_boot`; domain apps expose boot-agnostic ops that boot calls; no boot logic in other apps. | |

---

### Multi-Section Profile
----
RID: `req-boot-profile`  
Status: `Implemented`

A boot profile is a single config-as-code document composed of named sections.

#### Implementation

> **v0 (minimal):** the profile drives standup with the plugins to seed + collectors to fire (≈ today's flat `boot/<id>.boot.json`, e.g. `boot/test_all.boot.json`, or an in-package record like samsite's) plus minimal admin info. Named, app-owned sections composed from per-app JSON-Schema fragments (below) are the planned shape but are **deferred** to their first consumer (`req-boot-sections`); v0 does not compose per-app schemas.

- A profile is a version-controlled file, selected `--profile` > `TAP_BOOT_PROFILE`. **A profile is required by default**: a missing one fails loud, so a deployment never silently starts empty-but-apparently-healthy because `TAP_BOOT_PROFILE` was accidentally omitted. The single escape hatch is an explicit `--allow-empty`, an opt-in to an auth-only, no-outbound standup. (This collapses the earlier two-mode framing — dev no-op vs deploy-required — into one rule: requiring a profile is the safe default *everywhere*, and an intentional empty standup is always explicit. One flag, no inverted `--require-profile`.)
- v1 sections: `identity`, `auth`, `population`. The section set is open — any capability app may register a section (`req-boot-sections`).
- The profile supersedes the flat collector-only profile shape: the existing collector list becomes the `fire-collector` steps of the `population` section (`req-boot-population`).
- A profile carries only declarative state and secret *references* (`req-boot-secrets`), never secret values.
- Each section's shape is defined by its owning app's mandatory JSON Schema fragment; the profile as a whole is the composition of those fragments plus a thin bootloader-owned envelope (version, profile metadata, section ordering-within-population).
- A profile with no `population` outbound steps is a safe, no-network standup (identity + auth only).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-profile-1 | Named Sections | Proposed | A profile is a document of named sections, not a flat list. | |
| req-boot-profile-2 | Supersedes Flat Profile | Proposed | The collector-only profile is absorbed as the population fire-collector steps. | |
| req-boot-profile-3 | References Not Secrets | Proposed | Profiles contain only declarative state and secret references. | |
| req-boot-profile-4 | Opt-In Outbound | Implemented | An explicit `--allow-empty` (no profile) is an auth-only standup that reaches out to nothing. | |
| req-boot-profile-5 | Profile Required By Default | Implemented | Boot requires an explicit profile by default; a missing profile fails loud (single escape hatch: `--allow-empty`), never a silent empty-but-healthy start. No inverted `--require-profile` flag. | |

---

### Pre-Boot Stage
----
RID: `req-boot-preboot`  
Status: `Proposed`

Plugin installation and the pre-migrate snapshot run in a **pre-boot stage** in the container entrypoint — *before* `migrate` and before `manage.py boot`. Both must precede Django importing settings: install *generates* the plugin settings (`TAP_PLUGINS`), and the snapshot must predate any schema change to be a valid restore point.

#### Implementation

> **Plugin-refactor — not built in v0.** The v0 entrypoint already runs `uv sync → migrate → manage.py boot`; this generalizes the "migrations are a precondition of boot, not a boot phase" rule (`req-boot-app`) into a named pre-boot precondition slot. Lands with the plugin refactor (`step-rampart-first-paying-customer`, the installable-plugins critical path), paired with `req-tap-plugin-arch-install-registry`.

- **Settings-free, so it cannot live in `tap_boot`.** Pre-boot runs before Django reads settings — indeed it *generates* part of them — so it cannot be a Django app or a `manage.py` command. Its logic is a settings-free Python module the entrypoint invokes; per the avoid-app-interdependency posture it lives in **`tap/`** (app-neutral, import-safe), reading the boot profile as plain JSON. The install/packaging mechanics it calls (uv resolution, `tap.plugins` entry-point discovery, the plugin registry/report) are owned by `spec-tap-plugin-architecture.md` (`req-tap-plugin-arch-install-registry`); pre-boot is the boot-profile-side *executor* of the install set.
- **`tap_boot` owns the contract, not the pre-Django execution.** The boot profile (a `tap_boot` document) declares the install set (`req-boot-install-section`) and the snapshot switch (`req-boot-snapshot`); the `tap/` wrapper executes them. This is the Kubernetes `initContainers` shape — declared in one spec, executed as a distinct run-to-completion lifecycle stage before the main process. The boot **phase** order (`req-boot-phases`) is unchanged; pre-boot sits *before* `manage.py boot`, which is exactly what its name encodes (and disambiguates it from the in-`boot` `bootstrap` phase).
- **Entrypoint ordering:** `[cache-seed] → uv sync → pre-boot (install plugins → [switch] snapshot DB → verify) → migrate → manage.py boot (auth → population)`. (The optional cache-seed step copies the image's pre-compiled wheel cache into an empty uv-cache volume — a speed optimization only; the phase contract is unchanged.)
- **Reboot stability.** Pre-boot is idempotent and fast on reboot: an already-installed plugin set is a no-op (no re-pull), satisfying "a container that already has its plugins just works." The install report / registry is the idempotency oracle (`req-tap-plugin-arch-install-registry`).
- **Failure is fatal — abort the whole standup.** An install / identity-mismatch / uv-resolve failure, or a snapshot failure while the switch is on, aborts pre-boot loud; the entrypoint never reaches `migrate` or `boot`. Because pre-boot runs *before* `migrate`, such an abort leaves the database untouched (the same "abort before any mutation" guarantee `req-boot-population-4` gives, extended to schema).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-preboot-1 | Settings-Free Entrypoint Stage | Implemented | `tap/preboot.py` (`python -m tap.preboot`) runs in `docker/entrypoint.sh` before `migrate`; a settings-free, django-free module, not a Django app or `manage.py` command. | |
| req-boot-preboot-2 | Contract In tap_boot, Execution In tap/ | Implemented | The profile declares the install set + snapshot switch (`tap_boot` schema); `tap/preboot.py` executes them. Boot phase order unchanged. | |
| req-boot-preboot-3 | Reboot Is A No-Op | Implemented | `is_satisfied()` skips an already-installed plugin (git: matching pinned rev; editable/path: present). Validated: a re-run logs "already satisfied — no-op". | Offline `wheelhouse` idempotency (dist present at the wheel version) lands with `req-tap-plugin-arch-sources-6` |
| req-boot-preboot-4 | Failure Aborts Before Migrate | Implemented | Install/identity/guard/snapshot failure raises `PrebootError` → non-zero exit; the entrypoint aborts before `migrate` (DB untouched). Validated via an incoherent profile. | |

---

### Install Section
----
RID: `req-boot-install-section`  
Status: `Implemented`

The boot profile gains an `install` section — the desired plugin set — kept **separate** from `population`.

#### Implementation

> **Plugin-refactor — not built in v0.** The install/packaging side is `req-tap-plugin-arch-install-registry`; this requirement owns the boot-profile-side declaration and the cross-section drift guard.

- **Two sections, two questions.** `install` declares *which plugins go on the instance* — uniform for everyone who runs that plugin: TAP slug, source provenance, credential reference for private sources, enabled surfaces, install mode (package/checkout). `population` declares *how this deployment orders, seeds, and fires them* — highly deployment-specific. This is the well-trodden separation: NetBox splits `local_requirements.txt` (install) from `PLUGINS`/`PLUGINS_CONFIG` (enable/configure); Terraform splits `required_providers` (pinned, reproducible) from the resource/ordering graph. Install is reproducible-and-shared; ordering/firing is per-deployment.
- **One document, two readers, two times.** The `install` section is consumed by the pre-boot wrapper (pre-Django, `req-boot-preboot`); `population` is consumed by `manage.py boot`. The wrapper reads `install` as plain JSON before settings exist; it is therefore *not* a `req-boot-sections` handler (those register at Django `ready()` and run inside the boot command).
- **Identity boundaries.** `install` entries carry the TAP `slug` + source provenance + mode; the Python distribution/package name, `app_config`, and `tap.plugins` entry-point key remain the packaging concern (`req-tap-plugin-arch-install-registry` Identity Boundaries). The section declares *what TAP wants*; uv/packaging/discovery resolves *how it is obtained*.
- **Drift between the two sections — a two-layer guard** (both fail loud, neither silent):
  1. **Static profile-coherence (pre-boot, pre-migrate):** every plugin slug referenced in `population` also appears in `install`. Document-level — no DB, no registries — so it runs *before* `migrate` and catches the common authoring drift ("named it in population, forgot to add it to install") before any schema change, so the migrate-then-fail-in-population path never triggers for it. Because it is about the profile *document*, it survives a future `population` refactor untouched.
  2. **Runtime availability (boot, pre-population):** every plugin a `population` step names is actually installed, registered, and migration-applied — extends `req-boot-population-4`'s in-memory pre-resolution ("abort before any grid mutation"). This is the runtime readiness check; it lives with `population` (and moves with it when `population` is refactored).
- These are genuinely *different* checks (document coherence vs runtime readiness), so two homes is correct, not a smell. NetBox's own failure mode — a slug in `PLUGINS` that was never installed crashes the instance — is exactly what layer 1 prevents, earlier and louder.
- **Declared-vs-actual reconciliation (pre-boot, a third axis).** The two guards above reconcile the profile's *own* sections (`install` ↔ `population`). A separate axis reconciles the `install` section (declared desired set) against what is *actually installed on disk* (the `tap.plugins` entry points in the venv). The *missing* direction — declared+enabled but not installed — is already fatal in the entry-point identity check (`req-boot-preboot`). The reconciliation guard closes the *other* direction: a package-mode distribution installed but named by **no** enabled `install` entry — a stale install left from a prior profile, a plugin the profile `enabled: false`-d but never uninstalled, or an undeclared/manually-installed plugin. Loading undeclared code at standup is exactly the supply-chain surface the declared-vs-actual security posture guards, so it **fails closed** (`spec-security-posture.md` `req-sec-cheap-edges`: over-restriction relaxes cheaply, omission retrofits expensively). It is scoped to package-mode plugins by construction (build-baked plugins carry no `tap.plugins` entry point). In the normal entrypoint flow `uv sync --all-packages` prunes package-mode dists before pre-boot reinstalls the enabled set, so extras are normally zero; a non-empty set is real venv/profile drift. This is the load-path guard; the richer human-facing declared-vs-installed-vs-loaded view is the deferred registry/report (`req-tap-plugin-arch-install-registry-3/-5`), not this abort-path check.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-install-section-1 | Install Separate From Population | Implemented | `install` (plugins[] + snapshot switch) is a distinct profile section from `population`; both in `tap_boot/schemas/boot.schema.json`. | |
| req-boot-install-section-2 | Pre-Boot Reads Install | Implemented | `tap/preboot.py:read_profile` reads `install` as plain JSON before Django; not a `req-boot-sections` handler. | |
| req-boot-install-section-3 | Static Coherence Guard | Implemented | `static_coherence_guard` fails loud pre-migrate if a `population` seed-plugin slug is neither in `install` nor build-baked. | |
| req-boot-install-section-4 | Runtime Availability Guard | Implemented | The registered-check half is `resolve_tap_plugin` in boot pre-resolution (`req-boot-population-4`); a package-mode `population` slug not installed → not in TAP_PLUGINS → not registered → fails loud. Migration-applied depth remains a thin future extension. | |
| req-boot-install-section-5 | Install Reconciliation Guard | Implemented | `reconciliation_guard` fails closed if a package-mode plugin is installed (exposes a `tap.plugins` entry point) but is not a declared+enabled `install` entry — undeclared code must not load at standup (declared-vs-actual, `req-sec-cheap-edges`). The inverse (declared but not installed) is already fatal in the entry-point identity check. | |

---

### Minimal Core Baseline
----
RID: `req-boot-minimal-baseline`
Status: `Proposed`

The canonical baseline is **minimal, not maximal.** The old `base` profile installed *every* plugin, which quietly served two unrelated roles: the product/dev baseline (what a fresh instance *is*) and the test-everything vehicle (the one container the FULL test lane boots so a single pytest run can import every plugin). Conflating them is why `base` grew into a kitchen sink. Installing everything does not scale as plugins proliferate, and becomes **literally unwritable** once plugins live in their own repos/dists (the core repo cannot enumerate them) — so `base` is a monorepo artifact that must not survive the plugin refactor.

The replacement model:

- **`core` (`boot/core.boot.json`) — the baseline.** Zero plugins: the core `tap_*` apps only (grid + auth + web + api + cares + boot + health), a bare grid with only the core-owned types (`entity`, `edge`, `batch`, `keystone`, `dimension`, `search`), reaching out to nothing. What a real deployment starts from and *adds to*; the intended default a plain spawn boots. Minimal attack surface (the reconciliation posture favours the smallest declared set). **Landed + live-verified:** a zero-plugin `core` boots healthy, reconciliation `0 == 0`.
- **`core_dev` (`boot/core_dev.boot.json`) — the core test tier.** `core` + `grid_fixtures` (the neutral `grid_fixtures__*` vocabulary the core suites build fixtures from), nothing else. **Landed.**
- **Every other profile is additive.** `samsite` = `core` + its plugin set. A **plugin's standalone-test profile is plugin-owned**. Its location has **moved into the package**: `spec-tap-boot-bootstrap.md` (`req-boot-bootstrap-records-in-package`) supersedes the old plugin-root `plugins/<slug>/<slug>.boot.json` location with in-package boot **records** at `tap_plugin/<slug>/boot/<name>.boot.json` — because a root-level file does not ship in the wheel and so cannot be fetched from an index/wheelhouse, whereas an in-package record rides the artifact and is source-type-agnostic. They boot via a bootstrap pointer (`spawn --from <source-ref>#<record>`), and a plugin may ship several (instance flavors). First instance: `gryphon_playground`'s `boot/playground.boot.json` + `boot/soak.boot.json` (`core` floor + `grid_fixtures` + `gryphon_playground`).

Test tiering is the corollary: the FULL lane's "one container, everything imported" model is the *only* thing `base = everything` was really buying. Moving to a minimal baseline means the core suites run on `core_dev`, each plugin's suite runs on its own per-plugin profile, and the fleet-asserting tests (e.g. `tap_plugins/tests/test_report.py`, which asserts specific plugins appear in the report) run on the union tier — see `req-dev-validation-suite-tiers`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-minimal-baseline-1 | Core Is Zero-Plugin | Implemented | `boot/core.boot.json` declares no plugins and boots healthy (reconciliation `0==0`, `TAP_PLUGINS` empty). | Live-verified via throwaway spawn. |
| req-boot-minimal-baseline-2 | Core-Dev Test Tier | Implemented | `boot/core_dev.boot.json` = `core` + `grid_fixtures` only; the profile the core suites boot against. | |
| req-boot-minimal-baseline-3 | Additive Profiles | Implemented | Every non-core profile is `core` + an explicit plugin set; no profile installs "everything" by default. The lone union (`test_all`) is explicitly the test/gate superset, not a deployment default. | Landed 2026-07-03. `core`/`core_dev`/`test_all` (repo-local) and the samsite record (in-package since 2026-08-09) all additive over the `core` floor. |
| req-boot-minimal-baseline-4 | Default Repoint | Implemented | The default spawn / entrypoint profile is repointed from `base` to `core_dev` (fast inner-loop: core + grid_fixtures). `core` is the explicit product baseline. | Landed 2026-07-03: `spawn-session.sh` `BOOT_PROFILE:-core_dev`, `docker/entrypoint.sh` `TAP_BOOT_PROFILE:-core_dev`. The full lane / promote gate explicitly boots `test_all`, not the default. |
| req-boot-minimal-baseline-5 | Retire Base → test_all | Implemented | `base` is renamed to `test_all`: the **permanent union** the suite runs against (**landed 2026-07-03**). Lean per-profile *test lanes* are infeasible (pytest discovery is file-path — an absent plugin's tests hard-error at collection; `test_settings` sees the installed venv, not a profile), so the union stays. Core independence is bridged by the **lean-container independence gate** (`scripts/gate-lean`, `req-dev-validation-lean-boot`) that stands up a genuinely fresh, lean-installed stack (own compose project → own venv volume) and full-boots `core` — the only shape that actually catches core→plugin-dep import leakage (`requests`/`jwt`), since a shared full venv masks it. Landed + proven both directions 2026-07-03 (core boots healthy in isolation; an injected core `import boto3` is caught RED). A plugin's standalone-test profile is plugin-owned (`plugins/<slug>/*.boot.json`, `spawn --boot-file`), created only on demand. | Full spec: `req-dev-validation-lean-boot` in spec-dev-validation.md; pairs with `req-dev-validation-suite-tiers`. |

---

### Pre-Migrate Snapshot
----
RID: `req-boot-snapshot`  
Status: `Proposed`

As the last act of pre-boot — *before* `migrate` — the instance takes a full schema+data database snapshot, gated by a switch that **defaults to true**. This is the disaster-recovery primitive that makes forward-only migrations (`req-boot-idempotent`) safe.

#### Implementation

> **Plugin-refactor — not built in v0.** The first thing that will save a botched first-field-deployment database; also the foundation for a later periodic snapshot system.

- **Why before migrate, in pre-boot: the application has not started.** The DB is quiescent — no connections, no in-flight writes, no DDL contention — so the snapshot is fast, consistent, and uncontended, and it is a clean restore point for the *entire* standup, not just `migrate`.
- **Serial, always (at standup).** The snapshot completes and is verified before `migrate` mutates anything: the restore-point guarantee demands it, and `pg_dump`'s `ACCESS SHARE` would contend with `migrate`'s `ACCESS EXCLUSIVE` if they overlapped (the lock-queue cascade `req-boot-idempotent` avoids). Because the DB is quiescent, "serial" costs only the dump's own wall-clock. Big-DB latency is solved by snapshot *technology* — a copy-on-write volume snapshot (the upgrade path) — never by racing `migrate`.
- **Verify-before-proceed.** A backup that cannot be restored is a guarantee that is a latent lie until it fails; the snapshot is confirmed (completed, non-empty, restorable) before `migrate` runs. If the switch is on and the snapshot fails, abort loud (`req-boot-preboot`) — never `migrate` without the promised net.
- **Restore is a deliberate human action, never automatic.** The switch guarantees a restore *point exists* and records its location + provenance in the boot/install report; auto-restore-on-failure (masks the real problem, invites restore-loops) is explicitly rejected. Recovery from a bad/destructive migration or upgrade is *restore the snapshot*, not *reverse-migrate* (`req-boot-idempotent`).
- **v0 = `pg_dump`** (single portable artifact, MVCC-consistent, no app lock). **Volume/storage snapshot** (ZFS/LVM/cloud-volume; RDS-style pre-upgrade auto-snapshot) is the documented **scale upgrade path** — same light-now / heavy-later shape as the plugin DB-isolation path (`req-tap-plugin-type-db-affordance`).
- **Switch + dev-disable.** The switch is a boot-variable (`req-boot-variable-resolution`) in the `install`/pre-boot section, **default-true on absence** (safe-by-default: a new prod profile that forgets the field still snapshots; over-restriction relaxes cheaply, a forgotten snapshot retrofits expensively). Dev worktrees disable it via the env override (`spawn-session.sh` writes it into the session's `.env.local`), since dev DBs reset freely. **A skipped snapshot logs loud (WARNING)** — a disabled safety net must announce itself.
- **Foundation for periodic snapshots.** The snapshot is a small callable primitive in `tap/` (take → verify → name in report), so a future periodic/scheduled snapshot system is "call it on a schedule + add retention/rotation" — *don't build the scheduler now; just shape the primitive*. Periodic snapshots run against a **live** DB and are therefore **concurrent/online** (`pg_dump` is built for it: MVCC-consistent, `ACCESS SHARE` only) — the opposite concurrency answer from the quiescent standup case, for the same underlying reason (what else is touching the DB).
- **Security.** The artifact is sensitive-at-rest: inherit location/permission/retention discipline and record provenance. Lower-risk for TAP than most, since secrets live in `TAP_SECRETS_ROOT` files, not the DB — named, not implied.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-snapshot-1 | Snapshot Before Migrate | Implemented | `take_snapshot()` runs as the last pre-boot act, before `createcachetable`/`migrate`, while the app is not started (DB quiescent). | |
| req-boot-snapshot-2 | Switch Defaults True | Implemented | `snapshot_before_migrate` boot-variable, default true on absence; dev disables via `TAP_BOOT_INSTALL__SNAPSHOT_BEFORE_MIGRATE=false`; a skip logs WARNING. | |
| req-boot-snapshot-3 | Serial + Verify Before Proceed | Implemented | `pg_dump -Fc` then `pg_restore --list` verification (non-empty + restorable) before the entrypoint proceeds; failure with switch on raises. | |
| req-boot-snapshot-4 | Restore Is A Human Action | Implemented | The dump is written + its path logged; nothing auto-restores. | |
| req-boot-snapshot-5 | pg_dump Now / Volume Upgrade Path | Implemented | Uses `pg_dump -Fc`; copy-on-write volume snapshot remains the documented scale upgrade path. | |
| req-boot-snapshot-6 | Callable Primitive | Implemented | `take_snapshot()` is a settings-free `tap/` primitive reusable by a future periodic system. | Periodic system itself is backlog |

---

### Boot Variable Resolution
----
RID: `req-boot-variable-resolution`  
Status: `Proposed`

A boot-profile value may be overridden at runtime through a standard precedence ladder, so per-environment overrides (e.g. disabling the snapshot in dev) are a *general mechanism*, not a bespoke flag per setting.

#### Implementation

> **Plugin-refactor — not built in v0.** Adopt the *shape* as the convention now; implement the minimal resolver for the keys actually in play (the snapshot switch is the first).

- **Precedence (highest wins): CLI flag > environment variable > boot-profile value > built-in default.** This is the near-universal config-resolution standard (Viper/Cobra, built for 12-factor apps): a default in the profile, a deployment override via env, a single-run override via flag.
- **Env naming — systematic, not ad hoc.** Map a profile key to an env name by: prefix `TAP_BOOT_`, uppercase, nested sections joined by `__` (double-underscore — bash-safe on every platform, unlike `:`/`.`; the convention Spring Boot / pydantic-settings / typed-settings converge on). Example: `install.snapshot_before_migrate` → `TAP_BOOT_INSTALL__SNAPSHOT_BEFORE_MIGRATE`. This fits TAP's existing env convention (`TAP_GRID_ID`, `TAP_SECRETS_ROOT`, `TAP_PLUGINS`, `TAP_PLUGIN_CONFIG`). The snapshot switch is then one key under this scheme, not a one-off `TAP_SKIP_DB_SNAPSHOT`.
- **Resolve-once + provenance (protects config-as-code, `req-boot-trust`).** The resolver produces one effective value per key and records the **effective value and its source** (flag/env/profile/default) in the boot/install report. An override is therefore never a *silent* divergence from the declared profile — it is a loud, audited line ("snapshot: false — source: env"). Viper's own rule applies: the resolved configuration, with provenance, is the single source of truth.
- **Pre-Django constraint.** The snapshot key is read by the settings-free pre-boot wrapper, so the resolver is a settings-free helper in `tap/` (env + CLI + JSON + default; no Django settings framework). It is shared by the pre-boot wrapper (pre-Django) and `manage.py boot` (post-Django).
- **Scope — don't build Viper.** Adopt the precedence + naming + report-the-effective-value as the standing convention so every future boot variable inherits it. Wire **env + profile + default** now (env is what dev-disable needs); reserve the **CLI-flag** layer in the convention for its first consumer.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-variable-resolution-1 | Precedence Ladder | Implemented | `resolve_var()`: env > profile > default (flag layer reserved for the CLI-override backlog). | |
| req-boot-variable-resolution-2 | Systematic Env Mapping | Implemented | `env_var_name()` maps `TAP_BOOT_<SECTION>__<KEY>`; no bespoke per-setting names. Empty-env-as-absent guarded. | |
| req-boot-variable-resolution-3 | Resolve-Once + Provenance | Implemented | `ResolvedVar(value, source)` returns one effective value + its provenance; logged at pre-boot. Full boot-report surface is `req-boot-report` (deferred). | |
| req-boot-variable-resolution-4 | Settings-Free Resolver | Implemented | `resolve_var()` is a settings-free `tap/` helper usable pre-Django; post-Django reuse lands when more variables need it. | |

---

### App-Registered Section Handlers
----
RID: `req-boot-sections`  
Status: `Proposed`

Each capability app owns its profile section through a registered handler. Apps cannot overwrite each other's sections.

#### Implementation

> **Deferred — not built in v0** (see [v0 Scope](#v0-scope-minimal-useful)). Kept `Proposed` as the planned shape; its first consumer is the authN Google OIDC provider configuration (`req-tap-auth-providers`), which will define the section + schema shape concretely. v0 implements the phases directly in the boot command (`req-boot-phases`); a phase's op-call becomes a handler body when this lands — an additive refactor, not a rewrite.

- A section handler bundles: a stable `section_key`, a **mandatory** JSON Schema fragment for that section's shape, and a `validate(section_data)` / `plan(section_data)` / `apply(section_data)` interface — not merely a schema plus `apply(dry_run=True)`. `validate` does **semantic pre-resolution** (resolve references, catch impossible config) before any mutation; `plan` reports what would change; `apply` mutates.
- Handlers register on a `tap_grid` `Registry` (`tap_grid/registry.py`), which **raises `ImproperlyConfigured` on a duplicate key** by default (no `merge_fn`). Two apps registering the same `section_key` is therefore a hard startup error — the immutability is structural, not convention.
- Registering a handler without a schema fragment is itself a registration error: every section is schema-described or it does not exist.
- The bootloader passes each handler **only its own section's data** — this isolates *configuration*: a handler cannot be driven by another section's config, so config-level cross-section coupling is structurally impossible. It is **not** a code sandbox: handler code is trusted Python and can technically query or mutate anything, exactly like all boot code (`req-boot-trust`). The guarantee is honest as **data isolation, not code isolation**.
- Section handlers and the registry live in `tap_boot` (not the domain apps): each handler calls the relevant capability app's boot-agnostic ops (`auth` → `tap_auth.sync_auth` + initial admin + provider config; `identity` → the `tap_grid` keystone service; `population` → the plugin GRIFT import path + `tap_cares` collector firing). This keeps the dependency direction one-way (`req-boot-app`).
- The registry is populated at app `ready()` time (read-only registration only, consistent with `req-tap-plugin-load-v0-ready-readonly`); the handlers' `apply` runs only under the explicit boot command.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-sections-1 | Registered Handlers | Proposed | Sections are provided by app-registered handlers on a `tap_grid` registry. | |
| req-boot-sections-2 | Duplicate Section Fails | Proposed | Two handlers for one `section_key` raise `ImproperlyConfigured` at startup. | |
| req-boot-sections-3 | Schema Mandatory | Proposed | A handler without a JSON Schema fragment cannot register. | |
| req-boot-sections-4 | Section Data Isolation | Proposed | A handler receives only its own section's *data* (config isolation, no cross-section config coupling); handler *code* remains trusted, not sandboxed. | |

---

### Validate Before Apply
----
RID: `req-boot-validate`  
Status: `Proposed`

The whole profile is validated before any of it is applied.

#### Implementation

> **Deferred with `req-boot-sections` — not built in v0** (see [v0 Scope](#v0-scope-minimal-useful)). The two-layer framework lands with the section handlers it validates (first consumer: authN Google OIDC config). v0 keeps only the cheap guard that already exists in `fire_boot_collectors`: an unknown plugin/collector key fails loud before any population step (`req-boot-population`).

- Validation has **two layers, both before any mutation**:
  1. **Schema (shape):** every present section validates against its handler's JSON Schema fragment; unknown section keys and unknown fields fail loud (`additionalProperties: false` at the section level).
  2. **Semantic (pre-resolution):** each handler's `validate` resolves references before any `apply` runs — unknown plugin/collector keys, missing required secret references, unsupported profile version, and impossible/contradictory config (e.g. an auth config that would lock out every admin) are caught up front, not discovered mid-mutation. This generalizes `fire_boot_collectors`' existing "unknown key aborts before any collector fires." Schema alone catches shape, not these.
- A `--dry-run` / `plan` mode runs both validation layers and reports the planned actions (which sections, which population steps, in what order) **without mutating** state. It is the **best current plan, not a guarantee** — like Terraform's plan, state can drift between plan and apply, so a dry-run is advisory.
- Dry-run defaults to **offline / no outbound**: schema + semantic validation + local plan only. Live checks (provider reachability, OIDC discovery, upstream probes) are opt-in via an explicit `--live-checks`, never the default.
- Failures are loud and machine-readable: the error names the offending section/field/step so a zero-touch caller (or an AI operator) can correct the profile and re-run deterministically.
- Validation is independent of where the profile came from (boot-embedded today; a standalone source later, per the secondary non-boot config-source item in `spec-tap-auth-v0.md`'s Backlog) — the validator operates on the loaded document, not its origin.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-validate-1 | Validate All First | Proposed | All sections validate before any `apply` runs. | |
| req-boot-validate-2 | Unknown Rejected | Proposed | Unknown section keys / fields fail loud. | |
| req-boot-validate-3 | Dry Run Advisory + Offline | Proposed | `--dry-run`/`plan` validates and reports the best current plan (advisory, may drift) without mutating; defaults offline, live checks opt-in via `--live-checks`. | |
| req-boot-validate-4 | Loud Machine-Readable Failure | Proposed | Validation errors name the offending location precisely. | |
| req-boot-validate-5 | Semantic Pre-Resolution | Proposed | Beyond schema shape, handlers semantically validate (unknown plugin/collector/secret-ref, bad version, impossible config) before any `apply` mutates. | |

---

### Fixed Phase Order
----
RID: `req-boot-phases`  
Status: `Implemented`

Boot runs sections in a fixed, code-defined phase order. Profiles cannot reorder phases.

#### Implementation

> **v0 phase order: `auth → population`** (see [v0 Scope](#v0-scope-minimal-useful)). The fuller `bootstrap → identity → auth → population` described below is the future shape: v0 needs neither a separate `bootstrap` actor-resolve phase nor an `identity` keystone phase, because nothing writes through the service layer before `auth`. In v0 the boot actor is resolved *in* the `auth` phase (after `sync_auth` creates it) and bound (`acting_as`) for `population`.

- Coarse phase order is hardcoded, not config. **v0: `auth → population`** (the fuller order below is added in code as those phases gain content).
- **`bootstrap` resolves the boot actor first.** Identity, auth, and population are all service-layer writes, and the auth doctrine forbids `User=None` at the service boundary (`req-tap-auth-actor-model`) — so a named actor must exist before the *first* boot write. The `bootstrap` pre-phase creates-or-resolves the `tap_bootloader` `program` built-in actor (`req-tap-auth-builtins`); every subsequent boot write runs as `tap_bootloader`. The chicken-and-egg of the *first* actor is resolved cleanly: creating it is a low-level bootstrap write *below* the named-actor contract — the same place the auth spec puts migrations / raw table creation — and once it exists, identity/auth/population all go through the service layer as a named actor. This supersedes any "identity is the first phase" reading: identity writes the keystone, which needs the actor, so it cannot be first.
- **Authority, scoped — not omnipotence.** Boot writes need *authorization*, and capabilities sync in the `auth` phase, so the bootloader actor must be able to write during `identity`. Rather than implicit boot-omnipotence, the `bootstrap` pre-phase grants `tap_bootloader` an **explicit, least-privilege, code-defined boot-capability bundle** — exactly what boot needs (`grid.write`, `grid.import_grift`, the auth/capability/provider-management capabilities, `config.manage`, `cares.run_collectors`) and no more. It deliberately **excludes destructive grid demolition boot never needs** — `grid.purge` (DEBUG-destructive) and `grid.delete` — so a boot *bug* cannot nuke the grid. Boot's own destructive operations (keystone overwrite, capability prune, user deactivation) live in the auth/config/capability domain, not arbitrary grid mutation, so the exclusion costs boot nothing.
  - This bounds the blast radius of boot *bugs* (anti-footgun, `req-boot-trust`); it is **not** a sandbox against a *malicious* profile. Because the bundle includes capability-management, a malicious trusted profile could self-escalate — accepted, since boot config is code-level-trusted by design. Least-privilege here protects against accidents and documents boot's reach: the right level of defense, not security theater.
  - The grant is established at `bootstrap` (resolve the actor + grant its scoped bundle) before `identity` — an explicit scoped grant, not a disabled gate. This supersedes the earlier "implicit boot privilege" framing and settles the authz chicken-and-egg cleanly.
- The load-bearing invariant remains **auth before population**: the remaining `program` built-in actors, capabilities, and grants land in the `auth` phase before `population` seeds or collects under them.
- Profiles control **what is in** each section and the **intra-population** step order (`req-boot-population`) — never the phase sequence itself.
- Phase order is intentionally rigid until there is a concrete reason to relax it; new phases are added in code with explicit placement, not declared by profiles.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-phases-1 | Fixed Order | Proposed | Phase order (`bootstrap → identity → auth → population`) is code-defined; profiles cannot reorder phases. | |
| req-boot-phases-2 | Auth Before Population | Proposed | Auth (capabilities, built-in actors, grants) is applied before any actor-attributed population work. | |
| req-boot-phases-3 | Bootstrap Actor First | Proposed | A `bootstrap` pre-phase resolves the `tap_bootloader` actor before identity; all boot writes run as it, so no boot write is `User=None`. | |
| req-boot-phases-4 | Least-Privilege Boot Actor | Proposed | `tap_bootloader` is granted an explicit least-privilege boot-capability bundle (no `grid.purge`/`grid.delete`), not full admin — bounding the blast radius of boot bugs. | |

---

### Population Phase
----
RID: `req-boot-population`  
Status: `Implemented`

The population phase brings plugins online and populates them, as an ordered list of declared, interleavable steps.

#### Implementation

> **v0:** built — it maps directly onto the existing standup ops (`import_plugin_grift` path + `reconcile_collector_nodes` + collector firing). With `req-boot-validate` deferred, the unknown-key pre-resolution below is v0's validate-before-mutate.

- The `population` section is an **ordered** list of steps; each step is one of the v1 step-types:
  - `seed-plugin`: bring a plugin online — its types/edges/searches are registered (already done at `ready()`), then its GRIFT seed bundles are imported via the `import_plugin_grift` path. **Convergence caveat:** GRIFT dedups by batch identity — re-importing an *identical* batch is skipped, so an *edited* bundle does **not** converge on re-boot unless its batch identity changes. Boot resolves this explicitly rather than assuming upsert: the default is **durable version-bumped batches** (a plugin bumps its batch version when content changes, so the new identity converges), with a **DEBUG-only boot force/reimport** mode for dev iteration; production never blind-force-reimports. This decision is named so it is chosen, not silently assumed — the trap is an edited-but-not-bumped bundle that silently skips while boot reports success.
  - `fire-collector`: fire a collector via `run_collection`, with the per-profile `on_failure` and sequential-ordering semantics absorbed from `spec-dev-boot-collectors.md`.
- Steps run **strictly in declared order, sequentially, no overlap**. The declared order is load-bearing: a collector that reads another collector's output must be ordered after it so its edges mint in one boot pass (the established collector-pipeline dependency, stated generically).
- v1 default arrangement mirrors today: all `seed-plugin` steps, then `fire-collector` steps. The step model deliberately permits **interleaving** (seed a plugin, fire its collectors, seed the next) so that a plugin whose collector depends on a prior plugin being fully *online and collected* can be expressed without restructuring.
- **Open seam (let samsite teach us):** whether `fire-collector` stays a top-level population step or migrates into a plugin-owned "after I am online, fire these" hook is deferred. The step model is chosen so either outcome is a later refinement, not a rewrite. v1 does not require plugin-owned collector hooks; it only refuses to foreclose them.
- A `seed-plugin` step naming an unknown plugin slug or an unknown `bundle`, or a `fire-collector` step naming an unknown collector key, fails loud in **pre-resolution** — which runs against in-memory registries (the plugin manifest, the `tap_cares` collector registry) **before any grid mutation, including the collector-node reconcile**. A malformed profile therefore aborts without writing or updating a single node (`req-boot-population-4`). An unknown `bundle` is a hard error rather than a silent zero-bundle no-op, so a typo in boot config cannot become a green boot with missing seed data.
- **Runtime availability (plugin refactor, `req-boot-install-section`).** When installable plugins land, pre-resolution additionally fails loud if a `population` step names a plugin that is not actually installed/registered/migration-applied — the runtime half of the two-layer drift guard (the static half, "every `population` slug is also in `install`", runs earlier in pre-boot, before `migrate`). This is the same in-memory, abort-before-mutation pre-resolution generalized to "declared in population but not on the instance."

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-population-1 | Ordered Steps | Proposed | Population is an ordered list of steps applied strictly in order, sequentially. | |
| req-boot-population-2 | Two Step-Types | Proposed | v1 step-types are `seed-plugin` and `fire-collector`. | |
| req-boot-population-3 | Interleaving Permitted | Proposed | The model allows seed/fire steps to interleave, not only seed-all-then-fire-all. | |
| req-boot-population-4 | Unknown Key Fails | Implemented | An unknown plugin slug, collector key, or `bundle` name aborts in pre-resolution — before any grid mutation, including the collector-node reconcile. | |
| req-boot-population-5 | Collector Semantics Absorbed | Proposed | `fire-collector` preserves `run_collection`, `on_failure`, and ordered-firing semantics. | |
| req-boot-population-6 | GRIFT Convergence Explicit | Proposed | `seed-plugin` convergence is bounded by GRIFT batch identity: version-bumped batches converge; a DEBUG-only force/reimport serves dev; production never blind-force-reimports; edited-but-not-bumped must not silently skip-as-success. | |
| req-boot-population-7 | Runtime Plugin Availability | Implemented | The registered dimension holds via `resolve_tap_plugin` pre-resolution: a package-mode `population` plugin not installed is absent from TAP_PLUGINS → not in INSTALLED_APPS → not registered → fails loud. Explicit migration-applied assertion is a thin future extension. | Plugin refactor |

---

### Search Read-Only Role Provisioning
----
RID: `req-boot-search-role`  
Status: `Implemented`

Boot provisions the dedicated least-privilege database role that the read-only search
connection authenticates as (`req-grid-search-readonly-role.sec`). It runs after migrations
settle — so every plugin table exists — and grants the role `SELECT` on exactly the
Gryphon-searchable tables plus the grid spine, deriving that set from the searchable
registry (`req-grid-traversal-exec-searchable.sec`) rather than a hand-maintained list.

#### Implementation

- **Ordering.** The step runs inside `manage.py boot`, which the entrypoint runs *after*
  `migrate` (`req-boot-preboot`: `uv sync → pre-boot → migrate → manage.py boot`). All
  plugin tables therefore exist, and the app registry (hence the searchable registry
  populated at `__init_subclass__`) is loaded, when the grant set is computed.
- **Idempotent, re-run every boot** (`req-boot-idempotent`). The step: ensures the role
  exists (`CREATE ROLE ... LOGIN` if absent, password from a `tap_cares` secret), `REVOKE`s
  all table privileges from it, then `GRANT SELECT` on the computed set (searchable model
  tables + `tap_entity`, `tap_edge`, `tap_entity_type`, `tap_dimension`). Re-running
  reconciles the grant to the current searchable set, so a plugin added since last boot is
  covered (or, if newly un-searchable, revoked) without manual steps.
- **Authority.** The GRANT is issued by the bootloader connecting as the table-owning
  application role (which holds grant authority), not as the read-only role itself. The
  read-only role never holds DDL or write privileges.
- **Resource GUCs pinned in the same step.** After the grants, the step pins the
  resource-bound GUCs on the role via `ALTER ROLE <role> SET statement_timeout=… SET
  lock_timeout=… SET temp_file_limit=… SET work_mem=…`
  (`req-grid-traversal-exec-resource-bounds.sec`, `req-grid-search-readonly-role.sec-6`).
  Values come from configuration with conservative defaults; the `ALTER ROLE … SET` is
  idempotent, so re-running boot converges them like the grants.
- **Connection-privilege posture is explicit, not defaulted.** The step sets the role's
  database/schema privileges deliberately rather than inheriting Postgres defaults: `GRANT
  CONNECT` on the TAP database and `GRANT USAGE` on the schema(s) holding the searchable +
  spine tables (so `SELECT` is reachable), and **`REVOKE TEMP`/`TEMPORARY` on the database**.
  Revoking temp closes the residue that `default_transaction_read_only` leaves open — a
  read-only transaction may still write *temporary* tables, so the role is denied temp-table
  creation at the privilege layer rather than relying on it to be harmless. The role holds no
  privileges on any non-searchable schema.
- **Fail-safe direction.** A searchable table that is somehow not yet granted is simply
  unreadable (a `permission denied`, caught loud by `req-grid-db-permission-flaw.sec`),
  never over-exposed. Under-grant is a visible CI/runtime failure; over-grant cannot happen
  because the set is derived, not authored.

**Landed vs. deferred in v0 (honest scope).** The role, the model-layer-derived `SELECT` grants,
the idempotent reconcile, the owner-issued authority, and the role-pinned resource GUCs are
**built** (`tap_grid/search_role.py`, provisioned in the boot grid-infra phase). Two parts of
the *target* design above are not yet built and remain `Proposed`:

- **Grant set is the full grid-table classification, not a narrower searchable subset.** The
  opt-in searchability gate (`req-grid-traversal-exec-searchable.sec`) is `Proposed`, so
  `GRYPHON_SEARCHABLE` does not exist yet; the grant set is derived from the grid-table
  classification (`GRID_TABLE_ROLE` via `tap_grid/grid_tables.py`, the shared single source
  of truth also consumed by the ORM read backstop — `req-grid-table-classification.sec` in
  `spec-grid-security.md`, incl. its provision-time reconcile against tables that actually
  exist). "Searchable" ≡ "every grid table" until the gate lands and narrows it. This is
  broader than the eventual target but still strictly grid-only — the fail-safe direction
  holds.
- **`REVOKE TEMP`/`TEMPORARY` is not yet issued** (`req-boot-search-role-7`, `Proposed`). The
  read-only-transaction temp residue is currently bounded by the role-pinned `temp_file_limit`
  (a 1 GB hard cap on spill), not closed at the privilege layer. Revoking `TEMP` interacts
  with the default `PUBLIC` grant (it would have to be revoked from `PUBLIC`, touching the app
  role too), so it is deferred to a reviewed change rather than added blind here.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-search-role-1 | Runs After Migrate | Implemented | The step runs after `migrate` completes, so every plugin table exists before grants are computed. | Guaranteed by the entrypoint order. |
| req-boot-search-role-2 | Grant Set Derived From Registry | Implemented | The granted tables are computed from the `GRYPHON_SEARCHABLE` registry plus the fixed spine tables, not a hand-maintained allowlist. | |
| req-boot-search-role-3 | Idempotent Reconcile | Implemented | Re-running the step converges the role's grants to the current searchable set (adds new, revokes removed) with no manual action. | |
| req-boot-search-role-4 | Least Privilege | Implemented | The provisioned role holds only `SELECT` on the granted set — no write, no DDL, no other tables. | |
| req-boot-search-role-5 | Issued By Owner Role | Implemented | Grants are issued by the table-owning application role; the read-only role never gains privilege-granting authority. | |
| req-boot-search-role-6 | Resource GUCs Pinned On The Role | Implemented | The same step pins `statement_timeout`, `lock_timeout`, `temp_file_limit`, and `work_mem` on the role via idempotent `ALTER ROLE … SET`, from configuration with conservative defaults. | Realizes `req-grid-traversal-exec-resource-bounds.sec` at the role. |
| req-boot-search-role-7 | Connection Privileges Set Explicitly | Proposed | The step grants `CONNECT` on the database and `USAGE` on the searchable/spine schema(s), and revokes `TEMP`/`TEMPORARY` on the database, so temp-table creation is denied at the privilege layer (closing the read-only-transaction temp residue) rather than defaulted. | Least-privilege connection posture. |

#### Future
- When the fuller phase order lands (`req-boot-phases`), this step is a natural member of a
  grid/infrastructure phase; in v0 it attaches as a post-migrate provisioning step.
- **Least-privilege DB-role decomposition (backlog).** Today a single "god" DB role owns the
  tables and is used for boot, migrations, grants, *and* runtime app queries — an
  owner-by-convenience, not by design. `sec-5` above (`Issued By Owner Role`) leans on that
  owner. The backlog item is to split it into three scoped roles: (1) a **bootstrap /
  migration role** holding only the DDL + `GRANT` authority that plugin install and `migrate`
  need, used exclusively by `manage.py boot` / `migrate` and never at runtime; (2) a
  **runtime application role** holding DML only (no DDL, no ownership) for the web app's
  writable `default` connection; (3) the read-only search role (`tap_gryphon_ro`,
  `req-grid-search-readonly-role.sec`) already planned. Payoff beyond least privilege: if the
  *runtime* role is not the table owner, PostgreSQL Row-Level Security policies apply to it
  **without** needing `FORCE ROW LEVEL SECURITY`, directly de-risking the RLS owner-bypass
  edge named for the future dimension-scoping work (`spec-security-posture.md`). Deferred, not
  built; the bootstrap role still needs DDL (migrations create/alter tables), so it is
  privileged but boot-scoped and distinct from the runtime identity.

---

### Collector Await Timeout
----
RID: `req-boot-collector-timeout`  
Status: `Implemented`

A `fire-collector` step awaits its collector's job to a terminal state for a bounded time; the bound is configurable per step.

#### Implementation

- Each `fire-collector` step may declare an optional integer `timeout_seconds`; the bootloader passes it to `tap_cares.services.fire_collector_and_await`. A collector that does not reach a terminal state within the bound is a step failure (subject to the population `on_failure`), not an indefinite hang.
- When a step omits `timeout_seconds`, the bootloader applies a single default (`DEFAULT_COLLECTOR_TIMEOUT_SECONDS`, 90s) — deliberately short so snappy collectors finish well inside it; a slow collector (a full cloud pull) declares a higher value on its step (e.g. the samsite record gives boto3 / samsite-compliance 300s).
- **Backlog:** the better long-term home for the *default* is the collector itself — a per-collector `COLLECTION_TIMEOUT_SECONDS` class default on `CollectorBase` (mirroring the existing `SELF_TEST_LIVE_CHECK_TIMEOUT_SECONDS`) that the step-level `timeout_seconds` overrides. v0 uses the single bootloader fallback; the per-collector default is deferred until a collector needs it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-collector-timeout-1 | Per-Step Timeout | Implemented | A `fire-collector` step's optional `timeout_seconds` bounds the await; exceeding it is a step failure, not a hang. | |
| req-boot-collector-timeout-2 | Default When Unset | Implemented | A step with no `timeout_seconds` uses the bootloader default (90s). | |
| req-boot-collector-timeout-3 | Per-Collector Default | Proposed | A per-collector `COLLECTION_TIMEOUT_SECONDS` default that the step overrides. | Backlog |

---

### Per-Collector Boot Criticality
----
RID: `req-boot-collector-criticality`  
Status: `Proposed`

A `fire-collector` step can declare its own boot-criticality — *critical* (a failed run aborts boot) or *best-effort* (a failed run is logged and boot continues) — overriding the profile-wide default.

#### Implementation

> **Backlog — not built in v0.** Captured here so the boot-criticality model is consistent across boot sections.

- **Today (v0):** boot-criticality for collectors is **profile-wide**, not per-collector. `on_failure` lives on the `BootProfile` (default `"abort"`, `tap_boot/profile.py`); a failed `fire-collector` step aborts boot when `on_failure="abort"` and otherwise is collected and reported (`req-boot-population-5`). A `FireCollectorStep` carries no criticality field, so a single profile is all-or-nothing: *every* fired collector is critical, or *none* are. This is sufficient for the binary "this standup's collectors are critical" case.
- **The gap:** a profile cannot mix criticalities — e.g. "the AWS pull is critical (abort if it fails), but the GitHub pull is best-effort (continue)". The natural shape is a per-step field on `FireCollectorStep` (e.g. `critical: bool`, or a per-step `on_failure`) that **overrides** the profile-level `on_failure`; the profile default is retained when a step omits it.
- **Auth parity (the motivating rationale):** auth already has *per-provider* boot-criticality via `critical_for_boot` (`req-tap-auth-providers-6`). Collectors should reach the same granularity so the two surfaces share one mental model: each fired/configured thing declares whether its failure blocks standup or merely degrades a running instance.
- **Relationship to health / partial-instance default (cross-ref the secrets discussion):** the *default* posture agreed for collectors is **health-degrade, not boot-block** — a collector that is **not** a `fire-collector` step never runs at boot and so never blocks it; its missing-secret / upstream failure surfaces through that consumer's own health probe (the per-consumer conditional-secret-validation pattern, `spec-tap-cares-secrets` → *Shared Resolver* discussion and the auth-providers health probe) and loudly when it next runs. This requirement is only about the **opt-in** path: putting a collector in the boot profile *and* choosing whether that specific collector's failure is fatal. A collector that can't run because its secret is missing/malformed is a step failure; per-step criticality decides whether that aborts boot or degrades.
- **Deferred because** no current standup needs mixed criticality in one profile; the profile-wide `on_failure` covers today's needs. Lands when a real profile must hold both a critical and a best-effort collector.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-collector-criticality-1 | Per-Step Criticality | Proposed | A `fire-collector` step may declare its own criticality, overriding the profile-level `on_failure`. | Backlog |
| req-boot-collector-criticality-2 | Auth Parity | Proposed | Collector per-step criticality mirrors auth's per-provider `critical_for_boot` so both share one boot-criticality model. | Backlog |
| req-boot-collector-criticality-3 | Default Preserved | Proposed | A step without explicit criticality inherits the profile `on_failure` (default `abort`); a collector absent from the profile never blocks boot. | Backlog |

---

### Identity Section
----
RID: `req-boot-identity`  
Status: `Proposed`

If no keystone exists on the grid at boot, the bootloader lays down a generic instance keystone so a zero-touch standup is always self-described; it never overrides a keystone that already exists.

#### Status Details

**Backlog, not critical path.** A deliberately deferred refinement (formalized here from a shot-from-the-hip idea). In v0 the instance keystone comes from plugin GRIFT — the samsite bundle already lays down the "Samsite" keystone (`spec-grid-keystone.md`), read oldest-first as the foundational context. Boot writes no keystone in v0.

#### Implementation

- The fallback is owned by `tap_boot` (a future `identity` phase) and writes through the `tap_grid` keystone service as the `tap_bootloader` actor.
- It is **create-if-absent only**: if any keystone already exists on the grid, boot leaves it untouched (the plugin-GRIFT or operator keystone wins). Only an empty grid gets the generated keystone.
- The generic keystone is built from profile envelope metadata (a `title` + `description` describing the instance) plus the grid identity, and ships a `context_schema_json` documenting its `context_json` to satisfy the keystone self-describing contract (`req-grid-keystone-validation`). Adding that `title`/`description` to the profile envelope is part of this backlog item.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-identity-1 | Generate If Absent | Proposed | If no keystone exists at boot, a generic instance keystone is generated from profile metadata; an existing keystone is never overridden. | Backlog |
| req-boot-identity-2 | Self-Describing | Proposed | The generated keystone ships `context_json` paired with a `context_schema_json` that validates it. | Backlog |

---

### Idempotent Re-Apply
----
RID: `req-boot-idempotent`  
Status: `Implemented`

Re-applying a profile converges the instance to the declared state without duplication or error.

#### Implementation

> **v0:** relies on the underlying ops already being idempotent in practice (`sync_auth` hard-sync, `reconcile_collector_nodes`, GRIFT batch-identity dedup, collector upsert/OCC). The **formal** convergence contract + convergence tests below are deferred.

- Boot is safe to re-run, but idempotency is scoped to **declared domain state**, not operational/audit state. Re-applying the same profile converges the declared resources — no duplicated nodes/edges/actors/keystones, no hard error — but operational records *do* and *should* append: log lines, boot events, `CollectionJob`s, entity history/versions, timestamps, and any FLIP records are an append-only audit trail of each run, not domain state to converge. "Same instance state" means same *declared* state; the audit trail honestly shows that boot ran twice.
- Each section handler is responsible for its own declared-state convergence: auth capability sync is a hard-sync, initial-admin is add/update-only (`req-tap-auth-boot`), identity keystone is create-or-update (`req-boot-identity`), `seed-plugin` converges only as far as GRIFT batch identity allows (`req-boot-population`), `fire-collector` re-collection converges via the collector's own upsert/OCC behavior.
- Convergence, not blind replay: a re-apply updates changed declared resources and leaves the rest, rather than re-creating from scratch; it does not suppress the operational append trail.
- Idempotency is what makes zero-touch standup re-runnable after a partial failure: fix the cause, re-run the same profile.
- **Roll-forward recovery, never roll-back.** An aborted standup leaves a valid waypoint, not a corrupt state: a migrated-but-unpopulated database is *incomplete, not inconsistent* (empty schema satisfies every constraint; partial population is prevented by `req-boot-population-4`'s abort-before-mutation). Recovery is therefore always **fix-config-and-re-run**: `migrate` is forward-idempotent (already-applied migrations skip; the fixed re-run converges), so abort-at-any-point → re-run converges. The platform never reverse-migrates to recover — reverse migrations are lossy (industry consensus is forward-only in production; rolling back schema after data exists risks data loss). Migrations stay reversible *where it is free* (`RunPython.noop`) as dev-convenience hygiene, but recovery never *depends* on reversal. The one case roll-forward cannot cover — a migration/upgrade that succeeds but is destructive or wrong — is covered by restoring the pre-migrate snapshot (`req-boot-snapshot`), not by reversal. **No transaction is held open across `migrate` + `population`**: that is not expressible across two process steps, Postgres already gives per-migration DDL atomicity, and holding `ACCESS EXCLUSIVE` across population's collector I/O would cascade locks — best practice is short transactions, non-DB work outside them.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-idempotent-1 | Declared State Converges | Proposed | Re-applying converges declared domain state (no duplicated domain objects, no error); operational/audit records (logs, boot events, jobs, history, FLIP) may append. | |
| req-boot-idempotent-2 | Section-Owned | Proposed | Each handler owns its own declared-state convergence semantics. | |
| req-boot-idempotent-3 | Roll-Forward Recovery | Implemented | Realized by the entrypoint order: pre-boot → `migrate` → (spawn-time) `boot`; no transaction spans them, `migrate` is forward-idempotent, and nothing reverse-migrates or auto-restores. Destructive-migration recovery is the human snapshot restore. | |

---

### Config-As-Code Trust Model
----
RID: `req-boot-trust`  
Status: `Implemented`

Boot config is trusted at the same level as application code. Guards defend against malformed profiles, not against the operator.

#### Implementation

- Boot is **zero-touch and lights-out**: no interactive prompts, ever. The profile fully declares intent; the bootloader applies it without human interaction.
- Boot config is **code-level-trusted**: a privileged operator's profile may declare powerful, destructive changes (keystone overwrite, capability prune, user deactivation). The bootloader does **not** sandbox the operator's intent and makes no attempt to defend against a malicious boot config — that trust boundary is the same one we extend to module code.
- The guards that exist — full-profile validation, `--dry-run`, idempotent convergence, loud failure — are for **correctness and operability**, not security against the operator. Their job is to stop a *malformed* profile from silently bricking an unattended, zero-touch standup, not to second-guess a *well-formed* one.
- This is the boot analogue of the auth recovery-floor doctrine (`req-tap-auth-policy`): some layer is trusted-by-design so the system can be stood up and recovered; boot is that layer for instance state.
- Generating a profile (interactively or via a helper) is explicitly **out of scope and deferred** — boot only ever *applies* config-as-code. (See Backlog: profile generator.)

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-trust-1 | Zero-Touch | Proposed | Boot never prompts; it applies a declared profile without interaction. | |
| req-boot-trust-2 | Operator-Trusted | Proposed | Boot does not sandbox the operator; destructive declared changes are permitted. | |
| req-boot-trust-3 | Guards Are Anti-Footgun | Proposed | Validation/dry-run/idempotency defend against malformed profiles, not the operator. | |

---

### Secret References Only
----
RID: `req-boot-secrets`  
Status: `Implemented`

Boot profiles reference secrets; they never contain them.

#### Implementation

- Profile sections that need secrets carry **references** to keys under `TAP_SECRETS_ROOT`; the referenced secret is resolved at apply time by the owning handler.
- Secret values are never embedded in profile files and never persisted to the database (consistent with `req-tap-auth-providers` secret handling).
- A reference to a missing secret fails loud at apply (and is surfaced by `--dry-run` where the check is offline-safe).
- Boot logging redacts secret values (`req-boot-report`).
- `req-boot-required-secrets` (Proposed) layers a declared requirements *manifest* on this rule: secret **identities** may be listed up front; values still never appear.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-secrets-1 | References Only | Proposed | Profiles carry secret references under `TAP_SECRETS_ROOT`, never values. | |
| req-boot-secrets-2 | Missing Secret Fails | Proposed | An unresolved secret reference fails loud at apply. | |

---

### Required Secrets Declaration
----
RID: `req-boot-required-secrets`  
Status: `Implemented`

> **Built 2026-08-09.** Schema: `required_secrets` + fire-collector `secrets` refs in `tap_boot/schemas/boot.schema.json` (every field described). Parsing + the two coherence rules: `tap_boot/profile.py` (`RequiredSecret`, `_validate_secret_coherence` — rule A enabled-scoped so the rules compose; see the docstring). Offline check: `tap_boot/orchestrator.py:_preflight_required_secrets`, resolving through the loaded envelope registry (`tap_cares.secrets.resolve_secret`) so the check cannot drift from what boot's collectors actually resolve; blocked collectors skip their live self-test and fail with the offline reason. First declaring profile: the samsite record (since 2026-08-09 in-package at `tap_plugin/samsite/boot/samsite.boot.json` in `tap-plugin-samsite`; aws_core:boto_collector kind `aws_static_access_key` — the on-disk reality of the reference deployment, NOT `aws_assumed_role`; the note names the cross-account swap — plus github_core:collector kind `github_pat`). Profile sweep 2026-08-09: samsite is the only shipped profile firing collectors; core/core_dev/test_all/soak are seed-only, operator_sso consumes its OIDC secret via the auth section (outside this contract — see the auth-section boundary note below). Covered by `tap_boot/tests/test_profile.py` + `test_orchestrator.py`. The provisioning walkthrough consumer landed same day: `tap_boot/skills/provision-secrets/SKILL.md` (core-side by design — needed at spawn time when only core exists; plugin-shipped skills are never surfaced by wire-skills).

A boot profile declares, in one top-level list, every secret its composition requires — so "what must be provisioned before this profile can stand up" is answerable by reading the profile, from a bare clone, without booting a container or touching the network.

**The gap this closes.** The collector-readiness preflight (`req-boot-obs-preflight`) already catches a dead or absent credential in seconds, in-container, via live self-tests — but it answers *"is this credential alive?"*, not *"what must a fresh operator mint before first boot?"*. A fresh host discovers the requirements only by booting into the failure, and provisioning guidance (the get-started flow, a secrets walkthrough skill) has no machine-readable source to enumerate. The declaration is that source: the offline, host-readable half of the credential story, layered under the live self-test which stays authoritative for liveness.

```json
{
  "required_secrets": [
    { "scope": "aws_core", "key": "boto_collector", "kind": "aws_assumed_role",
      "note": "Cross-account read-only role; mandatory External ID." },
    { "scope": "github_core", "key": "collector", "kind": "github_pat",
      "note": "Fine-grained PAT, read-only, scoped to the collected org." }
  ],
  "population": {
    "steps": [
      { "type": "fire-collector", "key": "github_core:github_core",
        "secrets": ["github_core:collector"] }
    ]
  }
}
```

#### Implementation

- **Top-level manifest.** `required_secrets` entries carry exactly the envelope identity — `scope`, `key`, `kind` (`req-tap-cares-secrets-shape`) — plus a one-line least-privilege `note`. References only, never values (`req-boot-secrets`); never minting prose (the how-to-mint walkthrough lives with the kind's consumer-owned schema and the provisioning skill, `req-tap-cares-secrets-consumer-kinds`). Every schema field carries a description.
- **Bare consumption refs.** A population step that resolves a secret at run time declares it as `secrets: ["<scope>:<key>"]` — bare strings, deliberately **not** objects: the ref is the entire step-level surface, so per-collector configuration cannot creep in through this door (that is its own future need, `req-boot-collector-criticality` territory). The install section's per-source `credential` key (`req-tap-plugin-arch-source-secret-6`) remains its own pre-boot declaration and is untouched by this requirement.
- **Coherence, checked not trusted.** The dual declaration is kept honest the same way `BUILD_BAKED_PLUGIN_SLUGS` is kept honest against `INSTALLED_APPS` — by a guard, making it a checksum rather than a drift point. Two fail-loud rules under the v0 validation posture (`req-boot-validate`: shape + unknown key fails loud): a step ref with no matching entry invalidates the profile; an entry referenced by no **enabled** step invalidates it as stale.
- **Necessity follows the composition.** The effective required set is: entries referenced by at least one enabled step. Disabling a step drops its requirement (and the stale rule demands removing the orphaned entry) — no waiver mechanism, no per-secret conditional logic in the profile.
- **Preflight placement.** Presence + kind-match of the effective set is checked at the head of the population preflight (`req-boot-obs-preflight-6`) — offline, before any live self-test call, joining the same batch verdict. The abort names every missing or kind-mismatched `scope:key` with its expected kind and `note`, never a value. Absent-secret (a provisioning gap, fix = mint it) is thereby distinguished from dead-credential (a liveness gap, fix = rotate it).
- **Offline-safe by construction.** Unlike the live self-test — deliberately excluded from offline validation — this check reads only the profile and the envelope files, so it belongs to any future `--dry-run` (`req-boot-validate`) and to host-side pre-checks: spawn may verify `TAP_SECRETS_ROOT` before standing anything up, and provisioning tooling enumerates needs from a bare clone. Host-side checks are advisory; the in-container preflight is authoritative (the container's mount is what boot will actually resolve from).
- **Doctrine fit.** This is *not* the static expected-secret list `req-tap-cares-secrets-conditional-validation` forbids: the forbidden shape is TAP itself keeping a global inventory (code-level or on-grid). A profile is one operator's config-as-code (`req-boot-trust`) declaring its own composition's dependencies — the same "the declaration IS the requirement" contract as the git source `credential` key (`req-tap-plugin-arch-source-secret-5`) — with conditionality carried structurally by which steps are enabled. `tap_cares` stays necessity-agnostic; `tap_boot` owns and enforces this contract; health probes remain the runtime authority.
- **Named AI/tooling consumers** (`spec-ai-integration.md`): the spawn host-check, the secrets-provisioning walkthrough skill, and the boot preflight all read this one declaration — no parallel inventory anywhere.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-required-secrets-1 | Top-Level Declaration | Implemented | A profile may declare `required_secrets`; each entry carries envelope identity (`scope`, `key`, `kind`) plus a least-privilege `note`; references only, never values; every schema field described. | |
| req-boot-required-secrets-2 | Bare Consumption Refs | Implemented | Population steps declare consumption as bare `"scope:key"` strings under `secrets`; no step-level secret configuration beyond the ref. | Anti-creep: per-collector config stays its own surface. |
| req-boot-required-secrets-3 | Refs Resolve | Implemented | A step ref with no matching `required_secrets` entry fails profile validation loud. | |
| req-boot-required-secrets-4 | No Stale Entries | Implemented | An entry referenced by no enabled step fails profile validation loud. | Disabling a step ⇒ remove its orphaned entry. |
| req-boot-required-secrets-5 | Preflight Presence + Kind | Implemented | Before population mutates, every entry referenced by an enabled step must resolve to an on-disk envelope with matching `kind`; joins the collector preflight's batch verdict; abort names `scope:key` + expected kind, never values. | `req-boot-obs-preflight-6`. |
| req-boot-required-secrets-6 | Offline-Checkable | Implemented | The declared check needs only the profile + envelope files: usable by dry-run validation and host-side pre-checks (spawn, provisioning tooling); the in-container check stays authoritative. | |

#### Future

- **Auth-section secrets are outside this contract (named boundary).** `required_secrets` entries must be referenced by an enabled *population step* (rule B), so a secret consumed by the auth phase (e.g. `operator_sso`'s OIDC client secret) cannot be declared here without reading as stale. Auth keeps its own validation path (`critical_for_boot` + the provider health probe, `req-tap-auth-providers`); extending the declaration to auth-consumed secrets is a future decision, not an accident of omission.
- **Kind alternatives.** `kind` is single-valued, but an envelope slot may legitimately accept one of several kinds (aws_core's collector takes `aws_static_access_key` OR `aws_assumed_role`). The shipped samsite profile declares the reference deployment's actual kind and documents the swap in its `note`; if per-deployment kind-editing proves noisy, `kind` could become a one-of list — demand-gated.
- **Manifest conformance cross-check** (`req-tap-plugin-manifest-v0-secrets`, `spec-tap-plugin-manifest-v0.md`, Backlog): once plugins declare the secret kinds their collectors consume, a conformance check compares a profile's consumption refs against the union of what its enabled steps' plugins declare — catching both gaps (step needs a secret the profile never listed) and stale entries mechanically, closing the last hand-maintenance seam.
- Interplay with profile inheritance/composition (Backlog) when that lands: the coherence rules apply to the *effective* merged profile.

---

### Spawn Bridge
----
RID: `req-boot-spawn-bridge`  
Status: `Implemented`
Trace: `non-python` — scripts/spawn-session.sh

The dev spawn flow stands instances up through the bootloader, so dev and customer standup share one path.

#### Implementation

- `scripts/spawn-session.sh` invokes the bootloader (`manage.py boot --profile <id>`) instead of hand-running `import_plugin_grift`, `fire_boot_collectors`, and `createsuperuser` as separate ad hoc steps.
- The de-facto spawn ordering becomes the bootloader's declared phases; the bash script keeps only its dev-host concerns (worktree, ports, `.env.local`, secrets bind-mount, credentials file).
- The spawn-created `admin` superuser joining `tap_admin` (`req-tap-auth-local-5`) runs through the bootloader's identity/auth path, not a separate shell step.
- Migrations remain in the container entrypoint and run before the bootloader (precondition, not a boot phase).
- Dev and customer standup exercising the same bootloader is the mechanism that keeps boot dog-fooded before any customer relies on it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-spawn-bridge-1 | Spawn Calls Bootloader | Proposed | `spawn-session.sh` stands up via the bootloader, not ad hoc management commands. | |
| req-boot-spawn-bridge-2 | One Standup Path | Proposed | Dev and customer standup use the same bootloader path. | |
| req-boot-spawn-bridge-3 | Admin Bridge Through Boot | Proposed | The `admin` → `tap_admin` bridge runs through boot, not a separate shell step. | |

---

### Boot Logging
----
RID: `req-boot-report`  
Status: `Implemented`

Boot logs what it did. A durable boot-report artifact is deferred.

#### Implementation

- The bootloader logs each section/step action — added / updated / synced / fired / skipped — using the standard TAP logging conventions (`spec-tap-logging.md`, site-token discipline).
- **v0 honest scope:** the `tap_bootloader` actor is bound (`acting_as`) only around the **population** phase, so population log lines — and Flaws emitted there (`spec-tap-flaw-v0.md`) — are attributed to it without extra plumbing. The **auth/bootstrap** phase runs *before* the actor exists (v0 mints `tap_bootloader` inside `sync_auth`, the chicken-and-egg the phase order notes), so its log lines are **not** actor-attributed — there is no actor yet to attribute them to. Full-phase attribution (one actor as writer, authorization subject, and log attribution at once) is the **future** shape that arrives with the `bootstrap` pre-phase resolving the actor first (`req-boot-phases`); v0 does not and cannot claim it for auth/bootstrap logs.
- Secret values are redacted in all boot logs (`req-boot-secrets`).
- Logging is the v1 record of a boot; the durable per-run boot record is now specified as `req-boot-obs-record` (`spec-tap-boot-observability.md`, file-based v0); the grid-node/queryable representation stays backlog.
- Under failure, logs name the failed section/step and reason so an unattended caller can diagnose and re-run.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-report-1 | Actions Logged | Proposed | Each boot action is logged with the standard conventions. | |
| req-boot-report-2 | Secrets Redacted | Proposed | Boot logs never contain secret values. | |

### Standup Abort Signal
----
RID: `req-boot-abort-signal`
Status: `Implemented`

Boot standup is the **first consumer** of the app-wide `ABORT` logging signal (`req-tap-logging-abort-signal`, [spec-tap-logging.md](spec-tap-logging.md)). This requirement is that consumption, not a competing standard: the standup pipeline (`docker/entrypoint.sh` → `tap.preboot` → `migrate` → `manage.py boot`) emits an `ABORT` record on any **fatal, unrecoverable** failure, so a watcher reacts the instant it happens instead of inferring failure from an *absence* (a readiness probe that never goes green).

**As built (2026-07-03).** The Python fatal exits emit via `tap.logging.abort(logger, domain, reason)`: `tap.preboot` (`domain=preboot`, replacing the old `[8ed8]` string) and the `manage.py boot` command's `BootError`/`AuthSyncError`/profile-load handlers (`domain=boot`, replacing `[916b]`/`[f750]`). The entrypoint's bash-driven steps emit the same sentinel via an `emit_abort` shell helper on `createcachetable`/`migrate` failure (`domain=migrate`) — `migrate` being where a core→plugin-dep import leak (`req-dev-validation-lean-boot`) actually crashes, since it runs `django.setup()`. `scripts/spawn-session.sh` Step 5 tails the web log for the rendered `TAP-ABORT:` line **and** checks the container state (`exited`/`dead`/`restarting`), fast-failing on either — so a fatal standup reds in seconds with its reason instead of at the timeout. `scripts/gate-lean` inherits it (it drives the same spawn). Health failures are already fast-failed by the post-readiness Step 6.5 health gate, so they need no readiness-loop emit.

**The problem it solves.** Today a fatal standup failure is announced by inconsistent, human-only strings — `docker/entrypoint.sh` prints `FATAL: pre-boot stage failed …` to stderr, `tap.preboot` logs `[8ed8] pre-boot ABORT: …`, `tap_boot.orchestrator` logs `[ac13] boot population aborting …` — with no common signal. So `scripts/spawn-session.sh` Step 5 (and `scripts/gate-lean`) can only poll "is runserver listening?" and, when the answer is permanently *no* (the entrypoint `exit 1`'d, or `runserver` is crash-looping on a `ModuleNotFoundError`), they wait out the full **300s readiness timeout** before failing. The failure is caught (RED) but slowly — see `req-dev-validation-lean-boot` Future.

**The signal (owned by the logging spec).** Each fatal standup path emits one `ABORT` record via `tap.logging.abort(logger, domain, reason)` — `domain` ∈ `preboot | migrate | boot | health` — replacing the ad-hoc `FATAL:` / `ABORT` strings. It is a structured record (`message_code = ABORT`, `message_data = {domain, reason}`), **not** an in-band string; the `console` handler renders it as the greppable `TAP-ABORT: <domain>: <reason>` line every shell watcher already tails, and the JSON sink emits the field. The descriptive detail still logs through the normal path; the `ABORT` record is the terminal signal, once, before non-zero exit.

**Consumers.** `spawn-session.sh` Step 5 tails the web log during its readiness wait and **fast-fails** on the rendered `TAP-ABORT:` line (or on the `web` container having exited) — surfacing the reason immediately instead of at the timeout. `scripts/gate-lean` inherits that fast-fail transitively (it drives the same spawn). CI and the `/diagnose-failed-session-spawn` skill key off the same signal (`message_code == ABORT` in JSON, the sentinel in text).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-boot-abort-signal-1 | Emits the ABORT signal | Implemented | Every fatal standup failure emits one `ABORT` record (`req-tap-logging-abort-signal`) via `tap.logging.abort(...)` (Python) or `emit_abort` (entrypoint bash), before non-zero exit — not an ad-hoc string. | Replaces the `FATAL:` / `[8ed8]` / `[916b]` / `[f750]` strings with the reserved signal; the descriptive log line stays. |
| req-boot-abort-signal-2 | Readiness-phase stages covered | Implemented | The readiness-phase fatal stages — preboot, migrate (incl. createcachetable), boot — each emit it with the right `domain`. Health failures are caught by the post-readiness Step 6.5 health gate, so they need no readiness-loop emit. | The stages that would otherwise hang the readiness poll. |
| req-boot-abort-signal-3 | Watchers fast-fail | Implemented | `spawn-session.sh` (and thus `gate-lean`) abort within seconds of the rendered sentinel — or of the container exiting/restarting — not at the readiness timeout. | Closes the 300s-timeout latency in `req-dev-validation-lean-boot`. |
| req-boot-abort-signal-4 | Reason preserved | Implemented | The `reason` is surfaced in the fast-fail message and the full log context stays in `scripts/dc logs web`, not swallowed. | Feeds `spec-dev-multisession-diagnose.md`. |

---

## Suggested Implementation Sequence (v0 minimal)

All in the new `tap_boot` app; domain apps only gain/expose callable ops.

1. Create the `tap_boot` app; add it **first** in `INSTALLED_APPS`. Add `manage.py boot --profile <name> [--allow-empty]` + a small boot context (resolve `tap_bootloader`, one `acting_as` around population).
2. Profile load: `--profile` > `TAP_BOOT_PROFILE`; load `boot/<id>.json` (reuse the existing loader/shape); deploy requires a profile (`req-boot-profile`).
3. `auth` phase: call `tap_auth.sync_auth()`; resolve `tap_bootloader`; call a new `tap_auth.ensure_initial_admin()` (add/update-only, joins `tap_admin` — absorbs spawn's `createsuperuser` + group-join; `req-tap-auth-boot` step 4).
4. `population` phase (under `acting_as(tap_bootloader)`): seed plugins (the `import_plugin_grift` path), `reconcile_collector_nodes()`, then fire collectors via a new callable `fire_boot_collectors_from_profile()` extracted from the command. Unknown plugin/collector key fails loud first (`req-boot-population`).
5. Bridge `spawn-session.sh`: replace steps 5.9 / 6 / 6.1 / 6.5 + the `tap_admin` group-join with one `manage.py boot --profile "$TAP_BOOT_PROFILE"` (passing the `DJANGO_SUPERUSER_*` env it already resolves). Keep worktree / ports / `.env.local` / secrets-mount / password / `.dev-credentials`.
6. Tests + status flips: fresh-DB `boot --profile samsite` reaches the same end-state as the bash spawn; bridge runs green. Flip the v0 reqs `Proposed → Implemented`; leave `req-boot-sections` / `req-boot-validate` (OIDC-driven) and `req-boot-identity` (backlog) `Proposed`.

Deferred (build when the demand signal arrives, not before): the section-handler framework + two-layer validation (`req-boot-sections` / `req-boot-validate`, first consumer = authN Google OIDC config); the keystone fallback (`req-boot-identity`); `--dry-run`/`plan`; the formal idempotency contract; the durable boot report.

## Backlog

Deferred out of the v0 minimal path (see [v0 Scope](#v0-scope-minimal-useful)), to be built when their demand signal arrives:

- **App-registered section handlers + registry + per-section schema composition (`req-boot-sections`), two-layer validate-before-apply + `--dry-run` (`req-boot-validate`)** — first consumer is the authN Google OIDC provider configuration (`req-tap-auth-providers`); built then, so the real config defines the section/schema shape.
- **Instance keystone fallback (`req-boot-identity`)** — generate-if-absent + the profile envelope `title`/`description`; not critical path.
- **Formal idempotency convergence contract + tests (`req-boot-idempotent`)** — v0 relies on op-level idempotency.

Longer-horizon:

- Profile generator helper (CLI or otherwise) that *produces* a boot profile — authoring is separate from applying; this would be a convenience, not a requirement.
- Plugin-owned collector-firing hooks (resolve the `req-boot-population` open seam once samsite teaches us).
- Plugin dependency-graph resolution (v1 relies on declared order; a real DAG is deferred).
- **Parallel collector execution.** v0 fires `fire-collector` steps strictly serially, each awaited to terminal before the next (`req-boot-population-1`), because some collectors depend on earlier ones' grid state (samsite-compliance reads boto3's `aws_account` nodes and github_core's `github_workflow` nodes). But independent collectors — e.g. the FedRAMP KSI catalog pull — need not block the others, so a future population could run non-dependent steps concurrently (a parallel/concurrent group, or DAG-derived parallelism once dependency resolution exists) while preserving declared ordering for the dependent edges. Deferred to the "make it fast" performance phase, well after functional completeness; v0's serial-and-correct default stands until then.
- Durable, queryable boot-report **grid node/model** (v1 logs only). The file-based per-run record is now `req-boot-obs-record` (`spec-tap-boot-observability.md`); this backlog item is the grid projection of it.
- **Periodic / scheduled database snapshots** — built on the `req-boot-snapshot` callable primitive (take → verify → name in report), plus retention/rotation; runs concurrent/online against a live DB (the opposite of the serial standup snapshot). The primitive is shaped for this in the plugin refactor; the scheduler is not built then.
- **Copy-on-write volume snapshots** — the `req-boot-snapshot` scale upgrade path (ZFS/LVM/cloud-volume), if/when `pg_dump` latency or DB size demands it.
- **CLI-flag override layer** for boot variables (`req-boot-variable-resolution`) — the convention reserves `flag > env > profile > default`; the env layer is wired first (dev-disable needs it), the flag layer when a single-run override first needs one.
- Profile inheritance / composition (multiple profiles, overlays, base+override).
- Satellite / headless boot variants (where no human admin is expected; intersects `req-tap-auth-boot` relaxations).
- Standalone (non-boot-embedded) config source for sections (intersects the secondary non-boot config-source item in `spec-tap-auth-v0.md`'s Backlog).

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed | Requirement has been designed but not yet accepted for implementation. |
| Approved for Development | Requirement is accepted and ready to be implemented. |
| In Development | Actively being worked on. |
| Implemented | Has been written. |
| Verified | Has met the acceptance criteria. |
| Refactoring | In the process of being re-worked. |
| Deprecating | In the process of being deprecated. |
| Deprecated | No longer part of the current architecture. |
