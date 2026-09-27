/**
 * tap_viz runtime: search execution helper.
 *
 * Posts to the tap_api search execute endpoint and returns the canonical
 * {nodes, edges, info, warnings} envelope. Used by tap layouts to fetch
 * additional graph data at runtime.
 */

const EXECUTE_URL = (searchId) => `/api/v1/searches/${searchId}/execute`;

function getCsrfToken() {
    // base.html's meta tag, not the cookie: its name is per stack (tap#773).
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
}

export async function executeSearch({searchId, inputs, limit, offset, layer} = {}) {
    if (!searchId) throw new Error("executeSearch: searchId required");
    const body = {};
    if (inputs !== undefined) body.inputs = inputs;
    if (limit !== undefined) body.limit = limit;
    if (offset !== undefined) body.offset = offset;
    if (layer !== undefined) body.layer = layer;

    const response = await fetch(EXECUTE_URL(searchId), {
        method: "POST",
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCsrfToken(),
        },
        body: JSON.stringify(body),
    });

    if (!response.ok) {
        let detail = null;
        try {
            detail = await response.json();
        } catch (_) {
            /* ignore */
        }
        const err = new Error(`executeSearch failed: ${response.status}`);
        err.status = response.status;
        err.detail = detail;
        throw err;
    }

    return response.json();
}
