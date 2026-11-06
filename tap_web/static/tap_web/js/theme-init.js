// Colour theme, applied before first paint (spec-web-theme.md, req-web-theme-init).
// Loaded as a plain blocking <script src> in <head> -- external, so it needs no CSP exception, and blocking, so
// <html data-theme> is set before the stylesheet paints and a dark viewer never sees a light flash.
//
// The choice is localStorage `theme` = "light" | "dark" | "auto" (the key and values Django admin's own toggle
// uses, so the admin follows the app). "auto" -- and anything missing, unreadable or unrecognised -- is the
// viewer's `prefers-color-scheme`: the attribute is then left off and the CSS media query decides.
(function () {
  "use strict";
  var mode = "auto";
  try {
    var saved = window.localStorage.getItem("theme");
    if (saved === "light" || saved === "dark") mode = saved;
  } catch (e) {
    // storage blocked (private window, site data blocked): fall back to the system scheme
  }
  var root = document.documentElement;
  if (mode === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", mode);
  root.setAttribute("data-theme-mode", mode);
})();
