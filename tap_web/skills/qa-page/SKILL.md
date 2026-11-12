---
name: qa-page
description: Independent QA review of TAP rooms as a reader meets them — drive each page in Chromium at two widths, check the standard chrome works (structural sidebar, resource drawer, table filters), run axe-core, read every screenshot, and return PASS/FAIL gates plus an editorial verdict with ranked defects. Use after any page or chrome change, and as the reviewer half of every refine-page round. The reviewer is a skeptic: claims need evidence from this run.
allowed-tools: Read Bash Bash(scripts/dc *) Bash(curl *)
argument-hint: <room paths, e.g. /stage /stage/hosts> [--round N]
---

# QA a page: the editor-tester's review

> **Skill source-of-truth.** Canonical location: `tap_web/skills/qa-page/SKILL.md`; `.claude/skills/qa-page` is a
> wiring symlink (`scripts/wire-skills.sh`). Edit the canonical.

You are not the author of the page. You are the editor who has to sign it off and the tester who has to break it.
The author (often you, a minute ago, under `refine-page`) believes the page works; your job is to find where it
does not, from evidence this run produced. A review that finds nothing is either a very good page or a lazy
review, and the second is more common: if you report zero defects, say which checks you ran that could have
found one.

Two committed helpers live next to this file:

- **`qa_drive.py`** drives the rooms (Playwright + Chromium, a minted session) and writes `qa-report.json`
  and the screenshots: status, console errors, overflow, page facts, the sidebar (present, `aria-current`,
  collapses to a rail, nothing hamburger-like), the first drawer-enabled table (a click on a cell with no
  link opens the drawer, seven categories, `?drawer=` in the URL, focus moves in, Escape closes, focus
  returns to the row, Enter on that row opens it again, the Overview row count, a shot with it open), the
  first filter bar on the room re-opened fresh (a chip click narrows the rows, counted through Tabulator
  because the DOM holds only the visible rows, writes `?f.`, a reload keeps it), and axe-core WCAG 2.x
  A/AA violations by impact. `--scheme dark` drives every page with `prefers-color-scheme: dark`.
- **`qa_gates.py`** turns that report into one PASS / FAIL / WARN line per gate with its evidence, and exits
  non-zero on a blocking failure.

## Best practices for TAP

The shared list is [AGENTS.md § Best practices for TAP](../../../AGENTS.md#best-practices-for-tap). For this skill, lead with:

- **Name the evidence behind every claim** (12): read, grepped, ran or inferred, with the file:line, output or commit.
- **Verify by presence, never by absence** (from `drive-browser`): count the rows, the categories, the chips.

## Authoritative sources

- [`spec-web-navigation.md`](../../specs/spec-web-navigation.md) — `req-web-nav-sidebar`, `req-web-nav-no-hamburger`, the chrome budget.
- [`spec-web-drawer.md`](../../specs/spec-web-drawer.md) — the drawer's region, categories, URL state and focus contract.
- [`spec-web-panels-standard-table.md`](../../specs/spec-web-panels-standard-table.md) — `req-web-stdpanel-table-filters`, row navigation.
- [`design-page`](../design-page/SKILL.md) — the reading discipline the editorial verdict is measured against.
- [`drive-browser`](../drive-browser/SKILL.md) — the venv, the session mint, the cookie name.

## Procedure

**Step 0 — setup (idempotent).** The `drive-browser` venv, plus axe-core:

```bash
VENV="$HOME/.cache/tap-playwright/venv"
[ -x "$VENV/bin/python" ] || { python3 -m venv "$VENV"; "$VENV/bin/pip" install -q playwright; "$VENV/bin/python" -m playwright install chromium; }
"$VENV/bin/python" -c "import axe_playwright_python" 2>/dev/null || "$VENV/bin/pip" install -q axe-playwright-python
```

**Step 1 — a session.** Mint one with `drive-browser`'s `mint_session.py` and keep it in a file the driver reads
(mode 600, gitignored `logs/`):

```bash
scripts/dc exec -T web uv run python manage.py shell < tap_web/skills/drive-browser/mint_session.py \
  | grep -E '^SESSION(KEY|COOKIE)=' > logs/.drive-session && chmod 600 logs/.drive-session
```

**Step 2 — drive.** One `--room` per page under review; `--crawl` when navigation changed.

```bash
"$VENV/bin/python" tap_web/skills/qa-page/qa_drive.py --out logs/qa/<stamp> \
  --room stage=/stage --room hosts=/stage/hosts --crawl
python3 tap_web/skills/qa-page/qa_gates.py logs/qa/<stamp>/qa-report.json > logs/qa/<stamp>/qa-gates.md
# Always a second pass in the dark theme: tokens flip, and contrast failures hide there.
"$VENV/bin/python" tap_web/skills/qa-page/qa_drive.py --out logs/qa/<stamp>/dark --scheme dark --widths 1440 \
  --room stage=/stage --room hosts=/stage/hosts
python3 tap_web/skills/qa-page/qa_gates.py logs/qa/<stamp>/dark/qa-report.json > logs/qa/<stamp>/dark/qa-gates.md
```

A passing contrast gate does not prove the colour is the intended one. A label that turned red passes at
5:1 on a light background. Compare headings, group headers and chips by eye against the previous run.

**Step 3 — look.** Read every screenshot with the Read tool, both widths, and the drawer shot. A gate table
without the shots read is half a review. For each room, answer in one line each:

1. **Job** — what is this page for, and does the first screen answer it? (Name the element that answers.)
2. **Hierarchy** — is the most important number or table the most prominent thing? What competes with it?
3. **Navigation** — can the reader tell where they are (breadcrumb, sidebar current item) and get to the next room?
4. **Filters and views** — are the chips the ones this reader acts on? Do the counts agree with the table?
5. **Drill-down** — does the drawer answer "what is this row?" without leaving the list? Which category was empty that should not be?
6. **Words** — any label a reader would not understand (internal type slugs, raw ids, plugin suffixes)?
7. **Visual** — truncation, overlap, misalignment, low contrast, a dark-mode surprise, an empty band.

**Step 4 — the verdict.** Write `qa-<round>.md` next to the report:

- The gate table (from `qa_gates.py`), unedited.
- **Defects**, ranked by what they cost the reader, each as: severity (blocker / major / minor / nit), room and
  width, what you saw (screenshot file and region, or report key), why it matters, a suggested fix. A defect
  without a location is an opinion.
- **Editorial verdict**: Ship / Ship with fixes / Do not ship, with one sentence why.
- **What this review could not see** (no data in a category, a state not reachable, a width not driven).

Blocking gates fail the review regardless of the editorial verdict.

## Severity

| Severity | Meaning |
| --- | --- |
| blocker | A gate failed, the page errors, data is wrong or contradictory, or a keyboard user cannot reach or leave the drawer. |
| major | The page's job is not answered on the first screen, a filter the reader needs is missing, or the drawer hides the data the row is about. |
| minor | Wording, a weak default sort, an empty category that could be filled, spacing that slows reading. |
| nit | Taste. List at most three. |

## Failure modes

- **The login wall in every shot** — the cookie name is per stack; regenerate `logs/.drive-session`.
- **`enabled_rows: 0`** — the table has no `drawer` config, or its rows lack the id field it names; check the
  panel config before reporting "drawer broken".
- **`opened=False navigated_to=…`** — the click landed on a link (a cell link navigates by design). Every cell
  in the row holds a link, so no plain cell exists: either a column without a link is missing, or the table
  should not be a drawer table.
- **Third-party styles on new markup** — wrapping library-rendered content in a new element can pick up the
  library's selectors (Tabulator colours every `span` in a group header). Re-read the shot after any
  markup change inside a library widget.
- **Chip click did nothing** — a page served without htmx (a panel error) or a filter on a field the rows lack.
- **axe `color-contrast` on the dark theme only** — drive with the theme forced; tokens flip per scheme.

## Data handling

Screenshots and reports hold whatever the stack holds. Keep them under `logs/` (gitignored) in mode-700
directories, never in the repo or a ticket.
