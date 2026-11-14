// Structural sidebar behaviour (req-web-nav-sidebar): the collapse toggle and the per-group expanders.
// The tree itself is server-rendered from the nav index; nothing here adds or removes items.
(function () {
  "use strict";

  function setCollapsed(root, collapsed, button) {
    root.setAttribute("data-sidebar", collapsed ? "collapsed" : "expanded");
    if (button) {
      button.setAttribute("aria-expanded", collapsed ? "false" : "true");
      button.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
    }
    try {
      window.localStorage.setItem("tap-sidebar", collapsed ? "collapsed" : "expanded");
    } catch (e) {
      // storage blocked: the choice lasts for this page only
    }
  }

  function init() {
    var aside = document.querySelector("[data-tap-sidebar]");
    if (!aside) return;
    var root = document.documentElement;
    var collapse = aside.querySelector("[data-tap-sb-collapse]");
    if (collapse) {
      var collapsed = root.getAttribute("data-sidebar") === "collapsed";
      collapse.setAttribute("aria-expanded", collapsed ? "false" : "true");
      collapse.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
      collapse.addEventListener("click", function () {
        setCollapsed(root, root.getAttribute("data-sidebar") !== "collapsed", collapse);
      });
    }
    aside.addEventListener("click", function (event) {
      var toggle = event.target.closest("[data-tap-sb-toggle]");
      if (!toggle) return;
      if (root.getAttribute("data-sidebar") === "collapsed") {
        setCollapsed(root, false, collapse);
      }
      var list = document.getElementById(toggle.getAttribute("aria-controls"));
      if (!list) return;
      var open = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      list.hidden = !open;
    });
    var current = aside.querySelector('[aria-current="page"]');
    if (current && current.scrollIntoView) current.scrollIntoView({ block: "nearest" });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
