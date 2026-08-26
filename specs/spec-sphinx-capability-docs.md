# Sphinx Capability Documentation

## Philosophy

TAP needs documentation that is both close enough to the implementation for code
review and drift tracking, and available enough to humans and agents that do not
have or should not need code-level access. The existing specs remain the
canonical source of truth for what TAP should do and why. Sphinx capability
documentation is the implemented-surface layer: code-local or source-doc-local
claims about what TAP can do today, linked back to specs and forward to tests,
Gridkin scenarios, and user-facing documentation.

The long-term destination is an on-board, offline documentation capability.
TAP/Rampart must be able to run with no internet access, and installed
documentation must vary by the core apps and plugins present in a running
instance. Public web publishing is optional later; local source docs and generated
offline docs are the center of gravity.

This spec deliberately adopts the Python/Sphinx ecosystem instead of inventing a
TAP-only documentation language. Human-authored pages use MyST Markdown. Python
source extraction is static-first through Sphinx AutoAPI to avoid import-time
Django/plugin side effects. Traceability and feature matrices use Sphinx-Needs
style capability objects.

## Goals

|   |   |  |
| :---: | --- | --- |
| 1. | Code-Adjacent Capability Claims | Load-bearing affordances are documented at their canonical review anchor, close to the implementation or source page that owns the claim. |
| 2. | Spec-Test-Doc Traceability | Capability blocks link specs, implementation anchors, tests/Gridkin scenarios, and human docs into one inspectable chain. |
| 3. | Offline And Composable | Core apps and plugins can carry their own source docs so an installed TAP instance can eventually assemble local docs from installed components. |
| 4. | External And Agent Useful | Capability metadata is scoped by audience and affordance so users and agents can discover the surfaces relevant to their task. |
| 5. | Advisory First, Ratcheting Later | The first pass reports gaps without blocking work; once stable, known gaps ratchet down through the standard in-repo manifest pattern. |

## Requirements

| RID | Name | Status | Notes |
| --- | --- | :---: | --- |
| req-sphinx-docs-toolchain | [Sphinx Toolchain](#sphinx-toolchain) | Proposed | Intended packages and static-first extraction posture |
| req-sphinx-docs-source-layout | [Source Layout](#source-layout) | Proposed | Root misc docs, core app docs, plugin docs; source files only |
| req-sphinx-docs-capability-blocks | [Capability Blocks](#capability-blocks) | Implemented | Documentation-only after the 2026-08-20 ruling: blocks describe affordances, `TAP-IMPLEMENTS` owns the ownership relation, `:implements:` stripped |
| req-sphinx-docs-metadata | [Capability Metadata](#capability-metadata) | Proposed | Audience, affordance, status, since/changed, spec/test/doc links |
| req-sphinx-docs-versioning | [Versioning And Change History](#versioning-and-change-history) | Proposed | Git is exact history; capability metadata records meaningful behavioral milestones |
| req-sphinx-docs-gap-tracking | [Advisory Gap Tracking](#advisory-gap-tracking) | Proposed | Generated reports plus `docs/capability-known-gaps.toml` later |
| req-sphinx-docs-rollout | [Rollout Sequence](#rollout-sequence) | Proposed | Gryphon vertical slice first, then core apps, then plugins |
| req-sphinx-docs-runtime-surfacing | [Runtime Docs Surfacing](#runtime-docs-surfacing) | Backlog | In-app/web/API docs discovery from installed apps/plugins |

### Sphinx Toolchain
----
RID: `req-sphinx-docs-toolchain`
Status: `Proposed`

The intended documentation toolchain is:

- `sphinx` — documentation build system.
- `myst-parser` — MyST Markdown for human-authored source pages.
- `sphinx-autoapi` — static Python source extraction, preferred over import-time
  `autodoc` for TAP code.
- `sphinx-needs` — capability/requirement/test traceability, feature matrices,
  and filtered reports.

This requirement names the intended packages but does not by itself approve or
add third-party dependencies. Adding the packages to `pyproject.toml` is a later
implementation step and must follow the repository dependency-approval rule.

Static extraction is the default because importing TAP modules to build docs can
trigger Django setup, app registry behavior, plugin registration, settings
requirements, and other import-time side effects. Import-based Sphinx extensions
may be used only for narrow surfaces where import safety is deliberate and
documented.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sphinx-docs-toolchain-1 | Intended packages named | Proposed | The spec names `sphinx`, `myst-parser`, `sphinx-autoapi`, and `sphinx-needs` as the intended toolchain. | Dependency addition is separate. |
| req-sphinx-docs-toolchain-2 | Static extraction preferred | Proposed | AutoAPI/static extraction is the default for Python source docs; import-time autodoc is fallback only with explicit justification. | Avoids TAP import side effects. |
| req-sphinx-docs-toolchain-3 | Build implementation separate | Proposed | The first actual Sphinx project/config/build command is owned by a later implementation requirement or spec. | This spec defines conventions first. |

### Source Layout
----
RID: `req-sphinx-docs-source-layout`
Status: `Proposed`

Documentation source is stored with the component that owns the affordance:

- `docs/misc/` — repo-level and developer/LLM "stuff drawer" docs that are useful
  but not worth precisely categorizing.
- `tap_<app>/docs/` — core app capability, user, operator, and extension docs.
- `plugins/<slug>/docs/` — plugin-local docs shipped with that plugin.

The previous root `docs/` flat-directory convention was an emergent v0 shape. It
remains valid only as a repo-level container; `docs/misc/` is the intentionally
loose drawer for existing development docs and future miscellaneous docs.

These directories contain **source docs only**: MyST Markdown, reStructuredText
where unavoidable, images/assets referenced by docs, and other hand-authored
source. Generated HTML, search indexes, JSON exports, PDFs, or other rendered
artifacts are build outputs. They are not committed to source directories unless
a later deployment-specific requirement explicitly creates a deployment artifact
branch or external publish target.

No docs manifest is required in v0. Sphinx/AutoAPI/Sphinx-Needs should derive the
documentation inventory from source pages and capability blocks. A manifest may
be reconsidered when the runtime web/API docs helper is designed, if generated
Sphinx/Needs inventory is not enough for installed-doc discovery.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sphinx-docs-source-layout-1 | Misc drawer exists | Proposed | Existing loose repo docs live under `docs/misc/`. | "Stuff drawer" by convention. |
| req-sphinx-docs-source-layout-2 | Core app docs colocated | Proposed | Core app documentation source may live under `tap_<app>/docs/`. | Used for on-board docs composition. |
| req-sphinx-docs-source-layout-3 | Plugin docs colocated | Proposed | Plugin documentation source may live under `plugins/<slug>/docs/`. | Installed plugin set determines available docs. |
| req-sphinx-docs-source-layout-4 | Source only | Proposed | Generated docs artifacts are not committed into app/plugin docs source directories. | Build outputs are ignored/artifacts. |
| req-sphinx-docs-source-layout-5 | Manifest deferred | Proposed | No docs manifest is required in v0; reconsider during runtime docs surfacing design. | Avoids premature structured format. |

### Capability Blocks
----
RID: `req-sphinx-docs-capability-blocks`
Status: `Implemented`
Trace: `process` — an authoring convention for docstring capability blocks; conformance is editorial, no code derives or enforces it

#### Status Details

**Superseded 2026-08-12 by [`spec-tap-requirement-traceability.md`](spec-tap-requirement-traceability.md)**
(`req-tap-traceability-claim`), and never built.

The overlap is the `:implements: req-…` field proposed below. Two docstring conventions for one
relationship — "this code realizes that requirement" — would be exactly the duplication that spec
exists to prevent, so `TAP-IMPLEMENTS` is the single mechanism and this block is retired rather
than layered on top of it.

**RESOLVED 2026-08-20 (George): convert.** The dispute (recorded 2026-08-14: the deprecation
said "never built" while the tree carried 10+ live, maintained blocks) is closed by
re-scoping: capability blocks are **documentation, never traceability**. The `:implements:`
fields — the one overlap with `TAP-IMPLEMENTS` — are stripped from every live block (the
field-to-RID mapping survives in the resolving commit's diff, which is the gryphon claim
batch's shortlist); the rest of each block (audience, status, limitations, gridkin coverage
links) stays as the reader-facing affordance documentation it demonstrably is. New blocks may
be authored under this documentation-only scope; ownership claims are minted separately,
through the traceability convention, after per-function verification.

**What is not carried forward, stated honestly:** a capability block was broader than a traceability
link — it also carried audience, affordance kind, status, validating tests and doc links, i.e. a
*reader-facing capability catalogue*, which `TAP-IMPLEMENTS` deliberately does not attempt.
`TAP-IMPLEMENTS` answers "which function owns this requirement's fact," not "what can a user do
here." That catalogue remains an unbuilt, unclaimed idea; if it is wanted it should be re-proposed
on its own merits and consume the traceability claim rather than restate it.

A capability block documents a load-bearing user-, operator-, plugin-author-, or
agent-relevant affordance. It is not a generic function docstring and it is not a
second copy of the full spec. It is a short implemented-surface claim: what the
affordance is, what status it has, where its canonical spec lives, what validates
it, and where a reader can learn how to use it.

A capability block is scoped to one *reader-facing affordance* — what a user or
agent experiences as a single thing they can do. That may map to one `req-*`
requirement or stack several. Granularity follows reader usefulness, not
requirement count — and ownership is never stated here: the `:implements:`
field is retired (2026-08-20 ruling), because `TAP-IMPLEMENTS` claims are the
one mechanism for "this code realizes that requirement".

Capability IDs mirror the house `req-*` style:

```text
cap-<scope>-<system>-<feature>[-<subfeature>]
```

Examples:

- `cap-grid-gryphon-type-scan`
- `cap-grid-gryphon-not-exists`
- `cap-plugins-manifest-v0`
- `cap-cares-collector-registration`

The capability block lives at the **canonical review anchor**: the place a
reviewer would naturally inspect to verify the implementation claim. That may be
a module docstring, class docstring, function docstring, or a MyST source page
for non-code or cross-cutting affordances such as settings/configuration.

For a code-backed capability the anchor is the **closest code site that owns the
claim** — frequently a single function, and a private (`_`-prefixed) function is
a perfectly good anchor. Public-versus-private is not a selection factor: a
reader following capability blocks through the code already has the source, so
the value is proximity to the implementation, not reachability through a public
symbol. Use a broader module or class docstring only when a capability genuinely
spans several functions; never relocate a block away from its implementation
merely to land on a public symbol.

The block is designed to be **human-legible as plain text** in the docstring
itself — a developer or agent reading the source sees a structured, readable
metadata block whether or not a Sphinx build has ever processed it.

Blocks are allowed in both Python docstrings and MyST pages. A capability block
that is not attached directly to a Python object must provide a source/code
anchor field that names where the implementation claim is reviewed.

Illustrative shape:

```rst
.. tap:capability:: Gryphon type scan
   :id: cap-grid-gryphon-type-scan
   :status: implemented
   :audience: external-user; agent; developer
   :affordance: querying
   :implements: req-grid-traversal-lang-patterns
   :covered-by: gridkin:type_scan-scan-returns-every-pg-node-in-the-fixture
   :docs: tap_grid/docs/gryphon/reference.md#type-scan
```

The exact directive name and option spelling may be adjusted during the Sphinx
implementation if Sphinx-Needs requires a different syntax, but the semantic
fields in this spec are the contract.

A capability block for a `querying`-affordance feature carries a **worked example**. In v0 the
example is a delimited literal block in the block body — introduced by `Example::` — not a
directive option: a directive option value is reliably single-line, and example queries are
frequently multi-line or exceed the 120-character line limit (which applies inside docstrings).
The example query is sourced from the block's `covered-by` scenario, so it cannot drift from a
validated, snapshot-tested query. Promoting the example to a first-class `:example:` directive
option is revisited once the Sphinx build exists and Sphinx-Needs' multi-line-option behavior is
known.

More generally: a directive **option** value must fit a single line within the 120-character
limit; multi-line or long content belongs in the block body.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sphinx-docs-capability-blocks-1 | `cap-*` IDs | Proposed | Capability IDs use `cap-<scope>-<system>-<feature>` style, mirroring TAP RID conventions. | |
| req-sphinx-docs-capability-blocks-2 | Canonical review anchor | Proposed | Each capability block lives at the closest code site that owns the implementation claim, or a MyST page for non-code affordances. | Private functions are valid anchors; proximity to the implementation beats reachability through a public symbol. |
| req-sphinx-docs-capability-blocks-3 | Code and MyST allowed | Proposed | Capability blocks may appear in Python docstrings or MyST source pages. | Non-code blocks need source/code anchor metadata. |
| req-sphinx-docs-capability-blocks-4 | Load-bearing only | Proposed | Capability blocks are required only for load-bearing affordances; ordinary helpers keep normal docstrings. | |
| req-sphinx-docs-capability-blocks-5 | Worked example for querying blocks | Proposed | A `querying`-affordance block carries a worked `Example::` literal block in its body, sourced from its `covered-by` scenario. | Directive option values stay single-line; long content goes in the body. |

### Capability Metadata
----
RID: `req-sphinx-docs-metadata`
Status: `Proposed`

Capability metadata must be rich enough to generate filtered docs, a
PostgreSQL-style feature matrix, and traceability reports.

Required fields:

- `id` — stable `cap-*` capability ID.
- `status` — standard TAP lifecycle state where possible (`Proposed`,
  `In Development`, `Implemented`, `Verified`, `Deprecated`, etc.).
- `audience` — one or more intended readers.
- `affordance` — one or more task/context categories.
- ~~`implements`~~ — **retired (2026-08-20)**: ownership lives in `TAP-IMPLEMENTS` claims, never in a block field.

Recommended fields:

- `covered-by` — tests, Gridkin scenario IDs, validation-map rows, or other
  validation surfaces. A Gridkin scenario is referenced by its literal
  `scenario_id` — the `<feature-file-stem>-<slugified-scenario-name>` string the
  Gridkin loader assigns — prefixed `gridkin:`. A pytest test is referenced by
  its node id, prefixed `pytest:`.
- `docs` — human-authored docs target.
- `since` — first TAP version/release where the capability exists.
- `changed` — meaningful behavior-change milestone, not every wording edit.
- `limitations` — compact current caveats when they materially affect use.

Initial audience vocabulary:

- `external-user`
- `operator`
- `plugin-author`
- `developer`
- `agent`

Initial affordance vocabulary:

- `querying`
- `configuration`
- `operation`
- `debugging`
- `development`
- `extension`
- `collection`
- `visualization`
- `api`

The vocabulary is intentionally small and grows by demand. A new audience or
affordance value should be added when at least two capabilities need it or a
single capability would otherwise be materially misclassified.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sphinx-docs-metadata-1 | Required metadata present | Proposed | Capability blocks carry `id`, `status`, `audience`, `affordance`, and `implements`. | |
| req-sphinx-docs-metadata-2 | Validation link supported | Proposed | Capability blocks can link to tests, Gridkin scenarios, or validation surfaces through `covered-by`. | |
| req-sphinx-docs-metadata-3 | Audience filterable | Proposed | Audience values support filtered docs for external users, operators, plugin authors, developers, and agents. | |
| req-sphinx-docs-metadata-4 | Affordance filterable | Proposed | Affordance values support filtered docs by task/context such as querying, operation, debugging, and extension. | |
| req-sphinx-docs-metadata-5 | Vocabulary grows by demand | Proposed | New audience/affordance values are added only when a concrete capability needs them. | |

### Versioning And Change History
----
RID: `req-sphinx-docs-versioning`
Status: `Proposed`

Git remains the exact source of edit history. Capability blocks do not carry
manual `last-edited`, `last-reviewed`, or "docstring version" counters. Those
fields drift and duplicate information git already knows.

Capability metadata may carry:

- `since` — when the capability first became available.
- `changed` — a meaningful user-visible behavior change.

In v0, `since` is left unpopulated: TAP has no release or version scheme, so a
uniform placeholder would carry no information. Populating `since` is gated on
TAP adopting a real versioning scheme — that maturity step is the trigger to
start recording first-available versions (see [Future](#future)).

Human-authored Sphinx/MyST pages may use Sphinx `versionadded`,
`versionchanged`, and deprecation directives for reader-facing release notes.
These should mark behavior changes, not every prose edit.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sphinx-docs-versioning-1 | Git is exact history | Proposed | Capability docs do not store edit timestamps or docstring version counters. | Use git log for exact history. |
| req-sphinx-docs-versioning-2 | `since` allowed | Proposed | Capability blocks may record the first release/version where the capability exists. | Not populated in v0; gated on TAP adopting a real versioning scheme. |
| req-sphinx-docs-versioning-3 | `changed` is behavioral | Proposed | Capability blocks or prose docs record only meaningful behavior changes, not wording edits. | |

### Advisory Gap Tracking
----
RID: `req-sphinx-docs-gap-tracking`
Status: `Proposed`

The first Sphinx capability pass is advisory/reporting, not gate-blocking. It
should produce reports such as:

- spec/RID claims implemented but no capability block found
- capability block exists but no linked spec/RID
- capability block exists but no linked validation surface
- capability block exists but no human docs target
- linked spec/capability statuses disagree

When the reporting surface stabilizes, known gaps are tracked in a committed
manifest, proposed path:

```text
docs/capability-known-gaps.toml
```

Each entry records a stable gap ID, kind, target, reason, owning spec, and
remove-when condition. This follows the standard bounded, reviewed, in-repo
manifest pattern used by the validation system. Once enforcement is enabled, the
report fails on new unlisted gaps and on stale manifest entries whose gaps no
longer exist.

The manifest is not required until there is an actual report generator. This
spec names the tracking shape now so advisory gaps have a path to completion
rather than living in memory.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sphinx-docs-gap-tracking-1 | Advisory first | Proposed | Initial Sphinx capability reports do not block development or promotion. | |
| req-sphinx-docs-gap-tracking-2 | Gap categories named | Proposed | Reports distinguish missing docs, missing specs, missing validation, missing anchors, and stale status. | |
| req-sphinx-docs-gap-tracking-3 | Known-gaps manifest path named | Proposed | `docs/capability-known-gaps.toml` is the proposed manifest path once reporting exists. | |
| req-sphinx-docs-gap-tracking-4 | Ratchet path defined | Proposed | Later enforcement fails on new unlisted gaps and stale listed gaps. | Mirrors `spec-dev-validation`. |

### Rollout Sequence
----
RID: `req-sphinx-docs-rollout`
Status: `Proposed`

Rollout is vertical-slice first, then core sweep, then plugins.

1. **Gryphon slice.** Use Gryphon as the proving ground because it has a clear
   external language surface, active capability growth, specs, Gridkin scenarios,
   and immediate validation pain. The slice authors capability blocks in their
   docstring anchors against the semantic-field contract of this spec; it does
   not require, and is not blocked on, the Sphinx build (`req-sphinx-docs-toolchain-3`).
   Until that build lands, the blocks are inert, human-legible metadata in the
   docstrings; Sphinx-Needs validates them when it does.
2. **Core app sweep.** Apply the convention across load-bearing external and
   agent-relevant affordances in core apps (`tap_grid`, `tap_plugins`,
   `tap_api`, `tap_web`, `tap_viz`, `tap_cares`, later `tap_ai`).
3. **Plugin pass.** Apply the convention to currently installed/built plugins,
   starting with plugin-building affordances and plugin-user affordances that are
   intentionally exposed outside code.

Grid-derived docs inventories for pages, panels, searches, collectors, and other
on-grid entities are backlog. They likely need runtime grid extraction and are
not part of the first plugin pass.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sphinx-docs-rollout-1 | Gryphon first | Proposed | The first implementation pass applies the convention to Gryphon only, authoring capability blocks in docstrings. | Do not start with a whole-system census; not gated on the Sphinx build. |
| req-sphinx-docs-rollout-2 | Core sweep second | Proposed | After the vertical slice, load-bearing core app affordances are covered. | |
| req-sphinx-docs-rollout-3 | Plugins third | Proposed | Plugin docs follow after core conventions are proven. | |
| req-sphinx-docs-rollout-4 | Grid-derived inventories deferred | Proposed | Page/panel/search/collector inventories derived from grid state are backlog. | Needs runtime docs surfacing design. |

### Runtime Docs Surfacing
----
RID: `req-sphinx-docs-runtime-surfacing`
Status: `Backlog`

TAP eventually needs an internal docs surface that can show the documentation
available in a running instance, assembled from core apps plus installed plugins.
This is required for offline operation, human users, and agents that should be
able to ask "what can this instance do?" without internet access.

This requirement is backlog. It names the future surface only:

- discover source/generated docs contributed by installed core apps and plugins
- expose docs through the web app and/or API
- filter by audience, affordance, app/plugin, capability status, and installed
  component
- decide whether a docs manifest is needed or whether generated Sphinx/Needs
  inventory is sufficient
- handle grid-derived documentation for pages, panels, collectors, searches, and
  other on-grid affordance objects

Rendering and navigation belong in future `tap_web`/`tap_api` requirements that
reference this docs-system requirement rather than reinventing the discovery
shape.

#### Acceptance Criteria

| ACID | Title | Status | Description | Notes |
| --- | --- | :---: | --- | --- |
| req-sphinx-docs-runtime-surfacing-1 | On-board docs named | Backlog | Runtime docs are an on-board/offline TAP capability, not only public publishing. | |
| req-sphinx-docs-runtime-surfacing-2 | Installed components compose | Backlog | The future docs surface accounts for the installed core apps/plugins in a running instance. | |
| req-sphinx-docs-runtime-surfacing-3 | Manifest reconsidered then | Backlog | A docs manifest is considered only during runtime docs discovery design. | |
| req-sphinx-docs-runtime-surfacing-4 | Web/API rendering deferred | Backlog | Web/API surfacing is explicitly out of v0 and owned by future requirements. | |

## Future

- Sphinx project scaffolding and local build command.
- CI docs build as a validation check on PRs and/or pre-push promote paths.
- Publish-on-main to GitHub Pages, Read the Docs, or another static host if
  public docs become useful; generated docs remain artifacts, not source.
- Machine-readable export of the Sphinx-Needs capability inventory for internal
  agents.
- Runtime docs browser/search inside TAP.
- Populate capability `since` once TAP adopts a real versioning/release scheme —
  versioning maturity is the trigger to begin recording first-available versions.
- Harden Gridkin `covered-by` links: a Gridkin `scenario_id` is derived from the
  scenario name, so renaming a scenario silently breaks any capability block's
  `covered-by` reference to it. The advisory gap report (`req-sphinx-docs-gap-tracking`)
  catches the break after the fact; an explicit stable `id` field on Gridkin
  scenarios would prevent it. Accepted as-is for v0.

## Requirement Review Needed

Open questions where the spec and the tree disagree. Recorded, not decided. Indexed across all
specs in [doc-tap-requirement-review-ledger.md](../docs/misc/doc-tap-requirement-review-ledger.md).

### Live capability blocks under a deprecated convention — RESOLVED 2026-08-20 (George)

**Ruling: convert.** `:implements:` stripped from every live block (ownership has one
convention, `TAP-IMPLEMENTS`); the blocks themselves stay as documentation-only affordance
records, and the requirement is re-scoped `Implemented` under that reading (see its Status
Details). Gryphon functions are unblocked for claims — minted through the traceability
convention with per-function verification, using the stripped field mapping (in the
resolving commit's diff) as the shortlist. A future capability *catalogue* that consumes
claims rather than restating them remains an unclaimed idea; it needs its own proposal.

## Status Vocabulary

Standard TAP states: `Proposed`, `Approved for Development`, `In Development`,
`Implemented`, `Verified`, `Refactoring`, `Deprecating`, `Deprecated`, `Backlog`.
