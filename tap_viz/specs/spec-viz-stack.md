# Viz Stack Specification

## Philosophy

A **stack** collapses a homogeneous set of nodes into a single visual token. When a scene contains many instances of the same kind of thing — the instances in a scaling group, the entries in a transparency log, a fan of near-identical artifacts — drawing each one individually is both noisy and a waste of canvas. The interesting fact is rarely *which* one; it is *that there are N of them*, all alike.

The stack answers that. It keeps one member on the graph as the **representative** (the face of the pile), draws a few offset **depth cards** behind it so the eye reads "a pile, not a node", and prints the **true count** in a chip. The other members are collapsed off the canvas. The result is one token that says, at a glance, "many of these, and here's how many."

A stack is a **runtime primitive**, not a projection-level feature. A layout module calls it from `execute(context)` after it has positioned (and, where applicable, nested) the member set — the same way a layout calls the nesting and arrangement runtimes. It composes with the rest of the viz stack rather than replacing any of it: members are still real graph nodes, the representative still carries its type icon and badges, and edges are preserved through re-pointing rather than discarded.

Two quantities are kept deliberately distinct. **Depth** is how many layers are drawn — capped decoration whose only job is to communicate "pile." **Count** is the cardinality of the set — the truth, carried by the chip. A pile of two hundred shows the same small stack of cards as a pile of four; only the chip differs. Depth must never be read as, or mistaken for, count.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Proxy-Collapse | One representative stands in for the whole set; the rest are collapsed off-canvas, not merely overlapped. |
| 2. | Layout-Called | A reusable runtime primitive invoked by a layout module; not bound to any one projection or domain. |
| 3. | Depth ≠ Count | Depth cards are capped decoration ("this is a pile"); the chip carries the true, unbounded cardinality. |
| 4. | Edge-Preserving | Edges from collapsed members to nodes outside the stack are re-pointed onto the representative and deduped. |
| 5. | Disclosure-Honest | The exact integer is stored on the token; the chip label is a lossy view; the exact value is recoverable. |
| 6. | Idempotent | Safe to re-run across elevation transitions; a re-run rebuilds cleanly rather than compounding. |
| 7. | Composable | Coexists with type-icon badges, status badges, nesting, and arrangements without special-casing. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-stack-primitive | [Runtime Primitive](#runtime-primitive) | Implemented | `applyStack(cy, opts)` runtime module, called by layout modules |
| req-viz-stack-proxy-collapse | [Proxy Collapse](#proxy-collapse) | Implemented | Representative stays visible; other members hidden via `tap-stack-collapsed` |
| req-viz-stack-depth | [Depth Cards](#depth-cards) | Implemented | Up to `depthCap - 1` decorative offset cards; capped, never a count |
| req-viz-stack-direction | [Growth Direction](#growth-direction) | Implemented | `auto` fans away from scene center (POV); overridable enum + per-axis `offset` |
| req-viz-stack-count-chip | [Count Chip](#count-chip) | Implemented | Neutral rounded-rect straddling the representative's bottom edge |
| req-viz-stack-count-format | [Count Formatting](#count-formatting) | Implemented | Humanized k/M/B abbreviation with bounded width |
| req-viz-stack-count-disclosure | [Count Disclosure](#count-disclosure) | Implemented | Exact integer stored on the chip; surfaced on hover; label is a derived view |
| req-viz-stack-name | [Stack Name](#stack-name) | Implemented | Optional stack name shown on the representative in place of its individual label |
| req-viz-stack-edge-collapse | [Edge Collapse](#edge-collapse) | Implemented | Re-point + dedup collapsed members' external edges onto the representative |
| req-viz-stack-min-collapse | [Collapse Threshold](#collapse-threshold) | Implemented | Below `minToCollapse` members, no-op |
| req-viz-stack-idempotent | [Idempotent Re-Run](#idempotent-re-run) | Implemented | Keyed by `stackId`; a re-run tears down the prior pass first |
| req-viz-stack-noninteractive | [Non-Interactive Helpers](#non-interactive-helpers) | Implemented | Cards/chip are not entities; excluded from tap/double-tap and badge passes |
| req-viz-stack-declarative | [Declarative Form](#declarative-form) | Proposed | A `stack` block on the Layout entity once the procedural shape has settled |
| req-viz-stack-expand | [Expand / Drill](#expand--drill) | Proposed | Reveal members via an elevation reached by double-tapping the representative |

## Requirements

### Runtime Primitive
----
RID: `req-viz-stack-primitive`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/stack.js

The stack is delivered as a client-side runtime module, `tap_viz/static/tap_viz/js/runtime/stack.js`, exporting `applyStack(cy, opts)`. A layout module calls it from `execute(context)` against the live Cytoscape instance, passing the member set it has already selected and positioned. This mirrors how layouts call the nesting and arrangement runtimes: node *identification* is the layout's responsibility (selector, gryphon, or otherwise); the stack primitive owns only the collapse, decoration, and edge handling.

`applyStack` returns a handle `{destroy, count, collapsed}`. `destroy()` removes the helper nodes and synthetic edges, un-collapses the members, and detaches listeners — restoring the pre-stack scene.

Inputs (`opts`): `members` (the full set, including the representative), optional `representative` (defaults to the first member), optional `position` for the representative, `depthCap` (default 3), `minToCollapse` (default 2), `direction` (default `"auto"` — see [Growth Direction](#growth-direction)), `offset` (px between stacked icons, default 7), `chip` (default true), `label` (the stack name — see [Stack Name](#stack-name)), and `stackId`.

### Proxy Collapse
----
RID: `req-viz-stack-proxy-collapse`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/stack.js

One member — the representative — remains on the canvas as the face of the pile and keeps all of its normal rendering (icon, label, badges, nesting parent). Every other member is collapsed by adding the `tap-stack-collapsed` class, which resolves to `display: none` through the global hidden-element style. Collapsed members remain in the graph model (so the collapse is reversible and survives as data) but are removed from layout and rendering, including their own edges.

This is a true collapse, not a visual overlap: a pile of N contributes one rendered node plus its decoration, regardless of N.

### Depth Cards
----
RID: `req-viz-stack-depth`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/stack.js

Behind the representative, `min(count, depthCap) - 1` decorative **depth cards** are drawn, each offset from the representative by a fixed per-card delta so the group reads as a fanned pile. Cards are non-interactive, reduced-opacity nodes that mirror the representative's shape and model colors (fill / border) but carry **no icon** — a faded blank token reads as "another one of these" without the icon-placement noise of a half-shown glyph on a small offset card. The cards are z-ordered front-to-back: the card nearest the front draws highest and each deeper card strictly below it, all below the representative, so the offset reads unambiguously as a stack rather than a scatter. When the representative has a nesting parent, cards are created within that same parent so they share its render layer and z-ordering.

Depth is **capped decoration**. It does not scale with the count and carries no numeric meaning. A stack of 4 and a stack of 4,000 draw the same number of cards. The cap (`depthCap`, default 3) bounds the decoration so a large pile does not sprawl.

### Growth Direction
----
RID: `req-viz-stack-direction`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/stack.js

The pile grows in a configurable direction — the side the depth cards fan toward, set by `direction` with a per-axis `offset` (px between successive icons, default 7).

**`auto`** (the default) fans the pile **away from the center of the visible scene**, mimicking the viewer's perspective: a token in the upper-right of the view builds up-right, one in the lower-left builds down-left, and so on. This reads as stable because every pile leans toward the nearest edge, away from the focal center, rather than all leaning the same way. The scene center is the center of the bounding box of all visible content (excluding helper nodes) — the proxy for "center of the initial view", since the projection's initial fit frames exactly that content. For `auto`, the direction is resolved in a **post-layout settle pass** (`settleStacks(cy)`, called by the projection runtime after every layout has run) rather than at `applyStack` time: a layout module may build a stack mid-render, before sibling layouts have positioned their nodes, so the scene center is only trustworthy once the whole scene is settled (hidden members are excluded so they don't skew it). The settle pass is idempotent and re-runs on elevation transitions. Explicit directions need no settle and apply immediately at build time.

The `auto` quadrant rule, with deterministic tiebreaks for on-axis tokens:

- strictly inside a quadrant → fan into that quadrant (upper-right → up-right, upper-left → up-left, lower-right → down-right, lower-left → down-left);
- on the center-vertical line → up-right;
- on the center-horizontal line → up-right at/right of center, up-left left of center.

On-axis cases bias **upward**; the vertical and right-of-center cases bias **right**.

**Explicit override** — any of `up-right`, `up-left`, `down-right`, `down-left`, `up`, `down`, `left`, `right` — pins the direction regardless of position. The diagonals fan on both axes; `up`/`down` and `left`/`right` fan on one. The count chip stays bottom-center in every direction (see [Count Chip](#count-chip)).

### Count Chip
----
RID: `req-viz-stack-count-chip`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/stack.js

The true cardinality is shown in a **count chip**: a neutral rounded-rectangle straddling the bottom-center edge of the representative (half on the face, half below), so the representative's icon — which communicates *what kind* of thing the pile contains — stays legible above it. The chip reuses the badge contrast treatment (a hairline halo) so the count reads over any icon.

The chip is deliberately a **neutral** color, not an alert color, and sits at the bottom of the representative — distinct in both hue and position from the alert/status badges, which occupy the upper-right corner. "How many" and "how alarming" are different signals and must not be confused. The upper-right corner is reserved for status/alert badges; the stack count does not encroach on it.

The chip uses a rounded-rectangle (not a circle) so it can carry multi-digit, humanized labels without distortion.

### Count Formatting
----
RID: `req-viz-stack-count-format`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/stack.js

Chip labels are humanized so a large pile does not overrun its token. The format (`humanizeCount`, in `tap_viz/static/tap_viz/js/runtime/format.js`):

- `< 1000` → the exact integer (`1`, `42`, `999`).
- `>= 1000` → scaled to `k` / `M` / `B`:
  - mantissa `< 10` → one decimal, with a trailing `.0` dropped (`1.2k`, `9.9k`, `2k`).
  - mantissa `>= 10` → integer (`12k`, `120k`, `15M`).
- Rounding is half-up. A carry that pushes the mantissa to `>= 1000` rolls up to the next unit (`999,999` → `1M`, not `1000k`).

Humanization keeps the rendered label bounded to a handful of glyphs, which is what lets the chip's width stay predictable rather than ballooning with the magnitude of the count.

### Count Disclosure
----
RID: `req-viz-stack-count-disclosure`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/stack.js

The humanized chip label is a **lossy display**, never the source of truth. The exact integer count is stored on the chip node and surfaced verbatim (grouped, e.g. `1,234`) on hover. The exact value is read from the stored datum — it is never reconstructed by expanding the abbreviated label. A consumer inspecting the token can always recover the true cardinality.

This is the disclosure discipline applied to the stack: store the absolute fact, derive the human view from it, and keep the fact recoverable.

### Stack Name
----
RID: `req-viz-stack-name`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/stack.js

Once a set is collapsed, the pile is best described by what the set *is* ("Rekor Entries"), not by the identity of whichever member happens to be the representative ("entry #1635734195"). An optional `label` therefore stands in for the representative's individual label while the stack is active. The original label is stashed and restored on `destroy()`, so the substitution is non-destructive and survives idempotent re-runs.

The name is the layout author's choice; the primitive does not derive it. Combined with the count chip, the token reads as "&lt;name&gt; ×&lt;count&gt;".

### Edge Collapse
----
RID: `req-viz-stack-edge-collapse`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/stack.js

When members collapse, their edges stop rendering with them. To preserve the graph's meaning, edges from collapsed members to nodes **outside** the stack are re-pointed onto the representative and deduped by `(direction, edge type, other endpoint)`:

- If the representative already carries an equivalent connection, nothing is added (a pile that all points at one target shows one edge).
- If a collapsed member connects to a distinct external endpoint the representative does not reach, a synthetic edge is added from the representative to that endpoint (a pile pointing at several distinct targets shows one edge per distinct target).
- Edges purely between members of the same stack are intra-stack and drop with the collapse.

Synthetic edges are marked as stack-owned and removed on `destroy()`.

### Collapse Threshold
----
RID: `req-viz-stack-min-collapse`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/stack.js

Below `minToCollapse` members (default 2), `applyStack` is a no-op: a lone node is left exactly as it was, with no cards and no chip. A "stack of one" is just a node.

### Idempotent Re-Run
----
RID: `req-viz-stack-idempotent`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/stack.js

A stack is keyed by `stackId` (defaulting to a value derived from the representative's id). Re-invoking `applyStack` for the same `stackId` — as happens when a projection re-runs its layouts on an elevation transition — first tears down the prior pass (removes that stack's cards, chip, and synthetic edges; un-collapses its members) and then rebuilds. Re-runs do not accumulate duplicate helpers. Distinct `stackId`s on one canvas are independent and do not interfere.

### Non-Interactive Helpers
----
RID: `req-viz-stack-noninteractive`
Status: `Implemented`
Trace: `non-python` — tap_viz/static/tap_viz/js/runtime/stack.js

Depth cards and the count chip are presentation helpers, not graph entities. They are excluded from node tap and double-tap handling (the chip answers hover only) and from the type-icon and status-badge passes, the same way existing badge and shadow helper nodes are excluded. Collapsed (hidden) members are likewise excluded from badge passes, which apply only to visible nodes.

### Declarative Form
----
RID: `req-viz-stack-declarative`
Status: `Proposed`

Once the procedural API has proven out against real consumers, a declarative `stack` block may be added to the Layout entity — member selection by gryphon, plus the presentation knobs (`depthCap`, `cardOffset`, `chip`) — resolved by the runtime the way arrangements are. The declarative shape is intentionally deferred until the procedural form has settled, so the schema is designed against real usage rather than speculation.

### Expand / Drill
----
RID: `req-viz-stack-expand`
Status: `Proposed`

Revealing the collapsed members is left to the existing elevation mechanism rather than an in-place expand gesture: a projection may target a lower elevation that renders the members un-piled, reached by double-tapping the representative. The chip's hover surface is the seam through which a future single-click member listing (reusing the info-window) could be offered. No new interaction model is introduced by the stack itself.
