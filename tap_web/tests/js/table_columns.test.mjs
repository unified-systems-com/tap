// Table panel column options: field_path (req-web-stdpanel-table-config-22) and empty_text (-23).
// Run with `node --test`; tap_web/tests/test_table_panel.py::test_js_columns runs it when node exists.
// panel-table.js is a browser IIFE: it is loaded into a vm context with stub globals and the test seam
// (window.__TAP_TABLE_TEST__) hands back the pure column builders. No Tabulator or DOM is needed.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import vm from "node:vm";

const src = readFileSync(new URL("../../static/tap_web/js/panel-table.js", import.meta.url), "utf8");
const seam = {};
const window = {__TAP_TABLE_TEST__: seam, location: {href: "http://x/", origin: "http://x", pathname: "/"}};
const document = {readyState: "complete", addEventListener() {}, querySelectorAll: () => [], documentElement: {}};
vm.runInNewContext(src, {window, document, history: {}, sessionStorage: {}, console, URL});
const {buildCustomColumns, resolveFieldPaths} = seam;

const cellOf = (value) => ({getValue: () => value});
const TEXT = (escaped) => `<span class="tap-cell-text">${escaped}</span>`;
const render = (spec, value) => buildCustomColumns([spec])[0].formatter(cellOf(value), {}, () => {});

test("the seam exposes the builders", () => {
    assert.equal(typeof buildCustomColumns, "function");
    assert.equal(typeof resolveFieldPaths, "function");
});

test("field_path reaches a key that itself contains a dot", () => {
    const rows = [
        {dimensions: {"dataclass.customer": "high", dataclass: {customer: "WRONG"}}},
        {dimensions: {}},
        {dimensions: null},
        {},
    ];
    const specs = resolveFieldPaths([{field_path: ["dimensions", "dataclass.customer"], title: "T"}], rows);
    const key = specs[0].field;
    assert.ok(key && !key.includes("."), "the synthetic key is dot-free so Tabulator reads it flat");
    assert.deepEqual(rows.map((r) => r[key]), ["high", undefined, undefined, undefined]);
    assert.equal(buildCustomColumns(specs)[0].field, key);
});

test("field_path columns in a group get distinct keys, and plain field columns are untouched", () => {
    const rows = [{a: {"b.c": 1, d: 2}, plain: 3}];
    const specs = resolveFieldPaths(
        [{field: "plain", title: "P"}, {title: "G", columns: [{field_path: ["a", "b.c"], title: "X"}, {field_path: ["a", "d"], title: "Y"}]}],
        rows,
    );
    assert.equal(specs[0].field, "plain");
    const [x, y] = specs[1].columns;
    assert.notEqual(x.field, y.field);
    assert.deepEqual([rows[0][x.field], rows[0][y.field]], [1, 2]);
});

test("a dotted field still resolves as before (no field_path means no change)", () => {
    const specs = [{field: "dimensions.dataclass.customer", title: "T"}];
    assert.deepEqual(resolveFieldPaths(specs, [{}]), specs);
});

test("empty_text replaces a null, missing or empty value for the default formatter, escaped", () => {
    const spec = {field: "f", title: "T", empty_text: "<n/a> & co"};
    for (const v of [null, undefined, ""]) assert.equal(render(spec, v), "&lt;n/a&gt; &amp; co");
    assert.equal(render(spec, "<b>x</b>"), TEXT("&lt;b&gt;x&lt;/b&gt;"), "a real value is still escaped plain text");
    assert.equal(render(spec, 0), TEXT("0"), "zero is a value");
    assert.equal(render(spec, false), TEXT("false"), "false is a value");
});

test("empty_text applies with every declared formatter, never leaving a blank", () => {
    const names = ["toneBadge", "toneThreshold", "percent", "link", "externalLink", "datetime", "capitalized", "json", "tickCross", "arrayCount", "linkList", "ciaLevel", "ellipsisSuffix"];
    for (const formatter of names) {
        for (const v of [null, undefined, ""]) {
            assert.equal(render({field: "f", title: "T", formatter, empty_text: "none yet"}, v), "none yet", `${formatter} ${v}`);
        }
    }
});

test("without empty_text the column is exactly as before", () => {
    const col = buildCustomColumns([{field: "f", title: "T"}])[0];
    assert.equal(col.formatter(cellOf(null)), "");
    const tone = buildCustomColumns([{field: "f", title: "T", formatter: "percent"}])[0];
    assert.notEqual(tone.formatter(cellOf(0.5), {}, () => {}), "none yet");
});

test("empty_text and a non-empty value hand over to the column formatter", () => {
    const out = render({field: "f", title: "T", formatter: "percent", empty_text: "n/a"}, 0.25);
    assert.match(out, /25/);
    assert.doesNotMatch(out, /n\/a/);
});

// Cell alignment (req-web-stdpanel-table-config-25).
test("every column is vertically centred and left-aligned unless its spec says align", () => {
    const [a, b, c] = buildCustomColumns([
        {field: "a", title: "A"},
        {field: "b", title: "B", align: "right"},
        {field: "c", title: "C", align: "center"},
    ]);
    assert.deepEqual([a.vertAlign, a.hozAlign, a.headerHozAlign], ["middle", "left", undefined]);
    assert.deepEqual([b.vertAlign, b.hozAlign, b.headerHozAlign], ["middle", "right", "right"]);
    assert.deepEqual([c.vertAlign, c.hozAlign], ["middle", "center"]);
});

test("the leaves of a grouped header are centred too", () => {
    const [g] = buildCustomColumns([{title: "G", columns: [{field: "a", title: "A"}]}]);
    assert.equal(g.columns[0].vertAlign, "middle");
    assert.equal(g.columns[0].hozAlign, "left");
});

test("plain text is escaped in a shrinkable span, and an empty value stays empty", () => {
    const col = buildCustomColumns([{field: "f", title: "T"}, {field: "f", title: "T", formatter: "capitalized"}]);
    assert.equal(col[0].formatter(cellOf("<i>"), {}), TEXT("&lt;i&gt;"));
    assert.equal(col[1].formatter(cellOf("abc"), {}), TEXT("Abc"));
    assert.equal(col[0].formatter(cellOf(null), {}), "");
});

// Plain links (req-web-stdpanel-table-config-26).
test("formatter_params.style plain adds the plain modifier to every link formatter, default does not", () => {
    const row = {id: "c-1", name: "openssl", u: "https://example.com/x", items: [{id: "c-1", name: "openssl"}]};
    const cell = (value) => ({getValue: () => value, getRow: () => ({getData: () => row})});
    const html = (spec, value) => buildCustomColumns([{field: "f", title: "T", ...spec}])[0].formatter(cell(value), spec.formatter_params, () => {});
    const specs = [
        [{formatter: "link", formatter_params: {href_template: "/c/{id}", external: false}}, "CVE-1"],
        [{formatter: "externalLink"}, "https://example.com/x"],
        [{formatter: "linkList", formatter_params: {href_template: "/c/{id}", external: false}}, row.items],
    ];
    for (const [spec, value] of specs) {
        const plain = html({...spec, formatter_params: {...spec.formatter_params, style: "plain"}}, value);
        assert.match(plain, /class="tap-cell-link tap-cell-link--plain"/, spec.formatter);
        const dflt = html(spec, value);
        assert.match(dflt, /class="tap-cell-link"/, spec.formatter);
        assert.doesNotMatch(dflt, /--plain/, spec.formatter);
    }
});

// field_paths + joiner (req-web-stdpanel-table-config-28).
const joined = (spec, rows) => {
    const [resolved] = resolveFieldPaths([{title: "T", ...spec}], rows);
    return rows.map((r) => r[resolved.field]);
};
const PATHS = [["dimensions", "dataclass.customer"], ["dimensions", "dataclass.infra"]];

test("field_paths joins the non-empty values with the default joiner, in the order given", () => {
    const rows = [
        {dimensions: {"dataclass.customer": "high", "dataclass.infra": "low"}},
        {dimensions: {"dataclass.customer": "", "dataclass.infra": "low"}},
        {dimensions: {"dataclass.customer": "high"}},
        {dimensions: {"dataclass.customer": "  ", "dataclass.infra": null}},
        {dimensions: {}},
        {dimensions: null},
        {},
    ];
    assert.deepEqual(joined({field_paths: PATHS}, rows), ["high, low", "low", "high", null, null, null, null]);
});

test("field_paths honours the joiner, keeps zero and false, and skips lists and objects", () => {
    const rows = [{a: 0, b: false, c: [1], d: {x: 1}, e: "z"}];
    assert.deepEqual(joined({field_paths: [["a"], ["b"], ["c"], ["d"], ["e"]], joiner: " | "}, rows), ["0 | false | z"]);
    assert.deepEqual(joined({field_paths: [["e"], ["a"]], joiner: ""}, [{a: 1, e: "z"}]), ["z1"]);
});

test("field_paths reads own keys only, so a path never reaches the prototype", () => {
    const rows = [{dimensions: {}}];
    assert.deepEqual(joined({field_paths: [["dimensions", "constructor"], ["__proto__", "x"]]}, rows), [null]);
});

test("field_paths gives a dot-free key, works inside a group, and an all-empty cell shows empty_text", () => {
    const rows = [{a: {"b.c": "x"}}, {a: {}}];
    const specs = resolveFieldPaths(
        [{title: "G", columns: [{title: "J", field_paths: [["a", "b.c"], ["a", "d"]], empty_text: "none"}]}],
        rows,
    );
    const leaf = specs[0].columns[0];
    assert.ok(!leaf.field.includes("."));
    assert.deepEqual(rows.map((r) => r[leaf.field]), ["x", null]);
    const col = buildCustomColumns([leaf])[0];
    assert.equal(col.formatter(cellOf(rows[1][leaf.field]), {}, () => {}), "none");
    assert.equal(col.formatter(cellOf(rows[0][leaf.field]), {}, () => {}), TEXT("x"));
});

test("a field_paths column and a field_path column get distinct keys", () => {
    const rows = [{a: 1, b: 2}];
    const specs = resolveFieldPaths([{title: "A", field_path: ["a"]}, {title: "B", field_paths: [["a"], ["b"]]}], rows);
    assert.notEqual(specs[0].field, specs[1].field);
    assert.deepEqual([rows[0][specs[0].field], rows[0][specs[1].field]], [1, "1, 2"]);
});

// Wrapping text column (req-web-stdpanel-table-config-31).
test("wrap: true marks the column's cells, and only that column; the text stays escaped", () => {
    const [a, b, c] = buildCustomColumns([
        {field: "a", title: "A", wrap: true},
        {field: "b", title: "B"},
        {field: "c", title: "C", wrap: false},
    ]);
    assert.equal(a.cssClass, "tap-col-wrap");
    assert.equal(b.cssClass, undefined);
    assert.equal(c.cssClass, undefined);
    assert.equal(a.formatter(cellOf("x <b>y</b>"), {}), TEXT("x &lt;b&gt;y&lt;/b&gt;"));
    assert.equal(a.headerSort, true);
});

// The entityType formatter (req-web-stdpanel-table-config-32). params.types is the server's catalog.
const ET = "aws_core__aws_s3_bucket";
const types = {
    aws_core__aws_ecs_container: {name: "ECS Container", icon: "/static/aws_core/icons/aws-ecs.svg"},
    aws_core__aws_s3_bucket: {name: "S3 Bucket", icon: ""},
    computing_core__file: {name: "", icon: "/static/computing_core/icons/file.svg"},
};
const et = (value, params) => buildCustomColumns([{field: "t", title: "T", formatter: "entityType", formatter_params: params}])[0]
    .formatter(cellOf(value), params, () => {});

test("entityType shows the icon and the name pill for a type that has both, muted by default", () => {
    const out = et("aws_core__aws_ecs_container", {types});
    assert.match(out, /<img src="\/static\/aws_core\/icons\/aws-ecs\.svg" alt="ECS Container"/);
    assert.match(out, /ECS Container<\/span>$/);
    assert.match(out, /--tap-gray-100/, "the default tone is muted");
});

test("entityType show icon is the glyph alone, show name is the pill alone", () => {
    const icon = et("aws_core__aws_ecs_container", {types, show: "icon"});
    assert.match(icon, /^<img /);
    assert.doesNotMatch(icon, /<span/);
    const name = et("aws_core__aws_ecs_container", {types, show: "name"});
    assert.doesNotMatch(name, /<img/);
    assert.match(name, /ECS Container/);
});

test("entityType tone colours the pill", () => {
    assert.match(et(ET, {types, show: "name", tone: "good"}), /--tap-green-100/);
    assert.match(et(ET, {types, show: "name", tone: "nonsense"}), /--tap-gray-100/, "an unknown tone is muted");
});

test("a type with a name but no icon draws no image, and show icon falls back to the name", () => {
    assert.doesNotMatch(et(ET, {types}), /<img/);
    assert.match(et(ET, {types}), /S3 Bucket/);
    assert.equal(et(ET, {types, show: "icon"}), "S3 Bucket");
});

test("a type with an icon but no published name shows the humanised slug", () => {
    const out = et("computing_core__file", {types});
    assert.match(out, /<img src="\/static\/computing_core\/icons\/file\.svg" alt="File"/);
    assert.match(out, />File<\/span>$/);
});

test("an unknown type shows a humanised slug and no broken image", () => {
    const out = et("some_plugin__big_thing", {types});
    assert.doesNotMatch(out, /<img/);
    assert.match(out, />Big Thing<\/span>$/);
    assert.match(et("plain", {}), />Plain<\/span>$/, "no types at all is still safe");
});

test("a row value is only a lookup key: never an image address, never markup, never a prototype member", () => {
    for (const hostile of ["/static/evil.svg", "javascript:alert(1)", "__proto__", "constructor", "<img src=x onerror=1>"]) {
        const out = et(hostile, {types});
        assert.doesNotMatch(out, /<img/, hostile);
        assert.doesNotMatch(out, /<img src=x|onerror=1>/, hostile);
    }
});

test("a registry icon that is not a same-origin path is not drawn", () => {
    for (const bad of ["https://evil.example/x.svg", "//evil.example/x.svg", "javascript:alert(1)"]) {
        assert.doesNotMatch(et("t__x", {types: {t__x: {name: "X", icon: bad}}}), /<img/, bad);
    }
});

test("entityType escapes the published name, and an empty value is a dash or the empty_text", () => {
    assert.match(et("t__x", {types: {t__x: {name: "<b>&", icon: ""}}}), /&lt;b&gt;&amp;/);
    assert.match(et("", {types}), /–/);
    assert.equal(render({field: "t", title: "T", formatter: "entityType", empty_text: "none"}, null), "none");
});
