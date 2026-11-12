# Web Resource Drawer Specification

## Philosophy

A board is read as a list: the reader scans, picks a row, decides whether it matters, and goes back to the list.
Sending them to a full page for every row breaks that rhythm; they lose their scroll, their filters and their
place. The **resource drawer** answers "what is this row?" beside the list. It slides in from the right over the
page's edge, shows one entity's data grouped into the categories a reader asks about, and closes back to the
same list. The full object viewer is one link away for the reader who wants to stay.

Cloud-security consoles converged on this shape (Wiz's resource details drawer: overview, related issues,
relationships, tags, a code trace, and a raw JSON tab). TAP's version derives every category from the grid; no
category is hand-written per type.

The drawer lives in the chrome `overlay` region (`spec-web-chrome.md`). It is an inspection surface, not
navigation: it never lists pages, so it is outside `req-web-nav-no-hamburger`.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Stay in place | Inspecting a row never loses the list's scroll, filters or grouping. |
| 2. | Derived | Every category comes from the entity's fields, edges and FLIP; types add nothing to get a drawer. |
| 3. | Linkable | An open drawer is part of the URL; Back closes it. |
| 4. | Accessible | Non-modal region with a visible title, Escape closes, focus returns to the row. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-drawer | [Resource Drawer](#resource-drawer) | Implemented | A right-side, non-modal region in `base.html` that shows one entity, fetched as an HTML fragment |
| req-web-drawer-fragment | [Drawer Fragment Route](#drawer-fragment-route) | Implemented | `GET /object/<entity_type>/<url_id>/drawer/` returns the drawer body; same authorization as the viewer |
| req-web-drawer-categories | [Drawer Categories](#drawer-categories) | Implemented | Overview, Findings, Relationships, Configuration, Tags, Provenance, Raw — each derived, each with a three-state empty |
| req-web-drawer-open | [Opening And State](#opening-and-state) | Implemented | A table row (or any `[data-tap-drawer]` link) opens it; `?drawer=<entity_id>` restores it; Back and Escape close it |

## Requirements

### Resource Drawer
----
RID: `req-web-drawer`

Status: `Implemented`

Trace: `non-python` — tap_web/templates/tap_web/base.html, tap_web/static/tap_web/js/drawer.js

#### Implementation
- One `<aside id="tap-drawer" role="region" aria-labelledby="tap-drawer-title" hidden>` in `base.html`, after `<main>`, rendered only for a caller with `grid.read`.
- Width `min(36rem, 100vw)`, fixed to the right edge below the header, its own scroll; the page behind stays interactive (non-modal).
- Header: type icon, entity name as the title, type label, an "Open full page" link to the object viewer, and a Close button (`aria-label="Close details"`).
- Slide-in transition of 160ms, none under `prefers-reduced-motion: reduce`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-drawer-1 | Region In Chrome | Implemented | `base.html` carries the hidden drawer region for a reader with `grid.read`, and none otherwise. | `tap_web/tests/test_drawer.py` |
| req-web-drawer-2 | Non-Modal | Implemented | Opening the drawer does not trap focus or make the page inert. | browser QA (`qa-page`) |

### Drawer Fragment Route
----
RID: `req-web-drawer-fragment`

Status: `Implemented`

#### Implementation
- `GET /object/<entity_type>/<url_id>/drawer/` (`tap_web.views.object_drawer_view`), the same `url_id` grammar as the viewer: the slug part is decorative, the uuid after the last `--` is the identity.
- Authorization is the viewer's (`READ_CAPABILITY`); a missing entity is a 404 fragment with a sentence, not a page.
- The response is a fragment (no `base.html`), safe to swap into the region.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-drawer-fragment-1 | Fragment Renders | Implemented | The route returns 200 with the drawer body for a live entity, including one whose name contains `/`. | `tap_web/tests/test_drawer.py` |
| req-web-drawer-fragment-2 | Authorized | Implemented | An anonymous caller is refused. | `tap_web/tests/test_drawer.py` |
| req-web-drawer-fragment-3 | Missing Entity | Implemented | An unknown uuid returns 404 with a sentence. | `tap_web/tests/test_drawer.py` |

### Drawer Categories
----
RID: `req-web-drawer-categories`

Status: `Implemented`

#### Implementation
Each category is a `<section>` with a heading and a count; an empty category says what was looked for (observed-empty), never renders blank.

1. **Overview** — type, name, entity id, and the first scalar fields that identify the object: the model's optional `DRAWER_OVERVIEW` fields, then `state`, `status`, `severity`, `instance_id`, `private_ip`, `resource_ids`, `region`, `account_id` and the like when the model has them (a one-item list of scalars shows as its item); plus, for a single outgoing edge, a "Resource" row first when it is `CONCERNS_RESOURCE*` (what a finding is about) and the account or region when the edge type ends `ACCOUNT` or `REGION`. Neighbours everywhere in the drawer are labelled with their type's display name, never its slug.
2. **Findings** — edges whose neighbour's model declares `DRAWER_ROLE = "finding"`, incoming edges whose type (without its `__<plugin>` suffix) starts with `CONCERNS_RESOURCE`, and outgoing `HOLDS_*FINDING` edges (an account holding its findings); each a link that opens that finding in the drawer.
3. **Relationships** — every other edge, grouped by edge type and direction (out / in), each neighbour a drawer link; groups over 25 show the first 25 and a count.
4. **Configuration** — the model's fields (the viewer's field pairs), grouped by the model's optional `DRAWER_GROUPS = {"Label": ["field", ...]}`; ungrouped fields go under "Fields". Long or structured values collapse.
5. **Tags** — the `tags` field as key/value rows; a `deployed_from` (or `DeployedFrom`) tag is lifted to a "Declared in" line (the code trace).
6. **Provenance** — the FLIP rows (`flip_panel.get_flip_context_for_entity`): which batch and source last wrote each field.
7. **Raw** — the `configuration` field (or, absent that, every field) as pretty JSON in a collapsed `<details>`.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-drawer-categories-1 | All Categories Present | Implemented | The fragment carries the seven category sections in order. | `tap_web/tests/test_drawer.py` |
| req-web-drawer-categories-2 | Findings From Edges | Implemented | An incoming `CONCERNS_RESOURCE*` edge appears under Findings, not Relationships. | `tap_web/tests/test_drawer.py` |
| req-web-drawer-categories-3 | Empty Is Stated | Implemented | A category with nothing to show renders a sentence. | `tap_web/tests/test_drawer.py` |
| req-web-drawer-categories-4 | Overview Identifies | Implemented | A single outgoing `CONCERNS_RESOURCE*` edge leads Overview as "Resource"; a single outgoing account or region edge becomes an Overview row labelled with the neighbour's type name; neighbour links show type display names, not slugs; field labels keep acronyms upper-case (`Private IP`, not `Private Ip`). | `tap_web/tests/test_drawer.py` |

### Opening And State
----
RID: `req-web-drawer-open`

Status: `Implemented`

Trace: `non-python` — tap_web/static/tap_web/js/drawer.js, tap_web/static/tap_web/js/panel-table.js

#### Implementation
- A table with a `drawer` config dispatches `tap:row-activate` on a plain row click (`req-web-stdpanel-table-row-nav-5`); `drawer.js` handles it. Any element with `data-tap-drawer="<fragment url>"` opens it too (drawer links inside the drawer).
- Opening pushes `?drawer=<entity_id>&drawer_type=<entity_type>` with `history.pushState`; loading a URL that carries them opens the drawer; Back (`popstate`) closes or switches it.
- Escape (when focus is not in an input that uses Escape) and the Close button close it; focus returns to the element that opened it; on open, focus moves to the drawer title.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-drawer-open-1 | Row Opens Drawer | Implemented | A plain click on a drawer-enabled row opens the drawer with that entity. | browser QA (`qa-page`) |
| req-web-drawer-open-2 | URL Restores | Implemented | Loading a page with `?drawer=` opens the drawer. | browser QA (`qa-page`) |
| req-web-drawer-open-3 | Escape And Focus | Implemented | Escape closes the drawer and focus returns to the opener. | browser QA (`qa-page`) |
