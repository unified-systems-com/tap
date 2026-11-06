/**
 * Command palette per req-web-nav-command-palette.
 *
 * Cmd-K / Ctrl-K (or the chrome affordance button) opens a centered modal
 * with a fuzzy-search input. Results stream from /__nav-index.json on
 * first open and cache for the session. Clicking a result (or pressing
 * Enter on the highlighted row) navigates. Esc / click-outside closes.
 *
 * v0 scope: registered Pages only. Entities, recent visits, and platform
 * commands are spec'd as later additions; this MVP just answers the
 * "what pages exist?" question that drove the rollout.
 */
(function () {
  "use strict";

  let navIndex = null;       // Cached nav-index data; populated on first open.
  let modal = null;          // The palette modal element.
  let input = null;          // The search input.
  let resultsList = null;    // The results list element.
  let selectedIndex = 0;     // Currently highlighted result.
  let currentResults = [];   // Most recent result set.

  // -------------------------------------------------------------------------
  // Fuzzy match scoring.
  // -------------------------------------------------------------------------
  // For an empty query: return all pages, sorted alphabetically by URL.
  // For a non-empty query: tiered scoring — exact > prefix > substring >
  // subsequence > URL substring > description substring. Top 10 returned.

  function isSubsequence(needle, haystack) {
    let i = 0;
    for (const c of haystack) {
      if (c === needle[i]) i++;
      if (i === needle.length) return true;
    }
    return false;
  }

  function scorePage(page, q) {
    const name = (page.name || "").toLowerCase();
    const url = (page.url || "").toLowerCase();
    const desc = (page.description || "").toLowerCase();
    if (name === q) return 1000;
    if (name.startsWith(q)) return 800;
    if (name.includes(q)) return 600;
    if (isSubsequence(q, name)) return 400;
    if (url.includes(q)) return 300;
    if (desc.includes(q)) return 100;
    return 0;
  }

  function rankPages(query) {
    if (!navIndex) return [];
    if (!query) {
      // Empty query — return the tree form. Each entry carries a `_depth`
      // marker the renderer uses to indent under the parent.
      return treePages();
    }
    const q = query.toLowerCase();
    // Ranked search: fuzzy score dominates; nav_weight acts as a tiebreaker
    // boost (~5pts per weight unit) per req-web-nav-page-weight — high
    // priority edges out equal-score items but doesn't override a clearly
    // better fuzzy match. Cap the boost contribution so a +999 admin page
    // can't beat a tight fuzzy hit on an unweighted page.
    const scored = navIndex.pages
      .map((page) => {
        const base = scorePage(page, q);
        if (base === 0) return null;
        const boost = Math.max(-100, Math.min(100, (page.nav_weight || 0) * 5));
        return { score: base + boost, page };
      })
      .filter((entry) => entry !== null)
      .sort((a, b) => b.score - a.score);
    return scored.slice(0, 10).map((entry) => entry.page);
  }

  /** Empty-query mode: list every page in document-order, nested under its parent.
   *
   *  Each page's parent is its breadcrumb's second-to-last segment URL.
   *  Children are rendered immediately after their parent and indented by
   *  their depth. The renderer uses the `_depth` marker to decide indent.
   */
  function treePages() {
    if (!navIndex) return [];
    const byParent = new Map();
    navIndex.pages.forEach((p) => {
      if (p.breadcrumb.length < 2) return; // skip a page registered at "/"
      const parent = p.breadcrumb[p.breadcrumb.length - 2].url;
      if (!byParent.has(parent)) byParent.set(parent, []);
      byParent.get(parent).push(p);
    });
    // Within each parent's children: sort by `nav_weight DESC, name ASC` per
    // req-web-nav-page-weight. Higher weight floats up; ties alphabetical.
    const out = [];
    const walk = (parentUrl, depth) => {
      const children = (byParent.get(parentUrl) || [])
        .slice()
        .sort(
          (a, b) =>
            (b.nav_weight || 0) - (a.nav_weight || 0) ||
            (a.name || a.url).localeCompare(b.name || b.url)
        );
      children.forEach((c) => {
        out.push({ ...c, _depth: depth });
        walk(c.url, depth + 1);
      });
    };
    walk("/", 0);
    return out;
  }

  // -------------------------------------------------------------------------
  // Modal DOM.
  // -------------------------------------------------------------------------

  function createModal() {
    const overlay = document.createElement("div");
    overlay.className = "tap-palette-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "Command palette");

    const box = document.createElement("div");
    box.className = "tap-palette-box";

    input = document.createElement("input");
    input.type = "text";
    input.className = "tap-palette-input";
    input.setAttribute("placeholder", "Search pages…");
    input.setAttribute("aria-label", "Search pages");
    input.setAttribute("autocomplete", "off");
    input.setAttribute("autocorrect", "off");
    input.setAttribute("autocapitalize", "off");
    input.setAttribute("spellcheck", "false");

    resultsList = document.createElement("ul");
    resultsList.className = "tap-palette-results";
    resultsList.setAttribute("role", "listbox");

    box.appendChild(input);
    box.appendChild(resultsList);
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    // Click-outside dismisses.
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closePalette();
    });
    input.addEventListener("input", () => renderResults());
    input.addEventListener("keydown", handleKeyNav);

    return overlay;
  }

  function renderResults() {
    const query = input.value;
    currentResults = rankPages(query);
    resultsList.innerHTML = "";
    selectedIndex = 0;

    if (currentResults.length === 0) {
      const li = document.createElement("li");
      li.className = "tap-palette-empty";
      li.textContent = navIndex ? "No pages match" : "Loading pages…";
      resultsList.appendChild(li);
      return;
    }

    currentResults.forEach((page, i) => {
      const li = document.createElement("li");
      li.className = "tap-palette-result" + (i === 0 ? " is-selected" : "");
      li.setAttribute("role", "option");
      li.setAttribute("data-url", page.url);
      // Tree-mode indent: empty-query results carry `_depth` so the renderer
      // can offset them under their parent. Typed-query results don't carry
      // depth — they render flat.
      if (typeof page._depth === "number") {
        li.style.paddingLeft = `${0.5 + page._depth * 1.25}rem`;
      }

      const name = document.createElement("span");
      name.className = "tap-palette-result-name";
      name.textContent = page.name || page.url;

      const url = document.createElement("span");
      url.className = "tap-palette-result-url";
      url.textContent = page.url;

      li.appendChild(name);
      li.appendChild(url);

      li.addEventListener("click", (e) => navigate(page.url, e));
      li.addEventListener("mouseenter", () => {
        selectedIndex = i;
        updateSelection();
      });

      resultsList.appendChild(li);
    });
  }

  function updateSelection() {
    const items = resultsList.querySelectorAll(".tap-palette-result");
    items.forEach((item, i) => {
      if (i === selectedIndex) item.classList.add("is-selected");
      else item.classList.remove("is-selected");
    });
    if (items[selectedIndex]) {
      items[selectedIndex].scrollIntoView({ block: "nearest" });
    }
  }

  function handleKeyNav(e) {
    if (e.key === "Escape") {
      closePalette();
      e.preventDefault();
    } else if (e.key === "ArrowDown") {
      selectedIndex = Math.min(selectedIndex + 1, currentResults.length - 1);
      updateSelection();
      e.preventDefault();
    } else if (e.key === "ArrowUp") {
      selectedIndex = Math.max(selectedIndex - 1, 0);
      updateSelection();
      e.preventDefault();
    } else if (e.key === "Enter") {
      const page = currentResults[selectedIndex];
      if (page) navigate(page.url, e);
      e.preventDefault();
    }
  }

  // Cmd-click (macOS) or Ctrl-click (elsewhere), and Cmd/Ctrl+Enter, open the page in a new tab, the way a
  // link does; a plain click or Enter navigates in place. The URL comes from the same-origin nav index.
  function navigate(url, event) {
    if (event && (event.metaKey || event.ctrlKey)) {
      window.open(url, "_blank", "noopener");
      return;
    }
    window.location.href = url;
  }

  async function loadNavIndex() {
    if (navIndex) return;
    try {
      const response = await fetch("/__nav-index.json");
      navIndex = await response.json();
    } catch (e) {
      console.error("Failed to load nav index:", e);
      navIndex = { pages: [] };
    }
  }

  async function openPalette() {
    if (!modal) modal = createModal();
    modal.classList.add("is-open");
    input.value = "";
    // Initial render gives the loading-state message until fetch resolves.
    renderResults();
    input.focus();
    if (!navIndex) await loadNavIndex();
    renderResults();
  }

  function closePalette() {
    if (modal) modal.classList.remove("is-open");
  }

  // -------------------------------------------------------------------------
  // Wire Cmd-K / Ctrl-K and the chrome affordance.
  // -------------------------------------------------------------------------

  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      openPalette();
      e.preventDefault();
    }
  });

  function wireAffordance() {
    const btn = document.querySelector("[data-tap-palette-affordance]");
    if (btn) {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        openPalette();
      });
      // The template's ⌘K hint is the no-JS default; non-Mac platforms trigger
      // via ctrlKey, so relabel to the shortcut those users actually press.
      const isMac = /mac|iphone|ipad|ipod/i.test(
        (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || ""
      );
      if (!isMac) {
        btn.title = "Search pages (Ctrl+K)";
        const kbd = btn.querySelector(".tap-palette-affordance-kbd");
        if (kbd) kbd.textContent = "Ctrl+K";
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wireAffordance);
  } else {
    wireAffordance();
  }
})();
