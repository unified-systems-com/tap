# Web Time Display Specification

## Philosophy

TAP stores time in one form and shows it in another. On the grid, in the
database, on the wire, and to AI consumers, a timestamp is an **absolute
instant in UTC** — unambiguous, comparable, sortable, and identical for every
reader. That is the truth of the data and it never changes for presentation.

What a *human* reads is a projection of that instant into the zone they are
standing in. "14:30 UTC" is the fact; "10:30 EDT" is what the analyst in New
York should see on the screen. Localization is therefore a **last-hop
presentation concern** — it happens at the very edge, closest to the eye, and
never leaks backward into storage, APIs, or the machine-readable surfaces that
`spec-web-navigation.md` promises to AI agents.

This spec exists because TAP today is **inconsistent**: some surfaces render UTC
and some render browser-local, depending only on whether the timestamp happened
to be formatted by a Django template or by Tabulator JavaScript. That split is
an accident of implementation, not a decision. This spec makes the decision:
one convention, applied everywhere a human reads a time.

The security-product context adds one rule the general web does not need: a bare
local time is **evidentiarily ambiguous**. For a compliance/assessment platform
(Rampart), a displayed time must never lose its absolute reference — the zone is
disclosed and the UTC instant stays one hover away.

## Prior Art Applied

- **Django timezone support** (`USE_TZ=True`, already enabled) stores aware UTC
  datetimes and localizes on render to the "current time zone." The current zone
  defaults to `TIME_ZONE` and can be overridden per request via
  `django.utils.timezone.activate()` or per block via the `{% load tz %}` tags
  (`{% localtime %}`, `{% timezone %}`, `|localtime`/`|utc`/`|timezone`). Django
  does **not** auto-detect the browser's zone — that must come from the client.
  Source: <https://docs.djangoproject.com/en/stable/topics/i18n/timezones/>
- **GitHub's `<relative-time>` / `<local-time>` custom elements** ship a UTC
  ISO-8601 instant in the markup and localize it in the browser, so the server
  needs no knowledge of the viewer's zone and anonymous pages localize correctly.
  TAP adapts the shape (a `<time datetime="…Z">` element + one JS pass) without
  the dependency. Source: <https://github.com/github/relative-time-element>
- **HTML `<time datetime>`** is the standard machine-readable time element: a
  human-readable body plus a canonical machine value. TAP uses the `datetime`
  attribute to carry the UTC instant and rewrites the body to local text.
  Source: <https://developer.mozilla.org/docs/Web/HTML/Element/time>
- **`Intl.DateTimeFormat().resolvedOptions().timeZone`** is the browser's own
  report of the viewer's zone — the localization input Django cannot see
  server-side. Source: <https://developer.mozilla.org/docs/Web/JavaScript/Reference/Global_Objects/Intl/DateTimeFormat/resolvedOptions>

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Truthful | Storage, wire, and machine surfaces are always absolute UTC; localization never mutates the data. |
| 2. | Consistent | Every human-facing time renders through one convention — no accidental UTC-vs-local split by rendering path. |
| 3. | Local | A human reads times in their own zone with zero configuration and zero server state. |
| 4. | Unambiguous | A displayed local time always discloses its zone and keeps its UTC instant reachable — evidence-safe. |
| 5. | Machine-Honest | AI/API/JSON surfaces stay unambiguous ISO-8601 UTC; localization is a browser-only concern. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-time-utc-canonical | [UTC Is Canonical](#utc-is-canonical) | Implemented | Storage, wire, and machine surfaces are absolute UTC (`USE_TZ=True`); localization never mutates the instant |
| req-web-time-local-display | [Human Times Are Local](#human-times-are-local) | Implemented | Every human-facing web time localizes to the viewer's browser zone via `localtime.js` |
| req-web-time-zone-disclosure | [Local Times Disclose Their Zone](#local-times-disclose-their-zone) | Implemented | Displayed local times carry the zone abbrev + UTC tooltip + `datetime` attr |
| req-web-time-single-helper | [One Rendering Helper](#one-rendering-helper) | Implemented | Server: `tap_web/timefmt.py` + `tap_time` filter; client: `TapLocalTime` in `localtime.js` |
| req-web-time-machine-utc | [Machine Surfaces Never Localize](#machine-surfaces-never-localize) | Implemented | Nav-index / payloads / exports stay ISO-8601 UTC; localization is browser-only |

## Settled Decisions

Two forks shaped the build. Both are decided (George, 2026-07-02).

1. **Whose "local" (D1) — DECIDED: the viewer's browser zone.** Client-side
   localization (GitHub's model): the server ships UTC, the browser localizes to
   the zone from `Intl.DateTimeFormat().resolvedOptions().timeZone`. Rejected
   alternatives: a single fixed deployment zone (`TIME_ZONE` setting) and a
   per-user stored preference (`timezone.activate()` middleware) — the former
   isn't "local to whoever's looking," the latter adds model + middleware surface
   the browser default doesn't need. Per-user preference is retained as a Future
   Seam for the traveling-analyst case.

2. **Zone disclosure form (D2) — DECIDED: zone abbreviation shown + UTC
   tooltip.** The visible text carries the zone abbreviation (`2026-07-02 10:30
   EDT`) and the `<time>` element's `title=` carries the exact UTC instant
   (`2026-07-02 14:30:00 UTC`). Rejected: local text with UTC only in the tooltip
   (no visible abbrev) and bare local text with no disclosure — both weaker for a
   security/evidence product.

## Requirements

### UTC Is Canonical
----
RID: `req-web-time-utc-canonical`

Status: `Implemented`

Every timestamp TAP stores, transmits, or hands to a machine consumer is an
absolute instant in UTC. This is already the case (`USE_TZ=True`,
`TIME_ZONE="UTC"` in `tap/settings.py`, aware datetimes throughout); this
requirement makes it a **named invariant** so that localization work cannot
erode it. Localization is strictly a browser-side projection of these instants;
no storage column, service-layer return value, API field, or JSON payload is
ever localized.

#### Implementation

- Datetimes are stored timezone-aware in UTC. No naive datetimes enter storage.
- The service layer returns aware UTC datetimes; callers do not pre-localize.
- Any localization happens only at the final human-render hop (see
  `req-web-time-local-display`) and never mutates the source value.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-time-utc-canonical-1 | Storage Is UTC | Implemented | All stored datetimes are timezone-aware UTC; `USE_TZ=True` remains on. | `tap/settings.py`; already true, guarded against regression. |
| req-web-time-utc-canonical-2 | Localization Is Non-Destructive | Implemented | No code path converts a stored/returned datetime to a local zone before it reaches the human-render hop. | `render_local_time` reads the UTC value and emits presentation text; the value is untouched. |

### Human Times Are Local
----
RID: `req-web-time-local-display`

Status: `Implemented`

Every timestamp a human reads in the TAP web UI is displayed in **the viewer's
local time zone** — the zone reported by their browser — regardless of whether
that timestamp is rendered by a Django template or by client-side panel
JavaScript. This resolves the current split where server-rendered templates show
UTC (`|date` under `TIME_ZONE="UTC"`) while Tabulator panels already show
browser-local (`new Date(...).toLocaleString()`).

#### Status Details

Motivating defect: the same product shows two different times for the same
instant depending on rendering path.
- **UTC today:** `tap_web/templates/tap_web/viewer.html` (`started_at|date`),
  `partials/batch_card.html`, `panels/flip_panel.html`.
- **Browser-local today:** `tap_web/static/tap_web/js/panel-table.js`
  (`toLocaleString()` / the `datetime` preset formatter),
  fed ISO strings from `panels/viewer_panel` and `panels/batch_list`.

The convergence target is the browser-local behavior the JS path already has,
applied uniformly (D1: viewer's browser zone).

#### Implementation

- Server-rendered times emit a machine-readable UTC instant in the markup (a
  `<time datetime="2026-07-02T14:30:00Z">` element carrying the ISO-8601 UTC
  value) with a UTC fallback body, rather than pre-formatting to a zone.
- A single small JS pass (see `req-web-time-single-helper`) rewrites each such
  element's body to the browser-local rendering, using the zone from
  `Intl.DateTimeFormat().resolvedOptions().timeZone`.
- Client-rendered panels (Tabulator) route through the same shared helper so
  their formatting matches the server-rendered surfaces exactly (same date/time
  format, same zone disclosure) instead of the current bespoke formatter.
- With JavaScript disabled, the `<time>` body shows the UTC fallback (explicitly
  labeled UTC) — degraded but never wrong.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-time-local-display-1 | One Zone Everywhere | Implemented | For a given viewer, every human-facing timestamp renders in the same (their) zone, whether server- or client-rendered. | Server + client both route through `localtime.js`; kills the UTC-vs-local split. |
| req-web-time-local-display-2 | No Server Zone Knowledge Required | Implemented | Localization requires no per-user setting and no server-side zone detection; anonymous and pre-auth pages localize correctly. | `Intl…resolvedOptions().timeZone` in `localtime.js`. |
| req-web-time-local-display-3 | Safe Without JS | Implemented | With JS disabled, timestamps render as explicitly-labeled UTC, never as an unlabeled ambiguous time. | The `<time>` fallback body (`… UTC`); `test_time_display.py`. |

### Local Times Disclose Their Zone
----
RID: `req-web-time-zone-disclosure`

Status: `Implemented`

Because TAP is a security/compliance platform, a displayed local time must never
be evidentiarily ambiguous. Every localized timestamp **names its zone** and
keeps its **absolute UTC instant reachable**, so a reader (or an auditor reading
over their shoulder) can always recover the exact instant.

#### Implementation

- The visible rendering includes the zone abbreviation, e.g. `2026-07-02 10:30
  EDT` (D2: abbreviation shown).
- The `<time>` element's `title=` (hover tooltip) carries the exact UTC instant,
  e.g. `2026-07-02 14:30:00 UTC`.
- The `datetime` attribute retains the canonical ISO-8601 UTC value for machine
  reading and copy-paste.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-time-zone-disclosure-1 | Zone Is Named | Implemented | A localized timestamp's visible text discloses its zone (abbreviation). | `zoneAbbrev()` in `localtime.js` appends the short zone name. |
| req-web-time-zone-disclosure-2 | UTC Instant Reachable | Implemented | The exact UTC instant is always recoverable from the element (tooltip + `datetime` attribute). | `title` (UTC) + `datetime` (ISO-Z) set by `render_local_time` / `formatEl`; `test_time_display.py`. |

### One Rendering Helper
----
RID: `req-web-time-single-helper`

Status: `Implemented`

There is exactly **one** way to render a human-facing time in TAP web: a shared
helper. Ad-hoc datetime formatting (inline `|date` with a UTC result, bespoke
`toLocaleString()` calls, hand-rolled `getHours()` padding) is prohibited so the
convention cannot drift back into a split.

#### Implementation

- A template helper (a `{% load %}`-able tag/filter, e.g. `{% localtime_tag
  value %}` or `value|tap_localtime`) emits the standard `<time>` element with
  the UTC `datetime` attribute, UTC fallback body, and UTC tooltip.
- A single JS module localizes every `<time data-tap-localtime>` element on load
  (and after HTMX/panel swaps) to the browser zone with zone disclosure.
- The Tabulator `datetime` preset formatter in `panel-table.js` is replaced by a
  call into the same JS localization routine, so panels and templates share one
  code path and one output format.
- Existing UTC-rendering templates (`viewer.html`, `batch_card.html`,
  `flip_panel.html`) migrate to the helper.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-time-single-helper-1 | Single Template Entry Point | Implemented | Human-facing server-rendered times go through the shared template helper; no raw `|date` on a UTC-stored value remains in human-facing templates. | `tap_web/timefmt.py` + `tap_time` filter; migrated `viewer.html`, `batch_card.html`, `flip_panel.html`, and `viewer_panel` field rendering. |
| req-web-time-single-helper-2 | Single Client Entry Point | Implemented | Client-rendered times (Tabulator) call the shared JS localization routine, not a bespoke formatter. | `panel-table.js` `datetime` + `updated_at` formatters call `TapLocalTime.formatEl`. |
| req-web-time-single-helper-3 | Identical Output | Implemented | The same instant renders as identical text whether it came through the server or the client path. | Server `render_local_time` and client `formatEl` share one format + zone-disclosure convention. |

### Machine Surfaces Never Localize
----
RID: `req-web-time-machine-utc`

Status: `Implemented`

Machine-readable surfaces — `/__nav-index.json`, plugin/API JSON responses, data
exports, and any payload an AI agent or automation consumes — emit **ISO-8601
UTC** and are never localized. This preserves the "AI is a first-class consumer,
text-first" contract of `spec-web-navigation.md`: a machine reader must get one
unambiguous instant, not a zone-dependent string.

#### Implementation

- JSON/API datetime fields serialize as ISO-8601 UTC with a `Z` suffix (the
  existing `nav_index_view` `generated_at` pattern:
  `datetime.now(UTC).isoformat().replace("+00:00", "Z")`).
- Panel data payloads that feed client-side rendering carry the UTC ISO value;
  localization happens only in the browser render layer, not in the payload.
- Exports (CSV/JSON per `spec-web-panel-data-export.md`) emit UTC; if a localized
  export is ever wanted, it is an explicit opt-in with the zone recorded in the
  export, never the default.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-time-machine-utc-1 | JSON Is UTC | Implemented | Nav-index and API JSON datetime fields are ISO-8601 UTC (`Z`-suffixed), never localized. | `nav_index_view` `generated_at`; unchanged by this work. |
| req-web-time-machine-utc-2 | Payloads Carry UTC | Implemented | Panel data payloads carry UTC instants; the browser localizes at render, the payload does not. | `viewer_panel`/`batch_list` emit `isoformat()`; localization is browser-only. |
| req-web-time-machine-utc-3 | Exports Are UTC | Implemented | Data exports emit UTC by default; any localized export is explicit and self-documenting. | Per `spec-web-panel-data-export.md`; UTC default unchanged. |

## Future Seams

- **Per-user zone preference** — if a user wants a *fixed* display zone
  regardless of the browser they are on (e.g. an analyst who travels but wants
  everything in their home office zone), a stored preference overrides the
  browser-detected zone. Deferred; the browser default covers the common case.
- **Relative time** — "3 minutes ago" style rendering (Django `naturaltime` /
  `<relative-time>`) is zone-independent and complements this spec for recency
  surfaces; a future revision may define where relative vs. absolute is used.
- **Configurable format** — 12h vs 24h, date order, and locale-aware formatting
  via `Intl.DateTimeFormat` locale options; v0 fixes one format.

## Status Vocabulary

| Status States | |
| --- | --- |
| Proposed | |
| Approved for Development | |
| In Development | |
| Implemented | |
| Verified | |
| Deprecated | |

## RID Format

`req-<application>-<specification>-<feature>-<sub-feature>`

## Requirements Format

`RID: \`...\``
`Status: \`...\``

| Sub-Sections | (as needed) |
| --- | --- |
| Status Details | |
| Implementation | |
| Acceptance Criteria | |
| Future | |
