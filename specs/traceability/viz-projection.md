<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_viz/specs/spec-viz-projection.md`

| Bucket | Count |
| --- | ---: |
| excluded | 7 |
| unbuilt | 2 |
| retired | 4 |
| unaccounted | 2 |
| 0-ACID (payable) | 1 |

## Exclusions

Reasons verbatim from each `Trace:` line; ⚠ marks zero-ACID exempt.

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-viz-projection-elevation-invariants` | process |  | the entry-asserts-state authoring contract for elevation layouts; there is no exit hook to enforce, each layout author conforms at entry |
| `req-viz-projection-incremental-loading` | process | ⚠ | a v0 placement decision (follow-up fetch lives inside tap layouts, no separate elevation-level search contract); guidance for layout authors, no core mechanism |
| `req-viz-projection-layout-runtime` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/projection.js |
| `req-viz-projection-lock-nodes` | non-python |  | tap_viz/static/tap_viz/js/runtime/projection.js |
| `req-viz-projection-lotr-monolith` | external | ⚠ | lotr plugin (evicted; the worked monolithic projection lives in its grift bundle) |
| `req-viz-projection-min-zoom` | non-python |  | tap_viz/static/tap_viz/js/runtime/projection.js |
| `req-viz-projection-self-contained` | narrative | ⚠ | a design principle (projections depend on no model-level display hints); the substance is distributed across the searches/elevations/layout machinery of the sibling requirements |
