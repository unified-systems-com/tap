/**
 * stack.js — Reusable "stack" (pile / deck-collapse) primitive for TAP Viz.
 *
 * A stack collapses a homogeneous set of nodes — hosts in a scaling group,
 * transparency-log entries, anything where "there are N of the same thing" is
 * the point — into a single visual token so it stops eating canvas. The token
 * is built from three parts:
 *
 *   - Representative: one real member node, kept on the graph as the face of
 *     the pile. Its icon tells you *what kind* of thing this is.
 *   - Depth cards: up to `depthCap - 1` decorative offset nodes drawn behind
 *     the representative. Pure presentation — they say "this is a pile",
 *     nothing more. NEVER read as a count.
 *   - Count chip: a neutral rounded-rectangle straddling the bottom edge of
 *     the representative, showing the *true* cardinality (humanized for big
 *     numbers). The exact integer is stored on the chip and surfaced on hover.
 *
 * The other members are collapsed (display:none via the tap-stack-collapsed
 * class). Their edges vanish with them; edges from collapsed members to nodes
 * *outside* the stack are re-pointed onto the representative and deduped, so a
 * pile that all points at one target shows one edge, and a pile pointing at
 * several distinct targets shows one edge per distinct target.
 *
 * This is a runtime primitive, not a projection-level feature: a layout module
 * calls applyStack(cy, ...) from its execute(context) after it has positioned
 * (and, if applicable, nested) the member set. Idempotent per stackId — safe
 * to re-run across elevation transitions.
 *
 * Depth (how many cards) and count (the chip number) are deliberately
 * independent: a pile of 200 shows `depthCap` layers and a "200" chip. Depth
 * is capped decoration; the chip carries the truth. See spec-viz-stack.md.
 */

import {humanizeCount, exactCount} from "./format.js";

export const STACK_COLLAPSED_CLASS = "tap-stack-collapsed";

const CARD_ID_PREFIX = "stackcard:";
const CHIP_ID_PREFIX = "stackchip:";
const EDGE_ID_PREFIX = "stackedge:";
const TOOLTIP_CLASS = "tap-stack-tooltip";

const DEFAULT_DEPTH_CAP = 3;
const DEFAULT_MIN_TO_COLLAPSE = 2;
// Pixel shift between successive cards (and between the representative and the
// first card), applied per active axis of the stack direction.
const DEFAULT_OFFSET = 7;
// Depth-card z-index ceiling. The front card (depth 1) draws at CARD_Z_TOP - 1,
// each deeper card one lower, so the pile reads front-to-back. The
// representative sits above all cards (see node[_stack_front_id] in
// panel-graph.js, z-index 20 > CARD_Z_TOP).
const CARD_Z_TOP = 10;

// Stack growth directions → unit (dx, dy) in Cytoscape model space (+y is down).
// "auto" is resolved per-stack against the scene center (see _resolveDirection).
const DIRECTIONS = {
    "up-right":   {dx:  1, dy: -1},
    "up-left":    {dx: -1, dy: -1},
    "down-right": {dx:  1, dy:  1},
    "down-left":  {dx: -1, dy:  1},
    "up":         {dx:  0, dy: -1},
    "down":       {dx:  0, dy:  1},
    "left":       {dx: -1, dy:  0},
    "right":      {dx:  1, dy:  0},
};
const DEFAULT_DIRECTION = "auto";

// "auto" stacks awaiting a settled scene. The growth direction for "auto" depends
// on the representative's position relative to the scene center, which isn't
// reliable until every layout has positioned its nodes — applyStack may be called
// from a layout module's execute() mid-render, before sibling layouts run. So
// "auto" stacks register here and resolve in settleStacks(), which the projection
// runtime calls once all layouts have run. Keyed per-cy; each entry holds the
// shared mutable `step` object, so the resolved direction also flows through the
// representative's position-follow handler.
const _autoStacks = new WeakMap();

function _trackAuto(cy, state) {
    let m = _autoStacks.get(cy);
    if (!m) {
        m = new Map();
        _autoStacks.set(cy, m);
    }
    m.set(state.stackId, state);
}

function _untrackAuto(cy, stackId) {
    const m = _autoStacks.get(cy);
    if (m) m.delete(stackId);
}

/**
 * Resolve + apply the growth direction for every "auto" stack against the now-
 * settled scene. The projection runtime calls this AFTER all layouts have run,
 * so _sceneCenter reflects final node positions (not the partial scene visible
 * when an individual layout called applyStack). Idempotent — safe to re-run on
 * elevation transitions. Explicit-direction stacks are not tracked and need no
 * settle; no-op when no "auto" stacks exist.
 *
 * @param {cytoscape.Core} cy
 */
export function settleStacks(cy) {
    const m = _autoStacks.get(cy);
    if (!m || m.size === 0) return;
    const center = _sceneCenter(cy);
    m.forEach((state) => {
        if (!state.representative || state.representative.length === 0) return;
        const dir = _resolveDirection("auto", state.representative.position(), center);
        state.step.x = dir.dx * state.offset;
        state.step.y = dir.dy * state.offset;
        _positionParts(cy, {representative: state.representative, stackId: state.stackId, step: state.step, chipId: state.chipId});
    });
}

/**
 * Collapse a set of member nodes into a single stack token.
 *
 * @param {cytoscape.Core} cy
 * @param {Object} opts
 * @param {cytoscape.Collection|cytoscape.NodeSingular[]} opts.members
 *   The full set of nodes in the pile (including the representative).
 * @param {cytoscape.NodeSingular} [opts.representative]
 *   The face of the pile; defaults to the first member. Stays visible.
 * @param {{x:number,y:number}} [opts.position]
 *   Where to place the representative (and therefore the pile). Defaults to
 *   the representative's current position.
 * @param {number} [opts.depthCap=3] Max visual layers (representative + cards).
 * @param {number} [opts.minToCollapse=2] Below this many members, no-op.
 * @param {string} [opts.direction="auto"] Growth direction. "auto" fans the
 *   pile away from the scene center (POV perspective: a node in the lower-left
 *   builds down-left, etc.). Explicit: "up-right" | "up-left" | "down-right" |
 *   "down-left" | "up" | "down" | "left" | "right".
 * @param {number} [opts.offset=7] Pixel shift between stacked icons, per active axis.
 * @param {boolean} [opts.chip=true] Render the count chip (always bottom-center).
 * @param {string} [opts.label] Stack name shown on the representative in place
 *   of its individual label (e.g. "Rekor Entries"). Restored on destroy.
 * @param {string} [opts.stackId] Stable id for idempotent re-runs.
 * @returns {{destroy: Function, count: number, collapsed: number}}
 */
export function applyStack(cy, opts = {}) {
    const members = _toNodeArray(opts.members).filter((n) => n && n.length > 0 && n.isNode());
    const count = members.length;
    const minToCollapse = opts.minToCollapse || DEFAULT_MIN_TO_COLLAPSE;

    const representative = opts.representative && opts.representative.length > 0
        ? opts.representative
        : members[0];

    // Nothing to pile: leave the lone node (if any) untouched.
    if (count < minToCollapse || !representative || representative.length === 0) {
        return {destroy: () => {}, count, collapsed: 0};
    }

    const stackId = opts.stackId || ("stack:" + representative.id());
    const depthCap = opts.depthCap || DEFAULT_DEPTH_CAP;
    const offset = opts.offset != null ? opts.offset : DEFAULT_OFFSET;
    const direction = opts.direction || DEFAULT_DIRECTION;
    const wantChip = opts.chip !== false;

    // Idempotency: tear down any prior pass for this stackId before rebuilding.
    _cleanup(cy, stackId);

    if (opts.position) {
        representative.position({x: opts.position.x, y: opts.position.y});
    }
    const repId = representative.id();

    // --- Collapse the non-representative members -------------------------
    const memberIds = new Set(members.map((n) => n.id()));
    const collapsed = members.filter((n) => n.id() !== repId);
    collapsed.forEach((n) => {
        n.data("_stack_collapsed_by", stackId);
        n.addClass(STACK_COLLAPSED_CLASS);
    });

    // --- Re-point + dedup edges onto the representative ------------------
    // Edges with a now-hidden endpoint stop drawing on their own; we restore
    // the *distinct* outbound/inbound connections to nodes outside the stack
    // as synthetic edges from the representative, skipping any the
    // representative already carries.
    _rerouteEdges(cy, {representative, collapsed, memberIds, stackId});

    // --- Resolve growth direction ---------------------------------------
    // In "auto", the pile fans away from the center of the visible scene (the
    // content the initial fit frames), so a node in the lower-left builds
    // down-left, mimicking the viewer's perspective. Computed after collapse so
    // the now-hidden members don't skew the center. `step` is the per-card
    // shift along whichever axes the direction activates.
    const dir = _resolveDirection(direction, representative.position(), _sceneCenter(cy));
    const step = {x: dir.dx * offset, y: dir.dy * offset};

    // --- Depth cards (decoration only) ----------------------------------
    // Cards mirror the representative's shape and model colors but carry NO
    // icon: a faded blank token reads as "another one of these" without the
    // icon-placement noise of a half-shown glyph on a small offset card. They
    // are z-ordered so each deeper card sits strictly below the one in front.
    const depthShown = Math.min(count, depthCap);
    const parentId = _parentId(representative);
    const cardShape = representative.data("shape") || "ellipse";
    const cardFill = representative.data("fill_color");
    const cardBorder = representative.data("border_color");
    const cardLabelColor = representative.data("label_color");
    const repW = representative.width();
    const repH = representative.height();
    const cardEls = [];
    for (let depth = 1; depth < depthShown; depth++) {
        const data = {
            id: CARD_ID_PREFIX + stackId + ":" + depth,
            _is_stack_card: true,
            _stack_id: stackId,
            _stack_depth: depth,
            _stack_z: CARD_Z_TOP - depth,
            shape: cardShape,
        };
        if (cardFill) data.fill_color = cardFill;
        if (cardBorder) data.border_color = cardBorder;
        if (cardLabelColor) data.label_color = cardLabelColor;
        if (parentId) data.parent = parentId;
        cardEls.push({group: "nodes", data, locked: true});
    }
    representative.data("_stack_front_id", stackId);
    // Optional stack name: once collapsed, the pile is "Rekor Entries", not
    // entry #1635734195 — so the stack label stands in for the representative's
    // individual label. Stash the original so destroy() can restore it.
    if (opts.label != null) {
        if (representative.data("_stack_label_orig") === undefined) {
            representative.data("_stack_label_orig", representative.data("label"));
        }
        representative.data("label", opts.label);
    }
    if (cardEls.length > 0) {
        cy.add(cardEls);
        cardEls.forEach((c) => {
            const card = cy.getElementById(c.data.id);
            if (card.length > 0) card.style({width: repW, height: repH});
        });
    }

    // --- Count chip ------------------------------------------------------
    let chipId = null;
    if (wantChip) {
        chipId = CHIP_ID_PREFIX + stackId;
        const repMin = Math.min(repW, repH);
        const chipH = Math.max(16, repMin * 0.46);
        const label = humanizeCount(count);
        // Bounded width: humanized labels cap at ~5 glyphs. Pad generously so
        // the rounded-rect never clips the text.
        const chipW = Math.max(chipH * 1.5, label.length * (chipH * 0.6) + chipH * 0.7);
        const data = {
            id: chipId,
            _is_stack_chip: true,
            _stack_id: stackId,
            _stack_host: repId,
            _stack_count: count,
            _stack_count_label: label,
        };
        cy.add([{group: "nodes", data, locked: true}]);
        const chip = cy.getElementById(chipId);
        if (chip.length > 0) chip.style({width: chipW, height: chipH});
    }

    // --- Position cards + chip, then track the representative ------------
    _positionParts(cy, {representative, stackId, step, chipId});

    // Re-entrancy guard (tap#304, the tap#289 class): positioning the cards
    // and the chip emits `position`/`bounds` on nodes that carry
    // `_stack_front_id`, which re-enters this handler; on a flat scene the
    // recursion happens to bottom out, with the representative nested inside
    // a projectNested box (drag-group and badge-nodes also listening) it does
    // not. Skip while mid-reposition; `_positionParts` itself only moves a
    // part whose target changed.
    let repositioning = false;
    function onRepMove(evt) {
        if (evt.target.id() !== repId) return;
        if (repositioning) return;
        repositioning = true;
        try {
            _positionParts(cy, {representative, stackId, step, chipId});
        } finally {
            repositioning = false;
        }
    }
    cy.on("position bounds", "node[_stack_front_id]", onRepMove);

    // "auto" can't be trusted at call time — applyStack may run before sibling
    // layouts position their nodes — so track it for settleStacks() to resolve
    // against the settled scene. The `step` resolved above is a best-effort
    // placeholder; settleStacks mutates this same object, so onRepMove picks up
    // the corrected direction too.
    if (direction === "auto") {
        _trackAuto(cy, {representative, stackId, chipId, offset, step});
    }

    // --- Hover tooltip: exact count on the chip -------------------------
    const tooltip = chipId ? _attachTooltip(cy, {chipId, stackId, count}) : {destroy: () => {}};

    return {
        count,
        collapsed: collapsed.length,
        destroy: () => {
            cy.off("position bounds", "node[_stack_front_id]", onRepMove);
            tooltip.destroy();
            _cleanup(cy, stackId);
        },
    };
}

// ---------------------------------------------------------------------------
// Internals
// ---------------------------------------------------------------------------

function _toNodeArray(members) {
    if (!members) return [];
    if (typeof members.toArray === "function") return members.toArray();
    return Array.from(members);
}

function _parentId(node) {
    const parent = node.parent();
    return parent && parent.length > 0 ? parent.id() : null;
}

/**
 * Center of the visible scene — the proxy for "center of the initial view",
 * since the projection's initial fit() frames exactly this content. Helper
 * nodes (cards, chips, badges, shadows) are excluded so they don't skew it.
 */
function _sceneCenter(cy) {
    const real = cy.nodes(":visible").filter(
        (n) =>
            !n.data("_is_stack_card") &&
            !n.data("_is_stack_chip") &&
            !n.data("_is_badge") &&
            !n.data("_is_status_badge") &&
            !n.data("_is_shadow"),
    );
    const bb = (real.length > 0 ? real : cy.nodes(":visible")).boundingBox();
    return {x: (bb.x1 + bb.x2) / 2, y: (bb.y1 + bb.y2) / 2};
}

/**
 * Resolve a direction option to a unit (dx, dy). Explicit values map straight
 * through DIRECTIONS; "auto" fans the pile away from the scene center:
 *   - strictly inside a quadrant → that quadrant (upper-right → up-right, …)
 *   - on the center-vertical line → up-right
 *   - on the center-horizontal line → up-right (at/right of center) or up-left
 * On-axis cases bias upward; the vertical/right cases bias right. EPS gives a
 * small tolerance so a near-centered node resolves deterministically.
 */
function _resolveDirection(direction, repPos, sceneCenter) {
    if (direction && direction !== "auto") {
        return DIRECTIONS[direction] || DIRECTIONS["up-right"];
    }
    const EPS = 0.5;
    const dx = repPos.x - sceneCenter.x;
    const dy = repPos.y - sceneCenter.y;
    if (Math.abs(dx) <= EPS) return DIRECTIONS["up-right"];
    if (Math.abs(dy) <= EPS) return dx >= 0 ? DIRECTIONS["up-right"] : DIRECTIONS["up-left"];
    return {dx: dx > 0 ? 1 : -1, dy: dy < 0 ? -1 : 1};
}

function _rerouteEdges(cy, {representative, collapsed, memberIds, stackId}) {
    const repId = representative.id();

    // Connection keys the representative already covers (dir|edge_type|other).
    const repKeys = new Set();
    representative.connectedEdges().forEach((e) => {
        const sId = e.source().id();
        const tId = e.target().id();
        const type = e.data("label") || "";
        if (sId === repId) repKeys.add("out|" + type + "|" + tId);
        if (tId === repId) repKeys.add("in|" + type + "|" + sId);
    });

    const seen = new Set();
    const syntheticEls = [];
    collapsed.forEach((m) => {
        const mId = m.id();
        m.connectedEdges().forEach((e) => {
            const isOut = e.source().id() === mId;
            const otherId = isOut ? e.target().id() : e.source().id();
            if (memberIds.has(otherId)) return; // intra-stack edge — drops with the members
            const type = e.data("label") || "";
            const dir = isOut ? "out" : "in";
            const key = dir + "|" + type + "|" + otherId;
            if (repKeys.has(key) || seen.has(key)) return;
            seen.add(key);
            syntheticEls.push({
                group: "edges",
                data: {
                    id: EDGE_ID_PREFIX + stackId + ":" + key,
                    source: isOut ? repId : otherId,
                    target: isOut ? otherId : repId,
                    label: type,
                    _is_stack_edge: true,
                    _stack_id: stackId,
                },
            });
        });
    });
    if (syntheticEls.length > 0) cy.add(syntheticEls);
}

function _positionParts(cy, {representative, stackId, step, chipId}) {
    const pos = representative.position();
    if (isNaN(pos.x) || isNaN(pos.y)) return;

    const moveTo = (node, x, y) => {
        const cur = node.position();
        if (cur.x === x && cur.y === y) return;   // no-op moves must not emit (tap#304)
        node.unlock();
        node.position({x, y});
        node.lock();
    };

    cy.nodes('[_stack_id = "' + stackId + '"][?_is_stack_card]').forEach((card) => {
        const depth = card.data("_stack_depth") || 1;
        moveTo(card, pos.x + step.x * depth, pos.y + step.y * depth);
    });

    if (chipId) {
        const chip = cy.getElementById(chipId);
        if (chip.length > 0) {
            const bb = representative.boundingBox({includeLabels: false});
            moveTo(chip, pos.x, bb.y2);
        }
    }
}

function _attachTooltip(cy, {chipId, stackId, count}) {
    const container = cy.container();
    if (!container) return {destroy: () => {}};
    if (getComputedStyle(container).position === "static") {
        container.style.position = "relative";
    }

    let tip = null;
    const exact = exactCount(count);

    function show() {
        const chip = cy.getElementById(chipId);
        if (chip.length === 0) return;
        if (!tip) {
            tip = document.createElement("div");
            tip.className = TOOLTIP_CLASS;
            container.appendChild(tip);
        }
        tip.textContent = exact;
        const rp = chip.renderedPosition();
        const rh = chip.renderedHeight();
        tip.style.left = rp.x + "px";
        tip.style.top = (rp.y - rh / 2 - 6) + "px";
        tip.style.display = "block";
    }
    function hide() {
        if (tip) tip.style.display = "none";
    }

    function onOver(evt) {
        if (evt.target.data("_stack_id") === stackId) show();
    }
    function onOut(evt) {
        if (evt.target.data("_stack_id") === stackId) hide();
    }

    cy.on("mouseover", "node[_is_stack_chip]", onOver);
    cy.on("mouseout", "node[_is_stack_chip]", onOut);
    cy.on("pan zoom", hide);

    return {
        destroy: () => {
            cy.off("mouseover", "node[_is_stack_chip]", onOver);
            cy.off("mouseout", "node[_is_stack_chip]", onOut);
            cy.off("pan zoom", hide);
            if (tip && tip.parentNode) tip.parentNode.removeChild(tip);
            tip = null;
        },
    };
}

function _cleanup(cy, stackId) {
    const sel = '[_stack_id = "' + stackId + '"]';
    cy.nodes(sel + "[?_is_stack_card]").remove();
    cy.nodes(sel + "[?_is_stack_chip]").remove();
    cy.edges(sel + "[?_is_stack_edge]").remove();

    cy.nodes('[_stack_collapsed_by = "' + stackId + '"]').forEach((n) => {
        n.removeClass(STACK_COLLAPSED_CLASS);
        n.removeData("_stack_collapsed_by");
    });
    // Clear the representative's front marker for this stack, restoring the
    // original (pre-stack) label if the stack name overrode it.
    cy.nodes('[_stack_front_id = "' + stackId + '"]').forEach((n) => {
        if (n.data("_stack_label_orig") !== undefined) {
            n.data("label", n.data("_stack_label_orig"));
            n.removeData("_stack_label_orig");
        }
        n.removeData("_stack_front_id");
    });
    _untrackAuto(cy, stackId);
}
