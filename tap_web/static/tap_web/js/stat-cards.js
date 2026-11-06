/**
 * stat-cards.js -- finishes the viewer-dependent cells of the Stat Cards panel
 * (req-web-stdpanel-statcards-age).
 *
 * The server renders <time data-tap-age datetime="ISO-UTC" title="ISO-UTC">ISO</time>.
 * This script replaces the text with the elapsed time against NOW in the
 * browser ("19 days", "3 hours") and the tooltip with the exact timestamp in
 * the shared localtime format (TapLocalTime). `datetime` cells are not handled
 * here: localtime.js already localizes every <time data-tap-localtime>.
 *
 * It names no field, panel or tool: it only reads the attributes above.
 */
(function () {
  "use strict";

  var MIN = 60, HOUR = 3600, DAY = 86400, MONTH = 30 * DAY, YEAR = 365 * DAY;

  function plural(n, unit) {
    return n + " " + unit + (n === 1 ? "" : "s");
  }

  /** Elapsed seconds (may be negative: a future instant) as short human text. */
  function formatAge(seconds) {
    var future = seconds < 0;
    var s = Math.abs(seconds);
    var text;
    if (s < MIN) text = "under a minute";
    else if (s < HOUR) text = plural(Math.floor(s / MIN), "minute");
    else if (s < DAY) text = plural(Math.floor(s / HOUR), "hour");
    else if (s < 60 * DAY) text = plural(Math.floor(s / DAY), "day");
    else if (s < YEAR) text = plural(Math.floor(s / MONTH), "month");
    else text = plural(Math.floor(s / YEAR), "year");
    return future && s >= MIN ? "in " + text : text;
  }

  function render(root, nowMs) {
    var scope = root && root.querySelectorAll ? root : document;
    var nodes = scope.querySelectorAll("time[data-tap-age]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var iso = el.getAttribute("datetime");
      var t = new Date(iso).getTime();
      if (!iso || isNaN(t)) continue; // leave the server text: the raw value, never blank
      el.textContent = formatAge((nowMs - t) / 1000);
      el.setAttribute(
        "title",
        window.TapLocalTime ? window.TapLocalTime.format(iso).title : iso
      );
    }
  }

  /**
   * Mark each closed longtext value that already fits its line limit (data-fits), so it does not offer a
   * "Show all" that would reveal nothing. Without this script every longtext offers the toggle: nothing is hidden.
   */
  function markFits(root) {
    var scope = root && root.querySelectorAll ? root : document;
    var boxes = scope.querySelectorAll("details.tap-statcard__longtext:not([open])");
    for (var i = 0; i < boxes.length; i++) {
      var text = boxes[i].querySelector(".tap-statcard__longtext-text");
      if (text && text.clientHeight > 0 && text.scrollHeight <= text.clientHeight + 1) boxes[i].setAttribute("data-fits", "");
    }
  }

  function run(root) {
    render(root, Date.now());
    markFits(root);
  }

  window.TapStatCards = { formatAge: formatAge, render: run, markFits: markFits };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { run(document); });
  } else {
    run(document);
  }
  // Panels arrive by HTMX swap; ages also drift, so refresh them once a minute.
  document.addEventListener("htmx:afterSettle", function (evt) { run(evt.target || document); });
  setInterval(function () { run(document); }, 60000);
})();
