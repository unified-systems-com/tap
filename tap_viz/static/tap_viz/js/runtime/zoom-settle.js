/**
 * zoom-settle.js — "settle mode" for the zoom constant-scale policy (spec-viz-label-sizing,
 * req-viz-label-sizing-settle-*).
 *
 * While the viewer zooms nothing is written: the scene scales geometrically, which is free. When the zoom has been still
 * for `debounce_ms`, ONE rewrite sets font sizes, border widths, edge widths, arrow scales and icon-card sizes so that
 * they appear `base * zoom^a` on screen, clamped, for the zoom the viewer stopped at. Per-frame style writes cost 15-33 ms
 * of script at several hundred nodes and are not used.
 *
 * Writes are Cytoscape bypass styles (`ele.style(...)` inside `cy.batch`). The append form
 * `cy.style().selector().style().update()` is never used: it re-parses and re-applies the whole stylesheet.
 *
 * Each element's base is its own computed style value, read the first time the element is written and kept in the
 * element's scratch. Layout and measurement read the base: on `layoutstart` every written value is put back, and the
 * settle runs again after `layoutstop`, so panning, zooming and settling never perturb a layout.
 */

export const DEFAULT_DEBOUNCE_MS = 150;
export const DEFAULT_EXPONENT = 0.3;
const FAMILIES = ["font", "border", "edge", "arrow", "icon"];
// min_scale / max_scale are multiples of the element's own base size. The label band is 12-20 px around the 14 px
// `normal` tier (12/14, 20/14); the others are the measured 0.6-1.7 band.
const DEFAULT_BAND = {
    font: {min_scale: 0.85, max_scale: 1.45},
    border: {min_scale: 0.6, max_scale: 1.7},
    edge: {min_scale: 0.6, max_scale: 1.7},
    arrow: {min_scale: 0.6, max_scale: 1.7},
    icon: {min_scale: 0.6, max_scale: 1.7},
};
const EPSILON = 1 / 1024; // 2^-10: a binary fraction is exact (a decimal literal is not)
const SCRATCH = "_tapZoomSettle";

function _num(v) {
    return typeof v === "number" && Number.isFinite(v);
}

/**
 * Validate a raw `zoom_settle` panel config and fill the defaults. Returns the effective config, or null when the
 * feature is off (absent, `enabled` not true) or the config is malformed (warned, so a typo never breaks the graph).
 */
export function normalizeSettleConfig(raw) {
    if (!raw || typeof raw !== "object" || raw.enabled !== true) return null;
    const bad = (msg) => {
        console.warn("[TAP zoom-settle] ignored:", msg);
        return null;
    };
    const debounce = raw.debounce_ms === undefined ? DEFAULT_DEBOUNCE_MS : raw.debounce_ms;
    if (!_num(debounce) || debounce < 0 || debounce > 5000) return bad("debounce_ms must be a number from 0 to 5000");
    const exponent = raw.exponent === undefined ? DEFAULT_EXPONENT : raw.exponent;
    if (!_num(exponent) || exponent < 0 || exponent > 1) return bad("exponent must be a number from 0 to 1");
    const given = raw.classes === undefined ? {} : raw.classes;
    if (!given || typeof given !== "object") return bad("classes must be an object");
    const classes = {};
    for (const fam of FAMILIES) {
        const c = given[fam] === undefined ? {} : given[fam];
        if (!c || typeof c !== "object") return bad(`classes.${fam} must be an object`);
        const a = c.exponent === undefined ? exponent : c.exponent;
        const lo = c.min_scale === undefined ? DEFAULT_BAND[fam].min_scale : c.min_scale;
        const hi = c.max_scale === undefined ? DEFAULT_BAND[fam].max_scale : c.max_scale;
        if (!_num(a) || a < 0 || a > 1) return bad(`classes.${fam}.exponent must be a number from 0 to 1`);
        if (!_num(lo) || lo <= 0 || lo > 1) return bad(`classes.${fam}.min_scale must be greater than 0 and at most 1`);
        if (!_num(hi) || hi < 1 || hi > 10) return bad(`classes.${fam}.max_scale must be from 1 to 10`);
        classes[fam] = {exponent: a, min_scale: lo, max_scale: hi};
    }
    for (const key of Object.keys(given)) if (!FAMILIES.includes(key)) return bad(`unknown class ${key}`);
    return {debounce_ms: debounce, classes, texture_on_viewport: raw.texture_on_viewport === true};
}

/**
 * The factor to multiply an element's base (model units) by at `zoom`: the clamped on-screen size divided by the zoom,
 * `clamp(z^a, min, max) / z`. Exponent 1 gives 1 (geometric); exponent 0 gives constant on-screen size inside the band.
 */
export function modelFactor(zoom, cls) {
    const on = Math.min(cls.max_scale, Math.max(cls.min_scale, Math.pow(zoom, cls.exponent)));
    return on / zoom;
}

function _read(ele, prop) {
    const v = ele.numericStyle(prop);
    return Number.isFinite(v) ? v : null;
}

// The properties of one element: [family, cytoscape property, unit suffix].
function _props(ele) {
    if (ele.isEdge()) {
        const out = [["edge", "width", ""], ["arrow", "arrow-scale", ""]];
        // An edge whose label is empty draws no text, so its font is not worth a write.
        if (String(ele.style("label")) !== "") out.push(["font", "font-size", "px"]);
        return out;
    }
    const out = [["font", "font-size", "px"], ["border", "border-width", ""]];
    if (ele.data("_is_icon_node")) out.push(["icon", "width", ""], ["icon", "height", ""]);
    return out;
}

/**
 * Turn settle mode on for one Cytoscape instance.
 *
 * @param {cytoscape.Core} cy
 * @param {Object} rawConfig The panel's `zoom_settle` config (see normalizeSettleConfig). Not enabled → inert handle.
 * @param {Object} [hooks] Test seams: `hooks.later(fn)` replaces rAF/setTimeout-0 for the second batch,
 *                         `hooks.setTimeout` / `hooks.clearTimeout` replace the debounce timer.
 * @returns {{enabled: boolean, settle: Function, restore: Function, destroy: Function, config: Object|null}}
 */
export function initZoomSettle(cy, rawConfig, hooks = {}) {
    const config = normalizeSettleConfig(rawConfig);
    if (!config) return {enabled: false, config: null, settle() {}, restore() {}, destroy() {}};

    const setT = hooks.setTimeout || ((fn, ms) => setTimeout(fn, ms));
    const clearT = hooks.clearTimeout || ((id) => clearTimeout(id));
    const later = hooks.later || ((fn) => {
        if (typeof requestAnimationFrame === "function") requestAnimationFrame(() => setT(fn, 0));
        else setT(fn, 0);
    });

    let timer = null;
    let token = 0;
    let layoutRunning = false;
    let settledZoom = null;
    let alive = true;

    function _slot(ele) {
        let s = ele.scratch(SCRATCH);
        if (!s) {
            s = {};
            ele.scratch(SCRATCH, s);
        }
        return s;
    }

    // Write the policy values for `zoom` to `elements`. A prop is skipped when it already holds what we would write.
    function _write(elements, zoom) {
        elements.forEach((ele) => {
            const slot = _slot(ele);
            const out = {};
            for (const [fam, prop, unit] of _props(ele)) {
                const key = fam + ":" + prop;
                let rec = slot[key];
                const now = _read(ele, prop);
                if (now === null) continue;
                // Someone else (a layout module, an elevation) changed the value since we wrote it: it is the new base.
                if (!rec || Math.abs(now - rec.written) > EPSILON * Math.max(1, Math.abs(rec.written))) {
                    rec = {base: now, written: now};
                    slot[key] = rec;
                }
                if (rec.base <= 0) continue;
                const value = rec.base * modelFactor(zoom, config.classes[fam]);
                if (Math.abs(value - rec.written) <= EPSILON * Math.max(1, value)) continue;
                rec.written = value;
                out[prop] = unit ? value + unit : value;
            }
            if (Object.keys(out).length) {
                ele.style(out);
                // A bypass font-size write leaves the label's cached bounds at the old size, so the canvas clips the
                // larger text (measured on the playground landing graph). The bounds are re-derived on the next read.
                if (out["font-size"] !== undefined) ele.dirtyBoundingBoxCache();
            }
        });
    }

    function _viewport() {
        const ext = cy.extent();
        const m = 40 / cy.zoom();
        return {x1: ext.x1 - m, x2: ext.x2 + m, y1: ext.y1 - m, y2: ext.y2 + m};
    }

    function settle() {
        if (!alive || layoutRunning) return;
        timer = null;
        const my = ++token;
        const zoom = cy.zoom();
        if (!(zoom > 0)) return;
        const box = _viewport();
        const inView = (n) => {
            const p = n.position();
            return p.x >= box.x1 && p.x <= box.x2 && p.y >= box.y1 && p.y <= box.y2;
        };
        // Batch 1: the visible leaves, every compound parent, and the edges touching those.
        const first = new Set();
        const nodes1 = cy.nodes().filter((n) => n.isParent() || inView(n));
        nodes1.forEach((n) => first.add(n.id()));
        const edges1 = cy.edges().filter((e) => first.has(e.data("source")) || first.has(e.data("target")));
        cy.batch(() => {
            _write(nodes1, zoom);
            _write(edges1, zoom);
        });
        // Batch 2, a later task so the first can paint: everything else. A newer zoom supersedes it (token), because
        // the newer pass writes every element again.
        later(() => {
            if (!alive || my !== token) return;
            const nodes2 = cy.nodes().filter((n) => !first.has(n.id()));
            const edges2 = cy.edges().filter((e) => !first.has(e.data("source")) && !first.has(e.data("target")));
            cy.batch(() => {
                _write(nodes2, zoom);
                _write(edges2, zoom);
            });
            settledZoom = zoom;
            cy.emit("tapzoomsettled");
        });
    }

    function schedule() {
        if (!alive || layoutRunning) return;
        if (timer !== null) clearT(timer);
        timer = setT(settle, config.debounce_ms);
    }

    // Put every written value back to its base (the reference measurement) and forget nothing: the next settle
    // recognises the restored value as the base again.
    function restore() {
        token += 1;
        cy.batch(() => {
            cy.elements().forEach((ele) => {
                const slot = ele.scratch(SCRATCH);
                if (!slot) return;
                const out = {};
                for (const key of Object.keys(slot)) {
                    const prop = key.split(":")[1];
                    const rec = slot[key];
                    const unit = prop === "font-size" ? "px" : "";
                    if (rec.written !== rec.base) {
                        out[prop] = unit ? rec.base + unit : rec.base;
                        rec.written = rec.base;
                    }
                }
                if (Object.keys(out).length) {
                    ele.style(out);
                    if (out["font-size"] !== undefined) ele.dirtyBoundingBoxCache();
                }
            });
        });
        settledZoom = null;
    }

    const onZoom = () => {
        if (settledZoom !== null && Math.abs(cy.zoom() - settledZoom) < 1 / 1048576) return; // 2^-20, exact
        schedule();
    };
    const onLayoutStart = () => {
        layoutRunning = true;
        if (timer !== null) clearT(timer);
        timer = null;
        restore();
    };
    const onLayoutStop = () => {
        layoutRunning = false;
        schedule();
    };
    const onAdd = () => schedule();

    cy.on("zoom", onZoom);
    cy.on("layoutstart", onLayoutStart);
    cy.on("layoutstop", onLayoutStop);
    cy.on("add", onAdd);
    schedule();

    return {
        enabled: true,
        config,
        settle,
        restore,
        destroy() {
            alive = false;
            if (timer !== null) clearT(timer);
            timer = null;
            cy.off("zoom", onZoom);
            cy.off("layoutstart", onLayoutStart);
            cy.off("layoutstop", onLayoutStop);
            cy.off("add", onAdd);
            restore();
        },
    };
}
