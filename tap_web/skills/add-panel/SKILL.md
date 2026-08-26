---
name: add-panel
description: Add a new panel type (or panel instance) to a TAP plugin or app. Use for any new dashboard widget, profile page, table panel, KPI/Finding strip, info window, or graph panel mounted on a Page.
allowed-tools: Read Write Edit Bash(scripts/dc *) Bash(scripts/uuid7 *) Bash(grep *) Bash(find *) Bash(ls *) Bash(mkdir *) Glob Grep
argument-hint: <plugin_or_app_slug> <panel_slug>
---

# Add a New Panel

You are adding a panel to a TAP page. There are two distinct artifacts and you need to know up-front which you're creating:

- A **panel type** — a Python class that defines how a category of panels resolves data and renders. Lives in a plugin/app once; reusable across pages and consumers. Example: `FindingStripPanelType`, `KsiCompliancePanelType`, `tap_viz` graph panel.
- A **panel instance** — a `panel`-typed entity that mounts an instance of a panel type onto a specific page slot, with instance-specific configuration. Lives in GRIFT, owned by the *consuming* plugin (not the panel-type plugin).

Most "add a panel" requests need both. A few need only one — e.g. seeding a second instance of an existing panel type on a different page is instance-only; building a brand-new dashboard widget that no consumer needs yet is type-only.

## Authoritative Sources (read these first; do not guess from memory)

- **[`tap_web/specs/spec-web-page.md`](../../specs/spec-web-page.md)** — Page model, layout JSON shape, how slots work, `USES_PANEL` hotlink.
- **[`tap_web/specs/spec-web-panels-standard.md`](../../specs/spec-web-panels-standard.md)** — the standard panel types tap_web ships (`viewer`, `editor`, `table`, `flip`, `history`); read before deciding to author a custom type.
- **[`tap_web/specs/spec-web-panels-standard-table.md`](../../specs/spec-web-panels-standard-table.md)** — read first if your panel is tabular; the standard table panel may already cover the use case.
- **[`tap_grid/specs/spec-grid-traversal-language.md`](../../../tap_grid/specs/spec-grid-traversal-language.md)** — gryphon syntax for any data-loading queries the panel runs.
- **[`tap_grid/specs/spec-grid-search.md`](../../../tap_grid/specs/spec-grid-search.md)** — when the panel uses a Search entity instead of an inline gryphon string.
- **[`tap_grid/specs/spec-grift-v0.md`](../../../tap_grid/specs/spec-grift-v0.md)** — for seeding the panel instance and the page's `USES_PANEL` edge.

If a spec contradicts a pattern in code, flag it to the user — do not silently work around it.

## Step 1: Decide The Panel's Shape With The User

Before writing any code, agree on:

1. **Type or instance only?** Is this a brand-new panel category (type + instance), an additional instance of an existing type (instance only), or a hypothetical type with no consumer yet (type only)?
2. **Standard or custom?** Could this be one of the tap_web standard panel types (`viewer`, `editor`, `table`, `flip`, `history`)? If yes, prefer that — author a panel **instance** with the standard type's `view` and skip the panel-type code entirely. Only build a custom type when the standard panel can't express what you need (per the open-alerts panel-type requirement in the genericom plugin repo's spec; examples: plugin-defined columns the standard table can't express, row-detail expand-on-click, layout shapes outside the standard set).
3. **Plugin home for the type.** Generic panel types should live in `tap_web` so any plugin can use them. Domain-specific panel types live in the domain plugin (e.g. KSI Compliance Panel lives in `fedramp_20x_ksi`). Confirm before creating the directory.
4. **Plugin home for the instance.** Per the finding-strip instance-config requirement (genericom plugin repo's spec): the **consuming** plugin owns the instance, not the panel-type plugin. The Genericom landing's Finding Strip instance lives in the genericom plugin, not `fedramp_20x_ksi`.
5. **Slug, label, view path.** The panel type's `slug` (snake_case, e.g. `finding_strip`), `label` ("Finding Strip"), `view` template path (`<plugin>/panels/<slug>.html`).
6. **Data shape.** Where does the panel get its data? gryphon (preferred — see [`feedback_prefer_gryphon.md`](../../../../.claude/projects/-Users-george-Documents-code-tap/memory/feedback_prefer_gryphon.md)), Search entity, ORM (last resort, requires discussion). For data-loading questions or gryphon limitations, see [`feedback_gryphon_in_development.md`](../../../../.claude/projects/-Users-george-Documents-code-tap/memory/feedback_gryphon_in_development.md) — **flag missing gryphon features to the user before falling back**.
7. **Configuration surface.** What does an instance configure? List every key that lives in `panel.config` (e.g. `tiles`, `column_mode`, `hide_header`, `entity_id_param`, etc.) and whether each is required or optional.
8. **Static assets.** CSS file, JS file (if any). Server-rendered panels often need no JS.
9. **Editor view.** Is in-page editing in scope for v0? Usually no; declare `editor_view = ""`.

Write down the agreed shape before generating code; it becomes the spec section in Step 7.

## Step 2: Author The Spec First

Per the [Spec-First feedback memory](../../../../.claude/projects/-Users-george-Documents-code-tap/memory/feedback_spec_first.md), new components must be driven by a spec before code lands.

Place the spec at:

- `<panel-type-plugin>/specs/spec-<plugin>-<panel>.md` for plugin-owned panel types (e.g. `spec-fedramp-20x-ksi-finding-strip.md`).
- `tap_web/specs/spec-web-panels-<panel>.md` for tap_web-owned types.

Required sections (model on [`spec-fedramp-20x-ksi-finding-strip.md`](../../../plugins/fedramp_20x_ksi/specs/spec-fedramp-20x-ksi-finding-strip.md)):

- Philosophy — what the panel is for, why it exists separate from sibling panels.
- Goals (numbered table).
- Requirements table at top with RIDs and statuses (initially `In Development`).
- Per-requirement sections, each with:
  - Status Details (when relevant — e.g. why this is `In Development` rather than `Approved for Development`).
  - Implementation (concrete file paths, class names, field names, configuration shape).
  - Acceptance Criteria table (ACIDs that prove the requirement is met).
  - Future bullets (deferred work that has a clear shape).
- Out Of Scope (v0).
- Future (forward-looking changes).

Typical RIDs for a panel-type spec:
- `req-<panel>-panel-type` — class shape, registration, slug, label, view, css, config_defaults.
- `req-<panel>-tile-schema` / `req-<panel>-config-schema` — what `panel.config` accepts.
- `req-<panel>-resolution` — how data loads, gryphon vs ORM, error semantics.
- `req-<panel>-rendering` — template structure, CSS conventions, empty state, header behavior.
- `req-<panel>-instance-config` — how consuming plugins seed instances.

Get user agreement on the spec before generating code. Update statuses to `Implemented` as each piece lands.

## Step 3: Author The Panel Type Class

Skip if you're authoring an instance only.

Create `<panel-type-plugin>/panels/<slug>/__init__.py` with the class shape demonstrated by [`FindingStripPanelType`](../../../plugins/fedramp_20x_ksi/panels/finding_strip/__init__.py):

```python
"""<Panel name> — <one-line purpose>."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django.http import HttpRequest

    from tap_web.models import Panel

logger = logging.getLogger(__name__)


class <Class>PanelType:
    slug = "<snake_case_slug>"
    label = "<Human Label>"
    view = "<plugin>/panels/<slug>.html"
    css: list[str] = ["<plugin>/css/<slug>.css"]
    js: list[str] = []  # optional; usually empty for server-rendered panels
    editor_view = ""  # only set if in-page editing is in scope
    config_defaults: dict[str, Any] = {}  # safe defaults so an unconfigured instance still renders

    @classmethod
    def get_view_context(cls, panel: Panel, request: HttpRequest) -> dict[str, Any]:
        # Pull config off panel.config, run gryphon queries, return template context.
        # Wrap data loading in try/except so one failed query doesn't kill the page;
        # surface failures in the context (e.g. tile.error) and let the template render
        # an inline error indicator. See req-<panel>-error-handling.
        ...
```

### Class members the renderer reads

- **`slug`** — registry key. The panel page renderer matches an instance's `view` field against the registered type's `view` template path; the slug is also used in the HTMX panel URL.
- **`label`** — human-readable type name. Shown in admin / debug UIs.
- **`view`** — Django template path. Must exist under `<plugin>/templates/<plugin>/panels/<slug>.html`.
- **`css`** — list of static file paths. The page pipeline injects `<link>` tags for these.
- **`editor_view`** — separate template for an "edit mode" of the panel. Empty string if not supported.
- **`config_defaults`** — dict applied when a panel instance has no `config` field.
- **`get_view_context(panel, request)`** — `@classmethod` returning a dict the template renders. The panel argument is the `Panel` model instance; `request` is the HTTP request. **All data loading happens here**; the template should be dumb.

### Data loading

Default to **gryphon** for any read. Two shapes:

- **Search entity reference** (preferred when the query is reusable / shared):
  ```python
  from tap_grid.search import execute_search
  from tap_grid.models import Search
  search = Search.objects.get(entity_id=panel.config["search_id"])
  envelope = execute_search(search, inputs={...})
  ```
- **Inline gryphon string** (preferred when the query is panel-specific and not worth a separate Search entity):
  ```python
  from tap_grid.gryphon.executor import execute_gryphon_raw
  envelope = execute_gryphon_raw(query_str, inputs, db_alias="search_readonly")
  ```

Both return `{"nodes": [...], "edges": [...], "rows": [...], "info": {...}, "warnings": {...}}`. **Beware** of `Search.default_limit`: when set, the response is wrapped in `{count, limit, offset, results}` and you must read from `results.<key>` instead. Keep `default_limit` unset for badge / strip / tile-style panels whose JS reads `data.rows` at the top level.

### Error handling

Wrap each query in `try/except Exception as exc:` and:

- Log via `logger.exception(...)` so the traceback hits server logs.
- Surface the error string in the template context (e.g. `tile["error"] = str(exc)`).
- Return a valid context dict regardless — the panel must not crash the page.

## Step 4: Author The Template

Create `<panel-type-plugin>/templates/<plugin>/panels/<slug>.html`:

```html
<div class="tap-panel tap-panel--<panel-slug-kebab>">
    {% if not panel.config.hide_header %}{% include "tap_web/panel_header.html" %}{% endif %}
    {% if <context-key> %}
    <div class="tap-<panel>">
        ...render the data...
    </div>
    {% else %}
    <div class="tap-<panel>--empty">No <thing> configured.</div>
    {% endif %}
</div>
```

### Template conventions

- **Outer wrapper** is `<div class="tap-panel tap-panel--<panel-slug-kebab>">`. The `tap-panel` base class is global; `tap-panel--<panel>` is panel-specific.
- **Optional header** via `{% include "tap_web/panel_header.html" %}`, suppressed by `panel.config.hide_header`.
- **Empty state** must render even when the data list is empty — never produce an empty container.
- **Error rendering** — when a tile / row / section has an `error` field set by the resolver, render an inline error indicator with the message in the `title` attribute for hover.

### Tailwind: invoke /tailwind-rebuild after a class change

Templates use Tailwind utility classes (e.g. `flex`, `w-full`, `text-slate-500`, `sm:grid-cols-3`). The compiled stylesheet at `tap_web/static/tap_web/css/tailwind.css` is committed to git and regenerated **on demand** by the `/tailwind-rebuild` skill — there is NO container watcher, by design ([`tap_web/specs/spec-web-tailwind-pipeline.md`](../../specs/spec-web-tailwind-pipeline.md) explains the rationale).

If your panel template adds or removes Tailwind utility class strings (anything in a `class="..."` attribute — `flex`, `gap-4`, `text-amber-300`, responsive variants like `sm:grid-cols-3`, arbitrary values like `max-w-[90rem]`), invoke `/tailwind-rebuild` before declaring the panel done. The skill installs the pinned binary (cached after first use), rebuilds the CSS, and you commit the regenerated `tap_web/static/tap_web/css/tailwind.css` alongside the template change.

Scanned content paths: `tap_web/templates`, `tap_viz/templates`, and `plugins/**/templates`. Plugin templates are covered — utilities used only inside a plugin template will be in the compiled output after the skill runs (`req-web-tailwind-pipeline-content-paths`).

If you skip the skill after adding a new class, the symptom is "class attribute set on the element, computed style ignores it." This is NOT a CSS-specificity bug — the rule simply doesn't exist in the compiled CSS. Recognize on sight, invoke the skill, retry. Recovery procedure if the skill itself fails: [`docs/misc/doc-dev-tailwind-rebuild.md`](../../../docs/misc/doc-dev-tailwind-rebuild.md).

## Step 5: Author The CSS

Create `<panel-type-plugin>/static/<plugin>/css/<slug>.css`:

- Class names follow BEM: `.tap-<panel>`, `.tap-<panel>__<element>`, `.tap-<panel>--<modifier>`.
- Color palette defaults to TAP's slate scale (`#64748b` slate-500, `#1e293b` slate-800, `#94a3b8` slate-400, `#e2e8f0` slate-200). Domain-specific brand colors require explicit justification.
- Numeric values use `font-variant-numeric: tabular-nums` so digit width stays stable across refresh.
- Use CSS-only `:has()` overrides scoped to the panel class when the panel needs to influence enclosing page layout (see [`panel-open-alerts.css`](../../../plugins/genericom/static/genericom/css/panel-open-alerts.css) for an example).

## Step 6: Register The Panel Type

Edit the panel-type plugin's `apps.py`:

```python
from tap_plugins.base import TapPluginConfig


class <Plugin>Config(TapPluginConfig):
    def ready(self) -> None:
        super().ready()
        from plugins.<plugin>.panels.<slug> import <Class>PanelType
        from tap_web.registry import panel_type_registry

        panel_type_registry.register("<slug>", <Class>PanelType)
```

The registration **must** happen in `AppConfig.ready()` — earlier registration sites run before all apps load and miss dependencies. The registry is a `ScopedRegistry` keyed by plugin scope; the `register("<slug>", cls)` call binds the slug to the class for the duration of the process.

## Step 7: Seed The Panel Instance

Skip if you're authoring a panel type only.

In the **consuming plugin's** GRIFT directory (e.g. `plugins/genericom/grift/pages-<panel>.grift.json`):

```json
{
  "metadata": {"grift_version": "0"},
  "_reserved": {},
  "batches": [
    {
      "batch_entity": {
        "entity_id": "<scripts/uuid7>",
        "entity_type": "batch",
        "name": "<Plugin> <Panel> v0.1.0",
        "dimensions": {}
      },
      "batch_node": {
        "source": "plugins.<consuming-plugin>",
        "name": "<Plugin> <Panel> v0.1.0",
        "description": "<one-line purpose>"
      },
      "nodes": [
        {
          "entity": {
            "entity_id": "<scripts/uuid7>",
            "entity_type": "panel",
            "name": "<Instance Name>",
            "dimensions": {"tap.graph": "web"}
          },
          "node": {
            "slug": "<consuming-plugin>-<panel>",
            "name": "<Instance Name>",
            "view": "<panel-type-plugin>/panels/<slug>.html",
            "editor_view": "",
            "config": {
              "hide_header": true,
              "<config-keys>": ...
            }
          }
        }
      ],
      "edges": [
        {
          "entity": {
            "entity_id": "<scripts/uuid7>",
            "entity_type": "edge",
            "name": "Page USES_PANEL <Panel>",
            "dimensions": {}
          },
          "edge": {
            "from_entity_id": "<page-entity-id>",
            "to_entity_id": "<panel-entity-id>",
            "edge_type": "USES_PANEL",
            "properties": {"hotlink": {"model": "page", "spec": "page-panels", "value": "<slot-name>"}}
          }
        }
      ]
    }
  ]
}
```

### GRIFT bookkeeping

- All UUIDs come from `scripts/uuid7`. Never hand-shape.
- `panel.view` **must** match the panel type's `view` attribute exactly. Mismatch → page renders nothing for that slot.
- `USES_PANEL` edge `properties.hotlink.value` must match the slot name in the page's `layout.columns.<col>.rows.<row>.panel-id`. The slot name is independent of the panel slug — pages own slot names.
- Register the new GRIFT bundle in the consuming plugin's `tap-plugin.toml` under `[grift]`, with a key matching the file's base name (without `.grift.json`).

### Iterating on a panel instance

Per `req-tap-plugin-arch-iterative-dev`:

- **Version bump** (always valid): create a new batch with a fresh `batch_entity_id` and a bumped name (`v0.1.0` → `v0.2.0`). Node and edge entity IDs inside the batch stay stable so upsert applies.
- **Force re-import** (DEBUG-only): `import_plugin_grift <plugin> --force-batches=<batch_id>`.

Editing GRIFT in place without one of those paths is silently ignored.

## Step 8: Wire The Page Layout (If Needed)

If you're adding a new slot to an existing page or seating the panel on a new page, follow the **[`add-page`](../add-page/SKILL.md) skill** for the page-side work. It owns the page-layout JSON grammar, the `USES_PANEL` hotlink invariant, the `panel-id` slot semantics, and the rules for adding-a-slot-to-existing-page vs creating-a-new-page.

A panel instance on its own does nothing — it must be mounted on a page via a `USES_PANEL` edge whose `properties.hotlink.value` matches the page's `panel-id` slot. Use `add-page` for that wiring.

## Step 9: Verify End-To-End

Restart the web service if you registered a new panel type (so `AppConfig.ready()` runs):

```bash
scripts/dc restart web
```

Re-import GRIFT:

```bash
scripts/dc exec web uv run python manage.py import_plugin_grift <consuming-plugin>
```

Visit the page in a browser and confirm:

- The panel renders.
- Data loads (or the empty state renders cleanly).
- CSS is applied (no FOUC, no missing class names).
- HTMX swap re-init works if the panel has interactive JS.

Use Playwright to screenshot any new panel — per [`feedback_playwright_verify.md`](../../../../.claude/projects/-Users-george-Documents-code-tap/memory/feedback_playwright_verify.md). Save screenshots to `screenshots/` (gitignored).

## Step 10: Spec Sync

- Flip every requirement and ACID from `In Development` → `Implemented` once the panel renders correctly end-to-end.
- Update the spec's requirement-status table at the top to match.
- If any docs reference the panel's RIDs, update them per the doc-spec sync rules in [`specs/spec-docs.md`](../../../specs/spec-docs.md).

## Common Mistakes (do not commit any of these)

- **Authoring a custom type when a standard panel works.** Always check `tap_web/specs/spec-web-panels-standard*.md` first. Authoring a one-off custom panel that should have been a standard table panel creates duplicate code paths that drift apart.
- **Seeding instances from the panel-type plugin.** The Finding Strip panel type lives in `fedramp_20x_ksi`, but the Genericom landing instance lives in `plugins/genericom/`. Cross-pollination here couples the type to one consumer and blocks reuse.
- **`panel.view` doesn't match the type's `view`.** Page renders nothing for that slot. Triple-check this when you bump a batch after a rename — the GRIFT instance and the panel-type class must move in lockstep.
- **Forgetting `panel_type_registry.register()` in `AppConfig.ready()`.** Symptom: panel slug is unknown to the renderer; HTMX swap returns 404. Registration **must** be in `ready()`, not at module import time.
- **Setting `default_limit` on a Search whose results the JS reads from `data.rows`.** Pagination wraps the response in `data.results.rows`. Status badges and tile-style panels that hit `/api/v1/searches/{id}/execute` and read `data.rows` will silently fail.
- **Hand-shaped UUIDs in GRIFT.** Always use `scripts/uuid7`. The hand-shaped synthetic style was retired; new shapes will not pass the synthetic-UUID lint.
- **`USES_PANEL.properties.hotlink.value` doesn't match the page's `panel-id` slot.** Hotlink validation fails with `missing edges for: [...]` or `extra edges: [...]`. Slot name is the source of truth on the page; the edge property mirrors it.
- **Missing empty state in the template.** Empty data lists must render an empty-state element with helpful text, not an empty container.
- **Skipping the spec.** Per CLAUDE.md feedback, new components must be driven by a spec. If none exists, draft one before coding (Step 2).
- **Using ORM in the panel without flagging it.** Per [`feedback_prefer_gryphon.md`](../../../../.claude/projects/-Users-george-Documents-code-tap/memory/feedback_prefer_gryphon.md) and [`feedback_gryphon_in_development.md`](../../../../.claude/projects/-Users-george-Documents-code-tap/memory/feedback_gryphon_in_development.md): if gryphon falls down, **flag it to the user before falling back to ORM**.

## Quick Reference: Anatomy Of A Panel

```
plugins/<panel-type-plugin>/
├── apps.py                                    # registers the type in ready()
├── panels/
│   └── <slug>/
│       └── __init__.py                        # PanelType class (Step 3)
├── templates/<plugin>/panels/
│   └── <slug>.html                            # template (Step 4)
├── static/<plugin>/css/
│   └── <slug>.css                             # styling (Step 5)
└── specs/
    └── spec-<plugin>-<panel>.md               # the spec (Step 2)

plugins/<consuming-plugin>/
├── tap-plugin.toml                            # registers the GRIFT bundle
└── grift/
    └── pages-<panel>.grift.json               # panel instance + USES_PANEL edge (Step 7)
```

## Existing Panels For Reference

When designing a new panel, skim one of these end-to-end first to anchor your approach:

- **Finding Strip** — generic configurable tile strip, gryphon-driven. [`spec-fedramp-20x-ksi-finding-strip.md`](../../../plugins/fedramp_20x_ksi/specs/spec-fedramp-20x-ksi-finding-strip.md), [`panels/finding_strip/`](../../../plugins/fedramp_20x_ksi/panels/finding_strip/).
- **KSI Compliance View** — domain-specific table with plugin-defined columns. [`spec-fedramp-20x-ksi-compliance-view.md`](../../../plugins/fedramp_20x_ksi/specs/spec-fedramp-20x-ksi-compliance-view.md).
- **KSI Indicator Profile** — single-entity detail page with gryphon hub-and-spoke loading. [`spec-fedramp-20x-ksi-indicator-profile.md`](../../../plugins/fedramp_20x_ksi/specs/spec-fedramp-20x-ksi-indicator-profile.md).
- **Genericom Open Alerts** — Tabulator-backed table panel with grouping, formatters, and HTMX re-init. [`spec-genericom-open-alerts-table.md`](../../../plugins/genericom/specs/spec-genericom-open-alerts-table.md).
- **tap_viz Graph Panel** — Cytoscape-rendered graph panel with status badges and projection runtime. [`spec-viz-panel.md`](../../../tap_viz/specs/spec-viz-panel.md).
