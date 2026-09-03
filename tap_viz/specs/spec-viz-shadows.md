# Viz Shadows Specification

## Philosophy

Some entities naturally exist in multiple locations within a topology. An RDS instance spans two subnets across availability zones. A load balancer has listeners in multiple network segments. The graph captures this accurately with multiple edges, but a spatial visualization must decide where to draw the node.

Promoting a multi-homed entity to its nearest common ancestor (e.g. VPC-level) solves the placement ambiguity but loses the visual signal of where the entity actually operates. Shadow nodes restore that signal. The primary node stays at its natural position in the layout hierarchy and remains the canonical target for alerts, badges, selection, and interaction. Lightweight shadow copies appear inside each location where the entity has a presence, connected back to the primary by visual-only links.

This separation between primary and shadow keeps the information architecture clean: there is always exactly one authoritative representation of an entity in the scene, and the shadows exist only to communicate spatial presence.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Unambiguous Primary | Every multi-homed entity has exactly one primary node that owns alerts, badges, and interaction state. |
| 2. | Spatial Presence | Shadow nodes communicate where the entity physically operates within the topology. |
| 3. | Visual Distinction | Shadows are immediately recognizable as references, not independent entities. |
| 4. | Readable Links | Shadow-to-primary links are visually distinct from graph edges so the viewer can distinguish topology from identity. |
| 5. | Group Awareness | Hovering any member of a shadow group highlights the entire group so the viewer can instantly see all locations for that entity. |

## Requirement Status

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-viz-shadows-terminology | [Shadow Terminology](#shadow-terminology) | In Development | Vocabulary for shadow, primary, shadow group, and shadow link |
| req-viz-shadows-primary | [Primary Node](#primary-node) | In Development | The canonical node representation that owns state and interaction |
| req-viz-shadows-shadow-node | [Shadow Node](#shadow-node) | In Development | Lightweight visual copy placed inside a hosting location |
| req-viz-shadows-link | [Shadow Link](#shadow-link) | In Development | Visual-only edge connecting a shadow to its primary |
| req-viz-shadows-hover-highlight | [Hover Highlight](#hover-highlight) | In Development | Mouse-over any group member highlights all others |
| req-viz-shadows-nesting | [Shadow Nesting](#shadow-nesting) | In Development | Shadows participate in their host container's viewport parent chain |
| req-viz-shadows-layout-integration | [Layout Integration](#layout-integration) | In Development | How layouts declare which entities produce shadows |

## Requirements

### Shadow Terminology
----
RID: `req-viz-shadows-terminology`

Status: `In Development`

TAP Viz uses a small vocabulary for multi-location entity representation.

#### Implementation

- A `shadow` is a lightweight visual copy of a node placed inside a location where the entity has a presence but is not canonically positioned.
- A `primary node` is the canonical representation of the entity in the scene. It owns alerts, badges, and interaction state.
- A `shadow group` is the set comprising one primary node and all of its shadows. Every member shares a common `_shadow_group` identifier (set to the primary node's ID).
- A `shadow link` is a visual-only Cytoscape edge connecting a shadow to its primary. Shadow links are not graph edges and carry no semantic meaning beyond identity.

#### Development

"Shadow" was chosen over "ghost" (reserved for future "grid host" concept) and "doppelganger" (implies full copy rather than reduced-fidelity reference). The term communicates both visual lightness and derivative identity.

#### Future

If TAP later needs shadows for purposes beyond multi-homed topology (e.g. cross-projection references), the vocabulary should extend rather than overload these terms.


### Primary Node
----
RID: `req-viz-shadows-primary`

Status: `In Development`

Every multi-homed entity has exactly one primary node in the scene.

#### Implementation

- The primary node is positioned by the layout at whatever level is natural for the entity (typically the nearest common ancestor of all its locations, e.g. VPC-level for a multi-subnet resource).
- The primary node receives all standard visual treatments: type icon badges, alert indicators, full opacity, standard border style.
- The primary node is fully interactive: clickable, draggable, selectable.
- The primary node's `_shadow_group` data field contains the group identifier (the entity's own ID).
- The primary node's `_shadow_role` data field is set to `"primary"`.
- Shadow nodes are excluded from tap navigation — clicking a shadow does not navigate to the entity's object viewer. Only the primary handles navigation.

#### Development

Keeping the primary at a higher level in the nesting hierarchy means it is always visible even when a parent container is collapsed or the viewer hasn't zoomed into a specific subnet. This also provides a natural anchor point for alert placement — there is never ambiguity about which copy of a node should show an alert badge.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-shadows-primary-1 | Single Primary | In Development | Each shadow group has exactly one node with `_shadow_role: "primary"`. | `createShadows` stamps primary; only entities with 2+ location edges qualify |
| req-viz-shadows-primary-2 | Full Visual Treatment | In Development | Primary node renders with standard opacity, borders, badges, and alerts. | Standard Cytoscape styles apply; no shadow-specific overrides on primary |
| req-viz-shadows-primary-3 | Full Interactivity | In Development | Primary node is clickable, draggable, and selectable. | Shadow nodes excluded from tap handler and hit test |


### Shadow Node
----
RID: `req-viz-shadows-shadow-node`

Status: `In Development`

Shadow nodes are reduced-fidelity visual copies placed inside hosting locations.

#### Implementation

- Shadow nodes are real Cytoscape nodes (not HTML overlays) so they participate in zoom scaling and layout.
- Shadow nodes render with reduced opacity (0.5) to signal derivative status.
- Shadow nodes render with a dashed border (2px, slate gray) to further distinguish them from primary nodes.
- Shadow nodes display the same label as their primary.
- Shadow nodes display the same type icon badge as their primary (when `node_style` is `"icon-badge"`).
- Shadow nodes are sized identically to their primary. They inherit the primary's `entity_type`, so the shared `baseSizes[entity_type]` lookup in `projectNested` sizes them the same way. Visual distinction between primary and shadow is carried by opacity and dashed border, not size.
- Shadow node IDs use the format `shadow:<primary_id>:<container_id>`.
- Shadow node data includes:
  - `_shadow_group`: the group identifier (matches primary's entity ID)
  - `_shadow_role`: `"shadow"`
  - `_shadow_primary`: the primary node's ID
  - `_shadow_host`: the container node's ID where this shadow is placed
  - `_is_shadow`: `true` (for style selector and guard checks)
  - `entity_type`: same as primary (for badge eligibility)
  - `icon_url`: same as primary (for badge rendering)
  - `label`: same as primary
- Shadow nodes participate in hover (triggers group highlight) but are excluded from tap navigation.

#### Development

The reduced visual treatment (opacity + dashed border) follows established UI patterns for "reference" or "alias" representations. The viewer should learn that a dashed, translucent node means "this entity lives here but is represented elsewhere." Size matches the primary — a shadow is the same entity rendered with lower visual weight.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-shadows-shadow-node-1 | Reduced Opacity | In Development | Shadow nodes render at 0.5 opacity. | `node[_is_shadow]` style selector |
| req-viz-shadows-shadow-node-2 | Dashed Border | In Development | Shadow nodes render with a dashed border style. | `border-style: "dashed"` in style |
| req-viz-shadows-shadow-node-3 | Same Label | In Development | Shadow nodes display the same label as their primary. | Copied from primary data at creation |
| req-viz-shadows-shadow-node-4 | Size Matches Primary | In Development | Shadow nodes inherit their primary's `entity_type` and are sized via the same `baseSizes` lookup, producing identical dimensions. | No separate shadow-size config |
| req-viz-shadows-shadow-node-5 | Shadow Data Fields | In Development | Shadow nodes carry `_shadow_group`, `_shadow_role`, `_shadow_primary`, `_shadow_host`, `_is_shadow`. | Set by `createShadows()` |


### Shadow Link
----
RID: `req-viz-shadows-link`

Status: `In Development`

Shadow links are visual-only Cytoscape edges connecting each shadow to its primary.

#### Implementation

- Shadow links are Cytoscape edges added at runtime by `createShadows()`, not graph edges from the data model.
- Shadow links render with a dashed line style (6/4 dash pattern).
- Shadow links use a neutral slate color (`#cbd5e1`) that does not compete with graph edge colors.
- Shadow links have no arrowheads.
- Shadow links are non-interactive (`events: "no"`).
- Shadow link IDs use the format `shadow-link:shadow:<primary_id>:<container_id>`.
- Shadow link data includes:
  - `_is_shadow_link`: `true`
  - `_shadow_group`: the group identifier
- Shadow links are excluded from graph analysis and traversal operations.

#### Development

The dashed style distinguishes shadow links from real graph edges at a glance. The absence of arrows avoids implying directionality or data flow between primary and shadow.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-shadows-link-1 | Dashed Style | In Development | Shadow links render with a dashed line (6/4 pattern). | `line-style: "dashed"` + `line-dash-pattern` |
| req-viz-shadows-link-2 | No Arrows | In Development | Shadow links have no arrowheads. | `target-arrow-shape: "none"` |
| req-viz-shadows-link-3 | Non-Interactive | In Development | Shadow links cannot be selected or clicked. | `events: "no"` |
| req-viz-shadows-link-4 | Visual Only | In Development | Shadow links are not graph edges and are excluded from graph operations. | Created at runtime, not from data model |


### Hover Highlight
----
RID: `req-viz-shadows-hover-highlight`

Status: `In Development`

Hovering any member of a shadow group highlights all other members and their connecting shadow links.

#### Implementation

- When the user mouses over a primary node that has shadows, all shadows in its group and their shadow links receive the `tap-shadow-highlight` CSS class.
- When the user mouses over a shadow node, the primary node and all other shadows in the group and all shadow links receive the `tap-shadow-highlight` CSS class.
- Highlight treatment:
  - Shadow nodes: opacity increases from 0.5 to 0.9, border color changes to indigo (`#6366f1`), border width increases to 3px.
  - Primary node: border color changes to indigo (`#6366f1`), border width increases to 3px.
  - Shadow links: color changes to indigo (`#6366f1`), width increases to 2.5px.
- The highlight clears when the mouse leaves all members of the group.
- Highlight is purely visual and does not affect selection state.
- `initShadowInteraction(cy)` wires up mouseover/mouseout listeners on `node[_shadow_group]` and returns a `{destroy}` handle for lifecycle cleanup.

#### Development

Group highlighting is the primary mechanism for answering "where else does this entity exist?" without requiring the viewer to trace edges manually. The hover interaction is lightweight and non-destructive.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-shadows-hover-highlight-1 | Primary Hover Highlights Shadows | In Development | Hovering the primary highlights all shadows and shadow links. | `mouseover` on `node[_shadow_group]` adds class to group |
| req-viz-shadows-hover-highlight-2 | Shadow Hover Highlights Group | In Development | Hovering a shadow highlights the primary, all other shadows, and all shadow links. | Same listener; `_shadow_group` selector matches all members |
| req-viz-shadows-hover-highlight-3 | Highlight Clears on Leave | In Development | Highlight clears when the mouse leaves all group members. | `mouseout` removes `tap-shadow-highlight` class |


### Shadow Nesting
----
RID: `req-viz-shadows-nesting`

Status: `In Development`

Shadow nodes participate in the bounded-layer nesting model through their host container.

#### Implementation

- Shadow creation happens BEFORE `projectNested` so shadows participate in nesting resolution and influence parent container sizing.
- Each shadow node gets a synthetic `_SHADOW_PLACEMENT` edge to its host container. The layout adds a nesting rule matching this edge type (e.g. `(parent:aws_subnet)<-[:_SHADOW_PLACEMENT]-(child)`).
- The nesting resolver assigns each shadow's `_viewport_parent` to its host container through normal single-parent resolution.
- Shadows move with their host container when the container is dragged (via the existing drag-group mechanism).
- Dragging the primary node does NOT move its shadows (they belong to different viewport parents).
- Shadow sizes are resolved by the same `baseSizes[entity_type]` lookup that primaries use. Because `createShadows` copies the primary's `entity_type` onto each shadow node, shadows and primaries of the same entity type share dimensions. No separate shadow-size config is needed.

#### Development

This follows naturally from the existing bounded-layer nesting model. A shadow is just another child of its host container from the perspective of drag-group and layout positioning. The synthetic placement edge pattern mirrors the existing `_VPC_SCOPED` edge pattern used for primary node promotion. No special-casing is needed in the nesting resolver.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-shadows-nesting-1 | Pre-Nesting Creation | In Development | Shadows are created before `projectNested` runs. | `createShadows()` called before `projectNested()` in layout |
| req-viz-shadows-nesting-2 | Synthetic Placement Edge | In Development | Each shadow has a `_SHADOW_PLACEMENT` edge to its host container for nesting resolution. | Edge hidden via `tap-nesting-hidden` class |
| req-viz-shadows-nesting-3 | Viewport Parent is Host | In Development | Shadow node's `_viewport_parent` is its host container after nesting resolution. | Natural result of placement edge matching nesting rule |
| req-viz-shadows-nesting-4 | Drag Follows Host | In Development | Shadows move when their host container is dragged. | Inherits from drag-group.js via `_viewport_parent` chain |
| req-viz-shadows-nesting-5 | Primary Drag Independent | In Development | Dragging the primary does not move shadows. | Different viewport parents in nesting tree |
| req-viz-shadows-nesting-6 | Shadow Size From baseSizes | In Development | Shadow dimensions come from the shared `baseSizes[entity_type]` lookup, matching the primary of the same type. | No `_is_shadow` branch in the sizing step |


### Layout Integration
----
RID: `req-viz-shadows-layout-integration`

Status: `In Development`

Layouts declare which entities produce shadow nodes and where those shadows are placed.

#### Implementation

- Shadow creation is a layout-time operation, not a projection-level declaration.
- The layout module is responsible for:
  - Calling `createShadows(cy, config)` before `projectNested` with:
    - `entityTypes`: which entity types produce shadows (e.g. `["aws_alb", "aws_rds_instance"]`)
    - `edgeType`: which edge type connects entities to host containers (e.g. `"RESIDES_IN"`)
    - `placementEdgeType`: synthetic edge type for nesting resolution (e.g. `"_SHADOW_PLACEMENT"`)
  - Adding a nesting rule in the `projectNested` relationships for the placement edge type.
  - Optionally calling `initShadowInteraction(cy)` after layout to wire up hover. The projection runtime also handles this automatically when shadow nodes are detected.
- The runtime utility module `shadow-nodes.js` provides:
  - `createShadows(cy, config)` — creates shadow nodes, placement edges, and shadow links. Returns `{shadowGroups}`.
  - `initShadowInteraction(cy)` — wires up hover highlighting. Returns `{destroy}`.
  - `removeShadows(cy)` — removes all shadow nodes, links, placement edges, and clears primary data stamps.
- Multi-homed detection: `createShadows` only creates shadows for entities with 2+ matching edges of the specified type. Single-homed entities are unaffected.
- The projection runtime (`projection.js`) manages shadow interaction lifecycle: destroying and re-creating the interaction handle on elevation transitions.

#### Development

Making shadow creation a layout responsibility (rather than a projection-level automatic behavior) gives each layout full control over which entities deserve shadows and how they are positioned. A VPC topology layout knows that RDS instances span subnets; a different layout for the same data might not need shadows at all.

The utility module keeps the boilerplate out of individual layouts while preserving layout authority over the decision of when and where to create shadows.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-viz-shadows-layout-integration-1 | Layout-Driven | In Development | Shadow creation is initiated by the layout module, not automatically by the projection runtime. | `aws-top-level.js` calls `createShadows()` explicitly |
| req-viz-shadows-layout-integration-2 | Utility Module | In Development | `shadow-nodes.js` provides create/destroy/highlight lifecycle. | Three exported functions: `createShadows`, `initShadowInteraction`, `removeShadows` |
| req-viz-shadows-layout-integration-3 | Cleanup on Relayout | In Development | Shadow interaction listeners are destroyed and recreated on elevation change. | `projection.js` manages `shadowInteractionHandle` lifecycle |
| req-viz-shadows-layout-integration-4 | Multi-Homed Threshold | In Development | Only entities with 2+ location edges produce shadows; single-homed entities are unaffected. | `createShadows` checks `locationEdges.length < 2` |

#### Future

- Consider a declarative shadow rule syntax in the projection definition if the pattern becomes common enough that every layout is writing the same multi-homed detection logic.
- Explore whether shadow nodes should participate in search result highlighting.
- Define behavior for shadows when their primary node is hidden by a filter or collapsed parent.
