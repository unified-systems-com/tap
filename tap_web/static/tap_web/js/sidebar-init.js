// Structural sidebar state, applied before first paint (req-web-nav-sidebar).
// Blocking <script src> in <head>, like theme-init.js, so a collapsed rail never flashes open.
//
// localStorage `tap-sidebar` = "collapsed" | "expanded". Missing or unreadable: collapsed under 900px wide,
// expanded otherwise. The result is <html data-sidebar="collapsed|expanded">; sidebar.css reads it.
(function () {
  "use strict";
  var state = null;
  try {
    state = window.localStorage.getItem("tap-sidebar");
  } catch (e) {
    // storage blocked: fall through to the width default
  }
  if (state !== "collapsed" && state !== "expanded") {
    state = window.matchMedia && window.matchMedia("(max-width: 899px)").matches ? "collapsed" : "expanded";
  }
  document.documentElement.setAttribute("data-sidebar", state);
})();
