/**
 * arrangement.js — Post-layout positioning runtime.
 *
 * Executes an ordered list of arrangement definitions against a Cytoscape
 * instance. Each arrangement identifies an anchor node and member nodes via
 * server-side gryphon queries, then repositions the members along an axis
 * relative to the anchor.
 *
 * See spec-viz-arrangement.md.
 */

const GRYPHON_URL = "/api/v1/gryphon/execute";

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Execute an ordered list of arrangements against the Cytoscape instance.
 *
 * @param {cytoscape.Core} cy - The active Cytoscape instance.
 * @param {Array<Object>} arrangements - Arrangement definitions in execution order.
 * @param {Object} inputs - Runtime input variables passed through to gryphon queries.
 * @returns {Promise<{warnings: string[]}>} Collected warnings from all arrangements.
 */
export async function executeArrangements(cy, arrangements, inputs) {
    const warnings = [];

    for (const arrangement of arrangements) {
        try {
            const result = await _executeOne(cy, arrangement, inputs);
            warnings.push(...result.warnings);
        } catch (err) {
            warnings.push(`arrangement_error: ${err.message}`);
        }
    }

    return {warnings};
}

// ---------------------------------------------------------------------------
// Internal
// ---------------------------------------------------------------------------

async function _executeOne(cy, arrangement, inputs) {
    const warnings = [];

    // --- Resolve anchor ---
    const anchorResult = await _executeGryphon(arrangement.anchor.gryphon, inputs);
    const anchorNodes = anchorResult.nodes || [];

    if (anchorNodes.length === 0) {
        warnings.push("arrangement_anchor_missing");
        return {warnings};
    }
    if (anchorNodes.length > 1) {
        warnings.push("arrangement_anchor_ambiguous");
        return {warnings};
    }

    const anchorId = anchorNodes[0].entity_id;
    const anchorEle = cy.getElementById(anchorId);
    if (!anchorEle || anchorEle.length === 0 || anchorEle.hasClass("tap-elevation-hidden")) {
        warnings.push("arrangement_anchor_missing");
        return {warnings};
    }

    // --- Resolve members ---
    const membersResult = await _executeGryphon(arrangement.members.gryphon, inputs);
    const memberIds = (membersResult.nodes || []).map((n) => n.entity_id);

    // Match against cy elements, exclude anchor and hidden nodes.
    const members = memberIds
        .map((id) => cy.getElementById(id))
        .filter((ele) => ele && ele.length > 0)
        .filter((ele) => ele.id() !== anchorId)
        .filter((ele) => !ele.hasClass("tap-elevation-hidden"));

    if (members.length === 0) {
        return {warnings};
    }

    // --- Determine axis ---
    const isVertical = arrangement.positioning === "vertical";
    const axisKey = isVertical ? "y" : "x";
    const crossKey = isVertical ? "x" : "y";

    // --- Step 1: Axis snapping ---
    const anchorPos = anchorEle.position();
    const crossValue = anchorPos[crossKey];

    for (const ele of members) {
        const pos = {...ele.position()};
        pos[crossKey] = crossValue;
        ele.position(pos);
    }

    // --- Step 2: Even distribution ---
    if (arrangement.distribution === "even" && members.length >= 1) {
        // Sort members by their current position along the axis so the
        // result is deterministic regardless of fetch order.
        members.sort((a, b) => a.position()[axisKey] - b.position()[axisKey]);

        const spanPx = arrangement.span_px;
        const anchorOffsetPx = arrangement.anchor_offset_px;
        const anchorAxisValue = anchorPos[axisKey];
        const hasExplicitPlacement = spanPx != null || anchorOffsetPx != null;

        let start;
        let end;
        if (hasExplicitPlacement) {
            // Anchor-relative placement: members start at
            // anchor + anchor_offset_px (default 0) and span span_px total
            // along the axis. All members end up on one side of the anchor
            // when anchor_offset_px > 0 — the typical "story reads below
            // the anchor" case. Either field alone is enough to trigger
            // this branch; a single-member arrangement only needs an
            // offset to place its member at a fixed distance.
            const offset = anchorOffsetPx != null ? anchorOffsetPx : 0;
            start = anchorAxisValue + offset;
            end = start + (spanPx != null ? spanPx : 0);
        } else if (members.length >= 2) {
            // Legacy: span members' current min..max range.
            start = members[0].position()[axisKey];
            end = members[members.length - 1].position()[axisKey];
        } else {
            // Single member with no explicit placement — nothing to distribute.
            return {warnings};
        }

        if (members.length === 1) {
            const pos = {...members[0].position()};
            pos[axisKey] = start;
            members[0].position(pos);
        } else {
            const gap = (end - start) / (members.length - 1);
            for (let i = 0; i < members.length; i++) {
                const pos = {...members[i].position()};
                pos[axisKey] = start + i * gap;
                members[i].position(pos);
            }
        }
    }

    return {warnings};
}

async function _executeGryphon(query, inputs) {
    const csrfToken = _getCsrfToken();
    const headers = {"Content-Type": "application/json"};
    if (csrfToken) headers["X-CSRFToken"] = csrfToken;

    const res = await fetch(GRYPHON_URL, {
        method: "POST",
        credentials: "same-origin",
        headers,
        body: JSON.stringify({query, inputs: inputs || {}, layer: "lite"}),
    });

    if (!res.ok) {
        const detail = await res.text();
        throw new Error(`Gryphon query failed (${res.status}): ${detail}`);
    }

    return await res.json();
}

function _getCsrfToken() {
    // base.html's meta tag, not the cookie: its name is per stack (tap#773).
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
}
