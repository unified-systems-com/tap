---
name: new-plugin
description: Scaffold a new TAP plugin with manifest, models, edges, tests, specs, icons, and docs. Supports both from-scratch authoring and spec-first graduation from a pre-authored planning doc.
disable-model-invocation: true
allowed-tools: Read Write Edit Bash(git *) Bash(gh *) Bash(mkdir *) Bash(mv *) Bash(ls *) Glob Grep
argument-hint: <slug> <display-name>  |  --from-spec <path>
---

# Scaffold a New TAP Plugin

> **Skill source-of-truth.** This SKILL.md's canonical location is `tap_plugins/skills/new-plugin/SKILL.md`. The `.claude/skills/new-plugin/` path is a directory-level symlink — edit the canonical, the symlink follows. Same pattern holds for the other plugin-tooling skills (`add-model`, `add-edge`, `add-page`, `add-panel`): canonical lives under the owning package's `skills/` directory.

You are creating a new TAP plugin. Plugins are **installable Python packages** (package-mode, since the 2026-07 refactor): a wheel-buildable dist with a `tap.plugins` entry point, consumed via uv (editable in the monorepo now; git-source / index later). The repo is decoupled from identity — a plugin can live standalone or in the monorepo `plugins/<slug>/` without changing what it *is*. Lead with the package-mode shape below from the very first file; it is cheap now and expensive to retrofit.

## Package-Mode Layout (the current shape — READ FIRST)

> This supersedes any older "flat `plugins/<slug>/apps.py` + `git submodule add`" guidance. Authoritative specs: `req-tap-plugin-arch-identity` (identity chain), `req-tap-plugin-arch-install-registry` (install/discovery), `req-tap-plugin-arch-versioning` (hatch-vcs), `req-tap-plugin-arch-dependencies` (deps). Recipe reference: `docs/misc/doc-plugin-boot-install-handoff.md` + `doc-plugin-source-identity-deps-handoff.md`. Clone an already-migrated plugin (`plugins/computing_core/` is the cleanest leaf; `plugins/samsite/` shows cross-plugin deps) as your template.

**The identity chain (all four MUST agree — the pre-boot conformance gate fails closed otherwise):**
`slug` (manifest `slug` == `tap.plugins` entry-point key == namespace segment) · dist `tap-plugin-<slug>` (PEP 503) · import namespace `tap_plugin.<slug>` (PEP 420, singular `tap_plugin`) · AppConfig `tap_plugin.<slug>.apps:<Slug>Config`.

**Directory shape** — the monorepo project dir `plugins/<slug>/` holds the packaging + test-infra; the **runtime package** is nested at `tap_plugin/<slug>/` and is the ONLY thing that ships in the wheel:

```text
plugins/<slug>/
  pyproject.toml            # dist + entry point + hatch-vcs (template below)
  __init__.py               # monorepo test-collection MARKER (not the package; ships in no wheel)
  .gitignore                # __pycache__/, *.pyc, .pytest_cache/, .mypy_cache/, .ruff_cache/
  specs/                    # plugin specs (NOT in wheel)
  tests/                    # plugin tests (NOT in wheel)
  tap_plugin/               # PEP 420 namespace — NO __init__.py here (shared namespace)
    <slug>/                 # the runtime package (this is what installs)
      __init__.py           # package docstring
      apps.py               # one TapPluginConfig subclass, body `pass`
      tap-plugin.toml       # manifest (lives INSIDE the runtime package)
      models/  edges/  grift/  static/<slug>/  templates/<slug>/  migrations/
```

**`pyproject.toml` template** (namespace build via hatchling + hatch-vcs; the plugin-creation skill emits this so authors never hand-set it):

```toml
[project]
name = "tap-plugin-<slug>"
description = "TAP <Display Name> plugin — <one line>."
requires-python = ">=3.14"
dynamic = ["version"]
dependencies = []                    # Tier-0 RUNTIME deps go here (see Dependencies below)

[project.entry-points."tap.plugins"]
<slug> = "tap_plugin.<slug>.apps:<Slug>Config"   # entry-point KEY == slug

# Developer-mode (test/lint) deps — the plugin's OWN dev closure, so its suite runs
# standalone (post-eviction) instead of free-riding on the monorepo root venv's dev
# group (req-tap-plugin-arch-dev-deps). PEP 735 dependency-groups: NOT [project.optional-
# dependencies] (extras are opt-in runtime features), and NEVER a boot/install concept —
# dev deps must not enter a deployed instance. Dev-group deps never ship in the wheel.
# Pulled with `uv sync --group dev` / `uv run --group dev pytest` in a standalone checkout;
# in the monorepo the shared root dev group already covers them, so this is a pre-demand
# foundational edge (born-correct so the free-riding habit never calcifies).
[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-django>=4.9",
    "factory-boy>=3.3",
]

[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[tool.hatch.version]
source = "vcs"

[tool.hatch.version.raw-options]
root = "../.."                       # MONOREPO-TRANSITION ARTIFACT — remove on extraction
fallback_version = "0.0.0"

[tool.hatch.build.targets.wheel]
only-include = ["tap_plugin/<slug>"]
```

- **Manifest class paths use the namespace.** `[models]`/`[edges]` entries are `tap_plugin.<slug>.models.X`, not `plugins.<slug>...` or a bare `<slug>...`.
- **`models/__init__.py` re-exports via the namespace:** `from tap_plugin.<slug>.models.foo import Foo`.
- **`apps.py` sets no `name`/`label`.** `TapPluginConfig.__init_subclass__` derives `name` from the module path (`tap_plugin.<slug>`); `label` comes from the manifest `slug`.
- **Install is uv, not submodules.** In the monorepo, add the plugin to a boot profile's `install` section (`{ "slug": "<slug>", "enabled": true, "source": { "type": "editable", "path": "plugins/<slug>" } }`) and it installs at pre-boot. `git submodule add` is explicitly rejected (the old dependency nightmare). Do NOT add the plugin to `INSTALLED_APPS` — package-mode plugins load via `TAP_PLUGINS` from the profile.
- **A SPLIT plugin** (one that ships a test harness, like `gryphon_playground`) keeps test-infra subpackages at `plugins/<slug>/` and only moves the runtime into `tap_plugin/<slug>/`; the marker `__init__.py` lets the test-infra keep importing `plugins.<slug>.<subpkg>`.

## Operating Modes

This skill supports two entry modes; the work in Steps 1 and 3 differs based on which one applies. Every other step is identical.

**From-scratch mode.** No pre-authored spec exists. The skill collaborates with the user to draft the spec from zero (the original path).

**Spec-first mode.** A planning doc has already been authored — typically in another LLM session — at `docs/misc/preplugin-<slug>-v?.md`, or at a path the user passes via `--from-spec`. The skill reviews the doc, asks bounded clarifying questions, normalizes it into canonical spec shape, and graduates it (via `mv`) into `plugins/<slug>/specs/spec-<slug>-v0.md`.

### Detect the mode

Resolution order:

1. If `$ARGUMENTS` includes `--from-spec <path>`, that's spec-first mode with the named path.
2. Otherwise, once a slug is known (from `$ARGUMENTS` or just-asked), check `docs/misc/preplugin-<slug>-v?.md`. If exactly one match exists, that's spec-first mode. If multiple, ask which.
3. Otherwise, from-scratch mode.

Confirm the detected mode with the user in one sentence before proceeding.

## How TAP Specifications Work

TAP uses a spec-first development process. Specifications live in `specs/` directories throughout the codebase and are the authoritative source for how things work. Each spec contains requirements with RIDs (requirement IDs), acceptance criteria, and implementation details.

When you are unsure how something works — models, edges, manifests, icons, validation, GRIFT — read the relevant spec. Do not guess or rely on patterns you've seen elsewhere.

**Key specs to read before starting (plugin-scaffolding scope):**

- `tap_plugins/specs/spec-tap-plugin-architecture.md` — plugin structure, repo conventions, skills, package layout
- `tap_plugins/specs/spec-tap-plugin-manifest-v0.md` — manifest format and validation rules
- `tap_grid/specs/spec-grid-icon.md` — icon key format, SVG requirements, vendor brand colors
- `tap_grid/specs/spec-grift-v0.md` — GRIFT interchange format for seed data

**Key schemas:**

- `tap_grid/schemas/grift-document.schema.json` — machine-readable GRIFT document schema
- `tap_plugins/validate/plugin-validation-result.schema.json` — validation output schema

For per-model and per-edge work, the [`add-model`](../../../tap_grid/skills/add-model/SKILL.md) and [`add-edge`](../../../tap_grid/skills/add-edge/SKILL.md) skills carry the canonical spec pointers (BaseModel contract, edge-definition schema, hotlinks, history). Don't duplicate that material here — defer to those skills in Steps 5 and 6.

If a spec seems incomplete or contradicts what you see in code, flag it to the user rather than silently working around it.

## Step 1: Establish Names And Defaults

Before drafting the full spec, collaborate with the user on the naming and dimension conventions for the plugin. This reduces churn later.

If $ARGUMENTS provides a slug and display name, use those. Otherwise ask.

Gather from the user:

1. **Plugin slug** — used as manifest `slug`, Django app label, directory name
2. **Display name** — human-readable name for the manifest `name` field
3. **Description** — one-line description
4. **Default dimensions convention** — what dimension key/value should all TAP-managed entities and edges use?
5. **Naming strategy** — proposed model/type slugs, edge slugs, icon keys, and GRIFT bundle names
6. **Repo shape** — default is in-monorepo (`plugins/<slug>/`, editable-installed via a boot profile). Only gather a standalone GitHub repo name/org if the user explicitly wants a separate repo now (rare during the monorepo phase; identity is repo-independent either way)

Default dimensions are required **when the plugin contributes TAP-managed entities** (models or edges). If the plugin's Plugin Scope explicitly excludes TAP-managed entities — e.g., a panel-only, presentation-only, or pure-helper plugin — default dimensions are N/A; note the carve-out once and do not require a value. Otherwise, dimension-less TAP-managed types should be treated as a design bug to justify rather than a default to accept silently.

**In spec-first mode**, slug + display name come from the spec's `## Plugin Identity` section (see Step 3). Default dimensions, naming strategy, and GitHub repo metadata may or may not be answered in the spec — the Step 3 review pass identifies the gaps and asks for them in one bounded batch rather than re-eliciting answers the spec already contains.

## Step 2: Repository Shape (decoupled — usually the monorepo)

The repo is **not** load-bearing for identity (`req-tap-plugin-arch-identity-4`). In the current monorepo workflow a new plugin lives in-tree at `plugins/<slug>/` and is installed as an **editable uv package** via a boot profile — no separate repo and **no `git submodule add`** (submodules were the prior dependency nightmare; package-mode install replaces them). Commit the plugin dir alongside the rest of the monorepo.

If a genuinely standalone repo is wanted later, extraction is a one-line source change (editable → git-source) plus removing the `root = "../.."` monorepo-transition artifact from `pyproject.toml`; identity is unchanged because it lives in the package, not the repo. Do not stand up a separate GitHub repo pre-emptively unless the user asks — it adds submodule/CI friction with no identity benefit during the monorepo phase.

## Step 3: Write or Graduate the Specification

Before writing any code, ensure a settled plugin specification exists at `plugins/<slug>/specs/spec-<slug>-v0.md`. The spec drives everything that follows — this is the most important step.

### Canonical Spec Shape

The required sections of a graduated TAP plugin spec:

- `## Plugin Identity` — slug, display name, and key initial entry points (e.g. initial page route, initial panel type slug, initial page variables). This is the "what is this plugin called and where does it land" header that anyone graduating the spec wants to read first. Required on every plugin spec; do not invent ad-hoc top metadata blocks in lieu of this section.
- `## Philosophy` — why this plugin exists, what domain it models, what's deliberately in vs. out of scope
- `## Goals` — numbered table: `| # | Name | Description |`
- `## Requirements` — top-level table: `| RID | Name | Status | Notes |`
- Per-requirement section: `### <Name>` heading, `----` divider, `RID: \`req-<slug>-<noun>\``, `Status: \`<Proposed|Implemented|Backlog>\``, descriptive body, optional `#### Implementation` body, and an `#### Acceptance Criteria` table (`| ACID | Title | Status | Description | Notes |`)
- Model catalog (if applicable) — what models, organized by category, with rationale
- Edge types (if applicable) — what relationships, organized by category
- Reference data (if applicable) — what GRIFT seed data
- Icons (if applicable) — what the icon approach will be
- Non-goals — encoded either as a tail `### v0 Non-Goals` requirement (e.g. `req-<slug>-nongoals`) or as `Backlog`-status requirements; pick one and apply consistently within the spec

Read existing graduated specs for format/tone — strong references: `plugins/aws_core/specs/spec-aws-core-v0.md`, `plugins/samsite/specs/spec-samsite-compliance-collector-v0.md`, `plugins/gryphon_playground/specs/spec-gridkin-v0.md`.

### From-Scratch Variant

Collaborate with the user to draft the spec from zero. Gather:

1. **Domain** — what resource types, relationships, and reference data does this plugin model?
2. **Default dimensions** — confirm the convention from Step 1 (skip if the plugin contributes no TAP-managed entities)
3. **Naming strategy** — confirm the naming set from Step 1 before drafting
4. **Repo shape** — confirm in-monorepo (default) vs a standalone repo now (rare; identity is repo-independent)

Bias toward durable primitives. If a proposed model or edge feels speculative, unstable, or too domain-specific for the plugin's stated scope, flag it and move it to non-goals or future work instead of forcing it into v0.

Go back and forth with the user until the spec is agreed.

### Spec-First Variant

A pre-authored planning doc exists at `docs/misc/preplugin-<slug>-v?.md` (or the `--from-spec` path). Treat it as the source of truth and do not re-draft from scratch. The work here is **review → clarify → normalize → graduate**, in that order.

#### Review Checklist

Run every item; report findings in one summary before asking anything.

| # | Check | What "fail" looks like |
| :---: | --- | --- |
| a | **Required sections present.** All sections in the Canonical Spec Shape above. Specifically check whether a `## Plugin Identity` section exists, or whether the doc has an ad-hoc top metadata block to convert. | Missing Philosophy, Goals, Requirements table, or per-req sections; ad-hoc top metadata block in lieu of `## Plugin Identity` |
| b | **RIDs well-formed.** Unique within the spec, kebab-case, prefixed `req-<slug>-`. | Duplicates, missing prefix, non-kebab-case |
| c | **ACIDs well-formed.** Unique under each RID, kebab-case, prefixed with the RID (e.g. `req-roscale-v0-scope-1`). | Duplicates within a requirement, missing or wrong prefix |
| d | **Statuses valid.** Every Status ∈ `{Proposed, Implemented, Backlog}`. | Non-canonical statuses like `Pre-Plugin Planning`, `Draft`, etc. |
| e | **Step 1 + Step 3 questions answered.** Slug, display name, description, scope, naming strategy, default dimensions (only if Step 1's conditional applies), GitHub repo metadata. | Any of these missing or vague enough to need user input |
| f | **Known Codex-shaped artifacts flagged for normalization.** | See list below |
| g | **Spec quality smell-tests.** Are requirements concrete? ACs testable? Contradictions, undefined terms, ambiguous scope language? | Any "we'll figure it out" hand-waving in normative sections |

Known Codex-shaped artifacts (item f) and their normalizations:

- `# <Name> v0 Pre-Plugin Plan`-style title → rename to `# <Name> Plugin Specification` (or domain-appropriate canonical title)
- Top-level `Status: Pre-Plugin Planning` line under the title → drop. Status lives per-requirement, not at the document level.
- Top metadata block (slug / display name / initial page / initial panel / initial variable laid out as key/value pairs at the top) → convert to a proper `## Plugin Identity` section.
- `## Strategic Check` section (path alignment, scope risk, defer list, recommendation) → drop. Pure planning artifact; not part of a settled spec. Optionally archive separately under `docs/misc/decision-*.md` if the rationale is worth keeping.
- `## Initial Implementation Outline` section (numbered list of "first slice" steps) → drop. This skill IS the implementation outline; Steps 4–13 below cover it.
- `## Open Questions For Implementation` tail bucket → fold each open question into the relevant requirement's `Notes` column on the Requirements table, or into a per-requirement note inside the requirement body. Open questions belong adjacent to the requirement they affect, not in a tail bucket.
- `## Prior Art And Source Boundaries` as a top-level section → consider folding into the most-relevant requirement (e.g., a Vendored Assets requirement). Keep the substance; lose the top-level slot if the content only justifies a single requirement.

#### Clarifying-Question Protocol

Where the checklist finds genuine gaps, ask in **one bounded batch** via `AskUserQuestion` — at most 4 questions per batch. Only open a second batch if the first batch's answers reveal new gaps that weren't visible before. Avoid 20-question chains; if many gaps exist, surface that as "this spec needs more work before graduation" and stop, rather than power through with a long elicitation.

#### Normalize

Apply the checklist findings to the doc in place. Then show the normalized result to the user and get one round of approval before graduation. Do not graduate on assumed approval.

#### Graduate

```bash
mkdir -p plugins/<slug>/specs
mv docs/misc/preplugin-<slug>-v0.md plugins/<slug>/specs/spec-<slug>-v0.md
```

`mv` clean — the planning doc is replaced; history lives in git. Do not leave a redirect stub at the old path; stubs rot.

Confirm the file is in its new location before proceeding to Step 4.

---

After either variant, update requirement statuses to `Implemented` as you build each piece. Spec drift is a bug — keep statuses in sync with code as the work proceeds.

## Step 4: Create Plugin Directory and Core Files

Create the package-mode layout under `plugins/<slug>/` per the **Package-Mode Layout** section above (the authoritative shape) and `tap_plugins/specs/spec-tap-plugin-architecture.md`. Clone an already-migrated leaf (`plugins/computing_core/`) rather than hand-building — it is faster and guarantees the identity chain agrees.

The core files every plugin needs (note the packaging vs runtime-package split):

- `plugins/<slug>/pyproject.toml` — the dist + `tap.plugins` entry point + hatch-vcs (template in the layout section)
- `plugins/<slug>/__init__.py` — the monorepo test-collection **marker** (comment only; ships in no wheel), NOT the package
- `plugins/<slug>/.gitignore` — bytecode/cache ignores (contents below)
- `plugins/<slug>/tap_plugin/<slug>/__init__.py` — the runtime package marker, docstring only
- `plugins/<slug>/tap_plugin/<slug>/apps.py` — single `TapPluginConfig` subclass, body `pass`, no explicit `name`/`label`/`verbose_name`
- `plugins/<slug>/tap_plugin/<slug>/tap-plugin.toml` — manifest per `spec-tap-plugin-manifest-v0.md` (class paths use `tap_plugin.<slug>.…`). Include a **`[fips]` crypto-posture declaration** (`spec-fips.md`, `req-tap-plugin-manifest-v0-fips`): a pure-Python plugin with no crypto deps declares `[fips]\nstatus = "compatible"` (grid_fixtures is the dogfood example) — conformance verifies it against a scan. If the plugin pulls a non-FIPS crypto provider (see the Dependencies FIPS check), declare `status = "uses-nonvalidated"` with a `reason` instead. Absent `[fips]` is undeclared, not assumed compatible.
- `plugins/<slug>/tap_plugin/<slug>/migrations/__init__.py` — empty
- `plugins/<slug>/README.md` — plugin-local developer and AI-agent orientation notes
- `plugins/<slug>/docs/` — setup guides, runbooks, inventories, deeper design notes
- `plugins/<slug>/tests/__init__.py` — empty
- **NO** `plugins/<slug>/tap_plugin/__init__.py` — the namespace package must stay init-free so dists share it (PEP 420).
- `.gitignore` — keep Python bytecode and tooling caches out of the index. Minimum recommended contents:

  ```gitignore
  __pycache__/
  *.pyc
  *.pyo
  .pytest_cache/
  .mypy_cache/
  .ruff_cache/
  ```

  Without this, the first `git add -A` after running tests or migrations will quietly pull dozens of `.pyc` files into a commit.

Create root `README.md` as soon as the plugin directory exists. This file is not marketing copy. It is the durable context page for future developers and AI agents working inside the plugin, especially after the plugin is split into its own repository or submodule. At minimum include:

- what this plugin owns
- what nearby TAP apps or plugins own instead
- important specs and docs to read first
- current model, edge, collector, and GRIFT scope
- local validation and operational notes

Keep it short at scaffold time, then maintain it as decisions accumulate. Do not leave it as a stale placeholder once the plugin has real behavior.

Periodically revisit root `README.md` and any plugin-local docs during plugin work, especially after adding models, edges, collectors, GRIFT seed data, validation behavior, or operational assumptions. Treat stale plugin documentation as spec drift: update it in the same change set when the implementation or architecture moves. Use `docs/` for setup guides, operator runbooks, inventories, and longer design notes that would make the root README hard to scan.

## If Your Plugin Ships Templates

If the plugin will render its own panels or pages, those land under `plugins/<slug>/templates/<slug>/...` and the actual authoring follows the [`add-panel`](../../../tap_web/skills/add-panel/SKILL.md) and [`add-page`](../../../tap_web/skills/add-page/SKILL.md) skills. One scaffold-time thing worth knowing up front:

- **Tailwind utilities require invoking `/tailwind-rebuild` after class changes.** There's no container watcher (by design — [`tap_web/specs/spec-web-tailwind-pipeline.md`](../../../tap_web/specs/spec-web-tailwind-pipeline.md) explains why). The compiled `tap_web/static/tap_web/css/tailwind.css` is committed to git. After editing a template that adds or removes a Tailwind utility class string, invoke `/tailwind-rebuild` and commit the regenerated CSS alongside the template change. Scanned paths include `plugins/**/templates` so plugin templates are covered. Skill docs: [`tap_web/skills/tailwind-rebuild/SKILL.md`](../../../tap_web/skills/tailwind-rebuild/SKILL.md). Recovery if the skill fails: [`docs/misc/doc-dev-tailwind-rebuild.md`](../../../docs/misc/doc-dev-tailwind-rebuild.md).

## Plugin Configuration And Dependencies (hard rules)

Two anti-patterns that have bitten this codebase — do not repeat them:

- **No plugin config in core infrastructure.** A plugin's configuration must not live in `docker-compose.yml`, core settings, or other shared infra (`req-tap-plugin-arch-runtime-4`). Plugins self-configure through plugin-owned mechanisms — in v0, on-disk secrets discovered under `TAP_SECRETS_ROOT` (e.g. resolve a well-known `SecretRef`). A durable on-grid plugin-config model is future work. The removed `AWS_CORE_STEAMPIPE_COLLECTOR` compose entry was this mistake.
- **No new third-party dependencies without explicit approval.** TAP deliberately minimizes third-party dependence: prefer Django/stdlib and capabilities already present before reaching for a package. Adding a library requires deliberate justification and the user's go-ahead — never slip one in.

### Declaring dependencies (three tiers, `req-tap-plugin-arch-dependencies`)

- **Tier 0 — package/library deps (incl. plugin→plugin code) → `pyproject.toml` `dependencies`.** e.g. `dependencies = ["tap-plugin-aws-core>=0.1"]` or a third-party lib. uv resolves the closure + version diamonds, fail-closed. Use version specifiers, not git-URLs, so deps stay index-resolvable.
  - **FIPS crypto check — do this BEFORE adding any dependency (`spec-fips.md`, standing filter).** TAP runs FIPS-on by default (`TAP_FIPS=1`), and the crypto-BOM gate fails-closed on any crypto provider that is not FIPS-validated. A plugin runs in the same image/process as core, so a dependency that carries its OWN crypto defeats a FIPS-capable core. Ask what crypto the library uses:
    - **Bundled-OpenSSL wheels** (the `[binary]`/manylinux kind — e.g. `psycopg[binary]`) statically bundle their own OpenSSL, which ignores the system FIPS provider and **breaks under FIPS**. Prefer the source/`[c]` extra that links the SYSTEM libpq/OpenSSL (this is why core uses `cryptography` `--no-binary` and `psycopg[c]`).
    - **Non-OpenSSL crypto** — a Rust crate on `ring`/`aws-lc-rs`, a `libsodium`/`pynacl` wheel, a bundled Go binary, or anything pulling a JVM (BouncyCastle) — is NOT the validated module and runs SILENTLY non-FIPS. Avoid it, or swap to an ecosystem-validated equivalent.
    - If a non-validated provider is genuinely unavoidable, you MUST declare it: set the manifest `[fips]` table to `status = "uses-nonvalidated"` with a `reason` (see Step 4). Conformance verifies the declaration against a scan of your plugin's shipped artifacts + declared deps; a FIPS deployment then requires a justified operator `fips_waivers` entry to run your plugin. A plugin can never silently opt itself out. When in doubt, run `manage.py validate_plugin plugins/<slug> --level structure` and read the `crypto-providers` check.
- **Tier 1 — load/registration order → manifest `depends_on`.** If your plugin *imports* another plugin (`from tap_plugin.<other> import …`), declare that edge:
  ```toml
  depends_on = [
    { slug = "<other>", note = "why — e.g. imports its models/panels at import time" },
    # optional: min_version = "0.2.0", optional = true
  ]
  ```
  The pre-boot **consistency gate fails closed** if you import a plugin you didn't declare (declared ⊇ observed), if a declared dep isn't installed before you, or if a min-version is unmet. So: import a plugin → declare it. The `note` is AI-/security-readable intent — always write one.
- **Tier 2 — runtime DATA order (you read nodes another plugin's *collector* produced) → stays PROFILE-EXPLICIT.** This is NOT a `depends_on` — the import graph can't see data deps, and conflating them produces a confidently-wrong picture. Order the fire-collector steps in the boot profile and document why (samsite reads `aws_core` nodes this way — profile order, not a manifest edge).

After scaffolding, `manage.py plugins` (the read-only report, gated by `plugins.read`) shows your plugin's identity, surfaces, load health, and both dependency directions (`depends_on` + `required_by`) — use it to confirm the plugin loaded and its edges are what you expect.

## Step 5: Create Models

For each model the plugin needs, follow the **[`add-model`](../../../tap_grid/skills/add-model/SKILL.md) skill**. It is the canonical procedure for adding a TAP-managed BaseModel — file layout, required class variables, dual-schema contract, manifest registration, migrations, spec sync, and tests are all covered there.

Within plugin scaffolding, complete the skill's Step 1 (shape) and Step 2 (model file) for every model before moving on. Step 4 (manifest registration), Step 5 (migrations), and Step 8 (tests) typically run once at the end of plugin scaffolding rather than once per model.

Re-export every model from `models/__init__.py` using the namespace path so `from tap_plugin.<slug>.models import <Model>` works (e.g. `from tap_plugin.<slug>.models.foo import Foo`).

## Step 6: Create Edge Definitions

For each edge type the plugin needs, follow the **[`add-edge`](../../../tap_grid/skills/add-edge/SKILL.md) skill**. It is the canonical procedure for adding an edge type — `.edge.json` file shape, source/target rules, property schema design (especially enums), manifest registration, default dimensions, and tests are all covered there.

Within plugin scaffolding, complete the skill's Step 1 (shape) and Step 2 (edge file) for every edge before moving on. Step 3 (manifest registration) and Step 7 (tests) typically run once at the end of plugin scaffolding rather than once per edge.

## Step 7: Create GRIFT Seed Data (if applicable)

If the plugin includes reference data that should be pre-loaded, create GRIFT files in `grift/`.

Read `tap_grid/specs/spec-grift-v0.md` for the format. Validate against `tap_grid/schemas/grift-document.schema.json`.

Use deterministic entity IDs where repeated imports should upsert cleanly. If the repo does not yet have an approved pattern for the plugin, flag that gap rather than inventing an unstable ID scheme silently.

### Iterating on GRIFT content

GRIFT batches are idempotent by `batch_entity.entity_id` — editing a file in place and re-running the importer does nothing. When you need to revise content, pick one of two canonical paths:

- **Version bump (always valid, required for release).** Create a new batch with a fresh `batch_entity.entity_id` and a bumped name (`v0.1.0` → `v0.2.0`). Node and edge entity_ids inside the batch stay stable so upsert applies. This is the path whenever the change ships, whenever you're outside `DEBUG=True`, and whenever you want the batch history to read as a coherent progression.
- **Force re-import (dev iteration only, DEBUG-gated).** Use `import_plugin_grift <plugin> --force-batches=<batch_id>` to re-apply the same batch without changing its id. Add `--purge` to hard-delete ephemeral orphans. Add `--sweep-strict` to abort if any orphan can't be cleanly swept. All permitted if and only if `DEBUG=True`.

Canonical guidance lives in [`tap_plugins/specs/spec-tap-plugin-architecture.md`](../../tap_plugins/specs/spec-tap-plugin-architecture.md) under *Iterative Development* (`req-tap-plugin-arch-iterative-dev`). The underlying requirements — force re-import, batch-scoped sweep, sweep purge — are defined in [`tap_grid/specs/spec-grid-import-grift.md`](../../tap_grid/specs/spec-grid-import-grift.md).

Do not silently edit grift content and re-run the importer without picking one of the two paths above; the edit will be ignored and you'll waste time debugging an absence of change.

## Step 8: Create Icons

Read `tap_grid/specs/spec-grid-icon.md` for the full icon contract.

Icons are optional but strongly encouraged. If the user hasn't specified icon requirements, ask them:

- Should icons use vendor brand colors (e.g. official AWS/GCP icons) or TAP's `currentColor` convention?
- Are there official icon assets available for this domain?
- Which models should share icon keys?

Every model that declares `ENTITY_ICON` must have a corresponding SVG at `static/<slug>/icons/<icon-key>.svg`. Icon keys must be kebab-case.

## Step 9: Create Tests

Create `tests/test_<slug>_manifest.py` for plugin validation system tests:

```python
from pathlib import Path
import pytest
from tap_plugins.validate.service import validate_plugin

PLUGIN_ROOT = Path(__file__).resolve().parent.parent

class TestStructure:
    def test_structure_passes(self):
        result = validate_plugin(PLUGIN_ROOT, level="structure")
        assert result.ok, result.to_human()

    def test_strict_passes(self):
        result = validate_plugin(PLUGIN_ROOT, level="structure", strict=True)
        assert result.ok, result.to_human()
```

Note: `loads` and `runs` level tests require the plugin to be installed + loaded (editable-installed and listed in a booted profile's `install` section, so it lands in `TAP_PLUGINS`). Structure-level tests work standalone.

Create additional test files for domain-specific behavior. Name test files after what they test — `test_<slug>_edges.py`, `test_<slug>_defaults.py`, etc. — not always `_models.py`.

Do not re-implement structural or smoke tests that the centralized plugin validation system already covers.

## Step 10: Validate

Validate in layers — structure first (no Django), then the real package-mode install + boot gates:

1. **Structure** (no Django) — manifest, paths, edge files, directory structure:
   ```bash
   python -m tap_plugins.validate_plugin plugins/<slug>/tap_plugin/<slug>
   ```
2. **Editable install + pre-boot gates** — install the package and run pre-boot for a profile that lists it in its `install` section. This exercises the conformance gate (slug/dist/entry-key/namespace agree), the reconciliation guard (installed == declared), and the dependency consistency gate (declared ⊇ observed imports, order, min-version):
   ```bash
   scripts/dc exec -T web uv pip install --editable plugins/<slug>
   scripts/dc exec -T web uv run --no-sync python -m tap.preboot --profile <profile>
   ```
3. **Report** — confirm the plugin loaded, its surfaces registered, and its dependency edges are correct:
   ```bash
   scripts/dc exec -T web uv run --no-sync python manage.py plugins   # (--json for the machine view)
   ```

Fix any gate failure before proceeding — they fail closed by design. Structure-level validation confirms manifest/import/path correctness but does not prove DB tables/migration state; the report + a `migrate` do.

## Step 11: Update Plugin Documentation

Update root `README.md` so it is useful to a future developer or AI agent landing directly in the plugin. Cover:

- What the plugin does (1-2 sentences)
- What this plugin owns versus what remains in TAP core or sibling plugins
- Resource types modeled (organized by category)
- Edge types
- Collector, receiver, emitter, or schedule behavior, if any
- GRIFT seed data and import expectations, if any
- Important specs and source files to read before editing
- How to install (add to a boot profile `install` section as an editable source; `uv pip install --editable`; `migrate`) — not submodules, not `INSTALLED_APPS`
- How to validate (`python -m tap.preboot --profile <profile>` for the gates; `manage.py plugins` for the report)
- Pointer to `specs/` for detailed documentation

Create or update `docs/` files for operational setup, runbooks, generated inventories, and longer implementation notes. The root README should point into those docs rather than absorbing all details.

## Step 12: Wire Into A Boot Profile And Commit

Package-mode plugins load via the boot profile's `install` section, **not** `INSTALLED_APPS` and **not** a submodule. To integrate:

1. Add an `install` entry to the relevant boot profile(s) — including `boot/test_all.boot.json` (the test/gate union the full lane boots, so your plugin's tests are discoverable) and any other profile the test/dev container boots, so pre-boot's reconciliation guard doesn't fail closed on an installed-but-undeclared plugin:
   ```json
   { "slug": "<slug>", "enabled": true, "source": { "type": "editable", "path": "plugins/<slug>" },
     "note": "<what it is; install-only vs seeded>" }
   ```
   If the plugin ships GRIFT seed data, also add a `population` `seed-plugin` step. If it declares Tier-1 `depends_on`, list it in the `install` section **after** its dependencies (deps before dependents — the gate checks this).
2. Commit the plugin in the monorepo (it is not a separate repo during the monorepo phase):
   ```bash
   git add plugins/<slug> boot/<profile>.boot.json
   git commit -m "feat(plugins): add <Display Name> plugin (package-mode)"
   ```

Do NOT hardcode the plugin in `settings.INSTALLED_APPS` — that is the legacy build-baked path (`BUILD_BAKED_PLUGIN_SLUGS` is now empty; every plugin is package-mode). The pre-boot stage splices installed plugins into `INSTALLED_APPS` via `TAP_PLUGINS`.

This step is intentionally late, but the author may commit partial progress earlier, especially once the initial spec exists.

## Step 13: Update Specification

Go back to the spec and update all requirement statuses to reflect what was implemented. The spec must stay in sync with the code — spec drift is a bug.
