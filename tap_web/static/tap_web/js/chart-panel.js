/**
 * chart-panel.js -- draws the Chart panel (req-web-panels-chart-render).
 *
 * The server renders <figure data-tap-chart data-tap-chart-option='{...}'> holding an ECharts option that is
 * pure JSON (rows already injected as option.dataset). This script only: reads the page's design tokens
 * (--tap-chart-* on the panel root) into an ECharts theme, applies the optional colour map, turns on `aria`,
 * draws, and redraws on theme change and on container resize. It names no field, panel or chart type, and it
 * never evaluates anything from the option.
 */
(function () {
  "use strict";

  var live = []; // {root, mount, option, colorSpec, chart, ro}
  var HAS = Object.prototype.hasOwnProperty;

  function tokens(root) {
    var cs = getComputedStyle(root);
    return {
      v: function (name, fallback) {
        var x = cs.getPropertyValue("--tap-chart-" + name).trim();
        return x || fallback;
      }
    };
  }

  function theme(t) {
    var text = t.v("text", "#0f172a"), muted = t.v("text-muted", "#475569");
    var axis = t.v("axis", "#64748b"), grid = t.v("grid", "#e2e8f0"), bg = t.v("bg", "#ffffff");
    var axisCommon = {
      axisLine: { lineStyle: { color: axis } },
      axisTick: { lineStyle: { color: axis } },
      axisLabel: { color: muted },
      nameTextStyle: { color: muted },
      splitLine: { lineStyle: { color: grid } }
    };
    var palette = [];
    for (var i = 1; i <= 8; i++) palette.push(t.v("accent-" + i, "#0072b2"));
    // Data labels are solid filled text: no outline (ECharts' text border is what made them hard to read on
    // the dark frame), the theme's text colour unless the config sets one (req-web-panels-chart-theme-5).
    var solid = { label: { color: text, textBorderWidth: 0, textBorderColor: "transparent", textShadowBlur: 0 } };
    return {
      color: palette,
      backgroundColor: "transparent",
      textStyle: { color: text },
      title: { textStyle: { color: text }, subtextStyle: { color: muted } },
      legend: { textStyle: { color: muted }, pageTextStyle: { color: muted } },
      categoryAxis: axisCommon,
      valueAxis: axisCommon,
      timeAxis: axisCommon,
      logAxis: axisCommon,
      visualMap: { textStyle: { color: muted } },
      tooltip: {
        backgroundColor: bg,
        borderColor: grid,
        textStyle: { color: text },
        confine: true,
        extraCssText: "max-width:min(22rem,90vw);white-space:normal;overflow-wrap:anywhere;"
      },
      bar: solid,
      line: solid,
      scatter: solid,
      pie: { itemStyle: { borderColor: bg, borderWidth: 1 }, label: solid.label },
      treemap: { itemStyle: { borderColor: bg }, label: { color: "#ffffff", textBorderWidth: 0 } },
      sunburst: { itemStyle: { borderColor: bg }, label: solid.label },
      gauge: { title: { color: muted }, detail: { color: text } },
      radar: { axisName: { color: muted }, splitLine: { lineStyle: { color: grid } }, axisLine: { lineStyle: { color: grid } } },
      heatmap: { label: solid.label },
      funnel: { label: solid.label, itemStyle: { borderColor: bg } }
    };
  }

  /** Resolve a colour map's tokens to colours. */
  function resolveColors(spec, t) {
    var out = { map: {}, field: spec.field || null, dflt: spec["default"] ? t.v(spec["default"], null) : null };
    Object.keys(spec.map || {}).forEach(function (k) { out.map[k] = t.v(spec.map[k], null); });
    return out;
  }

  function lookup(colors, key) {
    return key !== null && key !== undefined && HAS.call(colors.map, String(key)) ? colors.map[String(key)] : null;
  }

  /** Colour series named by a mapped value, and data items whose field / name is a mapped value. */
  function applyColors(option, colors) {
    var series = Array.isArray(option.series) ? option.series : option.series ? [option.series] : [];
    series.forEach(function (s) {
      if (s.itemStyle && s.itemStyle.color) return;
      var named = lookup(colors, s.name);
      if (named) {
        s.color = named;
        s.itemStyle = Object.assign({}, s.itemStyle, { color: named });
        return;
      }
      var pick = function (p) {
        var d = p && p.data, v = null;
        if (colors.field && d && !Array.isArray(d) && typeof d === "object") v = lookup(colors, d[colors.field]);
        if (!v) v = lookup(colors, p && p.name);
        return v || colors.dflt || (p && p.color);
      };
      var perItem = s.type === "pie" || s.type === "scatter" || s.type === "funnel" ||
        s.type === "treemap" || s.type === "sunburst" || (s.type === "bar" && (s.colorBy === "data" || colors.field));
      if (perItem) s.itemStyle = Object.assign({}, s.itemStyle, { color: pick });
    });
  }

  /** A series label the config declares gets the solid, outline-free defaults for whatever it leaves unset. */
  function solidLabels(option, t) {
    var text = t.v("text", "#0f172a");
    var series = Array.isArray(option.series) ? option.series : option.series ? [option.series] : [];
    series.forEach(function (s) {
      ["label", "emphasis", "select", "blur"].forEach(function (key) {
        var l = key === "label" ? s.label : s[key] && s[key].label;
        if (!l || typeof l !== "object") return;
        if (l.textBorderWidth === undefined) l.textBorderWidth = 0;
        if (l.textShadowBlur === undefined) l.textShadowBlur = 0;
        if (l.color === undefined && key === "label") l.color = text;
      });
    });
  }

  /** A same-origin path (never protocol-relative), judged on what the browser will navigate to. */
  function safePath(url) {
    if (typeof url !== "string" || url.charAt(0) !== "/") return false;
    try { return new URL(url, window.location.href).origin === window.location.origin; } catch (e) { return false; }
  }

  /** Click-through: a bar or scatter item whose row carries a server-filled `_url` navigates to it. */
  function wireClick(entry) {
    entry.chart.on("click", function (p) {
      var url = p && p.data && !Array.isArray(p.data) && typeof p.data === "object" ? p.data._url : null;
      if (!url || (p.seriesType !== "bar" && p.seriesType !== "scatter") || !safePath(url)) return;
      var ev = p.event && p.event.event;
      if (ev && (ev.ctrlKey || ev.metaKey)) window.open(url, "_blank", "noopener");
      else window.location.assign(url);
    });
  }

  function showError(root, message) {
    var box = root.querySelector(".tap-chart__error");
    if (box) { box.textContent = message; box.hidden = false; }
    var mount = root.querySelector(".tap-chart__mount");
    if (mount) mount.hidden = true;
  }

  function draw(entry) {
    var panel = entry.root.closest(".tap-panel--chart") || entry.root;
    var t = tokens(panel);
    echarts.registerTheme("tap-chart-theme", theme(t));
    if (entry.chart) entry.chart.dispose();
    var option = JSON.parse(JSON.stringify(entry.option));
    if (entry.colorSpec) applyColors(option, resolveColors(entry.colorSpec, t));
    solidLabels(option, t);
    // ECharts' generated description misreads dataset-encoded series; the server's label (what the chart
    // shows, how many rows) is the accessible name, and the hidden table carries the data.
    var label = entry.root.getAttribute("data-tap-chart-label");
    var aria = Object.assign({ enabled: true }, option.aria);
    if (label) aria.label = Object.assign({ description: label }, aria.label);
    option.aria = aria;
    entry.chart = echarts.init(entry.mount, "tap-chart-theme", { renderer: "canvas" });
    entry.chart.setOption(option);
    wireClick(entry);
  }

  function dispose(entry) {
    if (entry.ro) entry.ro.disconnect();
    if (entry.chart) entry.chart.dispose();
    live = live.filter(function (e) { return e !== entry; });
  }

  function init(root) {
    if (root.getAttribute("data-tap-chart-ready")) return;
    var mount = root.querySelector(".tap-chart__mount");
    try {
      if (!window.echarts) throw new Error("the charting library did not load");
      var entry = {
        root: root,
        mount: mount,
        option: JSON.parse(root.getAttribute("data-tap-chart-option")),
        colorSpec: root.hasAttribute("data-tap-chart-colors") ? JSON.parse(root.getAttribute("data-tap-chart-colors")) : null,
        chart: null,
        ro: null
      };
      draw(entry);
      if (window.ResizeObserver) {
        entry.ro = new ResizeObserver(function () {
          if (!root.isConnected) { dispose(entry); return; }
          if (entry.chart) entry.chart.resize();
        });
        entry.ro.observe(mount);
      }
      live.push(entry);
      root.setAttribute("data-tap-chart-ready", "1");
    } catch (err) {
      root.setAttribute("data-tap-chart-ready", "error");
      showError(root, "This chart could not be drawn: " + (err && err.message ? err.message : err));
    }
  }

  function redrawAll() {
    live.slice().forEach(function (entry) {
      if (!entry.root.isConnected) { dispose(entry); return; }
      try { draw(entry); } catch (err) { showError(entry.root, "This chart could not be redrawn: " + err.message); }
    });
  }

  function run(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    var nodes = root.querySelectorAll("[data-tap-chart]");
    for (var i = 0; i < nodes.length; i++) init(nodes[i]);
  }

  // Theme: the viewer's scheme, or an explicit data-theme / class on <html>.
  if (window.matchMedia) {
    var mq = window.matchMedia("(prefers-color-scheme: dark)");
    if (mq.addEventListener) mq.addEventListener("change", redrawAll);
  }
  if (window.MutationObserver) {
    new MutationObserver(redrawAll).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
  }
  window.addEventListener("resize", function () {
    live.forEach(function (e) { if (e.chart) e.chart.resize(); });
  });

  window.TapChart = { run: run, redraw: redrawAll, theme: theme, applyColors: applyColors, solidLabels: solidLabels, safePath: safePath };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { run(document); });
  } else {
    run(document);
  }
  document.addEventListener("htmx:afterSettle", function (evt) { run(evt.target || document); });
})();
