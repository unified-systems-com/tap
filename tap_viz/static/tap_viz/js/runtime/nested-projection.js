/**
 * tap_viz runtime: nested-projection.
 *
 * Bottom-up nested projection model (see spec-viz-nested-projection.md).
 *
 *   - Leaves have fixed true sizes from baseSizes. They are never shrunk
 *     to fit a parent.
 *   - Containers are sized to their laid-out children plus padding. Their
 *     baseSizes entry acts as a minimum floor.
 *
 * Pipeline:
 *   1. Resolve nesting relationships → parent/child assignments.
 *   2. Hide consumed containment edges; stamp _viewport_parent.
 *   3. Measure pass (bottom-up): size leaves first, then each container from
 *      its children's laid-out bbox. Each inner layout returns
 *      {width, height, placements} where placements are per-child offsets
 *      from the bbox center.
 *   4. Apply resolved widths/heights; diff the .tap-viewport-parent class.
 *   5. Place roots via a natural layout centered at origin.
 *   6. Position pass (top-down): recurse from roots, applying cached
 *      placements relative to each parent's center.
 *   7. Z-index by depth.
 *
 * No Cytoscape compound nodes are used. All nodes remain flat peers.
 * Containment is purely positional.
 */

// ---- Gryphon subset pattern parser ----
// Matches: (parent:label)-[:TYPE]->(child:label) OR (parent:label)<-[:TYPE]-(child:label)
const NESTING_PATTERN_RE = /^\(parent(?::(\w+))?\)\s*(?:-\[(?:\w+)?:?(\w+)\]->\s*\(child(?::(\w+))?\)|<-\[(?:\w+)?:?(\w+)\]-\s*\(child(?::(\w+))?\))$/;

export const HIDDEN_CONTAINMENT_CLASS = "tap-hidden-containment";
export const VIEWPORT_PARENT_CLASS = "tap-viewport-parent";
export const ELEVATION_HIDDEN_CLASS = "tap-elevation-hidden";

function parsePattern(gryphon) {
    if (!gryphon) return null;
    const m = NESTING_PATTERN_RE.exec(gryphon.trim());
    if (!m) return null;
    if (m[2]) {
        return {parentLabel: m[1] || null, childLabel: m[3] || null, edgeType: m[2], direction: "out"};
    }
    return {parentLabel: m[1] || null, childLabel: m[5] || null, edgeType: m[4], direction: "in"};
}

// ---- Nesting resolver (stamps data, no compounds) ----

/**
 * Resolve parent-child assignments from relationship declarations.
 *
 * Two relationship shapes are supported (req-viz-nested-projection-dimension-match):
 *
 *   1. Edge-walking:        {name, gryphon: "(parent:T1)-[:EDGE]->(child:T2)"}
 *      Pairs are read from cy.edges() matching the parsed pattern.
 *
 *   2. Dimension-equality:  {name, dimension_match: {parent_type, dimension}}
 *      Pairs are read from cy.nodes(): every node whose
 *      `dimensions[<dimension>]` equals a parent_type node's
 *      `dimensions[<dimension>]` becomes that parent's child. No edge
 *      required — the containment relationship is encoded in the shared
 *      dimension value. Originating case: AWS resources nesting under
 *      their aws_account via the `aws_account` spine dimension.
 *
 * Does NOT mutate cy. Returns assignment maps.
 */
export function resolveNesting(cy, relationships) {
    const warnings = [];
    const edgeRules = [];
    const dimensionRules = [];

    relationships.forEach((rel) => {
        if (rel.dimension_match) {
            const dm = rel.dimension_match;
            if (!dm.parent_type || !dm.dimension) {
                warnings.push({
                    category: "malformed_dimension_match",
                    message: `dimension_match requires parent_type and dimension; got ${JSON.stringify(dm)}`,
                });
                return;
            }
            dimensionRules.push({parentType: dm.parent_type, dimension: dm.dimension});
            return;
        }
        const parsed = parsePattern(rel.gryphon || "");
        if (!parsed) {
            warnings.push({category: "unsupported_matcher_syntax", message: `Cannot parse gryphon: ${rel.gryphon}`});
            return;
        }
        edgeRules.push(parsed);
    });

    const candidates = {};
    const consumedEdges = {};

    // Edge-walking rules.
    cy.edges().forEach((edge) => {
        if (edge.hasClass(ELEVATION_HIDDEN_CLASS)) return;
        const edgeType = edge.data("edge_type") || edge.data("label") || "";
        const sourceId = edge.source().id();
        const targetId = edge.target().id();
        const sourceType = edge.source().data("entity_type") || "";
        const targetType = edge.target().data("entity_type") || "";

        edgeRules.forEach((rule) => {
            if (edgeType !== rule.edgeType) return;
            let parentId = null;
            let childId = null;
            if (rule.direction === "out") {
                if ((!rule.parentLabel || sourceType === rule.parentLabel) &&
                    (!rule.childLabel || targetType === rule.childLabel)) {
                    parentId = sourceId;
                    childId = targetId;
                }
            } else {
                if ((!rule.parentLabel || targetType === rule.parentLabel) &&
                    (!rule.childLabel || sourceType === rule.childLabel)) {
                    parentId = targetId;
                    childId = sourceId;
                }
            }
            if (parentId && childId) {
                if (!candidates[childId]) candidates[childId] = {};
                candidates[childId][parentId] = true;
                consumedEdges[edge.id()] = [parentId, childId];
            }
        });
    });

    // Dimension-equality rules. For each rule, find every node of parent_type
    // and pair it with all other nodes whose <dimension> value matches.
    dimensionRules.forEach((rule) => {
        const parents = cy.nodes(`[entity_type="${rule.parentType}"]`)
            .filter((n) => !n.hasClass(ELEVATION_HIDDEN_CLASS));
        parents.forEach((parent) => {
            const parentDims = parent.data("dimensions") || {};
            const parentValue = parentDims[rule.dimension];
            if (parentValue == null || parentValue === "") return;
            cy.nodes().forEach((child) => {
                if (child.id() === parent.id()) return;
                if (child.hasClass(ELEVATION_HIDDEN_CLASS)) return;
                const childDims = child.data("dimensions") || {};
                if (childDims[rule.dimension] !== parentValue) return;
                if (!candidates[child.id()]) candidates[child.id()] = {};
                candidates[child.id()][parent.id()] = true;
            });
        });
    });

    const parentByChildId = {};
    Object.keys(candidates).forEach((childId) => {
        const parents = Object.keys(candidates[childId]);
        if (parents.length === 1) {
            parentByChildId[childId] = parents[0];
        } else {
            warnings.push({
                category: "multiple_parents",
                message: `Child ${childId} has ${parents.length} candidate parents: ${parents.join(", ")}`,
            });
        }
    });

    const inCycle = {};
    Object.keys(parentByChildId).forEach((startChild) => {
        const visited = {};
        let current = startChild;
        while (parentByChildId[current]) {
            if (visited[current]) {
                let cycleNode = current;
                do {
                    inCycle[cycleNode] = true;
                    cycleNode = parentByChildId[cycleNode];
                } while (cycleNode && cycleNode !== current);
                break;
            }
            visited[current] = true;
            current = parentByChildId[current];
        }
    });
    if (Object.keys(inCycle).length > 0) {
        warnings.push({category: "cycle_detected", message: `Cycle involving: ${Object.keys(inCycle).join(", ")}`});
        Object.keys(inCycle).forEach((id) => delete parentByChildId[id]);
    }

    const hiddenEdgeIds = new Set();
    Object.keys(consumedEdges).forEach((edgeId) => {
        const [parentId, childId] = consumedEdges[edgeId];
        if (parentByChildId[childId] === parentId) {
            hiddenEdgeIds.add(edgeId);
        }
    });

    return {parentByChildId, hiddenEdgeIds, warnings};
}

// ---- Main API ----

/**
 * Project nested scenes with bottom-up natural sizing.
 *
 * @param {cytoscape.Core} cy
 * @param {Object} config
 * @param {Array<{name: string, gryphon: string}>} config.relationships
 * @param {Object<string, {width: number, height: number}>} config.baseSizes
 *   True size for leaves; minimum floor for containers.
 * @param {number} config.padding - Default padding on all sides of a container's inner bbox.
 * @param {Object<string, number>} [config.paddings] - Per-parent-type padding overrides.
 * @param {string|Object} config.innerLayout - "grid" | "align-distribute-vertical" | "tiered-rows" | "flow" | "ranked" | {name, ...opts}.
 * @param {Object<string, string|Object>} [config.innerLayouts] - Per-parent-type overrides.
 * @param {boolean} [config.fit] - Fit viewport after projection.
 * @returns {Promise<{warnings: Array}>}
 */
export async function projectNested(cy, config) {
    const {relationships, baseSizes, padding, innerLayout} = config;
    const paddings = config.paddings || {};
    const innerLayouts = config.innerLayouts || {};
    const warnings = [];

    if (!relationships || !baseSizes || padding == null || !innerLayout) {
        throw new Error("projectNested: relationships, baseSizes, padding, and innerLayout are required");
    }

    // Step 1: Clear prior nesting state. .tap-viewport-parent is NOT cleared
    // here — it's diffed after resolution for flicker-free re-entry.
    _clearNestingState(cy);

    // Step 2: Resolve nesting.
    const resolved = resolveNesting(cy, relationships);
    warnings.push(...resolved.warnings);

    // Step 3: Stamp _viewport_parent + hide containment edges.
    Object.keys(resolved.parentByChildId).forEach((childId) => {
        const node = cy.getElementById(childId);
        if (!node.empty()) {
            node.data("_viewport_parent", resolved.parentByChildId[childId]);
        }
    });
    resolved.hiddenEdgeIds.forEach((edgeId) => {
        const edge = cy.getElementById(edgeId);
        if (!edge.empty()) edge.addClass(HIDDEN_CONTAINMENT_CLASS);
    });

    // Step 4: Build children map and derive roles.
    const childrenByParent = {};
    Object.keys(resolved.parentByChildId).forEach((childId) => {
        const parentId = resolved.parentByChildId[childId];
        if (!childrenByParent[parentId]) childrenByParent[parentId] = [];
        childrenByParent[parentId].push(childId);
    });
    const isContainer = (id) => Array.isArray(childrenByParent[id]) && childrenByParent[id].length > 0;

    // Top-level nodes: any non-elevation-hidden node with no _viewport_parent.
    const topLevelNodeIds = cy.nodes()
        .filter((n) => !n.hasClass(ELEVATION_HIDDEN_CLASS))
        .filter((n) => !resolved.parentByChildId[n.id()])
        .map((n) => n.id());

    // Topological order for containers — deepest first.
    const containerOrder = [];
    const seen = new Set();
    function topoVisit(id) {
        if (seen.has(id)) return;
        seen.add(id);
        (childrenByParent[id] || []).forEach(topoVisit);
        if (isContainer(id)) containerOrder.push(id);
    }
    topLevelNodeIds.forEach(topoVisit);

    // Step 5: Measure pass.
    const resolvedSize = {};          // id → {width, height}
    const placementsByParent = {};    // parentId → [{node, dx, dy}]

    // Leaves first. Shadows are sized like any other leaf of their
    // entity_type — the shadow-nodes runtime copies entity_type from the
    // primary, so baseSizes[entity_type] applies uniformly.
    cy.nodes().forEach((n) => {
        if (n.hasClass(ELEVATION_HIDDEN_CLASS)) return;
        const id = n.id();
        if (isContainer(id)) return;
        const et = n.data("entity_type") || "";
        const base = baseSizes[et] || {width: 40, height: 40};
        resolvedSize[id] = {width: base.width, height: base.height};
    });

    // Containers bottom-up.
    for (const parentId of containerOrder) {
        const parentNode = cy.getElementById(parentId);
        if (parentNode.empty()) continue;
        const parentType = parentNode.data("entity_type") || "";
        const pad = _resolvePadding(parentNode, padding, paddings);
        const layoutFn = _resolveLayoutFn(parentNode, innerLayout, innerLayouts);

        const childDescs = (childrenByParent[parentId] || [])
            .map((cid) => cy.getElementById(cid))
            .filter((n) => !n.empty() && !n.hasClass(ELEVATION_HIDDEN_CLASS))
            .map((n) => ({
                node: n,
                width: resolvedSize[n.id()].width,
                height: resolvedSize[n.id()].height,
            }));

        const floor = baseSizes[parentType] || {width: 0, height: 0};

        if (childDescs.length === 0) {
            resolvedSize[parentId] = {width: floor.width || 40, height: floor.height || 40};
            placementsByParent[parentId] = [];
            continue;
        }

        const layoutResult = layoutFn(childDescs);
        const {width: naturalW, height: naturalH, placements} = layoutResult;
        // A natural layout may report what it could not place cleanly
        // (e.g. `ranked` children without a stage). Extra keys on the
        // contract are optional; the runtime only reads `warnings`.
        if (Array.isArray(layoutResult.warnings)) warnings.push(...layoutResult.warnings);

        resolvedSize[parentId] = {
            width:  Math.max(naturalW + 2 * pad, floor.width),
            height: Math.max(naturalH + 2 * pad, floor.height),
        };
        placementsByParent[parentId] = placements;
    }

    // Step 6: Apply resolved sizes to all nodes.
    Object.keys(resolvedSize).forEach((id) => {
        const node = cy.getElementById(id);
        if (node.empty()) return;
        const sz = resolvedSize[id];
        node.style({"width": sz.width, "height": sz.height});
    });

    // Step 7: Diff .tap-viewport-parent class (flicker-free re-entry).
    const newVpParentIds = new Set(Object.keys(childrenByParent).filter(isContainer));
    cy.nodes("." + VIEWPORT_PARENT_CLASS).forEach((n) => {
        if (!newVpParentIds.has(n.id())) n.removeClass(VIEWPORT_PARENT_CLASS);
    });
    newVpParentIds.forEach((id) => {
        const n = cy.getElementById(id);
        if (!n.empty()) n.addClass(VIEWPORT_PARENT_CLASS);
    });

    // Step 8: Place roots via natural layout centered at origin.
    const rootDescs = topLevelNodeIds
        .filter((id) => resolvedSize[id])
        .map((id) => ({
            node: cy.getElementById(id),
            width: resolvedSize[id].width,
            height: resolvedSize[id].height,
        }));

    if (rootDescs.length > 0) {
        const rootLayoutFn = _resolveLayoutFn(null, innerLayout, innerLayouts);
        const rootResult = rootLayoutFn(rootDescs);
        if (Array.isArray(rootResult.warnings)) warnings.push(...rootResult.warnings);
        rootResult.placements.forEach(({node, dx, dy}) => {
            node.position({x: dx, y: dy});
        });
    }

    // Step 9: Position pass (top-down recursion).
    function placeChildren(parentId) {
        const parent = cy.getElementById(parentId);
        if (parent.empty()) return;
        const center = parent.position();
        (placementsByParent[parentId] || []).forEach(({node, dx, dy}) => {
            node.position({x: center.x + dx, y: center.y + dy});
            if (isContainer(node.id())) placeChildren(node.id());
        });
    }
    topLevelNodeIds.forEach(placeChildren);

    // Step 10: Z-index by nesting depth.
    const depthByNode = {};
    function assignDepths(id, depth) {
        depthByNode[id] = depth;
        (childrenByParent[id] || []).forEach((cid) => assignDepths(cid, depth + 1));
    }
    topLevelNodeIds.forEach((id) => assignDepths(id, 0));
    cy.nodes().forEach((n) => {
        if (n.hasClass(ELEVATION_HIDDEN_CLASS)) return;
        const d = depthByNode[n.id()] || 0;
        n.style({"z-index": d * 10});
    });

    if (config.fit) {
        cy.fit(cy.nodes().not("." + ELEVATION_HIDDEN_CLASS), 40);
    }

    return {warnings};
}

// ---- Natural layout functions ----
//
// A natural layout takes an array of {node, width, height} and returns
// {width, height, placements}, where placements = [{node, dx, dy}] are
// offsets from the bbox center. The layout does not set positions.

function _gridNatural(children, opts) {
    const spacing = (opts && opts.spacing) || 1.2;
    const n = children.length;
    if (n === 0) return {width: 0, height: 0, placements: []};

    const cols = Math.max(1, Math.ceil(Math.sqrt(n)));
    const rows = Math.max(1, Math.ceil(n / cols));

    let maxW = 0, maxH = 0;
    children.forEach((c) => {
        if (c.width > maxW) maxW = c.width;
        if (c.height > maxH) maxH = c.height;
    });
    const cellW = maxW * spacing;
    const cellH = maxH * spacing;

    const width = cols * cellW;
    const height = rows * cellH;

    const placements = children.map((c, i) => {
        const col = i % cols;
        const row = Math.floor(i / cols);
        return {
            node: c.node,
            dx: (col + 0.5) * cellW - width / 2,
            dy: (row + 0.5) * cellH - height / 2,
        };
    });
    return {width, height, placements};
}

function _alignDistributeVerticalNatural(children, opts) {
    const gap = (opts && opts.gap != null) ? opts.gap : 8;
    const typeOrder = (opts && opts.typeOrder) || null;
    const n = children.length;
    if (n === 0) return {width: 0, height: 0, placements: []};

    // Optional typed ordering: items whose entity_type appears in typeOrder
    // are placed first, in that order. Unlisted items follow, stably ordered.
    let ordered = children;
    if (typeOrder) {
        const rank = new Map(typeOrder.map((t, i) => [t, i]));
        ordered = [...children];
        ordered.sort((a, b) => {
            const ar = rank.has(a.node.data("entity_type")) ? rank.get(a.node.data("entity_type")) : Infinity;
            const br = rank.has(b.node.data("entity_type")) ? rank.get(b.node.data("entity_type")) : Infinity;
            return ar - br;
        });
    }

    const width = ordered.reduce((m, c) => Math.max(m, c.width), 0);
    const height = ordered.reduce((s, c) => s + c.height, 0) + gap * (n - 1);

    const placements = [];
    let y = -height / 2;
    ordered.forEach((c) => {
        placements.push({
            node: c.node,
            dx: 0,
            dy: y + c.height / 2,
        });
        y += c.height + gap;
    });
    return {width, height, placements};
}

/**
 * Flow layout: children packed left-to-right into rows of variable-size
 * cells, wrapping when a row would exceed the target width. Each cell is
 * its child's own size (no shared max-cell as in `grid`), so a container
 * holding a few large children among many small ones stays compact
 * (tap#292 — the git-serious account box: one repository with ~25
 * workflows beside nineteen with two).
 *
 * Target row width is derived from the children's total area and the
 * requested aspect ratio — sqrt(totalArea * aspect) — and never less than
 * the widest child, so a single oversized child always fits on its own row.
 * Rows are top-aligned; each row's height is its tallest cell; the block
 * is left-packed and returned centered on the origin.
 *
 * Opts:
 *   aspect:  target width/height of the packed block (default 1.6)
 *   gap:     edge-to-edge gap between cells and between rows (default 12)
 *   sort:    "label" (alphabetical, default) | "area-desc" (largest first,
 *            which packs tighter and reads as "the big one on top")
 */
function _flowNatural(children, opts) {
    const aspect = (opts && opts.aspect > 0) ? opts.aspect : 1.6;
    const gap = (opts && opts.gap != null) ? opts.gap : 12;
    const sort = (opts && opts.sort) || "label";
    const n = children.length;
    if (n === 0) return {width: 0, height: 0, placements: []};

    const ordered = [...children];
    if (sort === "area-desc") {
        ordered.sort((a, b) => (b.width * b.height) - (a.width * a.height));
    } else if (sort !== "input") {
        ordered.sort((a, b) => (a.node.data("label") || "").localeCompare(b.node.data("label") || ""));
    }

    const totalArea = ordered.reduce((s, c) => s + (c.width + gap) * (c.height + gap), 0);
    const widest = ordered.reduce((m, c) => Math.max(m, c.width), 0);
    const targetWidth = Math.max(widest, Math.sqrt(totalArea * aspect));

    // Row-break pass.
    const rows = [];
    let row = {cells: [], width: 0, height: 0};
    ordered.forEach((c) => {
        const needed = row.cells.length === 0 ? c.width : row.width + gap + c.width;
        if (row.cells.length > 0 && needed > targetWidth) {
            rows.push(row);
            row = {cells: [], width: 0, height: 0};
        }
        row.cells.push(c);
        row.width = row.cells.length === 1 ? c.width : row.width + gap + c.width;
        row.height = Math.max(row.height, c.height);
    });
    if (row.cells.length > 0) rows.push(row);

    const width = rows.reduce((m, r) => Math.max(m, r.width), 0);
    const height = rows.reduce((s, r) => s + r.height, 0) + gap * (rows.length - 1);

    // Placement pass: left-packed rows, top-aligned cells, block centered.
    const placements = [];
    let y = -height / 2;
    rows.forEach((r) => {
        let x = -width / 2;
        r.cells.forEach((c) => {
            placements.push({node: c.node, dx: x + c.width / 2, dy: y + c.height / 2});
            x += c.width + gap;
        });
        y += r.height + gap;
    });
    return {width, height, placements};
}

/**
 * Tiered rows layout: groups children into horizontal tiers by entity-type
 * membership, subnets/containers flush-left, primary leaves flush-right.
 *
 * Membership rule per child:
 *   - effective types = {self entity_type} ∪ (if container: direct children's entity_types)
 *   - first matching tier wins: tier matches if tier.entityTypes ∩ effective types ≠ ∅
 *   - child is placed on the "primary" (right) side if the match is via its OWN
 *     entity_type; otherwise it's on the "contained" (left) side.
 *
 * Within each row:
 *   - contained items are alphabetized by label and left-packed from the row's
 *     left edge;
 *   - primary items are alphabetized by label and right-packed to the row's
 *     right edge (preserving alphabetical L→R visual order);
 *   - if a row has only primaries OR only contained items, it is centered.
 *
 * Unassigned children (no tier matches) are collected into a final row,
 * centered.
 *
 * Opts:
 *   tiers:    [{name, entityTypes: [string, ...]}]  top-to-bottom
 *   rowGap:   vertical gap between tier rows (default 20)
 *   itemGap:  horizontal gap between items within a row (default 12)
 */
function _tieredRowsNatural(children, opts) {
    const tiers = (opts && opts.tiers) || [];
    const rowGap = (opts && opts.rowGap != null) ? opts.rowGap : 20;
    const itemGap = (opts && opts.itemGap != null) ? opts.itemGap : 12;

    if (children.length === 0 || tiers.length === 0) {
        return {width: 0, height: 0, placements: []};
    }

    const byLabel = (a, b) => (a.node.data("label") || "").localeCompare(b.node.data("label") || "");

    // Classify children into tier buckets.
    const buckets = tiers.map(() => ({contained: [], primaries: []}));
    const unassigned = [];

    children.forEach((c) => {
        const node = c.node;
        const selfType = node.data("entity_type") || "";
        const descendants = node.cy().nodes(`[_viewport_parent="${node.id()}"]`);
        const effective = new Set([selfType]);
        descendants.forEach((n) => {
            const t = n.data("entity_type");
            if (t) effective.add(t);
        });

        let placed = false;
        for (let i = 0; i < tiers.length; i++) {
            const types = tiers[i].entityTypes || [];
            if (types.some((t) => effective.has(t))) {
                if (types.includes(selfType)) {
                    buckets[i].primaries.push(c);
                } else {
                    buckets[i].contained.push(c);
                }
                placed = true;
                break;
            }
        }
        if (!placed) unassigned.push(c);
    });

    buckets.forEach((b) => {
        b.contained.sort(byLabel);
        b.primaries.sort(byLabel);
    });
    unassigned.sort(byLabel);

    // Build row records for non-empty tiers (preserving tier order).
    function _rowFor(items) {
        const containedW = items.contained.reduce((s, c) => s + c.width, 0)
            + itemGap * Math.max(0, items.contained.length - 1);
        const primariesW = items.primaries.reduce((s, c) => s + c.width, 0)
            + itemGap * Math.max(0, items.primaries.length - 1);
        const contentW = containedW + primariesW
            + (items.contained.length && items.primaries.length ? itemGap : 0);
        const heights = items.contained.map((c) => c.height)
            .concat(items.primaries.map((c) => c.height));
        const rowH = heights.length > 0 ? Math.max(...heights) : 0;
        return {
            contained: items.contained,
            primaries: items.primaries,
            containedW,
            primariesW,
            contentW,
            height: rowH,
        };
    }

    const rows = [];
    buckets.forEach((b) => {
        if (b.contained.length + b.primaries.length > 0) rows.push(_rowFor(b));
    });
    if (unassigned.length > 0) {
        rows.push(_rowFor({contained: unassigned, primaries: []}));
    }

    if (rows.length === 0) return {width: 0, height: 0, placements: []};

    const totalW = rows.reduce((m, r) => Math.max(m, r.contentW), 0);
    const totalH = rows.reduce((s, r) => s + r.height, 0) + rowGap * (rows.length - 1);

    // Place. Each row is tightly packed (contained then primaries) and
    // centered within the overall width. Rows narrower than the widest
    // row do not stretch — they sit centered so a small row doesn't
    // artificially push its primary to the far right.
    const placements = [];
    let yOffset = -totalH / 2;
    rows.forEach((row, rowIndex) => {
        if (rowIndex > 0) yOffset += rowGap;
        const rowCenterY = yOffset + row.height / 2;

        const items = [...row.contained, ...row.primaries];
        let x = -row.contentW / 2;
        items.forEach((c, i) => {
            if (i > 0) x += itemGap;
            placements.push({node: c.node, dx: x + c.width / 2, dy: rowCenterY});
            x += c.width;
        });

        yOffset += row.height;
    });

    return {width: totalW, height: totalH, placements};
}

/**
 * "ranked" natural layout — columns by an integer stage (tap#293).
 *
 * Each child carries `data._stage`, an integer set beforehand by the calling
 * layout module (the runtime derives nothing here: a module that ranks jobs
 * by their `needs:` depth, or workflows by pipeline stage, stamps the number
 * and this layout only reads it — graph-agnostic, like `flow`). Children with
 * equal stage form one column; columns are ordered by stage along
 * `direction`, and within a column children stack top-to-bottom.
 *
 * Children WITHOUT an integer `_stage` are never silently placed in column 0
 * (an unknown rendered as a known). They go to a trailing "unranked" column
 * after the highest stage — in flow direction, so it is the last column the
 * eye reaches — and a warning is returned alongside the placements.
 *
 * `rtl` is an exact mirror of `ltr`: same width/height, every dx negated
 * about the centre.
 *
 * Opts:
 *   direction:  "ltr" (stage 0 leftmost, default) | "rtl" (stage 0 rightmost)
 *   columnGap:  gap between columns (default 40)
 *   rowGap:     gap between stacked children in a column (default 12)
 *   sort:       "label" (alphabetical within a column, default) | "input"
 *               (preserve the children's input order) | "order" (by the
 *               integer `data._order` the caller stamped, ties by label —
 *               e.g. pipelines grouped by trigger class within a stage)
 *   columnLayout: "stack" (default: one child per row, top-to-bottom) |
 *               "flow" (each column is packed by `flow` into wrapping rows
 *               in the column's sorted order, so a stage with many
 *               children becomes a block instead of a tower)
 *   flowAspect: target width ÷ height of a flowed column (default 0.9)
 *
 * Returns the standard {width, height, placements} plus `warnings`.
 */
function _rankedNatural(children, opts) {
    const direction = (opts && opts.direction === "rtl") ? "rtl" : "ltr";
    const columnGap = (opts && opts.columnGap != null) ? opts.columnGap : 40;
    const rowGap = (opts && opts.rowGap != null) ? opts.rowGap : 12;
    const sort = (opts && opts.sort) || "label";
    const columnLayout = (opts && opts.columnLayout === "flow") ? "flow" : "stack";
    const flowAspect = (opts && opts.flowAspect != null) ? opts.flowAspect : 0.9;
    const warnings = [];
    if (children.length === 0) return {width: 0, height: 0, placements: [], warnings};

    const byStage = new Map();
    const unranked = [];
    children.forEach((c) => {
        const stage = c.node.data("_stage");
        if (Number.isInteger(stage)) {
            if (!byStage.has(stage)) byStage.set(stage, []);
            byStage.get(stage).push(c);
        } else {
            unranked.push(c);
        }
    });

    const stages = [...byStage.keys()].sort((a, b) => a - b);
    const columns = stages.map((s) => byStage.get(s));
    if (unranked.length > 0) {
        columns.push(unranked);
        warnings.push({
            category: "unranked_children",
            message: `${unranked.length} child(ren) without an integer _stage placed in a trailing unranked column: `
                + unranked.map((c) => c.node.id()).join(", "),
        });
    }

    const byLabel = (a, b) => (a.node.data("label") || "").localeCompare(b.node.data("label") || "");
    if (sort === "label") {
        columns.forEach((col) => col.sort(byLabel));
    } else if (sort === "order") {
        const orderOf = (c) => (Number.isInteger(c.node.data("_order")) ? c.node.data("_order") : Number.MAX_SAFE_INTEGER);
        columns.forEach((col) => col.sort((a, b) => (orderOf(a) - orderOf(b)) || byLabel(a, b)));
    }

    // Each column is either a vertical stack (one child per row) or a flow
    // block packed in the column's sorted order; both yield the same shape:
    // a width, a height, and child offsets from the column's centre.
    const blocks = columns.map((col) => {
        if (columnLayout === "flow") {
            return _flowNatural(col, {aspect: flowAspect, gap: rowGap, sort: "input"});
        }
        const w = Math.max(...col.map((c) => c.width));
        const h = col.reduce((s, c) => s + c.height, 0) + rowGap * (col.length - 1);
        const placements = [];
        let y = -h / 2;
        col.forEach((c, j) => {
            if (j > 0) y += rowGap;
            placements.push({node: c.node, dx: 0, dy: y + c.height / 2});
            y += c.height;
        });
        return {width: w, height: h, placements};
    });
    const colW = blocks.map((b) => b.width);
    const width = colW.reduce((s, w) => s + w, 0) + columnGap * (columns.length - 1);
    const height = Math.max(...blocks.map((b) => b.height));

    // Visual order: ltr walks stage-ascending left→right; rtl walks it
    // right→left. Laying the reversed sequence out from the same left edge
    // mirrors every column centre about the origin exactly.
    const order = columns.map((_, i) => i);
    if (direction === "rtl") order.reverse();

    const placements = [];
    let x = -width / 2;
    order.forEach((i, k) => {
        if (k > 0) x += columnGap;
        const cx = x + colW[i] / 2;
        blocks[i].placements.forEach(({node, dx, dy}) => placements.push({node, dx: cx + dx, dy}));
        x += colW[i];
    });

    return {width, height, placements, warnings};
}

// ---- Internal helpers ----

function _clearNestingState(cy) {
    cy.nodes().forEach((n) => {
        n.removeData("_viewport_parent");
    });
    cy.edges("." + HIDDEN_CONTAINMENT_CLASS).removeClass(HIDDEN_CONTAINMENT_CLASS);
    // .tap-viewport-parent is diffed in step 7, not cleared here.
}

function _resolvePadding(parentNode, defaultPadding, perTypePaddings) {
    if (parentNode && perTypePaddings) {
        const parentType = parentNode.data("entity_type") || "";
        if (perTypePaddings[parentType] != null) return perTypePaddings[parentType];
    }
    return defaultPadding;
}

function _resolveLayoutFn(parentNode, defaultLayout, perTypeLayouts) {
    let spec = defaultLayout;
    if (parentNode && perTypeLayouts) {
        const parentType = parentNode.data("entity_type") || "";
        if (perTypeLayouts[parentType]) spec = perTypeLayouts[parentType];
    }
    let name, opts;
    if (typeof spec === "string") {
        name = spec;
        opts = {};
    } else {
        name = (spec && spec.name) || "grid";
        opts = spec || {};
    }
    switch (name) {
        case "align-distribute-vertical":
            return (children) => _alignDistributeVerticalNatural(children, opts);
        case "tiered-rows":
            return (children) => _tieredRowsNatural(children, opts);
        case "flow":
            return (children) => _flowNatural(children, opts);
        case "ranked":
            return (children) => _rankedNatural(children, opts);
        case "grid":
        default:
            return (children) => _gridNatural(children, opts);
    }
}
