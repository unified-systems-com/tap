---
name: launch-ui
description: Open the current TAP session's web UI in a browser (or print its URL when headless) by resolving the session from the worktree's .env.local. Use when someone says "/launch-ui", "open the UI", "show me the dashboard", or asks for the session's URL/port from inside a session worktree — including after spawn's attach pause pointed here. NOT for standing up a stopped stack (offer scripts/dc up -d, don't run it unasked) and NOT for other sessions' UIs (current worktree only in v0).
allowed-tools: Read Bash(scripts/dc *) Bash(cat *) Bash(curl *) Bash(open *) Bash(xdg-open *) Bash(ls *)
---

# Launch UI: Open This Session's Web UI

> **Skill source-of-truth.** Canonical location: `tap_boot/skills/launch-ui/SKILL.md`. `.claude/skills/…` is a wiring symlink (`scripts/wire-skills.sh`). Edit the canonical.

One job: get the human looking at *this* session's running web UI with the least
ceremony — resolve, verify, print, open. This is an operational procedure authored
as an AI-operable skill (`spec-ai-integration.md`): the coding agent inside a session
is the expected operator, on the human's "open the UI".

## Best practices for TAP

The shared list is [AGENTS.md § Best practices for TAP](../../../AGENTS.md#best-practices-for-tap). For this skill, lead with:

- **Name the evidence behind every claim** (12): read, grepped, ran or inferred, with the file:line, output or commit.


## Step 1 — Resolve the session from the worktree

Read `.env.local` in the worktree root for `WEB_PORT` and `TAP_SESSION_LABEL`.

- **No `.env.local` (or no `TAP_SESSION_LABEL` in it)** → this is not a provisioned
  session worktree. Say so plainly and point at the two ways in: `cd` into a session
  worktree under `~/tap-sessions/<name>/`, or spawn one (`scripts/spawn-session.sh`,
  or the `get-started` skill for a guided walk). Stop — do not guess a port.

The URLs are then:

- Direct: `http://localhost:<WEB_PORT>/` — **the sign-in origin.** Passkey login works
  ONLY here: the ceremony origin is pinned exactly and browsers refuse RP-ID
  `localhost` from a `*.localhost` subdomain (`req-tap-auth-passkey-rollout-6`).
- Labeled: `http://<TAP_SESSION_LABEL>.tap.localhost:<WEB_PORT>/` (the address bar
  names the session — `req-dev-multisession-browser-disambiguation`). Identification
  alias only; it is also a separate cookie realm from Direct, so a login on one does
  not carry to the other.

## Step 2 — Verify the stack is actually up (never silently start it)

`scripts/dc ps --format '{{.State}}' web` (always `scripts/dc`, never bare
`docker compose` — the env cascade targets this session's containers).

- **Not running / no output** → say the stack is down and **offer** `scripts/dc up -d`
  — starting containers is the operator's call, not a side effect of asking for a URL.
  Stop until they choose.
- **Running** → optionally confirm HTTP is answering (`curl -s -o /dev/null -m 5
  http://localhost:<WEB_PORT>/` — any response, including a redirect to login, counts);
  if the container is up but HTTP isn't answering yet, say the entrypoint is likely
  still syncing and the URL will work shortly.

## Step 3 — Print, then open

**Always print both URLs first** — that is the headless-safe core of this skill and
must happen even when a browser open follows (or fails).

Then open the **Direct** URL in the platform browser — never the labeled one (the
login page it lands on cannot complete a passkey ceremony there):

- macOS: `open 'http://localhost:<port>/'`
- Linux: `xdg-open '…'` when available
- Neither works (headless, SSH, no DISPLAY, command missing) → the printed URLs ARE
  the deliverable; say the human can paste them into any local browser. No error
  theatrics — printing already succeeded.

First login guidance when asked: passkey if one is bound (spawn Step 6.4), otherwise
`admin` + the password in `.dev-credentials` (worktree root, gitignored). The full
access block is also in `logs/session-info.txt` (written by spawn's `cli` launch path).

## Non-goals (v0 — named, demand-gated)

- **Any-session launch by label** (resolving another session's port from the
  `~/tap-sessions/.registry` and opening *its* UI) is deliberately out of scope.
  v0 is current-worktree only; build the registry-backed variant when someone
  actually asks for it, not before.
- Starting/stopping stacks. This skill observes and opens; `scripts/dc` verbs stay
  explicit operator actions.
