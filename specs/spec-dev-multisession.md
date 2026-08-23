# Multi-Session Development Environment

## Philosophy

Multiple concurrent Claude Code sessions (CLI + VSCode extension, and eventually three or more) need to operate on the TAP codebase without colliding. Two collisions happen today: file-system races on the same working tree, and Docker collisions on shared container names, networks, volumes, and host ports. The fix is full-stack isolation per session — separate working tree, separate Docker stack, separate database — orchestrated by repeatable spawn/despawn scripts so adding a third or fourth session is a one-command operation.

The Playwright MCP server is stateless per call and remains shared across sessions.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Stack Isolation | Each session runs its own Docker Compose project with its own containers, network, volumes, and host ports. |
| 2. | Working Tree Isolation | Each session has its own checkout (git worktree) so file edits never overlap. |
| 3. | Repeatable Spawn | Adding a new session is a single command that produces a working environment seeded with current data. |
| 4. | Zero-Setup Default | The primary checkout works with `docker compose up` and no manual env configuration, preserving today's developer experience. |
| 5. | Demand-Driven Allocation | Sessions get a port band the first time they're spawned, recorded in a per-machine registry. The primary's reservation (8000/5432) is fixed; everything else is allocated on demand. Ephemeral by default — despawn frees the band. |
| 6. | Runtime Environment Isolation | The Linux container's Python virtualenv is isolated from any host-side Python virtualenv so host tools and container tools never rewrite each other's interpreter links. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-dev-multisession-compose-parameterized | [Parameterized Compose Stack](#parameterized-compose-stack) | Implemented | Phase 1 |
| req-dev-multisession-env-cascade | [Env File Cascade](#env-file-cascade) | Implemented | Phase 1 |
| req-dev-multisession-port-registry | [Per-Machine Session Registry](#per-machine-session-registry) | Implemented | Phase 1 |
| req-dev-multisession-browser-disambiguation | [Browser Disambiguation](#browser-disambiguation) | Implemented | Phase 1 |
| req-dev-multisession-spawn-script | [Spawn Script](#spawn-script) | Implemented | Phase 2; interactive. The SINGLE entry point: first boot on a fresh machine and the Nth session are the same command (stand-up.sh retired 2026-08-09) |
| req-dev-multisession-host-readiness | [Host Readiness Battery](#host-readiness-battery) | Implemented | Spawn Step 0.1: toolchain checks + the `~/tap-sessions/main` layout seatbelt, absorbed from the retired stand-up.sh; runs on every spawn |
| req-dev-multisession-admin-bootstrap | [Admin User Bootstrap](#admin-user-bootstrap) | Implemented | Phase 2, sub-feature of spawn |
| req-dev-multisession-spawn-import-strict | [Granular Grift Import Failure Mode](#granular-grift-import-failure-mode) | Backlog | Phase 3 polish on top of fail-fast |
| req-dev-multisession-push-workflow | [Session → Main Push Workflow](#session-→-main-push-workflow) | Implemented | Always-on discipline; codifies how session worktrees advance origin/main and keep the local main worktree current |
| req-dev-multisession-promote-script | [Promote-to-Main Script](#promote-to-main-script) | Implemented | Per-session wrapper around the push-workflow discipline |
| req-dev-multisession-promote-all-script | [Promote-All-Sessions Script](#promote-all-sessions-script) | Implemented | Registry-driven orchestrator over the per-session script |
| req-dev-multisession-promote-gate | [Promote-Path Validation Gate](#promote-path-validation-gate) | Implemented | Promote path runs the dev-validation gate (`scripts/gate`) and refuses to advance origin/main on red; reciprocal of req-dev-validation-promote-hook |
| req-dev-multisession-ci-gate | [All-Plugins CI Gate](#all-plugins-ci-gate) | Implemented | Promote also triggers + blocks on the server-side all-plugins CI lane (option B: trigger + poll, keeps the atomic push); reciprocal of req-dev-validation-all-plugins-lane. Bootstrap-skips until the workflow is on main |
| req-dev-multisession-list-script | [List Script](#list-script) | Proposed | Phase 3 |
| req-dev-multisession-named-routing | [Name-Based Routing via Reverse Proxy](#name-based-routing-via-reverse-proxy) | Backlog | Phase 3 polish |

Teardown is tracked separately in [spec-dev-multisession-teardown.md](spec-dev-multisession-teardown.md). Smoke tests live in [spec-dev-multisession-smoketest.md](spec-dev-multisession-smoketest.md). Diagnosing a spawn that fails to stand up — the *why* behind the spawn script's recovery-command trap (`req-dev-multisession-spawn-script-4`) — is standardized in [spec-dev-multisession-diagnose.md](spec-dev-multisession-diagnose.md) (the `/diagnose-failed-session-spawn` skill). First-boot collector firing — the spawn step that fires collectors to populate collected data after seeding — is specified in [spec-dev-boot-collectors.md](spec-dev-boot-collectors.md) (`req-dev-boot-collectors-spawn-integration`).

### Parameterized Compose Stack
----
RID: `req-dev-multisession-compose-parameterized`
Status: `Implemented`
Trace: `non-python` — docker-compose.yml

`docker-compose.yml` MUST read `COMPOSE_PROJECT_NAME` and host port mappings from environment variables, with sensible defaults preserving the current `tap` / `8000` / `5432` behavior. Variables to parameterize:

- `COMPOSE_PROJECT_NAME` — namespace for containers, networks, volumes (Compose reads this natively).
- `WEB_PORT` — host port mapped to Django container `8000`. Default `8000`.
- `POSTGRES_PORT` — host port mapped to Postgres container `5432`. Default `5432`.
- `TAP_GRID_ID` — installation identity. Default the current hardcoded UUID; spawn script (Phase 2) generates a new one per session.
- `TAP_PRODUCT_NAME` — product name shown in the UI title bar, header, and `<title>` element. Default `"TAP"`. Set per-session in `.env.local` (e.g. `RAMPART`) for branded demo instances; the value is read by `tap_web/context_processors.py` and exposed to every template as `{{ product_name }}`.

#### Implementation
- `docker-compose.yml` uses `${VAR:-default}` substitution syntax so the file remains valid with no `.env` present.
- A checked-in `.env` carries the defaults so `docker compose up` works out of the box in the primary checkout.
- Container-internal ports (`8000`, `5432`) stay fixed; only host-side mappings move.
- **The container virtualenv lives in a per-project named volume** (`venv:/app/.venv`) mounted over the worktree's `.venv` path. This is a deliberate host/container isolation choice: macOS host tools and the Linux container cannot safely share one Python virtualenv because interpreter paths, scripts, and binary wheels are platform-specific. The container owns `/app/.venv`; host-side tools that need Python should use a separate environment such as `.venv-host` via `UV_PROJECT_ENVIRONMENT=.venv-host`.
- **uv cache lives in a per-project named volume** (`uv_cache:/root/.cache/uv`). Per-project named volumes mean (a) cache corruption can't leak between sessions and (b) `dc down -v` (already part of despawn) clears it. The published image ships a pre-compiled wheel cache at `/opt/uv-cache-seed` (Dockerfile `deps-warm` stage) that the entrypoint copies into an EMPTY cache volume on first boot — distinct from the 2026-04-27 fossilization problem (incrementally-accreted cache state trapped in local Docker build layers and replayed across rebuilds): the seed is rebuilt from scratch by `uv sync --frozen` in a clean stage keyed on `pyproject.toml`+`uv.lock` whenever the lock changes, and an existing volume is never touched.
- **Dependency sync runs in the entrypoint, not the Dockerfile.** Both `/app/.venv` and `/root/.cache/uv` are runtime named volumes that hide image content at their mount paths, so the venv the containers actually use is always created by `docker/entrypoint.sh`'s `uv sync` on first container start (normally in seconds, from the seeded wheel cache); subsequent starts are near-instant no-ops because the venv and cache persist in their respective mounts. The `deps-warm` build-time sync exists only to produce the wheel-cache seed at a non-mounted path — its venv is discarded, deliberately: a cp-seeded venv proved uv-hostile on the CI runner (2026-08-09), while a sync-created one is the long-proven path.

#### Future
If we add Redis, mailcatcher, or other host-exposed services, follow the same pattern: add `<SERVICE>_PORT` variable with a default, allocate it a fixed offset in the port registry.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-compose-parameterized-1 | Default behavior unchanged | Proposed | `docker compose up` from a fresh clone with the checked-in `.env` produces containers named `tap-web-1` / `tap-db-1` listening on host `8000` / `5432`. | |
| req-dev-multisession-compose-parameterized-2 | Override applied | Proposed | Setting `COMPOSE_PROJECT_NAME=tap_cli WEB_PORT=8001 POSTGRES_PORT=5433` and running compose produces containers in the `tap_cli` project listening on host `8001` / `5433`. | |
| req-dev-multisession-compose-parameterized-3 | Two stacks coexist | Proposed | Two checkouts running compose with different namespaces produce two simultaneously-running, non-conflicting Docker stacks. | |
| req-dev-multisession-compose-parameterized-4 | uv cache is a per-project named volume | Proposed | The web service mounts `uv_cache:/root/.cache/uv`. Each compose project gets its own volume; cache corruption is per-session and cleared by `dc down -v`. | |
| req-dev-multisession-compose-parameterized-5 | Dependency sync at entrypoint | Proposed | `uv sync` runs from `docker/entrypoint.sh`, not the Dockerfile, so the install lands in the container venv and uv cache named volumes rather than in image layers. | |
| req-dev-multisession-compose-parameterized-6 | Container venv is a named volume | Proposed | The web service mounts `venv:/app/.venv` so container-side `uv sync` never writes the host worktree's `.venv` directory. | Prevents host/container virtualenv path and binary-wheel collisions. |
| req-dev-multisession-compose-parameterized-7 | Host Python uses a separate env | Proposed | Documentation and scripts treat `/app/.venv` as container-owned; any host-side Python workflow uses a distinct env path such as `.venv-host`. | Avoids two OSes mutating one virtualenv. |

### Env File Cascade
----
RID: `req-dev-multisession-env-cascade`
Status: `Implemented`
Trace: `non-python` — scripts/dc

A small `scripts/dc` wrapper invokes Docker Compose with `--env-file .env --env-file .env.local` (the latter included only when present), so `.env` provides defaults and `.env.local` overrides them per worktree. Direct `docker compose` invocations still work using only `.env`.

#### Implementation
- `.env` is **checked in** with defaults (`COMPOSE_PROJECT_NAME`, `WEB_PORT`, `POSTGRES_PORT`, `TAP_GRID_ID`).
- `.env.local` is **gitignored** (`.gitignore` updated accordingly).
- `scripts/dc` is a thin shell script: cascades env files and forwards arguments to `docker compose`.
- Documented usage: `scripts/dc up`, `scripts/dc exec web ...`, etc. — drop-in for `docker compose`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-env-cascade-1 | Wrapper cascades env files | Proposed | `scripts/dc config` resolves variables from `.env.local` when present, falling back to `.env`. | |
| req-dev-multisession-env-cascade-2 | `.env.local` not tracked | Proposed | `git status` is clean after creating a `.env.local` file. | |

### Per-Machine Session Registry
----
RID: `req-dev-multisession-port-registry`
Status: `Implemented`
Trace: `non-python` — scripts/spawn-session.sh

Sessions are allocated port bands on demand at spawn time and recorded in a per-machine registry at `~/tap-sessions/.registry`. The primary stack's reservation is fixed; session names are otherwise arbitrary and chosen by the developer.

#### Reserved

| Name | COMPOSE_PROJECT_NAME | WEB_PORT | POSTGRES_PORT |
| --- | --- | --- | --- |
| (default — primary stack) | tap | 8000 | 5432 |

#### Allocation algorithm

For session band `N` (1 ≤ N ≤ 50): `WEB_PORT = 8000 + 10N`, `POSTGRES_PORT = 5432 + 10N`. So band 1 = 8010 / 5442, band 2 = 8020 / 5452, etc.

On `scripts/spawn-session.sh`, the script:
1. Reads the registry.
2. Rejects the chosen name if it already has a row.
3. Walks bands 1..50 and picks the smallest one whose ports are not already in any registry row.
4. After a successful spawn, appends the new row to the registry.

The 10-port spacing per band leaves headroom for additional host-exposed services (Redis, mailcatcher, debugger) within a session without renumbering.

The cap (50) exists to fail loudly rather than allocate into someone else's well-known port range. If you genuinely need more concurrent sessions than that, you have bigger problems than a script error.

#### Format

Line-delimited, single-space-separated columns: `name web db branch spawned`. Comment lines start with `#`. Example:

```
# name web db branch spawned
cli 8010 5442 session/cli 2026-04-27T15:00:00Z
vscode 8020 5452 session/vscode 2026-04-27T15:30:00Z
```

#### Ephemeral by default

Despawn removes the row, freeing the band for reuse. Re-spawning the same name later may or may not return the same band depending on what else has been spawned since. If sticky-band behavior is wanted, a future `--retain` flag on despawn could preserve the row while removing everything else.

#### Concurrency

Two simultaneous spawns could race and pick the same band. This is genuinely rare in practice and not worth a `flock` (which isn't in macOS's base system anyway). If it becomes a real problem we'll add a lock-directory pattern (`mkdir`-based, portable).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-port-registry-1 | Registry is canonical for live sessions | Proposed | Every active session has exactly one row in `~/tap-sessions/.registry`; despawn removes it. | |
| req-dev-multisession-port-registry-2 | Allocation finds smallest free band | Proposed | Spawn picks the lowest-numbered free band, not a random one. | |
| req-dev-multisession-port-registry-3 | Cap enforced | Proposed | Spawn fails with a clear error when all 50 bands are occupied. | |

### Browser Disambiguation
----
RID: `req-dev-multisession-browser-disambiguation`
Status: `Implemented`

Two zero-infra mechanisms let the developer tell at a glance which session a browser tab points at:

1. **`*.localhost` URL convention.** Modern browsers resolve any `*.localhost` subdomain to `127.0.0.1` natively per RFC 6761 — no `/etc/hosts` edits, no DNS server. Each session is reachable at `http://<name>.tap.localhost:<WEB_PORT>/` (e.g. `http://cli.tap.localhost:8010/`). The hostname is purely a label in the URL bar; the port still does the actual routing. Django's `ALLOWED_HOSTS` includes `.localhost` (leading-dot wildcard) so subdomain access is permitted without per-session config.

2. **`TAP_SESSION_LABEL` env var rendered in the UI.** When set (typically to the same name as the session, e.g. `cli`), the value renders as a `[label]` prefix in the `<title>` (browser tab) and as a colored badge next to the product name in the nav bar. Empty for the primary stack so default behavior is unchanged.

The two mechanisms are independent and complementary — the URL labels the address bar, the badge labels the page chrome. Together they make tab-switching unambiguous without any new infrastructure.

**The labeled URL is a label, not a sign-in origin.** Passkey login works only at the direct `http://localhost:<WEB_PORT>/` origin: browsers refuse RP-ID `localhost` from a `*.localhost` subdomain with a pre-prompt `SecurityError`, and the ceremony origin is pinned exactly on the server side regardless (req-tap-auth-passkey-webauthn-7). The labeled hostname is also a separate cookie realm — a session established on one origin does not carry to the other. Spawn's output and `/launch-ui` therefore lead with (and open) the direct URL, and the login page itself signposts the way out when reached on a refused origin (req-tap-auth-passkey-rollout-6).

#### Implementation
- `tap/settings.py`: `ALLOWED_HOSTS` default extended to include `.localhost`. New `TAP_SESSION_LABEL` setting reads `TAP_SESSION_LABEL` env var (empty default).
- `tap_web/context_processors.py`: `branding` exposes `session_label` to all templates.
- `tap_web/templates/tap_web/base.html`: title prefix `[label] ` (outside the `{% block title %}` so it applies to all child templates) and a small amber badge in the nav.
- `docker-compose.yml`: `ALLOWED_HOSTS` default updated; `TAP_SESSION_LABEL` passed through with `${TAP_SESSION_LABEL:-}`.
- Per-session `.env.local` (set during onboarding): `TAP_SESSION_LABEL=<name>`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-browser-disambiguation-1 | Subdomain access works | Proposed | `http://cli.tap.localhost:8010/` reaches the session's Django when `ALLOWED_HOSTS` includes `.localhost`. | |
| req-dev-multisession-browser-disambiguation-2 | Title shows label | Proposed | When `TAP_SESSION_LABEL=cli`, the page `<title>` is prefixed with `[cli]`. | |
| req-dev-multisession-browser-disambiguation-3 | Nav shows badge | Proposed | When `TAP_SESSION_LABEL=cli`, the nav bar shows a `cli` badge next to the product name. | |
| req-dev-multisession-browser-disambiguation-4 | Primary stack unchanged | Proposed | With no `TAP_SESSION_LABEL` set, no prefix or badge appears — primary UI is unchanged. | |

### Spawn Script
----
RID: `req-dev-multisession-spawn-script`
Status: `Implemented`
Trace: `non-python` — scripts/spawn-session.sh

`scripts/spawn-session.sh` provisions a new isolated environment interactively — and it is the **single entry point**: first boot on a fresh machine and the Nth concurrent session are the same command (the separate `scripts/stand-up.sh` adopter path was retired 2026-08-09; its host checks became Step 0.1, [Host Readiness Battery](#host-readiness-battery), and its conversational driver became the `get-started` skill). The script prompts only for decisions the developer must make (Keychain setup if missing, session name) and runs everything else automatically:

1. **Step 0.1 — Host readiness.** The toolchain/layout battery ([req-dev-multisession-host-readiness](#host-readiness-battery)); also detects a first spawn (no registry yet) to set honest expectations: the one-time published-image download is the long-ish step, and only the offline/unpublished local-build fallback compiles FIPS OpenSSL from source (10–20 minutes).
2. **Step 0 — Keychain check.** If `tap-dev-default` is missing, offers to set it. macOS-only; non-Darwin platforms skip this step and fall back to env var or random per session.
3. **Step 1 — Session name and band allocation.** Displays the current live sessions from `~/tap-sessions/.registry` (initializing the file with a header on first use). Prompts for a name; validates against `^[a-z][a-z0-9_-]*$` and rejects `default` (reserved for the primary stack). Rejects names already in the registry. Allocates the smallest free band (per [Per-Machine Session Registry](#per-machine-session-registry)) and computes web/db ports. Also runs the stale-Docker pre-check so leftover state from a prior failed spawn aborts cleanly with a "remove this first" message.
4. **Step 1.5 — Refresh local main.** `git -C ~/tap-sessions/main pull --ff-only origin main`, so the new session branches from current code (see [Session → Main Push Workflow](#session-→-main-push-workflow)). The layout seatbelt in Step 0.1 guarantees the main worktree location.
5. **Step 2 — Worktree.** Creates the worktree at `~/tap-sessions/<name>` (or `$WORKTREE_BASE/<name>` for throwaway consumers) on a new branch `session/<name>` from `main`. Aborts if the worktree path already exists. Initializes the captured standup transcript at `logs/spawn.log` (`req-boot-obs-spawn-presentation`).
6. **Step 3 / 3.5 / 3.6 — `.env.local`, secrets mount, skills.** Generates a fresh `TAP_GRID_ID`; writes `COMPOSE_PROJECT_NAME`, `WEB_PORT`, `POSTGRES_PORT`, `TAP_GRID_ID`, `TAP_SESSION_LABEL`, `TAP_BOOT_PROFILE`; provisions the `tap_secrets/` bind-mount target (shared `~/tap-secrets` symlink when present); wires `.claude/skills/` via `scripts/wire-skills.sh`.
7. **Step 4 — Pull + start.** Pull-first: `scripts/dc pull web db` fetches the published GHCR images (toolchain + FIPS OpenSSL + pre-compiled wheel cache baked in; `spec-cicd-hardening.md` build-once artifact), falling back loudly to an EXPLICIT local build when the pull fails (`scripts/dc build web db` via the docker-compose.build.yml overlay; offline/unpublished — the 10–20-minute from-source path); then `scripts/dc up -d`. The base compose file itself is pull-only: `up` hard-fails on a missing pinned tag rather than silently building (see `req-cicd-product-releases-3`). Both quiet-captured with a live elapsed counter.
8. **Step 5 — Entrypoint wait.** Polls readiness; fast-fails on the `TAP-ABORT` signal or a dead container (`req-boot-abort-signal`). Hang detection is **stall-aware**: the primary trigger is no-new-web-log-output for 120s (a healthy entrypoint streams continuously; wall-clock cannot distinguish slow from stuck), with a path-conditional wall-clock ceiling as the outer bound (600s after a successful image pull, 900s on the local-build fallback).
9. **Step 6 / 6.4 / 6.5 — Boot, passkey, health.** Resolves the admin password ([req-dev-multisession-admin-bootstrap](#admin-user-bootstrap)), writes `.dev-credentials`, runs `manage.py boot --profile <id>` (`req-boot-spawn-bridge`; boot's own observability is `spec-tap-boot-observability.md`), bootstraps the dev passkey, then gates on `manage.py health --set readiness`.
10. **Done.** Appends the registry row and prints labeled URL, direct URL, admin URL, admin credentials, credentials-file path, transcript location, and how to attach Claude Code. With the `cli` launch target, the access block is additionally persisted to `logs/session-info.txt` and — on a real terminal only (`[[ -t 0 ]]`; scripted invocations can never hang here) — the script pauses for Enter before `exec claude` takes over the terminal, so the info doesn't scroll away unrecoverably; the pause message points at `/launch-ui` (the skill that reopens the web UI from inside the session).

The script wires a failure trap that, on any non-zero exit, prints recovery commands for the partial state (despawn + worktree-remove + branch-delete). This isolates the developer from "where did spawn fail and what do I do now" guesswork. That trap covers the *recovery*; the *root-cause read* ("why did it fail") is standardized separately in [spec-dev-multisession-diagnose.md](spec-dev-multisession-diagnose.md).

Worktrees live **outside** the repo at `~/tap-sessions/<name>` to keep the main tree uncluttered.

#### Future

A `--non-interactive` mode (taking `--name`, `--admin-password` flags) would make the script CI-friendly. Not v1. Auto-allocation of new port bands (when "make it fast" mode lands) would skip the registry-edit-first requirement for ad-hoc names.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-spawn-script-1 | Single-command spawn | Proposed | `scripts/spawn-session.sh` produces a running, seeded stack with admin user at the registered port band. | |
| req-dev-multisession-spawn-script-2 | Idempotent failure | Proposed | Re-running spawn for a session with an existing worktree aborts before any mutation. | |
| req-dev-multisession-spawn-script-3 | Registry collision rejection | Proposed | Names already present in `~/tap-sessions/.registry` are rejected with a clear error pointing at despawn. | |
| req-dev-multisession-spawn-script-4 | Failure trap recovery | Proposed | On non-zero exit during spawn, the script prints recovery commands for the partial state. | |

### Host Readiness Battery
----
RID: `req-dev-multisession-host-readiness`
Status: `Implemented`
Trace: `non-python` — scripts/spawn-session.sh

Spawn's Step 0.1 verifies, on **every** run, that the host can actually carry a spawn — the first-run gate for a fresh machine and the every-run seatbelt against drift. Absorbed from the retired `scripts/stand-up.sh` so there is exactly one entry point and one implementation of the checks (the copy-drift between the two scripts — stand-up had silently lost the health gate — is the motivating scar).

#### Implementation

- **Toolchain (fail with the fix):** `git`, `python3`, `docker` on PATH; Compose v2 present (the retired v1 binary is named as unsupported); `lsof` (the port-band probe reads nothing without it and would silently allocate a busy band — fail-loud belongs up front); daemon responsiveness within a bounded probe, with **distinct** messages for not-installed, not-running, and the Linux permission/docker-group case.
- **Layout seatbelt:** the primary clone must live at `~/tap-sessions/main`. Derived from git itself (`git worktree list --porcelain`, first entry — correct no matter which session worktree invoked spawn), compared physically (`pwd -P`) so symlinked homes don't false-positive. The failure message carries both repair paths: fresh re-clone into place, or `mv` an existing clone (git is location-independent). **Skipped when `WORKTREE_BASE` is overridden** — throwaway consumers (`scripts/gate-lean`) are not part of the durable layout.
- **First-spawn detection:** no `~/tap-sessions/.registry` yet ⇒ first run on this host; used only for honest messaging (the one-time published-image download, and the 10–20-minute from-source FIPS build that only the offline/unpublished fallback takes — `spec-cicd-hardening.md` build-once artifact).
- **Soft checks (warn, never block):** unset git identity (commits would carry an auto-derived name/email).
- Nothing in the battery mutates the host; it is read-only and idempotent by construction.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-host-readiness-1 | Toolchain Named Fixes | Implemented | Missing docker / compose v2 / lsof / python3 fail with the platform-specific install fix; daemon not-running vs permission-denied get distinct messages. | |
| req-dev-multisession-host-readiness-2 | Layout Seatbelt | Implemented | A primary clone not at `~/tap-sessions/main` fails with both repair paths (re-clone vs `mv`); derived via git, compared physically; correct when invoked from a session worktree. | |
| req-dev-multisession-host-readiness-3 | Throwaway Exemption | Implemented | The layout check is skipped when `WORKTREE_BASE` is overridden; toolchain checks still run. | gate-lean |
| req-dev-multisession-host-readiness-4 | Read-Only Battery | Implemented | The battery mutates nothing; soft checks warn without blocking. | |

### Granular Grift Import Failure Mode
----
RID: `req-dev-multisession-spawn-import-strict`
Status: `Backlog`

Today, step 6 of the spawn script (`import_plugin_grift --all`) is fail-fast: any bundle failing validation raises `CommandError` and aborts the spawn so the developer doesn't end up in a session with borked data. That's the right default but it has one obvious downside — a single bad bundle aborts the whole spawn, even when nineteen others would have imported fine.

This requirement adds an opt-in continue-on-error mode so developers iterating on a single plugin can still get a session up:

- `--strict` (default for spawn): exit non-zero on the first failed bundle and abort. Matches today's behavior.
- `--continue-on-error`: import every bundle the validator accepts, log each failure inline, and exit non-zero at the end with a one-line summary of what failed. Spawn does **not** use this mode by default — it's invoked manually after spawn (`scripts/dc exec web uv run python manage.py import_plugin_grift --all --continue-on-error`) when the developer wants a partial seed for plugin development.

The motivating event: 2026-05-06, a `genericom/ec2-internals.grift.json` bundle failed `envelope_payload_name_mismatch` validation; spawn step 6 wrote a red error line but exited 0, and the session looked "ready" with silently-missing data. Layer 1 of the fix — a spawn-script acceptance criterion since folded into this requirement (`req-dev-multisession-spawn-import-strict-1` below) — made the import command exit non-zero. This requirement is the optional layer 2.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-spawn-import-strict-1 | Strict-by-default | Backlog | `import_plugin_grift` exits non-zero on first failed bundle when `--continue-on-error` is not passed. | Already implemented as part of the layer-1 spawn-script fix (a former spawn-script ACID, retired into this requirement). |
| req-dev-multisession-spawn-import-strict-2 | Continue-on-error flag | Backlog | `--continue-on-error` causes the command to attempt every bundle and exit non-zero at the end with a per-bundle summary. | |
| req-dev-multisession-spawn-import-strict-3 | Spawn defaults to strict | Backlog | `scripts/spawn-session.sh` invokes import without `--continue-on-error`, so a bad bundle aborts the spawn and fires the failure trap. | |

### Session → Main Push Workflow
----
RID: `req-dev-multisession-push-workflow`
Status: `Implemented`
Trace: `process` — the branch-and-promote discipline developers follow; scripts automate steps, the rule is the requirement

Multi-worktree development needs an unambiguous rule for how changes leave a session and become part of `main`. Without it, parallel sessions race each other on `origin/main`, new session spawns start from stale code, and the discipline becomes "whatever the current developer remembers." This requirement codifies the rule so every session — human or agent — follows the same four-step pattern.

**AI-review triage (2026-08-20).** The `copilot-review-floor` org ruleset auto-reviews every
PR ~1–3 minutes after it opens (re-reviewing on each push, Comment-state only) — but a
fast-lane PR auto-merges on gate-green ~10 minutes later with nobody having read the
feedback. So: **whoever opens a PR reads its reviewer feedback before calling the work
done** — `scripts/pr-review-triage <pr> [--wait]` prints the review bodies (INCLUDING the
suppressed findings Copilot collapses into a `<details>` block — real catches hide there)
plus all inline comments. Fix-worthy findings are pushed onto the PR branch (re-arming
auto-merge against the new commit); noise is dismissed consciously, never silently. This is
advisory triage, not a gate — the blocking lever (require-conversation-resolution) is
deliberately held until the reviewer's precision is proven (see the ensemble spec/plan).

#### The discipline

1. **Never edit `main` directly.** All work happens on a `session/<name>` branch inside a session worktree under `~/tap-sessions/<name>/`. The primary worktree at `~/tap-sessions/main/` is a passive reflection of `origin/main`; its working tree should never have uncommitted changes. Following this rule alone makes everything below succeed by default.
2. **Pre-push merge.** Before pushing to advance `main`, the session worktree must catch up to whatever sibling sessions have already landed:

   ```
   git fetch origin main
   git merge origin/main
   ```

   Resolve any conflicts on the session branch, commit, then continue. Skipping this step risks a non-fast-forward rejection at push time or, worse, silent overwrite of another session's work if anyone ever uses `--force`.
3. **Push.** Advance `origin/main` AND the session branch on origin in one atomic operation, using `--atomic` with multiple refspecs:

   ```
   git push --atomic origin session/<name>:main session/<name>:session/<name>
   ```

   Each refspec is `<local>:<remote>`. The first advances `origin/main` from the session tip; the second advances (or creates) `origin/session/<name>`. The `--atomic` flag is REQUIRED: without it, git transmits both refspecs but the server is free to apply them independently — so a non-fast-forward on `:main` would still leave the session-branch update applied (or vice versa). With `--atomic`, either both refs advance or neither does. There is no separate "merge into main" commit. A single `:main` push by itself does NOT preserve the session branch on origin; the `session/<name>:session/<name>` refspec must be present.
4. **Sync the primary worktree.** Immediately after the push, advance the local `main` ref in the primary worktree so it matches `origin/main`:

   ```
   git -C /Users/george/tap-sessions/main pull --ff-only
   ```

   This step is load-bearing: `scripts/spawn-session.sh` runs `git worktree add <path> -b session/<name> main` to branch the new session from the local `main` ref. If that ref is stale, every newly-spawned session starts from old code. The post-push pull keeps it current. (The spawn script also runs its own `pull --ff-only` against `main` at Step 1.5 as a belt-and-suspenders guard — see `req-dev-multisession-push-workflow-6`.)

#### The second road: a gated PR (bot-adjacent changes)

Since the `main-required-checks` ruleset (2026-08-09), the promote is no longer the only
sanctioned road to `main` — **a PR whose `gate` check is green is equally valid**, and for
one class of change it is strictly better: a change whose only consumer is a **pending bot
PR** (a Renovate policy/config/bound edit, a baseline update for a dependency bump). Pushing
that change onto the bot's own branch bundles policy + payload into ONE gate pass (~10 min)
instead of three serialized ones (promote the policy ~12 min → bot re-dispatch → rebased-PR
gate ~10 min ≈ 25 min — measured the hard way, mypy bound saga, 2026-08-09). Renovate stops
auto-rebasing an edited branch, which is fine when the edit's author intends to merge it.
Decision rule: *session work → promote; a change consumed by a pending gated PR → bundle
into that PR's branch.* After the PR merges, sibling session branches pick it up via the
normal pre-push merge.

#### The everyday docs road: the tier-gated PR (2026-08-10)

Documentation-only changes previously rode a **human-authorized direct FF push** to `main`
(the "docs-only bypass" — judgment plus the ruleset's admin bypass, loud but undesigned).
That practice is **retired as the everyday path**: since change-tier gating
(`req-dev-validation-product-line-lanes-7`, `scripts/change-tier`), the PR road itself is
cheap for inert diffs — a **docs-tier** PR (docs/, plan/, root `*.md`, LICENSE/NOTICE)
gates in ~1 minute (setup + secret-scan + dco; no lanes, no boot gates), and a
**specs-tier** PR adds only the `test_all` lane (spec markdown is parsed by tests — Map
sync, RID resolution — but cannot affect boot). Same PR flow, same single required `gate`
check, no bypass. The direct atomic push remains **bootstrap/skip-hatch only**
(`req-dev-multisession-push-workflow-3`). Decision rule stays simple: *every change rides
a PR; the tier decides how much battery the PR burns.*

#### Why the naive form does not work

The intuitive command for step 4 is `git fetch origin main:main` from inside the session worktree. Git rejects it:

```
fatal: refusing to fetch into branch 'refs/heads/main' checked out at '/Users/george/tap-sessions/main'
```

A branch ref cannot be advanced from outside the worktree that has it checked out — git enforces this to prevent the working tree and the ref from desynchronizing. The fetch-and-fast-forward has to happen *inside* the main worktree, which is exactly what `git -C /path/to/main pull --ff-only` does without requiring a `cd`.

If `pull --ff-only` ever fails with "not a fast-forward", it means a sibling worktree pushed to main between this session's pre-push merge and this push. Surface the error, re-merge `origin/main` into the session branch, and re-run the push + post-push pull.

#### What a partial workaround looks like

`git fetch origin main` (no refspec) updates only the remote-tracking branch `origin/main`. It avoids the "refusing to fetch into checked-out branch" error but does **not** advance local `main`. It's a safe fallback that keeps `origin/main` current for the *next* session's pre-push merge, but it leaves the spawn-session staleness problem unsolved. Use only when `pull --ff-only` itself fails (e.g. someone forgot the "never edit on main" rule and left uncommitted changes); fix the underlying issue rather than relying on this fallback.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-push-workflow-1 | Never edit on main | Implemented | The primary worktree at `~/tap-sessions/main/` MUST NOT carry uncommitted changes or local commits that haven't traveled through a session branch. All edits live on `session/<name>` branches. | |
| req-dev-multisession-push-workflow-2 | Pre-push merge required | Implemented | Before advancing `origin/main`, the session branch MUST be fast-forwardable to its target by merging `origin/main` first. | Prevents non-fast-forward push rejections and overwrites. |
| req-dev-multisession-push-workflow-3 | Atomic combined-refspec push (fallback path) | Implemented | The push command is `git push --atomic origin session/<name>:main session/<name>:session/<name>` — two refspecs on one push, with `--atomic` so `origin/main` and `origin/session/<name>` advance all-or-nothing. WITHOUT `--atomic`, git transmits both refspecs but the server may apply them independently — a non-fast-forward on one ref would still leave the other update applied. WITH `--atomic`, either both refs advance or neither does. A single `:main` refspec advances only `origin/main` and does NOT preserve the session branch on origin; the second refspec is required. | No separate merge commit; no checkout of `main`. SINCE 2026-08-10 this is the BOOTSTRAP/SKIP-HATCH path only: the default road to main is the PR flow (promote-script-4a) — the server merges on green required checks, and `origin/session/<name>` is pushed as the PR head. |
| req-dev-multisession-push-workflow-4 | Post-push primary sync | Implemented | After the push, the local `main` ref MUST be advanced via `git -C /Users/george/tap-sessions/main pull --ff-only`. | Load-bearing for `scripts/spawn-session.sh` correctness. |
| req-dev-multisession-push-workflow-5 | Naive fetch form is wrong | Implemented | `git fetch origin main:main` from a session worktree is explicitly NOT the post-push sync. Git refuses to fast-forward a ref that's checked out elsewhere; the operation must run inside the main worktree (via `git -C`). | Documented so agents don't reinvent the workaround. |
| req-dev-multisession-push-workflow-6 | Spawn-side guard | Implemented | `scripts/spawn-session.sh` refreshes local `main` from `origin/main` BEFORE creating the new session worktree. The pull MUST run inside the main worktree (via `git -C "$HOME/tap-sessions/main" pull --ff-only origin main`), not via `$REPO` — `$REPO` is wherever the script was invoked from (possibly a session worktree), and pulling there would advance the session branch rather than main. A non-fast-forward (uncommitted changes on main, divergent local main) aborts the spawn loudly rather than silently starting a session from stale code. If the main worktree is missing at `$HOME/tap-sessions/main` (non-standard layout), the guard warns and skips rather than aborting. | Belt-and-suspenders with the post-push sync: that keeps siblings current between spawns; this guard ensures the *next* spawn is current even if the discipline slipped. |
| req-dev-multisession-push-workflow-7 | Docs ride the tier-gated PR, not the bypass | Implemented | Documentation/spec-only changes advance `origin/main` through the normal PR road; the change tier (`scripts/change-tier`, reciprocal `req-dev-validation-product-line-lanes-7`) makes that road cheap (docs ≈ 1 min; specs = the `test_all` lane only). The human-authorized direct FF push for docs-only diffs is RETIRED as an everyday path — direct atomic push is bootstrap/skip-hatch only. | Replaces the 2026-07-06 "docs-only bypass" practice; the shortcut now lives inside the required check instead of beside it. |

#### Future

- A pre-push git hook could refuse `session/<name>:main` if the pre-push merge step was skipped, but hook installation in fresh worktrees is its own coordination problem.

### Promote-to-Main Script
----
RID: `req-dev-multisession-promote-script`
Status: `Implemented`
Trace: `non-python` — scripts/promote-to-main.sh

`scripts/promote-to-main.sh` is a single-invocation wrapper around the four-step discipline in [Session → Main Push Workflow](#session-→-main-push-workflow). It runs from inside a session worktree and:

1. Fetches `origin/main`.
2. Performs the pre-push merge of `origin/main` into the session branch when the branch is behind. Skips when not behind to avoid a redundant empty merge commit.
3. Pushes with `git push --atomic origin session/<name>:main session/<name>:session/<name>` so `origin/main` and `origin/session/<name>` advance together (req-dev-multisession-push-workflow-3).
4. Advances the local `main` ref via `git -C $HOME/tap-sessions/main pull --ff-only origin main` so the next spawn branches from current code (req-dev-multisession-push-workflow-4).

The script is the canonical implementation of the push workflow. Agents (Claude, Codex, or otherwise) and humans alike SHOULD invoke it rather than re-typing the four commands; the script is part of the contract so both the action and its discoverability live in one place under version control.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-promote-script-1 | Operates on current worktree | Implemented | The script resolves the target via `git rev-parse --show-toplevel` and rejects invocation outside a worktree or on a non-`session/<name>` branch. | Lets the orchestrator `cd` into each worktree and call this script without arguments. |
| req-dev-multisession-promote-script-2 | Clean working tree required | Implemented | Aborts when there are staged or unstaged changes. Untracked files are permitted because `.env.local` and `.dev-credentials` are always untracked. | |
| req-dev-multisession-promote-script-3 | Pre-push merge | Implemented | Runs `git merge --no-edit origin/main` only when the branch is behind. Conflicts abort the merge and surface a manual-resolution message. | Skipping when not behind avoids needless merge commits. |
| req-dev-multisession-promote-script-4 | Atomic dual-refspec push (fallback) | Implemented | The direct atomic push per req-dev-multisession-push-workflow-3 runs ONLY on the bootstrap/skip-hatch path (gate workflow absent from origin/main, or `TAP_PROMOTE_SKIP_CI_GATE=1`), where it rides the admin bypass loudly. | Superseded as the default by `-4a`. |
| req-dev-multisession-promote-script-4a | PR promote (default) | Implemented | Default road to main (2026-08-10): push `session/<name>`, open/update the promote PR, run the local FAST lane in the shadow of the server checks, then ARM auto-merge (merge commit — squash would discard the individually SIGNED commits) only after local green; the server's required `gate` check (test_all lane + CI cold-boot + lean-boot jobs) decides the landing. Re-promote safety: any stale auto-merge arming is DISARMED before pushing (arming persists across pushes and would let the server land fresh commits before the local gates run). Local boot gates are OPTIONAL fast feedback (`TAP_PROMOTE_LOCAL_BOOT_GATES=1`) now that CI owns boot truth. | The bypass is unused on this path; emptying the bypass list + merge queue are the ruleset flip, tracked in `req-cicd-branch-protection`. |
| req-dev-multisession-promote-script-5 | Post-push primary sync | Implemented | Runs `git -C $HOME/tap-sessions/main pull --ff-only origin main` after a successful push. Warns and skips if the main worktree is absent (non-standard layout). | |
| req-dev-multisession-promote-script-6 | Dry-run mode | Implemented | `--dry-run` reports each step as `[dry-run] would: ...` without invoking any write operation, including the fetch. | |

### Promote-All-Sessions Script
----
RID: `req-dev-multisession-promote-all-script`
Status: `Implemented`
Trace: `non-python` — scripts/promote-all-sessions.sh

`scripts/promote-all-sessions.sh` is the orchestrator companion to `scripts/promote-to-main.sh`. It reads the per-machine session registry at `$HOME/tap-sessions/.registry` and runs the per-session promote script in each session worktree, in registry order.

Sequential is intentional: each per-session promote pushes its tip to `origin/main`, and the next session's pre-push merge then folds that change into its branch before its own push. Parallelism here would only create the non-fast-forward races the workflow already prevents.

A human running this script from any shell can promote every active session with one command; an agent inside a single session worktree continues to use the per-session script (it has no business reaching into sibling worktrees without operator intent).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-promote-all-script-1 | Registry-driven session list | Implemented | Reads `$HOME/tap-sessions/.registry`, ignoring comment and empty lines, to determine which session worktrees to promote. | |
| req-dev-multisession-promote-all-script-2 | Sequential execution | Implemented | Sessions are promoted one at a time, in registry order. The per-session script runs inside its own worktree (via subshell `cd`). | Each pre-push merge picks up earlier sessions' pushes. |
| req-dev-multisession-promote-all-script-3 | Stop on first failure by default | Implemented | A failed per-session promote aborts the orchestrator with a non-zero exit. `--keep-going` flips the default and runs every remaining session, exiting non-zero only if any failed. | |
| req-dev-multisession-promote-all-script-4 | Missing worktree skip | Implemented | A registry row whose worktree directory is absent is skipped with a warning (not failed). | The row is stale; the operator should `despawn` it to clean up. |
| req-dev-multisession-promote-all-script-5 | Pre-feature-branch skip | Implemented | A worktree without `scripts/promote-to-main.sh` is skipped with a warning. | Lets older session branches coexist while the convention rolls out. |
| req-dev-multisession-promote-all-script-6 | Summary output | Implemented | Prints ok / failed / skipped session names at the end so the operator sees what landed at a glance. | |
| req-dev-multisession-promote-all-script-7 | Dry-run mode | Implemented | `--dry-run` forwards `--dry-run` to each per-session invocation. | |

### Promote-Path Validation Gate
----
RID: `req-dev-multisession-promote-gate`
Status: `Proposed`

Advancing `origin/main` from a session branch MUST be gated on a passing validation run. The pre-push merge (step 2 of [Session → Main Push Workflow](#session-→-main-push-workflow)) makes the session branch fast-forwardable; this requirement adds that the merged tree MUST then pass the development validation gate *before* the atomic dual-refspec push. On a failing gate the promote aborts and `origin/main` is not advanced — a session never publishes a tree it has not validated, which is what protects every session spawned from local `main`.

This is the reciprocal of `req-dev-validation-promote-hook` in [spec-dev-validation.md](spec-dev-validation.md). The division is deliberate and MUST be kept consistent: this requirement owns the obligation *on the promote workflow* (when in the four-step sequence the gate runs, and that red blocks the push); the validation spec owns the *gate contract itself* (what the gate asserts, the cold-boot cycle, real-backend fidelity, the known-broken manifest). Neither spec restates the other's substance.

`scripts/promote-to-main.sh` and, transitively, `scripts/promote-all-sessions.sh` are the canonical enforcement points; the documented manual fallback sequence carries the same obligation. The gate runs after the pre-push merge so it validates the exact tree that will become `origin/main`. **Implemented:** `promote-to-main.sh` Step 2.5 runs the full pytest lane (`scripts/test`) then the cold-boot gate (`scripts/gate`) after the pre-push merge and before the atomic dual-refspec push; either red calls `fail` and aborts before any ref advances. The gate requires the session's stack to be up (it runs inside the compose image); `--dry-run` skips it (no push to gate).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-promote-gate-1 | Gate after merge, before push | Implemented | The validation gate runs after the pre-push merge and before the atomic dual-refspec push, against the merged tree. | `promote-to-main.sh` Step 2.5. Validates exactly what becomes `origin/main`. |
| req-dev-multisession-promote-gate-2 | Red blocks the push | Implemented | A failing gate aborts the promote with a non-zero exit; `origin/main` is not advanced and the session branch is not force-published past it. | `scripts/gate` non-zero → `fail` before Step 3. |
| req-dev-multisession-promote-gate-3 | Scripts and fallback covered | Implemented | `scripts/promote-to-main.sh`, the all-sessions orchestrator, and the documented manual sequence all carry the gate obligation. | Orchestrator calls the per-session script (transitive). |
| req-dev-multisession-promote-gate-4 | Reciprocal consistency | Implemented | This requirement and `req-dev-validation-promote-hook` cross-reference and stay consistent; neither restates the other's substance. | Prevents cross-spec drift. |

### All-Plugins CI Gate
----
RID: `req-dev-multisession-ci-gate`
Status: `Implemented`
Trace: `non-python` — .github/workflows/product-lines.yml

Once plugins leave the monorepo, the local [Promote-Path Validation Gate](#promote-path-validation-gate) can only validate the plugins installed in *this* stack; all-plugins truth moves server-side ([spec-dev-validation.md](spec-dev-validation.md) `req-dev-validation-all-plugins-lane`). This requirement obliges the promote path to **also** block on that lane: after the local gate is green, `promote-to-main.sh` triggers the all-plugins workflow on the merged tree, polls it to completion, and refuses the atomic dual-refspec push on red. **Option B** (trigger + poll) is chosen over a PR-gated merge specifically so the atomic dual-refspec push semantics that `req-dev-multisession-push-workflow-3` relies on are preserved — the fuller PR-gated model (option A) waits for the second-contributor trigger. Reciprocal of `req-dev-validation-all-plugins-lane-3`; neither restates the other's substance.

#### Status Details

Implemented as Step 2.6 of `scripts/promote-to-main.sh`: after the local gate is green it publishes the merged tree to a throwaway `_ci-gate/<session>` ref (so neither `origin/main` nor `origin/session/<name>` moves before validation), dispatches `all-plugins.yml` against that ref via `gh workflow run`, polls `gh run list` for the run on the exact merged SHA, then `gh run watch --exit-status` blocks the push on red and the throwaway ref is deleted on every exit path.

**Bootstrap — unexercised until the first post-bootstrap promote.** `workflow_dispatch` only works once `all-plugins.yml` is on `origin/main`, so the gate detects the file's presence on `origin/main` (via git, no `gh` needed) and **skips itself on the bootstrap promote that first lands the workflow** — that promote is ungated by construction. The wiring is therefore landed but has not yet run against a real gated promote; the first genuine exercise is the next promote after the workflow reaches main (planned: the aws-cloud worktree's first push under this process). Escape hatch `TAP_PROMOTE_SKIP_CI_GATE=1` skips loudly for the case where the full plugin set is validated another way (e.g. a full-monorepo local stack that already has every plugin installed).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-ci-gate-1 | Trigger + poll, then push | Implemented | After the local gate passes, promote triggers the all-plugins lane on the merged tree, polls to green, and only then runs the atomic push. | Keeps the atomic dual-refspec push (option B, not PR-gated). Runs against a throwaway `_ci-gate/<session>` ref. |
| req-dev-multisession-ci-gate-2 | Red blocks the push | Implemented | A red or timed-out lane aborts the promote; `origin/main` is not advanced and the session branch is not force-published past it. | Same fail-closed posture as the local gate. The workflow's own `timeout-minutes: 40` bounds a hung lane. |
| req-dev-multisession-ci-gate-3 | Reciprocal consistency | Implemented | This requirement and `req-dev-validation-all-plugins-lane` cross-reference and stay consistent; neither restates the other's substance. | Prevents cross-spec drift. |
| req-dev-multisession-ci-gate-4 | Bootstrap self-skip | Implemented | The gate skips itself when `all-plugins.yml` is not yet on `origin/main` (detected via git), so the promote that first lands the workflow is ungated by construction; every promote after is gated. | Escape hatch `TAP_PROMOTE_SKIP_CI_GATE=1` for a separately-validated full set. |

### Admin User Bootstrap
----
RID: `req-dev-multisession-admin-bootstrap`
Status: `Implemented`
Trace: `non-python` — scripts/spawn-session.sh

The spawn script must create a Django admin superuser in each new session's database, unattended, without prompting. This is a sub-feature of [Spawn Script](#spawn-script) but specified separately because the credential resolution model has its own design surface.

> **Reconciliation (2026-07-07):** `tap_auth/specs/spec-tap-auth-passkey-v0.md` (`req-tap-auth-passkey-dev-bootstrap`) revises this requirement for **passwordless-primary** deployments: the dev admin bridge changes from "resolve a password (env → Keychain → random), write `.dev-credentials`, `createsuperuser`" to "seed the admin and **replay the operator's exported public passkey record**" via `manage.py enroll-admin --import-dev-passkey`. Only public credential material moves (TAP never exports the private half — it stays under the authenticator/platform or its sync fabric); one `localhost` passkey then logs into every spawned session. This retires the dev password and makes the dev loop exercise the real passkey path. The password resolution model below remains the contract until that lands (feature Phase 2 / slim Phase A).

#### Username and email — fixed

- **Username:** `admin`.
- **Email:** `admin@<session>.tap.localhost` (e.g. `admin@cli.tap.localhost`).

Both are deterministic from the session name. Not configurable in v0 to keep the spawn flow simple.

#### Password resolution order

The spawn script resolves the admin password by checking these sources in order; the first that yields a value wins:

1. `--admin-password=<value>` flag passed to spawn (explicit, highest priority).
2. `TAP_DEV_ADMIN_PASSWORD` environment variable.
3. **macOS Keychain** (Darwin only): `security find-generic-password -s tap-dev-default -a admin -w 2>/dev/null`. Silently falls through if Keychain is locked, the entry is missing, or the platform is not Darwin.
4. **Default:** generate a fresh random password — `python3 -c "import secrets; print(secrets.token_urlsafe(18))"`.

Sources 1–3 give the developer a way to pin a stable password across sessions when convenience matters. Source 4 keeps the secure default in place.

#### Credentials file

Whatever password is resolved, the spawn script writes it (along with username, email, session name, and timestamp) to `<worktree>/.dev-credentials`. The file is the runtime interface — both the attached Claude session and the developer read it from a known path. Format mirrors `.env`:

```
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=<resolved>
DJANGO_SUPERUSER_EMAIL=admin@<session>.tap.localhost
SESSION_NAME=<session>
GENERATED_AT=<ISO-8601>
```

`.dev-credentials` is gitignored (a `.dev-credentials` rule is added to `.gitignore` alongside `.env.local`).

#### Superuser creation

The spawn script invokes Django's built-in unattended path:

```bash
scripts/dc exec \
  -e DJANGO_SUPERUSER_USERNAME \
  -e DJANGO_SUPERUSER_PASSWORD \
  -e DJANGO_SUPERUSER_EMAIL \
  web uv run python manage.py createsuperuser --noinput
```

Env vars are sourced from `.dev-credentials`. The command is idempotent in spawn flow because the database is freshly migrated (no existing admin user).

#### Echo at completion

Spawn ends by printing the resolved credentials and the session URL to stdout once, so a developer running spawn from a terminal sees them without having to read the file. The credentials file is named in the output ("Saved to `<worktree>/.dev-credentials`") so terminal-loss is recoverable.

#### Despawn behavior

`scripts/despawn-session.sh` removes the worktree, which deletes `.dev-credentials` along with everything else. The macOS Keychain entry (if used) is **not** touched by default — it's intended to outlive sessions. A `--purge-keychain` flag on despawn explicitly removes the `tap-dev-default` Keychain entry when the developer wants a clean slate.

#### Threat model and limits

`.dev-credentials` is a plaintext password on disk. This is acceptable for dev environments (no worse than `.env.local` carrying database credentials) but worth being explicit:

- **In scope:** preventing accidental commit (gitignored), preventing cross-session leakage (per-worktree, random by default).
- **Out of scope:** protecting against an attacker with filesystem access to the dev machine. Anyone who can read `.env.local` can read `.dev-credentials`, and anyone who can run shell commands as the developer can read the macOS Keychain (eventually, after Keychain auth — Keychain raises the bar but does not eliminate the threat).

Hardening beyond this (e.g. SSH-key-encrypted credentials, ephemeral admin tokens) is a Phase 4 concern, not Phase 2.

#### Cross-platform note

The Keychain branch (#3 above) is wrapped in a Darwin check. Linux / Windows dev machines fall through to env var or random — same UX, different ceiling on convenience.

#### Acceptance Criteria

> **Phase note (2026-07-07):** ACs -2, -3, -4, -5 describe the **password-era** bridge and are **superseded** by `req-tap-auth-passkey-dev-bootstrap` (passkey replay) once it lands — do not implement both. They remain the contract only until passkey replay ships. AC -1's "admin exists" survives; its "log in to `/admin/` (via password)" clause is replaced by passkey login (`req-tap-auth-passkey-recovery`).

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-admin-bootstrap-1 | Admin user created unattended | Proposed | After spawn, `admin` superuser exists in the session DB and can log in to `/admin/`. | "log in via password" → passkey once `req-tap-auth-passkey-dev-bootstrap` lands. |
| req-dev-multisession-admin-bootstrap-2 | Resolution order honored | Proposed | `--admin-password`, `TAP_DEV_ADMIN_PASSWORD`, Keychain, random — checked in that order; first hit wins. | Password-era; superseded by `req-tap-auth-passkey-dev-bootstrap`. |
| req-dev-multisession-admin-bootstrap-3 | Credentials file written | Proposed | `<worktree>/.dev-credentials` exists with all five fields and is gitignored. | Password-era; superseded by `req-tap-auth-passkey-dev-bootstrap`. |
| req-dev-multisession-admin-bootstrap-4 | Echoed once at spawn | Proposed | Spawn output names the username, password, email, URL, and credentials-file path. | Password-era; superseded by `req-tap-auth-passkey-dev-bootstrap`. |
| req-dev-multisession-admin-bootstrap-5 | Keychain optional | Proposed | Spawn succeeds on a machine with no `tap-dev-default` Keychain entry by falling through to random generation. | Password-era; superseded by `req-tap-auth-passkey-dev-bootstrap`. |
| req-dev-multisession-admin-bootstrap-6 | Despawn cleans up | Proposed | After despawn, `.dev-credentials` is gone (worktree removed). Keychain entry remains unless `--purge-keychain`. | |

### List Script
----
RID: `req-dev-multisession-list-script`
Status: `Proposed`

`scripts/list-sessions.sh` shows live state across all sessions: name, worktree path, branch, project name, ports, container status. Convenience for when 3+ sessions are running.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-list-script-1 | Live status | Proposed | List script shows running and stopped sessions with their ports and worktree paths. | |

### Name-Based Routing via Reverse Proxy
----
RID: `req-dev-multisession-named-routing`
Status: `Backlog`

A shared Traefik (or nginx-proxy) container running on the host outside any session's compose stack listens on `:80` and routes by `Host` header. Each session's compose adds router labels (e.g. `Host(\`cli.tap.localhost\`)`) and joins a shared `tap_proxy` network. Result: each session is reachable at `http://<name>.tap.localhost/` — **no port** in the URL — and Traefik forwards to the right `tap_<name>-web-1`. Direct `localhost:<WEB_PORT>` access continues to work as a fallback.

#### Status Details

Backlog because [Browser Disambiguation](#browser-disambiguation) already gives us human-readable URLs (`<name>.tap.localhost:<port>`) and visual labels in the UI without any new infrastructure. Traefik adds clean port-free URLs but introduces a shared singleton with its own lifecycle; promote when port management becomes the friction point or we cross enough sessions that remembering `:8010` vs `:8020` is the bottleneck.

#### Future Implementation Sketch

- Top-level `docker/proxy/` directory holds a Traefik compose file and config.
- A `scripts/proxy.sh up|down` controls the singleton.
- Spawn script adds Traefik labels to the new session's compose override and joins the shared network.
- Smoke test grows an ACID that verifies `curl -H 'Host: <name>.tap.localhost' http://localhost/` reaches the right session.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-named-routing-1 | Port-free URL works | Backlog | `http://<name>.tap.localhost/` reaches the named session via the proxy. | |
| req-dev-multisession-named-routing-2 | Direct port still works | Backlog | `http://localhost:<WEB_PORT>/` continues to work as a fallback. | |
| req-dev-multisession-named-routing-3 | Proxy lifecycle script | Backlog | `scripts/proxy.sh up|down` controls the shared Traefik singleton. | |

## Developer Onboarding

The canonical, step-by-step procedure for spawning a new isolated session lives in the doc [docs/misc/doc-dev-multisession-onboarding.md](../docs/misc/doc-dev-multisession-onboarding.md), owned by [spec-dev-multisession-onboarding-doc.md](spec-dev-multisession-onboarding-doc.md). Read the doc to onboard; this spec stays focused on *what* the system does, not *how* to use it.

After onboarding completes, the developer attaches an agent/editor session inside the new worktree, and that session runs the smoke tests in [spec-dev-multisession-smoketest.md](spec-dev-multisession-smoketest.md). Teardown is documented in [spec-dev-multisession-teardown.md](spec-dev-multisession-teardown.md).

## Operational Notes

### Per-session Claude Code attachment

Each worktree is a self-contained working directory, so attach Claude Code or Codex against the worktree before starting work. Claude CLI picks up `pwd`, Codex Desktop picks up the path passed to `codex app <worktree>`, and VSCode picks up the workspace folder it's opened against.

### Shared infrastructure

- **Playwright MCP**: stateless per call, safe to share across sessions. Each Claude session points at the same MCP server.
- **`.git`**: worktrees share the underlying repo, so commits/branches are visible across sessions immediately. Cross-session merges happen locally without a GitHub round-trip.

### Python environments

- **Container runtime:** `/app/.venv` is container-owned and backed by the compose project's `venv` named volume. Run app commands and tests through `scripts/dc exec web ...` so they use the Linux container environment.
- **Host tools:** do not point host-side Python, pytest, or editors at the container-owned `.venv`. If host-side Python is needed, use a separate environment path such as `UV_PROJECT_ENVIRONMENT=.venv-host uv sync`, and keep `.venv-host/` ignored.

### Future services

To add a new host-exposed service (Redis, mailcatcher, debugger):
1. Add the service to `docker-compose.yml` with `${SERVICE_PORT:-<default>}:<container-port>` mapping.
2. Allocate a fixed offset within each session's 10-port band (e.g., session `cli` = `tap_cli`, ports `8010` web, `5442` postgres, `6310` redis).
3. Update the port registry table in this spec.
4. Update spawn script's `.env.local` template.

## Status Vocabulary

Standard TAP states: `Proposed`, `Approved for Development`, `In Development`, `Implemented`, `Verified`, `Refactoring`, `Deprecating`, `Deprecated`, `Backlog`.
