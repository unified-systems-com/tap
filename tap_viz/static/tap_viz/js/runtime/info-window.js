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
const WIDE_CLASS = "tap-info-window--wide";
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
    // A badge set with a multi-column table (req-viz-info-window-columns-9) widens the window to its
    // content, between the fixed 280px and a 560px cap; otherwise the width stays fixed.
    const wide = badgeSets.some((s) => _columnCount(s.info_window) > 1);
    if (wide) el.classList.add(WIDE_CLASS);
    _positionFromHost(el, panelEl, host, wide);
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
                // Parsed into an inert document and adopted, not assigned as markup: every cell
                // value is already escaped by renderInfoTable, and this keeps the page free of an
                // innerHTML sink for row data.
                const parsed = new DOMParser().parseFromString(
                    renderInfoTable(hostRows, cfg.info_window),
                    "text/html",
                );
                bodyEl.replaceChildren(...parsed.body.childNodes);
                _wireRowLinks(bodyEl);
                if (state.el.classList.contains(WIDE_CLASS)) _fitWithinPanel(state.el, state.panelEl);
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

/** Number of columns an `info_window` block renders; 1 for the legacy Name column. */
function _columnCount(infoWindowCfg) {
    const cols = infoWindowCfg && infoWindowCfg.columns;
    return Array.isArray(cols) && cols.length > 0 ? cols.length : 1;
}

/**
 * Render one section's table (req-viz-info-window-columns).
 *
 * Without `info_window.columns` this is the legacy single Name column with no visible header
 * (req-viz-info-window-columns-3). With it, a real table with a header row of the configured labels.
 */
export function renderInfoTable(rows, infoWindowCfg) {
    const cfg = infoWindowCfg || {};
    if (Array.isArray(cfg.columns) && cfg.columns.length > 0) {
        return _renderColumnsTable(rows, cfg.columns, cfg.row_url_template);
    }
    return _renderTable(rows, cfg.row_url_template);
}

const TONES = ["good", "warn", "bad", "muted", "info"];

/**
 * A fraction 0..1 as a percentage (0.0004 -> "0.04%"), or null when the value is not such a fraction.
 * `decimals` is 0..6 and defaults to 2.
 */
function _percentText(value, decimals) {
    const n = typeof value === "number" ? value : Number(value);
    if (typeof value === "boolean" || !Number.isFinite(n) || n < 0 || n > 1) return null;
    const d = Number.isInteger(decimals) && decimals >= 0 && decimals <= 6 ? decimals : 2;
    return `${(Math.round(n * 10 ** (d + 2)) / 10 ** d).toFixed(d)}%`;
}

/** The tone of a numeric value from `tone_steps` (highest min first) or `zero_tone`; null when none applies. */
function _toneFor(value, col) {
    if (!Array.isArray(col.tone_steps) || value === null || value === undefined || value === "") return null;
    const n = typeof value === "number" ? value : Number(value);
    if (typeof value === "boolean" || !Number.isFinite(n)) return null;
    if (n === 0 && TONES.includes(col.zero_tone)) return col.zero_tone;
    const steps = col.tone_steps
        .filter((st) => st && typeof st.min === "number" && TONES.includes(st.tone))
        .sort((a, b) => b.min - a.min);
    const hit = steps.find((st) => n >= st.min);
    return hit ? hit.tone : null;
}

function _cellText(value, format, decimals) {
    // Missing is an empty cell, never the string "undefined" (req-viz-info-window-columns-5).
    if (value === null || value === undefined || value === "") return "";
    if (format === "number") {
        // One decimal place (req-viz-info-window-columns-7); a value that is not a number is shown
        // as given rather than hidden, so bad data stays visible.
        const n = typeof value === "number" ? value : Number(value);
        if (Number.isFinite(n)) return n.toFixed(1);
    }
    if (format === "percent") {
        // A value that is not a 0..1 fraction is shown as given, so bad data stays visible.
        const shown = _percentText(value, decimals);
        if (shown !== null) return shown;
    }
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
}

function _renderColumnsTable(rows, columns, rowUrlTemplate) {
    // The row link goes on the first column marked `link: true`, else on the first column
    // (req-viz-info-window-columns-6). The finding_id fallback of the legacy Name column does not
    // apply here: a configured table states its own link, or has none.
    const flagged = columns.findIndex((c) => c && c.link === true);
    const linkIdx = flagged >= 0 ? flagged : 0;
    const cellClass = (c) => (c.align === "right" ? ' class="tap-info-window__cell--right"' : "");
    // `nowrap: true` keeps a cell's text on one line (req-viz-info-window-columns-11); body cells only,
    // so a long header label may still wrap. Absent or false leaves the markup untouched.
    const bodyCellClass = (c) => {
        const classes = [];
        if (c.align === "right") classes.push("tap-info-window__cell--right");
        if (c.nowrap === true) classes.push("tap-info-window__cell--nowrap");
        return classes.length ? ` class="${classes.join(" ")}"` : "";
    };
    const head = columns
        .map((c) => `<th scope="col"${cellClass(c)}>${_escape(c.label)}</th>`)
        .join("");
    const body = rows
        .map((r) => {
            const tds = columns
                .map((c, i) => {
                    const text = _escape(_cellText(r[c.field], c.format, c.decimals));
                    const url = i === linkIdx && text !== "" ? _buildRowUrl(rowUrlTemplate, r) : null;
                    let inner = url ? `<a class="tap-info-window__row-link" href="${url}">${text}</a>` : text;
                    // tone_steps (req-viz-info-window-columns-16): a numeric value is drawn as a toned badge.
                    const tone = text !== "" ? _toneFor(r[c.field], c) : null;
                    if (tone) {
                        inner = `<span class="tap-info-window__tone tap-info-window__tone--${tone}" title="${tone}">${inner}</span>`;
                    }
                    return `<td${bodyCellClass(c)}>${inner}</td>`;
                })
                .join("");
            return `<tr>${tds}</tr>`;
        })
        .join("");
    return `
        <table class="tap-info-window__table tap-info-window__table--columns">
            <thead><tr>${head}</tr></thead>
            <tbody>${body}</tbody>
        </table>
    `;
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

function _positionFromHost(el, panelEl, host, wide) {
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
    // Wide windows size to their content in CSS (.tap-info-window--wide); _fitWithinPanel re-clamps
    // the left edge once the table is in.
    if (!wide) el.style.width = `${DEFAULT_WIDTH_PX}px`;
    el.style.maxHeight = `${maxHeight}px`;
}

function _fitWithinPanel(el, panelEl) {
    const overflow = el.offsetLeft + el.offsetWidth - panelEl.clientWidth;
    if (overflow > 0) el.style.left = `${Math.max(0, el.offsetLeft - overflow)}px`;
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
