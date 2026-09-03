/**
 * chrome.js — the ONE place a projection's label sizing and container
 * chrome live, so every layout module reads as the same product instead of
 * re-deriving font sizes and label anchors per scene (derive-a-fact-once).
 *
 * Two exports:
 *
 *   applyStandardChrome(cy, opts)  — the org-view conventions (git-serious
 *     org.js, 2026-09-02): 14px node labels, 15px/600 container labels,
 *     leaf labels centred and ellipsised at a max width, edge-type labels
 *     off, edges drawn above the compound boxes. Call BEFORE projectNested.
 *
 *   placeParentLabels(cy, opts)    — anchor every `.tap-viewport-parent`
 *     label in the box's upper-left (or another corner) by computing the
 *     Cytoscape text-margin offsets from the box's resolved size and the
 *     measured label width. Cytoscape has no "inside top-left" anchor, only
 *     margins from the centre, so this runs AFTER projectNested has sized
 *     the boxes; pair it with a per-side `paddings: {top}` on the container
 *     so the first row of children starts below the label.
 *
 * Spec: spec-viz-nested-projection.md § Container Visual Switch
 * (req-viz-nested-projection-container-visual-3/-4).
 */

import {VIEWPORT_PARENT_CLASS} from "./nested-projection.js";

const DEFAULTS = {
    nodeFontSize: 14,
    parentFontSize: 15,
    parentFontWeight: 600,
    leafTypes: [],          // entity types whose labels are centred + ellipsised
    leafMaxWidth: 170,
    leafFontSize: null,     // defaults to nodeFontSize
    edgeLabels: false,
};

/**
 * Apply the standard chrome. Returns the effective options so a caller can
 * derive matching sizes (e.g. the top padding for placeParentLabels).
 */
export function applyStandardChrome(cy, opts = {}) {
    const o = {...DEFAULTS, ...opts};
    const leafFont = o.leafFontSize || o.nodeFontSize;
    let style = cy.style()
        .selector("edge")
        .style({"z-compound-depth": "top", "z-index": 1, ...(o.edgeLabels ? {} : {label: ""})})
        .selector("node")
        .style({"font-size": `${o.nodeFontSize}px`})
        .selector("." + VIEWPORT_PARENT_CLASS)
        .style({"font-size": `${o.parentFontSize}px`, "font-weight": String(o.parentFontWeight)});
    if (o.leafTypes.length > 0) {
        const sel = o.leafTypes.map((t) => `node[entity_type = "${t}"]`).join(", ");
        style = style.selector(sel).style({
            "font-size": `${leafFont}px`, "text-wrap": "ellipsis", "text-max-width": `${o.leafMaxWidth}px`,
            "text-valign": "center", "text-halign": "center",
        });
    }
    style.update();
    return o;
}

/**
 * Height a container must reserve above its children for an anchored label.
 */
export function parentLabelInset(opts = {}) {
    const o = {...DEFAULTS, ...opts};
    const inset = opts.inset != null ? opts.inset : 8;
    return Math.round(o.parentFontSize * 1.3) + inset * 2;
}

/**
 * Anchor container labels in a corner, inside the box.
 *
 * @param {cytoscape.Core} cy
 * @param {Object} [opts]
 * @param {string} [opts.anchor="upper-left"]  "upper-left" | "upper-right" | "top-center"
 * @param {number} [opts.inset=8]              distance from the box edges
 * @param {number} [opts.parentFontSize=15]
 */
export function placeParentLabels(cy, opts = {}) {
    const anchor = opts.anchor || "upper-left";
    const inset = opts.inset != null ? opts.inset : 8;
    const fontSize = opts.parentFontSize || DEFAULTS.parentFontSize;
    const weight = opts.parentFontWeight || DEFAULTS.parentFontWeight;
    const measure = _textMeasurer(`${weight} ${fontSize}px sans-serif`);

    cy.batch(() => {
        cy.nodes("." + VIEWPORT_PARENT_CLASS).forEach((n) => {
            const w = n.width();
            const h = n.height();
            const textW = measure(n.data("label") || "");
            const labelW = Math.min(textW, Math.max(0, w - 2 * inset));
            // Margins are offsets from the node centre; a centred label's box
            // is textW wide and ~fontSize tall.
            const my = -(h / 2) + inset + fontSize * 0.65;
            let mx = 0;
            if (anchor === "upper-left") mx = -(w / 2) + inset + labelW / 2;
            else if (anchor === "upper-right") mx = (w / 2) - inset - labelW / 2;
            n.style({
                "text-valign": "center", "text-halign": "center",
                "text-margin-x": mx, "text-margin-y": my,
                "text-wrap": "ellipsis", "text-max-width": `${Math.max(20, w - 2 * inset)}px`,
            });
        });
    });
}

function _textMeasurer(font) {
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");
    if (!ctx) return (text) => text.length * 7;
    ctx.font = font;
    return (text) => ctx.measureText(text).width;
}
