# Web Chrome Specification

## Philosophy

TAP web chrome is the persistent application shell around pages. It is not a Page, and it is not a Panel that every Page happens to mount. Pages own document content and route-specific panel layout; Chrome owns the stable application affordances that surround that content: brand identity, location, global navigation, user identity, global feedback, optional live signals, and shortcuts.

Chrome is deliberately **panel-like** rather than a reinvention. A `ChromeSurface` hosts small, typed, reusable `ChromeEntry` objects in named regions, using the same broad ideas that make Pages and Panels work: graph-backed objects, declarative placement, registered type renderers, server-rendered fragments, and HTMX-friendly refresh. The important difference is lifecycle. Chrome persists while pages change; loading a new Page must not require rebuilding every chrome entry.

The security boundary is strict: graph-backed chrome activates only after the caller is authorized to read the Page/chrome graph. Login, denial, provider-error, and other pre-auth/error pages are static/auth-owned render surfaces; they do not mount `ChromeSurface` and they do not read graph-backed chrome entries.

## Prior Art Applied

This design follows mature UI extension patterns without copying code:

- VS Code contribution points separate commands, menu placement, views, containers, and keybindings. TAP adapts the separation of placement from activation and shortcut dispatch. Source: <https://code.visualstudio.com/api/references/contribution-points>
- Grafana plugin metadata separates plugin-provided pages/panels from navigation inclusion, role/action visibility, and icons. TAP adapts the idea that chrome placement is metadata around an affordance, not the affordance's implementation. Source: <https://grafana.com/developers/plugin-tools/reference/plugin-json>
- WordPress `add_menu_page` treats menu visibility capability as separate from the target page's own authorization. TAP keeps the same invariant: showing a chrome entry is UX; activating its target still authorizes normally. Source: <https://developer.wordpress.org/reference/functions/add_menu_page/>
- Turbo and Inertia both establish persistent app-shell patterns where layout/chrome can survive page visits. TAP adapts the lifecycle shape while retaining server-rendered Django templates. Sources: <https://turbo.hotwired.dev/handbook/building>, <https://inertiajs.com/docs/v3/the-basics/layouts>
- HTMX supports fragment refresh via triggers such as periodic polling and out-of-band swaps. TAP uses that for chrome signals/badges instead of introducing a push channel in v1. Sources: <https://htmx.org/attributes/hx-trigger/>, <https://htmx.org/attributes/hx-swap-oob/>
- WAI-ARIA Authoring Practices and WCAG define the accessibility floor for navigation, breadcrumbs, menu buttons, dialogs, keyboard access, focus visibility, status updates, contrast, and target size. TAP adapts those patterns directly rather than inventing custom ARIA behavior. Sources: <https://www.w3.org/WAI/ARIA/apg/patterns/breadcrumb/>, <https://www.w3.org/WAI/ARIA/apg/patterns/menu-button/>, <https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/>, <https://www.w3.org/WAI/WCAG22/quickref/>

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Graph-Native | Chrome surfaces and entries are first-class graph-backed web objects after authorization. |
| 2. | Persistent | Page loads update the page host without rebuilding the whole chrome shell. |
| 3. | Composable | Chrome entries are typed, panel-like affordances mounted into named surface regions. |
| 4. | Secure | Graph-backed chrome is absent before Page/chrome read authorization; visibility never replaces target authorization. |
| 5. | Explicit | Entry placement, activation, shortcut bindings, and live signal refresh are separate contracts. |
| 6. | Conservative | V1 uses server-rendered fragments, Django/static assets, and HTMX-compatible refresh; no new dependency is required. |
| 7. | Accessible | Chrome entries are keyboard-operable, screen-reader legible, and aligned with WAI-ARIA/WCAG patterns. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-chrome-surface | [Chrome Surface Objects](#chrome-surface-objects) | Proposed | Graph-backed persistent shell host with named regions and slots |
| req-web-chrome-authz | [Chrome Authorization Boundary](#chrome-authorization-boundary) | Proposed | Graph-backed chrome activates only after Page/chrome read authorization |
| req-web-chrome-entry | [Chrome Entry Objects](#chrome-entry-objects) | Proposed | Panel-like graph objects mounted into chrome regions |
| req-web-chrome-entry-types | [Chrome Entry Type Registry](#chrome-entry-type-registry) | Proposed | Registered entry types own rendering, assets, and activation interpretation |
| req-web-chrome-accessibility | [Chrome Accessibility](#chrome-accessibility) | Proposed | Chrome surfaces and entries follow native HTML, WAI-ARIA, WCAG, and keyboard/focus contracts |
| req-web-chrome-placement | [Chrome Entry Placement](#chrome-entry-placement) | Proposed | Surface layout plus hotlink-style edges bind entries to slots |
| req-web-chrome-activation | [Chrome Entry Activation](#chrome-entry-activation) | Proposed | Activation is optional and explicit; `null` means inert |
| req-web-chrome-shortcuts | [Chrome Shortcuts](#chrome-shortcuts) | Proposed | Optional shortcut bindings dispatch entry activation through one central listener |
| req-web-chrome-signals | [Chrome Signals](#chrome-signals) | Proposed | Entries may expose HTMX-refreshable badge/status fragments |
| req-web-chrome-branding | [Branding Entries](#branding-entries) | Proposed | Site icon and product mark are chrome entries, with branding source seams |
| req-web-chrome-builtin-entries | [Built-In Chrome Entries](#built-in-chrome-entries) | Proposed | Existing product mark, breadcrumb, palette, session tag, user menu, feedback, and mini-graph map to entries/regions |
| req-web-chrome-page-host | [Persistent Page Host](#persistent-page-host) | Proposed | Page content loads independently of chrome shell refresh |
| req-web-chrome-migration | [Navigation Spec Migration](#navigation-spec-migration) | Proposed | Supersedes nav-as-panel with ChromeSurface/ChromeEntry architecture |

## Requirements

### Chrome Surface Objects
----
RID: `req-web-chrome-surface`

Status: `Proposed`

A `ChromeSurface` is the graph-backed object representing a persistent web shell. It declares the named chrome regions and slot layout into which `ChromeEntry` objects are mounted.

#### Implementation

- `ChromeSurface` is a TAP-managed node in the canonical web dimension.
- A surface has at minimum:
  - `slug` - stable identifier for the shell, e.g. `authenticated-app`.
  - `name` - human-readable name.
  - `description` - optional human-readable purpose.
  - `layout` - structured JSON declaring regions and slots.
  - `config` - structured JSON for surface-level rendering options.
- The initial authenticated app surface declares, at minimum:
  - `topbar.leading`
  - `topbar.path`
  - `topbar.trailing`
  - `feedback`
  - `overlay`
  - `page-host`
- `page-host` is the region into which the current Page response is rendered/swapped. It is not a `ChromeEntry` slot.

#### Development

This object is the replacement for treating `tap_web/templates/tap_web/base.html` as an implicit, unmodeled source of truth. The base template remains the implementation substrate, but the chrome shape becomes inspectable and graph-addressable.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-chrome-surface-1 | Graph Node | Proposed | `ChromeSurface` is a TAP-managed graph node in the web dimension. | |
| req-web-chrome-surface-2 | Named Regions | Proposed | The surface declares named regions, including a page host region. | |
| req-web-chrome-surface-3 | No Page Coupling | Proposed | A `ChromeSurface` is not a `Page` and is not mounted per Page. | |
| req-web-chrome-surface-4 | Persistent Lifecycle | Proposed | The active surface can persist across Page content swaps. | |


### Chrome Authorization Boundary
----
RID: `req-web-chrome-authz`

Status: `Proposed`

Graph-backed chrome activates only for callers authorized to read Page/chrome graph data. Pre-auth, login, denial, provider-error, and other static auth/error pages render themselves and do not mount `ChromeSurface`.

#### Implementation

- A request must pass the Page/chrome read gate before `ChromeSurface`, `ChromeEntry`, chrome signal endpoints, or chrome-backed navigation data are read.
- The current implementation's relevant permission is `grid.read`; a future narrower Page/chrome read capability may replace it.
- Login and auth/error templates may render static product name/icon/branding from settings or static assets, but that is not graph-backed chrome and is not a `ChromeSurface` consumer.
- Chrome entry visibility never authorizes the target action. Activating an entry runs the target Page, view, form, or fragment authorization normally.
- Hidden or unauthorized entries must not request their signals or leak counts through badge refresh endpoints.

#### Development

This is the security lesson from the navigation review: universal chrome must not perform graph reads before authorization. The target architecture removes the need for a read-free degraded breadcrumb in graph-backed chrome because graph-backed chrome simply is not active before the read gate.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-chrome-authz-1 | Post-Read-Gate Only | Proposed | Graph-backed chrome reads happen only after Page/chrome read authorization. | |
| req-web-chrome-authz-2 | Static Auth Pages Are Non-Consumers | Proposed | Login/auth/error pages do not mount `ChromeSurface` or read `ChromeEntry`. | |
| req-web-chrome-authz-3 | Visibility Is Not Authorization | Proposed | A visible entry's target still performs normal authorization on activation. | |
| req-web-chrome-authz-4 | Signal Authz | Proposed | Signal endpoints compute data under the current caller and do not reveal unauthorized counts/status. | |


### Chrome Entry Objects
----
RID: `req-web-chrome-entry`

Status: `Proposed`

A `ChromeEntry` is a small, panel-like, graph-backed affordance mounted into a `ChromeSurface`. It owns presentation metadata, entry-type identity, optional activation, optional shortcut bindings, and optional live signal configuration.

#### Fields

| Field | Type | Required | Notes |
| --- | --- | :---: | --- |
| `slug` | CharField | Yes | Stable kebab-case identifier. |
| `name` | CharField | Yes | Human-readable name. |
| `description` | TextField | No | What the entry is for. |
| `entry_type` | CharField | Yes | Registered entry type slug. |
| `config` | JSONField object | Yes | Entry-type-specific presentation/configuration. |
| `activation` | JSONField object or null | No | Explicit activation contract. `null` or missing means inert. |
| `shortcuts` | JSONField list | No | Optional shortcut bindings for this entry's activation. |
| `signal` | JSONField object or null | No | Optional live badge/status refresh contract. |

#### Implementation

- `ChromeEntry` is not a `Panel`, but it reuses the same architectural pattern: graph-backed instance plus registered type renderer.
- `activation`, `shortcuts`, and `signal` are independent:
  - An entry can render without activation.
  - An entry can activate without shortcuts.
  - An entry can expose a signal without changing activation.
- Entry `config` must be validated by the entry type. Invalid configuration fails loud rather than silently rendering a broken shell.

#### Development

The object exists because chrome entries deserve identity. They are not just template snippets: they may have placement, lifecycle, optional live status, shortcut bindings, and future user/product-line configuration.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-chrome-entry-1 | Graph Node | Proposed | `ChromeEntry` is a TAP-managed graph node in the web dimension. | |
| req-web-chrome-entry-2 | Panel-Like Instance | Proposed | Entry instances carry config and resolve through a registered entry type. | |
| req-web-chrome-entry-3 | Optional Activation | Proposed | Missing or `null` activation means the entry is inert. | |
| req-web-chrome-entry-4 | Optional Shortcuts | Proposed | Shortcuts are optional bindings on entries with activation. | |
| req-web-chrome-entry-5 | Optional Signal | Proposed | Signals are optional and do not change entry activation semantics. | |


### Chrome Entry Type Registry
----
RID: `req-web-chrome-entry-types`

Status: `Proposed`

Chrome entry types are registered in code, analogous to panel types. A type owns rendering behavior, static assets, config validation, and activation interpretation for entries of that type.

#### Implementation

- `tap_web` exposes a `chrome_entry_type_registry`.
- A `ChromeEntryType` declares, at minimum:
  - `slug`
  - `template_name` or equivalent renderer hook
  - `css` and `js` static asset lists
  - config validation behavior
  - supported activation kinds, if any
- Entry static assets are owned by the type, not by each entry instance.
- Type assets are local Django static assets; external URLs are not allowed.

#### Development

This mirrors the Panel asset decision: instance-level asset overrides invite drift and silently mask inconsistent configuration. Chrome entries should stay even stricter because they are persistent shell code.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-chrome-entry-types-1 | Registry Exists | Proposed | Chrome entry types register at app startup. | |
| req-web-chrome-entry-types-2 | Type Owns Assets | Proposed | Static assets come from the entry type, not the entry instance. | |
| req-web-chrome-entry-types-3 | Local Assets Only | Proposed | Entry assets resolve through local Django static paths. | |
| req-web-chrome-entry-types-4 | Config Validation | Proposed | Type-specific config is validated before render. | |


### Chrome Accessibility
----
RID: `req-web-chrome-accessibility`

Status: `Proposed`

Chrome surfaces and entries must be accessible by construction. Every built-in and plugin-provided `ChromeEntryType` must define the semantic, keyboard, focus, and announcement behavior needed for disabled users, following native HTML first and WAI-ARIA/WCAG patterns where native elements are insufficient.

#### Implementation

- Prefer native HTML controls and landmarks before ARIA:
  - use `<a>` for navigation;
  - use `<button>` for actions;
  - use `<header>`, `<nav>`, and `<main>` for shell landmarks;
  - use standard form controls for interactive inputs.
- ARIA is additive, not decorative. Entry types must not add ARIA roles/states that contradict native semantics.
- `ChromeSurface` rendering provides:
  - a labelled application/header navigation landmark where appropriate;
  - a stable `<main>` or equivalent page-host landmark for Page content;
  - a route for keyboard users to move from persistent chrome to page content without traversing every chrome control on every page transition.
- Breadcrumb navigation follows the WAI-ARIA breadcrumb pattern:
  - the breadcrumb is inside a labelled `nav`;
  - the current page segment uses `aria-current="page"` when it is represented in the breadcrumb;
  - separators are not exposed as misleading interactive content unless they are actual controls.
- Menu/disclosure-style entries, such as the user menu and breadcrumb popovers, follow menu-button/disclosure semantics:
  - the trigger is a button or native disclosure control;
  - expanded/collapsed state is communicated;
  - Escape closes the popup;
  - focus behavior is predictable and returns to the trigger when appropriate.
- Overlay entries, such as the command palette, follow modal dialog behavior:
  - focus moves into the overlay on open;
  - Tab and Shift-Tab stay within the overlay while modal;
  - Escape closes the overlay;
  - focus returns to the invoker on close.
- Every activation reachable by pointer must be reachable by keyboard, except activation explicitly marked non-interactive (`activation: null`).
- Focus indicators must be visible and must not be obscured by sticky chrome.
- Text, icons conveying meaning, badges, and focus indicators must meet WCAG contrast expectations.
- Interactive chrome targets must be sized and spaced to meet WCAG 2.2 target-size expectations unless an explicit exception applies.
- Chrome signals/badges must not spam assistive technology:
  - routine polling updates are quiet by default;
  - important state changes may use a polite status/live region;
  - urgent interruptions require a deliberately specified reason.
- `ChromeEntryType` definitions document their accessible name source, role/landmark behavior, state attributes, keyboard interactions, focus behavior, and live-announcement behavior when applicable.

#### Development

Chrome is persistent and shared by every Page, so accessibility defects here multiply across the application. The right time to specify this is before entry types proliferate. This is not a full accessibility program or certification claim; it is the platform contract that prevents custom chrome entries from silently bypassing keyboard and screen-reader basics.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-chrome-accessibility-1 | Native First | Proposed | Entry renderers use native semantic elements before ARIA roles. | |
| req-web-chrome-accessibility-2 | Entry Type Contract | Proposed | Each `ChromeEntryType` declares accessible name, role/state, keyboard, focus, and live-announcement behavior as applicable. | |
| req-web-chrome-accessibility-3 | Landmarks | Proposed | The surface exposes labelled chrome/navigation landmarks and a stable page host landmark. | |
| req-web-chrome-accessibility-4 | Keyboard Operable | Proposed | Interactive chrome entries are operable by keyboard and protect typing contexts. | Cross-ref `req-web-chrome-shortcuts`. |
| req-web-chrome-accessibility-5 | Focus Managed | Proposed | Popovers/overlays manage focus predictably and return focus to the invoker when appropriate. | |
| req-web-chrome-accessibility-6 | Current Location Communicated | Proposed | Breadcrumb/current-location entries communicate current state with `aria-current` or an equivalent pattern. | |
| req-web-chrome-accessibility-7 | Signals Announce Deliberately | Proposed | Signal refreshes are quiet by default and use live/status regions only for deliberate user-facing changes. | |
| req-web-chrome-accessibility-8 | Contrast And Target Size | Proposed | Chrome controls, meaningful icons, badges, and focus indicators meet WCAG contrast and target-size expectations. | |


### Chrome Entry Placement
----
RID: `req-web-chrome-placement`

Status: `Proposed`

Chrome entry placement is declarative. A `ChromeSurface` layout declares slots, and hotlink-style edges bind `ChromeEntry` nodes to those slots.

#### Implementation

- `ChromeSurface.layout` declares region/slot ids.
- A web-dimension edge, e.g. `USES_CHROME_ENTRY`, links a `ChromeSurface` to a `ChromeEntry`.
- The edge carries the target slot id in a hotlink-compatible property, following the Page-to-Panel pattern.
- Exact-mode consistency validation ensures every linked entry targets an existing surface slot and every required slot has a linked entry.
- Ordering within a region is layout-defined, not inferred from database row order.

#### Development

The Page/Panel hotlink system already solved the "layout slot and graph edge must agree" problem. Chrome should reuse that shape instead of inventing a parallel binding scheme.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-chrome-placement-1 | Layout Declares Slots | Proposed | Surface layout has stable region and slot ids. | |
| req-web-chrome-placement-2 | Edge Binds Entry | Proposed | Edges bind `ChromeEntry` nodes to surface slots. | |
| req-web-chrome-placement-3 | Hotlink Consistency | Proposed | Slot ids on edges and layout are validated consistently. | |
| req-web-chrome-placement-4 | Stable Order | Proposed | Region order is determined by layout, not incidental query order. | |


### Chrome Entry Activation
----
RID: `req-web-chrome-activation`

Status: `Proposed`

Chrome entry activation is the explicit behavior triggered by a click, keyboard shortcut, palette selection, or future non-web command surface. Activation is optional. No activation, or `activation: null`, means the entry is presentation-only and inert.

#### Implementation

- Activation is represented as a structured JSON object, not an ad hoc JavaScript callback string.
- Initial activation kinds may include:
  - `navigate` - navigate to a same-origin path.
  - `open_overlay` - open a chrome-owned overlay such as the command palette.
  - `post_form` - submit a CSRF-protected form such as sign out.
  - `refresh_region` - request a chrome/page fragment refresh.
- Entry types declare which activation kinds they support.
- Activation targets must be same-origin unless a later spec explicitly designs external-link behavior.
- Activation does not bypass authorization at the target.

#### Development

"Activation" is the shared vocabulary that keeps clicks, shortcuts, and future AI-driven invocation aligned without overloading the term "shortcut." A shortcut is only one way to trigger activation.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-chrome-activation-1 | Explicit Object | Proposed | Entry activation is a structured object or `null`. | |
| req-web-chrome-activation-2 | Null Means Inert | Proposed | Missing or null activation renders no activation action. | Site icon/product mark may be inert. |
| req-web-chrome-activation-3 | Type-Supported | Proposed | Entry types declare supported activation kinds. | |
| req-web-chrome-activation-4 | Same-Origin Default | Proposed | V1 activation targets are same-origin. | |
| req-web-chrome-activation-5 | Target Authz Still Runs | Proposed | Activated targets perform their normal authorization. | |


### Chrome Shortcuts
----
RID: `req-web-chrome-shortcuts`

Status: `Proposed`

Shortcuts are optional bindings that trigger entry activation through one central shortcut listener. They are a chrome/platform capability, not one-off `keydown` handlers scattered across entry JavaScript.

#### Implementation

- A small central shortcut dispatcher owns document-level key handling.
- Entry shortcut bindings declare:
  - key chord
  - optional platform override, e.g. macOS `cmd+k` vs non-macOS `ctrl+k`
  - context rule, e.g. authenticated app shell and no text input focus
  - activation target, inherited from the entry unless explicitly scoped
- Entries with `activation: null` cannot declare active shortcuts.
- Text inputs, textareas, contenteditable surfaces, and editor contexts are protected by default.
- Duplicate active bindings fail loud in development/test.
- Existing direct listeners, such as the command palette's Cmd/Ctrl-K binding, migrate to the dispatcher.

#### Development

The current chrome has locally owned handlers: palette opens on a `palette.js` document listener, user menu and breadcrumb popovers each own Escape handling. That is a reasonable v0 state, but it is not a platform shortcut model. This requirement standardizes shortcuts without requiring user-customizable keymaps in v1.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-chrome-shortcuts-1 | Central Dispatcher | Proposed | One dispatcher owns global shortcut handling. | |
| req-web-chrome-shortcuts-2 | Optional Bindings | Proposed | Shortcuts are optional and attach to activation. | |
| req-web-chrome-shortcuts-3 | Input Protection | Proposed | Typing contexts are protected by default. | |
| req-web-chrome-shortcuts-4 | Conflict Detection | Proposed | Duplicate active bindings fail loud in development/test. | |
| req-web-chrome-shortcuts-5 | Existing Listeners Migrate | Proposed | Palette/user-menu/breadcrumb shortcut-like behavior migrates or is explicitly scoped. | |

#### Non-Goals

- User-customizable keymaps.
- Shortcut editor UI.
- Multi-step key chords.
- Plugin shortcut marketplace.


### Chrome Signals
----
RID: `req-web-chrome-signals`

Status: `Proposed`

Chrome signals are optional live badge/status projections for entries. V1 defines only the refresh contract, not a general alert/notification node model.

#### Implementation

- A signal declaration names how the entry fetches its current badge/status.
- V1 may use HTMX polling on the signal fragment:

```html
<span
  hx-get="/chrome/signals/<entry-slug>/"
  hx-trigger="load, every 30s, tap:chrome-refresh from:body"
  hx-swap="outerHTML"></span>
```

- A later batching endpoint may refresh multiple visible entries at once using JSON or HTMX out-of-band swaps.
- The signal response is a narrow projection, for example:

```json
{
  "entry": "collectors",
  "state": "critical",
  "count": 3,
  "label": "3 failed collector runs",
  "detail_url": "/administrivia/collectors?status=failed",
  "updated_at": "2026-07-02T18:20:00Z"
}
```

- Signal computation runs under the current caller and may use service-layer reads, Search/Gryphon, or other approved read surfaces.
- A hidden or unauthorized entry does not request its signal.

#### Development

This is the place for alert badges on chrome entries, but not the alert store itself. If alerts gain lifecycle such as unread, acknowledged, dismissed, resolved, recipient, or assignment, they need a dedicated future model/spec. The chrome badge remains a projection over whatever authoritative source owns the state.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-chrome-signals-1 | Optional Signal | Proposed | Entries may declare no signal. | |
| req-web-chrome-signals-2 | HTMX-Compatible Refresh | Proposed | V1 signal refresh can be implemented as server-rendered HTMX fragments. | |
| req-web-chrome-signals-3 | Narrow Projection | Proposed | Signal responses expose only count/state/label/link-style projection data. | |
| req-web-chrome-signals-4 | Current Caller Authz | Proposed | Signal computation runs under the current caller and cannot leak unauthorized data. | |
| req-web-chrome-signals-5 | Alert Model Deferred | Proposed | This spec does not define persistent notification/alert lifecycle nodes. | |


### Branding Entries
----
RID: `req-web-chrome-branding`

Status: `Proposed`

The site-wide icon and product mark are first-class chrome entries. They are presentation entries by default; `activation: null` is valid and means they do not navigate or trigger behavior.

#### Implementation

- Built-in branding entry types include:
  - `site-icon`
  - `product-mark`
- `site-icon` displays the configured product/site icon in chrome.
- `product-mark` displays the configured product name.
- Favicon and site icon are related but separate contracts:
  - Favicon belongs to browser chrome.
  - Site icon belongs to TAP chrome.
- V1 may seed branding entry config from settings/static assets, but authenticated chrome uses graph-backed `ChromeEntry` instances after authorization.
- Static login/auth/error pages are responsible for their own brand rendering and do not consume graph-backed branding entries.
- Future product-line branding may bundle product name, site icon, favicon, and visual tokens under a named brand/profile, but that is not required for v1.

#### Development

The site icon has been wanted as a real product-line affordance. Modeling it as a `ChromeEntry` keeps it swappable without overloading `TAP_PRODUCT_NAME` or treating favicon as the in-app brand source.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-chrome-branding-1 | Site Icon Entry | Proposed | A built-in `site-icon` entry type exists. | |
| req-web-chrome-branding-2 | Product Mark Entry | Proposed | A built-in `product-mark` entry type exists. | |
| req-web-chrome-branding-3 | Inert Allowed | Proposed | Branding entries may use `activation: null`. | |
| req-web-chrome-branding-4 | Favicon Separate | Proposed | Browser favicon is not the same contract as the in-app site icon. | |
| req-web-chrome-branding-5 | Product-Line Seam | Backlog | A future brand/profile object may group name/icon/favicon/tokens. | |


### Built-In Chrome Entries
----
RID: `req-web-chrome-builtin-entries`

Status: `Proposed`

The current app chrome is migrated into built-in entries and regions rather than remaining hand-coded in `base.html`.

#### Inventory

| Current Surface | Target Shape | Notes |
| --- | --- | --- |
| Product mark | `product-mark` `ChromeEntry` | Settings-seeded, graph-backed after authz, inert unless configured otherwise. |
| Site-wide icon | `site-icon` `ChromeEntry` | New desired entry; separate from favicon. |
| Breadcrumb/path navigator | composite `breadcrumb` `ChromeEntry` | Uses authorized page/nav data; owns chevrons, column explorer, overflow. |
| Command palette affordance | `command-palette` `ChromeEntry` | Activation opens palette overlay; shortcut optional. |
| Session tag | `session-tag` `ChromeEntry` | Dev/ops signal from settings or seeded config. |
| User menu | `user-menu` `ChromeEntry` | Auth identity display plus sign-out activation. |
| Flash messages | `feedback` region | Global feedback chrome, not navigation; may host transient message entries/fragments. |
| Mini-graph | `mini-graph` `ChromeEntry` | Backlog, graph-backed, uses `tap_viz` primitives. |

#### Implementation

- `base.html` becomes the renderer for a `ChromeSurface` rather than the source of hardcoded chrome inventory.
- Built-in entry types are owned by `tap_web`, except mini-graph rendering may depend on `tap_viz` once its sibling spec is ready.
- The command palette's existing page-only search is preserved during migration, then expanded under future palette/activation work.
- The old "nav as built-in Panel" path is superseded by the `ChromeSurface`/`ChromeEntry` path.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-chrome-builtin-entries-1 | Existing Chrome Mapped | Proposed | Every existing chrome bit is mapped to an entry or region. | |
| req-web-chrome-builtin-entries-2 | Base Template Not Canon | Proposed | `base.html` renders configured chrome rather than hardcoding the inventory. | |
| req-web-chrome-builtin-entries-3 | Feedback Region | Proposed | Flash/global feedback is treated as chrome feedback, not navigation. | |
| req-web-chrome-builtin-entries-4 | Mini-Graph Remains Backlog | Proposed | Reserved mini-graph work remains deferred until `tap_viz` support is ready. | |


### Persistent Page Host
----
RID: `req-web-chrome-page-host`

Status: `Proposed`

The active `ChromeSurface` persists while Pages load inside its page host. A Page transition should not inherently rebuild product mark, breadcrumb shell, palette, user menu, shortcut dispatcher, or other stable chrome entries.

#### Implementation

- The chrome renderer exposes a stable page host element.
- Same-origin Page navigation may request a page-fragment response and swap only the page host.
- Route-sensitive chrome entries, such as breadcrumb and mini-graph, refresh at entry/region granularity after navigation.
- Page-specific panel assets remain the Page's concern:
  - V1 may full-reload when a target page requires new assets the persistent shell has not loaded.
  - A later asset loader may append newly required panel CSS/JS without a full reload.
- The browser URL and document title still reflect the current Page.

#### Development

This requirement is why Chrome is a separate system instead of a Page requirement. Page content should change without treating the whole app shell as disposable.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-chrome-page-host-1 | Stable Host | Proposed | The shell exposes a stable page content host. | |
| req-web-chrome-page-host-2 | Page Swap Possible | Proposed | Same-origin Page loads can swap page content independently of chrome. | |
| req-web-chrome-page-host-3 | Entry Refresh Granularity | Proposed | Route-sensitive chrome refreshes by entry/region, not full shell rebuild. | |
| req-web-chrome-page-host-4 | Asset Escape Hatch | Proposed | Full reload remains allowed when a target Page requires unloaded assets. | |


### Navigation Spec Migration
----
RID: `req-web-chrome-migration`

Status: `Proposed`

This spec supersedes the proposed `req-web-nav-panel` direction in `tap_web/specs/spec-web-navigation.md`. Navigation does not become a standard Panel mounted on every Page. Instead, navigation becomes a set of built-in `ChromeEntry` types mounted on a persistent `ChromeSurface`.

#### Implementation

- Keep the existing acute security fix until the chrome migration lands:
  - unauthorized callers must not trigger graph-backed Page reads from universal chrome.
  - `/__nav-index.json` stays gated on read authorization.
- Replace `req-web-nav-panel` with:
  - `req-web-chrome-surface`
  - `req-web-chrome-authz`
  - `req-web-chrome-entry`
  - `req-web-chrome-builtin-entries`
- Migrate code in small steps:
  1. Define models/registry/seed for `ChromeSurface` and built-in `ChromeEntry` instances.
  2. Render current hardcoded chrome through built-in entry renderers behind the read gate.
  3. Move palette shortcut handling to the shortcut dispatcher.
  4. Move breadcrumb/nav-index consumers behind the chrome entry data path.
  5. Add persistent page-host swapping after the surface/entry boundary is stable.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-chrome-migration-1 | Nav-Panel Superseded | Proposed | `req-web-nav-panel` is no longer the target architecture. | |
| req-web-chrome-migration-2 | Security Fix Preserved | Proposed | The current read-free/gated behavior remains until the replacement is active. | |
| req-web-chrome-migration-3 | Incremental Cutover | Proposed | Migration can proceed entry by entry without a one-shot rewrite. | |
| req-web-chrome-migration-4 | Tests Move With Contract | Proposed | Existing navigation/chrome tests are updated to assert the new surface/entry contracts. | |

## Status Vocabulary

| Status States | |
| --- | --- |
| Proposed | |
| Backlog | Wanted, intentionally deferred from this revision; distinct from `Proposed` and from Future Seams. |
| Approved for Development | |
| In Development | |
| Implemented | |
| Verified | |
| Refactoring | |
| Deprecating | |
| Deprecated | |

## Requirements Format

`RID: \`...\``
`Status: \`...\``

| Status Details | |
| --- | --- |
| Requirement | Canonical statement of the requirement. |
| Implementation | Implementation notes or the planned mechanism. |
| Development | Design rationale, tradeoffs, and guidance for future maintainers. |
| Acceptance Criteria | ACID rows with testable conditions. |
| Future / Non-Goals | Explicitly deferred work. |
