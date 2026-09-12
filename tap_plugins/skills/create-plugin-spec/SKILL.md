---
name: create-plugin-spec
description: Author a new TAP plugin's specification — identity chain, canonical shape, dimensions, review checklist — as the first artifact in a standalone plugin repo, before any code. Spec-first; the new-plugin skill scaffolds FROM this spec.
argument-hint: <slug> <display-name>
---

# Create a Plugin Spec

> **Skill source-of-truth.** Canonical location: `tap_plugins/skills/create-plugin-spec/SKILL.md`;
> `.claude/skills/create-plugin-spec` is a wiring symlink (`scripts/wire-skills.sh`). Edit the canonical.

You are writing the specification for a plugin that does not exist yet. The order is fixed: **create the
repository, drop the spec, review it, then build the plugin from the spec.** This skill covers the first
three. [`new-plugin`](../new-plugin/SKILL.md) (`--from-spec`) scaffolds the package from what you write here
and must not be run first — a scaffold without a reviewed spec is the shape that never converges.

Extracted 2026-09-12 from the dcom spec's first cut, which got the shape mostly right and the *identity*
wrong in four places (legacy dist prefix, repo name, missing dev-workspace row, non-canonical tail
sections). Every one of those is a check below. Reference spec: `zizmor-tap/specs/spec-zizmor-v0.md`.

## Step 0: Read the authorities (do not work from memory)

- `tap_plugins/specs/spec-tap-plugin-architecture.md` — `req-tap-plugin-arch-identity` (the identity chain;
  amended 2026-08-26), `req-tap-plugin-arch-layout`, `req-tap-plugin-arch-dependencies`, `-versioning`,
  `-dev-deps`.
- `tap_plugins/specs/spec-tap-plugin-manifest-v0.md` — what the manifest can declare; `depends_on` shape;
  `[fips]`.
- `tap_boot/specs/spec-tap-boot-bootstrap.md` — `req-boot-bootstrap-ci-record` (the in-package `ci` record
  every plugin ships) and `req-boot-bootstrap-records-in-package`.
- `tap_grid/specs/spec-grid-dimension.md` — dimensions on entity; default dimensions per type and per edge.
- `tap_grid/specs/spec-grid-icon.md`, `spec-grift-v0.md` when the plugin ships types or seed data.
- The reference spec, top to bottom: `_dev-plugins/zizmor/specs/spec-zizmor-v0.md` (or the zizmor-tap repo).

## Step 1: Derive the identity chain — never author it

Everything in the Plugin Identity table derives from the **slug**. Write the slug once, derive the rest,
and check the derivations against `tap/plugin_identity.py` (`dist_name_for_slug`) rather than typing them:

| Row | Derivation | Example (`slug = zizmor`) |
| --- | --- | --- |
| Slug | The one identity: manifest `slug` == entry-point key == namespace segment. snake_case. | `zizmor` |
| Display name | `TAP <Name>` | `TAP zizmor` |
| Description | One sentence; the manifest `description`. | … |
| Kind | Leaf plugin (consumes a substrate, consumed by a product) · `*_core` substrate (neutral vocabulary others depend on downward) · vocabulary substrate with no models (a dimension pack) · product. Name what it consumes and what consumes it. | Leaf: consumes github_core, consumed by git-serious |
| Dist | **`<slug-dashed>-tap`**. The `tap-plugin-<slug>` prefix is LEGACY (accepted with a warning until the rename wave; never emitted for a new plugin). | `zizmor-tap` |
| Import namespace | `tap_plugin.<slug>` — PEP 420, singular `tap_plugin`, no `tap_plugin/__init__.py`. | `tap_plugin.zizmor` |
| Entry point | `<slug> = "tap_plugin.<slug>.apps:<Slug>Config"` under `[project.entry-points."tap.plugins"]` | `zizmor = "tap_plugin.zizmor.apps:ZizmorConfig"` |
| AppConfig | `tap_plugin.<slug>.apps.<Slug>Config`; `name` derived from the module path, `label`/`verbose_name` from the manifest — nothing authored in `apps.py`. | |
| Repo | `unified-systems-com/<dist>` — mirror the dist, **standalone from the first commit** (every plugin is evicted; the monorepo `plugins/<slug>/` shape is history). | `unified-systems-com/zizmor-tap` |
| Dev workspace | `spawn-session.sh <label> --from <record> --dev-plugins <slug>[,<deps>]` | `--dev-plugins zizmor,github_core` |
| Depends on | Tier-1 `depends_on` slugs with a one-line *why* each (imports models / targets types / inherits a vocabulary). "Nothing" is a valid, stated answer. | `github_core` |
| Collector | Registry key `<slug>:<name>`, or "None — seeded, never collected". | `zizmor:zizmor` |
| Trigger | Own `schedule` node / fired by a consumer / boot-record `fire-collector` / none. | |
| Pages | Route table (`/…`) with panels mounted, or "None in v0". One requirement per page and per panel type follows in the body. | |
| GRIFT | Each `grift/*.grift.json` with what it seeds. | |
| Boot records | `ci` (in-package, `req-boot-bootstrap-ci-record`) at minimum; the `#ci` pointer form for reproducing CI. | |
| Spec home | `specs/spec-<slug>-v0.md` at the repository root, from the first commit. Core is never edited to define a plugin. | |

Then the **Default dimensions** table: every dimension key the plugin's nodes and edges carry, its value,
and *why*. A plugin that ships TAP-managed types with no default dimension is a design error to justify in
writing, not a default to accept. If the plugin models a designed system, say whether it inherits the dcom
model (`dcom-tap/specs/spec-dcom-v0.md`) and how each type is stamped.

**Checks that bit (2026-09-12):**

- Dist written as `tap-plugin-<slug>` → wrong since 2026-08-26. Repo created under that name → rename
  (`gh repo rename`) and fix every link.
- No `Dev workspace` row → the reader cannot stand the plugin up; add it.
- `--boot-file` is a deprecated alias; write `--from`.
- Tests belong **inside the package** (`tap_plugin/<slug>/tests/`) so they ride the wheel — not at the repo
  root. The root `__init__.py` is only the pytest collection marker.

## Step 2: The canonical shape

Sections, in this order. Nothing ad hoc above `## Plugin Identity`; nothing after `## Icons`.

1. `# <Name> Plugin Specification` — one-paragraph lede in bold saying what the plugin *is*.
2. `## Plugin Identity` — the table from Step 1, then the Default dimensions table.
3. `## Philosophy` — why it exists, what it deliberately does not do, the three-states stance, and a
   **Provenance markers** line: which claims are *observed* (measured, dated) and which are *documented*
   or *designed*.
4. `## Goals` — `| # | Name | Description |`, Title-Case names.
5. `## Requirements` — `| RID | Name | Status | Notes |`, one row per requirement, Name linking to its
   section. Status ∈ `Proposed` · `Approved for Development` · `In Development` · `Implemented` ·
   `Verified` · `Backlog`. Non-goals are either a tail `req-<slug>-nongoals` requirement or `Backlog`
   requirements — pick one convention and hold it (zizmor: Backlog rows for real future work, plus a
   nongoals tail when something is genuinely *not* going to be built).
6. Per requirement: `### <Name>` · `----` · `RID: \`req-<slug>-<noun>\`` · blank · `Status: \`…\`` · blank ·
   prose · `#### Implementation` (concrete: file paths, class names, field names, config shape) · `####
   Acceptance Criteria` as `| ACID | Title | Status | Description | Notes |` with ACIDs `req-<slug>-<noun>-<n>`.
   One blank line between every metadata line (`scripts/spec-two-line-metadata` enforces it).
   **One requirement per page and per panel type** the plugin ships; the `add-page` / `add-panel` skills
   consume those requirements, they do not create them.
7. Tail sections — **a design-time catalog that the code supersedes.** Before any code exists the spec is
   the only place the plugin's types can be described, so `## Model catalog` (`| Model | Entity type |
   Category | Rationale |`) and `## Edge types` (`| Edge | From → To | Properties | Rationale |`) are written
   at authoring time as the *design* of what will be built — otherwise nodes and edges would have to be
   written during spec creation. Once the plugin ships, the manifest (`[models]`, `[edges]`) and the classes
   are self-describing and become the one source; the catalog is then **superseded**: when the owning
   requirement flips to `Implemented`, trim each row to the decision the code cannot state (why the type
   exists, why the edge points that way, what was rejected — zizmor's `no-yaml is the fourth outcome`,
   `slugs carry their object nouns`) or delete the row, and head the section "Superseded by the manifest as
   of v<x>". A catalog left verbatim beside a shipped manifest is a second copy that exists to be wrong
   (derive-a-fact-once). `## Reference data` (`| Document | Contents | Seeded by |`) is a deployment
   decision and stays; `## Icons` only when the approach is a decision. (Ruled 2026-09-12: "an initial model
   catalog in a pure .md specification … superseded / implemented and possibly deleted once the spec is
   implemented.")

Do **not** add the core-spec tails (`## Status Vocabulary`, `## RID Format`) to a plugin spec; the plugin
architecture spec owns those.

## Step 3: Greenfield means greenfield

A spec for a *new* vocabulary must not carry the old one. If the plugin replaces or deprecates something
that exists elsewhere, the deprecation is written **in the spec of the plugin being deprecated**, linking
forward to the new spec — never backward from the new spec to the old key, type or name. The new spec
should read correctly to someone who never saw what it replaces. (Ruled 2026-09-12 on dcom: "the spec is
going to outlive us all; pure and unencumbered by previous decisions.")

Cross-repo references that *are* allowed: core requirements the plugin relies on (by RID), the grid
mechanisms it feeds (by tap issue when not yet built), and sibling plugins it depends on (by slug).

## Step 4: Repository, review, and what the ruleset does to a new repo

1. **Confirm before creating anything outward-facing.** Creating an org repository is a public,
   hard-to-reverse mutation. Before the first `gh` write, show the human the exact plan — org, repo name
   (the dist), visibility, the branch plan (bootstrap main; spec on `spec/<slug>-v0`), and the commit the
   review shims will be copied from — and proceed only on an explicit yes. Invoking this skill is a request
   for a spec, not standing authorization to mutate the organization.
2. **Create the repo**, empty: `gh repo create unified-systems-com/<dist> --public`. The org ruleset applies
   the moment the repo exists: main is PR-only, force-push is refused, and Copilot review is attached. So
   **never commit the spec straight to main** — bootstrap main with `README.md` + `LICENSE` (Apache-2.0,
   copy from a sibling plugin) and put the spec on `spec/<slug>-v0`.
3. **Wire the AI review in the same first PR wave, from a pinned source.** The Unified AI Review runs from
   two shim workflows every plugin repo carries (`.github/workflows/ai-review-capture.yml`, `ai-review.yml`).
   Copy them from **this repository's own `.github/workflows/`** at the commit you are working from — the
   in-tree, reviewed copy (`specs/spec-cicd-ai-review.md`), never a sibling plugin's default branch, which is
   a mutable source that would transitively inject workflow code into every new repo. Record the source
   commit in the PR body and confirm the machinery/prompt pins inside the files are unchanged (`diff` against
   the source). The privileged stage runs the *default-branch* definition, so those files must be on main
   before any PR in the repo gets a Codex/Grok seat. A repo without them gets no review and no error.
4. **Open the spec PR** with review asks in the body: is the value/type set complete and disjoint; is every
   number derivable; where are the three states; what did the author assume versus observe.
5. Run `scripts/pr-review-triage <pr> --wait` (from the tap worktree, naming the PR) and read every seat, including
   suppressed findings in the summaries.
6. Only after the spec is approved: `new-plugin --from-spec specs/spec-<slug>-v0.md`.

## Step 5: Review checklist (run on the finished spec)

- [ ] Every Plugin Identity row is derived from the slug and matches `dist_name_for_slug`; no `tap-plugin-` prefix anywhere.
- [ ] Repo row says standalone from the first commit; Dev workspace row uses `--from`.
- [ ] Default dimensions table present, or the "no TAP-managed types" carve-out stated once.
- [ ] Goals table header is `| # | Name | Description |`.
- [ ] Every requirement has two-line metadata, an Implementation body concrete enough to build from, and an ACID table.
- [ ] One requirement per page and per panel type.
- [ ] Non-goals follow one convention (Backlog rows and/or a nongoals tail); no `## Out of Scope` / `## Future` free sections.
- [ ] Model catalog / Edge types present at design time; once `Implemented`, headed as superseded by the manifest with only decision rows surviving.
- [ ] No legacy vocabulary in a greenfield spec; deprecations live in the deprecated plugin's spec.
- [ ] The human confirmed the repo plan before `gh repo create`; the shim workflows were copied from this repo's own tree at a named commit and diffed clean.
- [ ] Every cited RID, file path and issue number resolves (a citation that does not resolve reads as verification).
- [ ] Three states, never two, wherever absence can occur; presence is not correctness.
- [ ] Provenance markers: observed vs documented vs designed.

## Step 6: Record

The spec PR body carries the checklist result. When a check here proves wrong or incomplete in the field,
fix this file in the same PR that fixes the spec — a skill that drifts from the specs it cites is the
presence-not-correctness trap wearing a helpful face.
