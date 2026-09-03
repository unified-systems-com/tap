# Playwright MCP Refresh

## Philosophy

The Playwright MCP server occasionally wedges — a stale child process keeps a Chromium session pinned, MCP calls start hanging or returning errors, and Claude Code can no longer drive the browser. The cure is mechanical: kill every Playwright MCP process, then restart Claude Code so the harness spawns a fresh MCP connection. Doing that by hand is fiddly (multiple `pgrep`s, watching for stragglers, parent-npm vs child cleanup), so the work is captured in a single script that an attached Claude session can run on its own. The script is the canonical recovery path; this spec defines what it must do, and the companion doc-spec owns the human/LLM-facing how-to.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Single-Command Recovery | One invocation kills every Playwright MCP process, including parent npm wrappers. |
| 2. | LLM-Runnable | An attached Claude session can invoke the script without elevated permissions or interactive prompts. |
| 3. | Idempotent | Running on a clean system is a no-op; running on a half-wedged system finishes cleanup. |
| 4. | Safe | The script touches Playwright MCP processes only — no other Node, npm, or Chromium processes get killed. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-dev-playwright-refresh-script | [Refresh Script](#refresh-script) | Implemented | `scripts/refresh-playwright.sh` |
| req-dev-playwright-refresh-restart | [Restart Handoff](#restart-handoff) | Implemented | Script tells operator to restart Claude Code |
| req-dev-playwright-refresh-scope | [Scoped Process Match](#scoped-process-match) | Implemented | Match only Playwright MCP processes |

### Refresh Script
----
RID: `req-dev-playwright-refresh-script`

Status: `Implemented`

`scripts/refresh-playwright.sh` is a single executable shell script that terminates every Playwright MCP process on the host. It runs unattended (no prompts, no flags) and exits 0 whether or not any processes were found.

#### Implementation
- Lives at `scripts/refresh-playwright.sh`, mode 0755.
- `pgrep -f 'playwright-mcp'` finds child processes; sends `SIGTERM`, waits ~1s, force-kills stragglers with `SIGKILL`.
- Separately matches `@playwright/mcp` to clean up parent npm processes that hold the MCP socket.
- Uses `set -euo pipefail`; shells out only to standard macOS / Linux utilities (`pgrep`, `kill`, `xargs`).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-playwright-refresh-script-1 | Script exists and is executable | Implemented | `scripts/refresh-playwright.sh` is checked in with executable bit set. | |
| req-dev-playwright-refresh-script-2 | No-arg invocation | Implemented | `scripts/refresh-playwright.sh` runs to completion with no arguments. | |
| req-dev-playwright-refresh-script-3 | Idempotent on clean system | Implemented | Running when no MCP processes exist exits 0 with a "no processes" message. | |

### Restart Handoff
----
RID: `req-dev-playwright-refresh-restart`

Status: `Implemented`

Killing the MCP processes is necessary but not sufficient — Claude Code holds a stale connection until restarted. The script must tell the operator to restart Claude Code as the final step, so an attached LLM session knows it has to escalate to the human (or itself, if it can re-exec) rather than silently expecting browser tools to start working again.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-playwright-refresh-restart-1 | Restart instruction printed | Implemented | Final line of script output instructs the user/LLM to restart Claude Code. | |

### Scoped Process Match
----
RID: `req-dev-playwright-refresh-scope`

Status: `Implemented`

The script must not kill unrelated Node, npm, or Chromium processes. The `pgrep -f` patterns are scoped to `playwright-mcp` (the MCP child) and `@playwright/mcp` (the npm parent). Both patterns are specific enough to avoid collateral damage.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-playwright-refresh-scope-1 | Patterns scoped to Playwright MCP | Implemented | `pgrep -f` patterns match `playwright-mcp` and `@playwright/mcp` only. | |

## Operational Notes

### When to refresh

Symptoms that warrant running the script:
- `mcp__playwright__browser_*` calls hang or time out.
- Playwright returns "browser already closed" / "target closed" errors that don't recover after navigation.
- A previous session crashed mid-run and a Chromium window is still open with no MCP attached.

### Sequencing with Claude Code

The script kills the MCP processes; the next Claude Code launch spawns a fresh MCP connection. An attached Claude session that runs the script must then exit and be relaunched by the human (or by an outer harness). The script makes this explicit in its final printed message.

### Future

If wedging becomes frequent, layered options:
1. Add a `--check` mode that reports MCP process state without killing.
2. Add a self-restart hook so an attached Claude session can refresh without human intervention (out of scope today — depends on Claude Code surface-area we don't control).
3. Wire the refresh into a hook that runs on MCP-error detection.

## Linked Docs

- [docs/misc/doc-dev-playwright-refresh.md](../docs/misc/doc-dev-playwright-refresh.md) — operator/LLM how-to for invoking the script.

## Status Vocabulary

Standard TAP states: `Proposed`, `Approved for Development`, `In Development`, `Implemented`, `Verified`, `Refactoring`, `Deprecating`, `Deprecated`, `Backlog`.
