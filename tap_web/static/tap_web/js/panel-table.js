/**
 * panel-table.js — TAP Table Panel browser glue.
 *
 * Initializes a Tabulator instance for each Table Panel fragment on the page.
 * Data is read from an embedded <script type="application/json"> container
 * placed by the server-side template (req-web-stdpanel-table-render-3).
 *
 * Pagination is server-backed: clicking Prev/Next triggers an HTMX request
 * that replaces the panel fragment with a new server-rendered page.
 * Tabulator's own pagination is disabled.
 *
 * Column mode is selected via data-tap-table-mode on the mount element:
 *   "node" (default) — common_metadata columns
 *   "edge"           — edge relationship columns (from / type / to)
 */

(function () {
  "use strict";

  // Columns for common_metadata mode (req-web-stdpanel-table-columns).
  // Node data uses the GRIFT envelope shape (spec-grift-envelope):
  // spine fields flat at top; per-model fields in `data`; render hints in `display.tap_viz`.
  var COMMON_METADATA_COLUMNS = [
    {
      // Icon column — decorative, no header text, empty when no icon available.
      title: "",
      field: "display.tap_viz.icon_url",
      width: 36,
      hozAlign: "center",
      headerSort: false,
      formatter: function (cell) {
        var url = cell.getValue();
        if (!url) return "";
        var img = document.createElement("img");
        img.src = url;
        img.alt = "";
        img.setAttribute("aria-hidden", "true");
        img.style.width = "20px";
        img.style.height = "20px";
        img.style.display = "block";
        img.style.margin = "auto";
        return img;
      },
    },
    {
      title: "ID",
      field: "entity_id",
      width: 120,
      formatter: function (cell) {
        // Show only the last 8 chars of the UUID for readability.
        var val = cell.getValue() || "";
        return val.length > 8 ? "\u2026" + val.slice(-8) : val;
      },
      tooltip: function (e, cell) {
        return cell.getValue();
      },
    },
    {
      title: "Name",
      field: "name",
      widthGrow: 2,
    },
    {
      title: "Type",
      field: "entity_type",
      width: 120,
    },
    {
      title: "Last Edited",
      field: "updated_at",
      width: 160,
      // Route through the shared localtime helper so panel cells localize to the
      // viewer's browser zone with zone disclosure, identical to server-rendered
      // <time> elements (spec-web-time-display, req-web-time-single-helper).
      formatter: function (cell) {
        var val = cell.getValue();
        if (!val) return "";
        if (window.TapLocalTime) return window.TapLocalTime.formatEl(val);
        return String(val);
      },
    },
    {
      title: "Dimensions",
      field: "dimensions",
      widthGrow: 1,
      formatter: function (cell) {
        var val = cell.getValue();
        if (!val || typeof val !== "object") return "";
        return JSON.stringify(val);
      },
    },
  ];

  // ---------------------------------------------------------------------
  // Preset formatters — referenced by name from a panel's `columns` config
  // (config.columns[].formatter). String names keep the panel config
  // declarative (no inline JS in grift); the JS owns the rendering.
  // ---------------------------------------------------------------------
  function _safeStr(v) { return v == null ? "" : String(v); }
  function _escapeHtml(v) {
    return _safeStr(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // Resolve a dotted field path ("data.attributes.public") against a row object.
  function _getPath(obj, path) {
    if (!path) return undefined;
    var parts = String(path).split(".");
    var cur = obj;
    for (var i = 0; i < parts.length; i++) {
      if (cur == null) return undefined;
      cur = cur[parts[i]];
    }
    return cur;
  }


  // A href is safe when it is absolute http(s) or a same-origin path. "//host"
  // (protocol-relative) and every other scheme are rejected, so a hostile
  // value never becomes a javascript: or data: href.
  function _safeHref(v) {
    v = _safeStr(v);
    return /^https?:\/\//i.test(v) || (v.charAt(0) === "/" && v.charAt(1) !== "/");
  }
  // Fill "{data.x}" placeholders from a row. Each value is URI-encoded per
  // segment ("/" survives, so a branch like docs/foo keeps its slashes); an
  // empty value voids the whole link (returns ""), never a half-built URL.
  function _fillTemplate(template, row) {
    var missing = false;
    var out = _safeStr(template).replace(/\{([A-Za-z0-9_.]+)\}/g, function (_m, p) {
      var v = _safeStr(_getPath(row, p));
      if (!v) { missing = true; return ""; }
      return encodeURIComponent(v).replace(/%2F/gi, "/");
    });
    return missing ? "" : out;
  }
  function _elapsedSeconds(row, params) {
    params = params || {};
    // require_field: a run that has not concluded has no elapsed yet — its
    // "end" is whatever the API last touched. Empty → null, never a number.
    if (params.require_field && !_safeStr(_getPath(row, params.require_field))) return null;
    var a = Date.parse(_safeStr(_getPath(row, params.start)));
    var b = Date.parse(_safeStr(_getPath(row, params.end)));
    if (isNaN(a) || isNaN(b) || b < a) return null;
    return Math.round((b - a) / 1000);
  }
  function _humanDuration(sec) {
    if (sec < 60) return sec + "s";
    var m = Math.floor(sec / 60), s = sec % 60;
    if (m < 60) return m + "m " + (s < 10 ? "0" : "") + s + "s";
    var h = Math.floor(m / 60); m = m % 60;
    return h + "h " + (m < 10 ? "0" : "") + m + "m";
  }

  // Per-row baseline for the elapsed formatter: the median (and MAD) of the
  // OTHER rows in the same group (params.baseline.group_by field paths), from
  // the rows currently loaded in the table. Computed once per table+column and
  // cached on the table instance; the loaded page is the population, so the
  // sample size is always shown — a baseline of two rows is not a baseline.
  function _median(xs) {
    var a = xs.slice().sort(function (p, q) { return p - q; }); var n = a.length;
    return n % 2 ? a[(n - 1) / 2] : (a[n / 2 - 1] + a[n / 2]) / 2;
  }
  function _baselineFor(cell, params) {
    var b = params && params.baseline; if (!b || !Array.isArray(b.group_by) || !b.group_by.length) return null;
    var table = cell.getTable(); var key = JSON.stringify(b);
    table._tapBaselines = table._tapBaselines || {};
    var groups = table._tapBaselines[key];
    if (!groups) {
      groups = Object.create(null);  // no prototype: a group key can never be __proto__
      table.getData().forEach(function (row) {
        if (b.where && Object.keys(b.where).some(function (f) { return _safeStr(_getPath(row, f)) !== _safeStr(b.where[f]); })) return;
        var sec = _elapsedSeconds(row, params); if (sec == null) return;
        var g = b.group_by.map(function (f) { return _safeStr(_getPath(row, f)); }).join("\u0001");
        (groups[g] = groups[g] || []).push({ id: row.entity_id, sec: sec });
      });
      table._tapBaselines[key] = groups;
    }
    var row = cell.getRow().getData();
    var g = b.group_by.map(function (f) { return _safeStr(_getPath(row, f)); }).join("\u0001");
    var others = (groups[g] || []).filter(function (e) { return e.id !== row.entity_id; }).map(function (e) { return e.sec; });
    var minN = b.min_n || 3;
    if (others.length < minN) return { n: others.length, min_n: minN };
    var med = _median(others);
    var mad = _median(others.map(function (x) { return Math.abs(x - med); })) * 1.4826;
    return { n: others.length, min_n: minN, median: med, mad: mad };
  }

  var FORMATTERS = {
    plaintext: function (cell) { return _escapeHtml(cell.getValue()); },
    datetime: function (cell) {
      // Local timestamp with zone disclosure, via the shared localtime helper
      // (spec-web-time-display, req-web-time-single-helper). The incoming value
      // is UTC ISO-8601; the helper localizes to the viewer's browser zone.
      var v = cell.getValue();
      if (!v) return "";
      if (window.TapLocalTime) return window.TapLocalTime.formatEl(v);
      return _escapeHtml(v);
    },
    tickCross: function (cell) {
      var v = cell.getValue();
      if (v === true || v === "true") return '<span style="color:#16a34a;font-weight:600">✓</span>';
      if (v === false || v === "false") return '<span style="color:#dc2626;font-weight:600">✕</span>';
      return '<span style="color:#9ca3af">–</span>';
    },
    ellipsisSuffix: function (cell) {
      var v = _safeStr(cell.getValue());
      return _escapeHtml(v.length > 8 ? "…" + v.slice(-8) : v);
    },
    json: function (cell) {
      var v = cell.getValue();
      if (v == null) return "";
      if (typeof v === "object") {
        var s = JSON.stringify(v);
        return _escapeHtml(s.length > 60 ? s.slice(0, 60) + "…" : s);
      }
      return _escapeHtml(v);
    },
    passFailBadge: function (cell) {
      var v = _safeStr(cell.getValue()).toLowerCase();
      if (v === "pass") return '<span style="background:#dcfce7;color:#166534;padding:2px 8px;border-radius:4px;font-weight:600;font-size:11px">PASS</span>';
      if (v === "fail") return '<span style="background:#fee2e2;color:#991b1b;padding:2px 8px;border-radius:4px;font-weight:600;font-size:11px">FAIL</span>';
      return _escapeHtml(cell.getValue());
    },
    conclusionBadge: function (cell) {
      // GitHub-shaped terminal conclusion (workflow run / job): success,
      // failure, cancelled, skipped, timed_out, action_required, neutral,
      // stale, startup_failure. Green/red for the two that matter, a neutral
      // grey pill for the rest, and a dash for absent — an empty cell must read
      // as "not observed", never as quietly fine.
      var v = _safeStr(cell.getValue()).toLowerCase();
      if (!v) return '<span style="color:#9ca3af">–</span>';
      var pill = function (bg, fg, text) {
        return '<span style="background:' + bg + ';color:' + fg + ';padding:2px 8px;border-radius:4px;font-weight:600;font-size:11px">' + text + '</span>';
      };
      if (v === "success") return pill("#dcfce7", "#166534", "SUCCESS");
      if (v === "failure" || v === "timed_out" || v === "startup_failure") return pill("#fee2e2", "#991b1b", v.toUpperCase().replace(/_/g, " "));
      return pill("#f3f4f6", "#4b5563", _escapeHtml(v.toUpperCase().replace(/_/g, " ")));
    },
    externalLink: function (cell) {
      // A URL rendered as an anchor that opens in a new tab. Only http(s)
      // values become links; anything else renders as escaped text so a
      // hostile value never becomes a javascript: href.
      var v = _safeStr(cell.getValue());
      if (!/^https?:\/\//i.test(v)) return _escapeHtml(v);
      var label = v.replace(/^https?:\/\//i, "");
      if (label.length > 48) label = label.slice(0, 47) + "…";
      return '<a href="' + _escapeHtml(v) + '" target="_blank" rel="noopener noreferrer" style="color:#2563eb;text-decoration:underline" title="' + _escapeHtml(v) + '">' + _escapeHtml(label) + ' ↗</a>';
    },
    link: function (cell, params) {
      // The cell's own value as the link text; the href comes from another
      // field (href_field) or a template over the row (href_template). A
      // missing or unsafe href degrades to plain text. external:false keeps
      // the link in-tab (same-origin paths); the default opens a new tab.
      params = params || {};
      var row = cell.getRow().getData();
      var text = params.text ? _safeStr(params.text) : _safeStr(cell.getValue());
      var href = params.href_field ? _safeStr(_getPath(row, params.href_field)) : _fillTemplate(params.href_template, row);
      if (!text || !_safeHref(href)) return _escapeHtml(text);
      var target = params.external === false ? "" : ' target="_blank" rel="noopener noreferrer"';
      return '<a href="' + _escapeHtml(href) + '"' + target + ' class="tap-cell-link" style="color:#2563eb;text-decoration:underline" title="' + _escapeHtml(href) + '">' + _escapeHtml(text) + '</a>';
    },
    elapsed: function (cell, params) {
      // Wall-clock between two ISO timestamps on the row (params.start /
      // params.end), humanized; exact seconds in the title. Absent or
      // inverted → a dash, never "0s". The ratio to the row's group baseline
      // is its own column: baselineRatio / baselineN.
      var sec = _elapsedSeconds(cell.getRow().getData(), params);
      if (sec == null) return '<span style="color:#9ca3af">–</span>';
      return '<span title="' + sec + ' s">' + _escapeHtml(_humanDuration(sec)) + '</span>';
    },
    baselineRatio: function (cell, params) {
      // This row's elapsed over the median of the OTHER loaded rows in its
      // group (params.start/end + params.baseline). Three states, never two:
      // ▲ratio (slow, red) / ▼ratio (fast, muted) / ratio (within) — or a
      // dash with the sample size when history is thin. Sorts by the ratio.
      var row = cell.getRow().getData();
      var sec = _elapsedSeconds(row, params);
      var base = _baselineFor(cell, params);
      if (sec == null || !base) return '<span style="color:#9ca3af">–</span>';
      if (base.median == null) {
        return '<span style="color:#9ca3af" title="not enough history: ' + base.n + ' comparable run(s) loaded, ' + base.min_n + ' needed">–</span>';
      }
      var b = params.baseline; var ratio = sec / (base.median || 1);
      var flagRatio = b.flag_ratio || 1.5, madK = b.mad_k || 3;
      var slow = ratio >= flagRatio && sec > base.median + madK * base.mad;
      var fast = ratio <= 1 / flagRatio && sec < base.median - madK * base.mad;
      var title = 'median ' + _humanDuration(Math.round(base.median)) + ' over ' + base.n + ' comparable run(s); spread ±' + _humanDuration(Math.round(base.mad));
      if (slow) return '<span style="color:#b91c1c;font-weight:600" title="' + _escapeHtml(title) + '">▲' + ratio.toFixed(1) + '×</span>';
      if (fast) return '<span style="color:#6b7280" title="' + _escapeHtml(title) + '">▼' + ratio.toFixed(1) + '×</span>';
      return '<span style="color:#6b7280" title="' + _escapeHtml(title) + '">' + ratio.toFixed(1) + '×</span>';
    },
    baselineN: function (cell, params) {
      // The sample size behind baselineRatio — how many comparable rows are
      // loaded for this row's group. Sorts numerically.
      var base = _baselineFor(cell, params);
      if (!base) return '<span style="color:#9ca3af">–</span>';
      var thin = base.median == null;
      return '<span style="color:' + (thin ? '#9ca3af' : '#374151') + '" title="' + (thin ? 'below the ' + base.min_n + ' needed for a baseline' : 'comparable runs loaded') + '">' + base.n + '</span>';
    },
    sparkline: function (cell, params) {
      // The row's group (params.group_by) as a strip: one bar per loaded row,
      // placed at its actual start time (params.x) on an axis shared by the
      // whole table so cadence reads across rows, height = elapsed relative to
      // the group's longest, failures in the critical hue, this row in the
      // accent, the group median as a hairline. Wrapped in a link when
      // params.href_template is set.
      params = params || {};
      var table = cell.getTable(); var row = cell.getRow().getData();
      var key = "spark:" + JSON.stringify(params);
      table._tapBaselines = table._tapBaselines || {};
      var groups = table._tapBaselines[key];
      if (!groups) {
        groups = { byGroup: Object.create(null), xmin: Infinity, xmax: -Infinity };
        table.getData().forEach(function (r) {
          var x = Date.parse(_safeStr(_getPath(r, params.x || params.start)));
          var sec = _elapsedSeconds(r, params); if (isNaN(x) || sec == null) return;
          var g = (params.group_by || []).map(function (f) { return _safeStr(_getPath(r, f)); }).join("\u0001");
          (groups.byGroup[g] = groups.byGroup[g] || []).push({ id: r.entity_id, x: x, sec: sec, status: _safeStr(_getPath(r, params.color_field || "data.conclusion")) });
          if (x < groups.xmin) groups.xmin = x; if (x > groups.xmax) groups.xmax = x;
        });
        table._tapBaselines[key] = groups;
      }
      var g = (params.group_by || []).map(function (f) { return _safeStr(_getPath(row, f)); }).join("\u0001");
      var series = groups.byGroup[g] || [];
      if (!series.length) return '<span style="color:#9ca3af">–</span>';
      var W = params.width || 120, H = params.height || 24, pad = 3;
      // Axis: the group's own first→last run (params.axis "group", default) or
      // the whole table's window (params.axis "table"). A table-wide axis is
      // comparable across rows but a burst of recent runs piles into a few
      // pixels; the label always states the span in days either way.
      var xmin = groups.xmin, xmax = groups.xmax;
      if (params.axis !== "table") {
        xmin = Infinity; xmax = -Infinity;
        series.forEach(function (e) { if (e.x < xmin) xmin = e.x; if (e.x > xmax) xmax = e.x; });
      }
      var span = Math.max(1, xmax - xmin);
      var maxSec = series.reduce(function (m, e) { return Math.max(m, e.sec); }, 1);
      var med = _median(series.map(function (e) { return e.sec; }));
      var bad = params.bad_values || ["failure", "timed_out", "startup_failure", "cancelled"];
      var bars = series.slice().sort(function (a, b) { return a.x - b.x; }).map(function (e) {
        var x = pad + ((e.x - xmin) / span) * (W - 2 * pad);
        var h = Math.max(2, Math.round((e.sec / maxSec) * (H - 2 * pad)));
        var isMe = e.id === row.entity_id;
        var fill = bad.indexOf(e.status) >= 0 ? "#d03b3b" : (isMe ? "#1f2328" : "#9ca3af");
        var w = isMe ? 3 : 2;
        return '<rect x="' + (x - w / 2).toFixed(1) + '" y="' + (H - pad - h) + '" width="' + w + '" height="' + h + '" rx="1" fill="' + fill + '"><title>' + _escapeHtml(_humanDuration(e.sec) + " · " + e.status + " · " + new Date(e.x).toLocaleString()) + '</title></rect>';
      }).join("");
      var my = H - pad - Math.max(2, Math.round((med / maxSec) * (H - 2 * pad)));
      var hair = '<line x1="' + pad + '" y1="' + my + '" x2="' + (W - pad) + '" y2="' + my + '" stroke="#6b7280" stroke-width="1" stroke-dasharray="2 2" opacity="0.7"/>';
      var msPerDay = 24 * 60 * 60 * 1000;
      var days = Math.round(span / msPerDay);
      var label = series.length + " run(s) over " + (days < 1 ? "one day" : days + " days") + (params.axis === "table" ? " (shared axis)" : "") + "; median " + _humanDuration(Math.round(med)) + "; this run " + _humanDuration(_elapsedSeconds(row, params) || 0);
      var svg = '<svg width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + _escapeHtml(label) + '" style="display:block;overflow:visible"><title>' + _escapeHtml(label) + '</title>' + hair + bars + '</svg>';
      var href = params.href_template ? _fillTemplate(params.href_template, row) : "";
      if (!_safeHref(href)) return svg;
      return '<a href="' + _escapeHtml(href) + '" class="tap-cell-link" style="display:inline-block" title="' + _escapeHtml(label) + '">' + svg + '</a>';
    },
    iconMap: function (cell, params) {
      // A closed-set value rendered as a glyph: params.icons maps value →
      // same-origin image path, params.labels maps value → accessible label
      // (defaults to the value). Unmapped values render as text so a new
      // vocabulary word is visible, not invisible. show_text keeps the word
      // beside the glyph.
      params = params || {};
      var v = _safeStr(cell.getValue());
      var src = _safeStr((params.icons || {})[v]);
      if (!v || !src || src.charAt(0) !== "/" || src.charAt(1) === "/") return _escapeHtml(v);
      var label = _safeStr((params.labels || {})[v] || v);
      var img = '<img src="' + _escapeHtml(src) + '" alt="' + _escapeHtml(label) + '" title="' + _escapeHtml(label) + '" width="16" height="16" style="display:inline-block;vertical-align:middle">';
      return params.show_text ? img + ' <span>' + _escapeHtml(v) + '</span>' : img;
    },
    tailSegment: function (cell, params) {
      // The last path segment of a slash-joined value ("owner/repo" → "repo"),
      // full value in the title. For a single-account instance the owner is
      // noise on every row. params.sep overrides the separator.
      var v = _safeStr(cell.getValue()); var sep = (params && params.sep) || "/";
      var i = v.lastIndexOf(sep); var tail = i >= 0 ? v.slice(i + 1) : v;
      return '<span title="' + _escapeHtml(v) + '">' + _escapeHtml(tail) + '</span>';
    },
    painBadge: function (cell) {
      var v = _safeStr(cell.getValue());
      var colors = {
        N1: ["#dbeafe", "#1e40af"], N2: ["#dcfce7", "#166534"],
        N3: ["#fef3c7", "#92400e"], N4: ["#fed7aa", "#9a3412"],
        N5: ["#fecaca", "#991b1b"],
      };
      var pair = colors[v];
      if (!pair) return v;
      return '<span style="background:' + pair[0] + ';color:' + pair[1] +
        ';padding:2px 8px;border-radius:4px;font-weight:600;font-size:11px">' + v + '</span>';
    },
    arrayCount: function (cell) {
      var v = cell.getValue();
      if (!Array.isArray(v) || v.length === 0) return '<span style="color:#9ca3af">—</span>';
      return String(v.length);
    },
    // Like tickCross but a "no" is rendered as a neutral dash rather than a red
    // ✕ — for boolean columns where false/absent is unremarkable (e.g. a
    // component simply not being public).
    tickDash: function (cell) {
      var v = cell.getValue();
      if (v === true || v === "true") return '<span style="color:#16a34a;font-weight:600">✓</span>';
      return '<span style="color:#9ca3af">–</span>';
    },
    // Compact FIPS-199-style impact level: low → L, moderate → M, high → H,
    // anything else (not-applicable, n/a, blank) → a neutral dash. Color-coded
    // by severity so the C/I/A columns read at a glance.
    ciaLevel: function (cell) {
      var v = _safeStr(cell.getValue()).toLowerCase().trim();
      var map = { low: ["L", "#16a34a"], moderate: ["M", "#d97706"], high: ["H", "#dc2626"] };
      var hit = map[v];
      if (hit) return '<span style="color:' + hit[1] + ';font-weight:700">' + hit[0] + '</span>';
      return '<span style="color:#9ca3af">–</span>';
    },
  };

  // Per-entity-type detail URLs override the generic /object/<type>/.../ route
  // when a custom page exists (Path B parameterized pages). Coupling lives in
  // the URL map for now; a per-plugin registration mechanism would lift this.
  // Each function receives (entity_id, rowData) so a single entity_type can
  // route by an inner field — compliance_artifact fans out by `kind` to the
  // dedicated OSCAL workbench viewers (entity passed via each viewer's
  // entity_id_var query param), falling back to the universal viewer.
  var PER_TYPE_DETAIL_URL = {
    vdr_finding:         function (id) { return "/samsite/finding/"   + id; },
    ksi_indicator:       function (id) { return "/samsite/indicator/" + id; },
    ksi_component:       function (id) { return "/samsite/component/" + id; },
    ksi_signal:          function (id) { return "/samsite/artifacts/ksi-signal?ksi_signal_entity_id=" + id; },
    vdr_report:          function (id) { return "/samsite/artifacts/vdr-report?vdr_report_entity_id=" + id; },
    batch:               function (id) { return "/administrivia/batch?batch_entity_id=" + id; },
    compliance_artifact: function (id, row) {
      var kind = ((row || {}).data || {}).kind || "";
      if (kind === "oscal_ssp")  return "/samsite/artifacts/ssp?oscal_ssp_artifact_entity_id=" + id;
      if (kind === "oscal_poam") return "/samsite/artifacts/poam?oscal_poam_artifact_entity_id=" + id;
      if (kind === "iiw")        return "/samsite/artifacts/iiw?iiw_artifact_entity_id=" + id;
      return "/samsite/artifact/" + id;  // fallback: universal viewer
    },
  };

  function buildCustomColumns(specs) {
    return specs.map(function (spec) {
      var col = {
        field: spec.field,
        title: spec.title,
        headerSort: spec.headerSort !== false,
      };
      if (spec.header_tooltip) col.headerTooltip = spec.header_tooltip;
      if (spec.width != null) col.width = spec.width;
      if (spec.widthGrow != null) col.widthGrow = spec.widthGrow;
      if (spec.minWidth != null) col.minWidth = spec.minWidth;
      var fmt = FORMATTERS[spec.formatter || "plaintext"];
      if (fmt) {
        col.formatter = fmt;
        // Declarative per-column parameters (config.columns[].formatter_params)
        // reach the formatter as Tabulator's formatterParams.
        col.formatterParams = spec.formatter_params || {};
      }
      if (spec.formatter === "baselineRatio" || spec.formatter === "baselineN") {
        var bp = spec.formatter_params || {};
        col.sorter = function (a, b, aRow, bRow) {
          var f = function (r) {
            var fake = { getRow: function () { return r; }, getTable: function () { return r.getTable(); } };
            var base = _baselineFor(fake, bp);
            if (!base) return -1;
            if (spec.formatter === "baselineN") return base.n;
            var sec = _elapsedSeconds(r.getData(), bp);
            return (base.median == null || sec == null) ? -1 : sec / (base.median || 1);
          };
          return f(aRow) - f(bRow);
        };
      }
      if (spec.formatter === "elapsed") {
        // Sort by the computed seconds, not by the cell's own field.
        var ep = spec.formatter_params || {};
        col.sorter = function (a, b, aRow, bRow) {
          var x = _elapsedSeconds(aRow.getData(), ep), y = _elapsedSeconds(bRow.getData(), ep);
          return (x == null ? -1 : x) - (y == null ? -1 : y);
        };
      }
      if (spec.tooltip === "full_value") {
        col.tooltip = function (e, cell) { return _safeStr(cell.getValue()); };
      }
      return col;
    });
  }

  // Columns for edge mode — endpoint labels resolved into display.tap_viz.
  // Edge envelopes follow the same shape as node envelopes; edge_type and
  // properties live in `data`, from/to labels in `display.tap_viz.{from,to}_label`.
  var EDGE_COLUMNS = [
    {
      title: "From",
      field: "display.tap_viz.from_label",
      widthGrow: 2,
    },
    {
      title: "Type",
      field: "data.edge_type",
      width: 160,
    },
    {
      title: "To",
      field: "display.tap_viz.to_label",
      widthGrow: 2,
    },
    {
      title: "Properties",
      field: "data.properties",
      widthGrow: 1,
      formatter: function (cell) {
        var val = cell.getValue();
        if (!val || typeof val !== "object" || Object.keys(val).length === 0) return "";
        return JSON.stringify(val);
      },
    },
  ];

  /**
   * Mount a single Table Panel.
   *
   * @param {HTMLElement} mountEl  - div[data-tap-table-mount]
   */
  function mountTablePanel(mountEl) {
    // Skip if already initialized (prevents double-init on full-document re-scan).
    if (mountEl.getAttribute("data-tap-table-mounted")) return;

    var panelId = mountEl.getAttribute("data-tap-table-panel-id");
    if (!panelId) return;

    var dataScriptEl = document.getElementById("tap-table-data-" + panelId);
    if (!dataScriptEl) {
      console.warn("TAP table panel: no data script found for panel", panelId);
      return;
    }

    var rows;
    try {
      rows = JSON.parse(dataScriptEl.textContent);
    } catch (e) {
      console.error("TAP table panel: failed to parse data for panel", panelId, e);
      return;
    }

    // Per-panel custom column spec (from panel.config.columns); when present,
    // overrides the default common_metadata / edge column sets.
    var customColumns = null;
    var customColumnsScript = document.getElementById("tap-table-columns-" + panelId);
    if (customColumnsScript) {
      try {
        customColumns = JSON.parse(customColumnsScript.textContent);
      } catch (e) {
        console.warn("TAP table panel: failed to parse columns spec for panel", panelId, e);
      }
    }

    var mode = mountEl.getAttribute("data-tap-table-mode") || "node";
    var columns;
    if (customColumns && customColumns.length > 0) {
      columns = buildCustomColumns(customColumns);
    } else {
      columns = mode === "edge" ? EDGE_COLUMNS : COMMON_METADATA_COLUMNS;
    }

    // Optional declarative row grouping (panel.config.group_by). Generic
    // prefix-rule engine: each row is classified into a group by matching a
    // field value against an ordered list of {prefix, label} rules; non-matches
    // fall into default_label. Group display order follows rule order, so the
    // consumer's grift config — not this platform JS — owns the section taxonomy.
    var groupSpec = null;
    var groupScript = document.getElementById("tap-table-groupby-" + panelId);
    if (groupScript) {
      try {
        groupSpec = JSON.parse(groupScript.textContent);
      } catch (e) {
        console.warn("TAP table panel: failed to parse group_by spec for panel", panelId, e);
      }
    }

    var tableOptions = {
      data: rows,
      columns: columns,
      layout: "fitColumns",
      pagination: false, // Server handles pagination; disable Tabulator's own.
      placeholder: "No results.",
    };
    // config.refresh_seconds: re-fetch this panel's fragment on a timer via
    // the enclosing page slot's hx-get (htmx:afterSettle remounts the table),
    // with a countdown pill and a pause toggle so the reader knows the table is
    // live. Paused state is remembered per panel for the browser session.
    var refreshEvery = parseInt(mountEl.getAttribute("data-tap-table-refresh") || "", 10);
    if (refreshEvery > 0) _startAutoRefresh(mountEl, panelId, refreshEvery);

    // config.height (px): a fixed-height table that scrolls inside itself
    // with a sticky header, so a page can let the document scroll while each
    // table stays a reasonable size.
    var fixedHeight = parseInt(mountEl.getAttribute("data-tap-table-height") || "", 10);
    if (fixedHeight > 0) tableOptions.height = fixedHeight;

    if (groupSpec && Array.isArray(groupSpec.rules) && groupSpec.rules.length > 0) {
      var groupRules = groupSpec.rules;
      var groupField = groupSpec.field;
      var defaultLabel = groupSpec.default_label || "Other";
      var classify = function (rowData) {
        var raw = _safeStr(_getPath(rowData, groupField));
        for (var i = 0; i < groupRules.length; i++) {
          if (raw.indexOf(groupRules[i].prefix) === 0) return groupRules[i].label;
        }
        return defaultLabel;
      };
      // Rank groups by rule order (default group sorts last) so sections render
      // in the order the consumer declared, with rows sorted within each group.
      var groupRank = {};
      groupRules.forEach(function (r, i) { groupRank[r.label] = i; });
      var defaultRank = groupRules.length;
      var rankOf = function (label) {
        return Object.prototype.hasOwnProperty.call(groupRank, label) ? groupRank[label] : defaultRank;
      };
      rows.sort(function (a, b) {
        var ra = rankOf(classify(a)), rb = rankOf(classify(b));
        if (ra !== rb) return ra - rb;
        var av = _safeStr(_getPath(a, groupField)), bv = _safeStr(_getPath(b, groupField));
        return av < bv ? -1 : av > bv ? 1 : 0;
      });
      tableOptions.groupBy = classify;
      tableOptions.groupHeader = function (value, count) {
        return _safeStr(value) +
          ' <span style="color:#6b7280;font-weight:400;margin-left:8px">(' + count + ')</span>';
      };
    }

    // Node-mode rows navigate to the object viewer on click (req-web-stdpanel-table-row-nav).
    // Use rowFormatter to attach the click handler directly on the DOM element — Tabulator v6
    // removed rowClick as a constructor option in favour of table.on().
    if (mode === "node") {
      tableOptions.rowFormatter = function (row) {
        var el = row.getElement();
        el.style.cursor = "pointer";
        el.addEventListener("click", function (ev) {
          // A click on an in-cell link (link / externalLink formatters) is the
          // link's, not the row's — otherwise one click opens two pages.
          if (ev && ev.target && ev.target.closest && ev.target.closest("a")) return;
          var data = row.getData();
          var entityType = data.entity_type || "";
          var entityId = data.entity_id || "";
          var urlId = ((data.display || {}).tap_viz || {}).url_id || "";
          if (!entityType) return;
          // Save scroll position so the back-button restoration can return
          // the user to where they were on this page.
          saveScrollForReturn();
          var perType = PER_TYPE_DETAIL_URL[entityType];
          if (perType && entityId) {
            window.location.href = perType(entityId, data);
          } else if (urlId) {
            window.location.href = "/object/" + entityType + "/" + urlId + "/";
          }
        });
      };
    } else if (mode === "raw") {
      // Raw-mode rows are self-sourced (the panel emits the JSON). A row may
      // carry a `_url` string; if present the row becomes a clickable
      // navigation to that URL. Rows without `_url` stay inert.
      tableOptions.rowFormatter = function (row) {
        var url = row.getData()._url || "";
        if (!url) return;
        var el = row.getElement();
        el.style.cursor = "pointer";
        el.addEventListener("click", function () {
          saveScrollForReturn();
          window.location.href = url;
        });
      };
    }

    /* global Tabulator */
    var table = new Tabulator(mountEl, tableOptions);
    mountEl.setAttribute("data-tap-table-mounted", "true");

    // Optional quick-filter search box (panel.config.quick_filter). Live-filters
    // the loaded rows across all displayed columns; group headers re-count as the
    // set narrows. Client-side only — scoped to the rows currently on the page.
    var filterInput = document.getElementById("tap-table-filter-" + panelId);
    if (filterInput) {
      var filterFields = (customColumns && customColumns.length > 0)
        ? customColumns.map(function (c) { return c.field; })
        : ["name", "entity_type"];
      var applyFilter = function () {
        var term = filterInput.value.trim().toLowerCase();
        if (!term) { table.clearFilter(); return; }
        table.setFilter(function (data) {
          for (var i = 0; i < filterFields.length; i++) {
            var v = _getPath(data, filterFields[i]);
            if (v != null && String(v).toLowerCase().indexOf(term) !== -1) return true;
          }
          return false;
        });
      };
      filterInput.addEventListener("input", applyFilter);
      // Re-apply any pre-existing value (e.g. after an HTMX fragment swap that
      // recreated the table but left a typed term in the input).
      if (filterInput.value) applyFilter();
    }
  }

  /**
   * Find and mount all table panels within a root element.
   *
   * @param {Document|HTMLElement} root
   */

  function _startAutoRefresh(mountEl, panelId, seconds) {
    var slot = mountEl.closest("[hx-get]");
    var status = mountEl.parentElement ? mountEl.parentElement.querySelector("[data-tap-table-refresh-status]") : null;
    if (!slot || typeof htmx === "undefined") return;
    var key = "tap-table-refresh-paused:" + panelId;
    var paused = false;
    try { paused = sessionStorage.getItem(key) === "1"; } catch (e) { /* storage unavailable: never paused */ }
    var left = seconds;
    var render = function () {
      if (!status) return;
      status.textContent = paused ? "⏸ auto-refresh paused" : "↻ auto-refresh in " + left + "s";
      status.style.cursor = "pointer";
      status.setAttribute("role", "button");
      status.setAttribute("aria-live", "polite");
    };
    if (status) {
      status.addEventListener("click", function () {
        paused = !paused; left = seconds;
        try { sessionStorage.setItem(key, paused ? "1" : "0"); } catch (e) { /* ignore */ }
        render();
      });
    }
    render();
    var timer = setInterval(function () {
      if (!document.contains(mountEl)) { clearInterval(timer); return; }  // fragment replaced
      if (paused) return;
      left -= 1;
      if (left > 0) { render(); return; }
      clearInterval(timer);
      if (status) status.textContent = "↻ refreshing…";
      htmx.ajax("GET", slot.getAttribute("hx-get"), { target: slot, swap: "innerHTML" });
    }, 1000);
  }

  function mountAll(root) {
    var mounts = (root || document).querySelectorAll("[data-tap-table-mount]");
    mounts.forEach(function (el) {
      mountTablePanel(el);
    });
  }

  // Initial mount on DOMContentLoaded.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      mountAll(document);
    });
  } else {
    mountAll(document);
  }

  // Re-mount after HTMX swaps (panel fragment reload, pagination).
  // Use htmx:afterSettle (fires after DOM is stable) and search from
  // document — outerHTML swaps remove the original target from the DOM,
  // so evt.detail.target may be stale.
  document.addEventListener("htmx:afterSettle", function () {
    mountAll(document);
    mountPageSizeSelectors(document);
  });

  // --- Page-size selector with localStorage persistence ---

  var STORAGE_KEY = "tap-table-page-size";

  function getStoredPageSize() {
    try {
      var val = localStorage.getItem(STORAGE_KEY);
      return val !== null ? val : null;
    } catch (e) {
      return null;
    }
  }

  function storePageSize(value) {
    try {
      localStorage.setItem(STORAGE_KEY, value);
    } catch (e) {
      // Silently ignore storage failures.
    }
  }

  /**
   * Wire up page-size <select> elements within a root.
   * On change, persist to localStorage and reload the panel via HTMX.
   * The nav bar appears twice (above + below table); both selectors are
   * wired but only one triggers the localStorage-restore reload.
   */
  function mountPageSizeSelectors(root) {
    var selects = (root || document).querySelectorAll("[data-tap-page-size-select]");
    var reloadTriggered = false;

    selects.forEach(function (sel) {
      // Skip already-wired selectors.
      if (sel.getAttribute("data-tap-mounted")) return;
      sel.setAttribute("data-tap-mounted", "true");

      // On first load, if localStorage has a stored value and it differs from
      // the server-rendered selection, trigger a reload with the stored value.
      // Only one selector needs to trigger this (the reload replaces both).
      if (!reloadTriggered) {
        var stored = getStoredPageSize();
        if (stored !== null && sel.value !== stored) {
          var hasOption = Array.from(sel.options).some(function (o) {
            return o.value === stored;
          });
          if (hasOption) {
            sel.value = stored;
            reloadTriggered = true;
            reloadPanel(sel, stored);
            return;
          }
        }
      }

      sel.addEventListener("change", function () {
        var newSize = sel.value;
        storePageSize(newSize);
        reloadPanel(sel, newSize);
      });
    });
  }

  /**
   * Reload the panel fragment via HTMX with the given page_size.
   */
  function reloadPanel(selectEl, pageSize) {
    var footer = selectEl.closest("[data-tap-table-footer]");
    if (!footer) return;
    var slug = footer.getAttribute("data-tap-panel-slug");
    var panelId = footer.getAttribute("data-tap-panel-id");
    if (!slug || !panelId) return;

    var panelEl = footer.closest(".tap-panel--table");
    if (!panelEl) return;

    var url = "/panel/" + slug + "--" + panelId + "/?page_size=" + pageSize + "&offset=0";

    /* global htmx */
    if (typeof htmx !== "undefined") {
      htmx.ajax("GET", url, { target: panelEl, swap: "outerHTML" });
    }
  }

  // Initial mount for page-size selectors.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      mountPageSizeSelectors(document);
    });
  } else {
    mountPageSizeSelectors(document);
  }

  // ---------------------------------------------------------------------
  // Scroll restoration.
  //
  // Pages with table panels lazy-load their content via HTMX after initial
  // page render. Browsers' default scroll restoration fires BEFORE the
  // panels expand the document height, so back-navigation lands at the top
  // even though the browser "tried" to restore. Workaround: take over the
  // restoration ourselves — save scrollY when navigating away via a row
  // click, restore once the document is tall enough to accommodate it
  // (after htmx:afterSettle fires for the lazy panels).
  // ---------------------------------------------------------------------
  var SCROLL_KEY_PREFIX = "tap-return-scroll:";

  function saveScrollForReturn() {
    try {
      sessionStorage.setItem(SCROLL_KEY_PREFIX + window.location.pathname, String(window.scrollY));
    } catch (e) {
      // sessionStorage can fail in private mode; silently ignore.
    }
  }

  function _scrollKey() { return SCROLL_KEY_PREFIX + window.location.pathname; }

  var _scrollRestoreDone = false;
  function tryRestoreScroll() {
    if (_scrollRestoreDone) return;
    var savedY;
    try { savedY = sessionStorage.getItem(_scrollKey()); } catch (e) { return; }
    if (!savedY) return;
    var targetY = parseInt(savedY, 10);
    if (isNaN(targetY) || targetY <= 0) {
      try { sessionStorage.removeItem(_scrollKey()); } catch (e) { /* ignore */ }
      _scrollRestoreDone = true;
      return;
    }
    // Only scroll once the document is tall enough for the saved Y to be valid.
    if (document.documentElement.scrollHeight >= targetY + window.innerHeight - 50) {
      window.scrollTo(0, targetY);
      try { sessionStorage.removeItem(_scrollKey()); } catch (e) { /* ignore */ }
      _scrollRestoreDone = true;
    }
  }

  // Take manual control so the browser doesn't auto-restore to the wrong
  // (pre-lazy-load) position.
  if ("scrollRestoration" in history) {
    history.scrollRestoration = "manual";
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", tryRestoreScroll);
  } else {
    tryRestoreScroll();
  }
  // Each HTMX settle expands the page; retry restoration in case the
  // document just grew tall enough.
  document.addEventListener("htmx:afterSettle", tryRestoreScroll);
})();
