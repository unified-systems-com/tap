#!/usr/bin/env bash
# scripts/despawn-session.sh — fully tear down a multi-session dev environment.
#
# Removes everything: docker containers + volumes + networks, the worktree
# (with all uncommitted files), the session/<name> branch, and the registry
# row. Best-effort: individual step failures log a warning and we continue —
# the goal is "leave nothing behind."
#
# Spec: req-dev-multisession-teardown-script in spec-dev-multisession-teardown.md
#
# Usage:
#   scripts/despawn-session.sh                  # interactive — pick from registry
#   scripts/despawn-session.sh <name>           # despawn the named session (with confirm)
#   scripts/despawn-session.sh <name> --yes     # skip confirm prompt (clean sessions only)
#   scripts/despawn-session.sh <name> --abandon-unmerged
#                                               # consent to destroy commits that exist
#                                               # only on session/<name> (not in origin/main).
#                                               # Without this flag, despawn HARD-STOPS when
#                                               # the branch has unpushed commits.
#   scripts/despawn-session.sh <name> --purge-image
#                                               # also remove the tap-web/tap-db images
#                                               # THIS session resolves to (its compose
#                                               # config), so the next spawn re-pulls
#                                               # (or rebuilds) from scratch. Refused,
#                                               # not forced, while another session's
#                                               # container still holds the image.
#   scripts/despawn-session.sh <name> --keep-images
#                                               # skip the post-teardown image hygiene
#                                               # (scripts/prune-images) that reclaims
#                                               # superseded tap-web/tap-db images and
#                                               # stale build cache (tap#271).
#
# Safety: unpushed commits on session/<name> are real, hard-to-recover work, so
# despawn refuses to delete the branch until they are promoted (scripts/promote-to-main.sh)
# or you explicitly pass --abandon-unmerged. A merely-dirty worktree (uncommitted
# scratch) does not hard-stop, but it always forces an interactive confirm — even
# under --yes — so a scripted --yes can never silently torch uncommitted work.

# NOT set -e — we want best-effort cleanup, not abort-on-first-failure.
set -uo pipefail

# Resolve repo root from this script's own location, not $PWD, so the script
# can be invoked from anywhere (e.g. via a PATH symlink or alias).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
REGISTRY="$HOME/tap-sessions/.registry"

bold()   { printf "\n\033[1m==> %s\033[0m\n" "$1"; }
info()   { printf "    %s\n" "$1"; }
ok()     { printf "\033[32m    %s\033[0m\n" "$1"; }
warn()   { printf "\033[33m    %s\033[0m\n" "$1"; }
err()    { printf "\033[31m    %s\033[0m\n" "$1" >&2; }
prompt() { printf "    \033[36m%s\033[0m " "$1"; }

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------
SESSION_NAME=""
ASSUME_YES=0
PURGE_IMAGE=0
KEEP_IMAGES=0
ABANDON_UNMERGED=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -y|--yes)             ASSUME_YES=1; shift ;;
    --purge-image)        PURGE_IMAGE=1; shift ;;
    --keep-images)        KEEP_IMAGES=1; shift ;;
    --abandon-unmerged)   ABANDON_UNMERGED=1; shift ;;
    -h|--help)
      sed -n '/^# Usage:/,/^# *$/p' "$0" | sed 's/^# //; s/^#//'
      exit 0
      ;;
    -*)               err "Unknown flag: $1"; exit 1 ;;
    *)                SESSION_NAME="$1"; shift ;;
  esac
done

# ---------------------------------------------------------------------------
# Pick session name interactively if not provided
# ---------------------------------------------------------------------------
if [[ -z "$SESSION_NAME" ]]; then
  if [[ -f "$REGISTRY" ]] && grep -qvE '^(#|$)' "$REGISTRY"; then
    bold "Current sessions"
    printf '      %-20s %-5s %-5s %s\n' "name" "web" "db" "spawned"
    grep -vE '^(#|$)' "$REGISTRY" | while read -r r_name r_web r_db r_branch r_spawned; do
      printf '      %-20s %-5s %-5s %s\n' "$r_name" "$r_web" "$r_db" "$r_spawned"
    done
    echo
  else
    info "No sessions in registry. Proceed by name to clean up half-spawned state."
  fi
  prompt "Session name to despawn:"
  read -r SESSION_NAME
fi

[[ -n "$SESSION_NAME" ]] || { err "Session name required"; exit 1; }

# WORKTREE_BASE mirrors spawn-session.sh: a session spawned into an alternate
# base (e.g. the lean-boot gate's tmp dir) is torn down by name from that same
# base. Default ~/tap-sessions preserves existing behaviour.
WORKTREE="${WORKTREE_BASE:-$HOME/tap-sessions}/$SESSION_NAME"
PROJECT="tap_${SESSION_NAME}"

# ---------------------------------------------------------------------------
# Show the plan, get confirmation
# ---------------------------------------------------------------------------
bold "Despawn plan for '$SESSION_NAME'"
info "  Docker project:        $PROJECT"
info "  Worktree:              $WORKTREE  (entire directory + all uncommitted files)"
info "  Branch:                session/$SESSION_NAME"
info "  Registry row:          $REGISTRY"
# --purge-image: resolve the session's image refs NOW, while its worktree (and
# .env.local) still exists — compose is the one authority on which images this
# session uses (a session on `:latest` and a checkout pinned to a TAP_VERSION
# resolve differently; tap#273 — the old `tap_<name>-web` target was an image
# name compose stopped producing in the pull-only wave).
PURGE_REFS=""
if [[ "$PURGE_IMAGE" -eq 1 ]]; then
  if [[ -x "$WORKTREE/scripts/dc" ]]; then
    PURGE_REFS="$( cd "$WORKTREE" && timeout 60 scripts/dc config --images 2>/dev/null | sort -u )" \
      || warn "  could not resolve this session's images (compose config failed) — --purge-image has nothing to target"
  else
    warn "  no live worktree at $WORKTREE — --purge-image cannot resolve this session's images"
  fi
  info "  Purge images:          $(echo "$PURGE_REFS" | tr '\n' ' ')(next spawn re-pulls; refused while another session holds one)"
fi
[[ "$KEEP_IMAGES" -eq 0 ]] && info "  Image hygiene:         superseded tap images + stale build cache (scripts/prune-images; --keep-images to skip)"

# tap-cares secrets mount — flag real per-session secrets that would be lost.
# A symlink target (e.g. ~/tap-secrets/) is preserved because rm -rf doesn't
# follow symlinks; we only warn when files are about to be deleted.
if [[ -L "$WORKTREE/tap_secrets" ]]; then
  info "  Secrets mount:         symlink to $(readlink "$WORKTREE/tap_secrets") (target preserved)"
elif [[ -d "$WORKTREE/tap_secrets" ]]; then
  SECRET_FILE_COUNT="$(find "$WORKTREE/tap_secrets" -name '*.secret.json' -type f 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "$SECRET_FILE_COUNT" -gt 0 ]]; then
    warn "  Secrets mount:         $SECRET_FILE_COUNT *.secret.json file(s) in $WORKTREE/tap_secrets/ WILL BE DELETED"
  fi
fi
echo

# ---------------------------------------------------------------------------
# SAFETY GUARD — refuse to torch unmerged work without explicit consent.
#
# This re-introduces, in deliberately narrowed form, the dirty/unmerged checks
# that req-dev-multisession-teardown-safety deprecated on 2026-04-27. That
# deprecation was right that blocking on *every* dirty worktree — behind a
# single blunt --force everyone reflexively types — just made safety into
# noise. The fix is to separate the two loss vectors and narrow the bypass:
#
#   * Unpushed COMMITS on session/<name> are real, hard-to-recover work
#     (branch -D makes them unreachable). HARD STOP. --yes does NOT bypass it;
#     only --abandon-unmerged (a flag your fingers don't already know) does.
#   * A merely-dirty worktree is usually transient scratch (mid-debug, failed
#     spawn, SIGKILL during migrate — exactly the 2026-04-27 cases). It does
#     not hard-stop, but it always forces an interactive [y/N] confirm, even
#     under --yes, so a scripted --yes can never silently torch it.
#
# Re-framed 2026-06-30 — see req-dev-multisession-teardown-safety.
# ---------------------------------------------------------------------------
GUARD_BRANCH="session/$SESSION_NAME"
UNPUSHED_COUNT=0
UNPUSHED_LIST=""
DIRTY=0
DIRTY_COUNT=0

# Unpushed commits: only meaningful while the branch ref still exists. The
# commits live in $REPO's object store regardless of whether the worktree is
# still on disk, so check the branch, not the directory.
if git -C "$REPO" rev-parse --verify --quiet "refs/heads/$GUARD_BRANCH" >/dev/null; then
  # Refresh origin/main so "unpushed" is accurate. Offline → compare against
  # last-known origin/main; a stale ref only ever makes MORE commits look
  # unpushed, never fewer, so failing closed here is the safe direction.
  git -C "$REPO" fetch --quiet origin main 2>/dev/null \
    || warn "Could not fetch origin/main; comparing against last-known origin/main."
  if git -C "$REPO" rev-parse --verify --quiet origin/main >/dev/null; then
    UNPUSHED_COUNT="$(git -C "$REPO" rev-list --count "origin/main..$GUARD_BRANCH" 2>/dev/null || echo 0)"
    [[ "$UNPUSHED_COUNT" -gt 0 ]] && \
      UNPUSHED_LIST="$(git -C "$REPO" log --oneline --no-decorate "origin/main..$GUARD_BRANCH" 2>/dev/null)"
  else
    # No origin/main to compare against at all — cannot prove the branch is
    # safe, so treat every commit on it as unpushed (fail closed).
    UNPUSHED_COUNT="$(git -C "$REPO" rev-list --count "$GUARD_BRANCH" 2>/dev/null || echo 0)"
    UNPUSHED_LIST="$(git -C "$REPO" log --oneline --no-decorate "$GUARD_BRANCH" 2>/dev/null | head -20)"
  fi
fi

# Dirty worktree: only if the directory is actually a live git worktree.
if [[ -d "$WORKTREE" ]] && git -C "$WORKTREE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  DIRTY_PORCELAIN="$(git -C "$WORKTREE" status --porcelain 2>/dev/null)"
  if [[ -n "$DIRTY_PORCELAIN" ]]; then
    DIRTY=1
    DIRTY_COUNT="$(printf '%s\n' "$DIRTY_PORCELAIN" | wc -l | tr -d ' ')"
  fi
fi

# Hard stop on unpushed commits unless explicitly abandoned.
if [[ "$UNPUSHED_COUNT" -gt 0 && "$ABANDON_UNMERGED" -eq 0 ]]; then
  bold "BLOCKED — '$SESSION_NAME' has $UNPUSHED_COUNT commit(s) not in origin/main"
  err "These commits exist ONLY on $GUARD_BRANCH. Despawn force-deletes the branch"
  err "(git branch -D), making them unreachable — this work would be lost:"
  echo
  printf '%s\n' "$UNPUSHED_LIST" | sed 's/^/      /'
  echo
  err "To keep it (recommended):   cd $WORKTREE && scripts/promote-to-main.sh"
  err "To deliberately discard it: re-run despawn with --abandon-unmerged"
  exit 1
fi

[[ "$UNPUSHED_COUNT" -gt 0 ]] && \
  warn "Abandoning $UNPUSHED_COUNT unmerged commit(s) on $GUARD_BRANCH (--abandon-unmerged)."
[[ "$DIRTY" -eq 1 ]] && \
  warn "Worktree has $DIRTY_COUNT uncommitted change(s); these will be destroyed."

# Clean-state verdict — when there is genuinely nothing to lose, say so in no
# uncertain terms right before the [y/N] prompt, so the confirm is an informed
# "yes, this is safe" rather than a blind one. This is the affirmative twin of
# the BLOCKED / warn paths above: exactly one of them speaks on every run.
if [[ "$UNPUSHED_COUNT" -eq 0 && "$DIRTY" -eq 0 ]]; then
  bold "CLEAN — no work will be lost"
  if git -C "$REPO" rev-parse --verify --quiet "refs/heads/$GUARD_BRANCH" >/dev/null; then
    ok "  Branch $GUARD_BRANCH is fully merged into origin/main (0 unpushed commits)."
  else
    ok "  No $GUARD_BRANCH branch on disk — nothing to abandon."
  fi
  if [[ -d "$WORKTREE" ]] && git -C "$WORKTREE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    ok "  Worktree $WORKTREE has 0 uncommitted changes (git status is clean)."
  else
    ok "  No live worktree at $WORKTREE — no uncommitted files to destroy."
  fi
  ok "  Tearing down disposable infra only: containers, volumes, networks, registry row."
  echo
fi

# A dirty worktree forces an interactive confirm even under --yes.
DO_PROMPT=1
[[ "$ASSUME_YES" -eq 1 ]] && DO_PROMPT=0
if [[ "$DIRTY" -eq 1 && "$DO_PROMPT" -eq 0 ]]; then
  warn "--yes was given, but the worktree has uncommitted changes; requiring confirmation."
  DO_PROMPT=1
fi

if [[ "$DO_PROMPT" -eq 1 ]]; then
  prompt "Permanently delete all of the above? [y/N]"
  read -r ans
  [[ "$ans" =~ ^[Yy] ]] || { info "Aborted."; exit 0; }
fi

# ---------------------------------------------------------------------------
# 1. Stop docker stack (preferring scripts/dc inside the worktree so .env.local
#    is honored; fall back to the project name if dc is unavailable).
# ---------------------------------------------------------------------------
bold "Stopping docker stack"
if [[ -d "$WORKTREE" && -x "$WORKTREE/scripts/dc" ]]; then
  ( cd "$WORKTREE" && scripts/dc down -v --remove-orphans 2>&1 ) || warn "scripts/dc down returned non-zero (may already be down)"
else
  docker compose -p "$PROJECT" down -v --remove-orphans 2>&1 || warn "docker compose down returned non-zero (may already be down)"
fi

# ---------------------------------------------------------------------------
# 2. Belt-and-suspenders volume + network cleanup. If step 1 didn't have a
#    valid .env.local to identify the project, named volumes/networks may
#    still exist.
# ---------------------------------------------------------------------------
bold "Removing residual docker volumes and networks"
volumes_to_rm="$(docker volume ls --filter "name=${PROJECT}_" --format '{{.Name}}')"
if [[ -n "$volumes_to_rm" ]]; then
  echo "$volumes_to_rm" | while read -r v; do
    info "  volume: $v"
    docker volume rm "$v" >/dev/null 2>&1 || warn "    (failed)"
  done
else
  info "  no volumes"
fi
networks_to_rm="$(docker network ls --filter "name=${PROJECT}_" --format '{{.Name}}')"
if [[ -n "$networks_to_rm" ]]; then
  echo "$networks_to_rm" | while read -r n; do
    info "  network: $n"
    docker network rm "$n" >/dev/null 2>&1 || warn "    (failed)"
  done
else
  info "  no networks"
fi

# ---------------------------------------------------------------------------
# 3. Worktree + branch. --force ignores uncommitted files (the
#    user explicitly asked for nuke). If the directory survives somehow
#    (e.g. removed outside git's awareness), rm -rf it.
# ---------------------------------------------------------------------------
bold "Removing worktree and branch"
git -C "$REPO" worktree remove --force "$WORKTREE" 2>/dev/null && info "  worktree removed via git" || info "  worktree not in git's list"
git -C "$REPO" worktree prune 2>/dev/null
if [[ -e "$WORKTREE" ]]; then
  warn "  worktree directory still on disk; removing forcibly"
  rm -rf "$WORKTREE" && info "  $WORKTREE removed"
fi
git -C "$REPO" branch -D "session/$SESSION_NAME" 2>/dev/null && info "  branch deleted" || info "  branch not present"

# ---------------------------------------------------------------------------
# 5. Registry row.
# ---------------------------------------------------------------------------
bold "Removing registry row"
if [[ -f "$REGISTRY" ]]; then
  if grep -qE "^${SESSION_NAME} " "$REGISTRY"; then
    sed -i.bak "/^${SESSION_NAME} /d" "$REGISTRY" && rm -f "$REGISTRY.bak"
    info "  row for '$SESSION_NAME' removed"
  else
    info "  no row for '$SESSION_NAME' (was probably never recorded)"
  fi
else
  info "  no registry file"
fi

# ---------------------------------------------------------------------------
# 6. Optional: purge the images this session resolved to (captured above,
#    before the worktree went away) so the next spawn re-pulls or rebuilds
#    from scratch — the "poisoned image cache" escape hatch. `docker rmi`
#    without -f: an image another live session's container holds is refused,
#    which is the right outcome (that session keeps working; this one is
#    gone either way). Runtime Python state lives in compose volumes and is
#    removed by `down -v` / residual volume cleanup above. A tag removed here
#    whose image ID is still referenced elsewhere merely untags; step 7's
#    prune sweeps whatever becomes dangling.
# ---------------------------------------------------------------------------
if [[ "$PURGE_IMAGE" -eq 1 ]]; then
  bold "Purging this session's images"
  if [[ -n "$PURGE_REFS" ]]; then
    while read -r img; do
      [[ -n "$img" ]] || continue
      if rmi_out="$(timeout 60 docker rmi "$img" 2>&1)"; then
        info "  removed: $img"
      else
        warn "  kept $img: ${rmi_out##*$'\n'}"
      fi
    done <<<"$PURGE_REFS"
  else
    info "  nothing resolved — no images to purge"
  fi
fi

# ---------------------------------------------------------------------------
# 7. Image hygiene (tap#271). Runs AFTER the worktree is gone so this session
#    no longer contributes to the keep-set; prune-images derives what is still
#    referenced from every remaining worktree and never touches volumes.
#    Uses the primary checkout's copy (this script's $REPO), like every other
#    step here.
# ---------------------------------------------------------------------------
if [[ "$KEEP_IMAGES" -eq 0 ]]; then
  bold "Reclaiming superseded images"
  if [[ -x "$REPO/scripts/prune-images" ]]; then
    "$REPO/scripts/prune-images" || warn "prune-images returned non-zero (best-effort; run scripts/prune-images by hand)"
  else
    warn "  $REPO/scripts/prune-images not found — skipped"
  fi
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
bold "Despawn complete for '$SESSION_NAME'"
echo
info "Verification (everything below should be empty / 'no output'):"
info "  docker compose -p $PROJECT ps -a"
info "  docker volume ls | grep ${PROJECT}_"
info "  ls $WORKTREE 2>&1 | head"
info "  git -C $REPO worktree list | grep tap-sessions/$SESSION_NAME"
info "  grep '^$SESSION_NAME ' $REGISTRY"
echo
