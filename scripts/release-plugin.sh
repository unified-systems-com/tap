#!/usr/bin/env bash
# scripts/release-plugin.sh — release ONE evicted plugin in one command.
#
# Implements req-dev-workspace-release (specs/spec-dev-plugin-workspace.md): the
# plugin-repo analogue of promote-to-main.sh (which is monorepo-only). Closes the
# hand-typed-release drift gap (plugin-release-gap-no-promote-equivalent) where an
# evicted plugin's release was a hand-typed push + tag + boot-rev bump that silently
# drifted if the tag step was skipped.
#
# Given a plugin checked out editable in a workspace (spawn --dev-plugins), it:
#   1. Pre-release guard — refuse to release red (req-dev-workspace-release-2):
#      a. conformance: `validate_plugin --strict` (the same gate the reusable CI runs);
#      b. the plugin's own tests: `pytest --pyargs tap_plugin.<slug>` (needs the harness up).
#   2. PR-based landing + immutable tag (req-dev-workspace-release-4/-5): push the plugin
#      repo's commits to a release/<tag> branch, open a PR to the default branch, merge it
#      with a MERGE COMMIT (so the released commit is an ancestor of the default branch),
#      then create the immutable `v<version>` tag. Never direct-pushes a branch — the tag
#      push is the only direct ref write, and it targets refs/tags only, which branch
#      rulesets do not gate. Refuses if the tag already exists.
#   3. Substrate-first pin bump (req-dev-workspace-release-1/-3): advance every consuming
#      boot profile's pinned rev for this slug to `v<version>` (tap.plugin_release). Run
#      release on the substrate BEFORE its consumers so dependency order holds.
#
# Usage:
#   scripts/release-plugin.sh <slug> <version>
#   scripts/release-plugin.sh <slug> <version> --dry-run       # report; no push/tag/write
#   scripts/release-plugin.sh <slug> <version> --repo-dir DIR  # plugin checkout (default: _dev-plugins/<slug>)
#   scripts/release-plugin.sh <slug> <version> --skip-tests    # conformance only (e.g. tests already green in CI)
#   scripts/release-plugin.sh <slug> <version> --boot-dir DIR  # profiles to bump (default: boot)
#
set -euo pipefail

bold() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }
info() { printf "    %s\n" "$1"; }
warn() { printf "\033[33m    %s\033[0m\n" "$1"; }
fail() { printf "\033[31m    ERROR: %s\033[0m\n" "$1" >&2; exit 1; }

SLUG=""
VERSION=""
REPO_DIR=""
BOOT_DIR="boot"
DRY_RUN=0
SKIP_TESTS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--dry-run) DRY_RUN=1; shift ;;
    --skip-tests) SKIP_TESTS=1; shift ;;
    --repo-dir)   REPO_DIR="${2:?--repo-dir needs a path}"; shift 2 ;;
    --repo-dir=*) REPO_DIR="${1#*=}"; shift ;;
    --boot-dir)   BOOT_DIR="${2:?--boot-dir needs a path}"; shift 2 ;;
    --boot-dir=*) BOOT_DIR="${1#*=}"; shift ;;
    -h|--help)
      sed -n '/^# Usage:/,/^# *$/p' "$0" | sed 's/^# //; s/^#//'
      exit 0
      ;;
    -*) fail "Unknown flag: $1" ;;
    *)
      if [[ -z "$SLUG" ]]; then SLUG="$1"
      elif [[ -z "$VERSION" ]]; then VERSION="$1"
      else fail "Unexpected arg: $1"; fi
      shift
      ;;
  esac
done

[[ -n "$SLUG" ]]    || fail "Missing <slug>. Usage: release-plugin.sh <slug> <version>"
[[ -n "$VERSION" ]] || fail "Missing <version>. Usage: release-plugin.sh <slug> <version>"

# Mirror real side-effecting ops vs a "would: ..." line under --dry-run.
dry() {
  if [[ "$DRY_RUN" -eq 1 ]]; then info "[dry-run] would: $*"; else "$@"; fi
}

REPO="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "Not inside a git worktree."
cd "$REPO"

# Normalize + validate the version to its canonical vX.Y.Z tag before doing anything.
TAG="$(python3 - "$VERSION" <<'PY'
import sys
from tap.plugin_release import normalize_tag, PluginReleaseError
try:
    print(normalize_tag(sys.argv[1]))
except PluginReleaseError as exc:
    print(f"error: {exc}", file=sys.stderr); sys.exit(1)
PY
)" || fail "Invalid version '$VERSION' (expected vMAJOR.MINOR.PATCH)."

[[ -n "$REPO_DIR" ]] || REPO_DIR="_dev-plugins/$SLUG"
[[ -d "$REPO_DIR/.git" ]] || fail "Plugin checkout not found at '$REPO_DIR' (a git repo). \
Check it out editable first: spawn --dev-plugins $SLUG, or pass --repo-dir."

# The plugin checkout must live under the harness worktree, so the running `web` container sees
# it at /app/<rel> (the worktree is bind-mounted to /app — that is exactly where a --dev-plugins
# editable install already resolves from). Conformance + tests run IN the container, against the
# plugin's real install environment, not a venv-free host guess.
REPO_DIR_ABS="$(cd "$REPO_DIR" && pwd)"
case "$REPO_DIR_ABS/" in
  "$REPO"/*) REL_REPO_DIR="${REPO_DIR_ABS#"$REPO"/}" ;;
  *) fail "Plugin checkout '$REPO_DIR' is outside the harness worktree ($REPO). \
The workspace expects it under _dev-plugins/<slug> so the container can see it." ;;
esac
CONTAINER_DIR="/app/$REL_REPO_DIR"

bold "Releasing $SLUG $TAG  (repo: $REL_REPO_DIR)"
[[ "$DRY_RUN" -eq 1 ]] && warn "DRY RUN — no push, tag, or profile write will happen."

# ---------------------------------------------------------------------------
# Step 1a: conformance gate (req-dev-workspace-release-2). The exact
# `validate_plugin --strict` the reusable per-repo CI runs — here in-container.
# ---------------------------------------------------------------------------
bold "Conformance gate: validate_plugin --strict"
scripts/dc exec -T web uv run python -m tap_plugins.validate_plugin "$CONTAINER_DIR" --strict \
  || fail "Conformance gate failed for $SLUG — refusing to release. Fix the manifest/layout first."
info "conformance: pass"

# ---------------------------------------------------------------------------
# Step 1b: the plugin's own tests (req-dev-workspace-release-2). Runs against the
# live harness (needs the stack up). Skippable when a green CI already vouched.
# ---------------------------------------------------------------------------
if [[ "$SKIP_TESTS" -eq 1 ]]; then
  warn "Skipping the plugin test suite (--skip-tests). Ensure CI is green before you rely on this release."
else
  bold "Plugin tests: pytest --pyargs tap_plugin.$SLUG"
  # Distinguish "the tests failed" from "there were no tests". pytest exits 5 for
  # NO TESTS COLLECTED, which is a DIFFERENT and more dangerous outcome: it means the
  # release gate ran and asserted nothing. Both refuse, but conflating them reports a
  # plugin with a dead/absent suite as an ordinary test failure and sends the release
  # engineer hunting for a broken test that does not exist. This is exactly how two
  # evicted plugins shipped unrunnable suites for two weeks.
  set +e
  scripts/dc exec -T web uv run pytest --pyargs "tap_plugin.$SLUG"
  pytest_rc=$?
  set -e
  case "$pytest_rc" in
    0) info "tests: pass" ;;
    5) fail "Plugin tests for $SLUG collected ZERO tests — refusing to release.
    The suite is absent, unimportable, or not shipped inside the package. Tests must
    live at tap_plugin/$SLUG/tests/ so they ship in the wheel and '--pyargs' finds
    them; a repo-root tests/ directory is NOT collected by this gate. A green release
    on an empty suite is worse than a red one — it certifies nothing while looking
    like it certified something." ;;
    *) fail "Plugin tests failed for $SLUG (pytest exit $pytest_rc) — refusing to release. (Is the harness up? scripts/dc up -d)" ;;
  esac
fi

# ---------------------------------------------------------------------------
# Step 2: PR-based landing + immutable tag (req-dev-workspace-release-4/-5).
# The release commits reach the default branch through a PR merged with a MERGE
# COMMIT — never a direct branch push. Direct pushes are dead everywhere
# (treat-the-maintainer-as-an-outsider; the org-wide require-PR ruleset rejects
# them), and the merge-commit method keeps the tagged commit an ancestor of the
# default branch. The tag push is the only direct ref write and targets
# refs/tags only, which branch rulesets do not gate. A release is immutable —
# refuse to move an existing tag.
# ---------------------------------------------------------------------------
bold "Land + tag $TAG (PR-based; no direct branch push)"
if git -C "$REPO_DIR" rev-parse -q --verify "refs/tags/$TAG" >/dev/null 2>&1; then
  fail "Tag $TAG already exists locally in $REPO_DIR. A release is immutable — bump the version."
fi
if git -C "$REPO_DIR" ls-remote --exit-code --tags origin "$TAG" >/dev/null 2>&1; then
  fail "Tag $TAG already exists on origin. A release is immutable — bump the version."
fi
if ! git -C "$REPO_DIR" diff --quiet || ! git -C "$REPO_DIR" diff --cached --quiet; then
  fail "Plugin checkout $REPO_DIR has uncommitted changes. Commit them before releasing."
fi
CURRENT_BRANCH="$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD)"
[[ "$CURRENT_BRANCH" != "HEAD" ]] || fail "Plugin checkout is on a detached HEAD — check out a branch before releasing."
# The commit the gates certified — captured NOW, because the post-merge
# fast-forward moves HEAD to the merge commit and the tag must not follow it.
RELEASE_SHA="$(git -C "$REPO_DIR" rev-parse HEAD)"

# gh runs inside the plugin checkout so it resolves the plugin repo, not the harness.
ghp() { (cd "$REPO_DIR" && gh "$@"); }

git -C "$REPO_DIR" fetch origin --quiet
git -C "$REPO_DIR" rev-parse -q --verify "refs/remotes/origin/$CURRENT_BRANCH" >/dev/null 2>&1 \
  || fail "Branch '$CURRENT_BRANCH' does not exist on origin. Release from a branch that exists remotely (normally the default branch)."

AHEAD="$(git -C "$REPO_DIR" rev-list --count "origin/$CURRENT_BRANCH..HEAD")"
if [[ "$AHEAD" -eq 0 ]]; then
  # Everything is already on origin (e.g. landed via an earlier PR) — nothing to
  # merge; the release is just the tag.
  info "No commits ahead of origin/$CURRENT_BRANCH — skipping the release PR, tagging directly."
else
  # NOTE: the branch is release/vX.Y.Z, never bare vX.Y.Z — a branch named exactly
  # like the tag makes every later ref ambiguous.
  RELEASE_BRANCH="release/$TAG"
  if git -C "$REPO_DIR" ls-remote --exit-code --heads origin "$RELEASE_BRANCH" >/dev/null 2>&1; then
    fail "Branch $RELEASE_BRANCH already exists on origin — a previous release attempt left it behind. Inspect and delete it first."
  fi
  command -v gh >/dev/null 2>&1 || fail "gh CLI is required for the PR-based release path."

  bold "Release PR: $RELEASE_BRANCH → $CURRENT_BRANCH ($AHEAD commit(s))"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    info "[dry-run] would: push HEAD to origin/$RELEASE_BRANCH, open a PR onto $CURRENT_BRANCH, merge it with a merge commit (auto-merge fallback + poll), then tag."
  else
    git -C "$REPO_DIR" push origin "HEAD:refs/heads/$RELEASE_BRANCH"
    ghp pr create --head "$RELEASE_BRANCH" --base "$CURRENT_BRANCH" \
      --title "Release $SLUG $TAG" \
      --body "Automated release PR from scripts/release-plugin.sh (req-dev-workspace-release-5). Pre-release gates (validate_plugin --strict$([[ "$SKIP_TESTS" -eq 1 ]] && echo "; tests SKIPPED via --skip-tests" || echo " + plugin test suite")) passed locally." \
      >/dev/null
    PR_NUM="$(ghp pr list --head "$RELEASE_BRANCH" --base "$CURRENT_BRANCH" --state open --json number -q '.[0].number')"
    [[ -n "$PR_NUM" ]] || fail "Opened the release PR but could not resolve its number. Inspect: gh pr list --head $RELEASE_BRANCH"
    info "release PR #$PR_NUM open"

    # Plugin repos carry no CODEOWNERS or required checks (until they hold files that
    # warrant them), so the direct merge normally lands instantly. If rules DO block
    # it, arm auto-merge and poll — and if review is required, that block is the
    # control working, so surface it loudly instead of waiting forever.
    if ! ghp pr merge "$PR_NUM" --merge --delete-branch >/dev/null 2>&1; then
      warn "Direct merge blocked — arming auto-merge and polling (repo rules may require checks or review)."
      ghp pr merge "$PR_NUM" --auto --merge --delete-branch >/dev/null 2>&1 \
        || fail "Could not merge or arm auto-merge on PR #$PR_NUM. Inspect: gh pr view $PR_NUM --repo <plugin-repo>"
      for _i in $(seq 1 60); do
        _state="$(ghp pr view "$PR_NUM" --json state -q .state 2>/dev/null || true)"
        [[ "$_state" == "MERGED" ]] && break
        [[ "$_state" == "CLOSED" ]] && fail "Release PR #$PR_NUM was closed without merging — aborting before the tag."
        sleep 10
      done
      _state="$(ghp pr view "$PR_NUM" --json state -q .state 2>/dev/null || true)"
      [[ "$_state" == "MERGED" ]] || fail "Release PR #$PR_NUM did not merge within 10 min. Auto-merge stays armed; if the repo requires code-owner review, get the approval, let it land, then re-run this release (it will skip the PR and tag directly)."
    fi
    info "release PR #$PR_NUM merged"
    git -C "$REPO_DIR" fetch origin --quiet
    # Local branch is now behind the merge commit; fast-forward so the checkout
    # matches origin. Best-effort — a failure here does not endanger the release.
    git -C "$REPO_DIR" merge --ff-only "origin/$CURRENT_BRANCH" >/dev/null 2>&1 \
      || warn "Could not fast-forward local $CURRENT_BRANCH onto origin — sync it manually (git pull --ff-only)."
  fi
fi

# The tag points at the released commit itself (now an ancestor of the default
# branch via the merge commit) — consumers pin the tag, so its target is the
# exact commit the gates certified, not the merge commit.
dry git -C "$REPO_DIR" tag -a "$TAG" -m "Release $SLUG $TAG" "$RELEASE_SHA"
dry git -C "$REPO_DIR" push origin "$TAG"
info "tagged $TAG @ ${RELEASE_SHA:0:8}"

# ---------------------------------------------------------------------------
# Step 3: bump every consuming boot profile's pin (req-dev-workspace-release-1/-3).
# Substrate-first: release the substrate before its consumers so this bump lands
# the fresh substrate pin in the consumers' profiles before THEY release.
# ---------------------------------------------------------------------------
bold "Bump consuming boot profiles in $BOOT_DIR/"
if [[ "$DRY_RUN" -eq 1 ]]; then
  python3 -m tap.plugin_release --slug "$SLUG" --version "$TAG" --boot-dir "$BOOT_DIR" --dry-run
else
  python3 -m tap.plugin_release --slug "$SLUG" --version "$TAG" --boot-dir "$BOOT_DIR"
fi

bold "Done: $SLUG $TAG"
info "Next: commit the boot-profile bump(s) in this harness, then release any consumers (substrate-first)."
