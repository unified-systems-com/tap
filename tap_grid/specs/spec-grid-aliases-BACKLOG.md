# Grid Alias Specification

## Philosophy

TAP needs a consistent way for one graph subject to be known by multiple names without collapsing all naming into a single unstable string. A server may have a canonical operator-facing name while also being known by a hostname, one or more DNS names, and one or more IP addresses. Some of those names may be direct fields on the server model, while others may be discovered through adjacent graph state several hops away.

This specification separates:
- the canonical entity name
- accepted aliases for that entity
- model-defined naming offers from adjacent graph objects
- model-defined alias acceptance policy on the named subject

The named subject remains authoritative. Other models may suggest names, but they do not get to define what another entity is called. In strict mode the named model must explicitly declare the accepted path back to the naming source, creating a handshake that prevents unrelated or rogue models from spraying names into load-bearing identity surfaces.

Aliases are meant to be searchable and accessible. They are not first-class graph nodes in the first implementation. Accepted aliases are cached on the named entity so the common paths of display, search, and resolution do not require repeated graph traversal.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Stable | Preserve a canonical entity name while allowing multiple changing aliases |
| 2. | Controlled | Keep authority over accepted names with the named model rather than the contributing model |
| 3. | Searchable | Make accepted aliases fast to query without graph-walking on every lookup |
| 4. | Graph-Aware | Allow alias contribution from adjacent graph state, including multi-hop paths |
| 5. | Safe | Prevent undeclared or accidental graph paths from becoming load-bearing names |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-aliases-canonical | [Canonical Name And Alias Split](#canonical-name-and-alias-split) | Proposed | `Entity.name` remains canonical while aliases are stored separately |
| req-grid-aliases-offer | [Alias Offer Contract](#alias-offer-contract) | Proposed | Contributing models may offer alias candidates upstream |
| req-grid-aliases-policy | [Alias Acceptance Policy](#alias-acceptance-policy) | Proposed | The named model controls which offers are accepted and how they are used |
| req-grid-aliases-path | [Path Handshake And Resolution](#path-handshake-and-resolution) | Proposed | Strict acceptance requires compatible path declarations on both sides |
| req-grid-aliases-cache | [Alias Cache And Search](#alias-cache-and-search) | Proposed | Accepted aliases are cached on the named entity for lookup and search |

## Explanation

The canonical generic naming surface for an entity remains the `name` field defined by `req-grid-entity-metadata` in [spec-grid-entity.md](/Users/george/Documents/code/tap/tap_grid/specs/spec-grid-entity.md). This specification does not replace that contract. It extends it by defining how alternate accepted names are offered, filtered, and cached.

The driving distinction is:

| Concept | Meaning |
| --- | --- |
| Canonical name | The authoritative generic name for an entity, stored in `Entity.name` |
| Alias | An alternate accepted name for an entity that may be used for lookup, search, or contextual display |
| Alias offer | A candidate alias suggested by another model or graph-adjacent object |
| Alias acceptance policy | The rules on the named model that decide which offers become aliases and whether any may influence the canonical name |

Aliases may come from:
- direct fields on the named model
- direct fields on a nearby model
- multi-hop graph paths such as `ip_address -> interface -> server`
- future perspective-assembled naming overlays

The first implementation should keep aliases as accepted, structured metadata on the named entity rather than introducing dedicated alias nodes. That keeps the hot paths simple while leaving room for a later graph-native alias object if aliases eventually need their own lifecycle or relationships.

### Canonical Name And Alias Split
----
RID: `req-grid-aliases-canonical`

Status: `Proposed`

The canonical name of an entity and its aliases are distinct concepts and must be stored separately.

#### Status Details
Proposed as the foundational naming rule for multi-name subjects such as servers, interfaces, and DNS-backed objects.

#### Implementation
- `Entity.name` remains the canonical generic name for the entity.
- Accepted aliases are stored separately from `Entity.name` in structured alias metadata on the entity spine.
- Aliases do not automatically replace the canonical name merely by existing.
- A model's alias acceptance policy may optionally declare that some accepted alias kinds are eligible to become the canonical name, but that promotion remains under the named model's control.
- Search and display may consult aliases, but they remain conceptually distinct from the canonical name.

#### Development
This split avoids turning `Entity.name` into a context-dependent or unstable field. It also creates a clear place to support primary-name-only searches versus alias-inclusive searches.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-aliases-canonical-1 | Canonical Name Remains Separate | Proposed | The naming model preserves `Entity.name` as the canonical generic name distinct from aliases. | |
| req-grid-aliases-canonical-2 | Aliases Are Structured | Proposed | Accepted aliases are stored in structured metadata rather than flattened into a single free-text field. | |
| req-grid-aliases-canonical-3 | Aliases Do Not Automatically Rewrite Canonical Name | Proposed | Alias acceptance alone does not force `Entity.name` to change. | |

#### Future
Define whether some models should be able to lock canonical naming entirely so aliases can never become canonical without an explicit operator action.

### Alias Offer Contract
----
RID: `req-grid-aliases-offer`

Status: `Proposed`

Models may declare that they can offer alias candidates to another subject through graph-aware paths.

#### Status Details
Proposed. This is the contributor side of the naming handshake.

#### Implementation
Contributing models may define an `OFFERS_ALIAS` or equivalent class-level configuration describing:
- the alias `kind` being offered such as `ip`, `hostname`, `fqdn`, or `nickname`
- where the offered value comes from
- the graph path along which the offer is made
- whether the offer is intended for primary-name consideration, alias-only use, or both

An alias offer is only a suggestion. It does not become authoritative merely because the contributing model declared it.

The path declaration should describe graph shape rather than become a general-purpose graph query language. The first implementation should favor a constrained ordered-hop contract that can be executed by existing ORM search capabilities rather than inventing a separate query language.

#### Development
This keeps naming contribution near the data that knows how to spell the name while still preserving authority on the receiving subject.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-aliases-offer-1 | Contributing Models Can Declare Offers | Proposed | A contributing model may declare alias offers at the class level. | |
| req-grid-aliases-offer-2 | Offers Carry Alias Kind | Proposed | Each alias offer identifies the kind of alias being offered. | |
| req-grid-aliases-offer-3 | Offers Include Path Shape | Proposed | Each alias offer includes a constrained graph path declaration describing the intended upstream target shape. | Reuse existing ORM search capability where possible |
| req-grid-aliases-offer-4 | Offers Are Suggestive Only | Proposed | Declaring an alias offer does not by itself create an accepted alias on another subject. | |

#### Future
If the constrained path shape later proves insufficient, add expressive power carefully without turning alias declaration into a second graph DSL.

### Alias Acceptance Policy
----
RID: `req-grid-aliases-policy`

Status: `Proposed`

The named model is authoritative over which alias offers it accepts, which kinds are searchable, and which accepted aliases may influence the canonical name.

#### Status Details
Proposed. This is the control surface that makes aliasing safe for load-bearing object identity.

#### Implementation
Named models may define a `ALIAS_POLICY` or equivalent class-level configuration describing:
- acceptance mode such as `strict`, `lazy`, or `hybrid`
- accepted alias kinds
- accepted contributor model types
- accepted path signatures
- normalization and validation rules per alias kind
- relative priority of accepted aliases
- whether a given alias kind is `primary_eligible`, `alias_only`, or rejected

Suggested policy semantics:

| Mode | Meaning |
| --- | --- |
| `strict` | Only explicitly approved offers with compatible reverse path declarations are accepted |
| `lazy` | The subject may retain broader offers as aliases unless explicitly blocked |
| `hybrid` | Strict rules apply to primary-eligible aliases while looser rules may allow alias-only acceptance |

The named model remains the authority. Contributing models may suggest, but the named model decides what it accepts and how accepted aliases are used.

#### Development
This mirrors the direction already taken in draft participation and perspective field policy: risky behavior should be authored, not guessed.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-aliases-policy-1 | Named Model Declares Policy | Proposed | The named model may declare alias acceptance policy at the class level. | |
| req-grid-aliases-policy-2 | Policy Controls Accepted Kinds | Proposed | Alias acceptance policy can allow, reject, or restrict alias kinds. | |
| req-grid-aliases-policy-3 | Policy Controls Canonical Eligibility | Proposed | The named model decides which accepted alias kinds may influence the canonical name. | |
| req-grid-aliases-policy-4 | Policy Supports Strict And Non-Strict Modes | Proposed | The policy surface supports at least `strict`, `lazy`, and `hybrid` acceptance behavior. | |

#### Future
Consider whether some models should support operator-configurable policy overrides without redefining the model-level default contract.

### Path Handshake And Resolution
----
RID: `req-grid-aliases-path`

Status: `Proposed`

Strict alias acceptance requires a compatible path declaration on both the contributing model and the named model.

#### Status Details
Proposed. This is the key control that prevents a rogue model from spraying names across the graph.

#### Implementation
In `strict` mode:
- the contributing model declares the upstream path along which it offers an alias
- the named model declares the accepted reverse path back to the contributing model
- an alias is accepted only if the path declarations are compatible under the alias policy

This creates a handshake:
- contributor offers
- receiver accepts
- compatibility is required before the alias becomes authoritative enough to enter the accepted alias cache

The path syntax should remain intentionally narrow. It should describe path structure, direction, and optional type constraints needed for alias resolution and invalidation. It should not become a general graph query language.

#### Development
This requirement is intentionally conservative. Naming is load-bearing, so acceptance should be explicit where identity mistakes would be costly.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-aliases-path-1 | Strict Mode Requires Handshake | Proposed | In strict mode an alias offer is accepted only when contributor and receiver path declarations are compatible. | |
| req-grid-aliases-path-2 | Receiver Defines Accepted Reverse Path | Proposed | The named model can declare the accepted reverse path back to contributing models. | |
| req-grid-aliases-path-3 | Incompatible Paths Are Ignored | Proposed | Alias offers with incompatible path declarations are not accepted into the alias cache. | |
| req-grid-aliases-path-4 | Path Contract Is Constrained | Proposed | The path declaration surface is intentionally narrower than a general graph query language. | |

#### Future
Document exact path-shape compatibility rules once the first implementation picks the concrete ORM-backed path schema.

### Alias Cache And Search
----
RID: `req-grid-aliases-cache`

Status: `Proposed`

Accepted aliases are cached on the named entity in a searchable structure so common name lookup paths do not require repeated graph traversal.

#### Status Details
Proposed. This keeps the first implementation fast and operationally simple.

#### Implementation
The alias cache should live on the named entity spine and store accepted alias entries with enough metadata to explain why an alias was accepted. A cached alias entry should be able to carry fields such as:
- `value`
- `kind`
- `source_entity_id`
- `source_entity_type`
- `accepted_via`
- `priority`
- `primary_eligible`
- `accepted_at`

The cache stores accepted aliases, not raw offers.

Search behavior should support at least:
- canonical-name-only lookup
- canonical-name-plus-alias lookup
- future filtering by alias kind if needed

Alias cache recomputation should be triggered when relevant contributing nodes, named nodes, or path-participating edges change.

#### Development
This keeps aliases cheap to search and inspect while avoiding the complexity of dedicated alias nodes in the first pass.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-aliases-cache-1 | Accepted Aliases Cached On Entity | Proposed | Accepted aliases are cached on the named entity rather than requiring graph traversal for every lookup. | |
| req-grid-aliases-cache-2 | Cache Stores Accepted Not Raw Offers | Proposed | The alias cache contains post-policy accepted aliases rather than every raw candidate offered by the graph. | |
| req-grid-aliases-cache-3 | Canonical And Alias Search Can Be Separated | Proposed | The search model can distinguish canonical-name-only lookup from alias-inclusive lookup. | |
| req-grid-aliases-cache-4 | Recompute Trigger Surface Exists | Proposed | Alias cache recomputation can be triggered by changes to contributing nodes, receiving nodes, or relevant path edges. | |

#### Future
If aliases later need their own independent lifecycle, relationships, or permissions, reconsider whether a dedicated alias node should be added as a second-layer abstraction above the cached entity alias surface.

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
| Deprecated |  |

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
