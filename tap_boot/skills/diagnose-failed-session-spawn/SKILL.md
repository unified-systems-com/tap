---
name: diagnose-failed-session-spawn
description: Diagnose why a multi-session dev spawn (scripts/spawn-session.sh, or a scripts/gate-lean throwaway) failed to stand up — pinpoint the failing spawn step, name the root cause with the load-bearing log excerpt, and say what to fix. Use whenever a spawn aborts, boots UNHEALTHY, hangs, or the lean-boot gate goes RED.
allowed-tools: Read Grep Glob Bash(scripts/dc *) Bash(docker *) Bash(docker compose *) Bash(git *) Bash(grep *) Bash(tail *) Bash(cat *) Bash(sed *) Bash(ls *) Bash(cut *)
argument-hint: [session-name | compose-project | path-to-diag-log]  (default: infer the most recent failed spawn)
---

# Diagnose a Failed Session Spawn

> **Skill source-of-truth.** Canonical location: `tap_boot/skills/diagnose-failed-session-spawn/SKILL.md`. `.claude/skills/…` is a wiring symlink (`scripts/wire-skills.sh`). Edit the canonical.

A spawn (`scripts/spawn-session.sh`) stands an instance up through a fixed ordered sequence; a `scripts/gate-lean` throwaway drives that same sequence with a lean, isolated venv. When one fails, the failure is almost always at a **specific step**, and the web container's logs name it. This skill is the standardized read of that sequence so we stop re-deriving it by hand each time. Produce a **verdict**: failing step → root cause → the log line that proves it → the fix → whether to nuke.

**Owning spec:** `specs/spec-dev-multisession-diagnose.md` (`req-dev-multisession-diagnose-*`) is canonical for *what* this procedure must establish; this SKILL.md is *how*. Keep them aligned — a new requirement there earns a step here, and vice versa.

Authoritative background (skim, do not guess): `scripts/spawn-session.sh` (the step sequence), `scripts/despawn-session.sh` (teardown), `scripts/gate-lean` (the lean-boot gate + its `*-diag.log`), `specs/spec-dev-multisession.md`, `specs/spec-tap-boot-v0.md` (boot phases), `specs/spec-dev-validation.md`.

## Step 0 — Establish the target

Identify the failed session's **compose project** (`tap_<name>`) and where its worktree lives:

1. If given a `*-diag.log` path (a `gate-lean` failure capture), read it first — it already holds `compose ps` + `web logs`. Then continue for anything it doesn't cover.
2. Else resolve the project. From inside a session worktree, `scripts/dc` targets it; otherwise use `docker compose -p tap_<name>`. List candidates: `docker ps -a --format '{{.Names}}\t{{.Status}}' | grep -E 'tap_'`. A failed spawn appends **no** registry row (`~/tap-sessions/.registry` is append-on-success), so a container present but absent from the registry is itself a signal of a partial spawn.
3. Note the worktree base: default `~/tap-sessions/<name>`, but a `gate-lean` throwaway lives under `WORKTREE_BASE` (system tmp). `git worktree list` shows live ones.

## Step 1 — Read container state (which step died)

**Read the boot record first** (req-boot-obs-record): `<worktree>/logs/boot/latest.boot-record.json` holds the last boot's structured outcome — phases, per-step status + durations, boot-variable provenance, and on abort the failing step + its failing self-test checks (e.g. the 401 that names a dead credential). A stale `"outcome": "running"` means the boot process was killed mid-run. The spawn transcript (`<worktree>/logs/spawn.log`) is the raw-output companion. Then:

```
docker compose -p tap_<name> ps          # container states + exit codes
docker compose -p tap_<name> logs --tail 300 web
docker compose -p tap_<name> logs --tail 80 db
```

Map the last successful line in the `web` log to the spawn step. The failure-prone steps, in order:

| Step | What runs | Typical failure signature |
| --- | --- | --- |
| **4** Pull & start | `dc pull web db` + `up -d` (published GHCR images; local build only as fallback) | **pull failure** (offline, GHCR outage, unpublished tag — degrades to the slow local-build path, watch for an unexpected build); image build error in the fallback; **port already allocated** (`bind: address already in use`); a stale prior stack on the band |
| **5** Entrypoint | uv sync → **pre-boot** (install plugins, conformance/reconcile/dep/coherence gates, snapshot) → **migrate** → runserver | see Step 2 below — this is where most real failures land |
| **6** `manage.py boot` | auth → population (seed-plugin / fire-collector) | population **abort**: unknown plugin/collector/bundle key; a seed bundle raised; a `fire-collector` step timed out (`req-boot-collector-timeout`) |
| **6.5** Health gate | `manage.py health --json` | a critical probe UNHEALTHY: db / cache (`tap_cache` table) / queue / secrets |

## Step 2 — Classify the root cause (pre-boot / migrate / boot / health)

Match the `web` log against these signatures — most-common first:

- **Step 5 backstop on a HEALTHY, still-progressing container (slow boot, not a fault).** Since 2026-08-09 evening the wait is STALL-AWARE: the primary trigger is `Entrypoint STALLED` (no web-log output for 120s — a real hang), and the wall-clock ceiling (600s warm-pull path / 900s local-build fallback) only fires on a boot that is *still streaming* (`log was still progressing Ns ago` in the message) but `docker compose ps` shows web Up and the log still advancing (uv sync / migrate). Time the phases with `docker logs --timestamps`. Since the published-image wave (2026-08-09) the entrypoint seeds the uv cache from the image and a normal first boot syncs in seconds — so hitting the 600s backstop now implies the slow FALLBACK path ran: look for a missing `==> Seeding uv cache` line (stale/absent seed → live `cryptography --no-binary` compile, ~4m33s observed) or an unexpected local image build. Markers: `.dev-credentials` absent (Step 6 never ran) + no registry row. Fix for the CEILING case: do NOT nuke — let the entrypoint finish, then run the tail steps manually (Step 6 creds + `manage.py boot`, 6.4 passkey `--json`→`--import`, 6.5 `manage.py health --json`, registry append); then chase the host load or why the warm path was skipped. The STALLED case is a genuine hang: read the last log line for what wedged (a lock, a dead DB, a hung network call) — waiting longer will not help.
- **Probe-blind timeout: healthy container, host under load.** `Web did not become ready in ${WAIT_TIMEOUT}s` while the diag/web log shows a COMPLETE boot (migrations done, runserver + queue workers up, well inside the window). Cause: the Step 5 readiness probe treats a request TIMEOUT as not-listening, and a loaded host (several stacks + CI lanes on one machine) pushes a healthy dev server past the probe's per-request ceiling — every poll fails while the server is fine. Intermittent by construction (load-dependent: red-green-red across identical code). Fixed 2026-08-09 by raising the per-request ceiling to 10s; if it recurs, suspect host saturation first. Beware a mis-verdict here: one 2026-08-09 red showed "IMAGE BUILD / SPAWN INFRA — no container created" from a STALE diag file — gate-lean's capture path can fail to write, leaving an earlier run's capture in place (unowned bug, flagged 2026-08-09). An empty `compose ps` in a diag ≠ containers never existed — cross-check the web log tail and the file's timestamps.
- **Import leakage (the `requests` / `jwt` class).** `ModuleNotFoundError: No module named '<pkg>'` raised from a **core** (`tap_*`) module during pre-boot / migrate / boot, in a **lean** profile (`core` / `core_dev`) where that package isn't installed. This is exactly what `gate-lean` exists to catch: a core module imports a **plugin-only** dependency. Root cause is the offending `import` in core, not the venv. Fix: move the dependency out of the core import path (lazy-import it inside the plugin, or declare it as a core dep if it truly is one). Confirm with `grep -rn "import <pkg>" tap*/` to find the leak.
- **Pointer-rehomed profile spawned without `--from` (profile file absent).** `TAP-ABORT: preboot: boot profile '<id>' not found at /app/boot/<id>.boot.json`, repeating every few seconds — compose restarts the entrypoint on exit, so `ps` shows web `Restarting (1)`: read the loop as ONE failure, not many. Cause: the profile was evicted from core and ships inside its plugin repo (the samsite rehome, commit 3bd0e40d, 2026-08-09 — `req-boot-bootstrap-samsite-rehome`), but the spawn ran the plain form (or `.env.local` carries a stale `TAP_BOOT_PROFILE`) so the stage-0 pointer fetch never staged the record. Tell: `spawn.log` opens directly at the image pull with no `--from`/pointer-fetch/`--boot-file` lines. DB untouched (abort is pre-migrate). Fix, live worktree (do NOT nuke — and never despawn the worktree you're working in): fetch `tap_plugin/<slug>/boot/<id>.boot.json` from the plugin repo at its CURRENT release tag (check `gh api repos/<org>/<repo>/tags`, not the tag frozen in old help text) into the worktree's `boot/`; the `.:/app` bind mount means the crash-looping entrypoint picks it up on its next restart; then run the tail steps manually (Step 6 creds + `manage.py boot`, 6.4 passkey, 6.5 health, registry append). Alternative for a disposable target: despawn and re-spawn with `--from git+https://github.com/<org>/<repo>@<tag>#<id>`. GRACEFUL SINCE 2026-08-20: spawn's Step 2.9 preflight fails this host-side in <1s (available-ids list + pointer-form hint, before any docker work), and both container-side readers (`tap/preboot.py` / `tap_boot/profile.py`, `TAP-KNOWN-DUPE(boot-profile-not-found)`) now emit the same enriched message — so seeing the bare container-side abort implies a stale `.env.local` `TAP_BOOT_PROFILE` or a non-spawn standup, not a spawn invocation.
- **Pre-boot gate abort.** A `[hex]` `pre-boot … gate` line at ERROR: identity/reconciliation/dependency/coherence mismatch (e.g. `installed != declared`, a collector-scope drift, an undeclared cross-plugin import edge). Root cause is a manifest ↔ install ↔ code disagreement; the message names the mismatch. (See the collector-identity / validate_plugin work.)
- **Migration drift / failure.** `makemigrations --check` would flag model drift; a `migrate` traceback names the failing migration/SQL. Fix: generate + commit the migration, or repair the bad one.
- **Boot population abort.** `BootError` naming an unknown plugin/collector/bundle, or a seed bundle exception. Root cause is the profile referencing something the install set / registry doesn't provide, or bad GRIFT.
- **Preflight offline lane: required secret missing / kind-mismatched.** Boot aborts in seconds with `required secret <scope>:<key> missing` (or `kind mismatch`) before any seed — the boot record's `abort.missing_secrets` carries ref/kind/note/problem. A PROVISIONING gap, not a code fault: the profile declares a secret this host has not been given (or the envelope's `kind` field disagrees with the declaration). Fix = drive `/provision-secrets` (enumerate → mint → place → restart web → re-boot). Remember the loader is load-once: a freshly placed envelope needs `scripts/dc restart web` before it is visible.
- **Fire-collector external-credential failure.** A `fire-collector` step FAILED with an auth-shaped summary (e.g. github_core's `GitHub API unreachable or PAT auth failed`) while the container log is otherwise clean. Note Step 6 runs via `scripts/dc exec` from the *host*, so its output lands in the spawn terminal and the captured transcript at `<worktree>/logs/spawn.log` (req-boot-obs-spawn-presentation), not `logs web` — read that transcript first; re-running `scripts/dc exec -T web uv run python manage.py boot --profile <id>` is the fallback when no transcript exists. Then split credential-dead vs target-moved: probe the collector's own self-test path in a shell (resolve the secret, hit the provider's cheapest authed endpoint, e.g. GitHub `/rate_limit`, printing only status + token prefix/length — never the token). 401 ⇒ the stored credential is revoked/expired/rotated; 200 + per-resource 404 ⇒ the secret's target list (org/repo) is stale. Fix = drive `/provision-secrets` (rotate path; `manage-secret` if the kind/consumer wiring itself is wrong) — and remember `~/tap-secrets` is shared host state: the fix (and the breakage) applies to every session at once.
- **Health red.** Read the probe JSON: `docker compose -p tap_<name> exec -T web uv run python manage.py health --json`. `tap_cache` missing ⇒ createcachetable ordering; a secrets probe ⇒ a required secret absent under `TAP_SECRETS_ROOT`; db/queue ⇒ backend down.
- **Infra, not app.** Port collision (Step 4): another stack holds the band — `docker ps --format '{{.Names}} {{.Ports}}' | grep <port>`. DB unhealthy: read `logs db`. Stale volume from a prior aborted run: a `_venv` / `_postgres_data` volume for the project lingering (`docker volume ls | grep tap_<name>`).

## Step 3 — Verdict

State plainly: **failing step**, **root cause**, the **one log line** that proves it, the **fix**, and **whether the throwaway/session should be nuked** (`WORKTREE_BASE=<base> scripts/despawn-session.sh <name> --yes` — clean throwaways tear down unattended; a session with unpushed commits is HARD-STOPPED by despawn, report that instead of forcing). If diagnosing a `gate-lean` RED, note that gate-lean nukes on exit — so diagnose from the captured `*-diag.log` unless you caught it live.

## Step 4 — Reflect and evolve this skill (do every run)

Before finishing, reflect on the diagnostic session itself:

- Did the failure fit a signature above, or was it a **new** class? If new, add a row/bullet (signature → root cause → fix) so the next run catches it in one pass.
- Did a step's evidence command come up short (wrong log depth, a state `ps`/`logs` didn't reveal, a probe you had to reach for)? Improve the command.
- Was the target hard to resolve (naming, tmp base, no registry row)? Sharpen Step 0.

Make the edit to **this** SKILL.md in the same change (it is the standard we are iterating), and note in your summary what you changed and why — so the skill compounds instead of staying frozen at its first draft. A new *signature* is a SKILL.md-only edit; only a genuinely new **requirement** (a new kind of thing the procedure must establish) also touches the owning spec (`spec-dev-multisession-diagnose.md`).
