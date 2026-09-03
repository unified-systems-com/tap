# Panel Sequence Navigation Specification — v0

## Philosophy

Some TAP entities accumulate as an ordered **sequence of emissions** over time — the same logical artifact re-collected or re-published, landing as distinct nodes (e.g. `compliance_artifact` of a given `kind`, newest-first by `fetched_at`). A viewer that renders one such entity should let the reader **walk the sequence** — open the latest by default, then step back to older emissions and forward again — without leaving the page.

This spec defines a **standalone sequence-navigator panel**: a back/forward selector mounted *above* a content viewer panel on the same page. It is the companion to [`spec-web-panel-entity-resolution-v0`](spec-web-panel-entity-resolution-v0.md): that helper answers *which* entity is current (URL deep-link wins, else a fallback query picks latest); this panel answers *where* in the sequence that entity sits and *what its neighbours are*. Both key off the **same `entity_id_var`** and the **same ordering**, so they compose without coordination.

**It composes, it does not modify.** The selector is a sibling panel, not a change to the content panel. Any viewer becomes navigable by mounting this panel above it and pointing both at the same URL variable — the content panel (e.g. roscale's OSCAL workbench) is untouched. This is the page/panel architecture's movable-subject contract doing exactly what it's for.

**Navigation is plain links, not JS.** Each Older/Newer control is an anchor to `?<entity_id_var>=<neighbour_id>` on the current path. Clicking does a full page navigation; every panel on the page re-resolves to the chosen emission through its normal entity-resolution path. No client state, no JS, bookmarkable at every step.

This graduates the "History timeline panel" future seam named in `spec-web-panel-entity-resolution-v0` (Future Work) — the real use case (the samsite artifact viewers, walking multiple OSCAL/IIW emissions) arrived.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Walk The Sequence | Older/Newer controls step through the ordered emissions of a kind; the content panel follows because both read the same URL var. |
| 2. | Honest Position | The bar shows "N of M" and the current emission's label (a timestamp), and marks the latest explicitly — the reader always knows where they are. |
| 3. | Composes, Doesn't Modify | The selector is a sibling panel; mounting it requires no change to the content panel it sits above. |
| 4. | Reuses Resolution | The ordered sequence is a Gryphon query the panel author writes (newest-first); the panel reuses the entity-resolution query runner rather than a parallel mechanism. |
| 5. | Polished Edges | At the latest, Newer is disabled; at the oldest, Older is disabled; an empty grid renders an informational empty state; a deep link outside the sequence reports total without faking a position. |
| 6. | No Privileged Defaults | The panel bakes in no entity types, kinds, or field names; every instance supplies its `entity_id_var`, ordered `sequence.query`, and label field. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-web-seqnav-panel | [Sequence-Nav Panel Type](#sequence-nav-panel-type) | Implemented | `tap_web.panels.sequence_nav.SequenceNavPanelType`, registered as `sequence-nav` |
| req-web-seqnav-config | [Panel Config Contract](#panel-config-contract) | Implemented | `entity_id_var` + `sequence.{query, label_field, label}` |
| req-web-seqnav-position | [Position Resolution](#position-resolution) | Implemented | Newest-first query; current = URL var, else latest; Older = next index, Newer = previous |
| req-web-seqnav-links | [Navigation Links](#navigation-links) | Implemented | Anchors to `?<entity_id_var>=<neighbour_id>`; full-page nav re-resolves every panel |
| req-web-seqnav-edges | [Edge & Empty States](#edge--empty-states) | Implemented | Disabled ends, empty grid, out-of-sequence deep link |

### Sequence-Nav Panel Type
----
RID: `req-web-seqnav-panel`

Status: `Implemented`

The panel type lives at **`tap_web/panels/sequence_nav/__init__.py`** as `SequenceNavPanelType`, registered in `tap_web/apps.py` under the slug `sequence-nav`. Its view template is `tap_web/panels/sequence_nav.html`; its styling is `tap_web/static/tap_web/css/sequence-nav.css`. It renders only the selector chrome — never the artifact body.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-seqnav-panel-1 | Registered | Implemented | `sequence-nav` is in `panel_type_registry`; pages mount it via `USES_PANEL`. | |
| req-web-seqnav-panel-2 | Chrome Only | Implemented | The panel renders the Older/Newer/position bar; it does not render the resolved entity's content. | |

### Panel Config Contract
----
RID: `req-web-seqnav-config`

Status: `Implemented`

```json
{
  "entity_id_var": "<the URL var the sibling content panel reads>",
  "sequence": {
    "query": "MATCH (a:<type>) WHERE ... AND a.data.<ts> IS NOT NULL ORDER BY a.data.<ts> DESC LIMIT 200",
    "label_field": "<node data field shown per emission, e.g. fetched_at>",
    "label": "<human label for the kind, e.g. OSCAL SSP>"
  }
}
```

- `entity_id_var` — MUST match the `entity_id_var` of the content panel beneath it, so Older/Newer links flip the same variable the content panel resolves on.
- `sequence.query` — a Gryphon query returning the full ordered sequence, **newest-first** (`ORDER BY <ts> DESC`), bounded by a sane `LIMIT`. The panel author owns it; the panel runs it verbatim via the entity-resolution query runner. Include `AND <ts> IS NOT NULL` for the same NULL-sort defence the entity-resolution spec calls for. Gryphon string literals are double-quoted (`\"oscal_ssp\"` in JSON).
- `sequence.label_field` — node data field used for the per-emission label; when absent the panel tries `fetched_at` then `emitted_at`, then the node name.
- `sequence.label` — optional human label for the kind, shown as a prefix.

Concrete instance (samsite OSCAL SSP viewer):

```json
{
  "entity_id_var": "oscal_ssp_artifact_entity_id",
  "sequence": {
    "query": "MATCH (a:compliance_artifact) WHERE a.data.kind = \"oscal_ssp\" AND a.data.fetched_at IS NOT NULL ORDER BY a.data.fetched_at DESC LIMIT 200",
    "label_field": "fetched_at",
    "label": "OSCAL SSP"
  }
}
```

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-seqnav-config-1 | Shared Var | Implemented | `entity_id_var` is read from config and used both to read the current id from the URL and to build neighbour links. | |
| req-web-seqnav-config-2 | Author Owns Order | Implemented | The newest-first ordering is the query's `ORDER BY`; the panel does not re-sort. | |
| req-web-seqnav-config-3 | Label Fallback | Implemented | Absent `label_field` falls back to `fetched_at`, then `emitted_at`, then node name. | |

### Position Resolution
----
RID: `req-web-seqnav-position`

Status: `Implemented`

The panel runs `sequence.query` (reusing `entity_resolution._run_fallback_query`), yielding the newest-first list. The **current** entity is `request.GET[entity_id_var]` if present, else index 0 (latest — matching what the content panel's fallback resolves). With the current index `i` in a list of `M`:

- **position** = `i + 1`, **total** = `M`, **is_latest** = `i == 0`.
- **Older** (back in time) = index `i + 1`; absent at the oldest.
- **Newer** (toward latest) = index `i - 1`; absent at the latest.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-seqnav-position-1 | Latest By Default | Implemented | With no URL var, position is 1 of M and Newer is disabled. | Matches the content panel's latest fallback. |
| req-web-seqnav-position-2 | Older/Newer Semantics | Implemented | Older steps to an earlier emission, Newer to a more recent one, consistent with newest-first ordering. | Verified on the samsite SSP viewer (5 emissions): latest → Older → 2 of 5. |

### Navigation Links
----
RID: `req-web-seqnav-links`

Status: `Implemented`

Each control is an anchor to `?<entity_id_var>=<neighbour_id>` (query-only href, preserving the current path). Clicking is a full-page navigation; the page re-renders and every panel — the selector and the content panel — re-resolves to the chosen emission via its own entity-resolution path. The view is bookmarkable at every position.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-seqnav-links-1 | Query-Only Hrefs | Implemented | Neighbour links set only the query var; the path is unchanged. | |
| req-web-seqnav-links-2 | Whole-Page Re-resolve | Implemented | After navigation the content panel shows the chosen emission (deep-link, no fallback banner). | Verified: Older → workbench shows the older `fetched_at`. |

### Edge & Empty States
----
RID: `req-web-seqnav-edges`

Status: `Implemented`

- **At the latest**: Newer renders disabled (no href). **At the oldest**: Older renders disabled.
- **Empty grid** (`total == 0`): an informational empty state ("No emissions on the grid yet."), not an error block.
- **Out-of-sequence deep link**: if the current id is not in the sequence (e.g. a different kind), the bar reports total ("this emission · M on the grid") without inventing a position — never a false "k of M".
- **Misconfigured / query error**: a single inline message; the page does not crash (the content panel still renders).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-web-seqnav-edges-1 | Disabled Ends | Implemented | Newer disabled at latest; Older disabled at oldest. | |
| req-web-seqnav-edges-2 | Empty Informational | Implemented | `total == 0` renders informational, not error. | |
| req-web-seqnav-edges-3 | No False Position | Implemented | An out-of-sequence current id reports total only, never a fabricated position. | |

## Out Of Scope (v0)

- **Jump-to controls** (first/latest buttons, a dropdown of all emissions, a timeline scrubber). The position resolution already computes first/latest ids; these are additional renderers over the same data when a consumer needs them.
- **Cross-kind sequences** (walking heterogeneous types in one sequence). v0 is one kind per navigator, expressed by the query.
- **Multi-emission accumulation for upsert-keyed types.** The navigator is only as rich as the data: types keyed on an intrinsic id (`ksi_signal` on `signal_id`) accumulate one node per genuine emission, so their sequence grows only on real change; `compliance_artifact` (keyed on `kind/fetched_at`) accumulates per collection. The deferred `compliance_artifact` content-hash re-key (see `plugins/samsite/specs/spec-samsite-viewer-pages-v0.md` Non-Goals) governs whether re-fetches that didn't change content count as distinct sequence members. The navigator renders whatever the grid holds.

## Future

- **Standalone helper extraction.** Position resolution currently lives in the panel's `get_view_context`. If a second consumer needs the prev/next/position computation without the panel chrome, extract a `resolve_sequence(...) -> SequencePosition` helper alongside `entity_resolution.resolve_entity` (the two are deliberate companions).
- **Jump-to / timeline renderers** (see Out Of Scope) when a consumer asks.
