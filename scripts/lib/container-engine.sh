# scripts/lib/container-engine.sh — SOURCED, never executed.
#
# Chooses the container engine the dev scripts talk to, in ONE place, so spawn, dc, despawn,
# prune-images and gate-lean can never disagree about which daemon a session lives on.
# Spec: req-dev-multisession-container-engine in specs/spec-dev-multisession.md.
#
# The client is always the Docker CLI + Compose v2 plugin. What changes is the socket it
# talks to: Docker by default, Podman's Docker-compatible socket when Docker is not there.
# Podman is reached by exporting DOCKER_HOST, which every script below already inherits —
# nothing else in the scripts needs to know which engine it is.
#
# Public functions (all safe under `set -euo pipefail`; none of them exits the caller):
#   tap_engine_select [<worktree>]  sets TAP_ENGINE and, for Podman, exports DOCKER_HOST
#   tap_engine_persist <env-file>   records a Podman choice in the session's .env.local
#   tap_engine_podman_socket        prints the host-side Podman socket path, or fails
#   tap_engine_warn_other <project> warns when the compose project lives on the OTHER engine
#
# TAP_ENGINE after tap_engine_select, in precedence order:
#   explicit  DOCKER_HOST or DOCKER_CONTEXT was already set — never overridden
#   sticky    the worktree's .env.local carries DOCKER_HOST (the session was created on Podman)
#   docker    `docker info` answers on the default socket
#   podman    Docker did not answer and a responding Podman socket was found
#   none      nothing answered; the caller's own "daemon not responding" error stands
#
# bash 3.2 compatible (macOS /bin/bash): no associative arrays, no ${var,,}.

# Bound a daemon call so a wedged engine degrades to "not available", not a hung spawn.
_tap_engine_t() {  # <seconds> <cmd...>
  local secs="$1"; shift
  if command -v timeout >/dev/null 2>&1; then timeout "$secs" "$@"
  elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$secs" "$@"
  else "$@"
  fi
}

# Progress lines; scripts/dc runs on every compose call and sets TAP_ENGINE_QUIET to stay silent.
_tap_engine_say() {  # <message>
  [[ -n "${TAP_ENGINE_QUIET:-}" ]] || printf '    %s\n' "$1" >&2
}

# DOCKER_HOST is only ever a unix socket here. A value read out of .env.local is data from a
# file a person can edit, so it is validated against this shape before it is exported, and is
# never interpolated into a command line.
_tap_engine_valid_host() {  # <value>
  [[ "$1" =~ ^unix:///[A-Za-z0-9_./@+-]+$ ]]
}

tap_engine_podman_socket() {
  command -v podman >/dev/null 2>&1 || return 1
  local p
  # macOS / Windows: the socket on the HOST that forwards into the machine VM. `podman info`
  # reports the path INSIDE the VM there, which does not exist on the host, so this comes first.
  p="$(_tap_engine_t 8 podman machine inspect --format '{{.ConnectionInfo.PodmanSocket.Path}}' 2>/dev/null | head -1)" || p=""
  if [[ -n "$p" && -S "$p" ]]; then printf '%s\n' "$p"; return 0; fi
  # Linux: no machine; the engine's own socket.
  p="$(_tap_engine_t 8 podman info --format '{{.Host.RemoteSocket.Path}}' 2>/dev/null | head -1)" || p=""
  p="${p#unix://}"
  if [[ -n "$p" && -S "$p" ]]; then printf '%s\n' "$p"; return 0; fi
  return 1
}

tap_engine_select() {
  local wt="${1:-}" sticky="" sock=""
  TAP_ENGINE="none"

  if [[ -n "${DOCKER_HOST:-}" || -n "${DOCKER_CONTEXT:-}" ]]; then
    TAP_ENGINE="explicit"; export TAP_ENGINE; return 0
  fi

  # A session created on Podman stays on Podman: its containers and volumes live there, so a
  # later despawn from a fresh shell must reach the same daemon. Docker being up is irrelevant.
  if [[ -n "$wt" && -f "$wt/.env.local" ]]; then
    sticky="$(sed -n 's/^DOCKER_HOST=//p' "$wt/.env.local" | tail -1)"
    sticky="${sticky%[\"\']}"; sticky="${sticky#[\"\']}"
    if [[ -n "$sticky" ]]; then
      if _tap_engine_valid_host "$sticky"; then
        export DOCKER_HOST="$sticky"; TAP_ENGINE="sticky"; export TAP_ENGINE
        _tap_engine_say "Container engine: Podman socket recorded in $wt/.env.local ($DOCKER_HOST)."
        return 0
      fi
      echo "    WARNING: ignoring DOCKER_HOST in $wt/.env.local — not a plain unix:/// socket path." >&2
    fi
  fi

  if command -v docker >/dev/null 2>&1 && _tap_engine_t 8 docker info >/dev/null 2>&1; then
    TAP_ENGINE="docker"; export TAP_ENGINE; return 0
  fi

  if command -v docker >/dev/null 2>&1 && sock="$(tap_engine_podman_socket)"; then
    if DOCKER_HOST="unix://$sock" _tap_engine_t 8 docker info >/dev/null 2>&1; then
      export DOCKER_HOST="unix://$sock"; TAP_ENGINE="podman"; export TAP_ENGINE
      _tap_engine_say "Container engine: Docker is not responding; using Podman at $DOCKER_HOST."
      return 0
    fi
  fi

  export TAP_ENGINE
  return 0
}

# Record a Podman choice in the session's .env.local so every later script, from any shell,
# reaches the same daemon. A no-op for every other engine, and idempotent.
tap_engine_persist() {  # <env-file>
  [[ "${TAP_ENGINE:-}" == "podman" ]] || return 0
  local f="$1"
  [[ -f "$f" ]] || return 0
  grep -q '^DOCKER_HOST=' "$f" 2>/dev/null && return 0
  printf '# Container engine chosen at spawn (scripts/lib/container-engine.sh): this session lives on Podman.\nDOCKER_HOST=%s\n' \
    "$DOCKER_HOST" >> "$f"
}

# The failure this exists for: a despawn run in a shell that reaches the wrong daemon finds
# nothing, says so, removes the worktree and reports success — while the stack keeps running
# on the other engine. Looks for the compose project on the engine this run is NOT using.
tap_engine_warn_other() {  # <compose-project>
  local project="$1" ids="" sock="" other=""
  case "${TAP_ENGINE:-}" in
    podman|sticky)
      other="the default Docker daemon"
      ids="$(env -u DOCKER_HOST -u DOCKER_CONTEXT bash -c '
        command -v docker >/dev/null 2>&1 || exit 0
        docker ps -a -q --filter "label=com.docker.compose.project=$1" 2>/dev/null' _ "$project" 2>/dev/null)" || ids=""
      ;;
    docker|explicit)
      sock="$(tap_engine_podman_socket)" || return 0
      [[ "unix://$sock" == "${DOCKER_HOST:-}" ]] && return 0
      other="Podman at unix://$sock"
      ids="$(DOCKER_HOST="unix://$sock" _tap_engine_t 8 docker ps -a -q \
        --filter "label=com.docker.compose.project=$project" 2>/dev/null)" || ids=""
      ;;
    *) return 0 ;;
  esac
  if [[ -n "$ids" ]]; then
    echo "    WARNING: compose project '$project' also has containers on $other." >&2
    echo "    This run is talking to a different engine, so they will NOT be removed." >&2
    if [[ -n "$sock" ]]; then
      echo "    Remove them with: DOCKER_HOST=unix://$sock docker compose -p $project down -v --remove-orphans" >&2
    else
      echo "    Remove them with: env -u DOCKER_HOST docker compose -p $project down -v --remove-orphans" >&2
    fi
  fi
  return 0
}
