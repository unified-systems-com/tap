# Grid Perspective Specification

## Philosophy

Perspective stores alternate source-specific views of the same canonical graph object without forcing those views to overwrite one another. It is the grid capability that models "what this source saw" or "how this observer sees the subject." Agreement and disagreement are derived features built on top of perspective data, not the storage model itself.

## Goals

|    |              |                                                                                           |
| :---: | ---       | ---                                                                                       |
| 1. | Overlay      | Perspective stores partial overlays rather than replacing canonical state                  |
| 2. | Observer-Safe| Multiple perspectives can coexist on the same canonical subject without stomping           |
| 3. | Bootstrap    | Perspective ingest can create missing canonical subjects when the graph is first discovered |
| 4. | Extensible   | Agreement and other comparison features can be layered on later without redefining storage  |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-grid-perspective-record | [Perspective Record Model](#perspective-record-model) | Proposed | One perspective record per subject + perspective + observed_at with a partial payload |
| req-grid-perspective-time | [Perspective Observation Time](#perspective-observation-time) | Proposed | `observed_at` is required for perspective-enabled models |
| req-grid-perspective-bootstrap | [Canonical Bootstrap From First Perspective](#canonical-bootstrap-from-first-perspective) | Proposed | Perspective ingest may create missing canonical subjects and seed bootstrap fields |
| req-grid-perspective-fields | [Perspective Field Policy](#perspective-field-policy) | Proposed | Per-field buckets define bootstrap, perspective-tracked, and excluded behavior |
| req-grid-perspective-presentation | [Perspective Presentation and Derivation](#perspective-presentation-and-derivation) | Proposed | Perspective source truth is stored raw; overlays and agreement are derived at the service/model layer |

## Explanation

Perspective exists because many graph facts are observer-dependent. An outside scanner, an internal scanner, a host agent, and a human analyst may all describe the same canonical subject differently without any of them being useless or necessarily "wrong." TAP must preserve those views side by side.

This capability therefore separates:

- the canonical subject
- the perspective records attached to it
- the derived comparisons or overlays built from those records

Perspective is the storage and modeling layer. Agreement is a later comparison layer on top.

### Perspective Record Model
----
RID: `req-grid-perspective-record`

Status: `Proposed`

A perspective record is a first-class record describing what a specific perspective said about a canonical subject at a specific observed time. It stores a partial overlay payload, not a full shadow copy and not a direct canonical overwrite.

#### Status Details
Not yet implemented. This requirement captures the agreed underlying data model for the first pass.

#### Implementation
The perspective model should support:

1. A pointer to the canonical subject, which may be a node or an edge.
2. A durable perspective identifier describing the viewpoint.
3. A required `observed_at` timestamp.
4. A partial payload containing all claims from that observation event.
5. Optional operational metadata such as confidence, method, actor, source, and batch.
6. Lifecycle status such as active, superseded, or retracted if needed by the implementation.

The record granularity is:

`one perspective record per subject + perspective + observed_at`

with a partial payload containing all claims from that observation event.

Omitted fields in the payload mean "no statement." They do not mean null, false, or absent unless the payload explicitly says so.

#### Development
This record shape gives TAP clean ingest semantics and keeps perspective events self-contained without requiring one row per field path.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-perspective-record-1 | Subject Linkage | Proposed | Each perspective record links to one canonical subject, which may be a node or an edge. | |
| req-grid-perspective-record-2 | Observation Event Granularity | Proposed | TAP stores one perspective record per subject + perspective + observed_at, with all claims from that event in a single partial payload. | |
| req-grid-perspective-record-3 | Partial Overlay Semantics | Proposed | Fields omitted from the payload mean the perspective makes no statement about them. | |

#### Future
If some high-volume data source later needs one-row-per-claim storage, TAP may add a more granular internal representation while preserving this same logical model at the API/service layer.

### Perspective Observation Time
----
RID: `req-grid-perspective-time`

Status: `Proposed`

Perspective-enabled models require explicit observation time so TAP can preserve when a source says the observation was true.

#### Status Details
Agreed for the first implementation. This is one of the key differentiators between perspective and ordinary canonical writes.

#### Implementation
The rules are:

1. `observed_at` is required for perspective records on perspective-enabled models.
2. TAP transaction time remains system-owned and is recorded separately through history/batch mechanisms.
3. `observed_at` is the source/world-time timestamp for the observation event.
4. Perspective ordering and comparison may use `observed_at`, but this does not replace TAP's own recorded time.

#### Development
Requiring observation time avoids silently inventing world-time semantics for source data that is explicitly supposed to represent observed reality.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-perspective-time-1 | Observed At Required | Proposed | Perspective records for perspective-enabled models must include `observed_at`. | |
| req-grid-perspective-time-2 | Distinct From Transaction Time | Proposed | Perspective storage keeps `observed_at` distinct from TAP's own recorded time. | |
| req-grid-perspective-time-3 | Source Time Semantics | Proposed | `observed_at` is treated as the time of the observation event supplied by the source or write path. | |

#### Future
Later work may distinguish `asserted_at` from `observed_at` if TAP begins storing non-observational claims such as analyst judgments or hypotheses.

### Canonical Bootstrap From First Perspective
----
RID: `req-grid-perspective-bootstrap`

Status: `Proposed`

Perspective ingest may discover a subject before TAP has a canonical object for it. In that case, the ingest path must resolve or create the canonical subject before persisting the perspective record.

#### Status Details
Agreed as a first-pass architectural rule. This prevents early-source discovery flows from becoming second-class citizens.

#### Implementation
The ingest flow for a perspective-enabled write is:

1. Resolve the canonical subject using model-specific identity rules.
2. If it does not exist, create it with sensible defaults and required identity/structural data.
3. Persist the perspective record attached to that canonical subject.

Creation-time rule:

- `first one to write wins` applies only to canonical bootstrap fields needed to instantiate the canonical object.
- This is an initialization rule, not a truth rule.

On initial creation, the perspective payload and the canonical object may legitimately match for bootstrap fields. After creation, later perspective writes do not automatically overwrite canonical state unless another canonical update rule explicitly allows it.

#### Development
This preserves practical ingest behavior without collapsing perspective into canonical truth. The key is to keep bootstrap values limited to fields needed to create and identify the canonical subject.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-perspective-bootstrap-1 | Find Or Create Subject | Proposed | Perspective ingest resolves an existing canonical subject or creates one before the perspective record is stored. | |
| req-grid-perspective-bootstrap-2 | Bootstrap Fields Only | Proposed | "First one to write wins" applies only to declared bootstrap fields needed for canonical creation. | |
| req-grid-perspective-bootstrap-3 | No Automatic Later Overwrite | Proposed | Later perspective records do not automatically overwrite canonical fields merely because they were observed later. | |

#### Future
If some entities need stricter identity-resolution rules or quarantine flows for ambiguous subjects, TAP should add explicit resolver policies rather than weakening the canonical bootstrap contract.

### Perspective Field Policy
----
RID: `req-grid-perspective-fields`

Status: `Proposed`

Perspective-enabled models must explicitly declare how fields behave under perspective ingest.

#### Status Details
This requirement captures the agreed first-pass policy buckets and should be treated as the minimum required policy surface for implementation.

#### Implementation
Each perspective-enabled model or edge type should define fields in the following buckets:

1. `bootstrap_from_first_perspective`
2. `perspective_tracked`
3. `excluded_from_perspective`

Semantics:

- `bootstrap_from_first_perspective`
  Fields that may seed canonical state only during first canonical creation.

- `perspective_tracked`
  Fields that may appear in perspective payloads and participate in later comparison/agreement features.

- `excluded_from_perspective`
  Fields that are canonical-only and may not be written through perspective ingest.

Compatibility rules:

1. A field may appear in both `bootstrap_from_first_perspective` and `perspective_tracked`.
2. A field in `excluded_from_perspective` must not appear in the other two buckets.
3. Fields omitted from all buckets are undefined behavior until explicitly classified by policy.

#### Development
This keeps the first implementation understandable while leaving room for more nuanced policy later. It also cleanly expresses the difference between creation-time seeding and ongoing observer-specific claims.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-perspective-fields-1 | Three Policy Buckets | Proposed | Perspective-enabled models expose the three agreed field policy buckets. | |
| req-grid-perspective-fields-2 | Bootstrap And Perspective Compatibility | Proposed | A field may be both bootstrap-capable and perspective-tracked. | Useful for identity fields like port number |
| req-grid-perspective-fields-3 | Excluded Fields Are Isolated | Proposed | A field listed as excluded from perspective cannot also be bootstrap or perspective-tracked. | |

#### Future
Later versions may add policy for promotion from perspective to canonical state, but that is explicitly out of scope for the first pass.

### Perspective Presentation and Derivation
----
RID: `req-grid-perspective-presentation`

Status: `Proposed`

Perspective source truth should be stored raw and presented through service/model-layer overlay assembly. Materialized views are not part of the first implementation.

#### Status Details
Agreed for v1. This requirement keeps the storage model simple while the semantics are still being defined.

#### Implementation
The first implementation should:

1. Store raw perspective records as the source of truth.
2. Assemble overlays and perspective-specific presentations at the service or model layer.
3. Leave agreement/disagreement as a derived comparison feature over perspective records.
4. Avoid materialized views in v1.

Materialized views are considered a future optimization for cached derived interpretations once the overlay and agreement semantics have stabilized.

#### Development
Avoiding materialized views early keeps the capability honest. The team can refine storage and comparison behavior first, then decide later whether any derived shapes are stable enough to cache.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-grid-perspective-presentation-1 | Raw Records Are Source Truth | Proposed | Perspective records remain the authoritative stored form of observer-specific data. | |
| req-grid-perspective-presentation-2 | Overlay Assembly At Service Layer | Proposed | TAP presents overlays and comparisons by assembling perspective records at the service/model layer rather than through v1 materialized views. | |
| req-grid-perspective-presentation-3 | Agreement Is Derived | Proposed | Agreement/disagreement logic operates over perspective records and is not itself the perspective storage model. | |

#### Future
If repeated overlay or agreement queries become expensive at scale, TAP may later introduce cached or materialized derived representations without redefining perspective storage semantics.
