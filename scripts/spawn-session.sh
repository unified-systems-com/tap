#!/usr/bin/env bash
# scripts/spawn-session.sh — interactive multi-session dev environment provisioning.
#
# This script is the canonical implementation of the onboarding procedure.
# Each numbered step block below carries a spec anchor pointing at the
# requirement that defines its behavior. To understand WHY a step does what
# it does, read the linked requirement — not a parallel description elsewhere
# (those would just drift).
#
# THE single entry point: first boot on a fresh machine and the Nth concurrent
# session are the same command (scripts/stand-up.sh retired 2026-08-09 — its host
# checks are Step 0.1 below; its conversational driver is the get-started skill).
#
# Top-level requirements implemented here:
#   req-dev-multisession-spawn-script      — overall flow, registry validation, failure trap
#   req-dev-multisession-host-readiness    — Step 0.1 toolchain checks + layout seatbelt
#   req-dev-multisession-admin-bootstrap   — Django admin user creation + .dev-credentials
#
# Top-level requirements depended on:
#   req-dev-multisession-compose-parameterized  — docker-compose.yml env-var contract
#   req-dev-multisession-env-cascade            — scripts/dc cascades .env + .env.local
#   req-dev-multisession-port-registry          — registry table in the spec is authoritative
#   req-dev-multisession-browser-disambiguation — TAP_SESSION_LABEL + *.localhost URL
#
# All four are documented in: specs/spec-dev-multisession.md
# Public-facing entry point: docs/misc/doc-dev-multisession-onboarding.md

set -euo pipefail

# Resolve the repo root from this script's own location, not $PWD, so the
# script can be invoked from anywhere (e.g. via a PATH symlink or alias).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"

bold()  { printf "\n\033[1m==> %s\033[0m\n" "$1"; }
info()  { printf "    %s\n" "$1"; }
warn()  { printf "\033[33m    %s\033[0m\n" "$1"; }
fail()  { printf "\033[31m    ERROR: %s\033[0m\n" "$1" >&2; exit 1; }
prompt(){ printf "    \033[36m%s\033[0m " "$1"; }

# Run a command with a wall-clock timeout. Pure bash so we don't depend on
# coreutils' `timeout`(1) (not present on stock macOS). Forwards the command's
# stdout to ours; stderr inherits from the caller (so `with_timeout N cmd 2>/dev/null`
# still suppresses the inner command's stderr). Returns the command's exit code,
# or 124 if it was killed for running past the deadline (matching GNU timeout).
with_timeout() {
  local timeout_secs="$1"; shift
  local tmpfile; tmpfile="$(mktemp)"
  "$@" >"$tmpfile" &
  local pid=$!
  local elapsed=0
  while (( elapsed < timeout_secs )); do
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid"; local rc=$?
      cat "$tmpfile"; rm -f "$tmpfile"
      return $rc
    fi
    sleep 1
    elapsed=$(( elapsed + 1 ))
  done
  kill -TERM "$pid" 2>/dev/null
  sleep 1
  kill -KILL "$pid" 2>/dev/null
  wait "$pid" 2>/dev/null
  cat "$tmpfile"; rm -f "$tmpfile"
  return 124
}

# --- Quiet-capture presentation (req-boot-obs-spawn-presentation) -----------
# The noisy steps (docker build/up, manage.py boot, health --json) append their
# full output to $SPAWN_LOG and the terminal shows one status line per step;
# TAP_SPAWN_VERBOSE=1 restores full streaming. $SPAWN_LOG is initialized once
# the worktree exists (Step 2) — the steps before it are one-line-per-action
# already. Spec: specs/spec-tap-boot-observability.md.
SPAWN_LOG=""

# run_quiet <label> <cmd...> — run a long, noisy command with its output
# captured to $SPAWN_LOG, showing `<label> ... <elapsed>s` while it runs and
# `ok (Ns)` / `FAILED (Ns)` + the captured tail when it finishes. Falls back to
# plain streaming under TAP_SPAWN_VERBOSE=1 or before $SPAWN_LOG exists.
run_quiet() {
  local label="$1"; shift
  if [[ -n "${TAP_SPAWN_VERBOSE:-}" || -z "$SPAWN_LOG" ]]; then
    info "$label ..."
    "$@"
    return
  fi
  printf '\n===> %s\n' "$label" >>"$SPAWN_LOG"
  local t0=$SECONDS rc=0 pid
  "$@" >>"$SPAWN_LOG" 2>&1 &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    printf '\r    %s ... %ds ' "$label" "$(( SECONDS - t0 ))"
    sleep 2
  done
  wait "$pid" || rc=$?
  if (( rc == 0 )); then
    printf '\r    %s ... \033[32mok\033[0m (%ds)    \n' "$label" "$(( SECONDS - t0 ))"
  else
    printf '\r    %s ... \033[31mFAILED\033[0m (%ds)\n' "$label" "$(( SECONDS - t0 ))"
    printf '    last lines of the captured output (%s):\n' "$SPAWN_LOG"
    tail -n 20 "$SPAWN_LOG" | sed 's/^/      | /'
  fi
  return $rc
}

# boot_status_filter — pass through only the bootloader's own section/step
# status lines (phases, [seed-plugin]/[fire-collector] steps, OK/FAILED,
# TAP-ABORT) so the operator watches population progress without the
# migration/warning firehose. Pure bash so every line renders as it arrives.
boot_status_filter() {
  local line
  while IFS= read -r line; do
    case "$line" in
      "Boot starting"*|"Boot complete"*|"boot complete"*|"Auth phase"*|"Grid-infra phase"*|"Population plan"*|"Population phase"*|"Population preflight"*|"  ["*|"    OK "*|"    FAILED "*|"      check "*|*TAP-ABORT*)
        printf '    %s\n' "$line" ;;
    esac
  done
  return 0
}

# Trap to give the user a one-line recovery command if anything goes sideways.
SESSION_NAME=""
on_failure() {
  local rc=$?
  if [[ $rc -ne 0 ]] && [[ -n "$SESSION_NAME" ]]; then
    echo
    warn "spawn failed (exit $rc). To nuke the partial state and start clean:"
    warn "  scripts/despawn-session.sh $SESSION_NAME --yes"
    warn ""
    warn "Add --purge-image if you suspect a poisoned Docker image cache — that"
    warn "forces a no-cache rebuild on the next spawn. Runtime Python state is"
    warn "owned by per-project compose volumes and despawn removes it."
    if [[ -n "$SPAWN_LOG" && -s "$SPAWN_LOG" ]]; then
      warn ""
      warn "Full standup transcript: $SPAWN_LOG"
    fi
  fi
}
trap on_failure EXIT

# ---------------------------------------------------------------------------
# Parse args
#
# Positional <name> skips the interactive name prompt in step 1.
# Optional <launch> is `cli`, `codex`, or `vscode` — when set, after a
# successful spawn the script auto-launches the matching editor against the
# new worktree.
# ---------------------------------------------------------------------------
LAUNCH_TARGET=""
BOOT_PROFILE=""
BOOT_FILE=""
DEV_PLUGINS=""
FROM_POINTER=""
FROM_CREDENTIAL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      cat <<EOF
Usage: $0 [<name>] [cli|codex|vscode] [<boot-profile>]

Spawn a new isolated TAP dev session. The positional args, in order, are:
  <name>          session label (lowercase, e.g. cli, fix-arrangements).
                  If omitted, the script prompts for it interactively.
  <boot-profile>  which boot/<profile>.boot.json \`manage.py boot\` applies to
                  this session (e.g. \`test_all\`). Optional — omit it and the
                  session boots the \`core_dev\` profile (core + grid_fixtures,
                  the minimal inner-loop baseline). What a profile declares and
                  how boot applies it lives in spec-tap-boot-v0.md, not here.
The launch target (cli|codex|vscode) is recognized by value, so it may sit
anywhere among the positionals; the two free-form words are <name> then
<boot-profile>.

The launch target auto-attaches an editor after spawn completes:
  cli     — cd into the worktree and exec \`claude\` (this script's process
            becomes the claude REPL)
  codex   — open the worktree in the Codex desktop app via
            \`codex app <worktree>\` (non-blocking — Codex launches separately)
  vscode  — open the worktree in VS Code via the \`code\` CLI (any platform),
            falling back to \`open -a "Visual Studio Code"\` on macOS
            (non-blocking — VS Code launches as a separate app)

\`--boot <profile>\` is an explicit alternative to the positional boot-profile
(handy in scripts / to avoid positional ambiguity). See
specs/spec-tap-boot-v0.md.

\`--boot-file <path>\` boots an arbitrary \`*.boot.json\` file that need NOT live in
the repo's boot/ dir — it is staged into the new worktree's boot/ under its
basename id and booted. Use it to stand up a profile that lives anywhere: a
plugin's own standalone-test profile (\`plugins/<slug>/<name>.boot.json\`), a
fork's edited in-package record, or a scratch/experimental profile, without
committing it to boot/. The trusted-local-file tier: no pointer fetch, no
digest ceremony. Composes with --dev-plugins (the staged record becomes the
workspace base). Mutually exclusive with --boot / the positional boot-profile
/ --from.

\`--from <pointer> [--credential <ref>]\` boots from a BOOTSTRAP POINTER
(spec-tap-boot-bootstrap.md): \`<source-ref>#<record>\` names a versioned plugin
artifact + a boot record shipped inside it, e.g.
\`git+https://github.com/unified-systems-com/tap-plugin-gryphon-playground@v0.1.0#soak\`.
Stage-0 fetches ONLY that record out of the git artifact (a blobless clone, no
install), verifies it against the artifact's declared sha256, writes it into
this worktree's boot/, and boots it — the record's own \`install\` section then
git-installs its plugins (the full from-git standup). \`--credential\` names the
source secret for a private repo: a bare name (resolved under
TAP_SECRETS_ROOT / ~/tap-secrets) or a full path to a *.secret.json. Mutually
exclusive with --boot / --boot-file / the positional boot-profile.

\`--dev-plugins <slug[,slug...]>\` stands up a PLUGIN WORKSPACE
(spec-dev-plugin-workspace.md) over a base profile: each slug is resolved
against that profile's git install entry (its url/rev/credential), cloned editable
into \`_dev-plugins/<slug>/\` in the worktree, and its source flipped git->editable;
every other plugin stays git-pinned. Requires a base, in any of three forms: a
repo-local profile (positional/--boot), a \`--from\` pointer (stage-0-staged +
digest-verified — the durable/versioned tier), or a \`--boot-file\` path (staged
as-is — the everyday fork/dev tier); the slug must already be a plugin in that
base. Use it to develop one or more plugins live against the rest of a real
profile. For a COUPLED change, name both:
\`--dev-plugins compliance_core,fedramp_20x_ksi\`.

Examples:
  $0                              # interactive, plain boot, no auto-launch
  $0 fix-arrangements             # named, plain boot
  $0 fix-arrangements cli         # named + attach Claude, plain boot
  $0 samsite-demo cli --from \\
     git+https://github.com/unified-systems-com/tap-plugin-samsite@v0.2.0#samsite
                                  # the samsite demo: its record ships IN the plugin
                                  # (req-boot-bootstrap-samsite-rehome) and boots by pointer
  $0 gryphon-soak cli --from \\
     git+https://github.com/unified-systems-com/tap-plugin-gryphon-playground@v0.1.0#soak
                                  # single-command boot from a git bootstrap pointer
  $0 wsdev cli test_all --dev-plugins compliance_core
                                  # workspace: compliance_core editable over a repo-local profile
  $0 sam-dev cli --from \\
     git+https://github.com/unified-systems-com/tap-plugin-samsite@v0.2.0#samsite \\
     --dev-plugins samsite
                                  # workspace over a POINTER: the samsite record is stage-0
                                  # fetched from the plugin repo, then the samsite plugin is
                                  # checked out editable over it — the external-adopter dev flow
                                  # (spec-dev-plugin-workspace.md)
  $0 sam-dev2 cli \\
     --boot-file ~/my-fork/tap_plugin/samsite/boot/samsite.boot.json \\
     --dev-plugins samsite
                                  # workspace over a LOCAL FILE — the fork-cutover dev flow:
                                  # edit your fork's in-package record (your repo URLs, rev may
                                  # be a BRANCH), stage it as-is, samsite editable over it.
                                  # No digest ceremony; --from is the versioned tier.

Spec: req-dev-multisession-spawn-script in specs/spec-dev-multisession.md
EOF
      exit 0
      ;;
    --boot)
      shift
      [[ $# -gt 0 ]] || fail "--boot requires a profile name (a boot/<profile>.boot.json id)."
      BOOT_PROFILE="$1"
      shift
      ;;
    --boot=*)
      BOOT_PROFILE="${1#--boot=}"
      shift
      ;;
    --boot-file)
      shift
      [[ $# -gt 0 ]] || fail "--boot-file requires a path to a *.boot.json file."
      BOOT_FILE="$1"
      shift
      ;;
    --boot-file=*)
      BOOT_FILE="${1#--boot-file=}"
      shift
      ;;
    --from)
      shift
      [[ $# -gt 0 ]] || fail "--from requires a bootstrap pointer (e.g. git+https://…@v0.1.0#soak)."
      FROM_POINTER="$1"
      shift
      ;;
    --from=*)
      FROM_POINTER="${1#--from=}"
      shift
      ;;
    --credential)
      shift
      [[ $# -gt 0 ]] || fail "--credential requires a source-secret name or a path to a *.secret.json."
      FROM_CREDENTIAL="$1"
      shift
      ;;
    --credential=*)
      FROM_CREDENTIAL="${1#--credential=}"
      shift
      ;;
    --dev-plugins)
      shift
      [[ $# -gt 0 ]] || fail "--dev-plugins requires a comma-separated list of plugin slugs."
      DEV_PLUGINS="$1"
      shift
      ;;
    --dev-plugins=*)
      DEV_PLUGINS="${1#--dev-plugins=}"
      shift
      ;;
    -*) fail "Unknown flag: $1" ;;
    cli|codex|vscode)
      [[ -z "$LAUNCH_TARGET" ]] || fail "Multiple launch targets given: '$LAUNCH_TARGET' and '$1'."
      LAUNCH_TARGET="$1"
      shift
      ;;
    *)
      # Free-form positionals, in order: <name> then <boot-profile>.
      # (cli|codex|vscode are matched above, so they may appear anywhere.)
      if [[ -z "$SESSION_NAME" ]]; then
        SESSION_NAME="$1"
      elif [[ -z "$BOOT_PROFILE" ]]; then
        BOOT_PROFILE="$1"
      else
        fail "Unexpected extra argument: '$1' (usage: <name> [cli|codex|vscode] [boot-profile])."
      fi
      shift
      ;;
  esac
done

# --boot-file: validate + resolve the path NOW (before any `cd`), while relative
# paths still resolve against the invocation CWD. The file is staged into the new
# worktree's boot/ in Step 2 so both pre-boot and `manage.py boot` read it by id.
# Lets a profile that lives anywhere (a plugin's own standalone-test profile, a
# scratch file) boot without being committed to the repo's boot/ dir.
BOOT_FILE_ID=""
if [[ -n "$BOOT_FILE" ]]; then
  [[ -z "$BOOT_PROFILE" ]] || fail "--boot-file and --boot/<boot-profile> are mutually exclusive."
  [[ -f "$BOOT_FILE" ]] || fail "--boot-file: no such file: '$BOOT_FILE'"
  # The '<id>.boot.json' grammar below is the shell twin of tap/boot_naming.py
  # (the one Python home of this fact) — shell cannot import it; edit in lockstep.
  [[ "$BOOT_FILE" == *.boot.json ]] || fail "--boot-file: expected a '*.boot.json' file, got: '$BOOT_FILE'"
  BOOT_FILE="$(cd "$(dirname "$BOOT_FILE")" && pwd)/$(basename "$BOOT_FILE")"
  BOOT_FILE_ID="$(basename "$BOOT_FILE" .boot.json)"
  [[ "$BOOT_FILE_ID" =~ ^[a-zA-Z0-9._-]+$ ]] \
    || fail "--boot-file: profile id derived from the filename is invalid: '$BOOT_FILE_ID' (use [A-Za-z0-9._-])."
fi

# --from: a bootstrap pointer (spec-tap-boot-bootstrap). The stage-0 fetch is deferred to
# Step 2 (once the worktree exists) so the record lands directly in $WORKTREE/boot/ — no
# temp file, nothing left behind. Here we only enforce mutual exclusivity; a pointer replaces
# a local profile entirely (it names its own install set + record). --credential is meaningless
# without --from.
if [[ -n "$FROM_POINTER" ]]; then
  [[ -z "$BOOT_PROFILE" ]] || fail "--from and --boot/<boot-profile> are mutually exclusive."
  [[ -z "$BOOT_FILE" ]] || fail "--from and --boot-file are mutually exclusive."
fi
[[ -z "$FROM_CREDENTIAL" || -n "$FROM_POINTER" ]] || fail "--credential requires --from."

# --dev-plugins: the plugin workspace (spec-dev-plugin-workspace.md). It OVERRIDES a subset of a
# base profile's plugins to editable, so it needs SOME base — any of the three base forms:
#   a repo-local profile (positional/--boot),
#   a --from pointer (stage-0 fetched + digest-verified, the durable/versioned tier), or
#   a --boot-file path (staged as-is, the trusted-local-file tier — the fork-cutover dev flow:
#   point it at YOUR checkout's edited in-package record, rev-as-branch and all).
# Step 2 stages whichever base was given BEFORE the derivation runs, so the derivation code
# reads boot/<id>.boot.json by id and never knows which form supplied it.
if [[ -n "$DEV_PLUGINS" ]]; then
  [[ -n "$BOOT_PROFILE" || -n "$FROM_POINTER" || -n "$BOOT_FILE" ]] \
    || fail "--dev-plugins requires a base boot profile (positional, --boot, --from <pointer>, or --boot-file <path>) to override."
fi

cd "$REPO"

# ============================================================================
# Step 0.1: Host readiness (req-dev-multisession-host-readiness)
#
# The first-run gate and the every-run seatbelt, absorbed from the retired
# scripts/stand-up.sh: spawn is the single entry point for a fresh clone AND
# the Nth session, so the host checks that used to live in a separate script
# run here — cheaply, idempotently, on every spawn. Each failure names its
# platform-specific fix; nothing in this step mutates the host.
# ============================================================================
bold "Step 0.1: Host readiness"

command -v git >/dev/null 2>&1 || fail "git not found on PATH."
command -v python3 >/dev/null 2>&1 || fail "python3 not found on PATH (spawn uses it to mint ids and passwords)."
command -v docker >/dev/null 2>&1 || fail "docker not found on PATH.
    macOS: install Docker Desktop. Linux: install Docker Engine + the Compose v2 plugin.
    See 'Host prerequisites' in docs/misc/doc-dev-multisession-onboarding.md."
docker compose version >/dev/null 2>&1 || fail "'docker compose' (the v2 plugin) is not available.
    The retired v1 'docker-compose' binary is not supported. Linux: apt install docker-compose-plugin."
# The port-band probe (Step 1) reads nothing when lsof is absent and would
# silently allocate a busy band — so a missing lsof fails HERE, loudly.
command -v lsof >/dev/null 2>&1 || fail "lsof not found — the port-band probe depends on it. Install it (e.g. apt install lsof) and re-run."

if ! with_timeout 8 docker info >/dev/null 2>&1; then
  if with_timeout 8 sh -c 'docker info 2>&1' | grep -qi "permission denied"; then
    fail "Docker daemon refused the connection: permission denied.
    Linux: add yourself to the docker group (sudo usermod -aG docker \$USER), then log out and back in."
  fi
  fail "Docker daemon is not responding.
    Start Docker Desktop (macOS) or the engine (Linux: systemctl start docker) and re-run."
fi
info "Toolchain OK: docker + compose v2 + lsof + python3."

# Layout seatbelt: the primary clone lives at ~/tap-sessions/main — the layout
# the registry, promote, and despawn lifecycles standardize on. Derived from git
# itself (the first `git worktree list` entry is the primary working copy, no
# matter which session worktree invoked us), compared physically so symlinked
# homes don't false-positive. Skipped when WORKTREE_BASE is overridden — a
# throwaway consumer (gate-lean) is not part of the durable layout.
CANONICAL_MAIN="$HOME/tap-sessions/main"
if [[ -z "${WORKTREE_BASE:-}" ]]; then
  PRIMARY_CLONE="$(git -C "$REPO" worktree list --porcelain | head -n 1 | cut -d' ' -f2-)"
  PRIMARY_PHYS="$(cd "$PRIMARY_CLONE" 2>/dev/null && pwd -P || echo "$PRIMARY_CLONE")"
  CANONICAL_PHYS="$(cd "$CANONICAL_MAIN" 2>/dev/null && pwd -P || echo "$CANONICAL_MAIN")"
  if [[ "$PRIMARY_PHYS" != "$CANONICAL_PHYS" ]]; then
    fail "The primary clone lives at $PRIMARY_CLONE — the multi-session layout standardizes on $CANONICAL_MAIN.
    Fresh clone (nothing to keep):  git clone \$(git -C '$PRIMARY_CLONE' remote get-url origin) $CANONICAL_MAIN
                                    (then delete $PRIMARY_CLONE)
    Existing work in this clone:    mkdir -p \$HOME/tap-sessions && mv '$PRIMARY_CLONE' $CANONICAL_MAIN
                                    (git does not care where the repo directory lives; mv preserves everything)
    Then: cd $CANONICAL_MAIN && scripts/spawn-session.sh"
  fi
  info "Layout OK: primary clone at $CANONICAL_MAIN."
fi

# First-spawn detection (no registry yet = fresh host): only changes messaging —
# the one-time published-image download is the long-ish step; only the offline/
# unpublished local-build fallback compiles FIPS OpenSSL from source.
FIRST_RUN=0
[[ -f "$HOME/tap-sessions/.registry" ]] || FIRST_RUN=1

# Soft checks: warn, never block. Identity resolves in the repo's context (repo-local
# config counts — session worktrees share it), not the invoking shell's cwd.
if ! git -C "$REPO" config user.email >/dev/null 2>&1 || ! git -C "$REPO" config user.name >/dev/null 2>&1; then
  warn "git identity is unset — commits from sessions will carry an auto-derived name/email."
  warn "  Fix: git config --global user.name 'Your Name' && git config --global user.email you@example.com"
fi

# ============================================================================
# Step 0: macOS Keychain admin password (one-time per Mac)
#
# Spec: req-dev-multisession-admin-bootstrap (Password resolution order, source #3).
#       Keychain is the recommended home for the shared default admin password
#       across sessions. Random-per-session is the fallback when this is unset.
#       Service name `tap-dev-default` and account `admin` are the contract.
# ============================================================================
bold "Step 0: macOS Keychain admin password"

if [[ "$(uname)" != "Darwin" ]]; then
  info "Not macOS — Keychain step skipped. Falling back to env var or random per session."
elif security find-generic-password -s tap-dev-default -a admin >/dev/null 2>&1; then
  info "Already set in Keychain (tap-dev-default / admin). Skipping."
elif [[ -n "${TAP_DEV_ADMIN_PASSWORD:-}" ]]; then
  info "TAP_DEV_ADMIN_PASSWORD set in env — env wins the resolution ladder; skipping the Keychain stash prompt."
elif [[ ! -t 0 ]]; then
  info "Non-interactive (no TTY on stdin) — skipping the Keychain stash prompt; a random per-session password is generated."
else
  info "No 'tap-dev-default' Keychain entry found."
  info "Stash a stable admin password? Skipping is fine — a random one will be generated"
  info "for this session and saved to the worktree's .dev-credentials file."
  prompt "Set Keychain password now? [Y/n]"
  read -r ans
  ans="${ans:-Y}"
  if [[ "$ans" =~ ^[Yy] ]]; then
    info "macOS will prompt for the password (not echoed, not in shell history)."
    security add-generic-password -s tap-dev-default -a admin -w
    info "Saved."
  else
    info "Skipping — random password will be generated per session."
  fi
fi

# ============================================================================
# Step 1: Pick a session name and allocate a port band
#
# Spec: req-dev-multisession-port-registry — sessions are allocated on demand.
#       The per-machine registry at ~/tap-sessions/.registry is canonical for
#       active sessions. Despawn removes the row; spawn appends one. Bands are
#       ephemeral by default (despawn frees them).
#       req-dev-multisession-spawn-script — name validation, primary-name
#       reservation, stale-docker pre-check.
# ============================================================================
bold "Step 1: Pick a session name and allocate a port band"

REGISTRY="$HOME/tap-sessions/.registry"
mkdir -p "$HOME/tap-sessions"

if [[ ! -f "$REGISTRY" ]]; then
  cat > "$REGISTRY" <<'EOF'
# TAP multi-session dev environment registry (per-machine, line-delimited).
# Each non-comment row records a live session: name web db branch spawned
# Spawn appends; despawn removes. See specs/spec-dev-multisession.md.
EOF
fi

# Display current allocations only when we'll actually prompt — if the name
# came in via CLI arg, the listing is noise.
if [[ -z "$SESSION_NAME" ]]; then
  ACTIVE_COUNT="$(grep -cvE '^(#|$)' "$REGISTRY" || true)"
  if [[ "$ACTIVE_COUNT" -gt 0 ]]; then
    info "Current sessions ($ACTIVE_COUNT):"
    printf '      %-20s %-5s %-5s %s\n' "name" "web" "db" "spawned"
    grep -vE '^(#|$)' "$REGISTRY" | while read -r r_name r_web r_db r_branch r_spawned; do
      printf '      %-20s %-5s %-5s %s\n' "$r_name" "$r_web" "$r_db" "$r_spawned"
    done
  else
    info "No sessions currently spawned."
  fi
  echo

  prompt "Session name:"
  read -r SESSION_NAME
else
  info "Session name (from CLI): $SESSION_NAME"
fi
[[ -n "$SESSION_NAME" ]] || fail "Session name is required."
[[ "$SESSION_NAME" =~ ^[a-z][a-z0-9_-]*$ ]] || fail "Session name must be lowercase, start with a letter, and contain only letters/digits/_/-."
[[ "$SESSION_NAME" != "default" ]] || fail "'default' is reserved for the primary stack. Pick another name."

# Reject collision with an existing registry entry.
if grep -qE "^${SESSION_NAME} " "$REGISTRY"; then
  fail "Session '$SESSION_NAME' already exists in $REGISTRY. Despawn it first, or pick a different name."
fi

# Allocate the smallest free band starting at 1 (web=8010, db=5442).
# Band 0 (8000/5432) is reserved for the primary stack.
# Cap at 50 so we fail loudly instead of allocating into someone else's well-
# known port range.
#
# A band is "free" when neither the registry NOR actual listening sockets
# claim it. The actual-port check catches the drift case where a session was
# spawned by an earlier script version that never appended its registry row,
# or where the host has something else listening on the band's ports.
#
# The probe needs lsof, and a missing lsof must fail LOUDLY: with it absent the
# pipeline below quietly returns "not in use" for every port, the guard reads
# nothing and passes, and spawn allocates a band something else is listening on.
# Enforced up front in the Step 0.1 host-readiness battery.
port_in_use() {
  lsof -iTCP:"$1" -sTCP:LISTEN -P -n 2>/dev/null | grep -q LISTEN
}
WEB_PORT=""
POSTGRES_PORT=""
for ((band=1; band<=50; band++)); do
  candidate_web=$((8000 + 10 * band))
  candidate_db=$((5432 + 10 * band))
  if grep -qE "^[^ #]+ ${candidate_web} ${candidate_db} " "$REGISTRY"; then
    continue   # band claimed in registry
  fi
  if port_in_use "$candidate_web" || port_in_use "$candidate_db"; then
    continue   # band claimed by something actually listening
  fi
  WEB_PORT=$candidate_web
  POSTGRES_PORT=$candidate_db
  break
done
[[ -n "$WEB_PORT" ]] || fail "All session bands (1..50) are in use. Despawn unused sessions or raise the cap."

info "Allocated: tap_$SESSION_NAME / web=$WEB_PORT / db=$POSTGRES_PORT"

# WORKTREE_BASE overrides where the worktree is written (default: ~/tap-sessions).
# A throwaway consumer (e.g. the lean-boot independence gate) points this at the
# system tmp dir so a disposable session never clutters ~/tap-sessions. Registry
# keys by unique name, so tmp + home spawns coexist. despawn-session.sh honours
# the SAME override, so a tmp-dir session stays teardownable by name.
WORKTREE="${WORKTREE_BASE:-$HOME/tap-sessions}/$SESSION_NAME"
[[ ! -e "$WORKTREE" ]] || fail "Worktree already exists at $WORKTREE. Despawn first."

# Catch stale Docker state from a previous failed spawn whose `dc down -v`
# didn't actually target the right project (typically because .env.local was
# missing at cleanup time). Leftover volumes survive `git worktree remove`
# and would silently inherit database, container venv, or uv cache state into
# the new session.
# Time-box the Docker probes — a wedged Docker Desktop will otherwise hang
# this script silently for as long as the operator is willing to wait.
# 8s is generous: a healthy daemon answers these queries in <100ms.
DOCKER_PROBE_TIMEOUT=8
STALE_VOLUMES_RC=0
STALE_VOLUMES="$(with_timeout "$DOCKER_PROBE_TIMEOUT" docker volume ls --filter "name=tap_${SESSION_NAME}_" --format '{{.Name}}' 2>/dev/null)" || STALE_VOLUMES_RC=$?
if [[ $STALE_VOLUMES_RC -eq 124 ]]; then
  fail "'docker volume ls' timed out after ${DOCKER_PROBE_TIMEOUT}s — the Docker daemon is unresponsive.
    Restart Docker Desktop (or your Docker engine) and re-run this script."
fi
if [[ -n "$STALE_VOLUMES" ]]; then
  fail "Stale Docker volumes exist for project 'tap_${SESSION_NAME}':
    $STALE_VOLUMES
    Remove them first: scripts/despawn-session.sh $SESSION_NAME --yes"
fi
STALE_CONTAINERS_RC=0
STALE_CONTAINERS="$(with_timeout "$DOCKER_PROBE_TIMEOUT" docker ps -a --filter "label=com.docker.compose.project=tap_${SESSION_NAME}" --format '{{.Names}}' 2>/dev/null)" || STALE_CONTAINERS_RC=$?
if [[ $STALE_CONTAINERS_RC -eq 124 ]]; then
  fail "'docker ps -a' timed out after ${DOCKER_PROBE_TIMEOUT}s — the Docker daemon is unresponsive.
    Restart Docker Desktop (or your Docker engine) and re-run this script."
fi
if [[ -n "$STALE_CONTAINERS" ]]; then
  fail "Stale Docker containers exist for project 'tap_${SESSION_NAME}': $STALE_CONTAINERS
    Remove them first: docker compose -p tap_${SESSION_NAME} down -v --remove-orphans"
fi

# ============================================================================
# Step 1.5: Refresh local main from origin
#
# Spec: req-dev-multisession-push-workflow (step 4 + spawn-side guard).
#       `git worktree add -b session/<name>` below branches from local `main`'s
#       HEAD. If sibling sessions have pushed work to origin/main since this
#       worktree's main ref last advanced, branching now would silently start
#       the new session from stale code. Refresh first so the new session is
#       always current.
#
#       The pull must run INSIDE the main worktree (not via `$REPO`, which is
#       wherever the script was invoked from — possibly a session worktree).
#       `git -C <main-worktree> pull` runs as if invoked there, so it advances
#       `main` rather than whatever branch the invoking worktree has checked out.
#
#       --ff-only refuses non-fast-forward updates — if it fails, local main
#       has either uncommitted changes (a discipline violation; never edit on
#       main) or has diverged from origin (also a discipline violation). Surface
#       the error rather than papering over it.
# ============================================================================
MAIN_WORKTREE="$HOME/tap-sessions/main"
bold "Step 1.5: Refreshing local main from origin"
if [[ ! -d "$MAIN_WORKTREE/.git" && ! -f "$MAIN_WORKTREE/.git" ]]; then
  warn "Main worktree not found at $MAIN_WORKTREE — skipping refresh."
  warn "If this is a non-standard checkout layout, advance local main manually before spawning."
else
  if ! git -C "$MAIN_WORKTREE" pull --ff-only origin main; then
    fail "Local main is not fast-forwardable from origin/main.
    Resolve manually in $MAIN_WORKTREE before spawning a new session.
    Common causes: uncommitted changes in main (never edit there), or a divergent local main."
  fi
  info "Local main is current with origin/main."
fi

# ============================================================================
# Step 2: Create the worktree
#
# Spec: req-dev-multisession-spawn-script — worktrees live OUTSIDE the repo at
#       ~/tap-sessions/<name> on a new branch session/<name>. Working tree
#       isolation is goal #2 of spec-dev-multisession.md.
#
#       The explicit `main` start-point is load-bearing: without it,
#       `git worktree add -b <new>` uses the INVOKING worktree's HEAD, not
#       `main`. If spawn-session.sh is invoked from a session worktree (e.g.
#       an agent inside vscode-prime spawning a sub-session), the new session
#       would silently inherit that session's branch-local commits. Naming
#       `main` makes the start point unambiguous and ties the new session to
#       the local `main` ref that Step 1.5 just refreshed from origin.
# ============================================================================
bold "Step 2: Creating worktree at $WORKTREE"
# Base ref the new session branches from. Default `main` (a normal spawn starts a
# fresh session from the canonical baseline). TAP_SPAWN_BASE_REF overrides it — the
# lean-boot gate (scripts/gate-lean) sets it to the invoking worktree's HEAD so the
# throwaway validates the exact (possibly just-merged, not-yet-pushed) tree, not
# whatever `main` happens to point at.
BASE_REF="${TAP_SPAWN_BASE_REF:-main}"
git worktree add "$WORKTREE" -b "session/$SESSION_NAME" "$BASE_REF"
cd "$WORKTREE"
info "Created. Now on branch session/$SESSION_NAME (branched from $BASE_REF)."

# Per-spawn captured transcript (req-boot-obs-spawn-presentation): from here on
# the noisy steps append their full output to this file; the terminal shows
# per-step status lines. logs/ is the visible runtime-log home (gitignored);
# the file is overwritten by each spawn of this worktree.
mkdir -p "$WORKTREE/logs"
SPAWN_LOG="$WORKTREE/logs/spawn.log"
: > "$SPAWN_LOG"
info "Capturing verbose standup output to $SPAWN_LOG"

# Point git at the tracked .githooks/ (post-merge/checkout/rewrite clear a stale
# .mypy_cache — see .githooks/_clear_mypy_cache.sh). Idempotent: this writes the
# SHARED config (worktrees share one common git dir), so all worktrees inherit it;
# re-setting it per-spawn is just insurance for a fresh clone that never set it.
git config core.hooksPath .githooks

# --boot-file: stage the provided profile into this worktree's boot/ under its
# basename id, then boot it like any named profile. The staged copy is a local,
# uncommitted file in the throwaway worktree (fine — it goes away on despawn).
if [[ -n "$BOOT_FILE" ]]; then
  if [[ -f "$WORKTREE/boot/$BOOT_FILE_ID.boot.json" ]]; then
    warn "--boot-file id '$BOOT_FILE_ID' shadows an existing boot/ profile in this worktree; using the provided file."
  fi
  cp "$BOOT_FILE" "$WORKTREE/boot/$BOOT_FILE_ID.boot.json"
  BOOT_PROFILE="$BOOT_FILE_ID"
  info "Staged --boot-file -> boot/$BOOT_FILE_ID.boot.json; booting profile '$BOOT_FILE_ID'."
fi

# --from: resolve the bootstrap pointer NOW (worktree exists) — stage-0 fetches ONLY the boot
# record out of the versioned git artifact (blobless clone, verified against the artifact's
# [[boot.records]] sha256) and writes it straight into this worktree's boot/. It is then booted
# like any named profile; the record's own `install` section git-installs its plugins in pre-boot
# (the full download-from-git experience). tap.boot_pointer is pure-stdlib so the host python3
# runs it venv-free; run it from $REPO so the module resolves. See spec-tap-boot-bootstrap.md.
if [[ -n "$FROM_POINTER" ]]; then
  cred_args=()
  [[ -n "$FROM_CREDENTIAL" ]] && cred_args=(--credential "$FROM_CREDENTIAL")
  info "Resolving --from pointer (stage-0 fetch): $FROM_POINTER"
  # ${cred_args[@]+…}: bash 3.2 (stock macOS) treats an EMPTY array expansion as unbound
  # under `set -u` and aborts — the +-guard expands to nothing instead of erroring.
  if ! STAGED_RECORD="$(cd "$REPO" && python3 -m tap.boot_pointer "$FROM_POINTER" ${cred_args[@]+"${cred_args[@]}"} --out "$WORKTREE/boot")"; then
    fail "--from: stage-0 fetch failed for pointer '$FROM_POINTER' (see boot-pointer error above)."
  fi
  BOOT_PROFILE="$(basename "$STAGED_RECORD" .boot.json)"
  info "Staged --from -> boot/$BOOT_PROFILE.boot.json; booting profile '$BOOT_PROFILE'."
fi

# --dev-plugins: derive a mixed editable+git workspace profile from the base profile.
# tap.dev_workspace (pure stdlib, host-runnable venv-free like tap.boot_pointer) resolves each
# named slug against the base profile's git install entry (the url/rev/credential authority),
# clones it editable into $WORKTREE/_dev-plugins/<slug>, flips that entry git->editable, and writes
# boot/<base>__dev.boot.json. We then boot that derived profile. See spec-dev-plugin-workspace.md.
#
# ORDERING (the --from / --boot-file compositions): this block runs AFTER both staging blocks
# above, so when a composition is given, $BOOT_PROFILE is already the staged record's id and the
# derivation reads $WORKTREE/boot/<id>.boot.json exactly as it reads a repo-local profile. Trust
# boundary: --from's digest verification happened at fetch time against the record as shipped;
# --boot-file is the trusted-local-file tier by its existing contract (no ceremony to bypass).
# Either way the derived __dev profile is a post-verification LOCAL mutation — identical in kind
# to the repo-local flow. Nothing new is trusted (req-dev-workspace-spawn-6/-7).
if [[ -n "$DEV_PLUGINS" ]]; then
  info "Deriving dev workspace: editable [$DEV_PLUGINS] over base profile '$BOOT_PROFILE'"
  if ! STAGED_DEV="$(cd "$REPO" && python3 -m tap.dev_workspace \
      --base-profile "$BOOT_PROFILE" --dev-plugins "$DEV_PLUGINS" --worktree "$WORKTREE")"; then
    fail "--dev-plugins: workspace derivation failed (see error above)."
  fi
  BOOT_PROFILE="$(basename "$STAGED_DEV" .boot.json)"
  info "Staged dev workspace -> boot/$BOOT_PROFILE.boot.json; booting profile '$BOOT_PROFILE'."
fi

# ============================================================================
# Step 3: Write .env.local
#
# Spec: req-dev-multisession-compose-parameterized — docker-compose.yml reads
#       COMPOSE_PROJECT_NAME, WEB_PORT, POSTGRES_PORT, TAP_GRID_ID from env.
#       req-dev-multisession-env-cascade — scripts/dc layers .env.local on top
#       of the checked-in .env so this per-worktree override file is the
#       standard way to differentiate sessions.
#       req-dev-multisession-browser-disambiguation — TAP_SESSION_LABEL drives
#       the page-title prefix and nav badge so browser tabs are distinguishable.
#       TAP_GRID_ID is freshly generated per session because each isolated
#       stack is logically a separate TAP installation.
# ============================================================================
bold "Step 3: Writing .env.local"
# uuid.uuid7 entered the stdlib in Python 3.14. The host's `python3` may be older
# (the Docker container is fine — that's 3.14+ — but we need the GRID_ID set
# before the container starts). Fall back to an inline RFC 9562 implementation
# so the script works on any Python 3.x host.
TAP_GRID_ID="$(python3 - <<'PY'
import os, time, uuid
try:
    print(uuid.uuid7())
except AttributeError:
    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_a = int.from_bytes(os.urandom(2), "big") & 0xFFF
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    val = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    print(uuid.UUID(int=val))
PY
)"
# TAP_BOOT_PROFILE names which boot/<id>.boot.json `manage.py boot` applies in Step 6.
# It is chosen explicitly per spawn via `--boot <profile>`; a plain spawn (no profile
# given) resolves to the minimal `core_dev` profile (core + grid_fixtures) — the lean
# inner-loop baseline that reaches out to nothing.
# We write that RESOLVED id, never an empty value, so every session's config states
# what it actually runs and the container-side fallback never fires in normal
# operation. The peer default lives in docker/entrypoint.sh (BOOT_PROFILE_ID) as the
# safety net for non-spawn deployments — edit one, check the other.
# `core` is the zero-plugin product baseline; `test_all` is the test union. See
# specs/spec-tap-boot-v0.md (req-boot-minimal-baseline).
# TAP_BOOT_INSTALL__SNAPSHOT_BEFORE_MIGRATE=false disables the pre-boot pre-migrate
# snapshot in dev worktrees (req-boot-snapshot-2): dev DBs reset freely, so the
# restore point is pure overhead. The env override wins over the profile's
# snapshot_before_migrate field; a skipped snapshot logs loud at container start.
# Prod/customer standups OMIT this line so the snapshot defaults on.
cat > .env.local <<EOF
COMPOSE_PROJECT_NAME=tap_$SESSION_NAME
WEB_PORT=$WEB_PORT
POSTGRES_PORT=$POSTGRES_PORT
TAP_GRID_ID=$TAP_GRID_ID
TAP_SESSION_LABEL=$SESSION_NAME
TAP_BOOT_PROFILE=${BOOT_PROFILE:-core_dev}
TAP_BOOT_INSTALL__SNAPSHOT_BEFORE_MIGRATE=false
# Dev sessions track main's tip; a plain (non-session) docker compose up gets the
# release pinned in .env. Both refs are written in full BECAUSE overriding TAP_VERSION
# here would silently do nothing — .env interpolates its image refs before this file
# is read (see the warning in .env).
TAP_WEB_IMAGE=ghcr.io/unified-systems-com/tap-web:latest
TAP_DB_IMAGE=ghcr.io/unified-systems-com/tap-db:latest
EOF
info "Wrote $WORKTREE/.env.local (gitignored)."

# ============================================================================
# Step 3.5: Provision the tap_secrets/ bind-mount target
#
# Spec: req-tap-cares-secrets-files in tap_cares/specs/spec-tap-cares-secrets.md.
#       docker-compose.yml bind-mounts ./tap_secrets:/run/tap-secrets:ro into
#       the web container. Without this step, Docker auto-creates that host
#       directory at `dc up` time as root, blocking the operator from dropping
#       *.secret.json files in without sudo.
#
#       If $HOME/tap-secrets/ exists on the host, symlink the worktree's
#       tap_secrets to it so one shared secrets directory feeds every session.
#       Otherwise create an empty per-session directory; the tap-cares loader
#       no-ops cleanly when the root is empty.
# ============================================================================
bold "Step 3.5: Provisioning tap_secrets/ bind-mount target"
SHARED_SECRETS="$HOME/tap-secrets"
if [[ -d "$SHARED_SECRETS" ]]; then
  ln -s "$SHARED_SECRETS" "$WORKTREE/tap_secrets"
  info "Linked $WORKTREE/tap_secrets -> $SHARED_SECRETS (shared across sessions)."
else
  mkdir -p "$WORKTREE/tap_secrets"
  info "Created empty $WORKTREE/tap_secrets/ (per-session)."
  info "Tip: 'mkdir $SHARED_SECRETS' to share one secrets directory across all sessions."
fi

# ============================================================================
# Step 3.6: Wire project-internal skills into .claude/skills/
#
# Each <app>/skills/<skill-name>/SKILL.md becomes a harness-invocable slash
# command by being symlinked into <worktree>/.claude/skills/. Without this
# step the in-tree skills (build-gryphon-capability, add-page, etc.) are
# just markdown discipline docs the agent has to read and follow manually.
#
# The symlink farm is per-worktree and gitignored; never pollutes the user's
# global ~/.claude/skills/ namespace. Regenerator is idempotent and can be
# re-run anywhere by hand (`scripts/wire-skills.sh`) — useful after adding a
# new skill mid-session.
# ============================================================================
bold "Step 3.6: Wiring project-internal skills into .claude/skills/"
"$WORKTREE/scripts/wire-skills.sh"

# ============================================================================
# Step 4: Build & start the Docker stack
#
# Spec: req-dev-multisession-env-cascade — must invoke compose via scripts/dc
#       (not bare docker compose) so .env.local is layered correctly and the
#       per-session port band actually takes effect.
# ============================================================================
bold "Step 4: Pulling images and starting Docker stack"
info "Pull-first: the published tap-web/tap-db images (GHCR, anonymous) carry the toolchain"
info "and a pre-compiled wheel cache, so no local compile. Falls back to a local build when the"
info "pull fails (offline, or the image is not yet published)."
if [[ "$FIRST_RUN" -eq 1 ]]; then
  info "First spawn on this host: the image download is the long-ish step (one-time; later"
  info "spawns reuse it). The offline/unpublished fallback builds locally instead — that"
  info "slow path compiles FIPS OpenSSL + the Python closure and can take 10-20 minutes."
fi
PULL_OK=1
run_quiet "Pulling published images (GHCR)" scripts/dc pull web db || PULL_OK=0
if [[ "$PULL_OK" -eq 0 ]]; then
  # The base compose file is pull-only (docker-compose.build.yml); `up` no
  # longer falls back to building on its own, so the offline/unpublished
  # path builds EXPLICITLY here — still loud, still the slow path.
  warn "Pull failed — building images locally (the slow path)."
  run_quiet "Building images locally (pull-fallback)" scripts/dc build web db
fi
run_quiet "Starting containers" scripts/dc up -d

# ============================================================================
# Step 5: Wait for the entrypoint to finish initial setup
#
# `dc up -d` returns the moment PID 1 (entrypoint.sh) starts, but the entrypoint
# is still running `uv sync` (slow on first run — populates the named-volume
# uv cache and container venv) and then `migrate`. Running another
# `dc exec uv run ...` here would race those processes and one of them gets
# SIGKILL'd by the lock contention (this caused exit 137 errors all day).
#
# Instead, poll for runserver readiness — once Django responds on port 8000
# inside the container, we know uv sync + migrate are both done. Migrate is
# already applied by the entrypoint, so we don't re-run it here.
# ============================================================================
# --- standup death detection (req-boot-abort-signal) -------------------------
# The standup pipeline emits `TAP-ABORT: <domain>: <reason>` into the web container
# log the instant it gives up (tap.logging.abort() for the Python steps, the
# entrypoint's emit_abort for its bash steps). These two checks let ANY spawn phase
# fail fast on "something died" — with the reason and a diagnosis pointer — instead
# of hanging on a poll or dying under `set -e` with only the generic recovery trap.
# Reused by Step 5 (readiness wait) and Step 6 (bootloader).

# Fail with the ABORT reason if the standup emitted the signal. Returns 0 (no-op)
# when there is none, so it is safe to call speculatively after any phase.
abort_check() {
  local line
  line="$(scripts/dc logs web 2>&1 | grep -a 'TAP-ABORT:' | tail -n1 || true)"
  [[ -z "$line" ]] && return 0
  fail "Standup ABORTED (fast-fail).
    Reason: ${line#*TAP-ABORT: }
    Diagnose: the /diagnose-failed-session-spawn skill, or: scripts/dc logs web  (in $WORKTREE)"
}

# Fail if the web container has died / is crash-looping — a dead entrypoint never
# becomes 'ready', and `exec` into a stopped container just reads as 'not ready
# yet', so without this an exited container polls to the timeout. Prefers the
# specific ABORT reason when one was emitted.
web_container_dead_check() {
  local state
  state="$(scripts/dc ps --all --format '{{.State}}' web 2>/dev/null | head -n1 || true)"
  case "$state" in
    exited|dead|restarting)
      abort_check
      fail "The web container is not running (state=${state}) — standup crashed before serving.
    Diagnose: the /diagnose-failed-session-spawn skill, or: scripts/dc logs web  (in $WORKTREE)" ;;
  esac
}

bold "Step 5: Waiting for entrypoint (uv sync + migrate + runserver)"
info "First-time uv sync downloads ~50MB of wheels — typically 1-3 minutes."
# Readiness backstops. The PRIMARY hang trigger is STALL DETECTION: a healthy
# entrypoint streams log output continuously (cache seed, uv sync, plugin
# installs, migrations), so "no new web-log output for STALL_TIMEOUT" is the
# real signal — wall-clock alone cannot distinguish slow from stuck (observed
# 2026-08-09: a loaded host ran a HEALTHY migrate straight past the old 600s
# wall-clock while streaming the whole time). The wall-clock ceiling remains
# only as the outer safety bound, sized by which Step 4 path ran: the warm
# pull-first path still legitimately runs minutes (a samsite-class pre-boot
# git-installs 11 plugins; a loaded host stretches everything), and the
# local-build fallback adds the FIPS delta source compile (~4m30s for a
# cryptography bump alone).
STALL_TIMEOUT=120
if [[ "${PULL_OK:-1}" -eq 1 ]]; then
  WAIT_TIMEOUT=600   # warm path: published images + seeded wheel cache
else
  WAIT_TIMEOUT=900   # fallback local build: stale/absent seed re-pays the compile
fi
WAIT_START=$(date +%s)
LAST_LOG_SIZE=0
LAST_PROGRESS=$WAIT_START
while true; do
  # Fatal-standup fast-paths (before the readiness probe, which would otherwise
  # poll a dead/aborted container to the timeout — the 300s black-box this replaces,
  # e.g. a core->plugin-dep import leak crashing `migrate`):
  abort_check                 # (a) an emitted TAP-ABORT signal → fail with the reason
  web_container_dead_check    # (b) the container exited / is crash-looping → fail

  # (c) Readiness. Use Python's urllib (always present — the base image is
  #     python:3.14-slim, which doesn't ship curl). The check passes if anything
  #     HTTP responds at all — the goal is "is runserver listening?", not "does the
  #     page load cleanly?". 500s are fine here; we just need to know uv sync +
  #     migrate finished and the dev server bound the port.
  if scripts/dc exec -T web python -c "
import urllib.request, sys
try:
    # timeout=10, NOT 2: a timeout counts as 'not listening', and under heavy
    # host load (multiple stacks + CI lanes on one machine) a HEALTHY dev
    # server can exceed 2s per request — observed 2026-08-09: two lean-boot
    # gate reds with a fully-booted container failing this probe for 600s.
    # Responsiveness is governed by the 3s poll cadence, not this ceiling.
    urllib.request.urlopen('http://localhost:8000/admin/', timeout=10)
    sys.exit(0)
except urllib.error.HTTPError:
    sys.exit(0)  # 4xx/5xx from a real server is still 'listening'
except Exception:
    sys.exit(1)  # connection refused / not listening yet
" 2>/dev/null; then
    info "Web is responding."
    break
  fi
  # Stall detection: track web-log growth; a healthy entrypoint streams, a hang
  # goes silent. Byte count via wc -c — cheap, and monotonic while logs append.
  NOW=$(date +%s)
  LOG_SIZE=$(scripts/dc logs web 2>&1 | wc -c | tr -d ' ')
  if [[ "$LOG_SIZE" -gt "$LAST_LOG_SIZE" ]]; then
    LAST_LOG_SIZE=$LOG_SIZE
    LAST_PROGRESS=$NOW
  fi
  STALLED_FOR=$(( NOW - LAST_PROGRESS ))
  if [[ $STALLED_FOR -gt $STALL_TIMEOUT ]]; then
    fail "Entrypoint STALLED: no new web-log output for ${STALL_TIMEOUT}s (waited $((NOW - WAIT_START))s total, no ABORT signal).
    The container is up but silent — a genuine hang, not a slow healthy boot.
    Inspect: scripts/dc logs web  (in $WORKTREE). Diagnose: the /diagnose-failed-session-spawn skill."
  fi
  elapsed=$(( NOW - WAIT_START ))
  if [[ $elapsed -gt $WAIT_TIMEOUT ]]; then
    fail "Web did not become ready in the ${WAIT_TIMEOUT}s ceiling (log was still progressing ${STALLED_FOR}s ago; no ABORT signal).
    A loaded host can stretch a healthy boot past the ceiling — check 'scripts/dc logs web' in $WORKTREE:
    if the entrypoint is still advancing, let it finish and run the tail steps manually (see the diagnose skill's backstop-timeout signature)."
  fi
  printf "    waiting... %ds (log progress %ds ago)   \r" "$elapsed" "$STALLED_FOR"
  sleep 3
done
echo

# ============================================================================
# Step 6: Stand the instance up via the bootloader
#
# spawn's job ends at "hand a fresh DB + running container to the bootloader."
# `manage.py boot --profile <id>` owns the standup contract — phases, ordering,
# auth, plugin seeding, collectors — and is the SAME path in dev and customer
# environments (req-boot-spawn-bridge). Do NOT re-describe boot's phases here;
# they live in spec-tap-boot-v0.md. (Migrations + the cache table already ran in
# the entrypoint — schema preconditions, not boot phases.)
#
# What spawn legitimately owns at this step is dev-env-specific: resolving the
# admin password and exposing it through the .dev-credentials interface. boot's
# auth phase creates the admin from the DJANGO_SUPERUSER_* env this step supplies
# (req-tap-auth-local-5); spawn just sources the password and passes it.
#
# Admin password resolution (req-dev-multisession-admin-bootstrap):
# TAP_DEV_ADMIN_PASSWORD → macOS Keychain (tap-dev-default/admin) → random. The
# resolved password is written to .dev-credentials (gitignored) — the runtime
# interface the attached Claude / developer reads on demand.
#
# Profile default: the explicit `--boot` profile if given, else `core_dev`
# (core + grid_fixtures) — a plain spawn stands up the lean inner-loop baseline
# and reaches out to nothing.
# ============================================================================
bold "Step 6: Standing the instance up (manage.py boot)"

BOOT_PROFILE_EFFECTIVE="${BOOT_PROFILE:-core_dev}"

# Resolution order matches req-dev-multisession-admin-bootstrap.
# (--admin-password CLI flag isn't supported in v1; add later if needed.)
ADMIN_PASSWORD=""
if [[ -n "${TAP_DEV_ADMIN_PASSWORD:-}" ]]; then
  ADMIN_PASSWORD="$TAP_DEV_ADMIN_PASSWORD"
  info "Admin password source: \$TAP_DEV_ADMIN_PASSWORD"
elif [[ "$(uname)" == "Darwin" ]] && ADMIN_PASSWORD="$(security find-generic-password -s tap-dev-default -a admin -w 2>/dev/null)" && [[ -n "$ADMIN_PASSWORD" ]]; then
  info "Admin password source: macOS Keychain (tap-dev-default)"
else
  ADMIN_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')"
  info "Admin password source: random (fresh per session)"
fi

ADMIN_EMAIL="admin@$SESSION_NAME.tap.localhost"

cat > .dev-credentials <<EOF
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=$ADMIN_PASSWORD
DJANGO_SUPERUSER_EMAIL=$ADMIN_EMAIL
SESSION_NAME=$SESSION_NAME
GENERATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

info "Booting with profile '$BOOT_PROFILE_EFFECTIVE'."
# The bootloader emits `TAP-ABORT: boot: <reason>` on a fatal population/auth
# failure (req-boot-abort-signal). Guard the exec so that surfaces as a clean
# fast-fail with the reason + diagnosis pointer, rather than a bare `set -e` death
# into the generic recovery trap.
#
# Presentation (req-boot-obs-spawn-presentation): the full boot output is
# captured to $SPAWN_LOG; the terminal streams only boot's own section/step
# status lines (phases, [seed-plugin]/[fire-collector] OK/FAILED) so failures —
# including the load-bearing `FAILED —` line and TAP-ABORT — stay visible live.
BOOT_CMD=(scripts/dc exec -T
  -e DJANGO_SUPERUSER_USERNAME=admin
  -e DJANGO_SUPERUSER_PASSWORD="$ADMIN_PASSWORD"
  -e DJANGO_SUPERUSER_EMAIL="$ADMIN_EMAIL"
  web uv run python manage.py boot --profile "$BOOT_PROFILE_EFFECTIVE")
BOOT_RC=0
if [[ -n "${TAP_SPAWN_VERBOSE:-}" ]]; then
  "${BOOT_CMD[@]}" || BOOT_RC=$?
else
  printf '\n===> manage.py boot --profile %s\n' "$BOOT_PROFILE_EFFECTIVE" >>"$SPAWN_LOG"
  # pipefail: the pipeline's status is boot's own exit code (tee and the filter
  # both succeed), captured without tripping set -e.
  "${BOOT_CMD[@]}" 2>&1 | tee -a "$SPAWN_LOG" | boot_status_filter || BOOT_RC=$?
fi
if (( BOOT_RC != 0 )); then
  abort_check   # surface the specific TAP-ABORT: boot reason if one was emitted
  fail "manage.py boot failed (profile '$BOOT_PROFILE_EFFECTIVE').
    Boot record:  $WORKTREE/logs/boot/latest.boot-record.json (structured outcome + failing checks)
    Transcript:   $SPAWN_LOG (also: scripts/dc logs web, in $WORKTREE)
    Diagnose: the /diagnose-failed-session-spawn skill."
fi

info "Instance booted via manage.py boot. Credentials saved to $WORKTREE/.dev-credentials (gitignored)."

# ============================================================================
# Step 6.4: Dev passkey — register once, replay forever (req-tap-auth-passkey-dev-bootstrap)
#
# All the logic lives in `manage.py bootstrap_dev_passkey` (req-…-dev-bootstrap-9); this
# step is a CALLER, not a second implementation. It asks the command for the state, then
# does the two things only the host can do:
#
#   * decide whether a human is present. `docker compose exec -T` strips the TTY, so an
#     isatty() check inside the container would answer for the wrong process. We test
#     `[[ -t 0 ]]` here and only then pass --wait (req-…-dev-bootstrap-13) — CI, gate-lean,
#     and throwaway stacks never block on a browser that isn't there.
#   * place the record. /run/tap-secrets is mounted read-only into the container on purpose
#     (that mount is an integrity control for a file whose integrity is load-bearing), so
#     the command EMITS and we write. Atomically: temp file + mv + chmod 600, never a bare
#     `>` redirect, which truncates its target before the command runs and leaves a
#     zero-byte record behind (req-…-dev-bootstrap-12).
#
# Fail-open by design: any refusal or failure here falls back to the Step 6 password bridge
# rather than aborting the spawn. Runs AFTER boot so sync_auth has provisioned tap_admin.
# ============================================================================
DEV_PASSKEY_RECORD_HOST="$WORKTREE/tap_secrets/dev-passkey/admin.dev-passkey.json"
bold "Step 6.4: Dev passkey"

# --json is side-effect-free and always exits 0; stdout carries only the state object.
PASSKEY_STATE_JSON="$(scripts/dc exec -T web uv run python manage.py bootstrap_dev_passkey \
  --json --profile "$BOOT_PROFILE_EFFECTIVE" 2>/dev/null || echo '{}')"
PASSKEY_STATE="$(printf '%s' "$PASSKEY_STATE_JSON" | python3 -c \
  'import json,sys; print(json.load(sys.stdin).get("state","unknown"))' 2>/dev/null || echo unknown)"

case "$PASSKEY_STATE" in
  ready)
    if scripts/dc exec -T web uv run python manage.py bootstrap_dev_passkey \
        --import --profile "$BOOT_PROFILE_EFFECTIVE"; then
      info "Dev passkey bound to admin. Log in at http://localhost:$WEB_PORT/ with your passkey."
    else
      info "Dev passkey import failed — continuing with the password bridge. See the output above."
    fi
    ;;
  needs_registration)
    if [[ -t 0 ]]; then
      info "No dev passkey yet. Registering one now — this is a ONE-TIME step; every future"
      info "spawn will bind it automatically with no re-registration."
      mkdir -p "$(dirname "$DEV_PASSKEY_RECORD_HOST")"
      RECORD_TMP="$(mktemp "${DEV_PASSKEY_RECORD_HOST}.XXXXXX")"
      # stdout -> the temp record; the secret-bearing enrollment link stays on stderr.
      if scripts/dc exec -T web uv run python manage.py bootstrap_dev_passkey \
          --register --wait --emit-record --profile "$BOOT_PROFILE_EFFECTIVE" \
          --base-url "http://localhost:$WEB_PORT" > "$RECORD_TMP"; then
        chmod 600 "$RECORD_TMP"
        mv -f "$RECORD_TMP" "$DEV_PASSKEY_RECORD_HOST"   # atomic: never a partial record
        info "Dev passkey saved to $DEV_PASSKEY_RECORD_HOST (0600). Future spawns are zero-touch."
      else
        rm -f "$RECORD_TMP"
        info "Passkey registration did not complete — continuing with the password bridge."
        info "  Re-run any time: scripts/dc exec web uv run python manage.py bootstrap_dev_passkey --register --wait"
      fi
    else
      info "No dev passkey record at $DEV_PASSKEY_RECORD_HOST — skipping (password bridge only)."
      info "  To enable one-gesture passkey login on every future spawn, run this from a terminal:"
      info "  scripts/spawn-session.sh … (interactive), or register manually:"
      info "  scripts/dc exec web uv run python manage.py bootstrap_dev_passkey --register --wait"
    fi
    ;;
  not_dev)
    info "Profile '$BOOT_PROFILE_EFFECTIVE' is not 'dev_local' — dev passkey onboarding refused (fail closed)."
    ;;
  *)
    info "Could not resolve dev passkey state — continuing with the password bridge."
    ;;
esac

# ============================================================================
# Step 6.5: Functional health gate (manage.py health)
#
# The Step 5 wait only proves runserver is LISTENING — it accepts any HTTP
# response, 5xx included, as "ready". That blindness is exactly what let the
# tap_cache latent-provisioning fault ship a "successful" spawn that 500s on
# first cache access. After boot, gate on the in-process health service via the
# CLI: `manage.py health` runs a live db + cache (set/get round-trip) + queue +
# secrets probe and exits non-zero when a critical backend is broken. This is
# the network-free exec gate (req-tap-health-exposure-2) that replaced the
# unauthenticated /healthz endpoint (req-tap-health-exposure-4). See
# specs/spec-tap-health-v0.md and docs/aar/2026-06-26-tap-cache-latent-provisioning.md.
# ============================================================================
bold "Step 6.5: Gating on instance health (manage.py health)"
# The probe JSON is captured to $SPAWN_LOG either way; it is printed to the
# terminal only on failure (where it is the evidence naming the broken probe)
# or under TAP_SPAWN_VERBOSE=1.
HEALTH_RC=0
HEALTH_JSON="$(scripts/dc exec -T web uv run python manage.py health --set readiness --json 2>>"$SPAWN_LOG")" || HEALTH_RC=$?
printf '\n===> manage.py health --set readiness --json\n%s\n' "$HEALTH_JSON" >>"$SPAWN_LOG"
if (( HEALTH_RC == 0 )); then
  if [[ -n "${TAP_SPAWN_VERBOSE:-}" ]]; then printf '%s\n' "$HEALTH_JSON"; fi
  info "Instance is healthy (db + cache + queue + secrets probes passed)."
else
  printf '%s\n' "$HEALTH_JSON"
  fail "Instance booted but health is UNHEALTHY — a critical backend (db/cache/secrets) is broken.
    The report JSON above names the failing probe (status + code). Inspect logs:
      scripts/dc logs web
    (in $WORKTREE). Do NOT treat this session as usable until 'manage.py health --set readiness' passes."
fi

# ============================================================================
# Final: record the session in the registry
#
# Spec: req-dev-multisession-port-registry — registry is the canonical record
#       of live sessions. Append-on-success means partial spawns leave no
#       row; the band stays "free" for the next attempt to retry the same
#       name. (Trade-off: two simultaneous spawns could race on band
#       allocation. Genuinely rare; not worth a lock for v1.)
# ============================================================================
SPAWNED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "$SESSION_NAME $WEB_PORT $POSTGRES_PORT session/$SESSION_NAME $SPAWNED_AT" >> "$REGISTRY"

# ============================================================================
# Done — print URLs, credentials, and attach instructions
#
# Spec: req-dev-multisession-browser-disambiguation — the labeled URL uses the
#       *.localhost subdomain pattern (RFC 6761 native browser resolution to
#       127.0.0.1) so the address bar tells the developer which session they're
#       in. The direct localhost:<port> URL leads: it is the ONLY origin passkey
#       sign-in works on — browsers refuse RP-ID "localhost" from a *.localhost
#       subdomain, and the ceremony origin is pinned exactly
#       (req-tap-auth-passkey-rollout-6). The labeled URL is an address-bar
#       label, and its cookie realm is separate from Direct's.
# ============================================================================
trap - EXIT  # Disarm failure trap on success.

echo
bold "Done — session '$SESSION_NAME' is ready."
echo
info "URLs"
info "  Direct:    http://localhost:$WEB_PORT/  <- sign in HERE (passkeys refuse other origins)"
info "  Labeled:   http://$SESSION_NAME.tap.localhost:$WEB_PORT/  (address-bar label only)"
info "  Admin URL: http://localhost:$WEB_PORT/admin/"
echo
info "Admin credentials"
info "  Username:  admin"
info "  Password:  (saved to .dev-credentials — never printed to stdout)"
info "  File:      $WORKTREE/.dev-credentials"
info "  Read with: cat '$WORKTREE/.dev-credentials'"
echo
info "Standup transcript"
info "  Captured:  $WORKTREE/logs/spawn.log (full docker/boot/health output; TAP_SPAWN_VERBOSE=1 streams instead)"
echo
info "Secrets mount (tap-cares runtime secrets)"
if [[ -L "$WORKTREE/tap_secrets" ]]; then
  info "  Host path: $WORKTREE/tap_secrets -> $(readlink "$WORKTREE/tap_secrets")"
else
  info "  Host path: $WORKTREE/tap_secrets/"
fi
info "  Container: /run/tap-secrets (read-only)"
info "  Drop:      <key>.secret.json  (see tap_cares/specs/spec-tap-cares-secrets.md)"
echo
info "Attach Claude Code"
info "  CLI:       cd $WORKTREE && claude"
info "  Codex:     codex app '$WORKTREE'"
info "  VSCode:    open '$WORKTREE' in a new VSCode window"
echo
info "Next: from inside the attached Claude session, run the smoke tests in"
info "      specs/spec-dev-multisession-smoketest.md"
echo

# ============================================================================
# Auto-launch editor (optional second positional arg)
#
# `cli` — exec claude in the worktree. This script's process becomes the
#         claude REPL; when claude exits the user is back in their original
#         shell.
# `codex` — open the worktree in the Codex desktop app. Non-blocking, same
#           shape as `vscode`, but routed through Codex's workspace-aware CLI.
# `vscode` — open the worktree as a folder in VS Code. Non-blocking; the
#            script exits normally after the open call returns.
# ============================================================================
case "$LAUNCH_TARGET" in
  cli)
    # The exec below REPLACES this process with the claude REPL, which takes over
    # the terminal — the access summary above would scroll away unrecoverably. So:
    # persist the access block to a file in the worktree first, then (interactive
    # runs only) pause so the human can read/copy before attaching. The /launch-ui
    # skill reopens the web UI from inside the session any time after.
    SESSION_INFO_FILE="$WORKTREE/logs/session-info.txt"
    cat > "$SESSION_INFO_FILE" <<EOF
TAP session '$SESSION_NAME' — access info (written by spawn-session.sh, $(date -u +%Y-%m-%dT%H:%M:%SZ))

URLs
  Direct:    http://localhost:$WEB_PORT/  <- sign in HERE (passkeys refuse other origins)
  Labeled:   http://$SESSION_NAME.tap.localhost:$WEB_PORT/  (address-bar label only)
  Admin URL: http://localhost:$WEB_PORT/admin/

Admin credentials
  Username:  admin
  Password:  saved to $WORKTREE/.dev-credentials (gitignored; read with cat)

Secrets mount:  $WORKTREE/tap_secrets -> container /run/tap-secrets (read-only)
Standup log:    $WORKTREE/logs/spawn.log
Boot profile:   $BOOT_PROFILE_EFFECTIVE

Reopen the web UI from inside the session any time: /launch-ui
Smoke tests:    specs/spec-dev-multisession-smoketest.md
EOF
    info "Session info saved to $SESSION_INFO_FILE"
    # Pause ONLY on a real terminal: scripted/CI/gate-lean invocations (no tty on
    # stdin) must never hang here. `read` from a non-tty would consume piped stdin
    # or return immediately — skipping it entirely keeps those paths exec-clean.
    if [[ -t 0 ]]; then
      echo
      read -r -p "    Press Enter to attach Claude Code (info saved to logs/session-info.txt; reopen the UI anytime with /launch-ui) ... "
    fi
    bold "Launching Claude Code in $WORKTREE..."
    cd "$WORKTREE"
    # Name the session after the worktree label so it's recognizable without a
    # manual /rename. (Color is left to the user — pick one per /color to match
    # the session's mood.)
    exec claude -n "$SESSION_NAME"
    ;;
  codex)
    bold "Opening $WORKTREE in Codex..."
    codex app "$WORKTREE"
    ;;
  vscode)
    bold "Opening $WORKTREE in VS Code..."
    # Prefer the `code` CLI: it exists on Linux and on any macOS install that ran
    # "Shell Command: Install 'code' command". `open -a` is the Darwin-only fallback
    # for a macOS VS Code whose shell command was never installed.
    if command -v code >/dev/null 2>&1; then
      code "$WORKTREE"
    elif [[ "$(uname)" == "Darwin" ]]; then
      open -a "Visual Studio Code" "$WORKTREE"
    else
      warn "No 'code' CLI on PATH — open $WORKTREE in your editor manually."
    fi
    ;;
esac
