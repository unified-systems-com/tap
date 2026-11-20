// Behavioural checks for tap_viz/static/tap_viz/js/runtime/compound-edge.js (req-viz-compound-edge).
//
// Run by tap_viz/tests/test_compound_edge_runtime.py with a Node that can load the vendored cytoscape:
//   node compound_edge_runtime.mjs <path to cytoscape.min.js> <path to compound-edge.js>
// Prints one JSON line per check: {"check": ..., "ok": true|false, "detail": ...}. Cytoscape runs headless with
// styles on, so `visible()` reads the same hidden-class rule the graph panel's stylesheet carries.
import {createRequire} from "module";
import {pathToFileURL} from "url";

const [, , cytoscapePath, modulePath] = process.argv;
const cytoscape = createRequire(import.meta.url)(cytoscapePath);
const {applyCompoundEdges, COMPOUND_COLLAPSED_CLASS} = await import(pathToFileURL(modulePath).href);

const ROLES = {
    source: "REACHABILITY_SOURCE__p",
    destination: "REACHABILITY_DESTINATION__p",
    path: "TRAVERSES_COMPONENT__p",
};

function scene() {
    return cytoscape({
        headless: true,
        styleEnabled: true,
        elements: [
            {data: {id: "igw", label: "gateway", entity_type: "p__gateway"}},
            {data: {id: "eni", label: "interface", entity_type: "p__interface"}},
            {data: {id: "sg", label: "group", entity_type: "p__group"}},
            {data: {id: "vm", label: "instance", entity_type: "p__instance"}},
            {data: {id: "f1", label: "tcp 22 open", entity_type: "p__reachability", compound_edge: ROLES}},
            {data: {id: "e-src", source: "igw", target: "f1", label: ROLES.source}},
            {data: {id: "e-dst", source: "f1", target: "eni", label: ROLES.destination}},
            {data: {id: "e-path", source: "f1", target: "sg", label: ROLES.path}},
            {data: {id: "e-plain", source: "eni", target: "vm", label: "ATTACHED_TO_INSTANCE__p"}},
            // A second compound edge whose receiver is hidden (inside an icon node, or deferred by an elevation).
            {data: {id: "hidden-eni", label: "hidden", entity_type: "p__interface"}, classes: "tap-elevation-hidden"},
            {data: {id: "f2", label: "udp 53 open", entity_type: "p__reachability", compound_edge: ROLES}},
            {data: {id: "e2-src", source: "igw", target: "f2", label: ROLES.source}},
            {data: {id: "e2-dst", source: "f2", target: "hidden-eni", label: ROLES.destination}},
            // A middle node of another type, for the types filter.
            {data: {id: "flow", label: "flow", entity_type: "p__flow", compound_edge: {
                source: "FLOW_SOURCE__p", destination: "FLOW_DESTINATION__p"}}},
            {data: {id: "f-src", source: "vm", target: "flow", label: "FLOW_SOURCE__p"}},
            {data: {id: "f-dst", source: "flow", target: "igw", label: "FLOW_DESTINATION__p"}},
        ],
        style: [
            {selector: "node", style: {width: 40, height: 40}},
            {selector: ".tap-elevation-hidden, ." + COMPOUND_COLLAPSED_CLASS, style: {display: "none"}},
        ],
    });
}

const report = (check, ok, detail) => console.log(JSON.stringify({check, ok, detail}));
const arrows = (cy) => cy.edges("[?_is_compound_edge]");
// Read the computed display, not `visible()`: the latter's cache can lag a class change made in the same tick.
const hidden = (cy, id) => cy.getElementById(id).pstyle("display").value === "none";

// 1. Collapse: the middle node and its role edges go, one synthetic arrow from sender to receiver appears.
{
    const cy = scene();
    const handle = applyCompoundEdges(cy, {types: ["p__reachability"]});
    const ids = ["f1", "e-src", "e-dst", "e-path"];
    report("collapse-hides-middle-and-roles", ids.every((id) => hidden(cy, id)) && !hidden(cy, "e-plain"),
        ids.map((id) => `${id}:${hidden(cy, id) ? "hidden" : "shown"}`).join(" "));
    const a = arrows(cy);
    const one = a.length === 1 && a[0].source().id() === "igw" && a[0].target().id() === "eni";
    report("one-synthetic-arrow", one && a[0].data("_compound_id") === "f1" && a[0].data("label") === "tcp 22 open",
        `${a.length} arrow(s): ${a.map((e) => `${e.source().id()}>${e.target().id()} [${e.data("label")}]`).join(", ")}`);
    report("count-and-skipped", handle.count === 1 && handle.skipped.length === 1 && handle.skipped[0] === "f2",
        `count=${handle.count} skipped=${JSON.stringify(handle.skipped)}`);

    // 2. An end that is not drawn: no arrow is re-pointed, the middle node stays an ordinary node.
    const f2Arrows = a.filter((e) => e.data("_compound_id") === "f2");
    report("end-not-drawn-left-alone", f2Arrows.length === 0 && !hidden(cy, "f2") && !hidden(cy, "e2-src"),
        `f2 arrows=${f2Arrows.length} f2=${hidden(cy, "f2") ? "hidden" : "shown"}`);

    // 3. Tap the arrow: it expands into the stored pieces.
    a[0].emit("tap");
    report("expand-on-arrow-tap", arrows(cy).length === 0 && ["f1", "e-src", "e-dst", "e-path"].every((id) => !hidden(cy, id)),
        `arrows=${arrows(cy).length} f1=${hidden(cy, "f1") ? "hidden" : "shown"}`);

    // 4. Tap the expanded middle node: it collapses again.
    cy.getElementById("f1").emit("tap");
    report("collapse-on-middle-tap", arrows(cy).length === 1 && hidden(cy, "f1"),
        `arrows=${arrows(cy).length} f1=${hidden(cy, "f1") ? "hidden" : "shown"}`);

    // 5. Re-run: idempotent, one arrow per compound edge, never two.
    applyCompoundEdges(cy, {types: ["p__reachability"]});
    report("idempotent-rerun", arrows(cy).length === 1 && hidden(cy, "f1"), `arrows=${arrows(cy).length}`);

    // 6. The types filter: the flow middle node was not listed, so it is untouched.
    report("types-filter", !hidden(cy, "flow") && arrows(cy).filter((e) => e.data("_compound_id") === "flow").length === 0,
        `flow=${hidden(cy, "flow") ? "hidden" : "shown"}`);

    // 7. destroy restores everything the pass changed, and leaves classes it did not set alone.
    handle.destroy();
    applyCompoundEdges(cy, {types: ["p__reachability"]}).destroy();
    const leftovers = cy.elements("." + COMPOUND_COLLAPSED_CLASS).length;
    report("destroy-restores", arrows(cy).length === 0 && leftovers === 0 && !hidden(cy, "f1")
        && cy.getElementById("hidden-eni").hasClass("tap-elevation-hidden"),
        `arrows=${arrows(cy).length} collapsed=${leftovers}`);
}

// 8. No types given: every node carrying `compound_edge` is a candidate.
{
    const cy = scene();
    const handle = applyCompoundEdges(cy);
    const ids = arrows(cy).map((e) => e.data("_compound_id")).sort();
    report("all-middle-nodes-by-default", handle.count === 2 && JSON.stringify(ids) === JSON.stringify(["f1", "flow"]),
        `count=${handle.count} arrows for ${JSON.stringify(ids)}`);
}
process.exit(0);
