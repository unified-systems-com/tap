/**
 * info-window.js — Status badge detail window for TAP Viz.
 *
 * Opens an HTML overlay next to a host node when a badge (or the host itself)
 * is clicked. The window shows one section per configured badge set, listing
 * rows returned by that set's detail Search. Rows are keyed by entity_id so the
 * window filters client-side to the clicked host's entries — matching the
 * count-search pattern used by status-badges.js.
 *
 * Rendering is a plain <div> overlay positioned from the host's rendered
 * Cytoscape coordinates. No popper/floating-ui dependency. The window is
 * created on open, removed on close; it does not follow the node on pan/zoom.
 *
 * Dismissal: X button, ESC key, and click-outside all dismiss cleanly. Opening
 * a new window closes the previous one. Clicking the originating host or
 * badge again also dismisses (toggle).
 *
 * Spec: tap_viz/specs/spec-viz-status-badge-info.md
 */

const WINDOW_CLASS = "tap-info-window";
const DEFAULT_OFFSET_PX = 12;
const DEFAULT_WIDTH_PX = 280;
const DEFAULT_MAX_HEIGHT_RATIO = 0.6;

let _activeWindow = null;

/**
 * Open (or toggle) the info window for a host.
 *
 * @param {cytoscape.Core} cy
 * @param {HTMLElement} panelEl The panel container (used as overlay parent).
 * @param {cytoscape.NodeSingular} host The host node the badges belong to.
 * @param {Object} statusBadgesConfig The `status_badges` projection block.
 */
export function openInfoWindow(cy, panelEl, host, statusBadgesConfig) {
    if (!cy || !panelEl || !host || !statusBadgesConfig) return;

    // Toggle: reopening on the same host closes the window.
    if (_activeWindow && _activeWindow.hostId === host.id()) {
        closeInfoWindow();
        return;
    }

    // Replacing: any open window dismisses before the new one appears.
    closeInfoWindow();

    const badgeSets = Array.isArray(statusBadgesConfig.badge_sets)
        ? statusBadgesConfig.badge_sets.filter((s) => s && s.info_window && s.info_window.search_id)
        : [];
    if (badgeSets.length === 0) return;

    const el = document.createElement("div");
    el.className = WINDOW_CLASS;
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-label", "Finding details");
    _positionFromHost(el, panelEl, host);
    el.innerHTML = _renderShell(host);
    panelEl.appendChild(el);

    const state = {
        hostId: host.id(),
        el,
        panelEl,
        keydown: null,
        outsideClick: null,
        destroyed: false,
    };
    _activeWindow = state;

    el.querySelector(".tap-info-window__close").addEventListener("click", (e) => {
        e.stopPropagation();
        closeInfoWindow();
    });

    state.keydown = (e) => {
        if (e.key === "Escape") closeInfoWindow();
    };
    document.addEventListener("keydown", state.keydown);

    // One tick delay so the triggering click doesn't immediately dismiss via
    // the click-outside listener.
    setTimeout(() => {
        if (state.destroyed) return;
        state.outsideClick = (e) => {
            if (!state.el) return;
            if (state.el.contains(e.target)) return;
            closeInfoWindow();
        };
        document.addEventListener("click", state.outsideClick, true);
    }, 0);

    _loadSections(state, host, badgeSets).catch((err) => {
        console.warn("[info-window] load failed:", err);
    });
}

/** Close the currently open info window, if any. */
export function closeInfoWindow() {
    if (!_activeWindow) return;
    const state = _activeWindow;
    _activeWindow = null;
    state.destroyed = true;
    if (state.keydown) document.removeEventListener("keydown", state.keydown);
    if (state.outsideClick) document.removeEventListener("click", state.outsideClick, true);
    if (state.el && state.el.parentNode) state.el.parentNode.removeChild(state.el);
}

function _renderShell(host) {
    // Host data uses `label` as the display string (populated by panel-graph.js
    // from entity.name); fall back to the node id if neither is set.
    const title = _escape(host.data("label") || host.data("name") || host.id());
    const entityType = _escape(host.data("entity_type") || "");
    return `
        <div class="tap-info-window__header">
            <div class="tap-info-window__title">
                <div class="tap-info-window__name">${title}</div>
                <div class="tap-info-window__type">${entityType}</div>
            </div>
            <button type="button" class="tap-info-window__close" aria-label="Close">×</button>
        </div>
        <div class="tap-info-window__body"></div>
    `.trim();
}

async function _loadSections(state, host, badgeSets) {
    const hostId = host.id();
    const body = state.el.querySelector(".tap-info-window__body");
    if (!body) return;

    // Kick off one fetch per configured badge set, in parallel.
    const sections = badgeSets.map((cfg, idx) => {
        const sectionEl = document.createElement("section");
        sectionEl.className = "tap-info-window__section";
        sectionEl.dataset.setName = cfg.name;
        const headerLabel = cfg.label || cfg.name;
        sectionEl.innerHTML = `
            <div class="tap-info-window__section-header">
                <span class="tap-info-window__dot"></span>
                <span class="tap-info-window__set-name">${_escape(headerLabel)}</span>
                <span class="tap-info-window__count"></span>
            </div>
            <div class="tap-info-window__section-body">
                <div class="tap-info-window__loading">Loading…</div>
            </div>
        `;
        const dot = sectionEl.querySelector(".tap-info-window__dot");
        dot.style.backgroundColor = cfg.color || "#999";
        body.appendChild(sectionEl);
        return {cfg, sectionEl};
    });

    let anyRendered = false;

    await Promise.all(
        sections.map(async ({cfg, sectionEl}) => {
            const bodyEl = sectionEl.querySelector(".tap-info-window__section-body");
            const countEl = sectionEl.querySelector(".tap-info-window__count");
            try {
                const rows = await _runSearch(cfg.info_window);
                if (state.destroyed) return;
                const hostRows = rows.filter((r) => String(r.entity_id) === String(hostId));
                if (hostRows.length === 0) {
                    sectionEl.remove();
                    return;
                }
                anyRendered = true;
                countEl.textContent = String(hostRows.length);
                bodyEl.innerHTML = _renderTable(hostRows, cfg.info_window.row_url_template);
                _wireRowLinks(bodyEl);
            } catch (err) {
                if (state.destroyed) return;
                console.warn(`[info-window] section '${cfg.name}' failed:`, err);
                bodyEl.innerHTML = `<div class="tap-info-window__error">Failed to load.</div>`;
                countEl.textContent = "!";
                anyRendered = true;
            }
        }),
    );

    if (!anyRendered && !state.destroyed) {
        // Stale count — no rows to show. Close silently.
        closeInfoWindow();
    }
}

function _renderTable(rows, rowUrlTemplate) {
    // A configured row_url_template (req-viz-info-window-row-link) takes priority
    // over the finding_id fallback below: two badge sets from different plugins
    // can both return a `finding_id` field, and only the template knows which
    // route that id actually belongs to.
    //
    // Legacy fallback: when a row carries finding_id and no template is
    // configured, wrap the label in a click-through to the finding profile.
    // Styling stays inline (no underline / no link blue) — see
    // `.tap-info-window__row-link` in panel-graph.css.
    const cells = rows
        .map((r) => {
            const label = _escape(r.name || r.entity_id || "");
            const templated = _buildRowUrl(rowUrlTemplate, r);
            if (templated) {
                return `<tr><td><a class="tap-info-window__row-link" href="${templated}">${label}</a></td></tr>`;
            }
            if (!rowUrlTemplate && r.finding_id) {
                const href = `/fedramp-ksi/finding?entity_id=${encodeURIComponent(r.finding_id)}`;
                return `<tr><td><a class="tap-info-window__row-link" href="${href}">${label}</a></td></tr>`;
            }
            return `<tr><td>${label}</td></tr>`;
        })
        .join("");
    return `
        <table class="tap-info-window__table">
            <thead><tr><th>Name</th></tr></thead>
            <tbody>${cells}</tbody>
        </table>
    `;
}

/**
 * Stop a row link's click from bubbling to the document-level click-outside
 * listener (req-viz-info-window-row-link): that listener already ignores a
 * click inside the window element, but the anchor's default navigation still
 * races the same event on some browsers' back-forward cache / SPA-style
 * intercepts, so the window's own teardown must not run first and detach the
 * anchor out from under the click.
 */
function _wireRowLinks(container) {
    container.querySelectorAll(".tap-info-window__row-link").forEach((a) => {
        a.addEventListener("click", (e) => e.stopPropagation());
    });
}

const _PLACEHOLDER = /\{([A-Za-z0-9_]+)\}/g;

/**
 * Fill a same-origin `row_url_template` from one row's fields (req-viz-info-window-row-link).
 *
 * Mirrors tap_web's table_panel `_with_row_urls`: every `{field}` placeholder
 * must resolve to a present, non-empty value on the row, or no URL is built
 * at all — a half-built link is worse than none. Values are URL-encoded as
 * one path/query segment, so nothing a row contains can change the URL's shape.
 */
function _buildRowUrl(template, row) {
    if (!template) return null;
    const aliases = [...template.matchAll(_PLACEHOLDER)].map((m) => m[1]);
    for (const alias of aliases) {
        const value = row[alias];
        if (value === null || value === undefined || value === "") return null;
    }
    let url = template;
    for (const alias of aliases) {
        url = url.replaceAll(`{${alias}}`, encodeURIComponent(String(row[alias])));
    }
    return _escape(url);
}

async function _runSearch(infoWindowCfg) {
    const searchId = infoWindowCfg.search_id;
    const inputs = infoWindowCfg.inputs || {};
    const url = `/api/v1/searches/${searchId}/execute`;
    const csrfToken = _readCsrfToken();
    const headers = {"Content-Type": "application/json"};
    if (csrfToken) headers["X-CSRFToken"] = csrfToken;
    const res = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify({inputs}),
        credentials: "same-origin",
    });
    if (!res.ok) {
        throw new Error(`search fetch ${searchId} returned HTTP ${res.status}`);
    }
    const data = await res.json();
    return Array.isArray(data.rows) ? data.rows : [];
}

function _positionFromHost(el, panelEl, host) {
    const rpos = host.renderedPosition();
    const rw = host.renderedWidth();
    const rh = host.renderedHeight();
    const panelRect = panelEl.getBoundingClientRect();

    // Host's upper-right rendered point inside the panel.
    const rightX = rpos.x + rw / 2 + DEFAULT_OFFSET_PX;
    const topY = rpos.y - rh / 2;

    const maxHeight = Math.floor(panelRect.height * DEFAULT_MAX_HEIGHT_RATIO);

    // Clamp so the window stays inside the panel viewport.
    const clampedLeft = Math.min(
        Math.max(0, rightX),
        Math.max(0, panelRect.width - DEFAULT_WIDTH_PX),
    );
    const clampedTop = Math.min(
        Math.max(0, topY),
        Math.max(0, panelRect.height - 40),
    );

    el.style.position = "absolute";
    el.style.left = `${clampedLeft}px`;
    el.style.top = `${clampedTop}px`;
    el.style.width = `${DEFAULT_WIDTH_PX}px`;
    el.style.maxHeight = `${maxHeight}px`;
}

function _readCsrfToken() {
    // base.html's meta tag, not the cookie: its name is per stack (tap#773).
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : null;
}

function _escape(s) {
    return String(s == null ? "" : s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}
