// Behavioural checks for tap_viz/static/tap_viz/js/runtime/nested-projection.js: the per-container layout override
// (req-viz-nested-projection-container-size-from-children-5) and the `ranked` rows axis
// (req-viz-nested-projection-natural-layouts-8).
//
// Run by tap_viz/tests/test_nested_projection_runtime.py:
//   node nested_projection_runtime.mjs <path to cytoscape.min.js> <path to nested-projection.js>
// Prints one JSON line per check: {"check": ..., "ok": true|false, "detail": ...}. Cytoscape runs headless.
import {createRequire} from "module";
import {pathToFileURL} from "url";

const [, , cytoscapePath, modulePath] = process.argv;
const cytoscape = createRequire(import.meta.url)(cytoscapePath);
const {projectNested} = await import(pathToFileURL(modulePath).href);

const report = (check, ok, detail) => console.log(JSON.stringify({check, ok, detail}));
const near = (a, b, tol = 0.5) => Math.abs(a - b) <= tol;

const T = "t", H = "h";
const REL = [{name: "holds", gryphon: `(parent:${T})<-[:IN]-(child:${H})`}, {name: "holds-t", gryphon: `(parent:${T})<-[:IN]-(child:${T})`}];
const SIZES = {[T]: {width: 100, height: 60}, [H]: {width: 40, height: 40}};

// A leader (stage 0) and three child teams (stage 1) inside "top"; "leaf" is a team of the same type holding two people.
function scene(topData = {}) {
    const els = [
        {data: {id: "top", entity_type: T, label: "top", _stage: 0, ...topData}},
        {data: {id: "lead", entity_type: H, label: "lead", _stage: 0, _order: 0}},
        {data: {id: "leaf", entity_type: T, label: "leaf", _stage: 1, _order: 0}},
        {data: {id: "a", entity_type: H, label: "a", _stage: 0, _order: 0}},
        {data: {id: "b", entity_type: H, label: "b", _stage: 0, _order: 1}},
    ];
    ["x", "y", "z"].forEach((id) => els.push({data: {id, entity_type: T, label: id, _stage: 1, _order: 0}}));
    const edge = (s, t) => els.push({data: {id: `${s}-${t}`, source: s, target: t, edge_type: "IN", label: "IN"}});
    ["lead", "leaf", "x", "y", "z"].forEach((c) => edge(c, "top"));
    edge("a", "leaf"); edge("b", "leaf");
    return cytoscape({headless: true, styleEnabled: true, elements: els});
}
const pos = (cy, id) => cy.getElementById(id).position();
const cfg = (extra = {}) => ({
    relationships: REL, baseSizes: SIZES, padding: 10,
    innerLayout: {name: "ranked", sort: "order", columnGap: 20, rowGap: 30}, ...extra,
});

// 1. rows axis: leader alone, centred, above a row of three teams on one line.
{
    const cy = scene({_inner_layout: {name: "ranked", axis: "rows", sort: "label", columnGap: 20, rowGap: 30}});
    // The leaf is stage-ranked by the default (columns) layout: two people stacked? they share a stage, so one column.
    const res = await projectNested(cy, cfg());
    const lead = pos(cy, "lead"), top = pos(cy, "top"), ys = ["leaf", "x", "y", "z"].map((id) => pos(cy, id).y);
    report("rows-leader-above-row", lead.y < Math.min(...ys), JSON.stringify({lead, ys}));
    report("rows-leader-centred", near(lead.x, top.x), JSON.stringify({lead, top}));
    report("rows-children-share-a-line", ys.every((y) => near(y, ys[0])), JSON.stringify(ys));
    const xs = ["leaf", "x", "y", "z"].map((id) => pos(cy, id).x).sort((p, q) => p - q);
    report("rows-children-side-by-side", xs.every((x, i) => i === 0 || x - xs[i - 1] >= 100), JSON.stringify(xs));
    // block: 40 (leader) + 30 + 130 (the leaf holds two stacked people: 40+30+40+20) = 200 tall; 4*100 + 3*20 = 460 wide; plus padding 10 each side
    const top2 = cy.getElementById("top");
    report("rows-container-size", near(top2.style("width").replace("px", "") * 1, 480) && near(top2.style("height").replace("px", "") * 1, 220),
        `${top2.style("width")} x ${top2.style("height")}`);
    report("rows-no-warnings", res.warnings.length === 0, JSON.stringify(res.warnings));
}

// 2. override beats entity type: the leaf (same type) keeps the default column layout.
{
    const cy = scene({_inner_layout: {name: "ranked", axis: "rows", sort: "label", columnGap: 20, rowGap: 30}});
    await projectNested(cy, cfg());
    const a = pos(cy, "a"), b = pos(cy, "b");
    report("override-leaves-sibling-type-alone", near(a.x, b.x) && b.y > a.y, JSON.stringify({a, b}));
}

// 3. override as a plain name string, and precedence over innerLayouts[entity_type].
{
    const cy = scene({_inner_layout: "grid"});
    await projectNested(cy, cfg({innerLayouts: {[T]: {name: "ranked", axis: "rows", sort: "label"}}}));
    const ys = ["lead", "leaf", "x", "y", "z"].map((id) => pos(cy, id).y);
    report("override-beats-per-type", !ys.every((y) => near(y, ys[0])) && ys.length === 5, JSON.stringify(ys));
}

// 4. malformed override: ignored with a warning, not an exception.
{
    const cy = scene({_inner_layout: 42});
    const res = await projectNested(cy, cfg());
    report("malformed-override-warns", res.warnings.some((w) => w.category === "invalid_inner_layout"), JSON.stringify(res.warnings));
}

// 5. rtl mirrors vertically; re-entry is stable; an unranked child warns and trails.
{
    const rows = {name: "ranked", axis: "rows", sort: "label", columnGap: 20, rowGap: 30};
    const cy = scene({_inner_layout: rows});
    await projectNested(cy, cfg());
    const first = ["lead", "x", "y", "z"].map((id) => pos(cy, id));
    await projectNested(cy, cfg());
    const again = ["lead", "x", "y", "z"].map((id) => pos(cy, id));
    report("rows-reentry-stable", JSON.stringify(first) === JSON.stringify(again), JSON.stringify({first, again}));

    cy.getElementById("top").data("_inner_layout", {...rows, direction: "rtl"});
    await projectNested(cy, cfg());
    report("rows-rtl-leader-below", pos(cy, "lead").y > pos(cy, "x").y, JSON.stringify([pos(cy, "lead"), pos(cy, "x")]));

    cy.getElementById("top").data("_inner_layout", rows);
    cy.getElementById("x").removeData("_stage");
    const res = await projectNested(cy, cfg());
    report("rows-unranked-trails-with-warning",
        res.warnings.some((w) => w.category === "unranked_children") && pos(cy, "x").y > pos(cy, "y").y,
        JSON.stringify({w: res.warnings.map((w) => w.category), x: pos(cy, "x"), y: pos(cy, "y")}));
}

// 6. default axis unchanged: no override, columns as before (leader and teams side by side, centred vertically).
{
    const cy = scene();
    await projectNested(cy, cfg());
    report("default-columns-unchanged", pos(cy, "lead").x < pos(cy, "x").x && near(pos(cy, "lead").y, pos(cy, "top").y), JSON.stringify([pos(cy, "lead"), pos(cy, "x")]));
}
process.exit(0);
