#!/usr/bin/env bash
# scripts/lite-spawn.sh — the fast-to-type front door onto `spawn-session.sh --lite`.
#
# Stands up a real worktree (host checks, git worktree, .env.local, secrets,
# skills) and stops there — no containers, no boot. For "I have an idea, let
# me look at the code and try something" on a memory-constrained host that
# doesn't want another full stack running just to read files. Boot it into a
# real running instance later, on the same worktree, with:
#
#   scripts/promote-lite-session.sh <name>
#
# All args pass straight through to spawn-session.sh with --lite injected —
# same name/launch-target/boot-profile grammar, see `spawn-session.sh --help`.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/spawn-session.sh" --lite "$@"
