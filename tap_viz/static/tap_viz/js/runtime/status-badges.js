/**
 * status-badges.js — Status badge set rendering for TAP Viz.
 *
 * Renders per-node status badges (alert, warn, and other named state
 * signals) in the upper-right corner of each host, left-to-right in
 * declaration order of the projection's status_badges.badge_sets array.
 * An array (not an object) is used so declaration order survives through
 * Postgres JSONB storage, which does not preserve JSON object key order.
 *
 * Each badge set declares a color, text color, and population mechanism
 * that produces an integer count per node. Populations run on entry and
 * re-run on `refresh_seconds` intervals. Badges appear when a count is a
 * positive integer, disappear when it drops to zero, and update their
 * label when the count changes.
 *
 * On a failed refresh, existing status badges switch their border to a
 * dashed grey line to mark stale state. A subsequent successful refresh
 * restores the default solid border in the set's color.
 *
 * Badge sizing reuses the "smallest host wins" rule from badge-nodes.js
 * so status badges and type icon badges share the same diameter at a
 * given elevation.
 *
 * Spec: tap_viz/specs/spec-viz-badges.md
 *   - req-viz-badges-badge-set
 *   - req-viz-badges-status-sets
 */

import {computeUniformBadgeSize} from "./badge-nodes.js";

const STATUS_BADGE_ID_PREFIX = "sbadge:";
// Status badges render at a fraction of the type icon badge diameter so the
// two don't compete for the eye at parity. 0.75 is a readable size that
// still carries a 1-2 digit count clearly.
const STATUS_BADGE_RATIO = 0.75;
// Border color is derived by darkening the fill. 0.6 gives a visible but
// tonally-related edge rather than a contrasting outline.
const BORDER_DARKEN_FACTOR = 0.6;

function _darken(hex, factor) {
    const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || "");
    if (!m) return hex;
    const parts = [m[1], m[2], m[3]]
        .map((x) => Math.max(0, Math.min(255, Math.round(parseInt(x, 16) * factor))))
        .map((x) => x.toString(16).padStart(2, "0"));
    return "#" + parts.join("");
}

/**
 * Apply status badges configured on the projection.
 *
 * @param {cytoscape.Core} cy
 * @param {Object|undefined} statusBadgesConfig The `status_badges` block from projection.definition.
 * @param {Object} [opts]
 * @param {number} [opts.uniformBadgeSize] Shared diameter; falls back to computing across all nodes.
 * @param {number} [opts.badgeRatio]
 * @param {number} [opts.minBadgeSize]
 * @returns {{ ready: Promise, destroy: Function }}
 */
export function applyStatusBadges(cy, statusBadgesConfig, opts = {}) {
    const noop = {destroy: () => {}};
    if (!statusBadgesConfig || typeof statusBadgesConfig !== "object") return noop;
    const badgeSets = statusBadgesConfig.badge_sets;
    if (!Array.isArray(badgeSets) || badgeSets.length === 0) return noop;
    // Filter to well-formed entries with a name; preserve array order.
    const orderedSets = badgeSets.filter(
        (s) => s && typeof s === "object" && typeof s.name === "string" && s.name.length > 0,
    );
    if (orderedSets.length === 0) return noop;

    _removeStatusBadges(cy);

    const shared =
        opts.uniformBadgeSize && opts.uniformBadgeSize > 0
            ? opts.uniformBadgeSize
            : computeUniformBadgeSize(cy.nodes(), opts);
    const statusSize = shared * STATUS_BADGE_RATIO;

    const refreshSeconds = Number(statusBadgesConfig.refresh_seconds || 0);

    const state = {
        cy,
        orderedSets,
        statusSize,
        stale: false,
        intervalId: null,
    };

    // Kick off the initial render pass. Population may be async (search-backed),
    // so the initial call is promise-based and the stale marker engages on failure.
    // The ready promise is exposed so callers can await badge creation before
    // running cascade reveal.
    const readyPromise = _renderPass(state)
        .then(() => _setStale(state, false))
        .catch((err) => {
            console.warn("[status-badges] initial render failed:", err);
            _setStale(state, true);
        });

    function onHostPosition(evt) {
        const host = evt.target;
        if (host.data("_is_badge") || host.data("_is_status_badge")) return;
        _repositionHostBadges(state, host);
    }
    cy.on("position", "node[_status_host_active]", onHostPosition);

    if (refreshSeconds > 0) {
        state.intervalId = setInterval(async () => {
            try {
                await _renderPass(state);
                _setStale(state, false);
            } catch (err) {
                console.warn("[status-badges] refresh failed:", err);
                _setStale(state, true);
            }
        }, refreshSeconds * 1000);
    }

    return {
        ready: readyPromise,
        destroy: () => {
            cy.off("position", "node[_status_host_active]", onHostPosition);
            if (state.intervalId) {
                clearInterval(state.intervalId);
                state.intervalId = null;
            }
            _removeStatusBadges(cy);
        },
    };
}

async function _renderPass(state) {
    const {cy, orderedSets, statusSize} = state;

    // Population pass per set — run in parallel so search-backed sets don't
    // block static ones. Any population throws on failure; the caller engages
    // the stale marker and leaves existing badges in place.
    const setPops = await Promise.all(
        orderedSets.map(async (cfg, setIdx) => ({
            setIdx,
            name: cfg.name,
            cfg,
            counts: await _runPopulation(cy, cfg.population || {}),
        })),
    );

    _removeStatusBadges(cy);

    // Only visible, non-helper nodes host status badges. Excludes type-icon
    // badges, other status badges, stack helper nodes (depth cards / count
    // chip), and anything hidden by class (elevation/nesting/stack-collapsed).
    const hosts = cy.nodes().filter(
        (n) =>
            !n.data("_is_badge") &&
            !n.data("_is_status_badge") &&
            !n.data("_is_stack_card") &&
            !n.data("_is_stack_chip") &&
            n.visible(),
    );

    const badgeElements = [];
    const activeHostIds = [];

    hosts.forEach((host) => {
        const hostId = host.id();
        // Active sets for this host, preserving declaration order.
        const active = setPops.filter((sp) => {
            const c = sp.counts[hostId];
            return typeof c === "number" && Number.isInteger(c) && c > 0;
        });
        if (active.length === 0) return;
        activeHostIds.push(hostId);

        const pos = host.position();
        const w = host.width();
        const h = host.height();
        const rightX = pos.x + w / 2;
        const topY = pos.y - h / 2;
        const total = active.length;

        active.forEach((sp, idx) => {
            const count = sp.counts[hostId];
            // First-declared (idx=0) sits leftmost; last-declared (idx=total-1)
            // sits at the corner.
            const slotOffset = (total - 1 - idx) * statusSize;
            badgeElements.push({
                group: "nodes",
                data: {
                    id: STATUS_BADGE_ID_PREFIX + sp.name + ":" + hostId,
                    _is_status_badge: true,
                    _status_set: sp.name,
                    _status_host: hostId,
                    _status_slot: idx,
                    _status_total: total,
                    _status_fill: sp.cfg.color || "#ef4444",
                    _status_text: sp.cfg.text_color || "#ffffff",
                    _status_border: _darken(sp.cfg.color || "#ef4444", BORDER_DARKEN_FACTOR),
                    _status_count_label: String(count),
                },
                position: {x: rightX - slotOffset, y: topY},
                locked: true,
            });
        });
    });

    // Mark hosts that now have status badges so the position listener
    // only fires for them.
    cy.nodes("[_status_host_active]").removeData("_status_host_active");
    activeHostIds.forEach((id) => {
        const host = cy.getElementById(id);
        if (host.length > 0) host.data("_status_host_active", true);
    });

    if (badgeElements.length === 0) return;

    cy.add(badgeElements);
    cy.nodes("[_is_status_badge]").forEach((badge) => {
        badge.style({width: statusSize, height: statusSize});
    });

    // Stale state survives re-renders: if state.stale is set, stamp it onto
    // the freshly-created badges so the style selector continues to match.
    if (state.stale) {
        cy.nodes("[_is_status_badge]").data("_status_stale", true);
    }
}

async function _runPopulation(cy, population) {
    if (!population || typeof population !== "object") return {};
    const {type} = population;
    if (type === "static_by_node_type") {
        const rules = Array.isArray(population.rules) ? population.rules : [];
        if (rules.length === 0) return {};
        const counts = {};
        cy.nodes().forEach((n) => {
            if (n.data("_is_badge") || n.data("_is_status_badge")) return;
            const entityType = n.data("entity_type") || "";
            for (const r of rules) {
                if (r && r.entity_type === entityType) {
                    const c = Number(r.count);
                    if (Number.isFinite(c) && c >= 0) counts[n.id()] = Math.floor(c);
                    break;
                }
            }
        });
        return counts;
    }
    if (type === "search") {
        return await _runSearchPopulation(population);
    }
    console.warn("[status-badges] unknown population.type:", type);
    return {};
}

async function _runSearchPopulation(population) {
    const searchId = population.search_id;
    if (!searchId) {
        console.warn("[status-badges] search population missing search_id");
        return {};
    }
    const inputs = population.inputs || {};
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
    const rows = Array.isArray(data.rows) ? data.rows : [];
    const counts = {};
    for (const row of rows) {
        const eid = row.entity_id;
        const c = Number(row.count);
        if (eid && Number.isFinite(c) && c >= 0) {
            counts[String(eid)] = Math.floor(c);
        }
    }
    return counts;
}

function _readCsrfToken() {
    // base.html's meta tag, not the cookie: its name is per stack (tap#773).
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : null;
}

function _repositionHostBadges(state, host) {
    const {cy, statusSize} = state;
    const hostId = host.id();
    const badges = cy.nodes(`[_status_host = "${hostId}"]`);
    if (badges.length === 0) return;
    const pos = host.position();
    const w = host.width();
    const h = host.height();
    const rightX = pos.x + w / 2;
    const topY = pos.y - h / 2;
    badges.forEach((badge) => {
        const slot = badge.data("_status_slot") || 0;
        const total = badge.data("_status_total") || badges.length;
        const slotOffset = (total - 1 - slot) * statusSize;
        badge.unlock();
        badge.position({x: rightX - slotOffset, y: topY});
        badge.lock();
    });
}

function _setStale(state, isStale) {
    if (state.stale === isStale) return;
    state.stale = isStale;
    const cy = state.cy;
    if (isStale) {
        cy.nodes("[_is_status_badge]").data("_status_stale", true);
    } else {
        cy.nodes("[_is_status_badge]").removeData("_status_stale");
    }
}

function _removeStatusBadges(cy) {
    cy.nodes("[_status_host_active]").removeData("_status_host_active");
    cy.nodes("[_is_status_badge]").remove();
}
