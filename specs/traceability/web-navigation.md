<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_web/specs/spec-web-navigation.md`

| Bucket | Count |
| --- | ---: |
| mapped | 5 |
| excluded | 5 |
| unbuilt | 2 |
| retired | 1 |
| 0-ACID (payable) | 0 |

## Exclusions

Reasons verbatim from each `Trace:` line; ⚠ marks zero-ACID exempt.

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-web-nav-breadcrumb-header` | non-python |  | tap_web/templates/tap_web/base.html |
| `req-web-nav-chrome-budget` | process |  | change-control on the header's enumerated element budget; additions require a spec revision, conformance is review discipline |
| `req-web-nav-no-hamburger` | process |  | a standing design prohibition; code cannot demonstrate an absence, review discipline holds the line |
| `req-web-nav-segment-interactions` | non-python |  | tap_web/static/tap_web/js/breadcrumb.js |
| `req-web-nav-user-menu` | non-python |  | tap_web/templates/tap_web/base.html |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-web-nav-auto-parent` | Implemented | Implemented | `build_breadcrumb` | — |
| `req-web-nav-chrome-read-free` | Implemented | Implemented | `breadcrumb` | — |
| `req-web-nav-index-endpoint` | Implemented | Implemented | `nav_index_view` | — |
| `req-web-nav-page-discoverable` | Implemented | Implemented | `Page` | — |
| `req-web-nav-page-weight` | Implemented | Implemented | `Page` | — |
