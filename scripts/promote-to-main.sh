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
      # The generated traceability report is a KNOWN conflict magnet (every
      # session regenerates it; aggregates + sorted tables collide even for
      # disjoint work — bit three promotes in one day, 2026-08-24). Its
      # generated blocks carry zero authored content and their INPUTS (spec
      # ACIDs + markers) merged cleanly, so regenerate-on-the-merged-tree IS
      # the correct merge — computed by the generator, not by git. The commit
      # below CONCLUDES the in-progress merge (MERGE_HEAD present), so it is
      # always creatable, even byte-identical to main's copy (zero-drift case).
      #
      # Trust note (AI-review disposition, PR #120): the syncs execute the
      # merged branch's code in the web container — no NEW privilege: the local
      # gates below already execute that same branch's code (pytest IS
      # arbitrary execution) for a maintainer promoting their own session.
      # scripts/dc bind-mounts this worktree at /app, so regen sees the merged
      # tree, never image contents.
      GEN_REPORT="specs/spec-tap-requirement-traceability.md"
      CONFLICTS="$(git diff --name-only --diff-filter=U)"
      # Exact single-path test: multiple unmerged paths yield a multiline
      # string that cannot equal the one filename. The marker gate self-disarms
      # this path once fragmentation moves the generated blocks out of the
      # spec: a conflict there WITHOUT markers is an authored-prose conflict,
      # where --theirs would destroy session edits — that goes to a human.
      if [[ "$CONFLICTS" == "$GEN_REPORT" ]] \
         && git show ":3:$GEN_REPORT" 2>/dev/null | grep -q "BEGIN GENERATED"; then
        info "Sole conflict is the generated traceability report — auto-resolving by regeneration..."
        git checkout --theirs "$GEN_REPORT"
        git add "$GEN_REPORT"
        if scripts/dc exec -T web uv run python manage.py guards --sync-evidence >/dev/null 2>&1 \
           && scripts/dc exec -T web uv run python manage.py guards --sync-accounting >/dev/null 2>&1; then
          # Stage the DOCUMENTED generated write-set (report + the per-spec
          # fragment dir sam-dev's fragmentation introduces), then fail closed
          # on any write outside it and on any surviving unmerged path — regen
          # side effects must never ride a merge commit unexamined.
          git add "$GEN_REPORT" 2>/dev/null || true
          [[ -d specs/traceability ]] && git add specs/traceability 2>/dev/null
          STRAY="$(git status --porcelain | grep -v -E "^[AMRD ]{2} (specs/spec-tap-requirement-traceability\.md|specs/traceability/)" | grep -v "^??" || true)"
          if [[ -n "$STRAY" ]] || git diff --name-only --diff-filter=U | grep -q .; then
            git merge --abort 2>/dev/null || true
            fail "Regeneration touched paths outside the documented generated set (or left unmerged paths): $STRAY — resolve manually on $BRANCH, then re-run."
          fi
          git commit --no-edit >/dev/null || {
            git merge --abort 2>/dev/null || true
            fail "Auto-resolve commit failed. Resolve manually on $BRANCH, then re-run."
          }
          info "Regenerated on the merged tree; merge committed."
        else
          git merge --abort 2>/dev/null || true
          fail "Regeneration failed (web container up?). Resolve manually on $BRANCH, then re-run."
        fi
      else
        git merge --abort 2>/dev/null || true
        fail "Merge conflicted beyond the generated-report auto-resolve case. Aborted. Resolve manually on $BRANCH, commit, then re-run."
      fi
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

      # TITLE, the half scripts/promote-pr-body does not cover: the body is derived
      # from the diff, but the title is what a reviewer sees in a list of six PRs and
      # what survives in `git log --oneline` forever. "promote: <session> → main"
      # names the mechanism, not the change (CONTRIBUTING.md § Pull Requests). Derive
      # it where the branch says one thing; say so loudly where it does not.
      # bash 3.2 on macOS — no mapfile/readarray.
      # Session attribution is MANDATORY in every PR title (spec-dev-multisession.md
      # § Session attribution, req-dev-multisession-push-workflow): multi-session
      # traffic on origin/main must stay attributable at a glance. The native promote
      # form carries it; a derived subject does not, so the derived cases append the
      # `[via <session>]` suffix — from scripts/pr-via, DERIVED never hand-typed.
      _n="$(git log --no-merges --oneline "origin/main..$BRANCH" | wc -l | tr -d ' ')"
      _via="$(scripts/pr-via 2>/dev/null || printf '[via %s]' "$SESSION")"
      if [[ -n "${PROMOTE_TITLE:-}" ]]; then
        PR_TITLE="$PROMOTE_TITLE"
        [[ "$PR_TITLE" == *"[via "* ]] || PR_TITLE="$PR_TITLE $_via"
      elif [[ "$_n" -eq 1 ]]; then
        PR_TITLE="$(git log --no-merges --format=%s -1 "origin/main..$BRANCH") $_via"
      else
        PR_TITLE="promote: $SESSION → main — $_n commits, RETITLE ME"
        warn "Promote PR title is auto-derived from $_n commits and says nothing useful."
        warn "Retitle it (gh pr edit <n> --title ...) or set PROMOTE_TITLE next time."
      fi

      gh pr create --head "$BRANCH" --base main \
        --title "$PR_TITLE" \
        --body "Session promote via scripts/promote-to-main.sh (PR flow). Tip: $TIP. Local fast lane runs promote-side; the required 'gate' check (test_all lane + cold-boot + lean-boot CI jobs) decides the landing. Merge is armed only after local green." \
        >/dev/null 2>&1 || true
      PR_NUM="$(gh pr list --head "$BRANCH" --base main --state open --json number -q '.[0].number' 2>/dev/null || true)"
      [[ -n "$PR_NUM" && "$PR_NUM" != "null" ]] || fail "Could not create/locate the promote PR for $BRANCH."
      info "Opened promote PR #$PR_NUM."
    fi

    # Derived PR body, regenerated EVERY run — a promote whose body says nothing
    # about its contents defeats every reviewer reading it (the cover-story
    # finding human + AI seats made independently across #103/#108/#111/#115).
    # scripts/promote-pr-body supersedes the inline commit-subjects block that
    # landed via #117 (subjects + sensitivity buckets + RIDs + full narrative;
    # --body-file retires the backtick-substitution hazard). FAIL-CLOSED (the
    # AI-review call on #120): the approver reads the body, so a stale body is
    # a misinformed approval — and a gh outage here dooms the arm/poll below
    # anyway; re-running is cheap. mktemp + trap: no predictable /tmp path.
    PROMOTE_BODY_TMP="$(mktemp "${TMPDIR:-/tmp}/promote-body.XXXXXX")" || fail "mktemp failed."
    trap 'rm -f "$PROMOTE_BODY_TMP"' EXIT
    python3 scripts/promote-pr-body origin/main > "$PROMOTE_BODY_TMP" \
      || fail "PR body derivation failed — fix scripts/promote-pr-body (an undeclared promote is the failure class this exists to kill)."
    gh pr edit "$PR_NUM" --body-file "$PROMOTE_BODY_TMP" >/dev/null \
      || fail "PR body publication failed — not proceeding against a stale declaration. Re-run to retry."

    if ! run_local_gates fast; then
      warn "Local gates RED — auto-merge stays DISARMED; PR #$PR_NUM remains open (server checks continue, nothing can land)."
      fail "Local gates RED — aborting promote. origin/main is NOT advanced. Fix and re-run (same PR updates)."
    fi

    # FINALIZE: local green → arm. Both authorities must now be green to land.
    info "Local gates GREEN — arming auto-merge (merge commit) on PR #$PR_NUM ..."
    if ! gh pr merge "$PR_NUM" --auto --merge >/dev/null 2>&1; then
      warn "Could not arm auto-merge (setting/API hiccup) — falling back to poll-and-merge."
    fi

    # ---- AI-review triage, wired into the workflow that creates its window ----
    # The org ruleset reviews every PR ~1-3 min after open; this promote then waits
    # ~10 min for the gate. scripts/pr-review-triage was built for exactly that window
    # (see its header) but was invoked only by convention — prose in CLAUDE.md — so it
    # ran when the operator remembered and silently did not when they didn't. PR #181
    # is the worked example: a CODEOWNERS entry naming an account without write access
    # shipped as inert, and the reviewer had said so. A step that only happens when
    # remembered is not a step. Running it HERE makes seeing the feedback a property of
    # promoting rather than of memory.
    #
    # Never fatal: the gates decide whether the change LANDS; this decides whether
    # anyone has READ the commentary. A reviewer outage must not red a green promote.
    # Findings are re-stated at the end of the run (see TRIAGE_STATUS below) because
    # the wait loop's output buries anything printed here — the tail is what gets read.
    # mktemp + trap matching the PROMOTE_BODY_TMP idiom 30 lines above — same file,
    # same convention. The trap names BOTH temp files rather than adding a second EXIT
    # trap, because a second `trap ... EXIT` REPLACES the first and would silently leak
    # the PR body file; `${x:-}` keeps it safe wherever only one is set.
    bold "AI-review triage for PR #$PR_NUM"
    TRIAGE_OUT="$(mktemp "${TMPDIR:-/tmp}/promote-triage.XXXXXX")" || fail "mktemp failed."
    trap 'rm -f "${PROMOTE_BODY_TMP:-}" "${TRIAGE_OUT:-}"' EXIT
    # `tee`, not a plain redirect: the --wait poll can sit silent for up to 3 minutes,
    # and a promote that looks hung is a promote someone ^Cs. pipefail (set at the top)
    # keeps the pipeline's status the triage script's, not tee's.
    if scripts/pr-review-triage "$PR_NUM" --wait 2>&1 | tee "$TRIAGE_OUT"; then
      # Count inline findings only. Deliberately NOT a clean/dirty verdict: Copilot
      # hides suppressed findings inside the review SUMMARY, so a zero here is not
      # "nothing to read" — claiming otherwise would rebuild the false confidence
      # this block exists to prevent.
      TRIAGE_INLINE="$(grep -cE '^── ' "$TRIAGE_OUT" || true)"
      TRIAGE_STATUS="reviewed"
    else
      warn "No AI review arrived within the wait window (reviewer slow or offline)."
      TRIAGE_INLINE="0"
      TRIAGE_STATUS="absent"
    fi
    rm -f "$TRIAGE_OUT"

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

# The triage obligation, re-stated where it actually gets read: this line is the LAST
# thing a long promote prints, so a tail-reader cannot walk past it (the failure this
# whole block exists to fix). Never a verdict — always an obligation.
case "${TRIAGE_STATUS:-}" in
  reviewed)
    info "AI review: ${TRIAGE_INLINE:-0} inline finding(s) printed above, plus review SUMMARIES (Copilot hides suppressed findings there). Read both before calling this done; fix-worthy findings ride a follow-up PR onto this branch."
    ;;
  absent)
    warn "AI review: none had arrived when this run checked. Triage before calling this done: scripts/pr-review-triage ${PR_NUM:-<pr>}"
    ;;
esac
