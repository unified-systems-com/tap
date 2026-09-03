# Callsite Identity Convention

## Philosophy

This spec is a standing **convention**, not a feature: it states how TAP's build-time
tree-scanners name *the thing they found, where it is*. It is the center of gravity for
callsite identity, consulted whenever a scanner (`tap/source_scan.py` and every guard
that layers on it — authz-coverage, direct-write, log-site, and their successors)
decides how to key a finding.

The convention exists because a single identity string was silently doing **several
jobs with opposite stability requirements**, and the jobs pulled the scanners apart:

> A callsite finding has separable concerns — a **stable anchor** (drift-proof
> structural identity), a **physical location** (what a human or triage agent
> navigates to), and, when needed, an **occurrence discriminator** (what tells two
> offenses at the same anchor apart). From these compose two derived identities: the
> **occurrence_key** (anchor + discriminator, one per physical offense — the SARIF
> fingerprint) and the **baseline key** (the ratchet entry, at remediation-unit
> granularity). The anchor must be drift-proof; the location drifts by nature; the
> discriminator exists only when an anchor legitimately covers more than one offense.
> Fuse them into one string and you get either baseline churn (a line number in the
> anchor) or lost offenses (a set collapse that drops the location).

### Scope

This convention governs the identity of findings from **ratcheted callsite scanners**
(those with a committed baseline) and **any scanner whose findings feed SARIF export**.
Non-ratcheted structural guards that emit callsite strings only in an error message
(no baseline, no SARIF) are listed in the Conformance Ledger for honesty, and adopt the
model when they gain a baseline or a SARIF surface — not before.

Two observations drive this:

- **The ratchet's natural unit is the remediation unit, and it differs per scanner.**
  authz gating is a *function-level* decorator, so two `write_batch()` calls in one
  function are fixed by one edit and are correctly *one* baseline entry. direct-write
  remediation is *per-call*, so each write is its own entry. This divergence is a
  deliberate, principled choice — not drift to be normalized away. A universal standard
  must *accommodate* both granularities, not force one.
- **Per-offense SARIF export forces the separation into the open.** You cannot emit one
  SARIF result per offense — each with a `physicalLocation` a reviewer can click and a
  `partialFingerprint` that survives edits — until scanners preserve per-occurrence
  locations and stop collapsing to a stable set too early. Settling this convention is
  Phase 0 of the guard-SARIF effort; it is also independently valuable (it kills the
  recurring direct-write baseline churn).

This convention deliberately **coexists with honest accepted debt.** Not every in-scope
callsite scanner conforms today; the point is that each in-scope scanner's identity state
is *recorded* (see the Conformance Ledger), not that all are migrated at once. (Non-callsite
scanners — JSON-naming, secret-leak, plugin-deps, and the like — are out of this
convention's scope entirely and are not on the ledger's hook.) Migration is a follow-on,
sequenced with the SARIF work.

## Goals

|   |   |   |
| :---: | --- | --- |
| 1. | One Identity Model | Every in-scope callsite scanner names findings with the same three-role model (anchor / location / discriminator). |
| 2. | Drift-Proof Baselines | A finding's ratchet key does not change when unrelated edits move code up or down its file. |
| 3. | Per-Offense Addressability | Every physical offense is individually locatable and stably fingerprinted, so SARIF can carry one result per offense. |
| 4. | Honest Per-Scanner Status | Each scanner's current-vs-target identity state is recorded, not implied behind conformance. |

## Prior Art

This formalizes patterns TAP and the wider ecosystem already use:

- **SARIF's own result model** separates the three roles: `physicalLocation.region`
  (where it is), `logicalLocations[].fullyQualifiedName` (the enclosing scope), and
  `partialFingerprints` (stable dedup identity across runs). The convention maps its
  three roles straight onto these.
- **Content-hash-plus-ordinal fingerprinting.** The committed codex-security scan
  already discriminates identical findings with a hashed anchor plus an ordinal suffix
  (`primaryLocationLineHash: "…:1"`). Adopting the same shape means TAP guard SARIF and
  the codex-security scanner SARIF dedupe uniformly in one triage surface.
- **log-site's mint-a-unique-token discipline** (`spec-tap-logging.md`,
  `req-tap-logging-site-id-scanner`): the author mints a `[<hex>]` token whose
  within-file uniqueness is enforced at authoring time, so the anchor is unique *by
  construction* and needs no discriminator. This is the convention's exemplar and the
  reason the standard prefers enforced uniqueness over after-the-fact discrimination.
- **GitHub code-scanning's SARIF ingestion** consumes results with repository-relative
  `physicalLocation.artifactLocation.uri` and `region.startLine`/`endLine`, and keeps
  result *identity* (`partialFingerprints`, used to correlate an alert across runs)
  separate from the clickable physical location. This is exactly the anchor/occurrence_key
  vs location split above, so a conformant TAP finding drops into GitHub code scanning
  unchanged when that CI surface lands.

## The CallsiteIdentity Model

A `CallsiteIdentity` extends the existing `CallSite` (`tap/source_scan.py`, already
documented as *"the shared currency of the tree-scanners… scanners layer their own
richer result types on top"*). It is **three primitives** and **two derived keys**.

Primitives:

- **anchor** — the drift-proof structural id: `<repo-relative POSIX path>::<qualname>::<construct>`
  (construct = sink name, `Model.op`, or an author-minted `[<hex>]` token). It never
  contains a raw line number, and two identical offenses in one scope share it. It is
  the coarsest identity — not necessarily unique per physical offense.
- **location** — path plus region (line span). For navigation only. It drifts freely
  and is *never* part of the anchor or either derived key. This is today's `CallSite`.
- **discriminator** — present only when an anchor can cover more than one physical
  offense. Scheme: a **semantic hash** of the offending construct (recipe in
  `req-tap-callsite-identity-discriminator`), with an **ordinal fallback** for
  byte-identical constructs.

Derived keys:

- **occurrence_key** — `anchor` (+ `discriminator` when present). Identifies exactly one
  physical offense. This is the SARIF `partialFingerprints["tapCallsite/v1"]`.
- **baseline key** — the ratchet's entry identity, at *remediation-unit* granularity:
  equal to the **anchor** when one fix clears every offense sharing it (per-function —
  authz), or to the **occurrence_key** when each offense is fixed independently
  (per-call — direct-write). Never the location.

So the anchor is not "the fingerprint" and not always "the baseline key": the
**occurrence_key** is the SARIF fingerprint, and the **baseline key** is the anchor or
the occurrence_key depending on the remediation unit
(`req-tap-callsite-identity-remediation-unit`). The two coincide only for per-function
scanners with no discriminator.

**SARIF mapping** (the downstream consumer this model is designed for):

| Concern | SARIF field |
| --- | --- |
| occurrence_key | `partialFingerprints["tapCallsite/v1"]` (the discriminator is part of it, e.g. `…#2`, so two occurrences do not dedupe into one result) |
| anchor's qualname | `logicalLocations[].fullyQualifiedName` |
| location | `physicalLocation.artifactLocation.uri` (repo-relative) + `physicalLocation.region` (`startLine`/`endLine`) |

A scanner whose anchor carries no line by design (authz keys `qualname`; a file-only
scanner keys `path`) emits a `physicalLocation` with a `uri` and, where available, a
`region` — and a `logicalLocation` for the scope. Omitting a line the scanner does not
have is honest; fabricating one to fill the field is not.

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-tap-callsite-identity-model | [Three-Role Identity](#three-role-identity) | Proposed | Separate anchor / location / discriminator; each has a stated stability contract |
| req-tap-callsite-identity-anchor | [Drift-Proof Anchor](#drift-proof-anchor) | Proposed | The anchor never carries a raw line number; it is the drift-proof root both derived keys compose from, not itself the ratchet key or SARIF fingerprint |
| req-tap-callsite-identity-remediation-unit | [Ratchet Unit Is The Remediation Unit](#ratchet-unit-is-the-remediation-unit) | Proposed | Key at the granularity a fix clears; do not over-refine |
| req-tap-callsite-identity-scan-rich-collapse-late | [Scan Rich, Collapse Late](#scan-rich-collapse-late) | Proposed | Scanners yield per-occurrence records; collapse to the anchor set only at baseline-diff |
| req-tap-callsite-identity-discriminator | [Discriminator On Demand](#discriminator-on-demand) | Proposed | Discriminate only when an anchor can hold >1 offense; prefer enforced anchor-uniqueness |
| req-tap-callsite-identity-conformance | [Honest Conformance Ledger](#honest-conformance-ledger) | Proposed | Record each in-scope scanner's current-vs-target identity state; re-baseline on anchor-format change |

---

### Three-Role Identity
----
RID: `req-tap-callsite-identity-model`  

Status: `Proposed`  

A tree-scanner finding's identity separates three roles — **anchor**, **location**,
**discriminator** — each with its own stability contract, rather than fusing them into
one string.

#### Implementation

- The **anchor** is stable across unrelated edits (drift-proof) and is the single
  drift-proof *root* both derived keys compose from — the baseline key directly, and the
  SARIF fingerprint via the occurrence_key. It is not itself either key: the ratchet keys
  on the baseline key and SARIF keys on the occurrence_key.
- The **location** (path + region) is expected to drift and is used only for
  navigation; it never appears in the anchor.
- The **discriminator** is optional and present only per `req-tap-callsite-identity-discriminator`.
- The model extends `CallSite` in `tap/source_scan.py` rather than introducing a
  parallel primitive; scanners layer their richer result types on it.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-callsite-identity-model-1 | Roles Are Separable | Proposed | A finding exposes anchor, location, and (optional) discriminator as distinct values, not one fused string. | |
| req-tap-callsite-identity-model-2 | Stated Contracts | Proposed | Each scanner states, for its findings, what its anchor is and why it is drift-proof. | |

---

### Drift-Proof Anchor
----
RID: `req-tap-callsite-identity-anchor`  

Status: `Proposed`  

A finding's anchor is drift-proof: it does not change when unrelated edits move the
offending code up or down its file. A raw line number MUST NOT appear in the anchor.

#### Implementation

- The anchor is composed from stable structure — an enclosing scope qualname, a
  construct name (sink / model+operation), and/or an author-minted token — never a line
  number.
- The line number is retained on the **location** for messages and SARIF regions only.
- This requirement is the direct-write fix: `path:lineno` puts a drift-prone value in
  the drift-proof slot, so it churns; its target anchor is `path::qualname::Model.op`
  with `lineno` demoted to location.
- The anchor feeds both derived keys — the baseline key (directly, per-function; via the
  occurrence_key, per-call) and the SARIF fingerprint (via the occurrence_key). It is
  the single drift-proof root both consumers derive from, not itself "the fingerprint".
- **Path semantics.** The path component is a **normalized repo-relative POSIX path**.
  The anchor is therefore line-drift-proof but *not* file-rename-proof: moving or
  renaming a file changes the anchor, and that is a **reviewed baseline change** (the
  new anchors are the diff a reviewer sees), not silent churn.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-callsite-identity-anchor-1 | No Line In Anchor | Proposed | No scanner's anchor contains a raw line number. | |
| req-tap-callsite-identity-anchor-2 | Single Drift-Proof Root | Proposed | The baseline key and the SARIF fingerprint both derive from the anchor; neither embeds the location. | |
| req-tap-callsite-identity-anchor-3 | Normalized Repo-Relative Path | Proposed | The path component is a normalized repo-relative POSIX path; a file move/rename is a reviewed baseline change. | |

---

### Ratchet Unit Is The Remediation Unit
----
RID: `req-tap-callsite-identity-remediation-unit`  

Status: `Proposed`  

Each scanner names its **remediation unit** — the granularity at which a single fix
clears a finding — and sets its **baseline key** to that granularity. Scanners MUST NOT
key the baseline finer than the remediation unit.

#### Implementation

- authz's remediation unit is **per-function** (one `@requires_capability` clears every
  sink in the function), so its **baseline key is the anchor** (`path::qualname::sink`)
  and two calls in one function are correctly one baseline entry. Its SARIF export still
  emits two results (two occurrence_keys, `…#1`/`…#2`) so both are clickable — the
  discriminator lives in the fingerprint, *not* in the baseline key. Normalizing authz's
  baseline to per-line "for consistency" would churn it for zero remediation value —
  explicitly disallowed.
- direct-write's remediation unit is **per-call** (each write is individually rerouted),
  so its **baseline key is the occurrence_key** — two identical writes in one function
  are two baseline entries, distinguished by the discriminator.
- log-site has two facets: a **well-formed** token is **per-token** (the token *is* the
  fix, and its anchor `path::[<hex>]` is unique by construction), while a **violation** (a
  missing or malformed token) is **per-call** — each offending log call is fixed
  independently by minting a token, and there is no `[<hex>]` yet to key on, so it takes a
  per-call occurrence key until it graduates to the well-formed anchor.
- Divergent remediation granularity across scanners is expected and correct; the
  convention unifies the *model*, not the granularity.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-callsite-identity-remediation-unit-1 | Unit Is Named | Proposed | Each scanner states its remediation unit and sets its baseline key to that granularity (the anchor stays the structural root; it is not refined to baseline granularity). | |
| req-tap-callsite-identity-remediation-unit-2 | No Over-Refinement | Proposed | An anchor is not refined below the remediation unit (no churn for zero remediation value). | |

---

### Scan Rich, Collapse Late
----
RID: `req-tap-callsite-identity-scan-rich-collapse-late`  

Status: `Proposed`  

Scanners return one record **per occurrence**, carrying the full location. The collapse
to the set of baseline keys happens only at the baseline-diff step — never inside the
scanner.

#### Implementation

- The scanner's result type is a *list* of per-occurrence records, each with location
  (and discriminator material), so no offense is lost before consumers see it.
- The **ratchet** path maps occurrences to their baseline-key set at comparison time;
  the **SARIF** path consumes the full per-occurrence stream (one result per
  occurrence_key).
- This is the authz de-collapse: authz's scanner already returns a rich
  `list[SinkSite]`; only the guard `measure()`'s `{s.key(...) for s in …}` collapses
  two calls to one. The fix moves the collapse from the scanner/guard to the
  baseline-diff step, leaving the committed baseline unchanged.
- No consumer other than baseline-diff is permitted to reduce occurrences to baseline
  keys.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-callsite-identity-scan-rich-collapse-late-1 | Per-Occurrence Output | Proposed | A scanner yields one record per physical offense, each with its own location. | |
| req-tap-callsite-identity-scan-rich-collapse-late-2 | Collapse At Diff Only | Proposed | Reduction to the anchor set happens only at baseline comparison, not in the scanner or a report path. | |

---

### Discriminator On Demand
----
RID: `req-tap-callsite-identity-discriminator`  

Status: `Proposed`  

A discriminator is added only when a scanner's remediation unit can legitimately hold
more than one physical offense at the same anchor. Where the author controls the
anchor token, prefer enforcing anchor-uniqueness over discriminating after the fact.

#### Implementation

- **Prefer enforced uniqueness.** log-site forbids duplicate `[<hex>]` within a file at
  authoring time, so its anchor is unique by construction and needs no discriminator.
  This is the preferred design when the anchor is author-minted.
- **Discriminate when uniqueness cannot be enforced.** authz (two `write_batch` in one
  function) and direct-write (two identical writes in one function) scan patterns they
  cannot force unique, so they add a discriminator: a semantic hash of the construct,
  with an ordinal fallback (`…#1`, `…#2`) for byte-identical constructs. Reordering two
  distinct constructs does not swap their hashes; only genuinely identical constructs
  fall back to order.
- The discriminator is part of the **occurrence_key** (`anchor#<disc>`), which is the
  SARIF fingerprint, so occurrences do not dedupe into one result. It enters the
  **baseline key** only for a per-offense remediation unit (direct-write), never for a
  per-function one (authz — see `req-tap-callsite-identity-remediation-unit`).

#### Semantic-hash recipe

To stop three scanners inventing three hashes, the semantic hash is computed over
**scanner-owned canonical material** with **all location attributes excluded**:

- the normalized repo-relative POSIX path,
- the enclosing qualname,
- the construct kind (sink name / write kind),
- the model and operation when statically known,
- a structural dump of the offending AST node with positions stripped —
  `ast.dump(node, include_attributes=False)` (or the scanner's equivalent canonical
  serialization).

`include_attributes=False` (dropping `lineno`/`col_offset`) is what keeps the hash
drift-proof. The hash is the primary discriminant; the **ordinal** (`#1`, `#2`, in
scan order) is the fallback only when two offenses produce the identical canonical
material.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-callsite-identity-discriminator-1 | Only When Needed | Proposed | A discriminator is present only when the remediation unit can hold more than one offense. | |
| req-tap-callsite-identity-discriminator-2 | Uniqueness Preferred | Proposed | Where the anchor token is author-controlled, uniqueness is enforced rather than discriminated after the fact. | |
| req-tap-callsite-identity-discriminator-3 | Stable Scheme | Proposed | Discrimination uses a semantic hash over location-free canonical material with an ordinal fallback, matching the codex-security fingerprint shape. | |
| req-tap-callsite-identity-discriminator-4 | Location Excluded From Hash | Proposed | The semantic hash excludes all location attributes (line/column), e.g. `ast.dump(node, include_attributes=False)`. | |

---

### Honest Conformance Ledger
----
RID: `req-tap-callsite-identity-conformance`  

Status: `Proposed`  

Each scanner's current-vs-target identity state is recorded here, so non-conformance is
a stated choice rather than a silent gap. A change to a scanner's anchor format
re-baselines its ratchet in the same reviewed change.

#### Implementation

Conformance ledger (updated as scanners migrate). "In scope" = has a baseline and/or a
planned SARIF surface (see [Scope](#scope)); non-ratcheted guards
that only put a callsite in an error string are listed for honesty and migrate when they
gain a baseline or SARIF surface.

| Scanner | In scope | Remediation unit | Key today | Conformant? | Migration |
| --- | --- | --- | --- | --- | --- |
| authz (`tap/authz_coverage.py`) | ✅ ratchet | per-function | anchor `path::qualname::sink` | ✅ | **Done** — on `CallsiteRatchet` (PER_ANCHOR); collapse moved to diff-prep, baseline byte-identical; `SinkSite.discriminator` feeds the SARIF occurrence_key |
| direct-write (`tap/direct_write_coverage.py`) | ✅ ratchet | per-call | occurrence_key `path::qualname::Model.op#<disc>` | ✅ | **Done** — scanner enriched (scope stack + `Model.op` + `ast.dump` discriminator); on `CallsiteRatchet` (PER_OCCURRENCE); baseline was comment-only, no entries to re-key |
| log-site — well-formed tokens (`tap/guards/log_site_uniqueness`, `_format`) | ✅ structural | per-token | `path::[<hex>]` (token unique within its file; the path namespaces it → globally unique by construction) | ✅ exemplar (anchor role) | none |
| log-site — violation baseline (`tap/guards/log_site_baseline`) | ✅ ratchet | per-call | occurrence_key `path::qualname::<construct>::<kind>#<disc>` | ✅ | **Done** — scanner walks scope + captures construct (`logger.<level>`/`getLogger`) + kind (missing/fstring/getlogger-arg) as `LogViolationSite`; guard on `CallsiteRatchet` (PER_OCCURRENCE); baseline was empty, no entries to re-key; a site graduates to the well-formed `path::[<hex>]` anchor once a token is minted |
| mypy (`tap/guards/mypy.py`) | ✅ ratchet | per file+code | `path:code:count` | ⚠️ intentionally coarse (aggregate count, no callsite) | out of model by design — not a per-callsite scanner; recorded so the ledger is complete |
| service-gateway (`tap_grid/guards/service_gateway.py`) | ❌ error-string only | per-def | `name:lineno` (message) | n/a today | adopt anchor `path::qualname` if it gains a baseline or SARIF surface |
| recurring-uniqueness (`tap_cares/guards/recurring.py`) | ❌ error-string only | per-callsite | `rel:lineno` (message) | n/a today | adopt anchor if it gains a baseline or SARIF surface |

- An anchor- or baseline-key-format change (direct-write, log-site violation keys)
  regenerates its baseline in the same reviewed change, via the existing ratchet
  re-baseline pattern (`manage.py guards --sync-*` / reviewed baseline edit), so the
  format change and the recorded debt move together.
- This ledger is governed by the honest-risk doctrine
  (`spec-security-posture.md`, `req-sec-honest-risk`): un-migrated scanners are named,
  not hidden.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-tap-callsite-identity-conformance-1 | State Is Recorded | Proposed | Every in-scope callsite scanner appears in the ledger with its current-vs-target identity state. | |
| req-tap-callsite-identity-conformance-2 | Re-Baseline On Format Change | Proposed | An anchor-format change re-baselines the affected ratchet in the same reviewed change. | |

---

## Relationship To Other Specs

- **The SARIF export spec (in progress)** — depends on this convention as its Phase 0.
  Per-offense SARIF results are only possible once scanners obey
  `req-tap-callsite-identity-scan-rich-collapse-late` (locations survive to the export)
  and `req-tap-callsite-identity-anchor` (a stable fingerprint exists). The SARIF spec
  cites those two RIDs as prerequisites and reuses the anchor/location/discriminator →
  fingerprint/region/`#n` mapping.
- **`spec-dev-validation.md`** — owner of the guard/ratchet harness and the Validation
  Map that these scanners' guards appear in. This convention governs *how* those
  scanners identify findings; the Map governs *that* they run. The guards' `rid`s are
  unchanged by this convention (it is a *how*, cited in guard docstrings, not a guard's
  primary requirement).
- **`spec-tap-logging.md`** (`req-tap-logging-site-id-scanner`) — the anchor-uniqueness
  exemplar the convention points to (`req-tap-callsite-identity-discriminator`).
- **`spec-security-posture.md`** (`req-sec-honest-risk`) — governs the Conformance
  Ledger: un-migrated scanners are named honestly, not implied conformant.

## Status Vocabulary

| Status States |  |
| --- | --- |
| Proposed | Requirement has been designed but not yet accepted for implementation. |
| Approved for Development | Requirement is accepted and ready to be implemented. |
| In Development | Actively being worked on. |
| Implemented | Has been written. |
| Verified | Has met the acceptance criteria. |
| Refactoring | In the process of being re-worked. |
| Deprecating | In the process of being deprecated. |
| Deprecated | No longer part of the current architecture. |
