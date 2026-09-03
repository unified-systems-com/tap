# Disclosure Flags Specification

## Philosophy

Compliance artifacts that ingest external sources at build time (vulnerability catalogs, advisory databases, scanner outputs, attestation chains) silently degrade when an input is missing. The artifact still serializes, signs, and publishes — but a `kev: 0` count in the report's summary block could mean "evaluated against the CISA KEV catalog and found nothing" or "never loaded the KEV catalog at all." From the JSON alone, the consumer can't tell.

This spec codifies a two-sided discipline that TAP applies to any artifact crossing the producer-consumer boundary:

- **Producer side** (the artifact's emitter): every external-source ingestion path SHOULD record a `<source>_loaded` boolean in the artifact's machine-readable summary, true iff the source was successfully loaded for that build. Silent absence is the bug; missing data is fine only if the missing-ness is named.
- **Consumer side** (TAP panels, decomposers, dashboards reading the artifact): the boolean MUST flow through any decomposition unchanged, MUST be visible somewhere in the UI that consumes the data, and MUST NOT allow "no findings" interpretations to derive from absence when the flag is `false`.

The pattern pairs with [`spec-grift-envelope.md`](../../tap_grid/specs/spec-grift-envelope.md)'s per-emission identity (artifacts accumulate historically; each one carries its own honesty about what ran). It is the structural counterpart to the "don't silently shortcut" principle that runs through the TAP codebase.

Originating example: the `notgeorge/samsite` website's VDR aggregator (`scripts/build-vdr-report.py`). Before disclosure flags were added, a missing CISA KEV catalog produced an empty `kev_cves` set; every finding got `is_kev: false`; the documented "block on KEV" build-gate was silently a no-op. Adding `summary.kev_catalog_loaded` and `summary.dependabot_alerts_loaded` to the artifact made the no-op detectable; adding the `samsite-vdr-ingestion-health` panel that surfaces those flags on `/samsite/compliance` made the no-op visible. Both halves were needed.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | Honesty | Artifacts that take a shortcut at build time disclose it explicitly. No more silent shortcuts disguised as clean signals. |
| 2. | Detectable Regressions | A consumer of the artifact can detect when an upstream ingestion path stops running, without reading commit history or pipeline logs. |
| 3. | Decomposer Preservation | When a collector decomposes an artifact into on-grid nodes, the disclosure flags must land on a node the UI can query. |
| 4. | Unknown ≠ False | Older artifacts that predate a flag's introduction render as `unknown` in the UI, not as `false`. The two states have different operational meaning. |
| 5. | Composable Across Producers | The producer / consumer contract is identical regardless of which artifact carries the flags — VDR, OSCAL SSP, KSI signal, future artifacts. One rule. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-disclosure-flags-naming | [Flag Naming Convention](#flag-naming-convention) | Proposed | `<source>_loaded` (snake-case, lowercase) on the artifact's `summary` block |
| req-disclosure-flags-producer | [Producer Obligation](#producer-obligation) | Proposed | Artifacts ingesting external sources SHOULD emit a disclosure flag per source |
| req-disclosure-flags-decomposer | [Decomposer Preservation](#decomposer-preservation) | Proposed | Collectors copy `summary` verbatim onto the on-grid node's `summary` field |
| req-disclosure-flags-consumer-surface | [Consumer Surface](#consumer-surface) | Proposed | Panels reading flagged artifacts MUST display the flags as a visible UI element |
| req-disclosure-flags-three-states | [Three-State Rendering](#three-state-rendering) | Proposed | `ok` (present + truthy), `missing` (present + falsy), `unknown` (absent) are visually distinct |
| req-disclosure-flags-degraded-render | [Degraded Render Discipline](#degraded-render-discipline) | Proposed | When a flag is `missing`, derived "no findings" claims are qualified; the UI signals the data is incomplete |
| req-disclosure-flags-unknown-not-missing | [Unknown is Not Missing](#unknown-is-not-missing) | Proposed | Absent flag = older artifact, not a regression — must render differently than false |

### Flag Naming Convention
----
RID: `req-disclosure-flags-naming`

Status: `Proposed`

Disclosure flags live on the artifact's `summary` block (or its idiomatic equivalent for the artifact type — `metadata`, `provenance`, etc.) and follow this naming:

- **Snake-case, lowercase.** `kev_catalog_loaded`, `dependabot_alerts_loaded`. Not `kevCatalogLoaded`, not `KEV_LOADED`.
- **Boolean.** `true` iff the source was loaded successfully; `false` iff the load was attempted and failed, OR was never attempted. The distinction between "attempted and failed" vs "never attempted" can be captured in adjacent fields (`<source>_load_error`, `<source>_load_attempted_at`) if the producer cares; the boolean is the minimum contract.
- **`<source>_loaded`** is the canonical shape: noun describing the external source + `_loaded`. Reads naturally: `if not report["summary"]["kev_catalog_loaded"]: ...`.
- **Located in the summary block.** Not in per-finding records (those are derived from the source, not about it). Not in a separate top-level field (that creates an extra location consumers have to remember).

If an artifact ingests N external sources, it carries N disclosure flags. They are independent — one source loading does not vouch for another.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-disclosure-flags-naming-1 | Snake-Case Boolean | Proposed | Flag names are snake_case + lowercase, values are `true`/`false`. | |
| req-disclosure-flags-naming-2 | _loaded Suffix | Proposed | Each flag's key ends with `_loaded`. | |
| req-disclosure-flags-naming-3 | Summary Block | Proposed | The flags live on the artifact's summary/metadata block, not per-finding. | |

### Producer Obligation
----
RID: `req-disclosure-flags-producer`

Status: `Proposed`

An artifact that ingests an external source at build time SHOULD emit a disclosure flag for that source. "External source" here means anything that can fail to load without making the build itself fail — a fetched catalog, an API-returned list, a sibling artifact, a vendor schema.

The flag must be set EVERY build, not just when the load fails. A consumer reading an artifact that lacks the flag entirely can't tell whether the artifact predates the flag (acceptable) or whether the producer regressed and stopped emitting it (silent failure).

Concretely (current example): `scripts/build-vdr-report.py` ingests CISA KEV and GitHub Dependabot alerts. Both ingest functions now return `(value, loaded)` tuples, and `main()` writes `kev_catalog_loaded` and `dependabot_alerts_loaded` to `report["summary"]` every build. The flags are part of the artifact's signed body — Sigstore signing covers them, so a forged "everything ran" claim is detectable.

#### Status Details

Implemented upstream for VDR. Not yet implemented for: OSCAL SSP generation (its `import-profile.href` could carry a `profile_resolved` flag), KSI signal emitter (its `provenance` block could carry a `terraform_state_loaded` / `package_lock_loaded` per ingested source).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-disclosure-flags-producer-1 | Flag Emitted Every Build | Proposed | The producer writes the flag with a value on every build, success or failure. Absence is a regression. | |
| req-disclosure-flags-producer-2 | Inside The Signature | Proposed | When the artifact is signed, the flags are part of the signed body. | |
| req-disclosure-flags-producer-3 | VDR Implemented | Implemented | `vdr-report.json` carries `kev_catalog_loaded` and `dependabot_alerts_loaded`. | Upstream: notgeorge/samsite@436ff9f |
| req-disclosure-flags-producer-4 | OSCAL Profile Flag | Backlog | The OSCAL SSP generator records a `profile_resolved` flag for its `import-profile.href` chain. | Future; aligns with the ROSCALE catalog-lookup follow-up |

### Decomposer Preservation
----
RID: `req-disclosure-flags-decomposer`

Status: `Proposed`

When a TAP collector decomposes an artifact into on-grid nodes (per [`spec-grift-envelope.md`](../../tap_grid/specs/spec-grift-envelope.md)), the disclosure flags MUST land on a node that downstream UI can query — typically by copying the entire `summary` block verbatim into a `summary` JSONField on the artifact's primary node.

The decomposer MUST NOT:

- Strip flags during decomposition because the model schema doesn't enumerate them. (JSONField columns accept any keys; that's the point.)
- Rewrite flag names to a different convention.
- Selectively copy only flags the decomposer knows about. New flags appear upstream without coordination; the decomposer's job is to be a faithful conduit.

The samsite compliance collector's `decompose_vdr_report` already does the right thing — `vdr_report.summary = report.get("summary") or {}` (line 319 of `plugins/samsite/collectors/compliance_collector/decompose.py`). New flags upstream appear on the grid automatically.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-disclosure-flags-decomposer-1 | Faithful Conduit | Proposed | Decomposers copy the summary block verbatim; new flags appear on the grid without code changes. | |
| req-disclosure-flags-decomposer-2 | JSONField Storage | Proposed | The on-grid node stores the summary in a JSONField (no schema enumeration of expected keys). | |
| req-disclosure-flags-decomposer-3 | VDR Decomposer Verified | Implemented | `decompose_vdr_report` copies `summary` verbatim into `vdr_report.summary`. | |

### Consumer Surface
----
RID: `req-disclosure-flags-consumer-surface`

Status: `Proposed`

Any TAP panel or dashboard that renders data derived from a flagged artifact MUST surface the flags somewhere visible in the UI. "Somewhere visible" means:

- One screen away, no clicking required to reveal — a pill row, a header strip, a status icon next to the artifact's identity. Not a tooltip-only and not a "show debug info" toggle.
- Identifying which artifact the flags came from when ambiguity is possible (e.g., the latest emission's flags vs. a deep-linked specific emission's flags).
- Refreshing when the underlying data refreshes — if the panel auto-resolves the latest artifact, the flags shown are the latest's, not stale from a prior render.

The originating implementation: `plugins/samsite/panels/vdr_ingestion_health` renders `kev_catalog_loaded` and `dependabot_alerts_loaded` as ✓/✗/? pills on row-1 of `/samsite/compliance`. Future flagged artifacts (e.g., a future SSP-profile-resolved flag) should add a sibling surfacing.

A panel does NOT need a dedicated "ingestion health" sub-panel to satisfy this — flags can be inline with the artifact's other identity. The samsite VDR ingestion health panel exists because the VDR isn't otherwise prominent on the compliance landing; an OSCAL workbench already shows its source artifact, so adding a flag-pill row to the workbench panel itself is the right shape for SSP-side flags.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-disclosure-flags-consumer-surface-1 | Visible Without Interaction | Implemented | Flags appear in the rendered HTML with no clicks required. | VDR ingestion health panel renders the pill row directly on `/samsite/compliance`. |
| req-disclosure-flags-consumer-surface-2 | Latest-Resolved Flags Match Latest Data | Implemented | When a panel uses the [canonical entity-resolution fallback](../../tap_web/specs/spec-web-panel-entity-resolution-v0.md), the flags shown are from the same emission whose data is rendered. | The VDR panel's fallback query selects the latest `vdr_report`; the same node provides the flags shown. |

### Three-State Rendering
----
RID: `req-disclosure-flags-three-states`

Status: `Proposed`

The UI rendering of a disclosure flag has three states, NOT two:

| State | Trigger | Visual |
| --- | --- | --- |
| `ok` | Flag key present in summary AND value is truthy | Green ✓ pill |
| `missing` | Flag key present in summary AND value is falsy | Red ✗ pill, BOLD, may emphasize via background color |
| `unknown` | Flag key NOT in summary at all | Gray ? pill |

The `unknown` state is essential — it carries different information than `missing`. An older artifact predates a flag's introduction; it isn't a regression. A newer artifact missing a flag the producer should be emitting IS a regression. The UI must distinguish these so users don't chase phantom regressions on archived data.

Consumers are NOT free to collapse the three states into two for visual simplicity. A toggle that flips between "all green vs anything-not-green" forecloses the unknown signal and is forbidden by this requirement.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-disclosure-flags-three-states-1 | Three Distinct Visuals | Implemented | ok, missing, and unknown each have a unique color and glyph. | VDR panel: green check / red cross / gray `?`. |
| req-disclosure-flags-three-states-2 | No Two-State Collapse | Implemented | UI must not collapse unknown into either ok or missing. | VDR panel computes `state` as one of three explicit branches; older reports rendering `unknown` was the originating test case. |

### Degraded Render Discipline
----
RID: `req-disclosure-flags-degraded-render`

Status: `Proposed`

When a flag is in the `missing` state, the consumer panel MUST NOT allow derived "no findings" claims to read as clean. Concretely:

- A panel showing "0 KEV-flagged CVEs" while `kev_catalog_loaded` is false MUST visually qualify the zero — strikethrough, italic, asterisk, "(catalog did not load)" annotation, or equivalent.
- The panel's overall container SHOULD pick up a degraded-state visual cue (e.g., red background on the ingestion-health row, an "unverified" badge on the artifact's identity card).
- The panel SHOULD render an explicit caveat sentence naming the consequence: "Findings derived from <source> are absent by omission, not by clean signal — interpret with care."

This is the rule that closes the original VDR loop: if the producer says "KEV catalog didn't load," the consumer does not allow a user to glance at "0 KEV findings" and conclude "we're clean on KEV." The whole point of the disclosure flag is that absence has a name and the UI uses it.

`unknown` does NOT trigger degraded rendering — it's a separate axis. Lack of producer disclosure is not the same as explicit disclosure of failure.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-disclosure-flags-degraded-render-1 | No Clean "Zero" Render | Proposed | Derived "no findings" counts from a degraded source are visually qualified, not shown as a clean zero. | Not yet implemented by any panel — VDR ingestion health is a meta-panel that doesn't show counts. The first count-bearing consumer of a flagged artifact lands this. |
| req-disclosure-flags-degraded-render-2 | Container-Level Visual Cue | Implemented | The panel container surfaces a visual cue (red background, "unverified" badge) when any of its flags is `missing`. | VDR panel: `samsite-vdr-health-degraded` class flips on when `any_false` is true. |
| req-disclosure-flags-degraded-render-3 | Explicit Caveat Text | Implemented | The panel renders a caveat sentence naming the consequence; the user does not have to infer it. | VDR panel emits a caveat paragraph when any flag is `missing` — "absent by omission, not by clean signal". |

### Unknown is Not Missing
----
RID: `req-disclosure-flags-unknown-not-missing`

Status: `Proposed`

A historical artifact may predate a flag's introduction — the producer began emitting `dependabot_alerts_loaded` at commit X; artifacts collected before commit X don't carry the key. This is normal and expected, especially on a grid that retains per-emission history.

Such artifacts render their flag pill in the `unknown` state, NOT `missing`. The distinction:

- `missing` says: "The producer explicitly recorded that this load failed (or wasn't attempted) for this build." That's a regression-detection signal.
- `unknown` says: "We don't have a producer disclosure either way for this build. The flag may not have existed yet." That's a historical-context signal.

A consumer treating these the same way will produce false-positive regression alerts on every backfill or history-browse. Don't do it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-disclosure-flags-unknown-not-missing-1 | Distinct Treatment | Implemented | Code paths that check for "missing" use `summary.get(key) is False` (or equivalent), not `not summary.get(key)`. | VDR panel: explicit `if not present: state = "unknown"; elif loaded: state = "ok"; else: state = "missing"`. |
| req-disclosure-flags-unknown-not-missing-2 | No False Regression Alerts | Proposed | Alerting / monitoring on disclosure flags doesn't fire on absent keys. | |

## Future Work

Not in v0 scope but worth naming:

- **Per-flag metadata.** Each disclosure flag could grow companion fields: `<source>_loaded_at` (timestamp of the attempt), `<source>_load_error` (string describing the failure), `<source>_load_source_version` (commit/etag/timestamp of the loaded source). Useful for deeper debugging; tracked as a follow-up.
- **Cross-artifact disclosure aggregation.** A TAP-wide "ingestion health" dashboard that aggregates flags across all flagged artifacts on the grid — one screen showing "are all your compliance pipelines running their evaluations." Worth doing once a third flagged-artifact-consumer-panel exists.
- **Producer-side schema enforcement.** A JSON Schema patch that requires `<source>_loaded` keys to exist for every named external source on a given artifact type. Currently the discipline is policed by code review; a schema would make it automatic.
