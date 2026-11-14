---
name: refine-page
description: Improve TAP rooms in a loop of at least three rounds — use the UI as the reader does, score it against a fixed rubric with evidence, critique that critique, fix the worst problems, hand the result to qa-page for an independent review, and repeat. Ends by proposing improvements to this skill and qa-page from what the rounds taught. Use when a page or a set of rooms "works" but does not yet read well, after new chrome lands, or when asked to editorialize, optimize or make pages easy to navigate.
allowed-tools: Read Write Bash Bash(scripts/dc *) Bash(curl *)
argument-hint: <rooms, e.g. /stage /stage/hosts /aws/security-hub> [--rounds N, default 3]
---

# Refine a page: the self-critiquing loop

> **Skill source-of-truth.** Canonical location: `tap_web/skills/refine-page/SKILL.md`; `.claude/skills/refine-page`
> is a wiring symlink (`scripts/wire-skills.sh`). Edit the canonical.

`design-page` decides how a room should read before it exists. This skill takes rooms that exist and makes
them better by *using* them, the way their reader will, and being honest about what that showed. It is a loop
because one pass finds the loud problems and hides the quiet ones behind them; and it critiques its own
critique because the author of a page is the worst judge of it.

Each round has two voices that must not merge:

- **The editor** (this skill): uses the page, scores it, decides what to change, changes it.
- **The QA tester** (`qa-page`): drives it independently, runs the gates, signs off or does not.

## Best practices for TAP

The shared list is [AGENTS.md § Best practices for TAP](../../../AGENTS.md#best-practices-for-tap). For this skill, lead with:

- **Name the evidence behind every claim** (12): a score without a screenshot region or a report key is not a score.
- **Fix the platform, not the page, when the gap is the platform's**: a missing filter kind is a core change
  with a spec and a test; a bad column order is page data.

## Inputs

- The rooms (paths) and, for each, its **reader and job** in one sentence ("the on-call engineer: which host
  needs me first?"). Take them from the page's own description or `design-page` notes; if none exist, write
  them first. A room without a stated job cannot be scored.
- Where the page data lives (a GRIFT builder, a plugin's grift, a template). Fixes go there, never into the
  running database by hand.

## The rubric (fixed for the whole loop)

Score each room 0–3 on each line. 0 broken, 1 poor, 2 adequate, 3 good. Every score cites evidence.

| # | Criterion | 3 looks like |
| --- | --- | --- |
| R1 | **Job answered** | The first screen at 1440 answers the reader's question with a number, a list or a verdict, named in the critique. |
| R2 | **Hierarchy** | The answer is the most prominent element; supporting panels are visibly secondary; nothing competes. |
| R3 | **Way-finding** | Breadcrumb and sidebar agree on where you are; the next room is one click; no dead-end page. |
| R4 | **Filters and views** | The chips are the fields this reader acts on; counts agree with the rows; a useful view is one tab away; state survives reload. |
| R5 | **Drill-down** | A row opens the drawer by click and by Enter; its Overview identifies the thing (a host by its instance id and IP, a finding by the resource it concerns); Findings and Relationships hold what the row is about; "Open full page" is there for more. |
| R6 | **Words** | Labels are the reader's words; no slugs, raw ids or plugin suffixes in headings or chips; empty states say what was looked for. |
| R7 | **Density and polish** | Readable at 900 and 1440; no truncation that hides meaning, overlap or empty bands; dark mode holds. |
| R8 | **Accessibility** | No serious or critical axe violations; keyboard can open and leave the drawer; focus is visible. |

A room's score is the minimum line, not the average: one broken line is a broken page.

## The loop

Create `logs/refine/<run>/` (mode 700). For round N = 1, 2, 3, … :

1. **Use it.** Run `qa-page`'s driver for all rooms into `logs/refine/<run>/round-N/`, then read every
   screenshot (both widths, the drawer shots). Click the paths a reader would: a sidebar item, a chip, a view
   tab, a row, a drawer link to a neighbour, Back. Note what surprised you as you go.
2. **Critique** — write `round-N/critique.md`:
   - The rubric table per room, each score with its evidence.
   - **Top problems**, at most five across all rooms, ranked by reader cost, each with the fix you intend and
     where it lives (page data, panel config, core chrome).
3. **Self-critique** — append a `## Critique of the critique` section before changing anything. Answer honestly:
   - Which score did I give because I built it, not because the screenshot earned it? Lower it.
   - What did I not look at (a width, the dark theme, an empty category, the keyboard, a second filter)?
   - If the reader opened this page at 2 a.m., what would they say is wrong in ten seconds — and is it on my list?
   - Did round N−1's fixes cause anything new? Compare the shots, not the gates: a passing gate hid a red
     label that round N−1 introduced.
   - Is any gate failure a defect of the driver rather than the page? Before scoring a line 0, reproduce it
     by hand (a probe script); score an unexercised feature as unscored, not broken.
   - Is any fix on my list cosmetic while a structural problem waits? Reorder.
   - If I fixed anything before writing this file, say so, and score the state before the fix.
4. **Fix.** Apply the top problems. Page data through its builder and a GRIFT re-import; a platform gap as a
   core change with its spec row, a test, and a Tailwind rebuild if classes changed. Keep a `round-N/changes.md`:
   what changed, where, and which problem it answers.
5. **QA.** Run `qa-page` on the changed rooms (`round-N/qa-N.md`, gates and verdict). A blocking gate means
   the round is not done: fix and re-run QA before the next round.
6. **Decide.** Continue while N < 3, or any room scores below 2 on any line, or QA did not say Ship. Stop at
   N = 6 and write down what is still below 2 and why it could not be fixed in data or chrome.

After the last round, write `logs/refine/<run>/summary.md`:

- Scores per room per round (a table), so the trend is visible.
- What changed, grouped as page data versus platform.
- **Skill improvements**: which rubric line did not discriminate (always 3, or always disputed), which check
  you did by eye that `qa_drive.py` should do, which defect class recurred. Propose the edit to this file or
  `qa-page` concretely; apply it when it is a clear improvement and say so.

## What good fixes look like

- Answer first: a stat strip or one-row identity above a long table; the long table second.
- Filters on the fields the reader acts on (status, severity, product, owner), not on every column; a view per
  question the room is asked often ("Unresolved", "Critical"), not per column value.
- `drawer` on every list whose rows are entities, so drilling down keeps the list.
- Group by what the reader fixes by (account, product), largest group first, and offer the alternative axis
  as a Group-by choice rather than a second table.
- Words: a heading says what the reader learns ("Hosts not reporting"), not what the data is ("Instance list").

## What not to do

- Do not add chrome: no menus, no extra header items (`req-web-nav-chrome-budget`); the sidebar grows only by
  adding pages.
- Do not hand-edit the database or the compiled CSS; do not copy another product's code, styles or assets.
- Do not mark a round done because the scores went up; a round is done when QA's gates pass.
