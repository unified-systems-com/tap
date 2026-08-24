# Feature Specification

## Philosophy
Making user and plugin-defined pages and panels stored on the grid work requires a rethink of how rendering takes place and must account for routing, creation, and security.

We haven't fully defined the panel structure yet, likely going to do that next.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Secure         | This is critical path for routes and rendering, playing with fire, have to get it right                  |
| 2. | Consistent     | Create one approach for rendering any / all page types, static, forms, charts, graphs                    |
| 3. | Flexible       | Make it possible to support the widesst range of page types                                              |
| 4. | Elegant        | Paths are still a somewhat important signal of information, they should be informative                   | 
| 5. | Shared Context | Rendering process supports shared query params, localstorage / page state and inter-panel notifications  | 

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-rendering-resolution | [Dynamic Page Resolution](#dynamic-page-resolution) | Implemented | Pages and panels resolve at request time; no static URL config changes needed for new pages |
| req-web-rendering-slashpage | [Pages Start With /](#pages-start-with-) | Implemented | Dynamic pages rooted at `/`, not `/pages/...` |
| req-web-render-process | [Page Rendering Process](#page-rendering-process) | Implemented | Multi-step pipeline: URL → page view → page service → page template → panel HTMX calls |
| req-web-render-panel | [Panel Rendering Process](#panel-rendering-process) | Implemented | Panels rendered via HTMX; generic view renders panel's declared template |
| req-web-render-panel-edit | [Panel Edit Rendering](#panel-edit-rendering) | Implemented | Panel edit pages integrate the panel route with the generic web editor shell |
| req-web-render-missingpan | [Missing / Broken Panels](#missing--broken-panels) | Implemented | Missing panels show "Panel Error" in their layout slot |
| req-web-render-landing | [Landing Page Owns /](#landing-page-owns-) | Implemented | Root `/` delegates to LandingPage-linked Page without client-side redirect |
| req-web-render-flash | [Flash Messages](#flash-messages) | Implemented | The base template renders + consumes Django messages once, where the user lands, as a dismissible banner |
| req-web-rendering-pagesan.sec | [Page Rendering Sanitization](#page-rendering-sanitization-security) | Implemented | Base template + HTMX + static asset manifest ensure safe page output |
| req-web-rendering-panelsan.sec | [Panel Rendering Sanitization](#panel-rendering-sanitization-security) | Implemented | Standard Django templates; `\|safe` risk documented |
| req-web-rendering-path.sec | [Path Access Security](#path-access-security) | Backlog | User permission checks (deferred to user security model) |
| req-web-rendering-route.sec | [Path Overwrite Security](#path-overwrite-security) | Backlog | Plugin isolation to prevent path hijacking |
| req-web-rendering-docref | [Doc-Reference Link Rendering](#doc-reference-link-rendering) | Backlog | Web-UI touchpoint: render a *resolved* structured doc reference as a navigable link; resolution contract owned by the docs system |
| req-web-rendering-headless | [Headless Web Disable](#headless-web-disable) | Backlog | Boot/settings toggle to not mount the `tap_web` surface at all — for headless / API-only / minimal deployments (e.g. the gryphon playground) |


### Dynamic Page Resolution
----
RID: `req-web-rendering-resolution`
Status: `Implemented`

Page and panel resolution is dynamic at request time, but Django route definitions remain static.

Coincidentally this will allow us to later apply User Security Models to limit which pages the user is allowed to see in their current permission levels.  Same permission system.

It also means that new pages and installed pages will be available immediately upon creation without having to muck around with adding to urls.py or restarting the application.

The top-level `tap/urls.py` delegates everything that isn't reserved by other core modules (`admin`, `api`) to `tap_web/urls.py`.

`tap_web/urls.py` defines three stable patterns:
1. `/panel/<slug>--<uuid>/` → panel fragment view
2. `` (empty, root) → landing page view
3. `<path:page_slug>` (catch-all) → page view

This creates a clean-enough separation of concerns - if plugins want to have their own pages they can create them as page objects.
If they want to have their own endpoints to consume data they can register them with the api system.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-rendering-resolution-1 | Static URL Patterns | Implemented | `tap_web/urls.py` defines static patterns; no URL config changes are needed when new pages or panels are created. | |
| req-web-rendering-resolution-2 | tap/urls.py Delegates | Implemented | `tap/urls.py` delegates all non-reserved paths (`admin`, `api`) to `tap_web/urls.py` via `include`. | |

#### Future
API system supports plugins adding paths that hang off /api


### Pages Start With /
RID: `req-web-rendering-slashpage`
Status: `Implemented`

I really, really want dynamic pages to be able to work from /.  I've seen how other sites do it and I understand the added complexity this introduces, but for the goal of elegance I do not want to create a default /page path that all dynamic pages live on - it's just ugly and confusing.

This aligns with requiring all Page paths to begin with /.  It's honest and straightforward.

This will be implemented in the tap_web urls.py logic, not using client-side redirects.


### Page Rendering Process
RID: `req-web-render-process`
Status: `Implemented`

Django has a robust page rendering process that does all sorts of things right.  The page and panel rendering process will utilize as much of those mechanisms as possible.

Proposed process:
1. `tap_web/urls.py` — routes request to the page view handler
2. Page View (`tap_web/views.py`) — calls the page service layer to resolve the page and its panels
3. Page Service (`tap_web/page_service.py`) — `get_page_by_slug(slug)` returns the `Page` object and its ordered `USES_PANEL` edge set; `get_landing_page()` returns the landing-page-referenced `Page`
4. Page Template (`tap_web/templates/tap_web/page.html`) — renders the CSS Grid layout by looping over the `layout` JSONField; inserts HTMX `<div hx-get="/panel/<slug>--<uuid>/">` stubs per slot; emits deduped CSS from all panels at `<head>`, deduped JS at end of `<body>`
5. Panel View Handlers (`tap_web/views.py`) — panels served at `/panel/<slug>--<uuid>/`; UUID parsed to look up the `Panel`; `render(request, panel.view)` renders the declared template; exceptions return the panel error fragment
6. Layout CSS — CSS Grid for column placement; column/row key numeric suffixes (`col-1`, `row-2`) map to grid `order` values. `col_span` and `row_span` from the layout schema apply via `grid-column: span N` / `grid-row: span N`. Rows render as vertical flex items inside each column; row `height` maps to `flex` values (`auto` → `flex: 0 0 auto`, `Nfr` → `flex: N 1 0`) so `Nfr` rows distribute the remaining viewport height after the base template wrapper stretches to fill `<main>`.

Panels rely on asset manifests declared on the **panel type class** (not the panel instance) so page rendering can gather, dedupe, and emit static CSS/JS before panel fragments are requested. The aggregator resolves each panel to its registered type via the panel's `view` field and reads `js` / `css` class attributes from the type.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-render-process-1 | Page Service Resolves Page | Implemented | `get_page_by_slug(slug)` returns a `Page` and its ordered panel set. Returns 404 if slug not found. | |
| req-web-render-process-2 | Asset Deduplication | Implemented | CSS and JS declared across all panels in a page are deduplicated (by path) before emission. Duplicates are silently dropped. | |
| req-web-render-process-3 | CSS at Head, JS at Body End | Implemented | Panel CSS emitted inside `<head>`; panel JS emitted at the end of `<body>`. | |
| req-web-render-process-4 | CSS Grid Layout | Implemented | Layout JSONField column/row keys drive CSS Grid placement. `col_span`/`row_span` values drive `grid-column: span N` / `grid-row: span N`. | |


### Panel Rendering Process
RID: `req-web-render-panel`
Status: `Implemented`

Panels are rendered via HTMX calls from the page template. Each Panel object stores a `view` (template path string); the panel type class matching that view declares the static asset lists (`js`, `css`). The page template emits the full deduped asset set (collected from every panel's type) before HTMX calls are made; HTMX then fills each layout slot with the rendered panel fragment.

#### Panel Endpoint

```
/panel/<slug>--<entity-uuid>/
```

The slug is decorative (for readability). The UUID is used to look up the Panel. On exception, the view returns an HTML error fragment at HTTP 200 so the HTMX swap completes.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-render-panel-1 | HTMX Fragment Endpoint | Implemented | Panel endpoint at `/panel/<slug>--<uuid>/` renders the Panel's declared template and returns an HTML fragment. | |
| req-web-render-panel-2 | Generic View | Implemented | A single generic panel view handler calls `render(request, panel.view)` regardless of panel type or plugin origin. | |
| req-web-render-panel-3 | UUID Lookup | Implemented | UUID portion of the URL slug is parsed to look up the Panel by `entity_id`. | |


### Panel Edit Rendering
RID: `req-web-render-panel-edit`
Status: `Implemented`

Panel edit mode integrates the panel edit route with the generic web editor shell. Shared editor layout and preview behavior are defined in `spec-web-editor.md`; this section defines only the panel-route integration.

#### Implementation
Editor route:

```
/panel/<slug>--<entity-uuid>/edit/
```

Behavior:
- route resolves the Panel by UUID using the same decorative-slug pattern as normal panel rendering
- the generic editor shell is rendered for the resolved Panel
- the shell includes the required graph context preview defined in `spec-web-editor.md`
- panels may render an object-specific preview showing what the panel looks like
- the typed editor region renders the panel's declared `editor_view`
- editor page emits deduped editor CSS and JS using the panel type's `editor_css` / `editor_js` class attributes
- preview and save are separate actions
- preview applies current draft editor state without persistence
- edit submissions post back to the panel edit endpoint

Panels supply panel-specific editor content and optional object-preview behavior; rendering owns the route integration and page assembly.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-render-panel-edit-1 | Edit Route Exists | Implemented | Panel edit mode is routed at `/panel/<slug>--<uuid>/edit/`. | |
| req-web-render-panel-edit-2 | UUID Lookup | Implemented | Edit route resolves the panel by UUID using the decorative slug pattern. | |
| req-web-render-panel-edit-3 | Generic Editor Shell Used | Implemented | Panel edit pages are assembled through the generic web editor shell. | `panel_edit_view` renders `tap_web/editor.html` |
| req-web-render-panel-edit-4 | Panel Editor Uses Declared Template | Implemented | The typed editor region renders the panel's declared `editor_view`. | |
| req-web-render-panel-edit-5 | Editor Assets Emitted | Implemented | Editor page emits `editor_css` in the head and `editor_js` at the end of the body. | Sourced from the panel type class. |
| req-web-render-panel-edit-6 | Preview Separate From Save | Backlog | Preview is deferred; save + history-revert is the v1 undo strategy. | |
| req-web-render-panel-edit-7 | Preview Applies Draft State | Backlog | Preview is deferred; see `req-web-editor-preview-exec`. | |
| req-web-render-panel-edit-8 | Edit Posts To Edit Endpoint | Implemented | Edit submissions target the panel edit endpoint rather than the normal view endpoint. | |

#### Future
Consider adding an unsaved-changes indicator and editor lifecycle hooks if editor interactions become more dynamic.


### Missing / Broken Panels
RID: `req-web-render-missingpan`
Status: `Implemented`

If a panel cannot be rendered for whatever reason, populate its row / column with "Panel Error" followed by an explanatory message and output detailed information into the console (until we have better logging setup).

#### Implementation

The panel view handler wraps `render(request, panel.view)` in a try/except. On any exception, it renders `tap_web/templates/tap_web/panel_error.html` with the exception message and returns HTTP 200 (so the HTMX swap completes). Django's standard logging captures the full traceback.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-render-missingpan-1 | Error Fragment Returned | Implemented | Panel endpoint returns HTTP 200 with error HTML on exception so HTMX swap completes. | |
| req-web-render-missingpan-2 | Error Slot Shows "Panel Error" | Implemented | Error fragment displays "Panel Error" and the exception message in the layout slot. | |
| req-web-render-missingpan-3 | Exception Logged | Implemented | Full traceback is captured via Django's standard logger for the `tap_web.views` module. | |

#### Future
Better logging of missing / broken panels.

### Landing Page Owns /
RID: `req-web-render-landing`
Status: `Proposed`

Landing page function is responsible for handling requests to `/`.
That request is handled by directly calling the landing-page-referenced page and without doing client-side redirects.
All parameters passed to `/` are passed to the page.

#### Implementation

`get_landing_page()` in `tap_web/page_service.py`:
1. Queries all `LandingPage` objects ordered by `entity__created_at` ascending
2. Follows the `USES_LANDING_PAGE` edge from the earliest `LandingPage` to its target `Page`
3. Returns that `Page` (or `None` if none configured)

The landing view passes all query parameters from the root request through to the page rendering context unchanged.

Note: `created_at` lives on `Entity`, not on `BaseModel` (which no longer carries `created_at`). Ordering is `LandingPage.objects.order_by("entity__created_at")`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-render-landing-1 | No Client-Side Redirect | Implemented | `/` renders the landing-page-referenced Page directly; no HTTP redirect is issued. | |
| req-web-render-landing-2 | Query Params Passed Through | Implemented | Query parameters from the root request are available in the page rendering context. | |
| req-web-render-landing-3 | Earliest LandingPage Selected | Implemented | If multiple LandingPage nodes exist, the one with the earliest `entity__created_at` is used. | |
| req-web-render-landing-4 | No LandingPage Returns 404 | Implemented | If no LandingPage exists, `/` returns a 404. | Currently falls back to the legacy home view instead. |


### Flash Messages
----
RID: `req-web-render-flash`
Status: `Implemented`
Trace: `non-python` — tap_web/templates/tap_web/base.html

The base template renders and **consumes** the Django messages framework once, as a dismissible banner under the header, so a message queued by an action (e.g. allauth's sign-in notice) appears on the page the user actually lands on — not stranded until the next message-rendering page. This is global feedback chrome, distinct from navigation (`spec-web-navigation`) and from per-panel error rendering (`req-web-render-missingpan`).

#### Implementation

- `base.html` iterates `{% if messages %}` in a flash region between the header and the page body. Iterating *consumes* the one-shot messages, so each shows exactly once, on the landing page — fixing the class of bug where an auth message lingered onto the logout screen because no app page rendered messages.
- Each banner carries the message-level tag class (`.tap-flash--success/-error/-warning/-info`) and a dismiss `×`; `tap_web/js/usermenu.js` removes it on click and auto-dismisses after a timeout. Styling is `.tap-flash*` in `palette.css`.
- Message *content* is owned by whoever queues it (allauth, future TAP code); this requirement owns only the rendering + consumption + dismissal.
- allauth's **login-success** message is intentionally suppressed (an empty `account/messages/logged_in.txt` override; allauth skips a message that renders empty) — the post-login landing should reveal the grid cleanly, and the sign-in is self-evident. The logout confirmation is kept.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-render-flash-1 | Rendered + Consumed In Base | Implemented | The base template renders any queued Django messages and consumes them (each shows once), on the page the user lands on. | `{% if messages %}` in `base.html`. |
| req-web-render-flash-2 | Level Styling | Implemented | Each banner reflects its message level (success / error / warning / info). | `.tap-flash--<tag>`. |
| req-web-render-flash-3 | Dismissible | Implemented | A banner is dismissible (× / click) and auto-dismisses after a timeout. | `tap_web/js/usermenu.js`. |


### Page Rendering Sanitization Security
RID: `req-web-rendering-pagesan.sec`
Status: `Implemented`

Pages need to be sanitized using django's bulit-in capabilities.

Proposed implementation is to use a base page template to build the scaffolding, then populate using htmx calls to a dedicaded /panel endpoint responsible for rendering the panel body properly and returns a list of static assets that will be rendered at the bottom of the page.

Page generation will place the panel css elements at the top of the page and js from panels at the bottom using proeperly sanitized outputs that point to static asset files only.



### Panel Rendering Sanitization Security
RID: `req-web-rendering-panelsan.sec`
Status: `Implemented`

Panels use their own rendering with standard views and templates that are returned to the HTMX calls from the page.

#### Risks
* Panels can still use `|safe` in their templates to bypass security, which would be the case if we were rendering their templates directly so it's a wash and something we'll need to address in Future plugin security checks



### Path Access Security
RID: `req-web-rendering-path.sec`
Status: `Backlog`
Revisit When:  `User Security Model is in place`

Paths that a user does not have access to should not be resolveable to avoid information disclosure.

Question:
1. Not-authorized vs not-found:  I hate how GitHub returns 404 for directories that I don't have permission on.
2. Logged-in vs Not:  If a user is logged in do we want to allow them to see certain page types and indicate they have a permission problem - this hinges on how robust the user security model is.
3. Configurable?  Consider giving the grid admin the choice of how to hande this - which fits with the sophisticated beanbag approach.

#### Security Concerns
Being able to see pages on the site:
1. Discloses the types of plugins that are installed
2. Gives away information about what the site is for, what it's storing
3. Is just bad practice


### Path Overwrite Security
----
RID: `req-web-rendering-route.sec`
Status: `Backlog`
Revisit When:  `Refactoring the plugin system to add willison module hooks`

We want to address the risk that plugins could screw with existing paths.  The issue is that django modules by default have everything they need to access the deep url config variables inside django and screw around with stuff.

#### Security Concerns
Malicious plugins could:
* Replace the /admin path with a page that intercepts the user's login creds and everything they need to hack the site.
* Replace /api to intercept / modify / change data
* Replace an existing page to show inaccurate information or intercept form inputs and change things
* Inject javascript files that overwrite the static copies in other plugins and poof javascript execution inside the browser (although that may be handeld by the static module)

Basically it's the second worst possible form of injection beyond direct execution of untrusted code inside the app (which is currently the standard for plugins).


### Doc-Reference Link Rendering
----
RID: `req-web-rendering-docref`
Status: `Backlog`
Revisit When: `req-docs-ref-resolution promotes out of Backlog, or the first docs/ page a self-test points at exists`

This is the **web-UI half** of structured doc-reference handling. The split is deliberate and named early so the touchpoint is known before either side is built:

- **Resolution** — turning a structured reference `{plugin, doc, section?, label?}` into a canonical doc target — is a docs-system concern, owned by `specs/spec-docs.md` `req-docs-ref-resolution`. Not a web concern.
- **Rendering** — turning a *resolved* target into a clickable link / route / HTMX surface inside a page or panel — is this requirement. It is the web-UI concern and lives here in `tap_web` because doc links are a cross-cutting rendering primitive any panel can use, not a feature of one consuming surface (e.g. the CARES collector readiness panels at `tap_cares/specs/spec-tap-cares-administrivia.md` `req-tap-cares-administrivia-collector-readiness-5`).

Until both halves land, the interim behavior is the explicit, named stub described in `req-docs-ref-resolution`: panels display the raw `ref`/`label` strings and render no navigable link. This requirement does not define the resolver, the docs route, or the link markup — only that, when resolution exists, rendering a resolved doc reference is a `tap_web` rendering primitive, not bespoke per-panel code.

#### Status Details

Backlog, blocked on `req-docs-ref-resolution` (no resolver, no rendered docs to link to). It is recorded now purely to fix the concern boundary: resolution ≠ rendering ≠ emission, three specs, no overlap.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-rendering-docref-1 | Rendering Only | Backlog | This requirement covers rendering a resolved doc target as a navigable web link; it does not resolve references (that is `req-docs-ref-resolution`). | Concern separation. |
| req-web-rendering-docref-2 | Shared Primitive | Backlog | Doc-link rendering is a shared `tap_web` rendering helper usable by any page/panel, not duplicated per consuming panel. | |
| req-web-rendering-docref-3 | Interim Raw Display | Backlog | Until resolution lands, panels display raw `ref`/`label` with no link; this is the named stub from `req-docs-ref-resolution-5`. | |

### Headless Web Disable
----
RID: `req-web-rendering-headless`
Status: `Backlog`
Revisit When: `a deployment needs to run without the web UI (minimal / headless / API-only), or the gryphon playground wants a truly chrome-free standup`

TAP should support standing up an instance with the **web UI mounted off entirely** — not merely empty of pages, but not served at all — for headless / data-plane / minimal deployments. Today `tap/urls.py` unconditionally delegates every non-reserved path to `tap_web/urls.py` (`req-web-rendering-resolution`); headless mode makes that delegation conditional on a settings flag, ultimately driven by the boot profile (config-as-code, `spec-tap-boot-v0`), so a profile can declare "no web surface."

Motivating case: `boot/gryphon.boot.json` exists only to exercise the Gryphon query language. It already drops the admin chrome (administrivia), but the web catch-all still mounts with no landing page. A headless toggle would let it — and real API-only / minimal deployments — run with no web surface at all.

Parallel: the same capability is wanted for the API surface (see the tap_api backlog, "Headless API disable"). Both are the same idea — a boot/settings **surface toggle** consumed where surfaces mount in `tap/urls.py` — named on each side so the touchpoint is known before it is built. The shared mechanism (the flag) belongs in settings / `tap`, not in either app depending on the other (`avoid tap_* app interdependencies`). Web-disable and API-disable are independent: either surface can be off without the other.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-rendering-headless-1 | Conditional Mount | Backlog | When the web-disabled flag is set, `tap/urls.py` does not mount the `tap_web` delegation; the web surface is absent rather than 404-per-page. | Driven by settings, ultimately the boot profile. |
| req-web-rendering-headless-2 | Boot-Declared | Backlog | The toggle is declarable in the boot profile so a headless standup is config-as-code, not a code change. | `spec-tap-boot-v0`. |
| req-web-rendering-headless-3 | Independent Of API | Backlog | Disabling the web surface is independent of disabling the API surface; either can be off without the other. | Parallels the tap_api headless item. |

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed |  |
| Approved for Development |  |
| In Development |  |
| Implemented |  |
| Verified |  |
| Refactoring |  |
| Deprecating |  |
| Deprecated |  |

## RID Format

`req-<application>-<specification>-<feature>-<sub-feature>`

## Requirements Format

`RID: \`...\``  
`Status: \`...\``

| Sub-Sections | (as needed) |
| --- | --- |
| Status Details |  |
| Implementation |  |
| Development |  |
| Acceptance Criteria |  |
| Future |  |
| Backlog |  |
