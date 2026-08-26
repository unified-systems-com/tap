# Developer Onboarding Doc — Multi-Session Dev

## Philosophy

A developer (human or LLM) provisioning a new isolated TAP dev session needs a single procedural doc to follow — not a hunt across three feature specs. The feature specs (`spec-dev-multisession.md`, `spec-dev-multisession-smoketest.md`, `spec-dev-multisession-teardown.md`) define *what* the multi-session system does and *why*; this doc-spec owns the *how-to* surface — `docs/misc/doc-dev-multisession-onboarding.md` — and tracks its alignment with the underlying behavior.

The doc is the trial run for the documentation system defined in [spec-docs.md](spec-docs.md). Any rough edges in the trial fold back into the meta-spec.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Single Public Entry Point | One short doc tells a developer exactly what command to run to spawn a session and where to look for what it does. |
| 2. | Zero Procedural Duplication | The doc does NOT describe step-by-step procedure — the script is canonical, and parallel descriptions just drift. The doc's job is to point readers at the script and at the specs that define its behavior. |
| 3. | LLM-Actionable | An attached Claude Code session reading this doc immediately knows the entry command and where to follow up (smoke-test spec, teardown spec). |
| 4. | Drift-Resistant | The doc has almost no surface to drift — only the script invocation and links. Behavior is documented at its canonical home (specs + script comments). |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-dev-multisession-onboarding-doc-exists | [Doc Exists at Canonical Path](#doc-exists-at-canonical-path) | Proposed | `docs/misc/doc-dev-multisession-onboarding.md` |
| req-dev-multisession-onboarding-doc-pointer | [Pointer-Only Surface](#pointer-only-surface) | Proposed | Doc names the script invocation and links the specs; no procedural duplication |
| req-dev-multisession-onboarding-doc-frontmatter | [Frontmatter Per spec-docs](#frontmatter-per-spec-docs) | Proposed | Conforms to `req-docs-frontmatter` |
| req-dev-multisession-onboarding-doc-handoff | [Handoff to Smoke-Test and Teardown](#handoff-to-smoke-test-and-teardown) | Proposed | Doc tells the reader what to do next |

### Doc Exists at Canonical Path
----
RID: `req-dev-multisession-onboarding-doc-exists`
Status: `Proposed`

The doc lives at `docs/misc/doc-dev-multisession-onboarding.md`. The path is canonical; cross-references in other specs and docs link here.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-onboarding-doc-exists-1 | File present | Proposed | `docs/misc/doc-dev-multisession-onboarding.md` exists in the repo. | |
| req-dev-multisession-onboarding-doc-exists-2 | Cross-references resolve | Proposed | Every link to the doc from other specs/docs resolves. | |

### Pointer-Only Surface
----
RID: `req-dev-multisession-onboarding-doc-pointer`
Status: `Proposed`

The doc must NOT contain a step-by-step procedure. The canonical procedure lives in two places, and only those two:

1. The **script** at `scripts/spawn-session.sh` — runnable, executable behavior.
2. The **spec requirements** in `spec-dev-multisession.md` (and its sibling teardown / smoketest specs) — the *why* behind each behavior, anchored from inline comments in the script.

The doc's job is to:

- Name the entry-point command (one fenced code block).
- Link to the canonical specs (so the reader knows where to look for *what the script does*).
- Hand off to the smoke-test and teardown specs (so the reader knows what to do next).

This keeps drift to a minimum: the only surface in the doc that can drift is the entry-point command itself and the link targets. Everything substantive about behavior is captured at its canonical home.

#### Status Details

This requirement replaces the earlier onboarding-doc-procedure requirement (RID retired with it), which required the doc to contain a manual procedure that "matched current behavior." That procedure was deleted on 2026-04-27 because (a) the spawn script now exists and is canonical, and (b) parallel procedural descriptions in two places drift. The doc has been slimmed to a pointer-only surface.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-onboarding-doc-pointer-1 | No step-by-step procedure | Proposed | The doc body has zero numbered procedural steps. | |
| req-dev-multisession-onboarding-doc-pointer-2 | Names the script | Proposed | The doc contains exactly one fenced code block invoking `scripts/spawn-session.sh`. | |
| req-dev-multisession-onboarding-doc-pointer-3 | Links the canonical specs | Proposed | The doc links `req-dev-multisession-spawn-script` and `req-dev-multisession-admin-bootstrap` (so readers can follow the trail to behavior). | |

### Frontmatter Per spec-docs
----
RID: `req-dev-multisession-onboarding-doc-frontmatter`
Status: `Proposed`

The doc carries the YAML frontmatter pattern defined in [req-docs-frontmatter](spec-docs.md#frontmatter-schema):

- Required: `spec` (this file), `audience`.
- Recommended: `covers` (the three multi-session specs and the meta-spec), `update-triggers`.
- Optional but included: `assumes`, `provides`, since the doc is LLM-targeted.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-onboarding-doc-frontmatter-1 | Required fields present | Proposed | `spec`, `audience` populated correctly. | |
| req-dev-multisession-onboarding-doc-frontmatter-2 | Update triggers populated | Proposed | `update-triggers:` lists the concrete change areas this doc depends on. | |

### Handoff to Smoke-Test and Teardown
----
RID: `req-dev-multisession-onboarding-doc-handoff`
Status: `Proposed`

Reading the doc must leave the developer (or attached Claude) knowing the two next steps in the lifecycle:

1. **Verification:** run the procedure in [spec-dev-multisession-smoketest.md](spec-dev-multisession-smoketest.md) from inside the attached Claude session.
2. **Cleanup when done:** see [spec-dev-multisession-teardown.md](spec-dev-multisession-teardown.md).

Without these handoffs the doc would create an orphaned starting point — the developer spawns a session and doesn't know how to verify it or how to clean it up.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-dev-multisession-onboarding-doc-handoff-1 | Smoke-test linked | Proposed | The doc links `spec-dev-multisession-smoketest.md` with a sentence about when to run it. | |
| req-dev-multisession-onboarding-doc-handoff-2 | Teardown linked | Proposed | The doc links `spec-dev-multisession-teardown.md` with a sentence about when to use it. | |

## Re-evaluation Triggers

The doc must be reviewed (and updated if needed) when any of the following change. This list is the narrative source for the doc's `update-triggers:` frontmatter; the two should stay in sync.

The doc is now a pointer-only surface, so the trigger list is small by design. Behavior triggers (compose env contract, port registry, worktree convention, etc.) belong on `spec-dev-multisession.md` and `scripts/spawn-session.sh`'s inline comments — not here.

| Trigger | Why it matters |
| --- | --- |
| `scripts/spawn-session.sh` invocation, prompts, or output | The doc names the script as the entry point; if the invocation changes (path, flags, prompt sequence) the doc drifts. |
| Restructuring of `spec-dev-multisession-smoketest.md` or `-teardown.md` | The doc hands off to those specs; structural changes need link audits. |

History: the doc previously contained a full step-by-step manual procedure with ~10 behavior-related triggers. When the spawn script shipped (2026-04-27), the manual procedure was deleted and the trigger list collapsed to the two above. See `req-dev-multisession-onboarding-doc-pointer` for the rationale.

## Linked Specs

The doc directly references:

- [spec-dev-multisession.md](spec-dev-multisession.md) — port registry, env cascade, spawn-script (future).
- [spec-dev-multisession-smoketest.md](spec-dev-multisession-smoketest.md) — handoff target after onboarding.
- [spec-dev-multisession-teardown.md](spec-dev-multisession-teardown.md) — referenced for "how to clean up".
- [spec-docs.md](spec-docs.md) — frontmatter and conventions.

## Status Vocabulary

Standard TAP states: `Proposed`, `Approved for Development`, `In Development`, `Implemented`, `Verified`, `Refactoring`, `Deprecating`, `Deprecated`, `Backlog`.
