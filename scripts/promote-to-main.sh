#!/usr/bin/env bash
# scripts/promote-to-main.sh — promote the current session worktree's commits
# to origin/main.
#
# Implements req-dev-multisession-promote-script (specs/spec-dev-multisession.md)
# which codifies steps 1–4 of req-dev-multisession-push-workflow as one
# invocation:
#   1. Fetch origin/main.
#   2. Pre-push merge of origin/main into the session branch (surfaces real
#      conflicts in the session worktree, the right place to resolve them).
#   3. PR promote (req-cicd-branch-protection PR flow): push the session branch,
#      open/update the promote PR, run the local fast lane in the shadow of the
#      server-side checks, then ARM auto-merge only after local green — the
#      server (required `gate` check incl. the CI cold-boot/lean-boot jobs)
#      decides the landing. Direct atomic push survives ONLY as the
#      bootstrap/skip-hatch path (cloud gate inactive), where it rides the
#      admin bypass loudly.
#   4. Sync the primary worktree (git -C ~/tap-sessions/main pull --ff-only)
#      so the local main ref the next spawn branches from is current.
#
# Companion: scripts/promote-all-sessions.sh iterates the registry and calls
# this script in each worktree in turn.
#
# Usage:
#   scripts/promote-to-main.sh           # promote this session
#   scripts/promote-to-main.sh --dry-run # report what would happen; no writes
#

set -euo pipefail

bold() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }
info() { printf "    %s\n" "$1"; }
warn() { printf "\033[33m    %s\033[0m\n" "$1"; }
fail() { printf "\033[31m    ERROR: %s\033[0m\n" "$1" >&2; exit 1; }

DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--dry-run) DRY_RUN=1; shift ;;
    -h|--help)
      sed -n '/^# Usage:/,/^# *$/p' "$0" | sed 's/^# //; s/^#//'
      exit 0
      ;;
    -*) fail "Unknown flag: $1" ;;
    *)  fail "Unexpected arg: $1" ;;
  esac
done

# Mirror real git ops vs a "would: ..." log line, depending on --dry-run.
dry() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[dry-run] would: $*"
  else
    "$@"
  fi
}

# Operate on the worktree we were invoked from, not the script's location —
# the orchestrator cd's into each session before calling us.
REPO="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "Not inside a git worktree."
cd "$REPO"

# Sanity: must be on a session/<name> branch
# (req-dev-multisession-push-workflow-1 — never edit on main).
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
case "$BRANCH" in
  session/*) SESSION="${BRANCH#session/}" ;;
  main)      fail "On 'main' — promote from a session worktree, not the main worktree." ;;
  HEAD)      fail "Detached HEAD. Checkout the session branch first." ;;
  *)         fail "Unexpected branch '$BRANCH'. Expected 'session/<name>'." ;;
esac

# Sanity: clean working tree. Merge would refuse anyway, but a clear message
# is friendlier than git's default. Untracked files are fine (e.g. .env.local,
# .dev-credentials) — only staged/unstaged changes block us.
if ! git diff --quiet || ! git diff --cached --quiet; then
  fail "Working tree is not clean. Commit or stash before promoting."
fi

bold "Promoting $BRANCH → origin/main"

# ---------------------------------------------------------------------------
# Step 1: fetch.
# ---------------------------------------------------------------------------
info "Fetching origin/main..."
dry git fetch origin main

# Snapshot how this branch sits against origin/main.
AHEAD="$(git rev-list --count origin/main..HEAD 2>/dev/null || echo "0")"
BEHIND="$(git rev-list --count HEAD..origin/main 2>/dev/null || echo "0")"
info "  ahead of origin/main:  $AHEAD"
info "  behind origin/main:    $BEHIND"

if [[ "$AHEAD" -eq 0 ]]; then
  info "Nothing to push. Done."
  exit 0
fi

# ---------------------------------------------------------------------------
# Step 2: pre-push merge (req-dev-multisession-push-workflow-2).
# Skip when not behind to avoid a redundant empty merge commit.
# ---------------------------------------------------------------------------
if [[ "$BEHIND" -gt 0 ]]; then
  info "Pre-push merge: merging origin/main into $BRANCH ($BEHIND commits behind)..."
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[dry-run] would: git merge --no-edit origin/main"
  else
    if ! git merge --no-edit origin/main; then
      git merge --abort 2>/dev/null || true
      fail "Merge conflicted. Aborted. Resolve manually on $BRANCH, commit, then re-run."
    fi
  fi
fi

# ---------------------------------------------------------------------------
# Step 2.5 + 2.6: parallelized validation gate (req-dev-multisession-promote-gate,
# req-dev-multisession-ci-gate, req-dev-validation-product-line-lanes-6).
#
# Two validation surfaces gate the push, and they OVERLAP in wall-clock:
#
#   * CLOUD (Step 2.6) — the product-lines `test_all` union lane (free GitHub
#     runners): the all-plugins authority (full plugin set, real image). Same
#     suite the local lane would run, but definitive. Dispatched FIRST so it runs
#     while the local gates run underneath it.
#
#   * LOCAL (Step 2.5) — cold-boot gate + lean-boot gate (structural checks the
#     cloud lane does NOT do) plus a pytest lane. When the cloud gate is ACTIVE it
#     owns the full corpus, so the local pytest is only the FAST fail-fast subset
#     (`scripts/test --fast`, no gryphon corpus — deferred to the cloud). When the
#     cloud gate is INACTIVE (bootstrap / skip-hatch), the local lane is the SOLE
#     authority and runs the FULL corpus (`scripts/test --gryphon`).
#
# Wall-clock is max(local, cloud), not sum: the cloud run is kicked off, the local
# gates run in its shadow, then we JOIN on the cloud run's conclusion. A local red
# CANCELS the in-flight cloud run (saves compute). Both green ⇒ push. Either red, a
# lost-contact timeout, or an un-runnable cloud gate ⇒ abort with origin/main NOT
# advanced (fail-closed).
#
# The cloud lane runs against a THROWAWAY ref (_ci-gate/<session>), so neither
# origin/main nor origin/session/<name> moves before validation — only Step 3's
# atomic push advances them.
#
# Bootstrap: workflow_dispatch only works once the gate workflow is on origin/main;
# until then the cloud gate is SKIPPED (detected via git) and the local FULL lane is
# the sole authority for that one promote. Escape hatches: TAP_PROMOTE_CI_WORKFLOW=
# all-plugins.yml (free-runner fallback) and TAP_PROMOTE_SKIP_CI_GATE=1 (skip cloud;
# local FULL lane is authority). When the cloud gate SHOULD run, gh with the
# 'workflow' scope is REQUIRED — a missing gh fails closed rather than silently
# downgrading to a possibly-focused local stack.
# ---------------------------------------------------------------------------
CI_WORKFLOW="${TAP_PROMOTE_CI_WORKFLOW:-product-lines.yml}"
# product-lines.yml is a per-line matrix; the promote gate runs only the all-plugins
# `test_all` union lane. all-plugins.yml takes no inputs.
CI_DISPATCH_ARGS=()
[[ "$CI_WORKFLOW" == "product-lines.yml" ]] && CI_DISPATCH_ARGS=(-f line=test_all)

# Run the local validation surfaces in order. $1 = "fast" | "full". Called in a
# condition (`if ! run_local_gates ...`), so `set -e` is relaxed inside the body —
# every step handles its own failure with an explicit `|| return 1`.
run_local_gates() {
  local mode="$1"
  # DCO sign-off trailers (req-cicd-dco-signoff) — host-side and cheap, so it runs
  # first, before the stack even matters. ENFORCING since 2026-08-12 (CONTRIBUTING.md
  # + DCO landed as approved policy): a missing trailer aborts the promote. The
  # enforcing default lives in check-dco itself, not in an env var here, so an
  # ad-hoc run gives the same verdict. Merge + bot commits exempt (the promote's
  # pre-push merge stays clean).
  info "DCO sign-off trailer check (scripts/check-dco; enforcing — CONTRIBUTING.md is policy) ..."
  scripts/check-dco || return 1
  # Change-tier shortcut (req-dev-validation-product-line-lanes-7): a docs-tier
  # diff (scripts/change-tier — inert documentation only) cannot red pytest or
  # boot, and the server gate applies the same tier logic to its own jobs. The
  # shortcut applies ONLY in `fast` mode — when the cloud gate is inactive
  # (`full`), local is the sole authority and runs everything regardless of tier.
  if [[ "$mode" == "fast" && "$(scripts/change-tier origin/main)" == "docs" ]]; then
    info "Docs-tier diff — local pytest + boot gates skipped (the server gate mirrors the tier; check-dco ran above, secret-scan + dco run on the PR)."
    return 0
  fi
  if ! scripts/dc ps --status running --services 2>/dev/null | grep -qx web; then
    warn "Validation gate requires this session's stack to be up (scripts/dc up -d)."
    return 1
  fi
  # Clear mypy's incremental cache — it goes stale across the pre-push merge when a
  # merge moves/deletes a module (content-hash invalidation misses the tree-structure
  # change → false import-untyped in the mypy guard). The .githooks/post-merge hook
  # also clears it; this is the hook-independent fail-safe on the branch that advances
  # origin/main. (Standardizes the fix for the github_core false red on tip a94bc98c.)
  info "Clearing mypy incremental cache (post-merge staleness guard) ..."
  scripts/dc exec -T web sh -c 'rm -rf /app/.mypy_cache' 2>/dev/null || true
  if [[ "$mode" == "full" ]]; then
    # Sole authority: run the FULL corpus. --gryphon forces the gryphon corpus ON
    # regardless of the diff (req-dev-validation-suite-tiers-4).
    info "Local pytest — FULL lane (scripts/test --gryphon; cloud gate inactive → sole authority) ..."
    scripts/test --gryphon || return 1
  else
    # Cloud owns the full corpus incl. gryphon; local runs the fast fail-fast subset.
    info "Local pytest — FAST lane (scripts/test --fast; cloud gate owns the full corpus incl. gryphon) ..."
    scripts/test --fast || return 1
  fi
  # Boot gates: since 2026-08-10 the cold-boot + lean-boot gates run as REQUIRED
  # CI jobs (product-lines.yml, aggregated into `gate`) — the server owns boot
  # truth, so the local copies are OPTIONAL fast feedback, not authorities. In
  # `full` mode (cloud inactive → local is the sole authority) they still run;
  # in `fast` mode they are skipped unless TAP_PROMOTE_LOCAL_BOOT_GATES=1.
  if [[ "$mode" == "full" || "${TAP_PROMOTE_LOCAL_BOOT_GATES:-0}" == "1" ]]; then
    info "Local pytest GREEN. Cold-boot gate (scripts/gate; skips on a focused stack) ..."
    scripts/gate --skip-if-not-installable || return 1
    info "Cold-boot gate GREEN. Lean-boot independence gate (scripts/gate-lean) ..."
    scripts/gate-lean || return 1
    info "Local gates GREEN (pytest + cold-boot + lean-boot)."
  else
    info "Local pytest GREEN. Boot gates are CI-owned (cold-boot + lean-boot jobs, REQUIRED via gate); TAP_PROMOTE_LOCAL_BOOT_GATES=1 also runs them here."
  fi
  return 0
}

if [[ "$DRY_RUN" -eq 1 ]]; then
  info "[dry-run] would: push $BRANCH, open/update the promote PR, run the local fast lane in the shadow of the server checks (product-lines: test_all lane + cold-boot + lean-boot + api-fuzz), then arm auto-merge and wait for the server to land it. Bootstrap/skip-hatch would run the FULL local lane and direct-push (admin bypass, loud)."
else
  # --- Decide the disposition: PR flow (default) vs direct (bootstrap/skip). ---
  CLOUD_ACTIVE=0
  if ! git cat-file -e "origin/main:.github/workflows/$CI_WORKFLOW" 2>/dev/null; then
    warn "Gate workflow ($CI_WORKFLOW) not yet on origin/main — bootstrap promote: local FULL lane + direct push."
  elif [[ "${TAP_PROMOTE_SKIP_CI_GATE:-0}" == "1" ]]; then
    warn "TAP_PROMOTE_SKIP_CI_GATE=1 — local FULL lane + direct push (admin bypass, loud). Only when the full set is known green another way."
  else
    command -v gh >/dev/null 2>&1 || fail "PR promote requires gh. Install+auth gh, or set TAP_PROMOTE_SKIP_CI_GATE=1 if the full set is validated another way."
    gh repo view --json nameWithOwner -q .nameWithOwner >/dev/null 2>&1 || fail "gh could not resolve the repo (auth?)."
    CLOUD_ACTIVE=1
  fi

  if [[ "$CLOUD_ACTIVE" -eq 0 ]]; then
    # --- Direct path (bootstrap / skip-hatch): local FULL lane is sole authority. ---
    bold "Development-validation gate on the merged tree (local FULL lane — server gate inactive/skipped)"
    run_local_gates full || fail "Local validation RED — aborting promote. origin/main is NOT advanced (req-dev-validation-promote-hook-2). Fix and re-run."
    bold "Direct atomic push: origin/main and origin/$BRANCH (bypass path)"
    PUSH_OUT="$(git push --atomic origin "$BRANCH:main" "$BRANCH:$BRANCH" 2>&1)" \
      || { printf '%s\n' "$PUSH_OUT"; fail "Atomic push failed."; }
    printf '%s\n' "$PUSH_OUT"
    if grep -q "Bypassed rule violations" <<<"$PUSH_OUT"; then
      warn "ADMIN BYPASS carried this direct push (expected on the bootstrap/skip path — req-cicd-branch-protection)."
    fi
  else
    # --- PR flow: the server's required checks (incl. CI boot gates) decide. ---
    bold "PR promote: $BRANCH → PR → server gate → auto-merge"

    # Re-promote safety FIRST: auto-merge arming persists across new pushes, so a
    # stale arm from an earlier attempt would let the server merge fresh commits
    # on cloud-green BEFORE our local gates run. Disarm before pushing anything.
    PR_NUM="$(gh pr list --head "$BRANCH" --base main --state open --json number -q '.[0].number' 2>/dev/null || true)"
    if [[ -n "$PR_NUM" && "$PR_NUM" != "null" ]]; then
      gh pr merge --disable-auto "$PR_NUM" >/dev/null 2>&1 || true
      info "Existing promote PR #$PR_NUM — auto-merge disarmed until this run's local gates pass."
    fi

    info "Pushing $BRANCH (server checks start now; local gates run in their shadow) ..."
    git push --force-with-lease origin "$BRANCH:$BRANCH" >/dev/null 2>&1 || fail "Could not push $BRANCH."

    if [[ -z "$PR_NUM" || "$PR_NUM" == "null" ]]; then
      TIP="$(git rev-parse --short HEAD)"
      gh pr create --head "$BRANCH" --base main \
        --title "promote: $SESSION → main" \
        --body "Session promote via scripts/promote-to-main.sh (PR flow). Tip: $TIP. Local fast lane runs promote-side; the required 'gate' check (test_all lane + cold-boot + lean-boot CI jobs) decides the landing. Merge is armed only after local green." \
        >/dev/null 2>&1 || true
      PR_NUM="$(gh pr list --head "$BRANCH" --base main --state open --json number -q '.[0].number' 2>/dev/null || true)"
      [[ -n "$PR_NUM" && "$PR_NUM" != "null" ]] || fail "Could not create/locate the promote PR for $BRANCH."
      info "Opened promote PR #$PR_NUM."
    fi

    # The PR body carries the session's commit subjects, refreshed every run — a
    # promote whose body says nothing about its contents defeats every reviewer
    # reading it (human and AI seats both flagged the boilerplate bodies on
    # PR #108/#111 as an undisclosed-plumbing-change smell). Plain single quotes
    # around 'gate': a markdown backtick in this double-quoted context is live
    # command substitution (learned the hard way).
    PROMOTE_SUBJECTS="$(git log --format='- %h %s' origin/main..HEAD -- 2>/dev/null | grep -v "^- [0-9a-f]* Merge " | head -30 || true)"
    gh pr edit "$PR_NUM" --body "Session promote via scripts/promote-to-main.sh (PR flow). Local fast lane runs promote-side; the required 'gate' check (test_all lane + cold-boot + lean-boot CI jobs) decides the landing. Merge is armed only after local green.

Commits in this promote (excluding sync merges):
$PROMOTE_SUBJECTS" >/dev/null 2>&1 \
      || warn "Could not refresh PR #$PR_NUM body with commit subjects (cosmetic; continuing)."

    if ! run_local_gates fast; then
      warn "Local gates RED — auto-merge stays DISARMED; PR #$PR_NUM remains open (server checks continue, nothing can land)."
      fail "Local gates RED — aborting promote. origin/main is NOT advanced. Fix and re-run (same PR updates)."
    fi

    # FINALIZE: local green → arm. Both authorities must now be green to land.
    info "Local gates GREEN — arming auto-merge (merge commit) on PR #$PR_NUM ..."
    if ! gh pr merge "$PR_NUM" --auto --merge >/dev/null 2>&1; then
      warn "Could not arm auto-merge (setting/API hiccup) — falling back to poll-and-merge."
    fi

    info "Waiting for the server to land PR #$PR_NUM (required checks: gate = test_all lane + cold-boot + lean-boot) ..."
    MERGED=0
    _pr_errs=0
    for _i in $(seq 1 240); do          # 240 * 15s = 60 min ceiling
      _line="$(gh pr view "$PR_NUM" --json state,mergeStateStatus -q '.state + "|" + .mergeStateStatus' 2>/dev/null || true)"
      if [[ -z "$_line" ]]; then
        _pr_errs=$((_pr_errs + 1))
        [[ "$_pr_errs" -ge 20 ]] && fail "Lost contact with GitHub polling PR #$PR_NUM. Auto-merge stays armed — it lands server-side when checks pass. Inspect: gh pr view $PR_NUM"
        sleep 15; continue
      fi
      _pr_errs=0
      case "${_line%%|*}" in
        MERGED) MERGED=1; break ;;
        CLOSED) fail "PR #$PR_NUM was closed without merging — aborting. Inspect: gh pr view $PR_NUM" ;;
      esac
      # Try the fallback merge whenever the server reports CLEAN (auto-merge normally beats us to it).
      if [[ "${_line##*|}" == "CLEAN" ]]; then
        gh pr merge "$PR_NUM" --merge >/dev/null 2>&1 || true
      fi
      [[ $((_i % 8)) -eq 0 ]] && info "  still waiting (state=${_line%%|*}, checks=${_line##*|}) ..."
      sleep 15
    done
    if [[ "$MERGED" -ne 1 ]]; then
      fail "PR #$PR_NUM did not merge within 60 min. Auto-merge is ARMED — it lands server-side when checks pass; origin/main advances then. Inspect: gh pr checks $PR_NUM"
    fi
    info "PR #$PR_NUM MERGED — origin/main advanced by the server on green checks."
    git fetch origin main >/dev/null 2>&1 || true
  fi
fi

# ---------------------------------------------------------------------------
# Step 4: sync the primary worktree (req-dev-multisession-push-workflow-4).
# Load-bearing for spawn-session.sh: the next spawn branches from local main.
# ---------------------------------------------------------------------------
bold "Syncing primary worktree"
MAIN_WORKTREE="$HOME/tap-sessions/main"
if [[ -d "$MAIN_WORKTREE/.git" || -f "$MAIN_WORKTREE/.git" ]]; then
  dry git -C "$MAIN_WORKTREE" pull --ff-only origin main
else
  warn "Main worktree at $MAIN_WORKTREE not found; skipped."
  warn "If this is a non-standard checkout, advance local main manually before the next spawn."
fi

info "Promoted '$SESSION' to origin/main."
