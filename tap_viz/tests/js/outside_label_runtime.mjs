// Behavioural check for runtime/chrome.js placeParentLabels with an outside label hint
// (req-viz-system-display-hints-10). Run by tap_viz/tests/test_scope_box_runtime.py:
//   node outside_label_runtime.mjs <path to cytoscape.min.js> <path to chrome.js>
// Prints one JSON line per check. Text is measured by a fake canvas at 7px per character.
import {createRequire} from "module";
import {pathToFileURL} from "url";

const [, , cytoscapePath, modulePath] = process.argv;
const cytoscape = createRequire(import.meta.url)(cytoscapePath);
globalThis.document = {
    createElement: () => ({getContext: () => ({font: "", measureText: (t) => ({width: t.length * 7})})}),
};
const {placeParentLabels} = await import(pathToFileURL(modulePath).href);

const report = (check, ok, detail) => console.log(JSON.stringify({check, ok, detail}));

function scene(boundaryData) {
    // The container is a plain node of the container's size carrying the viewport-parent class: placeParentLabels
    // reads only the class, the node's size and its font, and headless cytoscape does not size compounds.
    return cytoscape({
        headless: true, styleEnabled: true,
        elements: [{data: {id: "box", label: "Authorization Boundary", ...boundaryData}, classes: "tap-viewport-parent"}],
        style: [{selector: "node", style: {width: 440, height: 120, "font-size": 15, "font-weight": 600}}],
    });
}
const margin = (cy, prop) => Number(String(cy.getElementById("box").style(prop)).replace("px", ""));

// An outside top-left label: standing above the box (valign top, the hint's own margin), left end on the left edge.
{
    const cy = scene({label_position: "outside", label_anchor: "left", label_valign: "top", label_halign: "center", label_margin_y: -6});
    placeParentLabels(cy);
    const box = cy.getElementById("box");
    const textW = "Authorization Boundary".length * 7;
    const expectX = -(box.width() - textW) / 2;
    report("outside-left-valign", box.style("text-valign") === "top", `text-valign=${box.style("text-valign")}`);
    report("outside-left-shift", Math.abs(margin(cy, "text-margin-x") - expectX) < 0.5, `x=${margin(cy, "text-margin-x")} want ${expectX}`);
    report("outside-left-above-edge", margin(cy, "text-margin-y") < 0, `y=${margin(cy, "text-margin-y")}`);
}
// right anchor mirrors it.
{
    const cy = scene({label_position: "outside", label_anchor: "right", label_valign: "top", label_halign: "center", label_margin_y: -6});
    placeParentLabels(cy);
    report("outside-right-shift", margin(cy, "text-margin-x") > 0, `x=${margin(cy, "text-margin-x")}`);
}
// centre anchor adds no shift.
{
    const cy = scene({label_position: "outside", label_anchor: "center", label_valign: "top", label_halign: "center", label_margin_y: -6});
    placeParentLabels(cy);
    report("outside-center-no-shift", margin(cy, "text-margin-x") === 0, `x=${margin(cy, "text-margin-x")}`);
}
// A node with no outside hint keeps the old inside upper-left placement (backward compatible).
{
    const cy = scene({});
    placeParentLabels(cy);
    const box = cy.getElementById("box");
    report("inside-unchanged", box.style("text-valign") === "center" && margin(cy, "text-margin-y") > -box.height() / 2 - 1
        && margin(cy, "text-margin-x") < 0, `valign=${box.style("text-valign")} x=${margin(cy, "text-margin-x")} y=${margin(cy, "text-margin-y")}`);
}
process.exit(0);
