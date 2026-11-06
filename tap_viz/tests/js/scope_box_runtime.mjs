// Behavioural checks for tap_viz/static/tap_viz/js/runtime/layout-scope-boxes.js (req-viz-layout-scope-box).
//
// Run by tap_viz/tests/test_scope_box_runtime.py with a Node that can load the vendored cytoscape:
//   node scope_box_runtime.mjs <path to cytoscape.min.js> <path to layout-scope-boxes.js>
// Prints one JSON line per check: {"check": ..., "ok": true|false, "detail": ...}. Cytoscape runs headless
// (styleEnabled, compound nodes); the DOM is the few calls the module makes, faked below.
import {createRequire} from "module";
import {pathToFileURL} from "url";

const [, , cytoscapePath, modulePath] = process.argv;
const cytoscape = createRequire(import.meta.url)(cytoscapePath);

function fakeElement(tag) {
    const el = {
        tag, style: {}, children: [], className: "", parentNode: null, textContent: "",
        appendChild(child) { child.parentNode = el; el.children.push(child); return child; },
        removeChild(child) { el.children = el.children.filter((c) => c !== child); },
        querySelector() { return {parentNode: el}; },
    };
    return el;
}
globalThis.document = {createElement: fakeElement};
const {applyScopeBoxes} = await import(pathToFileURL(modulePath).href);

function scene() {
    const container = fakeElement("div");
    const cy = cytoscape({
        headless: true, styleEnabled: true,
        elements: [
            {data: {id: "account"}},
            {data: {id: "a", parent: "account"}, position: {x: 0, y: 0}},
            {data: {id: "b", parent: "account"}, position: {x: 120, y: 0}},
        ],
        style: [{selector: "node", style: {width: 40, height: 40}}],
    });
    cy.container = () => container;
    return {cy, container};
}

const members = (ids) => (n) => ids.includes(n.id());
const report = (check, ok, detail) => console.log(JSON.stringify({check, ok, detail}));

// 1. A member read that emits `bounds` on the member again (tap#289) must not overflow the stack.
{
    const {cy} = scene();
    const proto = Object.getPrototypeOf(cy.nodes());
    const original = proto.boundingBox;
    let reads = 0;
    proto.boundingBox = function (...args) { reads += 1; this.emit("bounds"); return original.apply(this, args); };
    try {
        applyScopeBoxes(cy, [{label: "Row", filter: members(["a", "b"])}]);
        cy.getElementById("a").position({x: 5, y: 5});
        report("reentrant-bounds", true, `${reads} member reads`);
    } catch (e) {
        report("reentrant-bounds", false, `${e.constructor.name}: ${String(e.message).slice(0, 80)}`);
    }
    proto.boundingBox = original;
}

// 2. A hidden container is neither measured nor drawn; the first render after it is shown draws the box.
{
    const {cy, container} = scene();
    const proto = Object.getPrototypeOf(cy.nodes());
    const original = proto.boundingBox;
    let reads = 0;
    proto.boundingBox = function (...args) { reads += 1; return original.apply(this, args); };
    container.style.visibility = "hidden";
    const handle = applyScopeBoxes(cy, [{label: "Row", filter: members(["a", "b"]), style: {padding: 10}}]);
    const box = container.children[0].children[0];
    report("hidden-not-measured", reads === 0, `${reads} reads while hidden`);
    report("hidden-not-drawn", box.style.display === "none", `display=${box.style.display}`);
    cy.getElementById("a").position({x: 3, y: 3});
    report("hidden-move-still-not-measured", reads === 0, `${reads} reads after a move`);
    container.style.visibility = "";
    cy.emit("render");
    report("shown-draws-on-render", reads > 0 && box.style.display === "" && /px$/.test(box.style.width || ""),
        `reads=${reads} display=${JSON.stringify(box.style.display)} width=${box.style.width}`);
    handle.destroy();
    proto.boundingBox = original;
}

// 3. display:none on the container counts as hidden too.
{
    const {cy, container} = scene();
    container.style.display = "none";
    applyScopeBoxes(cy, [{label: "Row", filter: members(["a"])}]);
    const box = container.children[0].children[0];
    report("display-none-not-drawn", box.style.display === "none", `display=${box.style.display}`);
}
process.exit(0);
