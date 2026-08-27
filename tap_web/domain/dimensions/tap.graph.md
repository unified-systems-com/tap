# `tap.graph`

## Blurb

Partitions the nodes that make up TAP's own user interface away from the nodes describing the estate — so a graph view does not render itself.

## Purpose

`Page`, `Panel` and `LandingPage` are real grid entities. That is deliberate: the UI is data, so a plugin extends the interface by landing nodes rather than by shipping view code. It also means TAP's own dashboards live on the same spine as the repositories and runners those dashboards display.

Without a partition, the obvious query — show me the graph — returns the estate *plus the furniture used to look at it*, and a visualisation of an eight-node inventory arrives with dozens of panel nodes tangled through it. `tap.graph: web` is the line between the instrument and the reading.

## Goals

- Keep interface nodes out of estate queries and estate visualisations by default.
- Let the UI be data — extensible by landing nodes — without that choice leaking into every domain query.
- Give web-origin edges the same stamp as web nodes, so a partition filter holds across a traversal rather than only at the endpoints.

## Identity

The key is `tap.graph`, under the `tap.` namespace reserved for TAP's own vocabulary. The value is declared in exactly one place — `tap_web/dimensions.py`, `WEB_DIMENSIONS` — and every `tap_web` node type and web-origin edge type reads it from there rather than restating the literal (`req-web-page-dim`). That single spelling is the point: a dimension re-typed per model is a dimension that will eventually be mistyped in one of them.

It is a leaf module rather than a constant in `tap_web.models` for a concrete reason worth recording: `TapWebConfig.edge_types` needs the value in its *class body*, which Django evaluates while populating app configs, before the model registry is ready — importing `tap_web.models` there raises `AppRegistryNotReady`.

## Boundaries

- **Not a rendering instruction.** The dimension says a node belongs to the web partition; it says nothing about how, whether, or where it is drawn. That is `DEFAULT_DISPLAY` and the visualisation layer.
- **Not visibility or authorization.** Partition, not permission.
- **Not `tap_viz`'s arrangements and layouts.** Those model how a graph is *presented* and are their own types; this dimension is currently declared by `tap_web`'s page furniture.
- **The declared set is narrower than the observed vocabulary.** Only `web` is declared by a model or edge type today. Other `tap.graph` values exist in fixtures and overrides elsewhere in the tree; they are not part of this article's closed set because nothing *declares* them as a type default. If one becomes a declared default, it belongs here — and the coverage guard will say so.

## Neutrality

**TAP-specific.** It exists because TAP models its own interface as graph data. Any system that did the same would need an equivalent, but the concept is inseparable from that architectural choice and is not a candidate for a neutral substrate.

## Observability

**Always fully observable — declared, never fetched.** Applied from `DEFAULT_DIMENSIONS` at creation (`req-grid-dimension-dc`) for nodes, and from the edge type's registered `default_dimensions` for web-origin edges (`req-grid-dimension-dc-4`). It cannot be missing because a credential could not see it.

The honest caveat is coverage rather than permission: the partition holds only where a type *declares* it. A node landed by a plugin into the web surface without the stamp is invisible to the partition filter and will appear in estate queries — a gap in declaration, not in observation, and exactly what the single-spelling rule in Identity exists to prevent.

## Authoritative Source

- **Source:** `tap_web/dimensions.py` (`WEB_DIMENSIONS`, the one spelling) and `req-web-page-dim`; `tap_grid/specs/spec-grid-dimension.md` for the application semantics
- **Version:** `req-web-page-dim` claim `@8520a04984b4/08c16715b9ad`; declarations as of commit `b7b35149`
- **Retrieved:** 2026-08-27

## Prior Art

- `tap_grid/specs/spec-grid-dimension.md` (2026-08-27) — default-dimension application for nodes and for edge types.
- `tap_web/dimensions.py` (2026-08-27) — the derivation claim and the `AppRegistryNotReady` reasoning behind the module's existence.

## Values

- `web` — the node or edge is part of TAP's own web interface: a `Page`, a `Panel`, a `LandingPage`, or an edge minted by the web layer to connect them. The only declared value, and deliberately singular: the partition is binary — interface or estate — and a second value would need to justify what third thing a node could be.
