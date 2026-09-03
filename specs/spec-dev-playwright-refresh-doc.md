# Doc-Spec — Playwright MCP Refresh

## Philosophy

When an attached Claude Code session notices that the Playwright MCP server has wedged, it needs a single procedural surface that tells it — without escalating to a human — exactly which script to run, how to interpret the output, and how to hand back to a clean session. This doc-spec owns `docs/misc/doc-dev-playwright-refresh.md`, the canonical procedure, and tracks its alignment with the underlying script defined in [spec-dev-playwright-refresh.md](spec-dev-playwright-refresh.md).

The doc is LLM-first because the primary consumer is an attached Claude session running into a wedged MCP; humans read it as the secondary audience.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Self-Service for LLMs | An attached Claude session can follow the doc top-to-bottom without prompting the human first. |
| 2. | Symptom-Driven Entry | The doc opens with the symptom checklist so a wedged session can tell whether the doc applies. |
| 3. | Spec-Aligned | Steps reflect the current behavior of `scripts/refresh-playwright.sh`. |
| 4. | Drift-Resistant | Every change to the script or the MCP integration surface flags this doc for review via `update-triggers:`. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-dev-playwright-refresh-doc-exists | [Doc Exists at Canonical Path](#doc-exists-at-canonical-path) | Proposed | `docs/misc/doc-dev-playwright-refresh.md` |
| req-dev-playwright-refresh-doc-procedure | [Procedure Reflects Current Behavior](#procedure-reflects-current-behavior) | Proposed | Steps match the script |
| req-dev-playwright-refresh-doc-frontmatter | [Frontmatter Per spec-docs](#frontmatter-per-spec-docs) | Proposed | Conforms to `req-docs-frontmatter` |
| req-dev-playwright-refresh-doc-llm-runnable | [LLM-Runnable Steps](#llm-runnable-steps) | Proposed | No interactive prompts; tool calls only |

### Doc Exists at Canonical Path
----
RID: `req-dev-playwright-refresh-doc-exists`

Status: `Proposed`

The doc lives at `docs/misc/doc-dev-playwright-refresh.md`. The path is canonical; cross-references in other specs and CLAUDE.md link here.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-playwright-refresh-doc-exists-1 | File present | Proposed | `docs/misc/doc-dev-playwright-refresh.md` exists in the repo. | |
| req-dev-playwright-refresh-doc-exists-2 | Cross-references resolve | Proposed | Every link to the doc from other specs/docs/CLAUDE.md resolves. | |

### Procedure Reflects Current Behavior
----
RID: `req-dev-playwright-refresh-doc-procedure`

Status: `Proposed`

The doc's procedural steps must match what `scripts/refresh-playwright.sh` actually does, as defined in [spec-dev-playwright-refresh.md](spec-dev-playwright-refresh.md):

- The single command is `scripts/refresh-playwright.sh` (no flags).
- Expected output mentions "Killing PIDs" / "no processes found".
- The handoff step matches [req-dev-playwright-refresh-restart](spec-dev-playwright-refresh.md#restart-handoff): exit Claude Code, relaunch, MCP reconnects.
- The symptom list matches the [When to refresh](spec-dev-playwright-refresh.md#when-to-refresh) operational note.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-playwright-refresh-doc-procedure-1 | Command name correct | Proposed | Doc invokes `scripts/refresh-playwright.sh` exactly. | |
| req-dev-playwright-refresh-doc-procedure-2 | Symptoms match spec | Proposed | Symptom list aligns with the spec's "When to refresh" notes. | |
| req-dev-playwright-refresh-doc-procedure-3 | Restart step explicit | Proposed | Doc tells the reader the script alone is not enough — Claude Code must restart. | |

### Frontmatter Per spec-docs
----
RID: `req-dev-playwright-refresh-doc-frontmatter`

Status: `Proposed`

The doc carries the YAML frontmatter pattern defined in [req-docs-frontmatter](spec-docs.md#frontmatter-schema):

- Required: `spec` (this file), `audience` (must include `llm`).
- Recommended: `covers` ([spec-dev-playwright-refresh.md](spec-dev-playwright-refresh.md) and the relevant RIDs), `update-triggers`.
- Optional but included: `assumes`, `provides`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-playwright-refresh-doc-frontmatter-1 | Required fields present | Proposed | `spec`, `audience` populated correctly. | |
| req-dev-playwright-refresh-doc-frontmatter-2 | LLM in audience | Proposed | `audience` includes `llm`. | |
| req-dev-playwright-refresh-doc-frontmatter-3 | Update triggers populated | Proposed | `update-triggers:` lists the concrete change areas this doc depends on. | |

### LLM-Runnable Steps
----
RID: `req-dev-playwright-refresh-doc-llm-runnable`

Status: `Proposed`

The doc must be runnable by an attached Claude session without human intervention up to the relaunch step:

- Every command is a single shell line, copy-pasteable into a `Bash` tool call.
- No interactive prompts, no `read`, no flags requiring human judgment.
- The relaunch step is explicitly flagged as the only point where human action (or outer-harness re-exec) is required.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-playwright-refresh-doc-llm-runnable-1 | Copy-pasteable commands | Proposed | Every step is a single shell line runnable via the `Bash` tool. | |
| req-dev-playwright-refresh-doc-llm-runnable-2 | Human-handoff flagged | Proposed | The relaunch step is clearly marked as requiring human or outer-harness action. | |

## Re-evaluation Triggers

The doc must be reviewed (and updated if needed) when any of the following change. This list is the narrative source for the doc's `update-triggers:` frontmatter; the two should stay in sync.

| Trigger | Why it matters |
| --- | --- |
| `scripts/refresh-playwright.sh` behavior or output | Doc quotes the script's output; changes break the symptom-recognition flow. |
| Playwright MCP package name or invocation | Process-match patterns (`playwright-mcp`, `@playwright/mcp`) and symptoms tied to the package. |
| Claude Code restart mechanics | If "exit and re-run claude" stops being the right relaunch path, the handoff step needs updating. |
| MCP server registration in `.claude/` settings | If MCP wiring moves, the symptom list and verification steps may need to change. |
| Adoption of a self-restart / hook-based recovery (Future in feature spec) | Would replace or supplement the manual relaunch step. |

## Linked Specs

The doc directly references:

- [spec-dev-playwright-refresh.md](spec-dev-playwright-refresh.md) — the script's behavior and acceptance criteria.
- [spec-docs.md](spec-docs.md) — frontmatter and conventions.

## Status Vocabulary

Standard TAP states: `Proposed`, `Approved for Development`, `In Development`, `Implemented`, `Verified`, `Refactoring`, `Deprecating`, `Deprecated`, `Backlog`.
