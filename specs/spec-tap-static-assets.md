# TAP Static Assets

## Philosophy

Every Django app in TAP that ships browser-facing assets (JavaScript, CSS, images, fonts) registers its own static directory. Without a shared convention, TAP-authored code and vendored third-party libraries end up mixed flat in the same directory, making provenance invisible: a reviewer can't tell at a glance whether a file is ours to edit or an upstream distribution we must not touch, and there is no single place to audit what third-party code is loaded into the browser.

This specification defines the canonical layout for static assets across every app and plugin in TAP. It sits above `tap_web`, `tap_viz`, and all plugins because the rule is cross-cutting: any Django app that registers a static directory is in scope.

The split is **per-app**, not shared. `tap_viz/static/tap_viz/js/lib/cytoscape.min.js` tells you immediately that tap_viz vendored Cytoscape — ownership and provenance are visible from the path alone. A shared vendor pool would obscure that.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Namespaced roots | Every app's static assets live under `<app>/static/<app>/...` so they cannot collide across apps. |
| 2. | Ownership visible in path | TAP-authored and vendored third-party code are in separate subdirectories, per-app, so provenance is obvious. |
| 3. | Vendor auditability | Every vendored file is recorded in the app's `third_party_manifest.toml` per `spec-grid-security.md`. |
| 4. | No cross-app reach | Templates reference assets only from their own app's namespace; sharing happens through deliberate promotion, not ad hoc `{% static %}` calls into sibling apps. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-static-assets-layout | [App-Namespaced Layout](#app-namespaced-layout) | Proposed | Canonical directory shape for every app |
| req-tap-static-assets-vendor-split | [TAP vs. Vendored Split](#tap-vs-vendored-split) | Proposed | `lib/` subdirectory for third-party files |
| req-tap-static-assets-no-cross-app | [No Cross-App References](#no-cross-app-references) | Proposed | Templates stay within their own app namespace |

### App-Namespaced Layout
----
RID: `req-tap-static-assets-layout`
Status: `Proposed`

Every Django app in the TAP repo — including `tap_web`, `tap_viz`, and all plugins under `plugins/` — that registers a static directory MUST place its assets under `<app>/static/<app>/...`. This is Django's recommended collision-safe pattern: the inner app-named directory ensures that `{% static '<app>/js/foo.js' %}` from one app cannot clash with another.

Flat layouts like `<app>/static/js/foo.js` (without the inner app-named directory) are not permitted for new code, and existing deviations should be migrated (see [Future](#future)).

The concrete shape for each app is:

```
<app>/static/<app>/
├── js/
│   ├── <tap-owned>.js
│   └── lib/
│       └── <vendored>.js
├── css/
│   ├── <tap-owned>.css
│   └── lib/
│       └── <vendored>.css
└── <other asset types as needed, following the same pattern>
```

Every file under any `lib/` directory MUST be recorded as a `[[component]]` entry in that app's `third_party_manifest.toml` per `spec-grid-security.md` (`req-grid-thirdparty-manifest.sec` and its acceptance criteria). That manifest is the canonical provenance and integrity record — this spec deliberately does not duplicate those requirements, only the on-disk layout.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-static-assets-layout-1 | Namespaced root | Proposed | Every app's static files resolve under `<app>/static/<app>/...`. | |
| req-tap-static-assets-layout-2 | No flat layouts | Proposed | No app in the repo ships assets directly under `<app>/static/js/` or `<app>/static/css/` without the inner app-named directory. | |

### TAP vs. Vendored Split
----
RID: `req-tap-static-assets-vendor-split`
Status: `Proposed`

Within each app's namespaced static directory, TAP-authored and third-party files MUST be separated:

- `<app>/static/<app>/js/` — TAP-authored JavaScript
- `<app>/static/<app>/js/lib/` — vendored third-party JavaScript
- `<app>/static/<app>/css/` — TAP-authored CSS
- `<app>/static/<app>/css/lib/` — vendored third-party CSS

The split is **per-app**, never shared across apps. If two apps need the same library, each vendors its own copy. This makes provenance obvious from the file path and avoids hidden coupling through a shared pool.

**Generated artifacts** are a third category, narrower in scope than vendored or hand-authored. `tap_web/static/tap_web/css/tailwind.css` is the only current instance: it is produced from `tap_web/static/tap_web/css/tailwind-input.css` and the scanned templates by the pinned `tailwindcss` binary at image build time and at dev container start (see [`tap_web/specs/spec-web-tailwind-pipeline.md`](../tap_web/specs/spec-web-tailwind-pipeline.md)). Generated artifacts live in the TAP-authored CSS root rather than under `lib/` because they are not an upstream distribution, are gitignored because the build is the source of truth, and are documented as generated in their owning app's `third_party_manifest.toml` (the tool that produced them, not the file itself, is the third-party dependency).

Files in any `lib/` directory:

- MUST preserve the upstream filename where practical (e.g. `cytoscape.min.js`, not `cyto.js`)
- MUST be unmodified distributions of the upstream release
- MUST NOT be edited. If a local patch is required, the file is forked into the TAP-authored directory under a clearly distinct name, and the rationale is documented in the app's `DESIGN.md` or an appropriate spec.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-static-assets-vendor-split-1 | Vendored files under `lib/` | Proposed | Every third-party JS/CSS file in the repo lives under a `lib/` subdirectory of its owning app's namespaced static dir. | |
| req-tap-static-assets-vendor-split-2 | TAP-authored files outside `lib/` | Proposed | No TAP-authored file lives inside any `lib/` directory. | |
| req-tap-static-assets-vendor-split-3 | Unmodified vendored files | Proposed | Files under `lib/` match their upstream distribution byte-for-byte (or carry a documented fork in the TAP-authored dir). | |

### No Cross-App References
----
RID: `req-tap-static-assets-no-cross-app`
Status: `Proposed`

Templates MUST reference static assets only within their own app's namespace. A `tap_viz` template uses `{% static 'tap_viz/js/panel-graph.js' %}`; it does not reach into `{% static 'tap_web/js/...' %}`, and vice versa. Plugin templates reference only their own plugin's static namespace.

If an asset needs to be shared across apps, the sharing is made deliberate: the asset is promoted to `tap_web` (the asset layer for dashboards and UIs, per `CLAUDE.md`) and re-vendored there, or the consuming apps each vendor their own copy. Ad hoc cross-app `{% static %}` paths are not permitted because they create invisible coupling that breaks when the providing app reorganizes its assets.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-static-assets-no-cross-app-1 | Namespace discipline | Proposed | Every `{% static %}` reference in a template resolves to a path prefixed with that template's owning app name. | |

### Future

Remaining deviations from this spec:

- `tap_web/templates/tap_web/viewer.html` and `tap_web/templates/tap_web/editor.html` reference `tap_viz/js/lib/...` assets from tap_web templates, violating req-tap-static-assets-no-cross-app. Resolving this is a larger refactor (likely moving those template blocks into `tap_viz`) and is out of scope for the initial layout migration.
- The two soft mentions in [tap_web/specs/spec-web-panel.md](../tap_web/specs/spec-web-panel.md) and [tap_web/specs/spec-web-panels-standard-table.md](../tap_web/specs/spec-web-panels-standard-table.md) should be tightened to point at this canonical spec rather than restating the convention loosely.

Potential future extensions:
- A repo-level lint or CI check that enforces the acceptance criteria mechanically (no flat layouts, no cross-app `{% static %}` references, every file under a `lib/` directory has a matching entry in the owning app's `third_party_manifest.toml`).
- Subresource Integrity (SRI) attributes emitted on `<script>`/`<link>` tags using the `checksum_sha256` already recorded in `third_party_manifest.toml`.

## Status Vocabulary

Use these values consistently in the Requirements table and each requirement's `Status` line:

| Status States |  |
| --- | --- |
| Proposed | Hey everyone, here's an idea. |
| Approved for Development | Requirement is accepted and ready to be implemented. |
| In Development | Actively being worked on, see the Development section for more details. |
| Implemented | Has been written, see the Implementation section for how. |
| Verified | Has met the acceptance criteria as defined in that section. |
| Refactoring | In the process of being re-worked. |
| Deprecating | In the process of being deprecated. |
| Deprecated | No longer live. |
