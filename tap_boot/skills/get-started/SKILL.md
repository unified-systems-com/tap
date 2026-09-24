---
name: get-started
description: Get a fresh developer from a bare machine (or a fresh clone) to a running, logged-in-able TAP dev session by preparing the host and driving scripts/spawn-session.sh — the single entry point for first boot AND every later session. Use when someone says "get TAP running", "stand up TAP/Rampart", "set me up", or asks how to log in for the first time. NOT for an already-provisioned session worktree (that is scripts/dc up -d).
allowed-tools: Read Grep Glob Bash(scripts/*) Bash(docker *) Bash(docker compose *) Bash(git *) Bash(uname *) Bash(grep *) Bash(cat *) Bash(ls *) Bash(tail *) Bash(mkdir *)
argument-hint: [session-name] [boot-profile]  (defaults: prompt for name; core_dev profile)
---

# Get Started: Fresh Machine → Running TAP Session

> **Skill source-of-truth.** Canonical location: `tap_boot/skills/get-started/SKILL.md`. `.claude/skills/…` is a wiring symlink (`scripts/wire-skills.sh`); this skill's symlink is the ONE committed in a fresh clone, because it bootstraps everything else.

`scripts/spawn-session.sh` is the **single canonical entry point** — first boot on a
bare machine and the Nth concurrent session are the same command. Its Step 0.1
host-readiness battery checks the toolchain and the repo layout on every run
(`req-dev-multisession-host-readiness`), so this skill re-implements nothing: you
prepare the host conversationally, make the choices with the human, invoke the
script, and walk them in the door. If the script's behavior looks wrong, fix the
script — a parallel procedure here would only drift.

The goal is minutes-to-logged-in, with the human feeling cared for at every step.

## Best practices for TAP

The shared list is [AGENTS.md § Best practices for TAP](../../../AGENTS.md#best-practices-for-tap). For this skill, lead with:

- **Name the evidence behind every claim** (12): read, grepped, ran or inferred, with the file:line, output or commit.
- **Treat specs as canon** (13): read the spec first and change it with the code.


## Step 0 — Recognize which situation you are in

- **`.env.local` here has `TAP_SESSION_LABEL`** → an already-provisioned session
  worktree. `scripts/dc up -d` starts it; nothing to get started.
- **Repo present, no sessions yet** → proceed. The script self-detects first-run.
- **No clone at all** → start at Step 1's clone stanza.

## Step 1 — Prepare the host (platform-specific)

Detect the platform (`uname`). Then:

- **macOS**: Docker Desktop installed and running is the whole list.
- **Linux**: work through **"Host prerequisites (Linux)"** in
  `docs/misc/doc-dev-multisession-onboarding.md` — Docker Engine with the Compose
  v2 plugin, docker-group membership, `lsof`, free ports. Warn about the
  root-owned bind-mount papercut *before* it bites (relief valve:
  `sudo chown -R "$USER" .`). That section is canonical; don't restate it from memory.
- **Both**: ~10 GB free disk for the images; network access to GHCR for the
  anonymous pull (the offline fallback builds locally from source instead).
  Spawn's own battery re-checks the toolchain and
  gives the fix for anything missed — you are smoothing, not gatekeeping.

## Step 2 — The canonical layout (one stanza, non-negotiable)

The primary clone lives at `~/tap-sessions/main`; sessions are worktrees beside it.
Spawn enforces this (the layout seatbelt) — set it up right the first time:

```bash
mkdir -p ~/tap-sessions
git clone git@github.com:unified-systems-com/tap.git ~/tap-sessions/main
cd ~/tap-sessions/main
```

If they already cloned elsewhere, the seatbelt's failure message gives both repair
paths (fresh re-clone vs `mv` an existing clone); prefer whichever matches how much
work is already in the clone.

## Step 3 — Choices, made WITH the human

1. **Session name** (first positional arg): short, lowercase — `dev` is a fine first name.
2. **Boot profile** (second positional): omit it → `core_dev` (core + test fixtures,
   no credentials needed, the right first boot). `core` is the zero-plugin baseline;
   The samsite demo is not a repo-local profile: its record ships inside
   `tap-plugin-samsite` and boots via the pointer form instead of a positional —
   `spawn-session.sh demo cli --from git+https://github.com/unified-systems-com/tap-plugin-samsite@v0.2.0#samsite`.
   It needs AWS/GitHub credentials plus per-deployment config — drive
   `/provision-secrets` first (it enumerates the record's declared
   `required_secrets` and walks the minting/placement), and see the samsite plugin
   README for the per-deployment config.
3. **FIPS** (default ON — leave it unless asked). The published images carry the
   validated OpenSSL provider pre-built; only the offline/unpublished local-build
   fallback compiles it from source (10–20 minutes, once). `TAP_FIPS=0` is the
   explicit dev-only escape hatch on that fallback path.
4. **Admin password**: macOS offers a one-time Keychain stash (stable across
   sessions); otherwise random-per-session, written to the worktree's
   `.dev-credentials`. A stable non-Keychain password: export
   `TAP_DEV_ADMIN_PASSWORD` first — never type a password into the chat.

## Step 4 — Run it

```bash
scripts/spawn-session.sh <name>            # or: scripts/spawn-session.sh <name> <profile>
```

Narrate the `==>` step banners as they pass. The noisy steps show one status line
with a live elapsed counter; the full output is captured to the new worktree's
`logs/spawn.log` (`TAP_SPAWN_VERBOSE=1` streams instead). Boot progress streams its
own section lines — `[seed-plugin] … OK`, `[fire-collector] … OK`. The script
fast-fails on a `TAP-ABORT` signal rather than hanging; a counter quietly ticking
through the first build is normal.

## Step 5 — If it fails

The readiness battery and every later step fail specifically, naming the fix — read
the error first. For failures after the stack starts, drive
`/diagnose-failed-session-spawn`: its first move is the boot record at
`<worktree>/logs/boot/latest.boot-record.json`, then the captured transcript. If it
looks like a TAP bug, help them file a GitHub issue with the failing step's output,
`scripts/dc logs web` tail, `uname -a`, and Docker version — first-adopter rough
edges are wanted; make filing feel like contributing.

## Step 6 — Walk them in the door

From the script's final summary (with the `cli` launch target the same access block
is saved to `logs/session-info.txt`, and `/launch-ui` reopens the web UI from inside
the session any time later — no need to scroll back):

1. Open the labeled URL (`http://<name>.tap.localhost:<port>/`) — or just invoke
   `/launch-ui`, which verifies the stack and opens the browser for them. First login is
   **username `admin` + the password from `.dev-credentials`** — the spawn may have
   already registered a dev passkey (it says so); otherwise enroll one from the
   authenticated session.
2. Point forward: `/new-plugin` scaffolds their first plugin; each plugin's README
   documents its collectors and credentials; `scripts/dc up -d` / `down` /
   `logs -f web` is the daily loop, and `scripts/spawn-session.sh <another-name>`
   is how they get their next concurrent session.
