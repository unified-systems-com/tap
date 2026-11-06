# Web Colour Theme Specification

## Philosophy

A TAP page has one colour theme at a time, chosen by the viewer: light, dark, or the viewer's system setting. The
choice covers the whole UI. A theme that reaches some panels and not others is worse than none, because the panels it
misses become the bright rectangles in a dark page, so this spec states the rule for every surface instead of
listing the ones already done: **no colour in the UI is a literal that ignores the theme.** A colour is a token, and a
token has a light value and a dark value.

The mechanism is the one the chart, stat-card and info-window styles already used (tokens on a root, dark values under
`prefers-color-scheme: dark` and under `[data-theme="dark"]`, the media-query block guarded by `:not([data-theme="light"])`),
promoted from three panels to the page. What was missing was the thing that sets `data-theme`: nothing did, so those
panels could follow only the operating system. This spec adds the setter (a switch in the user menu), the no-flash
script, the palette every stylesheet reads, and the bridge that lets Tailwind utility classes read the same palette.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Whole UI | Every page, panel, overlay and auth page follows the theme; no panel is exempt by omission. |
| 2. | Viewer's choice | Light, dark or system, switchable from the user menu on every page, remembered in the browser. |
| 3. | No flash | The theme is applied before the first paint, so a dark viewer never sees a light page first. |
| 4. | One palette | Plain CSS, Tailwind utilities, canvas-drawn charts and the graph read the same tokens. |
| 5. | Readable | Text on its surface meets 4.5:1 in both themes. |
| 6. | No new server state | The choice lives in the browser; no model, migration or request-time branch. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-theme-tokens | [Palette Tokens](#palette-tokens) | Implemented | `theme.css`: RGB-triplet palette with light, system-dark and forced-dark value sets |
| req-web-theme-init | [Applied Before First Paint](#applied-before-first-paint) | Implemented | `theme-init.js`, a blocking external script in `<head>` of every page that links `theme.css` |
| req-web-theme-toggle | [Light, Dark, System Switch](#light-dark-system-switch) | Implemented | `partials/theme_switch.html` + `theme-toggle.js`; localStorage key `theme`, shared with Django admin |
| req-web-theme-tailwind | [Tailwind Reads The Palette](#tailwind-reads-the-palette) | Implemented | `tailwind.config.js` maps its colours onto `--tap-<name>-<shade>`; templates need no `dark:` variants |
| req-web-theme-header | [Header Bar](#header-bar) | Implemented | Light bar in the light theme, its own dark bar in dark; `--tap-header-*` tokens, contrast-checked |
| req-web-theme-surfaces | [Every Surface Uses Tokens](#every-surface-uses-tokens) | Implemented | Stylesheets, templates and panel scripts carry no theme-blind colour literal, except the fixed cases named there |
| req-web-theme-graph | [Graph Canvas](#graph-canvas) | Implemented | The canvas background is theme-invariant (fixed light); the chrome around it themes |
| req-web-theme-contrast | [Readable In Both Themes](#readable-in-both-themes) | Implemented | Text on its surface at least 4.5:1, measured in a real browser |
| req-web-theme-scope | [Scope And Plugin Surfaces](#scope-and-plugin-surfaces) | Implemented | What the theme does not reach: plugin-owned stylesheets, error pages |

## Requirements

### Palette Tokens
----
RID: `req-web-theme-tokens`

Status: `Implemented`

`tap_web/static/tap_web/css/theme.css` defines the palette as custom properties named `--tap-<name>-<shade>` (`--tap-slate-200`,
`--tap-red-700`, ...), plus `--tap-white`, `--tap-canvas`, `--tap-chrome`, and the fixed `--tap-graph-bg` / `--tap-graph-grid`. Each value is a space-separated
RGB triplet, so plain CSS reads `rgb(var(--tap-slate-200))` and `rgb(var(--tap-slate-200) / 0.5)`, and Tailwind reads
the same variable with its own alpha.

#### Implementation

- Light values are Tailwind's default palette, so the light theme is the same colours as before the theme existed.
- Dark neutrals rise in lightness with elevation (page, surface, hover, border) and the text ramp is the mirror image;
  dark chromatic steps are the mirrored step (`red-50` becomes `red-950`'s value, `red-700` becomes `red-300`'s).
- The dark set is written twice: under `@media (prefers-color-scheme: dark)` as `:root:not([data-theme="light"])`, and
  under `:root[data-theme="dark"]`. The two blocks must stay identical.
- `:root { color-scheme: light dark }` with `[data-theme="light"]` and `[data-theme="dark"]` narrowing it, so scrollbars
  and native controls follow the theme.
- Panel-level token sets (`--tap-chart-*`, `--statcard-*`, `--tap-info-*`) keep their own definitions, with the same
  three-block shape, and now respond to `data-theme` because something sets it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-theme-tokens-1 | Light And Dark For Every Token | Implemented | Every token defined for the light theme is also defined in the system-dark block and the forced-dark block. | `test_theme_assets.py` |
| req-web-theme-tokens-2 | Dark Blocks Identical | Implemented | The system-dark block and the forced-dark block hold the same declarations. | `test_theme_assets.py` |
| req-web-theme-tokens-3 | Forced Light Wins | Implemented | The system-dark block is guarded by `:not([data-theme="light"])`, so an explicit light choice beats a dark system setting. | `test_theme_assets.py` |
| req-web-theme-tokens-4 | Triplet Values | Implemented | Palette values are RGB triplets, usable with an alpha channel. | `test_theme_assets.py` |

### Applied Before First Paint
----
RID: `req-web-theme-init`

Status: `Implemented`

`tap_web/static/tap_web/js/theme-init.js` is a plain, blocking `<script src>` in `<head>`, before the stylesheets. It reads
localStorage `theme` (`light`, `dark` or `auto`; the key and values Django admin's own switch uses), guarded so blocked
storage is not an error, and sets `<html data-theme>` to `light` or `dark`. For `auto`, or any missing or unrecognised value,
it leaves the attribute off, so `prefers-color-scheme` decides. It records the choice as `data-theme-mode`.

#### Implementation

- External, not inline: it needs no script-source exception under a content security policy (none is set today),
  and blocking, not deferred, which is what removes the flash.
- Included from `tap_web/partials/theme_head.html`, which `base.html`, the allauth shell and every standalone auth page
  include in `<head>`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-theme-init-1 | Blocking Head Script | Implemented | Every full page links `theme-init.js` as a non-deferred, non-async script in `<head>`, before any stylesheet. | `test_theme_assets.py` |
| req-web-theme-init-2 | Guarded Storage | Implemented | The script reads localStorage inside `try`/`catch` and falls back to the system scheme. | `test_theme_assets.py` |
| req-web-theme-init-3 | Every Full Page | Implemented | `base.html`, the allauth layout and each standalone auth template include `theme_head.html`. | `test_theme_assets.py` |

### Light, Dark, System Switch
----
RID: `req-web-theme-toggle`

Status: `Implemented`

A three-button group (Light, System, Dark) in the **user menu** (the dropdown opened from the avatar at the top right), as a labelled "Theme" row between the identity and Sign out; it shows the current choice through `aria-pressed` and is reachable by keyboard (the menu is a `<details>`, the buttons are ordinary tab stops). It is not a permanent header control. A page with no user menu (signed-out pages, the auth pages) shows the same group inline in its header, because there is nowhere else to put it.
`theme-toggle.js` stores the choice in localStorage `theme` (removing the key for System), applies it to `<html>`, marks
the pressed button with `aria-pressed`, and announces `tap:themechange` on `document` with `{mode, scheme}` so canvas-drawn
surfaces redraw. It follows a change made in another tab, and an operating-system change while the mode is System.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-theme-toggle-1 | Switch On Every Page | Implemented | Every full page renders the switch with the three choices: in the user menu when there is one, else inline in the header. | `test_theme_assets.py` |
| req-web-theme-toggle-5 | In The User Menu | Implemented | In `base.html` the switch is inside the user-menu dropdown; the only other include is the signed-out fallback. | `test_theme_assets.py` |
| req-web-theme-toggle-2 | Accessible | Implemented | The group is labelled, each button has an accessible name and `aria-pressed`. | `test_theme_assets.py` |
| req-web-theme-toggle-3 | Announces Change | Implemented | A change dispatches `tap:themechange`; the script contains no `innerHTML` assignment. | `test_theme_assets.py` |
| req-web-theme-toggle-4 | No Server State | Implemented | The choice is stored only in the browser; no model or migration carries it. | Proven in a browser |

### Tailwind Reads The Palette
----
RID: `req-web-theme-tailwind`

Status: `Implemented`

`tailwind.config.js` replaces the colours Tailwind's utilities draw (`slate`, `gray`, `red`, `green`, `amber`, `blue`, `indigo`,
`orange`, `yellow`, `canvas`) with `rgb(var(--tap-<name>-<shade>) / <alpha-value>)`, so `bg-slate-50` or `text-red-700` is the
light value in a light theme and the mirrored dark value in a dark one, in core and plugin templates alike, with no `dark:`
variants. `white` and `black` stay literal for text on a solid fill; a white surface is `bg-white`, which `theme.css` points at
`--tap-white`. A solid fill that keeps light text in both themes uses a component class built on `--tap-chrome`, not a
palette step.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-theme-tailwind-1 | Palette Is Variables | Implemented | The compiled `tailwind.css` draws slate, red, green, amber, blue, indigo, gray and canvas utilities from `--tap-*` variables, not hex or fixed rgb. | `test_theme_assets.py` |
| req-web-theme-tailwind-2 | White Surface Follows Theme | Implemented | `theme.css` maps `.bg-white` to the surface token. | `test_theme_assets.py` |
| req-web-theme-tailwind-3 | Solid Fills Keep Light Text | Implemented | No template pairs `text-white` with a palette-step fill. | `test_theme_assets.py` |

### Header Bar
----
RID: `req-web-theme-header`

Status: `Implemented`

The header is a light bar in the light theme (the canvas tone `#f1f0ec` with a thin bottom border, dark text and icons, so a dark
logo and the menu read natively) and its own dark bar in the dark theme. Every header colour is a `--tap-header-*` token
(`bg`, `border`, `fg`, `link`, `dim`, `wash`, `session`, `avatar`) with a light and a dark value, used by the bar, the
breadcrumb, the palette affordance, the user-menu trigger and the auth pages' header. The `[ session ]` label is amber-800 on the
light bar and amber-300 on the dark one. The site glyph carries its own fixed light tile and is not recoloured.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-theme-header-1 | Contrast On The Bar | Implemented | Header text, secondary text, the session label and the avatar initial are at least 4.5:1 on the bar, in both themes. | `test_theme_assets.py` |
| req-web-theme-header-2 | Light Bar, Dark Bar | Implemented | The light bar is the canvas tone, the dark bar is dark, and the bar has a bottom border. | `test_theme_assets.py` |

### Every Surface Uses Tokens
----
RID: `req-web-theme-surfaces`

Status: `Implemented`

Core stylesheets, templates and panel scripts take their colours from the palette or from a panel's own token set. The
fixed cases, each deliberate:

- **Data-carried colours** (a model's node fill, a status badge's fill and text, a layout module's colours) are data and
  stay as written.
- **The graph canvas** and everything drawn in it (`req-web-theme-graph`), and the site glyph and favicon with their own light tile.
- **Container labels** drawn over a container's own pastel fill keep dark ink.

Table cells, pills, marks and sparklines are built with `rgb(var(--tap-...))` in inline style (never an SVG presentation
attribute, which does not take `var()`), and form controls take the surface and ink of the theme.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-theme-surfaces-1 | No Literal Colours In Core Stylesheets | Implemented | Colour declarations in the core stylesheets are tokens, except the fixed cases above and shadows. | `test_theme_assets.py` lists the allowed files and literals |
| req-web-theme-surfaces-2 | Table Cells | Implemented | `panel-table.js` colours pills, marks and the sparkline with palette tokens, not hex literals. | `test_theme_assets.py` |
| req-web-theme-surfaces-3 | Panels Rendered Dark | Implemented | Every page type renders with a dark surface and no `.tap-panel-error` under `data-theme="dark"`. | Proven in a browser |
| req-web-theme-surfaces-4 | Form Controls | Implemented | Fields take the theme's surface and ink at zero specificity. | `test_theme_assets.py` |
| req-web-theme-surfaces-5 | Table Popovers | Implemented | A table header's pop-over (`header_tooltip`) and any Tabulator popup take surface, ink and rule from tokens, never the library's white. | `test_table_polish.py`; see `req-web-stdpanel-table-config-24` |

### Graph Canvas
----
RID: `req-web-theme-graph`

Status: `Implemented`

The graph panel's canvas is **theme-invariant** (George, 2026-10-20): the Cytoscape canvas and its grid
(`.tap-cy-static-grid`, the panel's graph container) keep one uniform light background, `--tap-graph-bg` (the page canvas
`#f1f0ec`) with the existing grid lines `--tap-graph-grid`, in every theme, because node colours are data and lose fidelity
against a dark ground. Both tokens are defined once and never redefined for dark. Everything drawn inside the canvas
(labels, edges, borders, the toolbar, scope boxes, the Cytoscape stylesheet) keeps its light-mode colours. Everything around it
follows the theme: the panel header and frame, the page, and the info window, whose `--tap-info-*` tokens carry dark
values. The same rule covers the site glyph and favicon: each carries its own fixed light background tile.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-theme-graph-1 | Canvas Background Is Theme-Invariant | Implemented | The canvas background and grid are fixed tokens with one light value, absent from the dark blocks. | `test_theme_assets.py` |
| req-web-theme-graph-2 | Canvas Contents Keep Light Colours | Implemented | `panel-graph.js` has no theme hook and no palette token; the Cytoscape stylesheet is the light-mode one. | `test_theme_assets.py` |
| req-web-theme-graph-3 | Surrounding UI Follows | Implemented | The info window and the panel chrome around the canvas follow the theme. | `test_theme_assets.py` |

### Readable In Both Themes
----
RID: `req-web-theme-contrast`

Status: `Implemented`

Text on its own surface is at least 4.5:1 in both themes on the key surfaces: page, table, stat card, chart frame, info
window, forms, header, auth pages. It is measured in a real browser from computed colours, not assumed from the token
values; disabled controls are exempt.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-theme-contrast-1 | Measured In A Browser | Implemented | A browser pass over the playground pages, the administrivia pages and the login page finds no text below 4.5:1 in either theme on the surfaces core owns. | Light-mode captions below 4.5:1 (null dashes, some slate-400 labels) pre-date the theme and are not touched |

### Scope And Plugin Surfaces
----
RID: `req-web-theme-scope`

Status: `Implemented`

Trace: `narrative` — it states what the theme does not cover; there is no behaviour to test beyond the documentation row

The theme covers what core ships. Two things sit outside it, by design:

- **A plugin's own stylesheet or script** (a `.css` or `.js` a plugin ships, a plugin panel's inline colours) is the plugin's to
  convert to the palette tokens; a plugin that uses only Tailwind utilities is covered by `req-web-theme-tailwind`. A plugin
  that mixes Tailwind text classes with its own literal light backgrounds will read badly in a dark theme until it adopts the tokens.
- **Error pages.** `404.html`/`500.html` do not exist yet (`req-tap-serving-error-pages`, Backlog); when they land they include
  `tap_web/partials/theme_head.html` like every other full page.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-theme-scope-1 | Plugin Surfaces Named | Implemented | The limits above are stated here, so a plugin author knows the convention to adopt. | Documentation |
