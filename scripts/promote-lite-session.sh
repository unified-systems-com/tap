#!/usr/bin/env bash
# scripts/promote-lite-session.sh — finish a `lite-spawn.sh` worktree into a
# real running instance: allocates the port band `--lite` deferred, patches
# it into the worktree's own .env.local, then runs Step 4 onward of
# spawn-session.sh (build/start Docker, wait, manage.py boot, dev passkey,
# health gate) exactly as a normal spawn would — nothing from before is
# redone. See spawn-session.sh's `--lite` / `--promote` handling.
#
# Usage: scripts/promote-lite-session.sh <name>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/spawn-session.sh" --promote "$@"
