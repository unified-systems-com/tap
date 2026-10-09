#!/usr/bin/env bash
# scripts/wire-skills.sh — populate <worktree>/.claude/skills/ with one
# symlink per in-tree skill so the harness can invoke them as slash commands.
#
# Scans every `<app>/skills/<skill-name>/SKILL.md` in the worktree and creates
# `.claude/skills/<skill-name> -> <app>/skills/<skill-name>` (relative path)
# so the harness's skill registry picks them up. Idempotent — safe to re-run.
#
# Collision policy: when two apps define a skill with the same basename, BOTH
# get the app-prefixed slug (`<app-slug>-<skill-name>`); neither claims the
# un-prefixed name. Behavior is independent of filesystem scan order.
#
# `.claude/skills/` is gitignored (with the `get-started` symlink whitelisted so a
# fresh clone can drive its first spawn). The farm is per-worktree;
# nothing here pollutes the user's global ~/.claude/skills/ namespace.
#
# Called automatically by scripts/spawn-session.sh at the end of provisioning.
# Run it manually anywhere else (e.g. main worktree, or after adding a new
# `<app>/skills/<name>/SKILL.md` mid-session).

set -euo pipefail

# Resolve worktree root from this script's location (works from any cwd).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKTREE="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILLS_DIR="$WORKTREE/.claude/skills"

# --- Gather every <app>/skills/<name>/SKILL.md as `<name>\t<app-slug>\t<abs-dir>`
TMP_INVENTORY="$(mktemp)"
trap 'rm -f "$TMP_INVENTORY" "$TMP_DUPES"' EXIT

find "$WORKTREE" \
  -type f \
  -name SKILL.md \
  -not -path "$WORKTREE/.git/*" \
  -not -path "$WORKTREE/.venv/*" \
  -not -path "$WORKTREE/.claude/*" \
  -not -path "$WORKTREE/node_modules/*" \
  | while read -r skill_md; do
    skill_dir="$(dirname "$skill_md")"           # /abs/.../<app>/skills/<name>
    skill_name="$(basename "$skill_dir")"
    skills_root="$(dirname "$skill_dir")"        # /abs/.../<app>/skills
    app_root="$(dirname "$skills_root")"         # /abs/.../<app>
    app_rel="${app_root#$WORKTREE/}"             # <app>  or  plugins/<plugin>
    app_slug="${app_rel//\//-}"                  # plugins/aws_core → plugins-aws_core
    printf '%s\t%s\t%s\n' "$skill_name" "$app_slug" "$skill_dir"
  done > "$TMP_INVENTORY"

# --- Detect collisions (skill names appearing more than once)
TMP_DUPES="$(mktemp)"
awk -F'\t' '{print $1}' "$TMP_INVENTORY" | sort | uniq -d > "$TMP_DUPES"

# --- Make the symlink farm; nuke prior symlinks first so renames don't leave
# orphans, but preserve any non-symlink files a developer put there by hand.
mkdir -p "$SKILLS_DIR"
find "$SKILLS_DIR" -maxdepth 1 -type l -delete

n_total=0
n_prefixed=0
while IFS=$'\t' read -r skill_name app_slug skill_dir; do
  if grep -qx "$skill_name" "$TMP_DUPES"; then
    link_name="$app_slug-$skill_name"
    n_prefixed=$((n_prefixed + 1))
  else
    link_name="$skill_name"
  fi
  # Symlink with a relative target so the farm survives renaming the worktree.
  rel_target="$(python3 -c "import os, sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))" "$skill_dir" "$SKILLS_DIR")"
  ln -snf "$rel_target" "$SKILLS_DIR/$link_name"
  n_total=$((n_total + 1))
done < "$TMP_INVENTORY"

# --- Report
if [[ $n_prefixed -gt 0 ]]; then
  echo "wire-skills: linked $n_total skill(s) into .claude/skills/ ($n_prefixed app-prefixed due to collisions)"
else
  echo "wire-skills: linked $n_total skill(s) into .claude/skills/"
fi
