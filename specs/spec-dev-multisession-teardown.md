# Multi-Session Dev Environment — Teardown

## Philosophy

Every spawned dev session must despawn cleanly with **one command**. Manual teardown is error-prone — leftover containers, orphaned volumes, dangling networks, abandoned worktrees, and unmerged session branches accumulate fast and silently degrade the developer experience. A single-invocation teardown script is the public interface; everything else is implementation detail.

This spec lives separately from [spec-dev-multisession.md](spec-dev-multisession.md) so the teardown feature can be tracked, reviewed, and shipped on its own cadence.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Single Command | One invocation removes the entire session — no follow-up cleanup required. |
| 2. | Total Cleanup | Containers, networks, volumes, worktree, and session branch are all gone. |
| 3. | Safety Rails | Refuse to destroy uncommitted work or unmerged branches without explicit consent. |
| 4. | Idempotent | Running teardown on an already-torn-down session is a no-op with a clear message, not an error. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-dev-multisession-teardown-script | [Despawn Script](#despawn-script) | Implemented | The one-line public interface |
| req-dev-multisession-teardown-cleanup | [Total Cleanup](#total-cleanup) | Implemented | What "torn down" means |
| req-dev-multisession-teardown-safety | [Safety Rails](#safety-rails) | Implemented | Re-framed 2026-06-30: hard-stop on unpushed commits; dirty worktree only forces confirm |

### Despawn Script
----
RID: `req-dev-multisession-teardown-script`

Status: `Implemented`

The public interface is a single command:

```bash
scripts/despawn-session.sh <name>                  # interactive confirm
scripts/despawn-session.sh <name> --yes            # skip confirm (clean sessions only)
scripts/despawn-session.sh                         # interactive — pick from registry
scripts/despawn-session.sh <name> --purge-image    # also remove this session's images (re-pull next spawn)
scripts/despawn-session.sh <name> --abandon-unmerged  # consent to discard unpushed commits
scripts/despawn-session.sh <name> --keep-images    # skip the image-hygiene step
```

Where `<name>` matches a session previously spawned via the procedure in [spec-dev-multisession.md](spec-dev-multisession.md) (e.g. `cli`, `vscode`). The script also accepts names that are not in the registry — useful for cleaning up half-spawned sessions where the registry append never happened.

Flags:

- `--yes` / `-y` — skip the confirmation prompt. Pair with the named form for one-line invocation in scripts. Narrowed by the safety guard ([Safety Rails](#safety-rails)): `--yes` never bypasses the unpushed-commit hard-stop, and a dirty worktree still forces an interactive confirm even under `--yes`.
- `--purge-image` — also remove the `tap-web` / `tap-db` images **this session resolves to** (its own `scripts/dc config --images`, captured before the worktree is removed), so the next spawn re-pulls — or, on the pull-fallback path, rebuilds — from scratch. This is the "poisoned image" escape hatch. `docker rmi` is never forced: an image another live session's container holds is refused and reported, which is the right outcome. Runtime Python state lives in compose volumes and is removed by normal despawn volume cleanup. (Until tap#273 the flag targeted `tap_<name>-web`, an image name compose stopped producing in the pull-only wave — a documented flag that silently did nothing.)
- `--keep-images` — skip the post-teardown image hygiene step (`scripts/prune-images`, see [Image Hygiene](#image-hygiene)). Hygiene runs by default because the alternative was observed: with nothing in the lifecycle reclaiming superseded pulled images, Docker.raw ratcheted to ~88GiB and the host disk hit 100% (tap#271).
- `--abandon-unmerged` — explicit consent to destroy commits that exist only on `session/<name>` and are not in `origin/main`. Required to despawn a session whose branch is ahead of `origin/main`; without it, despawn hard-stops. See [Safety Rails](#safety-rails).

#### Behavior

Best-effort, aggressive teardown. Individual cleanup-step failures log a warning and continue rather than aborting — the goal is "leave nothing behind," not "halt at the first surprise." Re-running on an already-torn-down session is safe (each step's no-op path is reached cleanly).

#### Implementation

The script lives at `scripts/despawn-session.sh` and is checked into the repo. It runs from anywhere (uses `git rev-parse --show-toplevel` of the primary checkout for relative ops).

**Invoke despawn from the primary checkout (`~/tap-sessions/main`).** Each worktree carries its own copy of the script, so a despawn run from inside a stale session uses *that* session's possibly-outdated copy — including, before this version, one with no [safety guard](#safety-rails) at all. The primary checkout is the one kept current via the promote sync ([req-dev-multisession-push-workflow-4](spec-dev-multisession.md)), so running despawn from there guarantees the guard is present. This matters most for the dangerous case the guard defends — despawning a session that itself holds unpushed work.

Sequence:

1. **Pick the session.** If `<name>` is provided, use it. Otherwise display the registry and prompt. Names not in the registry are accepted (cleaning up a half-spawned session may not have a registry row).
2. **Show the plan and confirm.** Lists what will be removed (containers, volumes, networks, worktree path including all uncommitted files, branch, registry row, optionally the per-project image). Skip with `--yes`.
3. **Stop the stack.** Prefer `cd <worktree> && scripts/dc down -v --remove-orphans` so `.env.local` resolves the project name correctly. Fall back to `docker compose -p tap_<name> down -v --remove-orphans` if the worktree is unavailable.
4. **Belt-and-suspenders volume / network cleanup.** Even after step 3, named volumes / networks under `tap_<name>_` are matched and removed explicitly. This catches the failure mode where a previous `dc down` couldn't identify the project (missing `.env.local`).
5. **Remove the worktree and branch.** `git worktree remove --force` followed by `git branch -D session/<name>`. If the worktree directory survives somehow (e.g. removed outside git's awareness), `rm -rf` it.
6. **Remove the registry row.** `sed -i.bak "/^<name> /d" ~/tap-sessions/.registry`, freeing the band for reuse. See [req-dev-multisession-port-registry](spec-dev-multisession.md#per-machine-session-registry).
7. **(Optional) Purge this session's images** with `--purge-image`: `docker rmi` (unforced) for each ref the session's compose config resolved to in step 2. A ref another session's container holds is kept and the daemon's reason printed. Runtime Python state is not image-owned; `down -v` and the residual volume cleanup remove the Postgres data, container venv, and uv cache volumes.
8. **Image hygiene** (unless `--keep-images`): run `scripts/prune-images` from the primary checkout. It runs *after* step 5 so the despawned worktree no longer contributes to the keep-set. See [Image Hygiene](#image-hygiene).
9. **Print a verification block** with the commands the operator can run to confirm everything's gone.

#### Image Hygiene

Spawn pulls the published `tap-web` / `tap-db` images and every session rides `:latest` (the `.env.local` block in `spawn-session.sh`). Each publish re-points `:latest`; the previous digest becomes an untagged `<none>` image; old pinned tags and local `scripts/dc build` cache accrue the same way. Before tap#271 no lifecycle step ever reclaimed any of it.

`scripts/prune-images` is the one reclaim path (invoked by despawn on every teardown and by spawn after a successful pull — the moment a digest is superseded; runnable by hand, `--dry-run` reports without removing). Its rules:

- **The keep-set is derived, never authored.** Every git worktree of the repo resolves its own image refs through `scripts/dc config --images` — the same `.env` + `.env.local` cascade `up` uses — so a checkout pinned to an older `TAP_VERSION` keeps that version and a `:latest` session keeps whatever `:latest` currently is. Images any container references (running or stopped) are additionally protected by the daemon (`docker rmi` without `-f` refuses).
- **Scope is the TAP-owned repositories only** — the repos the *primary* checkout's compose resolves to — never every repository some worktree mentions, so an upstream image shared with non-TAP projects on the host (e.g. a bare `postgres`) is out of reach.
- **It removes** superseded in-scope tags (image ID not in the keep-set), dangling images (`docker image prune` without `-a`), and build cache unused for longer than `BUILD_CACHE_UNTIL` (default 72h — bounded, not zeroed, so Dockerfile iteration keeps a warm cache).
- **It never runs** `docker volume prune` (a session that is `down` but not despawned owns named DB volumes no container references — pruning them is data loss) or `docker system prune -a` (would take the current pin of every stopped session; spawn re-pulls, but that must be a conscious act).
- **Fail-closed on an incomplete keep-set**: if any worktree carrying a `docker-compose.yml` cannot resolve its images, superseded-tag removal is skipped for that run (dangling + build-cache pruning still run — they never touch a tagged image). Every daemon call is bounded by a timeout so a disk-starved daemon degrades to "prune skipped", never a wedged spawn or despawn.
- Trap: on macOS, Docker.raw returns host space via TRIM after in-VM deletion; `df` may not move until Docker Desktop restarts.

#### Best-effort semantics

Individual cleanup steps log a warning on failure and continue. The script doesn't run with `set -e`. The reasoning: when an operator invokes despawn, what they want is "leave nothing behind from this session." Aborting on the first surprise (a missing volume, a worktree git no longer knows about, etc.) leaves more partial state than just pushing through. Re-running on an already-clean session is safe — each step's no-op branch is reached without error.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-teardown-script-1 | Single-command invocation | Proposed | `scripts/despawn-session.sh <name>` is the only command needed for a clean teardown. | |
| req-dev-multisession-teardown-script-2 | Idempotent | Proposed | Running on a non-existent or already-torn-down session exits 0 with no error. | |
| req-dev-multisession-teardown-script-3 | Image purge flag | Implemented | `--purge-image` removes the images the session's own compose config resolves to (captured before worktree removal), unforced, so the next spawn re-pulls/rebuilds from scratch; a ref held by another session's container is kept and the reason reported. | Re-targeted 2026-09-01 (tap#273): the previous `tap_<name>-web` target no longer existed. Verified by hand: with the images held by live sessions every ref is refused with the daemon's conflict message; after `down`, a session's refs are removed. |
| req-dev-multisession-teardown-script-4 | Half-spawn recovery | Proposed | Despawn cleans up sessions whose registry append never happened (worktree exists, registry row doesn't). | |
| req-dev-multisession-teardown-script-5 | Best-effort cleanup | Proposed | Individual cleanup-step failures log a warning and continue. | |
| req-dev-multisession-teardown-script-6 | Image hygiene | Implemented | Despawn (and spawn, after a successful pull) runs `scripts/prune-images`: after it, no in-scope `tap-web`/`tap-db` image other than those resolved by a remaining worktree (or held by a container) remains, dangling images are gone, and build cache unused beyond `BUILD_CACHE_UNTIL` is gone; named volumes are never pruned. `--keep-images` opts out. | tap#271; `--dry-run` for the report-only form. Verified by hand 2026-09-01: a distinct stale `tap-db` tag survives while a container holds it and is removed once free; a shared-ID extra tag is left (costs nothing). |

### Total Cleanup
----
RID: `req-dev-multisession-teardown-cleanup`

Status: `Proposed`

After a successful (non-dry-run, non-`--keep-branch`) teardown for session `<name>`, none of the following may exist:

- Containers in project `tap_<name>`.
- Networks owned by project `tap_<name>`.
- Volumes owned by project `tap_<name>` (notably `tap_<name>_postgres_data`, `tap_<name>_venv`, and `tap_<name>_uv_cache`).
- The worktree directory `~/tap-sessions/<name>`.
- The git branch `session/<name>`.
- The session's row in `~/tap-sessions/.registry` (band must be freed for reuse).

#### Verification

Run from the primary checkout:

```bash
docker ps -a --filter "label=com.docker.compose.project=tap_<name>"   # no rows
docker volume ls --format '{{.Name}}' | grep "^tap_<name>_"           # no output
docker network ls --filter "name=tap_<name>_" --format '{{.Name}}'    # no rows
[[ -d ~/tap-sessions/<name> ]] && echo FAIL || echo OK                # OK
git branch --list "session/<name>" | grep .                           # no output
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-teardown-cleanup-1 | No containers | Proposed | No containers remain in the session's compose project. | |
| req-dev-multisession-teardown-cleanup-2 | No volumes | Proposed | No volumes remain in the session's compose project, including Postgres data, the container Python virtualenv, and uv cache. | |
| req-dev-multisession-teardown-cleanup-3 | No network | Proposed | No networks remain in the session's compose project. | |
| req-dev-multisession-teardown-cleanup-4 | Worktree removed | Proposed | The `~/tap-sessions/<name>` directory is gone. | |
| req-dev-multisession-teardown-cleanup-5 | Branch removed | Proposed | The `session/<name>` branch is gone (unless `--keep-branch`). | |
| req-dev-multisession-teardown-cleanup-6 | Registry row removed | Proposed | The session's row in `~/tap-sessions/.registry` is gone, freeing its band for reuse. | |

### Safety Rails
----
RID: `req-dev-multisession-teardown-safety`

Status: `Implemented`

The two ways despawn can destroy real work are not equivalent, and the guard treats them differently. This is the key lesson of the 2026-04-27 deprecation (see history below): the original blunt design collapsed both into one rule and one `--force`, which made safety into noise.

**Unpushed commits — hard stop.** If `session/<name>` has commits not reachable from `origin/main` (`git rev-list origin/main..session/<name>` is non-empty), despawn refuses outright and exits non-zero. `git branch -D` would make those commits unreachable; they are real, hard-to-recover work. `--yes` does **not** bypass this. The only ways forward are to promote the work (`scripts/promote-to-main.sh`) or to pass `--abandon-unmerged` as explicit, deliberate consent to discard it. The block is non-destructive: it fires before any teardown step runs, so the branch, worktree, and containers all survive a blocked invocation. Before measuring, despawn does a best-effort `git fetch origin main` so "unpushed" is accurate; if the fetch fails (offline) or there is no `origin/main` at all, the guard **fails closed** (stale/absent comparison can only over-count unpushed commits, never under-count).

**Dirty worktree — forced confirm, not a block.** Uncommitted changes (modified, staged, or untracked) are usually transient scratch left by exactly the cases the 2026-04-27 deprecation named — mid-debugging, a failed spawn, a SIGKILL during migrate. These do **not** hard-stop. They are surfaced in the plan and they force an interactive `[y/N]` confirm even when `--yes` is passed, so a scripted `--yes` can never silently torch uncommitted work, but an operator who means it is one keystroke away.

This keeps the common path frictionless: a session despawned after promotion is clean and fully pushed, so `--yes` sails straight through.

#### History — original framing (deprecated 2026-04-27)
The original safety design called for despawn to refuse on *both* dirty worktrees and unmerged commits, with a single `--force` as the opt-in override. In practice, despawn is most often invoked exactly when the worktree is dirty, making the refusal the rule and `--force` the path everyone reflexively types — so the rail protected nothing. That framing was deprecated in favor of aggressive-by-default cleanup with a confirm prompt. The 2026-06-30 re-framing above keeps that lesson (a dirty worktree must not be a blunt block) while restoring a real rail for the genuinely dangerous case the confirm-only design left exposed: committed-but-unpushed work destroyed by `branch -D`. The distinction the original design missed is that uncommitted scratch and unpushed commits are not the same loss.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-teardown-safety-1 | Dirty worktree forces confirm | Implemented | A dirty worktree does not hard-stop, but forces an interactive `[y/N]` confirm even under `--yes`. | |
| req-dev-multisession-teardown-safety-2 | Unpushed commits hard-stop | Implemented | A branch ahead of `origin/main` blocks despawn (non-destructively, exit non-zero); only `--abandon-unmerged` overrides, and `--yes` does not. | |
| req-dev-multisession-teardown-safety-3 | Fail closed when unverifiable | Implemented | If `origin/main` cannot be fetched or does not exist, treat all branch commits as unpushed rather than assuming safety. | |

## Manual Teardown (until the script lands)

Until `scripts/despawn-session.sh` is implemented, follow this sequence by hand for session `<name>`:

```bash
NAME=<name>
REPO=~/Documents/code/tap
cd ~/tap-sessions/$NAME
git status                                        # confirm clean
scripts/dc down -v --remove-orphans

cd $REPO
git worktree remove ~/tap-sessions/$NAME
git branch -D session/$NAME

# Free the band for reuse — remove the registry row.
sed -i.bak "/^${NAME} /d" ~/tap-sessions/.registry && rm -f ~/tap-sessions/.registry.bak
```

Verify with the commands in [Total Cleanup → Verification](#verification).

## Status Vocabulary

Standard TAP states: `Proposed`, `Approved for Development`, `In Development`, `Implemented`, `Verified`, `Refactoring`, `Deprecating`, `Deprecated`.
