# Draft Dimension Specification

Note: this draft should be reconsidered as a broader pocket-dimensions concept. Using pocket dimensions for draft management is one important use case, but likely not the only one.

## Philosophy

Drafts in TAP should be graph-native. When a user needs to preview or stage changes to a graph-shaped object, TAP should not be forced to rely on purely request-local state or on immediately mutating the canonical graph and then reverting it later.

A draft dimension provides a cleaner model: each draft is its own pocket dimension represented as a sparse overlay on top of canonical graph state. Only the objects and relationships intentionally brought into the draft are copied or shadowed. Everything else continues to resolve from the canonical graph.

This makes draft behavior useful beyond web editing. The same mechanism should be available to API-driven clients, background workflows, and any future tool that needs isolated staged graph changes.

Drafts are also not universally safe. Some model and edge types are load-bearing and should not be draft-enabled casually. Each draft-enabled model must describe exactly how it participates in draft behavior so TAP does not accidentally produce misleading or semantically invalid previews.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Graph-Native | Drafts are represented as graph state, not only as transient request memory |
| 2. | Sparse | Drafts copy only what is necessary rather than forking the entire graph |
| 3. | Reusable | Draft dimensions work for web, API, and other TAP surfaces |
| 4. | Disposable | Each draft can be fully collapsed or removed when it is no longer needed |
| 5. | Safe By Default | Draft behavior is opt-in and model-defined for semantically sensitive types |
| 6. | Evolvable | The first contract supports basic staged graph changes while leaving concurrency and merge policy for later work |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-draft-dimension | [Draft Dimension Model](#draft-dimension-model) | Proposed | Each draft is represented as its own pocket dimension rather than only as unsaved request state |
| req-grid-draft-node | [Draft Node](#draft-node) | Proposed | A first-class Draft node describes and anchors each draft pocket dimension |
| req-grid-draft-overlay | [Sparse Overlay Semantics](#sparse-overlay-semantics) | Proposed | Draft dimensions shadow canonical graph state only where draft entries exist |
| req-grid-draft-definition | [Model Draft Definition](#model-draft-definition) | Proposed | Each draft-enabled model defines exactly how it drafts |
| req-grid-draft-resolution | [Draft Resolution Rules](#draft-resolution-rules) | Proposed | Reading in a draft context resolves draft state first, then canonical |
| req-grid-draft-tombstone | [Draft Tombstones](#draft-tombstones) | Proposed | Drafts need an explicit way to represent removals of canonical objects/relationships |
| req-grid-draft-promote | [Draft Promotion](#draft-promotion) | Proposed | Saving a draft promotes its staged changes into canonical graph state |
| req-grid-draft-discard | [Draft Discard](#draft-discard) | Proposed | Discarding a draft removes its overlay state without touching canonical state |
| req-grid-draft-isolation | [Draft Isolation](#draft-isolation) | Proposed | Multiple drafts may exist without becoming canonical automatically |
| req-grid-draft-concurrency | [Concurrent Drafts](#concurrent-drafts) | Backlog | Coordinating overlapping drafts is deferred to a dedicated later rule set |
| req-grid-draft-merge | [Draft Merge Semantics](#draft-merge-semantics) | Backlog | Merge/conflict semantics are intentionally deferred |
| req-grid-draft-cardinality | [Draft Cardinality Policy](#draft-cardinality-policy) | Backlog | Models may later describe whether they are solo-draft or multi-draft |
| req-grid-draft-drift | [Draft Drift Against Canonical](#draft-drift-against-canonical) | Backlog | Handling canonical changes during the drafting period is deferred |

## Explanation

#### The Core Idea

Canonical graph state remains authoritative.

A draft dimension is a pocket dimension: an isolated, draft-specific slice of graph state that may contain:
- draft copies of existing nodes
- draft copies of existing edges
- draft-created nodes
- draft-created edges
- draft tombstones representing removals of canonical graph elements within the draft view

When TAP resolves graph state inside a draft context, it should prefer draft entries in that pocket dimension when they exist and fall back to canonical state when they do not.

This is intentionally not a full graph fork. Forking the whole graph would be expensive, difficult to reason about, and unnecessary for the editing and preview cases driving this feature. The pocket dimension should contain only objects intentionally copied or created as part of the drafting process.

#### Why Not History Alone

History is still valuable for audit, undo, and provenance. It is not by itself a clean preview mechanism for graph-native staged work because it requires canonical mutation before inspection. Draft dimensions preserve the distinction between:
- staged but not committed graph state
- committed canonical graph state

#### Why Model Definitions Matter

Some entities and edges are safe to draft by straightforward copy-and-shadow rules. Others are semantically load-bearing and should not be automatically draft-enabled.

Examples of draft-risky graph structures:
- hotlink-backed relationships
- edges whose meaning depends on uniqueness or ordering guarantees
- edges with external side effects
- relationships that act as coordination or routing primitives rather than ordinary content links

For this reason, draft participation must be model-defined rather than globally inferred.

#### Why A Draft Node Helps

Pocket dimensions still need a stable graph object that names and anchors the draft itself.

A first-class Draft node gives TAP:
- a stable identity for the draft
- metadata about the draft lifecycle
- a place to store the pocket dimension identifier
- a graph-native way to count and traverse drafts attached to a canonical root object

This avoids overloading dimension keys alone with all draft lifecycle meaning.

### Draft Dimension Model
----
RID: `req-grid-draft-dimension`

Status: `Proposed`

Each draft is represented through its own pocket dimension on the entity spine rather than only as transient request-local state.

#### Implementation
- Each draft has its own dimension identity.
- Draft graph state for that draft is represented using dimensions on backing `Entity` rows.
- Nodes and edges may both participate in draft dimensions because both are entity-backed.
- The draft system should be usable by any TAP surface that can read or write graph state, including web and API clients.
- Draft dimensions are distinct from canonical dimensions and do not become canonical merely by existing.
- A draft pocket dimension should be fully removable once it is promoted or discarded.

#### Development
Keep the draft mechanism below the UI layer. The web editor may consume it later, but the capability should belong to the grid.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-draft-dimension-1 | Each Draft Uses Its Own Dimension | Proposed | Each draft is represented through its own pocket dimension rather than only through request-local editor state. | |
| req-grid-draft-dimension-2 | Nodes And Edges Participate | Proposed | Both nodes and edges may appear in draft dimensions because both are entity-backed. | |
| req-grid-draft-dimension-3 | Surface-Agnostic Capability | Proposed | Draft dimensions are a grid capability usable by web, API, and other TAP clients. | |
| req-grid-draft-dimension-4 | Pocket Dimension Removable | Proposed | A draft pocket dimension can be fully removed after promotion or discard. | |

### Draft Node
----
RID: `req-grid-draft-node`

Status: `Proposed`

Each pocket draft dimension is anchored by a first-class Draft node.

#### Implementation
- TAP defines a `Draft` node type as a first-class graph object.
- Each Draft node represents one draft pocket dimension.
- The Draft node stores or points to the identifier for its pocket dimension.
- The Draft node points to the canonical root object it is about through a `DRAFT_OF` edge.
- The Draft node is the graph-native object used to discover how many drafts hang off a given canonical root object.
- A Draft node may later carry lifecycle metadata such as status, owner, timestamps, or descriptive labels.

#### Development
The Draft node should be the handle people and systems talk about. The pocket dimension is the isolated graph slice behind that handle.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-draft-node-1 | Draft Node Exists | Proposed | TAP defines a first-class Draft node type. | |
| req-grid-draft-node-2 | One Draft Node Per Pocket Dimension | Proposed | Each Draft node anchors exactly one pocket draft dimension. | |
| req-grid-draft-node-3 | Draft Stores Pocket Dimension Identity | Proposed | The Draft node stores or references the identifier for its pocket dimension. | |
| req-grid-draft-node-4 | Draft Points To Canonical Root | Proposed | The Draft node connects to the canonical root object through a `DRAFT_OF` edge. | |
| req-grid-draft-node-5 | Draft Discovery Is Graph-Native | Proposed | Draft counts and draft lookup for a canonical root object are supported through Draft nodes and edges. | |

### Sparse Overlay Semantics
----
RID: `req-grid-draft-overlay`

Status: `Proposed`

A draft dimension is a sparse pocket overlay over canonical graph state, not a full fork.

#### Implementation
- A draft pocket dimension contains only graph elements intentionally copied, created, or tombstoned for that draft.
- Unchanged objects continue to resolve from canonical state.
- The overlay may include:
  - draft copy of a canonical node
  - draft copy of a canonical edge
  - draft-created node
  - draft-created edge
  - draft tombstone
- TAP should not require a full graph duplication to support a draft.

#### Development
Sparse overlays are the design center. If a future use case truly needs a full fork, that should be a separate feature rather than an accidental consequence of draft design.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-draft-overlay-1 | Sparse By Default | Proposed | Draft pocket dimensions contain only the graph elements intentionally brought into draft scope. | |
| req-grid-draft-overlay-2 | Canonical Fallback Preserved | Proposed | Unchanged graph elements continue to resolve from canonical state when no draft override exists. | |
| req-grid-draft-overlay-3 | Full Fork Not Required | Proposed | The draft contract does not require duplication of the entire graph. | |

### Model Draft Definition
----
RID: `req-grid-draft-definition`

Status: `Proposed`

Each draft-enabled model must define exactly how it participates in draft behavior.

#### Implementation
- Draft participation is opt-in.
- A draft-enabled model should provide a draft definition section describing:
  - whether the model may be draft-copied
  - which adjacent edges may be copied into a draft
  - which adjacent nodes may be copied into a draft
  - whether draft tombstones are allowed for the model or its relationships
  - any graph semantics that make the model draft-sensitive
- Edge types may also require draft definitions when their semantics are load-bearing.
- In the absence of a draft definition, TAP should not assume a model or edge type is safe to copy into a draft pocket dimension.
- A draft definition may later also describe draft cardinality policy for the model, but that policy is not part of the first implementation.

#### Development
This keeps the dangerous cases explicit. Draft behavior should be authored, not guessed.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-draft-definition-1 | Draft Participation Is Opt In | Proposed | Models are not assumed to be draft-enabled by default. | |
| req-grid-draft-definition-2 | Model Defines Draft Behavior | Proposed | Each draft-enabled model declares how it participates in draft copying and shadowing. | |
| req-grid-draft-definition-3 | Edge Semantics May Need Definitions | Proposed | Load-bearing edge types may require explicit draft definitions rather than inheriting generic copy rules. | |

### Draft Resolution Rules
----
RID: `req-grid-draft-resolution`

Status: `Proposed`

Graph reads inside a draft context resolve that draft pocket dimension first, then canonical state.

#### Implementation
- A draft context identifies the active draft pocket dimension.
- When resolving an object in a draft context:
  - if a draft shadow exists, use it
  - else if a draft tombstone exists, treat the canonical object as absent in that draft
  - else fall back to canonical state
- The same principle applies to nodes and edges.
- Draft resolution rules should be consistent across service, API, and web entry points.

#### Development
The resolution rule should be simple enough to reason about locally: draft wins, tombstone hides, canonical fills the gaps.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-draft-resolution-1 | Draft Shadow Wins | Proposed | If a draft copy exists for an object, draft resolution returns the draft copy rather than canonical state. | |
| req-grid-draft-resolution-2 | Tombstone Hides Canonical | Proposed | If a draft tombstone exists, the canonical object is treated as absent in that draft context. | |
| req-grid-draft-resolution-3 | Canonical Fallback | Proposed | If no draft override exists, resolution falls back to canonical state. | |
| req-grid-draft-resolution-4 | Resolution Is Cross-Surface | Proposed | Draft resolution rules are shared across grid service, API, and web usage. | |

### Draft Tombstones
----
RID: `req-grid-draft-tombstone`

Status: `Proposed`

Drafts need an explicit way to represent the removal of canonical graph elements inside a draft.

#### Implementation
- Absence of a draft copy does not mean deletion; it means canonical fallback.
- Draft deletion therefore requires an explicit tombstone mechanism.
- Tombstones may apply to:
  - canonical nodes hidden in a draft
  - canonical edges hidden in a draft
- Tombstone behavior must be honored by draft resolution.

#### Development
Without tombstones, a sparse overlay cannot represent deletions safely.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-draft-tombstone-1 | Tombstone Concept Exists | Proposed | Drafts include an explicit mechanism for representing removals of canonical graph elements. | |
| req-grid-draft-tombstone-2 | Tombstones Distinct From Absence | Proposed | Lack of a draft copy does not imply deletion; explicit tombstone state is required. | |

### Draft Promotion
----
RID: `req-grid-draft-promote`

Status: `Proposed`

Saving a draft promotes its staged graph changes into canonical state.

#### Implementation
- Promotion applies the draft overlay into canonical graph state.
- Promotion may include:
  - updating canonical objects from draft shadows
  - creating new canonical objects from draft-created objects
  - deleting canonical objects or relationships represented by tombstones
- Promotion should be the point where history/provenance capture occurs once draft support is implemented.
- Promotion does not imply that drafts are merge-safe; overlapping draft policy is a separate concern.

#### Development
Promotion is the commit point. Draft existence alone should never silently mutate canonical state.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-draft-promote-1 | Explicit Promotion Required | Proposed | Draft state becomes canonical only through an explicit promotion step. | |
| req-grid-draft-promote-2 | Promotion Applies Overlay Semantics | Proposed | Promotion applies staged updates, creations, and removals represented in the draft overlay. | |

### Draft Discard
----
RID: `req-grid-draft-discard`

Status: `Proposed`

Discarding a draft removes its pocket dimension state without mutating canonical graph state.

#### Implementation
- Draft discard deletes or deactivates the draft pocket dimension.
- Canonical graph state remains unchanged.
- Discard must remove the effect of draft shadows and tombstones from future draft resolution for that draft.

#### Development
Discard should be boring and reliable. If draft discard can surprise people, the draft system will not be trusted.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-draft-discard-1 | Discard Leaves Canonical Untouched | Proposed | Removing a draft does not mutate canonical graph state. | |
| req-grid-draft-discard-2 | Pocket Dimension Effect Removed | Proposed | Once discarded, the draft pocket dimension no longer affects graph resolution. | |

### Draft Isolation
----
RID: `req-grid-draft-isolation`

Status: `Proposed`

Multiple draft pocket dimensions may exist without automatically affecting one another or canonical state.

#### Implementation
- Drafts are isolated from canonical state until promoted.
- A draft context must identify which draft pocket dimension is active.
- Multiple drafts may exist simultaneously even if they concern related graph elements.
- This requirement does not yet define how conflicting drafts interact at promotion time.

#### Development
Isolation is required before concurrency policy. We can let multiple drafts exist before we fully define how they collide.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-draft-isolation-1 | Draft Context Identifies Pocket Dimension | Proposed | Reads and writes in draft mode are scoped to a specific draft pocket dimension. | |
| req-grid-draft-isolation-2 | Multiple Drafts May Coexist | Proposed | TAP permits more than one draft pocket dimension to exist at the same time. | |
| req-grid-draft-isolation-3 | Canonical State Not Auto-Mutated | Proposed | Isolated drafts do not affect canonical state until promotion. | |

### Concurrent Drafts
----
RID: `req-grid-draft-concurrency`

Status: `Backlog`

Concurrent drafts that touch overlapping graph elements require explicit conflict and coordination rules, but those rules are deferred.

#### Implementation
Future work must define:
- whether overlapping drafts are always allowed
- whether drafts can lock graph elements
- what happens when one draft promotes over graph elements another draft also shadows
- whether promotion fails, rebases, or creates conflict records

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-draft-concurrency-1 | Concurrent Draft Policy Deferred Explicitly | Backlog | TAP tracks concurrent draft handling as dedicated backlog work rather than leaving it implicit. | |

### Draft Merge Semantics
----
RID: `req-grid-draft-merge`

Status: `Backlog`

Merging, rebasing, and conflict resolution between drafts are separate concerns and should be defined explicitly in later work.

#### Implementation
Future work must define:
- whether draft-to-draft merge exists
- whether draft-to-canonical rebase exists
- conflict representation for nodes, edges, and tombstones
- whether merge behavior is global or model-specific

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-draft-merge-1 | Merge Policy Deferred Explicitly | Backlog | TAP tracks merge semantics as a dedicated backlog concern. | |

### Draft Cardinality Policy
----
RID: `req-grid-draft-cardinality`

Status: `Backlog`

Models may later describe whether they allow multiple drafts at once or prefer a single draft attached to the canonical root object.

#### Implementation
Future work must define:
- whether models may declare `solo_draft` versus `multi_draft` behavior
- whether draft cardinality is enforced at the model level, service level, or both
- whether a shared single-draft mode has different collaboration semantics from ordinary independent drafts

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-draft-cardinality-1 | Draft Cardinality Policy Deferred Explicitly | Backlog | Model-level solo-draft versus multi-draft policy is tracked as dedicated backlog work. | |

### Draft Drift Against Canonical
----
RID: `req-grid-draft-drift`

Status: `Backlog`

Canonical graph state may change while a draft is open. Handling this drift requires explicit policy and is deferred.

#### Implementation
Future work must define:
- how TAP detects that canonical objects or related graph elements changed during the drafting period
- how drift is surfaced to users or API callers
- whether promotion fails, rebases, warns, or creates conflict records when drift is detected
- whether drift handling is global or may vary by model and edge definition

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-draft-drift-1 | Canonical Drift Policy Deferred Explicitly | Backlog | TAP tracks canonical-change handling during the draft period as dedicated backlog work. | |

## Clarifying Questions For Future Work

These questions are intentionally recorded here so the first draft contract can move forward without pretending the hard parts are already settled.

1. What exact dimension keys identify draft overlays, sessions, and ownership?
2. What is the canonical identity relationship between a draft shadow and the canonical object it shadows?
3. Are some edge types globally non-draftable, or is all draft safety expressed only through per-model and per-edge definitions?
4. Does promotion operate as a direct write-through, a diff application, or a FLIP-recorded transaction bundle?
5. How should API callers authenticate and authorize access to shared or collaborative drafts?
6. Should the Draft node carry lifecycle metadata directly, or should some of that live elsewhere?

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed |  |
| Approved for Development | Requirement is accepted and ready to be implemented |
| In Development |  |
| Implemented |  |
| Verified |  |
| Refactoring |  |
| Deprecating |  |
| Deprecated | Not part of the current architecture and should not be implemented |

## RID Format

`req-<application>-<specification>-<feature>-<sub-feature>`

## Requirements Format

`RID: \`...\``
`Status: \`...\``

| Sub-Sections | (as needed) |
| --- | --- |
| Status Details |  |
| Implementation |  |
| Development |  |
| Acceptance Criteria |  |
| Future |  |
