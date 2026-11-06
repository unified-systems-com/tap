// Behavioural checks for tap_viz/static/tap_viz/js/runtime/zoom-settle.js (req-viz-label-sizing-settle).
//
// Run by tap_viz/tests/test_zoom_settle_runtime.py:
//   node zoom_settle_runtime.mjs <path to cytoscape.min.js> <path to zoom-settle.js>
// Prints one JSON line per check: {"check": ..., "ok": true|false, "detail": ...}. Cytoscape runs headless
// (styleEnabled, compound nodes). The debounce timer and the second-batch task are driven by hand through the
// module's test seams, so no check waits on a clock.
import {createRequire} from "module";
import {pathToFileURL} from "url";

const [, , cytoscapePath, modulePath] = process.argv;
const cytoscape = createRequire(import.meta.url)(cytoscapePath);
const {initZoomSettle, normalizeSettleConfig, modelFactor} = await import(pathToFileURL(modulePath).href);

const report = (check, ok, detail) => console.log(JSON.stringify({check, ok, detail}));
const near = (a, b, tol = 0.01) => Math.abs(a - b) <= tol;

function scene() {
    // Two compound parents, leaves spread far apart so a small viewport sees only some of them.
    const els = [{data: {id: "p", label: "p"}}, {data: {id: "q", label: "q"}}];
    for (let i = 0; i < 6; i++) els.push({data: {id: "n" + i, parent: i < 3 ? "p" : "q", label: "node " + i}, position: {x: i * 1000, y: 0}});
    els.push({data: {id: "icon", label: "ic", _is_icon_node: true}, position: {x: 0, y: 500}});
    els.push({data: {id: "e0", source: "n0", target: "n1", label: ""}});
    els.push({data: {id: "e5", source: "n4", target: "n5", label: ""}});
    const cy = cytoscape({
        headless: true, styleEnabled: true, elements: els, zoom: 1, pan: {x: 0, y: 0},
        style: [
            {selector: "node", style: {width: 40, height: 40, "font-size": 14, "border-width": 2, label: "data(label)"}},
            {selector: "edge", style: {width: 2, "arrow-scale": 1}},
            {selector: "node[?_is_icon_node]", style: {width: 96, height: 96}},
        ],
    });
    // Positions given in the element JSON are dropped for children of a compound, so set them once it exists.
    for (let i = 0; i < 6; i++) cy.getElementById("n" + i).position({x: i * 1000, y: 0});
    cy.getElementById("icon").position({x: 0, y: 500});
    return cy;
}

// Drives the module by hand: timers are collected and fired explicitly.
function rig(cfg, cy = scene()) {
    const timers = [], tasks = [];
    const hooks = {
        setTimeout: (fn, ms) => { timers.push({fn, ms}); return timers.length - 1; },
        clearTimeout: (id) => { if (timers[id]) timers[id].fn = null; },
        later: (fn) => tasks.push(fn),
    };
    const handle = initZoomSettle(cy, cfg, hooks);
    const live = () => timers.filter((t) => t.fn);
    return {cy, handle, timers, tasks, live,
        fire() { const t = live().pop(); if (t) { const fn = t.fn; t.fn = null; fn(); } },
        runTasks() { while (tasks.length) tasks.shift()(); }};
}
const num = (cy, id, prop) => cy.getElementById(id).numericStyle(prop);

// 1. Off unless enabled; a malformed config is off too.
{
    const quiet = console.warn; console.warn = () => {};
    const a = normalizeSettleConfig(undefined), b = normalizeSettleConfig({}), c = normalizeSettleConfig({enabled: false});
    const d = normalizeSettleConfig({enabled: true, exponent: 3}), e = normalizeSettleConfig({enabled: true, classes: {font: {min_scale: 0}}});
    const f = normalizeSettleConfig({enabled: true, classes: {nope: {}}});
    console.warn = quiet;
    report("off-unless-enabled", a === null && b === null && c === null, "absent / empty / false are off");
    report("malformed-is-off", d === null && e === null && f === null, "exponent 3, min_scale 0, unknown class are off");
    const cy = scene();
    const r = rig(undefined, cy);
    report("inert-handle", r.handle.enabled === false && r.live().length === 0, "no timer, no listener");
}

// 2. Defaults and the formula.
{
    const cfg = normalizeSettleConfig({enabled: true});
    report("defaults", cfg.debounce_ms === 150 && near(cfg.classes.font.exponent, 0.3) && near(cfg.classes.font.min_scale, 0.85)
        && near(cfg.classes.border.max_scale, 1.7) && cfg.texture_on_viewport === false, JSON.stringify(cfg));
    const geo = {exponent: 1, min_scale: 0.1, max_scale: 10};
    report("formula-geometric", near(modelFactor(2, geo), 1) && near(modelFactor(0.5, geo), 1), "exponent 1 leaves the style alone");
    const flat = {exponent: 0, min_scale: 0.5, max_scale: 2};
    report("formula-constant", near(modelFactor(2, flat) * 2, 1) && near(modelFactor(0.8, flat) * 0.8, 1), "exponent 0: on-screen factor 1");
    report("clamp-band", near(modelFactor(4, {exponent: 1, min_scale: 0.5, max_scale: 2}) * 4, 2) && near(modelFactor(0.1, {exponent: 1, min_scale: 0.5, max_scale: 2}) * 0.1, 0.5),
        "on-screen factor is held in [min_scale, max_scale]");
}

// 3. Nothing is written during zoom; the debounce restarts on every zoom; one settle at the end.
{
    const r = rig({enabled: true, exponent: 0.5, debounce_ms: 150});
    r.fire();           // the load-time settle at zoom 1: factor 1 is inside the band, nothing to write
    r.runTasks();
    const before = num(r.cy, "n0", "font-size");
    r.cy.zoom(2);
    r.cy.zoom(3);
    r.cy.zoom(4);
    const written = num(r.cy, "n0", "font-size");
    report("no-writes-during-zoom", written === before && r.live().length === 1, `font ${before} -> ${written} with ${r.live().length} timer`);
    report("debounce-ms", r.live()[0].ms === 150, `timer ${r.live()[0].ms} ms`);
    r.fire(); r.runTasks();
    report("settle-writes-final-zoom", near(num(r.cy, "n0", "font-size") * 4, 14 * 1.45, 0.05) , `on-screen ${num(r.cy, "n0", "font-size") * 4}px at z=4 (ceiling 20.3)`);
}

// 4. Constant on screen inside the band, for font, border, edge, arrow, icon.
{
    const r = rig({enabled: true, exponent: 0, classes: {font: {min_scale: 0.5, max_scale: 2}}});
    r.fire(); r.runTasks();
    const seen = {};
    for (const z of [0.8, 1.25]) {
        r.cy.zoom(z); r.fire(); r.runTasks();
        seen[z] = {font: num(r.cy, "n0", "font-size") * z, border: num(r.cy, "n0", "border-width") * z,
            edge: num(r.cy, "e0", "width") * z, arrow: num(r.cy, "e0", "arrow-scale") * z, icon: num(r.cy, "icon", "width") * z};
    }
    const same = Object.keys(seen[0.8]).every((k) => near(seen[0.8][k], seen[1.25][k], 0.02));
    report("constant-on-screen", same, JSON.stringify(seen));
    report("icon-card-resized", near(num(r.cy, "icon", "width"), 96 / 1.25, 0.05) && num(r.cy, "icon", "height") === num(r.cy, "icon", "width"),
        `icon card ${num(r.cy, "icon", "width")} model units at z=1.25`);
    const plain = num(r.cy, "n0", "width");
    report("plain-node-size-unchanged", plain === 40, `width ${plain}`);
}

// 5. Two batches: visible + parents + their edges first, the rest in a later task.
{
    const r = rig({enabled: true, exponent: 0, classes: {font: {min_scale: 0.1, max_scale: 10}}});
    r.fire(); r.runTasks();
    r.cy.viewport({zoom: 2, pan: {x: 0, y: 0}});   // sees x in [0, ~model width/2]: only n0 (and the icon) are in view in a headless 0x0 box
    r.cy.resize();
    r.fire();
    const first = {n0: num(r.cy, "n0", "font-size"), n5: num(r.cy, "n5", "font-size"), p: num(r.cy, "p", "font-size"), q: num(r.cy, "q", "font-size")};
    const queued = r.tasks.length;
    r.runTasks();
    const second = {n5: num(r.cy, "n5", "font-size")};
    report("batch-1-parents-and-visible", near(first.p, 7) && near(first.q, 7) && near(first.n0, 7) , JSON.stringify(first));
    report("batch-2-is-a-later-task", queued === 1 && near(first.n5, 14) && near(second.n5, 7), `queued ${queued}; far node ${first.n5} then ${second.n5}`);
}

// 6. A newer zoom supersedes an unfinished second batch.
{
    const r = rig({enabled: true, exponent: 0, classes: {font: {min_scale: 0.1, max_scale: 10}}});
    r.fire(); r.runTasks();
    r.cy.zoom(2); r.fire();                 // batch 1 at z=2, batch 2 queued
    r.cy.zoom(4); r.fire();                 // a newer settle starts
    r.runTasks();                           // both queued second batches run; only the newer may write
    report("stale-batch-dropped", near(num(r.cy, "n5", "font-size") * 4, 14, 0.05), `far node on screen ${num(r.cy, "n5", "font-size") * 4}px at z=4`);
}

// 7. Layout start restores the base (reference measurement); layout stop settles again; destroy restores.
{
    const r = rig({enabled: true, exponent: 0, classes: {font: {min_scale: 0.1, max_scale: 10}}});
    r.fire(); r.runTasks();
    r.cy.zoom(2); r.fire(); r.runTasks();
    const settled = num(r.cy, "n0", "font-size");
    r.cy.emit("layoutstart");
    const during = num(r.cy, "n0", "font-size");
    const timersDuring = r.live().length;
    r.cy.zoom(3);
    report("layout-start-restores-base", near(settled, 7) && during === 14 && timersDuring === 0 && r.live().length === 0,
        `settled ${settled}, during layout ${during}, timers ${r.live().length}`);
    r.cy.emit("layoutstop");
    r.fire(); r.runTasks();
    report("layout-stop-settles", near(num(r.cy, "n0", "font-size") * 3, 14, 0.05), `on screen ${num(r.cy, "n0", "font-size") * 3}px at z=3`);
    r.handle.destroy();
    report("destroy-restores", num(r.cy, "n0", "font-size") === 14 && r.live().length === 0, `font ${num(r.cy, "n0", "font-size")}`);
    r.cy.zoom(5);
    report("destroy-detaches", r.live().length === 0, "no timer after destroy");
}

// 8. A value another writer changed after ours becomes the new base; the stylesheet is never re-applied.
{
    const r = rig({enabled: true, exponent: 0, classes: {font: {min_scale: 0.1, max_scale: 10}}});
    r.fire(); r.runTasks();
    r.cy.zoom(2); r.fire(); r.runTasks();
    r.cy.getElementById("n0").style({"font-size": "20px"});      // e.g. a layout module sets a larger interior font
    r.cy.zoom(4); r.fire(); r.runTasks();
    report("foreign-write-rebased", near(num(r.cy, "n0", "font-size") * 4, 20, 0.05), `on screen ${num(r.cy, "n0", "font-size") * 4}px, base 20`);
    let reapplied = false;
    const style = r.cy.style();
    const orig = style.update;
    style.update = function (...a) { reapplied = true; return orig.apply(this, a); };
    r.cy.zoom(1.5); r.fire(); r.runTasks();
    style.update = orig;
    report("stylesheet-not-reapplied", reapplied === false, "cy.style().update() not called by a settle");
}

// 9. Edges: label-less edges get no font write; edges touching only far nodes are second-batch.
{
    const r = rig({enabled: true, exponent: 0, classes: {edge: {min_scale: 0.1, max_scale: 10}}});
    r.fire(); r.runTasks();
    r.cy.zoom(2); r.fire(); r.runTasks();
    report("edge-width-settled", near(num(r.cy, "e0", "width") * 2, 2, 0.05), `edge on screen ${num(r.cy, "e0", "width") * 2}px`);
}
process.exit(0);
