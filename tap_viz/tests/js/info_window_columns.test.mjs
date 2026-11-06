// info_window.columns rendering (req-viz-info-window-columns-3..8). Run with `node --test`; the
// Python wrapper tap_viz/tests/test_info_window_columns.py::test_js_rendering runs it when node exists.
// renderInfoTable is pure string-in/string-out, so no DOM is needed.
import assert from "node:assert/strict";
import {test} from "node:test";
import {renderInfoTable} from "../../static/tap_viz/js/runtime/info-window.js";

const rows = [
    {entity_id: "h", name: "n1", id: "CVE-1", cvss: 9, title: "First <b>bad</b>", finding_id: "f1"},
    {entity_id: "h", name: "n2", id: "CVE-2", cvss: "7.25", title: null, finding_id: "f2"},
    {entity_id: "h", name: "n3", id: "CVE-3"},
];
const cols = [
    {field: "id", label: "ID", link: true},
    {field: "cvss", label: "CVSS", align: "right", format: "number"},
    {field: "title", label: "Title"},
];
const tds = (html) => [...html.split("<tbody>")[1].matchAll(/<tr>(.*?)<\/tr>/gs)].map((m) => [...m[1].matchAll(/<td[^>]*>(.*?)<\/td>/gs)].map((c) => c[1]));

test("absent columns is the legacy single Name column, header hidden by CSS", () => {
    const html = renderInfoTable(rows, {search_id: "s"});
    assert.match(html, /<thead><tr><th>Name<\/th><\/tr><\/thead>/);
    assert.doesNotMatch(html, /table--columns/);
    assert.equal((html.match(/<td>/g) || []).length, 3);
});

test("legacy path still honours row_url_template and the finding_id fallback", () => {
    const withTpl = renderInfoTable(rows, {row_url_template: "/x?i={finding_id}"});
    assert.match(withTpl, /href="\/x\?i=f1"/);
    assert.match(withTpl, /<td>n3<\/td>/); // row 3 has no finding_id -> plain text
    assert.match(renderInfoTable(rows, {}), /href="[^"]*entity_id=f1"/);
});

test("empty columns array falls back to legacy", () => {
    assert.doesNotMatch(renderInfoTable(rows, {columns: []}), /table--columns/);
});

test("header row shows every label in order", () => {
    const html = renderInfoTable(rows, {columns: cols});
    assert.match(html, /table--columns/);
    assert.match(html, /<thead><tr><th scope="col">ID<\/th><th scope="col" class="tap-info-window__cell--right">CVSS<\/th><th scope="col">Title<\/th><\/tr><\/thead>/);
    assert.equal(tds(html).length, 3);
});

test("missing, null and empty values are empty cells, never undefined", () => {
    const html = renderInfoTable(rows, {columns: cols});
    assert.doesNotMatch(html, /undefined|null/);
    assert.deepEqual(tds(html)[2], ["CVE-3", "", ""]);
    assert.equal(tds(html)[1][2], "");
    assert.equal(tds(renderInfoTable([{id: ""}], {columns: cols}))[0].join("|"), "||");
});

test("number format gives one decimal place and leaves non-numbers as given", () => {
    const t = tds(renderInfoTable(rows, {columns: cols}));
    assert.equal(t[0][1], "9.0");
    assert.equal(t[1][1], "7.3");
    assert.equal(tds(renderInfoTable([{cvss: "n/a"}], {columns: cols}))[0][1], "n/a");
    assert.equal(tds(renderInfoTable([{cvss: 0}], {columns: cols}))[0][1], "0.0");
    // text format does not round
    assert.equal(tds(renderInfoTable([{cvss: 9.25}], {columns: [{field: "cvss", label: "C"}]}))[0][0], "9.25");
});

test("cell text and labels are escaped", () => {
    const html = renderInfoTable(rows, {columns: [{field: "title", label: "<i>T</i>"}]});
    assert.match(html, /First &lt;b&gt;bad&lt;\/b&gt;/);
    assert.match(html, /&lt;i&gt;T&lt;\/i&gt;/);
    assert.doesNotMatch(html, /<b>|<i>/);
});

test("link goes on the link:true column when the template resolves, else nowhere", () => {
    const cfg = {columns: [{field: "title", label: "T"}, {field: "id", label: "ID", link: true}], row_url_template: "/p?f={finding_id}"};
    const t = tds(renderInfoTable(rows, cfg));
    assert.match(t[0][1], /^<a class="tap-info-window__row-link" href="\/p\?f=f1">CVE-1<\/a>$/);
    assert.doesNotMatch(t[0][0], /<a /);
    assert.doesNotMatch(t[2].join(""), /<a /); // row 3 lacks finding_id: all-or-nothing
});

test("link defaults to the first column and needs a template (no finding_id fallback)", () => {
    const withTpl = tds(renderInfoTable(rows, {columns: cols, row_url_template: "/p?f={finding_id}"}));
    assert.match(withTpl[0][0], /<a [^>]*href="\/p\?f=f1">CVE-1<\/a>/);
    const noTpl = renderInfoTable(rows, {columns: cols});
    assert.doesNotMatch(noTpl, /<a /);
});

test("template values are URL-encoded and the href is escaped", () => {
    const html = renderInfoTable([{id: "x", finding_id: 'a b"&<'}], {columns: [{field: "id", label: "ID"}], row_url_template: "/p?f={finding_id}"});
    assert.match(html, /href="\/p\?f=a%20b%22%26%3C"/);
});

test("nowrap: true puts the nowrap class on that column's body cells only (columns-12)", () => {
    const nw = [{field: "id", label: "ID", link: true, nowrap: true}, {field: "cvss", label: "CVSS", align: "right", nowrap: true}, {field: "title", label: "Title"}];
    const html = renderInfoTable(rows, {columns: nw});
    const body = html.split("<tbody>")[1];
    assert.equal((body.match(/<td class="tap-info-window__cell--nowrap">/g) || []).length, 3);
    assert.equal((body.match(/<td class="tap-info-window__cell--right tap-info-window__cell--nowrap">/g) || []).length, 3);
    assert.equal((body.match(/<td>/g) || []).length, 3); // the Title column is untouched
    assert.doesNotMatch(html.split("<tbody>")[0], /nowrap/); // headers keep wrapping
    assert.doesNotMatch(html, /style=/);
});

test("nowrap absent or false leaves the output identical to before (columns-12)", () => {
    const plain = renderInfoTable(rows, {columns: cols});
    const falsy = renderInfoTable(rows, {columns: cols.map((c) => ({...c, nowrap: false}))});
    assert.equal(falsy, plain);
    assert.doesNotMatch(plain, /nowrap/);
});

test("percent format shows a 0..1 fraction as a percentage with decimals places", () => {
    const col = (extra) => [{field: "p", label: "P", format: "percent", ...extra}];
    const cell = (v, extra) => tds(renderInfoTable([{p: v}], {columns: col(extra)}))[0][0];
    assert.equal(cell(0.0004), "0.04%");
    assert.equal(cell(0.5), "50.00%");
    assert.equal(cell(0.12345, {decimals: 1}), "12.3%");
    assert.equal(cell(1, {decimals: 0}), "100%");
    assert.equal(cell(0), "0.00%");
    assert.equal(cell("0.25", {decimals: 0}), "25%");
    // not a fraction: shown as given, never hidden
    assert.equal(cell(1.5), "1.5");
    assert.equal(cell("n/a"), "n/a");
    assert.equal(cell(null), "");
});

test("tone_steps draws a numeric cell as a toned badge, highest min first", () => {
    const steps = [{min: 0.0001, tone: "info"}, {min: 7, tone: "bad"}, {min: 4, tone: "warn"}]; // order must not matter
    const cols = [{field: "c", label: "CVSS", format: "number", tone_steps: steps, zero_tone: "muted"}];
    const cell = (v) => tds(renderInfoTable([{c: v}], {columns: cols}))[0][0];
    assert.equal(cell(9.8), '<span class="tap-info-window__tone tap-info-window__tone--bad" title="bad">9.8</span>');
    assert.match(cell(7), /tone--bad/);
    assert.match(cell(5.5), /tone--warn/);
    assert.match(cell(4), /tone--warn/);
    assert.match(cell(0.5), /tone--info/);
    assert.match(cell(0), /tone--muted/);
    // below every step, negative or not a number: plain text
    assert.equal(cell(-1), "-1.0");
    assert.equal(cell("n/a"), "n/a");
    assert.equal(cell(null), "");
    assert.equal(cell(""), "");
});

test("a toned cell keeps the row link inside the badge", () => {
    const cols = [{field: "c", label: "C", link: true, tone_steps: [{min: 0, tone: "good"}]}];
    const html = renderInfoTable([{c: 3, finding_id: "f1"}], {columns: cols, row_url_template: "/x?i={finding_id}"});
    assert.match(tds(html)[0][0], /^<span class="tap-info-window__tone tap-info-window__tone--good" title="good"><a class="tap-info-window__row-link" href="\/x\?i=f1">3<\/a><\/span>$/);
});
