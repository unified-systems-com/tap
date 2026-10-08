# Design a Page: Working Boards, Not Walls of Text

> **Skill source-of-truth.** Canonical location: `tap_web/skills/design-page/SKILL.md`; `.claude/skills/design-page`
> is a wiring symlink (`scripts/wire-skills.sh`). Edit the canonical.

This skill is about how a TAP page **reads**, after `add-page` / `add-panel` have decided what it *is*. It was
extracted on 2026-09-11 from the git-serious secret pages (the ones that landed well) and from the first cut of
the git-serious query-pack pages (the ones that did not — "these pages need some serious attention"). The
difference between the two was not the data; it was that one set followed a discipline and the other set was
text in the order the author thought of it.

Run it **before** the first template is written and **again** on the screenshot, because it catches two
different failures: a page designed without a job, and a page whose render does not match its template.

## Authoritative sources (read first; do not guess)

- [`tap_web/specs/spec-web-page.md`](../../specs/spec-web-page.md) — pages, slots, `USES_PANEL`.
- [`tap_web/specs/spec-web-panels-standard.md`](../../specs/spec-web-panels-standard.md) — prefer a standard panel
  (`table` in rows mode, `viewer`) before a custom one; a custom panel earns its place by *composition*, not by
  re-implementing a table.
- [`tap_grid/specs/spec-grid-icon.md`](../../../tap_grid/specs/spec-grid-icon.md) — every `BaseModel` declares an
  `ENTITY_ICON`; icons are decorative and never the sole carrier of meaning (`req-grid-icon-render-2`).
- [`tap_web/specs/spec-web-time-display.md`](../../specs/spec-web-time-display.md) — times are viewer-local via
  `{% load tap_time %}` / `|tap_localtime`, never hand-formatted.
- The two reference pages, in this order: `git_serious/templates/git_serious/panels/secret_detail.html` (one
  object in full) and `secrets_overview.html` (an estate rollup); their stylesheet `git_serious/css/secrets.css`
  is the type scale and tone vocabulary below. The zizmor finding page is the older sibling they were modelled on.

## Step 0: Name the page's job in one sentence

Write it at the top of the spec before anything else: *who* opens this page, *what question* they arrive with,
and *what they do next*. A page with two jobs is two pages (the secret page and the secrets page are not one).
Every section below must serve that sentence or leave.

A **board** is a page someone works from — scans, filters, picks a row, comes back tomorrow. A **profile** is
one object in full. They are designed differently (Steps 3 and 4). Most requests that arrive as "a table of X"
are boards; most that arrive as "a page for X" are profiles.

## Step 1: Load-bearing rules (all pages)

1. **Three states, never two — visibly.** Every fact the page shows can be *observed*, *observed-empty*, or
   *not observable*, and the render must make them look different. Zero rows is a fact; "we could not look" is
   a different fact; an empty table that means either is the failure this codebase exists to catch. The
   secrets page renders *never referenced* (warn), *cannot find* (bad), *unknown, not none* (muted) as three
   different badges for this reason. Never render a value the grid does not hold.
2. **Meaning line before data.** Every section opens with one muted sentence saying what the section
   *means* and how to read it — what a row is, what absence means, what is derived versus observed. This is
   the single cheapest cognitive-load reducer on the page: the reader is never left inferring the semantics
   from the shape of the data.
3. **Derived, and say so.** Anything computed (reach, exposure, "20 never name it") is computed from the grid
   at render and the meaning line says what it was computed *from*. Nothing is typed in; a number a reader
   could not reproduce from the page's own facts is a number to delete.
4. **Provenance is present and collapsed.** A `<details>` at the foot names the sources, the joins and the
   ceilings. It is there for the reader who asks "says who?" and out of the way for the one who does not.
5. **Bad input is a state.** A missing or malformed `?id=` renders a sentence and a link back, never a 500 and
   never an empty page.
6. **Nothing hardcoded that the grid can answer.** Counts, names, reach, ages: all from the grid. Plugin URLs
   come from panel config templates (`page_url(template, **fields)`), never literals in core.

## Step 2: The visual system (inherit it; do not invent a second one)

TAP pages sit on the shell's neutral ground and system sans; the page owns typography *inside* its panel.

**Type scale** (from `secrets.css`; reuse the `.tap-gs-*` classes or mirror them under your own prefix):

| Role | Size | Notes |
| --- | --- | --- |
| kind line | .72rem, uppercase, letter-spaced, 70% | `git-serious · Actions secrets` — the noun class, with a link back up the hierarchy |
| title | 1.55rem / 600 | one line; a `code` title for identifiers |
| subtitle | 1rem, 80% | holder / scope / one fact |
| badges | .74rem pills | state, not decoration (Step 2 tones) |
| subject block | dt .7rem uppercase 60% / dd 1rem | 4–6 facts in a grid, rules above and below |
| section h4 | 1.02rem / 600 | |
| meaning line | .88rem, 72% | max-width 70rem |
| fact | .98rem | |
| row / card body | .9rem | |
| provenance | .85rem, collapsed | |

**Tones are vocabulary, not palette.** `bad` (#991b1b on #fee2e2) = a fact that needs action; `warn` (#92400e on
#fef3c7) = a fact to read; `ok` (#166534 on #dcfce7) = confirmed fine; `muted` (#64748b on #f8fafc) = not
observable / derived context; `scope` (#5b21b6 on #ede9fe) = a classification, not a judgement. **Use a tone
only for what it means** — a stage or a category is never `bad`, and `ok` is never the absence of a finding
we could not look for. A page should have at most one *loud* element in the viewport (a red left rule on the
header when the object is exposed; a red row rule); everything else is quiet.

**Layout primitives:** header with kind/title/sub/badges and a 3px left rule; the subject `dl` grid; sections
separated by a hairline; `.tap-gs-row` (a 3-column grid: name / facts / state, wraps to one column under 900px)
for lists of things with state; `.tap-gs-card` grid for a set of peers the reader compares; `.tap-gs-bearing`
(key / value pairs) for "does this matter here". Code blocks: monospace .8rem on a 4% grey, a 2px left rule
whose colour says what the block is (theirs grey, ours green, refused red dashed).

**Icons (new with this skill).** Every `BaseModel` already ships an `ENTITY_ICON` (Octicon-derived for
github_core, 24-unit grid, GitHub ink). Reuse them; do not draw new glyphs for things that have a type:

- Beside a **title** (the object's own type, 1.25rem, 70% opacity) and beside a **kind line** at 1rem.
- On every **card** and **row** whose first column names an object of a type: the type's icon at 1rem before
  the name. Two different types in one list (a repository row next to an environment row) now read apart
  without the reader parsing a word.
- On **chips that name types** (the query page's "what it needs").
- On **KPI tiles** in a summary strip.
- Render by slug with `{% load git_serious_icons %}{% type_icon "github_core__github_account" %}` (an `<img>`
  from `tap_grid.icon.resolve_icon_url`; a by-slug tag belongs in `tap_web`'s `tap_icons` — file it when a
  second plugin needs it). Never let the icon carry a meaning the text does not (`req-grid-icon-render-2`).
- The shell's reset makes `img` block-level: give the icon class `display: inline-block` or every icon drops
  onto its own line (caught on the first screenshot of this pass).
- Concepts with no type (a PAT grant before slice C, a stage, a severity) get **no bespoke pictogram**: a tone
  badge or a monospace chip. If the concept becomes a type, it gets its icon then — the model is the icon's
  home, so the picture and the data cannot drift apart.

## Step 3: Designing a board

A board is scanned, filtered and acted on. Its cognitive budget is spent on *finding the row*, so:

1. **Summary strip first — one row of 4–6 tiles**, each a number + label + tone + icon: the page's job in
   numbers before any list. If the numbers are the whole point (a ladder, a gauge), draw them (a CSS bar
   with the count on it); otherwise tiles.
2. **One primary list.** If the rows come from a Search, use the standard `table` panel in rows mode
   (`row_url_template`, `quick_filter`, `default_page_size`, sortable columns) — it already does filter,
   sort, paging and row-click, and a custom re-implementation of those is a defect. If the rows come from
   content (a data file) and not from the grid, a `module` Search runner that returns rows is the honest way
   to put them through the same table (`register_search_runner`), and it is *not* the break-glass case —
   there is no Gryphon that could have asked the question.
3. **Group only by the axis the reader acts on**, and put the group's count in its header. Grouping by stage
   is right for "what lands when"; grouping by severity is right for "what do I fix first". Never two
   groupings in one list; offer the other as a sort.
4. **Columns: name first, state second, everything else after; six at most.** The name column carries the
   icon and one line of secondary text (id · category) in .82em muted; the state column is a tone badge;
   numbers are right-aligned and tabular. Anything the reader would need to scroll sideways for is a detail
   for the profile page.
5. **Row click goes to the profile**; make the whole row the target and the name a real `<a>` too.
6. **The three states appear as group headers or tiles, not as blank cells** ("14 not observable" is a
   tile; a row's empty cell is a bug).
7. **Provenance and method collapse at the foot.** Licence, pins, "how these were derived" belong there.

## Step 4: Designing a profile

A profile is read top to bottom once, then returned to for one section. So:

1. **Header answers "what is this and should I worry" in two seconds:** kind line with icon and a link to the
   board; a title; one subtitle fact; 2–4 state badges; a loud left rule only when the object is exposed.
2. **Subject block: the 4–6 facts a reader would otherwise scroll for**, with three-state rendering on each
   (`not recorded` in italics is a state, not a blank).
3. **Sections in the order of the reader's questions**, each with a meaning line: *where it reaches / who
   uses it / does this matter here* for a secret; *what it asks / their text, ours / what it needs / the
   answer here* for a query. The **answer** section — the live result — comes last and is the widest; it is
   what the reader scrolls to on a return visit.
4. **Two columns only when the pair is the point** (their Cypher beside our Gryphon); otherwise one column,
   max-width 70rem for prose, full width for tables.
5. **Prev / next along the board's order** at the foot, and a link to the board in the kind line.
6. **Exact copies of upstream text are attributed inline** (repo @ pin · path) and licensed in provenance.

## Step 5: Cognitive-load checklist (run on the screenshot, not the template)

Take the screenshot (`drive-browser`) and answer each with a yes:

- [ ] Can a reader say the page's job from the first viewport alone?
- [ ] Is there exactly one loud element in the first viewport, or none?
- [ ] Does every section open with a meaning line?
- [ ] Do the three states look different everywhere they can occur?
- [ ] Are there icons beside every typed object in lists, cards and chips — and no icon carrying meaning alone?
- [ ] Is every number derived at render, and does the page say from what?
- [ ] Is the primary list ≤ 6 columns, name first, state second, numbers tabular?
- [ ] Does a row click go somewhere, and is the destination a real link too?
- [ ] Is provenance present and collapsed?
- [ ] Does it hold at ~900px (rows collapse to one column; nothing scrolls sideways except a table in its own container)?
- [ ] **Does the render match the template?** Blank values with the prose intact means the panel type is not
      registered in the running process (restart `web` after editing `apps.py`) or the context key changed.
      A screenshot of the *wrong* page passing this checklist is the presence-not-correctness trap again.

## Step 6: What the query-pack first cut got wrong (so it is not repeated)

The pack page listed 79 rows in a five-column table under a paragraph of prose, with counts typed into
sentences and no summary strip; the query page put the answer table under four sections of text with no
icons and no subject block. The template was right about *facts* and wrong about *order and shape*: the job
("which of these run here, and what lands when") was not answerable from the first viewport; the three
states were badges buried in a column instead of tiles; the list had no icons, so 79 rows of near-identical
text; and the screenshot was never taken, so a blank render (an unregistered panel type) shipped. Every one
of those is a checklist line above.

## Step 7: Record it

The page's spec (`spec-<plugin>-<page>.md`) gets a **Design** subsection: the job sentence, board or profile,
the summary tiles or subject facts chosen, the grouping axis, the loud element, and which icons render
where. The checklist result rides the PR description with the screenshot.
