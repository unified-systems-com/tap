<!-- GENERATED TRACEABILITY FRAGMENT — manage.py guards --sync-accounting / --sync-evidence; do not hand-edit -->

# `tap_viz/specs/spec-viz-layouts.md`

| Bucket | Count |
| --- | ---: |
| mapped | 2 |
| excluded | 7 |
| unbuilt | 1 |
| retired | 1 |
| 0-ACID (payable) | 1 |

## Exclusions

Reasons verbatim from each `Trace:` line; ⚠ marks zero-ACID exempt.

| RID | Category | 0-ACID | Reason |
| --- | --- | :---: | --- |
| `req-viz-layout-capabilities` | narrative | ⚠ | an allowance, not a mechanism: nothing derives or enforces "layouts may do all scene work"; the runtime simply does not restrict, and the enforceable pieces (context shape, serial execution, warnings) live in the sibling requirements |
| `req-viz-layout-execution` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/layout-loader.js |
| `req-viz-layout-lotr-example` | external | ⚠ | lotr plugin (evicted; the worked saga-stage layout example lives there) |
| `req-viz-layout-module-contract` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/layout-loader.js |
| `req-viz-layout-runtime-context` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/layout-loader.js |
| `req-viz-layout-runtime-modules` | process | ⚠ | a path-namespace authoring convention (projections/ for executables, runtime/ for shared utilities); conformance is editorial, imports are authored per-module |
| `req-viz-layout-warnings-errors` | non-python | ⚠ | tap_viz/static/tap_viz/js/runtime/layout-loader.js |

## Evidence

| Requirement | Declared | Derived | Implementation | Verified by |
| --- | --- | --- | --- | --- |
| `req-viz-layout-artifact` | Implemented | Implemented | `Layout` | — |
| `req-viz-layout-dual-mode` | Implemented | Implemented | `Layout` | — |
