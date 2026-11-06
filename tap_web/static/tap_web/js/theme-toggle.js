// Theme switch (spec-web-theme.md, req-web-theme-toggle). Wires every `[data-tap-theme-switch]` group: its buttons carry
// `data-tap-theme-set="light|dark|auto"`. A click stores the choice (localStorage `theme`, guarded -- storage may be
// blocked), applies it to <html>, marks the pressed button, and announces `tap:themechange` on document so canvas-drawn
// surfaces (charts, the graph) can re-read their tokens. A change made in another tab, or by the OS while the mode
// is "auto", is followed too.
(function () {
  "use strict";
  var KEY = "theme";
  var root = document.documentElement;
  var media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function stored() {
    try {
      var v = window.localStorage.getItem(KEY);
      return v === "light" || v === "dark" ? v : "auto";
    } catch (e) {
      return root.getAttribute("data-theme-mode") || "auto";
    }
  }

  function effective(mode) {
    if (mode === "light" || mode === "dark") return mode;
    return media && media.matches ? "dark" : "light";
  }

  function paint(mode) {
    if (mode === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", mode);
    root.setAttribute("data-theme-mode", mode);
    document.querySelectorAll("[data-tap-theme-set]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-tap-theme-set") === mode ? "true" : "false");
    });
    document.dispatchEvent(new CustomEvent("tap:themechange", { detail: { mode: mode, scheme: effective(mode) } }));
  }

  function choose(mode) {
    try {
      if (mode === "auto") window.localStorage.removeItem(KEY);
      else window.localStorage.setItem(KEY, mode);
    } catch (e) {
      // not persisted; still applied for this page view
    }
    paint(mode);
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-tap-theme-set]");
    if (b) choose(b.getAttribute("data-tap-theme-set"));
  });
  window.addEventListener("storage", function (e) {
    if (e.key === KEY || e.key === null) paint(stored());
  });
  if (media && media.addEventListener) {
    media.addEventListener("change", function () {
      if (stored() === "auto") paint("auto");
    });
  }

  // Reflect the already-applied mode on the buttons (theme-init.js set the attribute; this only marks them).
  var mode = root.getAttribute("data-theme-mode") || stored();
  document.querySelectorAll("[data-tap-theme-set]").forEach(function (b) {
    b.setAttribute("aria-pressed", b.getAttribute("data-tap-theme-set") === mode ? "true" : "false");
  });
})();
