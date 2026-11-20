/**
 * compound-edge.js — draw a compound edge as one arrow (req-viz-compound-edge).
 *
 * On the grid a compound edge is three or more stored pieces: a middle node, a source edge
 * from the sender into it, a destination edge from it to the receiver, and optionally a
 * carrier edge and path edges out of it (req-grid-edge-compound). On a page it should read
 * as one arrow from sender to receiver. This runtime does that:
 *
 *   - For each middle node in the scene (a node whose `compound_edge` data names its role
 *     edges — the graph panel copies it from the envelope's display lane, computed from the
 *     type's COMPOUND_EDGE declaration, req-viz-system-display-hints-11), it hides the middle
 *     node and its role edges with the `tap-compound-collapsed` class.
 *   - It adds one synthetic edge from each drawn sender to each drawn receiver, marked
 *     `_is_compound_edge` and carrying `_compound_id` (the middle node's id), labelled with
 *     the middle node's label. This is the one line on a TAP page that is not an edge in the
 *     grid; spec-viz-icon-node's `req-viz-icon-node-edges` admits exactly it.
 *   - Tapping the arrow expands it: the arrow goes, the middle node and its role edges come
 *     back. Tapping an expanded middle node collapses it again.
 *   - A compound edge with an end that is not drawn (absent from the scene, or hidden inside
 *     an icon node or by an elevation) is left as it is: no arrow is re-pointed onto anything
 *     that stands in for the missing end (the icon-node rule), so the middle node shows as the
 *     ordinary node it is.
 *
 * Modelled on applyStack: a layout module calls applyCompoundEdges(cy, opts) from its
 * execute(context) after it has positioned the scene; idempotent per handle id; destroy()
 * restores everything the pass changed.
 */

export const COMPOUND_COLLAPSED_CLASS = "tap-compound-collapsed";

const EDGE_ID_PREFIX = "compoundedge:";
const DEFAULT_HANDLE_ID = "compound";

/**
 * Collapse every compound edge in the scene into one arrow.
 *
 * @param {cytoscape.Core} cy
 * @param {Object} [opts]
 * @param {string[]} [opts.types] Middle-node entity types to collapse. Omitted: every node
 *   that carries `compound_edge` data. Type names are configuration (create-layout).
 * @param {string} [opts.id="compound"] Stable handle id for idempotent re-runs.
 * @returns {{count: number, skipped: string[], expand: Function, collapse: Function, destroy: Function}}
 *   `count` is the number of compound edges collapsed; `skipped` the middle-node ids left
 *   expanded because an end was not drawn.
 */
export function applyCompoundEdges(cy, opts = {}) {
    const handleId = opts.id || DEFAULT_HANDLE_ID;
    const types = Array.isArray(opts.types) ? new Set(opts.types) : null;

    _cleanup(cy, handleId);
    _offHandlers(cy, handleId);

    const managed = new Map(); // middle id -> {roles, pairs}
    const skipped = [];
    cy.nodes().forEach((middle) => {
        const roles = middle.data("compound_edge");
        if (!roles || typeof roles !== "object" || !roles.source || !roles.destination) return;
        if (types && !types.has(middle.data("entity_type"))) return;
        if (!_shown(middle)) return; // hidden by an elevation, a stack or nesting: not ours to draw
        const pairs = _drawnPairs(middle, roles);
        if (pairs.length === 0) {
            skipped.push(middle.id());
            return;
        }
        managed.set(middle.id(), {roles, pairs});
    });

    function collapse(middleId) {
        const entry = managed.get(middleId);
        const middle = cy.getElementById(middleId);
        if (!entry || middle.length === 0) return false;
        _removeArrows(cy, handleId, middleId);
        middle.removeData("_compound_expanded_by");
        middle.data("_compound_collapsed_by", handleId);
        middle.addClass(COMPOUND_COLLAPSED_CLASS);
        _roleEdges(middle, entry.roles).forEach((e) => {
            e.data("_compound_collapsed_by", handleId);
            e.addClass(COMPOUND_COLLAPSED_CLASS);
        });
        const label = middle.data("label") || "";
        cy.add(entry.pairs.map(([sourceId, targetId]) => ({
            group: "edges",
            data: {
                id: EDGE_ID_PREFIX + handleId + ":" + middleId + ":" + sourceId + ">" + targetId,
                source: sourceId,
                target: targetId,
                label,
                _is_compound_edge: true,
                _compound_id: middleId,
                _compound_handle: handleId,
            },
        })));
        return true;
    }

    function expand(middleId) {
        const entry = managed.get(middleId);
        const middle = cy.getElementById(middleId);
        if (!entry || middle.length === 0) return false;
        _removeArrows(cy, handleId, middleId);
        _restore(middle, handleId);
        _roleEdges(middle, entry.roles).forEach((e) => _restore(e, handleId));
        middle.data("_compound_expanded_by", handleId);
        return true;
    }

    managed.forEach((_entry, middleId) => collapse(middleId));

    function onArrowTap(evt) {
        const edge = evt.target;
        if (edge.data("_compound_handle") !== handleId) return;
        expand(edge.data("_compound_id"));
    }
    function onMiddleTap(evt) {
        const node = evt.target;
        if (node.data("_compound_expanded_by") !== handleId) return;
        collapse(node.id());
    }
    cy.on("tap", "edge[?_is_compound_edge]", onArrowTap);
    cy.on("tap", "node[_compound_expanded_by]", onMiddleTap);
    _handlers(cy).set(handleId, [onArrowTap, onMiddleTap]);

    return {
        count: managed.size,
        skipped,
        expand,
        collapse,
        destroy: () => {
            _offHandlers(cy, handleId);
            _cleanup(cy, handleId);
        },
    };
}

// ---------------------------------------------------------------------------
// Internals
// ---------------------------------------------------------------------------

const _handlersByCy = new WeakMap();

function _handlers(cy) {
    let m = _handlersByCy.get(cy);
    if (!m) {
        m = new Map();
        _handlersByCy.set(cy, m);
    }
    return m;
}

function _offHandlers(cy, handleId) {
    const m = _handlers(cy);
    const pair = m.get(handleId);
    if (!pair) return;
    cy.off("tap", "edge[?_is_compound_edge]", pair[0]);
    cy.off("tap", "node[_compound_expanded_by]", pair[1]);
    m.delete(handleId);
}

/** The middle node's role edges, by direction: the source edge points in, every other role points out. */
function _roleEdges(middle, roles) {
    const id = middle.id();
    const outbound = new Set([roles.destination, roles.carrier, roles.path].filter(Boolean));
    return middle.connectedEdges().filter((e) => {
        if (e.data("_is_compound_edge")) return false;
        const type = e.data("label");
        if (e.target().id() === id && type === roles.source) return true;
        return e.source().id() === id && outbound.has(type);
    });
}

/**
 * Is this node drawn? Read from the computed `display` / `visibility` of the node and its compound
 * ancestors rather than `visible()`, whose cached answer can lag a class change made in the same
 * tick (observed under headless cytoscape 3.34 when a class and data change together).
 */
function _shown(node) {
    let n = node;
    while (n && n.length > 0) {
        if (n.pstyle("display").value === "none" || n.pstyle("visibility").value === "hidden") return false;
        n = n.parent();
    }
    return true;
}

/** [senderId, receiverId] for every drawn sender and drawn receiver of this middle node. */
function _drawnPairs(middle, roles) {
    const id = middle.id();
    const senders = new Set();
    const receivers = new Set();
    middle.connectedEdges().forEach((e) => {
        const type = e.data("label");
        if (type === roles.source && e.target().id() === id && _shown(e.source())) senders.add(e.source().id());
        if (type === roles.destination && e.source().id() === id && _shown(e.target())) {
            receivers.add(e.target().id());
        }
    });
    const pairs = [];
    const byId = (a, b) => a.localeCompare(b);
    [...senders].sort(byId).forEach((s) => [...receivers].sort(byId).forEach((r) => pairs.push([s, r])));
    return pairs;
}

function _removeArrows(cy, handleId, middleId) {
    cy.edges("[?_is_compound_edge]")
        .filter((e) => e.data("_compound_handle") === handleId && e.data("_compound_id") === middleId)
        .remove();
}

function _restore(ele, handleId) {
    if (ele.data("_compound_collapsed_by") !== handleId) return;
    ele.removeClass(COMPOUND_COLLAPSED_CLASS);
    ele.removeData("_compound_collapsed_by");
}

function _cleanup(cy, handleId) {
    cy.edges("[?_is_compound_edge]").filter((e) => e.data("_compound_handle") === handleId).remove();
    cy.elements().filter((ele) => ele.data("_compound_collapsed_by") === handleId).forEach((ele) => _restore(ele, handleId));
    cy.nodes().filter((n) => n.data("_compound_expanded_by") === handleId).forEach((n) => n.removeData("_compound_expanded_by"));
}
