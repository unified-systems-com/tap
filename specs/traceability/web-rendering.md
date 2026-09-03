<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_web/specs/spec-web-rendering.md`

| Bucket | Count |
| --- | ---: |
| mapped | 8 |
| excluded | 1 |
| unbuilt | 5 |
| 0-ACID (payable) | 3 |

## Exclusions

Reasons verbatim from each `Trace:` line; ⚠ marks zero-ACID exempt.

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-web-render-flash` | non-python |  | tap_web/templates/tap_web/base.html |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-web-render-missingpan` | Implemented | Implemented | `_panel_error` | — |
| `req-web-render-panel` | Implemented | Implemented | `panel_view` | — |
| `req-web-render-panel-edit` | Implemented | Implemented | `panel_edit_view` | — |
| `req-web-render-process` | Implemented | Implemented | `_render_page` | — |
| `req-web-rendering-pagesan.sec` | Implemented | Implemented | `_render_page` | — |
| `req-web-rendering-panelsan.sec` | Implemented | Implemented | `panel_view` | — |
| `req-web-rendering-resolution` | Implemented | Implemented | `page_view` | — |
| `req-web-rendering-slashpage` | Implemented | Implemented | `landing_view` | — |
