// Resource drawer (spec-web-drawer.md): one entity's data beside the list, without leaving it.
//
// Opened by a `tap:row-activate` event (a drawer-enabled table row, req-web-stdpanel-table-row-nav-5) or a plain
// click on any [data-tap-drawer="<fragment url>"] link. The body is the server-rendered fragment from
// /object/<type>/<url_id>/drawer/. State is in the URL (?drawer=<entity id>&drawer_type=<type>): opening pushes,
// Back undoes the last open or close. Non-modal: no focus trap, the page stays usable. Escape closes; focus
// returns to the opener.
(function () {
  "use strict";

  var region = null;
  var body = null;
  var opener = null;
  var currentKey = "";
  var token = 0;

  function fragmentUrl(entityType, entityId) {
    return "/object/" + encodeURIComponent(entityType) + "/--" + encodeURIComponent(entityId) + "/drawer/";
  }

  function readState() {
    var params = new URLSearchParams(window.location.search);
    var id = params.get("drawer");
    var type = params.get("drawer_type");
    return id && type ? { id: id, type: type } : null;
  }

  function writeState(entity, push) {
    var url = new URL(window.location.href);
    if (entity) {
      url.searchParams.set("drawer", entity.id);
      url.searchParams.set("drawer_type", entity.type);
    } else {
      url.searchParams.delete("drawer");
      url.searchParams.delete("drawer_type");
    }
    var state = entity ? { tapDrawer: true } : null;
    if (push) window.history.pushState(state, "", url);
    else window.history.replaceState(state, "", url);
  }

  function announce(entity) {
    document.dispatchEvent(new CustomEvent("tap:drawer-change", { detail: entity ? { entityId: entity.id } : {} }));
  }

  function show(url, entity, push) {
    var mine = ++token;
    region.hidden = false;
    region.setAttribute("aria-busy", "true");
    window.requestAnimationFrame(function () {
      region.classList.add("tap-drawer--in");
    });
    return fetch(url, { credentials: "same-origin", headers: { "HX-Request": "true" } })
      .then(function (response) {
        return response.text();
      })
      .then(function (html) {
        if (mine !== token) return;
        body.innerHTML = html;
        region.removeAttribute("aria-busy");
        var head = body.querySelector("[data-tap-drawer-entity]");
        var resolved = entity || (head ? { id: head.getAttribute("data-tap-drawer-entity"), type: head.getAttribute("data-tap-drawer-type") } : null);
        if (resolved) {
          var key = resolved.type + ":" + resolved.id;
          if (key !== currentKey) {
            currentKey = key;
            writeState(resolved, push);
          }
        }
        announce(resolved);
        var title = body.querySelector("#tap-drawer-title");
        if (title) title.focus({ preventScroll: true });
      })
      .catch(function () {
        if (mine !== token) return;
        region.removeAttribute("aria-busy");
        body.innerHTML = '<p class="tap-drawer-empty">The details could not be loaded. Check the connection and try again.</p>';
      });
  }

  function open(url, entity, from) {
    if (from) opener = from;
    return show(url, entity, true);
  }

  function hide() {
    token++;
    currentKey = "";
    region.classList.remove("tap-drawer--in");
    region.hidden = true;
    body.innerHTML = "";
    announce(null);
    if (opener && document.contains(opener)) opener.focus({ preventScroll: true });
    opener = null;
  }

  function close() {
    if (region.hidden) return;
    writeState(null, true); // a new entry, so Back reopens what was just closed
    hide();
  }

  function syncFromUrl() {
    var entity = readState();
    if (!entity) {
      if (!region.hidden) hide();
      return;
    }
    if (entity.type + ":" + entity.id === currentKey) return;
    currentKey = entity.type + ":" + entity.id;
    show(fragmentUrl(entity.type, entity.id), entity, false);
  }

  function plainClick(event) {
    return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
  }

  function init() {
    region = document.querySelector("[data-tap-drawer-region]");
    if (!region) return;
    body = region.querySelector("[data-tap-drawer-body]");

    document.addEventListener("tap:row-activate", function (event) {
      var d = event.detail || {};
      if (!d.entityId || !d.entityType) return;
      open(fragmentUrl(d.entityType, d.entityId), { id: String(d.entityId), type: String(d.entityType) }, d.opener || null);
    });

    document.addEventListener("click", function (event) {
      var link = event.target.closest("[data-tap-drawer]");
      if (link && plainClick(event)) {
        event.preventDefault();
        open(link.getAttribute("data-tap-drawer"), null, region.contains(link) ? opener : link);
        return;
      }
      if (event.target.closest("[data-tap-drawer-close]")) {
        close();
        return;
      }
      var tab = event.target.closest(".tap-drawer-tabs a");
      if (tab) {
        event.preventDefault();
        var target = body.querySelector(tab.getAttribute("href"));
        if (target) target.scrollIntoView({ block: "start" });
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape" || region.hidden) return;
      var t = event.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT") && !region.contains(t)) return;
      if (document.querySelector(".tap-palette-overlay.is-open")) return;
      close();
    });

    window.addEventListener("popstate", syncFromUrl);
    syncFromUrl();
  }

  window.tapDrawer = {
    open: function (entityType, entityId, from) {
      if (!region) return null;
      return open(fragmentUrl(entityType, entityId), { id: String(entityId), type: String(entityType) }, from || null);
    },
    close: function () {
      if (region) close();
    },
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
