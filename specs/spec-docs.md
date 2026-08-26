# TAP Documentation System

## Philosophy

Specs are the canonical source of truth for *what* TAP does and *why*. Docs are the human- and LLM-readable surface that explains *how* to use, operate, or extend the system. Specs are authoritative; docs are derivative. The two must stay aligned, but their lifecycles are different — specs change when behavior changes, docs change when how-we-explain-it changes — so they need their own mechanisms for drift detection rather than being collapsed into one.

This spec defines the documentation system: where docs live, how they reference specs, how each doc is itself owned by a spec, and the conventions that keep both sides aligned without depending on an LLM remembering to update them.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Two-Way Linkage | Every doc points to its owning spec; every owning spec points back at the doc. Refactoring a requirement surfaces affected docs via grep. |
| 2. | Lifecycle Tracking | Each doc has a status (Proposed → Implemented → Verified → Deprecated) carried in its owning spec, the same vocabulary specs use. |
| 3. | Drift Detection | A change to a spec or a key implementation file flags the doc for review, via explicit `update-triggers:` and conventions baked into CLAUDE.md. |
| 4. | LLM-Friendly | Docs carry frontmatter that lets an LLM efficiently decide whether to read a doc, and what's expected to be true after reading it. |
| 5. | Zero-Drift Metadata | All version and edit history is derived from git, never stored in files. Git is the single source of truth for what changed and when. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-docs-location | [Docs Live in `docs/`](#docs-live-in-docs) | Refactoring | Superseded in part by `spec-sphinx-capability-docs.md`; root `docs/misc/` is the loose drawer |
| req-docs-naming | [Doc and Doc-Spec Naming](#doc-and-doc-spec-naming) | Proposed | `doc-` prefix; `-doc.md` suffix on owning specs |
| req-docs-frontmatter | [Frontmatter Schema](#frontmatter-schema) | Proposed | Required and optional fields |
| req-docs-owning-spec | [Each Doc Has an Owning Spec](#each-doc-has-an-owning-spec) | Proposed | Doc-spec is its own file |
| req-docs-spec-linkage | [Spec Linkage in Body](#spec-linkage-in-body) | Proposed | Spec link on second line of body |
| req-docs-versioning | [Git-Derived Versioning](#git-derived-versioning) | Proposed | No version metadata stored in files |
| req-docs-change-history | [Change History via Git](#change-history-via-git) | Proposed | Doc-only commits when possible; git is the changelog |
| req-docs-drift-conventions | [Drift Detection Conventions](#drift-detection-conventions) | Proposed | CLAUDE.md and memory rules |
| req-docs-rid-integrity | [Referenced RIDs Resolve](#referenced-rids-resolve) | Implemented | Mechanize the honor-system half of drift-conventions: every `req-*` cited in a living doc/spec/agent-guide resolves to a defined requirement |
| req-docs-landing-page | [Docs Landing Page](#docs-landing-page) | Backlog | Top-level index doc for human/LLM orientation |
| req-docs-ref-resolution | [Structured Doc-Reference Resolution](#structured-doc-reference-resolution) | Backlog | Core shape: a structured doc reference resolves to a canonical doc target; emitters produce refs now, resolution deferred; web rendering is a separate concern |

### Docs Live in `docs/`
----
RID: `req-docs-location`
Status: `Proposed`

All repo-level TAP docs live under a top-level `docs/` directory. The original flat-directory convention has been superseded by [spec-sphinx-capability-docs.md](spec-sphinx-capability-docs.md): existing loose development docs now live in `docs/misc/`, while app and plugin capability docs may live under `tap_<app>/docs/` and `plugins/<slug>/docs/`.

`docs/misc/` is intentionally a "stuff drawer" for development, LLM, and cross-cutting notes that are useful but not worth precisely categorizing. Source docs only live there; generated Sphinx artifacts are build outputs.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-docs-location-1 | Top-level docs/ exists | Proposed | A `docs/` directory exists at the repo root, gitignore-tracked. | |
| req-docs-location-2 | Misc drawer | Proposed | Loose repo-level docs live under `docs/misc/`. | Supersedes the earlier flat-only convention. |

### Doc and Doc-Spec Naming
----
RID: `req-docs-naming`
Status: `Proposed`

- **Doc files:** `docs/doc-<system>-<name>.md` — kebab-case, `doc-` **prefix** marks the file as a doc.
- **Doc specs:** `specs/spec-<system>-<doc-name>-doc.md` — the standard `spec-` prefix is preserved (these are specs); the `-doc` **suffix** is the marker that distinguishes a doc-owning spec from a feature spec.

The asymmetry is intentional: doc files use a prefix because that's what users see when browsing `docs/`; doc specs use a suffix because they live alongside feature specs in `specs/` and the `spec-` prefix must stay consistent for grep and ordering.

`<system>` is the same identifier the doc covers (`dev-multisession`, `tap-grid`, etc.). `<name>` is the doc's specific subject (`onboarding`, `runbook`, etc.).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-docs-naming-1 | Doc filenames follow pattern | Proposed | Every file in `docs/` matches `doc-<system>-<name>.md`. | |
| req-docs-naming-2 | Doc-spec filenames follow pattern | Proposed | Every doc-owning spec matches `spec-<system>-<doc-name>-doc.md`. | |

### Frontmatter Schema
----
RID: `req-docs-frontmatter`
Status: `Proposed`

Every doc opens with a YAML frontmatter block. Required fields anchor the doc to its spec and audience; optional fields aid LLM orientation and drift detection.

```yaml
---
# Required
spec: specs/spec-<system>-<doc-name>-doc.md     # the doc's owning spec
audience: [developer, llm]                       # one or more of: developer, operator, contributor, llm

# Recommended
covers:                                          # specs and/or RIDs this doc references
  - specs/spec-<system>.md
  - req-<system>-<feature>
update-triggers:                                 # changes that should prompt re-reading this doc
  - <plain-English description of what change matters>

# Optional, for LLM orientation
assumes:                                         # prerequisite knowledge (one-liners or links)
  - <prerequisite>
provides: |                                      # what the reader can do/know after reading
  <single-paragraph outcome>
---
```

Notes:
- `audience` MUST include `llm` if the doc is intended to be referenced by Claude during development. This is the default for TAP docs because LLMs are first-class readers here.
- `update-triggers` is the primary mechanism for AI-driven drift detection. List concrete things ("changes to `scripts/dc` behavior", "changes to the port registry table") rather than vague areas ("infra changes").
- **No version, last-edited, or last-reviewed fields.** All of those derive from git — see [Git-Derived Versioning](#git-derived-versioning) and [Change History via Git](#change-history-via-git).

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-docs-frontmatter-1 | Required fields present | Proposed | Every doc carries `spec` and `audience`. | |
| req-docs-frontmatter-2 | Recommended fields present where applicable | Proposed | Most docs carry `covers` and `update-triggers`. | |

### Each Doc Has an Owning Spec
----
RID: `req-docs-owning-spec`
Status: `Proposed`

Every doc has exactly one owning spec, which is a separate file at `specs/spec-<system>-<doc-name>-doc.md`. The doc-spec captures:

- **Intent** — why the doc exists, what reader problem it solves.
- **Scope** — what the doc covers and explicitly does not cover.
- **Re-evaluation triggers** — narrative version of the doc's `update-triggers:` frontmatter, with reasoning. Why this list, not some other list.
- **Linked specs** — every spec/requirement the doc references.
- **Lifecycle requirements** — Proposed → Implemented → Verified → Deprecated, like any other spec.

A single doc-spec MAY own multiple closely-related docs (e.g. an onboarding doc + a quick-reference cheatsheet for the same system) when their lifecycles are inseparable. Default to one-doc-per-doc-spec.

The doc-spec being its own file (rather than a section inside another spec) means: a doc covering five other specs has one home for its lifecycle metadata, and all references to "what does this doc do" point to one place.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-docs-owning-spec-1 | One owning spec per doc | Proposed | Every doc has a `spec:` frontmatter pointing to a `spec-*-doc.md` file. | |
| req-docs-owning-spec-2 | Doc-spec captures intent and triggers | Proposed | Doc-spec includes Intent, Scope, Re-evaluation triggers, Linked specs, Lifecycle. | |

### Spec Linkage in Body
----
RID: `req-docs-spec-linkage`
Status: `Proposed`

The doc body's first line is an H1 title. The doc body's second line is a markdown link to the owning spec. This creates a visible reading-time link in addition to the frontmatter. Body content begins on subsequent lines.

```markdown
# Onboarding a New Multi-Session Dev Environment

Spec: [spec-dev-multisession-onboarding-doc.md](../specs/spec-dev-multisession-onboarding-doc.md)

The rest of the doc starts here...
```

Within the body, references to specific requirements use markdown links to RID anchors:

```markdown
This procedure satisfies [req-dev-multisession-spawn-script](../specs/spec-dev-multisession.md#spawn-script).
```

Inline RID links serve drift detection: a `grep -r req-dev-multisession-spawn-script docs/` reveals every doc the requirement touches, so refactoring the requirement is a tractable lookup.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-docs-spec-linkage-1 | H1 then spec link | Proposed | Body line 1 is H1, body line 2 is the spec link. | |
| req-docs-spec-linkage-2 | RID links in body | Proposed | Requirement references in the body are markdown links to RID anchors. | |

### Git-Derived Versioning
----
RID: `req-docs-versioning`
Status: `Proposed`

No version, edit-time, or review-time metadata is stored in doc frontmatter. All of it derives from git on demand:

- `last-edited`: `git log -1 --format=%cI <file>` (ISO timestamp of the last commit touching the file).
- `version`: `git log -1 --format=%h <file>` (short SHA of the last commit touching the file).
- Full edit history: `git log <file>` — the canonical changelog.

The git history is the single source of truth. Any human or LLM that wants to know what changed in a doc can run `git log -- <file>` and read the actual diff. Storing duplicate metadata in the file itself can only drift away from this truth, so we don't.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-docs-versioning-1 | No version metadata in files | Proposed | No doc frontmatter contains `last-edited`, `last-reviewed`, or `version` fields. | |
| req-docs-versioning-2 | Git derivation works | Proposed | `git log -1 --format=%cI <doc>` returns a valid ISO timestamp. | |

### Change History via Git
----
RID: `req-docs-change-history`
Status: `Proposed`

The git log is the doc changelog. Two commit conventions keep that log readable:

1. **Doc-only commits** when a doc change is not paired with a behavior change (typo fix, clarification, re-organization, link repair, audience update). This makes `git log -- docs/<file>` read like a clean changelog of doc-level edits.
2. **Bundled commits** when a doc change accompanies a behavior change in the same PR (a new feature lands and its onboarding doc updates with it). They ship in one commit so any checkout is internally consistent — code and the doc that explains it move together.

Commit messages for doc changes should describe **what changed in the doc and why**, not just "update docs". Future readers (human or LLM) running `git log -- <file>` should be able to understand the trajectory of the doc from subjects alone.

#### Implementation

A future helper `scripts/doc-history <file>` may print a formatted git log (subject, date, author) for a given doc, but is not required — `git log --format='%cd %s' -- <file>` already does this in one line.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-docs-change-history-1 | Doc-only commit convention documented | Proposed | CLAUDE.md describes when to make doc-only vs bundled commits. | |
| req-docs-change-history-2 | Descriptive doc commit subjects | Proposed | Doc commits use descriptive subjects, not generic ("update docs"). | |

### Docs Landing Page
----
RID: `req-docs-landing-page`
Status: `Backlog`

A top-level landing doc at `docs/doc-index.md` (or similar) serves as the directory for all TAP docs. Purpose: the first place a human or LLM looks when deciding which doc to read. Contains:

- One-line summary per doc (audience, what it's for).
- Link to the doc and its owning spec.
- Optional grouping by audience or topic when the count grows.

This doc is itself owned by a doc-spec and follows the same conventions as every other doc.

#### Status Details

Backlog because we have only one doc to start with — a directory of size 1 is overhead. Promote to Approved for Development when the doc count reaches ~3 or when the first orientation friction shows up (someone — human or LLM — asks "what docs do we have?").

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-docs-landing-page-1 | Index lists every doc | Backlog | `docs/doc-index.md` enumerates every doc in `docs/` with summary and audience. | |
| req-docs-landing-page-2 | Owned by a doc-spec | Backlog | The landing doc has its own `spec-docs-index-doc.md` owning spec. | |

### Structured Doc-Reference Resolution
----
RID: `req-docs-ref-resolution`
Status: `Backlog`

Subsystems already *emit* structured references to canonical documentation before any surface can *resolve* them. The collector self-test contract is the first emitter: `CollectorDocRef` (`tap_cares/specs/spec-tap-cares-collector.md` `req-tap-cares-collector-self-test-5`) carries `plugin`, `doc`, `section`, `label`, and a derived `ref` string of the form `<plugin>/<doc>#<section>`. AWS and KSI collectors attach these to non-ready self-test checks today. Nothing turns them into a navigable target yet — they round-trip as opaque strings.

This requirement defines the **core architectural shape** of doc-reference resolution, and deliberately stops at the shape:

- **Reference shape (stable now).** A structured doc reference is `{plugin, doc, section?, label?}`. The `<plugin>/<doc>` pair maps to a doc file under the [Doc and Doc-Spec Naming](#doc-and-doc-spec-naming) convention (`req-docs-naming`); `section` is an in-doc anchor; `label` is display text. Emitters MAY produce references for docs that do not exist yet — a reference is a *claim about where the explanation will live*, not a guarantee it is written.
- **Resolution contract (deferred).** A resolver takes a structured reference and returns a canonical doc target (resolved doc path + anchor) or a typed "unresolved" result — never an exception, never a fabricated link. Resolution is **application-agnostic**: the same contract serves a web UI, an API response, or an agent. It belongs here, in the docs system, not in any one consuming application.
- **Separation of concerns (the point of specifying this now).** *Resolution* (ref → canonical doc target) is a docs-system concern owned by this requirement. *Rendering* (turning a resolved target into a clickable link, a route, an HTMX surface) is a web-UI concern owned by `tap_web/specs/spec-web-rendering.md` `req-web-rendering-docref`. *Emission* (producing refs) is each emitting subsystem's concern (collectors: `req-tap-cares-collector-self-test-5`). Three concerns, three homes, named now so the touchpoints are known before anything is built.

Until this lands, the interim contract is explicit: emitters produce references, consumers display the raw `ref`/`label` strings, and no resolution or navigation is implied. That interim behavior is a *named stub*, not an oversight — every consuming spec and code seam points back at this RID.

#### Status Details

Backlog. There is exactly one emitter (collector self-tests) and zero rendered docs, so a resolver would resolve nothing. Promote to Approved for Development when the first real `docs/` page that a self-test should point at exists, or when a second emitter appears — whichever first creates demand for resolution rather than display.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-docs-ref-resolution-1 | Reference Shape Is Canonical | Backlog | The `{plugin, doc, section?, label?}` structure (and its `<plugin>/<doc>#<section>` `ref` form) is the one doc-reference shape; emitters conform to it. | `CollectorDocRef` is the reference implementation. |
| req-docs-ref-resolution-2 | Resolution Is Application-Agnostic | Backlog | The resolver is a docs-system capability usable by any surface (web, API, agent); it is not implemented inside a consuming application. | |
| req-docs-ref-resolution-3 | Unresolved Is A Typed Result | Backlog | Resolving a reference to a not-yet-written or unknown doc returns a typed "unresolved" result, never an exception or a fabricated link. | |
| req-docs-ref-resolution-4 | Rendering Is Out Of Scope Here | Backlog | This requirement defines resolution only. Rendering a resolved target as a navigable link is owned by `req-web-rendering-docref`. | Concern separation. |
| req-docs-ref-resolution-5 | Interim Stub Is Named | Backlog | Until resolution lands, consumers display raw `ref`/`label` and every deferral points at this RID rather than a vague "future docs surface". | |

### Drift Detection Conventions
----
RID: `req-docs-drift-conventions`
Status: `Proposed`

Two complementary mechanisms keep docs and specs aligned:

**Convention (CLAUDE.md):** when editing a spec or a file flagged by some doc's `update-triggers:`, search `docs/` for any reference to that spec/RID/concept; review hits and update the doc when its content has drifted from current behavior. When editing a doc, re-read its `spec:` and skim its `covers:` list to confirm the doc still aligns. Doc-only commits (or bundled commits when a behavior change ships) form the audit trail — see [Change History via Git](#change-history-via-git).

**Manual checklist (doc-spec template):** every doc-spec carries a Re-evaluation triggers section listing what changes should prompt a doc re-read. When implementing a change in any of those triggers, the doc-spec's lifecycle requires a doc review pass.

A future linter pass (out of scope for now) could enforce: every doc has a valid `spec:` link, every owning spec exists, every RID in `covers:` resolves, and the git timestamp of any file in a doc's `update-triggers:` list is not newer than the doc's own `git log -1` timestamp (would suggest the doc has not been re-touched since the trigger fired). Layer 3 in the spec-dev-multisession discussion. Add only if drift becomes a real problem. **The RID-resolution slice of that linter is now specified separately as [Referenced RIDs Resolve](#referenced-rids-resolve) (`req-docs-rid-integrity`) — the demand signal arrived (2026-08-11).**

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-docs-drift-conventions-1 | CLAUDE.md guidance | Proposed | CLAUDE.md includes a "Documentation drift" section describing the spec ↔ doc review workflow. | |
| req-docs-drift-conventions-2 | Memory rule | Proposed | A feedback memory captures the doc-review-on-spec-edit rule and vice versa. | |

### Referenced RIDs Resolve
----
RID: `req-docs-rid-integrity`
Status: `Implemented`

The documentation system is held together by `req-*` cross-references: docs cite them,
`covers:` lists enumerate them, and the agent guides (`CLAUDE.md`, `AGENTS.md`) point
sessions at them. Today only *guard* and *declared-surface* RIDs are machine-checked
(`test_guard_rid_resolves`, `test_declared_surface_rid_resolves`); every other citation
rests on the grep discipline in [Drift Detection Conventions](#drift-detection-conventions).
Rename or retire a requirement and each doc citing the old RID strands silently. The
reader most harmed is **Player 3** (`spec-ai-integration.md`): AI sessions ground
themselves by *chasing RIDs*, so a dangling reference quietly poisons an agent's grounding
— a machine-legibility defect, not a cosmetic one.

**Demand signal (2026-08-11):** near-misses caught only by hand — a strategy doc whose
forecast had silently become history, and the `uuid5` rename class where string-level
renames miss derived references. Cheap now: the hard half already exists —
`tap.guards.base.defined_requirement_rids()` resolves the *definition* side (an `RID:`
heading or a table-row cell — deliberately NOT an inline mention), so only the
*reference* side is unbuilt.

**Shape.** A standalone script (the `scripts/check-dco` / `scripts/change-tier` pattern —
ONE artifact, MANY invokers) that collects `req-*` tokens from the living surfaces,
subtracts `defined_requirement_rids()`, and fails on the remainder. Run it as (a) a cheap
always-on CI job — it is grep-speed, so it fits even the ~1-minute **docs tier**, closing
the gap that a lane-only test would leave for a brand-new doc citing a typo'd RID
(`req-dev-validation-product-line-lanes-7`) — and (b) a pytest wrapper for local runs.

**Scope decision, made:** archival corpora (`docs/aar/`, `docs/postmortems/`, dated
handoffs) legitimately cite retired requirements — they describe the past, and a dead RID
there is a *record*, not drift. They are **excluded** (the recommended option), by a named
directory rule stated once in `tap.spec_trace`.

#### Implementation

`tap/spec_trace.py` owns both halves and is the **one** parser of the spec corpus:
`load_corpus()` builds a `Requirement` per `RID:` heading (status, ACIDs, normalized body,
content hash); `dangling_citations()` subtracts it from every citation found in the living
surfaces. `defined_requirement_rids()` in `tap/guards/base.py` now delegates here rather
than keeping a second regex pair — the definition of "what RIDs exist" is derived once.

Two invokers over that one artifact: `scripts/check-rids` (docs tier and any ad hoc run)
and the `rid-reference-integrity` ratchet (`tap/guards/rid_integrity.py`) for the pytest
lanes and `manage.py guards --check`.

**Reserved placeholder namespace — `req-example-*`.** Documentation *about* the RID
convention must name RIDs that do not exist (a template, a `grep` example, this spec).
Without a reserved prefix each becomes a permanent baseline entry that can never be
remediated — the stale-exemption smell. Authors write `req-example-…` and the scanner
skips it. This is the narrow, review-visible escape hatch for illustrative prose, and the
same idiom as `# noqa: TAP-LOG-ID`.

**Two precision rules the live corpus forced**, both regression-tested in
`tap/tests/test_spec_trace.py`: a citation is never preceded by a word character or a
hyphen (else the filename `spec-req-<name>.md` yields a phantom for its trailing segment),
and never immediately followed by a hyphen (else a citation wrapped across a line is
captured as its truncated stem). Both produced phantoms against the real tree before they
were added.

#### Development

The `.sec` facet convention had silently defeated the original resolver: its character
class excluded `.`, so all 30 dotted RIDs resolved as their undotted stems, and every
`.sec` citation *looked* valid while pointing at a requirement that does not exist.
Fixing it immediately surfaced a real consequence — `tap/guards/surfaces.py` declared the
read-only-search write-detection surface against the *undotted stem* of
`req-grid-search-readonly.sec`, which was never a requirement at all; it now names
`req-grid-search-readonly.sec-6`, the criterion that actually describes that surface.

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-docs-rid-integrity-1 | Referenced RIDs resolve | Implemented | Every `req-*` token cited in a living doc, spec cross-reference, or agent guide resolves to a requirement defined per `defined_requirement_rids()`. | Reuses the existing resolver; only the reference-side scan is new. |
| req-docs-rid-integrity-2 | Runs in every tier | Implemented | The check runs on docs-tier changes too (own cheap CI job), not only in the test lane — otherwise a new doc citing a typo'd RID lands ungated. | `scripts/check-rids`: one artifact, many invokers. |
| req-docs-rid-integrity-3 | Archival scope is explicit | Implemented | Archival corpora are excluded by an explicit, documented rule — never by accident. | `_ARCHIVAL_DIR_PARTS` in `tap.spec_trace`; historical records citing retired RIDs are correct, not drift. |
| req-docs-rid-integrity-4 | Illustrative RIDs are namespaced | Implemented | Prose about the convention uses the reserved `req-example-*` prefix, which the scanner skips, so documentation never becomes un-remediable baseline debt. | Keeps the baseline pure real drift. |

## Trial Run

The first doc to run through this system is the developer onboarding for multi-session dev environments. Sequencing:

1. This spec lands first as the meta-spec.
2. `specs/spec-dev-multisession-onboarding-doc.md` is created as the doc's owning spec.
3. The Developer Onboarding section is moved out of `specs/spec-dev-multisession.md` and into `docs/misc/doc-dev-multisession-onboarding.md` with the frontmatter pattern.
4. CLAUDE.md gains a Documentation section describing the drift conventions.
5. A feedback memory captures the doc-review-on-spec-edit rule.

Lessons learned from the trial fold back into this spec.

## Requirement Review Needed

Open questions where the documentation system makes no ruling. Recorded, not decided. Indexed
across all specs in [doc-tap-requirement-review-ledger.md](../docs/misc/doc-tap-requirement-review-ledger.md).

### Retired-in-place specs — RESOLVED 2026-08-20 (George)

**Ruling: a retired spec moves to `specs/archive/`.** The location is the fact — the archival
exclusion (`req-docs-rid-integrity-3`) now covers `archive` alongside `docs/aar/` and
postmortems, so no scanner needs a retirement conditional and no retirement record is ever
edited to make its RIDs "resolve." The file keeps its name (git history and inbound archival
links survive); a big banner at its top plus the AGENTS.md exclusion note carry the
don't-rely-on-this signal at every entry point. Executed for
`specs/archive/spec-tap-auth-assurance-v0.md`; the 16-entry floor of the
`rid-reference-integrity` baseline is gone with it.

## Status Vocabulary

Standard TAP states: `Proposed`, `Approved for Development`, `In Development`, `Implemented`, `Verified`, `Refactoring`, `Deprecating`, `Deprecated`, `Backlog`.
