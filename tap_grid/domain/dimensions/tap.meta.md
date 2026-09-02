# `tap.meta`

## Blurb

Marks a node that describes the grid itself rather than anything in the world — TAP's own reflection, partitioned so it never contaminates a domain query.

## Purpose

The grid holds two populations that look identical to a query and mean opposite things. Most nodes describe something outside TAP: a repository, a runner, an IAM role. A few describe **TAP** — the definition of a dimension, the keystone that says what this instance is. Both are `Entity` rows with types and edges, and without a marker a count of "everything on the grid" silently mixes an instance's self-description into its inventory.

`tap.meta` is that marker. A node carrying it is self-describing metadata; a node without it is an observation of the world.

## Goals

- Separate the grid's self-description from the estate it describes, so neither pollutes a count of the other.
- Make "what does this instance say about itself" a dimension filter rather than a hard-coded list of entity types.
- Keep meta nodes first-class — queryable, edge-connectable, historied — instead of exiling them to a side table.

## Identity

The key is `tap.meta`, under the `tap.` namespace reserved for TAP's own vocabulary (as opposed to a plugin's, which uses its own prefix). Dot notation is the grid's nesting convention (`req-grid-dimension`, Goal 2: dimensions nest via dot notation to form sub-namespaces), so `tap.meta` is the `meta` sub-namespace of TAP's own.

Dimension keys are effectively immutable for the same reason slugs are: they are written into every entity's `dimensions` JSONB and indexed by a GIN index, so a rename is a data migration across the whole grid, not an edit.

## Boundaries

- **Not a permission or visibility marker.** A meta node is not more or less privileged than any other; the dimension says what a node *is about*, never who may read it.
- **Not the same as a plugin's own namespace.** `tap_cares` and `tap.graph` partition by *owner* and *surface*; `tap.meta` partitions by *reflexivity*. A `tap_cares` collector node describes real collection work in the world and is deliberately not meta.
- **Values are open in principle, closed in practice.** Only two node types declare it today. New values are minted by adding a self-describing node type, not by writing a taxonomy up front.

## Neutrality

**TAP-specific and permanently so.** This dimension exists because TAP puts its own configuration on its own grid. A system that kept its metadata out of band would have no use for it. It is not a candidate for any neutral substrate.

## Observability

**Always fully observable — it is declared, never fetched.** `tap.meta` is applied from `DEFAULT_DIMENSIONS` at entity creation (`req-grid-dimension-dc`), so it is present the moment the row exists and cannot be absent because a credential could not see it. This is the opposite of a collected dimension like `github.surface`, whose absence can mean either "not that surface" or "we could not look".

The one real gap is the reverse: nothing yet *enumerates* dimensions on the grid. `Dimension` is a first-class node type with `name` and `description` (`req-grid-dimension-dn`, Implemented), and outside its own definition and tests nothing in production creates one. So "which dimensions exist, and why" is not currently a graph query — it is a source read, which this article is the interim answer to.

## Authoritative Source

- **Source:** `tap_grid/specs/spec-grid-dimension.md` — `req-grid-dimension-dn` (Dimension Node) and `req-grid-dimension-dc` (Default Dimension Application); the declarations themselves in `tap_grid/models.py`
- **Version:** spec status `Implemented`; declarations as of commit `b7b35149`
- **Retrieved:** 2026-08-27

## Prior Art

- `tap_grid/specs/spec-grid-dimension.md` (2026-08-27) — the owning spec: dimensions as contexts and namespaces on the entity spine, nested by dot notation.
- `specs/spec-grid-keystone.md` (2026-08-27) — the keystone contract, which is why `keystone` is one of the two values.
- `specs/spec-ai-integration.md` (2026-08-27) — the machine-legibility argument for why an instance's self-description belongs on the grid at all, and therefore why it needs partitioning off.

## Values

- `dimension` — a `Dimension` node: the definition of a dimension, on the grid. Self-referential on purpose (the dimension vocabulary describes itself in its own terms), and tagged so it is self-identifying regardless of which dimension it happens to define.
- `keystone` — a `Keystone` node: the record of what *this* TAP instance is, where its data came from, and the schema documenting that context. The first thing a session or an AI helper reads to ground itself, which is exactly why it must be separable from the estate it describes.
