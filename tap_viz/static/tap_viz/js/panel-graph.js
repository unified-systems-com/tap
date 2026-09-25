/**
 * panel-graph.js — TAP Graph Panel Cytoscape renderer.
 *
 * Reads nodes and edges from embedded JSON script blocks, initialises a
 * Cytoscape instance inside the panel container, and attaches toolbar
 * controls (zoom in, zoom out, fit, fullscreen).
 *
 * Called per-panel via the inline IIFE in graph_panel.html:
 *   initGraph(panelId)
 */

/* global cytoscape */

// ---------------------------------------------------------------------------
// TapVizNestingResolver — client-side compound-node resolution
// ---------------------------------------------------------------------------

// Matches: (parent:label)-[:TYPE]->(child:label) OR (parent:label)<-[:TYPE]-(child:label)
// Edge bracket supports [:TYPE], [var:TYPE], or [TYPE].
var NESTING_PATTERN_RE = /^\(parent(?::(\w+))?\)\s*(?:-\[(?:\w+)?:?(\w+)\]->\s*\(child(?::(\w+))?\)|<-\[(?:\w+)?:?(\w+)\]-\s*\(child(?::(\w+))?\))$/;

function TapVizNestingResolver(nodes, edges) {
    this.nodes = nodes;
    this.edges = edges;
}

TapVizNestingResolver.prototype._parsePattern = function (gryphon) {
    var m = NESTING_PATTERN_RE.exec(gryphon.trim());
    if (!m) return null;
    // Groups: 1=parentLabel, 2=outEdgeType, 3=outChildLabel, 4=inEdgeType, 5=inChildLabel
    if (m[2]) {
        return { parentLabel: m[1] || null, childLabel: m[3] || null, edgeType: m[2], direction: "out" };
    }
    return { parentLabel: m[1] || null, childLabel: m[5] || null, edgeType: m[4], direction: "in" };
};

TapVizNestingResolver.prototype.resolve = function () {
    var self = this;
    var warnings = [];

    // 1. Build type-by-entity-id map.
    var typeByEntityId = {};
    this.nodes.forEach(function (n) {
        typeByEntityId[n.entity_id] = n.entity_type;
    });

    // 2. Collect all nesting rules from all node types' display.nesting metadata.
    var rules = [];
    var seenTypes = {};
    this.nodes.forEach(function (n) {
        var entityType = n.entity_type;
        if (seenTypes[entityType]) return;
        seenTypes[entityType] = true;

        var tapViz = (n.display || {}).tap_viz || {};
        var nesting = tapViz.nesting;
        if (!nesting) return;

        // Parent-side rules: self-side is parent, so parentLabel must match entityType.
        (nesting.parent || []).forEach(function (rel) {
            var parsed = self._parsePattern(rel.gryphon || "");
            if (!parsed) {
                warnings.push({ category: "unsupported_matcher_syntax", message: "Cannot parse: " + rel.gryphon });
                return;
            }
            if (parsed.parentLabel && parsed.parentLabel !== entityType) {
                warnings.push({ category: "context_type_mismatch", message: "Parent rule on " + entityType + " declares parent:" + parsed.parentLabel });
                return;
            }
            parsed.parentLabel = entityType;
            rules.push(parsed);
        });

        // Child-side rules: self-side is child, so childLabel must match entityType.
        (nesting.child || []).forEach(function (rel) {
            var parsed = self._parsePattern(rel.gryphon || "");
            if (!parsed) {
                warnings.push({ category: "unsupported_matcher_syntax", message: "Cannot parse: " + rel.gryphon });
                return;
            }
            if (parsed.childLabel && parsed.childLabel !== entityType) {
                warnings.push({ category: "context_type_mismatch", message: "Child rule on " + entityType + " declares child:" + parsed.childLabel });
                return;
            }
            parsed.childLabel = entityType;
            rules.push(parsed);
        });
    });

    // 3. Deduplicate rules (same parentLabel + childLabel + edgeType + direction).
    var ruleKeys = {};
    var uniqueRules = [];
    rules.forEach(function (r) {
        var key = (r.parentLabel || "") + "|" + (r.childLabel || "") + "|" + r.edgeType + "|" + r.direction;
        if (!ruleKeys[key]) {
            ruleKeys[key] = true;
            uniqueRules.push(r);
        }
    });

    // 4. Match edges against rules, build candidate assignments.
    var candidates = {};  // childId -> Set of parentIds
    var consumedEdges = {};  // edgeId -> [parentId, childId]
    this.edges.forEach(function (e) {
        var ent = e.entity || {};
        var ed = e.edge || {};
        var edgeId = ent.entity_id;
        var fromType = typeByEntityId[ed.from_entity_id];
        var toType = typeByEntityId[ed.to_entity_id];

        uniqueRules.forEach(function (rule) {
            var parentId, childId;
            if (rule.direction === "out" && ed.edge_type === rule.edgeType) {
                if ((!rule.parentLabel || fromType === rule.parentLabel) &&
                    (!rule.childLabel || toType === rule.childLabel)) {
                    parentId = ed.from_entity_id;
                    childId = ed.to_entity_id;
                }
            } else if (rule.direction === "in" && ed.edge_type === rule.edgeType) {
                // Inbound: (parent)<-[:TYPE]-(child) means from=child, to=parent.
                if ((!rule.parentLabel || toType === rule.parentLabel) &&
                    (!rule.childLabel || fromType === rule.childLabel)) {
                    parentId = ed.to_entity_id;
                    childId = ed.from_entity_id;
                }
            }
            if (parentId && childId) {
                if (!candidates[childId]) candidates[childId] = {};
                candidates[childId][parentId] = true;
                consumedEdges[edgeId] = [parentId, childId];
            }
        });
    });

    // 5. Accept single-parent, reject multiple parents.
    var parentByChildId = {};
    var hiddenEdgeIds = new Set();
    Object.keys(candidates).forEach(function (childId) {
        var parents = Object.keys(candidates[childId]);
        if (parents.length === 1) {
            parentByChildId[childId] = parents[0];
        } else {
            warnings.push({
                category: "multiple_parents",
                message: "Child " + childId + " has " + parents.length + " candidate parents: " + parents.join(", "),
            });
        }
    });

    // 6. Detect cycles — walk parent chain, drop cyclic assignments.
    var inCycle = {};
    Object.keys(parentByChildId).forEach(function (startChild) {
        var visited = {};
        var current = startChild;
        while (parentByChildId[current]) {
            if (visited[current]) {
                // Mark all nodes in the cycle.
                var cycleNode = current;
                do {
                    inCycle[cycleNode] = true;
                    cycleNode = parentByChildId[cycleNode];
                } while (cycleNode !== current);
                break;
            }
            visited[current] = true;
            current = parentByChildId[current];
        }
    });
    if (Object.keys(inCycle).length > 0) {
        warnings.push({
            category: "cycle_detected",
            message: "Cycle involving: " + Object.keys(inCycle).join(", "),
        });
        Object.keys(inCycle).forEach(function (id) {
            delete parentByChildId[id];
        });
    }

    // 7. Mark consumed edges as hidden (only for accepted assignments).
    Object.keys(consumedEdges).forEach(function (edgeId) {
        var pair = consumedEdges[edgeId];
        var parentId = pair[0], childId = pair[1];
        if (parentByChildId[childId] === parentId) {
            hiddenEdgeIds.add(edgeId);
        }
    });

    return { parentByChildId: parentByChildId, hiddenEdgeIds: hiddenEdgeIds, warnings: warnings };
};


// ---------------------------------------------------------------------------
// TapParentLabelOverlay — LEGACY: used only by non-projection panels that
// still use compound-node nesting. Projection panels use the bounded-layer
// model with .tap-viewport-parent native Cytoscape labels instead.
//
// The cytoscape-node-html-label plugin cannot reliably position compound node
// labels because its one("render") bootstrap fires before layout, when
// compound node dimensions are NaN.  This overlay creates and positions
// label divs directly, hooking into layoutstop, pan/zoom, and position/bounds
// events after layout completes and dimensions are stable.
// ---------------------------------------------------------------------------

function TapParentLabelOverlay(cy, parentLabelData) {
    this._cy = cy;
    this._data = parentLabelData;  // { entityId: { label, icon_url, config } }
    this._container = null;        // outer div (pan/zoom transformed)
    this._els = {};                // entityId -> wrapper div
}

TapParentLabelOverlay.prototype.init = function () {
    var self = this;
    var cyContainer = this._cy.container();

    // Create overlay container next to the canvas.
    var el = document.createElement("div");
    var canvas = cyContainer.querySelector("canvas");
    var s = el.style;
    s.position = "absolute";
    s.zIndex = "10";
    s.width = "500px";
    s.margin = s.padding = s.border = s.outline = "0px";
    s.pointerEvents = "none";
    s.transformOrigin = "top left";
    canvas.parentNode.appendChild(el);
    this._container = el;

    // Wrappers are created lazily on first sync so parents that appear after
    // init (e.g. when a drilldown tap layout nests new children inside an
    // existing node) also get labels.
    this._cy.nodes(":parent").forEach(function (node) {
        self._ensureWrapper(node);
    });

    // Initial sync.
    this._syncPanZoom();
    this._syncAllPositions();

    // Bind events.
    this._cy.on("pan zoom", function () { self._syncPanZoom(); });
    this._cy.on("layoutstop", function () { self._syncAllPositions(); });
    this._cy.on("position bounds", "node:parent", function (evt) {
        self._syncPosition(evt.target);
    });
};

TapParentLabelOverlay.prototype._ensureWrapper = function (node) {
    var id = node.id();
    if (this._els[id]) return this._els[id];
    if (node.hasClass("tap-dim-anchor")) return null;

    // Prefer prebuilt label data; fall back to the node's own data so the
    // overlay works without server-side metadata. When a type-icon badge is
    // active for the host (_badge_active), the badge is already rendering
    // the icon as a separate corner node — repeating it inside the label
    // overlay would be visual duplication, so the overlay label is
    // text-only in that case.
    var pl = this._data[id] || {
        label: node.data("label") || node.data("entity_type") || id,
        icon_url: node.data("_badge_active")
            ? ""
            : (node.data("icon_url") || node.data("_original_icon_url") || ""),
    };

    var wrapper = document.createElement("div");
    wrapper.style.position = "absolute";

    var iconHtml = pl.icon_url
        ? '<img class="tap-parent-label__icon" src="' + _escapeHtml(pl.icon_url) + '" alt="" />'
        : "";
    wrapper.innerHTML = '<div class="tap-parent-label">' + iconHtml +
        '<span class="tap-parent-label__text">' + _escapeHtml(pl.label || "") + "</span></div>";

    this._container.appendChild(wrapper);
    this._els[id] = wrapper;
    return wrapper;
};

TapParentLabelOverlay.prototype._syncPanZoom = function () {
    var pan = this._cy.pan();
    var zoom = this._cy.zoom();
    var t = "translate(" + pan.x + "px," + pan.y + "px) scale(" + zoom + ")";
    var s = this._container.style;
    s.webkitTransform = t;
    s.msTransform = t;
    s.transform = t;
};

TapParentLabelOverlay.prototype._syncAllPositions = function () {
    var self = this;
    var liveParentIds = {};
    this._cy.nodes(":parent").forEach(function (node) {
        liveParentIds[node.id()] = true;
        self._ensureWrapper(node);
        self._syncPosition(node);
    });
    // Strip wrappers for nodes that are no longer parents (e.g. a character
    // that had its artifact children moved out on an elevation transition).
    Object.keys(this._els).forEach(function (id) {
        if (!liveParentIds[id]) {
            var wrapper = self._els[id];
            if (wrapper && wrapper.parentNode) wrapper.parentNode.removeChild(wrapper);
            delete self._els[id];
        }
    });
};

TapParentLabelOverlay.prototype._syncPosition = function (node) {
    var wrapper = this._ensureWrapper(node);
    if (!wrapper) return;

    var pos = node.position();

    // Guard against pre-layout NaN dimensions.
    if (isNaN(pos.x) || isNaN(pos.y)) return;

    // Anchor the wrapper's bottom-center to the host's visible top edge:
    // pos.x is the horizontal center, bb.y1 is the rendered top of the
    // bbox (including the compound's padding + border). Using bbox.y1
    // rather than pos.y - h/2 places the label outside-center above the
    // visible compound border — `h` here is the model-rect height, which
    // for a compound parent excludes ~32 px of padding + border, so a
    // h-based anchor falls inside the visible compound by that margin.
    var bb = node.boundingBox({includeLabels: false});
    if (isNaN(bb.x1) || isNaN(bb.y1)) return;
    var x = pos.x;
    var y = bb.y1;

    var t = "translate(-50%, -100%) translate(" + x.toFixed(2) + "px," + y.toFixed(2) + "px)";
    var s = wrapper.style;
    s.webkitTransform = t;
    s.msTransform = t;
    s.transform = t;
};


// ---------------------------------------------------------------------------
// initGraph — main entry point per graph panel
// ---------------------------------------------------------------------------

function initGraph(panelId) {
    const nodesEl = document.getElementById("tap-graph-nodes-" + panelId);
    const edgesEl = document.getElementById("tap-graph-edges-" + panelId);
    const projectionEl = document.getElementById("tap-graph-projection-" + panelId);
    const container = document.getElementById("tap-graph-container-" + panelId);
    const cyEl = document.getElementById("tap-graph-" + panelId);

    if (!nodesEl || !edgesEl || !container || !cyEl) return;

    const nodes = JSON.parse(nodesEl.textContent || "[]");
    const edges = JSON.parse(edgesEl.textContent || "[]");
    const projection = projectionEl ? JSON.parse(projectionEl.textContent || "null") : null;
    const inputsEl = document.getElementById("tap-graph-inputs-" + panelId);
    const panelInputs = inputsEl ? JSON.parse(inputsEl.textContent || "{}") : {};

    // Projection-hosted panel: empty scenes are allowed (the runtime populates them).
    if (nodes.length === 0 && !projection) {
        cyEl.innerHTML = '<p class="text-sm text-slate-400 p-4">No nodes to display.</p>';
        return;
    }

    // Nesting resolution — gated by layout flag.
    var nestingEnabled = container.dataset.nesting === "true";
    var nesting = { parentByChildId: {}, hiddenEdgeIds: new Set(), warnings: [] };

    if (nestingEnabled) {
        var resolver = new TapVizNestingResolver(nodes, edges);
        nesting = resolver.resolve();
        nesting.warnings.forEach(function (w) {
            console.warn("[TAP Nesting]", w.category, w.message);
        });
    }

    // Collect the set of entity IDs that are actual parents (have children).
    var parentIds = new Set();
    Object.keys(nesting.parentByChildId).forEach(function (childId) {
        parentIds.add(nesting.parentByChildId[childId]);
    });

    // Build per-parent metadata for HTML label rendering.
    // parentLabelData: { entityId: { label, icon_url, config } }
    var parentLabelData = {};
    if (parentIds.size > 0) {
        nodes.forEach(function (n) {
            if (!parentIds.has(n.entity_id)) return;
            var tapViz = (n.display || {}).tap_viz || {};
            var nestingMeta = tapViz.nesting || {};
            var plConfig = nestingMeta.parent_label || {};
            parentLabelData[n.entity_id] = {
                label: n.name || n.entity_type || n.entity_id,
                icon_url: tapViz.icon_url || "",
                config: {
                    horizontal_alignment: plConfig.horizontal_alignment || "center",
                    vertical_alignment: plConfig.vertical_alignment || "top",
                    inside_or_outside: plConfig.inside_or_outside || "outside",
                },
            };
        });
    }

    // Build Cytoscape elements from GRIFT envelopes (spec-grift-envelope).
    // Each envelope has spine fields flat at top, per-model data in `data`,
    // and computed-for-render values in `display.tap_viz`.
    const cyNodes = nodes.map(function (n) {
        var tapViz = (n.display || {}).tap_viz || {};
        var colors = tapViz.colors || {};
        var data = {
            id: n.entity_id,
            label: n.name || n.entity_type || n.entity_id,
            entity_type: n.entity_type || "",
            icon_url: tapViz.icon_url || "",
            shape: tapViz.shape || "ellipse",
            url_id: tapViz.url_id || "",
            // Single-tap navigation target, computed server-side from the
            // panel's nav_rules (graph_panel). Empty string = no navigation.
            // nav_external opens it in a new tab instead of replacing the page.
            nav_url: tapViz.nav_url || "",
            nav_external: !!tapViz.nav_external,
            // Spine dimensions — needed client-side for dimension-equality
            // nesting (spec-viz-nested-projection § dimension_match). Carried
            // shallow on the data dict so cytoscape selectors / runtime code
            // can read `n.data("dimensions").<key>` without re-fetching from
            // the server. Always an object; never null.
            dimensions: n.dimensions || {},
            // Per-model tags (e.g. AWS resource tags: Project, Component,
            // Environment). Lifted onto the cy data dict so client-side
            // runtimes — layout-scope-boxes, ad-hoc filters — can select by
            // tag without re-fetching. Sourced from the envelope's per-model
            // `data.tags` field; nodes whose model doesn't carry tags get
            // an empty object so selectors don't NPE.
            tags: ((n.data || {}).tags) || {},
            // The node's typed model fields: the envelope's whole `data` lane
            // (spec-grift-envelope § Data Lane Rule), so a layout reads
            // `node.data("fields").is_global` instead of parsing the label
            // (req-viz-layout-node-fields). The lane already decides what is
            // served; nothing is added or withheld here. Always an object.
            fields: n.data || {},
        };
        if (colors.fill) data.fill_color = colors.fill;
        if (colors.border) data.border_color = colors.border;
        if (colors.label) data.label_color = colors.label;

        // Label-position hint: valign/halign + inside/outside -> Cytoscape
        // text-valign, text-halign, text-margin-y (inside uses positive margin,
        // outside uses negative — pushing the label off the container edge).
        var label = tapViz.label || {};
        if (label.valign && label.halign) {
            data.label_valign = label.valign;
            data.label_halign = label.halign;
            var outsideMargin = 6;
            var sign = label.position === "outside" ? -1 : 1;
            if (label.valign === "top") data.label_margin_y = sign * outsideMargin;
            else if (label.valign === "bottom") data.label_margin_y = -sign * outsideMargin;
            else data.label_margin_y = 0;
        }

        if (nesting.parentByChildId[n.entity_id]) {
            data.parent = nesting.parentByChildId[n.entity_id];
        }
        return { data: data };
    });

    const nodeIds = new Set(nodes.map(function (n) { return n.entity_id; }));
    const cyEdges = edges
        .filter(function (e) {
            var ed = e.data || {};
            return nodeIds.has(ed.from_entity_id) && nodeIds.has(ed.to_entity_id);
        })
        .map(function (e) {
            var ed = e.data || {};
            var edgeId = e.entity_id || (ed.from_entity_id + "-" + ed.to_entity_id + "-" + ed.edge_type);
            var classes = nesting.hiddenEdgeIds.has(edgeId) ? "tap-nesting-hidden" : "";
            return {
                data: {
                    id: edgeId,
                    source: ed.from_entity_id,
                    target: ed.to_entity_id,
                    label: ed.edge_type || "",
                },
                classes: classes,
            };
        });

    const placement = container.dataset.placement || "cytoscape:cose";
    const cy = cytoscape({
        container: cyEl,
        elements: cyNodes.concat(cyEdges),
        style: [
            {
                // Base node style — solid colour, used when no icon resolves.
                selector: "node",
                style: {
                    "shape": "data(shape)",
                    "background-color": "#4f46e5",
                    "label": "data(label)",
                    "color": "#1e293b",
                    "font-size": "11px",
                    "text-valign": "bottom",
                    "text-margin-y": "4px",
                    "width": 40,
                    "height": 40,
                },
            },
            {
                // Nodes that have a resolved icon URL: show the icon over a
                // light background so the SVG is legible.
                selector: "node[icon_url != '']",
                style: {
                    "background-color": "#e0e7ff",
                    "background-image": "data(icon_url)",
                    "background-fit": "none",
                    "background-width": "65%",
                    "background-height": "65%",
                    "background-position-x": "50%",
                    "background-position-y": "50%",
                    "background-clip": "none",
                    "background-image-opacity": 1,
                },
            },
            {
                selector: "edge",
                style: {
                    "width": 2,
                    "line-color": "#94a3b8",
                    "target-arrow-color": "#94a3b8",
                    "target-arrow-shape": "triangle",
                    "curve-style": "bezier",
                    "label": "data(label)",
                    "font-size": "9px",
                    "color": "#000000",
                },
            },
            {
                // Compound parent nodes (legacy nesting containers).
                // Normal text label and background-image icon are suppressed;
                // parent-label HTML overlay handles icon + text rendering.
                selector: ":parent",
                style: {
                    "background-opacity": 0.08,
                    "background-image": "none",
                    "border-width": 2,
                    "border-color": "#94a3b8",
                    "padding": "30px",
                    "label": "",
                },
            },
            {
                // Bounded-layer viewport parents (nested projection model).
                // Container visual: subtle background, top-aligned label,
                // icon suppressed. Children are positioned inside via
                // projectNested runtime.
                selector: ".tap-viewport-parent",
                style: {
                    "background-color": "#f1f5f9",
                    "background-image": "none",
                    "background-opacity": 1,
                    "border-width": 2,
                    "border-color": "#94a3b8",
                    "border-opacity": 0.6,
                    "label": "data(label)",
                    "text-valign": "top",
                    "text-halign": "center",
                    "text-margin-y": 6,
                    "font-size": "10px",
                    "color": "#475569",
                },
            },
            {
                // Hidden by class:
                //  - tap-nesting-hidden / tap-hidden-containment: consumed by
                //    nesting resolution (the edge drove a parent-child assignment)
                //  - tap-elevation-hidden: the active elevation's layout has
                //    deferred this element to a lower-altitude elevation
                //  - tap-stack-collapsed: collapsed into a stack pile, the
                //    representative + count chip stand in for it
                selector: ".tap-nesting-hidden, .tap-hidden-containment, .tap-elevation-hidden, .tap-stack-collapsed",
                style: { "display": "none" },
            },
            {
                // Badge nodes: small transparent disks anchored to host node's
                // upper-left corner, letting the host's type icon show through
                // with no visible bubble or border. Non-interactive.
                //
                // The fully-transparent default trades the visible badge frame
                // for a cleaner icon-only read. A configurable bubble/border
                // appearance is deferred to future work.
                selector: "node[_is_badge]",
                style: {
                    "shape": "ellipse",
                    "background-color": "#ffffff",
                    "background-opacity": 0,
                    "background-image": "data(icon_url)",
                    "background-fit": "none",
                    "background-width": "100%",
                    "background-height": "100%",
                    "background-position-x": "50%",
                    "background-position-y": "50%",
                    "background-clip": "none",
                    "background-image-opacity": 1,
                    "border-width": 0,
                    "label": "",
                    "events": "no",
                    "z-index": 999,
                },
            },
            {
                // Status badges: filled circles at the upper-right corner of
                // host nodes showing a numeric count. Fill, text, and border
                // colors are driven per-set through data attributes set by
                // status-badges.js. The border is a darker related shade of
                // the fill, computed client-side. Events ARE enabled so the
                // badge intercepts its own taps (otherwise clicks pass through
                // to the host node behind, which now has plugin-owned tap
                // semantics — see spec-viz-panel.md req-viz-panel-click-semantics-7).
                selector: "node[_is_status_badge]",
                style: {
                    "shape": "ellipse",
                    "background-color": "data(_status_fill)",
                    "background-opacity": 1,
                    "background-image": "none",
                    "border-width": 1,
                    "border-color": "data(_status_border)",
                    "border-style": "solid",
                    "color": "data(_status_text)",
                    "label": "data(_status_count_label)",
                    "text-valign": "center",
                    "text-halign": "center",
                    "text-margin-x": 0,
                    "text-margin-y": 0,
                    "font-size": 11,
                    "font-weight": "bold",
                    "events": "yes",
                    "z-index": 999,
                },
            },
            {
                // Stale marker: dashed grey border overrides the default
                // solid, set-colored border when a refresh has failed.
                selector: "node[_is_status_badge][?_status_stale]",
                style: {
                    "border-style": "dashed",
                    "border-color": "#94a3b8",
                },
            },
            {
                // Stack depth cards: decorative offset copies drawn behind the
                // representative so a collapsed pile reads as "many of these."
                // No icon — a faded blank token in the representative's own
                // model colors (the per-model node[fill_color] rule below
                // repaints fill/border when the model ships colors; the neutral
                // slate here is the fallback for uncolored models). Per-card
                // z-index (data(_stack_z)) makes each deeper card draw strictly
                // below the one in front, so the offset reads as a stack.
                selector: "node[_is_stack_card]",
                style: {
                    "shape": "data(shape)",
                    "background-color": "#e2e8f0",
                    "background-image": "none",
                    "opacity": 0.5,
                    "border-width": 2,
                    "border-color": "#cbd5e1",
                    "label": "",
                    "events": "no",
                    "z-index": "data(_stack_z)",
                },
            },
            {
                // Stack representative: the face of the pile, raised above its
                // depth cards (CARD_Z_TOP is 10 in stack.js; 20 clears all
                // cards while staying below the badges/chip at 999/1000).
                selector: "node[_stack_front_id]",
                style: {
                    "z-index": 20,
                },
            },
            {
                // Stack count chip: a neutral rounded-rectangle straddling the
                // bottom edge of the representative, showing the true
                // cardinality (humanized for large numbers). The white hairline
                // is a contrast halo so the count reads over any icon. Neutral
                // slate — deliberately NOT an alert color — to distinguish
                // "how many" from the alert/status badges in the upper-right.
                // Events ARE enabled so the chip can answer hover for the exact
                // count; tap/double-tap are filtered out (see hit-test below).
                selector: "node[_is_stack_chip]",
                style: {
                    "shape": "round-rectangle",
                    "background-color": "#475569",
                    "background-opacity": 1,
                    "background-image": "none",
                    "border-width": 1.5,
                    "border-color": "#ffffff",
                    "color": "#ffffff",
                    "label": "data(_stack_count_label)",
                    "text-valign": "center",
                    "text-halign": "center",
                    "text-margin-x": 0,
                    "text-margin-y": 0,
                    "font-size": 10,
                    "font-weight": "bold",
                    "events": "yes",
                    "z-index": 1000,
                },
            },
            {
                // Host nodes in badge mode: icon removed from body, label centered.
                selector: "node[_badge_active]",
                style: {
                    "background-color": "#e0e7ff",
                    "background-image": "none",
                    "text-valign": "center",
                    "text-halign": "center",
                    "text-margin-y": 0,
                    "font-size": "9px",
                },
            },
            {
                // Model-level topo colors from DEFAULT_DISPLAY.tap_viz.colors.
                // Applied after the viewport-parent and badge-host defaults so
                // the per-model palette wins; nodes without the hint keep the
                // default indigo fill and slate border behavior.
                selector: "node[fill_color]",
                style: {
                    "background-color": "data(fill_color)",
                    "background-opacity": 1,
                    "border-color": "data(border_color)",
                    "border-width": 2,
                    "color": "data(label_color)",
                },
            },
            {
                // Compound viewport-parents with a model-level fill color.
                // Cytoscape state pseudo-classes (`:parent`) have higher
                // specificity than plain attribute selectors, so the per-model
                // palette must be re-asserted with state-level specificity to
                // win over the compound-parent default opacity 0.08.
                selector: ":parent[fill_color]",
                style: {
                    "background-color": "data(fill_color)",
                    "background-opacity": 1,
                    "border-color": "data(border_color)",
                    "border-width": 2,
                    "color": "data(label_color)",
                },
            },
            {
                // Compound viewport-parents with a model-level fill color.
                // Compound (`:parent`) nodes get aggressively-opacity-reduced
                // background by default; for nodes that ship a per-model fill
                // color we re-assert it here with `:parent[fill_color]` so the
                // palette wins over the compound default.
                selector: ":parent[fill_color]",
                style: {
                    "background-color": "data(fill_color)",
                    "background-opacity": 1,
                    "border-color": "data(border_color)",
                    "border-width": 2,
                    "color": "data(label_color)",
                },
            },
            {
                // Model-level label-position hint from DEFAULT_DISPLAY.tap_viz.label.
                // Placed after tap-viewport-parent + badge-host rules so it
                // overrides their baked-in text alignment.
                selector: "node[label_valign][label_halign]",
                style: {
                    "text-valign": "data(label_valign)",
                    "text-halign": "data(label_halign)",
                    "text-margin-y": "data(label_margin_y)",
                },
            },
            {
                // Shadow nodes: reduced opacity, dashed border to signal
                // "this entity is present here but represented elsewhere."
                selector: "node[_is_shadow]",
                style: {
                    "opacity": 0.5,
                    "border-style": "dashed",
                    "border-width": 2,
                    "border-color": "#94a3b8",
                },
            },
            {
                // Shadow links: dashed visual-only edges connecting shadows
                // to their primary. No arrows, neutral color, non-interactive.
                selector: "edge[_is_shadow_link]",
                style: {
                    "line-style": "dashed",
                    "line-color": "#cbd5e1",
                    "line-dash-pattern": [6, 4],
                    "width": 1.5,
                    "target-arrow-shape": "none",
                    "label": "",
                    "events": "no",
                    "z-index": 0,
                },
            },
            {
                // Shadow group hover highlight: increased opacity on shadows,
                // thicker border on primary, brighter shadow-link edges. Node
                // borders keep their own hue-matched data(border_color); only
                // the connecting dashed lines shift to a neutral indigo to
                // signal which group is active across differently-colored
                // nodes.
                selector: "node[_is_shadow].tap-shadow-highlight",
                style: {
                    "opacity": 0.9,
                    "border-width": 3,
                },
            },
            {
                selector: "node[_shadow_role='primary'].tap-shadow-highlight",
                style: {
                    "border-width": 3,
                },
            },
            {
                selector: "edge[_is_shadow_link].tap-shadow-highlight",
                style: {
                    "line-color": "#6366f1",
                    "width": 2.5,
                },
            },
            {
                // Node selection — lighten the existing fill and thicken the
                // border, both hue-preserving. The border bump to 4px sits
                // one step above shadow-hover's 3px indigo so the two states
                // stack legibly when a selected node is inside a hovered
                // shadow group. border-color falls through to the node's own
                // data(border_color) rather than being overridden to indigo.
                selector: "node:selected",
                style: {
                    "background-blacken": -0.3,
                    "border-width": 4,
                },
            },
            {
                selector: "edge:selected",
                style: {
                    "line-color": "#7c3aed",
                    "target-arrow-color": "#7c3aed",
                },
            },
        ],
        userZoomingEnabled: true,
        userPanningEnabled: true,
        boxSelectionEnabled: true,
    });

    // Background grid is drawn by CSS on the container (see panel-graph.css
    // `.tap-cy-static-grid`). The cytoscape-grid-guide extension was
    // previously used for its drawn-grid feature but lagged pan/zoom by a
    // frame, and its other features (snap-to-grid, alignment guidelines,
    // resize handles) were never enabled. Removed in a06d6f0; re-add if
    // those features become useful.

    if (projection) {
        // Hide the graph element immediately so the raw graph never flashes
        // before the projection runtime takes over with cascade reveal.
        cyEl.style.visibility = "hidden";

        // Projection-hosted panel: hand off to the client runtime instead of
        // running a single top-level layout. The runtime orchestrates
        // elevations, tap layouts, and zoom-driven transitions.
        import("/static/tap_viz/js/runtime/projection.js")
            .then(function (mod) {
                return mod.initProjection(cy, projection, {inputs: panelInputs});
            })
            .then(function () {
                // After the projection runtime settles, init the parent-label
                // HTML overlay if any Cytoscape compound parents exist (e.g.,
                // projections that nest via resolveNesting + cy.move). The
                // overlay falls back to node.data() when parentLabelData has
                // no entry for an id, so projection-created parents render.
                if (cy.nodes(":parent").length > 0) {
                    var overlay = new TapParentLabelOverlay(cy, parentLabelData);
                    overlay.init();
                }
            })
            .catch(function (err) {
                console.error("[TAP projection] init failed", err);
            });
    } else {
        // Legacy layout-hosted panel: single placement, zoom-locked after layout.
        cy.one("layoutstop", function () {
            cy.minZoom(cy.zoom());

            // Parent-label HTML overlay — initialized after layout so compound
            // node positions and dimensions are stable.
            if (parentIds.size > 0) {
                var overlay = new TapParentLabelOverlay(cy, parentLabelData);
                overlay.init();
            }
        });

        cy.layout(_buildLayout(placement)).run();
    }

    _attachToolbar(container, cy);

    // Node tap / double-tap handling.
    //
    // Single-tap on a status badge opens the info window for its host. Tap
    // on a host node body does NOT open the info window — host-body taps
    // are reserved for plugins/projections to bind their own behavior on
    // entity types they own (e.g. the AWS top-level projection navigates
    // to the EC2 instance page on EC2 body taps).
    //
    // Double-tap on any node remains the projection runtime's drilldown
    // gesture. Two detection channels run in parallel so cytoscape's
    // pointer translation quirks can't silently break drilldown across
    // browsers:
    //
    //   1. Manual two-tap timer on cytoscape `tap` events. Works reliably
    //      in Chrome; timing varies in Firefox.
    //   2. Native browser `dblclick` on the cy container with a hit test
    //      that maps pointer coordinates to the target node. This is the
    //      guaranteed path on every browser.
    //
    // Both channels funnel through _fireDoubleTap, which dedupes by node+
    // timestamp so rapid double-fires become one.
    //
    // Click semantics spec: tap_viz/specs/spec-viz-panel.md
    //   req-viz-panel-click-semantics
    var DBL_TAP_WINDOW_MS = 400;
    var DBL_FIRE_DEDUP_MS = 500;
    var pendingActionTimer = null;
    var lastTapTime = 0;
    var lastTapNodeId = null;
    var lastFiredNodeId = null;
    var lastFiredTime = 0;

    function _fireDoubleTap(node) {
        if (!node) return;
        var now = Date.now();
        if (node.id() === lastFiredNodeId && (now - lastFiredTime) < DBL_FIRE_DEDUP_MS) {
            return;
        }
        lastFiredNodeId = node.id();
        lastFiredTime = now;
        lastTapTime = 0;
        lastTapNodeId = null;
        clearTimeout(pendingActionTimer);
        pendingActionTimer = null;
        node.trigger("tap-double");
    }

    function _openInfoWindowForHost(host) {
        if (!projection || !projection.status_badges) return;
        import("/static/tap_viz/js/runtime/info-window.js")
            .then(function (mod) {
                mod.openInfoWindow(cy, container, host, projection.status_badges);
            })
            .catch(function (err) {
                console.warn("[TAP info-window] import failed", err);
            });
    }

    cy.on("tap", "node", function (evt) {
        var node = evt.target;
        if (node.data("_is_badge") || node.data("_is_shadow")) return;
        // Stack helpers (depth cards, count chip) are not entities — they carry
        // no tap/double-tap semantics. The chip answers hover only.
        if (node.data("_is_stack_card") || node.data("_is_stack_chip")) return;

        // Status badge tap → open info window for the host. Badges are the
        // only single-tap target that opens the info-window. Fire immediately;
        // badges are not double-tap targets.
        if (node.data("_is_status_badge")) {
            var hostId = node.data("_status_host");
            var badgeHost = hostId ? cy.getElementById(hostId) : null;
            if (badgeHost && badgeHost.length > 0) {
                _openInfoWindowForHost(badgeHost);
            }
            return;
        }

        // Projection-declared navigation: a node carrying nav_url (computed
        // server-side from the panel's nav_rules) navigates on single-tap.
        // External targets open in a new tab; internal ones replace the page.
        // This is the generic primitive plugins/projections opt into for the
        // single-tap gesture; nodes with no nav_url keep the no-op behavior.
        var navUrl = node.data("nav_url");
        if (navUrl) {
            if (node.data("nav_external")) {
                window.open(navUrl, "_blank", "noopener");
            } else {
                window.location.href = navUrl;
            }
            return;
        }

        // Host node tap → manual double-tap detection only. Single-tap on a
        // host body (with no nav_url) has no built-in action; plugins/projections
        // own that gesture for entity types they care about.
        var nodeId = node.id();
        var now = Date.now();
        if (nodeId === lastTapNodeId && (now - lastTapTime) < DBL_TAP_WINDOW_MS) {
            _fireDoubleTap(node);
            return;
        }
        lastTapTime = now;
        lastTapNodeId = nodeId;
    });

    // Firefox fallback: native dblclick with pointer→node hit test.
    if (projection) {
        cyEl.addEventListener("dblclick", function (e) {
            var rect = cyEl.getBoundingClientRect();
            var node = _findNodeAtRenderedPosition(cy, e.clientX - rect.left, e.clientY - rect.top);
            if (node) _fireDoubleTap(node);
        });
    }
}

function _findNodeAtRenderedPosition(cy, x, y) {
    // Prefer leaf nodes (non-parents) so a click inside a compound lands on
    // the child, not the compound parent. Walk in reverse so topmost-painted
    // wins when overlaps occur.
    var hits = [];
    cy.nodes(":visible").forEach(function (n) {
        if (n.data("_is_badge") || n.data("_is_shadow")) return;
        if (n.data("_is_stack_card") || n.data("_is_stack_chip")) return;
        var rpos = n.renderedPosition();
        var rw = n.renderedWidth() / 2;
        var rh = n.renderedHeight() / 2;
        if (x >= rpos.x - rw && x <= rpos.x + rw && y >= rpos.y - rh && y <= rpos.y + rh) {
            hits.push(n);
        }
    });
    if (hits.length === 0) return null;
    // Leaves first, then parents.
    var leaves = hits.filter(function (n) { return n.children().length === 0; });
    if (leaves.length > 0) return leaves[leaves.length - 1];
    return hits[hits.length - 1];
}


function _buildLayout(placement) {
    if (placement === "cytoscape:grid") {
        return { name: "grid", fit: true, padding: 30 };
    }
    if (placement === "cytoscape:preset") {
        return { name: "preset" };
    }
    // cytoscape:cose (default)
    return {
        name: "cose",
        idealEdgeLength: 100,
        nodeOverlap: 20,
        fit: true,
        padding: 30,
        randomize: false,
        componentSpacing: 80,
        nodeRepulsion: 400000,
        edgeElasticity: 100,
        gravity: 80,
        numIter: 1000,
        initialTemp: 200,
        coolingFactor: 0.95,
        minTemp: 1.0,
    };
}

function _attachToolbar(container, cy) {
    // Guarantee the container is the positioning context regardless of class resolution order.
    container.style.position = "relative";

    const toolbar = document.createElement("div");
    toolbar.className = "tap-cy-toolbar";
    toolbar.innerHTML = [
        '<button class="tap-cy-btn" data-action="zoom-in" title="Zoom in">',
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">',
        '<circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>',
        '<line x1="11" y1="8" x2="11" y2="14"></line><line x1="8" y1="11" x2="14" y2="11"></line>',
        "</svg></button>",
        '<button class="tap-cy-btn" data-action="zoom-out" title="Zoom out">',
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">',
        '<circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>',
        '<line x1="8" y1="11" x2="14" y2="11"></line>',
        "</svg></button>",
        '<button class="tap-cy-btn" data-action="fit" title="Fit to view">',
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">',
        '<path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"></path>',
        "</svg></button>",
        '<div class="tap-cy-sep"></div>',
        '<button class="tap-cy-btn" data-action="fullscreen" title="Toggle fullscreen">',
        '<svg class="tap-cy-expand" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">',
        '<polyline points="15 3 21 3 21 9"></polyline><polyline points="9 21 3 21 3 15"></polyline>',
        '<line x1="21" y1="3" x2="14" y2="10"></line><line x1="3" y1="21" x2="10" y2="14"></line>',
        "</svg>",
        '<svg class="tap-cy-compress" style="display:none" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">',
        '<polyline points="4 14 10 14 10 20"></polyline><polyline points="20 10 14 10 14 4"></polyline>',
        '<line x1="14" y1="10" x2="21" y2="3"></line><line x1="3" y1="21" x2="10" y2="14"></line>',
        "</svg>",
        "</button>",
    ].join("");

    container.appendChild(toolbar);

    toolbar.addEventListener("click", function (e) {
        const btn = e.target.closest("[data-action]");
        if (!btn) return;
        const action = btn.dataset.action;
        if (action === "zoom-in") cy.zoom(cy.zoom() * 1.2);
        else if (action === "zoom-out") cy.zoom(cy.zoom() / 1.2);
        else if (action === "fit") cy.fit();
        else if (action === "fullscreen") _toggleFullscreen(container, cy, btn);
    });

    document.addEventListener("fullscreenchange", function () {
        if (!document.fullscreenElement) {
            const btn = toolbar.querySelector("[data-action='fullscreen']");
            if (btn) _syncFullscreenIcon(btn, false);
            setTimeout(function () { cy.resize(); cy.fit(); }, 100);
        }
    });
}

function _toggleFullscreen(container, cy, btn) {
    if (!document.fullscreenElement) {
        container.requestFullscreen().then(function () {
            _syncFullscreenIcon(btn, true);
            setTimeout(function () { cy.resize(); cy.fit(); }, 100);
        });
    } else {
        document.exitFullscreen();
    }
}

function _syncFullscreenIcon(btn, isFullscreen) {
    const expand = btn.querySelector(".tap-cy-expand");
    const compress = btn.querySelector(".tap-cy-compress");
    if (expand) expand.style.display = isFullscreen ? "none" : "";
    if (compress) compress.style.display = isFullscreen ? "" : "none";
}

function _escapeHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}
