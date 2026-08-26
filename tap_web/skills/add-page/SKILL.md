---
name: add-page
description: Add a new TAP web page (or update the layout of an existing one). Use when creating a routable page that hosts panels — landing pages, profile pages, dashboards — or when changing the panel-slot layout of an existing page.
allowed-tools: Read Write Edit Bash(scripts/dc *) Bash(scripts/uuid7 *) Bash(grep *) Bash(find *) Bash(ls *) Bash(mkdir *) Glob Grep
argument-hint: <plugin_slug> <page_slug>
---

# Add a New Page

You are adding a TAP web page. A page is a routable URL that hosts one or more panels in a grid layout. Pages own URL slugs, layout JSON (which slots exist and how they're sized), and the `USES_PANEL` edges that wire panel instances into those slots.

This skill covers two flows that share most of their machinery:

- **New page** — fresh slug, fresh layout, fresh page entity, fresh `USES_PANEL` edges.
- **Layout update** — re-publishing an existing page's layout (e.g. adding a new row, changing a slot's height, splitting a column). Same GRIFT machinery; you re-publish the same page entity_id with a new batch.

Most of the friction with pages is in the layout JSON's grammar (which is strict) and in the `USES_PANEL` hotlink invariant (which is exact-match against the layout's slots). This skill walks both.

## Authoritative Sources (read these first; do not guess from memory)

- **[`tap_web/specs/spec-web-page.md`](../../specs/spec-web-page.md)** — Page model, layout JSON contract, slug rules, hotlink semantics. This is the canonical source for everything in this skill.
- **[`tap_web/validation.py`](../../validation.py)** — the actual JSON Schema enforced on `Page.layout`. When the docs say "the layout JSON shape" they mean what's in this file.
- **[`tap_web/skills/add-panel/SKILL.md`](../add-panel/SKILL.md)** — read first if the page needs a panel that doesn't exist yet. Build the panel, then mount it on the page.
- **[`tap_grid/specs/spec-grid-hotlink.md`](../../../tap_grid/specs/spec-grid-hotlink.md)** — `USES_PANEL` is `mode: "exact"`; understanding hotlink semantics matters when the layout and edges drift.
- **[`tap_grid/specs/spec-grift-v0.md`](../../../tap_grid/specs/spec-grift-v0.md)** — for seeding the page entity and its edges.

If a spec contradicts a pattern in code, flag it to the user — do not silently work around it.

## Step 1: Decide The Page's Shape With The User

Before writing any code, agree on:

1. **New page or layout update?** A new page needs a fresh entity_id, slug, layout, and edges. A layout update re-publishes an existing page's entity_id with a new batch, keeping the entity stable.
2. **URL slug** (e.g. `/genericom`, `/fedramp-ksi/finding`, `/admin/dimensions`). Must start with `/`. Must not collide with reserved prefixes (admin areas, panel HTMX routes). Lowercase + kebab-case is the convention.
3. **Page name** — human-readable title. Shows in the browser tab and the page header.
4. **Plugin home** — which plugin's GRIFT seeds the page. Usually the consuming plugin (the one whose users will navigate here). For pages that combine panels from multiple plugins, the consuming plugin still owns the page entity; cross-plugin references are by entity_id.
5. **Panel inventory** — list every panel slot the page needs. For each slot:
   - **Slot name** (e.g. `kpi`, `main`, `alerts`) — short kebab-case. Lives in `layout.columns.<col>.rows.<row>.panel-id`.
   - **Panel instance** — which panel-typed entity mounts in this slot. If the panel type doesn't exist yet, **stop and run [`add-panel`](../add-panel/SKILL.md) first**. Do not author both the panel and the page in the same skill invocation; the panel skill exists for a reason.
   - **Panel instance plugin** — which plugin's GRIFT seeds the panel instance. Often the same plugin as the page; sometimes different.
6. **Layout grid** — number of columns, their widths, rows per column, row heights. The layout grammar is intentionally constrained (see [Step 4](#step-4-author-the-layout-json)); the user should sketch the grid before you write JSON.
7. **Navigation** — should the new page appear in any navigation menu, sidebar, or breadcrumb chain? Many pages are reachable only via drill-down click handlers (e.g. EC2 instance page is opened by clicking an EC2 node in the Genericom landing graph) and don't need a top-level nav entry.
8. **Spec home** — should this page get its own spec? For a new domain page (Genericom landing, KSI Indicator Profile, Finding Profile) yes; for a routine layout update on an existing page, fold the change into the existing page's spec.

Write down the agreed shape before generating GRIFT; it becomes the spec section in [Step 2](#step-2-author-or-update-the-spec).

## Step 2: Author Or Update The Spec

Per the [Spec-First feedback memory](../../../../.claude/projects/-Users-george-Documents-code-tap/memory/feedback_spec_first.md), new pages must be driven by a spec before code lands. Layout updates on existing pages should update the existing page's spec rather than spawn a new one.

### New page spec

Place at `<plugin>/specs/spec-<plugin>-<page-slug>.md`. Required sections (model on existing page specs like [`spec-fedramp-20x-ksi-compliance-view.md`](../../../plugins/fedramp_20x_ksi/specs/spec-fedramp-20x-ksi-compliance-view.md) or [`spec-fedramp-20x-ksi-indicator-profile.md`](../../../plugins/fedramp_20x_ksi/specs/spec-fedramp-20x-ksi-indicator-profile.md)):

- Philosophy — what the page is for, who uses it, what the navigation entry point is.
- Goals (numbered table).
- Requirements table at top with RIDs and statuses (initially `In Development`).
- Per-requirement sections covering:
  - **Page Entity** — slug, name, layout shape.
  - **Panel Slots** — which panel instances mount in which slots, in what order, with what heights/widths.
  - **Navigation** — how users reach this page (drill-down click, nav menu, direct URL).
  - **Data Loading** — if any panel uses URL query params (`entity_id`, dimension filters, etc.), document the contract.
  - **Future** for deferred page concerns (auth, breadcrumbs, edit mode).
- Out Of Scope (v0).
- Future.

Typical RIDs:

- `req-<page>-page-entity` — slug, name, basic layout shape.
- `req-<page>-panel-slots` — slot-to-panel mapping.
- `req-<page>-navigation` — how the page is reached.
- `req-<page>-url-params` (optional) — when the page reads `entity_id` or other query params.

### Layout update

Edit the existing page's spec to:

- Add a new requirement (or new ACID under an existing requirement) describing the layout change.
- Document why the layout changed — what new panel was introduced, why an existing slot moved or resized.
- Reference the new GRIFT batch's version (e.g. "Layout v0.2.0 adds the Open Alerts row").

Get user agreement on the spec before writing GRIFT. Update statuses to `Implemented` once the page renders correctly.

## Step 3: Make Sure The Panels Exist

A page is a hollow shell without panel instances. Before authoring the page GRIFT, confirm every slot has a panel instance to mount:

```bash
scripts/dc exec web uv run python manage.py shell -c "
from tap_web.models import Panel
for slot, instance_id in [('kpi', '<uuid>'), ('main', '<uuid>'), ('alerts', '<uuid>')]:
    p = Panel.objects.filter(entity_id=instance_id).first()
    print(f'{slot}: {\"ok\" if p else \"MISSING\"} {p.name if p else instance_id}')
"
```

If any panel is missing, **stop here** and use [`add-panel`](../add-panel/SKILL.md) to seed it. Do not paper over a missing panel by leaving its slot out of the layout — that hides the dependency and creates a half-complete page.

## Step 4: Author The Layout JSON

The layout JSON has a **strict, schema-validated** grammar. The full schema lives in [`tap_web/validation.py::_PAGE_LAYOUT_SCHEMA`](../../validation.py). Key constraints:

```json
{
  "columns": {
    "col-1": {
      "width": "1fr",
      "rows": {
        "row-1": {"panel-id": "kpi", "height": "auto"},
        "row-2": {"panel-id": "main", "height": "1fr"},
        "row-3": {"panel-id": "alerts", "height": "auto"}
      }
    }
  }
}
```

### Hard rules (the validator rejects anything else)

- **`columns` is required.** A layout with no columns fails validation.
- **Column keys** match `^col-[1-9][0-9]*(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?$` — `col-1`, `col-2`, `col-3-aside`, etc. Numeric suffixes start at 1, never 0.
- **Column `width`** is one of `auto`, `1fr` … `12fr`. No pixel widths, no percentages, no `min-content`.
- **`rows` is required** within each column.
- **Row keys** match `^row-[1-9][0-9]*(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?$`. Same numeric-suffix rule.
- **Row `panel-id`** is required, matches `^[a-z][a-z0-9-]*$`. This is the slot name; it's matched **exactly** by `USES_PANEL.properties.hotlink.value`.
- **Row `height`** is one of `auto`, `1fr` … `12fr`. Same set as column width.
- **`row_span` / `col_span`** (optional): integers ≥ 1; default 1. Rarely needed in v0 layouts.
- **`tags`** (optional): map of kebab-case keys to kebab-case values, on either columns or rows. Used for downstream styling hooks; not interpreted by the schema itself.
- **Unknown keys are rejected** at column- and row-level. The schema is deliberately strict.

### Sizing semantics

- `auto` — claim only the intrinsic size of the content. Use for headers, KPI strips, summary rows.
- `1fr` … `12fr` — fractional units. A row marked `1fr` claims whatever space remains after `auto` rows have taken theirs. Multiple `Nfr` rows split the remaining space proportionally.
- A column with one `auto` row plus one `1fr` row produces a "header on top, fills below" stack — the most common shape.

### Common shapes

**Single-column landing page** (Genericom):

```json
{
  "columns": {
    "col-1": {
      "width": "1fr",
      "rows": {
        "row-1": {"panel-id": "kpi", "height": "auto"},
        "row-2": {"panel-id": "main", "height": "1fr"},
        "row-3": {"panel-id": "alerts", "height": "auto"}
      }
    }
  }
}
```

**Two-column profile page** (sidebar + main):

```json
{
  "columns": {
    "col-1-side": {
      "width": "1fr",
      "rows": {"row-1": {"panel-id": "metadata", "height": "auto"}}
    },
    "col-2-main": {
      "width": "3fr",
      "rows": {"row-1": {"panel-id": "main", "height": "1fr"}}
    }
  }
}
```

**Single-panel page** (drill-down detail):

```json
{
  "columns": {
    "col-1": {
      "width": "1fr",
      "rows": {"row-1": {"panel-id": "main", "height": "1fr"}}
    }
  }
}
```

If the user wants something the grammar can't express, **flag it** before working around it. The schema's strictness is intentional; loosening it requires a spec change.

## Step 5: Author The Page GRIFT

Place at `plugins/<plugin>/grift/<page>-page.grift.json` (e.g. `pages.grift.json` for a plugin's main landing, or `<page-slug>-page.grift.json` for a profile page).

Bundle shape:

```json
{
  "metadata": {"grift_version": "0"},
  "_reserved": {},
  "batches": [
    {
      "batch_entity": {
        "entity_id": "<scripts/uuid7>",
        "entity_type": "batch",
        "name": "<Plugin> <Page Name> v0.1.0",
        "dimensions": {}
      },
      "batch_node": {
        "source": "plugins.<plugin>",
        "name": "<Plugin> <Page Name> v0.1.0",
        "description": "<one or two sentences explaining what the page is and what panels it hosts>"
      },
      "nodes": [
        {
          "entity": {
            "entity_id": "<scripts/uuid7>",
            "entity_type": "page",
            "name": "<Page Name>",
            "dimensions": {"tap.graph": "web"}
          },
          "node": {
            "name": "<Page Name>",
            "slug": "/<page-slug>",
            "layout": { ...the layout JSON from Step 4... }
          }
        }
      ],
      "edges": [
        {
          "entity": {
            "entity_id": "<scripts/uuid7>",
            "entity_type": "edge",
            "name": "Page USES_PANEL <slot-name>",
            "dimensions": {}
          },
          "edge": {
            "from_entity_id": "<page-entity-id>",
            "to_entity_id": "<panel-instance-entity-id>",
            "edge_type": "USES_PANEL",
            "properties": {"hotlink": {"model": "page", "spec": "page-panels", "value": "<slot-name>"}}
          }
        }
      ]
    }
  ]
}
```

### The hotlink invariant

The `Page` model declares a `mode: "exact"` hotlink:

```python
HOTLINKS: ClassVar[list[dict]] = [
    {
        "name": "page-panels",
        "field": "layout",
        "selector_type": "simple_path",
        "selector": "columns.*.rows.*.panel-id",
        "edge_direction": "outbound",
        "edge_type": "USES_PANEL",
        "mode": "exact",
    }
]
```

This means: **every `panel-id` value extracted from the layout must have a corresponding `USES_PANEL` edge with `properties.hotlink.value` equal to that panel-id, and vice versa**. Drift in either direction fails import with `missing edges for: [...]` or `extra edges: [...]`.

When you author the GRIFT:

- One `USES_PANEL` edge per slot in the layout.
- The edge's `from_entity_id` is the page entity_id.
- The edge's `to_entity_id` is the panel instance entity_id (from Step 3's verification).
- The edge's `properties.hotlink.value` is the slot name (`panel-id`) from the layout, **not** the panel's slug or name.

### GRIFT bookkeeping

- All UUIDs come from `scripts/uuid7`. Never hand-shape.
- Register the new GRIFT bundle in the consuming plugin's `tap-plugin.toml` under `[grift]`, with a key matching the file's base name (without `.grift.json`).

### Iterating on a page

Per `req-tap-plugin-arch-iterative-dev`:

- **Version bump** (always valid): create a new batch with a fresh `batch_entity_id` and a bumped name (`v0.1.0` → `v0.2.0`). The page's entity_id stays stable; the layout JSON updates in place. New `USES_PANEL` edges (for newly-added slots) get fresh entity_ids; removed edges should be in the new batch's edge list as `delete_edge` ops if those edges shouldn't exist anymore (or the batch-scoped sweep handles it — see [`spec-tap-plugin-architecture.md` Iterative Development](../../../tap_plugins/specs/spec-tap-plugin-architecture.md#iterative-development)).
- **Force re-import** (DEBUG-only): `import_plugin_grift <plugin> --force-batches=<batch_id>`.

Editing GRIFT in place without one of those paths is silently ignored.

## Step 6: Confirm The URL Route Resolves

The page's `slug` field doubles as the URL path. The Django URL configuration is generic — any `Page` entity in the database with a slug `/foo` becomes routable at `/foo` automatically; you do **not** add a new entry to a `urls.py` file for each page.

If the slug collides with a reserved prefix, the validator rejects it at import time. Reserved prefixes include the admin URL prefix, the HTMX panel URL prefix (`/panel/`), and any other path Django routes have already claimed. The full reserved-prefix list is computed from the URL configuration; see [`tap_web/validation.py::validate_page_slug`](../../validation.py).

## Step 7: Wire Navigation (If Needed)

A page reachable only by direct URL or drill-down click handler doesn't need any nav work. If the page should appear in a top-level menu, sidebar, or breadcrumb chain, the navigation surface lives in the relevant template — usually a base template the plugin extends or a navigation partial included in the site chrome.

Check the consuming plugin's templates for an existing navigation partial before adding a new one. Authoring a new top-level navigation surface is a design decision worth raising with the user — most TAP pages so far have been reached via drill-down, not menu.

### If you edit a template

Most page work is JSON layout assembly and doesn't touch templates. If this step (or an earlier step) had you adding Tailwind utility classes to a navigation partial, base template, or any other HTML, invoke `/tailwind-rebuild` before declaring the page done and commit the regenerated `tap_web/static/tap_web/css/tailwind.css` alongside the template change. The compiled CSS is committed in git — no container watcher, by design ([`tap_web/specs/spec-web-tailwind-pipeline.md`](../../specs/spec-web-tailwind-pipeline.md)). Scanned paths include `tap_web/templates`, `tap_viz/templates`, and `plugins/**/templates`.

If the skill itself fails, recovery procedure is in [`docs/misc/doc-dev-tailwind-rebuild.md`](../../../docs/misc/doc-dev-tailwind-rebuild.md).

## Step 8: Verify End-To-End

Re-import GRIFT:

```bash
scripts/dc exec web uv run python manage.py import_plugin_grift <plugin>
```

Common failure modes and what they mean:

| Error | Cause | Fix |
| --- | --- | --- |
| `Hotlink 'page-panels' (exact): missing edges for: [...]` | Layout references a `panel-id` slot that has no `USES_PANEL` edge. | Add the edge in the same batch, or remove the slot from the layout. |
| `Hotlink 'page-panels' (exact): extra edges: [...]` | A `USES_PANEL` edge exists with a `hotlink.value` that the layout doesn't have. | Remove the edge or add the slot to the layout. |
| `slug must start with /` | Slug missing leading `/`. | Add it. |
| `slug ... is reserved` | Slug collides with admin / HTMX / static URL prefix. | Rename. |
| `panel-id ... does not match pattern` | Slot name has uppercase, underscores, or starts with a digit. | Use kebab-case starting with a letter. |

Visit the page in a browser:

```bash
# WEB_PORT comes from .env.local
open http://localhost:$WEB_PORT/<page-slug>
```

Confirm:

- The page renders.
- Every slot is filled by its panel; no empty slots.
- Layout proportions match the user's intent (auto rows shrink, fr rows expand).
- No console errors from any panel's JS init.

Use Playwright to screenshot any new page — per [`feedback_playwright_verify.md`](../../../../.claude/projects/-Users-george-Documents-code-tap/memory/feedback_playwright_verify.md). Save to `screenshots/` (gitignored).

## Step 9: Spec Sync

- Flip every requirement and ACID from `In Development` → `Implemented` once the page renders correctly end-to-end.
- Update the spec's requirement-status table at the top to match.
- If any docs reference the page's RIDs, follow the doc-spec sync rules in [`specs/spec-docs.md`](../../../specs/spec-docs.md).

## Common Mistakes (do not commit any of these)

- **Authoring the page before the panels exist.** Pages are hollow without panels. If [Step 3](#step-3-make-sure-the-panels-exist) finds a missing panel, stop and run [`add-panel`](../add-panel/SKILL.md) first.
- **`panel-id` ≠ `USES_PANEL.hotlink.value`.** The hotlink is `mode: "exact"`. Any drift fails import. Slot names are the source of truth on the page side; the edge property mirrors them.
- **Using the panel's `slug` as `panel-id`.** Slots are owned by the page, not the panel. The Genericom landing's `kpi` slot mounts a panel whose slug is `genericom-finding-strip` — those names don't have to match.
- **Hand-shaped UUIDs.** Always use `scripts/uuid7`.
- **Bumping `Page.entity_id` instead of bumping the batch.** The page entity_id should stay stable across layout updates; the *batch* gets a fresh entity_id. Re-publishing a page with a new entity_id breaks every existing reference (drill-down click handlers, internal links, search results).
- **Editing GRIFT in place without bumping the batch.** Idempotent re-imports skip unchanged batches. Either bump the batch_entity_id (always valid) or use `--force-batches` (DEBUG-only).
- **Skipping the spec.** Per CLAUDE.md feedback, new components must be driven by a spec.
- **Inventing a column or row width outside the schema's enum.** The grammar is strict on purpose. If you think you need a non-grammar value, raise it as a spec change before working around it.
- **Adding a `urls.py` entry for the page.** TAP routes pages from the database; you do not edit Django URL configuration per-page.
- **Letting layout updates drift between page spec and panel specs.** If you re-arrange the layout to add a row that mounts a new panel, both the page spec and the panel spec should reflect the change. The doc-spec sync rules in `spec-docs.md` apply.

## Quick Reference: Anatomy Of A Page

```
plugins/<consuming-plugin>/
├── tap-plugin.toml                            # registers the page-GRIFT bundle
├── grift/
│   └── <page-slug>-page.grift.json            # page entity + USES_PANEL edges (Step 5)
└── specs/
    └── spec-<plugin>-<page-slug>.md           # page spec (Step 2)
```

## Existing Pages For Reference

When designing a new page, skim one of these end-to-end first to anchor your approach:

- **Genericom Landing** — single-column page with KPI strip + graph + alerts table. Layout owned by [`open-alerts.grift.json`](../../../plugins/genericom/grift/open-alerts.grift.json) (because the alerts row is added on top of an earlier batch); base layout from [`pages.grift.json`](../../../plugins/genericom/grift/pages.grift.json).
- **KSI Compliance View** — single-panel page driven by a domain-specific table. [`spec-fedramp-20x-ksi-compliance-view.md`](../../../plugins/fedramp_20x_ksi/specs/spec-fedramp-20x-ksi-compliance-view.md), [`grift/ksi-compliance-page.grift.json`](../../../plugins/fedramp_20x_ksi/grift/ksi-compliance-page.grift.json).
- **KSI Indicator Profile** — drill-down profile page reading `entity_id` from query params. [`spec-fedramp-20x-ksi-indicator-profile.md`](../../../plugins/fedramp_20x_ksi/specs/spec-fedramp-20x-ksi-indicator-profile.md), [`grift/ksi-indicator-profile-page.grift.json`](../../../plugins/fedramp_20x_ksi/grift/ksi-indicator-profile-page.grift.json).
- **EC2 Instance Page (Genericom)** — drill-down profile reached by clicking an EC2 node in the landing graph. [`grift/ec2-instance-page.grift.json`](../../../plugins/genericom/grift/ec2-instance-page.grift.json).
